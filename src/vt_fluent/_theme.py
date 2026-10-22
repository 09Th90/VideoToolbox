# -*- coding: utf-8 -*-
# @version 2.5.2
"""vt_fluent 主题引擎（自研，替代 qfluentwidgets.common.config / style_sheet / font）。

定位：Fluent 风格主题层的单一权威。上层控件（_buttons/_inputs/_display/...）
与宿主页面的样式、图标取色、字体、配置持久化全部经这里。与 qfluentwidgets
对应模块的**行为契约**（B0 门 = 逐值对照）：

· Theme / qconfig / ConfigItem 体系     —— 配置项、验证器、序列化器、信号
· ThemeColor 七档 HSV 派生               —— 与 qfluentwidgets 同公式同系数
· setTheme / setThemeColor / 样式表管理器 —— 注册表 + 主题切换全量重应用
· renderQss / applyThemeColor            —— `--ThemeColorXxx` 模板替换
· setFont / fontFamilies                 —— 应用字体清单

与上游的两处**刻意差异**（不损 Fluent 风格）：
1. AUTO 档系统深浅探测自研（winreg 直读 AppsUseLightTheme），不依赖 darkdetect
   —— 少一个随包第三方依赖（本库存在的理由之一）。
2. FluentStyleSheet 的 QSS 载体是自写合并文件（_qss/common + light/dark），
   而非上游的逐控件分文件；QSS 规则按类名作用域，合并不改渲染语义。
"""

import json
import os
import sys
from collections import OrderedDict
from copy import deepcopy
from enum import Enum
from pathlib import Path
from string import Template
from typing import List, Union
import weakref

from PySide6.QtCore import QFile, QObject, QEvent, QDynamicPropertyChangeEvent, Signal, qVersion
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QApplication, QWidget, QStyleFactory


# ---------------------------------------------------------------------- #
# 主题枚举
# ---------------------------------------------------------------------- #
class Theme(Enum):
    """主题枚举（与 qfluentwidgets.Theme 逐名同值）。"""

    LIGHT = "Light"
    DARK = "Dark"
    AUTO = "Auto"


# ---------------------------------------------------------------------- #
# 配置校验 / 序列化
# ---------------------------------------------------------------------- #
class ConfigValidator:
    """配置校验器基类。"""

    def validate(self, value):
        return True

    def correct(self, value):
        return value


class RangeValidator(ConfigValidator):
    """区间校验器。"""

    def __init__(self, min, max):
        self.min = min
        self.max = max
        self.range = (min, max)

    def validate(self, value):
        return self.min <= value <= self.max

    def correct(self, value):
        return min(max(self.min, value), self.max)


class OptionsValidator(ConfigValidator):
    """枚举候选校验器。"""

    def __init__(self, options):
        if not options:
            raise ValueError("The `options` can't be empty.")
        if isinstance(options, Enum):
            options = options._member_map_.values()
        self.options = list(options)

    def validate(self, value):
        return value in self.options

    def correct(self, value):
        return value if self.validate(value) else self.options[0]


class BoolValidator(OptionsValidator):
    """布尔校验器。"""

    def __init__(self):
        super().__init__([True, False])


class FolderValidator(ConfigValidator):
    """目录校验器。"""

    def validate(self, value):
        return Path(value).exists()

    def correct(self, value):
        path = Path(value)
        path.mkdir(exist_ok=True, parents=True)
        return str(path.absolute()).replace("\\", "/")


class FolderListValidator(ConfigValidator):
    """目录列表校验器。"""

    def validate(self, value):
        return all(Path(i).exists() for i in value)

    def correct(self, value: List[str]):
        folders = []
        for folder in value:
            path = Path(folder)
            if path.exists():
                folders.append(str(path.absolute()).replace("\\", "/"))
        return folders


class ColorValidator(ConfigValidator):
    """颜色校验器。"""

    def __init__(self, default):
        self.default = QColor(default)

    def validate(self, color):
        try:
            return QColor(color).isValid()
        except Exception:
            return False

    def correct(self, value):
        return QColor(value) if self.validate(value) else self.default


class ConfigSerializer:
    """序列化器基类。"""

    def serialize(self, value):
        return value

    def deserialize(self, value):
        return value


class EnumSerializer(ConfigSerializer):
    """枚举序列化器。"""

    def __init__(self, enumClass):
        self.enumClass = enumClass

    def serialize(self, value):
        return value.value

    def deserialize(self, value):
        return self.enumClass(value)


class ColorSerializer(ConfigSerializer):
    """QColor 序列化器。"""

    def serialize(self, value: QColor):
        return value.name(QColor.HexArgb)

    def deserialize(self, value):
        if isinstance(value, list):
            return QColor(*value)
        return QColor(value)


# ---------------------------------------------------------------------- #
# 配置项
# ---------------------------------------------------------------------- #
class ConfigItem(QObject):
    """配置项（group/name/default/validator/serializer/restart）。"""

    valueChanged = Signal(object)

    def __init__(self, group, name, default, validator=None, serializer=None, restart=False):
        super().__init__()
        self.group = group
        self.name = name
        self.validator = validator or ConfigValidator()
        self.serializer = serializer or ConfigSerializer()
        self.__value = default
        self.value = default
        self.restart = restart
        self.defaultValue = self.validator.correct(default)

    @property
    def value(self):
        return self.__value

    @value.setter
    def value(self, v):
        v = self.validator.correct(v)
        ov = self.__value
        self.__value = v
        if ov != v:
            self.valueChanged.emit(v)

    @property
    def key(self):
        return self.group + "." + self.name if self.name else self.group

    def __str__(self):
        return f"{self.__class__.__name__}[value={self.value}]"

    def serialize(self):
        return self.serializer.serialize(self.value)

    def deserializeFrom(self, value):
        self.value = self.serializer.deserialize(value)


class RangeConfigItem(ConfigItem):
    """区间配置项。"""

    @property
    def range(self):
        return self.validator.range

    def __str__(self):
        return f"{self.__class__.__name__}[range={self.range}, value={self.value}]"


class OptionsConfigItem(ConfigItem):
    """候选配置项。"""

    @property
    def options(self):
        return self.validator.options

    def __str__(self):
        return f"{self.__class__.__name__}[options={self.options}, value={self.value}]"


