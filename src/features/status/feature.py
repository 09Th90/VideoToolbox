# -*- coding: utf-8 -*-
# @version 3.3.1
"""status 功能清单。后端=引擎门面级自检，无独立后端模块。"""
from features._registry import CliCommand, FeatureSpec

FEATURE = FeatureSpec(
    id="status",
    title="环境自检",
    summary="工具在位性、AI/ASR 槽配置、全功能可用性总览（--ping 实测连通）",
    backend="",
    requires=(),
    services={},
    cli=(CliCommand(
        name="status",
        help="环境/AI 配置自检（工具在位性、AI/ASR 槽是否已配）",
        setup="features.status.cli:setup_status"),),
    order=10,
)