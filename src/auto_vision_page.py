#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# @version 1.18.3
"""「自动化」页 —— B 站自动投稿（v1.17.x 起精简为投稿专用）
====================================================================
页面只做一件事：用内置视觉引擎（`auto_vision_core`）驱动用户自己已登录
的浏览器窗口完成 B 站投稿，分两张卡片：

  ① 目标窗口 · 模板采集  选浏览器窗口 → 抓帧 → 在预览上框选目标元素 →
                        存成投稿管线要用的模板（清单见 `bili_upload` 的
                        `TEMPLATE_MANIFEST`，落 `data/auto_vision/bili/`）；
  ② 投稿任务 · 执行     视频/标题/简介/标签/分区/话题表单，可从视频所在目录的
                        `视频信息.txt` 一键读取；投稿跑在后台线程，阶段 /
                        进度 / 日志经信号回主线程，失败自动留整屏截图。

声明式投稿管线与模板清单都在 `bili_upload.py`（不碰 Qt，可单独单测），
本页只是它的界面外壳。为什么单独成模块（而不是像其余页面那样写进
video_toolbox_qt.py）：主文件里的页面共享 `ScrollPage` / `card()` /
`row()`，页面独立成模块会反向 import 主文件形成循环导入。本页自带一套
等价的壳（`_card` / `_row`），只依赖 `ui_theme` 与 qfluentwidgets，于是
主文件里只需要 3 行注册代码。

⚠ 边界：视觉 + 鼠标/键盘注入，不碰浏览器进程；默认**演练模式**（只识别、
只标注），要真跑必须手动关掉演练开关。
"""

import os
import tempfile
import time

import numpy as np
from PIL import Image
from PyQt5.QtCore import Qt, QRect, QThread, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QLabel,
                             QPlainTextEdit, QSizePolicy, QVBoxLayout, QWidget)

from qfluentwidgets import (CaptionLabel, ComboBox, FluentIcon as FIF,
                            InfoBar, InfoBarPosition, LineEdit,
                            PrimaryPushButton, ProgressBar, PushButton,
                            ScrollArea, StrongBodyLabel, SubtitleLabel,
                            SwitchButton, TextEdit)

import auto_vision_core as av
import bili_upload as bu
import ui_theme

#: 程序数据目录（模板 / 失败截图都落在这里）；取不到就退到临时目录
try:
    import video_toolbox as _engine
    DATA_DIR = _engine.DATA_DIR
except Exception:  # noqa: BLE001
    DATA_DIR = os.path.join(tempfile.gettempdir(), "video_toolbox_data")


# ---------------------------------------------------------------------- #
# 页面壳：与主文件 card()/row() 等价的最小实现（避免反向 import 主文件）
# ---------------------------------------------------------------------- #
def _card(title=None, caption=None):
    box = ui_theme.UICard()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(14, 12, 14, 14)
    lay.setSpacing(8)
    if title:
        lay.addWidget(StrongBodyLabel(title, box))
    if caption:
        cap = CaptionLabel(caption, box)
        cap.setWordWrap(True)
        lay.addWidget(cap)
    return box, lay


def _row(*widgets, spacing=8):
    holder = QWidget()
    lay = QHBoxLayout(holder)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(spacing)
    for w in widgets:
        if w is None:
            lay.addStretch(1)
        else:
            lay.addWidget(w)
    return holder


def _tip(level, title, text, parent):
    try:
        getattr(InfoBar, level)(title, text, duration=3500,
                                position=InfoBarPosition.BOTTOM_RIGHT,
                                parent=parent)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------- #
