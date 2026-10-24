# -*- coding: utf-8 -*-
# @version 2.6.0
"""自研「语音转录」页（含 ``VideoInfoCard``）。

视觉与引擎转录页对齐；把原本运行期打在引擎类上的转录补丁**内建为显式逻辑**：

  ① 命令栏转录模型下拉只建「默认 / ASR」两项；
  ② 选「ASR」实时 ``apply_asr_to_engine()``（以全局「ASR 语音识别」为准），未配
     好给设置指引；选「默认」落回 B 接口；启动恢复/广播只做显示映射并按需回写；
     ``_vt_model_busy`` 截断 cfg 信号环路；
  ③ 独立转录（``need_next_task=False``）完成后把产物字幕装载进「字幕翻译」并切
     过去；入口先无条件复位 ``is_processing``；``_home_of`` 沿 parent 链上溯（Qt
     会把子界面重挂到 QStackedWidget，故不能只用 ``parent()``）；``_produced_subtitle``
     按同基名补齐真实后缀；
  ⑥ 启用了声纹则先后台 ``QThread`` 筛选、筛完再回填（顺序不可反；worker 挂实例
     防 GC）；
  ③-B 陈旧「处理中」自愈：``dropEvent`` / ``_on_file_select`` 前，若标记为真但无
     运行中的转录线程，则清标记并复位卡片按钮，再照常放行。

对外契约（``command_bar`` / ``model_button`` / ``model_menu`` / ``video_info_card``
/ ``transcription_setting_card`` / ``is_processing`` / ``finished`` / ``set_task``
/ ``process`` / ``dropEvent`` / ``_on_file_select`` / ``_on_transcript_finished``
/ ``on_transcription_model_changed`` / ``_setup_command_bar``）与引擎同名同义。
"""
from __future__ import annotations

import datetime
import os
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QStandardPaths, Qt, QThread, Signal
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)
from vt_fluent import (
    Action,
    BodyLabel,
    CardWidget,
    CommandBar,
    FluentIcon,
    InfoBar,
    InfoBarPosition,
    PillPushButton,
    PrimaryPushButton,
    ProgressRing,
    PushButton,
    RoundMenu,
    TransparentDropDownPushButton,
    setFont,
)

from . import _seams
from .components import TranscriptionSettingCard, TranscriptionSettingDialog


