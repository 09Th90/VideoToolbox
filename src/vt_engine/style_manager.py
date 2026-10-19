# @version 2.4.0
"""字幕样式管理（自研，替代 videocaptioner.core.subtitle.style_manager）。

可观察契约（用户样式文件与 ffmpeg 渲染都依赖它，必须逐字节一致）：

* 样式文件为 JSON：``ass-<名>.json`` / ``rounded-<名>.json``（无前缀亦可），
  按「精确文件名 → 带前缀文件名（mode 优先）→ JSON name 字段」顺序查找；
* :meth:`SubtitleStyle.to_ass_string` 产出的 ASS V4+ Styles 段是
  **ffmpeg 的输入格式**——字段顺序、``&H00BBGGRR`` 颜色序、``\\q1``
  尾缀任一改动都会改变烧录字幕外观；
* 样式目录默认取引擎数据目录 ``resource/subtitle_style``（用户已有
  样式文件在那里），随包默认样式由 ``EnginePaths.seed_subtitle_styles``
  补齐（不覆盖已有文件）。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

from vt_engine.log import setup_logger

logger = setup_logger("vt_engine.style")

__all__ = [
    "StyleMode",
    "SecondaryStyle",
    "SubtitleStyle",
    "style_id_from_filename",
    "list_styles",
    "load_style",
    "available_style_names",
    "save_style",
    "default_styles_dir",
]


class StyleMode(Enum):
    """渲染模式。"""

    ASS = "ass"
    ROUNDED = "rounded"


@dataclass
class SecondaryStyle:
    """ASS 模式的双语第二行样式。"""

    font_name: str = "Arial"
    font_size: int = 30
    color: str = "#ffffff"
    outline_color: str = "#000000"
    outline_width: float = 2.0
    spacing: float = 0.8


@dataclass
class SubtitleStyle:
    """统一字幕样式（ASS 与圆角背景两种模式合用一个数据类）。"""

    # -- 元数据 --
    name: str = ""
    description: str = ""
    mode: StyleMode = StyleMode.ASS

    # -- 公共 --
    font_name: str = "Noto Sans SC"
    font_size: int = 42

    # -- ASS 模式字段 --
    primary_color: str = "#65ff5a"
    outline_color: str = "#000000"
    outline_width: float = 2.0
    bold: bool = True
    spacing: float = 3.2
    margin_bottom: int = 30
    secondary: Optional[SecondaryStyle] = None

    # -- 圆角背景模式字段 --
    text_color: str = "#000000"
    bg_color: str = "#0de3ffe5"
    corner_radius: int = 14
    padding_h: int = 24
    padding_v: int = 18
    line_spacing: int = 12
    letter_spacing: int = 1
    margin_bottom_rounded: int = 40

    # ---------------- 转换 ----------------
    def to_ass_string(self) -> str:
        """渲染为 ASS V4+ Styles 段（ffmpeg 输入格式，字节级契约）。"""
        primary = _hex_to_ass(self.primary_color)
        outline = _hex_to_ass(self.outline_color)
        bold_flag = -1 if self.bold else 0

        sec = self.secondary or SecondaryStyle(
            font_name=self.font_name,
            font_size=int(self.font_size * 0.7))
        sec_color = _hex_to_ass(sec.color)
        sec_outline = _hex_to_ass(sec.outline_color)

        header = (
            "[V4+ Styles]\n"
            "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,"
            "OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,"
            "ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,"
            "Alignment,MarginL,MarginR,MarginV,Encoding"
        )
        default_line = (
            f"Style: Default,{self.font_name},{self.font_size},"
            f"{primary},&H000000FF,{outline},&H00000000,"
            f"{bold_flag},0,0,0,100,100,{self.spacing},0,1,"
            f"{self.outline_width},0,2,10,10,{self.margin_bottom},1,\\q1"
        )
        secondary_line = (
            f"Style: Secondary,{sec.font_name},{sec.font_size},"
            f"{sec_color},&H000000FF,{sec_outline},&H00000000,"
            f"{bold_flag},0,0,0,100,100,{sec.spacing},0,1,"
            f"{sec.outline_width},0,2,10,10,{self.margin_bottom},1,\\q1"
        )
        return f"{header}\n{default_line}\n{secondary_line}"

    def to_rounded_dict(self) -> dict:
        """圆角渲染器所需的扁平 dict。"""
        return {
            "font_name": self.font_name,
            "font_size": self.font_size,
            "text_color": self.text_color,
            "bg_color": self.bg_color,
            "corner_radius": self.corner_radius,
            "padding_h": self.padding_h,
            "padding_v": self.padding_v,
            "margin_bottom": self.margin_bottom_rounded,
            "line_spacing": self.line_spacing,
            "letter_spacing": self.letter_spacing,
        }

    def to_json_dict(self) -> dict:
        """序列化为 JSON dict（保存用）。"""
        d: dict = {"name": self.name, "description": self.description,
                   "mode": self.mode.value}
        if self.mode == StyleMode.ROUNDED:
            d.update(self.to_rounded_dict())
        else:
            d.update({
                "font_name": self.font_name,
                "font_size": self.font_size,
                "primary_color": self.primary_color,
                "outline_color": self.outline_color,
                "outline_width": self.outline_width,
                "bold": self.bold,
                "spacing": self.spacing,
                "margin_bottom": self.margin_bottom,
            })
            if self.secondary:
                d["secondary"] = asdict(self.secondary)
        return d

    # ---------------- 工厂 ----------------
    @classmethod
    def from_json(cls, data: dict) -> "SubtitleStyle":
        """从 JSON dict 构造（未指定 mode 时按字段自动判别）。"""
        if "mode" in data:
            mode = StyleMode(data["mode"])
        elif any(k in data for k in ("bg_color", "text_color",
                                     "corner_radius")):
            mode = StyleMode.ROUNDED
        else:
            mode = StyleMode.ASS
        sec_data = data.get("secondary")
        secondary = SecondaryStyle(**sec_data) \
            if isinstance(sec_data, dict) else None

        if mode == StyleMode.ROUNDED:
            return cls(
                name=data.get("name", ""),
                description=data.get("description", ""),
                mode=mode,
                font_name=data.get("font_name", cls.font_name),
                font_size=data.get("font_size", cls.font_size),
                text_color=data.get("text_color", cls.text_color),
                bg_color=data.get("bg_color", cls.bg_color),
                corner_radius=data.get("corner_radius",
                                       cls.corner_radius),
                padding_h=data.get("padding_h", cls.padding_h),
                padding_v=data.get("padding_v", cls.padding_v),
                margin_bottom_rounded=data.get(
                    "margin_bottom", cls.margin_bottom_rounded),
                line_spacing=data.get("line_spacing", cls.line_spacing),
                letter_spacing=data.get("letter_spacing",
                                        cls.letter_spacing),
            )

        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            mode=mode,
            font_name=data.get("font_name", cls.font_name),
            font_size=data.get("font_size", cls.font_size),
            primary_color=data.get("primary_color", cls.primary_color),
            outline_color=data.get("outline_color", cls.outline_color),
            outline_width=data.get("outline_width", cls.outline_width),
            bold=data.get("bold", cls.bold),
            spacing=data.get("spacing", cls.spacing),
            margin_bottom=data.get("margin_bottom", cls.margin_bottom),
            secondary=secondary,
        )

    @classmethod
    def from_file(cls, path: Path) -> "SubtitleStyle":
        """从文件加载（.json 或旧版 .txt ASS 样式）。"""
        content = Path(path).read_text(encoding="utf-8")
        if Path(path).suffix == ".json":
            return cls.from_json(json.loads(content))
        if "[V4+ Styles]" in content or "Style:" in content:
            return _parse_ass_txt(content, Path(path).stem)
        raise ValueError(f"Unrecognized style file format: {path}")

    @classmethod
    def from_rounded_dict(cls, data: dict) -> "SubtitleStyle":
        """从扁平 dict（界面配置）构造圆角样式。"""
        return cls.from_json({**data, "mode": "rounded"})


# ---------------- 模块级助手 ----------------

def style_id_from_filename(filename: str) -> str:
    """从文件名提取用户可见样式 ID：``ass-default.json`` → ``default``。"""
    stem = Path(filename).stem
    for prefix in ("ass-", "rounded-"):
        if stem.startswith(prefix):
            return stem[len(prefix):]
    return stem


def default_styles_dir() -> Path:
    """默认样式目录（引擎数据目录 resource/subtitle_style）。"""
    from vt_engine.paths import default_engine_paths
    return default_engine_paths().subtitle_style_path


def list_styles(styles_dir: Optional[Path] = None) -> List[SubtitleStyle]:
    """列出目录下全部样式（损坏文件跳过并告警，不抛）。"""
    if styles_dir is None:
        styles_dir = default_styles_dir()
    if not Path(styles_dir).exists():
        return []
    result: List[SubtitleStyle] = []
    for f in sorted(Path(styles_dir).glob("*.json")):
        try:
            style = SubtitleStyle.from_file(f)
            if not style.name:
                style.name = style_id_from_filename(f.name)
            result.append(style)
        except Exception:  # noqa: BLE001
            logger.warning("Failed to load style %s", f)
    return result


def load_style(name: str, styles_dir: Optional[Path] = None,
               mode: Optional[str] = None) -> Optional[SubtitleStyle]:
    """按名加载样式（精确文件名 → 带前缀文件名（mode 优先）→ name 字段）。"""
    if styles_dir is None:
        styles_dir = default_styles_dir()
    if not Path(styles_dir).exists():
        return None

    exact = Path(styles_dir) / f"{name}.json"
    if exact.exists():
        try:
            return SubtitleStyle.from_file(exact)
        except Exception:  # noqa: BLE001
            pass

    prefixes = ["ass-", "rounded-"]
    if mode == "rounded":
        prefixes = ["rounded-", "ass-"]
    for prefix in prefixes:
        prefixed = Path(styles_dir) / f"{prefix}{name}.json"
        if prefixed.exists():
            try:
                return SubtitleStyle.from_file(prefixed)
            except Exception:  # noqa: BLE001
                pass

    for f in Path(styles_dir).glob("*.json"):
        try:
            style = SubtitleStyle.from_file(f)
            if style.name == name or style_id_from_filename(f.name) == name:
                return style
        except Exception:  # noqa: BLE001
            pass
    return None


def available_style_names(styles_dir: Optional[Path] = None) -> List[str]:
    """全部样式名（去重排序）。"""
    return sorted({s.name for s in list_styles(styles_dir)})


def save_style(style: SubtitleStyle, styles_dir: Optional[Path] = None,
               filename: str = "") -> Path:
    """保存样式为 ``<mode>-<name>.json``（已存在则覆盖）。返回文件路径。"""
    if styles_dir is None:
        styles_dir = default_styles_dir()
    d = Path(styles_dir)
    d.mkdir(parents=True, exist_ok=True)
    if not filename:
        prefix = "rounded-" if style.mode == StyleMode.ROUNDED else "ass-"
        filename = "%s%s.json" % (prefix, style.name or "untitled")
    path = d / filename
    path.write_text(json.dumps(style.to_json_dict(), ensure_ascii=False,
                               indent=2), encoding="utf-8")
    return path


# ---------------- 内部 ----------------

def _hex_to_ass(hex_color: str) -> str:
    """``#RRGGBB`` / ``#AARRGGBB`` → ASS ``&H..BBGGRR``。"""
    h = hex_color.lstrip("#")
    if len(h) == 8:
        a, r, g, b = h[0:2], h[2:4], h[4:6], h[6:8]
        return f"&H{a}{b}{g}{r}"
    if len(h) == 6:
        r, g, b = h[0:2], h[2:4], h[4:6]
        return f"&H00{b}{g}{r}"
    return "&H00ffffff"


