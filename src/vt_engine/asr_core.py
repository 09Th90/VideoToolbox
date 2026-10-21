# @version 2.4.1
"""ASR 执行链收口（复用自研接缝模块 ``engine_asr``）。

``WhisperAPI``（OpenAI 兼容客户端）、``BaseASR``（CRC32 + 磁盘缓存 +
模板方法）、``ChunkedASR`` + ``ChunkMerger``（分块几何 600s/10s/并发3，
行为契约）、``transcribe`` 编排入口——均已对着引擎逐段交叉验证。

缓存工厂注入：宿主通过 :func:`set_cache_hub` 注入进程内共享 hub；
未注入时落 ``default_cache_hub()``（与引擎缓存同址，两套实现共享同一
磁盘目录但各自持连接——故主程序内应优先注入同一 hub）。
"""

from __future__ import annotations

from vt_engine._bootstrap import SRC_DIR  # noqa: F401

from engine_asr import (  # noqa: E402
    ASRStatus,
    BaseASR,
    ChunkedASR,
    ChunkMerger,
    WhisperAPI,
    transcribe,
    set_cache_hub,
    set_ffmpeg,
    CHUNK_LENGTH_SEC,
    CHUNK_OVERLAP_SEC,
    CHUNK_CONCURRENCY,
    ASR_CACHE_EXPIRE,
)

__all__ = [
    "ASRStatus",
    "BaseASR",
    "ChunkedASR",
    "ChunkMerger",
    "WhisperAPI",
    "transcribe",
    "set_cache_hub",
    "set_ffmpeg",
    "CHUNK_LENGTH_SEC",
    "CHUNK_OVERLAP_SEC",
    "CHUNK_CONCURRENCY",
    "ASR_CACHE_EXPIRE",
    "default_asr_cache_hub",
]


def default_asr_cache_hub():
    """未注入时的兜底缓存工厂（惰性，落引擎缓存同址）。"""
    from vt_engine.cache import default_cache_hub
    return default_cache_hub()
