# -*- coding: utf-8 -*-
# @version 2.8.0
"""结构体检、比较、漏译、扫描与 subfix

源：subtitle_calib_merged.py L12795-L13481 @ 97d7d463（2026-10-24 冻结快照）
"""
import io
import os
import re
import shutil
import sys
import unicodedata
from .asr import _scan_split_line
from .data.ark import AK_MISSING_CHECK
from .data.bilingual import WUWA_MISSING_CHECK
from .data.endfield import ENDFIELD_MISSING_CHECK
from .format import is_line_too_long, line_width
from .srt import _cue_first_text_map, _detect_layout, _iter_ref_lines, _load_calib_records
from .state import CTX_TABLES, TABLES
from .text import _MARKER_ONLY, _decode_any, _split_cue_text



def _cmd_align_audit(src, out, window=5, ratio=1.45, min_ratio=0.45, quiet=False, strict=False):
    """对齐体检：查 cue 串位 / 接缝叠字 / 起首标点 / 空行超长。返回退出码。"""
    import difflib
    s_map = _cue_first_text_map(src)
    o_map = _cue_first_text_map(out)
    nums = sorted(o_map)
    if not nums:
        print("align-audit：未解析到 cue，请检查输入"); return 1

    A, B, C, D = [], [], [], []
    for n in nums:
        new = o_map[n]
        base = difflib.SequenceMatcher(None, new, s_map.get(n, "")).ratio()
        best_r, best_k = 0.0, None
        for k in range(n - window, n + window + 1):
            if k == n or k not in s_map:
                continue
            r = difflib.SequenceMatcher(None, new, s_map[k]).ratio()
            if r > best_r:
                best_r, best_k = r, k
        if best_k is not None and best_r > base * ratio and best_r > min_ratio:
            A.append((n, best_k, best_k - n, base, best_r))
    for i in range(len(nums) - 1):
        a, b = o_map[nums[i]], o_map[nums[i + 1]]
        if len(a) < 3 or len(b) < 3:
            continue
        for L in (3, 2):
            if a[-L:] == b[:L]:
                B.append((nums[i], nums[i + 1], a[-8:], b[:8])); break
    for n in nums:
        t = o_map[n].lstrip()
        if t and t[0] in "。，、！？；：）】”’":
            C.append((n, o_map[n]))
    for n in nums:
        t = o_map[n].strip()
        if not t:
            D.append((n, "空行"))
        elif is_line_too_long(t):
            D.append((n, "行宽 %.1f 超限" % line_width(t)))

    if not quiet:
        print(f"align-audit：src {len(s_map)} cue / out {len(o_map)} cue"
              f"（窗口 ±{window}，倍数 {ratio}）")
        print(f"  A 串位嫌疑 {len(A)} 处")
        for n, k, off, b, r in A[:40]:
            print(f"    cue {n} 更像源第 {k} 条（偏移 {off:+d}，相似 {b:.2f} -> {r:.2f}）"
                  f" | 现: {o_map[n][:22]}")
        print(f"  B 接缝叠字 {len(B)} 处")
        for a, b_, ta, tb in B[:20]:
            print(f"    {a}→{b_}: …{ta} ‖ {tb}…")
        print(f"  C 起首标点 {len(C)} 处")
        for n, t in C[:20]:
            print(f"    cue {n}: {t[:24]}")
        print(f"  D 空行/超长 {len(D)} 处")
        for n, why in D[:20]:
            print(f"    cue {n}: {why}")
    if A:
        print(f"ALIGN-AUDIT：存在 {len(A)} 处串位嫌疑，请人工确认后再交付"
              + ("（--strict：按门禁失败）" if strict else "（默认不判失败；加 --strict 可当门禁）"))
        return 1 if strict else 0
    print("ALIGN-AUDIT OK：无串位嫌疑")
    return 0



