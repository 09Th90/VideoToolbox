# @version 2.2.5
"""ASR 链路（自研，替代 videocaptioner.core.asr 的转写执行部分）。

P2 接缝：把第三方引擎的 ASR 执行链迁到本项目自有代码——``WhisperAPI``
（OpenAI 兼容客户端）、``BaseASR``（CRC32 + 磁盘缓存 + 模板方法）、
分块与合并组件（``ChunkedASR`` + ``ChunkMerger``）、``transcribe`` 编排。

P2 之前的形态
-------------
v1.19.x 及以前，本项目只把 ASR **配置**写进引擎 settings.json
（``video_toolbox.apply_asr_to_engine()``），执行仍由引擎完成 ⇒ 依赖未消除。

编写依据
--------
按规格风险约束 1，本模块基于**接口契约 + 可观察行为**编写，未复制第三方实现：

* 接口契约：类名、构造/方法签名、异常类型、缓存键构造形式；
* 可观察行为：CRC32 文件标识、缓存键拼接、分块几何（10 分钟 / 10 秒重叠 /
  并发 3）、合并算法（滑动窗口最佳对齐 → 中点切分）、失败语义。
* 本项目既有能力：``tools/ai_client.py`` 的单通道 base/key/model、
  ``calib_media_agent._multipart_post`` 的 multipart 上传、
  ``engine_cache`` 的惰性缓存、``engine_asr_data`` 的数据模型。

设计约束
--------
1. **缓存键与 expire 是持久化契约**。引擎已落盘的 ASR 缓存键形如
   ``WhisperAPI:{crc32}-{model}-{language}-{prompt}``，expire 为 2 天。
   键或 expire 变了 ⇒ 全部历史缓存失效、同一段音频被重复计费转写。
   故 ``_get_key`` / ``run`` 的拼接形式与 expire 常量必须逐字一致。
2. **分块几何是行为契约**：长视频靠「分块 + 重叠 + 去重合并」才能转录。
   几何参数变动会同时影响**时间轴正确性**与**去重质量**，因此以具名常量
   固化，并在自检里锁死。
3. **零强制第三方依赖**：``pydub``（解码/切块）与 ``openai``（SDK）都是
   可选——缺失时降级为 ffmpeg 切块 / 原生 urllib 上传，而不是崩掉。
   faster-whisper（MIT 组件）作为 local 模式的实现保留为可选增强。
4. **失败必须显式**：不静默返回空结果。
"""

from __future__ import annotations

import difflib
import io
import os
import threading
import time
import uuid
import zlib
from concurrent.futures import ThreadPoolExecutor
from enum import Enum
from typing import Callable, Optional

from engine_asr_data import ASRData, ASRDataSeg
from engine_cache import CacheHub, is_cache_enabled

__all__ = [
    "BaseASR",
    "WhisperAPI",
    "ChunkedASR",
    "ChunkMerger",
    "transcribe",
    "ASRStatus",
    "CHUNK_LENGTH_SEC",
    "CHUNK_OVERLAP_SEC",
    "CHUNK_CONCURRENCY",
    "ASR_CACHE_EXPIRE",
    "set_cache_hub",
]


class ASRStatus(Enum):
    """转写进度阶段（消息 + 百分比）。

    百分比是**界面进度条与用户预期对齐**的依据：分块转录下「上传」
    只占很小一段，真正的等待在「转写中」，故 TRANSCRIBING 定在 60
    而非 10——避免进度条长时间停在开头看起来像卡死。
    """

    INITIALIZING = ("initializing", 0)
    CONVERTING_AUDIO = ("converting_audio", 5)
    UPLOADING = ("uploading", 10)
    UPLOAD_PART = ("upload_part", 20)
    UPLOAD_COMMIT = ("upload_commit", 30)
    UPLOAD_COMPLETE = ("upload_complete", 40)
    CREATING_TASK = ("creating_task", 40)
    TASK_CREATED = ("task_created", 50)
    SUBMITTING = ("submitting", 50)
    TRANSCRIBING = ("transcribing", 60)
    PROCESSING = ("processing", 70)
    QUERYING_RESULT = ("querying_result", 80)
    PARSING_RESULT = ("parsing_result", 90)
    FINALIZING = ("finalizing", 95)
    COMPLETED = ("completed", 100)

    @property
    def message(self) -> str:
        return self.value[0]

    @property
    def progress(self) -> int:
        return self.value[1]

    def with_progress(self, progress: int):
        """返回 ``(进度, 消息)``，与 ``callback(progress, message)`` 对齐。"""
        return (progress, self.message)

    def callback_tuple(self):
        return (self.progress, self.message)

