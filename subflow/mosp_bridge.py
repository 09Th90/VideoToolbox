# -*- coding: utf-8 -*-
# @version 2.4.0
"""SRT 与 MAW 字幕工程（.mosp）互转——subflow「人工校对」环节的交接桥。

规范依据 moys-asr-workflow 仓库 JSON_SCHEMA.md（moy.asr.project.v1）：
- 工程文件是 UTF-8 无 BOM、LF 换行、缩进 2 的 JSON（对齐 MAW project_io.write_mosp）；
- segments[*].start/end 全部是整数毫秒，end > start，建议按时间升序；
- 第三方生成工程时 waveform/spectral 等派生缓存可完全省略；items 可填 []，
  编辑器拆分字幕时会按字符比例自动插值时间点；
- text 可含 \\n（编辑器渲染为换行）；
- disabled=true 的段在预览与默认导出中被跳过，渲染回 SRT 时同样跳过。

交接用法：
    成品 SRT --srt_to_mosp()--> review/xxx.mosp --> MAW --server 打开，人工校对保存
    保存后的 .mosp --mosp_to_srt()--> review/xxx-reviewed.srt --> 烧录交付
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

MOSP_SCHEMA = "moy.asr.project.v1"

# 时间码：HH:MM:SS,ms（标准 SRT 逗号），容忍 HH:MM:SS.ms（部分工具误用点号）
_CUE_TIME = re.compile(
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*"
    r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})"
)


@dataclass
class Cue:
    start_ms: int
    end_ms: int
    text: str

    def normalized_text(self) -> str:
        """块内多行合成单串，行间以 \\n 连接（不落 CRLF，写出层统一翻译）。"""
        return "\n".join(line.strip("\ufeff\r") for line in self.text.splitlines()).strip()


def srt_time_to_ms(h: str, m: str, s: str, ms: str) -> int:
    return ((int(h) * 60 + int(m)) * 60 + int(s)) * 1000 + int(ms.ljust(3, "0")[:3])


def ms_to_srt_time(total_ms: int) -> str:
    total_ms = max(0, int(total_ms))
    h, rem = divmod(total_ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def parse_srt(text: str) -> list[Cue]:
    """宽容解析 SRT：剥 BOM、统一换行、跳过序号行与无法识别的行。"""
    cues: list[Cue] = []
    start_ms = end_ms = None
    body: list[str] = []
    for raw in text.splitlines():
        line = raw.strip("\ufeff").rstrip("\r")
        m = _CUE_TIME.search(line)
        if m:
            if start_ms is not None and body:
                cues.append(Cue(start_ms, end_ms, "\n".join(body)))
            start_ms = srt_time_to_ms(m.group(1), m.group(2), m.group(3), m.group(4))
            end_ms = srt_time_to_ms(m.group(5), m.group(6), m.group(7), m.group(8))
            body = []
        elif start_ms is not None:
            if line.strip() == "":
                cues.append(Cue(start_ms, end_ms, "\n".join(body)))
                start_ms, body = None, []
            elif not (line.strip().isdigit() and not body):
                body.append(line)
    if start_ms is not None and body:
        cues.append(Cue(start_ms, end_ms, "\n".join(body)))
    return [c for c in cues if c.normalized_text()]


def read_text_any(path: Path) -> str:
    """读文本：UTF-8 优先，兼容 utf-8-sig 与 GBK 产物；剔除 BOM。"""
    data = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def write_text(path: Path, text: str, *, crlf: bool) -> None:
    """写出 UTF-8 无 BOM。crlf=True 供 SRT（Windows 本地生态），False 供 .mosp JSON。

    先把任意来源的换行（\\r\\n / \\r）归一成 \\n，再交给 newline 参数统一翻译，
    避免对已含 CRLF 的文本二次翻译出 \\r\\r\\n（行间多空行的经典坑）。
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\r\n" if crlf else "\n") as f:
        f.write(text)


def cues_to_srt(cues: list[Cue]) -> str:
    blocks = []
    for i, cue in enumerate(cues, 1):
        blocks.append(f"{i}\n{ms_to_srt_time(cue.start_ms)} --> {ms_to_srt_time(cue.end_ms)}\n{cue.text}")
    return "\n\n".join(blocks) + "\n"


def srt_to_mosp(srt_path: Path, media_path: Path | None, mosp_path: Path, *, language: str = "") -> int:
    """把 SRT 转成可直接被 MAWE 打开的 .mosp 工程，返回段数。"""
    cues = parse_srt(read_text_any(srt_path))
    segments = []
    for i, cue in enumerate(cues, 1):
        segments.append(
            {
                "id": f"main-{i:03d}",
                "start": int(cue.start_ms),
                "end": int(cue.end_ms),
                "text": cue.normalized_text(),
                "items": [],
            }
        )
    project = {
        "schema": MOSP_SCHEMA,
        "media": str(media_path).replace("\\", "/") if media_path else "",
        "language": language or "",
        "language_source": "hint" if language else "unknown",
        # 中文/日文等字符型语言按字符计量切句，英文按词；仅影响编辑器切句方式
        "split_mode": "word" if language.lower() in ("en", "eng") else "continuous",
        "timestamp_granularity": "segment",
        "model": "finesub",
        "preserve_punctuation": True,
        "segments": segments,
    }
    write_text(mosp_path, json.dumps(project, ensure_ascii=False, indent=2) + "\n", crlf=False)
    return len(segments)


def mosp_to_srt(mosp_path: Path, srt_path: Path) -> int:
    """把校对保存后的 .mosp 渲染回 SRT（跳过 disabled 段），返回段数。"""
    project = json.loads(read_text_any(mosp_path))
    segments = project.get("segments")
    if not isinstance(segments, list):
        raise ValueError(f"{mosp_path.name}: 不是合法的 MAW 工程（缺少 segments 数组）")
    cues = [
        Cue(int(seg["start"]), int(seg["end"]), str(seg.get("text", "")))
        for seg in segments
        if not seg.get("disabled") and str(seg.get("text", "")).strip()
    ]
    write_text(srt_path, cues_to_srt(cues), crlf=True)
    return len(cues)
