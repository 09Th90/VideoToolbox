#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# @version 1.18.3
"""split -> batch_XX.tsv ; merge -> zh_map.json ; apply -> r3.srt ; verify -> 结构断言
源文件结构：3908 条 x 4 行 + 3907 空行 = 19539 行，CRLF，无 BOM。"""
import os, re, sys, glob, json

ROOT = r"I:\Agent Work\软件开发\视频工具箱\review"
SRC = r"D:\原片\Reacting to ALL the resonator showcases - Wuthering Waves\【字幕】Reacting to ALL the resonator showcases - Wuthering Waves.en-谷歌翻译.calib.r2.srt"
DST = r"D:\原片\Reacting to ALL the resonator showcases - Wuthering Waves\【字幕】Reacting to ALL the resonator showcases - Wuthering Waves.en-谷歌翻译.calib.r3.srt"
TIME_RE = re.compile(r'\d\d:\d\d:\d\d,\d\d\d --> \d\d:\d\d:\d\d,\d\d\d$')

def read_src_lines():
    raw = open(SRC, 'rb').read()
    assert raw[:3] != b'\xef\xbb\xbf', 'unexpected BOM'
    assert raw.count(b'\r') == raw.count(b'\n'), 'mixed EOL'
    lines = raw.decode('utf-8').split('\r\n')
    if lines and lines[-1] == '': lines.pop()
    return lines

def parse(lines):
    assert len(lines) == 3908*5 - 1, f"line count {len(lines)}"
    items = []
    for i in range(0, len(lines), 5):
        block = lines[i:i+5]
        if i + 4 < len(lines):
            assert block[4] == '', f"not blank @{i}"
        idx, t, zh = block[0], block[1], block[2]
        en = block[3]
        assert re.fullmatch(r'\d+', idx) and TIME_RE.fullmatch(t), f"bad head @{idx}"
        items.append((idx, t, zh, en))
    assert [int(a[0]) for a in items] == list(range(1, 3909)), 'index sequence broken'
    return items

def cmd_split(nbatch=20):
    lines = open(os.path.join(ROOT, 'all.tsv'), encoding='utf-8').read().rstrip('\n').split('\n')
    assert len(lines) == 3908
    size = -(-len(lines) // nbatch)
    for i in range(0, len(lines), size):
        n = i // size + 1
        open(os.path.join(ROOT, f'batch_{n:02d}.tsv'), 'w', encoding='utf-8', newline='\n').write('\n'.join(lines[i:i+size]) + '\n')
        print(f"batch_{n:02d}.tsv #{lines[i].split(chr(9))[0]}..#{lines[min(i+size,len(lines))-1].split(chr(9))[0]} ({len(lines[i:i+size])})")

def cmd_merge():
    m, dup, bad = {}, [], []
    files = sorted(glob.glob(os.path.join(ROOT, 'out_*.tsv')))
    print("out files:", [os.path.basename(f) for f in files])
    for p in files:
        for ln in open(p, encoding='utf-8'):
            ln = ln.rstrip('\n').rstrip('\r')
            if not ln.strip(): continue
            parts = ln.split('\t')
            if len(parts) < 2 or not re.fullmatch(r'\d+', parts[0]):
                bad.append((os.path.basename(p), ln[:60])); continue
            idx = parts[0]
            zh = '\t'.join(parts[1:]).strip()
            if idx in m: dup.append(idx)
            m[idx] = zh
    allidx = {str(i) for i in range(1, 3909)}
    missing = sorted(allidx - set(m), key=int)
    extra = sorted(set(m) - allidx, key=int)
    empty = sorted([i for i, v in m.items() if not v], key=int)
    nl = sorted([i for i, v in m.items() if '\n' in v or '\r' in v], key=int)
    def w(s):
        return sum(1.0 if ord(c) > 0x2E80 else 0.5 for c in s)
    toowide = sorted([(i, round(w(v),1)) for i, v in m.items() if w(v) > 22.5], key=lambda x: int(x[0]))
    print(f"got={len(m)} missing={len(missing)} extra={len(extra)} dup={len(dup)} badformat={len(bad)} empty={len(empty)} newline={len(nl)} toowide={len(toowide)}")
    if missing[:30]: print("MISSING:", missing[:30])
    if extra[:10]: print("EXTRA:", extra[:10])
    if dup[:10]: print("DUP:", dup[:10])
    if bad[:10]: print("BAD:", bad[:10])
    if empty[:30]: print("EMPTY:", empty[:30])
    if toowide[:30]: print("WIDE:", toowide[:30])
    if not (missing or extra or dup or bad or empty or nl):
        json.dump(m, open(os.path.join(ROOT, 'zh_map.json'), 'w', encoding='utf-8'), ensure_ascii=False)
        print("WROTE zh_map.json")
    else:
        print("MERGE NOT CLEAN")

def cmd_apply():
    m = json.load(open(os.path.join(ROOT, 'zh_map.json'), encoding='utf-8'))
    assert len(m) == 3908
    lines = read_src_lines()
    items = parse(lines)
    out = []
    for k, (idx, t, zh, en) in enumerate(items):
        out.append(idx); out.append(t); out.append(m[idx]); out.append(en)
        if k < len(items) - 1: out.append('')
    data = '\r\n'.join(out) + '\r\n'
    open(DST, 'wb').write(data.encode('utf-8'))
    print("wrote", DST, os.path.getsize(DST), "bytes")

def cmd_verify():
    a = parse(read_src_lines())
    raw = open(DST, 'rb').read()
    assert raw[:3] != b'\xef\xbb\xbf', 'BOM appeared'
    assert raw.count(b'\r') == raw.count(b'\n') or (raw.count(b'\r\n')*2 == raw.count(b'\n')), 'EOL mixed'
    lines = raw.decode('utf-8').split('\r\n')
    if lines and lines[-1] == '': lines.pop()
    b = parse(lines)
    errs = []
    changed = 0
    for (i1,t1,z1,e1),(i2,t2,z2,e2) in zip(a,b):
        if i1!=i2 or t1!=t2: errs.append(f"head@{i1}")
        if e1!=e2: errs.append(f"EN changed @{i1}")
        if z1!=z2: changed += 1
    print(f"blocks={len(b)} zh_changed={changed}/{len(a)}")
    print("ERRORS:", errs[:10] if errs else "none — 时间轴/英文行/序号全部一致")

if __name__ == '__main__':
    {'split': cmd_split, 'merge': cmd_merge, 'apply': cmd_apply, 'verify': cmd_verify}[sys.argv[1]]()
