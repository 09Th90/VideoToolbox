# @version 2.5.2
"""vt_engine 导入引导：把程序 src 目录放上 ``sys.path``。

本包（``vt_engine``）是「完整运行引擎」的并行开发载体，内部复用本项目
既有的自研接缝模块（``engine_asr`` / ``engine_cache`` / ``engine_paths``
等平铺模块）。这些模块与主程序同在 ``src`` 目录下；当 vt_engine 被
**单独**导入（脱离主程序的 sys.path 上下文，如自检子进程、独立 CLI）时，
平铺模块可能不可见——本模块在最早时机补上 src 目录，保证
``import engine_asr`` 与 ``import vt_engine`` 同样可行。

约束：本模块不 import 任何第三方引擎（``videocaptioner``）——那是整条
替换线的红线，由 ``scripts/dev/_selftest_vt_engine.py`` 的 AST 检查守护。
"""

from __future__ import annotations

import os
import sys

#: 本包所在目录的上一级即程序 src 目录（vt_engine 位于 src/vt_engine/）。
SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

__all__ = ["SRC_DIR"]
