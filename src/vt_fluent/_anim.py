# -*- coding: utf-8 -*-
# @version 2.4.0
"""vt_fluent 动画辅助（自研，替代 qfluentwidgets.common.animation + smooth_scroll）。

服务 B1 控件族：卡片背景色过渡（BackgroundAnimationWidget）、凸起阴影
（DropShadowAnimation）、分段指示器 squash-stretch（ScaleSlideAnimation）、
下拉箭头回弹（TranslateYAnimation）、平滑滚动（SmoothScroll 系）。

动效时长/缓动逐值对齐上游（120ms 背景、100ms 把手、150ms 阴影、
200+400ms 指示器两段、500ms 平滑滚动 OutCubic）。
"""

from PySide6.QtCore import (QEasingCurve, QEvent, QObject, QParallelAnimationGroup,
                            QPoint, QPointF, Property, QPropertyAnimation, QRectF,
                            QSequentialAnimationGroup, Qt, Signal)
from PySide6.QtGui import QColor, QEnterEvent, QMouseEvent
from PySide6.QtWidgets import (QAbstractItemView, QAbstractScrollArea, QGraphicsDropShadowEffect,
                               QLineEdit, QListView, QScrollBar, QWidget)


def createBezierCurve(x1, y1, x2, y2):
    """造三次贝塞尔缓动（上游 FluentAnimation.createBezierCurve 等价物）。"""
    curve = QEasingCurve(QEasingCurve.BezierSpline)
    curve.addCubicBezierSegment(QPointF(x1, y1), QPointF(x2, y2), QPointF(1, 1))
    return curve


class singledispatchmethod:
    """单派发方法描述符（对齐上游 overload.py）。

    与 functools 版的差异：**纯关键字调用也能派发**——无位置参数时扫
    kwargs 值里的注册类型。控件构造重载（self.__init__(parent=parent)
    这种内部回跳）全靠这个语义，functools 版会 IndexError。
    """

    def __init__(self, func):
        from functools import singledispatch, update_wrapper
        self.dispatcher = singledispatch(func)
        self.func = func
        self._uw = update_wrapper

    def register(self, cls, method=None):
        return self.dispatcher.register(cls, func=method)

    def __get__(self, obj, cls=None):
        def _method(*args, **kwargs):
            if args:
                method = self.dispatcher.dispatch(args[0].__class__)
            else:
                method = self.func
                for v in kwargs.values():
                    if v.__class__ in self.dispatcher.registry:
                        method = self.dispatcher.dispatch(v.__class__)
                        if method is not self.func:
                            break
            return method.__get__(obj, cls)(*args, **kwargs)
        self._uw(_method, self.func)
        _method.register = self.register
        return _method


class AnimationBase(QObject):
    """动画基类：给父控件装事件过滤器，转发 hover/press/release。"""

    def __init__(self, parent: QWidget):
        super().__init__(parent=parent)
        parent.installEventFilter(self)

    def _onHover(self, e):
        pass

    def _onLeave(self, e):
        pass

    def _onPress(self, e):
        pass

    def _onRelease(self, e):
        pass

    def eventFilter(self, obj, e):
        if obj is self.parent():
            if e.type() == QEvent.MouseButtonPress:
                self._onPress(e)
            elif e.type() == QEvent.MouseButtonRelease:
                self._onRelease(e)
            elif e.type() == QEvent.Enter:
                self._onHover(e)
            elif e.type() == QEvent.Leave:
                self._onLeave(e)
        return super().eventFilter(obj, e)


class TranslateYAnimation(AnimationBase):
    """下拉箭头回弹（按下下沉 2px，松开 OutElastic 回位）。"""

    valueChanged = Signal(float)

    def __init__(self, parent: QWidget, offset=2):
        super().__init__(parent)
        self._y = 0
        self.maxOffset = offset
        self.ani = QPropertyAnimation(self, b"y", self)

    def getY(self):
        return self._y

    def setY(self, y):
        self._y = y
        self.parent().update()
        self.valueChanged.emit(y)

    def _onPress(self, e):
        self.ani.setEndValue(self.maxOffset)
        self.ani.setEasingCurve(QEasingCurve.OutQuad)
        self.ani.setDuration(150)
        self.ani.start()

    def _onRelease(self, e):
        self.ani.setEndValue(0)
        self.ani.setDuration(500)
        self.ani.setEasingCurve(QEasingCurve.OutElastic)
        self.ani.start()

    y = Property(float, getY, setY)


