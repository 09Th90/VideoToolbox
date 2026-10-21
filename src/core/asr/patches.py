# -*- coding: utf-8 -*-
# @version 2.5.1
"""vc ASR 补丁（协议注入 / 分块几何 / 非中英占比守卫）（v2.3.1 拆分工程 · 自 video_toolbox.py 原样搬入）。

core/asr 域：ASR 全协议适配 + vc 转录补丁；依赖规则见 core/__init__.py。
"""
import time

from core.shared.log import _vc_log
from core.asr.protocol import (
    ASR_FILETRANS_POLL_MAX, ASR_INLINE_AUDIO_MAX_RAW, ASR_WS_FRAME_BYTES,
    _asr_assemblyai_submit, _asr_azure_submit, _asr_chat_audio_submit,
    _asr_dashscope_filetrans_submit, _asr_dashscope_native_submit,
    _asr_dashscope_realtime_submit, _asr_deepgram_submit,
    _asr_elevenlabs_submit, _asr_empty_body_err, _asr_fallback_chat_audio,
    _asr_gemini_submit, _asr_normalize_resp, _asr_retry_native,
    _asr_separate_audio, _asr_volcengine_submit, asr_base_guard,
    asr_diarize_of, asr_model_guard, asr_model_hard_guard, asr_protocol_fix,
    asr_protocol_of, asr_separate_of, asr_strip_endpoint_tail)

