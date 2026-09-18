# -*- coding: utf-8 -*-
# @version 1.14.1
"""
全局 AI 客户端（OpenAI 兼容 · 单通道）。

工具箱内所有 AI 能力（标题/语言识别、视觉识别、字幕引擎优化/拆分、AI 校准）
统一走本模块：
- 仅依赖 Python 标准库（urllib），GUI 主程序与投稿引擎共用同一份代码；
- 配置持久化在 data\\ai_config.json，首次调用自动生成默认配置，
  换 Key / 换模型直接改该文件即可，无需改代码；
- **单通道（v1.12.0，原接口 A/B 合并）**：一套地址/密钥/模型全程序共用，
  统一走 OpenAI 兼容协议（/chat/completions）：
    · 工具箱自身：标题/语言识别（文本）、视觉识别（同一地址的视觉模型）；
    · 字幕引擎：优化/拆分（保存时自动写入引擎的 OpenAI 兼容槽）；
    · AI 校准：Agent 级字幕校准（原 calib_channel 通道选择已废弃）。
  旧双通道配置（接口 A Anthropic + 接口 B OpenAI）在 load_config 时自动迁移：
  base_url 为旧 Anthropic 地址时用接口 B 的地址/模型顶上。
- **ASR（语音识别）**：asr_mode = service 走自有 OpenAI 兼容 ASR 服务
  （/audio/transcriptions，可对接 Whisper / SenseVoice 等自建服务），
  = local 走本地独立 faster-whisper 模型（模型名 + 模型目录自定义）；
- 视觉通道：vision_base_url 留空 = 沿用 base_url；vision_fallback_model
  非空时，主视觉模型被限流/拥堵（1305/429）自动降级重试；
- chat_text：纯文本对话；chat_vision：图片 + 文本（屏幕识别用）；
- detect_language：标题/文本语言识别（字幕语言跟随标题语言用）；
- 回复中的 thinking 块自动跳过，只拼接 text 块；JSON 回复用 try_parse_json 解析；
- 智谱"1305 访问量过大 / overloaded"与 HTTP 429/5xx 自动退避重试。
"""

from __future__ import annotations

import base64
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 配置（默认值 = 出厂内置；data/ai_config.json 可覆盖）
# ---------------------------------------------------------------------------
def _resolve_data_dir() -> Path:
    """定位「软件文件夹下的 data 目录」，保证 AI 配置不落到 C 盘/用户目录。

    优先级：
      1. 环境变量 VT_DATA_ROOT（主程序注入，便携部署 / 数据根自定义时跟随）；
      2. 打包形态：exe 同级 data\\；
      3. 源码形态：向上找到「其下有 tools 且本文件就在该 tools 内」的程序根；
      4. 兜底：<本文件>/../../data（即 <程序根>/tools/ai_client.py 的常规布局）。
    """
    env = (os.environ.get("VT_DATA_ROOT") or "").strip().strip('"')
    if env:
        return Path(env) / "data"
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "data"
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "tools").is_dir() and \
                (parent / "tools" / "ai_client.py").is_file():
            return parent / "data"
    return here.parents[1] / "data"


DATA_DIR = _resolve_data_dir()
CONFIG_PATH = DATA_DIR / "ai_config.json"

DEFAULT_CONFIG: dict = {
    "enabled": True,
    # 唯一 LLM 通道（OpenAI 兼容 /chat/completions）——
    # 工具箱自身、字幕引擎（优化/拆分）、AI 校准共用一套地址/密钥/模型
    "base_url": "https://open.bigmodel.cn/api/paas/v4",
    # ⚠️ 密钥不随程序分发（v1.14.1 安全整改）：出厂不内置任何 Key，
    #    用户在「设置 → 全局 AI」填写后写入 data\ai_config.json（运行期文件，
    #    不入 git、不进安装包）。此处留空，程序检测到空 Key 时给出配置指引。
    "api_key": "",
    "model": "glm-4.7-flash",
    # 视觉通道（OpenAI chat/completions 格式）：留空 = 沿用 base_url
    "vision_base_url": "",
    "vision_model": "glm-4.6v-flash",
    # 主视觉模型限流/拥堵时自动降级到此模型（空 = 不降级）
    "vision_fallback_model": "",
    # ---- ASR 语音识别（转录）：服务 或 本地独立模型 ----
    # asr_mode: "service" = 自有 ASR 服务（OpenAI 兼容 /audio/transcriptions）
    #           "local"   = 本地独立 faster-whisper 模型（可指定模型名与模型目录）
    "asr_mode": "service",
    "asr_base_url": "https://api.siliconflow.cn/v1",
    "asr_api_key": "",
    "asr_model": "FunAudioLLM/SenseVoiceSmall",
    "asr_prompt": "",
    # asr_protocol: 服务模式接口协议——"auto"=按地址/模型自动识别；
    #   "openai"=OpenAI Whisper 兼容（multipart /audio/transcriptions）；
    #   "azure"=Azure OpenAI（deployments + api-key 头）；
    #   "dashscope"=阿里百炼兼容模式（chat/completions + input_audio）
    "asr_protocol": "auto",
    "asr_local_model": "large-v3",
    "asr_local_model_dir": "",
    # ---- AI 校准（Agent 级字幕校准）----
    # v1.12.0：原 calib_channel（接口 A/B 选择）随双通道合并一并废弃
    "calib_chunk_cues": 120,   # 每块最多 cue 条数
    "calib_max_chars": 6000,   # 每块字符预算（超出自动再拆）
    "calib_max_tokens": 8192,  # 单次调用的最大输出
    "calib_concurrency": 1,    # 逐块 LLM 调用并发路数（1＝串行；v1.16.0 受控并发）
    "max_tokens": 2048,
    "timeout": 90,
    "retries": 3,
}


