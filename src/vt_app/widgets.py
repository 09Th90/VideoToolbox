# -*- coding: utf-8 -*-
# @version 3.3.1
"""通用控件基建（原 video_toolbox_qt.py 同名代码，逐字下沉）。

卡片工厂 / 日志视图 / 行布局 / 页面壳 / 导航宽度——所有页面共用，
页面拆出后一律 ``from vt_app.widgets import ...``，禁止反向 import 入口。
"""
import os
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QPainter, QPen,
                           QTextCursor)
from PySide6.QtWidgets import (QAbstractButton, QApplication, QHBoxLayout,
                               QLabel, QSizePolicy, QVBoxLayout, QWidget)

from vt_fluent import (BodyLabel, CardWidget, CaptionLabel, ScrollArea,
                       SimpleCardWidget, StrongBodyLabel, SubtitleLabel,
                       TextEdit, TitleLabel)

import ui_theme

# ========== 导航宽度（按最长项文字自适应） ==========
# 导航项宽度的构成（见 qfluentwidgets.components.navigation.navigation_widget）：
#   1. FluentWindow 左侧栏 → panel 左侧内边距（NaviPanel 边距 4+4）
#   2. Expand 按钮 40px（收起态图标条宽度）
#   3. 图标与文字之间的间距
#   4. 文字宽度（QFontMetrics.horizontalAdvance）
#   5. 右侧呼吸空间
NAV_BUTTON_W = 40          # 收起态按钮宽度，也是展开态图标区宽度
NAV_ICON_TEXT_GAP = 14     # 图标右缘到文字左缘
NAV_SIDE_PADDING = 8       # panel 左右各自的内边距
NAV_TEXT_TAIL = 6          # 文字右侧余量，避免紧贴滚动条


def nav_width_for(texts, font=None):
    """按导航项文案计算展开态宽度：最长一项文字宽 + 2 个字符 + 固有占位。

    用户要求「单行最大字数宽度 + 2 个字符的宽度」——2 个字符用中文字宽
    （em 宽）计，保证任何文案下右侧都留出约两个汉字的空间。

    字体默认取**应用字体**（main() 里 app.setFont 设定的那个）；只有显式传入
    font、或 QApplication 尚未建立时才回退雅黑 9pt。硬编码字体名会在「系统装的
    字体与 app 字体不同」时量出偏差宽度，表现为「程序刚开启时导航宽度不对、
    过一会儿才收敛」（v1.11.0 修正）。
    """
    if font is None:
        try:
            font = QApplication.font()
        except Exception:  # noqa: BLE001
            font = None
    fm = QFontMetrics(font or QFont("Microsoft YaHei UI", 9))
    longest = max((fm.horizontalAdvance(t or "") for t in texts), default=0)
    two_chars = fm.horizontalAdvance("字字")
    return max(200, (NAV_SIDE_PADDING * 2 + NAV_BUTTON_W + NAV_ICON_TEXT_GAP
            + longest + two_chars + NAV_TEXT_TAIL))