def _ass_color_to_hex(ass_color: str) -> str:
    """ASS ``&HAABBGGRR`` → ``#RRGGBB``。"""
    c = ass_color.strip().lstrip("&Hh")
    if len(c) == 8:
        b, g, r = c[2:4], c[4:6], c[6:8]
    elif len(c) == 6:
        b, g, r = c[0:2], c[2:4], c[4:6]
    else:
        return "#ffffff"
    return f"#{r}{g}{b}"


def _parse_ass_txt(content: str, stem: str = "") -> SubtitleStyle:
    """解析旧版 .txt（ASS V4+ Style 行）。"""
    kwargs: dict = {"name": stem, "mode": StyleMode.ASS}
    secondary_kwargs: dict = {}
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("Style: Default,"):
            parts = line.split(",")
            kwargs["font_name"] = parts[1]
            kwargs["font_size"] = int(parts[2])
            kwargs["primary_color"] = _ass_color_to_hex(parts[3])
            kwargs["outline_color"] = _ass_color_to_hex(parts[5])
            kwargs["bold"] = parts[7].strip() == "-1"
            kwargs["spacing"] = float(parts[13])
            kwargs["outline_width"] = float(parts[16])
            kwargs["margin_bottom"] = int(parts[21])
        elif line.startswith("Style: Secondary,"):
            parts = line.split(",")
            secondary_kwargs["font_name"] = parts[1]
            secondary_kwargs["font_size"] = int(parts[2])
            secondary_kwargs["color"] = _ass_color_to_hex(parts[3])
            secondary_kwargs["outline_color"] = _ass_color_to_hex(parts[5])
            secondary_kwargs["spacing"] = float(parts[13])
            secondary_kwargs["outline_width"] = float(parts[16])
    if secondary_kwargs:
        kwargs["secondary"] = SecondaryStyle(**secondary_kwargs)
    return SubtitleStyle(**kwargs)
