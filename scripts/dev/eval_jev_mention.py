# -*- coding: utf-8 -*-
# @version 3.2.0
"""包C-2：Jev mention 消歧真实请求探针（decision-model-preview）。

复用包A（calib_mention_decision）的 build_mention_request / build_mention_evidence
问题构造与证据卡，对 jev_mention_cases.jsonl 逐批发 choice（T 内候选 +
cannot_determine）请求。批 ≤8（Jev 单请求上限 16 的一半，失败整批降级）。

用法：
  tools\\python\\python.exe scripts\\dev\\eval_jev_mention.py --dry-run --split eval
  tools\\python\\python.exe scripts\\dev\\eval_jev_mention.py --split all --variant baseline,few-shot
  tools\\python\\python.exe scripts\\dev\\eval_jev_mention.py --self-test   # 离线 mock 自测
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
from tools.decision_client import (DecisionClient, validate_questions,  # noqa: E402
                                   MAX_QUESTIONS)
from features.calibrate.calib_mention_decision import (  # noqa: E402
    build_mention_request, build_mention_evidence)

UNCERTAIN = "cannot_determine"       # _disambiguation_question 的兜底选项键
BATCH_SIZE = 8                       # ≤ decision_client.MAX_QUESTIONS

#: few-shot 变体注入的固定示例（真实文本改写，只示范判读口径，不生成新文本）
FEW_SHOT = [
    {"example": "pick_gold",
     "zh": "守护者希恩，月狐。",
     "ref": "My deal with Shin was meant to stay",
     "T": ["心", "心月狐"], "gold": "心月狐",
     "rationale": "中文行唯一出现的「希恩」是心月狐的合法形式，证据卡标注其"
                  "来自鸣潮岁主；ref 行多目标表面形 Shin 命中两个候选，但只有"
                  "心月狐在中文行有形式支撑 → 选心月狐。"},
    {"example": "cannot_determine",
     "zh": "现在这个版本的主流玩法变了。",
     "ref": "the current meta has changed a lot.",
     "T": ["meta", "梅塔"], "gold": UNCERTAIN,
     "rationale": "中文行不含任何候选形式，证据卡也未在中文行出现；无法从证据"
                  "判断该 cue 实际指哪个对象 → 必须选 cannot_determine，不得"
                  "凭记忆猜。"},
]

#: 请求里随 record 携带的 kind（决定 build_mention_request 的问题构造分支）
TIER_KIND = {"T1": "tb_fail", "T2": "tb_fail", "T3": "ambiguous_dis0"}


def load_cases(path, split="all", limit=0, tiers=None):
    cases = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            c = json.loads(line)
            if split != "all" and c.get("split") != split:
                continue
            if tiers and c.get("tier") not in tiers:
                continue
            cases.append(c)
    return cases[:limit] if limit else cases


def _assert_no_calib(cases):
    for c in cases:
        for k in ("source", "ref_source"):
            v = str(c.get(k) or "")
            if ".calib.srt" in os.path.basename(v):
                raise AssertionError("金标污染：case %s 来源指向校准产物 %s"
                                     % (c.get("id"), v))


def case_record(case, registry):
    """把评测 case 转成包A build_mention_request 的 record 结构。"""
    tier = case.get("tier") or "T1"
    record = {
        "num": case["id"],
        "kind": TIER_KIND.get(tier, "tb_fail"),
        "zh": case["zh"], "ref": case["ref"],
        "T": list(case.get("T") or []),
        "R": list(case.get("T") or []),   # tb_fail 保守回退口径：R=全 T
    }
    record["evidence"] = build_mention_evidence(record, registry)
    return record


def build_batch_request(chunk, registry, variant):
    records = [case_record(c, registry) for c in chunk]
    state, questions, items = build_mention_request(records, registry,
                                                    variant=variant)
    if variant == "few-shot":
        state = dict(state)
        state["few_shot_examples"] = FEW_SHOT
    return state, questions, items, records


def _div(a, b):
    return (a / b) if b else None


def _r(v):
    return round(v, 4) if v is not None else None


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


def metrics(rows):
    """探针指标：gold 已定（mechanical）条目上算准确率/召回/拦截/分箱。"""
    det = [r for r in rows if r.get("gold_status") == "mechanical"]
    pos = [r for r in det if r["gold"]]              # gold ∈ T
    neg = [r for r in det if not r["gold"]]          # gold = uncertain
    bins = defaultdict(lambda: [0, 0])
    for r in det:
        b = bins[_bin(r["confidence"])]
        b[0] += 1
        b[1] += 1 if r["correct"] else 0
    prob_gold_ok = [r["probabilities"].get(r["gold"], 0.0)
                    for r in pos if r["correct"]]
    prob_gold_bad = [r["probabilities"].get(r["gold"], 0.0)
                     for r in pos if not r["correct"]]
    prob_unc = [r["probabilities"].get(UNCERTAIN, 0.0) for r in neg]
    by_tier = {}
    for tier in ("T1", "T2", "T3"):
        sub = [r for r in rows if r.get("tier") == tier]
        sub_det = [r for r in sub if r.get("gold_status") == "mechanical"]
        by_tier[tier] = {
            "cases": len(sub),
            "gold_determined": len(sub_det),
            "accuracy": _r(_div(sum(1 for r in sub_det if r["correct"]),
                                len(sub_det))),
            "uncertain_rate": _r(_div(
                sum(1 for r in sub if r["choice"] == UNCERTAIN), len(sub))),
        }
    return {
        "cases": len(rows), "degraded": sum(1 for r in rows
                                            if r.get("status") == "degraded"),
        "gold_determined": len(det),
        "accuracy": _r(_div(sum(1 for r in det if r["correct"]), len(det))),
        "positive_recall": _r(_div(
            sum(1 for r in pos if r["choice"] == r["gold"]), len(pos))),
        "negative_refusal": _r(_div(
            sum(1 for r in neg if r["choice"] == UNCERTAIN), len(neg))),
        "uncertain_rate": _r(_div(
            sum(1 for r in rows if r["choice"] == UNCERTAIN), len(rows))),
        "confidence_bins": {k: {"n": v[0], "acc": _r(_div(v[1], v[0]))}
                            for k, v in sorted(bins.items())},
        "probabilities": {
            "mean_P_gold_when_correct": _r(_div(sum(prob_gold_ok),
                                                len(prob_gold_ok))),
            "mean_P_gold_when_wrong": _r(_div(sum(prob_gold_bad),
                                              len(prob_gold_bad))),
            "mean_P_uncertain_on_no_anchor": _r(_div(sum(prob_unc),
                                                     len(prob_unc))),
        },
        "by_tier": by_tier,
    }


def run_variant(cases, variant, client, registry, batch_size=BATCH_SIZE,
                log=print):
    """逐批发请求；单批异常整批降级，不中断后续批。"""
    rows, errors, requests = [], [], 0
    for offset in range(0, len(cases), batch_size):
        chunk = cases[offset:offset + batch_size]
        state, questions, items, records = build_batch_request(
            chunk, registry, variant)
        prompt_bytes = len(json.dumps(state, ensure_ascii=False).encode("utf-8"))
        try:
            response = client.decide(state, questions)
            requests += 1
            for case, item in zip(chunk, items):
                answer = response["answers"][item["question"]]
                ev = item.get("evidence") or {}
                rows.append({
                    "id": case["id"], "tier": case.get("tier"),
                    "label": case.get("label"), "pair": case.get("pair"),
                    "gold": case.get("gold", ""),
                    "gold_status": case.get("gold_status", ""),
                    "choice": str(answer.get("choice")),
                    "correct": str(answer.get("choice")) ==
                               (case.get("gold") or UNCERTAIN),
                    "confidence": float(answer.get("confidence", 0.0)),
                    "probabilities": dict(answer.get("probabilities") or {}),
                    "request_id": response.get("request_id", ""),
                    "model": response.get("model"),
                    "synthetic": case.get("synthetic", ""),
                    "mode": case.get("mode"),
                    "stats": case.get("stats") or {},
                    "evidence_status": ev.get("status"),
                    "T": case.get("T") or [],
                    "prompt_bytes": prompt_bytes,
                })
        except Exception as exc:  # noqa: BLE001 — 单批失败整批降级
            message = "%s: %s" % (type(exc).__name__, str(exc)[:200])
            errors.append({"offset": offset, "count": len(chunk),
                           "first_id": chunk[0]["id"], "error": message})
            for case in chunk:
                rows.append({
                    "id": case["id"], "tier": case.get("tier"),
                    "label": case.get("label"), "pair": case.get("pair"),
                    "gold": case.get("gold", ""),
                    "gold_status": case.get("gold_status", ""),
                    "choice": "", "correct": False, "confidence": 0.0,
                    "probabilities": {}, "request_id": "",
                    "status": "degraded", "reason": message,
                    "synthetic": case.get("synthetic", ""),
                    "mode": case.get("mode"), "stats": case.get("stats") or {},
                    "evidence_status": (case_record(case, registry)
                                        .get("evidence") or {}).get("status"),
                    "T": case.get("T") or [], "prompt_bytes": prompt_bytes,
                })
        log("  %s[%d/%d] 批 %d 例 %dB" % (variant, offset + len(chunk),
                                          len(cases), batch_size, prompt_bytes))
    report = metrics(rows)
    report["variant"] = variant
    report["requests"] = requests
    report["errors"] = errors
    report["items"] = rows
    return report


def dry_run(cases, variants, registry):
    """零网络：构造全部批请求，校验问题协议与证据覆盖/体积。"""
    _assert_no_calib(cases)
    out = {"mode": "dry-run", "network": "none", "cases": len(cases),
           "variants": {}}
    for variant in variants:
        statuses, bytes_total, n_req = Counter(), 0, 0
        max_q = 0
        for offset in range(0, len(cases), BATCH_SIZE):
            chunk = cases[offset:offset + BATCH_SIZE]
            state, questions, items, _recs = build_batch_request(
                chunk, registry, variant)
            validate_questions(questions)      # 协议校验（本地，不发请求）
            assert len(questions) <= MAX_QUESTIONS
            statuses.update((it.get("evidence") or {}).get("status", "none")
                            for it in items)
            bytes_total += len(json.dumps(state, ensure_ascii=False)
                               .encode("utf-8"))
            n_req += 1
            max_q = max(max_q, len(questions))
        out["variants"][variant] = {
            "requests": n_req, "batch_size": BATCH_SIZE,
            "max_questions_per_request": max_q,
            "state_bytes_total": bytes_total,
            "state_bytes_avg": int(bytes_total / max(n_req, 1)),
            "evidence_status": dict(statuses),
        }
    return out


# ---------------------------------------------------------------- mock 自测


class FakeMentionClient:
    """对齐 _selftest_decision.FakeShadow 的离线客户端（零网络）。"""

    def __init__(self, error=False):
        self.active = True
        self.status = {"active": True, "mode": "shadow",
                       "model": "decision-model-preview",
                       "endpoint": "https://example/systemone"}
        self.config = {"decision_max_items": 32, "decision_batch_size": 8}
        self.error = error
        self.calls = []

    def decide(self, state, questions):
        self.calls.append((state, questions))
        if self.error:
            raise RuntimeError("模拟超时")
        answers = {}
        for name, q in questions.items():
            keys = [k for k in q["criteria"] if k != UNCERTAIN]
            if keys and state["items"] and \
                    next(it for it in state["items"]
                         if it["question"] == name).get("kind") == "tb_fail":
                choice, conf = keys[0], 0.85
            else:
                choice, conf = UNCERTAIN, 0.7
            probs = {k: 0.05 for k in q["criteria"]}
            probs[choice] = 1.0 - 0.05 * (len(probs) - 1)
            answers[name] = {"type": "choice", "choice": choice,
                             "confidence": conf, "probabilities": probs}
        return {"model": "decision-model-preview", "request_id": "mock-req",
                "answers": answers}


def self_test(cases_path, out_path):
    """离线 mock 全链路自测（对齐 _selftest_decision 口径），PASS/FAIL 输出。"""
    passed, failed = [], []

    def check(name, cond, detail=""):
        (passed if cond else failed).append((name, detail))
        print(("PASS" if cond else "FAIL"), name, detail if not cond else "")

    registry = _load_registry()
    all_cases = load_cases(cases_path, "all")
    # 分层取样：每层取前 12，保证 mock 自测覆盖 T1/T2/T3 全部问题分支
    cases = []
    for tier in ("T1", "T2", "T3"):
        cases.extend([c for c in all_cases
                      if c.get("tier") == tier][:12])
    check("样本加载（分层 T1/T2/T3）", len(cases) > 0)
    try:
        _assert_no_calib(cases)
        check("金标零 .calib 污染断言", True)
    except AssertionError as exc:
        check("金标零 .calib 污染断言", False, str(exc))

    fake = FakeMentionClient()
    report = run_variant(cases, "few-shot", fake, registry, log=lambda *_: None)
    check("mock 客户端零网络（无 opener/urllib 调用）",
          all(not isinstance(c, tuple) or len(c) == 2
              for c in fake.calls) and len(fake.calls) > 0
          and fake.calls[0][0].get("business") == "mention_disambiguation_review")
    check("每批问题数 ≤ 8", all(len(q) <= BATCH_SIZE for _s, q in fake.calls))
    check("全部批通过协议校验",
          all(_safe_validate(q) for _s, q in fake.calls))
    check("记录含 id/tier/gold/choice/probabilities/confidence/request_id/stats",
          all(all(k in r for k in ("id", "tier", "gold", "choice",
                                   "probabilities", "confidence",
                                   "request_id", "stats"))
              for r in report["items"]))
    check("request_id 落到每条记录",
          all(r["request_id"] == "mock-req" for r in report["items"]))
    check("概率归一化", all(abs(sum(r["probabilities"].values()) - 1.0) < 0.08
                            for r in report["items"] if r["probabilities"]))
    check("few-shot 变体注入示例", _few_shot_injected(fake))
    check("指标键齐全", all(k in report for k in
                            ("accuracy", "positive_recall", "negative_refusal",
                             "confidence_bins", "probabilities", "by_tier")))
    check("T3 收到 cannot_determine 口径答案",
          any(r["choice"] == UNCERTAIN for r in report["items"]
              if r["tier"] == "T3"))

    err_client = FakeMentionClient(error=True)
    err_report = run_variant(cases, "baseline", err_client, registry,
                             log=lambda *_: None)
    check("批失败整批降级", err_report["degraded"] == len(cases)
          and len(err_report["errors"]) > 0
          and all(r.get("status") == "degraded" for r in err_report["items"]))

    dry = dry_run(cases, ["baseline", "few-shot"], registry)
    check("dry-run 零网络且批数一致",
          dry["variants"]["baseline"]["requests"] ==
          dry["variants"]["few-shot"]["requests"] > 0)

    payload = {"schema": "jev-mention-eval/1", "probe_source": "self_test_mock",
               "mock": True, "split": "all", "cases": len(cases),
               "variants": {"few-shot": report, "baseline": err_report},
               "dry_run": dry}
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("mock 探针输出：%s" % out_path)
    print("\n%d PASS / %d FAIL" % (len(passed), len(failed)))
    return 1 if failed else 0


def _safe_validate(questions):
    try:
        validate_questions(questions)
        return True
    except Exception:  # noqa: BLE001
        return False


def _few_shot_injected(fake):
    return all("few_shot_examples" in s for s, _q in fake.calls
               if s.get("policy", {}).get("prompt_variant") == "few-shot")


def _load_registry():
    from features.calibrate.calib_evidence import _load_registry
    return _load_registry()[0]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Jev mention 消歧真实请求探针")
    ap.add_argument("--cases", default="data/entities/jev_mention_cases.jsonl")
    ap.add_argument("--split", choices=("train", "eval", "all"), default="all")
    ap.add_argument("--tier", default="",
                    help="逗号分隔过滤，如 T1,T3；默认全部")
    ap.add_argument("--variant", default="few-shot",
                    help="baseline / few-shot / baseline,few-shot")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    ap.add_argument("--out", default="")
    ap.add_argument("--dry-run", action="store_true",
                    help="零网络：只构造请求并检查证据覆盖/体积/协议")
    ap.add_argument("--self-test", action="store_true",
                    help="离线 mock 自测（FakeShadow 口径），产出 mock 探针 JSON")
    args = ap.parse_args(argv)

    cases_path = os.path.join(ROOT, args.cases)
    variants = [v.strip() for v in args.variant.split(",") if v.strip()]
    tiers = [t.strip() for t in args.tier.split(",") if t.strip()] or None

    if args.self_test:
        return self_test(cases_path,
                         os.path.join(ROOT, "data", "tmp",
                                      "jev_mention_eval_mock.json"))

    cases = load_cases(cases_path, args.split, args.limit, tiers)
    if not cases:
        ap.error("没有匹配的评测样本")
    registry = _load_registry()

    if args.dry_run:
        report = dry_run(cases, variants, registry)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    cfg = load_config()
    client = DecisionClient(cfg)
    if not client.active:
        print(json.dumps({"error": "Jev 门控未激活（真实请求需 Token Plan 密钥）",
                          "status": client.status}, ensure_ascii=False, indent=2))
        return 2
    reports = {}
    for variant in variants:
        print("variant=%s cases=%d" % (variant, len(cases)))
        reports[variant] = run_variant(cases, variant, client, registry,
                                       args.batch_size)
    payload = {
        "schema": "jev-mention-eval/1",
        "probe_source": "real_request",
        "mock": False,
        "split": args.split, "cases": len(cases),
        "endpoint": client.status.get("endpoint"),
        "variants": reports,
    }
    out = args.out or os.path.join(
        ROOT, "data", "entities", "jev_mention_eval_%s.json" % args.split)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    for variant, report in reports.items():
        slim = {k: v for k, v in report.items()
                if k not in ("items",)}
        print(json.dumps(slim, ensure_ascii=False, indent=2)[:2200])
    print("探针报告：%s" % out)
    return 0 if not any(r["errors"] for r in reports.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
