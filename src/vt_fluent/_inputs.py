# -*- coding: utf-8 -*-
# @version 2.5.2
"""vt_fluent 输入族（自研，替代 qfluentwidgets 输入类控件）。

行为契约（对齐上游 1.11.3）：
· LineEdit/TextEdit/PlainTextEdit：固定高 33、聚焦底部下划线（主题色/错误红）、
  内嵌按钮（清除/查看密码/动作）、补全弹层、右键菜单；
· ComboBox：按钮式下拉（箭头回弹动画），完整项模型 API（addItem/currentIndex/
  currentText/itemData/setMaxVisibleItems…）、placeholder 文字态；
· EditableComboBox：可编辑下拉（行编辑 + 下拉按钮 + 补全联动）；
· SpinBox/CompactSpinBox：内联双按钮 / 紧凑单按钮 + 浮出步进；内部结构名
  （hBoxLayout/upButton/downButton/compactSpinButton）与 qt_compat
  的 SpinBox 补丁挂载点同名兼容；
· CheckBox：八态自绘指示器（18px 圆角 4.5）+ Accept/PartialAccept 图标；
· SwitchButton：滑块指示器（42×22，120ms 位移动画）+ 开关文字；
· Slider：自绘凹槽 + 圆点把手（22×22，100ms 半径动画）、点击定位。

弹层形态（B2 起）：下拉（ComboBoxMenu）/补全（CompleterMenu）/右键菜单
均已升级为 RoundMenu flyout（comboListWidget/completerListWidget objectName
供 QSS 选中态挂靠）；外部传入的 QMenu 由 _buttons._menu_exec 鸭子类型兼容。
"""

from enum import Enum

from PySide6.QtCore import (QEvent, QPoint, QPropertyAnimation, QRectF, QSize,
                            Qt, QTimer, Signal, Property)
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QCheckBox, QCompleter, QDoubleSpinBox,
                               QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
                               QPushButton, QSizePolicy, QSlider, QSpinBox,
                               QStyle, QStyleOptionButton, QTextEdit,
                               QToolButton, QVBoxLayout, QWidget)

from ._anim import TranslateYAnimation, SmoothScrollDelegate, singledispatchmethod
from ._buttons import ToolButton, TransparentToolButton, _menu_exec, \
                     _menu_width_fit
from ._menu import MenuAnimationType, RoundMenu
from ._icon import ExtraIcon, FluentIcon, drawIcon, toQIcon
from ._theme import (FluentStyleSheet, ThemeColor, autoFallbackThemeColor,
                     fallbackThemeColor, isDarkTheme, repolish, setFont,
                     setCustomStyleSheet, themeColor, updateDynamicStyle,
                     validColor, FluentSystemColor)

#: 数字框步进图标（上游 SpinIcon.UP/DOWN 等价物，EXTRA_ART 取字）
SPIN_UP = ExtraIcon("images_spin_box_Up")
SPIN_DOWN = ExtraIcon("images_spin_box_Down")
#: 复选图标（上游 CheckBoxIcon 等价物；绘制时按主题反色取 fill）
CHECK_ACCEPT = ExtraIcon("images_check_box_Accept")
CHECK_PARTIAL = ExtraIcon("images_check_box_PartialAccept")


class LineEditButton(QToolButton):
    """行编辑内嵌按钮（清除/查看密码/动作/下拉箭头，对齐上游 LineEditButton）。"""

    def __init__(self, icon, parent=None):
        super().__init__(parent)
        self._icon = icon
        self._action = None
        self.isPressed = False
        self.setFixedSize(31, 23)
        self.setIconSize(QSize(10, 10))
        self.setCursor(Qt.PointingHandCursor)
        self.setObjectName("lineEditButton")
        FluentStyleSheet.LINE_EDIT.apply(self)

    def setAction(self, action):
        self._action = action
        self._onActionChanged()
        self.clicked.connect(action.trigger)
        action.toggled.connect(self.setChecked)
        action.changed.connect(self._onActionChanged)

    def _onActionChanged(self):
        action = self.action()
        self.setIcon(action.icon())
        self.setToolTip(action.toolTip())
        self.setEnabled(action.isEnabled())
        self.setCheckable(action.isCheckable())
        self.setChecked(action.isChecked())

    def action(self):
        return self._action

    def setIcon(self, icon):
        self._icon = icon
        self.update()

    def mousePressEvent(self, e):
        self.isPressed = True
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        self.isPressed = False
        super().mouseReleaseEvent(e)

    def paintEvent(self, e):
        super().paintEvent(e)
        if self._icon is None:
            return
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing |
                               QPainter.SmoothPixmapTransform)
        iw, ih = self.iconSize().width(), self.iconSize().height()
        w, h = self.width(), self.height()
        rect = QRectF((w - iw) / 2, (h - ih) / 2, iw, ih)
        if self.isPressed:
            painter.setOpacity(0.7)
        if isDarkTheme():
            drawIcon(self._icon, painter, rect)
        else:
            drawIcon(self._icon, painter, rect, fill="#656565")


def _undo_available(widget) -> bool:
    """撤销可用态：QLineEdit 有 isUndoAvailable()，QTextEdit/QPlainTextEdit 无。

    多行编辑只能用 undoAvailable 信号反馈的末态，这里退化为「有文档修改记录
    或文档自带撤销栈」判断；取不到时按可用处理（禁用项比误禁更烦人）。
    """
    fn = getattr(widget, "isUndoAvailable", None)
    if callable(fn):
        return fn()
    doc = getattr(widget, "document", None)
    if callable(doc):
        return doc().isUndoAvailable()
    return True


def _redo_available(widget) -> bool:
    """重做可用态（同上：仅 QLineEdit 提供 isRedoAvailable）。"""
    fn = getattr(widget, "isRedoAvailable", None)
    if callable(fn):
        return fn()
    doc = getattr(widget, "document", None)
    if callable(doc):
        return doc().isRedoAvailable()
    return True


def _edit_context_menu(widget):
    """标准编辑右键菜单（RoundMenu 圆角弹层，行编辑/多行编辑共用）。

    行编辑与多行编辑共用：撤销/重做/剪切/复制/粘贴/删除/全选，
    各项可用态按控件当前状态初始化。
    """
    menu = RoundMenu("", widget)

    def _add(text, slot, enabled, shortcut=None):
        act = menu.addAction(text)
        act.triggered.connect(slot)
        act.setEnabled(enabled)
        if shortcut:
            act.setShortcut(shortcut)
        return act

    _add(widget.tr("撤销"), widget.undo, _undo_available(widget), "Ctrl+Z")
    _add(widget.tr("重做"), widget.redo, _redo_available(widget), "Ctrl+Y")
    menu.addSeparator()
    readonly = widget.isReadOnly()
    has_sel = widget.textCursor().hasSelection() if hasattr(widget, "textCursor") \
        else widget.hasSelectedText()
    _add(widget.tr("剪切"), widget.cut, has_sel and not readonly, "Ctrl+X")
    _add(widget.tr("复制"), widget.copy, has_sel, "Ctrl+C")
    _add(widget.tr("粘贴"), widget.paste, not readonly, "Ctrl+V")

    def _delete():
        if hasattr(widget, "textCursor"):
            widget.textCursor().removeSelectedText()
        else:
            widget.del_()

    _add(widget.tr("删除"), _delete, has_sel and not readonly)
    menu.addSeparator()
    _add(widget.tr("全选"), widget.selectAll, True, "Ctrl+A")
    return menu


