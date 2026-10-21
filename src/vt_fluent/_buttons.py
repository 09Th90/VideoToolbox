# -*- coding: utf-8 -*-
# @version 2.5.1
"""vt_fluent 按钮族（自研，替代 qfluentwidgets.components.widgets.button）。

行为契约（对齐上游 1.11.3）：
· PushButton/PrimaryPushButton/ToolButton 三态（hover/pressed/disabled 的
  图标透明度 0.786/0.63、文字色）、hasIcon 属性驱动的 padding（12px 左内边距
  vs 36px 图标位）；
· HyperlinkButton：主题色文字 + 打开 URL；
· RadioButton：自绘圆环指示器（10px 半径、hover/pressed 分态）；
· 下拉按钮族：ARROW_DOWN 箭头 + 回弹动画，菜单鸭子类型（QMenu 直接可用，
  B2 的 RoundMenu 带 flyout 语义时自动走 aniType 参数）；
· PillPushButton：自绘胶囊（全圆角 = 半高），checked 取主题色。

弹层降级说明（B1→B2 过渡）：下拉/补全弹层默认用 QMenu 兜底；B2 的
_menu.py 落地后 _showMenu 自动识别 RoundMenu（有 view/heightForAnimation）
并走 flyout 动画路径，控件侧零改动。
"""

from ._anim import singledispatchmethod

from PySide6.QtCore import QPoint, QRectF, QSize, Qt, QUrl, Property, Signal
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPainterPath
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QRadioButton, QSizePolicy, QToolButton, QWidget

from ._anim import TranslateYAnimation
from ._icon import (Action, FluentIcon, FluentIconBase, Icon, drawIcon, isDarkTheme,
                    toQIcon)
from ._theme import (Theme, ThemeColor, autoFallbackThemeColor, FluentStyleSheet,
                     setFont, themeColor)


def _menu_exec(menu, pos, ani_type=None):
    """鸭子类型弹菜单：RoundMenu（含子类）走 flyout，QMenu 只收 pos。

    ⚠ RoundMenu 子类必须用非绑定调用 ``RoundMenu.exec(menu, ...)``：
    PySide6 会把子类实例的 ``menu.exec(pos, aniType=...)`` 派发到 C++
    QMenu.exec 并抛 AttributeError（详见 _menu.show_menu 的 docstring）。
    函数级 import 避开 _menu ↔ _buttons 的循环导入。
    """
    from ._menu import RoundMenu
    if isinstance(menu, RoundMenu):
        RoundMenu.exec(menu, pos, aniType=ani_type)
        return
    try:
        menu.exec(pos, aniType=ani_type)
    except (TypeError, AttributeError):
        menu.exec(pos)


def _menu_width_fit(menu, button):
    """有 view 的菜单（RoundMenu）按按钮宽度补最小宽；QMenu 跳过。"""
    view = getattr(menu, "view", None)
    if view is None:
        return
    try:
        if view.width() < button.width():
            view.setMinimumWidth(button.width())
            menu.adjustSize()
    except Exception:
        pass


