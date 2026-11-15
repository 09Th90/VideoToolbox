# -*- coding: utf-8 -*-
"""workbench 功能清单。GUI「字幕处理」页；依赖 transcribe/translate 服务。"""
from features._registry import FeatureSpec

FEATURE = FeatureSpec(
    id="workbench",
    title="字幕工作台",
    summary="转录→翻译→合成一体工作台（自研 vt_engine_ui 优先，videocaptioner 回退）",
    backend="vt_engine_ui",
    requires=("qt",),
    services={},
    order=40,
)