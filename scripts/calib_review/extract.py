#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# @version 1.18.2
"""结构体检 + 导出审阅用清单（编号 / 中文行 / 英文行）。"""
import re, os, collections

SRC = r"D:\原片\Reacting to ALL the resonator showcases - Wuthering Waves\【字幕】Reacting to ALL the resonator showcases - Wuthering Waves.en-谷歌翻译.calib.r2.srt"
OUT = r"I:\Agent Work\软件开发\视频工具箱\review"
os.makedirs(OUT, exist_ok=True)

raw = open(SRC, 'rb').read()
out = []
W = out.append
W(f"bom={raw[:3]==b'\xef\xbb\xbf'} crlf={raw.count(b'\r\n')} lf={raw.count(b'\n')}")
text = raw.decode('utf-8')

# 用正则切块：编号 / 时间轴 / 其余内容
blocks = re.split(r'\r?\n\r?\n+', text.strip())
W(f"blocks={len(blocks)}")

shape = collections.Counter()
items = []
bad = []
for n, b in enumerate(blocks):
    L = b.split('\n')
    L = [x.rstrip('\r') for x in L]
    shape[len(L)] += 1
    if not re.fullmatch(r'\d+', L[0].strip()):
        bad.append(('idx', n, b[:80])); continue
    if not re.fullmatch(r'\d\d:\d\d:\d\d,\d\d\d --> \d\d:\d\d:\d\d,\d\d\d', L[1].strip()):
        bad.append(('time', n, b[:80])); continue
    if len(L) < 3:
        bad.append(('short', n, b[:80])); continue
    items.append((L[0].strip(), L[1].strip(), L[2], '\n'.join(L[3:])))

W(f"shapes={dict(shape)}")
W(f"items={len(items)} bad={len(bad)}")
for x in bad[:20]: W(f"  BAD {x}")

# 编号连续性
seq_ok = all(items[i][0] == str(i+1) for i in range(len(items)))
W(f"index_seq_continuous={seq_ok}")

# 中文行是否含拉丁 / 英文行是否为空
latin = [it for it in items if re.search(r'[A-Za-z]{2,}', it[2])]
empty_en = [it for it in items if not it[3].strip()]
W(f"zh_with_latin={len(latin)} en_empty={len(empty_en)}")

# 中文行含全角/半角混排异常
cjk_only = [it for it in items if not re.search(r'[\u4e00-\u9fff]', it[2])]
W(f"zh_without_cjk={len(cjk_only)}")
for it in cjk_only[:30]: W(f"  NOCJK #{it[0]}: {it[2]!r} | {it[3]!r}")

with open(os.path.join(OUT, 'extract_info.txt'), 'w', encoding='utf-8') as f:
    f.write('\n'.join(out))

# 导出审阅清单（TSV：idx \t zh \t en）
with open(os.path.join(OUT, 'all.tsv'), 'w', encoding='utf-8', newline='') as f:
    for idx, t, zh, en in items:
        f.write(f"{idx}\t{zh}\t{en.replace(chr(10),' / ')}\n")
W("wrote all.tsv")
open(os.path.join(OUT, 'extract_info.txt'), 'a', encoding='utf-8').write('\nwrote all.tsv')
print('\n'.join(out))
