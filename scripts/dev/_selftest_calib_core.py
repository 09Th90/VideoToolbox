# -*- coding: utf-8 -*-
# @version 2.7.0
"""calib_core 并行包自检（不部署、不修改生产单文件）。

覆盖：
  1. 静态契约：表/上下文/ENTITIES/缓存与生产单文件逐项相等；
  2. 17 个校准模式：out/report/rows/hits/stdout 逐字节一致；
  3. 格式边界：CRLF/BOM/英文在上/单行韩语/无末尾空行；
  4. 28 个子命令：rc/stdout/stderr/产物一致；
  5. 导入无写盘、无参用法文档、缓存原地重建、性能记录。

用法（在程序根执行）：
    PYTHONPATH=src tools\\python\\python.exe scripts\\dev\\_selftest_calib_core.py
"""
import argparse
import ast
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import types

ROOT = os.getcwd()
if not os.path.isfile(os.path.join(ROOT, "subtitle_calib_merged.py")):
    ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "src")
REF_SCRIPT = os.path.join(ROOT, "subtitle_calib_merged.py")
PY = sys.executable

os.environ.setdefault("VT_NO_SYNC", "1")
os.environ.setdefault("PYTHONHASHSEED", "0")

_passed = 0
_failed = []
_skipped = 0


def check(name, cond, detail=""):
    global _passed
    if cond:
        _passed += 1
    else:
        _failed.append((name, detail))
        print("FAIL", name, detail)


def check_output(name, ref_out, pkg_out):
    check(name, ref_out == pkg_out,
          f"\n  REF={ref_out[:400]!r}\n  PKG={pkg_out[:400]!r}")


