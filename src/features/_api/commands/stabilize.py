# -*- coding: utf-8 -*-
# @version 3.1.5
"""stabilize 命令编排（透传 calib_core stabilize 子命令，行为不变）。"""
from __future__ import annotations

from features._api.commands.calibrate import passthrough_run
from features._api.errors import fail


def run(params: dict, log) -> dict:
    input_list = params.get("input") or []
    if not input_list:
        return fail("缺少输入字幕（用法：stabilize <input.srt> [--out F] …）")
    return passthrough_run("stabilize", input_list, params.get("extra") or [], log)