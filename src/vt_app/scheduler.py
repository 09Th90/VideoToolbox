# -*- coding: utf-8 -*-
# @version 3.2.0
"""首帧后后台任务调度器（原 video_toolbox_qt.py 同名代码，逐字下沉）。"""
import os
import time

from PySide6.QtCore import QEvent, QObject, QTimer

from vt_app.boot import _perf_note

# ========== 首帧后后台任务调度（2026-10-21 启动调度专项） ==========
# 问题（实测）：窗口首帧 T+1.005s 之后，主线程被一串互相不让出的
# ``QTimer.singleShot`` 占住——SpinBox 兼容探测 ≈0.6s、引擎预热线程抢 GIL
# 1.97s、全树刷主题色 ≈1.8s、库页/自动化页/流水线各自建控件。用户在这 1–5s
# 里点导航「没反应」，体感就是卡死。
#
# 本调度器把首帧后的**全部**后台任务收进一个队列，按三个原则跑：
#   ① 单帧预算（默认 60ms）：一次 tick 内累计超预算就停，下一轮继续——
#      保证事件循环随时能回去处理点击；
#   ② 用户输入感知：鼠标/键盘一动，450ms 内暂停后台任务（用户在用就不打扰）；
#      连续操作超 8s 强制放行一次，避免任务被永久饿死；
#   ③ 依赖 + 插队：预热完成前不建引擎界面；用户主动点进字幕页时 run_now 插队。
#
# ⚠ 不并入常驻的 ``_pump``（120ms 消息泵）——那是业务消息通道，语义不同。


