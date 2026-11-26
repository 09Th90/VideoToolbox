# -*- coding: utf-8 -*-
# @version 3.3.1
"""publish 功能清单：发布素材生成（10 段时间轴 + 10 tag + 中文标题）。"""
from features._registry import CliCommand, FeatureSpec

FEATURE = FeatureSpec(
    id="publish",
    title="发布素材",
    summary="从字幕生成 B 站投稿素材：10 段时间轴（按剧情/≥5s/≤16字）+ 10 tag + 中文标题",
    backend="features.publish.publish_material",
    requires=(),
    services={
        "generate_material": "features.publish.publish_material:generate_material",
        "parse_srt_timed": "features.publish.publish_material:parse_srt_timed",
        "build_page": "features.publish.page:build_page",
    },
    cli=(CliCommand(
        name="publish",
        help="发布素材：从字幕生成 10 段时间轴 + 10 tag + 中文标题（投稿信息.txt）",
        setup="features.publish.cli:setup_publish"),),
    order=85,
)