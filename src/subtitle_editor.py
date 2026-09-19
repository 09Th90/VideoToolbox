# -*- coding: utf-8 -*-
# @version 1.15.1
"""字幕编辑页（打轴）的界面控件：波形时间轴 + 字幕表模型。

参照开源实现的结构：
  · Nosub（Qt + libmpv + FFmpeg）三件套：播放器 + 波形轨 + 字幕表；
  · KDE Subtitle Composer（Qt + mpv + 波形轨）—— 字幕块直接画在时间轴上。

本文件只放"控件"；页面组装是 `video_toolbox_qt.py` 里的 `SubtitleEditPage`
（与其余页面放在同一个文件，避免 `video_toolbox_qt` ↔ 本模块的循环导入）。
控件与数据层（subtitle_editor_core）解耦：控件只持有 cues 的**引用**，
改动通过信号上报给页面统一处理（便于把每次改动压进撤销栈）。
"""
from PyQt5.QtCore import QPoint, QRect, QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import (QColor, QFont, QFontMetrics, QPainter, QPen, QPolygon)
from PyQt5.QtWidgets import (QAbstractItemView, QCheckBox, QColorDialog, QComboBox, QFontComboBox,
                             QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
                             QLineEdit, QPushButton, QScrollArea, QSizePolicy, QSlider,
                             QSpinBox, QTableWidget, QToolButton, QVBoxLayout, QWidget)

from subtitle_editor_core import MIN_DURATION_MS, ms_to_clock

# ---------- 配色（主题感知：深色=控制台深底，浅色=纸面浅底） ----------
#: 时间轴调色板，深浅两套键集一致。深色套沿用 v1.13.x 的控制台配色；
#: 浅色套 v1.14.1 新增——此前浅色主题下波形/标尺/字幕块仍是深底，与整页
#: 白卡片对比刺眼（用户截图反馈「浅色背景中不协调」）。
#: 浅色底取 log_bg 同款 #F4F6F8，与日志控制台保持同一设计语言。
_PAL_DARK = {
    "bg": QColor("#141414"),
    "wave": QColor("#4aa3df"),
    "wave_dim": QColor("#2f6d94"),
    "cue": QColor("#3a3a3a"),
    "cue_border": QColor("#555555"),
    "cue_text": QColor("#d8d8d8"),
    "cue_sel": QColor("#c9a227"),
    "cue_sel_bg": QColor("#4a3f14"),
    "playhead": QColor("#e0533a"),
    "band": QColor(69, 200, 119, 70),      # 框选矩形填充
    "band_line": QColor("#45C877"),
    "ruler": QColor("#1c1c1c"),
    "ruler_text": QColor("#8a8a8a"),
    "grid": QColor("#2a2a2a"),
}
_PAL_LIGHT = {
    "bg": QColor("#F4F6F8"),
    "wave": QColor("#3D8FD1"),
    "wave_dim": QColor("#B9D3E8"),
    "cue": QColor("#E7EAEF"),
    "cue_border": QColor("#C4CAD2"),
    "cue_text": QColor("#33373D"),
    "cue_sel": QColor("#A87F0A"),
    "cue_sel_bg": QColor("#F3E9C8"),
    "playhead": QColor("#E0533A"),
    "band": QColor(69, 200, 119, 60),
    "band_line": QColor("#2FA95F"),
    "ruler": QColor("#EDEFF2"),
    "ruler_text": QColor("#7A8087"),
    "grid": QColor("#E0E3E8"),
}
_PAL_CACHE = {"key": None, "pal": None}


def _colors():
    """当前主题的时间轴配色（dict[str, QColor]，按主题缓存、切换自动失效）。"""
    try:
        import ui_theme
        dark = ui_theme.is_dark()
    except Exception:            # 无 app/无 ui_theme 的测试环境：回退深色
        dark = True
    key = "dark" if dark else "light"
    if _PAL_CACHE["key"] != key:
        _PAL_CACHE["pal"] = dict(_PAL_DARK if dark else _PAL_LIGHT)
        _PAL_CACHE["key"] = key
    return _PAL_CACHE["pal"]

RULER_H = 22
CUE_TRACK_H = 28
WAVE_MIN_H = 60
PAN_THRESHOLD_PX = 4    # 空白处按下后位移超过它才算「拖动平移」，否则算「点击定位」
PLAYHEAD_GRAB_PX = 6    # 播放头左右这么宽内按下 = 抓住播放头拖，而不是点空白

#: 属性面板里那几个**原生 QToolButton / QSlider** 的样式（主题感知）。
#: 不套样式的话它们在深色主题下几乎是"看不见的"——实测对齐九宫格只剩几个
#: 极暗的小方块、B/I/U 根本认不出来（原生控件默认走浅色 palette）。
#: v1.13.x：改为按 ui_theme token 生成深浅两套；面板本身也带上不透明的
#: 卡片底 + 描边——此前面板是透明的，白字直接叠在板块背景图上，浅色
#: 主题下基本看不清（用户截图反馈「非深色页面下板块样式不合理」）。
#: v1.14.2：数字框/下拉框/复选框统一交给 ui_theme.build_app_qss() 的全局
#: 规则（同一控件全应用一套皮肤），这里只留**面板独有**的部分——卡片底、
#: 分组标题与分隔线、九宫格与 B/I/U/S 这类 QToolButton、滑杆、色块。
def props_qss(t, accent):
    """属性面板 QSS。`t` = ui_theme.tokens()，`accent` = 主题色。"""
    import ui_theme
    tint = ui_theme._tint(accent, 0.18)
    return f"""
SubtitlePropsPanel{{background:{t['card']};border:1px solid {t['card_border']};
                    border-radius:10px;}}
SubtitlePropsPanel QLabel{{color:{t['text']};background:transparent;}}
SubtitlePropsPanel QLabel#propMeta{{color:{t['text_dim']};}}
SubtitlePropsPanel QLabel#propCaption{{color:{t['text_dim']};font-size:11px;}}
SubtitlePropsPanel QLabel#secTitle{{color:{t['text']};font-size:12px;
                    font-weight:600;}}
QScrollArea{{background:transparent;border:none;}}
QScrollArea > QWidget > QWidget{{background:transparent;}}
/* 分组之间一条发丝线：四组标题在一条竖向流里，没有线就分不出层次 */
QWidget#propSec{{border-top:1px solid {t['border']};padding-top:6px;}}
QWidget#propSecTop{{border-top:none;padding-top:0px;}}
QToolButton{{background:{t['input_bg']};color:{t['text']};border:1px solid {t['border']};
            border-radius:6px;font-size:12px;padding:0px 2px;}}
QToolButton:hover{{background:{t['card_hover']};border-color:{t['border_hover']};}}
QToolButton:pressed{{background:{t['card_pressed']};}}
QToolButton:checked{{background:{accent};color:#FFFFFF;border-color:{accent};}}
QToolButton#secToggle,QToolButton#secAdd{{background:transparent;border:none;
            color:{t['text_dim']};padding:0px;}}
QToolButton#secToggle:hover,QToolButton#secAdd:hover{{background:{tint};
            border:none;color:{t['text']};}}
QSlider::groove:horizontal{{height:4px;background:{t['border']};border-radius:2px;}}
QSlider::sub-page:horizontal{{background:{accent};border-radius:2px;}}
QSlider::handle:horizontal{{background:#FFFFFF;border:1px solid {accent};
                           width:12px;margin:-5px 0;border-radius:6px;}}
QSlider::handle:horizontal:hover{{background:{t['card_hover']};}}
QPushButton{{background:{t['input_bg']};color:{t['text']};border:1px solid {t['border']};
            border-radius:6px;padding:1px 10px;min-height:20px;}}
QPushButton:hover{{background:{t['card_hover']};border-color:{t['border_hover']};}}
QPushButton:pressed{{background:{t['card_pressed']};}}
QPushButton#navBtn{{padding:0px;font-size:9px;}}
"""


