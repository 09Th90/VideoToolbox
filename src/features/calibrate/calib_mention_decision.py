# -*- coding: utf-8 -*-
# @version 3.3.1
"""L3 对象级 mention 的 Jev 结构化影子审核（shadow-only，不产生任何硬裁决）。

定位：calib_decision（accepted 采纳项复核）之外的第二条影子链——对象级 mention
视角。对 process 返回的 rows 离线重建 mention 决策记录（v1 零缝：calib_core 一行
不改，全部数据从 rows + 纯函数重建），把多目标消歧（tb_fail/ambiguous_dis0）、
疑似漏译（unresolved_proper）、可锚定错形（anchorable_wrong）与 scoping 排除
（blocked）送 Jev 结构化裁决；结果只写入返回的 summary 报告。

铁律：
  * 影子非阻断——本模块绝不回写 accepted/字幕/rows/hits，异常整批降级 degraded；
  * 引擎纯度——只 import calib_core.mention / calib_core.asr 的纯函数
    （pair_cue/scope_state/build_maps/_ref_for_match 等，无网络），
    绝不 import calib_core.engine / calib_core.process；
  * 用户裁决——当前 shadow-only（探针 gated 升级是后续工作），policy 恒为
    {shadow_only: True, allow_text_generation: False}；
  * 无网络硬依赖——decision_client 为 None 或未激活时零请求直接返回。

Jev 看不到本地对象库，因此每条记录都附带候选证据卡（build_mention_evidence，
对齐 calib_evidence 的 compact 口径），否则模型会凭记忆猜官方译名。
"""
from __future__ import annotations

from .calib_evidence import _load_registry, _works

SCHEMA_VERSION = "vt.calibrate.mention_review.v1"
EVIDENCE_SCHEMA = "vt.calibrate.mention_evidence.v1"

#: kind 分类优先级（一行 cue 命中多类时取最靠前者；契约定序，不可重排）
KIND_PRIORITY = ("tb_fail", "ambiguous_dis0", "unresolved_proper",
                 "anchorable_wrong", "blocked")

#: 单请求问题上限（对齐 tools/decision_client.MAX_QUESTIONS = 16）
MAX_QUESTIONS = 16


def _int_setting(value, default, low, high):
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def _mention_kit():
    """惰性加载 calib_core 纯函数（引擎边界接缝；失败即证据层降级，不阻断）。"""
    from calib_core.mention import (MentionPairer, build_maps, scope_state,
                                    longest_bounded, _parent_tiebreak,
                                    OBJ_CANONS)
    from calib_core.asr import _ref_for_match
    return {"MentionPairer": MentionPairer, "build_maps": build_maps,
            "scope_state": scope_state, "longest_bounded": longest_bounded,
            "_parent_tiebreak": _parent_tiebreak, "OBJ_CANONS": OBJ_CANONS,
            "_ref_for_match": _ref_for_match}


def _substantive(canon_list):
    """剔除音乐/通用词候选（ref mention 无消歧价值的类目，mention.py 同款口径）。

    引擎层不可用时全量保留（宁可多审不可漏审），保证闸门永不因依赖缺失误放行。
    """
    try:
        from calib_core.mention import _is_generic, _is_music
    except Exception:  # noqa: BLE001 — 分类依赖缺失时退化为不过滤
        return list(canon_list)
    return [c for c in canon_list if not (_is_music({c}) or _is_generic({c}))]


# ---------------------------------------------------------------- 离线重建


def _tb_fail_targets(M, anchor, zh, kit):
    """重扫 anchor 定位 tie-break 失败的多目标 mention 候选（只读归因）。

    scope_state 的 stats 只回计数；这里按同一裁决顺序（zh 交集→parent 链）
    找出真正失败的多目标 mention，把它们的候选并成 T。不改任何引擎状态。
    """
    ref_ms = kit["longest_bounded"](M["ref_auto"], (anchor or "").lower()) \
        if anchor else []
    zh_ms = kit["longest_bounded"](M["zh_auto"], zh or "")
    targets = set()
    for i, (_, _, _, rt) in enumerate(ref_ms):
        if len(rt) <= 1:
            continue
        zt = set(zh_ms[i][3]) if i < len(zh_ms) else set()
        if len(rt & zt) == 1:                      # 规则1：zh 序次交集已裁决
            continue
        if kit["_parent_tiebreak"](set(rt)):       # 规则2：parent 链已裁决
            continue
        targets |= set(rt)                         # 保守回退（tb_fail 分支）
    return targets