class _CompleterMenu(RoundMenu):
    """补全弹层（对齐上游 CompleterMenu：RoundMenu + completerListWidget）。

    接口对齐上游使用面：setCompletion(model, column) / popup(pos) /
    activated(str)。
    """

    activated = Signal(str)

    def __init__(self, lineEdit, parent=None):
        super().__init__(parent)
        self._lineEdit = lineEdit
        self.view.setObjectName("completerListWidget")
        self.triggered.connect(self._onTriggered)

    def setCompletion(self, model, column=0):
        texts = []
        for row in range(model.rowCount()):
            idx = model.index(row, column)
            text = idx.data(Qt.DisplayRole)
            if text:
                texts.append(str(text))
        # 先清空旧项再重填（菜单复用：LineEdit 每次输入都会刷新）
        for action in self.actions():
            self.removeAction(action)
        for text in texts:
            self.addAction(text)

    def setItems(self, items):
        for text in items:
            self.addAction(text)

    def popup(self, pos):
        self.exec(pos, aniType=MenuAnimationType.FADE_IN_DROP_DOWN)

    # ⚠ PySide6 specificity：子类必须自带 exec 定义，否则调用被派发到
    # C++ QMenu.exec 抛 AttributeError（详见 _menu.show_menu）。
    def exec(self, pos, ani=True, aniType=MenuAnimationType.FADE_IN_DROP_DOWN):
        RoundMenu.exec(self, pos, aniType=aniType)

    def _onTriggered(self, action):
        self.activated.emit(action.text())


class LineEdit(QLineEdit):
    """行编辑（对齐上游 LineEdit）。

    Constructors
    ------------
    * LineEdit(`parent`: QWidget = None)
    * LineEdit(`text`: str, `parent`: QWidget = None)
    """

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self._isClearButtonEnabled = False
        self._completer = None
        self._completerMenu = None
        self._isError = False
        self.lightFocusedBorderColor = QColor()
        self.darkFocusedBorderColor = QColor()

        self.leftButtons = []
        self.rightButtons = []

        self.setProperty("transparent", True)
        FluentStyleSheet.LINE_EDIT.apply(self)
        self.setFixedHeight(33)
        self.setAttribute(Qt.WA_MacShowFocusRect, False)
        setFont(self)

        self.hBoxLayout = QHBoxLayout(self)
        self.clearButton = LineEditButton(FluentIcon.CLOSE, self)
        self.clearButton.setFixedSize(29, 25)
        self.clearButton.hide()

        self.hBoxLayout.setSpacing(3)
        self.hBoxLayout.setContentsMargins(4, 4, 4, 4)
        self.hBoxLayout.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.hBoxLayout.addWidget(self.clearButton, 0, Qt.AlignRight)

        self.clearButton.clicked.connect(self.clear)
        self.textChanged.connect(self._onTextChanged)
        self.textEdited.connect(self._onTextEdited)

    def isError(self):
        return self._isError

    def setError(self, isError: bool):
        if isError == self.isError():
            return
        self._isError = isError
        self.update()

    def setCustomFocusedBorderColor(self, light, dark):
        self.lightFocusedBorderColor = QColor(light)
        self.darkFocusedBorderColor = QColor(dark)
        self.update()

    def focusedBorderColor(self):
        if self.isError():
            return FluentSystemColor.CRITICAL_FOREGROUND.color()
        return autoFallbackThemeColor(self.lightFocusedBorderColor,
                                      self.darkFocusedBorderColor)

    def setClearButtonEnabled(self, enable: bool):
        self._isClearButtonEnabled = enable
        self._adjustTextMargins()

    def isClearButtonEnabled(self) -> bool:
        return self._isClearButtonEnabled

    def setCompleter(self, completer):
        self._completer = completer

    def completer(self):
        return self._completer

    def addAction(self, action, position=QLineEdit.ActionPosition.TrailingPosition):
        QLineEdit.addAction(self, action)

        button = LineEditButton(action.icon())
        button.setAction(action)
        button.setFixedWidth(29)

        if position == QLineEdit.ActionPosition.LeadingPosition:
            self.hBoxLayout.insertWidget(len(self.leftButtons), button, 0,
                                         Qt.AlignLeading)
            if not self.leftButtons:
                self.hBoxLayout.insertStretch(1, 1)
            self.leftButtons.append(button)
        else:
            self.rightButtons.append(button)
            self.hBoxLayout.addWidget(button, 0, Qt.AlignRight)

        self._adjustTextMargins()

    def addActions(self, actions, position=QLineEdit.ActionPosition.TrailingPosition):
        for action in actions:
            self.addAction(action, position)

    def _adjustTextMargins(self):
        left = len(self.leftButtons) * 30
        right = len(self.rightButtons) * 30 + 28 * self.isClearButtonEnabled()
        m = self.textMargins()
        self.setTextMargins(left, m.top(), right, m.bottom())

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        self.clearButton.hide()

    def focusInEvent(self, e):
        super().focusInEvent(e)
        if self.isClearButtonEnabled():
            self.clearButton.setVisible(bool(self.text()))

    def _onTextChanged(self, text):
        if self.isClearButtonEnabled():
            self.clearButton.setVisible(bool(text) and self.hasFocus())

    def _onTextEdited(self, text):
        if not self.completer():
            return
        if self.text():
            QTimer.singleShot(50, self._showCompleterMenu)
        elif self._completerMenu:
            self._completerMenu.close()

    def setCompleterMenu(self, menu):
        """挂补全弹层（B2 的 RoundMenu 版走同一接口）。"""
        menu.activated.connect(self._onCompleterActivated)
        self._completerMenu = menu

    def _onCompleterActivated(self, text):
        if self.completer():
            self.completer().activated.emit(text)

    def _showCompleterMenu(self):
        if not self.completer() or not self.text():
            return
        if not self._completerMenu:
            self.setCompleterMenu(_CompleterMenu(self))
        self.completer().setCompletionPrefix(self.text())
        self._completerMenu.setCompletion(
            self.completer().completionModel(),
            self.completer().completionColumn())
        if self._completerMenu.actions():
            pos = self.mapToGlobal(QPoint(0, self.height()))
            self._completerMenu.popup(pos)

    def contextMenuEvent(self, e):
        menu = _edit_context_menu(self)
        menu.exec(e.globalPos())

    def paintEvent(self, e):
        super().paintEvent(e)
        if not self.hasFocus():
            return
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        m = self.contentsMargins()
        w = self.width() - m.left() - m.right()
        h = self.height()
        path = QPainterPath()
        path.addRoundedRect(QRectF(m.left(), h - 10, w, 10), 5, 5)
        rectPath = QPainterPath()
        rectPath.addRect(m.left(), h - 10, w, 8)
        path = path.subtracted(rectPath)
        painter.fillPath(path, self.focusedBorderColor())