class WaveformTimeline(QWidget):
    """波形 + 字幕块时间轴。

    交互（v1.13.x 起空白处可直接拖动平移视图）：
      · 左键拖播放头    → **拖动橙色播放头**定位（标尺区任意位置按住即可拖，
                          波形里贴着橙线 ±6px 也可以拖）
      · 左键点空白      → 请求定位到该时刻（**按下原地抬起**才算点击）
      · 左键拖空白/波形  → 自由平移视图（拖动超过 PAN_THRESHOLD_PX 即进入平移）
      · 左键拖字幕块中部 → 平移该条
      · 左键拖字幕块边缘 → 改起点/终点
      · 中键拖          → 同上平移视图（兼容旧习惯）
      · 滚轮            → 以鼠标位置为锚点缩放
      · Shift/Ctrl+滚轮  → 横向滚动
      · 双击字幕块       → 请求在该时刻切割

    「时间轴拖不动」的两次修法：v1.13.x 先给空白处加了拖动平移分支（此前
    按下**立刻**发定位信号就返回，根本没有拖动分支）；用户随后指出他要的是
    **橙线本身可拖**，于是补上播放头抓取模式——标尺区/橙线附近按下即抓住，
    移动时连续 seek，播放头因此从"只能点"变成"能拖"。

    平移后自动**关闭播放头跟随**，否则播放中会被 `_ensure_visible` 拽回原位，
    手感仍然是「拖不动」；点击空白定位时重新打开跟随。
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
        self.selected = -1              # "主选中"（最后点中的那条），保持旧语义
        self.selected_set = set()       # 多选集合；空集表示没有选中
        self.follow_playhead = True

        self.pixels_per_second = 80.0    # 缩放
        self.view_start_ms = 0           # 左边缘对应时间
        self.frame_fps = 25.0            # 视频帧率（页面从 mpv 同步；帧刻度用）

        self._drag_mode = None           # 'pending' / 'move' / 'start' / 'end' / 'scroll'
        self._drag_cue = -1
        self._drag_grab_ms = 0
        self._drag_orig = None
        self._drag_x0 = 0
        self._drag_view0 = 0
        self._press_x = 0                # 'pending' 期间记住按下位置：原地抬起则在此定位
        self._band0 = 0                  # 框选起点 x
        self._band1 = 0                  # 框选终点 x

        # 主题感知：深浅切换时按新调色板整条重绘（weakref 回调，不拖住回收）。
        try:
            import ui_theme
            ui_theme.connect_theme(self, lambda w: w.update())
        except Exception:
            pass

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
        old_view = self.view_start_ms
        old_x = self.ms_to_x(self.position_ms)
        self.position_ms = max(0, int(ms))
        # 用户正在手动平移时不抢视图：否则播放中每帧都被 _ensure_visible 拽回，
        # 表现就是「怎么拖都拖不动」。
        if (follow and self.follow_playhead and self.width() > 0
                and self._drag_mode not in ("pending", "scroll")):
            self._ensure_visible(self.position_ms)
        if self.view_start_ms != old_view:
            self.update()                 # 视图平移了：整条重画
        else:
            # 只让播放头扫过的两条窄带失效。这是"播放时不卡"的关键：
            # 全量重绘会把整条波形（逐像素 drawLine）重跑一遍。
            for x in (old_x, self.ms_to_x(self.position_ms)):
                self.update(QRect(x - 4, 0, 9, self.height()))

    def selected_indices(self):
        """当前选中的全部下标（升序）。没有多选时退化成单选的那一条。"""
        if self.selected_set:
            return sorted(self.selected_set)
        return [self.selected] if self.selected >= 0 else []

    def _repaint_cues(self):
        """选中态只影响最底下那条 cue 轨道，别牵动整条波形。"""
        self.update(QRect(0, self.height() - CUE_TRACK_H,
                          self.width(), CUE_TRACK_H))

    def set_selection(self, indices):
        """整批设置选中（Ctrl+A / 框选结束 / 外部同步都用它）。"""
        sel = set(int(i) for i in (indices or []))
        if sel == self.selected_set:
            return
        self.selected_set = sel
        self.selected = max(sel) if sel else -1
        self._repaint_cues()

    def set_selected(self, idx):
        idx = int(idx)
        want = {idx} if idx >= 0 else set()
        if idx != self.selected or want != self.selected_set:
            self.selected = idx
            self.selected_set = want
            self._repaint_cues()

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
        # 上限 20000pps：30fps 一帧约 667px、60fps 也有 333px——逐帧对齐
        # 绰绰有余；再大只剩放大噪声，没有信息增量
        self.pixels_per_second = max(4.0, min(20000.0, pps))
        self.view_start_ms = max(0, min(self._max_view_start(),
                                        int(anchor_ms - anchor_x * 1000.0 / self.pixels_per_second)))
        self.update()

    def scroll_by_px(self, dx):
        self.view_start_ms = max(0, min(self._max_view_start(),
                                        self.view_start_ms + int(dx * 1000.0 / self.pixels_per_second)))
        self.update()

    def _begin_pan(self, x):
        """进入「拖动平移视图」模式，并关掉播放头跟随。"""
        self._drag_mode = "scroll"
        self._drag_x0 = x
        self._drag_view0 = self.view_start_ms
        self.follow_playhead = False
        self.setCursor(Qt.ClosedHandCursor)

    def _pan_to(self, x):
        """按拖动**起点**绝对换算视图左边缘。

        与 `scroll_by_px` 的增量做法不同：增量每次都被 clamp，一路拖到最左再往回拖
        会有明显粘滞；这里始终以 `_drag_view0` 为基准，来回甩都不会丢行程。
        """
        delta_ms = int((self._drag_x0 - x) * 1000.0 / self.pixels_per_second)
        self.view_start_ms = max(0, min(self._max_view_start(),
                                        self._drag_view0 + delta_ms))
        self.update()

    def fit_all(self):
        if self.duration_ms > 0 and self.width() > 0:
            self.pixels_per_second = max(4.0, self.width() * 1000.0 / self.duration_ms)
            self.view_start_ms = 0
            self.update()

    def set_fps(self, fps):
        """同步视频帧率（页面从 mpv 拿 container-fps；拿不到默认 25）。"""
        try:
            fps = float(fps)
        except (TypeError, ValueError):
            return
        if fps > 0 and abs(fps - self.frame_fps) > 1e-6:
            self.frame_fps = fps
            self.update()

    # ---------- 绘制 ----------
    def paintEvent(self, ev):
        """绘制整条时间轴（支持 Qt 的**局部重绘**）。

        为什么要按 clip 裁剪：波形是 `for x in range(w)` 一列一条 drawLine 画
        出来的，而播放头 40ms 动一次、拖动时每帧都在动。若每帧都全量重绘，
        等于每秒几十次把整条波形重画一遍——导入视频后 mpv 还在解码，就明显卡。
        配合 `set_position` / `set_selected` 的窄带失效，播放时每帧实际只需
        画到十几个像素列。
        """
        p = QPainter(self)
        c = _colors()
        clip = ev.rect()
        w, h = self.width(), self.height()
        full = clip.width() >= w and clip.height() >= h
        p.fillRect(self.rect() if full else clip, c["bg"])
        wave_top = RULER_H
        wave_h = max(10, h - RULER_H - CUE_TRACK_H)
        cue_top = h - CUE_TRACK_H

        self._paint_ruler(p, w, clip)
        self._paint_wave(p, w, wave_top, wave_h, clip, full)
        self._paint_cues(p, w, cue_top, clip, full)
        self._paint_band(p)
        self._paint_playhead(p, h)

    def _paint_ruler(self, p, w, clip):
        c = _colors()
        p.fillRect(QRect(clip.left(), 0, clip.width(), RULER_H), c["ruler"])
        pps = self.pixels_per_second
        # 刻度步长：目标每 80px 一个主刻度
        step_s = _nice_step(80.0 / pps)
        t = (int(self.view_start_ms / (step_s * 1000.0))) * step_s * 1000.0
        p.setPen(QPen(c["ruler_text"]))
        f = QFont()
        f.setPointSize(8)
        p.setFont(f)
        end_ms = self.view_start_ms + w * 1000.0 / pps
        while t <= end_ms + step_s * 1000:
            x = self.ms_to_x(int(t))
            # 刻度文字有宽度（mm:ss 约 40px），出界一点也得画，否则局部重绘时
            # 会出现"字被切掉一半"
            if 0 <= x <= w and clip.left() - 70 <= x <= clip.right() + 70:
                p.drawLine(x, RULER_H - 5, x, RULER_H)
                p.drawText(x + 3, RULER_H - 7, _ruler_label(t, step_s))
                p.setPen(QPen(c["grid"]))
                p.drawLine(x, RULER_H, x, self.height())
                p.setPen(QPen(c["ruler_text"]))
            t += step_s * 1000.0
        self._paint_frame_ticks(p, w, clip)

    def _paint_frame_ticks(self, p, w, clip):
        """高倍放大时的**帧刻度**：每帧一条短线，帧距够宽时标帧号。

        「精度更高，显示更多帧」：帧是打轴的最小对齐单位——放大到一帧好
        几个像素后把帧边界画出来，逐帧对齐（,/.）就有的放矢。一帧不到
        5px 时画出来全是噪音，直接跳过。
        """
        fps = float(self.frame_fps or 25.0)
        if fps <= 0 or self.pixels_per_second <= 0:
            return
        frame_ms = 1000.0 / fps
        frame_px = frame_ms * self.pixels_per_second
        if frame_px < 5.0:
            return
        c = _colors()
        x0 = max(0, clip.left())
        x1 = min(w - 1, clip.right())
        t0 = self.view_start_ms + x0 * 1000.0 / self.pixels_per_second
        t1 = self.view_start_ms + (x1 + 1) * 1000.0 / self.pixels_per_second
        f0 = max(0, int(t0 / frame_ms))
        f1 = int(t1 / frame_ms) + 1
        show_no = frame_px >= 56.0
        pen = QPen(c["grid"])
        ff = QFont()
        ff.setPointSize(7)
        for fi in range(f0, f1 + 1):
            x = self.ms_to_x(int(fi * frame_ms))
            if x < 0 or x > w:
                continue
            p.setPen(pen)
            p.drawLine(x, RULER_H - 2, x, RULER_H)
            if show_no:
                p.setFont(ff)
                p.setPen(QPen(c["ruler_text"]))
                p.drawText(x + 2, RULER_H - 2, str(fi))
                p.setPen(pen)

    def _paint_wave(self, p, w, top, wave_h, clip, full):
        c = _colors()
        x_from = max(0, clip.left())
        x_to = min(w - 1, clip.right())
        mid = top + wave_h / 2.0
        p.setPen(QPen(c["wave_dim"]))
        p.drawLine(x_from, int(mid), x_to, int(mid))
        if not self.peaks:
            if full:            # 居中提示只在整条重绘时画，避免被切成半句
                p.setPen(QPen(c["ruler_text"]))
                p.drawText(QRect(0, top, w, wave_h), Qt.AlignCenter,
                           "（未加载音频波形）")
            return
        pps = self.peaks_pps
        half = wave_h / 2.0 - 2
        pen = QPen(c["wave"])
        p.setPen(pen)
        for x in range(x_from, x_to + 1):
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

    def _paint_cues(self, p, w, top, clip, full):
        c = _colors()
        p.fillRect(QRect(clip.left(), top, clip.width(), CUE_TRACK_H), c["ruler"])
        # 夹住绘制范围：字幕块上的文本是逐块 drawText 的，不夹的话局部重绘时
        # 会把整行文字都画出去（Qt 会裁，但白做一遍排版）
        p.save()
        p.setClipRect(clip)
        f = QFont()
        f.setPointSize(8)
        p.setFont(f)
        fm = QFontMetrics(f)
        for i, cu in enumerate(self.cues):
            x0 = self.ms_to_x(cu.start)
            x1 = self.ms_to_x(cu.end)
            if x1 < clip.left() - 20 or x0 > clip.right() + 20:
                continue
            r = QRect(x0, top + 3, max(2, x1 - x0), CUE_TRACK_H - 6)
            sel = i in self.selected_set or (not self.selected_set
                                             and i == self.selected)
            p.setBrush(c["cue_sel_bg"] if sel else c["cue"])
            p.setPen(QPen(c["cue_sel"] if sel else c["cue_border"],
                          2 if sel else 1))
            p.drawRect(r)
            if r.width() > 16:
                p.setPen(QPen(c["cue_text"]))
                txt = fm.elidedText((cu.text or "").replace("\n", " "),
                                    Qt.ElideRight, r.width() - 6)
                p.drawText(r.adjusted(3, 0, -3, 0), Qt.AlignVCenter, txt)
        p.restore()
        if not self.cues and full:
            p.setPen(QPen(c["ruler_text"]))
            p.drawText(QRect(0, top, w, CUE_TRACK_H), Qt.AlignCenter,
                       "（未加载字幕）")

    def _paint_band(self, p):
        """框选矩形（只在框选进行中画）。"""
        if self._drag_mode != "band":
            return
        c = _colors()
        x0, x1 = sorted((self._band0, self._band1))
        top = self.height() - CUE_TRACK_H
        p.setBrush(c["band"])
        p.setPen(QPen(c["band_line"], 1, Qt.DashLine))
        p.drawRect(QRect(x0, top, max(1, x1 - x0), CUE_TRACK_H))

    def _apply_band(self):
        """把框选范围换算成命中的 cue 下标（区间相交即算命中）。"""
        x0, x1 = sorted((self._band0, self._band1))
        picked = set()
        for i, c in enumerate(self.cues):
            cx0, cx1 = self.ms_to_x(c.start), self.ms_to_x(c.end)
            if cx1 >= x0 and cx0 <= x1:
                picked.add(i)
        self.selected_set = picked
        self.selected = max(picked) if picked else -1

    def _paint_playhead(self, p, h):
        x = self.ms_to_x(self.position_ms)
        if 0 <= x <= self.width():
            ph = _colors()["playhead"]
            p.setPen(QPen(ph, 2))
            p.drawLine(x, 0, x, h)
            # 顶部抓手：这条橙线现在可以**直接拖动**，画个把手让"可拖"一眼可见，
            # 同时也把抓取目标从 1px 的线扩成一个看得见的三角。
            p.setBrush(ph)
            p.setPen(Qt.NoPen)
            p.drawPolygon(QPolygon([QPoint(x - 6, 0), QPoint(x + 6, 0), QPoint(x, 9)]))
            if self.pixels_per_second >= 800:
                # 高倍放大：播放头旁显示精确时间与帧号（逐帧打轴的读数）
                fps = float(self.frame_fps or 25.0)
                fr = int(self.position_ms * fps / 1000.0)
                p.setPen(QPen(_colors()["ruler_text"]))
                f = QFont()
                f.setPointSize(8)
                p.setFont(f)
                label = "%s  f%d" % (ms_to_clock(self.position_ms), fr)
                p.drawText(x + (9 if x + 170 <= self.width() else -168),
                           RULER_H - 7, label)

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
            self._begin_pan(x)
            return
        if ev.button() != Qt.LeftButton:
            return
        # ① 播放头优先：标尺区任意位置、或波形/空白区里贴着橙线（±6px）按下，
        #    都算「抓住播放头拖」。剪映那种"拖橙线找位置"的操作靠的就是这条。
        #    ⚠️ 字幕块轨道（最底下 28px）不参与播放头命中的抢占——那里的
        #    边缘拖拽改起止时间更重要，橙线正好压在某条上时不能把它抢走。
        cue_top = self.height() - CUE_TRACK_H
        phx = self.ms_to_x(self.position_ms)
        if y < RULER_H or (y < cue_top - 2 and abs(x - phx) <= PLAYHEAD_GRAB_PX):
            self._begin_playhead_drag(x)
            return
        idx, mode = self._cue_at(x, y)
        if idx < 0:
            # cue 轨道上的**空白**：拖 = 框选多条。
            # 波形/标尺区的空白仍然是"待定"（拖动平移视图 / 原地点击定位），
            # 两者不能抢同一种手势。
            if y >= cue_top - 2:
                self._drag_mode = "band"
                self._band0 = self._band1 = x
                if not (ev.modifiers() & (Qt.ShiftModifier | Qt.ControlModifier)):
                    self.selected_set = set()
                    self.selected = -1
                self._repaint_cues()
                return
            self._drag_mode = "pending"
            self._drag_x0 = x
            self._press_x = x
            self._drag_view0 = self.view_start_ms
            return
        # —— 点中某条：按修饰键决定单选 / 加选 / 范围选 ——
        mods = ev.modifiers()
        if mods & Qt.ShiftModifier and self.selected >= 0:
            lo, hi = sorted((self.selected, idx))
            self.selected_set = set(range(lo, hi + 1))
            self.selected = idx
        elif mods & Qt.ControlModifier:
            self.selected_set = set(self.selected_set)
            if idx in self.selected_set:
                self.selected_set.discard(idx)
            else:
                self.selected_set.add(idx)
            self.selected = (idx if idx in self.selected_set
                             else (max(self.selected_set) if self.selected_set else -1))
        else:
            # ⚠️ 点**已选中**的条（多选 ≥2 时）不能把它重置成单选——
            # Ctrl+A 全选后按住字幕块准备拖动，走的就是这条路径；一旦
            # 重置，紧随其后的批量快照只看到一条，「整体调整」就失效了。
            # （点集合**外**的条才是「换目标」，单选化。）
            if idx not in self.selected_set or len(self.selected_set) <= 1:
                self.selected_set = {idx}
            self.selected = idx
        self._repaint_cues()
        self.cue_selected.emit(self.selected)
        # 撤销快照必须在**改动之前**落地：下面 mouseMoveEvent 会直接改 cue
        self.drag_started.emit()
        self._drag_mode = mode
        self._drag_cue = idx
        self._drag_x0 = x
        self._drag_orig = (self.cues[idx].start, self.cues[idx].end)
        # ⚠️ 多选批量基准：Ctrl+A 全选（或框选 / Ctrl 点选 ≥2 条）后拖动，
        # **所有选中条一起平移相同时间量**（保持相对间隔）——基准必须取
        # 按下那一刻的原始坐标：每帧都拿"当前值"叠位移会越拖越漂。
        sel = {i for i in self.selected_set if 0 <= i < len(self.cues)}
        if idx in sel and len(sel) > 1:
            self._drag_multi = {i: (self.cues[i].start, self.cues[i].end)
                                for i in sel}
        else:
            self._drag_multi = None
        self.update()

    def _begin_playhead_drag(self, x):
        """进入「拖动播放头」模式：按下即定位，之后跟着鼠标连续 seek。"""
        self._drag_mode = "playhead"
        self.follow_playhead = True          # 拖动播放头时视图要跟着它走
        self.setCursor(Qt.SizeHorCursor)
        self.position_clicked.emit(self.x_to_ms(x))

    def mouseMoveEvent(self, ev):
        x, y = ev.pos().x(), ev.pos().y()
        if self._drag_mode == "playhead":
            # 拖出左右边界时钳到边缘，避免"甩出去就没反应"
            x = max(0, min(self.width(), x))
            self.position_clicked.emit(self.x_to_ms(x))
            return
        if self._drag_mode == "band":
            self._band1 = x
            self._apply_band()
            self._repaint_cues()
            return
        if self._drag_mode == "pending":
            if abs(x - self._drag_x0) >= PAN_THRESHOLD_PX:
                # 基准取「进入平移这一刻」的 x，起手不会跳掉阈值那段位移
                self._begin_pan(x)
            return
        if self._drag_mode == "scroll":
            self._pan_to(x)
            return
        if self._drag_mode in ("move", "start", "end") and 0 <= self._drag_cue < len(self.cues):
            delta = self.x_to_ms(x) - self.x_to_ms(self._drag_x0)
            o_start, o_end = self._drag_orig
            c = self.cues[self._drag_cue]
            if self._drag_mode == "move":
                d = max(-o_start, delta)
                c.start, c.end = o_start + d, o_end + d
                if self._drag_multi:
                    # 全选/多选批量平移：每条以自己的原始坐标为基准加同样
                    # 的位移（各自钳住不越 0，保持条目间相对间隔）
                    for i, (s0, e0) in self._drag_multi.items():
                        if i == self._drag_cue:
                            continue
                        cc = self.cues[i]
                        dd = max(-s0, d)
                        cc.start, cc.end = s0 + dd, e0 + dd
                self.cue_dragged.emit(self._drag_cue, "move", d)
            elif self._drag_mode == "start":
                ns = max(0, min(o_end - MIN_DURATION_MS, o_start + delta))
                delta_s = ns - o_start
                c.start = ns
                if self._drag_multi:
                    # 批量改起点：全部选中条平移同样的起点位移（各自钳住
                    # 不越 0、不留小于最短时长的负时长）
                    for i, (s0, e0) in self._drag_multi.items():
                        if i != self._drag_cue:
                            self.cues[i].start = max(
                                0, min(e0 - MIN_DURATION_MS, s0 + delta_s))
                self.cue_dragged.emit(self._drag_cue, "start", ns)
            else:
                ne = max(o_start + MIN_DURATION_MS, o_end + delta)
                delta_e = ne - o_end
                c.end = ne
                if self._drag_multi:
                    # 批量改终点：全部选中条平移同样的终点位移（起点不变）
                    for i, (_s0, e0) in self._drag_multi.items():
                        if i != self._drag_cue:
                            self.cues[i].end = max(
                                self.cues[i].start + MIN_DURATION_MS, e0 + delta_e)
                self.cue_dragged.emit(self._drag_cue, "end", ne)
            # 只失效 cue 轨道那一条：拖字幕块时波形一点没变，没必要把
            # 逐像素绘制的波形整条重画一遍（这是拖动卡顿的另一半来源）。
            self.update(QRect(0, self.height() - CUE_TRACK_H,
                              self.width(), CUE_TRACK_H))
            return
        # 悬停：播放头附近 / 字幕块边缘 / 字幕块中部各有各的光标
        cue_top = self.height() - CUE_TRACK_H
        if y < RULER_H or (y < cue_top - 2
                           and abs(x - self.ms_to_x(self.position_ms)) <= PLAYHEAD_GRAB_PX):
            self.setCursor(Qt.SizeHorCursor)
            return
        idx, mode = self._cue_at(x, y)
        if mode in ("start", "end"):
            self.setCursor(Qt.SizeHorCursor)
        elif mode == "move":
            self.setCursor(Qt.OpenHandCursor)
        else:
            self.setCursor(Qt.ArrowCursor)

    def mouseReleaseEvent(self, ev):
        if self._drag_mode == "band":
            self._apply_band()
            self._repaint_cues()
            self.cue_selected.emit(self.selected)
        elif self._drag_mode == "pending":
            # 全程没超过平移阈值 → 当作点击定位，并恢复播放头跟随
            self.follow_playhead = True
            self.position_clicked.emit(self.x_to_ms(self._press_x))
        elif self._drag_mode in ("move", "start", "end"):
            self.drag_finished.emit()
        self._drag_mode = None
        self._drag_cue = -1
        self._drag_multi = None      # 多选批量平移的原始坐标快照（见 press）
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
        # 主题感知：表格底/表头/交替行/选中色按 token 生成（v1.14.1）。
        # 此前无任何 QSS，原生 QTableWidget 吃系统 palette——系统深色模式 +
        # 浅色主题时表格发黑，与整页白卡片割裂。
        self._apply_theme()
        try:
            import ui_theme
            ui_theme.connect_theme(self, lambda w: w._apply_theme())
        except Exception:
            pass

    def _apply_theme(self):
        """字幕表主题感知 QSS（深色=深控制台表，浅色=白表）。"""
        try:
            import ui_theme
            t = ui_theme.tokens()
            accent = ui_theme.get_accent()
        except Exception:
            return
        self.setStyleSheet(
            f"QTableWidget{{background:{t['card']};color:{t['text']};"
            f"alternate-background-color:{t['card_hover']};"
            f"border:1px solid {t['card_border']};gridline-color:{t['border']};"
            f"selection-background-color:{accent};selection-color:#FFFFFF;}}"
            "QTableWidget::item{padding:2px 4px;}"
            f"QHeaderView::section{{background:{t['card_hover']};"
            f"color:{t['text_dim']};border:none;"
            f"border-right:1px solid {t['border']};"
            f"border-bottom:1px solid {t['border']};padding:3px 6px;}}")

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

    def select_rows(self, rows, scroll=True):
        """整批选中若干行（时间轴上多选时同步过来）。"""
        from PyQt5.QtCore import QItemSelection, QItemSelectionModel
        self._loading = True
        try:
            self.clearSelection()
            sel = QItemSelection()
            picked = [r for r in rows if 0 <= r < self.rowCount()]
            for r in picked:
                sel.select(self.model().index(r, 0),
                           self.model().index(r, self.columnCount() - 1))
            if picked:
                self.selectionModel().select(
                    sel, QItemSelectionModel.Select | QItemSelectionModel.Rows)
                if scroll:
                    self.scrollToItem(self.item(picked[0], 0),
                                      QAbstractItemView.PositionAtCenter)
        finally:
            self._loading = False

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

    def reveal_row(self, r):
        """只滚动定位到某行，**不动选中集合**——画面上点中/拖动字幕时，
        主选中要跟随，但 Ctrl+A 的多选不能被打散（与 select_row 的区别）。"""
        if 0 <= r < self.rowCount():
            it = self.item(r, 0)
            if it is not None:
                self.scrollToItem(it, QAbstractItemView.PositionAtCenter)


def _skin_color_dialog(dlg):
    """把当前主题的 palette + QSS 套到颜色框上（含把「确定」涂成主题色）。"""
    import ui_theme
    dlg.setPalette(ui_theme.dialog_palette())
    dlg.setStyleSheet(ui_theme.dialog_qss())
    for btn in dlg.findChildren(QPushButton):
        if btn.isDefault():              # 主操作上色（皮肤要贴在按钮自身）
            btn.setStyleSheet(ui_theme.primary_button_qss())


class ThemedColorDialog(QColorDialog):
    """跟随当前主题的 QColorDialog。

    ⚠️ 皮肤必须**在 showEvent 里再套一次**：主窗口是 Mica 的 FluentWindow，它的
    palette.Window 是黑的（浅色主题下也一样，页面靠自身 QSS 铺白），而 Qt 建窗
    那一刻会把这个 palette 往顶层对话框上再解析一遍——实测 show 前 setPalette
    已是 #FFFFFF，show 之后被打回 #000000，颜色框于是整块发黑（用户截图反馈
    「浅色页面里这个板块不协调」）。所以构造时套一次、每次 show 再套一次。

    ⚠️ 同时不用静态版 `QColorDialog.getColor()`：那条路走系统原生框，深浅两档
    都不受我们的 token 管。
    """

    def __init__(self, cur, parent=None, title=""):
        super().__init__(cur, parent)
        if title:
            self.setWindowTitle(title)
        self.setOption(QColorDialog.DontUseNativeDialog, True)
        _skin_color_dialog(self)

    def showEvent(self, ev):
        super().showEvent(ev)
        _skin_color_dialog(self)
        # ⚠️ 光在 showEvent 里套还不够：Qt 建窗过程中（show() 返回之前）会把主窗口
        #    那套黑 palette 在这只顶层窗口上**再解析一次**，把刚套好的打回去
        #    （实测 PaletteChange 序列：白 → 黑 → 白 → 黑）。所以再排一个 0ms 的
        #    补套，落在建窗之后。
        QTimer.singleShot(0, self._reskin)

    def _reskin(self):
        if self.isVisible():
            _skin_color_dialog(self)


def themed_color_dialog(cur, parent, title):
    """造一个跟随当前主题的颜色选择框（`_pick` 与主题预览脚本共用）。"""
    return ThemedColorDialog(cur, parent, title)


class _Section(QWidget):
    """可折叠分组：标题行（▾ 名称 … 右侧可选 +）+ 内容区。

    版式照抄剪映右侧属性栏——每组一个标题行，点标题折叠/展开。
    """

    def __init__(self, title, parent=None, extra_btn=False, first=False):
        super().__init__(parent)
        # 分组上方的发丝线（props_qss 的 #propSec）是写在样式表里的边框——
        # 普通 QWidget 不开 WA_StyledBackground 根本不画。
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("propSecTop" if first else "propSec")
        self._open = True
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(4)

        head = QHBoxLayout()
        head.setSpacing(4)
        self.btn_toggle = QToolButton(self)
        self.btn_toggle.setArrowType(Qt.DownArrow)
        self.btn_toggle.setAutoRaise(True)
        self.btn_toggle.setFixedSize(16, 16)
        self.btn_toggle.setToolTip("折叠 / 展开")
        self.btn_toggle.setObjectName("secToggle")
        # 必须覆盖 props_qss 里那条 QToolButton 规则：那条给了边框和背景色，
        # 套到折叠箭头上会渲染成一个像复选框的小方块。覆盖规则也在 props_qss
        # 里（#secToggle/#secAdd 按主题取色），这里不再写死颜色。
        self.btn_toggle.clicked.connect(self.toggle)
        self.lbl = QLabel(title, self)
        self.lbl.setObjectName("secTitle")
        f = self.lbl.font()
        f.setBold(True)
        self.lbl.setFont(f)
        head.addWidget(self.btn_toggle)
        head.addWidget(self.lbl)
        head.addStretch(1)
        self.btn_add = None
        if extra_btn:
            self.btn_add = QToolButton(self)
            self.btn_add.setText("+")
            self.btn_add.setAutoRaise(True)
            self.btn_add.setFixedSize(18, 18)
            self.btn_add.setObjectName("secAdd")
            head.addWidget(self.btn_add)
        lay.addLayout(head)

        self.body = QWidget(self)
        self.body_lay = QVBoxLayout(self.body)
        self.body_lay.setContentsMargins(4, 0, 0, 4)
        self.body_lay.setSpacing(5)
        lay.addWidget(self.body)

    def row(self, *widgets, spacing=5):
        h = QHBoxLayout()
        h.setSpacing(spacing)
        for w in widgets:
            if w is None:
                h.addStretch(1)
            else:
                h.addWidget(w)
        h.addStretch(1)
        self.body_lay.addLayout(h)
        return h

    def toggle(self):
        self._open = not self._open
        self.body.setVisible(self._open)
        self.btn_toggle.setArrowType(Qt.DownArrow if self._open else Qt.RightArrow)


class _PanelBody(QWidget):
    """属性面板的内容容器：**最小尺寸声明为 0**。

     的实现是直接加上
    ，**根本不看 sizePolicy** —— 所以想让
    "滚动区不跟着内容长"，只能从内容控件这头覆写。

    为什么非做不可：面板内容实测 222x830，会让滚动区、右栏、QSplitter、
    页面、主窗口的最小尺寸一路被顶到 1440x889。窗口比屏幕还大，下边缘跑到
    屏幕外，用户的原话就是"左右、对角依旧无法""只能拉顶部，底部调不了"。
    """

    def minimumSizeHint(self):
        return QSize(0, 0)


class SubtitlePropsPanel(QWidget):
    """「字幕属性」面板（版式复刻剪映右侧属性栏）。

    右栏不再保留任何字幕框：**字幕本身在画面上直接操作**——点它选中、拖它
    移位、双击就地改字（见 `subtitle_overlay.SubtitleStage`）。这里只管外观，
    两边共用同一份样式字典，改哪边都是改同一份数据。
    """

    style_changed = pyqtSignal(dict)
    step_requested = pyqtSignal(int)
    #: 点标题行的「导出」：把当前字幕导出成 SRT / ASS 文件。
    #: 面板只管发信号，落盘逻辑在页面（SubtitlEditPage.export_subtitle）——
    #: 那边才拿得到完整 doc、样式字典与文件对话框的父窗口。
    export_requested = pyqtSignal()

    #: 对齐九宫格（小键盘布局，与 ASS 的 Alignment 一致）
    ALIGN_CELLS = ((7, "↖"), (8, "↑"), (9, "↗"),
                   (4, "←"), (5, "·"), (6, "→"),
                   (1, "↙"), (2, "↓"), (3, "↘"))
    ALIGN_TIPS = {1: "左下", 2: "底部居中", 3: "右下", 4: "左中", 5: "正中",
                  6: "右中", 7: "左上", 8: "顶部居中", 9: "右上"}
    #: 九宫格单格边长（px）＋格间距：缩到 26 才腾得出横向空间，
    #: 把「垂直距 / 水平距 / 横向 / 纵向 / 描边」五个数值框并到同一排。
    ALIGN_BTN_PX = 26
    ALIGN_GAP_PX = 3
    #: 轨道样式：ASS 没有轨道概念，这里只做版式占位
    TRACK_STYLES = ("无",)

    def __init__(self, parent=None):
        super().__init__(parent)
        # props_qss 给根容器写了 background —— 普通 QWidget 不开这个属性
        # 就不画样式表背景（深色下面板会透出浅色窗口底，浅字全看不清）
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._loading = False
        self._index = -1
        self._build()

    def minimumSizeHint(self):
        """右栏能多窄多矮由 setMinimumWidth 说了算，不由内容决定。

        不覆写的话最小尺寸会顺着"滚动区 → body → 里头的控件"一路传到
        QSplitter、页面、主窗口，窗口就缩不动（详见 _build 里的注释）。
        """
        ms = self.minimumSize()
        return ms if ms.width() > 0 else super().minimumSizeHint()

    # ---------- 构建 ----------
    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        body = _PanelBody(self)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(10, 4, 10, 8)
        lay.setSpacing(6)

        area = QScrollArea(self)
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        area.setWidget(body)
        outer.addWidget(area)
        # ⚠️ 这两行是"窗口能不能自由缩放"的关键：
        #     取的是**内容控件**的
        #    minimumSizeHint —— 面板内容有 830 高 / 570 宽，于是右栏（下面那句
        #    setMinimumWidth(292) 形同虚设）把 QSplitter 顶到 850 宽、把页面顶到
        #    898、最后把主窗口顶到 1440x889。窗口比屏幕还大，下边缘跑到屏幕外，
        #    用户看到的就是"左右、对角都拖不动，只能拉顶部"。
        #    把 body 的垂直策略设为 Ignored + 给滚动区一个我们自己的最小尺寸，
        #    滚动区就只按这里声明的尺寸说话。
        body.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Ignored)
        area.setMinimumSize(180, 100)
        # 292 = 文字与控件在窄栏里还放得下的下限（横向滚动条是关掉的）
        self.setMinimumWidth(292)

        # ---- 标题行：属性 / 当前条序号 / 上下条 ----
        top = QHBoxLayout()
        top.setSpacing(6)
        self.lbl_no = QLabel("属性", self)
        f = self.lbl_no.font()
        f.setBold(True)
        self.lbl_no.setFont(f)
        self.lbl_meta = QLabel("", self)
        self.lbl_meta.setObjectName("propMeta")
        self.lbl_meta.setMinimumWidth(0)
        self.lbl_meta.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        top.addWidget(self.lbl_no)
        top.addWidget(self.lbl_meta)
        top.addStretch(1)
        self.btn_prev = QPushButton("▲", self)
        self.btn_next = QPushButton("▼", self)
        for b, tip in ((self.btn_prev, "上一条（↑）"), (self.btn_next, "下一条（↓）")):
            b.setFixedWidth(26)
            b.setObjectName("navBtn")
            b.setToolTip(tip)
            top.addWidget(b)
        # 右上角「导出」：当前字幕 -> SRT（纯文本）/ ASS（带面板这套样式）。
        # 走默认 QPushButton 样式（navBtn 那条 font-size:9px 是给 ▲▼ 符号的，
        # 套到汉字上会小得看不清）。
        self.btn_export = QPushButton("导出", self)
        self.btn_export.setToolTip(
            "导出字幕文件：SRT = 纯文本；ASS = 连同右上方面板调的样式一起带走"
            "（不改变当前打开的文件）")
        self.btn_export.clicked.connect(self.export_requested.emit)
        top.addWidget(self.btn_export)
        lay.addLayout(top)

        # ---- 预览行：当前字幕文本（只读回显，编辑在画面上双击）----
        self.lbl_preview = QLabel("（当前时间点没有字幕）", self)
        self.lbl_preview.setWordWrap(True)
        self.lbl_preview.setToolTip("这一行只是回显；改字请在画面上双击字幕")
        lay.addWidget(self.lbl_preview)

        # ================= 轨道样式（占位）=================
        sec_track = _Section("轨道样式", self, extra_btn=True, first=True)
        self.cb_track = QComboBox(self)
        self.cb_track.addItems(self.TRACK_STYLES)
        self.cb_track.setToolTip("ASS 字幕没有「轨道样式」这个概念，这里仅保留版式位置")
        sec_track.row(self.cb_track)
        lay.addWidget(sec_track)

        # ================= 文本 =================
        sec_text = _Section("文本", self)

        self.cb_font = QFontComboBox(self)
        self.cb_font.setMinimumWidth(110)
        self.cb_font.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLength)
        self.cb_font.setMinimumContentsLength(6)
        self.cb_font.setToolTip("画面字幕使用的字体（写进 ASS 的 Fontname）")
        sec_text.body_lay.addWidget(self.cb_font)

        self.cb_weight = QComboBox(self)
        self.cb_weight.addItems(("Regular", "Bold"))
        self.cb_weight.setToolTip("字重：Bold 等同于加粗按钮")
        sec_text.body_lay.addWidget(self.cb_weight)

        # 字形按钮行：B / I / U / S
        self.btn_bold = self._toggle("B", "加粗（Bold）")
        self.btn_ital = self._toggle("I", "斜体（Italic）")
        self.btn_ul = self._toggle("U", "下划线（Underline，仅预览层可见）")
        self.btn_strike = self._toggle("S", "删除线（StrikeOut）")
        for b in (self.btn_bold, self.btn_ital, self.btn_ul, self.btn_strike):
            b.setFixedWidth(26)
        sec_text.row(self.btn_bold, self.btn_ital, self.btn_ul, self.btn_strike,
                     None)

        # 字号：数值 + 滑块
        size_head = QHBoxLayout()
        size_head.setSpacing(5)
        self.sp_size = QSpinBox(self)
        self.sp_size.setRange(10, 200)
        # 76：新输入框皮肤右侧留了 34px 给上下箭头，太小会把三位数裁掉
        self.sp_size.setFixedWidth(84)
        size_head.addWidget(self._label("字体大小"))
        size_head.addStretch(1)
        size_head.addWidget(self.sp_size)
        sec_text.body_lay.addLayout(size_head)
        self.sl_size = QSlider(Qt.Horizontal, self)
        self.sl_size.setRange(10, 200)
        self.sl_size.setToolTip("字号（按 1080p 画面计，实际按画面高度等比缩放）")
        sec_text.body_lay.addWidget(self.sl_size)

        lay.addWidget(sec_text)

        # ================= 对齐与变换 =================
        # 九宫格缩到 26×26（原来 30×24 还单独占一行），右侧**同一排**放五个
        # 数值框：垂直距 / 水平距 / 横向缩放 / 纵向缩放 / 描边宽度。
        # 数值排成「小标签 + 框」两列，不再把 VA / % 这类前后缀塞进同一个
        # 输入框——栏宽被拉窄时（面板最小 292）前后缀会把数字顶掉。
        # 对齐模式状态与「回到对齐」入口收进左列，正好补上九宫格下面的空当。
        sec_pos = _Section("对齐并变换", self)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(self.ALIGN_GAP_PX)
        self.align_btns = {}
        for n, (val, sym) in enumerate(self.ALIGN_CELLS):
            b = QToolButton(self)
            b.setText(sym)
            b.setFixedSize(self.ALIGN_BTN_PX, self.ALIGN_BTN_PX)
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.setToolTip(self.ALIGN_TIPS.get(val, ""))
            grid.addWidget(b, n // 3, n % 3)
            self.align_btns[val] = b
        gwrap = QWidget(self)
        gwrap.setLayout(grid)

        # v1.14.2：画面拖动 = 自由位置。「对齐」九宫格是**一次性**定位（点一次
        # 就把框摆到那个区域），一旦在画面上拖过，位置就脱离对齐规则，得能一键
        # 回到规则模式。文字取短（列宽只有九宫格那么宽），细节交给 tooltip。
        self.lbl_pos = QLabel("跟随对齐", self)
        self.lbl_pos.setObjectName("propCaption")
        self.lbl_pos.setToolTip("「跟随对齐」= 位置由对齐九宫格 + 边距决定；"
                                "在画面上拖动字幕（或拖把手缩放）会变成自由位置")
        self.btn_pos_reset = QToolButton(self)
        self.btn_pos_reset.setText("回到对齐")
        self.btn_pos_reset.setToolTip("清除画面拖动产生的自由位置，"
                                      "让字幕回到「对齐」九宫格 + 边距决定的位置")
        self.btn_pos_reset.setEnabled(False)
        self.btn_pos_reset.setFixedHeight(22)
        self.btn_pos_reset.setSizePolicy(QSizePolicy.Preferred,
                                         QSizePolicy.Fixed)
        self.btn_pos_reset.clicked.connect(self._on_reset_pos)

        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(4)
        left.addWidget(gwrap, 0, Qt.AlignLeft)
        left.addWidget(self.lbl_pos)
        left.addWidget(self.btn_pos_reset)
        left.addStretch(1)
        lwrap = QWidget(self)
        lwrap.setLayout(left)
        # 钉死左列宽度：外层 QWidget 的 sizeHint 会随布局浮动，给死宽度才能
        # 保证九宫格不被右边的数值列挤扁。
        lwrap.setFixedWidth(self.ALIGN_BTN_PX * 3 + self.ALIGN_GAP_PX * 2)

        # 五个数值框：位置（垂直 / 水平）、缩放（横向 / 纵向）、描边宽度。
        # 宽度由布局自适应（原来每个写死 76/58，窄栏里右侧空一大截）。
        self.sp_margin = QSpinBox(self)
        self.sp_margin.setRange(0, 900)
        self.sp_margin.setToolTip("垂直距：字幕距对齐边的距离（ASS 的 MarginV）")
        self.sp_margin_l = QSpinBox(self)
        self.sp_margin_l.setRange(0, 900)
        self.sp_margin_l.setToolTip("水平距：字幕距对齐边的距离"
                                    "（ASS 的 MarginL / MarginR，"
                                    "按对齐方向决定贴哪一边）")
        self.sp_scale_x = QSpinBox(self)
        self.sp_scale_x.setRange(10, 500)
        self.sp_scale_x.setSuffix("%")
        self.sp_scale_x.setToolTip("横向缩放（ASS 的 ScaleX，100% 为原始大小）")
        self.sp_scale_y = QSpinBox(self)
        self.sp_scale_y.setRange(10, 500)
        self.sp_scale_y.setSuffix("%")
        self.sp_scale_y.setToolTip("纵向缩放（ASS 的 ScaleY，100% 为原始大小）")
        self.sp_outline = QSpinBox(self)
        self.sp_outline.setRange(0, 8)
        self.sp_outline.setToolTip("描边宽度（0 = 不描边）")

        nums = QGridLayout()
        nums.setContentsMargins(0, 0, 0, 0)
        nums.setHorizontalSpacing(5)
        nums.setVerticalSpacing(5)
        for i, (lab, box) in enumerate(
                (("垂直距", self.sp_margin), ("水平距", self.sp_margin_l),
                 ("横向", self.sp_scale_x), ("纵向", self.sp_scale_y),
                 ("描边", self.sp_outline))):
            cap = self._label(lab)
            # 小一号的说明字：这五行的标签列宽直接吃掉输入框的宽度，
            # 面板拉到最小（292）时 12px 的三字标签会把 500% 顶掉。
            cap.setObjectName("propNumLab")
            nums.addWidget(cap, i, 0)
            nums.addWidget(box, i, 1)
            box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        nums.setColumnStretch(1, 1)
        nwrap = QWidget(self)
        nwrap.setLayout(nums)
        nwrap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        align_row = QHBoxLayout()
        align_row.setContentsMargins(0, 0, 0, 0)
        align_row.setSpacing(10)
        align_row.addWidget(lwrap, 0, Qt.AlignTop)
        align_row.addWidget(nwrap, 1, Qt.AlignTop)
        sec_pos.body_lay.addLayout(align_row)
        lay.addWidget(sec_pos)

        # ================= 外观 =================
        sec_look = _Section("外观", self)

        self.btn_color = QPushButton(self)
        self.btn_color.setFixedSize(46, 24)
        self.btn_color.setToolTip("填充色：字幕文字本身（ASS 的 PrimaryColour）")
        sec_look.row(self._label("填充"), self.btn_color, None)

        self.btn_outline = QPushButton(self)
        self.btn_outline.setFixedSize(46, 24)
        self.btn_outline.setToolTip("描边色（ASS 的 OutlineColour）")
        sec_look.row(self._label("描边"), self.btn_outline, None)

        self.chk_bg = QCheckBox("背景", self)
        self.chk_bg.setToolTip("给字幕加不透明底框（ASS 的 BorderStyle=3）")
        self.btn_bg = QPushButton(self)
        self.btn_bg.setFixedSize(46, 24)
        self.btn_bg.setToolTip("背景色（ASS 的 BackColour）")
        sec_look.row(self.chk_bg, self.btn_bg, None)

        self.chk_shadow = QCheckBox("阴影", self)
        self.chk_shadow.setToolTip("开启投影（ASS 的 Shadow）")
        self.btn_shadow = QPushButton(self)
        self.btn_shadow.setFixedSize(46, 24)
        self.btn_shadow.setToolTip("阴影颜色（与背景共用 ASS 的 BackColour）")
        self.sp_shadow = QSpinBox(self)
        self.sp_shadow.setRange(0, 20)
        self.sp_shadow.setFixedWidth(72)
        self.sp_shadow.setToolTip("阴影距离（ASS 的 Shadow）")
        sec_look.row(self.chk_shadow, self.btn_shadow, self.sp_shadow, None)
        lay.addWidget(sec_look)

        tip = QLabel("画面上：点一下选中、拖动改位置、拖四角缩放、拖四边拉伸、"
                     "双击就地改字。位置拖过之后与「对齐」无关，"
                     "想回到对齐位置按上面的按钮。", self)
        tip.setWordWrap(True)
        tip.setObjectName("propMeta")
        lay.addWidget(tip)
        lay.addStretch(1)

        # ---------- 信号 ----------
        self.btn_prev.clicked.connect(lambda: self.step_requested.emit(-1))
        self.btn_next.clicked.connect(lambda: self.step_requested.emit(1))
        self.cb_font.currentFontChanged.connect(self._emit)
        self.cb_weight.currentIndexChanged.connect(self._on_weight)
        self.sp_size.valueChanged.connect(self._on_size_spin)
        self.sl_size.valueChanged.connect(self._on_size_slider)
        for b in (self.btn_bold, self.btn_ital, self.btn_ul, self.btn_strike):
            b.toggled.connect(self._emit)
        self.sp_outline.valueChanged.connect(self._emit)
        self.sp_margin.valueChanged.connect(self._emit)
        self.sp_margin_l.valueChanged.connect(self._emit)
        self.sp_scale_x.valueChanged.connect(self._emit)
        self.sp_scale_y.valueChanged.connect(self._emit)
        self.sp_shadow.valueChanged.connect(self._emit)
        for val, b in self.align_btns.items():
            # ⚠️ 不能直连 _emit：autoExclusive 的 QToolButton 点**已选中的格**
            # 会把它取消选中，alignment 回落默认 2——字幕已拖到自由位置时
            # 表现为"点了没反应/字幕乱跳"，必须走专门的定位语义（见下）
            b.clicked.connect(lambda _checked=False, v=val:
                              self._on_align_clicked(v))
        self.chk_bg.toggled.connect(self._emit)
        self.chk_shadow.toggled.connect(self._emit)
        self.btn_color.clicked.connect(lambda: self._pick("color"))
        self.btn_outline.clicked.connect(lambda: self._pick("outline_color"))
        self.btn_bg.clicked.connect(lambda: self._pick("back_color"))
        self.btn_shadow.clicked.connect(lambda: self._pick("back_color"))
        self._paint_color_buttons()
        # 主题感知外观：面板底色/控件 QSS 按当前主题生成；主题档或系统深浅
        # 变化时由 ui_theme 回调重应用（weakref，不拖住本面板回收）
        self._apply_theme()
        import ui_theme
        ui_theme.connect_theme(self, lambda w: w._apply_theme())

    def _apply_theme(self):
        """按当前主题重应用面板样式（深色=深面板，浅色=白面板）。"""
        import ui_theme
        t = ui_theme.tokens()
        accent = ui_theme.get_accent()
        self.setStyleSheet(props_qss(t, accent))
        # 回显条：底色统一走 log_bg（控制台语言，深 #1B1B1B / 浅 #F4F6F8），
        # 有无字幕只差文字色。此前 set_cue 里写死 #232323 深底，每次刷新都把
        # 主题样式盖回深色——浅色主题下就是那块突兀的黑框（用户截图反馈）。
        self.lbl_preview.setStyleSheet(
            self._preview_qss(getattr(self, "_index", -1) < 0))
        # 字体下拉不再单独写样式：ui_theme.build_app_qss() 的 combo 组已经把
        # QFontComboBox（含弹出列表、箭头、hover）一起管了——同一种控件全应用
        # 一套皮肤，避免"面板里一个样、别处又一个样"。
        self._paint_color_buttons()

    def _preview_qss(self, dim=True):
        """字幕回显条样式（主题感知）：`dim`=无字幕时的弱化文字色。"""
        import ui_theme
        t = ui_theme.tokens()
        return (f"color:{t['text_dim'] if dim else t['text']};"
                f"background:{t['log_bg']};"
                f"border:1px solid {t['border']};border-radius:4px;"
                "padding:4px 6px;")

    def _label(self, text):
        lb = QLabel(text, self)
        lb.setObjectName("propMeta")
        return lb

    def _toggle(self, text, tip):
        b = QToolButton(self)
        b.setText(text)
        b.setCheckable(True)
        b.setToolTip(tip)
        f = b.font()
        f.setBold(text == "B")
        f.setItalic(text == "I")
        b.setFont(f)
        return b

    # ---------- 颜色 ----------
    def _pick(self, key):
        cur = QColor(str(self.current_style().get(key) or "#FFFFFF"))
        title = {"color": "填充色", "outline_color": "描边色",
                 "back_color": "背景 / 阴影色"}.get(key, "选择颜色")
        dlg = themed_color_dialog(cur, self, title)
        if dlg.exec_() != QColorDialog.Accepted:
            return
        col = dlg.currentColor()
        if not col.isValid():
            return
        self._colors[key] = col.name().upper()
        self._paint_color_buttons()
        self._emit()

    def _paint_color_buttons(self):
        """四个色块按钮刷上当前颜色（**带外描边**：纯白/纯黑色块也要看得见）。"""
        st = self.current_style()
        import ui_theme
        t = ui_theme.tokens()
        accent = ui_theme.get_accent()
        pairs = (("color", self.btn_color), ("outline_color", self.btn_outline),
                 ("back_color", self.btn_bg), ("back_color", self.btn_shadow))
        for key, btn in pairs:
            c = str(st.get(key) or ("#000000" if key == "back_color" else "#FFFFFF"))
            btn.setStyleSheet(
                f"QPushButton{{background:{c};"
                f"border:1px solid {t['border_hover']};border-radius:6px;}}"
                f"QPushButton:hover{{border:2px solid {accent};}}"
                f"QPushButton:pressed{{border:2px solid {accent};}}")

    # ---------- 内容 ----------
    def set_cue(self, cue, idx, total):
        """回显当前时间点的字幕（文本只预览，改字在画面上双击）。"""
        self._index = idx
        if cue is None:
            self.lbl_meta.setText("· 无字幕（共 %d 条）" % total)
            self.lbl_preview.setText("（当前时间点没有字幕）")
            self.lbl_preview.setStyleSheet(self._preview_qss(True))
        else:
            self.lbl_meta.setText("· %d/%d · %.2fs"
                                  % (idx + 1, total, cue.duration / 1000.0))
            self.lbl_preview.setText("C1:字幕  " + (cue.text or "").replace("\n", " "))
            self.lbl_preview.setStyleSheet(self._preview_qss(False))

    def current_style(self):
        align = 2
        for val, b in self.align_btns.items():
            if b.isChecked():
                align = val
                break
        cols = getattr(self, "_colors", {})
        shadow = self.sp_shadow.value() if self.chk_shadow.isChecked() else 0
        st = {
            "font": self.cb_font.currentFont().family(),
            "size": self.sp_size.value(),
            "bold": self.btn_bold.isChecked(),
            "italic": self.btn_ital.isChecked(),
            "underline": self.btn_ul.isChecked(),
            "strikeout": self.btn_strike.isChecked(),
            "color": cols.get("color", "#FFFFFF"),
            "outline_color": cols.get("outline_color", "#000000"),
            "outline": self.sp_outline.value(),
            "back_color": cols.get("back_color", "#000000"),
            "border_style": 3 if self.chk_bg.isChecked() else 1,
            "shadow": shadow,
            "alignment": align,
            "margin_v": self._real_val(self.sp_margin, "_va", 40),
            "margin_l": self._real_val(self.sp_margin_l, "_ha", 10),
            "margin_r": self._real_val(self.sp_margin_l, "_ha", 10),
            "scale_x": self.sp_scale_x.value(),
            "scale_y": self.sp_scale_y.value(),
        }
        # 自由位置模式下，两个位置框的语义是**几何原点**（框左 x / 框顶 y）：
        # 用户改动了框 = 要求按原点精确定位 → 直接写 pos_x/pos_y；margin 维持
        # 原真实值（不然"回到对齐"会把坐标值当边距，位置乱跳）
        if getattr(self, "_free_pos", False) and (
                int(self.sp_margin.value()) != int(getattr(self, "_va_shown", -1))
                or int(self.sp_margin_l.value()) != int(getattr(self, "_ha_shown", -1))):
            st["margin_v"] = int(getattr(self, "_va_real", 40))
            st["margin_l"] = int(getattr(self, "_ha_real", 10))
            st["margin_r"] = int(getattr(self, "_ha_real", 10))
            st["pos_x"] = int(self.sp_margin_l.value())
            st["pos_y"] = int(self.sp_margin.value())
        return st

    def _real_val(self, spin, prefix, default):
        """面板读数 vs 真实值的取舍。

        自由位置模式下，`sp_margin` / `sp_margin_l` 显示的是**折算出来的
        等效边距**（画面拖动时实时变化），并不是样式里的 margin_*。所以：

          · 用户没动过这个框（值仍等于显示值）→ 上报**真实值**，别把显示用的
            折算值当成用户输入（否则改颜色都会被判定成"改了位置"）；
          · 用户动了 → 那就是明确的输入，按输入值上报（同时自由位置作废，
            回到规则定位，符合"输入边距 = 用规则定位"的直觉）。
        """
        cur = int(spin.value())
        if cur == int(getattr(self, prefix + "_shown", default)):
            return int(getattr(self, prefix + "_real", default))
        return cur

    def set_style(self, style):
        self._loading = True
        try:
            st = dict(style or {})
            self._colors = {
                "color": str(st.get("color") or "#FFFFFF").upper(),
                "outline_color": str(st.get("outline_color") or "#000000").upper(),
                "back_color": str(st.get("back_color") or "#000000").upper(),
            }
            fam = str(st.get("font") or "Microsoft YaHei")
            if fam and self.cb_font.currentFont().family() != fam:
                self.cb_font.setCurrentFont(QFont(fam))
            self.cb_weight.setCurrentIndex(1 if st.get("bold") else 0)
            self.sp_size.setValue(int(st.get("size", 46)))
            self.sl_size.setValue(int(st.get("size", 46)))
            self.sp_outline.setValue(int(st.get("outline", 2)))
            # 「垂直距 / 水平距」两种来源：
            #   · 跟随对齐模式 → 样式里的 margin_v / margin_l 本身就是它；
            #   · 自由位置模式 → 画面上拖过之后，stage 按框的实际几何折算成
            #     等效边距放在 _va / _ha 里传进来，面板照它显示（这样拖动时
            #     数字才跟着动）。但要**同时记住真实值**：用户没动过这个框时
            #     上报的仍是原始 margin_v/l —— 否则"拖好位置再改个颜色"会被
            #     当成"改了位置"而把自由位置丢掉。
            self._va_shown = int(st.get("_va", st.get("margin_v", 40)))
            self._va_real = int(st.get("margin_v", 40))
            self._ha_shown = int(st.get("_ha", st.get("margin_l", 10)))
            self._ha_real = int(st.get("margin_l", 10))
            self.sp_margin.setValue(self._va_shown)
            self.sp_margin_l.setValue(self._ha_shown)
            self.sp_scale_x.setValue(int(st.get("scale_x", 100)))
            self.sp_scale_y.setValue(int(st.get("scale_y", 100)))
            self.btn_bold.setChecked(bool(st.get("bold")))
            self.btn_ital.setChecked(bool(st.get("italic")))
            self.btn_ul.setChecked(bool(st.get("underline")))
            self.btn_strike.setChecked(bool(st.get("strikeout")))
            bg = int(st.get("border_style", 1) or 1) == 3
            self.chk_bg.setChecked(bg)
            sh = int(st.get("shadow", 0) or 0)
            self.chk_shadow.setChecked(sh > 0)
            self.sp_shadow.setValue(sh)
            align = int(st.get("alignment", 2))
            b = self.align_btns.get(align) or self.align_btns.get(2)
            if b is not None:
                b.setChecked(True)
            self._set_pos_state(st)
            self._paint_color_buttons()
        finally:
            self._loading = False

    def _set_pos_state(self, style):
        """刷新「位置：跟随对齐 / 已自定义」状态与回退按钮可用性。

        文案取短（左列只有九宫格那么宽，最长四字），完整语义在 tooltip 里。
        """
        free = (style.get("pos_x") is not None and style.get("pos_y") is not None)
        self._free_pos = free
        self.lbl_pos.setText("已自定义" if free else "跟随对齐")
        self.btn_pos_reset.setEnabled(bool(free))
        # 自由位置下这两个框换了读数基准：**几何原点**（框左上角到画面
        # 左/顶边的 PlayRes 坐标）——拖动、缩放、手输都以原点为准；
        # 跟随对齐时仍是 MarginV/L（距对齐边，与对齐规则联动）。
        if free:
            self.sp_margin.setToolTip("垂直位置：字幕框**顶边**到画面顶部的"
                                      "距离（几何原点 y，1080p 坐标），"
                                      "手输可精确定位")
            self.sp_margin_l.setToolTip("水平位置：字幕框**左边**到画面左侧的"
                                        "距离（几何原点 x，1080p 坐标），"
                                        "手输可精确定位")
            # 原点坐标的量程是整个画面（PlayRes 1920x1080）——沿用的 900
            # 上限会把大坐标手输钳掉
            self.sp_margin.setRange(0, 1080)
            self.sp_margin_l.setRange(0, 1920)
        else:
            self.sp_margin.setToolTip("垂直位置：字幕距对齐边的距离（ASS 的 MarginV）")
            self.sp_margin_l.setToolTip("水平位置（ASS 的 MarginL / MarginR，"
                                        "按对齐方向决定贴哪一边）")
            self.sp_margin.setRange(0, 900)
            self.sp_margin_l.setRange(0, 900)

    def _on_reset_pos(self):
        """回到对齐位置：显式把自由位置清成 None 上报。

        ⚠️ 必须显式带 `pos_x/pos_y=None` 两个键：页面只有在样式里**显式**
        出现这两个键时才认定"用户要求清位置"，否则它会把已拖好的自由位置
        原样保留（那是"改字号别把位置弄丢"的保护）。
        """
        st = self.current_style()
        st["pos_x"] = None
        st["pos_y"] = None
        self.style_changed.emit(st)

    # ---------- 联动 ----------
    def _on_align_clicked(self, val):
        """九宫格点击 = **把字幕摆到该区域**（清自由位置，重新定位）。

        ⚠️ autoExclusive 的 QToolButton 点**已选中的格**会把它取消选中——
        若直连 _emit，alignment 会回落默认 2 且样式可能毫无变化，表现就是
        用户看到的「字幕拖动后再点对齐没反应 / 先消失再出现」两拍行为。
        这里统一兜住：
          · 点完把该格**重新 setChecked**（被 autoExclusive 取消了就拉回来，
            组内其它格自然被顶掉）；
          · 样式**显式**带 pos_x/pos_y=None——页面据此清自由位置，让本次
            对齐立即生效（与「回到对齐」按钮同一语义）。
        """
        if self._loading:
            return
        b = self.align_btns.get(val)
        if b is not None and not b.isChecked():
            b.setChecked(True)
        st = self.current_style()
        st["pos_x"] = None
        st["pos_y"] = None
        self.style_changed.emit(st)

    def _on_weight(self, idx):
        if self._loading:
            return
        self.btn_bold.setChecked(idx == 1)   # 由 _emit 统一上报
        self._emit()

    def _on_size_slider(self, v):
        if not self._loading and self.sp_size.value() != v:
            self.sp_size.setValue(v)

    def _on_size_spin(self, v):
        if not self._loading and self.sl_size.value() != v:
            self.sl_size.setValue(v)
        self._emit()

    def _emit(self, *_a):
        if self._loading:
            return
        self.style_changed.emit(self.current_style())
