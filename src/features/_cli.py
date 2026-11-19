# -*- coding: utf-8 -*-
# @version 3.1.1
"""CLI 共享基础设施 —— 数据根 / JSON 信封 / 引擎惰性加载（纯标准库）。

从 agent_cli.py 下沉（2026-11-15 功能解耦）：各功能的 cli.py 共用这一套
信封与工具函数，行为与原 agent_cli 完全一致。agent_cli.py 保留兼容再导出。

约定（与 SKILL.md 同源）：
* ``--json``  stdout 只落一个 JSON 对象；过程日志走 stderr
* 退出码 0 成功 / 1 失败；透传类子命令原样透传脚本退出码
* ``_apply_data_root`` 必须在 import 引擎**之前**调用
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

#: 程序根（``<根>\src\features\_cli.py`` → ``<根>``）
APP_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
#: CLI 自身版本（与工具箱 VERSION 独立；--version 输出含 "agent_cli" 字样是契约）
VERSION = "1.0.0"


# ============================================================
# 数据根 / 引擎惰性加载
# ============================================================
def _apply_data_root(args) -> None:
    """把 --data-root 落成 VT_DATA_ROOT（必须在 import 引擎之前调用）。"""
    dr = (getattr(args, "data_root", "") or "").strip().strip('"')
    if dr and os.environ.get("VT_DATA_ROOT", "") != dr:
        os.environ["VT_DATA_ROOT"] = os.path.abspath(dr)


def _engine():
    """惰性加载引擎门面（体量大，且要求 VT_DATA_ROOT 先就位）。"""
    import video_toolbox as engine  # noqa: PLC0415 —— 惰性
    return engine


def _data_root() -> str:
    """解析后的数据根（与引擎同口径，供不 import 引擎的轻路径使用）。"""
    env = (os.environ.get("VT_DATA_ROOT") or "").strip().strip('"')
    if env:
        return os.path.abspath(env)
    pointer = os.path.join(APP_ROOT, "data_dir.txt")
    try:
        if os.path.isfile(pointer):
            with open(pointer, encoding="utf-8-sig") as f:
                v = f.read().strip().strip('"')
            if v:
                return os.path.abspath(v)
    except OSError:
        pass
    return APP_ROOT


def _agent_out_dir() -> str:
    return os.path.join(_data_root(), "data", "agent_out",
                        time.strftime("%Y%m%d-%H%M%S"))


def _mod(name):
    import importlib  # noqa: PLC0415
    return importlib.import_module(name)


# ============================================================
# 输出信封
# ============================================================
def _say(args, msg: str) -> None:
    """过程日志：人读模式走 stdout，--json 模式走 stderr（stdout 留给 JSON）。"""
    if getattr(args, "as_json", False):
        print(msg, file=sys.stderr)
    else:
        print(msg)


def _emit(args, payload: dict) -> int:
    """最终结果输出。--json 落单个 JSON 到 stdout；否则人读摘要。返回退出码。"""
    ok = bool(payload.get("ok"))
    if getattr(args, "as_json", False):
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if ok else 1
    for line in _human_lines(payload):
        print(line)
    return 0 if ok else 1


def _human_lines(payload: dict) -> list:
    """把结果 dict 转成人读摘要（只挑关键键，其余进 detail）。"""
    lines = ["ok: %s" % payload.get("ok")]
    for k, v in payload.items():
        if k in ("ok",):
            continue
        if isinstance(v, (dict, list)):
            v = json.dumps(v, ensure_ascii=False)
        lines.append("%s: %s" % (k, v))
    return lines


def _fail(args, error: str, **extra) -> int:
    return _emit(args, {"ok": False, "error": error, **extra})


# ============================================================
# 数值小工具（info / download 共用）
# ============================================================
def _to_float(v):
    try:
        return round(float(v), 3)
    except (TypeError, ValueError):
        return None


def _to_int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _rate(txt):
    try:
        num, _, den = txt.partition("/")
        d = float(den or 1)
        return float(num) / d if d else None
    except (TypeError, ValueError):
        return None


# ============================================================
# argparse 全局选项的「子命令级副本」
# ============================================================
#: Agent 写成 ``status --json``（选项在后）是本能，两种位置都必须认。
#: default=SUPPRESS 保证未提供时不会用 False/"" 覆盖全局值。
common = argparse.ArgumentParser(add_help=False)
common.add_argument("--json", dest="as_json", action="store_true",
                    default=argparse.SUPPRESS,
                    help="结构化输出（stdout 只落一个 JSON；日志走 stderr）")
common.add_argument("--data-root", default=argparse.SUPPRESS,
                    help="数据根目录（默认：VT_DATA_ROOT > data_dir.txt > 程序根）")