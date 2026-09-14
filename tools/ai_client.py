# -*- coding: utf-8 -*-
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
    "api_key": "a962f094b8c741c9afae51fd09c99e1b.SIxG2jxt0tKvCXWK",
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
    "asr_local_model": "large-v3",
    "asr_local_model_dir": "",
    # ---- AI 校准（Agent 级字幕校准）----
    # v1.12.0：原 calib_channel（接口 A/B 选择）随双通道合并一并废弃
    "calib_chunk_cues": 120,   # 每块最多 cue 条数
    "calib_max_chars": 6000,   # 每块字符预算（超出自动再拆）
    "calib_max_tokens": 8192,  # 单次调用的最大输出
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


def _models_url(base: str) -> str:
    """OpenAI 兼容模型列表地址（用于 ASR 服务连通性测试）。"""
    b = (base or "").rstrip("/")
    tail = b.rsplit("/", 1)[-1].lower()
    if tail.startswith("v") and tail[1:2].isdigit():
        return b + "/models"
    return b + "/v1/models"


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

    service = 自有 ASR 服务（OpenAI 兼容 /audio/transcriptions）；
    local   = 本地独立 faster-whisper 模型（模型名 + 模型目录可自定义）。
    """
    c = dict(cfg or load_config())
    mode = str(c.get("asr_mode") or "service").strip().lower()
    if mode not in ("service", "local"):
        mode = "service"
    return {
        "mode": mode,
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
                    model: str | None = None) -> str:
        """OpenAI 兼容文本对话。返回首个 choice 的文本。"""
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
            content = resp["choices"][0]["message"].get("content")
        except (KeyError, IndexError, TypeError):
            raise AIClientError(
                f"OpenAI 兼容接口返回结构异常: {str(resp)[:200]}")
        if isinstance(content, list):      # 部分模型返回块列表
            content = "\n".join(
                str(b.get("text") or "") for b in content
                if isinstance(b, dict) and b.get("type") == "text")
        return str(content or "").strip()

    # ---- 对话 ------------------------------------------------------------
    def chat(self, content, *, system: str | None = None,
             max_tokens: int | None = None, model: str | None = None) -> str:
        """文本对话（OpenAI 兼容 /chat/completions）。返回模型回复文本。"""
        return self.chat_openai(content, system=system,
                                max_tokens=max_tokens, model=model)

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

    service 模式：GET {base}/models（OpenAI 兼容端点通用）验证地址与密钥；
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
    url = _models_url(ac["base_url"])
    req = urllib.request.Request(
        url, headers={"Authorization": "Bearer " + ac["api_key"],
                      "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:200]
        except Exception:  # noqa: BLE001
            pass
        return False, f"HTTP {e.code}: {detail or e.reason}"
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return False, f"网络错误: {e}"
    n = raw.count('"id"')
    return True, (f"接口连通（{url}）；模型 {ac['model'] or '未填'}"
                  + (f"，服务端可见 {n} 个模型" if n else ""))
