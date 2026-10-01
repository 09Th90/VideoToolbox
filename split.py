#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# @version 1.16.4
"""把 all.tsv 切成等量批次，供并行精校。"""
import os
R = r"I:\Agent Work\软件开发\视频工具箱\review"
lines = open(os.path.join(R, 'all.tsv'), encoding='utf-8').read().rstrip('\n').split('\n')
N = 12
size = -(-len(lines) // N)
man = []
for i in range(0, len(lines), size):
    n = i // size + 1
    chunk = lines[i:i+size]
    p = os.path.join(R, f'batch_{n:02d}.tsv')
    open(p, 'w', encoding='utf-8', newline='\n').write('\n'.join(chunk) + '\n')
    first, last = chunk[0].split('\t')[0], chunk[-1].split('\t')[0]
    man.append((n, len(chunk), first, last))
    print(f"batch_{n:02d}.tsv  {len(chunk)} lines  #{first}..#{last}")
print("total", sum(m[1] for m in man))
