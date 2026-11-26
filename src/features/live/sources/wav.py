# -*- coding: utf-8 -*-
# @version 3.3.1
"""WAV 文件音源：离线回归与无声卡环境的验证入口。

要求 16 kHz / 单声道 / 16-bit；不符合时给出明确错误（不静默重采样）。
realtime=True 时按帧时长 pacing，模拟真实采集速度。
"""
from __future__ import annotations

import time
import wave
from pathlib import Path
from typing import Iterator

from .base import Source


class WavSource(Source):
    name = "wav"

    def __init__(self, path, realtime: bool = True, loop: bool = False,
                 frame_size: int = 3200):
        self.path = Path(path) if path else Path()
        self.realtime = bool(realtime)
        self.loop = bool(loop)
        self.frame_size = int(frame_size)
        self._stopped = False
        self.frames_emitted = 0
        self.error = ""

    def _check(self, w: wave.Wave_read) -> None:
        if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (16000, 1, 2):
            raise ValueError(
                "WAV must be 16kHz/mono/s16le, got "
                f"{w.getframerate()}Hz/{w.getnchannels()}ch/"
                f"{w.getsampwidth() * 8}bit: {self.path}")

    def iter_frames(self) -> Iterator[bytes]:
        if not str(self.path) or not self.path.is_file():
            raise FileNotFoundError(f"WAV not found: {self.path}")
        pace = self.frame_size / 32000.0
        self._stopped = False
        while not self._stopped:
            with wave.open(str(self.path), "rb") as w:
                self._check(w)
                while not self._stopped:
                    chunk = w.readframes(self.frame_size // 2)
                    if not chunk:
                        break
                    if len(chunk) < self.frame_size:
                        chunk = chunk.ljust(self.frame_size, b"\x00")
                    yield chunk
                    self.frames_emitted += 1
                    if self.realtime:
                        time.sleep(pace)
            # 补 7 帧静音，让 VAD 的静音收尾条件闭合
            if not self._stopped:
                for _ in range(7):
                    yield b"\x00" * self.frame_size
                    self.frames_emitted += 1
                    if self.realtime:
                        time.sleep(pace)
            if not self.loop:
                break

    def stop(self) -> None:
        self._stopped = True

    def stats(self) -> dict:
        return {"name": self.name, "path": str(self.path),
                "frames_emitted": self.frames_emitted,
                "realtime": self.realtime, "loop": self.loop,
                "error": self.error}