def load_config() -> dict:
    """读取 AI 配置；文件不存在时用默认值落盘一份，方便用户直接修改。

    v1.12.0 兼容迁移：旧双通道配置（接口 A 的 base_url 为 Anthropic 地址、
    接口 B 为 llm_base_url/llm_model）自动合并为单通道——用接口 B 的
    地址/模型顶上（两通道密钥本就共用同一个）。
    """
    cfg = dict(DEFAULT_CONFIG)
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
        if isinstance(raw, dict):
            old_base = str(raw.get("base_url") or "").lower()
            if raw.get("llm_base_url") and "anthropic" in old_base:
                raw["base_url"] = raw["llm_base_url"]
                if raw.get("llm_model"):
                    raw["model"] = raw["llm_model"]
            for k in DEFAULT_CONFIG:
                if k in raw and raw[k] is not None:
                    cfg[k] = raw[k]
    except (OSError, ValueError):
        pass
    if not CONFIG_PATH.exists():
        try:
            save_config(cfg)
        except OSError:
            pass
    if _FORCE_DISABLED:
        cfg["enabled"] = False
    return cfg


def save_config(cfg: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2),
                           encoding="utf-8")


# 运行期开关（--no-ai 用），不影响配置文件
_FORCE_DISABLED = False


def set_enabled(enabled: bool) -> None:
    global _FORCE_DISABLED
    _FORCE_DISABLED = not enabled


class AIClientError(RuntimeError):
    """AI 调用失败（网络 / 鉴权 / 接口报错）。"""


# ---------------------------------------------------------------------------
# 语言识别本地启发式（明显语系不占用 AI 请求，只有拉丁语种才问 AI）
# ---------------------------------------------------------------------------
import re as _re

_KANA_RE = _re.compile(r"[぀-ヿ]")          # 平假名/片假名
_HANGUL_RE = _re.compile(r"[가-힯]")        # 韩语谚文
_CJK_RE = _re.compile(r"[一-鿿]")           # 汉字
_THAI_RE = _re.compile(r"[฀-๿]")
_ARABIC_RE = _re.compile(r"[؀-ۿ]")
_CYRILLIC_RE = _re.compile(r"[Ѐ-ӿ]")
_LATIN_RE = _re.compile(r"[A-Za-zÀ-ɏ]")