class ColorConfigItem(ConfigItem):
    """颜色配置项。"""

    def __init__(self, group, name, default, restart=False):
        super().__init__(group, name, QColor(default), ColorValidator(default),
                         ColorSerializer(), restart)

    def __str__(self):
        return f"{self.__class__.__name__}[value={self.value.name()}]"


# ---------------------------------------------------------------------- #
# 系统深浅探测（自研，替代 darkdetect）
# ---------------------------------------------------------------------- #
def _system_is_dark():
    """Windows 当前是否为深色应用模式。

    读 HKCU\\...\\Themes\\Personalize 的 AppsUseLightTheme（0=深色）。
    非 Windows 或读不到时回退浅色——与 darkdetect 探测失败（None）时
    qconfig 落 Theme.LIGHT 的行为一致。
    """
    if sys.platform != "win32":
        return False
    try:
        import winreg
        with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            v, _ = winreg.QueryValueEx(k, "AppsUseLightTheme")
            return v == 0
    except Exception:
        return False


# ---------------------------------------------------------------------- #
# 应用配置（qconfig）
# ---------------------------------------------------------------------- #
class QConfig(QObject):
    """应用配置：主题档 / 主题色 / 字体清单 + 持久化。"""

    appRestartSig = Signal()
    themeChanged = Signal(Theme)
    themeChangedFinished = Signal()
    themeColorChanged = Signal(QColor)

    # ⚠ 默认档与上游 qfluentwidgets（LIGHT）**有意偏离**：对齐业务主题源
    # ui_theme._default_cfg()["theme"]="dark"（src/ui_theme.py）。否则任何
    # 绕过 apply_startup_theme 的入口（GUI 探针/单测/独立页面构造）会落到
    # LIGHT，与 ui_theme 轨读到的用户配置（默认 dark）错位——2026-10-20
    # 复现：探针裸构造页面时 qconfig=LIGHT 而 ui_custom=dark，浅档 QSS 与
    # 深色 UICard token 混搭（「页面一半深一半浅」）。
    themeMode = OptionsConfigItem(
        "QFluentWidgets", "ThemeMode", Theme.DARK, OptionsValidator(Theme),
        EnumSerializer(Theme))
    themeColor = ColorConfigItem("QFluentWidgets", "ThemeColor", "#009faa")
    fontFamilies = ConfigItem(
        "QFluentWidgets", "FontFamilies",
        ["Segoe UI", "Microsoft YaHei", "PingFang SC"])

    def __init__(self):
        super().__init__()
        self.file = Path("config/config.json")
        # 与 themeMode 默认档一致（DARK，对齐 ui_theme._default_cfg；理由见
        # themeMode 定义处注释）。
        self._theme = Theme.DARK
        self._cfg = self

    def get(self, item):
        return item.value

    def set(self, item, value, save=True, copy=True):
        if item.value == value:
            return
        try:
            item.value = deepcopy(value) if copy else value
        except Exception:
            item.value = value
        if save:
            self.save()
        if item.restart:
            self._cfg.appRestartSig.emit()
        if item is self._cfg.themeMode:
            self.theme = value
            self._cfg.themeChanged.emit(value)
        if item is self._cfg.themeColor:
            self._cfg.themeColorChanged.emit(value)

    def toDict(self, serialize=True):
        items = {}
        for name in dir(self._cfg.__class__):
            item = getattr(self._cfg.__class__, name)
            if not isinstance(item, ConfigItem):
                continue
            value = item.serialize() if serialize else item.value
            if not items.get(item.group):
                if not item.name:
                    items[item.group] = value
                else:
                    items[item.group] = {}
            if item.name:
                items[item.group][item.name] = value
        return items

    def save(self):
        self._cfg.file.parent.mkdir(parents=True, exist_ok=True)
        with open(self._cfg.file, "w", encoding="utf-8") as f:
            json.dump(self._cfg.toDict(), f, ensure_ascii=False, indent=4)

    def load(self, file=None, config=None):
        if isinstance(config, QConfig):
            self._cfg = config
            self._cfg.themeChanged.connect(self.themeChanged)
        if isinstance(file, (str, Path)):
            self._cfg.file = Path(file)
        try:
            with open(self._cfg.file, encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}
        items = {}
        for name in dir(self._cfg.__class__):
            item = getattr(self._cfg.__class__, name)
            if isinstance(item, ConfigItem):
                items[item.key] = item
        for k, v in cfg.items():
            if not isinstance(v, dict) and items.get(k) is not None:
                items[k].deserializeFrom(v)
            elif isinstance(v, dict):
                for key, value in v.items():
                    key = k + "." + key
                    if items.get(key) is not None:
                        items[key].deserializeFrom(value)
        self.theme = self.get(self._cfg.themeMode)

    @property
    def theme(self):
        return self._cfg._theme

    @theme.setter
    def theme(self, t):
        if t == Theme.AUTO:
            t = Theme.DARK if _system_is_dark() else Theme.LIGHT
        self._cfg._theme = t


QT_VERSION = tuple(int(v) for v in qVersion().split("."))

qconfig = QConfig()


def isDarkTheme():
    """当前是否深色。"""
    return qconfig.theme == Theme.DARK


def theme():
    """当前实际生效主题（AUTO 已解析）。"""
    return qconfig.theme


def isDarkThemeMode(themeMode=Theme.AUTO):
    """主题档是否为深色（AUTO 问当前解析值）。"""
    return themeMode == Theme.DARK if themeMode != Theme.AUTO else isDarkTheme()


def themeColor():
    """当前主题色（PRIMARY 档）。"""
    return ThemeColor.PRIMARY.color()


def toggleTheme(save=False, lazy=False):
    """深浅互换。"""
    setTheme(Theme.LIGHT if isDarkTheme() else Theme.DARK, save, lazy)


