# -*- coding: utf-8 -*-
# @version 2.6.0
"""自研「字幕翻译」页（含 ``SubtitleTableModel`` / ``PromptDialog``）。

视觉与引擎字幕页对齐；把补丁 ⑨ 的「按声纹筛选」按钮 + 筛选前表格回写内建为
显式逻辑。``command_bar`` 上仍保留引擎原生的 ``optimize_button``（QAction，
「字幕校正」）——宿主 ``_build_engine`` 会把它从命令栏摘掉（保持既有最终视觉），
故这里照常构建、由宿主整形，避免行为漂移。

对外契约（``command_bar`` / ``main_layout`` / ``subtitle_table`` / ``model`` /
``optimize_button`` / ``translate_button`` / ``layout_button`` /
``target_language_button`` / ``start_button`` / ``subtitle_path`` / ``task`` /
``finished`` / ``set_task`` / ``process`` / ``load_subtitle_file``）与引擎同名同义。
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QTime, QThread, Signal
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QKeyEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QVBoxLayout,
    QWidget,
)
from vt_fluent import (
    Action,
    BodyLabel,
    CommandBar,
    InfoBar,
    InfoBarPosition,
    MessageBoxBase,
    PrimaryPushButton,
    ProgressBar,
    PushButton,
    RoundMenu,
    TableView,
    TextEdit,
    TransparentDropDownPushButton,
)
from vt_fluent import FluentIcon as FIF

from . import _seams


class SubtitleTableModel(QAbstractTableModel):
    def __init__(self, data: Union[str, Dict[str, Any]] = ""):
        super().__init__()
        self._data: Dict[str, Any] = {}
        if isinstance(data, str):
            self.load_data(data)
        else:
            self._data = data

    def load_data(self, data: str):
        try:
            self._data = json.loads(data)
            self.layoutChanged.emit()
        except json.JSONDecodeError:
            pass

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid() or not self._data:
            return None
        row = index.row()
        col = index.column()
        segment = self._data.get(str(row + 1))
        if not segment:
            return None
        if role in (Qt.DisplayRole, Qt.EditRole):
            if col == 0:
                return QTime(0, 0).addMSecs(segment["start_time"]).toString("hh:mm:ss.zzz")[:-2]
            elif col == 1:
                return QTime(0, 0).addMSecs(segment["end_time"]).toString("hh:mm:ss.zzz")[:-2]
            elif col == 2:
                return segment["original_subtitle"]
            elif col == 3:
                return segment["translated_subtitle"]
        elif role == Qt.TextAlignmentRole:
            if col in [0, 1]:
                return Qt.AlignCenter
        return None

    def setData(self, index: QModelIndex, value: Any, role: int = Qt.EditRole) -> bool:
        if not index.isValid() or not self._data:
            return False
        if role == Qt.EditRole:
            row = index.row()
            col = index.column()
            segment = self._data.get(str(row + 1))
            if not segment:
                return False
            if col == 2:
                segment["original_subtitle"] = value
            elif col == 3:
                segment["translated_subtitle"] = value
            else:
                return False
            self.dataChanged.emit(index, index, [Qt.DisplayRole, Qt.EditRole])
            return True
        return False

    def headerData(self, section: int, orientation, role: int = Qt.DisplayRole) -> Any:
        if role == Qt.DisplayRole:
            if orientation == Qt.Horizontal:
                return [
                    self.tr("开始时间"),
                    self.tr("结束时间"),
                    self.tr("字幕内容"),
                    self.tr("翻译字幕") if _seams.cfg.need_translate.value else self.tr("优化字幕"),
                ][section]
            elif orientation == Qt.Vertical:
                return str(section + 1)
        elif role == Qt.TextAlignmentRole:
            return Qt.AlignCenter
        return None

    def rowCount(self, parent: Optional[QModelIndex] = None) -> int:
        return len(self._data)

    def columnCount(self, parent: Optional[QModelIndex] = None) -> int:
        return 4

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.NoItemFlags
        if index.column() in [2, 3]:
            return Qt.ItemIsEditable | Qt.ItemIsEnabled | Qt.ItemIsSelectable
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable

    def update_data(self, new_data: Dict[str, str]) -> None:
        updated_rows = set()
        for key, value in new_data.items():
            if key in self._data:
                self._data[key]["translated_subtitle"] = value
                row = list(self._data.keys()).index(key)
                updated_rows.add(row)
        if updated_rows:
            min_row = min(updated_rows)
            max_row = max(updated_rows)
            top_left = self.index(min_row, 2)
            bottom_right = self.index(max_row, 3)
            self.dataChanged.emit(top_left, bottom_right, [Qt.DisplayRole, Qt.EditRole])

    def update_all(self, data: Dict[str, Any]) -> None:
        self._data = data
        self.layoutChanged.emit()


class SubtitleInterface(QWidget):
    finished = Signal(str, str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.task = None
        self.subtitle_path: Optional[str] = None
        self.custom_prompt_text: str = _seams.cfg.custom_prompt_text.value
        self._vt_vp_worker = None
        # 优化/重译线程是否在跑（终态权威标记）。引擎 SubtitleThread 在
        # except 分支先 error.emit 再补发 progress(100)，stop() 也会补发
        # progress(100, "已终止")——没有这个标记，这些迟到进度会把错误态
        # （progress_bar.error() 的红色）覆盖成 100% 完成态。
        self._opt_active = False
        self.setAttribute(Qt.WA_DeleteOnClose)
        self._init_ui()
        self._setup_signals()
        self._update_prompt_button_style()
        self.set_values()
        # 补丁 ⑨（内建）：命令栏加「按声纹筛选」按钮
        self._add_voiceprint_button()

    def _add_voiceprint_button(self):
        try:
            btn = PushButton("按声纹筛选", self)
            btn.setToolTip("按已启用的主播声纹过滤当前字幕（原件自动备份为 *_未筛选.srt）")
            btn.clicked.connect(lambda: self._vt_filter_current_subtitle())
            self.command_bar.addWidget(btn)
            self._vt_vp_button = btn
        except Exception as e:  # noqa: BLE001
            _seams.vc_log(f"字幕翻译页声纹按钮挂载失败：{e}")

    def _init_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setObjectName("main_layout")
        self.main_layout.setSpacing(20)
        self._setup_top_layout()
        self._setup_subtitle_table()
        self._setup_bottom_layout()

    def set_values(self):
        self.layout_button.setText(_seams.cfg.subtitle_layout.value.value)
        self.translate_button.setChecked(_seams.cfg.need_translate.value)
        self.optimize_button.setChecked(_seams.cfg.need_optimize.value)
        self.target_language_button.setText(_seams.cfg.target_language.value.value)
        self.target_language_button.setEnabled(_seams.cfg.need_translate.value)

    def _setup_top_layout(self):
        top_layout = QHBoxLayout()

        self.command_bar = CommandBar(self)
        self.command_bar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        top_layout.addWidget(self.command_bar, 1)

        ent = _seams.entities
        save_menu = RoundMenu(parent=self)
        save_menu.view.setMaxVisibleItems(8)
        for format in ent.OutputSubtitleFormatEnum:
            action = Action(text=format.value)
            action.triggered.connect(
                lambda checked, f=format.value: self.on_save_format_clicked(f))
            save_menu.addAction(action)

        save_button = TransparentDropDownPushButton(self.tr("保存"), self, FIF.SAVE)
        save_button.setMenu(save_menu)
        save_button.setFixedHeight(34)
        self.command_bar.addWidget(save_button)

        self.layout_button = TransparentDropDownPushButton(
            self.tr("字幕排布"), self, FIF.LAYOUT)
        self.layout_button.setFixedHeight(34)
        self.layout_button.setMinimumWidth(125)
        self.layout_menu = RoundMenu(parent=self)
        for layout in ["译文在上", "原文在上", "仅译文", "仅原文"]:
            action = Action(text=layout)
            action.triggered.connect(
                lambda checked, layout_value=layout:
                _seams.signal_bus.subtitle_layout_changed.emit(layout_value))
            self.layout_menu.addAction(action)
        self.layout_button.setMenu(self.layout_menu)
        self.command_bar.addWidget(self.layout_button)
        self.command_bar.addSeparator()

        self.optimize_button = Action(
            FIF.EDIT, self.tr("字幕校正"),
            triggered=self.on_subtitle_optimization_changed, checkable=True)
        self.command_bar.addAction(self.optimize_button)

        self.translate_button = Action(
            FIF.LANGUAGE, self.tr("字幕翻译"),
            triggered=self.on_subtitle_translation_changed, checkable=True)
        self.command_bar.addAction(self.translate_button)

        self.target_language_button = TransparentDropDownPushButton(
            self.tr("翻译语言"), self, FIF.LANGUAGE)
        self.target_language_button.setFixedHeight(34)
        self.target_language_button.setMinimumWidth(125)
        self.target_language_menu = RoundMenu(parent=self)
        self.target_language_menu.setMaxVisibleItems(10)
        for lang in _seams.translate_types.TargetLanguage:
            action = Action(text=lang.value)
            action.triggered.connect(
                lambda checked, lang_value=lang.value:
                _seams.signal_bus.target_language_changed.emit(lang_value))
            self.target_language_menu.addAction(action)
        self.target_language_button.setMenu(self.target_language_menu)
        self.command_bar.addWidget(self.target_language_button)
        self.command_bar.addSeparator()

        self.prompt_button = Action(
            FIF.DOCUMENT, self.tr("Prompt"), triggered=self.show_prompt_dialog)
        self.command_bar.addAction(self.prompt_button)

        self.command_bar.addAction(
            Action(FIF.SETTING, "", triggered=self.show_subtitle_settings))
        self.command_bar.addAction(
            Action(FIF.FOLDER, "", triggered=self.on_open_folder_clicked))
        self.command_bar.addSeparator()
        self.command_bar.addAction(
            Action(FIF.FOLDER_ADD, "", triggered=self.on_file_select))

        self.start_button = PrimaryPushButton(self.tr("开始"), self, icon=FIF.PLAY)
        self.start_button.clicked.connect(
            lambda: self.start_subtitle_optimization(need_create_task=True))
        self.start_button.setFixedHeight(34)
        top_layout.addWidget(self.start_button)

        self.main_layout.addLayout(top_layout)

    def _setup_subtitle_table(self):
        self.subtitle_table = TableView(self)
        self.model = SubtitleTableModel("")
        self.subtitle_table.setModel(self.model)
        self.subtitle_table.setBorderVisible(True)
        self.subtitle_table.setBorderRadius(8)
        self.subtitle_table.setWordWrap(True)
        self.subtitle_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.subtitle_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.subtitle_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)
        self.subtitle_table.setColumnWidth(0, 120)
        self.subtitle_table.setColumnWidth(1, 120)
        self.subtitle_table.verticalHeader().setVisible(True)
        self.subtitle_table.verticalHeader().setDefaultAlignment(Qt.AlignCenter)
        self.subtitle_table.verticalHeader().setDefaultSectionSize(50)
        self.subtitle_table.verticalHeader().setMinimumWidth(20)
        self.subtitle_table.setEditTriggers(
            QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.subtitle_table.clicked.connect(self.on_subtitle_clicked)
        self.subtitle_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.subtitle_table.customContextMenuRequested.connect(self.show_context_menu)
        self.main_layout.addWidget(self.subtitle_table)

    def _setup_bottom_layout(self):
        self.bottom_layout = QHBoxLayout()
        self.progress_bar = ProgressBar(self)
        self.status_label = BodyLabel(self.tr("请拖入字幕文件"), self)
        self.status_label.setMinimumWidth(100)
        self.status_label.setAlignment(Qt.AlignCenter)
        self.cancel_button = PushButton(self.tr("取消"), self, icon=FIF.CANCEL)
        self.cancel_button.hide()
        self.cancel_button.clicked.connect(self.cancel_optimization)
        self.bottom_layout.addWidget(self.progress_bar, 1)
        self.bottom_layout.addWidget(self.status_label)
        self.bottom_layout.addWidget(self.cancel_button)
        self.main_layout.addLayout(self.bottom_layout)

    def _setup_signals(self) -> None:
        sb = _seams.signal_bus
        sb.subtitle_layout_changed.connect(self.on_subtitle_layout_changed)
        sb.target_language_changed.connect(self.on_target_language_changed)
        sb.subtitle_optimization_changed.connect(self.on_subtitle_optimization_changed)
        sb.subtitle_translation_changed.connect(self.on_subtitle_translation_changed)

    def show_prompt_dialog(self) -> None:
        dialog = PromptDialog(self)
        if dialog.exec_():
            self.custom_prompt_text = _seams.cfg.custom_prompt_text.value
            self._update_prompt_button_style()

    def _update_prompt_button_style(self) -> None:
        if self.custom_prompt_text.strip():
            green_icon = FIF.DOCUMENT.colored(QColor(76, 255, 165), QColor(76, 255, 165))
            self.prompt_button.setIcon(green_icon)
        else:
            self.prompt_button.setIcon(FIF.DOCUMENT)

    def set_task(self, task) -> None:
        if hasattr(self, "subtitle_optimization_thread"):
            self.subtitle_optimization_thread.stop()
            self._opt_active = False
        self.start_button.setEnabled(True)
        self.task = task
        self.subtitle_path = task.subtitle_path
        self.update_info(task)

    def update_info(self, task) -> None:
        if not self.task:
            return
        original_subtitle_save_path = Path(str(self.task.subtitle_path))
        asr_data = _seams.ASRData.from_subtitle_file(str(original_subtitle_save_path))
        self.model._data = asr_data.to_json()
        self.model.layoutChanged.emit()
        self.status_label.setText(self.tr("已加载文件"))

    def start_subtitle_optimization(self, need_create_task: bool = True) -> None:
        const = _seams.constants
        if self._is_processing():
            return
        if not self.subtitle_path:
            InfoBar.warning(self.tr("警告"), self.tr("请先加载字幕文件"),
                            duration=const.INFOBAR_DURATION_WARNING, parent=self)
            return
        self.start_button.setEnabled(False)
        self.progress_bar.resume()
        self.progress_bar.reset()
        self.cancel_button.show()
        if need_create_task:
            if self.model._data:
                _seams.ASRData.from_json(self.model._data).to_srt(save_path=self.subtitle_path)
            self.task = _seams.TaskFactory.create_subtitle_task(file_path=self.subtitle_path)
        if not self.task:
            self.start_button.setEnabled(True)
            self.cancel_button.hide()
            return
        self.subtitle_optimization_thread = _seams.threads.SubtitleThread(self.task)
        self.subtitle_optimization_thread.finished.connect(self.on_subtitle_optimization_finished)
        self.subtitle_optimization_thread.progress.connect(self.on_subtitle_optimization_progress)
        self.subtitle_optimization_thread.update.connect(self.update_data)
        self.subtitle_optimization_thread.update_all.connect(self.update_all)
        self.subtitle_optimization_thread.error.connect(self.on_subtitle_optimization_error)
        self.subtitle_optimization_thread.set_custom_prompt_text(self.custom_prompt_text)
        self._opt_active = True
        self.subtitle_optimization_thread.start()
        InfoBar.info(self.tr("开始优化"), self.tr("开始优化字幕"),
                     duration=const.INFOBAR_DURATION_INFO, parent=self)

    def process(self) -> None:
        self.start_subtitle_optimization(need_create_task=False)

    def on_subtitle_optimization_finished(self, video_path: str, output_path: str) -> None:
        self._opt_active = False
        self.start_button.setEnabled(True)
        self.cancel_button.hide()
        self.progress_bar.setValue(100)
        if self.task and self.task.need_next_task:
            self.finished.emit(video_path, output_path)
        InfoBar.success(
            self.tr("优化完成"), self.tr("优化完成字幕..."),
            duration=_seams.constants.INFOBAR_DURATION_SUCCESS,
            position=InfoBarPosition.BOTTOM, parent=self.parent())

    def on_subtitle_optimization_error(self, error: str) -> None:
        self._opt_active = False
        self.start_button.setEnabled(True)
        self.cancel_button.hide()
        self.progress_bar.error()
        # v2.3.1：一次「开始」可能跑优化 + 翻译两步，失败不一定来自优化——
        # 标题跟着内容走，别让翻译失败顶着一顶「优化失败」的帽子
        # （用户报「优化失败 Translation failed」时的第一困惑就是这个）。
        _msg = str(error)
        _title = (self.tr("翻译失败")
                  if ("译" in _msg or "Translation" in _msg)
                  else self.tr("优化失败"))
        InfoBar.error(_title, self.tr(_msg),
                      duration=_seams.constants.INFOBAR_DURATION_ERROR, parent=self)

    def on_subtitle_optimization_progress(self, value: int, status: str) -> None:
        # 终态后到来的进度不回弹：引擎 SubtitleThread 在 except 分支先
        # error.emit 再补发 progress(100, "字幕处理失败")，stop() 也会补发
        # progress(100, "已终止")。无脑 setValue 会把 error() 的红色错误态
        # 覆盖成满格完成态——进度条撒谎比不动更难排查。
        if not self._opt_active:
            return
        self.progress_bar.setValue(value)
        self.status_label.setText(status)

    def update_data(self, data):
        self.model.update_data(data)

    def update_all(self, data):
        self.model.update_all(data)

    def remove_widget(self) -> None:
        self.start_button.hide()
        for i in range(self.bottom_layout.count()):
            item = self.bottom_layout.itemAt(i)
            if item:
                widget = item.widget()
                if widget:
                    widget.hide()

    def on_file_select(self) -> None:
        ent = _seams.entities
        subtitle_formats = " ".join(f"*.{f.value}" for f in ent.SupportedSubtitleFormats)
        filter_str = f"{self.tr('字幕文件')} ({subtitle_formats})"
        file_path, _ = QFileDialog.getOpenFileName(
            self, self.tr("选择字幕文件"), "", filter_str)
        if file_path:
            self.subtitle_path = file_path
            self.load_subtitle_file(file_path)

    def on_save_format_clicked(self, format: str) -> None:
        const = _seams.constants
        if not self.subtitle_path:
            InfoBar.warning(self.tr("警告"), self.tr("请先加载字幕文件"),
                            duration=const.INFOBAR_DURATION_WARNING, parent=self)
            return
        default_name = Path(self.subtitle_path).stem
        file_path, _ = QFileDialog.getSaveFileName(
            self, self.tr("保存字幕文件"), default_name, f"{self.tr('字幕文件')} (*.{format})")
        if not file_path:
            return
        try:
            cfg = _seams.cfg
            asr_data = _seams.ASRData.from_json(self.model._data)
            # 归一为自研枚举：自研 ASRData 按枚举身份分支，跨类枚举永不相等
            layout = _seams.self_subtitle_layout(cfg.subtitle_layout.value)
            if file_path.endswith(".ass"):
                style_str = _seams.subtitle_style.get_subtitle_style(cfg.subtitle_style_name.value)
                asr_data.to_ass(style_str, layout, file_path)
            else:
                asr_data.save(file_path, layout=layout)
            InfoBar.success(self.tr("保存成功"), self.tr("字幕已保存至:") + file_path,
                            duration=const.INFOBAR_DURATION_SUCCESS, parent=self)
            _seams.platform_utils.reveal_in_explorer(file_path)
        except Exception as e:  # noqa: BLE001
            InfoBar.error(self.tr("保存失败"), self.tr("保存字幕文件失败: ") + str(e),
                          duration=const.INFOBAR_DURATION_ERROR, parent=self)

    def on_open_folder_clicked(self) -> None:
        const = _seams.constants
        if not self.task:
            InfoBar.warning(self.tr("警告"), self.tr("请先加载字幕文件"),
                            duration=const.INFOBAR_DURATION_WARNING, parent=self)
            return
        if self.task.output_path:
            output_path = Path(self.task.output_path)
            target_dir = str(output_path.parent if output_path.exists()
                             else Path(self.task.subtitle_path).parent)
        else:
            target_dir = str(Path(self.task.subtitle_path).parent)
        _seams.platform_utils.open_folder(target_dir)

    def load_subtitle_file(self, file_path: str) -> None:
        self.subtitle_path = file_path
        asr_data = _seams.ASRData.from_subtitle_file(file_path)
        self.model._data = asr_data.to_json()
        self.model.layoutChanged.emit()
        self.status_label.setText(self.tr("已加载文件"))

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        event.accept() if event.mimeData().hasUrls() else event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        const = _seams.constants
        ent = _seams.entities
        supported = {f.value for f in ent.SupportedSubtitleFormats}
        files = [u.toLocalFile() for u in event.mimeData().urls()]
        for file_path in files:
            if not os.path.isfile(file_path):
                continue
            file_ext = os.path.splitext(file_path)[1][1:].lower()
            if file_ext in supported:
                self.load_subtitle_file(file_path)
                InfoBar.success(
                    self.tr("导入成功"), self.tr("成功导入") + os.path.basename(file_path),
                    duration=const.INFOBAR_DURATION_SUCCESS,
                    position=InfoBarPosition.BOTTOM, parent=self)
                break
            else:
                InfoBar.error(
                    self.tr("格式错误") + file_ext,
                    self.tr("支持的字幕格式:") + str(supported),
                    duration=const.INFOBAR_DURATION_ERROR, parent=self)
        event.accept()

    def closeEvent(self, event) -> None:
        if hasattr(self, "subtitle_optimization_thread"):
            self.subtitle_optimization_thread.stop()
        super().closeEvent(event)

    def show_subtitle_settings(self) -> None:
        from .subtitle_setting_dialog import SubtitleSettingDialog
        dialog = SubtitleSettingDialog(self.window())
        dialog.exec_()

    def on_subtitle_clicked(self, index: QModelIndex) -> None:
        row = index.row()
        item = list(self.model._data.values())[row]
        start_time = item["start_time"]
        end_time = (item["end_time"] - 50
                    if item["end_time"] - 50 > start_time else item["end_time"])
        _seams.signal_bus.play_video_segment(start_time, end_time)

    def show_context_menu(self, pos) -> None:
        cfg = _seams.cfg
        menu = RoundMenu(parent=self)
        indexes = self.subtitle_table.selectedIndexes()
        if not indexes:
            return
        rows = sorted(set(index.row() for index in indexes))
        if not rows:
            return
        merge_action = Action(FIF.LINK, self.tr("合并"))
        delete_action = Action(FIF.DELETE, self.tr("删除"))
        retranslate_action = Action(FIF.SYNC, self.tr("重新翻译"))
        menu.addAction(merge_action)
        menu.addAction(delete_action)
        menu.addAction(retranslate_action)
        merge_action.setShortcut("Ctrl+M")
        delete_action.setShortcut("Delete")
        retranslate_action.setShortcut("Ctrl+T")
        merge_action.setEnabled(len(rows) > 1)
        retranslate_action.setEnabled(cfg.need_translate.value and not self._is_processing())
        merge_action.triggered.connect(lambda: self.merge_selected_rows(rows))
        delete_action.triggered.connect(lambda: self.delete_selected_rows(rows))
        retranslate_action.triggered.connect(lambda: self.retranslate_selected_rows(rows))
        menu.exec(self.subtitle_table.viewport().mapToGlobal(pos))

    def merge_selected_rows(self, rows: List[int]) -> None:
        if not rows or len(rows) < 2:
            return
        data = self.model._data
        data_list = list(data.values())
        first_row = data_list[rows[0]]
        last_row = data_list[rows[-1]]
        start_time = first_row["start_time"]
        end_time = last_row["end_time"]
        original_subtitles = []
        translated_subtitles = []
        for row in rows:
            item = data_list[row]
            original_subtitles.append(item["original_subtitle"])
            translated_subtitles.append(item["translated_subtitle"])
        merged_item = {
            "start_time": start_time,
            "end_time": end_time,
            "original_subtitle": " ".join(original_subtitles),
            "translated_subtitle": " ".join(translated_subtitles),
        }
        keys = list(data.keys())
        preserved_keys = keys[: rows[0]] + keys[rows[-1] + 1:]
        new_data: Dict[str, Any] = {}
        for i, key in enumerate(preserved_keys):
            if i == rows[0]:
                new_data[f"{len(new_data) + 1}"] = merged_item
            new_data[f"{len(new_data) + 1}"] = data[key]
        if rows[0] >= len(preserved_keys):
            new_data[f"{len(new_data) + 1}"] = merged_item
        self.subtitle_table.clearSelection()
        self.model.update_all(new_data)
        InfoBar.success(self.tr("合并成功"), self.tr("已成功合并选中的字幕行"),
                        duration=_seams.constants.INFOBAR_DURATION_SUCCESS, parent=self)

    def delete_selected_rows(self, rows: List[int]) -> None:
        if not rows:
            return
        data = self.model._data
        keys = list(data.keys())
        rows_set = set(rows)
        new_data: Dict[str, Any] = {}
        for i, key in enumerate(keys):
            if i not in rows_set:
                new_data[f"{len(new_data) + 1}"] = data[key]
        self.subtitle_table.clearSelection()
        self.model.update_all(new_data)

    def _is_processing(self) -> bool:
        if hasattr(self, "subtitle_optimization_thread") and self.subtitle_optimization_thread.isRunning():
            return True
        if hasattr(self, "_retranslate_thread") and self._retranslate_thread.isRunning():
            return True
        return False

    def retranslate_selected_rows(self, rows: List[int]) -> None:
        if not rows or not self.model._data:
            return
        if self._is_processing():
            return
        all_keys = list(self.model._data.keys())
        selected_data = {all_keys[row]: self.model._data[all_keys[row]] for row in rows}
        subtitle_task = _seams.TaskFactory.create_subtitle_task(file_path=self.subtitle_path or "")
        config = subtitle_task.subtitle_config
        if not config:
            return
        self.start_button.setEnabled(False)
        self.status_label.setText(self.tr("正在重新翻译..."))
        self.progress_bar.resume()
        self.progress_bar.reset()
        file_name = Path(self.subtitle_path).name if self.subtitle_path else ""
        self._retranslate_thread = _seams.threads.RetranslateThread(selected_data, config, file_name)
        self._retranslate_thread.finished.connect(self._on_retranslate_finished)
        self._retranslate_thread.progress.connect(self.on_subtitle_optimization_progress)
        self._retranslate_thread.error.connect(self._on_retranslate_error)
        self._opt_active = True
        self._retranslate_thread.start()

    def _on_retranslate_finished(self, result: dict) -> None:
        self._opt_active = False
        self.start_button.setEnabled(True)
        self.model.update_data(result)
        self.progress_bar.setValue(100)
        self.status_label.setText(self.tr("重新翻译完成"))
        InfoBar.success(self.tr("翻译完成"), self.tr("已更新选中行的翻译"),
                        duration=_seams.constants.INFOBAR_DURATION_SUCCESS, parent=self)

    def _on_retranslate_error(self, error: str) -> None:
        self._opt_active = False
        self.start_button.setEnabled(True)
        self.progress_bar.error()
        self.status_label.setText(self.tr("重新翻译失败"))
        InfoBar.error(self.tr("翻译失败"), error,
                      duration=_seams.constants.INFOBAR_DURATION_ERROR, parent=self)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_M:
            indexes = self.subtitle_table.selectedIndexes()
            if indexes:
                rows = sorted(set(index.row() for index in indexes))
                if len(rows) > 1:
                    self.merge_selected_rows(rows)
            event.accept()
        elif event.key() == Qt.Key_Delete:
            indexes = self.subtitle_table.selectedIndexes()
            if indexes:
                rows = sorted(set(index.row() for index in indexes))
                self.delete_selected_rows(rows)
            event.accept()
        elif event.modifiers() == Qt.ControlModifier and event.key() == Qt.Key_T:
            if _seams.cfg.need_translate.value and not self._is_processing():
                indexes = self.subtitle_table.selectedIndexes()
                if indexes:
                    rows = sorted(set(index.row() for index in indexes))
                    self.retranslate_selected_rows(rows)
            event.accept()
        else:
            super().keyPressEvent(event)

    def cancel_optimization(self) -> None:
        if hasattr(self, "subtitle_optimization_thread"):
            self.subtitle_optimization_thread.stop()
            self._opt_active = False
            self.start_button.setEnabled(True)
            self.cancel_button.hide()
            self.progress_bar.resume()
            self.progress_bar.setValue(0)
            self.status_label.setText(self.tr("已取消校正"))
            InfoBar.warning(self.tr("已取消"), self.tr("字幕校正已取消"),
                            duration=_seams.constants.INFOBAR_DURATION_WARNING, parent=self)

    def on_target_language_changed(self, language: str) -> None:
        for lang in _seams.translate_types.TargetLanguage:
            if lang.value == language:
                self.target_language_button.setText(lang.value)
                _seams.cfg.set(_seams.cfg.target_language, lang)
                break

    def on_subtitle_optimization_changed(self, checked: bool) -> None:
        _seams.cfg.set(_seams.cfg.need_optimize, checked)
        self.optimize_button.setChecked(checked)

    def on_subtitle_translation_changed(self, checked: bool) -> None:
        _seams.cfg.set(_seams.cfg.need_translate, checked)
        self.translate_button.setChecked(checked)
        self.target_language_button.setEnabled(checked)

    def on_subtitle_layout_changed(self, layout: str) -> None:
        layout_enum = _seams.entities.SubtitleLayoutEnum(layout)
        _seams.cfg.set(_seams.cfg.subtitle_layout, layout_enum)
        self.layout_button.setText(layout)

    # ---------------- 补丁 ⑨（内建）：按声纹筛选当前字幕 ----------------
    def _start_voiceprint_filter(self, out, media, then) -> bool:
        parent = self.window()
        try:
            bar = InfoBar.info("正在按声纹筛选", "只保留主播台词，请稍候（长片约需半分钟）…",
                               duration=-1, position=InfoBarPosition.BOTTOM, parent=parent)
        except Exception:  # noqa: BLE001
            bar = None

        class _VpWorker(QThread):
            done = Signal(object)

            def run(self):
                try:
                    r = _seams.voiceprint_filter_subtitle(out, media)
                except Exception as e:  # noqa: BLE001
                    _seams.vc_log(f"声纹筛选失败：{e}")
                    r = {"error": str(e)}
                self.done.emit(r)

        def _finish(res):
            try:
                if bar is not None:
                    bar.close()
            except Exception:  # noqa: BLE001
                pass
            try:
                if isinstance(res, dict) and res.get("error"):
                    InfoBar.error("声纹筛选失败", str(res["error"])[:200] + "\n字幕已保留未筛选版本",
                                  duration=9000, position=InfoBarPosition.BOTTOM, parent=parent)
                elif res is None:
                    InfoBar.warning("声纹筛选未执行",
                                    "声纹模型还没下载：到「语音转录 → 主播声纹」点「下载模型」",
                                    duration=8000, position=InfoBarPosition.BOTTOM, parent=parent)
                else:
                    InfoBar.success(
                        "声纹筛选完成",
                        "保留 %d 条（其中存疑 %d）/ 丢弃 %d；原件已备份为「%s」"
                        % (res["kept_total"], res["review"], res["drop"],
                           os.path.basename(res.get("backup") or "")),
                        duration=9000, position=InfoBarPosition.BOTTOM, parent=parent)
            except Exception:  # noqa: BLE001
                pass
            try:
                then()
            except Exception as e:  # noqa: BLE001
                _seams.vc_log(f"声纹筛选后刷新异常：{e}")

        w = _VpWorker()
        w.done.connect(_finish)
        self._vt_vp_worker = w
        w.start()
        return True

    def _vt_filter_current_subtitle(self):
        path = getattr(self, "subtitle_path", None)
        media = getattr(getattr(self, "task", None), "video_path", None)
        if not path or not os.path.isfile(path):
            InfoBar.warning("没有可筛选的字幕", "请先加载字幕文件", duration=5000,
                            position=InfoBarPosition.BOTTOM, parent=self)
            return
        if not media or not os.path.isfile(media):
            InfoBar.warning("缺少配套视频",
                            "声纹筛选要从原视频/音频里取声音，当前字幕没有关联的媒体文件",
                            duration=7000, position=InfoBarPosition.BOTTOM, parent=self)
            return
        if not _seams.voiceprint_enabled_names():
            InfoBar.warning("没有启用声纹", "到「语音转录 → 主播声纹」勾选要保留的声音（可多选）",
                            duration=7000, position=InfoBarPosition.BOTTOM, parent=self)
            return
        # 先把表格编辑写回文件（与 start_subtitle_optimization 同款），避免丢改动
        try:
            if getattr(self.model, "_data", None):
                _seams.ASRData.from_json(self.model._data).to_srt(save_path=path)
        except Exception as e:  # noqa: BLE001
            _seams.vc_log(f"筛选前回写表格失败（忽略，继续筛）：{e}")

        def _after():
            try:
                self.load_subtitle_file(path)
            except Exception as e:  # noqa: BLE001
                _seams.vc_log(f"筛选后刷新表格失败：{e}")

        if not self._start_voiceprint_filter(path, media, _after):
            _after()


class PromptDialog(MessageBoxBase):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setup_ui()
        self.setWindowTitle(self.tr("文稿提示"))
        self.yesButton.clicked.connect(self.save_prompt)

    def setup_ui(self) -> None:
        self.titleLabel = BodyLabel(self.tr("文稿提示"), self)
        self.text_edit = TextEdit(self)
        self.text_edit.setPlaceholderText(
            self.tr(
                "请输入文稿提示（辅助校正字幕和翻译）\n\n"
                "支持以下内容:\n"
                "1. 术语表 - 专业术语、人名、特定词语的修正对照表\n"
                "示例:\n机器学习->Machine Learning\n马斯克->Elon Musk\n打call->应援\n\n"
                "2. 原字幕文稿 - 视频的原有文稿或相关内容\n"
                "示例: 完整的演讲稿、课程讲义等\n\n"
                "3. 修正要求 - 内容相关的具体修正要求\n"
                "示例: 统一人称代词、规范专业术语等\n\n"
                "注意: 使用小型LLM模型时建议控制文稿在1千字内。对于不同字幕文件,请使用与该字幕相关的文稿提示。"))
        self.text_edit.setText(_seams.cfg.custom_prompt_text.value)
        self.text_edit.setMinimumWidth(420)
        self.text_edit.setMinimumHeight(380)
        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.text_edit)
        self.viewLayout.setSpacing(10)
        self.yesButton.setText(self.tr("确定"))
        self.cancelButton.setText(self.tr("取消"))

    def get_prompt(self) -> str:
        return self.text_edit.toPlainText()

    def save_prompt(self) -> None:
        _seams.cfg.set(_seams.cfg.custom_prompt_text, self.text_edit.toPlainText())
