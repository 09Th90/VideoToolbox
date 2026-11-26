# -*- coding: utf-8 -*-
# @version 3.3.1
"""输出广播契约：每个 Sink 接收终版 Cue，自己决定如何落盘/上屏。"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..cue import Cue


class Sink(ABC):
    name = "base"

    @abstractmethod
    def publish(self, cue: Cue) -> None:
        """接收一条 Cue（可能是同 seq 的译文补丁，Sink 自行 upsert）。"""

    def new_session(self) -> None:
        pass

    def close(self) -> None:
        pass

    def stats(self) -> dict:
        return {"name": self.name}


class Broadcast:
    def __init__(self):
        self.sinks: list[Sink] = []

    def add(self, sink: Sink) -> None:
        self.sinks.append(sink)

    def publish(self, cue: Cue) -> None:
        for sink in self.sinks:
            try:
                sink.publish(cue)
            except Exception:  # noqa: BLE001 —— 单个 Sink 故障不得断字幕链路
                pass

    def new_session(self) -> None:
        for sink in self.sinks:
            try:
                sink.new_session()
            except Exception:  # noqa: BLE001
                pass

    def close(self) -> None:
        for sink in self.sinks:
            try:
                sink.close()
            except Exception:  # noqa: BLE001
                pass

    def stats(self) -> dict:
        return {"sinks": [s.stats() for s in self.sinks]}
