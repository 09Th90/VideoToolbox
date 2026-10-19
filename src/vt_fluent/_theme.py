# -*- coding: utf-8 -*-
# @version 2.4.0
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

    themeMode = OptionsConfigItem(
        "QFluentWidgets", "ThemeMode", Theme.LIGHT, OptionsValidator(Theme),
        EnumSerializer(Theme))
    themeColor = ColorConfigItem("QFluentWidgets", "ThemeColor", "#009faa")
    fontFamilies = ConfigItem(
        "QFluentWidgets", "FontFamilies",
        ["Segoe UI", "Microsoft YaHei", "PingFang SC"])

    def __init__(self):
        super().__init__()
        self.file = Path("config/config.json")
        self._theme = Theme.LIGHT
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
    """
    if theme is None or theme == Theme.AUTO:
        theme = qconfig.theme
    template = QssTemplate(qss)
    mappings = {c.value: c.name() for c in ThemeColor._member_map_.values()}
    mappings["FontFamilies"] = ",".join(
        [f"'{i}'" for i in qconfig.get(qconfig.fontFamilies)])
    mappings.update(designTokens(theme))
    return template.safe_substitute(mappings)


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
            obj.setStyleSheet(getStyleSheet(styleSheetManager.source(obj)))
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


def getStyleSheetFromFile(file: Union[str, QFile]):
    """读 QSS 文件内容（UTF-8）。"""
    f = QFile(file) if not isinstance(file, QFile) else file
    if not f.open(QFile.ReadOnly):
        return ""
    qss = str(f.readAll(), encoding="utf-8")
    f.close()
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
    widget.setStyleSheet(getStyleSheet(source, theme))


def setCustomStyleSheet(widget: QWidget, lightQss: str, darkQss: str):
    """设控件自定义样式表（明/暗两套）。"""
    CustomStyleSheet(widget).setCustomStyleSheet(lightQss, darkQss)


def addStyleSheet(widget: QWidget, source, theme=Theme.AUTO, register=True):
    """在既有样式表上追加一段。"""
    if register:
        styleSheetManager.register(source, widget, reset=False)
        qss = getStyleSheet(styleSheetManager.source(widget), theme)
    else:
        qss = widget.styleSheet() + "\n" + getStyleSheet(source, theme)
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
    """主题切换后重应用全部已注册控件的样式表。"""
    removes = []
    for widget, file in list(styleSheetManager.items()):
        try:
            if not (lazy and widget.visibleRegion().isNull()):
                setStyleSheet(widget, file, qconfig.theme)
            else:
                styleSheetManager.register(file, widget)
                widget.setProperty("dirty-qss", True)
        except RuntimeError:
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
