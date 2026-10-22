# -*- coding: utf-8 -*-
# @version 2.5.4
"""SRT cue 级稳定化库（stabilize 子命令的实现，2026-10-12 新增）。

============================================================
定位
============================================================
对标 FineSub（downloads/finesub v0.5.1）的 ASR 稳定化层，把其中
**文本+时长判据**原值移植到本管线的 SRT cue 级；依赖词级置信/能量/VAD
的判据（DP 全局选点、能量腿、第二模型 veto）不移植——SRT 只有 cue 级
坐标。查漏报告见仓库根目录 `finesub_stabilize_gap_analysis.md`。

本管线的位置：ASR/谷翻产出 SRT → **stabilize（本模块）** → 术语校准
（subtitle_calib_merged.py REPLACE / calib_ai_agent）→ 交付。
即稳定化是校准**之前**的结构层，与校准的"只改文字不动时间轴"铁律
不冲突——它本来就负责时间轴。

产品口径（继承 flow / align-audit / missing 子命令）：
  · **不带 --out 只出报告**（三类候选全部列出，退出码 1＝有候选）；
  · 带 --out 才落盘，且只应用显式开启的操作（--drop/--merge/--split，
    可用 --no-drop/--no-merge/--no-split 关掉某一类）；
  · 序号重排、时间轴重算都写进报告的前后对照表。

阈值全部来自 FineSub 并有出处注释；**新短语进表必须有语料证据**，
禁止凭感觉加（先验赔率不是原理，见 gap 报告 §8）。
============================================================
"""

from __future__ import annotations

import os
import re
import sys
import unicodedata


# =============================================================
# 阈值常量（FineSub 原值，附出处）
# =============================================================

# ---- 套话幽灵（FineSub stabilization.py CLOSING_GHOST_*，2026-08-05/08-30）----
# 日文族：整段就是套话且被压进物理不可能的时长 → 语速腿可丢弃。
CLOSING_GHOST_PHRASES_JA = ("おわり", "それではまた", "ありがとうございました")
# 英文族：语料实产（P1 环境音语料 369 行 8 种文本）统计得出；
# "you." 故意不列——三字符会命中真实代词（已知缺口，补它需要
# 「相接半句合并后再判」规则，不是加个字符串）。
CLOSING_GHOST_PHRASES_EN = ("thankyou", "thank", "imsorry", "thanksforwatching",
                            "thankyouforwatching", "pleasesubscribe")
# 只有日文族允许纯语速腿丢弃；英文族失效形态是**拉长**（漏网
# "Thank you." 10 字符摊 11.6 秒），且 20 字/秒对拉丁文是正常快语速
# （≈200 wpm）不是物理不可能 → 英文族一律证据门控（观测，不自动丢）。
CLOSING_GHOST_RATE_GATED_PHRASES = CLOSING_GHOST_PHRASES_JA
CLOSING_GHOST_MAX_EXTRA_CHARS = 2          # 整段归一化后 ≤ 短语长度+2
CLOSING_GHOST_MIN_CHARS_PER_SEC = 20.0     # 语速幽灵线：duration < 短语字数/20

# ---- 复读幻觉（FineSub text.py REPEAT_* / GROUP_REPEAT_*）----
GROUP_REPEAT_MIN_COUNT = 4                 # 成组 tandem 复读最少轮数
GROUP_REPEAT_MIN_UNITS = 32.0              # 复读总跨度 ≥ 32 加权单位
REPEAT_DETECT_MORE_THAN = 7                # 精确单元复读 >7 次（塌缩保留 5）
REPEAT_KEEP_RUN = 5
REPEAT_MATCH_MAX_CHARS = 100               # motif 长度上界（防 O(n·m) 爆炸）
SPACE_DELIMITED_WORD_UNITS = 3.0           # 空格分词脚本（拉丁等）的词权
NON_SPACE_SCRIPT_CHAR_UNITS = 1.0          # 非空格脚本（CJK/假名/谚文）的字权
DIGIT_RUN_UNITS = 1.0

# ---- 语言切换观测（FineSub LANG_SWITCH_*，仅打标不丢）----
LANG_SWITCH_RUN_MAX_LATIN_RATIO = 0.3      # 全文件拉丁占比低于它 = CJK 主导素材
LANG_SWITCH_SEGMENT_MIN_LATIN_RATIO = 0.7  # 段内拉丁占比 ≥ 0.7
LANG_SWITCH_SEGMENT_MIN_LETTERS = 8        # 段字母数 ≥ 8

# ---- 合并门槛（FineSub llm/prompt_constants.py，单一事实源原值）----
HARD_MERGE_CHARS = 20          # 加权字数硬门槛，越过原则上必须拆回
HARD_MERGE_SECONDS = 4.0       # 跨度硬门槛（秒）
ABSOLUTE_MERGE_CHARS = 36      # 绝对门槛，任何情况都必须拒绝合并
ABSOLUTE_MERGE_SECONDS = 7.0   # 绝对门槛（秒）
FILLER_MAX_CHARS = 3           # 三明治中间纯语气碎片字数上限
SANDWICH_MAX_CHARS = 16        # 三明治合并后字数上限
SANDWICH_MAX_SECONDS = 4.0     # 三明治合计时长上限
# 合并邻接 gap 上限：FineSub DP 的 G(g) 在 g=1.5s 时近乎强制切分，
# SRT 无词级停顿可用，取 1.0s 作为"续句"代理（保守侧）。
MERGE_MAX_GAP_SECONDS = 1.0

# ---- 拆分墙（FineSub segmentation.py SplitParams 的 U 形合格区）----
CHARS_IDEAL_HI = 20.0          # 加权字数理想区上墙
DUR_IDEAL_HI = 4.5             # 时长理想区上墙（秒）
CHARS_OK_HI = 36.0             # 加权字数合格区上墙（拆分触发线）
DUR_OK_HI = 8.0                # 时长合格区上墙（拆分触发线）
DUR_OK_LO = 0.6                # 时长合格区下墙（拆出的碎片不得短于此）
CHARS_OK_LO = 3.0              # 加权字数合格区下墙

# ---- 纯填充短行观测（FineSub「高度疑似语气填充词」的 SRT 层保守子集）----
# FineSub 原判据要 low_conf（ASR 信号），SRT 没有 → 只收「整行 = 纯语气
# token 且时长 <0.5s」的形态，且**只观测不自动丢**（口癖可能是内容）。
FILLER_TOKENS = frozenset({"呃", "嗯", "啊", "哦", "欸", "诶", "唉", "哎",
                           "噢", "喔", "嗯嗯", "啊啊"})
