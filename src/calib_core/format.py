# -*- coding: utf-8 -*-
# @version 2.8.0
"""行宽、重排、口播风格与 cue 稳定化

源：subtitle_calib_merged.py L12310-L12747 @ 97d7d463（2026-10-24 冻结快照）
"""
import io
import os
import re
import shutil
import sys
import unicodedata
from .srt import _detect_layout, _iter_cue_lines
from .text import _decode_any



# =============================================================
# 行宽体检（length 子命令，2026-09-14 新增）
#
#   动机：verify 只断言「结构未变」（cue 数/序号/时间轴/参考行/CRLF/BOM），
#   不查行宽；而逐 cue 整行重写（subfix 空 old 覆盖）最容易把中文行写长。
#   本子命令按 A 版「排版线」既有判据把关，两版口径一致：
#   东亚 W/F/A 宽字符计 1.0、半角计 0.5 ⇒ 「32 汉字」等价于「64 英文字符」。
#
#   默认只统计**内容行**（每个 cue 除最后一行参考行外的文本行），参考行
#   只做提示（双语片源的参考行本来就常超宽，混在一起会很吵）；
#   `--all` 把参考行一并计入判定与门禁。
#   超限退出码 1，可直接在流水线里当门禁用。
#   用法：length <a.srt> [b.srt ...] [--all]
# =============================================================

MAX_LINE_ZH = 32            # 内容行上限（汉字当量）

MAX_LINE_EN = 64            # 与 32 汉字等价（半角计 0.5）

MAX_LINE_WIDTH = 32.0


# =============================================================
# 口播风格表（flow 子命令，2026-10-01 沉淀自鸣潮 3.7 日语初见片第三轮精修）
#   「熟肉」要读起来像中国主播在说话，而不是翻译腔。这里只收**确定性高**的
#   书面腔->口语替换；语境敏感的词（非常/关于/并且…）不进表，交给逐 cue 人工。
#   ⚠ 与术语表一样按键长降序替换（长键在前），防短键吃掉长键前缀。
# =============================================================
STYLE_MAP = {
    "非常抱歉": "实在抱歉",     # 长键优先，防被 "抱歉" 类短键截断
    "确实如此": "是这样",
    "显而易见": "一眼就看得出",
    "即便如此": "就算这样",
    "请多关照": "请多指教",
    "我明白了": "原来如此",
    "不得不": "只能",
    "因此": "所以", "然而": "不过", "并且": "而且", "由于": "因为",
    "此外": "另外", "是否": "是不是", "无法": "没法", "立刻": "马上",
    "十分": "挺", "些许": "有点",
    # —— 2026-10-01 韩服 3.7 心月狐片（여우별 정주행）第三轮口播化实测补充 ——
    # ⚠ 长键必须先于裸键：原句常是「依然**是**…」，裸键替换会产出「还是是」
    "依然是": "还是", "仍然是": "还是", "依旧是": "还是",
    "依然": "还是", "仍然": "还是", "仍旧": "还是",
    "必须": "得", "尚未": "还没", "并非": "不是",
    "实际上": "其实", "这件事": "这事", "的事情": "的事",
}

# 整行「语气填充词」归一表（2026-10-01 第三轮口播化沉淀）。
#   病灶：韩语原声片的谷翻会把韩语语气词/填充词**直译成中文实词**，单独成行时
#   完全是错字观感——最常见的是 어/아（语气词）→「语言」、예→「示例」、
#   나는/나→「I」。这类是**整行**级别的误译，不是词级，故 STYLE_MAP 的
#   子串替换救不了，须整行精确匹配。只在 flow --fix-style 时应用。
#   戒律：只收「整行 = 纯语气词」且中文原样读不通的；有实义的（如"有的"）不收，
#         留人工判断，避免误伤。
FILLER_MAP = {
    "语言": "呃",
    "示例": "嗯",
    "I": "我",
    # ⚠ 整行**连接词**（然而/但是/以及/所以…）**不要**进本表：换成另一个连接词
    #   仍然过不了「行首悬挂连词」这一关，属于自欺。那类走 LEAD_CONJ 体检 +
    #   人工改写成自足短语（"不过啊——" / "哇！" / "于是，"），见 _cmd_flow 说明。
}