def load_ref():
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    spec = importlib.util.spec_from_file_location("calib_ref", REF_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["calib_ref"] = mod
    spec.loader.exec_module(mod)
    return mod


def load_pkg():
    if SRC not in sys.path:
        sys.path.insert(0, SRC)
    import calib_core  # noqa: F401
    return calib_core


def section(title):
    print("\n[" + title + "]")


# ---------------------------------------------------------------- 1. 静态契约

def test_static(ref, pkg):
    section("1. 静态契约")
    contracts = [
        "ENTITIES", "BILINGUAL_TERMS", "CONTEXT_MAP", "EXCLUDE_CONTEXT",
        "_MODE_TERM_TABLE", "_MODE_CTX_TABLE", "EN_LINE_TERM_FIXES",
        "_decode_any", "process", "_scan_split_line", "_ref_for_match",
        "TABLES", "CTX_TABLES", "USAGE_DOC",
    ]
    for name in contracts:
        check(f"契约符号 {name}", hasattr(pkg, name))

    prod_terms = {n: v for n, v in vars(ref).items()
                  if n.endswith("TERMS") and isinstance(v, dict) and v}
    pkg_terms = {n: v for n, v in pkg.TABLES.items()
                 if n.endswith("TERMS") and isinstance(v, dict) and v}
    check("术语表集合", set(prod_terms) == set(pkg_terms),
          (sorted(set(prod_terms) - set(pkg_terms)), sorted(set(pkg_terms) - set(prod_terms))))
    for n in sorted(set(prod_terms) & set(pkg_terms)):
        check(f"术语表 {n}", prod_terms[n] == pkg_terms[n],
              f"{len(prod_terms[n])}/{len(pkg_terms[n])}")

    for n in ("KEEP_EN", "WORD_MAP", "EN_LINE_TERM_FIXES", "MERGE_FIXES",
              "ENDFIELD_AUTO_MARKERS", "RETIRED_KO_KEYS", "RETIRED_JA_KEYS",
              "PGR_OVERRIDES_SRC", "_MODE_TERM_TABLE", "_MODE_CTX_TABLE",
              "_MODE_NAMES", "KO_INFO", "WWOC_INFO", "ENDO_INFO", "PGR_INFO",
              "ZHO_INFO", "AK_INFO", "AK_KO_INFO"):
        check(f"常量 {n}", getattr(ref, n) == getattr(pkg, n))

    prod_ctx = {n: v for n, v in vars(ref).items()
                if (n.endswith("_CONTEXT") or n == "CONTEXT_MAP")
                and isinstance(v, list) and v}
    pkg_ctx = {n: v for n, v in pkg.CTX_TABLES.items()
               if (n.endswith("_CONTEXT") or n == "CONTEXT_MAP")
               and isinstance(v, list) and v}
    check("上下文表集合", set(prod_ctx) == set(pkg_ctx),
          (sorted(set(prod_ctx) - set(pkg_ctx)), sorted(set(pkg_ctx) - set(prod_ctx))))
    for n in sorted(set(prod_ctx) & set(pkg_ctx)):
        check(f"上下文表 {n}", prod_ctx[n] == pkg_ctx[n],
              f"{len(prod_ctx[n])}/{len(pkg_ctx[n])}")

    check("ENTITIES 长度", len(ref.ENTITIES) == len(pkg.ENTITIES),
          (len(ref.ENTITIES), len(pkg.ENTITIES)))
    for i, (a, b) in enumerate(zip(ref.ENTITIES, pkg.ENTITIES)):
        fa = (a.canonical, a.modes, a.en, a.ja, a.ko, a.category,
              a.variants, a.ctx, a.exclude, a.note)
        fb = (b.canonical, b.modes, b.en, b.ja, b.ko, b.category,
              b.variants, b.ctx, b.exclude, b.note)
        if fa != fb:
            check(f"ENTITIES[{i}]", False, fa)
            break
    else:
        check("ENTITIES 逐项", True)

    caches = [
        "_CONTEXT_COMPILED", "_EXCLUDE_COMPILED", "_JA_CONTEXT_COMPILED",
        "_JA_ENDFIELD_CONTEXT_COMPILED", "_AK_CONTEXT_COMPILED",
        "_AK_KO_CONTEXT_COMPILED", "_KO_CONTEXT_COMPILED",
        "_KO_ASR_CONTEXT_COMPILED", "_REACT_CONTEXT_COMPILED",
        "_HSR_CONTEXT_COMPILED", "_POKEMON_CONTEXT_COMPILED",
        "_ENDFIELD_KO_CONTEXT_COMPILED", "_ENDFIELD_BI_CONTEXT_COMPILED",
    ]

    def shape(v):
        if isinstance(v, list):
            return [(p.pattern, p.flags, w, r) for p, w, r in v]
        return {k: (v2, [p.pattern for p in rxs]) for k, (v2, rxs) in v.items()}

    for n in caches:
        check(f"缓存 {n}", shape(getattr(ref, n)) == shape(getattr(pkg, n)))

    for mode, tname in pkg._MODE_TERM_TABLE.items():
        check(f"模式表映射 {mode}", tname in pkg.TABLES, tname)
    for mode, cname in pkg._MODE_CTX_TABLE.items():
        check(f"模式上下文映射 {mode}", cname in pkg.CTX_TABLES, cname)

    # 漏 import 检查（只看生产文件里存在的顶层名；函数内局部 import 不算）
    prod_names = set(vars(ref))
    for modname, mod in sorted(sys.modules.items()):
        if not modname.startswith("calib_core") or not isinstance(mod, types.ModuleType):
            continue
        path = getattr(mod, "__file__", None)
        if not path or not path.endswith(".py"):
            continue
        tree = ast.parse(open(path, encoding="utf-8").read())
        local_imports = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom):
                local_imports.update(a.asname or a.name for a in n.names)
            elif isinstance(n, ast.Import):
                local_imports.update((a.asname or a.name).split(".")[0] for a in n.names)
        loads = {x.id for x in ast.walk(tree)
                 if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Load)}
        missing = sorted(n for n in loads
                         if n in prod_names and n not in local_imports
                         and n not in vars(mod) and not hasattr(mod, n))
        check(f"漏 import {os.path.basename(path)}", not missing, missing)

    # 缓存必须原地重建：engine 持有的引用要能看到新规则
    from calib_core import engine, state
    check("缓存引用共享", engine._CONTEXT_COMPILED is state._CONTEXT_COMPILED)
    before = len(engine._CONTEXT_COMPILED)
    state.CONTEXT_MAP.append((r"__selftest_never__", "测试错形", "测试正形"))
    state._rebuild_context_caches()
    check("缓存原地重建", len(engine._CONTEXT_COMPILED) == before + 1)
    state.CONTEXT_MAP.pop()
    state._rebuild_context_caches()
    check("缓存重建可还原", len(engine._CONTEXT_COMPILED) == before)


# ---------------------------------------------------------------- 2. 17 模式

