# -*- coding: utf-8 -*-
# @version 3.2.5
"""L2 生成式校准前的 Jev 结构化分诊（pre_calibration_triage，shadow-only）。

定位：在逐块生成式校准**之前**对 pending 块做一次「要不要校准 / 需要什么
证据 / 走哪条路线」的分诊预判。与 calib_decision（accepted 复核）、
calib_mention_decision（对象级 mention 复核）构成三条影子链的第三条——
它是唯一挂在**生成式调用之前**的挂载点。

铁律（WP4 用户裁决：默认全影子）：
  * 影子非阻断——本模块只记录 would_skip / would_save，**绝不改动 pending、
    绝不跳过任何生成式调用**；异常整批降级 degraded；
  * 机械基线 / 参考行保护 / verify 始终执行，不可被分诊跳过（policy 声明）；
  * 引擎纯度——只复用 calib_mention_decision 的离线重建（其内部只 import
    calib_core.mention / calib_core.asr 纯函数），绝不 import
    calib_core.engine / calib_core.process / 网络模块；
  * 无网络硬依赖——decision_client 为 None 或未激活（decision_mode=off）时
    零请求零开销直接返回，挂载点行为与不挂载完全一致。

数据流（插入点 A）：
  pending_chunks = [(idx, chunk)]，chunk = [(num, zh, en), ...]
  → collect_triage_records(...)：每块离线收集 issue_types / issue_samples /
    rule_hits / script_changes_in_block / residual_wrong / evidence
  → _gate_route_triage：本地确定性闸门先行（zero_issue → 本可跳过；
    round_no>1 / 块太小 / 跨作品冲突 → 送 Jev；缺官方名 → needs_web_hint）
  → apply_triage_shadow：批 ≤4 块（每块 4 问 × 4 块 = MAX_QUESTIONS=16）
    → client.decide → 只写 summary 报告。
"""
from __future__ import annotations

from .calib_evidence import _load_registry, _works
from .calib_mention_decision import (
    MAX_QUESTIONS as _MENTION_MAX_QUESTIONS,
    collect_records,
    mention_evidence_text,
)

SCHEMA_VERSION = "vt.calibrate.triage.v1"
EVIDENCE_SCHEMA = "vt.calibrate.mention_evidence.v1"
BUSINESS = "pre_calibration_triage"
POLICY = {"shadow_only": True, "allow_text_generation": False,
          "mechanical_baseline_already_applied": True,
          "ref_lines_protected": True}

#: 单请求问题上限（对齐 tools/decision_client.MAX_QUESTIONS = 16）
MAX_QUESTIONS = _MENTION_MAX_QUESTIONS
#: 每块的问题数（general / web / media / route）
QUESTIONS_PER_BLOCK = 4
#: 单请求块数上限（16 问 ÷ 4 问/块 = 4 块/请求）
BLOCKS_PER_REQUEST = MAX_QUESTIONS // QUESTIONS_PER_BLOCK

#: 本地闸门「可跳过」的块内 cue 数下限：块太小（<20 条）跳过收益低，
#: 保守送 Jev / 生成式，避免把小改动块误跳导致整段漏校。
MIN_CUES_GATE = 20

#: 块级 issue 样本上限（控制 state 体积）
ISSUE_SAMPLES_MAX = 6
#: 块级证据卡里引用的 mention 证据文本条数上限
EVIDENCE_TEXTS_MAX = 4

#: issue 预分类枚举（复用 calib_mention_decision._classify_cue 的 kind 口径）
ISSUE_KINDS = ("tb_fail", "ambiguous_dis0", "unresolved_proper",
               "anchorable_wrong", "blocked", "no_issue")


def _int_setting(value, default, low, high):
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------- 记录收集


