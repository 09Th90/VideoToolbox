# -*- coding: utf-8 -*-
# @version 3.1.0
"""AI 校准采纳项的 Jev 结构化影子复核（不生成或改写字幕文本）。

2026-11-18 优化：
  * 每条改动附本地对象库证据包（官方名/作品/类别/已知错形）；
  * choice 边界从“语义像不像”改成“是否属于证据支持的最小替换”；
  * 证据缺失或目标冲突时明确降级为 manual_review/questionable；
  * accepted 与字幕产物始终原样，Jev 只写报告。
"""
from __future__ import annotations

SCHEMA_VERSION = "vt.calibrate.shadow.v1"
EVIDENCE_SCHEMA = "vt.calibrate.evidence.v1"
ROUTES = {
    "consistent": "改动保留原意，术语和语义一致",
    "manual_review": "证据不足或改动较复杂，建议人工复核",
    "questionable": "可能偏离原意、误改术语或引入新问题",
}

EVIDENCE_ROUTES = {
    "consistent": (
        "证据 status=ok 且 clean_replacement=true：new 只把 old 中该目标对象的"
        "已知错形替换成 evidence.official（或 evidence.aliases 中的官方别名），"
        "句法、语气和其他信息不变。"),
    "questionable": (
        "new 超出最小术语替换：引入 evidence 之外的人名/地名/术语，改动了非术语"
        "内容，或把普通词/更长词中的字符串误当专名；也可由 target_conflict 判定。"),
    "manual_review": (
        "证据 status=missing、存在多个可能目标、soft=true、old/new 过短或句法明显"
        "歧义；不得仅凭记忆补官方名。"),
}

FEWSHOT_EXAMPLES = [
    {"old": "安特雷斯拉。", "new": "安特雷西斯拉。",
     "evidence": "官方目标「特雷西斯」；旧文命中已知错形「特雷斯」；只做最小替换：是。",
     "label": "accept"},
    {"old": "安特雷斯拉。", "new": "安伊什梅尔拉。",
     "evidence": "官方目标「伊什梅尔」；旧文命中已知错形：无；只做最小替换：否。",
     "label": "reject"},
    {"old": "分析了希恩支离破碎的频率", "new": "分析了心月狐支离破碎的频率",
     "evidence": "官方目标「心月狐」；旧文命中已知错形「希恩」；只做最小替换：是。",
     "label": "accept"},
]


def _int_setting(value, default, low, high):
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def _summary(client, accepted_total):
    status = dict(getattr(client, "status", {}) or {})
    return {"schema_version": SCHEMA_VERSION,
            "evidence_schema": EVIDENCE_SCHEMA,
            "active": bool(status.get("active")),
            "mode": str(status.get("mode") or "off"),
            "model": status.get("model") or "decision-model-preview",
            "endpoint": status.get("endpoint") or "",
            "reason": status.get("reason") or "not_configured",
            "accepted_total": accepted_total, "selected": 0, "evaluated": 0,
            "jev_evaluated": 0, "requests": 0, "truncated": 0, "gated": 0,
            "evidence_ok": 0, "evidence_missing": 0, "evidence_conflict": 0,
            "gate_reasons": {},
            "routes": {}, "items": [], "errors": []}


def _baseline_question(qname):
    return {
        "type": "choice",
        "instructions": (
            "只比较 state.items 中 question=%s 的 old/new。该改动已经通过"
            "序号、时间轴、行结构和宽度等机械校验；你只复核语义保留与术语"
            "一致性，不生成新文本，不声称已联网核实官方译名。输出 consistent、"
            "manual_review 或 questionable。" % qname),
        "criteria": ROUTES,
    }


def _evidence_question(qname, evidence):
    status = (evidence or {}).get("status")
    text = (evidence or {}).get("text") or ""
    extra = ""
    if status != "ok":
        extra = " 本条证据缺失或冲突，按 criteria 走 manual_review/questionable，不要猜官方名。"
    return {
        "type": "choice",
        "instructions": (
            "只复核 state.items 中 question=%s 的 old/new。以 item.evidence 为唯一"
            "官方事实来源；证据卡：%s 不生成新文本，也不得凭记忆补官方名。"
            "先看 clean_replacement / target_conflict / text，再判是否只在错形"
            "位置做了最小替换。输出 consistent、manual_review 或 questionable。"
            "%s" % (qname, text, extra)),
        "criteria": EVIDENCE_ROUTES,
    }