# ---------------------------------------------------------------------- #
# 主题色七档派生（HSV，公式与 qfluentwidgets 逐系数一致）
# ---------------------------------------------------------------------- #
class ThemeColor(Enum):
    """主题色档位（PRIMARY/DARK_1..3/LIGHT_1..3）。"""

    PRIMARY = "ThemeColorPrimary"
    DARK_1 = "ThemeColorDark1"
    DARK_2 = "ThemeColorDark2"
    DARK_3 = "ThemeColorDark3"
    LIGHT_1 = "ThemeColorLight1"
    LIGHT_2 = "ThemeColorLight2"
    LIGHT_3 = "ThemeColorLight3"

    def name(self):
        return self.color().name()

    def color(self):
        color = qconfig.get(qconfig._cfg.themeColor)
        h, s, v, _ = color.getHsvF()
        if isDarkTheme():
            s *= 0.84
            v = 1
            if self == self.DARK_1:
                v *= 0.9
            elif self == self.DARK_2:
                s *= 0.977
                v *= 0.82
            elif self == self.DARK_3:
                s *= 0.95
                v *= 0.7
            elif self == self.LIGHT_1:
                s *= 0.92
            elif self == self.LIGHT_2:
                s *= 0.78
            elif self == self.LIGHT_3:
                s *= 0.65
        else:
            if self == self.DARK_1:
                v *= 0.75
            elif self == self.DARK_2:
                s *= 1.05
                v *= 0.5
            elif self == self.DARK_3:
                s *= 1.1
                v *= 0.4
            elif self == self.LIGHT_1:
                v *= 1.05
            elif self == self.LIGHT_2:
                s *= 0.75
                v *= 1.05
            elif self == self.LIGHT_3:
                s *= 0.65
                v *= 1.05
        return QColor.fromHsvF(h, min(s, 1), min(v, 1))


# ---------------------------------------------------------------------- #
# 设计令牌（QSS 库色板单点）
# ---------------------------------------------------------------------- #
#: 设计令牌表 —— 新增控件域与增量演进的**唯一**取色入口。
#:
#: 历史：light/dark.qss 的存量规则是 B0-B2 逐值对照基准（224 项 parity
#: 已验证），**保持原文本**；本表面向**新增域**（滚动条/进度条/Tab/树/
#: 原生提示与菜单/卡片/滚动区）及今后一切增量——新规则一律写 `--Token`
#: 占位符，色值只在此处登记，明暗两档键集一致（键缺失时 renderQss 按
#: safe_substitute 静默跳过，但自检会拦）。
DESIGN_TOKENS = {
    Theme.LIGHT: {
        # 文字
        "TextPrimary": "black",
        "TextSecondary": "rgb(96, 96, 96)",
        "TextPlaceholder": "rgba(0, 0, 0, 0.6063)",
        "TextPressed": "rgba(0, 0, 0, 0.63)",
        "TextDisabled": "rgba(0, 0, 0, 0.36)",
        "TextDisabledWeak": "rgba(0, 0, 0, 0.36)",
        "TextOnAccentDisabled": "rgba(255, 255, 255, 0.43)",
        # 控件填充
        "CtrlFill": "rgba(255, 255, 255, 0.7)",
        "CtrlFillHover": "rgba(249, 249, 249, 0.5)",
        "CtrlFillPressed": "rgba(249, 249, 249, 0.3)",
        "CtrlFillDisabled": "rgba(249, 249, 249, 0.3)",
        "AccentFillDisabled": "rgb(52, 52, 52)",
        "InputFillFocus": "white",
        # 描边
        "StrokeCtrl": "rgba(0, 0, 0, 0.073)",
        "StrokeCtrlBottom": "rgba(0, 0, 0, 0.183)",
        "StrokeCtrlTop": "rgba(0, 0, 0, 0.073)",
        "StrokeDisabled": "rgba(0, 0, 0, 0.06)",
        "StrokeInput": "rgba(0, 0, 0, 13)",
        "StrokeInputBottom": "rgba(0, 0, 0, 100)",
        "StrokeMenu": "rgba(0, 0, 0, 0.1)",
        "StrokeToolTip": "rgba(0, 0, 0, 0.06)",
        "StrokeTable": "rgba(0, 0, 0, 21)",
        "StrokeSolidWeak": "rgb(229, 229, 229)",
        # 弱填充（悬停/按压的 subtle 底）
        "FillSubtle": "rgba(0, 0, 0, 0.0373)",
        "FillSubtleActive": "rgba(0, 0, 0, 0.0241)",
        "FillSubtleHover": "rgba(0, 0, 0, 9)",
        "FillSubtlePressed": "rgba(0, 0, 0, 6)",
        "SegmentedFill": "rgba(0, 0, 0, 0.0241)",
        "SegmentedStroke": "rgba(0, 0, 0, 0.0578)",
        # 实底表面
        "SurfaceSolid": "rgb(249, 249, 249)",
        "DialogFill": "white",
        "DialogFooterFill": "rgb(243, 243, 243)",
        # 专用域
        "SliderGroove": "rgba(0, 0, 0, 100)",
        "ScrollHandle": "rgba(0, 0, 0, 0.35)",
        "ScrollHandleHover": "rgba(0, 0, 0, 0.5)",
        "TrackFill": "rgba(0, 0, 0, 0.0837)",
        "SplitterFill": "transparent",
    },
    Theme.DARK: {
        # 文字
        "TextPrimary": "white",
        "TextSecondary": "rgb(208, 208, 208)",
        "TextPlaceholder": "rgba(255, 255, 255, 0.6063)",
        "TextPressed": "rgba(255, 255, 255, 0.786)",
        "TextDisabled": "rgba(255, 255, 255, 0.3628)",
        "TextDisabledWeak": "rgba(255, 255, 255, 0.36)",
        "TextOnAccentDisabled": "rgba(255, 255, 255, 0.43)",
        # 控件填充
        "CtrlFill": "rgba(255, 255, 255, 0.0605)",
        "CtrlFillHover": "rgba(255, 255, 255, 0.0837)",
        "CtrlFillPressed": "rgba(255, 255, 255, 0.0326)",
        "CtrlFillDisabled": "rgba(255, 255, 255, 0.0419)",
        "AccentFillDisabled": "rgb(52, 52, 52)",
        "InputFillFocus": "rgb(31, 31, 31)",
        # 描边
        "StrokeCtrl": "rgba(255, 255, 255, 0.053)",
        "StrokeCtrlBottom": "rgba(255, 255, 255, 0.053)",
        "StrokeCtrlTop": "rgba(255, 255, 255, 0.08)",
        "StrokeDisabled": "rgba(255, 255, 255, 0.0698)",
        "StrokeInput": "rgba(255, 255, 255, 0.08)",
        "StrokeInputBottom": "rgba(255, 255, 255, 0.5442)",
        "StrokeMenu": "rgba(255, 255, 255, 0.1)",
        "StrokeToolTip": "rgb(28, 28, 28)",
        "StrokeTable": "rgba(255, 255, 255, 21)",
        "StrokeSolidWeak": "rgb(29, 29, 29)",
        # 弱填充
        "FillSubtle": "rgba(255, 255, 255, 0.08)",
        "FillSubtleActive": "rgba(255, 255, 255, 0.06)",
        "FillSubtleHover": "rgba(255, 255, 255, 9)",
        "FillSubtlePressed": "rgba(255, 255, 255, 6)",
        "SegmentedFill": "rgba(0, 0, 0, 0.1)",
        "SegmentedStroke": "rgba(255, 255, 255, 0.08)",
        # 实底表面
        "SurfaceSolid": "rgb(43, 43, 43)",
        "DialogFill": "rgb(43, 43, 43)",
        "DialogFooterFill": "rgb(32, 32, 32)",
        # 专用域
        "SliderGroove": "rgb(158, 159, 159)",
        "ScrollHandle": "rgba(255, 255, 255, 0.35)",
        "ScrollHandleHover": "rgba(255, 255, 255, 0.5)",
        "TrackFill": "rgba(255, 255, 255, 0.0837)",
        "SplitterFill": "transparent",
    },
}