def _cmd_verify(src, out):
    """verify：校验两个 SRT cue数/序号/时间轴/参考行/换行/BOM 全一致，仅内容文本行变化。

    双语片（bi）：额外断言末位参考（英/日/韩）行零变化；
    单语片（mono）：无参考行，断言 cue数/序号/时间轴/总行数/CRLF/BOM 一致，文本行允许变化。"""
    def parse(p):
        raw = open(p, "rb").read()
        crlf = b"\r\n" in raw; bom = raw.startswith(b"\xef\xbb\xbf")
        lines = _decode_any(raw).replace("\r\n", "\n").replace("\r", "\n").split("\n")
        layout = _detect_layout(lines)
        cues = []
        i, n = 0, len(lines)
        while i < n:
            s = lines[i].strip()
            if s.isdigit() and (i == 0 or lines[i - 1].strip() == ""):
                j = i + 1
                if j < n and "-->" in lines[j]:
                    kk = j + 1
                    while kk < n and lines[kk].strip() != "":
                        kk += 1
                    if kk - 1 >= j + 1:
                        # 2026-10-23：保留全部文本行，按语言比对中文/参考行，
                        # 不再只看首行与末行（多行 cue 的中段参考行此前漏检）。
                        cues.append((int(s), lines[j], lines[j + 1:kk]))
                    i = kk
                    continue
            i += 1
        return cues, crlf, bom, layout, len(lines)
    s, scrlf, sbom, slay, snlines = parse(src)
    o, ocrlf, obom, olay, onlines = parse(out)
    print(f"src: {len(s)} cues, {slay}, CRLF={scrlf}, BOM={sbom} | "
          f"out: {len(o)} cues, {olay}, CRLF={ocrlf}, BOM={obom}")
    assert len(s) == len(o), "cue count mismatch"
    assert scrlf == ocrlf, "CRLF mismatch"
    assert sbom == obom, "BOM mismatch"
    assert slay == olay, f"layout mismatch: {slay} vs {olay}"
    if slay == "mono":
        assert snlines == onlines, f"TOTAL LINE COUNT CHANGED! {snlines} vs {onlines}"
    ts = e = z = 0
    for (n1, t1, texts1), (n2, t2, texts2) in zip(s, o):
        assert n1 == n2, f"num mismatch {n1}"
        ts += t1 != t2
        assert len(texts1) == len(texts2), f"text line count changed at cue {n1}"
        if slay == "bi":
            zh1, ref1 = _split_cue_text(texts1)
            zh2, ref2 = _split_cue_text(texts2)
            assert zh1 == zh2 and ref1 == ref2, f"language layout changed at cue {n1}"
            z += sum(texts1[i] != texts2[i] for i in zh1)
            e += sum(texts1[i] != texts2[i] for i in ref1)
        else:
            z += sum(a != b for a, b in zip(texts1, texts2))
    assert ts == 0, "TIMESTAMPS CHANGED!"
    if slay == "bi":
        assert e == 0, "REFERENCE LINES CHANGED!"
        print(f"timestamp diffs: {ts} | reference diffs: {e} | content(zh) diffs: {z}")
        print("VERIFY OK[bi]：仅中文内容行变化，序号/时间轴/参考行/CRLF/BOM 全部一致")
    else:
        print(f"timestamp diffs: {ts} | total lines: {snlines} (unchanged) | text diffs: {z}")
        print("VERIFY OK[mono]：单语片文本行已更新，cue数/序号/时间轴/总行数/CRLF/BOM 全部一致")