class PasswordLineEdit(LineEdit):
    """密码行编辑（对齐上游 PasswordLineEdit：查看按钮 + 禁 IME + 无右键菜单）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.viewButton = LineEditButton(FluentIcon.VIEW, self)
        self.setEchoMode(QLineEdit.Password)
        self.setContextMenuPolicy(Qt.NoContextMenu)
        self.hBoxLayout.addWidget(self.viewButton, 0, Qt.AlignRight)
        self.setClearButtonEnabled(False)
        self.viewButton.installEventFilter(self)
        self.viewButton.setIconSize(QSize(13, 13))
        self.viewButton.setFixedSize(29, 25)

    def setPasswordVisible(self, isVisible: bool):
        if isVisible:
            self.setEchoMode(QLineEdit.Normal)
        else:
            self.setEchoMode(QLineEdit.Password)

    def isPasswordVisible(self):
        return self.echoMode() == QLineEdit.Normal

    def setClearButtonEnabled(self, enable: bool):
        self._isClearButtonEnabled = enable
        if self.viewButton.isHidden():
            self.setTextMargins(0, 0, 28 * enable, 0)
        else:
            self.setTextMargins(0, 0, 28 * enable + 30, 0)

    def setViewPasswordButtonVisible(self, isVisible: bool):
        self.viewButton.setVisible(isVisible)
        # 重算右边距，否则隐藏后仍留 30px 空白
        self.setClearButtonEnabled(self._isClearButtonEnabled)

    def eventFilter(self, obj, e):
        if obj is not self.viewButton or not self.isEnabled():
            return super().eventFilter(obj, e)
        if e.type() == QEvent.MouseButtonPress:
            self.setPasswordVisible(True)
        elif e.type() == QEvent.MouseButtonRelease:
            self.setPasswordVisible(False)
        return super().eventFilter(obj, e)

    def inputMethodQuery(self, query):
        if query == Qt.InputMethodQuery.ImEnabled:
            return False
        return super().inputMethodQuery(query)


class TextEdit(QTextEdit):
    """多行文本编辑（对齐上游 TextEdit；平滑滚动由 SmoothScrollDelegate 承担）。"""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.scrollDelegate = SmoothScrollDelegate(self)
        FluentStyleSheet.LINE_EDIT.apply(self)
        updateDynamicStyle(self)
        setFont(self)

    def contextMenuEvent(self, e):
        menu = _edit_context_menu(self)
        menu.exec(e.globalPos())


class PlainTextEdit(QPlainTextEdit):
    """多行纯文本编辑（对齐上游 PlainTextEdit）。"""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.scrollDelegate = SmoothScrollDelegate(self)
        FluentStyleSheet.LINE_EDIT.apply(self)
        updateDynamicStyle(self)
        setFont(self)

    def contextMenuEvent(self, e):
        menu = _edit_context_menu(self)
        menu.exec(e.globalPos())


class ComboItem:
    """下拉项（文本/图标/用户数据/可用态）。"""

    def __init__(self, text, icon=None, userData=None, isEnabled=True):
        self.text = text
        self.icon = icon
        self.userData = userData
        self.isEnabled = isEnabled


class _ComboBoxMenu(RoundMenu):
    """下拉弹层（对齐上游 ComboBoxMenu：RoundMenu + comboListWidget 契规）。

    * view.objectName='comboListWidget'（QSS 选中态/圆角规则挂靠）；
    * itemHeight 33、视口上下留白跟随上游；
    * view 暴露 width/heightForAnimation/adjustSize 供 ComboBox 判向。
    """

    def __init__(self, parent=None):
        super().__init__("", parent)
        self.view.setObjectName("comboListWidget")
        self.view.setViewportMargins(0, 2, 0, 6)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setItemHeight(33)

    # ⚠ PySide6 specificity：子类必须自带 exec 定义（见 _menu.show_menu）
    def exec(self, pos, ani=True, aniType=MenuAnimationType.DROP_DOWN):
        RoundMenu.exec(self, pos, aniType=aniType)


class ComboBoxBase:
    """下拉框项模型基类（对齐上游 ComboBoxBase 的全部项 API）。"""

    activated = Signal(int)
    textActivated = Signal(str)

    def __init__(self, parent=None, **kwargs):
        pass

    def _setUpUi(self):
        self.isHover = False
        self.isPressed = False
        self.items = []
        self._currentIndex = -1
        self._maxVisibleItems = -1
        self.dropMenu = None
        self._placeholderText = ""
        FluentStyleSheet.COMBO_BOX.apply(self)
        self.installEventFilter(self)

    def addItem(self, text, icon=None, userData=None):
        item = ComboItem(text, icon, userData)
        self.items.append(item)
        if len(self.items) == 1:
            self.setCurrentIndex(0)

    def addItems(self, texts):
        for text in texts:
            self.addItem(text)

    def removeItem(self, index: int):
        if not 0 <= index < len(self.items):
            return
        self.items.pop(index)
        if index < self.currentIndex():
            self.setCurrentIndex(self._currentIndex - 1)
        elif index == self.currentIndex():
            if index > 0:
                self.setCurrentIndex(self._currentIndex - 1)
            else:
                self.setText(self.itemText(0))
                self.currentTextChanged.emit(self.currentText())
                self.currentIndexChanged.emit(0)
        if self.count() == 0:
            self.clear()

    def currentIndex(self):
        return self._currentIndex

    def setCurrentIndex(self, index: int):
        if not 0 <= index < len(self.items) or index == self.currentIndex():
            return
        oldText = self.currentText()
        self._currentIndex = index
        self.setText(self.items[index].text)
        if oldText != self.currentText():
            self.currentTextChanged.emit(self.currentText())
        self.currentIndexChanged.emit(index)

    def setText(self, text: str):
        super().setText(text)
        self.adjustSize()

    def currentText(self):
        if not 0 <= self.currentIndex() < len(self.items):
            return ""
        return self.items[self.currentIndex()].text

    def currentData(self):
        if not 0 <= self.currentIndex() < len(self.items):
            return None
        return self.items[self.currentIndex()].userData

    def setCurrentText(self, text):
        if text == self.currentText():
            return
        index = self.findText(text)
        if index >= 0:
            self.setCurrentIndex(index)

    def setItemText(self, index: int, text: str):
        if not 0 <= index < len(self.items):
            return
        self.items[index].text = text
        if self.currentIndex() == index:
            self.setText(text)

    def itemData(self, index: int):
        if not 0 <= index < len(self.items):
            return None
        return self.items[index].userData

    def itemText(self, index: int):
        if not 0 <= index < len(self.items):
            return ""
        return self.items[index].text

    def itemIcon(self, index: int):
        if not 0 <= index < len(self.items):
            return QIcon()
        return self.items[index].icon

    def setItemData(self, index: int, value):
        if 0 <= index < len(self.items):
            self.items[index].userData = value

    def setItemIcon(self, index: int, icon):
        if 0 <= index < len(self.items):
            self.items[index].icon = icon

    def setItemEnabled(self, index: int, isEnabled: bool):
        if 0 <= index < len(self.items):
            self.items[index].isEnabled = isEnabled

    def findData(self, data):
        for i, item in enumerate(self.items):
            if item.userData == data:
                return i
        return -1

    def findText(self, text: str):
        for i, item in enumerate(self.items):
            if item.text == text:
                return i
        return -1

    def clear(self):
        if self.currentIndex() >= 0:
            self.setText("")
        self.items.clear()
        self._currentIndex = -1

    def count(self):
        return len(self.items)

    def insertItem(self, index: int, text: str, icon=None, userData=None):
        item = ComboItem(text, icon, userData)
        self.items.insert(index, item)
        if index <= self.currentIndex():
            self.setCurrentIndex(self.currentIndex() + 1)

    def insertItems(self, index: int, texts):
        pos = index
        for text in texts:
            self.items.insert(pos, ComboItem(text))
            pos += 1
        if index <= self.currentIndex():
            self.setCurrentIndex(self.currentIndex() + pos - index)

    def setMaxVisibleItems(self, num: int):
        self._maxVisibleItems = num

    def maxVisibleItems(self):
        return self._maxVisibleItems

    def _closeComboMenu(self):
        if not self.dropMenu:
            return
        try:
            self.dropMenu.close()
        except RuntimeError:
            pass
        self.dropMenu = None

    def _onDropMenuClosed(self):
        self.dropMenu = None

    def _createComboMenu(self):
        return _ComboBoxMenu(self)

    def _showComboMenu(self):
        if not self.items:
            return

        menu = self._createComboMenu()
        for item in self.items:
            action = QAction(toQIcon(item.icon) if item.icon else QIcon(),
                             item.text)
            action.setEnabled(item.isEnabled)
            menu.addAction(action)

        # 点击项 → 下标（lstrip 去掉图标对齐用的前导空格）
        menu.view.itemClicked.connect(
            lambda i: self._onItemClicked(self.findText(i.text().lstrip())))

        if menu.view.width() < self.width():
            menu.view.setMinimumWidth(self.width())
            menu.adjustSize()

        menu.setMaxVisibleItems(self.maxVisibleItems())
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        menu.closedSignal.connect(self._onDropMenuClosed)
        self.dropMenu = menu

        # 选中项（默认动作）
        if self.currentIndex() >= 0 and self.items:
            menu.setDefaultAction(menu.actions()[self.currentIndex()])

        # 上下空间判定：下方够就下拉，否则上拉
        x = (-menu.width() // 2 + menu.layout().contentsMargins().left()
             + self.width() // 2)
        pd = self.mapToGlobal(QPoint(x, self.height()))
        hd = menu.view.heightForAnimation(pd, MenuAnimationType.DROP_DOWN)
        pu = self.mapToGlobal(QPoint(x, 0))
        hu = menu.view.heightForAnimation(pu, MenuAnimationType.PULL_UP)

        if hd >= hu:
            menu.view.adjustSize(pd, MenuAnimationType.DROP_DOWN)
            RoundMenu.exec(menu, pd, aniType=MenuAnimationType.DROP_DOWN)
        else:
            menu.view.adjustSize(pu, MenuAnimationType.PULL_UP)
            RoundMenu.exec(menu, pu, aniType=MenuAnimationType.PULL_UP)

    def _toggleComboMenu(self):
        if self.dropMenu:
            self._closeComboMenu()
        else:
            self._showComboMenu()

    def _onItemClicked(self, index):
        if not self.items[index].isEnabled:
            return
        if index != self.currentIndex():
            self.setCurrentIndex(index)
        self.activated.emit(index)
        self.textActivated.emit(self.currentText())


class ComboBox(QPushButton, ComboBoxBase):
    """按钮式下拉框（对齐上游 ComboBox：箭头回弹 + 弹层）。

    Constructors
    ------------
    * ComboBox(`parent`: QWidget = None)
    """

    currentIndexChanged = Signal(int)
    currentTextChanged = Signal(str)
    activated = Signal(int)
    textActivated = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.arrowAni = TranslateYAnimation(self)
        self._setUpUi()
        setFont(self)

    def eventFilter(self, obj, e):
        if obj is self:
            if e.type() == QEvent.MouseButtonPress:
                self.isPressed = True
            elif e.type() == QEvent.MouseButtonRelease:
                self.isPressed = False
            elif e.type() == QEvent.Enter:
                self.isHover = True
            elif e.type() == QEvent.Leave:
                self.isHover = False
        return super().eventFilter(obj, e)

    def setPlaceholderText(self, text: str):
        self._placeholderText = text
        if self.currentIndex() <= 0:
            self._updateTextState(True)
            self.setText(text)

    def setCurrentIndex(self, index: int):
        if index < 0:
            self._currentIndex = -1
            self.setPlaceholderText(self._placeholderText)
        elif 0 <= index < len(self.items):
            self._updateTextState(False)
            super().setCurrentIndex(index)

    def _updateTextState(self, isPlaceholder):
        if self.property("isPlaceholderText") == isPlaceholder:
            return
        self.setProperty("isPlaceholderText", isPlaceholder)
        repolish(self)

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        self._toggleComboMenu()

    def paintEvent(self, e):
        QPushButton.paintEvent(self, e)
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing)
        if self.isHover:
            painter.setOpacity(0.8)
        elif self.isPressed:
            painter.setOpacity(0.7)
        rect = QRectF(self.width() - 22, self.height() / 2 - 5 + self.arrowAni.y,
                      10, 10)
        if isDarkTheme():
            FluentIcon.ARROW_DOWN.render(painter, rect)
        else:
            FluentIcon.ARROW_DOWN.render(painter, rect, fill="#646464")


class EditableComboBox(LineEdit, ComboBoxBase):
    """可编辑下拉框（对齐上游 EditableComboBox：行编辑 + 下拉按钮 + 补全联动）。

    Constructors
    ------------
    * EditableComboBox(`parent`: QWidget = None)
    """

    currentIndexChanged = Signal(int)
    currentTextChanged = Signal(str)
    activated = Signal(int)
    textActivated = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self._setUpUi()

        self.dropButton = LineEditButton(FluentIcon.ARROW_DOWN, self)
        self.setTextMargins(0, 0, 29, 0)
        self.dropButton.setFixedSize(30, 25)
        self.hBoxLayout.addWidget(self.dropButton, 0, Qt.AlignRight)

        self.dropButton.clicked.connect(self._toggleComboMenu)
        self.textChanged.connect(self._onComboTextChanged)
        self.returnPressed.connect(self._onReturnPressed)

        FluentStyleSheet.LINE_EDIT.apply(self)

        self.clearButton.clicked.disconnect()
        self.clearButton.clicked.connect(self._onClearButtonClicked)

    def setCompleterMenu(self, menu):
        super().setCompleterMenu(menu)
        menu.activated.connect(self._onCompleterActivated)

    def _onCompleterActivated(self, text):
        index = self.findText(text)
        if index >= 0:
            self.setCurrentIndex(index)

    def currentText(self):
        return self.text()

    def setCurrentIndex(self, index: int):
        if index >= self.count() or index == self.currentIndex():
            return
        if index < 0:
            self._currentIndex = -1
            self.setText("")
            return
        self._currentIndex = index
        self.setText(self.items[index].text)
        self.currentIndexChanged.emit(index)

    def _onComboTextChanged(self, text):
        self._currentIndex = -1
        self.currentTextChanged.emit(text)
        for i, item in enumerate(self.items):
            if item.text == text:
                self._currentIndex = i
                self.currentIndexChanged.emit(i)
                return

    def _onReturnPressed(self):
        index = self.findText(self.text())
        if index >= 0:
            self.setCurrentIndex(index)

    def _onDropMenuClosed(self):
        self.dropMenu = None

    def _onClearButtonClicked(self):
        LineEdit.clear(self)
        self._currentIndex = -1


class SpinButton(QToolButton):
    """内联步进按钮（31×23，对齐上游 SpinButton）。"""

    def __init__(self, icon, parent=None):
        super().__init__(parent=parent)
        self.isPressed = False
        self._icon = icon
        self.setFixedSize(31, 23)
        self.setIconSize(QSize(10, 10))
        FluentStyleSheet.SPIN_BOX.apply(self)

    def mousePressEvent(self, e):
        self.isPressed = True
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        self.isPressed = False
        super().mouseReleaseEvent(e)

    def paintEvent(self, e):
        super().paintEvent(e)
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing |
                               QPainter.SmoothPixmapTransform)
        if not self.isEnabled():
            painter.setOpacity(0.36)
        elif self.isPressed:
            painter.setOpacity(0.7)
        self._icon.render(painter, QRectF(10, 6.5, 11, 11))


class CompactSpinButton(QToolButton):
    """紧凑步进按钮（26×33，上下双箭头，对齐上游 CompactSpinButton）。"""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setFixedSize(26, 33)
        self.setCursor(Qt.IBeamCursor)

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing)
        x = (self.width() - 10) / 2
        s = 9
        SPIN_UP.render(painter, QRectF(x, self.height() / 2 - s + 1, s, s))
        SPIN_DOWN.render(painter, QRectF(x, self.height() / 2, s, s))


class _SpinFlyoutView(QWidget):
    """紧凑数字框步进浮层内容（上下 36×36 按钮，对齐上游 SpinFlyoutView）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.upButton = TransparentToolButton(SPIN_UP, self)
        self.downButton = TransparentToolButton(SPIN_DOWN, self)
        self.vBoxLayout = QVBoxLayout(self)

        self.upButton.setFixedSize(36, 36)
        self.downButton.setFixedSize(36, 36)
        self.upButton.setIconSize(QSize(13, 13))
        self.downButton.setIconSize(QSize(13, 13))

        self.vBoxLayout.setContentsMargins(6, 6, 6, 6)
        self.vBoxLayout.setSpacing(0)
        self.vBoxLayout.addWidget(self.upButton)
        self.vBoxLayout.addWidget(self.downButton)

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing)
        painter.setBrush(QColor(46, 46, 46) if isDarkTheme()
                         else QColor(249, 249, 249))
        painter.setPen(QColor(0, 0, 0, 51) if isDarkTheme()
                       else QColor(0, 0, 0, 15))
        rect = self.rect().adjusted(1, 1, -1, -1)
        painter.drawRoundedRect(rect, 8, 8)


