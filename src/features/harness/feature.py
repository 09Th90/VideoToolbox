# -*- coding: utf-8 -*-
"""harness 功能清单。GUI harness_page 已在外部模块；harness 本体未部署时页面显示引导卡。"""
from features._registry import FeatureSpec

FEATURE = FeatureSpec(
    id="harness",
    title="AI 托管",
    summary="DeepSeek harness 适配（node 子进程），技能包物化与配置同步",
    backend="harness_bridge",
    requires=("node",),
    services={},
    order=80,
)