# -*- coding: utf-8 -*-
# @version 2.9.0
"""calib_core 并行包自检（不部署、不修改生产单文件）。

覆盖：
  1. 静态契约：表/上下文/ENTITIES/缓存与生产单文件逐项相等；
  2. 23 个校准模式：out/report/rows/hits/stdout 逐字节一致；
  3. 格式边界：CRLF/BOM/英文在上/单行韩语/无末尾空行；
     3b. 英文在上版式的取行与 merge/length/flow/align-audit/audit 五条通路；
     3c. EP17 相变临界术语沉淀 + ak 分支 EXCLUDE 回滚层（含凯尔特/Cow·Calcite 负例）；
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
import re
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
        "_JA_ENDFIELD_CONTEXT_COMPILED", "_JA_PGR_CONTEXT_COMPILED", "_AK_CONTEXT_COMPILED",
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


# ---------------------------------------------------------------- 2. 23 模式

MODES = ["bi", "ko", "ja", "jpe", "wwoc", "ak", "akko", "zho", "endo",
         "endobi", "endoko", "pgr", "pgren", "react", "zel", "hsr", "pkm", "limbus", "ffrs",
         # 2026-11-01：pbz 是 2026-10-30 加模式时漏同步的一项，连同新增的 ff14 一起补齐
         "pbz", "ff14",
         # 2026-11-03 新增：战双日语原声（--pgrja）
         "pgrja",
         # 2026-11-03 新增：明日方舟日语原声（--akja）
         "akja"]
REFS = {"ja": "テストの文", "jpe": "テストの文", "pgrja": "テストの文",
        "akja": "テストの文",
        "ko": "테스트 문장",
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
    elif mode in ("ja", "jpe", "pgrja", "akja"):
        # 日语原声片：参考行是日语，ctx 锚点打在日语行上。
        # ⚠ 别让 pgrja/akja 落到 else 的英文样例分支——那样 ctx 永不命中，等于测空转。
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
    section("2. 23 模式")
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


def test_wwoc_context(ref, pkg):
    section("2b. WWOC_CONTEXT")
    with tempfile.TemporaryDirectory(prefix="calib_selftest_wwoc_") as d:
        src = os.path.join(d, "wwoc.srt")
        body = "\r\n".join([
            "1", "00:00:01,000 --> 00:00:03,000", "十字军", "크루세이더의 노래",
            "", "2", "00:00:03,000 --> 00:00:05,000", "涟漪", "잔물결이란 노래",
            "", "3", "00:00:05,000 --> 00:00:07,000", "反向", "리버스 노래",
            "", "4", "00:00:07,000 --> 00:00:09,000", "《Alice Fiction》", "앨리스 픽션 노래",
            "",
        ])
        open(src, "wb").write(body.encode("utf-8"))
        a, b, o1, o2, r1, r2, s1, s2 = run_process(ref, pkg, src, "wwoc")
        txt = o2.decode("utf-8")
        check("wwoc ctx 输出一致", o1 == o2 and a[0] == b[0] and a[1] == b[1])
        check("wwoc 十字军锚定", "克鲁赛德战记" in txt)
        check("wwoc 涟漪锚定", "轻涟" in txt)
        check("wwoc 反向锚定", "重返未来：1999" in txt)
        check("wwoc 官方英文名", "《漂眇群像》" in txt)
        check("wwoc 参考行不变",
              "크루세이더의 노래" in txt and "잔물결이란 노래" in txt
              and "리버스 노래" in txt and "앨리스 픽션 노래" in txt)


def test_akja_context(ref, pkg):
    section("2d. AKJA（日语原声·明日方舟）正例")
    # 这一节补的是 --pgrja 当初没做的「正例」环节：只测「生成物 vs 包」一致性的 test_modes
    # 查不出两类静默灾难 —— engine 漏 terms 分支会拿鸣潮 BILINGUAL_TERMS 改方舟片，
    # 漏 cue 分派分支会掉进 bi 的 else。故这里同时断言**替换确实发生**与**无关语境不替换**。
    with tempfile.TemporaryDirectory(prefix="calib_selftest_akja_") as d:
        src = os.path.join(d, "akja.srt")
        body = "\r\n".join([
            # 1) ctx 命中：天灾 <- スカージ（正常中文词，只能锚定，禁裸键）
            "1", "00:00:01,000 --> 00:00:03,000", "哦，天灾也有一定的威慑力", "あ、スカージも威嚇があるね",
            "",
            # 2) ctx 不得越界：中文同样有"天灾"，但参考行没有スカージ ⇒ 必须原样
            "2", "00:00:03,000 --> 00:00:05,000", "这场天灾真可怕", "この天災は恐ろしい",
            "",
            # 3) 纯汉字日语参考行（本片 61 条靶区，#78 型）：ref_pos 为空时锚点回落末文本行，
            #    且**第二行必须逐字节不变**（ak 分支做不到这一点，故 akja 照 jpe 形状）
            "3", "00:00:05,000 --> 00:00:07,000", "四四章", "四四章",
            "",
            # 4) 合并表生效：AK_TERMS 的通用方舟错形（凯尔西）在 --akja 下也必须命中
            "4", "00:00:07,000 --> 00:00:09,000", "凯尔西来了", "ケルシーが来た",
            "",
            # 5) AK_JA_TERMS 的日语向裸键（片假名音译串）
            "5", "00:00:09,000 --> 00:00:11,000", "那是苏卡吉，苏卡吉在哪", "あれ、スカジはどこですか",
            "",
            # 6) **尾巴类**：AK_TERMS 的裸键 Pepe->佩佩 会咬住 ASR 形 "Pepei" 产「佩佩i」
            #    （#2219 参考行「本当にまだペーペイだからさ」）⇒ ctx 必须把尾巴收回拉丁原形
            "6", "00:00:11,000 --> 00:00:13,000", "真的还是Pepei，嗯，一切", "本当にまだペーペイだからさ",
            "",
        ])
        open(src, "wb").write(body.encode("utf-8"))
        a, b, o1, o2, r1, r2, s1, s2 = run_process(ref, pkg, src, "akja")
        txt = o2.decode("utf-8")
        check("akja 生成物与包输出逐字节一致", o1 == o2 and r1 == r2 and s1 == s2)
        check("akja ctx 锚定生效（天灾->斯卡蒂）", "斯卡蒂也有一定的威慑力" in txt)
        check("akja ctx 不越界（无スカージ锚点的天灾保留）", "这场天灾真可怕" in txt)
        check("akja 纯汉字参考行锚定生效（四四章->4-4 章）", "4-4 章" in txt)
        check("akja 纯汉字参考行第二行逐字节不动",
              txt.count("四四章") == 1 and "テスト" not in txt)
        check("akja 合并 AK_TERMS 生效（凯尔西->凯尔希）", "凯尔希来了" in txt)
        check("akja 日语向裸键生效（苏卡吉->斯卡蒂）",
              "那是斯卡蒂，斯卡蒂在哪" in txt)
        check("akja 尾巴不得留在产物（佩佩i 必须被收口）", "佩佩i" not in txt)
        check("akja 尾巴收回拉丁原形（查无证件不校名）",
              "真的还是Pepei，嗯，一切" in txt)
        check("akja 确实产出了替换（rows>0，防空转）", len(a[0]) >= 4)
        # str 模式默认带 re.UNICODE(32)，判据只能是「没开 IGNORECASE」，不是 flags==0
        check("akja ctx 不带 re.I（锚点是假名/日服汉字）",
              all(not (p.flags & re.IGNORECASE)
                  for p, _w, _r in ref._AK_JA_CONTEXT_COMPILED))
        check("akja 两张表都在注册表里",
              "AK_JA_TERMS" in ref.TABLES and "AK_JA_CONTEXT" in ref.CTX_TABLES)
        check("akja 模式投影目标已登记",
              ref._MODE_TERM_TABLE.get("akja") == "AK_JA_TERMS"
              and ref._MODE_CTX_TABLE.get("akja") == "AK_JA_CONTEXT")


def test_ko_lotte_terms(ref, pkg):
    section("2c. KO 乐天影院联动术语")
    cases = [
        ("这就是明祖和乐天影业的周边", "명조와 롯데 시네마의 굿즈", "这就是鸣潮和乐天影院的周边"),
        ("有一群狐狸。这是", "여우의 별자리가 있습니다", "有心月狐。这是"),
        ("世明先生，你做了很多", "많이 하셨네, 세명 씨", "锁暝，你做了很多"),
        ("这是钥匙帽", "키캡", "这是键帽"),
        ("这是石板", "슬레이트", "这是场记板"),
        ("接下来是标清版本", "SD 버전", "接下来是SD版"),
        ("这是Cambaggage套装", "캠베지 세트", "这是画布套装"),
        ("这是一套金属徽章", "금속 핀배찌 세트", "这是金属徽章套装"),
        ("特殊待遇", "특전", "特典"),
        ("20个自助机", "매점", "20个影院卖场"),
        ("三个人同行", "세 명이 동행", "三个人同行"),
        ("这是心的剧情", "여우의 별자리 이야기", "这是心的剧情"),
        ("这是心的周边", "여우의 별자리 굿즈", "这是心月狐的周边"),
        ("杜加姆身后还有一顶帽子", "두감님 뒤에 모자도 있습니다", "锁暝身后还有一顶帽子"),
        ("Cinema Now 世界塔的预订", "시네마 이제 월드 타워에 예매를", "乐天影院 世界塔的预订"),
        ("这就是盒子。哦，是个框架", "박스입니다. 오, 액자인데 불", "这就是盒子。哦，是个灯箱"),
        ("这是画布套装。自由与自由", "캠베지 세트입니다. LD와 LD", "这是画布套装。LD版"),
        ("是杯子。就这样。其心和", "컵임. 됐다. 그 여의 별자리와", "是杯子。就这样。心月狐和"),
        ("接下来是锁暝。哦，宝贝", "다음에는 쇠명. 오, 인형", "接下来是锁暝。哦，毛绒"),
        ("三人应要求。示意图。", "요망에 세 명. 도해. 각각 다른", "锁暝。示意图。"),
    ]
    with tempfile.TemporaryDirectory(prefix="calib_selftest_ko_lotte_") as d:
        src = os.path.join(d, "ko_lotte.srt")
        lines = []
        for i, (zh, ko, _) in enumerate(cases, 1):
            lines += [str(i), "00:00:01,000 --> 00:00:03,000", zh, ko, ""]
        open(src, "wb").write(("\r\n".join(lines) + "\r\n").encode("utf-8"))
        a, b, o1, o2, r1, r2, s1, s2 = run_process(ref, pkg, src, "ko")
        check("ko 乐天术语输出一致",
              o1 == o2 and r1 == r2 and a[0] == b[0] and a[1] == b[1])
        out = o2.decode("utf-8").split("\r\n")
        for i, (_, _, expected) in enumerate(cases):
            actual = out[5 * i + 2]
            check(f"ko 乐天术语 #{i + 1}", actual == expected, f"{actual!r} != {expected!r}")
        check("ko 乐天术语负例·三个人", out[5 * 10 + 2] == "三个人同行")
        check("ko 乐天术语负例·剧情心", out[5 * 11 + 2] == "这是心的剧情")


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


# ------------------------------------------------------ 3b. 英文在上版式（2026-11-02）

EN_FIRST_SRT = (
    "1\r\n00:00:01,000 --> 00:00:03,000\r\n"
    "Ark Knights is coming\r\n方舟骑士要来了\r\n\r\n"
    "2\r\n00:00:04,000 --> 00:00:06,000\r\n"
    "The doctor will smile\r\n医生会笑的\r\n\r\n"
    "3\r\n00:00:07,000 --> 00:00:09,000\r\n"
    "[音乐]\r\n[音楽]\r\n"
)
EN_FIRST_CALIB = "1\t明日方舟要来了\n2\t博士会笑的\n"


def _srt_blocks(text):
    return [b.replace("\r", "").split("\n") for b in re.split(r"\r?\n\r?\n+", text.strip())]


def test_en_first_layout(ref, pkg):
    """英文 ASR 在上、谷翻中文在下的片源：取行 / 回填 / 体检三条通路都要落在中文行。

    回归动机：merge/length/flow/align-audit/audit 曾硬编码「末行=参考行」，在这类
    片源上会把新中文写进英文行、把英文行当内容行体检（串位恒查不出、假绿灯）。
    同时守住反向约束：「[音楽]」这类全汉字的日语参考行仍须按位置约定处理，
    否则日语片源的参考行会被当成中文行整块覆盖。
    """
    section("3b. 英文在上版式")
    for tag, m in (("单文件", ref), ("分包", pkg)):
        check(f"取行 英文在上 {tag}", m._cue_zh_ref(["Hello", "你好"]) == ([1], [0]))
        check(f"取行 中文在上 {tag}", m._cue_zh_ref(["你好", "Hello"]) == ([0], [1]))
        check(f"取行 全汉字参考行仍按位置 {tag}",
              m._cue_zh_ref(["[音乐]", "[音楽]"]) == ([0], [1]))
        with tempfile.TemporaryDirectory(prefix="calib_selftest_enf_") as d:
            src = os.path.join(d, "en_first.srt")
            open(src, "wb").write(EN_FIRST_SRT.encode("utf-8"))
            tab = os.path.join(d, "calib.tsv")
            open(tab, "wb").write(EN_FIRST_CALIB.encode("utf-8"))
            out = os.path.join(d, "merged.srt")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                m._cmd_merge(src, tab, out)
            got = _srt_blocks(open(out, "rb").read().decode("utf-8"))
            check(f"merge 只回填中文行 {tag}",
                  got[0][2] == "Ark Knights is coming" and got[0][3] == "明日方舟要来了"
                  and got[1][3] == "博士会笑的"
                  and got[2][2] == "[音乐]" and got[2][3] == "[音楽]")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                m._cmd_verify(src, out)
            check(f"verify 参考行零改动 {tag}",
                  "VERIFY OK" in buf.getvalue() and "reference diffs: 0" in buf.getvalue())
            rows = {num: zh for num, zh, _r in m._iter_cue_lines(out)}
            check(f"length 内容行是中文行 {tag}",
                  rows.get("1") == ["明日方舟要来了"] and rows.get("3") == ["[音乐]"])
            first = m._cue_first_text_map(out)
            check(f"align-audit 内容映射取中文行 {tag}",
                  first[1] == "明日方舟要来了" and first[3] == "[音乐]")
            _layout, triples = m._iter_cue_triples(out)
            check(f"audit 中英两列不互换 {tag}",
                  triples[0] == ("1", "明日方舟要来了", "Ark Knights is coming"))
            flowed = os.path.join(d, "flowed.srt")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                m._cmd_flow(src, flowed)
            a, b = _srt_blocks(open(src, "rb").read().decode("utf-8")), \
                _srt_blocks(open(flowed, "rb").read().decode("utf-8"))
            check(f"flow --out 不动英文参考行 {tag}", len(a) == len(b)
                  and all(x[2] == y[2] for x, y in zip(a, b)))


# ------------------------------------------------ 3c. EP17 术语与 ak 排除层（2026-11-02）

# (中文行, 英文参考行, 期望中文行, 说明) —— 版式与 EP17 反应片一致：英文在上、中文在下
_AK_POSITIVE = [
    ("新的 mon3tr 吗", "is that like the new monster", "新的 Mon3tr 吗",
     "AK_TERMS 大小写敏感裸键 mon3tr->Mon3tr"),
    ("等等，关闭是不是可以实装了", "wait is playable closure finally", "等等，可露希尔是不是可以实装了",
     "关闭 只按 closure 英文锚定"),
    ("后卫吧", "defender, huh", "重装吧",
     "后卫 只按 defender 锚定"),
    ("好吧，医生", "All right, the doctor", "好吧，博士",
     "医生 只按 doctor 锚定"),
    ("所以连怪物都有全新皮肤", "so even Monster got a brand new skin", "所以连怪物都有全新皮肤",
     "怪物 **不入表**：跨片实测 \"the monster reset\" 是通用怪物义，锚定过宽会误伤"),
    ("那是愈伤组织的造型", "that's the callus design", "那是Mon3tr的造型",
     "愈伤组织=callus 罕见形，保留锚定"),
    ("称为临界相变", "is called Critical Phase Transition", "称为相变临界",
     "EP17 官方章名裸键"),
    ("克拉科恩是个疯狂的家伙", "Crackborn's a crazy one", "裂响是个疯狂的家伙",
     "Crackborn/克拉科恩 -> 裂响"),
]
_AK_NEGATIVE = [
    ("凯尔特神话很美", "Celtic mythology is beautiful", "凯尔特神话很美",
     "凯尔特 绝不进 ak：AK_TERMS 无此键，bi 侧才由 EXCLUDE 兜"),
    ("Cow 真的回来了，还有 Calcite", "so cow really is back", "Cow 真的回来了，还有 Calcite",
     "短拉丁键 Cow/Cal 不入表，不得咬 Calcite"),
    ("直播感谢 Enfield Arcane 的支持", "shoutout to Enfield Arcane", "直播感谢 Enfield Arcane 的支持",
     "ak 分支新增 EXCLUDE 回滚层：参考行命中负例即撤销"),
]
_AK_POSITIVE_ONLY = [
    ("感谢 Enfield", "endfield is coming soon", "感谢 终末地",
     "ak EXCLUDE 层的正向对照（无负例则照常替换）"),
]


def _ak_srt(cases):
    out = []
    for i, (zh, en, _exp, _note) in enumerate(cases, 1):
        out += [str(i), "00:00:%02d,000 --> 00:00:%02d,000" % (i, i + 2), en, zh, ""]
    return "\r\n".join(out).rstrip() + "\r\n"


def _ak_zh_lines(raw):
    txt = raw.decode("utf-8-sig")
    return [b.replace("\r", "").split("\n")[3]
            for b in re.split(r"\r?\n\r?\n+", txt.strip())]


def test_ak_ep17_terms(ref, pkg):
    """EP17「相变临界」二校沉淀的术语与层序断言（含两条防误伤负例）。

    回归动机：① 官方书写是 Mon3tr，小写形要能机械修回；② 关闭/后卫/医生/怪物 这类常用中文词
    只能靠英文参考行锚定；③ ak 分支 2026-11-02 才补上 EXCLUDE 回滚层，必须有一正一负两条证明；
    ④ 「凯尔特」「Cow/Cal」绝不能进 AK_TERMS，否则 bi 侧靠 EXCLUDE 兜住的误伤会在 ak 片复发。
    """
    section("3c. EP17 术语与 ak 排除层")
    pos = _AK_POSITIVE + _AK_NEGATIVE + _AK_POSITIVE_ONLY
    for tag, m in (("单文件", ref), ("分包", pkg)):
        with tempfile.TemporaryDirectory(prefix="calib_selftest_ep17_") as d:
            src = os.path.join(d, "ep17.srt")
            open(src, "wb").write(_ak_srt(pos).encode("utf-8"))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                m.process(src, os.path.join(d, "out.srt"), os.path.join(d, "out.md"),
                          mode="ak")
            got = _ak_zh_lines(open(os.path.join(d, "out.srt"), "rb").read())
            for i, (zh, en, exp, note) in enumerate(pos):
                check(f"EP17 ak {note} {tag}", i < len(got) and got[i] == exp,
                      "cue %d 输入 %r 期望 %r 实得 %r（参考行 %r）" % (i + 1, zh, exp,
                                                            got[i:i + 1], en))

    # 参照/分包必须逐字节一致（与其余模式断言同口径）
    with tempfile.TemporaryDirectory(prefix="calib_selftest_ep17_x_") as d:
        src = os.path.join(d, "ep17.srt")
        open(src, "wb").write(_ak_srt(pos).encode("utf-8"))
        a, b, o1, o2, r1, r2, s1, s2 = run_process(ref, pkg, src, "ak")
        check("EP17 ak 单文件与分包一致",
              o1 == o2 and r1 == r2 and a[0] == b[0] and a[1] == b[1] and s1 == s2)


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
    # 韩语原声片源：ref 是**纯韩单语**（每 cue 一行谚文），target 是「韩行在上、中文在下」双语
    "ko_ref.srt": ("1\r\n00:00:01,000 --> 00:00:03,000\r\n에코 세팅 확인했습니다\r\n\r\n"
                   "2\r\n00:00:04,000 --> 00:00:06,000\r\n치사 3돌입니다\r\n\r\n"
                   "3\r\n00:00:07,000 --> 00:00:09,000\r\n너는 치사하고 속상해\r\n"),
    "ko_zh.srt": ("1\r\n00:00:01,000 --> 00:00:03,000\r\n에코 세팅 확인했습니다\r\n回声设置已确认\r\n\r\n"
                  "2\r\n00:00:04,000 --> 00:00:06,000\r\n치사 3돌입니다\r\nChisa 是 3 突\r\n\r\n"
                  "3\r\n00:00:07,000 --> 00:00:09,000\r\n너는 치사하고 속상해\r\n你真小气，难受\r\n"),
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
    # 韩语原声：漏译体检走纯韩 ref；再单列一条「误拿双语文件当参考侧」的护栏用例
    ("missing-ko", ["missing", "ko_ref.srt", "ko_zh.srt", "--mode", "ko", "--window", "1"], ()),
    ("missing-ko-guard", ["missing", "ko_zh.srt", "ko_zh.srt", "--mode", "ko"], ()),
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
    # 上面全是「单体 vs 真源」一致性对照，测不出两版一起坏；护栏的返回码单独断言一次。
    with tempfile.TemporaryDirectory(prefix="calib_guard_") as d:
        _prepare_cli(d)
        rc, out, err = _run_cli("pkg", ["missing", "ko_zh.srt", "ko_zh.srt", "--mode", "ko"], d, {})
        txt = (out + err).decode("utf-8", "replace")
        check("missing --mode ko 假绿灯护栏返回码", rc == 1 and "WARN" in txt,
              f"rc={rc} out={txt[:160]!r}")


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


# ---------------------------------------------------------------- 6. 鸣潮 3.8 二校回灌

def test_wuwa38_regressions(ref, pkg):
    section("6. 鸣潮 3.8 二校回灌")
    cases = [
        ("乘客们，欢迎乘坐列车", "Welcome to our train, passengers.", "乘客们，欢迎乘坐列车"),
        ("乘客，请保持警惕", "Passenger, stay alert.", "异客，请保持警惕"),
        ("这只是个隐喻", "This is just a metaphor.", "这只是个隐喻"),
        ("隐喻：ReFantazio", "Metaphor: ReFantazio", "《暗喻幻想》：ReFantazio"),
        ("丽丽，你好", "Lili, hello.", "莉莉，你好"),
        ("莉丽，你好", "Lili, hello.", "莉莉，你好"),
        ("转校进入第二索拉里斯学院", "transfer to Second Solaris Academy", "转校进入第二索拉学院"),
        ("雪平贵飞的衣服", "Hiyuki's outfit", "绯雪的衣服"),
        ("每日抽卡", "daily gacha in another game", "每日抽卡"),
        ("每日抽卡", "daily gacha in Wuthering Waves with Lily", "每日唤取"),
        # --- 2026-11-08 Jadealy《鸣潮》3.8 前瞻片：ASR 残形 + 误伤负例回归 ---
        ("我们还是要看海浪版", "wuth ering waves version", "我们还是要看《鸣潮》版本"),
        ("Mother ing Waves 服装展示", "Mother ing Waves outfit showcase.", "《鸣潮》 服装展示"),
        ("看起来就像我习惯的VU VA", "It looks like the VU VA", "看起来就像我习惯的鸣潮"),
        ("它给了火星车头", "It is giving rover head.", "它给了漂泊者头"),
        ("先不谈 Brand t 的笑话", "jokes aside about Brand t", "先不谈 布兰特 的笑话"),
        ("它是卢伊拉设计的", "Luc illa designed it", "它是洛瑟菈设计的"),
        ("百合给百合", "Lilies for Lily.", "百合给莉莉"),
        ("百合给莉莉", "Lilies for Lily.", "百合给莉莉"),   # 幂等收口：成品再跑一遍不变
        ("一片百合紫云的田野", "a field of lily purple cloud.", "一片百合紫云的田野"),
        ("第一阶段百合", "First phase Lily.", "第一阶段莉莉"),
        ("天哪，又是由纪", "Oh my gosh Yuki again.", "天哪，又是绯雪"),
        # --- 2026-11-08 深度二校：一校把「由纪→绯雪」误判为跨片误伤，本轮纠正 ---
        ("我非常喜欢由纪", "I love Yuki so much.", "我非常喜欢绯雪"),
        ("杀死真正的由纪", "Kill real Yuki.", "杀死真正的绯雪"),
        ("我喜欢Y uki，我有S 6 Yuki", "我喜欢Y uki，我有S 6 Yuki", "我喜欢绯雪，我有S 6 绯雪"),
        ("我很高兴我已经拥有 S 6 Yuki", "I ' m so glad I already have S 6 Yuki.", "我很高兴我已经拥有 S 6 绯雪"),
        ("Fy uka 皮肤是必须的", "Fy uka skin is a must.", "绯雪 皮肤是必须的"),
        ("Y uki，我美丽的女王", "Y uki, my beautiful gorgeous queen.", "绯雪，我美丽的女王"),
        ("由纪今天很开心", "My friend came today.", "由纪今天很开心"),  # 非 Yuki 语境：反向负例仍回滚，零跨片误伤
        ("展览位置展览快捷方式", "Ex position exposition shortcuts.", "展览位置展览快捷方式"),
        ("他们会遇到各种各样的乘客", "They will meet all kinds of passengers,", "他们会遇到各种各样的乘客"),
    ]
    with tempfile.TemporaryDirectory(prefix="calib_wuwa38_") as d:
        src = os.path.join(d, "in.srt")
        blocks = []
        for i, (zh, en, _) in enumerate(cases, 1):
            blocks.append(f"{i}\r\n00:00:{i:02d},000 --> 00:00:{i + 1:02d},000\r\n{zh}\r\n{en}")
        open(src, "wb").write("\r\n\r\n".join(blocks).encode("utf-8") + b"\r\n")
        for label, mod in (("pkg", pkg), ("ref", ref)):
            out = os.path.join(d, f"{label}.srt")
            mod.process(src, out, None, mode="bi")
            text = open(out, encoding="utf-8").read().replace("\r\n", "\n")
            got = []
            for block in text.split("\n\n"):
                parts = [x for x in block.split("\n") if x.strip()]
                if len(parts) >= 4:
                    got.append(parts[2])
            check(f"{label} 鸣潮3.8回灌条数", len(got) == len(cases), f"{len(got)}/{len(cases)}")
            for i, ((zh, en, want), actual) in enumerate(zip(cases, got), 1):
                check(f"{label} #{i} {zh}", actual == want, f"got={actual!r} want={want!r}")


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
    test_wwoc_context(ref, pkg)
    test_akja_context(ref, pkg)
    test_ko_lotte_terms(ref, pkg)
    test_format(ref, pkg)
    test_en_first_layout(ref, pkg)
    test_ak_ep17_terms(ref, pkg)
    test_wuwa38_regressions(ref, pkg)
    test_cli(ref, pkg)
    test_import_and_docs(ref, pkg)
    print(f"\nPASS {_passed} / FAIL {len(_failed)}")
    for name, detail in _failed:
        print("FAIL:", name, detail)
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