class PushButton(QPushButton):
    """标准按钮。

    Constructors
    ------------
    * PushButton(`parent`: QWidget = None)
    * PushButton(`text`: str, `parent`: QWidget = None,
                 `icon`: QIcon | str | FluentIconBase = None)
    * PushButton(`icon`: QIcon | FluentIconBase, `text`: str, `parent`: QWidget = None)
    """

    @singledispatchmethod
    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        FluentStyleSheet.BUTTON.apply(self)
        self.isPressed = False
        self.isHover = False
        self.setIconSize(QSize(16, 16))
        self.setIcon(None)
        setFont(self)
        self._postInit()

    @__init__.register
    def _(self, text: str, parent: QWidget = None,
          icon=None):
        self.__init__(parent=parent)
        self.setText(text)
        self.setIcon(icon)

    @__init__.register
    def _(self, icon: QIcon, text: str, parent: QWidget = None):
        self.__init__(text, parent, icon)

    @__init__.register
    def _(self, icon: FluentIconBase, text: str, parent: QWidget = None):
        self.__init__(text, parent, icon)

    def _postInit(self):
        pass

    def setIcon(self, icon):
        has_icon = not (icon is None
                        or (isinstance(icon, QIcon) and icon.isNull()))
        self._icon = icon or QIcon()
        if self.property("hasIcon") != has_icon:
            self.setProperty("hasIcon", has_icon)
            self._repolish()
        self.update()

    def _repolish(self):
        """动态属性变更后重算 QSS（动态属性不会自动触发重算）。

        ⚠ 不要用 setStyle(QApplication.style())：它会把控件的 style 指针
        换成 app 的 QStyleSheetStyle，主题/全局样式重建后
        [hasIcon=true] 规则可能不再命中，padding-left 退回 12px，
        自绘图标就会压在文字上。
        """
        self.style().unpolish(self)
        self.style().polish(self)
        self.updateGeometry()

    def icon(self):
        return toQIcon(self._icon)

    def setProperty(self, name, value):
        if name != "icon":
            return super().setProperty(name, value)
        self.setIcon(value)
        return True

    def mousePressEvent(self, e):
        self.isPressed = True
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        self.isPressed = False
        super().mouseReleaseEvent(e)

    def enterEvent(self, e):
        self.isHover = True
        self.update()

    def leaveEvent(self, e):
        self.isHover = False
        self.update()

    def _drawIcon(self, icon, painter, rect, state=QIcon.Off):
        drawIcon(icon, painter, rect, state)

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.icon().isNull():
            return
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing |
                               QPainter.SmoothPixmapTransform)
        if not self.isEnabled():
            painter.setOpacity(0.3628)
        elif self.isPressed:
            painter.setOpacity(0.786)
        w, h = self.iconSize().width(), self.iconSize().height()
        y = (self.height() - h) / 2
        mw = self.minimumSizeHint().width()
        x = 12 + (self.width() - mw) // 2 if mw > 0 else 12
        if self.isRightToLeft():
            x = self.width() - w - x
        try:
            self._drawIcon(self._icon, painter, QRectF(x, y, w, h))
        finally:
            # 显式收尾：PySide6 的 QPainter 在 GC 前不会 end()，子类
            # (CommandButton) 紧接着再开一个 painter 会撞「A paint device
            # can only be painted by one painter at a time」而**静默**画不出
            # 东西。用 finally 兜住 _drawIcon 抛异常的情况，免得 painter
            # 泄漏到下一次 paint 把所有后续自绘一起废掉。
            painter.end()


class PrimaryPushButton(PushButton):
    """主题色主按钮（图标反色：浅色档画深色图标）。"""

    def _drawIcon(self, icon, painter, rect, state=QIcon.Off):
        if isinstance(icon, FluentIconBase) and self.isEnabled():
            # 主按钮上图标反色（浅底深图标 / 深底浅图标）
            theme = Theme.DARK if not isDarkTheme() else Theme.LIGHT
            icon = icon.icon(theme)
        elif not self.isEnabled():
            painter.setOpacity(0.786 if isDarkTheme() else 0.9)
            if isinstance(icon, FluentIconBase):
                icon = icon.icon(Theme.DARK)
        PushButton._drawIcon(self, icon, painter, rect, state)


class TransparentPushButton(PushButton):
    """透明底按钮（QSS 里与 PushButton 同规则，仅语义区分）。"""


class ToggleButton(PushButton):
    """可勾选按钮（checked 走主按钮视觉）。"""

    def _postInit(self):
        self.setCheckable(True)
        self.setChecked(False)

    def _drawIcon(self, icon, painter, rect):
        if not self.isChecked():
            return PushButton._drawIcon(self, icon, painter, rect)
        PrimaryPushButton._drawIcon(self, icon, painter, rect, QIcon.On)


TogglePushButton = ToggleButton


