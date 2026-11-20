# -*- coding: utf-8 -*-
# @version 3.1.3
"""download 子命令参数壳（L2 CLI）。job/legacy 双路径编排在 features/_api/commands/download.py。"""
from __future__ import annotations

from features._api import dispatch
from features._cli import _emit, _say, common


def cmd_download(args) -> int:
    params = {"url": args.url, "dir": args.dir,
              "height": getattr(args, "height", 0),
              "subs": getattr(args, "subs", False)}
    return _emit(args, dispatch("download", params, log=lambda m: _say(args, m)))


def setup_download(sub) -> None:
    s = sub.add_parser("download", parents=[common],
                       help="下载视频（yt-dlp，自动代理+游客 cookie，合并 mp4）")
    s.add_argument("url", help="视频链接（YouTube/B站等 yt-dlp 支持的站点）")
    s.add_argument("--dir", default="", help="输出目录（默认 data\\downloads\\agent\\<标题>\\）")
    s.add_argument("--height", type=int, default=0,
                   help="限制最大分辨率高度（如 1080；0=不限制）")
    s.add_argument("--subs", action="store_true",
                   help="同时下载字幕（job 编排模式下生效）")
    s.set_defaults(fn=cmd_download)