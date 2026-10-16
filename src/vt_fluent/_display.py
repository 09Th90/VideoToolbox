# -*- coding: utf-8 -*-
# @version 2.3.1
"""vt_fluent 展示族（自研，替代 qfluentwidgets 展示类控件）。

行为契约（对齐上游 1.11.3）：
· 标签族：CaptionLabel 12 / BodyLabel 14 / StrongBodyLabel 14 半粗 /
  SubtitleLabel 20 半粗 / TitleLabel 28 半粗；文字色明暗双色 + 主题切换跟随；
· 卡片族：CardWidget（上下弧线描边 + 三态底色）、SimpleCardWidget、
  ElevatedCardWidget（阴影 + hover 上浮 3px）；
· ScrollArea：平滑滚动（SmoothScrollDelegate）+ 透明背景开关；
· SegmentedWidget/Pivot：分段选中（背景块 + 底部指示器，指示器
  squash-stretch 滑移动画），addItem/setCurrentItem/removeWidget；
· ProgressBar/ProgressRing：val 动画（150ms）、暂停/错误态、
  百分比文字（%p/%v/%m 格式符）；
· TableWidget/TableView/ListWidget：行级委托绘制（悬停/按压/选中底色、
  首列指示条、复选框）、表头分段描边、平滑滚动。

行编辑单元格编辑器复用 vt_fluent._inputs.LineEdit（createEditor 内建）。
"""

from PySide6.QtCore import QEasingCurve, QEvent, QModelIndex, QPoint, QPropertyAnimation, QRectF, QSize, Qt, Signal, Property
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPalette, QPen
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QFrame, QHBoxLayout,
                               QHeaderView, QLabel, QListView, QListWidget, QMenu,
                               QProgressBar, QScrollArea, QSizePolicy,
                               QStyledItemDelegate, QStyleOptionViewItem,
                               QTableView, QTableWidget, QVBoxLayout, QWidget)

from ._anim import (BackgroundAnimationWidget, DropShadowAnimation,
                    ScaleSlideAnimation, SmoothScrollDelegate, createBezierCurve)
from ._buttons import PushButton
from ._inputs import CHECK_ACCEPT, CHECK_PARTIAL, LineEdit
from ._theme import (FluentStyleSheet, autoFallbackThemeColor, getFont, isDarkTheme,
                     qconfig, setCustomStyleSheet, setFont, themeColor)

#: 表格行指示条/复选框的复选图标（上游 CheckBoxIcon 等价物）
_CHECK_ICONS = (CHECK_ACCEPT, CHECK_PARTIAL)