# 中文行**行首悬挂标点**：机翻把日语的句中顿号/句号一起搬到了行首，
# 单独成行时看着像错字（如 "。以前也经常被人这么说"）。flow 默认清掉。
# 不含 ！？：行首的叹号/问号承载语气，清了会掉情绪，保留。
LEAD_PUNCT = "。，、；："

# 中文行**行首悬挂连词**（2026-10-01 第三轮「跨 cue 连贯」新增）。
#   病灶：机翻按韩语/日语句读切 cue，把连接词整个留到下一 cue 开头；单看一行像断句，
#   连读时更糟——连接词与本句被 cue 边界劈开（"否定词/主语跨 cue" 的同源问题）。
#   分两级：① 整行**就是**一个连接词（最刺眼，必须并入上一 cue 或改写成自足短语）；
#           ② 行首连词且**上一 cue 中文行已收句**（。！？），说明连词接不上。
#   与时间轴无关，flow 只体检不自动改（改法须人工：并入上一 cue 或重写成自足句）。
LEAD_CONJ = ("然而", "但是", "不过", "因此", "所以", "于是", "而且", "并且",
             "以及", "加之", "另外", "此外", "接着", "然后", "那么", "既然",
             "因为", "虽然", "即使", "即便", "尽管", "还有", "更重要的是")

# 上一 cue 收句判定用：这些标点说明上一行已经说完，本行再起连词就是"接不上"。
_SENT_END = ("。", "！", "？", "……", "！", "？")



def char_width(ch):
    """东亚宽字符（W/F/A）计 1.0，其余（半角）计 0.5。"""
    return 1.0 if unicodedata.east_asian_width(ch) in ("W", "F", "A") else 0.5



def line_width(s):
    """整行显示宽度（以汉字为单位）。"""
    return sum(char_width(c) for c in s)



def is_line_too_long(s, limit=MAX_LINE_WIDTH):
    return line_width(s) > limit



def _cmd_length(paths, show_all=False):
    """length：内容行行宽体检（>MAX_LINE_ZH 汉字当量即超限，退出码 1）。"""
    bad_total = 0
    for path in paths:
        if not os.path.exists(path):
            print(f"[跳过] 文件不存在: {path}")
            continue
        bad, ref_bad, cues = [], [], 0
        widest, ref_widest = (0.0, ""), (0.0, "")
        for num, zh_lines, ref in _iter_cue_lines(path):
            cues += 1
            for t in zh_lines:
                L = line_width(t)
                if L > widest[0]:
                    widest = (L, t)
                if L > MAX_LINE_WIDTH:
                    bad.append((num, L, t))
            if ref is not None:
                L = line_width(ref)
                if L > ref_widest[0]:
                    ref_widest = (L, ref)
                if L > MAX_LINE_WIDTH:
                    ref_bad.append((num, L, ref))
        print(f"{path}: {cues} cues")
        if bad:
            print(f"  内容行超限 {len(bad)} 处（>{MAX_LINE_ZH} 汉字当量）:")
            for num, L, t in bad[:20]:
                print(f"    #{num} {L:.1f} {t}")
            if len(bad) > 20:
                print(f"    ... 另有 {len(bad) - 20} 处")
        else:
            print("  内容行超限 0 处")
        print(f"  最宽内容行 {widest[0]:.1f}: {widest[1]}")
        if ref_bad:
            tag = "" if show_all else "（提示，不计入门禁；--all 才纳入）"
            print(f"  参考行超限 {len(ref_bad)} 处{tag}:")
            for num, L, t in ref_bad[:10]:
                print(f"    #{num} {L:.1f} {t}")
        bad_total += len(bad) + (len(ref_bad) if show_all else 0)
    if bad_total:
        print(f"LENGTH FAIL：{bad_total} 处超限")
        return 1
    print(f"LENGTH OK：全部在 {MAX_LINE_ZH} 汉字当量内")
    return 0