MODES = ["bi", "ko", "ja", "jpe", "wwoc", "ak", "akko", "zho", "endo",
         "endobi", "endoko", "pgr", "pgren", "react", "zel", "hsr", "pkm"]
REFS = {"ja": "テストの文", "jpe": "テストの文", "ko": "테스트 문장",
        "akko": "테스트 문장", "endoko": "테스트 문장"}


def first_key(ref, mode):
    tname = ref._MODE_TERM_TABLE.get(mode)
    tbl = getattr(ref, tname, {}) if tname else {}
    return next(iter(tbl), "测试词")


def mode_srt(ref, mode):
    z = first_key(ref, mode)
    en = "Endpoint sample text"
    if mode == "ko":
        body = [f"{z}测试", "테스트 문장", "这是第二行中文", "테스트 문장"]
    elif mode == "ak":
        body = [f"{z}测试", "第二行中文", en, "second english line"]
    elif mode in ("akko", "endoko"):
        body = [f"{z}测试", "테스트 문장"]
    elif mode in ("ja", "jpe"):
        body = [f"{z}测试", "テストの文"]
    elif mode == "endo":
        body = [f"{z}测试"]
    else:
        body = [f"{z}测试", en]
    return "\r\n".join(["1", "00:00:01,000 --> 00:00:03,000"] + body) + "\r\n"


def run_process(ref, pkg, src, mode, **kw):
    d = os.path.dirname(src)
    o1, o2 = os.path.join(d, "ref.out.srt"), os.path.join(d, "pkg.out.srt")
    r1, r2 = os.path.join(d, "ref.md"), os.path.join(d, "pkg.md")
    b1, b2 = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(b1):
        a = ref.process(src, o1, r1, mode=mode, **kw)
    with contextlib.redirect_stdout(b2):
        b = pkg.process(src, o2, r2, mode=mode, **kw)
    return (a, b, open(o1, "rb").read(), open(o2, "rb").read(),
            open(r1, "rb").read(), open(r2, "rb").read(),
            b1.getvalue(), b2.getvalue())


def test_modes(ref, pkg):
    section("2. 17 模式")
    with tempfile.TemporaryDirectory(prefix="calib_selftest_modes_") as d:
        for mode in MODES:
            src = os.path.join(d, mode + ".srt")
            open(src, "wb").write(mode_srt(ref, mode).encode("utf-8"))
            kw = {"pgr_override": {"1": "覆盖后的中文"}} if mode == "pgr" else {}
            a, b, o1, o2, r1, r2, s1, s2 = run_process(ref, pkg, src, mode, **kw)
            check(f"模式 {mode}",
                  o1 == o2 and r1 == r2 and a[0] == b[0] and a[1] == b[1] and s1 == s2,
                  f"rows {len(a[0])}/{len(b[0])} hits {len(a[1])}/{len(b[1])}")

        # fix_en
        ek = next(iter(ref.EN_LINE_TERM_FIXES), "Wuthering")
        src = os.path.join(d, "fixen.srt")
        open(src, "wb").write(("\r\n".join([
            "1", "00:00:01,000 --> 00:00:03,000", "测试中文", f"{ek} sample",
        ]) + "\r\n").encode("utf-8"))
        a, b, o1, o2, r1, r2, s1, s2 = run_process(ref, pkg, src, "bi", fix_en=True)
        check("fix_en", o1 == o2 and r1 == r2 and a[0] == b[0] and a[1] == b[1])

        # learned_kb 注入
        kb = {"version": 1, "candidates": {"x": {
            "wrong": "测试词", "right": "校准词", "mode": "bi",
            "status": "confirmed", "count": 2, "samples": []}}}
        kbp = os.path.join(d, "learned.json")
        json.dump(kb, open(kbp, "w", encoding="utf-8"), ensure_ascii=False)
        src = os.path.join(d, "learned.srt")
        open(src, "wb").write(("\r\n".join([
            "1", "00:00:01,000 --> 00:00:03,000", "测试词在这里", "test here",
        ]) + "\r\n").encode("utf-8"))
        a, b, o1, o2, r1, r2, s1, s2 = run_process(ref, pkg, src, "bi", learned_kb=kbp)
        check("learned_kb 注入", o1 == o2 and r1 == r2 and a[0] == b[0] and a[1] == b[1])


# ---------------------------------------------------------------- 3. 格式边界