class TransparentTogglePushButton(TogglePushButton):
    """透明底可勾选按钮。"""


class HyperlinkButton(PushButton):
    """超链接按钮（主题色文字，点击打开 URL）。

    Constructors
    ------------
    * HyperlinkButton(`parent`: QWidget = None)
    * HyperlinkButton(`url`: str, `text`: str, `parent`: QWidget = None,
                      `icon`: QIcon | str | FluentIconBase = None)
    * HyperlinkButton(`icon`: QIcon | FluentIconBase, `url`: str, `text`: str,
                      `parent`: QWidget = None)
    """

    @singledispatchmethod
    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self._url = QUrl()
        FluentStyleSheet.BUTTON.apply(self)
        self.setCursor(Qt.PointingHandCursor)
        setFont(self)
        self.clicked.connect(self._onClicked)

    @__init__.register
    def _(self, url: str, text: str, parent: QWidget = None, icon=None):
        self.__init__(parent)
        self.setText(text)
        self.setUrl(url)
        self.setIcon(icon)

    @__init__.register
    def _(self, icon: QIcon, url: str, text: str, parent: QWidget = None):
        self.__init__(url, text, parent, icon)

    @__init__.register
    def _(self, icon: FluentIconBase, url: str, text: str, parent: QWidget = None):
        self.__init__(url, text, parent, icon)

    def getUrl(self):
        return self._url

    def setUrl(self, url):
        self._url = QUrl(url)

    def _onClicked(self):
        if self.getUrl().isValid():
            QDesktopServices.openUrl(self.getUrl())

    def _drawIcon(self, icon, painter, rect, state=QIcon.Off):
        if isinstance(icon, FluentIconBase) and self.isEnabled():
            icon = icon.icon(color=themeColor())
        elif not self.isEnabled():
            painter.setOpacity(0.3628 if isDarkTheme() else 0.36)
        drawIcon(icon, painter, rect, state)

    url = Property(QUrl, getUrl, setUrl)