# ============ 分块几何（行为契约，自检会锁死）============
#: 单块长度（秒）。长音频靠分块绕过 API 超时与内存上限。
CHUNK_LENGTH_SEC = 60 * 10
#: 相邻块重叠（秒）。重叠是「去重合并」能对齐的前提——没有重叠就没有
#: 可匹配的重复文本，合并只能退化���时间边界硬切，字幕会出现重复句。
CHUNK_OVERLAP_SEC = 10
#: 并发块数。本地转录（faster-whisper / whisper-cpp）固定单线程。
CHUNK_CONCURRENCY = 3

#: ASR 缓存有效期（秒，2 天）。与引擎一致，改动会让历史缓存全部失效。
ASR_CACHE_EXPIRE = 86400 * 2

_MS_PER_SEC = 1000

#: 进程内共享的缓存工厂。由宿主（``video_toolbox.vc_lazy_cache_patch`` 建的
#: hub）通过 :func:`set_cache_hub` 注入；未注入时本模块按需自建一个到
#: ``<data>/VideoCaptioner/cache``。
#:
#: 为什么用注入而不是各自 new：引擎的 ``BaseASR`` 与翻译器共用 asr 缓存目录，
#: 若这里另起一个 hub，会与引擎那份形成两套实例（同一目录、两个连接）⇒
#: 限流记录与缓存统计对不上。
_CACHE_HUB = None


def set_cache_hub(hub):
    """注入缓存工厂（幂等）。返回传入的 hub。"""
    global _CACHE_HUB
    _CACHE_HUB = hub
    return hub


def _cache_hub():
    """取缓存工厂；未注入时按需自建。"""
    global _CACHE_HUB
    if _CACHE_HUB is None:
        import tempfile
        _CACHE_HUB = CacheHub(os.path.join(tempfile.gettempdir(),
                                           "vt_asr_cache"))
    return _CACHE_HUB


#: ffmpeg 定位（可选，用于 pydub 缺失时的切块兜底）。宿主可注入精确路径。
_FFMPEG = None


def set_ffmpeg(path):
    """注入 ffmpeg 路径（可选增强）。"""
    global _FFMPEG
    _FFMPEG = path
    return path


def _find_ffmpeg():
    """定位 ffmpeg：注入值 → 环境变量 → PATH。找不到返回 ``None``。"""
    if _FFMPEG:
        return _FFMPEG
    import shutil
    from_env = os.environ.get("VT_FFMPEG") or os.environ.get("FFMPEG_PATH")
    if from_env and os.path.isfile(from_env):
        return from_env
    return shutil.which("ffmpeg")


def _now():
    return time.time()


