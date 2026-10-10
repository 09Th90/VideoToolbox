# -*- coding: utf-8 -*-
# @version 1.19.0
"""从校准临时文件（fix / calib TSV）里挖「可复用的错形→正形」，并与 KB 查重。

背景：这些 TSV 是 subfix 的逐句修复记录（num\\t旧行\\t新行），已应用到成品 SRT。
合并进 subtitle_calib_merged.py 的应是其中**可复用的规律**（错形→正形），
不是逐句文本。本脚本用 difflib 取每行的变更片段，聚频后与 KB 查重，
输出「新候选 / 已在 KB」两份清单供人工裁断 —— 不直接写库。
"""
import difflib
import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
KB_PATH = os.path.join(ROOT, "subtitle_calib_merged.py")

#: (文件, 片源模式) —— 文件名 -> mode
FILES = {
    # 终末地（--endobi / --endo）
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
    # 鸣潮（--ko / bi）
    "outbox/calib_diff_adhd_reacts_37_final.tsv": "bi",
    "outbox/calib_diff_adhd_reacts_37.tsv": "bi",
    "outbox/calib_diff_adhd_reacts_37_v2.tsv": "bi",
    "outbox/calib_diff_adhd_reacts_37_v3.tsv": "bi",
}
for p in glob.glob("work_jadealy/calib_*.tsv"):
    FILES[p.replace("\\", "/")] = "ko"


def load_kb_text():
    return open(KB_PATH, encoding="utf-8").read()


def changed_pairs(old, new):
    """取一行旧→新的变更片段对，过滤纯空白/标点差异。"""
    sm = difflib.SequenceMatcher(None, old, new, autojunk=False)
    out = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("equal",):
            continue
        o, n = old[i1:i2], new[j1:j2]
        if not o or not n:
            continue
        if o.strip() == n.strip():
            continue
        # 去掉两侧共用的空白，避免把「空格差异」当术语
        o2, n2 = o.strip(), n.strip()
        if not o2 or not n2 or o2 == n2:
            continue
        out.append((o2, n2))
    return out


CJK = re.compile(r"[\u4e00-\u9fff]")


def looks_like_term(o, n):
    """像术语错形的粗过滤：两侧都含汉字/字母，长度适中，且不是整句改写。"""
    if not (2 <= len(o) <= 14 and 2 <= len(n) <= 14):
        return False
    if not (CJK.search(o) or re.search(r"[A-Za-z]", o)):
        return False
    if not (CJK.search(n) or re.search(r"[A-Za-z]", n)):
        return False
    # 整句改写（长度差异过大 / 变更占比过高）不算术语
    if abs(len(o) - len(n)) > max(6, min(len(o), len(n))):
        return False
    # 纯标点/数字差异不算
    if not re.search(r"[\u4e00-\u9fffA-Za-z]", o) or \
       not re.search(r"[\u4e00-\u9fffA-Za-z]", n):
        return False
    return True


def main():
    kb = load_kb_text()
    cand = Counter()          # (old, new) -> 次数
    src_of = defaultdict(set)
    mode_of = defaultdict(set)
    parsed = skipped = 0

    for rel, mode in FILES.items():
        path = os.path.join(ROOT, rel)
        if not os.path.isfile(path):
            print("  [跳过] 不存在：%s" % rel)
            continue
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.rstrip("\n").rstrip("\r")
                if not line.strip():
                    continue
                parts = line.split("\t")
                if len(parts) < 3:
                    skipped += 1
                    continue
                num, old, new = parts[0], parts[1], parts[2]
                if not old or not new or old == new:
                    continue
                parsed += 1
                for o, n in changed_pairs(old, new):
                    if looks_like_term(o, n):
                        key = (o, n)
                        cand[key] += 1
                        src_of[key].add(os.path.basename(rel))
                        mode_of[key].add(mode)

    print("解析 %d 行修复记录，候选片段 %d 个" % (parsed, len(cand)))

    # 与 KB 查重：错形是否已是 KB 里的键（或出现在键里）
    def in_kb(s):
        return ('"%s"' % s) in kb or ("'%s'" % s) in kb

    fresh = [(o, n, c) for (o, n), c in cand.items() if not in_kb(o)]
    known = [(o, n, c) for (o, n), c in cand.items() if in_kb(o)]

    # 按「出现次数 × 出现文件数」排序；单文件单次的通常是逐句措辞，不是术语
    def rank(item):
        o, n, c = item
        return (-c, -len(src_of[(o, n)]), o)

    fresh.sort(key=rank)

    out = {
        "parsed_lines": parsed,
        "candidates_total": len(cand),
        "already_in_kb": len(known),
        "fresh": [
            {"old": o, "new": n, "count": c,
             "files": sorted(src_of[(o, n)]), "modes": sorted(mode_of[(o, n)])}
            for o, n, c in fresh
        ],
    }
    outp = os.path.join(ROOT, "data", "tmp", "_calib_mine_report.json")
    os.makedirs(os.path.dirname(outp), exist_ok=True)
    json.dump(out, open(outp, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

    print("\n== 新候选（不在 KB）：%d 个，按频次排序，前 60 ==" % len(fresh))
    for o, n, c in fresh[:60]:
        files = sorted(src_of[(o, n)])
        print("  %dx  %-14s -> %-14s  [%s]" % (c, o, n, ",".join(files)[:56]))
    print("\n== 已在 KB（无需重复加）：%d 个 ==" % len(known))
    for o, n, c in known[:15]:
        print("  %dx  %-14s -> %-14s" % (c, o, n))
    print("\n明细已写到：%s" % outp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
