# -*- coding: utf-8 -*-
# @version 1.19.0
"""严格核验：每个候选错形在 KB 里的真实形态。

分类：
  KEY      出现在带引号的键/变体里（已覆盖，勿重复加）
  CTXNOTE  出现在注释里且注释含「仅/佐证/ctx/锚」等字样（已裁决走 ctx 或刻意不加）
  COMMENT  仅出现在注释里（有过记录但可能未固化为条目）
  ABSENT   KB 里完全没有（真·新候选，需评估入库）
"""
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
KB_PATH = os.path.join(ROOT, "subtitle_calib_merged.py")
REPORT = os.path.join(ROOT, "data", "tmp", "_calib_mine_report.json")

kb_lines = open(KB_PATH, encoding="utf-8").read().split("\n")

CTX_HINT = re.compile(r"仅英文|佐证|ctx|锚|刻意|不收录|不改|常用词|常用语|通用词|生僻|锁暝|裁决")

def classify(word):
    hits = []
    for i, ln in enumerate(kb_lines):
        if word in ln:
            quoted = ('"%s"' % word) in ln or ("'%s'" % word) in ln
            is_comment = ln.lstrip().startswith("#")
            if quoted and not is_comment:
                hits.append(("KEY", i + 1, ln.strip()))
            elif is_comment:
                hits.append(("CTXNOTE" if CTX_HINT.search(ln) else "COMMENT",
                             i + 1, ln.strip()))
            else:
                hits.append(("CODE", i + 1, ln.strip()))
    if not hits:
        return "ABSENT", []
    order = {"KEY": 0, "CTXNOTE": 1, "CODE": 2, "COMMENT": 3}
    best = sorted(hits, key=lambda h: order[h[0]])[0][0]
    return best, hits


rep = json.load(open(REPORT, encoding="utf-8"))
seen, buckets = set(), {"KEY": [], "CTXNOTE": [], "COMMENT": [],
                        "ABSENT": [], "CODE": []}
for c in rep["fresh"]:
    o = c["old"]
    if o in seen:
        continue
    seen.add(o)
    st, hits = classify(o)
    buckets[st].append((c, hits[:3]))

for st in ("ABSENT", "CTXNOTE", "COMMENT", "CODE", "KEY"):
    lst = buckets[st]
    print("\n=== %s：%d 个 ===" % (st, len(lst)))
    for c, hits in sorted(lst, key=lambda x: -x[0]["count"])[:40 if st != "ABSENT" else 200]:
        ln = ""
        if hits:
            ln = "  ⟵ kb:%d %s" % (hits[0][1], hits[0][2][:90])
        print("  %2dx %-14s -> %-12s%s" % (c["count"], c["old"], c["new"], ln))