def _cmd_compare(src, out, tsv):
    """compare：比对两个 SRT 生成 错误vs正确 对照表（序号/原文中文/校准后中文/英文行）。"""
    def parse(p):
        lines = _decode_any(open(p, "rb").read()).replace("\r\n", "\n").split("\n")
        layout = _detect_layout(lines)
        cues = []
        i, n = 0, len(lines)
        while i < n:
            s = lines[i].strip()
            if s.isdigit() and (i == 0 or lines[i - 1].strip() == ""):
                j = i + 1
                if j < n and "-->" in lines[j]:
                    kk = j + 1
                    while kk < n and lines[kk].strip() != "":
                        kk += 1
                    if kk - 1 >= j + 1:
                        texts = lines[j + 1:kk]
                        zh_pos, ref_pos = _split_cue_text(texts)
                        if layout == "mono":
                            z = " ".join(texts)
                            ref = ""
                        elif zh_pos:
                            z = " ".join(texts[i] for i in zh_pos)
                            ref = " ".join(texts[i] for i in ref_pos)
                        else:
                            z = texts[0]
                            ref = texts[-1] if len(texts) > 1 else ""
                        cues.append((int(s), z, ref))
                    i = kk
                    continue
            i += 1
        return cues
    sc, oc = parse(src), parse(out)
    assert len(sc) == len(oc)
    with open(tsv, "w", encoding="utf-8") as f:
        f.write("序号\t原文中文(机翻)\t校准后中文\t英文行\n")
        for (n1, z1, e1), (n2, z2, e2) in zip(sc, oc):
            if z1 != z2:
                f.write(f"{n1}\t{z1}\t{z2}\t{e1}\n")
    print("对照表:", tsv, "| 改动行数:", sum(1 for a, b in zip(sc, oc) if a[1] != b[1]))



def _load_missing_rules(mode=None, file=None):
    """漏译体检规则：--mode endo 取内置 ENDFIELD_MISSING_CHECK；--mode wuwa 取
    鸣潮专名表 WUWA_MISSING_CHECK；--mode ak 取明日方舟 AK_MISSING_CHECK；--file 追加 TSV
    （每行：英文正则<TAB>中文必现词1|词2[<TAB>说明]，# 开头注释）。"""
    rules = []
    if mode in ("endo", "endobi", "endoko", "jpe"):
        rules.extend(ENDFIELD_MISSING_CHECK)
    if mode in ("wuwa", "wuwa-bi", "ww"):
        rules.extend(WUWA_MISSING_CHECK)
    if mode == "ak":
        rules.extend(AK_MISSING_CHECK)
    if file:
        raw = open(file, "rb").read()
        for ln in _decode_any(raw).splitlines():
            if not ln.strip() or ln.lstrip().startswith("#") or "\t" not in ln:
                continue
            parts = ln.split("\t")
            zhs = tuple(w.strip() for w in parts[1].split("|") if w.strip())
            if parts[0].strip() and zhs:
                note = parts[2].strip() if len(parts) > 2 else ""
                rules.append((parts[0].strip(), zhs, note))
    return rules



def _cmd_missing(ref, target, mode=None, file=None, quiet=False, window=0):
    """missing：漏译体检（只读）。英文参考 cue 命中某术语、中文 cue 却无任一对应中文词
    → 疑似漏译（机翻整词吞掉，--endo/subfix 查不出）。返回退出码：有疑似 1，否则 0。
    window=N（N>0）：把第 n±N 条邻接 cue 的中文并入判定——口播字幕里一个术语的英文和
    中文常被切到相邻两条 cue，严格逐 cue 会把「译在隔壁 cue」误报成漏译；战斗片元素/
    机制词高频跨 cue，建议 --window 1。默认 window=0（严格逐 cue，旧行为）。"""
    rules = _load_missing_rules(mode, file)
    if not rules:
        print("missing：无规则。请加 --mode endo（内置战斗片表）或 --file 映射.tsv"
              "（每行：英文正则<TAB>中文词1|词2）")
        return 1
    rmap = _cue_first_text_map(ref)
    tmap = _cue_first_text_map(target)
    order = sorted(tmap)
    pos = {n: k for k, n in enumerate(order)}

    def zh_around(n):
        if window <= 0:
            return tmap[n]
        k = pos[n]
        return " ".join(tmap[m] for m in order[max(0, k - window):k + window + 1])

    compiled = [(re.compile(p, re.I), zhs, p) for p, zhs, _note in rules]
    hits = []
    for n in order:
        en = rmap.get(n, "")
        if not en:
            continue
        zh = zh_around(n)
        for rx, zhs, pat in compiled:
            if rx.search(en) and not any(z in zh for z in zhs):
                hits.append((n, pat, "/".join(zhs), en.strip().replace("\n", " "),
                             tmap[n].strip().replace("\n", " ")))
    if not quiet:
        scope = f" / 邻接窗口 ±{window}" if window else " / 严格逐cue"
        print(f"missing：英文参考 {len(rmap)} cue / 中文 {len(tmap)} cue / 规则 {len(rules)} 条{scope}")
    if hits:
        print(f"疑似漏译 {len(hits)} 处（英文有术语、中文无对应词）：")
        for n, pat, zhs, en, zh in hits:
            print(f"  cue {n} [{pat} → 须含 {zhs}]\n      EN: {en[:90]}\n      ZH: {zh[:90]}")
        return 1
    if not quiet:
        print("未发现漏译 ✓")
    return 0



