# -*- coding: utf-8 -*-
# @version 3.3.1
"""对象级 mention 提取与序次配对（M3-1，对象级锚定框架基础）。

用字符级 AC 自动机分别扫参考行（ENTITIES en/ja/ko + aliases）与中文行（合法形 ∪ 错形键），
产出 per-cue mention 列表并按序次配对，分类 resolved/ambiguous/mismatch/unresolved，
标记残留错形中可被 ref 单目标锚定的部分（anchorable，M3-4 价值量）。

本模块当前为**只读诊断/框架层**：不改 srt、不接管 process 替换决策。M3-4 起把配对产出的
per-cue allow-set 喂 acindex.replay_serial(text, only=...)，将 ctx 正则锚定泛化为对象级 mention 锚定。

关键语义（M3-1 原型实测验证）：
  * 字符级 AC 无词边界，纯 ASCII 表面形（ak/one/shin）会命中 make/money 子串——
    longest_bounded 对纯 ASCII 字母数字表面形强制首尾邻字符非字母数字（词边界）。
  * targets 用集合，不强行消歧；多目标 tie-break（M3-5 三级）：zh 序次交集→category 首段
    证据→parent 链，全部 fail-closed，失败回退全 T（挂起不盲改）。
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
    # monolith 拍平后 TABLES 为顶层名（state 模块名不存在）；包模式走 state.TABLES。
    tables = globals()["TABLES"] if "TABLES" in globals() else state.TABLES
    return dict(tables[tname]) if tname else dict(BILINGUAL_TERMS)


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
        par = getattr(e, "parent", "") or ""
        if par and e.canonical not in _PARENT_MAP:
            _PARENT_MAP[e.canonical] = par
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
# 最小触发门：仅当本 cue ref 存在多目标 ref mention 才启用对象 scoping；单目标 ref 走与现状
# 完全相同的代码路径（结构化零漂移）。多目标 tie-break（M3-5 起三级）：zh 序次交集恰1→裁决；
# category 首段证据恰一命中→裁决（fail-closed）；parent 链（ENTITIES.parent 实锤数据）→裁决；
# 失败保守回退全 T（只可能少改不可能改错）。

#: 对象 canonical 集合（ctx 规则 right 归属判定；right∈OBJ_CANONS 为对象规则，否则语境规则豁免）
OBJ_CANONS = frozenset(e.canonical for e in ENTITIES)

#: canonical -> 直接 parent（M3-5 装载：build_maps 从 ENTITIES e.parent 扫描填充，
#: 重复登记 canonical 以首条非空为准；数据侧宁缺毋滥，只登记 note 实锤的父子关系）
_PARENT_MAP: dict = {}


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


def _category_tiebreak(T, zh_ms, i):
    """M3-5 规则3：category 首段证据 tie-break（fail-closed，只可能少改不可能改错）。

    ① T 内任一候选缺 category 首段 → None；
    ② 首段集合 < len(T)（存在同类目候选，category 不可区分）→ None（交 parent 规则）；
    ③ 证据 = 本 cue zh 行其余 mention 的对象 category 首段集合（排除本位 i）：
       恰一候选的首段落入证据集 → 裁决该候选；否则 None（保守回退全 T）。
    """
    if len(T) < 2:
        return None
    cats = {}
    for c in T:
        cat = _CANON_CATEGORY.get(c, "")
        if not cat:                              # ① 缺 category → 放弃
            return None
        cats[c] = cat
    if len(set(cats.values())) < len(T):         # ② 同类目不可区分 → 交 parent
        return None
    evidence = set()
    for j in range(len(zh_ms)):
        if j == i:                               # 排除本位
            continue
        for c in zh_ms[j][3]:
            cc = _CANON_CATEGORY.get(c, "")
            if cc:
                evidence.add(cc)
    hits = [c for c, cat in cats.items() if cat in evidence]
    return hits[0] if len(hits) == 1 else None


def scope_state(M, zh, anchor):
    """对象级 scoping 触发门 + R 计算。返回 (enabled, R, stats)。

    enabled = anchor 存在多目标 ref mention；enabled=False 时 R=None（完全现状）。
    R = tie-break 后本 cue 对象集（frozenset）。
    """
    st = dict(ref_ms=0, multi=0, resolved_tb1=0, resolved_tb2=0,
              resolved_tb3=0, tb_fail=0)
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
        cand = _category_tiebreak(T, zh_ms, i)   # 规则3（M3-5）：category 首段证据裁决
        if cand:
            R.add(cand)
            st["resolved_tb3"] += 1
            continue
        par = _parent_tiebreak(T)                # 规则2：parent 链（M3-5 起有数据）
        if par:
            R.add(par)
            st["resolved_tb2"] += 1
            continue
        R |= T                                   # 保守回退：全 T 进 R
        st["tb_fail"] += 1
    return True, frozenset(R), st


# P2-2（2026-11-24）：ctx 表索引缓存 —— id(table) → (代次, table, automaton, order, charset)。
#   表内容由 state._rebuild_context_caches 原地重建（kb-sync 注入），所以必须靠
#   state._CACHE_GEN 代次判失效；缓存持有 table 强引用，杜绝 id 复用误命中。
_CTX_INDEX_CACHE = {}


def _cache_gen():
    """缓存代次：包模式读 state._CACHE_GEN，monolith 拍平后读顶层同名全局。"""
    if "_CACHE_GEN" in globals():
        return globals()["_CACHE_GEN"]
    return state._CACHE_GEN


def _ctx_table_index(table):
    """(automaton, order, charset)：wrong 键的 AC 自动机 + 表内下标（同键多条目）。"""
    key = id(table)
    gen = _cache_gen()
    ent = _CTX_INDEX_CACHE.get(key)
    if ent is not None and ent[0] == gen and ent[1] is table:
        return ent[2], ent[3], ent[4]
    order, patterns = {}, {}
    for i, (_crx, wrong, right) in enumerate(table):
        if not wrong:
            continue
        order.setdefault(wrong, []).append(i)
        patterns.setdefault(wrong, right or "")
    autom = Automaton(patterns) if patterns else None
    charset = frozenset("".join(patterns)) if patterns else frozenset()
    _CTX_INDEX_CACHE[key] = (gen, table, autom, order, charset)
    return autom, order, charset


def ctx_apply(new, table, anchor, R=None, skip_wrongs=frozenset()):
    """ctx 循环（现状/scoped 双模）。返回 (new, 应用数, gate 排除数)。

    R=None → 完全现状（gate OFF，逐字节同原循环）。
    R=frozenset → 对象规则 gate：right∈OBJ_CANONS 且 right∉R → 跳过；语境规则不受限。
    skip_wrongs → EXCLUDE 预跳过：这些 wrong 键的 ctx 规则跳过。

    P2-2：把「1669 条逐条 `wrong in new` 线性判断」改成「AC 一次扫出候选键，再按
    表内下标升序逐个判定」。与原循环**严格等价**的三条依据：
      1. 原循环只对「wrong 在当前 new 里」的条目做实质判定 → 候选集=这些条目；
      2. 原循环按表下标升序、每条目至多访问一次 → 用 `i >= start` 单调推进复现；
      3. 每次成功替换后重扫 new：替换可能引入目标名里的新错形键，其下标 > i 的
         条目在原循环里**会**被后续访问（下标 ≤ i 的已过站，不会被回访）→ 重扫后
         重新取 `i >= start` 的最小下标即等价。
    """
    used = blocked = 0
    if not table:
        return new, used, blocked
    autom, order, charset = _ctx_table_index(table)
    if autom is None or not new or charset.isdisjoint(new):
        return new, used, blocked
    n = len(table)
    start = 0
    cand = autom.candidates(new) - skip_wrongs
    while cand:
        best = n
        for k in cand:
            for i in order.get(k, ()):
                if start <= i < best:
                    best = i
        if best == n:
            break
        start = best + 1
        crx, wrong, right = table[best]
        if wrong not in new:      # 已被更早的替换吃掉（原循环此处同样空转）
            continue
        if R is not None and right in OBJ_CANONS and right not in R:
            if crx.search(anchor):
                blocked += 1
            continue
        if crx.search(anchor):
            new = _ctx_replace(new, wrong, right)
            used += 1
            cand = autom.candidates(new) - skip_wrongs   # 每次成功替换后重扫
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