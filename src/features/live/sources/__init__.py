# -*- coding: utf-8 -*-
# @version 3.3.1
"""音频源工厂：loopback（系统内录）/ mic（麦克风）/ wav（离线回归）。"""
from .base import Source
from .wav import WavSource

__all__ = ["Source", "WavSource", "build_source", "list_devices"]


def list_devices(kind: str = "loopback") -> list[dict]:
    from .soundcard_source import list_devices as _ld  # noqa: PLC0415
    return _ld(kind)


def build_source(cfg, name: str | None = None, **overrides) -> Source:
    kind = name or cfg.get("source", "type", "loopback")
    scfg = dict(cfg.section("source"))
    scfg.update(overrides)
    frame_ms = int(cfg.get("audio", "frame_ms", 100))
    sample_rate = int(cfg.get("audio", "sample_rate", 16000))
    if kind == "wav":
        path = cfg.resolve(scfg.get("wav") or cfg.get("source", "wav", ""))
        return WavSource(path,
                         realtime=bool(scfg.get("realtime", True)),
                         loop=bool(scfg.get("loop", False)),
                         frame_size=int(sample_rate * frame_ms / 1000) * 2)
    if kind in ("loopback", "mic"):
        from .soundcard_source import SoundcardSource  # noqa: PLC0415
        return SoundcardSource(kind=kind, device=scfg.get("device", ""),
                               sample_rate=sample_rate, frame_ms=frame_ms)
    raise ValueError(f"unknown source type: {kind!r} "
                     "(expected loopback | mic | wav)")
