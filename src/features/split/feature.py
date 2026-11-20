# -*- coding: utf-8 -*-
# @version 3.1.2
"""split 功能清单。video_split 是解耦样板：纯标准库、不 import Qt。"""
from features._registry import CliCommand, FeatureSpec

FEATURE = FeatureSpec(
    id="split",
    title="视频切片",
    summary="按时间点/时长拆段，copy→MKV→H.264 三级回退，逐段校验可播放",
    backend="features.split.video_split",
    requires=("ffmpeg", "ffprobe"),
    services={
        "probe_media": "features.split.video_split:probe_media",
        "plan_split": "features.split.video_split:plan_split",
        "split_video": "features.split.video_split:split_video",
        "hms": "features.split.video_split:hms",
        "build_page": "features.split.page:build_page",
    },
    cli=(CliCommand(
        name="split",
        help="视频切片：按时间点（HH:MM:SS）或时长（xHyMzS）拆成多段，逐段校验可播放",
        setup="features.split.cli:setup_split"),),
    order=80,
)