# @version 2.9.0
"""本地 ASR（内置 faster-whisper 直连，替代外部 CLI 版）。

v2.8.1 BugFix（本轮）
--------------------
旧实现把音频交给随包的独立可执行程序（``faster-whisper-xxl`` /
``faster-whisper``）转成 SRT；但装机环境里这两个程序都不存在，``_resolve_program``
必然抛 ``EnvironmentError: faster-whisper-xxl 程序未找到``，本地转录链路**从未
跑通**。同时权重只在 HF 缓存里、GPU 侧缺 ``cublas64_12.dll``。本轮修复：

1. **不再依赖任何外部 exe**：直接用 ``faster_whisper.WhisperModel`` 加载并转写，
   产出的 SRT 文本仍走 ``_make_segments`` 解析（音乐标记 / 幻觉文本过滤契约不变）。
2. **自动定位工具箱模型**：``tools\\asr_model\\faster-whisper\\<model>``，
   由 :mod:`asr_local_paths` 按 frozen / 源码 / 自定义数据根三种形态解析；
   显式 ``model_dir`` 只有真的含完整权重才算命中（引擎会把该字段硬编码成空的
   ``data\\videocaptioner\\models``，不能让它顶掉真权重）。
3. **设备降级**：``cuda/float16`` 优先；缺 cuBLAS/cuDNN 时 GPU **加载**或
   **推理**任一阶段失败都 **自动降级** ``cpu/int8`` 并写日志（本机实测错误
   发生在推理阶段：模型能加载，``transcribe`` 才抛 cublas64_12.dll）；CPU 也
   失败则如实抛中文错误，绝不静默返回空结果、绝不静默切回云端。进程内记录
   GPU 不可用后，后续分块直接走 CPU，避免每块重复失败。
4. **完全离线**：``HF_HUB_OFFLINE=1`` + ``local_files_only=True``。

**缓存键是持久化契约**：``BaseASR.run`` 用 ``f"{类名}:{子键}"``、expire 2 天；
本类子键仍是 ``f"{crc32_hex}-{md5(str(self._build_command('')))}"``。
``_build_command`` 的**参数集合与顺序一字未改**——它是缓存键的一部分，勿随意
调整。``faster_whisper_program`` 现在固定为 :data:`EMBEDDED_PROGRAM_TAG`
（``faster-whisper-xxl``）：这只是**缓存键历史占位名**，不代表真的会执行外部
程序。迁移说明见交付文档：旧链路构造即抛异常，历史上不存在本地 ASR 缓存；
即便极端情况下存在，也只是重新转录一次，不会命中错位字幕。

**幻觉文本过滤是行为契约**：语音模型在长静音/纯音乐段会吐出固定套话
（「请不吝点赞 订阅 转发」这类），不滤掉就会出现在成片字幕里。

已知口径差异（内置直连 vs 外部 XXL）
------------------------------------
* ``--ff_mdx_kim2``（人声分离）内置 faster-whisper 不支持，会写日志说明并忽略，
  但仍参与缓存键（保留在 ``_build_command`` 中）。
* ``vad_method``（silero_v3/v4/...）在 faster-whisper 1.1.1 的 ``VadOptions`` 里
  **没有** ``method`` 字段，运行时探测后忽略并写日志；``vad_threshold`` 仍生效，
  参数仍参与缓存键。
* ``one_word`` 逐词字幕需要词级时间戳，仅在 ``need_word_time_stamp`` 为真时展开；
  否则按句级输出（避免中文音频被切成单字字幕）。
* 字幕落盘由上层任务完成；``output_dir`` / ``output_format`` 只参与缓存键。
"""

from __future__ import annotations

import hashlib
import inspect
import logging
import os
import re
import shutil
import tempfile
import threading
from typing import Callable, List, Optional, Tuple

import asr_local_paths
from engine_asr import BaseASR, ASRStatus
from engine_asr_data import ASRData, ASRDataSeg

__all__ = [
    "FasterWhisperASR",
    "HALLUCINATION_KEYWORDS",
    "is_rtx_50_series",
    "EMBEDDED_PROGRAM_TAG",
    "CPU_THREADS_CAP",
    "load_local_model",
    "mark_gpu_unusable",
    "reset_gpu_state",
    "clear_model_cache",
    "get_log_records",
    "clear_log_records",
]

