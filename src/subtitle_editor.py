# -*- coding: utf-8 -*-
# @version 1.12.2
"""字幕编辑页（打轴）的界面控件：波形时间轴 + 字幕表模型。

参照开源实现的结构：
  · Nosub（Qt + libmpv + FFmpeg）三件套：播放器 + 波形轨 + 字幕表；
  · KDE Subtitle Composer（Qt + mpv + 波形轨）—— 字幕块直接画在时间轴上。

本文件只放"控件"；页面组装是 `video_toolbox_qt.py` 里的 `SubtitleEditPage`
（与其余页面放在同一个文件，避免 `video_toolbox_qt` ↔ 本模块的循环导入）。
控件与数据层（subtitle_editor_core）解耦：控件只持有 cues 的**引用**，
改动通过信号上报给页面统一处理（便于把每次改动压进撤销栈）。
"""
from PyQt5.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PyQt5.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget, QWidget

from subtitle_editor_core import MIN_DURATION_MS, ms_to_clock

# ---------- 配色（深底，浅/深主题下都可用） ----------
C_BG = QColor("#141414")
C_WAVE = QColor("#4aa3df")
C_WAVE_DIM = QColor("#2f6d94")
C_CUE = QColor("#3a3a3a")
C_CUE_TEXT = QColor("#d8d8d8")
C_CUE_SEL = QColor("#c9a227")
C_CUE_SEL_BG = QColor("#4a3f14")
C_PLAYHEAD = QColor("#e0533a")
C_RULER = QColor("#1c1c1c")
C_RULER_TEXT = QColor("#8a8a8a")
C_GRID = QColor("#2a2a2a")

RULER_H = 22
CUE_TRACK_H = 28
WAVE_MIN_H = 60