def _classify_cue(res, enabled, R, stats, M, zh, anchor, kit):
    """从 pair_cue/scope_state 结果离线分类，返回 (kind, T, extra)。

    anchor = _ref_for_match(ref)（scope_state 同款锚定行）。kind=None 表示本 cue
    无对象级行为后果，不产生审核记录。extra 仅 anchorable_wrong 时携带
    {"wrong", "right"}（本地最小替换验证用）。
    """
    zh_map = M["zh_map"]
    # 1) tb_fail：多目标 tie-break 失败，保守回退全候选（对象 scoping 有行为后果）
    if enabled and stats.get("tb_fail", 0) > 0:
        targets = _tb_fail_targets(M, anchor, zh, kit)
        if not targets and R:
            targets = set(R)
        return "tb_fail", targets, None
    # 2) ambiguous_dis0：ref 多目标且 zh 未消歧（交集≠1）
    amb_dis0 = [a for a in (res.get("ambiguous") or ()) if not a[5]]
    if amb_dis0:
        targets = set()
        for a in amb_dis0:
            targets |= set(a[2])
        return "ambiguous_dis0", targets, None
    # 3) unresolved_proper：ref mention 在中文行无对应（非音乐/通用，疑似漏译）
    if res.get("unresolved_proper"):
        targets = set()
        for u in res["unresolved_proper"]:
            targets |= set(u[2])
        return "unresolved_proper", targets, None
    # 4) anchorable_wrong：残留错形可被 ref 单目标锚定（本地最小替换可验证）
    if res.get("anchorable_wrong", 0) > 0:
        wrong_keys = M["wrong_keys"]
        for i, rs, zs, rt in res.get("resolved") or ():
            if zs in wrong_keys and rt:
                return ("anchorable_wrong", {rt[0]},
                        {"wrong": zs, "right": rt[0]})
        return "anchorable_wrong", set(), None
    # 5) blocked：对象 scoping 启用且 zh 行存在被 gate 排除的对象规则（right∉R）
    if enabled and R:
        obj_canons = kit["OBJ_CANONS"] if kit else frozenset()
        blocked = {t for _, _, _, zt in (res.get("zh_ms") or ()) for t in zt
                   if t in obj_canons and t not in R}
        if blocked:
            return "blocked", blocked, None
    return None, set(), None


def collect_records(rows, mode, registry=None):
    """v1 零缝：从 process 的 rows 离线重建 mention 决策记录。

    rows 元素 = (num, old中文原行, new, ref参考行)。对每行用
    MentionPairer(mode).pair(old, ref) + scope_state(build_maps(mode), old,
    _ref_for_match(ref)) 重建分类（tb_fail/ambiguous_dis0/unresolved_proper/
    anchorable_wrong/blocked，按 KIND_PRIORITY 取首个命中）。

    覆盖定理：所有有行为后果的 cue 必在 rows，因此离线重建可完整覆盖；
    无命中的行不产生记录。返回 list[dict]，每条
    {num, kind, zh, new, ref, T, R, stats, [anchor], evidence}。
    """
    kit = _mention_kit()
    pairer = kit["MentionPairer"](mode)
    M = kit["build_maps"](mode)
    if registry is None:
        registry, _source = _load_registry()
    records = []
    for row in rows or []:
        cells = list(row[:4]) + [""] * (4 - len(row[:4]))
        num, old, new, ref = cells
        old = str(old or "")
        ref = str(ref or "")
        res = pairer.pair(old, ref)
        anchor = kit["_ref_for_match"](ref)
        enabled, R, stats = kit["scope_state"](M, old, anchor)
        kind, T, extra = _classify_cue(res, enabled, R, stats, M, old, anchor, kit)
        if kind is None:
            continue
        record = {"num": num, "kind": kind, "zh": old, "new": str(new or ""),
                  "ref": ref, "T": sorted(T),
                  "R": sorted(R) if R else [], "stats": dict(stats)}
        if extra:
            record["anchor"] = extra
        record["evidence"] = build_mention_evidence(record, registry)
        records.append(record)
    return records


# ---------------------------------------------------------------- 证据卡


