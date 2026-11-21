# -*- coding: utf-8 -*-
# @version 3.1.5
"""subtitle_edit 功能清单。GUI「字幕编辑」页；内嵌字幕对话框 ComposeDialog 属本功能。"""
from features._registry import FeatureSpec, GuiSpec

FEATURE = FeatureSpec(
    id="subtitle_edit",
    title="字幕编辑",
    summary="字幕编辑/时间轴/ mpv 预览/内嵌字幕（不重编码）",
    backend="subtitle_editor_core",
    requires=("qt", "mpv"),
    services={"build_page": "features.subtitle_edit.page:build_page"},
    gui=GuiSpec(nav="字幕编辑",
                builder="features.subtitle_edit.page:build_page",
                position="top", order=50, object_name="SubtitleEditPage",
                icon="CUT", attr="subtitle_edit_page"),
    order=50,
)