# -*- coding: utf-8 -*-
# @version 3.1.4
"""功能注册表 —— 视频工具箱插件化核心（纯标准库，禁 Qt / 禁第三方）。

契约
----
* ``features/`` 下每个**非下划线**子包 = 一个功能；包内 ``feature.py`` 必须
  暴露 ``FEATURE: FeatureSpec``，且 ``spec.id`` 与包名一致。
* ``discover()`` 只 import 各包的 feature.py（清单）；后端模块在
  ``ensure()`` / ``service()`` 首次使用时才惰性 import。任何单包损坏/缺失
  只记录 reason，**绝不外抛**——「缺少某个功能不影响程序正常启动运行」。
* 适配器（feature.py / cli.py）模块级禁 Qt 与重依赖；GUI 页面放 page.py，
  由 ``gui.builder`` 指向的工厂函数惰性构造（阶段②接线）。
* 功能间互相调用一律经 ``service(fid, name)``，禁止跨功能直接 import。

新增功能：复制 ``features/_template/`` 为 ``features/<name>/``，改清单即可
（打包侧 collect_submodules / iss recursesubdirs 自动收集，无需手工登记）。
"""
from __future__ import annotations

import importlib
import importlib.util
import pkgutil
from dataclasses import dataclass, field

__all__ = ["CliCommand", "GuiSpec", "FeatureSpec", "FeatureStatus",
           "FeatureUnavailable", "FeatureRegistry", "resolve"]


class FeatureUnavailable(RuntimeError):
    """功能不可用（缺失 / 损坏 / 依赖未装）。携带可操作指引，调用方按需捕获。"""

    def __init__(self, fid: str, reason: str, title: str = ""):
        self.fid = fid
        self.reason = reason
        label = "功能「%s」" % (title or fid)
        super().__init__("%s不可用：%s。其他功能不受影响；"
                         "请检查对应模块及其依赖是否就位。" % (label, reason))


@dataclass(frozen=True)
class CliCommand:
    """一个 CLI 子命令的声明。

    setup 指向 ``func(subparsers)``：负责 add_parser / 参数 / set_defaults(fn=…)。
    passthrough=True 的子命令（calibrate/stabilize/audit）由入口 main()
    先截下原始 argv 再透传，与 argparse 解耦。
    """
    name: str
    help: str = ""
    setup: str = ""            # "module:func"
    passthrough: bool = False


@dataclass(frozen=True)
class GuiSpec:
    """一个功能页的挂载声明（阶段② MainWindow 注册表驱动挂载时消费）。

    builder 指向 ``func(app) -> QWidget``；position: top=主列表 / bottom=导航底部；
    messages 为该页订阅的消息前缀（bus 契约，页面拆出时逐个认领）；
    icon 为 vt_fluent.FluentIcon 的属性名；attr 为 MainWindow 上的属性名
    （兼容旧代码 self.download_page 等引用）；lazy=False 表示常驻真身
    （如字幕工作台，启动期即构造）；sep_before=True 在该页前插导航分隔线。
    """
    nav: str
    builder: str               # "module:func"
    position: str = "top"
    order: int = 100
    object_name: str = ""
    messages: tuple = ()
    icon: str = ""
    attr: str = ""
    lazy: bool = True
    sep_before: bool = False


@dataclass(frozen=True)
class FeatureSpec:
    """功能清单。feature.py 里 ``FEATURE = FeatureSpec(...)`` 即完成注册。

    backend   主后端模块（惰性 import；空=清单级功能，如 status）
    requires  外部依赖键（ffmpeg/ffprobe/ytdlp/asr/llm/network/qt/mpv/node/uia），
              仅用于 status 展示与引导，不做硬阻断
    services  对外服务表 name -> "module:attr"（attr 支持点链 Class.method）
    check     轻量无副作用探针 "module:func" -> (ok, detail)；
              空则默认 find_spec(backend)（不 import、零副作用）
    """
    id: str
    title: str
    summary: str = ""
    backend: str = ""
    requires: tuple = ()
    services: dict = field(default_factory=dict)
    cli: tuple = ()            # CliCommand…
    gui: GuiSpec | None = None
    check: str = ""
    order: int = 100


@dataclass
class FeatureStatus:
    """发现结果。state: ok=清单已加载；error=发现失败（reason 带原因）。"""
    id: str
    title: str
    state: str
    reason: str = ""
    spec: FeatureSpec | None = None


def resolve(path: str):
    """把 ``"module:attr"`` 解析成对象（attr 支持点链，如 Class.method）。

    只给模块名（无冒号）时返回模块本身。惰性 import 的唯一入口。
    """
    mod_name, _, attr = path.partition(":")
    mod = importlib.import_module(mod_name)
    if not attr:
        return mod
    obj = mod
    for part in attr.split("."):
        obj = getattr(obj, part)
    return obj