#: 缓存键历史占位名（不是可执行程序）。保持它以使 ``_build_command`` 的参数
#: 集合与顺序逐字不变；``ff_mdx_kim2`` 分支也因此保持原有触发条件。
EMBEDDED_PROGRAM_TAG = "faster-whisper-xxl"

#: 幻觉文本关键词——语音模型在静音/音乐段常吐的固定套话。
#: 命中即整条丢弃（不是替换、不是降权：这些句子压根不是说话内容）。
HALLUCINATION_KEYWORDS = (
    "请不吝点赞 订阅 转发",
    "打赏支持明镜",
)

#: 音乐标记前缀（以这些符号开头的条目是音效标注，不是台词）
_MUSIC_PREFIXES = ("【", "[", "(", "（")

#: GPU 侧加载失败的典型特征（只用于日志措辞，不用于决定是否降级——
#: 任何 cuda 失败都降级，CPU 再失败才如实报错，不掩盖真实故障）。
_GPU_ERR_WORDS = ("cublas", "cudnn", "cuda", "cudart", "nvrtc",
                  "library", "gpu", "device")

_LOG_PREFIX = "[本地ASR] "
_LOG_RECORDS: List[str] = []
_LOG_LOCK = threading.Lock()

#: 进程内模型缓存：``ChunkedASR`` 多块时避免每块重新加载 3 GiB 权重。
#: key = (归一化模型目录, device, compute_type)。
_MODEL_CACHE = {}
_MODEL_CACHE_LOCK = threading.Lock()

#: CPU 线程上限。CTranslate2 默认 ``cpu_threads=0``（= 全部逻辑核），MKL 会按
#: 线程数分配工作区；实测本机 32 GiB 内存但仅约 4 GiB 可用时，large-v3 的
#: ``cpu/int8`` 直接 ``mkl_malloc: failed to allocate memory``（探针在内存宽裕
#: 时能加载，故属环境相关）。限制到 4 线程后同一份权重稳定可加载——
#: 「能跑」优先于「跑满核」，速度略降可接受。
CPU_THREADS_CAP = 4

#: 进程内「GPU 不可用」标记。cuBLAS/cuDNN 缺失时模型**能加载**、直到推理才
#: 抛错（本机实测：cuda/float16 下 WhisperModel 加载成功，transcribe 抛
#: ``Library cublas64_12.dll is not found``）。只在加载阶段降级是不够的，
#: 必须覆盖推理阶段；一旦确认 GPU 不可用，后续分块直接走 CPU，避免每块重试。
_GPU_UNUSABLE = False
_GPU_UNUSABLE_LOCK = threading.Lock()

#: 推理阶段 GPU 相关异常的特征词（区分「GPU 坏了」与「音频/模型坏了」）。
_GPU_INFER_ERR_WORDS = (
    "cublas", "cudnn", "cuda", "cudart", "nvrtc", "cublaslt",
    "not found or cannot be loaded", "out of memory", "gpu", "device")


def _is_gpu_error(exc: BaseException) -> bool:
    """异常是否属于 GPU/cuBLAS/cuDNN 运行库问题（决定是否降级重试）。"""
    text = ("%s %s" % (type(exc).__name__, exc)).lower()
    return any(word in text for word in _GPU_INFER_ERR_WORDS)


def mark_gpu_unusable(reason: str = "") -> None:
    """记录「本机 GPU 不可用」并清掉已缓存的 GPU 模型（幂等、写日志）。"""
    global _GPU_UNUSABLE
    with _GPU_UNUSABLE_LOCK:
        if _GPU_UNUSABLE:
            return
        _GPU_UNUSABLE = True
    _log("进程内已记录 GPU 不可用（%s）；后续本地转录直接走 CPU / int8，"
         "避免每个分块重复失败" % (reason or "推理阶段失败"))
    clear_model_cache()


def reset_gpu_state() -> None:
    """复位 GPU 状态并清模型缓存（自检用例隔离；用户装好 CUDA 库后重启即恢复）。"""
    global _GPU_UNUSABLE
    with _GPU_UNUSABLE_LOCK:
        _GPU_UNUSABLE = False
    clear_model_cache()


