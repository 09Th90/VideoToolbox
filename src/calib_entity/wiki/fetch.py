# @version 2.4.1
"""抓取四个 wiki 的角色名单，并回填对象库缺失的作品归属。

输出补丁结构（不直接改源文件）::

    {
      "schema": "calib-entity-wiki/1",
      "sources": {...},                       # 站点与抓取时间
      "works": {"明日方舟": {"count": 428, "names": [...]}, ...},
      "patches": [                            # 逐对象补全建议
        {"id": "余烬", "work": "终末地", "action": "set-work",
         "from": "", "evidence": "endfield.wiki.gg/Category:Operators"}
      ],
      "coverage": {"before": {...}, "after": {...}}
    }
"""
from __future__ import annotations

import datetime as _dt
import json
import os
from typing import Dict, Iterable, List, Optional, Tuple

from .client import WikiClient
from .sources import SITES, is_latin, normalize_title


def fetch_work(work: str, pause: float = 0.15) -> dict:
    cfg = SITES[work]
    cli = WikiClient(cfg["api"], pause=pause)
    cats = cfg.get("categories") or [cfg.get("category")]
    titles: List[str] = []
    per_cat: Dict[str, int] = {}
    names: List[str] = []
    seen = set()
    name_sources: Dict[str, List[str]] = {}

    def _add(title: str, source: str) -> None:
        for n in normalize_title(work, title):
            if n not in seen:
                seen.add(n)
                names.append(n)
            name_sources.setdefault(n, []).append(source)

    # 分类来源（角色/声骸/武器等：专名密度高，置信度高）
    for cat in cats:
        got = cli.category_members(cat)
        per_cat[cat] = len(got)
        titles.extend(got)
        for t in got:
            _add(t, "cat:" + cat)

    # 前缀来源（名词注释/世界观：含大量通用词，置信度低）
    for pf in (cfg.get("prefixes") or []):
        got = cli.allpages_prefix(pf)
        per_cat["prefix:" + pf] = len(got)
        titles.extend(got)
        for t in got:
            _add(t, "prefix:" + pf)

    return {
        "work": work, "api": cfg["api"], "categories": cats,
        "per_category": per_cat,
        "raw": titles, "names": names, "name_sources": name_sources,
        "error": cli.last_error,
    }


def fetch_all(works: Optional[Iterable[str]] = None, pause: float = 0.15) -> Dict[str, dict]:
    out = {}
    for w in (works or SITES.keys()):
        out[w] = fetch_work(w, pause=pause)
    return out


# ---------------------------------------------------------------- 匹配


def match(reg: dict, fetched: Dict[str, dict]) -> dict:
    """把 wiki 名单与对象库的 canonical 对齐。

    只做「中文名 → 作品」的精确匹配；终末地名单是英文，额外用 en 字段匹配。
    """
    name2work: Dict[str, str] = {}
    name2conf: Dict[str, str] = {}
    ambiguous = set()
    conflicts: List[Tuple[str, str, str]] = []
    for work, data in fetched.items():
        for n in data["names"]:
            if is_latin(n):
                continue                     # 英文名走 en 匹配，不参与中文精确匹配
            srcs = (data.get("name_sources") or {}).get(n) or []
            conf = "high" if any(s.startswith("cat:") for s in srcs) else "low"
            prev = name2work.get(n)
            if prev and prev != work:
                conflicts.append((n, prev, work))
                # 两边都是高置信才算真歧义；低置信（名词注释类通用词）直接让位
                if conf == "high" and name2conf.get(n) == "high":
                    ambiguous.add(n)
                    name2work.pop(n, None)
                    name2conf.pop(n, None)
                elif conf == "high":
                    name2work[n] = work
                    name2conf[n] = conf
                continue
            if n not in ambiguous:
                name2work[n] = work
                name2conf[n] = conf

    # 英文名（终末地）：用对象库 en 字段反查
    en2work: Dict[str, str] = {}
    for work, data in fetched.items():
        for n in data["names"]:
            if is_latin(n):
                en2work.setdefault(n.lower(), work)

    patches, matched = [], {}
    for c, e in reg.items():
        work = name2work.get(c)
        conf = name2conf.get(c, "")
        evidence = f"分类匹配（{conf}）" if work else ""
        if not work and e.en:
            for part in str(e.en).split("/"):
                p = part.strip().lower()
                if p and p in en2work:
                    work = en2work[p]
                    conf = "medium"
                    evidence = f"英文名匹配 en={part.strip()}"
                    break
        if work:
            matched[c] = work
            patches.append({
                "id": c, "work": work, "action": "set-work",
                "confidence": conf,
                "evidence": evidence,
                "category": e.category,
            })

    missing = [c for c in reg if c not in matched]
    return {
        "name2work": name2work,
        "en2work": en2work,
        "conflicts": conflicts,
        "matched": matched,
        "patches": patches,
        "unmatched": missing,
    }


def build_report(reg: dict, fetched: Dict[str, dict], matched: dict,
                 patches: Optional[List[dict]] = None) -> dict:
    total = len(reg)
    before = 0
    for c, e in reg.items():
        cat = e.category or ""
        if any(w in cat for w in ("鸣潮", "明日方舟", "终末地", "战双")):
            before += 1
    conf = {"high": 0, "medium": 0, "low": 0}
    newly = 0
    for p in (patches or []):
        c = p.get("confidence", "low")
        conf[c] = conf.get(c, 0) + 1
        if not p.get("category"):
            newly += 1                     # 原本无 category = 真补全（其余是印证已有标注）
    after = before + newly
    return {
        "objects": total,
        "work_tagged_before": before,
        "work_tagged_before_pct": round(before / total * 100, 1) if total else 0.0,
        "work_matched_by_wiki": len(matched),
        "work_newly_tagged": newly,
        "work_tagged_after": after,
        "work_tagged_after_pct": round(after / total * 100, 1) if total else 0.0,
        "patch_confidence": conf,
        "wiki_counts": {w: len(d["names"]) for w, d in fetched.items()},
        "wiki_errors": {w: d["error"] for w, d in fetched.items() if d.get("error")},
    }


def save(payload: dict, path: str) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return path
