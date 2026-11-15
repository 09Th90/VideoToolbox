# -*- coding: utf-8 -*-
"""pipeline 功能清单。STAGES 声明表自带 optional 降级位，缺功能时阶段自动跳过。"""
from features._registry import FeatureSpec

FEATURE = FeatureSpec(
    id="pipeline",
    title="流水线",
    summary="目录感知一条龙：download→merge→transcribe→translate→calib1→calib2→package",
    backend="pipeline",
    requires=("ffmpeg", "ytdlp", "asr", "network"),
    services={},
    order=60,
)