def designTokens(theme=None):
    """取指定主题的设计令牌字典（缺省当前主题；未知主题回浅色档）。"""
    theme = qconfig.theme if theme is None else theme
    return DESIGN_TOKENS.get(theme, DESIGN_TOKENS[Theme.LIGHT])


# ---------------------------------------------------------------------- #
# QSS 模板替换
# ---------------------------------------------------------------------- #
class QssTemplate(Template):
    """QSS 模板（分隔符 `--`，占位符如 --ThemeColorPrimary）。"""

    delimiter = "--"


def applyThemeColor(qss: str):
    """把 QSS 里的 --ThemeColorXxx 占位符替换为当前主题色名（#rrggbb）。"""
    template = QssTemplate(qss)
    mappings = {c.value: c.name() for c in ThemeColor._member_map_.values()}
    return template.safe_substitute(mappings)


def renderQss(qss: str, theme=None):
    """渲染 QSS：设计令牌 + 主题色七档 + 字体清单全量替换。

    · ``--Token``          ← DESIGN_TOKENS[theme]（缺省/AUTO 取当前主题）
    · ``--ThemeColorXxx``  ← ThemeColor 七档运行期派生（跟随 qconfig 主题）
    · ``--FontFamilies``   ← 'Segoe UI','Microsoft YaHei',...
    对不含占位符的文本输出逐字节不变（theme 自检的兼容前提）。

    2026-10-20 性能优化：渲染结果 memo（LRU 128）。输出只取决于
    (qss 文本, 主题档, themeColor, 字体清单) 四元组——同一份合并 QSS 在
    一轮 updateStyleSheet 里会被几百个控件各求一次，memo 后每次改色/切档
    只做一次 29KB 级 safe_substitute，其余全是 O(1) 命中。
    键里带上 qss 本体强引用，顺带防 hash 碰撞误用。
    """
    if theme is None or theme == Theme.AUTO:
        theme = qconfig.theme
    if os.environ.get("VT_QSS_NOCACHE"):
        # 逃生开关：整体关停 memo（含对照基准，行为回到优化前）
        fonts = tuple(qconfig.get(qconfig.fontFamilies))
        template = QssTemplate(qss)
        mappings = {c.value: c.name() for c in ThemeColor._member_map_.values()}
        mappings["FontFamilies"] = ",".join([f"'{i}'" for i in fonts])
        mappings.update(designTokens(theme))
        return template.safe_substitute(mappings)
    fonts = tuple(qconfig.get(qconfig.fontFamilies))
    key = (qss, theme, qconfig.get(qconfig.themeColor).name(), fonts)
    hit = _RENDER_CACHE.get(key)
    if hit is not None:
        _RENDER_CACHE.move_to_end(key)
        return hit
    template = QssTemplate(qss)
    mappings = {c.value: c.name() for c in ThemeColor._member_map_.values()}
    mappings["FontFamilies"] = ",".join([f"'{i}'" for i in fonts])
    mappings.update(designTokens(theme))
    out = template.safe_substitute(mappings)
    _RENDER_CACHE[key] = out
    if len(_RENDER_CACHE) > 128:
        _RENDER_CACHE.popitem(last=False)
    return out


#: renderQss 渲染结果 memo（键含 qss 本体，命中即 O(1)；见 renderQss docstring）
_RENDER_CACHE: "OrderedDict[tuple, str]" = OrderedDict()

# ---------------------------------------------------------------------- #
# 选择器感知的 QSS 切片（2026-10-20 性能优化）
# ---------------------------------------------------------------------- #
#: 全量合并 QSS ~29KB，历史上每个控件都挂全量：setStyleSheet 的解析与
#: unpolish/polish 级联全量计费（实测容器一发 ~42ms、注册面 2233 个控件）。
#: 本模块按选择器类名给每个控件只发它**可能命中**的规则子集。
#:
#: 优先级安全性（关键论证）：一条规则能匹配控件 W，当且仅当其最右简单
#: 选择器命中 W——右端是类 C 则 C ∈ W 的 MRO（类命中），右端是 #id 则
#: id == W 的 objectName（ID 命中），右端是 `*`/裸伪态则恒发。因此**所
#: 有能匹配 W 的规则都落在 W 自己的切片里**，跨族后代选择器（如
#: `SettingCard QPushButton`）不会从「自有层」降级到「祖先层」，Qt 的
#: 「自有层优先」规则不会改变既有特异性裁决；切不中的规则本就不应用于
#: W（或由其目标控件/祖先层各自携带）。
#:
#: VT_QSS_FULL=1 整体关停（回退全量行为，排障/对照用）。
#: 原生子控件类——QScrollBar/QHeaderView/QAbstractItemView/QWidget 等是
#: Qt **原生子控件**（滚动条、表头、下拉视图、滚动视口），自身不进样式表
#: 注册表、类名也不在注册祖先的 MRO 里，全量时代靠「人人满载」经 Qt 级联
#: 获得样式。切片后给**每个**注册控件的切片补充「右端类属于该集合」的
#: 规则（如 `QScrollBar::add-line {height:0}`、`QComboBox
#: QAbstractItemView`），保持这些原生子控件的观感与全量时代一致。
_NATIVE_CHILD_CLASSES = frozenset({
    "QScrollBar", "QHeaderView", "QAbstractItemView", "QWidget",
    "QSlider", "QGraphicsView", "QGraphicsScene",
})
#: 可能承载上述原生子控件的「容器」类——只有它们需要这份补充规则；
#: 按钮/标签/卡片等叶子控件不需要（缩小切片、降低 polish 成本）。
_NATIVE_HOST_CLASSES = frozenset({
    "QAbstractScrollArea", "QAbstractItemView", "QScrollArea", "QTextEdit",
    "QPlainTextEdit", "QGraphicsView", "QComboBox", "QFontComboBox",
    "QTableView", "QTreeView", "QListView", "QListWidget", "QTableWidget",
    "QTreeWidget", "QTabWidget", "QSplitter",
})
_SLICE_CACHE = {}        # (path, theme, 类名, objectName) -> 切片文本
_CLASS_KEY_CACHE = {}    # type -> (类名, MRO 类名集)
_QSS_INDEX_CACHE = {}    # (path, theme) -> (parsed_rules, 全部类名集)


