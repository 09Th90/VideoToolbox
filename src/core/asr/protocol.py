# -*- coding: utf-8 -*-
# @version 2.6.0
"""ASR 服务模式全协议适配（协议推断/守卫 + 各服务商 submit + 词级聚合）（v2.3.1 拆分工程 · 自 video_toolbox.py 原样搬入）。

core/asr 域：ASR 全协议适配 + vc 转录补丁；依赖规则见 core/__init__.py。
"""
import base64
import json
import os
import re
import time

from core.shared.log import _vc_log
from core.shared.ai import ai_load_config, ai_mod

# ---------- v1.14.1 起：ASR 服务模式全协议适配 ----------

#: 支持的协议（= 配置里 asr_protocol 的取值；auto 为自动识别）
#: ⚠️ `dashscope` 是历史键：它其实就是 chat_audio 那一族（百炼兼容模式），
#:    保留是为了让老配置继续能用，新推断一律产出 `chat_audio`。
ASR_PROTOCOLS = ("auto", "openai", "azure", "chat_audio", "dashscope",
                 "deepgram", "elevenlabs", "gemini",
                 "volcengine", "assemblyai", "dashscope_realtime",
                 "dashscope_native", "dashscope_filetrans")

#: 协议说明（供界面下拉提示与日志引用）
ASR_PROTOCOL_NOTES = {
    "openai": "OpenAI Whisper 兼容（multipart /audio/transcriptions）——"
              "覆盖 OpenAI / 硅基流动 / Groq / Fireworks / DeepInfra / "
              "Mistral Voxtral / 自建 whisper.cpp、faster-whisper 服务等",
    "azure": "Azure OpenAI（deployments 端点 + api-key 头）",
    "chat_audio": "OpenAI 兼容 chat/completions + input_audio（音频以 Data URL "
                  "传入）——阿里云百炼 Qwen-ASR（qwen3-asr-flash）、"
                  "小米 MiMo（mimo-v2.5-asr）等",
    "dashscope": "同 chat_audio（历史键，保留兼容）",
    "deepgram": "Deepgram（POST /v1/listen，Authorization: Token + 原始音频，"
                "带词级时间轴）",
    "elevenlabs": "ElevenLabs Scribe（POST /v1/speech-to-text，xi-api-key，"
                  "带词级时间轴）",
    "gemini": "Google Gemini（generateContent + inline_data，返回纯文本，"
              "时间轴按句兜底）",
    "volcengine": "火山引擎（豆包）录音识别极速版——一次请求即返回，本地文件"
                  "直传；密钥填「APPID:AccessToken」或新版 API Key，"
                  "模型填 Resource ID（默认 volc.bigasr.auc_turbo）",
    "assemblyai": "AssemblyAI（上传 → 提交 → 轮询；Authorization 头**不带** "
                  "Bearer，模型名可逗号分隔多个做回退，带词级时间轴）",
    "dashscope_realtime": "百炼实时（WebSocket）——把本地音频切片推给 "
                          "wss://…/api-ws/v1/inference/，覆盖**只有实时形态**"
                          "的模型（fun-asr-flash-8k-realtime / fun-asr-realtime"
                          " / qwen3-asr-flash-realtime 等），带原生句级时间轴",
    "dashscope_filetrans":
        "百炼 Filetrans 异步文件转写（提交 → 轮询，POST /api/v1/services/"
        "audio/asr/transcription）——模型名带 -filetrans；⚠️ 不收本地音频，"
        "会先把音频传到百炼临时存储再转写（官方标注勿用于生产环境）；"
        "说话人分离仅支持单声道、建议 ≤2 小时",
    "dashscope_native": "百炼原生录音文件识别（POST /api/v1/services/aigc/"
                        "multimodal-generation/generation）——Qwen-Audio-3.0-ASR-"
                        "Flash（qwen-audio-3.0-asr-flash）等**不走兼容模式**的 "
                        "ASR 模型专用；音频以 base64 Data URL 传入，响应含词级"
                        "时间轴（output.sentence.words）",
}

#: 实时（WebSocket 流式）模型的识别特征：这些模型**不能**一次性上传调用
ASR_REALTIME_HINTS = ("realtime", "-rt-", "streaming")

#: 实时模型里属于「录音转写」族的关键词：名字带 realtime 但确实是语音识别
#: 模型（百炼实时协议可用）。livetranslate 这类实时**对话/翻译**模型不在此
#: 族——任何协议都拿它做不了转写，必须提前拦下给改法。
_REALTIME_ASR_FAMILY = ("asr", "paraformer", "sensevoice", "whisper",
                        "stt", "transcri")


def is_realtime_asr_family(model: str) -> bool:
    """是否「实时语音识别」族模型（区别于实时对话/翻译模型）。"""
    m = str(model or "").lower()
    if not any(h in m for h in ASR_REALTIME_HINTS):
        return False
    return any(k in m for k in _REALTIME_ASR_FAMILY)


_TTS_HINTS = ("tts", "speech-synthesis", "voice-synthesis", "cosyvoice",
              "sambert")

#: 百炼**原生**（multimodal-generation）录音文件识别模型特征：qwen-audio 系带
#: asr 的即时模型。实测（2026-09-20）：qwen-audio-3.0-asr-flash 官方文档给的就是
#: 原生端点，拿兼容模式的 chat/completions 打它**恒回 HTTP 400 空体**——同一个
#: 模型、同一份音频，换端点即 200 并返回词级时间轴。filetrans（异步，需公网
#: URL）与 realtime 不在此列。
def is_dashscope_native_asr(model) -> bool:
    m = str(model or "").lower()
    if not m or "filetrans" in m or any(h in m for h in ASR_REALTIME_HINTS):
        return False
    return "qwen-audio" in m and "asr" in m


#: 百炼原生 ASR 的官方 API 路径（与 compatible-mode 不是同一个端点）
ASR_NATIVE_PATH = "/api/v1/services/aigc/multimodal-generation/generation"


def _asr_native_url(base_url):
    """从「接口地址」推导百炼原生 ASR 端点（只换路径，不换域名）。

    · 已填原生端点 → 原样；
    · 填 compatible-mode/v1 或只填域名 → 同域名 + 官方 API 路径；
    · 留空 → 公共百炼 dashscope.aliyuncs.com + 官方 API 路径。
    """
    b = asr_strip_endpoint_tail(str(base_url or "").strip())
    low = b.lower()
    if low.endswith(ASR_NATIVE_PATH.lower()):
        return b
    if not b:
        return "https://dashscope.aliyuncs.com" + ASR_NATIVE_PATH
    if "//" in b:
        scheme, rest = b.split("//", 1)
        return scheme + "//" + rest.split("/", 1)[0] + ASR_NATIVE_PATH
    return "https://" + b.split("/", 1)[0] + ASR_NATIVE_PATH


def asr_model_hard_guard(model: str) -> str:
    """模型与「录音转写」根本不符的硬守卫：**不论协议**都返回提示（可放行空串）。

    覆盖两类（v1.15.5 实测各踩一次）：
      · 实时对话/翻译模型（livetranslate 族）：名字带 realtime 但不是转写；
      · 语音合成（TTS）模型（qwen-audio-3.0-tts-plus 等）：输出音频不收音频。
    两类走任何协议都转写不了（WS 被拒后降级文件上传只回 HTTP 400/500 空
    体），所以无条件拦，并在提示里给出录音文件识别模型与套餐专属端点。
    """
    m = str(model or "").lower()
    if any(h in m for h in ASR_REALTIME_HINTS) and not is_realtime_asr_family(m):
        return ("模型「%s」是实时对话/翻译模型（名字带 realtime 但不是录音转写"
                "模型），语音转写用不了它。请改录音文件识别模型：百炼 "
                "qwen3-asr-flash / qwen-audio-3.0-asr-flash（原生端点）/ "
                "fun-asr-flash、硅基流动 "
                "FunAudioLLM/SenseVoiceSmall、OpenAI whisper-1；订阅套餐还要"
                "端点配套：百炼按量 dashscope.aliyuncs.com/compatible-mode/v1、"
                "Token Plan token-plan.cn-beijing.maas.aliyuncs.com/"
                "compatible-mode/v1" % model)
    if any(k in m for k in _TTS_HINTS):
        return ("模型「%s」是语音合成（TTS）模型——它输出音频、不收音频，做不了"
                "语音转写。请改录音文件识别模型：百炼 qwen3-asr-flash / "
                "qwen-audio-3.0-asr-flash（原生端点）/ fun-asr-flash、硅基流动 "
                "FunAudioLLM/SenseVoiceSmall、OpenAI whisper-1" % model)
    return ""


def _host_path(base: str):
    """拆出 (host, 路径) 小写形式，供各端点守卫判断域名与路径段。"""
    b = str(base or "").strip().rstrip("/").lower()
    if "//" in b:
        b = b.split("//", 1)[1]
    host, _, path = b.partition("/")
    return host, ("/" + path) if path else ""


def _is_anthropic_only_path(base: str) -> bool:
    """火山方舟 Anthropic 协议专用端点：/api/coding、/api/compatible。

    这两个地址不含 "anthropic" 字样却只收 Anthropic 协议——旧守卫只认
    "anthropic" 关键词时拦不住，OpenAI 请求打上去必 404/400。该平台的
    OpenAI 协议端点是 /api/v3（按量）与 /api/coding/v3（Coding Plan）。
    """
    host, path = _host_path(base)
    if "volces.com" not in host and "volcengine" not in host:
        return False
    return path.rstrip("/").endswith(("/api/coding", "/api/compatible"))


#: 「完整端点」的常见尾巴 —— 用户从服务商文档抄地址时容易连路径一起抄进来
ASR_ENDPOINT_TAILS = ("/audio/transcriptions", "/audio/translations",
                      "/chat/completions", "/v2/upload", "/v2/transcript",
                      "/api/v1/services/aigc/multimodal-generation/generation")


def asr_strip_endpoint_tail(base, *tails):
    """削掉"用户把**完整端点**抄进地址栏"的那截尾巴。

    为什么要削：无论 OpenAI SDK 还是我们自己的拼接，都是「base + 固定路径」
    的写法，而服务商文档给的常常是完整 URL —— 例如智谱的
    `https://open.bigmodel.cn/api/paas/v4/audio/transcriptions`。照抄进去就会
    拼成 `.../audio/transcriptions/audio/transcriptions` → 404。
    宁可在这里削一次，也不该让用户对着 404 猜。

    不传 tails 时按 `ASR_ENDPOINT_TAILS` 里的常见端点尾巴削。
    """
    tails = tails or ASR_ENDPOINT_TAILS
    b = str(base or "").strip().rstrip("/")
    changed = True
    while changed and b:
        changed = False
        low = b.lower()
        for tail in tails:
            t = str(tail or "").strip().lower().rstrip("/")
            if t and low.endswith(t):
                b = b[: -len(t)].rstrip("/")
                changed = True
                break
    return b


def _infer_asr_protocol(base_url, model):
    """按地址与模型名推断协议（auto 档的唯一实现）。

    顺序有讲究：先认**域名独有的**服务（小米 MiMo / deepgram / elevenlabs /
    gemini），再认 Azure，最后才是"看着像 OpenAI 兼容"的兜底。

    ⚠️ 「chat/completions + input_audio」这族（百炼 Qwen-ASR、小米 MiMo ASR）
    必须与 `openai` 分开：这类服务**没有** `/audio/transcriptions` 端点，
    按 openai 协议去调只会 404（小米 MiMo 官方明确说明 ASR 走 chat completions）。
    """
    base = str(base_url or "").lower()
    mdl = str(model or "").lower()
    if "openspeech.bytedance.com" in base or "volcengine" in base:
        return "volcengine"
    if "assemblyai.com" in base:
        return "assemblyai"
    if "filetrans" in mdl:
        # 模型名带 -filetrans 是百炼异步文件转写的专有命名（qwen3-asr-flash-
        # filetrans / qwen-audio-3.0-asr-flash-filetrans / fun-asr 系列），
        # 走同步端点会 404/参数错——直接按异步链路认。
        return "dashscope_filetrans"
    if ("aliyuncs.com" in base or "dashscope" in base) and any(
            h in mdl for h in ASR_REALTIME_HINTS):
        # 百炼系域名 + 实时模型：这类模型只有 WebSocket 形态 → 走实时协议。
        # （它们连 compatible-mode 的 chat/completions 都调不了，官方模型表
        #   标注「模式=即时、API=WebSocket」。）
        return "dashscope_realtime"
    if ("aliyuncs.com" in base or "dashscope" in base) \
            and is_dashscope_native_asr(mdl):
        # Qwen-Audio-3.0-ASR-Flash 这类**原生端点**专用的录音文件识别模型：
        # 按 chat_audio 打 compatible-mode 恒回 400 空体（v1.15.6 实测），
        # 换原生端点即通 —— 必须在这里就分出去。
        return "dashscope_native"
    if "deepgram.com" in base:
        return "deepgram"
    if "elevenlabs.io" in base:
        return "elevenlabs"
    if "generativelanguage.googleapis.com" in base:
        return "gemini"
    if ("openai.azure.com" in base or "/openai/deployments/" in base
            or "azure.com" in base):
        return "azure"
    if ("xiaomimimo.com" in base or "mimo-v2" in mdl
            or "compatible-mode" in base or "dashscope" in base
            or ("qwen" in mdl and ("audio" in mdl or "asr" in mdl))
            or "paraformer" in mdl or "fun-asr" in mdl):
        return "chat_audio"
    return "openai"


def asr_protocol_fix(proto, base_url, model):
    """协议纠偏（双向）：把「协议 ↔ 端点 ↔ 模型」明显对不上的组合拉回正轨。

    返回 `(修正后的协议, 给日志的说明)`；无需修正时说明为空串。

    · `openai` + 百炼/小米系端点或模型 → 按推断改走 `chat_audio`
      （这类服务没有 `/audio/transcriptions`，按 openai 打只会 404）。
    · `dashscope_realtime` + 模型**不含实时特征**（v1.15.3 新增的反向守卫）
      → 按推断改走文件识别。用文件识别模型去连实时端点时，服务端只回
      `InvalidParameter url error, please check url!`——用户完全无从下手；
      而「接口协议」显式选过「百炼实时（WebSocket）」后，很容易与后来换成的
      文件识别模型残留成这个组合（实测踩到）。
    """
    p = str(proto or "").strip().lower()
    mdl = str(model or "").lower()
    if p == "openai":
        auto = _infer_asr_protocol(base_url, model)
        if auto and auto != "openai":
            return auto, "协议 openai 与该端点/模型不符，自动改走 %s" % auto
    if p in ("chat_audio", "dashscope", "dashscope_native") \
            and "filetrans" in mdl:
        # 模型名带 -filetrans 却按同步协议在打：走 Filetrans 提交-轮询链路。
        # 这是用户换模型后最常见的残留组合（旧配置留着 chat_audio）。
        return "dashscope_filetrans", (
            "模型「%s」是百炼异步文件转写模型，改走 Filetrans（提交 → 轮询）"
            "链路" % mdl)
    if p in ("chat_audio", "dashscope") and is_dashscope_native_asr(mdl):
        # v1.15.6：Qwen-Audio-3.0-ASR-Flash 这类原生端点专用模型被显式/旧配置
        # 判成 chat_audio 时，compatible-mode 只会回 HTTP 400 空体（重试与降级
        # 都救不回）→ 按推断改走原生端点。
        return "dashscope_native", (
            "模型「%s」走百炼原生端点（multimodal-generation），兼容模式的 "
            "chat/completions 对它恒回 400 空体，协议自动改走 dashscope_native"
            % model)
    if p == "dashscope_realtime" and not any(h in mdl for h in ASR_REALTIME_HINTS):
        auto = _infer_asr_protocol(base_url, model)
        if auto and auto != "dashscope_realtime":
            return auto, ("协议设为「百炼实时（WebSocket）」但模型「%s」不是实时"
                          "模型（名里没有 realtime / -rt- / streaming），"
                          "自动改走 %s" % (model, auto))
    return p, ""


