# -*- coding: utf-8 -*-
# @version 2.8.0
"""vt_fluent 反馈族（自研，替代 qfluentwidgets 的 info_bar / dialog_box）。

行为契约（对齐上游 1.11.3）：
· InfoBar：info/success/warning/error 四类工厂 + 位置/队列管理
  （同位置多条自动叠放、消失后其余上移 200ms）、fade-out 200ms、
  duration<0 常驻、可关闭按钮、自定义背景色、addWidget 扩展位；
· MaskDialogBase：遮罩对话框（淡入 200ms/淡出 100ms、点遮罩可关、
  可拖动、阴影、居中卡片）；
· MessageBoxBase：表单类对话框基类（yesButton/cancelButton/validate/
  hideYesButton/hideCancelButton/viewLayout）；
· MessageBox：标题+正文+按钮组的标准消息框（yesSignal/cancelSignal）。

CJK 感知文本折行（TextWrap）随族内置；InfoBar 图标为语义彩色双变体
（light/dark 各一套，不做 fill 替换，仅 Info 的圆底染主题色）。
"""

import sys
import unicodedata
import weakref
from functools import lru_cache

from PySide6.QtCore import (QEasingCurve, QEvent, QObject, QParallelAnimationGroup,
                            QPoint, QPropertyAnimation, QRectF, QSize, Qt, QTimer,
                            Signal)
from PySide6.QtGui import QColor, QIcon, QPainter, QResizeEvent
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QApplication, QDialog, QFrame, QGraphicsDropShadowEffect,
                               QGraphicsOpacityEffect, QHBoxLayout, QLabel,
                               QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from ._anim import SmoothScrollDelegate
from ._buttons import PrimaryPushButton, TransparentToolButton
from ._icon import FluentIcon, FluentIconBase, _fill_swapped, drawIcon, toQIcon
from ._icons_data import EXTRA_ART
from ._theme import FluentStyleSheet, isDarkTheme, setFont, themeColor


class TextWrap:
    """CJK 感知折行（对齐上游 TextWrap 的使用面：wrap(text, width, once)）。"""

    @classmethod
    @lru_cache(maxsize=128)
    def get_width(cls, char: str) -> int:
        return 2 if unicodedata.east_asian_width(char) in ("F", "W") else 1

    @classmethod
    @lru_cache(maxsize=32)
    def get_text_width(cls, text: str) -> int:
        return sum(cls.get_width(c) for c in text)

    @classmethod
    def wrap(cls, text: str, width: int, once: bool = True):
        """按显示宽度折行（CJK 记 2），返回 (文本, 是否发生折行)。"""
        width = int(width)
        lines = text.splitlines() or [text]
        is_wrapped = False
        wrapped = []

        for line in lines:
            if cls.get_text_width(line) <= width:
                wrapped.append(line)
                continue

            is_wrapped = True
            cur, cur_w = [], 0
            for ch in line:
                w = cls.get_width(ch)
                if cur_w + w > width and cur:
                    wrapped.append("".join(cur))
                    if once:
                        wrapped.append(line[len("".join(wrapped)):].rstrip())
                        return "".join(wrapped), True
                    cur, cur_w = [], 0
                cur.append(ch)
                cur_w += w
            if cur:
                wrapped.append("".join(cur))

        return "".join(wrapped), is_wrapped


def _info_bar_position():
    """取 B0 定义在包入口的 InfoBarPosition（延迟导入避免循环）。"""
    from . import InfoBarPosition
    return InfoBarPosition


_InfoBarPosition = _info_bar_position()


class InfoBarIcon:
    """信息条图标（语义彩色，light/dark 双变体）。"""

    INFORMATION = "Info"
    SUCCESS = "Success"
    WARNING = "Warning"
    ERROR = "Error"

    @staticmethod
    def key(name: str, dark: bool = None) -> str:
        dark = isDarkTheme() if dark is None else dark
        return "images_info_bar_%s_%s" % (name, "dark" if dark else "light")

    @staticmethod
    def svg(name: str, dark: bool = None) -> str:
        return EXTRA_ART[InfoBarIcon.key(name, dark)]