def _rule_hits_for_chunk(rules, chunk):
    """块级规则命中计数（与 select_rules_for_chunk 同口径：zh 命中 hot、
    ref 命中 warm）。只计数不构造文本，供 zero_issue 闸门与证据卡用。"""
    zh_text = "\n".join(zh for _n, zh, _e in chunk)
    ref_text = "\n".join(en for _n, _zh, en in chunk)
    hot = warm = 0
    for wrong, _canon in rules or ():
        if not wrong:
            continue
        if wrong in zh_text:
            hot += 1
        elif wrong in ref_text:
            warm += 1
    return {"hot": hot, "warm": warm, "total": hot + warm}


def _block_evidence(issue_types, rule_hits, texts, works, missing_official,
                    cue_total):
    """块级证据卡：聚合 mention 证据 + 规则命中 + 统计，供 Jev 判读。"""
    ev_texts = [t for t in (texts or []) if t]
    rule_total = int((rule_hits or {}).get("total") or 0)
    if list(issue_types or []) == ["no_issue"] and rule_total == 0:
        status = "clean"
        text = ("本块 %d 条 cue 无对象级问题，也无可解释的规则命中"
                "（机械基线已应用）。" % cue_total)
    elif missing_official:
        status = "missing"
        text = ("本块存在本地对象库无规格的候选（%d 条记录缺官方名），"
                "需联网查证官方名后再裁决。规则命中 %d 条。"
                % (missing_official, rule_total))
    else:
        status = "ok"
        kinds = "、".join(str(k) for k in (issue_types or [])) or "无"
        head = "；".join(ev_texts[:2])
        text = ("本块问题类型：%s；规则命中 %d 条。证据摘要：%s"
                % (kinds, rule_total, head or "无"))
    return {"schema_version": EVIDENCE_SCHEMA, "status": status,
            "issue_types": [str(k) for k in (issue_types or [])],
            "rule_hits": dict(rule_hits or {}),
            "works": sorted(works or []),
            "missing_official": int(missing_official or 0),
            "texts": ev_texts, "text": text}


def collect_triage_records(pending_chunks, rules, *, mode="bi", round_no=1,
                           registry=None, script_changes_map=None):
    """逐块离线收集分诊记录（v1 零缝：不读引擎状态，全部从 chunk 重建）。

    pending_chunks = [(idx, chunk)]，chunk = [(num, zh, en), ...]（与
    calibrate 主流程的 chunks/pending 同构）。每块用
    calib_mention_decision.collect_records 对 rows=[(num, zh, zh, en)] 离线
    重建 mention 决策记录（内部走 _classify_cue 预分类），聚合成块级记录：

      {block, cue_range, cue_total, issue_types, issue_samples(≤6),
       rule_hits, script_changes_in_block, residual_wrong, evidence}

    issue_types ∈ ISSUE_KINDS；块内无 mention 记录时为 ["no_issue"]。
    script_changes_map = {num: 基线新文本}（挂载方从基线产物 parse 而来），
    用于统计机械基线在本块造成的改动数；缺省视为 0。round_no 仅入档
    （闸门的轮次判定在 _gate_route_triage 显式传参处生效）。
    """
    if registry is None:
        registry, _source = _load_registry()
    script_changes_map = script_changes_map or {}
    records = []
    for idx, chunk in pending_chunks or []:
        chunk = list(chunk or [])
        rows = [(num, zh, zh, en) for num, zh, en in chunk]
        mention_records = collect_records(rows, mode, registry)
        kinds = sorted({str(r.get("kind")) for r in mention_records})
        issue_types = kinds if kinds else ["no_issue"]
        samples = []
        for r in mention_records[:ISSUE_SAMPLES_MAX]:
            samples.append({
                "num": r.get("num"), "kind": r.get("kind"),
                "zh": str(r.get("zh") or "")[:80],
                "candidates": list(r.get("T") or [])[:4],
            })
        # residual_wrong：残留错形（anchorable_wrong）条数与最小替换样本
        residual = [r for r in mention_records
                    if r.get("kind") == "anchorable_wrong"]
        rule_hits = _rule_hits_for_chunk(rules, chunk)
        script_changes = sum(
            1 for num, zh, _en in chunk
            if num in script_changes_map
            and str(script_changes_map.get(num) or "") != str(zh or ""))
        # 跨作品候选 / 缺官方名（闸门用）：聚合块内记录证据卡的候选
        works, missing_official = set(), 0
        for r in mention_records:
            ev = r.get("evidence") or {}
            if ev.get("status") == "missing":
                missing_official += 1
            for c in ev.get("candidates") or []:
                w = str(c.get("work") or "")
                if not w and c.get("category"):
                    w = _works(str(c.get("category") or ""))
                if w:
                    works.add(w)
        texts = [mention_evidence_text(r.get("evidence") or {})
                 for r in mention_records[:EVIDENCE_TEXTS_MAX]]
        first, last = (chunk[0][0], chunk[-1][0]) if chunk else ("", "")
        record = {
            "block": idx,
            "cue_range": "%s-%s" % (first, last),
            "cue_total": len(chunk),
            "round_no": int(round_no or 1),
            "issue_types": issue_types,
            "issue_samples": samples,
            "rule_hits": rule_hits,
            "script_changes_in_block": script_changes,
            "residual_wrong": {
                "count": len(residual),
                "samples": [{"num": r.get("num"),
                             "wrong": (r.get("anchor") or {}).get("wrong", ""),
                             "right": (r.get("anchor") or {}).get("right", "")}
                            for r in residual[:ISSUE_SAMPLES_MAX]]},
            "mention_records_total": len(mention_records),
            "cross_work": len(works) > 1,
            "works": sorted(works),
            "missing_official": missing_official,
        }
        record["evidence"] = _block_evidence(issue_types, rule_hits, texts,
                                             works, missing_official,
                                             len(chunk))
        records.append(record)
    return records


