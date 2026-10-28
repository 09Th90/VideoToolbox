# -*- coding: utf-8 -*-
# @version 2.8.0
"""检查 src/calib_core 数据表相对生产单文件的漂移（只读，不写任何文件）。

并行开发期生产文件仍在更新；本工具用于快速回答「哪些表需要从
subtitle_calib_merged.py 重新搬进 src/calib_core/data/」。

用法（在程序根执行）：
    PYTHONPATH=src tools\\python\\python.exe scripts\\dev\\_extract_calib_tables.py
    PYTHONPATH=src tools\\python\\python.exe scripts\\dev\\_extract_calib_tables.py --show 20

退出码：0=无漂移；1=有漂移或导入失败。
"""
import argparse
import importlib.util
import os
import sys

ROOT = os.getcwd()
if not os.path.isfile(os.path.join(ROOT, "subtitle_calib_merged.py")):
    ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(ROOT, "subtitle_calib_merged.py")
SRC = os.path.join(ROOT, "src")

os.environ.setdefault("VT_NO_SYNC", "1")


def load_ref():
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    spec = importlib.util.spec_from_file_location("calib_ref", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["calib_ref"] = mod
    spec.loader.exec_module(mod)
    return mod


def load_pkg():
    if SRC not in sys.path:
        sys.path.insert(0, SRC)
    import calib_core
    return calib_core


def shape(v):
    if isinstance(v, list):
        return [(p.pattern, p.flags, w, r) for p, w, r in v]
    return {k: (v2, [p.pattern for p in rxs]) for k, (v2, rxs) in v.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", type=int, default=5, help="每张表最多展示几个差异键")
    args = ap.parse_args()

    try:
        ref = load_ref()
        pkg = load_pkg()
    except Exception as e:  # noqa: BLE001
        print(f"DRIFT：加载失败 {type(e).__name__}: {e}")
        return 1

    drift = []

    prod_terms = {n: v for n, v in vars(ref).items()
                  if n.endswith("TERMS") and isinstance(v, dict) and v}
    pkg_terms = {n: v for n, v in pkg.TABLES.items()
                 if n.endswith("TERMS") and isinstance(v, dict) and v}
    for n in sorted(set(prod_terms) - set(pkg_terms)):
        drift.append(f"缺表 {n}（生产 {len(prod_terms[n])} 条）")
    for n in sorted(set(pkg_terms) - set(prod_terms)):
        drift.append(f"多表 {n}（包内 {len(pkg_terms[n])} 条）")
    for n in sorted(set(prod_terms) & set(pkg_terms)):
        a, b = prod_terms[n], pkg_terms[n]
        if a == b:
            continue
        only_a = [k for k in a if k not in b]
        only_b = [k for k in b if k not in a]
        changed = [k for k in a if k in b and a[k] != b[k]]
        bits = []
        if only_a:
            bits.append(f"生产新增 {len(only_a)}: {only_a[:args.show]}")
        if only_b:
            bits.append(f"包内多出 {len(only_b)}: {only_b[:args.show]}")
        if changed:
            bits.append(f"映射变化 {len(changed)}: {changed[:args.show]}")
        drift.append(f"表 {n}：" + "；".join(bits))

    for n in ("KEEP_EN", "WORD_MAP", "EN_LINE_TERM_FIXES", "MERGE_FIXES",
              "ENDFIELD_AUTO_MARKERS", "RETIRED_KO_KEYS", "RETIRED_JA_KEYS",
              "PGR_OVERRIDES_SRC", "_MODE_TERM_TABLE", "_MODE_CTX_TABLE",
              "_MODE_NAMES", "KO_INFO", "WWOC_INFO", "ENDO_INFO", "PGR_INFO",
              "ZHO_INFO", "AK_INFO", "AK_KO_INFO"):
        if getattr(ref, n) != getattr(pkg, n):
            drift.append(f"常量 {n} 不一致")

    prod_ctx = {n: v for n, v in vars(ref).items()
                if (n.endswith("_CONTEXT") or n == "CONTEXT_MAP")
                and isinstance(v, list) and v}
    pkg_ctx = {n: v for n, v in pkg.CTX_TABLES.items()
               if (n.endswith("_CONTEXT") or n == "CONTEXT_MAP")
               and isinstance(v, list) and v}
    for n in sorted(set(prod_ctx) - set(pkg_ctx)):
        drift.append(f"缺上下文表 {n}（生产 {len(prod_ctx[n])} 条）")
    for n in sorted(set(pkg_ctx) - set(prod_ctx)):
        drift.append(f"多上下文表 {n}（包内 {len(pkg_ctx[n])} 条）")
    for n in sorted(set(prod_ctx) & set(pkg_ctx)):
        if prod_ctx[n] != pkg_ctx[n]:
            drift.append(f"上下文表 {n}：{len(prod_ctx[n])} vs {len(pkg_ctx[n])} 条")

    if len(ref.ENTITIES) != len(pkg.ENTITIES):
        drift.append(f"ENTITIES：生产 {len(ref.ENTITIES)} vs 包内 {len(pkg.ENTITIES)}")
    else:
        for i, (a, b) in enumerate(zip(ref.ENTITIES, pkg.ENTITIES)):
            fa = (a.canonical, a.modes, a.en, a.ja, a.ko, a.category,
                  a.variants, a.ctx, a.exclude, a.note)
            fb = (b.canonical, b.modes, b.en, b.ja, b.ko, b.category,
                  b.variants, b.ctx, b.exclude, b.note)
            if fa != fb:
                drift.append(f"ENTITIES[{i}]：{a.canonical!r} 字段不一致")
                break

    caches = [
        "_CONTEXT_COMPILED", "_EXCLUDE_COMPILED", "_JA_CONTEXT_COMPILED",
        "_JA_ENDFIELD_CONTEXT_COMPILED", "_AK_CONTEXT_COMPILED",
        "_AK_KO_CONTEXT_COMPILED", "_KO_CONTEXT_COMPILED",
        "_KO_ASR_CONTEXT_COMPILED", "_REACT_CONTEXT_COMPILED",
        "_HSR_CONTEXT_COMPILED", "_POKEMON_CONTEXT_COMPILED",
        "_ENDFIELD_KO_CONTEXT_COMPILED", "_ENDFIELD_BI_CONTEXT_COMPILED",
    ]
    for n in caches:
        if shape(getattr(ref, n)) != shape(getattr(pkg, n)):
            drift.append(f"缓存 {n} 内容不一致")

    if not drift:
        print("TABLES OK：19 张 dict、12 张上下文表、ENTITIES 与 13 个缓存均与生产一致")
        return 0
    print(f"DRIFT：{len(drift)} 处差异")
    for d in drift:
        print(" -", d)
    print("\n处理建议：把生产文件的新条目补进 src/calib_core/data/ 对应模块，"
          "再跑 scripts/dev/_selftest_calib_core.py。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
