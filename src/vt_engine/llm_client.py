# @version 2.5.4
"""LLM 客户端（自研，替代 videocaptioner.core.llm.client 的公开面）。

单通道原则（v1.12.0 起全项目一致）：一套 base_url / api_key / model，
权威配置在 ``data/ai_config.json``（``tools/ai_client.py`` 读取）；引擎
settings.json 的 LLM 分组只是该配置的**持久化镜像**（主程序
``apply_global_llm_to_engine`` 负责同步）。因此本模块：

* 配置解析优先走 ``tools/ai_client.load_config()``（单一事实来源），
  取不到时回落自研 cfg 的 OpenAI 兼容槽（按 llm_service 选分组）；
* 传输**优先复用 ai_client.AIClient**（自带重试/退避、模型能力钳制、
  端点↔模型自动匹配、请求日志），避免第二套 LLM 传输逻辑漂移；
* ai_client 不可导入时（裁剪环境）退到自带零依赖 urllib 传输——
  OpenAI 兼容 ``/chat/completions``，语义不变。

缓存
----
引擎的 LLM memoize 直接落在共享 llm 缓存目录、键无前缀——若自研实现
沿用同键，会把**字符串结果**写进引擎期望 response 对象的槽位，
引擎读到 ``str`` 后 ``hasattr(choices)`` 失败当错误处理。故自研侧键
一律加 ``vt_engine:`` 前缀，物理同目录、逻辑不相撞。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import List, Optional, Tuple

from vt_engine.constants import LLM_CACHE_EXPIRE
from vt_engine.log import setup_logger

logger = setup_logger("vt_engine.llm")

__all__ = [
    "LLMError",
    "resolve_llm_settings",
    "ai_enabled",
    "get_ai_client",
    "reset_client",
    "chat",
    "chat_text",
    "check_llm_connection",
    "get_available_models",
]

#: 自研 LLM 缓存键前缀（避免与引擎 memoize 键相撞，见模块 docstring）。
_CACHE_KEY_PREFIX = "vt_engine:llm:"

_client = None          # type: Optional[object]
_client_cfg_tag = ""    # 配置指纹：变化即重建客户端


class LLMError(RuntimeError):
    """LLM 调用失败（未配置 / 网络 / 鉴权 / 结构异常）。"""


# --------------------------------------------------------------------------
# 配置解析（ai_config.json 权威，cfg 槽位兜底）
# --------------------------------------------------------------------------
def _import_ai_client_module():
    """惰性导入 tools/ai_client.py（tools 目录上 sys.path）。"""
    try:
        import ai_client  # noqa: PLC0411
        return ai_client
    except Exception:
        pass
    try:
        from vt_engine.paths import default_engine_paths
        # EnginePaths.bin_path 即随包 tools 目录（ai_client.py 所在）
        tools = str(default_engine_paths().bin_path)
    except Exception:  # noqa: BLE001
        return None
    import sys
    if tools not in sys.path:
        sys.path.insert(0, tools)
    try:
        import ai_client  # noqa: PLC0411
        return ai_client
    except Exception:
        return None


def resolve_llm_settings() -> dict:
    """解析当前 LLM 单通道配置。

    返回 ``{enabled, base_url, api_key, model}``。``enabled=False`` 表示
    用户关闭了 AI 或没配密钥——调用方应给出明确指引，而不是拿着空密钥
    去撞 401。
    """
    mod = _import_ai_client_module()
    if mod is not None:
        try:
            cfg = mod.load_config()
            key = str(cfg.get("api_key") or "").strip()
            return {
                "enabled": bool(cfg.get("enabled", True)) and bool(key),
                "base_url": str(cfg.get("base_url") or "").strip(),
                "api_key": key,
                "model": str(cfg.get("model") or "").strip(),
            }
        except Exception as e:  # noqa: BLE001
            logger.warning("读取 ai_config 失败，回落引擎槽位: %s", e)
    return _settings_from_cfg()


def _settings_from_cfg() -> dict:
    """从自研 cfg 的 LLM 分组解析（按 llm_service 选分组，同 TaskFactory）。"""
    from vt_engine.config import cfg
    from vt_engine.entities import LLMServiceEnum
    slots = {
        LLMServiceEnum.OPENAI: ("openai_api_base", "openai_api_key",
                                "openai_model"),
        LLMServiceEnum.SILICON_CLOUD: ("silicon_cloud_api_base",
                                       "silicon_cloud_api_key",
                                       "silicon_cloud_model"),
        LLMServiceEnum.DEEPSEEK: ("deepseek_api_base", "deepseek_api_key",
                                  "deepseek_model"),
        LLMServiceEnum.OLLAMA: ("ollama_api_base", "ollama_api_key",
                                "ollama_model"),
        LLMServiceEnum.LM_STUDIO: ("lm_studio_api_base", "lm_studio_api_key",
                                   "lm_studio_model"),
        LLMServiceEnum.GEMINI: ("gemini_api_base", "gemini_api_key",
                                "gemini_model"),
        LLMServiceEnum.CHATGLM: ("chatglm_api_base", "chatglm_api_key",
                                 "chatglm_model"),
    }
    base_a, key_a, model_a = slots.get(
        cfg.llm_service.value, slots[LLMServiceEnum.OPENAI])
    key = str(getattr(cfg, key_a).value or "").strip()
    return {
        "enabled": bool(key),
        "base_url": str(getattr(cfg, base_a).value or "").strip(),
        "api_key": key,
        "model": str(getattr(cfg, model_a).value or "").strip(),
    }


def ai_enabled() -> bool:
    """AI 是否可用（启用开关 + 密钥非空）。"""
    return bool(resolve_llm_settings()["enabled"])


def get_ai_client():
    """取（缓存的）``ai_client.AIClient`` 实例；不可用抛 :class:`LLMError`。"""
    global _client, _client_cfg_tag
    s = resolve_llm_settings()
    if not s["enabled"]:
        raise LLMError("AI 未配置或已关闭：请在「设置」中填写 API 地址/密钥/模型")
    tag = "%s|%s|%s" % (s["base_url"], s["model"],
                        (s["api_key"] or "")[:8])
    if _client is not None and _client_cfg_tag == tag:
        return _client
    mod = _import_ai_client_module()
    if mod is None:
        raise LLMError("ai_client 模块不可用（tools 目录缺失？）")
    try:
        _client = mod.AIClient()
    except Exception as e:  # noqa: BLE001
        raise LLMError("AI 客户端初始化失败: %s" % e) from e
    _client_cfg_tag = tag
    return _client


def reset_client() -> None:
    """配置变更后重建客户端（下次调用自动 lazily 重建）。"""
    global _client, _client_cfg_tag
    _client = None
    _client_cfg_tag = ""


# --------------------------------------------------------------------------
# 零依赖兜底传输（ai_client 缺失时）
# --------------------------------------------------------------------------
def _chat_url(base_url: str) -> str:
    u = (base_url or "").strip().rstrip("/")
    if not u:
        raise LLMError("LLM base_url 为空")
    if u.endswith("/chat/completions"):
        return u
    if not u.endswith("/v1") and "/v1/" not in (u + "/") \
            and "/chat/completions" not in u:
        u += "/v1"
    return u + "/chat/completions"


def _post_chat(url: str, api_key: str, body: dict,
               timeout: float = 120.0) -> dict:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer %s" % api_key)
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:300]
        except Exception:  # noqa: BLE001
            pass
        raise LLMError("LLM 服务返回 HTTP %s：%s" % (e.code, detail))
    except urllib.error.URLError as e:
        raise LLMError("LLM 服务不可达：%s" % e.reason)


def _extract_text(resp: dict) -> str:
    """OpenAI 兼容响应 → 文本（跳过 thinking 块，只拼 text）。"""
    try:
        msg = resp["choices"][0]["message"]
    except (KeyError, IndexError, TypeError):
        raise LLMError("LLM 响应结构异常: %s" % str(resp)[:200])
    content = msg.get("content")
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict):
                if b.get("type") in (None, "text") and b.get("text"):
                    parts.append(str(b["text"]))
            else:
                parts.append(str(b))
        return "".join(parts).strip()
    return str(content or "").strip()


# --------------------------------------------------------------------------
# 对外：对话
# --------------------------------------------------------------------------
def _llm_cache():
    """llm 缓存（惰性建库；diskcache 缺失时降级内存缓存）。"""
    from vt_engine.cache import default_cache_hub
    from vt_engine.cache import generate_cache_key
    return default_cache_hub().get("llm"), generate_cache_key


def chat(prompt: str, system: str = "", model: str = "",
         max_tokens: Optional[int] = None,
         use_cache: bool = True) -> str:
    """单轮对话，返回助手文本。失败抛 :class:`LLMError`（绝不返回空串）。"""
    s = resolve_llm_settings()
    if not s["enabled"]:
        raise LLMError("AI 未配置或已关闭：请在「设置」中填写 API 地址/密钥/模型")
    use_model = model or s["model"]
    if not use_model:
        raise LLMError("未配置 LLM 模型名")

    if use_cache:
        cache, gen_key = _llm_cache()
        key = _CACHE_KEY_PREFIX + gen_key(
            (prompt, system, use_model, max_tokens))
        try:
            hit = cache.get(key, default=None)
        except Exception:  # noqa: BLE001
            hit = None
        if isinstance(hit, str) and hit:
            return hit

    text = _chat_once(prompt, system, use_model, max_tokens)
    if not text:
        raise LLMError("LLM 返回空内容")
    if use_cache:
        try:
            cache.set(key, text, expire=LLM_CACHE_EXPIRE)
        except Exception:  # noqa: BLE001  缓存失败不影响主流程
            pass
    return text


def _chat_once(prompt: str, system: str, model: str,
               max_tokens: Optional[int]) -> str:
    """真实发一次请求（ai_client 优先，urllib 兜底）。"""
    mod = _import_ai_client_module()
    if mod is not None:
        try:
            client = get_ai_client()
            kw = {}
            if max_tokens:
                kw["max_tokens"] = int(max_tokens)
            return str(client.chat(prompt, system=system or None,
                                   model=model or None, **kw)).strip()
        except LLMError:
            raise
        except Exception as e:  # noqa: BLE001
            raise LLMError("LLM 调用失败: %s" % e) from e
    # —— 兜底传输 ——
    s = resolve_llm_settings()
    body = {
        "model": model,
        "messages": ([{"role": "system", "content": system}]
                     if system else []) +
                    [{"role": "user", "content": prompt}],
    }
    if max_tokens:
        body["max_tokens"] = int(max_tokens)
    return _extract_text(_post_chat(_chat_url(s["base_url"]),
                                    s["api_key"], body))


def chat_text(prompt: str, **kw) -> str:
    """:func:`chat` 的别名（ai_client 风格调用面）。"""
    return chat(prompt, **kw)


# --------------------------------------------------------------------------
# 连通性检查（设置页「测试连接」用）
# --------------------------------------------------------------------------
def check_llm_connection(base_url: str = "", api_key: str = "",
                         model: str = "") -> Tuple[bool, str]:
    """测试 LLM 连接：发一句 'Just respond with "Hello"!'。

    返回 ``(是否成功, 说明)``——说明成功时是模型回复、失败时是原因。
    """
    s = resolve_llm_settings()
    base = (base_url or s["base_url"]).strip()
    key = (api_key or s["api_key"]).strip()
    mdl = (model or s["model"]).strip()
    if not base or not key or not mdl:
        return False, "API 地址 / 密钥 / 模型 不完整，请先配置"
    try:
        resp = _post_chat(_chat_url(base), key, {
            "model": mdl,
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": 'Just respond with "Hello"!'},
            ],
            "max_tokens": 16,
        }, timeout=60.0)
        text = _extract_text(resp)
        return (True, text or "ok")
    except LLMError as e:
        return False, str(e)


_WEIGHT_HINTS = (
    ("gpt-4o", 90), ("gpt-4.1", 89), ("claude", 88), ("gpt-4", 85),
    ("deepseek-v3", 84), ("deepseek-chat", 83), ("deepseek", 80),
    ("qwen-max", 79), ("qwen-plus", 78), ("qwen", 75), ("glm-4", 74),
    ("kimi", 73), ("moonshot", 72), ("gemini", 70), ("llama", 60),
    ("mistral", 55), ("whisper", 10), ("tts", 5), ("embedding", 3),
)


def get_available_models(base_url: str = "",
                         api_key: str = "") -> List[str]:
    """拉取端点模型列表（GET {base}/models），按「聊天模型优先」排序。

    纯信息展示用途；失败返回空列表（调用方提示手动填模型名）。
    """
    s = resolve_llm_settings()
    base = (base_url or s["base_url"]).strip().rstrip("/")
    key = (api_key or s["api_key"]).strip()
    if not base or not key:
        return []
    url = base if base.endswith("/models") else base + "/models"
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", "Bearer %s" % key)
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:  # noqa: BLE001
        logger.warning("获取模型列表失败: %s", e)
        return []
    names = [m.get("id") for m in (data.get("data") or [])
             if isinstance(m, dict) and m.get("id")]
    if not names:
        return []

    def _weight(name: str) -> int:
        low = name.lower()
        for hint, w in _WEIGHT_HINTS:
            if hint in low:
                return w
        return 50

    return sorted(names, key=lambda n: (-_weight(n), n))