class _SpinFlyout(QWidget):
    """紧凑数字框步进浮层（B1 极简定位弹层；B2 换 Flyout 动画版）。

    Qt.Popup 语义：点外部自动关闭，与上游 Flyout 的关闭行为等价。
    """

    def __init__(self, view, parent=None):
        super().__init__(parent, Qt.Popup)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(view)

    def showAt(self, pos):
        self.move(pos)
        self.show()


class SpinBoxBase:
    """数字框 UI 基类（对齐上游 SpinBoxBase）。

    ⚠ 内部结构名（hBoxLayout/upButton/downButton/compactSpinButton）是
    qt_compat.install_spinbox_fix 补丁的挂载点，勿改名。
    """

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self._isError = False
        self.lightFocusedBorderColor = QColor()
        self.darkFocusedBorderColor = QColor()

        self.hBoxLayout = QHBoxLayout(self)

        self.setProperty("transparent", True)
        FluentStyleSheet.SPIN_BOX.apply(self)
        self.setButtonSymbols(QSpinBox.NoButtons)
        self.setFixedHeight(33)
        setFont(self)

        self.setAttribute(Qt.WA_MacShowFocusRect, False)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._showContextMenu)

    def isError(self):
        return self._isError

    def setError(self, isError: bool):
        if isError == self.isError():
            return
        self._isError = isError
        self.update()

    def setReadOnly(self, isReadOnly: bool):
        super().setReadOnly(isReadOnly)
        self.setSymbolVisible(not isReadOnly)

    def setSymbolVisible(self, isVisible: bool):
        self.setProperty("symbolVisible", isVisible)
        repolish(self)

    def setCustomFocusedBorderColor(self, light, dark):
        self.lightFocusedBorderColor = QColor(light)
        self.darkFocusedBorderColor = QColor(dark)
        self.update()

    def focusedBorderColor(self):
        if self.isError():
            return FluentSystemColor.CRITICAL_FOREGROUND.color()
        return autoFallbackThemeColor(self.lightFocusedBorderColor,
                                      self.darkFocusedBorderColor)

    def _showContextMenu(self, pos):
        menu = _edit_context_menu(self.lineEdit())
        menu.exec_(self.mapToGlobal(pos))

    def _drawBorderBottom(self):
        if not self.hasFocus():
            return
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        path = QPainterPath()
        w, h = self.width(), self.height()
        path.addRoundedRect(QRectF(0, h - 10, w, 10), 5, 5)
        rectPath = QPainterPath()
        rectPath.addRect(0, h - 10, w, 8)
        path = path.subtracted(rectPath)
        painter.fillPath(path, self.focusedBorderColor())

    def paintEvent(self, e):
        super().paintEvent(e)
        self._drawBorderBottom()