def build_mention_evidence(record, registry=None):
    """候选证据卡：对 T 中各 canonical 取对象库规格，并标注是否在 zh 行出现。

    Jev 看不到对象库，必须把 official/en/ja/ko/aliases/kind/category/work 塞进
    state；status ∈ ok/partial/missing（对齐 calib_evidence 的缺口语义）。
    """
    if registry is None:
        registry, source = _load_registry()
    else:
        source = "provided"
    zh = str(record.get("zh") or "")
    targets = list(record.get("T") or [])
    candidates, missing = [], 0
    for canon in targets:
        spec = registry.get(canon) if registry else None
        if spec is None:
            missing += 1
            candidates.append({"canonical": canon, "official": canon,
                               "status": "missing"})
            continue
        aliases = [str(a) for a in (getattr(spec, "aliases", ()) or ()) if a]
        variants = [str(v) for v in (getattr(spec, "variants", ()) or ()) if v]
        candidates.append({
            "canonical": canon,
            "official": getattr(spec, "canonical", "") or canon,
            "kind": getattr(spec, "kind", "") or "unknown",
            "category": getattr(spec, "category", "") or "",
            "work": _works(getattr(spec, "category", "") or ""),
            "en": getattr(spec, "en", "") or "",
            "ja": getattr(spec, "ja", "") or "",
            "ko": getattr(spec, "ko", "") or "",
            "aliases": aliases[:8],
            "in_zh": any(f and f in zh for f in ([canon] + aliases + variants)),
        })
    if not targets or missing == len(targets):
        status = "missing"
    elif missing:
        status = "partial"
    else:
        status = "ok"
    evidence = {"schema_version": EVIDENCE_SCHEMA, "status": status,
                "source": source, "cue_kind": record.get("kind") or "",
                "candidates": candidates}
    evidence["text"] = mention_evidence_text(evidence)
    return evidence


def mention_evidence_text(evidence):
    """把候选证据卡压成一句可直接判读的中文事实卡（对齐 evidence_text）。"""
    cands = evidence.get("candidates") or []
    if not cands:
        return "本条无候选对象。"
    parts = []
    for c in cands:
        if c.get("status") == "missing":
            parts.append("「%s」本地对象库无规格" % c.get("canonical"))
            continue
        seen = "已在中文行出现" if c.get("in_zh") else "未在中文行出现"
        parts.append("「%s」（%s/%s，%s）" % (c.get("official"), c.get("kind"),
                                             c.get("work") or "未标注作品", seen))
    return "候选对象：" + "；".join(parts) + "。"


def compact_for_prompt(evidence):
    """去掉空字段控制 state 体积；status 恒保留（对齐 calib_evidence.compact）。"""
    drop = ("schema_version", "source", "cue_kind")
    out = {}
    for k, v in evidence.items():
        if k in drop or v in ("", None, [], {}, False):
            continue
        out[k] = v
    if "status" in evidence:
        out["status"] = evidence["status"]
    if "text" not in out:
        out["text"] = mention_evidence_text(evidence)
    return out


# ---------------------------------------------------------------- 本地闸门


def _gate_route_record(record):
    """本地闸门先行，不调 Jev。返回 (route, why)；route="" 表示送 Jev。

    route ∈ gated/manual_review/questionable/consistent（对齐 calib_decision）：
      * T 剔音乐/通用词后仅剩 1（或 0）候选 → gated（本地可裁决）；
      * anchorable_wrong 且本地最小替换可验证 → gated；
      * 证据缺失/部分缺失或候选跨作品 → manual_review。
    """
    kind = record.get("kind") or ""
    zh = str(record.get("zh") or "")
    if kind == "anchorable_wrong":
        anchor = record.get("anchor") or {}
        wrong, right = anchor.get("wrong") or "", anchor.get("right") or ""
        if wrong and right and wrong in zh:
            return "gated", "anchorable_min_replace_verified"
    targets = list(record.get("T") or [])
    if targets:
        kept = _substantive(targets)
        if len(kept) <= 1:
            return "gated", ("single_candidate_after_filter" if kept
                             else "no_candidate_after_filter")
    evidence = record.get("evidence") or {}
    status = evidence.get("status")
    if status not in ("ok", None):
        return "manual_review", "evidence_%s" % status
    works = {(c.get("work") or "") for c in (evidence.get("candidates") or [])
             if c.get("status") != "missing"} - {""}
    if len(works) > 1:
        return "manual_review", "candidates_cross_work"
    return "", ""


def _local_resolution(record, why):
    """gated 条目的本地裁决结果（只进报告，绝不回写任何校准产物）。"""
    if why == "anchorable_min_replace_verified":
        return (record.get("anchor") or {}).get("right") or ""
    kept = _substantive(list(record.get("T") or []))
    return kept[0] if kept else ""


# ---------------------------------------------------------------- 请求构造