def _cmd_scan(cues, min_cnt=2):
    """scan：扫描 cues 表英文列高频候选词（辅判定待校准专名/错词）。"""
    from collections import Counter
    rows = open(cues, encoding="utf-8").read().splitlines()
    ens = [ln.split("\t")[2] for ln in rows if len(ln.split("\t")) == 3]
    texts = " ".join(ens)
    words = re.findall(r"[A-Z][a-zA-Z'\-]+", texts)
    c = Counter(words)
    common = set("""I You We They He She It The A An And Or But Of To In On At For With From By
As Is Are Was Were Be Been Being This That These Those There Here Not No Yes So If Then Than
When Where Which Who Whom What How Why Do Does Did Done Doing Have Has Had Having Will Would
Can Could Should Shall May Might Must Okay Ok Yeah Yep Nope Uh Um Well Like Just Really
Actually Also Even Still Already Yet Only Too Very Much More Most Some Any All Both Each Every
Other Another Same Such Own Right Now One Two Three Four Five Six Seven Eight Nine Ten First
Second Third Last Next New Old Good Bad Great Big Small High Low Long Short Fast Slow Easy
Hard Free Play Player Game Mode Time Day Week Month Year Hour Minute Second People Someone
Everyone Everything Nothing Something Anything YouTube Ark Knights RA CC IS LMD E2 E1 AK OG
XP DPS VIP EZ GG""".split())
    for w, cnt in c.most_common(500):
        if w not in common and cnt >= min_cnt and len(w) > 2:
            print(f"{w}: {cnt}")



def _cmd_scan_split(paths, min_cnt=1):
    """scan-split：扫描英文/参考行里的疑似 ASR 断词（只读，不改文件）。
    根因定位用：ASR 在单词内部插空格（"reson ator"/"Water ing lace"）会让
    CONTEXT 英文锚定失效、并让谷翻产出中文残渣。输出候选（片段对 + 频次 + 样例序号），
    人工确认后按  "断词形": "规范英文"  追加进 EN_ASR_SPLIT_FIXES 即生效。"""
    if isinstance(paths, str):
        paths = [paths]
    agg = {}          # (l, r, joined) -> [cnt, [nums], auto]
    for p in paths:
        try:
            for num, line in _iter_ref_lines(p):
                for l, r, joined, auto in _scan_split_line(line):
                    rec = agg.setdefault((l, r, joined), [0, [], auto])
                    rec[0] += 1
                    if len(rec[1]) < 6:
                        rec[1].append(num)
                    rec[2] = rec[2] or auto
        except Exception as e:  # noqa: BLE001  单文件异常不影响其余
            print(f"  ⚠ 跳过 {p}: {e}")
    rows = [(k, v) for k, v in agg.items() if v[0] >= min_cnt]
    if not rows:
        print("未发现疑似 ASR 断词（参考行正常）。")
        return 0
    rows.sort(key=lambda kv: (-kv[1][2], -kv[1][0], kv[0][0]))
    auto_n = sum(1 for _, v in rows if v[2])
    print(f"疑似 ASR 断词候选 {len(rows)} 组（其中拼接即已知专名、可直接自动重组 {auto_n} 组）：")
    for (l, r, joined), (cnt, nums, auto) in rows:
        tag = "可自动重组" if auto else "需人工确认"
        print(f"  {l} + {r}  ->  {joined}   [{tag}]  x{cnt}  例序号: {nums}")
    print("\n确认后把条目追加进 EN_ASR_SPLIT_FIXES（\"断词形\": \"规范英文\"）即自动生效。")
    return 0



