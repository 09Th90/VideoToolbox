# -*- coding: utf-8 -*-
"""compose 子命令（原 agent_cli.cmd_compose）。

2026-11-15 功能解耦：soft 模式改 import subtitle_compose_core（纯函数、无 Qt），
修掉「CLI 合成软字幕却拖着 PySide6+vt_fluent 依赖链」的泄漏点。
"""
from __future__ import annotations

import os
import subprocess

from features._cli import _agent_out_dir, _emit, _engine, _fail, _say, common


def cmd_compose(args) -> int:
    engine = _engine()
    ffmpeg_path, _ = engine.ensure_ffmpeg()
    video = os.path.abspath(args.video)
    sub = os.path.abspath(args.sub)
    for label, p in (("视频", video), ("字幕", sub)):
        if not os.path.isfile(p):
            return _fail(args, "%s文件不存在：%s" % (label, p))
    audio = os.path.abspath(args.audio) if args.audio else ""
    if audio and not os.path.isfile(audio):
        return _fail(args, "音轨文件不存在：%s" % audio)
    ext = os.path.splitext(sub)[1].lower()
    out = os.path.abspath(args.out) if args.out else os.path.join(
        _agent_out_dir(),
        os.path.splitext(os.path.basename(video))[0] + ".composed.mp4")
    if os.path.abspath(out) == video:
        return _fail(args, "输出文件不能就是原视频本身")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)

    # —— 带独立音轨（下载产物合并场景）→ 引擎 merge_pair ——
    if audio:
        atype = "m4a" if audio.lower().endswith(".m4a") else "weba"
        sub_type = "srt" if ext == ".srt" else "ass"
        _say(args, "[信息] 走引擎 merge_pair（%s 音轨 + %s 字幕，%s）"
             % (atype, sub_type, "硬烧" if (sub_type == "ass" and
                                            args.mode != "mkv") else "封装"))
        engine.merge_pair(video, audio, atype, sub, sub_type, out,
                          ffmpeg_path,
                          ass_mode="burn" if args.mode == "burn" else
                          ("mkv" if out.lower().endswith(".mkv") else "burn"))
        if not os.path.isfile(out):
            return _fail(args, "合成失败（merge_pair 未产出文件），详见上方输出")
        return _emit(args, {"ok": True, "video": video, "subtitle": sub,
                            "audio": audio, "output": out, "mode": "merge"})

    # —— 无独立音轨：soft（封装软字幕，不重编码）/ burn（ASS 硬烧，重编码）——
    if args.mode == "burn":
        sub_clean = sub.replace("\\", "/").replace("'", "\\'")
        argv = [ffmpeg_path, "-y", "-nostdin", "-i", video,
                "-vf", "subtitles='%s'" % sub_clean,
                "-c:v", "libx264", "-crf", "18", "-preset", "fast",
                "-c:a", "copy", out]
        _say(args, "[信息] 硬烧录字幕（视频重编码 H.264）…")
    else:
        import subtitle_compose_core  # noqa: PLC0415 —— 纯函数，无 Qt
        argv, err = subtitle_compose_core.build_command(ffmpeg_path, video, sub, out)
        if err:
            return _fail(args, err)
        _say(args, "[信息] 软字幕封装（音视频 copy，不重编码）…")
    proc = subprocess.run(argv, capture_output=True,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if proc.returncode != 0 or not os.path.isfile(out):
        tail = proc.stderr.decode("utf-8", "replace").strip().splitlines()[-6:]
        return _fail(args, "ffmpeg 退出码 %s：\n%s"
                     % (proc.returncode, "\n".join(tail)))
    return _emit(args, {"ok": True, "video": video, "subtitle": sub,
                        "output": out, "mode": args.mode})


def setup_compose(sub) -> None:
    s = sub.add_parser("compose", parents=[common],
                       help="字幕合成：软封装（copy）/ 硬烧录 / 带独立音轨合并")
    s.add_argument("video", help="视频文件")
    s.add_argument("sub", help="字幕文件（.srt/.ass）")
    s.add_argument("--audio", default="", help="独立音轨（.m4a/.weba，如下载产物分离音轨；可选）")
    s.add_argument("--mode", default="soft", choices=["soft", "burn", "mkv"],
                   help="soft=软封装不重编码（默认）；burn=硬烧录（ASS，重编码）；mkv=封装进 MKV")
    s.add_argument("--out", default="", help="输出文件（默认 data\\agent_out\\<时间戳>\\<名>.composed.mp4）")
    s.set_defaults(fn=cmd_compose)