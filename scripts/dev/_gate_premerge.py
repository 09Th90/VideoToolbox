# -*- coding: utf-8 -*-
# @version 3.2.0
"""T10 合并前门禁编排：三件套一次跑齐。

三件（任一 FAIL 即退出码 1，缺片组 SKIP 不阻断但点名）：
  1. onepass --gate --max-differ 0   7 片 10 组（scripts/dev/_gate_films.py）：
     对象索引「单遍最长」vs「全表串行」语义分叉必须为 0（M3 受控换义回归护栏）。
  2. verify EQUIVALENT               同 10 组：索引预筛 vs 全表串行逐字节等价。
  3. lint 差分门                     新增 error = 0（scripts/dev/_gate_lint_diff.py，
     HEAD 单文件 vs 工作树单文件对拍；存量 error 不误伤）。

参考项（不阻断，独立验收见 scripts/dev/_gate_family_gap.py）：
  family_gap 双轨（7 片 audit；缺片 skip）——默认只打印，--strict-family-gap 才并入退出码。

用法（程序根，合并前跑）：
    PYTHONPATH=src tools\\python\\python.exe scripts\\dev\\_gate_premerge.py
    PYTHONPATH=src tools\\python\\python.exe scripts\\dev\\_gate_premerge.py --json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
_SRC = os.path.join(_ROOT, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
os.environ.setdefault("VT_NO_SYNC", "1")


def _engine():
    from calib_entity import spec as spec_mod
    return spec_mod.load_engine()


def gate_onepass_verify(groups, eng, idx_cache):
    """三件套之 1+2：10 组 onepass 门禁 + verify 等价（共用同模式索引）。"""
    from calib_entity import index as index_mod
    from calib_entity import shadow as shadow_mod
    rows = []
    for name, mode, path in groups:
        row = {"group": name, "mode": mode,
               "onepass": "SKIP", "verify": "SKIP", "differ": None, "verdict": None}
        if path is None:
            rows.append(row)
            print(f"  [SKIP] {name:16s} 缺片（外部片源不在本机）")
            continue
        idx = idx_cache.get(mode)
        if idx is None:
            idx = idx_cache[mode] = index_mod.ModeIndex.build(mode, engine=eng)
        rep = shadow_mod.diff_onepass(mode, path, engine=eng, index=idx)
        ok = rep["differ"] <= 0
        row["onepass"] = "PASS" if ok else "BLOCK"
        row["differ"] = rep["differ"]
        rep2 = shadow_mod.verify_index_equivalence(mode, path, engine=eng, index=idx)
        ok2 = rep2["verdict"].startswith("EQUIVALENT")
        row["verify"] = "PASS" if ok2 else "BLOCK"
        row["verdict"] = rep2["verdict"]
        rows.append(row)
        print(f"  [{'PASS' if ok else 'BLOCK'}] {name:16s} onepass 分叉 {rep['differ']}"
              f" | [{'PASS' if ok2 else 'BLOCK'}] verify {rep2['verdict']}"
              f"（行 {rep2['lines']}）")
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description="T10 合并前门禁编排（三件套）")
    ap.add_argument("--json", action="store_true", help="输出 JSON 报告")
    ap.add_argument("--skip-family-gap", action="store_true",
                    help="不跑 family_gap 参考项")
    ap.add_argument("--strict-family-gap", action="store_true",
                    help="family_gap FAIL 也并入退出码（默认仅参考）")
    args = ap.parse_args(argv)

    import _gate_films
    import _gate_lint_diff

    groups = _gate_films.gate_groups()
    t0 = time.perf_counter()
    print("T10 合并前门禁编排（三件套）")
    print(f"  组数 {len(groups)}（7 片现行产物 + 3 组上一版产物；缺片组 SKIP）")

    print("\n[1/3] onepass --gate --max-differ 0（对象索引单遍 vs 串行，分叉=0）")
    print("[2/3] verify EQUIVALENT（索引预筛 vs 全表串行，逐字节等价）")
    eng = _engine()
    idx_cache = {}
    rows = gate_onepass_verify(groups, eng, idx_cache)
    n_skip = sum(1 for r in rows if r["onepass"] == "SKIP")
    n_fail = sum(1 for r in rows if r["onepass"] == "BLOCK" or r["verify"] == "BLOCK")
    gate12 = "PASS" if n_fail == 0 else "BLOCK"

    print("\n[3/3] lint 差分门（新增 error = 0，HEAD vs 工作树）")
    lint_rep = _gate_lint_diff.run()
    print("  " + "\n  ".join(_gate_lint_diff.render(lint_rep).splitlines()[2:]))
    gate3 = lint_rep["verdict"]

    fg_rep = None
    if not args.skip_family_gap:
        print("\n[参考] family_gap 双轨（不阻断；独立验收 = _gate_family_gap.py）")
        import _gate_family_gap
        fg_rep = _gate_family_gap.run()
        print("  " + "\n  ".join(_gate_family_gap.render(fg_rep).splitlines()[2:]))

    strict_fail = (fg_rep is not None and args.strict_family_gap
                   and fg_rep["verdict"] == "FAIL")
    ok = gate12 == "PASS" and gate3 == "PASS" and not strict_fail
    summary = {
        "groups": rows, "groups_skip": n_skip, "groups_fail": n_fail,
        "onepass_verify": gate12,
        "lint": {k: lint_rep[k] for k in ("old_error", "new_error", "verdict")},
        "family_gap": (None if fg_rep is None else
                       {k: fg_rep[k] for k in ("total", "verdict", "missing")}),
        "elapsed_s": round(time.perf_counter() - t0, 1),
        "verdict": "PASS" if ok else "BLOCK",
    }
    print("\n" + "=" * 60)
    print(f"三件套：onepass+verify {gate12}"
          f"（{len(rows) - n_skip}/{len(rows)} 组跑，缺片 {n_skip}）"
          f" | lint {gate3}（新增 {len(lint_rep['added'])}）"
          + (f" | family_gap 参考 {fg_rep['verdict']}（合计 {fg_rep['total']}）"
             if fg_rep else ""))
    print(f"→ {summary['verdict']}（用时 {summary['elapsed_s']}s）")
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