class RadioButton(QRadioButton):
    """单选按钮（自绘圆环指示器）。

    Constructors
    ------------
    * RadioButton(`parent`: QWidget = None)
    * RadioButton(`text`: str, `parent`: QWidget = None)
    """

    @singledispatchmethod
    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self._lightTextColor = QColor(0, 0, 0)
        self._darkTextColor = QColor(255, 255, 255)
        self.lightIndicatorColor = QColor()
        self.darkIndicatorColor = QColor()
        self.indicatorPos = QPoint(11, 12)
        self.isHover = False
        FluentStyleSheet.BUTTON.apply(self)
        self.setAttribute(Qt.WA_MacShowFocusRect, False)
        self._postInit()

    @__init__.register
    def _(self, text: str, parent: QWidget = None):
        self.__init__(parent)
        self.setText(text)

    def _postInit(self):
        pass

    def enterEvent(self, e):
        self.isHover = True
        self.update()

    def leaveEvent(self, e):
        self.isHover = False
        self.update()

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        self._drawIndicator(painter)
        self._drawText(painter)

    def _drawText(self, painter):
        if not self.isEnabled():
            painter.setOpacity(0.36)
        painter.setFont(self.font())
        painter.setPen(self.textColor())
        painter.drawText(QRectF(29, 0, self.width(), self.height()).toRect(),
                         Qt.AlignVCenter, self.text())

    def _drawIndicator(self, painter):
        if self.isChecked():
            if self.isEnabled():
                borderColor = autoFallbackThemeColor(
                    self.lightIndicatorColor, self.darkIndicatorColor)
            else:
                borderColor = QColor(255, 255, 255, 40) if isDarkTheme() \
                    else QColor(0, 0, 0, 55)
            filledColor = Qt.black if isDarkTheme() else Qt.white
            if self.isHover and not self.isDown():
                self._drawCircle(painter, self.indicatorPos, 10, 4,
                                 borderColor, filledColor)
            else:
                self._drawCircle(painter, self.indicatorPos, 10, 5,
                                 borderColor, filledColor)
        else:
            if self.isEnabled():
                if not self.isDown():
                    borderColor = QColor(255, 255, 255, 153) if isDarkTheme() \
                        else QColor(0, 0, 0, 153)
                else:
                    borderColor = QColor(255, 255, 255, 40) if isDarkTheme() \
                        else QColor(0, 0, 0, 55)
                if self.isDown():
                    filledColor = Qt.black if isDarkTheme() else Qt.white
                elif self.isHover:
                    filledColor = QColor(255, 255, 255, 11) if isDarkTheme() \
                        else QColor(0, 0, 0, 15)
                else:
                    filledColor = QColor(0, 0, 0, 26) if isDarkTheme() \
                        else QColor(0, 0, 0, 6)
            else:
                filledColor = Qt.transparent
                borderColor = QColor(255, 255, 255, 40) if isDarkTheme() \
                    else QColor(0, 0, 0, 55)
            self._drawCircle(painter, self.indicatorPos, 10, 1,
                             borderColor, filledColor)
            if self.isEnabled() and self.isDown():
                borderColor = QColor(255, 255, 255, 40) if isDarkTheme() \
                    else QColor(0, 0, 0, 24)
                self._drawCircle(painter, self.indicatorPos, 9, 4,
                                 borderColor, Qt.transparent)

    def _drawCircle(self, painter, center, radius, thickness, borderColor, filledColor):
        path = QPainterPath()
        path.setFillRule(Qt.WindingFill)
        outerRect = QRectF(center.x() - radius, center.y() - radius,
                           2 * radius, 2 * radius)
        path.addEllipse(outerRect)
        ir = radius - thickness
        innerRect = QRectF(center.x() - ir, center.y() - ir, 2 * ir, 2 * ir)
        innerPath = QPainterPath()
        innerPath.addEllipse(innerRect)
        path = path.subtracted(innerPath)
        painter.setPen(Qt.NoPen)
        painter.fillPath(path, borderColor)
        painter.fillPath(innerPath, filledColor)

    def textColor(self):
        return self._darkTextColor if isDarkTheme() else self._lightTextColor

    def getLightTextColor(self):
        return self._lightTextColor

    def setLightTextColor(self, color):
        self._lightTextColor = QColor(color)
        self.update()

    def getDarkTextColor(self):
        return self._darkTextColor

    def setDarkTextColor(self, color):
        self._darkTextColor = QColor(color)
        self.update()

    def setIndicatorColor(self, light, dark):
        self.lightIndicatorColor = QColor(light)
        self.darkIndicatorColor = QColor(dark)
        self.update()

    def setTextColor(self, light, dark):
        self.setLightTextColor(light)
        self.setDarkTextColor(dark)

    lightTextColor = Property(QColor, lambda self: self._lightTextColor,
                              lambda self, c: self.setLightTextColor(c))
    darkTextColor = Property(QColor, lambda self: self._darkTextColor,
                             lambda self, c: self.setDarkTextColor(c))


