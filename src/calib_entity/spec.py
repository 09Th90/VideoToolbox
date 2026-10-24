# @version 2.6.0
"""对象规格层：把扁平表 + ENTITIES 折叠成唯一的 ``EntitySpec`` 集合。

与主脚本 ``_kb_view()`` 的差别（也是本层存在的理由）：

1. **modes 不再丢**：``_kb_view()`` 只从扁平表折叠 modes，纯元数据实体会得到空
   modes；本层额外并入 ``ENTITIES.modes``，并把「扁平表命中」与「实体声明」合并。
2. **重复登记可观测**：同一 canonical 被登记 N 次时不再静默 later-wins，而是聚合
   notes 分段并记 ``dup_entries`` 问题，供 lint 定为 error。
3. **别名与错形分层**：``aliases``（官方简称/别译）与 ``variants``（ASR/机翻错形）
   分字段存放。当前脚本里两者混装，导致 audit 把「已是官方简称」误报成漏校。
   本层不擅自改语义：只给 ``alias_candidate`` 标记，人工确认后才进 aliases。
4. **kind 归一**：从 category 前缀解析出 role/place/faction/term/work/ost/... ，
   供 mention 消歧（P2）按对象类型决定译名。

并行开发期铁律：本模块只读主脚本，不 patch、不回写。
"""
from __future__ import annotations

import dataclasses
import hashlib
import importlib
import json
import os
import re
import sys
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------- 引导

ENGINE_MODULE = "subtitle_calib_merged"


def project_root() -> str:
    """定位程序根（含主脚本 ``subtitle_calib_merged.py`` 的目录）。

    优先 cwd（打包/安装后 cwd 就是程序根）；否则从本文件向上最多找 4 层。
    包位于 ``src/calib_entity/``，所以回退路径是「向上 2 层到 src，再向上到根」。
    """
    cwd = os.getcwd()
    if os.path.isfile(os.path.join(cwd, ENGINE_MODULE + ".py")):
        return cwd
    cur = os.path.dirname(os.path.abspath(__file__))
    for _ in range(4):
        cur = os.path.dirname(cur)
        if os.path.isfile(os.path.join(cur, ENGINE_MODULE + ".py")):
            return cur
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_engine():
    """import 主脚本（只读）。禁用自动同步，避免 import 期碰远端状态。"""
    root = project_root()
    if root not in sys.path:
        sys.path.insert(0, root)
    os.environ.setdefault("VT_NO_SYNC", "1")
    return importlib.import_module(ENGINE_MODULE)


# ---------------------------------------------------------------- 类别

#: category 前缀 -> kind（顺序敏感，先匹配先得）
_KIND_PREFIXES: Tuple[Tuple[str, str], ...] = (
    ("曲目", "ost"),
    ("角色", "role"),
    ("地名", "place"),
    ("势力", "faction"),
    ("组织", "faction"),
    ("术语", "term"),
    ("概念", "term"),
    ("作品", "work"),
    ("公司", "company"),
    ("厂商", "company"),
    ("主播", "person"),
    ("人物", "person"),
    ("乐理", "theory"),
    ("活动", "event"),
    ("版本", "version"),
)


def kind_of(category: str) -> str:
    """category 字符串 -> 归一 kind。空/未知返回 ``unknown``。"""
    c = (category or "").strip()
    if not c:
        return "unknown"
    for prefix, kind in _KIND_PREFIXES:
        if c.startswith(prefix) or ("/" + prefix) in c or ("·" + prefix) in c:
            return kind
    return "unknown"


#: 疑为官方缩写的形态：全大写、2~6 位、含数字亦可（NTE / COD / PGR / SSR）
_ABBR_RX = re.compile(r"^[A-Z][A-Z0-9]{1,5}$")


# ---------------------------------------------------------------- 数据模型


