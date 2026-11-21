# -*- coding: utf-8 -*-
# @version 3.1.6
"""info 子命令参数壳（L2 CLI）。业务编排在 features/_api/commands/info.py。"""
from __future__ import annotations

from features._api import dispatch
from features._cli import _emit, _say, common


def cmd_info(args) -> int:
    return _emit(args, dispatch("info", {"file": args.file},
                                log=lambda m: _say(args, m)))


def setup_info(sub) -> None:
    s = sub.add_parser("info", parents=[common],
                       help="媒体/字幕元信息（ffprobe；字幕给 cue 数与时间跨度）")
    s.add_argument("file", help="视频 / 音频 / 字幕文件路径")
    s.set_defaults(fn=cmd_info)