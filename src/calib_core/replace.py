# -*- coding: utf-8 -*-
# @version 2.7.0
"""术语替换与上下文替换原语

源：subtitle_calib_merged.py L11565-L11609 @ 97d7d463（2026-10-24 冻结快照）
"""
import io
import os
import re
import shutil
import sys
import unicodedata



def _compile_map(mapping):
    """预编译术语表 -> (按键长降序的 (key, value) 对, 键字符并集)。
    每张表只编译一次，避免逐行重复排序；字符集用于整行快速预筛。"""
    pairs = sorted(mapping.items(), key=lambda kv: len(kv[0]), reverse=True)
    charset = frozenset("".join(mapping)) if mapping else frozenset()
    return pairs, charset



def _replace_report(text, pairs, charset, hits):
    """单遍完成 长键优先替换 + 命中统计。
    行内不包含任何键字符时不可能命中，直接原样返回（整行预筛）。"""
    if not charset or charset.isdisjoint(text):
        return text
    for k, v in pairs:
        if k in text:
            hits[k] = hits.get(k, 0) + 1
            text = text.replace(k, v)
    return text



def _ctx_replace(text, wrong, right):
    """上下文替换的防叠字包装（2026-10-04）。

    当「正确形」本身包含「错形」时（心月狐⊃月狐、阿达希尔⊃达希尔、
    明日方舟：终末地⊃末地），裸 str.replace 会命中上一轮刚生成的正确形，
    产出「心心月狐 / 阿阿达希尔 / 终终末地」。此处先把文本中既有的正确形
    用哨兵字符保护起来，替换错形后再还原，等价于给错形加了「不得位于
    正确形内部」的负向断言。wrong 不含于 right 时行为与 str.replace 完全一致。
    """
    if not wrong or wrong not in text:
        return text
    if wrong in right:
        sent = "\x00"
        while sent in text:
            sent += "\x00"
        return text.replace(right, sent).replace(wrong, right).replace(sent, right)
    return text.replace(wrong, right)



def apply_map(text, mapping):
    """按错误形式->正确形式替换，长词优先。"""
    pairs, charset = _compile_map(mapping)
    return _replace_report(text, pairs, charset, {})

