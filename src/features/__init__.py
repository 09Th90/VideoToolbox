# -*- coding: utf-8 -*-
# @version 3.2.0
"""features —— 功能层：每个功能一个独立包，清单注册、惰性加载、错误隔离。

* 契约与注册表实现见 ``_registry.py``；新功能模板见 ``_template/``。
* 本 ``__init__`` **零副作用**：发现只发生在首次 ``registry()`` 调用时。
* 依赖红线：适配器（feature.py / cli.py）模块级禁 Qt；页面（page.py）只经
  vt_app 基建 + 注册表服务，禁止反向 import GUI 入口。
* 模块位置（2026-11-15 模块独立文件夹）：功能专属实现一律放各功能包内；
  src 顶层只留入口/壳层/共享接缝六件，禁止新增顶层域模块。
"""
from ._registry import (CliCommand, FeatureRegistry, FeatureSpec, FeatureStatus,
                        FeatureUnavailable, GuiSpec, resolve)

__all__ = ["CliCommand", "FeatureRegistry", "FeatureSpec", "FeatureStatus",
           "FeatureUnavailable", "GuiSpec", "resolve", "registry"]

_default = None


def registry() -> FeatureRegistry:
    """全局单例注册表（首次调用自动 discover）。"""
    global _default
    if _default is None:
        _default = FeatureRegistry()
        _default.discover()
    return _default