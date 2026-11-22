# -*- coding: utf-8 -*-
# @version 3.2.5
"""T7 lint 差分门：改动前（HEAD 单文件）vs 改动后（工作树单文件）的 error 对拍。

门语义是「**新增 error 数 = 0**」而非绝对门：存量 89 dup_canonical / 111
longkey_order / 1 error 级 multi_target 全是已裁决的 error 级存量，绝对门必炸。
判据：以 (code, object, detail) 三元组为身份，`工作树 error 集 − HEAD error 集`
必须为空集（error 消失＝降噪/修复，放行；error 新增＝回归，拦截）。

error 集与 cascade 无关（cascade_substring 只产 warn），故 cascade=False 提速。

用法（程序根）：
    PYTHONPATH=src tools\\python\\python.exe scripts\\dev\\_gate_lint_diff.py
    PYTHONPATH=src tools\\python\\python.exe scripts\\dev\\_gate_lint_diff.py \\
        --old data/backup/calib_ref_frozen_20261122.py --json
退出码：新增 error = 0 → 0；否则 1。
"""
from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import os
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
_SRC = os.path.join(_ROOT, "src")
_MONOLITH = os.path.join(_ROOT, "subtitle_calib_merged.py")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
os.environ.setdefault("VT_NO_SYNC", "1")


def _lint_errors(monolith_path):
    """加载指定单文件（只读 import），返回 error 多重集（含重复三元组计数）。

    ⚠ 用 collections.Counter 而非 set：同一 (code, object, detail) 可能合法出现多次
    （重复登记对象各记一条），set 去重会把 201 折成 182，多出的一条重复即真新增。
    """
    from calib_entity import lint as lint_mod
    from calib_entity import spec as spec_mod
    if not os.path.isfile(monolith_path):
        raise FileNotFoundError(f"单文件不存在：{monolith_path}")
    name = "calib_monolith_" + str(abs(hash(monolith_path)) % 10**8)
    spec = importlib.util.spec_from_file_location(name, monolith_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    reg = spec_mod.build_registry(mod)
    res = lint_mod.run_lint(reg, mod, cascade=False)
    errs = collections.Counter((r["code"], r["object"], r["detail"])
                               for r in res["errors"])
    return errs, res["counts"], reg


def _head_monolith():
    """git show HEAD:subtitle_calib_merged.py → 临时文件路径（工作树干净时与现值同源）。"""
    blob = subprocess.run(
        ["git", "show", "HEAD:subtitle_calib_merged.py"],
        cwd=_ROOT, capture_output=True, timeout=60)
    if blob.returncode != 0 or not blob.stdout:
        raise RuntimeError("git show HEAD:subtitle_calib_merged.py 失败："
                           + blob.stderr.decode("utf-8", "replace")[:200])
    fd, path = tempfile.mkstemp(suffix="_monolith_head.py", prefix="_gate_lint_")
    with os.fdopen(fd, "wb") as f:
        f.write(blob.stdout)
    return path


def run(old_path=None, new_path=None):
    """对拍返回报告 dict。old 缺省=HEAD 单文件；new 缺省=工作树单文件。"""
    tmp = None
    try:
        if old_path is None:
            tmp = old_path = _head_monolith()
        new_path = new_path or _MONOLITH
        old_errs, old_counts, _reg_old = _lint_errors(old_path)
        new_errs, new_counts, reg_new = _lint_errors(new_path)
        added = sorted((new_errs - old_errs).elements())   # 多重集差：新增含重复增量
        removed = sorted((old_errs - new_errs).elements())
        return {
            "old": old_path, "new": new_path,
            "old_error": sum(old_errs.values()), "new_error": sum(new_errs.values()),
            "old_unique": len(old_errs), "new_unique": len(new_errs),
            "old_counts": old_counts, "new_counts": new_counts,
            "objects": len(reg_new),
            "added": added, "removed": removed,
            "verdict": "PASS" if not added else "BLOCK",
            "gate": "新增 error = 0",
        }
    finally:
        if tmp and os.path.isfile(tmp):
            os.unlink(tmp)


def render(rep):
    L = ["T7 lint 差分门（新增 error = 0，不误伤存量；error 按 (code,object,detail) 多重集对拍）", ""]
    L.append(f"  改动前 {os.path.basename(rep['old'])}: error {rep['old_error']}"
             f"（去重 {rep['old_unique']}）")
    L.append(f"  改动后 {os.path.basename(rep['new'])}: error {rep['new_error']}"
             f"（去重 {rep['new_unique']}，对象 {rep['objects']} 个）")
    if rep["added"]:
        L.append(f"  新增 error {len(rep['added'])} 条：")
        for code, obj, detail in rep["added"][:20]:
            L.append(f"    [{code}] {obj} | {detail}")
        if len(rep["added"]) > 20:
            L.append(f"    … 另有 {len(rep['added']) - 20} 条")
    else:
        L.append("  新增 error：0 条" + (
            f"（消失 {len(rep['removed'])} 条＝降噪/修复，放行）" if rep["removed"] else ""))
    L.append(f"  → {rep['verdict']}（门：{rep['gate']}）")
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description="T7 lint 差分门")
    ap.add_argument("--old", default=None,
                    help="改动前单文件路径（缺省 = git HEAD 版 subtitle_calib_merged.py）")
    ap.add_argument("--new", default=None,
                    help="改动后单文件路径（缺省 = 工作树 subtitle_calib_merged.py）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        rep = run(old_path=args.old, new_path=args.new)
    except (RuntimeError, FileNotFoundError) as exc:
        print(f"lint 差分门无法执行：{exc}")
        return 2
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print(render(rep))
    return 0 if rep["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
