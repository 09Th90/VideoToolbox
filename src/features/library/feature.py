# -*- coding: utf-8 -*-
# @version 3.0.0
"""library 功能清单。GUI「视频库」页；扫盘惰性（用户首次打开才执行）。"""
from features._registry import FeatureSpec, GuiSpec

FEATURE = FeatureSpec(
    id="library",
    title="视频库",
    summary="媒体文件注册/类型表/目录监视，下载产物自动入库",
    backend="features.library.media_registry",
    requires=(),
    services={"build_page": "features.library.page:build_page"},
    gui=GuiSpec(nav="视频库", builder="features.library.page:build_page",
                position="top", order=30, object_name="LibraryPage",
                icon="VIDEO", attr="library_page", messages=("lib_",)),
    order=30,
)