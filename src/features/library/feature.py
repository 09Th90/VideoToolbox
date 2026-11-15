# -*- coding: utf-8 -*-
"""library 功能清单。GUI「视频库」页；扫盘惰性（用户首次打开才执行）。"""
from features._registry import FeatureSpec

FEATURE = FeatureSpec(
    id="library",
    title="视频库",
    summary="媒体文件注册/类型表/目录监视，下载产物自动入库",
    backend="media_registry",
    requires=(),
    services={},
    order=30,
)