def _load_subfix_tsv(path):
    """加载逐 cue 子串修正表：num<TAB>old<TAB>new（old 为空串=整行覆盖，用于 ERROR 补译）。
    返回 {num: [(old, new), ...]}，同一 num 可多行（按文件顺序依次应用）。"""
    rules = {}
    for ln in _decode_any(open(path, "rb").read()).splitlines():
        ln = ln.rstrip("\r")
        parts = ln.split("\t")
        if len(parts) < 3 or not parts[0].strip().isdigit():
            continue
        rules.setdefault(parts[0].strip(), []).append((parts[1], "\t".join(parts[2:])))
    return rules



def _cmd_subfix(src, fixtsv, out, compare=None, side=None, single=False, strict=False):
    """subfix：按 num<TAB>old<TAB>new 逐 cue 修正“中文行”，其余结构（序号/时间轴/
    空行/换行/BOM/参考行）一字不动。等价于原先各项目手写的 fix.py，统一沉淀为一个子命令。
    old 为空串 -> 整行覆盖（ERROR 补译）。未命中的规则会打印 [MISS] 以便自查。
    2026-10-23：按语言定位中文行（兼容英文在上/中文在下）；拒绝空 new 与纯标记行覆盖；
    --strict 时存在 MISS / 空文案 / 越界或缺失序号则返回 1，可当门禁。
    --single：纯中文行片（每 cue 仅 1 个文本行、无参考行，如英文原声谷歌机翻单语 SRT），
              此时修正唯一文本行；默认仅处理“中文行+参考行”的双语 cue，单文本行整块跳过。"""
    rules = _load_subfix_tsv(fixtsv)
    raw = open(src, "rb").read()
    bom = raw.startswith(b"\xef\xbb\xbf")
    crlf = b"\r\n" in raw
    lines = _decode_any(raw).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out_lines = list(lines)
    applied, miss, rows, invalid = 0, [], [], []
    seen_nums = set()
    i, n = 0, len(lines)
    while i < n:
        s = lines[i].strip()
        if s.isdigit() and (i == 0 or lines[i - 1].strip() == ""):
            j = i + 1
            if j < n and "-->" in lines[j]:
                kk = j + 1
                while kk < n and lines[kk].strip() != "":
                    kk += 1
                has_text = kk - 1 >= j + 1
                multi_line = kk - 1 > j + 1      # 双语片：中文行 + 参考行
                if has_text:
                    seen_nums.add(s)
                if has_text and (multi_line or single) and s in rules:
                    texts = lines[j + 1:kk]
                    zh_pos, ref_pos = _split_cue_text(texts)
                    if zh_pos:
                        target = zh_pos[0]
                    elif single:
                        target = 0
                    else:
                        # 双语 cue 没有中文行（仅英文/参考行）：拒绝写参考行
                        i = kk
                        continue
                    zh_idx = j + 1 + target
                    old_line = lines[zh_idx]
                    new_line = old_line
                    cue_ok = True
                    for old, new in rules[s]:
                        if not new.strip():
                            invalid.append((s, old, "空 new：会删除中文行"))
                            cue_ok = False
                            continue
                        if old == "":
                            cand = new
                        elif old in new_line:
                            cand = new_line.replace(old, new)
                        else:
                            miss.append((s, old))
                            continue
                        if _MARKER_ONLY.match(old_line.strip()) and cand.strip() != old_line.strip():
                            invalid.append((s, old, "覆盖纯标记行"))
                            cue_ok = False
                            continue
                        new_line = cand
                    if cue_ok and new_line != old_line and new_line.strip():
                        out_lines[zh_idx] = new_line
                        ref = " ".join(lines[j + 1 + p] for p in ref_pos) if ref_pos else old_line
                        rows.append((s, old_line, new_line, ref))
                        applied += 1
                i = kk
                continue
        i += 1
    body = "\n".join(out_lines)
    if crlf:
        body = body.replace("\n", "\r\n")
    if os.path.abspath(out) == os.path.abspath(src):
        bak = out + ".bak"
        if not os.path.exists(bak):
            shutil.copyfile(src, bak)
            print("已备份原文件:", bak)
    with open(out, "w", encoding="utf-8", newline="") as f:
        f.write(("\ufeff" if bom else "") + body)
    total = sum(len(v) for v in rules.values())
    missing_nums = sorted(set(rules) - seen_nums, key=int)
    extra = []
    if miss:
        extra.append(f"未命中 {len(miss)}")
    if invalid:
        extra.append(f"无效 {len(invalid)}")
    if missing_nums:
        extra.append(f"缺失 cue {len(missing_nums)}")
    print(f"subfix：规则 {total} 条 / 命中 {applied} cue" + (f" / {' / '.join(extra)}" if extra else ""))
    for num, old in miss:
        print(f"  [MISS] #{num}: {old!r}")
    for num, old, why in invalid:
        print(f"  [INVALID] #{num}: {old!r}（{why}）")
    if missing_nums:
        print(f"  [MISSING CUE] {missing_nums}")
    if compare:
        with open(compare, "w", encoding="utf-8", newline="") as f:
            f.write("序号\t原文中文(机翻)\t校准后中文\t参考行\n")
            for num, o, nw, ref in rows:
                f.write(f"{num}\t{o}\t{nw}\t{ref}\n")
        print("对照表:", compare)
    if side:
        with open(side, "w", encoding="utf-8", newline="") as f:
            f.write("num\tnew_zh\n")
            for num, o, nw, ref in rows:
                f.write(f"{num}\t{nw}\n")
        print("侧车覆盖表:", side)
    print("写入:", out)
    if strict and (miss or invalid or missing_nums):
        print("STRICT FAIL：存在 MISS/无效规则/缺失 cue，未通过门禁")
        return 1
    return 0



