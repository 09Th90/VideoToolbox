# -*- coding: utf-8 -*-
# @version 2.3.1
"""翻译域（core/translate）：翻译请求路由补丁。

子模块：
  · ``route_patch``  `vc_translate_route_patch`（把翻译请求路由钉死——
    微软直连 / 谷歌走本地代理，不跟随系统代理；v2.3.1 起含
    2026-10-17 双重保险：`__init__` 与 `translate_subtitle` 双侧包补丁）

翻译主链在 ``engine_translate``（引擎层）与 ``pipeline``（CLI 编排），
本域只收单体里残存的翻译胶水。

依赖规则：只准依赖 ``core.shared``；见 core/__init__.py。
"""
from .route_patch import *  # noqa: F401,F403

from .route_patch import __all__ as _rp_all

__all__ = sorted(set(_rp_all))
