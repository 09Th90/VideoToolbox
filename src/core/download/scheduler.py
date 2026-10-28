# -*- coding: utf-8 -*-
# @version 2.8.0
"""下载队列状态机（core/download 内部模块，纯标准库、无 Qt）。

调度器只拥有状态与槽位；真正起线程/杀进程由 GUI/宿主按事件完成。
run_id 用于丢弃旧运行代次的迟到进度/完成消息；revision 用于丢弃乱序状态。
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable


class TaskState(str, Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PAUSING = "pausing"
    PAUSED = "paused"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"


TERMINAL_STATES = frozenset({TaskState.CANCELLED, TaskState.COMPLETED, TaskState.FAILED})
ACTIVE_STATES = frozenset({TaskState.DOWNLOADING, TaskState.PAUSING, TaskState.CANCELLING})
PENDING_STATES = frozenset({TaskState.QUEUED, TaskState.PAUSED})


@dataclass
class QueueTask:
    task_id: str
    url: str
    format_id: str = ""
    state: TaskState = TaskState.QUEUED
    revision: int = 0
    run_id: int = 0
    attempts: int = 0
    progress: float = 0.0
    speed: float = 0.0
    eta: float = -1.0
    error: str = ""
    payload: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    finished_at: float = 0.0


@dataclass(frozen=True)
class QueueEvent:
    kind: str
    task_id: str = ""
    state: TaskState = TaskState.QUEUED
    revision: int = 0
    run_id: int = 0
    progress: float = 0.0
    speed: float = 0.0
    eta: float = -1.0
    text: str = ""
    completed: bool = False
    error: str = ""


def queue_mode_enabled(default: bool = True) -> bool:
    value = (os.environ.get("VT_DL_QUEUE") or "").strip().lower()
    if value in ("0", "false", "no", "off"):
        return False
    if value in ("1", "true", "yes", "on"):
        return True
    return bool(default)


class DownloadQueue:
    def __init__(self, max_concurrent: int = 2, on_event: Callable[[QueueEvent], None] | None = None):
        self._lock = threading.RLock()
        self._max = max(1, int(max_concurrent))
        self._ceiling = self._max
        self._tasks: dict[str, QueueTask] = {}
        self._waiting: list[str] = []
        self._running: set[str] = set()
        self._on_event = on_event

    # ---------- event plumbing ----------
    def set_event_sink(self, callback: Callable[[QueueEvent], None] | None) -> None:
        self._on_event = callback

    def _emit(self, events: list[QueueEvent]) -> None:
        cb = self._on_event
        if cb is None:
            return
        for event in events:
            try:
                cb(event)
            except Exception:
                pass

    # ---------- helpers (call while holding lock) ----------
    def _event(self, kind: str, task: QueueTask, text: str = "", *,
               completed: bool = False, error: str = "") -> QueueEvent:
        return QueueEvent(
            kind=kind, task_id=task.task_id, state=task.state,
            revision=task.revision, run_id=task.run_id,
            progress=task.progress, speed=task.speed, eta=task.eta,
            text=text, completed=completed, error=error,
        )

    def _set_state(self, task: QueueTask, state: TaskState,
                   events: list[QueueEvent], text: str = "") -> None:
        task.state = state
        task.revision += 1
        events.append(self._event("state", task, text))

    def _remove_waiting(self, task_id: str) -> None:
        try:
            self._waiting.remove(task_id)
        except ValueError:
            pass

    def _pump(self, events: list[QueueEvent]) -> None:
        self._ceiling = max(self._max, len(self._running))
        while len(self._running) < self._max:
            task_id = None
            for candidate in list(self._waiting):
                task = self._tasks.get(candidate)
                if task is not None and task.state == TaskState.QUEUED:
                    task_id = candidate
                    break
                self._remove_waiting(candidate)
            if task_id is None:
                return
            self._remove_waiting(task_id)
            task = self._tasks[task_id]
            task.run_id += 1
            task.started_at = time.time()
            task.finished_at = 0.0
            self._running.add(task_id)
            self._set_state(task, TaskState.DOWNLOADING, events, "slot acquired")
            events.append(QueueEvent(
                kind="run", task_id=task.task_id, state=task.state,
                revision=task.revision, run_id=task.run_id,
                progress=task.progress, speed=task.speed, eta=task.eta,
            ))

    def _active_duplicate(self, url: str, format_id: str) -> QueueTask | None:
        for task in self._tasks.values():
            if task.state in TERMINAL_STATES:
                continue
            if task.url == url and task.format_id == format_id:
                return task
        return None

    # ---------- public ----------
    def add(self, task_id: str, url: str, format_id: str = "",
            payload: dict | None = None) -> QueueTask:
        events: list[QueueEvent] = []
        with self._lock:
            existing = self._tasks.get(task_id) or self._active_duplicate(url, format_id)
            if existing is not None:
                return existing
            task = QueueTask(task_id=task_id, url=url, format_id=format_id,
                             payload=dict(payload or {}))
            self._tasks[task_id] = task
            self._waiting.append(task_id)
            events.append(self._event("added", task))
            self._pump(events)
        self._emit(events)
        return task

    def find_active(self, url: str, format_id: str = "") -> QueueTask | None:
        with self._lock:
            return self._active_duplicate(url, format_id)

    def get_task(self, task_id: str) -> QueueTask | None:
        with self._lock:
            return self._tasks.get(task_id)

    def pause(self, task_id: str) -> bool:
        events: list[QueueEvent] = []
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.state in TERMINAL_STATES:
                return False
            if task.state == TaskState.QUEUED:
                self._remove_waiting(task_id)
                self._set_state(task, TaskState.PAUSED, events, "paused before start")
            elif task.state == TaskState.DOWNLOADING:
                self._set_state(task, TaskState.PAUSING, events, "pause requested")
            else:
                return False
        self._emit(events)
        return True

    def resume(self, task_id: str) -> bool:
        events: list[QueueEvent] = []
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.state != TaskState.PAUSED:
                return False
            self._set_state(task, TaskState.QUEUED, events, "resume requested")
            if task_id not in self._waiting:
                self._waiting.append(task_id)
            self._pump(events)
        self._emit(events)
        return True

    def cancel(self, task_id: str) -> bool:
        events: list[QueueEvent] = []
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.state in TERMINAL_STATES:
                return False
            if task.state in (TaskState.QUEUED, TaskState.PAUSED):
                self._remove_waiting(task_id)
                self._set_state(task, TaskState.CANCELLED, events, "cancelled")
                task.finished_at = time.time()
                events.append(self._event("finished", task, completed=False,
                                          error="cancelled"))
            elif task.state in (TaskState.DOWNLOADING, TaskState.PAUSING):
                self._set_state(task, TaskState.CANCELLING, events, "cancel requested")
        self._emit(events)
        return True

    def retry(self, task_id: str) -> bool:
        events: list[QueueEvent] = []
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.state != TaskState.FAILED:
                return False
            task.attempts += 1
            task.progress = 0.0
            task.speed = 0.0
            task.eta = -1.0
            task.error = ""
            self._set_state(task, TaskState.QUEUED, events, "retry")
            if task_id not in self._waiting:
                self._waiting.append(task_id)
            self._pump(events)
        self._emit(events)
        return True

    def progress(self, task_id: str, run_id: int, pct: float,
                 speed: float = 0.0, eta: float = -1.0) -> bool:
        events: list[QueueEvent] = []
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.state not in ACTIVE_STATES:
                return False
            if run_id != task.run_id:
                return False
            task.progress = max(0.0, min(100.0, float(pct)))
            task.speed = max(0.0, float(speed))
            task.eta = float(eta)
            events.append(self._event("progress", task))
        self._emit(events)
        return True

    def worker_stopped(self, task_id: str, run_id: int, *,
                       completed: bool = False, paused: bool = False,
                       cancelled: bool = False, error: str = "") -> bool:
        events: list[QueueEvent] = []
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task_id not in self._running or run_id != task.run_id:
                return False
            self._running.discard(task_id)
            task.finished_at = time.time()
            if cancelled or task.state == TaskState.CANCELLING:
                self._set_state(task, TaskState.CANCELLED, events, "cancelled")
                events.append(self._event("finished", task, error="cancelled"))
            elif completed:
                task.progress = 100.0
                self._set_state(task, TaskState.COMPLETED, events, "completed")
                events.append(self._event("finished", task, completed=True))
            elif paused or task.state == TaskState.PAUSING:
                self._set_state(task, TaskState.PAUSED, events, "paused")
                events.append(self._event("finished", task, text="paused"))
            else:
                task.error = error or "failed"
                self._set_state(task, TaskState.FAILED, events, task.error)
                events.append(self._event("finished", task, error=task.error))
            self._pump(events)
        self._emit(events)
        return True

    def set_max_concurrent(self, value: int) -> int:
        events: list[QueueEvent] = []
        with self._lock:
            self._max = max(1, int(value))
            self._ceiling = max(self._ceiling, self._max, len(self._running))
            events.append(QueueEvent(kind="max_changed", text=str(self._max)))
            self._pump(events)
        self._emit(events)
        return self._max

    def cancel_all(self) -> list[str]:
        events: list[QueueEvent] = []
        ids: list[str] = []
        with self._lock:
            for task in self._tasks.values():
                if task.state in TERMINAL_STATES:
                    continue
                ids.append(task.task_id)
                if task.state in (TaskState.QUEUED, TaskState.PAUSED):
                    self._remove_waiting(task.task_id)
                    self._set_state(task, TaskState.CANCELLED, events, "cancelled")
                    task.finished_at = time.time()
                    events.append(self._event("finished", task, error="cancelled"))
                else:
                    self._set_state(task, TaskState.CANCELLING, events, "cancel requested")
        self._emit(events)
        return ids

    def active_count(self) -> int:
        with self._lock:
            return sum(1 for t in self._tasks.values() if t.state in ACTIVE_STATES)

    def queued_count(self) -> int:
        with self._lock:
            return sum(1 for t in self._tasks.values() if t.state == TaskState.QUEUED)

    def is_idle(self) -> bool:
        with self._lock:
            return not self._running and not self._waiting

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "max": self._max,
                "running": sorted(self._running),
                "waiting": list(self._waiting),
                "states": {tid: t.state.value for tid, t in self._tasks.items()},
                "revisions": {tid: t.revision for tid, t in self._tasks.items()},
                "run_ids": {tid: t.run_id for tid, t in self._tasks.items()},
            }

    def invariant_error(self) -> str:
        with self._lock:
            if len(self._running) > self._ceiling:
                return "running %d > ceiling %d" % (len(self._running), self._ceiling)
            for tid in self._running:
                task = self._tasks.get(tid)
                if task is None:
                    return "running unknown %s" % tid
                if task.state not in ACTIVE_STATES:
                    return "running %s state %s" % (tid, task.state)
            for tid in self._waiting:
                task = self._tasks.get(tid)
                if task is None:
                    return "waiting unknown %s" % tid
                if task.state != TaskState.QUEUED:
                    return "waiting %s state %s" % (tid, task.state)
            for task in self._tasks.values():
                if task.state == TaskState.PAUSED and task.task_id in self._running:
                    return "paused %s is running" % task.task_id
            return ""


__all__ = [
    "TaskState", "QueueTask", "QueueEvent", "DownloadQueue",
    "TERMINAL_STATES", "ACTIVE_STATES", "PENDING_STATES",
    "queue_mode_enabled",
]