# ========== 通用控件 ==========
class LogView(CardWidget):
    """日志卡片：等宽字体、按级别着色、自动滚动到底。

    v1.13.x 主题感知：深色主题保持「控制台」深底，浅色主题换浅底深字，
    跟随主题档/系统深浅实时切换（不再固定深底——浅色页面里一块黑日志
    过于突兀）。
    """

    def __init__(self, title="运行日志", height=150, parent=None):
        super().__init__(parent)
        self.text = TextEdit(self)
        self.text.setReadOnly(True)
        self.text.setMinimumHeight(height)
        # 文档限行：日志区长期运行会积累上万行，富文本插入与光标滚动成本随
        # 行数线性上升——并行下载时数千条日志会把主线程塞死。旧行自动丢弃。
        self.text.document().setMaximumBlockCount(1500)
        self._apply_log_theme()
        # 主题切换时重应用样式表（ui_theme 回调；weakref 不拖住本控件）
        ui_theme.connect_theme(self, lambda v: v._apply_log_theme())

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 14, 20, 18)
        lay.setSpacing(10)
        lay.addWidget(CaptionLabel(title, self))
        lay.addWidget(self.text)

    def _apply_log_theme(self):
        """按当前主题给日志文本区上色（深色=控制台深底，浅色=浅底深字）。"""
        t = ui_theme.tokens()
        # 固定底色的由来：qfluentwidgets 的 TextEdit 在深色主题下不会自动
        # 变色，默认白底放在深色卡片里非常突兀——改为按主题 token 上色。
        self.text.setStyleSheet(
            f"TextEdit{{background:{t['log_bg']};color:{t['log_text']};"
            "border:none;"
            "font-family:Consolas,'Microsoft YaHei UI';font-size:12px;}")

    def _colors(self):
        """按级别着色（浅色主题下把过浅的级别色加深，保证白底可读）。"""
        if ui_theme.is_dark():
            return {"dim": "#8A8A8A", "ok": "#2E9E5B",
                    "err": "#D64545", "info": "#B0B0B0",
                    "think": "#8E7CC3"}   # AI 校准思考链（紫，区别于正文）
        return {"dim": "#787F87", "ok": "#1F8A4C",
                "err": "#C0392B", "info": "#4A5057",
                "think": "#6A5ACD"}

    def line(self, msg, level="dim"):
        colors = self._colors()
        color = colors.get(level, colors["dim"])
        stamp = datetime.now().strftime("%H:%M:%S")
        t = ui_theme.tokens()
        self.text.setTextColor(QColor(t["log_dim"]))
        self.text.insertPlainText(f"{stamp}  ")
        self.text.setTextColor(QColor(color))
        self.text.insertPlainText(str(msg) + "\n")
        self.text.setTextColor(QColor(t["log_text"]))
        self.text.moveCursor(QTextCursor.End)
        self.text.ensureCursorVisible()

    def clear(self):
        self.text.clear()


def card(title=None, caption=None):
    """新建一张卡片，返回 (卡片, 其内部竖向布局)。

    卡片会被放进滚动区，说明文字不自动换行（避免 heightForWidth 与滚动区
    互相触发重排）；文案一律保持一行能放下的长度。
    v1.13.x 界面美化：换用 ui_theme.UICard 统一皮肤（圆角 10、1px 描边、
    hover 提亮），所有页面共用一套卡片观感。
    """
    box = ui_theme.UICard()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(14, 12, 14, 14)
    lay.setSpacing(8)
    if title:
        lay.addWidget(StrongBodyLabel(title, box))
    if caption:
        lay.addWidget(fit_caption(CaptionLabel(caption, box)))
    return box, lay


class AccentDot(QAbstractButton):
    """主题色预设圆点（自绘）。

    之前用 qfluentwidgets PushButton + QSS 上色，有两个绕不开的坑：
    ① QSS 的 background 在**首帧**不生效（样式缓存），必须等鼠标碰一下
    才上色；② qfluentwidgets 切主题/页面首显时会按 FluentStyleSheet 给
    控件重新 setStyleSheet，把自定义背景**覆盖回默认灰**。修补（repolish、
    showEvent 重刷）都只是治标，用户实测仍是「主题色按键必须点击一次才会
    显示」。圆点本质是个色块，直接自绘最稳：无 QSS、无样式缓存、无主题
    重刷覆盖，任何主题下首帧即为最终效果。
    """

    def __init__(self, hexcolor, parent=None):
        super().__init__(parent)
        self._color = QColor(hexcolor)
        self._selected = False
        self._hover = False
        self.setFixedSize(24, 24)
        self.setCursor(Qt.PointingHandCursor)

    def set_dot_color(self, hexcolor):
        c = QColor(hexcolor)
        if c.isValid() and c != self._color:
            self._color = c
            self.update()

    def set_selected(self, on):
        on = bool(on)
        if on != self._selected:
            self._selected = on
            self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(1, 1, -1, -1)
        p.setPen(Qt.NoPen)
        p.setBrush(self._color)
        p.drawEllipse(r)
        # 选中描白圈，hover 描浅灰圈（与旧 QSS 行为一致）
        if self._selected:
            ring = QColor("#FFFFFF")
        elif self._hover:
            ring = QColor("#E8EAED")
        else:
            return
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(ring, 2))
        p.drawEllipse(r.adjusted(1, 1, -1, -1))


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