def _split_qss_rules(text):
    """把合并 QSS 拆成 [(selector, block), ...]（去注释；本库 QSS 无嵌套块）。"""
    import re
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    rules = []
    pos, n = 0, len(text)
    while pos < n:
        brace = text.find("{", pos)
        if brace < 0:
            break
        close = text.find("}", brace)
        if close < 0:
            break
        sel = text[pos:brace].strip()
        if sel:
            rules.append((sel, text[brace + 1:close]))
        pos = close + 1
    return rules


def _rule_tokens(sel):
    """选择器里的类名集合（大写开头标识符）与 #id 集合。"""
    import re
    classes = frozenset(t for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", sel)
                        if t[:1].isupper())
    ids = frozenset(re.findall(r"#([A-Za-z_][A-Za-z0-9_]*)", sel))
    return classes, ids


def _widget_class_key(widget):
    cls = type(widget)
    key = _CLASS_KEY_CACHE.get(cls)
    if key is None:
        names = frozenset(c.__name__ for c in cls.__mro__)
        key = (cls.__name__, names)
        _CLASS_KEY_CACHE[cls] = key
    return key


def _rightmost_class(sel):
    """选择器最右简单选择器里的类名（原生子控件补充集判定用）。"""
    tail = sel.replace(">", " ").replace("+", " ").split()[-1] if sel else ""
    classes, _ = _rule_tokens(tail)
    for c in classes:
        return c
    return ""


def _qss_index(source, theme):
    """(path, theme) → (解析后的规则表, 全部类名集)；解析只做一次。"""
    path = source.path(theme)
    key = (path, theme)
    hit = _QSS_INDEX_CACHE.get(key)
    if hit is None:
        parsed = []
        all_classes = set()
        for sel, block in _split_qss_rules(source.content(theme)):
            classes, ids = _rule_tokens(sel)
            parsed.append((sel, block, classes, ids, _rightmost_class(sel)))
            all_classes |= classes
        hit = _QSS_INDEX_CACHE[key] = (parsed, frozenset(all_classes))
    return hit


def sliced_qss(source, widget, theme=Theme.AUTO):
    """source 全量内容按 widget 类系切片（带缓存）；语义见模块注释。"""
    if os.environ.get("VT_QSS_FULL"):
        return source.content(theme)
    if not isinstance(widget, QWidget):
        # 非控件载体（如 QApplication 上的 app.qss）：全量
        return source.content(theme)
    if theme is None or theme == Theme.AUTO:
        theme = qconfig.theme
    try:
        path = source.path(theme)
    except Exception:
        return source.content(theme)
    parsed, all_classes = _qss_index(source, theme)
    cls_name, names = _widget_class_key(widget)
    objname = widget.objectName() or ""
    ck = (path, theme, cls_name, objname)
    hit = _SLICE_CACHE.get(ck)
    if hit is not None:
        return hit
    is_host = bool(names & _NATIVE_HOST_CLASSES)
    if names & all_classes or objname:
        parts = [f"{sel} {{{block}}}"
                 for sel, block, classes, ids, rightmost in parsed
                 if (classes & names)
                 or (ids and objname in ids)
                 or (is_host and rightmost in _NATIVE_CHILD_CLASSES)  # 容器补充
                 or (not classes and not ids)]      # `*`/裸伪态：恒发
        out = "\n".join(parts)
    else:
        out = ""                    # 类系与整份 QSS 无交集：无规则可命中
    _SLICE_CACHE[ck] = out
    return out


def _iter_sheet_sources(source):
    """递归展平 compose（addStyleSheet 会 legit 累积多源；展平后逐个渲染）。"""
    if isinstance(source, StyleSheetCompose):
        out = []
        for s in source.sources:
            out.extend(_iter_sheet_sources(s))
        return out
    return [source]


def render_for_widget(widget, source, theme=Theme.AUTO):
    """按控件类系切片渲染（setStyleSheet/updateStyleSheet 统一入口）。

    文件类源（FluentStyleSheet/StyleSheetFile）走切片；CustomStyleSheet
    是逐控件动态属性，原样拼接在尾部（与 StyleSheetCompose 同序）。
    """
    if theme is None or theme == Theme.AUTO:
        theme = qconfig.theme
    parts = []
    for s in _iter_sheet_sources(source):
        if isinstance(s, CustomStyleSheet):
            parts.append(s.content(theme))
        else:
            parts.append(sliced_qss(s, widget, theme))
    text = "\n".join(p for p in parts if p)
    return renderQss(text, theme)


# ---------------------------------------------------------------------- #
# QSS 载体与样式表管理
# ---------------------------------------------------------------------- #
#: vt_fluent 自带 QSS 目录（common 结构 + light/dark 色板，见模块 docstring）
_QSS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_qss")


