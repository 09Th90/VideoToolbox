# -*- coding: utf-8 -*-
# @version 1.18.0
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
- 火山方舟 Token Plan 端点（/api/plan/v3）只收套餐模型：按量模型（如
  deepseek-flash）打上去恒回 404 UnsupportedModel（agent plan feature）。
- 设置自动匹配（2026-10-01 v2，本文件是唯一权威实现）：
  · **端点↔模型**：Token Plan 端点 + 非套餐模型 → 自动换成套餐默认模型
    （match_volces_plan_model）；反向——按量端点（/api/v3）+ 套餐专用模型名
    不做改写（套餐模型在按量端点同样可用）。
  · **Key↔端点**：Token Plan 发放的 Key 只被 /api/plan/* 接受，打按量端点
    恒 401。首次撞 401 即把 `self.plan_key_only = True` 记在客户端上，后续
    相同端点不再重复「换 /api/v3 再撞 401」的无效重试（避免一次设置错误在
    逐块校准时放大成整轮 401 风暴）。
  · **失败前的最后自救**：套餐端点回 UnsupportedModel 时，先按 `MODEL_CAPS`
    换套餐默认模型在**原端点**重试；仍不行才考虑换端点；两者都不行时给出
    含「自动匹配」结论的一句话处置建议，不再抛长篇英文原文。
  · **能力钳制**：已知模型的上下文/输出能力记入 MODEL_CAPS，发送前钳制
    max_tokens，校准入口钳制输入/输出预算，避免「1M 上下文配 8K 输出小模型」
    这类组合错误必然失败。
- 自动匹配结果回传：`AIClient.auto_notes`（人类可读说明列表）+ 模块级
  `match_settings()`（设置页「自动匹配」按钮与校准入口共用，返回修正后的
  配置副本与说明）。
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

#: 本模块的 logger 以前**从未被配置过**——`logger.info("…重试…")` 全部无声
#: 丢弃、`logger.warning` 只落到 stderr（GUI 下看不到）。结果是：一块校准卡在
#: "90 秒超时 → 退避重试"里拖到 7 分 39 秒，用户界面上却一片空白，只能判成
#: "程序卡死"（2026-10-05 实测）。这里给 logger 挂一个轮转文件 handler，
#: 让重试 / 超时 / 端点自愈第一次有据可查。
_LOG_READY = False


def _log_filename() -> str:
    """日志文件名；自检进程隔离（与 video_toolbox._append_log 同一套判据）。"""
    name = os.path.basename(sys.argv[0] or "")
    if os.environ.get("VT_SELFTEST") == "1" \
            or name.startswith(("_selftest", "_smoke")):
        return "ai_client_selftest.log"
    return "ai_client.log"


def _ensure_file_log() -> None:
    """给本模块 logger 挂轮转文件 handler（只挂一次；任何异常都吞掉）。"""
    global _LOG_READY
    if _LOG_READY:
        return
    _LOG_READY = True
    try:
        if logger.handlers:            # 宿主已配置过 → 不抢
            return
        import logging.handlers
        logdir = DATA_DIR.parent / "logs"
        logdir.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            str(logdir / _log_filename()), maxBytes=1_500_000,
            backupCount=2, encoding="utf-8")
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname).1s] %(message)s", "%Y-%m-%d %H:%M:%S"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    except Exception:  # noqa: BLE001
        pass

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
    # v1.16.5 修复：说话人分离 / 语音分离两个开关此前「只写不读」——
    #   video_toolbox_qt.py 保存时会写进 ai_config.json，但本 schema 缺这两个
    #   键，而 load_config 只接受 DEFAULT_CONFIG 内的键（见下方 for k in
    #   DEFAULT_CONFIG）⇒ 保存即被静默丢弃、重启回落 False。此处补齐 schema。
    "asr_diarize": False,
    "asr_separate": False,
    # ---- AI 校准（Agent 级字幕校准）----
    # v1.12.0：原 calib_channel（接口 A/B 选择）随双通道合并一并废弃
    # v1.15.4：按「模型最大值」放开——上下文预算默认 1M token，单次输出默认
    #   65536（推理模型的思考链也吃这份额度，给小了正文会空）；端点不接受
    #   该额度时程序会按错误类型**自动减半重试**，无需手工调小。
    "calib_chunk_cues": 400,          # 每块最多 cue 条数
    "calib_max_chars": 60000,         # 每块字符预算（超出自动再拆）
    "calib_max_tokens": 65536,        # 单次调用的最大输出（设置页「输出」）
    "calib_context_tokens": 1000000,  # 可用上下文预算（设置页「输入」；片源档案按 1/4 折算采样）
    # v1.15.7：AI 校准思考控制（参考模型厂商「高级配置」样式）——
    #   calib_thinking=False 时请求体带 thinking={"type":"disabled"}；
    #   calib_reasoning_effort 取值 low/medium/high/xhigh/max，随请求体
    #   reasoning_effort 下发（端点不认该参数时自动去掉重试，见 chat_openai）。
    "calib_thinking": True,
    "calib_reasoning_effort": "high",
    "calib_concurrency": 1,    # 逐块 LLM 调用并发路数（1＝串行；v1.16.0 受控并发）
    # v1.16.1：Agent 思考轮次上限 —— 每块「思考 → 联网查证 → 再思考」的往返轮数。
    #   0 = 关闭（不限，内部另有 32 轮安全上限防死循环）；>0 = 硬上限。
    #   注意：它约束的是**工具/查证往返**，不是日志里的 [x/8]（那是 8 个流水线步骤）。
    "calib_think_rounds": 0,
    # v1.16.1：Agent 集群（多智能体协作，**默认关闭**）——
    #   members 每项 {name, base_url, api_key, model, role}：
    #     role="calibrate" 提议 Agent（多成员按块轮转，分散负载/多模型并行）
    #     role="review"    评审 Agent（独立端点/模型复核提议，全部通过才采纳）
    #   未填的 base_url/api_key/model 回落全局配置；rounds = 评审-整改协作轮数。
    "calib_cluster_enabled": False,
    "calib_cluster_members": [],
    "calib_cluster_rounds": 1,
    # calib_style: "term"=术语级（只替换名词）；"rewrite"=整句重写（理顺机翻）
    # 2026-09-20 修复：此前不在白名单里，界面保存后会被静默丢弃
    "calib_style": "term",
    # calib_web_enabled: AI 校准 Agent 联网查证（web_search/web_fetch 工具环）
    "calib_web_enabled": False,
    "max_tokens": 2048,
    "timeout": 90,
    "retries": 3,
}

#: v1.15.4：这些键若**低于**下表值（早期版本落盘的小值，会让推理模型的思考链
#: 吃光输出额度、片源档案整段落空），首次加载时自动抬到新默认。带迁移标记
#: 保证只做一次——之后用户若手动调小，程序不再覆盖。
_RAISE_ON_MIGRATE = {
    "calib_chunk_cues": 400,
    "calib_max_chars": 60000,
    "calib_max_tokens": 65536,
    "calib_context_tokens": 1000000,
}
_TOKEN_MIGRATION_TAG = "1.15.4"


def load_config() -> dict:
    """读取 AI 配置；文件不存在时用默认值落盘一份，方便用户直接修改。

    v1.12.0 兼容迁移：旧双通道配置（接口 A 的 base_url 为 Anthropic 地址、
    接口 B 为 llm_base_url/llm_model）自动合并为单通道——用接口 B 的
    地址/模型顶上（两通道密钥本就共用同一个）。
    """
    cfg = dict(DEFAULT_CONFIG)
    _migrated = False
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
            # v1.15.4 一次性迁移：早期落盘的 calib_* 偏小（如 max_tokens=5120），
            # 推理模型下思考链会把正文挤空 ⇒ 抬到新默认（见 _RAISE_ON_MIGRATE）。
            if str(raw.get("calib_token_migrated") or "") != _TOKEN_MIGRATION_TAG:
                for _k, _v in _RAISE_ON_MIGRATE.items():
                    try:
                        if int(cfg.get(_k) or 0) < _v:
                            cfg[_k] = _v
                    except (TypeError, ValueError):
                        cfg[_k] = _v
                cfg["calib_token_migrated"] = _TOKEN_MIGRATION_TAG
                _migrated = True
    except (OSError, ValueError):
        pass
    if not CONFIG_PATH.exists() or _migrated:
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
    # 火山方舟裸端点（…/api/plan、…/api/coding）：补 v3 版本段——通用规则
    # 会把尾段 "plan"/"coding" 当裸域名，错拼成 /api/plan/v1/chat/
    # completions（2026-10-01 实测，方舟只认 /api/plan/v3 与 /api/coding/v3）
    host, path = _host_path(b)
    if ("volces.com" in host or "volcengine" in host) \
            and path.rstrip("/").endswith(("/api/plan", "/api/coding")):
        return b + "/v3/chat/completions"
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
                      "/chat/completions", "/v2/upload", "/v2/transcript",
                      "/api/v1/services/aigc/multimodal-generation/generation")


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


def _is_maas_base(base: str) -> bool:
    """是否阿里云百炼 maas 专属实例端点（Token Plan / 专属实例）。

    专属实例的 /models 列表**不列 ASR 模型**（实测 2026-09-20：部署在
    token-plan 实例上的 qwen-audio-3.0-asr-flash 也不在列表里），列表核对
    对这类端点不可信，需要发真实探测请求实锤。
    """
    return "maas.aliyuncs.com" in str(base or "").lower()


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
                 "volcengine", "assemblyai", "dashscope_realtime",
                 "dashscope_native", "dashscope_filetrans")

#: 百炼原生（multimodal-generation）录音文件识别模型的官方 API 路径
ASR_NATIVE_PATH = "/api/v1/services/aigc/multimodal-generation/generation"

#: 实时（WebSocket 流式）模型特征：一次性上传整段音频用不了它们
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


def is_dashscope_native_asr(model: str) -> bool:
    """是否百炼**原生端点**专用的录音文件识别模型（qwen-audio 系带 asr）。

    与引擎侧 `is_dashscope_native_asr` 同规则。实测（2026-09-20）：
    qwen-audio-3.0-asr-flash 打 compatible-mode 的 chat/completions 恒回
    HTTP 400 空体，换原生端点即 200 —— 协议推断必须在这里就分出去。
    """
    m = str(model or "").lower()
    if not m or "filetrans" in m or any(h in m for h in ASR_REALTIME_HINTS):
        return False
    return "qwen-audio" in m and "asr" in m


def _asr_native_url(base: str) -> str:
    """推导百炼原生 ASR 端点（只换路径，不换域名）。与引擎侧同规则。"""
    b = _asr_base_clean(base)
    low = b.lower()
    if low.endswith(ASR_NATIVE_PATH.lower()):
        return b
    if not b:
        return "https://dashscope.aliyuncs.com" + ASR_NATIVE_PATH
    if "//" in b:
        scheme, rest = b.split("//", 1)
        return scheme + "//" + rest.split("/", 1)[0] + ASR_NATIVE_PATH
    return "https://" + b.split("/", 1)[0] + ASR_NATIVE_PATH


#: 只可能在境内可达的国内 AI/ASR 端点后缀。必须与 src/video_toolbox.py 的
#: DOMESTIC_AI_ENDPOINT_SUFFIXES 同规则（引擎与 AI 客户端两侧一致）。
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


def is_domestic_ai_endpoint(url: str) -> bool:
    """端点是否属于「只在境内可达」的国内 AI/ASR 服务。"""
    host, _ = _host_path(url)
    host = host.split(":")[0]
    return any(host == s or host.endswith("." + s)
               for s in DOMESTIC_AI_ENDPOINT_SUFFIXES)


def urlopen_endpoint(req, timeout):
    """按端点归属选 opener：国内端点强制直连，其余跟随系统/环境代理。

    urllib 默认同样经 ``getproxies()`` 读 Windows 注册表的系统代理
    （Clash / FlClash 一类），国内百炼端点被送进海外节点转发会被对端直接
    断连——表现为让人误判「实例没有可用的 ASR」。空 dict 的 ProxyHandler
    表示「不走任何代理」，且 ``build_opener`` 不会再补上默认 ProxyHandler，
    与 ``src/push_via_git_api.py`` 的 ``_OPENER`` 是同一手法。
    """
    url = getattr(req, "full_url", "") or (req if isinstance(req, str) else "")
    if is_domestic_ai_endpoint(url):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        return opener.open(req, timeout=timeout)
    return urllib.request.urlopen(req, timeout=timeout)


_TTS_HINTS = ("tts", "speech-synthesis", "voice-synthesis", "cosyvoice",
              "sambert")


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


def _is_volces_plan_url(url: str) -> bool:
    """是否火山方舟「Token Plan」端点（.../api/plan/v3[/chat/completions]）。

    该端点只收「支持 agent plan 特性」的模型（doubao-seed 系列等套餐模型）；
    deepseek-flash 这类纯按量模型打上去恒回 HTTP 404 UnsupportedModel
    （"The requested model does not support the agent plan feature"）。
    """
    host, path = _host_path(url)
    if "volces.com" not in host and "volcengine" not in host:
        return False
    return "/api/plan/" in path or path.rstrip("/").endswith("/api/plan")


def _is_volces_paygo_url(url: str) -> bool:
    """是否火山方舟**按量**端点（.../api/v3[/chat/completions]）。

    与 _is_volces_plan_url 互斥；用于识别「地址填按量、Key 却是套餐 Key」
    这类反向设置错配（打上去恒 401 AuthenticationError）。
    """
    host, path = _host_path(url)
    if "volces.com" not in host and "volcengine" not in host:
        return False
    p = path.rstrip("/")
    if "/api/plan/" in p or p.endswith("/api/plan") \
            or "/api/coding/" in p or p.endswith("/api/coding"):
        return False
    return p.startswith("/api/v3")


def _volces_paygo_url(url: str) -> str:
    """火山方舟 Token Plan 端点 → 按量计费端点（/api/plan → /api/v3，只换路径）。

    同一个 API Key 两个端点通用：套餐模型走 /api/plan/v3 消耗套餐额度，
    按量模型必须走 /api/v3。2026-10-01 修复：此前地址栏填
    ark.cn-beijing.volces.com/api/plan/v3 + deepseek-flash，测试连接直接
    报「HTTP 404 UnsupportedModel … agent plan feature」，用户无从下手。
    注意传入的可能是已拼好 /chat/completions 的完整地址，要替换的是
    /api/plan/v3 整段（换成 /api/v3），不能只换 /api/plan/ 前缀——
    否则会把 /api/plan/v3/chat/completions 改错成 /api/v3/v3/chat/completions。

    2026-10-01 实测修正：Token Plan 发放的 Key 只被 /api/plan/* 接受，
    打按量端点恒 401 AuthenticationError——回落能否成功取决于 Key 类型。
    2026-10-01 v2：该回落已降级为「就地自救后的第二选择」，见 _post_openai。
    """
    return _re.sub(r"/api/plan/v(\d+)", r"/api/v\1", str(url or ""), count=1)


#: 火山方舟 Agent Plan（Token Plan）支持的模型名单（2026-10-01 官方文档
#: volcengine.com/docs/82379/2366394）。该端点只收名单内模型；名单外模型
#: （含 deepseek-flash 等纯按量模型）打上去恒回 404 UnsupportedModel。
VOLCES_PLAN_MODELS = frozenset({
    "doubao-seed-2.0-mini", "doubao-seed-2.0-lite", "doubao-seed-2.1-turbo",
    "doubao-seed-evolving", "deepseek-v4-flash", "deepseek-v4-pro",
    "deepseek-v4.1-flash", "glm-5.3", "glm-5.3-flash", "glm-latest",
    "minimax-m3", "kimi-k2.7-code", "kimi-k2.8-preview", "kimi-k3",
})

#: 套餐端点的自动匹配默认模型：多模态（视觉通道可沿用）、1M 上下文、
#: 384K 最大输出，校准的大上下文 + 大输出场景都够用。
VOLCES_PLAN_DEFAULT_MODEL = "deepseek-v4.1-flash"

#: 各平台端点的「模型名白名单外」判据与回落：键 = 域名关键词，
#: 值 = (必须排除的模型名集合, 明显不属于本族的前缀, 回落模型)。
#: 之所以用「排除集 + 族前缀」两段判据：单靠前缀会把跨平台的
#: deepseek-flash（火山按量名）误判成 DeepSeek 官方模型。
PROVIDER_RULES = {
    "api.deepseek.com": {
        # 2026-10-05 按官方文档重核（api-docs.deepseek.com/quick_start/pricing）：
        #   官方现役模型只有 **deepseek-flash**（通用，1M 上下文 / 384K 输出，
        #   支持视觉）与 **deepseek-v4-pro**（推理，1M / 384K，不支持视觉）。
        #   旧名 deepseek-chat / deepseek-reasoner 已于 2026-07-24 23:59 停用；
        #   deepseek-v4.1-flash 是火山方舟套餐侧的名字，官方不认。
        #   官方仍兼容 deepseek-v4-flash / deepseek-v4-flash-vision-exp
        #   （等价 deepseek-flash，按 Flash 计费）⇒ 不列入排除集，原样放行。
        "not_here": frozenset({"deepseek-chat", "deepseek-reasoner",
                               "deepseek-v3", "deepseek-v3.2", "deepseek-r1",
                               "deepseek-v4.1-flash"}),
        "prefixes": ("deepseek-",),
        "default": "deepseek-flash",
        "hint": "DeepSeek 官方现役模型为 deepseek-flash（通用+视觉）与 "
                "deepseek-v4-pro（推理）；旧名 deepseek-chat / "
                "deepseek-reasoner 已于 2026-07-24 停用",
    },
    "bigmodel.cn": {
        "not_here": frozenset(),
        "prefixes": ("glm-", "charglm-", "embedding-", "cogview-", "cogvideo-"),
        "default": "glm-4.7-flash",
    },
    ".z.ai": {
        "not_here": frozenset(),
        "prefixes": ("glm-",),
        "default": "glm-4.7-flash",
    },
    "volces.com": {
        "not_here": frozenset(),
        "prefixes": ("doubao-", "deepseek-v", "kimi-", "glm-", "minimax-",
                     "seed-", "skylark-"),
        "default": "",
    },
    "volcengine": {
        "not_here": frozenset(),
        "prefixes": ("doubao-", "deepseek-v", "kimi-", "glm-", "minimax-",
                     "seed-", "skylark-"),
        "default": "",
    },
    "aliyuncs.com": {
        "not_here": frozenset(),
        "prefixes": ("qwen", "paraformer", "fun-", "sambert", "cosyvoice",
                     "wanx", "stable-diffusion"),
        "default": "",
    },
    "dashscope": {
        "not_here": frozenset(),
        "prefixes": ("qwen", "paraformer", "fun-", "sambert", "cosyvoice"),
        "default": "",
    },
    "api.openai.com": {
        "not_here": frozenset(),
        "prefixes": ("gpt-", "o1", "o3", "o4", "chatgpt", "whisper",
                     "text-embedding", "tts-", "dall-e"),
        "default": "",
    },
}

#: 别名对照（模型名抄错平台/抄到已停用的旧名时，给出官方现役替代）
#: 2026-10-05 按官方文档重核：deepseek-chat / deepseek-reasoner 已于
#: 2026-07-24 停用，现役只有 deepseek-flash 与 deepseek-v4-pro。
DEEPSEEK_OFFICIAL_ALIASES = {
    # —— 官方已停用的旧名（打上去恒 404 Model Not Exist）——
    "deepseek-chat": "deepseek-flash",
    "deepseek-reasoner": "deepseek-v4-pro",
    "deepseek-v3": "deepseek-flash",
    "deepseek-v3.2": "deepseek-flash",
    "deepseek-r1": "deepseek-v4-pro",
    # —— 其它平台的模型名（火山方舟套餐侧）——
    "deepseek-v4.1-flash": "deepseek-flash",
}


def provider_of(base_url) -> str:
    """识别端点厂商（返回 PROVIDER_RULES 的域名关键词）；未识别返回空串。

    空串 = 不做厂商级校验（维持原行为，避免误伤自建/中转端点）。
    """
    b = str(base_url or "").lower()
    for key in PROVIDER_RULES:
        if key in b:
            return key
    return ""


def match_provider_model(base_url, model):
    """厂商端点 ↔ 模型名自动匹配：返回 (模型, 说明|None)。

    解决的设置错误：把 A 平台的模型名填到 B 平台端点，或填了**已停用**的旧
    模型名。两类都实测踩过：
      · 「DeepSeek 官方地址 + deepseek-v4.1-flash」——后者是火山方舟套餐侧的
        名字，官方不认；
      · 「DeepSeek 官方地址 + deepseek-chat」——该名 2026-07-24 已停用，现役
        只有 deepseek-flash 与 deepseek-v4-pro（见官方定价页）。
    硬发出去会被服务端当成推理模型（思考链吃光额度、正文为空）或直接报错，
    报错文本里没有任何线索指向"模型名抄错了平台/版本"，用户无从判断。
    """
    p = provider_of(base_url)
    m = str(model or "").strip()
    if not p or not m:
        return m, None
    rule = PROVIDER_RULES.get(p) or {}
    low = m.lower()
    # ① 明确知道「本平台没有这个模型名」→ 给别名替代（说明最贴切）
    if low in (rule.get("not_here") or ()):
        alt = DEEPSEEK_OFFICIAL_ALIASES.get(low) if p == "api.deepseek.com" \
            else None
        alt = alt or rule.get("default")
        if alt and alt != m:
            hint = rule.get("hint") or ""
            return alt, (
                "模型「%s」在该端点（%s）不存在%s，已自动换成「%s」"
                % (m, p, ("（" + hint + "）") if hint else "", alt))
    # ② 族前缀不匹配 → 换该平台通用模型（仅限有默认值的平台）
    prefixes = rule.get("prefixes") or ()
    if prefixes and not low.startswith(tuple(prefixes)):
        dft = rule.get("default")
        if dft and dft != m:
            return dft, ("模型「%s」不属于该端点的模型族（%s），已自动换成该"
                         "平台通用模型「%s」"
                         % (m, " / ".join(prefixes), dft))
    return m, None


#: 已知模型的能力表（上下文 ctx / 单次最大输出 out，tokens）：「设置自动
#: 匹配」据此钳制输入/输出预算；表外模型不钳制（维持原行为）。
#: 数值来源：火山方舟 Agent Plan 官方文档（2026-10-01）、DeepSeek 官方
#: 文档；取标称的保守可用值，超发的部分会在发送前被夹回。
MODEL_CAPS = {
    # —— 火山方舟 Agent Plan 套餐模型 ——
    "deepseek-v4.1-flash":  {"ctx": 1048576, "out": 393216},
    "deepseek-v4-flash":    {"ctx": 1048576, "out": 393216},
    "deepseek-v4-pro":      {"ctx": 1048576, "out": 393216},
    "kimi-k2.8-preview":    {"ctx": 1048576, "out": 1048576},
    "glm-5.3":              {"ctx": 1048576, "out": 131072},
    "glm-latest":           {"ctx": 1048576, "out": 131072},
    "glm-5.3-flash":        {"ctx": 1048576, "out": 131072},
    "kimi-k3":              {"ctx": 1048576, "out": 131072},
    "minimax-m3":           {"ctx": 1048576, "out": 131072},
    "doubao-seed-evolving": {"ctx": 1048576, "out": 262144},
    "doubao-seed-2.1-turbo": {"ctx": 262144, "out": 262144},
    "doubao-seed-2.0-lite": {"ctx": 262144, "out": 131072},
    "doubao-seed-2.0-mini": {"ctx": 262144, "out": 131072},
    "kimi-k2.7-code":       {"ctx": 262144, "out": 32768},
    # —— 火山方舟按量常见 ——
    "doubao-seed-1.6-flash":        {"ctx": 262144, "out": 8192},
    "doubao-seed-1.6-flash-250828": {"ctx": 262144, "out": 8192},
    # ⚠️ 同名跨平台：本行是**火山方舟按量**侧的 deepseek-flash。DeepSeek
    #    官方也有同名模型但能力大得多（1M / 384K），故官方端点走下面的
    #    PROVIDER_MODEL_CAPS 覆盖表，不要在这里写官方数值。
    "deepseek-flash":       {"ctx": 131072, "out": 65536},
    # ⚠️ 已删除 deepseek-chat / deepseek-reasoner（2026-07-24 官方停用）。
    #    这两名字现在只可能出现在第三方中转上，各家中转的能力值无从核实，
    #    按「表外模型不钳制」处理——宁可让端点自己报错并由 _shrink_max_tokens
    #    减半自愈，也不要拿旧官方的 65536/8192 去误伤 1M 上下文的中转。
}


#: 厂商级能力覆盖表：**同名模型在不同平台能力不同**时用（最典型的就是
#: deepseek-flash —— DeepSeek 官方 1M/384K，火山方舟按量另有数值）。
#: 查表顺序：先厂商覆盖表，再回落 MODEL_CAPS。
#: 数值来源：DeepSeek 官方定价页 api-docs.deepseek.com/quick_start/pricing
#: （2026-10-05 核对）——deepseek-flash 与 deepseek-v4-pro 均为
#: 上下文 1M、单次最大输出 384K。
PROVIDER_MODEL_CAPS = {
    "api.deepseek.com": {
        "deepseek-flash":     {"ctx": 1048576, "out": 393216},
        # 官方兼容的旧名，等价 deepseek-flash（按 Flash 计费）
        "deepseek-v4-flash":  {"ctx": 1048576, "out": 393216},
        "deepseek-v4-flash-vision-exp": {"ctx": 1048576, "out": 393216},
        "deepseek-v4-pro":    {"ctx": 1048576, "out": 393216},
    },
}


#: 厂商级「无视觉能力」模型 → 该平台的视觉替代模型。视觉槽填到这些模型上
#: 时屏幕识别/截图理解必失败（服务端直接报"不支持图片输入"）。
#: DeepSeek 官方：deepseek-v4-pro 不支持 Vision，deepseek-flash 支持。
PROVIDER_NO_VISION = {
    "api.deepseek.com": (frozenset({"deepseek-v4-pro"}), "deepseek-flash"),
}


def model_caps(model, base_url=None):
    """查模型能力表：{"ctx":…, "out":…}；表外模型返回 None（不钳制）。

    base_url 非空时先查厂商级覆盖表 PROVIDER_MODEL_CAPS（同名模型跨平台
    能力不同，如 deepseek-flash），未命中再回落通用表 MODEL_CAPS。
    """
    name = str(model or "").strip().lower()
    if base_url:
        p = provider_of(base_url)
        if p:
            hit = (PROVIDER_MODEL_CAPS.get(p) or {}).get(name)
            if hit:
                return hit
    return MODEL_CAPS.get(name)


#: 订阅套餐（Plan）端点 → (套餐名, 条款要点)。这类端点的服务条款普遍**只允许
#: 交互式使用**，明确禁止「自动化脚本 / 自定义应用程序后端 / 非交互式批量调用」。
#: 产品口径（2026-10-05 用户拍板）：**不阻止用户接入**——能不能用、会不会被判
#: 违规由服务商判定，但程序必须把风险讲清楚，风险由用户自负。
#: 判据只认套餐专属端点，按量端点（dashscope 公共 / 火山 /api/v3）不在此列，
#: 也不要把 `*.maas.aliyuncs.com` 泛化成套餐——那还会命中专属实例。
PLAN_ENDPOINT_RISKS = (
    (("token-plan",), "百炼 Token Plan",
     "仅限在编程工具/智能体工具中交互式使用，不可用于自动化脚本、"
     "自定义应用程序后端或任何非交互式批量调用"),
    (("coding.dashscope.aliyuncs.com",), "百炼 Coding Plan",
     "仅限编程工具交互式使用，批量/自动化调用同样属于超范围使用"),
    (("/api/plan/", "/api/plan"), "火山方舟 Agent Plan（Token Plan）",
     "套餐权益限交互式使用，脚本化批量调用可能被判定为滥用"),
    (("/api/coding",), "火山方舟 / 智谱 Coding Plan",
     "仅限编程工具交互式使用，批量/自动化调用属于超范围使用"),
)


def plan_endpoint_risk(base_url) -> str:
    """订阅套餐端点的**合规风险**提示；不是套餐端点则返回空串。

    只提示、不改变任何请求行为（不拦、不改地址、不改模型）。本软件的转录与
    字幕校准是典型的**批量非交互调用**，恰好落在多数套餐条款的禁止范围内，
    用户看不到条款就会在毫不知情的情况下把 Key 用成违规状态——所以这里把
    条款原文要点与稳妥替代（按量端点）一并说清。
    """
    b = str(base_url or "").strip().lower()
    if not b:
        return ""
    for keys, name, note in PLAN_ENDPOINT_RISKS:
        if any(k in b for k in keys):
            return ("⚠️ 该地址是「%s」订阅套餐端点：套餐条款规定%s。本软件的"
                    "转录与字幕校准属于批量非交互调用，若被服务商判定违规，"
                    "可能被暂停订阅或封禁 API Key——**风险由你自行承担**。"
                    "求稳请改用按量计费端点（百炼 dashscope.aliyuncs.com/"
                    "compatible-mode/v1、火山方舟 ark.cn-beijing.volces.com/"
                    "api/v3、硅基流动 api.siliconflow.cn/v1）。" % (name, note))
    return ""


def match_volces_plan_model(base_url, model):
    """Token Plan 端点的模型自动匹配：返回 (模型, 调整说明|None)。

    地址是火山套餐端点（/api/plan/v3，含裸 /api/plan）而模型不在套餐名单
    内时，自动换成套餐默认模型 VOLCES_PLAN_DEFAULT_MODEL——原模型多半是
    纯按量模型（deepseek-flash 等），硬发只会 404 UnsupportedModel，而按量
    端点又不认套餐 Key（401），这个组合没有任何一端能通。模型留空时回落
    到套餐默认模型；端点与模型本就匹配则原样返回。
    """
    if not _is_volces_plan_url(str(base_url or "")):
        return str(model or "").strip(), None
    m = str(model or "").strip()
    if m.lower() in VOLCES_PLAN_MODELS:
        return m, None
    return VOLCES_PLAN_DEFAULT_MODEL, (
        "模型「%s」不在火山方舟 Token Plan 套餐内，已自动切换为「%s」"
        "（套餐模型；原模型属按量计费，套餐端点不接收、按量端点又不认"
        "套餐 Key）" % (m or "(空)", VOLCES_PLAN_DEFAULT_MODEL))


#: 输入/输出预算的出厂默认（与 DEFAULT_CONFIG 保持一致，供 match_settings 用）
_CALIB_OUT_DEFAULT = 65536
_CALIB_CTX_DEFAULT = 1000000


def match_settings(cfg: dict) -> tuple[dict, list]:
    """设置自动匹配（2026-10-01 v2）：把一份 AI 配置**修正成自洽可用的组合**。

    返回 (修正后的配置副本, 说明列表)。纯函数，不改传入的 dict，不发网络请求。

    修正项（"设置错误"逐项自动纠正，避免用户对着报错猜）：
      0. **厂商 ↔ 模型名**：把 A 平台的模型名填到 B 平台端点，或填了已停用的
         旧名（如 DeepSeek 官方地址 + 已停用的 deepseek-chat / 火山套餐侧的
         deepseek-v4.1-flash）→ 换成该平台现役模型。
      1. **端点 ↔ 模型**：Token Plan 端点（/api/plan/v3）+ 名单外模型 →
         换成套餐默认模型。套餐 Key 打按量端点必 401、按量模型打套餐端点
         必 404，两端都不通。
      2. **视觉模型**：视觉槽留空时跟随文本模型；地址与文本同源时一并匹配。
      2b. **视觉能力**：视觉槽落到「不支持图片输入」的模型上（DeepSeek 官方
         deepseek-v4-pro）→ 换成同平台的视觉模型（deepseek-flash）。
      3. **输出预算**：calib_max_tokens 超模型单次输出上限 → 夹到上限
         （推理模型思考链吃光额度会让正文为空，超发只会换来 400）。
         能力值先按厂商覆盖表（PROVIDER_MODEL_CAPS）取，再回落通用表。
      4. **上下文预算**：calib_context_tokens 超模型上下文上限 → 夹到上限。
      5. **预算过低兜底**：输出低于 8192（校准无法工作）→ 抬到 8192。
    """
    out = dict(cfg or {})
    notes: list = []

    base = str(out.get("base_url") or "").strip()
    model = str(out.get("model") or "").strip()

    # ---- 0. 厂商 ↔ 模型名（先做：跨平台抄错模型名比端点类型错更常见）----
    new_model, note = match_provider_model(base, model)
    if note:
        notes.append(note)
        out["model"] = new_model
        model = new_model

    # ---- 1. 端点 ↔ 模型 ----
    new_model, note = match_volces_plan_model(base, model)
    if note:
        notes.append(note)
        out["model"] = new_model
        model = new_model

    # ---- 2. 视觉模型 ----
    vbase = (str(out.get("vision_base_url") or "").strip() or base)
    vmodel = str(out.get("vision_model") or "").strip()
    if not vmodel:
        out["vision_model"] = model
        if model:
            notes.append("视觉模型留空，已跟随文本模型「%s」" % model)
    else:
        new_v, note = match_provider_model(vbase, vmodel)
        if note:
            notes.append("视觉通道：" + note)
            out["vision_model"] = new_v
            vmodel = new_v
        new_v, note = match_volces_plan_model(vbase, vmodel)
        if note:
            notes.append("视觉通道：" + note)
            out["vision_model"] = new_v
    # 视觉槽与文本槽指向同一套餐端点时，用非套餐视觉模型同样会 404
    if base and not vbase:
        out["vision_base_url"] = base

    # ---- 2b. 视觉能力：模型本身不收图片 → 换同平台的视觉模型 ----
    # DeepSeek 官方 deepseek-v4-pro 不支持 Vision；用户把文本模型设成它、
    # 视觉槽留空（跟随文本）时，屏幕识别/截图理解会直接报"不支持图片输入"。
    _vnow = str(out.get("vision_model") or "").strip()
    _vrule = PROVIDER_NO_VISION.get(provider_of(vbase) or provider_of(base))
    if _vrule and _vnow.lower() in _vrule[0] and _vrule[1] != _vnow:
        out["vision_model"] = _vrule[1]
        notes.append("视觉模型「%s」不支持图片输入（屏幕识别会失败），已换成"
                     "同平台的「%s」" % (_vnow, _vrule[1]))

    # ---- 3~5. 预算钳制 ----
    caps = model_caps(model, base)
    if caps:
        try:
            _mt = int(out.get("calib_max_tokens") or _CALIB_OUT_DEFAULT)
        except (TypeError, ValueError):
            _mt = _CALIB_OUT_DEFAULT
        if _mt > caps["out"]:
            out["calib_max_tokens"] = caps["out"]
            notes.append("输出预算 %d → %d（模型「%s」的单次输出上限）"
                         % (_mt, caps["out"], model))
        try:
            _cx = int(out.get("calib_context_tokens") or _CALIB_CTX_DEFAULT)
        except (TypeError, ValueError):
            _cx = _CALIB_CTX_DEFAULT
        if _cx > caps["ctx"]:
            out["calib_context_tokens"] = caps["ctx"]
            notes.append("上下文预算 %d → %d（模型「%s」的上下文上限）"
                         % (_cx, caps["ctx"], model))
    try:
        if int(out.get("calib_max_tokens") or 0) < 8192:
            notes.append("输出预算 %s → 8192（推理模型的思考链会吃光额度，"
                         "过小会让正文为空）" % out.get("calib_max_tokens"))
            out["calib_max_tokens"] = 8192
    except (TypeError, ValueError):
        pass

    return out, notes


def is_volces_plan_base(base_url) -> bool:
    """公开判据：该地址是不是火山方舟 Token Plan 端点（设置页/校准入口共用）。"""
    return _is_volces_plan_url(str(base_url or ""))


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
    if "filetrans" in model:
        # 与引擎侧 _infer_asr_protocol 同规则：-filetrans 是百炼异步文件转写
        # 专有命名，走提交-轮询链路（不收本地音频）。
        return "dashscope_filetrans"
    if "openspeech.bytedance.com" in base or "volcengine" in base:
        return "volcengine"
    if "assemblyai.com" in base:
        return "assemblyai"
    if ("aliyuncs.com" in base or "dashscope" in base) and any(
            h in model for h in ASR_REALTIME_HINTS):
        # 百炼系域名 + 实时模型：只有 WebSocket 形态（与引擎侧同规则）
        return "dashscope_realtime"
    if ("aliyuncs.com" in base or "dashscope" in base) \
            and is_dashscope_native_asr(model):
        # Qwen-Audio-3.0-ASR-Flash 这类原生端点专用模型（与引擎侧同规则）
        return "dashscope_native"
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
    if "anthropic" in b or _is_anthropic_only_path(b):
        return ("ASR 地址填的是 Anthropic 文本对话端点（%s）——它收不了音频。"
                "请改填 OpenAI 兼容端点：公共百炼 "
                "https://dashscope.aliyuncs.com/compatible-mode/v1，Token Plan "
                "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1，"
                "火山方舟 https://ark.cn-beijing.volces.com/api/v3（Coding Plan "
                "为 /api/coding/v3），或专属实例的 …/compatible-mode/v1" % base_url)
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


#: 主动探测用的官方示例音频（真实人声，阿里云 OSS 长期样例）。
#: ⚠️ 必须用**真实语音**：ASR 模型收到无语音的正弦波/静音时会回 HTTP 400
#: 空体，拿它探测会把「模型完全正常」误报成「收不了音频」（v1.15.6 踩过）。
ASR_PROBE_AUDIO_URL = ("https://dashscope.oss-cn-beijing.aliyuncs.com/"
                       "samples/audio/paraformer/hello_world_female2.wav")


def _asr_native_probe(base: str, api_key: str, model: str):
    """百炼原生 ASR 的主动探测：用官方示例音频实打实跑一次识别。

    返回 (verdict, note)：
      · (True, text)         200 且拿到文本 —— 端点/密钥/模型都对；
      · ("missing", detail)  404 / model not exist —— 该实例没部署这个模型；
      · (False, detail)      其它 HTTP 错误（密钥被拒 / 参数被拒）；
      · (None, err)          网络失败，下不了结论。
    """
    url = _asr_native_url(base)
    body = json.dumps({
        "model": str(model or "").strip(),
        "input": {"messages": [{"role": "user", "content": [
            {"type": "input_audio",
             "input_audio": {"data": ASR_PROBE_AUDIO_URL}}]}]},
        "parameters": {"format": "wav", "sample_rate": "16000"},
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={
        "Authorization": "Bearer " + str(api_key or ""),
        "Content-Type": "application/json",
        "X-DashScope-SSE": "disable"})
    try:
        with urlopen_endpoint(req, 45) as resp:
            raw = resp.read().decode("utf-8", "replace")
        try:
            d = json.loads(raw)
        except ValueError:
            return True, ""            # 200 就算通，解析失败不影响结论
        out = d.get("output") if isinstance(d.get("output"), dict) else {}
        sent = out.get("sentence") if isinstance(out.get("sentence"), dict) else {}
        text = str(sent.get("text") or out.get("text") or d.get("text") or "")
        return True, text
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:200]
        except Exception:  # noqa: BLE001
            pass
        low = detail.lower()
        if e.code in (404, 400) and ("model not exist" in low
                                     or "model_not_found" in low):
            return "missing", "HTTP %d: %s" % (e.code, detail)
        if e.code == 404:
            return "missing", "HTTP %d: %s" % (e.code, detail or e.reason)
        return False, "HTTP %d: %s" % (e.code, detail or e.reason)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return None, str(e)


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
        # 说话人分离（diarization）总开关——只有部分服务端原生支持，
        # 不支持的端点拿到 True 也只是不产生说话人标签。
        "diarize": _asr_diarize_flag(c.get("asr_diarize")),
        # 语音分离（separation）：重叠语音分离 / 音乐 reaction 剔除歌声。
        # 目前仅作接口占位（引擎侧 _asr_separate_audio），无端点消费。
        "separate": _asr_diarize_flag(c.get("asr_separate")),
        "local_model": str(c.get("asr_local_model") or "").strip(),
        "local_model_dir": str(c.get("asr_local_model_dir") or "").strip(),
    }


def _asr_diarize_flag(val) -> bool:
    """把配置里的开关值（bool / 1 / "true" / "yes" / "on"）归一成布尔。"""
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    return str(val or "").strip().lower() in ("1", "true", "yes", "on")


def _is_retryable(status: int | None, detail: str) -> bool:
    """智谱 1305（访问量过大）/ overloaded / 429 / 5xx 可退避重试。"""
    if status is None:                      # 网络错误
        return True
    if status == 429 or status >= 500:
        return True
    d = (detail or "").lower()
    return "1305" in d or "overloaded" in d or "稍后再试" in d


#: 「max_tokens 超过端点上限」类报错的关键词（命中即值得减半重试）
_MAX_TOKENS_OVER_PAT = (
    "max_tokens", "max token", "maximum tokens", "too large", "too big",
    "exceed", "greater than", "at most", "no more than",
    "超过", "超出", "上限", "太大",
)


#: 网络/超时类报错特征：这类错误**永远不是**「输出预算太大」，必须先行排除。
#: 教训（2026-10-05）：_MAX_TOKENS_OVER_PAT 里有「超过/超出/上限」这种泛词，
#: 任何含这些字的中文报错都会被误判成 max_tokens 超限 → 白白跑 6 次减半请求
#: （每次减半还各带一轮 4 次重试），把一次超时放大成重试风暴。
_NETWORK_ERR_PAT = ("超时", "timed out", "timeout", "网络错误", "urlopen",
                    "connection reset", "connection refused", "connection aborted",
                    "dns", "temporary failure", "name or service",
                    "ssl", "proxy", "代理")


def _is_max_tokens_over(err) -> bool:
    """错误文本是否属于「max_tokens 参数值超过端点/模型上限」类。

    ⚠️ 判据故意收紧到「参数值超限」语义：`maximum context length`（输入
    太长）与 `maximum output tokens`（额度太大）文本近似，但前者减半
    max_tokens 没用、只会浪费一次请求。误判代价 = 多一次更快失败的请求；
    漏判代价 = 大额度 + 小端点组合直接报错不可用——两边都可控，取中间值：
    认 max_tokens 字样与超限措辞，不认裸的 context length。
    """
    low = str(err).lower()
    if any(k in low for k in _NETWORK_ERR_PAT):
        return False                      # 超时/连不上：减半 max_tokens 修不了
    if "context length" in low or "上下文" in low:
        return False
    return any(k in low for k in _MAX_TOKENS_OVER_PAT)


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
        if "anthropic" in base.lower() or _is_anthropic_only_path(base):
            raise AIClientError(
                "检测到 Anthropic 协议端点（如 /api/anthropic、火山 /api/coding）。"
                "全局 AI 已统一 OpenAI 兼容协议，请填 OpenAI 兼容地址："
                "智谱按量 https://open.bigmodel.cn/api/paas/v4（Coding Plan 为 "
                "/api/coding/paas/v4）、火山 https://ark.cn-beijing.volces.com/api/v3"
                "（Coding Plan 为 /api/coding/v3）、百炼 Token Plan "
                "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1")
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
        # 设置自动匹配（2026-10-01 v2）：厂商↔模型名、Token Plan 端点↔模型，
        # 两层都过一遍。说明存 auto_notes，由测试连接 / 校准入口亮给用户看
        # （logger 在打包运行时不落界面）。
        self.auto_notes: list = []
        self.model, _n = match_provider_model(base, self.model)
        if _n:
            self.auto_notes.append(_n)
            logger.warning("AI 自动匹配（厂商↔模型）：%s", _n)
        self.model, _n = match_volces_plan_model(base, self.model)
        if _n:
            self.auto_notes.append(_n)
            logger.warning("AI 自动匹配：%s", _n)
        #: 已知「这把 Key 是 Token Plan 套餐专用」——按量端点必 401，
        #: 记下后不再做「换 /api/v3 再撞 401」的无效重试（2026-10-01 v2）。
        self.plan_key_only = False
        #: 最近一次「就地换套餐模型」的说明（失败路径也要能回传给设置页）。
        self._last_rescue = ""
        _vbase = (str(self.cfg.get("vision_base_url") or "").strip()
                  or base)
        self.vision_model, _n = match_volces_plan_model(_vbase,
                                                        self.vision_model)
        if _n and _n not in self.auto_notes:
            self.auto_notes.append(_n)
            logger.warning("AI 自动匹配（视觉通道）：%s", _n)
        self.vision_fallback_model = str(
            self.cfg.get("vision_fallback_model") or "")
        self.max_tokens = int(self.cfg.get("max_tokens") or 2048)
        self.timeout = float(self.cfg.get("timeout") or 90)
        self.retries = int(self.cfg.get("retries")
                           if self.cfg.get("retries") is not None else 3)
        #: 过程事件回调（可选）callable(msg, level) —— 重试 / 超时 / 端点自愈
        #: 这类"过程动作"经它上报给调用方（校准日志），否则用户在整个等待期间
        #: 看不到任何输出，只能把"正在重试"判成"程序卡死"。
        self.on_event = None
        _ensure_file_log()

    # ---- 过程事件上报 ----------------------------------------------------
    def _emit(self, msg: str, level: str = "info") -> None:
        """把一次过程动作同时写进文件日志与调用方回调（都 best-effort）。"""
        try:
            logger.log(logging.WARNING if level in ("err", "warn") else logging.INFO,
                       "%s", msg)
        except Exception:  # noqa: BLE001
            pass
        cb = self.on_event
        if not callable(cb):
            return
        try:
            cb(msg, level)
        except TypeError:
            try:
                cb(msg)
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001
            pass

    # ---- 超时取值 --------------------------------------------------------
    def _timeout_for(self, body: dict) -> float:
        """按本次输出预算放大超时，避免大块校准被 90 秒默认值反复打断。

        2026-10-05 实测：火山 Agent Plan + 400 条/块（约 6 万字符输入、输出
        预算 65536）时，单块正常耗时约 85 秒——**正好压在 90 秒默认超时线上**，
        服务端稍慢就被判超时、退避重试，一块能拖到 7 分 39 秒，而这段等待在
        界面上完全空白（用户只能判断成"卡住"）。这里按输出预算线性放宽：

          · max_tokens ≤ 8192（连通性测试、小请求）→ 维持原超时，行为不变；
          · 更大预算 → 按 token/128 秒给量（65536 → 512s），上限 300 秒。

        上限 300 秒是**刻意留的**：请求期间不检查取消标志，超时太长会让
        「停止」按钮迟迟不生效。
        """
        try:
            mt = int(body.get("max_tokens") or 0)
        except (TypeError, ValueError):
            mt = 0
        if mt <= 8192:
            return self.timeout
        return max(self.timeout, min(300.0, mt / 128.0))

    # ---- 底层请求 --------------------------------------------------------
    def _request(self, url: str, headers: dict, body: dict) -> dict:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        _to = self._timeout_for(body)
        last_err: Exception | None = None
        for attempt in range(self.retries + 1):
            _t0 = time.time()
            try:
                req = urllib.request.Request(url, data=data,
                                             headers=headers, method="POST")
                with urlopen_endpoint(req, _to) as resp:
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
                # 超时与"连不上"分开说：前者多半是模型还没吐完（大块 + 思考），
                # 后者才是网络/代理问题——两者的处置完全不同。
                if isinstance(e, TimeoutError) or "timed out" in str(e).lower():
                    # ⚠ 措辞刻意避开「超过/超出/上限/太大」——那些词会被
                    # _is_max_tokens_over 当成"输出预算太大"，进而触发 6 次
                    # 减半重试（每次还各带一轮 4 次重试），把一次超时放大成
                    # 重试风暴。超时减半 max_tokens 毫无用处。
                    last_err = AIClientError(
                        f"等待响应超时（{_to:.0f} 秒内没收到任何数据）")
                else:
                    last_err = AIClientError(f"网络错误: {e}")
            except json.JSONDecodeError as e:
                # v1.16.5 修复：端点返回非 JSON 正文（网关 HTML 错误页 / 空体）
                # 时 json.loads 抛 JSONDecodeError——它不在上面的 except 元组里，
                # 会直接冒泡绕过重试与 AIClientError 统一包装。归入可重试失败。
                last_err = AIClientError(f"响应非 JSON: {e}")
            if attempt < self.retries:
                wait = 2.0 * (attempt + 1)
                _el = time.time() - _t0
                # 这条以前只走 logger.info，而全项目没配过 logging ⇒ 谁也看不到，
                # 用户只能对着空白的界面等（2026-10-05 实测踩到）。改为 _emit：
                # 文件日志 + 校准日志双落，让"正在重试"看得见。
                self._emit("AI 请求失败（%.0f 秒后重试，第 %d/%d 次；"
                           "本次已等待 %.0f 秒）：%s"
                           % (wait, attempt + 1, self.retries, _el, last_err),
                           "err")
                time.sleep(wait)
        raise last_err or AIClientError("AI 请求失败")

    def _post_openai(self, url: str, body: dict) -> dict:
        """OpenAI 兼容端点（chat/completions）：Bearer 鉴权 + error 字段校验。

        Azure OpenAI 特殊处理：api-key 头鉴权（Bearer 不被接受），
        缺 api-version 参数时自动补默认版本。

        2026-10-01 火山方舟 Plan 端点**设置自动匹配**（v2，按用户实测反馈重写）：

        旧版（v1）的策略是「套餐端点报模型不支持 → 直接换按量端点重试」。
        实测这是错的：套餐 Key 打按量端点**必 401**，等于用一次注定失败的
        请求把「一个设置错误」换成一串 401 报错，逐块校准时还会放大成整轮
        401 风暴（用户看到的正是这个）。v2 改为**先就地自救，再考虑换端点**：

          ① 套餐端点 + 模型不在套餐名单 → 直接把 body 里的模型换成套餐默认
             模型，在**同一个套餐端点**上重发。这一步不需要换端点、不需要
             换 Key，是纯设置错配，绝大多数情况到此即通（并把换过的模型
             记进 auto_notes，供上层写回设置）。
          ② ①仍报「模型不支持」→ 才按老路换 /api/v3 试一次。
          ③ 换按量端点若回 401 → 把 `self.plan_key_only = True` 记在实例上，
             之后**不再尝试换端点**（Plan Key 只认 /api/plan/*，重试纯属浪费），
             直接抛出含修复动作的中文说明。
        """
        try:
            return self._post_openai_once(url, body)
        except AIClientError as e:
            low = str(e).lower()
            # —— 反向设置错配：地址填了按量端点（/api/v3）而 Key 是套餐 Key ——
            # 这是「设置错误」的另一半。按量端点对套餐 Key 恒 401，用户在设置页
            # 只看到一串英文 AuthenticationError，无从下手。这里认出火山按量
            # 地址 + 401，直接给「把地址改回 /api/plan/v3」这一条动作。
            if (_is_volces_paygo_url(url)
                    and ("401" in low or "authenticationerror" in low
                         or "unauthorized" in low)):
                self.plan_key_only = True
                raise AIClientError(
                    "火山方舟按量端点（/api/v3）拒绝了当前 API Key（401）："
                    "这把是 Token Plan（套餐）专用 Key，按量端点不认它。\n"
                    "修复：把「接口地址」改回 https://ark.cn-beijing.volces.com/"
                    "api/plan/v3，或点一次「自动匹配」（程序会按地址纠正模型）；"
                    "只有到控制台新建常规 Key 之后，才该使用 /api/v3。"
                    "（原始报错：%s）" % str(e)[:200]) from e
            if not (_is_volces_plan_url(url)
                    and ("agent plan" in low or "unsupportedmodel" in low
                         or "unsupported model" in low)):
                raise
            # —— ① 就地自救：只换模型，端点和 Key 都不动 ——
            _old = str(body.get("model") or "")
            if _old.strip().lower() not in VOLCES_PLAN_MODELS:
                body = dict(body)
                body["model"] = VOLCES_PLAN_DEFAULT_MODEL
                note = ("模型「%s」不在火山方舟 Token Plan 套餐内，已自动切换"
                        "为套餐模型「%s」" % (_old or "(空)",
                                              VOLCES_PLAN_DEFAULT_MODEL))
                logger.warning("设置自动匹配：%s（重发到套餐端点）", note)
                try:
                    resp = self._post_openai_once(url, body)
                except AIClientError as e1:
                    logger.warning("换套餐模型后仍失败：%s", str(e1)[:160])
                    low, _ = str(e1).lower(), note
                    self._last_rescue = note
                else:
                    if url == getattr(self, "url", None):
                        self.model = VOLCES_PLAN_DEFAULT_MODEL
                    if url == getattr(self, "vision_url", None):
                        self.vision_model = VOLCES_PLAN_DEFAULT_MODEL
                    if note not in self.auto_notes:
                        self.auto_notes.append(note)
                    return resp
            # —— ② Plan Key 已知只认套餐端点：不再做注定 401 的换端点重试 ——
            if getattr(self, "plan_key_only", False):
                raise AIClientError(
                    "当前 API Key 是火山方舟 Token Plan（套餐）专用 Key，"
                    "只被 /api/plan/v3 接受，按量端点（/api/v3）一律 401。\n"
                    "请在设置的「全局 AI」卡片点一次「自动匹配」：程序会把"
                    "模型换成套餐内模型并保持 /api/plan/v3 地址；"
                    "若确实想用按量模型（deepseek-flash 等），需到火山方舟"
                    "控制台新建一把常规 Key 并把地址改为 "
                    "https://ark.cn-beijing.volces.com/api/v3。"
                    "（原始报错：%s）" % str(e)[:200]) from e
            fixed = _volces_paygo_url(url)
            logger.warning("Token Plan 端点不支持当前模型（%s），"
                           "改用按量端点 %s 重试", str(e)[:120], fixed)
            try:
                resp = self._post_openai_once(fixed, body)
            except AIClientError as e2:
                low2 = str(e2).lower()
                if ("401" in low2 or "authentication" in low2
                        or "api key" in low2 or "ak/sk" in low2):
                    # 套餐 Key 打按量端点：这个组合没有任何一端能通，别再
                    # 让用户对着 401 猜——记住 Key 类型，并直接说明处置方式。
                    self.plan_key_only = True
                    raise AIClientError(
                        "按量端点（/api/v3）拒绝了当前 API Key（401 鉴权失败）："
                        "这把是 Token Plan（套餐）专用 Key，只能在 /api/plan/v3 "
                        "上使用，按量端点不认它。\n"
                        "最快修复：在设置的「全局 AI」卡片点一次「自动匹配」"
                        "——程序会把模型换成套餐内模型（deepseek-v4.1-flash 等）"
                        "并保持 https://ark.cn-beijing.volces.com/api/plan/v3 地址；\n"
                        "想改用按量：到火山方舟控制台「API Key 管理」新建常规 "
                        "Key，接口地址改为 https://ark.cn-beijing.volces.com/api/v3。"
                        "（按量重试原文：%s）" % str(e2)[:200]) from e2
                raise AIClientError(
                    "当前模型不支持火山方舟 Token Plan 端点（/api/plan/v3），"
                    "改用按量端点（/api/v3）重试仍失败：%s。按量模型"
                    "（deepseek-flash 等）请把接口地址改为 "
                    "https://ark.cn-beijing.volces.com/api/v3；只有套餐内模型"
                    "才需要保留 /api/plan/v3。" % str(e2)[:300]) from e2
            if url == getattr(self, "url", None):
                self.url = fixed
            if url == getattr(self, "vision_url", None):
                self.vision_url = fixed
            return resp

    def _post_openai_once(self, url: str, body: dict) -> dict:
        """单发一次 OpenAI 兼容请求（Plan 自愈的重试目标，见 _post_openai）。"""
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

    def _shrink_max_tokens(self, body: dict, first_err: str,
                           floor: int = 1024):
        """max_tokens 被端点拒绝时的减半自愈（2026-09-20，配合「输出」512K）。

        各家端点输出上限不一（DeepSeek 384K、多数中转 64K/16K），用户在设置
        页把「输出」调到 512K 后，小端点会直接 400 报参数超限。此处逐次减半
        重发（最多 6 次、下界 floor），拿到成功响应即返回 (实际额度, resp)。
        仍失败则抛最后一次错误——此时是真打不通，不是额度问题。
        """
        cur = int(body.get("max_tokens") or 0)
        err = first_err
        for _ in range(6):
            cur //= 2
            if cur < floor:
                break
            body["max_tokens"] = cur
            logger.info("接口拒绝 max_tokens（%s），减半到 %d 重试",
                        err[:120], cur)
            try:
                resp = self._post_openai(self.url, body)
                return cur, resp
            except AIClientError as e:
                err = str(e)
                if not _is_max_tokens_over(e):
                    raise
        raise AIClientError(
            f"端点不接受当前 max_tokens（减半到 {cur} 仍被拒）：{err[:200]}")

    def chat_openai(self, prompt, *, system: str | None = None,
                    max_tokens: int | None = None,
                    model: str | None = None,
                    on_reasoning=None,
                    thinking: bool | None = None,
                    reasoning_effort: str | None = None) -> str:
        """OpenAI 兼容文本对话。返回首个 choice 的文本。

        on_reasoning（v1.14.2）：可选回调，接收模型思考链文本
        （message.reasoning_content，或 content 块列表里的 thinking 块），
        供 AI 校准等场景把 Agent 的推理过程打进日志；回调异常不影响主流程。

        thinking / reasoning_effort（2026-09-20，参考模型厂商「高级配置」）：
        仅显式传入时才写进请求体（不影响未传参数的其它调用）——
          · thinking=False → {"thinking":{"type":"disabled"},
            "reasoning_effort":"none"}（DeepSeek/智谱等混合思考模型均认）；
          · thinking=True + effort(low/medium/high/max) → "reasoning_effort"；
        端点不认识这些参数（HTTP 400 参数类报错）时自动去掉重试一次。

        max_tokens 超限自愈（2026-09-20）：设置页「输出」最高可调 512K，但
        各家端点上限不一（DeepSeek 384K、部分中转 64K）——被端点以
        max_tokens 超限类错误拒绝时，自动**减半重试**（最低 1024），让大额度
        配置在支持的端点全额下发、在不支持的端点降级可用而不是直接报错。
        """
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user",
                         "content": prompt if isinstance(prompt, str)
                         else str(prompt)})
        # 设置自动匹配（2026-10-01）：max_tokens 超模型单次输出上限时先夹回
        # 再发（端点 400 兜底仍有减半自愈，这里能把失败消在发送前）。
        # v2：显式传入的 model= 也要过一遍「厂商↔模型」「端点↔模型」匹配——
        # 此前只有 __init__ 做这件事，校准/评审等显式传模型的调用会把不匹配
        # 的模型直接发出，撞 404 后才走「换按量端点」的弯路（套餐 Key 下必 401）。
        _m = model or self.model
        for _matcher in (match_provider_model, match_volces_plan_model):
            _m2, _mn = _matcher(self.url, _m)
            if _mn:
                logger.warning("AI 自动匹配（调用级）：%s", _mn)
                _m = _m2
                if _mn not in self.auto_notes:
                    self.auto_notes.append(_mn)
        _want = int(max_tokens or self.max_tokens)
        _caps = model_caps(_m)
        if _caps and _want > _caps["out"]:
            logger.info("max_tokens %d 超模型「%s」输出上限，自动降为 %d",
                        _want, _m, _caps["out"])
            _want = _caps["out"]
        body: dict = {
            "model": _m,
            "max_tokens": _want,
            "messages": messages,
        }
        if thinking is False:
            body["thinking"] = {"type": "disabled"}
            body["reasoning_effort"] = "none"
        elif thinking is True or reasoning_effort:
            effort = str(reasoning_effort or "").strip().lower()
            if effort and effort != "none":
                body["reasoning_effort"] = effort
        try:
            resp = self._post_openai(self.url, body)
        except AIClientError as e:
            low = str(e).lower()
            if ("reasoning_effort" in body or "thinking" in body) \
                    and any(k in low for k in
                            ("reasoning_effort", "thinking", "unrecognized",
                             "unknown", "not supported", "unsupported",
                             "extra fields", "invalid parameter",
                             "invalid argument", "字段", "参数")):
                # 端点不支持思考控制参数：去掉后重试一次（保持旧行为可用）
                logger.info("接口拒绝思考控制参数（%s），去掉后重试",
                            str(e)[:120])
                body.pop("thinking", None)
                body.pop("reasoning_effort", None)
                try:
                    resp = self._post_openai(self.url, body)
                except AIClientError as e2:
                    if not _is_max_tokens_over(e2):
                        raise
                    body["max_tokens"], resp = self._shrink_max_tokens(
                        body, str(e2))
            else:
                if not _is_max_tokens_over(e):
                    raise
                body["max_tokens"], resp = self._shrink_max_tokens(
                    body, str(e))
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
                    "请改用非推理模型（如 deepseek-flash / glm-4.7-flash）"
                    "或在设置页把「思考」关掉、加大「单次最大输出 token」")
            if reason == "length":
                raise AIClientError("输出被 max_tokens 截断，请加大输出预算")
        return content

    # ---- 对话 ------------------------------------------------------------
    def chat(self, content, *, system: str | None = None,
             max_tokens: int | None = None, model: str | None = None,
             on_reasoning=None, thinking: bool | None = None,
             reasoning_effort: str | None = None) -> str:
        """文本对话（OpenAI 兼容 /chat/completions）。返回模型回复文本。"""
        return self.chat_openai(content, system=system,
                                max_tokens=max_tokens, model=model,
                                on_reasoning=on_reasoning,
                                thinking=thinking,
                                reasoning_effort=reasoning_effort)

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


# ---- v1.16.1：Agent 集群（多智能体协作）成员 -------------------------------
CLUSTER_ROLES = ("calibrate", "review")


def cluster_members(cfg: dict | None = None, role: str | None = None) -> list:
    """取归一化后的集群成员列表（可选按 role 过滤）。

    成员形如 {name, base_url, api_key, model, role}；role 缺省/非法一律按
    "calibrate"。空字段保留为空串，由 member_client 回落到全局配置。
    """
    c = dict(cfg or load_config())
    raw = c.get("calib_cluster_members")
    if isinstance(raw, str):                 # 容错：界面可能存成整段文本
        raw = parse_cluster_text(raw)
    out = []
    for m in (raw or []):
        if not isinstance(m, dict):
            continue
        r = str(m.get("role") or "calibrate").strip().lower()
        if r not in CLUSTER_ROLES:
            r = "calibrate"
        if role and r != role:
            continue
        out.append({
            "name": str(m.get("name") or "").strip() or r,
            "base_url": str(m.get("base_url") or "").strip(),
            "api_key": str(m.get("api_key") or "").strip(),
            "model": str(m.get("model") or "").strip(),
            "role": r,
        })
    return out


def parse_cluster_text(text: str) -> list:
    """把「角色|名称|base_url|api_key|模型」多行文本解析成成员列表（界面输入用）。

    角色缺省/非法时按 calibrate；允许整行只给 base_url（自动补角色）。
    """
    out = []
    for ln in str(text or "").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        parts = [p.strip() for p in ln.split("|")]
        parts += [""] * (5 - len(parts))
        role = parts[0].lower()
        if role not in CLUSTER_ROLES:
            # 允许省略角色（首列直接给 base_url）
            parts = ["calibrate", ""] + parts[:3]
            role = "calibrate"
        out.append({"role": role, "name": parts[1], "base_url": parts[2],
                    "api_key": parts[3], "model": parts[4]})
    return out


def member_client(member: dict, cfg: dict | None = None) -> "AIClient":
    """按集群成员构造独立 AIClient（覆盖 base_url / api_key / model）。

    未填字段回落全局配置，因此成员可以只覆盖「模型」或只覆盖「密钥」。
    """
    base = dict(cfg or load_config())
    m = dict(member or {})
    for k in ("base_url", "api_key", "model"):
        v = str(m.get(k) or "").strip()
        if v:
            base[k] = v
    return AIClient(base)


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
    guard = asr_model_hard_guard(ac["model"])
    if not guard:
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
    elif proto == "dashscope_native":
        # 百炼原生端点专用模型（Qwen-Audio-3.0-ASR-Flash 等）：**不能**用
        # /models 核对模型（该实例列表不列 ASR 模型），也不该拿正弦波试（无
        # 语音音频会被服务端 400 拒，误报「收不了音频」）——用官方示例音频
        # 实打实跑一次识别。
        verdict, note = _asr_native_probe(ac["base_url"], ac["api_key"],
                                          ac["model"])
        if verdict is True:
            return True, ("百炼原生（multimodal-generation，%s）；模型 %s 实测"
                          "识别通过：%s" % (_asr_native_url(ac["base_url"]),
                                          ac["model"],
                                          (note or "(无文本)")[:60]))
        if verdict == "missing":
            return False, ("模型「%s」在该实例/账号上不存在（%s）。请到百炼"
                           "控制台确认实例是否部署了该录音文件识别模型，"
                           "或改用公共百炼 dashscope.aliyuncs.com 的按量端点 + "
                           "普通百炼 API Key。" % (ac["model"], note or "404"))
        if verdict is False:
            return False, ("接口连通（百炼原生端点），但模型「%s」探测识别被"
                           "拒：%s。请确认密钥属于该实例、模型名与官方一致，"
                           "且账号已开通该模型。" % (ac["model"], note))
        return True, ("百炼原生端点已连通（%s）；模型 %s 的主动探测未完成"
                      "（%s），实际可用性以转录结果为准"
                      % (_asr_native_url(ac["base_url"]), ac["model"], note))
    elif proto == "dashscope_filetrans":
        # Filetrans 模型也不进 /models 列表（与原生端点同理，记忆结论：
        # 专属实例连部署的 qwen-audio 都不列），按 /models 核对必假阴性；
        # 且它没有只读探测端点——轻校验模型名，真伪留给转录那一步。
        m = str(ac["model"] or "").strip()
        if not m:
            return False, ("Filetrans 需要模型名（如 qwen3-asr-flash-filetrans、"
                           "qwen-audio-3.0-asr-flash-filetrans；填同步模型名"
                           "程序会自动补 -filetrans 后缀）")
        return True, ("百炼 Filetrans（异步提交 → 轮询）：密钥已填、模型 %s；"
                      "该服务无只读探测端点，实际可用性以转录结果为准。注意："
                      "转录时会先把音频传到百炼临时存储（官方标注勿用于生产"
                      "环境），说话人分离仅支持单声道、建议 ≤ 2 小时" % m)
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
        with urlopen_endpoint(req, 15) as resp:
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
        listing = "%s%s" % (sample, " 等 %d 个" % len(names)
                            if len(names) > 8 else "")
        if _is_maas_base(ac["base_url"]):
            # v1.15.6 实测（token-plan 专属实例）：专属实例的 /models **不列
            # ASR 模型**——名单里没有 ≠ 没部署，列表核对对这类端点不可信。
            # 这里不再按列表下「不可用」的结论（曾误报「实例没有可用的录音
            # 文件识别模型」）。模型确实不存在时，转录会给出服务端的明确报错
            # （404 model not exist）；原生端点专用模型另有主动探测分支。
            return True, ("接口连通（协议 %s）；模型 %s 不在该实例的 /models "
                          "列表里（实例可见：%s）。注意：maas 专属实例的 "
                          "/models 不列 ASR 模型（Qwen-Audio-3.0-ASR-Flash 这类"
                          "实测也不在列表），列表核对不可信 —— 若控制台确认"
                          "实例已部署该模型，直接保存并转录即可，以转录结果为"
                          "准。" % (proto_note, ac["model"], listing))
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
