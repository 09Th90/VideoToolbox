# -*- coding: utf-8 -*-
# @version 3.1.3
"""字幕合成纯函数核心（无 Qt、无本项目依赖，可独立单测）。

2026-11-15 功能解耦：从 subtitle_compose.py 拆出。原文件里「命令拼装 / 进度
解析 / 默认输出名」本就是纯函数，但与 ComposeDialog 同文件，导致 CLI 软封装
路径（agent_cli compose --mode soft）被迫 import PySide6+vt_fluent 整条 GUI
依赖链。拆出后 CLI 只碰本模块；subtitle_compose.py 再导出旧名，调用方零改动。

内嵌字幕（`-c:v copy -c:a copy -c:s mov_text`）只把字幕当独立轨道塞进容器，
音视频字节级原样搬过去，不重新编码——设计取舍详见 subtitle_compose.py 头注。
"""
import os
import re

#: 容器 -> 字幕编码。mp4 系只吃 mov_text；mkv 用原生 srt，兼容性最好
SOFT_CODECS = {
    ".mp4": "mov_text",
    ".m4v": "mov_text",
    ".mov": "mov_text",
    ".mkv": "srt",
}


def build_command(ffmpeg, video, subtitle, output):
    """拼出「内嵌字幕」的 ffmpeg 参数表（list，不经过 shell）。

    返回 `(argv, 错误信息)`；错误信息非空时应直接提示用户，不要启动进程。
    音视频一律 `copy`、只多一条字幕轨——所以这个操作**不重新编码**。
    """
    for label, p in (("视频", video), ("字幕", subtitle)):
        if not p or not os.path.isfile(p):
            return None, "%s文件不存在：%s" % (label, p or "(空)")
    if not output:
        return None, "没有指定输出文件"

    ext = os.path.splitext(output)[1].lower()
    codec = SOFT_CODECS.get(ext)
    if codec is None:
        return None, "只支持 .mp4 / .mkv 输出（当前 %s）" % (ext or "无扩展名")

    out_dir = os.path.dirname(os.path.abspath(output))
    if out_dir and not os.path.isdir(out_dir):
        return None, "输出目录不存在：%s" % out_dir

    # `-y` 是无条件覆盖，别让用户一不小心把原片写没了
    if os.path.abspath(output) == os.path.abspath(video):
        return None, "输出文件不能就是原视频本身，换个文件名"

    return [
        ffmpeg, "-y", "-hide_banner",
        # GUI 调 ffmpeg 的常规护身符：免得它去读一个永远不产出数据的 stdin 句柄
        "-nostdin",
        "-i", video,
        # 进度走 stdout；`-progress` 的字段名骗人，解析见 parse_progress
        "-progress", "pipe:1", "-nostats",
        "-i", subtitle,
        "-map", "0:v:0", "-map", "0:a?", "-map", "1:0",
        "-c:v", "copy", "-c:a", "copy", "-c:s", codec,
        "-metadata:s:s:0", "language=chi",
        output,
    ], ""


_KEY_RE = re.compile(r"^([A-Za-z_]+)=(.*)$")


def parse_progress(line, total_ms):
    """解析一行 `-progress` 输出；返回 0-100 的整数，或 None（不是进度行）。

    注意：`out_time_ms` 的**单位其实是微秒**——ffmpeg 这个字段名是历史遗留的
    坑，按毫秒算会得到 1000 倍的速度。上限压到 99，100 只由 `progress=end`
    给出。内嵌只用 copy，通常几秒结束，进度可能直接跳到 100，属正常。
    """
    m = _KEY_RE.match((line or "").strip())
    if not m:
        return None
    key, val = m.group(1), m.group(2).strip()
    if key == "progress":
        return 100 if val == "end" else None
    if key in ("out_time_ms", "out_time_us"):
        if not total_ms:
            return None
        try:
            us = int(float(val))
        except (TypeError, ValueError):
            return None
        if us < 0:
            us = 0
        return min(99, int(us / 1000.0 * 100.0 / float(total_ms)))
    return None


def default_output(video):
    """默认输出名：`<视频名>_内嵌字幕.mp4`。"""
    stem = os.path.splitext(video or "output")[0]
    return stem + "_内嵌字幕.mp4"