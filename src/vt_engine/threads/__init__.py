# @version 2.5.3
"""Qt 线程层（自研，替代 videocaptioner.ui.thread.* 五个线程）。

信号契约与引擎线程逐一对应（``vt_engine_ui`` 各页按名访问）：

* :class:`TranscriptThread` —— ``finished(TranscribeTask)`` /
  ``progress(int, str)`` / ``error(str)``；
* :class:`VideoInfoThread` —— ``finished(VideoInfo)`` / ``error(str)``；
* :class:`SubtitleThread` —— ``finished(str, str)`` / ``progress`` /
  ``update(dict)`` / ``update_all(dict)`` / ``error(str)``；
* :class:`RetranslateThread` —— ``finished(dict)`` / ``progress`` /
  ``error(str)``；
* :class:`VideoDownloadThread` —— ``finished(str)`` / ``progress`` /
  ``error(str)``。

全部为 ``vt_engine.pipeline``（无 Qt 执行体）的薄封装；本层**不接入
主程序**——未来切换只改 ``vt_engine_ui/_seams.py`` 的取值来源。
"""

from __future__ import annotations

from vt_engine.threads.transcript_thread import TranscriptThread
from vt_engine.threads.video_info_thread import VideoInfoThread
from vt_engine.threads.subtitle_thread import (
    RetranslateThread,
    SubtitleThread,
)
from vt_engine.threads.video_download_thread import VideoDownloadThread

__all__ = [
    "TranscriptThread",
    "VideoInfoThread",
    "SubtitleThread",
    "RetranslateThread",
    "VideoDownloadThread",
]
