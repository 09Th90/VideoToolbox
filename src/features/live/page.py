# -*- coding: utf-8 -*-
# @version 3.3.1
"""实时字幕控制页：音源/设备、开始停止、状态、字幕流、日志、悬浮层开关。

约束：只经 ``vt_app`` 基建 + 本功能包；不反向 import GUI 入口。
线程边界：``LiveService`` 只往 ``queue.Queue`` 写，本页用 QTimer 轮询，
worker 永不碰 QWidget。
"""
from __future__ import annotations

import queue
import time

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QFileDialog,
                               QHeaderView, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from vt_fluent import (BodyLabel, CaptionLabel, ComboBox, FluentIcon as FIF,
                       LineEdit, PlainTextEdit, PrimaryPushButton, PushButton,
                       StrongBodyLabel)

from vt_app.widgets import ScrollPage, card, row

from features.live.calib_adapter import MODE_LABELS
from features.live.config import LiveConfig
from features.live.service import LiveService
from features.live import sources as live_sources

SOURCE_ITEMS = (("loopback", "系统内录（WASAPI）"),
                ("mic", "麦克风"),
                ("wav", "WAV 文件（回归）"))


def _fmt_ms(ms: int) -> str:
    ms = max(0, int(ms))
    m, s = divmod(ms // 1000, 60)
    return f"{m:02d}:{s:02d}"


class LivePage(QWidget):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setObjectName("LivePage")
        self.service: LiveService | None = None
        self.overlay = None
        self._queue: queue.Queue | None = None
        self._rows: dict[int, int] = {}
        self._cues: dict[int, dict] = {}
        self._connected_quit = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.shell = ScrollPage(
            "实时字幕",
            "系统内录/麦克风实时双语字幕；ASR 端点与密钥复用「设置 → ASR 语音识别」；"
            "同步增量输出 SRT，另写 sub_en.txt / sub_zh.txt 供 OBS 文本源读取。",
            self, scrollable=True)
        outer.addWidget(self.shell)
        vbox = self.shell.content_lay
        vbox.setSpacing(12)

        # ---------------------------------------------------------------- 采集
        box, lay = card("采集与识别")
        self.source_combo = ComboBox(self)
        for key, label in SOURCE_ITEMS:
            self.source_combo.addItem(label, key)
        self.device_combo = ComboBox(self)
        self.refresh_btn = PushButton(FIF.SYNC, "刷新设备", self)
        self.refresh_btn.clicked.connect(self.refresh_devices)
        self.source_combo.currentIndexChanged.connect(self._on_source_changed)
        lay.addWidget(row(BodyLabel("音源", self), self.source_combo,
                          self.device_combo, self.refresh_btn))

        self.wav_edit = LineEdit(self)
        self.wav_edit.setPlaceholderText("选择 16 kHz / 单声道 / 16-bit WAV")
        self.wav_browse = PushButton(FIF.FOLDER, "浏览…", self)
        self.wav_browse.clicked.connect(self.browse_wav)
        lay.addWidget(row(BodyLabel("WAV", self), self.wav_edit, self.wav_browse))

        self.calib_combo = ComboBox(self)
        for key, label in MODE_LABELS:
            self.calib_combo.addItem(f"{label}（{key}）", key)
        self.calib_combo.currentIndexChanged.connect(self._on_calib_changed)
        self.srt_check = QCheckBox("同步输出 SRT", self)
        self.srt_check.setChecked(True)
        self.srt_check.setEnabled(False)
        self.srt_check.setToolTip("SRT 始终同步输出；关闭请改 data/live_config.json")
        lay.addWidget(row(BodyLabel("校准", self), self.calib_combo,
                          self.srt_check))

        self.start_btn = PrimaryPushButton(FIF.PLAY, "开始", self)
        self.stop_btn = PushButton(FIF.CANCEL, "停止", self)
        self.overlay_btn = PushButton(FIF.VIDEO, "显示悬浮窗", self)
        self.out_btn = PushButton(FIF.FOLDER, "打开输出目录", self)
        self.start_btn.clicked.connect(self.start_live)
        self.stop_btn.clicked.connect(self.stop_live)
        self.overlay_btn.clicked.connect(self.toggle_overlay)
        self.out_btn.clicked.connect(self.open_out_dir)
        lay.addWidget(row(self.start_btn, self.stop_btn, self.overlay_btn,
                          self.out_btn))
        vbox.addWidget(box)

        # ---------------------------------------------------------------- 状态
        box, lay = card("运行状态")
        self.status_label = StrongBodyLabel("未开始", self)
        self.srt_label = CaptionLabel("SRT：—", self)
        self.srt_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.stats_label = CaptionLabel("ASR：未检测 · 本地引擎：未检测", self)
        lay.addWidget(self.status_label)
        lay.addWidget(self.stats_label)
        lay.addWidget(self.srt_label)
        vbox.addWidget(box)

        # ---------------------------------------------------------------- 字幕流
        box, lay = card("字幕流", "最近 300 条；悬浮层只显示最新 2 条")
        self.table = QTableWidget(0, 4, self)
        self.table.setHorizontalHeaderLabels(["时间", "译文", "原文", "后端"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeToContents)
        for i in (1, 2, 3):
            self.table.horizontalHeader().setSectionResizeMode(
                i, QHeaderView.Stretch if i != 3 else QHeaderView.ResizeToContents)
        self.table.setMinimumHeight(260)
        lay.addWidget(self.table)
        vbox.addWidget(box)

        # ---------------------------------------------------------------- 日志
        box, lay = card("日志")
        self.log = PlainTextEdit(self)
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(140)
        self.log.setFont(QFont("Consolas", 9))
        lay.addWidget(self.log)
        vbox.addWidget(box)

        self._timer = QTimer(self)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self._drain)
        self._timer.start()

        self._load_config_to_ui()
        self._set_running_ui(False)
        self.refresh_devices(silent=True)

    # ------------------------------------------------------------------ config
    def _load_config_to_ui(self) -> None:
        cfg = LiveConfig.load()
        kind = cfg.get("source", "type", "loopback")
        idx = self.source_combo.findData(kind)
        if idx >= 0:
            self.source_combo.setCurrentIndex(idx)
        self.wav_edit.setText(str(cfg.get("source", "wav", "") or ""))
        mode = cfg.get("calib", "mode", "bi")
        midx = self.calib_combo.findData(mode)
        if midx >= 0:
            self.calib_combo.setCurrentIndex(midx)
        self.srt_check.setChecked(bool(cfg.get("srt", "enabled", True)))
        self._on_source_changed()

    def _on_source_changed(self) -> None:
        kind = self.source_combo.currentData()
        is_wav = kind == "wav"
        self.wav_edit.setEnabled(is_wav)
        self.wav_browse.setEnabled(is_wav)
        self.device_combo.setEnabled(not is_wav)
        self.refresh_btn.setEnabled(not is_wav)

    def _on_calib_changed(self) -> None:
        mode = self.calib_combo.currentData()
        if self.service is not None:
            self.service.apply_hot_update({"calib.mode": mode})

    # ------------------------------------------------------------------ devices
    def refresh_devices(self, silent: bool = False) -> None:
        kind = self.source_combo.currentData()
        self.device_combo.clear()
        if kind == "wav":
            self._on_source_changed()
            return
        try:
            devices = live_sources.list_devices(kind)
        except Exception as e:  # noqa: BLE001
            self.device_combo.addItem("（设备枚举失败）", "")
            if not silent:
                self._log(f"设备枚举失败：{e}")
            return
        for d in devices:
            mark = "（默认）" if d.get("default") else ""
            self.device_combo.addItem(d["name"] + mark, d["name"])
        if not devices:
            self.device_combo.addItem("（无可用设备）", "")
        else:
            # 默认口可能在列表中间（多扬声器/多麦克风）；不显式选中就用了
            # 列表第一项，用户会以为「系统默认」但实际抓的是另一只设备。
            default_idx = next((i for i, d in enumerate(devices)
                                if d.get("default")), 0)
            self.device_combo.setCurrentIndex(default_idx)

    def browse_wav(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 WAV（16 kHz / 单声道 / 16-bit）", "",
            "WAV 音频 (*.wav)")
        if path:
            self.wav_edit.setText(path)

    # ------------------------------------------------------------------ lifecycle
    def _ensure_service(self) -> LiveService:
        if self.service is None:
            self._queue = queue.Queue(maxsize=200)
            self.service = LiveService(LiveConfig.load(), self._queue)
            app = self.app
            if not self._connected_quit:
                try:
                    from PySide6.QtWidgets import QApplication
                    QApplication.instance().aboutToQuit.connect(self.shutdown)
                    self._connected_quit = True
                except Exception:  # noqa: BLE001
                    pass
        return self.service

    def start_live(self) -> None:
        kind = self.source_combo.currentData() or "loopback"
        device = self.device_combo.currentData() or ""
        if kind == "wav":
            path = self.wav_edit.text().strip()
            if not path:
                self._log("未选择 WAV 文件。")
                return
            import os
            if not os.path.isfile(path):
                self._log(f"WAV 不存在：{path}")
                return
        else:
            try:
                import soundcard  # noqa: F401,PLC0415
            except ImportError:
                self._log("未安装 soundcard，无法内录/麦克风。请执行：\n"
                          "  tools\\python\\python.exe -m pip install soundcard numpy\n"
                          "或先用「WAV 文件」模式验证链路。")
                return
        service = self._ensure_service()
        if kind == "wav":
            service.cfg.hot_update({"source.wav": self.wav_edit.text().strip(),
                                    "source.type": "wav"})
        try:
            service.start(kind, device)
        except Exception as e:  # noqa: BLE001
            self._log(f"启动失败：{e}")
            return
        self._set_running_ui(True)
        self.status_label.setText(f"运行中 · {self.source_combo.currentText()}")
        if self.overlay is not None and self.overlay.isVisible():
            self.overlay.show_overlay()
        self.srt_label.setText(f"SRT：{service.srt_path()}")

    def stop_live(self) -> None:
        if self.service is not None:
            self.service.stop()
        if self.overlay is not None:
            self.overlay.hide_overlay()
        self._set_running_ui(False)
        self.status_label.setText("已停止")

    def _set_running_ui(self, running: bool) -> None:
        self.start_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        self.source_combo.setEnabled(not running)
        self.device_combo.setEnabled(not running and self.source_combo.currentData() != "wav")
        self.refresh_btn.setEnabled(not running and self.source_combo.currentData() != "wav")
        self.wav_edit.setEnabled(not running and self.source_combo.currentData() == "wav")
        self.wav_browse.setEnabled(not running and self.source_combo.currentData() == "wav")

    def toggle_overlay(self) -> None:
        if self.overlay is None:
            from features.live.overlay import OverlayWindow
            cfg = self.service.cfg if self.service else LiveConfig.load()
            self.overlay = OverlayWindow(cfg)
            self.overlay.set_cues(list(self._cues.values()))
        if self.overlay.isVisible():
            self.overlay.hide_overlay()
            self.overlay_btn.setText("显示悬浮窗")
        else:
            self.overlay.show_overlay()
            self.overlay_btn.setText("隐藏悬浮窗")

    def open_out_dir(self) -> None:
        cfg = self.service.cfg if self.service else LiveConfig.load()
        path = cfg.path("sinks", "text_dir")
        try:
            path.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        except Exception as e:  # noqa: BLE001
            self._log(f"打开输出目录失败：{e}")

    def shutdown(self) -> None:
        if self.service is not None:
            self.service.stop()
        if self.overlay is not None:
            self.overlay.hide()

    # ------------------------------------------------------------------ queue
    def _drain(self) -> None:
        if self._queue is None:
            return
        for _ in range(20):
            try:
                msg = self._queue.get_nowait()
            except queue.Empty:
                break
            self._handle(msg)

    def _handle(self, msg: dict) -> None:
        kind = msg.get("type")
        stats = msg.get("stats") or {}
        self._update_status(stats)
        if kind == "cues":
            cues = msg.get("cues") or []
            self._upsert_cues(cues)
            if self.overlay is not None and self.overlay.isVisible():
                self.overlay.set_cues(list(self._cues.values()))
        elif kind == "error":
            self._log(str(msg.get("message") or "未知错误"))
        elif kind == "drop":
            self._log(f"丢段：{msg.get('message', '')}")
        elif kind == "stopped":
            self._set_running_ui(False)
            self.status_label.setText("已停止")
        elif kind == "started":
            self.srt_label.setText(f"SRT：{stats.get('srt', '')}")
        elif kind == "config":
            if self.service is not None and self.overlay is not None:
                self.overlay.apply_ui()

    def _update_status(self, stats: dict) -> None:
        router = stats.get("router") or {}
        state = router.get("state", "—")
        pending = (stats.get("bus") or {}).get("pending", 0)
        dropped = ((stats.get("bus") or {}).get("dropped_oldest", 0)
                   + (stats.get("bus") or {}).get("dropped_stale", 0))
        cloud = stats.get("cloud") or {}
        local = stats.get("local") or {}
        calib = stats.get("calib") or {}
        latency = cloud.get("last_latency_s", 0)
        segs = stats.get("segments_produced", 0)
        self.stats_label.setText(
            f"ASR：{'已配置' if stats.get('asr_configured') else '未配置'}"
            f" · 本地引擎：{'在位' if stats.get('local_configured') else '未安装'}"
            f" · 状态：{state} · 段：{segs} · 队列：{pending} · 丢段：{dropped}"
            f" · ASR 延迟：{latency}s"
            f" · 校准：{calib.get('normalized') or '直通'}")
        srt = stats.get("srt") or ""
        if srt:
            self.srt_label.setText(f"SRT：{srt}")

    def _upsert_cues(self, cues: list[dict]) -> None:
        for cue in cues:
            seq = int(cue.get("seq", 0))
            self._cues[seq] = cue
            row = self._rows.get(seq)
            if row is None:
                row = self.table.rowCount()
                self.table.insertRow(row)
                self._rows[seq] = row
                for col in range(4):
                    item = QTableWidgetItem("")
                    if col == 0:
                        item.setTextAlignment(Qt.AlignCenter)
                    self.table.setItem(row, col, item)
            self._fill_row(row, cue)
        if len(self._cues) > 300:
            for seq in sorted(self._cues)[:-300]:
                self._cues.pop(seq, None)
                row = self._rows.pop(seq, None)
                if row is not None and row < self.table.rowCount():
                    self.table.removeRow(row)
                    self._rows = {k: (v - 1 if v > row else v)
                                  for k, v in self._rows.items()}
            for seq in sorted(self._cues):
                row = self._rows.get(seq)
                if row is not None:
                    self._fill_row(row, self._cues[seq])
        self.table.scrollToBottom()

    def _fill_row(self, row: int, cue: dict) -> None:
        values = (_fmt_ms(cue.get("t0_ms", 0)),
                  (cue.get("main") or "").strip(),
                  (cue.get("sub") or "").strip(),
                  (cue.get("backend") or "") +
                  (" / 降级" if cue.get("degraded") else ""))
        for col, value in enumerate(values):
            item = self.table.item(row, col)
            if item is None:
                item = QTableWidgetItem("")
                self.table.setItem(row, col, item)
            item.setText(value)
            if col == 0:
                item.setTextAlignment(Qt.AlignCenter)
            if cue.get("degraded") and col == 1:
                item.setForeground(Qt.darkYellow)

    def _log(self, text: str) -> None:
        if not text:
            return
        stamp = time.strftime("%H:%M:%S")
        self.log.appendPlainText(f"[{stamp}] {text}")


def build_page(app):
    """GuiSpec.builder 入口：只由 MainWindow 惰性调用。"""
    return LivePage(app)
