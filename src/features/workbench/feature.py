# -*- coding: utf-8 -*-
# @version 3.3.1
"""workbench 功能清单。GUI「字幕处理」页；依赖 transcribe/translate 服务。"""
from features._registry import FeatureSpec, GuiSpec

FEATURE = FeatureSpec(
    id="workbench",
    title="字幕工作台",
    summary="转录→翻译→合成一体工作台（自研 vt_engine_ui 优先，videocaptioner 回退）",
    backend="vt_engine_ui",
    requires=("qt",),
    services={"build_page": "features.workbench.page:build_page"},
    # 常驻真身（lazy=False）：首页任务创建/启动期 prewarm_import 都直接取
    # subtitle_page 属性，惰性化会改变启动行为——保持与旧硬编码一致。
    gui=GuiSpec(nav="字幕处理", builder="features.workbench.page:build_page",
                position="top", order=40, object_name="SubtitlePage",
                icon="FONT", attr="subtitle_page", lazy=False, sep_before=True,
                messages=("cal_",)),
    order=40,
)