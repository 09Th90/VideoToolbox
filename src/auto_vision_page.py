#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# @version 1.16.4
"""「自动化」页 —— 视觉自动化 demo（参考 MAA 的四段设计）
====================================================================
本页是 `auto_vision_core` 的界面外壳，把 MAA 的「感知 → 认知 → 决策 → 行动」
四段在视频工具箱里演示一遍：

  ① 感知 · 抓帧     选一个窗口当"屏幕"，抓它的客户区画面；
  ② 认知 · 识别     模板匹配（FFT 归一化互相关）/ 色块匹配，命中框画在预览上；
  ③ 决策 · 任务     一份声明式 JSON 管线（仿 MAA tasks.json），可单步 / 整条跑；
  ④ 行动 · 点击     ClickSelf 点命中位置——**默认演练模式不真点**，要真点得手动关掉；
  ⑤ 内置演示场景    自绘一个"游戏画面"（目标图标位置随机），一键跑通全链路，
                    不需要用户准备任何素材就能看到效果。

为什么单独成模块（而不是像其余 6 个页面那样写进 video_toolbox_qt.py）：
  主文件里那些页面共享 `ScrollPage` / `card()` / `row()`，页面独立成模块会反向
  import 主文件形成循环导入。本页自带一套等价的壳（`_card` / `_row`），只依赖
  `ui_theme` 与 qfluentwidgets，于是主文件里只需要 3 行注册代码。

⚠ 与 MAA 一样的边界：视觉 + 鼠标注入，不改动目标进程内存；但**自动化别人家的
界面仍属灰色地带**，请只用于自己的窗口、自己的程序。
"""

import json
import os
import tempfile
import time

import numpy as np
from PIL import Image
from PyQt5.QtCore import Qt, QPoint, QRect, QTimer, pyqtSignal
from PyQt5.QtGui import (QBrush, QColor, QFont, QImage, QPainter, QPen,
                         QPixmap, QPolygon)
from PyQt5.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QLabel,
                             QPlainTextEdit, QSizePolicy, QVBoxLayout, QWidget)

from qfluentwidgets import (BodyLabel, CaptionLabel, ComboBox, FluentIcon as FIF,
                            InfoBar, InfoBarPosition, LineEdit,
                            PrimaryPushButton, PushButton, ScrollArea, Slider,
                            SpinBox, StrongBodyLabel, SubtitleLabel,
                            SwitchButton, TextEdit)

import auto_vision_core as av
import ui_theme

#: 生成的模板落盘位置：优先跟程序数据目录走，取不到就退到临时目录
try:
    import video_toolbox as _engine
    TEMPLATE_DIR = os.path.join(_engine.DATA_DIR, "auto_vision")
except Exception:  # noqa: BLE001
    TEMPLATE_DIR = os.path.join(tempfile.gettempdir(), "video_toolbox_auto")

#: 内置演示场景里目标图标的逻辑边长（模板按设备像素比放大到物理像素）
DEMO_ICON_SIZE = 56
#: 场景底色 —— 与模板底色必须一致（模板连"UI 背景"一起截，跟 MAA 的做法一样）
SCENE_BG = QColor(30, 34, 40)
SCENE_ACCENT = QColor(245, 196, 84)


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
# 内置演示场景：自绘一个"游戏画面"，目标图标位置随机
# ---------------------------------------------------------------------- #
def draw_target_icon(painter, rect, accent=SCENE_ACCENT, hole=SCENE_BG):
    """画目标图标（外圈 + 四齿 + 中心十字）。

    场景与模板渲染**共用这一个函数**——模板因此和画面里的图标逐像素一致，
    这正是 MAA 的模板来源（从游戏 UI 里截下来的素材）。
    """
    painter.save()
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    cx, cy = x + w / 2.0, y + h / 2.0
    r = min(w, h) / 2.0
    # 四个"齿"（先画，被外圈压住根部）
    tooth = max(4.0, r * 0.30)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(accent))
    for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
        tr = QRect(0, 0, int(tooth), int(tooth))
        # ⚠ PyQt5 的 QRect.moveCenter 只吃 QPoint；传两个 int 会抛 TypeError，
        # 而异常发生在 paintEvent 里会被 Qt 直接吞掉并 abort（无任何 traceback，
        # 表现为"窗口一 show 就崩"）。必须用 QPoint。
        tr.moveCenter(QPoint(int(cx + dx * r * 0.92), int(cy + dy * r * 0.92)))
        painter.drawRoundedRect(tr, tooth * 0.25, tooth * 0.25)
    # 外圈
    pen = QPen(accent)
    pen.setWidthF(max(2.0, r * 0.22))
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawEllipse(QRect(int(cx - r * 0.72), int(cy - r * 0.72),
                              int(r * 1.44), int(r * 1.44)))
    # 中心十字
    pen.setWidthF(max(2.0, r * 0.16))
    painter.setPen(pen)
    arm = r * 0.34
    painter.drawLine(int(cx - arm), int(cy), int(cx + arm), int(cy))
    painter.drawLine(int(cx), int(cy - arm), int(cx), int(cy + arm))
    painter.restore()


