# -*- coding: utf-8 -*-
# @version 3.1.4
"""transcribe 子命令参数壳（L2 CLI）。编排在 features/_api/commands/transcribe.py。"""
from __future__ import annotations

from features._api import dispatch
from features._cli import _emit, _say, common


def cmd_transcribe(args) -> int:
    params = {"file": args.file, "lang": args.lang, "out": args.out}
    return _emit(args, dispatch("transcribe", params, log=lambda m: _say(args, m)))


def setup_transcribe(sub) -> None:
    s = sub.add_parser("transcribe", parents=[common],
                       help="ASR 转录出 SRT（模型/密钥读设置页 ASR 槽）")
    s.add_argument("file", help="视频或音频文件")
    s.add_argument("--lang", default="", help="识别语言：ISO 码或引擎标签（ja/en/zh/日本語…；空=自动检测）")
    s.add_argument("--out", default="", help="输出 .srt 或目录（默认 data\\agent_out\\<时间戳>\\）")
    s.set_defaults(fn=cmd_transcribe)