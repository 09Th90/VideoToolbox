# -*- coding: utf-8 -*-
# @version 3.0.0
"""视频库页（2026-11-15 功能解耦阶段③：从 video_toolbox_qt.py 拆出，逐字同源）。

* 缩略图缓存常量/助手（LIB_EXTS/THUMB_DIR/CARD_W…/thumb_cache_name/fmt_hms）
  为本功能专属，随页迁入；入口再导出旧名保存量调用方零改动。
* 消息自订阅（bus「lib_」前缀），不再依赖入口 _dispatch。
"""
import hashlib
import os
import re
import threading

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QFileDialog, QGridLayout, QVBoxLayout, QWidget)

from vt_fluent import (BodyLabel, CaptionLabel, FluentIcon as FIF, LineEdit,
                       PushButton, ScrollArea)

import video_toolbox as engine
import ui_theme

from vt_app.widgets import ScrollPage, card, row
from features._media import VIDEO_EXTS

LIB_EXTS = set(VIDEO_EXTS)
THUMB_DIR = engine.THUMB_CACHE_DIR
CARD_W, THUMB_W, THUMB_H = 232, 200, 118


def thumb_cache_name(path):
    """缩略图缓存文件名：净化文件名 + 完整路径哈希 + 修改时间戳（含目录，防串图）。

    v1.10.0 起输出 .jpg —— 旧 tkinter 版用 .ppm（Tk 能读、Qt 读不了），
    换界面后旧缓存不会再被命中，会自动按新名重新生成，无需手工清理。
    """
    stem = os.path.splitext(os.path.basename(path))[0]
    try:
        stamp = int(os.path.getmtime(path))
    except OSError:
        stamp = 0
    digest = hashlib.md5(os.path.abspath(path).encode("utf-8", "replace")).hexdigest()[:8]
    return re.sub(r"[^\w.-]", "_", stem)[:60] + "__" + digest + "__" + str(stamp) + ".jpg"


