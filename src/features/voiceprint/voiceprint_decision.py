# -*- coding: utf-8 -*-
# @version 3.3.1
"""声纹存疑 cue 的 Jev 结构化路由（Schema v2 三态：shadow / assist / auto）。

Jev 看不到音频，不能也不应凭台词猜说话人身份。这里只让它根据本地声纹分数、
竞争者分差、簇一致性和相邻 cue 状态给出路由建议；默认**影子模式**只追加
`details[i].jev`，绝不修改本地 verdict 或字幕。

三态（附录 A.3「决策结果使用约束」，用户裁决：默认全影子）：

  ======  =============================================================  ======
  阶段    行为                                                            默认
  ======  =============================================================  ======
  shadow  R0：批量请求 5 问/cue，答案只追加 ``details[i].jev``，           开
          verdict / 产物一个字节不动；异常整批 degraded。
  assist  R1：仅 review 且本地闸门未分流的 cue；输出白名单三件事          关
          （待复核排序 priority_manual 置前 / 报告建议列 / conflict
          标注），仍不回写 verdict、不增删产物。
  auto    R2：高置信（≥T1）∧ P(route)≥P1 ∧ evidence_quality 达标 ∧        关
          硬规则一致 ∧ 声学不冲突 ∧ 场景白名单，才允许把 review 的
          **路由三值**改掉；文本/时间轴/结构永不触碰；低置信 100% 待复核。
  ======  =============================================================  ======

Schema v2（业务层 ``vt.voiceprint.filter.v2``，见 ``vp_decision_schema.py``）：
每条 cue 5 问（content_role / evidence_conflict / cluster_split_needed /
route / evidence_quality），每请求最多 3 条 cue（5×3=15 ≤ 客户端上限 16）；
state 数值字段全部附带业务口径（STATE_FIELD_GLOSSARY 随 policy 下发）。

引擎纯度：本模块只消费 ``client.decide(state, questions)``（协议信封
vt.decision.v1 由 tools/decision_client 负责），不 import 任何网络/引擎/
音频代码——mock client 即可离线全量自测（``src/_selftest_voiceprint_decision.py``）。
"""
from __future__ import annotations

import math

from features.voiceprint import vp_decision_schema as S
from features.voiceprint.vp_decision_schema import (
    SCHEMA_VERSION, STATE_FIELD_GLOSSARY,
)

#: R0 历史：v1 影子路由的业务 Schema 版本（仅供历史报告/审计对照）。
SHADOW_SCHEMA_V1 = S.LEGACY_SHADOW_VERSION
#: WP5 预留：声源分离后端标识；未接入分离时恒为 "none"。
SEPARATION_BACKEND = "none"

#: v1 影子的「复核优先级」三值词汇（R0 历史报告仍用）。v2 的业务路由词汇是
#: keep/drop/review/cannot_determine（vp_decision_schema.ROUTE_OPTIONS）；
#: 两者并存，v1 词汇不再进 v2 请求的 criteria。
ROUTES = {
    "routine_review": "本地证据一致，按普通待复核处理",
    "priority_manual": "歧义或上下文冲突较高，优先人工听辨",
    "insufficient_evidence": "声纹或音频证据不足，需要补充证据后再判断",
}


def _int_setting(value, default, low, high):
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def _float_setting(value, default, low, high):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if v != v:
        return default
    return max(low, min(high, v))


def _finite(value):
    """float 化且拒绝 NaN/Inf（协议 allow_nan=False，state 一律不发 NaN）。"""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if v == v and math.isfinite(v) else None


# ---------------------------------------------------------------- 组/簇画像


def _group_key(row):
    """details 行的组键（画像聚合用）：说话人标签优先，其次本地簇号。"""
    spk = str(row.get("speaker") or "")
    if spk:
        return "s:" + spk
    try:
        lb = int(row.get("cluster"))
    except (TypeError, ValueError):
        return None
    return ("c:%d" % lb) if lb >= 0 else None