def _mostly_ascii(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    ascii_letters = [c for c in letters if ord(c) < 128]
    return len(ascii_letters) >= len(letters) * 0.8


def _heuristic_language(text: str) -> str:
    """按 Unicode 区段判断明显语系；拉丁字母文本返回 'latin' 交由 AI 细分。"""
    if _KANA_RE.search(text):
        return "ja"          # 有假名一律日语（汉字+假名混合也是日语）
    if _HANGUL_RE.search(text):
        return "ko"
    if _THAI_RE.search(text):
        return "th"
    if _ARABIC_RE.search(text):
        return "ar"
    if _CYRILLIC_RE.search(text):
        return "ru"
    if _CJK_RE.search(text):
        return "zh"          # 纯汉字（简体繁体均按 B 站习惯先给简体）
    if _LATIN_RE.search(text):
        return "latin"
    return ""


def _chat_url(base: str) -> str:
    """OpenAI 兼容对话地址归一化（v1.12.0 增强多厂商兼容）。

    兼容的填法：
      · 已到端点：.../chat/completions → 原样返回；
      · 到版本段：.../v1、.../v4、.../v1beta、.../compatible-mode/v1
        （阿里百炼 / 智谱 paas/v4 / OpenAI /v1 等）→ + /chat/completions；
      · Gemini OpenAI 兼容层：.../v1beta/openai[/] → + /chat/completions；
      · 裸域名：https://api.openai.com、https://api.deepseek.com 等
        → + /v1/chat/completions（DeepSeek/Ollama/主流中转均兼容 /v1）。
    """
    b = (base or "").strip().rstrip("/")
    if not b:
        return b
    if b.endswith("/chat/completions"):
        return b
    if b.endswith("/openai"):            # Gemini 的 OpenAI 兼容层
        return b + "/chat/completions"
    tail = b.rsplit("/", 1)[-1].lower()
    # /v1、/v4、/v1beta 之类的版本段结尾：直接拼后缀
    if tail.startswith("v") and tail[1:2].isdigit():
        return b + "/chat/completions"
    return b + "/v1/chat/completions"


_AZURE_HOST_KEYWORD = "openai.azure.com"
_AZURE_API_VERSION = "2024-10-21"


def _is_azure_base(base: str) -> bool:
    """识别 Azure OpenAI 地址（鉴权与端点结构与 OpenAI 标准不同）。"""
    return _AZURE_HOST_KEYWORD in (base or "").lower()


def _azure_chat_url(base: str) -> str:
    """Azure OpenAI 对话端点：要求填到 .../openai/deployments/<部署名>。

    已带 api-version 参数则原样保留，否则补默认版本。
    """
    b = (base or "").strip().rstrip("/")
    if "/deployments/" not in b:
        raise AIClientError(
            "Azure OpenAI 地址需填到 .../openai/deployments/<部署名>"
            "（程序自动补 /chat/completions 与 api-version）")
    if b.endswith("/chat/completions"):
        b = b[: -len("/chat/completions")]
    if "api-version=" in b:
        return b
    sep = "&" if "?" in b else "?"
    return f"{b}/chat/completions{sep}api-version={_AZURE_API_VERSION}"


def _asr_url(base: str) -> str:
    """OpenAI 兼容 ASR 地址归一化：允许填裸域名 / 到 /v1。"""
    b = (base or "").rstrip("/")
    if b.endswith("/audio/transcriptions"):
        return b
    tail = b.rsplit("/", 1)[-1].lower()
    if tail.startswith("v") and tail[1:2].isdigit():
        return b + "/audio/transcriptions"
    return b + "/v1/audio/transcriptions"


#: 「完整端点」的常见尾巴（与 src/video_toolbox.py 的 ASR_ENDPOINT_TAILS 一致）
ASR_ENDPOINT_TAILS = ("/audio/transcriptions", "/audio/translations",
                      "/chat/completions", "/v2/upload", "/v2/transcript")


def _asr_base_clean(base: str) -> str:
    """削掉"用户把完整端点抄进地址栏"的尾巴。

    与 `src/video_toolbox.py` 的 `asr_strip_endpoint_tail` 同一规则：不削的话
    探测地址会拼成 `.../audio/transcriptions/v1/models`（智谱那种完整 URL 就
    会踩到），测试连接会误报不可用。
    """
    b = str(base or "").strip().rstrip("/")
    changed = True
    while changed and b:
        changed = False
        low = b.lower()
        for tail in ASR_ENDPOINT_TAILS:
            if low.endswith(tail):
                b = b[: -len(tail)].rstrip("/")
                changed = True
                break
    return b


def _is_zhipu_asr_base(base: str) -> bool:
    """是否智谱 ASR 服务（bigmodel.cn / z.ai）。

    智谱的 /models 端点只列 LLM 与视觉模型，ASR 模型（glm-asr-*）不列在
    列表里，但 audio/transcriptions 端点确实可用。模型可见性核对该类平台
    必须放行，否则「接口连通、模型实际可用」会被误报成"看不到模型"。
    """
    b = str(base or "").lower()
    return ("bigmodel.cn" in b or ".z.ai" in b or "z.ai/" in b
            or b.startswith("z.ai"))


def _models_url(base: str) -> str:
    """OpenAI 兼容模型列表地址（用于 ASR 服务连通性测试）。"""
    b = _asr_base_clean(base)
    tail = b.rsplit("/", 1)[-1].lower()
    if tail.startswith("v") and tail[1:2].isdigit():
        return b + "/models"
    return b + "/v1/models"


#: 支持的 ASR 协议（与 src/video_toolbox.py 的 ASR_PROTOCOLS 保持一致）
#: ⚠️ `dashscope` 是历史键（= chat_audio 那一族），保留只为兼容老配置
ASR_PROTOCOLS = ("auto", "openai", "azure", "chat_audio", "dashscope",
                 "deepgram", "elevenlabs", "gemini",
                 "volcengine", "assemblyai", "dashscope_realtime")

#: 实时（WebSocket 流式）模型特征：一次性上传整段音频用不了它们
ASR_REALTIME_HINTS = ("realtime", "-rt-", "streaming")


def resolve_asr_protocol(ac: dict) -> str:
    """解析 ASR 服务模式实际使用的接口协议。

    ac 为 asr_config() 产物。显式配置直接用；auto 按地址与模型名推断：
    先认域名独有的服务（deepgram / elevenlabs / gemini），再认 Azure，
    然后是兼容模式（百炼 compatible-mode / dashscope / qwen-asr /
    paraformer / fun-asr）→ dashscope，其余一律按 OpenAI 兼容处理。
    ⚠️ 规则必须与 src/video_toolbox.py 的 _infer_asr_protocol 一致，
    否则「测试连接」与「实际转录」会用两套协议。
    """
    p = str(ac.get("protocol") or "auto").strip().lower()
    if p in ("dashscope", "chat_audio"):
        return "chat_audio"          # 历史键归一
    if p in ASR_PROTOCOLS and p != "auto":
        return p
    base = (ac.get("base_url") or "").lower()
    model = (ac.get("model") or "").lower()
    if "openspeech.bytedance.com" in base or "volcengine" in base:
        return "volcengine"
    if "assemblyai.com" in base:
        return "assemblyai"
    if ("aliyuncs.com" in base or "dashscope" in base) and any(
            h in model for h in ASR_REALTIME_HINTS):
        # 百炼系域名 + 实时模型：只有 WebSocket 形态（与引擎侧同规则）
        return "dashscope_realtime"
    if "deepgram.com" in base:
        return "deepgram"
    if "elevenlabs.io" in base:
        return "elevenlabs"
    if "generativelanguage.googleapis.com" in base:
        return "gemini"
    if (_AZURE_HOST_KEYWORD in base or "/openai/deployments/" in base
            or "azure.com" in base):
        return "azure"
    if ("xiaomimimo.com" in base or "mimo-v2" in model
            or "compatible-mode" in base or "dashscope" in base
            or ("qwen" in model and ("audio" in model or "asr" in model))
            or "paraformer" in model or "fun-asr" in model):
        return "chat_audio"
    return "openai"


def asr_realtime_guard(model: str) -> str:
    """实时（流式）模型守卫：返回提示，可放行时空串（文案与引擎侧一致）。

    ⚠️ 只在**非实时协议**下调用——实时模型在「百炼实时（WebSocket）」协议
    （dashscope_realtime）下能正常出字幕，不该被拦。
    """
    m = str(model or "").lower()
    if any(h in m for h in ASR_REALTIME_HINTS):
        return ("模型「%s」是实时（WebSocket 流式）语音识别，本协议用不了它。"
                "把「接口协议」改为「百炼实时（WebSocket）」（留自动识别也会"
                "选中），或改用录音文件识别模型：公共百炼 qwen3-asr-flash、"
                "硅基流动 FunAudioLLM/SenseVoiceSmall、OpenAI whisper-1" % model)
    return ""


def asr_base_guard(base_url: str) -> str:
    """ASR 地址守卫：地址填成「文本对话端点」时给出能照着改的提示。

    最常见的是把 Anthropic（/apps/anthropic、/api/anthropic）这类只收文本
    的端点当成 ASR 地址 —— 它收不了 multipart 音频，表现是五花八门的
    404 / 415，与其让用户对着状态码猜，不如直接说该填什么。
    """
    b = str(base_url or "").lower()
    if "anthropic" in b:
        return ("ASR 地址填的是 Anthropic 文本对话端点（%s）——它收不了音频。"
                "请改填 OpenAI 兼容端点：公共百炼 "
                "https://dashscope.aliyuncs.com/compatible-mode/v1，"
                "或专属实例的 …/compatible-mode/v1" % base_url)
    return ""


def asr_model_visible(raw: str, model: str):
    """从 /models 的 JSON 响应里判断配置的模型是否可见。

    返回 (hit, names)：hit 为 True/False/None（None = 列表解析不了或没法比，
    例如网关不返回 data 数组）；names 是服务端报告的全部模型 id。
    匹配按「整串或末段、忽略大小写」——硅基流动这类会把组织前缀拼进 id
    （FunAudioLLM/SenseVoiceSmall），用户填的常常只有名字段。
    """
    try:
        data = json.loads(raw).get("data") or []
        names = [str((m or {}).get("id") or "")
                 for m in data if isinstance(m, dict)]
    except (ValueError, AttributeError, TypeError):
        return None, []
    want = str(model or "").strip().lower()
    if not want or not names:
        return None, names
    tail = want.rsplit("/", 1)[-1]
    hit = any(x.lower() == want or x.lower().rsplit("/", 1)[-1] == tail
              for x in names)
    return hit, names


def _azure_asr_probe_url(base: str) -> str:
    """Azure ASR 连通性探测地址：部署根（GET 列部署，api-key 头）。

    允许填资源根 / .../openai/deployments/<部署名>，截到 deployments 上一层。
    """
    b = _asr_base_clean(base)
    if "/openai/deployments/" in b:
        b = b.split("/openai/deployments/")[0] + "/openai/deployments"
    elif not b.endswith("/openai/deployments"):
        b = b + "/openai/deployments"
    sep = "&" if "?" in b else "?"
    return f"{b}{sep}api-version={_AZURE_API_VERSION}"


def channel_config(cfg: dict | None = None, channel: str = "a") -> dict:
    """取规范化配置（v1.12.0 起单通道；channel 参数保留兼容，忽略）。

    返回 dict(base_url, api_key, model, protocol="openai", vision_base_url,
    vision_model, enabled)。
    """
    c = dict(cfg or load_config())
    return {
        "channel": "single",
        "protocol": "openai",
        "base_url": str(c.get("base_url") or "").strip(),
        "api_key": str(c.get("api_key") or "").strip(),
        "model": str(c.get("model") or "").strip(),
        "vision_base_url": str(c.get("vision_base_url") or "").strip(),
        "vision_model": str(c.get("vision_model") or "").strip(),
        "enabled": bool(c.get("enabled", True)),
    }


def asr_config(cfg: dict | None = None) -> dict:
    """取 ASR（语音识别）规范化配置，供字幕引擎「转录配置」注入使用。

    service = 自有 ASR 服务（协议见 protocol 字段，全协议适配）；
    local   = 本地独立 faster-whisper 模型（模型名 + 模型目录可自定义）。
    """
    c = dict(cfg or load_config())
    mode = str(c.get("asr_mode") or "service").strip().lower()
    if mode not in ("service", "local"):
        mode = "service"
    proto = str(c.get("asr_protocol") or "auto").strip().lower()
    if proto not in ASR_PROTOCOLS:
        # 全协议白名单（v1.14.2）：老版只认 4 个值，把 UI 保存的
        # dashscope_realtime / deepgram / volcengine 等显式选择静默打回 auto
        proto = "auto"
    return {
        "mode": mode,
        "protocol": proto,
        "base_url": str(c.get("asr_base_url") or "").strip(),
        "api_key": str(c.get("asr_api_key") or "").strip(),
        "model": str(c.get("asr_model") or "").strip(),
        "prompt": str(c.get("asr_prompt") or "").strip(),
        "local_model": str(c.get("asr_local_model") or "").strip(),
        "local_model_dir": str(c.get("asr_local_model_dir") or "").strip(),
    }


def _is_retryable(status: int | None, detail: str) -> bool:
    """智谱 1305（访问量过大）/ overloaded / 429 / 5xx 可退避重试。"""
    if status is None:                      # 网络错误
        return True
    if status == 429 or status >= 500:
        return True
    d = (detail or "").lower()
    return "1305" in d or "overloaded" in d or "稍后再试" in d


def _emit_reasoning(on_reasoning, text) -> None:
    """把思考链片段交给上报回调（v1.14.2，AI 校准日志显示 Agent 思考过程）。

    空白跳过；回调内部异常吞掉，绝不影响正常取回正文。
    """
    if on_reasoning is None:
        return
    text = (text or "").strip()
    if not text:
        return
    try:
        on_reasoning(text)
    except Exception:  # noqa: BLE001
        logger.debug("on_reasoning 回调异常（忽略）", exc_info=True)


class AIClient:
    """OpenAI 兼容最小客户端（无第三方依赖，v1.12.0 起单通道）。

    一套配置（base_url / api_key / model）全程序共用：
    - chat / chat_text：OpenAI 兼容 /chat/completions；
    - chat_vision：同一地址的视觉模型（vision_base_url 留空 = base_url）。
    """

    def __init__(self, config: dict | None = None, channel: str = "a") -> None:
        self.cfg = config or load_config()
        cc = channel_config(self.cfg)
        self.protocol = "openai"
        self.api_key = cc["api_key"]
        base = cc["base_url"]
        if "anthropic" in base.lower():
            raise AIClientError(
                "检测到 Anthropic 专用地址（如 /api/anthropic）。"
                "全局 AI 已统一 OpenAI 兼容协议，请填 OpenAI 兼容地址"
                "（如 https://open.bigmodel.cn/api/paas/v4）")
        self.is_azure = _is_azure_base(base)
        if self.is_azure:
            self.url = _azure_chat_url(base)
            # Azure 视觉走同一多模态部署（vision_base_url 留空时不另行推导）
            self.vision_url = self.url
        else:
            self.url = _chat_url(base)
            vbase = (str(self.cfg.get("vision_base_url") or "").strip()
                     or base)
            self.vision_url = _chat_url(vbase)
        self.model = cc["model"] or DEFAULT_CONFIG["model"]
        self.vision_model = str(self.cfg.get("vision_model")
                                or DEFAULT_CONFIG["vision_model"])
        self.vision_fallback_model = str(
            self.cfg.get("vision_fallback_model") or "")
        self.max_tokens = int(self.cfg.get("max_tokens") or 2048)
        self.timeout = float(self.cfg.get("timeout") or 90)
        self.retries = int(self.cfg.get("retries")
                           if self.cfg.get("retries") is not None else 3)

    # ---- 底层请求 --------------------------------------------------------
    def _request(self, url: str, headers: dict, body: dict) -> dict:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        last_err: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                req = urllib.request.Request(url, data=data,
                                             headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                detail = ""
                try:
                    detail = e.read().decode("utf-8", "replace")[:400]
                except Exception:  # noqa: BLE001
                    pass
                if not _is_retryable(e.code, detail):
                    raise AIClientError(f"HTTP {e.code}: {detail}") from e
                last_err = AIClientError(f"HTTP {e.code}: {detail}")
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last_err = AIClientError(f"网络错误: {e}")
            if attempt < self.retries:
                wait = 2.0 * (attempt + 1)
                logger.info("AI 请求失败（%s），%.0f 秒后重试（第 %d/%d 次）",
                            last_err, wait, attempt + 1, self.retries)
                time.sleep(wait)
        raise last_err or AIClientError("AI 请求失败")

    def _post_openai(self, url: str, body: dict) -> dict:
        """OpenAI 兼容端点（chat/completions）：Bearer 鉴权 + error 字段校验。

        Azure OpenAI 特殊处理：api-key 头鉴权（Bearer 不被接受），
        缺 api-version 参数时自动补默认版本。
        """
        headers = {"content-type": "application/json"}
        if _is_azure_base(url):
            headers["api-key"] = self.api_key
            if "api-version=" not in url:
                sep = "&" if "?" in url else "?"
                url = f"{url}{sep}api-version={_AZURE_API_VERSION}"
        else:
            headers["Authorization"] = "Bearer " + self.api_key
        resp = self._request(url, headers, body)
        if isinstance(resp, dict) and resp.get("error"):
            err = resp["error"]
            if isinstance(err, dict):
                raise AIClientError(
                    f"{err.get('code', err.get('type', 'error'))}: "
                    f"{err.get('message', err)}")
            raise AIClientError(str(err))
        return resp

    def chat_openai(self, prompt, *, system: str | None = None,
                    max_tokens: int | None = None,
                    model: str | None = None,
                    on_reasoning=None) -> str:
        """OpenAI 兼容文本对话。返回首个 choice 的文本。

        on_reasoning（v1.14.2）：可选回调，接收模型思考链文本
        （message.reasoning_content，或 content 块列表里的 thinking 块），
        供 AI 校准等场景把 Agent 的推理过程打进日志；回调异常不影响主流程。
        """
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user",
                         "content": prompt if isinstance(prompt, str)
                         else str(prompt)})
        body: dict = {
            "model": model or self.model,
            "max_tokens": int(max_tokens or self.max_tokens),
            "messages": messages,
        }
        resp = self._post_openai(self.url, body)
        try:
            msg = resp["choices"][0]["message"]
            content = msg.get("content")
        except (KeyError, IndexError, TypeError):
            raise AIClientError(
                f"OpenAI 兼容接口返回结构异常: {str(resp)[:200]}")
        if isinstance(content, list):      # 部分模型返回块列表
            think, texts = [], []
            for b in content:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text":
                    texts.append(str(b.get("text") or ""))
                elif b.get("type") in ("thinking", "reasoning"):
                    think.append(str(b.get("thinking") or b.get("text") or ""))
            _emit_reasoning(on_reasoning, "\n".join(think))
            content = "\n".join(texts)
            if not think and isinstance(msg, dict):   # 块列表无思考块 → 看主字段
                _emit_reasoning(
                    on_reasoning,
                    str(msg.get("reasoning_content") or ""))
        else:
            _emit_reasoning(
                on_reasoning,
                str(msg.get("reasoning_content") or "")
                if isinstance(msg, dict) else "")
        content = str(content or "").strip()
        if not content:
            # 推理模型常见故障：思考链吃光输出预算，正文为空。静默返回空串会让
            # 上层把「没拿到数据」误当「没有改动」，必须显式报错、给出可操作提示。
            msg = resp["choices"][0] if resp.get("choices") else {}
            reason = msg.get("finish_reason") or ""
            if msg.get("message", {}).get("reasoning_content"):
                raise AIClientError(
                    "模型只输出了思考链、正文为空"
                    f"（finish_reason={reason or '未知'}，多为思考耗尽 max_tokens）。"
                    "请改用非推理模型（如 deepseek-chat）或加大「单次最大输出 token」")
            if reason == "length":
                raise AIClientError("输出被 max_tokens 截断，请加大输出预算")
        return content

    # ---- 对话 ------------------------------------------------------------
    def chat(self, content, *, system: str | None = None,
             max_tokens: int | None = None, model: str | None = None,
             on_reasoning=None) -> str:
        """文本对话（OpenAI 兼容 /chat/completions）。返回模型回复文本。"""
        return self.chat_openai(content, system=system,
                                max_tokens=max_tokens, model=model,
                                on_reasoning=on_reasoning)

    def chat_text(self, prompt: str, **kw) -> str:
        return self.chat(prompt, **kw)

    def chat_vision(self, prompt: str, images, **kw) -> str:
        """视觉通道（OpenAI chat/completions 格式）：图片 + 文本提问（屏幕识别用）。

        :param images: PNG 字节或文件路径列表
        """
        blocks: list[dict] = []
        for img in images:
            if isinstance(img, (bytes, bytearray)):
                b64 = base64.b64encode(bytes(img)).decode()
            else:
                b64 = base64.b64encode(Path(img).read_bytes()).decode()
            blocks.append({
                "type": "image_url",
                "image_url": {"url": "data:image/png;base64," + b64},
            })
        blocks.append({"type": "text", "text": prompt})
        body: dict = {
            "model": kw.pop("model", None) or self.vision_model,
            "max_tokens": int(kw.pop("max_tokens", None) or self.max_tokens),
            "messages": [{"role": "user", "content": blocks}],
            # 屏幕识别要的是直接答案，关闭思考链避免 max_tokens 被推理耗尽
            "thinking": {"type": "disabled"},
            "temperature": 0.1,
        }

        def _send(b: dict) -> dict:
            return self._post_openai(self.vision_url, b)

        try:
            resp = _send(body)
        except AIClientError as e:
            msg = str(e)
            low = msg.lower()
            if "thinking" in body and any(
                    k in low for k in ("thinking", "unrecognized",
                                       "unknown parameter", "not supported",
                                       "extra_fields", "invalid argument")):
                # v1.12.0 兼容性：thinking 是智谱私有参数，OpenAI/Azure 等
                # 厂商会拒绝未知字段（HTTP 400）——去掉后重试一次
                logger.info("视觉接口拒绝 thinking 参数（%s），去掉后重试",
                            msg[:120])
                body.pop("thinking", None)
                resp = _send(body)
            else:
                # 主视觉模型拥堵/限流（1305/429/overloaded）时降级到备用模型
                congested = any(k in msg for k in
                                ("1305", "1302", "429", "overloaded"))
                if congested and self.vision_fallback_model \
                        and self.vision_fallback_model != body["model"]:
                    logger.warning("视觉模型 %s 拥堵（%s），降级到 %s 重试",
                                   body["model"], msg[:80],
                                   self.vision_fallback_model)
                    body["model"] = self.vision_fallback_model
                    resp = _send(body)
                else:
                    raise
        try:
            content = resp["choices"][0]["message"].get("content")
        except (KeyError, IndexError, TypeError):
            raise AIClientError(f"视觉接口返回结构异常: {str(resp)[:200]}")
        if isinstance(content, list):   # 部分模型返回块列表
            parts = [str(b.get("text") or "") for b in content
                     if isinstance(b, dict) and b.get("type") == "text"]
            content = "\n".join(parts)
        if not content:
            raise AIClientError("视觉接口返回空内容（可能被思考链耗尽 max_tokens）")
        return str(content).strip()

    # ---- 语言识别（字幕跟随标题语言用） -----------------------------------
    def detect_language(self, text: str) -> str:
        """识别文本主要语言，返回小写代码（zh/en/ja/ko/...）；失败返回 ''。

        先用本地文字特征启发式（假名→ja、谚文→ko、汉字→zh、拉丁→AI 细分），
        只有拉丁字母语种等模糊情况才调用 AI，省请求也更稳。
        """
        text = (text or "").strip()
        if not text:
            return ""
        local = _heuristic_language(text)
        if local and local != "latin":
            return local
        prompt = (
            "判断以下文字的主要语言。辨别要点：出现平假名/片假名（如 の です って）"
            "一律是日语 ja；韩语谚文是 ko；简体/繁体汉字且无假名是 zh；"
            "拉丁字母按语种区分（en/es/fr/de/pt 等）。"
            "只回复严格 JSON：{\"lang\":\"代码\"}，代码从 zh, en, ja, ko, es, fr, "
            "de, ru, pt, ar, th, vi, id, other 中选择。\n文字：" + text[:200])
        try:
            raw = self.chat_text(prompt, max_tokens=256)
        except AIClientError as e:
            logger.warning("AI 语言识别调用失败: %s", e)
            # AI 不可用时的兜底：纯 ASCII 拉丁文本按英语处理，其余放弃
            if local == "latin":
                return "en" if _mostly_ascii(text) else ""
            return ""
        data = try_parse_json(raw)
        code = ""
        if isinstance(data, dict):
            code = str(data.get("lang") or "").strip().lower()
        else:
            code = raw.strip().strip('"').lower()
        return code if code in BILI_SUBTITLE_LANGS or code == "other" else ""


