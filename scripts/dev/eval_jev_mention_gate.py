# -*- coding: utf-8 -*-
# @version 3.3.1
"""包C-3：Jev mention 消歧离线系统级回放（不联网，读探针 JSON + 重跑 scope_state）。

对照：
  * A 本地规则 alone：生产 scope_state 口径——规则1（zh 序次交集恰 1）裁决；
    tb_fail 保守回退全 T；音乐/通用词-only 候选本地闸门直接拦（不进 Jev）。
  * B 本地 + Jev 收缩：**仅 tb_fail** 且 _substantive(T) 非空时取 Jev choice
    命中 T 内且 confidence ≥ θ → 收缩 R 至该候选；uncertain/低置信回退全 T；
    **永不扩到 T 外**。

指标：binary accuracy / 正例召回 / 负例拦截 / review rate / 漏改误改计数
（漏改误改用真实模式术语表模拟：zh 行实际含错形 w→right r，规则在 R 内即发）
+ confidence 分箱 + probabilities 区分度。阈值扫 0.50/0.60/0.70/0.80。

J1-J4 逐项判定（全过才允许 Jev 参与 R 裁决，只收缩 R；否则继续影子）：
  * J1  加 Jev 后正例召回/负例拦截/binary accuracy ≥ alone（安全护栏）；
  * J2  T2 子集 Jev 命中金标率 > 回退全 T 基线 且 误收缩漏改 ≤ 回退误改
        （**需 T2 人工金标；金标未回填前正式判定=待人工**）；
  * J3  confidence 分箱正确率单调正相关 + 高置信桶 precision≥0.85 且样本≥10；
  * J4  T3 假候选 uncertain 率 ≥ 0.8。

用法：
  tools\\python\\python.exe scripts\\dev\\eval_jev_mention_gate.py
  tools\\python\\python.exe scripts\\dev\\eval_jev_mention_gate.py --probe-file data/tmp/jev_mention_eval_mock.json --variant few-shot
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from calib_core.asr import _ref_for_match  # noqa: E402
from calib_core.mention import (build_maps, mode_terms, scope_state,  # noqa: E402
                                _is_generic, _is_music, longest_bounded,
                                _parent_tiebreak)

THRESHOLDS = (0.50, 0.60, 0.70, 0.80)
UNCERTAIN = "cannot_determine"


def _substantive(canon_list):
    """剔除音乐/通用词候选（与 calib_mention_decision._substantive 同口径）。"""
    return [c for c in canon_list
            if not (_is_music({c}) or _is_generic({c}))]


def load_cases(path):
    cases = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                c = json.loads(line)
                cases[c["id"]] = c
    return cases


def load_probe(path, variant):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    variants = data.get("variants") or {}
    if variant not in variants:
        raise SystemExit("探针文件缺少 variant=%s（现有：%s）"
                         % (variant, sorted(variants)))
    rep = variants[variant]
    rows = {}
    for r in rep.get("items") or []:
        rows[r["id"]] = r
    return rows, data


# ---------------------------------------------------------------- 引擎重放


def rerun_scope(mode, zh, ref):
    """逐 cue 重跑 scope_state。

    返回 (enabled, R, stats, rule1_targets, multi_targets)：
      rule1_targets：规则1/2 已裁决的目标集（A 口径下已收缩部分）；
      multi_targets：全部多目标 ref mention 的候选并集（含已裁决与 tb_fail）。
    """
    M = build_maps(mode)
    anchor = _ref_for_match(ref)
    enabled, R, st = scope_state(M, zh, anchor)
    rule1, multi = set(), set()
    if enabled:
        ref_ms = longest_bounded(M["ref_auto"], anchor.lower()) if anchor else []
        zh_ms = longest_bounded(M["zh_auto"], zh)
        for i, (_, _, _, rt) in enumerate(ref_ms):
            if len(rt) <= 1:
                continue
            multi |= set(rt)
            zt = set(zh_ms[i][3]) if i < len(zh_ms) else set()
            if len(rt & zt) == 1:
                rule1 |= (rt & zt)
            else:
                par = _parent_tiebreak(set(rt))
                if par:
                    rule1 |= {par}
    return enabled, R, dict(st or {}), rule1, multi


def wrongform_fire_map(mode, zh, T):
    """真实术语表模拟：zh 行实际含有的 T 内候选错形 {candidate: [wrong,...]}。

    语境正则条件近似为恒真（回放口径，报告注明）；right∉OBJ_CANONS 的语境规则
    不受 R 约束、A/B 恒同，不在决策域内，不计入漏改误改。
    """
    from calib_core.mention import OBJ_CANONS
    table = mode_terms(mode)
    out = defaultdict(list)
    low = zh  # 术语表错形键大小写敏感口径与引擎一致
    for wrong, right in table.items():
        if not wrong or not right or wrong == right:
            continue
        if right in OBJ_CANONS and right in set(T) and wrong in low:
            out[right].append(wrong)
    return dict(out)


# ---------------------------------------------------------------- A/B 决策


def replay_case(case, probe_row, theta):
    """单 case 回放，返回 A/B 决策与判定要素。

    路由（生产口径）：
      * rule1_resolved   多目标全被规则1/2 裁决 → A 已收缩，Jev 不参与；
      * jev_consulted    tb_fail 且 substantive(T) 非空 → A 回退全 T，B 可收缩；
      * pre_gated_no_jev 音乐/通用词-only 候选 → 本地闸门拦，Jev 不参与；
      * probe_only_declared 引擎未触发 scoping（T3 通用词声明式探针）→ A/B 全 T。
    """
    mode = case.get("mode") or "bi"
    zh, ref = case["zh"], case["ref"]
    T_case = list(case.get("T") or [])
    gold = case.get("gold") or ""
    enabled, _R_engine, stats, rule1, multi = rerun_scope(mode, zh, ref)
    engine_derived = bool(enabled) and set(multi) == set(T_case) and bool(T_case)
    T = sorted(multi) if engine_derived else list(T_case)
    substantive = _substantive(T)
    tb_fail = int((stats or {}).get("tb_fail", 0))

    if not enabled:
        route = "probe_only_declared"
        R_A_T = set(T)
    elif tb_fail > 0:
        if substantive:
            route = "jev_consulted"
            R_A_T = set(T)                      # tb_fail 保守回退全 T
        else:
            route = "pre_gated_no_jev"          # 音乐/通用词-only：本地闸门拦
            R_A_T = set(T)
    else:
        route = "rule1_resolved"
        R_A_T = set(rule1) & set(T) or set(rule1)

    # B 本地 + Jev 收缩（仅 jev_consulted；永不扩到 T 外）
    R_B_T = set(R_A_T)
    jev_shrunk = False
    if route == "jev_consulted" and probe_row and \
            probe_row.get("status") != "degraded":
        choice = probe_row.get("choice") or ""
        conf = float(probe_row.get("confidence") or 0.0)
        if choice in set(T) and choice != UNCERTAIN and conf >= theta:
            R_B_T = {choice}
            jev_shrunk = True
    # g_decision：gold ∈ T → 收缩到金标；gold 为空 → 保持全 T（不承诺）
    if gold and gold in set(T):
        g_decision = frozenset([gold])
    else:
        g_decision = frozenset(T)
    return {
        "route": route, "engine_derived": engine_derived,
        "T": T, "gold": gold, "R_A": R_A_T, "R_B": R_B_T,
        "g_decision": g_decision, "jev_shrunk": jev_shrunk,
        "stats": stats, "fire_map": wrongform_fire_map(mode, zh, T),
        "jev_choice": (probe_row or {}).get("choice", ""),
        "jev_confidence": float((probe_row or {}).get("confidence") or 0.0),
        "jev_probabilities": dict((probe_row or {}).get("probabilities") or {}),
        "tier": case.get("tier"), "label": case.get("label"),
        "pair": case.get("pair"), "gold_status": case.get("gold_status"),
        "synthetic": case.get("synthetic"), "mode": mode,
    }


def metrics(decisions):
    """A/B 对照指标（含漏改/误改模拟计数）。"""
    total = len(decisions)
    out = {"cases": total}
    for who, key in (("alone_A", "R_A"), ("with_jev_B", "R_B")):
        bin_correct = sum(1 for d in decisions if d[key] == d["g_decision"])
        pos = [d for d in decisions if d["gold"] and d["gold"] in set(d["T"])]
        neg = [d for d in decisions if not d["gold"]]
        recall = sum(1 for d in pos if d["gold"] in d[key]) if pos else None
        intercept = sum(1 for d in neg if d[key] == d["g_decision"]) \
            if neg else None
        review = sum(1 for d in decisions if d[key] == frozenset(d["T"]))
        missed = wrong = 0
        missed_ids, wrong_ids = [], []
        for d in decisions:
            R = d[key]
            for cand, wrongs in d["fire_map"].items():
                should = (cand == d["gold"] and d["gold"] != "")
                fires = cand in R
                if should and not fires:
                    missed += 1
                    missed_ids.append(d["id"])
                if not should and fires:
                    wrong += 1
                    wrong_ids.append(d["id"])
        out[who] = {
            "binary_accuracy": round(bin_correct / total, 4) if total else None,
            "positive_recall": round(recall / len(pos), 4) if pos else None,
            "negative_intercept": round(intercept / len(neg), 4) if neg else None,
            "review_rate": round(review / total, 4) if total else None,
            "missed_changes": missed, "wrong_changes": wrong,
        }
    routes = Counter(d["route"] for d in decisions)
    out["routes"] = dict(routes)
    out["jev_shrunk"] = sum(1 for d in decisions if d["jev_shrunk"])
    return out


# ---------------------------------------------------------------- J1-J4


def judge_j1(m_all, m_b, gold_decisions):
    """J1：加 Jev 后（B）正例召回/负例拦截/binary accuracy ≥ alone（A）。"""
    checks = {}
    for k in ("positive_recall", "negative_intercept", "binary_accuracy"):
        a, b = m_all[k], m_b[k]
        checks[k] = {"A": a, "B": b, "pass": (b is not None and a is not None
                                              and b + 1e-9 >= a)}
    checks["pass"] = all(v["pass"] for v in checks.values())
    checks["population"] = "gold-determined %d cases" % gold_decisions
    return checks


def judge_j2(decisions, checklist_path, probe_rows=None):
    """J2：T2 子集 Jev 命中金标率 > 回退全 T 基线 且 误收缩漏改 ≤ 回退误改。

    T2 金标为 pending_human 时正式判定=待人工；给出非定性观测供标注参考
    （观测用原始提交口径，不看置信阈值）。
    """
    t2_pending = [d for d in decisions
                  if d["tier"] == "T2" and d["gold_status"] == "pending_human"]
    committed = []
    for d in t2_pending:
        row = (probe_rows or {}).get(d["id"]) or {}
        choice = row.get("choice") or ""
        if choice and choice != UNCERTAIN and choice in set(d["T"]):
            committed.append({"id": d["id"], "choice": choice,
                              "confidence": row.get("confidence")})
    obs = {
        "t2_pending_cases": len(t2_pending),
        "jev_committed_count_raw": len(committed),
        "jev_committed_rate_raw": round(len(committed) / len(t2_pending), 4)
        if t2_pending else None,
        "mean_confidence_when_committed": round(
            sum(c["confidence"] for c in committed) / len(committed), 4)
        if committed else None,
        "note": "提交不等于正确：金标回填前无法评价命中率；这些提交可作为"
                "人工标注优先复核项",
    }
    human = [d for d in decisions
             if d["tier"] == "T2" and d["gold_status"] == "human_confirmed"]
    if human:
        pos = [d for d in human if d["gold"] in set(d["T"])]
        hit = sum(1 for d in pos if d["R_B"] == frozenset([d["gold"]]))
        baseline = 1.0 / max(len(pos[0]["T"]), 1) if pos else 0.0
        a_missed = sum(1 for d in pos for c, ws in d["fire_map"].items()
                       if c == d["gold"] and c not in d["R_A"])
        b_missed = sum(1 for d in pos for c, ws in d["fire_map"].items()
                       if c == d["gold"] and c not in d["R_B"])
        return {"status": "judged", "human_gold_cases": len(human),
                "jev_hit_rate": round(hit / len(pos), 4) if pos else None,
                "fallback_baseline": round(baseline, 4),
                "hit_beats_baseline": hit / len(pos) > baseline if pos else False,
                "B_missed": b_missed, "A_wrong_or_missed": a_missed,
                "pass": (hit / len(pos) > baseline and b_missed <= a_missed)
                if pos else False}
    return {"status": "待人工金标（不满足放行条件）",
            "checklist": checklist_path,
            "note": "T2 全部 gold_status=pending_human；人工回填前 J2 无法定性，"
                    "J1-J4 全过才允许参与 R 裁决的判据因此未满足",
            "observation_non_qualifying": obs}


def judge_j3(rows):
    """J3：confidence 分箱正确率单调正相关 + 高置信桶 precision≥0.85 且样本≥10。"""
    det = [r for r in rows if r.get("gold_status") == "mechanical"]
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
    for r in det:
        b = bins[bin_of(float(r.get("confidence") or 0.0))]
        b[0] += 1
        b[1] += 1 if r.get("correct") else 0
    table = {}
    for o in order:
        if bins[o][0]:
            table[o] = {"n": bins[o][0],
                        "acc": round(bins[o][1] / bins[o][0], 4)}
    seq = [(k, table[k]["acc"], table[k]["n"]) for k in order if k in table]
    # 单调：非降（允许并列）；只在样本≥10 的相邻桶之间要求严格不降
    monotone = True
    prev = None
    for _k, acc, n in seq:
        if n >= 10:
            if prev is not None and acc < prev - 1e-9:
                monotone = False
            prev = acc if prev is None else max(prev, acc)
    high = [r for r in det if float(r.get("confidence") or 0.0) >= 0.80]
    hp = round(sum(1 for r in high if r.get("correct")) / len(high), 4) \
        if high else None
    return {"bins": table, "monotone": monotone,
            "high_conf_bucket": {"threshold": 0.80, "n": len(high),
                                 "precision": hp},
            "pass": bool(monotone and hp is not None and hp >= 0.85
                         and len(high) >= 10)}


def judge_j4(rows):
    """J4：T3 假候选 uncertain 率 ≥ 0.8。"""
    t3 = [r for r in rows if r.get("tier") == "T3"
          and r.get("status") != "degraded"]
    unc = sum(1 for r in t3 if r.get("choice") == UNCERTAIN)
    rate = round(unc / len(t3), 4) if t3 else None
    return {"t3_cases": len(t3), "uncertain_rate": rate,
            "pass": rate is not None and rate >= 0.8}


def eval_variant(cases, probe_rows, probe_items, variant, checklist_path):
    """单变体完整回放 + J1-J4 判定。"""
    probe_rows_by_id = probe_rows

    decisions = []
    for cid, case in cases.items():
        d = replay_case(case, probe_rows.get(cid), 0.80)
        d["id"] = cid
        decisions.append(d)
    gold_det = [d for d in decisions if d["gold_status"] == "mechanical"]
    m_all = metrics(gold_det)
    t2_pending = [d for d in decisions if d["tier"] == "T2"
                  and d["gold_status"] == "pending_human"]
    m_all_t2 = metrics(t2_pending) if t2_pending else {"cases": 0}

    thresholds = {}
    for theta in THRESHOLDS:
        dec_t = [replay_case(case, probe_rows.get(cid), theta)
                 for cid, case in cases.items()]
        thresholds["%.2f" % theta] = {
            "gold_determined": metrics([d for d in dec_t
                                        if d["gold_status"] == "mechanical"]),
            "t2_pending": metrics([d for d in dec_t if d["tier"] == "T2"
                                   and d["gold_status"] == "pending_human"]),
            "all_cases_incl_pending": metrics(dec_t),
        }

    j1 = judge_j1(m_all["alone_A"], m_all["with_jev_B"], len(gold_det))
    j2 = judge_j2(decisions, checklist_path, probe_rows_by_id)
    j3 = judge_j3(probe_items)
    j4 = judge_j4(probe_items)
    j_pass = {"J1": j1["pass"], "J2": j2.get("pass"),
              "J3": j3["pass"], "J4": j4["pass"]}
    all_pass = all(v is True for v in j_pass.values())
    conclusion = {
        "J1": ("PASS" if j1["pass"] else "FAIL") + "：" +
              json.dumps({k: v for k, v in j1.items()
                          if k in ("positive_recall", "negative_intercept",
                                   "binary_accuracy")}, ensure_ascii=False),
        "J2": ("待人工金标：清单已产出（%s），人工回填前无法定性 → 不满足"
               "「J1-J4 全过才放行」" % os.path.basename(checklist_path))
              if j2.get("status") != "judged" else
              ("PASS" if j2["pass"] else "FAIL"),
        "J3": ("PASS" if j3["pass"] else "FAIL") +
              "：分箱 %s；高置信桶(≥0.80) n=%d precision=%s" % (
                  "单调" if j3["monotone"] else "非单调",
                  j3["high_conf_bucket"]["n"],
                  j3["high_conf_bucket"]["precision"]),
        "J4": ("PASS" if j4["pass"] else "FAIL") +
              "：T3 uncertain 率 %s（%d 例）" % (j4["uncertain_rate"],
                                               j4["t3_cases"]),
    }
    verdict = ("放行：Jev 参与 R 裁决（只收缩 R）" if all_pass
               else "继续影子（shadow-only）：J1-J4 未全过%s" %
               ("；J2 待人工金标" if j2.get("status") != "judged" else ""))
    return {
        "variant": variant,
        "route_distribution": dict(Counter(d["route"] for d in decisions)),
        "engine_derived_cases": sum(1 for d in decisions
                                    if d["engine_derived"]),
        "A_vs_B_gold_determined": m_all,
        "A_vs_B_t2_pending": m_all_t2,
        "threshold_sweep": thresholds,
        "J1": j1, "J2": j2, "J3": j3, "J4": j4,
        "J_pass": j_pass, "conclusion": conclusion, "verdict": verdict,
        "probe_metrics": {k: v for k, v in (probe_meta_items(variant) or {})
                          .items() if k in ("accuracy", "positive_recall",
                                            "negative_refusal",
                                            "uncertain_rate",
                                            "confidence_bins")},
    }


_PROBE_META = {}


def probe_meta_items(variant):
    rep = (_PROBE_META.get("variants") or {}).get(variant) or {}
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Jev mention 离线系统级回放")
    ap.add_argument("--cases", default="data/entities/jev_mention_cases.jsonl")
    ap.add_argument("--probe-file",
                    default="data/entities/jev_mention_eval_all.json")
    ap.add_argument("--variant", default="baseline,few-shot",
                    help="逗号分隔；全部对照回放，verdict 取最后一个")
    ap.add_argument("--decision-variant", default="few-shot",
                    help="放行判定采用的变体（生产意图配置）")
    ap.add_argument("--checklist",
                    default="data/entities/jev_mention_t2_checklist.json")
    ap.add_argument("--out",
                    default="data/entities/jev_mention_gate_eval.json")
    args = ap.parse_args(argv)

    cases = load_cases(os.path.join(ROOT, args.cases))
    with open(os.path.join(ROOT, args.probe_file), encoding="utf-8") as f:
        probe_meta = json.load(f)
    _PROBE_META.update(probe_meta)
    checklist_path = os.path.join(ROOT, args.checklist)

    variants = [v.strip() for v in args.variant.split(",") if v.strip()]
    results = {}
    for variant in variants:
        probe_rows, _ = load_probe(os.path.join(ROOT, args.probe_file),
                                   variant)
        probe_items = (probe_meta.get("variants", {}).get(variant, {})
                       or {}).get("items") or []
        results[variant] = eval_variant(cases, probe_rows, probe_items,
                                        variant, checklist_path)

    chosen = results.get(args.decision_variant) or results[variants[-1]]
    verdict = chosen["verdict"]
    payload = {
        "schema": "jev-mention-gate-eval/1",
        "mode": "offline_replay_no_network",
        "probe_source": {"file": args.probe_file,
                         "mock": probe_meta.get("mock", False)},
        "cases": len(cases),
        "gold_determined_cases": sum(
            1 for c in cases.values()
            if c.get("gold_status") == "mechanical"),
        "decision_variant": args.decision_variant,
        "variants": results,
        "conclusion": chosen["conclusion"],
        "verdict": verdict,
        "notes": [
            "漏改/误改模拟：真实模式术语表逐 case 扫 zh 行错形，right∈决策域 T 的"
            "对象规则按 R 是否包含 right 判定发/不发；语境正则近似恒真（回放口径）。",
            "J2 需要 T2 人工金标：清单已产出待回填；回填后把 cases.jsonl 对应条目 "
            "gold_status 改为 human_confirmed 再重跑本脚本即可得到正式判定。",
            "A=生产本地规则（规则1 裁决 / tb_fail 回退全 T / 音乐通用词-only 本地拦）；"
            "B 仅在 tb_fail 且 substantive 候选非空时按 Jev 收缩，永不扩到 T 外。",
        ],
    }
    out = os.path.join(ROOT, args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    for variant, res in results.items():
        print("== variant=%s ==" % variant)
        print(json.dumps({k: res[k] for k in
                          ("route_distribution", "A_vs_B_gold_determined",
                           "J_pass", "verdict")}, ensure_ascii=False,
                         indent=2)[:2600])
    print("结论（decision_variant=%s）：%s" % (args.decision_variant, verdict))
    print(json.dumps(chosen["conclusion"], ensure_ascii=False, indent=2))
    print("回放报告：%s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
