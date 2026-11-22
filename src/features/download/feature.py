# -*- coding: utf-8 -*-
# @version 3.2.0
"""download 功能清单。后端 core.download.job（v2.3.1 已拆好的域包）。"""
from features._registry import CliCommand, FeatureSpec, GuiSpec

FEATURE = FeatureSpec(
    id="download",
    title="视频下载",
    summary="yt-dlp 下载（自动代理+游客 cookie，job 编排，合并 mp4，残留清理）",
    backend="core.download.job",
    requires=("ytdlp", "ffmpeg", "network"),
    services={
        "run_download_job": "core.download.job:run_download_job",
        "download_orchestrator": "core.download.job:download_orchestrator",
        "build_page": "features.download.page:build_page",
    },
    cli=(CliCommand(
        name="download",
        help="下载视频（yt-dlp，自动代理+游客 cookie，合并 mp4）",
        setup="features.download.cli:setup_download"),),
    gui=GuiSpec(nav="视频处理", builder="features.download.page:build_page",
                position="top", order=20, object_name="DownloadPage",
                icon="DOWNLOAD", attr="download_page",
                messages=("detect_done", "sys_log", "dl_")),
    order=30,
)