def _render_svg(svg: str, painter, rect):
    QSvgRenderer(svg.encode()).render(painter, QRectF(rect))


class InfoIconWidget(QWidget):
    """信息条图标（36×36，Info 型圆底染主题色，对齐上游 InfoIconWidget）。"""

    def __init__(self, icon, parent=None):
        super().__init__(parent=parent)
        self.setFixedSize(36, 36)
        self.icon = icon

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing |
                               QPainter.SmoothPixmapTransform)
        rect = QRectF(10, 10, 15, 15)

        if isinstance(self.icon, str):
            svg = InfoBarIcon.svg(self.icon)
            if self.icon == InfoBarIcon.INFORMATION:
                # 只染首个 fill（圆底），保留白色字形
                svg = _fill_swapped(svg, themeColor().name())
            _render_svg(svg, painter, rect)
        else:
            drawIcon(self.icon, painter, rect)


class InfoBar(QFrame):
    """信息条（对齐上游 InfoBar）。

    Constructors
    ------------
    * InfoBar(`icon`, `title`, `content`, `orient`=Qt.Horizontal,
              `isClosable`=True, `duration`=1000,
              `position`=InfoBarPosition.TOP_RIGHT, `parent`=None)
    """

    closedSignal = Signal()

    def __init__(self, icon, title: str, content: str,
                 orient=Qt.Horizontal, isClosable=True, duration=1000,
                 position=None, parent=None):
        super().__init__(parent=parent)
        self.title = title
        self.content = content
        self.orient = orient
        self.icon = icon
        self.duration = duration
        self.isClosable = isClosable
        self.position = (_InfoBarPosition.TOP_RIGHT if position is None
                         else position)

        self.titleLabel = QLabel(self)
        self.contentLabel = QLabel(self)
        self.closeButton = TransparentToolButton(FluentIcon.CLOSE, self)
        self.iconWidget = InfoIconWidget(icon)

        self.hBoxLayout = QHBoxLayout(self)
        self.textLayout = (QHBoxLayout() if self.orient == Qt.Horizontal
                           else QVBoxLayout())
        self.widgetLayout = (QHBoxLayout() if self.orient == Qt.Horizontal
                             else QVBoxLayout())

        self.opacityEffect = QGraphicsOpacityEffect(self)
        self.opacityAni = QPropertyAnimation(self.opacityEffect, b"opacity", self)

        self.lightBackgroundColor = None
        self.darkBackgroundColor = None

        self._initWidget()

    def _initWidget(self):
        self.opacityEffect.setOpacity(1)
        self.setGraphicsEffect(self.opacityEffect)

        self.closeButton.setFixedSize(36, 36)
        self.closeButton.setIconSize(QSize(12, 12))
        self.closeButton.setCursor(Qt.PointingHandCursor)
        self.closeButton.setVisible(self.isClosable)

        self._setQss()
        self._initLayout()

        self.closeButton.clicked.connect(self.close)

    def _initLayout(self):
        self.hBoxLayout.setContentsMargins(6, 6, 6, 6)
        self.hBoxLayout.setSizeConstraint(QVBoxLayout.SetMinimumSize)
        self.textLayout.setSizeConstraint(QHBoxLayout.SetMinimumSize)
        self.textLayout.setAlignment(Qt.AlignTop)
        self.textLayout.setContentsMargins(1, 8, 0, 8)

        self.hBoxLayout.setSpacing(0)
        self.textLayout.setSpacing(5)

        self.hBoxLayout.addWidget(self.iconWidget, 0, Qt.AlignTop | Qt.AlignLeft)
        self.textLayout.addWidget(self.titleLabel, 1, Qt.AlignTop)
        self.titleLabel.setVisible(bool(self.title))

        if self.orient == Qt.Horizontal:
            self.textLayout.addSpacing(7)

        self.textLayout.addWidget(self.contentLabel, 1, Qt.AlignTop)
        self.contentLabel.setVisible(bool(self.content))
        self.hBoxLayout.addLayout(self.textLayout)

        if self.orient == Qt.Horizontal:
            self.hBoxLayout.addLayout(self.widgetLayout)
            self.widgetLayout.setSpacing(10)
        else:
            self.textLayout.addLayout(self.widgetLayout)

        self.hBoxLayout.addSpacing(12)
        self.hBoxLayout.addWidget(self.closeButton, 0, Qt.AlignTop | Qt.AlignLeft)

        self._adjustText()

    def _setQss(self):
        self.titleLabel.setObjectName("titleLabel")
        self.contentLabel.setObjectName("contentLabel")
        if isinstance(self.icon, str):
            self.setProperty("type", self.icon)
        FluentStyleSheet.INFO_BAR.apply(self)

    def _fadeOut(self):
        try:
            self.opacityAni.setDuration(200)
            self.opacityAni.setStartValue(1)
            self.opacityAni.setEndValue(0)
            self.opacityAni.finished.connect(self.close)
            self.opacityAni.start()
        except RuntimeError:
            pass

    def _adjustText(self):
        w = 900 if not self.parent() else (self.parent().width() - 50)
        chars = max(min(w / 10, 120), 30)
        self.titleLabel.setText(TextWrap.wrap(self.title, chars, False)[0])
        chars = max(min(w / 9, 120), 30)
        self.contentLabel.setText(TextWrap.wrap(self.content, chars, False)[0])
        self.adjustSize()

    def addWidget(self, widget: QWidget, stretch=0):
        self.widgetLayout.addSpacing(6)
        align = Qt.AlignTop if self.orient == Qt.Vertical else Qt.AlignVCenter
        self.widgetLayout.addWidget(widget, stretch, Qt.AlignLeft | align)

    def setCustomBackgroundColor(self, light, dark):
        self.lightBackgroundColor = QColor(light)
        self.darkBackgroundColor = QColor(dark)
        self.update()

    def eventFilter(self, obj, e):
        if obj is self.parent():
            if e.type() in (QEvent.Resize, QEvent.WindowStateChange):
                self._adjustText()
        return super().eventFilter(obj, e)

    def closeEvent(self, e):
        self.closedSignal.emit()
        self.deleteLater()
        e.ignore()

    def showEvent(self, e):
        self._adjustText()
        super().showEvent(e)

        if self.duration >= 0:
            QTimer.singleShot(self.duration, self._fadeOut)

        if (self.position is not None
                and self.position != _InfoBarPosition.NONE):
            InfoBarManager.make(self.position).add(self)

        if self.parent():
            self.parent().installEventFilter(self)

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.lightBackgroundColor is None:
            return
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self.darkBackgroundColor if isDarkTheme()
                         else self.lightBackgroundColor)
        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.drawRoundedRect(rect, 6, 6)

    @classmethod
    def new(cls, icon, title, content, orient=Qt.Horizontal, isClosable=True,
            duration=1000, position=None, parent=None):
        w = InfoBar(icon, title, content, orient, isClosable, duration,
                    _InfoBarPosition.TOP_RIGHT if position is None else position,
                    parent)
        w.show()
        return w

    @classmethod
    def info(cls, title, content, orient=Qt.Horizontal, isClosable=True,
             duration=1000, position=None, parent=None):
        return cls.new(InfoBarIcon.INFORMATION, title, content, orient,
                       isClosable, duration, position, parent)

    @classmethod
    def success(cls, title, content, orient=Qt.Horizontal, isClosable=True,
                duration=1000, position=None, parent=None):
        return cls.new(InfoBarIcon.SUCCESS, title, content, orient, isClosable,
                       duration, position, parent)

    @classmethod
    def warning(cls, title, content, orient=Qt.Horizontal, isClosable=True,
                duration=1000, position=None, parent=None):
        return cls.new(InfoBarIcon.WARNING, title, content, orient, isClosable,
                       duration, position, parent)

    @classmethod
    def error(cls, title, content, orient=Qt.Horizontal, isClosable=True,
              duration=1000, position=None, parent=None):
        return cls.new(InfoBarIcon.ERROR, title, content, orient, isClosable,
                       duration, position, parent)