def triage_evidence_text(record):
    """把块级证据卡压成一句可判读的中文卡（渲染/自测用）。"""
    ev = (record or {}).get("evidence") or {}
    return str(ev.get("text") or "本块无证据。")


# ---------------------------------------------------------------- 本地闸门


def _gate_route_triage(record, round_no=1):
    """本地确定性闸门先行（不调 Jev）。返回 (route, why)。

    route ∈ ""（送 Jev）/ "skip_generative"（本可跳过生成式）/
    "needs_web_hint"（送 Jev 且提示需联网查官方名）。判定顺序（契约定序）：
      1. round_no > 1                     → 送 Jev（残留问题本地判不了）
      2. cue_total < MIN_CUES_GATE        → 送 Jev（块太小，跳过收益低）
      3. zero_issue                       → skip_generative
      4. anchorable_verified              → skip_generative
      5. cross_work_conflict              → 送 Jev
      6. missing 官方名                   → needs_web_hint
      7. 其余                             → 送 Jev
    """
    record = record or {}
    cue_total = int(record.get("cue_total") or 0)
    if round_no is not None and int(round_no) > 1:
        return "", "generative_consulted_round_gt1"
    if cue_total < MIN_CUES_GATE:
        return "", "block_too_small"
    issue_types = list(record.get("issue_types") or ["no_issue"])
    rule_total = int((record.get("rule_hits") or {}).get("total") or 0)
    if issue_types == ["no_issue"] and rule_total == 0:
        return "skip_generative", "zero_issue"
    if _anchorable_verified(record):
        return "skip_generative", "anchorable_verified"
    if record.get("cross_work"):
        return "", "cross_work_conflict"
    if int(record.get("missing_official") or 0) > 0:
        return "needs_web_hint", "missing_official_name"
    return "", "generative_consulted"


