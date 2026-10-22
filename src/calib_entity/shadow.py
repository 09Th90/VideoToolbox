# @version 2.5.4
"""影子双跑：证明「索引预筛无损」，并量化「单遍 vs 串行」的语义分叉。

分两步，顺序不能颠倒：

1. ``verify_index_equivalence`` —— **等价性证明**
   基准 = 主脚本 ``_replace_report``（全表串行）；
   对照 = 同一套 pairs、但只应用 AC 扫出的候选键。
   两者必须逐字节一致。不一致只有一种原因：串行替换**造出了新键**
   （目标名里含有另一个错形键），使后续短键在旧引擎里被二次命中。
   这类行必须记录 ``needs_rescan``，否则「用索引替代全表扫描」不成立。

2. ``diff_onepass`` —— **语义分叉量化**
   基准 = 串行（旧）；对照 = 单遍最长优先（新，对象级目标语义）。
   差异按原因归类：cascade（目标自吞）/ overlap（重叠竞争）/ other。
   这一步产出的是「切换后会发生什么」的清单，而不是通过/失败判定。

本模块只读 srt，不写回。
"""
from __future__ import annotations

from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

from .index import ModeIndex

SAMPLE_LIMIT = 20


# ---------------------------------------------------------------- 输入


def iter_text_lines(path: str, engine) -> Iterator[Tuple[int, str]]:
    """逐行产出 srt 的文本行（跳过序号行、时间轴行、空行）。"""
    raw = open(path, "rb").read()
    text = engine._decode_any(raw).replace("\r\n", "\n").replace("\r", "\n")
    for lineno, line in enumerate(text.split("\n"), 1):
        s = line.strip().lstrip("\ufeff")
        if not s or s.isdigit() or "-->" in s:
            continue
        yield lineno, line


def _classify_reason(serial_hits: Sequence[str], terms: Dict[str, str]) -> str:
    """串行命中序列里，后面的键是否落在前面某个键的目标文本内（=自吞级联）。"""
    for i, later in enumerate(serial_hits):
        for earlier in serial_hits[:i]:
            target = terms.get(earlier, "")
            if later and later in target and later != target:
                return "cascade"
    return "overlap"


# ---------------------------------------------------------------- 第一步：等价性


def verify_index_equivalence(mode: str, srt_path: str, engine=None,
                             index: Optional[ModeIndex] = None,
                             limit: int = 0) -> dict:
    """验证「AC 预筛 + 串行顺序」与「全表串行」逐字节一致。

    返回 dict：
      lines / identical / differ / differ_ratio_pct
      needs_rescan（differ 行里，替换后出现候选集之外新键的行数）
      samples: [{lineno, before, base, candidate, serial_hits, new_keys}]
    """
    eng = engine or _engine()
    idx = index or ModeIndex.build(mode, engine=eng)
    pairs = idx.pairs
    charset = idx.charset

    lines = identical = 0
    needs_rescan = 0
    fallback_ok = 0
    samples: List[dict] = []

    for lineno, line in iter_text_lines(srt_path, eng):
        lines += 1
        if limit and lines > limit:
            lines -= 1
            break
        base = eng._replace_report(line, pairs, charset, {})
        cand = idx.candidates(line)
        got, hits = idx.replay_serial(line, only=cand)
        if got == base:
            identical += 1
            continue
        # 不一致：检查是否由「替换后产生新键」导致
        extra = idx.candidates(got) - cand
        if extra:
            needs_rescan += 1
        # 兜底：该行退回全表串行（不预筛），必须与基准一致
        got2, _ = idx.replay_serial(line)
        if got2 == base:
            fallback_ok += 1
        if len(samples) < SAMPLE_LIMIT:
            samples.append({
                "lineno": lineno,
                "before": line,
                "base": base,
                "candidate": got,
                "serial_hits": hits,
                "new_keys": sorted(extra),
                "fallback_reproduces": got2 == base,
            })

    differ = lines - identical
    if differ == 0:
        verdict = "EQUIVALENT"
    elif fallback_ok == differ:
        verdict = "EQUIVALENT_WITH_FALLBACK"
    else:
        verdict = "DIVERGED"
    return {
        "mode": mode,
        "src": srt_path,
        "lines": lines,
        "identical": identical,
        "differ": differ,
        "differ_ratio_pct": round(differ / lines * 100, 3) if lines else 0.0,
        "needs_rescan": needs_rescan,
        "fallback_ok": fallback_ok,
        "verdict": verdict,
        "samples": samples,
    }