# ---------------------------------------------------------------------------
# 语言 → 字幕参数映射（B 站字幕语言名 / yt-dlp --sub-langs）
# ---------------------------------------------------------------------------
BILI_SUBTITLE_LANGS: dict[str, str] = {
    "zh": "简体中文", "en": "英语", "ja": "日本語", "ko": "한국어",
    "es": "西班牙语", "fr": "法语", "de": "德语", "ru": "俄语",
    "pt": "葡萄牙语", "ar": "阿拉伯语", "th": "泰语", "vi": "越南语",
    "id": "印尼语",
}

YTDLP_SUB_LANGS: dict[str, str] = {
    "zh": "zh-Hans,zh-CN,zh,zh-Hant,zh-TW",
    "en": "en,en-US,en-GB",
    "ja": "ja", "ko": "ko", "es": "es,es-419", "fr": "fr", "de": "de",
    "ru": "ru", "pt": "pt,pt-BR", "ar": "ar", "th": "th", "vi": "vi",
    "id": "id",
}

# 同目录字幕文件的语言后缀（find_subtitle_for_video 匹配用）
SUBTITLE_FILE_SUFFIXES: dict[str, tuple[str, ...]] = {
    "zh": ("zh-hans", "zh-cn", "zh-hant", "zh-tw", "zh"),
    "en": ("en", "en-us", "en-gb"),
    "ja": ("ja", "jp"), "ko": ("ko", "kr"), "es": ("es",),
    "fr": ("fr",), "de": ("de",), "ru": ("ru",), "pt": ("pt",),
    "ar": ("ar",), "th": ("th",), "vi": ("vi",), "id": ("id",),
}


