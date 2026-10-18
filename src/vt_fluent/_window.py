# -*- coding: utf-8 -*-
# @version 2.3.1
"""vt_fluent 窗口与导航（自研，替代 qfluentwidgets.window + navigation）。

行为契约（对齐上游 1.11.3）：
· FluentWindow：无边框窗口 + Windows 11 Mica 背景（DWM 系统背景，非 Mica
  环境自动回落实底）+ 48px 标题栏（图标/标题/最小化/最大化/关闭）+
  左侧导航 + 右侧 StackedWidget；addSubInterface/switchTo/removeInterface/
  setMicaEffectEnabled/titleBar/navigationInterface/stackedWidget；
· NavigationInterface：竖向导航（展开 312 / 紧凑 48，可折叠，滚动承载，
  底部分隔项），addItem/addWidget/addSeparator/setCurrentItem/expand/toggle/
  setExpandWidth/setMinimumExpandWidth/setCollapsible/widget/removeWidget；
· NavigationWidget：40×36（紧凑）/312×36（展开）自绘导航项
  （图标 16×16@11.5,10、文字 @44、选中指示条 3×16 圆角 1.5、
  悬停底 rgba(c,c,c,6/10)、按压 0.7 透明度）。

自研口径：不依赖 PySideSix-Frameless-Window——缩放/拖动/最大化用
Windows 原生命中测试（WM_NCHITTEST）与标题栏鼠标事件直接实现。
"""

import ctypes
import sys

from PySide6.QtCore import QEvent, QMargins, QPoint, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (QColor, QCursor, QFont, QIcon, QPainter, QPen)
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QScrollArea,
                               QSizePolicy, QStackedWidget, QVBoxLayout, QWidget)

from ._anim import BackgroundAnimationWidget
from ._icon import FluentIcon, drawIcon, toQIcon
from ._theme import (FluentStyleSheet, autoFallbackThemeColor, isDarkTheme, qconfig,
                     setFont)


def _nav_position():
    """取 B0 定义在包入口的 NavigationItemPosition（延迟导入避免循环）。"""
    from . import NavigationItemPosition
    return NavigationItemPosition


# ---------------------------------------------------------------------- #
# Mica / 无边框窗口
# ---------------------------------------------------------------------- #
def _set_mica(hwnd, dark: bool) -> bool:
    """Windows 11 Mica 系统背景（DWMWA_SYSTEMBACKDROP_TYPE=38）。"""
    if sys.platform != "win32":
        return False
    try:
        dwm = ctypes.windll.dwmapi
        backdrop = ctypes.c_int(2)  # DWMSBT_MAINWINDOW (Mica)
        dwm.DwmSetWindowAttribute(hwnd, 38, ctypes.byref(backdrop),
                                  ctypes.sizeof(backdrop))
        # 深色标题栏（Win10 1903+ / Win11）
        dark_mode = ctypes.c_int(1 if dark else 0)
        dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(dark_mode),
                                  ctypes.sizeof(dark_mode))
        return True
    except Exception:
        return False


def _remove_backdrop(hwnd) -> bool:
    if sys.platform != "win32":
        return False
    try:
        dwm = ctypes.windll.dwmapi
        none = ctypes.c_int(1)  # DWMSBT_NONE
        dwm.DwmSetWindowAttribute(hwnd, 38, ctypes.byref(none),
                                  ctypes.sizeof(none))
        return True
    except Exception:
        return False