class InlineSpinBoxBase(SpinBoxBase):
    """内联数字框基类（上下双 31×23 按钮，对齐上游 InlineSpinBoxBase）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.upButton = SpinButton(SPIN_UP, self)
        self.downButton = SpinButton(SPIN_DOWN, self)

        self.hBoxLayout.setContentsMargins(0, 4, 4, 4)
        self.hBoxLayout.setSpacing(5)
        self.hBoxLayout.addWidget(self.upButton, 0, Qt.AlignRight)
        self.hBoxLayout.addWidget(self.downButton, 0, Qt.AlignRight)
        self.hBoxLayout.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.upButton.clicked.connect(self.stepUp)
        self.downButton.clicked.connect(self.stepDown)

    def setSymbolVisible(self, isVisible: bool):
        super().setSymbolVisible(isVisible)
        self.upButton.setVisible(isVisible)
        self.downButton.setVisible(isVisible)

    def setAccelerated(self, on: bool):
        super().setAccelerated(on)
        self.upButton.setAutoRepeat(on)
        self.downButton.setAutoRepeat(on)


class CompactSpinBoxBase(SpinBoxBase):
    """紧凑数字框基类（26×33 单按钮 + 浮出步进，对齐上游 CompactSpinBoxBase）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.compactSpinButton = CompactSpinButton(self)
        self.spinFlyoutView = _SpinFlyoutView(self)
        self.spinFlyout = _SpinFlyout(self.spinFlyoutView, self)

        self.hBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.hBoxLayout.addWidget(self.compactSpinButton, 0, Qt.AlignRight)
        self.hBoxLayout.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.compactSpinButton.clicked.connect(self._showFlyout)
        self.spinFlyoutView.upButton.clicked.connect(self.stepUp)
        self.spinFlyoutView.downButton.clicked.connect(self.stepDown)

        self.spinFlyout.hide()

    def setAccelerated(self, on: bool):
        super().setAccelerated(on)
        self.spinFlyoutView.upButton.setAutoRepeat(on)
        self.spinFlyoutView.downButton.setAutoRepeat(on)

    def focusInEvent(self, e):
        super().focusInEvent(e)
        self._showFlyout()

    def setSymbolVisible(self, isVisible: bool):
        super().setSymbolVisible(isVisible)
        self.compactSpinButton.setVisible(isVisible)

    def _showFlyout(self):
        if self.spinFlyout.isVisible() or self.isReadOnly():
            return
        y = int(self.compactSpinButton.height() / 2 - 46)
        pos = self.compactSpinButton.mapToGlobal(QPoint(-12, y))
        self.spinFlyout.showAt(pos)


