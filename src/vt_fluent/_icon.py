# -*- coding: utf-8 -*-
# @version 2.3.1
"""vt_fluent 图标引擎（自研，替代 qfluentwidgets.common.icon 的 SVG 图标体系）。

与 qfluentwidgets 1.11.3 FluentIcon 的行为契约：
· FluentIcon 枚举全成员（名与值逐一相同，含 LIBRARY/BOOK_SHELF 别名对）；
· 图标颜色跟随主题：浅色=黑、深色=白，AUTO 实时解析（切主题即换色）；
· Disabled 态透明度 0.5、Selected 态 0.7（与上游 FluentIconEngine 一致）；
· Action/Icon/toQIcon 签名兼容。

实现差异（不损风格）：
· 艺术字内嵌于 _icons_data.ART（单黑变体），渲染时按主题**替换 fill**——
  一份数据服务明暗两档，且随主题色可着色（替代上游 _black/_white 双文件）；
· 未覆盖的使用面外成员（ART 缺项）渲染时报清晰错误，指引补提取脚本。
"""

import re
from enum import Enum
from functools import singledispatchmethod

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import (QAction, QColor, QIcon, QIconEngine, QImage, QPainter,
                           QPixmap)
from PySide6.QtSvg import QSvgRenderer

from ._icons_data import ART, MEMBERS
from ._theme import Theme, isDarkTheme

#: 单 fill 占位（59 个图标经核均为 #000000 或 #000，恰好一处）
_FILL_RE = re.compile(r'fill="#0+"')


def getIconColor(theme=Theme.AUTO, reverse=False):
    """图标色名（'black'/'white'，沿用上游语义：浅色档黑、深色档白）。"""
    if not reverse:
        lc, dc = "black", "white"
    else:
        lc, dc = "white", "black"
    if theme == Theme.AUTO:
        return dc if isDarkTheme() else lc
    return dc if theme == Theme.DARK else lc


def _fill_swapped(svg: str, hexcolor: str) -> str:
    """把图标 SVG 的单 fill 替换为目标色（#rrggbb）。"""
    return _FILL_RE.sub('fill="%s"' % hexcolor, svg, count=1)


class FluentIconEngine(QIconEngine):
    """Fluent 图标引擎：主题感知 + 态透明度 + x=19 光学修正（对齐上游）。"""

    def __init__(self, icon, reverse=False):
        super().__init__()
        self.icon = icon
        self.isThemeReversed = reverse

    def _target_color(self):
        theme = Theme.AUTO
        if self.isThemeReversed:
            theme = Theme.LIGHT if isDarkTheme() else Theme.DARK
        return QColor(getIconColor(theme))

    def paint(self, painter, rect, mode, state):
        painter.save()
        if mode == QIcon.Disabled:
            painter.setOpacity(0.5)
        elif mode == QIcon.Selected:
            painter.setOpacity(0.7)
        icon = self.icon
        if isinstance(icon, Icon):
            icon = icon.fluentIcon
        if isinstance(icon, FluentIconBase):
            svg = icon._svg_bytes(self._target_color().name())
            renderer = QSvgRenderer(svg)
            # 上游光学修正：x=19 处左移 1px（导航栏图标居中补偿）
            if rect.x() == 19:
                rect = rect.adjusted(-1, 0, 0, 0)
            renderer.render(painter, QRectF(rect))
        painter.restore()

    def clone(self):
        return FluentIconEngine(self.icon, self.isThemeReversed)

    def pixmap(self, size, mode, state):
        image = QImage(size, QImage.Format_ARGB32)
        image.fill(Qt.transparent)
        pixmap = QPixmap.fromImage(image, Qt.NoFormatConversion)
        painter = QPainter(pixmap)
        self.paint(painter, QRect(0, 0, size.width(), size.height()), mode, state)
        painter.end()
        return pixmap


class SvgIconEngine(QIconEngine):
    """静态 SVG 引擎（给定完整 SVG 字节流）。"""

    def __init__(self, svg: str):
        super().__init__()
        self.svg = svg

    def paint(self, painter, rect, mode, state):
        renderer = QSvgRenderer(self.svg.encode())
        renderer.render(painter, QRectF(rect))

    def clone(self):
        return SvgIconEngine(self.svg)

    def pixmap(self, size, mode, state):
        image = QImage(size, QImage.Format_ARGB32)
        image.fill(Qt.transparent)
        pixmap = QPixmap.fromImage(image, Qt.NoFormatConversion)
        painter = QPainter(pixmap)
        self.paint(painter, QRect(0, 0, size.width(), size.height()), mode, state)
        painter.end()
        return pixmap


