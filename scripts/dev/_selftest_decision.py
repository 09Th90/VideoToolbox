# -*- coding: utf-8 -*-
# @version 3.1.5
"""Jev / System One 门控、协议与影子不改写自检（全部使用模拟响应，不联网）。"""
import copy
import io
import json
import os
import sys
import tempfile
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "src"))

from tools.decision_client import (DecisionClient, DecisionError, DecisionUnavailable,
                                   availability, systemone_url, validate_response)
from tools.ai_client import DEFAULT_CONFIG
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

print("\n%d PASS / %d FAIL" % (PASS, FAIL))
raise SystemExit(1 if FAIL else 0)
