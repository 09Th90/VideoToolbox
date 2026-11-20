# -*- coding: utf-8 -*-
# @version 3.1.3
"""compose 子命令参数壳（L2 CLI）。编排在 features/_api/commands/compose.py。"""
from __future__ import annotations

from features._api import dispatch
from features._cli import _emit, _say, common


def cmd_compose(args) -> int:
    params = {"video": args.video, "sub": args.sub, "audio": args.audio,
              "mode": args.mode, "out": args.out}
    return _emit(args, dispatch("compose", params, log=lambda m: _say(args, m)))


def setup_compose(sub) -> None:
    s = sub.add_parser("compose", parents=[common],
                       help="字幕合成：软封装（copy）/ 硬烧录 / 带独立音轨合并")
    s.add_argument("video", help="视频文件")
    s.add_argument("sub", help="字幕文件（.srt/.ass）")
    s.add_argument("--audio", default="", help="独立音轨（.m4a/.weba，如下载产物分离音轨；可选）")
    s.add_argument("--mode", default="soft", choices=["soft", "burn", "mkv"],
                   help="soft=软封装不重编码（默认）；burn=硬烧录（ASS，重编码）；mkv=封装进 MKV")
    s.add_argument("--out", default="", help="输出文件（默认 data\\agent_out\\<时间戳>\\<名>.composed.mp4）")
    s.set_defaults(fn=cmd_compose)