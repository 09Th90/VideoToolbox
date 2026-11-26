# -*- coding: utf-8 -*-
# @version 3.3.1
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



def _apply_pair(text, k, v):
    """单条规则 k→v 的串行替换原语（2026-11-24 收尾硬化 A：引擎幂等）。

    错形是官方名子串（k ⊂ v）时走 _ctx_replace 的哨兵保护——否则裸 str.replace
    会命中**上一次运行已生成的官方名**：超频→超频演算→超频演算演算…，引擎对
    自身产物不幂等（p3_idem 矩阵 353 例唯一非幂等源；按模式并表可达规则 5 条：
    超频→超频演算 / 先约电台→鸣潮先约电台 / 血与净雨→罪血与净雨 /
    热队→灼热队 / 在前作，罗德岛→华法琳在前作，罗德岛）。
    k ⊄ v 时与 str.replace 逐字节一致（有意的级联如 金阁→金戈→今州 不受影响）。
    **所有串行替换路径（_replace_report / replace_serial_ac / replay_serial）必须
    共用本原语**，否则 calib_entity.shadow 的等价性证明失效。
    """
    if k != v and k in v:
        return _ctx_replace(text, k, v)
    return text.replace(k, v)


def _replace_report(text, pairs, charset, hits):
    """单遍完成 长键优先替换 + 命中统计。
    行内不包含任何键字符时不可能命中，直接原样返回（整行预筛）。
    2026-11-24：自子串规则（k ⊂ v）经 _apply_pair 保护后，行内只有已完整的官方名
    时不再叠字、也不再计为命中（原先既叠字又虚报命中）。"""
    if not charset or charset.isdisjoint(text):
        return text
    for k, v in pairs:
        if k in text:
            new = _apply_pair(text, k, v)
            if new == text and k != v:
                continue            # 自子串键：行内只有已完整的官方名 → 无改动不计命中
            text = new
            hits[k] = hits.get(k, 0) + 1
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



def _check_term_hazards(mapping):
    """检测术语表的“二次命中”隐患（2026-09-10 沉淀自终末地 ja_auto 项目）。

    `_replace_report` 是**按键长降序逐条 str.replace**，不是单遍扫描。因此若短键 k
    出现在另一条目 k2 的替换结果 value2 里，k2 先替换后，k 会再次命中刚生成的文本：
      {"阿尔达西尔":"阿达希尔", "达希尔":"阿达希尔"} -> 阿达希尔 再被 达希尔 命中 -> 阿阿达希尔
      {"明日方舟末地":"明日方舟：终末地", "末地":"终末地"}   -> 终末地 再被 末地 命中 -> 终终末地
    有意为之的级联（如 金阁->金戈 再 金戈->今州）也会被列出，需人工确认。
    返回 [(短键, 长键, 长键的替换结果, 短键的替换结果), ...]。

    2026-11-22 从 inspect.py 搬入本替换原语模块（零依赖纯函数），消除 sync→inspect 反向边。
    """
    bad, seen = [], set()
    pairs = sorted(mapping.items(), key=lambda kv: len(kv[0]), reverse=True)
    for i, (k, vk) in enumerate(pairs):
        if vk == k:                    # 恒等键不参与
            continue
        for k2, v2 in pairs[:i]:       # 只有“先处理”的条目才会留下可被二次命中的结果
            if v2 != k2 and k in v2 and (k, k2) not in seen:
                seen.add((k, k2))
                bad.append((k, k2, v2, vk))
    return bad

