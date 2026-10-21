# -*- coding: utf-8 -*-
# @version 2.4.1
"""子进程工具与中止原语（窗口隐藏 / 进程树杀灭 / 可取消睡眠）（v2.3.1 拆分工程 · 自 video_toolbox.py 原样搬入）。

本模块是 src/core/shared/ 的组成部分；域间依赖规则见 core/__init__.py。
"""
import subprocess
import sys
import threading
import time

# ========== 子进程窗口控制 ==========
# 保留原始入口，供命令行模式继续显示 yt-dlp 进度；
# run_process / popen_process 用于 GUI 或捕获输出的场景，避免弹出黑色控制台。
_SUBPROCESS_RUN = subprocess.run
_SUBPROCESS_POPEN = subprocess.Popen


def _hide_console_kwargs(kwargs):
    if sys.platform.startswith("win"):
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        kwargs.setdefault("startupinfo", startupinfo)
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | subprocess.CREATE_NO_WINDOW
    return kwargs


def run_process(*args, **kwargs):
    return _SUBPROCESS_RUN(*args, **_hide_console_kwargs(kwargs))


def popen_process(*args, **kwargs):
    return _SUBPROCESS_POPEN(*args, **_hide_console_kwargs(kwargs))


# ========== 下载中止原语（v1.19.1） ==========
def kill_process_tree(proc):
    """杀掉子进程**及其全部后代**，返回是否成功。

    为什么不能只用 `proc.kill()`：yt-dlp / ffmpeg / NPE(java) 都会再 fork
    出自己的子进程（ffmpeg 合并、NPE 内部再起下载线程对应的进程）。只杀
    父进程的话，孙进程会继续持有 .part 文件写句柄、继续吃带宽——用户点完
    「取消选中任务」看着像没生效，日志还在滚就是这个原因。
    Windows 没有 POSIX 进程组，用 taskkill /T 递归杀；其余平台退回 kill()。
    """
    if proc is None:
        return False
    try:
        if proc.poll() is not None:
            return True          # 已经自己退出了，无需再杀
    except Exception:  # noqa: BLE001
        return False
    if sys.platform.startswith("win"):
        try:
            run_process(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                        capture_output=True, timeout=15)
            return True
        except Exception:  # noqa: BLE001 —— 退回单进程 kill
            pass
    try:
        proc.kill()
        return True
    except Exception:  # noqa: BLE001
        return False


def sleep_cancellable(seconds, cancel=None):
    """可被取消标志打断的睡眠；被打断返回 True。

    取消按钮置位后，退避等待必须立刻放行——原先 `time.sleep(6)` 一口气睡满，
    用户点完取消还要白等几十秒才看到界面收敛。
    """
    if cancel is None:
        time.sleep(seconds)
        return False
    end = time.time() + max(0.0, float(seconds))
    while True:
        if cancel.is_set():
            return True
        left = end - time.time()
        if left <= 0:
            return False
        time.sleep(min(0.2, left))
# =============================


# ========== 工具引导锁（并行 ensure_* 防重复下载；v2.3.1 随进程原语迁入） ==========
_BOOTSTRAP_LOCK = threading.Lock()


__all__ = [
    "run_process",
    "popen_process",
    "kill_process_tree",
    "sleep_cancellable",
]
