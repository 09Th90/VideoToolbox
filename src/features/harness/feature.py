# -*- coding: utf-8 -*-
# @version 3.3.1
"""harness 功能清单。GUI harness_page 已在外部模块；harness 本体未部署时页面显示引导卡。"""
from features._registry import FeatureSpec, GuiSpec

FEATURE = FeatureSpec(
    id="harness",
    title="AI 托管",
    summary="DeepSeek harness 适配（node 子进程），技能包物化与配置同步",
    backend="features.harness.harness_bridge",
    requires=("node",),
    services={},
    # builder 在 harness 适配层不可用时抛异常 → 注册表挂载跳过（导航缺席），
    # 与旧 _HARNESS_IMPORT_OK 分支行为一致；harness 本体未部署时页面照建、
    # 显示部署引导卡（降级模式②，页面内处置）。
    gui=GuiSpec(nav="AI 托管", builder="vt_app.main_window:_build_harness_page_entry",
                position="bottom", order=80, object_name="HarnessPage",
                icon="IOT", attr="harness_page"),
    order=80,
)