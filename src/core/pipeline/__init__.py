# -*- coding: utf-8 -*-
# @version 2.5.2
"""流水线域（core/pipeline）：CLI 编排入口 + 下载字幕滚动重叠整理。

子模块：
  · ``main``         CLI 主入口（下载/合并模式分发；编排层，横向依赖 download）
  · ``srt_rolling``  滚动式重叠整理（srt_time_to_ms / ms_to_srt_time /
                     normalize_rolling_srt + 门槛常量）

依赖规则：pipeline 为编排层，允许横向依赖 core/download；其余域不横向。
"""
from .srt_rolling import *  # noqa: F401,F403
from .main import *  # noqa: F401,F403

from .srt_rolling import __all__ as _sr_all

__all__ = sorted(set(_sr_all + ["main"]))