def asr_base_guard(base_url):
    """ASR 地址守卫：地址填成了「文本对话端点」时给出能照着改的提示。

    最常见的错误是把 Anthropic / chat 这类**只收文本**的端点当成 ASR 地址
    （音频走 multipart 或 input_audio，那些端点根本不收），表现就是五花八门
    的 404 / 415 —— 与其让用户对着状态码猜，不如直接说"该填什么"。
    """
    b = str(base_url or "").lower()
    if "anthropic" in b or _is_anthropic_only_path(b):
        return ("ASR 地址填的是 Anthropic 文本对话端点（%s）——它收不了音频。"
                "请改填 OpenAI 兼容端点：公共百炼 "
                "https://dashscope.aliyuncs.com/compatible-mode/v1，Token Plan "
                "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1，"
                "火山方舟 https://ark.cn-beijing.volces.com/api/v3（Coding Plan "
                "为 /api/coding/v3），或专属实例的 …/compatible-mode/v1" % base_url)
    return ""


def asr_model_guard(model):
    """实时（流式）模型守卫：返回给用户看的提示，可放行时返回空串。

    ⚠️ 只在**非实时协议**下调用：实时模型在「百炼实时（WebSocket）」协议下
    是能正常出字幕的（_asr_dashscope_realtime_submit），不该被拦。
    """
    m = str(model or "").lower()
    if any(h in m for h in ASR_REALTIME_HINTS):
        return ("模型「%s」是实时（WebSocket 流式）语音识别，本协议用不了它。"
                "把「接口协议」改为「百炼实时（WebSocket）」（留自动识别也会"
                "选中），或改用录音文件识别模型：公共百炼 qwen3-asr-flash、"
                "硅基流动 FunAudioLLM/SenseVoiceSmall、OpenAI whisper-1" % model)
    return ""


def asr_protocol_of(ai_cfg=None):
    """解析 ASR 服务模式当前应使用的接口协议。

    显式协议直接用；auto 按 base_url 与模型名推断（与 tools\\ai_client.py
    resolve_asr_protocol 同一套规则，这里独立实现避免依赖 ai_mod 失败）。
    """
    try:
        ac = ai_mod().asr_config(ai_cfg or ai_load_config())
        p = str(ac.get("protocol") or "auto").strip().lower()
        if p in ("dashscope", "chat_audio"):
            return "chat_audio"      # 历史键归一到 chat_audio（两者同一实现）
        if p in ASR_PROTOCOLS and p != "auto":
            return p
        return _infer_asr_protocol(ac.get("base_url"), ac.get("model"))
    except Exception:  # noqa: BLE001
        pass
    # v1.14.2：ai_client 读取失败不再盲返 openai（实时模型经 OpenAI SDK 必断、
    # qwen-audio 族在 maas 无 /audio/transcriptions）——退一步直读磁盘配置推断。
    try:
        raw = ai_cfg if ai_cfg else ai_load_config()
    except Exception:  # noqa: BLE001
        raw = {}
    raw = raw or {}
    p = str(raw.get("asr_protocol") or "auto").strip().lower()
    if p in ("dashscope", "chat_audio"):
        return "chat_audio"
    if p in ASR_PROTOCOLS and p != "auto":
        return p
    return _infer_asr_protocol(str(raw.get("asr_base_url") or ""),
                               str(raw.get("asr_model") or ""))


def _asr_diarize_flag(val):
    """把配置里的开关值（bool / 1 / "true" / "yes" / "on"）归一成布尔。"""
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    return str(val or "").strip().lower() in ("1", "true", "yes", "on")


def asr_diarize_of(ai_cfg=None):
    """是否开启说话人分离（diarization）——与 asr_protocol_of 同一套读法。

    只有部分服务端原生支持（火山极速版 / AssemblyAI / Deepgram /
    ElevenLabs / 百炼 3.1 原生端点 / 百炼 Filetrans）；不支持的端点拿到
    True 也只是不产生 speaker 字段，字幕形态不变。
    """
    try:
        ac = ai_mod().asr_config(ai_cfg or ai_load_config())
        return _asr_diarize_flag(ac.get("diarize"))
    except Exception:  # noqa: BLE001
        pass
    try:
        raw = ai_cfg if ai_cfg else ai_load_config()
    except Exception:  # noqa: BLE001
        raw = {}
    return _asr_diarize_flag((raw or {}).get("asr_diarize"))


def _asr_diarize_on(asr_obj):
    """取本次转录是否要说话人分离。

    _submit 会把全局开关写进 asr_obj.diarize（分块重试、实时降级时沿用同一
    个值），没写就回落到读配置。
    """
    v = getattr(asr_obj, "diarize", None)
    if v is None:
        return asr_diarize_of()
    return _asr_diarize_flag(v)


def asr_separate_of(ai_cfg=None):
    """是否开启语音分离（separation）——与 asr_diarize_of 同一套读法。

    语音分离比说话人分离（diarization）更硬核：diarization 只回答"谁在
    什么时候说话"，separation 要在**两人同时说话**时把重叠的混合信号拆成
    各自独立的单人轨（音乐 reaction 里"把歌声从人声里剔除"也归这一路）。

    ⚠️ 当前版本**只保留开关与接口**，未内置声源分离模型（Demucs /
    MossFormer 等体积与算力开销较大）。开启后转录会在日志里记录待分离
    音频路径；后续接入时只需替换 `_asr_separate_audio` 的实现。
    """
    try:
        ac = ai_mod().asr_config(ai_cfg or ai_load_config())
        return _asr_diarize_flag(ac.get("separate"))
    except Exception:  # noqa: BLE001
        pass
    try:
        raw = ai_cfg if ai_cfg else ai_load_config()
    except Exception:  # noqa: BLE001
        raw = {}
    return _asr_diarize_flag((raw or {}).get("asr_separate"))


def _asr_separate_on(asr_obj):
    """取本次转录是否要语音分离（与 _asr_diarize_on 同构，供分块重试沿用）。"""
    v = getattr(asr_obj, "separate", None)
    if v is None:
        return asr_separate_of()
    return _asr_diarize_flag(v)


def _ensure_ffmpeg():
    """ffmpeg 引导（v2.3.1：asr 域→download 域的运行时耦合，按域间规则
    走函数内延迟 import；A4 收口时评估是否上移 shared）。"""
    from core.download.deps import ensure_ffmpeg
    return ensure_ffmpeg()


def _asr_separate_audio(audio_path, asr_obj=None):
    """语音分离的**接口占位**：把音频里的重叠人声拆成单人轨。

    约定（后续接入声源分离模型时按此实现即可，调用方无需改动）：
      · 入参：`audio_path` 原始音频；`asr_obj` 当前转录对象（可读配置）；
      · 返回：`[(标签, 音频路径), ...]` 列表——每个元素是一条**单人轨**，
        标签形如 `说话人1`（与 diarization 的编号口径一致），路径为分离后
        落盘的音频；无重叠 / 未启用时返回 `[(None, audio_path)]`（原轨）。
      · 音乐 reaction 场景：把"歌声"当作独立的一路返回（标签 `歌声`），
        调用方按标签决定是否剔除——这正是"把歌声给剔除出去"的落点。

    当前实现是**直通**（不分离，原样返回单轨），只做日志记录，便于确认
    开关已经贯通到引擎。真正的分离模型接入点见 docs/程序说明书(开发版).md。
    """
    try:
        _vc_log("[ASR] 语音分离已开启（接口占位，未内置分离模型），待处理音频：%s"
                % (audio_path,))
    except Exception:  # noqa: BLE001
        pass
    return [(None, audio_path)]