# ── rewrap：超宽行按标点拆行（2026-10-11 沉淀，替代旧版 --layout）──────────
# 断点规则：仅句读标点后可断；吸附后续收尾引号/句读防行首标点；引号括号内（depth>0）不断；
# 英文缩写（Mr./Dr. 等）与"标点+数字"（1.6/2.0）不断；无标点长串按宽度硬切兜底。
# 注：ASCII 撇号/右侧弯引号（it's、That's）不入引号对——否则 depth 卡死、断点全废、退化硬切
_REWRAP_OPENERS = "《「『【（(\"“‘"

_REWRAP_CLOSERS = "》」』】）)\"”’"

_REWRAP_ZH_BREAKS = "。！？；…、，"

_REWRAP_EN_BREAKS = ".!?:;,"

_REWRAP_ABSORB = "！？…。、，》」』】）)\"'”’"

_REWRAP_ABBREV = re.compile(r"(?i)\b(mr|mrs|ms|dr|st|jr|sr|vs|etc|prof|capt|sgt|col|lt|gen|approx|no)\.$|\b[A-Za-z]\.$")



def _rewrap_segments(line, respect_depth=True):
    """按可断标点把一行切成段；段顺序拼接＝原行（仅断点处切开）。"""
    segs, start, depth, n = [], 0, 0, len(line)
    i = 0
    while i < n:
        c = line[i]
        if c in _REWRAP_OPENERS:
            depth += 1
        elif c in _REWRAP_CLOSERS:
            depth = max(0, depth - 1)
        brk = False
        if not respect_depth or depth == 0:
            if c in _REWRAP_ZH_BREAKS:
                brk = True
            elif c in _REWRAP_EN_BREAKS and i + 1 < n and line[i + 1] in " \t":
                if c != "." or not _REWRAP_ABBREV.search(line[:i + 1]):
                    brk = True
        if brk:
            j = i + 1
            while j < n and line[j] in _REWRAP_ABSORB:
                j += 1
            if j < n and line[j].isdigit():
                i += 1          # 1.6 / 2.0 等版本号、小数：该标点不设断点
                continue
            segs.append(line[start:j])
            start = j
            i = j
            continue
        i += 1
    if start < n:
        segs.append(line[start:])
    return segs



def _rewrap_line(line, width):
    """超宽行拆为多行（贪心装段，续行去首空白）；未超宽原样返回单行。"""
    if line_width(line) <= width:
        return [line]
    segs = _rewrap_segments(line)
    if len(segs) == 1:
        segs = _rewrap_segments(line, respect_depth=False)
    pieces = []
    for s in segs:
        if line_width(s) <= width:
            pieces.append(s)
            continue
        cur = ""
        for ch in s:            # 无标点长串兜底：按宽度硬切
            if cur and line_width(cur) + char_width(ch) > width:
                pieces.append(cur)
                cur = ch
            else:
                cur += ch
        if cur:
            pieces.append(cur)
    out, cur, cur_w = [], "", 0.0
    for s in pieces:
        if cur and cur_w + line_width(s) > width:
            out.append(cur.rstrip())
            cur = s.lstrip(" \t\u3000")     # 仅换行起点去首空白；行内合并保留原空格
            cur_w = line_width(cur)
        else:
            cur += s
            cur_w += line_width(s)
    if cur.strip():
        out.append(cur.rstrip())
    return out or [line]



