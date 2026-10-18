# -*- coding: utf-8 -*-
# @version 2.3.1
"""vt_fluent 菜单族（自研，替代 qfluentwidgets.components.widgets.menu/command_bar）。

行为契约（对齐上游 1.11.3）：
· RoundMenu：圆角 flyout 菜单（QMenu 子类 + 自绘列表视图），
  addAction/addWidget/insertAction/removeAction/clear/setMaxVisibleItems/
  setItemHeight/setShadowEffect/actions()/view/closedSignal 全量 API；
  exec(pos, ani, aniType) 支持 DROP_DOWN/PULL_UP/FADE_IN 五档动画；
· MenuActionListWidget：adjustSize/heightForAnimation/itemsHeight/
  setItemHeight/setMaxVisibleItems（下拉按钮与 ComboBox 的宽度/高度判定依赖）；
· CommandBar：命令条（图标/文字/图文按钮、分隔符、溢出 more 菜单、
  hiddenAction 收纳），setSpaing/addAction/addSeparator/setToolButtonStyle。

B1 的 QMenu 兜底路径自动升级：_buttons._menu_exec 检测到 view/
heightForAnimation 即走 flyout 动画（鸭子类型，控件侧零改动）。
"""

from enum import Enum

from PySide6.QtCore import (QEasingCurve, QEvent, QModelIndex, QObject, QPoint,
                            QParallelAnimationGroup, QPropertyAnimation, QRect,
                            QRectF, QSize, Qt, QTimer, Signal)
from PySide6.QtGui import (QColor, QCursor, QFontMetrics, QHoverEvent, QIcon,
                           QKeySequence, QPainter, QPen, QPixmap, QRegion)
from PySide6.QtWidgets import (QApplication, QFrame, QGraphicsDropShadowEffect,
                               QHBoxLayout, QListWidget, QListWidgetItem, QMenu,
                               QStyle, QStyledItemDelegate, QStyleFactory,
                               QStyleOptionViewItem, QWidget)

from ._anim import SmoothScrollDelegate
from ._buttons import TransparentToggleToolButton
from ._icon import (Action, FluentIcon, FluentIconBase, FluentIconEngine,
                    Icon, toQIcon)
from ._theme import FluentStyleSheet, isDarkTheme, setFont, getFont


def getCurrentScreenGeometry():
    """当前鼠标所在屏幕的可用几何（对齐上游 common.screen）。"""
    screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
    return screen.availableGeometry()


class MenuAnimationType(Enum):
    """菜单动画类型（与上游逐名同值）。"""

    NONE = 0
    DROP_DOWN = 1
    PULL_UP = 2
    FADE_IN_DROP_DOWN = 3
    FADE_IN_PULL_UP = 4


class MenuItemDelegate(QStyledItemDelegate):
    """菜单项委托（分隔线自绘 + 快捷键右对齐）。"""

    def _isSeparator(self, index: QModelIndex):
        return index.model().data(index, Qt.DecorationRole) == "seperator"

    def paint(self, painter, option, index):
        if not self._isSeparator(index):
            return super().paint(painter, option, index)

        painter.save()
        c = 0 if not isDarkTheme() else 255
        pen = QPen(QColor(c, c, c, 25), 1)
        pen.setCosmetic(True)
        painter.setPen(pen)
        rect = option.rect
        painter.drawLine(0, rect.y() + 4, rect.width() + 12, rect.y() + 4)
        painter.restore()

    def helpEvent(self, event, view, option, index):
        return False


class ShortcutMenuItemDelegate(MenuItemDelegate):
    """带快捷键的菜单项委托。"""

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        if self._isSeparator(index):
            return

        action = index.data(Qt.UserRole)
        if not isinstance(action, Action) and not hasattr(action, "shortcut"):
            return
        try:
            shortcut = action.shortcut()
        except Exception:
            return
        if shortcut.isEmpty():
            return

        painter.save()
        if not (option.state & QStyle.State_Enabled):
            painter.setOpacity(0.5 if isDarkTheme() else 0.6)

        font = getFont(12)
        painter.setFont(font)
        painter.setPen(QColor(255, 255, 255, 200) if isDarkTheme()
                       else QColor(0, 0, 0, 153))

        fm = QFontMetrics(font)
        text = shortcut.toString(QKeySequence.NativeText)
        sw = fm.horizontalAdvance(text)
        painter.translate(option.rect.width() - sw - 20, 0)
        rect = QRectF(0, option.rect.y(), sw, option.rect.height())
        painter.drawText(rect, Qt.AlignLeft | Qt.AlignVCenter, text)
        painter.restore()


