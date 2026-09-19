# -*- coding: utf-8 -*-
# @version 1.15.4
"""视频画面上的**字幕层**：可点选、可拖动、可就地改字。

为什么要自己开一个窗口
----------------------
播放器是 `MPV(wid=hwnd)` 嵌进来的**原生子窗口**。Windows 上：

  · 同一个父窗口里的 **非原生** Qt 控件，绘制结果被原生子窗口整个盖住
    （父窗口的绘制内容永远在子窗口之下），所以普通浮层看不见；
  · 而**原生子窗口**又拿不到透明背景（`WA_TranslucentBackground` 在
    Windows 上只对 **顶层窗口** 生效）。

两条路都堵死，于是只剩一条：让字幕层成为一个**顶层无边框透明窗口**，
贴着视频区摆放。顶层窗口天然在原生子窗口之上，透明和鼠标事件都正常。
代价是要自己跟着视频区同步几何（60ms 定时器 + host 的 resize 事件）。

挡不挡主窗口（很重要）
-------------------------
本层是顶层窗口，会参与鼠标命中测试。所以：**几何贴视频画面**（下面讲），
但 **mask 只覆盖"字幕块 + 余量"**——字幕之外的点/拖都回到主窗口，否则
拖窗口边框、拉分割条这些操作会被它吃掉（用户报的"放入视频后无法自由
调整页面"就是这个）。另外主窗口正在被拖拽时**不做几何同步**：本层每次
setGeometry 都是一次 SetWindowPos，插进系统的缩放模态循环会把它打断。

和 mpv 的分工
-------------
字幕预览**改由本层渲染**（`MpvPlayer` 不再 sub-add），因为要支持"点中它、
拖它"。样式参数与 `subtitle_editor_core.render_ass` 用的是**同一份字典**
（font / size / color / outline / alignment / margin_*），所以画面上看到的
就是导出成 ASS 时的样子。

坐标基准沿用 ASS 的老规矩：样式是相对 **PlayRes 1920x1080** 给的，绘制时
按 `画面高度 / 1080` 等比缩放。
"""
import sys
import time

from PyQt5.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import (QColor, QFont, QFontMetricsF, QPainter, QPainterPath,
                         QPen, QRegion)
from PyQt5.QtWidgets import QApplication, QTextEdit, QWidget

ASS_PLAY_RES_Y = 1080.0

#: 选中框与把手
C_SEL = QColor("#45C877")
C_SEL_SOFT = QColor(69, 200, 119, 90)

HANDLE = 7          # 把手边长（逻辑像素）
HANDLE_HIT = 9      # 把手命中半径：比画出来的略大一圈，小方块才好点
HIT_PAD = 6         # 命中测试外扩，太薄的字幕不好点
MASK_PAD = 18       # 窗口 mask 在字幕块外扩这么多，让选框/把手/拖动都够用

#: 缩放的夹取范围（相对按下那一刻的取值）
ZOOM_MIN = 0.15
ZOOM_MAX = 6.0

#: 8 个把手（小键盘方位）及其鼠标指针
HANDLE_CURSORS = {
    "nw": Qt.SizeFDiagCursor, "se": Qt.SizeFDiagCursor,
    "ne": Qt.SizeBDiagCursor, "sw": Qt.SizeBDiagCursor,
    "n": Qt.SizeVerCursor, "s": Qt.SizeVerCursor,
    "w": Qt.SizeHorCursor, "e": Qt.SizeHorCursor,
}


class _InlineEdit(QTextEdit):
    """就地编辑框：Enter 提交、Shift+Enter 换行、Esc 取消。"""

    submitted = pyqtSignal(bool)     # True=提交，False=取消

    def keyPressEvent(self, ev):
        if ev.key() in (Qt.Key_Return, Qt.Key_Enter) and not (
                ev.modifiers() & Qt.ShiftModifier):
            self.submitted.emit(True)
            return
        if ev.key() == Qt.Key_Escape:
            self.submitted.emit(False)
            return
        super().keyPressEvent(ev)

    def focusOutEvent(self, ev):
        super().focusOutEvent(ev)
        self.submitted.emit(True)


