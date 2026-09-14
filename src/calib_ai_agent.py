# -*- coding: utf-8 -*-
"""AI 校准 Agent —— Agent 级字幕术语校准（v1.11.0）。

定位
====
用户开启「AI 校准」后点「开始校准」，等价于向一个 Agent 下达这样的要求：

    基于脚本 subtitle_calib_merged，校准字幕，不允许改变时间轴和格式，
    仅调整文字内容，如果一次无法读取完整，就自行拆分，最后合并。

本模块就是那个 Agent 的实现：它**不依赖 GUI**，只依赖标准库 + 注入的
LLM 对话回调，因此可被界面、命令行、自检脚本共用。

Agent 的工具与闭环（每一步都进日志）
====================================
  1. 术语脚本基线   —— 调 subtitle_calib_merged.py 跑一遍机械校准，
                       保证官方术语表命中的部分一定正确（兜底、幂等）。
  2. 抽取 cue 表     —— `extract`：把 SRT 抽成「序号 / 中文行 / 英文行」，
                       把时间轴、序号、空行等结构信息彻底剥离。
  3. 载入知识库      —— `kb-export --json`：560 个对象级实体 → 展开为
                       「错形 → 官方名」规则 + 负向排除规则。
  4. 自主分块        —— 按 cue 条数与字符预算切块；单块过大或返回被截断时
                       自动二分重试（这就是「一次读不完就自行拆分」）。
  5. 逐块 LLM 判定   —— 只允许名词级替换，输出严格 JSON。
  6. 证据校验        —— 每处改动必须能被知识库规则解释（或至少替换目标命中
                       官方名）；命中负向排除规则则回滚。无法解释的提议拒收
                       并写入报告，绝不让模型自由改写句子。
  7. 合并回填        —— 按 cue 边界重建 SRT：只替换中文行，序号 / 时间轴 /
                       英文行 / 换行 / BOM 一字不动。
  8. 独立校验        —— 再调脚本 `verify` 做第三方断言（cue 数、序号、时间轴、
                       英文行、CRLF、BOM 全一致），不通过即判失败。

「再次校准」= 以本轮输出为新输入再跑一轮（round_no+1），提示词里告知上一轮
已处理的规模，让模型专挑残留错形。

调用契约
========
    calibrate(src, out=..., report=..., mode_flag="--ko", log=..., chat=...)

    log(msg, level="dim")                 # 日志回调（GUI 投递到消息队列）
    chat(prompt, system=None, max_tokens=8192) -> str   # LLM 文本回调

返回 dict：ok / out / report / script_changes / ai_changes / rejected / round / error
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import time

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


def rule_text(rules, cues_text: str, budget: int = RULE_TEXT_BUDGET) -> str:
    """生成喂给模型的知识库片段：本文真实命中的错形优先，再按长度补齐。"""
    hit, rest = [], []
    for wrong, canon in rules:
        (hit if wrong in cues_text else rest).append((wrong, canon))
    out, used = [], 0
    for wrong, canon in hit + rest:
        line = f"{wrong} → {canon}"
        if used + len(line) + 1 > budget:
            break
        out.append(line)
        used += len(line) + 1
    return "\n".join(out)


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
    "3) 只输出严格 JSON 数组，元素形如 "
    '{"num":"12","new_zh":"替换后的完整中文行","reason":"错形 → 官方名"}；\n'
    "4) 没有任何改动时输出 []；不要输出解释、不要用 markdown 代码围栏。"
)


def build_user_prompt(mode_flag: str, rules_text: str, chunk, round_no: int) -> str:
    """组装单块请求：知识库片段 + 待校准条目（TSV：序号 / 中文行）。

    条目内的真实换行统一转成字面 ``\\n`` 以便单行传输，模型按同一约定回传。
    """
    body = "\n".join(f"{num}\t{zh.replace(chr(10), chr(92) + 'n')}"
                     for num, zh, _en in chunk)
    extra = ("这是第 %d 轮复查：上一轮的结果已经写回，请只挑出仍然残留的错形。\n"
             % round_no) if round_no > 1 else ""
    return (
        f"【片源模式】{MODE_NAME.get(mode_flag, mode_flag or '中英双语')}\n"
        f"{extra}"
        "【术语知识库（错形 → 官方名）】\n" + (rules_text or "（空）") + "\n\n"
        "【待校准条目（每行：序号<TAB>中文行；\\n 表示该条内的换行）】\n"
        + body + "\n\n"
        "请输出需要修改的条目 JSON 数组（保持 \\n 转义与原文一致，只替换术语）。"
    )


def parse_changes(raw: str):
    """从模型回复里解析改动列表；返回 (list, 是否可能被截断)。"""
    if not raw:
        return [], False
    s = raw.strip()
    truncated = not (s.rstrip().endswith("]"))
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
        return [], truncated
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
                    return [], truncated
                return (data if isinstance(data, list) else []), truncated
    return [], True


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
              workdir: str = None, cancel=None) -> dict:
    """Agent 级 AI 校准主流程（详见模块 docstring）。

    baseline=True 时先跑术语脚本得到基线（推荐：机械部分零成本且必定正确）；
    round_no>1 表示「再次校准」，提示词会要求只挑残留错形。
    """
    t0 = time.time()
    log = log or (lambda m, level="dim": None)
    if chat is None:
        raise ValueError("calibrate 需要注入 chat(prompt, system, max_tokens) 回调")
    script = script or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), SCRIPT_NAME)
    if not os.path.isfile(script):
        return {"ok": False, "error": f"校准脚本缺失：{script}"}
    if python is None:                                  # 兜底：当前解释器
        python = sys.executable

    def _tick():
        if cancel is not None and cancel():
            raise CalibCancelled()

    tmp = workdir or tempfile.mkdtemp(prefix="vt_calib_ai_")
    os.makedirs(tmp, exist_ok=True)
    stem = os.path.splitext(out or src)[0]
    if out is None:
        out = os.path.splitext(src)[0] + ".calib.srt"
    report = report or (os.path.splitext(out)[0] + ".ai.md")
    result = {"ok": False, "out": out, "report": report, "script_changes": 0,
              "ai_changes": 0, "rejected": 0, "round": round_no, "error": "",
              "accepted": [], "rejected_items": [], "seconds": 0.0}
    try:
        # ---------- 1. 术语脚本基线 ----------
        base = src
        if baseline:
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

        # ---------- 4. 自主分块 ----------
        _tick()
        chunks = _split_chunks(cues, chunk_cues, max_chars)
        _log_do(log, f"[4/8] 分块完成：{len(chunks)} 块"
                     f"（每块 ≤{chunk_cues} 条 / ≤{max_chars} 字符）")
        rules_txt = rule_text(rules, "".join(zh for _n, zh, _e in cues))
        _log_do(log, f"  → 本轮喂给模型的知识库片段 {len(rules_txt.splitlines())} 行"
                     f"（校验仍用全量 {len(rules)} 条规则）")

        # ---------- 5~6. 逐块调用 + 证据校验 ----------
        accepted, rejected = {}, []
        for idx, chunk in enumerate(chunks, 1):
            _tick()
            _log_do(log, f"[5/8] 第 {idx}/{len(chunks)} 块"
                         f"（{len(chunk)} 条，{chunk[0][0]}–{chunk[-1][0]}）…")
            changes = _ask_block(chat, mode_flag, rules_txt, chunk, round_no,
                                 max_tokens, log, _tick)
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
                ok, why, soft = validate_change(old, new, rules, excludes,
                                                canonicals, ref_map.get(num, ""))
                if ok:
                    accepted[num] = new
                    result["accepted"].append((num, old_map[num], new, why, soft))
                else:
                    rejected.append((num, new, why))
            _log_do(log, f"  → 累计采纳 {len(accepted)} 处，拒绝 {len(rejected)} 处",
                    "ok" if accepted else "dim")

        result["ai_changes"] = len(accepted)
        result["rejected"] = len(rejected)
        result["rejected_items"] = rejected

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


def _ask_block(chat, mode_flag, rules_txt, chunk, round_no, max_tokens, log, tick):
    """请模型判定一个块的改动；调用失败或返回被截断时二分重试（自主拆分）。

    截断的半截 JSON 一律丢弃，改为把块拆一半分别重问——这就是「一次读不完
    就自行拆分，最后合并」的实现。
    """
    raw = ""
    try:
        raw = chat(build_user_prompt(mode_flag, rules_txt, chunk, round_no),
                   SYSTEM_PROMPT, max_tokens=max_tokens)
    except Exception as e:  # noqa: BLE001
        _log_do(log, f"  ! 该块调用失败：{str(e)[:120]}", "err")
    changes, truncated = parse_changes(raw)
    if changes and not truncated:
        return changes
    if len(chunk) <= 1:
        return changes
    tick()
    half = max(1, len(chunk) // 2)
    _log_do(log, f"  ! {'返回被截断' if truncated else '未取到有效 JSON'}，"
                 f"拆为 {half}+{len(chunk) - half} 重试", "err")
    return (_ask_block(chat, mode_flag, rules_txt, chunk[:half], round_no,
                       max_tokens, log, tick)
            + _ask_block(chat, mode_flag, rules_txt, chunk[half:], round_no,
                         max_tokens, log, tick))


def _write_report(path, src, out, mode_flag, round_no, result, rules) -> None:
    """写 AI 校准报告（markdown）：采纳明细 + 拒绝明细，便于人工复核与 learn。"""
    lines = [f"# AI 校准报告（第 {round_no} 轮）", "",
             f"- 源文件：`{src}`",
             f"- 输出文件：`{out}`",
             f"- 片源模式：{MODE_NAME.get(mode_flag, mode_flag or '中英双语')}",
             f"- 时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
             f"- 改动：术语脚本 {result['script_changes']} 处 + AI {result['ai_changes']} 处；"
             f"拒绝 {result['rejected']} 处",
             f"- 校验：序号 / 时间轴 / 英文行 / 换行 / BOM 全部一致（脚本 verify 通过）",
             "", "## 一、AI 采纳明细（仅中文行变化）", "",
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
    lines += ["", "## 三、备注", "",
              "- 标 ⚠ 的条目是知识库尚未收录的疑似新错形，建议用 "
              "`learn` 子命令沉淀进学习库后再次校准。",
              "- 本报告不改变时间轴与格式：SRT 的序号 / 时间轴 / 英文行 / "
              "空行 / 换行 / BOM 均由校验脚本逐条断言。"]
    _write_text(path, "\n".join(lines) + "\n")
