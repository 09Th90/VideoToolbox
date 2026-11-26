# -*- coding: utf-8 -*-
# @version 3.3.1
"""trace 命令编排：开发版校准观测事件只读查询。

数据源 = features.calibrate.telemetry 的 JSONL 事件文件（logs/trace/<session>/）。
本命令不写任何事件、不碰校准产物；观测未启用时 list 返回空清单。
``after`` 游标是 CLI --follow 增量轮询的内部参数（不经 spec/argparse 登记）。
"""
from __future__ import annotations

from features._api.errors import fail


def run(params: dict, log) -> dict:
    from features.calibrate import telemetry as _tel  # noqa: PLC0415
    action = params.get("action") or "list"
    session = params.get("session") or None
    if action == "list":
        try:
            limit = int(params.get("limit") or 30)
        except (TypeError, ValueError):
            limit = 30
        return {"ok": True, "root": _tel.trace_root(),
                "sessions": _tel.list_sessions(limit=limit)}
    if action == "show":
        summary = _tel.session_summary(session)
        if "error" in summary:
            return fail(summary["error"])
        return {"ok": True, **summary}
    if action == "tail":
        kind = params.get("kind") or None
        try:
            limit = int(params.get("limit") if params.get("limit") is not None else 50)
        except (TypeError, ValueError):
            limit = 50
        events = _tel.read_events(session=session, kind=kind,
                                  limit=None if limit <= 0 else limit,
                                  after=params.get("after") or None)
        sid = session or _tel.latest_session()
        cursor = None
        if events:
            last = events[-1]
            cursor = {"ts": last.get("ts", ""), "pid": last.get("pid", 0),
                      "seq": last.get("seq", 0)}
        return {"ok": True, "session": sid, "count": len(events),
                "events": events, "cursor": cursor}
    return fail("未知 action：%s（可用 list/tail/show）" % action)