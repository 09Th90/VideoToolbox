# -*- coding: utf-8 -*-
# @version 3.3.1
"""输出广播工厂：控制台 / JSONL / 文本接力 / SRT。"""
from .base import Broadcast, Sink
from .console import ConsoleSink
from .jsonl import JsonlSink
from .srt import SrtSink
from .text import TextFileSink

__all__ = ["Sink", "Broadcast", "ConsoleSink", "JsonlSink", "SrtSink",
           "TextFileSink", "build_sinks"]


def build_sinks(cfg) -> Broadcast:
    bus = Broadcast()
    if cfg.get("sinks", "console", False):
        bus.add(ConsoleSink())
    out = cfg.path("sinks", "text_dir")
    if cfg.get("sinks", "jsonl", True):
        bus.add(JsonlSink(out / "cues.jsonl"))
    if cfg.get("sinks", "text_files", True):
        bus.add(TextFileSink(out))
    if cfg.get("sinks", "srt", True) and cfg.get("srt", "enabled", True):
        bus.add(SrtSink(out,
                        filename=cfg.get("srt", "filename", "live.srt"),
                        bilingual=bool(cfg.get("srt", "bilingual", True)),
                        min_duration_ms=int(cfg.get("srt", "min_duration_ms", 1200))))
    return bus