class FeatureRegistry:
    """功能注册表：发现 / 惰性加载 / 错误隔离 / 服务解析。

    所有查询方法自带 discover()（幂等）；任何单包异常都被隔离成
    statuses() 里的一条 error 记录，不会传染其它功能，更不会炸启动。
    """

    def __init__(self, package: str = "features"):
        self.package = package
        self._specs: dict = {}
        self._errors: dict = {}      # 包名 -> reason
        self._backends: dict = {}    # fid -> 已 import 的后端模块
        self._discovered = False

    # ---------------- 发现 ----------------
    def discover(self, force: bool = False) -> "FeatureRegistry":
        if self._discovered and not force:
            return self
        self._discovered = True
        self._specs.clear()
        self._errors.clear()
        self._backends.clear()
        try:
            pkg = importlib.import_module(self.package)
            paths = list(getattr(pkg, "__path__", []))
        except Exception as e:  # noqa: BLE001 —— 包本体坏了也要能启动
            self._errors["<%s>" % self.package] = "%s: %s" % (type(e).__name__, e)
            return self
        for mi in pkgutil.iter_modules(paths):
            if not mi.ispkg or mi.name.startswith("_"):
                continue
            try:
                mod = importlib.import_module("%s.%s.feature"
                                              % (self.package, mi.name))
                spec = getattr(mod, "FEATURE", None)
                if not isinstance(spec, FeatureSpec):
                    raise TypeError("feature.py 必须暴露 FEATURE: FeatureSpec")
                if spec.id != mi.name:
                    raise ValueError("FEATURE.id=%r 与包名 %r 不一致"
                                     % (spec.id, mi.name))
                if spec.id in self._specs:
                    raise ValueError("功能 id 重复：%s" % spec.id)
                self._specs[spec.id] = spec
            except Exception as e:  # noqa: BLE001 —— 单包损坏只记录，不传染
                self._errors[mi.name] = "%s: %s" % (type(e).__name__, e)
        return self

    # ---------------- 查询 ----------------
    def specs(self) -> dict:
        self.discover()
        return dict(self._specs)

    def errors(self) -> dict:
        self.discover()
        return dict(self._errors)

    def get(self, fid: str) -> FeatureSpec:
        self.discover()
        if fid not in self._specs:
            raise FeatureUnavailable(fid, self._errors.get(fid, "功能未注册"))
        return self._specs[fid]

    def available(self, fid: str) -> bool:
        """清单级可用（discover 成功）。深度可用性见 probe()/ensure()。"""
        self.discover()
        return fid in self._specs

    def _ordered(self) -> list:
        return sorted(self._specs.values(), key=lambda s: (s.order, s.id))

    def statuses(self) -> list:
        self.discover()
        out = [FeatureStatus(id=s.id, title=s.title, state="ok", spec=s)
               for s in self._ordered()]
        for name, reason in sorted(self._errors.items()):
            out.append(FeatureStatus(id=name, title=name, state="error",
                                     reason=reason))
        return out

    def cli_commands(self) -> list:
        """[(fid, CliCommand)]，按功能 order 排序（决定 --help 列表顺序）。"""
        self.discover()
        return [(s.id, c) for s in self._ordered() for c in s.cli]

    def passthrough_names(self) -> list:
        return [c.name for _, c in self.cli_commands() if c.passthrough]

    def gui_specs(self) -> list:
        """[(fid, GuiSpec)]，按 gui.order 排序（阶段②挂载消费）。"""
        self.discover()
        items = [(s.id, s.gui) for s in self._specs.values() if s.gui]
        return sorted(items, key=lambda t: (t[1].order, t[0]))

    # ---------------- 惰性加载 / 服务 ----------------
    def ensure(self, fid: str):
        """惰性 import 后端模块（带缓存）。失败抛 FeatureUnavailable。"""
        spec = self.get(fid)
        if not spec.backend:
            return None
        if fid in self._backends:
            return self._backends[fid]
        try:
            mod = importlib.import_module(spec.backend)
        except Exception as e:  # noqa: BLE001
            raise FeatureUnavailable(
                fid, "后端模块 %s 加载失败（%s: %s）"
                % (spec.backend, type(e).__name__, e), spec.title) from e
        self._backends[fid] = mod
        return mod

    def service(self, fid: str, name: str):
        """取功能对外服务（惰性解析 "module:attr"）。缺失抛 FeatureUnavailable。"""
        spec = self.get(fid)
        target = (spec.services or {}).get(name)
        if not target:
            raise FeatureUnavailable(fid, "未声明服务 %s" % name, spec.title)
        try:
            return resolve(target)
        except Exception as e:  # noqa: BLE001
            raise FeatureUnavailable(
                fid, "服务 %s 解析失败（%s: %s）"
                % (name, type(e).__name__, e), spec.title) from e

    def probe(self, fid: str) -> tuple:
        """轻量可用性探针，返回 (ok, detail)。**零副作用、绝不抛异常**。

        默认 find_spec(backend)：只查模块在位性，不 import（避免拉起引擎树）；
        清单里声明了 check 的走自定义探针。真正的 import 失败在使用点由
        ensure()/service() 转成 FeatureUnavailable / JSON 错误信封。
        """
        try:
            spec = self.get(fid)
        except FeatureUnavailable as e:
            return False, e.reason
        try:
            if spec.check:
                ok, detail = resolve(spec.check)()
                return bool(ok), str(detail)
            if spec.backend:
                found = importlib.util.find_spec(spec.backend) is not None
                return found, (spec.backend if found
                               else "缺少模块 %s" % spec.backend)
            return True, "清单级功能"
        except Exception as e:  # noqa: BLE001
            return False, "%s: %s" % (type(e).__name__, e)