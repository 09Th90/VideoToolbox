# -*- coding: utf-8 -*-
"""
全局 AI 客户端（智谱 GLM · 双端点）。

工具箱内所有 AI 能力（投稿页屏幕识别、字幕/标题语言识别等）统一走本模块：
- 仅依赖 Python 标准库（urllib），GUI 主程序与投稿引擎共用同一份代码；
- 配置持久化在 data\\ai_config.json，首次调用自动生成默认配置，
  换 Key / 换模型直接改该文件即可，无需改代码；
- 文本通道：Anthropic Messages 兼容接口（/v1/messages），默认模型 glm-4.7-flash；
- 视觉通道：实测智谱 Anthropic 兼容端点会静默丢弃图片（模型只会幻觉），
  因此屏幕识别走同一账号的 GLM 视觉接口（/api/paas/v4/chat/completions），
  默认视觉模型 glm-4.6v-flash；vision_base_url 留空时按 base_url 自动推导；
  vision_fallback_model 非空时，主视觉模型被限流/拥堵（1305/429）自动降级重试；
- chat_text：纯文本对话；chat_vision：图片 + 文本（屏幕识别用）；
- detect_language：标题/文本语言识别（字幕语言跟随标题语言用）；
- 回复中的 thinking 块自动跳过，只拼接 text 块；JSON 回复用 try_parse_json 解析；
- 智谱“1305 访问量过大 / overloaded”与 HTTP 429/5xx 自动退避重试。
"""

from __future__ import annotations

import base64
import json
import logging
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 配置（默认值 = 出厂内置；data/ai_config.json 可覆盖）
# ---------------------------------------------------------------------------
# ai_client.py 位于 <程序目录>/tools/uploader_src/modules/ 下，
# parents[3] 即程序目录（打包后为 exe 同级，源码模式为仓库根）。
if getattr(sys, "frozen", False):
    _APP_DIR = Path(sys.executable).resolve().parent
else:
    _APP_DIR = Path(__file__).resolve().parents[3]
DATA_DIR = _APP_DIR / "data"
CONFIG_PATH = DATA_DIR / "ai_config.json"

DEFAULT_CONFIG: dict = {
    "enabled": True,
    # 文本通道（Anthropic Messages 兼容）
    "base_url": "https://open.bigmodel.cn/api/anthropic",
    "api_key": "a962f094b8c741c9afae51fd09c99e1b.SIxG2jxt0tKvCXWK",
    "model": "glm-4.7-flash",
    # 视觉通道（GLM 视觉接口；留空 = 按 base_url 自动推导）
    "vision_base_url": "",
    "vision_model": "glm-4.6v-flash",
    # 主视觉模型限流/拥堵时自动降级到此模型（空 = 不降级）
    "vision_fallback_model": "",
    "max_tokens": 2048,
    "timeout": 90,
    "retries": 3,
}


def load_config() -> dict:
    """读取 AI 配置；文件不存在时用默认值落盘一份，方便用户直接修改。"""
    cfg = dict(DEFAULT_CONFIG)
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
        if isinstance(raw, dict):
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


def _derive_vision_base(base_url: str) -> str:
    """按文本通道 base_url 推导智谱视觉接口地址。"""
    base = (base_url or "").lower()
    if "api.z.ai" in base:
        return "https://api.z.ai/api/paas/v4"
    # 默认智谱国内站
    return "https://open.bigmodel.cn/api/paas/v4"


def _is_retryable(status: int | None, detail: str) -> bool:
    """智谱 1305（访问量过大）/ overloaded / 429 / 5xx 可退避重试。"""
    if status is None:                      # 网络错误
        return True
    if status == 429 or status >= 500:
        return True
    d = (detail or "").lower()
    return "1305" in d or "overloaded" in d or "稍后再试" in d