# 抓帧预览：等比缩放显示 + 鼠标框选（模板采集就靠它框出目标元素）
# ---------------------------------------------------------------------- #
class ShotView(QLabel):
    """显示抓到的画面；支持拖拽框选，并把选中区域换算回**帧像素坐标**。"""

    selectionChanged = pyqtSignal(int, int, int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(300)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(320)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(
            "QLabel{background:#1e2228;border:1px solid #3a4250;"
            "border-radius:8px;color:#8a94a6;}")
        self.setText("还没有画面 —— 先选一个窗口，点「抓帧」")
        self._pix = None
        self._frame_size = (0, 0)
        self._img_rect = QRect()
        self._sel = None
        self._drag_from = None
        self.setMouseTracking(True)

    # -- 数据入口 ----------------------------------------------------- #
    def set_frame(self, frame_rgb):
        h, w = frame_rgb.shape[:2]
        arr = np.ascontiguousarray(frame_rgb, dtype=np.uint8)
        img = QImage(arr.data, w, h, 3 * w, QImage.Format_RGB888).copy()
        self._pix = QPixmap.fromImage(img)
        self._frame_size = (w, h)
        self._sel = None
        self._drag_from = None
        self.setText("")          # 清掉占位文字，免得等比缩放留白处露出来
        self.update()

    def selection(self):
        return self._sel

    # -- 坐标换算 ----------------------------------------------------- #
    def _fit_rect(self):
        if self._pix is None:
            return QRect()
        pw, ph = self._pix.width(), self._pix.height()
        if pw <= 0 or ph <= 0:
            return QRect()
        s = min((self.width() - 4) / pw, (self.height() - 4) / ph)
        dw, dh = int(pw * s), int(ph * s)
        return QRect((self.width() - dw) // 2, (self.height() - dh) // 2,
                     dw, dh)

    def _to_frame(self, pt):
        r = self._img_rect
        if r.isEmpty() or self._pix is None:
            return (0, 0)
        sx = self._pix.width() / float(r.width())
        sy = self._pix.height() / float(r.height())
        return (int((pt.x() - r.x()) * sx), int((pt.y() - r.y()) * sy))

    # -- 交互 --------------------------------------------------------- #
    def mousePressEvent(self, e):
        if self._pix is not None and self._img_rect.contains(e.pos()):
            self._drag_from = e.pos()
            self._sel = None
            self.update()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag_from is not None:
            self._sel = QRect(self._drag_from, e.pos()).normalized()
            self.update()
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._drag_from is not None:
            r = QRect(self._drag_from, e.pos()).normalized()
            self._drag_from = None
            if r.width() > 6 and r.height() > 6:
                x0, y0 = self._to_frame(r.topLeft())
                x1, y1 = self._to_frame(r.bottomRight())
                w, h = max(1, x1 - x0), max(1, y1 - y0)
                fw, fh = self._frame_size
                x0 = max(0, min(x0, fw - 1))
                y0 = max(0, min(y0, fh - 1))
                w = max(1, min(w, fw - x0))
                h = max(1, min(h, fh - y0))
                self._sel = r
                self.selectionChanged.emit(x0, y0, w, h)
            else:
                self._sel = None
            self.update()
        super().mouseReleaseEvent(e)

    # -- 绘制 --------------------------------------------------------- #
    def paintEvent(self, e):
        super().paintEvent(e)
        if self._pix is None:
            return
        # ⚠ paintEvent 里抛出的异常会被 Qt 吞掉并直接 abort 进程（没有任何
        # traceback），所以这里整体兜底：宁可画不出来，也不能让程序崩。
        try:
            self._paint_overlay()
        except Exception:  # noqa: BLE001
            pass

    def _paint_overlay(self):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        self._img_rect = self._fit_rect()
        p.drawPixmap(self._img_rect, self._pix)
        # 框选区域（蓝）
        if self._sel is not None:
            p.setPen(QPen(QColor(64, 158, 255), 2, Qt.DashLine))
            p.setBrush(QColor(64, 158, 255, 40))
            p.drawRect(self._sel)
        p.end()


# ---------------------------------------------------------------------- #
# 投稿执行线程：把 bili_upload.run_submission 放后台，日志/阶段经信号回主线程
# ---------------------------------------------------------------------- #
class BiliUploadWorker(QThread):
    """后台跑一次投稿。

    ⚠ 工作线程**绝不能直接碰 Qt 控件**（会崩或随机死锁），所有回显都走信号：
    `logged` / `staged` / `done`。
    """

    logged = pyqtSignal(str)
    staged = pyqtSignal(str, str)          # (node_name, 阶段文案)
    done = pyqtSignal(dict)

    def __init__(self, task, win, dry_run, data_dir, parent=None):
        super().__init__(parent)
        self.task = task
        self.win = win
        self.dry_run = dry_run
        self.data_dir = data_dir

    def run(self):  # noqa: D102 - QThread 入口
        try:
            res = bu.run_submission(
                task=self.task, win=self.win, dry_run=self.dry_run,
                data_dir=self.data_dir,
                on_log=self.logged.emit,
                on_stage=lambda n, l: self.staged.emit(n, l))
        except Exception as exc:  # noqa: BLE001
            self.logged.emit(f"[E] 投稿线程异常：{type(exc).__name__}: {exc}")
            res = {"ok": False, "reached": [], "failed_at": "exception",
                   "steps": [], "screenshot": None, "missing": []}
        self.done.emit(res)


# ---------------------------------------------------------------------- #
# 页面
# ---------------------------------------------------------------------- #
class AutoVisionPage(QWidget):
    """「自动化」导航页（B 站投稿专用）。"""

    def __init__(self, app=None, parent=None):
        super().__init__(parent)
        self.app = app
        self.setObjectName("AutoVisionPage")

        self._frame = None            # 最近一次抓帧（模板采集的素材）
        self._sel = (0, 0, 0, 0)      # 预览上的框选区域（帧像素坐标）
        self._bili_worker = None      # 投稿后台线程（一次一个）

        self._build()

    # ---------------- 布局 ---------------- #
    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 16, 24, 18)
        outer.setSpacing(10)
        outer.addWidget(SubtitleLabel("自动化 · B 站投稿", self))
        cap = CaptionLabel(
            "用内置视觉引擎驱动你自己已登录的浏览器窗口投稿 B 站："
            "先在下面选窗口、抓帧、采集模板，再填任务、演练确认后真跑。"
            "全程只看屏幕、模拟键鼠，不碰浏览器进程；默认演练模式，"
            "不会真的动你的鼠标键盘。", self)
        cap.setWordWrap(True)
        outer.addWidget(cap)

        self.area = ScrollArea(self)
        self.area.setWidgetResizable(True)
        self.area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.area.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        holder = QWidget(self.area)
        holder.setStyleSheet("QWidget{background:transparent;}")
        lay = QVBoxLayout(holder)
        lay.setContentsMargins(4, 2, 12, 16)
        lay.setSpacing(12)
        self.area.setWidget(holder)
        outer.addWidget(self.area, 1)
        self.vbox = lay

        self.vbox.addWidget(self._card_capture())
        self.vbox.addWidget(self._card_bili())
        self.vbox.addStretch(1)

    # ---------------- ① 目标窗口 · 模板采集 ---------------- #
    def _card_capture(self):
        box, lay = _card(
            "目标窗口 · 模板采集",
            "先在浏览器里打开 B 站投稿页并登录，再在这里选中该窗口、抓帧；"
            "在预览上按住左键框选目标元素，存成投稿管线要用的模板。")
        self.win_combo = ComboBox()
        self.win_combo.setMinimumWidth(360)
        btn_refresh = PushButton("刷新窗口", icon=FIF.SYNC)
        btn_refresh.clicked.connect(self.refresh_windows)
        self.btn_shot = PrimaryPushButton("抓帧", icon=FIF.CAMERA)
        self.btn_shot.clicked.connect(self.take_shot)
        self.pw_switch = SwitchButton()
        self.pw_switch.setOnText("兜底")
        self.pw_switch.setOffText("兜底")
        self.pw_switch.setChecked(False)
        lay.addWidget(_row(self.win_combo, btn_refresh, self.btn_shot,
                           CaptionLabel("PrintWindow"), self.pw_switch))
        lay.addWidget(_row(CaptionLabel(
            "提示：目标窗口不要被别的窗口完全盖住——抓帧走的是屏幕拷贝；"
            "被遮挡时可打开「兜底」改用 PrintWindow（对 GPU 渲染的窗口可能全黑）。")))
        self.shot_view = ShotView()
        self.shot_view.selectionChanged.connect(self._on_selection)
        lay.addWidget(self.shot_view)
        self.capture_status = CaptionLabel("尚未抓帧")
        lay.addWidget(self.capture_status)

        # —— 模板采集 ——
        self.bili_tpl_combo = ComboBox()
        self.bili_tpl_combo.setMinimumWidth(250)
        btn_save = PushButton("把框选存为该模板", icon=FIF.SAVE)
        btn_save.clicked.connect(self._bili_save_template)
        btn_tpl_dir = PushButton("模板目录", icon=FIF.FOLDER)
        btn_tpl_dir.clicked.connect(self._bili_open_template_dir)
        lay.addWidget(_row(CaptionLabel("采集模板"), self.bili_tpl_combo,
                           btn_save, btn_tpl_dir))
        self.bili_tpl_status = CaptionLabel("")
        self.bili_tpl_status.setWordWrap(True)
        lay.addWidget(self.bili_tpl_status)

        self.refresh_windows()
        self._bili_refresh_tpl_combo()
        return box

    # -- 窗口 / 抓帧 -- #
    def refresh_windows(self):
        self.win_combo.clear()
        self._wins = av.list_windows()
        if not self._wins:
            self.win_combo.addItem("（没找到可用窗口）", userData=None)
            return
        for w in self._wins:
            size = f"{w.size[0]}×{w.size[1]}"
            self.win_combo.addItem(f"{w.title[:46]}  [{size}]", userData=w.hwnd)
        self.capture_status.setText(f"找到 {len(self._wins)} 个可见窗口，"
                                    f"请选择一个后点「抓帧」")

    def _selected_window(self):
        hwnd = self.win_combo.currentData()
        if not hwnd:
            return None
        for w in getattr(self, "_wins", []):
            if w.hwnd == hwnd:
                return w
        return av.window_info(hwnd)

    def take_shot(self):
        win = self._selected_window()
        if win is None:
            _tip("warning", "提示", "先在上面的下拉框里选一个目标窗口", self)
            return
        try:
            frame, origin, cost = av.capture_window(
                win, use_printwindow=self.pw_switch.isChecked())
        except Exception as exc:  # noqa: BLE001
            _tip("error", "抓帧失败", f"{type(exc).__name__}: {exc}", self)
            return
        self._frame = frame
        self.shot_view.set_frame(frame)
        self.capture_status.setText(
            f"已抓帧：{frame.shape[1]}×{frame.shape[0]} 像素，"
            f"用时 {cost:.0f} ms，客户区屏幕原点 ({origin[0]}, {origin[1]})")

    def _on_selection(self, x, y, w, h):
        self._sel = (x, y, w, h)
        self.capture_status.setText(
            f"框选区域：x={x} y={y} w={w} h={h}（相对客户区）"
            f"　—— 可在下方「采集模板」里点「把框选存为该模板」")

    # -- 模板清单 -- #
    def _bili_refresh_tpl_combo(self):
        tdir = bu.template_dir(DATA_DIR)
        cur = self.bili_tpl_combo.currentData()
        self.bili_tpl_combo.blockSignals(True)
        self.bili_tpl_combo.clear()
        for item in bu.TEMPLATE_MANIFEST:
            has = os.path.isfile(os.path.join(tdir, item["file"]))
            mark = "✓" if has else "✗"
            label = f"{mark} {item['label']}" + ("（可选）" if item.get("optional")
                                                else "")
            self.bili_tpl_combo.addItem(label, userData=item["key"])
        self.bili_tpl_combo.blockSignals(False)
        if cur:
            idx = self.bili_tpl_combo.findData(cur)
            if idx >= 0:
                self.bili_tpl_combo.setCurrentIndex(idx)
        miss = bu.missing_templates(DATA_DIR)                    # 只算必需
        miss_all = bu.missing_templates(DATA_DIR, include_optional=True)
        total = len(bu.TEMPLATE_MANIFEST)
        self.bili_tpl_status.setText(
            f"模板目录：{tdir}\n"
            f"已采集 {total - len(miss_all)}/{total} 张；必需还差 {len(miss)} 张"
            + (f"：{'、'.join(m['label'] for m in miss)}" if miss else "（已齐）")
            + "。采集方法：在上面选中投稿页窗口 → 抓帧 → 在预览上框出该元素 → "
              "点「把框选存为该模板」。")

    def _bili_cur_tpl(self):
        key = self.bili_tpl_combo.currentData()
        for item in bu.TEMPLATE_MANIFEST:
            if item["key"] == key:
                return item
        return None

    def _bili_save_template(self):
        item = self._bili_cur_tpl()
        if item is None:
            _tip("warning", "提示", "先在「采集模板」下拉框里选一个模板项", self)
            return
        if self._frame is None:
            _tip("warning", "提示", "先抓帧（上面的「抓帧」按钮）", self)
            return
        x, y, w, h = self._sel
        if w < 6 or h < 6:
            _tip("warning", "提示", "先在预览图上按住左键框选该元素（至少 6×6）", self)
            return
        crop = self._frame[y:y + h, x:x + w]
        tdir = bu.template_dir(DATA_DIR)
        os.makedirs(tdir, exist_ok=True)
        path = os.path.join(tdir, item["file"])
        try:
            Image.fromarray(crop).save(path)
        except Exception as exc:  # noqa: BLE001
            _tip("error", "保存模板失败", str(exc), self)
            return
        _tip("success", "模板已保存", f"{item['label']} → {item['file']}"
             f"（{w}×{h}）", self)
        self._bili_refresh_tpl_combo()

    def _bili_open_template_dir(self):
        tdir = bu.template_dir(DATA_DIR)
        os.makedirs(tdir, exist_ok=True)
        self._open_path(tdir)

    def _bili_open_shot_dir(self):
        sdir = bu.screenshot_dir(DATA_DIR)
        os.makedirs(sdir, exist_ok=True)
        self._open_path(sdir)

    def _open_path(self, path):
        try:
            os.startfile(path)          # noqa: S606 - Windows 专用，仅本机
        except Exception:  # noqa: BLE001
            try:
                import subprocess
                subprocess.Popen(["explorer", os.path.normpath(path)])
            except Exception:  # noqa: BLE001
                _tip("warning", "提示", f"路径：{path}", self)

    # ---------------- ② 投稿任务 · 执行 ---------------- #
    def _card_bili(self):
        box, lay = _card(
            "B 站投稿任务",
            "填任务（或点「从 视频信息.txt 读取」一键带入视频所在目录里的物料）→ "
            "开始投稿。默认演练模式（只识别不真点），确认无误后再切「真跑」。")

        self.bili_video = LineEdit()
        self.bili_video.setPlaceholderText("视频文件完整路径")
        btn_pick = PushButton("浏览…", icon=FIF.FOLDER)
        btn_pick.clicked.connect(self._bili_pick_video)
        btn_wuliao = PushButton("从 视频信息.txt 读取", icon=FIF.DOCUMENT)
        btn_wuliao.clicked.connect(self._bili_load_wuliao)
        lay.addWidget(_row(CaptionLabel("视频"), self.bili_video, btn_pick,
                           btn_wuliao))

        self.bili_title = LineEdit()
        self.bili_title.setPlaceholderText("稿件标题")
        lay.addWidget(_row(CaptionLabel("标题"), self.bili_title))

        self.bili_desc = TextEdit()
        self.bili_desc.setPlaceholderText("简介（可留空）")
        self.bili_desc.setFixedHeight(60)
        lay.addWidget(_row(CaptionLabel("简介"), self.bili_desc))

        self.bili_tags = LineEdit()
        self.bili_tags.setPlaceholderText("标签，用 / 、 ， 或空格分隔，"
                                          "如：鸣潮 / 游戏实况")
        lay.addWidget(_row(CaptionLabel("标签"), self.bili_tags))

        self.bili_zone = LineEdit()
        self.bili_zone.setPlaceholderText("分区名，如 游戏")
        self.bili_zone_combo = ComboBox()
        self.bili_zone_combo.setMinimumWidth(170)
        self.bili_zone_combo.addItem("（未检测）", userData="")
        self.bili_zone_combo.currentIndexChanged.connect(self._bili_zone_picked)
        btn_detect = PushButton("检测分区", icon=FIF.SEARCH)
        btn_detect.clicked.connect(self._bili_detect_zone)
        btn_detect_topic = PushButton("检测话题", icon=FIF.SEARCH)
        btn_detect_topic.clicked.connect(self._bili_detect_topic)
        lay.addWidget(_row(CaptionLabel("分区"), self.bili_zone,
                           self.bili_zone_combo, btn_detect, btn_detect_topic))

        self.bili_topic = LineEdit()
        self.bili_topic.setPlaceholderText("参与话题（可留空）")
        lay.addWidget(_row(CaptionLabel("话题"), self.bili_topic))

        # —— 执行 ——
        btn_open = PushButton("打开投稿页", icon=FIF.GLOBE)
        btn_open.clicked.connect(self._bili_open_page)
        btn_shot_dir = PushButton("失败截图目录", icon=FIF.FOLDER)
        btn_shot_dir.clicked.connect(self._bili_open_shot_dir)
        self.btn_bili_run = PrimaryPushButton("开始投稿", icon=FIF.ROBOT)
        self.btn_bili_run.clicked.connect(self._bili_start)
        self.bili_dry = SwitchButton()
        self.bili_dry.setOnText("演练")
        self.bili_dry.setOffText("真跑")
        self.bili_dry.setChecked(True)
        lay.addWidget(_row(btn_open, btn_shot_dir, self.btn_bili_run,
                           CaptionLabel("演练模式（只识别不真点）"), self.bili_dry))
        self.bili_progress = ProgressBar()
        self.bili_progress.setValue(0)
        lay.addWidget(self.bili_progress)
        self.bili_stage = CaptionLabel("尚未开始")
        self.bili_stage.setWordWrap(True)
        lay.addWidget(self.bili_stage)

        # —— 日志 ——
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(170)
        self.log_view.setStyleSheet(
            "QPlainTextEdit{background:#1e2228;color:#c9d1d9;"
            "border:1px solid #3a4250;border-radius:8px;font-family:Consolas,"
            "'Cascadia Mono',monospace;font-size:9.5pt;}")
        self.log_view.setPlaceholderText("投稿执行日志会打在这里")
        lay.addWidget(self.log_view)
        btn_clear = PushButton("清空日志", icon=FIF.DELETE)
        btn_clear.clicked.connect(self.log_view.clear)
        lay.addWidget(_row(btn_clear))
        return box

    # -- 日志 -- #
    def _log(self, text):
        self.log_view.appendPlainText(str(text))
        self.log_view.verticalScrollBar().setValue(
            self.log_view.verticalScrollBar().maximum())
        QApplication.processEvents()

    # -- 任务字段 -- #
    def _bili_pick_video(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择要投稿的视频", "",
            "视频 (*.mp4 *.flv *.mkv *.mov *.avi *.wmv *.webm *.ts *.m4v);;所有文件 (*)")
        if path:
            self.bili_video.setText(path)

    def _bili_load_wuliao(self):
        video = self.bili_video.text().strip()
        wpath = bu.find_wuliao(video) if video else None
        if not wpath:
            _tip("warning", "提示",
                 "没在视频目录找到 视频信息.txt；请先填视频路径，或手动填写", self)
            return
        data = bu.load_wuliao(wpath)
        if data["title"]:
            self.bili_title.setText(data["title"])
        if data["desc"]:
            self.bili_desc.setPlainText(data["desc"])
        if data["tags"]:
            self.bili_tags.setText(" / ".join(data["tags"]))
        if data["zone"]:
            self.bili_zone.setText(data["zone"])
        if data["topic"]:
            self.bili_topic.setText(data["topic"])
        self._log(f"已从 {wpath} 读取物料：标题/标签{len(data['tags'])}个/"
                  f"分区={data['zone'] or '(无)'}")
        _tip("success", "已读取物料", os.path.basename(wpath), self)

    def _bili_zone_picked(self, _idx):
        val = self.bili_zone_combo.currentData()
        if val:
            self.bili_zone.setText(str(val))

    def _bili_task(self):
        return {
            "video": self.bili_video.text().strip(),
            "title": self.bili_title.text().strip(),
            "desc": self.bili_desc.toPlainText().strip(),
            "tags": bu.split_tags(self.bili_tags.text()),
            "zone": self.bili_zone.text().strip(),
            "topic": self.bili_topic.text().strip(),
            "submit": True,
        }

    # -- AI 检测（分区 / 话题）-- #
    def _bili_detect_zone(self):
        win = self._selected_window()
        if win is None:
            _tip("warning", "提示", "先在「目标窗口」里选中投稿页所在窗口", self)
            return
        if not bu.ai_available():
            _tip("warning", "AI 未启用",
                 "分区检测依赖视觉模型，请到「设置 → 全局 AI」填写密钥", self)
            return
        _tip("info", "检测中", "请在浏览器里把「分区」面板点开，正在读屏…", self)
        QApplication.processEvents()
        try:
            res = bu.detect_zone_options(win)
        except Exception as exc:  # noqa: BLE001
            _tip("error", "检测失败", f"{type(exc).__name__}: {exc}", self)
            return
        opts = res.get("options") or []
        self.bili_zone_combo.blockSignals(True)
        self.bili_zone_combo.clear()
        if opts:
            self.bili_zone_combo.addItem("（选择一个）", userData="")
            for o in opts:
                self.bili_zone_combo.addItem(o, userData=o)
        else:
            self.bili_zone_combo.addItem("（未检测到）", userData="")
        self.bili_zone_combo.blockSignals(False)
        self._log(f"检测到分区 {len(opts)} 个：{opts}")
        _tip("success" if opts else "warning", "分区检测",
             f"{len(opts)} 个（见日志；也可直接手填分区名）", self)

    def _bili_detect_topic(self):
        win = self._selected_window()
        if win is None:
            _tip("warning", "提示", "先在「目标窗口」里选中投稿页所在窗口", self)
            return
        if not bu.ai_available():
            _tip("warning", "AI 未启用",
                 "话题检测依赖视觉模型，请到「设置 → 全局 AI」填写密钥", self)
            return
        QApplication.processEvents()
        try:
            res = bu.detect_topic_options(win)
        except Exception as exc:  # noqa: BLE001
            _tip("error", "检测失败", f"{type(exc).__name__}: {exc}", self)
            return
        opts = res.get("options") or []
        self._log(f"检测到话题 {len(opts)} 个：{opts}")
        if opts and not self.bili_topic.text().strip():
            self.bili_topic.setText(opts[0])
        _tip("success" if opts else "warning", "话题检测", f"{len(opts)} 个", self)

    def _bili_open_page(self):
        try:
            import webbrowser
            webbrowser.open(bu.UPLOAD_URL)
        except Exception as exc:  # noqa: BLE001
            _tip("error", "打开失败", str(exc), self)

    # -- 执行 -- #
    def _bili_start(self):
        if self._bili_worker is not None and self._bili_worker.isRunning():
            _tip("warning", "提示", "上一轮投稿还在跑，请稍候", self)
            return
        win = self._selected_window()
        if win is None:
            _tip("warning", "提示", "先在「目标窗口」里选中你已登录 B 站的浏览器窗口",
                 self)
            return
        task = self._bili_task()
        if not task["video"] or not os.path.isfile(task["video"]):
            _tip("warning", "提示", "请先填一个存在的视频文件路径", self)
            return
        if not task["title"]:
            _tip("warning", "提示", "标题不能为空", self)
            return
        dry = self.bili_dry.isChecked()
        missing = bu.missing_templates(DATA_DIR)
        if missing:
            self._log("⚠ 还差必需模板：" + "、".join(m["label"] for m in missing)
                      + "（对应步骤会走熔断分支）")
        self._log("=" * 46)
        self._log(f"开始投稿（{'演练：不会真点鼠标/键盘' if dry else '⚠ 真跑模式'}）")
        self.bili_progress.setValue(0)
        self.bili_stage.setText("启动中…")
        self.btn_bili_run.setEnabled(False)
        worker = BiliUploadWorker(task, win, dry, DATA_DIR, self)
        worker.logged.connect(self._log)
        worker.staged.connect(self._on_bili_stage)
        worker.done.connect(self._on_bili_done)
        self._bili_worker = worker
        worker.start()

    def _on_bili_stage(self, _node, label):
        self.bili_stage.setText(f"当前阶段：{label}")
        order = list(bu.STAGES.values())
        if label in order:
            i = order.index(label)
            self.bili_progress.setValue(int((i + 1) / len(order) * 100))

    def _on_bili_done(self, res):
        self.btn_bili_run.setEnabled(True)
        ok = bool(res.get("ok"))
        self.bili_progress.setValue(100 if ok else self.bili_progress.value())
        failed = res.get("failed_at")
        if ok:
            self.bili_stage.setText("✅ 流程完成（演练模式下未真正提交）")
            _tip("success", "投稿流程完成", "演练模式未真点；确认后可关掉演练再跑", self)
        else:
            self.bili_stage.setText(
                f"❌ 未完成（停在中途：{failed or '未到达终点'}）"
                + (f"；失败截图：{res.get('screenshot')}"
                   if res.get("screenshot") else ""))
            _tip("warning", "投稿未完成",
                 f"停在中途：{failed or '未到达终点'}（详见日志）", self)
        self._bili_refresh_tpl_combo()
