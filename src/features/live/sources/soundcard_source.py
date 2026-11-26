# -*- coding: utf-8 -*-
# @version 3.3.1
"""Windows 实时采集音源：系统内录（WASAPI loopback）与麦克风。

依赖 soundcard + numpy。**惰性导入**：没装依赖时功能页仍能打开，
只有点「开始」且选了内录/麦克风才会报可操作的错误。
输出契约：16 kHz / 单声道 / s16le，每 frame_ms 一帧（默认 100 ms = 3200 字节）。
"""
from __future__ import annotations

import threading
from typing import Iterator

from .base import Source

_INSTALL_HINT = ("实时采集需要 soundcard 与 numpy。请在工具箱内嵌 Python 安装：\n"
                 "  tools\\python\\python.exe -m pip install soundcard numpy")


def _deps():
    try:
        import numpy as np  # noqa: PLC0415
        import soundcard as sc  # noqa: PLC0415
    except ImportError as e:  # pragma: no cover
        raise ImportError(_INSTALL_HINT) from e
    return np, sc


def list_devices(kind: str = "loopback") -> list[dict]:
    """枚举可选设备；default 标记系统默认口，供 UI 直接展示。"""
    _, sc = _deps()
    if kind == "loopback":
        devs = [d for d in sc.all_microphones(include_loopback=True) if d.isloopback]
        default_name = sc.default_speaker().name
    elif kind == "mic":
        devs = list(sc.all_microphones(include_loopback=False))
        default_name = sc.default_microphone().name
    else:
        raise ValueError(f"unknown capture kind: {kind!r}")
    return [{"name": d.name, "channels": d.channels,
             "default": d.name == default_name} for d in devs]


def pick_device(kind: str, device: str = ""):
    """device 为空取系统默认口；否则按全名或子串匹配。"""
    _, sc = _deps()
    if kind == "loopback":
        devs = [d for d in sc.all_microphones(include_loopback=True) if d.isloopback]
        default_name = sc.default_speaker().name
    elif kind == "mic":
        devs = list(sc.all_microphones(include_loopback=False))
        default_name = sc.default_microphone().name
    else:
        raise ValueError(f"unknown capture kind: {kind!r}")
    if not devs:
        raise RuntimeError(f"no {kind} capture device available")
    if device:
        for d in devs:
            if d.name == device:
                return d
        for d in devs:
            if device in d.name:
                return d
        raise ValueError(f"{kind} device not found: {device!r}; "
                         f"available: {[d.name for d in devs]}")
    for d in devs:
        if d.name == default_name:
            return d
    return devs[0]


def to_s16le(data) -> bytes:
    """soundcard 的 float32 [-1,1] → 单声道 s16le。"""
    np, _ = _deps()
    a = np.asarray(data, dtype=np.float32)
    if a.ndim > 1:
        a = a.mean(axis=1) if a.shape[1] > 1 else a[:, 0]
    return (np.clip(a, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()


class SoundcardSource(Source):
    name = "soundcard"

    def __init__(self, kind: str = "loopback", device: str = "",
                 sample_rate: int = 16000, frame_ms: int = 100):
        self.kind = kind
        self.device = device or ""
        self.sample_rate = int(sample_rate)
        self.frame_ms = int(frame_ms)
        self.frame_size = int(self.sample_rate * self.frame_ms / 1000) * 2
        self._stopped = threading.Event()
        self.frames_emitted = 0
        self.active_device = ""
        self.error = ""

    def iter_frames(self) -> Iterator[bytes]:
        self._stopped.clear()
        self.frames_emitted = 0
        self.error = ""
        n = self.frame_size // 2
        try:
            dev = pick_device(self.kind, self.device)
        except Exception as e:  # noqa: BLE001
            self.error = str(e)
            raise
        self.active_device = dev.name
        with dev.recorder(samplerate=self.sample_rate, channels=1,
                          blocksize=n) as rec:
            while not self._stopped.is_set():
                pcm = to_s16le(rec.record(numframes=n))
                if len(pcm) < self.frame_size:
                    pcm = pcm.ljust(self.frame_size, b"\x00")
                self.frames_emitted += 1
                yield pcm[: self.frame_size]

    def stop(self) -> None:
        self._stopped.set()

    def stats(self) -> dict:
        return {"name": self.name, "kind": self.kind,
                "device": self.active_device or self.device,
                "frames_emitted": self.frames_emitted,
                "frame_ms": self.frame_ms, "error": self.error}
