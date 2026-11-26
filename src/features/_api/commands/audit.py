# -*- coding: utf-8 -*-
# @version 3.3.1
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
    payload = passthrough_run("audit", input_list, params.get("extra") or [], log)
    if "exit_code" in payload:
        _enrich(input_list, params.get("extra") or [], payload)
    return payload


def _enrich(input_list: list, extra: list, payload: dict) -> None:
    """只增字段（P1）：candidates——_cmd_audit(as_json=True) 只读复扫捕获 JSON，
    绕开入口 redirect_stdout 吞内层 JSON 的问题；主透传路径与退出码不变。"""
    try:
        import contextlib  # noqa: PLC0415
        import io  # noqa: PLC0415
        import json  # noqa: PLC0415
        from calib_core.kb import _cmd_audit  # noqa: PLC0415
        mode, loose, window = "bi", False, 0
        it = iter(extra)
        for a in it:
            if a == "--mode":
                mode = next(it, "bi")
            elif a == "--loose":
                loose = True
            elif a == "--window":
                window = int(next(it, "0"))
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _cmd_audit(input_list[0], mode=mode, as_json=True,
                       loose=loose, window=window)
        d = json.loads(buf.getvalue())
        payload["candidates"] = (len(d.get("latin_residue", []))
                                 + len(d.get("variant_residue_high", []))
                                 + len(d.get("family_gap", [])))
    except Exception:  # noqa: BLE001 —— 增强失败不影响主路径
        pass