class FluentLabelBase(QLabel):
    """Fluent 标签基类（对齐上游 FluentLabelBase）。

    Constructors
    ------------
    * FluentLabelBase(`parent`: QWidget = None)
    * FluentLabelBase(`text`: str, `parent`: QWidget = None)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init()

    def _init(self):
        FluentStyleSheet.LABEL.apply(self)
        self.setFont(self.getFont())
        self.setTextColor()
        qconfig.themeChanged.connect(self._applyThemeColor)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._onContextMenuRequested)

    def getFont(self):
        raise NotImplementedError

    def _applyThemeColor(self):
        self.setTextColor(self.lightColor, self.darkColor)

    def setTextColor(self, light=QColor(0, 0, 0), dark=QColor(255, 255, 255)):
        self.lightColor = QColor(light)
        self.darkColor = QColor(dark)
        setCustomStyleSheet(
            self,
            "FluentLabelBase{color:%s}" % self.lightColor.name(QColor.HexArgb),
            "FluentLabelBase{color:%s}" % self.darkColor.name(QColor.HexArgb))

    def getPixelFontSize(self):
        return self.font().pixelSize()

    def setPixelFontSize(self, size: int):
        font = self.font()
        font.setPixelSize(size)
        self.setFont(font)

    def setStrikeOut(self, isStrikeOut: bool):
        font = self.font()
        font.setStrikeOut(isStrikeOut)
        self.setFont(font)

    def setUnderline(self, isUnderline: bool):
        font = self.font()
        font.setUnderline(isUnderline)
        self.setFont(font)

    def _onContextMenuRequested(self, pos):
        menu = QMenu(self)
        act = menu.addAction(self.tr("复制"))
        act.triggered.connect(self._copyText)
        menu.exec(self.mapToGlobal(pos))

    def _copyText(self):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self.text())

    pixelFontSize = Property(int, getPixelFontSize, setPixelFontSize)
    strikeOut = Property(bool, lambda self: self.font().strikeOut(), setStrikeOut)
    underline = Property(bool, lambda self: self.font().underline(), setUnderline)


class CaptionLabel(FluentLabelBase):
    """说明文字（12px）。"""

    def __init__(self, text=None, parent=None):
        super().__init__(parent)
        if text is not None:
            self.setText(text)

    def getFont(self):
        return getFont(12)


class BodyLabel(FluentLabelBase):
    """正文（14px）。"""

    def __init__(self, text=None, parent=None):
        super().__init__(parent)
        if text is not None:
            self.setText(text)

    def getFont(self):
        return getFont(14)


class StrongBodyLabel(FluentLabelBase):
    """强调正文（14px 半粗）。"""

    def __init__(self, text=None, parent=None):
        super().__init__(parent)
        if text is not None:
            self.setText(text)

    def getFont(self):
        return getFont(14, QFont.DemiBold)


class SubtitleLabel(FluentLabelBase):
    """小标题（20px 半粗）。"""

    def __init__(self, text=None, parent=None):
        super().__init__(parent)
        if text is not None:
            self.setText(text)

    def getFont(self):
        return getFont(20, QFont.DemiBold)


class TitleLabel(FluentLabelBase):
    """大标题（28px 半粗）。"""

    def __init__(self, text=None, parent=None):
        super().__init__(parent)
        if text is not None:
            self.setText(text)

    def getFont(self):
        return getFont(28, QFont.DemiBold)


class CardWidget(BackgroundAnimationWidget, QFrame):
    """卡片（对齐上游 CardWidget：上下弧线描边 + 三态底色动画）。"""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self._isClickEnabled = False
        self._borderRadius = 5

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        self.clicked.emit()

    def setClickEnabled(self, isEnabled: bool):
        self._isClickEnabled = isEnabled
        self.update()

    def isClickEnabled(self):
        return self._isClickEnabled

    def _normalBackgroundColor(self):
        return QColor(255, 255, 255, 13 if isDarkTheme() else 170)

    def _hoverBackgroundColor(self):
        return QColor(255, 255, 255, 21 if isDarkTheme() else 64)

    def _pressedBackgroundColor(self):
        return QColor(255, 255, 255, 8 if isDarkTheme() else 64)

    def getBorderRadius(self):
        return self._borderRadius

    def setBorderRadius(self, radius: int):
        self._borderRadius = radius
        self.update()

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        r = self.borderRadius
        d = 2 * r
        isDark = isDarkTheme()

        # 上描边
        from PySide6.QtGui import QPainterPath
        path = QPainterPath()
        path.arcMoveTo(1, h - d - 1, d, d, 240)
        path.arcTo(1, h - d - 1, d, d, 225, -60)
        path.lineTo(1, r)
        path.arcTo(1, 1, d, d, -180, -90)
        path.lineTo(w - r, 1)
        path.arcTo(w - d - 1, 1, d, d, 90, -90)
        path.lineTo(w - 1, h - r)
        path.arcTo(w - d - 1, h - d - 1, d, d, 0, -60)

        topBorderColor = QColor(0, 0, 0, 20)
        if isDark:
            if self.isPressed:
                topBorderColor = QColor(255, 255, 255, 18)
            elif self.isHover:
                topBorderColor = QColor(255, 255, 255, 13)
        else:
            topBorderColor = QColor(0, 0, 0, 15)
        painter.strokePath(path, topBorderColor)

        # 下描边
        path = QPainterPath()
        path.arcMoveTo(1, h - d - 1, d, d, 240)
        path.arcTo(1, h - d - 1, d, d, 240, 30)
        path.lineTo(w - r - 1, h - 1)
        path.arcTo(w - d - 1, h - d - 1, d, d, 270, 30)

        bottomBorderColor = topBorderColor
        if not isDark and self.isHover and not self.isPressed:
            bottomBorderColor = QColor(0, 0, 0, 27)
        painter.strokePath(path, bottomBorderColor)

        # 背景
        painter.setPen(Qt.NoPen)
        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.setBrush(self.backgroundColor)
        painter.drawRoundedRect(rect, r, r)

    borderRadius = Property(int, getBorderRadius, setBorderRadius)


class SimpleCardWidget(CardWidget):
    """简洁卡片（对齐上游 SimpleCardWidget：纯底色 + 细描边，无三态动画）。"""

    def __init__(self, parent=None):
        super().__init__(parent)

    def _normalBackgroundColor(self):
        return QColor(255, 255, 255, 13 if isDarkTheme() else 170)

    def _hoverBackgroundColor(self):
        return self._normalBackgroundColor()

    def _pressedBackgroundColor(self):
        return self._normalBackgroundColor()

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing)
        painter.setBrush(self.backgroundColor)
        painter.setPen(QColor(0, 0, 0, 48) if isDarkTheme() else QColor(0, 0, 0, 12))
        r = self.borderRadius
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), r, r)


class ElevatedCardWidget(SimpleCardWidget):
    """凸起卡片（对齐上游 ElevatedCardWidget：阴影 + hover 上浮 3px）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.shadowAni = DropShadowAnimation(self, hoverColor=QColor(0, 0, 0, 20))
        self.shadowAni.setOffset(0, 5)
        self.shadowAni.setBlurRadius(38)

        self.elevatedAni = QPropertyAnimation(self, b"pos", self)
        self.elevatedAni.setDuration(100)

        self._originalPos = self.pos()
        self.setBorderRadius(8)

    def enterEvent(self, e):
        super().enterEvent(e)
        if self.elevatedAni.state() != QPropertyAnimation.Running:
            self._originalPos = self.pos()
        self._startElevateAni(self.pos(), self.pos() - QPoint(0, 3))

    def leaveEvent(self, e):
        super().leaveEvent(e)
        self._startElevateAni(self.pos(), self._originalPos)

    def mousePressEvent(self, e):
        super().mousePressEvent(e)
        self._startElevateAni(self.pos(), self._originalPos)

    def _startElevateAni(self, start, end):
        self.elevatedAni.setStartValue(start)
        self.elevatedAni.setEndValue(end)
        self.elevatedAni.start()

    def _hoverBackgroundColor(self):
        return QColor(255, 255, 255, 16) if isDarkTheme() else QColor(255, 255, 255)

    def _pressedBackgroundColor(self):
        return QColor(255, 255, 255, 6 if isDarkTheme() else 118)


