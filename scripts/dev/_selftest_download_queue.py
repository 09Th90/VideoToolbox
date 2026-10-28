# -*- coding: utf-8 -*-
"""P3a 回归：纯模型下载队列（无 Qt、无网络）。"""
from __future__ import annotations

import os
import random
import sys
import threading
import time
from pathlib import Path

APP_DIR = Path(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
sys.path.insert(0, str(APP_DIR / "src"))
os.environ.setdefault("VT_DATA_ROOT", str(APP_DIR / "data" / "tmp" / "download_queue_selftest"))

from core.download.scheduler import (  # noqa: E402
    DownloadQueue, QueueEvent, TaskState, queue_mode_enabled,
)

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append({"name": name, "ok": bool(ok), "detail": str(detail)})
    print(("[PASS] " if ok else "[FAIL] ") + name
          + (("  " + str(detail)) if detail else ""), flush=True)


def events_of(events, kind):
    return [e for e in events if e.kind == kind]


def test_basic():
    events = []
    q = DownloadQueue(max_concurrent=2, on_event=events.append)
    tasks = [q.add(f"T{i}", f"https://example.test/{i}") for i in range(5)]
    runs = events_of(events, "run")
    check("concurrency + queue", len(runs) == 2 and q.active_count() == 2
          and q.queued_count() == 3, q.snapshot())
    first = runs[0]
    check("run event has run_id", first.run_id == 1 and first.task_id == "T0")
    task = q.get_task("T0")
    check("progress accepted", q.progress("T0", 1, 42.5, 1000, 9))
    check("stale progress rejected", not q.progress("T0", 0, 99))
    check("worker stopped", q.worker_stopped("T0", 1, completed=True))
    check("next starts after slot", q.get_task("T2").state == TaskState.DOWNLOADING
          and q.get_task("T0").state == TaskState.COMPLETED)
    check("duplicate active rejected", q.add("Tnew", "https://example.test/1").task_id == "T1")


def test_pause_resume():
    events = []
    q = DownloadQueue(max_concurrent=1, on_event=events.append)
    q.add("A", "https://example.test/a")
    run = events_of(events, "run")[0]
    check("pause running", q.pause("A") and q.get_task("A").state == TaskState.PAUSING)
    check("pause ack", q.worker_stopped("A", run.run_id, paused=True)
          and q.get_task("A").state == TaskState.PAUSED)
    old_run = run.run_id
    events.clear()
    check("resume", q.resume("A") and q.get_task("A").state == TaskState.DOWNLOADING)
    new_run = events_of(events, "run")[0].run_id
    check("new run id", new_run > old_run)
    check("old progress rejected", not q.progress("A", old_run, 50))
    check("new progress accepted", q.progress("A", new_run, 10))
    check("old done rejected", not q.worker_stopped("A", old_run, completed=True))
    check("new done", q.worker_stopped("A", new_run, completed=True))


def test_race_and_cancel():
    q = DownloadQueue(max_concurrent=1)
    q.add("A", "https://example.test/a")
    q.pause("A")
    check("pause + completed wins", q.worker_stopped("A", 1, completed=True)
          and q.get_task("A").state == TaskState.COMPLETED)
    q2 = DownloadQueue(max_concurrent=1)
    q2.add("A", "https://example.test/a")
    q2.add("B", "https://example.test/b")
    q2.cancel("B")
    check("cancel queued", q2.get_task("B").state == TaskState.CANCELLED)
    q2.add("C", "https://example.test/c")
    # A 仍占槽位，C 仍在排队；先结束 A，让 C 拿到槽位
    q2.worker_stopped("A", 1, completed=True)
    c_run = 1
    q2.cancel("C")
    check("cancel running ack", q2.worker_stopped("C", c_run, completed=True)
          and q2.get_task("C").state == TaskState.CANCELLED)


def test_dynamic_max_and_cancel_all():
    q = DownloadQueue(max_concurrent=2)
    for i in range(5):
        q.add(f"T{i}", f"https://example.test/{i}")
    check("lower does not kill running", q.set_max_concurrent(1) == 1 and q.active_count() == 2)
    q.set_max_concurrent(4)
    check("raise fills", q.active_count() >= 2)
    q.cancel_all()
    states = q.snapshot()["states"].values()
    check("cancel_all", all(s in ("cancelling", "cancelled") for s in states),
          list(states))


def test_fuzz():
    rng = random.Random(20261027)
    events = []
    q = DownloadQueue(max_concurrent=2, on_event=events.append)
    violations = []
    for i in range(10_000):
        ids = list(q.snapshot()["states"])
        tid = rng.choice(ids) if ids else ""
        op = rng.choices(
            ("add", "pause", "resume", "cancel", "finished", "failed",
             "progress", "retry", "max", "stale"),
            weights=(20, 9, 9, 9, 12, 7, 15, 5, 5, 9), k=1,
        )[0]
        try:
            if op == "add" or not ids:
                q.add(f"T{i}", f"https://example.test/{i}")
            elif op == "pause":
                q.pause(tid)
            elif op == "resume":
                q.resume(tid)
            elif op == "cancel":
                q.cancel(tid)
            elif op == "finished":
                task = q.get_task(tid)
                if task:
                    q.worker_stopped(tid, task.run_id, completed=True)
            elif op == "failed":
                task = q.get_task(tid)
                if task:
                    q.worker_stopped(tid, task.run_id, error="injected")
            elif op == "progress":
                task = q.get_task(tid)
                if task:
                    q.progress(tid, task.run_id, rng.random() * 100)
            elif op == "retry":
                q.retry(tid)
            elif op == "max":
                q.set_max_concurrent(rng.randint(1, 6))
            elif op == "stale":
                task = q.get_task(tid)
                if task:
                    q.progress(tid, max(0, task.run_id - 1), rng.random() * 100)
        except Exception as e:  # noqa: BLE001
            violations.append((i, op, repr(e)))
            break
        err = q.invariant_error()
        if err:
            violations.append((i, op, err))
            break
    check("10k event fuzz", not violations, violations[:1])


def test_real_threads():
    q = DownloadQueue(max_concurrent=2)
    fake_runs = []
    lock = threading.Lock()

    def on_event(ev: QueueEvent):
        if ev.kind == "run":
            fake_runs.append((ev.task_id, ev.run_id))
            def work(task_id=ev.task_id, run_id=ev.run_id):
                time.sleep(0.05)
                task = q.get_task(task_id)
                if task and task.state == TaskState.CANCELLING:
                    q.worker_stopped(task_id, run_id, cancelled=True)
                elif task and task.state == TaskState.PAUSING:
                    q.worker_stopped(task_id, run_id, paused=True)
                else:
                    q.worker_stopped(task_id, run_id, completed=True)
            threading.Thread(target=work, daemon=True).start()

    q.set_event_sink(on_event)
    for i in range(20):
        q.add(f"R{i}", f"https://example.test/r{i}")
    time.sleep(0.2)
    # 暂停一个正在跑的、取消一个排队的
    running = list(q.snapshot()["running"])
    if running:
        q.pause(running[0])
    waiting = list(q.snapshot()["waiting"])
    if waiting:
        q.cancel(waiting[0])
    deadline = time.time() + 15
    while time.time() < deadline:
        if q.is_idle():
            break
        time.sleep(0.02)
    states = q.snapshot()["states"]
    ok = q.is_idle() and not q.invariant_error() and any(
        s in ("completed", "paused", "cancelled") for s in states.values())
    check("20 real fake workers", ok, f"runs={len(fake_runs)} states={set(states.values())}")


def test_env_and_source():
    old = os.environ.get("VT_DL_QUEUE")
    try:
        os.environ["VT_DL_QUEUE"] = "0"
        check("queue env off", queue_mode_enabled(True) is False)
        os.environ["VT_DL_QUEUE"] = "1"
        check("queue env on", queue_mode_enabled(False) is True)
        os.environ.pop("VT_DL_QUEUE", None)
        check("queue default", queue_mode_enabled(True) is True)
    finally:
        if old is None:
            os.environ.pop("VT_DL_QUEUE", None)
        else:
            os.environ["VT_DL_QUEUE"] = old
    text = (APP_DIR / "src" / "core" / "download" / "scheduler.py").read_text(encoding="utf-8")
    forbidden = ("PySide6", "PyQt", "qfluentwidgets", "from core.pipeline", "import core.pipeline")
    check("scheduler no Qt/pipeline", all(x not in text for x in forbidden))


def main():
    for fn in (test_basic, test_pause_resume, test_race_and_cancel,
               test_dynamic_max_and_cancel_all, test_fuzz, test_real_threads,
               test_env_and_source):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            check(fn.__name__, False, repr(e))
    passed = sum(1 for r in RESULTS if r["ok"])
    print("\n%d/%d passed" % (passed, len(RESULTS)))
    if passed != len(RESULTS):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
