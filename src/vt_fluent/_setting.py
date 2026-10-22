# -*- coding: utf-8 -*-
# @version 2.5.3
"""vt_fluent 设置卡族（自研，替代 qfluentwidgets 的 settings 包）。

行为契约（对齐上游 1.11.3）：
· SettingCard：图标 + 标题 + 说明 + 右侧控件；固定高 50/70（有无说明）；
  自绘圆角底（深色白 13 / 浅色白 170，描边 0 0 0 50/19）；
· SwitchSettingCard / RangeSettingCard / PushSettingCard /
  PrimaryPushSettingCard / HyperlinkCard / ColorSettingCard /
  ComboBoxSettingCard：右侧控件 + configItem 双向绑定；
· OptionsSettingCard / CustomColorSettingCard：可展开卡（箭头旋转 200ms、
  内容区滚动展开），单选按钮组；
· ExpandSettingCard / ExpandGroupSettingCard：展开容器（QScrollArea +
  滚动值动画）；
· ExpandLayout：自适应高度布局（⚠ 私有 `_ExpandLayout__widgets` 列表是
  video_toolbox_qt.py 跨组移卡的挂钩点，勿改名）；
· SettingCardGroup：分组标题 + ExpandLayout 卡容器。
"""

from enum import Enum

from PySide6.QtCore import (QEasingCurve, QEvent, QPoint, QPropertyAnimation,
                            Property, QRect, QRectF, QSize, Qt, Signal)
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QColorDialog,
                               QFrame, QHBoxLayout, QLabel, QLayout, QPushButton,
                               QScrollArea, QSizePolicy, QToolButton, QVBoxLayout,
                               QWidget)

from ._buttons import HyperlinkButton, RadioButton, TransparentToolButton
from ._icon import FluentIcon, FluentIconBase, drawIcon
from ._inputs import (ComboBox, IndicatorPosition, Slider, SwitchButton)
from ._theme import (ColorConfigItem, FluentStyleSheet, OptionsConfigItem,
                     RangeConfigItem, isDarkTheme, qconfig, repolish, setFont)

#: 颜色选择按钮默认尺寸（对齐上游 ColorPickerButton）
COLOR_BUTTON_SIZE = QSize(96, 32)


class IconWidget(QWidget):
    """图标控件（对齐上游 IconWidget：按给定尺寸画图标）。"""

    def __init__(self, icon, parent=None):
        super().__init__(parent=parent)
        self.setFixedSize(16, 16)
        self.icon = icon

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing |
                               QPainter.SmoothPixmapTransform)
        drawIcon(self.icon, painter, self.rect())


class SettingIconWidget(IconWidget):
    """设置卡图标（16×16，对齐上游 SettingIconWidget）。"""

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing |
                               QPainter.SmoothPixmapTransform)
        drawIcon(self.icon, painter, self.rect())