class FramelessWindow(QWidget):
    """无边框窗口基类（原生命中测试缩放 + 标题栏拖动）。"""

    BORDER_WIDTH = 6
    #: WM_NCHITTEST 返回码
    _HTLEFT, _HTRIGHT, _HTTOP = 10, 11, 12
    _HTTOPLEFT, _HTTOPRIGHT = 13, 14
    _HTBOTTOM, _HTBOTTOMLEFT, _HTBOTTOMRIGHT = 15, 16, 17

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.titleBar = None

    def setTitleBar(self, titleBar):
        self.titleBar = titleBar
        titleBar.raise_()

    def nativeEvent(self, eventType, message):
        if sys.platform == "win32" and not self.isMaximized():
            try:
                from ctypes import wintypes
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == 0x0084:  # WM_NCHITTEST
                    x = ctypes.c_short(msg.lParam & 0xFFFF).value
                    y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
                    pos = self.mapFromGlobal(QPoint(x, y))
                    bw = self.BORDER_WIDTH
                    w, h = self.width(), self.height()
                    on_left = pos.x() < bw
                    on_right = pos.x() >= w - bw
                    on_top = pos.y() < bw
                    on_bottom = pos.y() >= h - bw
                    if on_top and on_left:
                        return True, self._HTTOPLEFT
                    if on_top and on_right:
                        return True, self._HTTOPRIGHT
                    if on_bottom and on_left:
                        return True, self._HTBOTTOMLEFT
                    if on_bottom and on_right:
                        return True, self._HTBOTTOMRIGHT
                    if on_left:
                        return True, self._HTLEFT
                    if on_right:
                        return True, self._HTRIGHT
                    if on_top:
                        return True, self._HTTOP
                    if on_bottom:
                        return True, self._HTBOTTOM
            except Exception:
                pass
        return super().nativeEvent(eventType, message)


# ---------------------------------------------------------------------- #
# 导航部件
# ---------------------------------------------------------------------- #
class NavigationWidget(QWidget):
    """导航项基类（对齐上游 NavigationWidget 的尺寸/态语义）。"""

    clicked = Signal(bool)
    selectedChanged = Signal(bool)
    EXPAND_WIDTH = 312

    def __init__(self, isSelectable: bool, parent=None):
        super().__init__(parent)
        self.isCompacted = True
        self.isSelected = False
        self.isPressed = False
        self.isEnter = False
        self.isAboutSelected = False
        self.isSelectable = isSelectable
        self.treeParent = None
        self.nodeDepth = 0
        self.lightTextColor = QColor(0, 0, 0)
        self.darkTextColor = QColor(255, 255, 255)
        self.lightIndicatorColor = QColor()
        self.darkIndicatorColor = QColor()
        self.setFixedSize(40, 36)

    def enterEvent(self, e):
        self.isEnter = True
        self.update()

    def leaveEvent(self, e):
        self.isEnter = False
        self.isPressed = False
        self.update()

    def mousePressEvent(self, e):
        super().mousePressEvent(e)
        self.isPressed = True
        self.update()

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        self.isPressed = False
        self.update()
        self.clicked.emit(True)

    def click(self):
        self.clicked.emit(True)

    def setCompacted(self, isCompacted: bool):
        if isCompacted == self.isCompacted:
            return
        self.isCompacted = isCompacted
        if isCompacted:
            self.setFixedSize(40, 36)
        else:
            self.setFixedSize(self.EXPAND_WIDTH, 36)
        self.update()

    def setSelected(self, isSelected: bool):
        if not self.isSelectable:
            return
        self.isSelected = isSelected
        self.isAboutSelected = False
        self.update()
        self.selectedChanged.emit(isSelected)

    def textColor(self):
        return self.darkTextColor if isDarkTheme() else self.lightTextColor

    def setTextColor(self, light, dark):
        self.lightTextColor = QColor(light)
        self.darkTextColor = QColor(dark)
        self.update()

    def setAboutSelected(self, selected: bool):
        self.isAboutSelected = selected
        self.update()

    def _margins(self):
        return QMargins(0, 0, 0, 0)

    def indicatorRect(self):
        m = self._margins()
        return QRectF(m.left(), 10, 3, 16)

    def setIndicatorColor(self, light, dark):
        self.lightIndicatorColor = QColor(light)
        self.darkIndicatorColor = QColor(dark)
        self.update()


