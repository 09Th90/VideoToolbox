# -*- coding: utf-8 -*-
# @version 3.2.5
"""WP4：Jev 生成前分诊门禁离线回放（不联网；架构骨架，G0 数据后期投喂）。

对照（与 eval_jev_mention_gate.py 同范式，决策对象从 R 收缩换成 skip/consult）：
  * A 本地闸门 alone：calib_triage_decision._gate_route_triage 的 skip/consult
    决策（zero_issue / anchorable_verified → skip；round_no>1 / 块太小 /
    跨作品冲突 / 缺官方名 → consult）。
  * B 本地 + Jev 分诊：仅对「A 判 skip」的块允许 Jev 纠错——jev_general=yes
    （或低置信 no）时改回 consult（保守方向，防漏改）；**永不把 consult 改成
    skip**（保守不可逆）。A 判 consult 的块恒 consult。

指标：missed_changes（skip 但 truth=needs_generative 的漏改块数）/
wasted_consults（consult 但 truth=skippable 的白跑块数）/ skip_precision /
binary accuracy + confidence 分箱。阈值扫 0.50/0.60/0.70/0.80。

判定（全过才允许分诊门禁脱离影子；否则继续影子）：
  * J1  加 Jev 后漏改 ≤ 本地闸门 alone（安全护栏）；
  * J3  confidence 分箱正确率单调正相关 + 高置信桶 precision≥0.85 且样本≥10；
  * R   近随机护栏：B 决策与 ground truth 一致率 ≤ 0.55 → 不启用。

数据集：data/entities/jev_triage_cases.jsonl（由 build_jev_triage_dataset.py
从留出片源收集，ground truth = 跳过后 verify+learn+人工 diff 漏改）。
**架构就位，不跑真实门禁验证**（G0 数据后期投喂）。

用法：
  tools\\python\\python.exe scripts\\dev\\eval_jev_triage_gate.py --self-test
  tools\\python\\python.exe scripts\\dev\\eval_jev_triage_gate.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

THRESHOLDS = (0.50, 0.60, 0.70, 0.80)
#: 近随机护栏：一致率不超过该值视为「近随机」，不启用门禁
RANDOM_GUARD_ACC = 0.55
#: J3 高置信桶阈值与样本下限
HIGH_CONF_THRESHOLD = 0.80
HIGH_CONF_MIN_N = 10
HIGH_CONF_MIN_PRECISION = 0.85

GROUND_TRUTHS = ("skippable", "needs_generative")


# ---------------------------------------------------------------- 数据加载


def load_cases(path):
    """读分诊评测 jsonl：每行一个块级 case。"""
    cases = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                c = json.loads(line)
                cases[c["id"]] = c
    return cases


# ---------------------------------------------------------------- A/B 决策


def replay_case(case, theta):
    """单 case 回放，返回 A/B 决策与判定要素。

    B 的 Jev 纠错方向（保守不可逆）：A=skip 时——jev_general=yes → 改 consult；
    jev_general=no 且 confidence≥θ → 保持 skip；jev_general=no 且 confidence<θ
    → 保守改 consult。A=consult 恒 consult。
    """
    gate_local = str(case.get("gate_local") or "")
    decision_a = "skip" if gate_local == "skip_generative" else "consult"
    conf = _conf_of(case)
    decision_b = decision_a
    jev_shrunk = False
    if decision_a == "skip":
        jev_general = str(case.get("jev_general") or "")
        if jev_general == "yes":
            decision_b = "consult"
            jev_shrunk = True
        elif jev_general == "no" and conf is not None and conf >= theta:
            decision_b = "skip"          # Jev 高置信确认
        else:
            decision_b = "consult"       # 低置信/缺答 → 保守不跳过
            jev_shrunk = True
    truth = str(case.get("ground_truth") or "")
    correct = (decision_b == "skip") == (truth == "skippable")
    return {
        "id": case.get("id"), "source": case.get("source"),
        "block": case.get("block"), "truth": truth,
        "decision_a": decision_a, "decision_b": decision_b,
        "gate_local": gate_local,
        "gate_reason_local": case.get("gate_reason_local") or "",
        "jev_general": str(case.get("jev_general") or ""),
        "confidence": conf, "jev_shrunk": jev_shrunk,
        "correct": correct,
        "gold_status": case.get("gold_status") or "",
    }


def _conf_of(case):
    try:
        v = case.get("jev_confidence")
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def metrics(decisions, key="decision_b"):
    """A/B 决策指标（漏改/白跑/精确率/一致率）。"""
    total = len(decisions)
    if not total:
        return {"cases": 0}
    skipped = [d for d in decisions if d[key] == "skip"]
    consulted = [d for d in decisions if d[key] == "consult"]
    missed = sum(1 for d in decisions
                 if d[key] == "skip" and d["truth"] == "needs_generative")
    wasted = sum(1 for d in decisions
                 if d[key] == "consult" and d["truth"] == "skippable")
    correct = sum(1 for d in decisions
                  if (d[key] == "skip") == (d["truth"] == "skippable"))
    return {
        "cases": total,
        "skipped_blocks": len(skipped),
        "consulted_blocks": len(consulted),
        "missed_changes": missed,
        "wasted_consults": wasted,
        "skip_precision": round(1.0 - missed / len(skipped), 4)
        if skipped else None,
        "binary_accuracy": round(correct / total, 4),
        "correct_skips": len(skipped) - missed,
    }


# ---------------------------------------------------------------- 判定


def judge_j1(m_a, m_b):
    """J1 安全护栏：加 Jev 后漏改 ≤ 本地闸门 alone。

    correct_skips 只作观测（Jev 保守纠错天然会把部分正确 skip 改成
    wasted consult——那是收益侧代价，不是安全问题，不参与 pass）。
    """
    a_missed = m_a.get("missed_changes")
    b_missed = m_b.get("missed_changes")
    return {
        "missed_changes": {"A": a_missed, "B": b_missed,
                           "pass": (b_missed is not None
                                    and a_missed is not None
                                    and b_missed <= a_missed)},
        "correct_skips_observed": {"A": m_a.get("correct_skips"),
                                   "B": m_b.get("correct_skips")},
        "pass": None,
    }


def _finish_j1(j1):
    j1["pass"] = all(v["pass"] for k, v in j1.items()
                     if k != "pass" and isinstance(v, dict) and "pass" in v)
    return j1


def judge_j3(decisions):
    """J3：confidence 分箱正确率单调正相关 + 高置信桶 precision≥0.85 且 n≥10。"""
    det = [d for d in decisions
           if d.get("confidence") is not None
           and str(d.get("gold_status") or "human_confirmed") != "pending_human"]
    order = ["<0.60", "0.60-0.80", "0.80-0.90", "0.90-0.95", ">=0.95"]

    def bin_of(c):
        if c >= 0.95:
            return ">=0.95"
        if c >= 0.90:
            return "0.90-0.95"
        if c >= 0.80:
            return "0.80-0.90"
        if c >= 0.60:
            return "0.60-0.80"
        return "<0.60"

    bins = defaultdict(lambda: [0, 0])
    for d in det:
        b = bins[bin_of(float(d["confidence"]))]
        b[0] += 1
        b[1] += 1 if d.get("correct") else 0
    table = {o: {"n": bins[o][0], "acc": round(bins[o][1] / bins[o][0], 4)}
             for o in order if bins[o][0]}
    seq = [(k, table[k]["acc"], table[k]["n"]) for k in order if k in table]
    # 单调：非降（允许并列）；只在样本≥10 的相邻桶之间要求严格不降
    monotone = True
    prev = None
    for _k, acc, n in seq:
        if n >= 10:
            if prev is not None and acc < prev - 1e-9:
                monotone = False
            prev = acc if prev is None else max(prev, acc)
    high = [d for d in det if float(d["confidence"]) >= HIGH_CONF_THRESHOLD]
    hp = round(sum(1 for d in high if d.get("correct")) / len(high), 4) \
        if high else None
    return {"bins": table, "monotone": monotone,
            "high_conf_bucket": {"threshold": HIGH_CONF_THRESHOLD,
                                 "n": len(high), "precision": hp},
            "pass": bool(monotone and hp is not None
                         and hp >= HIGH_CONF_MIN_PRECISION
                         and len(high) >= HIGH_CONF_MIN_N)}


def judge_random_guard(m_b):
    """近随机护栏：B 决策与 ground truth 一致率 ≤ 0.55 → 不启用。"""
    acc = m_b.get("binary_accuracy")
    return {"binary_accuracy": acc, "threshold": RANDOM_GUARD_ACC,
            "pass": acc is not None and acc > RANDOM_GUARD_ACC}


def eval_cases(cases, theta):
    """全量回放 + A/B 指标 + 三项判定。"""
    decisions = [replay_case(c, theta) for c in cases.values()]
    gold_det = [d for d in decisions
                if str(d.get("gold_status") or "human_confirmed")
                != "pending_human"]
    m_a = metrics(gold_det, key="decision_a")
    m_b = metrics(gold_det, key="decision_b")
    j1 = _finish_j1(judge_j1(m_a, m_b))
    j3 = judge_j3(decisions)
    rg = judge_random_guard(m_b)
    j_pass = {"J1": j1["pass"], "J3": j3["pass"], "random_guard": rg["pass"]}
    all_pass = all(v is True for v in j_pass.values())
    verdict = ("放行：分诊门禁可脱离影子（按 B 决策口径）" if all_pass
               else "继续影子（shadow-only）：判定未全过")
    return {
        "theta": theta,
        "route_distribution": dict(Counter(d["decision_b"] for d in decisions)),
        "gate_reasons": dict(Counter(d["gate_reason_local"] for d in decisions)),
        "jev_shrunk": sum(1 for d in decisions if d["jev_shrunk"]),
        "local_alone_A": m_a, "local_plus_jev_B": m_b,
        "J1": j1, "J3": j3, "random_guard": rg,
        "J_pass": j_pass, "verdict": verdict,
    }


# ---------------------------------------------------------------- mock 自测


def _self_test_cases():
    """内置 mock 数据集（零网络）：覆盖本地 skip 正确/错误、Jev 纠错/低置信。

    预期（B 决策口径）：missed=0（6 条本地误 skip 被 Jev 高置信纠错）、
    wasted=4（4 条正确 skip 被 Jev 低置信否决 → 保守 consult）、
    accuracy=0.90、高置信桶 n=36 precision=1.0。
    """
    cases = {}
    def add(cid, gate, reason, truth, jev_general, conf, gold="human_confirmed"):
        cases[cid] = {"id": cid, "source": "mock", "block": len(cases) + 1,
                      "cue_total": 24, "gate_local": gate,
                      "gate_reason_local": reason, "ground_truth": truth,
                      "jev_general": jev_general, "jev_confidence": conf,
                      "gold_status": gold}
    for i in range(20):    # 本地 skip 正确，Jev 高置信确认
        add("m%02d" % i, "skip_generative", "zero_issue", "skippable",
            "no", 0.95)
    for i in range(10):    # 本地 consult 正确（Jev 只能确认，不改 skip）
        add("c%02d" % i, "", "generative_consulted", "needs_generative",
            "yes", 0.95)
    for i in range(6):     # 本地误 skip，Jev 纠错（B 漏改减少）
        add("e%02d" % i, "skip_generative", "anchorable_verified",
            "needs_generative", "yes", 0.90)
    for i in range(4):     # 本地 skip 正确，Jev 低置信否决 → 保守 consult
        add("w%02d" % i, "skip_generative", "zero_issue", "skippable",
            "no", 0.50)
    return cases


def self_test() -> int:
    """--self-test：mock 数据全管线跑一遍，断言结构与关键数值（零网络）。"""
    cases = _self_test_cases()
    assert len(cases) == 40, "mock 数据集应为 40 条"
    result = eval_cases(cases, theta=0.80)
    m_a, m_b = result["local_alone_A"], result["local_plus_jev_B"]
    # A：本地闸门 6 处误 skip → 漏改 6；正确 skip 24（20 正确 + 4 条
    # Jev 低置信否决前本也正确）
    assert m_a["missed_changes"] == 6, "A missed=%r" % m_a["missed_changes"]
    assert m_a["correct_skips"] == 24, "A correct_skips=%r" % m_a["correct_skips"]
    assert m_a["wasted_consults"] == 0, "A wasted=%r" % m_a["wasted_consults"]
    # B：Jev 纠错后漏改 0；低置信否决 4 条 → 白跑 4
    assert m_b["missed_changes"] == 0, "B missed=%r" % m_b["missed_changes"]
    assert m_b["wasted_consults"] == 4, "B wasted=%r" % m_b["wasted_consults"]
    assert m_b["correct_skips"] == 20, "B correct_skips=%r" % m_b["correct_skips"]
    assert abs(m_b["binary_accuracy"] - 0.90) < 1e-6, \
        "B accuracy=%r" % m_b["binary_accuracy"]
    j1, j3, rg = result["J1"], result["J3"], result["random_guard"]
    assert j1["pass"] is True, "J1 应 PASS：%s" % json.dumps(j1)
    assert j3["pass"] is True, "J3 应 PASS：%s" % json.dumps(j3)
    assert j3["high_conf_bucket"]["n"] == 36, \
        "高置信桶 n=%r" % j3["high_conf_bucket"]["n"]
    assert rg["pass"] is True, "近随机护栏应 PASS"
    assert result["verdict"].startswith("放行"), result["verdict"]
    # 阈值扫描结构完整
    sweep = {("%.2f" % th): eval_cases(cases, th)["local_plus_jev_B"]
             for th in THRESHOLDS}
    assert set(sweep) == {"0.50", "0.60", "0.70", "0.80"}
    # 渲染层联动：summary→render_triage_section 幂等（影子链路结构自检）
    from features.calibrate.calib_triage_decision import (
        SCHEMA_VERSION, POLICY, render_triage_section)
    assert SCHEMA_VERSION == "vt.calibrate.triage.v1"
    assert POLICY["shadow_only"] is True
    lines = render_triage_section({"active": False, "mode": "off",
                                   "reason": "mode_off", "blocks_total": 0})
    assert lines[0].startswith("## 附：Jev 生成前分诊影子")
    assert render_triage_section({"active": False, "mode": "off",
                                  "reason": "mode_off", "blocks_total": 0}) \
        == lines, "渲染必须幂等"
    print(json.dumps({"self_test": "PASS", "cases": len(cases),
                      "A_missed": m_a["missed_changes"],
                      "B_missed": m_b["missed_changes"],
                      "B_accuracy": m_b["binary_accuracy"],
                      "verdict": result["verdict"]}, ensure_ascii=False))
    return 0


def dry_run(args) -> int:
    """--dry-run：检查数据文件与步骤计划，不执行真实回放写盘。"""
    cases_path = os.path.join(ROOT, args.cases)
    plan = {"schema": "jev-triage-gate-eval/1", "dry_run": True,
            "cases_file": args.cases, "cases_exists": os.path.isfile(cases_path),
            "out": args.out,
            "steps": [
                "load_cases(%s)" % args.cases,
                "for theta in %s: eval_cases(cases, theta)" % (THRESHOLDS,),
                "judge J1 / J3 / random_guard → verdict",
                "write %s" % args.out,
            ],
            "notes": [
                "G0 数据由 build_jev_triage_dataset.py 从留出片源收集后投喂；",
                "数据未投喂前正式判定恒为「继续影子」。",
            ]}
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Jev 生成前分诊离线门禁回放")
    ap.add_argument("--cases",
                    default="data/entities/jev_triage_cases.jsonl")
    ap.add_argument("--theta", type=float, default=0.80,
                    help="放行判定采用的置信阈值")
    ap.add_argument("--out",
                    default="data/entities/jev_triage_gate_eval.json")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--self-test", action="store_true",
                    help="内置 mock 数据全管线自测（零网络）")
    args = ap.parse_args(argv)

    if args.self_test:
        return self_test()
    if args.dry_run:
        return dry_run(args)

    cases_path = os.path.join(ROOT, args.cases)
    if not os.path.isfile(cases_path):
        print(json.dumps({"verdict": "待数据（G0 数据集未投喂）",
                          "cases_file": args.cases,
                          "note": "先运行 build_jev_triage_dataset.py 收集 "
                                  "R0 影子数据并回填 ground truth"},
                         ensure_ascii=False, indent=2))
        return 0
    cases = load_cases(cases_path)
    result = eval_cases(cases, theta=float(args.theta))
    payload = {
        "schema": "jev-triage-gate-eval/1",
        "mode": "offline_replay_no_network",
        "cases": len(cases),
        "theta": float(args.theta),
        **result,
        "notes": [
            "A=本地确定性闸门 alone（calib_triage_decision._gate_route_triage）；",
            "B 仅对 A 判 skip 的块允许 Jev 保守纠错（yes→consult；低置信 no→"
            "consult），永不把 consult 改成 skip。",
            "ground truth=跳过后 verify+learn+人工 diff 漏改；"
            "gold_status=pending_human 的 case 不计入正式判定。",
        ],
    }
    out = os.path.join(ROOT, args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(json.dumps({k: result[k] for k in
                      ("route_distribution", "local_alone_A",
                       "local_plus_jev_B", "J_pass", "verdict")},
                     ensure_ascii=False, indent=2)[:2600])
    print("回放报告：%s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