def asr_examples(cfg=None):
    """生成当前 ASR 配置对应的**非流式**调用示例（curl + Python）。

    为什么要有它：设置页「测试 ASR 配置」失败时，或者要在别的程序 / 脚本里
    集成同一套服务时，用户需要一条**自己能跑通**的命令，用来区分"是我程序
    的问题"还是"密钥 / 账号 / 模型的问题"。示例里的请求与引擎 `_asr_*_submit`
    一一对应（同一端点、同样的头与 body 形态），跑通它即等于验证了本程序。

    密钥一律用环境变量占位，不把明文写进可复制文本。
    返回 dict(protocol, title, curl, python, env, notes)。
    """
    try:
        ac = ai_mod().asr_config(cfg or ai_load_config())
    except Exception:  # noqa: BLE001
        ac = {"mode": "service", "base_url": "", "model": "", "api_key": ""}
    mode = str(ac.get("mode") or "service")
    base = str(ac.get("base_url") or "").strip().rstrip("/")
    model = str(ac.get("model") or "").strip()
    proto = "local" if mode == "local" else asr_protocol_of(cfg)
    notes = ["非流式：一次请求（或上传→提交→轮询）返回完整结果，"
             "不是 WebSocket 实时流；实时模型（*realtime*）用不了这种调用。",
             "示例与程序内实现一一对应：跑通它 = 这套密钥/地址/模型可用。"]

    if proto == "local":
        _lang = str(ac.get("language") or "").strip()
        return {
            "protocol": "local", "title": "本地 faster-whisper（不联网）",
            "env": {},
            "curl": "（本地模式不涉及 HTTP，没有 curl 示例）",
            "python": "\n".join([
                "from faster_whisper import WhisperModel",
                "",
                "model = WhisperModel(%r, device=\"auto\")   # 或模型目录" % (model or "large-v3"),
                "segments, info = model.transcribe(\"audio.mp3\", %s)"
                % (("language=%r" % _lang) if _lang else "language=None  # 自动检测"),
                "print(\"\".join(s.text for s in segments))",
            ]),
            "notes": notes + ["本地模型在本程序的「设置 → ASR 语音识别 → 本地独立模型」里配。"]
                    + (["识别语言已固定为 %s（%r）。" % (ac.get("language_label"), _lang)]
                       if _lang else []),
        }

    # ⚠️ 只给变量名与说明，**不把密钥明文写进可复制文本**（方便安全地
    #    贴文档 / 发同事；也让示例本身不因换密钥而失效）
    env = {"ASR_API_KEY": "设置页「ASR 密钥」里填的那个"}
    title = {
        "openai": "OpenAI Whisper 兼容", "azure": "Azure OpenAI",
        "chat_audio": "Chat 音频转写（百炼 Qwen-ASR / 小米 MiMo 等）",
        "dashscope": "Chat 音频转写（百炼 Qwen-ASR / 小米 MiMo 等）",
        "deepgram": "Deepgram",
        "elevenlabs": "ElevenLabs Scribe", "gemini": "Google Gemini",
        "volcengine": "火山引擎（豆包）录音识别极速版",
        "assemblyai": "AssemblyAI",
        "dashscope_native": "百炼原生端点（Qwen-Audio-3.0-ASR-Flash 等 ASR 专用模型）",
        "dashscope_filetrans": "百炼 Filetrans 异步文件转写（提交 → 轮询）",
    }.get(proto, proto)

    if proto == "openai":
        sd_base = asr_strip_endpoint_tail(base or "https://api.openai.com/v1",
                                          "/audio/transcriptions",
                                          "/audio/translations")
        url = sd_base + "/audio/transcriptions"
        mdl = model or "whisper-1"
        _lang = str(ac.get("language") or "").strip()
        curl = "\n".join([
            'curl -X POST "%s" \\' % url,
            '  -H "Authorization: Bearer $ASR_API_KEY" \\',
            '  -F "file=@audio.mp3" \\',
            '  -F "model=%s" \\' % mdl,
        ] + (['  -F "language=%s" \\' % _lang] if _lang else [])
        + [
            '  -F "response_format=verbose_json" \\',
            '  -F "timestamp_granularities[]=word"',
        ])
        py = "\n".join([
            "import os",
            "from openai import OpenAI",
            "",
            "client = OpenAI(base_url=%r, api_key=os.environ[\"ASR_API_KEY\"])" % sd_base,
            "with open(\"audio.mp3\", \"rb\") as f:",
            "    r = client.audio.transcriptions.create(",
            "        model=%r, file=f, response_format=\"verbose_json\",  # 非流式" % mdl,
        ] + (["        language=%r," % _lang] if _lang else [])
        + [
            "        timestamp_granularities=[\"word\"])",
            "print(r.text)",
        ])
        notes = notes + (["识别语言已固定为 %s（请求带 language=%r）。"
                          % (ac.get("language_label"), _lang)] if _lang else [])
    elif proto == "azure":
        res = base or "https://<你的资源名>.openai.azure.com"
        dep = model or "<部署名>"
        if "/openai/deployments/" in res:
            url = res if res.lower().endswith("/audio/transcriptions") else \
                res + "/audio/transcriptions"
        else:
            url = "%s/openai/deployments/%s/audio/transcriptions" % (res, dep)
        if "api-version=" not in url:
            url += "?api-version=2024-10-21"
        curl = "\n".join([
            'curl -X POST "%s" \\' % url,
            '  -H "api-key: $ASR_API_KEY" \\',
            '  -F "file=@audio.mp3" \\',
            '  -F "response_format=verbose_json"',
        ])
        py = "\n".join([
            "import os",
            "from openai import AzureOpenAI",
            "",
            "client = AzureOpenAI(azure_endpoint=%r, api_key=os.environ[\"ASR_API_KEY\"],"
            % res,
            "                       api_version=\"2024-10-21\")",
            "with open(\"audio.mp3\", \"rb\") as f:",
            "    r = client.audio.transcriptions.create(",
            "        model=%r, file=f, response_format=\"verbose_json\")   # 非流式" % dep,
            "print(r.text)",
        ])
    elif proto in ("chat_audio", "dashscope"):
        url = (base or "https://dashscope.aliyuncs.com/compatible-mode/v1") \
            + "/chat/completions"
        mdl = model or "qwen3-asr-flash"
        # body 用 python 现造：base64 的引号嵌套交给 shell 太脆，
        # 而且 base64 -w0 在 macOS 上不支持（GNU 专有参数）
        _body = ("python -c \"import base64,json;b=base64.b64encode("
                 "open('audio.mp3','rb').read()).decode();"
                 "print(json.dumps({'model':'%s','messages':[{'role':'user',"
                 "'content':[{'type':'input_audio','input_audio':{'data':"
                 "'data:audio/mp3;base64,'+b}}]}],'stream':False}))\"" % mdl)
        curl = "\n".join([
            "BODY=$(%s)" % _body,
            'curl -X POST "%s" \\' % url,
            '  -H "Authorization: Bearer $ASR_API_KEY" \\',
            '  -H "Content-Type: application/json" \\',
            '  -d "$BODY"',
        ])
        py = "\n".join([
            "import base64, os",
            "from openai import OpenAI",
            "",
            "client = OpenAI(base_url=%r, api_key=os.environ[\"ASR_API_KEY\"])"
            % (base or "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            "b64 = base64.b64encode(open(\"audio.mp3\", \"rb\").read()).decode()",
            "r = client.chat.completions.create(          # 非流式",
            "    model=%r," % mdl,
            "    messages=[{\"role\": \"user\", \"content\": [",
            "        {\"type\": \"input_audio\",",
            "         \"input_audio\": {\"data\": \"data:audio/mp3;base64,\" + b64}}]}],",
            "    stream=False)",
            "print(r.choices[0].message.content)",
        ])
        notes.append("音频走 input_audio 的 **Data URL**（自带 MIME）；"
                     "`stream=false` 才是非流式。")
        if "xiaomimimo" in base.lower() or "mimo" in mdl.lower():
            notes.append("小米 MiMo：ASR 也走 chat/completions（**没有** "
                         "/audio/transcriptions 端点，别填成 OpenAI Whisper 那样），"
                         "仅支持 mp3 / wav，返回纯文本（时间轴由本程序按句兜底）。")
    elif proto == "dashscope_native":
        # 百炼原生端点（Qwen-Audio-3.0-ASR-Flash / Fun-ASR-Flash 这类模型）：
        # 不是 chat/completions，走 /api/v1/services/aigc/multimodal-generation/generation
        url = _asr_native_url(base or "https://dashscope.aliyuncs.com/compatible-mode/v1")
        mdl = model or "qwen-audio-3.0-asr-flash"
        _body = ("python -c \"import base64,json;b=base64.b64encode("
                 "open('audio.wav','rb').read()).decode();"
                 "print(json.dumps({'model':'%s','input':{'messages':[{'role':"
                 "'user','content':[{'type':'input_audio','input_audio':{'data':"
                 "'data:audio/wav;base64,'+b}}]}]},'parameters':"
                 "{'format':'wav','sample_rate':16000}}))\"" % mdl)
        curl = "\n".join([
            "BODY=$(%s)" % _body,
            'curl -X POST "%s" \\' % url,
            '  -H "Authorization: Bearer $ASR_API_KEY" \\',
            '  -H "Content-Type: application/json" \\',
            '  -d "$BODY"',
        ])
        py = "\n".join([
            "import base64, os",
            "import requests      # 原生端点不认 OpenAI SDK，直接用裸 HTTP",
            "",
            "b64 = base64.b64encode(open(\"audio.wav\", \"rb\").read()).decode()",
            "r = requests.post(                       # 非流式",
            "    %r," % url,
            "    headers={\"Authorization\": \"Bearer \" + os.environ[\"ASR_API_KEY\"],",
            "             \"Content-Type\": \"application/json\"},",
            "    json={\"model\": %r," % mdl,
            "          \"input\": {\"messages\": [{\"role\": \"user\", \"content\": [",
            "              {\"type\": \"input_audio\",",
            "               \"input_audio\": {\"data\": \"data:audio/wav;base64,\" + b64}}]}]},",
            "          \"parameters\": {\"format\": \"wav\", \"sample_rate\": 16000}})",
            "d = r.json()",
            "# 返回没有 choices：文本在 output.text，句内字级时间戳在 output.sentence.words",
            "print(d[\"output\"].get(\"text\") or d[\"output\"][\"sentence\"][\"text\"])",
        ])
        notes.append("百炼**原生端点**（不是 chat/completions）：Qwen-Audio-3.0-ASR-Flash "
                     "这类文件转写模型只认 multimodal-generation；用 chat 协议调它会收到 "
                     "HTTP 400 空响应（模型本身没问题）。")
        notes.append("响应没有 choices 字段：识别文本在 `output.text`（整段）/"
                     "`output.sentence.text`（句级），`output.sentence.words[]` 带字级 "
                     "begin_time/end_time（毫秒）+ 独立标点。")
    elif proto == "deepgram":
        b = base or "https://api.deepgram.com"
        url = b if b.lower().endswith("/listen") else \
            (b + "/listen" if b.lower().endswith("/v1") else b + "/v1/listen")
        mdl = model or "nova-3"
        curl = "\n".join([
            'curl -X POST "%s?model=%s&smart_format=true&language=zh-CN" \\'
            % (url, mdl),
            '  -H "Authorization: Token $ASR_API_KEY" \\',
            '  -H "Content-Type: audio/mp3" \\',
            '  --data-binary @audio.mp3',
        ])
        py = "\n".join([
            "import os",
            "import requests      # 官方 SDK（deepgram-sdk）各版本写法差异较大，",
            "                     # 这里给等价的裸 HTTP 版本，最稳",
            "r = requests.post(",
            "    %r," % (url + "?model=%s&smart_format=true&language=zh-CN" % mdl),
            "    headers={\"Authorization\": \"Token \" + os.environ[\"ASR_API_KEY\"],",
            "             \"Content-Type\": \"audio/mp3\"},",
            "    data=open(\"audio.mp3\", \"rb\").read(),   # 原始字节，不是 multipart",
            "    timeout=600)",
            "j = r.json()[\"results\"][\"channels\"][0][\"alternatives\"][0]",
            "print(j[\"transcript\"])",
            "for w in j.get(\"words\", []):        # 词级时间轴（秒）",
            "    print(w[\"start\"], w[\"end\"], w[\"word\"])",
        ])
        notes.append("鉴权头是 `Authorization: Token <key>`（不是 Bearer）；"
                     "音频以原始字节放在 body 里。")
    elif proto == "elevenlabs":
        b = base or "https://api.elevenlabs.io"
        url = b if b.lower().endswith("/speech-to-text") else b + "/v1/speech-to-text"
        mdl = model or "scribe_v1"
        curl = "\n".join([
            'curl -X POST "%s" \\' % url,
            '  -H "xi-api-key: $ASR_API_KEY" \\',
            '  -F "model_id=%s" \\' % mdl,
            '  -F "timestamps_granularity=word" \\',
            '  -F "file=@audio.mp3"',
        ])
        py = "\n".join([
            "import os",
            "from elevenlabs.client import ElevenLabs",
            "",
            "client = ElevenLabs(api_key=os.environ[\"ASR_API_KEY\"])",
            "with open(\"audio.mp3\", \"rb\") as f:",
            "    r = client.speech_to_text.convert(        # 非流式",
            "        model_id=%r, file=f, timestamps_granularity=\"word\")" % mdl,
            "print(r.text)",
        ])
    elif proto == "gemini":
        b = base or "https://generativelanguage.googleapis.com"
        mdl = model or "gemini-2.5-flash"
        url = "%s/v1beta/models/%s:generateContent" % (b, mdl)
        _body = ("python -c \"import base64,json;b=base64.b64encode("
                 "open('audio.mp3','rb').read()).decode();"
                 "print(json.dumps({'contents':[{'parts':[{'inline_data':"
                 "{'mime_type':'audio/mp3','data':b}},{'text':"
                 "'请把这段音频逐字转写为文本，只输出转写内容。'}]}]}))\"")
        curl = "\n".join([
            "BODY=$(%s)" % _body,
            'curl -X POST "%s" \\' % url,
            '  -H "x-goog-api-key: $ASR_API_KEY" \\',
            '  -H "Content-Type: application/json" \\',
            '  -d "$BODY"',
        ])
        py = "\n".join([
            "import base64, os",
            "from google import genai            # pip install google-genai",
            "",
            "client = genai.Client(api_key=os.environ[\"ASR_API_KEY\"])",
            "b64 = base64.b64encode(open(\"audio.mp3\", \"rb\").read()).decode()",
            "r = client.models.generate_content(        # 非流式",
            "    model=%r," % mdl,
            "    contents=[{\"inline_data\": {\"mime_type\": \"audio/mp3\", \"data\": b64}},",
            "              \"请把这段音频逐字转写为文本，只输出转写内容。\"])",
            "print(r.text)",
        ])
        notes.append("Gemini 返回纯文本、没有时间轴；本程序按句切分后再按句长占比"
                     "给出近似时间轴。")
    elif proto == "volcengine":
        url = (base or "https://openspeech.bytedance.com") + \
            ("" if base.endswith("/recognize/flash")
             else "/api/v3/auc/bigmodel/recognize/flash")
        res_id = model or VOLC_DEFAULT_RESOURCE
        env = {"VOLC_APP_ID": "控制台的 APP ID",
               "VOLC_ACCESS_KEY": "控制台的 Access Token"}
        _body = ("python -c \"import base64,json,os;b=base64.b64encode("
                 "open('audio.mp3','rb').read()).decode();"
                 "print(json.dumps({'user':{'uid':os.environ['VOLC_APP_ID']},"
                 "'audio':{'data':b},'request':{'model_name':'bigmodel',"
                 "'enable_punc':True,'show_utterances':True}}))\"")
        curl = "\n".join([
            "BODY=$(%s)" % _body,
            'curl -X POST "%s" \\' % url,
            '  -H "X-Api-App-Key: $VOLC_APP_ID" \\',
            '  -H "X-Api-Access-Key: $VOLC_ACCESS_KEY" \\',
            '  -H "X-Api-Resource-Id: %s" \\' % res_id,
            '  -H "X-Api-Request-Id: $(uuidgen)" \\',
            '  -H "X-Api-Sequence: -1" \\',
            '  -H "Content-Type: application/json" \\',
            '  -d "$BODY"',
        ])
        py = "\n".join([
            "import base64, json, os, uuid",
            "import requests        # 火山没有官方同步 Python SDK，这是等价实现",
            "",
            "r = requests.post(",
            "    %r," % url,
            "    headers={\"X-Api-App-Key\": os.environ[\"VOLC_APP_ID\"],",
            "             \"X-Api-Access-Key\": os.environ[\"VOLC_ACCESS_KEY\"],",
            "             \"X-Api-Resource-Id\": \"%s\"," % res_id,
            "             \"X-Api-Request-Id\": str(uuid.uuid4()),",
            "             \"X-Api-Sequence\": \"-1\",",
            "             \"Content-Type\": \"application/json\"},",
            "    data=json.dumps({\"user\": {\"uid\": os.environ[\"VOLC_APP_ID\"]},",
            "                     \"audio\": {\"data\": base64.b64encode(",
            "                         open(\"audio.mp3\", \"rb\").read()).decode()},",
            "                     \"request\": {\"model_name\": \"bigmodel\",",
            "                                 \"show_utterances\": True}}),",
            "    timeout=600)",
            "print(r.headers.get(\"X-Api-Status-Code\"))     # 20000000 = 成功（在响应头！）",
            "print(r.json()[\"result\"][\"text\"])",
        ])
        notes.append("状态码在**响应头** `X-Api-Status-Code`（`20000000` 为成功）；"
                     "新版控制台只有一个 API Key 时，把前两个头换成 "
                     "`X-Api-Key: $ASR_API_KEY`。")
    elif proto == "dashscope_filetrans":
        root = _asr_dashscope_root(base)
        mdl = model or "qwen3-asr-flash-filetrans"
        if "filetrans" not in mdl.lower():
            mdl = mdl + "-filetrans"
        curl = "\n".join([
            "# 1) 取上传凭证（Filetrans 不收本地文件，音频须先传到临时存储）",
            'POL=$(curl -s "%s%s?action=getPolicy&model=%s" \\'
            % (root, ASR_UPLOAD_POLICY_PATH, mdl),
            '  -H "Authorization: Bearer $ASR_API_KEY")',
            "# 2) 按凭证把音频传到百炼临时存储（OSS 表单上传，file 字段放最后）",
            'curl -s -X POST "$(echo $POL | jq -r .data.upload_host)" \\',
            '  -F "key=$(echo $POL | jq -r .data.upload_dir)/audio.mp3" \\',
            '  -F "policy=$(echo $POL | jq -r .data.policy)" \\',
            '  -F "Signature=$(echo $POL | jq -r .data.signature)" \\',
            '  -F "OSSAccessKeyId=$(echo $POL | jq -r .data.oss_access_key_id)" \\',
            '  -F "x-oss-object-acl=private" -F "x-oss-forbid-overwrite=true" \\',
            '  -F "file=@audio.mp3"',
            "# 3) 提交任务（oss:// 链接 + 两个必需头）",
            'ID=$(curl -s -X POST "%s%s" \\' % (root, ASR_FILETRANS_PATH),
            '  -H "Authorization: Bearer $ASR_API_KEY" \\',
            '  -H "Content-Type: application/json" \\',
            '  -H "X-DashScope-Async: enable" \\',
            '  -H "X-DashScope-OssResourceResolve: enable" \\',
            "  -d '{\"model\": \"%s\", \"input\": {\"file_urls\": "
            "[\"oss://<UPLOAD_DIR>/audio.mp3\"]}, \"parameters\": "
            "{\"diarization_enabled\": true}}' | jq -r .output.task_id)" % mdl,
            "# 4) 轮询任务；结果 JSON 地址在 output.results[0].transcription_url",
            'curl -s "%s/api/v1/tasks/$ID" -H "Authorization: Bearer $ASR_API_KEY"'
            % root,
        ])
        py = "\n".join([
            "import os, time, requests",
            "",
            "key = os.environ['ASR_API_KEY']",
            "root = %r" % root,
            "model = %r" % mdl,
            "",
            "# 程序内部就是这四步：凭证 → 传临时存储 → 提交 → 轮询下载",
            "pol = requests.get(root + '/api/v1/uploads',",
            "                   params={'action': 'getPolicy', 'model': model},",
            "                   headers={'Authorization': 'Bearer ' + key}",
            "                   ).json()['data']",
            "key_name = pol['upload_dir'] + '/audio.mp3'",
            "requests.post(pol['upload_host'],",
            "              data={'key': key_name, 'policy': pol['policy'],",
            "                    'Signature': pol['signature'],",
            "                    'OSSAccessKeyId': pol['oss_access_key_id'],",
            "                    'x-oss-object-acl': pol['x_oss_object_acl'],",
            "                    'x-oss-forbid-overwrite': pol['x_oss_forbid_overwrite'],",
            "                    'success_action_status': '200'},",
            "              files={'file': ('audio.mp3', open('audio.mp3', 'rb'))})",
            "",
            "task = requests.post(root + '/api/v1/services/audio/asr/transcription',",
            "                     headers={'Authorization': 'Bearer ' + key,",
            "                              'X-DashScope-Async': 'enable',",
            "                              'X-DashScope-OssResourceResolve': 'enable'},",
            "                     json={'model': model,",
            "                           'input': {'file_urls': ['oss://' + key_name]},",
            "                           'parameters': {'diarization_enabled': True}}",
            "                     ).json()['output']['task_id']",
            "",
            "while True:",
            "    out = requests.get(root + '/api/v1/tasks/' + task,",
            "                       headers={'Authorization': 'Bearer ' + key}",
            "                       ).json()['output']",
            "    if out['task_status'] in ('SUCCEEDED', 'FAILED'):",
            "        break",
            "    time.sleep(5)",
            "",
            "url = out['results'][0]['transcription_url']     # 结果要再下载一次",
            "sent = requests.get(url).json()['transcripts'][0]['sentences']",
            "for s in sent:                                   # 开分离后每句带 speaker_id",
            "    print(s.get('speaker_id'), s['text'])",
        ])
        notes.append(
            "⚠️ 官方限制：临时 URL 有效期 48 小时、凭证接口限流 100 QPS，文档"
            "标注「请勿用于生产环境」；说话人分离仅支持单声道、建议 ≤ 2 小时。"
            "qwen3 系模型的 input 字段是 file_url（单对象），qwen-audio / "
            "fun-asr 是 file_urls（数组），程序会按模型自动选。")
    else:   # assemblyai
        b = base or "https://api.assemblyai.com"
        models = [x.strip() for x in (model or "").split(",") if x.strip()] \
            or list(ASSEMBLYAI_DEFAULT_MODELS)
        models_json = "[\"" + "\", \"".join(models) + "\"]"
        curl = "\n".join([
            "# 1) 上传本地文件（raw bytes，不是 multipart）",
            'UP=$(curl -s -X POST "%s/v2/upload" \\' % b,
            '  -H "authorization: $ASR_API_KEY" --data-binary @audio.mp3 | jq -r .upload_url)',
            "# 2) 提交转写任务",
            'ID=$(curl -s -X POST "%s/v2/transcript" \\' % b,
            '  -H "authorization: $ASR_API_KEY" -H "content-type: application/json" \\',
            "  -d '{\"audio_url\": \"'$UP'\", \"speech_models\": %s}' | jq -r .id)"
            % models_json,
            "# 3) 轮询到完成（非流式：结果一次性取回）",
            'while :; do',
            '  S=$(curl -s "%s/v2/transcript/$ID" -H "authorization: $ASR_API_KEY"' % b,
            "        | jq -r .status)",
            '  [ "$S" = "completed" ] && break; [ "$S" = "error" ] && break; sleep 3',
            'done',
            'curl -s "%s/v2/transcript/$ID" -H "authorization: $ASR_API_KEY" | jq -r .text' % b,
        ])
        py = "\n".join([
            "import os",
            "import assemblyai as aai           # pip install assemblyai",
            "",
            "aai.settings.api_key = os.environ[\"ASR_API_KEY\"]",
            "cfg = aai.TranscriptionConfig(speech_models=%r, language_detection=True)"
            % models,
            "t = aai.Transcriber().transcribe(\"audio.mp3\", config=cfg)   # 阻塞到完成",
            "print(t.text)",
            "for w in (t.words or []):          # 词级时间轴（毫秒）",
            "    print(w.start, w.end, w.text)",
        ])
        notes.append("鉴权头是 `authorization: <key>`（**不带 Bearer**）；"
                     "`speech_models` 必填（官方无默认值）；词级时间轴单位是**毫秒**。"
                     "curl 示例用到 jq（Windows 上直接看 Python 版即可）。")

    return {"protocol": proto, "title": title, "curl": curl, "python": py,
            "env": env, "notes": notes}


def asr_examples_text(cfg=None):
    """把 asr_examples() 拼成一份可直接给人看 / 另存的纯文本。"""
    ex = asr_examples(cfg)
    out = ["# %s（协议：%s）" % (ex["title"], ex["protocol"]), ""]
    if ex.get("env"):
        out.append("# 先设置环境变量：")
        for k, note in ex["env"].items():
            out.append("#   export %s='%s'" % (k, note))
        out.append("")
    out += ["# ---- curl（非流式）----", ex["curl"], "",
            "# ---- Python（非流式）----", ex["python"], "", "# 说明"]
    out += ["#  · " + n for n in ex.get("notes", [])]
    return "\n".join(out)


def _asr_audio_format(data: bytes) -> str:
    """按魔数识别音频容器（DashScope input_audio 需要显式 format）。"""
    head = bytes(data[:16]) if data else b""
    if head.startswith(b"RIFF") and head[8:12] == b"WAVE":
        return "wav"
    if head.startswith(b"ID3") or (len(head) > 2 and head[0] == 0xFF
                                   and (head[1] & 0xE0) == 0xE0):
        return "mp3"
    if head.startswith(b"OggS"):
        return "ogg"
    if head.startswith(b"fLaC"):
        return "flac"
    return "mp3"


def _asr_text_to_segments(text, duration_sec):
    """把无时间戳的纯文本识别结果按句切分并按时长占比分配时间轴。

    返回与引擎 WhisperAPI._make_segments 兼容的
    [{"text":…, "start":秒, "end":秒}, …]；文本为空返回空表。
    """
    import re
    text = str(text or "").strip()
    if not text:
        return []
    # 先按句末标点/换行切句，再把超长句按逗号级标点二次切
    pieces = [p for p in re.split(r"(?<=[。！？!?；;…])\s*|\n+", text) if p.strip()]
    refined = []
    for p in pieces:
        p = p.strip()
        if len(p) > 42:
            parts = [q for q in re.split(r"(?<=[，,、])", p) if q.strip()]
        else:
            parts = [p]
        refined.extend(parts)
    if not refined:
        refined = [text]
    weights = [max(len(s), 1) for s in refined]
    total = float(sum(weights))
    dur_ms = max(int(float(duration_sec or 0) * 1000), 1000)
    segs, t = [], 0
    for s, w in zip(refined, weights):
        d = int(dur_ms * w / total)
        segs.append({"text": s, "start": round(t / 1000.0, 3),
                     "end": round((t + d) / 1000.0, 3)})
        t += d
    if segs:
        segs[-1]["end"] = round(dur_ms / 1000.0, 3)
    return segs


def _asr_is_cjk(ch):
    return bool(ch) and ord(ch) > 0x2E7F


def _asr_join_words(tokens):
    """拼词成句：中文之间不加空格，拉丁词之间加。"""
    out = ""
    for t in tokens:
        if out and not _asr_is_cjk(out[-1]) and not _asr_is_cjk(t[:1]):
            out += " "
        out += t
    return out


def _asr_is_sentence_end(tok):
    """词尾是否句末（词级 ASR 的 punctuated_word 会带标点）。

    英文句点一律算句末 —— **不需要**给小数开特例：词级结果不会把 `3.5`
    切成 `3.` + `5`（`3.5` 的末位是 `5`，本来就落不进句点分支）。
    """
    if not tok:
        return False
    return tok[-1] in "。！？!?；;…."


def _asr_words_to_segments(words, max_gap=0.9, max_chars=42):
    """词级时间轴 → 句级 segments（Deepgram / ElevenLabs / 火山 / 百炼原生用）。

    断句四条件：句末标点、停顿超过 max_gap 秒、当前句超长、**说话人切换**。
    最后一条为说话人分离（diarization）专用——不在切换处断开的话，同一条
    字幕里会混进两个人的发言，标签只能落在其中一个头上，看的人更乱。

    words 里带 `speaker` 时，产出段会多一个 `speaker` 字段（原样保留服务端
    的原始标识，统一编号交给 _asr_apply_speaker_labels 做）。不带 speaker
    时行为与 v1.15.7 之前完全一致（自检基线依赖这一点）。
    """
    segs = []
    cur, start, end, cur_spk = [], None, None, None

    def _flush():
        if not cur:
            return
        seg = {"text": _asr_join_words(cur),
               "start": round(start or 0, 3),
               "end": round(end if end is not None else (start or 0), 3)}
        if cur_spk is not None:
            seg["speaker"] = cur_spk
        segs.append(seg)

    for w in words or []:
        tok = str(w.get("word") or w.get("text") or "").strip()
        if not tok:
            continue
        try:
            s = float(w.get("start") or 0)
            e = float(w.get("end") or s)
        except (TypeError, ValueError):
            continue
        spk = w.get("speaker")
        spk = None if spk is None else str(spk)
        # 说话人切换 → 立即断句（先于停顿/长度判断，避免把新人的话并进旧句）
        if cur and spk is not None and cur_spk is not None and spk != cur_spk:
            _flush()
            cur, start, cur_spk = [], None, None
        if cur and (s - (end if end is not None else s) > max_gap
                    or sum(len(x) for x in cur) >= max_chars):
            _flush()
            cur, start, cur_spk = [], None, None
        if start is None:
            start = s
        cur.append(tok)
        end = e
        if cur_spk is None:
            cur_spk = spk
        if _asr_is_sentence_end(tok):
            _flush()
            cur, start, cur_spk = [], None, None
    _flush()
    return segs


#: 说话人标签形态：段文本前置，形如「[说话人1] 台词」
ASR_SPEAKER_PREFIX = "[说话人%d] "


def _asr_apply_speaker_labels(resp):
    """把段上的 speaker 落成文本前缀「[说话人1] …」。

    为什么拼进文本而不是给 ASRDataSeg 加字段：下游 ASRDataSeg 只有
    text/start_time/end_time 三个字段，翻译、AI 校准、字幕编辑页、SRT 导出
    全都只认 text。加字段要把这几处一起改；拼前缀则整条链路零改动。

    服务端返回的标识形态各异（火山是数字串、AssemblyAI 是 A/B/C、ElevenLabs
    是 spk_0），这里按**首次出现顺序**统一重编成 1、2、3……保证同一个结果
    内编号连续且与出场顺序一致。

    ⚠️ 有 speaker 时会同时摘掉 `words`：词级模式下 whisper_api._make_segments
    是一个词一条字幕，前缀会重复糊在每一个词上；说话人分离本就按话轮成段，
    强制走句级。
    """
    if not isinstance(resp, dict):
        return resp
    segs = resp.get("segments")
    if not isinstance(segs, list) or not segs:
        return resp
    order = {}
    hit = False
    for seg in segs:
        if not isinstance(seg, dict):
            continue
        raw = seg.get("speaker")
        if raw is None:
            continue
        key = str(raw)
        if key not in order:
            order[key] = len(order) + 1
        seg["text"] = (ASR_SPEAKER_PREFIX % order[key]) + str(seg.get("text") or "")
        hit = True
    if hit:
        resp.pop("words", None)
    return resp


def _asr_words_response(text, words):
    """统一成 {text, segments, words}：引擎两条消费路径（句级 / 词级）都能吃。"""
    clean = []
    for w in words or []:
        tok = str(w.get("word") or w.get("text") or "").strip()
        if not tok:
            continue
        try:
            s = float(w.get("start") or 0)
            e = float(w.get("end") or s)
        except (TypeError, ValueError):
            continue
        item = {"word": tok, "start": s, "end": e}
        spk = w.get("speaker")
        if spk is not None:
            item["speaker"] = str(spk)
        clean.append(item)
    out = {"text": str(text or ""), "segments": _asr_words_to_segments(clean)}
    if clean:
        out["words"] = clean
    return out


def _asr_plan_endpoint_hint(asr_obj):
    """订阅套餐端点配套提示（转录失败时追加，非套餐端点返回空串）。

    百炼 Token Plan / Coding Plan、智谱与火山 Coding Plan 均为专属端点且
    密钥不跨方案通用；套餐密钥打错端点时服务端常常只回空体 400/500，用户
    无从下手，故在此点名各方案端点。
    """
    b = str(getattr(asr_obj, "base_url", "") or "").lower()
    if not any(k in b for k in ("token-plan", "coding.", "/api/coding",
                                "maas.aliyuncs")):
        return ""
    return ("；端点与密钥须同属一个计费方案（百炼按量 "
            "dashscope.aliyuncs.com/compatible-mode/v1、Token Plan "
            "token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1、"
            "火山方舟 /api/v3（Coding Plan 为 /api/coding/v3）、智谱 "
            "/api/paas/v4（Coding Plan 为 /api/coding/paas/v4）——套餐密钥"
            "打错端点只会得到空体错误；Qwen-Audio-3.0-ASR-Flash 另有专用原生"
            "端点 /api/v1/services/aigc/multimodal-generation/generation，"
            "程序会按模型自动改走）")


#: 实例模型清单缓存：base_url -> (取回时间, [模型名…])
_ASR_MODELS_CACHE = {}


def asr_instance_models(base_url, api_key, ttl=600):
    """查 `GET {base}/models` 拿该实例**当前可用**的模型名列表（带缓存）。

    为什么需要它：百炼专属实例的模型清单**会变**。实测（2026-09-30）用户实例
    上 `qwen-audio-3.0-asr-flash` 消失后，原生端点与 chat/completions **都回
    400 空体 `{}`**——光看响应完全看不出原因，只能靠模型清单定位。拿不到
    返回 []（绝不干扰原错误路径）。
    """
    base = asr_strip_endpoint_tail(str(base_url or "").strip()).rstrip("/")
    if not base:
        return []
    hit = _ASR_MODELS_CACHE.get(base)
    if hit and (time.time() - hit[0]) < ttl:
        return hit[1]
    models = []
    try:
        import requests
        url = base + "/models"
        r = requests.get(url,
                         headers={"Authorization": "Bearer " + str(api_key or "")},
                         proxies=http_proxies_for(url), timeout=20)
        if r.status_code == 200:
            data = (r.json() or {}).get("data") or []
            models = [str(m.get("id")) for m in data if m.get("id")]
    except Exception:  # noqa: BLE001
        models = []
    _ASR_MODELS_CACHE[base] = (time.time(), models)
    return models


def asr_missing_model_hint(asr_obj):
    """模型不在该实例里时的**可操作**提示；判断不了返回空串。

    这是「转录失败」最常见的真实原因：用户配置没动，但服务端实例的模型清单
    变了。原文案只猜"模型与端点不配套"，会把人往改协议的方向带（而协议其实
    已经是对的），所以这里直接查清单点名，并给出该换什么。
    """
    model = str(getattr(asr_obj, "model", "") or "").strip()
    if not model:
        return ""
    models = asr_instance_models(getattr(asr_obj, "base_url", ""),
                                 getattr(asr_obj, "api_key", ""))
    if not models or model in models:
        return ""
    # 「可转写」的音频模型：TTS / 实时对话族虽然名字带 audio，却做不了录音
    # 转写（前者输出音频、后者是流式对话），算进来会把误诊说成"还有能用的"。
    audio_like = [m for m in models
                  if any(h in m.lower() for h in
                         ("asr", "audio", "whisper", "paraformer", "sensevoice"))
                  and not any(k in m.lower() for k in _TTS_HINTS)
                  and not any(k in m.lower() for k in ASR_REALTIME_HINTS)]
    # 误诊拦截（2026-10-05 实测）：清单里**一个音频类模型都没有**、而配置的
    # 又是原生端点的 ASR 模型（qwen-audio-*-asr-*）时，多半是这份清单压根不
    # 列 ASR 模型，而不是模型下架。实证：百炼 Token Plan 共享端点
    # token-plan.cn-beijing.maas.aliyuncs.com 的 `GET /models` 只回 16 个
    # 文本/图像/TTS/实时模型，不含 qwen-audio-3.0-asr-flash；但用同一个 Key
    # POST 原生端点，该模型能正常受理（回 400 空体 = 只是这段没语音），而
    # qwen3-asr-flash 才真回 404 Model not exist。此时报"模型已下架"会把用户
    # 引去改一份本来正确的配置，直接不提示。
    if not audio_like and is_dashscope_native_asr(model):
        return ""
    tip = ("；⚠️ `GET /models` 返回的实例清单里**找不到**模型「%s」"
           "（服务端模型清单会变，配置没动也可能失效）。" % model)
    if audio_like:
        tip += "其中音频相关的是：%s。" % "、".join(audio_like[:6])
    else:
        tip += ("而且**一个音频/识别类模型都没有**（现有：%s）。"
                % "、".join(models[:8]))
    # 免责：专属实例的 /models 有时不列 ASR 模型（历史踩过），所以清单只能
    # 当线索、不能当判决——否则会把"其实还能用"的用户劝去换配置。
    tip += ("（注意：专属实例的 /models 有时**不列** ASR 模型，清单只能作线索；"
            "若连一个音频类模型都没有，多半是该实例的 ASR 模型已下架——可改用"
            "公共百炼 dashscope.aliyuncs.com/compatible-mode/v1 + qwen3-asr-flash，"
            "或在「转录模型来源」里改用本地模型）")
    return tip


def _asr_err_hint(resp):
    """把 HTTP 错误响应转成"能照着修"的提示（密钥 / 模型名 / 其它）。"""
    text = ""
    try:
        text = (resp.text or "")[:300]
    except Exception:  # noqa: BLE001
        pass
    low = text.lower()
    if resp.status_code in (401, 403):
        return ("HTTP %d（密钥被拒：确认密钥属于这个服务/实例，并且在设置页按过"
                "「保存并应用」）: %s" % (resp.status_code, text))
    if "too large" in low or "file size" in low:
        # v1.14.2：百炼多模态端点对单次请求内嵌音频有体积上限，整段直传
        # （尤其降级 qwen3-asr-flash 时）会撞 This Multimodal file size is
        # too large——提示必须给"切短/压缩"出路，且不能被下面的实时误判分支吞掉。
        return ("HTTP %d（音频体积超过该端点单次上限：程序会自动把超限音频压成"
                "低码率 MP3 再传，仍超限说明音频太长——请把音频切短分段后分别转录，"
                "或改用支持大文件的服务端点）: %s" % (resp.status_code, text))
    if "too long" in low:
        return ("HTTP %d（音频时长超过该端点单次上限：程序会自动对半切分重试，"
                "仍失败则请把音频切短分段，或换支持长音频的模型）: %s"
                % (resp.status_code, text))
    if ("invalidparameter" in low or "invalid parameter" in low
            or "model not" in low or "unsupported" in low):
        return ("HTTP %d（参数或模型名不被该端点支持——注意实时（realtime）"
                "模型不能一次性上传调用）: %s" % (resp.status_code, text))
    if resp.status_code in (400, 500) and (
            not text.strip() or text.strip() == "{}"
            or ("internalerror" in low and "unknown" in low)):
        return ("HTTP %d（端点返回空体/未知错误：① 模型与端点不配套——"
                "Qwen-Audio-3.0-ASR-Flash（qwen-audio-3.0-asr-flash）这类百炼"
                "原生 ASR 模型走的是 multimodal-generation 端点，拿兼容模式的 "
                "chat/completions 打恒回空体 400，请把「接口协议」选为"
                "「百炼原生（ASR 专用端点）」或留自动识别；② 名字带 *realtime* "
                "的实时对话/翻译模型（如 livetranslate）、*tts* 语音合成模型"
                "都做不了录音转写，请改 qwen3-asr-flash、"
                "FunAudioLLM/SenseVoiceSmall、whisper-1 等；"
                "maas 专属实例请到百炼控制台确认实例已部署该模型"
                "（其 /models 列表不显示 ASR 模型，以控制台为准）；"
                "并确认地址与模型属同一计费套餐）: %s"
                % (resp.status_code, text))
    return "HTTP %d: %s" % (resp.status_code, text)


def _asr_normalize_resp(resp, asr_obj):
    """把各协议响应归一成引擎 _make_segments 可解析的 dict。

    已含 segments/words（带原生时间轴）→ 原样返回；纯文本/仅 text →
    按句切分 + 时长占比生成近似时间轴（无时间戳协议的兜底）。
    """
    if isinstance(resp, dict) and ("segments" in resp or "words" in resp):
        return _asr_apply_speaker_labels(resp)
    if isinstance(resp, dict):
        text = str(resp.get("text") or "")
    else:
        text = str(resp or "")
    return {"text": text,
            "segments": _asr_text_to_segments(text, getattr(asr_obj,
                                                            "audio_duration",
                                                            0))}


def _asr_azure_submit(asr_obj):
    """Azure OpenAI 语音转文字：POST …/deployments/<部署>/audio/transcriptions。

    地址允许填资源根或填到 deployments/<部署名>（自动补齐路径与 api-version），
    鉴权用 api-key 头（与 LLM 的 Azure 适配同一套约定）。
    """
    import requests
    base = (asr_obj.base_url or "").strip().rstrip("/")
    model = (asr_obj.model or "").strip()
    if "/openai/deployments/" not in base.lower():
        base = f"{base}/openai/deployments/{model}" if model else \
            f"{base}/openai/deployments"
    low = base.lower()
    if not low.endswith("/audio/transcriptions"):
        base = base + "/audio/transcriptions"
    if "api-version=" not in base:
        base = f"{base}{'&' if '?' in base else '?'}api-version=2024-10-21"
    fmt = _asr_audio_format(asr_obj.file_binary or b"")
    form = {"response_format": "verbose_json"}
    if asr_obj.language:
        form["language"] = asr_obj.language
    if asr_obj.prompt:
        form["prompt"] = asr_obj.prompt
    r = requests.post(
        base, headers={"api-key": asr_obj.api_key}, data=form,
        files={"file": (f"audio.{fmt}", asr_obj.file_binary or b"",
                        f"audio/{fmt}")},
        proxies=http_proxies_for(base), timeout=300)
    if r.status_code != 200:
        raise RuntimeError(f"Azure ASR HTTP {r.status_code}: {r.text[:200]}")
    try:
        return r.json()
    except ValueError:
        return {"text": r.text}


#: 多模态请求（chat_audio 的 Data URL / gemini 的 inline_data）内嵌音频的
#: 原始字节上限：base64 会再放大约 4/3，6.5MB 原始 ≈ 8.7MB 编码后，贴着百炼
#: compatible-mode 多模态请求体上限留余量。超限先压缩，再不行由服务端报体积错。
ASR_INLINE_AUDIO_MAX_RAW = 6_500_000

#: "audio is too long" 自动对半切分的最大递归层数（2^3=8 段封顶，防无限拆）
ASR_SPLIT_MAX_DEPTH = 3


def _asr_shrink_audio_blob(blob, max_raw_bytes):
    """超过内嵌上限的音频 → ffmpeg 压成低码率单声道 MP3（v1.14.2）。

    chat_audio / gemini 这类"音频进 JSON"的协议，原始文件直接 base64 会撑爆
    请求体上限（百炼报 Multimodal file size is too large）。语音识别对码率不
    敏感，32k/16k 单声道 MP3 足够。任何一步失败（无 ffmpeg/解码失败/越压越大）
    都**原样返回**，让服务端回它自己的错误码——绝不把用户音频弄丢或弄坏。
    """
    blob = blob or b""
    if len(blob) <= max_raw_bytes:
        return blob
    try:
        ffmpeg, _ffprobe = _ensure_ffmpeg()
    except Exception:  # noqa: BLE001
        ffmpeg = ""
    if not ffmpeg:
        return blob
    import subprocess as _sp
    import tempfile as _tf
    src = dst = ""
    try:
        with _tf.NamedTemporaryFile(suffix="." + _asr_audio_format(blob),
                                    delete=False) as tf:
            tf.write(blob)
            src = tf.name
        dst = src + ".shrink.mp3"
        for br in ("48k", "32k", "16k"):
            try:
                os.unlink(dst)
            except OSError:
                pass
            _sp.run([ffmpeg, "-y", "-i", src, "-vn", "-ac", "1",
                     "-b:a", br, dst],
                    capture_output=True, check=True, timeout=300,
                    creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0)
                    if os.name == "nt" else 0)
            data = open(dst, "rb").read()
            if data and len(data) <= max_raw_bytes:
                return data
        return blob          # 压到底仍超限/全部失败：原样交给服务端判
    except Exception:  # noqa: BLE001 非音频坏数据或 ffmpeg 报错
        return blob
    finally:
        for p in (src, dst):
            if p:
                try:
                    os.unlink(p)
                except OSError:
                    pass


def _asr_split_audio_blob(blob):
    """按中点切成（前半, 后半）两段 wav；切不了返回 None（v1.14.2）。

    服务端回 "The audio is too long" 时的自动补救：单请求超长 ⇒ 对半切开分别
    提交、文本顺序拼回（时间轴由本程序按段占比近似，见 _asr_normalize_resp）。
    """
    if not blob:
        return None
    try:
        ffmpeg, ffprobe = _ensure_ffmpeg()
    except Exception:  # noqa: BLE001
        return None
    if not ffmpeg or not ffprobe:
        return None
    import json as _json
    import subprocess as _sp
    import tempfile as _tf
    src = o1 = o2 = ""
    try:
        with _tf.NamedTemporaryFile(suffix="." + _asr_audio_format(blob),
                                    delete=False) as tf:
            tf.write(blob)
            src = tf.name
        pr = _sp.run([ffprobe, "-v", "error", "-show_entries",
                      "format=duration", "-of", "json", src],
                     capture_output=True, text=True, timeout=60,
                     creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0)
                     if os.name == "nt" else 0)
        dur = float((_json.loads(pr.stdout or "{}")
                     .get("format") or {}).get("duration") or 0)
        if dur < 2:
            return None                       # 太短不值得切
        half = dur / 2.0
        o1, o2 = src + ".a.wav", src + ".b.wav"
        _sp.run([ffmpeg, "-y", "-i", src, "-t", "%.3f" % half,
                 "-vn", "-ac", "1", o1],
                capture_output=True, check=True, timeout=300,
                creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0)
                if os.name == "nt" else 0)
        _sp.run([ffmpeg, "-y", "-i", src, "-ss", "%.3f" % half,
                 "-vn", "-ac", "1", o2],
                capture_output=True, check=True, timeout=300,
                creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0)
                if os.name == "nt" else 0)
        a = open(o1, "rb").read()
        b = open(o2, "rb").read()
        return (a, b) if a and b else None
    except Exception:  # noqa: BLE001
        return None
    finally:
        for p in (src, o1, o2):
            if p:
                try:
                    os.unlink(p)
                except OSError:
                    pass


