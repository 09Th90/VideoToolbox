# -*- coding: utf-8 -*-
# @version 3.1.6
"""download 命令编排（原 features/download/cli.py job/legacy 双路径，行为不变）。"""
from __future__ import annotations

import json
import os
import re
import subprocess

from features._api.errors import fail
from features._api.runtime import _engine, _to_float


def _download_job(params: dict, log) -> dict:
    """P1：统一 job 层；旧 legacy 保留。"""
    engine = _engine()
    from core.download.job import (
        DownloadJob, JobHooks, StreamingRunner,
        download_orchestrator, run_download_job,
    )
    ytdlp = engine.ensure_ytdlp()
    ffmpeg_path, _ = engine.ensure_ffmpeg()
    url = params.get("url", "")
    log("[1/3] 提取视频信息 …")
    try:
        raw = engine.fetch_info_json(ytdlp, url, log=lambda m: log(str(m)))
    except Exception as e:  # noqa: BLE001
        return fail("提取视频信息失败：%s" % e)
    if not raw:
        return fail("提取视频信息失败（网络/风控），详见上方日志")
    try:
        meta = json.loads(raw)
    except ValueError:
        meta = {}
    title = (meta.get("title") or "video").strip()
    duration = _to_float(meta.get("duration"))
    out_dir = os.path.abspath(params["dir"]) if params.get("dir") else os.path.join(
        engine.DATA_DIR, "downloads", "agent",
        re.sub(r'[\\/:*?"<>|]+', "_", title)[:80] or "video")
    os.makedirs(out_dir, exist_ok=True)

    def say_line(line):
        log(str(line))

    def extract(_ytdlp, _url):
        return engine.fetch_info_json(_ytdlp, _url, log=lambda m: log(str(m)))

    hooks = JobHooks(
        run=StreamingRunner(say_line),
        log=lambda m, lv="dim": log(str(m)),
        extract=extract,
        detect_language=engine.ai_detect_language,
        make_cover=lambda ff, folder: engine.make_cover_1280x720(ff, folder),
        write_info=engine.write_info_txt,
        normalize_srt=engine.normalize_rolling_srt,
    )
    spec = DownloadJob(
        url=url, folder=out_dir, meta=meta, raw_info=raw,
        max_height=int(params.get("height", 0) or 0),
        with_subs=bool(params.get("subs", False)),
        lock_proxy=True,
    )
    log("[2/3] 开始下载：%s" % title)
    result = run_download_job(spec, hooks)
    if not result.ok:
        return fail(result.error or "视频下载失败",
                    title=result.title or title, dir=result.folder or out_dir)
    files = [os.path.join(out_dir, n) for n in sorted(os.listdir(out_dir))
             if os.path.isfile(os.path.join(out_dir, n))]
    videos = [f for f in files if f.lower().endswith((".mp4", ".mkv", ".webm"))]
    log("[3/3] 下载完成")
    return {"ok": True, "title": result.title or title,
            "duration_sec": duration, "dir": result.folder or out_dir,
            "video": result.video or (videos[0] if videos else ""),
            "n_files": len(files)}


def run(params: dict, log) -> dict:
    from core.download.job import download_orchestrator
    if download_orchestrator(default="job") == "job":
        return _download_job(params, log)
    engine = _engine()
    ytdlp = engine.ensure_ytdlp()
    ffmpeg_path, _ = engine.ensure_ffmpeg()
    url = params.get("url", "")
    log("[1/3] 提取视频信息 …")
    try:
        raw = engine.fetch_info_json(ytdlp, url, log=lambda m: log(str(m)))
    except Exception as e:  # noqa: BLE001
        return fail("提取视频信息失败：%s" % e)
    if not raw:
        return fail("提取视频信息失败（网络/风控），详见上方日志")
    try:
        meta = json.loads(raw)
    except ValueError:
        meta = {}
    title = (meta.get("title") or "video").strip()
    duration = _to_float(meta.get("duration"))

    out_dir = os.path.abspath(params["dir"]) if params.get("dir") else os.path.join(
        engine.DATA_DIR, "downloads", "agent",
        re.sub(r'[\\/:*?"<>|]+', "_", title)[:80] or "video")
    os.makedirs(out_dir, exist_ok=True)

    proxy_args = engine.ytdlp_proxy_args()
    if proxy_args:
        log("[信息] 下载经代理 %s" % proxy_args[1])
    cookie_args = engine.ytdlp_cookie_args(log=lambda m: log(str(m)))
    height = ("[height<=%d]" % params["height"]) if params.get("height") else ""
    argv = [ytdlp, "-f", f"bv*{height}+ba/b",
            "--merge-output-format", "mp4",
            "--ffmpeg-location", os.path.dirname(ffmpeg_path),
            "--newline", "--no-playlist",
            # 与下载页/流水线共用同一份提速+抗断流参数（--concurrent-fragments 5、
            # --socket-timeout/--retries/--fragment-retries/--retry-sleep）。
            # ⚠ 用函数而非常量：A3-1 拆分已把 YTDLP_DL_COMMON_ARGS 改为
            #   ytdlp_dl_args()，旧名不存在（引旧名必 AttributeError）。
            *engine.ytdlp_dl_args(),
            "-o", engine.output_template(out_dir),
            *cookie_args, *proxy_args, url]
    log("[2/3] 开始下载：%s" % title)
    proc = subprocess.run(argv)
    if proc.returncode != 0:
        return fail("yt-dlp 退出码 %d" % proc.returncode, title=title, dir=out_dir)
    files = [os.path.join(out_dir, n) for n in sorted(os.listdir(out_dir))
             if os.path.isfile(os.path.join(out_dir, n))]
    videos = [f for f in files if f.lower().endswith((".mp4", ".mkv", ".webm"))]
    log("[3/3] 下载完成")
    return {"ok": True, "title": title,
            "duration_sec": duration, "dir": out_dir,
            "video": videos[0] if videos else "",
            "n_files": len(files)}