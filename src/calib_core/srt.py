# -*- coding: utf-8 -*-
# @version 2.7.0
"""SRT 解析、抽段、切分、配对与合并

源：subtitle_calib_merged.py L12061-L13070 @ 97d7d463（2026-10-24 冻结快照）
"""
import io
import os
import re
import shutil
import sys
import unicodedata
from .data.misc import MERGE_FIXES
from .text import _decode_any, _is_chinese_line, _iter_cue_text_blocks, _split_cue_text



def _detect_layout(lines):
    """返回片源版式：'mono'（单语，文本行即校准目标、无参考行）或 'bi'（双语，末行为参考行）。

    r_single：仅 1 个文本行的 cue 占比；r_zh_last：末行中文主导的 cue 占比。
    纯中文单行片 r_single≈1、r_zh_last≈1 → mono；常规中+外双行片 r_single≈0 → bi。
    """
    blocks = list(_iter_cue_text_blocks(lines))
    if not blocks:
        return "bi"
    total = len(blocks)
    single = sum(1 for t in blocks if len(t) == 1)
    last_zh = sum(1 for t in blocks if _is_chinese_line(t[-1]))
    r_single = single / total
    r_zh_last = last_zh / total
    if r_single >= 0.95 or (r_single >= 0.80 and r_zh_last >= 0.98):
        return "mono"
    return "bi"



def _cmd_extract(src, out):
    """extract：把 SRT 抽为 cue 表 num/中文/英文，中文/英文多行用 \\n 转义。

    双语片（bi）：中文=除末行外文本行，英文=末行参考行；
    单语片（mono，如纯中文单行熟肉）：全部文本行即中文，英文列留空。"""
    raw = open(src, "rb").read()
    norm = (_decode_any(raw).replace("\r\n", "\n").replace("\r", "\n"))
    lines = norm.split("\n")
    layout = _detect_layout(lines)
    recs = []
    i, n = 0, len(lines)
    while i < n:
        s = lines[i].strip()
        if s.isdigit() and (i == 0 or lines[i - 1].strip() == ""):
            j = i + 1
            if j < n and "-->" in lines[j]:
                kk = j + 1
                while kk < n and lines[kk].strip() != "":
                    kk += 1
                texts = lines[j + 1:kk]
                if not texts:
                    i = kk; continue
                esc = lambda x: x.replace("\\", "\\\\").replace("\u0009", " ").replace("\n", "\\n")
                zh_pos, ref_pos = _split_cue_text(texts)
                if layout == "mono" or (zh_pos and not ref_pos):
                    zh = "\\n".join(esc(texts[i]) for i in (zh_pos or range(len(texts))))
                    en = ""
                elif zh_pos:
                    # 按语言定位，兼容英文在上/中文在下与中文在上两种版式
                    zh = "\\n".join(esc(texts[i]) for i in zh_pos)
                    en = "\\n".join(esc(texts[i]) for i in ref_pos)
                else:
                    zh = esc(texts[0])
                    en = esc(texts[-1]) if len(texts) > 1 else ""
                recs.append((s, zh, en))
                i = kk
                continue
        i += 1
    with open(out, "w", encoding="utf-8", newline="") as f:
        f.write("序号\t中文行\t英文行\n")
        for num, zh, en in recs:
            f.write(f"{num}\t{zh}\t{en}\n")
    print(f"[{layout}] cues={len(recs)} -> {out}")



def _cmd_split(cues, prefix, n, letters="ABCDEFGHIJKLMNOP"):
    """split：把 cues.tsv 切为 n 段（输入 seg_{X}.tsv + 输出空 calib_{X}.tsv），供并行校准。"""
    segs = min(n, len(letters))
    if n > len(letters):
        segs = n  # 允许超过字母表，用数字后缀
    rows = open(cues, encoding="utf-8").read().splitlines()
    header, data = rows[0], rows[1:]
    ntotal = len(data)
    size = (ntotal + segs - 1) // segs
    for k in range(segs):
        chunk = data[k * size:(k + 1) * size]
        tag = letters[k] if k < len(letters) else str(k + 1)
        with open(f"{prefix}seg_{tag}.tsv", "w", encoding="utf-8", newline="") as f:
            f.write(header + "\n")
            for r in chunk:
                f.write(r + "\n")
        with open(f"{prefix}calib_{tag}.tsv", "w", encoding="utf-8", newline="") as f:
            f.write("num\tnew_zh\n")
        first = chunk[0].split("\t")[0] if chunk else "-"
        last = chunk[-1].split("\t")[0] if chunk else "-"
        print(f"seg_{tag}.tsv: rows={len(chunk)} num=({first}..{last})")



