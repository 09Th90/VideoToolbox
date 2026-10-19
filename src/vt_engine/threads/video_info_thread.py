# @version 2.4.0
"""视频信息线程（自研，替代 videocaptioner.ui.thread.video_info_thread）。"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from vt_engine.entities import VideoInfo
from vt_engine.media import probe_video_info

__all__ = ["VideoInfoThread"]


def _thumbnail_path(file_path) -> str:
    """按**完整路径**派生缩略图文件名，避免同名文件串味。

    ⚠ 旧实现用 ``Path(file_path).stem`` 命名（``第01集_thumbnail.jpg``）：
    不同目录/不同扩展名（mp4 与 mkv）的同名文件会落到同一个缓存文件，
    B 探测时 ``probe_video_info`` 写入后 A 再读就会显示**另一部片的画面**
    （缩略图是上次留下的，且从不清理）。这里加路径哈希前缀固定隔离，
    且保留可读 stem 便于人工排查。
    """
    src = str(file_path)
    stem = Path(src).stem or "video"
    # 只保留安全字符，避免文件名里的非法字符/超长 stem 污染路径
    safe = "".join(c for c in stem if c.isalnum() or c in "-_()（）")[:40] or "video"
    digest = hashlib.sha1(
        os.path.normcase(os.path.abspath(src)).encode("utf-8", "replace")
    ).hexdigest()[:12]
    return os.path.join(tempfile.gettempdir(),
                        "%s_%s_thumbnail.jpg" % (digest, safe))


class VideoInfoThread(QThread):
    """探测媒体信息（含缩略图提取）。"""

    finished = Signal(VideoInfo)
    error = Signal(str)

    def __init__(self, file_path):
        super().__init__()
        self.file_path = file_path

    def run(self):
        thumbnail_path = _thumbnail_path(self.file_path)
        try:
            video_info = probe_video_info(self.file_path,
                                          thumbnail_path=thumbnail_path)
            if video_info:
                self.finished.emit(video_info)
            else:
                self.error.emit("无法获取媒体文件信息，请确保文件格式正确")
        except Exception as e:  # noqa: BLE001
            self.error.emit(str(e))

