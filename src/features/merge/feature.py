# -*- coding: utf-8 -*-
# @version 3.1.3
"""merge 功能清单。无独立 CLI 子命令；GUI 为「视频处理」容器页的子板块。"""
from features._registry import FeatureSpec

FEATURE = FeatureSpec(
    id="merge",
    title="音视频合并",
    summary="视频 + 独立音轨合并（merge_pair，可选字幕硬烧/封装）",
    backend="core.download.media",
    requires=("ffmpeg",),
    services={"merge_pair": "core.download.media:merge_pair",
              "build_page": "features.merge.page:build_page"},
    order=31,
)