def _check_term_hazards(mapping):
    """检测术语表的“二次命中”隐患（2026-09-10 沉淀自终末地 ja_auto 项目）。

    `_replace_report` 是**按键长降序逐条 str.replace**，不是单遍扫描。因此若短键 k
    出现在另一条目 k2 的替换结果 value2 里，k2 先替换后，k 会再次命中刚生成的文本：
      {"阿尔达西尔":"阿达希尔", "达希尔":"阿达希尔"} -> 阿达希尔 再被 达希尔 命中 -> 阿阿达希尔
      {"明日方舟末地":"明日方舟：终末地", "末地":"终末地"}   -> 终末地 再被 末地 命中 -> 终终末地
    有意为之的级联（如 金阁->金戈 再 金戈->今州）也会被列出，需人工确认。
    返回 [(短键, 长键, 长键的替换结果, 短键的替换结果), ...]。"""
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



def _cmd_terms_check(names):
    """terms-check：列出（指定）术语表的二次命中隐患，供新增对照后自查。

    两类表都支持：
      ① 无条件表（*TERMS dict）：查"短键会命中另一条目替换结果"的二次替换隐患
         （_replace_report 是长键降序 str.replace，固有陷阱）；
      ② 上下文表（*_CONTEXT / CONTEXT_MAP，list[(rx, wrong, right)]，2026-10-06 起）：
         查"错形落在自己的正确形里"的叠字风险（如 心月狐⊃月狐）——ctx 走 _ctx_replace
         哨兵已兜底，这里只做提示，不套用 ① 的长键降序模型（ctx 按列表顺序 + 参考行锚定）。"""
    tables = {n: v for n, v in TABLES.items()
              if n.endswith("TERMS") and isinstance(v, dict) and v}
    ctxtabs = {n: v for n, v in CTX_TABLES.items()
               if (n.endswith("_CONTEXT") or n == "CONTEXT_MAP")
               and isinstance(v, list) and v}
    known = set(tables) | set(ctxtabs)
    if names:
        unknown = [n for n in names if n not in known]
        if unknown:
            print("未知表:", unknown, "| 可选:", sorted(known)); return
    todo = list(names) if names else sorted(tables) + sorted(ctxtabs)
    total = 0
    for n in todo:
        is_ctx = n not in tables
        if not is_ctx:
            bad = _check_term_hazards(tables[n])
        else:
            # 上下文表：错形落在自己的正确形里 -> 叠字风险（_ctx_replace 哨兵已兜底，仍提示）
            bad = [(w, f"{w}→{r}", r, r) for _rx, w, r in ctxtabs[n]
                   if w and r and w != r and w in r]
        if bad:
            total += len(bad)
            print(f"⚠ {n}（{'上下文表' if is_ctx else '无条件表'}）: {len(bad)} 处隐患")
            for k, k2, v2, vk in bad:
                if is_ctx:
                    print(f"   错形 {k!r} 落在正确形 {v2!r} 内（哨兵保护，确认无叠字即可）")
                else:
                    print(f"   短键 {k!r} 会命中 {k2!r} 的结果 {v2!r}（{k!r}->{vk!r}）")
        else:
            print(f"✓ {n}（{'上下文表' if is_ctx else '无条件表'}）: 无二次命中隐患")
    print(f"合计 {len(todo)} 张表，{total} 处隐患")