class SettingCard(QFrame):
    """设置卡（对齐上游 SettingCard）。

    Constructors
    ------------
    * SettingCard(`icon`, `title`: str, `content`: str = None, `parent`=None)
    """

    def __init__(self, icon, title, content=None, parent=None):
        super().__init__(parent=parent)
        self.iconLabel = SettingIconWidget(icon, self)
        self.titleLabel = QLabel(title, self)
        self.contentLabel = QLabel(content or "", self)
        self.hBoxLayout = QHBoxLayout(self)
        self.vBoxLayout = QVBoxLayout()

        if not content:
            self.contentLabel.hide()

        self.setFixedHeight(70 if content else 50)
        self.iconLabel.setFixedSize(16, 16)

        self.hBoxLayout.setSpacing(0)
        self.hBoxLayout.setContentsMargins(16, 0, 0, 0)
        self.hBoxLayout.setAlignment(Qt.AlignVCenter)
        self.vBoxLayout.setSpacing(0)
        self.vBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.vBoxLayout.setAlignment(Qt.AlignVCenter)

        self.hBoxLayout.addWidget(self.iconLabel, 0, Qt.AlignLeft)
        self.hBoxLayout.addSpacing(16)

        self.hBoxLayout.addLayout(self.vBoxLayout)
        self.vBoxLayout.addWidget(self.titleLabel, 0, Qt.AlignLeft)
        self.vBoxLayout.addWidget(self.contentLabel, 0, Qt.AlignLeft)

        self.hBoxLayout.addSpacing(16)
        self.hBoxLayout.addStretch(1)

        self.contentLabel.setObjectName("contentLabel")
        FluentStyleSheet.SETTING_CARD.apply(self)

    def setTitle(self, title: str):
        self.titleLabel.setText(title)

    def setContent(self, content: str):
        self.contentLabel.setText(content)
        self.contentLabel.setVisible(bool(content))

    def setValue(self, value):
        pass

    def setIconSize(self, width: int, height: int):
        self.iconLabel.setFixedSize(width, height)

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing)
        if isDarkTheme():
            painter.setBrush(QColor(255, 255, 255, 13))
            painter.setPen(QColor(0, 0, 0, 50))
        else:
            painter.setBrush(QColor(255, 255, 255, 170))
            painter.setPen(QColor(0, 0, 0, 19))
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 6, 6)


class SwitchSettingCard(SettingCard):
    """开关设置卡（右侧 SwitchButton + configItem 绑定）。"""

    checkedChanged = Signal(bool)

    def __init__(self, icon, title, content=None, configItem=None, parent=None):
        super().__init__(icon, title, content, parent)
        self.configItem = configItem
        self.switchButton = SwitchButton(self.tr("Off"), self,
                                         IndicatorPosition.RIGHT)

        if configItem:
            self.setValue(qconfig.get(configItem))
            configItem.valueChanged.connect(self.setValue)

        self.hBoxLayout.addWidget(self.switchButton, 0, Qt.AlignRight)
        self.hBoxLayout.addSpacing(16)
        self.switchButton.checkedChanged.connect(self._onCheckedChanged)

    def _onCheckedChanged(self, isChecked: bool):
        self.setValue(isChecked)
        self.checkedChanged.emit(isChecked)

    def setValue(self, isChecked: bool):
        if self.configItem:
            qconfig.set(self.configItem, isChecked)
        self.switchButton.setChecked(isChecked)
        self.switchButton.setText(
            self.tr("On") if isChecked else self.tr("Off"))

    def setChecked(self, isChecked: bool):
        self.setValue(isChecked)

    def isChecked(self):
        return self.switchButton.isChecked()


class RangeSettingCard(SettingCard):
    """滑杆设置卡（右侧数值 + Slider + RangeConfigItem 绑定）。"""

    valueChanged = Signal(int)

    def __init__(self, configItem, icon, title, content=None, parent=None):
        super().__init__(icon, title, content, parent)
        self.configItem = configItem
        self.slider = Slider(Qt.Horizontal, self)
        self.valueLabel = QLabel(self)

        self.slider.setMinimumWidth(268)
        self.slider.setSingleStep(1)
        self.slider.setRange(*configItem.range)
        self.slider.setValue(configItem.value)
        self.valueLabel.setNum(configItem.value)

        self.hBoxLayout.addStretch(1)
        self.hBoxLayout.addWidget(self.valueLabel, 0, Qt.AlignRight)
        self.hBoxLayout.addSpacing(6)
        self.hBoxLayout.addWidget(self.slider, 0, Qt.AlignRight)
        self.hBoxLayout.addSpacing(16)

        self.valueLabel.setObjectName("valueLabel")
        configItem.valueChanged.connect(self.setValue)
        self.slider.valueChanged.connect(self._onValueChanged)

    def _onValueChanged(self, value: int):
        self.setValue(value)
        self.valueChanged.emit(value)

    def setValue(self, value):
        qconfig.set(self.configItem, value)
        self.valueLabel.setNum(value)
        self.valueLabel.adjustSize()
        self.slider.setValue(value)