class StyleSheetBase:
    """QSS 载体基类（path/content/apply）。"""

    def path(self, theme=Theme.AUTO):
        raise NotImplementedError

    def content(self, theme=Theme.AUTO):
        return getStyleSheetFromFile(self.path(theme))

    def apply(self, widget: QWidget, theme=Theme.AUTO):
        setStyleSheet(widget, self, theme)


class FluentStyleSheet(StyleSheetBase, Enum):
    """Fluent 样式表句柄。

    ⚠ 与 qfluentwidgets 的差异（不损风格）：QSS 载体是**合并文件**
    （_qss/common.qss + light/dark.qss 全量），规则按类名作用域，
    故每个成员的 content() 都返回同一份合并 QSS——套到任一控件上，
    只有与其类名匹配的规则生效。成员名保留上游拼写作 API 兼容。
    """

    MENU = "menu"
    LABEL = "label"
    PIVOT = "pivot"
    BUTTON = "button"
    DIALOG = "dialog"
    SLIDER = "slider"
    INFO_BAR = "info_bar"
    SPIN_BOX = "spin_box"
    TAB_VIEW = "tab_view"
    TOOL_TIP = "tool_tip"
    CHECK_BOX = "check_box"
    COMBO_BOX = "combo_box"
    FLIP_VIEW = "flip_view"
    LINE_EDIT = "line_edit"
    LIST_VIEW = "list_view"
    TREE_VIEW = "tree_view"
    INFO_BADGE = "info_badge"
    PIPS_PAGER = "pips_pager"
    TABLE_VIEW = "table_view"
    CARD_WIDGET = "card_widget"
    TIME_PICKER = "time_picker"
    COLOR_DIALOG = "color_dialog"
    MEDIA_PLAYER = "media_player"
    SETTING_CARD = "setting_card"
    TEACHING_TIP = "teaching_tip"
    FLUENT_WINDOW = "fluent_window"
    SWITCH_BUTTON = "switch_button"
    MESSAGE_DIALOG = "message_dialog"
    STATE_TOOL_TIP = "state_tool_tip"
    CALENDAR_PICKER = "calendar_picker"
    FOLDER_LIST_DIALOG = "folder_list_dialog"
    SETTING_CARD_GROUP = "setting_card_group"
    EXPAND_SETTING_CARD = "expand_setting_card"
    NAVIGATION_INTERFACE = "navigation_interface"

    def path(self, theme=Theme.AUTO):
        return os.path.join(_QSS_DIR, "common.qss")

    def content(self, theme=Theme.AUTO):
        theme = qconfig.theme if theme == Theme.AUTO else theme
        parts = [getStyleSheetFromFile(os.path.join(_QSS_DIR, "common.qss"))]
        variant = "light.qss" if theme == Theme.LIGHT else "dark.qss"
        parts.append(getStyleSheetFromFile(os.path.join(_QSS_DIR, variant)))
        return "\n".join(p for p in parts if p)


class StyleSheetFile(StyleSheetBase):
    """文件 QSS 载体。"""

    def __init__(self, path: str):
        super().__init__()
        self.filePath = path

    def path(self, theme=Theme.AUTO):
        return self.filePath


class CustomStyleSheet(StyleSheetBase):
    """控件自定义 QSS（darkCustomQss / lightCustomQss 动态属性）。"""

    DARK_QSS_KEY = "darkCustomQss"
    LIGHT_QSS_KEY = "lightCustomQss"

    def __init__(self, widget: QWidget):
        super().__init__()
        self._widget = weakref.ref(widget)

    def path(self, theme=Theme.AUTO):
        return ""

    @property
    def widget(self):
        return self._widget()

    def __eq__(self, other):
        if not isinstance(other, CustomStyleSheet):
            return False
        return other.widget is self.widget

    def setCustomStyleSheet(self, lightQss: str, darkQss: str):
        self.setLightStyleSheet(lightQss)
        self.setDarkStyleSheet(darkQss)
        return self

    def setLightStyleSheet(self, qss: str):
        if self.widget:
            self.widget.setProperty(self.LIGHT_QSS_KEY, qss)
        return self

    def setDarkStyleSheet(self, qss: str):
        if self.widget:
            self.widget.setProperty(self.DARK_QSS_KEY, qss)
        return self

    def lightStyleSheet(self) -> str:
        if not self.widget:
            return ""
        return self.widget.property(self.LIGHT_QSS_KEY) or ""

    def darkStyleSheet(self) -> str:
        if not self.widget:
            return ""
        return self.widget.property(self.DARK_QSS_KEY) or ""

    def content(self, theme=Theme.AUTO) -> str:
        theme = qconfig.theme if theme == Theme.AUTO else theme
        if theme == Theme.LIGHT:
            return self.lightStyleSheet()
        return self.darkStyleSheet()


class StyleSheetCompose(StyleSheetBase):
    """多载体组合。"""

    def __init__(self, sources: List[StyleSheetBase]):
        super().__init__()
        self.sources = sources

    def content(self, theme=Theme.AUTO):
        return "\n".join(i.content(theme) for i in self.sources)

    def add(self, source: StyleSheetBase):
        if source is self or source in self.sources:
            return
        self.sources.append(source)

    def remove(self, source: StyleSheetBase):
        if source not in self.sources:
            return
        self.sources.remove(source)


class CustomStyleSheetWatcher(QObject):
    """监听 darkCustomQss/lightCustomQss 动态属性变化。"""

    def eventFilter(self, obj: QWidget, e: QEvent):
        if e.type() != QEvent.DynamicPropertyChange:
            return super().eventFilter(obj, e)
        name = QDynamicPropertyChangeEvent(e).propertyName().data().decode()
        if name in (CustomStyleSheet.LIGHT_QSS_KEY, CustomStyleSheet.DARK_QSS_KEY):
            addStyleSheet(obj, CustomStyleSheet(obj))
        return super().eventFilter(obj, e)


class DirtyStyleSheetWatcher(QObject):
    """脏标记懒刷新（lazy 主题切换时重绘即补样式表）。"""

    def eventFilter(self, obj: QWidget, e: QEvent):
        if e.type() != QEvent.Type.Paint or not obj.property("dirty-qss"):
            return super().eventFilter(obj, e)
        obj.setProperty("dirty-qss", False)
        if obj in styleSheetManager.widgets:
            try:
                obj.setStyleSheet(
                    render_for_widget(obj, styleSheetManager.source(obj)))
            except Exception:
                # 补刷失败：保留脏标记等下一次 Paint 重试，不把异常抛进
                # Qt 的事件系统（会打断该控件的后续事件处理）。
                obj.setProperty("dirty-qss", True)
        return super().eventFilter(obj, e)