def _anchorable_verified(record):
    """块内问题全部为残留错形，且每条样本 wrong/right 齐备（本地最小替换
    可验证）。mention 的 anchorable_wrong 记录本身即单目标锚定（T={rt[0]}），
    因此 kind 口径纯净 + 锚定对齐备即可判「本地可闭环」。"""
    record = record or {}
    issue_types = list(record.get("issue_types") or [])
    if set(issue_types) - {"anchorable_wrong"} or not issue_types:
        return False
    residual = record.get("residual_wrong") or {}
    if int(residual.get("count") or 0) <= 0:
        return False
    samples = list(residual.get("samples") or [])
    if not samples:
        return False
    return all(str(s.get("wrong") or "") and str(s.get("right") or "")
               for s in samples)


# ---------------------------------------------------------------- 请求构造


def _general_question(qname):
    return {"type": "choice",
            "criteria": {
                "yes": "块内有本地规则/证据无法闭环的问题（消歧失败、疑似漏译、"
                       "跨作品冲突、残留错形未闭合等），需要生成式校准修复。",
                "no": "块内零问题，或问题全部已被机械基线修正且本地可验证，"
                      "跳过生成式不会引入漏改。",
            },
            "instructions": (
                "只判断 state.items 中 question=%s 所在块是否需要生成式校准："
                "以 item.evidence / item.issue_samples 为唯一依据。机械基线已"
                "应用、参考行已保护、verify 始终执行；你只做「要不要把该块送"
                "生成式」的分诊预判，不生成新文本，不得凭记忆补官方名。"
                % qname)}


def _web_question(qname):
    return {"type": "choice",
            "criteria": {
                "yes": "块内存在本地对象库无规格的候选或跨作品冲突，需要联网"
                       "查证官方名/作品归属。",
                "no": "本地证据已足够裁决，无需联网。",
                "na": "本块无任何对象级问题，联网无从谈起。",
            },
            "instructions": (
                "只判断 state.items 中 question=%s 所在块是否需要联网证据："
                "issue_types 含缺失官方名候选或跨作品冲突时才考虑 yes；纯规则"
                "错形/已锚定替换选 no；零问题选 na。不生成新文本。" % qname)}


def _media_question(qname):
    return {"type": "choice",
            "criteria": {
                "yes": "文本与参考行证据冲突或不足，需要听写/画面证据复核"
                       "（音画不一致、听写歧义）。",
                "no": "文本证据已足够，不需要音画证据。",
                "na": "本块无任何对象级问题。",
            },
            "instructions": (
                "只判断 state.items 中 question=%s 所在块是否需要源媒体音画"
                "证据：仅在文本证据不足且疑似听写/听译错误时选 yes；否则 no"
                "或 na。不生成新文本。" % qname)}


def _route_question(qname):
    return {"type": "choice",
            "criteria": {
                "term": "块内问题只需名词级术语最小替换（默认路线）。",
                "rewrite": "块内是机翻腔/断句问题，需要整句重写才能修好。",
                "manual": "块内改动风险高或涉及创作取舍，交给人工处理。",
            },
            "instructions": (
                "只判断 state.items 中 question=%s 所在块的推荐处理路线："
                "以 issue_types / residual_wrong / 证据卡为依据。term 只做"
                "错形到官方名的最小替换；rewrite 允许整句重写中文行；manual"
                "不改。不生成新文本。" % qname)}


def _compact_block_evidence(evidence):
    """去掉空字段控制 state 体积；status/text 恒保留（对齐 mention 口径）。"""
    out = {}
    for k, v in dict(evidence or {}).items():
        if k in ("schema_version",) or v in ("", None, [], {}, False):
            continue
        out[k] = v
    out["status"] = (evidence or {}).get("status") or "missing"
    if "text" not in out:
        out["text"] = "本块无证据。"
    return out


