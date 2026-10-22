# -*- coding: utf-8 -*-
# @version 2.5.4
"""自研「任务创建」页。

视觉与行为对齐既有引擎工作台的任务创建页，并把原本运行期打上的两处补丁
**内建为显式逻辑**（不再 monkey-patch）：

  · 品牌中性化（原 ``_patch_task_creation``）：隐藏品牌 logo、移除独立窗口
    时代遗留的 ≥100px 大留白、``setSpacing(18)`` + 顶部 ``insertSpacing(0, 24)``；
  · 字幕接收（原 ``make_task_creation_drop_handler``）：``dropEvent`` 额外接受
    字幕文件——命中字幕就地收下并提示，其余一律走原「媒体文件」逻辑。

对外暴露的属性/信号（``search_input`` / ``status_label`` / ``info_label`` /
``donate_button`` / ``logo_label`` / ``main_layout`` / ``finished`` / ``url_detected``
/ ``ai_requested`` / ``dropEvent`` / ``setup_ui``）与引擎同名同义，宿主的实例级
整形与拖放分派因此无需改动。
"""
from __future__ import annotations

import os
from urllib.parse import urlparse

from PySide6.QtCore import QStandardPaths, Qt, QTimer, Signal
from PySide6.QtGui import QPixmap, QTextCursor
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)
from vt_fluent import (
    BodyLabel,
    FluentIcon,
    FluentStyleSheet,
    HyperlinkButton,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    ProgressBar,
    PushButton,
    TextEdit,
    ToolButton,
    isDarkTheme,
)

from . import _seams

# 字幕扩展名（与宿主 video_toolbox_qt.SUBTITLE_EXTS 一致）
SUBTITLE_EXTS = {".srt", ".ass", ".ssa", ".vtt", ".sub", ".smi", ".sbv", ".lrc"}


def _harness_ready() -> bool:
    """harness（AI 托管引擎）是否部署就绪。

    惰性 import + 全异常兜底：harness_bridge 只依赖标准库，但即便它因任何
    原因导入失败，这里也只返回 False——任务创建页的行为与从前完全一致。
    """
    try:
        import harness_bridge
        return harness_bridge.available()
    except Exception:  # noqa: BLE001
        return False


