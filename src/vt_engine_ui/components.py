# -*- coding: utf-8 -*-
# @version 2.1.0
"""自研 UI 组件（设置卡片 / 转录设置卡与弹窗）。

包含：
  · ``LineEditSettingCard``      —— 行输入设置卡（对齐引擎同名组件）
  · ``EditComboBoxSettingCard``  —— 可编辑下拉设置卡（对齐引擎同名组件）
  · ``TranscriptionSettingCard`` —— 转录设置卡；下拉收敛为「默认/ASR」后，引擎
    自带的 WhisperCpp / WhisperAPI / FasterWhisper 三块配置**永不可达**（补丁 ③
    的既定语义），故本卡只构建 ``empty_widget``，并把补丁 ④ 的提示语 + 声纹录入
    卡内建其中；``whisper_*_widget`` / ``faster_whisper_widget`` 保留为 None 以
    兼容任何遗留属性访问。
  · ``TranscriptionSettingDialog`` —— 转录设置弹窗，内建补丁 ⑦ 的「主播声纹」
    多选器。
"""
from __future__ import annotations

from typing import List, Optional, Union

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QCompleter, QStackedWidget, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    ComboBoxSettingCard,
    EditableComboBox,
    LineEdit,
    MessageBoxBase,
    SettingCard,
)
from qfluentwidgets import FluentIcon as FIF
from qfluentwidgets.common.config import ConfigItem, qconfig

from . import _seams


# --------------------------------------------------------------------------
# 行输入设置卡
# --------------------------------------------------------------------------
class LineEditSettingCard(SettingCard):
    textChanged = Signal(str)

    def __init__(self, configItem: ConfigItem, icon, title: str,
                 content: Optional[str] = None, placeholder: str = "", parent=None):
        super().__init__(icon, title, content, parent)
        self.configItem = configItem
        self.lineEdit = LineEdit(self)
        self.lineEdit.setPlaceholderText(placeholder)
        self.hBoxLayout.addWidget(self.lineEdit, 1, Qt.AlignRight)
        self.hBoxLayout.addSpacing(16)
        self.lineEdit.setMinimumWidth(280)
        self.setValue(qconfig.get(configItem))
        self.lineEdit.textChanged.connect(self.__onTextChanged)
        configItem.valueChanged.connect(self.setValue)

    def __onTextChanged(self, text: str):
        self.setValue(text)
        self.textChanged.emit(text)

    def setValue(self, value: str):
        qconfig.set(self.configItem, value)
        self.lineEdit.setText(value)


# --------------------------------------------------------------------------
# 可编辑下拉设置卡
# --------------------------------------------------------------------------
class EditComboBoxSettingCard(SettingCard):
    currentTextChanged = Signal(str)

    def __init__(self, configItem: ConfigItem, icon: Union[str, QIcon], title: str,
                 content: Optional[str] = None, items: Optional[List[str]] = None,
                 parent=None):
        super().__init__(icon, title, content, parent)
        self.configItem = configItem
        self.items = items or []
        self.comboBox = EditableComboBox(self)
        for item in self.items:
            self.comboBox.addItem(item)
        self._setupCompleter()
        self.hBoxLayout.addWidget(self.comboBox, 1, Qt.AlignRight)
        self.hBoxLayout.addSpacing(16)
        self.comboBox.setMinimumWidth(280)
        self.setValue(qconfig.get(configItem))
        self.comboBox.currentTextChanged.connect(self.__onTextChanged)
        configItem.valueChanged.connect(self.setValue)

    def _setupCompleter(self):
        if not self.items:
            return
        completer = QCompleter(self.items, self)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains)
        self.comboBox.setCompleter(completer)

    def __onTextChanged(self, text: str):
        self.setValue(text)
        self.currentTextChanged.emit(text)

    def setValue(self, value: str):
        qconfig.set(self.configItem, value)
        self.comboBox.setText(value)

    def addItems(self, items: List[str]):
        for item in items:
            self.comboBox.addItem(item)
        self.items.extend(items)
        self._setupCompleter()

    def setItems(self, items: List[str]):
        self.comboBox.clear()
        self.items = items
        for item in items:
            self.comboBox.addItem(item)
        self._setupCompleter()


# --------------------------------------------------------------------------
# 转录设置卡（下拉收敛后只保留 empty_widget + 声纹录入）
# --------------------------------------------------------------------------
class TranscriptionSettingCard(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        # 兼容遗留属性访问：三块引擎内置配置永不可达，置 None
        self.whisper_cpp_widget = None
        self.whisper_api_widget = None
        self.faster_whisper_widget = None
        self.setup_ui()

    def setup_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        self.stacked_widget = QStackedWidget(self)
        self.empty_widget = QWidget(self)
        self.stacked_widget.addWidget(self.empty_widget)
        self.main_layout.addWidget(self.stacked_widget)

        # 补丁 ④（内建）：空位放一行提示 + 声纹录入卡
        self._populate_empty_widget()

    def _populate_empty_widget(self):
        try:
            lay = QVBoxLayout(self.empty_widget)
            lay.setContentsMargins(24, 4, 24, 4)
            tip = BodyLabel(
                "默认：内置免费语音识别；ASR：使用设置页「ASR 语音识别」的模型"
                "（自有服务 / 本地模型），统一在全局设置中维护",
                self.empty_widget)
            tip.setStyleSheet("color: #8a8a8a;")
            tip.setWordWrap(True)
            lay.addWidget(tip)
            try:
                self.vt_voiceprint_card = _seams.VoiceprintEnrollCard(self.empty_widget)
                lay.addWidget(self.vt_voiceprint_card)
            except Exception as e:  # noqa: BLE001
                _seams.vc_log(f"声纹录入卡挂载失败：{e}")
            lay.addStretch(1)
        except Exception:  # noqa: BLE001
            pass

    def on_model_changed(self, value):
        # 下拉收敛为「默认/ASR」后，value 恒为显示名，永远落到 empty_widget
        self.stacked_widget.setCurrentWidget(self.empty_widget)


# --------------------------------------------------------------------------
# 转录设置弹窗（内建声纹多选）
# --------------------------------------------------------------------------
class TranscriptionSettingDialog(MessageBoxBase):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.titleLabel = BodyLabel(self.tr("转录设置"), self)

        ent = _seams.entities
        cfg = _seams.cfg
        self.output_format_card = ComboBoxSettingCard(
            cfg.transcribe_output_format,
            FIF.SAVE,
            self.tr("输出格式"),
            self.tr("选择转录字幕的输出格式"),
            texts=[fmt.value for fmt in ent.TranscribeOutputFormatEnum],
            parent=self,
        )

        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.output_format_card)
        self.viewLayout.setSpacing(10)

        # 补丁 ⑦（内建）：主播声纹多选
        try:
            self.vt_voiceprint_picker = _seams.VoiceprintPicker(self)
            self.viewLayout.addWidget(self.vt_voiceprint_picker)
        except Exception as e:  # noqa: BLE001
            _seams.vc_log(f"声纹多选器挂载失败：{e}")

        self.setWindowTitle(self.tr("转录设置"))
        self.widget.setMinimumWidth(380)
        self.yesButton.hide()
        self.cancelButton.setText(self.tr("关闭"))
