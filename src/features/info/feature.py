# -*- coding: utf-8 -*-
# @version 3.2.0
"""info 功能清单。ffprobe 探媒体；字幕摘要复用 ASRData（服务表声明）。"""
from features._registry import CliCommand, FeatureSpec

FEATURE = FeatureSpec(
    id="info",
    title="媒体元信息",
    summary="ffprobe 媒体元信息 + 字幕 cue 数/时间跨度摘要",
    backend="",
    requires=("ffprobe",),
    services={"from_subtitle_file": "engine_asr_data:ASRData.from_subtitle_file"},
    cli=(CliCommand(
        name="info",
        help="媒体/字幕元信息（ffprobe；字幕给 cue 数与时间跨度）",
        setup="features.info.cli:setup_info"),),
    order=20,
)