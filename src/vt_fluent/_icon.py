# -*- coding: utf-8 -*-
# @version 2.5.0
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
from ._anim import singledispatchmethod

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import (QAction, QColor, QIcon, QIconEngine, QImage, QPainter,
                           QPixmap)
from PySide6.QtSvg import QSvgRenderer

from ._icons_data import ART, EXTRA_ART, MEMBERS
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

    def _svg(self):
        """取该图标的 SVG 源（枚举成员查 ART，缺项报清晰错）。"""
        svg = ART.get(self.name)
        if svg is None:
            raise RuntimeError(
                "vt_fluent.FluentIcon.%s 无内嵌艺术字（使用面外成员）。"
                "补充：跑 scripts/dev/_gen_vt_fluent_icons.py 再生成"
                " _icons_data.py。" % self.name)
        return svg

    def _svg_bytes(self, hexcolor):
        return _fill_swapped(self._svg(), hexcolor).encode()

    def icon(self, theme=Theme.AUTO, color=None) -> QIcon:
        """造 QIcon（主题感知：AUTO 跟随当前主题实时换色）。"""
        if color is None:
            return QIcon(FluentIconEngine(self))
        return QIcon(SvgIconEngine(
            _fill_swapped(self._svg(), QColor(color).name())))

    def qicon(self, reverse=False) -> QIcon:
        """转 QIcon（主题同步更新）。"""
        return QIcon(FluentIconEngine(self, reverse))

    def colored(self, lightColor, darkColor):
        """明暗双色图标（运行期按主题取色）。"""
        return _ColoredFluentIcon(self, QColor(lightColor), QColor(darkColor))

    def render(self, painter, rect, theme=Theme.AUTO, **attributes):
        """自绘渲染（对齐上游 render：可带 fill 等属性覆盖取色）。"""
        if "fill" in attributes:
            color = QColor(attributes["fill"]).name()
        else:
            color = QColor(getIconColor(theme)).name()
        renderer = QSvgRenderer(self._svg_bytes(color))
        renderer.render(painter, QRectF(rect))


class _ColoredFluentIcon(FluentIconBase):
    """明暗分色图标（上游 ColoredFluentIcon 的等价物）。"""

    def __init__(self, icon, lightColor, darkColor):
        self.fluentIcon = icon
        self.lightColor = lightColor
        self.darkColor = darkColor

    def _svg(self):
        return self.fluentIcon._svg()

    def _target(self):
        return self.darkColor if isDarkTheme() else self.lightColor

    def icon(self, theme=Theme.AUTO, color=None) -> QIcon:
        return QIcon(SvgIconEngine(
            _fill_swapped(self.fluentIcon._svg(),
                          self._target().name())))

    def render(self, painter, rect, theme=Theme.AUTO, **attributes):
        renderer = QSvgRenderer(
            _fill_swapped(self.fluentIcon._svg(),
                          self._target().name()).encode())
        renderer.render(painter, QRectF(rect))


class ExtraIcon(FluentIconBase):
    """EXTRA_ART 内的自绘图标（check_box/spin_box 等非 FluentIcon 资源）。

    构造：ExtraIcon("images_check_box_Accept")（键 = 资源路径扁平化）。
    """

    def __init__(self, key):
        self._key = key

    @property
    def name(self):
        return self._key

    @property
    def value(self):
        return self._key

    def path(self, theme=Theme.AUTO):
        return ":/vt_fluent/images/%s.svg" % self._key

    def _svg(self):
        svg = EXTRA_ART.get(self._key)
        if svg is None:
            raise RuntimeError(
                "vt_fluent 无 EXTRA_ART 图标 %r；补提取：跑"
                " scripts/dev/_gen_vt_fluent_icons.py。" % self._key)
        return svg


#: FluentIcon 枚举：成员表来自 _icons_data.MEMBERS（与上游逐名同值）
FluentIcon = Enum("FluentIcon", MEMBERS, type=FluentIconBase)


class Icon(QIcon):
    """带 fluentIcon 溯源信息的 QIcon。

    ⚠ 必须用 FluentIconEngine 构造：`QIcon(path)` 走的是 Qt 资源路径
    （`:/vt_fluent/images/...`），本项目图标是内嵌 SVG、没有 .qrc，构造出来
    恒为空图标（曾导致菜单/命令条图标全部消失）。
    """

    def __init__(self, fluentIcon):
        super().__init__(FluentIconEngine(fluentIcon))
        self.fluentIcon = fluentIcon


def toQIcon(icon):
    """FluentIconBase/str/QIcon → QIcon。"""
    if isinstance(icon, str):
        return QIcon(icon)
    if isinstance(icon, FluentIconBase):
        return icon.icon()
    return icon


def drawIcon(icon, painter, rect, state=QIcon.Off, **attributes):
    """画图标（FluentIconBase 走自绘引擎，其余走 QIcon）。

    对齐上游 common.icon.drawIcon 的语义：FluentIconBase 渲染（可带 fill
    等属性），Icon 溯源到其 fluentIcon，其余按普通 QIcon 绘制。
    """
    if isinstance(icon, FluentIconBase):
        fill = attributes.get("fill")
        if fill:
            renderer = QSvgRenderer(
                _fill_swapped(icon._svg(), QColor(fill).name()).encode())
            renderer.render(painter, QRectF(rect))
        else:
            # 复用引擎（主题感知 + 态透明度由引擎处理）
            engine = FluentIconEngine(icon)
            r = rect.toRect() if hasattr(rect, "toRect") else QRect(rect)
            engine.paint(painter, r, QIcon.Normal, state)
    elif isinstance(icon, Icon):
        drawIcon(icon.fluentIcon, painter, rect, state, **attributes)
    else:
        icon = QIcon(icon)
        r = rect.toRect() if hasattr(rect, "toRect") else QRect(rect)
        icon.paint(painter, r, Qt.AlignCenter, state=state)


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