class FluentIconBase:
    """Fluent 图标基类（枚举成员的混入基类）。"""

    def path(self, theme=Theme.AUTO):
        """资源风格路径（API 兼容用；实际渲染走内嵌 ART）。"""
        return ":/vt_fluent/images/icons/%s_%s.svg" % (
            self.value, getIconColor(theme))

    def _art(self):
        svg = ART.get(self.name)
        if svg is None:
            raise RuntimeError(
                "vt_fluent.FluentIcon.%s 无内嵌艺术字（使用面外成员）。"
                "补充：跑 data/tmp/_extract_qfw_ref.py 提取后重跑"
                " data/tmp/_gen_icons_data.py 再生成 _icons_data.py。"
                % self.name)
        return svg

    def _svg_bytes(self, hexcolor):
        return _fill_swapped(self._art(), hexcolor).encode()

    def icon(self, theme=Theme.AUTO, color=None) -> QIcon:
        """造 QIcon（主题感知：AUTO 跟随当前主题实时换色）。"""
        if color is None:
            return QIcon(FluentIconEngine(self))
        return QIcon(SvgIconEngine(
            _fill_swapped(self._art(), QColor(color).name())))

    def qicon(self, reverse=False) -> QIcon:
        """转 QIcon（主题同步更新）。"""
        return QIcon(FluentIconEngine(self, reverse))

    def colored(self, lightColor, darkColor):
        """明暗双色图标（运行期按主题取色）。"""
        return _ColoredFluentIcon(self, QColor(lightColor), QColor(darkColor))


class _ColoredFluentIcon(FluentIconBase):
    """明暗分色图标（上游 ColoredFluentIcon 的等价物）。"""

    def __init__(self, icon, lightColor, darkColor):
        self.fluentIcon = icon
        self.lightColor = lightColor
        self.darkColor = darkColor

    def _target(self):
        return self.darkColor if isDarkTheme() else self.lightColor

    def icon(self, theme=Theme.AUTO, color=None) -> QIcon:
        return QIcon(SvgIconEngine(
            _fill_swapped(self.fluentIcon._art(),
                          self._target().name())))

    def render(self, painter, rect, theme=Theme.AUTO, **attributes):
        renderer = QSvgRenderer(
            _fill_swapped(self.fluentIcon._art(),
                          self._target().name()).encode())
        renderer.render(painter, QRectF(rect))


#: FluentIcon 枚举：成员表来自 _icons_data.MEMBERS（与上游逐名同值）
FluentIcon = Enum("FluentIcon", MEMBERS, type=FluentIconBase)


class Icon(QIcon):
    """带 fluentIcon 溯源信息的 QIcon。"""

    def __init__(self, fluentIcon):
        super().__init__(fluentIcon.path())
        self.fluentIcon = fluentIcon


def toQIcon(icon):
    """FluentIconBase/str/QIcon → QIcon。"""
    if isinstance(icon, str):
        return QIcon(icon)
    if isinstance(icon, FluentIconBase):
        return icon.icon()
    return icon


class Action(QAction):
    """Fluent 动作（QAction + fluentIcon 溯源，切主题图标跟随）。

    构造重载（对齐上游）：
    * Action(parent=..., **kwargs)
    * Action(text, parent=..., **kwargs)
    * Action(QIcon, text, parent=..., **kwargs)
    * Action(FluentIconBase, text, parent=..., **kwargs)
    """

    @singledispatchmethod
    def __init__(self, parent=None, **kwargs):
        super().__init__(parent, **kwargs)
        self.fluentIcon = None

    @__init__.register
    def _(self, text: str, parent=None, **kwargs):
        super().__init__(text, parent, **kwargs)
        self.fluentIcon = None

    @__init__.register
    def _(self, icon: QIcon, text: str, parent=None, **kwargs):
        super().__init__(icon, text, parent, **kwargs)
        self.fluentIcon = None

    @__init__.register
    def _(self, icon: FluentIconBase, text: str, parent=None, **kwargs):
        super().__init__(icon.icon(), text, parent, **kwargs)
        self.fluentIcon = icon

    def icon(self) -> QIcon:
        if self.fluentIcon:
            return Icon(self.fluentIcon)
        return super().icon()

    def setIcon(self, icon):
        if isinstance(icon, FluentIconBase):
            self.fluentIcon = icon
            icon = icon.icon()
        super().setIcon(icon)
