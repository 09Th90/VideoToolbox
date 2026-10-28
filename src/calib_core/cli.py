# -*- coding: utf-8 -*-
# @version 2.8.0
"""CLI 参数解析与子命令分发

源：subtitle_calib_merged.py L13295-L13650 @ 97d7d463（2026-10-24 冻结快照）
"""
import io
import os
import re
import shutil
import sys
import unicodedata
from ._doc import USAGE_DOC
from .data.modes import AK_INFO, AK_KO_INFO, ENDO_INFO, KO_INFO, PGR_INFO, PGR_OVERRIDES_SRC, WWOC_INFO, ZHO_INFO
from .engine import _load_override_tsv, process
from .format import _cmd_flow, _cmd_length, _cmd_rewrap, _cmd_stabilize
from .inspect import _cmd_align_audit, _cmd_compare, _cmd_lint, _cmd_missing, _cmd_scan, _cmd_scan_split, _cmd_subfix, _cmd_terms_check, _cmd_verify
from .kb import _cmd_audit, _cmd_kb_export, _cmd_kb_lint, _cmd_kb_lookup
from .learn import LEARNED_KB_DEFAULT, _cmd_learn, _cmd_learned_promote, _cmd_learned_reject, _cmd_learned_show, _learned_terms_for_mode
from .modes import detect_source_mode
from .srt import _cmd_extract, _cmd_merge, _cmd_pair, _cmd_split
from .sync import _cmd_kb_push, _cmd_kb_sync, _sync_inject_all, _sync_maybe_auto



