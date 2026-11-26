# -*- coding: utf-8 -*-
# @version 3.3.1
"""字幕条目模型与双语行解析（源：vt-web-server/itxw/cue.py）。

本地 Index-Echo 的两行 ``--ask`` 输出不符合上游三行配方（引擎会打印
``2 malformed subtitle lines``），且默认 ``format=json`` 使 ``segments`` 恒空，
因此双语配对必须在本模块按**行序**完成，不能依赖字符集猜角色。
"""
from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass, field

TIMESTAMP_RE = re.compile(
    r"^\s*\[\d{1,2}:\d{2}(?:\.\d{1,2})?-\d{1,2}:\d{2}(?:\.\d{1,2})?\]\s*"
)


def _is_han(ch: str) -> bool:
    return "\u4e00" <= ch <= "\u9fff"


def _has_letters(s: str) -> bool:
    return any(_is_han(c) or (c.isalpha() and ord(c) < 128) for c in s)


def script(s: str) -> str:
    han = sum(1 for c in s if _is_han(c))
    lat = sum(1 for c in s if c.isalpha() and ord(c) < 128)
    if han and han >= lat:
        return "zh"
    if lat:
        return "en"
    return "?"


def clean_lines(text: str | None) -> list[str]:
    """剥离时间戳 / 空行 / 无字母行 / 相邻重复行。"""
    out: list[str] = []
    for raw in (text or "").splitlines():
        ln = TIMESTAMP_RE.sub("", raw).strip()
        if not ln or not _has_letters(ln):
            continue
        if out and out[-1] == ln:
            continue
        out.append(ln)
    return out


def order_pairs(text: str | None) -> list[tuple[str, str]]:
    """按行序解析出 [(main=译文, sub=原文)]，与 ITX v1.3 语义一致。"""
    lines = clean_lines(text)
    if not lines:
        return []
    if len(lines) == 1:
        return [(lines[0], "")]
    scripts = [script(ln) for ln in lines]
    alternating = len(lines) % 2 == 0 and all(
        scripts[i] != scripts[i + 1] for i in range(0, len(lines), 2)
    )
    if alternating:
        return [(lines[i + 1], lines[i]) for i in range(0, len(lines), 2)]
    zh = [ln for ln, s in zip(lines, scripts) if s == "zh"]
    en = [ln for ln, s in zip(lines, scripts) if s == "en"]
    if zh and en:
        return [(" ".join(en), " ".join(zh))]
    return [(" ".join(lines), "")]


def pair_cloud(transcript: str, translation: str) -> tuple[str, str]:
    """云端通路：ASR 出原文，翻译出译文。返回 (main=译文, sub=原文)。"""
    src = (transcript or "").strip()
    dst = (translation or "").strip()
    if not dst:
        return (src, "")
    return (dst, src)


@dataclass
class Cue:
    seq: int
    main: str                      # 大字：译文
    sub: str                       # 小字：原文
    backend: str = "local"
    degraded: bool = False         # 仅有原文、无译文
    fallback_from: str = ""        # 由哪个云端后端降级而来
    interim: bool = False          # 预识别快照，终版到达后按 seq 覆盖
    t0_ms: int = 0
    duration_ms: int = 0
    created: float = field(default_factory=time.time)

    @property
    def start_ms(self) -> int:
        return max(0, int(self.t0_ms))

    @property
    def end_ms(self) -> int:
        return max(self.start_ms + 1, int(self.t0_ms) + max(0, int(self.duration_ms)))

    @classmethod
    def from_local_text(cls, text: str, *, seq: int, t0_ms: int = 0,
                        duration_ms: int = 0, backend: str = "local",
                        degraded: bool = False,
                        fallback_from: str = "") -> list["Cue"]:
        cues = []
        for main, sub in order_pairs(text):
            cues.append(cls(seq=seq, main=main, sub=sub, backend=backend,
                            degraded=degraded or not sub,
                            fallback_from=fallback_from, t0_ms=t0_ms,
                            duration_ms=duration_ms))
        return cues

    @classmethod
    def from_cloud(cls, transcript: str, translation: str, *, seq: int,
                   t0_ms: int = 0, duration_ms: int = 0, backend: str = "cloud",
                   interim: bool = False) -> "Cue":
        main, sub = pair_cloud(transcript, translation)
        return cls(seq=seq, main=main, sub=sub, backend=backend,
                   degraded=not sub and not interim, t0_ms=t0_ms,
                   duration_ms=duration_ms, interim=interim)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def key(self) -> int:
        """seq 幂等键：同一段重跑结果按 seq upsert，不追加第二条。"""
        return self.seq
