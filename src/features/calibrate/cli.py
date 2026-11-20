# -*- coding: utf-8 -*-
# @version 3.1.2
"""calibrate / stabilize / audit 子命令（原 agent_cli 透传段，行为不变）。"""
from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys

from features._cli import APP_ROOT, _fail, _say, common

#: 根目录校准统一脚本（透传回退目标；路径锚定文件，不可移动）
CALIB_SCRIPT = os.path.join(APP_ROOT, "subtitle_calib_merged.py")

#: 校准脚本支持的语言旗标（与 subtitle_calib_merged.main_argv 同步，2026-10-15）
CALIB_MODE_FLAGS = ("--ja", "--jpe", "--pgrja", "--ko", "--wwoc", "--ak", "--akko",
                    "--akja",                                   # 2026-11-03 新增：日语原声·明日方舟
                    "--zho", "--endo", "--endobi", "--fix-en", "--limbus",
                    "--ffrs", "--pbz", "--ssv", "--arcak",
                    "--arcakamiya")                            # 2026-11-19 新增：歌词向全曲纯享侧车


def _run_calib_passthrough(args, sub: str | None, extra: list) -> int:
    """校准子命令：优先同进程直连 calib_core 包；VT_CALIB_SUBPROCESS=1 回退单文件。

    双轨（2026-11-08）：根目录 subtitle_calib_merged.py 是构建产物，仍供
    知识同步链、自检工具与外部 D:\\原片\\ 工作流读取；运行时不再依赖它。
    """
    argv = ([sub] if sub else []) + list(extra)

    if os.environ.get("VT_CALIB_SUBPROCESS") != "1":
        # agent_cli.py 位于 <根>/src，sys.path[0] 天然可见 calib_core；
        # 被 import 为 src.agent_cli 时补一次路径，仍失败则回退旧通路。
        src_dir = os.path.join(APP_ROOT, "src")
        if src_dir not in sys.path:
            sys.path.insert(0, src_dir)
        try:
            from calib_core.cli import main_argv as _calib_main  # noqa: PLC0415
        except ImportError as e:
            _say(args, "[信息] calib_core 不可用（%s），回退单文件 subprocess" % e)
        else:
            _say(args, "[信息] " + " ".join(argv))

            def _invoke():
                try:
                    rc = _calib_main(argv)
                except SystemExit as ex:      # 子命令按惯例 sys.exit(rc)
                    rc = ex.code
                return 0 if rc is None else (rc if isinstance(rc, int) else 1)

            # --json 时 stdout 只能有最终 JSON；校准过程输出转到 stderr。
            if getattr(args, "as_json", False):
                with contextlib.redirect_stdout(sys.stderr):
                    rc = _invoke()
            else:
                rc = _invoke()
            if getattr(args, "as_json", False):
                print(json.dumps({"ok": rc == 0,
                                  "script": "calib_core.cli.main_argv",
                                  "exit_code": rc}, ensure_ascii=False, indent=2))
            return rc

    # —— 回退：原 subprocess 通路（单文件仍随包分发）——
    if not os.path.isfile(CALIB_SCRIPT):
        return _fail(args, "校准脚本不存在：%s" % CALIB_SCRIPT)
    cmd = [sys.executable, CALIB_SCRIPT]
    if sub:
        cmd.append(sub)
    cmd.extend(extra)
    _say(args, "[信息] %s" % " ".join(os.path.relpath(a, APP_ROOT)
                                      if os.path.isabs(a) and a.startswith(APP_ROOT)
                                      else a for a in cmd[1:]))
    proc = subprocess.run(cmd, cwd=APP_ROOT)
    if getattr(args, "as_json", False):
        print(json.dumps({"ok": proc.returncode == 0,
                          "script": os.path.relpath(CALIB_SCRIPT, APP_ROOT),
                          "exit_code": proc.returncode},
                         ensure_ascii=False, indent=2))
        return proc.returncode
    return proc.returncode


def cmd_calibrate(args) -> int:
    """术语/规则校准：`calibrate <input.srt> [--out F] [--report F] [--ja|--ko|…]`。

    其余未识别参数原样透传给 subtitle_calib_merged.py（参数表完全同源）。
    """
    if not args.input:
        return _fail(args, "缺少输入字幕（用法：calibrate <input.srt> [--out F] "
                           "[--report F] [--ja|--ko|--endo|--ak|…]）")
    return _run_calib_passthrough(args, None, args.input + args.extra)


def cmd_stabilize(args) -> int:
    """cue 稳定化：`stabilize <input.srt> [该脚本 stabilize 子命令的其余参数]`。"""
    if not args.input:
        return _fail(args, "缺少输入字幕（用法：stabilize <input.srt> [--out F] …）")
    return _run_calib_passthrough(args, "stabilize", args.input + args.extra)


def cmd_audit(args) -> int:
    """名词漏校三扫：`audit <校准后.srt> [--mode bi] [--out 报告.md] [--json] [--loose]`。

    透传 subtitle_calib_merged.py 的 audit 子命令：拉丁残留 / 知识库错形残留 /
    同词族一致性。退出码 1＝有候选（可当门禁）。
    """
    if not args.input:
        return _fail(args, "缺少输入字幕（用法：audit <校准后.srt> [--mode bi] "
                           "[--out 报告.md] [--json] [--loose]）")
    return _run_calib_passthrough(args, "audit", args.input + args.extra)


def setup_calibrate(sub) -> None:
    s = sub.add_parser("calibrate", parents=[common],
                       help="字幕术语校准（透传 subtitle_calib_merged.py，只改文字不动时间轴）")
    s.set_defaults(fn=cmd_calibrate, input=[], extra=[])


def setup_stabilize(sub) -> None:
    s = sub.add_parser("stabilize", parents=[common],
                       help="cue 稳定化（透传 subtitle_calib_merged.py 的 stabilize 子命令）")
    s.set_defaults(fn=cmd_stabilize, input=[], extra=[])


def setup_audit(sub) -> None:
    s = sub.add_parser("audit", parents=[common],
                       help="名词漏校三扫（透传 subtitle_calib_merged.py 的 audit 子命令；"
                            "拉丁残留 / 错形残留 / 同词族一致性，退出码 1＝有候选）")
    s.set_defaults(fn=cmd_audit, input=[], extra=[])