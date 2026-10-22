# @version 2.5.4
"""对象索引层：按模式构建 Aho-Corasick 自动机。

解决两个执行层问题：

1. **性能形态**：主脚本 ``_replace_report`` 对每一行遍历整张表（bi 模式约 2.4k 键），
   并对每个键做 ``k in text``。AC 一次扫描即可得到本行出现的全部键，候选集通常
   只有个位数——顺带把「长键必须写在短键前」这种书写顺序合同去掉（最长匹配天然满足）。
2. **对象视图**：命中结果带 ``target``（对象 canonical），后续 mention 消歧需要的
   「这个位置指的是哪个对象」在这里第一次变得可得。

注意语义差别（由 ``shadow.py`` 量化，不在本模块偷偷统一）：

* 主脚本 = **串行**：按键长降序逐键 ``str.replace``，替换产生的新文本会被后续短键
  再次命中（这是历史上「鸣潮的鸣潮」类垃圾串的成因）；
* 本模块 ``longest()`` = **单遍**：从左到右、同起点取最长、不重叠，替换结果不参与
  二次扫描。

两者在「目标名包含另一个错形键」时必然分叉。分叉是特性而非 bug：单遍语义是
对象级的目标语义。但切换前必须先用 ``shadow.verify_index_equivalence`` 证明
「索引预筛本身无损」，再用 ``shadow.diff_onepass`` 逐条看清分叉。
"""
from __future__ import annotations

from collections import deque
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

Match = Tuple[int, int, str, str]      # (start, end, surface, target_canonical)


class Automaton:
    """字符级 Aho-Corasick（纯 Python，无第三方依赖）。

    中文/日文/韩文与拉丁混排一律按字符匹配，不做词边界假设——这与主脚本
    ``str.replace`` 的语义一致（主脚本只有 ctx 正则里手写 ``\\b``）。
    """

    __slots__ = ("_next", "_fail", "_out", "_patterns", "_maxlen")

    def __init__(self, patterns: Mapping[str, str]):
        self._next: List[Dict[str, int]] = [{}]
        self._fail: List[int] = [0]
        self._out: List[List[Tuple[str, str]]] = [[]]
        self._patterns: Dict[str, str] = {}
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

    def _build_fail(self) -> None:
        q: deque = deque()
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

    # -- 查询 ----------------------------------------------------

    @property
    def patterns(self) -> Dict[str, str]:
        return dict(self._patterns)

    def __len__(self) -> int:
        return len(self._patterns)

    @property
    def nodes(self) -> int:
        return len(self._next)

    def scan(self, text: str) -> List[Match]:
        """全部匹配（允许重叠），按出现位置升序、同位置长键在前。"""
        if not text:
            return []
        res: List[Match] = []
        node = 0
        nxt_map = self._next
        fail = self._fail
        out = self._out
        for i, ch in enumerate(text):
            while node and ch not in nxt_map[node]:
                node = fail[node]
            node = nxt_map[node].get(ch, 0)
            if out[node]:
                for surface, target in out[node]:
                    res.append((i - len(surface) + 1, i + 1, surface, target))
        res.sort(key=lambda m: (m[0], -(m[1] - m[0])))
        return res

    def longest(self, text: str) -> List[Match]:
        """最长优先、互不重叠（从左到右贪心）。单遍替换的匹配序列。"""
        picked: List[Match] = []
        last_end = -1
        for m in self.scan(text):
            if m[0] >= last_end:
                picked.append(m)
                last_end = m[1]
        return picked

    def candidates(self, text: str) -> Set[str]:
        """本行出现过的全部键（供串行语义的预筛，语义等价性由 shadow 验证）。"""
        return {m[2] for m in self.scan(text)}

    def replace_longest(self, text: str) -> Tuple[str, List[Match]]:
        """单遍最长优先替换。返回 (新文本, 采纳的匹配)。"""
        ms = self.longest(text)
        if not ms:
            return text, []
        buf: List[str] = []
        pos = 0
        for start, end, surface, target in ms:
            buf.append(text[pos:start])
            buf.append(target)
            pos = end
        buf.append(text[pos:])
        return "".join(buf), ms


