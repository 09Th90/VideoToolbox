# -*- coding: utf-8 -*-
# @version 1.19.0
"""查看指定候选错形的原始 cue 上下文（旧行/新行全貌），供裁断锚点用。"""
import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

FILES = {
    "fix_endfield_report01.tsv": "endobi",
    "fix_talos2.tsv": "endobi",
    "fix_talos2_v2.tsv": "endobi",
    "fix_talos2_report01_356.tsv": "endobi",
    "side_calib.tsv": "endobi",
    "side3.tsv": "endobi",
    "work_si_argent/fix1.tsv": "endobi",
    "work_si_argent/fix2.tsv": "endobi",
    "work_si_argent/fix3.tsv": "endobi",
    "work_si_argent/fix4.tsv": "endobi",
    "work_si_argent/calib_v4.tsv": "endobi",
    "outbox/calib_diff_adhd_reacts_37_final.tsv": "bi",
}
for p in glob.glob(os.path.join(ROOT, "work_jadealy", "calib_*.tsv")):
    FILES[os.path.relpath(p, ROOT).replace("\\", "/")] = "ko"


def main():
    needles = sys.argv[1:]
    if not needles:
        print("用法: _show_calib_ctx.py <错形> [<错形> ...]")
        return 2
    for rel in FILES:
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            continue
        hits = []
        for line in open(path, encoding="utf-8", errors="replace"):
            line = line.rstrip("\r\n")
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            num, old, new = parts[0], parts[1], parts[2]
            if any(nd in old for nd in needles):
                hits.append((num, old, new))
        if hits:
            print("==== %s (%s) ====" % (rel, FILES[rel]))
            for num, old, new in hits[:14]:
                print("  #%s" % num)
                print("    旧: %s" % old)
                print("    新: %s" % new)
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
