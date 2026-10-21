# -*- coding: utf-8 -*-
# @version 2.5.0
"""自研「字幕设置」弹窗 + 数值输入设置卡（对齐引擎同名组件）。

由「字幕翻译」页命令栏的设置按钮打开。仅依赖 qfluentwidgets（保留组件）与
后端接缝的配置项，无引擎 UI 依赖。
"""
from __future__ import annotations

from typing import Optional, Union

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon
from vt_fluent import (
    BodyLabel,
    CompactSpinBox,
    MessageBoxBase,
    SettingCard,
    SwitchSettingCard,
)
from vt_fluent import FluentIcon as FIF
from vt_fluent import ConfigItem, qconfig

from . import _seams


class SpinBoxSettingCard(SettingCard):
    valueChanged = Signal(int)

    def __init__(self, configItem: ConfigItem, icon: Union[str, QIcon], title: str,
                 content: Optional[str] = None, minimum: int = 0, maximum: int = 100,
                 parent=None):
        super().__init__(icon, title, content, parent)
        self.configItem = configItem
        self.spinBox = CompactSpinBox(self)
        self.spinBox.setRange(minimum, maximum)
        self.spinBox.setMinimumWidth(60)
        self.hBoxLayout.addWidget(self.spinBox, 0, Qt.AlignRight)
        self.hBoxLayout.addSpacing(8)
        self.setValue(qconfig.get(configItem))
        self.spinBox.valueChanged.connect(self.__onValueChanged)
        configItem.valueChanged.connect(self.setValue)

    def __onValueChanged(self, value: int):
        self.setValue(value)
        self.valueChanged.emit(value)

    def setValue(self, value: int):
        qconfig.set(self.configItem, value)
        self.spinBox.setValue(value)


class SubtitleSettingDialog(MessageBoxBase):
    def __init__(self, parent=None):
        super().__init__(parent)
        cfg = _seams.cfg
        self.titleLabel = BodyLabel(self.tr("字幕设置"), self)

        self.split_card = SwitchSettingCard(
            FIF.ALIGNMENT, self.tr("字幕分割"),
            self.tr("字幕是否使用大语言模型进行智能断句"), cfg.need_split, self)

        self.word_count_cjk_card = SpinBoxSettingCard(
            cfg.max_word_count_cjk, FIF.TILES, self.tr("中文最大字数"),
            self.tr("单条字幕的最大字数 (对于中日韩等字符)"),
            minimum=8, maximum=50, parent=self)

        self.word_count_english_card = SpinBoxSettingCard(
            cfg.max_word_count_english, FIF.TILES, self.tr("英文最大单词数"),
            self.tr("单条字幕的最大单词数 (英文)"),
            minimum=8, maximum=50, parent=self)

        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.split_card)
        self.viewLayout.addWidget(self.word_count_cjk_card)
        self.viewLayout.addWidget(self.word_count_english_card)
        self.viewLayout.setSpacing(10)

        self.setWindowTitle(self.tr("字幕设置"))
        self.widget.setMinimumWidth(380)
        self.yesButton.hide()
        self.cancelButton.setText(self.tr("关闭"))
