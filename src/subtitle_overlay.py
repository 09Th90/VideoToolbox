# -*- coding: utf-8 -*-
# @version 1.13.2
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

from PyQt5.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import (QColor, QFont, QFontMetricsF, QPainter, QPainterPath,
                         QPen, QRegion)
from PyQt5.QtWidgets import QApplication, QTextEdit, QWidget

ASS_PLAY_RES_Y = 1080.0

#: 选中框与把手
C_SEL = QColor("#45C877")
C_SEL_SOFT = QColor(69, 200, 119, 90)

HANDLE = 7          # 把手边长（逻辑像素）
HIT_PAD = 6         # 命中测试外扩，太薄的字幕不好点
MASK_PAD = 18       # 窗口 mask 在字幕块外扩这么多，让选框/把手/拖动都够用


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
      · `layout_changed(dict)`   —— 拖动改了位置，回传新的 margin_* / alignment
      · `play_toggled()`         —— 双击空白 = 播放/暂停（视频区本来就没有
                                    别的鼠标交互，顺手补上，免得浮层白吃事件）
    """

    cue_clicked = pyqtSignal(int)
    selection_cleared = pyqtSignal()
    text_committed = pyqtSignal(int, str)
    layout_changed = pyqtSignal(dict)
    play_toggled = pyqtSignal()

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
        #: 拖动的**基准**：按下那一刻的样式与字幕矩形。
        #: ⚠️ 必须缓存，不能每帧拿"当前值"当基准——那样每个 mouseMove 都会
        #:    在上一帧结果上再叠一次位移，拖一点点字幕就冲到画面另一头
        #:    （e2e 实测：向上拖 60px 把 margin_v 从 40 顶到上限 600）。
        self._drag_style0 = None
        self._drag_rect0 = None
        self._rects = []           # [(idx, QRectF)]，本帧画出来的字幕矩形（命中用）
        self._mask = QRegion()     # 当前窗口 mask（只覆盖字幕块附近）
        self._pending_snap = False  # 强制补一次几何同步（跨屏/DPI 变化用）

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
        if self._drag is not None or self._editor is not None:
            return                 # 拖动/编辑期间不折腾窗口形状（见 mousePressEvent）
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

    def _layout_one(self, painter, text, style):
        """按 ASS 的 alignment / margin 规则算出文字块矩形并绘制。

        返回文字块的 QRectF（未命中任何文字时返回 None）。
        """
        if not (text or "").strip():
            return None
        scale = self._scale()
        font = self._font_for(style)
        fm = QFontMetricsF(font)
        lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        line_h = fm.height()
        widths = [fm.width(ln) for ln in lines]
        block_w = max(widths) if widths else 0.0
        block_h = line_h * len(lines)

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
        box = r.adjusted(-HIT_PAD, -HIT_PAD, HIT_PAD, HIT_PAD)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(C_SEL, 1.5, Qt.DashLine))
        p.drawRect(box)
        p.setPen(QPen(C_SEL, 1))
        p.setBrush(C_SEL)
        hx = box.left() - HANDLE / 2.0 - 1
        hy = box.top() - HANDLE / 2.0 - 1
        hw = box.width() + 2 - HANDLE
        hh = box.height() + 2 - HANDLE
        for pt in (QPointF(hx, hy), QPointF(hx + hw, hy),
                   QPointF(hx, hy + hh), QPointF(hx + hw, hy + hh)):
            p.drawRect(QRectF(pt.x(), pt.y(), HANDLE, HANDLE))

    # ---------------------------------------------------------
    # 命中与交互
    # ---------------------------------------------------------
    def _hit(self, pos):
        for i, r in reversed(self._rects):
            if r.adjusted(-HIT_PAD, -HIT_PAD, HIT_PAD, HIT_PAD).contains(QPointF(pos)):
                return i
        return -1

    def mousePressEvent(self, ev):
        if ev.button() != Qt.LeftButton:
            return
        if self._editor is not None:
            return                    # 编辑中：点击交给编辑框自己处理
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
            self.cue_clicked.emit(idx)
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

    def mouseMoveEvent(self, ev):
        if self._editor is not None:
            return
        if self._drag is None:
            self.setCursor(Qt.SizeAllCursor if self._hit(ev.pos()) >= 0
                           else Qt.ArrowCursor)
            return
        start, _ = self._drag
        delta = ev.pos() - start
        self._drag = (start, delta)
        # 还没超过阈值就不要改样式：否则"点一下"也会写进 margin_v
        if abs(delta.x()) < 5 and abs(delta.y()) < 5:
            return
        self._apply_drag()

    def mouseReleaseEvent(self, ev):
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
            return                    # 只是点了一下，位置没动
        # ⚠️ 顺序要紧：必须**先**用基准算出最终样式，**再**清基准。
        #    反过来写（先清空）会让 `_preview_after_drag` 退回用已被拖动
        #    改过的 `ass_style` 当基准，把位移又加一遍 —— 60px 的拖动
        #    因此被算成两次，直接顶到 margin_v 的上限。
        # 只有水平位移**足够明显**才顺带定一次对齐：位移很小时多半只是想
        # 上下挪一挪，这时切换对齐反而会让字幕横向跳一下。
        final = dict(self._preview_after_drag(delta, with_align=abs(delta.x()) >= 30))
        self._drag_style0 = None
        self._drag_rect0 = None
        self.layout_changed.emit(final)

    def mouseDoubleClickEvent(self, ev):
        idx = self._hit(ev.pos())
        if idx < 0:
            self.play_toggled.emit()
            return
        self._open_edit(idx)

    def _drag_delta(self):
        return self._drag[1] if self._drag else QPoint(0, 0)

    def _preview_after_drag(self, delta, with_align=False):
        """把一次拖动折算成新的样式。

        一切都相对**按下那一刻**的样式与矩形算（`_drag_style0` /
        `_drag_rect0`），所以结果只取决于总位移，与中途产生了多少个
        mouseMove 事件无关——否则会逐帧累积，字幕跑得比鼠标快好几倍。

        `with_align=False`（拖动过程中）**只改垂直**：对齐一旦在中途切换，
        字幕会整块从"居中"瞬移到"贴左/贴右"，看起来就是位置突然漂走。
        只有松手那一刻（`with_align=True`）才按落点定一次水平对齐。
        """
        style = dict(self._drag_style0 if self._drag_style0 is not None
                     else self.ass_style)
        scale = max(0.0001, self._scale())
        mv = float(style.get("margin_v", 40)) - delta.y() / scale
        style["margin_v"] = int(max(0, min(900, round(mv))))
        if not with_align:
            return style
        r = self._drag_rect0
        if r is not None:
            cx = r.center().x() + delta.x()
            fr = cx / max(1.0, float(self.width()))
            col = 0 if fr < 1 / 3.0 else (2 if fr > 2 / 3.0 else 1)
            align = int(style.get("alignment", 2) or 2)
            row = (align - 1) // 3
            style["alignment"] = row * 3 + col + 1
        return style

    def _apply_drag(self):
        """拖动过程中实时重画（把样式临时改掉，不改数据）。"""
        style = self._preview_after_drag(self._drag_delta())
        self.ass_style = style
        self.update()

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
