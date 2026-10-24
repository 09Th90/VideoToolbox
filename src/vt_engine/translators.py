# @version 2.7.0
"""机翻翻译器收口（复用自研接缝模块 ``engine_translate``）。

微软 / 谷歌 / DeepLx 三个免费端点的自研实现：会话显式直连
（``trust_env=False``）、失败条目标 ``ERROR`` 交上层兜底、缓存键
``类名:内容哈希:目标语言`` 与引擎一致。``GoogleTranslator`` 在本机
网络下不可用（421，历史实测）⇒ 探测与翻译都短路，不发无效请求。
"""

from __future__ import annotations

from vt_engine._bootstrap import SRC_DIR  # noqa: F401

from engine_translate import (  # noqa: E402
    BaseSubtitleTranslator,
    BingTranslator,
    GoogleTranslator,
    DeepLxTranslator,
    ERROR_MARK,
    make_translator,
    probe_translator,
    probe_translator_cached,
    TRANSLATOR_PROBES,
)

__all__ = [
    "BaseSubtitleTranslator",
    "BingTranslator",
    "GoogleTranslator",
    "DeepLxTranslator",
    "ERROR_MARK",
    "make_translator",
    "probe_translator",
    "probe_translator_cached",
    "TRANSLATOR_PROBES",
]
