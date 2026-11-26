# -*- coding: utf-8 -*-
# @version 3.3.1
"""本地证据闸门 + Jev 风险分数的系统级离线评估（不调用 API）。

输入：
  data/entities/jev_calib_cases.jsonl
  data/entities/jev_calib_eval_fewshot.json      （eval 的 noul few-shot 结果）
  data/entities/jev_calib_eval_train.json        （train 的 noul few-shot 结果）
输出：
  data/entities/jev_calib_gate_eval.json

用途：验证「本地证据闸门先拦目标冲突/非最小替换，Jev 只复核干净替换」能否
在不自动改写字幕的前提下，把可自动放行的 precision 提到可用水平。
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

from calib_entity import spec as spec_mod  # noqa: E402
from features.calibrate.calib_evidence import build_evidence  # noqa: E402


def load_cases(path, split):
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            c = json.loads(line)
            if c.get("split") == split:
                out[c["id"]] = c
    return out


def gate_route(evidence):
    status = (evidence or {}).get("status")
    if status == "conflict":
        return "questionable", "target_conflict"
    if status == "missing":
        return "manual_review", "evidence_missing"
    if not (evidence or {}).get("clean_replacement"):
        return "manual_review", "not_clean_replacement"
    return "", ""


def metrics(rows):
    total = len(rows)
    pred_pos = [r for r in rows if r["choice"] == "consistent"]
    pos = [r for r in rows if r["expected"] == "consistent"]
    neg = [r for r in rows if r["expected"] == "questionable"]
    binary_correct = sum(1 for r in rows
                         if (r["choice"] == "consistent") == (r["expected"] == "consistent"))
    return {
        "cases": total,
        "accuracy": round(sum(1 for r in rows if r["choice"] == r["expected"]) / total, 4),
        "binary_accuracy": round(binary_correct / total, 4),
        "routes": dict(Counter(r["choice"] for r in rows)),
        "positive_recall": round(sum(1 for r in pos if r["choice"] == "consistent") / len(pos), 4),
        "negative_intercept_rate": round(sum(1 for r in neg if r["choice"] != "consistent") / len(neg), 4),
        "consistent_precision": round(sum(1 for r in pred_pos if r["expected"] == "consistent") / len(pred_pos), 4),
        "consistent_coverage": round(len(pred_pos) / total, 4),
        "review_rate": round(1 - len(pred_pos) / total, 4),
        "gated_total": sum(1 for r in rows if r["gate"]),
        "gated_positive": sum(1 for r in rows if r["gate"] and r["expected"] == "consistent"),
        "gated_negative": sum(1 for r in rows if r["gate"] and r["expected"] == "questionable"),
    }


def main():
    cases_path = os.path.join(ROOT, "data", "entities", "jev_calib_cases.jsonl")
    registry = spec_mod.build_registry(spec_mod.load_engine())
    payload = {"schema": "jev-calib-gate-eval/1", "splits": {}}
    for split, report_name in (("eval", "jev_calib_eval_fewshot.json"),
                               ("train", "jev_calib_eval_train.json")):
        cases = load_cases(cases_path, split)
        report_path = os.path.join(ROOT, "data", "entities", report_name)
        if not os.path.exists(report_path):
            payload["splits"][split] = {"error": "缺少 %s" % report_name}
            continue
        items = {}
        with open(report_path, encoding="utf-8") as f:
            data = json.load(f)
        variant = data["variants"]["evidence_text_noul_fewshot"]
        for row in variant["items"]:
            items[row["id"]] = row

        base_rows = []
        for cid, case in cases.items():
            ev = build_evidence(case["old"], case["new"], case["why"], registry)
            gate, why = gate_route(ev)
            base_rows.append({"id": cid, "expected": case["expected"],
                              "gate": why, "evidence_status": ev.get("status"),
                              "clean_replacement": bool(ev.get("clean_replacement")),
                              "risk": (items.get(cid) or {}).get("risk")})
        thresholds = {}
        for t in (0.50, 0.55, 0.60, 0.65, 0.70, 0.75):
            rows = []
            for r in base_rows:
                if r["gate"]:
                    choice = "questionable" if r["gate"] == "target_conflict" else "manual_review"
                else:
                    choice = "questionable" if (r["risk"] or 0) >= t else "consistent"
                rows.append({"expected": r["expected"], "choice": choice, "gate": r["gate"]})
            thresholds["%.2f" % t] = metrics(rows)
        local_rows = []
        for r in base_rows:
            if r["gate"]:
                choice = "questionable" if r["gate"] == "target_conflict" else "manual_review"
            else:
                choice = "consistent"
            local_rows.append({"expected": r["expected"], "choice": choice, "gate": r["gate"]})
        payload["splits"][split] = {
            "cases": len(base_rows),
            "gate_reasons": dict(Counter(r["gate"] or "passed" for r in base_rows)),
            "local_gate_only": metrics(local_rows),
            "with_jev": thresholds,
        }
    out = os.path.join(ROOT, "data", "entities", "jev_calib_gate_eval.json")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print("报告：%s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