def srow(label, *widgets):
    """设置页输入行：标签 + 输入控件，第一个控件 stretch=1 吃满剩余宽度。

    与 label_row 的区别：label_row 行尾有 addStretch(1)，把布局里额外的横向
    空白全部吸到右侧，输入框只保持 sizeHint 宽度——长 URL/路径被横向截断
    （v1.13.0「设置页文字显示不全」的根因）。这里让输入框吃掉行内多余宽度，
    窗口放大时输入框随之变宽、长文本完整显示；后续按钮自然靠右排列。
    """
    holder = QWidget()
    lay = QHBoxLayout(holder)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(8)
    lay.addWidget(BodyLabel(label, holder))
    ws = [w for w in widgets if w is not None]
    if ws:
        lay.addWidget(ws[0], 1)
        for w in ws[1:]:
            lay.addWidget(w)
    return holder


def expand_h(widget, minimum=160):
    """让输入框横向自适应填满所在行（长 URL/路径不被截断）。

    v1.13.0：最小宽度由 360 → 220 → 160 逐步收紧——窗口缩小 / 导航变宽 /
    换到低分辨率屏时，卡片内的输入行不再把卡片撑出可视范围（页面扭曲的
    主要来源之一）；Expanding 策略保证宽度允许时仍会吃满整行。输入框在
    窄于内容时内部自动滚动，不丢失已有文字。
    """
    try:
        widget.setMinimumWidth(minimum)
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    except Exception:
        pass
    return widget


def fit_spin(spin, width, align=Qt.AlignRight | Qt.AlignVCenter):
    """数值框统一宽度与文字位置：固定宽度 + 数字右对齐。

    SpinBox 的右侧步进按钮占固定宽度，框太窄时编辑区会被压到只剩光标；
    数值右对齐后数字贴近按钮，长文本（如「关闭（不限）」）也不容易被裁。
    """
    spin.setFixedWidth(width)
    try:
        spin.setAlignment(align)
    except Exception:  # noqa: BLE001
        pass
    return spin


def fit_caption(label):
    """说明文字「宁可被裁也不撑宽卡片」（滚动区内不能换行的统一兜底）。

    QScrollArea 内一律不能用自动换行标签——heightForWidth 与滚动区会互相触发
    重排，事件循环卡死。于是长文案只有两种命运：把卡片撑宽（页面横向滚动又被
    禁用，结果就是超出可视范围、按钮被挤出屏幕），或者被裁。
    这里把水平方向的 sizeHint 置为忽略（Ignored 会连带忽略最小提示），
    卡片宽度改由输入框 / 按钮决定，文案再长也不会撑破布局。
    v1.11.0 起统一应用于 card() 的说明与各页手写的提示标签。
    """
    try:
        label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        label.setMinimumWidth(0)
    except Exception:
        pass
    return label


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


class PageHeader(QWidget):
    """v3 页头：20px 标题 + 11px 说明 + 右侧操作区。"""

    def __init__(self, title, subtitle="", parent=None):
        super().__init__(parent)
        self.setObjectName("PageHeader")
        self.setFixedHeight(54)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        self.title = QLabel(title, self)
        self.title.setObjectName("PageHeaderTitle")
        self.cap = QLabel(subtitle, self)
        self.cap.setObjectName("PageHeaderCaption")
        col.addWidget(self.title)
        col.addWidget(self.cap)
        lay.addLayout(col, 1)
        self.right = QHBoxLayout()
        self.right.setContentsMargins(0, 0, 0, 0)
        self.right.setSpacing(6)
        lay.addLayout(self.right)
        self._apply_theme()
        ui_theme.connect_theme(self, lambda w: w._apply_theme())

    def _apply_theme(self):
        t = ui_theme.tokens()
        self.setStyleSheet(
            "QLabel#PageHeaderTitle{font-size:20px;font-weight:600;color:%s;"
            "background:transparent;}"
            "QLabel#PageHeaderCaption{font-size:10.5px;color:%s;"
            "background:transparent;}" % (t["text"], t["text_dim"]))

    def add_action(self, widget):
        self.right.addWidget(widget)


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
        outer.setContentsMargins(22, 16, 22, 14)
        outer.setSpacing(8)
        self.title_label = SubtitleLabel(title, self)
        self.title_label.setObjectName("PageTitle")
        outer.addWidget(self.title_label)
        self.cap = None
        if subtitle:
            cap = CaptionLabel(subtitle, self)
            cap.setWordWrap(True)
            outer.addWidget(cap)
            # v1.13.x：暴露给子类。自动换行标签的 heightForWidth 会在首次布局时
            # 再算一遍高度（1 行 → 2 行），下方内容整体下移，表现就是「进页面
            # 上下闪一下」。子类可 `fit_caption(self.cap)` 把它压成不参与重排。
            self.cap = cap

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


