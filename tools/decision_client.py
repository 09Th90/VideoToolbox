# -*- coding: utf-8 -*-
# @version 3.3.0
"""阿里云百炼 System One / Jev 结构化决策客户端。

官方协议：POST /compatible-mode/v1/systemone，模型 decision-model-preview。
https://help.aliyun.com/zh/model-studio/decision-model-api

激活门控（有意保持严格，顺序即诊断顺序）：
  * decision_enabled=True（出厂 False ⇒ 生产链路默认门禁关闭、零请求；
    配置缺该键时按旧口径视为开，兼容直接构造与既有自测）；
  * 全局 AI 启用，decision_mode=shadow（off=关闭；assist/auto 为 R1+ 预留）；
  * 凭据：优先独立 decision_api_key（只存 data/credentials.json，来源标记
    credential_source="decision"）；R0 影子允许回落全局 api_key（标记
    "global_fallback"，进审计）；decision_require_own_key=True 时强制独立
    key，缺失即 missing_decision_key 不可用（R1 语义，本任务仅预留开关）；
  * 端点：取 decision_base_url（留空回落全局 base_url，记
    endpoint_fallback_global），主机必须逐字命中 DECISION_ENDPOINT_WHITELIST；
  * 区域绑定：decision_key_region 声明（如有）必须等于端点区域，否则
    region_mismatch；R0 只实放行北京端点（实测），新加坡为预留
    （endpoint_region_untested，实测通过并核对区域口径后再放行）。

普通百炼按量、工作空间专属域名、火山方舟 Token Plan 和其他 OpenAI 兼容端点
均不激活。当前只支持 shadow/off，不提供自动改写权限。

R0 影子补强（2026-11-22 WP3 part 1）：
  * 请求缓存 data/cache/decision/：键 = sha256(schema_version+model+canonical
    state+questions)，TTL 7 天，**仅 shadow 模式**启用（影子证据可复用，业务
    改写永不复用缓存）；缓存故障静默降级，绝不影响主流程；
  * 错误分类 network / auth / ratelimit / protocol（附在 DecisionError.category，
    供调用方降级审计），并计入聚合审计；
  * 聚合审计 audit_summary()：request_id 索引 → 批次/耗时/路由分布/错误分类
    计数。审计只含计数与分布，**绝不含 state 明文与任何凭据**。
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

MODEL = "decision-model-preview"
SCHEMA_VERSION = "vt.decision.v1"
DEFAULT_MODE = "shadow"
DEFAULT_TIMEOUT = 12.0
MAX_QUESTIONS = 16
TOKEN_PLAN_SUFFIX = ".maas.aliyuncs.com"

#: Jev 专属端点白名单（主机**逐字精确**匹配，不认子域/父域/关键词）。
#: 北京 = 实测可用；新加坡 = 预留（区域口径实测前不激活）。
DECISION_ENDPOINT_WHITELIST = (
    "token-plan.cn-beijing.maas.aliyuncs.com",
    "token-plan.ap-southeast-1.maas.aliyuncs.com",
)

#: R0 实际放行的端点子集：新加坡未实测（标记 endpoint_region_untested），
#: 实测通过并确认 opener 代理口径后再加入。
DECISION_ENDPOINT_ENABLED = ("token-plan.cn-beijing.maas.aliyuncs.com",)

#: 凭据来源标记（仅字符串标记；任何审计/状态副本不含明文 key）。
CREDENTIAL_SOURCE_DECISION = "decision"
CREDENTIAL_SOURCE_GLOBAL = "global_fallback"

#: 请求缓存：TTL 7 天，仅 shadow 模式（影子专用）。
CACHE_TTL_SECONDS = 7 * 24 * 3600


class DecisionError(RuntimeError):
    """网络、鉴权或协议错误；调用方应降级，不阻断主业务。

    ``category`` ∈ network/auth/ratelimit/protocol/unknown —— R0 错误分类，
    供降级审计（features 侧 except DecisionError 后可读 getattr(exc,
    "category", "unknown")）。分类只取类别字符串，不携带报文明文。
    """

    category = "unknown"

    def __init__(self, message, category="unknown"):
        super().__init__(message)
        if category:
            self.category = category


class DecisionUnavailable(DecisionError):
    """门控未满足；decide() 不会发出网络请求。"""


def _parts(base_url):
    raw = str(base_url or "").strip()
    if not raw:
        raise ValueError("接口地址为空")
    if "://" not in raw:
        raw = "https://" + raw
    parts = urllib.parse.urlparse(raw)
    if parts.scheme.lower() != "https" or not parts.hostname:
        raise ValueError("Jev 只接受 HTTPS 接口地址")
    return parts


def is_aliyun_token_plan(base_url):
    """兼容别名（宽松形态判据）：仅认百炼 Token Plan 专属域名。

    ⚠️ 激活门控请用 :func:`is_allowed_decision_endpoint`（白名单精确匹配）；
    本函数保留供设置页/旧调用方使用。
    """
    try:
        host = (_parts(base_url).hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    return host.startswith("token-plan.") and host.endswith(TOKEN_PLAN_SUFFIX)


def region_of(base_url):
    """从 Token Plan 专属域名提取区域段（cn-beijing / ap-southeast-1）。

    非白名单形态返回 ""。供区域绑定审计：decision_key_region 声明必须与
    端点区域一致，否则 availability 给 region_mismatch。
    """
    try:
        host = (_parts(base_url).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""
    if host.startswith("token-plan.") and host.endswith(TOKEN_PLAN_SUFFIX):
        return host[len("token-plan."):-len(TOKEN_PLAN_SUFFIX)]
    return ""


def is_allowed_decision_endpoint(base_url):
    """白名单精确判据：HTTPS + 主机逐字命中 DECISION_ENDPOINT_WHITELIST。

    比兼容别名 is_aliyun_token_plan 严格：token-plan.eu-central-1.* 这类
    未收录区域、子域伪装（evil.token-plan.cn-beijing.…）、后缀伪装
    （token-plan.cn-beijing.…evil.com）一律拒绝。
    """
    try:
        host = (_parts(base_url).hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    return host in DECISION_ENDPOINT_WHITELIST


def systemone_url(base_url):
    """把 Token Plan compatible-mode 基址规范化为 systemone URL。"""
    parts = _parts(base_url)
    if not is_aliyun_token_plan(base_url):
        raise ValueError("仅百炼 Token Plan 专属端点允许调用 Jev")
    path = parts.path.rstrip("/")
    if path.endswith("/chat/completions"):
        path = path[:-len("/chat/completions")]
    if path.endswith("/compatible-mode/v1/systemone"):
        final = path
    elif path.endswith("/compatible-mode/v1"):
        final = path + "/systemone"
    elif path.endswith("/compatible-mode"):
        final = path + "/v1/systemone"
    elif not path:
        final = "/compatible-mode/v1/systemone"
    else:
        raise ValueError("Token Plan 地址须位于 /compatible-mode/v1")
    return urllib.parse.urlunparse(("https", parts.netloc, final, "", "", ""))


def _flag(value, default=True):
    """开关值归一：None 用 default（decision_enabled 缺省 = 旧口径视为开）。"""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _credential_source(cfg):
    """凭据来源标记：显式标记优先（加载缝注入），否则按配置字段推断。

    decision        = 独立 decision_api_key（只存 credentials.json）；
    global_fallback = R0 影子回落复用全局 api_key（进审计）。
    """
    explicit = str(cfg.get("credential_source") or "").strip().lower()
    if explicit:
        return explicit
    if str(cfg.get("decision_api_key") or "").strip():
        return CREDENTIAL_SOURCE_DECISION
    return CREDENTIAL_SOURCE_GLOBAL


def availability(config):
    """返回可序列化门控状态；纯本地计算，不发请求、不含任何明文凭据。

    门控顺序（即诊断顺序）：decision_disabled → global_ai_disabled →
    mode_off → unsupported_mode → missing_decision_key/missing_api_key →
    unsupported_endpoint → region_mismatch → endpoint_region_untested →
    invalid_endpoint。输出额外带 credential_source / endpoint_region /
    endpoint_fallback_global / region_declared 审计字段。
    """
    cfg = dict(config or {})
    mode = str(cfg.get("decision_mode") or DEFAULT_MODE).strip().lower()
    model = str(cfg.get("decision_model") or "").strip() or MODEL
    enabled = _flag(cfg.get("decision_enabled"), True)
    source = _credential_source(cfg)
    declared_region = str(cfg.get("decision_key_region") or "").strip().lower()
    status = {"active": False, "mode": mode, "model": model,
              "schema_version": SCHEMA_VERSION, "endpoint": "",
              "reason": "", "detail": "",
              "decision_enabled": enabled,
              "credential_source": source,
              "region_declared": declared_region,
              "endpoint_region": "", "endpoint_fallback_global": False}
    if not enabled:
        status["reason"] = "decision_disabled"
        return status
    if not bool(cfg.get("enabled", True)):
        status["reason"] = "global_ai_disabled"
        return status
    if mode == "off":
        status["reason"] = "mode_off"
        return status
    if mode != "shadow":
        status["reason"] = "unsupported_mode"
        return status
    if _flag(cfg.get("decision_require_own_key"), False) \
            and source != CREDENTIAL_SOURCE_DECISION:
        # R1 语义：强制独立 decision_api_key，缺失即不可用（不回落全局）。
        status["reason"] = "missing_decision_key"
        return status
    if not str(cfg.get("api_key") or "").strip():
        status["reason"] = "missing_api_key"
        return status
    own_base = str(cfg.get("decision_base_url") or "").strip()
    base = own_base or str(cfg.get("base_url") or "").strip()
    if not own_base:
        status["endpoint_fallback_global"] = True
    if not is_allowed_decision_endpoint(base):
        status["reason"] = "unsupported_endpoint"
        return status
    region = region_of(base)
    status["endpoint_region"] = region
    if declared_region and declared_region != region:
        status["reason"] = "region_mismatch"
        status["detail"] = ("decision_key_region=%s 与端点区域 %s 不一致"
                            % (declared_region, region or "(未知)"))
        return status
    try:
        host = (_parts(base).hostname or "").lower().rstrip(".")
    except ValueError as exc:
        status["reason"] = "invalid_endpoint"
        status["detail"] = str(exc)
        return status
    if host not in DECISION_ENDPOINT_ENABLED:
        # 白名单内但区域未实测（R0 只实放行北京；新加坡预留）。
        status["reason"] = "endpoint_region_untested"
        return status
    try:
        status["endpoint"] = systemone_url(base)
    except ValueError as exc:
        status["reason"] = "invalid_endpoint"
        status["detail"] = str(exc)
        return status
    status["active"] = True
    return status


# ---------------------------------------------------------------------------
# R0 补强：错误分类 + 聚合审计（只含计数/分布/耗时，不含 state 与凭据明文）
# ---------------------------------------------------------------------------
_ERROR_CATEGORY_PATTERNS = (
    ("ratelimit", ("429", "限流", "too many requests", "rate limit")),
    ("auth", ("http 401", "http 403", "鉴权", "unauthorized", "forbidden")),
    ("network", ("请求失败", "超时", "timed out", "timeout", "连接", "connection",
                 "网络", "dns", "ssl", "代理", "proxy", "name or service")),
    ("protocol", ("json", "协议", "校验", "非法", "缺少", "缺失", "越界",
                  "未归一化", "响应", "模型不匹配", "服务端错误", "state")),
)


def classify_error(exc):
    """把异常归类为 network/auth/ratelimit/protocol/unknown（降级审计用）。

    DecisionError.category 优先；HTTPError 按状态码；其余按报文特征词。
    DecisionUnavailable（门控）归为 gating——它从未发出网络请求。
    """
    if isinstance(exc, DecisionUnavailable):
        return "gating"
    category = str(getattr(exc, "category", "") or "").strip().lower()
    if category and category != "unknown":
        return category
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code in (401, 403):
            return "auth"
        if exc.code == 429:
            return "ratelimit"
        if exc.code >= 500:
            return "network"
        return "protocol"
    text = str(exc).lower()
    for name, keys in _ERROR_CATEGORY_PATTERNS:
        if any(k in text for k in keys):
            return name
    return "unknown"


_AUDIT_LOCK = threading.Lock()
_AUDIT: dict = {}


def audit_reset():
    """清空聚合审计（自测/长跑轮换用）。"""
    with _AUDIT_LOCK:
        _AUDIT.clear()


def _audit_record(request_id, *, cached=False, error_category="", questions=0,
                  choices=None, latency_ms=None):
    """聚合一条审计事件；request_id 为空时归入「(未索引)」（失败常无 id）。"""
    rid = str(request_id or "").strip() or "(未索引)"
    with _AUDIT_LOCK:
        rec = _AUDIT.setdefault(rid, {
            "requests": 0, "cache_hits": 0, "errors": {}, "questions": 0,
            "latency_ms_total": 0.0, "routes": {}})
        if cached:
            rec["cache_hits"] += 1
        elif error_category:
            rec["errors"][error_category] = \
                rec["errors"].get(error_category, 0) + 1
        else:
            rec["requests"] += 1
        try:
            rec["questions"] += int(questions or 0)
        except (TypeError, ValueError):
            pass
        if latency_ms is not None:
            try:
                rec["latency_ms_total"] += float(latency_ms)
            except (TypeError, ValueError):
                pass
        for choice in (choices or ()):
            rec["routes"][str(choice)] = \
                rec["routes"].get(str(choice), 0) + 1


def audit_summary():
    """聚合审计快照（R0 补强）：request_id 索引 → 批次/耗时/路由分布/错误分类。

    ``errors`` 按类别（network/auth/ratelimit/protocol）聚合；``routes`` 为
    answer choice（或答案类型）的全局分布。**不含 state 明文与凭据。**
    """
    with _AUDIT_LOCK:
        snapshot = {rid: {
            "requests": rec["requests"], "cache_hits": rec["cache_hits"],
            "errors": dict(rec["errors"]), "questions": rec["questions"],
            "latency_ms_total": round(rec["latency_ms_total"], 1),
            "routes": dict(rec["routes"])}
            for rid, rec in _AUDIT.items()}
    errors, routes = {}, {}
    calls = hits = questions = 0
    latency_total = 0.0
    for rec in snapshot.values():
        calls += rec["requests"]
        hits += rec["cache_hits"]
        questions += rec["questions"]
        latency_total += rec["latency_ms_total"]
        for cat, n in rec["errors"].items():
            errors[cat] = errors.get(cat, 0) + n
        for route, n in rec["routes"].items():
            routes[route] = routes.get(route, 0) + n
    return {"requests_indexed": len(snapshot), "calls": calls,
            "cache_hits": hits, "questions": questions,
            "latency_ms_total": round(latency_total, 1),
            "errors": errors, "routes": routes, "by_request": snapshot}


def _answer_routes(answers):
    """从 answers 提取路由分布键（choice 值或答案类型），不含题目内容。"""
    routes = []
    if isinstance(answers, dict):
        for answer in answers.values():
            if isinstance(answer, dict):
                routes.append(str(answer.get("choice")
                                  or answer.get("type") or "?"))
    return routes


# ---------------------------------------------------------------------------
# R0 补强：请求缓存（data/cache/decision/，TTL 7 天，仅 shadow 启用）
# ---------------------------------------------------------------------------
def _data_root():
    """数据根，与 tools/credential_store._resolve_data_dir 同口径
    （VT_DATA_ROOT / 打包 / 源码三形态），缓存落数据根不落 C 盘。"""
    env = (os.environ.get("VT_DATA_ROOT") or "").strip().strip('"')
    if env:
        return env
    if getattr(sys, "frozen", False):
        return os.path.join(os.path.dirname(os.path.abspath(sys.executable)),
                            "data")
    here = os.path.dirname(os.path.abspath(__file__))          # tools/
    parent = os.path.dirname(here)                              # 程序根
    if os.path.isdir(os.path.join(parent, "tools")) and \
            os.path.isfile(os.path.join(parent, "tools", "ai_client.py")):
        return os.path.join(parent, "data")
    return os.path.join(os.path.dirname(here), "data")


def _resolve_cache_dir():
    """请求缓存目录 data/cache/decision/；VT_DECISION_CACHE_DIR 可覆盖
    （便携/自测隔离用）。"""
    override = (os.environ.get("VT_DECISION_CACHE_DIR") or "").strip().strip('"')
    if override:
        return override
    return os.path.join(_data_root(), "cache", "decision")


def _cache_key(schema_version, model, state, questions):
    """缓存键：sha256(schema_version + model + canonical(state+questions))。

    canonical = sort_keys 紧凑 JSON——同语义请求命中同一键；跨 schema/模型
    不串缓存。键里不含任何凭据。
    """
    payload = json.dumps({"schema_version": schema_version, "model": model,
                          "state": state, "questions": questions},
                         ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), default=str,
                         allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _finite_number(value, low=None, high=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DecisionError("Jev 返回了非数字字段")
    number = float(value)
    if not math.isfinite(number):
        raise DecisionError("Jev 返回了非有限数字")
    if low is not None and number < low or high is not None and number > high:
        raise DecisionError("Jev 返回数字越界")
    return number


def _validate_probabilities(value, required=None):
    if not isinstance(value, dict):
        raise DecisionError("Jev probabilities 不是对象")
    total = 0.0
    for key, probability in value.items():
        if not isinstance(key, str):
            raise DecisionError("Jev probabilities 含非法键")
        total += _finite_number(probability, 0.0, 1.0)
    if required and any(str(key) not in value for key in required):
        raise DecisionError("Jev probabilities 缺少问题选项")
    if value and abs(total - 1.0) > 0.08:
        raise DecisionError("Jev probabilities 未归一化")


def validate_questions(questions):
    if not isinstance(questions, dict) or not (1 <= len(questions) <= MAX_QUESTIONS):
        raise DecisionError("Jev questions 必须包含 1–16 个问题")
    for name, question in questions.items():
        if not isinstance(name, str) or not name.strip() or not isinstance(question, dict):
            raise DecisionError("Jev 问题名或问题对象非法")
        qtype = question.get("type")
        if qtype not in ("choice", "noul", "score"):
            raise DecisionError("Jev 问题类型须为 choice/noul/score")
        if "instructions" in question and not isinstance(question["instructions"], str):
            raise DecisionError("Jev instructions 须为字符串")
        criteria = question.get("criteria")
        if qtype == "choice":
            if (not isinstance(criteria, dict) or not (1 <= len(criteria) <= 255)
                    or any(not isinstance(k, str) or not k or not isinstance(v, str)
                           for k, v in criteria.items())):
                raise DecisionError("choice criteria 须为 1–255 个字符串映射")
        elif qtype == "score":
            if (not isinstance(criteria, list) or not (2 <= len(criteria) <= 255)
                    or any(not isinstance(x, str) for x in criteria)):
                raise DecisionError("score criteria 须为 2–255 个等级描述")
        elif criteria is not None and not isinstance(criteria, dict):
            raise DecisionError("noul criteria 须为可选对象")


def validate_response(response, questions, expected_model=None):
    """严格校验官方响应并返回内部版本化信封，不混入业务状态或凭据。

    expected_model：决策模型槽（DEFAULT_CONFIG.decision_model）——缺省按
    MODEL 校验，与既有调用方（两参形式）完全兼容。
    """
    model_name = str(expected_model or MODEL)
    if not isinstance(response, dict):
        raise DecisionError("Jev 响应不是 JSON 对象")
    if response.get("error"):
        raise DecisionError("Jev 服务端错误：" + str(response["error"])[:240])
    if response.get("model") != model_name:
        raise DecisionError("Jev 响应模型不匹配")
    answers = response.get("answers")
    if not isinstance(answers, dict):
        raise DecisionError("Jev 响应缺少 answers")
    for name, question in questions.items():
        answer = answers.get(name)
        if not isinstance(answer, dict) or answer.get("type") != question["type"]:
            raise DecisionError("Jev 问题 %s 的响应缺失或类型不一致" % name)
        qtype = question["type"]
        if qtype == "choice":
            if answer.get("choice") not in question["criteria"]:
                raise DecisionError("Jev choice 返回了未声明选项")
            _finite_number(answer.get("confidence"), 0.0, 1.0)
            _validate_probabilities(answer.get("probabilities"),
                                    question["criteria"].keys())
        elif qtype == "noul":
            _finite_number(answer.get("noul"), 0.0, 1.0)
            if "probabilities" in answer:
                _validate_probabilities(answer["probabilities"])
        else:
            levels = len(question["criteria"])
            _finite_number(answer.get("score"), 0.0, float(levels - 1))
            _finite_number(answer.get("confidence"), 0.0, 1.0)
            _validate_probabilities(answer.get("probabilities"), range(levels))
            if not isinstance(answer.get("legend"), dict):
                raise DecisionError("Jev score 缺少 legend")
    usage = response.get("usage") or {}
    if not isinstance(usage, dict):
        raise DecisionError("Jev usage 非法")
    latency = response.get("latency_ms")
    if latency is not None:
        _finite_number(latency, 0.0)
    return {"schema_version": SCHEMA_VERSION, "model": model_name,
            "request_id": str(response.get("request_id") or ""),
            "answers": answers, "usage": usage,
            "latency_ms": latency}


class DecisionClient:
    """无第三方 SDK 依赖的 Jev 客户端；opener 仅供自测注入。

    R0（2026-11-22 WP3 part 1）新增：
      * ``credential_source``：凭据来源标记（decision / global_fallback），
        来自加载缝注入或配置推断；只作字符串标记，状态/审计不含明文 key；
      * shadow 模式请求缓存（TTL 7 天，键含 schema/model/state/questions），
        命中返回的信封带 ``cached=True``；显式 ``cache=False`` 可关；
      * 错误分类（DecisionError.category）+ 聚合审计（audit_summary）。
    """

    def __init__(self, config=None, *, api_key=None, opener=None, timeout=None,
                 cache=None, cache_ttl=None):
        self.config = dict(config or {})
        if api_key is not None:
            self.config["api_key"] = str(api_key or "")
        self.status = availability(self.config)
        self.credential_source = str(
            self.status.get("credential_source") or CREDENTIAL_SOURCE_GLOBAL)
        self.api_key = str(self.config.get("api_key") or "").strip()
        if not self.api_key:
            # 直配独立 decision_api_key（未经加载缝注入）时兜底取用
            self.api_key = str(self.config.get("decision_api_key") or "").strip()
        self.model = str(self.config.get("decision_model") or "").strip() or MODEL
        try:
            self.timeout = float(timeout or self.config.get("decision_timeout")
                                 or DEFAULT_TIMEOUT)
        except (TypeError, ValueError):
            self.timeout = DEFAULT_TIMEOUT
        if self.timeout <= 0:
            self.timeout = DEFAULT_TIMEOUT
        self.opener = opener or self._region_open
        # 请求缓存（R0 影子专用）：缺省仅「激活且 mode=shadow」启用；
        # 显式 cache=False 可关。缓存目录只在启用时解析。
        if cache is None:
            cache = self.active and self.status.get("mode") == "shadow"
        self.cache_enabled = bool(cache) and self.active
        try:
            self.cache_ttl = float(cache_ttl or CACHE_TTL_SECONDS)
        except (TypeError, ValueError):
            self.cache_ttl = CACHE_TTL_SECONDS
        self.cache_dir = _resolve_cache_dir() if self.cache_enabled else ""

    @staticmethod
    def _region_open(request, timeout):
        """按端点区域选 opener：北京强制直连（与 tools/ai_client.py 的国内
        口径一致，避免系统代理海外节点被对端断连）；其它区域（新加坡预留）
        跟随系统/环境代理——海外端点可能需要代理才能达，实测后再定口径。
        """
        url = getattr(request, "full_url", "")
        if "cn-beijing" in str(url):
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({}))
            return opener.open(request, timeout=timeout)
        return urllib.request.urlopen(request, timeout=timeout)

    # ---- 请求缓存（影子专用；任何缓存故障静默降级，绝不影响主流程）----
    def _cache_path(self, key):
        return os.path.join(self.cache_dir, str(key) + ".json")

    def _cache_read(self, key):
        """读缓存；过期 / 损坏 / 缺失一律视为未命中。"""
        try:
            with open(self._cache_path(key), encoding="utf-8") as fh:
                data = json.load(fh)
            stored = float(data.get("stored_at") or 0.0)
            if stored <= 0 or (time.time() - stored) > self.cache_ttl:
                return None
            envelope = data.get("envelope")
            return envelope if isinstance(envelope, dict) else None
        except (OSError, ValueError, TypeError):
            return None

    def _cache_write(self, key, envelope):
        if not self.cache_dir or not isinstance(envelope, dict):
            return
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
            path = self._cache_path(key)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({"stored_at": time.time(),
                           "ttl_seconds": self.cache_ttl,
                           "schema_version": self.status.get("schema_version"),
                           "model": self.model,
                           "envelope": envelope},
                          fh, ensure_ascii=False)
            os.replace(tmp, path)
        except (OSError, ValueError, TypeError):
            pass

    @property
    def active(self):
        return bool(self.status.get("active"))

    def _audit_error(self, category, questions):
        _audit_record("", error_category=str(category or "unknown"),
                      questions=len(questions or {}))

    def decide(self, state, questions):
        if not self.active:
            raise DecisionUnavailable(self.status.get("reason") or "inactive")
        if not isinstance(state, (str, dict, list)) or state in ("", None, [], {}):
            raise DecisionError("Jev state 不能为空", "protocol")
        validate_questions(questions)
        cache_key = ""
        if self.cache_enabled:
            try:
                cache_key = _cache_key(
                    self.status.get("schema_version") or SCHEMA_VERSION,
                    self.model, state, questions)
            except (TypeError, ValueError):
                cache_key = ""            # state 不可序列化 → 跳过缓存直发
            if cache_key:
                cached = self._cache_read(cache_key)
                if cached is not None:
                    _audit_record(cached.get("request_id") or "", cached=True,
                                  questions=len(questions),
                                  choices=_answer_routes(cached.get("answers")
                                                         or {}))
                    return dict(cached, cached=True)
        body = {"model": self.model, "state": state, "questions": questions}
        payload = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
        request = urllib.request.Request(
            self.status["endpoint"], data=payload, method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + self.api_key})
        started = time.monotonic()
        try:
            response = self.opener(request, timeout=self.timeout)
            with response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            category = classify_error(exc)
            self._audit_error(category, questions)
            try:
                detail = exc.read(2048).decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                detail = ""
            raise DecisionError("Jev HTTP %s：%s" % (exc.code, detail[:300]),
                                category) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            category = classify_error(exc)
            self._audit_error(category, questions)
            raise DecisionError("Jev 请求失败：" + str(exc)[:240],
                                category) from exc
        try:
            obj = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            self._audit_error("protocol", questions)
            raise DecisionError("Jev 返回了非法 JSON", "protocol") from exc
        try:
            envelope = validate_response(obj, questions, self.model)
        except DecisionError as exc:
            if not str(getattr(exc, "category", "") or "").strip() \
                    or exc.category == "unknown":
                exc.category = "protocol"
            self._audit_error(exc.category, questions)
            raise
        latency_ms = (time.monotonic() - started) * 1000.0
        _audit_record(envelope.get("request_id") or "",
                      questions=len(questions),
                      choices=_answer_routes(envelope.get("answers") or {}),
                      latency_ms=latency_ms)
        if self.cache_enabled and cache_key:
            self._cache_write(cache_key, envelope)
        return dict(envelope, cached=False)


__all__ = ["MODEL", "SCHEMA_VERSION", "DEFAULT_MODE", "CACHE_TTL_SECONDS",
           "DECISION_ENDPOINT_WHITELIST", "DECISION_ENDPOINT_ENABLED",
           "CREDENTIAL_SOURCE_DECISION", "CREDENTIAL_SOURCE_GLOBAL",
           "DecisionClient", "DecisionError", "DecisionUnavailable",
           "availability", "is_aliyun_token_plan",
           "is_allowed_decision_endpoint", "region_of", "systemone_url",
           "validate_questions", "validate_response", "classify_error",
           "audit_summary", "audit_reset"]
