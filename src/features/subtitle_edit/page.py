# -*- coding: utf-8 -*-
# @version 3.1.0
"""字幕编辑页（2026-11-15 功能解耦阶段③：从 video_toolbox_qt.py 拆出，逐字同源）。

* 三件套后端：subtitle_editor_core（数据）/ subtitle_editor（控件）/
  subtitle_editor_media（mpv/波形）+ subtitle_overlay（画面字幕层）；
* 内嵌字幕对话框 ComposeDialog 属 compose 功能（subtitle_compose.py），经
  既有 import 使用；ConfirmDialog/_VideoHost 为本页专属，随页迁入；
* 本页全走 Qt 信号（无 pump 消息），不需要 bus 订阅。
"""
import json
import os
import sys
import threading
import time

from PySide6.QtCore import QEvent, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QKeyEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QDialog,
                               QFileDialog, QFrame, QHBoxLayout, QLabel,
                               QMessageBox, QSizePolicy, QSplitter,
                               QVBoxLayout, QWidget)

from vt_fluent import (CaptionLabel, ComboBox, FluentIcon as FIF, InfoBar,
                       InfoBarPosition, PrimaryPushButton, ProgressBar,
                       PushButton, StrongBodyLabel, ToolButton)

import video_toolbox as engine
import subtitle_editor_core as secore
from features.subtitle_edit.subtitle_editor import CueTable, SubtitlePropsPanel, WaveformTimeline
from features.subtitle_edit.subtitle_editor_media import MpvPlayer, WaveformCache
from features.subtitle_edit.subtitle_overlay import SubtitleStage
from features.compose.subtitle_compose import ComposeDialog

from vt_app.widgets import ScrollPage, fit_caption
from features._media import MEDIA_FILE_FILTER


class ConfirmDialog(QDialog):
    """确认框：**真·顶层模态窗口**，不是贴在主窗口里的自绘遮罩。

    为什么不能用 `qfluentwidgets.MessageBox`（v1.13.7 定论）：
    它在传了 parent 时会退化成**普通子控件** —— 探针实测
    `isWindow()==False`、`WS_CHILD==True`、`GetParent()` 就是主窗口、
    几何等于主窗口整块（见 `_workspace/probes/_probe_msgbox.py`）。而字幕编辑
    页的视频区是 **mpv 的原生子窗口**（`wid` 嵌进 `video_host`），原生子窗口在
    Windows 上永远盖在同级 Qt 自绘控件之前，并且播放器通常握着键盘焦点 ——
    于是用户看到的就是「这个框点不动、Esc/空格/回车全无反应」。

    顶层窗口由系统独立管理，不参与主窗口内部的层级之争，鼠标/键盘都稳。
    """

    def __init__(self, title, message, parent=None,
                 yes_text="确定", no_text="取消"):
        super().__init__(parent)
        # ⚠️ 必须是 Qt.Dialog：只给 FramelessWindowHint 会丢掉窗口类型
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint
                            | Qt.NoDropShadowWindowHint)
        self.setWindowModality(Qt.ApplicationModal)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowTitle(title or "确认")

        dark = False
        try:
            from vt_fluent import isDarkTheme
            dark = bool(isDarkTheme())
        except Exception:  # noqa: BLE001
            pass
        bg = "#2B2B2B" if dark else "#FFFFFF"
        fg = "#F3F3F3" if dark else "#1B1B1B"
        sub = "#C9C9C9" if dark else "#4C4C4C"
        line = "#3D3D3D" if dark else "#E6E6E6"

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame(self, objectName="vtConfirmCard")
        card.setAttribute(Qt.WA_StyledBackground, True)
        card.setStyleSheet(
            "#vtConfirmCard{background:%s;border:1px solid %s;"
            "border-radius:10px;}" % (bg, line))
        outer.addWidget(card)

        inner = QVBoxLayout(card)
        inner.setContentsMargins(26, 22, 26, 18)
        inner.setSpacing(10)

        lbl_title = QLabel(title or "确认", card, objectName="vtConfirmTitle")
        lbl_title.setStyleSheet(
            "#vtConfirmTitle{color:%s;font-size:15px;font-weight:600;"
            "background:transparent;border:none;}" % fg)
        lbl_body = QLabel(message or "", card, objectName="vtConfirmBody")
        lbl_body.setWordWrap(True)
        lbl_body.setStyleSheet(
            "#vtConfirmBody{color:%s;font-size:13px;background:transparent;"
            "border:none;}" % sub)
        lbl_body.setMinimumWidth(300)
        lbl_body.setMaximumWidth(420)
        inner.addWidget(lbl_title)
        inner.addWidget(lbl_body)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 8, 0, 0)
        buttons.setSpacing(10)
        buttons.addStretch(1)
        self.cancelButton = PushButton(no_text, card)
        self.yesButton = PrimaryPushButton(yes_text, card)
        for b in (self.cancelButton, self.yesButton):
            b.setFixedWidth(112)
        buttons.addWidget(self.cancelButton)
        buttons.addWidget(self.yesButton)
        inner.addLayout(buttons)

        self.cancelButton.clicked.connect(self.reject)
        self.yesButton.clicked.connect(self.accept)
        # 焦点落在"确定"上：回车即确认、Esc 即取消（QDialog 内建）
        self.yesButton.setFocus()
        self.adjustSize()

    def showEvent(self, e):
        super().showEvent(e)
        parent = self.parentWidget()
        if parent is not None:
            try:
                center = parent.window().frameGeometry().center()
                self.move(center - self.rect().center())
            except Exception:  # noqa: BLE001
                pass
        # 顶层窗口也可能被别的东西压在下面 / 没拿到前台，显式抬一次
        self.raise_()
        self.activateWindow()
        self.yesButton.setFocus()

    @staticmethod
    def release_stale_capture():
        """放掉可能残留的鼠标捕获（Windows 的 SetCapture 是独占的）。

        拖放（OLE）与视频窗口都会留下这种残留：谁握着捕获，鼠标消息就全归谁
        —— 对话框画得出来也点不动。ReleaseCapture 作用于**调用线程**，
        正是 GUI 线程自己。
        """
        if not sys.platform.startswith("win"):
            return
        try:
            import ctypes
            user32 = ctypes.windll.user32
            if user32.GetCapture():
                user32.ReleaseCapture()
        except Exception:  # noqa: BLE001
            pass

    @classmethod
    def ask(cls, parent, title, message, yes_text="确定", no_text="取消"):
        """弹一次确认；返回 True = 用户点了 yes。顶层模态，稳定可交互。"""
        cls.release_stale_capture()
        dlg = cls(title, message, parent, yes_text, no_text)
        try:
            return dlg.exec() == QDialog.Accepted
        finally:
            dlg.deleteLater()


class _VideoHost(QWidget):
    """播放器宿主：最小尺寸由 `setMinimumSize` 说了算。

    为什么不直接用 QWidget：mpv 是用 `wid` **嵌入**进来的原生子窗口，
    Qt 会把它的尺寸算进宿主控件的 `minimumSizeHint()` —— 载入视频后实测
    整个主窗口的最小高度从 620 涨到 810，于是窗口再也缩不下去（下边缘跑到
    屏幕外，"只能拉顶部、底部调不了"）。视频区该多小由我们声明，
    不该由播放器的原生窗口替我们决定。
    """

    def minimumSizeHint(self):
        # ⚠️ 判据必须是 **or**，不能写成 `and`：
        #    `setMinimumWidth` / `setMinimumHeight` 只要有一边没设（高度是 0），
        #    `and` 就不成立，于是回落到 `super().minimumSizeHint()` —— 而那个值
        #    里含着 mpv 原生子窗口的尺寸：载入视频后整个主窗口的最小高度会从
        #    620 一路涨到 810，窗口再也缩不下去（下边缘跑到屏幕外，"只能拉顶部、
        #    底部调不了"）。只要有一边是我们自己声明的，就以声明为准，
        #    视频区该多小由我们说了算，不该由播放器的原生窗口替我们决定。
        ms = self.minimumSize()
        if ms.width() > 0 or ms.height() > 0:
            return QSize(ms.width(), ms.height())
        return super().minimumSizeHint()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        # 尺寸一变就通知页面重算"视频框贴合比例"（见 SubtitleEditPage.
        # _fit_video_frame）。用回调而不是页面装 eventFilter：本类已经是
        # 播放器宿主的专有壳子，回调链路更短、也更好排查。
        cb = getattr(self, "resized_cb", None)
        if cb:
            try:
                cb()
            except Exception:  # noqa: BLE001
                pass