class StyleSheetManager(QObject):
    """样式表注册表（weakref，控件析构自动摘除）。"""

    def __init__(self):
        self.widgets = weakref.WeakKeyDictionary()

    def register(self, source, widget: QWidget, reset=True):
        if isinstance(source, str):
            source = StyleSheetFile(source)
        if widget not in self.widgets:
            widget.destroyed.connect(lambda: self.deregister(widget))
            widget.installEventFilter(CustomStyleSheetWatcher(widget))
            widget.installEventFilter(DirtyStyleSheetWatcher(widget))
            self.widgets[widget] = StyleSheetCompose([source, CustomStyleSheet(widget)])
        if not reset:
            self.source(widget).add(source)
        else:
            self.widgets[widget] = StyleSheetCompose([source, CustomStyleSheet(widget)])

    def deregister(self, widget: QWidget):
        if widget not in self.widgets:
            return
        self.widgets.pop(widget)

    def items(self):
        return self.widgets.items()

    def source(self, widget: QWidget):
        return self.widgets.get(widget, StyleSheetCompose([]))


styleSheetManager = StyleSheetManager()


#: QSS 文件内容缓存（键 = (abspath, mtime_ns, size)；2026-10-20 性能优化）。
#: 改色/切档时每个注册控件都会来取同一份合并 QSS——不缓存意味着几百个
#: 控件 × 2 次读盘 + UTF-8 解码反复发生。mtime_ns 粒度天然支持开发期改
#: qss 即时生效；VT_QSS_NOCACHE=1 可整体关停（排障/基准对照）。
_QSS_FILE_CACHE = {}


def _qss_warn(file):
    """QSS 读取失败告警（仅 frozen 生效；VT_QSS_WARN=0 关闭）。

    v2.5.1 修复「安装版 UI 退化」时加：spec datas 漏收 _qss 曾让
    getStyleSheetFromFile 在安装版静默返回空表、自绘控件族整体失去
    皮肤且无任何日志。此后再出现同类回归，startup.log 会留下 [W] 行。
    """
    if not getattr(sys, 'frozen', False) or os.environ.get('VT_QSS_WARN', '1') == '0':
        return
    try:
        path = file if isinstance(file, str) else file.fileName()
        from core.shared.log import _append_log
        _append_log('startup.log',
                    '[W] QSS 读取失败（spec datas 漏收 _qss？）: %s' % path)
    except Exception:
        pass


def getStyleSheetFromFile(file: Union[str, QFile]):
    """读 QSS 文件内容（UTF-8；带 mtime 粒度的内容缓存）。"""
    if os.environ.get("VT_QSS_NOCACHE"):
        f = QFile(file) if not isinstance(file, QFile) else file
        if not f.open(QFile.ReadOnly):
            _qss_warn(file)
            return ""
        qss = str(f.readAll(), encoding="utf-8")
        f.close()
        return qss
    path = file if isinstance(file, str) else file.fileName()
    try:
        st = os.stat(path)
        key = (os.path.abspath(path), st.st_mtime_ns, st.st_size)
    except OSError:
        key = None
    if key is not None:
        hit = _QSS_FILE_CACHE.get(key)
        if hit is not None:
            return hit
    f = QFile(file) if not isinstance(file, QFile) else file
    if not f.open(QFile.ReadOnly):
        _qss_warn(file)
        return ""
    qss = str(f.readAll(), encoding="utf-8")
    f.close()
    if key is not None:
        _QSS_FILE_CACHE[key] = qss
    return qss


def getStyleSheet(source, theme=Theme.AUTO):
    """取渲染后的 QSS（模板 + 设计令牌替换后）。"""
    if isinstance(source, str):
        source = StyleSheetFile(source)
    return renderQss(source.content(theme), theme)


def setStyleSheet(widget: QWidget, source, theme=Theme.AUTO, register=True):
    """设控件样式表并按需注册（注册后主题切换自动重应用）。"""
    if register:
        styleSheetManager.register(source, widget)
    widget.setStyleSheet(render_for_widget(widget, source, theme))


def setCustomStyleSheet(widget: QWidget, lightQss: str, darkQss: str):
    """设控件自定义样式表（明/暗两套）。"""
    CustomStyleSheet(widget).setCustomStyleSheet(lightQss, darkQss)


def addStyleSheet(widget: QWidget, source, theme=Theme.AUTO, register=True):
    """在既有样式表上追加一段。"""
    if register:
        styleSheetManager.register(source, widget, reset=False)
        qss = render_for_widget(widget, styleSheetManager.source(widget), theme)
    else:
        qss = widget.styleSheet() + "\n" + render_for_widget(widget, source, theme)
    if qss.rstrip() != widget.styleSheet().rstrip():
        widget.setStyleSheet(qss)


#: app 级 QSS（原生顶层控件兜底：QToolTip/QMenu/QMessageBox）。
#: 这些是独立的顶层窗口，不在任何业务控件的样式表作用子树内，
#: 只能套在 QApplication 上才生效（见 applyAppStyleSheet）。
_APP_QSS_FILE = os.path.join(_QSS_DIR, "app.qss")


def applyAppStyleSheet(app: QApplication, theme=Theme.AUTO):
    """把原生顶层控件兜底 QSS 套到 QApplication（并注册进管理器）。

    覆盖：QToolTip（全局工具提示——宿主 27 处 setToolTip 的观感统一，
    深色主题下不再是白底黑字）、原生 QMenu/QMessageBox 兜底。
    注册进 styleSheetManager 后，主题/主题色切换时自动重应用。
    """
    setStyleSheet(app, StyleSheetFile(_APP_QSS_FILE), theme)