class MenuActionListWidget(QListWidget):
    """菜单项列表视图（对齐上游 MenuActionListWidget 的尺寸契约）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._itemHeight = 28
        self._maxVisibleItems = -1

        self.setViewportMargins(0, 6, 0, 6)
        self.setTextElideMode(Qt.ElideNone)
        self.setDragEnabled(False)
        self.setMouseTracking(True)
        self.setVerticalScrollMode(self.ScrollMode.ScrollPerPixel)
        self.setIconSize(QSize(14, 14))
        self.setItemDelegate(ShortcutMenuItemDelegate(self))

        self.scrollDelegate = SmoothScrollDelegate(self)

        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    def insertItem(self, row, item):
        super().insertItem(row, item)
        self.adjustSize()

    def addItem(self, item):
        super().addItem(item)
        self.adjustSize()

    def takeItem(self, row):
        item = super().takeItem(row)
        self.adjustSize()
        return item

    def adjustSize(self, pos=None, aniType=MenuAnimationType.NONE):
        size = QSize()
        for i in range(self.count()):
            s = self.item(i).sizeHint()
            size.setWidth(max(s.width(), size.width(), 1))
            size.setHeight(max(1, size.height() + s.height()))

        w, h = MenuAnimationManager.make(self, aniType).availableViewSize(pos)

        m = self.viewportMargins()
        size += QSize(m.left() + m.right() + 2, m.top() + m.bottom())
        size.setHeight(min(h, size.height() + 3))
        size.setWidth(max(min(w, size.width()), self.minimumWidth()))

        if self.maxVisibleItems() > 0:
            size.setHeight(min(size.height(),
                               self.maxVisibleItems() * self._itemHeight
                               + m.top() + m.bottom() + 3))

        self.setFixedSize(size)

    def setItemHeight(self, height: int):
        if height == self._itemHeight:
            return
        for i in range(self.count()):
            item = self.item(i)
            if not self.itemWidget(item):
                item.setSizeHint(QSize(item.sizeHint().width(), height))
        self._itemHeight = height
        self.adjustSize()

    def setMaxVisibleItems(self, num: int):
        self._maxVisibleItems = num
        self.adjustSize()

    def maxVisibleItems(self):
        return self._maxVisibleItems

    def heightForAnimation(self, pos: QPoint, aniType):
        ih = self.itemsHeight()
        _, sh = MenuAnimationManager.make(self, aniType).availableViewSize(pos)
        return min(ih, sh)

    def itemsHeight(self):
        n = (self.count() if self.maxVisibleItems() < 0
             else min(self.maxVisibleItems(), self.count()))
        h = sum(self.item(i).sizeHint().height() for i in range(n))
        m = self.viewportMargins()
        return h + m.top() + m.bottom()


class SubMenuItemWidget(QWidget):
    """子菜单项（悬停发信号 + 右箭头，对齐上游 SubMenuItemWidget）。"""

    showMenuSig = Signal(object)

    def __init__(self, menu, item, parent=None):
        super().__init__(parent)
        self.menu = menu
        self.item = item

    def enterEvent(self, e):
        super().enterEvent(e)
        self.showMenuSig.emit(self.item)

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing)
        FluentIcon.CHEVRON_RIGHT.render(
            painter, QRectF(self.width() - 10, self.height() / 2 - 4.5, 9, 9))


class RoundMenu(QMenu):
    """圆角 flyout 菜单（对齐上游 RoundMenu）。

    Constructors
    ------------
    * RoundMenu(`title`: str = "", `parent`: QWidget = None)
    """

    closedSignal = Signal()

    def __init__(self, title="", parent=None):
        super().__init__(parent=parent)
        self.setTitle(title)
        self._icon = QIcon()
        self._actions = []
        self._subMenus = []

        self.isSubMenu = False
        self.parentMenu = None
        self.menuItem = None
        self.lastHoverItem = None
        self.lastHoverSubMenuItem = None
        self.isHideBySystem = True
        self.itemHeight = 28

        self.hBoxLayout = QHBoxLayout(self)
        self.view = MenuActionListWidget(self)

        self.aniManager = None
        self.timer = QTimer(self)

        self._initWidgets()

    def _initWidgets(self):
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint
                            | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setStyle(QStyleFactory.create("fusion"))

        self.timer.setSingleShot(True)
        self.timer.setInterval(400)
        self.timer.timeout.connect(self._onShowMenuTimeOut)

        self.setShadowEffect()
        self.hBoxLayout.addWidget(self.view, 1, Qt.AlignCenter)
        self.hBoxLayout.setContentsMargins(12, 8, 12, 20)
        FluentStyleSheet.MENU.apply(self)

        self.view.itemClicked.connect(self._onItemClicked)
        self.view.itemEntered.connect(self._onItemEntered)

    def setMaxVisibleItems(self, num: int):
        self.view.setMaxVisibleItems(num)
        self.adjustSize()

    def setItemHeight(self, height):
        if height == self.itemHeight:
            return
        self.itemHeight = height
        self.view.setItemHeight(height)

    def setShadowEffect(self, blurRadius=30, offset=(0, 8),
                        color=QColor(0, 0, 0, 30)):
        self.shadowEffect = QGraphicsDropShadowEffect(self.view)
        self.shadowEffect.setBlurRadius(blurRadius)
        self.shadowEffect.setOffset(*offset)
        self.shadowEffect.setColor(color)
        self.view.setGraphicsEffect(None)
        self.view.setGraphicsEffect(self.shadowEffect)

    def _setParentMenu(self, parent, item):
        self.parentMenu = parent
        self.menuItem = item
        self.isSubMenu = True if parent else False

    def adjustSize(self):
        m = self.layout().contentsMargins()
        w = self.view.width() + m.left() + m.right()
        h = self.view.height() + m.top() + m.bottom()
        self.setFixedSize(w, h)

    def icon(self):
        return self._icon

    def title(self):
        return self._title

    def setIcon(self, icon):
        if isinstance(icon, FluentIconBase):
            icon = Icon(icon)
        self._icon = icon

    def setTitle(self, title: str):
        self._title = title
        super().setTitle(title)

    def clear(self):
        while self._actions:
            self.removeAction(self._actions[-1])
        while self._subMenus:
            self.removeMenu(self._subMenus[-1])

    # ---- 项构造 -------------------------------------------------------- #
    def _createActionItem(self, action, before=None):
        if not before:
            self._actions.append(action)
            super().addAction(action)
        elif before in self._actions:
            index = self._actions.index(before)
            self._actions.insert(index, action)
            super().insertAction(before, action)
        else:
            raise ValueError("`before` is not in the action list")

        item = QListWidgetItem(self._createItemIcon(action), action.text())
        self._adjustItemText(item, action)

        if not action.isEnabled():
            item.setFlags(Qt.NoItemFlags)
        if action.text() != action.toolTip():
            item.setToolTip(action.toolTip())

        item.setData(Qt.UserRole, action)
        action.setProperty("item", item)
        action.changed.connect(self._onActionChanged)
        return item

    def _hasItemIcon(self):
        return any(not i.icon().isNull()
                   for i in list(self._actions) + list(self._subMenus))

    def _adjustItemText(self, item, action):
        if isinstance(self.view.itemDelegate(), ShortcutMenuItemDelegate):
            sw = self._longestShortcutWidth()
            if sw:
                sw += 22
        else:
            sw = 0

        fm = self.view.fontMetrics()
        if not self._hasItemIcon():
            item.setText(action.text())
            w = 40 + fm.boundingRect(action.text()).width() + sw
        else:
            item.setText(" " + action.text())
            space = 4 - fm.boundingRect(" ").width()
            w = 60 + fm.boundingRect(item.text()).width() + sw + space

        item.setSizeHint(QSize(w, self.itemHeight))
        return w

    def _longestShortcutWidth(self):
        fm = QFontMetrics(getFont(12))
        return max([fm.horizontalAdvance(a.shortcut().toString(
            QKeySequence.NativeText)) for a in self.menuActions()] or [0])

    def _onActionChanged(self):
        action = self.sender()
        item = action.property("item")
        if item is None:
            return
        item.setIcon(self._createItemIcon(action))
        if action.text() != action.toolTip():
            item.setToolTip(action.toolTip())
        self._adjustItemText(item, action)
        if action.isEnabled():
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
        else:
            item.setFlags(Qt.NoItemFlags)
        self.view.adjustSize()
        self.adjustSize()

    def _createItemIcon(self, w):
        hasIcon = self._hasItemIcon()
        try:
            icon = QIcon(FluentIconEngine(w.icon()))
        except Exception:
            icon = QIcon()

        if hasIcon and w.icon().isNull():
            pixmap = QPixmap(self.view.iconSize())
            pixmap.fill(Qt.transparent)
            icon = QIcon(pixmap)
        elif not hasIcon:
            icon = QIcon()
        return icon

    # ---- 增删 ---------------------------------------------------------- #
    def addAction(self, action):
        item = self._createActionItem(action)
        self.view.addItem(item)
        self.adjustSize()

    def insertAction(self, before, action):
        if before not in self._actions:
            return
        beforeItem = before.property("item")
        if not beforeItem:
            return
        index = self.view.row(beforeItem)
        item = self._createActionItem(action, before)
        self.view.insertItem(index, item)
        self.adjustSize()

    def addActions(self, actions):
        for action in actions:
            self.addAction(action)

    def insertActions(self, before, actions):
        for action in actions:
            self.insertAction(before, action)

    def addWidget(self, widget: QWidget, selectable=True, onClick=None):
        action = Action(self)
        action.setProperty("selectable", selectable)

        item = QListWidgetItem()
        item.setSizeHint(widget.sizeHint())
        item.setData(Qt.UserRole, action)
        action.setProperty("item", item)
        item.setFlags(Qt.ItemIsEnabled)

        self.view.addItem(item)
        self.view.setItemWidget(item, widget)
        self._actions.append(action)

        if onClick:
            action.triggered.connect(onClick)
        self.adjustSize()
        return action

    def _removeItem(self, item):
        self.view.takeItem(self.view.row(item))

    def removeAction(self, action):
        if action not in self._actions:
            return
        item = action.property("item")
        self._actions.remove(action)
        action.setProperty("item", None)
        if not item:
            return
        self._removeItem(item)
        super().removeAction(action)
        self.adjustSize()

    def setDefaultAction(self, action):
        if action not in self._actions:
            return
        item = action.property("item")
        if item:
            self.view.setCurrentItem(item)

    def addMenu(self, menu):
        if not isinstance(menu, RoundMenu):
            raise ValueError("`menu` should be an instance of `RoundMenu`.")
        item, w = self._createSubMenuItem(menu)
        self.view.addItem(item)
        self.view.setItemWidget(item, w)
        self.adjustSize()

    def insertMenu(self, before, menu):
        if not isinstance(menu, RoundMenu):
            raise ValueError("`menu` should be an instance of `RoundMenu`.")
        if before not in self._actions:
            raise ValueError("`before` should be in menu action list")
        item, w = self._createSubMenuItem(menu)
        self.view.insertItem(self.view.row(before.property("item")), item)
        self.view.setItemWidget(item, w)
        self.adjustSize()

    def _createSubMenuItem(self, menu):
        self._subMenus.append(menu)

        item = QListWidgetItem(self._createItemIcon(menu), menu.title())
        fm = self.view.fontMetrics()
        if not self._hasItemIcon():
            w = 60 + fm.boundingRect(menu.title()).width()
        else:
            item.setText(" " + item.text())
            w = 72 + fm.boundingRect(item.text()).width()

        menu._setParentMenu(self, item)
        item.setSizeHint(QSize(w, self.itemHeight))
        item.setData(Qt.UserRole, menu)

        widget = SubMenuItemWidget(menu, item, self)
        widget.showMenuSig.connect(self._showSubMenu)
        return item, widget

    def removeMenu(self, menu):
        if menu not in self._subMenus:
            return
        item = menu.menuItem
        self._subMenus.remove(menu)
        self._removeItem(item)
        self.adjustSize()

    def menuActions(self):
        return self._actions

    # ---- 交互 ---------------------------------------------------------- #
    def _onItemClicked(self, item):
        action = item.data(Qt.UserRole)
        if isinstance(action, RoundMenu):
            return
        if action not in self._actions or not action.isEnabled():
            return
        if self.view.itemWidget(item) and not action.property("selectable"):
            return

        self._hideMenu(False)

        if not self.isSubMenu:
            action.trigger()
            return
        self._closeParentMenu()
        action.trigger()

    def _closeParentMenu(self):
        menu = self
        while menu:
            menu.close()
            menu = menu.parentMenu

    def _onItemEntered(self, item):
        self.lastHoverItem = item
        if not isinstance(item.data(Qt.UserRole), RoundMenu):
            return
        self._showSubMenu(item)

    def _showSubMenu(self, item):
        self.lastHoverItem = item
        self.lastHoverSubMenuItem = item
        self.timer.stop()
        self.timer.start()

    def _onShowMenuTimeOut(self):
        if (self.lastHoverSubMenuItem is None
                or self.lastHoverItem is not self.lastHoverSubMenuItem):
            return
        w = self.view.itemWidget(self.lastHoverSubMenuItem)
        if w is None or w.menu.parentMenu.isHidden():
            return

        itemRect = QRect(w.mapToGlobal(w.rect().topLeft()), w.size())
        x = itemRect.right() + 5
        y = itemRect.y() - 5

        screenRect = getCurrentScreenGeometry()
        subSize = w.menu.sizeHint()
        if x + subSize.width() > screenRect.right():
            x = max(itemRect.left() - subSize.width() - 5, screenRect.left())
        if y + subSize.height() > screenRect.bottom():
            y = screenRect.bottom() - subSize.height()
        y = max(y, screenRect.top())

        w.menu.exec(QPoint(x, y), aniType=MenuAnimationType.FADE_IN_DROP_DOWN)

    def _hideMenu(self, isHideBySystem=False):
        self.isHideBySystem = isHideBySystem
        self.view.clearSelection()
        if self.isSubMenu:
            self.hide()
        else:
            self.close()

    def hideEvent(self, e):
        if self.isHideBySystem and self.isSubMenu:
            self._closeParentMenu()
        self.isHideBySystem = True
        e.accept()

    def closeEvent(self, e):
        e.accept()
        self.closedSignal.emit()
        self.view.clearSelection()

    def mousePressEvent(self, e):
        w = self.childAt(e.pos())
        if w is not self.view and not self.view.isAncestorOf(w):
            self._hideMenu(True)

    def mouseMoveEvent(self, e):
        if not self.isSubMenu:
            return
        pos = e.globalPos()
        view = self.parentMenu.view
        margin = view.viewportMargins()
        rect = view.visualItemRect(self.menuItem).translated(
            view.mapToGlobal(QPoint()))
        rect = rect.translated(margin.left(), margin.top() + 2)
        if (self.parentMenu.geometry().contains(pos)
                and not rect.contains(pos)
                and not self.geometry().contains(pos)):
            view.clearSelection()
            self._hideMenu(False)

    def exec(self, pos, ani=True, aniType=MenuAnimationType.DROP_DOWN):
        self.aniManager = MenuAnimationManager.make(self, aniType)
        self.aniManager.exec(pos)
        self.show()
        if self.isSubMenu:
            self.menuItem.setSelected(True)

    def exec_(self, pos, ani=True, aniType=MenuAnimationType.DROP_DOWN):
        self.exec(pos, ani, aniType)

    def adjustPosition(self):
        m = self.layout().contentsMargins()
        rect = getCurrentScreenGeometry()
        w = self.layout().sizeHint().width() + 5
        h = self.layout().sizeHint().height()
        x = min(self.x() - m.left(), rect.right() - w)
        y = self.y()
        if y > rect.bottom() - h:
            y = self.y() - h + m.bottom()
        self.move(x, y)

    def paintEvent(self, e):
        pass


class MenuAnimationManager(QObject):
    """菜单动画管理器（对齐上游 MenuAnimationManager 的尺寸/位移动画）。"""

    managers = {}

    def __init__(self, menu: RoundMenu):
        super().__init__()
        self.menu = menu
        self.ani = QPropertyAnimation(menu, b"pos", menu)
        self.ani.setDuration(250)
        self.ani.setEasingCurve(QEasingCurve.OutQuad)
        self.ani.valueChanged.connect(self._onValueChanged)
        self.ani.valueChanged.connect(self._updateMenuViewport)

    def _onValueChanged(self):
        pass

    def availableViewSize(self, pos):
        ss = getCurrentScreenGeometry()
        return ss.width() - 100, ss.height() - 100

    def _updateMenuViewport(self):
        self.menu.view.viewport().update()
        self.menu.view.setAttribute(Qt.WA_UnderMouse, True)
        e = QHoverEvent(QEvent.HoverEnter, QPoint(), QPoint(1, 1))
        QApplication.sendEvent(self.menu.view, e)

    def _endPosition(self, pos):
        m = self.menu
        rect = getCurrentScreenGeometry()
        w, h = m.width() + 5, m.height()
        x = min(pos.x() - m.layout().contentsMargins().left(), rect.right() - w)
        y = min(pos.y() - 4, rect.bottom() - h + 10)
        return QPoint(x, y)

    def _menuSize(self):
        m = self.menu.layout().contentsMargins()
        w = self.menu.view.width() + m.left() + m.right() + 120
        h = self.menu.view.height() + m.top() + m.bottom() + 20
        return w, h

    def exec(self, pos):
        pass

    @classmethod
    def register(cls, name):
        def wrapper(Manager):
            if name not in cls.managers:
                cls.managers[name] = Manager
            return Manager
        return wrapper

    @classmethod
    def make(cls, menu, aniType):
        if aniType not in cls.managers:
            raise ValueError("`%s` is an invalid menu animation type." % aniType)
        return cls.managers[aniType](menu)


@MenuAnimationManager.register(MenuAnimationType.NONE)
class DummyMenuAnimationManager(MenuAnimationManager):
    def exec(self, pos):
        self.menu.move(self._endPosition(pos))


@MenuAnimationManager.register(MenuAnimationType.DROP_DOWN)
class DropDownMenuAnimationManager(MenuAnimationManager):
    def exec(self, pos):
        pos = self._endPosition(pos)
        h = self.menu.height() + 5
        self.ani.setStartValue(pos - QPoint(0, int(h / 2)))
        self.ani.setEndValue(pos)
        self.ani.start()

    def availableViewSize(self, pos):
        ss = getCurrentScreenGeometry()
        return ss.width() - 100, max(ss.bottom() - pos.y() - 10, 1)

    def _onValueChanged(self):
        w, h = self._menuSize()
        y = self.ani.endValue().y() - self.ani.currentValue().y()
        self.menu.setMask(QRegion(0, y, w, h))


@MenuAnimationManager.register(MenuAnimationType.PULL_UP)
class PullUpMenuAnimationManager(MenuAnimationManager):
    def _endPosition(self, pos):
        m = self.menu
        rect = getCurrentScreenGeometry()
        w, h = m.width() + 5, m.height()
        x = min(pos.x() - m.layout().contentsMargins().left(), rect.right() - w)
        y = max(pos.y() - h + 10, rect.top() + 4)
        return QPoint(x, y)

    def exec(self, pos):
        pos = self._endPosition(pos)
        h = self.menu.height() + 5
        self.ani.setStartValue(pos + QPoint(0, int(h / 2)))
        self.ani.setEndValue(pos)
        self.ani.start()

    def availableViewSize(self, pos):
        ss = getCurrentScreenGeometry()
        return ss.width() - 100, max(pos.y() - ss.top() - 28, 1)

    def _onValueChanged(self):
        w, h = self._menuSize()
        y = self.ani.endValue().y() - self.ani.currentValue().y()
        self.menu.setMask(QRegion(0, y, w, h - 28))


@MenuAnimationManager.register(MenuAnimationType.FADE_IN_DROP_DOWN)
class FadeInDropDownMenuAnimationManager(MenuAnimationManager):
    def __init__(self, menu):
        super().__init__(menu)
        self.opacityAni = QPropertyAnimation(menu, b"windowOpacity", self)
        self.aniGroup = QParallelAnimationGroup(self)
        self.aniGroup.addAnimation(self.ani)
        self.aniGroup.addAnimation(self.opacityAni)

    def exec(self, pos):
        pos = self._endPosition(pos)
        self.opacityAni.setStartValue(0)
        self.opacityAni.setEndValue(1)
        self.opacityAni.setDuration(150)
        self.opacityAni.setEasingCurve(QEasingCurve.OutQuad)
        self.ani.setStartValue(pos - QPoint(0, 8))
        self.ani.setEndValue(pos)
        self.ani.setDuration(150)
        self.ani.setEasingCurve(QEasingCurve.OutQuad)
        self.aniGroup.start()

    def availableViewSize(self, pos):
        ss = getCurrentScreenGeometry()
        return ss.width() - 100, max(ss.bottom() - pos.y() - 10, 1)


@MenuAnimationManager.register(MenuAnimationType.FADE_IN_PULL_UP)
class FadeInPullUpMenuAnimationManager(MenuAnimationManager):
    def __init__(self, menu):
        super().__init__(menu)
        self.opacityAni = QPropertyAnimation(menu, b"windowOpacity", self)
        self.aniGroup = QParallelAnimationGroup(self)
        self.aniGroup.addAnimation(self.ani)
        self.aniGroup.addAnimation(self.opacityAni)

    def _endPosition(self, pos):
        m = self.menu
        rect = getCurrentScreenGeometry()
        w, h = m.width() + 5, m.height()
        x = min(pos.x() - m.layout().contentsMargins().left(), rect.right() - w)
        y = max(pos.y() - h + 15, rect.top() + 4)
        return QPoint(x, y)

    def exec(self, pos):
        pos = self._endPosition(pos)
        self.opacityAni.setStartValue(0)
        self.opacityAni.setEndValue(1)
        self.opacityAni.setDuration(150)
        self.opacityAni.setEasingCurve(QEasingCurve.OutQuad)
        self.ani.setStartValue(pos + QPoint(0, 8))
        self.ani.setEndValue(pos)
        self.ani.setDuration(200)
        self.ani.setEasingCurve(QEasingCurve.OutQuad)
        self.aniGroup.start()

    def availableViewSize(self, pos):
        ss = getCurrentScreenGeometry()
        return ss.width() - 100, max(pos.y() - ss.top() - 10, 1)


class CommandButton(TransparentToggleToolButton):
    """命令条按钮（图标/文字/图文，对齐上游 CommandButton）。"""

    def _postInit(self):
        super()._postInit()
        self.setCheckable(False)
        self.setToolButtonStyle(Qt.ToolButtonIconOnly)
        setFont(self, 12)
        self._text = ""
        self._action = None
        self._isTight = False

    def setTight(self, isTight: bool):
        self._isTight = isTight
        self.update()

    def isTight(self):
        return self._isTight

    def sizeHint(self) -> QSize:
        if self.isIconOnly():
            return QSize(36, 34) if self.isTight() else QSize(48, 34)
        tw = self.fontMetrics().boundingRect(self.text()).width()
        style = self.toolButtonStyle()
        if style == Qt.ToolButtonTextBesideIcon:
            return QSize(tw + 47, 34)
        if style == Qt.ToolButtonTextOnly:
            return QSize(tw + 32, 34)
        return QSize(tw + 32, 50)

    def isIconOnly(self):
        if not self.text():
            return True
        return self.toolButtonStyle() in (Qt.ToolButtonIconOnly,
                                          Qt.ToolButtonFollowStyle)

    def text(self):
        return self._text

    def setText(self, text: str):
        self._text = text
        self.update()

    def setAction(self, action):
        self._action = action
        self._onActionChanged()
        self.clicked.connect(action.trigger)
        action.toggled.connect(self.setChecked)
        action.changed.connect(self._onActionChanged)

    def _onActionChanged(self):
        action = self.action()
        self.setIcon(action.icon())
        self.setText(action.text())
        self.setToolTip(action.toolTip())
        self.setEnabled(action.isEnabled())
        self.setCheckable(action.isCheckable())
        self.setChecked(action.isChecked())

    def action(self):
        return self._action

    def paintEvent(self, e):
        super().paintEvent(e)
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing |
                               QPainter.SmoothPixmapTransform)

        if not self.isChecked():
            painter.setPen(Qt.white if isDarkTheme() else Qt.black)
        else:
            painter.setPen(Qt.black if isDarkTheme() else Qt.white)

        if not self.isEnabled():
            painter.setOpacity(0.43)
        elif self.isPressed:
            painter.setOpacity(0.63)

        style = self.toolButtonStyle()
        iw, ih = self.iconSize().width(), self.iconSize().height()

        if self.isIconOnly():
            y = (self.height() - ih) / 2
            x = (self.width() - iw) / 2
            self._drawIcon(self._icon, painter, QRectF(x, y, iw, ih))
        elif style == Qt.ToolButtonTextOnly:
            painter.drawText(self.rect(), Qt.AlignCenter, self.text())
        elif style == Qt.ToolButtonTextBesideIcon:
            y = (self.height() - ih) / 2
            self._drawIcon(self._icon, painter, QRectF(11, y, iw, ih))
            rect = QRectF(26, 0, self.width() - 26, self.height())
            painter.drawText(rect, Qt.AlignCenter, self.text())
        elif style == Qt.ToolButtonTextUnderIcon:
            x = (self.width() - iw) / 2
            self._drawIcon(self._icon, painter, QRectF(x, 9, iw, ih))
            rect = QRectF(0, ih + 13, self.width(), self.height() - ih - 13)
            painter.drawText(rect, Qt.AlignHCenter | Qt.AlignTop, self.text())


class MoreActionsButton(CommandButton):
    """溢出「更多」按钮。"""

    def _postInit(self):
        super()._postInit()
        self.setIcon(FluentIcon.MORE)


class CommandSeparator(QWidget):
    """命令条分隔符。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(9, 34)

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setPen(QColor(255, 255, 255, 21) if isDarkTheme()
                       else QColor(0, 0, 0, 15))
        painter.drawLine(5, 2, 5, self.height() - 2)


