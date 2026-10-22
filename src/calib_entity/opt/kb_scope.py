# @version 2.5.3
"""作品维度隔离：防止 A 作品的专名被注入 B 作品的片源。

问题实证（2026-10-19）：

    Entity「水月」category = 角色/明日方舟，variants 含 Mizuki
    终末地片源走纯 bi 模式 -> 注入到模型 -> 模型把「水木茂」改成「水月茂」

根因不是模型，是 ``Entity.modes`` 只有**语言/流程维度**（bi/ja/ko/endobi），
没有**作品维度**。`bi` 是通用双语模式，于是所有作品的词条混在一个池子里。

隔离口径（保守）：

* 只隔离**专名类**：role / place / faction / person —— 跨作品出现基本必错；
* ``term``（术语）**不隔离**：同一 IP 下「源石」「感染者」这类通名可能通用，
  误隔离的代价比误注入更高；
* ``work`` 未知（category 为空或无作品名）的实体**一律保留**——不确定就不排斥。
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from ..spec import EntitySpec

#: 作品名（按「更具体优先」排序：终末地必须排在明日方舟之前）
WORK_PRIORITY: Tuple[str, ...] = (
    "终末地", "战双帕弥什", "塞尔达传说", "异环", "边狱巴士",
    "鸣潮", "明日方舟", "崩坏星穹铁道", "原神", "绝区零",
)

#: 只有这些类别参与跨作品隔离
STRICT_KINDS: Set[str] = {"role", "place", "faction", "person"}


def work_of(category: str) -> str:
    """从 category 里解析作品名。解析不出返回空串（= 不参与隔离）。"""
    c = category or ""
    if not c:
        return ""
    for w in WORK_PRIORITY:
        if w in c:
            return w
    return ""


def is_strict(e: EntitySpec) -> bool:
    return e.kind in STRICT_KINDS


def filter_registry(reg: Dict[str, EntitySpec], work: str
                    ) -> Tuple[Dict[str, EntitySpec], List[Tuple[str, str, str]]]:
    """按作品过滤实体。

    返回 ``(保留的对象, [(被排除的对象, 它属于的作品, 原因)])``。
    ``work`` 为空时不做任何过滤（全保留）。
    """
    if not work:
        return dict(reg), []
    kept: Dict[str, EntitySpec] = {}
    dropped: List[Tuple[str, str, str]] = []
    for c, e in reg.items():
        ew = work_of(e.category)
        if is_strict(e) and ew and ew != work:
            dropped.append((c, ew, f"{e.kind} 类专名，属于「{ew}」"))
            continue
        kept[c] = e
    return kept, dropped


def build_terms(reg: Dict[str, EntitySpec], mode: str, work: str = ""
                ) -> Dict[str, str]:
    """按「模式 + 作品」组装 ``{错形: 官方名}``（对象层口径）。

    与 ``ModeIndex.build`` 的差别：这里只取对象层可执行的 variants，
    并按作品隔离专名类实体（用于诊断「哪些词该进、哪些该拦」）。
    """
    kept, _ = filter_registry(reg, work)
    out: Dict[str, str] = {}
    for e in kept.values():
        if mode not in e.modes:
            continue
        for v in e.variants:
            if v and v != e.canonical:
                out.setdefault(v, e.canonical)
    return out


def _canonical_owner(reg: Dict[str, EntitySpec], word: str):
    """在对象库里反查某个形态属于哪个对象。

    先按 canonical 精确匹配，再按 variants 匹配；都落空返回 None。
    """
    if word in reg:
        return reg[word]
    for e in reg.values():
        if word in e.variants:
            return e
    return None


def filter_terms(engine, reg: Dict[str, EntitySpec], mode: str, work: str
                 ) -> Tuple[Dict[str, str], List[Tuple[str, str, str, str]]]:
    """**词条级**作品隔离（比对象级更彻底）。

    扁平表里大量词条的目标对象是空壳（无 variants/ctx），对象级隔离看不到它们；
    但它们的目标 canonical 往往有 category，于是可以反查作品。

    实证：``BILINGUAL_TERMS["Mizuki"] = "水月"``，而「水月」category=角色/明日方舟。
    对象级隔离拦不住（水月 variants 为空），词条级可以。

    返回 ``(保留的词条, [(错形, 目标, 所属作品, 原因)])``。
    """
    tname = getattr(engine, "_MODE_TERM_TABLE", {}).get(mode)
    table = dict(getattr(engine, tname, None) or {}) if tname else {}
    if not work:
        return table, []

    kept: Dict[str, str] = {}
    dropped: List[Tuple[str, str, str, str]] = []
    for wrong, right in table.items():
        owner = reg.get(right)
        if owner is None:
            kept[wrong] = right          # 目标对象未登记 -> 无法判定，保留
            continue
        ow = work_of(owner.category)
        if is_strict(owner) and ow and ow != work:
            dropped.append((wrong, right, ow, f"{owner.kind} 类专名，属于「{ow}」"))
            continue
        kept[wrong] = right
    return kept, dropped


def explain(reg: Dict[str, EntitySpec], mode: str, work: str,
            words: Iterable[str], engine=None) -> List[dict]:
    """逐词说明「进 / 不进」及原因（供 CLI 与日志）。

    判定顺序（有 engine 时）：词条级隔离 -> 当前模式表有无 -> 对象库有无。
    """
    kept, dropped = filter_registry(reg, work)
    dropped_map = {c: (w, why) for c, w, why in dropped}

    table: Dict[str, str] = {}
    term_blocked: Dict[str, Tuple[str, str, str]] = {}
    if engine is not None:
        tname = getattr(engine, "_MODE_TERM_TABLE", {}).get(mode)
        table = dict(getattr(engine, tname, None) or {}) if tname else {}
        _kept_terms, dterms = filter_terms(engine, reg, mode, work)
        for wrong, right, ow, why in dterms:
            term_blocked[wrong] = (right, ow, why)

    out = []
    for word in words:
        if word in term_blocked:
            right, ow, why = term_blocked[word]
            out.append({"word": word, "state": "blocked", "owner": right,
                        "why": why, "work": ow})
            continue

        if engine is not None and word not in table:
            owner = _canonical_owner(reg, word)
            if owner is not None:
                out.append({"word": word, "state": "mode-miss",
                            "owner": owner.canonical,
                            "why": f"当前模式 {mode} 的表里没有该错形"})
            else:
                out.append({"word": word, "state": "unknown", "why": "不在本模式表，也不在对象库"})
            continue

        owner = _canonical_owner(reg, word)
        if owner is None:
            target = table.get(word, "?")
            out.append({"word": word, "state": "kept", "owner": target,
                        "why": "在模式表里，目标对象未登记"})
            continue
        if owner.canonical in dropped_map:
            w, why = dropped_map[owner.canonical]
            out.append({"word": word, "state": "blocked", "owner": owner.canonical,
                        "why": why, "work": w})
        else:
            ow = work_of(owner.category)
            out.append({"word": word, "state": "kept", "owner": owner.canonical,
                        "why": f"{owner.kind}/{ow or '未标注'}"})
    return out


def coverage(reg: Dict[str, EntitySpec]) -> dict:
    """对象层的「作品可判定率」体检：多少对象能说清自己属于哪个作品。"""
    total = len(reg)
    by_work: Dict[str, int] = {}
    unknown = 0
    for e in reg.values():
        w = work_of(e.category)
        if w:
            by_work[w] = by_work.get(w, 0) + 1
        else:
            unknown += 1
    return {
        "objects": total,
        "work_tagged": total - unknown,
        "work_tagged_pct": round((total - unknown) / total * 100, 1) if total else 0.0,
        "unknown": unknown,
        "by_work": dict(sorted(by_work.items(), key=lambda kv: -kv[1])),
    }
