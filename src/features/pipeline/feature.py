# -*- coding: utf-8 -*-
"""pipeline 功能清单。STAGES 声明表自带 optional 降级位，缺功能时阶段自动跳过。"""
from features._registry import FeatureSpec, GuiSpec

FEATURE = FeatureSpec(
    id="pipeline",
    title="流水线",
    summary="目录感知一条龙：download→merge→transcribe→translate→calib1→calib2→package",
    backend="features.pipeline.pipeline",
    requires=("ffmpeg", "ytdlp", "asr", "network"),
    services={"build_page": "features.pipeline.page:build_page"},
    gui=GuiSpec(nav="流水线", builder="features.pipeline.page:build_page",
                position="top", order=60, object_name="PipelinePage",
                icon="SYNC", attr="pipeline_page", messages=("pipe_",)),
    order=60,
)