def _log(msg: str) -> None:
    """写运行日志（引擎 vc_fallback.log + 标准 logging + 内存记录供自检断言）。"""
    text = str(msg)
    with _LOG_LOCK:
        _LOG_RECORDS.append(text)
    try:
        from core.shared.log import _vc_log
        _vc_log(_LOG_PREFIX + text)
    except Exception:  # noqa: BLE001 - 日志永远不能反过来影响主流程
        pass
    try:
        logging.getLogger("engine_asr_local").warning("%s%s", _LOG_PREFIX, text)
    except Exception:  # noqa: BLE001
        pass


def get_log_records() -> List[str]:
    """返回本进程内的本地 ASR 日志副本（自检/诊断用）。"""
    with _LOG_LOCK:
        return list(_LOG_RECORDS)


def clear_log_records() -> None:
    """清空内存日志记录（自检用例隔离用，不影响已落盘的日志）。"""
    with _LOG_LOCK:
        _LOG_RECORDS.clear()


def clear_model_cache() -> None:
    """清空进程内模型缓存（自检负向用例 / 换模型目录后必须调用）。"""
    with _MODEL_CACHE_LOCK:
        _MODEL_CACHE.clear()


def load_local_model(model_dir: str, device: str = "cuda") -> Tuple[object, str, str]:
    """加载内置 faster-whisper 模型；GPU 失败自动降级 CPU int8。

    参数
    ----
    model_dir:
        已由 :func:`asr_local_paths.resolve_model_dir` 校验过的完整权重目录。
    device:
        ``cuda`` / ``auto`` / 其它值 → 先试 ``cuda/float16``，失败降级
        ``cpu/int8``；显式 ``cpu`` → 直接 ``cpu/int8``。

    返回 ``(model, 实际设备, 实际计算类型)``。任何失败都会写日志；CPU 也失败
    时抛 :class:`RuntimeError`（中文，含全部尝试的异常摘要），不静默返回。
    """
    # ⚠ 延迟 import：PyInstaller spec 的 hiddenimports 需登记 faster_whisper
    # 及其子模块（见交付说明）。
    from faster_whisper import WhisperModel

    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")

    want = str(getattr(device, "value", device) or "cpu").strip().lower()
    with _GPU_UNUSABLE_LOCK:
        gpu_broken = _GPU_UNUSABLE
    if gpu_broken and want != "cpu":
        _log("进程内已记录 GPU 不可用，本次直接使用 CPU / int8")
        want = "cpu"
    plan: Tuple[Tuple[str, str], ...] = (
        (("cpu", "int8"),) if want == "cpu"
        else (("cuda", "float16"), ("cpu", "int8"))
    )
    errors: List[str] = []
    norm_dir = os.path.normcase(os.path.abspath(str(model_dir)))

    for index, (dev, compute) in enumerate(plan):
        key = (norm_dir, dev, compute)
        try:
            with _MODEL_CACHE_LOCK:
                model = _MODEL_CACHE.get(key)
                if model is None:
                    kw = {"device": dev, "compute_type": compute,
                          "local_files_only": True}
                    if dev == "cpu":
                        kw["cpu_threads"] = min(
                            CPU_THREADS_CAP, os.cpu_count() or CPU_THREADS_CAP)
                    model = WhisperModel(str(model_dir), **kw)
                    _MODEL_CACHE[key] = model
            if index > 0:
                _log("GPU 加载失败后已自动降级到 CPU / int8（不会切到云端）：%s"
                     % errors[-1])
            _log("本地 ASR 模型加载成功：目录=%s，设备=%s，计算类型=%s，完全离线"
                 % (model_dir, dev, compute))
            return model, dev, compute
        except Exception as exc:  # noqa: BLE001 - ctranslate2 抛的是 RuntimeError
            detail = "%s: %s" % (type(exc).__name__, str(exc)[:400])
            errors.append("[%s/%s] %s" % (dev, compute, detail))
            if dev == "cuda":
                hint = ("（典型原因是缺少 cuBLAS 12 / cuDNN 运行库）"
                        if any(w in detail.lower() for w in _GPU_ERR_WORDS)
                        else "")
                _log("GPU（cuda/float16）加载失败%s：%s；准备自动降级 CPU / int8"
                     % (hint, detail))
                continue
            final_msg = (
                "本地 faster-whisper 模型加载失败（已尝试 %s）：\n%s\n"
                "请检查模型目录 %s 是否完整，或到「设置 → ASR 语音识别 → "
                "本地独立模型」改选工具箱内已有的模型。"
                % (" → ".join("%s/%s" % (d, c) for d, c in plan),
                   "\n".join(errors), model_dir))
            # 不得静默失败：CPU 兜底也失败时必须留一条错误日志再抛出。
            _log(final_msg.replace("\n", " "))
            raise RuntimeError(final_msg) from exc

    raise RuntimeError("本地 faster-whisper 模型加载失败：\n%s"
                       % "\n".join(errors))