class TabPage(QWidget):
    """页内子板块的内容壳：可滚动、无大标题（标题由页内分段控件承担）。

    v1.13.0：页面合并（音画合并并入视频下载、字幕校准并入字幕处理）后，
    被合并的板块放进页内分段（SegmentedWidget）+ 本壳，各自独立滚动、
    互不挤占。与 ScrollPage 的区别只是没有 SubtitleLabel 大标题；其余
    （滚动区 / 卡片宽度跟随视口 / 水平滚动禁用）完全一致。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.view = self
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)
        self.area = ScrollArea(self)
        self.area.setWidgetResizable(True)
        self.area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.area.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        self.holder = QWidget(self.area)
        self.holder.setStyleSheet("QWidget{background:transparent;}")
        self.content_lay = QVBoxLayout(self.holder)
        self.content_lay.setContentsMargins(22, 12, 22, 14)
        self.content_lay.setSpacing(10)
        self.area.setWidget(self.holder)
        outer.addWidget(self.area, 1)
        self.vbox = self.content_lay

    def add_card(self, widget, stretch=0):
        self.vbox.addWidget(widget, stretch)


def tab_caption(text, parent=None):
    """子板块顶部的灰色说明（TabPage 无大标题，用一行说明补上下文）。"""
    cap = fit_caption(CaptionLabel(text, parent))
    cap.setTextColor("#8a8a8a", "#9a9a9a")
    return cap


class _MergeDropSlot(SimpleCardWidget):
    """拖放槽：显示已选文件名，点一下可浏览，也能从资源管理器拖入。

    原 MergePage 私有（名沿用），2026-11-15 功能解耦阶段③下沉为共享基建
    （合并/切片两页共用）。只收指定后缀的文件；拖入其它类型时 ignore()，
    事件继续冒泡给所在页，由页级分派按后缀自动归位（视频→视频槽、音频→
    音频槽、字幕→字幕槽）——于是「拖到槽上」与「拖到页面空白处」结果一致，
    用户不必瞄准。
    """

    def __init__(self, title, hint, exts, on_pick, parent=None):
        super().__init__(parent)
        self._exts = set(exts)
        self._on_pick = on_pick
        self._hint = hint
        self._path = ""
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(4)
        lay.addWidget(StrongBodyLabel(title, self))
        self.path_label = fit_caption(BodyLabel(hint, self))
        lay.addWidget(self.path_label)
        self._render()

    def _render(self):
        if self._path:
            self.path_label.setText(os.path.basename(self._path))
            self.path_label.setToolTip(self._path)
            self.path_label.setTextColor("#1a1a1a", "#e8e8e8")
        else:
            self.path_label.setText(self._hint)
            self.path_label.setToolTip("")
            self.path_label.setTextColor("#8a8a8a", "#9a9a9a")

    def path(self):
        return self._path

    def set_path(self, path):
        self._path = path or ""
        self._render()

    def matches(self, path):
        return os.path.splitext(path or "")[1].lower() in self._exts

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._on_pick()
        super().mouseReleaseEvent(e)

    def dragEnterEvent(self, e):
        urls = e.mimeData().urls() if e.mimeData().hasUrls() else []
        for u in urls:
            p = u.toLocalFile()
            if p and os.path.isfile(p) and self.matches(p):
                e.acceptProposedAction()
                return
        e.ignore()

    def dropEvent(self, e):
        urls = e.mimeData().urls() if e.mimeData().hasUrls() else []
        for u in urls:
            p = u.toLocalFile()
            if p and os.path.isfile(p) and self.matches(p):
                self.set_path(p)
                e.acceptProposedAction()
                return
        e.ignore()