class LogWindow(QWidget):
    """日志查看器（对齐引擎 ui.view.log_window，自研实现）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("日志查看器")
        self.resize(800, 600)

        FluentStyleSheet.FLUENT_WINDOW.apply(self)
        self._apply_qss()

        self.setWindowModality(Qt.NonModal)
        self.setWindowFlags(
            Qt.Window | Qt.WindowCloseButtonHint | Qt.WindowMinMaxButtonsHint
        )

        layout = QVBoxLayout(self)
        top_layout = QHBoxLayout()
        self.open_folder_btn = PushButton("打开日志文件夹", self)
        self.open_folder_btn.clicked.connect(self.open_log_folder)
        top_layout.addWidget(self.open_folder_btn)
        top_layout.addStretch()
        layout.addLayout(top_layout)

        self.log_text = TextEdit(self)
        self.log_text.setReadOnly(True)
        layout.addWidget(self.log_text)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_log)
        self.timer.start(500)

        self.log_path = self._log_file_path()
        self.log_file = None
        self.last_position = 0
        self.max_lines = 100
        self.auto_scroll = True
        try:
            self.log_file = open(self.log_path, "r", encoding="utf-8")
            self.load_last_lines(20480)
            self.log_text.moveCursor(QTextCursor.End)
            self.log_text.insertPlainText(
                f"\n{'=' * 25}以上是历史日志{'=' * 25}\n\n")
            self.last_position = self.log_file.tell()
        except Exception as e:  # noqa: BLE001
            self.log_file = None
            self.log_text.setPlainText(f"打开日志文件失败: {str(e)}")

        self.log_text.verticalScrollBar().valueChanged.connect(self.on_scroll_changed)

    def _apply_qss(self):
        try:
            vcc = _seams.vc_config
            theme = "dark" if isDarkTheme() else "light"
            qss = vcc.RESOURCE_PATH / "assets" / "qss" / theme / "demo.qss"
            with open(qss, encoding="utf-8") as f:
                self.setStyleSheet(f.read())
        except Exception:  # noqa: BLE001
            pass

    def _log_file_path(self):
        try:
            return str(_seams.vc_config.LOG_PATH / "app.log")
        except Exception:  # noqa: BLE001
            return "app.log"

    def load_last_lines(self, read_size):
        try:
            self.log_file.seek(0, 2)
            file_size = self.log_file.tell()
            read_size = min(read_size, file_size)
            self.log_file.seek(0)
            content = self.log_file.read()
            if len(content) > read_size:
                content = content[-read_size:]
                newline_pos = content.find("\n")
                if newline_pos != -1:
                    content = content[newline_pos + 1:]
            self.last_position = self.log_file.tell()
            self.log_text.moveCursor(QTextCursor.End)
            self.log_text.setPlainText(content)
            self.log_text.verticalScrollBar().setValue(
                self.log_text.verticalScrollBar().maximum())
        except Exception as e:  # noqa: BLE001
            self.log_text.setPlainText(f"读取日志文件失败: {str(e)}")

    def on_scroll_changed(self, value):
        scrollbar = self.log_text.verticalScrollBar()
        max_value = scrollbar.maximum()
        self.auto_scroll = max_value * 0.85 <= value <= max_value

    def update_log(self):
        if not self.log_file:
            return
        try:
            self.log_file.seek(self.last_position)
            new_content = self.log_file.read()
            if new_content:
                for line in new_content.splitlines(True):
                    self.log_text.moveCursor(QTextCursor.End)
                    self.log_text.insertPlainText(line)
                    self.log_text.repaint()
                self.last_position = self.log_file.tell()
                if self.auto_scroll:
                    self.log_text.verticalScrollBar().setValue(
                        self.log_text.verticalScrollBar().maximum())
        except Exception as e:  # noqa: BLE001
            self.log_text.setPlainText(f"读取日志文件出错: {str(e)}")

    def open_log_folder(self):
        try:
            _seams.platform_utils.reveal_in_explorer(str(self.log_path))
        except Exception:  # noqa: BLE001
            pass


class TaskCreationInterface(QWidget):
    """任务创建页（自研）。

    v2.1.0 起本页同时是**应用首页**（宿主把它从工作台分段里摘出来挂到
    导航第一项），所以除了「拖文件建任务」，还多了一件事：**识别网页链接
    并交给宿主的「视频下载」页**（见 ``url_detected`` 信号）。

    链接识别放宽到「用户真的那么粘」的程度——分享文案整段、漏协议头
    （``www.bilibili.com/...``）、带引号、结尾粘了中文标点都能认；判不准
    就当没有（弹原提示），绝不猜。
    """

    finished = Signal(str)
    #: 输入框里识别出一个网页链接。宿主（``video_toolbox_qt``）接它 →
    #: 跳到「视频处理 / 视频下载」并把链接填进去。**本页不再自己下载**：
    #: 宿主的下载页有画质选择 / 并行队列 / 中止 / 代理 / 字幕打包，
    #: 引擎那套 VideoDownloadThread 只有裸下一条，能力完全被覆盖。
    url_detected = Signal(str)
    #: v2.1.0：harness 就绪、且用户输入的是**纯文本**（不是文件也不是链接）
    #: 时不弹「格式错误」，改走 AI 托管（宿主接它 → 跳「AI 托管」页开跑）。
    #: harness 未部署时 :func:`process` 压根不会发这个信号，行为与从前一致。
    ai_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.task = None
        self.log_window = None

        self.setObjectName("TaskCreationInterface")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAcceptDrops(True)

        self.setup_ui()
        self.setup_values()
        self.setup_signals()

    # ---------------- UI 构建 ----------------
    def setup_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setObjectName("main_layout")
        self.main_layout.setSpacing(50)
        self.main_layout.addSpacing(120)
        self.setup_logo()
        self.setup_search_layout()
        self.setup_status_layout()
        self.setup_info_label()
        # 品牌中性化（内建，原 _patch_task_creation）：
        self._neutralize_brand()

    def _neutralize_brand(self):
        logo = getattr(self, "logo_label", None)
        if logo is not None:
            logo.hide()
        lay = getattr(self, "main_layout", None)
        if lay is not None:
            for i in reversed(range(lay.count())):
                item = lay.itemAt(i)
                spacer = item.spacerItem() if item is not None else None
                if spacer is not None and spacer.sizeHint().height() >= 100:
                    lay.removeItem(item)
            lay.setSpacing(18)
            lay.insertSpacing(0, 24)

    def setup_logo(self):
        self.logo_label = QLabel(self)
        try:
            logo_path = str(_seams.vc_config.ASSETS_PATH / "logo.png")
            pm = QPixmap(logo_path)
            if not pm.isNull():
                pm = pm.scaled(150, 150, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.logo_label.setPixmap(pm)
        except Exception:  # noqa: BLE001
            pass
        self.logo_label.setAlignment(Qt.AlignCenter)
        self.main_layout.addWidget(self.logo_label)
        self.main_layout.addSpacing(10)

    def setup_search_layout(self):
        self.search_layout = QHBoxLayout()
        self.search_layout.setContentsMargins(80, 0, 80, 0)
        self.search_input = LineEdit(self)
        self.search_input.setPlaceholderText(
            self.tr("请拖拽文件、粘贴视频链接，或输入要做的事（AI 托管）")
            if _harness_ready()
            else self.tr("请拖拽文件，或粘贴视频链接（自动识别整段分享文案）"))
        self.search_input.setFixedHeight(40)
        self.search_input.setClearButtonEnabled(True)
        self.search_input.focusOutEvent = lambda e: super(
            LineEdit, self.search_input).focusOutEvent(e)
        self.search_input.paintEvent = lambda e: super(
            LineEdit, self.search_input).paintEvent(e)
        self.search_input.setStyleSheet(
            self.search_input.styleSheet()
            + """
            QLineEdit {
                border-radius: 18px;
                padding: 0 20px;
                background-color: transparent;
                border: 1px solid rgba(255,255, 255, 0.08);
            }
            QLineEdit:focus[transparent=true] {
                border: 1px solid rgba(47,141, 99, 0.48);
            }

        """)
        self.start_button = ToolButton(FluentIcon.FOLDER, self)
        self.start_button.setFixedSize(40, 40)
        self.start_button.setStyleSheet(
            self.start_button.styleSheet()
            + """
            QToolButton {
                border-radius: 20px;
                background-color: #2F8D63;
            }
            QToolButton:hover {
                background-color: #2E805C;
            }
            QToolButton:pressed {
                background-color: #2E905C;
            }
        """)
        self.search_layout.addWidget(self.search_input)
        self.search_layout.addWidget(self.start_button)
        self.search_layout.setSpacing(10)
        self.main_layout.addLayout(self.search_layout)
        self.main_layout.addSpacing(100)

    def setup_status_layout(self):
        self.status_layout = QVBoxLayout()
        self.status_layout.setContentsMargins(50, 0, 30, 5)
        self.status_layout.setAlignment(Qt.AlignBottom | Qt.AlignHCenter)
        self.status_label = BodyLabel(self.tr("准备就绪"), self)
        self.status_label.setStyleSheet("font-size: 14px; color: #888888;")
        self.status_layout.addWidget(self.status_label, 0, Qt.AlignCenter)
        self.progress_bar = ProgressBar(self)
        self.status_label.hide()
        self.progress_bar.hide()
        self.progress_bar.setFixedWidth(300)
        self.status_layout.addWidget(self.progress_bar, 0, Qt.AlignCenter)

        self.main_layout.addStretch(1)
        self.main_layout.addLayout(self.status_layout)

    def setup_info_label(self):
        bottom_container = QWidget()
        bottom_layout = QHBoxLayout(bottom_container)
        bottom_layout.setContentsMargins(0, 0, 0, 0)

        self.log_button = HyperlinkButton(url="", text=self.tr("查看日志"), parent=self)
        self.log_button.setStyleSheet(
            self.log_button.styleSheet()
            + """
            QPushButton {
                font-size: 12px;
                color: #2F8D63;
                text-decoration: underline;
            }
        """)

        self.donate_button = HyperlinkButton(url="", text=self.tr("捐助"), parent=self)
        self.donate_button.setStyleSheet(
            self.donate_button.styleSheet()
            + """
            QPushButton {
                font-size: 12px;
                color: #2F8D63;
                text-decoration: underline;
            }
        """)

        try:
            version = _seams.vc_config.VERSION
        except Exception:  # noqa: BLE001
            version = ""
        self.info_label = BodyLabel(
            self.tr(f"©VideoCaptioner {version} • By Weifeng"), self)
        self.info_label.setAlignment(Qt.AlignCenter)
        self.info_label.setStyleSheet("font-size: 12px; color: #888888;")

        bottom_layout.addStretch()
        bottom_layout.addWidget(self.info_label)
        bottom_layout.addWidget(self.log_button)
        bottom_layout.addWidget(self.donate_button)
        bottom_layout.addStretch()

        self.main_layout.addStretch()
        self.main_layout.addWidget(bottom_container)

    def setup_signals(self):
        self.start_button.clicked.connect(self.on_start_clicked)
        self.search_input.textChanged.connect(self.on_search_input_changed)
        # 回车 = 点右侧按钮（输入框为空时回车等同「打开文件选择」，与按钮一致）
        self.search_input.returnPressed.connect(self.on_start_clicked)
        self.log_button.clicked.connect(self.show_log_window)
        self.donate_button.clicked.connect(self.show_donate_dialog)

    def setup_values(self):
        self.search_input.setText("")

    # ---------------- 交互 ----------------
    def _media_filter(self):
        ent = _seams.entities
        video_formats = " ".join(f"*.{f.value}" for f in ent.SupportedVideoFormats)
        audio_formats = " ".join(f"*.{f.value}" for f in ent.SupportedAudioFormats)
        return (f"{self.tr('媒体文件')} ({video_formats} {audio_formats});;"
                f"{self.tr('视频文件')} ({video_formats});;"
                f"{self.tr('音频文件')} ({audio_formats})")

    def on_start_clicked(self):
        if self.start_button._icon == FluentIcon.FOLDER:
            desktop_path = QStandardPaths.writableLocation(
                QStandardPaths.DesktopLocation)
            file_path, _ = QFileDialog.getOpenFileName(
                self, self.tr("选择媒体文件"), desktop_path, self._media_filter())
            if file_path:
                self.search_input.setText(file_path)
            return
        self.process()

    def on_search_input_changed(self):
        if self.search_input.text():
            self.start_button.setIcon(FluentIcon.PLAY)
        else:
            self.start_button.setIcon(FluentIcon.FOLDER)

    def dragEnterEvent(self, event):
        event.accept() if event.mimeData().hasUrls() else event.ignore()

    def dropEvent(self, event):
        files = [u.toLocalFile() for u in event.mimeData().urls()]
        # 字幕接收（内建，原 make_task_creation_drop_handler）：命中字幕就地收下
        subs = [p for p in files
                if p and os.path.isfile(p)
                and os.path.splitext(p)[1].lower() in SUBTITLE_EXTS]
        if subs:
            self.search_input.setText(subs[0])
            try:
                self.status_label.setText("导入成功")
                InfoBar.success(
                    "导入成功", "已导入字幕文件，点右侧按钮继续",
                    duration=3000, position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            except Exception:  # noqa: BLE001
                pass
            return
        self._drop_media(files)

    def _drop_media(self, files):
        ent = _seams.entities
        const = _seams.constants
        supported = ({f.value for f in ent.SupportedVideoFormats}
                     | {f.value for f in ent.SupportedAudioFormats})
        for file_path in files:
            if not os.path.isfile(file_path):
                continue
            file_ext = os.path.splitext(file_path)[1][1:].lower()
            if file_ext in supported:
                self.search_input.setText(file_path)
                self.status_label.setText(self.tr("导入成功"))
                InfoBar.success(
                    self.tr("导入成功"), self.tr("导入媒体文件成功"),
                    duration=const.INFOBAR_DURATION_SUCCESS, parent=self)
                break
            else:
                InfoBar.error(
                    self.tr("格式错误") + file_ext, self.tr("不支持该文件格式"),
                    duration=const.INFOBAR_DURATION_ERROR, parent=self)

    def _is_valid_url(self, url):
        try:
            result = urlparse(url)
            return result.scheme in ("http", "https") and bool(result.netloc)
        except ValueError:
            return False

    def create_task(self):
        self.process()

    def _process_file(self, file_path):
        self.finished.emit(file_path)

    def _process_url(self, url):
        """识别到网页链接 → 交给宿主跳「视频下载」（v2.1.0）。

        原实现在这里起 ``VideoDownloadThread`` 把视频下一条、再 emit
        ``finished`` 进转录链路。自研化后不再这么做：那条链路没有画质
        选择、没有并行队列、没有中止、没有代理兜底，而宿主下载页全都有，
        且下载完带字幕打包与信息 txt。**下载归下载页，建任务归本页**——
        用户粘链接时的意图本来就是「下载」，顺手在下载页把画质选好更符合。
        """
        self.url_detected.emit(url)

    def on_video_download_finished(self, video_file_path):
        """兼容钩子：宿主若仍接 ``on_video_download_finished``（例如引擎回退
        路径），行为不变。本页不再自行下载，正常路径不会走到这里。"""
        const = _seams.constants
        if video_file_path:
            self.finished.emit(video_file_path)
            InfoBar.success(
                self.tr("下载成功"), self.tr("视频下载完成，开始自动处理..."),
                duration=const.INFOBAR_DURATION_SUCCESS,
                position=InfoBarPosition.BOTTOM, parent=self.parent())
        else:
            InfoBar.error(
                self.tr("错误"), self.tr("视频下载失败"),
                duration=const.INFOBAR_DURATION_ERROR, parent=self)

    def on_create_task_progress(self, value, status):
        self.progress_bar.show()
        self.status_label.show()
        self.progress_bar.setValue(value)
        self.status_label.setText(status)

    def on_create_task_error(self, error):
        InfoBar.error(
            self.tr("错误"), self.tr(error),
            duration=_seams.constants.INFOBAR_DURATION_ERROR, parent=self)

    def set_task(self, task):
        self.task = task
        self.update_info()

    def update_info(self):
        if self.task:
            self.search_input.setText(self.task.file_path)

    def process(self):
        """入口：本地文件 → 建任务；网页链接 → 跳下载页；纯文本 → AI 托管。

        顺序要紧：``os.path.isfile`` 先判，否则 ``C:\\videos\\a.mp4`` 这种
        路径会被链接识别当成裸域名（``extract_web_url`` 已挡掉反斜杠与
        数字末段，但先判文件更省事也更保险）。最后的兜底也不是从前那个
        「格式错误」了——v2.1.0 起 harness 就绪时，纯文本交给 AI 托管
        （``ai_requested``）；harness 不在场才弹原来的错误提示。
        """
        raw = self.search_input.text()
        text = (raw or "").strip()
        if text and os.path.isfile(text):
            self._process_file(text)
            return
        # 链接识别放宽到分享文案整段 / 漏协议头 / 带引号 / 尾部标点
        url = _seams.extract_web_url(raw)
        if url:
            self.search_input.setText(url)
            self._process_url(url)
            return
        if text and _harness_ready():
            self.ai_requested.emit(text)
            return
        InfoBar.error(
            self.tr("错误"), self.tr("请输入音视频文件路径或URL"),
            duration=_seams.constants.INFOBAR_DURATION_ERROR, parent=self)

    def show_log_window(self):
        if self.log_window is None:
            self.log_window = LogWindow()
        if self.log_window.isHidden():
            self.log_window.show()
        else:
            self.log_window.activateWindow()

    def show_donate_dialog(self):
        # 捐助入口已中性化隐藏（宿主亦会 hide donate_button）；保留空实现，
        # 避免任何遗留连接触发时 AttributeError。
        return
