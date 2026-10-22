# -*- coding: utf-8 -*-
# @version 2.5.3
"""检查 src 里引用的 FluentIcon 成员是否都在 _icons_data.ART 中（防再犯 COPY 缺项）。"""
import ast
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "src")

art = set()
p = os.path.join(SRC, "vt_fluent", "_icons_data.py")
with open(p, encoding="utf-8") as f:
    txt = f.read()
m = re.search(r"^ART = \{(.*?)^\}", txt, re.S | re.M)
for line in m.group(1).splitlines():
    mm = re.match(r"\s+'([A-Z0-9_]+)':", line)
    if mm:
        art.add(mm.group(1))

pat = re.compile(r"\b(?:FIF|FluentIcon)\.([A-Z][A-Z0-9_]*)\b")
used = {}
for root, _, files in os.walk(SRC):
    if "__pycache__" in root:
        continue
    for fn in files:
        if not fn.endswith(".py"):
            continue
        fp = os.path.join(root, fn)
        try:
            with open(fp, encoding="utf-8") as f:
                src = f.read()
        except OSError:
            continue
        for name in pat.findall(src):
            used.setdefault(name, set()).add(os.path.relpath(fp, ROOT))

missing = sorted(n for n in used if n not in art)
print("ART:", len(art), " referenced:", len(used))
if missing:
    print("MISSING (%d):" % len(missing))
    for n in missing:
        print("  ", n, "<-", ", ".join(sorted(used[n])[:3]))
    sys.exit(1)
print("OK: all referenced FluentIcon members are in ART")