class InfoBarManager(QObject):
    """信息条位置管理器（对齐上游：叠放/滑入/消失后其余上移）。"""

    _instance = None
    managers = {}

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._inited = False
        return cls._instance

    def __init__(self):
        if getattr(self, "_inited", False):
            return
        super().__init__()
        self.spacing = 16
        self.margin = 24
        self.infoBars = weakref.WeakKeyDictionary()
        self.aniGroups = weakref.WeakKeyDictionary()
        self.slideAnis = []
        self.dropAnis = []
        self._inited = True

    def add(self, infoBar):
        p = infoBar.parent()
        if not p:
            return
        if p not in self.infoBars:
            p.installEventFilter(self)
            self.infoBars[p] = []
            self.aniGroups[p] = QParallelAnimationGroup(self)
        if infoBar in self.infoBars[p]:
            return

        if self.infoBars[p]:
            dropAni = QPropertyAnimation(infoBar, b"pos")
            dropAni.setDuration(200)
            self.aniGroups[p].addAnimation(dropAni)
            self.dropAnis.append(dropAni)
            infoBar.setProperty("dropAni", dropAni)

        self.infoBars[p].append(infoBar)
        slideAni = self._createSlideAni(infoBar)
        self.slideAnis.append(slideAni)
        infoBar.setProperty("slideAni", slideAni)
        infoBar.closedSignal.connect(lambda: self.remove(infoBar))
        slideAni.start()

    def remove(self, infoBar):
        p = infoBar.parent()
        if p not in self.infoBars or infoBar not in self.infoBars[p]:
            return
        self.infoBars[p].remove(infoBar)

        dropAni = infoBar.property("dropAni")
        if dropAni:
            self.aniGroups[p].removeAnimation(dropAni)
            if dropAni in self.dropAnis:
                self.dropAnis.remove(dropAni)
        slideAni = infoBar.property("slideAni")
        if slideAni in self.slideAnis:
            self.slideAnis.remove(slideAni)

        self._updateDropAni(p)
        self.aniGroups[p].start()

    def _createSlideAni(self, infoBar):
        slideAni = QPropertyAnimation(infoBar, b"pos")
        slideAni.setEasingCurve(QEasingCurve.OutQuad)
        slideAni.setDuration(200)
        slideAni.setStartValue(self._slideStartPos(infoBar))
        slideAni.setEndValue(self._pos(infoBar))
        return slideAni

    def _updateDropAni(self, parent):
        for bar in self.infoBars.get(parent, []):
            ani = bar.property("dropAni")
            if not ani:
                continue
            ani.setStartValue(bar.pos())
            ani.setEndValue(self._pos(bar))

    def _pos(self, infoBar, parentSize=None):
        raise NotImplementedError

    def _slideStartPos(self, infoBar):
        raise NotImplementedError

    def eventFilter(self, obj, e):
        try:
            if obj not in self.infoBars:
                return False
            if e.type() in (QEvent.Resize, QEvent.WindowStateChange):
                size = e.size() if e.type() == QEvent.Resize else None
                for bar in self.infoBars[obj]:
                    bar.move(self._pos(bar, size))
            return super().eventFilter(obj, e)
        except Exception:
            return False

    @classmethod
    def register(cls, name):
        def wrapper(Manager):
            if name not in cls.managers:
                cls.managers[name] = Manager
            return Manager
        return wrapper

    @classmethod
    def make(cls, position):
        if position not in cls.managers:
            raise ValueError("`%s` is an invalid info bar position." % position)
        return cls.managers[position]()


