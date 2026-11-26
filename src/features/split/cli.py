# -*- coding: utf-8 -*-
# @version 3.3.1
"""split 子命令参数壳（L2 CLI）。编排在 features/_api/commands/split.py。"""
from __future__ import annotations

from features._api import dispatch
from features._cli import _emit, _say, common


def cmd_split(args) -> int:
    params = {"file": args.file, "points": args.points, "durations": args.durations,
              "mode": args.mode, "out": args.out, "verify": args.verify}
    return _emit(args, dispatch("split", params, log=lambda m: _say(args, m)))


def setup_split(sub) -> None:
    s = sub.add_parser("split", parents=[common],
                       help="视频切片：按时间点（HH:MM:SS）或时长（xHyMzS）拆成多段，逐段校验可播放")
    s.add_argument("file", help="源视频")
    s.add_argument("--points", default="",
                   help="时间点列表（HH:MM:SS），如 \"00:00:00,01:00:00,02:00:00\"")
    s.add_argument("--durations", default="",
                   help="时长列表（xHyMzS），如 \"1h,1h\" / \"1h30m,30m,45s\"")
    s.add_argument("--mode", default="auto", choices=["copy", "auto", "encode"],
                   help="copy=无损快切；auto=快切校验不过就重编码（默认）；encode=精确重编码")
    s.add_argument("--out", default="",
                   help="输出目录（默认 data\\agent_out\\<时间戳>\\<名>_split）")
    s.add_argument("--verify", default="quick", choices=["quick", "full"],
                   help="逐段校验强度：quick=片头片尾抽检（默认）；full=整段全解码")
    s.set_defaults(fn=cmd_split)