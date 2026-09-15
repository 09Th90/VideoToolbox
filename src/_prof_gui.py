# -*- coding: utf-8 -*-
# @version 1.12.2
"""真实 GUI 启动/进入字幕处理页的耗时剖析（不联网、不写自检文件）。

用法：
    tools\\python\\python.exe src\\_prof_gui.py plain [点击时刻秒]
    tools\\python\\python.exe src\\_prof_gui.py lazy  [点击时刻秒]

lazy = 先给 diskcache.Cache 装上延迟代理，再让引擎导入缓存模块。
"""
import builtins
import importlib
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

MODE = (sys.argv[1] if len(sys.argv) > 1 else "plain").lower()
CLICK_AT = float(sys.argv[2]) if len(sys.argv) > 2 else 1.5

T0 = time.perf_counter()


def mark(msg):
    print(f"[prof] {time.perf_counter() - T0:7.3f}s {msg}", flush=True)


# ---- 可选：diskcache 延迟代理 --------------------------------------------
_ORIG_CACHE = None


class _LazyCache:
    def __init__(self, directory, **kwargs):
        self.__dict__["_lc_args"] = (directory,)
        self.__dict__["_lc_kw"] = kwargs
        self.__dict__["_lc_real"] = None

    def _real(self):
        r = self.__dict__["_lc_real"]
        if r is None:
            r = self.__dict__["_lc_real"] = _ORIG_CACHE(
                *self.__dict__["_lc_args"], **self.__dict__["_lc_kw"])
        return r

    def __getattr__(self, name):
        return getattr(self._real(), name)

    def __len__(self):
        return len(self._real())

    def __contains__(self, k):
        return k in self._real()

    def __getitem__(self, k):
        return self._real()[k]

    def __setitem__(self, k, v):
        self._real()[k] = v

    def __delitem__(self, k):
        del self._real()[k]

    def __iter__(self):
        return iter(self._real())

    def memoize(self, **kwargs):
        def deco(func):
            holder = {}

            def wrapper(*a, **kw):
                m = holder.get("m")
                if m is None:
                    m = holder["m"] = self._real().memoize(**kwargs)(func)
                return m(*a, **kw)
            wrapper.__name__ = getattr(func, "__name__", "wrapper")
            return wrapper
        return deco


if MODE in ("lazy", "lazy+warm"):
    import diskcache
    _ORIG_CACHE = diskcache.Cache
    diskcache.Cache = _LazyCache
    mark("已装 diskcache 延迟代理")

# ---- 导入耗时埋点（覆盖 prewarm 线程与主线程） -----------------------------
_oi = builtins.__import__


def _imp(name, globals=None, locals=None, fromlist=(), level=0):
    if name.startswith("videocaptioner") or name == "qfluentwidgets":
        t = time.perf_counter()
        r = _oi(name, globals, locals, fromlist, level)
        dt = time.perf_counter() - t
        if dt > 0.05:
            mark(f"import {name} ({dt:.3f}s)")
        return r
    return _oi(name, globals, locals, fromlist, level)


builtins.__import__ = _imp

import video_toolbox as engine  # noqa: E402

mark("engine 导入完成")


def main():
    engine.prepare_runtime_env()
    mark("prepare_runtime_env 完成")
    import video_toolbox_qt as g
    g.configure_qt_plugins()
    from PyQt5.QtCore import Qt, QTimer
    from PyQt5.QtGui import QFont, QGuiApplication
    from PyQt5.QtWidgets import QApplication
    from qfluentwidgets import Theme, setTheme, setThemeColor

    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    try:
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    except Exception:
        pass
    app = QApplication(sys.argv)
    setTheme(Theme.DARK)
    setThemeColor("#2F8D63")
    app.setFont(QFont("Microsoft YaHei UI", 9))

    # 关键方法埋点
    for cls, name, label in (
            (g.SubtitlePage, "prewarm", "SubtitlePage.prewarm 调用"),
            (g.SubtitlePage, "_build_now", "SubtitlePage._build_now"),
            (g.SubtitlePage, "_build_engine", "  └ _build_engine(HomeInterface)"),
            (g.SettingsPage, "_ensure_engine_setting", "SettingsPage 引擎设置懒加载"),
    ):
        orig = getattr(cls, name)

        def mk(orig=orig, label=label):
            def f(self, *a, **kw):
                t = time.perf_counter()
                r = orig(self, *a, **kw)
                mark(f"{label} = {time.perf_counter() - t:.3f}s")
                return r
            return f
        setattr(cls, name, mk())

    _obp = engine.engine_ui_brand_patch

    def bp():
        t = time.perf_counter()
        r = _obp()
        mark(f"engine_ui_brand_patch = {time.perf_counter() - t:.3f}s "
             f"(线程 {__import__('threading').current_thread().name})")
        return r
    engine.engine_ui_brand_patch = bp

    if MODE in ("warm", "lazy+warm"):
        def warm_fonts():
            from PyQt5.QtGui import QFont
            from PyQt5.QtWidgets import QLabel
            from qfluentwidgets.common.font import getFont
            keep = []
            for size in (12, 14, 16, 18, 20, 24):
                for weight in (QFont.Normal, QFont.DemiBold):
                    lbl = QLabel("字幕校准样例文本 ABCDEFG abcdefg 0123456789")
                    lbl.setFont(getFont(size, weight))
                    lbl.sizeHint()
                    lbl.adjustSize()
                    keep.append(lbl)
            return keep
        t = time.perf_counter()
        _KEEP = warm_fonts()   # noqa: F841
        mark(f"字体度量预热 = {time.perf_counter() - t:.3f}s")

    window = g.MainWindow([])
    mark("MainWindow 构建完成")
    window.fit_to_screen()
    window.show()
    mark("窗口显示")

    def click():
        t = time.perf_counter()
        window.switchTo(window.subtitle_page)
        mark(f"→ 进入字幕处理页阻塞 {time.perf_counter() - t:.3f}s")
        mark(f"   state={window.subtitle_page.state_label.text()}")

    QTimer.singleShot(int(CLICK_AT * 1000), click)
    QTimer.singleShot(int((CLICK_AT + 6) * 1000), app.quit)
    app.exec_()
    mark("退出")
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