def bili_subtitle_lang(lang_code: str, default: str = "") -> str:
    """语言代码 → B 站字幕语言显示名；未知名称返回 default。"""
    return BILI_SUBTITLE_LANGS.get((lang_code or "").lower(), default)


def ytdlp_sub_langs(lang_code: str, default: str = "") -> str:
    """语言代码 → yt-dlp --sub-langs 参数；未知返回 default。"""
    return YTDLP_SUB_LANGS.get((lang_code or "").lower(), default)


def detect_language(text: str) -> str:
    """模块级便捷入口：识别文本语言代码（AI 不可用/失败时返回 ''）。"""
    try:
        return get_client().detect_language(text)
    except Exception as e:  # noqa: BLE001
        logger.warning("AI 语言识别失败: %s", e)
        return ""


# ---------------------------------------------------------------------------
# 单例与 JSON 解析
# ---------------------------------------------------------------------------
_clients: dict = {}


def get_client(channel: str = "a") -> AIClient:
    """取 AI 客户端单例（v1.12.0 起单通道；channel 参数保留兼容，忽略）。"""
    client = _clients.get("single")
    if client is None:
        client = _clients["single"] = AIClient()
    return client


def reset_clients() -> None:
    """丢弃已建客户端（配置变更后调用，强制下次重建）。"""
    _clients.clear()