class SubtitleEditPage(ScrollPage):
    """字幕编辑（打轴）：播放器 + 波形时间轴 + 字幕表。

    结构照搬开源实现（Nosub 的三件套、KDE Subtitle Composer 的波形轨）：
      · 播放器  = libmpv 嵌进 QWidget（`subtitle_editor_media.MpvPlayer`）
      · 波形轨  = ffmpeg 解峰值 + 自绘字幕块（`subtitle_editor.WaveformTimeline`）
      · 字幕表  = 序号/起止/时长/文本（`subtitle_editor.CueTable`）
    数据层是 `subtitle_editor_core.SubtitleDoc` + `UndoStack`，时间一律 **int 毫秒**。

    三条底线：
      1. **许可**：libmpv 用 **LGPL** 构建，动态链接；
      2. **体积**：dll 不进安装包，由 `tools/download_open_source_deps.py`
         运行时拉取（沿用既有依赖拉取方案），缺失时本页只提示、不崩；
      3. **退出**：`aboutToQuit` 必须调 `shutdown()` 释放 libmpv，否则
         打包后 onefile 的 `_MEI***` 临时目录删不掉（v1.12.0 踩过）。
    """

    _wave_progress = Signal(int)          # 波形构建进度（0-100）
    _wave_ready = Signal(object, float)   # (peaks bytearray, 时长秒)
    _wave_failed = Signal(str)
    _mpv_ready = Signal(bool, str)        # 播放组件补装结果 (成功?, 错误)

    SPEEDS = ("0.25", "0.5", "0.75", "1.0", "1.25", "1.5", "2.0")
    #: 文本列里换行以 " / " 呈现（表格行高不随多行文本变化）；
    #: 提交时按同一分隔符还原。字幕里出现 " / " 的概率极低，且只在编辑该格时生效。
    NL_SEP = " / "

    def __init__(self, app, parent=None):
        # v1.13.x：副标题缩短到一行放得下，并 fit 掉自动换行。否则首次布局时
        # heightForWidth 会把 1 行算成 2 行 → 整页内容下移，就是「进页面上下闪一下」。
        super().__init__("字幕编辑",
                         "拖波形改起止时间，双击切分，[ ] 取起止点，空格播放暂停",
                         parent, scrollable=False)
        fit_caption(self.cap)
        self.app = app
        self.setObjectName("SubtitleEditPage")

        self.doc = secore.SubtitleDoc()
        self.undo = secore.UndoStack()
        self.video_path = ""
        self.sub_path = ""
        self.dirty = False
        self.ffmpeg = ""
        self.ffprobe = ""
        self._wave_stop = threading.Event()
        self._wave_busy = False
        # 播放器不可用提示的去重节流（拖时间轴会高频触发 _ensure_player，
        # 不去重的话 libmpv 缺失时错误 InfoBar 会连珠炮刷屏——用户实测截图）
        self._player_err_shown = ""
        self._player_err_at = 0.0
        self._mpv_installing = False
        self._mpv_pending_path = ""      # 补装完成后来不及 load 的媒体路径
        self._pre_drag = None            # 拖拽开始前的整档快照
        self._drag_pushed = False
        self._shortcuts = []
        # 画面字幕预览：cues -> ASS -> mpv 的 sub-add/sub-reload
        self._ass_sig = None             # 上次下发的 cues 指纹（相同就不重建）
        # 预览样式（字体 / 字号 / 颜色 / 描边 / 对齐 / 边距）**持久化**：
        # 这是用户一句句调出来的，重启就回默认等于白调。存数据根目录，不进 .srt。
        self._preview_style = dict(secore.ASS_DEFAULT_STYLE)
        self._preview_style.update(self._load_preview_style())
        self._cur_index = -2             # 面板正在显示的下标；-2 = 强制刷新

        self.mpv_dir = os.path.join(engine.TOOLS_DIR, "mpv")
        self.wave_cache = None
        self.player = MpvPlayer(self.mpv_dir, self)
        self.player.position_changed.connect(self._on_position)
        self.player.duration_changed.connect(self._on_duration)
        self.player.playing_changed.connect(self._on_playing)

        self._wave_progress.connect(self._on_wave_progress)
        self._wave_ready.connect(self._on_wave_ready)
        self._wave_failed.connect(self._on_wave_failed)
        self._mpv_ready.connect(self._on_mpv_ready)

        self._build_ui()
        self._install_shortcuts()
        self._refresh_status()

    # ---------------------------------------------------------
    # 界面
    # ---------------------------------------------------------
    def _build_ui(self):
        # 时间码放**状态栏右侧**（原来挂在工具条尾部，960px 窗口下会被压成
        # "00:02.000 /(" 什么都说不清）。
        self.lbl_time = StrongBodyLabel("--:--.--- / --:--.---", self)

        # —— 画面 + 右栏（右栏 = 字幕属性；字幕本身在**画面上**直接操作）——
        self.video_host = _VideoHost(self)
        self.video_host.setStyleSheet("background:#000;")
        self.video_host.setMinimumWidth(280)
        self.video_host.setMinimumHeight(160)
        # 视频框自适应长宽比：宿主尺寸一变就按视频比例重算高度（v1.14.3）
        self.video_host.resized_cb = self._fit_video_frame
        self.video_hint = CaptionLabel("尚未打开视频", self.video_host)
        self.video_hint.setStyleSheet("color:#777;background:transparent;")
        vlay = QVBoxLayout(self.video_host)
        vlay.setContentsMargins(0, 0, 0, 0)
        vlay.addWidget(self.video_hint, 0, Qt.AlignCenter)

        # v1.13.2：右栏不再保留字幕框/字幕列表，改为「字幕属性」面板。
        # 字幕本身是要"看得见、点得到、能拖"的东西，所以挪到画面上直接操作
        # （SubtitleStage），右侧只留外观参数；两边共用同一份样式字典。
        # 视频底部的一排图标控制栏：原来铺在页面顶部的两行文字按钮（工具条 +
        # 编辑条）全部并到这里，页面因此省下近 80px 高度还给画面。
        self.media_bar = self._build_media_bar()
        self.video_col = QWidget(self)
        vclay = QVBoxLayout(self.video_col)
        vclay.setContentsMargins(0, 0, 0, 0)
        vclay.setSpacing(2)
        vclay.addWidget(self.video_host, 1)
        vclay.addWidget(self.media_bar)
        # 视频框按比例压矮后，多出来的竖向空间要**上下均分**（视频块垂直
        # 居中）：前后各放一个 0 因子伸缩项。host 没封顶时 stretch=1 仍吃掉
        # 全部余量、两个伸缩项拿不到空间；被封顶后余量在两个伸缩项间对半
        # 分，控制条始终紧贴画面下沿。
        self._vclay = vclay
        vclay.insertStretch(0, 0)
        vclay.addStretch(0)

        self.props = SubtitlePropsPanel(self)

        # 画面字幕层：**顶层无边框透明窗口**，贴在视频的**实际显示区域**上。
        # 为什么不贴满 video_host：视频有黑边时（竖屏/异形比例）整块 widget 里
        # 只有中间一块是画面，贴满会让选框和真实字幕错位——字幕的坐标基准必须
        # 与画面一致，这是「浮层位置与字幕真实位置绑定」的关键。
        self.stage = SubtitleStage(self.video_host, self.window(),
                                   rect_provider=self._video_rect)

        self.hsplit = QSplitter(Qt.Horizontal, self)
        self.hsplit.setChildrenCollapsible(False)
        self.hsplit.addWidget(self.video_col)
        self.hsplit.addWidget(self.props)
        self.hsplit.setStretchFactor(0, 4)
        self.hsplit.setStretchFactor(1, 1)
        self.hsplit.setSizes([700, 300])

        self.timeline = WaveformTimeline(self)
        self.timeline.setMinimumHeight(110)

        # 全量列表（批量多选 / 合并 / 删除）挪到时间轴下方的抽屉里、默认收起：
        # 右栏让给了属性面板，但"批量改时间"的能力不能跟着丢。
        self.table = CueTable(self)
        self.table.setMinimumHeight(96)
        self.table_shell = QWidget(self)
        tlay = QVBoxLayout(self.table_shell)
        tlay.setContentsMargins(0, 0, 0, 0)
        tlay.setSpacing(0)
        tlay.addWidget(self.table)
        self.table_shell.hide()

        self.vsplit = QSplitter(Qt.Vertical, self)
        self.vsplit.setChildrenCollapsible(False)
        self.vsplit.addWidget(self.hsplit)
        self.vsplit.addWidget(self.timeline)
        self.vsplit.setStretchFactor(0, 1)
        self.vsplit.setStretchFactor(1, 0)
        self.vsplit.setSizes([520, 150])
        self.vbox.addWidget(self.vsplit, 1)
        self.vbox.addWidget(self.table_shell)

        # —— 状态区（左：状态文字；右：时间码）——
        srow = QHBoxLayout()
        srow.setSpacing(12)
        self.status = CaptionLabel("就绪", self)
        self.status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        srow.addWidget(self.status, 1)
        srow.addWidget(self.lbl_time, 0)
        self.shell_status = QWidget(self)
        self.shell_status.setLayout(srow)
        self.vbox.addWidget(self.shell_status)
        # v1.13.x：进度条必须放进**固定高度容器**再显隐。直接 addWidget 后 hide()，
        # 它一出现/一消失就带着下方内容上下位移（4px + 布局间距），
        # 表现出来正是「进页面上下闪一下」。容器常驻，显隐只影响它自己。
        self.wave_slot = QWidget(self)
        self.wave_slot.setFixedHeight(6)
        slot_lay = QVBoxLayout(self.wave_slot)
        slot_lay.setContentsMargins(0, 0, 0, 0)
        slot_lay.setSpacing(0)
        self.wave_bar = ProgressBar(self.wave_slot)
        self.wave_bar.setFixedHeight(4)
        slot_lay.addWidget(self.wave_bar)
        self.wave_bar.hide()
        self.vbox.addWidget(self.wave_slot)

        # —— 信号 ——
        # 控制栏上那批按钮的信号在 `_build_media_bar` 里已经连好，这里不再重复连
        # （连两次会让每次点击都触发两遍）。

        self.timeline.position_clicked.connect(self.seek_ms)
        self.timeline.cue_selected.connect(self._on_timeline_cue_selected)
        self.timeline.drag_started.connect(self._on_drag_started)
        self.timeline.cue_dragged.connect(self._on_cue_dragged)
        self.timeline.drag_finished.connect(self._on_drag_finished)
        self.timeline.split_requested.connect(self._on_split_requested)
        self.table.selection_changed.connect(self._on_table_selection)
        self.table.cell_committed.connect(self._on_cell_committed)
        # v1.16.5 修复：btn_list 的信号已由 _build_media_bar() 的 ibtn() 连过
        # （该函数内 b.clicked.connect(slot)），此处再连一次会让 toggle_list
        # 每次点击触发两遍（重复 table.load / setFocus）。故删除本行。
        self.props.step_requested.connect(self.goto_cue)
        self.props.style_changed.connect(self._on_style_changed)
        self.props.export_requested.connect(self.export_subtitle)
        self.props.set_style(self._preview_style)

        # —— 画面字幕层（点选 / 拖动 / 就地改字 / 双击空白播放暂停）——
        self.stage.cue_clicked.connect(self._on_stage_cue_clicked)
        self.stage.cue_followed.connect(self._on_stage_cue_followed)
        self.stage.delete_requested.connect(self._on_stage_delete)
        self.stage.selection_cleared.connect(self._on_stage_cleared)
        self.stage.command_requested.connect(self._on_stage_command)
        self.stage.text_committed.connect(self._on_stage_text)
        self.stage.layout_changed.connect(self._on_stage_layout)
        self.stage.layout_preview.connect(self._on_stage_layout_preview)
        self.stage.play_toggled.connect(self.toggle_play)
        self.stage.set_style(self._preview_style)
        self.stage.set_cues(self.doc.cues)

    # ---------------------------------------------------------
    # 视频底部的一排图标控制栏
    # ---------------------------------------------------------
    #: 控制栏图标按钮的边长（逻辑像素）。19 个图标 + 5 条分隔线 + 倍速下拉要在
    #: 一排里放下（1280 屏上窗口收敛后视频区只有 ~610px 宽），26 是实测算得下
    #: 的最大值——再大就会挤到裁切。
    BAR_ICON = 22

    def _build_media_bar(self):
        """视频**底部**的一排图标控制栏（原顶部两行文字按钮的替代）。

        两组考虑：
          · **放视频下面，不叠进画面**——video_host 里跑的是 mpv 的**原生
            子窗口**，任何 Qt 控件叠进去都会被它盖住，一个图标都看不见；
          · **全图标 + tooltip**——18 个中文按钮并排必然放不下，纯图标才能
            在一排里排开，完整说明留在 tooltip 与快捷键里。
        """
        bar = QWidget(self)
        bar.setObjectName("MediaBar")
        bar.setFixedHeight(self.BAR_ICON + 4)
        # 用 #MediaBar 限定，避免样式级联到里面的图标按钮上；
        # 配色主题感知（_apply_media_bar_theme），不再写死深色。
        self._media_dividers = []
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(8, 2, 8, 2)
        # 20 个图标 + 5 条分组竖线要在一排里放得下：按最小窗口（880 宽 → 视频区
        # 约 467px）反推，图标 22px、间距 1px 刚好富裕一点。再大就会互相重叠。
        lay.setSpacing(1)

        def ibtn(icon, tip, slot, checkable=False):
            b = ToolButton(icon, self)
            b.setFixedSize(self.BAR_ICON, self.BAR_ICON)
            b.setToolTip(tip)
            if checkable:
                b.setCheckable(True)
            b.clicked.connect(slot)
            # stretch=1：按钮本身是固定尺寸，多出来的空间由布局均分，于是
            # 图标沿整条栏**均匀铺开**，而不是全堆在左边（右边留一大片空）。
            lay.addWidget(b, 1)
            return b

        def divider():
            line = QWidget(bar)
            line.setFixedSize(1, 14)
            self._media_dividers.append(line)
            lay.addWidget(line)

        # —— 文件 ——
        self.btn_video = ibtn(FIF.VIDEO, "打开视频（Ctrl+O）", self.open_video)
        self.btn_sub = ibtn(FIF.FONT, "打开字幕（Ctrl+Shift+O）", self.open_subtitle)
        self.btn_save = ibtn(FIF.SAVE, "保存（Ctrl+S）", self.save)
        self.btn_save_as = ibtn(FIF.SAVE_AS, "另存为（Ctrl+Shift+S）", self.save_as)
        self.btn_close_media = ibtn(FIF.CLOSE, "关闭视频：卸下当前视频并复位波形"
                                              "（字幕不动）", self.close_video)
        divider()

        # —— 播放 ——
        self.btn_prev_frame = ibtn(FIF.CARE_LEFT_SOLID, "上一帧（← 或 ,）",
                                   lambda: self.step_frames(-1))
        self.btn_play = ibtn(FIF.PLAY_SOLID, "播放 / 暂停（空格）", self.toggle_play)
        self.btn_next_frame = ibtn(FIF.CARE_RIGHT_SOLID, "下一帧（→ 或 .）",
                                   lambda: self.step_frames(1))
        self.speed_box = ComboBox(bar)
        self.speed_box.addItems(self.SPEEDS)
        self.speed_box.setCurrentText("1.0")
        self.speed_box.setFixedWidth(62)
        self.speed_box.setToolTip("播放倍速")
        self.speed_box.currentTextChanged.connect(self._on_speed)
        lay.addWidget(self.speed_box, 1)
        divider()

        # —— 编辑 ——
        self.ops = []
        self.btn_split = ibtn(FIF.CUT, "切分：在播放头处把选中条目切成两条"
                                       "（Ctrl+K，或在波形上双击）", self.split_at_playhead)
        self.btn_merge = ibtn(FIF.CONSTRACT, "合并：把选中的多条合并为一条",
                              self.merge_selected)
        self.btn_del = ibtn(FIF.DELETE, "删除选中条目（Del）", self.delete_selected)
        self.btn_ins = ibtn(FIF.ADD, "插入：在播放头处插入一条 1.5s 空白字幕",
                            self.insert_at_playhead)
        self.ops.extend([self.btn_split, self.btn_merge, self.btn_del, self.btn_ins])
        divider()

        # —— 起止点 / 平移 ——
        self.btn_start = ibtn(FIF.PAGE_LEFT, "取起点：把选中条目的起点设为播放头（[）",
                              self.set_start_here)
        self.btn_end = ibtn(FIF.PAGE_RIGHT, "取终点：把选中条目的终点设为播放头（]）",
                            self.set_end_here)
        self.btn_fwd = ibtn(FIF.LEFT_ARROW, "前移 0.1s（Shift+←）",
                            lambda: self.shift_selected(-100))
        self.btn_bwd = ibtn(FIF.RIGHT_ARROW, "后移 0.1s（Shift+→）",
                            lambda: self.shift_selected(100))
        self.ops.extend([self.btn_start, self.btn_end])
        divider()

        # —— 历史 ——
        self.btn_undo = ibtn(FIF.HISTORY, "撤销（Ctrl+Z）", self.undo_edit)
        self.btn_redo = ibtn(FIF.SYNC, "重做（Ctrl+Y）", self.redo_edit)
        divider()

        # —— 工具 ——
        self.btn_compose = ibtn(FIF.MOVIE, "内嵌字幕：把当前字幕作为独立轨道内嵌"
                                           "进视频，音视频原样复制、不重新编码",
                                self.open_compose)
        self.btn_list = ibtn(FIF.MENU, "展开时间轴下方的全量列表"
                                       "（多选合并 / 批量删除 / 改时间）",
                             self.toggle_list, checkable=True)
        # 不加 addStretch —— 靠每项的 stretch=1 均分，图标才是「均匀排列」
        self._apply_media_bar_theme(bar)
        try:
            import ui_theme
            ui_theme.connect_theme(bar, lambda w: self._apply_media_bar_theme())
        except Exception:
            pass
        return bar

    def _apply_media_bar_theme(self, bar=None):
        """媒体条配色主题感知（v1.14.1）：深色=深控制台条，浅色=浅灰条。

        此前写死 #1b1b1b 深底 + #3d3d3d 分隔线，浅色主题下与整页白卡片
        割裂（用户截图反馈「浅色背景中不协调」）。浅色底改取 log_bg 同款
        #F4F6F8、分隔线取 border_hover，与日志控制台保持同一设计语言；
        深色下 log_bg 恰好就是原来的 #1b1b1b，观感不变。
        `bar` 可显式传入——构建期 self.media_bar 还没挂上（先建后赋值）。
        """
        bar = bar if bar is not None else getattr(self, "media_bar", None)
        if bar is None:
            return
        import ui_theme
        t = ui_theme.tokens()
        bar.setStyleSheet(
            "QWidget#MediaBar{background:%s;border-top:1px solid %s;}"
            % (t["log_bg"], t["border"]))
        for line in getattr(self, "_media_dividers", []):
            line.setStyleSheet("background:%s;" % t["border_hover"])

    # ---------------------------------------------------------
    # 字幕列表抽屉（批量改时间用；右栏已让给属性面板）
    # ---------------------------------------------------------
    def toggle_list(self):
        """展开/收起时间轴下方的全量列表。"""
        show = self.btn_list.isChecked()
        self.table_shell.setVisible(show)
        if show:
            self.table.load(self.doc.cues)
            idx = self.timeline.selected
            if idx >= 0:
                self.table.select_row(idx)
            self.table.setFocus()
        else:
            self.timeline.setFocus()
        self._refresh_status("已展开字幕列表" if show else "")

    # ---------------------------------------------------------
    # 快捷键（WidgetWithChildren：焦点在本页时才生效，不抢别的页面）
    # ---------------------------------------------------------
    def _install_shortcuts(self):
        def add(seq, slot):
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(slot)
            self._shortcuts.append(sc)

        add("Space", self.toggle_play)
        # 逐帧：Aegisub 的 , / . 是行业习惯；←/→ 同时可用（表格内编辑时让路）
        add(",", lambda: self.step_frames(-1))
        add(".", lambda: self.step_frames(1))
        add("Left", lambda: self.step_frames(-1))
        add("Right", lambda: self.step_frames(1))
        add("Shift+Left", lambda: self.nudge(-100))
        add("Shift+Right", lambda: self.nudge(100))
        add("Alt+Left", lambda: self.nudge(-1000))
        add("Alt+Right", lambda: self.nudge(1000))
        add("Up", lambda: self.goto_cue(-1))
        add("Down", lambda: self.goto_cue(1))
        add("[", self.set_start_here)
        add("]", self.set_end_here)
        add("Ctrl+K", self.split_at_playhead)
        add("Ctrl+A", self.select_all_cues)
        add("Del", self.delete_selected)
        add("Ctrl+Z", self.undo_edit)
        add("Ctrl+Y", self.redo_edit)
        add("Ctrl+Shift+Z", self.redo_edit)
        add("Ctrl+S", self.save)
        add("Ctrl+Shift+S", self.save_as)
        add("Ctrl+O", self.open_video)
        add("Ctrl+Shift+O", self.open_subtitle)
        add("Ctrl+=", lambda: self.timeline.zoom(1.25))
        add("Ctrl+-", lambda: self.timeline.zoom(1 / 1.25))
        add("Ctrl+0", self.timeline.fit_all)
        add("Ctrl+Shift+F", self.fit_selected)

    def _table_editing(self):
        """表格正在改单元格时，方向键要还给文本编辑框。"""
        try:
            if self.table.state() == QAbstractItemView.EditingState:
                return True
            w = QApplication.focusWidget()
            return w is not None and w.metaObject().className() in (
                "QLineEdit", "QTextEdit", "QPlainTextEdit")
        except Exception:
            return False

    def _forgive_key(self, seq):
        """把被快捷键吃掉的按键原样转发给当前焦点控件（表格内编辑用）。"""
        try:
            fw = QApplication.focusWidget()
            if fw is None:
                return
            key = QKeySequence(seq)[0]
            ev = QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier)
            QApplication.sendEvent(fw, ev)
        except Exception:
            pass

    # ---------------------------------------------------------
    # 生命周期
    # ---------------------------------------------------------
    def relayout_after_screen_change(self):
        """跨屏 / DPI 变化后重新收敛本页布局。

        必须做两件事：
          · **重设分割条比例**。Qt 在 PPI 变化后按各子项的 sizeHint 重排
            splitter，把视频区压扁、属性面板顶宽——用户看到的就是"跨屏
            拖动后页面扭曲变形"；而比例只在首次 show 时设过一次。
          · **让字幕层重新贴合画面**。它是顶层窗口，不会跟着主窗口的重排走，
            跨屏后会停在旧坐标上（看起来像浮在别处）。
        """
        self._apply_split_defaults()
        try:
            self._sync_stage_visible()
            self.stage.snap_to_host()
        except Exception:  # noqa: BLE001
            pass

    def _apply_split_defaults(self):
        """按黄金比例分配上下 / 左右两个分割条。

        为什么不能只在 `_build_ui` 里 `setSizes()` 就完事：构造时 splitter 的
        尺寸还是 0，Qt 会把这次 setSizes 当成"比例提示"记下来，随后又按各子项
        的 sizeHint 重新分配——结果视频区被压成一条（实测 531x173），属性面板
        也跟着挤到最小宽度。必须等**首次 show 之后**再设一次，这时尺寸才是真的。

        左右 72:28、上下 84:16：这是让视频画面接近 16:9、右栏刚好放得下属性
        面板、时间轴又不至于缩到看不见的一组值（按 1180x729 与 1280 屏实测
        收敛后的 1080x667 两档算的——后者上下空间更紧，取 84 才不至于把画面
        压成一条）。
        """
        try:
            w = self.hsplit.width()
            if w > 0:
                left = int(w * 0.72)
                self.hsplit.setSizes([left, w - left])
            h = self.vsplit.height()
            if h > 0:
                top = int(h * 0.84)
                self.vsplit.setSizes([top, h - top])
        except Exception:  # noqa: BLE001
            pass

    def showEvent(self, ev):
        super().showEvent(ev)
        QTimer.singleShot(0, lambda: self.timeline.setFocus())
        # 首次进页面时把属性面板对齐到播放头（此时还没有播放器）
        QTimer.singleShot(0, self._sync_current)
        # 字幕层是顶层窗口，页面不走它自己那一套显隐，必须手动跟
        QTimer.singleShot(0, self._sync_stage_visible)
        if not getattr(self, "_split_done", False):
            self._split_done = True
            QTimer.singleShot(0, self._apply_split_defaults)
            QTimer.singleShot(150, self._apply_split_defaults)

    def hideEvent(self, ev):
        # 页面切走后立刻暂停：mpv 在后台解码只是白烧 CPU
        try:
            if self.player.is_playing():
                self.player.pause()
        except Exception:
            pass
        try:
            self.stage.hide_stage()
        except Exception:
            pass
        super().hideEvent(ev)

    def shutdown(self):
        """退出前释放画面字幕层与 libmpv。

        两件事都必须做：
          · libmpv 不 `terminate()` 会留下 _MEI*** 删不掉的毛病（v1.12.0 踩过）；
          · 画面字幕层是个**顶层窗口**，进程退出时若它还活着，Qt 会在
            销毁顺序上踩空——实测收尾阶段访问冲突（0xC0000005，无 traceback），
            所以显式关掉再解引用。
        """
        self._wave_stop.set()
        try:
            self.stage.hide_stage()
            self.stage.close()
            self.stage.setParent(None)
            self.stage.deleteLater()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.player.terminate()
        except Exception:  # noqa: BLE001
            pass

    # ---------------------------------------------------------
    # 画面字幕层
    # ---------------------------------------------------------
    def _video_rect(self):
        """视频在 video_host 里的**实际显示矩形**（逻辑像素，已去掉黑边）。

        字幕的坐标基准必须和画面一致：竖屏视频、异形比例、或者窗口被拉成
        别的比例时，widget 里只有中间一块是画面，其余是黑边。字幕层贴
        "画面"而不是"widget"，选框和真实字幕才不会错位。
        """
        w, h = self.video_host.width(), self.video_host.height()
        if w < 8 or h < 8:
            return QRect(0, 0, max(0, w), max(0, h))
        ar = self.player.video_aspect() if self.player else 0.0
        if ar <= 0.01:
            return QRect(0, 0, w, h)          # 还没有视频：整块都算画面
        if w / float(h) > ar:                 # widget 更宽 → 左右留黑边
            vw = int(round(h * ar))
            return QRect((w - vw) // 2, 0, vw, h)
        vh = int(round(w / ar))               # widget 更高 → 上下留黑边
        return QRect(0, (h - vh) // 2, w, vh)

    def _fit_video_frame(self):
        """让视频框高度**跟随视频宽高比**（v1.14.3，去黑边）。

        以前 video_host 无条件铺满可用区域，比例不合的画面由 mpv 在里面
        加黑边——16:9 视频在偏方的宿主里上下全是黑框。现在拿到视频比例后
        把 host 的**最大高度**压到 `宽 / 比例`：

          · 用 maxHeight + Expanding 而不是 setFixedHeight：竖向空间不够时
            布局仍能把 host 压回可用高度（此时才轮到 mpv 左右加黑边兜底），
            不会撑破 video_col，拖竖向分割条也不会把画面挤出界；
          · 比例未知 / 没视频时解除封顶，回到铺满 + "尚未打开视频"占位；
          · 触发点：载入媒体（60ms / 400ms 两次，等 mpv 解出 video-params）、
            duration 就绪、宿主 resize（`_VideoHost.resized_cb`）、关视频。
        """
        host = self.video_host
        if host.width() < 8:
            return
        ar = self.player.video_aspect() if (self.player and self.video_path) else 0.0
        if ar <= 0.01:
            if host.maximumHeight() != 16777215:   # QWIDGETSIZE_MAX
                host.setMaximumHeight(16777215)
            return
        # 可用高度 = video_col 高度 - 控制条 - 布局间距（vclay spacing=2）
        try:
            spacing = self._vclay.spacing()
        except Exception:  # noqa: BLE001
            spacing = 2
        avail = self.video_col.height() - self.media_bar.height() - spacing
        target = int(round(host.width() / ar))
        target = max(host.minimumHeight(), min(target, max(160, avail)))
        if host.maximumHeight() != target:
            host.setMaximumHeight(target)

    def _sync_stage_visible(self):
        """按「有视频 + 页面可见」决定字幕层显隐。"""
        try:
            show = bool(self.video_path) and self.isVisible()
            if show:
                self.stage.show_over()
            else:
                self.stage.hide_stage()
        except Exception:
            pass

    def _on_stage_cue_clicked(self, idx):
        """在画面上**点一下**某条字幕：单选语义（覆盖时间轴/表格的多选）。"""
        if not (0 <= idx < len(self.doc.cues)):
            return
        self.timeline.set_selected(idx)
        self.table.select_row(idx)
        cue = self.doc.cues[idx]
        self.props.set_cue(cue, idx, len(self.doc.cues))

    def _on_stage_cue_followed(self, idx):
        """**拖动**某条字幕后的主选中跟随：只更新"当前条"，**保留多选**——
        否则 Ctrl+A 全选后拖一下画面字幕，全选就被打散了（用户实测）。"""
        if not (0 <= idx < len(self.doc.cues)):
            return
        self.timeline.selected = idx          # 只改主选中，不动 selected_set
        self.timeline._repaint_cues()
        self.table.reveal_row(idx)
        self.props.set_cue(self.doc.cues[idx], idx, len(self.doc.cues))

    def _on_stage_delete(self, idx):
        """画面右键「删除此字幕」：纯鼠标的删除入口。"""
        if not (0 <= idx < len(self.doc.cues)):
            return
        self._push_undo("删除")
        secore.delete_cues(self.doc.cues, [idx])
        self._after_bulk_change(keep_sel=min(idx, len(self.doc.cues) - 1))
        self._refresh_status("已删除 1 条（画面右键）")

    def _on_stage_command(self, name):
        """画面字幕层激活时的键盘命令（stage 是独立顶层窗口，主窗的
        QShortcut 此刻收不到——见 SubtitleStage.keyPressEvent）。"""
        fn = {"del": self.delete_selected,
              "undo": self.undo_edit,
              "redo": self.redo_edit,
              "all": self.select_all_cues,
              "play": self.toggle_play}.get(name)
        if fn:
            fn()

    def _on_stage_cleared(self):
        self.timeline.set_selected(-1)

    def _on_stage_text(self, idx, text):
        """画面上的就地编辑提交：和列表里改文本走同一条落库路径。"""
        self._on_current_text(idx, text)

    def _on_stage_layout(self, style):
        """画面拖动 / 把手缩放改了版式：并入预览样式。

        v1.14.2：画面上的一切手势只写**自由位置**（pos_x / pos_y）与字号、
        缩放，不再回写 alignment / margin_v —— 所以拖多少次都不会把面板的
        对齐选中态和全局边距改掉（"位置调整是一次性的"）。
        """
        self._preview_style = dict(secore.ASS_DEFAULT_STYLE)
        self._preview_style.update(style or {})
        self._ass_sig = None
        self._save_preview_style()
        self._push_preview(force=True)
        self.props.set_style(self._props_view(self._preview_style))
        self._refresh_status("已调整字幕版式（自由位置）")

    def _on_stage_layout_preview(self, style):
        """拖动 / 缩放**过程中**的实时读数（节流 25Hz，见 SubtitleStage）。

        只刷面板显示：不落盘、不重建预览、不动 `_preview_style` —— 那些都
        留给松手后的 `_on_stage_layout`，否则一串 mouseMove 会变成一串
        json 写盘 + ASS 重建。
        """
        try:
            self.props.set_style(self._props_view(style))
        except Exception:  # noqa: BLE001
            pass

    def _props_view(self, style):
        """给属性面板的显示副本：补上等效「垂直距 / 水平距」。

        面板那两个框的语义是"距对齐边"，而画面上拖动写的是自由位置 pos，
        不做折算就会完全脱节（用户拖动时数字一动不动）。`_va/_ha` 只是
        面板私有读法，不进样式、不落盘。
        """
        view = dict(style or {})
        try:
            view.update(self.stage.panel_metrics() or {})
        except Exception:  # noqa: BLE001
            pass
        return view

    # ---------------------------------------------------------
    # 依赖与提示
    # ---------------------------------------------------------
    def _info(self, kind, title, text, duration=4000):
        try:
            fn = {"ok": InfoBar.success, "warn": InfoBar.warning,
                  "err": InfoBar.error}.get(kind, InfoBar.info)
            fn(title, text, duration=duration, position=InfoBarPosition.TOP,
               parent=self.window() or self)
        except Exception:
            pass

    def _media_tools(self):
        """返回 (ffmpeg, ffprobe)；够不到就抛 RuntimeError 由调用方提示。"""
        if self.ffmpeg and self.ffprobe:
            return self.ffmpeg, self.ffprobe
        try:
            ff, fp = engine.ensure_ffmpeg()
        except SystemExit:
            raise RuntimeError("ffmpeg 不可用（自动下载失败）")
        if not (ff and fp and os.path.isfile(ff) and os.path.isfile(fp)):
            raise RuntimeError("找不到 ffmpeg / ffprobe")
        self.ffmpeg, self.ffprobe = ff, fp
        if self.wave_cache is None:
            self.wave_cache = WaveformCache(engine.DATA_DIR, ff, fp)
        return ff, fp

    def _ensure_player(self, quiet=False):
        """播放器按需创建：窗口真正显示后 winId() 才有效，因此不能提前建。

        构造页面时主窗口还没 show()，此时拿句柄会绑到一个随后被销毁的原生
        窗口上，表现为「有声音没画面」。

        quiet=True：失败不弹 InfoBar（拖时间轴等高频路径用——seek_ms 每次
        mouseMove 都会走到这里，去重 + 静默才能既保住"没视频也能拖时间轴
        定位"又不刷屏）。quiet=False 时同一错误 60 秒内也只提示一次。
        """
        if self.player.available:
            return True
        if not self.player.attach(self.video_host):
            err = self.player.error or "未知原因"
            now = time.monotonic()
            if (not quiet and err != self._player_err_shown
                    and now - self._player_err_at > 60):
                self._info("err", "播放器不可用", err[:300], 8000)
                self._player_err_shown = err
                self._player_err_at = now
            return False
        self._player_err_shown = ""
        return True

    def _install_mpv_async(self, pending_path=""):
        """后台补装 libmpv-2.dll（安装版不随包分发，用户机器上常常没有）。

        成功后自动重试挂播放器；pending_path 记下补装期间用户已选择的视频，
        装好即自动载入——用户对"下载了 39MB"的唯一感知就是"视频能放了"。
        """
        if self._mpv_installing:
            if pending_path:
                self._mpv_pending_path = pending_path
            return
        self._mpv_installing = True
        if pending_path:
            self._mpv_pending_path = pending_path
        self._info("warn", "正在补齐播放组件",
                   "libmpv-2.dll（约 39MB，仅首次）下载中，完成后自动恢复视频预览",
                   10000)

        def work():
            try:
                ok, err = engine.ensure_mpv_dll(self.mpv_dir)
            except Exception as e:  # noqa: BLE001
                ok, err = False, "%s: %s" % (type(e).__name__, e)
            self._mpv_ready.emit(ok, err)

        threading.Thread(target=work, name="vt-mpv-install", daemon=True).start()

    def _on_mpv_ready(self, ok, err):
        self._mpv_installing = False
        if not ok:
            self._info("err", "播放组件补装失败", (err or "未知原因")[:300], 10000)
            return
        self._info("ok", "播放组件已就绪", "视频预览已恢复可用", 5000)
        path = self._mpv_pending_path or self.video_path
        self._mpv_pending_path = ""
        if path and os.path.isfile(path) and self._ensure_player():
            self.player.load(path, autoplay=False)
            # 与 load_media 相同的延迟同步：等 mpv 解出宽高比再贴字幕层/贴合视频框
            QTimer.singleShot(60, self._sync_stage_visible)
            QTimer.singleShot(400, self._sync_stage_visible)
            QTimer.singleShot(60, self._fit_video_frame)
            QTimer.singleShot(400, self._fit_video_frame)

    def _mpv_missing_hint(self):
        dll = os.path.join(self.mpv_dir, "libmpv-2.dll")
        return ("未找到播放组件：\n%s\n\n"
                "请在程序目录执行（首次约 40MB）：\n"
                "    python tools\\download_open_source_deps.py --only mpv\n\n"
                "或到发布页手动下载 libmpv-2.zip 解压到 tools\\mpv\\。\n"
                "该组件为 LGPL 构建，不随安装包分发。" % dll)

    # ---------------------------------------------------------
    # 打开文件
    # ---------------------------------------------------------
    def _confirm_discard(self):
        if not self.dirty:
            return True
        # ⚠️ 用 ConfirmDialog（真·顶层模态），不要用 qfluentwidgets.MessageBox：
        #    后者退化成主窗口里的子控件，会被 mpv 原生子窗口吃掉鼠标、被播放器
        #    占着键盘焦点，表现为「整个框点不动、Esc/空格/回车都没反应」。
        return ConfirmDialog.ask(
            self.window() or self, "字幕尚未保存",
            "当前改动还没写回文件，确定要放弃吗？",
            yes_text="放弃改动", no_text="取消")

    def open_video(self):
        if not self._confirm_discard():
            return
        start = engine.get_saved_download_dir()
        start = start if os.path.isdir(start) else ""
        path, _ = QFileDialog.getOpenFileName(
            self, "打开视频", start, MEDIA_FILE_FILTER)
        if not path:
            return
        self.load_media(path)

    def load_media(self, path):
        """直接按路径载入媒体（拖进窗口 / 命令行入口），不再弹文件对话框。

        v1.13.0：与 open_video 共用同一套载入逻辑；libmpv 本身支持
        av1 / h264 / h265 / x264 等全格式，这里不再限制扩展名。

        v1.14.1：**播放组件缺失不再挡住载入**——此前 _ensure_player 失败
        直接 return，安装版用户（libmpv 不随包分发）连视频都放不进来，
        字幕/波形也一并瘫痪。现在降级载入：波形与字幕表照常（走 ffmpeg，
        与 mpv 无关），画面预览缺失只提示；同时后台自动补装组件，装好即
        自动载入刚才那份视频，无需用户重试。
        """
        if not self._confirm_discard():
            return False
        if not self._ensure_player(quiet=True):
            # 组件缺失：降级载入 + 后台补装，装好后 _on_mpv_ready 自动 load
            self._install_mpv_async(pending_path=path)
        self.video_path = path
        self.video_hint.hide()
        self._refresh_status()
        self._start_waveform(path)
        if self.player.available:
            self.player.load(path, autoplay=False)
            # 视频就绪 → 把画面字幕层贴到视频的**实际显示区域**并显示出来。
            # 延后一帧：此时 mpv 才拿到宽高比，抽黑边算出来的矩形才是准的。
            QTimer.singleShot(60, self._sync_stage_visible)
            QTimer.singleShot(400, self._sync_stage_visible)
            # 视频框自适应比例：mpv 解出 video-params 需要一点时间，两次兜底，
            # `_on_duration` 里还有最后一次（那时比例一定就绪了）。
            QTimer.singleShot(60, self._fit_video_frame)
            QTimer.singleShot(400, self._fit_video_frame)
        return True

    def close_video(self):
        """关闭当前视频，回到"尚未打开视频"的状态。

        只卸视频，**不动字幕**——字幕是独立文档，用户常常是"换一段视频接着
        用同一份字幕"。所以这里不碰 `doc` / `sub_path` / `dirty`。
        """
        if not self.video_path and not self.player.available:
            self._refresh_status("当前没有视频")
            return
        self._wave_stop.set()
        try:
            self.player.close_media()
        except Exception:  # noqa: BLE001
            pass
        self.video_path = ""
        try:
            self.stage.hide_stage()
        except Exception:  # noqa: BLE001
            pass
        self.video_hint.show()
        self.video_hint.raise_()
        # 解除比例封顶，视频框回到铺满状态接住占位提示
        self._fit_video_frame()
        # 波形与时长一起复位，否则时间轴还留着上一段视频的刻度
        self.timeline.set_media(bytearray(), 0, self.timeline.peaks_pps)
        self.timeline.set_cues(self.doc.cues)
        self._ass_sig = None
        self._cur_index = -2
        self._refresh_status("已关闭视频")
        self._sync_current()

    def open_subtitle(self):
        if not self._confirm_discard():
            return
        start = os.path.dirname(self.video_path) if self.video_path else ""
        if not start:
            start = engine.get_saved_download_dir()
            start = start if os.path.isdir(start) else ""
        path, _ = QFileDialog.getOpenFileName(
            self, "打开字幕", start, "字幕文件 (*.srt);;文本文件 (*.txt);;所有文件 (*.*)")
        if path:
            self.load_subtitle(path)

    def load_subtitle(self, path):
        """直接按路径载入字幕（拖进窗口 / 命令行入口）。"""
        if not self._confirm_discard():
            return False
        self._load_subtitle(path)
        return True

    def _load_subtitle(self, path):
        if not path:
            return
        try:
            with open(path, "rb") as fh:
                n, skipped = self.doc.load_bytes(fh.read(), path)
        except OSError as e:
            self._info("err", "读取失败", str(e)[:200])
            return
        self.sub_path = path
        self.undo.clear()
        self.dirty = False
        self.timeline.set_cues(self.doc.cues)
        self.table.load(self.doc.cues)
        self.timeline.set_selected(-1)
        self._sync_duration()
        self._refresh_status()
        self._mark_preview_dirty()
        self._sync_current()
        msg = "已载入 %d 条（编码 %s，换行 %s）" % (
            n, self.doc.src_encoding,
            "CRLF" if self.doc.newline == "\r\n" else "LF")
        if skipped:
            msg += "；跳过 %d 行无法识别的内容" % skipped
        self._info("ok", "字幕已载入", msg)

    def new_subtitle(self):
        if not self._confirm_discard():
            return
        self.doc = secore.SubtitleDoc()
        self.sub_path = ""
        self.undo.clear()
        self.dirty = False
        self.timeline.set_cues(self.doc.cues)
        self.table.load(self.doc.cues)
        self._refresh_status()
        self._mark_preview_dirty()
        self._sync_current()

    def _sync_duration(self):
        """时间轴总长取「视频时长 / 字幕末尾」两者较大值。"""
        dur_ms = self.player.duration_ms
        try:
            self.timeline.set_fps(self.player.fps)   # 帧刻度/帧号用真实帧率
        except Exception:
            pass
        if self.doc.cues:
            dur_ms = max(dur_ms, max(c.end for c in self.doc.cues) + 1000)
        if dur_ms:
            self.timeline.set_media(self.timeline.peaks, dur_ms,
                                    self.timeline.peaks_pps)

    # ---------------------------------------------------------
    # 保存
    # ---------------------------------------------------------
    def save(self):
        if not self.doc.cues:
            self._info("warn", "没有内容", "当前没有可保存的字幕")
            return
        if not self.doc.path:
            self.save_as()
            return
        self._write(self.doc.path)

    def save_as(self):
        if not self.doc.cues:
            self._info("warn", "没有内容", "当前没有可保存的字幕")
            return
        start = self.doc.path or (os.path.splitext(self.video_path)[0] + ".srt"
                                 if self.video_path else "")
        path, _ = QFileDialog.getSaveFileName(
            self, "另存为", start,
            "SRT 字幕 (*.srt);;ASS 字幕，含当前样式 (*.ass);;所有文件 (*.*)")
        if not path:
            return
        self._write(path)

    def _write(self, path):
        # 首次覆盖别人给的文件时留一份 .bak —— 打轴是高风险编辑，
        # 「保存后才发现切错」很常见，有备份就能回退。
        try:
            if os.path.isfile(path) and not os.path.isfile(path + ".bak"):
                with open(path, "rb") as src, open(path + ".bak", "wb") as dst:
                    dst.write(src.read())
        except OSError:
            pass
        try:
            if os.path.splitext(path)[1].lower() in (".ass", ".ssa"):
                # 源文件是 ASS/SSA：按面板样式写出 ASS——本页的 dump 只会
                # SRT，把 SRT 文本灌进 .ass 文件播放器直接读不出来
                cues = sorted(self.doc.cues,
                              key=lambda c: (int(c.start), int(c.end)))
                text = secore.render_ass(cues, self._preview_style)
                with open(path, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(text)
                self.doc.path = path
            else:
                self.doc.save_file(path)
        except OSError as e:
            self._info("err", "保存失败", str(e)[:250])
            return
        self.sub_path = path
        self.dirty = False
        self._info("ok", "已保存", path)
        self._refresh_status()

    def _bak_once(self, path):
        """导出/保存覆盖已存在文件前留一份 .bak（与 _write 同一习惯）。"""
        try:
            if os.path.isfile(path) and not os.path.isfile(path + ".bak"):
                with open(path, "rb") as src, open(path + ".bak", "wb") as dst:
                    dst.write(src.read())
        except OSError:
            pass

    # ---------------------------------------------------------
    # 导出（属性面板右上角「导出」按钮）
    # ---------------------------------------------------------
    def export_subtitle(self):
        """把当前字幕导出成文件，**不改变**当前打开的文件关联。

        与「另存为」的区别：另存为之后编辑的就是新文件（改 sub_path、
        清 dirty）；导出只是"把现在这份（含未保存改动）扔一份出去"，
        原文件关联、未保存标记都原样保留。

        两种格式：
          · SRT —— 纯文本，CRLF + 按原 BOM 习惯（to_bytes）；样式带不走
            （SRT 格式本身没有样式位）。
          · ASS —— 用 `render_ass` 连同面板这套样式字典一起写出，画面上
            预览长什么样、导出的 ASS 播出来就是什么样（含拖出来的
            \\an7\\pos 自由位置）。条目按时间轴排序，空文本条目跳过。

        ⚠️ `render_ass` 的 PlayRes 固定 1920x1080（libass 按容器等比缩放），
        与实际视频分辨率无关；这是预览层的同一套约定，不必按视频改。
        """
        if not self.doc.cues:
            self._info("warn", "没有内容", "当前没有可导出的字幕")
            return
        start = self.doc.path or (os.path.splitext(self.video_path)[0]
                                  if self.video_path else "")
        path, _ = QFileDialog.getSaveFileName(
            self, "导出字幕", start,
            "SRT 字幕 (*.srt);;ASS 字幕，含当前样式 (*.ass);;所有文件 (*.*)")
        if not path:
            return
        if not os.path.splitext(path)[1]:
            path += ".srt"                      # 没写后缀就按 SRT 兜底
        ext = os.path.splitext(path)[1].lower()
        if ext not in (".srt", ".ass"):
            self._info("err", "不支持的格式",
                       "导出只支持 .srt / .ass（当前 %s）" % ext)
            return
        self._bak_once(path)
        # 按时间轴排好再写（与内嵌字幕同一约定；doc 本身的顺序不动）
        cues = sorted(self.doc.cues, key=lambda c: (int(c.start), int(c.end)))

        # 说话人分轨（v1.15.9）：SRT 单文件放不下「说话人」这个维度，检测到
        # 多人时问一句——合成一个文件，还是按人拆成多条独立轨。ASS 不问：
        # 它天生支持多 Style，直接导出成一份彩色多人字幕即可（见 render_ass）。
        if ext == ".srt":
            named = [t for t in secore.split_by_speaker(cues) if t[0]]
            if len(named) >= 2:
                mode = self._ask_speaker_export(len(named))
                if mode == "split":
                    self._export_speaker_tracks(path, secore.split_by_speaker(cues))
                    return
                if mode == "cancel":
                    return

        try:
            if ext == ".ass":
                text = secore.render_ass(cues, self._preview_style)
                with open(path, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(text)
            else:
                data = secore.SubtitleDoc(cues=list(cues)).to_bytes()
                with open(path, "wb") as fh:
                    fh.write(data)
        except OSError as e:
            self._info("err", "导出失败", str(e)[:250])
            return
        self._info("ok", "已导出 " + ext[1:].upper(), path, 6000)

    def _ask_speaker_export(self, n):
        """多人字幕导出 SRT 前询问导出方式。返回 "merge" / "split" / "cancel"。"""
        box = QMessageBox(self)
        box.setWindowTitle("说话人分轨")
        box.setIcon(QMessageBox.Question)
        box.setText("检测到 %d 个说话人，按哪种方式导出 SRT？" % n)
        box.setInformativeText(
            "· 合并为一个文件：所有人同在一份 SRT，行首带 [说话人N] 前缀；\n"
            "· 按说话人拆分：每人一份独立 SRT（各自时间轴，便于独立打轴 / 翻译 / 渲染）。")
        b_merge = box.addButton("合并为一个文件", QMessageBox.AcceptRole)
        b_split = box.addButton("按说话人拆分", QMessageBox.ActionRole)
        box.addButton("取消", QMessageBox.RejectRole)
        box.setDefaultButton(b_merge)
        box.exec_()
        clicked = box.clickedButton()
        if clicked is b_split:
            return "split"
        if clicked is b_merge:
            return "merge"
        return "cancel"

    def _export_speaker_tracks(self, base_path, tracks):
        """把按说话人拆出的多条轨各写一份 SRT（文件名带说话人后缀）。

        每条轨只含该说话人的条目、各自保留原始时间轴——可直接丢进播放器 /
        剪辑软件当独立字幕轨，或逐条翻译、逐人渲染（对应需求里的「字幕独立
        轨」）。无归属轨（说话人识别不到的部分）写成 `-无归属` 后缀。
        """
        root, ext = os.path.splitext(base_path)
        ext = ext or ".srt"
        written = []
        for spk, cs in tracks:
            if not cs:
                continue
            suffix = ("-" + spk) if spk else "-无归属"
            path = "%s%s%s" % (root, suffix, ext)
            self._bak_once(path)
            try:
                with open(path, "wb") as fh:
                    fh.write(secore.SubtitleDoc(cues=list(cs)).to_bytes())
            except OSError as e:
                self._info("err", "分轨导出失败", "%s：%s" % (path, str(e)[:150]))
                return
            written.append(path)
        self._info("ok", "已导出 %d 条独立字幕轨" % len(written),
                   "\n".join(written), 8000)

    # ---------------------------------------------------------
    # 内嵌字幕（原引擎工作台「字幕视频合成」分段，v1.13.x 并到本页）
    # ---------------------------------------------------------
    def open_compose(self):
        """打开「内嵌字幕」对话框。

        用的是**内存里的 cues**（含未保存改动），所以不必先保存——
        这正是把它从引擎工作台搬过来的意义：那边只能吃磁盘上的文件。
        只把字幕挂成独立轨道，音视频 copy、不重新编码。
        """
        if not self.video_path:
            self._info("warn", "先打开视频",
                       "内嵌字幕需要一段视频；字幕用当前编辑的这份")
            return
        if not self.doc.cues:
            self._info("warn", "没有字幕", "先在波形上打轴，或用「插入」新建一条")
            return
        try:
            dlg = ComposeDialog(self, self)
        except Exception as e:  # noqa: BLE001
            self._info("err", "无法打开内嵌面板", str(e)[:200])
            return
        dlg.exec_()

    # ---------------------------------------------------------
    # 波形
    # ---------------------------------------------------------
    def _start_waveform(self, path):
        if self._wave_busy:
            self._wave_stop.set()
        try:
            self._media_tools()
        except RuntimeError as e:
            self._info("err", "无法生成波形", str(e), 6000)
            return
        self._wave_busy = True
        self._wave_stop = threading.Event()
        self.wave_bar.setValue(0)
        self.wave_bar.show()
        self.status.setText("正在解析音频波形…")

        def work():
            try:
                peaks, dur = self.wave_cache.get_or_build(
                    path,
                    on_progress=lambda p: self._wave_progress.emit(int(p)),
                    should_stop=self._wave_stop.is_set)
                if self._wave_stop.is_set():
                    return
                self._wave_ready.emit(peaks, dur)
            except Exception as e:  # noqa: BLE001
                self._wave_failed.emit("%s: %s" % (type(e).__name__, e))

        threading.Thread(target=work, name="vt-waveform", daemon=True).start()

    def _on_wave_progress(self, pct):
        try:
            self.wave_bar.setValue(max(0, min(100, int(pct))))
        except Exception:
            pass

    def _on_wave_ready(self, peaks, dur_sec):
        self._wave_busy = False
        self.wave_bar.hide()
        dur_ms = self.player.duration_ms or int(round(float(dur_sec or 0) * 1000))
        if self.doc.cues:
            dur_ms = max(dur_ms, max(c.end for c in self.doc.cues) + 1000)
        self.timeline.set_media(peaks, dur_ms, self.timeline.peaks_pps)
        self.timeline.set_cues(self.doc.cues)
        self.timeline.fit_all()
        self._refresh_status(
            "波形就绪（%d 个采样点）" % len(peaks) if peaks else "该媒体没有音频轨")

    def _on_wave_failed(self, msg):
        self._wave_busy = False
        self.wave_bar.hide()
        self._refresh_status("波形生成失败：" + msg[:120])

    # ---------------------------------------------------------
    # 播放
    # ---------------------------------------------------------
    def toggle_play(self):
        """空格 / 「播放」按钮：播放暂停。

        ⚠️ 没有视频时**绝不能**顺手弹「打开视频」的文件对话框：用户按空格的
        意图是"播放/暂停"，突然冒出一个占满屏幕的文件对话框，只会被理解成
        "程序全屏了"（用户反馈的"没放视频时按空格会全屏"就是这个）。
        改成一条不打断操作的 InfoBar 提示，顺带告诉他在哪儿打开视频。
        """
        if not self.video_path:
            self._info("warn", "还没有视频",
                       "先打开一段视频（Ctrl+O，或把文件拖进窗口），空格才是播放/暂停")
            return
        if not self._ensure_player():
            return
        self.player.toggle_play()

    def step_frames(self, n):
        if self._table_editing():
            self._forgive_key("Left" if n < 0 else "Right")
            return
        if not self._ensure_player():
            return
        self.player.step_frame(n)

    def nudge(self, delta_ms):
        if not self._ensure_player():
            return
        self.player.nudge_ms(delta_ms)

    def seek_ms(self, ms):
        # quiet：拖时间轴每次 mouseMove 都走到这里，没有视频属正常状态，
        # 静默降级为纯时间轴定位（面板跟着走）；弹窗交给低频动作路径
        if not self._ensure_player(quiet=True):
            self._sync_current(ms)      # 没有视频时也能用时间轴定位，面板照样跟着走
            return
        self.player.seek_ms(ms)

    def goto_cue(self, step):
        """上/下一条：选中并把播放头拉过去。"""
        if not self.doc.cues:
            return
        idx = self.timeline.selected
        if idx < 0:
            # 没选中时从"播放头最近的一条"起步，再按方向挪一格，
            # 这样首次按「下一条」不会看起来"没动"。
            idx = self.doc.nearest_index(self._pos_for_panel())
            idx = max(0, min(len(self.doc.cues) - 1, idx + int(step or 0)))
        else:
            idx = max(0, min(len(self.doc.cues) - 1, idx + step))
        self._select_cue(idx, seek=True)

    def _select_cue(self, idx, seek=False):
        if not (0 <= idx < len(self.doc.cues)):
            return
        self.timeline.set_selected(idx)
        self.table.select_row(idx)
        if seek:
            self.seek_ms(self.doc.cues[idx].start)

    def _on_speed(self, text):
        try:
            self.player.set_speed(float(text))
        except (TypeError, ValueError):
            pass

    def _on_position(self, ms):
        self.timeline.set_position(ms, follow=True)
        self._update_clock(ms)
        self._sync_current(ms)

    def _on_duration(self, ms):
        self._sync_duration()
        self._update_clock(self.player.position_ms)
        # 媒体刚就绪：字幕轨这时挂最稳（loadfile 之后字幕轨会被清空）
        self._push_preview(force=True)
        # 时长都解出来了，video-params 一定就绪——最后一次视频框贴合
        self._fit_video_frame()

    def _on_playing(self, playing):
        self.btn_play.setText("暂停" if playing else "播放")
        try:
            self.btn_play.setIcon(FIF.PAUSE_BOLD if playing else FIF.PLAY_SOLID)
        except Exception:
            pass

    def _update_clock(self, ms):
        total = self.player.duration_ms or self.timeline.duration_ms
        self.lbl_time.setText("%s / %s" % (secore.ms_to_clock(ms),
                                           secore.ms_to_clock(total)))

    # ---------------------------------------------------------
    # 画面字幕预览（cues -> ASS -> mpv 自渲染，不重新编码）
    # ---------------------------------------------------------
    # 为什么由 mpv 渲染而不是用 Qt 画一层浮层：播放器是**原生子窗口**
    # （`MPV(wid=hwnd)`），Windows 上 Qt 控件永远盖不到它上面，浮层会被画面
    # 整个吃掉。让 mpv 自己渲染（libass）反而更准——透明、贴合画面、
    # 逐帧精确，而且完全不需要重新编码。
    def _pos_for_panel(self):
        """面板跟随的时间点：有视频听播放器，没视频用时间轴自己的位置。"""
        return self.player.position_ms if self.video_path else self.timeline.position_ms

    def _mark_preview_dirty(self):
        """cues 内容变了：下次推位置时重建预览字幕，并强制面板重刷。"""
        self._ass_sig = None
        self._cur_index = -2

    def _push_preview(self, force=False):
        """把当前 cues + 样式推给**画面字幕层**（v1.13.2 起不再挂 mpv 字幕轨）。

        为什么改成 Qt 自绘：字幕要能被**点中、拖动、就地改字**，就必须是
        Qt 控件；而 mpv 是原生子窗口，Windows 上盖在它上面的普通 Qt 控件既
        画不出来也收不到鼠标。于是反转过来——预览交给 `SubtitleStage`
        （顶层透明窗口），mpv 只负责画面（`sid=no` 关掉它自己的字幕轨，
        免得内嵌字幕轨和我们叠成两层）。

        样式字典与 `render_ass` 共用同一份（font/size/color/outline/
        alignment/margin_*），所以画面上看到的就是导出成 ASS 时的样子。
        指纹没变就跳过，免得播放时每 40ms 无谓重绘。
        """
        if not self.doc.cues:
            self.stage.set_cues([])
            self.stage.set_speaker_colors({})
            return
        sig = secore.cues_signature(self.doc.cues)
        if not force and sig == self._ass_sig:
            return
        self._ass_sig = sig
        self.stage.set_style(self._preview_style)
        # 彩色多人字幕：把「说话人 -> 颜色」推给字幕层（与 render_ass 同一份
        # 映射），预览里每个说话人一种颜色，导出 ASS 后颜色一致。
        self.stage.set_speaker_colors(secore.speaker_color_map(
            secore.cue_speakers(self.doc.cues)))
        self.stage.set_cues(self.doc.cues)

    def _sync_current(self, ms=None):
        """把属性面板 / 画面字幕层对齐到播放位置。"""
        ms = self._pos_for_panel() if ms is None else ms
        idx = self.doc.index_at(int(ms))
        if idx != self._cur_index:
            self._cur_index = idx
            self.props.set_cue(self.doc.cues[idx] if idx >= 0 else None,
                               idx, len(self.doc.cues))
        self.stage.set_position(int(ms))
        self.stage.set_selected(self.timeline.selected)
        self._push_preview()

    def _on_current_text(self, idx, text):
        if not (0 <= idx < len(self.doc.cues)):
            return
        cue = self.doc.cues[idx]
        new_text = (text or "").replace("\r\n", "\n")
        if new_text == cue.text:
            return
        self._push_undo("改文本")
        cue.text = new_text
        self._after_current_change(idx)

    def _on_current_time(self, idx, start_text, end_text):
        if not (0 <= idx < len(self.doc.cues)):
            return
        cue = self.doc.cues[idx]
        s = secore.clock_to_ms(start_text)
        e = secore.clock_to_ms(end_text)
        if s is None or e is None or (s == cue.start and e == cue.end):
            self._cur_index = -2          # 输入非法或没改动：把显示复原
            self._sync_current()
            return
        self._push_undo("改时间")
        secore.set_boundary(self.doc.cues, idx, "start", s)
        secore.set_boundary(self.doc.cues, idx, "end", e)
        self._after_current_change(idx)
        self._sync_duration()

    def _after_current_change(self, idx):
        """单条改动后的统一收尾：表格 / 时间轴 / 预览 / 状态栏一起刷新。"""
        if 0 <= idx < len(self.doc.cues):
            self.table.refresh_row(idx, self.doc.cues[idx])
        self.timeline.update()
        self._mark_preview_dirty()
        self._sync_current()
        self._refresh_status()

    def _on_style_changed(self, style):
        """预览样式变了：整份重建（参数只有十来个，重生成比增量改简单）。

        ⚠️ 自由位置的取舍（v1.14.2）：**位置类参数**变了才丢弃 pos_x/pos_y
        —— 那等于用户在用「对齐 / 边距」重新定位，属于"一次性调整"，得让
        新位置说了算；改字号、颜色、描边这类**非位置**参数则要保住已经拖
        好的自由位置，否则"拖好位置再改字号"会当场跳回对齐位置。
        """
        old = self._preview_style or {}
        style = style or {}
        new = dict(secore.ASS_DEFAULT_STYLE)
        new.update(style)
        if "pos_x" in style or "pos_y" in style:
            # 样式里**显式**带了 pos 键 = 面板「回到对齐位置」按钮按下了，
            # 清掉自由位置（值本来就是 None，这里只是把语义写明确）
            new["pos_x"], new["pos_y"] = style.get("pos_x"), style.get("pos_y")
        elif not any(new.get(k) != old.get(k) for k in self.POS_KEYS):
            # 非位置类调整（字号 / 颜色 / 描边…）：保住已拖好的自由位置
            new["pos_x"], new["pos_y"] = old.get("pos_x"), old.get("pos_y")
        # 否则：位置类参数变了（对齐九宫格 / 边距）→ 保持默认 None，
        # 于是新对齐立刻生效，自由位置作废 —— 这就是"一次性调整"。
        self._preview_style = new
        self._save_preview_style()
        self._ass_sig = None
        self._push_preview(force=True)
        self.props.set_style(self._props_view(self._preview_style))  # 面板读数同步

    # ---------------------------------------------------------
    # 预览样式的持久化
    # ---------------------------------------------------------
    # 字体 / 颜色 / 描边 / 对齐 / 边距既是**画面上的预览**，也是导出 ASS 时用的
    # 同一份参数，所以理应跟项目走、而不是每次启动重来。落一个小 json 到数据
    # 根目录即可；**绝不写回用户的 .srt**——样式从来不属于字幕文件。
    STYLE_FILE = "subtitle_style.json"

    #: 位置类样式键：改动它们 = 用户在用「对齐 / 边距」重新定位，
    #: 此时丢弃画面拖动产生的自由位置（见 _on_style_changed）
    POS_KEYS = ("alignment", "margin_v", "margin_l", "margin_r")

    def _style_path(self):
        return os.path.join(engine.DATA_DIR, self.STYLE_FILE)

    def _load_preview_style(self):
        """读回上次的样式；文件缺失/损坏就退回默认（不抛异常）。"""
        try:
            with open(self._style_path(), encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                # 只认当前版本认得的键：旧版残留字段不会把样式搞乱
                return {k: v for k, v in data.items()
                        if k in secore.ASS_DEFAULT_STYLE}
        except Exception:  # noqa: BLE001
            pass
        return {}

    def _save_preview_style(self):
        """原子落盘（先写 .part 再 replace），失败静默。"""
        try:
            path = self._style_path()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".part"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self._preview_style, fh, ensure_ascii=False, indent=1)
            os.replace(tmp, path)
        except Exception:  # noqa: BLE001
            pass

    # ---------------------------------------------------------
    # 撤销 / 重做
    # ---------------------------------------------------------
    def _push_undo(self, label, snapshot=None):
        self.undo.push(self.doc.cues, label, snapshot=snapshot)
        self.dirty = True

    def undo_edit(self):
        snap, label = self.undo.undo(self.doc.cues)
        if snap is None:
            self._refresh_status("没有可撤销的操作")
            return
        self.doc.restore(snap)
        self.dirty = True
        self._after_bulk_change()
        self._refresh_status("已撤销：" + (label or "操作"))

    def redo_edit(self):
        snap, label = self.undo.redo(self.doc.cues)
        if snap is None:
            self._refresh_status("没有可重做的操作")
            return
        self.doc.restore(snap)
        self.dirty = True
        self._after_bulk_change()
        self._refresh_status("已重做：" + (label or "操作"))

    def _after_bulk_change(self, keep_sel=None):
        """条数/顺序可能都变了，表格与时间轴整体重建。"""
        self.timeline.set_cues(self.doc.cues)
        self.table.load(self.doc.cues)
        if keep_sel is not None and 0 <= keep_sel < len(self.doc.cues):
            self._select_cue(keep_sel)
        else:
            self.timeline.set_selected(-1)
        self._sync_duration()
        self._refresh_status()
        self._mark_preview_dirty()
        self._sync_current()

    # ---------------------------------------------------------
    # 选中
    # ---------------------------------------------------------
    def _on_timeline_cue_selected(self, idx):
        # 时间轴上可能是多选（框选 / Ctrl 点选），表格要跟着整批同步
        idxs = self.timeline.selected_indices()
        if idxs:
            self.table.select_rows(idxs, scroll=(len(idxs) == 1))
        if not (0 <= idx < len(self.doc.cues)):
            return
        # 播放头不在该条内时跟过去——打轴时这一步能省掉大量拖动
        c = self.doc.cues[idx]
        pos = self.player.position_ms
        if not (c.start <= pos < c.end):
            self.seek_ms(c.start)

    def _on_table_selection(self, idx):
        self.timeline.set_selected(idx)

    def _on_drag_started(self):
        # 拖拽是「边改边看」，快照必须此刻先存下来，等真正动了再压栈
        self._pre_drag = self.doc.snapshot()
        self._drag_pushed = False

    def _on_cue_dragged(self, idx, mode, value):
        """拖动时间轴上的字幕块（高频路径，每帧都会来一次）。

        两处刻意省掉的动作：
          · 抽屉收起时（默认）不刷表格——看不见的东西没必要重排；
          · 状态栏按 120ms 节流——`_refresh_status` 里的 stats 会遍历全部
            cues，字幕几百条时每帧一次全表统计，是拖动卡顿的隐形大头。
        """
        if not self._drag_pushed and self._pre_drag is not None:
            self._push_undo("拖动时间", snapshot=self._pre_drag)
            self._drag_pushed = True
        if 0 <= idx < len(self.doc.cues):
            if self.table_shell.isVisible():
                self.table.refresh_row(idx, self.doc.cues[idx])
            self._status_throttled()

    def _status_throttled(self, interval_ms=120):
        """高频路径上的状态栏刷新节流（统计要遍历全部 cues，不便宜）。"""
        now = time.time() * 1000.0
        if now - getattr(self, "_status_t", 0.0) < interval_ms:
            return
        self._status_t = now
        self._refresh_status()

    def _on_drag_finished(self):
        self._pre_drag = None
        self._drag_pushed = False
        self._status_t = 0.0          # 让收尾那次刷新不被节流吞掉
        # 多选批量平移（全选后拖一条，全部选中条一起动）：拖动中为省性能
        # 只刷被拖的那一行，松手把其余选中行的时间列一并刷掉
        rows = self.timeline.selected_indices()
        if len(rows) > 1 and self.table_shell.isVisible():
            for r in rows:
                if 0 <= r < len(self.doc.cues):
                    self.table.refresh_row(r, self.doc.cues[r])
        self._refresh_status()
        self._sync_duration()
        # 拖拽是高频路径：过程中不重建预览字幕，松手后统一来一次
        self._mark_preview_dirty()
        self._sync_current()

    def _on_split_requested(self, ms):
        self.split_at(ms)

    def _on_cell_committed(self, row, col, text):
        if not (0 <= row < len(self.doc.cues)):
            return
        c = self.doc.cues[row]
        if col == 1:
            ms = secore.clock_to_ms(text)
            if ms is None:
                self.table.refresh_row(row, c)
                return
            self._push_undo("改起点")
            secore.set_boundary(self.doc.cues, row, "start", ms)
        elif col == 2:
            ms = secore.clock_to_ms(text)
            if ms is None:
                self.table.refresh_row(row, c)
                return
            self._push_undo("改终点")
            secore.set_boundary(self.doc.cues, row, "end", ms)
        elif col == 4:
            new_text = text.replace(self.NL_SEP, "\n")
            if new_text == c.text:
                return
            self._push_undo("改文本")
            c.text = new_text
        else:
            return
        self.table.refresh_row(row, c)
        self.timeline.update()
        self._sync_duration()
        self._refresh_status()
        self._mark_preview_dirty()
        self._sync_current()

    # ---------------------------------------------------------
    # 编辑操作
    # ---------------------------------------------------------
    def _target_index(self):
        """当前要作用的那一条：优先表格多选里的第一条，其次时间轴选中。"""
        rows = self.table.selected_rows()
        if rows:
            return rows[0]
        idxs = self.timeline.selected_indices()
        return idxs[0] if idxs else -1

    def _selected_indices(self):
        """当前选中的全部下标（表格多选优先，其次时间轴多选）。"""
        rows = self.table.selected_rows()
        if rows:
            return rows
        return self.timeline.selected_indices()

    def select_all_cues(self):
        """Ctrl+A：全选字幕（表格抽屉展开时一并同步）。"""
        w = QApplication.focusWidget()
        if w is not None and w.metaObject().className() in (
                "QLineEdit", "QTextEdit", "QPlainTextEdit", "QSpinBox",
                "QDoubleSpinBox", "QAbstractSpinBox", "QComboBox"):
            self._forgive_key("Ctrl+A")      # 焦点在输入框 → 交还"全选文本"
            return
        if not self.doc.cues:
            self._refresh_status("还没有字幕")
            return
        all_idx = range(len(self.doc.cues))
        self.timeline.set_selection(all_idx)
        self.table.select_rows(all_idx, scroll=False)
        # 画面层的选中框是**单条**语义：全选后继续亮着旧的一条会显得
        # "那条被单独锁定、全选对画面无效"——清掉它
        self.stage.set_selected(-1)
        self._refresh_status("已全选 %d 条" % len(self.doc.cues))

    def split_at_playhead(self):
        pos = self.player.position_ms
        if not self.video_path:
            pos = self.timeline.position_ms
        self.split_at(pos)

    def split_at(self, ms):
        idx = self.doc.index_at(ms)
        if idx < 0:
            idx = self._target_index()
        if idx < 0:
            self._refresh_status("没有可切分的条目")
            return
        self._push_undo("切分")
        if not secore.split_cue(self.doc.cues, idx, ms):
            self.undo.undo(self.doc.cues)      # 落不下去就把刚才的快照撤回来
            self._refresh_status("切分位置太靠近边界（每条至少保留 %.0fms）"
                                 % secore.MIN_DURATION_MS)
            return
        self._after_bulk_change(keep_sel=idx + 1)

    def merge_selected(self):
        rows = self.table.selected_rows()
        if len(rows) < 2:
            self._refresh_status("合并需要选中至少两条")
            return
        self._push_undo("合并")
        new_idx = secore.merge_cues(self.doc.cues, rows)
        self._after_bulk_change(keep_sel=new_idx)

    def delete_selected(self):
        rows = self._selected_indices()
        if not rows:
            self._refresh_status("没有选中的条目")
            return
        self._push_undo("删除")
        secore.delete_cues(self.doc.cues, rows)
        self._after_bulk_change(keep_sel=min(rows))
        self._refresh_status("已删除 %d 条（Ctrl+Z 可撤销）" % len(rows))

    def insert_at_playhead(self):
        pos = self.player.position_ms if self.video_path else self.timeline.position_ms
        self._push_undo("插入")
        idx = secore.insert_cue(self.doc.cues, pos, 1500, "")
        self._after_bulk_change(keep_sel=idx)
        self.table.editItem(self.table.item(idx, 4))

    def set_start_here(self):
        self._set_boundary_here("start")

    def set_end_here(self):
        self._set_boundary_here("end")

    def _set_boundary_here(self, which):
        idx = self._target_index()
        if idx < 0:
            self._refresh_status("先选中一条字幕")
            return
        pos = self.player.position_ms if self.video_path else self.timeline.position_ms
        self._push_undo("取起点" if which == "start" else "取终点")
        ok = secore.set_boundary(self.doc.cues, idx, which, pos)
        if not ok:
            self.undo.undo(self.doc.cues)
            self._refresh_status("该时间点无法作为边界（会把条目压得过短）")
            return
        self.table.refresh_row(idx, self.doc.cues[idx])
        self.timeline.update()
        self._refresh_status()

    def shift_selected(self, delta_ms):
        rows = self._selected_indices()
        if not rows:
            self._refresh_status("先选中要平移的条目")
            return
        self._push_undo("平移选中的条目")
        moved = secore.shift_cues(self.doc.cues, rows, delta_ms)
        self._after_bulk_change(keep_sel=min(rows))
        self._refresh_status("已平移 %+dms" % moved)

    def shift_all(self, delta_ms):
        if not self.doc.cues:
            return
        self._push_undo("整轨平移")
        moved = secore.shift_all(self.doc.cues, delta_ms)
        self._after_bulk_change()
        self._refresh_status("整轨平移 %+dms" % moved)

    def fix_overlaps(self):
        self._push_undo("消除重叠")
        n = secore.fix_overlaps(self.doc.cues)
        if not n:
            self.undo.undo(self.doc.cues)
            self._refresh_status("没有相邻重叠")
            return
        self._after_bulk_change()
        self._refresh_status("已修正 %d 处重叠" % n)

    def clamp_zero(self):
        self._push_undo("修正零长条目")
        n = secore.clamp_zero_length(self.doc.cues)
        if not n:
            self.undo.undo(self.doc.cues)
            self._refresh_status("没有零长/倒挂的条目")
            return
        self._after_bulk_change()
        self._refresh_status("已修正 %d 条" % n)

    def renumber(self):
        self._push_undo("重新排序")
        secore.renumber(self.doc.cues)
        self._after_bulk_change()

    def fit_selected(self):
        """把视图缩放到选中条目所在区间（找不到选中就整轨）。"""
        rows = self._selected_indices()
        tw = max(200, self.timeline.width())
        if rows:
            c0 = self.doc.cues[rows[0]]
            c1 = self.doc.cues[rows[-1]]
            span = max(1000, c1.end - c0.start)
            self.timeline.pixels_per_second = max(
                4.0, min(4000.0, tw * 1000.0 / span * 0.9))
            self.timeline.view_start_ms = max(0, int(c0.start - span * 0.05))
            self.timeline.update()
        else:
            self.timeline.fit_all()

    # ---------------------------------------------------------
    # 状态栏
    # ---------------------------------------------------------
    def _refresh_status(self, extra=""):
        st = secore.stats(self.doc.cues)
        parts = []
        parts.append("视频：" + (os.path.basename(self.video_path) if self.video_path
                                else "未打开"))
        parts.append("字幕：" + (os.path.basename(self.sub_path) if self.sub_path
                                else "未保存"))
        parts.append("%d 条 / %d 字" % (st["count"], st["chars"]))
        if st["overlaps"]:
            parts.append("重叠 %d" % st["overlaps"])
        if st["zero"]:
            parts.append("过短 %d" % st["zero"])
        parts.append("编码 %s/%s" % (self.doc.src_encoding,
                                    "CRLF" if self.doc.newline == "\r\n" else "LF"))
        parts.append("缩放 %.0fpx/s" % self.timeline.pixels_per_second)
        if self.dirty:
            parts.append("● 未保存")
        if extra:
            parts.append(extra)
        try:
            self.status.setText("　|　".join(parts))
        except Exception:
            pass


def build_page(app, parent=None):
    """注册表 GuiSpec.builder 入口（subtitle_edit 功能页）。"""
    return SubtitleEditPage(app, parent)