def _group_profiles(details, threshold):
    """按组聚合 details：每组的逐 cue 分数表 / 条数 / 簇一致性 / 目标先验。

    一致性 = 组内 cue 分数的标准差（0-1，越低越一致；有效分不足 2 条为
    None——单条无从谈「一致」）。目标先验 = 组内是否存在分数 ≥ keep_threshold
    的 cue（有的话，对该组任何成员的 drop 建议都要过「声学冲突」这道硬规则）。
    """
    groups = {}
    for row in details:
        key = _group_key(row)
        if key is None:
            continue
        g = groups.setdefault(key, {"scores": [], "size": 0})
        g["size"] += 1
        sc = _finite(row.get("score"))
        if sc is not None:
            g["scores"].append(sc)
    for g in groups.values():
        if len(g["scores"]) >= 2:
            mean = sum(g["scores"]) / len(g["scores"])
            var = sum((s - mean) ** 2 for s in g["scores"]) / len(g["scores"])
            g["consistency"] = round(min(1.0, math.sqrt(max(var, 0.0))), 6)
        else:
            g["consistency"] = None
        g["has_prior"] = any(s >= float(threshold) for s in g["scores"])
    return groups


def _resolve_group_key(row, group_scores):
    """details 行在 group_scores（spk_scores 形态）里的键。

    spk_scores 的键有两种形态：说话人标签（"说话人1"）与本地簇号——无标签时
    是 ``str(簇号)``（score_clusters），有标签混簇时是 ``"簇" + 簇号``
    （filter_srt 的 setdefault("簇"+k)）。两种都试。
    """
    if not isinstance(group_scores, dict) or not group_scores:
        return None
    spk = str(row.get("speaker") or "")
    if spk and isinstance(group_scores.get(spk), dict):
        return spk
    try:
        lb = int(row.get("cluster"))
    except (TypeError, ValueError):
        return None
    if lb >= 0:
        for key in (str(lb), "簇" + str(lb)):
            if isinstance(group_scores.get(key), dict):
                return key
    return None


def _group_score(row, group_scores):
    """所属组的簇级分数（无组或无有效分为 None）。"""
    key = _resolve_group_key(row, group_scores)
    if key is None:
        return None
    return _finite((group_scores.get(key) or {}).get("score"))


def _best_competitor(row, group_scores):
    """最强竞争者分：其他组对目标模板的最高簇分；本组无有效分时全体皆竞争者。"""
    if not isinstance(group_scores, dict) or not group_scores:
        return None
    own_key = _resolve_group_key(row, group_scores)
    scores = []
    for key, info in group_scores.items():
        if key == own_key or not isinstance(info, dict):
            continue
        v = _finite(info.get("score"))
        if v is not None:
            scores.append(v)
    return max(scores) if scores else None


def _asr_is_target(row, group_scores, threshold):
    """ASR 标签组是否命中主播（组簇分 ≥ keep_threshold）。

    无 ASR 标签或无有效簇分 → None（state 发 null，不冒充布尔）。
    """
    if not str(row.get("speaker") or ""):
        return None
    key = _resolve_group_key(row, group_scores)
    if key is None:
        return None
    v = _finite((group_scores.get(key) or {}).get("score"))
    if v is None:
        return None
    return v >= float(threshold)


def _neighbor(decisions, details, index):
    """邻接 (text, state)；越界或缺 cue 返回 ("", None)。"""
    if index < 0 or index >= len(details):
        return "", None
    row = details[index]
    cue = decisions[index][0] if index < len(decisions) else None
    text = str(getattr(cue, "text", "") or "")[:200] if cue is not None else ""
    state = str(row.get("state") or "")
    return text, (state or None)


# ---------------------------------------------------------------- 请求构造


def _shadow_policy(threshold, low):
    return {"shadow_only": True, "allow_verdict_change": False,
            "keep_threshold": float(threshold), "low_threshold": float(low),
            "field_glossary": dict(STATE_FIELD_GLOSSARY)}


def _assist_policy(threshold, low):
    return {"shadow_only": False, "allow_verdict_change": False,
            "stage": "assist", "routing_constraints": "appendix_a3",
            "cannot_determine_means_review": True,
            "keep_threshold": float(threshold), "low_threshold": float(low),
            "field_glossary": dict(STATE_FIELD_GLOSSARY)}


def _auto_policy(threshold, low, whitelist, conf_t1, prob_p1):
    return {"shadow_only": False, "allow_verdict_change": True,
            "stage": "auto", "routing_constraints": "appendix_a3",
            "route_values_only": True, "no_text_timeline_change": True,
            "scene_whitelist": sorted(whitelist),
            "auto_conf_t1": float(conf_t1), "auto_prob_p1": float(prob_p1),
            "keep_threshold": float(threshold), "low_threshold": float(low),
            "field_glossary": dict(STATE_FIELD_GLOSSARY)}


