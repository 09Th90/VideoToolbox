# -*- coding: utf-8 -*-
# @version 3.2.0
"""calibrate 命令编排（原 features/calibrate/cli.py 透传核心，行为不变）。

优先同进程直连 calib_core.cli.main_argv；VT_CALIB_SUBPROCESS=1 或导入失败
回退根脚本 subprocess。**stdout 隔离（redirect_stdout）属入口边界**，由
CLI handler / api_worker 负责，本层不重定向（人读模式下 calib_core 的 print
就是最终用户输出）。退出码原样保留于信封 exit_code。
"""
from __future__ import annotations

import os
import subprocess
import sys

from features._api.errors import fail
from features._api.runtime import APP_ROOT

#: 根目录校准统一脚本（透传回退目标；路径锚定文件，不可移动）
CALIB_SCRIPT = os.path.join(APP_ROOT, "subtitle_calib_merged.py")

#: 历史兼容再导出（agent_cli.__all__ 冻结）；**参数唯一真源是 _api/spec.py**
#: （本 tuple 仅 18 项且含非模式旗标，已过期，不作 schema 依据）
CALIB_MODE_FLAGS = ("--ja", "--jpe", "--pgrja", "--ko", "--wwoc", "--ak", "--akko",
                    "--akja",                                   # 2026-11-03 新增：日语原声·明日方舟
                    "--zho", "--endo", "--endobi", "--fix-en", "--limbus",
                    "--ffrs", "--pbz", "--ssv", "--arcak",
                    "--arcakamiya")                            # 2026-11-19 新增：歌词向全曲纯享侧车


def passthrough_run(sub: str | None, input_list: list, extra: list, log) -> dict:
    """透传执行核心：返回 {ok, script, exit_code}（或前置失败 {ok:False,error}）。"""
    argv = ([sub] if sub else []) + list(input_list) + list(extra)

    if os.environ.get("VT_CALIB_SUBPROCESS") != "1":
        # 入口位于 <根>/src，sys.path[0] 天然可见 calib_core；
        # 被 import 为 src.agent_cli 时补一次路径，仍失败则回退旧通路。
        src_dir = os.path.join(APP_ROOT, "src")
        if src_dir not in sys.path:
            sys.path.insert(0, src_dir)
        try:
            from calib_core.cli import main_argv as _calib_main  # noqa: PLC0415
        except ImportError as e:
            log("[信息] calib_core 不可用（%s），回退单文件 subprocess" % e)
        else:
            log("[信息] " + " ".join(argv))

            def _invoke():
                try:
                    rc = _calib_main(argv)
                except SystemExit as ex:      # 子命令按惯例 sys.exit(rc)
                    rc = ex.code
                return 0 if rc is None else (rc if isinstance(rc, int) else 1)

            rc = _invoke()
            return {"ok": rc == 0,
                    "script": "calib_core.cli.main_argv",
                    "exit_code": rc}

    # —— 回退：原 subprocess 通路（单文件仍随包分发）——
    if not os.path.isfile(CALIB_SCRIPT):
        return fail("校准脚本不存在：%s" % CALIB_SCRIPT)
    cmd = [sys.executable, CALIB_SCRIPT]
    if sub:
        cmd.append(sub)
    cmd.extend(list(input_list) + list(extra))
    log("[信息] %s" % " ".join(os.path.relpath(a, APP_ROOT)
                              if os.path.isabs(a) and a.startswith(APP_ROOT)
                              else a for a in cmd[1:]))
    proc = subprocess.run(cmd, cwd=APP_ROOT)
    return {"ok": proc.returncode == 0,
            "script": os.path.relpath(CALIB_SCRIPT, APP_ROOT),
            "exit_code": proc.returncode}


def run(params: dict, log) -> dict:
    """术语/规则校准：input + 其余旗标原样透传（参数表与 calib_core 完全同源）。"""
    input_list = params.get("input") or []
    if not input_list:
        return fail("缺少输入字幕（用法：calibrate <input.srt> [--out F] "
                    "[--report F] [--ja|--ko|--endo|--ak|…]）")
    payload = passthrough_run(None, input_list, params.get("extra") or [], log)
    if "exit_code" in payload:
        _enrich(params.get("extra") or [], payload)
    return payload


def _enrich(extra: list, payload: dict) -> None:
    """只增字段（P1 信封增强，旧字段不动）：mode_name + changes（report TSV 数据行）。"""
    from features._api.spec import CALIBRATE_MODE_FLAGS  # noqa: PLC0415
    flag_mode = {m.flag: m.mode for m in CALIBRATE_MODE_FLAGS}
    mode = None
    it = iter(extra)
    for a in it:
        if a in flag_mode:
            mode = flag_mode[a]
        elif a == "--mode":
            mode = next(it, None)
    if mode:
        payload["mode_name"] = mode
    report = None
    it = iter(extra)
    for a in it:
        if a == "--report":
            report = next(it, None)
    if report and os.path.isfile(report):
        try:
            with open(report, encoding="utf-8") as f:
                n = len(f.read().splitlines())
            payload["changes"] = max(0, n - 1)      # 除表头
        except OSError:
            pass