def render_target_template(size=DEMO_ICON_SIZE, dpr=1.0):
    """把目标图标渲染成模板 QImage（按设备像素比放大到物理像素）。

    ⚠ 必须按 dpr 放大：抓帧拿到的是**物理像素**，模板若按逻辑像素渲染，
    在 125%/150%/200% 缩放下尺寸对不上，匹配必然失败。
    """
    px = max(8, int(round(size * float(dpr))))
    img = QImage(px, px, QImage.Format_RGB32)
    img.fill(SCENE_BG)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.scale(float(dpr), float(dpr))
    draw_target_icon(p, QRect(0, 0, int(size), int(size)))
    p.end()
    return img


class DemoScene(QWidget):
    """演示场景窗口：当作"游戏画面"，可被引擎抓帧、被真点击。"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("视觉自动化 · 演示场景（这就是被识别的「画面」）")
        self.resize(760, 460)
        self.setMinimumSize(520, 340)
        self.target = QRect(0, 0, DEMO_ICON_SIZE, DEMO_ICON_SIZE)
        self.decoys = []
        self.clicks = 0
        self.misses = 0
        self.last_click = None
        self._ripple = 0
        self._ripple_timer = QTimer(self)
        self._ripple_timer.setInterval(40)
        self._ripple_timer.timeout.connect(self._fade_ripple)
        self.relayout()

    def relayout(self):
        """随机摆放目标图标与干扰图形（保证不重叠、避开顶部标题带）。"""
        rng = np.random.default_rng()
        W, H = self.width(), self.height()
        s = DEMO_ICON_SIZE
        top, bottom = 56, H - 46
        self.target = QRect(int(rng.integers(12, max(13, W - s - 12))),
                            int(rng.integers(top, max(top + 1, bottom - s))),
                            s, s)
        shapes = ("circle", "square", "tri")
        colors = (QColor(70, 78, 92), QColor(58, 104, 150),
                  QColor(92, 70, 88))
        self.decoys = []
        for i in range(4):
            size = int(rng.integers(34, 58))
            for _ in range(40):               # 找一块不和目标重叠的位置
                r = QRect(int(rng.integers(10, max(11, W - size - 10))),
                          int(rng.integers(top, max(top + 1, bottom - size))),
                          size, size)
                if not r.intersects(self.target.adjusted(-18, -18, 18, 18)):
                    self.decoys.append((r, shapes[i % len(shapes)],
                                        colors[i % len(colors)]))
                    break
        self.update()

    def _fade_ripple(self):
        self._ripple = max(0, self._ripple - 1)
        self.update()
        if self._ripple == 0:
            self._ripple_timer.stop()

    def mousePressEvent(self, e):
        pos = e.pos()
        if self.target.contains(pos):
            self.clicks += 1
        else:
            self.misses += 1
        self.last_click = pos
        self._ripple = 6
        self._ripple_timer.start()
        self.update()
        super().mousePressEvent(e)

    def paintEvent(self, _e):
        # ⚠ paintEvent 里抛出的异常会被 Qt 吞掉并直接 abort 进程（没有任何
        # traceback），所以这里整体兜底：宁可画不出来，也不能让程序崩。
        try:
            self._paint()
        except Exception:  # noqa: BLE001
            pass

    def _paint(self):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        W, H = self.width(), self.height()
        # 底色必须与模板底色一致（图标直接落在纯色底上）
        p.fillRect(self.rect(), SCENE_BG)
        # 顶部标题带
        p.setPen(QPen(QColor(120, 132, 150)))
        f = QFont()
        f.setPointSizeF(10.5)
        p.setFont(f)
        p.drawText(QRect(16, 12, W - 32, 24), Qt.AlignLeft | Qt.AlignVCenter,
                   "DEMO SCENE —— 引擎只看位图，靠视觉找按钮")
        p.setPen(QPen(QColor(70, 78, 92)))
        p.drawLine(16, 42, W - 16, 42)
        # 干扰图形（形状与目标不同，用来验证不是"随便点一个"）
        for rect, shape, color in self.decoys:
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(color))
            if shape == "circle":
                p.drawEllipse(rect)
            elif shape == "square":
                p.drawRoundedRect(rect, 8, 8)
            else:
                poly = QPolygon([QPoint(rect.center().x(), rect.top()),
                                 QPoint(rect.right(), rect.bottom()),
                                 QPoint(rect.left(), rect.bottom())])
                p.drawPolygon(poly)
        # 目标图标
        draw_target_icon(p, self.target)
        # 底部状态
        p.setPen(QPen(QColor(150, 160, 175)))
        p.drawText(QRect(16, H - 34, W - 32, 22),
                   Qt.AlignLeft | Qt.AlignVCenter,
                   f"被点击 {self.clicks} 次 · 点空 {self.misses} 次"
                   f"（真点击会 +1）")
        # 点击涟漪
        if self._ripple and self.last_click is not None:
            alpha = int(200 * self._ripple / 6.0)
            radius = int(10 + (6 - self._ripple) * 8)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(255, 90, 90, alpha), 3))
            p.drawEllipse(self.last_click, radius, radius)
        p.end()


# ---------------------------------------------------------------------- #
# 抓帧预览：等比缩放显示 + 鼠标框选 + 命中框叠加
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
        self._hits = []
        self.setMouseTracking(True)

    # -- 数据入口 ----------------------------------------------------- #
    def set_frame(self, frame_rgb, hits=None):
        h, w = frame_rgb.shape[:2]
        arr = np.ascontiguousarray(frame_rgb, dtype=np.uint8)
        img = QImage(arr.data, w, h, 3 * w, QImage.Format_RGB888).copy()
        self._pix = QPixmap.fromImage(img)
        self._frame_size = (w, h)
        self._hits = list(hits or [])
        self._sel = None
        self._drag_from = None
        self.setText("")          # 清掉占位文字，免得等比缩放留白处露出来
        self.update()

    def set_hits(self, hits):
        self._hits = list(hits or [])
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
        # 同 DemoScene.paintEvent：paintEvent 内的异常会让 Qt 直接 abort，
        # 整块绘制必须兜底。
        try:
            self._paint_overlay()
        except Exception:  # noqa: BLE001
            pass

    def _paint_overlay(self):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        self._img_rect = self._fit_rect()
        p.drawPixmap(self._img_rect, self._pix)
        r = self._img_rect
        if r.width() <= 0:
            p.end()
            return
        sx = r.width() / float(max(1, self._pix.width()))
        sy = r.height() / float(max(1, self._pix.height()))

        def map_rect(x, y, w, h):
            return QRect(int(r.x() + x * sx), int(r.y() + y * sy),
                         max(1, int(w * sx)), max(1, int(h * sy)))

        # 命中框（红=最优，橙=其余）
        for i, m in enumerate(self._hits):
            color = QColor(255, 82, 82) if i == 0 else QColor(255, 168, 60)
            pen = QPen(color, 2)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            box = map_rect(m.x, m.y, m.w, m.h)
            p.drawRect(box)
            p.setPen(QPen(color))
            f = QFont()
            f.setPointSizeF(8.5)
            p.setFont(f)
            p.drawText(box.adjusted(2, -16, 2, 0), Qt.AlignLeft,
                       f"{m.score:.2f}")
        # 框选区域（蓝）
        if self._sel is not None:
            p.setPen(QPen(QColor(64, 158, 255), 2, Qt.DashLine))
            p.setBrush(QColor(64, 158, 255, 40))
            p.drawRect(self._sel)
        p.end()


# ---------------------------------------------------------------------- #
# 页面
# ---------------------------------------------------------------------- #
class AutoVisionPage(QWidget):
    """「自动化」导航页。"""

    def __init__(self, app=None, parent=None):
        super().__init__(parent)
        self.app = app
        self.setObjectName("AutoVisionPage")

        self._win = None            # 当前选中的 av.WindowInfo
        self._frame = None
        self._origin = (0, 0)
        self._sel = (0, 0, 0, 0)
        self._hits = []
        self._tpl_path = ""
        self._busy = False
        self.demo_scene = None
        self._demo_dpr = 1.0

        self._build()

    # ---------------- 布局 ---------------- #
    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 16, 24, 18)
        outer.setSpacing(10)
        outer.addWidget(SubtitleLabel("自动化", self))
        cap = CaptionLabel(
            "视觉自动化 demo：照 MAA 的思路——抓帧 → 识别 → 声明式任务 → 点击，"
            "全程只看屏幕、不碰目标程序内存。默认演练模式，不会真的动你的鼠标。",
            self)
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

        self.vbox.addWidget(self._card_sense())
        self.vbox.addWidget(self._card_recognize())
        self.vbox.addWidget(self._card_task())
        self.vbox.addWidget(self._card_demo())
        self.vbox.addWidget(self._card_about())
        self.vbox.addStretch(1)

    # ---------------- ① 感知 ---------------- #
    def _card_sense(self):
        box, lay = _card("① 感知 · 抓帧",
                         "选一个窗口当「屏幕」。抓的是它的客户区，"
                         "坐标原点随窗口走——和 MAA 的 ControlUnit 一个角色。")
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
        self.sense_status = CaptionLabel("尚未抓帧")
        lay.addWidget(self.sense_status)
        self.refresh_windows()
        return box

    def refresh_windows(self):
        self.win_combo.clear()
        self._wins = av.list_windows()
        if not self._wins:
            self.win_combo.addItem("（没找到可用窗口）", userData=None)
            return
        for w in self._wins:
            size = f"{w.size[0]}×{w.size[1]}"
            self.win_combo.addItem(f"{w.title[:46]}  [{size}]", userData=w.hwnd)
        self.sense_status.setText(f"找到 {len(self._wins)} 个可见窗口，"
                                  f"请选择一个后点「抓帧」")

    def _selected_window(self):
        hwnd = self.win_combo.currentData()
        if not hwnd:
            return None
        for w in getattr(self, "_wins", []):
            if w.hwnd == hwnd:
                return w
        # 下拉框里可能有"演示场景（临时）"这类不在枚举列表里的项
        return av.window_info(hwnd)

    def take_shot(self, quiet=False):
        win = self._selected_window()
        if win is None:
            if not quiet:
                _tip("warning", "提示", "先在下拉框里选一个目标窗口", self)
            return None
        try:
            frame, origin, cost = av.capture_window(
                win, use_printwindow=self.pw_switch.isChecked())
        except Exception as exc:  # noqa: BLE001
            _tip("error", "抓帧失败", f"{type(exc).__name__}: {exc}", self)
            return None
        self._win, self._frame, self._origin = win, frame, origin
        self._hits = []
        self.shot_view.set_frame(frame, [])
        self.sense_status.setText(
            f"已抓帧：{frame.shape[1]}×{frame.shape[0]} 像素，"
            f"用时 {cost:.0f} ms，客户区屏幕原点 ({origin[0]}, {origin[1]})")
        return frame

    def _on_selection(self, x, y, w, h):
        self._sel = (x, y, w, h)
        self.sense_status.setText(
            f"框选区域：x={x} y={y} w={w} h={h}（相对客户区）"
            f"　—— 可点「从框选生成模板」")

    # ---------------- ② 认知 ---------------- #
    def _card_recognize(self):
        box, lay = _card("② 认知 · 识别",
                         "模板匹配 = 归一化互相关（对亮度线性变化不敏感，"
                         "和 OpenCV 的 TM_CCOEFF_NORMED 同源）；"
                         "色块匹配 = 找最大同色连通块，便宜，适合判断「亮起 / 进度条」。")
        self.algo_combo = ComboBox()
        self.algo_combo.addItems(["模板匹配 TemplateMatch", "色块 ColorMatch"])
        self.algo_combo.setCurrentIndex(0)
        self.algo_combo.currentIndexChanged.connect(self._sync_algo_ui)
        self.algo_combo.setMinimumWidth(200)
        self.tpl_edit = LineEdit()
        self.tpl_edit.setPlaceholderText("模板图片路径（PNG），或先在预览里框选再点右边按钮")
        btn_pick = PushButton("浏览…", icon=FIF.FOLDER)
        btn_pick.clicked.connect(self._pick_template)
        self.btn_mktpl = PushButton("从框选生成模板", icon=FIF.CUT)
        self.btn_mktpl.clicked.connect(self._make_template)
        lay.addWidget(_row(self.algo_combo, self.tpl_edit, btn_pick,
                           self.btn_mktpl))
        self.thr_slider = Slider(Qt.Horizontal)
        self.thr_slider.setRange(30, 99)
        self.thr_slider.setValue(80)
        self.thr_slider.valueChanged.connect(self._sync_thr_label)
        self.thr_label = CaptionLabel("阈值 0.80")
        self.color_edit = LineEdit()
        self.color_edit.setText("245,196,84")
        self.color_edit.setMaximumWidth(130)
        self.tol_spin = SpinBox()
        self.tol_spin.setRange(2, 120)
        self.tol_spin.setValue(24)
        self.tol_spin.setMaximumWidth(90)
        self.btn_run = PrimaryPushButton("识别", icon=FIF.SEARCH)
        self.btn_run.clicked.connect(self.run_recognize)
        lay.addWidget(_row(CaptionLabel("得分门限"), self.thr_slider,
                           self.thr_label, CaptionLabel("颜色 R,G,B"),
                           self.color_edit, CaptionLabel("容差"),
                           self.tol_spin, self.btn_run))
        self.recog_status = CaptionLabel("尚未识别")
        lay.addWidget(self.recog_status)
        self._sync_algo_ui()
        return box

    def _sync_algo_ui(self):
        is_color = self.algo_combo.currentIndex() == 1
        for w in (self.tpl_edit, self.btn_mktpl):
            w.setEnabled(not is_color)
        self.color_edit.setEnabled(is_color)
        self.tol_spin.setEnabled(is_color)

    def _sync_thr_label(self, v):
        self.thr_label.setText(f"阈值 {v / 100.0:.2f}")

    def _pick_template(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择模板图片", "", "图片 (*.png *.jpg *.jpeg *.bmp)")
        if path:
            self.tpl_edit.setText(path)

    def _make_template(self):
        if self._frame is None:
            _tip("warning", "提示", "先抓帧", self)
            return
        x, y, w, h = self._sel
        if w < 8 or h < 8:
            _tip("warning", "提示", "先在预览图上按住左键框选一块区域（至少 8×8）", self)
            return
        crop = self._frame[y:y + h, x:x + w]
        os.makedirs(TEMPLATE_DIR, exist_ok=True)
        path = os.path.join(TEMPLATE_DIR, f"tpl_{int(time.time())}.png")
        try:
            Image.fromarray(crop).save(path)
        except Exception as exc:  # noqa: BLE001
            _tip("error", "保存模板失败", str(exc), self)
            return
        self.tpl_edit.setText(path)
        _tip("success", "模板已生成", f"{w}×{h} → {os.path.basename(path)}", self)

    def run_recognize(self):
        if self._frame is None:
            _tip("warning", "提示", "先抓帧", self)
            return []
        thr = self.thr_slider.value() / 100.0
        t0 = time.time()
        if self.algo_combo.currentIndex() == 1:
            try:
                rgb = [int(v) for v in self.color_edit.text().split(",")][:3]
            except Exception:  # noqa: BLE001
                _tip("warning", "提示", "颜色要写成 R,G,B 三个数字", self)
                return []
            hits = [m for m in av.match_color(self._frame, rgb, None,
                                              self.tol_spin.value())
                    if m.score >= thr]
            note = f"色块 {tuple(rgb)} ±{self.tol_spin.value()}"
        else:
            path = self.tpl_edit.text().strip()
            tpl = av.load_template(path) if path else None
            if tpl is None:
                _tip("warning", "提示", "模板读不到：先选一张 PNG，或在预览里框选生成", self)
                return []
            hits = av.match_template(self._frame, tpl, None, thr)
            note = f"模板 {os.path.basename(path)}（{tpl.shape[1]}×{tpl.shape[0]}）"
        cost = (time.time() - t0) * 1000.0
        self._hits = hits
        self.shot_view.set_hits(hits)
        if hits:
            self.recog_status.setText(
                f"{note} → 命中 {len(hits)} 处，最高 {hits[0].score:.3f} @ "
                f"({hits[0].x},{hits[0].y})，用时 {cost:.0f} ms")
        else:
            self.recog_status.setText(f"{note} → 未命中（阈值 {thr:.2f}，"
                                      f"用时 {cost:.0f} ms）")
        return hits

    # ---------------- ③ 决策 ---------------- #
    def _card_task(self):
        box, lay = _card("③ 决策 · 任务流水线（仿 MAA tasks.json）",
                         "每个节点 = 识别什么 + 在哪片 ROI + 做什么动作 + 成功后去哪。"
                         "next 为空 = 任务成功结束；识别始终失败就走 exceededNext（熔断兜底）。")
        self.task_edit = TextEdit()
        self.task_edit.setPlainText(av.demo_pipeline_text())
        self.task_edit.setMinimumHeight(210)
        lay.addWidget(self.task_edit)
        btn_load = PushButton("载入内置示例", icon=FIF.HISTORY)
        btn_load.clicked.connect(
            lambda: self.task_edit.setPlainText(av.demo_pipeline_text()))
        btn_check = PushButton("校验", icon=FIF.ACCEPT)
        btn_check.clicked.connect(self.check_task)
        btn_step = PushButton("单步", icon=FIF.PLAY)
        btn_step.clicked.connect(lambda: self.run_task(step_only=True))
        btn_run = PrimaryPushButton("运行任务", icon=FIF.PLAY_SOLID)
        btn_run.clicked.connect(lambda: self.run_task(step_only=False))
        self.dry_switch = SwitchButton()
        self.dry_switch.setOnText("演练")
        self.dry_switch.setOffText("真点")
        self.dry_switch.setChecked(True)
        lay.addWidget(_row(btn_load, btn_check, btn_step, btn_run,
                           CaptionLabel("演练模式（只识别不点鼠标）"),
                           self.dry_switch))
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(170)
        self.log_view.setStyleSheet(
            "QPlainTextEdit{background:#1e2228;color:#c9d1d9;"
            "border:1px solid #3a4250;border-radius:8px;font-family:Consolas,"
            "'Cascadia Mono',monospace;font-size:9.5pt;}")
        lay.addWidget(self.log_view)
        btn_clear = PushButton("清空日志", icon=FIF.DELETE)
        btn_clear.clicked.connect(self.log_view.clear)
        self.log_view.setPlaceholderText("执行日志会打在这里")
        lay.addWidget(_row(btn_clear))
        return box

    def _log(self, text):
        self.log_view.appendPlainText(str(text))
        self.log_view.verticalScrollBar().setValue(
            self.log_view.verticalScrollBar().maximum())
        QApplication.processEvents()

    def _pipeline_dict(self):
        try:
            data = json.loads(self.task_edit.toPlainText())
        except Exception as exc:  # noqa: BLE001
            _tip("error", "JSON 解析失败", str(exc), self)
            return None
        if not isinstance(data, dict):
            _tip("error", "JSON 结构不对", "顶层必须是 {节点名: {...}} 的对象", self)
            return None
        return data

    def check_task(self):
        data = self._pipeline_dict()
        if data is None:
            return
        nodes, errors = av.parse_pipeline(data)
        self._log(f"校验：{len(nodes)} 个节点"
                  + (f"，{len(errors)} 处问题" if errors else "，无问题"))
        for e in errors:
            self._log(f"  ⚠ {e}")
        if not errors:
            _tip("success", "校验通过", f"{len(nodes)} 个节点，引用关系正常", self)

    def _frame_provider(self, win):
        """给 Runner 用的抓帧回调：每次重新抓一帧（MAA 也是每步重新截图）。"""
        if win is None:
            return (None, (0, 0), 0.0)
        try:
            return av.capture_window(win)
        except Exception:  # noqa: BLE001
            return (None, (0, 0), 0.0)

    def run_task(self, step_only=False):
        data = self._pipeline_dict()
        if data is None:
            return
        win = self._selected_window()
        if win is None:
            _tip("warning", "提示", "先在「① 感知」里选一个目标窗口", self)
            return
        dry = self.dry_switch.isChecked()
        runner = av.PipelineRunner(self._frame_provider, TEMPLATE_DIR,
                                   on_log=self._log)
        self._log("=" * 46)
        self._log(f"开始执行（{'演练：不会真点鼠标' if dry else '⚠ 真点模式'}）")
        if step_only:
            nodes, errors = av.parse_pipeline(data)
            for e in errors:
                self._log(f"⚠ {e}")
            if not nodes:
                return
            name = next(iter(nodes))
            frame, origin, _ = self._frame_provider(win)
            if frame is None:
                self._log("抓帧失败")
                return
            res = runner.step(nodes[name], frame, dry_run=dry, origin=origin)
            self._hits = [res.match] if res.match else []
            self.shot_view.set_frame(frame, self._hits)
            return
        trace = runner.run(data, win=win, dry_run=dry)
        hits = [t.match for t in trace if t.match]
        self._hits = hits
        self.shot_view.set_hits(hits)
        ok = sum(1 for t in trace if t.hit)
        self._log(f"执行结束：{len(trace)} 步，命中 {ok} 步")
        _tip("success" if hits else "warning", "任务结束",
             f"{len(trace)} 步 / 命中 {ok} 步", self)

    # ---------------- ④ 内置演示场景 ---------------- #
    def _card_demo(self):
        box, lay = _card("④ 内置演示场景（一键跑通全链路）",
                         "不用准备任何素材：点开场景窗（一个自绘的「游戏画面」，"
                         "目标图标每次随机换位），再点「跑通演示」，程序会抓帧 → "
                         "模板匹配找到图标 → 按内置管线点它。")
        btn_open = PushButton("打开演示场景", icon=FIF.VIEW)
        btn_open.clicked.connect(self.open_demo_scene)
        btn_shuffle = PushButton("随机换位", icon=FIF.SYNC)
        btn_shuffle.clicked.connect(self.shuffle_demo_scene)
        btn_go = PrimaryPushButton("跑通演示", icon=FIF.ROBOT)
        btn_go.clicked.connect(self.run_demo)
        lay.addWidget(_row(btn_open, btn_shuffle, btn_go))
        self.demo_status = CaptionLabel("尚未打开演示场景")
        lay.addWidget(self.demo_status)
        return box

    def open_demo_scene(self):
        if self.demo_scene is None:
            self.demo_scene = DemoScene()
        self.demo_scene.show()
        self.demo_scene.raise_()
        self._demo_dpr = float(self.demo_scene.devicePixelRatioF() or 1.0)
        self.demo_status.setText(
            f"演示场景已打开（{self.demo_scene.width()}×"
            f"{self.demo_scene.height()} 逻辑像素，缩放 {self._demo_dpr:.2f}×）")
        # 把场景窗也塞进下拉框，方便手动抓帧
        return self.demo_scene

    def shuffle_demo_scene(self):
        if self.demo_scene is None:
            self.open_demo_scene()
        self.demo_scene.relayout()
        self.demo_status.setText("已随机换位 —— 再点「跑通演示」，"
                                 "这次命中的坐标会和上次不同")

    def _write_demo_template(self):
        """按设备像素比渲染内置目标图标，落盘成模板 PNG。"""
        os.makedirs(TEMPLATE_DIR, exist_ok=True)
        img = render_target_template(DEMO_ICON_SIZE, self._demo_dpr or 1.0)
        path = os.path.join(TEMPLATE_DIR, "__demo_target__.png")
        if not img.save(path):
            raise RuntimeError("模板写入失败")
        return path

    def run_demo(self):
        scene = self.demo_scene or self.open_demo_scene()
        scene.raise_()
        scene.activateWindow()
        QApplication.processEvents()
        time.sleep(0.25)          # 让窗口真正提到最前再抓帧
        QApplication.processEvents()
        # 场景可能被拖到别的屏上，缩放比要现取（模板按它渲染才和抓帧尺寸对齐）
        self._demo_dpr = float(scene.devicePixelRatioF() or 1.0)

        hwnd = int(scene.winId())
        win = av.window_info(hwnd)
        if win is None:
            _tip("error", "取窗口失败", "拿不到演示场景的窗口句柄", self)
            return
        try:
            self._write_demo_template()
        except Exception as exc:  # noqa: BLE001
            _tip("error", "生成模板失败", str(exc), self)
            return

        # 记下用户选的窗口（跑完恢复），把演示场景临时设为目标
        prev_hwnd = self.win_combo.currentData()
        self.win_combo.addItem("▶ 演示场景（临时）", userData=hwnd)
        self.win_combo.setCurrentIndex(self.win_combo.count() - 1)
        try:
            frame = self.take_shot(quiet=True)
            if frame is None:
                return
            self._log("=" * 46)
            self._log("【内置演示】抓帧完成，开始跑内置管线")
            runner = av.PipelineRunner(self._frame_provider, TEMPLATE_DIR,
                                       on_log=self._log)
            trace = runner.run(av.DEMO_PIPELINE, win=win,
                               dry_run=self.dry_switch.isChecked())
            hits = [t.match for t in trace if t.match]
            self._hits = hits
            self.shot_view.set_hits(hits)
            if hits:
                self.demo_status.setText(
                    f"演示完成：找到目标 @ ({hits[0].x},{hits[0].y})，"
                    f"得分 {hits[0].score:.3f}"
                    f"（{'演练，未真点' if self.dry_switch.isChecked() else '已真点'}）")
            else:
                self.demo_status.setText("演示未命中：请确认场景窗没有被遮挡，"
                                         "或换个位置再试")
        finally:
            if prev_hwnd is not None:
                self.win_combo.setCurrentIndex(0)
                for i in range(self.win_combo.count()):
                    if self.win_combo.itemData(i) == prev_hwnd:
                        self.win_combo.setCurrentIndex(i)
                        break

    # ---------------- ⑤ 说明 ---------------- #
    def _card_about(self):
        box, lay = _card("⑤ 这套设计跟 MAA 的对应关系",
                         "本页是「参考设计」而非 MAA 的移植：引擎侧 100% 自研，"
                         "只借它的分层与任务描述格式。")
        lines = [
            "· 感知 / 抓帧：MAA 用 ControlUnit 抽象（ADB 截屏、Win32 窗口截图）"
            "—— 本页用 auto_vision_core.capture_window（屏幕拷贝 + PrintWindow 兜底）。",
            "· 认知 / 识别：MAA 是模板匹配 → OCR → 神经网络的「三级火力」"
            "—— 本页实现前两级里的模板匹配与色块，OCR 只留了节点占位。",
            "· 决策 / 任务：字段名照抄 MAA tasks.json 的语义"
            "（roi / template / threshold / action / next / exceededNext / maxTimes / preDelay / postDelay）。",
            "· 行动 / 点击：MAA 走 ADB input 或 minitouch；本页用 SendInput "
            "绝对坐标点击（多屏、负坐标副屏也对）。",
            "· 默认演练：只识别、只标注，不动鼠标 —— 要真点必须手动关掉「演练模式」。",
            "· 边界：视觉 + 鼠标注入不改内存，但自动化别人家的界面仍属灰色地带，"
            "请只用于自己的窗口与自己的程序。",
        ]
        for t in lines:
            lab = BodyLabel(t, box)
            lab.setWordWrap(True)
            lay.addWidget(lab)
        return box