def _build_items(decisions, details, indexes, profiles, group_scores,
                 threshold, low):
    """Schema v2 的 state.items（保留 v1 八字段语义 + 新增业务字段）。"""
    items = []
    for pos, index in enumerate(indexes):
        row = details[index]
        cue = decisions[index][0] if index < len(decisions) else None
        prefix = "c%d" % pos
        route_q = prefix + "_route"
        target = _finite(row.get("score"))
        competitor = _best_competitor(row, group_scores)
        own_key = _resolve_group_key(row, group_scores)
        ginfo = group_scores.get(own_key) if own_key else None
        prof = profiles.get(_group_key(row)) or {}
        if isinstance(ginfo, dict):
            n = ginfo.get("n")
            size = (int(n) if isinstance(n, (int, float)) and float(n) == float(n)
                    and float(n) >= 1 else prof.get("size"))
        else:
            size = prof.get("size")
        margin = None
        if target is not None and competitor is not None:
            margin = round(target - competitor, 6)
        prev_t, prev_s = _neighbor(decisions, details, index - 1)
        next_t, next_s = _neighbor(decisions, details, index + 1)
        items.append({
            "question": route_q, "prefix": prefix,
            "questions": list(S.question_set(prefix).keys()),
            "num": row.get("num"),
            "start_ms": row.get("start"), "end_ms": row.get("end"),
            "duration_ms": row.get("duration_ms"),
            "text": str(getattr(cue, "text", "") or "")[:600],
            "text_lang": S.detect_text_lang(getattr(cue, "text", "")),
            "asr_speaker": row.get("speaker") or "",
            "asr_speaker_is_target": _asr_is_target(row, group_scores, threshold),
            "prev_text": prev_t, "prev_state": prev_s,
            "next_text": next_t, "next_state": next_s,
            "local_state": "review",
            "local_reason": row.get("reason") or "",
            "original_route": str(row.get("state") or "review"),
            "target_score": target,
            "best_competitor_score": competitor,
            "score_margin": margin,
            "cluster_score": _finite((ginfo or {}).get("score")) if own_key else None,
            "cluster_consistency": prof.get("consistency"),
            "cluster_size": size,
            "cluster_has_target_prior": bool(prof.get("has_prior")),
            "separation_backend": SEPARATION_BACKEND,
        })
    return items


def _build_request(decisions, details, indexes, profiles, group_scores, policy):
    """一批 cue 的 (state, questions, items)。questions = 5 问/cue。"""
    items = _build_items(decisions, details, indexes, profiles, group_scores,
                         policy["keep_threshold"], policy["low_threshold"])
    questions = {}
    for item in items:
        questions.update(S.question_set(item["prefix"]))
    state = {"schema_version": SCHEMA_VERSION,
             "business": "voiceprint_review_routing",
             "policy": policy, "items": items}
    return state, questions, items


def _parse_answers(item, response):
    """解析一条 cue 的 5 问答案。

    route 问严格解析（缺键/类型错会抛异常 → 调用方整批降级）；辅助问防御式
    解析（拿不到就 None，绝不因辅助问形态异常拖垮整批）。
    """
    answers = response["answers"]
    route = answers[item["question"]]
    prefix = item["prefix"]

    def _aux(key, field, as_choice=False):
        a = answers.get(prefix + "_" + key)
        if not isinstance(a, dict):
            return None
        v = a.get(field)
        if as_choice:
            return str(v) if v is not None else None
        try:
            v = float(v)
        except (TypeError, ValueError):
            return None
        return v if v == v else None

    return {"choice": str(route["choice"]),
            "confidence": float(route["confidence"]),
            "probabilities": dict(route.get("probabilities") or {}),
            "content_role": _aux("role", "choice", as_choice=True),
            "evidence_conflict": _aux("conflict", "noul"),
            "cluster_split_needed": _aux("split", "noul"),
            "evidence_quality_raw": _aux("quality", "score"),
            "model": response.get("model"),
            "request_id": response.get("request_id"),
            "questions": {name: answers.get(name)
                          for name in item["questions"]
                          if name != item["question"]}}


