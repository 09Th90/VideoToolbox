#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""视频工具箱 GUI v1.10.2 —— Fluent 矢量界面
====================================================================
界面形态（v1.10.0 起，原 tkinter 界面退役）：
  · FluentWindow + 左侧 NavigationInterface 导航（顶部功能区 + 底部分隔项）
  · 每页「标题区固定 + 内容滚动区」：内容放进 QScrollArea（水平滚动禁用，
    滚动区内一律不用自动换行标签，避免 heightForWidth 与滚动区互相触发重排），
    窗口最小尺寸不再被内容撑爆，任何屏幕尺寸下都完整可用；
  · 卡片内：标题 StrongBodyLabel / 说明 CaptionLabel / 控件行；
  · 全矢量渲染：图标为 FluentIcon 矢量字体图标，高分屏按逻辑像素缩放
    （AA_EnableHighDpiScaling + AA_UseHighDpiPixmaps），任意缩放比例不发虚。
页面（v1.10.0 起共 5 个，B站投稿板块已移除）：
  视频下载 · 视频库 · 音视频合并 · 字幕处理（内嵌第三方字幕引擎）· 字幕校准
线程模型沿用旧界面：后台线程只往 app.q 投消息，主线程用 QTimer 泵出后更新控件。
调试钩子（供打包验证/截图）：VT_GUI_SELFTEST=1 自检自退；VT_SHOT_TAB/VT_SHOT_FILE 截图。
"""

import hashlib
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from datetime import datetime

from PyQt5.QtCore import Qt, QTimer, QEvent, QUrl
from PyQt5.QtGui import QColor, QDesktopServices, QFont, QPixmap, QTextCursor
from PyQt5.QtWidgets import (QAbstractItemView, QApplication, QDialog,
                             QFileDialog, QGridLayout, QHBoxLayout, QHeaderView,
                             QTableWidgetItem, QVBoxLayout, QWidget)

from qfluentwidgets import (BodyLabel, CardWidget, CaptionLabel,
                            ComboBox, FluentIcon as FIF,
                            FluentWindow, InfoBar, InfoBarPosition, LineEdit,
                            ListWidget, MessageBox, NavigationItemPosition,
                            PrimaryPushButton, ProgressBar, PushButton,
                            ScrollArea, SimpleCardWidget, SubtitleLabel,
                            StrongBodyLabel, SwitchButton, TableWidget,
                            TextEdit, Theme, TitleLabel, setTheme, setThemeColor)

import video_toolbox as engine

VERSION = "1.10.3"

LIB_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv", ".ts", ".m4v", ".webm"}
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


# ========== 通用控件 ==========
class LogView(CardWidget):
    """日志卡片：等宽字体、按级别着色、自动滚动到底。"""

    COLORS = {"dim": "#8A8A8A", "ok": "#2E9E5B", "err": "#D64545", "info": "#B0B0B0"}

    def __init__(self, title="运行日志", height=150, parent=None):
        super().__init__(parent)
        self.text = TextEdit(self)
        self.text.setReadOnly(True)
        self.text.setMinimumHeight(height)
        # 固定深色底：qfluentwidgets 的 TextEdit 在深色主题下不会自动变色，
        # 默认白底放在深色卡片里非常突兀，这里统一成「控制台」配色
        self.text.setStyleSheet(
            "TextEdit{background:#1B1B1B;color:#D6D6D6;border:none;"
            "font-family:Consolas,'Microsoft YaHei UI';font-size:12px;}")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 14, 20, 18)
        lay.setSpacing(10)
        lay.addWidget(CaptionLabel(title, self))
        lay.addWidget(self.text)

    def line(self, msg, level="dim"):
        color = self.COLORS.get(level, self.COLORS["dim"])
        stamp = datetime.now().strftime("%H:%M:%S")
        self.text.setTextColor(QColor("#8A8A8A"))
        self.text.insertPlainText(f"{stamp}  ")
        self.text.setTextColor(QColor(color))
        self.text.insertPlainText(str(msg) + "\n")
        self.text.setTextColor(QColor("#D0D0D0"))
        self.text.moveCursor(QTextCursor.End)
        self.text.ensureCursorVisible()

    def clear(self):
        self.text.clear()


def card(title=None, caption=None):
    """新建一张卡片，返回 (卡片, 其内部竖向布局)。

    卡片会被放进滚动区，说明文字不自动换行（避免 heightForWidth 与滚动区
    互相触发重排）；文案一律保持一行能放下的长度。
    """
    box = CardWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(14, 12, 14, 14)
    lay.setSpacing(8)
    if title:
        lay.addWidget(StrongBodyLabel(title, box))
    if caption:
        lay.addWidget(CaptionLabel(caption, box))
    return box, lay


def row(*widgets, spacing=8):
    """把若干控件排成一行（末尾自动补弹性空间）。"""
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


def label_row(text, widget, spacing=8):
    return row(BodyLabel(text), widget, None, spacing=spacing)


class PageBase(QWidget):
    """页面基类：统一标题区 + 内容区。"""

    def __init__(self, title, subtitle, parent=None):
        super().__init__(parent)
        self.vbox = QVBoxLayout(self)
        self.vbox.setContentsMargins(32, 22, 32, 24)
        self.vbox.setSpacing(14)
        self.vbox.addWidget(TitleLabel(title, self))
        if subtitle:
            cap = CaptionLabel(subtitle, self)
            cap.setWordWrap(True)
            self.vbox.addWidget(cap)

    def add(self, widget, stretch=0):
        self.vbox.addWidget(widget, stretch)


class ScrollPage(QWidget):
    """页面壳：标题区固定 + 内容区。

    scrollable=True 时内容放进滚动区（水平滚动禁用）：
      · 窗口最小尺寸不再被页面内容撑爆——此前四个重页面的布局最小高度
        叠加把 FluentWindow 撑到 1300px+，小屏幕上窗口超出屏幕、底部
        控件（任务表/日志）不可见，这是 v1.10.2 布局重做的直接原因；
      · 滚动区内一律不用自动换行标签（见 card() 注释），防止
        heightForWidth 与滚动区互相触发重排导致事件循环卡死。

    scrollable=False 时内容直接铺满（供内嵌引擎界面等自带滚动的页面）。
    """

    def __init__(self, title, subtitle, parent=None, scrollable=True):
        super().__init__(parent)
        self.view = self
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 16, 24, 18)
        outer.setSpacing(10)
        outer.addWidget(SubtitleLabel(title, self))
        if subtitle:
            cap = CaptionLabel(subtitle, self)
            cap.setWordWrap(True)
            outer.addWidget(cap)

        if scrollable:
            self.area = ScrollArea(self)
            self.area.setWidgetResizable(True)
            self.area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.area.setStyleSheet("QScrollArea{background:transparent;border:none;}")
            self.holder = QWidget(self.area)
            self.holder.setStyleSheet("QWidget{background:transparent;}")
            self.content_lay = QVBoxLayout(self.holder)
            self.content_lay.setContentsMargins(4, 2, 12, 16)
            self.content_lay.setSpacing(12)
            self.area.setWidget(self.holder)
            outer.addWidget(self.area, 1)
            self.vbox = self.content_lay
        else:
            self.area = None
            self.holder = QWidget(self)
            self.holder.setStyleSheet("QWidget{background:transparent;}")
            self.content_lay = QVBoxLayout(self.holder)
            self.content_lay.setContentsMargins(0, 0, 0, 0)
            outer.addWidget(self.holder, 1)
            self.vbox = self.content_lay

    def add_card(self, widget, stretch=0):
        self.vbox.addWidget(widget, stretch)


# ========== 视频下载 ==========
class DownloadPage(QWidget):
    """单个链接反复添加；每个下载任务独立线程，互不阻塞。"""

    _EXTRACT_LOCK = threading.Lock()
    SUB_LANGS = "en,zh,ja,zh-Hans,zh-Hant,ko,es,fr,de"

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setObjectName("DownloadPage")
        self.qualities = []
        self.detected_url = ""
        self.info_json_path = None
        self.detecting = False
        self.task_seq = 0
        self.tasks = {}
        self.active_task = None
        self._dest_syncing = False
        self._row_of = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.shell = ScrollPage("视频下载",
                                "检测一个链接后即可加入并行下载；每个视频自动打包成独立文件夹"
                                "（视频 + 封面.jpg + 视频信息.txt）", self, scrollable=True)
        outer.addWidget(self.shell)
        self.vbox = self.shell.content_lay

        # —— 链接 ——
        self.url_edit = LineEdit(self)
        self.url_edit.setPlaceholderText("粘贴视频链接（支持 B 站 / YouTube 等）")
        box, lay = card("视频链接")
        paste_btn = PushButton(FIF.PASTE, "粘贴", self)
        paste_btn.clicked.connect(self.paste_url)
        lay.addWidget(row(self.url_edit, paste_btn))
        self.vbox.addWidget(box)

        # —— 保存位置 ——
        self.dest_edit = LineEdit(self)
        self.dest_edit.setText(engine.get_saved_download_dir())
        self.dest_edit.textChanged.connect(self._on_dest_change)
        browse_btn = PushButton(FIF.FOLDER, "浏览…", self)
        browse_btn.clicked.connect(self.browse_dest)
        box, lay = card("保存位置", "改动会立即记住，下次启动自动沿用")
        lay.addWidget(row(self.dest_edit, browse_btn))
        self.vbox.addWidget(box)

        # —— 画质 ——
        self.qlist = ListWidget(self)
        self.qlist.setMinimumHeight(84)
        self.qlist.setMaximumHeight(110)
        self.detect_btn = PrimaryPushButton(FIF.SEARCH, "检测画质", self)
        self.detect_btn.clicked.connect(self.detect)
        box, lay = card("画质", "仅列出 ≥720p；同分辨率取最大文件，优先 60fps")
        lay.addWidget(row(CaptionLabel("可用画质", self), None, self.detect_btn))
        lay.addWidget(self.qlist)
        self.vbox.addWidget(box)

        # —— 下载 ——
        self.sub_switch = SwitchButton(self)
        self.sub_switch.setChecked(True)
        self.prog = ProgressBar(self)
        self.pct_label = CaptionLabel("等待检测", self)
        self.dl_btn = PrimaryPushButton(FIF.DOWNLOAD, "加入并行下载", self)
        self.dl_btn.clicked.connect(self.start_download)
        box, lay = card("下载")
        lay.addWidget(row(BodyLabel("同时下载字幕（博主上传 + 自动生成，自动转 SRT）", self),
                          self.sub_switch, None))
        lay.addWidget(row(self.prog, self.pct_label, self.dl_btn))
        self.vbox.addWidget(box)

        # —— 任务列表 ——
        self.task_table = TableWidget(self)
        self.task_table.setBorderVisible(True)
        self.task_table.setBorderRadius(8)
        self.task_table.setWordWrap(False)
        self.task_table.setColumnCount(6)
        self.task_table.setHorizontalHeaderLabels(
            ["任务", "链接", "画质", "进度", "状态", "保存位置"])
        self.task_table.verticalHeader().hide()
        self.task_table.setMinimumHeight(130)
        self.task_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.task_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        for i, w in enumerate((56, 250, 76, 76, 76, 260)):
            self.task_table.setColumnWidth(i, w)
        self.task_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.task_table.itemSelectionChanged.connect(self.on_task_select)
        box, lay = card("并行下载任务", "点击任务行可查看对应进度")
        lay.addWidget(self.task_table)
        self.vbox.addWidget(box)

        self.log = LogView("下载日志", 130, self)
        self.vbox.addWidget(self.log)
        self.vbox.addStretch(1)

    # ---------- 交互 ----------
    def paste_url(self):
        cb = QApplication.clipboard()
        self.url_edit.setText((cb.text() or "").strip())

    def browse_dest(self):
        d = QFileDialog.getExistingDirectory(self, "选择保存位置",
                                             self.dest_edit.text() or engine.APP_DIR)
        if d:
            self.dest_edit.setText(d)
            self.log.line(f"[设置] 保存位置已改为：{d}（已记住）", "ok")

    def _on_dest_change(self, text):
        if self._dest_syncing:
            return
        raw = self.dest_edit.text()
        d = engine.clean_path(raw)
        self._dest_syncing = True
        try:
            if d and d != raw:
                self.dest_edit.setText(d)
            if d:
                engine.set_saved_download_dir(d)
        finally:
            self._dest_syncing = False

    def set_detecting(self, busy):
        self.detecting = busy
        self.detect_btn.setEnabled(not busy)

    def detect(self):
        url = engine.clean_path(self.url_edit.text())
        if not url.lower().startswith("http"):
            self._warn("请先填入有效的 http 链接")
            return
        if self.detecting:
            return
        self.set_detecting(True)
        self.log.line("[信息] 正在检测可用画质 ...", "dim")
        threading.Thread(target=self._detect_worker, args=(url,), daemon=True).start()

    def _detect_worker(self, url):
        try:
            ytdlp = engine.ensure_ytdlp()
            with DownloadPage._EXTRACT_LOCK:
                raw = engine.fetch_info_json(
                    ytdlp, url, log=lambda m: self.app.q.put(("sys_log", m)))
            if not raw:
                self.app.q.put(("detect_done", url, None, None,
                                "站点风控或网络异常，请稍后重试（具体原因已写入日志）"))
                return
            best = engine.parse_qualities(raw)
            info_path = engine.save_info_json(raw) if best else None
            self.app.q.put(("detect_done", url, best, info_path, None))
        except Exception as e:
            self.app.q.put(("detect_done", url, None, None, str(e)))

    def on_detect_done(self, url, best, info_path, err):
        self.set_detecting(False)
        if err or not best:
            self.log.line(f"[错误] 画质检测失败{': ' + err if err else '，未找到 ≥720p 格式'}", "err")
            return
        self.detected_url = url
        self.qualities = best
        self._drop_info_json()
        self.info_json_path = info_path
        self.qlist.clear()
        for i, f in enumerate(best, 1):
            size = f.get("filesize") or f.get("filesize_approx") or 0
            fps = round(f.get("fps") or 0)
            tag = "   （最高，推荐）" if i == 1 else ""
            self.qlist.addItem(f"{f['height']}p {fps}fps   ~{engine.format_size(size)}{tag}")
        self.qlist.setCurrentRow(0)
        self.log.line(f"[OK] 检测到 {len(best)} 档画质；点击「加入并行下载」后可继续添加新链接", "ok")

    def _drop_info_json(self):
        if self.info_json_path:
            try:
                os.remove(self.info_json_path)
            except OSError:
                pass
            self.info_json_path = None

    def start_download(self):
        url = engine.clean_path(self.url_edit.text())
        if not url.lower().startswith("http"):
            self._warn("请先填入有效的 http 链接")
            return
        if url != self.detected_url or not self.qualities:
            self._warn("当前链接尚未检测画质，请先点击「检测画质」")
            return
        if not self.info_json_path or not os.path.isfile(self.info_json_path):
            self._warn("画质检测结果已失效，请重新点击「检测画质」")
            return
        sel = self.qlist.currentRow()
        if sel < 0:
            self._warn("请选择一档画质")
            return
        for item in self.tasks.values():
            if item["url"] == url and item["status"] == "下载中":
            # 同一链接不重复加入
                self._info("这个视频正在下载中，无需重复添加")
                return

        dest = engine.clean_path(self.dest_edit.text()) or engine.DEFAULT_DOWNLOAD_DIR
        os.makedirs(dest, exist_ok=True)
        engine.set_saved_download_dir(dest)
        fmt = self.qualities[sel]
        fid, height = fmt["format_id"], fmt["height"]

        try:
            with open(self.info_json_path, "r", encoding="utf-8") as f:
                raw_text = f.read()
            task_info = engine.save_info_json(raw_text)
        except OSError:
            self._warn("画质检测结果已失效，请重新点击「检测画质」")
            return

        try:
            meta = json.loads(raw_text)
        except ValueError:
            meta = {}
        task_folder = engine.unique_folder(
            dest, engine.sanitize_folder_name(meta.get("title"), "video"))
        try:
            os.makedirs(task_folder, exist_ok=True)
        except OSError as e:
            self._error("创建文件夹失败", f"{task_folder}\n{e}")
            return

        self.task_seq += 1
        task_id = f"T{self.task_seq}"
        with_subs = self.sub_switch.isChecked()
        self.tasks[task_id] = {
            "url": url, "quality": f"{height}p", "pct": 0.0, "status": "下载中",
            "dest": dest, "folder": task_folder, "with_subs": with_subs,
        }
        self._add_task_row(task_id, url, f"{height}p", "0.0%", "下载中", task_folder)
        self.active_task = task_id
        self.prog.setValue(0)
        self.pct_label.setText("0.0%")
        sub_note = "（含字幕）" if with_subs else ""
        self.log.line(f"[任务 {task_id}] {height}p 开始下载{sub_note} → {task_folder}", "dim")
        self.log.line("[提示] 该任务已在后台运行，可以继续检测并添加下一个视频", "dim")
        threading.Thread(
            target=self._download_worker,
            args=(task_id, url, fid, task_folder, with_subs, task_info, meta, f"{height}p"),
            daemon=True).start()

    # ---------- 任务表 ----------
    def _add_task_row(self, task_id, url, quality, pct, status, dest):
        r = self.task_table.rowCount()
        self.task_table.insertRow(r)
        for c, text in enumerate((task_id, self._display_url(url), quality, pct, status, dest)):
            item = QTableWidgetItem(str(text))
            item.setToolTip(str(text))
            self.task_table.setItem(r, c, item)
        self._row_of[task_id] = r
        self.task_table.selectRow(r)

    def _set_cell(self, task_id, col, text):
        r = self._row_of.get(task_id)
        if r is None or r >= self.task_table.rowCount():
            return
        item = self.task_table.item(r, col)
        if item is None:
            item = QTableWidgetItem()
            self.task_table.setItem(r, col, item)
        item.setText(str(text))

    def on_task_select(self):
        rows = self.task_table.selectionModel().selectedRows()
        if not rows:
            return
        r = rows[0].row()
        for tid, rr in self._row_of.items():
            if rr == r:
                self.active_task = tid
                item = self.tasks.get(tid)
                if item:
                    self.prog.setValue(int(item["pct"]))
                    self.pct_label.setText(
                        f"{item['pct']:.1f}%" if item["status"] == "下载中" else item["status"])
                break

    @staticmethod
    def _display_url(url, limit=44):
        return url if len(url) <= limit else url[: limit - 3] + "..."

    # ---------- 下载线程（与旧界面逻辑一致） ----------
    def _download_worker(self, task_id, url, fid, folder, with_subs=False,
                         info_json_path=None, meta=None, quality_label=""):
        try:
            ytdlp = engine.ensure_ytdlp()
            ffmpeg_path, _ = engine.ensure_ffmpeg()
            opts = ["-f", f"{fid}+ba/b", "--merge-output-format", "mp4",
                    "--ffmpeg-location", os.path.dirname(ffmpeg_path),
                    "--newline", "--no-playlist",
                    "--write-thumbnail", "--convert-thumbnails", "jpg",
                    "-o", engine.output_template(folder)]
            rc = 1
            if info_json_path and os.path.isfile(info_json_path):
                rc, _ = self._run_ytdlp(
                    [ytdlp, "--load-info-json", info_json_path, *opts], task_id)
            if rc != 0:
                self.app.q.put(("sys_log", f"[任务 {task_id}] 复用检测结果下载失败"
                                          "（多为 CDN 链接过期），改用链接重新提取"))
                self.app.q.put(("dl_progress", task_id, 0.0))
                rc = self._fallback_download(task_id, ytdlp, url, opts)
            if rc == 0:
                self._pack_task(task_id, ffmpeg_path, folder, meta, quality_label)
                if with_subs:
                    self._fetch_subtitles(task_id, ytdlp, url, folder,
                                          info_json_path, meta=meta)
            self.app.q.put(("dl_done", task_id, rc, folder))
        except Exception as e:
            self.app.q.put(("dl_done", task_id, 1, f"出错: {e}"))
        finally:
            if info_json_path:
                try:
                    os.remove(info_json_path)
                except OSError:
                    pass

    def _fallback_download(self, task_id, ytdlp, url, opts):
        """复用检测结果失败时的兜底：重新提取后继续；提取阶段全局串行防风控。"""
        def slog(m):
            self.app.q.put(("sys_log", f"[任务 {task_id}] {m}"))

        with DownloadPage._EXTRACT_LOCK:
            fresh = engine.fetch_info_json(ytdlp, url, log=slog)
        if fresh:
            tmp = engine.save_info_json(fresh)
            try:
                rc, _ = self._run_ytdlp([ytdlp, "--load-info-json", tmp, *opts], task_id)
            finally:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            if rc == 0:
                return 0
        with DownloadPage._EXTRACT_LOCK:
            return self._run_ytdlp_with_retry([ytdlp, *opts, url], task_id)

    def _fetch_subtitles(self, task_id, ytdlp, url, folder, info_json_path, meta=None):
        """视频下载完成后单独拉字幕；失败只写日志，不影响任务成功状态。"""
        sub_langs = self.SUB_LANGS
        title = ""
        if isinstance(meta, dict):
            title = str(meta.get("title") or "").strip()
        if title:
            code = engine.ai_detect_language(title)
            if code:
                langs = engine.ytdlp_sub_langs(code)
                if langs:
                    sub_langs = langs
                    self.app.q.put(("dl_log", task_id,
                                    f"[字幕] AI 识别标题语言为 {code}，按标题语言拉取字幕（{langs}）"))
            else:
                self.app.q.put(("dl_log", task_id,
                                "[字幕] AI 语言识别不可用，按多语言列表拉取字幕"))
        opts = ["--skip-download", "--newline", "--no-playlist",
                "--socket-timeout", "15", "--retries", "2",
                "--write-subs", "--write-auto-subs", "--sub-langs", sub_langs,
                "--sub-format", "srt/best", "--convert-subs", "srt",
                "-o", engine.output_template(folder)]
        rc = 1
        if info_json_path and os.path.isfile(info_json_path):
            rc, _ = self._run_ytdlp([ytdlp, "--load-info-json", info_json_path, *opts], task_id)
        if rc != 0:
            with DownloadPage._EXTRACT_LOCK:
                rc, _ = self._run_ytdlp([ytdlp, *opts, url], task_id)
        try:
            has_srt = any(n.lower().endswith(".srt") for n in os.listdir(folder))
        except OSError:
            has_srt = False
        if has_srt:
            self.app.q.put(("dl_log", task_id, "[字幕] 已下载到本视频文件夹（.srt）"))
        else:
            self.app.q.put(("dl_log", task_id,
                            "[字幕] 该视频没有可用字幕，或字幕拉取失败"
                            "——不影响视频/封面/信息文件，任务仍算完成"))

    def _pack_task(self, task_id, ffmpeg_path, folder, meta, quality_label):
        data = meta if isinstance(meta, dict) else {}
        try:
            engine.write_info_txt(folder, data, quality_label)
            self.app.q.put(("dl_log", task_id, "[打包] 视频信息.txt 已生成"))
        except Exception as e:
            self.app.q.put(("dl_log", task_id, f"[打包] 视频信息.txt 写入失败: {e}"))
        if engine.make_cover_1280x720(ffmpeg_path, folder):
            self.app.q.put(("dl_log", task_id, "[打包] 封面.jpg（1280x720）已生成"))
        else:
            self.app.q.put(("dl_log", task_id, "[打包] 该视频无可用封面，已跳过封面步骤"))

    def _run_ytdlp(self, cmd, task_id):
        try:
            proc = engine.popen_process(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, encoding="utf-8", errors="replace", bufsize=1)
        except Exception as e:
            self.app.q.put(("dl_log", task_id, f"[错误] 无法启动下载器: {e}"))
            return 1, []
        lines = []
        pct_re = re.compile(r"\[download\]\s+([\d.]+)%")
        for line in proc.stdout:
            line = line.rstrip()
            lines.append(line)
            m = pct_re.search(line)
            if m:
                self.app.q.put(("dl_progress", task_id, float(m.group(1))))
            elif line and "Deprecated" not in line and "WARNING" not in line:
                self.app.q.put(("dl_log", task_id, line))
        return proc.wait(), lines

    def _run_ytdlp_with_retry(self, cmd, task_id, attempts=3):
        wait = 6
        rc, lines = 1, []
        for i in range(attempts):
            rc, lines = self._run_ytdlp(cmd, task_id)
            if rc == 0:
                return 0
            joined = "\n".join(lines)
            if "412" not in joined and "Unable to download webpage" not in joined:
                return rc
            if i < attempts - 1:
                self.app.q.put(("sys_log",
                                f"[任务 {task_id}] 站点风控拦截（HTTP 412），{wait}s 后重试 "
                                f"({i + 2}/{attempts}) ..."))
                time.sleep(wait)
                wait *= 2
        return rc

    # ---------- 主线程更新 ----------
    def on_dl_progress(self, task_id, pct):
        item = self.tasks.get(task_id)
        if not item:
            return
        item["pct"] = pct
        self._set_cell(task_id, 3, f"{pct:.1f}%")
        self._set_cell(task_id, 4, "下载中")
        if task_id == self.active_task:
            self.prog.setValue(int(pct))
            self.pct_label.setText(f"{pct:.1f}%")
        n = self.active_count()
        if n:
            self.pct_label.setToolTip(f"并行下载中：{n} 个任务")

    def on_dl_log(self, task_id, text):
        self.log.line(f"[任务 {task_id}] {text}", "dim")

    def on_dl_done(self, task_id, rc, folder):
        item = self.tasks.get(task_id)
        if item:
            item["pct"] = 100.0 if rc == 0 else item["pct"]
            item["status"] = "完成" if rc == 0 else "失败"
        self._set_cell(task_id, 3, "100%" if rc == 0 else "—")
        self._set_cell(task_id, 4, "完成" if rc == 0 else "失败")
        if rc == 0:
            self._set_cell(task_id, 5, folder)
        if task_id == self.active_task:
            if rc == 0:
                self.prog.setValue(100)
            self.pct_label.setText("完成" if rc == 0 else "失败")
        if rc == 0:
            self.log.line(f"[任务 {task_id}] [完成] 已打包到独立文件夹: {folder}", "ok")
            if item and item.get("with_subs"):
                self.log.line(f"[任务 {task_id}] 字幕（.srt，若有）已存入该视频文件夹", "dim")
            root_dir = (item or {}).get("dest") or os.path.dirname(folder)
            self.app.library_page.set_dir(root_dir)
            self.app.library_page.refresh()
            if self.active_count() == 0:
                engine.open_folder(folder)
        else:
            self.log.line(f"[任务 {task_id}] [错误] 下载失败，请查看上方日志"
                          "（多为站点风控或网络问题）", "err")

    def active_count(self):
        return sum(1 for item in self.tasks.values() if item["status"] == "下载中")

    # ---------- 提示 ----------
    def _warn(self, text):
        InfoBar.warning("提示", text, duration=3000, position=InfoBarPosition.BOTTOM_RIGHT,
                        parent=self)
        self.log.line(f"[提示] {text}", "err")

    def _info(self, text):
        InfoBar.info("提示", text, duration=3000, position=InfoBarPosition.BOTTOM_RIGHT,
                     parent=self)

    def _error(self, title, text):
        MessageBox(title, text, self).exec()


# ========== 视频库 ==========
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
        self.holder = QWidget()
        self.grid = QGridLayout(self.holder)
        self.grid.setContentsMargins(2, 2, 2, 2)
        self.grid.setSpacing(12)
        area.setWidget(self.holder)
        self.area = area
        self.empty_label = CaptionLabel("", self)
        self.vbox.addWidget(self.empty_label)
        self.vbox.addWidget(area, 1)
        self.area.installEventFilter(self)

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
            self._reflow()
        return super().eventFilter(obj, event)

    def _clear_cards(self):
        for c in self.cards.values():
            c["box"].setParent(None)
            c["box"].deleteLater()
        self.cards.clear()
        self._pixmaps.clear()

    def _make_card(self, v):
        if v["path"] in self.cards:
            return
        box = SimpleCardWidget(self.holder)
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

    def _reflow(self):
        if not self.cards:
            return
        width = max(self.area.viewport().width(), CARD_W + 8)
        cols = max(1, width // (CARD_W + 12))
        if cols == self._cols and self.grid.count() == len(self.cards):
            return
        self._cols = cols
        while self.grid.count():
            self.grid.takeAt(0)
        for i, c in enumerate(self.cards.values()):
            self.grid.addWidget(c["box"], i // cols, i % cols)
        self.grid.setRowStretch(self.grid.rowCount(), 1)


# ========== 音视频合并 ==========
class MergePage(QWidget):
    ASS_MODES = {"烧录为硬字幕": "burn", "封装为 MKV": "mkv", "忽略": "ignore"}

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setObjectName("MergePage")
        self.pairs = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.shell = ScrollPage("音视频智能合并",
                                "自动配对 mp4 + m4a/weba + srt/ass；m4a 直封，weba 转 AAC",
                                self, scrollable=True)
        outer.addWidget(self.shell)
        self.vbox = self.shell.content_lay

        self.in_edit = LineEdit(self)
        self.in_edit.setText(engine.DEFAULT_INPUT_DIR)
        in_browse = PushButton(FIF.FOLDER, "浏览…", self)
        in_browse.clicked.connect(lambda: self._browse(self.in_edit))
        self.out_edit = LineEdit(self)
        out_browse = PushButton(FIF.FOLDER, "浏览…", self)
        out_browse.clicked.connect(lambda: self._browse(self.out_edit))
        box, lay = card("输入 / 输出文件夹", "输出留空则默认写入「输入文件夹\合成结果」")
        lay.addWidget(label_row("输入文件夹", self.in_edit))
        lay.addWidget(in_browse, 0, Qt.AlignLeft)
        lay.addWidget(label_row("输出文件夹", self.out_edit))
        lay.addWidget(out_browse, 0, Qt.AlignLeft)
        self.vbox.addWidget(box)

        self.ass_combo = ComboBox(self)
        self.ass_combo.addItems(list(self.ASS_MODES))
        self.ass_combo.setCurrentIndex(0)
        self.force_switch = SwitchButton(self)
        self.scan_btn = PrimaryPushButton(FIF.SEARCH, "扫描配对", self)
        self.scan_btn.clicked.connect(self.scan)
        box, lay = card("配对选项")
        lay.addWidget(label_row("ASS 字幕处理", self.ass_combo))
        lay.addWidget(row(BodyLabel("同名但时长不一致也强制合成", self),
                          self.force_switch, None))
        lay.addWidget(row(None, self.scan_btn))
        self.vbox.addWidget(box)

        self.table = TableWidget(self)
        self.table.setBorderVisible(True)
        self.table.setBorderRadius(8)
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["视频", "音频", "字幕", "匹配", "时长差"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        for i, w in enumerate((240, 240, 150, 80, 80)):
            self.table.setColumnWidth(i, w)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        box, lay = card("配对结果")
        lay.addWidget(self.table)
        self.table.setMinimumHeight(200)
        self.vbox.addWidget(box)

        row3 = row(self.prog_bar(), None, self.merge_btn())
        self.vbox.addWidget(row3)
        self.log = LogView("合并日志", 120, self)
        self.vbox.addWidget(self.log)
        self.vbox.addStretch(1)

    def prog_bar(self):
        self.progress = ProgressBar(self)
        return self.progress

    def merge_btn(self):
        self.merge_button = PrimaryPushButton(FIF.MEDIA, "开始合成", self)
        self.merge_button.clicked.connect(self.start_merge)
        return self.merge_button

    def _browse(self, edit):
        d = QFileDialog.getExistingDirectory(self, "选择文件夹", edit.text() or engine.APP_DIR)
        if d:
            edit.setText(d)

    def set_busy(self, busy):
        self.scan_btn.setEnabled(not busy)
        self.merge_button.setEnabled(not busy)

    def scan(self):
        in_dir = engine.clean_path(self.in_edit.text())
        if not os.path.isdir(in_dir):
            InfoBar.warning("提示", "输入文件夹不存在", duration=3000,
                            position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        self.set_busy(True)
        self.log.line(f"[信息] 正在扫描: {in_dir}", "dim")
        threading.Thread(target=self._scan_worker, args=(in_dir,), daemon=True).start()

    def _scan_worker(self, in_dir):
        try:
            _, ffprobe = engine.ensure_ffmpeg()
            mp4s, m4as, webas, srts, asss = engine.scan_media(in_dir)
            pairs, rem_mp4, rem_m4a, rem_weba = engine.smart_pair(
                mp4s, m4as, webas, srts, asss, ffprobe)
            self.app.q.put(("scan_done", pairs, (rem_mp4, rem_m4a, rem_weba),
                            (len(mp4s), len(m4as), len(webas), len(srts), len(asss)), None))
        except Exception as e:
            self.app.q.put(("scan_done", None, None, None, str(e)))

    def on_scan_done(self, pairs, remaining, counts, err):
        self.set_busy(False)
        if err:
            self.log.line(f"[错误] 扫描失败: {err}", "err")
            return
        self.pairs = pairs or []
        self.table.setRowCount(0)
        name = {"perfect": "完美", "duration": "时长", "name_only": "仅同名"}
        for p in self.pairs:
            mp4, audio, at, mt, diff, sub, st = p
            r = self.table.rowCount()
            self.table.insertRow(r)
            for c, text in enumerate((
                    os.path.basename(mp4), os.path.basename(audio),
                    os.path.basename(sub) if sub else "—",
                    name.get(mt, mt), f"{diff:.2f}s")):
                item = QTableWidgetItem(str(text))
                item.setToolTip(str(text))
                self.table.setItem(r, c, item)
        n_mp4, n_m4a, n_weba, n_srt, n_ass = counts
        self.log.line(f"[OK] 找到 {n_mp4} 个 mp4 / {n_m4a} 个 m4a / {n_weba} 个 weba / "
                      f"{n_srt} 个 srt / {n_ass} 个 ass，配对 {len(self.pairs)} 对", "ok")
        rem_mp4, rem_m4a, rem_weba = remaining
        if rem_mp4:
            self.log.line(f"[未匹配视频] {len(rem_mp4)} 个：" +
                          "、".join(os.path.basename(f) for f in rem_mp4), "dim")
        if rem_m4a or rem_weba:
            self.log.line(f"[未匹配音频] {len(rem_m4a) + len(rem_weba)} 个", "dim")

    def start_merge(self):
        if not self.pairs:
            InfoBar.warning("提示", "请先「扫描配对」", duration=3000,
                            position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        in_dir = engine.clean_path(self.in_edit.text())
        out_dir = engine.clean_path(self.out_edit.text()) or os.path.join(in_dir, "合成结果")
        os.makedirs(out_dir, exist_ok=True)
        ass_mode = self.ASS_MODES.get(self.ass_combo.currentText(), "burn")
        to_merge = [p for p in self.pairs
                    if p[3] in ("perfect", "duration") or self.force_switch.isChecked()]
        if not to_merge:
            InfoBar.warning("提示", "没有可合成的配对（可勾选强制合成）", duration=3000,
                            position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        self.set_busy(True)
        self.progress.setValue(0)
        threading.Thread(target=self._merge_worker,
                         args=(to_merge, out_dir, ass_mode), daemon=True).start()

    def _merge_worker(self, to_merge, out_dir, ass_mode):
        ok_n = fail_n = 0
        try:
            ffmpeg_path, _ = engine.ensure_ffmpeg()
            total = len(to_merge)
            for idx, p in enumerate(to_merge, 1):
                mp4, audio, at, mt, diff, sub, st = p
                if st == "ass" and ass_mode == "ignore":
                    sub, st = None, None
                base = engine.get_base_name(mp4)
                out_path = os.path.join(out_dir, f"{base}_merged.mp4")
                counter, orig = 1, out_path
                while os.path.exists(out_path):
                    stem, ext = os.path.splitext(orig)
                    out_path = f"{stem}_{counter}{ext}"
                    counter += 1
                self.app.q.put(("mg_log", f"[{idx}/{total}] {base}"))
                ok, final_out = engine.merge_pair(mp4, audio, at, sub, st,
                                                  out_path, ffmpeg_path, ass_mode)
                if ok and os.path.exists(final_out):
                    ok_n += 1
                    self.app.q.put(("mg_log", f"     [OK] "
                                              f"{engine.format_size(os.path.getsize(final_out))}"))
                else:
                    fail_n += 1
                    self.app.q.put(("mg_log", "     [X] 失败"))
                self.app.q.put(("mg_progress", idx / total * 100))
            self.app.q.put(("mg_done", ok_n, fail_n, out_dir))
        except Exception as e:
            self.app.q.put(("mg_done", ok_n, fail_n, f"出错: {e}"))

    def on_mg_done(self, ok_n, fail_n, out_dir):
        self.set_busy(False)
        self.progress.setValue(100)
        self.log.line(f"[完成] 成功 {ok_n} / 失败 {fail_n} → {out_dir}",
                      "ok" if fail_n == 0 else "err")
        if fail_n == 0:
            engine.open_folder(out_dir)


# ========== 字幕处理（内嵌第三方字幕引擎） ==========
class SubtitlePage(QWidget):
    """字幕处理：内嵌字幕引擎工作台（任务创建 / 语音转录 / 优化翻译 / 合成）。

    v1.10.2 起不再唤起独立窗口，引擎界面直接嵌入本页：
      · 引擎以第三方开源组件形式随包内置，界面在宿主窗口内呈现；
      · 品牌水印与捐助入口在嵌入层隐藏（许可与来源见 docs/ 下声明文件）；
      · 引擎背景改为透明，跟随宿主深色主题（其自带样式是白底，会与
        宿主界面割裂）；首次切到本页时才创建，避免拖慢启动。
    """

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setObjectName("SubtitlePage")
        self._engine = None
        self._built = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.shell = ScrollPage("字幕处理",
                                "语音转录 · 字幕优化 · 翻译 · 配音 · 合成，一站式内嵌完成",
                                self, scrollable=False)
        outer.addWidget(self.shell)
        # 本页以引擎界面为主体：收紧页边距，把空间让给引擎工作台
        self.shell.layout().setContentsMargins(20, 12, 20, 12)
        self.shell.layout().setSpacing(8)
        self.vbox = self.shell.content_lay
        self.vbox.setContentsMargins(0, 0, 0, 0)
        self.vbox.setSpacing(8)

        # 中部：引擎界面宿主；底部一行：引擎状态 + 许可入口
        # （第三方组件的许可与来源见 docs\ 声明文件）
        self.host = QWidget(self)
        self.host_lay = QVBoxLayout(self.host)
        self.host_lay.setContentsMargins(0, 0, 0, 0)
        self.vbox.addWidget(self.host, 1)

        foot = QWidget(self)
        flay = QHBoxLayout(foot)
        flay.setContentsMargins(0, 0, 0, 0)
        flay.setSpacing(12)
        self.state_label = CaptionLabel("正在加载字幕引擎界面 …", foot)
        self.set_btn = PushButton(FIF.SETTING, "引擎设置…", foot)
        self.set_btn.setEnabled(False)
        self.set_btn.clicked.connect(self.open_settings)
        self.lic_btn = PushButton(FIF.CERTIFICATE, "许可与来源…", foot)
        self.lic_btn.clicked.connect(self.show_license)
        flay.addWidget(self.state_label, 1)
        flay.addWidget(self.set_btn)
        flay.addWidget(self.lic_btn)
        self.vbox.addWidget(foot)

    def _build_engine(self):
        """创建并内嵌引擎工作台；隐藏品牌水印与捐助入口。"""
        engine.engine_ui_brand_patch()   # 用户可见文案中性化（见 docs\ 声明）
        try:
            from videocaptioner.ui.view.home_interface import HomeInterface
        except Exception as e:  # noqa: BLE001
            self.state_label.setText(f"字幕引擎加载失败：{e}")
            return None
        home = HomeInterface()
        # 引擎自带白色页面背景，内嵌到深色宿主里改为透明、随主题配色
        home.setStyleSheet("HomeInterface{background:transparent;}")
        tc = getattr(home, "task_creation_interface", None)
        if tc is not None:
            for attr in ("info_label", "donate_button"):
                w = getattr(tc, attr, None)
                if w is not None:
                    w.hide()
        return home

    def showEvent(self, event):
        """首次显示时才加载引擎界面（内嵌 QWidget，随主题自动配色）。"""
        super().showEvent(event)
        if self._built:
            return
        self._built = True
        self._engine = self._build_engine()
        if self._engine is None:
            return
        self.host_lay.addWidget(self._engine)
        self.state_label.setText("字幕引擎已就绪（内嵌运行，无需联网下载模型）")
        self.set_btn.setEnabled(True)

    def open_settings(self):
        """打开引擎设置（API Key / 转录与翻译服务 / 字幕样式等）。

        引擎的设置页原本挂在它的独立主窗口导航上；内嵌模式下没有那个窗口，
        这里把设置界面装进一个对话框呈现。
        """
        try:
            dlg = EngineSettingsDialog(self.window())
            dlg.exec()
        except Exception as e:  # noqa: BLE001
            MessageBox("设置打开失败", str(e)[:300], self).exec()

    def show_license(self):
        if os.path.isfile(engine.VC_LICENSE_FILE):
            try:
                os.startfile(engine.VC_LICENSE_FILE)     # noqa: S606
                return
            except OSError:
                pass
        MessageBox("第三方组件许可与来源",
                   "本工具内置第三方开源字幕引擎，其许可全文与来源声明见安装目录 "
                   "docs/ 下的 VideoCaptioner_GPL-3.0.txt 与 VideoCaptioner_组件来源.txt。",
                   self).exec()


class EngineSettingsDialog(QDialog):
    """字幕引擎设置对话框：承载引擎的设置界面（内嵌模式下的唯一入口）。

    · 隐藏「关于」组与上游推广卡片（许可与来源见 docs\\ 声明文件）；
    · 设置页内跳转「字幕样式」时宿主没有导航栏，改为弹出子对话框。
    """

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Window)
        from videocaptioner.ui.view.setting_interface import SettingInterface
        self.setWindowTitle("字幕引擎设置")
        self.resize(880, 660)
        # 引擎设置界面自身是透明底，宿主 QDialog 需按主题铺底色；
        # 滚动区视口默认会画一层浅色底，一并压成透明
        from qfluentwidgets import isDarkTheme
        bg = "#1F1F1F" if isDarkTheme() else "#F3F3F3"
        self.setStyleSheet(
            f"QDialog{{background:{bg};}}\n"
            "QScrollArea, QScrollArea>QWidget>QWidget{background:transparent;}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.setting = SettingInterface(self)
        self._hide_upstream_promo()
        lay.addWidget(self.setting)
        self._style = None
        self._style_dlg = None

    def _hide_upstream_promo(self):
        """去掉上游品牌入口：关于组（检查更新/帮助/反馈）与官方 API 推广卡片。"""
        about = getattr(self.setting, "aboutGroup", None)
        if about is not None:
            about.hide()
        card = getattr(self.setting, "openaiOfficialApiCard", None)
        if card is not None:
            orig = card.setVisible
            card.setVisible = lambda _v=True: orig(False)
            orig(False)

    @property
    def subtitleStyleInterface(self):
        if self._style is None:
            from videocaptioner.ui.view.subtitle_style_interface import (
                SubtitleStyleInterface)
            self._style = SubtitleStyleInterface(self)
            self._style.hide()
        return self._style

    def switchTo(self, interface):
        """设置页里的「字幕样式」跳转：宿主无导航栏，弹独立对话框。"""
        if self._style_dlg is None:
            dlg = self._style_dlg = QDialog(self, Qt.Window)
            lay = QVBoxLayout(dlg)
            lay.setContentsMargins(0, 0, 0, 0)
            interface.setParent(dlg)
            lay.addWidget(interface)
            dlg.setWindowTitle(interface.windowTitle() or "字幕样式")
            dlg.resize(960, 680)
        self._style_dlg.exec()


# ========== 字幕校准 ==========
class CalibPage(ScrollPage):
    MODES = [
        ("中英双语（默认，BILINGUAL_TERMS）", ""),
        ("韩语原声（--ko）", "--ko"),
        ("日语原声（--ja）", "--ja"),
        ("明日方舟（--ak）", "--ak"),
        ("终末地（--endo）", "--endo"),
        ("中文行专属（--zho）", "--zho"),
        ("战双帕弥什（--pgr）", "--pgr"),
        ("综合手游OST（--wwoc）", "--wwoc"),
    ]

    def __init__(self, app, parent=None):
        super().__init__("字幕校准",
                         "调用统一校准脚本 subtitle_calib_merged.py 做名词级术语校准；"
                         "序号 / 时间轴 / 空行 / 换行 / BOM 一字不动", parent)
        self.app = app
        self.setObjectName("CalibPage")
        self.running = False
        self._script = os.path.join(engine.APP_DIR, "subtitle_calib_merged.py")

        if not os.path.isfile(self._script):
            warn = CaptionLabel(f"校准脚本缺失：{self._script}", self.view)
            warn.setWordWrap(True)
            warn.setTextColor(Qt.darkRed)
            self.add_card(warn)

        self.in_edit = LineEdit(self)
        self.in_edit.setPlaceholderText("选择 .srt 字幕文件")
        in_btn = PushButton(FIF.DOCUMENT, "浏览…", self)
        in_btn.clicked.connect(self.browse_in)
        self.out_edit = LineEdit(self)
        self.out_edit.setPlaceholderText("留空自动：同目录 原名.calib.srt（重名自动加序号）")
        out_btn = PushButton(FIF.SAVE, "浏览…", self)
        out_btn.clicked.connect(self.browse_out)

        box, lay = card("字幕文件（.srt）")
        lay.addWidget(row(self.in_edit, in_btn))
        lay.addWidget(row(self.out_edit, out_btn))
        self.add_card(box)

        self.mode_combo = ComboBox(self)
        self.mode_combo.addItems([m[0] for m in self.MODES])
        self.mode_combo.setCurrentIndex(0)
        self.layout_switch = SwitchButton(self)
        self.fix_switch = SwitchButton(self)
        self.report_switch = SwitchButton(self)
        self.report_switch.setChecked(True)
        self.stats_switch = SwitchButton(self)
        self.run_btn = PrimaryPushButton(FIF.PLAY, "开始校准", self.view)
        self.run_btn.clicked.connect(self.start)
        self.stage_label = CaptionLabel("", self.view)

        box, lay = card("片源模式与选项")
        lay.addWidget(label_row("片源模式", self.mode_combo))
        lay.addWidget(row(BodyLabel("长句拆两行（--layout，≥14 字在标点处拆，不切官方专名）", self.view),
                          self.layout_switch, None))
        lay.addWidget(row(BodyLabel("修正英文/参考行（--fix-en，仅双语模式生效）", self.view),
                          self.fix_switch, None))
        lay.addWidget(row(BodyLabel("生成改动对照报告（同名 .md）", self.view),
                          self.report_switch, None))
        lay.addWidget(row(BodyLabel("仅统计术语命中，不写输出文件", self.view),
                          self.stats_switch, None))
        lay.addWidget(row(self.stage_label, None, self.run_btn))
        self.add_card(box)

        self.log = LogView("校准日志", 170, self.view)
        self.add_card(self.log)
        self.vbox.addStretch(1)

    def browse_in(self):
        p, _ = QFileDialog.getOpenFileName(self, "选择字幕文件",
                                           self.in_edit.text() or engine.APP_DIR,
                                           "字幕文件 (*.srt);;所有文件 (*.*)")
        if p:
            self.in_edit.setText(p)

    def browse_out(self):
        p, _ = QFileDialog.getSaveFileName(self, "选择输出文件",
                                           self.in_edit.text() or engine.APP_DIR,
                                           "字幕文件 (*.srt);;所有文件 (*.*)")
        if p:
            self.out_edit.setText(p)

    def start(self):
        if self.running:
            InfoBar.info("提示", "校准任务进行中，请稍候", duration=3000,
                         position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        if not os.path.isfile(self._script):
            MessageBox("错误", f"校准脚本缺失：{self._script}", self).exec()
            return
        src = engine.clean_path(self.in_edit.text())
        if not src or not os.path.isfile(src):
            InfoBar.warning("提示", "请先选择一个 .srt 字幕文件", duration=3000,
                            position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        mode_flag = self.MODES[self.mode_combo.currentIndex()][1]
        stats_only = self.stats_switch.isChecked()

        out = ""
        if not stats_only:
            out = engine.clean_path(self.out_edit.text())
            if not out:
                out = os.path.splitext(src)[0] + ".calib.srt"
            if os.path.exists(out):
                stem, ext = os.path.splitext(out)
                n = 2
                while os.path.exists(f"{stem}({n}){ext}"):
                    n += 1
                out = f"{stem}({n}){ext}"

        args = [engine.system_python(), self._script, src]
        if out:
            args += ["--out", out]
            if self.report_switch.isChecked():
                args += ["--report", os.path.splitext(out)[0] + ".md"]
        if mode_flag:
            args.append(mode_flag)
        if self.layout_switch.isChecked():
            args.append("--layout")
        if self.fix_switch.isChecked():
            args.append("--fix-en")

        self.running = True
        self.run_btn.setEnabled(False)
        self.stage_label.setText("正在校准…")
        self.log.line(f"[校准] 模式: {self.mode_combo.currentText()}"
                      + ("（仅统计）" if stats_only else ""), "dim")
        self.log.line(f"[校准] 输入: {os.path.basename(src)}", "dim")
        if out:
            self.log.line(f"[校准] 输出: {out}", "dim")
        threading.Thread(target=self._worker, args=(args, out), daemon=True).start()

    def _worker(self, args, out):
        try:
            env = dict(os.environ, PYTHONIOENCODING="utf-8")
            proc = engine.popen_process(args, cwd=os.path.dirname(self._script),
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, encoding="utf-8", errors="replace",
                                        bufsize=1, env=env)
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    self.app.q.put(("cal_log", line))
            rc = proc.wait()
        except Exception as e:  # noqa: BLE001
            self.app.q.put(("cal_log", f"[错误] 校准进程异常: {e}"))
            rc = 1
        self.app.q.put(("cal_done", rc, out))

    def on_cal_done(self, rc, out):
        self.running = False
        self.run_btn.setEnabled(True)
        if rc == 0:
            self.stage_label.setText("校准完成")
            self.log.line("[OK] 校准完成" +
                          (f"，输出: {out}" if out else "（仅统计模式，未改写文件）"), "ok")
        else:
            self.stage_label.setText("校准失败")
            self.log.line(f"[错误] 校准失败（退出码 {rc}），详见上方日志", "err")


# ========== 主窗口 ==========
PAGE_TITLES = {"DownloadPage": "视频下载", "LibraryPage": "视频库",
               "MergePage": "音视频合并", "SubtitlePage": "字幕处理",
               "CalibPage": "字幕校准"}


class MainWindow(FluentWindow):
    """FluentWindow + 左侧导航（结构与主流 Fluent 桌面应用一致）。"""

    def __init__(self, argv=None):
        super().__init__()
        self.q = queue.Queue()
        self.setWindowTitle(f"视频工具箱 v{VERSION}")
        self.resize(1180, 860)
        self.setMinimumSize(960, 640)

        try:
            self.setMicaEffectEnabled(True)
        except Exception:
            pass

        self.download_page = DownloadPage(self, self)
        self.library_page = LibraryPage(self, self)
        self.merge_page = MergePage(self, self)
        self.subtitle_page = SubtitlePage(self, self)
        self.calib_page = CalibPage(self, self)

        self.addSubInterface(self.download_page, FIF.DOWNLOAD, "视频下载")
        self.addSubInterface(self.library_page, FIF.VIDEO, "视频库")
        self.addSubInterface(self.merge_page, FIF.MEDIA, "音视频合并")
        self.navigationInterface.addSeparator()
        self.addSubInterface(self.subtitle_page, FIF.FONT, "字幕处理")
        self.addSubInterface(self.calib_page, FIF.EDIT, "字幕校准")

        # 侧边导航常驻展开（默认窄条只有图标）
        self.navigationInterface.setCollapsible(False)

        self.switchTo(self.download_page)
        self._apply_argv(argv or [])
        QTimer.singleShot(400, self.library_page.auto_load)
        QTimer.singleShot(120, self._pump)

    # ---------- 页面/状态 ----------
    def fit_to_screen(self):
        """按所在屏幕可用区域收敛窗口尺寸并居中。

        1180x860 的默认尺寸在小屏（1080p 任务栏/150% 缩放）上会超出屏幕，
        导致右侧按钮被裁掉——启动时先按可用区域的 92% 收敛。
        """
        try:
            avail = self.screen().availableGeometry()
        except Exception:
            return
        w = min(self.width(), int(avail.width() * 0.92))
        h = min(self.height(), int(avail.height() * 0.92))
        w = max(w, self.minimumWidth())
        h = max(h, self.minimumHeight())
        self.resize(w, h)
        self.move(avail.x() + (avail.width() - w) // 2,
                  avail.y() + (avail.height() - h) // 2)

    def switchTo(self, page):
        self.stackedWidget.setCurrentWidget(page, popOut=False)
        self.setWindowTitle(
            f"视频工具箱 v{VERSION} — {PAGE_TITLES.get(page.objectName(), '')}")

    def page_by_key(self, key):
        return {"download": self.download_page, "library": self.library_page,
                "merge": self.merge_page, "subtitle": self.subtitle_page,
                "calib": self.calib_page}.get(key)

    def _apply_argv(self, argv):
        """命令行/拖入 .url、含链接的 txt：提取链接填到下载页。"""
        if not argv:
            return
        arg = engine.clean_path(argv[0])
        if not arg:
            return
        if os.path.isfile(arg):
            url = engine.extract_url(arg)
            if url:
                self.download_page.url_edit.setText(url)

    # ---------- 消息泵 ----------
    def _pump(self):
        try:
            while True:
                msg = self.q.get_nowait()
                self._dispatch(msg)
        except queue.Empty:
            pass
        QTimer.singleShot(120, self._pump)

    def _dispatch(self, msg):
        kind, args = msg[0], msg[1:]
        dl, lib, mg = self.download_page, self.library_page, self.merge_page
        cal = self.calib_page
        try:
            if kind == "detect_done":
                dl.on_detect_done(*args)
            elif kind == "sys_log":
                dl.log.line(args[0], "dim")
            elif kind == "dl_progress":
                dl.on_dl_progress(args[0], args[1])
            elif kind == "dl_log":
                dl.on_dl_log(args[0], args[1])
            elif kind == "dl_done":
                dl.on_dl_done(args[0], args[1], args[2])
            elif kind == "lib_scan_done":
                lib.on_scan_done(args[0], args[1])
            elif kind == "lib_thumb":
                lib.on_thumb(args[0], args[1])
            elif kind == "lib_thumb_fail":
                lib.on_thumb_fail(args[0])
            elif kind == "lib_log":
                lib.on_log(args[0])
            elif kind == "scan_done":
                mg.on_scan_done(*args)
            elif kind == "mg_log":
                mg.log.line(args[0], "dim")
            elif kind == "mg_progress":
                mg.progress.setValue(int(args[0]))
            elif kind == "mg_done":
                mg.on_mg_done(args[0], args[1], args[2])
            elif kind == "cal_log":
                cal.log.line(args[0], "dim")
            elif kind == "cal_done":
                cal.on_cal_done(args[0], args[1])
        except Exception as e:
            import traceback
            self._log_error(traceback.format_exc())
            InfoBar.error("界面更新出错", str(e)[:200], duration=5000,
                          position=InfoBarPosition.BOTTOM_RIGHT, parent=self)

    @staticmethod
    def _log_error(text):
        try:
            os.makedirs(engine.LOGS_DIR, exist_ok=True)
            with open(os.path.join(engine.LOGS_DIR, "gui_errors.log"),
                      "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {text}\n")
        except OSError:
            pass


def configure_qt_plugins():
    """显式指定 Qt 平台插件目录（必须在创建 QApplication 之前调用）。

    内置 PyQt5 不是用安装器装的，而是把 wheel 解包到 tools\\python 的
    site-packages —— Qt 按 sys.prefix 推算插件的默认逻辑在这种情况下找不到
    platforms/qwindows.dll，会直接报
    「no Qt platform plugin could be initialized」并弹模态框卡住进程。
    忽略平台插件目录的探测在打包后由 PyInstaller 的钩子负责（它会把
    platforms/qwindows.dll 一起打进包里），此时若强行指向内置运行时的
    PyQt5 反而可能因版本不一致而崩，故冻结模式下直接跳过。
    """
    if getattr(sys, "frozen", False):
        return ""
    for base in (engine.EMBEDDED_SITE_PACKAGES,
                 os.path.join(engine.TOOLS_DIR, "python", "Lib", "site-packages")):
        plugins = os.path.join(base, "PyQt5", "Qt5", "plugins")
        if os.path.isdir(plugins):
            os.environ.setdefault("QT_QPA_PLATFORM_PLUGIN_PATH", plugins)
            os.environ.setdefault("QT_PLUGIN_PATH", plugins)
            return plugins
    return ""


def main():
    configure_qt_plugins()
    # 矢量化：高分屏按逻辑像素缩放、图标/文字按矢量渲染，避免放大后发虚
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    setTheme(Theme.DARK)
    setThemeColor("#2F8D63")    # 品牌绿（与字幕引擎界面同色系）
    app.setFont(QFont("Microsoft YaHei UI", 9))   # 9pt 紧凑正文，高分屏随缩放走
    window = MainWindow(sys.argv[1:])
    window.fit_to_screen()

    shot_tab = os.environ.get("VT_SHOT_TAB")
    if shot_tab:
        page = window.page_by_key(shot_tab)
        if page:
            QTimer.singleShot(700, lambda: window.switchTo(page))
    shot_file = os.environ.get("VT_SHOT_FILE")
    if shot_file:
        def _shot():
            # 只抓本窗口：QScreen.grabWindow(传窗口句柄) 走 PrintWindow，即使被遮挡
            # 也只渲染本窗口，不会把桌面上其它应用的内容截进来（传 0 才是抓屏幕区域）。
            scr = QApplication.primaryScreen()
            try:
                pm = scr.grabWindow(int(window.winId()))
            except Exception:
                pm = None
            if pm is None or pm.isNull():
                pm = window.grab()
            pm.save(shot_file)
            print(f"[shot] saved: {shot_file}")
            QApplication.quit()
        QTimer.singleShot(2600, _shot)
    if os.environ.get("VT_GUI_SELFTEST"):
        def _ok():
            try:
                with open(os.path.join(engine.DATA_DIR, "GUI_SELFTEST_OK"), "w",
                          encoding="utf-8") as f:
                    f.write("ok:" + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            except OSError:
                pass
            QApplication.quit()
        QTimer.singleShot(2600, _ok)

    window.show()
    window.raise_()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
