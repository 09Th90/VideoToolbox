# -*- coding: utf-8 -*-
# @version 3.0.0
"""download 子命令（原 agent_cli.cmd_download / _cmd_download_job，行为不变）。"""
from __future__ import annotations

import json
import os
import re
import subprocess

from features._cli import _emit, _engine, _fail, _say, _to_float, common


def _cmd_download_job(args) -> int:
    """P1：统一 job 层；旧 cmd_download 保留为 legacy。"""
    engine = _engine()
    from core.download.job import (
        DownloadJob, JobHooks, StreamingRunner,
        download_orchestrator, run_download_job,
    )
    ytdlp = engine.ensure_ytdlp()
    ffmpeg_path, _ = engine.ensure_ffmpeg()
    url = args.url
    _say(args, "[1/3] 提取视频信息 …")
    try:
        raw = engine.fetch_info_json(ytdlp, url, log=lambda m: _say(args, str(m)))
    except Exception as e:  # noqa: BLE001
        return _fail(args, "提取视频信息失败：%s" % e)
    if not raw:
        return _fail(args, "提取视频信息失败（网络/风控），详见上方日志")
    try:
        meta = json.loads(raw)
    except ValueError:
        meta = {}
    title = (meta.get("title") or "video").strip()
    duration = _to_float(meta.get("duration"))
    out_dir = os.path.abspath(args.dir) if args.dir else os.path.join(
        engine.DATA_DIR, "downloads", "agent",
        re.sub(r'[\\/:*?"<>|]+', "_", title)[:80] or "video")
    os.makedirs(out_dir, exist_ok=True)

    def say_line(line):
        _say(args, str(line))

    def extract(_ytdlp, _url):
        return engine.fetch_info_json(
            _ytdlp, _url, log=lambda m: _say(args, str(m)))

    hooks = JobHooks(
        run=StreamingRunner(say_line),
        log=lambda m, lv="dim": _say(args, str(m)),
        extract=extract,
        detect_language=engine.ai_detect_language,
        make_cover=lambda ff, folder: engine.make_cover_1280x720(ff, folder),
        write_info=engine.write_info_txt,
        normalize_srt=engine.normalize_rolling_srt,
    )
    spec = DownloadJob(
        url=url, folder=out_dir, meta=meta, raw_info=raw,
        max_height=int(getattr(args, "height", 0) or 0),
        with_subs=bool(getattr(args, "subs", False)),
        lock_proxy=True,
    )
    _say(args, "[2/3] 开始下载：%s" % title)
    result = run_download_job(spec, hooks)
    if not result.ok:
        return _fail(args, result.error or "视频下载失败",
                     title=result.title or title, dir=result.folder or out_dir)
    files = [os.path.join(out_dir, n) for n in sorted(os.listdir(out_dir))
             if os.path.isfile(os.path.join(out_dir, n))]
    videos = [f for f in files if f.lower().endswith((".mp4", ".mkv", ".webm"))]
    _say(args, "[3/3] 下载完成")
    return _emit(args, {"ok": True, "title": result.title or title,
                        "duration_sec": duration, "dir": result.folder or out_dir,
                        "video": result.video or (videos[0] if videos else ""),
                        "n_files": len(files)})


def cmd_download(args) -> int:
    from core.download.job import download_orchestrator
    if download_orchestrator(default="job") == "job":
        return _cmd_download_job(args)
    engine = _engine()
    ytdlp = engine.ensure_ytdlp()
    ffmpeg_path, _ = engine.ensure_ffmpeg()
    url = args.url
    _say(args, "[1/3] 提取视频信息 …")
    try:
        raw = engine.fetch_info_json(ytdlp, url, log=lambda m: _say(args, str(m)))
    except Exception as e:  # noqa: BLE001
        return _fail(args, "提取视频信息失败：%s" % e)
    if not raw:
        return _fail(args, "提取视频信息失败（网络/风控），详见上方日志")
    try:
        meta = json.loads(raw)
    except ValueError:
        meta = {}
    title = (meta.get("title") or "video").strip()
    duration = _to_float(meta.get("duration"))

    out_dir = os.path.abspath(args.dir) if args.dir else os.path.join(
        engine.DATA_DIR, "downloads", "agent",
        re.sub(r'[\\/:*?"<>|]+', "_", title)[:80] or "video")
    os.makedirs(out_dir, exist_ok=True)

    proxy_args = engine.ytdlp_proxy_args()
    if proxy_args:
        _say(args, "[信息] 下载经代理 %s" % proxy_args[1])
    cookie_args = engine.ytdlp_cookie_args(log=lambda m: _say(args, str(m)))
    height = ("[height<=%d]" % args.height) if args.height else ""
    argv = [ytdlp, "-f", f"bv*{height}+ba/b",
            "--merge-output-format", "mp4",
            "--ffmpeg-location", os.path.dirname(ffmpeg_path),
            "--newline", "--no-playlist",
            # 与下载页/流水线共用同一份提速+抗断流参数（--concurrent-fragments 5、
            # --socket-timeout/--retries/--fragment-retries/--retry-sleep）。
            # 此前 CLI 未采用 → 分片串行下载，实测长视频仅 ~300KB/s。
            # ⚠ 用函数而非常量：A3-1 拆分已把 YTDLP_DL_COMMON_ARGS 改为
            #   ytdlp_dl_args()，旧名不存在（引旧名必 AttributeError）。
            *engine.ytdlp_dl_args(),
            "-o", engine.output_template(out_dir),
            *cookie_args, *proxy_args, url]
    _say(args, "[2/3] 开始下载：%s" % title)
    proc = subprocess.run(argv)
    if proc.returncode != 0:
        return _fail(args, "yt-dlp 退出码 %d" % proc.returncode,
                     title=title, dir=out_dir)
    files = [os.path.join(out_dir, n) for n in sorted(os.listdir(out_dir))
             if os.path.isfile(os.path.join(out_dir, n))]
    videos = [f for f in files if f.lower().endswith((".mp4", ".mkv", ".webm"))]
    _say(args, "[3/3] 下载完成")
    return _emit(args, {"ok": True, "title": title,
                        "duration_sec": duration, "dir": out_dir,
                        "video": videos[0] if videos else "",
                        "n_files": len(files)})


def setup_download(sub) -> None:
    s = sub.add_parser("download", parents=[common],
                       help="下载视频（yt-dlp，自动代理+游客 cookie，合并 mp4）")
    s.add_argument("url", help="视频链接（YouTube/B站等 yt-dlp 支持的站点）")
    s.add_argument("--dir", default="", help="输出目录（默认 data\\downloads\\agent\\<标题>\\）")
    s.add_argument("--height", type=int, default=0,
                   help="限制最大分辨率高度（如 1080；0=不限制）")
    s.add_argument("--subs", action="store_true",
                   help="同时下载字幕（job 编排模式下生效）")
    s.set_defaults(fn=cmd_download)