# ---------------------------------------------------------------- 第二步：语义分叉


def diff_onepass(mode: str, srt_path: str, engine=None,
                 index: Optional[ModeIndex] = None, limit: int = 0) -> dict:
    """串行（旧）vs 单遍最长优先（新）的逐行差异量化。"""
    eng = engine or _engine()
    idx = index or ModeIndex.build(mode, engine=eng)
    pairs = idx.pairs
    charset = idx.charset
    terms = idx.terms

    lines = identical = 0
    reasons: Dict[str, int] = {}
    samples: List[dict] = []

    for lineno, line in iter_text_lines(srt_path, eng):
        lines += 1
        if limit and lines > limit:
            lines -= 1
            break
        base = eng._replace_report(line, pairs, charset, {})
        got, ms = idx.replace_longest(line)
        if got == base:
            identical += 1
            continue
        _base2, serial_hits = idx.replay_serial(line)
        reason = _classify_reason(serial_hits, terms)
        reasons[reason] = reasons.get(reason, 0) + 1
        if len(samples) < SAMPLE_LIMIT:
            samples.append({
                "lineno": lineno,
                "before": line,
                "serial": base,
                "onepass": got,
                "reason": reason,
                "serial_hits": serial_hits,
                "onepass_hits": [m[2] for m in ms],
            })

    differ = lines - identical
    return {
        "mode": mode,
        "src": srt_path,
        "lines": lines,
        "identical": identical,
        "differ": differ,
        "differ_ratio_pct": round(differ / lines * 100, 3) if lines else 0.0,
        "reasons": dict(sorted(reasons.items(), key=lambda kv: -kv[1])),
        "samples": samples,
    }


# ---------------------------------------------------------------- 报告


def render_markdown(report: dict) -> str:
    head = [
        "# 影子双跑报告",
        "",
        "模式 `%s` | 源 `%s`" % (report.get("mode"), report.get("src")),
        "",
        "| 指标 | 值 |",
        "|---|---|",
    ]
    for k in ("lines", "identical", "differ", "differ_ratio_pct",
              "needs_rescan", "fallback_ok", "verdict"):
        if k in report:
            head.append("| %s | %s |" % (k, report[k]))
    if "reasons" in report:
        head.append("")
        head.append("## 差异原因分布")
        head.append("")
        for k, v in report["reasons"].items():
            head.append("- `%s`: %d 行" % (k, v))
    if report.get("samples"):
        head += ["", "## 样例", ""]
        for s in report["samples"]:
            head.append("### 行 %s" % s["lineno"])
            head.append("")
            head.append("- 原文：`%s`" % s["before"])
            if "base" in s:
                head.append("- 全表串行：`%s`" % s["base"])
                head.append("- 索引预筛：`%s`" % s["candidate"])
                if s.get("new_keys"):
                    head.append("- 新引入键：`%s`" % "`, `".join(s["new_keys"]))
                head.append("- 回退重跑可复现：`%s`" % s.get("fallback_reproduces"))
            else:
                head.append("- 串行（旧）：`%s`" % s["serial"])
                head.append("- 单遍（新）：`%s`" % s["onepass"])
                head.append("- 原因：`%s`" % s["reason"])
                head.append("- 旧命中：`%s`" % "`, `".join(s["serial_hits"]))
                head.append("- 新命中：`%s`" % "`, `".join(s["onepass_hits"]))
            head.append("")
    return "\n".join(head)


_ENGINE = None


def _engine():
    global _ENGINE
    if _ENGINE is None:
        from .spec import load_engine
        _ENGINE = load_engine()
    return _ENGINE
