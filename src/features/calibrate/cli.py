# -*- coding: utf-8 -*-
# @version 3.3.1
"""calibrate / stabilize / audit 子命令参数壳（L2 CLI，透传段）。

编排在 features/_api/commands/{calibrate,stabilize,audit}.py。
入口边界职责：--json 时 redirect_stdout 隔离 calib_core 过程输出、打印信封、
**退出码原样保留**（audit 1＝有候选，属检查结果）。
"""
from __future__ import annotations

import contextlib
import json
import sys

from features._api import dispatch
from features._api.commands.calibrate import CALIB_MODE_FLAGS, CALIB_SCRIPT
from features._cli import _emit, _say, common

__all__ = ["CALIB_SCRIPT", "CALIB_MODE_FLAGS", "cmd_calibrate", "cmd_stabilize",
           "cmd_audit", "setup_calibrate", "setup_stabilize", "setup_audit",
           "cmd_trace", "setup_trace"]


def _calib_handler(args, cmd: str) -> int:
    params = {"input": args.input, "extra": args.extra}
    log = lambda m: _say(args, m)  # noqa: E731
    if getattr(args, "as_json", False):
        # stdout 只留最终信封；calib_core 过程输出转 stderr（OS 级 fd 不动，
        # 回退 subprocess 的子进程输出仍继承原 stdout——与改造前一致）。
        with contextlib.redirect_stdout(sys.stderr):
            payload = dispatch(cmd, params, log)
    else:
        payload = dispatch(cmd, params, log)
    if "exit_code" not in payload:        # 前置失败（缺输入等）→ 标准信封
        return _emit(args, payload)
    rc = payload["exit_code"]
    if getattr(args, "as_json", False):
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return rc


def cmd_calibrate(args) -> int:
    """术语/规则校准：`calibrate <input.srt> [--out F] [--report F] [--ja|--ko|…]`。"""
    return _calib_handler(args, "calibrate")


def cmd_stabilize(args) -> int:
    """cue 稳定化：`stabilize <input.srt> [--out F] [--drop|--no-drop|…]`。"""
    return _calib_handler(args, "stabilize")


def cmd_audit(args) -> int:
    """名词漏校三扫：`audit <校准后.srt> [--mode bi] [--out 报告.md] [--loose]`。"""
    return _calib_handler(args, "audit")


def setup_calibrate(sub) -> None:
    s = sub.add_parser("calibrate", parents=[common],
                       help="字幕术语校准（透传 subtitle_calib_merged.py，只改文字不动时间轴）")
    s.set_defaults(fn=cmd_calibrate, input=[], extra=[])


def setup_stabilize(sub) -> None:
    s = sub.add_parser("stabilize", parents=[common],
                       help="cue 稳定化（透传 subtitle_calib_merged.py 的 stabilize 子命令）")
    s.set_defaults(fn=cmd_stabilize, input=[], extra=[])


def setup_audit(sub) -> None:
    s = sub.add_parser("audit", parents=[common],
                       help="名词漏校三扫（透传 subtitle_calib_merged.py 的 audit 子命令；"
                            "拉丁残留 / 错形残留 / 同词族一致性，退出码 1＝有候选）")
    s.set_defaults(fn=cmd_audit, input=[], extra=[])


def cmd_trace(args) -> int:
    """开发版校准观测：`trace list|tail|show [--session ID] [--kind …] [--follow]`。"""
    params = {"action": args.action, "session": args.session,
              "kind": args.kind, "limit": args.limit}
    log = lambda m: _say(args, m)  # noqa: E731
    if getattr(args, "follow", False):
        return _trace_follow(args, params, log)
    payload = dispatch("trace", params, log)
    return _emit(args, payload)


def _trace_follow(args, params, log) -> int:
    """--follow：0.5s 轮询增量事件。人读模式打紧凑行；--json 模式 NDJSON 流
    （每行一个事件对象，流式例外已在 SKILL.md 注明）。Ctrl-C 退出 rc=0。"""
    import time as _time
    after = None
    as_json = getattr(args, "as_json", False)
    try:
        while True:
            p = dict(params, action="tail", after=after, limit=0)
            payload = dispatch("trace", p, log)
            if not payload.get("ok"):
                return _emit(args, payload)
            for e in payload.get("events") or []:
                if as_json:
                    print(json.dumps(e, ensure_ascii=False), flush=True)
                else:
                    brief = json.dumps(e.get("payload") or {}, ensure_ascii=False)
                    if len(brief) > 200:
                        brief = brief[:200] + "…"
                    print("%s [%s/%s] %s" % (e.get("ts", ""), e.get("kind", ""),
                                             e.get("event", ""), brief), flush=True)
            if payload.get("cursor"):
                after = payload["cursor"]
            _time.sleep(0.5)
    except KeyboardInterrupt:
        return 0


def setup_trace(sub) -> None:
    s = sub.add_parser("trace", parents=[common],
                       help="开发版校准观测事件查询（工作流/AI 思考链/校准方向/数据访问）")
    s.add_argument("action", nargs="?", default="list",
                   choices=["list", "tail", "show"],
                   help="list=会话清单 / tail=事件流 / show=单会话摘要")
    s.add_argument("--session", default=None, help="会话 ID（默认最新）")
    s.add_argument("--kind", default=None,
                   choices=["workflow", "ai", "direction", "data"],
                   help="事件类别过滤：workflow/ai/direction/data")
    s.add_argument("--limit", type=int, default=50,
                   help="tail 取末尾 N 条事件（0=全部；list 时为会话数上限）")
    s.add_argument("--follow", action="store_true",
                   help="实时跟踪（0.5s 轮询；--json 模式输出 NDJSON 事件流）")
    s.set_defaults(fn=cmd_trace)