class SubtitleStage(QWidget):
    """贴在视频区上的透明字幕层。

    信号：
      · `cue_clicked(idx)`       —— 点中某条字幕（页面据此同步选中态）
      · `selection_cleared()`    —— 点到空白处，取消选中
      · `text_committed(idx, t)` —— 就地改字提交
      · `layout_changed(dict)`   —— 拖动/缩放**松手**后，回传最终样式字典
      · `layout_preview(dict)`   —— 拖动/缩放**过程中**的节流回调，给属性面板
                                    做实时读数（不落盘、不重建预览）
      · `play_toggled()`         —— 双击空白 = 播放/暂停（视频区本来就没有
                                    别的鼠标交互，顺手补上，免得浮层白吃事件）

两种版式模式（v1.14.2）
----------------------
  · **跟随对齐**（`pos_x/pos_y` 为空）：位置由 `alignment` + `margin_*` 决定，
    改字号或文本后位置自动重算，是"规则驱动"的模式；
  · **自由位置**（`pos_x/pos_y` 有值）：字幕块左上角按 PlayRes(1080) 坐标钉住，
    与对齐设置无关。

用户拖一下字幕（或拖把手缩放）就从前者切到后者——这正是需求里的
「位置调整是一次性的」：属性面板点一次对齐只是把框**摆到**那个区域，
之后怎么拖都不会再被对齐设置拉回去（`layout_changed` 只改 pos，不动
alignment/margin）。
    """

    cue_clicked = pyqtSignal(int)
    #: 拖动某条字幕时的"主选中跟随"：与 cue_clicked 的区别是**不清多选**——
    #: 全选（Ctrl+A）后拖画面字幕，多选集合必须原样保留（页面据此处理）
    cue_followed = pyqtSignal(int)
    delete_requested = pyqtSignal(int)
    selection_cleared = pyqtSignal()
    text_committed = pyqtSignal(int, str)
    layout_changed = pyqtSignal(dict)
    layout_preview = pyqtSignal(dict)
    play_toggled = pyqtSignal()
    #: 本层是**独立顶层窗口**：点画面上的字幕后激活权在本层，主窗口失活，
    #: 主窗的 QShortcut（WidgetWithChildren）全部收不到——Del 删不掉、
    #: Ctrl+Z/Y 无效。keyPressEvent 把按键翻成命令名交页面执行。
    command_requested = pyqtSignal(str)

    def __init__(self, host, parent_window, rect_provider=None):
        super().__init__(parent_window,
                         Qt.Tool | Qt.FramelessWindowHint
                         | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setWindowTitle("字幕层")

        self.host = host
        #: 回调：返回「视频在宿主控件里的**实际显示矩形**」（相对宿主，逻辑像素）。
        #: 视频有黑边时（竖屏、异形比例），整块宿主里只有中间一块是画面，
        #: 字幕层必须贴画面，否则选框和真实字幕对不上。
        self._rect_provider = rect_provider
        self.cues = []
        self.ass_style = {}
        self.position_ms = 0
        self.selected = -1

        self._editor = None
        self._edit_index = -1
        self._drag = None          # (起点 QPoint, 相对起点的位移 QPoint)
        self._press_idx = -1       # 按下命中的字幕（松手时区分"点一下/拖动"）
        self._press_moved = False  # 本次按住是否超过了拖动阈值
        self._resize = None        # 缩放中的上下文 dict（见 mousePressEvent）
        #: 拖动的**基准**：按下那一刻的样式与字幕矩形。
        #: ⚠️ 必须缓存，不能每帧拿"当前值"当基准——那样每个 mouseMove 都会
        #:    在上一帧结果上再叠一次位移，拖一点点字幕就冲到画面另一头
        #:    （e2e 实测：向上拖 60px 把 margin_v 从 40 顶到上限 600）。
        self._drag_style0 = None
        self._drag_rect0 = None
        self._rects = []           # [(idx, QRectF)]，本帧画出来的字幕矩形（命中用）
        self._mask = QRegion()     # 当前窗口 mask（只覆盖字幕块附近）
        self._pending_snap = False  # 强制补一次几何同步（跨屏/DPI 变化用）
        self._preview_t0 = 0.0     # 上一次发实时读数的时刻（节流用）

        # 顶层窗口不会自动跟着宿主走：主窗口拖动 / 分割条拖动 / 页面切换
        # 都不会给本窗口发事件，只能轮询对齐。60ms 在肉眼看来是"跟得上"的。
        self._track = QTimer(self)
        self._track.setInterval(60)
        self._track.timeout.connect(self._sync_geometry)

    # ---------------------------------------------------------
    # 数据
    # ---------------------------------------------------------
    def set_cues(self, cues):
        self.cues = cues or []
        self.update()

    def set_style(self, style):
        # ⚠️ 属性名不能叫 `style`：那会覆盖 `QWidget.style()`（Qt 内部要靠它
        #    取 QStyle），后果是**进程原生崩溃 0xC0000409 且没有任何 traceback**。
        self.ass_style = dict(style or {})
        self.update()

    def set_position(self, ms):
        ms = max(0, int(ms))
        if ms != self.position_ms:
            self.position_ms = ms
            if self._editor is None:       # 编辑中不要被播放头刷掉
                self.update()

    def set_selected(self, idx):
        if idx != self.selected:
            self.selected = idx
            self.update()

    # ---------------------------------------------------------
    # 几何跟随
    # ---------------------------------------------------------
    def _user_is_dragging(self):
        """用户是否正在拖拽（拖主窗口边框 / 拖分割条 / 拖字幕）。

        这个判断是「放入视频后窗口拖不动」的正解：本层是顶层窗口，每次
        `setGeometry` 都是一次 `SetWindowPos`；在系统自己的"拖边框改大小"
        模态循环里插进来会把它打断，用户看到的就是拖拽失步、拖不动。
        判据两层，任一成立就让路：
          · Qt 侧还有鼠标键按着（拖分割条、拖字幕、拖窗口）；
          · Windows 把鼠标捕获交给了主窗口（系统正在拖它的边框）。
        """
        try:
            if QApplication.mouseButtons() != Qt.NoButton:
                return True
        except Exception:  # noqa: BLE001
            pass
        if sys.platform == "win32":
            try:
                import win32gui

                win = self.window()
                if win is not None and win32gui.GetCapture() == int(win.winId()):
                    return True
            except Exception:  # noqa: BLE001
                pass
        return False

    def _apply_mask(self):
        """把窗口收紧成"字幕块 + 余量"。

        为什么非做不可：本层是**顶层窗口**，Windows 上整个矩形都参与命中
        测试。覆盖整块画面时，凡是与它重叠的主窗口操作都会失灵（贴边时的
        窗口拖拽、正好压在画面边缘的分割条……）。收紧之后，字幕之外的区域
        压根不属于本窗口，鼠标消息自然回到主窗口，副作用归零。
        没有可见字幕时收成 1x1：视觉上等同于隐藏，但不用反复 show/hide。
        """
        if self._gesture_active() or self._editor is not None:
            return                 # 拖动/缩放/编辑期间不折腾窗口形状（见 mousePressEvent）
        region = QRegion()
        for _i, r in self._rects:
            box = r.adjusted(-MASK_PAD, -MASK_PAD, MASK_PAD, MASK_PAD).toRect()
            region = region.united(QRegion(box))
        if region.isEmpty():
            region = QRegion(QRect(0, 0, 1, 1))
        if region != self._mask:
            self._mask = region
            self.setMask(region)

    def _sync_geometry(self):
        try:
            if not self.isVisible() or not self.host or not self.host.isVisible():
                return
            if self._user_is_dragging() and not self._pending_snap:
                return                 # 让路，别打断系统/用户的拖拽
            self._pending_snap = False
            tl = self.host.mapToGlobal(QPoint(0, 0))
            if self._rect_provider is not None:
                local = self._rect_provider()
            else:
                local = QRect(0, 0, self.host.width(), self.host.height())
            if local.width() < 8 or local.height() < 8:
                return
            want = QRect(tl.x() + local.x(), tl.y() + local.y(),
                         local.width(), local.height())
            if self.geometry() != want:
                # 换位置/尺寸前必须先清 mask：上一帧收紧过的 region 会让
                # 新位置画不出来，而画不出来就永远算不出新 mask（死锁）。
                self.clearMask()
                self.setGeometry(want)
                self.update()
        except Exception:  # noqa: BLE001
            pass

    def show_over(self):
        """显示并对齐到视频区（幂等）。

        ⚠️ 必须**先 show 再对齐**：`_sync_geometry` 开头会检查 `isVisible()`，
        反过来写的话首次显示时几何压根不会被设置，窗口会停在旧位置。
        """
        if not self.isVisible():
            self.show()
            self.raise_()
            self._sync_geometry()
            self.update()
        self._track.start()

    def snap_to_host(self):
        """立刻重新贴合宿主（跨屏 / DPI 变化后用；跳过 60ms 轮询的门控）。"""
        try:
            self._pending_snap = True
            self._sync_geometry()
            self.update()
        except Exception:  # noqa: BLE001
            pass

    def hide_stage(self):
        self._track.stop()
        self._cancel_edit()
        self._drag = None          # 半途隐藏：手势状态一并清掉，别留给下次
        self._resize = None
        self._drag_style0 = None
        self._drag_rect0 = None
        if self.isVisible():
            self.hide()

    # ---------------------------------------------------------
    # 绘制
    # ---------------------------------------------------------
    def _scale(self):
        """PlayRes(1080) → 实际画面的缩放比。"""
        h = max(1, self.height())
        return h / ASS_PLAY_RES_Y

    def _font_for(self, style):
        f = QFont(str(style.get("font") or "Microsoft YaHei"))
        # 纵向缩放（ScaleY）作用在字号上，横向缩放（ScaleX）用字体 stretch
        px = float(style.get("size", 46)) * self._scale()
        f.setPixelSize(max(6, int(round(px * float(style.get("scale_y", 100) or 100)
                                        / 100.0))))
        f.setStretch(max(10, min(400, int(round(float(
            style.get("scale_x", 100) or 100))))))
        f.setBold(bool(style.get("bold")))
        f.setItalic(bool(style.get("italic")))
        if style.get("underline"):
            f.setUnderline(True)
        if style.get("strikeout"):
            f.setStrikeOut(True)
        return f

    def _block_metrics(self, text, style):
        """文字块尺寸（屏幕像素）→ (宽, 高)；无可见文字给 (0, 0)。

        文本里的 `\\n` 是**手动换行**（预览层不自动折行），所以行数固定、
        宽高与字号严格成正比——拖动把手时「框跟手」才成立。
        """
        if not (text or "").strip():
            return 0.0, 0.0
        fm = QFontMetricsF(self._font_for(style))
        lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        widths = [fm.width(ln) for ln in lines]
        return (max(widths) if widths else 0.0), fm.height() * len(lines)

    def _block_origin(self, style, block_w, block_h):
        """文字块左上角（屏幕像素）。

        优先用自由位置 `pos_x` / `pos_y`（按 PlayRes 1080 坐标 × 当前缩放）；
        两者为空才退回 ASS 的 alignment + margin 规则。
        """
        scale = self._scale()
        px, py = style.get("pos_x"), style.get("pos_y")
        if px is not None and py is not None:
            return float(px) * scale, float(py) * scale
        w, h = float(self.width()), float(self.height())
        align = int(style.get("alignment", 2) or 2)
        align = min(9, max(1, align))
        row = (align - 1) // 3          # 0=底部 1=居中 2=顶部
        col = (align - 1) % 3           # 0=左 1=中 2=右
        mv = float(style.get("margin_v", 40)) * scale
        ml = float(style.get("margin_l", 10)) * scale
        mr = float(style.get("margin_r", 10)) * scale

        if col == 0:
            left = ml
        elif col == 1:
            left = (w - block_w) / 2.0
        else:
            left = w - mr - block_w
        if row == 0:
            top = h - mv - block_h
        elif row == 1:
            top = (h - block_h) / 2.0
        else:
            top = mv
        return left, top

    def _layout_one(self, painter, text, style):
        """按当前样式算出文字块矩形并绘制。

        返回文字块的 QRectF（未命中任何文字时返回 None）。
        """
        block_w, block_h = self._block_metrics(text, style)
        if block_w <= 0 or block_h <= 0:
            return None
        font = self._font_for(style)
        fm = QFontMetricsF(font)
        lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        widths = [fm.width(ln) for ln in lines]
        line_h = fm.height()
        scale = self._scale()
        left, top = self._block_origin(style, block_w, block_h)
        col = (min(9, max(1, int(style.get("alignment", 2) or 2))) - 1) % 3

        path = QPainterPath()
        y = top + fm.ascent()
        for ln, lw in zip(lines, widths):
            if col == 0:
                x = left
            elif col == 1:
                x = left + (block_w - lw) / 2.0
            else:
                x = left + block_w - lw
            if ln:
                path.addText(x, y, font, ln)
            y += line_h

        outline = float(style.get("outline", 2) or 0) * scale

        # —— 背景底框（BorderStyle=3）与阴影：都画在文字之下 ——
        if not path.isEmpty():
            border_style = int(style.get("border_style", 1) or 1)
            if border_style == 3 and block_w > 0:
                pad = outline + 2.0 * scale
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(str(style.get("back_color") or "#000000")))
                painter.drawRect(QRectF(left - pad, top - pad,
                                        block_w + 2 * pad, block_h + 2 * pad))
            shadow = float(style.get("shadow", 0) or 0) * scale
            if shadow > 0:
                off = QPainterPath()
                off.addPath(path.translated(shadow, shadow))
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(str(style.get("back_color") or "#000000")))
                painter.drawPath(off)

        if outline > 0 and not path.isEmpty():
            pen = QPen(QColor(str(style.get("outline_color") or "#000000")))
            pen.setWidthF(outline * 2.0)     # ASS 的 Outline 是单边宽度，笔宽要翻倍
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)
        if not path.isEmpty():
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(str(style.get("color") or "#FFFFFF")))
            painter.drawPath(path)
        return QRectF(left, top, block_w, block_h)

    def _visible_cues(self):
        pos = self.position_ms
        return [(i, c) for i, c in enumerate(self.cues)
                if c.start <= pos < c.end and (c.text or "").strip()]

    def paintEvent(self, _ev):
        p = QPainter(self)
        # ⚠️ 必须**显式清空**：本层带 `WA_TranslucentBackground`，它隐含
        #    `WA_NoSystemBackground`（不要用系统背景擦除）。少了这一步，上一帧
        #    的字形会残留，新字幕叠着旧字幕画——用户看到的就是"点过的字幕一直
        #    留在屏幕上、不随时间轴变化，每条字幕像独立的一块"。
        p.setCompositionMode(QPainter.CompositionMode_Clear)
        p.fillRect(self.rect(), Qt.transparent)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        self._rects = []
        for i, c in self._visible_cues():
            r = self._layout_one(p, c.text, self.ass_style)
            if r is not None:
                self._rects.append((i, r))
        # 选中框画在所有文字之上：它就是一个"独立区块"的可视边界
        for i, r in self._rects:
            if i == self.selected:
                self._paint_selection(p, r)
                break
        # 本帧的字幕矩形出来了 → 同步收紧窗口 mask（见 _apply_mask 的说明）
        self._apply_mask()

    def _paint_selection(self, p, r):
        box = self._selection_box(r)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(C_SEL, 1.5, Qt.DashLine))
        p.drawRect(box)
        p.setPen(QPen(C_SEL, 1))
        p.setBrush(C_SEL)
        # 8 个把手：四角等比缩放字号，四边单向拉伸（与面板的 ScaleX/Y 同源）
        for pt in self._handle_points(box).values():
            p.drawRect(QRectF(pt.x() - HANDLE / 2.0, pt.y() - HANDLE / 2.0,
                              HANDLE, HANDLE))

    # ---------------------------------------------------------
    # 命中与交互
    # ---------------------------------------------------------
    @staticmethod
    def _selection_box(r):
        """选中框 = 文字块外扩 HIT_PAD（把手也画在这条线上）。"""
        return r.adjusted(-HIT_PAD, -HIT_PAD, HIT_PAD, HIT_PAD)

    @staticmethod
    def _handle_points(box):
        """8 个把手的中心点（小键盘方位：nw / n / ne / w / e / sw / s / se）。"""
        x0, y0, x1, y1 = box.left(), box.top(), box.right(), box.bottom()
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        return {
            "nw": QPointF(x0, y0), "n": QPointF(cx, y0), "ne": QPointF(x1, y0),
            "w": QPointF(x0, cy), "e": QPointF(x1, cy),
            "sw": QPointF(x0, y1), "s": QPointF(cx, y1), "se": QPointF(x1, y1),
        }

    @staticmethod
    def _dist(a, b):
        return ((a.x() - b.x()) ** 2 + (a.y() - b.y()) ** 2) ** 0.5

    def _selected_rect(self):
        """当前选中那条的文字块矩形（没选中/不在本帧可见 → None）。"""
        for i, r in self._rects:
            if i == self.selected:
                return QRectF(r)
        return None

    def _hit(self, pos):
        for i, r in reversed(self._rects):
            if r.adjusted(-HIT_PAD, -HIT_PAD, HIT_PAD, HIT_PAD).contains(QPointF(pos)):
                return i
        return -1

    def _hit_handle(self, pos):
        """命中选中字幕的把手 → 把手名；没命中返回 None。

        只在**已选中**的那条上判定：把手本来也只为它画。半径给到
        HANDLE_HIT（比画出来的 7px 大一圈），小方块才点得稳。
        """
        r = self._selected_rect()
        if r is None:
            return None
        pt = QPointF(pos)
        best, best_d = None, float(HANDLE_HIT)
        for name, hp in self._handle_points(self._selection_box(r)).items():
            d = self._dist(hp, pt)
            if d <= best_d:
                best, best_d = name, d
        return best

    def _cursor_for(self, pos):
        handle = self._hit_handle(pos)
        if handle is not None:
            return HANDLE_CURSORS.get(handle, Qt.ArrowCursor)
        return Qt.SizeAllCursor if self._hit(pos) >= 0 else Qt.ArrowCursor

    def _gesture_active(self):
        return self._drag is not None or self._resize is not None

    def mousePressEvent(self, ev):
        if ev.button() != Qt.LeftButton:
            return
        if self._editor is not None:
            return                    # 编辑中：点击交给编辑框自己处理
        # 顺序要紧：先判把手、再判框内。把手压在框边上，反过来的话永远会被
        # 当成"拖动位置"，缩放就再也点不着了。
        handle = self._hit_handle(ev.pos())
        if handle is not None:
            self._begin_resize(handle, ev.pos())
            return
        idx = self._hit(ev.pos())
        if idx < 0:
            if self.selected >= 0:
                self.selected = -1
                self.update()
                self.selection_cleared.emit()
            return
        if idx != self.selected:
            self.selected = idx
            self.update()
        # ⚠️ 点击与拖动在**松手**时才区分（_press_idx / _press_moved）：
        #   · 点一下 = 单选该条（cue_clicked，会覆盖时间轴/表格的多选）；
        #   · 拖动   = 只让主选中跟随（cue_followed，**保留多选**）——
        #     在 press 时就发 cue_clicked 会把 Ctrl+A 全选当场打散，
        #     "全选后拖一下字幕"全选就没了（用户实测反馈）。
        self._press_idx = idx
        self._press_moved = False
        self._drag = (ev.pos(), QPoint(0, 0))
        self._drag_style0 = dict(self.ass_style)
        self._drag_rect0 = None
        # 拖动期间放开窗口形状：mask 是贴着字幕块的，字幕一动 mask 就变，
        # 逐帧 SetWindowRgn 会让窗口边缘抖动甚至把字幕裁掉。
        self.clearMask()
        for i, r in self._rects:
            if i == idx:
                self._drag_rect0 = QRectF(r)
                break
        self.setCursor(Qt.SizeAllCursor)

    def _begin_resize(self, handle, pos):
        """按下把手：把基准样式 / 框 / 起点都钉下来。

        与拖动同理——一切都相对按下那一刻算，结果只取决于总位移，不受
        中途产生了多少个 mouseMove 事件影响。
        """
        r = self._selected_rect()
        if r is None:
            return
        self.clearMask()          # 缩放会让框变形，mask 逐帧变会抖
        self._resize = {
            "handle": handle,
            "start": QPoint(pos),
            "style0": dict(self.ass_style),
            "rect0": QRectF(r),
            "box0": self._selection_box(r),
            "applied": False,
        }
        self.setCursor(HANDLE_CURSORS.get(handle, Qt.ArrowCursor))

    def mouseMoveEvent(self, ev):
        if self._editor is not None:
            return
        if self._resize is not None:
            self._apply_resize(ev.pos())
            return
        if self._drag is None:
            self.setCursor(self._cursor_for(ev.pos()))
            return
        start, _ = self._drag
        delta = ev.pos() - start
        self._drag = (start, delta)
        # 还没超过阈值就不要改样式：否则"点一下"也会把位置写脏
        if abs(delta.x()) < 5 and abs(delta.y()) < 5:
            return
        self._press_moved = True
        self._apply_drag()

    def mouseReleaseEvent(self, ev):
        if self._resize is not None:
            self._finish_resize()
            return
        if self._drag is None:
            return
        start, delta = self._drag
        self._drag = None
        self.setCursor(Qt.ArrowCursor)
        # 阈值取 5px：点击时常有一两像素的抖动，阈值太小会把"点一下"
        # 误判成"拖动改位置"，位置就莫名其妙变了。
        if abs(delta.x()) < 5 and abs(delta.y()) < 5:
            self._drag_style0 = None
            self._drag_rect0 = None
            # 只是点了一下 → 单选语义（覆盖时间轴/表格的多选）
            if getattr(self, "_press_idx", -1) >= 0:
                self.cue_clicked.emit(self._press_idx)
            self._press_idx = -1
            return
        self._press_idx = -1
        # ⚠️ 顺序要紧：必须**先**用基准算出最终样式，**再**清基准。
        #    反过来写（先清空）会让 `_preview_after_drag` 退回用已被拖动
        #    改过的 `ass_style` 当基准，把位移又加一遍 —— 60px 的拖动
        #    因此被算成两次，字幕直接冲到画面另一头。
        final = dict(self._preview_after_drag(delta))
        self._drag_style0 = None
        self._drag_rect0 = None
        self.layout_changed.emit(final)
        # 拖动结束：主选中跟随，但**保留多选**（"全选后拖字幕"不打散全选）
        if getattr(self, "_press_moved", False) and self.selected >= 0:
            self.cue_followed.emit(self.selected)

    def contextMenuEvent(self, ev):
        """右键菜单：命中字幕 → 删除 / 就地编辑（纯鼠标的删除入口）。"""
        idx = self._hit(ev.pos())
        if idx < 0 or self._editor is not None:
            return
        from PyQt5.QtWidgets import QMenu
        menu = QMenu(self)
        act_del = menu.addAction("删除此字幕")
        act_edit = menu.addAction("就地编辑")
        act = menu.exec_(ev.globalPos())
        if act is act_del:
            self.delete_requested.emit(idx)
        elif act is act_edit:
            self._open_edit(idx)

    def mouseDoubleClickEvent(self, ev):
        idx = self._hit(ev.pos())
        if idx < 0:
            self.play_toggled.emit()
            return
        self._open_edit(idx)

    def keyPressEvent(self, ev):
        """本层激活时的键盘命令 → 转交页面（主窗快捷键此刻收不到）。

        覆盖与页面快捷键同一套：Del 删除、Ctrl+Z 撤销、Ctrl+Y /
        Ctrl+Shift+Z 重做、Ctrl+A 全选、Space 播放暂停。其余按键不拦。
        """
        k, m = ev.key(), ev.modifiers()
        ctrl = bool(m & Qt.ControlModifier)
        shift = bool(m & Qt.ShiftModifier)
        name = ""
        if k == Qt.Key_Delete:
            name = "del"
        elif k == Qt.Key_Z and ctrl and not shift:
            name = "undo"
        elif (k == Qt.Key_Y and ctrl) or (k == Qt.Key_Z and ctrl and shift):
            name = "redo"
        elif k == Qt.Key_A and ctrl and not shift:
            name = "all"
        elif k == Qt.Key_Space and not ctrl and not shift:
            name = "play"
        if name:
            self.command_requested.emit(name)
            ev.accept()
            return
        super().keyPressEvent(ev)

    def _drag_delta(self):
        return self._drag[1] if self._drag else QPoint(0, 0)

    def _clamp_pos(self, style, px, py, text=None):
        """把自由位置夹进画面内：整块字幕不出界，怎么拖都不会丢。"""
        scale = max(0.0001, self._scale())
        if text is None:
            idx = self.selected
            text = self.cues[idx].text if 0 <= idx < len(self.cues) else ""
        bw, bh = self._block_metrics(text, style)
        max_x = max(0.0, (self.width() - bw) / scale)
        max_y = max(0.0, (self.height() - bh) / scale)
        return max(0.0, min(max_x, px)), max(0.0, min(max_y, py))

    def _preview_after_drag(self, delta):
        """把一次拖动折算成**自由位置**（`pos_x` / `pos_y`）。

        v1.14.2 起不再改 alignment / margin_v：那两个是「跟随对齐」模式的
        规则参数，一动就牵动全部字幕、还会把面板的对齐选中态改掉。改成写
        自由位置之后，「对齐按钮点一次定位」与「拖动自由移动」互不干涉
        —— 用户要的就是这个"一次性"。

        起始位置优先取已有的 pos；没有就把**当前框的左上角**就地固化成
        自由位置：视觉上不跳，但从此脱离对齐规则。
        """
        style = dict(self._drag_style0 if self._drag_style0 is not None
                     else self.ass_style)
        scale = max(0.0001, self._scale())
        r = self._drag_rect0 or QRectF(0, 0, 0, 0)
        px, py = style.get("pos_x"), style.get("pos_y")
        if px is None or py is None:
            px, py = r.left() / scale, r.top() / scale
        nx = float(px) + delta.x() / scale
        ny = float(py) + delta.y() / scale
        nx, ny = self._clamp_pos(style, nx, ny)
        style["pos_x"] = int(round(nx))
        style["pos_y"] = int(round(ny))
        return style

    def _apply_drag(self):
        """拖动过程中实时重画（把样式临时改掉，不改数据）。"""
        style = self._preview_after_drag(self._drag_delta())
        self.ass_style = style
        self.update()
        self._emit_preview()

    # ---------- 把手缩放 ----------
    def _apply_resize(self, pos):
        ctx = self._resize
        if ctx is None:
            return
        style = self._preview_after_resize(ctx, pos)
        if style is None:
            return
        ctx["applied"] = True
        self.ass_style = style
        self.update()
        self._emit_preview()

    def _emit_preview(self):
        """拖动/缩放过程中发一次节流的实时读数（给属性面板显示）。

        为什么必须节流：`layout_preview` 会驱动面板刷十几个控件，而
        mouseMove 在 120Hz 鼠标上能跑满帧；40ms（≈25Hz）足够"看起来实时"，
        又不会让面板控件成为拖动的瓶颈。
        """
        now = time.monotonic()
        if now - self._preview_t0 < 0.04:
            return
        self._preview_t0 = now
        self.layout_preview.emit(dict(self.ass_style))

    def panel_metrics(self):
        """给属性面板显示用的等效「垂直距 / 水平距」（PlayRes 单位）。

        ⚠️ 这两个值**不存在于样式里**，是按当前框的几何折算出来的显示量：
        自由位置模式下 pos 才是真值，而面板那两个框的语义是"距对齐边"，
        不折算的话读数会跟画面完全脱节（用户拖动时数字一动不动）。
        折算规则跟渲染规则一一对应，两种模式读数连续：

          · 垂直距：底部对齐（row=0）取"框底到画面底"，其余取"框顶到画面顶"；
          · 水平距：左/中列取"框左到画面左"，右列取"框右到画面右"。

        这里按样式现算而不读 `_rects`：`_rects` 是上一帧 paintEvent 的产物，
        改完样式立刻问它会拿到过期值；`_block_metrics` / `_block_origin`
        是纯函数，任何时刻都能算准。
        """
        idx = self.selected
        if not (0 <= idx < len(self.cues)) or self.width() < 8:
            return {}
        text = self.cues[idx].text or ""
        bw, bh = self._block_metrics(text, self.ass_style)
        if bw <= 0 or bh <= 0:
            return {}
        scale = max(0.0001, self._scale())
        left, top = self._block_origin(self.ass_style, bw, bh)
        w, h = self.width() / scale, self.height() / scale
        left, top = left / scale, top / scale
        # 自由位置：两个框显示**几何原点**（框左 x / 框顶 y，PlayRes 坐标）
        # ——拖动、缩放、手输全部以左上角为基准，所见即所得；
        # 跟随对齐模式仍显示"距对齐边"（与 margin 语义连续）
        if (self.ass_style.get("pos_x") is not None
                and self.ass_style.get("pos_y") is not None):
            return {"_va": int(round(top)), "_ha": int(round(left))}
        align = min(9, max(1, int(self.ass_style.get("alignment", 2) or 2)))
        row, col = (align - 1) // 3, (align - 1) % 3
        va = (h - (top + bh / scale)) if row == 0 else top
        ha = left if col != 2 else (w - (left + bw / scale))
        return {"_va": int(round(max(0.0, va))), "_ha": int(round(max(0.0, ha)))}

    def _finish_resize(self):
        ctx, self._resize = self._resize, None
        self.setCursor(Qt.ArrowCursor)
        if ctx is None or not ctx.get("applied"):
            return
        self.layout_changed.emit(dict(self.ass_style))

    def _preview_after_resize(self, ctx, pos):
        """把一次把手拖动折算成 字号 / 缩放 + 自由位置。

        ▸ 四角：等比缩放字号，锚点取**对角**——被抓的那只角跟手，另一只
          角不动；
        ▸ 左右边：改 ScaleX；上下边：改 ScaleY（面板里还能接着微调）；
        ▸ 结果一律写进自由位置：否则在「跟随对齐」模式下框会被对齐规则
          重新摆回去，手感就成了"缩得动、但框跑掉"。
        """
        handle = ctx["handle"]
        style = dict(ctx["style0"])
        scale = max(0.0001, self._scale())
        box0 = ctx["box0"]
        idx = self.selected
        text = self.cues[idx].text if 0 <= idx < len(self.cues) else ""
        cur = QPointF(pos)

        if handle in ("nw", "ne", "sw", "se"):
            fixed_left = "e" in handle          # 抓 e 侧的角 → 左边固定
            fixed_top = "s" in handle           # 抓 s 侧的角 → 上边固定
            anchor = QPointF(box0.left() if fixed_left else box0.right(),
                             box0.top() if fixed_top else box0.bottom())
            corner0 = QPointF(box0.left() if not fixed_left else box0.right(),
                              box0.top() if not fixed_top else box0.bottom())
            d0 = self._dist(anchor, corner0)
            if d0 < 1.0:
                return None
            k = max(ZOOM_MIN, min(ZOOM_MAX, self._dist(anchor, cur) / d0))
            size0 = float(ctx["style0"].get("size", 46) or 46)
            style["size"] = int(round(max(6, min(400, size0 * k))))
            bw, bh = self._block_metrics(text, style)
            bw += 2 * HIT_PAD
            bh += 2 * HIT_PAD
            left = anchor.x() if fixed_left else anchor.x() - bw
            top = anchor.y() if fixed_top else anchor.y() - bh
        else:
            bw0 = max(1.0, box0.width())
            bh0 = max(1.0, box0.height())
            if handle in ("e", "w"):
                want_w = ((cur.x() - box0.left()) if handle == "e"
                          else (box0.right() - cur.x()))
                k = max(ZOOM_MIN, min(ZOOM_MAX, want_w / bw0))
                sx0 = float(ctx["style0"].get("scale_x", 100) or 100)
                style["scale_x"] = int(round(max(10, min(500, sx0 * k))))
                # 字体 stretch 对宽度的响应不是严格线性，迭代两次基本贴合
                style["scale_x"] = self._fit_axis(
                    style, text, ctx["style0"], "scale_x", want_w)
                bw, _bh = self._block_metrics(text, style)
                bw += 2 * HIT_PAD
                left = box0.left() if handle == "e" else box0.right() - bw
                top = box0.top()
            else:
                want_h = ((cur.y() - box0.top()) if handle == "s"
                          else (box0.bottom() - cur.y()))
                k = max(ZOOM_MIN, min(ZOOM_MAX, want_h / bh0))
                sy0 = float(ctx["style0"].get("scale_y", 100) or 100)
                style["scale_y"] = int(round(max(10, min(500, sy0 * k))))
                style["scale_y"] = self._fit_axis(
                    style, text, ctx["style0"], "scale_y", want_h)
                _bw, bh = self._block_metrics(text, style)
                bh += 2 * HIT_PAD
                top = box0.top() if handle == "s" else box0.bottom() - bh
                left = box0.left()

        nx = (left + HIT_PAD) / scale        # 换成文字块左上角的 PlayRes 坐标
        ny = (top + HIT_PAD) / scale
        nx, ny = self._clamp_pos(style, nx, ny, text=text)
        style["pos_x"] = int(round(nx))
        style["pos_y"] = int(round(ny))
        return style if style != ctx["style0"] else None

    def _fit_axis(self, style, text, style0, key, want_px):
        """把某个缩放轴迭代逼近目标像素尺寸（两次足够收敛）。"""
        base = float(style0.get(key, 100) or 100)
        val = float(style.get(key, base) or base)
        for _ in range(2):
            bw, bh = self._block_metrics(text, style)
            got = (bw if key == "scale_x" else bh) + 2 * HIT_PAD
            if got < 1.0:
                break
            ratio = want_px / got
            if abs(ratio - 1.0) < 0.02:
                break
            val = max(10.0, min(500.0, val * ratio))
            style[key] = int(round(val))
        return int(round(max(10, min(500, val))))

    # ---------------------------------------------------------
    # 就地编辑
    # ---------------------------------------------------------
    def _open_edit(self, idx):
        r = None
        for i, rr in self._rects:
            if i == idx:
                r = rr
                break
        if r is None:
            return
        self._edit_index = idx
        self.clearMask()        # 编辑框比字幕块大，别被 mask 裁掉
        box = r.adjusted(-HIT_PAD * 2, -HIT_PAD * 2, HIT_PAD * 2, HIT_PAD * 2)
        box = box.intersected(QRectF(0, 0, self.width(), self.height()))
        ed = _InlineEdit(self)
        ed.setGeometry(box.toRect())
        ed.setPlainText(self.cues[idx].text or "")
        ed.setStyleSheet(
            "QTextEdit{background:rgba(0,0,0,200);color:#FFFFFF;"
            "border:1px solid #45C877;border-radius:4px;padding:4px;"
            "font-family:'Microsoft YaHei';font-size:13px;}")
        ed.submitted.connect(self._finish_edit)
        ed.show()
        ed.setFocus()
        ed.selectAll()
        self._editor = ed

    def _finish_edit(self, commit):
        ed, self._editor = self._editor, None
        idx = self._edit_index
        self._edit_index = -1
        if ed is None:
            return
        text = ed.toPlainText()
        ed.deleteLater()
        if commit and 0 <= idx < len(self.cues):
            self.text_committed.emit(idx, text.replace("\r\n", "\n"))
        self.update()
        self._apply_mask()      # 编辑结束，收回 mask

    def _cancel_edit(self):
        if self._editor is not None:
            self._finish_edit(False)

    def edit_active(self):
        return self._editor is not None
