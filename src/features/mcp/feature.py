# -*- coding: utf-8 -*-
# @version 3.3.1
"""mcp 功能清单（纯清单，模块级禁 SDK/Qt——status 探针只查 find_spec）。"""
from __future__ import annotations

from features._registry import FeatureSpec

FEATURE = FeatureSpec(
    id="mcp",
    title="MCP 服务",
    summary="对外 MCP host 接入（stdio）；与 CLI 共用 features._api 业务层",
    backend="",
    requires=("mcp",),
    check="features.mcp.feature:_probe",
    order=95,
)


def _probe():
    """轻量可用性探针：只查 SDK 在位性，不 import（零副作用）。"""
    import importlib.util  # noqa: PLC0415
    ok = importlib.util.find_spec("mcp") is not None
    return ok, ("mcp SDK 在位" if ok
                else "缺 mcp SDK（tools\\python -m pip install mcp==2.3.0；仅外部客户端需要）")