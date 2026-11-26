# -*- coding: utf-8 -*-
# @version 3.3.1
"""主线程挂起看门狗（2026-11-20 卡死排查优化）。

原理：主线程 QTimer 每秒更新心跳；daemon 线程检查心跳间隔，超过阈值
（默认 5s＝主线程完全没处理消息）即用 faulthandler 把**全部线程栈** dump
到 logs/hang_watchdog.log（每次挂起事件只 dump 一遍，恢复后重置）。
只读栈写日志，不杀进程不弹窗——设置页那类 5 秒级瞬态挂起（WER
AppHangTransient）无模块信息无日志，这是唯一能定位到卡住帧的手段。
"""
from __future__ import annotations

import faulthandler
import os
import threading
import time


def start(app_root: str, interval: float = 1.0, threshold: float = 5.0):
    """必须在主线程调用（QTimer 线程亲和）。返回 timer，调用方持引用防 GC。"""
    from PySide6.QtCore import QTimer  # noqa: PLC0415
    beat = [time.monotonic()]
    timer = QTimer()
    timer.setInterval(int(interval * 1000))
    timer.timeout.connect(lambda: beat.__setitem__(0, time.monotonic()))
    timer.start()
    log_path = os.path.join(app_root, "logs", "hang_watchdog.log")

    def _watch():
        dumped = False
        while True:
            time.sleep(interval)
            gap = time.monotonic() - beat[0]
            if gap > threshold:
                if not dumped:
                    dumped = True
                    try:
                        os.makedirs(os.path.dirname(log_path), exist_ok=True)
                        with open(log_path, "a", encoding="utf-8") as f:
                            f.write("\n==== %s 主线程 %.1fs 未响应（全线程栈）====\n"
                                    % (time.strftime("%Y-%m-%d %H:%M:%S"), gap))
                            faulthandler.dump_traceback(file=f, all_threads=True)
                    except OSError:
                        pass
            else:
                dumped = False

    threading.Thread(target=_watch, daemon=True, name="hang-watchdog").start()
    return timer