def _summary(client, stage="shadow"):
    status = dict(getattr(client, "status", {}) or {})
    return {"schema_version": SCHEMA_VERSION, "stage": stage,
            "active": bool(status.get("active")),
            "mode": str(status.get("mode") or "off"),
            "model": status.get("model") or "decision-model-preview",
            "endpoint": status.get("endpoint") or "",
            "reason": status.get("reason") or "not_configured",
            "review_total": 0, "selected": 0, "evaluated": 0,
            "requests": 0, "truncated": 0, "routes": {}, "errors": []}


def _batch_limits(client, max_items, batch_size):
    cfg = dict(getattr(client, "config", {}) or {})
    limit = _int_setting(max_items if max_items is not None
                         else cfg.get("decision_max_items"), 32, 0, 512)
    # v2 语义：decision_batch_size = 每请求 cue 数上限。
    # 5 问/cue，3 条 = 15 问 ≤ 客户端单请求上限 16；超过 3 条必须分批。
    batch = _int_setting(batch_size if batch_size is not None
                         else cfg.get("decision_batch_size"),
                         S.MAX_CUES_PER_REQUEST, 1, S.MAX_CUES_PER_REQUEST)
    return limit, batch


def _say(progress, text):
    if progress:
        try:
            progress(text)
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------- R0 影子


def apply_shadow(decisions, details, client, *, threshold, low,
                 max_items=None, batch_size=None, progress=None,
                 group_scores=None):
    """对最终仍为 review 的 cue 批量路由，返回摘要并就地追加 details[i].jev。

    `decisions` 的三元组从不回写。任何网络/协议异常只给本批追加 degraded 证据，
    主流程继续按本地 CAM++ 结果写正式 SRT 与待复核 SRT。

    Schema v2：state 携带竞争者分差/簇一致性/邻接文本等业务字段（口径随
    policy.field_glossary 下发），每条 cue 5 问、每请求最多 3 条 cue；
    jev 除 route 主答案外还记录其余四问原始答案（``jev["questions"]``），
    供影子评估离线复盘。
    """
    summary = _summary(client, stage="shadow")
    candidates = [i for i, row in enumerate(details)
                  if row.get("state") == "review"]
    summary["review_total"] = len(candidates)
    if not candidates or client is None or not getattr(client, "active", False):
        return summary
    limit, batch_size = _batch_limits(client, max_items, batch_size)
    selected = candidates[:limit]
    summary["selected"] = len(selected)
    summary["truncated"] = max(0, len(candidates) - len(selected))
    profiles = _group_profiles(details, threshold)
    policy = _shadow_policy(threshold, low)

    for offset in range(0, len(selected), batch_size):
        indexes = selected[offset:offset + batch_size]
        state, questions, items = _build_request(
            decisions, details, indexes, profiles, group_scores, policy)
        try:
            response = client.decide(state, questions)
            summary["requests"] += 1
            for index, item in zip(indexes, items):
                parsed = _parse_answers(item, response)
                choice = parsed["choice"]
                details[index]["jev"] = {
                    "mode": "shadow", "status": "ok", "schema": SCHEMA_VERSION,
                    "choice": choice, "confidence": parsed["confidence"],
                    "probabilities": parsed["probabilities"],
                    "questions": parsed["questions"],
                    "content_role": parsed["content_role"],
                    "evidence_conflict": parsed["evidence_conflict"],
                    "cluster_split_needed": parsed["cluster_split_needed"],
                    "evidence_quality": S.quality_level(
                        parsed["evidence_quality_raw"]),
                    "model": parsed["model"], "request_id": parsed["request_id"],
                }
                summary["routes"][choice] = summary["routes"].get(choice, 0) + 1
                summary["evaluated"] += 1
        except Exception as exc:  # noqa: BLE001 — 云端复核绝不影响本地筛选
            message = "%s: %s" % (type(exc).__name__, str(exc)[:240])
            summary["errors"].append({"first_num": items[0].get("num") if items else None,
                                      "count": len(items), "error": message})
            for index in indexes:
                details[index]["jev"] = {"mode": "shadow", "status": "degraded",
                                         "reason": message}
        _say(progress, "Jev 影子路由：%d/%d 条存疑 cue" %
             (min(offset + len(indexes), len(selected)), len(selected)))
    return summary


# ---------------------------------------------------------------- R1 辅助