# ---------------------------------------------------------------------- #
# 卡片背景色动画
# ---------------------------------------------------------------------- #
class BackgroundColorObject(QObject):
    """被 QPropertyAnimation 动画的颜色持有者。"""

    def __init__(self, parent):
        super().__init__(parent)
        self._backgroundColor = parent._normalBackgroundColor()

    def getBackgroundColor(self):
        return self._backgroundColor

    def setBackgroundColor(self, color):
        self._backgroundColor = color

    backgroundColor = Property(QColor, getBackgroundColor, setBackgroundColor)


class BackgroundAnimationWidget:
    """背景色动画混入：hover/pressed/focus/disabled 切换 120ms 过渡。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.isHover = False
        self.isPressed = False
        self.bgColorObject = BackgroundColorObject(self)
        self.backgroundColorAni = QPropertyAnimation(
            self.bgColorObject, b"backgroundColor", self)
        self.backgroundColorAni.setDuration(120)
        self.installEventFilter(self)

    def eventFilter(self, obj, e):
        if obj is self:
            if e.type() == QEvent.EnabledChange:
                if self.isEnabled():
                    self.setBackgroundColor(self._normalBackgroundColor())
                else:
                    self.setBackgroundColor(self._disabledBackgroundColor())
        return super().eventFilter(obj, e)

    def mousePressEvent(self, e):
        self.isPressed = True
        self._updateBackgroundColor()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        self.isPressed = False
        self._updateBackgroundColor()
        super().mouseReleaseEvent(e)

    def enterEvent(self, e):
        self.isHover = True
        self._updateBackgroundColor()

    def leaveEvent(self, e):
        self.isHover = False
        self._updateBackgroundColor()

    def focusInEvent(self, e):
        super().focusInEvent(e)
        self._updateBackgroundColor()

    def _normalBackgroundColor(self):
        from PySide6.QtGui import QColor
        return QColor(0, 0, 0, 0)

    def _hoverBackgroundColor(self):
        return self._normalBackgroundColor()

    def _pressedBackgroundColor(self):
        return self._normalBackgroundColor()

    def _focusInBackgroundColor(self):
        return self._normalBackgroundColor()

    def _disabledBackgroundColor(self):
        return self._normalBackgroundColor()

    def _updateBackgroundColor(self):
        from PySide6.QtWidgets import QLineEdit
        if not self.isEnabled():
            color = self._disabledBackgroundColor()
        elif isinstance(self, QLineEdit) and self.hasFocus():
            color = self._focusInBackgroundColor()
        elif self.isPressed:
            color = self._pressedBackgroundColor()
        elif self.isHover:
            color = self._hoverBackgroundColor()
        else:
            color = self._normalBackgroundColor()
        self.backgroundColorAni.stop()
        self.backgroundColorAni.setEndValue(color)
        self.backgroundColorAni.start()

    def getBackgroundColor(self):
        return self.bgColorObject.backgroundColor

    def setBackgroundColor(self, color):
        self.bgColorObject.backgroundColor = color

    @property
    def backgroundColor(self):
        return self.getBackgroundColor()


# ---------------------------------------------------------------------- #
# 凸起阴影
# ---------------------------------------------------------------------- #
class DropShadowAnimation(QPropertyAnimation):
    """hover 时挂阴影并渐显（150ms），离开渐隐后卸下。"""

    def __init__(self, parent: QWidget, normalColor=None, hoverColor=None):
        from PySide6.QtGui import QColor
        super().__init__(parent=parent)
        self.normalColor = normalColor or QColor(0, 0, 0, 0)
        self.hoverColor = hoverColor or QColor(0, 0, 0, 75)
        self.offset = QPoint(0, 0)
        self.blurRadius = 38
        self.shadowEffect = QGraphicsDropShadowEffect(self)
        self.shadowEffect.setColor(self.normalColor)
        parent.installEventFilter(self)

    def setBlurRadius(self, radius):
        self.blurRadius = radius

    def setOffset(self, dx, dy):
        self.offset = QPoint(dx, dy)

    def _createShadowEffect(self):
        self.shadowEffect = QGraphicsDropShadowEffect(self)
        self.shadowEffect.setOffset(self.offset)
        self.shadowEffect.setBlurRadius(self.blurRadius)
        self.shadowEffect.setColor(self.normalColor)
        self.setTargetObject(self.shadowEffect)
        self.setStartValue(self.shadowEffect.color())
        self.setPropertyName(b"color")
        self.setDuration(150)
        return self.shadowEffect

    def eventFilter(self, obj, e):
        if obj is self.parent() and self.parent().isEnabled():
            if e.type() == QEvent.Enter:
                if self.state() != QPropertyAnimation.Running:
                    self.parent().setGraphicsEffect(self._createShadowEffect())
                self.setEndValue(self.hoverColor)
                self.start()
            elif e.type() in (QEvent.Leave, QEvent.MouseButtonPress):
                if self.parent().graphicsEffect():
                    self.finished.connect(self._onAniFinished)
                    self.setEndValue(self.normalColor)
                    self.start()
        return super().eventFilter(obj, e)

    def _onAniFinished(self):
        self.finished.disconnect()
        self.shadowEffect = None
        self.parent().setGraphicsEffect(None)


# ---------------------------------------------------------------------- #
# 分段指示器（WinUI3 squash & stretch：先拉长覆盖、再滑动收敛）
# ---------------------------------------------------------------------- #
class ScaleSlideAnimation(QObject):
    """指示器两段式滑动动画（pos/length 双属性，QRectF 几何驱动）。"""

    valueChanged = Signal(QRectF)
    finished = Signal()

    def __init__(self, parent=None, orient=Qt.Orientation.Horizontal):
        super().__init__(parent)
        self.orient = orient
        self._geometry = QRectF(0, 0, 16, 3) if self.isHorizontal() else QRectF(0, 0, 3, 16)

        self.slideAniGroup = QParallelAnimationGroup(self)
        self.crossAniGroup = QParallelAnimationGroup(self)
        self.currentAni = self.slideAniGroup

        self.slidePosAni1 = QPropertyAnimation(self, b"pos", self)
        self.slidePosAni2 = QPropertyAnimation(self, b"pos", self)
        self.slideLengthAni1 = QPropertyAnimation(self, b"length", self)
        self.slideLengthAni2 = QPropertyAnimation(self, b"length", self)
        self.seqSlidePosAniGroup = QSequentialAnimationGroup(self)
        self.seqLengthAniGroup = QSequentialAnimationGroup(self)

        self.crossLenAni = QPropertyAnimation(self, b"length", self)
        self.crossPosAni = QPropertyAnimation(self, b"pos", self)

        self.seqSlidePosAniGroup.addAnimation(self.slidePosAni1)
        self.seqSlidePosAniGroup.addAnimation(self.slidePosAni2)
        self.seqLengthAniGroup.addAnimation(self.slideLengthAni1)
        self.seqLengthAniGroup.addAnimation(self.slideLengthAni2)
        self.slideAniGroup.addAnimation(self.seqSlidePosAniGroup)
        self.slideAniGroup.addAnimation(self.seqLengthAniGroup)

        self.crossAniGroup.addAnimation(self.crossLenAni)
        self.crossAniGroup.addAnimation(self.crossPosAni)

        self.slideAniGroup.finished.connect(self.finished)
        self.crossAniGroup.finished.connect(self.finished)

    def startAnimation(self, endRect: QRectF, useCrossFade=False):
        self.stopAnimation()
        startRect = QRectF(self.geometry)
        if self.isHorizontal():
            sameLevel = abs(startRect.y() - endRect.y()) < 1
            dim = startRect.width()
            start = startRect.x()
            end = endRect.x()
        else:
            sameLevel = abs(startRect.x() - endRect.x()) < 1
            dim = startRect.height()
            start = startRect.y()
            end = endRect.y()

        if sameLevel and not useCrossFade:
            self._startSlideAnimation(startRect, endRect, start, end, dim)
        else:
            self._startCrossFadeAnimation(startRect, endRect)

    def stopAnimation(self):
        self.slideAniGroup.stop()
        self.crossAniGroup.stop()

    def _startSlideAnimation(self, startRect, endRect, from_, to, dimension):
        """0→33%：拉长覆盖两段间距；33%→100%：滑动收敛到目标。"""
        self.currentAni = self.slideAniGroup
        for a in (self.slidePosAni1, self.slideLengthAni1):
            a.setDuration(200)
            a.setEasingCurve(createBezierCurve(0.9, 0.1, 1, 0.2))
        for a in (self.slidePosAni2, self.slideLengthAni2):
            a.setDuration(400)
            a.setEasingCurve(createBezierCurve(0.1, 0.9, 0.2, 1.0))

        dist = abs(to - from_)
        midLength = dist + dimension
        isForward = to > from_

        startPos = startRect.topLeft()
        endPos = endRect.topLeft()

        if isForward:
            self.slidePosAni1.setStartValue(startPos)
            self.slidePosAni1.setEndValue(startPos)
            self.slideLengthAni1.setStartValue(dimension)
            self.slideLengthAni1.setEndValue(midLength)
            self.slidePosAni2.setStartValue(startPos)
            self.slidePosAni2.setEndValue(endPos)
            self.slideLengthAni2.setStartValue(midLength)
            self.slideLengthAni2.setEndValue(dimension)
        else:
            self.slidePosAni1.setStartValue(startPos)
            self.slidePosAni1.setEndValue(endPos)
            self.slideLengthAni1.setStartValue(dimension)
            self.slideLengthAni1.setEndValue(midLength)
            self.slidePosAni2.setStartValue(endPos)
            self.slidePosAni2.setEndValue(endPos)
            self.slideLengthAni2.setStartValue(midLength)
            self.slideLengthAni2.setEndValue(dimension)

        self.slideAniGroup.start()

    def _startCrossFadeAnimation(self, startRect, endRect):
        self.currentAni = self.crossAniGroup
        self.setGeometry(endRect)
        isNextBelow = (endRect.y() > startRect.y() if not self.isHorizontal()
                       else endRect.x() > startRect.x())
        if self.isHorizontal():
            dim = endRect.width()
            startGeo = QRectF(
                endRect.x() + (0 if isNextBelow else dim), endRect.y(),
                0, endRect.height())
        else:
            dim = endRect.height()
            startGeo = QRectF(endRect.x(),
                              endRect.y() + (0 if isNextBelow else dim),
                              endRect.width(), 0)
        self.setGeometry(startGeo)
        self.crossLenAni.setDuration(600)
        self.crossLenAni.setStartValue(0)
        self.crossLenAni.setEndValue(dim)
        self.crossLenAni.setEasingCurve(QEasingCurve.OutQuint)
        self.crossPosAni.setDuration(600)
        self.crossPosAni.setStartValue(startGeo.topLeft())
        self.crossPosAni.setEndValue(endRect.topLeft())
        self.crossPosAni.setEasingCurve(QEasingCurve.OutQuint)
        self.crossAniGroup.start()

    def stop(self):
        self.stopAnimation()

    def state(self):
        return self.currentAni.state()

    def isHorizontal(self):
        return self.orient == Qt.Orientation.Horizontal

    def getPos(self):
        return QPointF(self.geometry.topLeft())

    def setPos(self, pos):
        self._geometry.moveTopLeft(pos)
        self.valueChanged.emit(self.geometry)

    def getLength(self):
        return self.geometry.width() if self.isHorizontal() else self.geometry.height()

    def setLength(self, length):
        if self.isHorizontal():
            self._geometry.setWidth(length)
        else:
            self._geometry.setHeight(length)
        self.valueChanged.emit(self.geometry)

    def getGeometry(self):
        return self._geometry

    def setGeometry(self, rect):
        self._geometry = rect

    def moveLeft(self, x):
        self._geometry.moveLeft(x)
        self.valueChanged.emit(self.geometry)

    def setValue(self, rect):
        self.setGeometry(rect)

    pos = Property(QPointF, getPos, setPos)
    length = Property(float, getLength, setLength)
    geometry = Property(QRectF, getGeometry, setGeometry)


# ---------------------------------------------------------------------- #
# 平滑滚动（condensed：滚轮 → 滚动条值 OutCubic 动画）
# ---------------------------------------------------------------------- #
class SmoothScrollBar(QScrollBar):
    """值变化带 500ms OutCubic 动画的滚动条（短距离按时长比例缩短）。"""

    def __init__(self, orient, parent):
        super().__init__(orient, parent)
        self.duration = 500
        # ⚠ __value 必须先于动画配置初始化：setTargetObject/propertyName 会
        # 立即回读属性当前值，彼时 __value 未建会抛不可见 AttributeError。
        self.__value = self.value()
        self.ani = QPropertyAnimation()
        self.ani.setTargetObject(self)
        self.ani.setPropertyName(b"val")
        self.ani.setEasingCurve(QEasingCurve.OutCubic)
        self.ani.setDuration(self.duration)

    def setValue(self, value, useAni=True):
        if value == self.value():
            return
        self.ani.stop()
        if not useAni:
            self.val = value
            return
        dv = abs(value - self.value())
        if dv < 50:
            self.ani.setDuration(int(self.duration * dv / 70))
        else:
            self.ani.setDuration(self.duration)
        self.ani.setStartValue(self.value())
        self.ani.setEndValue(value)
        self.ani.start()

    def scrollToValue(self, value):
        self.setValue(value)

    def scrollTo(self, value):
        self.setValue(value, useAni=False)

    def getVal(self):
        return self.__value

    def setVal(self, value):
        self.__value = value
        super().setValue(value)

    val = Property(int, getVal, setVal)


class SmoothScrollDelegate(QObject):
    """给滚动区挂平滑滚动：滚轮事件转动画、滚动条换 SmoothScrollBar、
    视图（item view）切 ScrollPerPixel、水平条策略订死。"""

    def __init__(self, parent: QAbstractScrollArea, useAni=True):
        super().__init__(parent)
        self.useAni = useAni
        self.vScrollBar = SmoothScrollBar(Qt.Vertical, parent)
        self.hScrollBar = SmoothScrollBar(Qt.Horizontal, parent)

        if isinstance(parent, QAbstractItemView):
            parent.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
            parent.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        if isinstance(parent, QListView):
            parent.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
            parent.horizontalScrollBar().setStyleSheet(
                "QScrollBar:horizontal{height: 0px}")

        parent.viewport().installEventFilter(self)

    def eventFilter(self, obj, e):
        if e.type() == QEvent.Wheel:
            # ⚠ 必须驱动**区域自身的滚动条**（parent.verticalScrollBar()）：
            # 早期版本驱动的是本类自建的游离 SmoothScrollBar，区域根本不动，
            # 滚轮等于被吞掉（B1 遗留 bug，2026-10-18 自查修复）。
            if e.angleDelta().y() != 0:
                if self._wheelScroll(self.parent().verticalScrollBar(),
                                     e.angleDelta().y()):
                    e.accept()
                    return True
            elif e.angleDelta().x() != 0:
                if self._wheelScroll(self.parent().horizontalScrollBar(),
                                     e.angleDelta().x()):
                    e.accept()
                    return True
        return super().eventFilter(obj, e)

    def _wheelScroll(self, bar, delta: int) -> bool:
        """滚轮 → 区域滚动条动画（OutCubic 300ms）；到界返回 False 放行。"""
        target = self._wheelTarget(bar, delta)
        if target == bar.value():
            return False
        if not self.useAni:
            bar.setValue(target)
            return True
        ani = QPropertyAnimation(bar, b"value", self)
        ani.setStartValue(bar.value())
        ani.setEndValue(target)
        ani.setDuration(300)
        ani.setEasingCurve(QEasingCurve.OutCubic)
        ani.start(QPropertyAnimation.DeleteWhenStopped)
        return True

    @staticmethod
    def _wheelTarget(bar, delta):
        """滚轮 delta → 目标值（夹在范围内；一步 120≈半页的 1/3）。"""
        step = max(bar.pageStep() // 3, 30) if bar.pageStep() else 60
        target = bar.value() - (1 if delta > 0 else -1) * step
        return max(bar.minimum(), min(bar.maximum(), target))
