# -*- coding: utf-8 -*-
# @version 3.3.1
"""T7 lint 差分门：改动前（HEAD 单文件）vs 改动后（工作树单文件）的 error 对拍。

门语义是「**新增 error 数 = 0**」而非绝对门：存量 89 dup_canonical / 111
longkey_order / 1 error 级 multi_target 全是已裁决的 error 级存量，绝对门必炸。
判据：以 (code, object, detail) 三元组为身份，`工作树 error 集 − HEAD error 集`
必须为空集（error 消失＝降噪/修复，放行；error 新增＝回归，拦截）。

**mode 标签归一**（默认开启，--no-normalize 保留原始口径）：detail / object 中的
mode 标签 token（如 `[ko]` `[endobi]` `[wuwa40ign]`）先经 normalize_mode 归一成新
「游戏-细类」子键再对拍——否则跨代（子键化改名：ko→wuwa-ko、ja→wuwa-ja、
endobi→endo-bi、wuwa40ign→wuwa-40ign、akja→ak-ja、jpe→endo-ja、pgren→pgr-en、
pgrja→pgr-ja、akko→ak-ko、arcak→ak-arcaea、endoko→endo-ko、wuwa40ko→wuwa-40ko）
会把同一存量 error 误计成「新增」。归一只改写已知旧键标签（normalize_mode 对
registry 新键与未知词原样返回 → 幂等），其余文本一字不动；同代对拍两侧标签本就
一致，归一前后结果不变。

error 集与 cascade 无关（cascade_substring 只产 warn），故 cascade=False 提速。

用法（程序根）：
    PYTHONPATH=src tools\\python\\python.exe scripts\\dev\\_gate_lint_diff.py
    PYTHONPATH=src tools\\python\\python.exe scripts\\dev\\_gate_lint_diff.py \\
        --old data/backup/calib_ref_frozen_20261122.py --json
    PYTHONPATH=src tools\\python\\python.exe scripts\\dev\\_gate_lint_diff.py --selftest
退出码：新增 error = 0 → 0；否则 1（selftest 失败 → 1）。
"""
from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import os
import re
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

from calib_core.data.modes import normalize_mode  # noqa: E402  （依赖上方 _SRC 注入）

# detail/object 中的 mode 标签 token：`[ko]`、`[wuwa-40ign]` 等小写方括号形式
# （实测 lint 明细所有标签均为 `[mode] ` 前缀；数字/中文/未知词不匹配或原样返回）。
_MODE_TOKEN_RE = re.compile(r"\[([a-z][a-z0-9_\-]*)\]")


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


def _normalize_mode_labels(text):
    """归一 text 中的 mode 标签 token（[ko]→[wuwa-ko]、[endobi]→[endo-bi]、…）。

    只对方括号 token 调 normalize_mode：已知旧键改写为新子键；registry 新键与
    未知词 normalize_mode 原样返回 → token 原样保留。幂等，其余文本零改动。
    """
    def _sub(m):
        tok = m.group(1)
        norm = normalize_mode(tok)
        return m.group(0) if norm == tok else f"[{norm}]"

    return _MODE_TOKEN_RE.sub(_sub, text)


def _normalize_errs(errs):
    """对 (code, object, detail) 三元组多重集的 object/detail 做 mode 标签归一重建。

    Counter（多重集）计数原样保留，仅重写三元组身份；code 为 lint 规则名不含
    mode 标签，不处理。
    """
    out = collections.Counter()
    for (code, obj, detail), n in errs.items():
        out[(code, _normalize_mode_labels(obj), _normalize_mode_labels(detail))] += n
    return out


