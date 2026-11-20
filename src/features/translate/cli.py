# -*- coding: utf-8 -*-
# @version 3.1.4
"""translate 子命令参数壳（L2 CLI）。编排在 features/_api/commands/translate.py。"""
from __future__ import annotations

from features._api import dispatch
from features._cli import _emit, _say, common


def cmd_translate(args) -> int:
    params = {"file": args.file, "to": args.to, "engine": args.engine,
              "threads": args.threads, "batch": args.batch, "out": args.out}
    return _emit(args, dispatch("translate", params, log=lambda m: _say(args, m)))


def setup_translate(sub) -> None:
    s = sub.add_parser("translate", parents=[common],
                       help="翻译字幕（bing/google/deeplx 免认证端点）")
    s.add_argument("file", help="输入字幕（.srt/.ass/.vtt）")
    s.add_argument("--to", default="zh-Hans", help="目标语言（zh-Hans/简体中文/en…）")
    s.add_argument("--engine", default="bing",
                   choices=["bing", "google", "deeplx", "微软翻译", "谷歌翻译", "DeepLx 翻译"],
                   help="翻译服务（默认 bing）")
    s.add_argument("--threads", type=int, default=4, help="并发线程数（默认 4）")
    s.add_argument("--batch", type=int, default=20, help="每块 cue 数（默认 20）")
    s.add_argument("--out", default="", help="输出字幕或目录（默认 data\\agent_out\\<时间戳>\\<名>.zh.srt）")
    s.set_defaults(fn=cmd_translate)