FILLER_MAX_SECONDS = 0.5

# ---- 说话人标记（本管线提示词契约：行首 ">>" 必须保留）----
SPEAKER_PREFIX = ">>"

# 多编码读取（与 subtitle_calib_merged.py 的 TEXT_ENCODINGS 一致）
TEXT_ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "big5", "shift_jis", "latin-1")


# =============================================================
# 文本度量（FineSub 原值移植）
# =============================================================

def weighted_char_count(text: str) -> float:
    """共享加权显示长度：拉丁字母/数字/标点/空格 = 0.5，其余可见字符 = 1.0，
    组合符与不可见控制/格式字符 = 0。（FineSub subtitles/metrics.py 原值）"""
    total = 0.0
    for char in text or "":
        category = unicodedata.category(char)
        if category.startswith("M") or category in {"Cc", "Cf", "Cs", "Cn"}:
            continue
        if (char.isspace()
                or category.startswith(("N", "P"))
                or (category.startswith("L") and "LATIN" in unicodedata.name(char, ""))):
            total += 0.5
        else:
            total += 1.0
    return total


def normalized_compact(text: str) -> str:
    """NFKC + casefold，去标点与空白——幻觉短语匹配 / 复读比较的共享比较键。
    （FineSub text.py 原值）"""
    return "".join(
        char.casefold()
        for char in unicodedata.normalize("NFKC", str(text))
        if not unicodedata.category(char).startswith("P") and not char.isspace()
    )


# 标点六分类（FineSub text.py punct_class 原值）：切分与胶合共用的单一事实源。
SENTENCE_END_PUNCT = frozenset("。．｡.！!？?…‥‼⁇⁈⁉")
CLAUSE_PUNCT = frozenset("、，,､；;：:")


def punct_class(ch: str) -> str:
    """sentence（句末，其后最强断点）/ clause（句中顿号类）/ opening（向右胶合）/
    closing（向左胶合）/ other（其余标点）/ none。"""
    if not ch:
        return "none"
    if ch in SENTENCE_END_PUNCT:
        return "sentence"
    if ch in CLAUSE_PUNCT:
        return "clause"
    category = unicodedata.category(ch)
    if category in ("Ps", "Pi"):
        return "opening"
    if category in ("Pe", "Pf"):
        return "closing"
    if category.startswith("P"):
        return "other"
    return "none"


# ---- 复读检测（FineSub text.py _text_unit_symbols / detect_repeating_group_cycle）----

INTERNAL_WORD_JOINERS = {"'", "’", "-", "·"}
NON_SPACE_DELIMITED_SCRIPT_MARKERS = (
    "CJK UNIFIED IDEOGRAPH", "HIRAGANA", "KATAKANA", "HANGUL", "THAI", "LAO",
    "KHMER", "MYANMAR",
)
SPACE_DELIMITED_SCRIPT_MARKERS = (
    "LATIN", "CYRILLIC", "GREEK", "ARABIC", "HEBREW", "DEVANAGARI", "BENGALI",
    "GURMUKH",
)


def _unicode_name(ch: str) -> str:
    try:
        return unicodedata.name(ch)
    except ValueError:
        return ""


def _is_non_space_script_letter(ch: str) -> bool:
    if not ch or not ch.isalpha():
        return False
    name = _unicode_name(ch)
    return any(marker in name for marker in NON_SPACE_DELIMITED_SCRIPT_MARKERS)


def _is_space_script_letter(ch: str) -> bool:
    if not ch or not ch.isalpha():
        return False
    if _is_non_space_script_letter(ch):
        return False
    name = _unicode_name(ch)
    return any(marker in name for marker in SPACE_DELIMITED_SCRIPT_MARKERS)


def _is_internal_joiner(text: str, index: int) -> bool:
    if index <= 0 or index >= len(text) - 1:
        return False
    ch = text[index]
    if ch not in INTERNAL_WORD_JOINERS:
        return False
    prev, nxt = text[index - 1], text[index + 1]
    return (prev.isalpha() or prev.isdigit()) and (nxt.isalpha() or nxt.isdigit())


def _text_unit_symbols(text: str):
    """归一化比较符号序列，带共享词单元权重（FineSub text.py 原值）。"""
    text = unicodedata.normalize("NFC", text or "")
    symbols = []
    run_chars = []
    run_has_space_script_letter = False
    run_has_digit = False

    def flush():
        nonlocal run_chars, run_has_space_script_letter, run_has_digit
        if run_has_space_script_letter:
            symbols.append(("".join(run_chars).casefold(), SPACE_DELIMITED_WORD_UNITS))
        elif run_has_digit:
            symbols.append(("".join(run_chars), DIGIT_RUN_UNITS))
        run_chars = []
        run_has_space_script_letter = False
        run_has_digit = False

    for index, ch in enumerate(text):
        if _is_space_script_letter(ch):
            run_chars.append(ch)
            run_has_space_script_letter = True
            continue
        if ch.isdigit():
            run_chars.append(ch)
            run_has_digit = True
            continue
        if unicodedata.category(ch).startswith("M"):
            if run_chars:
                run_chars.append(ch)
            continue
        if _is_internal_joiner(text, index):
            if run_chars:
                run_chars.append(ch)
            continue
        flush()
        if _is_non_space_script_letter(ch):
            symbols.append((ch.casefold(), NON_SPACE_SCRIPT_CHAR_UNITS))
        elif ch.isalpha():
            symbols.append((ch.casefold(), 1.0))
    flush()
    return symbols