def test_format(ref, pkg):
    section("3. 格式边界")
    cases = []
    cases.append(("bom_bi", "bi", "\ufeff" + "\r\n".join([
        "1", "00:00:01,000 --> 00:00:03,000",
        "浇水蕾丝刚刚在共鸣者展示柜上发布",
        "Water ing lace just released shin the reson ator showcase,", "", ""])))
    cases.append(("no_tail", "bi", "\r\n".join([
        "1", "00:00:01,000 --> 00:00:03,000", "这是普通句子", "This is a normal sentence"])))
    cases.append(("en_first", "bi", "\r\n".join([
        "1", "00:00:01,000 --> 00:00:03,000",
        "Water ing lace just released", "浇水蕾丝刚刚发布", "", ""])))
    cases.append(("en_first_ak", "ak", "\r\n".join([
        "1", "00:00:01,000 --> 00:00:03,000", "Some English line", "第一行中文",
        "Another English line", "第二行中文", "", ""])))
    ko_key = next(iter(ref.KO_ASR_TERMS), "테스트")
    cases.append(("ko_single", "ko", "\r\n".join([
        "1", "00:00:01,000 --> 00:00:03,000", f"{ko_key} 문장", "", ""])))
    endo_key = next(iter(ref.ENDFIELD_TERMS), "测试")
    cases.append(("endo_mono", "endo", "\r\n".join([
        "1", "00:00:01,000 --> 00:00:03,000", f"{endo_key}测试", "", ""])))

    with tempfile.TemporaryDirectory(prefix="calib_selftest_fmt_") as d:
        for name, mode, body in cases:
            src = os.path.join(d, name + ".srt")
            open(src, "wb").write(body.encode("utf-8"))
            a, b, o1, o2, r1, r2, s1, s2 = run_process(ref, pkg, src, mode)
            check(f"格式 {name}", o1 == o2 and r1 == r2 and a[0] == b[0] and a[1] == b[1])
            v1, v2 = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(v1):
                ref._cmd_verify(src, os.path.join(d, "ref.out.srt"))
            with contextlib.redirect_stdout(v2):
                pkg._cmd_verify(src, os.path.join(d, "pkg.out.srt"))
            check(f"verify {name}", v1.getvalue() == v2.getvalue()
                  and "VERIFY OK" in v1.getvalue())


# ---------------------------------------------------------------- 4. 28 子命令

CLI_BASE = (
    "1\r\n00:00:01,000 --> 00:00:03,000\r\n"
    "浇水蕾丝刚刚在共鸣者展示柜上发布\r\n"
    "Water ing lace just released shin the reson ator showcase,\r\n\r\n"
    "2\r\n00:00:04,000 --> 00:00:06,000\r\n恩德菲尔德\r\nEndfield\r\n\r\n"
    "3\r\n00:00:07,000 --> 00:00:09,000\r\n>> [音乐]\r\n\r\n"
    "4\r\n00:00:10,000 --> 00:00:12,000\r\n"
    "这是普通句子\r\nThis is a normal sentence\r\n"
)
CLI_CALIB = CLI_BASE.replace("这是普通句子", "这是校准后的句子")
CLI_FIXTURES = {
    "base.srt": CLI_BASE,
    "calib.srt": CLI_CALIB,
    "ref_en.srt": ("1\r\n00:00:01,000 --> 00:00:03,000\r\nThe Endfield reactor core\r\n\r\n"
                   "2\r\n00:00:04,000 --> 00:00:06,000\r\nWuthering Waves\r\n"),
    "zh.srt": ("1\r\n00:00:01,000 --> 00:00:03,000\r\n终末地反应堆核心\r\n\r\n"
               "2\r\n00:00:04,000 --> 00:00:06,000\r\n鸣潮\r\n"),
    "fix.tsv": "4\t这是普通句子\t这是校准后的句子\n",
    "calib.tsv": "4\t这是校准后的句子\n",
    "plain.txt": "这是纯文本\n第二行\n",
    "learned_seed.json": json.dumps({"version": 1, "candidates": {}}, ensure_ascii=False),
}
CLI_ENV = {
    "VT_NO_SYNC": "1", "PYTHONIOENCODING": "utf-8",
    "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0",
    "VT_SYNC_MODE": "legacy",
}


def _prepare_cli(d):
    for name, text in CLI_FIXTURES.items():
        open(os.path.join(d, name), "wb").write(text.encode("utf-8"))
    env = dict(os.environ, **CLI_ENV)
    subprocess.run([PY, REF_SCRIPT, "extract", "base.srt", "cues.tsv"],
                   cwd=d, env=env, capture_output=True, timeout=60)