@dataclasses.dataclass(frozen=True)
class EntitySpec:
    """一个对象的完整规格。``id`` 即 canonical（自然主键，改名需迁移）。"""

    id: str
    canonical: str
    kind: str = "unknown"
    category: str = ""
    modes: Tuple[str, ...] = ()
    en: str = ""
    ja: str = ""
    ko: str = ""
    aliases: Tuple[str, ...] = ()
    variants: Tuple[str, ...] = ()
    ctx: Tuple[Tuple[str, str], ...] = ()
    exclude: Tuple[str, ...] = ()
    parent: str = ""
    notes: Tuple[str, ...] = ()
    issues: Tuple[str, ...] = ()
    sources: Tuple[str, ...] = ()
    #: ENTITIES 里登记过几次（0 = 只有扁平表键对，没有对象身份）
    entity_entries: int = 0

    # -- 便捷视图 ------------------------------------------------

    @property
    def key(self) -> str:
        """ASCII 稳定引用（文件名/日志/交叉表）：e + md5(canonical)[:8]。"""
        return "e" + hashlib.md5(self.canonical.encode("utf-8")).hexdigest()[:8]

    @property
    def executable(self) -> bool:
        """是否携带可执行知识（变体或条件规则）。空壳对象对校准零贡献。"""
        return bool(self.variants or self.ctx)

    @property
    def wrong_forms(self) -> Tuple[str, ...]:
        """全部「需要改掉的形态」= 无条件变体 + 条件错形。"""
        seen: List[str] = []
        for w in list(self.variants) + [w for _rx, w in self.ctx if w]:
            if w and w not in seen:
                seen.append(w)
        return tuple(seen)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "key": self.key,
            "canonical": self.canonical,
            "kind": self.kind,
            "category": self.category,
            "modes": list(self.modes),
            "en": self.en,
            "ja": self.ja,
            "ko": self.ko,
            "aliases": list(self.aliases),
            "variants": list(self.variants),
            "ctx": [{"ref_regex": rx, "wrong": w} for rx, w in self.ctx],
            "exclude": list(self.exclude),
            "parent": self.parent,
            "notes": list(self.notes),
            "issues": list(self.issues),
            "sources": list(self.sources),
            "entity_entries": self.entity_entries,
        }


def _add(seq: List[str], value: str) -> None:
    if value and value not in seq:
        seq.append(value)


# ---------------------------------------------------------------- 折叠


def build_registry(engine=None) -> Dict[str, EntitySpec]:
    """折叠扁平表 + ENTITIES -> ``{canonical: EntitySpec}``（已去重）。

    折叠顺序：无条件变体表 -> 英文行修正表 -> ctx 表 -> exclude 表 -> ENTITIES。
    同一 canonical 的多条 ENTITIES 登记会聚合到同一对象（notes 保留分段）。
    """
    eng = engine or load_engine()
    acc: Dict[str, dict] = {}

    def slot(canonical: str) -> dict:
        return acc.setdefault(canonical, {
            "modes": [], "variants": [], "ctx": [], "exclude": [],
            "notes": [], "sources": [], "en": "", "ja": "", "ko": "",
            "category": "", "parent": "", "entries": 0,
        })

    # 1) 无条件变体表
    for mode, tname in getattr(eng, "_MODE_TERM_TABLE", {}).items():
        table = getattr(eng, tname, None) or {}
        for wrong, right in table.items():
            if not wrong or not right or wrong == right:
                continue
            s = slot(right)
            _add(s["modes"], mode)
            _add(s["variants"], wrong)
            _add(s["sources"], "flat:" + tname)

    # 2) 英文参考行修正表（目标通常不是中文官方名，单挂 fix-en）
    for wrong, right in (getattr(eng, "EN_LINE_TERM_FIXES", None) or {}).items():
        if not wrong or not right or wrong == right:
            continue
        s = slot(right)
        _add(s["modes"], "fix-en")
        _add(s["variants"], wrong)
        _add(s["sources"], "flat:EN_LINE_TERM_FIXES")

    # 3) 条件变体（ctx）
    for mode, cname in getattr(eng, "_MODE_CTX_TABLE", {}).items():
        for item in (getattr(eng, cname, None) or []):
            rx, wrong, right = (list(item) + [None, None, None])[:3]
            if not right:
                continue
            s = slot(right)
            _add(s["modes"], mode)
            pair = (str(rx), str(wrong or ""))
            if pair not in s["ctx"]:
                s["ctx"].append(pair)
            _add(s["sources"], "ctx:" + cname)

    # 4) 负向排除
    for wrong, payload in (getattr(eng, "EXCLUDE_CONTEXT", None) or {}).items():
        try:
            right, rxs = payload
        except (TypeError, ValueError):
            continue
        if not right:
            continue
        s = slot(right)
        _add(s["modes"], "bi")
        _add(s["exclude"], str(wrong))
        for rx in rxs or ():
            _add(s["sources"], "exclude:" + str(rx))

    # 5) 实体声明（en/ja/ko/category/note/modes/别名候选）
    for e in getattr(eng, "ENTITIES", ()) or ():
        s = slot(e.canonical)
        s["entries"] += 1
        for m in (e.modes or ()):
            _add(s["modes"], m)
        for fld in ("en", "ja", "ko", "category"):
            val = getattr(e, fld, "") or ""
            if val and not s[fld]:
                s[fld] = val
        if getattr(e, "note", ""):
            _add(s["notes"], e.note)
        for v in (e.variants or ()):
            _add(s["variants"], v)
        for rx, wrong in (e.ctx or ()):
            pair = (str(rx), str(wrong or ""))
            if pair not in s["ctx"]:
                s["ctx"].append(pair)
        for rx in (e.exclude or ()):
            _add(s["exclude"], str(rx))

    # 6) 收尾：构造不可变规格 + 诊断
    out: Dict[str, EntitySpec] = {}
    for canonical, s in acc.items():
        issues: List[str] = []
        variants = tuple(s["variants"])
        ctx = tuple(s["ctx"])

        if not s["modes"]:
            issues.append("no_modes")
        if not (variants or ctx):
            issues.append("hollow")
        if not (s["en"] or s["ja"] or s["ko"]):
            issues.append("no_i18n")
        if s["entries"] > 1:
            issues.append("dup_entries:%d" % s["entries"])

        # 别名候选：全大写缩写形态（只标记，不改语义）。
        #   两条都必须满足，否则宁可不报（大写形态多数是 ASR 误听，如 IMATH/MJO/VUA）：
        #     ① 不是官方外文名的大小写变体（HSIN 之于 Hsin 属 ASR 大写）；
        #     ② note 里能找到该缩写本身，且 note 含官方/简称/即 等依据字样。
        official_upper = {
            part.strip().upper()
            for field in (s["en"], s["ja"], s["ko"])
            for part in str(field).split("/")
            if part.strip()
        }
        note_blob = " ".join(s["notes"])
        for v in variants:
            if not (_ABBR_RX.match(v) and v != canonical and v.upper() not in official_upper):
                continue
            if v in note_blob and re.search(r"官方|简称|又名|即|译名", note_blob):
                issues.append("alias_candidate:" + v)
        # 风险：变体是自身官方名的真子串（替换后可能自吞）
        for v in variants:
            if 2 <= len(v) < len(canonical) and v in canonical:
                issues.append("self_substring:" + v)

        out[canonical] = EntitySpec(
            id=canonical,
            canonical=canonical,
            kind=kind_of(s["category"]),
            category=s["category"],
            modes=tuple(s["modes"]),
            en=s["en"], ja=s["ja"], ko=s["ko"],
            aliases=(),                    # 显式别名当前为空，等人工确认 alias_candidate
            variants=variants,
            ctx=ctx,
            exclude=tuple(s["exclude"]),
            parent=s["parent"],
            notes=tuple(s["notes"]),
            issues=tuple(issues),
            sources=tuple(s["sources"]),
            entity_entries=s["entries"],
        )
    return out