# =========================================================
# BaseASR：音频加载 + CRC32 + 磁盘缓存 + 模板方法
# =========================================================
class BaseASR:
    """ASR 基类。

    子类只需实现 :meth:`_run`（执行转写，返回原始响应 dict）与
    :meth:`_make_segments`（把响应转成 ``ASRDataSeg`` 列表）。

    关键契约
    --------
    * ``crc32_hex``：音频内容 CRC32（8 位小写 hex），是缓存键的组成部分。
      用**内容**而非路径 ⇒ 同一段音频换文件名仍命中缓存。
    * 缓存键 = ``f"{类名}:{子键}"``，expire = :data:`ASR_CACHE_EXPIRE`。
    """

    #: 支持的音频容器格式（按扩展名判定）
    SUPPORTED_SOUND_FORMAT = ("flac", "m4a", "mp3", "wav")

    _lock = threading.Lock()

    def __init__(self, audio_input=None, use_cache=False,
                 need_word_time_stamp=False):
        self.audio_input = audio_input
        self.file_binary = None
        self.use_cache = use_cache
        self.need_word_time_stamp = need_word_time_stamp
        self._set_data()
        self._cache = _cache_hub().get("asr")
        self.audio_duration = self._get_audio_duration()

    # ---------- 音频载入 ----------
    def _set_data(self):
        """载入音频字节并算出 CRC32。"""
        if isinstance(self.audio_input, (bytes, bytearray)):
            self.file_binary = bytes(self.audio_input)
        elif isinstance(self.audio_input, str):
            ext = self.audio_input.rsplit(".", 1)[-1].lower() if "." in \
                self.audio_input else ""
            if ext not in self.SUPPORTED_SOUND_FORMAT:
                raise ValueError("Unsupported sound format: %s" % ext)
            if not os.path.exists(self.audio_input):
                raise FileNotFoundError("File not found: %s" % self.audio_input)
            with open(self.audio_input, "rb") as f:
                self.file_binary = f.read()
        else:
            raise ValueError("audio_input must be provided as string or bytes")
        self.crc32_hex = format(zlib.crc32(self.file_binary) & 0xFFFFFFFF, "08x")

    def _get_audio_duration(self) -> float:
        """音频时长（秒）。

        探测失败时返回 10 分钟兜底——引擎同款。返回值只用于限流统计，
        兜底偏大会让限流判定偏保守，可接受。
        """
        if not self.file_binary:
            return 0.01
        try:
            return _probe_duration(self.file_binary)
        except Exception:  # noqa: BLE001
            return 60.0 * 10

    # ---------- 模板方法 ----------
    def run(self, callback: Optional[Callable[[int, str], None]] = None,
            **kwargs) -> ASRData:
        """执行转写（带缓存）。

        缓存键 ``f"{类名}:{子键}"``；命中直接返回，未命中则执行并写入缓存。
        """
        cache_key = "%s:%s" % (type(self).__name__, self._get_key())

        if self.use_cache and is_cache_enabled():
            cached = self._cache.get(cache_key, default=None)
            if cached is not None:
                if callback:
                    callback(100, "命中缓存")
                return ASRData(self._make_segments(cached))

        resp_data = self._run(callback, **kwargs)
        # 缓存失败不影响主流程：宁可慢一次，也不能让转写整体失败
        try:
            self._cache.set(cache_key, resp_data, expire=ASR_CACHE_EXPIRE)
        except Exception:  # noqa: BLE001
            pass
        return ASRData(self._make_segments(resp_data))

    def _get_key(self) -> str:
        """子类缓存键的**子键**部分（默认用文件 CRC32）。"""
        return self.crc32_hex

    def _make_segments(self, resp_data: dict):
        raise NotImplementedError("_make_segments must be implemented")

    def _run(self, callback=None, **kwargs) -> dict:
        raise NotImplementedError("_run must be implemented")

    # ---------- 公益服务限流 ----------
    RATE_LIMIT_MAX_CALLS = 100
    RATE_LIMIT_MAX_DURATION = 360 * 60
    RATE_LIMIT_TIME_WINDOW = 12 * 3600

    def _check_rate_limit(self) -> None:
        """公益服务限流（调用次数 + 总时长双阈值）。"""
        service_name = type(self).__name__
        tag = "rate_limit:%s" % service_name
        time_limit = _now() - self.RATE_LIMIT_TIME_WINDOW

        durations = []
        try:
            results = self._cache._sql(
                "SELECT key FROM Cache WHERE tag = ? AND store_time >= ?",
                (tag, time_limit)).fetchall()
            for (key,) in results:
                v = self._cache.get(key, default=None)
                if isinstance(v, (int, float)):
                    durations.append(v)
        except Exception as e:  # noqa: BLE001
            raise RuntimeError("Failed to query rate limit: %s" % e)

        total_duration = sum(durations)
        if total_duration + self.audio_duration > self.RATE_LIMIT_MAX_DURATION:
            raise RuntimeError("%s duration limit exceeded" % service_name)
        if len(durations) >= self.RATE_LIMIT_MAX_CALLS:
            raise RuntimeError("%s call count limit exceeded" % service_name)

        self._cache.set(
            "rate_limit_record:%s:%s" % (service_name, uuid.uuid4()),
            self.audio_duration, tag=tag,
            expire=int(self.RATE_LIMIT_TIME_WINDOW) + 3600)