class _StartupScheduler(QObject):
    """单定时器驱动的启动任务队列（见上方设计说明）。"""

    def __init__(self, app, budget_ms=60.0, idle_ms=450.0):
        super().__init__(app)
        self._tasks = []
        self._by_name = {}
        try:
            self._budget = float(os.environ.get("VT_SCHED_BUDGET") or budget_ms)
        except (TypeError, ValueError):
            self._budget = float(budget_ms)
        self._idle_ms = float(idle_ms)
        self._trace = bool(os.environ.get("VT_SCHED_TRACE"))
        self._last_input = 0.0
        self._starve_since = 0.0
        self._t0 = time.perf_counter()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._tick)
        # 只记录输入时间戳，恒 return False（绝不吞事件）
        try:
            app.installEventFilter(self)
        except Exception:  # noqa: BLE001
            pass

    # ---------- 注册与触发 ----------
    def add(self, name, fn, delay_ms=0, priority=50, depends_on=(),
            budget_ms=None, retry_ms=64):
        """登记一个任务。``fn`` 返回 False 表示「本轮没做完，保留待重试」，
        会在 ``retry_ms`` 之后再问一次（见 _tick 里的 due 重置）。"""
        if name in self._by_name:
            return self._by_name[name]
        t = {"name": name, "fn": fn,
             "due": self._t0 + max(0.0, float(delay_ms)) / 1000.0,
             "prio": int(priority), "deps": tuple(depends_on or ()),
             "budget": budget_ms, "retry": max(0.0, float(retry_ms)) / 1000.0,
             "done": False}
        self._tasks.append(t)
        self._by_name[name] = t
        self._arm(0)
        return t

    def mark_done(self, name):
        t = self._by_name.get(name)
        if t is not None:
            t["done"] = True
            self._arm(0)

    def run_now(self, name, priority=0):
        """用户主动触发：插队 + 忽略输入静默期。"""
        t = self._by_name.get(name)
        if t is None or t["done"]:
            return False
        t["prio"] = int(priority)
        t["due"] = 0.0
        self._last_input = 0.0
        self._arm(0)
        return True

    # ---------- 事件与驱动 ----------
    def eventFilter(self, obj, e):
        try:
            if e.type() in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease,
                            QEvent.MouseButtonDblClick, QEvent.KeyPress,
                            QEvent.Wheel):
                self._last_input = time.perf_counter()
        except Exception:  # noqa: BLE001
            pass
        return False

    def _arm(self, ms):
        try:
            self._timer.start(max(0, int(ms)))
        except Exception:  # noqa: BLE001 —— 定时器在退出流程中可能已失效
            pass

    def _blocked(self, t):
        for d in t["deps"]:
            dep = self._by_name.get(d)
            if dep is not None and not dep["done"]:
                return True
        return False

    def _next_delay_ms(self):
        now = time.perf_counter()
        pend = [t for t in self._tasks if not t["done"]]
        if not pend:
            return 0
        wait = 500.0
        for t in pend:
            if self._blocked(t):
                wait = min(wait, 64.0)      # 依赖未满足：低频轮询
            else:
                wait = min(wait, max(0.0, (t["due"] - now) * 1000.0))
        return wait

    def _tick(self):
        now = time.perf_counter()
        if not any(not t["done"] for t in self._tasks):
            return
        # 用户正在操作 → 让出。连续操作超 8s 则强制放行一轮（防饥饿）。
        if (now - self._last_input) * 1000.0 < self._idle_ms:
            if not self._starve_since:
                self._starve_since = now
            if now - self._starve_since < 8.0:
                self._arm(64)
                return
        self._starve_since = 0.0
        spent = 0.0
        while True:
            now = time.perf_counter()
            ready = [t for t in self._tasks
                     if not t["done"] and now >= t["due"] and not self._blocked(t)]
            if not ready:
                break
            t = min(ready, key=lambda x: x["prio"])
            cap = t["budget"] if t["budget"] is not None else self._budget
            if spent >= cap:
                break
            t_start = time.perf_counter()
            ok = True
            try:
                ok = t["fn"]()
            except Exception as e:  # noqa: BLE001 —— 单个任务失败不拖垮启动
                _perf_note(f"sched[{t['name']}] 失败：{e}")
            t["done"] = ok is not False
            cost = (time.perf_counter() - t_start) * 1000.0
            spent += cost
            if not t["done"]:
                # ⚠ 未完成的任务必须把 due 推到未来：否则它一直「已到期」，
                #   _next_delay_ms 返回 0 → 每个事件循环都跑一次 tick，变成
                #   隐形的 CPU 忙等（首版实测即此，prewarm_done 每轮重入）。
                t["due"] = time.perf_counter() + t["retry"]
            if self._trace and t["done"]:
                _perf_note(f"sched[{t['name']}] {cost:.1f}ms")
            if cost > max(50.0, cap) * 2.0:
                # 任务体内不可切分时 budget 只能事后记账——这段就是用户手里
                # 那一下「点不动」的真实时长。留个直接证据，别再靠猜。
                _perf_note(f"sched[{t['name']}] 超预算 {cost:.0f}ms"
                           f"（budget={cap:.0f}ms，任务体内不可切分）")
            if cost >= 8.0:
                break          # 重任务之后强制让出一帧，先让界面喘口气
        self._arm(self._next_delay_ms())


#: 调度器单例（main() 里 QApplication 之后创建；见 _defer）。
_SCHED = {"inst": None}


def _defer(name, fn, delay_ms=0, priority=50, depends_on=(), budget_ms=None):
    """把首帧后的后台任务交给调度器；调度器不在场时退回 singleShot 兜底。

    ⚠ ``fn`` 若是 bound method，退回路径必须包一层 ``lambda:`` —— 直接把
    bound method 传给 ``QTimer.singleShot`` 会在**注册时**就求值，惰性页会被
    提前构造出来（历史踩坑）。
    """
    s = _SCHED["inst"]
    if s is not None:
        return s.add(name, fn, delay_ms, priority, depends_on, budget_ms)
    try:
        QTimer.singleShot(max(0, int(delay_ms)), lambda: fn())
    except Exception:  # noqa: BLE001
        pass
    return None