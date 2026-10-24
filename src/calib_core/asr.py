# -*- coding: utf-8 -*-
# @version 2.6.0
"""英文 ASR 断词容错与参考行规整

源：subtitle_calib_merged.py L7172-L7271 @ 97d7d463（2026-10-24 冻结快照）
"""
import io
import os
import re
import shutil
import sys
import unicodedata
from .data.entities import ENTITIES
from .data.misc import EN_ASR_SPLIT_FIXES, EN_LINE_TERM_FIXES, _ASR_COMMON_WORDS, _ASR_SPLIT_SUFFIXES
from .replace import _compile_map, _replace_report


_KNOWN_EN_CACHE = None

_KNOWN_EN_MIN_LEN = 5          # 已知词最短长度：过短易被正常词边界污染（were/when/this…）



def _known_en_tokens():
    """已知英文专名词表（小写纯字母 token），惰性构建并缓存。
    来源：ENTITIES 的 en 名 + EN_LINE_TERM_FIXES / EN_ASR_SPLIT_FIXES 的目标值。
    护栏：只收长度 >= _KNOWN_EN_MIN_LEN 且不在 _ASR_COMMON_WORDS 的 token——
    防长句歌名（如 "When We Were the Most Beautiful"）把 were/when/most 等常用词
    混进词表，进而让 _rejoin_known 把正常词边界误判成断词。"""
    global _KNOWN_EN_CACHE
    if _KNOWN_EN_CACHE is not None:
        return _KNOWN_EN_CACHE
    toks = set()

    def _add(s):
        for t in re.findall(r"[A-Za-z]+", s or ""):
            tl = t.lower()
            if len(tl) >= _KNOWN_EN_MIN_LEN and tl not in _ASR_COMMON_WORDS:
                toks.add(tl)

    for e in ENTITIES:      # 实体表在 import 期已完成注册
        _add(getattr(e, "en", ""))
    for v in EN_LINE_TERM_FIXES.values():
        _add(v)
    for v in EN_ASR_SPLIT_FIXES.values():
        _add(v)
    _KNOWN_EN_CACHE = frozenset(toks)
    return _KNOWN_EN_CACHE



def _rejoin_known(text, known=None):
    """把相邻两段纯字母之间的空格去掉——**仅当**拼起来是已知英文专名。
    纯断词（"reson ator"->"resonator"）自动修复；正常词边界不动。
    护栏：左片段 >=3 字符（挡 "We re"/"Sh ing"），拼接结果须在已知词表内。
    迭代至稳定，可处理三段连续断词。"""
    if not text or " " not in text:
        return text
    known = known if known is not None else _known_en_tokens()
    if not known:
        return text
    parts = re.split(r"([ \t]+)", text)          # 奇数位为空白，保留原结构
    changed = True
    while changed:
        changed = False
        out, i = [], 0
        while i < len(parts):
            if (i + 2 < len(parts)
                    and re.fullmatch(r"[A-Za-z]{3,}", parts[i])
                    and re.fullmatch(r"[A-Za-z]+", parts[i + 2])
                    and (parts[i] + parts[i + 2]).lower() in known):
                out.append(parts[i] + parts[i + 2])   # 吃掉空白 + 右片段
                i += 3
                changed = True
            else:
                out.append(parts[i])
                i += 1
        parts = out
    return "".join(parts)



_SPLIT_FIX_CACHE = None



def _split_fix_pairs():
    """EN_ASR_SPLIT_FIXES 的编译缓存（长键优先 + 键字符集）。"""
    global _SPLIT_FIX_CACHE
    if _SPLIT_FIX_CACHE is None:
        _SPLIT_FIX_CACHE = _compile_map(EN_ASR_SPLIT_FIXES)
    return _SPLIT_FIX_CACHE



def _ref_for_match(ref):
    """锚定匹配专用：先套断词/误听修正表，再通用重组，返回规整后的参考行。
    只用于 CONTEXT/EXCLUDE 的正则匹配与 --fix-en 输出；
    **绝不**改动默认输出里的参考行（结构零改动原则）。"""
    if not ref:
        return ref
    pairs, chars = _split_fix_pairs()
    ref = _replace_report(ref, pairs, chars, {})
    return _rejoin_known(ref)



def _scan_split_line(line, known=None):
    """返回一行里疑似 ASR 断词的候选：[(左片段, 右片段, 拼接, 可自动重组)]。
    左片段须 >=3 字符（与 _rejoin_known 同护栏，挡 "We re"/"Sh ing" 类误报）。"""
    known = known if known is not None else _known_en_tokens()
    hits = []
    for m in re.finditer(r"\b([A-Za-z]{3,})[ \t]+([A-Za-z]{2,})\b", line or ""):
        l, r = m.group(1), m.group(2)
        joined = l + r
        if joined.lower() in known:
            hits.append((l, r, joined, True))        # 拼起来即已知专名 -> 可直接自动重组
            continue
        if l.lower() in _ASR_COMMON_WORDS or r.lower() in _ASR_COMMON_WORDS:
            continue                                 # 任一片段是完整单词 -> 不是断词
        if r.lower() in _ASR_SPLIT_SUFFIXES:
            hits.append((l, r, joined, False))       # 右片段是单词尾巴 -> 疑似断词，待人工确认
    return hits