class NavigationPushButton(NavigationWidget):
    """导航按钮项（图标 + 文字，对齐上游 NavigationPushButton）。"""

    def __init__(self, icon, text: str, isSelectable: bool, parent=None):
        super().__init__(isSelectable=isSelectable, parent=parent)
        self._icon = icon
        self._text = text
        setFont(self)

    def text(self):
        return self._text

    def setText(self, text: str):
        self._text = text
        self.update()

    def icon(self):
        return toQIcon(self._icon)

    def setIcon(self, icon):
        self._icon = icon
        self.update()

    def _canDrawIndicator(self):
        return self.isSelected

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing |
                               QPainter.TextAntialiasing |
                               QPainter.SmoothPixmapTransform)
        painter.setPen(Qt.NoPen)

        if self.isPressed:
            painter.setOpacity(0.7)
        if not self.isEnabled():
            painter.setOpacity(0.4)

        c = 255 if isDarkTheme() else 0
        m = self._margins()
        pl, pr = m.left(), m.right()
        globalRect = QRect(self.mapToGlobal(QPoint()), self.size())

        if self._canDrawIndicator():
            painter.setBrush(QColor(c, c, c, 6 if self.isEnter else 10))
            painter.drawRoundedRect(self.rect(), 5, 5)
            painter.setBrush(autoFallbackThemeColor(self.lightIndicatorColor,
                                                    self.darkIndicatorColor))
            painter.drawRoundedRect(self.indicatorRect(), 1.5, 1.5)
        elif ((self.isEnter and globalRect.contains(QCursor.pos()))
              or self.isAboutSelected) and self.isEnabled():
            painter.setBrush(QColor(c, c, c, 6 if self.isAboutSelected else 10))
            painter.drawRoundedRect(self.rect(), 5, 5)

        drawIcon(self._icon, painter, QRectF(11.5 + pl, 10, 16, 16))

        if self.isCompacted:
            return

        painter.setFont(self.font())
        painter.setPen(self.textColor())
        left = 44 + pl if not self.icon().isNull() else pl + 16
        painter.drawText(QRectF(left, 0, self.width() - 13 - left - pr,
                                self.height()),
                         Qt.AlignVCenter, self.text())


class NavigationToolButton(NavigationPushButton):
    """导航工具按钮（仅图标，固定紧凑）。"""

    def __init__(self, icon, parent=None):
        super().__init__(icon, "", False, parent)

    def setCompacted(self, isCompacted: bool):
        self.setFixedSize(40, 36)


class NavigationSeparator(NavigationWidget):
    """导航分隔线（对齐上游 NavigationSeparator）。"""

    def __init__(self, parent=None):
        super().__init__(False, parent=parent)
        self.setCompacted(True)

    def setCompacted(self, isCompacted: bool):
        if isCompacted:
            self.setFixedSize(48, 3)
        else:
            self.setFixedSize(self.EXPAND_WIDTH + 10, 3)
        self.update()

    def paintEvent(self, e):
        painter = QPainter(self)
        c = 255 if isDarkTheme() else 0
        pen = QPen(QColor(c, c, c, 15))
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.drawLine(0, 1, self.width(), 1)