def build_triage_request(records, variant="default"):
    """构造一批分诊请求（单批 ≤ BLOCKS_PER_REQUEST 块，超出由调用方分批）。

    每块 4 问：triage_N_general（yes/no）/ triage_N_web（yes/no/na）/
    triage_N_media（yes/no/na）/ triage_N_route（term/rewrite/manual）。
    返回 (state, questions, items)。
    """
    items, questions = [], {}
    for pos, record in enumerate(list(records or [])[:BLOCKS_PER_REQUEST]):
        p = "triage_%d" % pos
        item = {"question": p, "block": record.get("block"),
                "cue_range": str(record.get("cue_range") or ""),
                "cue_total": int(record.get("cue_total") or 0),
                "issue_types": list(record.get("issue_types") or []),
                "issue_samples": list(record.get("issue_samples") or []),
                "rule_hits": dict(record.get("rule_hits") or {}),
                "script_changes_in_block":
                    int(record.get("script_changes_in_block") or 0),
                "residual_wrong": dict(record.get("residual_wrong") or {}),
                "evidence": _compact_block_evidence(record.get("evidence") or {})}
        questions[p + "_general"] = _general_question(p)
        questions[p + "_web"] = _web_question(p)
        questions[p + "_media"] = _media_question(p)
        questions[p + "_route"] = _route_question(p)
        items.append(item)
    state = {"schema_version": SCHEMA_VERSION,
             "evidence_schema": EVIDENCE_SCHEMA,
             "business": BUSINESS,
             "policy": dict(POLICY),
             "policy_variant": str(variant or "default"),
             "items": items}
    return state, questions, items


# ---------------------------------------------------------------- 影子执行


def _summary(client, blocks_total):
    status = dict(getattr(client, "status", {}) or {})
    return {"schema_version": SCHEMA_VERSION,
            "evidence_schema": EVIDENCE_SCHEMA,
            "business": BUSINESS,
            "policy": dict(POLICY),
            "active": bool(status.get("active")),
            "mode": str(status.get("mode") or "off"),
            "model": status.get("model") or "decision-model-preview",
            "endpoint": status.get("endpoint") or "",
            "reason": status.get("reason") or "not_configured",
            "blocks_total": blocks_total, "selected": 0, "evaluated": 0,
            "jev_evaluated": 0, "requests": 0, "truncated": 0, "gated": 0,
            "gate_reasons": {}, "issue_kinds": {},
            "would_skip": 0, "would_skip_cues": 0,
            "would_save": 0, "needs_web": 0,
            "routes": {}, "items": [], "errors": []}