class ToolButton(QToolButton):
    """工具按钮（图标居中）。

    Constructors
    ------------
    * ToolButton(`parent`: QWidget = None)
    * ToolButton(`icon`: QIcon | str | FluentIconBase, `parent`: QWidget = None)
    """

    @singledispatchmethod
    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        FluentStyleSheet.BUTTON.apply(self)
        self.isPressed = False
        self.isHover = False
        self.setIconSize(QSize(16, 16))
        self.setIcon(QIcon())
        setFont(self)
        self._postInit()

    @__init__.register
    def _(self, icon: FluentIconBase, parent: QWidget = None):
        self.__init__(parent)
        self.setIcon(icon)

    @__init__.register
    def _(self, icon: QIcon, parent: QWidget = None):
        self.__init__(parent)
        self.setIcon(icon)

    @__init__.register
    def _(self, icon: str, parent: QWidget = None):
        self.__init__(parent)
        self.setIcon(icon)

    def _postInit(self):
        pass

    def setIcon(self, icon):
        self._icon = icon
        self.update()

    def icon(self):
        return toQIcon(self._icon)

    def setProperty(self, name, value):
        if name != "icon":
            return super().setProperty(name, value)
        self.setIcon(value)
        return True

    def mousePressEvent(self, e):
        self.isPressed = True
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        self.isPressed = False
        super().mouseReleaseEvent(e)

    def enterEvent(self, e):
        self.isHover = True
        self.update()

    def leaveEvent(self, e):
        self.isHover = False
        self.update()

    def _drawIcon(self, icon, painter, rect, state=QIcon.Off):
        drawIcon(icon, painter, rect, state)

    def paintEvent(self, e):
        super().paintEvent(e)
        if self._icon is None:
            return
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing |
                               QPainter.SmoothPixmapTransform)
        if not self.isEnabled():
            painter.setOpacity(0.43)
        elif self.isPressed:
            painter.setOpacity(0.63)
        w, h = self.iconSize().width(), self.iconSize().height()
        y = (self.height() - h) / 2
        x = (self.width() - w) / 2
        try:
            self._drawIcon(self._icon, painter, QRectF(x, y, w, h))
        finally:
            painter.end()   # 同上：给后续自绘留出干净的 paint device


class TransparentToolButton(ToolButton):
    """透明底工具按钮。"""


class PrimaryToolButton(ToolButton):
    """主题色工具按钮（图标反色）。"""

    def _drawIcon(self, icon, painter, rect, state=QIcon.Off):
        if isinstance(icon, FluentIconBase) and self.isEnabled():
            theme = Theme.DARK if not isDarkTheme() else Theme.LIGHT
            icon = icon.icon(theme)
        elif isinstance(icon, Icon) and self.isEnabled():
            theme = Theme.DARK if not isDarkTheme() else Theme.LIGHT
            icon = icon.fluentIcon.icon(theme)
        elif not self.isEnabled():
            painter.setOpacity(0.786 if isDarkTheme() else 0.9)
            if isinstance(icon, FluentIconBase):
                icon = icon.icon(Theme.DARK)
        return drawIcon(icon, painter, rect, state)


class ToggleToolButton(ToolButton):
    """可勾选工具按钮。"""

    def _postInit(self):
        self.setCheckable(True)
        self.setChecked(False)

    def _drawIcon(self, icon, painter, rect):
        if not self.isChecked():
            return ToolButton._drawIcon(self, icon, painter, rect)
        PrimaryToolButton._drawIcon(self, icon, painter, rect, QIcon.On)


class TransparentToggleToolButton(ToggleToolButton):
    """透明底可勾选工具按钮。"""