def _asr_chat_audio_submit(asr_obj, depth=0):
    """Chat 音频转写（OpenAI 兼容 chat/completions + input_audio）：

    POST {base}/chat/completions，音频以 input_audio 进多模态 messages。
    这一族目前包括：**阿里云百炼** Qwen-ASR（qwen3-asr-flash / qwen-audio-asr，
    含 maas 专属实例）、**小米 MiMo**（mimo-v2.5-asr）。

    ⚠️ `data` 必须是 **Data URL**（`data:audio/mp3;base64,…`）：两家官方示例
    都是这个形态，它自带 MIME、不必再给 format；只发裸 base64 会被判成无效
    音频。⚠️ 这些服务**没有** `/audio/transcriptions` 端点，别按 openai 协议调。
    ⚠️ 音频格式支持有限（百炼/MiMo 都主打 mp3、wav），其它容器请先转码。
    """
    import base64
    import requests
    base = (asr_obj.base_url or "").strip().rstrip("/")
    if not base.lower().endswith("/chat/completions"):
        base = base + "/chat/completions"
    # v1.14.2：整段直传是「Multimodal file size is too large」的头号来源
    # （尤其实时模型断连后自动降级 qwen3-asr-flash 走的就是这条路）——
    # 超过内嵌上限先压成低码率 MP3 再进 Data URL。
    blob = _asr_shrink_audio_blob(asr_obj.file_binary or b"",
                                  ASR_INLINE_AUDIO_MAX_RAW)
    fmt = _asr_audio_format(blob)
    b64 = base64.b64encode(blob).decode("ascii")
    content = [{"type": "input_audio",
                "input_audio": {"data": "data:audio/%s;base64,%s" % (fmt, b64)}}]
    if asr_obj.prompt:
        content.append({"type": "text", "text": asr_obj.prompt})
    body = {"model": asr_obj.model,
            "messages": [{"role": "user", "content": content}],
            "stream": False}
    lang = str(getattr(asr_obj, "language", "") or "").strip()
    if lang and lang not in ("auto", "zh"):
        body["asr_options"] = {"language": lang}
    r = requests.post(
        base, json=body,
        headers={"Authorization": "Bearer " + asr_obj.api_key,
                 "Content-Type": "application/json"},
        proxies=http_proxies_for(base), timeout=600)
    if r.status_code != 200:
        low = (r.text or "").lower()
        if ("too long" in low or "duration" in low) \
                and depth < ASR_SPLIT_MAX_DEPTH:
            halves = _asr_split_audio_blob(blob)
            if halves:
                import types as _types
                parts = []
                for hb in halves:
                    sub = _types.SimpleNamespace(
                        base_url=asr_obj.base_url, model=asr_obj.model,
                        api_key=asr_obj.api_key,
                        language=getattr(asr_obj, "language", ""),
                        prompt=getattr(asr_obj, "prompt", ""),
                        diarize=getattr(asr_obj, "diarize", None),
                        file_binary=hb)
                    parts.append(_asr_chat_audio_submit(sub, depth + 1))
                return "".join(parts)
        if "too long" in low or "duration" in low:
            raise RuntimeError(
                "ASR 服务：音频时长超限且自动切分重试已到底（不再继续切短），"
                "请把音频切短分段后分别转录，或换支持长音频的模型。"
                "原始错误：" + _asr_err_hint(r))
        raise RuntimeError("ASR 服务 " + _asr_err_hint(r)
                           + _asr_plan_endpoint_hint(asr_obj))
    try:
        data = r.json()
        cont = data["choices"][0]["message"].get("content")
        if isinstance(cont, list):        # 多模态响应可能是 [{text:…}]
            cont = "".join(str(x.get("text") or "") for x in cont
                           if isinstance(x, dict))
        return str(cont or "")
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"ASR 响应格式无法解析：{e}; body={r.text[:200]}")