def is_enabled() -> bool:
    return load_config().get("enabled", True)


def try_parse_json(text: str):
    """从模型回复中尽力提取 JSON（容忍 ```json 围栏与前后闲话）。

    解析成功返回 dict/list，失败返回 None（调用方自行兜底）。
    """
    if not text:
        return None
    s = text.strip()
    # 去掉 markdown 代码围栏
    if "```" in s:
        chunks = []
        for seg in s.split("```"):
            seg = seg.strip()
            if seg.startswith("json"):
                seg = seg[4:].strip()
            if seg:
                chunks.append(seg)
        s = "\n".join(chunks).strip()
    # 直接解析 → 截取第一个平衡的 {} / [] 块
    for opener, closer in (("{", "}"), ("[", "]")):
        start = s.find(opener)
        if start < 0:
            continue
        depth = 0
        for i in range(start, len(s)):
            ch = s[i]
            if ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    frag = s[start:i + 1]
                    try:
                        return json.loads(frag)
                    except ValueError:
                        break
    try:
        return json.loads(s)
    except ValueError:
        return None


def quick_test(channel: str = "a") -> tuple[bool, str]:
    """连通性自检：返回 (是否成功, 回复/错误信息)。同时报告所用模型。"""
    try:
        client = get_client()
        reply = client.chat_text("收到请只回复两个字：正常", max_tokens=512)
        return True, (reply or "(空回复)") + \
            f"（模型 {client.model}；视觉 {client.vision_model}）"
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def asr_test_connection(cfg: dict | None = None) -> tuple[bool, str]:
    """ASR（语音识别）配置自检：返回 (是否成功, 说明)。

    service 模式按协议探测：openai/dashscope 用 GET {base}/models（两者均为
    OpenAI 兼容模型列表）；azure 用 GET 部署根（api-key 头，列出部署）。
    local 模式：只做本地配置校验（模型名非空、模型目录存在性），不真正加载模型
    （加载会占用显存/内存且耗时，交给转录任务自身校验）。
    """
    ac = asr_config(cfg)
    if ac["mode"] == "local":
        if not ac["local_model"]:
            return False, "本地模式需要填写模型名（如 large-v3）"
        d = ac["local_model_dir"]
        if d:
            if not os.path.isdir(d):
                return False, f"模型目录不存在：{d}"
            if not os.listdir(d):
                return False, f"模型目录为空：{d}"
            return True, f"本地模型 {ac['local_model']}，目录 {d}（已就绪）"
        return True, (f"本地模型 {ac['local_model']}（用数据根 models 目录；"
                      "若模型未下载，请在字幕引擎设置内下载）")
    if not ac["base_url"]:
        return False, "服务模式需要填写 ASR 接口地址"
    if not ac["api_key"]:
        return False, "服务模式需要填写 ASR 密钥"
    # ⚠️ 必须先解析协议再跑实时模型守卫：实时模型在「百炼实时（WebSocket）」
    # 协议下是合法路径（握手验证密钥），先守卫会把 dashscope_realtime 分支
    # 永远拦死——"接口协议已选实时仍报不可用"就是这么来的。
    proto = resolve_asr_protocol(ac)
    guard = asr_base_guard(ac["base_url"])
    if not guard and proto != "dashscope_realtime":
        guard = asr_realtime_guard(ac["model"])
    if guard:
        return False, guard
    base = _asr_base_clean(ac["base_url"])
    if proto == "azure":
        url = _azure_asr_probe_url(ac["base_url"])
        headers = {"api-key": ac["api_key"]}
        proto_note = "Azure OpenAI（deployments）"
    elif proto == "deepgram":
        # 探测只读的 projects 列表（Token 头，与转录同一套鉴权）
        url = base + "/v1/projects"
        headers = {"Authorization": "Token " + ac["api_key"]}
        proto_note = "Deepgram（/v1/listen）"
    elif proto == "elevenlabs":
        url = base + "/v1/user"      # 只读、零额度消耗
        headers = {"xi-api-key": ac["api_key"]}
        proto_note = "ElevenLabs Scribe（/v1/speech-to-text）"
    elif proto == "gemini":
        url = base + "/v1beta/models"
        headers = {"x-goog-api-key": ac["api_key"]}
        proto_note = "Google Gemini（generateContent）"
    elif proto == "dashscope_realtime":
        # 实时协议走 WebSocket：没有只读探测端点，密钥在握手时验证
        return True, ("百炼实时（WebSocket）：密钥无效会在握手时被拒"
                      "（HTTP 401/403），实际可用性以转录结果为准；模型 %s"
                      % (ac["model"] or "未填"))
    elif proto == "volcengine":
        # 火山没有只读的探测端点：只校验密钥形态，真伪留给转录那一步
        key = str(ac["api_key"])
        if ":" in key:
            appid, _, acc = key.partition(":")
            if not appid.strip() or not acc.strip():
                return False, "密钥格式不对：旧版控制台应填 APPID:AccessToken"
        return True, ("火山（豆包）录音识别极速版：密钥形态已校验（%s）；"
                      "该服务不提供只读探测端点，实际可用性以转录结果为准"
                      % ("APPID:AccessToken" if ":" in key else "新版 X-Api-Key"))
    elif proto == "assemblyai":
        url = base + "/v2/transcript"      # 列历史转录，只读
        headers = {"authorization": ac["api_key"]}
        proto_note = "AssemblyAI（/v2/transcript）"
    else:
        url = _models_url(ac["base_url"])
        headers = {"Authorization": "Bearer " + ac["api_key"],
                   "content-type": "application/json"}
        proto_note = ("Chat 音频转写（chat/completions + input_audio）"
                      if proto in ("chat_audio", "dashscope")
                      else "OpenAI Whisper 兼容（/audio/transcriptions）")
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:200]
        except Exception:  # noqa: BLE001
            pass
        if e.code in (401, 403):
            return False, ("HTTP %d：密钥被拒 —— 确认密钥属于这个服务/实例，"
                           "并且已经点过设置页的「保存并应用」（只填不保存"
                           "不会生效）：%s" % (e.code, detail or e.reason))
        if e.code in (404, 405):
            # 有的专属实例 / 自建网关不实现"列出模型"，这不代表不能转录
            return True, ("接口可达（HTTP %d：该端点不提供模型列表，不代表"
                          "不可用）；协议 %s；地址 %s"
                          % (e.code, proto_note, url))
        return False, f"HTTP {e.code}: {detail or e.reason}"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return False, f"网络错误: {e}"
    n = raw.count('"id"')
    # 模型存在性核对：专属实例 / 网关往往只部署了部分模型。连通性测试通过
    # 不代表转录能用——配置的模型名不在列表里时，转录必失败。这里直接把
    # 实例上「实际可见的模型」告诉用户，免得他继续对着 404 猜。
    hit, names = asr_model_visible(raw, ac["model"])
    if hit is False and not _is_zhipu_asr_base(ac["base_url"]):
        sample = "、".join(sorted(names)[:8])
        return False, ("接口连通，但该服务/实例上看不到模型「%s」（可见的模型："
                       "%s%s）。注意：maas 专属实例通常只部署创建时选定的模型，"
                       "实时（*realtime*）模型不能用于一次性上传，请改用 "
                       "qwen3-asr-flash 这类录音文件识别模型。"
                       % (ac["model"], sample,
                          " 等 %d 个" % len(names) if len(names) > 8 else ""))
    if hit is False and _is_zhipu_asr_base(ac["base_url"]):
        # 智谱（bigmodel.cn / z.ai）的 /models 端点**只列 LLM/视觉模型**，
        # ASR 模型（glm-asr-2512 等）不列在列表里，但 audio/transcriptions
        # 端点确实可用——模型不在列表不代表不可用，这里如实说明并放行。
        return True, (f"接口连通（协议 {proto_note}，{url}）；模型 {ac['model'] or '未填'}"
                      "（智谱 /models 不列 ASR 模型，实际可用性以转录结果为准）")
    return True, (f"接口连通（协议 {proto_note}，{url}）；模型 {ac['model'] or '未填'}"
                  + (f"，服务端可见 {n} 个模型" if n else ""))
