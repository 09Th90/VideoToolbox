# -*- coding: utf-8 -*-
# @version 2.5.1
"""「字幕视频合成」页的**占位实现**。

在视频工具箱里，合成功能已并入自研「字幕编辑」页；宿主 ``_build_engine`` 会：
断开「字幕翻译完成 → 自动跳合成」的连线、把 ``switch_to_video_synthesis`` 置为
no-op、从分段控件与堆叠页摘掉本页并 ``hide()``。但 ``HomeInterface.closeEvent``
仍会调用它的 ``close()``，故实例必须存在、可构造、可隐藏、可关闭。

因此这里给出一个**永不显示**的最小占位控件（保持信号/方法契约），不含任何可见
控件——它对最终 GUI 无贡献（始终 hidden 且已从堆叠页移除）。P2/P4 若要在本工作
台内恢复合成，再替换为完整实现。
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget


class VideoSynthesisInterface(QWidget):
    finished = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("VideoSynthesisInterface")
        self.task = None

    def set_task(self, task) -> None:
        self.task = task

    def process(self) -> None:
        # 合成已并入「字幕编辑」页；此处不应被触达（宿主已断开自动跳转）。
        return
