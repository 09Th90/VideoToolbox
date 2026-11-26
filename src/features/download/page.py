# -*- coding: utf-8 -*-
# @version 3.3.1
"""视频下载页（2026-11-15 功能解耦阶段③：从 video_toolbox_qt.py 拆出，逐字同源）。

* 容器页：「视频下载 / 音画合并 / 视频切片」三个子板块，merge/split 经注册表
  服务组装（功能缺失时板块与分段自动缺席）；
* 消息自订阅（bus「detect_done / sys_log / dl_」），不再依赖入口 _dispatch；
* 后端：core.download.job / scheduler（队列模式）+ engine 的 yt-dlp 原语，
  NPE 第二引擎兜底（npe_backend）。
"""
import contextlib
import json
import os
import re
import subprocess
import threading
import time
from collections import deque

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QFileDialog,
                               QHBoxLayout, QHeaderView, QSizePolicy,
                               QStackedWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from vt_fluent import (BodyLabel, CaptionLabel, FluentIcon as FIF, InfoBar,
                       InfoBarPosition, LineEdit, ListWidget, MessageBox,
                       PrimaryPushButton, ProgressBar, PushButton,
                       SegmentedWidget, SpinBox, StrongBodyLabel, SwitchButton,
                       TableWidget)

import video_toolbox as engine
import ui_theme
from core.download.util import note_download_dir_owner
from core.download.ytdlp_util import (
    _finished_video as _dl_finished_video,
    _track_leftovers as _dl_track_leftovers,
    ytdlp_is_live, ytdlp_live_args, ytdlp_live_flag_unsupported,
)

from vt_app.boot import _perf_note
from vt_app.widgets import LogView, PageHeader, TabPage, card, row, srow


class _CancelledEarly(Exception):
    """下载线程在引导阶段（ensure_ytdlp / ensure_ffmpeg）就被取消。

    v1.19.1：引导阶段原先连取消标志都不看，用户点完取消还得干等 ~170MB
    的 ffmpeg 下载完。用专用异常而非返回码，是为了不污染 `rc` 语义
    （1 = 失败，只有 RC_CANCELLED 才走临时文件清理分支）。
    """


class _GuiJobRunner:
    """把 DownloadPage._run_ytdlp 适配成 core job 的 YtdlpRunner。"""

    def __init__(self, page, task_id):
        self.page = page
        self.task_id = task_id

    def run(self, cmd, *, phase="download"):
        from core.download.job import RunResult
        rc, lines = self.page._run_ytdlp(list(cmd), self.task_id, phase)
        return RunResult(int(rc), tuple(lines))