def detect_repeating_group_cycle(text: str, *, min_repeats: int = GROUP_REPEAT_MIN_COUNT,
                                 min_span_units: float = GROUP_REPEAT_MIN_UNITS):
    """描述第一个同时越过两个阈值的精确局部 tandem 复读；没有则 None。
    （FineSub text.py detect_repeating_group_cycle 原值）"""
    unit_symbols = _text_unit_symbols(text)
    required_repeats = max(2, int(min_repeats))
    required_units = max(0.0, float(min_span_units))
    symbol_count = len(unit_symbols)
    if symbol_count < required_repeats:
        return None
    symbols = [symbol for symbol, _units in unit_symbols]
    unit_prefix = [0.0]
    for _symbol, units in unit_symbols:
        unit_prefix.append(unit_prefix[-1] + units)
    char_prefix = [0]
    for symbol in symbols:
        char_prefix.append(char_prefix[-1] + len(symbol))
    max_motif_len = min(symbol_count // required_repeats, REPEAT_MATCH_MAX_CHARS)
    for motif_len in range(1, max_motif_len + 1):
        max_start = symbol_count - required_repeats * motif_len
        for start in range(max_start + 1):
            motif_chars = char_prefix[start + motif_len] - char_prefix[start]
            if motif_chars > REPEAT_MATCH_MAX_CHARS:
                continue
            motif = symbols[start:start + motif_len]
            repeats = 1
            cursor = start + motif_len
            while (cursor + motif_len <= symbol_count
                   and symbols[cursor:cursor + motif_len] == motif):
                repeats += 1
                cursor += motif_len
            if repeats < required_repeats:
                continue
            span_units = unit_prefix[cursor] - unit_prefix[start]
            if span_units < required_units:
                continue
            motif_units = unit_prefix[start + motif_len] - unit_prefix[start]
            motif_text = " ".join(motif)
            return ("repeating_group_cycle count=%d motif_units=%g span_units=%g motif='%s'"
                    % (repeats, motif_units, span_units, motif_text[:40]))
    return None


def detect_exact_repeat_over(text: str, detect_more_than: int = REPEAT_DETECT_MORE_THAN):
    """整段是否是同一单元的精确复读且超过 detect_more_than 次（FineSub
    _collapse_exact_repeating_unit 的判别部分；cue 级不自动压缩，只观测）。
    返回 (单元, 次数) 或 None。"""
    symbols = [s for s, _u in _text_unit_symbols(text)]
    if not symbols:
        return None
    # 整段单符号复读（哈哈× / 啊×）
    first = symbols[0]
    run = 0
    for s in symbols:
        if s == first:
            run += 1
        else:
            break
    if run == len(symbols) and run > detect_more_than:
        return first, run
    # 多符号 motif 整段 tandem（ABC ABC ABC …）
    for motif_len in range(1, len(symbols) // 2 + 1):
        if len(symbols) % motif_len:
            continue
        motif = symbols[:motif_len]
        times = len(symbols) // motif_len
        if times > detect_more_than and symbols == motif * times:
            return " ".join(motif), times
    return None


# =============================================================
# SRT 模型（块级编辑：非 cue 行原样保留）
# =============================================================

class Cue:
    """一个 SRT 条目。lines 含全部文本行（bi 版式末行是参考行）。"""

    __slots__ = ("num", "start_ms", "end_ms", "lines", "block_start", "block_end")

    def __init__(self, num, start_ms, end_ms, lines, block_start, block_end):
        self.num = num                  # 原始序号字符串
        self.start_ms = start_ms
        self.end_ms = end_ms
        self.lines = lines              # list[str]
        self.block_start = block_start  # 在 lines 总表里的起始下标（序号行）
        self.block_end = block_end      # 结束下标（不含，即首个非文本行/空行）

    @property
    def duration_sec(self):
        return max(0, self.end_ms - self.start_ms) / 1000.0


def _decode_any(raw: bytes) -> str:
    for enc in TEXT_ENCODINGS:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


_TIME_RE = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})")


def _parse_time(token: str):
    m = _TIME_RE.search(token or "")
    if not m:
        return None
    h, mi, s, ms = m.groups()
    return ((int(h) * 60 + int(mi)) * 60 + int(s)) * 1000 + int(ms.ljust(3, "0"))


def _fmt_time(ms: int) -> str:
    ms = max(0, int(ms))
    h, rem = divmod(ms, 3600000)
    mi, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return "%02d:%02d:%02d,%03d" % (h, mi, s, ms)


def parse_srt(lines):
    """解析已按 \\n 切行的 SRT → cues。

    空 cue（只有序号+时间轴、无文本行）也进列表（lines=[]）——它是结构性
    垃圾，由丢弃阶段处理；若在此跳过，它的行会原样留在输出里占一个序号，
    序号表反而断裂。非 cue 行原样留在调用方的 lines 表里，本函数只记录
    每个 cue 占用的行区间 [block_start, block_end)。
    """
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
                texts = lines[j + 1:kk]
                start = _parse_time(lines[j])
                end = _parse_time(lines[j].split("-->")[-1])
                cues.append(Cue(s, start or 0, end or 0, list(texts), i, kk))
                i = kk
                continue
        i += 1
    return cues


def _script_counts(s):
    han = hangul = kana = lat = 0
    for ch in s:
        o = ord(ch)
        if 0x4E00 <= o <= 0x9FFF:
            han += 1
        elif 0xAC00 <= o <= 0xD7AF:
            hangul += 1
        elif 0x3040 <= o <= 0x30FF:
            kana += 1
        elif ("A" <= ch <= "Z") or ("a" <= ch <= "z"):
            lat += 1
    return han, hangul, kana, lat


def _is_chinese_dominant(s):
    han, hangul, kana, lat = _script_counts(s)
    return han >= 1 and han > hangul + kana and han >= lat


def detect_layout(cues):
    """'mono'（单语，文本行即校准目标、无参考行）或 'bi'（双语，末行参考行）。
    判据与 subtitle_calib_merged.py _detect_layout 一致（单行 cue 占比 +
    末行中文主导占比），避免两处漂移。空 cue 不参与统计。"""
    real = [c for c in cues if c.lines]
    if not real:
        return "bi"
    single = sum(1 for c in real if len(c.lines) == 1)
    last_zh = sum(1 for c in real if _is_chinese_dominant(c.lines[-1]))
    r_single = single / len(real)
    r_zh_last = last_zh / len(real)
    if r_single > 0.9 and r_zh_last > 0.9:
        return "mono"
    return "bi"


def _latin_letter_stats(text):
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return 0, 0.0
    latin = sum(1 for ch in letters if "LATIN" in _unicode_name(ch))
    return len(letters), latin / len(letters)


def cue_content_lines(cue, layout):
    """内容行（校准目标）；bi 版式下末行是参考行，不算内容。"""
    if layout == "mono" or len(cue.lines) <= 1:
        return list(cue.lines)
    return list(cue.lines[:-1])


def cue_ref_line(cue, layout):
    if layout == "mono" or len(cue.lines) <= 1:
        return None
    return cue.lines[-1]


def cue_content_text(cue, layout):
    return "\n".join(cue_content_lines(cue, layout))


def _speaker_of(line):
    """>> 说话人标记的键（没有则 None）。"""
    t = (line or "").lstrip()
    if not t.startswith(SPEAKER_PREFIX):
        return None
    rest = t[len(SPEAKER_PREFIX):].strip()
    for sep in ("：", ":", " "):
        if sep in rest:
            return rest.split(sep, 1)[0].strip()
    return rest[:12]


# =============================================================
# 丢弃候选（--drop 应用前两类；其余只观测）
# =============================================================