#: 历史名（可能出现在旧配置 / 日志 / 自检里）：两个名字指同一实现
_asr_dashscope_submit = _asr_chat_audio_submit


def _asr_native_output(resp):
    """百炼原生 ASR 响应 → {"text", "segments"}（词级时间轴优先）。

    原生端点**没有 choices**：文本在 `output.sentence.text` / `output.text`
    （专属实例还会在顶层再复制一份 `sentence`/`text`）；`output.sentence.words[]`
    带毫秒级 begin_time/end_time 与独立 punctuation → 原生词级时间轴，
    聚合交给 _asr_words_to_segments（与 Deepgram/ElevenLabs 同一条路）。
    """
    try:
        data = resp.json()
    except (ValueError, AttributeError):
        data = {}
    if not isinstance(data, dict):
        return {"text": "", "segments": []}
    out = data.get("output") if isinstance(data.get("output"), dict) else {}
    # 开启说话人分离后官方改走 output.sentences[]（每个句子带 speaker_id），
    # 与不分离时的 output.sentence（单个对象）不是同一个字段——先认数组形态。
    sents = out.get("sentences")
    if not isinstance(sents, list):
        sents = data.get("sentences") \
            if isinstance(data.get("sentences"), list) else None
    if sents:
        words, texts = [], []
        for s in sents:
            if not isinstance(s, dict):
                continue
            t = str(s.get("text") or "")
            if t:
                texts.append(t)
            spk = s.get("speaker_id")
            for w in (s.get("words") or []):
                if not isinstance(w, dict):
                    continue
                tok = (str(w.get("text") or "")
                       + str(w.get("punctuation") or "")).strip()
                if not tok:
                    continue
                try:
                    b = float(w.get("begin_time")) / 1000.0
                    e = float(w.get("end_time")) / 1000.0
                except (TypeError, ValueError):
                    continue
                item = {"word": tok, "start": b, "end": e}
                if spk is not None:
                    item["speaker"] = str(spk)
                words.append(item)
        full = "".join(texts)
        if words:
            return {"text": full, "segments": _asr_words_to_segments(words)}
        return {"text": full, "segments": []}
    sent = out.get("sentence") if isinstance(out.get("sentence"), dict) else {}
    if not sent and isinstance(data.get("sentence"), dict):
        sent = data["sentence"]
    text = str(sent.get("text") or out.get("text") or data.get("text") or "")
    words = []
    for w in (sent.get("words") or []):
        if not isinstance(w, dict):
            continue
        tok = (str(w.get("text") or "") + str(w.get("punctuation") or "")).strip()
        if not tok:
            continue
        try:
            b = float(w.get("begin_time")) / 1000.0
            e = float(w.get("end_time")) / 1000.0
        except (TypeError, ValueError):
            continue
        words.append({"word": tok, "start": b, "end": e})
    if words:
        return {"text": text, "segments": _asr_words_to_segments(words)}
    return {"text": text, "segments": []}