class ScrollArea(QScrollArea):
    """平滑滚动区（对齐上游 ScrollArea）。

    Constructors
    ------------
    * ScrollArea(`parent`: QWidget = None)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.scrollDelagate = SmoothScrollDelegate(self)
        self.setWidgetResizable(True)

    def enableTransparentBackground(self):
        self.setStyleSheet("QScrollArea{border: none; background: transparent}")
        if self.widget():
            self.widget().setStyleSheet("QWidget{background: transparent}")


class PivotItem(PushButton):
    """Pivot 分段项（对齐上游 PivotItem）。"""

    itemClicked = Signal(bool)

    def _postInit(self):
        self.isSelected = False
        self.setProperty("isSelected", False)
        self.clicked.connect(lambda: self.itemClicked.emit(True))
        self.setAttribute(Qt.WA_LayoutUsesWidgetRect)
        FluentStyleSheet.PIVOT.apply(self)
        setFont(self, 18)

    def setSelected(self, isSelected: bool):
        if self.isSelected == isSelected:
            return
        self.isSelected = isSelected
        self.setProperty("isSelected", isSelected)
        self.setStyle(QApplication.style())
        self.update()


class Pivot(QWidget):
    """Pivot 分段导航（对齐上游 Pivot：底部指示器 + 滑移动画）。"""

    currentItemChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.items = {}
        self._currentRouteKey = None
        self._indicatorLength = 16

        self.lightIndicatorColor = QColor()
        self.darkIndicatorColor = QColor()

        self.hBoxLayout = QHBoxLayout(self)
        self.slideAni = ScaleSlideAnimation(self)

        FluentStyleSheet.PIVOT.apply(self)

        self.hBoxLayout.setSpacing(0)
        self.hBoxLayout.setAlignment(Qt.AlignLeft)
        self.hBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.hBoxLayout.setSizeConstraint(QHBoxLayout.SetMinimumSize)

        self.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Minimum)
        self.slideAni.valueChanged.connect(lambda: self.update())

    def addItem(self, routeKey: str, text: str, onClick=None, icon=None):
        return self.insertItem(-1, routeKey, text, onClick, icon)

    def addWidget(self, routeKey: str, widget, onClick=None):
        self.insertWidget(-1, routeKey, widget, onClick)

    def insertItem(self, index: int, routeKey: str, text: str, onClick=None,
                   icon=None):
        if routeKey in self.items:
            return
        item = PivotItem(text, self)
        if icon:
            item.setIcon(icon)
        self.insertWidget(index, routeKey, item, onClick)
        return item

    def insertWidget(self, index: int, routeKey: str, widget, onClick=None):
        if routeKey in self.items:
            return
        widget.setProperty("routeKey", routeKey)
        widget.itemClicked.connect(self._onItemClicked)
        if onClick:
            widget.itemClicked.connect(onClick)
        self.items[routeKey] = widget
        self.hBoxLayout.insertWidget(index, widget, 1)

    def removeWidget(self, routeKey: str):
        if routeKey not in self.items:
            return
        item = self.items.pop(routeKey)
        self.hBoxLayout.removeWidget(item)
        item.deleteLater()
        if not self.items:
            self._currentRouteKey = None

    def clear(self):
        for k, w in list(self.items.items()):
            self.hBoxLayout.removeWidget(w)
            w.deleteLater()
        self.items.clear()
        self._currentRouteKey = None

    def currentItem(self):
        if self._currentRouteKey is None:
            return None
        return self.widget(self._currentRouteKey)

    def currentRouteKey(self):
        return self._currentRouteKey

    def setCurrentItem(self, routeKey: str):
        if routeKey not in self.items or routeKey == self.currentRouteKey():
            return
        self._adjustIndicatorPos()
        self._currentRouteKey = routeKey
        self.slideAni.startAnimation(self.currentIndicatorGeometry())
        for k, item in self.items.items():
            item.setSelected(k == routeKey)
        self.currentItemChanged.emit(routeKey)

    def showEvent(self, e):
        super().showEvent(e)
        self._adjustIndicatorPos()

    def setIndicatorLength(self, length: int):
        self._indicatorLength = length
        self._adjustIndicatorPos()

    def indicatorLength(self):
        return self._indicatorLength

    def setItemFontSize(self, size: int):
        for item in self.items.values():
            font = item.font()
            font.setPixelSize(size)
            item.setFont(font)
            item.adjustSize()

    def setItemText(self, routeKey: str, text: str):
        self.widget(routeKey).setText(text)

    def setIndicatorColor(self, light, dark):
        self.lightIndicatorColor = QColor(light)
        self.darkIndicatorColor = QColor(dark)
        self.update()

    def _onItemClicked(self):
        item = self.sender()
        self.setCurrentItem(item.property("routeKey"))

    def widget(self, routeKey: str):
        if routeKey not in self.items:
            raise KeyError("`%s` is illegal." % routeKey)
        return self.items[routeKey]

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._adjustIndicatorPos()

    def _adjustIndicatorPos(self):
        item = self.currentItem()
        if item:
            self.slideAni.stop()
            self.slideAni.setValue(self.currentIndicatorGeometry())

    def currentIndicatorGeometry(self):
        item = self.currentItem()
        if not item:
            return QRectF(0, self.height() - 3, self.indicatorLength(), 3)
        rect = item.geometry()
        return QRectF(rect.x() - self.indicatorLength() // 2
                      + rect.width() // 2, self.height() - 3,
                      self.indicatorLength(), 3)

    def paintEvent(self, e):
        super().paintEvent(e)
        if not self.currentItem():
            return
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(autoFallbackThemeColor(self.lightIndicatorColor,
                                                self.darkIndicatorColor))
        painter.drawRoundedRect(self.slideAni.geometry, 1.5, 1.5)


class SegmentedWidget(Pivot):
    """分段控件（对齐上游 SegmentedWidget：选中背景块 + 底部指示器）。

    Constructors
    ------------
    * SegmentedWidget(`parent`: QWidget = None)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._slideX = 0.0
        # POINT_TO_POINT 语义：187ms + bezier(0.55, 0.55, 0, 1)
        self.slideAni = QPropertyAnimation(self, b"slideX", self)
        self.slideAni.setDuration(187)
        self.slideAni.setEasingCurve(createBezierCurve(0.55, 0.55, 0, 1))
        self.setAttribute(Qt.WA_StyledBackground)

    def insertItem(self, index: int, routeKey: str, text: str, onClick=None,
                   icon=None):
        if routeKey in self.items:
            return
        item = PivotItem(text, self)
        if icon:
            item.setIcon(icon)
        self.insertWidget(index, routeKey, item, onClick)
        return item

    def setCurrentItem(self, routeKey: str):
        if routeKey not in self.items or routeKey == self.currentRouteKey():
            return
        item = self.items[routeKey]
        start = self._slideX
        end = item.x()
        self._currentRouteKey = routeKey
        self.slideAni.stop()
        self.slideAni.setStartValue(start)
        self.slideAni.setEndValue(float(end))
        self.slideAni.start()
        for k, it in self.items.items():
            it.setSelected(k == routeKey)
        self.currentItemChanged.emit(routeKey)

    def getSlideX(self):
        return self._slideX

    def setSlideX(self, x):
        self._slideX = x
        self.update()

    slideX = Property(float, getSlideX, setSlideX)

    def _adjustIndicatorPos(self):
        """基类挂钩：直接吸附（不动画），兼容被替换的 slideAni 类型。"""
        item = self.currentItem()
        if item:
            self.slideAni.stop()
            self._slideX = float(item.x())
            self.update()

    def paintEvent(self, e):
        QWidget.paintEvent(self, e)
        if not self.currentItem():
            return
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing)

        if isDarkTheme():
            painter.setPen(QColor(255, 255, 255, 14))
            painter.setBrush(QColor(255, 255, 255, 15))
        else:
            painter.setPen(QColor(0, 0, 0, 19))
            painter.setBrush(QColor(255, 255, 255, 179))

        item = self.currentItem()
        rect = item.rect().adjusted(1, 1, -1, -1).translated(int(self._slideX), 0)
        painter.drawRoundedRect(rect, 5, 5)

        # 底部指示器
        painter.setPen(Qt.NoPen)
        painter.setBrush(autoFallbackThemeColor(self.lightIndicatorColor,
                                                self.darkIndicatorColor))
        x = int(self.currentItem().width() / 2 - 8 + self._slideX)
        painter.drawRoundedRect(QRectF(x, self.height() - 3.5, 16, 3), 1.5, 1.5)