def _probe_duration(binary: bytes) -> float:
    """用 pydub 探测时长（可选依赖，缺失时抛异常由调用方兜底）。"""
    from pydub import AudioSegment
    return AudioSegment.from_file(io.BytesIO(binary)).duration_seconds


# =========================================================
# WhisperAPI：OpenAI 兼容 /audio/transcriptions 客户端
# =========================================================
class WhisperAPI(BaseASR):
    """OpenAI 兼容 ASR 客户端。

    协议（``/audio/transcriptions``）：
      · body 为 multipart：``model`` / ``response_format=verbose_json`` /
        ``file`` / ``prompt`` / ``timestamp_granularities=["word","segment"]``；
      · 语言为空字符串表示自动检测 ⇒ **不传** ``language`` 参数让服务端判断；
      · ``verbose_json`` 响应含 ``segments``（句级）与可选 ``words``（词级）；
      · ``response_format`` 若被服务端忽略而返回字符串 ⇒ 端点不对，
        抛 ``ValueError`` 而不是当结果用。
    """

    def __init__(self, audio_input=None, whisper_model="whisper-1",
                 need_word_time_stamp=False, language="zh", prompt="",
                 base_url="", api_key="", use_cache=False):
        super().__init__(audio_input, use_cache, need_word_time_stamp)
        self.base_url = _normalize_base_url(base_url)
        self.api_key = (api_key or "").strip()
        if not self.base_url or not self.api_key:
            raise ValueError("Whisper BASE_URL and API_KEY must be set")
        self.model = whisper_model
        self.language = language
        self.prompt = prompt or ""

    def _get_key(self) -> str:
        """子键 = CRC32-模型-语言-提示词（与引擎一致，见模块级契约说明）。"""
        return "%s-%s-%s-%s" % (self.crc32_hex, self.model, self.language,
                                self.prompt)

    def _make_segments(self, resp_data: dict):
        """响应 → segments。词级优先（``need_word_time_stamp`` 且响应含 words）。"""
        if self.need_word_time_stamp and isinstance(resp_data, dict) \
                and "words" in resp_data:
            return [ASRDataSeg(
                text=w["word"],
                start_time=int(float(w["start"]) * 1000),
                end_time=int(float(w["end"]) * 1000))
                for w in resp_data["words"]]
        return [ASRDataSeg(
            text=str(seg["text"]).strip(),
            start_time=int(float(seg["start"]) * 1000),
            end_time=int(float(seg["end"]) * 1000))
            for seg in resp_data["segments"]]

    #: 单次转写请求超时（秒）。长音频靠分块规避长请求，故不必很大。
    REQUEST_TIMEOUT = 300

    def _submit(self) -> dict:
        from engine_asr_http import post_transcription
        prompt = self.prompt
        # 中文且无提示词时给一句引导，提升简体中文准确率（引擎既有行为）
        if self.language == "zh" and not prompt:
            prompt = "你好，我们需要使用简体中文，以下是普通话的句子"
        return post_transcription(
            base_url=self.base_url, api_key=self.api_key, model=self.model,
            audio_bytes=self.file_binary, prompt=prompt,
            language="" if not self.language else self.language,
            need_word_time_stamp=self.need_word_time_stamp,
            timeout=self.REQUEST_TIMEOUT)

    def _run(self, callback: Optional[Callable[[int, str], None]] = None,
             **kwargs) -> dict:
        if callback:
            callback(10, "提交转写请求")
        return self._submit()