class SpinBox(InlineSpinBoxBase, QSpinBox):
    """数字框。"""


class CompactSpinBox(CompactSpinBoxBase, QSpinBox):
    """紧凑数字框。"""


class DoubleSpinBox(InlineSpinBoxBase, QDoubleSpinBox):
    """双精度数字框。"""


class CompactDoubleSpinBox(CompactSpinBoxBase, QDoubleSpinBox):
    """紧凑双精度数字框。"""


class CheckBoxState(Enum):
    """复选状态机（对齐上游 CheckBoxState）。"""

    NORMAL = 0
    HOVER = 1
    PRESSED = 2
    CHECKED = 3
    CHECKED_HOVER = 4
    CHECKED_PRESSED = 5
    DISABLED = 6
    CHECKED_DISABLED = 7


class CheckBox(QCheckBox):
    """复选框（对齐上游 CheckBox：八态自绘指示器）。

    Constructors
    ------------
    * CheckBox(`parent`: QWidget = None)
    * CheckBox(`text`: str, `parent`: QWidget = None)
    """

    @singledispatchmethod
    def __init__(self, parent=None):
        super().__init__(parent)
        setFont(self)
        FluentStyleSheet.CHECK_BOX.apply(self)
        self.isPressed = False
        self.isHover = False
        self.lightCheckedColor = QColor()
        self.darkCheckedColor = QColor()
        self.lightTextColor = QColor(0, 0, 0)
        self.darkTextColor = QColor(255, 255, 255)

    @__init__.register
    def _(self, text: str, parent=None):
        self.__init__(parent)
        self.setText(text)

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

    def setCheckedColor(self, light, dark):
        self.lightCheckedColor = QColor(light)
        self.darkCheckedColor = QColor(dark)
        self.update()

    def setTextColor(self, light, dark):
        self.lightTextColor = QColor(light)
        self.darkTextColor = QColor(dark)
        setCustomStyleSheet(
            self,
            "CheckBox{color:%s}" % self.lightTextColor.name(QColor.HexArgb),
            "CheckBox{color:%s}" % self.darkTextColor.name(QColor.HexArgb))

    def _borderColor(self):
        if isDarkTheme():
            m = {
                CheckBoxState.NORMAL: QColor(255, 255, 255, 141),
                CheckBoxState.HOVER: QColor(255, 255, 255, 141),
                CheckBoxState.PRESSED: QColor(255, 255, 255, 40),
                CheckBoxState.CHECKED: fallbackThemeColor(self.darkCheckedColor),
                CheckBoxState.CHECKED_HOVER:
                    validColor(self.darkCheckedColor, ThemeColor.DARK_1.color()),
                CheckBoxState.CHECKED_PRESSED:
                    validColor(self.darkCheckedColor, ThemeColor.DARK_2.color()),
                CheckBoxState.DISABLED: QColor(255, 255, 255, 41),
                CheckBoxState.CHECKED_DISABLED: QColor(0, 0, 0, 0),
            }
        else:
            m = {
                CheckBoxState.NORMAL: QColor(0, 0, 0, 122),
                CheckBoxState.HOVER: QColor(0, 0, 0, 143),
                CheckBoxState.PRESSED: QColor(0, 0, 0, 69),
                CheckBoxState.CHECKED: fallbackThemeColor(self.lightCheckedColor),
                CheckBoxState.CHECKED_HOVER:
                    validColor(self.lightCheckedColor, ThemeColor.LIGHT_1.color()),
                CheckBoxState.CHECKED_PRESSED:
                    validColor(self.lightCheckedColor, ThemeColor.LIGHT_2.color()),
                CheckBoxState.DISABLED: QColor(0, 0, 0, 56),
                CheckBoxState.CHECKED_DISABLED: QColor(0, 0, 0, 0),
            }
        return m[self._state()]

    def _backgroundColor(self):
        if isDarkTheme():
            m = {
                CheckBoxState.NORMAL: QColor(0, 0, 0, 26),
                CheckBoxState.HOVER: QColor(255, 255, 255, 11),
                CheckBoxState.PRESSED: QColor(255, 255, 255, 18),
                CheckBoxState.CHECKED: fallbackThemeColor(self.darkCheckedColor),
                CheckBoxState.CHECKED_HOVER:
                    validColor(self.darkCheckedColor, ThemeColor.DARK_1.color()),
                CheckBoxState.CHECKED_PRESSED:
                    validColor(self.darkCheckedColor, ThemeColor.DARK_2.color()),
                CheckBoxState.DISABLED: QColor(0, 0, 0, 0),
                CheckBoxState.CHECKED_DISABLED: QColor(255, 255, 255, 41),
            }
        else:
            m = {
                CheckBoxState.NORMAL: QColor(0, 0, 0, 6),
                CheckBoxState.HOVER: QColor(0, 0, 0, 13),
                CheckBoxState.PRESSED: QColor(0, 0, 0, 31),
                CheckBoxState.CHECKED: fallbackThemeColor(self.lightCheckedColor),
                CheckBoxState.CHECKED_HOVER:
                    validColor(self.lightCheckedColor, ThemeColor.LIGHT_1.color()),
                CheckBoxState.CHECKED_PRESSED:
                    validColor(self.lightCheckedColor, ThemeColor.LIGHT_2.color()),
                CheckBoxState.DISABLED: QColor(0, 0, 0, 0),
                CheckBoxState.CHECKED_DISABLED: QColor(0, 0, 0, 56),
            }
        return m[self._state()]

    def _state(self):
        if not self.isEnabled():
            return (CheckBoxState.CHECKED_DISABLED if self.isChecked()
                    else CheckBoxState.DISABLED)
        if self.isChecked():
            if self.isPressed:
                return CheckBoxState.CHECKED_PRESSED
            if self.isHover:
                return CheckBoxState.CHECKED_HOVER
            return CheckBoxState.CHECKED
        if self.isPressed:
            return CheckBoxState.PRESSED
        if self.isHover:
            return CheckBoxState.HOVER
        return CheckBoxState.NORMAL

    def paintEvent(self, e):
        super().paintEvent(e)
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing)

        opt = QStyleOptionButton()
        opt.initFrom(self)
        rect = self.style().subElementRect(QStyle.SE_CheckBoxIndicator, opt, self)

        painter.setPen(self._borderColor())
        painter.setBrush(self._backgroundColor())
        painter.drawRoundedRect(rect, 4.5, 4.5)

        if not self.isEnabled():
            painter.setOpacity(0.8)

        if self.checkState() == Qt.Checked:
            CHECK_ACCEPT.render(painter, rect,
                                fill="#FFFFFF" if not isDarkTheme() else "#000000")
        elif self.checkState() == Qt.PartiallyChecked:
            CHECK_PARTIAL.render(painter, rect,
                                 fill="#FFFFFF" if not isDarkTheme() else "#000000")


