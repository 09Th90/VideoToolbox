# -*- coding: utf-8 -*-
# @version 2.7.0
"""片源模式探测

源：subtitle_calib_merged.py L4909-L4927 @ 97d7d463（2026-10-24 冻结快照）
"""
import io
import os
import re
import shutil
import sys
import unicodedata
from .data.endfield import ENDFIELD_AUTO_MARKERS
from .text import _decode_any



def endfield_auto_markers(lines):
    """返回文本里命中的终末地双语片源特征词（去重）。"""
    blob = "\n".join(lines)
    return [m for m in ENDFIELD_AUTO_MARKERS if m in blob]



def detect_source_mode(path):
    """片源自动识别（2026-10-07）：目前只区分「终末地·中英双语」与通用双语。

    供 AI 校准代理（calib_ai_agent）与流水线在**未显式指定模式**时调用，
    避免终末地专名因走默认 bi 模式而一处不改。
    """
    try:
        lines = _decode_any(open(path, "rb").read()).split("\n")
    except OSError:
        return "bi"
    return "endobi" if len(endfield_auto_markers(lines)) >= 2 else "bi"