def _closing_phrase_of(text):
    """整段文本归一化后等同于哪个套话短语（≤短语+2 字），没有则 None。
    长短语优先（thankyou 先于 thank）。（FineSub _closing_phrase_of 原值）"""
    compact = normalized_compact(text)
    if not compact:
        return None
    for phrase in sorted(set(CLOSING_GHOST_PHRASES_JA + CLOSING_GHOST_PHRASES_EN),
                         key=len, reverse=True):
        if phrase in compact and len(compact) <= len(phrase) + CLOSING_GHOST_MAX_EXTRA_CHARS:
            return phrase
    return None


def find_drop_candidates(cues, layout):
    """→ (drops, observations)。

    drops: [dict(num, text, reason, detail)]——两类高置信丢弃候选：
      ① 套话幽灵·语速不可能（日文族，整段=套话且 >20 字/秒）；
      ② 复读幻觉（tandem ≥4 轮且跨度 ≥32 加权单位）。
    observations: [dict(num, text, kind, detail)]——只观测不自动丢：
      英文套话疑似 / 复读超 7 次未塌缩 / 纯填充短行 / 语言切换噪音。
    """
    drops, observations = [], []
    full_text = "".join(cue_content_text(c, layout) for c in cues)
    _letters, latin_ratio = _latin_letter_stats(full_text)
    run_cjk_dominant = _letters > 0 and latin_ratio < LANG_SWITCH_RUN_MAX_LATIN_RATIO
    for cue in cues:
        # ⓿ 空 cue（无文本行）：结构性垃圾，丢弃
        if not [t for t in cue.lines if t.strip()]:
            drops.append({
                "num": cue.num, "text": "（空）",
                "reason": "空 cue",
                "detail": "只有序号和时间轴、无文本行",
            })
            continue
        content = cue_content_text(cue, layout)
        if not content.strip():
            continue
        duration = cue.duration_sec
        # ① 套话幽灵
        phrase = _closing_phrase_of(content)
        if phrase is not None:
            weighted = weighted_char_count(content)
            if (phrase in CLOSING_GHOST_RATE_GATED_PHRASES
                    and duration > 0 and duration < weighted / CLOSING_GHOST_MIN_CHARS_PER_SEC):
                drops.append({
                    "num": cue.num, "text": content.replace("\n", "⏎"),
                    "reason": "套话幽灵·语速不可能",
                    "detail": "整段=%r，%.2fs / %.1f 加权字 = %.1f 字每秒（>20 即物理不可能）"
                              % (phrase, duration, weighted,
                                 weighted / duration if duration > 0 else 0),
                })
            elif phrase in CLOSING_GHOST_PHRASES_EN:
                # 英文族：失效形态是拉长，语速腿永不响；且 20 字/秒对拉丁文是
                # 正常语速 → 证据门控，SRT 层只观测（可用音频证据 harness 确认）。
                observations.append({
                    "num": cue.num, "text": content.replace("\n", "⏎"),
                    "kind": "英文套话疑似",
                    "detail": "整段=%r（%.2fs）；英文族一律证据门控，不自动丢" % (phrase, duration),
                })
            else:
                observations.append({
                    "num": cue.num, "text": content.replace("\n", "⏎"),
                    "kind": "套话语速正常",
                    "detail": "整段=%r 但语速 %.1f 字/秒在物理可能范围——正常语速的套话幻觉"
                              "真实存在，语速判据刻意不碰（FineSub 2026-08-05 结论），"
                              "留音频证据或人工" % (phrase,
                                                   weighted / duration if duration > 0 else 0),
                })
        # ② 复读幻觉
        repeat = detect_repeating_group_cycle(content)
        if repeat:
            drops.append({
                "num": cue.num, "text": content.replace("\n", "⏎"),
                "reason": "复读幻觉",
                "detail": repeat,
            })
        else:
            over = detect_exact_repeat_over(content)
            if over:
                observations.append({
                    "num": cue.num, "text": content.replace("\n", "⏎"),
                    "kind": "复读超 7 次未塌缩",
                    "detail": "单元 %r ×%d；FineSub 口径为塌缩保留 5 次（词级操作），"
                              "cue 级不自动压缩，留人工" % (over[0], over[1]),
                })
        # ③ 纯填充短行（观测）
        stripped = content.strip()
        if stripped in FILLER_TOKENS and 0 < duration < FILLER_MAX_SECONDS:
            observations.append({
                "num": cue.num, "text": stripped,
                "kind": "纯填充短行",
                "detail": "整行=纯语气 token 且 %.2fs；口癖可能是内容，只观测不丢" % duration,
            })
        # ④ 语言切换噪音（观测；FineSub 同样不丢——命中集合里混着真实英文内容）
        if run_cjk_dominant:
            letters, seg_ratio = _latin_letter_stats(content)
            if (letters >= LANG_SWITCH_SEGMENT_MIN_LETTERS
                    and seg_ratio >= LANG_SWITCH_SEGMENT_MIN_LATIN_RATIO):
                observations.append({
                    "num": cue.num, "text": content.replace("\n", "⏎"),
                    "kind": "语言切换噪音",
                    "detail": "CJK 主导素材里的大段拉丁文本（%d 字母、拉丁占比 %.0f%%）；"
                              "可能混真实英文歌词/配音，只观测" % (letters, seg_ratio * 100),
                })
    return drops, observations


# =============================================================
# 合并候选（--merge 应用硬门槛内 + filler 三明治）
# =============================================================

def _merge_block_reason(a, b, layout):
    """返回不可合并的原因；None = 可合并（必要条件已过）。"""
    a_content = cue_content_lines(a, layout)
    b_content = cue_content_lines(b, layout)
    if not a_content or not b_content:
        return "空内容行"
    a_first, b_first = a_content[0].strip(), b_content[0].strip()
    if not a_first or not b_first:
        return "空内容行"
    # 上一条整体是纯填充词（"嗯"/"呃"…）：不是句子碎片，不向前合并
    # （它的正确去向是填充观测项或三明治的中段，不是续句合并的左段）。
    if a_first in FILLER_TOKENS:
        return "上一条是纯填充词"
    # 说话人：b 带标记且与 a 不同（或 a 没有）→ 换人嫌疑，绝不合并
    sp_a, sp_b = _speaker_of(a_first), _speaker_of(b_first)
    if sp_b is not None and sp_b != sp_a:
        return "换人说话（%s → %s）" % (sp_a or "无标记", sp_b)
    # 方括号标记（[音乐]/[笑声] 等非语音声响标注）：合并易丢语境，保守block
    if "[" in a_first or "[" in b_first:
        return "含 [方括号标记]"
    # a 已收句（句末标点/省略号）→ 语义已完结。多行 cue 看**末行**末字符。
    a_last = a_content[-1].strip()
    if a_last and punct_class(a_last[-1]) == "sentence":
        return "上一条已收句（%s）" % a_last[-1]
    # b 以句中/句首标点或开引号开头 → 断句被劈开的痕迹，交给 flow 人工处理
    if b_first and punct_class(b_first[0]) in ("clause", "opening"):
        return "下一条以 %s 开头" % b_first[0]
    # 邻接间隔：FineSub DP 的 G(g) 在 1.5s 近乎强制切分；SRT 无词级停顿，取 1.0s
    gap = (b.start_ms - a.end_ms) / 1000.0
    if gap > MERGE_MAX_GAP_SECONDS:
        return "间隔 %.2fs 过大" % gap
    return None