def _cmd_rewrap(src, out=None, width=None, report=None):
    """rewrap：超宽文本行在标点处于 cue 内拆行。序号/时间轴/空行/换行(CRLF)/BOM 原样，
    内容不增删（仅断点处空白并入行界）。默认宽度 = MAX_LINE_WIDTH 汉字当量（半角 0.5）。
    内容行与参考行一并处理；不带 --out 仅体检统计。"""
    limit = MAX_LINE_WIDTH if width is None else float(width)
    raw = open(src, "rb").read()
    bom = raw.startswith(b"\xef\xbb\xbf")
    crlf = b"\r\n" in raw
    lines = _decode_any(raw).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out_lines, rows, num, cues = [], [], None, 0
    i, n = 0, len(lines)
    while i < n:
        s = lines[i].strip()
        if (s.isdigit() and (i == 0 or lines[i - 1].strip() == "")
                and i + 1 < n and "-->" in lines[i + 1]):
            num, cues = s, cues + 1
            out_lines.extend(lines[i:i + 2])
            j = i + 2
            while j < n and lines[j].strip() != "":
                ln = lines[j]
                new = _rewrap_line(ln, limit)
                # 内容保全校验（去空白比对）：断点处空白并入行界属预期，非空白内容必须一致
                if len(new) > 1 and re.sub(r"\s+", "", "".join(new)) == re.sub(r"\s+", "", ln):
                    rows.append((num, ln, new))
                    out_lines.extend(new)
                else:
                    out_lines.append(ln)
                j += 1
            i = j
        else:
            out_lines.append(lines[i])
            i += 1
    print(f"[{src}] cues={cues} 拆行 {len(rows)} 行（宽度上限 {limit:g} 汉字当量）")
    for num, ln, new in rows:
        print(f"  #{num} {line_width(ln):.1f} -> {' / '.join(f'{line_width(x):.1f}' for x in new)}")
    if out:
        body = "\n".join(out_lines)
        if crlf:
            body = body.replace("\n", "\r\n")
        with open(out, "w", encoding="utf-8", newline="") as f:
            f.write(("\ufeff" if bom else "") + body)
        print(f"已写入：{out}")
    if report:
        with open(report, "w", encoding="utf-8") as f:
            f.write("# 超宽行拆行对照\n\n序号 | 原行 | 拆行后\n--- | --- | ---\n")
            for num, ln, new in rows:
                f.write(f"`{num}` | {ln} | {'<br>'.join(new)}\n")
        print(f"报告：{report}")



def _cmd_flow(src, out=None, fix_style=False):
    """flow：口播风格 + 跨 cue 连贯体检（可顺带修复）。

    动机（2026-10-01 鸣潮 3.7 日语初见片第三轮精修）：术语对了、时间轴对了，
    熟肉仍然可能"不像人话"——两个典型病灶：
      ① **行首悬挂标点**：机翻把日语句中顿号/句号搬到行首（"。以前也经常…"、
         "、为什么…"），跨 cue 连读时特别刺眼；
      ② **书面腔**：因此/然而/并且/是否/无法…，主播口播不会这么说话。
    本子命令：不带 --out 只体检（列清单，退出码非 0 表示有问题）；
    带 --out 写出成品，默认只清行首悬挂标点，加 --fix-style 才套 STYLE_MAP。
    ⚠ 只动中文行的**标点/虚词**，绝不改术语、绝不改序号/时间轴/参考行。
    """
    raw = open(src, "rb").read()
    bom = raw.startswith(b"\xef\xbb\xbf")
    crlf = b"\r\n" in raw
    norm = _decode_any(raw).replace("\r\n", "\n").replace("\r", "\n")
    lines = norm.split("\n")
    layout = _detect_layout(lines)
    spans, i, n = [], 0, len(lines)
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
                        # 单语片：唯一文本行即目标（区间含该行），纳入体检/修复。
                        spans.append((j + 1, kk, s, True))
                    else:
                        spans.append((j + 1, kk - 1, s, len(texts) >= 2))
                i = kk
                continue
        i += 1
    keys = sorted(STYLE_MAP, key=len, reverse=True)
    lead, longl, styled, filler, conj, conj2 = [], [], [], [], [], []
    prev_zh = ""
    for st, ed, num, has_zh in spans:
        if not has_zh:
            continue
        zh = lines[st]
        if zh[:1] in LEAD_PUNCT:
            lead.append((num, zh))
        if is_line_too_long(zh):
            longl.append((num, round(line_width(zh), 1), zh))
        # 悬挂连词：① 整行就是连接词；② 行首连词但上一 cue 已收句
        core = zh.strip().lstrip(">").strip()
        if core in LEAD_CONJ:
            conj.append((num, core, zh))
        elif prev_zh.endswith(_SENT_END):
            for c in sorted(LEAD_CONJ, key=len, reverse=True):
                if core.startswith(c):
                    conj2.append((num, c, zh))
                    break
        prev_zh = zh.rstrip()
        if zh.strip() in FILLER_MAP:
            filler.append((num, zh.strip(), FILLER_MAP[zh.strip()]))
            continue
        for k in keys:
            if k in zh:
                styled.append((num, k, zh))
                break
    print(f"{os.path.basename(src)}: {len(spans)} cues")
    print(f"  行首悬挂标点 {len(lead)} 处" + ("" if lead else "（干净）"))
    for num, t in lead[:8]:
        print(f"    #{num} {t[:40]}")
    print(f"  内容行超宽 {len(longl)} 处" + ("" if longl else "（干净）"))
    for num, L, t in longl[:8]:
        print(f"    #{num} {L:.1f} {t[:40]}")
    print(f"  语气填充词 {len(filler)} 处" + ("" if filler else "（干净）"))
    for num, a, b in filler[:8]:
        print(f"    #{num} [{a}] -> {b}")
    print(f"  书面腔命中 {len(styled)} 处" + ("" if styled else "（干净）"))
    for num, k, t in styled[:8]:
        print(f"    #{num} [{k}] {t[:40]}")
    print(f"  行首悬挂连词 {len(conj)} 处（整行=连词）" + ("" if conj else "（干净）"))
    for num, c, t in conj[:8]:
        print(f"    #{num} [{c}] {t[:40]}")
    print(f"  行首连词接不上 {len(conj2)} 处（上一 cue 已收句）" + ("" if conj2 else "（干净）"))
    for num, c, t in conj2[:8]:
        print(f"    #{num} [{c}] {t[:40]}")
    if not out:
        bad = len(lead) + len(longl) + len(conj)
        if bad:
            print(f"FLOW：{bad} 处待修（加 --out 输出成品；--fix-style 连书面腔一起改；"
                  f"悬挂连词须人工并入上一 cue 或改写成自足句）")
            return 1
        print("FLOW OK：口播风格与连贯性无待修项")
        return 0
    for st, ed, num, has_zh in spans:
        if not has_zh:
            continue
        zh = lines[st]
        nz = zh.lstrip(LEAD_PUNCT)
        if not nz.strip():
            nz = "……"                      # 整行只有标点：留个省略号，别留空行
        if fix_style:
            if nz.strip() in FILLER_MAP:    # 整行语气填充词优先（词级替换救不了）
                nz = FILLER_MAP[nz.strip()]
            else:
                for k in keys:
                    nz = nz.replace(k, STYLE_MAP[k])
        if nz != zh and not is_line_too_long(nz):
            lines[st] = nz
    body = "\n".join(lines)
    if crlf:
        body = body.replace("\n", "\r\n")
    with open(out, "w", encoding="utf-8", newline="") as f:
        f.write(("\ufeff" if bom else "") + body)
    print(f"已修复并写入: {out}")
    return 0



