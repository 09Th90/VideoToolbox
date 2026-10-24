# -*- coding: utf-8 -*-
# @version 2.6.0
"""文本解码与语言/行类型判定

源：subtitle_calib_merged.py L1-L12060 @ 97d7d463（2026-10-24 冻结快照）
"""
import io
import os
import re
import shutil
import sys
import unicodedata


# =============================================================
# 0. 统一解码：外部/用户文本一律智能解码，绝不因编码而崩
# =============================================================
# 背景（v1.12.0 修复）：本层曾在 v1.11.0 引入，重构时被删，导致输入解码退回
# 硬 `utf-8-sig` —— GBK/GB18030/Big5 编码的字幕直接 UnicodeDecodeError，
# 整条校准链路不可用（_selftest_pack 的「_decode_any 可读 GBK 字幕」即为守门断言）。
# 原则：读取外部/用户文本一律智能解码；写出统一 UTF-8（是否带 BOM / CRLF 按原样保留）。
TEXT_ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "big5", "shift_jis", "latin-1")



def _decode_any(data, encodings=TEXT_ENCODINGS):
    """把任意字节流解码成文本（永不抛异常）。

    BOM 优先：utf-32 > utf-16 > utf-8（用带 BOM 的编解码器，可自动剥掉 BOM）；
    无 BOM 依次尝试 utf-8 → gb18030（GBK 超集）→ big5 → shift_jis → latin-1，
    最后兜底 utf-8 replace。ASCII 是 UTF-8 子集，天然覆盖。
    """
    if isinstance(data, str):
        return data
    if not data:
        return ""
    if data[:4] in (b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff"):
        try:
            return data.decode("utf-32")
        except UnicodeDecodeError:
            pass
    elif data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        try:
            return data.decode("utf-16")
        except UnicodeDecodeError:
            pass
    if data[:3] == b"\xef\xbb\xbf":
        try:
            return data.decode("utf-8-sig")
        except UnicodeDecodeError:
            pass
    for enc in encodings:
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", "replace")



# =============================================================
# 通用校准函数（按模式逐行原位替换，保持格式一字不变）
# =============================================================
_KO_HANGUL = re.compile(r"[\uac00-\ud7a3\u3130-\u318f]")   # 谚文判据：含谚文的文本行=韩语参考行

_KANA = re.compile(r"[\u3040-\u30ff]")                       # 假名判据：含假名的文本行=日语参考行（2026-10-23）

_MARKER_ONLY = re.compile(r"^(?:>>\s*)?(?:\[[^\]]+\]\s*)+$")  # 纯标记行（>> [音乐] / [笑声]）

_ZH_PUNCT = re.compile(r"[，。！？；：、“”‘’（）《》【】…—]")  # 中文标点：纯拉丁中文行的兜底判据

_CJK = re.compile(r"[\u4e00-\u9fff]")                        # 汉字判据：含汉字的文本行=中文行（2026-10-14，ak 全中文行覆盖用）



# =============================================================
# 片源版式探测（mono 单语 / bi 双语，2026-10-09 沉淀）
#   extract/merge/verify/length/flow 原先默认「每条 cue ≥2 文本行、末行为
#   不可改动的参考（英/日/韩）行」。纯中文单行片源（如 UP 主 reaction 熟肉，
#   每条只有一行中文、无参考行）下，唯一文本行被当成参考行：merge 永不覆盖、
#   verify 又把它同时当中文行和英文行而误判。这里统一探测版式供各子命令复用，
#   双语片源（bi）的既有行为保持逐字节不变。
# =============================================================
def _script_counts(s):
    """统计一段文本里 汉字 / 谚文 / 假名 / 拉丁字母 的数量。"""
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
    """一行是否以中文为主导（至少 1 个汉字，汉字数 > 谚文+假名，且不少于拉丁字母）。"""
    han, hangul, kana, lat = _script_counts(s)
    return han >= 1 and han > hangul + kana and han >= lat



def _is_chinese_line(s):
    """行级中文判据（2026-10-23）：含汉字，且不含假名/谚文。

    与 _is_chinese_dominant 的区别：不要求汉字数≥拉丁字母数，避免
    「Shin 胜过 Swirling。不过第二段」这类中文+大量英文专名的行被误判
    为参考行，进而把英文行当成中文行改写。
    """
    return bool(_CJK.search(s)) and not _KANA.search(s) and not _KO_HANGUL.search(s)



def _split_cue_text(texts):
    """按语言把 cue 的文本行拆成 (中文行下标, 参考行下标)。

    2026-10-23：校准脚本原先假定「首文本行=中文、末行=参考」，遇到
    英文在上的双语片源会把英文当中文改。这里改为按字符集判定，
    与行序无关：含假名/谚文的一律视为参考行；其余含汉字的视为中文行；
    标记行（如 >> [音乐]）因含汉字归入中文行，交由调用方保护。
    """
    zh, ref = [], []
    for i, text in enumerate(texts):
        if _is_chinese_line(text):
            zh.append(i)
        else:
            ref.append(i)
    if not zh:
        # 纯拉丁中文行（如「Nvidia RTS Spark。」「Exorder。」）没有汉字，
        # 用中文标点兜底；只有恰好一行命中时才采用，避免误判英文参考行。
        punct = [i for i, text in enumerate(texts) if _ZH_PUNCT.search(text)]
        if len(punct) == 1:
            zh = punct
            ref = [i for i in range(len(texts)) if i not in zh]
    return zh, ref



def _iter_cue_text_blocks(lines):
    """遍历已 norm（\\n 分行）的 SRT 行，逐 cue 产出其文本行 list（不含序号/时间轴/空行）。"""
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
                    yield texts
                i = kk
                continue
        i += 1

