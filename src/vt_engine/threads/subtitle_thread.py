# @version 2.5.2
"""字幕线程（自研，替代 videocaptioner.ui.thread.subtitle_thread 的两个线程）。

信号契约与引擎逐一对应；执行体是 ``vt_engine.pipeline.process_subtitle``
（SubtitleThread）与 ``vt_engine.translate_factory``（RetranslateThread，
重译选中行）。停止语义对齐引擎 v1.11.0 修复：**先关优化器/翻译器线程池
再 terminate**——否则取消后线程池仍把剩余批次跑完（Rate Limit 之源）。
"""

from __future__ import annotations

from typing import List

from PySide6.QtCore import QThread, Signal

from vt_engine.asr_data import ASRData
from vt_engine.entities import SubtitleConfig, SubtitleProcessData, SubtitleTask
from vt_engine.llm_context import (
    clear_task_context,
    generate_task_id,
    set_task_context,
)
from vt_engine.log import setup_logger
from vt_engine.pipeline import process_subtitle
from vt_engine.translate_factory import translate_with_machine_fallback

logger = setup_logger("vt_engine.subtitle_thread")

__all__ = ["SubtitleThread", "RetranslateThread"]


class SubtitleThread(QThread):
    """字幕任务线程（断句/优化/翻译/保存）。"""

    finished = Signal(str, str)     # (video_path, output_path)
    progress = Signal(int, str)
    update = Signal(dict)           # {行号: 译文}（分块进度）
    update_all = Signal(dict)       # 全量数据快照
    error = Signal(str)

    def __init__(self, task: SubtitleTask):
        super().__init__()
        self.task = task
        self.translator = None
        self.subtitle_length = 0
        self.finished_subtitle_length = 0

    def set_custom_prompt_text(self, text: str):
        if self.task.subtitle_config:
            self.task.subtitle_config.custom_prompt_text = text

    # ---- 回调：进度 + update ----
    def _on_chunk(self, result: List[SubtitleProcessData]):
        self.finished_subtitle_length += len(result)
        pct = min(int(self.finished_subtitle_length /
                      max(self.subtitle_length, 1) * 100), 100)
        self.progress.emit(pct, "%d%% 处理字幕" % pct)
        result_dict = {
            str(d.index): d.translated_text or d.optimized_text
            or d.original_text for d in result}
        self.update.emit(result_dict)

    def _on_data(self, asr_data):
        self.subtitle_length = len(asr_data.segments)
        self.update_all.emit(asr_data.to_json())

    def run(self):
        try:
            process_subtitle(self.task, callback=self.progress.emit,
                             on_data=self._on_data)
            self.finished.emit(self.task.video_path or "",
                               self.task.output_path or "")
        except Exception as e:  # noqa: BLE001
            logger.exception("字幕处理失败: %s", e)
            self.error.emit(str(e))
            self.progress.emit(100, "字幕处理失败")

    def stop(self):
        """停止：先关翻译器线程池，再 terminate（引擎 v1.11.0 教训）。"""
        t = getattr(self, "translator", None)
        if t:
            try:
                t.stop()
            except Exception as e:  # noqa: BLE001
                logger.error("停止翻译器时出错：%s", e)
        try:
            self.terminate()
            if not self.wait(3000):
                logger.warning("线程未能在3秒内正常停止")
            self.progress.emit(100, "已终止")
        except Exception as e:  # noqa: BLE001
            logger.error("停止线程时出错: %s", e)
            self.progress.emit(100, "终止时发生错误")


class RetranslateThread(QThread):
    """重译选中行的轻量线程。"""

    finished = Signal(dict)          # {原始行号: translated_text}
    progress = Signal(int, str)
    error = Signal(str)

    def __init__(self, selected_data: dict,
                 subtitle_config: SubtitleConfig, file_name: str = ""):
        """
        selected_data: 选中条目（键为行号字符串，值为字幕数据）
        subtitle_config: 当前字幕配置
        file_name: 日志上下文用文件名
        """
        super().__init__()
        self.selected_data = selected_data
        self.subtitle_config = subtitle_config
        self.file_name = file_name
        self.total = max(1, len(selected_data))
        self.done = 0
        self.translator = None

    def stop(self):
        t = getattr(self, "translator", None)
        if t:
            try:
                t.stop()
            except Exception as e:  # noqa: BLE001
                logger.error("停止重译线程时出错: %s", e)

    def _callback(self, result: List[SubtitleProcessData]):
        self.done += len(result)
        pct = min(int(self.done / self.total * 100), 100)
        self.progress.emit(pct, "%d%% 翻译中" % pct)

    def run(self):
        set_task_context(task_id=generate_task_id(),
                         file_name=self.file_name, stage="translate")
        try:
            config = self.subtitle_config
            if not config.target_language:
                raise RuntimeError("目标语言未配置")
            asr_data = ASRData.from_json(self.selected_data)
            asr_data = translate_with_machine_fallback(
                config, "", self._callback, asr_data,
                on_translator=lambda t: setattr(self, "translator", t))
            # 与 ASRData.from_json 的按键 int 排序对齐：selected_data 的
            # 键顺序（表格选中序）不保证有序，直接 list() 会让译文错位
            # （2026-10-19 自查修复）。
            keys = sorted(self.selected_data.keys(), key=int)
            result = {keys[i]: seg.translated_text
                      for i, seg in enumerate(asr_data.segments)}
            self.finished.emit(result)
        except Exception as e:  # noqa: BLE001
            logger.exception("重新翻译失败: %s", e)
            self.error.emit(str(e))
        finally:
            clear_task_context()
