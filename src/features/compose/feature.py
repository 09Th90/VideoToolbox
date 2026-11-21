# -*- coding: utf-8 -*-
# @version 3.1.5
"""compose 功能清单。CLI soft 模式走 subtitle_compose_core（不再拖 Qt）。"""
from features._registry import CliCommand, FeatureSpec

FEATURE = FeatureSpec(
    id="compose",
    title="字幕合成",
    summary="软封装（copy 不重编码）/ ASS 硬烧录 / 带独立音轨 merge_pair 合并",
    backend="features.compose.subtitle_compose_core",
    requires=("ffmpeg",),
    services={
        "build_command": "features.compose.subtitle_compose_core:build_command",
        "merge_pair": "core.download.media:merge_pair",
    },
    cli=(CliCommand(
        name="compose",
        help="字幕合成：软封装（copy）/ 硬烧录 / 带独立音轨合并",
        setup="features.compose.cli:setup_compose"),),
    order=70,
)