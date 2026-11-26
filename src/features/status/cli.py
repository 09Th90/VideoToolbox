# -*- coding: utf-8 -*-
# @version 3.3.1
"""status 子命令参数壳（L2 CLI）。业务编排在 features/_api/commands/status.py。

2026-11-20 三层独立：CLI 只做参数解析与输出，经 _api 取能力（不复制业务）。
"""
from __future__ import annotations

from features._api import dispatch
from features._cli import _emit, _say, common


def cmd_status(args) -> int:
    return _emit(args, dispatch("status", {"ping": getattr(args, "ping", False)},
                                log=lambda m: _say(args, m)))


def setup_status(sub) -> None:
    s = sub.add_parser("status", parents=[common],
                       help="环境/AI 配置自检（工具在位性、AI/ASR 槽是否已配）")
    s.add_argument("--ping", action="store_true",
                   help="实测全局 AI 连通性（发一次真实请求）")
    s.set_defaults(fn=cmd_status)