def _asr_dashscope_native_submit(asr_obj, depth=0):
    """百炼原生录音文件识别（POST /api/v1/services/aigc/multimodal-generation/
    generation）——Qwen-Audio-3.0-ASR-Flash / Fun-ASR-Flash 等专用。

    与 chat_audio 的差别（v1.15.6 实测）：同一个模型、同一份音频，打
    compatible-mode 的 chat/completions 恒回 HTTP 400 空体 `{}`；换成本端点
    即 200 并返回词级时间轴。音频同样用 base64 Data URL（官方示例形态之一），
    另需 `parameters.format`（wav/mp3…），wav 再带 sample_rate。
    """
    import base64
    import requests
    url = _asr_native_url(getattr(asr_obj, "base_url", ""))
    blob = _asr_shrink_audio_blob(getattr(asr_obj, "file_binary", b"") or b"",
                                  ASR_INLINE_AUDIO_MAX_RAW)
    fmt = _asr_audio_format(blob)
    rate = _asr_wav_sample_rate(blob) or 16000
    content = [{"type": "input_audio",
                "input_audio": {"data": "data:audio/%s;base64,%s"
                                        % (fmt, base64.b64encode(blob).decode("ascii"))}}]
    params = {"format": fmt}
    if fmt == "wav":
        params["sample_rate"] = str(rate)
    if _asr_diarize_on(asr_obj):
        # 说话人分离：**仅 qwen-audio-3.1-asr-flash 支持**（官方文档标注）。
        # 3.0 / fun-asr-flash 上带这个参数会被拒或忽略——所以脚本只在用户
        # 主动开了开关时才下传，不开就与 v1.15.7 完全一致。
        params["speaker_diarization_enabled"] = True
    body = {"model": asr_obj.model,
            "input": {"messages": [{"role": "user", "content": content}]},
            "parameters": params}
    r = requests.post(url, json=body,
                      headers={"Authorization": "Bearer " + asr_obj.api_key,
                               "Content-Type": "application/json"},
                      proxies=http_proxies_for(url), timeout=600)
    if r.status_code != 200:
        low = (r.text or "").lower()
        # ① 静音分块：400 空体 + 音频无声 → 这段本来就没内容，返回空即可。
        #    不做这一步，直播回放里夹的静音段会让**整条转录**判失败
        #    （短视频恰好没静音段所以能过 —— 用户实测就是这个形态）。
        if r.status_code == 400 and (r.text or "").strip() in ("", "{}"):
            # ② 内容类失败：400 空体 = 「这段没有可识别语音」。实测同参数下
            #    600s 处 20s 片段回 200 + 279 字符，而 60s 处的 30s/280s 片段
            #    恒回 400 —— 后者是游戏音乐/音效段（音量正常但无语音）。
            #    直播回放里这类片段极多，一律当致命错误就会**整条转录必挂**
            #    （用户实测：短视频过、5 小时回放过不去，就是这个形态）。
            #    密钥/权限问题回 401/403 而不是 400 空体，故此处可安全跳过。
            _vc_log("原生 ASR：该分块无可识别语音（400 空体），按无内容跳过")
            return ""
        if ("too long" in low or "duration" in low) \
                and depth < ASR_SPLIT_MAX_DEPTH:
            halves = _asr_split_audio_blob(blob)
            if halves:
                import types as _types
                parts = []
                for hb in halves:
                    sub = _types.SimpleNamespace(
                        base_url=getattr(asr_obj, "base_url", ""),
                        model=asr_obj.model, api_key=asr_obj.api_key,
                        language=getattr(asr_obj, "language", ""),
                        prompt="", diarize=getattr(asr_obj, "diarize", None),
                        file_binary=hb)
                    parts.append(_asr_native_text(
                        _asr_dashscope_native_submit(sub, depth + 1)))
                return "".join(parts)
        raise RuntimeError("百炼原生 ASR " + _asr_err_hint(r)
                           + _asr_plan_endpoint_hint(asr_obj)
                           + asr_missing_model_hint(asr_obj))
    return _asr_native_output(r)


#: 百炼 Filetrans（异步文件转写）提交端点路径
ASR_FILETRANS_PATH = "/api/v1/services/audio/asr/transcription"

#: 百炼临时存储上传凭证端点（action=getPolicy）
ASR_UPLOAD_POLICY_PATH = "/api/v1/uploads"

#: Filetrans 任务轮询上限：5 秒一次 × 240 次 = 20 分钟（与 AssemblyAI 一致）
ASR_FILETRANS_POLL_MAX = 240


def _asr_dashscope_root(base_url):
    """从「接口地址」推百炼站点根（只留 scheme://host，去掉全部路径）。

    Filetrans 的上传凭证、任务提交、任务查询三个端点都在站点根下，与
    compatible-mode / multimodal-generation 不是同一层路径，所以这里要
    把用户填的 `…/compatible-mode/v1` 之类全部削掉，只留域名。
    """
    b = asr_strip_endpoint_tail(str(base_url or "").strip())
    if not b:
        return "https://dashscope.aliyuncs.com"
    if "//" in b:
        scheme, rest = b.split("//", 1)
        return scheme + "//" + rest.split("/", 1)[0]
    return "https://" + b.split("/", 1)[0]


def _asr_dashscope_upload_oss(root, model, blob, fmt, api_key):
    """把本地音频传到百炼临时存储，返回 `oss://…` 链接（官方称临时 URL）。

    Filetrans 不收本地文件也不收 Base64——只吃公网 URL，RESTful 下额外接受
    `oss://`。桌面端的音频在本地，所以只能先走这一步。
    ⚠️ 官方限制：临时 URL 有效期 48 小时、凭证接口限流 100 QPS，文档明确
    「请勿用于生产环境」。
    """
    import time
    import requests
    pol = requests.get(root + ASR_UPLOAD_POLICY_PATH,
                       params={"action": "getPolicy", "model": model},
                       headers={"Authorization": "Bearer " + api_key},
                       proxies=http_proxies_for(root), timeout=120)
    if pol.status_code != 200:
        raise RuntimeError("百炼上传凭证获取失败 " + _asr_err_hint(pol))
    try:
        d = (pol.json() or {}).get("data") or {}
    except ValueError as e:
        raise RuntimeError(f"上传凭证响应异常：{e}; body={pol.text[:200]}")
    host = str(d.get("upload_host") or "").strip()
    udir = str(d.get("upload_dir") or "").strip()
    if not host or not udir:
        raise RuntimeError("上传凭证缺少 upload_host / upload_dir：%s"
                           % pol.text[:200])
    fname = "vt_audio_%d.%s" % (int(time.time()), fmt)
    key = udir.rstrip("/") + "/" + fname
    form = {"OSSAccessKeyId": str(d.get("oss_access_key_id") or ""),
            "policy": str(d.get("policy") or ""),
            "Signature": str(d.get("signature") or ""),
            "key": key,
            "x-oss-object-acl": str(d.get("x_oss_object_acl") or "private"),
            "x-oss-forbid-overwrite": str(d.get("x_oss_forbid_overwrite") or "true"),
            "success_action_status": "200"}
    # file 字段必须是表单最后一项（OSS 要求）
    up = requests.post(host, data=form,
                       files={"file": (fname, blob, "audio/%s" % fmt)},
                       proxies=http_proxies_for(host), timeout=600)
    if up.status_code not in (200, 204):
        raise RuntimeError("音频上传到百炼临时存储失败 HTTP %d：%s"
                           % (up.status_code, up.text[:200]))
    return "oss://" + key


def _asr_filetrans_result_url(output):
    """取 Filetrans 结果 JSON 的下载地址。

    不同模型族字段不一样（踩过一次就得记下来）：
      · qwen-audio-3.x-asr-flash-filetrans / fun-asr → `output.results[].transcription_url`
      · qwen3-asr-flash-filetrans                    → `output.result.transcription_url`
    """
    res = output.get("results")
    if isinstance(res, list) and res:
        return str((res[0] or {}).get("transcription_url") or "")
    one = output.get("result")
    if isinstance(one, dict):
        return str(one.get("transcription_url") or "")
    return ""


def _asr_dashscope_filetrans_submit(asr_obj):
    """百炼 Filetrans 异步文件转写（POST /api/v1/services/audio/asr/transcription）。

    为什么单独一条协议：同步端点（multimodal-generation）有音频体积/时长上限，
    长音频要靠这条**提交-轮询**的异步链路；它也是 3.0 / fun-asr 上唯一能开
    说话人分离的通道（原生同步端点的 speaker_diarization_enabled 只认 3.1）。

    ⚠️ 与同步端点的根本差别：**不收本地音频**。官方明确 file_urls 只支持公网
    HTTP/HTTPS（RESTful 下额外支持 `oss://` 临时 URL），不支持 Base64、不支持
    二进制流、不支持本地路径。因此桌面端必须先把音频传到百炼临时存储
    （_asr_dashscope_upload_oss），再拿 `oss://` 链接提交，并在请求头带
    `X-DashScope-OssResourceResolve: enable` 让服务端解析。

    ⚠️ 说话人分离的两条硬限制（官方）：**仅单声道音频**；建议时长 ≤ 2 小时。
    """
    import time
    import requests
    root = _asr_dashscope_root(getattr(asr_obj, "base_url", ""))
    key = str(asr_obj.api_key or "")
    model = (asr_obj.model or "").strip()
    low_m = model.lower()
    # 用户常常直接填 qwen3-asr-flash（同步模型名）却选了 Filetrans：补后缀
    if model and "filetrans" not in low_m and low_m.startswith("qwen"):
        model = model + "-filetrans"
        low_m = model.lower()
    blob = getattr(asr_obj, "file_binary", b"") or b""
    fmt = _asr_audio_format(blob)
    oss_url = _asr_dashscope_upload_oss(root, model, blob, fmt, key)

    params = {"channel_id": [0]}
    if _asr_diarize_on(asr_obj):
        params["diarization_enabled"] = True
    lang = str(getattr(asr_obj, "language", "") or "").strip()
    if lang and lang not in ("auto", "zh"):
        params["language_hints"] = [lang]
    url = root + ASR_FILETRANS_PATH
    headers = {"Authorization": "Bearer " + key,
               "Content-Type": "application/json",
               "X-DashScope-Async": "enable",
               "X-DashScope-OssResourceResolve": "enable"}
    # qwen3 系用 input.file_url（单对象），qwen-audio / fun-asr 用 file_urls（数组）
    if low_m.startswith("qwen3-"):
        payload = {"model": model, "input": {"file_url": oss_url},
                   "parameters": params}
        alt = {"model": model, "input": {"file_urls": [oss_url]},
               "parameters": params}
    else:
        payload = {"model": model, "input": {"file_urls": [oss_url]},
                   "parameters": params}
        alt = {"model": model, "input": {"file_url": oss_url},
               "parameters": params}
    sub = requests.post(url, json=payload, headers=headers,
                        proxies=http_proxies_for(url), timeout=120)
    if sub.status_code >= 400:
        # 两个模型族的 input 字段不通用，被拒时换另一种形态再试一次
        sub = requests.post(url, json=alt, headers=headers,
                            proxies=http_proxies_for(url), timeout=120)
    if sub.status_code != 200:
        raise RuntimeError("百炼 Filetrans 提交失败 " + _asr_err_hint(sub)
                           + _asr_plan_endpoint_hint(asr_obj))
    try:
        tid = ((sub.json() or {}).get("output") or {}).get("task_id")
    except (ValueError, AttributeError, TypeError) as e:
        raise RuntimeError(f"提交响应异常：{e}; body={sub.text[:200]}")
    if not tid:
        raise RuntimeError("提交未返回 task_id：%s" % sub.text[:200])

    turl = root + "/api/v1/tasks/" + str(tid)
    out = None
    for _ in range(ASR_FILETRANS_POLL_MAX):
        time.sleep(5)
        got = requests.get(turl, headers={"Authorization": "Bearer " + key},
                           proxies=http_proxies_for(turl), timeout=60)
        if got.status_code != 200:
            raise RuntimeError("百炼 Filetrans 查询失败 " + _asr_err_hint(got))
        data = (got.json() or {}).get("output") or {}
        state = str(data.get("task_status") or "").upper()
        if state == "SUCCEEDED":
            out = data
            break
        if state in ("FAILED", "CANCELED", "CANCELLED"):
            raise RuntimeError(
                "百炼 Filetrans 任务失败：%s"
                % str(data.get("code") or data.get("message") or "")[:200])
    if out is None:
        raise RuntimeError("百炼 Filetrans 任务超时（轮询 20 分钟仍未完成）")

    trs = out.get("transcripts")
    js_url = _asr_filetrans_result_url(out)
    if not trs and js_url:
        jr = requests.get(js_url, proxies=http_proxies_for(js_url), timeout=300)
        if jr.status_code != 200:
            raise RuntimeError("下载转写结果失败 HTTP %d：%s"
                               % (jr.status_code, jr.text[:200]))
        try:
            trs = (jr.json() or {}).get("transcripts") or []
        except ValueError as e:
            raise RuntimeError(f"转写结果 JSON 解析失败：{e}; body={jr.text[:200]}")
    if not trs:
        raise RuntimeError("百炼 Filetrans 结果为空（无 transcripts）")

    segs, words, texts = [], [], []
    for tr in (trs or []):
        if not isinstance(tr, dict):
            continue
        for s in (tr.get("sentences") or []):
            if not isinstance(s, dict):
                continue
            t = str(s.get("text") or "").strip()
            spk = s.get("speaker_id")
            spk = None if spk is None else str(spk)
            ws = []
            for w in (s.get("words") or []):
                if not isinstance(w, dict):
                    continue
                tok = (str(w.get("text") or "")
                       + str(w.get("punctuation") or "")).strip()
                if not tok:
                    continue
                try:
                    wb = float(w.get("begin_time")) / 1000.0
                    we = float(w.get("end_time")) / 1000.0
                except (TypeError, ValueError):
                    continue
                item = {"word": tok, "start": wb, "end": we}
                if spk is not None:
                    item["speaker"] = spk
                ws.append(item)
            if ws:
                words.extend(ws)
            elif t:
                try:
                    b = float(s.get("begin_time") or 0) / 1000.0
                    e = float(s.get("end_time") or 0) / 1000.0
                except (TypeError, ValueError):
                    b = e = 0.0
                seg = {"text": t, "start": round(b, 3), "end": round(e, 3)}
                if spk is not None:
                    seg["speaker"] = spk
                segs.append(seg)
            if t:
                texts.append(t)
    full = "".join(texts)
    if words and not segs:
        return {"text": full, "segments": _asr_words_to_segments(words)}
    if segs:
        return {"text": full, "segments": segs}
    return full


def _asr_native_text(resp):
    """_asr_native_output 的结果取纯文本（切分重试时拼接用）。"""
    if isinstance(resp, dict):
        return str(resp.get("text") or "")
    return str(resp or "")


def _asr_retry_native(asr_obj, reason=""):
    """chat_audio 拿到空体 400/500 时改走百炼原生端点（同模型同音频）。

    Fun-ASR-Flash 等官方也挂在原生端点上，但老配置/某些网关按 chat_audio
    也能用 —— 所以不做静态推断，只在 chat_audio 明确失败（空体）时兜一次，
    且**每个任务只兜一次**（`_vt_native_retried` 标记），避免来回打。
    """
    if getattr(asr_obj, "_vt_native_retried", False):
        raise RuntimeError("ASR 服务 " + str(reason or "接口不可用"))
    if not _asr_is_dashscope_base(getattr(asr_obj, "base_url", "")):
        raise RuntimeError("ASR 服务 " + str(reason or "接口不可用"))
    try:
        asr_obj._vt_native_retried = True
    except Exception:  # noqa: BLE001
        pass
    _vc_log("chat_audio 空体失败（%s）→ 改走百炼原生 multimodal-generation"
            % str(reason)[:80])
    return _asr_dashscope_native_submit(asr_obj)


def _asr_is_dashscope_base(base_url):
    """是否百炼系地址（公共 dashscope 或 *.maas.aliyuncs.com 专属实例）。"""
    b = str(base_url or "").lower()
    return "dashscope" in b or "aliyuncs.com" in b


#: 只可能在境内可达的国内 AI/ASR 端点后缀（v1.15.6 代理劫持修复用）。
DOMESTIC_AI_ENDPOINT_SUFFIXES = (
    "aliyuncs.com",         # 百炼：dashscope / *.maas.aliyuncs.com 专属实例
    "aliyun.com",
    "volces.com",           # 火山方舟
    "volcengine.com",
    "volcengineapi.com",
    "bytedance.com",        # openspeech.bytedance.com
    "bigmodel.cn",          # 智谱
    "xfyun.cn",             # 讯飞
    "baidubce.com",
    "tencentcloudapi.com",
)


def is_domestic_ai_endpoint(url):
    """端点是否属于「只在境内可达」的国内 AI/ASR 服务。"""
    try:
        from urllib.parse import urlsplit
        host = (urlsplit(str(url or "")).hostname or "").lower()
    except Exception:  # noqa: BLE001
        return False
    return any(host == s or host.endswith("." + s)
               for s in DOMESTIC_AI_ENDPOINT_SUFFIXES)


