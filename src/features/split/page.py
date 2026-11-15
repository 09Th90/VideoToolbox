# -*- coding: utf-8 -*-
"""视频切片页（2026-11-15 功能解耦阶段③：从 video_toolbox_qt.py 拆出，逐字同源）。

解耦样板页：
* 只经 vt_app 基建（TabPage/card/LogView/拖放槽）+ 本功能后端 video_split；
* 消息自订阅（bus「sp_」前缀），不再依赖入口 _dispatch 路由表；
* 容器页（视频处理）经注册表服务 ``split.build_page`` 组装本板块，
  split 功能缺失时该板块自动缺席，不影响下载/合并。
"""
import os
import threading

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QHeaderView,
                               QTableWidgetItem)

from vt_fluent import (ComboBox, FluentIcon as FIF, InfoBar, InfoBarPosition,
                       LineEdit, PrimaryPushButton, ProgressBar, PushButton,
                       TableWidget, TextEdit)

import video_toolbox as engine
import features.split.video_split as vsplit

from vt_app.widgets import (LogView, TabPage, _MergeDropSlot, card,
                            label_row, row, srow, tab_caption)
from features._media import VIDEO_EXTS, VIDEO_FILE_FILTER


class SplitPage(TabPage):
    """视频切片：按「时间点」或「时长」把一条视频拆成多段。

    · 两种输入语法（程序自动识别，同一份输入里不许混用）：
        - 时间点 `00:00:00, 01:00:00, 02:00:00`（HH:MM:SS；也接受 MM:SS）
        - 时长   `1h, 1h` / `1h30m` / `90m` / `45s`（也接受 时/分/秒）
    · 「解析预览」先出段表（序号 / 起点 / 终点 / 时长），确认后再真切；
    · 三种模式：无损快切（copy，秒级）/ 自动（快切校验不过就重编码）/ 精确重编码；
    · 每段产出都过「有视频流 + 时长对得上 + 片头片尾解码抽检」——保证拆出来的
      每个视频都能正常播放；不兼容 mp4 的源（vp8/opus 等）自动改 MKV 无损封装。

    线程模型与其它页一致：后台线程只往 app.q 投消息，主线程 bus 泵出刷新控件。
    """

    SPEC_MODES = {"自动识别（时间点 / 时长）": "auto",
                  "时间点（HH:MM:SS）": "points",
                  "时长（xHyMzS）": "durations"}
    RUN_MODES = {"无损快切（推荐，秒级完成）": "copy",
                 "自动（快切校验不过就重编码）": "auto",
                 "精确重编码（切点严格对齐，慢）": "encode"}

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setObjectName("SplitPage")
        self.busy = False
        self._plan = None
        self._cancel = None

        # 功能解耦阶段③：消息自订阅（sp_ 前缀）。泵语义不变（120ms/每轮 200 条），
        # 只是路由从入口 _dispatch 硬编码改为页面认领。
        app.bus.subscribe("sp_", self._on_bus_message)

        v = self.content_lay
        v.setSpacing(12)
        v.addWidget(tab_caption(
            "按时间点（HH:MM:SS）或时长（xHyMzS）拆成多段；默认无损快切，逐段校验可播", self))

        # —— 源视频 ——
        self.src_slot = _MergeDropSlot(
            "源视频（必填）", "拖入要切片的视频，或点击这里选择", VIDEO_EXTS,
            self.pick_video, self)
        box, lay = card("源视频", "mp4 / mkv / webm / mov 等；点槽位可重新选择")
        lay.addWidget(self.src_slot)
        v.addWidget(box)

        # —— 切片参数 ——
        self.kind_combo = ComboBox(self)
        self.kind_combo.addItems(list(self.SPEC_MODES))
        self.spec_edit = TextEdit(self)
        self.spec_edit.setPlaceholderText(
            "时间点：00:00:00, 01:00:00, 02:00:00\n"
            "或时长：1h, 1h（也支持 1h30m / 90m / 45s）")
        self.spec_edit.setMinimumHeight(84)
        self.spec_edit.setMaximumHeight(120)
        self.plan_btn = PushButton(FIF.SEARCH, "解析预览", self)
        self.plan_btn.clicked.connect(self.parse_preview)
        self.plan_table = TableWidget(self)
        self.plan_table.setBorderVisible(True)
        self.plan_table.setBorderRadius(8)
        self.plan_table.setWordWrap(False)
        self.plan_table.setColumnCount(4)
        self.plan_table.setHorizontalHeaderLabels(["序号", "起点", "终点", "时长"])
        self.plan_table.verticalHeader().hide()
        self.plan_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.plan_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        for i, w in enumerate((60, 130, 130, 130)):
            self.plan_table.setColumnWidth(i, w)
        self.plan_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.plan_table.setMinimumHeight(150)
        box, lay = card("切片参数", "同一份输入里别混用两种语法；每段最少 1 秒")
        lay.addWidget(label_row("输入方式", self.kind_combo))
        lay.addWidget(self.spec_edit)
        lay.addWidget(row(None, self.plan_btn))
        lay.addWidget(self.plan_table)
        v.addWidget(box)

        # —— 输出 ——
        self.out_edit = LineEdit(self)
        self.out_edit.setPlaceholderText("留空则输出到「视频所在文件夹\\切片」")
        out_browse = PushButton(FIF.FOLDER, "浏览…", self)
        out_browse.clicked.connect(self._pick_out)
        self.mode_combo = ComboBox(self)
        self.mode_combo.addItems(list(self.RUN_MODES))
        box, lay = card("输出", "无损快切切点会对齐到关键帧（相邻段可能差/重叠 ≤1 个 GOP）；"
                                "要严格对齐请选精确重编码")
        lay.addWidget(srow("输出文件夹", self.out_edit))
        lay.addWidget(out_browse, 0, Qt.AlignLeft)
        lay.addWidget(label_row("切分模式", self.mode_combo))
        v.addWidget(box)

        # —— 执行 ——
        self.prog = ProgressBar(self)
        self.cancel_btn = PushButton(FIF.CANCEL, "中止", self)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_split)
        self.start_btn = PrimaryPushButton(FIF.CUT, "开始切片", self)
        self.start_btn.clicked.connect(self.start_split)
        v.addWidget(row(self.prog, self.cancel_btn, self.start_btn))
        self.log = LogView("切片日志", 120, self)
        v.addWidget(self.log)
        v.addStretch(1)

    # ---------- 消息 ----------
    def _on_bus_message(self, msg):
        """bus「sp_」前缀消息（原入口 _dispatch 的 sp_* 分支，语义逐字一致）。"""
        kind, args = msg[0], msg[1:]
        if kind == "sp_log":
            self.log.line(args[0], args[1] if len(args) > 1 else "dim")
        elif kind == "sp_progress":
            self.prog.setValue(int(args[0]))
        elif kind == "sp_done":
            self.on_done(args[0])

    # ---------- 选择 ----------
    def pick_video(self):
        start = os.path.dirname(self.src_slot.path() or "") or engine.APP_DIR
        path, _ = QFileDialog.getOpenFileName(self, "选择要切片的视频", start,
                                              VIDEO_FILE_FILTER)
        if not path:
            return
        self.src_slot.set_path(engine.clean_path(path))
        self._plan = None
        self.plan_table.setRowCount(0)
        self.log.line("[选择] %s" % os.path.basename(path), "dim")

    def _pick_out(self):
        d = QFileDialog.getExistingDirectory(
            self, "选择输出文件夹", self.out_edit.text() or engine.APP_DIR)
        if d:
            self.out_edit.setText(engine.clean_path(d))

    # ---------- 解析 ----------
    def _build_plan(self):
        """探测源 + 解析输入 → (plan, info)。解析失败抛 vsplit.SplitError。"""
        src = self.src_slot.path()
        if not src or not os.path.isfile(src):
            raise vsplit.SplitError("请先选择要切片的视频")
        _, ffprobe_path = engine.ensure_ffmpeg()
        info = vsplit.probe_media(ffprobe_path, src)
        kind = self.SPEC_MODES.get(self.kind_combo.currentText(), "auto")
        plan = vsplit.plan_split(info["duration"], self.spec_edit.toPlainText(), kind)
        return plan, info

    def parse_preview(self):
        try:
            plan, info = self._build_plan()
        except vsplit.SplitError as e:
            self._plan = None
            self.plan_table.setRowCount(0)
            self.log.line("[X] %s" % e, "err")
            InfoBar.warning("解析失败", str(e), duration=4000,
                            position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        self._plan = plan
        self._render_plan(plan)
        self.log.line("[解析] 片长 %s（%s），%s → %d 段"
                      % (vsplit.hms(info["duration"]),
                         "%dx%d" % (info["width"], info["height"])
                         if info["width"] else info["vcodec"],
                         "时间点" if plan["kind"] == "points" else "时长",
                         len(plan["segments"])), "ok")
        for w in plan.get("warnings") or []:
            self.log.line("[信息] " + w, "dim")

    def _render_plan(self, plan):
        segs = plan["segments"]
        self.plan_table.setRowCount(len(segs))
        for r, s in enumerate(segs):
            for c, text in enumerate((str(s["index"]),
                                      vsplit.hms(s["start"], True),
                                      vsplit.hms(s["end"], True),
                                      vsplit.hms(s["dur"], True))):
                self.plan_table.setItem(r, c, QTableWidgetItem(text))

    # ---------- 执行 ----------
    def start_split(self):
        if self.busy:
            return
        try:
            plan, _info = self._build_plan()      # 每次开跑都重算，避免沿用改过输入的旧方案
        except vsplit.SplitError as e:
            self.log.line("[X] %s" % e, "err")
            InfoBar.warning("无法开始", str(e), duration=4000,
                            position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        src = self.src_slot.path()
        out_dir = (engine.clean_path(self.out_edit.text())
                   or os.path.join(os.path.dirname(src), "切片"))
        mode = self.RUN_MODES.get(self.mode_combo.currentText(), "copy")
        self._plan = plan
        self._render_plan(plan)
        self.busy = True
        self.start_btn.setEnabled(False)
        self.plan_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.prog.setValue(0)
        self._cancel = threading.Event()
        self.log.line("[开始] %s → %s（%d 段，%s）"
                      % (os.path.basename(src), out_dir, len(plan["segments"]),
                         self.mode_combo.currentText()), "dim")
        for w in plan.get("warnings") or []:
            self.log.line("[信息] " + w, "dim")
        threading.Thread(target=self._worker,
                         args=(src, plan["segments"], out_dir, mode),
                         daemon=True).start()

    def _worker(self, src, segments, out_dir, mode):
        try:
            ffmpeg_path, ffprobe_path = engine.ensure_ffmpeg()
            res = vsplit.split_video(src, segments, out_dir, mode=mode,
                                     ffmpeg=ffmpeg_path, ffprobe=ffprobe_path,
                                     on_event=self._on_event, cancel=self._cancel)
        except Exception as e:  # noqa: BLE001
            res = {"ok": False, "error": str(e)[:300], "outputs": [],
                   "failed": [], "out_dir": out_dir}
        self.app.q.put(("sp_done", res))

    def _on_event(self, kind, payload=None):
        """切片线程 → 主线程消息（只投递，不碰控件）。"""
        if kind == "log":
            text, level = (payload if isinstance(payload, tuple) else (payload, "dim"))
            self.app.q.put(("sp_log", text, level))
        elif kind == "progress":
            self.app.q.put(("sp_progress", float(payload or 0)))

    def cancel_split(self):
        if self._cancel is not None:
            self._cancel.set()
            self.log.line("[信息] 已请求中止，当前段结束后停止…", "dim")
            self.cancel_btn.setEnabled(False)

    def on_done(self, res):
        self.busy = False
        self._cancel = None
        self.start_btn.setEnabled(True)
        self.plan_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        res = res or {}
        if res.get("ok"):
            self.prog.setValue(100)
            self.log.line("[完成] %s" % vsplit.summarize(res), "ok")
            try:
                engine.open_folder(res.get("out_dir") or "")
            except Exception:  # noqa: BLE001
                pass
            InfoBar.success("切片完成", vsplit.summarize(res), duration=5000,
                            position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
        else:
            self.prog.setValue(0)
            err = res.get("error") or "未知错误"
            self.log.line("[X] 切片失败：%s" % err, "err")
            for o in res.get("outputs") or []:
                self.log.line("[完成] %s（已校验可播）" % os.path.basename(o["path"]),
                              "ok")
            InfoBar.error("切片失败", str(err)[:200], duration=6000,
                          position=InfoBarPosition.BOTTOM_RIGHT, parent=self)


def build_page(app, parent=None):
    """注册表 GuiSpec.builder / 容器页组装入口（split.build_page 服务）。"""
    return SplitPage(app, parent)