# =============================================================
# SRT cue 级稳定化（stabilize 子命令，2026-10-12 新增）
#
#   对标 FineSub（downloads/finesub v0.5.1）ASR 稳定化层的 SRT 移植：
#   丢弃候选 / 碎片合并 / 超长 cue 拆分。库实现与阈值出处见
#   src\calib_stabilize.py 与 finesub_stabilize_gap_analysis.md。
#
#   与校准铁律的关系：稳定化是校准**之前**的结构层（FineSub 管线里排在
#   raw SRT 之前），本来就负责时间轴；校准（REPLACE/Agent）仍严守
#   "只改文字不动时间轴"。两者不冲突。
#
#   产品口径：不带 --out 只出报告（退出码 1＝有候选）；带 --out 才应用
#   显式开启的操作（--drop/--merge/--split 默认开，--no-* 可关）。
# =============================================================
def _cmd_stabilize(src, out=None, report=None, drop=True, merge=True, split=True):
    """stabilize：SRT cue 级稳定化（幻觉丢弃 / 碎片合并 / 超长拆分）。"""
    here = os.path.dirname(os.path.abspath(__file__))
    # 兼容三种布局：包内 src/calib_core、根 monolith、data/tmp 下的候选
    for _base in (here, os.path.dirname(here), os.path.dirname(os.path.dirname(here))):
        for _p in (_base, os.path.join(_base, "src")):
            if _p and _p not in sys.path:
                sys.path.insert(0, _p)
    try:
        import calib_stabilize as _st
    except ImportError as e:
        print(f"[错误] 无法导入 src\\calib_stabilize.py：{e}")
        return 2
    return _st.run(src, out=out, report=report, drop=drop, merge=merge, split=split)