def is_rtx_50_series() -> bool:
    """是否 RTX 50 系显卡（需 float16 计算类型）。

    50 系（Blackwell）在默认 int8/float32 下会报错或精度异常，必须显式
    指定 ``--compute_type float16``。GPUtil 不可用时返回 False——
    此时走默认计算类型，行为退化但不崩。内置直连下 GPU 一律用 float16，
    本函数仅用于保持 ``_build_command`` 的参数集合（缓存键）不变。
    """
    try:
        import GPUtil
    except ImportError:
        return False
    try:
        for g in GPUtil.get_gpus():
            name = (g.name or "").upper()
            if "50" in name and ("RTX" in name or "GEFORCE" in name):
                return True
    except Exception:  # noqa: BLE001
        return False
    return False


class FasterWhisperASR(BaseASR):
    """本地 faster-whisper 转写（内置 ``WhisperModel`` 直连）。

    构造签名与旧版**逐字一致**（``engine_asr._create_asr_instance`` 依赖它），
    但不再定位外部程序、不再抛 ``EnvironmentError``。程序名仅作缓存键占位。
    """

    def __init__(self, audio_input=None, faster_whisper_program: str = "",
                 whisper_model: str = "base", model_dir: str = "",
                 language: str = "zh", device: str = "cpu",
                 output_dir=None, output_format: str = "srt",
                 use_cache: bool = False, need_word_time_stamp: bool = False,
                 vad_filter: bool = True, vad_threshold: float = 0.4,
                 vad_method: str = "", ff_mdx_kim2: bool = False,
                 one_word: int = 0, prompt=None, **_ignored):
        super().__init__(audio_input, use_cache, need_word_time_stamp)

        self.model_path = whisper_model
        self.model_dir = model_dir
        self.faster_whisper_program = faster_whisper_program
        self.language = language
        self.device = device
        self.output_dir = output_dir
        self.output_format = output_format
        self.vad_filter = vad_filter
        self.vad_threshold = vad_threshold
        self.vad_method = vad_method
        self.ff_mdx_kim2 = ff_mdx_kim2
        self.prompt = prompt or ""
        # 文本重排参数（one_word 与 sentence 互斥：引擎同款，sentence 优先）
        self.one_word = 1 if one_word else 0
        self.sentence = False
        self.max_line_width = 100
        self.max_line_count = 1
        self.max_comma = 20
        self.max_comma_cent = 50

        self.process = None
        self._model = None
        self._resolved_model_dir = ""
        self._device_used = ""
        self._compute_used = ""
        self._resolve_program()

    # ---------- 程序定位（保留接口，语义改为内置直连） ----------
    def _resolve_program(self):
        """不再定位外部 exe；固定缓存键占位名并留痕。

        旧实现在 ``shutil.which`` 找不到 ``faster-whisper-xxl`` /
        ``faster-whisper`` 时抛 ``EnvironmentError``——本轮修复的核心就是
        去掉这个必然失败的前置条件。
        """
        self.faster_whisper_program = EMBEDDED_PROGRAM_TAG
        self.process = None
        _log("本地 ASR 采用内置 faster_whisper.WhisperModel 直连，"
             "无需外部 faster-whisper-xxl / faster-whisper 程序")

    # ---------- 命令行（只作缓存键，绝不执行） ----------
    def _build_command(self, audio_input: str):
        """构造命令行。参数集合与顺序即缓存键的一部分，勿随意调整。

        内置直连下这份命令**不会被执行**，只用于 ``_get_key`` 的 md5：
        改动任何一项都会让历史缓存失效（见模块开头的迁移说明）。
        """
        cmd = [str(self.faster_whisper_program),
               "-m", str(self.model_path),
               "--print_progress"]
        if self.model_dir:
            cmd.extend(["--model_dir", str(self.model_dir)])
        cmd.extend([str(audio_input), "-d", self.device,
                    "--output_format", self.output_format])
        # 语言为空 ⇒ 不传 -l，让程序自动检测
        if self.language:
            cmd.extend(["-l", self.language])
        cmd.extend(["-o", str(self.output_dir) if self.output_dir else "source"])

        if self.vad_filter:
            cmd.extend(["--vad_filter", "true",
                        "--vad_threshold", "%.2f" % self.vad_threshold])
            if self.vad_method:
                cmd.extend(["--vad_method", self.vad_method])
        else:
            cmd.extend(["--vad_filter", "false"])

        if self.ff_mdx_kim2 and self.faster_whisper_program.startswith(
                "faster-whisper-xxl"):
            cmd.append("--ff_mdx_kim2")

        cmd.extend(["--one_word", str(self.one_word)])

        if self.prompt:
            cmd.extend(["--initial_prompt", self.prompt])
        cmd.extend(["--beep_off"])

        if is_rtx_50_series():
            cmd.extend(["--compute_type", "float16"])
        return cmd

    # ---------- 缓存键 ----------
    def _get_key(self):
        """``crc32-hex + md5(完整命令)``——换任何参数都算另一份结果。"""
        cmd_hash = hashlib.md5(str(self._build_command("")).encode()).hexdigest()
        return "%s-%s" % (self.crc32_hex, cmd_hash)

    # ---------- 执行 ----------
    def _run(self, callback=None, **_kwargs) -> str:
        """内置直连转写，返回 SRT 文本（交给 ``_make_segments`` 解析）。"""
        if callback is None:
            def callback(_x, _y):
                return None

        model_dir = asr_local_paths.resolve_model_dir(
            self.model_path, self.model_dir)
        self._resolved_model_dir = model_dir
        explicit = str(self.model_dir or "").strip()
        if explicit and os.path.normcase(os.path.abspath(explicit)) != \
                os.path.normcase(os.path.abspath(model_dir)):
            _log("显式模型目录「%s」不含完整权重，已自动改用工具箱内模型：%s"
                 % (explicit, model_dir))
        if self.ff_mdx_kim2:
            _log("内置直连不支持 --ff_mdx_kim2 人声分离，已忽略该增强项"
                 "（不影响转写；仍计入缓存键）")

        with tempfile.TemporaryDirectory(prefix="vt_local_asr_") as temp_path:
            audio_path = self._prepare_audio(temp_path)
            callback(*ASRStatus.TRANSCRIBING.with_progress(5))
            self._model, self._device_used, self._compute_used = \
                load_local_model(model_dir, self.device)
            callback(*ASRStatus.TRANSCRIBING.with_progress(60))
            try:
                return self._transcribe(self._model, audio_path, callback)
            except Exception as exc:  # noqa: BLE001 - cuBLAS 在推理时才炸
                device = self._device_used
                compute = self._compute_used
                if device != "cuda" or not _is_gpu_error(exc):
                    raise RuntimeError(
                        "本地 faster-whisper 转写失败（%s/%s）：%s: %s"
                        % (device, compute, type(exc).__name__,
                           str(exc)[:400])) from exc
                detail = "%s: %s" % (type(exc).__name__, str(exc)[:300])
                _log("GPU（cuda/float16）推理失败：%s；自动降级 CPU / int8 重新转录"
                     % detail)
                mark_gpu_unusable(detail)
                (self._model, self._device_used,
                 self._compute_used) = load_local_model(model_dir, "cpu")
                try:
                    return self._transcribe(self._model, audio_path, callback)
                except Exception as exc2:  # noqa: BLE001
                    raise RuntimeError(
                        "本地 faster-whisper 转写失败：GPU 降级后 CPU / int8 仍失败。\n"
                        "GPU 错误：%s: %s\nCPU 错误：%s: %s"
                        % (type(exc).__name__, str(exc)[:300],
                           type(exc2).__name__, str(exc2)[:300])) from exc2

    def _prepare_audio(self, temp_path: str) -> str:
        """把输入音频落到临时目录，保留原扩展名让 PyAV 正确探测容器。"""
        if isinstance(self.audio_input, str) and os.path.isfile(self.audio_input):
            ext = os.path.splitext(self.audio_input)[1] or ".wav"
            dst = os.path.join(temp_path, "audio" + ext)
            shutil.copy2(self.audio_input, dst)
            return dst
        if self.file_binary:
            # ChunkedASR 的切块产物是 mp3 字节；PyAV 按内容探测，不依赖后缀。
            dst = os.path.join(temp_path, "audio.mp3")
            with open(dst, "wb") as f:
                f.write(self.file_binary)
            return dst
        raise ValueError("No audio data available")

    def _vad_parameters(self) -> dict:
        """组装 VAD 参数。faster-whisper 1.1.1 的 ``VadOptions`` 无 ``method``
        字段，运行时探测后忽略并写日志，避免静默吞掉用户配置。"""
        params = {"threshold": float(self.vad_threshold)}
        method = str(getattr(self.vad_method, "value", self.vad_method)
                     or "").strip()
        if not method:
            return params
        try:
            from faster_whisper.vad import VadOptions
            if "method" in inspect.signature(VadOptions).parameters:
                params["method"] = method
            else:
                _log("当前 faster-whisper 的 VadOptions 不支持 method=%s，"
                     "VAD 方法参数已忽略（阈值 %.2f 仍生效）"
                     % (method, float(self.vad_threshold)))
        except Exception as exc:  # noqa: BLE001
            _log("无法探测 VAD 方法支持情况（%s），method=%s 已忽略"
                 % (exc, method))
        return params

    def _transcribe(self, model, audio_path: str,
                    callback: Callable[[int, str], None]) -> str:
        """调用 ``WhisperModel.transcribe`` 并把结果转成 SRT 文本。"""
        language = _normalize_language(self.language,
                                       self._resolved_model_dir)
        kwargs = {
            "language": language,
            "beam_size": 5,
            "word_timestamps": bool(self.need_word_time_stamp),
            "vad_filter": bool(self.vad_filter),
        }
        if self.prompt:
            kwargs["initial_prompt"] = str(self.prompt)
        if self.vad_filter:
            kwargs["vad_parameters"] = self._vad_parameters()
        if self.one_word and not self.need_word_time_stamp:
            _log("one_word=1 但当前任务不需要词级时间戳，按句级输出"
                 "（逐词字幕需词级时间戳）")

        try:
            segments, info = model.transcribe(audio_path, **kwargs)
        except ValueError as exc:
            if kwargs.get("language") and "language" in str(exc).lower():
                _log("识别语言 %r 不受该模型支持，改用自动检测：%s"
                     % (kwargs["language"], exc))
                kwargs["language"] = None
                segments, info = model.transcribe(audio_path, **kwargs)
            else:
                raise RuntimeError("本地 faster-whisper 转写失败：%s" % exc) from exc
        except TypeError as exc:
            # 版本差异兜底：VadOptions 不接受未知字段时退到「仅阈值」。
            if "vad_parameters" in kwargs and (
                    "vad" in str(exc).lower() or "method" in str(exc).lower()):
                kwargs["vad_parameters"] = {
                    "threshold": float(self.vad_threshold)}
                _log("VAD 参数不被当前 faster-whisper 接受，已退到仅阈值：%s"
                     % exc)
                segments, info = model.transcribe(audio_path, **kwargs)
            else:
                raise RuntimeError("本地 faster-whisper 转写失败：%s" % exc) from exc

        total = float(getattr(info, "duration", 0.0) or 0.0)
        out: List[ASRDataSeg] = []
        last_pct = 60
        for seg in segments:
            text = _clean_text(getattr(seg, "text", "") or "")
            start = float(getattr(seg, "start", 0.0) or 0.0)
            end = float(getattr(seg, "end", start) or start)
            words = getattr(seg, "words", None) or []
            if self.one_word and self.need_word_time_stamp and words:
                for word in words:
                    wt = _clean_text(getattr(word, "word", "") or "")
                    if not wt:
                        continue
                    ws = float(getattr(word, "start", start) or start)
                    we = float(getattr(word, "end", ws) or ws)
                    out.append(ASRDataSeg(wt, int(ws * _MS_PER_SEC),
                                          int(max(we, ws) * _MS_PER_SEC)))
            elif text:
                out.append(ASRDataSeg(text, int(start * _MS_PER_SEC),
                                      int(max(end, start) * _MS_PER_SEC)))
            if total > 0:
                pct = 60 + int(35 * min(1.0, max(0.0, end / total)))
                if pct > last_pct:
                    last_pct = pct
                    callback(*ASRStatus.TRANSCRIBING.with_progress(pct))
        callback(*ASRStatus.TRANSCRIBING.with_progress(95))
        return _segments_to_srt(out)

    def _make_segments(self, resp_data: str):
        """解析 SRT 并过滤音乐标记与幻觉文本（行为契约，逐字保留）。"""
        data = ASRData.from_srt(resp_data)
        out = []
        for seg in data.segments:
            text = (seg.text or "").strip()
            if not text:
                continue
            if text.startswith(_MUSIC_PREFIXES):
                continue
            if any(k in text for k in HALLUCINATION_KEYWORDS):
                continue
            out.append(seg)
        return out