def _disambiguation_question(qname, record):
    """tb_fail/ambiguous_dis0：ref 多目标，本 cue 实际指哪个对象。"""
    criteria = {str(c): "ref 行多目标候选之一；若 zh 行语义与证据卡支持本 cue"
                       "指该对象，选它"
                for c in (record.get("T") or [])[:MAX_QUESTIONS - 1]}
    criteria["cannot_determine"] = "证据不足以确定本 cue 实际指哪个对象"
    return {"type": "choice", "criteria": criteria,
            "instructions": (
                "只裁决 state.items 中 question=%s 的对象指代：ref 行存在多目标"
                " mention，候选见 criteria，证据见 item.evidence。以 zh 行语义与"
                "证据卡为唯一依据判断本 cue 实际指哪个对象；不确定必须选 "
                "cannot_determine，不得凭记忆补官方名，不生成新文本。" % qname)}


def _missing_question(qname, record):
    """unresolved_proper：该 ref mention 是否在中文行有对应译名。"""
    criteria = {str(c): "该 ref mention 对应此对象；中文行虽无同形译名但已用"
                       "其他表述覆盖"
                for c in (record.get("T") or [])[:MAX_QUESTIONS - 1]}
    criteria["not_missing"] = "中文行确实没有该对象的对应译名（疑似真漏译）"
    return {"type": "choice", "criteria": criteria,
            "instructions": (
                "只判断 state.items 中 question=%s 的 ref mention 是否在中文行"
                "有对应译名：ref 出现某对象的原文 mention，而中文行未见对应译名。"
                "若中文行已用其他表述覆盖该对象，选对应官方名；确实缺失才选 "
                "not_missing。以 item.evidence 为唯一官方事实来源，不生成新文本。"
                % qname)}


def _risk_question(qname, record):
    """blocked/anchorable_wrong 兜底：noul 误改风险概率。"""
    kind = record.get("kind") or ""
    if kind == "blocked":
        inst = (
            "估计 state.items 中 question=%s 的对象 scoping 排除决策风险概率"
            "（0=排除正确，1=高风险）。本 cue 多目标裁决后 R=%s，对象 %s 的替换"
            "规则被本地 gate 排除。结合 zh 行与证据卡判断：若排除防止了把其它"
            "对象的错形误改，给低概率；若 zh 行语义明显指被排除对象（漏改），"
            "给高概率。不生成新文本，不得凭记忆补官方名。"
            % (qname, record.get("R") or [], record.get("T") or []))
    else:
        inst = (
            "估计 state.items 中 question=%s 的锚定错形替换风险概率（0=安全，"
            "1=高风险）。候选证据见 item.evidence；若 zh 行语义与 ref 佐证一致"
            "支持替换成该对象官方名，给低概率；否则给高概率。不生成新文本。"
            % qname)
    return {"type": "noul", "instructions": inst}


def build_mention_request(records, registry=None, variant="evidence"):
    """构造一批 mention 审核请求，供生产与离线评测共用。

    单请求 ≤ MAX_QUESTIONS 题（超出部分由调用方分批，本函数只截断防御）。
    返回 (state, questions, items)。
    """
    items, questions = [], {}
    for pos, record in enumerate(list(records or [])[:MAX_QUESTIONS]):
        kind = record.get("kind") or ""
        qname = "mention_%d" % pos
        item = {"question": qname, "num": record.get("num"), "kind": kind,
                "zh": str(record.get("zh") or "")[:800],
                "ref": str(record.get("ref") or "")[:800],
                "R": list(record.get("R") or [])}
        evidence = record.get("evidence")
        if evidence is None:
            evidence = build_mention_evidence(record, registry)
        item["evidence"] = compact_for_prompt(evidence)
        if kind in ("tb_fail", "ambiguous_dis0"):
            questions[qname] = _disambiguation_question(qname, record)
        elif kind == "unresolved_proper":
            questions[qname] = _missing_question(qname, record)
        else:
            questions[qname] = _risk_question(qname, record)
        items.append(item)
    state = {"schema_version": SCHEMA_VERSION,
             "evidence_schema": EVIDENCE_SCHEMA,
             "business": "mention_disambiguation_review",
             "policy": {"shadow_only": True, "allow_text_generation": False,
                        "prompt_variant": variant},
             "items": items}
    return state, questions, items


# ---------------------------------------------------------------- 影子执行