def vc_asr_protocol_patch():
    """ASR 服务模式全协议适配（幂等运行期补丁，引擎 WhisperAPI 不改本体）。

    在引擎 WhisperAPI._submit 前加协议分发：
      · openai     → 原实现（multipart /audio/transcriptions，verbose_json）；
      · azure      → deployments 端点 + api-key 头；
      · chat_audio → chat/completions + input_audio（百炼 Qwen-ASR、小米 MiMo）；
      · deepgram   → /v1/listen，Token 头 + 原始音频（原生词级时间轴）；
      · elevenlabs → /v1/speech-to-text，xi-api-key（原生词级时间轴）；
      · gemini     → generateContent + inline_data（纯文本，按句兜底）；
      · volcengine → 豆包录音识别极速版（一次请求返回，本地文件直传）；
      · assemblyai → /v2/upload + /v2/transcript + 轮询（词级时间轴）。
    各协议响应统一经 _asr_normalize_resp 归一：原生时间轴原样保留，
    纯文本响应（Azure json / Qwen-Audio / Gemini 等）按句切分 + 时长占比
    生成近似时间轴。缓存键追加协议名，防止换协议后吃到旧结果。
    ⚠️ 实时（WebSocket 流式）模型由 asr_model_guard 提前拦下并给出改法。
    """
    try:
        from videocaptioner.core.asr.whisper_api import WhisperAPI
    except Exception as e:  # noqa: BLE001
        _vc_log(f"ASR 协议补丁导入失败：{e}")
        return False
    if getattr(WhisperAPI, "_vt_proto_patched", False):
        return True
    orig_submit = WhisperAPI._submit
    orig_key = WhisperAPI._get_key

    def _submit(self):
        # 说话人分离开关：进 _submit 就取一次挂到实例上，分块重试 / 实时降级
        # 都沿用同一个值，避免同一段音频前后半截口径不一致。
        if getattr(self, "diarize", None) is None:
            self.diarize = asr_diarize_of()
        # 语音分离（separation）：同口径取一次挂到实例上。当前是**接口占位**
        # ——真正接入声源分离模型时，这里改成"先分离出单人轨、再逐轨提交
        # 识别"，音乐 reaction 的"剔除歌声"也在这一层按轨道标签筛掉。
        if getattr(self, "separate", None) is None:
            self.separate = asr_separate_of()
            if self.separate:
                try:
                    _src = getattr(self, "audio_input", "")
                    _asr_separate_audio(_src if isinstance(_src, str) else "", self)
                except Exception as e:  # noqa: BLE001
                    _vc_log("语音分离接口调用失败：%s" % (e,))
        proto = asr_protocol_of()
        # 协议纠偏统一收在 asr_protocol_fix（v1.14.2 起，v1.15.3 补反向守卫）：
        # ① 显式/旧配置判成 openai，但端点与模型特征指向别族时按推断改走——
        #    百炼 maas + 实时模型拿 OpenAI SDK 打必被服务端断连；qwen-audio/
        #    paraformer 族在 maas 上根本没有 /audio/transcriptions；
        # ② 协议选了「百炼实时」但模型不是实时模型时改走文件识别——否则服务端
        #    只回 `InvalidParameter url error, please check url!`，既看不懂、
        #    重试和降级也都救不回来（task-failed 属确定性错误）。
        proto, _fix_note = asr_protocol_fix(proto, getattr(self, "base_url", ""),
                                            getattr(self, "model", ""))
        if _fix_note:
            _vc_log("ASR " + _fix_note)
        # v1.15.5：实时对话/翻译模型（livetranslate 族）任何协议都转写不了，
        # 无条件拦——否则 WS 被拒后降级文件上传只拿到空体 400/500，无从下手。
        guard = asr_model_hard_guard(getattr(self, "model", ""))
        if proto != "dashscope_realtime":
            # 实时模型只有走实时协议才有救：其它协议下提前拦，别等服务端 404。
            # 走实时协议时**不能**拦（那正是让实时模型出字幕的路）。
            if not guard:
                guard = asr_base_guard(getattr(self, "base_url", ""))
            if not guard:
                guard = asr_model_guard(getattr(self, "model", ""))
            # 非 openai 协议不走引擎原实现，它那段"简体中文提示词预设"要自己补
            if (getattr(self, "language", "") == "zh"
                    and not getattr(self, "prompt", "")):
                self.prompt = "你好，我们需要使用简体中文，以下是普通话的句子"
        if guard:
            raise RuntimeError(guard)
        if proto == "dashscope_realtime" and not _proto._ASR_WS_DEGRADED:
            try:
                resp = _asr_dashscope_realtime_submit(self)
            except RuntimeError as e:
                # 实时 WebSocket 被服务端中途掐断（握手/task-started 正常、音频
                # 发送中或完成后无 Close 码断连；官方 dashscope SDK 同样无法
                # 使用——2026-09-17 实测，与客户端实现/网络路径无关）。
                _e = str(e)
                if "连接" not in _e and "超时" not in _e:
                    raise              # task-failed 等确定性错误，降级无意义
                _proto._ASR_WS_DEGRADED = True
                resp = _asr_fallback_chat_audio(self, _e)
        elif proto == "dashscope_realtime":
            # 本进程已确认实时通道被服务端掐断 → 直接走文件识别，不再试 WS
            resp = _asr_fallback_chat_audio(self)
        elif proto == "azure":
            resp = _asr_azure_submit(self)
        elif proto in ("chat_audio", "dashscope"):
            try:
                resp = _asr_chat_audio_submit(self)
            except RuntimeError as e:
                # v1.15.6：百炼原生专用模型（Qwen-Audio-3.0-ASR-Flash /
                # Fun-ASR-Flash）被兼容模式打回空体 400/500 —— 同一模型、同一
                # 音频换原生端点即通，这里兜一次（每个任务只兜一次）。
                if not _asr_empty_body_err(e):
                    raise
                resp = _asr_retry_native(self, e)
        elif proto == "dashscope_native":
            resp = _asr_dashscope_native_submit(self)
        elif proto == "dashscope_filetrans":
            resp = _asr_dashscope_filetrans_submit(self)
        elif proto == "deepgram":
            resp = _asr_deepgram_submit(self)
        elif proto == "elevenlabs":
            resp = _asr_elevenlabs_submit(self)
        elif proto == "gemini":
            resp = _asr_gemini_submit(self)
        elif proto == "volcengine":
            resp = _asr_volcengine_submit(self)
        elif proto == "assemblyai":
            resp = _asr_assemblyai_submit(self)
        else:
            # openai 协议走引擎原实现（OpenAI SDK）。SDK 会在 base_url 后面再
            # 拼一次 /audio/transcriptions，所以先把"完整端点"的尾巴削掉并
            # 重建 client —— 内存里改 base_url 不会影响已经建好的 client。
            clean = asr_strip_endpoint_tail(self.base_url, "/audio/transcriptions",
                                            "/audio/translations")
            if clean and clean != self.base_url:
                self.base_url = clean
                _vc_log(f"ASR 地址含完整端点，已规范化为 {clean}")
                try:
                    from openai import OpenAI
                    self.client = OpenAI(base_url=clean, api_key=self.api_key)
                except Exception as e:  # noqa: BLE001
                    _vc_log(f"规范化后重建 ASR 客户端失败：{e}")
            resp = orig_submit(self)
        return _asr_normalize_resp(resp, self)

    def _get_key(self):
        try:
            return f"{orig_key(self)}-{asr_protocol_of()}"
        except Exception:  # noqa: BLE001
            return orig_key(self)

    WhisperAPI._submit = _submit
    WhisperAPI._get_key = _get_key
    WhisperAPI._vt_proto_patched = True
    _vc_log("ASR 协议补丁已挂：openai/azure/chat_audio/deepgram/elevenlabs/"
            "gemini/volcengine/assemblyai（纯文本响应按句兜底；实时模型提前拦截）")
    try:
        vc_asr_chunk_patch()
    except Exception as e:  # noqa: BLE001
        _vc_log(f"分块补丁挂载失败：{e}")
    return True