class PushSettingCard(SettingCard):
    """按钮设置卡（右侧普通按钮）。"""

    clicked = Signal()

    def __init__(self, text, icon, title, content=None, parent=None):
        super().__init__(icon, title, content, parent)
        self.button = QPushButton(text, self)
        self.hBoxLayout.addWidget(self.button, 0, Qt.AlignRight)
        self.hBoxLayout.addSpacing(16)
        self.button.clicked.connect(self.clicked)


class PrimaryPushSettingCard(PushSettingCard):
    """主按钮设置卡。"""

    def __init__(self, text, icon, title, content=None, parent=None):
        super().__init__(text, icon, title, content, parent)
        self.button.setObjectName("primaryButton")


class HyperlinkCard(SettingCard):
    """超链接设置卡（右侧 HyperlinkButton）。"""

    def __init__(self, url, text, icon, title, content=None, parent=None):
        super().__init__(icon, title, content, parent)
        self.linkButton = HyperlinkButton(url, text, self)
        self.hBoxLayout.addWidget(self.linkButton, 0, Qt.AlignRight)
        self.hBoxLayout.addSpacing(16)


class ColorPickerButton(QToolButton):
    """颜色选择按钮（96×32 色块，点击弹系统取色框）。"""

    colorChanged = Signal(QColor)

    def __init__(self, color, title, parent=None, enableAlpha=False):
        super().__init__(parent=parent)
        self.title = title
        self.enableAlpha = enableAlpha
        self.setFixedSize(COLOR_BUTTON_SIZE)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setColor(color)
        self.setCursor(Qt.PointingHandCursor)
        self.clicked.connect(self._showColorDialog)

    def _showColorDialog(self):
        options = QColorDialog.ShowAlphaChannel if self.enableAlpha \
            else QColorDialog.ColorDialogOptions()
        color = QColorDialog.getColor(self.color, self.window(),
                                      self.tr("选择") + self.title, options)
        if color.isValid():
            self.setColor(color)
            self.colorChanged.emit(color)

    def setColor(self, color):
        self.color = QColor(color)
        self.update()

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing)
        pc = (QColor(255, 255, 255, 10) if isDarkTheme()
              else QColor(234, 234, 234))
        painter.setPen(pc)
        color = QColor(self.color)
        if not self.enableAlpha:
            color.setAlpha(255)
        painter.setBrush(color)
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 5, 5)


class ColorSettingCard(SettingCard):
    """颜色设置卡（右侧 ColorPickerButton + ColorConfigItem 绑定）。"""

    colorChanged = Signal(QColor)

    def __init__(self, configItem, icon, title, content=None, parent=None,
                 enableAlpha=False):
        super().__init__(icon, title, content, parent)
        self.configItem = configItem
        self.enableAlpha = enableAlpha
        self.colorPicker = ColorPickerButton(
            qconfig.get(configItem), title, self, enableAlpha)

        self.hBoxLayout.addWidget(self.colorPicker, 0, Qt.AlignRight)
        self.hBoxLayout.addSpacing(16)
        self.colorPicker.colorChanged.connect(self._onColorChanged)

        configItem.valueChanged.connect(self.setValue)

    def _onColorChanged(self, color):
        qconfig.set(self.configItem, color)
        self.colorChanged.emit(color)

    def setValue(self, color):
        self.colorPicker.setColor(color)


