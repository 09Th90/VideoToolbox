# @version 2.4.1
"""片源识别：标题 / 文件名 / 台词三通道，替代「只靠片内特征词」。

问题实证（2026-10-19 终末地 Si 片源）：

    文件名：Our Proxy can't be this CUTE! | Arknights: Endfield Operator Story: Si
    标题  ：同上
    台词  ：59 条里没有一个 ENDFIELD 特征词
    -> endfield_auto_markers() 返回 []  -> 片源按纯 bi 处理
    -> ENDFIELD_BI_TERMS 整表（570 条，含「操作员 -> 干员」）一条都没加载
    -> 产物 0 改动

片源身份在**标题里是显式的**，只是以前没人看。本模块把三条通道的置信度分开给，
调用方可以自己决定阈值（默认：标题/文件名命中即采信，台词只作佐证）。
"""
from __future__ import annotations

import os
import re
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

#: 作品 -> (模式, 标题/文件名关键词, 台词特征词)
#: 顺序敏感：终末地必须排在明日方舟之前（标题里两者会同时出现）。
WORK_RULES: Tuple[Tuple[str, str, Tuple[str, ...], Tuple[str, ...]], ...] = (
    ("终末地", "endobi",
     ("endfield", "终末地", "arknights: endfield", "arknights： endfield"),
     ("endfield", "终末地", "终末地工业")),
    ("鸣潮", "bi",
     ("wuthering waves", "wuwa", "鸣潮"),
     ("wuthering", "鸣潮", "resonator", "tacet")),
    ("战双帕弥什", "pgren",
     ("punishing gray raven", "战双", "pgr"),
     ("punishing", "战双", "construct")),
    ("明日方舟", "ak",
     ("arknights", "明日方舟"),
     ("rhodes island", "arknights", "originium", "operator")),
    ("塞尔达传说", "zel",
     ("zelda", "塞尔达"),
     ("zelda", "hyrule", "link")),
)


def _norm(s: str) -> str:
    """归一：小写、全角冒号转半角、压缩空白。"""
    if not s:
        return ""
    s = s.replace("：", ":").replace("｜", "|").lower()
    return re.sub(r"\s+", " ", s).strip()


def _hit(text: str, needles: Sequence[str]) -> List[str]:
    t = _norm(text)
    return [n for n in needles if _norm(n) and _norm(n) in t]


def _line_blob(lines: Optional[Iterable[str]], limit: int = 400) -> str:
    """台词池：只取前 limit 行，够判定特征词即可。"""
    if not lines:
        return ""
    out = []
    for i, ln in enumerate(lines):
        if i >= limit:
            break
        out.append(str(ln))
    return "\n".join(out)


def infer_mode(title: str = "", filename: str = "", lines: Optional[Iterable[str]] = None,
               default: str = "bi") -> dict:
    """推断片源模式。

    返回::

        {
          "mode": "endobi",
          "confidence": "high" | "medium" | "low",
          "reasons": ["标题命中 endfield", ...],
          "work": "终末地",
          "scores": {"终末地": {"title": 1, "filename": 1, "lines": 0}, ...}
        }

    置信度口径：
      high   标题或文件名命中（片源身份是显式写出来的）
      medium 台词特征词 >= 2（沿用主脚本 endfield_auto_markers 的判据）
      low    只有零散台词命中，或全部落空 -> 返回 default
    """
    title = title or ""
    filename = os.path.basename(filename or "") if filename else ""
    blob = _line_blob(lines)

    scores: Dict[str, dict] = {}
    for work, mode, title_needles, line_needles in WORK_RULES:
        t_hits = _hit(title, title_needles)
        f_hits = _hit(filename, title_needles)
        l_hits = _hit(blob, line_needles)
        scores[work] = {
            "title": len(t_hits), "filename": len(f_hits), "lines": len(l_hits),
            "mode": mode,
            "evidence": (t_hits + f_hits + l_hits)[:4],
        }

    # 1) 标题/文件名命中：按规则表顺序（终末地在明日方舟之前）取第一个
    for work, _mode, _tn, _ln in WORK_RULES:
        sc = scores[work]
        if sc["title"] or sc["filename"]:
            where = "标题" if sc["title"] else "文件名"
            return {
                "mode": sc["mode"], "confidence": "high", "work": work,
                "reasons": [f"{where}命中 {', '.join(sc['evidence'])}"],
                "scores": scores,
            }

    # 2) 台词特征词 >= 2
    for work, _mode, _tn, _ln in WORK_RULES:
        sc = scores[work]
        if sc["lines"] >= 2:
            return {
                "mode": sc["mode"], "confidence": "medium", "work": work,
                "reasons": [f"台词特征词 {sc['lines']} 个：{', '.join(sc['evidence'])}"],
                "scores": scores,
            }

    # 3) 兜底
    best = max(scores.items(), key=lambda kv: kv[1]["lines"])
    return {
        "mode": default, "confidence": "low", "work": "",
        "reasons": [f"标题/文件名无作品关键词，台词特征词不足（最高 {best[0]} {best[1]['lines']} 个）"],
        "scores": scores,
    }


def read_srt_lines(path: str) -> List[str]:
    raw = open(path, "rb").read()
    text = raw.decode("utf-8-sig", errors="replace")
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
