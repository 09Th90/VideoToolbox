# @version 2.5.3
"""知识注入安全化：外文官方名不该当「错形」。

主程序 ``calib_ai_agent.build_rules()``（第 386-389 行）有这一段：

    for alt in (e.get("en"), e.get("ja"), e.get("ko")):
        if alt:
            wrongs.append(alt)          # ← 官方外文名被塞进「错形」列表

设计意图是让模型能把听到的英文名对上官方中文（合理），但副作用是：

* 规则表里出现 ``Mizuki → 水月``，模型据此把中文行里的「水木茂」改成「水月茂」；
* ``select_rules()`` 按「错形出现在参考行」判 warm → ``Mizuki Shigeru`` 命中 → 必然注入；
* 规则条数被外文名撑大（bi 模式 2144 条里相当一部分来自这一层）。

本模块给出安全口径：

    variants + ctx   -> 替换规则（唯一允许模型据此改中文行的依据）
    en / ja / ko     -> 锚点（只用于「这段在讲这个实体」的判定，禁止作为替换指令）

并叠加作品维度隔离（``kb_scope``）。
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from ..spec import EntitySpec
from . import kb_scope

MIN_WRONG_LEN = 2          # 与主程序 MIN_WRONG_LEN 对齐

Rule = Tuple[str, str]


def _split_names(e: EntitySpec) -> List[str]:
    """en/ja/ko 可能写成 ``Sheen / Hsin``，按斜杠拆开。"""
    out: List[str] = []
    for field in (e.en, e.ja, e.ko):
        for part in re.split(r"\s*/\s*", str(field or "")):
            p = part.strip()
            if p:
                out.append(p)
    return out


def build_rules_safe(reg: Dict[str, EntitySpec], mode: str, work: str = "",
                     include_names: bool = False
                     ) -> Tuple[List[Rule], List[Tuple[str, str]], Dict[str, List[str]]]:
    """返回 ``(替换规则, 负向排除, 锚点名)``。

    与主程序 ``build_rules`` 的差异：
      1. 默认**不把 en/ja/ko 当错形**（``include_names=True`` 可复现旧行为）；
      2. 按作品隔离专名类实体（见 ``kb_scope``）。
    """
    kept, _dropped = kb_scope.filter_registry(reg, work)
    rules: Dict[str, str] = {}
    excludes: List[Tuple[str, str]] = []
    names: Dict[str, List[str]] = {}

    for e in kept.values():
        if mode not in e.modes:
            continue
        canon = e.canonical
        wrongs = list(e.variants) + [w for _rx, w in e.ctx if w]
        if include_names:
            wrongs += _split_names(e)
        for w in wrongs:
            w = str(w or "").strip()
            if not w or w == canon or len(w) < MIN_WRONG_LEN:
                continue
            rules.setdefault(w, canon)
        for rx in e.exclude:
            excludes.append((str(rx), ""))
        ns = _split_names(e)
        if ns:
            names.setdefault(canon, ns)

    items = sorted(rules.items(), key=lambda kv: (-len(kv[0]), kv[0]))
    return items, excludes, names


def compare(reg: Dict[str, EntitySpec], mode: str, work: str = "") -> dict:
    """对比「主程序口径」与「安全口径」的规则差异。"""
    old, _ex, names = build_rules_safe(reg, mode, work, include_names=True)
    new, _ex2, _names2 = build_rules_safe(reg, mode, work, include_names=False)
    old_map, new_map = dict(old), dict(new)
    name_only = {w: c for w, c in old_map.items() if w not in new_map}

    # 其中「危险」= 该外文名以某个中文错形的目标形式出现在片源，模型可能据此改中文
    dangerous = []
    for w, c in name_only.items():
        # 纯拉丁且长度 >= 4 的外文名，最容易让模型跨语言误替换
        if re.fullmatch(r"[A-Za-z][A-Za-z' \-]{3,}", w):
            dangerous.append((w, c))

    return {
        "mode": mode, "work": work,
        "rules_old": len(old), "rules_new": len(new),
        "name_only": len(name_only),
        "dangerous_latin_names": len(dangerous),
        "samples": dangerous[:20],
        "names": {k: v for k, v in list(names.items())[:10]},
    }


def render(rep: dict) -> str:
    L = [
        f"模式 {rep['mode']}" + (f" / 作品 {rep['work']}" if rep["work"] else ""),
        f"  主程序口径规则数      {rep['rules_old']}",
        f"  安全口径规则数        {rep['rules_new']}",
        f"  仅由外文名贡献（应剔除）{rep['name_only']}",
        f"  其中纯拉丁（最危险）    {rep['dangerous_latin_names']}",
    ]
    if rep["samples"]:
        L.append("  样例：")
        for w, c in rep["samples"]:
            L.append(f"    {w} → {c}")
    return "\n".join(L)
