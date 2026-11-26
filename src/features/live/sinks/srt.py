# -*- coding: utf-8 -*-
# @version 3.3.1
"""SRT 同步输出：边播边写，停止后即为可用的 .srt 文件。

设计
----
* 以 ``seq`` 为幂等键：云端「先原文、后补译文」会用同 seq 二次 publish，
  Sink 覆盖同一条并整体重写，不会产生重复字幕块。
* 每次 publish 都重写整份文件（N 条 cue 的 SRT 只有几十 KB），换来的是
  程序崩溃/强退时文件仍是**合法 SRT**，而不是半截块。
* 文件名带会话时间戳（``live_20261125-103000.srt``），不覆盖上一场。
* 双语：第一行译文、第二行原文；``bilingual=False`` 时只写译文。
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from ..cue import Cue
from .base import Sink


def _fmt_ms(ms: int) -> str:
    ms = max(0, int(ms))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, milli = divmod(rem, 1_000)
    return f"{h:02d}:{m:02d}:{s:02d},{milli:03d}"


class SrtSink(Sink):
    name = "srt"

    def __init__(self, out_dir: Path, filename: str = "live.srt",
                 bilingual: bool = True, min_duration_ms: int = 1200):
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.default_name = filename or "live.srt"
        self.bilingual = bool(bilingual)
        self.min_duration_ms = max(200, int(min_duration_ms))
        self.path = self.out_dir / self.default_name
        self._cues: dict[int, Cue] = {}
        self._lock = threading.RLock()
        self._ensure_file()

    # ------------------------------------------------------------------ session
    def _ensure_file(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as f:
            f.write("")

    def new_session(self) -> None:
        with self._lock:
            self._cues.clear()
            stem, ext = os.path.splitext(self.default_name)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            self.path = self.out_dir / f"{stem}_{stamp}{ext or '.srt'}"
            self._ensure_file()

    # ------------------------------------------------------------------ write
    def publish(self, cue: Cue) -> None:
        if cue.interim or not (cue.main or cue.sub):
            return
        with self._lock:
            self._cues[cue.seq] = cue
            self._rewrite()

    def _block_text(self, cue: Cue) -> str:
        main = (cue.main or "").strip()
        sub = (cue.sub or "").strip()
        if self.bilingual and sub and sub != main:
            return f"{main}\n{sub}" if main else sub
        return main or sub

    def _rewrite(self) -> None:
        ordered = [self._cues[k] for k in sorted(self._cues)]
        blocks: list[str] = []
        for i, cue in enumerate(ordered, 1):
            start = max(0, int(cue.t0_ms))
            end = start + max(self.min_duration_ms, int(cue.duration_ms))
            if i < len(ordered):
                next_start = max(0, int(ordered[i].t0_ms))
                if next_start > start:
                    end = min(end, next_start - 1)
                end = max(end, start + 200)
            text = self._block_text(cue)
            if not text:
                continue
            blocks.append(f"{len(blocks) + 1}\n"
                          f"{_fmt_ms(start)} --> {_fmt_ms(end)}\n{text}\n")
        body = "\n".join(blocks)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(body, encoding="utf-8")
        os.replace(tmp, self.path)

    def close(self) -> None:
        with self._lock:
            self._rewrite()

    def stats(self) -> dict:
        with self._lock:
            return {"name": self.name, "path": str(self.path),
                    "cues": len(self._cues), "bilingual": self.bilingual}