def main_argv():
    argv = sys.argv[1:]
    if argv and not argv[0].startswith("-"):
        sub = argv[0]
        if sub in ("extract", "split", "pair", "merge", "verify", "compare", "scan", "lint",
                   "scan-split", "scansplit", "missing", "subfix", "terms-check", "termscheck",
                   "terms", "length", "flow", "align-audit", "alignaudit", "rewrap",
                   "stabilize",
                   "kb-export", "kb-lookup", "kb-lint",
                   "learn", "learned-show", "learned-promote", "learned-reject",
                   "kb-sync", "kb-push", "detect-mode", "detectmode",
                   "audit"):
            # length 用退出码当门禁（超限 1），其余子命令返回 None -> 0
            sys.exit(_dispatch_subcommand(sub, argv[1:]) or 0)

    src = None
    out_path = report_path = None
    mode = "bi"
    fix_en = False
    learned_kb = None

    if argv and not argv[0].startswith("-"):
        src = argv[0]
    args = argv[1:] if (argv and not argv[0].startswith("-")) else argv
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--out" and i + 1 < len(args):
            out_path = args[i + 1]; i += 2
        elif a == "--report" and i + 1 < len(args):
            report_path = args[i + 1]; i += 2
        elif a == "--ko":
            mode = "ko"; i += 1
        elif a == "--ja":
            mode = "ja"; i += 1
        elif a == "--jpe":
            mode = "jpe"; i += 1
        elif a == "--wwoc":
            mode = "wwoc"; i += 1
        elif a == "--ak":
            mode = "ak"; i += 1
        elif a == "--akko":
            mode = "akko"; i += 1
        elif a == "--zho":
            mode = "zho"; i += 1
        elif a == "--endo":
            mode = "endo"; i += 1
        elif a == "--endobi":
            mode = "endobi"; i += 1
        elif a == "--endoko":
            mode = "endoko"; i += 1
        elif a == "--pgr":
            mode = "pgr"; i += 1
        elif a == "--pgren":
            mode = "pgren"; i += 1
        elif a == "--react":
            mode = "react"; i += 1
        elif a == "--limbus":
            mode = "limbus"; i += 1
        elif a == "--ffrs":
            mode = "ffrs"; i += 1
        elif a == "--zel":
            mode = "zel"; i += 1
        elif a == "--hsr":
            mode = "hsr"; i += 1
        elif a == "--pkm":
            mode = "pkm"; i += 1
        elif a == "--fix-en":
            fix_en = True; i += 1
        elif a == "--kb" and i + 1 < len(args):
            learned_kb = args[i + 1]; i += 2
        elif a == "--mode" and i + 1 < len(args):
            m = args[i + 1].lower()
            if m in ("limbus", "limbuscompany", "边狱巴士"):
                mode = "limbus"
            elif m in ("ffrs", "ffresonance", "finalfantasyresonance", "共鸣"):
                mode = "ffrs"
            elif m in ("pkm", "pokemon", "pokémon", "pocket_monsters"):
                mode = "pkm"
            elif m in ("hsr", "starrail", "star_rail", "honkai_starrail", "honkaistarrail"):
                mode = "hsr"
            else:
                mode = "ja" if m in ("ja", "japanese") else ("ko" if m in ("ko", "korean") else ("ak" if m in ("ak", "arknights") else ("zho" if m in ("zho", "zhonly", "zh_only") else ("endo" if m in ("endo", "endfield") else ("zel" if m in ("zel", "zelda", "legend of zelda", "zelda_direct") else "bi")))))
            i += 2
        else:
            i += 1

    info = {"ko": KO_INFO, "ak": AK_INFO, "endo": ENDO_INFO, "pgr": PGR_INFO, "zho": ZHO_INFO, "wwoc": WWOC_INFO, "akko": AK_KO_INFO}.get(mode)
    if src is None and info:
        src = info["src"]                       # 一键重跑内置片源
        if out_path is None:
            out_path = info["dst"]
    if src is None:
        print(USAGE_DOC)
        return

    # 学习库：--kb 指定；未指定时若 cwd 存在默认库则自动加载（confirmed 规则自动生效）
    if learned_kb is None and os.path.exists(LEARNED_KB_DEFAULT):
        learned_kb = LEARNED_KB_DEFAULT
    pgr_override = _load_override_tsv(PGR_OVERRIDES_SRC) if mode == "pgr" else None
    _sync_maybe_auto()          # v1.11.0：校准入口自动拉取+应用增量（幂等，失败静默降级）
    _sync_inject_all()          # 兜底：applied.json 生效条目注入本地表
    rows, hits = process(src, out_path, report_path, mode=mode,
                         fix_en=fix_en, pgr_override=pgr_override,
                         learned_kb=learned_kb)
    names = {"bi": "中英双语 (BILINGUAL_TERMS + CONTEXT_MAP + WORD_MAP)",
             "ko": "韩语原声 (KO_TERMS)",
             "ja": "日语原声 (JA_TERMS + JA_CONTEXT)",
             "jpe": "日语原声·终末地 (JA_ENDFIELD_TERMS + JA_ENDFIELD_CONTEXT)",
             "wwoc": "综合手游OST世界杯 (WWOC_TERMS)",
             "ak": "明日方舟本体 (AK_TERMS + AK_CONTEXT)",
             "akko": "明日方舟韩语原声 (AK_KO_TERMS + AK_KO_CONTEXT)",
             "zho": "中文行专属 (ZH_ONLY_TERMS)",
             "endo": "终末地 (ENDFIELD_TERMS)",
             "endobi": "终末地·中英双语 (ENDFIELD_BI_TERMS)",
             "endoko": "终末地·韩语原声 (ENDFIELD_KO_TERMS)",
             "pgr": "战双帕弥什 (PGR 侧车整行覆盖, {} 条)".format(len(pgr_override) if pgr_override else 0),
             "pgren": "战双帕弥什·英文原声 (PGR_EN_TERMS)",
             "react": "音乐/演唱点评 (REACT_TERMS)",
             "zel": "塞尔达传说 (ZELDA_TERMS)",
             "hsr": "崩坏：星穹铁道 (HSR_TERMS + HSR_CONTEXT)",
             "limbus": "边狱巴士 (LIMBUS_TERMS + LIMBUS_CONTEXT)",
             "ffrs": "最终幻想：共鸣 (FFRS_TERMS + FFRS_CONTEXT)",
             "pkm": "宝可梦城镇主题 (POKEMON_TERMS + POKEMON_CONTEXT)"}
    extra = (" + 英文行修正(--fix-en)" if fix_en else "")
    print("模式:", names[mode] + extra)
    if learned_kb:
        n_conf = len(_learned_terms_for_mode(learned_kb, mode))
        print(f"学习库: {learned_kb}（本模式 confirmed 规则 {n_conf} 条已注入）")
    print("存在术语表错误形式的块:", hits if hits else "无（已统一）")
    if out_path:
        print(f"已写入：{out_path}（{len(rows)} 处文本改动，序号/时间轴/空行/换行/BOM 保持原样）")
    if report_path:
        print(f"报告：{report_path}（{len(rows)} 处文本改动）")



