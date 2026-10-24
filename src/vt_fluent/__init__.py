# -*- coding: utf-8 -*-
# @version 2.6.0
"""vt_fluent——自研 Fluent 风格 QSS 主题库（替代 qfluentwidgets 的迁移目标）。

结构（对应《核心拆分与QSS主题迁移方案.md》§3.2）：
    _theme.py      主题引擎（Theme/qconfig/ConfigItem/ThemeColor/样式表管理）
    _qss/          合并 QSS（common 结构 + light/dark 色板，逐值对照上游）
    _icon.py       图标引擎（FluentIcon 全成员 + 主题感知渲染 + Action）
    _buttons.py    B1 步（pending）
    _inputs.py     B1 步（pending）
    _display.py    B1 步（pending）
    _feedback.py   B2 步（pending）
    _menu.py       B2 步（pending）
    _setting.py    B2 步（pending）
    _window.py     B3 步（pending）

**pending 桩约定**：__all__ 列全迁移契约面（parity 测试的全部 71 符号）。
未到施工步的控件族以桩导出——import 成功（契约面不塌），实例化抛
NotImplementedError 并指明所属 B 步。切换 src/ 某个文件的 import 之前，
其用到的控件族必须已为真实现（B4 逐文件切换纪律）。
"""

from enum import Enum

# ---------------------------------------------------------------------- #
# 纯常量枚举（先于子模块导入定义：_feedback/_window 模块级要用，
# 放到后面会触发循环导入）
# ---------------------------------------------------------------------- #
class NavigationItemPosition(Enum):
    """导航项位置（与 qfluentwidgets 逐名同值）。"""

    TOP = 0
    SCROLL = 1
    BOTTOM = 2


class InfoBarPosition(Enum):
    """信息条位置（与 qfluentwidgets 逐名同值）。"""

    TOP = 0
    BOTTOM = 1
    TOP_LEFT = 2
    TOP_RIGHT = 3
    BOTTOM_LEFT = 4
    BOTTOM_RIGHT = 5
    NONE = 6



from ._theme import (Theme, QConfig, qconfig, ConfigItem, ConfigValidator,
                     RangeValidator, OptionsValidator, BoolValidator,
                     FolderValidator, FolderListValidator, ColorValidator,
                     ConfigSerializer, EnumSerializer, ColorSerializer,
                     RangeConfigItem, OptionsConfigItem, ColorConfigItem,
                     ThemeColor, QssTemplate, applyThemeColor, renderQss,
                     StyleSheetBase, StyleSheetFile, StyleSheetCompose,
                     CustomStyleSheet, CustomStyleSheetWatcher,
                     DirtyStyleSheetWatcher, StyleSheetManager,
                     styleSheetManager, FluentStyleSheet, getStyleSheetFromFile,
                     getStyleSheet, setStyleSheet, setCustomStyleSheet,
                     addStyleSheet, updateStyleSheet, setTheme, toggleTheme,
                     applyAppStyleSheet, DESIGN_TOKENS, designTokens,
                     setThemeColor, themeColor, theme, isDarkTheme,
                     isDarkThemeMode, updateDynamicStyle, setFontFamilies,
                     fontFamilies, getFont, setFont, QT_VERSION)
from ._icon import (FluentIcon, FluentIconBase, FluentIconEngine, SvgIconEngine,
                    Icon, Action, toQIcon, getIconColor)
from ._buttons import (PushButton, PrimaryPushButton, ToolButton,
                      HyperlinkButton, PillPushButton,
                      TransparentDropDownPushButton, RadioButton)
from ._inputs import (LineEdit, PasswordLineEdit, TextEdit, PlainTextEdit,
                     ComboBox, EditableComboBox, SpinBox, CompactSpinBox,
                     SpinBoxBase, CheckBox, SwitchButton, Slider)
from ._display import (BodyLabel, CaptionLabel, StrongBodyLabel,
                      SubtitleLabel, TitleLabel, CardWidget, SimpleCardWidget,
                      ElevatedCardWidget, ScrollArea, SegmentedWidget,
                      ProgressBar, ProgressRing, ListWidget, TableWidget,
                      TableView)
from ._menu import RoundMenu, CommandBar, MenuAnimationType
from ._feedback import (MaskDialogBase, MessageBox, MessageBoxBase, InfoBar,
                        InfoBarIcon)
from ._setting import (SettingCard, SettingCardGroup, ExpandLayout,
                       ComboBoxSettingCard, OptionsSettingCard,
                       SwitchSettingCard, RangeSettingCard, PushSettingCard,
                       PrimaryPushSettingCard, CustomColorSettingCard,
                       HyperlinkCard)
