# -*- coding: utf-8 -*-
"""
同名元数据文件（侧车文件 / sidecar）解析。

拖入或选择视频后，自动在同目录查找与视频同名的 .json / .txt 文件，
按其中内容回填标题、简介、标签、分区、创作声明，实现“按提供的文件填写”。

示例：
  D:\\Videos\\ep01.mp4
  D:\\Videos\\ep01.json   或   D:\\Videos\\ep01.txt

JSON 格式（与任务文件一致）：
  {"title": "...", "description": "...",
   "tags": ["明日方舟", "二次元"], "zone": ["游戏", "电子竞技"],
   "declaration": "无"}

TXT 格式（键值行，全角/半角冒号均可；简介可跨多行）：
  标题：My Arknights: Endfield
  简介：第一行简介
  第二行简介
  标签：明日方舟,二次元,策略游戏
  分区：游戏/电子竞技
  创作声明：无

TXT 简式（无任何键名时）：第一行视为标题，其余全部视为简介。
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SIDECAR_SUFFIXES = (".json", ".txt")

# 字段别名（全部小写比较）
_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "title": ("视频标题", "稿件标题", "标题", "title", "name"),
    "description": ("视频简介", "稿件简介", "简介", "视频描述", "描述",
                    "description", "desc", "intro", "introduct"),
    "tags": ("视频标签", "稿件标签", "标签", "tags", "tag"),
    "zone": ("分区", "栏目", "分类", "zone", "category"),
    "declaration": ("创作声明", "声明", "declaration", "statement"),
    "topics": ("参与话题", "话题", "topics", "topic"),
}

# 标签分隔符：英文逗号、中文逗号、顿号、分号、空白
_TAG_SPLIT_RE = re.compile(r"[,，、;；\s]+")
# 分区层级分隔符：斜杠（中英文）、大于号、竖线
_ZONE_SPLIT_RE = re.compile(r"\s*[/／>》|]\s*")


def _match_field(line: str) -> tuple[str | None, str]:
    """识别一行是否以“字段名 + 冒号”开头，返回 (规范字段名, 剩余内容)。"""
    stripped = line.strip()
    for canon, aliases in _FIELD_ALIASES.items():
        for alias in aliases:
            if stripped.lower().startswith(alias.lower()):
                rest = stripped[len(alias):].lstrip("：: \t")
                return canon, rest
    return None, ""


def _split_tags(raw: Any) -> list[str]:
    if isinstance(raw, list):
        seq = [str(x) for x in raw]
    else:
        seq = _TAG_SPLIT_RE.split(str(raw))
    out: list[str] = []
    for t in seq:
        t = t.strip()
        if t and t not in out:
            out.append(t)
    return out


def _split_zone(raw: Any) -> Any:
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    text = str(raw).strip()
    parts = [p for p in _ZONE_SPLIT_RE.split(text) if p]
    return parts if len(parts) > 1 else text


def _normalize(data: dict[str, Any]) -> dict[str, Any]:
    """统一字段类型：tags/topics 为列表、zone 为字符串或两级列表。"""
    result: dict[str, Any] = {}
    if data.get("title"):
        result["title"] = str(data["title"]).strip()
    if data.get("description") is not None:
        result["description"] = str(data["description"]).strip()
    if data.get("tags"):
        result["tags"] = _split_tags(data["tags"])
    if data.get("topics"):
        result["topics"] = _split_tags(data["topics"])
    if data.get("zone") not in (None, ""):
        result["zone"] = _split_zone(data["zone"])
    if data.get("declaration"):
        decl = str(data["declaration"]).strip()
        if decl not in ("（无）", "无需标注"):
            result["declaration"] = decl
    return result


def parse_txt(text: str) -> dict[str, Any]:
    """解析 TXT 侧车文件（键值行模式 / 无键简式模式）。"""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    nonempty = [ln for ln in lines if ln.strip()]
    if not nonempty:
        return {}

    # 没有任何键名行 → 简式：首行标题，其余为简介
    has_key = any(_match_field(ln)[0] is not None for ln in nonempty)
    if not has_key:
        return _normalize({
            "title": nonempty[0].strip(),
            "description": "\n".join(nonempty[1:]).strip(),
        })

    raw: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []

    def flush() -> None:
        if current is not None:
            raw[current] = "\n".join(buf).strip()

    for line in lines:
        key, rest = _match_field(line)
        if key is not None:
            flush()
            current = key
            buf = [rest] if rest else []
        elif current is not None:
            buf.append(line)
    flush()
    return _normalize(raw)


def parse_sidecar_file(path: str | Path) -> dict[str, Any]:
    """解析单个侧车文件，返回规范化字段字典。"""
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".json":
        data = json.loads(p.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError(f"侧车 JSON 根节点必须是对象: {p}")
        return _normalize(data)
    if suffix == ".txt":
        return parse_txt(p.read_text(encoding="utf-8-sig"))
    raise ValueError(f"不支持的侧车文件类型: {p}")


def find_sidecar(video_path: str | Path) -> Path | None:
    """在视频同目录查找同名 .json / .txt 侧车文件（.json 优先）。"""
    base = Path(video_path).with_suffix("")
    for suffix in SIDECAR_SUFFIXES:
        candidate = Path(str(base) + suffix)
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def load_for_video(video_path: str | Path) -> tuple[dict[str, Any], Path | None]:
    """按视频查找并解析侧车文件。

    :return: (字段字典, 命中的侧车文件路径；未找到时为 ({}, None))
    """
    sidecar = find_sidecar(video_path)
    if sidecar is None:
        return {}, None
    try:
        data = parse_sidecar_file(sidecar)
        logger.info("已解析侧车文件 %s，字段: %s",
                    sidecar.name, list(data.keys()))
        return data, sidecar
    except Exception as e:  # noqa: BLE001
        logger.warning("侧车文件解析失败 %s: %s", sidecar, e)
        return {}, sidecar
