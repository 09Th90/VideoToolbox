# -*- coding: utf-8 -*-
"""自研信号总线（UI 层内部广播）。

等价于引擎 ``ui.common.signal_bus.signalBus``，但完全自研、零后端依赖：只有
Qt 信号定义，UI 各页用它做跨页联动（字幕排布 / 翻译开关 / 目标语言 / 转录
模型 / 视频播放片段 等）。信号名与语义与既有 UI 保持一致，保证各页联动行为
不变。
"""
from PyQt5.QtCore import QObject, QUrl, pyqtSignal


class SignalBus(QObject):
    # 字幕排布
    subtitle_layout_changed = pyqtSignal(str)
    # 字幕优化 / 翻译开关
    subtitle_optimization_changed = pyqtSignal(bool)
    subtitle_translation_changed = pyqtSignal(bool)
    # 翻译语言
    target_language_changed = pyqtSignal(str)
    # 转录模型
    transcription_model_changed = pyqtSignal(str)
    # 合成相关
    soft_subtitle_changed = pyqtSignal(bool)
    need_video_changed = pyqtSignal(bool)
    video_quality_changed = pyqtSignal(str)
    use_subtitle_style_changed = pyqtSignal(bool)
    subtitle_render_mode_changed = pyqtSignal(str)

    # 视频控制
    video_play = pyqtSignal()
    video_pause = pyqtSignal()
    video_stop = pyqtSignal()
    video_source_changed = pyqtSignal(QUrl)
    video_segment_play = pyqtSignal(int, int)
    video_subtitle_added = pyqtSignal(str)

    def play_video(self):
        self.video_play.emit()

    def pause_video(self):
        self.video_pause.emit()

    def stop_video(self):
        self.video_stop.emit()

    def set_video_source(self, url: QUrl):
        self.video_source_changed.emit(url)

    def play_video_segment(self, start_time: int, end_time: int):
        self.video_segment_play.emit(start_time, end_time)

    def add_subtitle(self, subtitle_file: str):
        self.video_subtitle_added.emit(subtitle_file)


signalBus = SignalBus()
