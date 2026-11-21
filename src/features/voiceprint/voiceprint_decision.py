# -*- coding: utf-8 -*-
# @version 3.1.6
"""声纹存疑 cue 的 Jev 影子路由。

Jev 看不到音频，不能也不应凭台词猜说话人身份。这里只让它根据本地声纹分数、
证据来源和相邻 cue 状态，给出人工复核优先级；绝不修改本地 verdict 或字幕。
"""
from __future__ import annotations

SCHEMA_VERSION = "vt.voiceprint.shadow.v1"
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


def _neighbor(details, index):
    if index < 0 or index >= len(details):
        return None
    row = details[index]
    return {"num": row.get("num"), "local_state": row.get("state"),
            "local_score": row.get("score"), "source": row.get("source"),
            "asr_speaker": row.get("speaker") or ""}


def _summary(client):
    status = dict(getattr(client, "status", {}) or {})
    return {"schema_version": SCHEMA_VERSION,
            "active": bool(status.get("active")),
            "mode": str(status.get("mode") or "off"),
            "model": status.get("model") or "decision-model-preview",
            "endpoint": status.get("endpoint") or "",
            "reason": status.get("reason") or "not_configured",
            "review_total": 0, "selected": 0, "evaluated": 0,
            "requests": 0, "truncated": 0, "routes": {}, "errors": []}


def apply_shadow(decisions, details, client, *, threshold, low,
                 max_items=None, batch_size=None, progress=None):
    """对最终仍为 review 的 cue 批量路由，返回摘要并就地追加 details[i].jev。

    `decisions` 的三元组从不回写。任何网络/协议异常只给本批追加 degraded 证据，
    主流程继续按本地 CAM++ 结果写正式 SRT 与待复核 SRT。
    """
    summary = _summary(client)
    candidates = [i for i, row in enumerate(details)
                  if row.get("state") == "review"]
    summary["review_total"] = len(candidates)
    if not candidates or client is None or not getattr(client, "active", False):
        return summary
    cfg = dict(getattr(client, "config", {}) or {})
    limit = _int_setting(max_items if max_items is not None
                         else cfg.get("decision_max_items"), 32, 0, 512)
    batch_size = _int_setting(batch_size if batch_size is not None
                              else cfg.get("decision_batch_size"), 8, 1, 8)
    selected = candidates[:limit]
    summary["selected"] = len(selected)
    summary["truncated"] = max(0, len(candidates) - len(selected))

    def _say(text):
        if progress:
            try:
                progress(text)
            except Exception:  # noqa: BLE001
                pass

    for offset in range(0, len(selected), batch_size):
        indexes = selected[offset:offset + batch_size]
        items, questions = [], {}
        for pos, index in enumerate(indexes):
            row = details[index]
            cue = decisions[index][0]
            qname = "route_%d" % pos
            items.append({
                "question": qname, "num": row.get("num"),
                "start_ms": row.get("start"), "end_ms": row.get("end"),
                "duration_ms": row.get("duration_ms"),
                "local_state": "review", "local_score": row.get("score"),
                "source": row.get("source"), "reason": row.get("reason"),
                "asr_speaker": row.get("speaker") or "",
                "local_cluster": row.get("cluster"),
                "text": str(getattr(cue, "text", "") or "")[:600],
                "previous": _neighbor(details, index - 1),
                "next": _neighbor(details, index + 1),
            })
            questions[qname] = {
                "type": "choice",
                "instructions": (
                    "只评估 state.items 中 question=%s 的存疑字幕。你不能听到音频，"
                    "不得凭台词猜测说话人身份；本地声纹分数是主要证据。只判断人工"
                    "复核优先级，输出 routine_review、priority_manual 或 "
                    "insufficient_evidence。" % qname),
                "criteria": ROUTES,
            }
        state = {
            "schema_version": SCHEMA_VERSION,
            "business": "voiceprint_review_routing",
            "policy": {"shadow_only": True, "allow_verdict_change": False,
                       "keep_threshold": float(threshold), "low_threshold": float(low)},
            "items": items,
        }
        try:
            response = client.decide(state, questions)
            summary["requests"] += 1
            for index, item in zip(indexes, items):
                answer = response["answers"][item["question"]]
                choice = str(answer["choice"])
                details[index]["jev"] = {
                    "mode": "shadow", "status": "ok", "choice": choice,
                    "confidence": float(answer["confidence"]),
                    "probabilities": dict(answer.get("probabilities") or {}),
                    "model": response.get("model"), "request_id": response.get("request_id"),
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
        _say("Jev 影子路由：%d/%d 条存疑 cue" %
             (min(offset + len(indexes), len(selected)), len(selected)))
    return summary


__all__ = ["apply_shadow", "SCHEMA_VERSION", "ROUTES"]
