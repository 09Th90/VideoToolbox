# -*- coding: utf-8 -*-
# @version 3.1.2
"""voiceprint 功能清单。GUI speaker_voiceprint_page 已在外部模块（阶段③注册挂载）。"""
from features._registry import FeatureSpec

FEATURE = FeatureSpec(
    id="voiceprint",
    title="声纹识别",
    summary="说话人声纹注册/识别，转录按说话人过滤",
    backend="features.voiceprint.speaker_voiceprint",
    requires=("asr",),
    services={},
    order=75,
)