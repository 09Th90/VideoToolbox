# -*- coding: utf-8 -*-
# @version 3.1.3
"""_api.runtime —— API 层运行时纯工具（L1 共享接缝，2026-11-20 三层独立）。

从 features/_cli.py 下沉的**纯工具**副本（_cli 属 L2 CLI 入口层，_api 禁 import）。
时间戳格式 / 数据根解析口径必须与 _cli 完全一致（golden 冻结）。
本模块只依赖标准库；引擎门面惰性 import（L0 允许）。
"""
from __future__ import annotations

import os
import time

#: 程序根（本文件在 src/features/_api/，上四级）
APP_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

#: status.version 字段的契约值——与 agent_cli 的 CLI 自身版本同源冻结
#: （agent_cli --version 输出 "agent_cli 1.0.0"，golden 基线冻结；非工具箱 VERSION）
API_VERSION = "1.0.0"


def _engine():
    """惰性加载引擎门面（L0；体量大，且要求 VT_DATA_ROOT 先就位）。"""
    import video_toolbox as engine  # noqa: PLC0415 —— 惰性
    return engine


def _data_root() -> str:
    """解析后的数据根（与引擎/_cli 同口径：VT_DATA_ROOT > data_dir.txt > 程序根）。"""
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
    """CLI/API 产物默认目录（时间戳只到秒——并发调用方必须显式 out）。"""
    return os.path.join(_data_root(), "data", "agent_out",
                        time.strftime("%Y%m%d-%H%M%S"))


def _mod(name):
    import importlib  # noqa: PLC0415
    return importlib.import_module(name)


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