class VideoInfoCard(CardWidget):
    finished = Signal(object)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setup_ui()
        self.setup_signals()
        self.task = None
        self.video_info = None
        self.transcription_interface = parent
        self.selected_audio_track_index = 0

    def setup_ui(self) -> None:
        self.setFixedHeight(150)
        self.main_layout = QHBoxLayout(self)
        self.main_layout.setContentsMargins(20, 15, 20, 15)
        self.main_layout.setSpacing(20)
        self.setup_thumbnail()
        self.setup_info_layout()
        self.setup_button_layout()

    def _default_thumbnail(self) -> str:
        try:
            return str(_seams.vc_config.RESOURCE_PATH / "assets" / "default_thumbnail.jpg")
        except Exception:  # noqa: BLE001
            return ""

    def setup_thumbnail(self) -> None:
        self.video_thumbnail = QLabel(self)
        self.video_thumbnail.setFixedSize(208, 117)
        self.video_thumbnail.setStyleSheet("background-color: #1E1F22;")
        self.video_thumbnail.setAlignment(Qt.AlignCenter)
        path = self._default_thumbnail()
        if path:
            pm = QPixmap(path)
            if not pm.isNull():
                pm = pm.scaled(self.video_thumbnail.size(), Qt.KeepAspectRatio,
                               Qt.SmoothTransformation)
                self.video_thumbnail.setPixmap(pm)
        self.main_layout.addWidget(self.video_thumbnail, 0, Qt.AlignLeft)

    def setup_info_layout(self) -> None:
        self.info_layout = QVBoxLayout()
        self.info_layout.setContentsMargins(3, 8, 3, 8)
        self.info_layout.setSpacing(10)

        self.video_title = BodyLabel(self.tr("请拖入音频或视频文件"), self)
        self.video_title.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
        self.video_title.setWordWrap(True)
        self.info_layout.addWidget(self.video_title, alignment=Qt.AlignTop)

        self.details_layout = QHBoxLayout()
        self.details_layout.setSpacing(15)

        self.resolution_info = self.create_pill_button(self.tr("画质"), 110)
        self.file_size_info = self.create_pill_button(self.tr("文件大小"), 110)
        self.duration_info = self.create_pill_button(self.tr("时长"), 100)
        self.audio_track_button = self.create_pill_button(self.tr("音轨"), 100)
        self.audio_track_button.hide()

        self.progress_ring = ProgressRing(self)
        self.progress_ring.setFixedSize(20, 20)
        self.progress_ring.setStrokeWidth(4)
        self.progress_ring.hide()

        self.details_layout.addWidget(self.resolution_info)
        self.details_layout.addWidget(self.file_size_info)
        self.details_layout.addWidget(self.duration_info)
        self.details_layout.addWidget(self.audio_track_button)
        self.details_layout.addWidget(self.progress_ring)
        self.details_layout.addStretch(1)
        self.info_layout.addLayout(self.details_layout)
        self.main_layout.addLayout(self.info_layout)

    def create_pill_button(self, text: str, width: int) -> PillPushButton:
        button = PillPushButton(text, self)
        button.setCheckable(False)
        setFont(button, 11)
        button.setMinimumWidth(50)
        return button

    def setup_button_layout(self) -> None:
        self.button_layout = QVBoxLayout()
        self.open_folder_button = PushButton(self.tr("打开文件夹"), self)
        self.start_button = PrimaryPushButton(self.tr("开始转录"), self)
        self.button_layout.addWidget(self.open_folder_button)
        self.button_layout.addWidget(self.start_button)
        self.start_button.setDisabled(True)

        button_widget = QWidget()
        button_widget.setLayout(self.button_layout)
        button_widget.setFixedWidth(130)
        self.main_layout.addWidget(button_widget)

    def update_info(self, video_info) -> None:
        self.reset_ui()
        self.video_info = video_info
        self.video_title.setText(video_info.file_name.rsplit(".", 1)[0])
        self.resolution_info.setText(
            self.tr("画质: ") + f"{video_info.width}x{video_info.height}")
        try:
            file_size_mb = os.path.getsize(video_info.file_path) / 1024 / 1024
            self.file_size_info.setText(self.tr("大小: ") + f"{file_size_mb:.1f} MB")
        except OSError:
            pass
        duration = datetime.timedelta(seconds=int(video_info.duration_seconds))
        self.duration_info.setText(self.tr("时长: ") + f"{duration}")
        self.update_audio_tracks(video_info)
        if self.transcription_interface and self.transcription_interface.is_processing:
            self.start_button.setEnabled(False)
        else:
            self.start_button.setEnabled(True)
        self.update_thumbnail(video_info.thumbnail_path)

    def update_audio_tracks(self, video_info) -> None:
        audio_streams = video_info.audio_streams
        if len(audio_streams) > 1:
            self.selected_audio_track_index = 0
            self.update_audio_track_button_text(audio_streams, 0)
            menu = RoundMenu(parent=self)
            for i, stream in enumerate(audio_streams):
                lang = stream.language
                text = self.tr("音轨") + str(i + 1)
                if lang:
                    text += f" ({lang})"
                action = Action(text)
                action.triggered.connect(
                    lambda checked, array_idx=i, streams=audio_streams:
                    self.on_audio_track_selected(array_idx, streams))
                menu.addAction(action)
            self.audio_track_button.clicked.connect(
                lambda: menu.exec(self.audio_track_button.mapToGlobal(
                    self.audio_track_button.rect().bottomLeft())))
            self.audio_track_button.show()
        else:
            self.audio_track_button.hide()
            self.selected_audio_track_index = 0

    def update_audio_track_button_text(self, audio_streams: list, array_index: int) -> None:
        if array_index < len(audio_streams):
            stream = audio_streams[array_index]
            lang = stream.language
            text = f"{self.tr('音轨')} {array_index + 1}"
            if lang:
                text += f" ({lang})"
            self.audio_track_button.setText(text)

    def on_audio_track_selected(self, array_index: int, audio_streams: list) -> None:
        self.selected_audio_track_index = array_index
        self.update_audio_track_button_text(audio_streams, array_index)

    def update_thumbnail(self, thumbnail_path):
        try:
            resource_path = _seams.vc_config.RESOURCE_PATH
        except Exception:  # noqa: BLE001
            resource_path = None
        if not thumbnail_path or not Path(str(thumbnail_path)).exists():
            if resource_path is not None:
                thumbnail_path = resource_path / "assets" / "audio-thumbnail.png"
        pm = QPixmap(str(thumbnail_path))
        if not pm.isNull():
            pm = pm.scaled(self.video_thumbnail.size(), Qt.KeepAspectRatio,
                           Qt.SmoothTransformation)
            self.video_thumbnail.setPixmap(pm)

    def setup_signals(self) -> None:
        self.start_button.clicked.connect(self.on_start_button_clicked)
        self.open_folder_button.clicked.connect(self.on_open_folder_clicked)

    def on_start_button_clicked(self):
        self.progress_ring.setValue(0)
        self.progress_ring.show()
        self.start_button.setDisabled(True)
        self.start_transcription()

    def on_open_folder_clicked(self):
        if self.task and self.task.output_path:
            original = Path(str(self.task.output_path))
            target_dir = str(original.parent if original.exists()
                             else Path(str(self.task.file_path)).parent)
            _seams.platform_utils.open_folder(target_dir)
        else:
            InfoBar.warning(
                self.tr("警告"), self.tr("没有可用的字幕文件夹"),
                duration=_seams.constants.INFOBAR_DURATION_WARNING, parent=self)

    def start_transcription(self, need_create_task=True):
        self.transcription_interface.is_processing = True
        self.start_button.setEnabled(False)
        if need_create_task:
            self.task = _seams.TaskFactory.create_transcribe_task(self.video_info.file_path)
        if not self.task:
            return
        self.task.selected_audio_track_index = self.selected_audio_track_index
        self.transcript_thread = _seams.threads.TranscriptThread(self.task)
        self.transcript_thread.finished.connect(self.on_transcript_finished)
        self.transcript_thread.progress.connect(self.on_transcript_progress)
        self.transcript_thread.error.connect(self.on_transcript_error)
        self.transcript_thread.start()

    def on_transcript_progress(self, value, message):
        # 终态后到来的进度不回弹按钮文案：引擎 TranscriptThread 在 except 分支
        # 先 error.emit 再补发 progress(100, "转录失败")，两个信号都会排到主
        # 线程队列；无脑 setText 会把错误态刚设好的「重新转录」覆盖成「转录
        # 失败」——绿色主按钮挂着失败文案，状态既看不懂也点不出正确预期。
        # is_processing 是终态权威标记：start_transcription 置真，
        # error / finished / _vt_heal_stale 置假。
        if not self.transcription_interface.is_processing:
            return
        self.start_button.setText(message)
        self.progress_ring.setValue(value)

    def on_transcript_error(self, error):
        self.transcription_interface.is_processing = False
        self.start_button.setEnabled(True)
        self.start_button.setText(self.tr("重新转录"))
        self.progress_ring.hide()
        InfoBar.error(
            self.tr("转录失败"), self.tr(error),
            duration=_seams.constants.INFOBAR_DURATION_ERROR,
            parent=self.parent().parent())

    def on_transcript_finished(self, task):
        self.start_button.setEnabled(True)
        self.start_button.setText(self.tr("转录完成"))
        self.progress_ring.hide()
        self.finished.emit(task)

    def reset_ui(self):
        self.start_button.setDisabled(False)
        self.start_button.setText(self.tr("开始转录"))
        self.progress_ring.setValue(0)
        self.progress_ring.hide()

    def set_task(self, task):
        self.task = task
        self.reset_ui()

    def stop(self):
        if hasattr(self, "transcript_thread"):
            self.transcript_thread.terminate()


