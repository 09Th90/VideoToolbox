# -*- coding: utf-8 -*-
# @version 3.1.1
"""阿里云百炼 System One / Jev 结构化决策客户端。

官方协议：POST /compatible-mode/v1/systemone，模型 decision-model-preview。
https://help.aliyun.com/zh/model-studio/decision-model-api

激活门控（有意保持严格）：
  * 全局 AI 启用，decision_mode=shadow；
  * 复用全局 AI 的独立凭据（不在本模块保存或记录明文）；
  * base_url 必须是百炼 Token Plan 专属域名 token-plan.*.maas.aliyuncs.com。

普通百炼按量、工作空间专属域名、火山方舟 Token Plan 和其他 OpenAI 兼容端点
均不激活。当前只支持 shadow/off，不提供自动改写权限。
"""
from __future__ import annotations

import json
import math
import urllib.error
import urllib.parse
import urllib.request

MODEL = "decision-model-preview"
SCHEMA_VERSION = "vt.decision.v1"
DEFAULT_MODE = "shadow"
DEFAULT_TIMEOUT = 12.0
MAX_QUESTIONS = 16
TOKEN_PLAN_SUFFIX = ".maas.aliyuncs.com"


class DecisionError(RuntimeError):
    """网络、鉴权或协议错误；调用方应降级，不阻断主业务。"""


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
    """仅认百炼 Token Plan 专属域名，不认普通 *.aliyuncs.com 或火山套餐。"""
    try:
        host = (_parts(base_url).hostname or "").lower().rstrip(".")
    except ValueError:
        return False
    return host.startswith("token-plan.") and host.endswith(TOKEN_PLAN_SUFFIX)


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


def availability(config):
    """返回可序列化门控状态；纯本地计算，不发请求、不返回凭据。"""
    cfg = dict(config or {})
    mode = str(cfg.get("decision_mode") or DEFAULT_MODE).strip().lower()
    base = str(cfg.get("base_url") or "").strip()
    status = {"active": False, "mode": mode, "model": MODEL,
              "schema_version": SCHEMA_VERSION, "endpoint": "",
              "reason": ""}
    if not bool(cfg.get("enabled", True)):
        status["reason"] = "global_ai_disabled"
        return status
    if mode == "off":
        status["reason"] = "mode_off"
        return status
    if mode != "shadow":
        status["reason"] = "unsupported_mode"
        return status
    if not str(cfg.get("api_key") or "").strip():
        status["reason"] = "missing_api_key"
        return status
    if not is_aliyun_token_plan(base):
        status["reason"] = "unsupported_endpoint"
        return status
    try:
        status["endpoint"] = systemone_url(base)
    except ValueError as exc:
        status["reason"] = "invalid_endpoint"
        status["detail"] = str(exc)
        return status
    status["active"] = True
    return status


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


def validate_response(response, questions):
    """严格校验官方响应并返回内部版本化信封，不混入业务状态或凭据。"""
    if not isinstance(response, dict):
        raise DecisionError("Jev 响应不是 JSON 对象")
    if response.get("error"):
        raise DecisionError("Jev 服务端错误：" + str(response["error"])[:240])
    if response.get("model") != MODEL:
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
    return {"schema_version": SCHEMA_VERSION, "model": MODEL,
            "request_id": str(response.get("request_id") or ""),
            "answers": answers, "usage": usage,
            "latency_ms": latency}


class DecisionClient:
    """无第三方 SDK 依赖的 Jev 客户端；opener 仅供自测注入。"""

    def __init__(self, config=None, *, api_key=None, opener=None, timeout=None):
        self.config = dict(config or {})
        if api_key is not None:
            self.config["api_key"] = str(api_key or "")
        self.status = availability(self.config)
        self.api_key = str(self.config.get("api_key") or "").strip()
        try:
            self.timeout = float(timeout or self.config.get("decision_timeout")
                                 or DEFAULT_TIMEOUT)
        except (TypeError, ValueError):
            self.timeout = DEFAULT_TIMEOUT
        if self.timeout <= 0:
            self.timeout = DEFAULT_TIMEOUT
        self.opener = opener or self._direct_open

    @staticmethod
    def _direct_open(request, timeout):
        # 百炼国内端点强制直连，与 tools/ai_client.py 的国内请求口径一致。
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        return opener.open(request, timeout=timeout)

    @property
    def active(self):
        return bool(self.status.get("active"))

    def decide(self, state, questions):
        if not self.active:
            raise DecisionUnavailable(self.status.get("reason") or "inactive")
        if not isinstance(state, (str, dict, list)) or state in ("", None, [], {}):
            raise DecisionError("Jev state 不能为空")
        validate_questions(questions)
        body = {"model": MODEL, "state": state, "questions": questions}
        payload = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
        request = urllib.request.Request(
            self.status["endpoint"], data=payload, method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + self.api_key})
        try:
            response = self.opener(request, timeout=self.timeout)
            with response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read(2048).decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                detail = ""
            raise DecisionError("Jev HTTP %s：%s" % (exc.code, detail[:300])) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise DecisionError("Jev 请求失败：" + str(exc)[:240]) from exc
        try:
            obj = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise DecisionError("Jev 返回了非法 JSON") from exc
        return validate_response(obj, questions)


__all__ = ["MODEL", "SCHEMA_VERSION", "DEFAULT_MODE", "DecisionClient",
           "DecisionError", "DecisionUnavailable", "availability",
           "is_aliyun_token_plan", "systemone_url", "validate_questions",
           "validate_response"]
