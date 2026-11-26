# -*- coding: utf-8 -*-
# @version 3.3.1
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
from .data.modes import MODE_REGISTRY
from .text import _decode_any

#: 片源识别的最低命中词数（全模式统一口径；个别模式若需不同阈值，可在注册表
#: markers 之外用 marker_min 覆盖——当前 33 模式均为 2）。
DETECT_MIN_HITS = 2


def endfield_auto_markers(lines):
    """返回文本里命中的终末地双语片源特征词（去重）。"""
    blob = "\n".join(lines)
    return [m for m in ENDFIELD_AUTO_MARKERS if m in blob]


def detect_mode_score(lines):
    """片源识别打分表（P2-5）：按注册表 markers 计数，返回 [(命中数, 模式, 命中词)]。

    降序（命中多者优先，同分按模式键字典序，确定性）。没有 markers 的模式不参与——
    它们是「具备该版式的专用模式」而不是「可被特征词认出的片源类型」。
    """
    blob = "\n".join(lines)
    scored = []
    for mode, spec in MODE_REGISTRY.items():
        mk = spec.get("markers") or ()
        if not mk:
            continue
        hit = [m for m in mk if m and m in blob]
        scored.append((len(hit), mode, hit))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return scored


def detect_source_detail(path):
    """片源识别（top1 + score）：返回 (模式, 命中数, 命中词)。

    top1 命中数达到该模式阈值（markers 模式默认 DETECT_MIN_HITS，可用注册表
    marker_min 覆盖）才算认出，否则回落通用双语 "bi"。未指定模式时由 AI 校准代理
    与流水线调用，避免终末地专名因走默认 bi 而一处不改。
    """
    try:
        lines = _decode_any(open(path, "rb").read()).split("\n")
    except OSError:
        return ("bi", 0, [])
    for score, mode, hits in detect_mode_score(lines):
        need = int((MODE_REGISTRY.get(mode) or {}).get("marker_min", DETECT_MIN_HITS))
        if score >= need:
            return (mode, score, hits)
    return ("bi", 0, [])


def detect_source_mode(path):
    """片源自动识别（兼容入口，返回模式键）。"""
    return detect_source_detail(path)[0]

