# -*- coding: utf-8 -*-
# @version 2.3.0
"""自研信号总线（UI 层内部广播）。

等价于引擎 ``ui.common.signal_bus.signalBus``，但完全自研、零后端依赖：只有
Qt 信号定义，UI 各页用它做跨页联动（字幕排布 / 翻译开关 / 目标语言 / 转录
模型 / 视频播放片段 等）。信号名与语义与既有 UI 保持一致，保证各页联动行为
不变。
"""
from PySide6.QtCore import QObject, QUrl, Signal


class SignalBus(QObject):
    # 字幕排布
    subtitle_layout_changed = Signal(str)
    # 字幕优化 / 翻译开关
    subtitle_optimization_changed = Signal(bool)
    subtitle_translation_changed = Signal(bool)
    # 翻译语言
    target_language_changed = Signal(str)
    # 转录模型
    transcription_model_changed = Signal(str)
    # 合成相关
    soft_subtitle_changed = Signal(bool)
    need_video_changed = Signal(bool)
    video_quality_changed = Signal(str)
    use_subtitle_style_changed = Signal(bool)
    subtitle_render_mode_changed = Signal(str)

    # 视频控制
    video_play = Signal()
    video_pause = Signal()
    video_stop = Signal()
    video_source_changed = Signal(QUrl)
    video_segment_play = Signal(int, int)
    video_subtitle_added = Signal(str)

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
