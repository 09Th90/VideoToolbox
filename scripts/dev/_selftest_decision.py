# -*- coding: utf-8 -*-
# @version 3.2.5
"""Jev / System One 门控、协议与影子不改写自检（全部使用模拟响应，不联网）。

WP3 part 1（2026-11-22）扩展：凭据隔离 / 端点白名单 / region 绑定 /
R1 缺独立 key / credential_source 标记 / 请求缓存命中 / decision_enabled
门禁 / 七类异常注入回退（断网/429/畸形JSON/越界概率/超时/region_mismatch/
missing_key）——输出恒为「原规则 + degraded 审计」。
"""
import copy
import io
import json
import os
import shutil
import sys
import tempfile
import urllib.error
from pathlib import Path
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))

from tools.decision_client import (DecisionClient, DecisionError, DecisionUnavailable,
                                   availability, systemone_url, validate_response,
                                   CACHE_TTL_SECONDS, audit_reset, audit_summary,
                                   classify_error, is_allowed_decision_endpoint,
                                   region_of)
from tools.ai_client import DEFAULT_CONFIG
import tools.ai_client as ai_client_mod
from tools.credential_store import (SECRET_FIELDS as CRED_SECRET_FIELDS,
                                    has as cred_has, mask as cred_mask,
                                    status as cred_status)
from core.shared import decision as decision_shim
from features.voiceprint.voiceprint_decision import ROUTES, apply_shadow
from features.calibrate.calib_decision import ROUTES as CALIB_ROUTES
from features.calibrate.calib_decision import apply_shadow as apply_calib_shadow

PASS = 0
FAIL = 0


def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print("PASS", name)
    else:
        FAIL += 1
        print("FAIL", name, detail)


TOKEN_PLAN = "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
BASE = {"enabled": True, "api_key": "test-only", "decision_mode": "shadow",
        "base_url": TOKEN_PLAN}

# 请求缓存隔离：自测客户端的 shadow 缓存全部进临时目录，不污染真实 data/cache。
os.makedirs(os.path.join(ROOT, "data", "tmp"), exist_ok=True)
_CACHE_TMP = tempfile.mkdtemp(prefix="vt_jevcache_",
                              dir=os.path.join(ROOT, "data", "tmp"))
os.environ["VT_DECISION_CACHE_DIR"] = _CACHE_TMP

