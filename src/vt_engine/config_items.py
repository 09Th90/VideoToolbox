# @version 2.5.1
"""设置项机制（自研，替代 qfluentwidgets 的 ConfigItem/ConfigSerializer/Validator）。

只实现本引擎用得到的兼容面：

* :class:`ConfigItem` / :class:`OptionsConfigItem` / :class:`RangeConfigItem`
  —— ``.value`` 读写语义（写=校验→纠正→落盘）；
* :class:`EnumSerializer` —— 枚举按 ``.value`` 存取（settings.json 实况）；
* 校验器 Bool / Range / Options / Folder，带 ``correct()`` 兜底。

为什么不直接依赖 qfluentwidgets：设置层必须在**无 Qt 环境**下可用
（自检子进程、无头 CLI、独立 worker），而 qconfig 的 load/set 语义与
Qt 信号深度耦合。引擎的 settings.json 本身是纯 JSON，无 Qt 依赖。
"""

from __future__ import annotations

from enum import Enum
from typing import Iterable, List, Optional

__all__ = [
    "ConfigSerializer",
    "EnumSerializer",
    "ConfigValidator",
    "BoolValidator",
    "RangeValidator",
    "OptionsValidator",
    "FolderValidator",
    "ConfigItem",
    "OptionsConfigItem",
    "RangeConfigItem",
]


class ConfigSerializer:
    """序列化器基类：Python 值 ↔ 文件存储值（默认恒等）。"""

    def serialize(self, value):
        return value

    def deserialize(self, value):
        return value


class EnumSerializer(ConfigSerializer):
    """枚举序列化：存 ``.value``、按值反构造。

    反构造失败（历史脏值/手改文件）返回 ``None``，由调用方落默认值——
    与引擎 OptionsValidator + EnumSerializer 的可观察行为一致。
    """

    def __init__(self, enum_cls: type):
        self.enum_cls = enum_cls

    def serialize(self, value):
        return getattr(value, "value", value)

    def deserialize(self, value):
        if isinstance(value, self.enum_cls):
            return value
        try:
            return self.enum_cls(value)
        except (ValueError, KeyError):
            return None


class ConfigValidator:
    """校验器基类：默认全部合法、不纠正。"""

    def validate(self, value) -> bool:
        return True

    def correct(self, value):
        return value


class BoolValidator(ConfigValidator):
    def validate(self, value) -> bool:
        return isinstance(value, bool)

    def correct(self, value):
        return bool(value)


class RangeValidator(ConfigValidator):
    """数值范围校验（越界钳回边界，与 qfluentwidgets 行为一致）。"""

    def __init__(self, min_value, max_value):
        self.min = min_value
        self.max = max_value

    def validate(self, value) -> bool:
        try:
            return self.min <= value <= self.max
        except TypeError:
            return False

    def correct(self, value):
        try:
            if value < self.min:
                return self.min
            if value > self.max:
                return self.max
        except TypeError:
            return self.min
        return value


class OptionsValidator(ConfigValidator):
    """枚举/选项列表校验。

    ``options`` 可为 Enum 类或可迭代对象。比较同时看**身份相等**与
    **字符串相等**（settings.json 里可能存 "1" 而选项是 1）。
    """

    def __init__(self, options):
        if isinstance(options, type) and issubclass(options, Enum):
            self.options: List = list(options)
        else:
            self.options = list(options)

    def validate(self, value) -> bool:
        for opt in self.options:
            if value == opt:
                return True
            if str(value) == str(getattr(opt, "value", opt)):
                return True
        return False

    def correct(self, value):
        if self.validate(value):
            return value
        return self.options[0] if self.options else value


class FolderValidator(ConfigValidator):
    """目录项校验：只要求是字符串（存在性不拦——建目录是运行期职责）。"""

    def validate(self, value) -> bool:
        return isinstance(value, str)

    def correct(self, value):
        return value if isinstance(value, str) else ""


class ConfigItem:
    """单个配置项。

    ``value`` 读返回内存值（反序列化后的 Python 对象）；写走
    :meth:`Config.set`（校验→纠正→内存→落盘），未挂到 Config 时
    （类定义期）仅纠正不落盘。
    """

    def __init__(self, group: str, name: str, default,
                 validator: Optional[ConfigValidator] = None,
                 serializer: Optional[ConfigSerializer] = None,
                 restart: bool = False):
        self.group = group
        self.name = name
        self.default = default
        self.validator = validator or ConfigValidator()
        self.serializer = serializer or ConfigSerializer()
        self.restart = restart
        self._value = default
        self._owner = None  # type: Optional[object]

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, v):
        if self._owner is None:
            self._value = self.validator.correct(v)
            return
        self._owner.set(self, v)

    @property
    def key(self) -> str:
        """``组名.键名``（诊断用）。"""
        return "%s.%s" % (self.group, self.name)

    def __repr__(self):
        return "<ConfigItem %s=%r>" % (self.key, self._value)


class OptionsConfigItem(ConfigItem):
    """枚举/选项类配置项。

    ``default`` 为枚举成员时自动挂 :class:`EnumSerializer`——settings.json
    里存的是 ``.value`` 字符串，读取时按值反构造回枚举。
    """

    def __init__(self, group, name, default, validator=None,
                 serializer=None, restart=False):
        if serializer is None and isinstance(default, Enum):
            serializer = EnumSerializer(type(default))
        if validator is None:
            validator = OptionsValidator(type(default)) \
                if isinstance(default, Enum) else OptionsValidator([])
        super().__init__(group, name, default, validator, serializer, restart)


class RangeConfigItem(ConfigItem):
    """数值范围配置项（``range`` 为 ``(min, max)``）。"""

    def __init__(self, group, name, default, range_,
                 restart=False):
        validator = RangeValidator(range_[0], range_[1])
        super().__init__(group, name, default, validator, None, restart)
