# -*- coding: utf-8 -*-
# @version 3.3.1
"""本地 Index-Echo 后端：一次 HTTP 转录同时得到原文与译文。

引擎默认返回 ``{"text": "原文\\n译文"}``；``format=json`` 时 ``segments``
通常为空（两行 --ask 不符合上游三行配方），因此以自实现按行序解析为主，
仅在引擎确实给出 segments 时按其逐条解析。

合并期修复：``configured`` 真实反映 ``crispasr.exe`` / 模型是否在位，
让路由不再对“没装本地引擎”的机器做假降级。
"""
from __future__ import annotations

from ..audio import Segment
from ..cue import Cue
from .base import SubtitleBackend


class LocalBackend(SubtitleBackend):
    name = "local-index-echo"

    def __init__(self, engine):
        self.engine = engine
        self.calls = 0
        self.cues = 0
        self.errors = 0

    @property
    def configured(self) -> bool:
        return bool(getattr(self.engine, "configured", True))

    def produce(self, seg: Segment) -> list[Cue]:
        try:
            res = self.engine.transcribe(seg.pcm)
        except Exception:
            self.errors += 1
            raise
        self.calls += 1
        segments = res.get("segments") or []
        cues: list[Cue] = []
        if segments:
            for item in segments:
                cues.extend(Cue.from_local_text(
                    item.get("text", ""), seq=seg.seq, t0_ms=seg.t0_ms,
                    duration_ms=seg.duration_ms, backend=self.name))
        else:
            cues = Cue.from_local_text(res.get("text", ""),
                                       seq=seg.seq, t0_ms=seg.t0_ms,
                                       duration_ms=seg.duration_ms,
                                       backend=self.name)
        self.cues += len(cues)
        return cues

    def stats(self) -> dict:
        return {"name": self.name, "configured": self.configured,
                "calls": self.calls, "cues": self.cues, "errors": self.errors}