def _summary(client, records_total):
    status = dict(getattr(client, "status", {}) or {})
    return {"schema_version": SCHEMA_VERSION,
            "evidence_schema": EVIDENCE_SCHEMA,
            "active": bool(status.get("active")),
            "mode": str(status.get("mode") or "off"),
            "model": status.get("model") or "decision-model-preview",
            "endpoint": status.get("endpoint") or "",
            "reason": status.get("reason") or "not_configured",
            "records_total": records_total, "selected": 0, "evaluated": 0,
            "jev_evaluated": 0, "requests": 0, "truncated": 0, "gated": 0,
            "gate_reasons": {}, "kinds": {},
            "routes": {}, "items": [], "errors": []}


def apply_mention_shadow(records, client, *, log=None, max_items=None,
                         batch_size=None, registry=None):
    """mention 影子审核入口：只写 summary 报告，绝不回写字幕/rows/hits。

    records 由 collect_records 产出；decision_client 为 None 或未激活时零请求
    直接返回（与 calib_decision.apply_shadow 同款降级口径）。limit 默认 32、
    batch 默认 8（≤ Jev 单请求 16 题上限）。逐批：本地闸门分流 → client.decide
    → 记 choice/confidence/probabilities；异常批整体 degraded + errors。
    """
    records = list(records or [])
    summary = _summary(client, len(records))
    if not records or client is None or not getattr(client, "active", False):
        return summary
    if registry is None:
        try:
            registry, _source = _load_registry()
        except Exception:  # noqa: BLE001 — 证据层不可用不能阻断影子审核
            registry = {}
    cfg = dict(getattr(client, "config", {}) or {})
    limit = _int_setting(max_items if max_items is not None
                         else cfg.get("decision_max_items"), 32, 0, 512)
    batch_size = _int_setting(batch_size if batch_size is not None
                              else cfg.get("decision_batch_size"), 8, 1, 8)
    selected = records[:limit]
    summary["selected"] = len(selected)
    summary["truncated"] = max(0, len(records) - len(selected))
    for r in selected:
        k = str(r.get("kind") or "")
        summary["kinds"][k] = summary["kinds"].get(k, 0) + 1

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
            gate, why = _gate_route_record(record)
            if gate:
                summary["gated"] += 1
                summary["evaluated"] += 1
                summary["gate_reasons"][why] = \
                    summary["gate_reasons"].get(why, 0) + 1
                summary["routes"][gate] = summary["routes"].get(gate, 0) + 1
                entry = {"num": record.get("num"), "kind": record.get("kind"),
                         "status": "gated", "choice": gate, "confidence": 1.0,
                         "probabilities": {gate: 1.0}, "gate": why,
                         "reason": "本地闸门；未调用 Jev"}
                if gate == "gated":
                    entry["resolved"] = _local_resolution(record, why)
                entries[i] = entry
            else:
                pending.append(record)
                pending_pos.append(i)
        if pending:
            try:
                state, questions, items = build_mention_request(pending, registry)
                response = client.decide(state, questions)
                summary["requests"] += 1
                for pos, item in zip(pending_pos, items):
                    answer = response["answers"][item["question"]]
                    if answer.get("type") == "noul":
                        risk = float(answer["noul"])
                        choice = "noul:%.2f" % risk
                        confidence = float(answer.get("confidence", 1.0 - risk))
                        bucket = "noul_risk_high" if risk >= 0.5 else "noul_risk_low"
                        summary["routes"][bucket] = \
                            summary["routes"].get(bucket, 0) + 1
                    else:
                        choice = str(answer["choice"])
                        confidence = float(answer["confidence"])
                        summary["routes"][choice] = \
                            summary["routes"].get(choice, 0) + 1
                    summary["evaluated"] += 1
                    summary["jev_evaluated"] += 1
                    entries[pos] = {
                        "num": item["num"], "kind": item.get("kind"),
                        "status": "ok", "choice": choice,
                        "confidence": confidence,
                        "probabilities": dict(answer.get("probabilities") or {}),
                        "model": response.get("model"),
                        "request_id": response.get("request_id"),
                    }
            except Exception as exc:  # noqa: BLE001 — 云端失败不影响校准产物
                message = "%s: %s" % (type(exc).__name__, str(exc)[:240])
                summary["errors"].append({
                    "first_num": pending[0].get("num") if pending else None,
                    "count": len(pending), "error": message})
                for pos in pending_pos:
                    entries[pos] = {"num": batch[pos].get("num"),
                                    "kind": batch[pos].get("kind"),
                                    "status": "degraded", "reason": message}
                _say("Jev mention 影子审核本批降级，校准结果保持不变：%s"
                     % message, "err")
        summary["items"].extend([x for x in entries if x is not None])
        _say("Jev mention 影子审核：%d/%d 条记录（本地闸门 %d，Jev %d）" %
             (min(offset + len(batch), len(selected)), len(selected),
              summary["gated"], summary["jev_evaluated"]))
    return summary


