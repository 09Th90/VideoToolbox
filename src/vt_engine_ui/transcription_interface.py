# -*- coding: utf-8 -*-
# @version 3.2.5
"""自研「语音转录」页（含 ``VideoInfoCard``）。

视觉与引擎转录页对齐；把原本运行期打在引擎类上的转录补丁**内建为显式逻辑**：

  ① 命令栏转录模型下拉只建「本地 / 云端」两项（2026-11-22 起不再有「默认」）；
  ② 选「本地」→ ``asr_mode=local`` + 引擎切 FasterWhisper（模型名/目录一并写入），
     选「云端」→ ``asr_mode=service`` + 引擎切 Whisper [API]（地址/密钥/模型一并
     写入）——**点哪项就真正切到哪套后端**；切换后当场体检（缺权重 / 缺密钥直接
     提示），启动恢复/广播按已保存模式对齐并回写；``_vt_model_busy`` 截断 cfg
     信号环路；
  ③ 独立转录（``need_next_task=False``）完成后把产物字幕装载进「字幕翻译」并切
     过去；入口先无条件复位 ``is_processing``；``_home_of`` 沿 parent 链上溯（Qt
     会把子界面重挂到 QStackedWidget，故不能只用 ``parent()``）；``_produced_subtitle``
     按同基名补齐真实后缀；
  ⑥ 启用了声纹则先后台 ``QThread`` 筛选、筛完再回填（顺序不可反；worker 挂实例
     防 GC）；
  ③-B 陈旧「处理中」自愈：``dropEvent`` / ``_on_file_select`` 前，若标记为真但无
     运行中的转录线程，则清标记并复位卡片按钮，再照常放行。

对外契约（``command_bar`` / ``model_button`` / ``model_menu`` / ``asr_lang_button``
/ ``asr_lang_menu`` / ``output_format_button`` / ``output_format_menu``
/ ``video_info_card`` / ``transcription_setting_card`` / ``is_processing``
/ ``finished`` / ``set_task`` / ``process`` / ``dropEvent`` / ``_on_file_select``
/ ``_on_transcript_finished`` / ``on_transcription_model_changed``
/ ``on_asr_language_changed`` / ``on_output_format_changed``
/ ``_setup_command_bar``）与引擎同名同义。
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
    SwitchButton,
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

    def _ensure_asr_selected(self) -> bool:
        """建任务前把「本地 / 云端」选定模式真正落到引擎，并确认它可用。

        以前这里负责「停在默认就自动切 ASR」；下拉拆成本地/云端后不再需要自动
        切换，但**必须**在转码前两道闸一起过：
          ① 按当前选择重新注入引擎转录配置（防止引擎里残留另一套模型——
             例如刚从设置页改过、或被历史任务带偏）；
          ② 模式未配置完整就中止并引导（本地缺权重 / 云端缺地址密钥）。
        否则要等整条音频转完才炸（2026-11-19 第三方反馈的 412 长跑问题同源）。

        返回 ``False`` 表示当前模式不可用——调用方应中止并引导去配置。
        """
        try:
            ui = self.transcription_interface
            mode = ui.current_asr_mode()
            ok, _detail = _seams.set_asr_mode(mode)
            try:
                ui._refresh_model_tooltip()
            except Exception:  # noqa: BLE001
                pass
            st = _seams.asr_mode_status(mode)
            if st.get("ready"):
                return True
            bar = InfoBar.warning(
                self.tr("「%s」还没配置完整") % ui.model_button.text(),
                str(st.get("hint") or "请到 设置 → ASR 语音识别 配置后点「保存并应用」"),
                duration=-1,
                parent=self.parent().parent())
            try:
                btn = PushButton(self.tr("去配置 ASR"))
                btn.clicked.connect(self._goto_asr_settings)
                bar.addWidget(btn)
            except Exception:  # noqa: BLE001
                pass
            return False
        except Exception as e:  # noqa: BLE001
            _seams.vc_log(f"ASR 模式校验失败：{e}")
            return True

    def start_transcription(self, need_create_task=True):
        self.transcription_interface.is_processing = True
        self.start_button.setEnabled(False)
        if need_create_task:
            if not self._ensure_asr_selected():
                # 前置拦截：未配置 ASR 时不建任务（必剪必失败，白等转码）
                self.transcription_interface.is_processing = False
                self.start_button.setEnabled(True)
                self.start_button.setText(self.tr("开始转录"))
                self.progress_ring.hide()
                return
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

    #: 失败文本命中这些特征时，说明「改配 ASR」就是下一步动作（B/J 失效、
    #: 本地模型缺权重/枚举崩溃、服务配置错误），错误条额外挂直达按钮。
    _ASR_FIX_HINTS = ("必剪", "剪映", "bcut", "412", "faster-whisper",
                      "faster_whisper", "'str' object", "转录服务",
                      "ASR", "Whisper", "模型")

    def on_transcript_error(self, error):
        self.transcription_interface.is_processing = False
        self.start_button.setEnabled(True)
        self.start_button.setText(self.tr("重新转录"))
        self.progress_ring.hide()
        text = str(error or "")
        _low = text.lower()
        fixable = any(k.lower() in _low for k in self._ASR_FIX_HINTS)
        bar = InfoBar.error(
            self.tr("转录失败"), self.tr(text),
            # 带操作按钮时常驻，给用户足够时间点击；纯提示保持原时长
            duration=(-1 if fixable
                      else _seams.constants.INFOBAR_DURATION_ERROR),
            parent=self.parent().parent())
        if fixable:
            try:
                btn = PushButton(self.tr("去配置 ASR"))

                def _go():
                    try:
                        bar.close()
                    except Exception:  # noqa: BLE001
                        pass
                    self._goto_asr_settings()

                btn.clicked.connect(_go)
                bar.addWidget(btn)
            except Exception as e:  # noqa: BLE001
                _seams.vc_log(f"转录失败提示按钮挂载失败：{e}")

    def _goto_asr_settings(self):
        """跳到设置页「ASR 语音识别」卡片（失败提示条按钮与引导文案共用）。"""
        try:
            win = self.window()
            fn = getattr(win, "open_asr_settings", None)
            if callable(fn):
                fn()
                return
            sp = getattr(win, "settings_page", None)
            if sp is not None and hasattr(win, "switchTo"):
                win.switchTo(sp)
        except Exception as e:  # noqa: BLE001
            _seams.vc_log(f"跳转 ASR 设置失败：{e}")

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

    #: 识别语言下拉（2026-10-25 从设置页迁来）：与引擎 TranscribeLanguageEnum
    #: 逐字对齐的常用子集。**新增项必须先在引擎枚举里存在**——写进 settings.json
    #: 的标签解析不了会静默回落默认值；自检 _selftest_asr_language.py 钉住
    #: 「本表 ⊆ 引擎枚举」。
    ASR_LANG_LABELS = ("自动检测", "中文", "英语", "日本語", "韩语", "粤语",
                       "法语", "德语", "西班牙语", "俄语", "葡萄牙语",
                       "土耳其语", "Italian", "Polish", "Dutch", "Arabic",
                       "Indonesian", "Thai", "Vietnamese")

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

        # 下拉只有「本地 / 云端」两档（2026-11-22）：本地 = 电脑里的
        # faster-whisper 模型（离线），云端 = 设置页填的服务商接口。
        # 点哪项就写 asr_mode 并注入引擎转录配置，不是只改文字。
        self.model_menu = RoundMenu(parent=self)
        self.model_menu.addActions([
            Action(FluentIcon.IOT, _seams.TM_DISPLAY_LOCAL),
            Action(FluentIcon.GLOBE, _seams.TM_DISPLAY_CLOUD),
        ])
        self.model_button.setMenu(self.model_menu)
        self.command_bar.addWidget(self.model_button)

        # 识别语言（2026-10-25 从 设置 → ASR 语音识别 迁来）：随选随用，
        # 保存 ai_config（任务创建时的覆盖来源）+ 直接写引擎语言（输出文件名 /
        # 引擎内存态），不走 apply_asr_to_engine——那会把转录模型强制切成 ASR。
        saved_lang = self._saved_language()
        self.asr_lang_menu = RoundMenu(parent=self)
        self.asr_lang_menu.setMaxVisibleItems(10)
        _langs = list(self.ASR_LANG_LABELS)
        if saved_lang not in _langs:
            # 历史上存过下拉之外的标签（更早版本 / 手改配置）：插回列表，
            # 保证按钮显示的就是真值。
            _langs.insert(1, saved_lang)
        for label in _langs:
            action = Action(label)
            action.triggered.connect(
                lambda checked=False, value=label:
                self.on_asr_language_changed(value))
            self.asr_lang_menu.addAction(action)

        self.asr_lang_button = TransparentDropDownPushButton(
            self.tr("语言：") + saved_lang, self, FluentIcon.LANGUAGE)
        self.asr_lang_button.setFixedHeight(34)
        self.asr_lang_button.setMinimumWidth(180)
        self.asr_lang_button.setToolTip(
            "音视频中说话的语言，下一次转录生效。\n"
            "· 自动检测（默认）：交给识别端按内容自行判断，并把引擎语言复位为自动；\n"
            "· 指定语言：多语言混夹 / 短片段素材上更准，但**选错会明显拉低识别率**；\n"
            "· 没有把握就留「自动检测」。")
        self.asr_lang_button.setMenu(self.asr_lang_menu)
        self.command_bar.addWidget(self.asr_lang_button)

        # 输出格式（2026-10-25 从齿轮弹窗迁来）：写引擎配置，下一次转录生效。
        self.output_format_menu = RoundMenu(parent=self)
        for fmt in _seams.entities.TranscribeOutputFormatEnum:
            action = Action(fmt.value)
            action.triggered.connect(
                lambda checked=False, value=fmt:
                self.on_output_format_changed(value))
            self.output_format_menu.addAction(action)

        self.output_format_button = TransparentDropDownPushButton(
            self.tr("格式：") + self._current_output_format(),
            self, FluentIcon.SAVE)
        self.output_format_button.setFixedHeight(34)
        self.output_format_button.setMinimumWidth(110)
        self.output_format_button.setToolTip(
            "转录字幕的输出格式，下一次转录生效。\n"
            "TXT 只导出纯文本，不会自动装载到「字幕翻译」。")
        self.output_format_button.setMenu(self.output_format_menu)
        self.command_bar.addWidget(self.output_format_button)

        self.command_bar.addSeparator()
        gear = Action(FluentIcon.SETTING, "",
                      triggered=self._show_voiceprint_settings)
        gear.setToolTip(self.tr("声纹设置"))
        self.command_bar.addAction(gear)
        self._mount_vp_auto_switch()
        self.main_layout.addWidget(self.command_bar)

    def _mount_vp_auto_switch(self):
        """命令栏的「声纹筛选」开关（**默认关**）——本次任务要不要筛。

        `selection.enabled`（齿轮里勾选的名单）从此只回答「筛谁」，不再单独
        构成自动执行的理由：2026-11-03 一份 3856 条的日语片被 10-30 残留的
        陌生声纹筛到只剩 22 条，就是因为没有这一层。与引擎补丁
        `core/asr/ui_patch.py` 对称挂载（`vt_ui_golden` 逐节点比对）。
        """
        try:
            sw = SwitchButton(self.tr("声纹筛选"), self.command_bar)
            sw.setChecked(_seams.voiceprint_auto_filter_enabled())
            sw.setToolTip(_seams.voiceprint_auto_tooltip())
            sw.setFixedHeight(34)
            sw.checkedChanged.connect(self._on_vp_auto_changed)
            self.command_bar.addWidget(sw)
            self.vp_auto_switch = sw
        except Exception as e:  # noqa: BLE001
            _seams.vc_log(f"转录页声纹开关挂载失败：{e}")

    def _on_vp_auto_changed(self, checked=False):
        """开关落盘 + 刷新文案；不弹 InfoBar（用户刚点完，无需确认音）。"""
        sw = getattr(self, "vp_auto_switch", None)
        try:
            _seams.voiceprint_set_auto_filter(
                bool(sw.isChecked()) if sw is not None else bool(checked))
            if sw is not None:
                sw.setToolTip(_seams.voiceprint_auto_tooltip())
            _seams.vc_log("用户%s转录页「声纹筛选」开关"
                          % ("打开" if (sw is not None and sw.isChecked())
                             else "关闭"))
        except Exception as e:  # noqa: BLE001
            _seams.vc_log(f"声纹自动筛选开关写入失败：{e}")

    def refresh_vp_auto_switch(self):
        """齿轮弹窗关掉后同步一次：勾选变了，开关文案里的名单也要跟着变。"""
        sw = getattr(self, "vp_auto_switch", None)
        if sw is None:
            return
        try:
            sw.blockSignals(True)
            sw.setChecked(_seams.voiceprint_auto_filter_enabled())
            sw.setToolTip(_seams.voiceprint_auto_tooltip())
            sw.blockSignals(False)
        except Exception as e:  # noqa: BLE001
            sw.blockSignals(False)
            _seams.vc_log(f"声纹开关状态刷新失败：{e}")

    def _show_voiceprint_settings(self):
        dialog = TranscriptionSettingDialog(self.window())
        dialog.exec_()
        self.refresh_vp_auto_switch()

    def _setup_signals(self) -> None:
        self.video_info_card.finished.connect(self._on_transcript_finished)
        for action in self.model_menu.actions():
            action.triggered.connect(
                lambda checked, text=action.text():
                self.on_transcription_model_changed(text))
        _seams.signal_bus.transcription_model_changed.connect(
            self.on_transcription_model_changed)

    def _show_voiceprint_settings(self):
        dialog = TranscriptionSettingDialog(self.window())
        dialog.exec_()

    def _set_value(self) -> None:
        model_name = _seams.cfg.get(_seams.cfg.transcribe_model).value
        self.on_transcription_model_changed(model_name)
        self._sync_engine_language()

    # ---------------- 识别语言 / 输出格式（2026-10-25） ----------------
    def _saved_language(self) -> str:
        try:
            label = str(
                _seams.ai_load_config().get("asr_language") or "").strip()
        except Exception:  # noqa: BLE001
            label = ""
        return label or "自动检测"

    def _current_output_format(self) -> str:
        try:
            fmt = _seams.cfg.get(_seams.cfg.transcribe_output_format)
            return getattr(fmt, "value", str(fmt))
        except Exception:  # noqa: BLE001
            return "SRT"

    def _sync_engine_language(self) -> None:
        """把 ai_config 里的显式语言对齐进引擎配置。

        只补显式语言，不在启动时把「自动检测」强写回引擎——后者可能覆盖
        用户在引擎/命令行里手动设过的取值。用户主动点「自动检测」时才复位。
        """
        label = self._saved_language()
        if label == "自动检测":
            return
        try:
            lang = _seams.entities.TranscribeLanguageEnum(label)
            if _seams.cfg.get(_seams.cfg.transcribe_language) != lang:
                _seams.cfg.set(_seams.cfg.transcribe_language, lang)
        except Exception as e:  # noqa: BLE001
            _seams.vc_log(f"识别语言对齐引擎失败（{label}）：{e}")

    def on_asr_language_changed(self, label: str) -> None:
        label = str(label or "").strip() or "自动检测"
        try:
            cfg = dict(_seams.ai_load_config())
            cfg["asr_language"] = label
            # 必须传完整配置：save_config 是整 dict 覆写，残缺 dict 会清空其余项。
            _seams.ai_mod().save_config(cfg)
        except Exception as e:  # noqa: BLE001
            InfoBar.error(
                self.tr("识别语言未保存"), str(e)[:300],
                duration=_seams.constants.INFOBAR_DURATION_ERROR,
                parent=self.window())
            self.asr_lang_button.setText(
                self.tr("语言：") + self._saved_language())
            return

        # ⚠ 不能走 apply_asr_to_engine：它会把 TranscribeModel 强制切成
        # WhisperAPI / FasterWhisper，用户停在「默认」时会被悄悄切走。
        try:
            _seams.cfg.set(
                _seams.cfg.transcribe_language,
                _seams.entities.TranscribeLanguageEnum(label))
        except Exception as e:  # noqa: BLE001
            _seams.vc_log(f"识别语言写入引擎配置失败（{label}）：{e}")
            if label == "自动检测":
                InfoBar.warning(
                    self.tr("语言未完全生效"),
                    self.tr("已保存「自动检测」，但引擎语言复位失败；"
                            "请到设置页「ASR 语音识别」保存一次配置"),
                    duration=_seams.constants.INFOBAR_DURATION_WARNING,
                    parent=self.window())
        self.asr_lang_button.setText(self.tr("语言：") + label)

    def on_output_format_changed(self, fmt) -> None:
        try:
            _seams.cfg.set(_seams.cfg.transcribe_output_format, fmt)
        except Exception as e:  # noqa: BLE001
            InfoBar.error(
                self.tr("输出格式未保存"), str(e)[:300],
                duration=_seams.constants.INFOBAR_DURATION_ERROR,
                parent=self.window())
            self.output_format_button.setText(
                self.tr("格式：") + self._current_output_format())
            return
        self.output_format_button.setText(
            self.tr("格式：") + getattr(fmt, "value", str(fmt)))

    # ---------------- 显示名 ↔ ASR 模式（本地 / 云端） ----------------
    def current_asr_mode(self) -> str:
        """当前下拉代表的模式：``local`` / ``service``。"""
        try:
            return ("local" if self.model_button.text()
                    == _seams.TM_DISPLAY_LOCAL else "service")
        except Exception:  # noqa: BLE001
            return _seams.asr_mode_of()

    def _refresh_model_tooltip(self):
        """按钮 tooltip 显示**真正**在用的模型/端点 + 未配置时的缺项。"""
        try:
            st = _seams.asr_mode_status(self.current_asr_mode())
            tip = "转录模型：%s\n%s" % (
                self.model_button.text(), st.get("detail") or "")
            if not st.get("ready") and st.get("hint"):
                tip += "\n⚠ " + st["hint"]
            self.model_button.setToolTip(tip)
        except Exception:  # noqa: BLE001
            pass

    def on_transcription_model_changed(self, model_name: str):
        if self._vt_model_busy:
            return
        ent = _seams.entities
        TM_LOCAL = _seams.TM_DISPLAY_LOCAL
        TM_CLOUD = _seams.TM_DISPLAY_CLOUD
        try:
            model_name = getattr(model_name, "value", model_name)
            # ① 用户点了「本地 / 云端」：写 asr_mode + 注入引擎转录配置（真正生效）
            if model_name in (TM_LOCAL, TM_CLOUD):
                mode = "local" if model_name == TM_LOCAL else "service"
                self._vt_model_busy = True
                try:
                    self.model_button.setText(model_name)
                    self.transcription_setting_card.on_model_changed(model_name)
                    ok, detail = _seams.set_asr_mode(mode)
                    self._refresh_model_tooltip()
                    st = _seams.asr_mode_status(mode)
                    if not ok:
                        InfoBar.error(
                            "转录模型切换失败",
                            ("%s；" % detail if detail else "")
                            + "引擎「转录配置」可能仍是旧模型，"
                              "请到 设置 → ASR 语音识别 点「保存并应用」",
                            duration=_seams.constants.INFOBAR_DURATION_ERROR,
                            parent=self.window())
                    elif not st.get("ready"):
                        InfoBar.warning(
                            "「%s」还没配置完整" % model_name,
                            st.get("hint")
                            or "请到 设置 → ASR 语音识别 配置后点「保存并应用」",
                            duration=8000, parent=self.window())
                    else:
                        InfoBar.success(
                            "已切换到「%s」" % model_name,
                            st.get("detail") or detail or "",
                            duration=_seams.constants.INFOBAR_DURATION_SUCCESS,
                            parent=self.window())
                finally:
                    self._vt_model_busy = False
                return

            # ② 启动恢复 / signalBus 广播（传引擎枚举值）：以**已保存的模式**为准，
            #    并顺手把引擎配置对齐（有差异才写盘），保证按钮显示=实际使用。
            mode = (_seams.asr_mode_of()
                    if model_name not in (ent.TranscribeModelEnum.WHISPER_API.value,
                                          ent.TranscribeModelEnum.FASTER_WHISPER.value)
                    else ("local" if model_name
                          == ent.TranscribeModelEnum.FASTER_WHISPER.value
                          else "service"))
            label = TM_LOCAL if mode == "local" else TM_CLOUD
            self.model_button.setText(label)
            self.transcription_setting_card.on_model_changed(label)
            # 顺手把 ai_config 的 asr_mode 与引擎现状对齐（一致时不写盘）。
            # 设置页「转录模型」下拉变动也会广播到这里，等于第二控制面同样
            # 真正生效，不会出现「界面云端、配置本地」的隐形分叉。
            try:
                self._vt_model_busy = True
                try:
                    ok, detail = _seams.set_asr_mode(mode)
                    if not ok:
                        _seams.vc_log(f"启动期对齐 ASR 转录配置失败：{detail}")
                finally:
                    self._vt_model_busy = False
            except Exception as e:  # noqa: BLE001
                _seams.vc_log(f"启动期对齐 ASR 转录配置异常：{e}")
            self._refresh_model_tooltip()
        except Exception as e:  # noqa: BLE001
            self._vt_model_busy = False
            _seams.vc_log(f"转录模型切换异常：{e}")

    def _asr_not_ready(self) -> bool:
        try:
            return not _seams.asr_mode_status(self.current_asr_mode()).get("ready")
        except Exception:  # noqa: BLE001
            return False

    def _asr_missing_hint(self) -> str:
        try:
            return _seams.asr_mode_status(
                self.current_asr_mode()).get("hint") or ""
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

    def _start_voiceprint_filter(self, iface, out, media, then, names=None) -> bool:
        """后台筛选，完成后回调 `then()`。

        `names`：自动路径传挂载点过完门禁的那一份名单（转录这几十秒里用户可能
        改了勾选）；省略＝按已启用名单筛（手动「按声纹筛选」按钮）。
        """
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
                    r = _seams.voiceprint_filter_subtitle(out, media,
                                                          names=names)
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
                # 文案与判定（含**熔断未覆盖**态）统一取 core 层，四处入口共用
                kind, title, content, ms = _seams.voiceprint_result_notice(res)
                getattr(InfoBar, kind)(title, content, duration=ms,
                                       position=InfoBarPosition.BOTTOM,
                                       parent=parent)
            except Exception:  # noqa: BLE001
                pass
            # 熔断也照样回填：成品没被改动，全文正是用户要的东西
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
                    # 纯音乐/无人声的片子转录出来是空 srt，`_produced_subtitle`
                    # 只看文件存在就照样弹「已装载」——表格 0 行配上成功提示，
                    # 用户读到的是「渲染坏了」。判据用装载后的模型条目数。
                    if not getattr(sub.model, "_data", None):
                        _seams.vc_log(f"独立转录完成 → 字幕为空，无可装载内容：{out}")
                        InfoBar.warning(
                            "转录完成",
                            "未识别到任何语音内容，生成的字幕为空（0 条）",
                            duration=5000, position=InfoBarPosition.BOTTOM, parent=home)
                        return True
                    _seams.vc_log(f"独立转录完成 → 已装载「字幕翻译」：{out}")
                    InfoBar.success(
                        "转录完成",
                        "生成的字幕已装载到「字幕翻译」，可直接开始优化 / 翻译",
                        duration=5000, position=InfoBarPosition.BOTTOM, parent=home)
                    return True

                # 门禁 = 转录页「声纹筛选」开关 ∧ 已启用名单；只看名单等于
                # 「某次勾过就永久自动筛」（2026-11-03 误杀 3834/3856 条）
                vp_names = _seams.voiceprint_auto_names() if out else []
                if vp_names:
                    if self._start_voiceprint_filter(self, out, media, _handoff,
                                                    vp_names):
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
        # 事前把「这次转录完会按声纹筛」说出来：以前这件事是静默发生的（只看
        # 一份跨会话残留的全局名单），用户根本不知道字幕会被就地改写。
        try:
            vp_names = _seams.voiceprint_auto_names()
            if vp_names:
                InfoBar.info(
                    "转录完成后将按声纹筛选",
                    "按「%s」保留其台词（转录页「声纹筛选」开关可关）"
                    % "、".join(vp_names),
                    duration=4000, position=InfoBarPosition.BOTTOM, parent=self)
        except Exception as e:  # noqa: BLE001
            _seams.vc_log(f"声纹筛选事前提示未发：{e}")
        self.is_processing = True
        # 与「开始转录」同一道前置闸：本入口的 task 是上游（首页/拖入）创建的，
        # 界面切换「本地 / 云端」**不会**改它。所以：
        #   · 当前模式未配置完整 → 中止并引导（本地缺权重 / 云端缺密钥）；
        #   · 模式可用但 task 里带的还是另一套模型（上游建任务后用户在转录页
        #     改过选择）→ 重建 task，保证真正跑的模型与按钮一致。
        if not self.video_info_card._ensure_asr_selected():
            self.is_processing = False
            self.video_info_card.reset_ui()
            return
        try:
            ent = _seams.entities
            want = (ent.TranscribeModelEnum.FASTER_WHISPER
                    if self.current_asr_mode() == "local"
                    else ent.TranscribeModelEnum.WHISPER_API)
            cur = getattr(getattr(self.task, "transcribe_config", None),
                          "transcribe_model", None)
            if self.task is not None and getattr(cur, "value", cur) != want.value:
                old = self.task
                new = _seams.TaskFactory.create_transcribe_task(
                    old.file_path,
                    need_next_task=bool(getattr(old, "need_next_task", False)),
                    task_id=getattr(old, "task_id", None))
                new.selected_audio_track_index = getattr(
                    old, "selected_audio_track_index", 0)
                self.set_task(new)
        except Exception as e:  # noqa: BLE001 - 重建失败不阻断（旧 task 仍可跑）
            _seams.vc_log(f"按当前 ASR 模式重建转录任务失败：{e}")
        self.video_info_card.start_transcription(need_create_task=False)

    def dragEnterEvent(self, event):
        event.accept() if event.mimeData().hasUrls() else event.ignore()

    def dropEvent(self, event):
        files = [u.toLocalFile() for u in event.mimeData().urls()]
        self.import_dropped_files(files)

    def import_dropped_files(self, files):
        """按路径导入（页内拖放与主窗口全局兜底分派共用同一条路径）。

        全局分派在「语音转录分段在前台」时调这里：拖到分段边缘/导航条等
        本控件矩形之外的位置，行为与拖在页内完全一致——就地载入待转录，
        不跳「字幕编辑」。返回 True = 已消费（含处理中拦截/格式错误提示）。
        """
        self._vt_heal_stale()
        if self.is_processing:
            InfoBar.warning(
                self.tr("警告"), self.tr("正在处理中，请等待当前任务完成"),
                duration=_seams.constants.INFOBAR_DURATION_WARNING, parent=self)
            return True
        ent = _seams.entities
        supported = ({f.value for f in ent.SupportedVideoFormats}
                     | {f.value for f in ent.SupportedAudioFormats})
        consumed = False
        for file_path in files:
            if not os.path.isfile(file_path):
                continue
            consumed = True
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
        return consumed

    def closeEvent(self, event):
        try:
            self.video_info_card.stop()
        except Exception:  # noqa: BLE001
            pass
        super().closeEvent(event)
