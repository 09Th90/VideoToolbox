# @version 2.6.0
"""对象级体检（P0）。

检查项与等级：

error（阻断，应立刻修）
  dup_canonical    同一 canonical 在 ENTITIES 里重复登记（身份不唯一）
  multi_target     同一模式内，同一错形被指向多个官方名（字符串层无法表达歧义）
  longkey_order    ctx 里短键排在长键之前（会被短键抢跑，产出残串）

warn（需人工裁决）
  alias_candidate  疑似官方缩写/别译混在 variants 里（会制造 audit 假阳性）
  self_substring   变体是自身官方名的真子串（替换后可能自吞）
  cascade_substring 变体是其它对象官方名的子串（替换后可能二次命中）
  no_modes         对象没有任何适用片源模式
  hollow           无变体、无 ctx 的空壳对象（ost 类降为 info）

info（补全提示）
  no_i18n          缺 en/ja/ko，audit 锚点对它失明
  hollow_ost       曲名类空壳（预期行为，无需处理）

所有条目都带 ``object``（canonical）与 ``detail``，便于直接生成人工待办。
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from .spec import EntitySpec, kind_of


def _rec(code: str, severity: str, obj: str, detail: str) -> dict:
    return {"code": code, "severity": severity, "object": obj, "detail": detail}


# ---------------------------------------------------------------- 单项检查


def check_dup_canonical(registry: Dict[str, EntitySpec], engine) -> List[dict]:
    """ENTITIES 里同一 canonical 登记次数 >1。"""
    out = []
    for e in registry.values():
        n = next((int(i.split(":")[1]) for i in e.issues if i.startswith("dup_entries:")), 1)
        if n > 1:
            out.append(_rec("dup_canonical", "error", e.canonical,
                            f"ENTITIES 登记 {n} 次（应合并为 1 个对象）"))
    return out


def check_multi_target(engine, limit: int = 200) -> List[dict]:
    """同模式内同一错形 -> 多个官方名。"""
    out: List[dict] = []
    for mode, cname in getattr(engine, "_MODE_CTX_TABLE", {}).items():
        seen: Dict[str, set] = {}
        for item in (getattr(engine, cname, None) or []):
            rx, wrong, right = (list(item) + [None, None, None])[:3]
            if wrong and right:
                seen.setdefault(wrong, set()).add(right)
        for wrong, rights in seen.items():
            if len(rights) > 1:
                out.append(_rec(
                    "multi_target", "error", wrong,
                    f"[{mode}] 「{wrong}」→ " + " / ".join(sorted(rights))
                    + "（靠规则顺序模拟优先级）"))
                if len(out) >= limit:
                    return out
    return out


def check_longkey_order(engine, limit: int = 400) -> List[dict]:
    """ctx 列表里短键抢在长键之前（同模式、同目标、互为子串）。"""
    out: List[dict] = []
    for mode, cname in getattr(engine, "_MODE_CTX_TABLE", {}).items():
        lst = getattr(engine, cname, None) or []
        for i, item in enumerate(lst):
            rx, w1, r1 = (list(item) + [None, None, None])[:3]
            if not w1 or not r1:
                continue
            for item2 in lst[i + 1:]:
                _rx2, w2, r2 = (list(item2) + [None, None, None])[:3]
                if w2 and r2 and w2 != w1 and w1 in w2 and r2 == r1:
                    out.append(_rec(
                        "longkey_order", "error", r1,
                        f"[{mode}] 短键「{w1}」排在长键「{w2}」之前（会被抢跑）"))
                    if len(out) >= limit:
                        return out
    return out


def check_alias_candidates(registry: Dict[str, EntitySpec]) -> List[dict]:
    """variants 里疑似官方缩写的形态（全大写 2~6 位）。不改语义，只提示。"""
    out = []
    for e in registry.values():
        cands = [i.split(":", 1)[1] for i in e.issues if i.startswith("alias_candidate:")]
        if cands:
            out.append(_rec("alias_candidate", "warn", e.canonical,
                            "疑为官方缩写：" + "、".join(cands) +
                            "（应进 aliases，而非 variants）"))
    return out


def check_self_substring(registry: Dict[str, EntitySpec]) -> List[dict]:
    out = []
    for e in registry.values():
        subs = [i.split(":", 1)[1] for i in e.issues if i.startswith("self_substring:")]
        if subs:
            out.append(_rec("self_substring", "warn", e.canonical,
                            "变体是自身官方名子串：" + "、".join(subs) +
                            "（须确认是否有防叠字包装）"))
    return out


def check_cascade_substring(registry: Dict[str, EntitySpec], limit: int = 200) -> List[dict]:
    """同模式内：甲的变体 ⊂ 乙的官方名（替换到乙后可能被甲二次命中）。"""
    by_mode: Dict[str, List[EntitySpec]] = {}
    for e in registry.values():
        for m in e.modes:
            if m == "fix-en":
                continue
            by_mode.setdefault(m, []).append(e)

    out: List[dict] = []
    for mode, ents in by_mode.items():
        canons = [(e.canonical, e) for e in ents if len(e.canonical) >= 3]
        for owner in ents:
            for v in owner.variants:
                if len(v) < 2:
                    continue
                for canon, target in canons:
                    if target is owner or v == canon:
                        continue
                    if v in canon:
                        out.append(_rec(
                            "cascade_substring", "warn", owner.canonical,
                            f"[{mode}] 变体「{v}」是 {canon!r} 的子串"))
                        if len(out) >= limit:
                            return out
    return out


def check_registry_hygiene(registry: Dict[str, EntitySpec]) -> List[dict]:
    out: List[dict] = []
    for e in registry.values():
        if "no_modes" in e.issues:
            out.append(_rec("no_modes", "warn", e.canonical,
                            f"无适用模式（kind={e.kind}）"))
        if "hollow" in e.issues:
            sev = "info" if e.kind == "ost" else "warn"
            out.append(_rec("hollow_ost" if sev == "info" else "hollow", sev,
                            e.canonical, "无变体、无 ctx（对校准零贡献）"))
        if "no_i18n" in e.issues:
            out.append(_rec("no_i18n", "info", e.canonical,
                            "缺 en/ja/ko，audit 锚点失明"))
    return out


# ---------------------------------------------------------------- 汇总


def run_lint(registry: Dict[str, EntitySpec], engine=None, cascade: bool = True) -> dict:
    eng = engine or _engine()
    recs: List[dict] = []
    recs += check_dup_canonical(registry, eng)
    recs += check_multi_target(eng)
    recs += check_longkey_order(eng)
    recs += check_alias_candidates(registry)
    recs += check_self_substring(registry)
    if cascade:
        recs += check_cascade_substring(registry)
    recs += check_registry_hygiene(registry)

    buckets = {"error": [], "warn": [], "info": []}
    for r in recs:
        buckets.setdefault(r["severity"], []).append(r)
    by_code: Dict[str, int] = {}
    for r in recs:
        by_code[r["code"]] = by_code.get(r["code"], 0) + 1
    return {
        "counts": {k: len(v) for k, v in buckets.items()},
        "by_code": dict(sorted(by_code.items(), key=lambda kv: -kv[1])),
        "errors": buckets["error"],
        "warnings": buckets["warn"],
        "infos": buckets["info"],
    }


def render_markdown(result: dict, limit: int = 30) -> str:
    c = result["counts"]
    L = [
        "# 对象级体检报告",
        "",
        f"error **{c.get('error', 0)}** | warn **{c.get('warn', 0)}** | info **{c.get('info', 0)}**",
        "",
    ]
    if result.get("by_code"):
        L.append("按检查项：" + "、".join(f"`{k}`={v}" for k, v in result["by_code"].items()))
        L.append("")
    titles = {"error": ("ERROR（阻断）", "errors"),
              "warn": ("WARN（人工裁决）", "warnings"),
              "info": ("INFO（补全提示）", "infos")}
    for sev, (title, key) in titles.items():
        rows = result.get(key) or []
        if not rows:
            continue
        L += [f"## {title}", "", "| 对象 | 代码 | 说明 |", "|---|---|---|"]
        for r in rows[:limit]:
            L.append(f"| {r['object']} | `{r['code']}` | {r['detail']} |")
        if len(rows) > limit:
            L.append(f"| … | | 另有 {len(rows) - limit} 条 |")
        L.append("")
    return "\n".join(L)


_ENGINE = None


def _engine():
    global _ENGINE
    if _ENGINE is None:
        from .spec import load_engine
        _ENGINE = load_engine()
    return _ENGINE
