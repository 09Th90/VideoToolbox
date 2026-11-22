# -*- coding: utf-8 -*-
# @version 3.1.6
"""对象级 mention 提取与序次配对（M3-1，对象级锚定框架基础）。

用字符级 AC 自动机分别扫参考行（ENTITIES en/ja/ko + aliases）与中文行（合法形 ∪ 错形键），
产出 per-cue mention 列表并按序次配对，分类 resolved/ambiguous/mismatch/unresolved，
标记残留错形中可被 ref 单目标锚定的部分（anchorable，M3-4 价值量）。

本模块当前为**只读诊断/框架层**：不改 srt、不接管 process 替换决策。M3-4 起把配对产出的
per-cue allow-set 喂 acindex.replay_serial(text, only=...)，将 ctx 正则锚定泛化为对象级 mention 锚定。

关键语义（M3-1 原型实测验证）：
  * 字符级 AC 无词边界，纯 ASCII 表面形（ak/one/shin）会命中 make/money 子串——
    longest_bounded 对纯 ASCII 字母数字表面形强制首尾邻字符非字母数字（词边界）。
  * targets 用集合，不强行消歧；多目标 tie-break 留 M3-5（category 相同→parent 链→挂起不盲改）。
  * 音乐/曲目类与通用词级实体（游戏/直播/角色/立绘）的 ref mention 无消歧价值，
    计入归因但不算净漏译候选（unresolved_proper 剔除）。
"""
import re
from collections import defaultdict

from .acindex import Automaton, replace_serial_ac
from .replace import _ctx_replace
from .data.entities import ENTITIES
from .data.modes import _MODE_TERM_TABLE
from .data.bilingual import BILINGUAL_TERMS
from . import state
from .state import _EXCLUDE_COMPILED

SEP = re.compile(r"[/,;，、／|｜]+")

# 通用词级实体（ref mention 无消歧价值，只用于归因不算净漏译）
GENERIC_CANON = {"游戏", "直播", "角色", "立绘"}
# 无消歧价值的类目（音乐类跨模式泄漏噪声）
_MUSIC_CATEGORIES = ("曲目", "音乐人")

_CACHE = {}
_CANON_CATEGORY = {}


def split_tokens(s):
    """en/ja/ko 字段拆分为表面形 token（≥2 字符、非纯数字）。"""
    out = set()
    for t in SEP.split(s or ""):
        t = t.strip()
        if len(t) >= 2 and not t.isdigit():
            out.add(t)
    return out


def longest_bounded(auto, text):
    """带 ASCII 词边界的 longest（生产必需语义）。

    字符级 AC 无词边界，纯 ASCII 字母数字表面形（ak/one/shin…）会命中 make/money 子串。
    规则：surface 为纯 ASCII 字母数字时，首尾邻字符必须非字母数字；然后贪心不重叠取最长。
    返回 [(start, end, surface, targets_frozenset)]。
    """
    ms = auto.scan(text)
    n = len(text)
    kept = []
    for start, end, sfc, tg in ms:
        if sfc.isascii() and sfc.isalnum():
            if start > 0 and text[start - 1].isalnum():
                continue
            if end < n and text[end].isalnum():
                continue
        kept.append((start, end, sfc, tg))
    picked, last_end = [], -1
    for m in kept:  # scan 已按 (start, -len) 排序
        if m[0] >= last_end:
            picked.append(m)
            last_end = m[1]
    return picked


def mode_terms(mode):
    tname = _MODE_TERM_TABLE.get(mode)
    return dict(state.TABLES[tname]) if tname else dict(BILINGUAL_TERMS)


def build_maps(mode):
    """按模式建 ref/zh 表面形→canonical 集合 映射 + AC 自动机（带缓存）。

    ref_map：ENTITIES（mode 适用）的 en/ja/ko 拆分 + aliases，lowercase 归一。
    zh_map：canonical/aliases/variants（合法形）∪ 模式错形键（错形→右值）。
    """
    if mode in _CACHE:
        return _CACHE[mode]
    ref_map, zh_map = defaultdict(set), defaultdict(set)
    ents = [e for e in ENTITIES if mode in e.modes]
    n_i18n = 0
    for e in ents:
        toks = set()
        for f in (e.en, e.ja, e.ko):
            toks |= split_tokens(f)
        toks |= {a.strip() for a in getattr(e, "aliases", ()) if len(a.strip()) >= 2}
        if toks:
            n_i18n += 1
        for t in toks:
            ref_map[t.lower()].add(e.canonical)
        zh_map[e.canonical].add(e.canonical)
        for a in getattr(e, "aliases", ()):
            if len(a.strip()) >= 2:
                zh_map[a.strip()].add(e.canonical)
        for v in e.variants:
            if len(v.strip()) >= 2:
                zh_map[v.strip()].add(e.canonical)
    wrong_keys = set()
    for wrong, right in mode_terms(mode).items():
        w = (wrong or "").strip()
        if w and right and w != right:
            zh_map[w].add(right)
            wrong_keys.add(w)
    ref_auto = Automaton({k: frozenset(v) for k, v in ref_map.items()})
    zh_auto = Automaton({k: frozenset(v) for k, v in zh_map.items()})
    for e in ENTITIES:
        _CANON_CATEGORY.setdefault(e.canonical, (e.category or "").split("/")[0])
    _CACHE[mode] = dict(
        ref_map=dict(ref_map), zh_map=dict(zh_map), ref_auto=ref_auto,
        zh_auto=zh_auto, wrong_keys=wrong_keys,
        n_entities=len(ents), n_i18n=n_i18n)
    return _CACHE[mode]