class CommandMenu(RoundMenu):
    """命令条溢出菜单。"""

    def __init__(self, parent=None):
        super().__init__("", parent)
        self.setItemHeight(32)
        self.view.setIconSize(QSize(16, 16))


class CommandBar(QFrame):
    """命令条（对齐上游 CommandBar：动作按钮 + 分隔符 + 溢出收纳）。

    Constructors
    ------------
    * CommandBar(`parent`: QWidget = None)
    """

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self._widgets = []
        self._hiddenWidgets = []
        self._hiddenActions = []

        self._menuAnimation = MenuAnimationType.DROP_DOWN
        self._toolButtonStyle = Qt.ToolButtonIconOnly
        self._iconSize = QSize(16, 16)
        self._isButtonTight = False
        self._spacing = 4

        self.moreButton = MoreActionsButton(self)
        self.moreButton.clicked.connect(self._showMoreActionsMenu)
        self.moreButton.hide()

        setFont(self, 12)
        self.setAttribute(Qt.WA_TranslucentBackground)

    def setSpaing(self, spacing: int):
        """兼容上游拼写（setSpaing）。"""
        if spacing == self._spacing:
            return
        self._spacing = spacing
        self.updateGeometry()

    def spacing(self):
        return self._spacing

    def addAction(self, action):
        if action in self.actions():
            return
        button = self._createButton(action)
        self._insertWidgetToLayout(-1, button)
        super().addAction(action)
        return button

    def addActions(self, actions):
        for action in actions:
            self.addAction(action)

    def addHiddenAction(self, action):
        if action in self.actions():
            return
        self._hiddenActions.append(action)
        self.updateGeometry()
        super().addAction(action)

    def addHiddenActions(self, actions):
        for action in actions:
            self.addHiddenAction(action)

    def insertAction(self, before, action):
        if before not in self.actions():
            return
        index = self.actions().index(before)
        button = self._createButton(action)
        self._insertWidgetToLayout(index, button)
        super().insertAction(before, action)
        return button

    def addSeparator(self):
        self.insertSeparator(-1)

    def insertSeparator(self, index: int):
        self._insertWidgetToLayout(index, CommandSeparator(self))

    def addWidget(self, widget):
        self._insertWidgetToLayout(-1, widget)

    def removeAction(self, action):
        if action not in self.actions():
            return
        for w in self.commandButtons:
            if w.action() is action:
                self._widgets.remove(w)
                w.hide()
                w.deleteLater()
                break
        self.updateGeometry()

    def removeWidget(self, widget):
        if widget not in self._widgets:
            return
        self._widgets.remove(widget)
        self.updateGeometry()

    def removeHiddenAction(self, action):
        if action in self._hiddenActions:
            self._hiddenActions.remove(action)

    def setToolButtonStyle(self, style):
        if self.toolButtonStyle() == style:
            return
        self._toolButtonStyle = style
        for w in self.commandButtons:
            w.setToolButtonStyle(style)

    def toolButtonStyle(self):
        return self._toolButtonStyle

    def setButtonTight(self, isTight: bool):
        if self.isButtonTight() == isTight:
            return
        self._isButtonTight = isTight
        for w in self.commandButtons:
            w.setTight(isTight)
        self.updateGeometry()

    def isButtonTight(self):
        return self._isButtonTight

    def setIconSize(self, size):
        if size == self._iconSize:
            return
        self._iconSize = size
        for w in self.commandButtons:
            w.setIconSize(size)

    def iconSize(self):
        return self._iconSize

    def resizeEvent(self, e):
        self.updateGeometry()

    def _createButton(self, action):
        button = CommandButton(self)
        button.setAction(action)
        button.setToolButtonStyle(self.toolButtonStyle())
        button.setTight(self.isButtonTight())
        button.setIconSize(self.iconSize())
        button.setFont(self.font())
        return button

    def _insertWidgetToLayout(self, index: int, widget):
        widget.setParent(self)
        widget.show()
        if index < 0:
            self._widgets.append(widget)
        else:
            self._widgets.insert(index, widget)
        self.setFixedHeight(max(w.height() for w in self._widgets))
        self.updateGeometry()

    def minimumSizeHint(self) -> QSize:
        return self.moreButton.size()

    def updateGeometry(self):
        self._hiddenWidgets.clear()
        self.moreButton.hide()

        visibles = self._visibleWidgets()
        x = self.contentsMargins().left()
        h = self.height()

        for widget in visibles:
            widget.show()
            widget.move(x, (h - widget.height()) // 2)
            x += (widget.width() + self.spacing())

        if self._hiddenActions or len(visibles) < len(self._widgets):
            self.moreButton.show()
            self.moreButton.move(x, (h - self.moreButton.height()) // 2)

        for widget in self._widgets[len(visibles):]:
            widget.hide()
            self._hiddenWidgets.append(widget)

    def _visibleWidgets(self):
        if self.suitableWidth() <= self.width():
            return self._widgets

        w = self.moreButton.width()
        index = 0
        for index, widget in enumerate(self._widgets):
            w += widget.width()
            if index > 0:
                w += self.spacing()
            if w > self.width():
                break
        return self._widgets[:index]

    def suitableWidth(self):
        widths = [w.width() for w in self._widgets]
        if self._hiddenActions:
            widths.append(self.moreButton.width())
        return sum(widths) + self.spacing() * max(len(widths) - 1, 0)

    def resizeToSuitableWidth(self):
        self.setFixedWidth(self.suitableWidth())

    def setFont(self, font):
        super().setFont(font)
        for button in self.commandButtons:
            button.setFont(font)

    @property
    def commandButtons(self):
        return [w for w in self._widgets if isinstance(w, CommandButton)]

    def setMenuDropDown(self, down: bool):
        self._menuAnimation = (MenuAnimationType.DROP_DOWN if down
                               else MenuAnimationType.PULL_UP)

    def isMenuDropDown(self):
        return self._menuAnimation == MenuAnimationType.DROP_DOWN

    def _showMoreActionsMenu(self):
        actions = self._hiddenActions.copy()
        for w in reversed(self._hiddenWidgets):
            if isinstance(w, CommandButton):
                actions.insert(0, w.action())

        menu = CommandMenu(self)
        menu.addActions(actions)

        x = (-menu.width() + menu.layout().contentsMargins().right()
             + self.moreButton.width() + 18)
        y = (self.moreButton.height()
             if self._menuAnimation == MenuAnimationType.DROP_DOWN else -5)
        pos = self.moreButton.mapToGlobal(QPoint(x, y))
        menu.exec(pos, aniType=self._menuAnimation)

