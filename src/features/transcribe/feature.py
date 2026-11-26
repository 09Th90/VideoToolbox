# -*- coding: utf-8 -*-
# @version 3.3.1
"""transcribe 功能清单。GUI 侧由 workbench（字幕工作台）承载。"""
from features._registry import CliCommand, FeatureSpec

FEATURE = FeatureSpec(
    id="transcribe",
    title="语音转录",
    summary="ASR 转录出 SRT（service/local 双槽，模型/密钥读设置页 ASR 槽）",
    backend="features.transcribe.engine_asr",
    requires=("ffmpeg", "asr"),
    services={
        "transcribe": "features.transcribe.engine_asr:transcribe",
        "set_ffmpeg": "features.transcribe.engine_asr:set_ffmpeg",
        "create_transcribe_task": "engine_task_factory:TaskFactory.create_transcribe_task",
    },
    cli=(CliCommand(
        name="transcribe",
        help="ASR 转录出 SRT（模型/密钥读设置页 ASR 槽）",
        setup="features.transcribe.cli:setup_transcribe"),),
    order=40,
)