@InfoBarManager.register(_InfoBarPosition.TOP)
class TopInfoBarManager(InfoBarManager):
    def _pos(self, infoBar, parentSize=None):
        p = infoBar.parent()
        parentSize = parentSize or p.size()
        x = (p.width() - infoBar.width()) // 2
        y = self.margin
        index = self.infoBars[p].index(infoBar)
        for bar in self.infoBars[p][0:index]:
            y += (bar.height() + self.spacing)
        return QPoint(x, y)

    def _slideStartPos(self, infoBar):
        pos = self._pos(infoBar)
        return QPoint(pos.x(), pos.y() - 16)


@InfoBarManager.register(_InfoBarPosition.TOP_RIGHT)
class TopRightInfoBarManager(InfoBarManager):
    def _pos(self, infoBar, parentSize=None):
        p = infoBar.parent()
        parentSize = parentSize or p.size()
        x = parentSize.width() - infoBar.width() - self.margin
        y = self.margin
        index = self.infoBars[p].index(infoBar)
        for bar in self.infoBars[p][0:index]:
            y += (bar.height() + self.spacing)
        return QPoint(x, y)

    def _slideStartPos(self, infoBar):
        return QPoint(infoBar.parent().width(), self._pos(infoBar).y())


@InfoBarManager.register(_InfoBarPosition.BOTTOM_RIGHT)
class BottomRightInfoBarManager(InfoBarManager):
    def _pos(self, infoBar, parentSize=None):
        p = infoBar.parent()
        parentSize = parentSize or p.size()
        x = parentSize.width() - infoBar.width() - self.margin
        y = parentSize.height() - infoBar.height() - self.margin
        index = self.infoBars[p].index(infoBar)
        for bar in self.infoBars[p][0:index]:
            y -= (bar.height() + self.spacing)
        return QPoint(x, y)

    def _slideStartPos(self, infoBar):
        return QPoint(infoBar.parent().width(), self._pos(infoBar).y())


