# -*- coding: utf-8 -*-
# @version 3.3.1
"""文本接力：原子写 sub_en.txt / sub_zh.txt。

沿用 vt-web-server 的 drawtext(reload=1) 契约；按行的字符集决定写入哪个文件。
OBS 的「文本(GDI+)」源直接读这两个文件即可实现实时上屏。
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

from ..cue import Cue, script
from .base import Sink


class TextFileSink(Sink):
    name = "text"

    def __init__(self, out_dir: Path):
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.en = self.out_dir / "sub_en.txt"
        self.zh = self.out_dir / "sub_zh.txt"
        self._lock = threading.Lock()

    @staticmethod
    def _write(path: Path, text: str) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            f.write(text or " ")
        os.replace(tmp, path)

    def publish(self, cue: Cue) -> None:
        if cue.interim:
            return
        en, zh = "", ""
        for line in (cue.main, cue.sub):
            if not line:
                continue
            if script(line) == "zh":
                zh = line
            else:
                en = line
        with self._lock:
            self._write(self.en, en)
            self._write(self.zh, zh)

    def new_session(self) -> None:
        with self._lock:
            self._write(self.en, " ")
            self._write(self.zh, " ")

    def stats(self) -> dict:
        return {"name": self.name, "dir": str(self.out_dir)}