def _binary_question(qname, evidence):
    status = (evidence or {}).get("status")
    text = (evidence or {}).get("text") or ""
    extra = " 证据非 ok 时必须 reject。" if status != "ok" else ""
    return {
        "type": "choice",
        "instructions": (
            "判断 state.items 中 question=%s 的改动是否可接受。以 item.evidence 为"
            "唯一官方事实来源，不生成新文本。证据卡：%s 只有 evidence.status=ok 且 "
            "clean_replacement=true 时 accept；否则 reject。%s" % (qname, text, extra)),
        "criteria": {
            "reject": "证据冲突/缺失，clean_replacement=false，或 new 引入证据之外的内容。",
            "accept": "证据 ok 且 clean_replacement=true，new 仅做错形到官方名的最小替换。",
        },
    }


def _noul_question(qname, evidence):
    status = (evidence or {}).get("status")
    text = (evidence or {}).get("text") or ""
    extra = " 证据缺失或冲突时，应给高风险概率。" if status != "ok" else ""
    return {
        "type": "noul",
        "instructions": (
            "估计 state.items 中 question=%s 的改动「不应被接受」的概率（0=完全"
            "支持，1=高风险）。以 item.evidence 为唯一官方事实来源。证据卡：%s "
            "若证据 status 不是 ok、clean_replacement=false、或 target_conflict "
            "存在，应给高概率；clean_replacement=true 且只在错形位置做最小替换时"
            "给低概率。不生成新文本，不得凭记忆补官方名。%s"
            % (qname, text, extra)),
    }


def build_request(selected, registry=None, *, variant="evidence"):
    """构造一批请求，供生产与离线评测共用。selected 为 accepted 五元组。"""
    items, questions = [], {}
    for pos, change in enumerate(selected):
        num, old, new, why, soft = change[:5]
        qname = "review_%d" % pos
        item = {"question": qname, "num": num,
                "old": str(old)[:800], "new": str(new)[:800],
                "reason": str(why)[:400], "soft": bool(soft)}
        if variant in ("evidence", "evidence_noul", "evidence_binary",
                       "evidence_text", "evidence_text_noul", "evidence_text_binary",
                       "evidence_text_noul_fewshot"):
            from .calib_evidence import build_evidence, compact_for_prompt
            evidence = build_evidence(str(old), str(new), str(why), registry)
            item["evidence"] = compact_for_prompt(evidence)
            if variant in ("evidence_noul", "evidence_text_noul",
                           "evidence_text_noul_fewshot"):
                questions[qname] = _noul_question(qname, evidence)
            elif variant in ("evidence_binary", "evidence_text_binary"):
                questions[qname] = _binary_question(qname, evidence)
            else:
                questions[qname] = _evidence_question(qname, evidence)
        else:
            evidence = None
            if variant == "baseline_noul":
                questions[qname] = {
                    "type": "noul",
                    "instructions": ("估计 state.items 中 question=%s 的改动不应被"
                                     "接受的概率；不得生成新文本。%s" % (qname, ""))}
            else:
                questions[qname] = _baseline_question(qname)
        items.append(item)
    state = {"schema_version": SCHEMA_VERSION, "evidence_schema": EVIDENCE_SCHEMA,
             "business": "subtitle_calibration_review",
             "policy": {"shadow_only": True, "allow_text_generation": False,
                        "mechanical_validation_already_passed": True,
                        "prompt_variant": variant},
             "items": items}
    if variant == "evidence_text_noul_fewshot":
        state["examples"] = FEWSHOT_EXAMPLES
        state["policy"]["judge_examples_first"] = True
    return state, questions, items


def _gate_route(evidence):
    """本地证据闸门：不依赖 Jev，先把确定高风险/不可核实的改动分流。"""
    status = (evidence or {}).get("status")
    if status == "conflict":
        return "questionable", "target_conflict"
    if status == "missing":
        return "manual_review", "evidence_missing"
    if not (evidence or {}).get("clean_replacement"):
        return "manual_review", "not_clean_replacement"
    return "", ""