class ComboBoxSettingCard(SettingCard):
    """下拉设置卡（右侧 ComboBox + OptionsConfigItem 绑定）。"""

    def __init__(self, configItem, icon, title, content=None, texts=None,
                 parent=None):
        super().__init__(icon, title, content, parent)
        self.configItem = configItem
        self.comboBox = ComboBox(self)
        self.hBoxLayout.addWidget(self.comboBox, 0, Qt.AlignRight)
        self.hBoxLayout.addSpacing(16)

        texts = texts or []
        self.optionToText = {o: t for o, t in zip(configItem.options, texts)}
        for text, option in zip(texts, configItem.options):
            self.comboBox.addItem(text, userData=option)

        # ⚠ 当前值可能**不在选项里**，而且可能是**另一个类**的枚举成员：
        #   本项目同时存在 `engine_entities.TranslatorServiceEnum` 与
        #   `videocaptioner.core.entities.TranslatorServiceEnum` 两个同名类，
        #   跨类枚举的 `==` / hash 恒不相等（已多次踩坑，见
        #   video_toolbox_qt.py v2.3.1 的同类注释）。旧写法
        #   `self.optionToText[qconfig.get(configItem)]` 直接查字典 → 取不到就
        #   抛 `KeyError(<TranslatorServiceEnum.GOOGLE: '谷歌翻译'>)`，整张
        #   设置卡构造失败、连累整个「设置」页回退引擎 UI（用户 2026-10-18
        #   日志实证：自研 SettingInterface 构造失败，回退引擎）。现在先精确
        #   匹配、再按 `.value` 值兜底，绝不因为一个历史值炸整页。
        self.comboBox.setCurrentText(self._textFor(qconfig.get(configItem)))
        self.comboBox.currentIndexChanged.connect(self._onCurrentIndexChanged)
        configItem.valueChanged.connect(self.setValue)

    def _textFor(self, value) -> str:
        """把配置值映射成下拉文案：精确匹配 → `.value` 值匹配 → 首项兜底。"""
        if value in self.optionToText:
            return self.optionToText[value]
        raw = getattr(value, "value", value)
        for option, text in self.optionToText.items():
            if getattr(option, "value", option) == raw:
                return text
        return next(iter(self.optionToText.values()), "")

    def _onCurrentIndexChanged(self, index: int):
        qconfig.set(self.configItem, self.comboBox.itemData(index))

    def setValue(self, value):
        if value not in self.optionToText:
            # 跨类枚举 / 历史值：按 .value 落到同类选项上再写回
            raw = getattr(value, "value", value)
            hit = next((o for o in self.optionToText
                        if getattr(o, "value", o) == raw), None)
            if hit is None:
                return
            value = hit
        self.comboBox.setCurrentText(self.optionToText[value])
        qconfig.set(self.configItem, value)


