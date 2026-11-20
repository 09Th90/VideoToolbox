# -*- coding: utf-8 -*-
# @version 3.1.3
"""Jev 校准判定集离线评测（真实 Token Plan 请求）。

用法：
  tools\\python\\python.exe scripts\\dev\\eval_jev_calib.py --split eval --variant baseline,evidence
  tools\\python\\python.exe scripts\\dev\\eval_jev_calib.py --dry-run --split train --limit 40
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
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tools.ai_client import load_config  # noqa: E402
from tools.decision_client import DecisionClient, DecisionError  # noqa: E402
from calib_entity import spec as spec_mod  # noqa: E402
from features.calibrate.calib_decision import build_request  # noqa: E402


def load_cases(path: str, split: str, limit: int = 0) -> list:
    cases = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            case = json.loads(line)
            if split != "all" and case.get("split") != split:
                continue
            cases.append(case)
    return cases[:limit] if limit else cases


def _div(a, b):
    return (a / b) if b else None


def _r(value):
    return round(value, 4) if value is not None else None


def _bin(conf):
    if conf >= 0.95:
        return ">=0.95"
    if conf >= 0.90:
        return "0.90-0.95"
    if conf >= 0.80:
        return "0.80-0.90"
    if conf >= 0.60:
        return "0.60-0.80"
    return "<0.60"


def metrics(rows, threshold=0.80):
    total = len(rows)
    correct = sum(1 for r in rows if r["choice"] == r["expected"])
    routes = Counter(r["choice"] for r in rows)
    pos = [r for r in rows if r["expected"] == "consistent"]
    neg = [r for r in rows if r["expected"] == "questionable"]
    predicted_pos = [r for r in rows if r["choice"] == "consistent"]
    high_pos = [r for r in predicted_pos if r["confidence"] >= threshold]
    bins = defaultdict(lambda: [0, 0])
    for r in rows:
        b = bins[_bin(r["confidence"])]
        b[0] += 1
        b[1] += 1 if r["choice"] == r["expected"] else 0
    return {
        "cases": total,
        "accuracy": _r(_div(correct, total)),
        "routes": dict(routes),
        "positive_count": len(pos),
        "negative_count": len(neg),
        "positive_recall": _r(_div(sum(1 for r in pos if r["choice"] == "consistent"), len(pos))),
        "negative_intercept_rate": _r(_div(sum(1 for r in neg if r["choice"] != "consistent"), len(neg))),
        "consistent_precision": _r(_div(sum(1 for r in predicted_pos if r["expected"] == "consistent"), len(predicted_pos))),
        "consistent_coverage": _r(_div(len(predicted_pos), total)),
        "high_conf_consistent_count": len(high_pos),
        "high_conf_consistent_precision": _r(
            _div(sum(1 for r in high_pos if r["expected"] == "consistent"), len(high_pos))),
        "manual_rate": _r(_div(routes.get("manual_review", 0), total)),
        "confidence_bins": {k: {"n": v[0], "acc": _r(_div(v[1], v[0]))}
                            for k, v in bins.items()},
    }


def _record(case, answer, response, risk_threshold=0.5):
    atype = answer.get("type")
    if atype == "noul":
        risk = float(answer["noul"])
        choice = "questionable" if risk >= risk_threshold else "consistent"
        confidence = max(risk, 1.0 - risk)
    elif answer.get("choice") in ("accept", "reject"):
        choice = "consistent" if answer["choice"] == "accept" else "questionable"
        confidence = float(answer["confidence"])
        risk = 1.0 - confidence if choice == "consistent" else confidence
    else:
        choice = answer["choice"]
        confidence = float(answer["confidence"])
        risk = 1.0 - confidence if choice == "consistent" else confidence
    return {
        "id": case["id"], "expected": case["expected"], "choice": choice,
        "confidence": confidence, "answer_type": atype, "risk": risk,
        "probabilities": dict(answer.get("probabilities") or {}),
        "work": case.get("work", ""), "kind": case.get("kind", ""),
        "pair": case.get("pair", ""), "old": case["old"], "new": case["new"],
        "request_id": response.get("request_id", ""),
    }


def run_variant(cases, variant, client, registry, batch_size=8, threshold=0.80,
                risk_threshold=0.5):
    rows, errors = [], []
    for offset in range(0, len(cases), batch_size):
        batch = cases[offset:offset + batch_size]
        changes = [(i + 1, c["old"], c["new"], c["why"], bool(c.get("soft"))) for i, c in enumerate(batch)]
        state, questions, items = build_request(changes, registry, variant=variant)
        try:
            response = client.decide(state, questions)
            for case, item in zip(batch, items):
                answer = response["answers"][item["question"]]
                rows.append(_record(case, answer, response, risk_threshold))
        except Exception as exc:  # noqa: BLE001
            errors.append({"offset": offset, "count": len(batch),
                           "error": "%s: %s" % (type(exc).__name__, str(exc)[:240])})
            break
    report = metrics(rows, threshold)
    report["variant"] = variant
    report["errors"] = errors
    report["by_work"] = {}
    for w in sorted({r["work"] for r in rows}):
        report["by_work"][w or "(未标注)"] = metrics([r for r in rows if r["work"] == w], threshold)
    report["items"] = rows
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Jev 校准判定集离线评测")
    ap.add_argument("--cases", default="data/entities/jev_calib_cases.jsonl")
    ap.add_argument("--split", choices=("train", "eval", "all"), default="eval")
    ap.add_argument("--variant", default="evidence",
                    help="baseline / evidence / baseline,evidence")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--threshold", type=float, default=0.80)
    ap.add_argument("--risk-threshold", type=float, default=0.5,
                    help="noul/风险概率转为 questionable 的阈值")
    ap.add_argument("--out", default="")
    ap.add_argument("--dry-run", action="store_true", help="只构造请求并检查证据覆盖，不发 API")
    args = ap.parse_args(argv)

    cases = load_cases(args.cases, args.split, args.limit)
    if not cases:
        ap.error("没有匹配的评测样本")
    variants = [v.strip() for v in args.variant.split(",") if v.strip()]
    registry = spec_mod.build_registry(spec_mod.load_engine())

    if args.dry_run:
        for variant in variants:
            state, _questions, items = build_request(
                [(i + 1, c["old"], c["new"], c["why"], bool(c.get("soft")))
                 for i, c in enumerate(cases)], registry, variant=variant)
            ev = [item.get("evidence", {}) for item in items]
            counts = Counter((x or {}).get("status", "none") for x in ev)
            print(json.dumps({"variant": variant, "cases": len(cases),
                              "evidence": dict(counts),
                              "prompt_bytes": len(json.dumps(state, ensure_ascii=False).encode("utf-8"))},
                             ensure_ascii=False, indent=2))
        return 0

    cfg = load_config()
    client = DecisionClient(cfg)
    if not client.active:
        print(json.dumps({"error": "Jev 门控未激活", "status": client.status},
                         ensure_ascii=False, indent=2))
        return 2
    reports = {}
    for variant in variants:
        report = run_variant(cases, variant, client, registry, args.batch_size,
                             args.threshold, args.risk_threshold)
        reports[variant] = report
        print(json.dumps({k: v for k, v in report.items()
                          if k not in ("items", "by_work", "confidence_bins")},
                         ensure_ascii=False, indent=2))
    payload = {"split": args.split, "cases": len(cases), "threshold": args.threshold,
               "risk_threshold": args.risk_threshold, "variants": reports}
    out = args.out or os.path.join(ROOT, "data", "entities",
                                   "jev_calib_eval_%s.json" % args.split)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("报告：%s" % out)
    return 0 if not any(r["errors"] for r in reports.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