# ---------------------------------------------------------------- 报告渲染


def _fmt_conf(value):
    """置信度列格式化（防御：非有限数一律 —）。"""
    try:
        f = float(value)
        return "%.3f" % f if f == f and f not in (float("inf"), float("-inf")) \
            else "—"
    except (TypeError, ValueError):
        return "—"


def render_mention_section(summary):
    """渲染「附：Jev 对象级 mention 影子审核」小节（纯函数、幂等）。

    同一 summary 重复渲染逐字节一致；三态（未激活/空记录、正常、降级）都完整
    可渲染：统计行恒在；未激活补原因行；无 items 补「无审核记录」；有 items
    出三态表格（cue号/kind/候选/Jev choice/置信度/gated/降级）。candidates 列
    取 item["candidates"]（由挂载方按 records 并入；缺失显示 —）。
    返回 list[str]，调用方自行以空行拼进报告。
    """
    s = dict(summary or {})
    items = list(s.get("items") or [])
    errors = list(s.get("errors") or [])
    degraded = sum(1 for it in items if it.get("status") == "degraded")
    lines = ["## 附：Jev 对象级 mention 影子审核（不改动已校验字幕）", ""]
    lines.append(
        "- 激活：%s；模式：%s；记录：%d；选中：%d；Jev 复核：%d；本地闸门：%d；"
        "降级：%d；超预算：%d"
        % ("是" if s.get("active") else "否", str(s.get("mode") or "off"),
           int(s.get("records_total") or 0), int(s.get("selected") or 0),
           int(s.get("jev_evaluated") or 0), int(s.get("gated") or 0),
           degraded, int(s.get("truncated") or 0)))
    if not s.get("active"):
        lines.append("- 未激活原因：%s"
                     % str(s.get("reason") or "not_configured").replace("|", "/"))
    kinds = dict(s.get("kinds") or {})
    if kinds:
        lines.append("- kind 分布：" + "、".join(
            "%s=%d" % (k, kinds[k]) for k in sorted(kinds)))
    if errors:
        lines.append("- 降级批次：" + "；".join(
            "%s（%d 条）" % (str(e.get("error") or "").replace("|", "/"),
                             int(e.get("count") or 0)) for e in errors))
    if not items:
        lines.append("- （无审核记录）")
        lines.append("> Jev 不参与 R 裁决，仅影子提示；本节不回写任何校准产物。")
        return lines
    lines += ["", "| cue号 | kind | 候选 | Jev choice | 置信度 | gated | 降级 |",
              "| --- | --- | --- | --- | --- | --- | --- |"]
    for it in items:
        num = str(it.get("num") or "")
        kind = str(it.get("kind") or "")
        cands = "、".join(str(c) for c in (it.get("candidates") or ())) or "—"
        status = str(it.get("status") or "")
        if status == "gated":
            lines.append("| %s | %s | %s | %s | %s | %s | — |" % (
                num, kind, cands, str(it.get("choice") or "—"),
                _fmt_conf(it.get("confidence")),
                str(it.get("gate") or "-").replace("|", "/")))
        elif status == "degraded":
            lines.append("| %s | %s | %s | — | — | — | %s |" % (
                num, kind, cands,
                str(it.get("reason") or "-").replace("|", "/")))
        else:
            lines.append("| %s | %s | %s | %s | %s | — | — |" % (
                num, kind, cands, str(it.get("choice") or "—"),
                _fmt_conf(it.get("confidence"))))
    lines += ["", "> Jev 不参与 R 裁决，仅影子提示：choice/probability 只进本节与 "
              "*.mention_review.json 侧车，不回写 accepted/字幕/rows/hits。",
              "> gated 行是本地确定性闸门（未调用 Jev）；降级行保持校准结果原样。"]
    return lines


__all__ = ["SCHEMA_VERSION", "EVIDENCE_SCHEMA", "KIND_PRIORITY",
           "MAX_QUESTIONS", "collect_records", "build_mention_evidence",
           "mention_evidence_text", "compact_for_prompt", "_gate_route_record",
           "build_mention_request", "apply_mention_shadow",
           "render_mention_section"]
