# -*- coding: utf-8 -*-
# @version 3.3.1
"""字幕后端：本地 Index-Echo 一体式、云端 Qwen-Audio ASR + Edge 翻译。"""
from .base import CloudError, SubtitleBackend
from .cloud import CloudBackend
from .local import LocalBackend

__all__ = ["SubtitleBackend", "CloudError", "LocalBackend", "CloudBackend",
           "build_backends"]


def build_backends(cfg, engine=None, calibrator=None):
    """装配 (local, cloud)。cloud 始终返回对象，未配置时由 Router 走纯本地；
    这样运行期补上凭据即可经 cred_revision 自动回探启用，无需重启。"""
    local = LocalBackend(engine) if engine is not None else None
    cloud = CloudBackend(cfg, calibrator=calibrator)
    return local, cloud