def http_proxies_for(url):
    """requests 的 ``proxies`` 取值：国内端点强制直连，其余返回 None（跟随系统）。

    requests 默认 ``trust_env=True``，在 Windows 下会**读注册表**
    ``HKCU\\...\\Internet Settings``，于是 Clash / FlClash 一类客户端的系统
    代理被套给**所有**请求。实测 ``token-plan.cn-beijing.maas.aliyuncs.com``
    被送进 FlClash 的 ``127.0.0.1:7890``；该订阅规则兜底是 ``MATCH,SELECT``，
    域名后缀不是 ``.cn`` 又没命中 GEOIP 直连 ⇒ 走海外节点，而该端点是阿里云
    北京 NLB 专有入口，海外节点转发失败即被对端断连，抛 ``ProxyError:
    ... RemoteDisconnected('Remote end closed connection without response')``；
    同一份音频直连则完全正常（返 401 而非 ProxyError）。

    故：国内端点显式直连，国外端点保持跟随系统代理（它们反而需要代理才能
    访问）。

    ⚠️ ``all`` 键**必须一起覆盖**（requests 2.34.2 实测）：环境里存在
    ``ALL_PROXY`` 时 ``getproxies()`` 会给出 ``all`` 键，只写 http/https 的
    话 ``merge_environment_settings`` 里的 ``setdefault('all', …)`` 仍会把
    代理塞回来（merged 变成 ``{'all': …}``），照旧走代理；写成三项全 None
    后 merged 才是空 dict，请求真正直连。
    """
    if is_domestic_ai_endpoint(url):
        return {"http": None, "https": None, "all": None}
    return None


def _asr_empty_body_err(exc):
    """异常是否属「HTTP 400/500 空体」——原生专用模型被兼容模式打回的形态。

    _asr_err_hint 会把空体错误写成「HTTP 400（端点返回空体/未知错误：…）」，
    未包装的诊断文本则是 `HTTP 400: {}`，两种都认。
    """
    s = str(exc or "")
    return ("空体" in s) or ("HTTP 400: {}" in s) or ("HTTP 500: {}" in s)


def _asr_wav_sample_rate(blob):
    """从 wav 头读采样率；非 wav / 读不到返回 0（调用方兜 16000）。"""
    try:
        if blob[:4] == b"RIFF" and blob[8:12] == b"WAVE":
            return int.from_bytes(blob[24:28], "little")
    except Exception:  # noqa: BLE001
        pass
    return 0


def _asr_deepgram_submit(asr_obj):
    """Deepgram 预录音频识别：POST {base}/v1/listen，原始音频字节 + Token 头。

    地址允许填 https://api.deepgram.com 或填到 /v1（自动补 /listen）。
    响应带词级时间轴（results.channels[0].alternatives[0].words），
    这里聚合成句级 segments 交给引擎。
    """
    import requests
    b = (asr_obj.base_url or "").strip().rstrip("/") or "https://api.deepgram.com"
    low = b.lower()
    if low.endswith("/listen"):
        url = b
    elif low.endswith("/v1"):
        url = b + "/listen"
    else:
        url = b + "/v1/listen"
    fmt = _asr_audio_format(asr_obj.file_binary or b"")
    params = {"model": (asr_obj.model or "nova-3"),
              "smart_format": "true", "punctuate": "true"}
    lang = str(getattr(asr_obj, "language", "") or "").strip()
    if lang and lang not in ("auto", "zh"):
        params["language"] = lang
    elif lang == "zh":
        params["language"] = "zh-CN"
    r = requests.post(
        url, params=params, data=asr_obj.file_binary or b"",
        headers={"Authorization": "Token " + asr_obj.api_key,
                 "Content-Type": "audio/%s" % fmt},
        proxies=http_proxies_for(url), timeout=600)
    if r.status_code != 200:
        raise RuntimeError("ASR 服务 " + _asr_err_hint(r))
    try:
        alt = r.json()["results"]["channels"][0]["alternatives"][0]
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"ASR 响应格式无法解析：{e}; body={r.text[:200]}")
    return _asr_words_response(
        alt.get("transcript") or "",
        [{"word": w.get("punctuated_word") or w.get("word"),
          "start": w.get("start"), "end": w.get("end")}
         for w in (alt.get("words") or [])])


def _asr_elevenlabs_submit(asr_obj):
    """ElevenLabs Scribe：POST {base}/v1/speech-to-text（multipart + xi-api-key）。

    响应 {text, words:[{text,start,end}], language_code} —— 同样聚合成句级。
    """
    import requests
    b = (asr_obj.base_url or "").strip().rstrip("/") or "https://api.elevenlabs.io"
    url = b if b.lower().endswith("/speech-to-text") else b + "/v1/speech-to-text"
    fmt = _asr_audio_format(asr_obj.file_binary or b"")
    form = {"model_id": (asr_obj.model or "scribe_v1"),
            "timestamps_granularity": "word"}
    lang = str(getattr(asr_obj, "language", "") or "").strip()
    if lang and lang not in ("auto", "zh"):
        form["language_code"] = lang
    r = requests.post(
        url, data=form,
        files={"file": ("audio.%s" % fmt, asr_obj.file_binary or b"",
                        "audio/%s" % fmt)},
        headers={"xi-api-key": asr_obj.api_key},
        proxies=http_proxies_for(url), timeout=600)
    if r.status_code != 200:
        raise RuntimeError("ASR 服务 " + _asr_err_hint(r))
    try:
        data = r.json()
    except ValueError as e:
        raise RuntimeError(f"ASR 响应格式无法解析：{e}; body={r.text[:200]}")
    return _asr_words_response(
        data.get("text") or "",
        [{"word": w.get("text") or w.get("word"),
          "start": w.get("start"), "end": w.get("end")}
         for w in (data.get("words") or [])])


def _asr_gemini_submit(asr_obj):
    """Google Gemini 多模态音频理解：POST models/<model>:generateContent。

    返回纯文本（无时间轴），由 _asr_normalize_resp 按句切分兜底；提示词优先
    用用户填的「识别提示词」，没填就给一句"逐字转写"的指令。
    """
    import base64
    import requests
    b = (asr_obj.base_url or "").strip().rstrip("/") \
        or "https://generativelanguage.googleapis.com"
    model = (asr_obj.model or "gemini-2.5-flash").strip()
    url = "%s/v1beta/models/%s:generateContent" % (b, model)
    # v1.14.2：与 chat_audio 同理，inline_data 的体积上限先压缩再编码
    blob = _asr_shrink_audio_blob(asr_obj.file_binary or b"",
                                  ASR_INLINE_AUDIO_MAX_RAW)
    fmt = _asr_audio_format(blob)
    b64 = base64.b64encode(blob).decode("ascii")
    instruction = (getattr(asr_obj, "prompt", "") or "").strip() \
        or "请把这段音频逐字转写为文本，只输出转写内容，不要加解释或标注。"
    body = {"contents": [{"parts": [
        {"inline_data": {"mime_type": "audio/%s" % fmt, "data": b64}},
        {"text": instruction}]}]}
    r = requests.post(url, json=body,
                      headers={"x-goog-api-key": asr_obj.api_key,
                               "Content-Type": "application/json"},
                      proxies=http_proxies_for(url), timeout=600)
    if r.status_code != 200:
        raise RuntimeError("ASR 服务 " + _asr_err_hint(r))
    try:
        parts = r.json()["candidates"][0]["content"]["parts"]
        return "".join(str(p.get("text") or "") for p in parts)
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"ASR 响应格式无法解析：{e}; body={r.text[:200]}")


#: 火山（豆包）录音识别极速版默认资源 ID
VOLC_DEFAULT_RESOURCE = "volc.bigasr.auc_turbo"

#: AssemblyAI 默认模型（官方的 speech_models 必填，没有默认值）
ASSEMBLYAI_DEFAULT_MODELS = ("universal-3-pro", "universal-2")


def _asr_volcengine_submit(asr_obj):
    """火山引擎（豆包）录音文件识别**极速版**：一次请求即返回，无需轮询。

    鉴权两种形态都吃（零配置改动）：
      · 新版控制台：`api_key` 填 API Key → 走 `X-Api-Key`；
      · 旧版控制台：`api_key` 填 `APPID:AccessToken`（冒号分隔）→ 走
        `X-Api-App-Key` + `X-Api-Access-Key`。
    `model` 填 Resource ID（默认 `volc.bigasr.auc_turbo`）。
    ⚠️ 状态码在**响应头** `X-Api-Status-Code`（`20000000` = OK），不在 body；
    `show_utterances=true` 才有时间轴（毫秒 → 秒）。
    """
    import base64
    import json
    import uuid
    import requests
    base = (asr_obj.base_url or "").strip().rstrip("/") \
        or "https://openspeech.bytedance.com"
    url = base if base.endswith("/recognize/flash") else \
        base + "/api/v3/auc/bigmodel/recognize/flash"
    key = str(asr_obj.api_key or "")
    headers = {"Content-Type": "application/json",
               "X-Api-Resource-Id": (asr_obj.model or VOLC_DEFAULT_RESOURCE),
               "X-Api-Request-Id": str(uuid.uuid4()),
               "X-Api-Sequence": "-1"}
    uid = ""
    if ":" in key:
        uid, _, acc = key.partition(":")
        headers["X-Api-App-Key"] = uid.strip()
        headers["X-Api-Access-Key"] = acc.strip()
    else:
        headers["X-Api-Key"] = key
    body = {"user": {"uid": uid or key},
            "audio": {"data": base64.b64encode(
                asr_obj.file_binary or b"").decode("ascii")},
            "request": {"model_name": "bigmodel", "enable_itn": True,
                        "enable_punc": True, "show_utterances": True}}
    lang = str(getattr(asr_obj, "language", "") or "").strip()
    if lang and lang not in ("auto", "zh"):
        body["request"]["language"] = lang
    if _asr_diarize_on(asr_obj):
        # 说话人分离（说话人日志）：官方标注 10 人以内效果较好。
        body["request"]["enable_speaker_info"] = True
    r = requests.post(url, data=json.dumps(body, ensure_ascii=False),
                      headers=headers, proxies=http_proxies_for(url),
                      timeout=600)
    code = r.headers.get("X-Api-Status-Code", "")
    if r.status_code != 200 or (code and code != "20000000"):
        raise RuntimeError("ASR 服务 " + _asr_err_hint(r)
                           + "（X-Api-Status-Code=%s %s）"
                           % (code or r.status_code,
                              r.headers.get("X-Api-Message", "")))
    try:
        res = (r.json() or {}).get("result") or {}
    except ValueError as e:
        raise RuntimeError(f"ASR 响应格式无法解析：{e}; body={r.text[:200]}")
    utts = res.get("utterances") or []
    ms = 1000.0
    if any(u.get("words") for u in utts):
        words = []
        for u in utts:
            spk = _asr_volc_speaker(u)
            for w in u.get("words") or []:
                item = {
                    "word": w.get("text"),
                    "start": float(w.get("start_time") or 0) / ms,
                    "end": float(w.get("end_time") or 0) / ms}
                if spk:
                    item["speaker"] = spk
                words.append(item)
        return _asr_words_response(res.get("text") or "", words)
    if utts:
        segs = []
        for u in utts:
            if not (u.get("text") or "").strip():
                continue
            seg = {"text": (u.get("text") or "").strip(),
                   "start": round(float(u.get("start_time") or 0) / ms, 3),
                   "end": round(float(u.get("end_time") or 0) / ms, 3)}
            spk = _asr_volc_speaker(u)
            if spk:
                seg["speaker"] = spk
            segs.append(seg)
        return {"text": res.get("text") or "", "segments": segs}
    return res.get("text") or ""


def _asr_volc_speaker(utt):
    """取火山分句上的说话人标识（找不到返回空串）。

    字段位置官方示例里没写死（旧版 v1 在 `utterances[].additions.speaker`，
    v3 bigmodel 的响应示例只给了 `result.additions`），所以这里把两种位置
    都试一遍——猜错字段的后果是**静默没有标签**（不报错但没效果），比报错
    更难发现，宁可多兼容几条路径。
    """
    if not isinstance(utt, dict):
        return ""
    add = utt.get("additions") if isinstance(utt.get("additions"), dict) else {}
    for v in (utt.get("speaker"), add.get("speaker"),
              add.get("speaker_id"), utt.get("speaker_id")):
        if v not in (None, ""):
            return str(v)
    return ""


def _asr_assemblyai_submit(asr_obj):
    """AssemblyAI：上传本地文件 → 提交任务 → 轮询结果（三步，异步）。

    ⚠️ 三个易错点：鉴权头是 `Authorization: <key>`（**没有 Bearer 前缀**）；
    `speech_models` 必填（不填直接报错，官方没有默认值）；词级时间轴单位是
    **毫秒**（别当秒用）。`model` 支持逗号分隔多个模型做回退。
    """
    import time
    import requests
    base = asr_strip_endpoint_tail(asr_obj.base_url, "/v2/upload",
                                   "/v2/transcript") \
        or "https://api.assemblyai.com"
    headers = {"authorization": str(asr_obj.api_key or "").strip()}
    # 1) 上传：必须是 raw bytes（不发 multipart，否则下游 Transcoding failed）
    up = requests.post(base + "/v2/upload", data=asr_obj.file_binary or b"",
                       headers=headers, proxies=http_proxies_for(base),
                       timeout=600)
    if up.status_code != 200:
        raise RuntimeError("ASR 服务 上传失败 " + _asr_err_hint(up))
    try:
        audio_url = up.json()["upload_url"]
    except (ValueError, KeyError, TypeError) as e:
        raise RuntimeError(f"上传响应异常：{e}; body={up.text[:200]}")
    # 2) 提交
    models = [m.strip() for m in str(asr_obj.model or "").split(",")
              if m.strip()] or list(ASSEMBLYAI_DEFAULT_MODELS)
    payload = {"audio_url": audio_url, "speech_models": models}
    lang = str(getattr(asr_obj, "language", "") or "").strip()
    if lang and lang not in ("auto", "zh"):
        payload["language_code"] = lang
    else:
        payload["language_detection"] = True
    if getattr(asr_obj, "prompt", ""):
        payload["prompt"] = asr_obj.prompt
    sub = requests.post(base + "/v2/transcript", json=payload, headers=headers,
                        proxies=http_proxies_for(base), timeout=120)
    if sub.status_code != 200:
        raise RuntimeError("ASR 服务 " + _asr_err_hint(sub))
    try:
        tid = (sub.json() or {}).get("id")
    except ValueError as e:
        raise RuntimeError(f"提交响应异常：{e}; body={sub.text[:200]}")
    if not tid:
        raise RuntimeError("提交未返回 transcript id：%s" % sub.text[:200])
    # 3) 轮询（官方建议 3 秒一次；20 分钟上限，避免任务卡死时无限等）
    url = base + "/v2/transcript/" + str(tid)
    for _ in range(400):
        time.sleep(3)
        got = requests.get(url, headers=headers,
                           proxies=http_proxies_for(url), timeout=60)
        if got.status_code != 200:
            raise RuntimeError("ASR 服务 查询失败 " + _asr_err_hint(got))
        data = got.json() or {}
        state = data.get("status")
        if state == "completed":
            words = [{"word": w.get("text"),
                      "start": float(w.get("start") or 0) / 1000.0,
                      "end": float(w.get("end") or 0) / 1000.0}
                     for w in (data.get("words") or [])]
            if words:
                return _asr_words_response(data.get("text") or "", words)
            return data.get("text") or ""
        if state == "error":
            raise RuntimeError("ASR 任务失败：" + str(data.get("error"))[:200])
    raise RuntimeError("ASR 任务超时（轮询 20 分钟仍未完成）")


def _asr_ws_url(base_url):
    """从「接口地址」推导百炼实时 ASR 的 WebSocket 端点。

    · 留空 / dashscope 公共 → wss://dashscope.aliyuncs.com/api-ws/v1/inference/
    · 专属实例（https://xxx.cn-beijing.maas.aliyuncs.com/…）→ 同域名换 wss，
      API 路径与公共端点一致（/api-ws/v1/inference/）
    · 用户直接填 wss://… → 尊重原样，只在缺路径时补 /api-ws/v1/inference/
    """
    b = str(base_url or "").strip().rstrip("/")
    if not b:
        return "wss://dashscope.aliyuncs.com/api-ws/v1/inference/"
    if b.lower().startswith(("wss://", "ws://")):
        low = b.lower()
        if low.endswith("/inference/"):
            return b
        if low.endswith("/inference"):
            return b + "/"
        return b + "/api-ws/v1/inference/"
    if b.lower().startswith("https://"):
        host = b[8:]
    elif b.lower().startswith("http://"):
        host = b[7:]
    else:
        host = b
    host = host.strip("/")
    if "/" in host:                       # 只取域名，路径一律换成 API 路径
        host = host.split("/", 1)[0]
    return "wss://%s/api-ws/v1/inference/" % host


