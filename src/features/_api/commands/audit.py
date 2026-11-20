# -*- coding: utf-8 -*-
# @version 3.1.2
"""audit 命令编排（透传 calib_core audit 子命令，行为不变）。

名词漏校三扫：拉丁残留 / 知识库错形残留 / 同词族一致性。
退出码 1＝有候选（检查结果，非故障；MCP 侧不置 isError）。
"""
from __future__ import annotations

from features._api.commands.calibrate import passthrough_run
from features._api.errors import fail


def run(params: dict, log) -> dict:
    input_list = params.get("input") or []
    if not input_list:
        return fail("缺少输入字幕（用法：audit <校准后.srt> [--mode bi] "
                    "[--out 报告.md] [--json] [--loose]）")
    return passthrough_run("audit", input_list, params.get("extra") or [], log)