def fmt_hms(seconds):
    seconds = int(seconds or 0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


class LibraryPage(QWidget):
    """视频库：自动加载 + 缩略图卡片；单击播放，右键打开所在文件夹。"""

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setObjectName("LibraryPage")
        self.cards = {}
        self.videos = []
        self._pixmaps = {}
        self._busy = False
        self._cols = 4

        # 功能解耦阶段③：消息自订阅（原入口 _dispatch 的 lib_* 分支）。
        app.bus.subscribe("lib_", self._on_bus_message)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.shell = ScrollPage("视频库",
                                "打开软件自动加载；缩略图自动生成并缓存；"
                                "单击卡片播放，右键打开所在文件夹", self, scrollable=False)
        outer.addWidget(self.shell)
        self.vbox = self.shell.content_lay
        self.vbox.setSpacing(12)

        self.dir_edit = LineEdit(self)
        self.dir_edit.setText(engine.get_saved_download_dir())
        browse = PushButton(FIF.FOLDER, "浏览…", self)
        browse.clicked.connect(self.browse)
        sync = PushButton(FIF.SYNC, "同步下载目录", self)
        sync.clicked.connect(self.sync_download_dir)
        self.refresh_btn = PushButton(FIF.UPDATE, "刷新", self)
        self.refresh_btn.clicked.connect(self.refresh)
        open_btn = PushButton(FIF.FOLDER_ADD, "打开文件夹", self)
        open_btn.clicked.connect(self.open_dir)
        box, lay = card("视频库文件夹")
        lay.addWidget(row(self.dir_edit, browse, sync, self.refresh_btn, open_btn))
        self.count_label = CaptionLabel("尚未扫描", self)
        lay.addWidget(self.count_label)
        self.vbox.addWidget(box)

        area = ScrollArea(self)
        area.setWidgetResizable(True)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # ⚠ 与 ScrollPage 一致：viewport 与内容控件**两层**都要透明化。
        # QScrollArea 的 viewport 与 setWidget 后的内容控件 autoFillBackground
        # 默认为 True，会按调色板把卡片网格区填成浅灰白（深色主题下发白）。
        area.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        self.holder = QWidget()
        self.holder.setStyleSheet("QWidget{background:transparent;}")
        self.grid = QGridLayout(self.holder)
        self.grid.setContentsMargins(2, 2, 2, 2)
        self.grid.setSpacing(12)
        area.setWidget(self.holder)
        self.area = area
        self.empty_label = CaptionLabel("", self)
        self.vbox.addWidget(self.empty_label)
        self.vbox.addWidget(area, 1)
        self.area.installEventFilter(self)

    # ---------- 消息 ----------
    def _on_bus_message(self, msg):
        """bus「lib_」前缀消息（原入口 _dispatch 的 lib_* 分支，语义逐字一致）。"""
        kind, args = msg[0], msg[1:]
        if kind == "lib_scan_done":
            self.on_scan_done(args[0], args[1])
        elif kind == "lib_thumb":
            self.on_thumb(args[0], args[1])
        elif kind == "lib_thumb_fail":
            self.on_thumb_fail(args[0])
        elif kind == "lib_log":
            self.on_log(args[0])

    # ---------- 操作 ----------
    def set_dir(self, path):
        self.dir_edit.setText(path)

    def browse(self):
        d = QFileDialog.getExistingDirectory(self, "选择视频库文件夹",
                                             self.dir_edit.text() or engine.APP_DIR)
        if d:
            self.dir_edit.setText(d)
            self.refresh()

    def sync_download_dir(self):
        self.dir_edit.setText(self.app.download_page.dest_edit.text())
        self.refresh()

    def open_dir(self):
        d = engine.clean_path(self.dir_edit.text())
        if os.path.isdir(d):
            engine.open_folder(d)

    def auto_load(self):
        if os.path.isdir(engine.clean_path(self.dir_edit.text())):
            self.refresh()

    def refresh(self):
        if self._busy:
            return
        folder = engine.clean_path(self.dir_edit.text())
        if not os.path.isdir(folder):
            self.empty_label.setText("视频库文件夹不存在，请先选择一个有效文件夹")
            return
        self._busy = True
        self.refresh_btn.setEnabled(False)
        self.empty_label.setText("")
        self.count_label.setText("正在扫描视频 …")
        threading.Thread(target=self._scan_worker, args=(folder,), daemon=True).start()

    # ---------- 后台 ----------
    def _scan_worker(self, folder):
        try:
            _, ffprobe = engine.ensure_ffmpeg()
            paths = []
            for root, dirs, files in os.walk(folder):
                dirs[:] = [d for d in dirs
                           if not d.startswith(".") and d != "thumb_cache"]
                for n in files:
                    if os.path.splitext(n)[1].lower() in LIB_EXTS:
                        paths.append(os.path.join(root, n))
            paths.sort(key=lambda p: os.path.basename(p).lower())
            videos = []
            for p in paths:
                try:
                    size = os.path.getsize(p)
                except OSError:
                    size = 0
                rel = os.path.relpath(p, folder)
                name = rel if os.path.dirname(rel) else os.path.basename(p)
                videos.append({
                    "path": p, "name": name, "size": size,
                    "dur": engine.get_duration(p, ffprobe),
                    "thumb": os.path.join(THUMB_DIR, thumb_cache_name(p)),
                })
            self.app.q.put(("lib_scan_done", videos, None))
        except Exception as e:
            self.app.q.put(("lib_scan_done", None, str(e)))

    def _thumb_worker(self, videos):
        try:
            ffmpeg, _ = engine.ensure_ffmpeg()
        except Exception as e:
            self.app.q.put(("lib_log", f"[缩略图] ffmpeg 不可用：{e}"))
            return
        os.makedirs(THUMB_DIR, exist_ok=True)
        for v in videos:
            if os.path.isfile(v["thumb"]):
                continue
            seek = 5 if (v["dur"] or 0) >= 12 else 0
            ok = self._extract_frame(ffmpeg, v["path"], v["thumb"], seek)
            if not ok and seek:
                ok = self._extract_frame(ffmpeg, v["path"], v["thumb"], 0)
            if ok and os.path.isfile(v["thumb"]):
                self.app.q.put(("lib_thumb", v["path"], v["thumb"]))
            else:
                self.app.q.put(("lib_thumb_fail", v["path"]))

    @staticmethod
    def _extract_frame(ffmpeg, video, thumb, seek):
        cmd = [ffmpeg, "-y"]
        if seek:
            cmd += ["-ss", str(seek)]
        cmd += ["-i", video, "-frames:v", "1", "-vf", f"scale={THUMB_W}:-2", thumb]
        try:
            return engine.run_process(cmd, capture_output=True, timeout=120).returncode == 0
        except Exception:
            return False

    # ---------- 主线程 ----------
    def on_scan_done(self, videos, err):
        self._busy = False
        self.refresh_btn.setEnabled(True)
        self._clear_cards()
        if err:
            self.count_label.setText("")
            self.empty_label.setText(f"扫描失败：{err}")
            return
        self.videos = videos or []
        if not self.videos:
            self.count_label.setText("共 0 个视频")
            self.empty_label.setText("该文件夹下没有找到视频文件")
            return
        total = sum(v["size"] for v in self.videos)
        self.count_label.setText(f"共 {len(self.videos)} 个视频 · {engine.format_size(total)}")
        for v in self.videos:
            self._make_card(v)
        self._reflow()
        missing = [v for v in self.videos if not os.path.isfile(v["thumb"])]
        if missing:
            threading.Thread(target=self._thumb_worker, args=(missing,), daemon=True).start()

    def on_thumb(self, path, thumb_path):
        cardd = self.cards.get(path)
        if not cardd:
            return
        pm = QPixmap(thumb_path)
        if pm.isNull():
            cardd["img"].setText("缩略图损坏")
            return
        self._pixmaps[path] = pm
        cardd["img"].setPixmap(pm.scaled(THUMB_W, THUMB_H, Qt.KeepAspectRatio,
                                         Qt.SmoothTransformation))
        cardd["img"].setText("")

    def on_thumb_fail(self, path):
        cardd = self.cards.get(path)
        if cardd:
            cardd["img"].setText("缩略图生成失败")

    def on_log(self, text):
        self.count_label.setText(text)

    # ---------- 卡片 ----------
    def eventFilter(self, obj, event):
        if obj is self.area and event.type() == QEvent.Resize:
            self._schedule_reflow()
        return super().eventFilter(obj, event)

    def showEvent(self, event):
        # v1.13.0：换屏/改 DPI/窗口缩小后回到本页时，按当前视口宽度重排卡片；
        # 延迟两档：视口尺寸可能晚于 show 更新，holder 重排后也要一次布局收敛。
        super().showEvent(event)
        QTimer.singleShot(0, self._reflow)
        QTimer.singleShot(60, self._reflow)

    def _clear_cards(self):
        for c in self.cards.values():
            c["box"].setParent(None)
            c["box"].deleteLater()
        self.cards.clear()
        self._pixmaps.clear()

    def _make_card(self, v):
        if v["path"] in self.cards:
            return
        # v1.13.x 界面美化：缩略图卡与全局 card() 共用 UICard 皮肤
        box = ui_theme.UICard(self.holder)
        box.setFixedWidth(CARD_W)
        lay = QVBoxLayout(box)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(6)
        img = BodyLabel("生成缩略图中 …", box)
        img.setAlignment(Qt.AlignCenter)
        img.setFixedSize(THUMB_W, THUMB_H)
        img.setStyleSheet("border-radius:6px;")
        name = BodyLabel(self._elide(v["name"], 26), box)
        name.setToolTip(v["path"])
        meta = CaptionLabel(f"{engine.format_size(v['size'])} · {fmt_hms(v['dur'])}", box)
        lay.addWidget(img)
        lay.addWidget(name)
        lay.addWidget(meta)
        box.mousePressEvent = lambda e, p=v["path"]: self._on_card_click(e, p)
        box.setContextMenuPolicy(Qt.CustomContextMenu)
        box.customContextMenuRequested.connect(
            lambda _pos, p=v["path"]: engine.open_folder(os.path.dirname(p)))
        self.cards[v["path"]] = {"box": box, "img": img}
        if os.path.isfile(v["thumb"]):
            self.on_thumb(v["path"], v["thumb"])

    @staticmethod
    def _elide(text, limit):
        return text if len(text) <= limit else "…" + text[-(limit - 1):]

    def _on_card_click(self, event, path):
        if event.button() == Qt.LeftButton:
            engine.open_folder(os.path.dirname(path))
            self._open_file(path)

    @staticmethod
    def _open_file(path):
        try:
            os.startfile(path)     # noqa: S606
        except OSError:
            pass

    def _reflow(self, *_):
        """按当前视口宽度重排卡片列数（v1.13.0：改为可靠触发）。

        旧实现直接在 ScrollArea 的 Resize 事件里读 viewport().width()——
        事件派发时视口可能还是旧尺寸，窗口缩小/换 DPI 屏后网格仍按旧列数
        排布，卡片超出视口、右侧被裁（横向滚动又禁用 → 视觉扭曲）。
        现在：每次都用「视口宽度」重算；若发现与当前列数不一致再重排；
        并延迟到事件循环空闲后再做一次兜底，覆盖视口晚于区域 resize 的情况。
        """
        if not self.cards:
            return
        try:
            vw = self.area.viewport().width()
        except Exception:
            vw = self.area.width()
        if vw <= 0:
            vw = self.area.width()
        width = max(vw, CARD_W + 8)
        cols = max(1, width // (CARD_W + 12))
        if cols == self._cols and self.grid.count() == len(self.cards):
            return
        self._cols = cols
        while self.grid.count():
            self.grid.takeAt(0)
        for i, c in enumerate(self.cards.values()):
            self.grid.addWidget(c["box"], i // cols, i % cols)
        self.grid.setRowStretch(self.grid.rowCount(), 1)
        # v1.13.0：重排后立刻把 holder 收缩到视口宽度——widgetResizable 的
        # 自动收缩发生在下一事件循环，期间旧列数仍把 holder 撑宽（横向滚动
        # 已禁用 → 卡片被右侧裁掉，即用户看到的「页面扭曲」）。
        try:
            vp = self.area.viewport().width()
            if vp > 0 and self.holder.width() != vp:
                self.holder.resize(vp, self.holder.height())
        except Exception:
            pass

    def _schedule_reflow(self):
        """滚动区尺寸变化后：本帧 + 下一帧各重排一次，消除视口/holder 时序差。"""
        self._reflow()
        QTimer.singleShot(0, self._reflow)
        QTimer.singleShot(50, self._reflow)


def build_page(app, parent=None):
    """注册表 GuiSpec.builder 入口（library 功能页）。"""
    return LibraryPage(app, parent)