def apply_shadow(result, client, *, max_items=None, batch_size=None, log=None,
                 registry=None, variant="evidence_text"):
    """复核 result.accepted，追加 result.decision；accepted 与输出文件保持原样。"""
    accepted = list(result.get("accepted") or [])
    summary = _summary(client, len(accepted))
    result["decision"] = summary
    if not accepted or client is None or not getattr(client, "active", False):
        return summary
    if variant != "baseline":
        try:
            from .calib_evidence import _load_registry, build_evidence
            if registry is None:
                registry, _source = _load_registry()
            evidences = [build_evidence(str(c[1]), str(c[2]), str(c[3]), registry)
                         for c in accepted]
        except Exception:  # noqa: BLE001 — 证据层不可用不能阻断校准
            registry, evidences = {}, []
    else:
        evidences = []
    cfg = dict(getattr(client, "config", {}) or {})
    limit = _int_setting(max_items if max_items is not None
                         else cfg.get("decision_max_items"), 32, 0, 512)
    batch_size = _int_setting(batch_size if batch_size is not None
                              else cfg.get("decision_batch_size"), 8, 1, 8)
    selected = accepted[:limit]
    selected_ev = evidences[:limit]
    summary["selected"] = len(selected)
    summary["truncated"] = max(0, len(accepted) - len(selected))
    summary["prompt_variant"] = variant

    for ev in selected_ev:
        status = (ev or {}).get("status")
        if status == "ok":
            summary["evidence_ok"] += 1
        elif status == "conflict":
            summary["evidence_conflict"] += 1
        else:
            summary["evidence_missing"] += 1

    def _say(text, level="dim"):
        if log:
            try:
                log(text, level)
            except TypeError:
                log(text)

    for offset in range(0, len(selected), batch_size):
        batch = selected[offset:offset + batch_size]
        entries = [None] * len(batch)
        pending, pending_pos = [], []
        for i, change in enumerate(batch):
            ev = selected_ev[offset + i] if selected_ev else {}
            gate, why = _gate_route(ev)
            if gate:
                summary["gated"] += 1
                summary["evaluated"] += 1
                summary["gate_reasons"][why] = summary["gate_reasons"].get(why, 0) + 1
                summary["routes"][gate] = summary["routes"].get(gate, 0) + 1
                entries[i] = {
                    "num": change[0], "status": "gated", "choice": gate,
                    "confidence": 1.0, "probabilities": {gate: 1.0},
                    "gate": why, "evidence_status": ev.get("status", ""),
                    "official": ev.get("official", ""),
                    "reason": "本地证据闸门；未调用 Jev",
                }
            else:
                pending.append(change)
                pending_pos.append(i)
        if pending:
            state, questions, items = build_request(pending, registry, variant=variant)
            try:
                response = client.decide(state, questions)
                summary["requests"] += 1
                for pos, item in zip(pending_pos, items):
                    answer = response["answers"][item["question"]]
                    choice = str(answer["choice"])
                    summary["routes"][choice] = summary["routes"].get(choice, 0) + 1
                    summary["evaluated"] += 1
                    summary["jev_evaluated"] += 1
                    entries[pos] = {
                        "num": item["num"], "status": "ok", "choice": choice,
                        "confidence": float(answer["confidence"]),
                        "probabilities": dict(answer.get("probabilities") or {}),
                        "model": response.get("model"),
                        "request_id": response.get("request_id"),
                        "evidence_status": (item.get("evidence") or {}).get("status"),
                        "official": (item.get("evidence") or {}).get("official", ""),
                    }
            except Exception as exc:  # noqa: BLE001 — 云端失败不影响已校验字幕
                message = "%s: %s" % (type(exc).__name__, str(exc)[:240])
                summary["errors"].append({"first_num": pending[0][0] if pending else None,
                                          "count": len(pending), "error": message})
                for pos in pending_pos:
                    entries[pos] = {
                        "num": batch[pos][0], "status": "degraded",
                        "reason": message, "evidence_status": "ok",
                    }
                _say("Jev 影子复核本批降级，校准结果保持不变：%s" % message, "err")
        summary["items"].extend([x for x in entries if x is not None])
        _say("Jev 影子复核：%d/%d 条采纳项（本地闸门 %d，Jev %d）" %
             (min(offset + len(batch), len(selected)), len(selected),
              summary["gated"], summary["jev_evaluated"]))
    return summary


__all__ = ["apply_shadow", "build_request", "SCHEMA_VERSION", "EVIDENCE_SCHEMA",
           "ROUTES", "EVIDENCE_ROUTES", "FEWSHOT_EXAMPLES"]
