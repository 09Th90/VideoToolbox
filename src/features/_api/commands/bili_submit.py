# -*- coding: utf-8 -*-
# @version 3.1.4
"""bili-submit 命令编排（原 features/automation/cli.py argv 映射，行为不变）。

内层 bili_auto_submit.main 自建 argparse 并直接 print（非统一信封）：
本层捕获其 stdout 随信封返回（stdout 键），退出码原样保留（exit_code）。
params["stream"]=True 时 Tee 直写调用方 stdout（CLI 保真：内容与流式时序不变）。
"""
from __future__ import annotations

import contextlib
import io
import sys


def run(params: dict, log) -> dict:
    import features.automation.bili_auto_submit as bas  # noqa: PLC0415
    argv = []
    material = params.get("material", "")
    if material:
        argv.append(material)
    for flag in ("probe", "dry_run", "edit"):
        if params.get(flag, False):
            argv.append("--" + flag.replace("_", "-"))
    for name in ("only", "visibility", "topic", "cover", "subtitle"):
        val = params.get(name, "")
        if val:
            argv += ["--" + name, str(val)]
    if params.get("as_json", False):
        argv.append("--json")

    buf = io.StringIO()
    if params.get("stream"):
        outer = sys.stdout

        class _Tee:
            def write(self, s):
                buf.write(s)
                outer.write(s)

            def flush(self):
                outer.flush()

        target = _Tee()
    else:
        target = buf
    try:
        with contextlib.redirect_stdout(target):
            rc = bas.main(argv)
    except SystemExit as ex:      # 内层 argparse error 会 sys.exit(2)——归一为信封
        rc = ex.code if isinstance(ex.code, int) else (0 if ex.code is None else 1)
    return {"ok": rc == 0, "exit_code": rc, "stdout": buf.getvalue()}