def _merge_gate(weighted, span_sec):
    """→ 'hard_ok' / 'over_hard' / 'over_absolute'。"""
    if weighted > ABSOLUTE_MERGE_CHARS or span_sec > ABSOLUTE_MERGE_SECONDS:
        return "over_absolute"
    if weighted > HARD_MERGE_CHARS or span_sec > HARD_MERGE_SECONDS:
        return "over_hard"
    return "hard_ok"


def _ends_cjk(s):
    return bool(s) and (unicodedata.name(s[-1], "").find("CJK") >= 0
                        or 0x3040 <= ord(s[-1]) <= 0x30FF
                        or 0xAC00 <= ord(s[-1]) <= 0xD7AF)


def _starts_cjk(s):
    return bool(s) and (unicodedata.name(s[0], "").find("CJK") >= 0
                        or 0x3040 <= ord(s[0]) <= 0x30FF
                        or 0xAC00 <= ord(s[0]) <= 0xD7AF)


def _join_pair(x, y):
    """拼接两段文本：CJK 边界直接接，拉丁边界补空格。"""
    x, y = (x or "").strip(), (y or "").strip()
    if not x:
        return y
    if not y:
        return x
    return x + y if (_ends_cjk(x) or _starts_cjk(y)) else x + " " + y


def _merged_preview(a, b, layout, mid=None):
    """合并后的文本行预览（内容行拼为一行，参考行依次保留）。

    mid：filler 三明治的中段文本——按 FineSub 口径保留一次（压缩而非删除），
    稳定化层不做内容删除。"""
    parts = [t.strip() for t in cue_content_lines(a, layout) if t.strip()]
    if mid and mid.strip():
        parts.append(mid.strip())
    parts.extend(t.strip() for t in cue_content_lines(b, layout) if t.strip())
    acc = ""
    for t in parts:
        acc = _join_pair(acc, t)
    out = [acc] if acc else []
    a_ref, b_ref = cue_ref_line(a, layout), cue_ref_line(b, layout)
    refs = [t.strip() for t in (a_ref, b_ref) if t is not None and t.strip()]
    if refs:
        merged_ref = refs[0]
        for t in refs[1:]:
            merged_ref = _join_pair(merged_ref, t)
        out.append(merged_ref)
    return out


def find_merge_candidates(cues, layout):
    """→ (applies, specials)。

    applies: 硬门槛内的相邻续句合并 + filler 三明治（--merge 应用）；
    specials: 越硬门槛但在绝对门槛内的「词中接回」特批候选（只报告，
     FineSub 口径：特批须说明理由，由人工拍板）。

    贪心链：入选一处合并后跳过其右段（i += 2），**不产生重叠候选**——
    应用阶段按块区间替换，重叠候选会互相踩坏行表。
    """
    applies, specials = [], []
    n = len(cues)
    used = set()          # 已纳入合并的 cue 下标（三明治用）
    i = 0
    while i < n - 1:
        if i in used:
            i += 1
            continue
        a, b = cues[i], cues[i + 1]
        # filler 三明治：a + 纯填充 b(≤3 加权字) + c
        if i + 2 < n and (i + 2) not in used:
            mid = cue_content_text(b, layout).strip()
            mid_w = weighted_char_count(mid)
            if (mid and mid_w <= FILLER_MAX_CHARS
                    and detect_exact_repeat_over(mid) is None
                    and _merge_block_reason(a, cues[i + 2], layout) is None):
                c = cues[i + 2]
                span = (c.end_ms - a.start_ms) / 1000.0
                weighted = (weighted_char_count(cue_content_text(a, layout))
                            + mid_w
                            + weighted_char_count(cue_content_text(c, layout)))
                if weighted <= SANDWICH_MAX_CHARS and span <= SANDWICH_MAX_SECONDS:
                    gap1 = (b.start_ms - a.end_ms) / 1000.0
                    gap2 = (c.start_ms - b.end_ms) / 1000.0
                    if gap1 <= MERGE_MAX_GAP_SECONDS and gap2 <= MERGE_MAX_GAP_SECONDS:
                        lines = _merged_preview(a, c, layout, mid=mid)
                        applies.append({
                            "kind": "filler 三明治",
                            "cues": (a.num, b.num, c.num),
                            "text": " ‖ ".join(
                                cue_content_text(x, layout).replace("\n", "⏎")
                                for x in (a, b, c)),
                            "merged": " ⏎ ".join(t.replace("\n", "⏎") for t in lines),
                            "time": "%s --> %s" % (_fmt_time(a.start_ms), _fmt_time(c.end_ms)),
                            "detail": "中段 %r 为纯填充（≤%d 字，保留一次不删除）；合计 %.1f "
                                      "加权字 / %.2fs（≤%d 字 / %.1fs）"
                                      % (mid, FILLER_MAX_CHARS, weighted, span,
                                         SANDWICH_MAX_CHARS, SANDWICH_MAX_SECONDS),
                        })
                        used.update({i, i + 1, i + 2})
                        i += 3
                        continue
        reason = _merge_block_reason(a, b, layout)
        if reason is not None:
            i += 1
            continue
        weighted = (weighted_char_count(cue_content_text(a, layout))
                    + weighted_char_count(cue_content_text(b, layout)))
        span = (b.end_ms - a.start_ms) / 1000.0
        gate = _merge_gate(weighted, span)
        lines = _merged_preview(a, b, layout)
        item = {
            "cues": (a.num, b.num),
            "text": " ‖ ".join((cue_content_text(a, layout),
                                cue_content_text(b, layout))).replace("\n", "⏎"),
            "merged": " ⏎ ".join(t.replace("\n", "⏎") for t in lines),
            "time": "%s --> %s" % (_fmt_time(a.start_ms), _fmt_time(b.end_ms)),
            "detail": "%.1f 加权字 / %.2fs" % (weighted, span),
        }
        if gate == "hard_ok":
            item["kind"] = "续句合并"
            applies.append(item)
            i += 2                      # 入选：跳过右段，避免重叠候选
            continue
        elif gate == "over_hard":
            # 唯一可特批形态：同一个词/不可拆短语被切断——SRT 无词级信息，
            # 代理判据是两侧都是裸词界（无任何标点）。仍不自动应用。
            item["kind"] = "越硬门槛·特批候选"
            item["detail"] += ("；越硬门槛（≤%d 字 / %.1fs 才可合并）——疑似词中切断，"
                               "按 FineSub 口径须人工说明理由后特批"
                               % (HARD_MERGE_CHARS, HARD_MERGE_SECONDS))
            specials.append(item)
        # over_absolute：任何情况都必须拒绝，连候选都不列；未入选只前进一格
        i += 1
    return applies, specials


