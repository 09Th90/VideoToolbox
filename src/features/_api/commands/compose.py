# -*- coding: utf-8 -*-
# @version 3.2.5
"""compose 命令编排（原 features/compose/cli.py cmd_compose，行为不变）。

soft 走 subtitle_compose_core（纯函数、无 Qt）；burn 拼 ffmpeg ASS 硬烧；
带独立音轨走引擎 merge_pair。
"""
from __future__ import annotations

import os
import subprocess

from features._api.errors import fail
from features._api.runtime import _agent_out_dir, _engine


def run(params: dict, log) -> dict:
    engine = _engine()
    ffmpeg_path, _ = engine.ensure_ffmpeg()
    video = os.path.abspath(params.get("video", ""))
    sub = os.path.abspath(params.get("sub", ""))
    for label, p in (("视频", video), ("字幕", sub)):
        if not os.path.isfile(p):
            return fail("%s文件不存在：%s" % (label, p))
    audio = os.path.abspath(params["audio"]) if params.get("audio") else ""
    if audio and not os.path.isfile(audio):
        return fail("音轨文件不存在：%s" % audio)
    mode = params.get("mode", "soft")
    ext = os.path.splitext(sub)[1].lower()
    out = os.path.abspath(params["out"]) if params.get("out") else os.path.join(
        _agent_out_dir(),
        os.path.splitext(os.path.basename(video))[0] + ".composed.mp4")
    if os.path.abspath(out) == video:
        return fail("输出文件不能就是原视频本身")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)

    # —— 带独立音轨（下载产物合并场景）→ 引擎 merge_pair ——
    if audio:
        atype = "m4a" if audio.lower().endswith(".m4a") else "weba"
        sub_type = "srt" if ext == ".srt" else "ass"
        log("[信息] 走引擎 merge_pair（%s 音轨 + %s 字幕，%s）"
            % (atype, sub_type, "硬烧" if (sub_type == "ass" and
                                           mode != "mkv") else "封装"))
        engine.merge_pair(video, audio, atype, sub, sub_type, out,
                          ffmpeg_path,
                          ass_mode="burn" if mode == "burn" else
                          ("mkv" if out.lower().endswith(".mkv") else "burn"))
        if not os.path.isfile(out):
            return fail("合成失败（merge_pair 未产出文件），详见上方输出")
        return {"ok": True, "video": video, "subtitle": sub,
                "audio": audio, "output": out, "mode": "merge"}

    # —— 无独立音轨：soft（封装软字幕，不重编码）/ burn（ASS 硬烧，重编码）——
    if mode == "burn":
        sub_clean = sub.replace("\\", "/").replace("'", "\\'")
        argv = [ffmpeg_path, "-y", "-nostdin", "-i", video,
                "-vf", "subtitles='%s'" % sub_clean,
                "-c:v", "libx264", "-crf", "18", "-preset", "fast",
                "-c:a", "copy", out]
        log("[信息] 硬烧录字幕（视频重编码 H.264）…")
    else:
        import features.compose.subtitle_compose_core as subtitle_compose_core  # noqa: PLC0415 —— 纯函数，无 Qt
        argv, err = subtitle_compose_core.build_command(ffmpeg_path, video, sub, out)
        if err:
            return fail(err)
        log("[信息] 软字幕封装（音视频 copy，不重编码）…")
    proc = subprocess.run(argv, capture_output=True,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if proc.returncode != 0 or not os.path.isfile(out):
        tail = proc.stderr.decode("utf-8", "replace").strip().splitlines()[-6:]
        return fail("ffmpeg 退出码 %s：\n%s" % (proc.returncode, "\n".join(tail)))
    return {"ok": True, "video": video, "subtitle": sub,
            "output": out, "mode": mode}