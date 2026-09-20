# -*- coding: utf-8 -*-
# @version 1.15.6
"""AI 校准 Agent —— Agent 级字幕术语校准（v1.11.0；v1.16.0 并发与提示词优化）。

定位
====
用户开启「AI 校准」后点「开始校准」，等价于向一个 Agent 下达这样的要求：

    基于脚本 subtitle_calib_merged，校准字幕，不允许改变时间轴和格式，
    仅调整文字内容，如果一次无法读取完整，就自行拆分，最后合并。

本模块就是那个 Agent 的实现：它**不依赖 GUI**，只依赖标准库 + 注入的
LLM 对话回调，因此可被界面、命令行、自检脚本共用。

Agent 的工具与闭环（每一步都进日志）
====================================
  1. 起点            —— 默认先跑术语脚本基线（机械部分零成本且必定正确）；
                        长片源第二轮可用 `resume_from` 直接以上轮产物为起点。
  1b. 参考行保护      —— 基线/上轮产物到手后，按 cue 序号把每条参考行强制还原成
                        原始 src 的样子：`--endo` 等「统一全部文本行」模式会连英文
                        参考行一起替换，若不纠正，第 8 步 verify 的「英文行 0 改动」
                        断言必失败、整轮白跑（2026-09-18 终末地反应片实操沉淀）。
  2. 抽取 cue 表      —— `extract`：SRT → 「序号 / 中文行 / 英文行」，剥离全部结构信息。
  3. 载入知识库       —— `kb-export --json`：对象级实体 → 「错形 → 官方名」+ 负向排除。
  4. 自主分块         —— 按 cue 条数与字符预算切块，并**回退到句子边界**（上一条参考行
                        以句末标点收尾，或与下一条的时间间隙 ≥0.8s），避免把跨 cue 的
                        长句劈到两块；同时按「中文行命中 → 参考行命中 → 其余」挑规则。
  5. 逐块 LLM 判定    —— 条目按三列 `序号<TAB>中文行<TAB>参考行` 投喂（双语片源的
                        参考行是最强判据，2026-09-14 起默认携带）；输出严格 JSON。
                        显式给 workdir 时每块落盘，中断后可断点续跑。
  6. 证据校验         —— 两种风格：
                          · `term`（默认）只接受能被知识库解释的名词级替换；
                          · `rewrite`（2026-09-14 新增）允许整句重写中文行，但逐条
                            断言「没有破坏什么」：行数一致、`[标记]` 与 `>>` 保留、
                            错形必换、已有官方名不被改坏、行宽 ≤32 汉字当量、
                            长度不膨胀、不新增原文没有的拉丁词。
  7. 合并回填         —— 按 cue 边界重建 SRT：只替换中文行，序号 / 时间轴 /
                        英文行 / 换行 / BOM 一字不动。
  8. 独立校验         —— 脚本 `verify`（cue 数/序号/时间轴/英文行/CRLF/BOM）做第三方
                        断言；随后 `length` 做行宽体检（超限记入报告，`strict_width=True`
                        时直接判失败）。不通过即判失败。

「再次校准」= round_no+1：用 `resume_from` 指向上轮产物作为起点（不从原始源重跑，
否则已采纳的改动会丢），并把上轮采纳明细作为 `prev_changes` 注入提示词（不得回退）。

调用契约
========
    calibrate(src, out=..., report=..., mode_flag="--ko", log=..., chat=...)

    log(msg, level="dim")                 # 日志回调（GUI 投递到消息队列）
    chat(prompt, system=None, max_tokens=8192) -> str   # LLM 文本回调

返回 dict：ok / out / report / script_changes / ai_changes / rejected / round / error

v1.16.0 优化
============
  · concurrency      逐块 LLM 调用受控并发（默认 1＝串行，行为与旧版一致）；
  · 块级规则裁剪      select_rules_for_chunk：只喂本块命中的 hot/warm 规则，
                     提示词 token 显著下降（校验仍用全量规则，正确性不变）；
  · JSON 抢救内置     _repair_json 不再依赖可选第三方库 json_repair；
  · 重试带反馈        invalid/truncated 重问时把失败原因与整改要求写进提示词；
  · ckpt 转义修复     断点续跑读取与 _esc 对称（旧版含反斜杠的文本会还原错）。
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor

SCRIPT_NAME = "subtitle_calib_merged.py"

#: 界面片源模式参数 → 知识库里的模式键（与脚本 ENTITIES 的 modes 取值一致）
MODE_KEY = {
    "": "bi", "--ja": "ja", "--jpe": "jpe", "--ko": "ko", "--ak": "ak",
    "--akko": "akko", "--endo": "endo", "--zho": "zho", "--pgr": "pgr",
    "--pgren": "pgren", "--wwoc": "wwoc", "--react": "react",
}
MODE_NAME = {
    "": "中英双语", "--ja": "日语原声·鸣潮", "--jpe": "日语原声·终末地",
    "--ko": "韩语原声·鸣潮", "--ak": "明日方舟", "--akko": "明日方舟·韩语",
    "--endo": "终末地", "--zho": "中文行专属", "--pgr": "战双帕弥什",
    "--pgren": "战双英文原声", "--wwoc": "综合手游OST", "--react": "音乐点评",
}

#: 知识库规则展开时的字符上限（喂给模型的精简子集；校验仍用全量规则）
RULE_TEXT_BUDGET = 14000
#: 单条例外：过短的错形（如单字母）容易误替换，直接不进规则
MIN_WRONG_LEN = 2


def _app_dir():
    """程序根目录：打包后 = exe 所在目录，源码模式 = src 的上级。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _is_self_exe(path):
    """path 是否就是本程序自身。打包后 sys.executable 指向 exe 自己，一旦被
    当成「Python 解释器」去 Popen，Windows 会拉起一个全新的主程序实例
    （表现为退出后反复重启），因此这里必须排除。"""
    if not path or not getattr(sys, "frozen", False):
        return False
    try:
        return (os.path.normcase(os.path.abspath(path)) ==
                os.path.normcase(os.path.abspath(sys.executable)))
    except Exception:  # noqa: BLE001
        return False


def resolve_python():
    """解析可用的 Python 解释器：tools\\python 内嵌运行时 → 系统 python。

    找不到返回 ""（调用方据此给出明确错误），**绝不回退到自身 exe**。
    """
    embedded = os.path.join(_app_dir(), "tools", "python", "python.exe")
    if os.path.isfile(embedded):
        return embedded
    if not getattr(sys, "frozen", False) and not _is_self_exe(sys.executable):
        return sys.executable
    found = shutil.which("python") or ""
    return "" if _is_self_exe(found) else found


# ============================ 长时双语片源特化（2026-09-14）============================
# 起因：人工校准《Music Composer Reacts - Alleikhreos Boss Theme》(英语原声 + 谷翻,
# 468 cue) 时确认了两条硬事实，据此改造本 Agent：
#   ① 双语片源的**英文参考行是最强判据**——人工流程就是「对着参考行重写中文行」；
#      而旧实现 build_user_prompt 只把「序号 / 中文行」喂给模型，白白丢掉参考行。
#   ② 机翻片（尤其 reaction/直播切片）的痛点不是术语而是**跨 cue 断句**：一句英文
#      被切成 2~4 条中文，术语表修不了。旧 validate_change 明确拒绝改写 ⇒ 这类片源
#      Agent 完全无能为力，只能人工逐条重写。故新增整句重写风格。
# 长片源（2000+ cue / 双语）另有三处特化：句子边界切块、按片源命中选择规则、
# 行宽门禁（复用脚本 length 的同一判据），以及显式 workdir 下的断点续跑。

#: 校准风格：term＝只做名词级术语替换（旧默认）；rewrite＝允许整句重写中文行
CALIB_STYLES = ("term", "rewrite")
STYLE_NAME = {"term": "术语级（只替换名词）", "rewrite": "整句重写（理顺机翻）"}

#: 是否把参考行一并喂给模型（双语/多语片源建议 True；比原文长不了多少，
#: 却能把它从「盲替换」变成「有据改写」。None = 由片源模式决定）
INCLUDE_REF_MODES = ("", "--ja", "--jpe", "--ko", "--ak", "--akko", "--endo",
                     "--pgren", "--wwoc", "--react")

#: 单行显示宽度上限（汉字当量；与 subtitle_calib_merged 的 MAX_LINE_ZH 同判据：
#: 东亚 W/F/A 宽字符计 1.0、半角计 0.5，故「32 汉字」等价于「64 英文字符」）
MAX_LINE_WIDTH = 32.0
#: 重写允许的最大膨胀比与最短保护（防止模型把一行写成三段）
REWRITE_GROWTH = 1.8
REWRITE_MIN_LEN = 24
#: 句末标点（用于句子边界切块：参考行以它结尾 ⇒ 这里是天然断点）
_SENT_TAIL = ".!?…。！？：；"
_SENT_TAIL_SOFT = "\"')）】」’”"
#: 相邻 cue 时间间隙 ≥ 该毫秒数视作断点（说话人换气/换句）
_SENT_GAP_MS = 800

#: 中文行里允许出现的拉丁串（原文自带的不受此表约束；此表只用于放宽"新增拉丁"）
LATIN_ALLOW = {
    "BGM", "OST", "PV", "EP", "AI", "OK", "Boss", "boss", "Drop", "drop",
    "Mix", "mix", "Live", "live", "Vocal", "vocal", "Dubstep", "dubstep",
    "Crywolf", "YMIR", "Somniomancer", "Endmin", "Endman",
}


class CalibCancelled(Exception):
    """用户取消（关闭页面 / 再次点击校准）。"""


# ============================ 基础文本 IO ============================
_BOMS = ((b"\xef\xbb\xbf", "utf-8-sig"), (b"\xff\xfe\x00\x00", "utf-32"),
         (b"\x00\x00\xfe\xff", "utf-32"), (b"\xff\xfe", "utf-16"),
         (b"\xfe\xff", "utf-16"))