class ProgressBar(QProgressBar):
    """进度条（对齐上游 ProgressBar：val 动画 + 暂停/错误态）。

    Constructors
    ------------
    * ProgressBar(`parent`: QWidget = None, `useAni`: bool = True)
    """

    def __init__(self, parent=None, useAni=True):
        super().__init__(parent)
        self._val = 0
        self.setFixedHeight(4)

        self._useAni = useAni
        self.lightBackgroundColor = QColor(0, 0, 0, 155)
        self.darkBackgroundColor = QColor(255, 255, 255, 155)
        self._lightBarColor = QColor()
        self._darkBarColor = QColor()
        self.ani = QPropertyAnimation(self, b"val", self)

        self._isPaused = False
        self._isError = False
        self.valueChanged.connect(self._onValueChanged)
        self.setValue(0)

    def getVal(self):
        return self._val

    def setVal(self, v: float):
        self._val = v
        self.update()

    def isUseAni(self):
        return self._useAni

    def setUseAni(self, isUse: bool):
        self._useAni = isUse

    def _onValueChanged(self, value):
        if not self.useAni:
            self._val = value
            return
        self.ani.stop()
        self.ani.setEndValue(value)
        self.ani.setDuration(150)
        self.ani.start()
        super().setValue(value)

    def lightBarColor(self):
        return self._lightBarColor if self._lightBarColor.isValid() else themeColor()

    def darkBarColor(self):
        return self._darkBarColor if self._darkBarColor.isValid() else themeColor()

    def setCustomBarColor(self, light, dark):
        self._lightBarColor = QColor(light)
        self._darkBarColor = QColor(dark)
        self.update()

    def setCustomBackgroundColor(self, light, dark):
        self.lightBackgroundColor = QColor(light)
        self.darkBackgroundColor = QColor(dark)
        self.update()

    def resume(self):
        self._isPaused = False
        self._isError = False
        self.update()

    def pause(self):
        self._isPaused = True
        self.update()

    def setPaused(self, isPaused: bool):
        self._isPaused = isPaused
        self.update()

    def isPaused(self):
        return self._isPaused

    def error(self):
        self._isError = True
        self.update()

    def setError(self, isError: bool):
        self._isError = isError
        if isError:
            self.error()
        else:
            self.resume()

    def isError(self):
        return self._isError

    def barColor(self):
        if self.isPaused():
            return QColor(252, 225, 0) if isDarkTheme() else QColor(157, 93, 0)
        if self.isError():
            return QColor(255, 153, 164) if isDarkTheme() else QColor(196, 43, 28)
        return self.darkBarColor() if isDarkTheme() else self.lightBarColor()

    def valText(self):
        if self.maximum() <= self.minimum():
            return ""
        from PySide6.QtCore import QLocale
        total = self.maximum() - self.minimum()
        result = self.format()
        locale = self.locale()
        locale.setNumberOptions(locale.numberOptions()
                                | QLocale.OmitGroupSeparator)
        result = result.replace("%m", locale.toString(total))
        result = result.replace("%v", locale.toString(self.val))
        if total == 0:
            return result.replace("%p", locale.toString(100))
        progress = int((self.val - self.minimum()) * 100 / total)
        return result.replace("%p", locale.toString(progress))

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing)

        bc = (self.darkBackgroundColor if isDarkTheme()
              else self.lightBackgroundColor)
        painter.setPen(bc)
        y = self.height() // 2
        painter.drawLine(0, y, self.width(), y)

        if self.minimum() >= self.maximum():
            return

        painter.setPen(Qt.NoPen)
        painter.setBrush(self.barColor())
        w = int(self.val / (self.maximum() - self.minimum()) * self.width())
        r = self.height() / 2
        painter.drawRoundedRect(QRectF(0, 0, w, self.height()), r, r)

    useAni = Property(bool, isUseAni, setUseAni)
    val = Property(float, getVal, setVal)


