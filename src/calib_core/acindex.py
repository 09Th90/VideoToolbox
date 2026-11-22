# -*- coding: utf-8 -*-
# @version 3.1.6
"""对象索引原语（M2 执行层对象化基础，自包含于 calib_core / monolith）。

字符级 Aho-Corasick + 按模式术语表组装的 ModeIndex。搬自 calib_entity.index（2026-11-22），
使其落在 calib_core 自包含边界内（monolith 仅从 calib_core 生成，不能 import calib_entity）。

两种语义（由影子双跑量化，不在此偷偷统一）：
  * replay_serial = 主脚本 _replace_report 的串行语义（键长降序逐键 str.replace，
    替换产生的新文本会被后续短键再次命中）——零漂移集成用这个；
  * replace_longest = 单遍最长优先、不重叠（对象级目标语义，P2 才切换）。

候选预筛（candidates）一次扫描得本行出现的全部键，供串行语义减少遍历量；
级联（目标名含另一错形键）会造出新键，须由调用方检测 candidates(结果)-candidates(原文)
非空时回退全表串行（影子验证 EQUIVALENT_WITH_FALLBACK 的充要条件）。
"""
from collections import deque

# Match = (start, end, surface, target_canonical)


class Automaton:
    """字符级 Aho-Corasick（纯 Python，无第三方依赖）。

    中文/日文/韩文与拉丁混排一律按字符匹配，不做词边界假设——与主脚本
    str.replace 语义一致（主脚本只有 ctx 正则里手写 \\b）。
    """

    __slots__ = ("_next", "_fail", "_out", "_patterns", "_maxlen")

    def __init__(self, patterns):
        self._next = [{}]
        self._fail = [0]
        self._out = [[]]
        self._patterns = {}
        self._maxlen = 0
        for surface, target in patterns.items():
            if not surface:
                continue
            self._patterns[surface] = target
            self._maxlen = max(self._maxlen, len(surface))
            node = 0
            for ch in surface:
                nxt = self._next[node].get(ch)
                if nxt is None:
                    nxt = len(self._next)
                    self._next[node][ch] = nxt
                    self._next.append({})
                    self._fail.append(0)
                    self._out.append([])
                node = nxt
            self._out[node].append((surface, target))
        self._build_fail()

    def _build_fail(self):
        q = deque()
        for ch, nxt in self._next[0].items():
            self._fail[nxt] = 0
            q.append(nxt)
        while q:
            r = q.popleft()
            for ch, u in self._next[r].items():
                q.append(u)
                f = self._fail[r]
                while f and ch not in self._next[f]:
                    f = self._fail[f]
                cand = self._next[f].get(ch, 0)
                self._fail[u] = 0 if cand == u else cand
                if self._fail[u]:
                    self._out[u].extend(self._out[self._fail[u]])

    @property
    def patterns(self):
        return dict(self._patterns)

    def __len__(self):
        return len(self._patterns)

    @property
    def nodes(self):
        return len(self._next)

    def scan(self, text):
        """全部匹配（允许重叠），按出现位置升序、同位置长键在前。"""
        if not text:
            return []
        res = []
        node = 0
        nxt_map, fail, out = self._next, self._fail, self._out
        for i, ch in enumerate(text):
            while node and ch not in nxt_map[node]:
                node = fail[node]
            node = nxt_map[node].get(ch, 0)
            if out[node]:
                for surface, target in out[node]:
                    res.append((i - len(surface) + 1, i + 1, surface, target))
        res.sort(key=lambda m: (m[0], -(m[1] - m[0])))
        return res

    def longest(self, text):
        """最长优先、互不重叠（从左到右贪心）。单遍替换的匹配序列。"""
        picked, last_end = [], -1
        for m in self.scan(text):
            if m[0] >= last_end:
                picked.append(m)
                last_end = m[1]
        return picked

    def candidates(self, text):
        """本行出现过的全部键（供串行语义预筛）。"""
        return {m[2] for m in self.scan(text)}

    def replace_longest(self, text):
        """单遍最长优先替换。返回 (新文本, 采纳的匹配)。"""
        ms = self.longest(text)
        if not ms:
            return text, []
        buf, pos = [], 0
        for start, end, surface, target in ms:
            buf.append(text[pos:start])
            buf.append(target)
            pos = end
        buf.append(text[pos:])
        return "".join(buf), ms


class ModeIndex:
    """按片源模式术语表组装的对象索引（terms 直传，无引擎/monolith 依赖）。

    pairs 保留主脚本顺序（键长降序、同长按插入序），使串行语义可逐字节复现；
    automaton 提供单遍语义与候选预筛。
    """

    __slots__ = ("mode", "terms", "pairs", "charset", "automaton")

    def __init__(self, mode, terms):
        self.mode = mode
        self.terms = {k: v for k, v in terms.items() if k and v and k != v}
        self.pairs = sorted(self.terms.items(), key=lambda kv: len(kv[0]), reverse=True)
        self.charset = frozenset("".join(self.terms)) if self.terms else frozenset()
        self.automaton = Automaton(self.terms)

    def __len__(self):
        return len(self.terms)

    def candidates(self, text):
        if not self.charset or self.charset.isdisjoint(text):
            return set()
        return self.automaton.candidates(text)

    def replace_longest(self, text):
        if not self.charset or self.charset.isdisjoint(text):
            return text, []
        return self.automaton.replace_longest(text)

    def replay_serial(self, text, only=None):
        """复现主脚本串行语义（键长降序逐键 replace）。only 给定时只应用这些键。

        返回 (新文本, 实际命中的键序列)。与 _replace_report 的文本输出等价
        （hits 计数由调用方按命中序列累加）。
        """
        if not self.charset or self.charset.isdisjoint(text):
            return text, []
        hit = []
        for k, v in self.pairs:
            if only is not None and k not in only:
                continue
            if k in text:
                hit.append(k)
                text = text.replace(k, v)
        return text, hit


def replace_serial_ac(text, idx, hits):
    """AC 预筛 + 串行级联回退的 _replace_report 等价替换（M2 零漂移集成）。

    与 replace._replace_report(text, idx.pairs, idx.charset, hits) 逐字节等价且 hits 计数一致：
      1. AC 一次扫描得原文候选键 cand；无候选直接返回（整行预筛）。
      2. 按 pairs 序仅对 cand 内键串行 replace，局部计 hit。
      3. 级联检测：替换结果出现 cand 之外的新键（目标名含另一错形键）→ 回退全表串行重算，
         保证与 _replace_report 完全一致（影子验证 EQUIVALENT_WITH_FALLBACK 的充要条件）。
      4. 局部 hit 合并进全局 hits（每键每行计 1，与 _replace_report 同口径）。
    """
    if not idx.charset or idx.charset.isdisjoint(text):
        return text
    cand = idx.automaton.candidates(text)
    if not cand:
        return text
    new = text
    local = {}
    for k, v in idx.pairs:
        if k in cand and k in new:
            local[k] = local.get(k, 0) + 1
            new = new.replace(k, v)
    if idx.automaton.candidates(new) - cand:
        new = text
        local = {}
        for k, v in idx.pairs:
            if k in new:
                local[k] = local.get(k, 0) + 1
                new = new.replace(k, v)
    for k, c in local.items():
        hits[k] = hits.get(k, 0) + c
    return new
