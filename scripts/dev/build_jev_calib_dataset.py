# -*- coding: utf-8 -*-
# @version 3.2.5
"""从真实“中文字幕 → 校准字幕”配对构造 Jev 校准判定集。

用途：
  * 正例：真实配对里唯一改动是“已知错形 → 官方名”的 cue；
  * 硬负例：保留同一 old，把错形替换成同类别、另一作品的官方名，
    模拟“候选改动看起来像术语修正，实际换错了实体”；
  * 按稳定 hash 切 train/eval，eval 只用于最终报告，不参与阈值选择。

注意：calib 配对本身是规则/模型校准产物，不是人工金标；本数据集衡量的是
“Jev 是否与本地对象库的官方名一致”，不等同于真实业务精准率。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from typing import Dict, Iterable, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from calib_entity import spec as spec_mod  # noqa: E402
from calib_entity.opt import kb_scope  # noqa: E402

_CUE_RX = re.compile(
    r"(?ms)^\s*(\d+)\s*\n"
    r"(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})\s*\n"
    r"(.+?)(?=\n\s*\n\s*\d+\s*\n|\Z)")


def parse_srt(path: str) -> Dict[int, str]:
    raw = open(path, "rb").read()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]
    text = raw.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    out: Dict[int, str] = {}
    for m in _CUE_RX.finditer(text):
        num = int(m.group(1))
        body = m.group(4).strip("\n")
        if body:
            out[num] = body
    return out


def _changed_line(old: str, new: str, wrong: str, canonical: str) -> Optional[Tuple[str, str]]:
    """只取发生干净替换的那一行，避免把英文参考行塞进判定集。"""
    old_lines, new_lines = old.split("\n"), new.split("\n")
    if len(old_lines) != len(new_lines):
        return None
    for a, b in zip(old_lines, new_lines):
        if wrong in a and a.replace(wrong, canonical) == b and a != b:
            return a, b
    return None


def _work(entity) -> str:
    return kb_scope.work_of(getattr(entity, "category", "") or "")


def _why(wrong: str, canonical: str) -> str:
    return "术语校准：错形「%s」→ 官方名「%s」" % (wrong, canonical)


def _distractor(registry, entity, work: str):
    """同 kind、尽量异作品、长度接近的对象，作为错误目标。"""
    candidates = []
    for e in registry.values():
        if e.canonical == entity.canonical or len(e.canonical) < 2:
            continue
        if e.kind != entity.kind:
            continue
        if e.canonical in entity.canonical or entity.canonical in e.canonical:
            continue
        ew = _work(e)
        if ew and work and ew == work:
            continue
        distance = abs(len(e.canonical) - len(entity.canonical))
        if distance > 4:
            continue
        candidates.append((distance, len(e.variants) == 0, e.canonical, e))
    candidates.sort(key=lambda x: (x[0], x[1], x[2]))
    return candidates[0][3] if candidates else None


def _split(case_id: str) -> str:
    # 20% eval，稳定可复现；不看模型输出，避免泄漏。
    return "eval" if int(hashlib.sha1(case_id.encode()).hexdigest(), 16) % 5 == 0 else "train"


def build(limit_pos: int = 160, max_per_entity: int = 2, max_per_file: int = 8) -> dict:
    eng = spec_mod.load_engine()
    registry = spec_mod.build_registry(eng)
    entities = [e for e in registry.values()
                if e.variants and e.kind not in ("ost", "unknown")]
    by_variant: List[Tuple[str, object]] = []
    for e in entities:
        for v in e.variants:
            if len(v) >= 2 and v != e.canonical:
                by_variant.append((v, e))
    by_variant.sort(key=lambda x: (-len(x[0]), x[0]))

    pairs = []
    base = os.path.join(ROOT, "data", "pipeline_work")
    for dirpath, _dirnames, filenames in os.walk(base):
        for fn in filenames:
            if not fn.endswith(".zh.srt"):
                continue
            calib_name = fn[:-len(".zh.srt")] + ".calib.srt"
            calib_path = os.path.join(dirpath, calib_name)
            if os.path.isfile(calib_path):
                pairs.append((os.path.join(dirpath, fn), calib_path))
    pairs.sort()

    positives: List[dict] = []
    seen = set()
    entity_counts: Dict[str, int] = {}
    for zh_path, calib_path in pairs:
        try:
            old_cues = parse_srt(zh_path)
            new_cues = parse_srt(calib_path)
        except OSError:
            continue
        file_count = 0
        for num in sorted(set(old_cues) & set(new_cues)):
            old, new = old_cues[num], new_cues[num]
            if old == new or len(old) < 4 or len(old) > 600:
                continue
            # 只收“唯一一处已知错形被替换为官方名”的干净样本。
            for wrong, entity in by_variant:
                if wrong not in old:
                    continue
                if old.replace(wrong, entity.canonical) != new:
                    continue
                if entity.canonical not in new:
                    continue
                line_pair = _changed_line(old, new, wrong, entity.canonical)
                if line_pair is None:
                    break
                old_line, new_line = line_pair
                if len(old_line) < 4 or len(old_line) > 300:
                    break
                if entity_counts.get(entity.canonical, 0) >= max_per_entity:
                    break
                if file_count >= max_per_file:
                    break
                key = (old_line, new_line, entity.canonical)
                if key in seen:
                    break
                seen.add(key)
                entity_counts[entity.canonical] = entity_counts.get(entity.canonical, 0) + 1
                file_count += 1
                positives.append({
                    "old": old_line, "new": new_line,
                    "why": _why(wrong, entity.canonical),
                    "soft": False, "entity": entity.canonical,
                    "wrong": wrong, "work": _work(entity),
                    "category": entity.category, "kind": entity.kind,
                    "source": os.path.relpath(zh_path, ROOT).replace("\\", "/"),
                    "cue": num, "pair": "positive",
                })
                break
            if len(positives) >= limit_pos:
                break
        if len(positives) >= limit_pos:
            break

    cases: List[dict] = []
    for pos, item in enumerate(positives):
        case = dict(item)
        case["id"] = "jev-%04d" % (pos + 1)
        case["split"] = _split(case["id"] + case["new"])
        case["expected"] = "consistent"
        cases.append(case)
        distractor = _distractor(registry, registry.get(item["entity"]), item["work"])
        if distractor is None:
            continue
        # 保留正确 why（声明官方名），但 new 换成另一官方名 → 目标冲突硬负例。
        neg_new = item["old"].replace(item["wrong"], distractor.canonical)
        if neg_new == item["old"] or neg_new == item["new"]:
            continue
        neg = dict(case)
        neg["id"] = "jev-%04dn" % (pos + 1)
        neg["split"] = _split(neg["id"] + neg_new)
        neg["new"] = neg_new
        neg["pair"] = "wrong_target_conflict"
        neg["expected"] = "questionable"
        neg["distractor"] = distractor.canonical
        cases.append(neg)

        # 第二类硬负例：连 why 也声称错目标，模拟“带错官方名的候选改动”。
        neg_why = dict(case)
        neg_why["id"] = "jev-%04dny" % (pos + 1)
        neg_why["split"] = _split(neg_why["id"] + neg_new)
        neg_why["new"] = neg_new
        neg_why["why"] = _why(item["wrong"], distractor.canonical)
        neg_why["pair"] = "wrong_target_wrong_claim"
        neg_why["expected"] = "questionable"
        neg_why["distractor"] = distractor.canonical
        cases.append(neg_why)

    summary = {
        "schema": "jev-calib-benchmark/1",
        "generated_from": "data/pipeline_work/*.zh.srt + *.calib.srt",
        "warning": "规则/模型校准配对，不是人工金标；仅衡量与本地官方名的一致性",
        "pairs": len(pairs), "positives": len(positives), "cases": len(cases),
        "by_split": {s: sum(1 for c in cases if c["split"] == s)
                     for s in ("train", "eval")},
        "by_label": {l: sum(1 for c in cases if c["expected"] == l)
                     for l in ("consistent", "questionable")},
        "by_work": {w: sum(1 for c in cases if c["work"] == w)
                    for w in sorted({c["work"] for c in cases})},
        "by_kind": {k: sum(1 for c in cases if c["kind"] == k)
                    for k in sorted({c["kind"] for c in cases})},
    }
    return {"summary": summary, "cases": cases}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="构造 Jev 校准判定集")
    ap.add_argument("--out", default="data/entities/jev_calib_cases.jsonl")
    ap.add_argument("--summary", default="data/entities/jev_calib_summary.json")
    ap.add_argument("--limit", type=int, default=160)
    args = ap.parse_args(argv)
    data = build(limit_pos=args.limit)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        for case in data["cases"]:
            f.write(json.dumps(case, ensure_ascii=False) + "\n")
    with open(args.summary, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data["summary"], f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(json.dumps(data["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