def _normalize_base_url(base_url: str) -> str:
    """规整 base_url：补 ``/v1``、去尾斜杠（OpenAI SDK 惯例）。"""
    u = (base_url or "").strip().rstrip("/")
    if not u:
        return ""
    if not u.endswith("/v1") and "/v1/" not in u + "/":
        # 已是完整端点（含 /audio 等）则不动，否则补 /v1
        if "/audio/" not in u:
            u += "/v1"
    return u


# =========================================================
# 分块与合并组件（单一组件：ChunkedASR + ChunkMerger）
# =========================================================
class ChunkMerger:
    """分块结果合并器：滑动窗口找最佳对齐，在重叠区域**中点**切分。

    匹配策略（依据是否为词级时间戳自动选择）
    ----------------------------------------
    * 词级（字级时间戳）→ **精确**文本匹配；
    * 句级 → ``difflib`` 模糊匹配，相似度 > ``fuzzy_threshold``（0.7）。

    为什么在中点切：重叠区里左右两侧说的是同一段话，任一点切都会让某一半
    字幕的时间戳落到错误的块上；中点对时间误差最不敏感。
    """

    def __init__(self, min_match_count: int = 2,
                 fuzzy_threshold: float = 0.7):
        self.min_match_count = min_match_count
        self.fuzzy_threshold = fuzzy_threshold
        self._is_word_level = False

    def merge_chunks(self, chunks, chunk_offsets=None,
                     overlap_duration: int = CHUNK_OVERLAP_SEC * _MS_PER_SEC):
        """合并多个块的结果（各块 segments 的时间戳从 0 起算）。"""
        if not chunks:
            raise ValueError("chunks must not be empty")
        if len(chunks) == 1:
            return chunks[0]

        self._is_word_level = any(
            c.is_word_timestamp() for c in chunks if c.has_data())

        if chunk_offsets is None:
            chunk_offsets = self._infer_chunk_offsets(chunks, overlap_duration)
        if len(chunks) != len(chunk_offsets):
            raise ValueError(
                "chunks 数量 (%d) 与 chunk_offsets 数量 (%d) 不匹配"
                % (len(chunks), len(chunk_offsets)))

        adjusted = [self._adjust_timestamps(c.segments, off)
                    for c, off in zip(chunks, chunk_offsets)]

        merged = adjusted[0]
        for i in range(1, len(adjusted)):
            merged = self._merge_two_sequences(
                merged, adjusted[i], overlap_duration)
        return ASRData(merged)

    # ---------- 内部 ----------
    def _merge_two_sequences(self, left, right, overlap_duration):
        if not left:
            return right
        if not right:
            return left
        left_len = len(left)

        left_overlap = self._extract_overlap_segments(
            left, from_end=True, duration=overlap_duration)
        right_overlap = self._extract_overlap_segments(
            right, from_end=False, duration=overlap_duration)
        if not left_overlap or not right_overlap:
            return left + right

        best = self._find_best_alignment(left_overlap, right_overlap)
        if best is None:
            # 无有效匹配 ⇒ 退化为「时间边界切分」：在 right 起点处断开
            split_idx = left_len
            right_start = right[0].start_time
            for i in range(left_len - 1, -1, -1):
                if left[i].end_time <= right_start:
                    split_idx = i + 1
                    break
            return left[:split_idx] + right

        ls, _le, rs, _re, _m = best
        left_mid = (ls + _le) // 2
        right_mid = (rs + _re) // 2
        left_overlap_offset = left_len - len(left_overlap)
        left_cut = left_overlap_offset + left_mid
        return left[:left_cut] + right[right_mid:]

    def _find_best_alignment(self, left, right):
        """滑动窗口找最佳对齐（返回 (左起, 左止, 右起, 右止, 匹配数) 或 None）。"""
        left_len, right_len = len(left), len(right)
        best_score, best_result = 0.0, None

        for i in range(1, left_len + right_len + 1):
            epsilon = float(i) / 10000.0     # 偏好更长匹配
            left_start = max(0, left_len - i)
            left_end = min(left_len, left_len + right_len - i)
            right_start = max(0, i - left_len)
            right_end = min(right_len, i)

            left_slice = left[left_start:left_end]
            right_slice = right[right_start:right_end]
            if len(left_slice) != len(right_slice):  # 数学上恒等，作不变量断言
                raise RuntimeError("对齐Error: %d vs %d"
                                   % (len(left_slice), len(right_slice)))

            if self._is_word_level:
                matches = sum(1 for a, b in zip(left_slice, right_slice)
                              if a.text == b.text)
            else:
                matches = sum(
                    1 for a, b in zip(left_slice, right_slice)
                    if difflib.SequenceMatcher(None, a.text, b.text).ratio()
                    > self.fuzzy_threshold)

            score = matches / float(i) + epsilon
            if matches >= self.min_match_count and score > best_score:
                best_score = score
                best_result = (left_start, left_end, right_start, right_end,
                               matches)
        return best_result

    @staticmethod
    def _adjust_timestamps(segments, offset):
        return [ASRDataSeg(text=s.text,
                           start_time=s.start_time + offset,
                           end_time=s.end_time + offset,
                           translated_text=s.translated_text)
                for s in segments]

    @staticmethod
    def _extract_overlap_segments(segments, from_end: bool, duration: int):
        """取重叠区 segments（从末尾往前 / 从开头往后）。"""
        if not segments:
            return []
        out = []
        if from_end:
            threshold = segments[-1].end_time - duration
            for seg in reversed(segments):
                if seg.start_time >= threshold:
                    out.insert(0, seg)
                else:
                    break
        else:
            threshold = segments[0].start_time + duration
            for seg in segments:
                if seg.end_time <= threshold:
                    out.append(seg)
                else:
                    break
        return out

    @staticmethod
    def _infer_chunk_offsets(chunks, overlap_duration):
        offsets = [0]
        for i in range(1, len(chunks)):
            prev = chunks[i - 1]
            if prev.segments:
                prev_end = prev.segments[-1].end_time
                nxt = offsets[-1] + prev_end - overlap_duration
                offsets.append(max(nxt, offsets[-1]))
            else:
                offsets.append(offsets[-1])
        return offsets