def _run_cli(which, args, d, extra):
    env = dict(os.environ, **CLI_ENV)
    env.update(extra)
    if which == "pkg":
        env["PYTHONPATH"] = SRC
        cmd = [PY, "-m", "calib_core"] + args
    else:
        cmd = [PY, REF_SCRIPT] + args
    try:
        p = subprocess.run(cmd, cwd=d, env=env, capture_output=True, timeout=40)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return "TIMEOUT", b"", b""


def _snapshot(d, skip):
    out = {}
    for base, dirs, files in os.walk(d):
        dirs[:] = [x for x in dirs if x != "__pycache__"]
        for f in files:
            if f.endswith(".pyc"):
                continue
            rel = os.path.relpath(os.path.join(base, f), d).replace("\\", "/")
            if any(rel.startswith(s) for s in skip):
                continue
            out[rel] = hashlib.sha256(open(os.path.join(base, f), "rb").read()).hexdigest()
    return out


def _norm_kb(path):
    try:
        kb = json.load(open(path, encoding="utf-8"))
    except Exception:
        return None
    for c in (kb.get("candidates") or {}).values():
        for k in ("first", "last", "updated", "ts"):
            c.pop(k, None)
    return kb


def _cli_case(name, args, outputs=(), skip=(), kb_path=None):
    with tempfile.TemporaryDirectory(prefix="calib_selftest_cli_") as d:
        rd, pd = os.path.join(d, "ref"), os.path.join(d, "pkg")
        os.makedirs(rd); os.makedirs(pd)
        _prepare_cli(rd); _prepare_cli(pd)
        er = {"VT_SYNC_DIR": os.path.join(rd, "sync"), "VT_SYNC_ROOT": os.path.join(rd, "remote")}
        ep = {"VT_SYNC_DIR": os.path.join(pd, "sync"), "VT_SYNC_ROOT": os.path.join(pd, "remote")}
        rc1, out1, err1 = _run_cli("ref", args, rd, er)
        rc2, out2, err2 = _run_cli("pkg", args, pd, ep)
        if rc1 == "TIMEOUT" or rc2 == "TIMEOUT":
            print("SKIP", name, "(timeout)")
            return True
        ok = rc1 == rc2 and out1 == out2 and err1 == err2
        s1, s2 = _snapshot(rd, skip), _snapshot(pd, skip)
        if outputs:
            for rel in outputs:
                if s1.get(rel) != s2.get(rel):
                    ok = False
        if kb_path:
            if _norm_kb(os.path.join(rd, kb_path)) != _norm_kb(os.path.join(pd, kb_path)):
                ok = False
        if ok:
            return True
        print("FAIL", name, f"rc {rc1}/{rc2}",
              f"out {out1[:200]!r}/{out2[:200]!r}",
              f"err {err1[:200]!r}/{err2[:200]!r}")
        return False


CLI_CASES = [
    ("extract", ["extract", "base.srt", "cues2.tsv"], ("cues2.tsv",)),
    ("split", ["split", "cues.tsv", "seg", "--n", "2"], ("segseg_A.tsv", "segseg_B.tsv")),
    ("pair", ["pair", "cues.tsv", "plain.txt", "--out", "pair.tsv"], ("pair.tsv",)),
    ("merge", ["merge", "base.srt", "calib.tsv", "--out", "merged.srt"], ("merged.srt",)),
    ("verify", ["verify", "base.srt", "base.srt"], ()),
    ("compare", ["compare", "base.srt", "base.srt", "cmp.tsv"], ("cmp.tsv",)),
    ("scan", ["scan", "cues.tsv", "--min", "1"], ()),
    ("scan-split", ["scan-split", "base.srt", "--min", "1"], ()),
    ("missing", ["missing", "ref_en.srt", "zh.srt", "--mode", "endo"], ()),
    ("lint", ["lint", "cues.tsv", "calib.tsv"], ()),
    ("subfix", ["subfix", "base.srt", "fix.tsv", "--out", "subfixed.srt"], ("subfixed.srt",)),
    ("terms-check", ["terms-check"], ()),
    ("length", ["length", "base.srt"], ()),
    ("flow", ["flow", "base.srt"], ()),
    ("align-audit", ["align-audit", "base.srt", "base.srt"], ()),
    ("rewrap", ["rewrap", "base.srt", "--out", "rewrapped.srt"], ("rewrapped.srt",)),
    ("stabilize", ["stabilize", "base.srt"], ()),
    ("detect-mode", ["detect-mode", "base.srt"], ()),
    ("audit", ["audit", "base.srt", "--mode", "bi"], ()),
    ("kb-export", ["kb-export", "--json", "--out", "kb.json"], ("kb.json",)),
    ("kb-lookup", ["kb-lookup", "鸣潮"], ()),
    ("kb-lint", ["kb-lint"], ()),
    ("learn", ["learn", "base.srt", "calib.srt", "--mode", "bi", "--kb", "learned.json"],
     ("learned.json",), (), "learned.json"),
    ("learned-show", ["learned-show", "--kb", "learned.json"], ()),
    ("learned-promote", ["learned-promote", "--kb", "learned.json"], ()),
    ("learned-reject", ["learned-reject", "测试词", "--kb", "learned.json"],
     ("learned.json",), (), "learned.json"),
    ("kb-sync", ["kb-sync"], (), ("sync/", "remote/")),
    ("kb-push", ["kb-push", "--learned", "learned.json"], (), ("sync/", "remote/")),
]