def _dispatch_subcommand(sub, args):
    """解析流式子命令参数并执行。"""
    pos = [a for a in args if not a.startswith("-")]
    opts = {}
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--n" and i + 1 < len(args):
            opts["n"] = int(args[i + 1]); i += 2
        elif a == "--min" and i + 1 < len(args):
            opts["min"] = int(args[i + 1]); i += 2
        elif a == "--fix":
            opts["fix"] = True; i += 1
        elif a == "--quiet":
            opts["quiet"] = True; i += 1
        elif a == "--strict":
            opts["strict"] = True; i += 1
        elif a == "--window" and i + 1 < len(args):
            opts["window"] = int(args[i + 1]); i += 2
        elif a == "--ratio" and i + 1 < len(args):
            opts["ratio"] = float(args[i + 1]); i += 2
        elif a == "--min-ratio" and i + 1 < len(args):
            opts["min_ratio"] = float(args[i + 1]); i += 2
        elif a == "--all":
            opts["all"] = True; i += 1
        elif a == "--fix-style":
            opts["fix-style"] = True; i += 1
        elif a == "--single":
            opts["single"] = True; i += 1
        elif a in ("--drop", "--merge", "--split"):
            opts[a[2:]] = True; i += 1
        elif a in ("--no-drop", "--no-merge", "--no-split"):
            opts[a[5:]] = False; i += 1
        elif a in ("--out", "--compare", "--side", "--letters", "--file", "--width",
                   "--report") and i + 1 < len(args):
            opts[a[2:]] = args[i + 1]; i += 2
        elif a == "--json":
            opts["json"] = True; i += 1
        elif a == "--loose":
            opts["loose"] = True; i += 1
        elif a == "--entities":
            opts["entities"] = True; i += 1
        elif a in ("--kb", "--mode", "--learned") and i + 1 < len(args):
            opts[a[2:]] = args[i + 1]; i += 2
        else:
            i += 1
    if sub == "extract":
        if len(pos) < 2:
            print("用法: extract <src.srt> <cues.tsv>"); return
        _cmd_extract(pos[0], pos[1])
    elif sub in ("detect-mode", "detectmode"):
        if not pos:
            print("用法: detect-mode <src.srt>"); return
        print("DETECT=" + detect_source_mode(pos[0]))
    elif sub == "split":
        if len(pos) < 2:
            print("用法: split <cues.tsv> <outprefix> --n <N>"); return
        _cmd_split(pos[0], pos[1], opts.get("n", 6))
    elif sub == "pair":
        if len(pos) < 2:
            print("用法: pair <seg_X.tsv> <纯文本.txt> [--out calib_X.tsv]"); return
        return _cmd_pair(pos[0], pos[1], opts.get("out"))
    elif sub == "merge":
        if len(pos) < 2 or "out" not in opts:
            print("用法: merge <src.srt> <校准表|目录> --out out.srt [--compare tsv] [--side tsv] [--fix]"); return
        _cmd_merge(pos[0], pos[1], opts["out"], opts.get("compare"), opts.get("side"), opts.get("fix", False))
    elif sub in ("align-audit", "alignaudit"):
        if len(pos) < 2:
            print("用法: align-audit <src.srt> <out.srt> [--window 5] [--ratio 1.45] [--quiet]"); return
        return _cmd_align_audit(pos[0], pos[1], opts.get("window", 5),
                                opts.get("ratio", 1.45), opts.get("min_ratio", 0.45),
                                opts.get("quiet", False), opts.get("strict", False))
    elif sub == "verify":
        if len(pos) < 2:
            print("用法: verify <src.srt> <out.srt>"); return
        _cmd_verify(pos[0], pos[1])
    elif sub == "compare":
        if len(pos) < 3:
            print("用法: compare <src.srt> <out.srt> <对照.tsv>"); return
        _cmd_compare(pos[0], pos[1], pos[2])
    elif sub == "scan":
        if not pos:
            print("用法: scan <cues.tsv> [--min 2]"); return
        _cmd_scan(pos[0], opts.get("min", 2))
    elif sub in ("scan-split", "scansplit"):
        if not pos:
            print("用法: scan-split <a.srt> [b.srt ...] [--min 1]"); return
        return _cmd_scan_split(pos, opts.get("min", 1))
    elif sub == "missing":
        if len(pos) < 2:
            print("用法: missing <英文参考.srt> <中文.srt> [--mode endo|wuwa] [--file 映射.tsv] [--window 1] [--quiet]")
            print("      漏译体检：英文 cue 有术语而中文 cue 无对应词 → 报疑似漏译（只读，命中退出码 1）")
            print("      --mode wuwa：鸣潮专名表（守岸人/鸣式/残象/残星会/岁主/阿布/新联邦）")
            print("      --window 1：邻接 cue 已译即不算漏译（战斗词跨 cue 断行时用，避免误报）")
            return
        return _cmd_missing(pos[0], pos[1], opts.get("mode"), opts.get("file"),
                            bool(opts.get("quiet")), int(opts.get("window", 0)))
    elif sub == "lint":
        if len(pos) < 2:
            print("用法: lint <cues.tsv> <calib目录|calib_*.tsv>"); return
        _cmd_lint(pos[0], pos[1])
    elif sub == "rewrap":
        if not pos:
            print("用法: rewrap <src.srt> [--out out.srt] [--width 32] [--report md]"); return
        return _cmd_rewrap(pos[0], opts.get("out"), opts.get("width"), opts.get("report"))
    elif sub == "subfix":
        if len(pos) < 2 or "out" not in opts:
            print("用法: subfix <src.srt> <fix.tsv> --out out.srt [--compare tsv] [--side tsv] [--single] [--strict]"); return
        return _cmd_subfix(pos[0], pos[1], opts["out"], opts.get("compare"), opts.get("side"),
                           single=bool(opts.get("single")), strict=bool(opts.get("strict")))
    elif sub == "length":
        if not pos:
            print("用法: length <a.srt> [b.srt ...] [--all]"); return 0
        return _cmd_length(pos, show_all=bool(opts.get("all")))
    elif sub == "flow":
        if not pos:
            print("用法: flow <src.srt> [--out out.srt] [--fix-style]"); return 0
        return _cmd_flow(pos[0], opts.get("out"), bool(opts.get("fix-style")))
    elif sub == "stabilize":
        if not pos:
            print("用法: stabilize <src.srt> [--out out.srt] [--report r.md] "
                  "[--drop] [--merge] [--split] [--no-drop] [--no-merge] [--no-split]")
            print("      SRT cue 级稳定化（对标 FineSub ASR 稳定化层）。不带 --out 只出"
                  "报告（退出码 1＝有候选）；带 --out 才应用显式开启的操作。")
            return 0
        return _cmd_stabilize(pos[0], opts.get("out"), opts.get("report"),
                              bool(opts.get("drop", True)),
                              bool(opts.get("merge", True)),
                              bool(opts.get("split", True)))
    elif sub in ("terms-check", "termscheck", "terms"):
        _cmd_terms_check(pos)
    elif sub == "audit":
        if not pos:
            print("用法: audit <校准后.srt> [--mode bi] [--out 报告.md] [--json] [--loose]")
            print("      名词漏校三扫：拉丁残留 / 知识库错形残留 / 同词族一致性。")
            print("      退出码 1＝有候选（可当门禁），0＝干净。")
            return 1
        return _cmd_audit(pos[0], opts.get("mode", "bi"), opts.get("out"),
                          bool(opts.get("json")), loose=bool(opts.get("loose")))

    elif sub == "kb-export":
        _cmd_kb_export(opts.get("out"), as_json=bool(opts.get("json")))
    elif sub == "kb-lookup":
        if not pos:
            print("用法: kb-lookup <词>"); return
        _cmd_kb_lookup(pos[0])
    elif sub == "kb-lint":
        _cmd_kb_lint()
    elif sub == "learn":
        if len(pos) < 2:
            print("用法: learn <原始.srt> <人工校准.srt> [--mode bi] [--kb 学习库.json]"); return
        _cmd_learn(pos[0], pos[1], opts.get("kb", LEARNED_KB_DEFAULT),
                   mode=opts.get("mode", "bi"))
    elif sub == "learned-show":
        _cmd_learned_show(opts.get("kb", LEARNED_KB_DEFAULT), mode=opts.get("mode"))
    elif sub == "learned-promote":
        _cmd_learned_promote(opts.get("kb", LEARNED_KB_DEFAULT),
                             mode=opts.get("mode"), entities=bool(opts.get("entities", True)))
    elif sub == "learned-reject":
        if not pos:
            print("用法: learned-reject <错形> [--mode bi] [--kb 学习库.json]"); return
        _cmd_learned_reject(pos[0], opts.get("kb", LEARNED_KB_DEFAULT),
                            mode=opts.get("mode"))
    elif sub == "kb-sync":
        _cmd_kb_sync()
    elif sub == "kb-push":
        _cmd_kb_push(learned=opts.get("learned") or opts.get("kb"),
                     file=opts.get("file"))