def updateStyleSheet(lazy=False):
    """主题切换后重应用全部已注册控件的样式表。

    2026-10-20 性能优化：渲染结果与组件文本都相同就不再 setStyleSheet（Qt 的
    setStyleSheet 会触发重新解析 + unpolish/polish 级联，同值调用纯属
    浪费）。配合 renderQss memo，一轮全量更新的 Python 侧成本从
    「控件数 × (读盘 + 29KB 替换)」降为「1 次替换 + 控件数次字符串比较」。
    """
    removes = []
    for widget, file in list(styleSheetManager.items()):
        try:
            if not isinstance(widget, QWidget):
                # app.qss 挂在 QApplication 上：**不随主题切换重设**——一次
                # app 级 setStyleSheet 会触发全应用 re-polish（实测 3~13s，
                # 与内容大小无关）。其规则已由 ui_theme 的逐控件表覆盖。
                continue
            # ⚠ QApplication（app.qss 的载体）没有 visibleRegion()，lazy 判定
            # 必须先确认是 QWidget——否则 AttributeError 会打断整个循环
            # （只有 RuntimeError 被捕获），导致部分控件漏刷（2026-10-20 修）。
            invisible = (lazy and isinstance(widget, QWidget)
                         and widget.visibleRegion().isNull())
            if not invisible:
                new = render_for_widget(widget, file, qconfig.theme)
                if new != widget.styleSheet():
                    widget.setStyleSheet(new)
            else:
                # ⚠ 不要再 register(file, widget)：控件本就来自注册表，而
                # register 的 reset 语义会把旧 compose 再包一层——每切一次
                # 档套娃深一层（2026-10-20 实测：嵌套后取不到 path、切片
                # 回退全量、join 成本累积，切档 43s→17s 的主要残余来源）。
                # 打脏标记即可：DirtyStyleSheetWatcher 首绘前会用现有
                # styleSheetManager.source(obj) 补齐。
                widget.setProperty("dirty-qss", True)
                # 必须主动排一次重绘（2026-10-20 复现实锤）：Qt 的绘制缓存
                # 在「外观无变化」时直接 blit 后备存储、不发 Paint——隐藏页
                # /滚动区外控件切档后因此永远等不到 DirtyStyleSheetWatcher
                # 的补齐（用户症状：「切主题后颜色不统一，鼠标点一下才好」，
                # 实测切档后 670/705 个注册控件停旧档、切页 pump 无补救）。
                # update() 让 Qt 标记需重绘：可见控件下帧即 Paint，隐藏控件
                # 到显示时补绘 → watcher 在首绘前把新档 QSS 补上。
                widget.update()
        except Exception:
            # 单控件渲染/设置失败不中断全局刷新（曾只捕 RuntimeError：
            # 一个坏控件（如 render 抛 ValueError）会让后续控件既没刷新
            # 也没打 dirty 标记，只能等一次偶然的鼠标交互才补救——
            # 2026-10-20 复现：注入异常后 setTheme 直接穿透到调用方）。
            removes.append(widget)
    for widget in removes:
        styleSheetManager.deregister(widget)


def setTheme(themeMode: Theme, save=False, lazy=False):
    """设主题档（不落盘除非 save=True）。"""
    qconfig.set(qconfig.themeMode, themeMode, save)
    updateStyleSheet(lazy)
    qconfig.themeChangedFinished.emit()


def setThemeColor(color, save=False, lazy=False):
    """设主题色（QColor/全局色/字符串均可）。"""
    color = QColor(color)
    qconfig.set(qconfig.themeColor, color, save=save)
    updateStyleSheet(lazy)


def repolish(widget: QWidget):
    """动态属性变更后重算 QSS（动态属性不会自动触发重算）。

    替代 setStyle(QApplication.style())：后者会把控件的 style 指针替换成
    app 的 QStyleSheetStyle，主题/全局样式重建后属性选择器规则可能失效
    （按钮 hasIcon 的 36px 图标位就是这么丢的）。
    """
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.updateGeometry()
    widget.update()


def updateDynamicStyle(widget: QWidget):
    """原生控件样式刷新（Win + Qt≥6.8 用 windowsvista，其余回默认）。"""
    if sys.platform != "win32" or QT_VERSION < (6, 8, 0):
        widget.setStyle(QApplication.style())
    else:
        widget.setStyle(QStyleFactory.create("windowsvista"))


# ---------------------------------------------------------------------- #
# 字体（对应 qfluentwidgets.common.font）
# ---------------------------------------------------------------------- #
def setFontFamilies(families: List[str], save=False):
    """设全控件字体族清单。"""
    qconfig.set(qconfig.fontFamilies, families, save)


def fontFamilies() -> List[str]:
    """取全控件字体族清单（副本）。"""
    return qconfig.get(qconfig.fontFamilies).copy()


def getFont(fontSize=14, weight=QFont.Normal):
    """按字体族清单造 QFont（像素字号）。

    weight 收 QFont.Weight 或等值 int——Qt 6.12 起 setWeight 只认枚举，
    上游直接把调用方给的 int 透传会 TypeError，这里做兼容 coercion。
    """
    font = QFont()
    font.setFamilies(qconfig.get(qconfig.fontFamilies))
    font.setPixelSize(fontSize)
    if not isinstance(weight, QFont.Weight):
        weight = QFont.Weight(int(weight))
    font.setWeight(weight)
    return font


def setFont(widget: QWidget, fontSize=14, weight=QFont.Normal):
    """设控件字体（像素字号 + 字体族清单）。"""
    widget.setFont(getFont(fontSize, weight))


# ---------------------------------------------------------------------- #
# 颜色辅助（对应 qfluentwidgets.common.color 的使用面子集）
# ---------------------------------------------------------------------- #
class FluentSystemColor(Enum):
    """系统语义色（前景 light/dark 两档；B1 用于输入框错误态描边）。"""

    CRITICAL_FOREGROUND = ("#c42b1c", "#ff99a4")

    def color(self):
        from ._theme import isDarkTheme
        return QColor(self.value[1] if isDarkTheme() else self.value[0])


def validColor(color: QColor, default: QColor) -> QColor:
    """颜色非法（空 QColor）时回落默认值。"""
    return color if color.isValid() else default


def fallbackThemeColor(color: QColor) -> QColor:
    """空颜色回落主题色（PRIMARY）。"""
    return color if color.isValid() else themeColor()


def autoFallbackThemeColor(light: QColor, dark: QColor) -> QColor:
    """按主题取 light/dark 之一，空值回落主题色。"""
    color = dark if isDarkTheme() else light
    return fallbackThemeColor(color)