@InfoBarManager.register(_InfoBarPosition.TOP_LEFT)
class TopLeftInfoBarManager(InfoBarManager):
    def _pos(self, infoBar, parentSize=None):
        p = infoBar.parent()
        parentSize = parentSize or p.size()
        y = self.margin
        index = self.infoBars[p].index(infoBar)
        for bar in self.infoBars[p][0:index]:
            y += (bar.height() + self.spacing)
        return QPoint(self.margin, y)

    def _slideStartPos(self, infoBar):
        return QPoint(-infoBar.width(), self._pos(infoBar).y())


@InfoBarManager.register(_InfoBarPosition.BOTTOM_LEFT)
class BottomLeftInfoBarManager(InfoBarManager):
    def _pos(self, infoBar, parentSize=None):
        p = infoBar.parent()
        parentSize = parentSize or p.size()
        y = parentSize.height() - infoBar.height() - self.margin
        index = self.infoBars[p].index(infoBar)
        for bar in self.infoBars[p][0:index]:
            y -= (bar.height() + self.spacing)
        return QPoint(self.margin, y)

    def _slideStartPos(self, infoBar):
        return QPoint(-infoBar.width(), self._pos(infoBar).y())


@InfoBarManager.register(_InfoBarPosition.BOTTOM)
class BottomInfoBarManager(InfoBarManager):
    def _pos(self, infoBar, parentSize=None):
        p = infoBar.parent()
        parentSize = parentSize or p.size()
        x = (parentSize.width() - infoBar.width()) // 2
        y = parentSize.height() - infoBar.height() - self.margin
        index = self.infoBars[p].index(infoBar)
        for bar in self.infoBars[p][0:index]:
            y -= (bar.height() + self.spacing)
        return QPoint(x, y)

    def _slideStartPos(self, infoBar):
        pos = self._pos(infoBar)
        return QPoint(pos.x(), pos.y() + 16)