def _local_gate(row):
    """本地确定性闸门（移植 calib_decision._gate_route 的范式）。

    先把**本地就能确定**的分流掉，不为它们浪费 Jev 请求：
      * target_score 无效（音频缺失/过短且无簇可借）→ 证据不可核实，
        直接待复核（gate=evidence_missing），不调用 Jev。
    返回 (gate_route, gate_reason)；未命中返回 ("", "")。
    """
    if _finite(row.get("score")) is None:
        return "review", "evidence_missing"
    return "", ""


def _assist_record(row, parsed, threshold, low, profiles):
    """按附录 A.3 约束把 5 问答案折算成 R1 建议记录（纯函数）。"""
    choice = parsed["choice"]
    conflict = S.is_conflicted(parsed["evidence_conflict"])
    prof = profiles.get(_group_key(row)) or {}
    hard = S.hard_route_conflict(choice, row.get("score"), threshold, low,
                                 prof.get("has_prior"))
    suggestion, priority, reasons = choice, "routine", []
    if choice == "cannot_determine":
        suggestion, priority = "review", "priority_manual"
        reasons.append("cannot_determine")
    if conflict:
        suggestion, priority = "review", "priority_manual"
        reasons.append("evidence_conflict")
    if hard:
        suggestion, priority = "review", "priority_manual"
        reasons.append("hard_rule:" + hard)
    if (choice not in ("review", "cannot_determine")
            and (S.is_dispersed(parsed["probabilities"])
                 or parsed["confidence"] < S.ASSIST_CONF_MIN)):
        suggestion, priority = "review", "priority_manual"
        reasons.append("low_confidence")
    return {"status": "ok", "route": choice, "suggestion": suggestion,
            "priority": priority, "confidence": parsed["confidence"],
            "probabilities": parsed["probabilities"], "conflict": conflict,
            "conflict_noul": parsed["evidence_conflict"],
            "cluster_split_needed": parsed["cluster_split_needed"],
            "content_role": parsed["content_role"],
            "evidence_quality": S.quality_level(parsed["evidence_quality_raw"]),
            "gate": ";".join(reasons), "model": parsed["model"],
            "request_id": parsed["request_id"]}


