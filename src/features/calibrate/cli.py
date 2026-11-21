# -*- coding: utf-8 -*-
# @version 3.1.6
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
           "cmd_audit", "setup_calibrate", "setup_stabilize", "setup_audit"]


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