def _is_music(targets):
    return any(_CANON_CATEGORY.get(c, "") in _MUSIC_CATEGORIES for c in targets)


def _is_generic(targets):
    return any(c in GENERIC_CANON for c in targets)


def pair_cue(M, zh, ref):
    """单 cue 序次配对。返回 dict：ref_ms/zh_ms/pairs/resolved/ambiguous/mismatch/
    unresolved/unresolved_proper/anchorable_wrong（残留错形可被 ref 单目标锚定）。

    配对三级（M3-1 原型）：序次逐位 ref第i↔zh第i；ref 单目标且 zh 目标集相交=resolved，
    不交=mismatch；ref 多目标=ambiguous（zh 已消歧当 |zh∩ref|==1）；ref 越界=unresolved。
    """
    ref_ms = longest_bounded(M["ref_auto"], ref.lower()) if ref else []
    zh_ms = longest_bounded(M["zh_auto"], zh)
    wrong_keys = M["wrong_keys"]
    pairs = min(len(ref_ms), len(zh_ms))
    resolved, ambiguous, mismatch, unresolved, unresolved_proper = [], [], [], [], []
    anchorable_wrong = 0
    for i in range(pairs):
        _, _, rs, rt = ref_ms[i]
        _, _, zs, zt = zh_ms[i]
        rt, zt = set(rt), set(zt)
        is_zh_wrong = zs in wrong_keys
        if len(rt) == 1:
            if zt & rt:
                resolved.append((i, rs, zs, sorted(rt)))
                if is_zh_wrong:
                    anchorable_wrong += 1
            else:
                mismatch.append((i, rs, sorted(rt), zs, sorted(zt)))
        else:
            dis = bool(zt & rt) and len(zt & rt) == 1
            ambiguous.append((i, rs, sorted(rt), zs, sorted(zt), dis))
    for i in range(pairs, len(ref_ms)):
        _, _, rs, rt = ref_ms[i]
        unresolved.append((i, rs, sorted(rt)))
        if not _is_music(rt) and not _is_generic(rt):
            unresolved_proper.append((i, rs, sorted(rt)))
    return dict(ref_ms=ref_ms, zh_ms=zh_ms, resolved=resolved, ambiguous=ambiguous,
                mismatch=mismatch, unresolved=unresolved,
                unresolved_proper=unresolved_proper, anchorable_wrong=anchorable_wrong,
                zh_extra=len(zh_ms) - pairs)


class MentionPairer:
    """对象级 mention 配对器（M3-4 集成接口）。按模式缓存索引，逐 cue 配对。"""

    def __init__(self, mode):
        self.mode = mode
        self.M = build_maps(mode)

    def pair(self, zh, ref):
        return pair_cue(self.M, zh, ref)

    def allow_set(self, zh, ref):
        """M3-4 用：由配对产出本 cue 允许替换的错形键集合（resolved+anchorable 的 zh 错形）。

        当前仅返回可锚定错形键（ref 单目标佐证），供 replay_serial(text, only=...) 预筛。
        未锚定错形不纳入（保守，回落旧整行 ctx 路径）。
        """
        res = self.pair(zh, ref)
        wrong_keys = self.M["wrong_keys"]
        allow = set()
        for i, rs, zs, rt in res["resolved"]:
            if zs in wrong_keys:
                allow.add(zs)
        return allow


# ---------------------------------------------------------------- M3-4 对象级 ctx scoping
# 最小触发门：仅当本 cue ref 存在多目标 mention 才启用对象 scoping；单目标 ref 走与现状
# 完全相同的代码路径（结构化零漂移）。多目标 tie-break：zh 序次交集恰1→裁决；parent 链
# （接口预留，生产 parent 数据当前为空）；失败保守回退全 T（只可能少改不可能改错）。

#: 对象 canonical 集合（ctx 规则 right 归属判定；right∈OBJ_CANONS 为对象规则，否则语境规则豁免）
OBJ_CANONS = frozenset(e.canonical for e in ENTITIES)

#: canonical -> 直接 parent（M3-5 填数；当前生产全空，_parent_tiebreak 永不触发）
_PARENT_MAP = {}