def selftest():
    """内置单测：旧键映射、幂等、新键/未知词/无标签原样。返回 0=全绿。"""
    cases = [
        # (输入, 期望)
        ("[ko] 短键「星座」排在长键「休闲星座」之前（会被抢跑）",
         "[wuwa-ko] 短键「星座」排在长键「休闲星座」之前（会被抢跑）"),
        ("[ja] 「X」被多条记录同时登记", "[wuwa-ja] 「X」被多条记录同时登记"),
        ("[endobi] 「Y」候选缺失", "[endo-bi] 「Y」候选缺失"),
        ("[wuwa40ign] 「Z」缩写超界", "[wuwa-40ign] 「Z」缩写超界"),
        ("[akja] 「W」排布反序", "[ak-ja] 「W」排布反序"),
        ("[jpe] 「V」排布反序", "[endo-ja] 「V」排布反序"),
        ("[pgren] 「U」排布反序", "[pgr-en] 「U」排布反序"),
        ("[pgrja] 「T」排布反序", "[pgr-ja] 「T」排布反序"),
        ("[akko] 「S」排布反序", "[ak-ko] 「S」排布反序"),
        ("[arcak] 「R」排布反序", "[ak-arcaea] 「R」排布反序"),
        ("[endoko] 「Q」排布反序", "[endo-ko] 「Q」排布反序"),
        ("[wuwa40ko] 「P」排布反序", "[wuwa-40ko] 「P」排布反序"),
        # 新键 / 父键 / 未知词 / 数字 / 无标签：原样
        ("[wuwa-ko] 短键「Suho」排在长键「Suhosi」之前", "[wuwa-ko] 短键「Suho」排在长键「Suhosi」之前"),
        ("[endo] 父键标签不动", "[endo] 父键标签不动"),
        ("[error] 未知方括号词不动", "[error] 未知方括号词不动"),
        ("[abc123] 未知小写词不动", "[abc123] 未知小写词不动"),
        ("纯文本无标签", "纯文本无标签"),
    ]
    fails = []
    for src, want in cases:
        got = _normalize_mode_labels(src)
        if got != want:
            fails.append(f"    映射失败：{src!r} → {got!r}（期望 {want!r}）")
        if _normalize_mode_labels(got) != got:  # 幂等
            fails.append(f"    幂等失败：{got!r}")
    if fails:
        print("selftest 失败：")
        print("\n".join(fails))
        return 1
    print(f"selftest 全绿（{len(cases)} 用例 + 幂等检查）")
    return 0


def run(old_path=None, new_path=None, normalize=True):
    """对拍返回报告 dict。old 缺省=HEAD 单文件；new 缺省=工作树单文件。

    normalize=True（默认）先对两侧三元组的 object/detail 做 mode 标签归一（跨代
    键改名不误报新增）；False 保留原始口径。归一幂等，同代对拍结果不变。
    """
    tmp = None
    try:
        if old_path is None:
            tmp = old_path = _head_monolith()
        new_path = new_path or _MONOLITH
        old_errs, old_counts, _reg_old = _lint_errors(old_path)
        new_errs, new_counts, reg_new = _lint_errors(new_path)
        if normalize:
            old_errs = _normalize_errs(old_errs)
            new_errs = _normalize_errs(new_errs)
        added = sorted((new_errs - old_errs).elements())   # 多重集差：新增含重复增量
        removed = sorted((old_errs - new_errs).elements())
        return {
            "old": old_path, "new": new_path,
            "old_error": sum(old_errs.values()), "new_error": sum(new_errs.values()),
            "old_unique": len(old_errs), "new_unique": len(new_errs),
            "old_counts": old_counts, "new_counts": new_counts,
            "objects": len(reg_new),
            "normalized": bool(normalize),
            "added": added, "removed": removed,
            "verdict": "PASS" if not added else "BLOCK",
            "gate": "新增 error = 0",
        }
    finally:
        if tmp and os.path.isfile(tmp):
            os.unlink(tmp)


def render(rep):
    L = ["T7 lint 差分门（新增 error = 0，不误伤存量；error 按 (code,object,detail) 多重集对拍，"
         + ("mode 标签已归一）" if rep.get("normalized") else "原始口径）"), ""]
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
    ap.add_argument("--no-normalize", action="store_true",
                    help="关闭 mode 标签归一（保留原始口径对拍；默认归一旧键→新子键）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true", help="跑内置单测后退出")
    args = ap.parse_args(argv)
    if args.selftest:
        return selftest()
    try:
        rep = run(old_path=args.old, new_path=args.new,
                  normalize=not args.no_normalize)
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
