# -*- coding: utf-8 -*-
# @version 3.1.1
"""启动诊断 / 崩溃守卫 / 启动期设施（原 video_toolbox_qt.py 同名代码，逐字下沉）。

⚠ 模块级只 import 标准库 + engine 门面；Qt / vt_fluent 一律函数体内导入——
本模块可能在 PySide6 之前被引用（_process_age_seconds），不得提前拉起 Qt。
"""
import os
import sys
import threading
import traceback
from datetime import datetime

import video_toolbox as engine


def _process_age_seconds():
    """进程真实存活秒数（Windows GetProcessTimes；失败返回 None）。

    ``_BOOT_T0`` 只能覆盖本文件导入之后的链路，解释器启动、site 初始化、
    onefile 解包都落在盲区。启动日志用这个值把「双击→窗口/首页」补全。
    """
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.GetProcessTimes.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
        ]
        k32.GetProcessTimes.restype = wintypes.BOOL
        k32.GetSystemTimeAsFileTime.argtypes = [
            ctypes.POINTER(wintypes.FILETIME)]
        created = wintypes.FILETIME()
        exited = wintypes.FILETIME()
        kernel = wintypes.FILETIME()
        user = wintypes.FILETIME()
        if not k32.GetProcessTimes(k32.GetCurrentProcess(),
                                   ctypes.byref(created),
                                   ctypes.byref(exited),
                                   ctypes.byref(kernel),
                                   ctypes.byref(user)):
            return None
        now = wintypes.FILETIME()
        k32.GetSystemTimeAsFileTime(ctypes.byref(now))
        c = (int(created.dwHighDateTime) << 32) | int(created.dwLowDateTime)
        n = (int(now.dwHighDateTime) << 32) | int(now.dwLowDateTime)
        return max(0.0, (n - c) / 10_000_000.0)
    except Exception:  # noqa: BLE001
        return None


def _perf_note(msg):
    """启动/预热耗时诊断：静默追加到 logs\\startup.log（best-effort）。

    用于日后排查「进入某页卡顿」——把各阶段耗时留痕，避免只能靠反复计时复现。
    v1.16.2：改走 engine._append_log（自动轮转，避免累积到几百 KB）；
    dedup=False —— 耗时时序本身就是数据，重复的「导航宽度」也要留全。
    """
    try:
        engine._append_log("startup.log", msg, dedup=False)
    except Exception:  # noqa: BLE001
        pass


# ========== 崩溃兜底：未捕获异常落盘 + 界面提示（v1.12.0） ==========
# 旧版 Qt5 绑定的默认行为：槽函数 / 回调里抛出未捕获异常时调用 qFatal() → 进程
# 立刻 abort（用户看到的就是「点一下按钮，程序没了」，且没有任何提示）。
# PySide6 起默认改为走 sys.excepthook（进程不再 abort，仅打 traceback，
# 2026-10-14 实测），但默认钩子不落盘、不弹提示；这里仍显式装钩子，保证：
#   · traceback 落盘 logs/crash.log（事后排查的唯一依据）；
#   · 主线程异常弹一次 InfoBar，后台线程异常仅记录（不打断工作）。
# 这类 bug 最常见的成因是漏定义名字（例如 duration=INFOBAR_DURATION_SUCCESS 却没定义），
# 静态检查见 src/check_names.py，自检里已加断言防回归。
CRASH_LOG = os.path.join(engine.LOGS_DIR, "crash.log")

#: faulthandler 状态（见 _install_faulthandler）。「fh」必须全局持有——
#: faulthandler.enable() 只记住底层 FILE*，Python 侧 file 对象被 GC 回收后
#: 句柄关闭，崩溃时静默写不出任何东西。
_FAULT_STATE = {"fh": None, "on": False}


def _crash_log_write(kind, exc_type, exc, tb, thread_name=""):
    """把 traceback 落盘 + 打到 stderr（best-effort，本身绝不抛）。"""
    try:
        os.makedirs(engine.LOGS_DIR, exist_ok=True)
        with open(CRASH_LOG, "a", encoding="utf-8") as f:
            f.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} [{kind}] "
                    f"线程={thread_name} =====\n")
            f.write("".join(traceback.format_exception(exc_type, exc, tb)))
    except Exception:
        pass
    try:
        traceback.print_exception(exc_type, exc, tb)
    except Exception:
        pass