class Indicator(ToolButton):
    """开关滑块指示器（42×22，对齐上游 Indicator：120ms 位移动画 + 全态自绘）。"""

    checkedChanged = Signal(bool)

    def __init__(self, parent):
        super().__init__(parent=parent)
        self.setCheckable(True)
        self.setFixedSize(42, 22)
        self.lightCheckedColor = QColor()
        self.darkCheckedColor = QColor()

        self._sliderX = 5
        self.slideAni = QPropertyAnimation(self, b"sliderX", self)
        self.slideAni.setDuration(120)

        self.toggled.connect(self._toggleSlider)

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        self.checkedChanged.emit(self.isChecked())

    def _toggleSlider(self):
        self.slideAni.setEndValue(25 if self.isChecked() else 5)
        self.slideAni.start()

    def toggle(self):
        self.setChecked(not self.isChecked())

    def setDown(self, isDown: bool):
        self.isPressed = isDown
        super().setDown(isDown)

    def setHover(self, isHover: bool):
        self.isHover = isHover
        self.update()

    def setCheckedColor(self, light, dark):
        self.lightCheckedColor = QColor(light)
        self.darkCheckedColor = QColor(dark)
        self.update()

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing)
        self._drawBackground(painter)
        self._drawCircle(painter)

    def _drawBackground(self, painter: QPainter):
        r = self.height() / 2
        painter.setPen(self._borderColor())
        painter.setBrush(self._backgroundColor())
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), r, r)

    def _drawCircle(self, painter: QPainter):
        painter.setPen(Qt.NoPen)
        painter.setBrush(self._sliderColor())
        painter.drawEllipse(int(self.sliderX), 5, 12, 12)

    def _backgroundColor(self):
        isDark = isDarkTheme()
        if self.isChecked():
            color = self.darkCheckedColor if isDark else self.lightCheckedColor
            if not self.isEnabled():
                return QColor(255, 255, 255, 41) if isDark else QColor(0, 0, 0, 56)
            if self.isPressed:
                return validColor(color, ThemeColor.LIGHT_2.color())
            if self.isHover:
                return validColor(color, ThemeColor.LIGHT_1.color())
            return fallbackThemeColor(color)
        if not self.isEnabled():
            return QColor(0, 0, 0, 0)
        if self.isPressed:
            return QColor(255, 255, 255, 18) if isDark else QColor(0, 0, 0, 23)
        if self.isHover:
            return QColor(255, 255, 255, 10) if isDark else QColor(0, 0, 0, 15)
        return QColor(0, 0, 0, 0)

    def _borderColor(self):
        isDark = isDarkTheme()
        if self.isChecked():
            return (self._backgroundColor() if self.isEnabled()
                    else QColor(0, 0, 0, 0))
        if self.isEnabled():
            return QColor(255, 255, 255, 153) if isDark else QColor(0, 0, 0, 133)
        return QColor(255, 255, 255, 41) if isDark else QColor(0, 0, 0, 56)

    def _sliderColor(self):
        isDark = isDarkTheme()
        if self.isChecked():
            if self.isEnabled():
                return QColor(Qt.black if isDark else Qt.white)
            return QColor(255, 255, 255, 77) if isDark else QColor(255, 255, 255)
        if self.isEnabled():
            return QColor(255, 255, 255, 201) if isDark else QColor(0, 0, 0, 156)
        return QColor(255, 255, 255, 96) if isDark else QColor(0, 0, 0, 91)

    def getSliderX(self):
        return self._sliderX

    def setSliderX(self, x):
        self._sliderX = max(x, 5)
        self.update()

    sliderX = Property(float, getSliderX, setSliderX)


class IndicatorPosition(Enum):
    """开关指示器位置（与上游逐名同值）。"""

    LEFT = 0
    RIGHT = 1


class SwitchButton(QWidget):
    """开关按钮（对齐上游 SwitchButton）。

    Constructors
    ------------
    * SwitchButton(`parent`: QWidget = None)
    * SwitchButton(`text`: str = "Off", `parent`: QWidget = None)
    """

    checkedChanged = Signal(bool)

    @singledispatchmethod
    def __init__(self, parent=None, indicatorPos=IndicatorPosition.LEFT):
        super().__init__(parent=parent)
        self._text = self.tr("Off")
        self._offText = self.tr("Off")
        self._onText = self.tr("On")
        self._spacing = 12
        self.lightTextColor = QColor(0, 0, 0)
        self.darkTextColor = QColor(255, 255, 255)
        self.indicatorPos = indicatorPos

        self.indicator = Indicator(self)
        self.label = QLabel(self._text, self)
        self._initWidget()

    @__init__.register
    def _(self, text: str = "Off", parent=None,
          indicatorPos=IndicatorPosition.LEFT):
        self.__init__(parent, indicatorPos)
        self._offText = text
        self.setText(text)

    def _initWidget(self):
        self.setAttribute(Qt.WA_StyledBackground)
        self.installEventFilter(self)
        self.setFixedHeight(22)

        self.hBox = QHBoxLayout(self)
        self.hBox.setSpacing(self._spacing)
        self.hBox.setContentsMargins(2, 0, 0, 0)
        if self.indicatorPos == IndicatorPosition.LEFT:
            self.hBox.addWidget(self.indicator)
            self.hBox.addWidget(self.label)
            self.hBox.setAlignment(Qt.AlignLeft)
        else:
            self.hBox.addWidget(self.label, 0, Qt.AlignRight)
            self.hBox.addWidget(self.indicator, 0, Qt.AlignRight)
            self.hBox.setAlignment(Qt.AlignRight)

        FluentStyleSheet.SWITCH_BUTTON.apply(self)
        FluentStyleSheet.SWITCH_BUTTON.apply(self.label)

        self.indicator.toggled.connect(self._updateText)
        self.indicator.toggled.connect(self.checkedChanged)

    def eventFilter(self, obj, e):
        if obj is self and self.isEnabled():
            if e.type() == QEvent.MouseButtonPress:
                self.indicator.setDown(True)
            elif e.type() == QEvent.MouseButtonRelease:
                self.indicator.setDown(False)
                self.indicator.toggle()
            elif e.type() == QEvent.Enter:
                self.indicator.setHover(True)
            elif e.type() == QEvent.Leave:
                self.indicator.setHover(False)
        return super().eventFilter(obj, e)

    def isChecked(self):
        return self.indicator.isChecked()

    def setChecked(self, isChecked):
        self._updateText()
        self.indicator.setChecked(isChecked)

    def setTextColor(self, light, dark):
        self.lightTextColor = QColor(light)
        self.darkTextColor = QColor(dark)
        self.update()

    def setCheckedIndicatorColor(self, light, dark):
        self.indicator.setCheckedColor(light, dark)

    def toggleChecked(self):
        self.indicator.toggle()

    def _updateText(self):
        self.label.setText(self.onText if self.isChecked() else self.offText)
        self.label.adjustSize()

    def getText(self):
        return self._text

    def setText(self, text):
        self._text = text
        self._offText = text
        self._onText = text
        self._updateText()

    def getSpacing(self):
        return self._spacing

    def setSpacing(self, spacing):
        self._spacing = spacing
        self.hBox.setSpacing(spacing)
        self.update()

    def getOnText(self):
        return self._onText

    def setOnText(self, text):
        self._onText = text
        self._updateText()

    def getOffText(self):
        return self._offText

    def setOffText(self, text):
        self._offText = text
        self._updateText()

    text = Property(str, getText, setText)
    spacing = Property(int, getSpacing, setSpacing)
    onText = Property(str, getOnText, setOnText)
    offText = Property(str, getOffText, setOffText)