class TranscriptionInterface(QWidget):
    finished = Signal(str, str)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAcceptDrops(True)
        self.task = None
        self.is_processing: bool = False
        self._vt_model_busy = False
        self._vt_vp_worker = None

        self._init_ui()
        self._setup_signals()
        self._set_value()

    # ---------------- UI ----------------
    def _init_ui(self) -> None:
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setObjectName("main_layout")
        self.main_layout.setSpacing(20)
        self._setup_command_bar()
        self.video_info_card = VideoInfoCard(self)
        self.main_layout.addWidget(self.video_info_card)
        self.transcription_setting_card = TranscriptionSettingCard(self)
        self.main_layout.addWidget(self.transcription_setting_card)

    def _setup_command_bar(self):
        self.command_bar = CommandBar(self)
        self.command_bar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.command_bar.setFixedHeight(40)

        self.open_file_action = Action(FluentIcon.FOLDER, self.tr("打开文件"))
        self.open_file_action.triggered.connect(self._on_file_select)
        self.command_bar.addAction(self.open_file_action)
        self.command_bar.addSeparator()

        self.model_button = TransparentDropDownPushButton(
            self.tr("转录模型"), self, FluentIcon.MICROPHONE)
        self.model_button.setFixedHeight(34)
        self.model_button.setMinimumWidth(180)

        # 补丁 ①（内建）：下拉只留「默认 / ASR」
        self.model_menu = RoundMenu(parent=self)
        self.model_menu.addActions([
            Action(FluentIcon.GLOBE, _seams.TM_DISPLAY_DEFAULT),
            Action(FluentIcon.MICROPHONE, _seams.TM_DISPLAY_ASR),
        ])
        self.model_button.setMenu(self.model_menu)
        self.command_bar.addWidget(self.model_button)
        self.command_bar.addSeparator()

        self.command_bar.addAction(
            Action(FluentIcon.SETTING, "", triggered=self._show_output_settings))
        self.main_layout.addWidget(self.command_bar)

    def _setup_signals(self) -> None:
        self.video_info_card.finished.connect(self._on_transcript_finished)
        for action in self.model_menu.actions():
            action.triggered.connect(
                lambda checked, text=action.text():
                self.on_transcription_model_changed(text))
        _seams.signal_bus.transcription_model_changed.connect(
            self.on_transcription_model_changed)

    def _show_output_settings(self):
        dialog = TranscriptionSettingDialog(self.window())
        dialog.exec_()

    def _set_value(self) -> None:
        model_name = _seams.cfg.get(_seams.cfg.transcribe_model).value
        self.on_transcription_model_changed(model_name)

    # ---------------- 补丁 ②：显示名 ↔ 引擎枚举 ----------------
    def on_transcription_model_changed(self, model_name: str):
        if self._vt_model_busy:
            return
        cfg = _seams.cfg
        ent = _seams.entities
        TM_DEFAULT = _seams.TM_DISPLAY_DEFAULT
        TM_ASR = _seams.TM_DISPLAY_ASR
        try:
            asr_values = (ent.TranscribeModelEnum.WHISPER_API.value,
                          ent.TranscribeModelEnum.FASTER_WHISPER.value)
            if model_name == TM_ASR:
                self._vt_model_busy = True
                try:
                    self.model_button.setText(TM_ASR)
                    self.transcription_setting_card.on_model_changed(TM_ASR)
                    ok, detail = _seams.apply_asr_to_engine()
                    if not ok:
                        _seams.vc_log(f"ASR 应用失败：{detail}")
                    if self._asr_not_ready():
                        InfoBar.warning(
                            "ASR 未配置",
                            ("%s；" % self._asr_missing_hint()
                             if self._asr_missing_hint() else "")
                            + "请到 设置 → ASR 语音识别 填好后点「保存并应用」"
                              "（只填不保存不生效）",
                            duration=8000, parent=self.window())
                finally:
                    self._vt_model_busy = False
                return
            if model_name == TM_DEFAULT:
                self._vt_model_busy = True
                try:
                    self.model_button.setText(TM_DEFAULT)
                    self.transcription_setting_card.on_model_changed(TM_DEFAULT)
                    cfg.set(cfg.transcribe_model, ent.TranscribeModelEnum.BIJIAN)
                finally:
                    self._vt_model_busy = False
                return
            # 启动恢复 / signalBus 广播（传引擎枚举值）：只做显示映射
            if model_name in asr_values:
                self.model_button.setText(TM_ASR)
                self.transcription_setting_card.on_model_changed(TM_ASR)
            else:
                self.model_button.setText(TM_DEFAULT)
                self.transcription_setting_card.on_model_changed(TM_DEFAULT)
                if model_name != ent.TranscribeModelEnum.BIJIAN.value:
                    self._vt_model_busy = True
                    try:
                        cfg.set(cfg.transcribe_model, ent.TranscribeModelEnum.BIJIAN)
                    finally:
                        self._vt_model_busy = False
        except Exception as e:  # noqa: BLE001
            self._vt_model_busy = False
            _seams.vc_log(f"转录模型切换异常：{e}")

    def _asr_not_ready(self) -> bool:
        try:
            ac = _seams.ai_mod().asr_config(_seams.ai_load_config())
            if ac.get("mode") == "local":
                return not (ac.get("local_model") or ac.get("local_model_dir"))
            return not (ac.get("base_url") and ac.get("api_key"))
        except Exception:  # noqa: BLE001
            return False

    def _asr_missing_hint(self) -> str:
        try:
            ac = _seams.ai_mod().asr_config(_seams.ai_load_config())
            if ac.get("mode") == "local":
                if not (ac.get("local_model") or ac.get("local_model_dir")):
                    return "本地模式还没填模型名或目录"
                return ""
            miss = []
            if not ac.get("base_url"):
                miss.append("接口地址")
            if not ac.get("api_key"):
                miss.append("密钥")
            return ("已保存的配置里缺：" + "、".join(miss)) if miss else ""
        except Exception:  # noqa: BLE001
            return ""

    # ---------------- 补丁 ③ + ⑥：转录完成回填 + 声纹筛选 ----------------
    def _home_of(self, widget):
        w = widget
        while w is not None:
            if getattr(w, "subtitle_optimization_interface", None) is not None:
                return w
            w = w.parent()
        try:
            for tl in QApplication.topLevelWidgets():
                if getattr(tl, "subtitle_optimization_interface", None) is not None:
                    return tl
                for ch in tl.findChildren(QWidget):
                    if getattr(ch, "subtitle_optimization_interface", None) is not None:
                        return ch
        except Exception:  # noqa: BLE001
            pass
        return None

    def _produced_subtitle(self, path):
        if not path:
            return None
        try:
            if os.path.isfile(path):
                return path
            base = os.path.splitext(path)[0]
            for ext in (".srt", ".ass", ".vtt"):
                cand = base + ext
                if os.path.isfile(cand):
                    return cand
            d, stem = os.path.split(base)
            if os.path.isdir(d):
                for name in sorted(os.listdir(d)):
                    low = name.lower()
                    if (name.startswith(stem + ".")
                            and low.endswith((".srt", ".ass", ".vtt"))):
                        return os.path.join(d, name)
        except Exception:  # noqa: BLE001
            pass
        return None

    def _start_voiceprint_filter(self, iface, out, media, then) -> bool:
        parent = self._home_of(iface) or iface.window()
        try:
            bar = InfoBar.info(
                "正在按声纹筛选", "只保留主播台词，请稍候（长片约需半分钟）…",
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
                    InfoBar.error(
                        "声纹筛选失败",
                        str(res["error"])[:200] + "\n字幕已保留未筛选版本",
                        duration=9000, position=InfoBarPosition.BOTTOM, parent=parent)
                elif res is None:
                    InfoBar.warning(
                        "声纹筛选未执行",
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
                _seams.vc_log(f"声纹筛选后回填异常：{e}")

        w = _VpWorker()
        w.done.connect(_finish)
        iface._vt_vp_worker = w
        w.start()
        return True

    def _on_transcript_finished(self, task):
        # 补丁 ③：入口先无条件复位「处理中」标记
        self.is_processing = False
        try:
            if task is not None and not getattr(task, "need_next_task", False):
                out = self._produced_subtitle(getattr(task, "output_path", None))
                media = getattr(task, "file_path", None)

                def _handoff():
                    home = self._home_of(self) if out else None
                    sub = (getattr(home, "subtitle_optimization_interface", None)
                           if home is not None else None)
                    if sub is None:
                        if out:
                            _seams.vc_log("独立转录完成，但未定位到工作台首页，回退引擎原逻辑")
                        return False
                    st = _seams.TaskFactory.create_subtitle_task(
                        out, media, need_next_task=False,
                        task_id=getattr(home, "_current_task_id", None))
                    sub.set_task(st)
                    home.stackedWidget.setCurrentWidget(sub)
                    home.pivot.setCurrentItem("SubtitleInterface")
                    _seams.vc_log(f"独立转录完成 → 已装载「字幕翻译」：{out}")
                    InfoBar.success(
                        "转录完成",
                        "生成的字幕已装载到「字幕翻译」，可直接开始优化 / 翻译",
                        duration=5000, position=InfoBarPosition.BOTTOM, parent=home)
                    return True

                if out and _seams.voiceprint_enabled_names():
                    if self._start_voiceprint_filter(self, out, media, _handoff):
                        return
                if _handoff():
                    return
        except Exception as e:  # noqa: BLE001
            _seams.vc_log(f"转录完成回填异常：{e}")
        # 引擎原生行为：need_next_task 时发 finished 并提示
        if task is not None and getattr(task, "need_next_task", False):
            self.finished.emit(task.output_path, task.file_path)
            InfoBar.success(
                self.tr("转录完成"), self.tr("开始字幕优化..."),
                duration=_seams.constants.INFOBAR_DURATION_SUCCESS,
                position=InfoBarPosition.BOTTOM, parent=self.parent())

    # ---------------- 补丁 ③-B：陈旧「处理中」自愈 ----------------
    def _vt_heal_stale(self) -> bool:
        if not getattr(self, "is_processing", False):
            return False
        card = getattr(self, "video_info_card", None)
        th = getattr(card, "transcript_thread", None) if card is not None else None
        if th is not None:
            try:
                if th.isRunning():
                    return False
            except Exception:  # noqa: BLE001
                return False
        self.is_processing = False
        try:
            if card is not None:
                card.reset_ui()
        except Exception:  # noqa: BLE001
            pass
        _seams.vc_log("转录页陈旧「处理中」状态已自愈（无运行中的转录线程）")
        return True

    # ---------------- 文件选择 / 拖拽 ----------------
    def _on_file_select(self):
        self._vt_heal_stale()
        desktop_path = QStandardPaths.writableLocation(QStandardPaths.DesktopLocation)
        file_path, _ = QFileDialog.getOpenFileName(
            self, self.tr("选择媒体文件"), desktop_path, self._media_filter())
        if file_path:
            self.update_info(file_path)

    def _media_filter(self):
        ent = _seams.entities
        video_formats = " ".join(f"*.{f.value}" for f in ent.SupportedVideoFormats)
        audio_formats = " ".join(f"*.{f.value}" for f in ent.SupportedAudioFormats)
        return (f"{self.tr('媒体文件')} ({video_formats} {audio_formats});;"
                f"{self.tr('视频文件')} ({video_formats});;"
                f"{self.tr('音频文件')} ({audio_formats})")

    def update_info(self, file_path):
        # 连续拖入多个文件时 update_info 会被反复调用（拖放 / set_task 两条路径）。
        # 旧实现直接覆盖 self.video_info_thread：上一个线程失去唯一引用却被 Qt
        # 内部持有，仍在跑的同时脱离管理；其 finished 仍连到
        # video_info_card.update_info，晚到的旧结果会把新文件的画面信息覆盖掉。
        # 这里先让旧线程收尾（断开信号 → 等它自己结束），再启动新的。
        self._stop_video_info_thread()
        self.video_info_thread = _seams.threads.VideoInfoThread(file_path)
        self.video_info_thread.finished.connect(self.video_info_card.update_info)
        self.video_info_thread.error.connect(self._on_video_info_error)
        self.video_info_thread.start()

    def _stop_video_info_thread(self):
        """停掉在跑的探测线程并断开信号；任何异常都不影响后续启动。"""
        th = getattr(self, "video_info_thread", None)
        if th is None:
            return
        try:
            for sig in ("finished", "error"):
                try:
                    getattr(th, sig).disconnect()
                except (RuntimeError, TypeError):
                    pass        # 未连接 / 对象已删
            if th.isRunning():
                th.quit()
                # 探测含 ffprobe + 截帧，给足收尾时间；超时也不阻塞界面
                if not th.wait(2000):
                    th.terminate()
                    th.wait(500)
        except Exception:       # noqa: BLE001
            pass
        finally:
            self.video_info_thread = None

    def _on_video_info_error(self, error_msg):
        self.is_processing = False
        InfoBar.error(
            self.tr("错误"), self.tr(error_msg),
            duration=_seams.constants.INFOBAR_DURATION_ERROR, parent=self)

    def set_task(self, task) -> None:
        self.task = task
        self.video_info_card.set_task(self.task)
        self.update_info(self.task.file_path)

    def process(self):
        self.is_processing = True
        self.video_info_card.start_transcription(need_create_task=False)

    def dragEnterEvent(self, event):
        event.accept() if event.mimeData().hasUrls() else event.ignore()

    def dropEvent(self, event):
        self._vt_heal_stale()
        if self.is_processing:
            InfoBar.warning(
                self.tr("警告"), self.tr("正在处理中，请等待当前任务完成"),
                duration=_seams.constants.INFOBAR_DURATION_WARNING, parent=self)
            return
        ent = _seams.entities
        supported = ({f.value for f in ent.SupportedVideoFormats}
                     | {f.value for f in ent.SupportedAudioFormats})
        files = [u.toLocalFile() for u in event.mimeData().urls()]
        for file_path in files:
            if not os.path.isfile(file_path):
                continue
            file_ext = os.path.splitext(file_path)[1][1:].lower()
            if file_ext in supported:
                self.update_info(file_path)
                InfoBar.success(
                    self.tr("导入成功"), self.tr("开始语音转文字"),
                    duration=_seams.constants.INFOBAR_DURATION_SUCCESS, parent=self)
                break
            else:
                InfoBar.error(
                    self.tr("格式错误") + file_ext, self.tr("请拖入音频或视频文件"),
                    duration=_seams.constants.INFOBAR_DURATION_ERROR, parent=self)

    def closeEvent(self, event):
        try:
            self.video_info_card.stop()
        except Exception:  # noqa: BLE001
            pass
        super().closeEvent(event)