class NavigationInterface(QWidget):
    """竖向导航接口（对齐上游 NavigationInterface 的使用面）。

    Constructors
    ------------
    * NavigationInterface(`parent`=None, `showMenuButton`=True,
                          `showReturnButton`=False, `collapsible`=True)
    """

    displayModeChanged = Signal(object)

    def __init__(self, parent=None, showMenuButton=True, showReturnButton=False,
                 collapsible=True):
        super().__init__(parent)
        #: 应用侧按 `navigationInterface.panel.font()` 取导航字体，
        #: 这里让 panel 指向自身（QWidget 自带 font()）。
        self.panel = self
        self.items = {}
        self.routeKeyToWidget = {}
        self._currentRouteKey = None
        self._isCollapsible = collapsible
        self._isExpanded = False
        self._expandWidth = NavigationWidget.EXPAND_WIDTH
        self._minimumExpandWidth = 1008

        self.topLayout = QVBoxLayout()
        self.bottomLayout = QVBoxLayout()
        self.vBoxLayout = QVBoxLayout(self)

        self.scrollArea = QScrollArea(self)
        self.scrollWidget = QWidget()
        self.scrollLayout = QVBoxLayout(self.scrollWidget)

        self._initInterface()

    def _initInterface(self):
        self.setAttribute(Qt.WA_StyledBackground)
        self.setFixedWidth(48)

        self.scrollArea.setWidget(self.scrollWidget)
        self.scrollArea.setWidgetResizable(True)
        self.scrollArea.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scrollArea.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scrollArea.setFrameShape(QFrame.NoFrame)

        self.scrollLayout.setContentsMargins(4, 8, 4, 8)
        self.scrollLayout.setSpacing(4)
        self.scrollLayout.setAlignment(Qt.AlignTop)
        self.scrollLayout.addLayout(self.topLayout)
        self.scrollLayout.addStretch(1)
        self.scrollLayout.addLayout(self.bottomLayout)

        #: 顶部返回键（应用把它改挂「定位到首页」；上游同位置同名）
        self.returnButton = NavigationToolButton(FluentIcon.RETURN, self)
        self.returnButton.setToolTip(self.tr("返回"))
        self.returnButton.move(4, 4)
        self.returnButton.show()

        self.vBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.vBoxLayout.setSpacing(0)
        self.vBoxLayout.addWidget(self.scrollArea)

    # ---- 项增删 -------------------------------------------------------- #
    def addItem(self, routeKey: str, icon, text: str, onClick=None,
                selectable=True, position=None, tooltip=None,
                isMinimalExpand=False):
        pos = _nav_position().TOP if position is None else position
        widget = NavigationPushButton(icon, text, selectable, self)
        widget.setToolTip(tooltip or text)
        self.addWidget(routeKey, widget, onClick, pos)
        return widget

    def addWidget(self, routeKey: str, widget, onClick=None, position=None):
        pos = _nav_position().TOP if position is None else position
        if routeKey in self.routeKeyToWidget:
            return

        widget.setParent(self.scrollWidget)
        widget.setCompacted(not self._isExpanded)

        if onClick:
            widget.clicked.connect(onClick)

        if pos == _nav_position().BOTTOM:
            self.bottomLayout.addWidget(widget)
        else:
            self.topLayout.addWidget(widget)

        self.routeKeyToWidget[routeKey] = widget
        self.items[routeKey] = widget
        widget.clicked.connect(lambda: self._onWidgetClicked(routeKey))

    def addSeparator(self, position=None):
        pos = _nav_position().TOP if position is None else position
        sep = NavigationSeparator(self)
        sep.setCompacted(not self._isExpanded)
        if pos == _nav_position().BOTTOM:
            self.bottomLayout.addWidget(sep)
        else:
            self.topLayout.addWidget(sep)

    def removeWidget(self, routeKey: str):
        if routeKey not in self.routeKeyToWidget:
            return
        w = self.routeKeyToWidget.pop(routeKey)
        self.items.pop(routeKey, None)
        self.topLayout.removeWidget(w)
        self.bottomLayout.removeWidget(w)
        w.deleteLater()

    def widget(self, routeKey: str):
        return self.routeKeyToWidget.get(routeKey)

    # ---- 选中 ---------------------------------------------------------- #
    def _onWidgetClicked(self, routeKey: str):
        self.setCurrentItem(routeKey)

    def setCurrentItem(self, routeKey: str):
        if routeKey not in self.routeKeyToWidget:
            return
        if self._currentRouteKey == routeKey:
            return
        old = self.routeKeyToWidget.get(self._currentRouteKey)
        if old is not None:
            old.setSelected(False)
        self._currentRouteKey = routeKey
        self.routeKeyToWidget[routeKey].setSelected(True)

    def currentItem(self):
        return self.routeKeyToWidget.get(self._currentRouteKey)

    def currentRouteKey(self):
        return self._currentRouteKey

    # ---- 展开/收起 ----------------------------------------------------- #
    def setCollapsible(self, collapsible: bool):
        self._isCollapsible = collapsible
        if not collapsible:
            # 上游语义：不可折叠 = 常驻展开（默认窄条只有图标）
            self._setExpanded(True)

    def isCollapsible(self):
        return self._isCollapsible

    def expand(self, useAni=True):
        self._setExpanded(True)

    def collapse(self, useAni=True):
        self._setExpanded(False)

    def toggle(self):
        self._setExpanded(not self._isExpanded)

    def isExpanded(self):
        return self._isExpanded

    def _setExpanded(self, expanded: bool):
        if self._isExpanded == expanded:
            return
        self._isExpanded = expanded
        for w in self.routeKeyToWidget.values():
            if expanded:
                w.EXPAND_WIDTH = max(self._expandWidth - 8, 40)
            w.setCompacted(not expanded)
            if expanded and not w.isCompacted:
                w.setFixedSize(w.EXPAND_WIDTH, 36)
        for sep in self.findChildren(NavigationSeparator):
            sep.setCompacted(not expanded)
        self.setFixedWidth(self._expandWidth if expanded else 48)

    def setExpandWidth(self, width: int):
        self._expandWidth = int(width)
        if not self._isExpanded:
            return
        self.setFixedWidth(self._expandWidth)
        for w in self.routeKeyToWidget.values():
            w.EXPAND_WIDTH = max(self._expandWidth - 8, 40)
            # setCompacted 在已是展开态时提前返回，这里直接落尺寸
            if not w.isCompacted:
                w.setFixedSize(w.EXPAND_WIDTH, 36)
            w.update()

    def setMinimumExpandWidth(self, width: int):
        self._minimumExpandWidth = width

    def setMenuButtonVisible(self, isVisible: bool):
        pass

    def setReturnButtonVisible(self, isVisible: bool):
        pass

    def setAcrylicEnabled(self, isEnabled: bool):
        pass

    def isAcrylicEnabled(self):
        return False