def _decode_any(raw: bytes) -> str:
    """兼容 UTF-8 / GBK / Big5 / UTF-16 的解码（与脚本同一策略）。"""
    for bom, enc in _BOMS:
        if raw.startswith(bom):
            try:
                return raw.decode(enc, errors="replace")
            except (UnicodeDecodeError, LookupError):
                break
    for enc in ("utf-8", "gb18030", "big5", "shift_jis", "latin-1"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def _read_text(path: str) -> str:
    with open(path, "rb") as f:
        return _decode_any(f.read())


def _write_text(path: str, text: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


# ============================ SRT 解析 / 回填 ============================
class Cue:
    """一条字幕：序号、时间轴行、文本行区间（含参考行）、中文行区间。"""

    __slots__ = ("num", "time_line", "zh_lines", "ref_line", "start", "end")

    def __init__(self, num, time_line, zh_lines, ref_line, start, end):
        self.num = num              # 序号（字符串，原样保留）
        self.time_line = time_line  # 时间轴行（原样，绝不改写）
        self.zh_lines = zh_lines    # 中文行列表（可能多行；单文本行 cue 为空）
        self.ref_line = ref_line    # 参考行（通常英文；原样保留）
        self.start = start          # 文本起始行索引（中文行第一行）
        self.end = end              # 文本结束行索引（不含参考行）


def parse_srt(path: str):
    """解析 SRT，返回 (lines, cues, crlf, bom)。

    只做结构识别，不改动任何字符；中文行 = 文本行里除最后一行以外的所有行
    （与 subtitle_calib_merged 的约定一致：单文本行 cue 视为无中文行，不覆盖）。
    """
    raw = open(path, "rb").read()
    crlf = b"\r\n" in raw
    bom = raw.startswith(b"\xef\xbb\xbf")
    norm = _decode_any(raw).replace("\r\n", "\n").replace("\r", "\n")
    lines = norm.split("\n")
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
                if texts:
                    cues.append(Cue(s, lines[j], texts[:-1], texts[-1],
                                    j + 1, kk - 1))
                    i = kk
                    continue
        i += 1
    return lines, cues, crlf, bom


def rebuild_srt(lines, cues, mapping: dict, crlf: bool, bom: bool) -> str:
    """按 cue 边界重建 SRT：只替换中文行，其余一字不动。

    mapping: {序号: 新中文文本}（文本内的换行用真实 "\\n"，行数须与原文一致，
    由调用方校验）。多行中文 cue 无校准文本时原样保留——重建式回填不会像
    「切片替换」那样让后续 cue 串位。
    """
    out_lines, prev = [], 0
    for cue in cues:
        out_lines.extend(lines[prev:cue.start])
        new = mapping.get(cue.num)
        if cue.zh_lines and new is not None:
            out_lines.extend(new.split("\n"))
        else:
            out_lines.extend(lines[cue.start:cue.end])
        prev = cue.end
    out_lines.extend(lines[prev:])
    body = "\n".join(out_lines)
    if crlf:
        body = body.replace("\n", "\r\n")
    return ("\ufeff" if bom else "") + body


def _protect_ref_lines(src_path: str, base_path: str) -> int:
    """基线后参考行保护：把 base 里每条 cue 的参考行强制还原为 src 的原样。

    起因（2026-09-18《NIKKE Player Reacts to Typhoeus》终末地反应片实操沉淀）：
    `--endo` 等「统一全部文本行」模式在脚本里是 `for ti in range(j+1, kk)`，
    会连英文参考行一起替换（如参考行 `Typhon`→`提弗洛斯`）；而第 [8/8] 步 verify
    硬断言「英文行 0 改动」，于是整轮校准必然以「校验未通过」中止——人工流程正是
    靠避开 `--endo`、改走 `subfix` 逐 cue 侧车只改中文行来绕开它。

    本函数在基线跑完后立即按 cue 序号对齐、把参考行还原成原始 src 的样子，机械保证
    「参考行永不改写」这条契约，不再依赖脚本模式的行为。对本就只改中文行的模式
    （bi/term 等）是 no-op（参考行本就一致，restored=0）。中文行 / 时间轴 / 序号 /
    换行 / BOM 一律不动。

    返回被还原的参考行数。
    """
    _sl, src_cues, _sc, _sb = parse_srt(src_path)
    _bl, base_cues, base_crlf, base_bom = parse_srt(base_path)
    src_ref = {c.num: c.ref_line for c in src_cues}   # cue 编号可能不连续，按序号索引
    out = list(_bl)
    restored = 0
    for c in base_cues:
        want = src_ref.get(c.num)
        if want is None:
            continue
        ref_idx = c.end                # 参考行恒在文本区间末行 = lines[kk-1] = c.end
        if 0 <= ref_idx < len(out) and out[ref_idx] != want:
            out[ref_idx] = want
            restored += 1
    if restored:
        body = "\n".join(out)
        if base_crlf:
            body = body.replace("\n", "\r\n")
        _write_text(base_path, ("\ufeff" if base_bom else "") + body)
    return restored


# ============================ 知识库 → 规则 ============================
def build_rules(entities, mode_key: str):
    """把对象级实体展开为 (错形 → 官方名) 规则与负向排除规则。

    返回 (rules, excludes, canonicals)：
      rules      [(wrong, canonical)]，按 wrong 长度降序（长优先，避免短错形
                 先替换把长错形切碎）；
      excludes   [(wrong, 正则字符串)]  命中参考行时回滚（脚本 exclude 语义）；
      canonicals 全部官方名集合（宽松校验用）。
    """
    picked = [e for e in entities if mode_key in (e.get("modes") or [])]
    # 模式键在知识库里没有对应实体（如战双走侧车表）时退化为全量，
    # 保证规则不为空；变体本身多为跨模式通用的机翻错形。
    if len(picked) < 10:
        picked = list(entities)
    rules, excludes, canonicals = {}, {}, set()
    for e in picked:
        canon = str(e.get("canonical") or "").strip()
        if not canon:
            continue
        canonicals.add(canon)
        wrongs = list(e.get("variants") or [])
        wrongs += [w for _rx, w in (e.get("ctx") or [])]
        for alt in (e.get("en"), e.get("ja"), e.get("ko")):
            alt = str(alt or "").strip()
            if alt:
                wrongs.append(alt)
        for w in wrongs:
            w = str(w or "").strip()
            if not w or w == canon or len(w) < MIN_WRONG_LEN:
                continue
            rules.setdefault(w, canon)
        for w, rx in (e.get("exclude") or []):
            w = str(w or "").strip()
            if w:
                excludes.setdefault(w, str(rx or ""))
    items = sorted(rules.items(), key=lambda kv: (-len(kv[0]), kv[0]))
    return items, sorted(excludes.items(), key=lambda kv: -len(kv[0])), canonicals


def select_rules(rules, cues, budget: int = RULE_TEXT_BUDGET):
    """按片源命中度挑选要喂给模型的规则（长片源规则可达数千条，必须挑）。

    优先级：① 错形出现在**中文行** → 必进（正是要改的）；
            ② 错形出现在**参考行** → 必进（双语片源的英文判据：这段在讲这个实体，
               让模型能把听到的英文名对上官方中文，而不是盲替换）；
            ③ 其余按原序（长键优先）补足预算。
    返回 (文本, 命中中文行的条数, 总条数)。
    """
    zh_text = "\n".join(zh for _n, zh, _e in cues)
    ref_text = "\n".join(en for _n, _zh, en in cues)
    hot, warm, rest = [], [], []
    for wrong, canon in rules:
        if wrong in zh_text:
            hot.append((wrong, canon))
        elif wrong in ref_text:
            warm.append((wrong, canon))
        else:
            rest.append((wrong, canon))
    out, used = [], 0
    for wrong, canon in hot + warm + rest:
        line = f"{wrong} → {canon}"
        if used + len(line) + 1 > budget:
            break
        out.append(line)
        used += len(line) + 1
    return "\n".join(out), len(hot), len(out)


def select_rules_for_chunk(rules, chunk, budget: int = RULE_TEXT_BUDGET):
    """块级规则裁剪（v1.16.0）：只挑「本块」命中的 hot/warm 规则。

    `select_rules` 是全片一次性筛选：长片源规则文本可达预算上限（14000 字符），
    而单个块通常只涉及少数实体，把全片规则喂给每一块是纯浪费。这里对每块单独
    裁剪：本块中文行命中的错形必进（hot），本块参考行命中的次之（warm）。
    正确性说明：证据校验（validate_change / validate_rewrite）仍用全量规则，
    裁剪只影响提示词规模，不影响改动是否被采纳；块内裁剪结果为空时提示词
    显示（空），模型自然输出 []（块内本就没有知识库可解释的错形）。
    返回 (文本, 命中本块中文行的条数)。
    """
    zh_text = "\n".join(zh for _n, zh, _e in chunk)
    ref_text = "\n".join(en for _n, _zh, en in chunk)
    hot, warm = [], []
    for wrong, canon in rules:
        if wrong in zh_text:
            hot.append((wrong, canon))
        elif wrong in ref_text:
            warm.append((wrong, canon))
    out, used = [], 0
    for wrong, canon in hot + warm:
        line = f"{wrong} → {canon}"
        if used + len(line) + 1 > budget:
            break
        out.append(line)
        used += len(line) + 1
    return "\n".join(out), len(hot)


def rule_text(rules, cues_text: str, budget: int = RULE_TEXT_BUDGET) -> str:
    """（兼容旧接口）按文本命中挑选规则片段。新代码请用 `select_rules`。"""
    return select_rules(rules, [("0", cues_text, "")], budget)[0]


# ============================ 长片源特化：行宽 / 句子边界 ============================
def char_width(ch: str) -> float:
    """东亚宽字符（W/F/A）计 1.0，其余（半角）计 0.5 —— 与校准脚本同判据。"""
    return 1.0 if unicodedata.east_asian_width(ch) in ("W", "F", "A") else 0.5


def line_width(text: str) -> float:
    """整行显示宽度（以汉字为单位）。"""
    return sum(char_width(c) for c in text)


def _parse_span(time_line: str):
    """把 "00:00:01,000 --> 00:00:02,000" 解析为 (start_ms, end_ms)；失败返回 None。"""
    m = re.search(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)",
                  time_line or "")
    if not m:
        return None
    g = [int(x) for x in m.groups()]
    return ((g[0] * 3600 + g[1] * 60 + g[2]) * 1000 + g[3],
            (g[4] * 3600 + g[5] * 60 + g[6]) * 1000 + g[7])


def _is_sentence_end(ref_line: str) -> bool:
    """参考行是否以一个完整句子收尾（句末标点，允许再跟闭合引号/括号）。"""
    s = (ref_line or "").strip()
    while s and s[-1] in _SENT_TAIL_SOFT:
        s = s[:-1].rstrip()
    return bool(s) and s[-1] in _SENT_TAIL


def _best_cut(cur, spans, backtrack: int = 4) -> int:
    """挑一个「句子边界」作为切点，返回下一块的首条下标（≥1）。

    首选「整块就是完整句子」——块末条的参考行以句末标点收尾时直接不切（cut=len）；
    否则向前回退最多 `backtrack` 条，找最后一个句末标点 / 时间间隙位置。
    """
    if cur and _is_sentence_end(cur[-1][2]):
        return len(cur)
    lo = max(1, len(cur) - backtrack)
    for idx in range(len(cur) - 1, lo - 1, -1):
        prev, nxt = cur[idx - 1], cur[idx]
        if _is_sentence_end(prev[2]):
            return idx
        if spans:
            a, b = spans.get(prev[0]), spans.get(nxt[0])
            if a and b and b[0] - a[1] >= _SENT_GAP_MS:
                return idx
    return len(cur)


def plan_chunks(cues, max_cues: int, max_chars: int, sentence_aware: bool = True,
                spans=None):
    """长片源切块：在条数/字符预算内切，并尽量回退到句子边界。

    为什么不能用纯贪心：双语片源里一句英文常跨 2~4 条 cue，机械切块会把同一句
    劈到两块，模型看不到后半句 ⇒ 中文只会被改得更碎。回退判据两条（取最靠后者）：
    ① 上一条的参考行以句末标点收尾；② 与下一条的时间间隙 ≥ _SENT_GAP_MS。
    保证每块至少 1 条、所有 cue 恰好覆盖一次、顺序不变。
    """
    if not sentence_aware:
        return _split_chunks(cues, max_cues, max_chars)
    size = lambda c: len(c[1]) + len(c[0]) + 4          # noqa: E731
    chunks, cur, chars = [], [], 0
    for cue in cues:
        ln = size(cue)
        if cur and (len(cur) >= max_cues or chars + ln > max_chars):
            cut = _best_cut(cur, spans)
            chunks.append(cur[:cut])
            cur = cur[cut:]
            chars = sum(size(c) for c in cur)
        cur.append(cue)
        chars += ln
    if cur:
        chunks.append(cur)
    return chunks


# ============================ 子进程：调用校准脚本 ============================
def run_script(python: str, script: str, args, log, cancel=None) -> tuple:
    """同步调用 subtitle_calib_merged.py 的某个子命令，返回 (rc, 输出文本)。"""
    cmd = [python, script] + [str(a) for a in args]
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        proc = subprocess.run(cmd, cwd=os.path.dirname(script), env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, encoding="utf-8", errors="replace",
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return proc.returncode, (proc.stdout or "").strip()
    except OSError as e:
        return 1, f"脚本调用失败: {e}"


# ============================ LLM 交互 ============================
SYSTEM_PROMPT = (
    "你是字幕术语校准助手。只做名词级术语校准，严格遵守：\n"
    "1) 只允许把「错形」替换成知识库里的官方名，禁止改写句子、增删语气词、"
    "调整标点、合并或拆分条目、翻译任何内容；\n"
    "2) 没有把握或未在知识库出现的，一律不要动；\n"
    "3) 条目里的第三列是原片语言的参考行，**只读**：禁止把它写进中文行、"
    "禁止翻译它、禁止用它的措辞替换已有中文；\n"
    "4) 中文行里的 [方括号标记]（如 [音乐]、[笑声]）与行首的 >> 说话人标记必须原样保留；\n"
    "5) 只输出严格 JSON 数组，元素形如 "
    '{"num":"12","new_zh":"替换后的完整中文行","reason":"错形 → 官方名"}；\n'
    "6) 没有任何改动时输出 []；不要输出解释、不要用 markdown 代码围栏。"
)

#: 整句重写风格（rewrite）：面向「机翻腔 / 跨 cue 断句」片源（如英语原声 + 谷翻的
#: reaction 片）。允许改写句子，但仍由代码侧守住硬契约（行数、标记、行宽、术语）。
REWRITE_SYSTEM_PROMPT = (
    "你是字幕校准助手，任务是把机翻（谷歌翻译等）的中文行改写成通顺、准确的中文。\n"
    "严格遵守：\n"
    "1) 只输出「中文行」的新文本；序号、时间轴、参考行一律不碰；\n"
    "2) 必须保留原行里所有 [方括号标记] 与行首的 >> 说话人标记（位置可微调，不得删除）；\n"
    "3) 术语一律用知识库里的官方名；中文行里出现「错形」必须替换成官方名，"
    "宁可不改也不能留着错形；\n"
    "4) 改写要点：理顺机翻的语序与断句，修掉代词/主宾颠倒、把被直译的虚词去掉；"
    "原句若跨越相邻条目，本轮只改自己这条，但要保证与相邻条目拼起来读得通；\n"
    "5) 单行长度控制在 32 个汉字当量以内（英文按半角计 0.5），宁可精简不要啰嗦；\n"
    "6) 不得新增原文没有的信息；不得把参考行里的专名音译进中文（知识库给了官方名的除外）；\n"
    "7) 只输出严格 JSON 数组，元素形如 "
    '{"num":"12","new_zh":"改写后的完整中文行","reason":"简述依据（如：语序理顺 / 错形→官方名）"}；\n'
    "8) 不需要改动的条目不要出现在结果里；全部无需改动时输出 []。"
)
STYLE_SYSTEM = {"term": SYSTEM_PROMPT, "rewrite": REWRITE_SYSTEM_PROMPT}


def _esc(text: str) -> str:
    """条目内的真实换行转成字面 \\n（单行传输），反斜杠先转义避免歧义。"""
    return (text or "").replace("\\", "\\\\").replace("\t", " ").replace("\n", "\\n")


def _unesc(text: str) -> str:
    """`_esc` 的逆变换（v1.16.0）：字面 \\n → 真实换行；\\\\ → \\。

    旧版断点续跑读取只做 `.replace("\\\\n", "\\n")`，与 `_esc` 的双重转义不对称：
    含真实反斜杠的文本（如 `C:\\path`）落盘后还原成 `C:\\\\path`，导致二次校准时
    参考行对不上、防回退比对失真。这里用单遍扫描同时还原两类转义，顺序天然安全。
    """
    s = text or ""
    out, i, n = [], 0, len(s)
    while i < n:
        if s[i] == "\\" and i + 1 < n:
            c = s[i + 1]
            if c == "n":
                out.append("\n")
                i += 2
                continue
            if c == "\\":
                out.append("\\")
                i += 2
                continue
        out.append(s[i])
        i += 1
    return "".join(out)


def build_user_prompt(mode_flag: str, rules_text: str, chunk, round_no: int,
                      style: str = "term", with_ref: bool = True,
                      prev_text: str = "", scope_text: str = "",
                      feedback: str = "") -> str:
    """组装单块请求：知识库片段 + 待校准条目 + 本轮约束。

    条目固定三列 `序号<TAB>中文行<TAB>参考行`（参考行可为空）：双语片源的参考行是
    最强判据，长片源上「给不给参考行」直接决定模型能不能对齐专名（2026-09-14 起默认给）。
    round_no>1 时额外注入上一轮已确认改动，防止模型在二次校准里把改对的名字改回去。
    v1.16.0：invalid/truncated 重问时经 `feedback` 注入上次失败的具体原因与
    整改要求——模型看到具体错误比笼统的「再试一次」命中率高得多。
    """
    cols = (lambda num, zh, en: f"{num}\t{_esc(zh)}\t{_esc(en)}") if with_ref \
        else (lambda num, zh, _en: f"{num}\t{_esc(zh)}")
    body = "\n".join(cols(num, zh, en) for num, zh, en in chunk)
    header = f"【片源模式】{MODE_NAME.get(mode_flag, mode_flag or '中英双语')}"
    if style == "rewrite":
        header += "｜【校准风格】整句重写（可理顺语序，但硬契约不变）"
    extra = ""
    if scope_text:
        extra += scope_text + "\n"
    if feedback:
        extra += "【上一次回复的问题（必须整改）】\n" + feedback + "\n\n"
    if round_no > 1:
        extra += ("这是第 %d 轮复查：上一轮的结果已经写回，请只挑出仍然残留的问题；"
                  "下面列出上一轮已确认的改动，**不得回退**。\n" % round_no)
    if prev_text:
        extra += "【上一轮已确认改动（只读，不得回退）】\n" + prev_text + "\n\n"
    guide = ("请输出需要修改的条目 JSON 数组（保持 \\n 转义与原文一致；"
             "new_zh 必须是完整的整条中文行）。" if style == "term" else
             "请输出需要改写的条目 JSON 数组（new_zh 是改写后的完整整条中文行，"
             "保持 \\n 转义与原文行数一致）。")
    return (header + "\n" + extra
            + "【术语知识库（错形 → 官方名）】\n" + (rules_text or "（空）") + "\n\n"
            + ("【待校准条目（每行三列：序号<TAB>中文行<TAB>参考行(原片语言，只读)）】\n"
               if with_ref else
               "【待校准条目（每行：序号<TAB>中文行；\\n 表示该条内的换行）】\n")
            + body + "\n\n" + guide)


def parse_changes(raw: str):
    """从模型回复里解析改动列表；返回 (changes, status)。

    status 三态，区分「正常无改动」与「真的没拿到数据」：
      "ok"＝拿到完整 JSON 数组（空数组 []＝这块无需改动，正常）；
      "truncated"＝数组未闭合，疑似被 max_tokens 截断；
      "invalid"＝空回复或 JSON 损坏，无法采信。
    """
    if not raw:
        return [], "invalid"
    s = raw.strip()
    if "```" in s:                      # 容忍代码围栏
        segs = [x.strip() for x in s.split("```")]
        for seg in segs:
            if seg.startswith("json"):
                seg = seg[4:].strip()
            if seg.startswith("["):
                s = seg
                break
    start = s.find("[")
    if start < 0:
        return [], "invalid"   # 连 "[" 都没有：拒绝语/错误页，不是截断
    depth = 0
    for i in range(start, len(s)):
        if s[i] == "[":
            depth += 1
        elif s[i] == "]":
            depth -= 1
            if depth == 0:
                try:
                    data = json.loads(s[start:i + 1])
                except ValueError:
                    fixed = _repair_json(s[start:])
                    if not fixed:
                        return [], "invalid"
                    return fixed, "ok"
                return (data if isinstance(data, list) else []), "ok"
    repaired = _repair_json(s[start:])
    if repaired:
        return repaired, "ok"   # 尾部半条被丢弃，完整部分照常采纳
    return [], "truncated"


def _repair_json(bad: str):
    """内置 JSON 抢救器（v1.16.0）：对未闭合/半坏的数组尽力修复，修不出返回 []。

    旧版依赖可选第三方库 json_repair，未安装时截断数组的完整前半段会被整体
    丢弃、再花一整轮拆块重问。这里内置等价的核心策略，零依赖：
      1) 逐条抢救：扫描顶层对象的配对（正确处理字符串内的引号/转义/嵌套），
         每拿到一个完整对象就解析入列；尾部残缺记录直接丢弃——
         宁可少改不可错改（对标 Harness：错误反馈也是接口的一部分）；
      2) 单条解析失败再做轻度修补（单引号、未转义的真实换行、尾逗号）。
    """
    if not bad:
        return []
    s = bad.strip()
    if s.startswith("["):
        s = s[1:].lstrip()

    def _loads_obj(t: str):
        t = t.strip().rstrip(",").strip()
        if not t:
            return None
        for cand in (t, t.replace("'", '"'),
                     t.replace("\r", "").replace("\n", "\\n")):
            try:
                v = json.loads(cand)
            except ValueError:
                continue
            if isinstance(v, dict):
                return v
        return None

    out, depth, start = [], 0, -1
    in_str = esc = False
    for i, ch in enumerate(s):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            if depth == 0:
                start = i
            depth += 1
        elif ch in "}]":
            if depth:
                depth -= 1
                if depth == 0 and start >= 0:
                    v = _loads_obj(s[start:i + 1])
                    if v is not None:
                        out.append(v)
                    start = -1
    return out


# ============================ 改动校验（证据链） ============================
def _candidates(old: str, hits, limit: int = 60):
    """用命中的规则穷举「把错形换成官方名」的结果集合（限定规模）。"""
    results = {old}
    stack = [old]
    while stack and len(results) < limit:
        cur = stack.pop()
        for wrong, canon in hits:
            if wrong in cur and wrong != canon:
                nxt = cur.replace(wrong, canon)
                if nxt not in results:
                    results.add(nxt)
                    stack.append(nxt)
    return results


def _diff_segments(old: str, new: str):
    """返回 (替换掉的片段列表, 新写入的片段列表)。"""
    import difflib
    sm = difflib.SequenceMatcher(None, old, new, autojunk=False)
    olds, news = [], []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("replace", "delete"):
            olds.append(old[i1:i2])
        if tag in ("replace", "insert"):
            news.append(new[j1:j2])
    return olds, news


def validate_change(old: str, new: str, rules, excludes, canonicals,
                    ref_line: str = "") -> tuple:
    """校验一处改动是否合法，返回 (是否接受, 依据说明, 是否疑似新错形)。

    判定顺序：
      1) 结构：空文本、行数变化 → 直接拒绝（保证「格式一字不动」）；
      2) 命中负向排除（替换后参考行命中正则）→ 拒绝；
      3) 知识库规则可完全解释 → 接受（依据：xx → 官方名）；
      4) 否则看差异片段：新写片段必须落在官方名上、且被替换片段足够短
         （名词级）→ 接受并标记「疑似新错形，建议 learn 沉淀」；
      5) 其余一律拒绝。
    """
    if not new.strip():
        return False, "校准后为空", False
    if new.count("\n") != old.count("\n"):
        return False, "行数与原文不符（会改动格式）", False
    if new == old:
        return False, "与原文相同", False
    # 规则命中（长错形优先）
    hits = [(w, c) for w, c in rules if w in old and w != c]
    if hits:
        cands = _candidates(old, hits, limit=60)
        if new in cands:
            used = [f"{w} → {c}" for w, c in hits if w not in new and c in new]
            detail = "；".join(dict.fromkeys(used)) or "按知识库规则替换"
            for w, rx in excludes:
                if w in old and rx:
                    try:
                        if re.search(rx, ref_line or ""):
                            return False, f"命中负向排除（{w} /{rx}/）", False
                    except re.error:
                        pass
            return True, detail, False
    olds, news = _diff_segments(old, new)
    if not news:
        return False, "无可识别改动", False
    if any(len(x) > 16 for x in olds):
        return False, "改动跨度过大（非名词级）", False
    joined = "".join(news)
    if len(joined) > 40:
        return False, "新增文本过多（疑似改写）", False
    hit_canon = [c for c in canonicals if c in joined]
    if hit_canon and all(len(x) <= 12 for x in olds):
        return True, "疑似新错形 → " + "、".join(hit_canon[:3]) + "（建议 learn 沉淀）", True
    return False, "无知识库依据且未落在官方名上", False


# ---- 整句重写模式的证据校验（2026-09-14 新增）----
_RE_LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z0-9'’\-]*")
_RE_TAG_ANY = re.compile(r"\[[^\[\]]{0,24}\]")
_RE_LEAD_GT = re.compile(r"^\s*>>+\s*")


def validate_rewrite(old: str, new: str, rules, excludes, canonicals,
                     ref_line: str = "", width_limit: float = MAX_LINE_WIDTH):
    """整句重写（rewrite）模式的证据校验：允许改写，但硬契约一条都不能破。

    与 `validate_change`（名词级）的区别：不再要求「改动能被知识库完全解释」
    （机翻腔的语序调整本来就没有对应规则），改为逐条断言「没有破坏什么」：
      1) 结构：空文本 / 行数变化 / 与原文相同 → 拒绝；
      2) 行首 `>>` 与所有 `[方括号标记]` 必须在（位置可微调，不得少）；
      3) 原文命中的错形不得残留在结果里（必须换成官方名）；
      4) 原文已有的官方名（长度 ≥2）不得被改坏；
      5) 行宽 ≤ `width_limit` 汉字当量（超了就是写太长，直接拒）；
      6) 长度膨胀 ≤ REWRITE_GROWTH 且受 REWRITE_MIN_LEN 保护（防注水）；
      7) 新增的拉丁串只允许是知识库里的官方英文名（防塞英文 / 私自音译）；
      8) 命中负向排除 → 回滚。
    返回 (是否接受, 依据说明, 是否提示人工复核)。
    """
    if not new.strip():
        return False, "改写后为空", False
    if new.count("\n") != old.count("\n"):
        return False, "行数与原文不符（会改动格式）", False
    if new == old:
        return False, "与原文相同", False

    for tag in _RE_TAG_ANY.findall(old):            # 2) 标记保护
        if tag not in new:
            return False, f"丢失标记 {tag}", False
    if _RE_LEAD_GT.match(old) and not _RE_LEAD_GT.match(new):
        return False, "丢失行首 >> 说话人标记", False

    hits = [(w, c) for w, c in rules if w in old and w != c]
    kept = [f"{w} → {c}" for w, c in hits if w in new and c not in new]
    if kept:                                        # 3) 错形不得残留
        return False, "残留错形未替换（" + "、".join(kept[:3]) + "）", False

    lost = [c for c in canonicals if len(c) >= 2 and c in old and c not in new]
    if lost:                                        # 4) 已有官方名不得改坏
        return False, "改坏了官方名（" + "、".join(lost[:3]) + "）", False

    w = max((line_width(x) for x in new.split("\n")), default=0.0)
    if w > width_limit:                             # 5) 行宽
        return False, f"改写后行宽 {w:.1f} 超过 {width_limit:.0f} 汉字当量", False

    if len(new) > max(REWRITE_MIN_LEN, int(len(old) * REWRITE_GROWTH)):
        return False, f"改写后长度 {len(new)} 相对原文 {len(old)} 膨胀过大", False

    allow = set(LATIN_ALLOW) | {c for c in canonicals if _RE_LATIN_WORD.fullmatch(c or "")}
    known = set(_RE_LATIN_WORD.findall(old)) | {c for c in canonicals if c in old}
    for tok in dict.fromkeys(_RE_LATIN_WORD.findall(new)):   # 7) 不得新增拉丁
        if tok in known or tok in allow:
            continue
        return False, f"新增了原文没有的拉丁词 {tok!r}", False

    for w0, rx in excludes:                          # 8) 负向排除
        if w0 in old and rx:
            try:
                if re.search(rx, ref_line or ""):
                    return False, f"命中负向排除（{w0} /{rx}/）", False
            except re.error:
                pass

    used = [f"{w2} → {c2}" for w2, c2 in hits if c2 in new]
    why = "整句重写"
    if used:
        why += "（" + "；".join(list(dict.fromkeys(used))[:3]) + "）"
    return True, f"{why}｜行宽 {w:.1f}", False


# ============================ 主流程 ============================
def _log_do(log, msg, level="dim"):
    try:
        log(msg, level)
    except TypeError:
        log(msg)


def calibrate(src: str, out: str = None, report: str = None, mode_flag: str = "",
              fix_en: bool = False, script: str = None, python: str = None,
              log=None, chat=None, chunk_cues: int = 120, max_chars: int = 6000,
              max_tokens: int = 8192, baseline: bool = True, round_no: int = 1,
              workdir: str = None, cancel=None, style: str = "term",
              resume_from: str = None, prev_changes=None, include_ref=None,
              sentence_aware: bool = True, strict_width: bool = False,
              checkpoint: bool = True,
              thinking: bool = True,
              concurrency: int = 1,
              learn_kb: str = None,
              context_tokens: int = 1000000) -> dict:
    """Agent 级 AI 校准主流程（详见模块 docstring）。

    baseline=True 时先跑术语脚本得到基线（推荐：机械部分零成本且必定正确）；
    round_no>1 表示「再次校准」，提示词会要求只挑残留问题，并注入 prev_changes
    防止把上轮已改对的再改回去；长片源第二轮务必用 resume_from 指向上轮产物，
    否则从原始源重跑基线会丢掉上一轮已采纳的改动。

    style="term"      只做名词级术语替换（旧行为，默认）
    style="rewrite"   允许整句重写中文行（机翻腔 / 跨 cue 断句片源专用）
    resume_from       起点文件（优先于脚本基线）
    prev_changes      [(num, old, new), ...] 上轮已确认改动，注入提示词禁止回退
    include_ref       None=按片源模式自动决定；是否把参考行一并喂给模型
    sentence_aware    分块时回退到句子边界（长双语片源建议 True）
    strict_width      行宽超限即判失败（默认只报告、不阻断）
    checkpoint        显式 workdir 下每块落盘进度，支持断点续跑
    thinking          v1.14.2：把模型思考链（推理模型返回的 reasoning_content）
                      实时打进校准日志（level="think"）；chat 回调不支持时自动忽略
    concurrency       v1.16.0：逐块 LLM 调用的并发路数（默认 1＝串行，行为与
                      旧版一致）。只并发「取回模型提议」这一步，证据校验与
                      合并仍在主线程按块序串行执行，结果与 ckpt 落盘顺序确定
    learn_kb          v1.15.1：学习库路径，交给收尾的 learn 沉淀用；
                      None = 脚本默认（cwd 下的 subtitle_learned_kb.json）。
                      **自检必须显式传临时库**，否则测试数据会写进真实知识库。
    context_tokens    v1.15.4：可用**上下文预算**（默认 1M token）。片源档案按
                      它的 1/4 折算采样上限 ⇒ 默认等于全量投喂字幕；输出额度
                      （max_tokens）默认 65536，端点不接受时会自动减半重试。
    """
    t0 = time.time()
    log = log or (lambda m, level="dim": None)
    if chat is None:
        raise ValueError("calibrate 需要注入 chat(prompt, system, max_tokens) 回调")
    if style not in CALIB_STYLES:
        style = "term"
    script = script or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), SCRIPT_NAME)
    if not os.path.isfile(script):
        return {"ok": False, "error": f"校准脚本缺失：{script}"}
    if not python or _is_self_exe(python):              # 兜底：内嵌运行时 → 系统 python
        python = resolve_python()
    if not python:
        return {"ok": False, "error": "未找到可用的 Python 运行时"
                                      "（AI 校准需要 tools\\python 或系统已安装 python）"}

    def _tick():
        if cancel is not None and cancel():
            raise CalibCancelled()

    def _think(txt):
        """模型思考链 → 校准日志：首行带 [思考] 前缀，余行缩进续排。"""
        for i, ln in enumerate(str(txt).splitlines()):
            _log_do(log, ("[思考] " if i == 0 else "        ") + ln, "think")

    tmp = workdir or tempfile.mkdtemp(prefix="vt_calib_ai_")
    os.makedirs(tmp, exist_ok=True)
    stem = os.path.splitext(out or src)[0]
    if out is None:
        out = os.path.splitext(src)[0] + ".calib.srt"
    report = report or (os.path.splitext(out)[0] + ".ai.md")
    result = {"ok": False, "out": out, "report": report, "script_changes": 0,
              "ai_changes": 0, "rejected": 0, "round": round_no, "error": "",
              "accepted": [], "rejected_items": [], "seconds": 0.0,
              "style": style, "width_over": 0, "width_widest": ("", ""),
              "manual_check": [], "resumed_from": "", "chunks": 0,
              "rules_injected": 0, "rules_hot": 0, "suggest_rewrite": False,
              "meta": {}, "learn": {},
              "concurrency": max(1, int(concurrency or 1))}
    try:
        # ---------- 1. 起点：上一轮结果（可选）或术语脚本基线 ----------
        base = src
        if resume_from and os.path.isfile(resume_from):
            base = resume_from
            result["resumed_from"] = resume_from
            _log_do(log, "[1/8] 以上一轮结果为新起点（跳过脚本基线）："
                         f"{os.path.basename(resume_from)}", "ok")
        elif baseline:
            _tick()
            _log_do(log, f"[1/8] 术语脚本基线（{'第 %d 轮' % round_no if round_no > 1 else '机械校准'}）…")
            base = os.path.join(tmp, "base.srt")
            base_md = os.path.join(tmp, "base.md")
            args = [src, "--out", base, "--report", base_md]
            if mode_flag:
                args.append(mode_flag)
            if fix_en:
                args.append("--fix-en")
            rc, text = run_script(python, script, args, log, cancel)
            for line in text.splitlines():
                if line.strip():
                    _log_do(log, "  · " + line.strip())
            if rc != 0 or not os.path.isfile(base):
                result["error"] = f"术语脚本基线失败（退出码 {rc}）"
                return result
            m = re.search(r"（(\d+) 处文本改动", text)
            result["script_changes"] = int(m.group(1)) if m else 0
            _log_do(log, f"  → 脚本基线完成：{result['script_changes']} 处改动", "ok")

        # 参考行不变量：无论 base 来自脚本基线还是上轮产物，参考行必须等于原始源。
        # --endo 等「统一全部文本行」模式会连英文参考行一起替换，在此机械纠正。
        _protect = _protect_ref_lines(src, base)
        if _protect:
            _log_do(log, f"  → 参考行保护：还原 {_protect} 条被基线误改的参考行", "ok")

        # ---------- 2. 抽取 cue 表 ----------
        _tick()
        _log_do(log, "[2/8] 抽取 cue 表（剥离时间轴/序号结构）…")
        cues_tsv = os.path.join(tmp, "cues.tsv")
        rc, text = run_script(python, script, ["extract", base, cues_tsv],
                              log, cancel)
        if rc != 0 or not os.path.isfile(cues_tsv):
            result["error"] = "抽取 cue 表失败"
            return result
        cues = []
        for ln in _read_text(cues_tsv).splitlines()[1:]:
            if not ln.strip():
                continue
            parts = ln.split("\t")
            if len(parts) < 2:
                continue
            zh = parts[1].replace("\\n", "\n")
            en = parts[2] if len(parts) > 2 else ""
            cues.append((parts[0].strip(), zh, en))
        if not cues:
            result["error"] = "cue 表为空（字幕可能没有可校准的中文行）"
            return result
        _log_do(log, f"  → 共 {len(cues)} 条 cue", "ok")

        # ---------- 3. 载入知识库 ----------
        _tick()
        mode_key = MODE_KEY.get(mode_flag, "bi")
        _log_do(log, f"[3/8] 载入对象级术语知识库（模式 {mode_key}）…")
        kb_json = os.path.join(tmp, "kb.json")
        rc, text = run_script(python, script,
                              ["kb-export", "--json", "--out", kb_json], log, cancel)
        entities = []
        if rc == 0 and os.path.isfile(kb_json):
            try:
                entities = json.loads(_read_text(kb_json))
            except ValueError:
                entities = []
        rules, excludes, canonicals = build_rules(entities, mode_key)
        _log_do(log, f"  → 实体 {len(entities)} 个 → 规则 {len(rules)} 条，"
                     f"官方名 {len(canonicals)} 个，排除 {len(excludes)} 条", "ok")

        # ---------- 4. 自主分块（长片源回退句子边界）+ 规则筛选 ----------
        _tick()
        spans = {}
        try:                       # 时间间隙是「句子边界」的第二个判据
            for c in parse_srt(base)[1]:
                sp = _parse_span(c.time_line)
                if sp:
                    spans[c.num] = sp
        except Exception:          # noqa: BLE001 时间轴解析失败不影响主流程
            spans = {}
        chunks = plan_chunks(cues, chunk_cues, max_chars,
                             sentence_aware=sentence_aware, spans=spans or None)
        result["chunks"] = len(chunks)
        _log_do(log, f"[4/8] 分块完成：{len(chunks)} 块"
                     f"（每块 ≤{chunk_cues} 条 / ≤{max_chars} 字符；"
                     f"{'句子边界对齐' if sentence_aware else '纯贪心'}）")
        _all_txt, hot_n, rule_n = select_rules(rules, cues)
        result["rules_injected"], result["rules_hot"] = rule_n, hot_n
        _log_do(log, f"  → 知识库片段全片命中 {rule_n} 条"
                     f"（其中 {hot_n} 条命中本片中文行）；逐块只注入该块命中的"
                     f"规则（v1.16.0 块级裁剪），校验仍用全量 {len(rules)} 条")
        if include_ref is None:
            include_ref = mode_flag in INCLUDE_REF_MODES
        _log_do(log, f"  → 携带参考行：{'是' if include_ref else '否'}"
                     f"；风格 {STYLE_NAME.get(style, style)}"
                     + (f"；注入上轮已确认改动 {len(prev_changes)} 条（禁止回退）"
                        if prev_changes else ""))

        # ---------- 5~6. 逐块调用 + 证据校验（长片源带断点续跑）----------
        accepted, rejected = {}, []
        ckpt_path = (os.path.join(workdir, "ckpt.tsv")
                     if (workdir and checkpoint) else None)
        done_path = (os.path.join(workdir, "ckpt.done")
                     if (workdir and checkpoint) else None)
        done_blocks = set()
        if done_path and os.path.isfile(done_path):
            done_blocks = {ln.strip() for ln in _read_text(done_path).splitlines()
                           if ln.strip().isdigit()}
        if ckpt_path and os.path.isfile(ckpt_path):
            try:
                for ln in _read_text(ckpt_path).splitlines():
                    p = ln.split("\t")
                    if len(p) >= 4 and p[0].strip().isdigit():
                        accepted[p[0].strip()] = _unesc(p[3])
                _log_do(log, f"  ⟲ 断点续跑：载入既有进度 {len(done_blocks)} 块 / "
                             f"{len(accepted)} 条改动（{os.path.basename(ckpt_path)}）",
                        "ok")
            except Exception:      # noqa: BLE001 进度文件损坏就重跑
                accepted = {}
                done_blocks = set()
        prev_text = ""
        if prev_changes:
            prev_text = "\n".join(
                "%s\t%s\t%s" % (n, _esc(o), _esc(x))
                for n, o, x in list(prev_changes)[:200])
        n_chunks = len(chunks)
        failed_blocks = 0          # 经重试仍无可信结果的块数（停止判定用）
        traj_path = os.path.join(tmp, "trajectory.log")

        def _traj(line):
            """逐轮轨迹（可观测性）：每块开始/结束带时间戳落盘，中断可回溯。"""
            if not checkpoint:
                return
            try:
                with io.open(traj_path, "a", encoding="utf-8") as f:
                    f.write(f"[{time.strftime('%H:%M:%S')}] {line}\n")
            except OSError:
                pass

        # 收集待处理块（断点续跑 / 上轮已完成的直接跳过）
        pending = []
        for idx, chunk in enumerate(chunks, 1):
            first, last = chunk[0][0], chunk[-1][0]
            if accepted and all(c[0] in accepted for c in chunk):
                _log_do(log, f"[5/8] 第 {idx}/{n_chunks} 块（{first}–{last}）"
                             f"已在上轮完成，跳过")
                continue
            if str(idx) in done_blocks:
                _log_do(log, f"[5/8] 第 {idx}/{n_chunks} 块（{first}–{last}）"
                             f"已处理过，跳过（断点续跑）")
                continue
            pending.append((idx, chunk))

        all_zh = {num: zh for num, zh, _e in cues}      # ckpt 全量列修复：
        all_ref = {num: en for num, _zh, en in cues}    # 旧版只按当前块回填
        # zh/ref 列，断点续跑载入的旧条目会被写成空列，二次续跑后对不上。

        def _merge_changes(chunk, changes):
            """证据校验 + 合并（主线程串行执行，顺序确定；v1.16.0 自逐块循环拆出）。"""
            old_map = {num: zh for num, zh, _e in chunk}
            ref_map = {num: en for num, _zh, en in chunk}
            for item in changes:
                if not isinstance(item, dict):
                    rejected.append(("?", str(item)[:40], "返回元素不是对象"))
                    continue
                num = str(item.get("num") or item.get("index") or "").strip()
                # 模型按约定用字面 \n 表示条内换行，这里还原为真实换行
                new = str(item.get("new_zh") or item.get("text") or "").strip()
                new = new.replace(chr(92) + "n", "\n")
                if num not in old_map:
                    rejected.append((num or "?", new, "序号不在本块内"))
                    continue
                old = old_map[num]
                if num in accepted:            # 同一 cue 已收过，后到覆盖
                    old = accepted[num]
                if style == "term":
                    ok, why, soft = validate_change(old, new, rules, excludes,
                                                    canonicals, ref_map.get(num, ""))
                else:
                    ok, why, soft = validate_rewrite(old, new, rules, excludes,
                                                     canonicals, ref_map.get(num, ""))
                if ok:
                    accepted[num] = new
                    result["accepted"].append((num, old_map[num], new, why, soft))
                else:
                    rejected.append((num, new, why))

        def _save_ckpt(idx):
            """断点落盘（主线程）：zh/ref 用全量映射，避免续跑旧条目写空列。"""
            if not ckpt_path:
                return
            try:
                _write_text(ckpt_path, "num\tzh\tref\tnew\n" + "".join(
                    "%s\t%s\t%s\t%s\n" % (n, _esc(all_zh.get(n, "")),
                                          _esc(all_ref.get(n, "")), _esc(v))
                    for n, v in sorted(accepted.items(),
                                       key=lambda kv: int(kv[0])
                                       if kv[0].isdigit() else 0)))
                done_blocks.add(str(idx))
                _write_text(done_path,
                            "\n".join(sorted(done_blocks, key=int)) + "\n")
            except Exception:          # noqa: BLE001 进度写盘失败不影响主流程
                pass

        def _run_block(job):
            """取回一个块的模型提议（并发时在工作线程执行；校验合并不在这里）。

            规则文本按块级裁剪（select_rules_for_chunk）；`_ask_block` 内部
            二分拆块时沿用父块的规则文本（是子块的超集，正确性无损）。
            """
            idx, chunk = job
            _tick()                    # 取消检查（线程内）：调用接口前先看一眼
            first, last = chunk[0][0], chunk[-1][0]
            rules_txt_i, _hot_i = select_rules_for_chunk(rules, chunk)
            scope = (f"【本块范围】全长 {len(cues)} 条中的第 {idx}/{n_chunks} 块"
                     f"（序号 {first}–{last}）；只处理本块条目。")
            changes, block_fail = _ask_block(chat, mode_flag, rules_txt_i, chunk,
                                             round_no, max_tokens, log, _tick,
                                             style=style, with_ref=include_ref,
                                             prev_text=prev_text, scope_text=scope,
                                             think=(_think if thinking else None))
            return idx, chunk, changes, block_fail

        conc = result["concurrency"]
        if conc > 1:
            _log_do(log, f"  → 并发调用：{conc} 路（只并发取回提议，"
                         f"校验合并仍按块序串行）", "ok")
        for bi in range(0, len(pending), conc):
            batch = pending[bi:bi + conc]
            _tick()
            for idx, chunk in batch:
                first, last = chunk[0][0], chunk[-1][0]
                _log_do(log, f"[5/8] 第 {idx}/{n_chunks} 块"
                             f"（{len(chunk)} 条，{first}–{last}）…")
                _traj(f"block {idx}/{n_chunks} cues={first}-{last} start")
            if conc <= 1:
                results = [_run_block(job) for job in batch]
            else:
                # pool.map：按块序回收结果；任一 worker 抛取消异常会向上传播
                #（其余 worker 因 cancel 已置位会在下一次 _tick 快速退出）
                with ThreadPoolExecutor(max_workers=conc) as pool:
                    results = list(pool.map(_run_block, batch))
            for idx, chunk, changes, block_fail in results:
                first, last = chunk[0][0], chunk[-1][0]
                if block_fail:
                    failed_blocks += 1
                _traj(f"block {idx}/{n_chunks} cues={first}-{last} done "
                      f"changes={len(changes)}{' FAILED' if block_fail else ''}")
                _merge_changes(chunk, changes)
                _save_ckpt(idx)        # 每块落盘：长片源中断后可续跑
                _log_do(log, f"  → 累计采纳 {len(accepted)} 处，拒绝 {len(rejected)} 处",
                        "ok" if accepted else "dim")

        # ---------- 停止条件（异常分支）：多数块拿不到可信结果 → 本轮不可信 ----------
        # Harness 设计要点：不能等模型「自报完成」就照常产出；接口持续故障时，
        # 宁可整轮失败让用户检查接口后重跑，也不写一份静默漏改的产物。
        if failed_blocks and (failed_blocks == n_chunks
 or (failed_blocks >= 3 and failed_blocks * 3 >= n_chunks)):
            result["error"] = (
                f"AI 接口持续异常：{failed_blocks}/{n_chunks} 块经重试仍未取得有效结果，"
                f"本轮校准不可信，已在合并写盘前中止（未生成输出）。"
                f"请在设置中检查 AI 接口连通性与额度后重试。")
            _log_do(log, "  ✗ " + result["error"], "err")
            return result
        if failed_blocks:
            _log_do(log, f"  ⚠ {failed_blocks}/{n_chunks} 块因接口异常按无改动跳过"
                         f"（未达中止阈值，可「再次校准」补跑）", "err")

        result["ai_changes"] = len(accepted)
        result["rejected"] = len(rejected)
        result["rejected_items"] = rejected
        # 「机器判不准、值得人工看一眼」的拒绝项（长片源收尾复核用）
        _soft_keys = ("跨度", "新增文本", "无知识库依据", "行宽", "膨胀",
                      "残留错形", "拉丁", "改坏")
        result["manual_check"] = [r for r in rejected
                                  if any(k in r[2] for k in _soft_keys)][:80]

        # 风格改派建议（2026-09-18 实操沉淀）：term 风格下，若模型反复提出
        # 整句重写却被名词级校验大面积挡回（跨度过大/新增文本），说明本片是机翻腔
        # （如谷翻反应片），术语级校准改不动。当轮就提醒改用 rewrite 风格再跑一轮，
        # 而不是让用户翻报告才发现 ai_changes ≈ 0。
        result["suggest_rewrite"] = False
        if style == "term" and rejected:
            _rw_keys = ("跨度", "新增文本", "无知识库依据")
            _rw_n = sum(1 for r in rejected if any(k in r[2] for k in _rw_keys))
            if _rw_n >= 6 and _rw_n >= len(accepted):
                result["suggest_rewrite"] = True
                _log_do(log, f"  ⚠ 本片疑为机翻腔：{_rw_n} 条整句重写提议被名词级校验挡回"
                             f"（仅采纳 {len(accepted)} 处）。建议改用 rewrite 风格（整句重写）"
                             f"重跑一轮，或人工确认后逐条覆盖。", "err")

        # ---------- 7. 合并回填 ----------
        _tick()
        _log_do(log, "[7/8] 合并回填（只替换中文行，结构一字不动）…")
        lines, srt_cues, crlf, bom = parse_srt(base)
        mapping = {}
        skipped = 0
        for cue in srt_cues:
            if cue.num in accepted and cue.zh_lines:
                new = accepted[cue.num]
                if new.count("\n") != len(cue.zh_lines) - 1:
                    skipped += 1
                    continue
                mapping[cue.num] = new
        body = rebuild_srt(lines, srt_cues, mapping, crlf, bom)
        _write_text(out, body)
        if skipped:
            _log_do(log, f"  · {skipped} 条因行数不一致被回滚（保持原样）", "err")
        # 校准表存档（便于人工复盘 / learn 沉淀）
        tsv = os.path.join(tmp, "calib_AI.tsv")
        _write_text(tsv, "num\tnew_zh\n" + "".join(
            f"{k}\t{v}\n" for k, v in sorted(mapping.items(), key=lambda kv: int(kv[0])
                                             if kv[0].isdigit() else 0)))
        _log_do(log, f"  → 已写入 {out}（采纳 {len(mapping)} 处）", "ok")

        # ---------- 8. 独立校验 ----------
        _tick()
        _log_do(log, "[8/8] 独立校验（脚本 verify：序号/时间轴/英文行/换行/BOM）…")
        rc, text = run_script(python, script, ["verify", src, out], log, cancel)
        for line in text.splitlines():
            if line.strip():
                _log_do(log, "  · " + line.strip())
        if rc != 0 or "VERIFY OK" not in text:
            result["error"] = "校验未通过：时间轴/序号/格式可能被改动，已中止"
            _log_do(log, "  ✗ 校验未通过，输出文件仅供排查", "err")
            return result
        _log_do(log, "  ✓ 校验通过：仅中文行变化", "ok")

        # ---------- 8b. 行宽体检（脚本 length，与排版线同一判据）----------
        # verify 只断言「结构未变」，不查行宽；整句重写最容易把中文行写长，
        # 故长片源收尾必须再过一道（脚本侧 length 超限退出码 1，与这里判据一致）。
        _tick()
        rc, text = run_script(python, script, ["length", out], log, cancel)
        m = re.search(r"内容行超限 (\d+) 处", text)
        result["width_over"] = int(m.group(1)) if m else 0
        m2 = re.search(r"最宽内容行 ([\d.]+): (.*)", text)
        if m2:
            result["width_widest"] = (m2.group(1), m2.group(2))
        if result["width_over"]:
            _log_do(log, f"  ⚠ 行宽超限 {result['width_over']} 处"
                         f"（>{MAX_LINE_WIDTH:.0f} 汉字当量），已记入报告", "err")
            if strict_width:
                result["error"] = f"行宽体检未通过：{result['width_over']} 处超限"
                return result
        else:
            _log_do(log, f"  ✓ 行宽体检通过（最宽 {result['width_widest'][0] or '—'} / "
                         f"{MAX_LINE_WIDTH:.0f} 汉字当量）", "ok")

        # ---------- 9. 片源档案与学习沉淀（v1.15.1）----------
        # 「再次校准」除校准字幕外还要给出：官方中文核对 / 脚本沉淀建议 /
        # 10 个 tag / 中文标题。这些都是**附加产出**：取消或失败都不能让
        # 已经校验通过的字幕白跑，故一律吞掉异常、只记日志。
        try:
            _tick()
            # v1.15.4：这里**不能**再把 max_tokens 压到 4096 —— 推理模型
            # （deepseek-flash / reasoner 等）会先吐思考链，4096 常被思考吃光、
            # 正文为空（finish_reason=length），片源档案整段落空（报告里
            # 「四、官方中文核对」「五、脚本沉淀建议」全显示「无」，
            # 用户完全看不出是失败还是真没有）。实测同片源：4096 必失败；
            # 8192 正常产出标题 / 10 个 tag / 官方中文 / 脚本建议四段。
            result["meta"] = build_meta(chat, mode_flag, src, cues,
                                        result["accepted"], log, round_no,
                                        max_tokens=max_tokens,
                                        think=_think if thinking else None,
                                        context_tokens=context_tokens)
        except CalibCancelled:
            _log_do(log, "  片源档案已取消（字幕结果不受影响）", "err")
        except Exception as e:  # noqa: BLE001
            _log_do(log, f"  ⚠ 片源档案异常（不影响校准结果）：{e}", "err")
        if result["accepted"] or result["script_changes"]:
            try:
                _tick()
                result["learn"] = run_learn(python, script, src, out, mode_flag,
                                            log, cancel, kb=learn_kb)
            except CalibCancelled:
                _log_do(log, "  学习沉淀已取消（字幕结果不受影响）", "err")
            except Exception as e:  # noqa: BLE001
                _log_do(log, f"  ⚠ 学习沉淀异常：{e}", "err")

        # 报告
        _write_report(report, src, out, mode_flag, round_no, result, rules)
        result["ok"] = True
        result["seconds"] = round(time.time() - t0, 1)
        _log_do(log, f"AI 校准完成（第 {round_no} 轮）：脚本 {result['script_changes']} 处"
                     f" + AI {result['ai_changes']} 处，拒绝 {result['rejected']} 处，"
                     f"耗时 {result['seconds']}s", "ok")
        _log_do(log, f"报告：{report}")
        return result
    except CalibCancelled:
        result["error"] = "已取消"
        _log_do(log, "已取消 AI 校准", "err")
        return result
    except Exception as e:  # noqa: BLE001
        result["error"] = f"{type(e).__name__}: {e}"
        _log_do(log, f"AI 校准异常：{result['error']}", "err")
        return result
    finally:
        if workdir is None:
            try:                                  # 清理临时目录（保留产物）
                import shutil
                shutil.rmtree(tmp, ignore_errors=True)
            except Exception:  # noqa: BLE001
                pass


