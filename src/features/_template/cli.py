# -*- coding: utf-8 -*-
# @version 3.1.4
"""CLI 子命令模板。模块级只许标准库 + features._cli；后端在 handler 内惰性 import。"""
from __future__ import annotations

from features._cli import _emit, _fail, common


def cmd_template(args) -> int:
    # import my_backend  # noqa: PLC0415 —— 惰性：缺依赖时由入口转成 JSON 错误信封
    return _emit(args, {"ok": True, "hello": "template"})


def setup_template(sub) -> None:
    s = sub.add_parser("_template", parents=[common], help="模板子命令")
    s.add_argument("file", nargs="?", default="", help="输入文件（可选）")
    s.set_defaults(fn=cmd_template)