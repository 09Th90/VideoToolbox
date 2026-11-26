# -*- coding: utf-8 -*-
# @version 3.3.1
"""JSONL 输出：每行一条终版 Cue，便于事后回放/统计。"""
from __future__ import annotations

import json
import threading
from pathlib import Path

from ..cue import Cue
from .base import Sink


class JsonlSink(Sink):
    name = "jsonl"

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._fh = None
        self._open()

    def _open(self, truncate: bool = False) -> None:
        if self._fh:
            try:
                self._fh.close()
            except Exception:  # noqa: BLE001
                pass
        self._fh = self.path.open("w" if truncate else "a",
                                  encoding="utf-8", buffering=1)

    def publish(self, cue: Cue) -> None:
        if cue.interim or not cue.main:
            return
        with self._lock:
            if self._fh is None:
                self._open()
            self._fh.write(json.dumps(cue.to_dict(), ensure_ascii=False) + "\n")

    def new_session(self) -> None:
        with self._lock:
            self._open(truncate=True)

    def close(self) -> None:
        with self._lock:
            if self._fh:
                try:
                    self._fh.close()
                except Exception:  # noqa: BLE001
                    pass
                self._fh = None

    def stats(self) -> dict:
        return {"name": self.name, "path": str(self.path),
                "open": self._fh is not None}