class WaveformTimeline(QWidget):
    """波形 + 字幕块时间轴。

    交互：
      · 左键点空白      → 请求定位到该时刻
      · 左键拖字幕块中部 → 平移该条
      · 左键拖字幕块边缘 → 改起点/终点
      · 滚轮            → 以鼠标位置为锚点缩放
      · Shift+滚轮/中键拖 → 横向滚动
      · 双击            → 请求在该时刻切割
    """

    position_clicked = pyqtSignal(int)
    cue_selected = pyqtSignal(int)
    drag_started = pyqtSignal()                 # 拖拽即将改动时间：页面借此先压撤销快照
    cue_dragged = pyqtSignal(int, str, int)     # (下标, 'start'/'end'/'move', ms)
    drag_finished = pyqtSignal()
    split_requested = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(WAVE_MIN_H + RULER_H + CUE_TRACK_H)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

        self.cues = []                  # 引用 core 的 list，不复制
        self.peaks = bytearray()
        self.peaks_pps = 200            # 每秒峰值点数
        self.duration_ms = 0
        self.position_ms = 0
        self.selected = -1
        self.follow_playhead = True

        self.pixels_per_second = 80.0    # 缩放
        self.view_start_ms = 0           # 左边缘对应时间

        self._drag_mode = None           # 'move' / 'start' / 'end' / 'scroll'
        self._drag_cue = -1
        self._drag_grab_ms = 0
        self._drag_orig = None
        self._drag_x0 = 0
        self._drag_view0 = 0

    # ---------- 数据 ----------
    def set_media(self, peaks, duration_ms, peaks_pps=200):
        self.peaks = peaks or bytearray()
        self.peaks_pps = peaks_pps
        self.duration_ms = int(duration_ms)
        self.view_start_ms = 0
        self.update()

    def set_cues(self, cues):
        self.cues = cues
        self.update()

    def set_position(self, ms, follow=True):
        self.position_ms = max(0, int(ms))
        if follow and self.follow_playhead and self.width() > 0:
            self._ensure_visible(self.position_ms)
        self.update()

    def set_selected(self, idx):
        if idx != self.selected:
            self.selected = idx
            self.update()

    # ---------- 坐标换算 ----------
    def ms_to_x(self, ms):
        return int((ms - self.view_start_ms) * self.pixels_per_second / 1000.0)

    def x_to_ms(self, x):
        return int(self.view_start_ms + x * 1000.0 / self.pixels_per_second)

    def _ensure_visible(self, ms):
        w = self.width()
        x = self.ms_to_x(ms)
        margin = w * 0.25
        if x < margin or x > w - margin:
            self.view_start_ms = max(0, int(ms - w * 1000.0 / self.pixels_per_second * 0.35))

    def _max_view_start(self):
        span = self.width() * 1000.0 / self.pixels_per_second
        total = max(self.duration_ms, 1000)
        return max(0, int(total - span))

    def zoom(self, factor, anchor_x=None):
        """以 anchor_x（默认窗口中心）为锚点缩放。"""
        if anchor_x is None:
            anchor_x = self.width() // 2
        anchor_ms = self.x_to_ms(anchor_x)
        pps = self.pixels_per_second * factor
        self.pixels_per_second = max(4.0, min(4000.0, pps))
        self.view_start_ms = max(0, min(self._max_view_start(),
                                        int(anchor_ms - anchor_x * 1000.0 / self.pixels_per_second)))
        self.update()

    def scroll_by_px(self, dx):
        self.view_start_ms = max(0, min(self._max_view_start(),
                                        self.view_start_ms + int(dx * 1000.0 / self.pixels_per_second)))
        self.update()

    def fit_all(self):
        if self.duration_ms > 0 and self.width() > 0:
            self.pixels_per_second = max(4.0, self.width() * 1000.0 / self.duration_ms)
            self.view_start_ms = 0
            self.update()

    # ---------- 绘制 ----------
    def paintEvent(self, _ev):
        p = QPainter(self)
        p.fillRect(self.rect(), C_BG)
        w, h = self.width(), self.height()
        wave_top = RULER_H
        wave_h = max(10, h - RULER_H - CUE_TRACK_H)
        cue_top = h - CUE_TRACK_H

        self._paint_ruler(p, w)
        self._paint_wave(p, w, wave_top, wave_h)
        self._paint_cues(p, w, cue_top)
        self._paint_playhead(p, h)

    def _paint_ruler(self, p, w):
        p.fillRect(0, 0, w, RULER_H, C_RULER)
        pps = self.pixels_per_second
        # 刻度步长：目标每 80px 一个主刻度
        step_s = _nice_step(80.0 / pps)
        t = (int(self.view_start_ms / (step_s * 1000.0))) * step_s * 1000.0
        p.setPen(QPen(C_RULER_TEXT))
        f = QFont()
        f.setPointSize(8)
        p.setFont(f)
        end_ms = self.view_start_ms + w * 1000.0 / pps
        while t <= end_ms + step_s * 1000:
            x = self.ms_to_x(int(t))
            if 0 <= x <= w:
                p.drawLine(x, RULER_H - 5, x, RULER_H)
                p.drawText(x + 3, RULER_H - 7, _ruler_label(t, step_s))
                p.setPen(QPen(C_GRID))
                p.drawLine(x, RULER_H, x, self.height())
                p.setPen(QPen(C_RULER_TEXT))
            t += step_s * 1000.0

    def _paint_wave(self, p, w, top, wave_h):
        mid = top + wave_h / 2.0
        p.setPen(QPen(C_WAVE_DIM))
        p.drawLine(0, int(mid), w, int(mid))
        if not self.peaks:
            p.setPen(QPen(C_RULER_TEXT))
            p.drawText(QRect(0, top, w, wave_h), Qt.AlignCenter,
                       "（未加载音频波形）")
            return
        pps = self.peaks_pps
        half = wave_h / 2.0 - 2
        pen = QPen(C_WAVE)
        p.setPen(pen)
        for x in range(w):
            t0 = self.view_start_ms + x * 1000.0 / self.pixels_per_second
            t1 = t0 + 1000.0 / self.pixels_per_second
            i0 = int(t0 * pps / 1000.0)
            i1 = int(t1 * pps / 1000.0)
            if i1 <= i0:
                i1 = i0 + 1
            if i1 <= 0 or i0 >= len(self.peaks):
                continue
            i0 = max(0, i0)
            i1 = min(len(self.peaks), i1)
            if i1 <= i0:
                continue
            v = max(self.peaks[i0:i1])
            if not v:
                continue
            hh = v / 255.0 * half
            p.drawLine(x, int(mid - hh), x, int(mid + hh))

    def _paint_cues(self, p, w, top):
        p.fillRect(0, top, w, CUE_TRACK_H, C_RULER)
        f = QFont()
        f.setPointSize(8)
        p.setFont(f)
        fm = QFontMetrics(f)
        for i, c in enumerate(self.cues):
            x0 = self.ms_to_x(c.start)
            x1 = self.ms_to_x(c.end)
            if x1 < -20 or x0 > w + 20:
                continue
            r = QRect(x0, top + 3, max(2, x1 - x0), CUE_TRACK_H - 6)
            sel = (i == self.selected)
            p.setBrush(C_CUE_SEL_BG if sel else C_CUE)
            p.setPen(QPen(C_CUE_SEL if sel else QColor("#555555"), 2 if sel else 1))
            p.drawRect(r)
            if r.width() > 16:
                p.setPen(QPen(C_CUE_TEXT))
                txt = fm.elidedText((c.text or "").replace("\n", " "),
                                    Qt.ElideRight, r.width() - 6)
                p.drawText(r.adjusted(3, 0, -3, 0), Qt.AlignVCenter, txt)
        p.setPen(QPen(C_RULER_TEXT))
        if not self.cues:
            p.drawText(QRect(0, top, w, CUE_TRACK_H), Qt.AlignCenter, "（未加载字幕）")

    def _paint_playhead(self, p, h):
        x = self.ms_to_x(self.position_ms)
        if 0 <= x <= self.width():
            p.setPen(QPen(C_PLAYHEAD, 2))
            p.drawLine(x, 0, x, h)

    # ---------- 命中测试 ----------
    def _cue_at(self, x, y):
        """返回 (下标, 抓取模式)；抓取模式为 'start'/'end'/'move'。"""
        h = self.height()
        cue_top = h - CUE_TRACK_H
        if y < cue_top - 2:
            return -1, None
        edge = 5
        for i, c in enumerate(self.cues):
            x0, x1 = self.ms_to_x(c.start), self.ms_to_x(c.end)
            if x0 - edge <= x <= x1 + edge:
                if abs(x - x0) <= edge:
                    return i, "start"
                if abs(x - x1) <= edge:
                    return i, "end"
                if x0 <= x <= x1:
                    return i, "move"
        return -1, None

    # ---------- 事件 ----------
    def mousePressEvent(self, ev):
        x, y = ev.pos().x(), ev.pos().y()
        if ev.button() == Qt.MiddleButton:
            self._drag_mode = "scroll"
            self._drag_x0 = x
            self._drag_view0 = self.view_start_ms
            self.setCursor(Qt.ClosedHandCursor)
            return
        if ev.button() != Qt.LeftButton:
            return
        idx, mode = self._cue_at(x, y)
        if idx < 0:
            self.position_clicked.emit(self.x_to_ms(x))
            return
        self.selected = idx
        self.cue_selected.emit(idx)
        # 撤销快照必须在**改动之前**落地：下面 mouseMoveEvent 会直接改 cue
        self.drag_started.emit()
        self._drag_mode = mode
        self._drag_cue = idx
        self._drag_x0 = x
        self._drag_orig = (self.cues[idx].start, self.cues[idx].end)
        self.update()

    def mouseMoveEvent(self, ev):
        x, y = ev.pos().x(), ev.pos().y()
        if self._drag_mode == "scroll":
            self.scroll_by_px(self._drag_x0 - x)
            return
        if self._drag_mode in ("move", "start", "end") and 0 <= self._drag_cue < len(self.cues):
            delta = self.x_to_ms(x) - self.x_to_ms(self._drag_x0)
            o_start, o_end = self._drag_orig
            c = self.cues[self._drag_cue]
            if self._drag_mode == "move":
                d = max(-o_start, delta)
                c.start, c.end = o_start + d, o_end + d
                self.cue_dragged.emit(self._drag_cue, "move", d)
            elif self._drag_mode == "start":
                ns = max(0, min(o_end - MIN_DURATION_MS, o_start + delta))
                c.start = ns
                self.cue_dragged.emit(self._drag_cue, "start", ns)
            else:
                ne = max(o_start + MIN_DURATION_MS, o_end + delta)
                c.end = ne
                self.cue_dragged.emit(self._drag_cue, "end", ne)
            self.update()
            return
        # 悬停时给边缘换光标
        idx, mode = self._cue_at(x, y)
        if mode in ("start", "end"):
            self.setCursor(Qt.SizeHorCursor)
        elif mode == "move":
            self.setCursor(Qt.OpenHandCursor)
        else:
            self.setCursor(Qt.ArrowCursor)

    def mouseReleaseEvent(self, ev):
        if self._drag_mode in ("move", "start", "end"):
            self.drag_finished.emit()
        self._drag_mode = None
        self._drag_cue = -1
        self._drag_orig = None
        self.setCursor(Qt.ArrowCursor)

    def mouseDoubleClickEvent(self, ev):
        x, y = ev.pos().x(), ev.pos().y()
        idx, mode = self._cue_at(x, y)
        if idx >= 0 and y >= self.height() - CUE_TRACK_H:
            self.split_requested.emit(self.x_to_ms(x))

    def wheelEvent(self, ev):
        mods = ev.modifiers()
        delta = ev.angleDelta().y()
        if mods & Qt.ShiftModifier:
            self.scroll_by_px(-delta * 0.6)
            return
        if mods & Qt.ControlModifier:
            self.scroll_by_px(-delta * 0.6)
            return
        # 默认缩放：向上滚放大
        self.zoom(1.15 if delta > 0 else 1 / 1.15, ev.pos().x())