def _parent_tiebreak(T, parent_map=None):
    """T 中恰一对象 P 使 T\\{P} 沿 parent 链到达 P → 返回 P；否则 None（不盲裁）。"""
    pm = parent_map if parent_map is not None else _PARENT_MAP
    if not pm or len(T) < 2:
        return None

    def reaches(q, p):
        seen = set()
        while q and q not in seen:
            seen.add(q)
            if q == p:
                return True
            q = pm.get(q, "")
        return q == p

    cands = [p for p in T if all(q == p or reaches(q, p) for q in T if q != p)]
    return cands[0] if len(cands) == 1 else None


def scope_state(M, zh, anchor):
    """对象级 scoping 触发门 + R 计算。返回 (enabled, R, stats)。

    enabled = anchor 存在多目标 ref mention；enabled=False 时 R=None（完全现状）。
    R = tie-break 后本 cue 对象集（frozenset）。
    """
    st = dict(ref_ms=0, multi=0, resolved_tb1=0, resolved_tb2=0, tb_fail=0)
    ref_ms = longest_bounded(M["ref_auto"], anchor.lower()) if anchor else []
    st["ref_ms"] = len(ref_ms)
    if not any(len(t) > 1 for _, _, _, t in ref_ms):
        return False, None, st
    zh_ms = longest_bounded(M["zh_auto"], zh)
    R = set()
    for i, (_, _, _, rt) in enumerate(ref_ms):
        if len(rt) == 1:
            R |= rt
            continue
        st["multi"] += 1
        T = set(rt)
        zt = set(zh_ms[i][3]) if i < len(zh_ms) else set()
        inter = T & zt
        if len(inter) == 1:                      # 规则1：zh 序次交集裁决
            R |= inter
            st["resolved_tb1"] += 1
            continue
        par = _parent_tiebreak(T)                # 规则2：parent 链（当前数据为空）
        if par:
            R.add(par)
            st["resolved_tb2"] += 1
            continue
        R |= T                                   # 保守回退：全 T 进 R
        st["tb_fail"] += 1
    return True, frozenset(R), st


def ctx_apply(new, table, anchor, R=None, skip_wrongs=frozenset()):
    """ctx 循环（现状/scoped 双模）。返回 (new, 应用数, gate 排除数)。

    R=None → 完全现状（gate OFF，逐字节同原循环）。
    R=frozenset → 对象规则 gate：right∈OBJ_CANONS 且 right∉R → 跳过；语境规则不受限。
    skip_wrongs → EXCLUDE 预跳过：这些 wrong 键的 ctx 规则跳过。
    """
    used = blocked = 0
    for crx, wrong, right in table:
        if wrong in skip_wrongs:
            continue
        if wrong in new:
            if R is not None and right in OBJ_CANONS and right not in R:
                if crx.search(anchor):
                    blocked += 1
                continue
            if crx.search(anchor):
                new = _ctx_replace(new, wrong, right)
                used += 1
    return new, used, blocked


def exclude_scan(anchor):
    """EXCLUDE 预跳过候选键集（仅判 ref 正则；wrong in old 由调用方交集判定）。"""
    return {w for w, (rt, rxs) in _EXCLUDE_COMPILED.items()
            if any(rx.search(anchor) for rx in rxs)}


def term_apply(old, term_idx, hits, skip_wrongs=frozenset()):
    """term 层：无跳过→replace_serial_ac（现状）；有跳过→replay_serial 排除键。

    hits 口径与 replace_serial_ac 一致（每键每行计 1）。
    """
    if not skip_wrongs:
        return replace_serial_ac(old, term_idx, hits)
    only = frozenset(term_idx.terms) - skip_wrongs
    new, hitseq = term_idx.replay_serial(old, only=only)
    for k in dict.fromkeys(hitseq):
        hits[k] = hits.get(k, 0) + 1
    return new


def exclude_rollback(new, old, anchor, hits, skip_wrongs=None):
    """EXCLUDE 层：skip_wrongs=None→现状整行倒回；预跳过版（非 None）→错误不产生无需倒回。"""
    if skip_wrongs is not None:
        return new
    for wrong, (right, rxs) in _EXCLUDE_COMPILED.items():
        if wrong in old and wrong not in new and any(rx.search(anchor) for rx in rxs):
            new = new.replace(right, wrong)
            hits.pop(wrong, None)
    return new


def cue_scope(M, zh, anchor):
    """cue 级 scoping 入口：返回 (R, skip_wrongs)。未启用时 (None, None)（完全现状）。

    启用时 R=对象集，skip_wrongs=EXCLUDE 预跳过键（wrong in zh ∩ exclude_scan(anchor)）。
    """
    enabled, R, _st = scope_state(M, zh, anchor)
    if not enabled:
        return None, None
    pre = {w for w in _EXCLUDE_COMPILED if w in zh} & exclude_scan(anchor)
    return R, frozenset(pre)