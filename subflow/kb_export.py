# -*- coding: utf-8 -*-
# @version 2.2.5
"""知识库统一导出器（方案书阶段 3）：finesub 知识库主库 → 各工具，严格单向。

主库形态：SubFlow 根 knowledge/rendered/ 下的 markdown 副本（finesub
knowledge.sqlite 的人读可编辑层，下次运行会被收录，因此编辑此处即改主库）：

    rendered/
    ├─ common/     index.md + 条目md（作品/题材术语）
    ├─ streamer/   index.md + 条目md（主播术语）
    └─ style/      翻译风格（不导出，非术语）

主库行式（见 finesub examples/knowledge 样板）：
- index 行：``- key [类型] | 其他语言本名 | 别名 | 一句简介``（streamer 无 [类型]）
- 条目「档案」节：``- [本名] 源语言全名 / 中文定名 / 英文定名``、``- [别名] 顿号分隔``
- 条目术语节（节名自取）：``源语言|中文定名|别名|一句话描述``（描述可含竖线）

导出物（写 glossary/，不回写主库，杜绝双写冲突）：
- video-toolbox.tsv：VT 术语表（列：原文、译名、类别），对齐 wuwa_glossary.tsv 口径；
  源语言列与别名列逐个展开成行，最大化 AI 校准命中率
- maw-hotwords.txt：MAW CLI --hotword-file 热词表（每行一词）
- maw-context.txt：MAW CLI --context-file 上下文（条目名：定名（别名）—— 简介）

VT 自身的 learned_kb 校准知识库按增量同步机制单独管理，不纳入本导出回流。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import mosp_bridge

_EXPORT_TSV = "video-toolbox.tsv"
_EXPORT_HOTWORDS = "maw-hotwords.txt"
_EXPORT_CONTEXT = "maw-context.txt"

# 参与导出的主库类别目录（style 是翻译口味，不是术语，跳过）
_KB_CATEGORIES = ("common", "streamer")


@dataclass
class Term:
    src: str          # ASR 可能输出的原文（源语言词/别名）
    zh: str           # 中文定名
    category: str     # 类别（条目类型/术语节名）
    note: str = ""    # 一句话描述（仅进 MAW context）

    def key(self) -> tuple[str, str]:
        return (self.src, self.zh)


@dataclass
class KbStats:
    tsv_rows: int = 0
    hotwords: int = 0
    context_lines: int = 0
    entries: int = 0
    skipped_style: bool = False
    warnings: list[str] = field(default_factory=list)
    summary: list[str] = field(default_factory=list)


def _has_cjk(s: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in s)


def _split_alts(cell: str) -> list[str]:
    """别名格：顿号分隔（含全角/半角逗号容错）。"""
    return [p.strip() for p in re.split(r"[、，,]", cell) if p.strip()]


def _paren_split(name: str) -> tuple[str, list[str]]:
    """『原神（げんしん）』→ ('原神', ['げんしん'])；无括号原样返回。"""
    m = re.fullmatch(r"([^（(]+)[（(]([^）)]+)[）)]", name.strip())
    if m:
        return m.group(1).strip(), [m.group(2).strip()]
    return name.strip(), []


def parse_index_line(line: str) -> tuple[str, str, list[str], list[str], str] | None:
    """解析 index 行 → (key, 类型, 本名列表, 别名列表, 简介)；非数据行返回 None。

    行式 ``- key [类型] | 其他语言本名 | 别名 | 一句简介``；本名与别名按顿号分段
    （streamer 样板的本名一格含「中文、英文」多段）。
    """
    body = line.strip().lstrip("-").strip()
    if not body or body.startswith("#") or body.startswith("格式："):
        return None
    parts = [p.strip() for p in body.split("|")]
    if len(parts) < 2 or not parts[0]:
        return None
    key_cell = parts[0]
    type_tag = ""
    m = re.match(r"^(.*?)\s*\[([^\]]+)\]$", key_cell)
    if m:
        key_cell, type_tag = m.group(1).strip(), m.group(2).strip()
    names = _split_alts(parts[1]) if len(parts) > 1 else []
    alts = _split_alts(parts[2]) if len(parts) > 2 else []
    # 简介在最后一格且可含竖线：重新 join，避免按 | 拆列时截断
    note = "|".join(p.strip() for p in parts[3:]) if len(parts) >= 4 else ""
    return key_cell, type_tag, names, alts, note


def parse_entry(path: Path, default_category: str) -> tuple[list[Term], str, str]:
    """解析条目 md → (术语列表, 条目中文定名, 条目简介)。

    术语行：恰好以竖线分隔 ≥3 列、首列非空且非 [标记] 的行（行首 '-' 可选）；
    档案节 [本名]/[别名] 行单独解析成条目级术语。
    """
    text = mosp_bridge.read_text_any(path)
    title = ""
    terms: list[Term] = []
    entry_zh = ""
    seen_head_name = False
    in_comment = False  # 条目内 <!-- ... --> 多行注释：其中的行式示例含竖线，必须整块跳过
    for raw in text.splitlines():
        line = raw.strip()
        if in_comment:
            if "-->" in line:
                in_comment = False
            continue
        if line.startswith("<!--"):
            if "-->" not in line:
                in_comment = True
            continue
        line = line.lstrip("-").strip()
        if not line:
            continue
        if line.startswith("#") and not title:
            title = line.lstrip("#").strip()
            continue
        if line.startswith("格式："):
            continue
        meta = re.match(r"^\[(本名|别名)\]\s*(.+)$", line)
        if meta:
            if meta.group(1) == "本名":
                segs = [s.strip() for s in meta.group(2).split("/")]
                if len(segs) >= 2:
                    src0, paren = _paren_split(segs[0])
                    zh = segs[1]
                    entry_zh = zh
                    seen_head_name = True
                    for src in ([src0] if src0 else []) + paren:
                        if src and src != zh:
                            terms.append(Term(src, zh, default_category or title, ""))
            else:
                zh = entry_zh or title
                for alt in _split_alts(meta.group(2)):
                    if _has_cjk(alt) and alt == zh:
                        continue
                    terms.append(Term(alt, zh, default_category or title, ""))
            continue
        cols = [c.strip() for c in line.split("|")]
        # 术语行：首列非空、次列（中文定名）非空、至少 3 列；[标记] 开头的是元数据行
        if len(cols) >= 3 and cols[0] and cols[1] and not cols[0].startswith("["):
            # 描述在最后一格且可含竖线：重新 join 还原，避免截断
            note = "|".join(cols[3:]) if len(cols) >= 4 else ""
            terms.append(Term(cols[0], cols[1], default_category or title, note))
            # 别名列逐个展开（同一定名，多个源语言写法）
            for alt in _split_alts(cols[2] if len(cols) > 2 else ""):
                if alt and alt != cols[0]:
                    terms.append(Term(alt, cols[1], default_category or title, note))
    if not seen_head_name and title:
        entry_zh = title
    return terms, entry_zh, ""


def collect(cfg: "bridges.ToolConfig") -> tuple[list[Term], KbStats]:
    """遍历主库 rendered/ 收集全部术语（保序去重：同 (src, zh) 只留首条）。"""
    stats = KbStats()
    terms: list[Term] = []
    seen: set[tuple[str, str]] = set()
    rendered = cfg.knowledge_root / "rendered"
    if not rendered.exists():
        stats.warnings.append(f"主库 rendered 目录不存在: {rendered}（首次使用请先在 finesub 侧建立知识库）")
        return terms, stats
    for category in _KB_CATEGORIES:
        cat_dir = rendered / category
        if not cat_dir.exists():
            continue
        # index 行本身也是术语源，但别名一格混含假名/英文/中文，CJK 猜测不可靠：
        # 只按第二列（其他语言本名）定方向——段含汉字则 key 为源语言（streamer 型），
        # 段不含汉字则 key 为中文定名（common 型）；别名只收不含汉字的源语言变体。
        index = cat_dir / "index.md"
        if index.exists():
            for raw in mosp_bridge.read_text_any(index).splitlines():
                parsed = parse_index_line(raw)
                if not parsed:
                    continue
                key, _type_tag, names, alts, note = parsed
                pairs: list[tuple[str, str]] = []
                for seg in names:
                    if _has_cjk(seg):
                        pairs.append((key, seg))
                    else:
                        pairs.append((seg, key))
                zh = next((z for _s, z in pairs), "")
                for alt in alts:
                    if not _has_cjk(alt) and zh:
                        pairs.append((alt, zh))
                for src, zh2 in pairs:
                    if src and zh2 and src != zh2 and (src, zh2) not in seen:
                        seen.add((src, zh2))
                        terms.append(Term(src, zh2, category or _type_tag, note))
        # 条目 md（类别取条目名，比目录名对校准更有辨识度）
        for entry in sorted(cat_dir.glob("*.md")):
            if entry.name == "index.md":
                continue
            entry_terms, _zh, _note = parse_entry(entry, entry.stem)
            stats.entries += 1
            for t in entry_terms:
                if (t.src, t.zh) in seen:
                    continue
                seen.add((t.src, t.zh))
                terms.append(t)
    if (rendered / "style").exists():
        stats.skipped_style = True
    return terms, stats


def _dedup(terms: list[Term]) -> list[Term]:
    out: list[Term] = []
    seen: set[tuple[str, str]] = set()
    for t in terms:
        k = t.key()
        if k in seen or not t.src or not t.zh:
            continue
        seen.add(k)
        out.append(t)
    return out


def sync(cfg: "bridges.ToolConfig") -> KbStats:
    """执行一次单向导出，返回统计（含摘要文本）。幂等：全量重写三个导出物。"""
    terms, stats = collect(cfg)
    terms = _dedup(terms)
    glossary = cfg.glossary_dir
    glossary.mkdir(parents=True, exist_ok=True)

    tsv_path = glossary / _EXPORT_TSV
    lines = [f"# 字幕工具箱统一术语表（来源：finesub 知识库主库，kb_export 单向导出，勿手改）"]
    lines.append("# 原文\t译名\t类别")
    for t in terms:
        lines.append(f"{t.src}\t{t.zh}\t{t.category}")
    mosp_bridge.write_text(tsv_path, "\n".join(lines) + "\n", crlf=True)
    stats.tsv_rows = len(terms)

    hot_path = glossary / _EXPORT_HOTWORDS
    words: list[str] = []
    seen_words: set[str] = set()
    for t in terms:
        for w in (t.src, t.zh):
            if w and w not in seen_words:
                seen_words.add(w)
                words.append(w)
    mosp_bridge.write_text(hot_path, "\n".join(words) + "\n", crlf=False)
    stats.hotwords = len(words)

    ctx_path = glossary / _EXPORT_CONTEXT
    ctx_lines: list[str] = []
    seen_ctx: set[str] = set()
    for t in terms:
        if t.note and t.zh not in seen_ctx:
            seen_ctx.add(t.zh)
            ctx_lines.append(f"{t.zh}：{t.note}")
    mosp_bridge.write_text(ctx_path, "\n".join(ctx_lines) + "\n", crlf=False)
    stats.context_lines = len(ctx_lines)

    summary = [
        f"主库条目 {stats.entries} 个，导出术语 {stats.tsv_rows} 行 → {tsv_path.name}",
        f"MAW 热词 {stats.hotwords} 个 → {hot_path.name}",
        f"MAW 上下文 {stats.context_lines} 行 → {ctx_path.name}",
    ]
    if stats.skipped_style:
        summary.append("style/ 翻译风格目录按规范未导出")
    summary.extend(f"警告：{w}" for w in stats.warnings)
    stats.summary = summary
    return stats
