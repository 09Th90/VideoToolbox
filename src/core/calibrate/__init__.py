# -*- coding: utf-8 -*-
# @version 2.4.0
"""校准域（core/calibrate）：AI 校准入口 + 多用户同步（GitHub/本地镜像/声纹）。

子模块：
  · ``ai``    calib_ai_chat / calib_web_proxy / calib_ai_run + 同步开关
  · ``sync``  GitHub 整文件通道（_gh_* 家族）+ 本地增量镜像 + 声纹 inbox
             同步 + sync_env_into（A3-2 追认自 shared 移入——与同步家族同段）

合并纯函数在根目录 calib_merge_core（GUI 引擎/退出同步/CI 共用）。

依赖规则：只准依赖 core/shared；对 asr 的引用函数内延迟（见 ai.py）。
"""
from .ai import *  # noqa: F401,F403
from .sync import *  # noqa: F401,F403

from .ai import __all__ as _ai_all
from .sync import __all__ as _sync_all

__all__ = sorted(set(_ai_all + _sync_all))
