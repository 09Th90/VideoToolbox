# -*- coding: utf-8 -*-
# @version 3.3.1
"""控制台输出：无 UI 冒烟/调试用。"""
from __future__ import annotations

import sys

from ..cue import Cue
from .base import Sink


class ConsoleSink(Sink):
    name = "console"

    def publish(self, cue: Cue) -> None:
        if cue.interim or not cue.main:
            return
        mark = "!" if cue.degraded else ""
        line = f"[{cue.seq}] {cue.main}{mark}"
        if cue.sub and cue.sub != cue.main:
            line += f"  /  {cue.sub}"
        try:
            print(line, flush=True)
        except Exception:  # noqa: BLE001
            pass

    def stats(self) -> dict:
        return {"name": self.name, "stream": bool(sys.stdout)}
