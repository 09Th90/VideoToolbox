# coding: utf-8
# @version 2.4.0
"""Qt / qfluentwidgets 运行期兼容补丁。

只放「上游有回归、且当前没有可升级版本」的针对性修补。每个补丁都必须自带
**运行期探测**：只有真的复现出问题才生效——上游修好后自动失效，不用回来删代码。
"""
from __future__ import annotations

#: qfluentwidgets `spin_box.qss` 里 `SpinBox { border: 1px; padding: 0 80px 0 10px }`：
#: 编辑框左沿 = 边框 1px + 左内边距 10px（普通档与 Compact 档一致）。
_SPIN_EDIT_LEFT_INSET = 11

#: 认为「编辑框宽度正常」的下限（px）。数值形如 1048576 至少要几十像素，
#: 这里只用来区分「1px 塌陷」与「正常」，取个远离两端的阈值即可。
_SPIN_EDIT_MIN_OK_WIDTH = 8


def _spin_editfield_is_broken():
    """探测 qfluentwidgets 的 SpinBox 内嵌编辑框是否被 Qt 算成了 1px 宽。

    建一个离屏的 SpinBox 跑一遍真实布局（不弹窗、不显示），量它的 QLineEdit。
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
    from vt_fluent import SpinBox

    host = QWidget()
    # WA_DontShowOnScreen：照常走 show/布局/几何计算，但不上屏，避免启动闪窗
    host.setAttribute(Qt.WA_DontShowOnScreen, True)
    lay = QVBoxLayout(host)
    box = SpinBox(host)
    box.setRange(0, 1000000)
    box.setValue(123456)
    lay.addWidget(box)
    host.resize(400, 60)
    host.show()
    try:
        QApplication.processEvents()
        le = box.lineEdit()
        return le is None or le.width() < _SPIN_EDIT_MIN_OK_WIDTH
    finally:
        host.hide()
        host.deleteLater()


def install_spinbox_fix():
    """修「设置页所有 SpinBox 数值空白、点上下箭头也不变」（Qt 6.12.0 回归）。

    现象：设置页里输入/输出预算、每块条数、每块字符预算、思考轮次上限等
    SpinBox 全是**空框**，只有上下箭头；点箭头数值其实在变，但看不见。

    根因：Qt 6.12.0 的 QStyleSheetStyle 在
    `spin->buttonSymbols == QAbstractSpinBox::NoButtons` 时，把
    SC_SpinBoxEditField 算成 **1px 宽**（qtbase qstylesheetstyle.cpp
    `case CC_SpinBox:` → `SC_SpinBoxEditField`）；而 qfluentwidgets 正是
    「先 `setButtonSymbols(NoButtons)`、再用 QSS 的 padding 预留右侧按钮位」。
    1px 的 QLineEdit 装不下数字，于是「数值看不见、也点不动」。
    用**纯 QSpinBox** + 带 padding 的 QSS + NoButtons 即可复现，与
    qfluentwidgets 本身无关。6.12.0 是当前 PyPI 最新版，没有补丁版可升。

    修法：给 SpinBoxBase 补 resizeEvent / showEvent / changeEvent，在 Qt 自己
    算完（算错的）几何之后，按「左边框+左内边距 … 右侧按钮左沿」把内嵌
    QLineEdit 重新铺开。只读时按钮隐藏，编辑框自动铺满整行；幂等、无副作用。

    返回是否真的打了补丁（False = 环境没这问题，或补丁已打过）。
    """
    try:
        from PySide6.QtWidgets import QAbstractSpinBox, QStyle
        from vt_fluent import SpinBoxBase
    except Exception:  # noqa: BLE001
        return False
    if getattr(SpinBoxBase, "_vt_editfield_fixed", False):
        return False
    try:
        if not _spin_editfield_is_broken():
            return False
    except Exception:  # noqa: BLE001
        return False

    def _relayout(self):
        # ⚠️ changeEvent 可能在 SpinBoxBase.__init__ 里就触发（那时 hBoxLayout
        # 还没建），必须容错，否则构造 SpinBox 直接抛 AttributeError。
        hbox = getattr(self, "hBoxLayout", None)
        if hbox is None:
            return
        le = self.lineEdit()
        if le is None:
            return
        margins = hbox.contentsMargins()
        spacing = hbox.spacing()
        if spacing < 0:
            spacing = self.style().pixelMetric(
                QStyle.PM_LayoutHorizontalSpacing)
        # 右侧按钮区按**实际可见**的按钮算：Inline 档是两个 31px，Compact 档
        # 是一个 26px；只读时全部隐藏 → 编辑框铺满整行。
        right = margins.right()
        for name in ("upButton", "downButton", "compactSpinButton"):
            btn = getattr(self, name, None)
            if btn is not None and btn.isVisible():
                right += btn.width() + spacing
        left = margins.left() + _SPIN_EDIT_LEFT_INSET
        rect = self.rect().adjusted(left, margins.top(), -right,
                                    -margins.bottom())
        if rect.width() > 0 and le.geometry() != rect:
            le.setGeometry(rect)

    def _resizeEvent(self, e):
        QAbstractSpinBox.resizeEvent(self, e)
        _relayout(self)

    def _showEvent(self, e):
        QAbstractSpinBox.showEvent(self, e)
        _relayout(self)

    def _changeEvent(self, e):
        QAbstractSpinBox.changeEvent(self, e)
        _relayout(self)

    SpinBoxBase.resizeEvent = _resizeEvent
    SpinBoxBase.showEvent = _showEvent
    SpinBoxBase.changeEvent = _changeEvent
    SpinBoxBase._vt_editfield_fixed = True
    return True