check("百炼 Token Plan 激活", availability(BASE)["active"])
for name, url in (
        ("普通百炼不激活", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        ("工作空间专属域名不激活", "https://ws.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"),
        ("火山 Token Plan 不激活", "https://ark.cn-beijing.volces.com/api/plan/v3"),
        ("QwenCloud 不激活", "https://ap-southeast-1.maas.qwencloudapi.com/compatible-mode/v1"),
        ("HTTP 不激活", "http://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1")):
    cfg = dict(BASE, base_url=url)
    check(name, not availability(cfg)["active"])
check("off 不激活", not availability(dict(BASE, decision_mode="off"))["active"])
check("缺密钥不激活", not availability(dict(BASE, api_key=""))["active"])
check("全局 AI 禁用不激活", not availability(dict(BASE, enabled=False))["active"])
check("URL 规范化", systemone_url(TOKEN_PLAN).endswith("/compatible-mode/v1/systemone"))
check("非法超时值回落默认", DecisionClient(
    dict(BASE, decision_timeout="bad")).timeout == 12.0)
check("决策配置进入持久化白名单", DEFAULT_CONFIG.get("decision_mode") == "shadow"
      and all(k in DEFAULT_CONFIG for k in
              ("decision_timeout", "decision_max_items", "decision_batch_size")))

calls = []
inactive = DecisionClient(dict(BASE, base_url="https://dashscope.aliyuncs.com"),
                          opener=lambda *a, **k: calls.append(a))
try:
    inactive.decide("x", {"q": {"type": "noul"}})
except DecisionUnavailable:
    pass
check("未激活时零网络请求", not calls)

questions = {
    "c": {"type": "choice", "criteria": {"a": "甲", "b": "乙"}},
    "n": {"type": "noul"},
    "s": {"type": "score", "criteria": ["差", "中", "好", "优"]},
}
official = {
    "model": "decision-model-preview", "request_id": "req-test",
    "answers": {
        "c": {"type": "choice", "choice": "a", "confidence": 0.8,
              "probabilities": {"a": 0.8, "b": 0.2}},
        "n": {"type": "noul", "noul": 0.75},
        "s": {"type": "score", "score": 2.0, "confidence": 0.8,
              "probabilities": {"0": 0.05, "1": 0.1, "2": 0.8, "3": 0.05},
              "legend": {"0": "差", "1": "中", "2": "好", "3": "优"}},
    },
    "usage": {"input_tokens": 20}, "latency_ms": 10,
}
captured = {}


def fake_open(request, timeout):
    captured["url"] = request.full_url
    captured["body"] = json.loads(request.data.decode("utf-8"))
    captured["timeout"] = timeout
    return io.BytesIO(json.dumps(official).encode("utf-8"))


client = DecisionClient(BASE, opener=fake_open)
envelope = client.decide({"business": "test"}, questions)
check("客户端发出官方 System One 路径", captured["url"].endswith("/systemone"))
check("请求体只含官方字段", set(captured["body"]) == {"model", "state", "questions"})
check("响应带内部版本", envelope["schema_version"] == "vt.decision.v1")
check("三类问题均通过校验", set(envelope["answers"]) == {"c", "n", "s"})
try:
    validate_response(dict(official, answers=dict(official["answers"], c={
        "type": "choice", "choice": "unknown", "confidence": 0.8,
        "probabilities": {"a": 0.8, "b": 0.2}})), questions)
except DecisionError:
    check("非法 choice 被拒绝", True)
else:
    check("非法 choice 被拒绝", False)

bad_probability = copy.deepcopy(official)
bad_probability["answers"]["c"]["probabilities"] = {"a": 0.9, "b": 0.3}
try:
    validate_response(bad_probability, questions)
except DecisionError:
    check("非归一化概率被拒绝", True)
else:
    check("非归一化概率被拒绝", False)


def timeout_open(_request, timeout):
    raise TimeoutError("模拟连接超时")


timeout_client = DecisionClient(BASE, opener=timeout_open)
try:
    timeout_client.decide("x", {"n": {"type": "noul"}})
except DecisionError as exc:
    check("客户端超时映射为可降级错误", "请求失败" in str(exc))
else:
    check("客户端超时映射为可降级错误", False)


class FakeShadow:
    def __init__(self, error=False, routes=None):
        self.active = True
        self.status = {"active": True, "mode": "shadow",
                       "model": "decision-model-preview", "endpoint": "https://example/systemone"}
        self.config = {"decision_max_items": 32, "decision_batch_size": 8}
        self.error = error
        self.routes = routes or ROUTES
        self.calls = []

    def decide(self, state, questions):
        self.calls.append((state, questions))
        if self.error:
            raise DecisionError("模拟超时")
        answers = {}
        route_keys = list(self.routes)
        for i, name in enumerate(questions):
            choice = route_keys[1] if i == 0 else route_keys[0]
            probabilities = {key: 0.1 for key in self.routes}
            probabilities[choice] = 0.8
            answers[name] = {"type": "choice", "choice": choice,
                             "confidence": 0.8, "probabilities": probabilities}
        return {"model": "decision-model-preview", "request_id": "shadow-req",
                "answers": answers}


def voiceprint_fixture():
    states = ["keep", "review", "review", "drop"]
    cues = [SimpleNamespace(text="cue%d" % i, speaker="", start=i * 1000,
                            end=i * 1000 + 800) for i in range(4)]
    verdict = [(cue, state, 0.5) for cue, state in zip(cues, states)]
    details = [{"num": i + 1, "start": cue.start, "end": cue.end,
                "duration_ms": 800, "state": state, "score": 0.5,
                "source": "cue_fallback", "reason": "borderline" if state == "review" else "",
                "speaker": "", "cluster": 0}
               for i, (cue, state) in enumerate(zip(cues, states))]
    return verdict, details


verdict, details = voiceprint_fixture()
original = copy.deepcopy(verdict)
shadow = FakeShadow()
summary = apply_shadow(verdict, details, shadow, threshold=0.55, low=0.45)
check("声纹只选最终 review", summary["review_total"] == 2 and summary["evaluated"] == 2)
check("声纹影子不改 verdict", verdict == original)
check("keep/drop 无 Jev 证据", "jev" not in details[0] and "jev" not in details[3])
check("review 保存概率与 request_id",
      details[1]["jev"]["request_id"] == "shadow-req"
      and abs(sum(details[1]["jev"]["probabilities"].values()) - 1.0) < 1e-6)
check("声纹问题不含身份判定选项", set(ROUTES) == {
    "routine_review", "priority_manual", "insufficient_evidence"})

verdict2, details2 = voiceprint_fixture()
original2 = copy.deepcopy(verdict2)
summary2 = apply_shadow(verdict2, details2, FakeShadow(error=True), threshold=0.55, low=0.45)
check("声纹异常按批降级", summary2["evaluated"] == 0 and len(summary2["errors"]) == 1)
check("声纹降级不改 verdict", verdict2 == original2)
check("声纹降级原因落明细", details2[1]["jev"]["status"] == "degraded")

calib = {"accepted": [(1, "恩德菲尔德", "终末地", "术语", False),
                      (2, "旧句", "新句", "整句校准", True)],
         "output_text": "已校验字幕，不应被影子复核改动"}
calib_original = copy.deepcopy(calib)
calib_fake = FakeShadow(routes=CALIB_ROUTES)
calib_summary = apply_calib_shadow(calib, calib_fake)
check("校准复核全部采纳项", calib_summary["accepted_total"] == 2
      and calib_summary["evaluated"] == 2)
check("校准影子不改 accepted 与文本", calib["accepted"] == calib_original["accepted"]
      and calib["output_text"] == calib_original["output_text"])
check("校准保存结构化概率", calib["decision"]["items"][0]["choice"] == "manual_review"
      and abs(sum(calib["decision"]["items"][0]["probabilities"].values()) - 1.0) < 1e-6)
check("校准问题禁止生成文本",
      all("不生成新文本" in q["instructions"]
          for q in calib_fake.calls[0][1].values()))

calib_error = {"accepted": copy.deepcopy(calib_original["accepted"])}
calib_error_before = copy.deepcopy(calib_error["accepted"])
calib_error_summary = apply_calib_shadow(
    calib_error, FakeShadow(error=True, routes=CALIB_ROUTES))
check("校准异常按批降级", len(calib_error_summary["errors"]) == 1
      and calib_error_summary["items"][0]["status"] == "degraded")
check("校准降级不改 accepted", calib_error["accepted"] == calib_error_before)

from features.calibrate.calib_ai_agent import _write_report
report_result = {"style": "term", "script_changes": 0, "ai_changes": 2,
                 "rejected": 0, "accepted": calib["accepted"], "rejected_items": [],
                 "width_over": 0, "width_widest": ("", ""), "manual_check": [],
                 "chunks": 1, "rules_injected": 0, "rules_hot": 0,
                 "meta": {}, "learn": {}, "decision": calib["decision"]}
with tempfile.TemporaryDirectory(prefix="vt_jev_",
                                 dir=os.path.join(ROOT, "data", "tmp")) as tmp:
    report_path = os.path.join(tmp, "report.md")
    _write_report(report_path, "in.srt", "out.srt", "", 1, report_result, [])
    with open(report_path, encoding="utf-8") as fh:
        report_text = fh.read()
check("校准报告包含 Jev 结构化结果", "Jev 结构化影子复核" in report_text
      and "manual_review" in report_text)
check("校准报告明确影子不改写", "不会撤销本轮采纳项" in report_text)

# ===========================================================================
# WP3 part 1（2026-11-22）扩展断言
# ===========================================================================

# ---- 端点白名单（北京过 / 新加坡预留 / 非白名单拒）----
SG_PLAN = "https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1"
check("白名单北京激活（显式 decision_enabled）",
      availability(dict(BASE, decision_enabled=True))["active"])
check("新加坡在白名单内（预留）", is_allowed_decision_endpoint(SG_PLAN))
sg_status = availability(dict(BASE, decision_enabled=True, base_url=SG_PLAN))
check("新加坡预留不激活（区域未实测）", not sg_status["active"]
      and sg_status["reason"] == "endpoint_region_untested")
check("白名单精确拒：子域伪装", not is_allowed_decision_endpoint(
    "https://evil.token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"))
check("白名单精确拒：后缀伪装", not is_allowed_decision_endpoint(
    "https://token-plan.cn-beijing.maas.aliyuncs.com.evil.example/"
    "compatible-mode/v1"))
check("白名单精确拒：未收录区域", not is_allowed_decision_endpoint(
    "https://token-plan.eu-central-1.maas.aliyuncs.com/compatible-mode/v1"))
check("region_of 解析区域段", region_of(TOKEN_PLAN) == "cn-beijing"
      and region_of(SG_PLAN) == "ap-southeast-1" and region_of("") == "")

# ---- region 绑定（decision_key_region 审计字段须等于端点区域）----
mis_status = availability(dict(BASE, decision_enabled=True,
                               decision_key_region="ap-southeast-1"))
check("region 绑定不匹配拒", not mis_status["active"]
      and mis_status["reason"] == "region_mismatch")
okr_status = availability(dict(BASE, decision_enabled=True,
                               decision_key_region="cn-beijing"))
check("region 绑定匹配放行", okr_status["active"]
      and okr_status["endpoint_region"] == "cn-beijing")

# ---- R1 预留：missing_decision_key（decision_require_own_key 模拟）----
r1_status = availability(dict(BASE, decision_require_own_key=True))
check("R1 缺独立 key 不可用", not r1_status["active"]
      and r1_status["reason"] == "missing_decision_key")
r1_ok_status = availability(dict(BASE, decision_require_own_key=True,
                                 decision_api_key="own-key",
                                 credential_source="decision"))
check("R1 有独立 key 放行", r1_ok_status["active"]
      and r1_ok_status["credential_source"] == "decision")

# ---- decision_enabled 门禁（默认出厂 False ⇒ 零激活零请求）----
dis_status = availability(dict(BASE, decision_enabled=False))
check("decision_enabled=False 门禁", not dis_status["active"]
      and dis_status["reason"] == "decision_disabled")
check("出厂默认零激活", not availability(DEFAULT_CONFIG)["active"]
      and availability(DEFAULT_CONFIG)["reason"] == "decision_disabled")
check("决策 4 键进入 DEFAULT_CONFIG 且独立 key 不在内",
      all(k in DEFAULT_CONFIG for k in ("decision_enabled", "decision_base_url",
                                        "decision_model", "decision_concurrency"))
      and DEFAULT_CONFIG["decision_enabled"] is False
      and DEFAULT_CONFIG["decision_model"] == "decision-model-preview"
      and DEFAULT_CONFIG["decision_concurrency"] == 1
      and "decision_api_key" not in DEFAULT_CONFIG)

# ---- 端点回落审计字段（decision_base_url 空 = 回落全局 base_url）----
check("端点回落全局记 endpoint_fallback_global",
      availability(dict(BASE, decision_enabled=True,
                        decision_base_url=""))["endpoint_fallback_global"]
      and not availability(dict(BASE, decision_enabled=True,
                                decision_base_url=TOKEN_PLAN))["endpoint_fallback_global"])

# ---- credential_source 标记（字符串标记，非明文）----
check("凭据来源标记：无独立 key = global_fallback",
      availability(dict(BASE, decision_enabled=True))["credential_source"]
      == "global_fallback")
check("凭据来源标记：配置带独立 key = decision",
      availability(dict(BASE, decision_enabled=True,
                        decision_api_key="x"))["credential_source"] == "decision")
check("凭据来源标记：显式标记优先",
      availability(dict(BASE, decision_enabled=True,
                        credential_source="decision"))["credential_source"]
      == "decision")

# ---- 凭据隔离（save_config 剥离 / ai_config 回读 / credentials 状态掩码）----
_orig_cfg_path = ai_client_mod.CONFIG_PATH
_orig_data_dir = ai_client_mod.DATA_DIR
_orig_cred_set = ai_client_mod._cred.set
_SECRET_TMP = tempfile.mkdtemp(prefix="vt_secreg_",
                               dir=os.path.join(ROOT, "data", "tmp"))
_secret_writes = []
try:
    ai_client_mod.DATA_DIR = Path(_SECRET_TMP)
    ai_client_mod.CONFIG_PATH = Path(_SECRET_TMP) / "ai_config.json"
    ai_client_mod._cred.set = \
        lambda name, value="": _secret_writes.append((name, str(value or "")))
    _iso_cfg = dict(DEFAULT_CONFIG)
    _iso_cfg["api_key"] = ""
    _iso_cfg["asr_api_key"] = ""
    _iso_cfg["decision_api_key"] = "sk-decision-secret-123"
    ai_client_mod.save_config(_iso_cfg)
    _iso_text = ai_client_mod.CONFIG_PATH.read_text(encoding="utf-8")
    check("凭据隔离：ai_config 回读不含 decision_api_key",
          "decision_api_key" not in _iso_text
          and "sk-decision-secret-123" not in _iso_text)
    check("凭据隔离：误传独立 key 剥离送凭据层",
          any(n == "decision_api_key" and v == "sk-decision-secret-123"
              for n, v in _secret_writes))
    check("凭据隔离：SECRET_FIELDS 同步三字段",
          "decision_api_key" in CRED_SECRET_FIELDS
          and set(cred_status()) == set(CRED_SECRET_FIELDS)
          and all(isinstance(v, bool) for v in cred_status().values()))
    check("凭据隔离：决策 4 键落盘白名单",
          all(k in _iso_text for k in ("decision_enabled", "decision_base_url",
                                       "decision_model", "decision_concurrency")))
    check("凭据隔离：mask 脱敏不回显明文",
          "sk-decision-secret-123"
          not in cred_mask("decision_api_key", "sk-decision-secret-123"))
finally:
    ai_client_mod.CONFIG_PATH = _orig_cfg_path
    ai_client_mod.DATA_DIR = _orig_data_dir
    ai_client_mod._cred.set = _orig_cred_set
    shutil.rmtree(_SECRET_TMP, ignore_errors=True)

# ---- shim 独立凭据注入（仅内存覆盖，永不回写调用方配置）----
shim_default = decision_shim.decision_client()
_expected_source = "decision" if cred_has("decision_api_key") else "global_fallback"
check("shim 默认路径：凭据来源标记", shim_default.credential_source == _expected_source)
check("shim 默认路径：出厂门禁关闭零请求", not shim_default.active
      and shim_default.status["reason"] == "decision_disabled")
_shim_leak = str(shim_default.api_key or "")
check("shim 默认路径：状态副本不含明文",
      not _shim_leak or _shim_leak not in json.dumps(shim_default.status))


class _FakeCred:
    """注入用假凭据层：decision_api_key 恒有值。"""

    @staticmethod
    def get(name, default=""):
        if name == "decision_api_key":
            return "sk-decision-inject-test"
        return default


_orig_cred_mod = decision_shim.credential_mod
try:
    decision_shim.credential_mod = lambda: _FakeCred
    _cfg_in = dict(DEFAULT_CONFIG, enabled=True, decision_enabled=True,
                   base_url=TOKEN_PLAN, decision_base_url=TOKEN_PLAN,
                   decision_mode="shadow", api_key="global-key-unchanged")
    injected = decision_shim.decision_client(_cfg_in)
    check("shim 独立凭据注入（仅内存覆盖 api_key）",
          injected.config["api_key"] == "sk-decision-inject-test"
          and injected.api_key == "sk-decision-inject-test"
          and injected.credential_source == "decision"
          and injected.status["credential_source"] == "decision"
          and injected.active)
    check("shim 注入不回写调用方配置",
          _cfg_in["api_key"] == "global-key-unchanged")
    check("shim 注入后状态副本不含明文",
          "sk-decision-inject-test" not in json.dumps(injected.status))
finally:
    decision_shim.credential_mod = _orig_cred_mod

# ---- R0 请求缓存（TTL 7 天，仅 shadow）与聚合审计 ----
audit_reset()
_fake_calls = {"n": 0}


def counting_open(request, timeout):
    _fake_calls["n"] += 1
    return fake_open(request, timeout)


cache_client = DecisionClient(dict(BASE, decision_enabled=True),
                              opener=counting_open)
check("shadow 客户端默认启用请求缓存（TTL 7 天）",
      cache_client.cache_enabled
      and cache_client.cache_ttl == CACHE_TTL_SECONDS
      and os.path.dirname(cache_client.cache_dir) != ""
      and cache_client.cache_dir.startswith(_CACHE_TMP))
env1 = cache_client.decide({"business": "cache"}, questions)
check("首次请求未命中缓存", env1.get("cached") is False and _fake_calls["n"] == 1)
env2 = cache_client.decide({"business": "cache"}, questions)
check("同语义请求命中缓存", env2.get("cached") is True
      and env2["answers"] == env1["answers"] and _fake_calls["n"] == 1)
env3 = cache_client.decide({"business": "cache-other-state"}, questions)
check("不同 state 不串缓存", env3.get("cached") is False and _fake_calls["n"] == 2)
snap = audit_summary()
check("聚合审计：缓存命中与调用计数", snap["cache_hits"] == 1 and snap["calls"] == 2)
check("聚合审计：路由分布", snap["routes"].get("a") == 3
      and snap["routes"].get("noul") == 3 and snap["routes"].get("score") == 3)
check("聚合审计：request_id 索引与批次",
      "req-test" in snap["by_request"]
      and snap["by_request"]["req-test"]["questions"] == 9
      and snap["by_request"]["req-test"]["latency_ms_total"] >= 0)
_audit_text = json.dumps(snap, ensure_ascii=False)
check("审计快照不含明文凭据", "test-only" not in _audit_text
      and "api_key" not in _audit_text and "state" not in _audit_text)
check("门控状态副本不含明文凭据",
      "test-only" not in json.dumps(cache_client.status))
check("非 shadow 不启用缓存",
      not DecisionClient(dict(BASE, decision_enabled=True, decision_mode="off"),
                         opener=counting_open).cache_enabled)


# ---- 七类异常注入回退：输出 = 原规则 + degraded 审计 ----
audit_reset()


def _raise_open(exc):
    def _open(request, timeout):
        raise exc
    return _open


def _body_open(payload):
    def _open(request, timeout):
        return io.BytesIO(payload)
    return _open


_http429 = urllib.error.HTTPError(
    TOKEN_PLAN + "/systemone", 429, "Too Many Requests", {},
    io.BytesIO(b'{"error":"rate limited"}'))
_bad_prob = copy.deepcopy(official)
_bad_prob["answers"]["c"]["probabilities"] = {"a": 0.9, "b": 0.3}
_error_cases = [
    ("断网", _raise_open(urllib.error.URLError(OSError("connection refused"))),
     "network"),
    ("429限流", _raise_open(_http429), "ratelimit"),
    ("畸形JSON", _body_open(b"{not-json"), "protocol"),
    ("越界概率", _body_open(json.dumps(_bad_prob).encode("utf-8")), "protocol"),
    ("超时", _raise_open(TimeoutError("模拟连接超时")), "network"),
]
for _name, _opener_fn, _expect in _error_cases:
    _v, _d = voiceprint_fixture()
    _before = copy.deepcopy(_v)
    _ec = DecisionClient(dict(BASE, decision_enabled=True), opener=_opener_fn)
    _caught = None
    try:
        # 完整 questions：确保「越界概率」在 c 选项上真实触发协议校验失败
        _ec.decide({"business": "injection-%s" % _name}, questions)
    except DecisionError as _exc:
        _caught = _exc
    check("异常注入[%s] 分类附着与归类=%s" % (_name, _expect),
          _caught is not None and getattr(_caught, "category", "") == _expect
          and classify_error(_caught) == _expect)
    _s = apply_shadow(_v, _d, _ec, threshold=0.55, low=0.45)
    check("异常注入[%s] verdict 不变（原规则输出）" % _name, _v == _before)
    check("异常注入[%s] degraded 审计" % _name, len(_s["errors"]) == 1
          and _s["evaluated"] == 0 and _d[1]["jev"]["status"] == "degraded")
    check("异常注入[%s] 分类计入聚合审计" % _name,
          audit_summary()["errors"].get(_expect, 0) >= 2)

# ---- 门控类异常注入（region_mismatch / missing_key）：零请求原规则输出 ----
for _name, _over, _reason in (
        ("region_mismatch", {"decision_key_region": "ap-southeast-1"},
         "region_mismatch"),
        ("missing_key(R1)", {"decision_require_own_key": True},
         "missing_decision_key")):
    _v, _d = voiceprint_fixture()
    _before = copy.deepcopy(_v)
    _gc = DecisionClient(dict(BASE, decision_enabled=True, **_over))
    _s = apply_shadow(_v, _d, _gc, threshold=0.55, low=0.45)
    check("门禁异常[%s] 零请求原规则输出" % _name,
          _v == _before and _s["evaluated"] == 0 and _s["requests"] == 0
          and not _s["active"] and _s["reason"] == _reason)
    check("门禁异常[%s] 明细无 jev 证据" % _name, "jev" not in _d[1])

# ---- 缓存目录清理（临时目录，不入库不残留）----
os.environ.pop("VT_DECISION_CACHE_DIR", None)
shutil.rmtree(_CACHE_TMP, ignore_errors=True)

print("\n%d PASS / %d FAIL" % (PASS, FAIL))
raise SystemExit(1 if FAIL else 0)