#: chat_audio 族（百炼 compatible-mode）单请求音频时长上限约 3 分钟，
#: 引擎默认按 600s 切块必超 → 该协议下把块长压到 170s（留转发/编码余量）。
ASR_CHAT_AUDIO_CHUNK_MS = 170_000

#: 百炼原生端点（multimodal-generation）单请求音频上限约 5 分钟 → 压到 280s。
ASR_NATIVE_CHUNK_MS = 280_000


def vc_asr_chunk_patch():
    """chat_audio 协议下把引擎的 ASR 音频分块长度压到 3 分钟内（幂等补丁）。

    引擎的 ChunkedASR 默认 chunk_length_ms=600s，对 OpenAI/Deepgram 这类
    长音频服务没问题；但百炼 compatible-mode 多模态单次请求上限约 3 分钟，
    600s 的块必被服务端拒（The audio is too long）。这里包住
    transcribe._create_whisper_api_asr：构造完成后按当前协议把块长改到 170s，
    让「切块→逐块提交」在提交前就合规，而不是等 400 再对半救火。
    """
    try:
        import importlib as _il
        # ⚠️ asr 包属性 transcribe 是**函数**（遮蔽同名子模块），普通
        # import ... as _tr 拿到的是函数；必须 importlib 按模块名取真模块。
        _tr = _il.import_module("videocaptioner.core.asr.transcribe")
    except Exception as e:  # noqa: BLE001
        _vc_log(f"分块补丁导入 transcribe 失败：{e}")
        return False
    if getattr(_tr, "_vt_chunk_patched", False):
        return True
    orig = getattr(_tr, "_create_whisper_api_asr", None)
    if orig is None:
        return False

    def _create(*a, **k):
        inst = orig(*a, **k)
        try:
            _p = asr_protocol_of()
            if _p in ("chat_audio", "dashscope"):
                inst.chunk_length_ms = ASR_CHAT_AUDIO_CHUNK_MS
            elif _p == "dashscope_native":
                # 原生端点官方上限约 5 分钟（Qwen-Audio-3.0-ASR-Flash），
                # 压到 280s 留转码/转发余量。
                inst.chunk_length_ms = ASR_NATIVE_CHUNK_MS
        except Exception as e:  # noqa: BLE001
            _vc_log(f"分块长度调整失败：{e}")
        return inst

    _tr._create_whisper_api_asr = _create
    _tr._vt_chunk_patched = True
    _vc_log("ASR 分块补丁已挂：chat_audio 协议块长压到 170s（默认 600s 超上限）")
    return True