class ModeIndex:
    """按片源模式组装的对象索引。

    ``pairs`` 保留主脚本的顺序（键长降序、同长按表内插入序），使串行语义可以被
    逐字节复现；``automaton`` 提供单遍语义与候选预筛。
    """

    __slots__ = ("mode", "terms", "pairs", "charset", "automaton")

    def __init__(self, mode: str, terms: Mapping[str, str]):
        self.mode = mode
        self.terms: Dict[str, str] = {k: v for k, v in terms.items() if k and v and k != v}
        # 与主脚本 _compile_map 完全同序：长度降序（sorted 稳定 -> 同长保持插入序）
        self.pairs: List[Tuple[str, str]] = sorted(
            self.terms.items(), key=lambda kv: len(kv[0]), reverse=True)
        self.charset = frozenset("".join(self.terms)) if self.terms else frozenset()
        self.automaton = Automaton(self.terms)

    # -- 构造 ----------------------------------------------------

    @classmethod
    def build(cls, mode: str, engine=None, extra_terms: Optional[Mapping[str, str]] = None,
              aliases: Optional[Iterable[Tuple[str, str]]] = None) -> "ModeIndex":
        """按模式取表（与 ``process()`` 的选表口径一致）+ 可选外挂条目。

        ``extra_terms``：片源自适应补充（如 bi 模式并入 ``ENDFIELD_BI_TERMS``）。
        ``aliases``：``(surface, canonical)`` 序列，官方简称；不覆盖已有键。
        """
        eng = engine or _engine()
        tname = getattr(eng, "_MODE_TERM_TABLE", {}).get(mode)
        base: Dict[str, str] = dict(getattr(eng, tname, None) or {}) if tname else {}
        if extra_terms:
            for k, v in extra_terms.items():
                base.setdefault(k, v)
        if aliases:
            for surface, canonical in aliases:
                if surface and canonical:
                    base.setdefault(surface, canonical)
        return cls(mode, base)

    # -- 视图 ----------------------------------------------------

    def __len__(self) -> int:
        return len(self.terms)

    def stats(self) -> dict:
        return {
            "mode": self.mode,
            "keys": len(self.terms),
            "targets": len(set(self.terms.values())),
            "charset": len(self.charset),
            "ac_nodes": self.automaton.nodes,
            "longest_key": max((len(k) for k in self.terms), default=0),
            "avg_key_len": round(
                sum(len(k) for k in self.terms) / max(len(self.terms), 1), 2),
        }

    def candidates(self, text: str) -> Set[str]:
        if not self.charset or self.charset.isdisjoint(text):
            return set()
        return self.automaton.candidates(text)

    def replace_longest(self, text: str) -> Tuple[str, List[Match]]:
        if not self.charset or self.charset.isdisjoint(text):
            return text, []
        return self.automaton.replace_longest(text)

    def replay_serial(self, text: str, only: Optional[Set[str]] = None
                      ) -> Tuple[str, List[str]]:
        """复现主脚本的串行语义（键长降序逐键 replace）。

        ``only`` 给定时只应用这些键（用于验证「AC 预筛是否无损」）。
        返回 (新文本, 实际命中的键序列)。
        """
        if not self.charset or self.charset.isdisjoint(text):
            return text, []
        hit: List[str] = []
        for k, v in self.pairs:
            if only is not None and k not in only:
                continue
            if k in text:
                hit.append(k)
                text = text.replace(k, v)
        return text, hit


_ENGINE = None


def _engine():
    global _ENGINE
    if _ENGINE is None:
        from .spec import load_engine
        _ENGINE = load_engine()
    return _ENGINE
