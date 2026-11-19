# -*- coding: utf-8 -*-
# @version 3.1.1
"""info 子命令：媒体 / 字幕元信息（原 agent_cli.cmd_info，行为不变）。"""
from __future__ import annotations

import json
import os
import subprocess

from features._cli import (_emit, _engine, _fail, _rate, _to_float, _to_int,
                           common)


def cmd_info(args) -> int:
    path = os.path.abspath(args.file)
    if not os.path.isfile(path):
        return _fail(args, "文件不存在：%s" % path)
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    engine = _engine()
    if ext in ("srt", "ass", "vtt", "ssa", "txt", "json"):
        return _info_subtitle(args, path, ext)
    if ext in ("mp3", "m4a", "wav", "flac", "aac", "ogg", "opus"):
        return _info_av(args, path, kind="audio")
    if ext in ("mp4", "mkv", "webm", "mov", "avi", "flv", "ts", "m4v",
               "weba", "mka", "mpg", "mpeg"):
        return _info_av(args, path, kind="video")
    # 未知扩展名按 ffprobe 探测结果判定
    probe = _ffprobe_json(engine, path)
    if probe is None:
        return _fail(args, "无法识别的文件类型：%s" % ext)
    fmt = (probe.get("format") or {}).get("format_name", "")
    if any(k in fmt for k in ("mp3", "aac", "flac", "wav", "ogg", "opus", "m4a")):
        return _info_av(args, path, kind="audio")
    return _info_av(args, path, kind="video")


def _ffprobe_json(engine, path):
    try:
        proc = subprocess.run(
            [engine.FFPROBE_PATH, "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", path],
            capture_output=True, timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if proc.returncode != 0:
            return None
        return json.loads(proc.stdout.decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        return None


def _info_av(args, path, kind):
    engine = _engine()
    probe = _ffprobe_json(engine, path)
    if probe is None:
        return _fail(args, "ffprobe 解析失败：%s" % path)
    fmt = probe.get("format") or {}
    streams = probe.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    result = {
        "ok": True,
        "file": path,
        "kind": kind,
        "duration_sec": _to_float(fmt.get("duration")),
        "size_bytes": _to_int(fmt.get("size")),
        "format": fmt.get("format_name"),
        "video": None if video is None else {
            "codec": video.get("codec_name"),
            "width": video.get("width"), "height": video.get("height"),
            "fps": _to_float(video.get("avg_frame_rate") and
                             _rate(video.get("avg_frame_rate"))),
        },
        "audio": None if audio is None else {
            "codec": audio.get("codec_name"),
            "channels": audio.get("channels"),
            "sample_rate": _to_int(audio.get("sample_rate")),
        },
        "n_streams": len(streams),
    }
    return _emit(args, result)


def _info_subtitle(args, path, ext):
    from engine_asr_data import ASRData  # noqa: PLC0415 —— 惰性
    try:
        data = ASRData.from_subtitle_file(path)
    except Exception as e:  # noqa: BLE001
        return _fail(args, "字幕解析失败：%s" % e)
    segs = list(getattr(data, "segments", []) or [])
    span = ""
    if segs:
        first = getattr(segs[0], "start_time", None)
        last = getattr(segs[-1], "end_time", None)
        fmt = lambda ms: "%02d:%02d:%06.3f" % (ms // 3600000, ms // 60000 % 60, (ms % 60000) / 1000) \
            if isinstance(ms, int) else str(ms)
        span = "%s → %s" % (fmt(first), fmt(last))
    result = {
        "ok": True,
        "file": path,
        "kind": "subtitle",
        "format": ext,
        "n_cues": len(segs),
        "time_span": span,
        "n_translated": sum(1 for s in segs
                            if (getattr(s, "translated_text", "") or "").strip()),
    }
    return _emit(args, result)


def setup_info(sub) -> None:
    s = sub.add_parser("info", parents=[common],
                       help="媒体/字幕元信息（ffprobe；字幕给 cue 数与时间跨度）")
    s.add_argument("file", help="视频 / 音频 / 字幕文件路径")
    s.set_defaults(fn=cmd_info)