class ExpandButton(QAbstractButton):
    """展开按钮（箭头 180° 旋转 200ms，对齐上游 ExpandButton）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(30, 30)
        self._angle = 0
        self.isHover = False
        self.isPressed = False
        self.rotateAni = QPropertyAnimation(self, b"angle", self)
        self.clicked.connect(self._onClicked)

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing |
                               QPainter.SmoothPixmapTransform)
        painter.setPen(Qt.NoPen)

        r = 255 if isDarkTheme() else 0
        color = Qt.transparent
        if self.isEnabled():
            if self.isPressed:
                color = QColor(r, r, r, 10)
            elif self.isHover:
                color = QColor(r, r, r, 14)
        else:
            painter.setOpacity(0.36)
        painter.setBrush(color)
        painter.drawRoundedRect(self.rect(), 4, 4)

        painter.translate(self.width() // 2, self.height() // 2)
        painter.rotate(self._angle)
        FluentIcon.ARROW_DOWN.render(painter, QRectF(-5, -5, 9.6, 9.6))

    def enterEvent(self, e):
        self.setHover(True)

    def leaveEvent(self, e):
        self.setHover(False)

    def mousePressEvent(self, e):
        super().mousePressEvent(e)
        self.setPressed(True)

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        self.setPressed(False)

    def setHover(self, isHover: bool):
        self.isHover = isHover
        self.update()

    def setPressed(self, isPressed: bool):
        self.isPressed = isPressed
        self.update()

    def _onClicked(self):
        self.setExpand(self.angle < 180)

    def setExpand(self, isExpand: bool):
        self.rotateAni.stop()
        self.rotateAni.setEndValue(180 if isExpand else 0)
        self.rotateAni.setDuration(200)
        self.rotateAni.start()

    def getAngle(self):
        return self._angle

    def setAngle(self, angle):
        self._angle = angle
        self.update()

    angle = Property(float, getAngle, setAngle)


class SpaceWidget(QWidget):
    """展开占位（对齐上游 SpaceWidget）。"""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedHeight(1)


class HeaderSettingCard(SettingCard):
    """带展开按钮的设置卡头（对齐上游 HeaderSettingCard）。"""

    def __init__(self, icon, title, content=None, parent=None):
        super().__init__(icon, title, content, parent)
        self.expandButton = ExpandButton(self)
        self.hBoxLayout.addWidget(self.expandButton, 0, Qt.AlignRight)
        self.hBoxLayout.addSpacing(8)
        self.titleLabel.setObjectName("titleLabel")
        self.installEventFilter(self)

    def eventFilter(self, obj, e):
        if obj is self:
            if e.type() == QEvent.Enter:
                self.expandButton.setHover(True)
            elif e.type() == QEvent.Leave:
                self.expandButton.setHover(False)
            elif e.type() == QEvent.MouseButtonPress and e.button() == Qt.LeftButton:
                self.expandButton.setPressed(True)
            elif e.type() == QEvent.MouseButtonRelease and e.button() == Qt.LeftButton:
                self.expandButton.setPressed(False)
                self.expandButton.click()
        return super().eventFilter(obj, e)

    def addWidget(self, widget: QWidget):
        n = self.hBoxLayout.count()
        self.hBoxLayout.removeItem(self.hBoxLayout.itemAt(n - 1))
        self.hBoxLayout.addWidget(widget, 0, Qt.AlignRight)
        self.hBoxLayout.addSpacing(19)
        self.hBoxLayout.addWidget(self.expandButton, 0, Qt.AlignRight)
        self.hBoxLayout.addSpacing(8)

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255, 13) if isDarkTheme()
                         else QColor(255, 255, 255, 170))

        p = self.parent()
        path = QPainterPath()
        path.setFillRule(Qt.WindingFill)
        path.addRoundedRect(QRectF(self.rect().adjusted(1, 1, -1, -1)), 6, 6)
        if hasattr(p, "isExpand") and p.isExpand:
            path.addRect(QRectF(1, self.height() - 8, self.width() - 2, 8))
        painter.drawPath(path.simplified())


class ExpandBorderWidget(QWidget):
    """展开卡描边层（对齐上游 ExpandBorderWidget）。"""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        parent.installEventFilter(self)

    def eventFilter(self, obj, e):
        if obj is self.parent() and e.type() == QEvent.Resize:
            self.resize(e.size())
        return super().eventFilter(obj, e)

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QColor(0, 0, 0, 50) if isDarkTheme()
                       else QColor(0, 0, 0, 19))
        p = self.parent()
        ch, h, w = p.card.height(), self.height(), self.width()
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 6, 6)
        if ch < h:
            painter.drawLine(1, ch, w - 1, ch)


class ExpandSettingCard(QScrollArea):
    """可展开设置卡（对齐上游 ExpandSettingCard：滚动值动画展开）。"""

    def __init__(self, icon, title, content=None, parent=None):
        super().__init__(parent=parent)
        self.isExpand = False
        self.scrollWidget = QFrame(self)
        self.view = QFrame(self.scrollWidget)
        self.card = HeaderSettingCard(icon, title, content, self)
        self.scrollLayout = QVBoxLayout(self.scrollWidget)
        self.viewLayout = QVBoxLayout(self.view)
        self.spaceWidget = SpaceWidget(self.scrollWidget)
        self.borderWidget = ExpandBorderWidget(self)

        self.expandAni = QPropertyAnimation(self.verticalScrollBar(),
                                            b"value", self)
        self._initExpandWidget()

    def _initExpandWidget(self):
        self.setWidget(self.scrollWidget)
        self.setWidgetResizable(True)
        self.setFixedHeight(self.card.height())
        self.setViewportMargins(0, self.card.height(), 0, 0)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.scrollLayout.setContentsMargins(0, 0, 0, 0)
        self.scrollLayout.setSpacing(0)
        self.scrollLayout.addWidget(self.view)
        self.scrollLayout.addWidget(self.spaceWidget)

        self.expandAni.setEasingCurve(QEasingCurve.OutQuad)
        self.expandAni.setDuration(200)

        self.view.setObjectName("view")
        self.scrollWidget.setObjectName("scrollWidget")
        self.setProperty("isExpand", False)
        FluentStyleSheet.EXPAND_SETTING_CARD.apply(self.card)
        FluentStyleSheet.EXPAND_SETTING_CARD.apply(self)

        self.card.installEventFilter(self)
        self.expandAni.valueChanged.connect(self._onExpandValueChanged)
        self.card.expandButton.clicked.connect(self.toggleExpand)

    def addWidget(self, widget: QWidget):
        self.card.addWidget(widget)
        self._adjustViewSize()

    def wheelEvent(self, e):
        e.ignore()

    def setExpand(self, isExpand: bool):
        if self.isExpand == isExpand:
            return
        self._adjustViewSize()

        self.isExpand = isExpand
        self.setProperty("isExpand", isExpand)
        repolish(self)

        if isExpand:
            h = self.viewLayout.sizeHint().height()
            self.verticalScrollBar().setValue(h)
            self.expandAni.setStartValue(h)
            self.expandAni.setEndValue(0)
        else:
            self.expandAni.setStartValue(0)
            self.expandAni.setEndValue(self.verticalScrollBar().maximum())
        self.expandAni.start()
        self.card.expandButton.setExpand(isExpand)

    def toggleExpand(self):
        self.setExpand(not self.isExpand)

    def resizeEvent(self, e):
        self.card.resize(self.width(), self.card.height())
        self.scrollWidget.resize(self.width(), self.scrollWidget.height())

    def _onExpandValueChanged(self):
        vh = self.viewLayout.sizeHint().height()
        h = self.viewportMargins().top()
        self.setFixedHeight(max(h + vh - self.verticalScrollBar().value(), h))

    def _adjustViewSize(self):
        h = self.viewLayout.sizeHint().height()
        self.spaceWidget.setFixedHeight(h)
        if self.isExpand:
            self.setFixedHeight(self.card.height() + h)

    def setValue(self, value):
        pass


class GroupSeparator(QWidget):
    """分组分隔线（对齐上游 GroupSeparator）。"""

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.setFixedHeight(3)

    def paintEvent(self, e):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing)
        painter.setPen(QColor(0, 0, 0, 36) if isDarkTheme()
                       else QColor(0, 0, 0, 15))
        painter.drawLine(0, 1, self.width(), 1)


class ExpandGroupSettingCard(ExpandSettingCard):
    """分组展开卡（对齐上游 ExpandGroupSettingCard）。"""

    def __init__(self, icon, title, content=None, parent=None):
        super().__init__(icon, title, content, parent)
        self.widgets = []
        self.viewLayout.setContentsMargins(0, 0, 0, 0)
        self.viewLayout.setSpacing(0)

    def addGroupWidget(self, widget: QWidget):
        if self.viewLayout.count() >= 1:
            self.viewLayout.addWidget(GroupSeparator(self.view))
        widget.setParent(self.view)
        self.widgets.append(widget)
        self.viewLayout.addWidget(widget)
        self._adjustViewSize()

    def removeGroupWidget(self, widget: QWidget):
        if widget not in self.widgets:
            return
        self.viewLayout.removeWidget(widget)
        self.widgets.remove(widget)
        widget.deleteLater()
        self._adjustViewSize()


class OptionsSettingCard(ExpandSettingCard):
    """选项设置卡（展开后单选组，对齐上游 OptionsSettingCard）。"""

    optionChanged = Signal(object)

    def __init__(self, configItem, icon, title, content=None, texts=None,
                 parent=None):
        super().__init__(icon, title, content, parent)
        self.texts = texts or []
        self.configItem = configItem
        self.configName = configItem.name
        self.choiceLabel = QLabel(self)
        self.buttonGroup = QButtonGroup(self)

        self.choiceLabel.setObjectName("titleLabel")
        self.addWidget(self.choiceLabel)

        self.viewLayout.setSpacing(19)
        self.viewLayout.setContentsMargins(48, 18, 0, 18)

        for text, option in zip(self.texts, configItem.options):
            button = RadioButton(text, self.view)
            self.buttonGroup.addButton(button)
            self.viewLayout.addWidget(button)
            button.setProperty(self.configName, option)

        self._adjustViewSize()
        self.setValue(qconfig.get(self.configItem))
        configItem.valueChanged.connect(self.setValue)
        self.buttonGroup.buttonClicked.connect(self._onButtonClicked)

    def _onButtonClicked(self, button):
        if button.text() == self.choiceLabel.text():
            return
        value = button.property(self.configName)
        qconfig.set(self.configItem, value)
        self.choiceLabel.setText(button.text())
        self.optionChanged.emit(self.configItem)

    def setValue(self, value):
        for button in self.buttonGroup.buttons():
            if not isinstance(button, RadioButton):
                continue
            if button.property(self.configName) == value:
                self.choiceLabel.setText(button.text())
                button.setChecked(True)
                break


class CustomColorSettingCard(ExpandGroupSettingCard):
    """自定义颜色卡（默认色/自定义色单选 + 取色，对齐上游同名卡）。"""

    colorChanged = Signal(QColor)

    def __init__(self, configItem, icon, title, content=None, parent=None,
                 enableAlpha=False):
        super().__init__(icon, title, content, parent)
        self.enableAlpha = enableAlpha
        self.configItem = configItem
        self.defaultColor = QColor(configItem.defaultValue)
        self.customColor = QColor(qconfig.get(configItem))

        self.choiceLabel = QLabel(self)
        self.radioWidget = QWidget(self.view)
        self.radioLayout = QVBoxLayout(self.radioWidget)
        self.defaultRadioButton = RadioButton(self.tr("默认颜色"),
                                              self.radioWidget)
        self.customRadioButton = RadioButton(self.tr("自定义颜色"),
                                             self.radioWidget)
        self.buttonGroup = QButtonGroup(self)

        self.customColorWidget = QWidget(self.view)
        self.customColorLayout = QHBoxLayout(self.customColorWidget)
        self.customLabel = QLabel(self.tr("自定义颜色"), self.customColorWidget)
        self.colorPicker = ColorPickerButton(self.customColor, title,
                                             self.customColorWidget,
                                             enableAlpha)

        self._initColorWidget()

    def _initColorWidget(self):
        self.choiceLabel.setObjectName("titleLabel")
        self.addWidget(self.choiceLabel)

        self.radioLayout.setSpacing(19)
        self.radioLayout.setContentsMargins(48, 18, 0, 18)
        self.radioLayout.addWidget(self.defaultRadioButton)
        self.radioLayout.addWidget(self.customRadioButton)
        self.radioLayout.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.buttonGroup.addButton(self.defaultRadioButton)
        self.buttonGroup.addButton(self.customRadioButton)

        self.customColorLayout.setContentsMargins(48, 18, 44, 18)
        self.customColorLayout.addWidget(self.customLabel, 0, Qt.AlignLeft)
        self.customColorLayout.addSpacing(16)
        self.customColorLayout.addWidget(self.colorPicker, 0, Qt.AlignRight)
        self.customColorLayout.setAlignment(Qt.AlignVCenter)

        self.viewLayout.setSpacing(0)
        self.viewLayout.setContentsMargins(0, 0, 0, 0)
        self.viewLayout.addWidget(self.radioWidget)
        self.viewLayout.addWidget(self.customColorWidget)

        self._adjustViewSize()

        self.defaultRadioButton.clicked.connect(
            lambda: self.setValue(self.defaultColor))
        self.customRadioButton.clicked.connect(
            lambda: self.setValue(self.customColor))
        self.colorPicker.colorChanged.connect(self._onColorChanged)

        self.setValue(qconfig.get(self.configItem))
        self.configItem.valueChanged.connect(self.setValue)

    def _onColorChanged(self, color):
        self.customColor = QColor(color)
        self.customRadioButton.setChecked(True)
        qconfig.set(self.configItem, color)
        self.colorChanged.emit(color)

    def setValue(self, color):
        color = QColor(color)
        qconfig.set(self.configItem, color)
        self.colorPicker.setColor(color)

        isDefault = color.name() == self.defaultColor.name()
        self.defaultRadioButton.setChecked(isDefault)
        self.customRadioButton.setChecked(not isDefault)
        self.customColorWidget.setVisible(not isDefault)
        # 行显示/隐藏改变 sizeHint，展开态需同步高度
        self._adjustViewSize()


class ExpandLayout(QLayout):
    """自适应高度布局（对齐上游 ExpandLayout）。

    ⚠ 私有列表 `_ExpandLayout__widgets` 是 video_toolbox_qt.py 跨组移卡的
    挂钩点（getattr(dst_lay, "_ExpandLayout__widgets")），勿改名。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.__items = []
        self.__widgets = []

    def addWidget(self, widget: QWidget):
        if widget in self.__widgets:
            return
        self.__widgets.append(widget)
        widget.installEventFilter(self)

    def addItem(self, item):
        self.__items.append(item)

    def count(self):
        return len(self.__items)

    def itemAt(self, index):
        if 0 <= index < len(self.__items):
            return self.__items[index]
        return None

    def takeAt(self, index):
        if 0 <= index < len(self.__items):
            self.__widgets.pop(index)
            return self.__items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Vertical

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._doLayout(QRect(0, 0, width, 0), False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._doLayout(rect, True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for w in self.__widgets:
            size = size.expandedTo(w.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def _doLayout(self, rect, move):
        margin = self.contentsMargins()
        x = rect.x() + margin.left()
        y = rect.y() + margin.top()
        width = rect.width() - margin.left() - margin.right()
        for i, w in enumerate(self.__widgets):
            if w.isHidden():
                continue
            y += (i > 0) * self.spacing()
            if move:
                w.setGeometry(QRect(QPoint(x, y), QSize(width, w.height())))
            y += w.height()
        return y - rect.y()

    def eventFilter(self, obj, e):
        if obj in self.__widgets:
            if e.type() == QEvent.Resize:
                ds = e.size() - e.oldSize()
                if ds.height() != 0 and ds.width() == 0:
                    w = self.parentWidget()
                    w.resize(w.width(), w.height() + ds.height())
        return super().eventFilter(obj, e)


class SettingCardGroup(QWidget):
    """设置卡分组（标题 + ExpandLayout，对齐上游 SettingCardGroup）。"""

    def __init__(self, title: str, parent=None):
        super().__init__(parent=parent)
        self.titleLabel = QLabel(title, self)
        self.vBoxLayout = QVBoxLayout(self)
        self.cardLayout = ExpandLayout()

        self.vBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.vBoxLayout.setAlignment(Qt.AlignTop)
        self.vBoxLayout.setSpacing(0)
        self.cardLayout.setContentsMargins(0, 0, 0, 0)
        self.cardLayout.setSpacing(2)

        self.vBoxLayout.addWidget(self.titleLabel)
        self.vBoxLayout.addSpacing(12)
        self.vBoxLayout.addLayout(self.cardLayout, 1)

        FluentStyleSheet.SETTING_CARD_GROUP.apply(self)
        setFont(self.titleLabel, 20)
        self.titleLabel.adjustSize()

    def addSettingCard(self, card: QWidget):
        card.setParent(self)
        self.cardLayout.addWidget(card)
        self.adjustSize()

    def addSettingCards(self, cards):
        for card in cards:
            self.addSettingCard(card)

    def adjustSize(self):
        h = self.cardLayout.heightForWidth(self.width()) + 46
        self.resize(self.width(), h)
