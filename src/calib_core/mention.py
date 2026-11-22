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

from .acindex import Automaton
from .data.entities import ENTITIES
from .data.modes import _MODE_TERM_TABLE
from .data.bilingual import BILINGUAL_TERMS
from . import state

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