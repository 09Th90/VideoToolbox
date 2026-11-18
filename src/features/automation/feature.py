# -*- coding: utf-8 -*-
# @version 3.1.0
"""automation 功能清单。GUI 侧 auto_vision_page 已在外部模块（阶段③注册挂载）。"""
from features._registry import CliCommand, FeatureSpec, GuiSpec

FEATURE = FeatureSpec(
    id="automation",
    title="自动化投稿",
    summary="B 站后台自动投稿（UIA 定位 + PostMessage 输入）/ 视觉状态机",
    backend="features.automation.bili_auto_submit",
    requires=("uia", "network"),
    services={},
    cli=(CliCommand(
        name="bili-submit",
        help="B 站后台自动投稿（UI Automation 定位 + 后台输入；素材目录内含投稿信息.txt）",
        setup="features.automation.cli:setup_bili_submit"),),
    gui=GuiSpec(nav="自动化", builder="vt_app.main_window:_build_auto_page_entry",
                position="bottom", order=90, object_name="AutoVisionPage",
                icon="ROBOT", attr="auto_page"),
    order=90,
)