# =============================================================
# 拆分候选（--split 应用；无标点超长只观测）
# =============================================================

def _split_points(text):
    """可断字符下标列表（断在该字符**之后**），按标点分级排序返回
    [(index, class_rank)]；括号深度内不断（opening 向右胶合 / closing 向左胶合）。"""
    points = []
    depth = 0
    for i, ch in enumerate(text):
        cls = punct_class(ch)
        if cls == "opening":
            depth += 1
            continue
        if cls == "closing":
            depth = max(0, depth - 1)
            continue
        if depth > 0:
            continue
        if cls == "sentence":
            points.append((i, 0))
        elif cls == "clause":
            points.append((i, 1))
        elif cls == "other":
            points.append((i, 2))
    return points


def _split_text_at(text, cut_indices):
    """按断点下标（断后）切文本；cut_indices 必须递增。"""
    pieces, start = [], 0
    for idx in cut_indices:
        pieces.append(text[start:idx + 1])
        start = idx + 1
    if start < len(text):
        pieces.append(text[start:])
    return [p for p in pieces if p.strip()]


def _plan_cuts(text, total_weight):
    """贪心选断点：优先句末、其次句中；目标是把超长段切成都 ≤ CHARS_OK_HI 的段。
    返回 cut_indices 或 None（无可用标点）。"""
    points = _split_points(text)
    if not points:
        return None
    cuts = []
    # 反复切：只要还有段超墙，就在最接近半权的点补一刀
    for _ in range(8):
        pieces = _split_text_at(text, cuts) if cuts else [text]
        over = [(k, p) for k, p in enumerate(pieces)
                if weighted_char_count(p) > CHARS_OK_HI]
        if not over:
            break
        k, piece = over[0]
        base = sum(len(p) for p in pieces[:k])
        piece_points = [(i, rank) for i, rank in points if base <= i < base + len(piece)]
        if not piece_points:
            return None
        target = base + len(piece) * 0.5
        best = min(piece_points, key=lambda pr: (abs(pr[0] + 1 - target), pr[1]))
        cuts.append(best[0])
        cuts.sort()
        if len(cuts) >= 8:
            break
    if not cuts:
        return None
    return cuts


def _split_ref_line(ref, cuts_ratio):
    """参考行按同一比例切：优先自身标点，其次空格，最后按字符比例硬切。"""
    if not ref:
        return []
    points = _split_points(ref)
    pieces = None
    if points:
        target = len(ref) * cuts_ratio
        best = min(points, key=lambda pr: (abs(pr[0] + 1 - target), pr[1]))
        pieces = _split_text_at(ref, [best[0]])
    if not pieces or len(pieces) < 2:
        # 无标点：找最接近比例位置的空格（拉丁词界），避免硬切断词
        target = len(ref) * cuts_ratio
        spaces = [i for i, ch in enumerate(ref) if ch == " "]
        if spaces:
            best = min(spaces, key=lambda i: abs(i + 1 - target))
            pieces = _split_text_at(ref, [best])
    if not pieces or len(pieces) < 2:
        cut = max(1, min(len(ref) - 1, int(round(len(ref) * cuts_ratio))))
        pieces = [ref[:cut], ref[cut:]]
    return [p for p in pieces if p.strip()]


def find_split_candidates(cues, layout):
    """→ (applies, observations)。applies: 超墙且找得到断点的 cue。"""
    applies, observations = [], []
    for cue in cues:
        content_lines = cue_content_lines(cue, layout)
        content = "\n".join(content_lines)
        weighted = weighted_char_count(content)
        duration = cue.duration_sec
        if weighted <= CHARS_OK_HI and duration <= DUR_OK_HI:
            continue
        cuts = _plan_cuts(content, weighted)
        if cuts is None:
            observations.append({
                "num": cue.num, "text": content.replace("\n", "⏎"),
                "kind": "超长无标点",
                "detail": "%.1f 加权字 / %.2fs 超墙（%g 字 / %gs）但无可断标点，需人工"
                          % (weighted, duration, CHARS_OK_HI, DUR_OK_HI),
            })
            continue
        pieces = _split_text_at(content, cuts)
        if len(pieces) < 2:
            continue
        # 时间按加权字数比例分配（SRT 无词级坐标的诚实近似）
        weights = [weighted_char_count(p) for p in pieces]
        total_w = sum(weights) or 1.0
        span = cue.duration_sec
        bounds, acc = [], 0.0
        for w in weights[:-1]:
            acc += w
            bounds.append(cue.start_ms + int(round(span * 1000 * acc / total_w)))
        ref = cue_ref_line(cue, layout)
        ratio = weights[0] / total_w
        ref_pieces = _split_ref_line(ref, ratio) if ref else []
        applies.append({
            "num": cue.num,
            "text": content.replace("\n", "⏎"),
            "kind": "超长拆分",
            "detail": "%.1f 加权字 / %.2fs → %d 段（断点分级：句末>句中；括号内不断）；"
                      "时间按加权字数比例分配" % (weighted, duration, len(pieces)),
            "pieces": pieces,
            "ref_pieces": ref_pieces,
            "bounds": bounds,
            "start_ms": cue.start_ms,
            "end_ms": cue.end_ms,
        })
    return applies, observations


# =============================================================
# 应用（块级编辑 + 重编号）
# =============================================================

def _render_cue_block(num, start_ms, end_ms, text_lines):
    return [str(num), "%s --> %s" % (_fmt_time(start_ms), _fmt_time(end_ms))] + list(text_lines)


