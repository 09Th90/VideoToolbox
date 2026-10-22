# @version 2.5.4
"""ASR HTTP 传输层收口（复用自研接缝模块 ``engine_asr_http``）。

multipart 上传与错误语义（``AsrHttpError`` 带 status/body）已可用本地假
HTTP 服务覆盖测试，不依赖真实 ASR 服务，也不产生费用。
"""

from __future__ import annotations

from vt_engine._bootstrap import SRC_DIR  # noqa: F401

from engine_asr_http import (  # noqa: E402
    post_transcription,
    transcription_url,
    AsrHttpError,
)

__all__ = ["post_transcription", "transcription_url", "AsrHttpError"]