def _crash_toast(title, text):
    """尽力在界面上提示一次；非主线程 / 无窗口时静默跳过。"""
    try:
        from PySide6.QtWidgets import QApplication
        from vt_fluent import InfoBar, InfoBarPosition
        if threading.current_thread() is not threading.main_thread():
            return
        app = QApplication.instance()
        if app is None:
            return
        win = app.activeWindow()
        if win is None:
            return
        InfoBar.error(title, text[:300], duration=6000,
                      position=InfoBarPosition.BOTTOM_RIGHT, parent=win)
    except Exception:
        pass


def _install_faulthandler():
    """原生崩溃（access violation / stack overflow）栈落盘。

    为什么必须有（2026-10-21）：`sys.excepthook` / `threading.excepthook` 只接
    **Python 层**异常。而 PySide6 里最常见的致命故障——C++ 对象已析构、Python
    侧仍持有引用；动画/定时器回调打到已删除的控件；跨线程碰 GUI——都以
    **Windows 原生崩溃**结束进程：用户看到「python 已停止运行」，而
    logs\\crash.log 里一行都没有，事后完全无从下手（本轮排查即卡在这里）。

    faulthandler 装的是 C 层 handler，段错误发生瞬间把**所有线程**的 Python
    栈写进文件（含崩溃线程），是唯一能拿到现场的通道。

    ⚠ 输出追加进**已有的** logs\\crash.log，不新建文件；VT_NO_FAULT=1 可关。
    """
    if _FAULT_STATE["on"] or os.environ.get("VT_NO_FAULT"):
        return False
    try:
        import faulthandler
        os.makedirs(engine.LOGS_DIR, exist_ok=True)
        # buffering=1（行缓冲）：崩溃瞬间的写入尽量不丢。
        fh = open(CRASH_LOG, "a", encoding="utf-8", buffering=1)
        fh.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} "
                 f"[faulthandler] 已启用（原生崩溃栈写在本段之后） =====\n")
        fh.flush()
        faulthandler.enable(file=fh, all_threads=True)
        # ⚠ 必须全局持有：enable() 只记住底层 FILE*，Python 侧 file 对象一旦被
        #   GC 回收，句柄随之关闭 → 崩溃时写不出任何东西，而且**不报错**。
        #   这是 faulthandler 最常见的静默失效方式。
        _FAULT_STATE["fh"] = fh
        _FAULT_STATE["on"] = True
        return True
    except Exception:  # noqa: BLE001 —— 诊断设施失败绝不能影响启动
        return False


def install_crash_guard():
    """装上未捕获异常钩子（main() 里、创建 QApplication 之前调用）。"""
    def _hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        _crash_log_write("主线程", exc_type, exc, tb,
                         threading.current_thread().name)
        _crash_toast("界面遇到一个错误（程序已继续运行）",
                     f"{exc_type.__name__}: {exc}（详情见 logs/crash.log）")

    def _thread_hook(args):
        if issubclass(args.exc_type, SystemExit):
            return
        _crash_log_write("后台线程", args.exc_type, args.exc_value,
                         args.exc_traceback,
                         getattr(getattr(args, "thread", None), "name", ""))

    sys.excepthook = _hook
    threading.excepthook = _thread_hook
    # 原生崩溃是另一条通道（Python 钩子抓不到），单独装。
    _install_faulthandler()