def apply_stabilize(lines, cues, layout, *, drop=True, merge=True, split=True,
                    drops=None, merges=None, splits=None):
    """把选定的操作应用到 lines（已按 \\n 切分）上，返回新 lines。

    编辑策略：自后向前替换每个受影响的 cue 块（保留下标有效），最后统一
    重编号。非 cue 行（文件头注释、空行等）原样保留。
    """
    drops = drops or []
    merges = merges or []
    splits = splits or []
    by_num = {c.num: c for c in cues}
    # 受影响块集合（按 block_start 去重）
    ops = []                      # (block_start, block_end, new_lines)
    drop_starts = set()
    for d in drops:
        cue = by_num.get(d["num"])
        if cue is not None:
            drop_starts.add(cue.block_start)
            ops.append((cue.block_start, cue.block_end, None))     # None = 删除
    if merge:
        for m in merges:
            if m.get("kind") != "续句合并":
                continue          # 三明治在下面按三块处理
            a, b = by_num.get(m["cues"][0]), by_num.get(m["cues"][1])
            if a is None or b is None:
                continue
            new_lines = _render_cue_block(a.num, a.start_ms, b.end_ms,
                                          _preview_to_lines(m["merged"]))
            ops.append((a.block_start, b.block_end, new_lines))
        for m in merges:
            if m.get("kind") != "filler 三明治":
                continue
            a, _mid, c = (by_num.get(m["cues"][0]), by_num.get(m["cues"][1]),
                          by_num.get(m["cues"][2]))
            if a is None or c is None:
                continue
            new_lines = _render_cue_block(a.num, a.start_ms, c.end_ms,
                                          _preview_to_lines(m["merged"]))
            ops.append((a.block_start, c.block_end, new_lines))
    if split:
        for s in splits:
            cue = by_num.get(s["num"])
            if cue is None:
                continue
            new_blocks = []
            pieces, ref_pieces = s["pieces"], s["ref_pieces"]
            bounds, start_ms, end_ms = s["bounds"], s["start_ms"], s["end_ms"]
            edges = [start_ms] + bounds + [end_ms]
            for k, piece in enumerate(pieces):
                text_lines = [piece]
                if ref_pieces:
                    if k < len(ref_pieces):
                        text_lines.append(ref_pieces[k])
                    elif k == len(pieces) - 1:
                        text_lines.extend(ref_pieces[len(pieces):])
                block = _render_cue_block(cue.num, edges[k], edges[k + 1], text_lines)
                if new_blocks:
                    new_blocks.append("")      # 块间空行：_renumber 靠它认 index 行
                new_blocks.extend(block)
            ops.append((cue.block_start, cue.block_end, new_blocks))
    if not ops:
        return list(lines), 0
    ops.sort(key=lambda o: o[0], reverse=True)
    out = list(lines)
    changed = 0
    for start, end, new_lines in ops:
        if new_lines is None:
            del out[start:end]
            changed += 1
        else:
            out[start:end] = new_lines
            changed += 1
    # 删除块可能留下连续空行：折叠成单个空行（SRT 块间分隔）
    out = _collapse_blank_runs(out)
    out = _renumber(out)
    return out, changed


def _preview_to_lines(preview):
    """报告预览里的 ⏎ 还原成真实换行行。"""
    return [t for t in (preview or "").split(" ⏎ ") if t != ""]


def _collapse_blank_runs(lines):
    out, blank = [], False
    for ln in lines:
        if ln.strip() == "":
            if blank:
                continue
            blank = True
        else:
            blank = False
        out.append(ln)
    while out and out[-1].strip() == "":
        out.pop()
    return out


def _renumber(lines):
    """重排所有 cue 序号为 1..N（合并/拆分/丢弃后序号必须连续）。"""
    out = []
    i, n, num = 0, len(lines), 0
    while i < n:
        s = lines[i].strip()
        if s.isdigit() and (i == 0 or lines[i - 1].strip() == ""):
            j = i + 1
            if j < n and "-->" in lines[j]:
                num += 1
                out.append(str(num))
                i += 1
                continue
        out.append(lines[i])
        i += 1
    return out


# =============================================================
# 报告
# =============================================================

def _fmt_report(src, layout, drops, merge_applies, merge_specials, splits,
                split_obs, applied, ops_desc):
    L = []
    L.append("# SRT 稳定化报告（stabilize）")
    L.append("")
    L.append("- 源文件：`%s`" % src)
    L.append("- 版式：%s" % ("mono（单语）" if layout == "mono" else "bi（双语，末行参考行）"))
    L.append("- 阈值出处：FineSub v0.5.1 stabilization.py / segmentation.py / "
             "llm/prompt_constants.py 原值移植（见 finesub_stabilize_gap_analysis.md）")
    L.append("")
    L.append("## 丢弃候选（--drop 应用；共 %d）" % len(drops))
    if drops:
        L.append("")
        L.append("序号 | 判定 | 依据 | 原文")
        L.append("--- | --- | --- | ---")
        for d in drops:
            L.append("`%s` | %s | %s | %s" % (d["num"], d["reason"], d["detail"], d["text"]))
    else:
        L.append("（干净）")
    L.append("")
    L.append("## 合并候选（--merge 应用硬门槛内；共 %d）" % len(merge_applies))
    if merge_applies:
        L.append("")
        L.append("类型 | 序号 | 原时间轴 | 判据 | 原文 ‖ 合并后")
        L.append("--- | --- | --- | --- | ---")
        for m in merge_applies:
            L.append("%s | %s | %s | %s | %s ‖ **%s**"
                     % (m["kind"], "+".join(m["cues"]), m["time"], m["detail"],
                        m["text"], m["merged"]))
    else:
        L.append("（干净）")
    L.append("")
    L.append("## 拆分候选（--split 应用；共 %d）" % len(splits))
    if splits:
        L.append("")
        L.append("序号 | 判据 | 原文 ‖ 拆分后")
        L.append("--- | --- | --- | ---")
        for s in splits:
            pieces = " ｜ ".join(s["pieces"])
            if s["ref_pieces"]:
                pieces += "　（参考行：%s）" % " ｜ ".join(s["ref_pieces"])
            L.append("`%s` | %s | %s ‖ **%s**" % (s["num"], s["detail"], s["text"], pieces))
    else:
        L.append("（干净）")
    L.append("")
    L.append("## 观测项（只报告，不自动应用；共 %d）"
             % (len(merge_specials) + len(split_obs)))
    if merge_specials or split_obs:
        L.append("")
        L.append("序号 | 类型 | 说明 | 原文")
        L.append("--- | --- | --- | ---")
        for m in merge_specials:
            L.append("%s | %s | %s | %s" % ("+".join(m["cues"]), m["kind"],
                                            m["detail"], m["text"]))
        for o in split_obs:
            L.append("`%s` | %s | %s | %s" % (o["num"], o["kind"], o["detail"], o["text"]))
    else:
        L.append("（干净）")
    if applied:
        L.append("")
        L.append("## 已应用")
        L.append("")
        L.append(ops_desc)
        L.append("")
        L.append("⚠ 序号已重排、时间轴已重算（合并取首尾跨度，拆分按加权字数比例分配）。"
                 "结构已变，`verify` 不再适用；`align-audit` 按序号比对，重排后必误报，"
                 "也不要跑。风格问题（行首悬挂标点等）接着走 `flow`。")
    L.append("")
    return "\n".join(L)