class ChunkedASR:
    """分块转录包装器：长音频切片 → 并发转录 → 合并去重。

    分块几何由 :data:`CHUNK_LENGTH_SEC` / :data:`CHUNK_OVERLAP_SEC` /
    :data:`CHUNK_CONCURRENCY` 固化（行为契约，见模块级说明）。
    """

    def __init__(self, asr_class, audio_path: str, asr_kwargs=None,
                 chunk_length: int = CHUNK_LENGTH_SEC,
                 chunk_overlap: int = CHUNK_OVERLAP_SEC,
                 chunk_concurrency: int = CHUNK_CONCURRENCY):
        self.asr_class = asr_class
        self.audio_path = audio_path
        self.asr_kwargs = dict(asr_kwargs or {})
        self.chunk_length_ms = int(chunk_length) * _MS_PER_SEC
        self.chunk_overlap_ms = int(chunk_overlap) * _MS_PER_SEC
        self.chunk_concurrency = int(chunk_concurrency)
        with open(audio_path, "rb") as f:
            self.file_binary = f.read()

    def run(self, callback: Optional[Callable[[int, str], None]] = None):
        chunks = self._split_audio()
        # 单块 ⇒ 不必切片，直接整段转录（省一次编解码）
        if len(chunks) == 1:
            return self.asr_class(self.audio_path,
                                  **self.asr_kwargs).run(callback)

        results = self._transcribe_chunks(chunks, callback)
        return self._merge_results(results, chunks)

    # ---------- 切块 ----------
    def _split_audio(self):
        """切成 ``[(块字节, 偏移毫秒)]``，相邻块保留 :data:`CHUNK_OVERLAP_SEC`。"""
        if self.file_binary is None:
            raise ValueError("file_binary is None, cannot split audio")
        total_ms, cut = _audio_duration_and_cut(self.audio_path,
                                                self.file_binary)
        chunks, start_ms = [], 0
        while start_ms < total_ms:
            end_ms = min(start_ms + self.chunk_length_ms, total_ms)
            data = cut(start_ms, end_ms)
            if data:
                chunks.append((data, start_ms))
            start_ms += self.chunk_length_ms - self.chunk_overlap_ms
            if end_ms >= total_ms:
                break
        if not chunks:                       # 极短/异常音频兜底
            chunks = [(self.file_binary, 0)]
        return chunks

    # ---------- 并发转录 ----------
    def _transcribe_chunks(self, chunks, callback):
        results = [None] * len(chunks)
        total = len(chunks)
        chunk_progress = [0] * total
        lock = threading.Lock()
        state = {"last": 0}

        def run_one(idx, chunk_bytes, offset_ms):
            def chunk_cb(progress, message):
                if not callback:
                    return
                with lock:
                    chunk_progress[idx] = progress
                    overall = sum(chunk_progress) // total
                    # 进度只允许单调递增：回退会让进度条「倒退」，看起来像卡死
                    if overall > state["last"]:
                        state["last"] = overall
                        callback(overall, "%d/%d: %s" % (idx + 1, total,
                                                        message))

            inst = self.asr_class(chunk_bytes, **self.asr_kwargs)
            return idx, inst.run(chunk_cb)

        with ThreadPoolExecutor(max_workers=self.chunk_concurrency) as pool:
            futures = [pool.submit(run_one, i, b, off)
                       for i, (b, off) in enumerate(chunks)]
            for fut in futures:
                idx, data = fut.result()
                results[idx] = data
        return [r for r in results if r is not None]

    def _merge_results(self, chunk_results, chunks):
        merger = ChunkMerger(min_match_count=2, fuzzy_threshold=0.7)
        return merger.merge_chunks(
            chunks=chunk_results,
            chunk_offsets=[off for _, off in chunks],
            overlap_duration=self.chunk_overlap_ms)