class StackedWidget(QFrame):
    """页面栈（对齐上游 window.StackedWidget：popOut 参数 + currentChanged 转发）。

    上游用 PopUpAniStackedWidget 做滑动动画；此处为**纯切换**（静态截图与
    布局完全一致），动画属后续 nicety，接口签名保持兼容。
    """

    currentChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.hBoxLayout = QHBoxLayout(self)
        self.view = QStackedWidget(self)

        self.hBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.hBoxLayout.addWidget(self.view)

        self.view.currentChanged.connect(self.currentChanged)
        self.setAttribute(Qt.WA_StyledBackground)

    def addWidget(self, widget):
        self.view.addWidget(widget)

    def removeWidget(self, widget):
        self.view.removeWidget(widget)

    def widget(self, index):
        return self.view.widget(index)

    def count(self):
        return self.view.count()

    def indexOf(self, widget):
        return self.view.indexOf(widget)

    def setCurrentWidget(self, widget, popOut=True):
        from PySide6.QtWidgets import QAbstractScrollArea
        if isinstance(widget, QAbstractScrollArea):
            widget.verticalScrollBar().setValue(0)
        self.view.setCurrentWidget(widget)

    def setCurrentIndex(self, index, popOut=True):
        self.view.setCurrentIndex(index)

    def currentIndex(self):
        return self.view.currentIndex()

    def currentWidget(self):
        return self.view.currentWidget()

    def setAnimationEnabled(self, isEnabled: bool):
        pass

    def isAnimationEnabled(self):
        return False


class FluentTitleBarButton(QWidget):
    """标题栏按钮（最小化/最大化/关闭，46×32）。"""

    def __init__(self, icon, parent=None):
        super().__init__(parent)
        self._icon = icon
        self.isHover = False
        self.isPressed = False
        self.isCloseButton = False
        self.setFixedSize(46, 32)
        self.setCursor(Qt.ArrowCursor)

    def setIcon(self, icon):
        self._icon = icon
        self.update()

    def icon(self):
        return toQIcon(self._icon)

    def enterEvent(self, e):
        self.isHover = True
        self.update()

    def leaveEvent(self, e):
        self.isHover = False
        self.isPressed = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.isPressed = True
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.isPressed:
            self.isPressed = False
            self.update()
            self.clicked.emit()

    clicked = Signal()

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing |
                               QPainter.SmoothPixmapTransform)
        c = 255 if isDarkTheme() else 0
        bg = Qt.transparent
        if self.isPressed:
            bg = QColor(c, c, c, 26) if not self.isCloseButton else QColor(192, 43, 28)
        elif self.isHover:
            bg = QColor(c, c, c, 14) if not self.isCloseButton else QColor(196, 43, 28)
        painter.setPen(Qt.NoPen)
        painter.setBrush(bg)
        painter.drawRect(self.rect())

        rect = QRectF(self.width() / 2 - 5, self.height() / 2 - 5, 10, 10)
        if self.isCloseButton and (self.isHover or self.isPressed):
            FluentIcon.CLOSE.render(painter, rect, fill="#FFFFFF")
        else:
            drawIcon(self._icon, painter, rect)


