# -*- coding: utf-8 -*-
# @version 3.1.6
"""translate 功能清单。GUI 侧由 workbench（字幕工作台）承载。"""
from features._registry import CliCommand, FeatureSpec

FEATURE = FeatureSpec(
    id="translate",
    title="字幕翻译",
    summary="bing/google/deeplx 免认证端点，双语 SRT（原文在上译文在下）",
    backend="features.translate.engine_translate",
    requires=("network",),
    services={"make_translator": "features.translate.engine_translate:make_translator"},
    cli=(CliCommand(
        name="translate",
        help="翻译字幕（bing/google/deeplx 免认证端点）",
        setup="features.translate.cli:setup_translate"),),
    order=50,
)