def apply_triage_shadow(client, records, *, round_no=1, log=None,
                        max_blocks=None, batch_size=None, registry=None):
    """分诊影子入口：只写 summary 报告，**绝不改动 pending / 绝不跳过生成式**。

    records 由 collect_triage_records 产出（块级记录快照）；decision_client
    为 None 或未激活（decision_mode=off）时零请求直接返回。批默认
    BLOCKS_PER_REQUEST=4（每块 4 问 ≤ Jev 单请求 16 题上限）。逐批：
    本地确定性闸门分流 → client.decide → 记各问 choice/confidence；
    异常整批 degraded。would_skip = 本地闸门判「本可跳过」的块数；
    would_save = 按每请求 4 块折算的估算可省请求数（影子口径，仅供观测）。
    """
    records = list(records or [])
    summary = _summary(client, len(records))
    if not records or client is None or not getattr(client, "active", False):
        return summary
    cfg = dict(getattr(client, "config", {}) or {})
    limit = _int_setting(max_blocks if max_blocks is not None
                         else cfg.get("decision_max_items"), 32, 0, 512)
    batch_size = _int_setting(batch_size if batch_size is not None
                              else cfg.get("decision_batch_size"),
                              BLOCKS_PER_REQUEST, 1, BLOCKS_PER_REQUEST)
    selected = records[:limit]
    summary["selected"] = len(selected)
    summary["truncated"] = max(0, len(records) - len(selected))

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
        for i, record in enumerate(batch):
            for k in record.get("issue_types") or []:
                summary["issue_kinds"][str(k)] = \
                    summary["issue_kinds"].get(str(k), 0) + 1
            gate, why = _gate_route_triage(record, round_no)
            if gate:
                summary["gated"] += 1
                summary["evaluated"] += 1
                summary["gate_reasons"][why] = \
                    summary["gate_reasons"].get(why, 0) + 1
                if gate == "skip_generative":
                    summary["would_skip"] += 1
                    summary["would_skip_cues"] += \
                        int(record.get("cue_total") or 0)
                else:
                    summary["needs_web"] += 1
                summary["routes"][gate] = summary["routes"].get(gate, 0) + 1
                entries[i] = {"block": record.get("block"),
                              "cue_range": record.get("cue_range"),
                              "status": "gated", "route": gate, "gate": why,
                              "confidence": 1.0,
                              "reason": "本地确定性闸门；未调用 Jev"}
            else:
                pending.append(record)
                pending_pos.append(i)
        if pending:
            try:
                state, questions, items = build_triage_request(pending)
                response = client.decide(state, questions)
                summary["requests"] += 1
                for pos, item in zip(pending_pos, items):
                    p = str(item.get("question"))
                    choices = {}
                    confidence = None
                    for slot in ("general", "web", "media", "route"):
                        answer = response["answers"].get(p + "_" + slot) or {}
                        choices[slot] = str(answer.get("choice") or "")
                        if slot == "general":
                            try:
                                confidence = float(answer.get("confidence"))
                            except (TypeError, ValueError):
                                confidence = None
                        bucket = "%s_%s" % (slot, choices[slot] or "unknown")
                        summary["routes"][bucket] = \
                            summary["routes"].get(bucket, 0) + 1
                    summary["evaluated"] += 1
                    summary["jev_evaluated"] += 1
                    entries[pos] = {"block": item.get("block"),
                                    "cue_range": item.get("cue_range"),
                                    "status": "ok",
                                    "choice_general": choices["general"],
                                    "choice_web": choices["web"],
                                    "choice_media": choices["media"],
                                    "choice_route": choices["route"],
                                    "confidence": confidence,
                                    "model": response.get("model"),
                                    "request_id": response.get("request_id")}
            except Exception as exc:  # noqa: BLE001 — 云端失败不影响校准链路
                message = "%s: %s" % (type(exc).__name__, str(exc)[:240])
                summary["errors"].append({
                    "first_block": pending[0].get("block") if pending else None,
                    "count": len(pending), "error": message})
                for pos in pending_pos:
                    entries[pos] = {"block": batch[pos].get("block"),
                                    "cue_range": batch[pos].get("cue_range"),
                                    "status": "degraded", "reason": message}
                _say("Jev 分诊影子本批降级，生成式校准链路保持不变：%s"
                     % message, "err")
        summary["items"].extend([x for x in entries if x is not None])
        _say("Jev 分诊影子：%d/%d 块（本地闸门 %d，Jev %d；影子口径本可省 "
             "%d 块 / 约 %d 请求）" %
             (min(offset + len(batch), len(selected)), len(selected),
              summary["gated"], summary["jev_evaluated"],
              summary["would_skip"], summary["would_save"]))
    # would_save：影子口径估算——跳过块按每请求 4 块折算成可省请求数
    summary["would_save"] = (summary["would_skip"] + BLOCKS_PER_REQUEST - 1) \
        // BLOCKS_PER_REQUEST if summary["would_skip"] else 0
    return summary


# ---------------------------------------------------------------- 报告渲染


def _fmt_conf(value):
    try:
        f = float(value)
        return "%.3f" % f if f == f and f not in (float("inf"),
                                                  float("-inf")) else "—"
    except (TypeError, ValueError):
        return "—"