class FluentTitleBar(QWidget):
    """标题栏（48px：图标 + 标题 + 窗口按钮，可拖动/双击最大化）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.window = parent
        self._dragPos = None
        self.setFixedHeight(48)
        self.setAttribute(Qt.WA_StyledBackground, False)

        self.iconWidget = QLabel(self)
        self.titleLabel = QLabel(self)
        self.minBtn = FluentTitleBarButton(FluentIcon.MINIMIZE, self)
        self.maxBtn = FluentTitleBarButton(FluentIcon.FULL_SCREEN, self)
        self.closeBtn = FluentTitleBarButton(FluentIcon.CLOSE, self)
        self.closeBtn.isCloseButton = True

        self.hBoxLayout = QHBoxLayout(self)
        self._initWidget()

    def _initWidget(self):
        self.hBoxLayout.setContentsMargins(12, 0, 0, 0)
        self.hBoxLayout.setSpacing(0)
        self.hBoxLayout.addWidget(self.iconWidget, 0, Qt.AlignVCenter)
        self.hBoxLayout.addSpacing(10)
        self.hBoxLayout.addWidget(self.titleLabel, 0, Qt.AlignVCenter)
        self.hBoxLayout.addStretch(1)
        self.hBoxLayout.addWidget(self.minBtn, 0, Qt.AlignVCenter)
        self.hBoxLayout.addWidget(self.maxBtn, 0, Qt.AlignVCenter)
        self.hBoxLayout.addWidget(self.closeBtn, 0, Qt.AlignVCenter)

        self.iconWidget.setFixedSize(18, 18)
        self.titleLabel.setStyleSheet("background: transparent;")
        setFont(self.titleLabel, 13)

        self.minBtn.clicked.connect(self.window.showMinimized)
        self.maxBtn.clicked.connect(self._toggleMaximized)
        self.closeBtn.clicked.connect(self.window.close)

    def _toggleMaximized(self):
        if self.window.isMaximized():
            self.window.showNormal()
        else:
            self.window.showMaximized()

    def setTitle(self, title: str):
        self.titleLabel.setText(title)

    def setIcon(self, icon):
        if icon is None:
            self.iconWidget.clear()
            return
        self.iconWidget.setPixmap(toQIcon(icon).pixmap(18, 18))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._dragPos = e.globalPosition().toPoint() - self.window.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._dragPos is None or self.window.isMaximized():
            return
        self.window.move(e.globalPosition().toPoint() - self._dragPos)

    def mouseReleaseEvent(self, e):
        self._dragPos = None

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._toggleMaximized()

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255, 8) if isDarkTheme()
                         else QColor(0, 0, 0, 4))
        painter.drawRect(self.rect())


class FluentWindow(BackgroundAnimationWidget, FramelessWindow):
    """Fluent 主窗口（无边框 + Mica + 标题栏 + 左侧导航 + 页面栈）。

    Constructors
    ------------
    * FluentWindow(`parent`: QWidget = None)
    """

    def __init__(self, parent=None):
        self._isMicaEnabled = False
        self._lightBackgroundColor = QColor(240, 244, 249)
        self._darkBackgroundColor = QColor(32, 32, 32)
        super().__init__(parent=parent)

        self.titleBar = FluentTitleBar(self)
        self.setTitleBar(self.titleBar)

        self.hBoxLayout = QHBoxLayout(self)
        self.widgetLayout = QHBoxLayout()
        self.stackedWidget = StackedWidget(self)
        self.navigationInterface = NavigationInterface(self, showReturnButton=True)

        self.hBoxLayout.setSpacing(0)
        self.hBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.hBoxLayout.addWidget(self.navigationInterface)
        self.hBoxLayout.addLayout(self.widgetLayout)
        self.hBoxLayout.setStretchFactor(self.widgetLayout, 1)

        self.widgetLayout.setContentsMargins(0, 48, 0, 0)
        self.widgetLayout.setSpacing(0)
        self.widgetLayout.addWidget(self.stackedWidget)

        FluentStyleSheet.FLUENT_WINDOW.apply(self.stackedWidget)
        self.stackedWidget.setObjectName("stackedWidget")

        self.titleBar.raise_()
        self.setMicaEffectEnabled(True)
        qconfig.themeChangedFinished.connect(self._onThemeChangedFinished)

    # ---- 背景 / Mica --------------------------------------------------- #
    def _normalBackgroundColor(self):
        if not self.isMicaEffectEnabled():
            return (self._darkBackgroundColor if isDarkTheme()
                    else self._lightBackgroundColor)
        return QColor(0, 0, 0, 0)

    def setCustomBackgroundColor(self, light, dark):
        self._lightBackgroundColor = QColor(light)
        self._darkBackgroundColor = QColor(dark)
        self._updateBackgroundColor()

    def _onThemeChangedFinished(self):
        if self.isMicaEffectEnabled():
            _set_mica(int(self.winId()), isDarkTheme())

    def setMicaEffectEnabled(self, isEnabled: bool):
        if sys.platform != "win32":
            return
        try:
            build = sys.getwindowsversion().build
        except Exception:
            build = 0
        if build < 22000:
            # 非 Win11：退化为实底（与上游一致）
            self._isMicaEnabled = False
            return
        self._isMicaEnabled = isEnabled
        if isEnabled:
            _set_mica(int(self.winId()), isDarkTheme())
        else:
            _remove_backdrop(int(self.winId()))
        self.setBackgroundColor(self._normalBackgroundColor())

    def isMicaEffectEnabled(self):
        return self._isMicaEnabled

    def paintEvent(self, e):
        super().paintEvent(e)
        painter = QPainter(self)
        painter.setPen(Qt.NoPen)
        painter.setBrush(self.backgroundColor)
        painter.drawRect(self.rect())

    def showEvent(self, e):
        super().showEvent(e)
        if self.isMicaEffectEnabled():
            _set_mica(int(self.winId()), isDarkTheme())

    # ---- 页面管理 ------------------------------------------------------ #
    def addSubInterface(self, interface: QWidget, icon, text: str,
                        position=None, parent=None, isTransparent=False):
        from . import NavigationItemPosition
        pos = NavigationItemPosition.TOP if position is None else position

        if not interface.objectName():
            raise ValueError("The object name of `interface` can't be empty string.")

        interface.setProperty("isStackedTransparent", isTransparent)
        self.stackedWidget.addWidget(interface)

        routeKey = interface.objectName()
        item = self.navigationInterface.addItem(
            routeKey=routeKey, icon=icon, text=text,
            onClick=lambda: self.switchTo(interface),
            position=pos, tooltip=text)

        if self.stackedWidget.count() == 1:
            self.stackedWidget.currentChanged.connect(
                self._onCurrentInterfaceChanged)
            self.navigationInterface.setCurrentItem(routeKey)

        self._updateStackedBackground()
        return item

    def removeInterface(self, interface: QWidget, isDelete=False):
        self.navigationInterface.removeWidget(interface.objectName())
        self.stackedWidget.removeWidget(interface)
        interface.hide()
        if isDelete:
            interface.deleteLater()

    def switchTo(self, interface: QWidget):
        self.stackedWidget.setCurrentWidget(interface)

    def _onCurrentInterfaceChanged(self, index: int):
        widget = self.stackedWidget.widget(index)
        if widget is not None:
            self.navigationInterface.setCurrentItem(widget.objectName())
        self._updateStackedBackground()

    def _updateStackedBackground(self):
        widget = self.stackedWidget.currentWidget()
        if widget is None:
            return
        isTransparent = bool(widget.property("isStackedTransparent"))
        if bool(self.stackedWidget.property("isTransparent")) == isTransparent:
            return
        self.stackedWidget.setProperty("isTransparent", isTransparent)
        self.stackedWidget.setStyle(QApplication.style())

    # ---- 布局 ---------------------------------------------------------- #
    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.titleBar.move(46, 0)
        self.titleBar.resize(self.width() - 46, self.titleBar.height())
        self.titleBar.raise_()
        self.navigationInterface.setFixedHeight(self.height())

    def setWindowTitle(self, title: str):
        super().setWindowTitle(title)
        self.titleBar.setTitle(title)

    def setWindowIcon(self, icon):
        super().setWindowIcon(icon)
        self.titleBar.setIcon(icon)