def _split_chunks(cues, max_cues: int, max_chars: int):
    """按 cue 条数与字符预算切块（两项任一超限即切）。"""
    chunks, cur, chars = [], [], 0
    for cue in cues:
        ln = len(cue[1]) + len(cue[0]) + 4
        if cur and (len(cur) >= max_cues or chars + ln > max_chars):
            chunks.append(cur)
            cur, chars = [], 0
        cur.append(cue)
        chars += ln
    if cur:
        chunks.append(cur)
    return chunks


def _ask_block(chat, mode_flag, rules_txt, chunk, round_no, max_tokens, log, tick,
               style="term", with_ref=True, prev_text="", scope_text="",
               attempt=0, think=None, feedback=""):
    """请模型判定一个块的改动，返回 (changes, hard_fail)。

    失败处理策略（2026-09-15 对标 DeepSeek Harness 的异常分支 / 资源上限同步优化）：
      · ok        拿到完整数组（含 []＝无需改动）→ 直接采纳，绝不再误拆；
      · invalid   空响应 / 解析不出：先**原块重问一次**（多为偶发抽风，成本最低、
                  命中最高）；重问仍坏 → 该块按「无改动」跳过并记失败，
                  **不再无谓二分**——旧版会把一次接口抖动放大成 log2(N) 层拆块、
                  把积分烧在注定失败的调用上；
      · truncated 数组未闭合：第一反应改为**加倍 max_tokens 重问一次**（截断多半
                  只是输出预算不够），仍截断才二分拆块（保留「读不完→拆分→合并」
                  的自主能力）；单条仍截断则跳过该条。
    hard_fail = 本块（含全部拆出的子块）都没拿到可信结果，供上层做停止判定。
    v1.16.0：重问时经 `feedback` 把上次失败原因与整改要求写进提示词
    （build_user_prompt 组装），而不是干巴巴地重发同一份请求。
    """
    system = STYLE_SYSTEM.get(style, SYSTEM_PROMPT)
    raw = ""
    err = ""
    prompt = build_user_prompt(mode_flag, rules_txt, chunk, round_no,
                               style=style, with_ref=with_ref,
                               prev_text=prev_text, scope_text=scope_text,
                               feedback=feedback)
    try:
        if think is not None:
            # v1.14.2：把模型思考链经 think(text) 上报到校准日志；回调方
            # （如自检的 fake_chat）不认识 on_reasoning 时抛 TypeError →
            # 退回普通调用，行为与旧版一致。
            try:
                raw = chat(prompt, system, max_tokens=max_tokens,
                           on_reasoning=think)
            except TypeError:
                raw = chat(prompt, system, max_tokens=max_tokens)
        else:
            raw = chat(prompt, system, max_tokens=max_tokens)
    except Exception as e:  # noqa: BLE001
        err = str(e)[:120]
        _log_do(log, f"  ! 该块调用失败：{err}", "err")
    changes, status = parse_changes(raw)
    if status == "ok":
        return changes, False

    if attempt == 0:
        # 第一次失败先原地重问（truncated 时已自动加倍输出预算；invalid 用原预算）；
        # v1.16.0：附上失败原因与整改要求——反馈也是接口的一部分。
        tick()
        if status == "truncated":
            feedback = ("上一次回复因输出过长被截断。整改要求：reason 一句话即可；"
                        "无需改动的条目一律不要输出；只输出需要修改的条目；"
                        "严格保持 JSON 数组完整闭合。")
            _log_do(log, f"  ! 返回被截断，原地重问一次（{len(chunk)} 条，"
                         f"输出预算加倍，已附整改要求）", "err")
        else:
            feedback = ("上一次回复未取得有效 JSON 数组"
                        + (f"（{err}）" if err else "")
                        + "。整改要求：只输出严格 JSON 数组本身——不要任何解释、"
                          "不要 markdown 代码围栏；元素形如 "
                          '{"num":"12","new_zh":"...","reason":"..."}；'
                          "无需改动时输出 []。")
            _log_do(log, f"  ! 未取到有效 JSON，原地重问一次（{len(chunk)} 条，"
                         f"已附整改要求）", "err")
        return _ask_block(chat, mode_flag, rules_txt, chunk, round_no,
                          # 加倍上限 512K（2026-09-20 配合设置页「输出」512K）；
                          # 旧版硬卡 65536 会把用户大额度配置在截断重问时打回 64K
                          min(max_tokens * 2, 524288) if status == "truncated"
                          else max_tokens,
                          log, tick, style, with_ref, prev_text, scope_text, 1,
                          think, feedback)

    if status == "invalid":
        _log_do(log, "  ✗ 重问后仍未取得有效结果，该块按无改动跳过"
                     + (f"（{err}）" if err else ""), "err")
        return [], True
    if len(chunk) <= 1:
        _log_do(log, "  ! 单条加倍后仍被截断，跳过该条", "err")
        return [], True
    tick()
    half = max(1, len(chunk) // 2)
    _log_do(log, f"  ! 重问仍被截断，拆为 {half}+{len(chunk) - half} 分块重试", "err")
    a, fa = _ask_block(chat, mode_flag, rules_txt, chunk[:half], round_no,
                       max_tokens, log, tick, style, with_ref, prev_text,
                       scope_text, 0, think)
    b, fb = _ask_block(chat, mode_flag, rules_txt, chunk[half:], round_no,
                       max_tokens, log, tick, style, with_ref, prev_text,
                       scope_text, 0, think)
    return a + b, (fa and fb)


# ============================ 第 9 步：片源档案（v1.15.1）============================
# 用户要求（2026-09-19）：「再次校准」除校准字幕外，还要
#   ① 检索官方中文  ② 基于改动优化脚本  ③ 总结 10 个 tag  ④ 给出合适的中文标题。
# 其中 ② 由脚本现成的 `learn` 子命令机械承担（有频次门槛，安全）；
# ①③④ 由一次 LLM 调用产出。全部写进**同一份**校准报告（多轮复写，不堆文件）。
#: tag 个数（用户指定）
META_TAG_COUNT = 10
#: 投喂模型的字幕采样上限（**未给上下文预算时的默认值**；v1.15.4 起按
#: `context_tokens` 放大——默认 1M token 预算下基本等于全量投喂）
META_SAMPLE_CUES = 150
META_SAMPLE_CHARS = 12000
#: 单 token 约合字符数（中英混排的保守估计），用于把上下文 token 预算
#: 换算成「可喂入的字幕字符数」。
CHARS_PER_TOKEN = 2.0
#: 单次输出额度的硬上限（防呆）。用户要求「按模型最大值」，这里给足空间；
#: 端点不接受时程序会按错误类型自动减半重试。
MAX_OUT_TOKENS = 1000000


def meta_sample_budget(context_tokens):
    """把「上下文 token 预算」换算成片源档案的采样上限。

    只动用预算的 1/4（其余留给提示词骨架、规则文本与输出），默认 1M token
    ⇒ 上限 25 万条 cue / 50 万字符，对任何正常片源都等于**全量投喂**。
    """
    n = int(context_tokens or 0)
    if n <= 0:
        return META_SAMPLE_CUES, META_SAMPLE_CHARS
    return (max(META_SAMPLE_CUES, n // 4),
            max(META_SAMPLE_CHARS, int(n * CHARS_PER_TOKEN / 4)))


def _budget_error_kind(msg):
    """调用失败是否与输出额度有关：'exhausted'（额度被思考链吃光，需更大）/
    'too_big'（端点不接受这么大的值，需更小）/ ''（与额度无关）。"""
    m = str(msg or "").lower()
    if ("思考" in m or "finish_reason=length" in m or "截断" in m
            or "truncat" in m):
        return "exhausted"
    if "max_tokens" in m or "max tokens" in m:
        return "too_big"
    if "too large" in m or "exceeds" in m or "范围" in m or "超出" in m:
        return "too_big"
    return ""

META_SYSTEM = (
    "你是资深的中日英游戏文案与直播视频本地化专家，熟悉鸣潮、明日方舟、"
    "明日方舟：终末地、战双帕弥什等作品的官方简体中文译名与社区常用叫法。"
    "只输出一个 JSON 对象，不要任何解释，不要代码块围栏。"
)


def _sample_cues(cues, max_n: int = META_SAMPLE_CUES,
                 max_chars: int = META_SAMPLE_CHARS):
    """均匀采样 cue：首尾必取，保证模型既看到开场也看到收尾。"""
    if len(cues) <= max_n:
        picked = list(cues)
    else:
        step = len(cues) / float(max_n)
        picked = [cues[min(int(i * step), len(cues) - 1)] for i in range(max_n)]
    out, used = [], 0
    for n, zh, en in picked:
        ln = len(zh) + len(en) + 8
        if used + ln > max_chars:
            break
        used += ln
        out.append((n, zh, en))
    return out


def _meta_prompt(mode_flag, src, sample_text, accepted, round_no, tag_count):
    """片源档案的提示词。"""
    accepted_text = "\n".join(
        f"- {str(o)[:40]} → {str(n)[:40]}" for _num, o, n, *_ in accepted[:80]
    ) or "（本轮无改动）"
    mode_key = MODE_KEY.get(mode_flag, "bi")
    return f"""下面是某视频字幕（已机翻 / 已校准）的内容采样，每行三列：
序号<TAB>中文行<TAB>原声参考行。

片源文件：{os.path.basename(src)}
片源模式：{MODE_NAME.get(mode_flag, mode_flag or '中英双语')}（模式键 {mode_key}）
本轮轮次：第 {round_no} 轮

【字幕采样】
{sample_text}

【本轮已采纳的改动】
{accepted_text}

【要做的四件事】
1. title —— 给这个视频起一个准确的**简体中文标题**：≤30 字，紧扣内容；
   不要书名号，不要“震惊/必看”这类营销词；作品专名用官方写法。
2. tags —— 正好 {tag_count} 个**简体中文标签**，覆盖「作品 / 角色 / 内容类型 /
   主题」四个维度；每个 2~8 字；互不重复；不要带 # 号。
3. official_terms —— 从采样里挑出**疑似非官方译名 / 机翻误译**的专有名词，
   给出该作品**公认的官方简体中文**写法。
   ⚠ 严禁编造：有把握的 confidence 填 "high"；拿不准的填 "low"，
   并在 note 里说明为什么拿不准——宁可少列，也不要虚构官方译名。
4. script_suggestions —— 其中值得沉淀进校准脚本术语表的条目，给出
   wrong（错形）/ right（官方名）/ mode（片源模式键）/ evidence（依据，如 cue 序号）。
   mode 拿不准就填 "{mode_key}"。

【输出格式：严格 JSON，直接以 {{ 开头】
{{"title": "…", "tags": ["…"], "official_terms": [{{"term": "…", "official": "…", "confidence": "high", "note": "…"}}], "script_suggestions": [{{"wrong": "…", "right": "…", "mode": "bi", "evidence": "…"}}]}}
"""


def _parse_meta_json(raw: str) -> dict:
    """从模型回复里抠出片源档案对象（容忍代码围栏与前后废话）。"""
    if not raw:
        return {}
    s = raw.strip()
    if "```" in s:
        for seg in s.split("```"):
            seg = seg.strip()
            if seg.startswith("json"):
                seg = seg[4:].strip()
            if seg.startswith("{"):
                s = seg
                break
    a, b = s.find("{"), s.rfind("}")
    if a < 0 or b <= a:
        return {}
    for cand in (s[a:b + 1], s[a:b + 1].replace("'", '"')):
        try:
            v = json.loads(cand)
        except ValueError:
            continue
        if isinstance(v, dict):
            return v
    return {}


def build_meta(chat, mode_flag, src, cues, accepted, log, round_no=1,
               max_tokens=65536, think=None, context_tokens=1000000) -> dict:
    """第 9 步：产出片源档案（中文标题 / 10 个 tag / 官方中文核对 / 脚本沉淀建议）。

    这是**附加产出**：任何失败都只记日志、不阻断校准（不能让整轮白跑）。
    """
    empty = {"title": "", "tags": [], "official_terms": [], "script_suggestions": []}
    _log_do(log, "[9/9] 片源档案：中文标题 / tag / 官方中文核对 / 脚本沉淀建议…")
    try:
        sample = _sample_cues(cues, *meta_sample_budget(context_tokens))
        sample_text = "\n".join(f"{n}\t{zh}\t{en}" for n, zh, en in sample)
        prompt = _meta_prompt(mode_flag, src, sample_text, accepted, round_no,
                              META_TAG_COUNT)
        # 输出额度自适应（v1.15.4）：推理模型会先吐**思考链**，额度被吃光时
        # 正文为空（finish_reason=length）；而部分端点又不接受过大的
        # max_tokens（直接报参数错）。故按失败类型自适应调整：
        # 额度耗尽 → 翻倍；参数超限 → 减半；直到拿到合法 JSON。
        cur = int(max_tokens or 0) or 65536
        tried, obj, last = set(), {}, ""
        for _ in range(6):
            if cur in tried or cur < 256:
                break
            tried.add(cur)
            try:
                try:
                    raw = chat(prompt, META_SYSTEM, max_tokens=cur,
                               on_reasoning=think)
                except TypeError:             # chat 回调不支持 on_reasoning
                    raw = chat(prompt, META_SYSTEM, max_tokens=cur)
            except Exception as _e:            # noqa: BLE001
                last = str(_e)[:180]
                _log_do(log, f"  ⚠ 片源档案调用失败（max_tokens={cur}）：{last}",
                        "err")
                _kind = _budget_error_kind(last)
                if _kind == "exhausted":
                    cur = min(cur * 2, MAX_OUT_TOKENS)
                    _log_do(log, f"  ↻ 额度被思考链吃光，以 max_tokens={cur} 重试…")
                    continue
                if _kind == "too_big":
                    cur //= 2
                    _log_do(log, f"  ↻ 端点不接受该额度，以 max_tokens={cur} 重试…")
                    continue
                break                          # 与额度无关，重试无意义
            obj = _parse_meta_json(raw)
            if obj:
                last = ""
                break
            last = "模型未返回合法 JSON（多为输出被截断）"
            _nxt = min(cur * 2, MAX_OUT_TOKENS)
            _log_do(log, f"  ↠ max_tokens={cur} 下未取得合法 JSON，"
                         f"加大到 {_nxt} 重试…")
            cur = _nxt
        if not obj:
            _log_do(log, f"  ⚠ 片源档案未生成：{last}", "err")
            return dict(empty, _error=last or "未取得有效 JSON")
        meta = {
            "title": str(obj.get("title") or "").strip(),
            "tags": [str(t).strip().lstrip("#") for t in (obj.get("tags") or [])
                     if str(t).strip()][:META_TAG_COUNT],
            "official_terms": [x for x in (obj.get("official_terms") or [])
                               if isinstance(x, dict)][:60],
            "script_suggestions": [x for x in (obj.get("script_suggestions") or [])
                                   if isinstance(x, dict)][:60],
        }
        if meta["title"]:
            _log_do(log, f"  ✓ 中文标题：{meta['title']}", "ok")
        if meta["tags"]:
            _log_do(log, f"  ✓ tag（{len(meta['tags'])} 个）："
                         + " / ".join(meta["tags"]), "ok")
        if meta["official_terms"]:
            _log_do(log, f"  ✓ 官方中文核对：{len(meta['official_terms'])} 条")
        if meta["script_suggestions"]:
            _log_do(log, f"  ✓ 脚本沉淀建议：{len(meta['script_suggestions'])} 条")
        return meta
    except Exception as e:  # noqa: BLE001
        _log_do(log, f"  ⚠ 片源档案生成失败（不影响校准结果）：{e}", "err")
        return dict(empty, _error=str(e)[:180])


def run_learn(python, script, src, out, mode_flag, log, cancel=None,
              kb: str = None) -> dict:
    """把「源 → 本轮产物」投喂给脚本的 learn 子命令，让新错形沉淀进学习库。

    learn 自带频次门槛（count>=2 且无反例才 confirmed 自动生效），所以自动调用
    是安全的：它只"提候选"，不会立刻乱改术语表。这也是「基于改动优化脚本」的
    落点——校准发现的错形不再只躺在报告里，而是进了可复用的知识库。

    :param kb: 学习库路径；None = 脚本默认（cwd 下的 subtitle_learned_kb.json）。
               **自检必须显式传临时库**，否则测试数据会写进真实知识库
               （2026-09-19 踩过：测试用的「卡西亚→卡提希娅」被 confirmed 进真库）。
    """
    mode_key = MODE_KEY.get(mode_flag, "bi")
    _log_do(log, f"[学习] 沉淀本轮新错形（learn --mode {mode_key}）…")
    try:
        args = ["learn", src, out, "--mode", mode_key]
        if kb:
            args += ["--kb", kb]
        rc, text = run_script(python, script, args, log, cancel)
        tail = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
        for ln in tail[-6:]:
            _log_do(log, "  · " + ln)
        return {"ok": rc == 0, "mode": mode_key, "kb": kb or "",
                "output": "\n".join(tail[-8:])}
    except Exception as e:  # noqa: BLE001
        _log_do(log, f"  ⚠ 学习沉淀失败（不影响校准结果）：{e}", "err")
        return {"ok": False, "mode": mode_key, "kb": kb or "", "output": str(e)}


def _write_report(path, src, out, mode_flag, round_no, result, rules) -> None:
    """写 AI 校准报告（markdown）：采纳明细 + 拒绝明细 + 行宽体检 + 人工复核清单。

    长片源（2000+ cue / 双语）报告额外记录分块方式、规则注入规模与断点续跑起点，
    便于事后复盘「这次为什么这么改」以及下一轮 resume。
    """
    widest = result.get("width_widest") or ("", "")
    lines = [f"# AI 校准报告（第 {round_no} 轮）", "",
             f"- 源文件：`{src}`",
             f"- 输出文件：`{out}`",
             f"- 片源模式：{MODE_NAME.get(mode_flag, mode_flag or '中英双语')}",
             f"- 校准风格：{STYLE_NAME.get(result.get('style', 'term'), '术语级（只替换名词）')}",
             f"- 时间：{time.strftime('%Y-%m-%d %H:%M:%S')}"]
    if result.get("suggest_rewrite"):
        lines += ["", "> ⚠ **本片疑为机翻腔**：多条整句重写提议被名词级校验挡回。"
                  "建议改用 `rewrite` 风格（整句重写）重跑一轮。"]
    if result.get("resumed_from"):
        lines.append(f"- 起点：以上轮结果 `{result['resumed_from']}` 为输入（未重跑脚本基线）")
    lines += [
        f"- 改动：术语脚本 {result['script_changes']} 处 + AI {result['ai_changes']} 处；"
        f"拒绝 {result['rejected']} 处",
        f"- 分块：{result.get('chunks') or '—'} 块；注入知识库片段 "
        f"{result.get('rules_injected') or 0} 条（其中 {result.get('rules_hot') or 0} 条命中本片）",
        "- 校验：序号 / 时间轴 / 英文行 / 换行 / BOM 全部一致（脚本 verify 通过）",
        f"- 行宽体检：超限 {result.get('width_over') or 0} 处；最宽内容行 "
        f"{widest[0] or '—'} / {MAX_LINE_WIDTH:.0f} 汉字当量"]
    # v1.15.1：片源档案（中文标题 / tag / 学习沉淀），写在同一份报告里
    meta = result.get("meta") or {}
    if meta.get("title"):
        lines.append(f"- **中文标题**：{meta['title']}")
    if meta.get("tags"):
        lines.append("- **标签**：" + " / ".join(meta["tags"]))
    learn = result.get("learn") or {}
    if learn.get("mode"):
        lines.append(f"- 学习沉淀：`learn --mode {learn['mode']}` "
                     + ("已投喂（新错形进入候选库，达频次门槛后自动生效）"
                        if learn.get("ok") else "未成功，详见日志"))
    lines += ["", "## 一、AI 采纳明细（仅中文行变化）", "",
              "| 序号 | 原文 | 校准后 | 依据 |", "| --- | --- | --- | --- |"]
    for num, old, new, why, soft in result["accepted"]:
        tag = ("⚠ " if soft else "") + why.replace("|", "/").replace("\n", "⏎")
        lines.append(f"| {num} | {old.replace('|', '/').replace(chr(10), '⏎')} | "
                     f"{new.replace('|', '/').replace(chr(10), '⏎')} | {tag} |")
    lines += ["", "## 二、被拒绝的模型提议", ""]
    if result["rejected_items"]:
        lines += ["| 序号 | 模型提议 | 拒绝原因 |", "| --- | --- | --- |"]
        for num, new, why in result["rejected_items"]:
            lines.append(f"| {num} | {str(new)[:60].replace('|', '/')} | {why} |")
    else:
        lines.append("（无）")
    manual = result.get("manual_check") or []
    lines += ["", "## 三、建议人工复核（机器判不准、值得看一眼）", ""]
    if manual:
        lines += ["| 序号 | 模型提议 | 拒绝原因 |", "| --- | --- | --- |"]
        for num, new, why in manual[:40]:
            lines.append(f"| {num} | {str(new)[:60].replace('|', '/')} | {why} |")
        lines += ["", "> 多为语序/断句层面的改写被规则挡下：若原行确实是机翻腔，"
                      "改用 `rewrite` 风格（整句重写）再跑一轮，或人工确认后逐条覆盖。"]
    else:
        lines.append("（无）")

    # 四、官方中文核对（v1.15.1）
    terms = meta.get("official_terms") or []
    lines += ["", "## 四、官方中文核对", ""]
    if terms:
        lines += ["| 字幕里的写法 | 建议官方中文 | 把握 | 说明 |",
                  "| --- | --- | --- | --- |"]
        for t in terms:
            conf = {"high": "高", "mid": "中", "low": "低 ⚠"}.get(
                str(t.get("confidence") or "").lower(),
                str(t.get("confidence") or "—"))
            lines.append(
                f"| {str(t.get('term') or '').replace('|', '/')} "
                f"| {str(t.get('official') or '').replace('|', '/')} "
                f"| {conf} | {str(t.get('note') or '').replace('|', '/')} |")
        lines += ["", "> ⚠ 本表由模型基于自身知识给出，**不是实时联网检索**："
                      "「把握」为低的行请人工核对官方来源后再采纳。"]
    else:
        # v1.15.4：区分「真的没有」与「本轮没生成」——后者把原因写出来，
        # 免得用户看到一片「无」却不知道是失败（实测踩过：推理模型思考链
        # 耗尽 max_tokens，整段落空）。
        _err = str(meta.get("_error") or "")
        lines.append("（**本轮未生成片源档案**：%s）" % _err if _err
                     else "（无——未发现疑似非官方译名）")

    # 五、脚本沉淀建议（v1.15.1）
    sugg = meta.get("script_suggestions") or []
    lines += ["", "## 五、脚本沉淀建议（可追加进术语表）", ""]
    if sugg:
        lines += ["| 错形 | 应改为 | 模式 | 依据 |", "| --- | --- | --- | --- |"]
        for s in sugg:
            lines.append(
                f"| {str(s.get('wrong') or '').replace('|', '/')} "
                f"| {str(s.get('right') or '').replace('|', '/')} "
                f"| {str(s.get('mode') or '').replace('|', '/')} "
                f"| {str(s.get('evidence') or '').replace('|', '/')} |")
        lines += ["", "> 本轮已自动把「源 → 产物」投喂给 `learn` 沉淀候选；"
                      "达频次门槛（≥2 且无反例）后自动生效。"
                      "上表是模型建议，采纳前请核对官方来源。"]
    else:
        _err = str(meta.get("_error") or "")
        lines.append("（**本轮未生成片源档案**：%s）" % _err if _err else "（无）")

    lines += ["", "## 六、备注", "",
              "- 标 ⚠ 的条目是知识库尚未收录的疑似新错形，建议用 "
              "`learn` 子命令沉淀进学习库后再次校准。",
              "- 行宽超限的条目（若有）只是提示：它意味着这一行在播放器里会偏长，"
              "`strict_width=True` 可让超限直接判失败。",
              "- 长片源第二轮建议带 `resume_from=<本轮输出>`：以上轮为起点继续，"
              "并把本轮采纳明细作为 `prev_changes` 传入以防回退。",
              "- 本报告不改变时间轴与格式：SRT 的序号 / 时间轴 / 英文行 / "
              "空行 / 换行 / BOM 均由校验脚本逐条断言。"]
    _write_text(path, "\n".join(lines) + "\n")