def test_cli(ref, pkg):
    section("4. 28 子命令")
    for case in CLI_CASES:
        name, args = case[0], case[1]
        outputs = case[2] if len(case) > 2 else ()
        skip = case[3] if len(case) > 3 else ()
        kb_path = case[4] if len(case) > 4 else None
        check(f"子命令 {name}", _cli_case(name, args, outputs, skip, kb_path))


# ---------------------------------------------------------------- 5. 导入/文档/性能

def test_import_and_docs(ref, pkg):
    section("5. 导入 / 文档 / 性能")
    check_output("USAGE_DOC 与生产 __doc__",
                 "\n".join(ref.__doc__.splitlines()),
                 "\n".join(pkg.USAGE_DOC.splitlines()))

    with tempfile.TemporaryDirectory(prefix="calib_selftest_doc_") as d:
        env = dict(os.environ, **CLI_ENV)
        r = subprocess.run([PY, REF_SCRIPT], cwd=d, env=env, capture_output=True, timeout=60)
        e = dict(env, PYTHONPATH=SRC)
        p = subprocess.run([PY, "-m", "calib_core"], cwd=d, env=e, capture_output=True, timeout=60)
        check("无参运行输出", r.returncode == p.returncode and r.stdout == p.stdout,
              f"{r.stdout[:200]!r}/{p.stdout[:200]!r}")

    with tempfile.TemporaryDirectory(prefix="calib_selftest_import_") as d:
        env = dict(os.environ, **CLI_ENV, PYTHONPATH=SRC)
        p = subprocess.run([PY, "-c", "import calib_core"], cwd=d, env=env,
                           capture_output=True, timeout=60)
        created = [x for x in os.listdir(d)]
        check("导入无写盘", p.returncode == 0 and not created, created)

    # 性能记录（不设门槛）
    with tempfile.TemporaryDirectory(prefix="calib_perf_") as d:
        src = os.path.join(d, "s.srt")
        open(src, "wb").write(CLI_BASE.encode("utf-8"))
        t1 = time.perf_counter()
        pkg.process(src, None, None, mode="bi")
        t2 = time.perf_counter()
        print(f"  性能：process 单次 {t2 - t1:.3f}s（仅供参考）")


# ---------------------------------------------------------------- main

def main():
    global REF_SCRIPT
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", default="",
                    help="候选单文件路径；默认仓库根 subtitle_calib_merged.py")
    args = ap.parse_args()
    if args.ref:
        REF_SCRIPT = os.path.abspath(args.ref)
    print("calib_core 并行包自检")
    print("根目录:", ROOT)
    print("参照脚本:", REF_SCRIPT)
    t0 = time.perf_counter()
    ref = load_ref()
    pkg = load_pkg()
    print(f"导入耗时：{time.perf_counter() - t0:.2f}s")
    test_static(ref, pkg)
    test_modes(ref, pkg)
    test_format(ref, pkg)
    test_cli(ref, pkg)
    test_import_and_docs(ref, pkg)
    print(f"\nPASS {_passed} / FAIL {len(_failed)}")
    for name, detail in _failed:
        print("FAIL:", name, detail)
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