def _cmd_lint(cues, calib_src):
    """lint：校验校准表相对 cue 表的完整性与文本质量。
    检查：重复序号 / 缺号（cue表有序号而校准表漏写）/ 越界序号 / 空文案 /
    中文文案中的意外拉丁-变音残留（白名单外的英文单词）/
    2026-09-05 沉淀自 Gloomwald's Rage 二次校准：分段书写 calib_*.tsv 时
    曾出现序号重复（127 写两遍）与外文残留（undeniable/càng/chord shape）。"""
    cue_nums = []
    for ln in open(cues, encoding="utf-8").read().splitlines()[1:]:
        m = re.match(r"(\d+)\t", ln)
        if m:
            cue_nums.append(int(m.group(1)))
    cue_set = set(cue_nums)
    orig = _load_calib_records(calib_src)
    problems = []
    seen = {}
    # 重复检测需重读原始行（_load_calib_records 已合并去重，这里按文件逐行统计）
    import glob as _glob
    if os.path.isdir(calib_src):
        files = sorted(_glob.glob(os.path.join(calib_src, "calib_*.tsv")))
    elif "*" in calib_src:
        files = sorted(_glob.glob(calib_src))
    else:
        files = [calib_src]
    for p in files:
        for ln in _decode_any(open(p, "rb").read()).splitlines():
            m = re.match(r"(\d+)\t", ln.lstrip("\ufeff"))
            if not m:
                continue
            n = m.group(1)
            seen[n] = seen.get(n, 0) + 1
    for n, cnt in sorted(seen.items(), key=lambda kv: int(kv[0])):
        if cnt > 1:
            problems.append(f"重复序号 {n}（出现 {cnt} 次）")
        if int(n) not in cue_set:
            problems.append(f"越界序号 {n}（cue 表无此条）")
    missing = sorted(cue_set - {int(k) for k in seen})
    if missing:
        problems.append(f"缺号 {len(missing)} 个: {missing[:20]}{'...' if len(missing) > 20 else ''}")
    # 文本质量：空文案 / 拉丁残留（音名 A-G、变音记号与常用保留词白名单）
    keep_words = {"music", "sus", "add", "flat", "sharp", "boss", "alex", "oreos",
                  "ooh", "oh", "ok", "pvp", "ost", "ost", "ost", "ost", "ost"}
    single_notes = set("abcdefg")          # 音名 A-G 允许
    for k in sorted(orig, key=int):
        txt = orig[k]
        if not txt.strip():
            problems.append(f"#{k} 空文案")
        for w in re.findall(r"[A-Za-zÀ-ɏ]+", txt):
            lw = w.lower()
            if lw in keep_words:
                continue
            if len(w) == 1 and lw in single_notes:
                continue
            problems.append(f"#{k} 拉丁残留: {w}（{txt[:24]}）")
    if problems:
        print(f"LINT {len(problems)} 处问题:")
        for p in problems:
            print(" -", p)
    else:
        print(f"LINT OK：{len(cue_nums)} cue 全覆盖，无重复/越界/空文案/拉丁残留")

