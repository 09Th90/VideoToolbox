# -*- coding: utf-8 -*-
# @version 3.1.3
"""校准改动的最小实体证据包。

Jev 看不到本地对象库；只给它一句 old/new 会让模型凭记忆猜官方译名。
本模块把对象库中的官方名、作品、类别、别名、已知错形和备注压缩成一个小包，
随每条改动一起送入 shadow 复核。它只读本地知识，不生成替换文本。
"""
from __future__ import annotations

from typing import Dict, List, Optional

SCHEMA_VERSION = "vt.calibrate.evidence.v1"
_MAX_TEXT = 160
_BAD_KEYS = {" the ", " a ", " an ", " of ", " to ", " and ", " is ", " in ", " on "}


def _load_registry():
    try:
        from calib_entity import spec as spec_mod
        return spec_mod.build_registry(spec_mod.load_engine()), "local_kb+wiki"
    except Exception:  # noqa: BLE001 — 证据层不可用不能阻断校准
        return {}, "unavailable"


def _works(category: str) -> str:
    for w in ("终末地", "战双帕弥什", "鸣潮", "明日方舟",
              "崩坏星穹铁道", "原神", "绝区零", "边狱巴士", "异环"):
        if w in (category or ""):
            return w
    return ""


def _find_in_text(text: str, registry: Dict[str, object]) -> Optional[object]:
    hits = [c for c in registry
            if c and c.strip() and c.lower() not in _BAD_KEYS and c in (text or "")]
    return registry[max(hits, key=len)] if hits else None


def _find_entity(old: str, new: str, why: str,
                 registry: Dict[str, object]) -> Optional[object]:
    """在 new/why 中找本次改动的目标对象；优先 new 里最长的官方名。"""
    if not registry:
        return None
    target = _find_in_text(new, registry)
    if target is not None:
        return target
    return _find_in_text(why, registry)


def _matched_wrongs(old: str, entity) -> List[str]:
    """old 中真实出现、且属于目标对象的已知错形。"""
    out = []
    for w in getattr(entity, "wrong_forms", ()) or ():
        if w and w in old:
            out.append(str(w))
    return out[:16]


def build_evidence(old: str, new: str, why: str = "",
                   registry: Optional[Dict[str, object]] = None) -> dict:
    """返回单条改动的证据包；找不到对象时给出明确 missing，不臆造官方名。"""
    if registry is None:
        registry, source = _load_registry()
    else:
        source = "provided"
    entity = _find_entity(old, new, why, registry)
    if entity is None:
        return {"schema_version": SCHEMA_VERSION, "status": "missing",
                "source": source, "official": "",
                "why": "本地对象库未匹配到 new/why 中的目标对象"}
    work = _works(getattr(entity, "category", "") or "")
    note = " | ".join(str(x) for x in (getattr(entity, "notes", ()) or ()) if x)
    evidence = {
        "schema_version": SCHEMA_VERSION, "status": "ok", "source": source,
        "official": entity.canonical,
        "kind": getattr(entity, "kind", "") or "unknown",
        "category": getattr(entity, "category", "") or "",
        "work": work,
        "en": getattr(entity, "en", "") or "",
        "ja": getattr(entity, "ja", "") or "",
        "ko": getattr(entity, "ko", "") or "",
        "aliases": list(getattr(entity, "aliases", ()) or ())[:8],
        "known_wrong_forms": _matched_wrongs(old, entity),
        "note": note[:_MAX_TEXT],
    }
    # why 声明的目标与 new 实际目标不一致 = 目标冲突，明确降级。
    claimed = _find_in_text(why, registry)
    if claimed is not None and claimed.canonical != entity.canonical:
        evidence["status"] = "conflict"
        evidence["claimed_target"] = claimed.canonical
    # 机械可判定的“干净替换”只作证据，不代替 Jev 的语义判断。
    clean = False
    used = ""
    for w in evidence["known_wrong_forms"]:
        if w and w != entity.canonical and old.replace(w, entity.canonical) == new:
            clean, used = True, w
            break
    evidence["clean_replacement"] = clean
    evidence["replaced_form"] = used
    evidence["official_in_new"] = entity.canonical in new
    return evidence


def evidence_text(evidence: dict) -> str:
    """把证据 JSON 压成一句可直接判读的中文事实卡。"""
    if not evidence:
        return "本地无证据。"
    status = evidence.get("status")
    if status == "missing":
        return "本地对象库未匹配到目标对象，无法核实官方名。"
    official = evidence.get("official") or ""
    kind = evidence.get("kind") or "unknown"
    work = evidence.get("work") or "未标注作品"
    if status == "conflict":
        return ("目标冲突：why 声明的是「%s」，但 new 命中的是「%s」（%s/%s）；"
                "这不是同一实体。" % (evidence.get("claimed_target") or "未知",
                                     official, kind, work))
    wrongs = evidence.get("known_wrong_forms") or []
    wrong = "、".join(wrongs) if wrongs else "无"
    clean = "是" if evidence.get("clean_replacement") else "否"
    return ("官方目标「%s」（%s/%s）；旧文命中已知错形：%s；"
            "new 是否只把该错形替换成官方名：%s。" % (official, kind, work, wrong, clean))


def compact_for_prompt(evidence: dict) -> dict:
    """去掉空字段，控制 state 体积；status 永远保留，便于模型识别冲突。"""
    keep_status = True
    drop = ("schema_version", "source", "why", "official_in_new")
    out = {}
    for k, v in evidence.items():
        if k in drop or v in ("", None, [], {}, False):
            continue
        out[k] = v
    if keep_status and "status" in evidence:
        out["status"] = evidence["status"]
    out["text"] = evidence_text(evidence)
    return out


__all__ = ["SCHEMA_VERSION", "build_evidence", "compact_for_prompt"]