def _cmd_pair(seg, txt, out=None):
    """pair：把「纯文本逐行译文」按 seg 的序号配对成 calib 表（2026-10-01 沉淀）。

    Agent 级逐段校准时**手写 `num<TAB>text` 会整体漂移**（2026-10-01 鸣潮 3.7 日语片
    实测错位 185 行：多写一行后，其后所有序号集体 −1）。正确姿势是：
      ① 只写**纯文本**（每行一个 cue，顺序与 seg 完全一致，允许含空行占位）；
      ② 用本子命令配对，**序号一律取自 seg**，人手永远不写序号；
      ③ 行数不一致直接报错退出，绝不产出错表。
    文本文件可带一列表头（new_zh / 中文 / 校准后中文 / 序号…），自动跳过。
    """
    seg_rows = []
    for ln in _decode_any(open(seg, "rb").read()).splitlines():
        ln = ln.strip("\ufeff").rstrip("\r")
        if not ln or ln.startswith("序号") or ln.startswith("num\t"):
            continue
        m = re.match(r"(\d+)", ln)
        if m:
            seg_rows.append(m.group(1))
    lines = [x.rstrip("\r") for x in _decode_any(open(txt, "rb").read()).splitlines()]
    while lines and (lines[0].strip() in ("new_zh", "中文", "校准后中文")
                     or lines[0].startswith("序号")):
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if len(seg_rows) != len(lines):
        print(f"PAIR FAIL：{os.path.basename(seg)} 有 {len(seg_rows)} 个序号，"
              f"{os.path.basename(txt)} 有 {len(lines)} 行文本，无法配对")
        for i in range(min(len(seg_rows), len(lines))):
            if not lines[i].strip():
                print(f"  首个空行在文本第 {i + 1} 行 -> 对应 cue #{seg_rows[i]}")
                break
        return 1
    blanks = [i + 1 for i, x in enumerate(lines) if not x.strip()]
    if blanks:
        print(f"PAIR WARN：文本第 {blanks[:5]} 行为空（若是漏写，请补齐后重跑）")
    if out is None:
        d, b = os.path.split(seg)
        out = os.path.join(d, b.replace("seg_", "calib_", 1)
                           if b.startswith("seg_") else b + ".calib.tsv")
    with open(out, "w", encoding="utf-8", newline="") as f:
        f.write("num\tnew_zh\n")
        for num, t in zip(seg_rows, lines):
            f.write(f"{num}\t{t.strip()}\n")
    print(f"PAIR OK：{len(seg_rows)} 条 -> {out}（序号取自 {os.path.basename(seg)}）")
    return 0



def _load_calib_records(src):
    """加载校准表（单个文件或目录，含 seg_*/calib_* 字样）：鲁棒解析 序号<TAB>校准后中文。"""
    import glob
    new_zh = {}
    if os.path.isdir(src):
        files = []
        for pat in ("calib_*", "seg_*", "cal_*", "_corrected"):
            if pat == "_corrected":
                files += sorted(glob.glob(os.path.join(src, "*_corrected.tsv")))
            else:
                files += sorted(glob.glob(os.path.join(src, f"{pat}*.tsv")))
        files = [f for f in files if os.path.isfile(f)]
    elif "*" in src:
        files = sorted(glob.glob(src))
    else:
        files = [src] if os.path.exists(src) else []
    for p in files:
        for ln in _decode_any(open(p, "rb").read()).splitlines():
            ln = ln.strip("\ufeff").rstrip("\r")
            m = re.match(r"(\d+)", ln)
            if not m:
                continue
            txt = ln[m.end():].lstrip("\t \u3000\u3000").strip()
            rest = ln[m.end():]
            if rest.count("\t") >= 2:   # seg_*三列原文段(序号\t原文\t参考行)不是校准表，跳过，
                continue                 # 防止目录合并时按文件名序在calib_*后加载、用机译原文反向覆盖人工校准
            if txt:
                new_zh[m.group(1)] = txt
    return new_zh



