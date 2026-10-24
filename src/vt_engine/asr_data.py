# @version 2.6.0
"""ASR 数据模型收口（复用自研接缝模块 ``engine_asr_data``）。

``ASRData`` / ``ASRDataSeg`` 的字段与导出方法（``to_srt`` / ``to_ass`` /
``save`` / ``optimize_timing`` …）是字幕链路的公共数据契约，已在主程序
接线并经逐字段交叉验证，本包直接复用，不再复制第二份实现。
"""

from __future__ import annotations

import os

from vt_engine._bootstrap import SRC_DIR  # noqa: F401

from engine_asr_data import ASRData, ASRDataSeg, handle_long_path  # noqa: E402

__all__ = [
    "ASRData",
    "ASRDataSeg",
    "handle_long_path",
    "asr_data_to_vtt",
    "save_vtt",
]


# ----------------------------------------------------------------#
# WebVTT 导出（自研）
# ----------------------------------------------------------------#
#: 引擎（与接缝模块 engine_asr_data）的 ``to_vtt`` 都是未实现桩
#: （NotImplementedError，上游把实现注释掉了）——而
#: ``TranscribeOutputFormatEnum.ALL`` 的展开**包含** vtt，走引擎路径
#: 选「全部格式」必然崩在此处。这里按 WebVTT 公开格式自研实现，
#: 时间戳沿用 SRT 的毫秒换算（逗号→点号）。


def _ms_to_vtt_ts(ms: int) -> str:
    """毫秒 → ``HH:MM:SS.mmm``（WebVTT 时间戳）。"""
    ms = max(0, int(ms))
    h, rem = divmod(ms, 3600_000)
    m, rem = divmod(rem, 60_000)
    sec, msec = divmod(rem, 1000)
    return "%02d:%02d:%02d.%03d" % (h, m, sec, msec)


def asr_data_to_vtt(asr_data: ASRData) -> str:
    """ASRData → WebVTT 文本（无样式、纯字幕块）。"""
    lines = ["WEBVTT", ""]
    for seg in asr_data.segments:
        lines.append("%s --> %s" % (_ms_to_vtt_ts(seg.start_time),
                                    _ms_to_vtt_ts(seg.end_time)))
        lines.append(seg.transcript)
        lines.append("")
    return "\n".join(lines)


def save_vtt(asr_data: ASRData, save_path: str) -> str:
    """写 WebVTT 文件并返回文本。"""
    text = asr_data_to_vtt(asr_data)
    path = handle_long_path(save_path)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return text
