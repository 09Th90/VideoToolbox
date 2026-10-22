# @version 2.5.2
"""采纳报告：把 ``.calib.md`` 第四节的「官方中文核对」变成可执行补丁。

问题实证（2026-10-19 终末地 Si）：报告第四节写着

    | 操作员     | 干员     | 高 |
    | 操作员文件 | 干员档案 | 高 |

产物却 0 改动。原因是「术语级 AI 通道」只认知识库规则，报告表走的是另一条通道
（`official_terms`），两条通道之间没有回写。本模块补上这一步：

    parse_report(md)            -> [(wrong, right, confidence, note)]
    select(pairs, min_conf)     -> 只留「把握=高」且目标明确的中文条目
    apply_srt(srt, pairs)       -> 只改中文行，序号/时间轴/参考行/CRLF/BOM 原样
    emit_python(pairs, table)   -> 可直接粘进术语表的片段
"""
from __future__ import annotations

import os
import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

Pair = Tuple[str, str]

_SECTION4 = re.compile(r"^##\s*四[、.]?\s*官方中文核对")
_TABLE_ROW = re.compile(r"^\|(.+)\|\s*$")
_SEP_ROW = re.compile(r"^\|[\s\-:|]+\|\s*$")
#: 目标不明确的标记：出现即丢弃
_UNCERTAIN = ("待确认", "待查", "待考", "待官方", "未知", "?", "？", "—", "-")


def _cells(line: str) -> List[str]:
    m = _TABLE_ROW.match(line.strip())
    if not m:
        return []
    return [c.strip() for c in m.group(1).split("|")]


def parse_report(path: str) -> List[dict]:
    """解析「四、官方中文核对」表，返回全部条目（不过滤）。"""
    text = open(path, "rb").read().decode("utf-8-sig", errors="replace")
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    in_sec = False
    out: List[dict] = []
    for ln in lines:
        if _SECTION4.match(ln.strip()):
            in_sec = True
            continue
        if in_sec and ln.startswith("## "):
            break
        if not in_sec:
            continue
        if _SEP_ROW.match(ln.strip()):
            continue
        cells = _cells(ln)
        if len(cells) < 3:
            continue
        if cells[0] in ("字幕里的写法", "写法", "原文"):
            continue
        wrong, right, conf = cells[0], cells[1], cells[2]
        note = cells[3] if len(cells) > 3 else ""
        out.append({"wrong": wrong, "right": right, "confidence": conf, "note": note})
    return out


def _is_uncertain(s: str) -> bool:
    t = (s or "").strip()
    if not t:
        return True
    if t.startswith("（") or t.startswith("("):
        return True
    return any(u in t for u in _UNCERTAIN)


def select(items: Iterable[dict], min_conf: str = "高") -> Tuple[List[dict], List[dict]]:
    """筛出可执行条目。返回 (采纳, 丢弃)。"""
    keep, drop = [], []
    for it in items:
        w, r, c = it["wrong"].strip(), it["right"].strip(), it["confidence"].strip()
        if not w or not r or w == r:
            drop.append({**it, "why": "错形与目标相同或为空"})
            continue
        if _is_uncertain(r):
            drop.append({**it, "why": "目标不明确（待确认/待查/?）"})
            continue
        if min_conf == "高" and c not in ("高", "high", "HIGH"):
            drop.append({**it, "why": f"把握={c}，低于阈值「高」"})
            continue
        if len(w) < 2:
            drop.append({**it, "why": "错形过短（<2 字），裸键风险高"})
            continue
        keep.append(it)
    # 长键优先：避免「操作员」先吃掉「操作员文件」
    keep.sort(key=lambda x: len(x["wrong"]), reverse=True)
    return keep, drop


# ---------------------------------------------------------------- srt 应用


def _parse_blocks(text: str) -> List[List[str]]:
    """按空行分块，返回每个 cue 的行列表（保持原样，含空串外的所有行）。"""
    blocks, cur = [], []
    for ln in text.split("\n"):
        if ln.strip() == "":
            if cur:
                blocks.append(cur)
                cur = []
        else:
            cur.append(ln)
    if cur:
        blocks.append(cur)
    return blocks


def apply_srt(srt_path: str, pairs: Sequence[Pair], out_path: Optional[str] = None) -> dict:
    """对 srt 的**首个文本行**应用替换，结构/时间轴/参考行/CRLF/BOM 原样。"""
    raw = open(srt_path, "rb").read()
    bom = raw.startswith(b"\xef\xbb\xbf")
    body = raw[3:] if bom else raw
    crlf = b"\r\n" in body
    text = body.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")

    blocks = _parse_blocks(text)
    changed = 0
    rows = []
    for blk in blocks:
        if len(blk) < 3 or not blk[0].strip().isdigit() or "-->" not in blk[1]:
            continue
        old = blk[2]
        new = old
        for wrong, right in pairs:          # 已长键优先
            if wrong in new:
                new = new.replace(wrong, right)
        if new != old:
            blk[2] = new
            changed += 1
            rows.append((blk[0].strip(), old, new))

    # 重组：块间空行、块内换行
    rebuilt = "\n\n".join("\n".join(b) for b in blocks) + "\n"
    out_bytes = rebuilt.replace("\n", "\r\n").encode("utf-8") if crlf else rebuilt.encode("utf-8")
    if bom:
        out_bytes = b"\xef\xbb\xbf" + out_bytes

    dst = out_path or srt_path
    with open(dst, "wb") as f:
        f.write(out_bytes)
    return {
        "src": srt_path, "out": dst, "changed": changed,
        "crlf": crlf, "bom": bom, "rows": rows[:50],
    }


def emit_python(pairs: Sequence[Pair], table: str = "ENDFIELD_BI_TERMS") -> str:
    """生成可直接粘进术语表的 Python 片段。"""
    if not pairs:
        return f"# 无可采纳条目（{table}）"
    lines = [f"# --- 由 calib_entity.opt.adopt 生成（{table}）---"]
    for wrong, right in pairs:
        lines.append(f'    "{wrong}": "{right}",')
    return "\n".join(lines)