def apply_assist(decisions, details, client, *, threshold, low,
                 max_items=None, batch_size=None, progress=None,
                 group_scores=None, enable=False,
                 max_failed_batches=S.ASSIST_MAX_FAILED_BATCHES):
    """R1 辅助路由骨架（**默认关闭**：enable=False 时零行为）。

    只处理最终仍为 review 且本地闸门未分流的 cue。输出**白名单三件事**
    （仍不回写 verdict、不增删产物）：

      1. 待复核排序建议 —— ``summary["priority_nums"]`` 把 priority_manual
         （cannot_determine / 声学冲突 / 硬规则冲突 / 低置信或概率分散）置前；
      2. 报告建议列 —— ``details[i]["assist"]["suggestion"]`` 与
         ``summary["items"]``（suggestion 只会是 keep/drop/review 三值；
         cannot_determine 一律折算为 review）；
      3. conflict 标注 —— ``details[i]["assist"]["conflict"]`` 与
         ``summary["conflicts"]``。

    路由约束（A.3）：低置信/概率分散 → 待复核不丢弃；硬规则冲突 → 硬规则
    优先（建议折回 review）；声学证据冲突 → 不得仅凭文本改；请求失败本批
    退回原规则（suggestion=原路由），连续 ``max_failed_batches`` 批失败则
    跳过剩余（不扩大自动化）。
    """
    summary = _summary(client, stage="assist")
    summary.update({"gated": 0, "gate_reasons": {}, "failed_batches": 0,
                    "skipped": 0, "priority_manual": 0, "conflicts": 0,
                    "items": [], "priority_nums": []})
    candidates = [i for i, row in enumerate(details)
                  if row.get("state") == "review"]
    summary["review_total"] = len(candidates)
    if not enable:
        summary["reason"] = "assist_disabled"
        return summary
    if not candidates or client is None or not getattr(client, "active", False):
        return summary
    limit, batch_size = _batch_limits(client, max_items, batch_size)
    selected = candidates[:limit]
    summary["selected"] = len(selected)
    summary["truncated"] = max(0, len(candidates) - len(selected))
    profiles = _group_profiles(details, threshold)
    policy = _assist_policy(threshold, low)

    entries = {}
    pending = []
    for index in selected:
        gate, why = _local_gate(details[index])
        if gate:
            summary["gated"] += 1
            summary["evaluated"] += 1
            summary["gate_reasons"][why] = summary["gate_reasons"].get(why, 0) + 1
            entries[index] = {"status": "gated", "suggestion": gate,
                              "priority": "routine", "gate": why,
                              "reason": "本地证据闸门；未调用 Jev"}
        else:
            pending.append(index)

    failed_streak = 0
    for offset in range(0, len(pending), batch_size):
        indexes = pending[offset:offset + batch_size]
        if failed_streak >= max_failed_batches:
            summary["skipped"] += len(indexes)   # 连续失败：跳过剩余
            continue
        state, questions, items = _build_request(
            decisions, details, indexes, profiles, group_scores, policy)
        try:
            response = client.decide(state, questions)
            failed_streak = 0
            summary["requests"] += 1
            for index, item in zip(indexes, items):
                parsed = _parse_answers(item, response)
                rec = _assist_record(details[index], parsed, threshold, low,
                                     profiles)
                entries[index] = rec
                summary["evaluated"] += 1
                summary["routes"][rec["suggestion"]] = \
                    summary["routes"].get(rec["suggestion"], 0) + 1
                if rec["priority"] == "priority_manual":
                    summary["priority_manual"] += 1
                if rec["conflict"]:
                    summary["conflicts"] += 1
        except Exception as exc:  # noqa: BLE001 — 辅助失败退回原规则
            failed_streak += 1
            summary["failed_batches"] += 1
            message = "%s: %s" % (type(exc).__name__, str(exc)[:240])
            summary["errors"].append({"first_num": items[0].get("num") if items else None,
                                      "count": len(items), "error": message})
            for index in indexes:                # 本批退回原规则（原路由照旧）
                entries[index] = {"status": "degraded",
                                  "suggestion": str(details[index].get("state") or "review"),
                                  "priority": "routine", "reason": message}
        _say(progress, "Jev 辅助路由：%d/%d 条存疑 cue" %
             (min(offset + len(indexes), len(pending)), len(pending)))

    for index, rec in entries.items():
        details[index]["assist"] = rec
        summary["items"].append({"num": details[index].get("num"),
                                 "suggestion": rec.get("suggestion"),
                                 "priority": rec.get("priority"),
                                 "conflict": bool(rec.get("conflict")),
                                 "status": rec.get("status")})
    manual = [i for i in selected
              if (entries.get(i) or {}).get("priority") == "priority_manual"]
    rest = [i for i in selected if i not in set(manual)]
    summary["priority_nums"] = [details[i].get("num") for i in manual + rest]
    return summary


# ---------------------------------------------------------------- R2 有限自动


