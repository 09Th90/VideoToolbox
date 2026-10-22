# @version 2.5.4
"""转录线程（自研，替代 videocaptioner.ui.thread.transcript_thread）。"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from vt_engine.entities import TranscribeTask
from vt_engine.log import setup_logger
from vt_engine.pipeline import transcribe_media

logger = setup_logger("vt_engine.transcript_thread")

__all__ = ["TranscriptThread"]


class TranscriptThread(QThread):
    """转录任务线程（执行体为 ``vt_engine.pipeline.transcribe_media``）。"""

    finished = Signal(TranscribeTask)
    progress = Signal(int, str)
    error = Signal(str)

    def __init__(self, task: TranscribeTask):
        super().__init__()
        self.task = task

    def run(self):
        try:
            transcribe_media(self.task, callback=self.progress.emit)
            self.finished.emit(self.task)
        except Exception as e:  # noqa: BLE001
            logger.exception("转录失败: %s", e)
            self.error.emit(str(e))
            self.progress.emit(100, "转录失败")