_MS_PER_SEC = 1000


def _normalize_language(language, model_dir: str) -> Optional[str]:
    """把配置里的语言标签/代码归一化成 faster-whisper 可接受的语言代码。

    返回 ``None`` 表示自动检测。``*.en`` 是英文专用模型，其它语言一律回退
    自动检测并写日志（否则 tokenizer 会直接抛 ValueError）。
    """
    raw = str(getattr(language, "value", language) or "").strip()
    if not raw or raw.lower() in ("auto", "自动检测", "none", "null"):
        return None
    base = os.path.basename(str(model_dir or ""))
    if base.lower().endswith(".en"):
        if raw.lower() not in ("en", "english", "英语"):
            _log("模型 %s 为英文专用，识别语言 %r 已改为自动检测" % (base, raw))
            return None
        return "en"
    try:
        from engine_entities import LANGUAGES
        if raw in LANGUAGES:
            code = str(LANGUAGES.get(raw) or "").strip()
            return code or None
    except Exception:  # noqa: BLE001
        pass
    if re.fullmatch(r"[A-Za-z]{2,3}(-[A-Za-z]{2,4})?", raw):
        return raw.lower()
    _log("无法识别的识别语言 %r，改用自动检测" % raw)
    return None


def _clean_text(text: str) -> str:
    """SRT 文本不能含换行（会把一个 cue 撕成两块）。"""
    return str(text).replace("\r", " ").replace("\n", " ").strip()


def _segments_to_srt(segs: List[ASRDataSeg]) -> str:
    """按 ``ASRData.to_srt`` 同款格式拼 SRT，保证 ``ASRData.from_srt`` 可解析。"""
    return "\n".join(
        "%d\n%s\n%s\n" % (n, seg.to_srt_ts(), seg.text)
        for n, seg in enumerate(segs, 1)
    )


# ---------- 旧 CLI 辅助函数：完整保留为兼容面（内置直连不再调用） ----------
_PROGRESS_RE = re.compile(r"(\d{1,3})\s*%")


def _parse_progress(line: str):
    """从程序输出里取百分比（取不到返回 None）。"""
    m = _PROGRESS_RE.search(line)
    if not m:
        return None
    try:
        return max(0, min(100, int(m.group(1))))
    except ValueError:
        return None


def _find_output_srt(temp_path: str):
    """在临时目录里找程序产出的 SRT（可能改名、可能落在 source 子目录）。"""
    for root, _dirs, files in os.walk(temp_path):
        for name in files:
            if name.lower().endswith(".srt"):
                return os.path.join(root, name)
    return None