def _nice_step(seconds):
    """把秒步长对齐到 1/2/5/10… 这类"好读"的刻度。"""
    for s in (0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60,
              120, 300, 600, 900, 1800, 3600):
        if s >= seconds:
            return s
    return 3600


def _ruler_label(t_sec, step):
    """刻度文字：短步长显示 ms，长步长显示 mm:ss。"""
    total_ms = int(round(t_sec))
    if step < 1:
        return ms_to_clock(total_ms)
    s = total_ms // 1000
    return "%d:%02d" % (s // 60, s % 60)


class CueTable(QTableWidget):
    """字幕表：序号 / 起始 / 结束 / 时长 / 文本。

    直接编辑时把改动通过 `cell_committed` 上报，由页面统一落库 + 压撤销栈。
    """

    cell_committed = pyqtSignal(int, int, str)   # (行, 列, 新文本)
    selection_changed = pyqtSignal(int)

    COLS = ("#", "起始", "结束", "时长", "文本")
    COL_W = (48, 100, 100, 70, 320)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(len(self.COLS))
        self.setHorizontalHeaderLabels(self.COLS)
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.DoubleClicked
                             | QAbstractItemView.EditKeyPressed)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        hh = self.horizontalHeader()
        for i, w in enumerate(self.COL_W):
            self.setColumnWidth(i, w)
        hh.setStretchLastSection(True)
        hh.setSectionResizeMode(0, QHeaderView.Fixed)
        self._loading = False
        self.itemSelectionChanged.connect(self._on_sel)
        self.itemChanged.connect(self._on_changed)

    def load(self, cues):
        """整体刷新；刷新期间屏蔽 itemChanged，避免把程序性更新当用户编辑。"""
        self._loading = True
        try:
            self.setRowCount(len(cues))
            for r, c in enumerate(cues):
                self._set_item(r, 0, str(r + 1), editable=False)
                self._set_item(r, 1, ms_to_clock(c.start))
                self._set_item(r, 2, ms_to_clock(c.end))
                self._set_item(r, 3, "%.2fs" % (c.duration / 1000.0), editable=False)
                self._set_item(r, 4, (c.text or "").replace("\n", " / "))
        finally:
            self._loading = False

    def refresh_row(self, r, cue):
        self._loading = True
        try:
            self._set_item(r, 1, ms_to_clock(cue.start))
            self._set_item(r, 2, ms_to_clock(cue.end))
            self._set_item(r, 3, "%.2fs" % (cue.duration / 1000.0), editable=False)
            self._set_item(r, 4, (cue.text or "").replace("\n", " / "))
        finally:
            self._loading = False

    def _set_item(self, r, c, text, editable=True):
        from PyQt5.QtWidgets import QTableWidgetItem
        it = self.item(r, c)
        if it is None:
            it = QTableWidgetItem()
            self.setItem(r, c, it)
        it.setText(text)
        if not editable:
            it.setFlags(it.flags() & ~Qt.ItemIsEditable)

    def _on_sel(self):
        if self._loading:
            return
        rows = self.selectionModel().selectedRows() if self.selectionModel() else []
        self.selection_changed.emit(rows[0].row() if rows else -1)

    def _on_changed(self, item):
        if self._loading:
            return
        self.cell_committed.emit(item.row(), item.column(), item.text())

    def selected_rows(self):
        rows = self.selectionModel().selectedRows() if self.selectionModel() else []
        return sorted(r.row() for r in rows)

    def select_row(self, r, scroll=True):
        self._loading = True
        try:
            self.clearSelection()
            if 0 <= r < self.rowCount():
                self.selectRow(r)
                if scroll:
                    self.scrollToItem(self.item(r, 0),
                                      QAbstractItemView.PositionAtCenter)
        finally:
            self._loading = False