def render_triage_section(summary):
    """渲染「附：Jev 生成前分诊影子」小节（纯函数、幂等）。

    同一 summary 重复渲染逐字节一致；三态（未激活/空记录、正常、降级）都
    完整可渲染。返回 list[str]，调用方自行以空行拼进报告。
    """
    s = dict(summary or {})
    items = list(s.get("items") or [])
    errors = list(s.get("errors") or [])
    degraded = sum(1 for it in items if it.get("status") == "degraded")
    lines = ["## 附：Jev 生成前分诊影子（不改动生成式校准链路）", ""]
    lines.append(
        "- 激活：%s；模式：%s；块数：%d；选中：%d；Jev 分诊：%d；本地闸门：%d"
        "（本可跳过 %d 块 / %d 条 cue，估算可省 %d 请求；需联网 %d）；降级：%d"
        % ("是" if s.get("active") else "否", str(s.get("mode") or "off"),
           int(s.get("blocks_total") or 0), int(s.get("selected") or 0),
           int(s.get("jev_evaluated") or 0), int(s.get("gated") or 0),
           int(s.get("would_skip") or 0), int(s.get("would_skip_cues") or 0),
           int(s.get("would_save") or 0), int(s.get("needs_web") or 0),
           degraded))
    if not s.get("active"):
        lines.append("- 未激活原因：%s"
                     % str(s.get("reason") or "not_configured").replace("|", "/"))
    kinds = dict(s.get("issue_kinds") or {})
    if kinds:
        lines.append("- issue 分布：" + "、".join(
            "%s=%d" % (k, kinds[k]) for k in sorted(kinds)))
    gate_reasons = dict(s.get("gate_reasons") or {})
    if gate_reasons:
        lines.append("- 本地闸门原因：" + "、".join(
            "%s=%d" % (k, gate_reasons[k]) for k in sorted(gate_reasons)))
    if errors:
        lines.append("- 降级批次：" + "；".join(
            "%s（%d 块）" % (str(e.get("error") or "").replace("|", "/"),
                             int(e.get("count") or 0)) for e in errors))
    if not items:
        lines.append("- （无分诊记录）")
        lines.append("> 影子分诊只记录 would_skip / would_save，绝不跳过任何"
                     "生成式调用；机械基线 / 参考行保护 / verify 始终执行。")
        return lines
    lines += ["", "| 块 | cue范围 | Jev general | web | media | route | 置信度 "
              "| 状态 |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for it in items:
        block = str(it.get("block") or "")
        rng = str(it.get("cue_range") or "").replace("|", "/")
        status = str(it.get("status") or "")
        if status == "gated":
            lines.append("| %s | %s | — | — | — | %s | %s | 本地闸门：%s |" % (
                block, rng, str(it.get("route") or "—"),
                _fmt_conf(it.get("confidence")),
                str(it.get("gate") or "-").replace("|", "/")))
        elif status == "degraded":
            lines.append("| %s | %s | — | — | — | — | — | 降级：%s |" % (
                block, rng,
                str(it.get("reason") or "-").replace("|", "/")))
        else:
            lines.append("| %s | %s | %s | %s | %s | %s | %s | 已记录 |" % (
                block, rng, str(it.get("choice_general") or "—"),
                str(it.get("choice_web") or "—"),
                str(it.get("choice_media") or "—"),
                str(it.get("choice_route") or "—"),
                _fmt_conf(it.get("confidence"))))
    lines += ["", "> 影子分诊只记录 would_skip / would_save，不跳过任何生成式"
              "调用；gated 行是本地确定性闸门（未调用 Jev），仅用于评估"
              "「若启用分诊门禁可省多少」，不构成实际决策。",
              "> 机械基线 / 参考行保护 / verify 与本节无关，始终全量执行。"]
    return lines


__all__ = ["SCHEMA_VERSION", "EVIDENCE_SCHEMA", "BUSINESS", "POLICY",
           "MAX_QUESTIONS", "QUESTIONS_PER_BLOCK", "BLOCKS_PER_REQUEST",
           "MIN_CUES_GATE", "ISSUE_KINDS", "collect_triage_records",
           "triage_evidence_text", "_gate_route_triage",
           "build_triage_request", "apply_triage_shadow",
           "render_triage_section"]