class AIClient:
    """智谱 GLM 双端点最小客户端（无第三方依赖）。

    - chat / chat_text：Anthropic Messages 兼容端点（glm-4.7-flash）；
    - chat_vision：GLM 视觉端点（glm-4.6v-flash，OpenAI chat/completions 格式）。
    """

    def __init__(self, config: dict | None = None) -> None:
        self.cfg = config or load_config()
        base = str(self.cfg.get("base_url", "")).rstrip("/")
        # 允许用户直接填到 /v1/messages 或只填到域名
        if not base.endswith("/v1/messages"):
            if base.endswith("/v1"):
                base += "/messages"
            else:
                base += "/v1/messages"
        self.url = base
        vbase = str(self.cfg.get("vision_base_url") or "").rstrip("/")
        if not vbase:
            vbase = _derive_vision_base(base)
        if not vbase.endswith("/chat/completions"):
            vbase += "/chat/completions"
        self.vision_url = vbase
        self.model = str(self.cfg.get("model") or DEFAULT_CONFIG["model"])
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

    def _post_anthropic(self, body: dict) -> dict:
        headers = {
            "x-api-key": str(self.cfg.get("api_key") or ""),
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        resp = self._request(self.url, headers, body)
        if isinstance(resp, dict) and resp.get("type") == "error":
            err = resp.get("error") or {}
            raise AIClientError(
                f"{err.get('type', 'error')}: {err.get('message', resp)}")
        return resp

    def _post_paas(self, body: dict) -> dict:
        headers = {
            "Authorization": "Bearer " + str(self.cfg.get("api_key") or ""),
            "content-type": "application/json",
        }
        resp = self._request(self.vision_url, headers, body)
        if isinstance(resp, dict) and resp.get("error"):
            err = resp["error"]
            raise AIClientError(
                f"{err.get('code', 'error')}: {err.get('message', err)}")
        return resp

    # ---- 对话 ------------------------------------------------------------
    def chat(self, content, *, system: str | None = None,
             max_tokens: int | None = None, model: str | None = None) -> str:
        """文本通道（Anthropic Messages）：发送一条 user 消息，返回 text 块拼接。

        :param content: 字符串（纯文本）或 Anthropic content 块列表
        """
        body: dict = {
            "model": model or self.model,
            "max_tokens": int(max_tokens or self.max_tokens),
            "messages": [{"role": "user", "content": content}],
        }
        if system:
            body["system"] = system
        resp = self._post_anthropic(body)
        parts: list[str] = []
        for blk in resp.get("content") or []:
            if isinstance(blk, dict) and blk.get("type") == "text":
                parts.append(str(blk.get("text") or ""))
        return "\n".join(parts).strip()

    def chat_text(self, prompt: str, **kw) -> str:
        return self.chat(prompt, **kw)

    def chat_vision(self, prompt: str, images, **kw) -> str:
        """视觉通道（GLM 视觉接口）：图片 + 文本提问（屏幕识别用）。

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
        try:
            resp = self._post_paas(body)
        except AIClientError as e:
            # 主视觉模型拥堵/限流（1305/429/overloaded）时自动降级到备用模型
            msg = str(e)
            congested = any(k in msg for k in ("1305", "1302", "429", "overloaded"))
            if congested and self.vision_fallback_model \
                    and self.vision_fallback_model != body["model"]:
                logger.warning("视觉模型 %s 拥堵（%s），降级到 %s 重试",
                               body["model"], msg[:80], self.vision_fallback_model)
                body["model"] = self.vision_fallback_model
                resp = self._post_paas(body)
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
_client: AIClient | None = None


def get_client() -> AIClient:
    global _client
    if _client is None:
        _client = AIClient()
    return _client


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


def quick_test() -> tuple[bool, str]:
    """连通性自检：返回 (是否成功, 回复/错误信息)。同时报告视觉通道配置。"""
    try:
        client = get_client()
        reply = client.chat_text("收到请只回复两个字：正常", max_tokens=512)
        return True, (reply or "(空回复)") + \
            f"（文本模型 {client.model}；视觉模型 {client.vision_model}）"
    except Exception as e:  # noqa: BLE001
        return False, str(e)
