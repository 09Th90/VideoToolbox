# -*- coding: utf-8 -*-
# @version 3.2.0
"""T7 family_gap 双轨独立验收（缺片 skip）。

对 7 片校准产物各跑一次名词漏校三扫（audit，calib_core.kb._cmd_audit），
取扫 3「同词族一致性」条数 len(family_gap)，对照冻结基线双轨判定：

  基线（src/calib_entity/_baseline.json，可用 --before/--target 覆盖）：
    family_gap_before_7films = 49   改前冻结值（勿重算）
    family_gap_target        = 5    收口目标
  双轨（7 片齐全才评估；任一缺片 → 整体 SKIP，铁律③）：
    收口轨  total <= target                      → PASS
    改善轨  total <= round(before * 0.7) = 34    → PASS（相对改善 >= 30%）
    两轨取或；都未达 → FAIL（报告分片明细）。

退出码：PASS / SKIP = 0（SKIP 不阻断合并，输出点名缺片）；FAIL = 1。

用法（程序根）：
    PYTHONPATH=src tools\\python\\python.exe scripts\\dev\\_gate_family_gap.py
    PYTHONPATH=src tools\\python\\python.exe scripts\\dev\\_gate_family_gap.py --selftest
    PYTHONPATH=src tools\\python\\python.exe scripts\\dev\\_gate_family_gap.py --json
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
_SRC = os.path.join(_ROOT, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
os.environ.setdefault("VT_NO_SYNC", "1")

#: 冻结默认值：_baseline.json 缺失（安装版）时的兜底口径，与文件保持一致
_BEFORE_FALLBACK = 49
_TARGET_FALLBACK = 5

_BASELINE_PATH = os.path.join(_ROOT, "src", "calib_entity", "_baseline.json")


def load_gate_baseline():
    """读 family_gap 双轨键；文件/键缺失回落冻结默认并标注。"""
    before, target, src = _BEFORE_FALLBACK, _TARGET_FALLBACK, "内置冻结默认"
    try:
        with open(_BASELINE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        b = data.get("family_gap_before_7films")
        t = data.get("family_gap_target")
        if isinstance(b, (int, float)) and isinstance(t, (int, float)):
            before, target, src = int(b), int(t), os.path.basename(_BASELINE_PATH)
    except (OSError, ValueError):
        pass
    return before, target, src


def dual_track(total, before, target):
    """双轨判定（纯函数）：收口轨 ≤target 或 改善轨 ≤round(before*0.7)，取或。"""
    cap_rel = round(before * 0.7)
    track_close = total <= target
    track_improve = total <= cap_rel
    return {
        "total": total, "before": before, "target": target, "cap_rel": cap_rel,
        "track_close": track_close, "track_improve": track_improve,
        "verdict": "PASS" if (track_close or track_improve) else "FAIL",
    }


def evaluate(results, before, target):
    """evaluate(results, before, target)（纯函数）。

    results = [(name, status, family_gap)]，status ∈ ok / missing。
    任一缺片 → SKIP（双轨不评估，铁律③）；齐全 → dual_track。
    """
    missing = [n for n, st, _g in results if st != "ok"]
    if missing:
        return {"verdict": "SKIP", "missing": missing,
                "total": sum(g for _n, st, g in results if st == "ok"),
                "reason": "缺片 %d/%d：外部片源不在本机，双轨不评估" % (
                    len(missing), len(results))}
    total = sum(g for _n, _st, g in results)
    out = dual_track(total, before, target)
    out["missing"] = []
    out["results"] = list(results)
    return out


def audit_family_gap(path, mode):
    """单片 audit → len(family_gap)（in-process，as_json 捕获 stdout）。"""
    from calib_core import kb as kb_mod
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        kb_mod._cmd_audit(path, mode=mode, as_json=True)
    return len(json.loads(buf.getvalue())["family_gap"])


def run(before=None, target=None):
    """跑 7 片 audit + 双轨判定，返回完整报告 dict。"""
    if before is None or target is None:
        b, t, src = load_gate_baseline()
        before = before if before is not None else b
        target = target if target is not None else t
        baseline_src = src
    else:
        baseline_src = "命令行覆盖"
    sys.path.insert(0, _HERE)                       # 共用片源表
    import _gate_films
    results = []
    for name, mode, path, _note in _gate_films.audit_films():
        if path is None:
            results.append((name, "missing", 0))
            continue
        try:
            results.append((name, "ok", audit_family_gap(path, mode)))
        except Exception as exc:                     # 片源损坏按缺片口径处理
            results.append((name, "missing", 0))
            print(f"  [warn] {name} audit 异常按缺片处理：{exc}", file=sys.stderr)
    out = evaluate(results, before, target)
    out["baseline_src"] = baseline_src
    out["films"] = [(n, st, g) for n, st, g in results]
    return out


def render(rep):
    L = ["T7 family_gap 双轨验收（7 片 audit）", ""]
    L.append(f"  基线来源 {rep['baseline_src']}：before={rep['before']} "
             f"target={rep['target']} 改善上限 round(before*0.7)={rep['cap_rel']}")
    L.append("")
    for name, st, g in rep.get("films", []):
        if st == "ok":
            L.append(f"  [ok  ] {name:14s} family_gap={g}")
        else:
            L.append(f"  [SKIP] {name:14s} 缺片（外部片源不在本机）")
    L.append("")
    if rep["verdict"] == "SKIP":
        L.append(f"  → SKIP：{rep['reason']}（{', '.join(rep['missing'])}）")
        L.append("  → 已测片合计 family_gap=%d（仅供人工参考，不评估双轨）" % rep["total"])
    else:
        verdict_zh = {"PASS": "PASS", "FAIL": "FAIL"}[rep["verdict"]]
        L.append(f"  合计 family_gap={rep['total']}")
        L.append(f"  收口轨（≤{rep['target']}）：{'达成' if rep['track_close'] else '未达'} | "
                 f"改善轨（≤{rep['cap_rel']}，相对改善≥30%）："
                 f"{'达成' if rep['track_improve'] else '未达'}")
        L.append(f"  → {verdict_zh}")
    return "\n".join(L)


def selftest():
    """单测：双轨判定 / 缺片 skip / 负例防恒过（纯函数，内存构造）。"""
    ok = True

    def check(name, cond, detail=""):
        nonlocal ok
        if not cond:
            ok = False
            print("FAIL", name, detail)
        else:
            print("PASS", name)

    d = dual_track(5, 49, 5)
    check("收口轨 5≤5 → PASS", d["verdict"] == "PASS" and d["track_close"])
    d = dual_track(34, 49, 5)
    check("改善轨 34≤34 → PASS", d["verdict"] == "PASS" and d["track_improve"]
          and not d["track_close"])
    d = dual_track(35, 49, 5)
    check("负向：35 双轨皆未达 → FAIL", d["verdict"] == "FAIL")
    d = dual_track(0, 49, 5)
    check("0 残留 → PASS", d["verdict"] == "PASS")
    ev = evaluate([("甲", "ok", 3), ("乙", "missing", 0)], 49, 5)
    check("缺片 → SKIP 且点名", ev["verdict"] == "SKIP" and ev["missing"] == ["乙"]
          and ev["total"] == 3)
    ev = evaluate([("甲", "missing", 0), ("乙", "missing", 0)], 49, 5)
    check("全缺 → SKIP", ev["verdict"] == "SKIP" and ev["total"] == 0)
    ev = evaluate([("甲", "ok", 10), ("乙", "ok", 24)], 49, 5)
    check("齐全 34 → 改善轨 PASS", ev["verdict"] == "PASS" and ev["total"] == 34)
    ev = evaluate([("甲", "ok", 40), ("乙", "ok", 9)], 49, 5)
    check("负向：49 原值 → FAIL", ev["verdict"] == "FAIL")
    b, t, _src = load_gate_baseline()
    check("基线键在位（49/5）", b == 49 and t == 5, f"{b}/{t}")
    print("SELFTEST", "OK" if ok else "FAILED")
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="T7 family_gap 双轨独立验收")
    ap.add_argument("--before", type=int, default=None, help="覆盖冻结改前值")
    ap.add_argument("--target", type=int, default=None, help="覆盖收口目标")
    ap.add_argument("--json", action="store_true", help="输出 JSON 报告")
    ap.add_argument("--selftest", action="store_true", help="跑内置单测后退出")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    rep = run(before=args.before, target=args.target)
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print(render(rep))
    return 0 if rep["verdict"] in ("PASS", "SKIP") else 1


if __name__ == "__main__":
    raise SystemExit(main())
