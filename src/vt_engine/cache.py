# @version 2.5.0
"""磁盘缓存收口（复用自研接缝模块 ``engine_cache``）。

:class:`CacheHub` 持有 5 类缓存的惰性工厂（llm / asr / tts / translate /
version_state），目录名是**持久化契约**——已有用户的缓存文件在这些目录下，
改名等于全部失效重算。本包不另建一套，直接复用同一实现。
"""

from __future__ import annotations

from vt_engine._bootstrap import SRC_DIR  # noqa: F401

from engine_cache import (  # noqa: E402
    CacheHub,
    LazyCache,
    generate_cache_key,
    enable_cache,
    disable_cache,
    is_cache_enabled,
    memoize,
    CACHE_KINDS,
)

__all__ = [
    "CacheHub",
    "LazyCache",
    "generate_cache_key",
    "enable_cache",
    "disable_cache",
    "is_cache_enabled",
    "memoize",
    "CACHE_KINDS",
    "default_cache_hub",
]


def default_cache_hub() -> CacheHub:
    """按当前运行上下文构造默认缓存工厂（惰性建库，无副作用）。"""
    from vt_engine.paths import default_engine_paths
    return CacheHub(str(default_engine_paths().cache_path))