def _cmd_merge(src, calib_src, out, compare=None, side=None, apply_fix=False):
    """merge：读校准段回填重建 SRT（只替换中文内容行），严格保留序号/时间轴/参考行/换行/BOM。
    另可写出对照表(--compare)与侧车覆盖表(--side)。
    apply_fix=True 时对回填中文再套 MERGE_FIXES 跨段统一（历史 AK 项目 FIXES 沉淀）。"""
    def _norm_fix(s):
        if apply_fix:
            for a, b in MERGE_FIXES:
                s = s.replace(a, b)
        return s
    orig = _load_calib_records(calib_src)
    raw = open(src, "rb").read()
    bom = raw.startswith(b"\xef\xbb\xbf")
    crlf = b"\r\n" in raw
    norm = _decode_any(raw).replace("\r\n", "\n").replace("\r", "\n")
    lines = norm.split("\n")
    layout = _detect_layout(lines)
    spans, timecodes, orig_zh = [], [], {}
    en_by_num = {}            # 序号->参考行：cue 编号不连续时对照表不再错行
    i, n = 0, len(lines)
    while i < n:
        s = lines[i].strip()
        if s.isdigit() and (i == 0 or lines[i - 1].strip() == ""):
            j = i + 1
            if j < n and "-->" in lines[j]:
                kk = j + 1
                while kk < n and lines[kk].strip() != "":
                    kk += 1
                texts = lines[j + 1:kk]
                if not texts:
                    i = kk; continue
                num = s
                timecodes.append(lines[j])
                if layout == "mono":
                    # 单语片：全部文本行都是待校准目标，没有末位参考行。
                    # 目标区间 [j+1, kk) 含唯一文本行，回填时才会真正覆盖。
                    t_st, t_ed, has_target = j + 1, kk, True
                    en_by_num[num] = ""
                    orig_zh[num] = "\n".join(texts)
                else:
                    # 双语片：中文行区间 [j+1, kk-1)，末行 kk-1 为不可改动的参考行；
                    # 单文本行 cue 无中文行（st==ed），重建时原样保留、绝不覆盖参考行。
                    t_st, t_ed = j + 1, kk - 1
                    has_target = len(texts) >= 2
                    en_by_num[num] = texts[-1]
                    orig_zh[num] = "\n".join(texts[:-1])
                spans.append((t_st, t_ed, num, has_target))
                i = kk
                continue
        i += 1
    # 2026-09-05 重建式回填：旧实现 out_lines[st:ed]=[单行] 在多行中文 cue
    # （歌词片源）被覆盖成单行后，后续 cue 的行索引静默错位、
    # 串写到错误位置。按 cue 边界重建输出：单行场景与旧实现逐字节一致；
    # 校准文本自带 \n 时按多行展开，多行原文 cue 无校准也原样保留。
    out_lines, prev = [], 0
    for t_st, t_ed, num, has_target in spans:
        out_lines.extend(lines[prev:t_st])
        if has_target and num in orig:
            out_lines.extend(_norm_fix(orig[num]).split("\n"))
        else:
            out_lines.extend(lines[t_st:t_ed])
        prev = t_ed
    out_lines.extend(lines[prev:])
    body = "\n".join(out_lines)
    if crlf:
        body = body.replace("\n", "\r\n")
    with open(out, "w", encoding="utf-8", newline="") as f:
        f.write(("\ufeff" if bom else "") + body)
    print(f"[{layout}] 校准条目:", len(orig), "| 已应用:", sum(1 for k in orig if k in orig_zh),
          "| 校准但原文件无此cue:", [k for k in sorted(orig, key=int) if k not in orig_zh])
    if compare:
        with open(compare, "w", encoding="utf-8", newline="") as f:
            f.write("序号\t原文中文(机翻)\t校准后中文\t英文行\n")
            for k in sorted(orig, key=int):
                f.write(f"{k}\t{orig_zh.get(k, '')}\t{orig[k]}\t{en_by_num.get(k, '')}\n")
        print("对照表:", compare)
    if side:
        with open(side, "w", encoding="utf-8", newline="") as f:
            f.write("num\tnew_zh\n")
            for k in sorted(orig, key=int):
                f.write(f"{k}\t{orig[k]}\n")
        print("侧车覆盖表:", side)
    print("写入:", out)