class MaskDialogBase(QDialog):
    """遮罩对话框基类（对齐上游：淡入淡出、点遮罩可关、可拖动）。

    Constructors
    ------------
    * MaskDialogBase(`parent`: QWidget = None)
    """

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self._isClosableOnMaskClicked = False
        self._isDraggable = False
        self._dragPos = QPoint()
        self._hBoxLayout = QHBoxLayout(self)
        self.windowMask = QWidget(self)

        self.widget = QFrame(self, objectName="centerWidget")
        self.setWindowFlags(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        if parent is not None:
            self.setGeometry(0, 0, parent.width(), parent.height())

        c = 0 if isDarkTheme() else 255
        self.windowMask.resize(self.size())
        self.windowMask.setStyleSheet(
            "background:rgba(%d, %d, %d, 0.6)" % (c, c, c))
        self._hBoxLayout.addWidget(self.widget)
        self.setShadowEffect()

        self.window().installEventFilter(self)
        self.windowMask.installEventFilter(self)
        self.widget.installEventFilter(self)

    def setShadowEffect(self, blurRadius=60, offset=(0, 10),
                        color=QColor(0, 0, 0, 100)):
        shadowEffect = QGraphicsDropShadowEffect(self.widget)
        shadowEffect.setBlurRadius(blurRadius)
        shadowEffect.setOffset(*offset)
        shadowEffect.setColor(color)
        self.widget.setGraphicsEffect(None)
        self.widget.setGraphicsEffect(shadowEffect)

    def setMaskColor(self, color: QColor):
        self.windowMask.setStyleSheet(
            "background: rgba(%d, %d, %d, %d)" % (
                color.red(), color.green(), color.blue(), color.alpha()))

    def _safe_clear_effect(self):
        """动画结束清掉 effect（2026-10-21 加固）。

        InfoBar 是会自动关闭的浮层，动画 200ms 后回调；若用户提前关窗/切页
        导致它被销毁，原 ``lambda: self.setGraphicsEffect(None)`` 会在已析构的
        C++ 对象上调用——轻则 RuntimeError 刷日志，重则在绘制路径段错误。
        """
        try:
            from ._anim import _alive
            if not _alive(self):
                return
        except Exception:  # noqa: BLE001
            pass
        try:
            self.setGraphicsEffect(None)
        except RuntimeError:
            pass

    def showEvent(self, e):
        opacityEffect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(opacityEffect)
        opacityAni = QPropertyAnimation(opacityEffect, b"opacity", self)
        opacityAni.setStartValue(0)
        opacityAni.setEndValue(1)
        opacityAni.setDuration(200)
        opacityAni.setEasingCurve(QEasingCurve.InSine)
        # ⚠ 回调一律 lambda *_:（PySide6 会带参传），且必须走存活判定
        opacityAni.finished.connect(lambda *_: self._safe_clear_effect())
        opacityAni.start()
        super().showEvent(e)

    def done(self, code):
        try:
            from ._anim import _alive
            if _alive(self.widget):
                self.widget.setGraphicsEffect(None)
        except Exception:  # noqa: BLE001
            pass
        opacityEffect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(opacityEffect)
        opacityAni = QPropertyAnimation(opacityEffect, b"opacity", self)
        opacityAni.setStartValue(1)
        opacityAni.setEndValue(0)
        opacityAni.setDuration(100)
        opacityAni.finished.connect(lambda *_: self._onDone(code))
        opacityAni.start()

    def _onDone(self, code):
        self.setGraphicsEffect(None)
        QDialog.done(self, code)

    def isClosableOnMaskClicked(self):
        return self._isClosableOnMaskClicked

    def setClosableOnMaskClicked(self, isClosable: bool):
        self._isClosableOnMaskClicked = isClosable

    def setDraggable(self, draggable: bool):
        self._isDraggable = draggable

    def isDraggable(self):
        return self._isDraggable

    def resizeEvent(self, e):
        self.windowMask.resize(self.size())

    def eventFilter(self, obj, e):
        if obj is self.window():
            if e.type() == QEvent.Resize:
                re = QResizeEvent(e)
                self.resize(re.size())
        elif obj is self.windowMask:
            if (e.type() == QEvent.MouseButtonRelease
                    and e.button() == Qt.LeftButton
                    and self.isClosableOnMaskClicked()):
                self.reject()
        elif obj is self.widget and self.isDraggable():
            if e.type() == QEvent.MouseButtonPress and e.button() == Qt.LeftButton:
                if not self.widget.rect().contains(e.pos()):
                    self._dragPos = e.pos()
                    return True
            elif e.type() == QEvent.MouseMove and not self._dragPos.isNull():
                pos = self.widget.pos() + e.pos() - self._dragPos
                pos.setX(max(0, min(pos.x(), self.width() - self.widget.width())))
                pos.setY(max(0, min(pos.y(), self.height() - self.widget.height())))
                self.widget.move(pos)
                return True
            elif e.type() == QEvent.MouseButtonRelease:
                self._dragPos = QPoint()
        return super().eventFilter(obj, e)


class MessageBoxBase(MaskDialogBase):
    """表单类对话框基类（对齐上游 MessageBoxBase）。

    Constructors
    ------------
    * MessageBoxBase(`parent`: QWidget = None)
    """

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.buttonGroup = QFrame(self.widget)
        self.yesButton = PrimaryPushButton(self.tr("确定"), self.buttonGroup)
        self.cancelButton = QPushButton(self.tr("取消"), self.buttonGroup)

        self.vBoxLayout = QVBoxLayout(self.widget)
        self.viewLayout = QVBoxLayout()
        self.buttonLayout = QHBoxLayout(self.buttonGroup)

        self._initWidget()

    def _initWidget(self):
        self._setQss()
        self._initLayout()

        self.setShadowEffect(60, (0, 10), QColor(0, 0, 0, 50))
        self.setMaskColor(QColor(0, 0, 0, 76))

        self.yesButton.setAttribute(Qt.WA_LayoutUsesWidgetRect)
        self.cancelButton.setAttribute(Qt.WA_LayoutUsesWidgetRect)
        self.yesButton.setAttribute(Qt.WA_MacShowFocusRect, False)

        self.yesButton.setFocus()
        self.buttonGroup.setFixedHeight(81)

        self.yesButton.clicked.connect(self._onYesButtonClicked)
        self.cancelButton.clicked.connect(self._onCancelButtonClicked)

    def _initLayout(self):
        self._hBoxLayout.removeWidget(self.widget)
        self._hBoxLayout.addWidget(self.widget, 1, Qt.AlignCenter)

        self.vBoxLayout.setSpacing(0)
        self.vBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.vBoxLayout.addLayout(self.viewLayout, 1)
        self.vBoxLayout.addWidget(self.buttonGroup, 0, Qt.AlignBottom)

        self.viewLayout.setSpacing(12)
        self.viewLayout.setContentsMargins(24, 24, 24, 24)

        self.buttonLayout.setSpacing(12)
        self.buttonLayout.setContentsMargins(24, 24, 24, 24)
        self.buttonLayout.addWidget(self.yesButton, 1, Qt.AlignVCenter)
        self.buttonLayout.addWidget(self.cancelButton, 1, Qt.AlignVCenter)

    def validate(self) -> bool:
        """关闭前校验（子类覆写）。"""
        return True

    def _onCancelButtonClicked(self):
        self.reject()

    def _onYesButtonClicked(self):
        if self.validate():
            self.accept()

    def _setQss(self):
        self.buttonGroup.setObjectName("buttonGroup")
        self.cancelButton.setObjectName("cancelButton")
        FluentStyleSheet.DIALOG.apply(self)

    def hideYesButton(self):
        self.yesButton.hide()
        self.buttonLayout.insertStretch(0, 1)

    def hideCancelButton(self):
        self.cancelButton.hide()
        self.buttonLayout.insertStretch(0, 1)


class Ui_MessageBox:
    """消息框 UI 部件（对齐上游 Ui_MessageBox）。"""

    yesSignal = Signal()
    cancelSignal = Signal()

    def _setUpUi(self, title, content, parent):
        self.content = content
        self.titleLabel = QLabel(title, parent)
        self.contentLabel = QLabel(content, parent)

        self.buttonGroup = QFrame(parent)
        self.yesButton = PrimaryPushButton(self.tr("确定"), self.buttonGroup)
        self.cancelButton = QPushButton(self.tr("取消"), self.buttonGroup)

        self.vBoxLayout = QVBoxLayout(parent)
        self.textLayout = QVBoxLayout()
        self.buttonLayout = QHBoxLayout(self.buttonGroup)

        self._initMessageWidget()

    def _initMessageWidget(self):
        self._setMessageQss()
        self._initMessageLayout()

        self.yesButton.setAttribute(Qt.WA_LayoutUsesWidgetRect)
        self.cancelButton.setAttribute(Qt.WA_LayoutUsesWidgetRect)
        self.yesButton.setFocus()
        self.buttonGroup.setFixedHeight(81)

        self.contentLabel.setContextMenuPolicy(Qt.CustomContextMenu)
        self._adjustMessageText()

        self.yesButton.clicked.connect(self._onMessageYesClicked)
        self.cancelButton.clicked.connect(self._onMessageCancelClicked)

    def _adjustMessageText(self):
        if self.isWindow():
            if self.parent():
                w = max(self.titleLabel.width(), self.parent().width())
                chars = max(min(w / 9, 140), 30)
            else:
                chars = 100
        else:
            w = max(self.titleLabel.width(), self.window().width())
            chars = max(min(w / 9, 100), 30)
        self.contentLabel.setText(TextWrap.wrap(self.content, chars, False)[0])

    def _initMessageLayout(self):
        self.vBoxLayout.setSpacing(0)
        self.vBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.vBoxLayout.addLayout(self.textLayout, 1)
        self.vBoxLayout.addWidget(self.buttonGroup, 0, Qt.AlignBottom)
        self.vBoxLayout.setSizeConstraint(QVBoxLayout.SetMinimumSize)

        self.textLayout.setSpacing(12)
        self.textLayout.setContentsMargins(24, 24, 24, 24)
        self.textLayout.addWidget(self.titleLabel, 0, Qt.AlignTop)
        self.textLayout.addWidget(self.contentLabel, 0, Qt.AlignTop)

        self.buttonLayout.setSpacing(12)
        self.buttonLayout.setContentsMargins(24, 24, 24, 24)
        self.buttonLayout.addWidget(self.yesButton, 1, Qt.AlignVCenter)
        self.buttonLayout.addWidget(self.cancelButton, 1, Qt.AlignVCenter)

    def _onMessageCancelClicked(self):
        self.reject()
        self.cancelSignal.emit()

    def _onMessageYesClicked(self):
        self.accept()
        self.yesSignal.emit()

    def _setMessageQss(self):
        self.titleLabel.setObjectName("titleLabel")
        self.contentLabel.setObjectName("contentLabel")
        self.buttonGroup.setObjectName("buttonGroup")
        self.cancelButton.setObjectName("cancelButton")
        FluentStyleSheet.DIALOG.apply(self)
        FluentStyleSheet.DIALOG.apply(self.contentLabel)
        self.yesButton.adjustSize()
        self.cancelButton.adjustSize()

    def setContentCopyable(self, isCopyable: bool):
        if isCopyable:
            self.contentLabel.setTextInteractionFlags(
                Qt.TextSelectableByMouse)
        else:
            self.contentLabel.setTextInteractionFlags(Qt.NoTextInteraction)

    def hideYesButton(self):
        self.yesButton.hide()
        self.buttonLayout.insertStretch(0, 1)

    def hideCancelButton(self):
        self.cancelButton.hide()
        self.buttonLayout.insertStretch(0, 1)


class MessageBox(MaskDialogBase, Ui_MessageBox):
    """标准消息框（对齐上游 MessageBox：yesSignal/cancelSignal）。

    Constructors
    ------------
    * MessageBox(`title`: str, `content`: str, `parent`: QWidget = None)
    """

    yesSignal = Signal()
    cancelSignal = Signal()

    def __init__(self, title: str, content: str, parent=None):
        super().__init__(parent=parent)
        self._setUpUi(title, content, self.widget)

        self.setShadowEffect(60, (0, 10), QColor(0, 0, 0, 50))
        self.setMaskColor(QColor(0, 0, 0, 76))
        self._hBoxLayout.removeWidget(self.widget)
        self._hBoxLayout.addWidget(self.widget, 1, Qt.AlignCenter)

        self.buttonGroup.setMinimumWidth(280)
        self.widget.setFixedSize(
            max(self.contentLabel.width(), self.titleLabel.width()) + 48,
            self.contentLabel.y() + self.contentLabel.height() + 105)

    def eventFilter(self, obj, e):
        if obj is self.window():
            if e.type() == QEvent.Resize:
                self._adjustMessageText()
        return super().eventFilter(obj, e)