def apply_auto(decisions, details, client, *, threshold, low,
               group_scores=None, enable=False, scene_whitelist=(),
               confidence_t1=None, prob_p1=None, max_items=None,
               batch_size=None, progress=None):
    """R2 有限自动路由骨架（**默认关闭**，且场景白名单为空时永不生效）。

    仅当 enable=True 且白名单非空时运行；一条 review cue 要把路由三值改掉
    必须同时通过全部门禁（附录 A.3 + 用户裁决「高置信 ≥98%」）：

      * route 是 keep/drop/review（cannot_determine 永不自动）；
      * confidence ≥ T1（默认 :data:`AUTO_CONF_T1` = 0.98）；
      * P(route) ≥ P1（默认 :data:`AUTO_PROB_P1` = 0.90）；
      * evidence_quality 展示级 ≥ 4（原始 score ≥ 2）；
      * evidence_conflict 未达冲突线（声学不冲突）；
      * content_role 落在场景白名单内；
      * 与硬规则一致（``hard_route_conflict`` 为空）。

    返回 ``(new_verdict, summary)``：new_verdict 与输入 decisions 等长同序、
    复用同一批 cue 对象与分数，**只改路由三值**——文本/时间轴/结构永不触碰；
    未过门禁的一律保持原路由（review），即「低置信 100% 待复核」。
    任何一批请求失败 → 本批退回原规则并**停止扩大自动化**（剩余跳过）。
    输入 `decisions` 本身不被修改。
    """
    summary = _summary(client, stage="auto")
    summary.update({"gates": {}, "auto_changed": 0, "kept_review": 0,
                    "skipped": 0, "items": [],
                    "scene_whitelist": sorted(str(s) for s in (scene_whitelist or ())),
                    "conf_t1": None, "prob_p1": None})
    new_verdict = list(decisions)
    candidates = [i for i, row in enumerate(details)
                  if row.get("state") == "review"]
    summary["review_total"] = len(candidates)
    if not enable:
        summary["reason"] = "auto_disabled"
        return new_verdict, summary
    if not candidates or client is None or not getattr(client, "active", False):
        return new_verdict, summary
    whitelist = {str(s) for s in (scene_whitelist or ())}
    if not whitelist:
        summary["reason"] = "scene_whitelist_empty"
        return new_verdict, summary
    conf_t1 = _float_setting(confidence_t1 if confidence_t1 is not None
                             else S.AUTO_CONF_T1, S.AUTO_CONF_T1, 0.5, 1.0)
    prob_p1 = _float_setting(prob_p1 if prob_p1 is not None
                             else S.AUTO_PROB_P1, S.AUTO_PROB_P1, 0.5, 1.0)
    summary["conf_t1"], summary["prob_p1"] = conf_t1, prob_p1
    limit, batch_size = _batch_limits(client, max_items, batch_size)
    selected = candidates[:limit]
    summary["selected"] = len(selected)
    summary["truncated"] = max(0, len(candidates) - len(selected))
    profiles = _group_profiles(details, threshold)
    policy = _auto_policy(threshold, low, whitelist, conf_t1, prob_p1)

    def _fail(index, reason):
        summary["gates"][reason] = summary["gates"].get(reason, 0) + 1
        summary["kept_review"] += 1

    stopped = False
    for offset in range(0, len(selected), batch_size):
        indexes = selected[offset:offset + batch_size]
        if stopped:
            summary["skipped"] += len(indexes)
            continue
        state, questions, items = _build_request(
            decisions, details, indexes, profiles, group_scores, policy)
        try:
            response = client.decide(state, questions)
            summary["requests"] += 1
            for index, item in zip(indexes, items):
                cue, state0, score0 = decisions[index]
                parsed = _parse_answers(item, response)
                choice = parsed["choice"]
                if choice not in ("keep", "drop", "review"):
                    _fail(index, "cannot_determine_or_unknown")
                    continue
                if parsed["confidence"] < conf_t1:
                    _fail(index, "low_confidence")
                    continue
                if parsed["probabilities"].get(choice, 0.0) < prob_p1:
                    _fail(index, "low_route_prob")
                    continue
                if (S.quality_level(parsed["evidence_quality_raw"]) or 0) \
                        < S.QUALITY_AUTO_MIN_LEVEL:
                    _fail(index, "low_evidence_quality")
                    continue
                if S.is_conflicted(parsed["evidence_conflict"]):
                    _fail(index, "evidence_conflict")
                    continue
                if parsed["content_role"] not in whitelist:
                    _fail(index, "scene_not_whitelisted")
                    continue
                prof = profiles.get(_group_key(details[index])) or {}
                hard = S.hard_route_conflict(choice, score0, threshold, low,
                                             prof.get("has_prior"))
                if hard:
                    _fail(index, "hard_rule:" + hard)
                    continue
                if choice != str(state0):
                    new_verdict[index] = (cue, choice, score0)
                    summary["auto_changed"] += 1
                else:
                    summary["kept_review"] += 1
                summary["routes"][choice] = summary["routes"].get(choice, 0) + 1
                summary["items"].append({"num": details[index].get("num"),
                                         "route": choice,
                                         "confidence": parsed["confidence"],
                                         "changed": choice != str(state0)})
        except Exception as exc:  # noqa: BLE001 — 自动模式失败即停止扩大
            stopped = True
            message = "%s: %s" % (type(exc).__name__, str(exc)[:240])
            summary["errors"].append({"first_num": items[0].get("num") if items else None,
                                      "count": len(items), "error": message})
        _say(progress, "Jev 自动路由：%d/%d 条存疑 cue" %
             (min(offset + len(indexes), len(selected)), len(selected)))
    return new_verdict, summary


__all__ = ["apply_shadow", "apply_assist", "apply_auto", "SCHEMA_VERSION",
           "SHADOW_SCHEMA_V1", "ROUTES", "SEPARATION_BACKEND",
           "STATE_FIELD_GLOSSARY"]
