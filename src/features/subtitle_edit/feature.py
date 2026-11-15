# -*- coding: utf-8 -*-
"""subtitle_edit 功能清单。GUI「字幕编辑」页；内嵌字幕对话框 ComposeDialog 属本功能。"""
from features._registry import FeatureSpec

FEATURE = FeatureSpec(
    id="subtitle_edit",
    title="字幕编辑",
    summary="字幕编辑/时间轴/ mpv 预览/内嵌字幕（不重编码）",
    backend="subtitle_editor_core",
    requires=("qt", "mpv"),
    services={},
    order=50,
)