class DownloadPage(QWidget):
    """单个链接反复添加；每个下载任务独立线程，互不阻塞。

    v1.13.0：原「音视频合并」板块更名为「音画合并」并并入本页——
    页内用 SegmentedWidget 分段切换「视频下载 / 音画合并 / 视频切片」三个子板块（三等分），
    参考字幕处理页的「一页多板块」形态。
    """

    _EXTRACT_LOCK = threading.Lock()
    SUB_LANGS = "en,zh,ja,zh-Hans,zh-Hant,ko,es,fr,de"
    #: 下载分片大小：YouTube 直链要求 Range 请求，不分片就 403（见下方说明）。
    #: 取引擎常量，保证下载页与流水线不会各自漂移。
    DL_CHUNK_SIZE = engine.YTDLP_CHUNK_SIZE

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
        # v1.19.0 下载中止：task_id → threading.Event（置位 = 用户请求取消）、
        # task_id → 当前正在跑的 yt-dlp/ffmpeg 子进程（取消时直接强杀）。
        self._cancel_events = {}
        self._procs = {}
        self._queue_mode = False
        self.dl_queue = None
        self._pause_events = {}
        self._run_ids = {}
        self._last_stats = {}
        self._max_syncing = False
        self._completed_dirs = set()
        self._cleaned_cancelled = set()

        # 功能解耦阶段③：消息自订阅（原入口 _dispatch 的 detect_done/sys_log/dl_* 分支）。
        # 自检桩没有 bus，允许跳过（真实 App 一定有）。
        _bus = getattr(app, "bus", None)
        if _bus is not None:
            _bus.subscribe("detect_done", self._on_bus_message)
            _bus.subscribe("sys_log", self._on_bus_message)
            _bus.subscribe("dl_", self._on_bus_message)

        try:
            from core.download.job import download_orchestrator
            from core.download.scheduler import DownloadQueue, queue_mode_enabled
            if (download_orchestrator(default="job") == "job"
                    and queue_mode_enabled(default=True)):
                self._queue_mode = True
                self.dl_queue = DownloadQueue(
                    max_concurrent=self._load_max_concurrent(),
                    on_event=self._on_queue_event,
                )
        except Exception:
            self._queue_mode = False
            self.dl_queue = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        head_wrap = QWidget(self)
        hw = QHBoxLayout(head_wrap)
        hw.setContentsMargins(22, 12, 22, 0)
        self.header = PageHeader(
            "视频下载",
            "粘贴链接后检测画质；下载自动打包封面、视频信息与字幕", head_wrap)
        hw.addWidget(self.header)
        outer.addWidget(head_wrap)

        # —— 页内分段：视频下载 / 音画合并 ——
        # v1.13.x：改为**铺满整行**（与「字幕处理」页观感对齐）。SegmentedWidget 对
        # 每项固定 stretch=1 等分：铺满后两个标签各占半行、文字居中、下划线跟文字走，
        # 不再缩在左上角一小团。旧版为了躲"窗口变宽被拉开空隙"把宽度收缩到内容并
        # 靠左对齐，结果就是"挤在一边"。
        # ⚠️ 边距必须加在**外层容器**上，绝不能设在 SegmentedWidget 自己身上：
        #    qfluentwidgets 的 `SegmentedWidget.paintEvent` 画选中框用的是
        #    `item.rect()`，而 `item.rect()` 恒为 (0,0,w,h)——它**忽略了 item
        #    在布局里的实际 y**。一旦控件自身带 contentsMargins，item 被整体
        #    下压 12px，框却仍画在 y=1，于是就成了「灰色区域贴顶、文字偏下」
        #    的错位（用户反馈的那张图）。边距挪到外层容器后两者重新对齐。
        self.seg = SegmentedWidget(self)
        self.seg.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        seg_wrap = QWidget(self)
        seg_lay = QHBoxLayout(seg_wrap)
        seg_lay.setContentsMargins(22, 4, 22, 0)
        seg_lay.setSpacing(0)
        seg_lay.addWidget(self.seg)
        outer.addWidget(seg_wrap)

        self.stack = QStackedWidget(self)
        outer.addWidget(self.stack, 1)

        # —— 子板块 1：视频下载（可滚动卡片区） ——
        self.dl_tab = TabPage(self)
        self.stack.addWidget(self.dl_tab)
        self.vbox = self.dl_tab.content_lay
        self.vbox.setSpacing(10)

        # —— 输入区（v3：合并为一张任务输入卡，链接/目录/画质/字幕同屏） ——
        self.url_edit = LineEdit(self)
        self.url_edit.setPlaceholderText("粘贴视频链接（支持 B 站 / YouTube 等）")
        paste_btn = PushButton(FIF.PASTE, "粘贴", self)
        paste_btn.clicked.connect(self.paste_url)

        self.dest_edit = LineEdit(self)
        self.dest_edit.setText(engine.get_saved_download_dir())
        self.dest_edit.textChanged.connect(self._on_dest_change)
        browse_btn = PushButton(FIF.FOLDER, "浏览…", self)
        browse_btn.clicked.connect(self.browse_dest)

        self.qlist = ListWidget(self)
        self.qlist.setObjectName("QualityList")
        self.qlist.setMinimumHeight(84)
        self.qlist.setMaximumHeight(102)
        self._paint_quality_list()
        self._quality_placeholder()
        ui_theme.connect_theme(
            self.qlist, lambda w: self._paint_quality_list())
        self.detect_btn = PrimaryPushButton(FIF.SEARCH, "检测画质", self)
        self.detect_btn.clicked.connect(self.detect)

        self.sub_switch = SwitchButton(self)
        self.sub_switch.setChecked(True)
        self.prog = ProgressBar(self)
        self.pct_label = CaptionLabel("等待检测", self)
        self.dl_btn = PrimaryPushButton(FIF.DOWNLOAD, "加入并行下载", self)
        self.dl_btn.clicked.connect(self.start_download)

        box, lay = card(
            "任务输入", "链接 → 检测画质 → 加入并行队列；下载自动打包独立文件夹")
        lay.addWidget(srow("视频链接", self.url_edit, paste_btn))
        lay.addWidget(srow("保存位置", self.dest_edit, browse_btn))
        lay.addWidget(row(CaptionLabel("可用画质", self), None, self.detect_btn))
        lay.addWidget(self.qlist)
        lay.addWidget(row(BodyLabel("同时下载字幕（博主上传 + 自动生成，自动转 SRT）", self),
                          self.sub_switch, None))
        lay.addWidget(row(self.prog, self.pct_label, self.dl_btn))
        self.vbox.addWidget(box)

        # —— 任务列表 ——
        self.task_table = TableWidget(self)
        self.task_table.setBorderVisible(True)
        self.task_table.setBorderRadius(8)
        self.task_table.setWordWrap(False)
        self.task_table.setColumnCount(8)
        self.task_table.setHorizontalHeaderLabels(
            ["任务", "链接", "画质", "进度", "速度", "剩余", "状态", "保存位置"])
        self.task_table.verticalHeader().hide()
        self.task_table.setMinimumHeight(190)
        self.task_table.setMaximumHeight(300)
        self.task_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.task_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        for i, w in enumerate((56, 220, 66, 66, 78, 70, 70, 240)):
            self.task_table.setColumnWidth(i, w)
        self.task_table.horizontalHeader().setSectionResizeMode(7, QHeaderView.Stretch)
        self.task_table.itemSelectionChanged.connect(self.on_task_select)
        box, lay = card()
        # v1.19.0：选中一行后点「取消选中任务」即可中止该下载。
        self.pause_btn = PushButton(FIF.PAUSE, "暂停", self)
        self.pause_btn.setEnabled(False)
        self.pause_btn.clicked.connect(self.pause_selected_task)
        self.cancel_btn = PushButton(FIF.CANCEL, "取消选中任务", self)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_selected_task)
        lay.addWidget(row(StrongBodyLabel("并行下载任务", self),
                          CaptionLabel("点击任务行可查看对应进度", self),
                          None, self.pause_btn, self.cancel_btn))
        self.max_spin = SpinBox(self)
        self.max_spin.setRange(1, 6)
        self.max_spin.setValue(self._load_max_concurrent())
        self.max_spin.valueChanged.connect(self._on_max_concurrent_changed)
        lay.addWidget(row(None, CaptionLabel("下载并发上限", self), self.max_spin))
        lay.addWidget(self.task_table)
        self.vbox.addWidget(box)

        self.log = LogView("下载日志", 110, self)
        self.vbox.addWidget(self.log)
        self.vbox.addStretch(1)

        # —— 子板块 2：音画合并（阶段③：注册表组装，merge 功能缺失时自动缺席） ——
        # v1.14.2 修复：app 必须传主窗口（消息队列 q 挂在主窗口上，传本页会
        # 导致合并线程投递日志即抛 AttributeError 而死）。
        self.merge_page = None
        try:
            from features import registry
            self.merge_page = registry().service("merge", "build_page")(self.app, self)
            self.stack.addWidget(self.merge_page)
        except Exception as _e:  # noqa: BLE001
            _perf_note(f"音画合并板块不可用（不影响下载/切片）：{_e}")

        # —— 子板块 3：视频切片（v2.10.0；阶段③：注册表组装，同上） ——
        self.split_page = None
        try:
            from features import registry
            self.split_page = registry().service("split", "build_page")(self.app, self)
            self.stack.addWidget(self.split_page)
        except Exception as _e:  # noqa: BLE001
            _perf_note(f"视频切片板块不可用（不影响下载/合并）：{_e}")

        # —— 分段联动 ——
        # v2.10.0：三项（视频下载 / 音画合并 / 视频切片）——SegmentedWidget 每项
        # 固定 stretch=1，铺满整行后正好三等分（见上方长注释）。
        # 阶段③：merge/split 分段按可用性挂载，索引取实际堆叠位置（功能缺席
        # 时剩余分段仍正确切换）。
        self.seg.addItem(
            "download", "视频下载",
            onClick=lambda: self._select_sub(
                0, "视频下载",
                "粘贴链接后检测画质；下载自动打包封面、视频信息与字幕"))
        if self.merge_page is not None:
            _mi = self.stack.count() - 1
            self.seg.addItem(
                "merge", "音画合并",
                onClick=lambda i=_mi: self._select_sub(
                    i, "音画合并",
                    "自动配对或手动双轨；输出写入「合成结果」"))
        if self.split_page is not None:
            _si = self.stack.count() - 1
            self.seg.addItem(
                "split", "视频切片",
                onClick=lambda i=_si: self._select_sub(
                    i, "视频切片",
                    "按时间点或时长拆段；默认无损快切，逐段校验可播"))
        self.seg.setCurrentItem("download")
        self.switch_tab = lambda i: self.stack.setCurrentIndex(i)

    def _select_sub(self, idx, title, caption):
        self.stack.setCurrentIndex(idx)
        if getattr(self, "header", None) is not None:
            self.header.title.setText(title)
            self.header.cap.setText(caption)

    def _paint_quality_list(self):
        t = ui_theme.tokens()
        self.qlist.setStyleSheet(
            "QListWidget#QualityList{background:%s;border:1px solid %s;"
            "border-radius:8px;padding:4px;}"
            "QListWidget#QualityList::item{padding:4px 8px;border-radius:5px;}"
            "QListWidget#QualityList::item:selected{background:%s;color:%s;}"
            % (t["input_bg"], t["card_border"], t["card_hover"], t["text"]))

    def _quality_placeholder(self):
        """空态占位：避免画质列表是一个没有说明的大空框。"""
        self.qlist.clear()
        self.qlist.addItem("粘贴链接并点「检测画质」，这里会列出可用格式")
        item = self.qlist.item(0)
        if item is not None:
            item.setFlags(Qt.NoItemFlags)
        self.qlist.setCurrentRow(-1)

    # ---------- 消息 ----------
    def _on_bus_message(self, msg):
        """bus 消息（原入口 _dispatch 的 detect_done/sys_log/dl_* 分支，语义逐字一致）。"""
        kind, args = msg[0], msg[1:]
        if kind == "detect_done":
            self.on_detect_done(*args)
        elif kind == "sys_log":
            self.log.line(args[0], "dim")
        elif kind == "dl_progress":
            self.on_dl_progress(*args)
        elif kind == "dl_log":
            self.on_dl_log(*args)
        elif kind == "dl_done":
            self.on_dl_done(*args)
        elif kind == "dl_queue_event":
            self.on_queue_event(args[0])

    # ---------- 交互 ----------
    def _read_url(self):
        """读取并归一化输入框链接。

        复用 ``extract_web_url``：覆盖漏协议头（bilibili.com/...）、分享文案
        整段、包裹引号/尖括号、尾部标点；纯文本/本地路径时返回 ``""``。
        """
        raw = self.url_edit.text()
        url = engine.extract_web_url(raw)
        if url and url != raw:
            self.url_edit.setText(url)
        return url

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
        url = self._read_url()
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
            self._quality_placeholder()
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

    @staticmethod
    def _load_max_concurrent():
        try:
            n = int(engine.load_config().get("download_max_concurrent", 2))
        except Exception:
            n = 2
        return max(1, min(6, n))

    @staticmethod
    def _save_max_concurrent(value):
        try:
            cfg = engine.load_config()
            cfg["download_max_concurrent"] = max(1, min(6, int(value)))
            engine.save_config(cfg)
        except Exception:
            pass

    def _on_max_concurrent_changed(self, value):
        if self._max_syncing:
            return
        self.apply_max_concurrent(value, save=True)

    def apply_max_concurrent(self, value, save=True):
        n = max(1, min(6, int(value)))
        if save:
            self._save_max_concurrent(n)
        self._max_syncing = True
        try:
            self.max_spin.setValue(n)
        finally:
            self._max_syncing = False
        if self.dl_queue is not None:
            self.dl_queue.set_max_concurrent(n)
        self.log.line(f"[队列] 并发上限已改为 {n}（调低不会打断正在下载的任务）", "dim")

    def start_download(self):
        url = self._read_url()
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
            if item["url"] == url and item.get("status") in ("下载中", "排队中", "暂停中", "已暂停"):
                self._info("这个视频已在队列中，无需重复添加")
                return

        dest = engine.clean_path(self.dest_edit.text()) or engine.DEFAULT_DOWNLOAD_DIR
        os.makedirs(dest, exist_ok=True)
        engine.set_saved_download_dir(dest)
        fmt = self.qualities[sel]
        fid, height = fmt["format_id"], fmt["height"]

        try:
            raw_text = engine.read_text_any(self.info_json_path)
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
            "url": url, "quality": f"{height}p", "pct": 0.0, "status": "排队中",
            "dest": dest, "folder": task_folder, "with_subs": with_subs,
            "fid": str(fid), "height": height, "quality_label": f"{height}p",
            "info_json_path": task_info, "meta": meta, "resume_info": "",
            "state": "queued", "state_rev": 0, "speed": 0.0, "eta": -1.0,
        }
        self._cancel_events[task_id] = threading.Event()
        self._pause_events[task_id] = threading.Event()

        if self._queue_mode and self.dl_queue is not None:
            existing = self.dl_queue.find_active(url, str(fid))
            if existing is not None:
                self.tasks.pop(task_id, None)
                self._cancel_events.pop(task_id, None)
                self._pause_events.pop(task_id, None)
                try:
                    os.rmdir(task_folder)
                except OSError:
                    pass
                r = self._row_of.get(existing.task_id)
                if r is not None:
                    self.task_table.selectRow(r)
                self._info("这个视频已在队列中，无需重复添加")
                return
            self.dl_queue.add(task_id, url, str(fid))
            self._add_task_row(task_id, url, f"{height}p", "0.0%", "—", "—",
                               "排队中", task_folder)
            self.active_task = task_id
            self.prog.setValue(0)
            self.pct_label.setText("排队中")
            sub_note = "（含字幕）" if with_subs else ""
            self.log.line(f"[任务 {task_id}] {height}p 已加入队列{sub_note} → {task_folder}", "dim")
            self.log.line("[提示] 达到并发上限后会等待槽位；可继续检测并添加下一个视频", "dim")
            return

        self.tasks[task_id]["status"] = "下载中"
        self._add_task_row(task_id, url, f"{height}p", "0.0%", "—", "—",
                           "下载中", task_folder)
        self.active_task = task_id
        self.prog.setValue(0)
        self.pct_label.setText("0.0%")
        sub_note = "（含字幕）" if with_subs else ""
        self.log.line(f"[任务 {task_id}] {height}p 开始下载{sub_note} → {task_folder}", "dim")
        self.log.line("[提示] 该任务已在后台运行，可以继续检测并添加下一个视频", "dim")
        threading.Thread(
            target=self._download_worker,
            args=(task_id, url, fid, task_folder, with_subs, task_info, meta,
                  f"{height}p"),
            daemon=True).start()

    # ---------- 任务表 ----------
    def _add_task_row(self, task_id, url, quality, pct, speed, eta, status, dest):
        r = self.task_table.rowCount()
        self.task_table.insertRow(r)
        values = (task_id, self._display_url(url), quality, pct, speed, eta, status, dest)
        for c, text in enumerate(values):
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

    @staticmethod
    def _queue_state_text(state):
        return {
            "queued": "排队中", "downloading": "下载中", "pausing": "暂停中",
            "paused": "已暂停", "cancelling": "取消中", "cancelled": "已取消",
            "completed": "完成", "failed": "失败",
        }.get(getattr(state, "value", str(state)), str(state))

    def _on_queue_event(self, ev):
        self.app.q.put(("dl_queue_event", ev))

    def on_queue_event(self, ev):
        if not self._queue_mode or self.dl_queue is None:
            return
        from core.download.scheduler import TaskState
        item = self.tasks.get(ev.task_id)
        if ev.kind == "run":
            task = self.dl_queue.get_task(ev.task_id)
            if (task is None or task.state != TaskState.DOWNLOADING
                    or task.run_id != ev.run_id):
                self.dl_queue.worker_stopped(
                    ev.task_id, ev.run_id,
                    cancelled=bool(task and task.state == TaskState.CANCELLING),
                    paused=bool(task and task.state == TaskState.PAUSING),
                    error="not started")
                return
            self._start_task_worker(ev.task_id, ev.run_id)
            return
        if item is None:
            return
        if ev.kind == "state":
            if ev.revision < int(item.get("state_rev", 0)):
                return
            item["state_rev"] = ev.revision
            item["state"] = ev.state.value
            item["status"] = self._queue_state_text(ev.state)
            self._set_cell(ev.task_id, 6, item["status"])
            if ev.task_id == self.active_task:
                self.pct_label.setText(item["status"])
            self._sync_task_buttons()
        elif ev.kind == "progress":
            self._apply_queue_progress(ev)
        elif ev.kind == "finished":
            self._on_queue_finished(ev)

    def _apply_queue_progress(self, ev):
        item = self.tasks.get(ev.task_id)
        if item is None:
            return
        item["pct"] = ev.progress
        item["speed"] = ev.speed
        item["eta"] = ev.eta
        self._set_cell(ev.task_id, 3, f"{ev.progress:.1f}%")
        self._set_cell(ev.task_id, 4, engine.format_size(ev.speed) + "/s" if ev.speed else "—")
        self._set_cell(ev.task_id, 5, engine.format_time(ev.eta) if ev.eta and ev.eta > 0 else "—")
        if ev.task_id == self.active_task:
            self.prog.setValue(int(ev.progress))
            self.pct_label.setText(f"{ev.progress:.1f}%")

    def _drop_info_file(self, item):
        path = item.get("info_json_path") or ""
        if path and os.path.isfile(path):
            try:
                os.remove(path)
            except OSError:
                pass
        item["info_json_path"] = ""

    def _on_queue_finished(self, ev):
        item = self.tasks.get(ev.task_id)
        if item is None or self.dl_queue is None:
            return
        from core.download.scheduler import TaskState
        if ev.state == TaskState.COMPLETED:
            item["state"] = "completed"
            item["status"] = "完成"
            item["pct"] = 100.0
            self._set_cell(ev.task_id, 3, "100%")
            self._set_cell(ev.task_id, 6, "完成")
            self._set_cell(ev.task_id, 7, item.get("folder", ""))
            self._drop_info_file(item)
            item["resume_info"] = ""
            self._completed_dirs.add(item.get("dest") or os.path.dirname(item.get("folder", "")))
            self._finish_queue_maps(ev.task_id)
            self.log.line(f"[任务 {ev.task_id}] [完成] 已打包到独立文件夹: {item.get('folder','')}", "ok")
            if ev.task_id == self.active_task:
                self.prog.setValue(100)
                self.pct_label.setText("完成")
            if self.dl_queue.is_idle():
                self._refresh_after_idle(ev.task_id)
        elif ev.state == TaskState.CANCELLED:
            item["state"] = "cancelled"
            item["status"] = "已取消"
            self._set_cell(ev.task_id, 3, "—")
            self._set_cell(ev.task_id, 6, "已取消")
            self._drop_info_file(item)
            item["resume_info"] = ""
            self._cleanup_cancelled_once(item)
            self.log.line(f"[任务 {ev.task_id}] [已取消] 未完成的部分已清理", "err")
            self._finish_queue_maps(ev.task_id)
        elif ev.state == TaskState.PAUSED:
            item["state"] = "paused"
            item["status"] = "已暂停"
            self._set_cell(ev.task_id, 6, "已暂停")
            self.log.line(f"[任务 {ev.task_id}] [已暂停] 分片已保留，可点击继续；HLS 恢复时可能从当前源重下", "dim")
            self._procs.pop(ev.task_id, None)
            self._run_ids.pop(ev.task_id, None)
            self._last_stats.pop(ev.task_id, None)
        else:
            item["state"] = "failed"
            item["status"] = "失败"
            self._set_cell(ev.task_id, 3, "—")
            self._set_cell(ev.task_id, 6, "失败")
            self._drop_info_file(item)
            self.log.line(f"[任务 {ev.task_id}] [错误] 下载失败：{ev.error or '未知错误'}", "err")
            self._finish_queue_maps(ev.task_id)
        self._sync_task_buttons()

    def _cleanup_cancelled_once(self, item):
        tid = [k for k, v in self.tasks.items() if v is item]
        if not tid or tid[0] in self._cleaned_cancelled:
            return
        self._cleaned_cancelled.add(tid[0])
        folder = item.get("folder", "")
        if folder:
            self._cleanup_cancelled(tid[0], folder)

    def _finish_queue_maps(self, task_id):
        DownloadPage._EOF_HINTED.pop(task_id, None)
        DownloadPage._EOF_KILLS.pop(task_id, None)
        self._cancel_events.pop(task_id, None)
        self._pause_events.pop(task_id, None)
        self._procs.pop(task_id, None)
        self._run_ids.pop(task_id, None)
        self._last_stats.pop(task_id, None)

    def _refresh_after_idle(self, task_id):
        root = ""
        if self._completed_dirs:
            root = sorted(self._completed_dirs)[-1]
            self._completed_dirs.clear()
        if root:
            self.app.library_page.set_dir(root)
            self.app.library_page.refresh()
        if task_id == self.active_task:
            item = self.tasks.get(task_id)
            if item and item.get("folder"):
                engine.open_folder(item["folder"])

    def _start_task_worker(self, task_id, run_id):
        item = self.tasks.get(task_id)
        if not item:
            self.dl_queue.worker_stopped(task_id, run_id, error="task missing")
            return
        self._run_ids[task_id] = run_id
        self._last_stats[task_id] = (0.0, -1.0)
        self._cancel_events.setdefault(task_id, threading.Event()).clear()
        self._pause_events.setdefault(task_id, threading.Event()).clear()
        item["state"] = "downloading"
        item["status"] = "下载中"
        self._set_cell(task_id, 6, "下载中")
        threading.Thread(
            target=self._download_worker,
            args=(task_id, item["url"], item.get("fid", ""), item["folder"],
                  item.get("with_subs", False), item.get("info_json_path", ""),
                  item.get("meta"), item.get("quality_label", ""),
                  run_id, item.get("resume_info", "")),
            daemon=True,
        ).start()

    def _sync_task_buttons(self):
        if not self._queue_mode:
            return
        item = self.tasks.get(self.active_task)
        if item is None:
            self.pause_btn.setEnabled(False)
            self.cancel_btn.setEnabled(False)
            return
        state = item.get("state")
        self.pause_btn.setEnabled(state in ("queued", "downloading", "paused"))
        if state == "paused":
            self.pause_btn.setText("继续")
            self.pause_btn.setIcon(FIF.PLAY)
        else:
            self.pause_btn.setText("暂停")
            self.pause_btn.setIcon(FIF.PAUSE)
        self.cancel_btn.setEnabled(state in ("queued", "downloading", "pausing", "paused"))

    def _selected_task_id(self):
        rows = self.task_table.selectionModel().selectedRows()
        if not rows:
            return ""
        r = rows[0].row()
        for tid, rr in self._row_of.items():
            if rr == r:
                return tid
        return ""

    def pause_selected_task(self):
        if not self._queue_mode or self.dl_queue is None:
            self._info("当前是旧下载模式，不支持暂停")
            return
        tid = self._selected_task_id()
        item = self.tasks.get(tid)
        if not item:
            self._warn("请先选中任务")
            return
        state = item.get("state")
        if state == "paused":
            self._pause_events.setdefault(tid, threading.Event()).clear()
            self.dl_queue.resume(tid)
            self.log.line(f"[任务 {tid}] 已继续，重新排队", "dim")
        elif state in ("queued", "downloading"):
            self._pause_events.setdefault(tid, threading.Event()).set()
            proc = self._procs.get(tid)
            if proc is not None:
                engine.kill_process_tree(proc)
            self.dl_queue.pause(tid)
            self.log.line(f"[任务 {tid}] 已请求暂停，等待当前进程退出并保留分片", "dim")
        else:
            self._info(f"任务 {tid} 当前状态为 {item.get('status')}，无需暂停")

    def on_task_select(self):
        rows = self.task_table.selectionModel().selectedRows()
        if not rows:
            self.cancel_btn.setEnabled(False)
            self.pause_btn.setEnabled(False)
            return
        r = rows[0].row()
        for tid, rr in self._row_of.items():
            if rr == r:
                self.active_task = tid
                item = self.tasks.get(tid)
                if item:
                    self.prog.setValue(int(item.get("pct", 0)))
                    self.pct_label.setText(
                        f"{item['pct']:.1f}%" if item.get("status") == "下载中" else item.get("status", ""))
                    if self._queue_mode:
                        self._sync_task_buttons()
                    else:
                        self.pause_btn.setEnabled(False)
                        self.cancel_btn.setEnabled(item["status"] == "下载中")
                break

    # ---------- 下载中止（v1.19.0） ----------
    #: 取消专用返回码：强杀子进程后 proc.wait() 的返回码不固定（Windows 上常是
    #: -9/1），统一收敛成这个值再投给 dl_done，主线程据此标记「已取消」。
    RC_CANCELLED = -9
    RC_PAUSED = -11
    #: 直链失效专用返回码：EOF / TLS 断连 / 403 意味着**已签发的链接本身作废**，
    #: 原地重试同一条 URL 是纯浪费（它仍绑定旧的出口 IP）。收敛成这个值，
    #: 让上层直接走「重新提取」而不是退避重试。
    #: 对应 engine.ytdlp_error_needs_reextract() 的判定。
    RC_REEXTRACT = -10

    #: 直链失效时最多重新提取几次。直链绑定签发时的出口 IP，代理一换节点旧链
    #: 全部作废，重新提取是唯一出路；但节点若持续抖动，反复提取也只是空耗，
    #: 到量就转普通失败，交给换源 / 第二引擎兜底。
    REEXTRACT_MAX = 2
    #: yt-dlp 输出只保留**尾部**这么多行供错误判定。
    #: HLS 源每片输出一行 `Downloading fragment N/M`——1069 片的下载就是
    #: 2138+ 行，直播存档能到上万行。全量累积既吃内存（多任务并行时叠加），
    #: 又让 `"\n".join(lines)` 每次重试都重拼一遍。错误判定（retryable /
    #: needs_reextract / err_brief）只看尾部，用环形缓冲即可。
    DL_LINES_KEEP = 600
    #: 下载输出里的 TLS EOF 特征（与 ytdlp_util.YTDLP_REEXTRACT_HINTS 同源，
    #: 这里只取用户最常看到的形态，用于在下载过程中提前给出 explanation）。
    _EOF_MARKS = ("EOF occurred in violation of protocol", "_ssl.c")
    #: 同一任务的同一类 EOF 只报一次：Retrying (1/10)…(10/10) 会重复刷屏。
    _EOF_HINTED = {}
    #: 单个任务内因 EOF **主动结束下载**的次数上限。
    #: EOF 说明已签发的链接作废，而 yt-dlp 自己的 `--retries` +
    #: `--retry-sleep exp=1:20`（最长 20s）会白耗数分钟才轮到上层重新提取
    #: （2026-10-17 监控实录：任务停滞 210MB 逾 10 分钟即此机制）。
    #: 主动结束可把这段等待压到 0；仍留上限，防止节点持续故障时无限循环。
    EOF_REEXTRACT_MAX = 2
    #: 各任务已发生的 EOF 主动结束次数（task_id -> int）；on_dl_done 回收。
    _EOF_KILLS = {}

    def _is_cancelled(self, task_id):
        evt = self._cancel_events.get(task_id)
        return bool(evt and evt.is_set())

    def _register_proc(self, task_id, proc):
        """把当前阶段（提取/下载/封面/NPE）的子进程登记到 _procs。

        v1.19.1：原先只有 `_run_ytdlp` 会登记，提取阶段
        （`fetch_info_json`）和封面阶段用的是引擎里另一个入口，取消按钮
        拿不到进程 → 点了取消完全没用。现在所有子进程都走这里。
        """
        if proc is None:
            self._procs.pop(task_id, None)
        else:
            self._procs[task_id] = proc

    def cancel_selected_task(self):
        """中止选中的下载任务：置标志 + 强杀当前子进程树，工作线程随即收敛。"""
        rows = self.task_table.selectionModel().selectedRows()
        if not rows:
            self._warn("请先在任务列表中选中要取消的任务")
            return
        r = rows[0].row()
        tid = next((t for t, rr in self._row_of.items() if rr == r), None)
        item = self.tasks.get(tid)
        if not item:
            return
        if self._queue_mode and self.dl_queue is not None:
            evt = self._cancel_events.get(tid)
            if evt:
                evt.set()
            proc = self._procs.get(tid)
            if proc is not None:
                engine.kill_process_tree(proc)
            self.dl_queue.cancel(tid)
            self.log.line(f"[任务 {tid}] 已请求取消，正在停止下载并清理临时文件 ...", "err")
            return
        if item["status"] != "下载中":
            self._info(f"任务 {tid} 已结束（{item['status']}），无需取消")
            return
        evt = self._cancel_events.get(tid)
        if evt:
            evt.set()
        proc = self._procs.get(tid)
        if proc is not None:
            # v1.19.1：杀进程**树**。yt-dlp/ffmpeg 会再 fork 子进程，
            # 只 kill 父进程的话孙进程继续写 .part、继续吃带宽。
            engine.kill_process_tree(proc)
        # v1.19.1：置「待确认」状态。原先立刻写死「已取消」，但只要
        # 队列里还有几条进度消息在泵，就会被 on_dl_progress 立刻改回
        # 「下载中」——用户看到的就是「点了取消，状态又跳回去了」。
        item["status"] = "取消中"
        self._set_cell(tid, 4, "—")
        self._set_cell(tid, 6, "取消中")
        self.cancel_btn.setEnabled(False)
        self.log.line(f"[任务 {tid}] 已请求取消，正在停止下载并清理临时文件 ...", "err")

    def _cleanup_cancelled(self, task_id, folder):
        """取消后清理半成品：.part/.ytdlp 分片、NPE 临时流文件；空文件夹一并移除。"""
        removed = 0
        try:
            names = os.listdir(folder)
        except OSError:
            names = []
        for name in names:
            low = name.lower()
            if low.endswith((".part", ".ytdlp", ".vtdl.resume.json",
                             ".vtdl.json", ".vtdl.single", ".vtdl.assembling",
                             ".npe_v.mp4", ".npe_a.m4a",
                             ".npe_v.m4v", ".npe_a.mp4", ".npe_v.webm",
                             ".npe_a.webm", ".npe_v.mp2t", ".npe_a.mp2t")):
                try:
                    os.remove(os.path.join(folder, name))
                    removed += 1
                except OSError:
                    pass
        if removed:
            self.app.q.put(("dl_log", task_id,
                            f"[清理] 已删除 {removed} 个未完成的临时文件"))
        try:
            os.rmdir(folder)  # 只删空目录；里面还有成品/字幕时保持原样
        except OSError:
            pass

    @staticmethod
    def _display_url(url, limit=44):
        return url if len(url) <= limit else url[: limit - 3] + "..."

    # ---------- 下载线程（与旧界面逻辑一致） ----------
    def _extract_lock(self, task_id, timeout=30.0):
        """可取消地获取提取锁；返回是否拿到。

        v1.19.1：`with _EXTRACT_LOCK` 是**不可中断阻塞**——并行任务里另一个
        正在做 180s 提取时，本任务卡在锁上，此时点取消毫无反应（它还没走到
        任何检查取消的地方）。改成带超时轮询，取消一置位立刻退出等待。
        """
        if task_id is None:
            DownloadPage._EXTRACT_LOCK.acquire()
            return True
        deadline = time.time() + timeout
        while True:
            if DownloadPage._EXTRACT_LOCK.acquire(timeout=0.2):
                return True
            if self._is_cancelled(task_id):
                return False
            if time.time() > deadline:
                self.app.q.put(("dl_log", task_id,
                                "[提取] 等待另一个任务的提取超时，继续排队重试"))
                return DownloadPage._EXTRACT_LOCK.acquire(timeout=0.2)

    def _fetch_info_for_task(self, task_id, ytdlp, url, slog):
        """任务线程内的提取：带取消 + 子进程登记。"""
        with contextlib.ExitStack() as stack:
            if not self._extract_lock(task_id):
                return None
            stack.callback(DownloadPage._EXTRACT_LOCK.release)
            evt = self._cancel_events.get(task_id)
            return engine.fetch_info_json(
                ytdlp, url, log=slog,
                cancel=evt,
                register=lambda p: self._register_proc(task_id, p))

    def _download_worker_job(self, task_id, url, fid, folder, with_subs=False,
                             info_json_path=None, meta=None, quality_label="",
                             run_id=0, resume_info=""):
        """P1b：走 core.download.job；旧 _download_worker 保留为 legacy。"""
        from core.download.job import (
            DownloadJob, JobHooks, run_download_job,
        )
        evt = self._cancel_events.get(task_id)
        pause_evt = self._pause_events.get(task_id)
        source_info = resume_info or info_json_path or ""
        try:
            def log(m, lv="dim"):
                if lv == "sys":
                    self.app.q.put(("sys_log", f"[任务 {task_id}] {m}"))
                else:
                    self.app.q.put(("dl_log", task_id, m, lv))

            def extract(_ytdlp, _url):
                return self._fetch_info_for_task(
                    task_id, _ytdlp, _url,
                    lambda m: self.app.q.put(("sys_log", f"[任务 {task_id}] {m}")))

            def make_cover(ff, f):
                return engine.make_cover_1280x720(
                    ff, f, cancel=evt,
                    register=lambda p: self._register_proc(task_id, p))

            hooks = JobHooks(
                run=_GuiJobRunner(self, task_id),
                cancel=evt,
                pause=pause_evt,
                log=log,
                progress=lambda p: self.app.q.put(("dl_progress", task_id, p)),
                register=lambda p: self._register_proc(task_id, p),
                extract=extract,
                detect_language=engine.ai_detect_language,
                make_cover=make_cover,
                write_info=engine.write_info_txt,
                normalize_srt=engine.normalize_rolling_srt,
            )
            spec = DownloadJob(
                url=url, folder=folder, meta=meta,
                info_json_path=source_info,
                format_id=fid, quality_label=quality_label,
                with_subs=with_subs, sub_langs=self.SUB_LANGS,
                lock_proxy=True,
            )
            result = run_download_job(spec, hooks)
            if result.cancelled:
                rc = self.RC_CANCELLED
            elif result.paused:
                rc = self.RC_PAUSED
            elif result.ok:
                rc = 0
            else:
                rc = 1
            self.app.q.put(("dl_done", task_id, rc, result.folder or folder,
                            run_id, result.resume_info))
        except Exception as e:  # noqa: BLE001
            self.app.q.put(("dl_done", task_id, 1, f"出错: {e}", run_id, ""))
        finally:
            if info_json_path and info_json_path != source_info:
                try:
                    os.remove(info_json_path)
                except OSError:
                    pass

    def _download_worker(self, task_id, url, fid, folder, with_subs=False,
                         info_json_path=None, meta=None, quality_label="",
                         run_id=0, resume_info=""):
        from core.download.job import download_orchestrator
        if download_orchestrator(default="job") == "job":
            return self._download_worker_job(
                task_id, url, fid, folder, with_subs,
                info_json_path, meta, quality_label, run_id, resume_info)
        try:
            # 先解析代理通道（内置内核模式会在此拉起内置 mihomo），再锁出口——
            # 顺序反了锁定会跑在内核就绪之前，必然失败。
            proxy_args = engine.ytdlp_proxy_args()
            if proxy_args:
                self.app.q.put(("dl_log", task_id,
                                f"[代理] 下载经本地代理 {proxy_args[1]}"))
            # 下载期间钉住出口节点：直链在签发时绑定了当时的出口 IP，
            # 中途换节点会让所有已签发分片瞬间失效（EOF/_ssl.c:1007）。
            # 多任务并行时内部有引用计数，只有首个任务真正切换、末个任务恢复。
            locked = engine.proxy_lock_acquire()
            if locked:
                self.app.q.put(("dl_log", task_id,
                                f"[代理] 已锁定出口节点 {locked}"
                                "（避免下载中途换 IP 导致分片失效）"))
            note_download_dir_owner(
                os.path.dirname(folder),
                log=lambda m, lvl="dim": self.app.q.put(("dl_log", task_id, m, lvl)))
            ytdlp = engine.ensure_ytdlp()
            # v1.19.1：引导阶段（首次运行要下 ~170MB ffmpeg）也能被取消。
            # 原先这里连取消标志都不看，用户点了取消还得干等整个下载。
            if self._is_cancelled(task_id):
                raise _CancelledEarly()
            ffmpeg_path, _ = engine.ensure_ffmpeg()
            if self._is_cancelled(task_id):
                raise _CancelledEarly()
            # 代理：YouTube 等站点在国内必须经代理才能下载（B 站等本来直连的
            # 站点，代理的 rules 里是 DIRECT，没有副作用）。拿不到代理就直连。
            # （proxy_args 已在函数开头解析——内置内核模式需先于锁定就绪。）
            # 源选择：YouTube 直链（videoplayback）单条服务能力有限——约 5 次
            # 请求 / 数十 MB 即失效回 403，大文件几乎必然失败；实测直链要先白等
            # 十几分钟才切到 HLS（用户看到的"下载过慢"）。HLS 每片独立取、还能
            # 并发（-N），稳定性与速度都更好 → **直接首选 HLS**，直链降级为兜底。
            # 设 VT_YTDLP_PREFER_HLS=0 可退回旧的"直链优先"行为。
            alt = engine.hls_alt_format(meta, fid)
            prefer = bool(alt) and engine.ytdlp_prefer_hls()
            use_fid = alt if prefer else fid
            if prefer:
                self.app.q.put(("dl_log", task_id,
                                f"[策略] 直链单条服务能力有限（数十 MB 即失效），"
                                f"改用 HLS 分片源 {alt}（分片并发 "
                                f"{engine.ytdlp_concurrent_fragments()}）"))
            # --http-chunk-size 是必须的：YouTube 自 2026-09 起对 videoplayback
            # 直链强制要求 Range 请求，yt-dlp 默认的整体 GET 一律 403 ——
            # 表现为"下载几秒/几十 MB 后失败"，看着像风控其实是缺 Range。
            # 分片后每个请求都带 Range，才能正常取到数据。
            opts = ["-f", f"{use_fid}+ba/b", "--merge-output-format", "mp4",
                    "--ffmpeg-location", os.path.dirname(ffmpeg_path),
                    "--newline", "--no-playlist",
                    "--http-chunk-size", self.DL_CHUNK_SIZE,
                    *engine.ytdlp_dl_args(),
                    # 直播特化（须跟在 ytdlp_dl_args 之后：-N 取最后出现值）
                    *ytdlp_live_args(meta),
                    "--write-thumbnail", "--convert-thumbnails", "jpg",
                    *proxy_args,
                    *engine.ytdlp_cookie_args(),
                    "-o", engine.output_template(folder)]
            if ytdlp_is_live(meta):
                self.app.q.put(("dl_log", task_id,
                                "[直播] 直播录制中：从 DVR 头追赶（可快于实时），"
                                "百分比/速度仅供参考，以分片计数为准"))
            rc = 1
            if not self._is_cancelled(task_id):
                if info_json_path and os.path.isfile(info_json_path):
                    rc, _ = self._run_ytdlp(
                        [ytdlp, "--load-info-json", info_json_path, *opts], task_id)
            if rc != 0 and not self._is_cancelled(task_id):
                self.app.q.put(("sys_log", f"[任务 {task_id}] 复用检测结果下载失败"
                                          "（多为 CDN 链接过期），改用链接重新提取"))
                self.app.q.put(("dl_progress", task_id, 0.0))
                rc = self._fallback_download(task_id, ytdlp, url, opts)
            if rc == self.RC_REEXTRACT and not self._is_cancelled(task_id):
                # v1.19.2：EOF/TLS 断连 = 链接作废，重新提取是唯一有效动作。
                # 但可能反复失效（节点一直在换、IP 反复被判风控）→ 给有限次数；
                # **耗尽后必须转成普通失败**，让下面的换源 / NPE 兜底继续接手。
                # （自检发现：此前直接把 RC_REEXTRACT 一路带到底，两个兜底的
                # 判定条件都含 `rc != RC_REEXTRACT`，于是全部被跳过、直接判负。）
                reext = 0
                while rc == self.RC_REEXTRACT and not self._is_cancelled(task_id):
                    reext += 1
                    if reext > self.REEXTRACT_MAX:
                        self.app.q.put(("sys_log",
                                        f"[任务 {task_id}] 已连续重新提取 "
                                        f"{self.REEXTRACT_MAX} 次仍未成功，"
                                        "改用其它下载源继续尝试"))
                        rc = 1
                        break
                    self.app.q.put(("sys_log",
                                    f"[任务 {task_id}] 下载链接已失效，重新提取新链接"
                                    f"（第 {reext}/{self.REEXTRACT_MAX} 次）"))
                    self.app.q.put(("dl_progress", task_id, 0.0))
                    rc = self._fallback_download(task_id, ytdlp, url, opts)
            if rc != 0 and not self._is_cancelled(task_id):
                # 换另一个源兜底：HLS 优先时退回直链，直链优先时改走 HLS。
                # （直链被限 403/中途断流时，HLS 每片独立请求，实测能下完 1080p）
                other = fid if prefer else alt
                if other:
                    rc = self._hls_fallback(task_id, ytdlp, url, opts, other,
                                            hls=bool(alt) and other == alt)
            if rc != 0 and not self._is_cancelled(task_id) \
                    and engine.npe_engine_mode() != "off":
                # 第二引擎兜底（2026-10-08 接入）：yt-dlp 的直链/HLS 全失败后，
                # 改用 NewPipe Extractor 重新解析并下载。实测同一网络、同一份
                # cookie 下 yt-dlp 报 "Sign in to confirm you're not a bot" 而
                # NPE 能拿到流，两个引擎确有互补性。
                rc = self._npe_fallback(task_id, url, folder, meta, quality_label)
            if self._is_cancelled(task_id):
                # v1.19.0：用户取消优先于一切——即使某一步刚好返回 0 也不打包。
                rc = self.RC_CANCELLED
            if rc == 0:
                leftovers = engine.ytdlp_part_leftovers(folder)
                if leftovers:
                    # rc==0 但仍有分片残留 = yt-dlp 重试耗尽后跳过了不可用
                    # 分片（返回码仍为 0）——告警"成品可能缺秒"再清残骸。
                    self.app.q.put((
                        "dl_log", task_id,
                        f"[警告] 检测到 {len(leftovers)} 个分片残留（已清理）："
                        f"{os.path.basename(leftovers[0])} 等 —— 成品可能缺对应"
                        "分片的几秒内容，如画面有跳变请重新下载", "err"))
                    for _p in leftovers:
                        try:
                            os.remove(_p)
                        except OSError:
                            pass
                # yt-dlp 合并后没删掉的单轨源文件（xxx.f270.mp4 / xxx.temp.mp4）：
                # 只在成品存在且体积不异常时清，避免误删仍在用的源轨。
                _final = _dl_finished_video(folder)
                if _final:
                    try:
                        _final_size = os.path.getsize(_final)
                    except OSError:
                        _final_size = 0
                    _removed_tracks = 0
                    for _p in _dl_track_leftovers(folder, _final):
                        try:
                            if _final_size and os.path.getsize(_p) <= _final_size * 1.2:
                                os.remove(_p)
                                _removed_tracks += 1
                        except OSError:
                            pass
                    if _removed_tracks:
                        self.app.q.put(("dl_log", task_id,
                                        f"[清理] 已删除 {_removed_tracks} "
                                        "个 yt-dlp 单轨残留"))
                self._pack_task(task_id, ffmpeg_path, folder, meta, quality_label)
                if with_subs and not self._is_cancelled(task_id):
                    self._fetch_subtitles(task_id, ytdlp, url, folder,
                                          info_json_path, meta=meta)
                if self._is_cancelled(task_id):
                    # 打包/字幕阶段被 Cancel：同样按取消收尾（成品若已写完会保留）。
                    rc = self.RC_CANCELLED
            elif rc == self.RC_CANCELLED:
                self._cleanup_cancelled(task_id, folder)
            self.app.q.put(("dl_done", task_id, rc, folder))
        except _CancelledEarly:
            # v1.19.1：引导阶段被取消，按取消收尾（清掉刚建的空目录）。
            self._cleanup_cancelled(task_id, folder)
            self.app.q.put(("dl_done", task_id, self.RC_CANCELLED, folder))
        except Exception as e:
            self.app.q.put(("dl_done", task_id, 1, f"出错: {e}"))
        finally:
            engine.proxy_lock_release()
            if info_json_path:
                try:
                    os.remove(info_json_path)
                except OSError:
                    pass

    def _fallback_download(self, task_id, ytdlp, url, opts):
        """复用检测结果失败时的兜底：重新提取后继续；提取阶段全局串行防风控。"""
        def slog(m):
            self.app.q.put(("sys_log", f"[任务 {task_id}] {m}"))

        if self._is_cancelled(task_id):  # v1.19.0：取消后不再进提取/重试
            return self.RC_CANCELLED

        fresh = self._fetch_info_for_task(
            task_id, ytdlp, url,
            lambda m: self.app.q.put(("sys_log", f"[任务 {task_id}] {m}")))
        if self._is_cancelled(task_id):
            return self.RC_CANCELLED
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
        # 锁只保护上方的元数据提取（fetch_info_json，短）；完整下载绝不能在
        # _EXTRACT_LOCK 内——此前把 _run_ytdlp_with_retry 整个包进锁，一个任务
        # 的几十分钟下载会让其余并行任务的兜底/字幕全部排队停摆。
        return self._run_ytdlp_with_retry([ytdlp, *opts, url], task_id)

    def _hls_fallback(self, task_id, ytdlp, url, opts, alt_fid, hls=True):
        """换**另一个源**再试一轮：直链失败 → 改 HLS；HLS 失败 → 退回直链。

        `hls=True` 表示 `alt_fid` 是 HLS 分片源：此时音轨仍可能是 https 直链、
        一样会被 403，需再补一轮 HLS 隐藏音轨 itag 233/234（它们 acodec 为空、
        不在常规音轨列表里，但实测能下且能合并）。换回直链时不需要这一轮。
        """
        def slog(m):
            self.app.q.put(("sys_log", f"[任务 {task_id}] {m}"))

        if self._is_cancelled(task_id):  # v1.19.0：取消后不再换源重试
            return self.RC_CANCELLED
        new_opts = list(opts)
        try:
            new_opts[new_opts.index("-f") + 1] = f"{alt_fid}+ba/b"
        except (ValueError, IndexError):
            new_opts += ["-f", f"{alt_fid}+ba/b"]
        selectors = [f"{alt_fid}+ba/b"]
        if hls:
            selectors.append(f"{alt_fid}+233/234/b")
        for sel in selectors:
            if self._is_cancelled(task_id):  # v1.19.0：换源循环里也响应取消
                return self.RC_CANCELLED
            opts_i = list(new_opts)
            try:
                opts_i[opts_i.index("-f") + 1] = sel
            except (ValueError, IndexError):
                opts_i += ["-f", sel]
            slog(f"改用备用{'HLS 分片源' if hls else '直链源'}（{sel}）重试 ...")
            fresh = self._fetch_info_for_task(task_id, ytdlp, url, slog)
            if self._is_cancelled(task_id):
                return self.RC_CANCELLED
            if fresh:
                tmp = engine.save_info_json(fresh)
                try:
                    rc, _ = self._run_ytdlp(
                        [ytdlp, "--load-info-json", tmp, *opts_i], task_id)
                finally:
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
                if rc == 0:
                    return 0
            # 下载段不进锁（理由同 _fallback_download）：fetch_info_json 上方
            # 已在锁内完成，yt-dlp 下载本身有风控重试兜底。
            rc = self._run_ytdlp_with_retry([ytdlp, *opts_i, url], task_id)
            if rc == 0:
                return 0
        return rc

    # ---------- 第二引擎：NewPipe Extractor 兜底（2026-10-08） ----------
    def _npe_fallback(self, task_id, url, folder, meta, quality_label):
        """yt-dlp 全部源失败后，用 NewPipe Extractor 重新解析并下载。

        返回 0/1。这里只做「取参数 + 转发消息」，下载逻辑全在
        `npe_backend.download()`（纯 Python，可脱离 GUI 单独测试）。
        任何异常都收敛成日志 + 1，绝不让兜底本身把任务弄崩。
        """
        def log(m, level="dim"):
            self.app.q.put(("dl_log", task_id, m, level))

        def prog(pct):
            self.app.q.put(("dl_progress", task_id, pct))

        try:
            import features.download.npe_backend as npe_backend
        except Exception as e:  # noqa: BLE001
            log(f"[NPE] 模块导入失败：{e}", "err")
            return 1

        ok, why = npe_backend.is_available()
        if not ok:
            log(f"[NPE] 不可用：{why}", "err")
            return 1

        proxy = engine.npe_proxy_url()
        cookie_file = engine.npe_cookie_file(log=lambda m: log(m))
        log("[NPE] yt-dlp 各源均失败，改用 NewPipe Extractor 兜底解析 ...")
        evt = self._cancel_events.get(task_id)
        info = npe_backend.probe(
            url, proxy=proxy, cookie_file=cookie_file,
            cancel=evt, register=lambda p: self._register_proc(task_id, p))
        if self._is_cancelled(task_id) or info.get("errorType") == "cancelled":
            log("[NPE] 已取消")
            return self.RC_CANCELLED
        if not info.get("ok"):
            log(f"[NPE] 解析失败：{npe_backend.error_hint(info)}", "err")
            return 1

        # 画质对齐：尽量贴合用户已选的那一档
        target = 0
        m = re.search(r"(\d{3,4})\s*p", str(quality_label or ""))
        if m:
            target = int(m.group(1))
        log("[NPE] 已解析：%s" % (info.get("title") or ""))

        ffmpeg_path, _ = engine.ensure_ffmpeg()
        ok2, out_path, err = npe_backend.download(
            info, folder, ffmpeg_path, proxy=proxy,
            referer="https://www.youtube.com/", max_height=target,
            log=log, progress=prog,
            cancel=self._cancel_events.get(task_id),  # v1.19.0：取消即停 ffmpeg
            sanitize=lambda t: engine.sanitize_folder_name(t, "video"),
            title_fallback=str((meta or {}).get("title") or "video"))
        if not ok2:
            if self._is_cancelled(task_id) or err == "已取消":
                log("[NPE] 已取消")
                return self.RC_CANCELLED
            log(f"[NPE] 兜底下载失败：{err}", "err")
            return 1
        log("[NPE] 兜底下载成功：%s（%s）" % (
            os.path.basename(out_path),
            engine.format_size(os.path.getsize(out_path))), "ok")
        return 0

    @staticmethod
    def _srt_state(folder, before=None):
        """目录里 .srt 的 {路径: (mtime_ns, 大小)} 快照。

        给了 `before` 就只返回**新增或刚被改写**的那些 —— 拉字幕前后各取一次，
        就能准确知道"这一轮到底拿到了哪几份"，不用猜文件名。
        """
        now = {}
        try:
            names = os.listdir(folder)
        except OSError:
            return {} if before is None else []
        for name in names:
            if not name.lower().endswith(".srt"):
                continue
            p = os.path.join(folder, name)
            try:
                st = os.stat(p)
            except OSError:
                continue
            now[p] = (st.st_mtime_ns, st.st_size)
        if before is None:
            return now
        return sorted(p for p, sig in now.items() if before.get(p) != sig)

    def _fetch_subtitles_once(self, task_id, ytdlp, url, folder,
                              info_json_path, sub_langs, proxy_args):
        """跑一轮字幕拉取；返回 yt-dlp 的返回码（0 只代表"命令没报错"）。"""
        opts = ["--skip-download", "--newline", "--no-playlist",
                "--socket-timeout", "15", "--retries", "3",
                "--write-subs", "--write-auto-subs", "--sub-langs", sub_langs,
                "--sub-format", "srt/best", "--convert-subs", "srt",
                *proxy_args,
                *engine.ytdlp_cookie_args(),
                "-o", engine.output_template(folder)]
        if info_json_path and os.path.isfile(info_json_path):
            rc, _ = self._run_ytdlp(
                [ytdlp, "--load-info-json", info_json_path, *opts], task_id)
            if rc == 0:
                return 0
        # ⚠️ 这里必须走带 412 重试的版本：字幕请求比视频请求更容易撞上站点风控，
        #    此前只跑一次 `_run_ytdlp`，一次 412 就白等（用户看到的"字幕下载失败"）。
        #    字幕下载不进 _EXTRACT_LOCK（理由同 _fallback_download 的下载段）。
        return self._run_ytdlp_with_retry([ytdlp, *opts, url], task_id)

    def _fetch_subtitles(self, task_id, ytdlp, url, folder, info_json_path, meta=None):
        """视频下载完成后单独拉字幕；失败只写日志，不影响任务成功状态。

        v1.13.7 三处加固：
          · 全程带代理（此前 yt-dlp 直连，YouTube 字幕根本拉不下来）；
          · AI 语言识别猜错 / 首轮空手时，改用多语言列表补拉一轮；
          · 拉到的每份字幕都做「去重叠」整理（平台自动字幕是滚动式，
            条条互相压住，见 engine.normalize_rolling_srt）。
        """
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

        proxy_args = engine.ytdlp_proxy_args()
        before = self._srt_state(folder)
        self._fetch_subtitles_once(task_id, ytdlp, url, folder,
                                   info_json_path, sub_langs, proxy_args)
        fresh = self._srt_state(folder, before)
        if not fresh and sub_langs != self.SUB_LANGS:
            # 首轮空手：多半是"标题语言"猜错了（比如英文字幕挂在 ja 上）。
            # 换成覆盖最广的多语言列表再试一次，这是唯一能纠正它的机会。
            self.app.q.put(("dl_log", task_id,
                            "[字幕] 首轮没取到字幕，改用多语言列表补拉一次"))
            self._fetch_subtitles_once(task_id, ytdlp, url, folder,
                                       info_json_path, self.SUB_LANGS, proxy_args)
            fresh = self._srt_state(folder, before)

        fixed = 0
        for p in fresh:
            try:
                if engine.normalize_rolling_srt(p):
                    fixed += 1
            except Exception as e:  # noqa: BLE001
                self.app.q.put(("sys_log",
                                f"[字幕] 整理 {os.path.basename(p)} 失败：{e}"))
        if fresh:
            extra = f"，其中 {fixed} 份做了去重叠整理" if fixed else ""
            self.app.q.put(("dl_log", task_id,
                            f"[字幕] 已下载 {len(fresh)} 份字幕（.srt）{extra}，"
                            "已存入该视频文件夹"))
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
        # v1.19.1：封面生成同样可取消（原先 subprocess.run 跑满 60s 超时，
        # 取消后还要白等；且 ffmpeg 收尾阶段没登记进程，按钮杀不掉）。
        evt = self._cancel_events.get(task_id)
        made = engine.make_cover_1280x720(
            ffmpeg_path, folder, cancel=evt,
            register=lambda p: self._register_proc(task_id, p))
        if made:
            self.app.q.put(("dl_log", task_id, "[打包] 封面.jpg（1280x720）已生成"))
        elif self._is_cancelled(task_id):
            self.app.q.put(("dl_log", task_id, "[打包] 已取消，跳过封面", "err"))
        else:
            self.app.q.put(("dl_log", task_id, "[打包] 该视频无可用封面，已跳过封面步骤"))

    @staticmethod
    def _eof_mark(line):
        """行内命中 EOF 特征时返回归一化标记（用于去重），否则空串。"""
        if not line:
            return ""
        for mk in DownloadPage._EOF_MARKS:
            if mk in line:
                # 归一到 "eof" 一族：不同行文本（Retrying 1/10 vs 10/10）不重复报
                return "eof"
        return ""

    @staticmethod
    def _eof_is_fatal(line, frag_context=False):
        """EOF 是否属于「整条链接作废」（而非单片失效）——决定要不要主动结束。

        yt-dlp 的 EOF 有几种形态，只有**直链**场景才值得主动杀进程：
          · 直链：``unable to download video data: Got error: EOF...``
            整条 videoplayback 失效，它自己的 ``--retries`` 重试的是同一条
            死链，纯属白等 → **应该主动结束**，交给上层重新提取；
          · 分片：``[hlsnative] Downloading fragment 42/500: Got error: EOF...``
            交给 ``--fragment-retries`` 逐片重下更有效（只重那一片，已下完的
            分片进度不丢）→ **不该杀**，杀了反而丢掉已有进度。
          · 缩略图/字幕等辅助资源：``WARNING: Unable to download video
            thumbnail 43: EOF...`` —— 不影响正片 → **不该杀**
            （2026-11-21 实录：T12 直播出生即被一条缩略图 EOF 误杀，
            进度清零重爬，形成「下载→杀→重提取」死循环）。

        ``frag_context``：读流循环按**实际出现过分片行**累积的上下文。
        分片下载的错误行自身常不带 fragment 关键词（只有裸 ``Got error:
        EOF... Retrying``），单看错误行会把直播/HLS 误判成直链——必须靠
        上下文区分。分片上下文里一律不杀（含直播）。
        """
        low = (line or "").lower()
        if any(k in low for k in ("thumbnail", "subtitle", "annotation")):
            return False
        if frag_context or any(k in low for k in
                               ("fragment", "hlsnative", "m3u8", "frag", "dash")):
            return False
        return True

    def _run_ytdlp(self, cmd, task_id, phase="download"):
        try:
            # 按字节读取、逐行智能解码（兼容 yt-dlp 输出 UTF-8/GBK；CJK 多字节
            # 不会跨越 0x0A 换行，故按行解码不会切断字符）
            proc = engine.popen_process(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        bufsize=1)
        except Exception as e:
            self.app.q.put(("dl_log", task_id, f"[错误] 无法启动下载器: {e}"))
            return 1, []
        # v1.19.0：登记当前子进程——取消按钮据此直接 kill；同一任务先后启动的
        # 多个进程（主源/兜底/字幕）只会登记最后一个，旧的早已 wait 完毕。
        self._procs[task_id] = proc
        # 环形缓冲：只留尾部（见 DL_LINES_KEEP 注释）。多任务并行 × 长视频时
        # 全量累积会让 GUI 进程内存持续上涨且不回落。
        lines = deque(maxlen=self.DL_LINES_KEEP)
        pct_re = re.compile(r"\[download\]\s+([\d.]+)%")
        frag_re = re.compile(r"\[download\]\s+Downloading fragment (\d+)/(\d+)")
        speed_re = re.compile(r"at\s+([\d.]+)\s*([KMGT]?i?B)/s")
        eta_re = re.compile(r"ETA\s+(\d+):(\d+)")
        # 分片上下文：出现过真实分片行即置位（HLS/DASH 分片源、直播）。
        # EOF 错误行自身常不带 fragment 关键词，靠它区分「直链作废该杀」
        # 与「分片抖动不该杀」（见 _eof_is_fatal）。
        saw_frag = False
        run_id = self._run_ids.get(task_id, 0)
        units = {"B": 1, "KiB": 1024, "MiB": 1024 ** 2, "GiB": 1024 ** 3, "TiB": 1024 ** 4}
        try:
            for raw in proc.stdout:
                if (phase == "download" and self._pause_events.get(task_id) is not None
                        and self._pause_events[task_id].is_set() and proc.poll() is None):
                    try:
                        proc.kill()
                    except Exception:  # noqa: BLE001
                        pass
                    break
                if self._is_cancelled(task_id) and proc.poll() is None:
                    # 取消路径之一（另一路是 cancel_selected_task 直接 kill）：
                    # 读流循环里发现取消标志就主动杀，避免卡在慢速连接上。
                    try:
                        proc.kill()
                    except Exception:  # noqa: BLE001
                        pass
                    break
                line = engine.decode_bytes_any(raw).rstrip()
                lines.append(line)
                if not saw_frag and ("fragment" in line or "hlsnative" in line):
                    saw_frag = True
                m = pct_re.search(line)
                if m:
                    speed, eta = 0.0, -1.0
                    sm = speed_re.search(line)
                    if sm:
                        try:
                            speed = float(sm.group(1)) * units.get(sm.group(2), 1)
                        except ValueError:
                            speed = 0.0
                    em = eta_re.search(line)
                    if em:
                        try:
                            eta = int(em.group(1)) * 60 + int(em.group(2))
                        except ValueError:
                            eta = -1.0
                    self.app.q.put(("dl_progress", task_id, float(m.group(1)),
                                    run_id, speed, eta))
                    continue
                m = frag_re.search(line)
                if m:
                    # HLS 分片行是大文件（直播存档可达数千片）日志洪流的主要来源，
                    # 每片一行会把主线程日志控件塞死——每 100 片折叠一条汇总；
                    # 内存 lines 仍保留全量供排障。
                    n, total = int(m.group(1)), int(m.group(2))
                    if n == total or n % 100 == 0:
                        self.app.q.put(("dl_log", task_id, f"[分片] 已下载 {n}/{total}"))
                    continue
                if line and "Deprecated" not in line:
                    # WARNING 透出：跳片（fragment not found / missing）之类警告
                    # 一旦被过滤，"静默缺片"就完全不可见。
                    self.app.q.put(("dl_log", task_id, line))
                m2 = self._eof_mark(line)
                if m2:
                    # 2026-10-17：EOF/TLS 断连是**链接作废**，不是抖动。
                    # 用户原来只看到 "Retrying (1/10)…(10/10)" 然后任务失败，
                    # 完全不知道为什么。这里用 proxy_note_eof() 判明根因
                    # （出口 IP 变了？节点没锁？还是纯线路抖动），
                    # 并直接告诉用户接下来会重新提取 —— 同一错误只报一次。
                    if DownloadPage._EOF_HINTED.get(task_id) != m2:
                        DownloadPage._EOF_HINTED[task_id] = m2
                        # 异步核查：proxy_note_eof 内的出口 IP 探测最坏 2.5s，
                        # 原先在读流循环里同步跑会拖住 stdout 读取，管道积压
                        # 反过来卡住 yt-dlp 输出（2026-11-21 诊断 P2）。
                        # 派后台线程，先占位提示、探完经事件队列补发结论。
                        self.app.q.put(("dl_log", task_id,
                                        "[代理] 检测到 TLS 断连（EOF），"
                                        "正在后台核查出口 IP…", "err"))

                        def _note_eof(line=line, tid=task_id):
                            try:
                                msg = engine.proxy_note_eof(line)
                            except Exception as e:  # noqa: BLE001
                                msg = "[代理] EOF 根因核查失败：%s" % e
                            self.app.q.put(("dl_log", tid, msg, "err"))

                        threading.Thread(target=_note_eof, daemon=True,
                                         name="eof-note-%s" % task_id).start()
                    # 整链作废（直链场景）时主动结束：yt-dlp 会拿同一条死链
                    # 重试 --retries 次、每次还要退避最多 20s，白等数分钟；
                    # 杀掉进程让上层立刻走「重新提取」，拿到绑定新 IP 的新链接。
                    # 分片/直播场景不杀（fragment-retries 逐片重下更有效，且不丢
                    # 进度）；缩略图等辅助资源失败也不杀（见 _eof_is_fatal）。
                    if self._eof_is_fatal(line, frag_context=saw_frag):
                        n = DownloadPage._EOF_KILLS.get(task_id, 0)
                        if n < self.EOF_REEXTRACT_MAX:
                            DownloadPage._EOF_KILLS[task_id] = n + 1
                            self.app.q.put((
                                "dl_log", task_id,
                                "[策略] 下载链接已失效（出口 IP 已变更），原地重试无效"
                                " —— 主动结束并重新提取新链接"
                                f"（第 {n + 1}/{self.EOF_REEXTRACT_MAX} 次）", "err"))
                            engine.kill_process_tree(proc)
                            break
            return proc.wait(), lines
        finally:
            self._procs.pop(task_id, None)

    def _run_ytdlp_with_retry(self, cmd, task_id, attempts=4):
        """带风控重试：判定复用引擎 `ytdlp_error_retryable`（三处同一口径）。

        v1.19.2：新增 EOF/TLS 断连的**短路**。这类失败说明已签发的链接本身
        作废（videoplayback 直链绑定了签发时的出口 IP，代理一换节点 CDN 就
        掐连接），原地重试是纯浪费。判定成立就直接返回 ``RC_REEXTRACT``，
        由上层拿去重新提取新链接，不再等 6→12→24s 的退避。
        """
        wait = 6
        rc, lines = 1, deque(maxlen=self.DL_LINES_KEEP)
        for i in range(attempts):
            if self._is_cancelled(task_id):
                # v1.19.0：取消后立即退出重试，不再白等退避。
                return self.RC_CANCELLED
            rc, lines = self._run_ytdlp(cmd, task_id)
            if rc == 0:
                return 0
            if self._is_cancelled(task_id):
                return self.RC_CANCELLED
            joined = "\n".join(lines)
            # 直播 --live-from-start 不被该源支持时：剥旗标立即重试一次，
            # 退回直播边缘跟随（不消耗重新提取配额）。
            if "--live-from-start" in cmd and ytdlp_live_flag_unsupported(joined):
                self.app.q.put(("dl_log", task_id,
                                "[直播] 该源不支持 --live-from-start，"
                                "退回直播边缘跟随重试"))
                cmd = [c for c in cmd if c != "--live-from-start"]
                continue
            # v1.19.2：直链失效优先于风控重试——它重试同一条 URL 100% 失败。
            if engine.ytdlp_error_needs_reextract(joined):
                self.app.q.put(("sys_log",
                                f"[任务 {task_id}] 下载链接已失效"
                                f"（{engine.ytdlp_err_brief(joined)}）"
                                "，正在重新提取新链接…"))
                return self.RC_REEXTRACT
            # 412/403/429、"Sign in" 等一律可重试：YouTube 直链失效或节点
            # IP 被判风控都会回 403，换一次提取（新直链）往往就过了；
            # 只有参数类错误才直接放弃。
            if not engine.ytdlp_error_retryable(joined):
                return rc
            if i < attempts - 1:
                self.app.q.put(("sys_log",
                                f"[任务 {task_id}] 站点风控或直链失效"
                                f"（{engine.ytdlp_err_brief(joined)}），"
                                f"{wait}s 后重试 ({i + 2}/{attempts}) ..."))
                # 退避等待改为可取消的短睡眠：取消一到立即返回，不等完整个
                # 指数退避。封顶 30s（2026-11-21 诊断 P2：6→12→24→48s 堆叠
                # 重提取循环，一次抖动空转数分钟）。
                for _ in range(wait * 2):
                    if self._is_cancelled(task_id):
                        return self.RC_CANCELLED
                    time.sleep(0.5)
                wait = min(wait * 2, 30)
        return rc

    # ---------- 主线程更新 ----------
    def on_dl_progress(self, task_id, pct, run_id=0, speed=0.0, eta=-1.0):
        if self._queue_mode and self.dl_queue is not None:
            rid = run_id or self._run_ids.get(task_id, 0)
            self.dl_queue.progress(task_id, rid, pct, speed, eta)
            return
        item = self.tasks.get(task_id)
        if not item:
            return
        # v1.19.1：取消/收尾后到达的**迟到进度消息**必须丢弃。原实现无条件
        # 把状态写回「下载中」，队列里积压的几条进度会把刚点完取消的界面
        # 顶回「下载中 / 正在增长」——用户判定「中止没生效」的直接原因。
        if item["status"] in ("取消中", "已取消", "完成", "失败"):
            return
        item["pct"] = pct
        self._set_cell(task_id, 3, f"{pct:.1f}%")
        self._set_cell(task_id, 4, engine.format_size(speed) + "/s" if speed else "—")
        self._set_cell(task_id, 5, engine.format_time(eta) if eta and eta > 0 else "—")
        self._set_cell(task_id, 6, "下载中")
        if task_id == self.active_task:
            self.prog.setValue(int(pct))
            self.pct_label.setText(f"{pct:.1f}%")
        n = self.active_count()
        if n:
            self.pct_label.setToolTip(f"并行下载中：{n} 个任务")

    def on_dl_log(self, task_id, text, level="dim", run_id=0):
        # v1.19.1：已取消/已收尾的任务不再继续刷屏（子进程被杀前吐的最后几行）。
        item = self.tasks.get(task_id)
        if self._queue_mode:
            if item is None or item.get("status") in ("已取消", "完成", "失败", "已暂停"):
                return
            if run_id and run_id != self._run_ids.get(task_id, 0):
                return
            self.log.line(f"[任务 {task_id}] {text}", level)
            return
        if item and item["status"] in ("已取消", "完成", "失败"):
            return
        self.log.line(f"[任务 {task_id}] {text}", level)

    def on_dl_done(self, task_id, rc, folder, run_id=0, resume_info=""):
        if self._queue_mode and self.dl_queue is not None:
            item = self.tasks.get(task_id)
            if item is not None and resume_info:
                item["resume_info"] = resume_info
            self.dl_queue.worker_stopped(
                task_id, run_id or self._run_ids.get(task_id, 0),
                completed=(rc == 0),
                paused=(rc == self.RC_PAUSED),
                cancelled=(rc == self.RC_CANCELLED),
                error="" if rc == 0 else "下载失败",
            )
            return
        DownloadPage._EOF_HINTED.pop(task_id, None)   # 回收 EOF 去重标记
        DownloadPage._EOF_KILLS.pop(task_id, None)   # 回收 EOF 主动结束计数
        self._cancel_events.pop(task_id, None)  # v1.19.0：回收取消标志
        self._procs.pop(task_id, None)
        item = self.tasks.get(task_id)
        if rc == self.RC_CANCELLED:  # v1.19.0：用户主动取消
            if item:
                item["status"] = "已取消"
            self._set_cell(task_id, 3, "—")
            self._set_cell(task_id, 6, "已取消")
            if task_id == self.active_task:
                self.pct_label.setText("已取消")
                self.cancel_btn.setEnabled(False)
            self.log.line(f"[任务 {task_id}] [已取消] 未完成的部分已清理，"
                          "可重新加入下载", "err")
            return
        if item:
            item["pct"] = 100.0 if rc == 0 else item["pct"]
            item["status"] = "完成" if rc == 0 else "失败"
        self._set_cell(task_id, 3, "100%" if rc == 0 else "—")
        self._set_cell(task_id, 6, "完成" if rc == 0 else "失败")
        if rc == 0:
            self._set_cell(task_id, 7, folder)
        if task_id == self.active_task:
            if rc == 0:
                self.prog.setValue(100)
            self.pct_label.setText("完成" if rc == 0 else "失败")
            self.cancel_btn.setEnabled(False)  # v1.19.0：任务已结束，取消按钮复位
        if rc == 0:
            self.log.line(f"[任务 {task_id}] [完成] 已打包到独立文件夹: {folder}", "ok")
            if item and item.get("with_subs"):
                self.log.line(f"[任务 {task_id}] 字幕（.srt，若有）已存入该视频文件夹", "dim")
            # 并行完成风暴去重：视频库刷新 = 全目录重扫 + 每个媒体文件起一个
            # ffprobe 进程（刚写完的几 GB 大文件单次可达数秒），每个任务完成
            # 各刷一次会连跑 N 轮——推迟到全部任务结束后统一刷一次。
            if self.active_count() == 0:
                root_dir = (item or {}).get("dest") or os.path.dirname(folder)
                self.app.library_page.set_dir(root_dir)
                self.app.library_page.refresh()
                if task_id == self.active_task:
                    engine.open_folder(folder)
        else:
            self.log.line(f"[任务 {task_id}] [错误] 下载失败，请查看上方日志"
                          "（多为站点风控或网络问题）", "err")

    def shutdown(self):
        if self.dl_queue is not None:
            for tid in list(self.tasks):
                evt = self._cancel_events.get(tid)
                if evt is not None:
                    evt.set()
                proc = self._procs.get(tid)
                if proc is not None:
                    try:
                        engine.kill_process_tree(proc)
                    except Exception:
                        pass
            try:
                self.dl_queue.cancel_all()
            except Exception:
                pass

    def active_count(self):
        if self._queue_mode and self.dl_queue is not None:
            return self.dl_queue.active_count()
        return sum(1 for item in self.tasks.values()
                   if item["status"] in ("下载中", "取消中"))

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


def build_page(app, parent=None):
    """注册表 GuiSpec.builder 入口（download 功能页 / 视频处理容器）。"""
    return DownloadPage(app, parent)