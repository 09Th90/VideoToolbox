# -*- coding: utf-8 -*-
# @version 3.3.1
"""音源契约：逐帧产出 16 kHz / 单声道 / s16le PCM。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterator


class Source(ABC):
    name = "base"
    error = ""

    @abstractmethod
    def iter_frames(self) -> Iterator[bytes]:
        """阻塞式逐帧产出；stop() 后应在 1 帧内退出。"""

    def stop(self) -> None:
        pass

    def stats(self) -> dict:
        return {"name": self.name}