def asr_non_zh_en_ratio(text):
    """文本中「非中/英」字符占比（0~1）；无有效字符返回 0。

    判据：跳过空白与标点符号；ASCII（字母数字）与**汉字**算"中/英"，其余
    书写系统（假名/谚文/西里尔/泰文…）算"非中英"。日文句子里的汉字计入中英，
    假名为主时占比仍过半 → 用于「默认接口语言提示」判断片源是不是中文/英文，
    非中英占比高时不再注入简体中文提示词。
    """
    import unicodedata
    total = other = 0
    for ch in str(text or ""):
        if ch.isspace():
            continue
        if unicodedata.category(ch)[0] in ("P", "S"):
            continue
        o = ord(ch)
        total += 1
        if o < 128:
            continue                                  # ASCII 字母数字
        if (0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF
                or 0xF900 <= o <= 0xFAFF
                or 0x3007 == o or 0x00AA == o or 0x00BA == o):
            continue                                  # 汉字（日文汉字同源）
        other += 1
    return (other / total) if total else 0.0


#: 引擎翻译服务枚举值（videocaptioner.core.entities.TranslatorServiceEnum）。
#: v1.12.0 起字幕翻译板块仅支持机翻（微软 / 谷歌 / DeepLx），LLM 翻译入口
#: 已全部移除；TS_LLM 仅用于把历史配置迁回机翻。
TS_LLM = "LLM 大模型翻译"
TS_BING = "微软翻译"

#: 免费翻译端点预检结果缓存（进程内，避免每条字幕重复探测）
_TS_PROBE_CACHE = {}


def _ts_probe_ok(kind):
    """免费翻译端点连通性探测（3 秒超时，结果进程内缓存）——诊断/备用。

    v1.12.0 实测：微软 ``edge.microsoft.com/translate/translatetext``（免认证）
    直连 200；谷歌 ``translate.googleapis.com/translate_a/single?client=gtx``
    需走系统代理（requests 默认信任），代理未开则超时。本函数**不用于短路**，
    只保留给诊断与后续"可用性提示"复用。
    """
    if kind in _TS_PROBE_CACHE:
        return _TS_PROBE_CACHE[kind]
    ok = True
    if kind == "google":
        try:
            import requests
            r = requests.get(
                "https://translate.googleapis.com/translate_a/single",
                params={"client": "gtx", "sl": "auto", "tl": "zh-CN",
                        "dt": "t", "q": "ok"},
                headers={"User-Agent": "Mozilla/5.0"}, timeout=3)
            ok = r.status_code == 200
        except Exception:  # noqa: BLE001
            ok = False
    _TS_PROBE_CACHE[kind] = ok
    return ok




__all__ = [
    "vc_asr_protocol_patch",
    "vc_asr_chunk_patch",
    "asr_non_zh_en_ratio",
    # vc_asr_protocol_patch 的翻译服务枚举迁移常量（拆分前在单体顶层，
    # golden 常量基线钉有；facade 经 core.asr.__all__ 再导出）
    "TS_LLM",
    "TS_BING",
    # vc_asr_chunk_patch 的分块几何常量（同上，golden 基线钉有）
    "ASR_CHAT_AUDIO_CHUNK_MS",
    "ASR_NATIVE_CHUNK_MS",
]


#: protocol 模块引用（_ASR_WS_DEGRADED 降级标志跨模块读写）
from core.asr import protocol as _proto  # noqa: E402
