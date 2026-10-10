# -*- coding: utf-8 -*-
# @version 1.19.0
"""从挖掘报告里筛「新候选中正形已是 KB 官方词」的条目 —— 大概率是真术语错形。

原理：KB 右值（canonical）都是官方名词；若某候选的「新」恰好是某个官方词，
而「旧」不在 KB，则它是漏沉淀的术语错形，优先级远高于 1x 的措辞改写。
"""
import json
import os
import re
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KB_PATH = os.path.join(ROOT, "subtitle_calib_merged.py")
REPORT = os.path.join(ROOT, "data", "tmp", "_calib_mine_report.json")

kb = open(KB_PATH, encoding="utf-8").read()

# 1) 收集 KB 里所有「官方词」：字符串字面量（"xxx": "yyy" / ctx 三元组的末位 / Entity canonical）
cands = re.findall(r'"([^"\n]{1,20})"', kb)
freq = Counter(cands)
# 出现在 KB 里的中文名（>=2 字、含汉字），视为官方词候选池
official = set()
for s, c in freq.items():
    if c >= 1 and re.fullmatch(r"[\u4e00-\u9fff·]{2,12}", s):
        official.add(s)
# ctx 三元组的末位显式取一遍（可靠性最高）
for m in re.finditer(r'\(r"[^"]*",\s*"[^"]*",\s*"([^"]+)"\)', kb):
    if re.search(r"[\u4e00-\u9fff]", m.group(1)):
        official.add(m.group(1))
print("官方词池：%d 个" % len(official))

rep = json.load(open(REPORT, encoding="utf-8"))
fresh = rep["fresh"]
print("新候选：%d 个" % len(fresh))

hits = [c for c in fresh if c["new"] in official]
print("\n== 正形是官方词的新候选：%d 个 ==" % len(hits))
for c in sorted(hits, key=lambda x: -x["count"]):
    print("  %2dx  %-14s -> %-12s  %s" % (c["count"], c["old"], c["new"],
                                          ",".join(c["modes"])))