def _iter_cue_lines(path):
    """产出 (序号, 内容行列表, 参考行)。与 process()/subfix 同一套块判据。

    双语片（bi）：内容行=除末行外文本行，参考行=末行；
    单语片（mono）：全部文本行都是内容行，参考行为 None（length 等据此跳过参考行检查）。"""
    raw = open(path, "rb").read()
    lines = _decode_any(raw).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    layout = _detect_layout(lines)
    i, n = 0, len(lines)
    while i < n:
        s = lines[i].strip()
        if s.isdigit() and (i == 0 or lines[i - 1].strip() == ""):
            j = i + 1
            if j < n and "-->" in lines[j]:
                kk = j + 1
                while kk < n and lines[kk].strip() != "":
                    kk += 1
                texts = lines[j + 1:kk]
                if texts:
                    if layout == "mono":
                        yield s, texts, None
                    else:
                        yield s, texts[:-1], texts[-1]
                i = kk
                continue
        i += 1



# =============================================================
# 对齐体检（align-audit 子命令，2026-10-01 新增）
#
#   动机：Agent 级逐段校准（extract → split → 逐块人工改 → merge）最容易犯的
#   不是术语错，而是**cue 串位**——某段校准结果整体偏移、两条 cue 内容互换、
#   或相邻 cue 重复。这类错误 `verify` **完全查不出来**（序号/时间轴/参考行
#   都没动，只有中文行变了），可观众看到的是"中文和英文对不上"。
#   2026-10-01 明日方舟男干员调查片（961 cue）两轮共查出 15 处串位，
#   其中含 376↔390、378↔379 两处**整块互换**，全靠本判据人工比对才揪出来，
#   故固化为子命令。
#
#   判据（全部只读，绝不改文件）：
#     A 串位嫌疑：校准行与「源文件第 n±K 条机翻行」的相似度显著高于第 n 条本身
#        （K=window，倍数=ratio，下限=min-ratio）→ 该条中文很可能属于别的 cue。
#        **A 类存在时退出码 1**，可直接在流水线里当门禁。
#     B 接缝叠字：第 n 条末尾 L 字 == 第 n+1 条开头 L 字（L=3,2）→ 跨 cue 重复。
#     C 起首标点：内容行以 。，、！？；：）】”’ 开头 → 上一条的断句被劈开。
#     D 空行 / 行宽超限（复用 length 的 32 汉字当量判据）。
#
#   注意：A 类判据是**启发式**，Agent 有意把内容跨 cue 重排（为了连读通顺）时
#   会误报，需人工确认；B/C/D 是硬判据。
#   用法：align-audit <src.srt> <out.srt> [--window 5] [--ratio 1.45] [--quiet]
# =============================================================

def _cue_first_text_map(path):
    """读 SRT -> {序号: 首个内容行}。与 process/merge 同一套块判据。"""
    out = {}
    raw = open(path, "rb").read()
    lines = _decode_any(raw).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    i, n = 0, len(lines)
    while i < n:
        s = lines[i].strip()
        if s.isdigit() and (i == 0 or lines[i - 1].strip() == ""):
            j = i + 1
            if j < n and "-->" in lines[j]:
                kk = j + 1
                while kk < n and lines[kk].strip() != "":
                    kk += 1
                texts = lines[j + 1:kk]
                if texts:
                    out[int(s)] = texts[0]
                i = kk
                continue
        i += 1
    return out



def _iter_ref_lines(path):
    """逐 cue 产出 (序号, 参考行)：双语 SRT 里中文行(首个文本行)以外的文本行。"""
    raw = open(path, "rb").read()
    lines = _decode_any(raw).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    i, n = 0, len(lines)
    while i < n:
        s = lines[i].strip()
        if s.isdigit() and (i == 0 or lines[i - 1].strip() == ""):
            j = i + 1
            if j < n and "-->" in lines[j]:
                kk = j + 1
                while kk < n and lines[kk].strip() != "":
                    kk += 1
                if kk - 1 >= j + 2:              # 存在独立参考行
                    for ti in range(j + 2, kk):
                        yield int(s), lines[ti]
                i = kk
                continue
        i += 1