from ._window import (FluentWindow, NavigationWidget, NavigationInterface,
                      FluentTitleBar)

__version__ = "2.3.1"


# ---------------------------------------------------------------------- #
# pending 桩（B1/B2/B3 施工步）
# ---------------------------------------------------------------------- #
def _make_pending(name, step):
    """造 pending 桩类：可导入，实例化抛指明 B 步的 NotImplementedError。"""

    def __init__(self, *args, **kwargs):
        raise NotImplementedError(
            "vt_fluent.%s 尚未实现（迁移计划 B%s 步）。"
            "把 src/ 文件切到 vt_fluent 之前，请先完成该控件族的"
            " parity 与黄金验收。" % (name, step))

    cls = type(name, (), {"__init__": __init__})
    cls.__doc__ = "vt_fluent pending 桩（B%s 步实现）。" % step
    return cls


#: (符号名, 所属 B 步)
_PENDING = [
    # B1/B2/B3 已全部落地（2026-10-18）。本机制保留：后续新增契约符号若需
    # 分步实现，按 ("Name", 步号) 登记即可，import 可用、实例化报错。
]

for _name, _step in _PENDING:
    globals()[_name] = _make_pending(_name, _step)

#: 迁移契约面：parity 测试（_selftest_qss_migration）的全部 71 符号 +
#: 主题/图标层的公开扩展。只许收缩不许新增（新增 = 该测试回归 FAIL）。
__all__ = [
    # 主题引擎
    "Theme", "QConfig", "qconfig", "ConfigItem", "ConfigValidator",
    "RangeValidator", "OptionsValidator", "BoolValidator", "FolderValidator",
    "FolderListValidator", "ColorValidator", "ConfigSerializer",
    "EnumSerializer", "ColorSerializer", "RangeConfigItem",
    "OptionsConfigItem", "ColorConfigItem", "ThemeColor", "QssTemplate",
    "applyThemeColor", "renderQss", "StyleSheetBase", "StyleSheetFile",
    "StyleSheetCompose", "CustomStyleSheet", "CustomStyleSheetWatcher",
    "DirtyStyleSheetWatcher", "StyleSheetManager", "styleSheetManager",
    "FluentStyleSheet", "getStyleSheetFromFile", "getStyleSheet",
    "setStyleSheet", "setCustomStyleSheet", "addStyleSheet",
    "applyAppStyleSheet", "DESIGN_TOKENS", "designTokens",
    "updateStyleSheet", "setTheme", "toggleTheme", "setThemeColor",
    "themeColor", "theme", "isDarkTheme", "isDarkThemeMode",
    "updateDynamicStyle", "setFontFamilies", "fontFamilies", "getFont",
    "setFont", "QT_VERSION",
    # 图标引擎
    "FluentIcon", "FluentIconBase", "FluentIconEngine", "SvgIconEngine",
    "Icon", "Action", "toQIcon", "getIconColor",
    # 常量枚举
    "NavigationItemPosition", "InfoBarPosition",
    # B1 控件族（pending）
    "PushButton", "PrimaryPushButton", "ToolButton", "HyperlinkButton",
    "PillPushButton", "TransparentDropDownPushButton", "LineEdit",
    "PasswordLineEdit", "TextEdit", "PlainTextEdit", "ComboBox",
    "EditableComboBox", "SpinBox", "CompactSpinBox", "SpinBoxBase",
    "CheckBox", "RadioButton", "SwitchButton", "Slider", "BodyLabel",
    "CaptionLabel", "StrongBodyLabel", "SubtitleLabel", "TitleLabel",
    "CardWidget", "SimpleCardWidget", "ElevatedCardWidget", "ScrollArea",
    "SegmentedWidget", "ProgressBar", "ProgressRing", "ListWidget",
    "TableWidget", "TableView",
    # B2 控件族（pending）
    "MaskDialogBase", "MessageBox", "MessageBoxBase", "InfoBar", "RoundMenu",
    "CommandBar", "SettingCard", "SettingCardGroup", "ExpandLayout",
    "ComboBoxSettingCard", "OptionsSettingCard", "SwitchSettingCard",
    "RangeSettingCard", "PushSettingCard", "PrimaryPushSettingCard",
    "CustomColorSettingCard", "HyperlinkCard",
    # B3 控件族（pending）
    "FluentWindow", "NavigationWidget",
    # 包元信息
    "__version__",
]