# =============================================================
# 入口
# =============================================================

def run(src, out=None, report=None, drop=True, merge=True, split=True, log=print):
    """执行 stabilize。返回退出码（0 干净 / 1 有候选 / 2 用法或 IO 错误）。"""
    if not os.path.isfile(src):
        log("[错误] 文件不存在: %s" % src)
        return 2
    raw = open(src, "rb").read()
    bom = raw.startswith(b"\xef\xbb\xbf")
    crlf = b"\r\n" in raw
    text = _decode_any(raw)
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    cues = parse_srt(lines)
    if not cues:
        log("[错误] 未解析到 cue，请检查输入: %s" % src)
        return 2
    layout = detect_layout(cues)

    drops, drop_obs = find_drop_candidates(cues, layout)
    merge_applies, merge_specials = find_merge_candidates(cues, layout)
    splits, split_obs = find_split_candidates(cues, layout)

    # 冲突过滤：应用阶段按块区间自后向前替换，任何两类操作不得碰同一 cue，
    # 否则行表被互相踩坏。优先级：丢弃（物理不可能性判据，最高置信）>
    # 拆分（客观墙违约）> 合并（启发式，让位）。被过滤掉的合并在报告里
    # 不计入可应用数。
    drop_nums = {d["num"] for d in drops}
    split_nums = {s["num"] for s in splits}
    before = len(merge_applies)
    merge_applies = [m for m in merge_applies
                     if not any(x in drop_nums or x in split_nums for x in m["cues"])]
    merge_nums = {x for m in merge_applies for x in m["cues"]}
    splits = [s for s in splits if s["num"] not in merge_nums and s["num"] not in drop_nums]
    conflict_dropped = before - len(merge_applies)

    log("[%s] %d cues（%s）" % (os.path.basename(src), len(cues),
                               "mono" if layout == "mono" else "bi"))
    if conflict_dropped:
        log("  （%d 处合并候选与丢弃/拆分冲突，未列入）" % conflict_dropped)
    log("  丢弃候选 %d 处" % len(drops)
        + ("" if drops else "（干净）"))
    for d in drops[:12]:
        log("    #%s %s：%s（%s）" % (d["num"], d["reason"], d["text"][:36], d["detail"][:60]))
    if len(drops) > 12:
        log("    ... 另有 %d 处" % (len(drops) - 12))
    log("  合并候选 %d 处" % len(merge_applies) + ("" if merge_applies else "（干净）"))
    for m in merge_applies[:12]:
        log("    #%s+%s %s：%s（%s）" % (m["cues"][0], m["cues"][1], m["kind"],
                                        m["text"][:30], m["detail"][:40]))
    if len(merge_applies) > 12:
        log("    ... 另有 %d 处" % (len(merge_applies) - 12))
    log("  拆分候选 %d 处" % len(splits) + ("" if splits else "（干净）"))
    for s in splits[:12]:
        log("    #%s %s：%s" % (s["num"], s["detail"][:40], s["text"][:30]))
    if len(splits) > 12:
        log("    ... 另有 %d 处" % (len(splits) - 12))
    obs_total = len(merge_specials) + len(split_obs) + len(drop_obs)
    log("  观测项 %d 处（只报告不应用）" % obs_total)
    for o in drop_obs[:8]:
        log("    #%s %s：%s" % (o["num"], o["kind"], o["detail"][:60]))
    for m in merge_specials[:8]:
        log("    #%s+%s %s：%s" % (m["cues"][0], m["cues"][1], m["kind"],
                                  m["detail"][:60]))
    for o in split_obs[:8]:
        log("    #%s %s：%s" % (o["num"], o["kind"], o["detail"][:60]))

    applied = False
    ops_desc = ""
    if out:
        want = []
        if drop:
            want.append("drop")
        if merge:
            want.append("merge")
        if split:
            want.append("split")
        if not want:
            log("未指定任何稳定化操作（--drop/--merge/--split），按仅报告处理，不写文件。")
        else:
            new_lines, changed = apply_stabilize(
                lines, cues, layout,
                drop=drop, merge=merge, split=split,
                drops=drops, merges=merge_applies, splits=splits)
            if changed:
                body = "\n".join(new_lines)
                if crlf:
                    body = body.replace("\n", "\r\n")
                with open(out, "w", encoding="utf-8", newline="") as f:
                    f.write(("\ufeff" if bom else "") + body)
                applied = True
                ops_desc = ("- 应用操作：%s\n- 改动块数：%d\n- 输出：`%s`"
                            % ("、".join(want), changed, out))
                log("已写入：%s（%s，改动 %d 块）" % (out, "、".join(want), changed))
            else:
                log("无可应用改动，未写文件。")

    if report:
        text_out = _fmt_report(src, layout, drops, merge_applies, merge_specials,
                               splits, split_obs, applied, ops_desc)
        with open(report, "w", encoding="utf-8") as f:
            f.write(text_out)
        log("报告：%s" % report)

    has_candidates = bool(drops or merge_applies or splits or merge_specials or split_obs)
    if not out:
        if has_candidates:
            log("STABILIZE：%d 丢弃 / %d 合并 / %d 拆分 / %d 观测 待处理"
                "（加 --out 落盘；--drop/--merge/--split 选择应用哪些，"
                "--no-* 可关）" % (len(drops), len(merge_applies), len(splits),
                                   len(merge_specials) + len(split_obs) + len(drop_obs)))
            return 1
        log("STABILIZE OK：无稳定化候选")
    return 0


if __name__ == "__main__":     # 手工小样：python calib_stabilize.py <src.srt> [--out x.srt]
    _args = sys.argv[1:]
    _out = None
    if "--out" in _args:
        _k = _args.index("--out")
        _out = _args[_k + 1]
        _args = _args[:_k] + _args[_k + 2:]
    raise SystemExit(run(_args[0], out=_out) if _args else 2)
