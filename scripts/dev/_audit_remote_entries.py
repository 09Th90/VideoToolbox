# -*- coding: utf-8 -*-
"""全表审计：origin/main 相对 HEAD 在 AST 条目层面是否真有缺失。

逐张模块级表（Dict/List）比对：
  - Dict：按 str 键比对（含被 merge_core 因混入非常量条目而整表跳过的表）；
  - List：按整元素 literal_eval 比对（CONTEXT_MAP 等）；
  - ENTITIES：按 canonical 比对，并报告两边同 canonical 但源片段不同。
"""
import ast
import os
import subprocess
import sys

ROOT = r"D:\Agent Work\软件开发\视频工具箱"
sys.path.insert(0, os.path.join(ROOT, "src"))
import calib_merge_core as mmc  # noqa: E402

CALIB = "subtitle_calib_merged.py"


def show(ref):
    p = subprocess.run(["git", "show", ref], cwd=ROOT, capture_output=True)
    if p.returncode != 0:
        raise SystemExit("git show %s failed" % ref)
    return p.stdout.decode("utf-8").replace("\r\n", "\n")


def dict_keys(node):
    out = {}
    for k, v in zip(node.keys, node.values):
        try:
            key = ast.literal_eval(k)
        except Exception:
            continue
        if isinstance(key, str):
            out[key] = v
    return out


def list_vals(node):
    out = []
    for e in node.elts:
        try:
            out.append(ast.literal_eval(e))
        except Exception:
            out.append(None)  # 不可字面量化的元素占位
    return out


def main():
    lt = mmc._ast_module_tables(show("HEAD:" + CALIB))
    rt = mmc._ast_module_tables(show("origin/main:" + CALIB))
    missing_total = 0
    for name, rnode in rt.items():
        lnode = lt.get(name)
        if lnode is None:
            print("TABLE MISSING IN LOCAL:", name)
            missing_total += 1
            continue
        if type(lnode) is not type(rnode):
            print("TABLE TYPE CHANGED:", name, type(lnode).__name__, "->", type(rnode).__name__)
            missing_total += 1
            continue
        if isinstance(rnode, ast.Dict):
            rk, lk = dict_keys(rnode), dict_keys(lnode)
            miss = sorted(set(rk) - set(lk))
            if miss:
                print("DICT %s: remote-only keys %d ->" % (name, len(miss)), miss[:20])
                missing_total += len(miss)
        elif isinstance(rnode, ast.List):
            if name == "ENTITIES":
                continue  # 单独处理
            rv, lv = list_vals(rnode), list_vals(lnode)
            miss = [v for v in rv if v is not None and v not in lv]
            if miss:
                print("LIST %s: remote-only elements %d ->" % (name, len(miss)), miss[:6])
                missing_total += len(miss)
    # ENTITIES：canonical 级
    def ents(src):
        node = mmc._ast_module_tables(src).get("ENTITIES")
        out = {}
        if isinstance(node, ast.List):
            for e in node.elts:
                if isinstance(e, ast.Call):
                    c, _m, _v = mmc._entity_fields(e)
                    if c is not None:
                        out[c] = ast.get_source_segment(src, e) or ""
        return out
    le, re_ = ents(show("HEAD:" + CALIB)), ents(show("origin/main:" + CALIB))
    miss_e = sorted(set(re_) - set(le))
    if miss_e:
        print("ENTITIES: remote-only canonicals ->", miss_e)
        missing_total += len(miss_e)
    diff_e = [c for c in set(re_) & set(le) if re_[c] != le[c]]
    print("ENTITIES: same-canonical different-source:", len(diff_e),
          "(本地改过 -> 保留本地，属设计行为)")
    for c in sorted(diff_e):
        print("   ~", c)
    print("\nTOTAL remote-only AST entries missing in local:", missing_total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