# ---------------------------------------------------------------- 统计 / 导出


def summary(reg: Dict[str, EntitySpec]) -> dict:
    """对象层体检摘要（供 CLI 打印与报告引用）。"""
    total = len(reg)
    exe = [e for e in reg.values() if e.executable]
    hollow = [e for e in reg.values() if not e.executable]
    dup = [e for e in reg.values() if any(i.startswith("dup_entries") for i in e.issues)]
    no_mode = [e for e in reg.values() if "no_modes" in e.issues]

    def _ratio(n: int) -> float:
        return round(n / total * 100, 1) if total else 0.0

    return {
        "objects": total,
        "executable": len(exe),
        "executable_ratio_pct": _ratio(len(exe)),
        "entity_objects": sum(1 for e in reg.values() if e.entity_entries),
        "objectified_ratio_pct": _ratio(
            sum(1 for e in reg.values() if e.entity_entries)),
        "hollow": len(hollow),
        "hollow_ost": sum(1 for e in hollow if e.kind == "ost"),
        "dup_canonical": len(dup),
        "dup_extra_entries": sum(
            int(i.split(":")[1]) - 1 for e in dup for i in e.issues
            if i.startswith("dup_entries")),
        "no_modes": len(no_mode),
        "has_en": sum(1 for e in reg.values() if e.en),
        "has_ja": sum(1 for e in reg.values() if e.ja),
        "has_ko": sum(1 for e in reg.values() if e.ko),
        "variants_total": sum(len(e.variants) for e in reg.values()),
        "ctx_total": sum(len(e.ctx) for e in reg.values()),
        "alias_candidates": sum(
            1 for e in reg.values() for i in e.issues if i.startswith("alias_candidate:")),
        "by_kind": _count_by(reg, lambda e: e.kind),
        "by_modes": _count_modes(reg),
    }


def _count_by(reg: Dict[str, EntitySpec], fn) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for e in reg.values():
        k = fn(e)
        out[k] = out.get(k, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def _count_modes(reg: Dict[str, EntitySpec]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for e in reg.values():
        for m in e.modes:
            out[m] = out.get(m, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def export_json(reg: Dict[str, EntitySpec], path: str) -> str:
    """写出对象库 JSON（P0 产物）。返回写入路径。"""
    data = {
        "schema": "calib-entity/1",
        "source": ENGINE_MODULE,
        "summary": summary(reg),
        "objects": [reg[k].to_dict() for k in sorted(reg, key=lambda c: (-len(reg[c].variants), c))],
    }
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return path