# =========================================================
# transcribe：编排入口
# =========================================================
def transcribe(audio_path: str, config, callback=None) -> ASRData:
    """按配置执行转写。

    非词级时间戳时额外调用 ``optimize_timing()`` 收敛字幕时长——引擎既有
    行为：句级时间戳的条目普遍偏长，直接出字幕会显得「字还没说完就切走」。
    """
    if callback is None:
        def callback(_p, _m):
            return None

    if getattr(config, "transcribe_model", None) is None:
        raise ValueError("Transcription model not set")

    asr = _create_asr_instance(audio_path, config)
    data = asr.run(callback=callback)
    if not getattr(config, "need_word_time_stamp", False):
        data.optimize_timing()
    return data


def _create_asr_instance(audio_path: str, config):
    """按 ``transcribe_model`` 构造（带分块包装的）ASR 实例。"""
    from engine_entities import TranscribeModelEnum
    model = config.transcribe_model

    if model == TranscribeModelEnum.WHISPER_API:
        kwargs = {
            "use_cache": True,
            "need_word_time_stamp": config.need_word_time_stamp,
            "language": config.transcribe_language,
            "whisper_model": config.whisper_api_model or "whisper-1",
            "api_key": config.whisper_api_key or "",
            "base_url": config.whisper_api_base or "",
            "prompt": config.whisper_api_prompt or "",
        }
        return ChunkedASR(asr_class=WhisperAPI, audio_path=audio_path,
                          asr_kwargs=kwargs)

    if model == TranscribeModelEnum.FASTER_WHISPER:
        from engine_asr_local import FasterWhisperASR
        kwargs = {
            "use_cache": True,
            "need_word_time_stamp": config.need_word_time_stamp,
            "language": config.transcribe_language,
            "whisper_model": (
                config.faster_whisper_model.value
                if config.faster_whisper_model else "base"),
            "model_dir": config.faster_whisper_model_dir or "",
            "device": config.faster_whisper_device,
            "vad_filter": config.faster_whisper_vad_filter,
            "vad_threshold": config.faster_whisper_vad_threshold,
            "vad_method": (
                config.faster_whisper_vad_method.value
                if config.faster_whisper_vad_method else ""),
            "ff_mdx_kim2": config.faster_whisper_ff_mdx_kim2,
            "one_word": config.faster_whisper_one_word,
            "prompt": config.faster_whisper_prompt,
        }
        # 本地转录单线程（模型已占满算力，再并发只会互相抢）
        return ChunkedASR(asr_class=FasterWhisperASR, audio_path=audio_path,
                          asr_kwargs=kwargs, chunk_concurrency=1,
                          chunk_length=CHUNK_LENGTH_SEC * 2)

    raise ValueError("Invalid transcription model: %s" % model)


