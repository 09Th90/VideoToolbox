# -*- coding: utf-8 -*-
# @version 2.7.0
"""下载字幕「滚动式重叠」整理（v2.3.1 拆分工程 · 自 video_toolbox.py 原样搬入）。

行为契约：只把每条压到「下一条的起始」；文本/起始/序号/空行/换行风格/BOM 原样。
"""
import codecs
import os
import re

from core.shared.textio import decode_bytes_any


# ========== 下载字幕的「滚动式重叠」整理（v1.13.7） ==========
# 平台（YouTube 等）给出的自动字幕是**滚动**结构：同一条的结束时间会一直延伸
# 到"下一条的结束"，于是整份字幕大面积互相压住（实测某 3566 条的字幕里有
# 3028 条与下一条重叠，占比 84.9%）。后果是播放时同一时刻两条并行、切轴抖动，
# 后续翻译与打轴也跟着错乱。
#
# 整理方式只有一件事：把每条压到"下一条的起始"。文本、起始时间、序号、空行、
# 换行风格（CRLF/LF）、BOM 全部原样保留 —— 实测这样处理后的结果与用户手工整理
# 出来的"正确字幕"逐条一致（3566/3566）。
_SRT_TL_RE = re.compile(
    r"^(?P<pre>[ \t]*)(?P<t1>\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})"
    r"(?P<sep>[ \t]*-->[ \t]*)"
    r"(?P<t2>\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})(?P<post>.*)$")
_SRT_TS_RE = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})([,.])(\d{1,3})")

#: 判定"滚动式字幕"的门槛：重叠占比 + 重叠条数 + 最少条数。
#: 保守取值，避免误伤"双人对话/双语对齐"这类**有意**重叠的普通字幕。
_ROLLING_RATIO = 0.15
_ROLLING_MIN_OVERLAP = 4
_ROLLING_MIN_CUES = 8


def srt_time_to_ms(text):
    """`00:01:02,345` / `00:01:02.345` → 毫秒；解析不了返回 None。"""
    m = _SRT_TS_RE.search(str(text or ""))
    if not m:
        return None
    h, mi, s, _dot, frac = m.groups()
    return (int(h) * 3600 + int(mi) * 60 + int(s)) * 1000 + int(frac.ljust(3, "0"))


def ms_to_srt_time(ms, sep=",", frac=3):
    """毫秒 → `00:01:02,345`；`frac` 保留原文件的小数位数。"""
    ms = max(0, int(ms))
    h, rem = divmod(ms, 3600000)
    mi, rem = divmod(rem, 60000)
    s, f = divmod(rem, 1000)
    digits = ("%03d" % f)[:frac].ljust(frac, "0")
    return "%02d:%02d:%02d%s%s" % (h, mi, s, sep, digits)


def normalize_rolling_srt(path, dry_run=False, stats=None):
    """把「滚动式」字幕整理成不重叠的常规 SRT（原地改写）；命中则返回 True。

    只改**结束时间**。判定门槛见 `_ROLLING_*`：只有大范围重叠才动手，
    条数太少或只是零散重叠的文件原样不动（那多半是有意的重叠）。

    `dry_run=True` 时只判断、不落盘（返回"本来会改"），供体检工具用；
    `stats` 传 dict 会填进 cues / overlaps / ratio / fixed 便于报告。
    任何异常都吞掉并返回 False —— 整理失败绝不能影响"下载已成功"这个事实。
    """
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError:
        return False
    if not raw:
        return False
    bom = raw.startswith(codecs.BOM_UTF8)
    text = decode_bytes_any(raw)
    if "\r\n" in text:
        nl, text = "\r\n", text.replace("\r\n", "\n")
    elif "\r" in text:
        nl, text = "\r", text.replace("\r", "\n")
    else:
        nl = "\n"

    lines = text.split("\n")
    cues = []      # (行号, 起始 ms, 结束 ms, 结束列起, 结束列止, 分隔符, 小数位)
    for i, line in enumerate(lines):
        m = _SRT_TL_RE.match(line)
        if not m or m.group("pre"):
            # 行首要空格的（缩进）一律不认：真时间轴行都从第 0 列开始，
            # 这样也不会误伤正好长成时间轴的**正文**
            continue
        start_ms = srt_time_to_ms(m.group("t1"))
        end_ms = srt_time_to_ms(m.group("t2"))
        if start_ms is None or end_ms is None:
            continue
        sep = "," if "," in m.group("t2") else "."
        frac = len(m.group("t2").split(sep)[-1])
        cues.append((i, start_ms, end_ms,
                     m.start("t2"), m.end("t2"), sep, frac))

    n = len(cues)
    if stats is not None:
        stats["cues"] = n
    if n < _ROLLING_MIN_CUES:
        if stats is not None:
            stats.update(overlaps=0, ratio=0.0, fixed=0)
        return False
    overlaps = sum(1 for k in range(n - 1) if cues[k][2] > cues[k + 1][1])
    if stats is not None:
        stats.update(overlaps=overlaps, ratio=overlaps / float(n - 1))
    if overlaps < _ROLLING_MIN_OVERLAP:
        if stats is not None:
            stats["fixed"] = 0
        return False
    if overlaps / float(n - 1) < _ROLLING_RATIO:
        if stats is not None:
            stats["fixed"] = 0
        return False

    edits = []     # (行号, 起列, 止列, 新文本)
    for k in range(n - 1):
        line_no, start_ms, end_ms, c0, c1, sep, frac = cues[k]
        next_start = cues[k + 1][1]
        if next_start <= start_ms or end_ms <= next_start:
            continue          # 起始倒挂 / 本来就不重叠：不动
        edits.append((line_no, c0, c1, ms_to_srt_time(next_start, sep, frac)))
    if stats is not None:
        stats["fixed"] = len(edits)
    if not edits:
        return False
    if dry_run:
        return True

    for line_no, c0, c1, new in reversed(edits):
        lines[line_no] = lines[line_no][:c0] + new + lines[line_no][c1:]
    out = nl.join(lines)
    data = out.encode("utf-8")
    if bom:
        data = codecs.BOM_UTF8 + data

    tmp = path + ".vtnew"
    try:
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False
    return True


__all__ = [
    "srt_time_to_ms",
    "ms_to_srt_time",
    "normalize_rolling_srt",
    "_SRT_TL_RE",
    "_SRT_TS_RE",
    "_ROLLING_RATIO",
    "_ROLLING_MIN_OVERLAP",
    "_ROLLING_MIN_CUES",
]
