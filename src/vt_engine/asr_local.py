# @version 2.4.1
"""本地 faster-whisper 收口（复用自研接缝模块 ``engine_asr_local``）。

faster-whisper 是 MIT 组件（保留并登记），作为 local 模式的实现；
幻觉文本过滤关键词与 RTX 50 探测保持与接缝模块一致。
"""

from __future__ import annotations

from vt_engine._bootstrap import SRC_DIR  # noqa: F401

from engine_asr_local import (  # noqa: E402
    FasterWhisperASR,
    HALLUCINATION_KEYWORDS,
    is_rtx_50_series,
)

__all__ = ["FasterWhisperASR", "HALLUCINATION_KEYWORDS", "is_rtx_50_series"]