class DropDownButtonBase:
    """下拉按钮基类：箭头回弹动画 + 鸭子类型菜单。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._menu = None
        self.arrowAni = TranslateYAnimation(self)

    def setMenu(self, menu):
        self._menu = menu

    def menu(self):
        return self._menu

    def _showMenu(self):
        if not self.menu():
            return
        menu = self.menu()
        _menu_width_fit(menu, self)
        x = -menu.width() // 2 + self.width() // 2
        pos = self.mapToGlobal(QPoint(x, self.height()))
        # 枚举在 _menu 里定义；函数内导入避开 _menu ↔ _buttons 循环依赖
        from ._menu import MenuAnimationType
        # 上方空间不足时上拉；RoundMenu 有 heightForAnimation 时用精确判定，
        # QMenu 兜底直接向下弹
        try:
            hd = menu.view.heightForAnimation(pos, MenuAnimationType.DROP_DOWN)
            pu = self.mapToGlobal(QPoint(x, 0))
            hu = menu.view.heightForAnimation(pu, MenuAnimationType.PULL_UP)
        except Exception:
            hd, hu = 0, 0
        if hd >= hu:
            _menu_exec(menu, pos, MenuAnimationType.DROP_DOWN)
        else:
            _menu_exec(menu, self.mapToGlobal(QPoint(x, 0)),
                       MenuAnimationType.PULL_UP)

    def _hideMenu(self):
        if self.menu():
            self.menu().hide()

    def _drawDropDownIcon(self, painter, rect):
        if isDarkTheme():
            FluentIcon.ARROW_DOWN.render(painter, rect)
        else:
            FluentIcon.ARROW_DOWN.render(painter, rect, fill="#646464")

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing)
        if not self.isEnabled():
            painter.setOpacity(0.43 if isDarkTheme() else 0.6)
        elif self.isHover:
            painter.setOpacity(0.8)
        elif self.isPressed:
            painter.setOpacity(0.7)
        arrowY = self.height() / 2 - 5 + (self.arrowAni.y if self.isEnabled() else 0)
        rect = QRectF(self.width() - 22, arrowY, 10, 10)
        self._drawDropDownIcon(painter, rect)


class DropDownPushButton(DropDownButtonBase, PushButton):
    """下拉按钮（点击弹菜单）。

    Constructors
    ------------
    * DropDownPushButton(`parent`: QWidget = None)
    * DropDownPushButton(`text`: str, `parent`: QWidget = None,
                         `icon`: QIcon | str | FluentIconBase = None)
    * DropDownPushButton(`icon`: QIcon | FluentIconBase, `text`: str,
                         `parent`: QWidget = None)
    """

    def mouseReleaseEvent(self, e):
        PushButton.mouseReleaseEvent(self, e)
        self._showMenu()

    def paintEvent(self, e):
        PushButton.paintEvent(self, e)
        DropDownButtonBase.paintEvent(self, e)


class TransparentDropDownPushButton(DropDownPushButton):
    """透明底下拉按钮。"""


class DropDownToolButton(DropDownButtonBase, ToolButton):
    """下拉工具按钮。"""

    def mouseReleaseEvent(self, e):
        ToolButton.mouseReleaseEvent(self, e)
        self._showMenu()

    def _drawIcon(self, icon, painter, rect):
        rect.moveLeft(12)
        return super()._drawIcon(icon, painter, rect)

    def paintEvent(self, e):
        ToolButton.paintEvent(self, e)
        DropDownButtonBase.paintEvent(self, e)


class TransparentDropDownToolButton(DropDownToolButton):
    """透明底下拉工具按钮。"""


class PrimaryDropDownButtonBase(DropDownButtonBase):
    """主题色下拉按钮基类（箭头反色）。"""

    def _drawDropDownIcon(self, painter, rect):
        theme = Theme.DARK if not (self.isEnabled() and isDarkTheme()) else Theme.LIGHT
        FluentIcon.ARROW_DOWN.icon(theme).paint(painter, rect.toRect())


class PrimaryDropDownPushButton(PrimaryDropDownButtonBase, PrimaryPushButton):
    """主题色下拉按钮。"""

    def mouseReleaseEvent(self, e):
        PrimaryPushButton.mouseReleaseEvent(self, e)
        self._showMenu()

    def paintEvent(self, e):
        PrimaryPushButton.paintEvent(self, e)
        PrimaryDropDownButtonBase.paintEvent(self, e)


class PrimaryDropDownToolButton(PrimaryDropDownButtonBase, PrimaryToolButton):
    """主题色下拉工具按钮。"""

    def mouseReleaseEvent(self, e):
        PrimaryToolButton.mouseReleaseEvent(self, e)
        self._showMenu()

    def _drawIcon(self, icon, painter, rect):
        rect.moveLeft(12)
        return super()._drawIcon(icon, painter, rect)

    def paintEvent(self, e):
        PrimaryToolButton.paintEvent(self, e)
        PrimaryDropDownButtonBase.paintEvent(self, e)


class PillButtonBase:
    """胶囊按钮基类：自绘全圆角底（checked 取主题色）。"""

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing)
        isDark = isDarkTheme()

        if not self.isChecked():
            rect = self.rect().adjusted(1, 1, -1, -1)
            borderColor = QColor(255, 255, 255, 18) if isDark \
                else QColor(0, 0, 0, 15)
            if not self.isEnabled():
                bgColor = QColor(255, 255, 255, 11) if isDark \
                    else QColor(249, 249, 249, 75)
            elif self.isPressed or self.isHover:
                bgColor = QColor(255, 255, 255, 21) if isDark \
                    else QColor(249, 249, 249, 128)
            else:
                bgColor = QColor(255, 255, 255, 15) if isDark \
                    else QColor(243, 243, 243, 194)
        else:
            if not self.isEnabled():
                bgColor = QColor(255, 255, 255, 40) if isDark \
                    else QColor(0, 0, 0, 55)
            elif self.isPressed:
                bgColor = ThemeColor.DARK_2.color() if isDark \
                    else ThemeColor.LIGHT_3.color()
            elif self.isHover:
                bgColor = ThemeColor.DARK_1.color() if isDark \
                    else ThemeColor.LIGHT_1.color()
            else:
                bgColor = themeColor()
            borderColor = Qt.transparent
            rect = self.rect()

        painter.setPen(borderColor)
        painter.setBrush(bgColor)
        r = rect.height() / 2
        painter.drawRoundedRect(rect, r, r)


class PillPushButton(TogglePushButton, PillButtonBase):
    """胶囊按钮（可勾选）。

    Constructors
    ------------
    * PillPushButton(`parent`: QWidget = None)
    * PillPushButton(`text`: str, `parent`: QWidget = None,
                     `icon`: QIcon | str | FluentIconBase = None)
    * PillPushButton(`icon`: QIcon | FluentIconBase, `text`: str,
                     `parent`: QWidget = None)
    """

    def paintEvent(self, e):
        PillButtonBase.paintEvent(self, e)
        TogglePushButton.paintEvent(self, e)


class PillToolButton(ToggleToolButton, PillButtonBase):
    """胶囊工具按钮。"""

    def paintEvent(self, e):
        PillButtonBase.paintEvent(self, e)
        ToggleToolButton.paintEvent(self, e)


class SplitDropButton(ToolButton):
    """分段下拉按钮的箭头段。"""

    def _postInit(self):
        self.arrowAni = TranslateYAnimation(self)
        self.setIcon(FluentIcon.ARROW_DOWN)
        self.setIconSize(QSize(10, 10))
        self.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Expanding)

    def _drawIcon(self, icon, painter, rect):
        rect.translate(0, self.arrowAni.y if self.isEnabled() else 0)
        if not self.isEnabled():
            painter.setOpacity(0.43 if isDarkTheme() else 0.36)
        elif self.isPressed:
            painter.setOpacity(0.5)
        elif self.isHover:
            painter.setOpacity(1)
        else:
            painter.setOpacity(0.63)
        super()._drawIcon(icon, painter, rect)


class PrimarySplitDropButton(PrimaryToolButton):
    """主题色分段下拉按钮的箭头段。"""

    def _postInit(self):
        self.arrowAni = TranslateYAnimation(self)
        self.setIcon(FluentIcon.ARROW_DOWN)
        self.setIconSize(QSize(10, 10))
        self.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Expanding)

    def _drawIcon(self, icon, painter, rect):
        rect.translate(0, self.arrowAni.y if self.isEnabled() else 0)
        if self.isPressed:
            painter.setOpacity(0.7)
        elif self.isHover:
            painter.setOpacity(0.9)
        else:
            painter.setOpacity(1)
        if isinstance(icon, FluentIconBase):
            if self.isEnabled():
                icon = icon.icon(Theme.DARK if not isDarkTheme() else Theme.LIGHT)
            else:
                icon = icon.icon(Theme.DARK)
        super()._drawIcon(icon, painter, rect)
