# -*- coding: utf-8 -*-
# @version 3.1.4
"""_api.errors —— 命令信封构造（与 CLI _emit/_fail 的 dict 形态同源）。"""
from __future__ import annotations


def ok(**fields) -> dict:
    return {"ok": True, **fields}


def fail(error: str, **fields) -> dict:
    return {"ok": False, "error": error, **fields}