class ProgressRing(ProgressBar):
    """进度环（对齐上游 ProgressRing：描边圆环 + 居中文字）。

    Constructors
    ------------
    * ProgressRing(`parent`: QWidget = None, `useAni`: bool = True)
    """

    def __init__(self, parent=None, useAni=True):
        super().__init__(parent, useAni=useAni)
        self.lightBackgroundColor = QColor(0, 0, 0, 34)
        self.darkBackgroundColor = QColor(255, 255, 255, 34)
        self._strokeWidth = 6
        self.setTextVisible(False)
        self.setFixedSize(100, 100)
        setFont(self)

    def getStrokeWidth(self):
        return self._strokeWidth

    def setStrokeWidth(self, w: int):
        self._strokeWidth = w
        self.update()

    def _drawText(self, painter: QPainter, text: str):
        painter.setFont(self.font())
        painter.setPen(Qt.white if isDarkTheme() else Qt.black)
        painter.drawText(self.rect(), Qt.AlignCenter, text)

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing)

        cw = self._strokeWidth
        w = min(self.height(), self.width()) - cw
        rc = QRectF(cw / 2, self.height() / 2 - w / 2, w, w)

        bc = (self.darkBackgroundColor if isDarkTheme()
              else self.lightBackgroundColor)
        pen = QPen(bc, cw, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        painter.setPen(pen)
        painter.drawArc(rc, 0, 360 * 16)

        if self.maximum() <= self.minimum():
            return

        pen.setColor(self.barColor())
        painter.setPen(pen)
        degree = int(self.val / (self.maximum() - self.minimum()) * 360)
        painter.drawArc(rc, 90 * 16, -degree * 16)

        if self.isTextVisible():
            self._drawText(painter, self.valText())

    strokeWidth = Property(int, getStrokeWidth, setStrokeWidth)


class TableItemDelegate(QStyledItemDelegate):
    """表格/列表行委托（对齐上游 TableItemDelegate 的绘制面）。

    行级绘制：悬停/按压/选中底色、首列圆角、选中指示条、复选框。
    （上游的 ItemViewToolTipDelegate 悬浮提示未移植，Qt 默认
    DisplayRole 提示行为保留。）
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.margin = 2
        self.hoverRow = -1
        self.pressedRow = -1
        self.selectedRows = set()
        self.lightCheckedColor = QColor()
        self.darkCheckedColor = QColor()

    def setHoverRow(self, row: int):
        self.hoverRow = row

    def setPressedRow(self, row: int):
        self.pressedRow = row

    def setSelectedRows(self, indexes):
        self.selectedRows.clear()
        for index in indexes:
            self.selectedRows.add(index.row())
            if index.row() == self.pressedRow:
                self.pressedRow = -1

    def sizeHint(self, option, index):
        from PySide6.QtCore import QMargins
        size = super().sizeHint(option, index)
        return size.grownBy(QMargins(0, self.margin, 0, self.margin))

    def createEditor(self, parent, option, index):
        lineEdit = LineEdit(parent)
        lineEdit.setProperty("transparent", False)
        lineEdit.setStyle(QApplication.style())
        lineEdit.setText(option.text)
        lineEdit.setClearButtonEnabled(True)
        return lineEdit

    def updateEditorGeometry(self, editor, option, index):
        rect = option.rect
        y = rect.y() + (rect.height() - editor.height()) // 2
        x, w = max(8, rect.x()), rect.width()
        if index.column() == 0:
            w -= 8
        editor.setGeometry(x, y, w, rect.height())

    def setCheckedColor(self, light, dark):
        self.lightCheckedColor = QColor(light)
        self.darkCheckedColor = QColor(dark)
        self.parent().viewport().update()

    def _drawBackground(self, painter, option, index):
        r = 5
        if index.column() == 0:
            rect = option.rect.adjusted(4, 0, r + 1, 0)
            painter.drawRoundedRect(rect, r, r)
        elif index.column() == index.model().columnCount(index.parent()) - 1:
            rect = option.rect.adjusted(-r - 1, 0, -4, 0)
            painter.drawRoundedRect(rect, r, r)
        else:
            rect = option.rect.adjusted(-1, 0, 1, 0)
            painter.drawRect(rect)

    def _drawIndicator(self, painter, option, index):
        y, h = option.rect.y(), option.rect.height()
        ph = round(0.35 * h if self.pressedRow == index.row() else 0.257 * h)
        painter.setBrush(autoFallbackThemeColor(self.lightCheckedColor,
                                                self.darkCheckedColor))
        painter.drawRoundedRect(QRectF(4, ph + y, 3, h - 2 * ph), 1.5, 1.5)

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.font = index.data(Qt.FontRole) or getFont(13)
        textColor = Qt.white if isDarkTheme() else Qt.black
        textBrush = index.data(Qt.ForegroundRole)
        if textBrush is not None:
            textColor = QBrush(textBrush).color()
        option.palette.setColor(QPalette.Text, textColor)
        option.palette.setColor(QPalette.HighlightedText, textColor)

    def paint(self, painter, option, index):
        painter.save()
        painter.setPen(Qt.NoPen)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setClipping(True)
        painter.setClipRect(option.rect)
        option.rect.adjust(0, self.margin, 0, -self.margin)

        isHover = self.hoverRow == index.row()
        isPressed = self.pressedRow == index.row()
        isAlternate = (index.row() % 2 == 0
                       and self.parent().alternatingRowColors())
        isDark = isDarkTheme()

        c = 255 if isDark else 0
        alpha = 0
        if index.row() not in self.selectedRows:
            if isPressed:
                alpha = 9 if isDark else 6
            elif isHover:
                alpha = 12
            elif isAlternate:
                alpha = 5
        else:
            if isPressed:
                alpha = 15 if isDark else 9
            elif isHover:
                alpha = 25
            else:
                alpha = 17

        if index.data(Qt.BackgroundRole):
            painter.setBrush(index.data(Qt.BackgroundRole))
        else:
            painter.setBrush(QColor(c, c, c, alpha))

        self._drawBackground(painter, option, index)

        if (index.row() in self.selectedRows and index.column() == 0
                and self.parent().horizontalScrollBar().value() == 0):
            self._drawIndicator(painter, option, index)

        if index.data(Qt.CheckStateRole) is not None:
            self._drawCheckBox(painter, option, index)

        painter.restore()
        super().paint(painter, option, index)

    def _drawCheckBox(self, painter, option, index):
        painter.save()
        checkState = Qt.CheckState(index.data(Qt.CheckStateRole))
        isDark = isDarkTheme()

        r = 4.5
        x = option.rect.x() + 15
        y = option.rect.center().y() - 9.5
        rect = QRectF(x, y, 19, 19)

        if checkState == Qt.CheckState.Unchecked:
            painter.setBrush(QColor(0, 0, 0, 26) if isDark else QColor(0, 0, 0, 6))
            painter.setPen(QColor(255, 255, 255, 142) if isDark
                           else QColor(0, 0, 0, 122))
            painter.drawRoundedRect(rect, r, r)
        else:
            color = autoFallbackThemeColor(self.lightCheckedColor,
                                           self.darkCheckedColor)
            painter.setPen(color)
            painter.setBrush(color)
            painter.drawRoundedRect(rect, r, r)
            if checkState == Qt.CheckState.Checked:
                _CHECK_ICONS[0].render(
                    painter, rect,
                    fill="#FFFFFF" if not isDark else "#000000")
            else:
                _CHECK_ICONS[1].render(
                    painter, rect,
                    fill="#FFFFFF" if not isDark else "#000000")
        painter.restore()


class TableBase:
    """表格基类（对齐上游 TableBase：行委托 + 平滑滚动 + 表头设置）。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.delegate = TableItemDelegate(self)
        self.scrollDelagate = SmoothScrollDelegate(self)
        self._isSelectRightClickedRow = False

        FluentStyleSheet.TABLE_VIEW.apply(self)

        self.setShowGrid(False)
        self.setMouseTracking(True)
        self.setAlternatingRowColors(True)
        self.setItemDelegate(self.delegate)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.horizontalHeader().setHighlightSections(False)
        self.verticalHeader().setHighlightSections(False)
        self.verticalHeader().setDefaultSectionSize(38)

        self.entered.connect(lambda i: self._setHoverRow(i.row()))
        self.pressed.connect(lambda i: self._setPressedRow(i.row()))
        self.verticalHeader().sectionClicked.connect(self.selectRow)

    def setBorderVisible(self, isVisible: bool):
        self.setProperty("isBorderVisible", isVisible)
        from ._theme import updateDynamicStyle
        updateDynamicStyle(self)

    def setBorderRadius(self, radius: int):
        qss = "QTableView{border-radius: %dpx}" % radius
        setCustomStyleSheet(self, qss, qss)

    def setCheckedColor(self, light, dark):
        self.delegate.setCheckedColor(light, dark)

    def _setHoverRow(self, row: int):
        self.delegate.setHoverRow(row)
        self.viewport().update()

    def _setPressedRow(self, row: int):
        if self.selectionMode() == QTableView.SelectionMode.NoSelection:
            return
        self.delegate.setPressedRow(row)
        self.viewport().update()

    def _setSelectedRows(self, indexes):
        if self.selectionMode() == QTableView.SelectionMode.NoSelection:
            return
        self.delegate.setSelectedRows(indexes)
        self.viewport().update()

    def leaveEvent(self, e):
        QTableView.leaveEvent(self, e)
        self._setHoverRow(-1)

    def resizeEvent(self, e):
        QTableView.resizeEvent(self, e)
        self.viewport().update()

    def keyPressEvent(self, e):
        QTableView.keyPressEvent(self, e)
        self.updateSelectedRows()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton or self._isSelectRightClickedRow:
            return QTableView.mousePressEvent(self, e)
        index = self.indexAt(e.pos())
        if index.isValid():
            self._setPressedRow(index.row())
        QWidget.mousePressEvent(self, e)

    def mouseReleaseEvent(self, e):
        QTableView.mouseReleaseEvent(self, e)
        self.updateSelectedRows()
        if self.indexAt(e.pos()).row() < 0 or e.button() == Qt.RightButton:
            self._setPressedRow(-1)

    def setItemDelegate(self, delegate):
        self.delegate = delegate
        super().setItemDelegate(delegate)

    def selectAll(self):
        QTableView.selectAll(self)
        self.updateSelectedRows()

    def selectRow(self, row: int):
        QTableView.selectRow(self, row)
        self.updateSelectedRows()

    def clearSelection(self):
        QTableView.clearSelection(self)
        self.updateSelectedRows()

    def setCurrentIndex(self, index):
        QTableView.setCurrentIndex(self, index)
        self.updateSelectedRows()

    def updateSelectedRows(self):
        self._setSelectedRows(self.selectedIndexes())


class TableWidget(TableBase, QTableWidget):
    """Fluent 表格控件。"""


class TableView(TableBase, QTableView):
    """Fluent 表格视图。"""


class ListBase:
    """列表基类（对齐上游 ListBase：行委托 + 平滑滚动）。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.delegate = TableItemDelegate(self)
        self.scrollDelegate = SmoothScrollDelegate(self)
        self._isSelectRightClickedRow = False

        FluentStyleSheet.LIST_VIEW.apply(self)
        self.setItemDelegate(self.delegate)
        self.setMouseTracking(True)

        self.entered.connect(lambda i: self._setHoverRow(i.row()))
        self.pressed.connect(lambda i: self._setPressedRow(i.row()))

    def _setHoverRow(self, row: int):
        self.delegate.setHoverRow(row)
        self.viewport().update()

    def _setPressedRow(self, row: int):
        if self.selectionMode() == QListView.SelectionMode.NoSelection:
            return
        self.delegate.setPressedRow(row)
        self.viewport().update()

    def _setSelectedRows(self, indexes):
        if self.selectionMode() == QListView.SelectionMode.NoSelection:
            return
        self.delegate.setSelectedRows(indexes)
        self.viewport().update()

    def leaveEvent(self, e):
        QListView.leaveEvent(self, e)
        self._setHoverRow(-1)

    def resizeEvent(self, e):
        QListView.resizeEvent(self, e)
        self.viewport().update()

    def keyPressEvent(self, e):
        QListView.keyPressEvent(self, e)
        self.updateSelectedRows()

    def setCheckedColor(self, light, dark):
        self.delegate.setCheckedColor(light, dark)

    def updateSelectedRows(self):
        self._setSelectedRows(self.selectedIndexes())


class ListWidget(ListBase, QListWidget):
    """Fluent 列表控件（对齐上游 ListWidget）。

    Constructors
    ------------
    * ListWidget(`parent`: QWidget = None)
    """

    def __init__(self, parent=None):
        super().__init__(parent)

    def setCurrentItem(self, item, command=None):
        self.setCurrentRow(self.row(item), command)

    def setCurrentRow(self, row: int, command=None):
        if not command:
            super().setCurrentRow(row)
        else:
            super().setCurrentRow(row, command)
        self.updateSelectedRows()