# =========================================================
# 音频切块底层（pydub 优先，缺失时用 ffmpeg）
# =========================================================
def _audio_duration_and_cut(audio_path: str, file_binary: bytes):
    """返回 ``(总时长毫秒, 切块函数)``。

    优先 pydub（引擎同款）；缺失时退到随包 ffmpeg。两条路都失败时抛异常，
    由调用方兜底成「整段当一块」。
    """
    try:
        from pydub import AudioSegment
        try:
            audio = AudioSegment.from_file(audio_path)
        except Exception:  # noqa: BLE001
            audio = AudioSegment.from_file(io.BytesIO(file_binary))
        total_ms = len(audio)

        def cut(start_ms, end_ms):
            buf = io.BytesIO()
            audio[start_ms:end_ms].export(buf, format="mp3")
            return buf.getvalue()

        return total_ms, cut
    except ImportError:
        pass

    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        # 没有解码器：无法可靠切块 ⇒ 整段当一块（长音频会超出 API 限制，
        # 但优于直接崩掉）
        return _bytes_duration_guess(file_binary), \
            lambda s, e: file_binary

    total_ms = _ffprobe_duration_ms(ffmpeg, audio_path) or \
        _bytes_duration_guess(file_binary)

    def cut_f(start_ms, end_ms):
        import subprocess
        import tempfile
        ss = start_ms / 1000.0
        dur = max(0.001, (end_ms - start_ms) / 1000.0)
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tf:
            out = tf.name
        try:
            subprocess.run(
                [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                 "-ss", "%.3f" % ss, "-t", "%.3f" % dur,
                 "-i", audio_path, "-f", "mp3", out],
                check=True, capture_output=True, timeout=600)
            with open(out, "rb") as f:
                return f.read()
        finally:
            try:
                os.unlink(out)
            except OSError:
                pass

    return total_ms, cut_f


def _find_ffmpeg():
    from engine_paths import _find_tool
    return _find_tool("ffmpeg")


def _ffprobe_duration_ms(ffmpeg, audio_path):
    import subprocess
    probe = ffmpeg.replace("ffmpeg", "ffprobe")
    if not os.path.isfile(probe):
        return None
    try:
        r = subprocess.run(
            [probe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", audio_path],
            capture_output=True, text=True, timeout=120)
        return int(float(r.stdout.strip()) * 1000)
    except Exception:  # noqa: BLE001
        return None


def _bytes_duration_guess(binary: bytes) -> int:
    """无解码器时的时长粗估（按 128kbps 估算，误差不影响正确性只影响切分）。"""
    return max(_MS_PER_SEC, int(len(binary) / (128 * 1000 / 8) * 1000))