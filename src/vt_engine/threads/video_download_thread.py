# @version 2.5.1
"""视频下载线程（自研最小实现，替代 videocaptioner.ui.thread.video_download_thread）。

契约：``finished(str)`` / ``progress(int, str)`` / ``error(str)``，
``__init__(url, work_dir)``，``download(need_subtitle=True,
need_thumbnail=False)``。

实现选择：走**随包 yt-dlp 二进制子进程**（项目自有下载链在
``core/download`` 域，那边的是完整版——cookie 预检、竞速、HLS 兜底等；
引擎工作台只需要「粘个链接下载下来」这一步，且不引入 yt-dlp Python
包的 import 期依赖）。进度解析 ``[download]  xx.x%`` 行。
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThread, Signal

from vt_engine.log import setup_logger

logger = setup_logger("vt_engine.video_download_thread")

__all__ = ["VideoDownloadThread"]

_PROGRESS_RE = re.compile(r"\[download\]\s+([\d.]+)%")


class VideoDownloadThread(QThread):
    """URL → 本地视频（yt-dlp 子进程）。"""

    finished = Signal(str)
    progress = Signal(int, str)
    error = Signal(str)

    def __init__(self, url: str, work_dir: str):
        super().__init__()
        self.url = url
        self.work_dir = work_dir
        self._proc = None

    @staticmethod
    def sanitize_filename(name: str, replacement: str = "_") -> str:
        return re.sub(r'[\\/:*?"<>|]', replacement, name or "").strip()

    def progress_hook(self, line: str):
        m = _PROGRESS_RE.search(line or "")
        if m:
            try:
                pct = min(100, int(float(m.group(1))))
            except ValueError:
                return
            self.progress.emit(pct, "%d%% 下载中" % pct)

    def _find_ytdlp() -> Optional[str]:
        from vt_engine.media import _tools_dir
        import shutil
        import os
        for key in ("VT_YTDLP",):
            v = (os.environ.get(key) or "").strip().strip('"')
            if v and os.path.isfile(v):
                return v
        cand = os.path.join(_tools_dir(), "yt-dlp.exe")
        if os.path.isfile(cand):
            return cand
        return shutil.which("yt-dlp")

    def run(self):
        try:
            path = self.download()
            self.finished.emit(path)
        except Exception as e:  # noqa: BLE001
            logger.exception("下载失败: %s", e)
            self.error.emit(str(e))

    def download(self, need_subtitle: bool = True,
                 need_thumbnail: bool = False) -> str:
        """下载并返回视频文件路径。"""
        ytdlp = self._find_ytdlp()
        if not ytdlp:
            raise RuntimeError("未找到 yt-dlp（tools/yt-dlp.exe）")
        work = Path(self.work_dir)
        work.mkdir(parents=True, exist_ok=True)

        args = [ytdlp, "--newline", "--no-playlist",
                "-P", str(work),
                "-o", "%(title)s.%(ext)s"]
        if need_subtitle:
            args += ["--write-subs", "--write-auto-subs",
                     "--sub-langs", "all",
                     "--convert-subs", "srt"]
        if need_thumbnail:
            args += ["--write-thumbnail"]
        args.append(self.url)

        logger.info("开始下载视频: %s", self.url)
        self._proc = subprocess.Popen(
            args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            if __import__("os").name == "nt" else 0)
        assert self._proc.stdout is not None
        for line in self._proc.stdout:
            self.progress_hook(line.rstrip())
        rc = self._proc.wait()
        if rc != 0:
            raise RuntimeError("yt-dlp 退出码 %s" % rc)

        # 找最新落地的媒体文件
        candidates = [p for p in work.iterdir()
                      if p.suffix.lower() in
                      (".mp4", ".mkv", ".webm", ".mov", ".flv", ".ts",
                       ".m4v", ".avi")]
        if not candidates:
            raise RuntimeError("下载完成但未找到媒体文件: %s" % work)
        newest = max(candidates, key=lambda p: p.stat().st_mtime)
        self.progress.emit(100, "下载完成")
        return str(newest)

    def stop(self):
        p = getattr(self, "_proc", None)
        if p and p.poll() is None:
            try:
                p.kill()
            except Exception:  # noqa: BLE001
                pass