class SliderHandle(QWidget):
    """滑杆圆点把手（22×22，100ms 半径动画，对齐上游 SliderHandle）。"""

    pressed = Signal()
    released = Signal()

    def __init__(self, parent):
        super().__init__(parent=parent)
        self.setFixedSize(22, 22)
        self._radius = 5
        self.lightHandleColor = QColor()
        self.darkHandleColor = QColor()
        self.radiusAni = QPropertyAnimation(self, b"radius", self)
        self.radiusAni.setDuration(100)

    @Property(int)
    def radius(self):
        return self._radius

    @radius.setter
    def radius(self, r):
        self._radius = r
        self.update()

    def setHandleColor(self, light, dark):
        self.lightHandleColor = QColor(light)
        self.darkHandleColor = QColor(dark)
        self.update()

    def enterEvent(self, e):
        self._startAni(6)

    def leaveEvent(self, e):
        self._startAni(5)

    def mousePressEvent(self, e):
        self._startAni(4)
        self.pressed.emit()

    def mouseReleaseEvent(self, e):
        self._startAni(6)
        self.released.emit()

    def _startAni(self, radius):
        self.radiusAni.stop()
        self.radiusAni.setStartValue(self.radius)
        self.radiusAni.setEndValue(radius)
        self.radiusAni.start()

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)

        # 外圈
        isDark = isDarkTheme()
        painter.setPen(QColor(0, 0, 0, 90 if isDark else 25))
        painter.setBrush(QColor(69, 69, 69) if isDark else QColor(255, 255, 255))
        painter.drawEllipse(self.rect().adjusted(1, 1, -1, -1))

        # 内圈（主题色）
        # ⚠ 对齐上游：半径**直接取 radius**（hover 5→6 时内圈变大、按下 4 时变小）。
        # 原写法 `c = 11 - r` 方向反了——hover/按下时内圈反而缩小，且中途
        # `setPen(Qt.NoPen)` 抹掉了上游内圈保留的描边（实测"把手样式不对"）。
        painter.setBrush(autoFallbackThemeColor(self.lightHandleColor,
                                                self.darkHandleColor))
        painter.drawEllipse(self.rect().center(), self.radius, self.radius)


class Slider(QSlider):
    """滑杆（对齐上游 Slider：自绘凹槽 + 把手 + 点击定位）。

    Constructors
    ------------
    * Slider(`parent`: QWidget = None)
    * Slider(`orient`: Qt.Orientation, `parent`: QWidget = None)
    """

    clicked = Signal(int)

    @singledispatchmethod
    def __init__(self, parent=None):
        super().__init__(parent)
        self._postInit()

    @__init__.register
    def _(self, orientation: Qt.Orientation, parent=None):
        super().__init__(orientation, parent)
        self._postInit()

    def _postInit(self):
        self.handle = SliderHandle(self)
        self._pressedPos = None
        self.lightGrooveColor = QColor()
        self.darkGrooveColor = QColor()
        self.setOrientation(self.orientation())
        self.handle.pressed.connect(self.sliderPressed)
        self.handle.released.connect(self.sliderReleased)
        self.valueChanged.connect(self._adjustHandlePos)

    def setThemeColor(self, light, dark):
        self.lightGrooveColor = QColor(light)
        self.darkGrooveColor = QColor(dark)
        self.handle.setHandleColor(light, dark)
        self.update()

    def setOrientation(self, orientation):
        super().setOrientation(orientation)
        if orientation == Qt.Horizontal:
            self.setMinimumHeight(22)
        else:
            self.setMinimumWidth(22)

    def mousePressEvent(self, e):
        # ⚠ 只响应左键（右键按下不应改值）
        if e.button() != Qt.LeftButton:
            return
        self._pressedPos = e.pos()
        self.setValue(self._posToValue(e.pos()))
        self.clicked.emit(self.value())

    def mouseMoveEvent(self, e):
        # ⚠ 只在**按住左键**时才改值。原实现无条件 setValue：一旦松手后
        # （或鼠标 grab 未按预期归还时）仍收到 move 事件，把手就会继续跟着
        # 鼠标走——用户实测"拖到某个位置停不下、一直跟着移动"。
        if not (e.buttons() & Qt.LeftButton):
            return
        self.setValue(self._posToValue(e.pos()))
        self._pressedPos = e.pos()
        self.sliderMoved.emit(self.value())

    @property
    def grooveLength(self):
        l = (self.width() if self.orientation() == Qt.Horizontal
             else self.height())
        return l - self.handle.width()

    def _adjustHandlePos(self):
        total = max(self.maximum() - self.minimum(), 1)
        delta = int((self.value() - self.minimum()) / total * self.grooveLength)
        if self.orientation() == Qt.Vertical:
            self.handle.move(0, delta)
        else:
            self.handle.move(delta, 0)

    def _posToValue(self, pos):
        pd = self.handle.width() / 2
        gs = max(self.grooveLength, 1)
        v = pos.x() if self.orientation() == Qt.Horizontal else pos.y()
        return int((v - pd) / gs * (self.maximum() - self.minimum())
                   + self.minimum())

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255, 115) if isDarkTheme()
                         else QColor(0, 0, 0, 100))
        if self.orientation() == Qt.Horizontal:
            self._drawHorizonGroove(painter)
        else:
            self._drawVerticalGroove(painter)

    def _drawHorizonGroove(self, painter: QPainter):
        w, r = self.width(), self.handle.width() / 2
        painter.drawRoundedRect(QRectF(r, r - 2, w - r * 2, 4), 2, 2)
        if self.maximum() - self.minimum() == 0:
            return
        painter.setBrush(autoFallbackThemeColor(self.lightGrooveColor,
                                                self.darkGrooveColor))
        aw = ((self.value() - self.minimum())
              / (self.maximum() - self.minimum()) * (w - r * 2))
        painter.drawRoundedRect(QRectF(r, r - 2, aw, 4), 2, 2)

    def _drawVerticalGroove(self, painter: QPainter):
        h, r = self.height(), self.handle.width() / 2
        painter.drawRoundedRect(QRectF(r - 2, r, 4, h - 2 * r), 2, 2)
        if self.maximum() - self.minimum() == 0:
            return
        painter.setBrush(autoFallbackThemeColor(self.lightGrooveColor,
                                                self.darkGrooveColor))
        ah = ((self.value() - self.minimum())
              / (self.maximum() - self.minimum()) * (h - 2 * r))
        painter.drawRoundedRect(QRectF(r - 2, r, 4, ah), 2, 2)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._adjustHandlePos()