#: 实时 ASR 的音频帧大小。官方示例按 100ms/3200 字节（16k/16bit）模拟实时，
#: 但批量转录要的是"尽快灌完"——64KB 一帧不 sleep，一小时音频几十秒发完；
#: 服务端按到达顺序处理，不需要对齐真实时间。
ASR_WS_FRAME_BYTES = 65536

#: 实时 ASR 推流倍速（相对 16bit 单声道 PCM 的实时字节率）。
#: ⚠️ 全速灌发实测会被服务端掐断连接（Connection to remote host was lost）：
#: 实时识别服务端按流式消费音频，输入速率远超实时会撑爆内部缓冲。默认
#: 20 倍速折中（6 分钟音频约 19 秒灌完）；VT_ASR_WS_SPEED 可调，最小 1 倍。
def _asr_ws_speed() -> float:
    """VT_ASR_WS_SPEED 归一：环境变量非数字时不炸 import（v1.16.5 修复）。

    此前写成模块级 `max(float(os.environ.get(...) or 20), 1.0)`——环境变量
    被设成非数字（如 "fast"）时 import 期抛 ValueError，整个引擎加载失败。
    """
    try:
        return max(float(os.environ.get("VT_ASR_WS_SPEED") or 20), 1.0)
    except (TypeError, ValueError):
        return 20.0


ASR_WS_SPEED = _asr_ws_speed()


def _asr_collect_sentence(msg, segments, texts):
    """把 result-generated 里的句子收进 segments（毫秒 → 秒）。

    实时流里同一句会先来"中间态"（end_time 为空、文本逐渐变长），说完才有
    带 begin/end 的最终事件 —— 只收**有终点的**，天然去重。
    """
    out = (msg.get("payload") or {}).get("output") or {}
    sent = out.get("sentence") or {}
    text = str(sent.get("text") or "").strip()
    if not text:
        return
    texts.append(text)
    b, e = sent.get("begin_time"), sent.get("end_time")
    if b is None or e is None:
        return                            # 句子还没说完，等最终事件
    try:
        b, e = float(b) / 1000.0, float(e) / 1000.0
    except (TypeError, ValueError):
        return
    if e > b:
        segments.append({"text": text, "start": round(b, 3),
                         "end": round(e, 3)})


def _asr_ws_prepare_audio(blob, model):
    """8k 专版模型 → ffmpeg 重采样为 8kHz 单声道 wav；其它模型原样返回。

    引擎提取音频固定 16kHz（video2audio `-ar 16000`），而
    fun-asr-flash-8k-realtime 等 8k 电话音专版模型**只收 8kHz**——16k 音频
    直接发过去服务端会异常断连（Connection to remote host was lost）。
    ffmpeg 不可用或转码失败时按原样返回，让服务端回具体错误码。
    """
    if "8k" not in str(model or "").lower():
        return blob, 16000
    if blob[:4] == b"RIFF" and blob[8:12] == b"WAVE":
        try:
            if int.from_bytes(blob[24:28], "little") == 8000:
                return blob, 8000              # 已是 8k wav，免转
        except Exception:  # noqa: BLE001
            pass
    try:
        ffmpeg, _ = _ensure_ffmpeg()
    except Exception:  # noqa: BLE001
        ffmpeg = ""
    if not ffmpeg or not blob:
        return blob, 16000
    import subprocess as _sp
    import tempfile as _tf
    src = dst = ""
    try:
        with _tf.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
            tf.write(blob)
            src = tf.name
        dst = src + ".8k.wav"
        _sp.run([ffmpeg, "-y", "-i", src, "-vn", "-ac", "1", "-ar", "8000", dst],
                capture_output=True, check=True,
                creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0)
        with open(dst, "rb") as f:
            out = f.read()
        return (out or blob, 8000) if out else (blob, 16000)
    except Exception:  # noqa: BLE001
        return blob, 16000
    finally:
        for p in (src, dst):
            if p:
                try:
                    os.unlink(p)
                except OSError:
                    pass


def _asr_dashscope_realtime_submit(asr_obj):
    """DashScope 实时语音识别（WebSocket，协议见官方「实时语音识别 API」）。

    覆盖**只有实时形态**的模型：fun-asr-flash-8k-realtime / fun-asr-realtime /
    qwen3-asr-flash-realtime（官方模型表标注「模式=即时、API=WebSocket」，
    compatible-mode 的 chat/completions 与 /audio/transcriptions 都调不了它们）。

    交互时序：run-task → task-started → 二进制音频帧 → finish-task →
    result-generated… → task-finished。要点：
      · 握手鉴权 `Authorization: Bearer <key>`，密钥无效直接握手失败；
      · result-generated 的 `payload.output.sentence` 带 begin/end（毫秒），
        即实时模型也有**原生时间轴**，聚合成句级 segments；
      · 60 秒无消息服务端会断连 —— 推帧循环不会空闲，finish 后服务端继续
        推结果，不受影响；
      · 推帧按 ASR_WS_SPEED 倍速限速（全速灌发会被服务端断连）；
      · 8k 专版模型自动把 16k 音频重采样为 8kHz（_asr_ws_prepare_audio）；
      · 断连/超时自动重试 1 次；task-failed（参数/模型错误）不重试。
    """
    import json as _json
    import time as _time
    import uuid as _uuid

    try:
        import websocket                     # websocket-client
    except ImportError as e:
        raise RuntimeError("实时协议缺少依赖 websocket-client，"
                           "请先安装：pip install websocket-client") from e

    url = _asr_ws_url(getattr(asr_obj, "base_url", ""))
    key = str(getattr(asr_obj, "api_key", "") or "").strip()
    lang = str(getattr(asr_obj, "language", "") or "").strip()
    blob, sample_rate = _asr_ws_prepare_audio(
        asr_obj.file_binary or b"", getattr(asr_obj, "model", ""))
    fmt = _asr_audio_format(blob)
    params = {"sample_rate": sample_rate, "format": fmt}
    if lang and lang not in ("auto", "zh"):
        params["language"] = lang

    # 推帧节奏：按 16bit 单声道 PCM 字节率折算每帧"音频时长"，倍速发送
    frame_gap = ASR_WS_FRAME_BYTES / (2.0 * max(sample_rate, 1)) / ASR_WS_SPEED

    class _Transient(Exception):
        """瞬态错误（断连/超时）——值得整段重发一次。"""

    def _ws_send(ws, payload):
        """ws.send 统一包装：服务端掐断后继续 send 会抛
        WebSocketConnectionClosedException（"socket is already closed"，既不是
        _Transient 也不是 RuntimeError）——不包的话既不会自动重试、也进不了
        _submit 的降级分支，用户只会看到裸异常。统一转 _Transient，让
        「重试一次 → 仍失败 → 降级 qwen3-asr-flash 文件识别」的链路生效。
        """
        try:
            ws.send(payload)
        except Exception as e:  # noqa: BLE001
            raise _Transient("实时 ASR 连接中断（发送）：%s" % e)

    def _recv_until(ws, want, deadline, segments, texts):
        """收事件直到 want；途中的 result-generated 顺路收集。"""
        while _time.monotonic() < deadline:
            try:
                raw = ws.recv()
            except Exception as e:  # noqa: BLE001
                raise _Transient("实时 ASR 连接中断：%s" % e)
            if not raw or isinstance(raw, bytes):
                continue
            try:
                msg = _json.loads(raw)
            except ValueError:
                continue
            header = msg.get("header") or {}
            event = str(header.get("event") or "")
            if event == "result-generated":
                _asr_collect_sentence(msg, segments, texts)
            elif event == "task-failed":
                # 参数/模型/密钥类错误，重试也不会好 → 直接抛；顺带把服务端那句
                # `InvalidParameter url error, please check url!` 翻译成可操作的
                # 引导——它几乎总是「模型与实时协议不匹配」造成的。
                code = str(header.get("error_code") or "")
                emsg = str(header.get("error_message") or "")
                hint = ""
                if "url" in emsg.lower() or "invalidparameter" in code.lower():
                    hint = ("。该模型很可能不是实时（WebSocket）模型——实时模型名"
                            "通常含 realtime（如 fun-asr-flash-realtime /"
                            " qwen3-asr-flash-realtime）；若用的是文件识别模型，"
                            "请把「接口协议」改为「自动识别」")
                raise RuntimeError("实时 ASR 任务失败：%s %s%s"
                                   % (code, emsg, hint))
            elif event == want:
                return
        raise _Transient("实时 ASR 等待 %s 超时" % want)

    def _run_once():
        try:
            ws = websocket.create_connection(
                url, timeout=60,
                header={"Authorization": "Bearer " + key,
                        "user-agent": "VideoToolbox-ASR"})
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            # v1.15.3：握手 401/403 是**确定性**的密钥/权限问题——重试与降级
            # 都无意义（降级到文件识别同样用这把密钥，只会再失败一次，用户
            # 反而看到两条互相矛盾的错误）。直接把结论摆出来并给出改法。
            if "401" in msg or "403" in msg:
                raise RuntimeError(
                    "实时 ASR 握手被拒（401/403）：密钥无效、或该密钥不属于这个"
                    "实例。请到「设置 → 字幕引擎」核对 ASR 密钥——**别把接口网址"
                    "粘进密钥栏**（实测踩到过），改完点「保存并应用」。端点：%s"
                    % url)
            raise _Transient("实时 ASR 连接失败（%s）：%s" % (url, msg))
        segments, texts = [], []
        task_id = _uuid.uuid4().hex[:32]     # 每次尝试新 task_id（服务端要求唯一）
        try:
            deadline = _time.monotonic() + 30 * 60      # 整体上限 30 分钟
            _ws_send(ws, _json.dumps({
                "header": {"action": "run-task", "task_id": task_id,
                           "streaming": "duplex"},
                "payload": {"task_group": "audio", "task": "asr",
                            "function": "recognition", "model": asr_obj.model,
                            "parameters": params, "input": {}}}))
            _recv_until(ws, "task-started", deadline, segments, texts)
            for i, off in enumerate(range(0, len(blob), ASR_WS_FRAME_BYTES)):
                if i and frame_gap > 0:
                    _time.sleep(frame_gap)              # 限速：防服务端断连
                _ws_send(ws, blob[off:off + ASR_WS_FRAME_BYTES])   # 二进制帧=原始音频
            _ws_send(ws, _json.dumps({"header": {"action": "finish-task",
                                                 "task_id": task_id,
                                                 "streaming": "duplex"},
                                      "payload": {"input": {}}}))
            _recv_until(ws, "task-finished", deadline, segments, texts)
        finally:
            try:
                ws.close()
            except Exception:  # noqa: BLE001
                pass
        return segments, texts

    segments = texts = None
    for attempt in (1, 2):
        try:
            segments, texts = _run_once()
            break
        except _Transient as e:
            if attempt == 1:
                _time.sleep(2)                          # 稍候重发整段
            else:
                hint = ""
                if "8k" in str(getattr(asr_obj, "model", "") or "").lower():
                    hint = ("；模型是 8k 电话音专版，已自动重采样为 8kHz 仍中断，"
                            "多为网络/服务端问题，可改用 16k 模型"
                            " fun-asr-flash-realtime")
                raise RuntimeError("%s（自动重试 1 次仍失败）%s" % (e, hint))
    if segments:
        return {"text": "".join(texts), "segments": segments}
    text = "".join(texts or [])
    if text:
        return text                     # 没拿到时间轴 → 按句兜底
    raise RuntimeError("实时 ASR 未返回任何识别结果")


#: 实时 WebSocket 会话级降级记忆：服务端掐断实时连接一经确认（官方 dashscope
#: SDK 也复现），本进程后续转录直接走文件识别，不再重复浪费重试时间。
_ASR_WS_DEGRADED = False


def _asr_fallback_chat_audio(asr_obj, reason=""):
    """实时 ASR 不可用 → 同端点换 qwen3-asr-flash 文件识别（chat_audio）。

    实测（2026-09-17）：maas 专属实例与公共百炼的 qwen3-asr-flash 文件识别
    均可用；⚠️ 专属实例的 asr 任务不支持 audio+text 混合输入——带 text
    提示词会 HTTP 400（"does not support this input"），必须裸音频。
    """
    if reason:
        _vc_log("实时 ASR 不可用（%s）→ 自动降级 qwen3-asr-flash 文件识别"
                % str(reason)[:80])
    asr_obj.model = "qwen3-asr-flash"
    asr_obj.prompt = ""
    return _asr_chat_audio_submit(asr_obj)




__all__ = [
    "is_realtime_asr_family",
    "is_dashscope_native_asr",
    "asr_model_hard_guard",
    "asr_strip_endpoint_tail",
    "asr_protocol_fix",
    "asr_base_guard",
    "asr_model_guard",
    "asr_protocol_of",
    "asr_diarize_of",
    "asr_separate_of",
    "asr_examples",
    "asr_examples_text",
    "asr_instance_models",
    "asr_missing_model_hint",
    "is_domestic_ai_endpoint",
    "http_proxies_for",
    "_asr_native_url",
    "_host_path",
    "_is_anthropic_only_path",
    "_infer_asr_protocol",
    "_asr_diarize_flag",
    "_asr_diarize_on",
    "_asr_separate_on",
    "_asr_separate_audio",
    "_asr_audio_format",
    "_asr_text_to_segments",
    "_asr_is_cjk",
    "_asr_join_words",
    "_asr_is_sentence_end",
    "_asr_words_to_segments",
    "_asr_apply_speaker_labels",
    "_asr_words_response",
    "_asr_plan_endpoint_hint",
    "_asr_err_hint",
    "_asr_normalize_resp",
    "_asr_azure_submit",
    "_asr_shrink_audio_blob",
    "_asr_split_audio_blob",
    "_asr_chat_audio_submit",
    "_asr_native_output",
    "_asr_dashscope_native_submit",
    "_asr_dashscope_root",
    "_asr_dashscope_upload_oss",
    "_asr_filetrans_result_url",
    "_asr_dashscope_filetrans_submit",
    "_asr_native_text",
    "_asr_retry_native",
    "_asr_is_dashscope_base",
    "_asr_empty_body_err",
    "_asr_wav_sample_rate",
    "_asr_deepgram_submit",
    "_asr_elevenlabs_submit",
    "_asr_gemini_submit",
    "_asr_volcengine_submit",
    "_asr_volc_speaker",
    "_asr_assemblyai_submit",
    "_asr_ws_url",
    "_asr_ws_speed",
    "_asr_collect_sentence",
    "_asr_ws_prepare_audio",
    "_asr_dashscope_realtime_submit",
    "_asr_fallback_chat_audio",
    "ASR_PROTOCOLS",
    "ASR_PROTOCOL_NOTES",
    "ASR_REALTIME_HINTS",
    "_REALTIME_ASR_FAMILY",
    "_TTS_HINTS",
    "ASR_NATIVE_PATH",
    "ASR_ENDPOINT_TAILS",
    "ASR_SPEAKER_PREFIX",
    "_ASR_MODELS_CACHE",
    "ASR_INLINE_AUDIO_MAX_RAW",
    "ASR_SPLIT_MAX_DEPTH",
    "ASR_FILETRANS_PATH",
    "ASR_UPLOAD_POLICY_PATH",
    "ASR_FILETRANS_POLL_MAX",
    "DOMESTIC_AI_ENDPOINT_SUFFIXES",
    "VOLC_DEFAULT_RESOURCE",
    "ASSEMBLYAI_DEFAULT_MODELS",
    "ASR_WS_FRAME_BYTES",
    "ASR_WS_SPEED",
    "_ASR_WS_DEGRADED",
]
