# -*- coding: utf-8 -*-
# @version 3.3.1
"""有界语音段队列：满时丢最旧、超时丢弃，固定单 worker 消费。

本地引擎实测 0.5x realtime，持续说话必然积压；本队列让字幕始终优先显示
最新一句。``max_pending`` 只约束待处理段，单 worker 保证 in-flight 恒为 1。
"""
from __future__ import annotations

import threading
import time
from collections import deque

from .audio import Segment


class BoundedBus:
    def __init__(self, max_pending: int = 3, stale_s: float = 20.0,
                 on_drop=None):
        self.max_pending = max(1, int(max_pending))
        self.stale_s = float(stale_s)
        self._q: deque[Segment] = deque()
        self._cv = threading.Condition()
        self._stopping = False
        self.on_drop = on_drop
        self.dropped_oldest = 0
        self.dropped_stale = 0
        self.processed = 0
        self.submitted = 0

    def submit(self, seg: Segment) -> bool:
        with self._cv:
            if self._stopping:
                return False
            if len(self._q) >= self.max_pending:
                old = self._q.popleft()
                self.dropped_oldest += 1
                if self.on_drop:
                    self.on_drop("oldest", old)
            self._q.append(seg)
            self.submitted += 1
            self._cv.notify()
            return True

    def submit_interim(self, seg: Segment) -> bool:
        """预识别段：队列满时直接丢自己，绝不挤掉待处理的终版段。"""
        with self._cv:
            if self._stopping or len(self._q) >= self.max_pending:
                return False
            self._q.append(seg)
            self.submitted += 1
            self._cv.notify()
            return True

    def get(self, timeout: float = 0.5) -> Segment | None:
        """阻塞取一段；跳过陈旧段。返回 None 表示暂无工作或已停止。"""
        with self._cv:
            if not self._q and not self._stopping:
                self._cv.wait(timeout)
            while self._q:
                seg = self._q.popleft()
                age = time.time() - seg.created
                if age > self.stale_s:
                    self.dropped_stale += 1
                    if self.on_drop:
                        self.on_drop("stale", seg)
                    continue
                self.processed += 1
                return seg
            return None

    def set_stopping(self) -> None:
        """拒绝新提交、清空待处理队列、唤醒 worker（不中断在途请求）。"""
        with self._cv:
            self._stopping = True
            self._q.clear()
            self._cv.notify_all()

    def clear(self) -> int:
        with self._cv:
            n = len(self._q)
            self._q.clear()
            return n

    @property
    def pending(self) -> int:
        with self._cv:
            return len(self._q)

    @property
    def stopping(self) -> bool:
        with self._cv:
            return self._stopping

    def stats(self) -> dict:
        with self._cv:
            return {"pending": len(self._q), "submitted": self.submitted,
                    "processed": self.processed,
                    "dropped_oldest": self.dropped_oldest,
                    "dropped_stale": self.dropped_stale,
                    "stopping": self._stopping}