def configure_qt_plugins():
    """显式指定 Qt 平台插件目录（必须在创建 QApplication 之前调用）。

    内置 PySide6 不是用安装器装的，而是把 wheel 解包到 tools\\python 的
    site-packages —— Qt 按 sys.prefix 推算插件的默认逻辑在这种情况下找不到
    platforms/qwindows.dll，会直接报
    「no Qt platform plugin could be initialized」并弹模态框卡住进程。
    （PySide6 是扁平布局：插件就在 site-packages\\PySide6\\plugins，
    没有旧版 Qt5\\ 那一层中间目录。）
    忽略平台插件目录的探测在打包后由 PyInstaller 的钩子负责（它会把
    platforms/qwindows.dll 一起打进包里），此时若强行指向内置运行时的
    PySide6 反而可能因版本不一致而崩，故冻结模式下直接跳过。
    """
    if getattr(sys, "frozen", False):
        return ""
    for base in (engine.EMBEDDED_SITE_PACKAGES,
                 os.path.join(engine.TOOLS_DIR, "python", "Lib", "site-packages")):
        plugins = os.path.join(base, "PySide6", "plugins")
        if os.path.isdir(plugins):
            os.environ.setdefault("QT_QPA_PLATFORM_PLUGIN_PATH", plugins)
            os.environ.setdefault("QT_PLUGIN_PATH", plugins)
            return plugins
    return ""


def _apply_app_icon(app):
    """把应用图标挂到 ``QApplication`` 上（v2.1.0）。

    为什么挂 QApplication 而不是 MainWindow：
      · ``QApplication.setWindowIcon`` 是**默认图标**——之后创建的**所有**
        顶层窗口都继承它（主窗口、日志查看器、各对话框，以及引擎回退路径
        自己起的那些）。只给 MainWindow 设的话，对话框标题栏全是空白图标。
      · 更要紧的一层：``video_toolbox.py`` 的任务创建页与
        ``vt_engine_ui/my_video_widget.py`` 都有「继承 QApplication 默认
        图标」的逻辑（引擎 UI 自带这套行为），不设应用图标它们就都是空的。

    **绝不抛异常**：图标是装饰，缺了只是少个图，不该让程序起不来。
    找不到 ico 时静默跳过（``engine.app_icon_path()`` 已负责多路径回退）。

    冻结态（onefile）走 ``sys._MEIPASS/assets/app_icon.ico``——spec 的
    ``datas`` 收的那一份。源码态直接读仓库根的 ``assets/``。
    """
    try:
        from PySide6.QtGui import QIcon
        path = engine.app_icon_path()
        if not path:
            return
        icon = QIcon(path)
        if icon.isNull():
            # 图标存在却读不出（文件被截断 / 编码坏了）——同样只记不抛
            _perf_note("应用图标读取失败：%s" % path)
            return
        app.setWindowIcon(icon)
        # 显式给主窗口也设一份：QApplication 默认图标对**已创建**的窗口
        # 不追溯（此处还没建 MainWindow，但显式设更保险，也便于将来调整顺序）
        try:
            app.setApplicationIcon(icon)
        except Exception:  # noqa: BLE001
            pass
        _perf_note("应用图标已应用：%s" % path)
    except Exception as e:  # noqa: BLE001
        try:
            _perf_note("应用图标设置异常（已忽略）：%s" % e)
        except Exception:  # noqa: BLE001
            pass


def _start_startup_sync_threads():
    """首页就绪后再起校准/声纹同步线程（失败静默，各自记日志）。"""
    # 启动即拉取最新校准知识并入本地（v1.10.7 多用户收敛的「拉」半程）
    threading.Thread(target=engine.sync_calib_on_startup, daemon=True).start()
    # 声纹模板同步是独立通道（src\features\voiceprint\voiceprint_sync.py）
    threading.Thread(target=engine.sync_voiceprint_on_startup, daemon=True).start()
    _perf_note("后台同步线程已启动（首页就绪后延迟）")


def _ensure_hidden_stdio():
    """pythonw 下 stdout/stderr 为 None：给 print/异常一个安全的落点。"""
    try:
        if sys.stdout is None:
            sys.stdout = open(os.devnull, "w", encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    if sys.stderr is not None:
        return
    try:
        os.makedirs(engine.LOGS_DIR, exist_ok=True)
        fh = open(os.path.join(engine.LOGS_DIR, "launcher_stderr.log"),
                  "a", encoding="utf-8", buffering=1)
        fh.write("\n--- launcher start %s ---\n"
                 % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        sys.stderr = fh
    except Exception:  # noqa: BLE001
        try:
            sys.stderr = open(os.devnull, "w", encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass