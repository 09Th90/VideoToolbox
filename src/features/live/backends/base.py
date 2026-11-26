# -*- coding: utf-8 -*-
# @version 3.3.1
"""后端契约：一段 PCM 进，一组 Cue 出。

本地 Index-Echo 是「ASR + 翻译一体」（一次调用返回两行），云端则是
「ASR → 翻译」两步，因此统一在 Backend 层而不是 ASR 层做抽象。
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..audio import Segment
from ..cue import Cue


class CloudError(RuntimeError):
    """云端后端失败。status 用于状态机判定是否永久禁用回探。"""

    def __init__(self, message: str, status: int | None = None,
                 kind: str = "network"):
        super().__init__(message)
        self.status = status
        self.kind = kind
        self.fatal = status in (401, 403) or kind == "unconfigured"


class SubtitleBackend(ABC):
    name = "base"

    @abstractmethod
    def produce(self, seg: Segment) -> list[Cue]:
        """处理一段语音，返回零条或多条 Cue。失败抛 CloudError / EngineError。"""

    @property
    def configured(self) -> bool:
        return True

    def stats(self) -> dict:
        return {"name": self.name}


def mark_fallback(cues: list[Cue], cloud_name: str) -> list[Cue]:
    """把本地重跑结果标注为降级产物。"""
    for c in cues:
        c.fallback_from = cloud_name
        c.degraded = c.degraded or not c.sub
    return cues
