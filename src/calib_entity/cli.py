# @version 2.6.0
"""对象级校准并行包 —— 命令行入口。

用法（cwd = 程序根）：

    python calib_entity/cli.py summary
    python calib_entity/cli.py export [--out data/entities/entities.json]
    python calib_entity/cli.py lint [--json] [--out 报告.md] [--fail-on error]
    python calib_entity/cli.py index --mode bi
    python calib_entity/cli.py verify  --mode bi <片源.srt> [--limit 500] [--json]
    python calib_entity/cli.py onepass --mode bi <片源.srt> [--limit 500] [--json]

也可用 ``python -m calib_entity.cli ...``。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

if __package__ in (None, ""):                      # 允许 `python calib_entity/cli.py`
    _PKG_PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _PKG_PARENT not in sys.path:
        sys.path.insert(0, _PKG_PARENT)
    from calib_entity import index as index_mod
    from calib_entity import lint as lint_mod
    from calib_entity import shadow as shadow_mod
    from calib_entity import spec as spec_mod
    from calib_entity.opt import adopt as adopt_mod
    from calib_entity.opt import kb_inject as inject_mod
    from calib_entity.opt import kb_scope as scope_mod
    from calib_entity.opt import source_guard as guard_mod
    from calib_entity.wiki import fetch as wiki_fetch
else:
    from . import index as index_mod
    from . import lint as lint_mod
    from . import shadow as shadow_mod
    from . import spec as spec_mod
    from .opt import adopt as adopt_mod
    from .opt import kb_inject as inject_mod
    from .opt import kb_scope as scope_mod
    from .opt import source_guard as guard_mod
    from .wiki import fetch as wiki_fetch


def _root() -> str:
    return spec_mod.project_root()


def _dump(obj, as_json: bool, text: str = "") -> None:
    if as_json:
        print(json.dumps(obj, ensure_ascii=False, indent=2))
    else:
        print(text or json.dumps(obj, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------- 子命令


def cmd_summary(args) -> int:
    eng = spec_mod.load_engine()
    reg = spec_mod.build_registry(eng)
    s = spec_mod.summary(reg)
    if args.json:
        print(json.dumps(s, ensure_ascii=False, indent=2))
        return 0
    print("对象库摘要（只读自 subtitle_calib_merged）")
    print(f"  对象总数            {s['objects']}")
    print(f"  可执行对象          {s['executable']}  ({s['executable_ratio_pct']}%)")
    print(f"  有对象身份(Entity)  {s['entity_objects']}  ({s['objectified_ratio_pct']}%)")
    print(f"  空壳对象            {s['hollow']}（其中 OST 曲名 {s['hollow_ost']}）")
    print(f"  重复登记 canonical  {s['dup_canonical']} 个（多余条目 {s['dup_extra_entries']}）")
    print(f"  无适用模式          {s['no_modes']}")
    print(f"  外文名 EN/JA/KO     {s['has_en']}/{s['has_ja']}/{s['has_ko']}")
    print(f"  变体 / ctx          {s['variants_total']} / {s['ctx_total']}")
    print(f"  别名候选            {s['alias_candidates']}")
    top_kind = list(s["by_kind"].items())[:6]
    print("  按类型：" + "、".join(f"{k}={v}" for k, v in top_kind)
          + (f" …（共 {len(s['by_kind'])} 类）" if len(s["by_kind"]) > 6 else ""))
    return 0


def cmd_export(args) -> int:
    eng = spec_mod.load_engine()
    reg = spec_mod.build_registry(eng)
    out = args.out or os.path.join(_root(), "data", "entities", "entities.json")
    path = spec_mod.export_json(reg, out)
    print(f"对象库已导出：{path}")
    print(f"  对象 {len(reg)} 个")
    return 0


def cmd_lint(args) -> int:
    eng = spec_mod.load_engine()
    reg = spec_mod.build_registry(eng)
    res = lint_mod.run_lint(reg, eng, cascade=not args.no_cascade)
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        md = lint_mod.render_markdown(res, limit=args.limit)
        if args.out:
            with open(args.out, "w", encoding="utf-8", newline="\n") as f:
                f.write(md + "\n")
            print(f"体检报告已写入：{args.out}")
            print(f"  error {res['counts'].get('error', 0)} | "
                  f"warn {res['counts'].get('warn', 0)} | "
                  f"info {res['counts'].get('info', 0)}")
        else:
            print(md)
    if args.fail_on == "error" and res["counts"].get("error", 0):
        return 1
    if args.fail_on == "warn" and (res["counts"].get("error", 0) or
                                   res["counts"].get("warn", 0)):
        return 1
    return 0


def cmd_index(args) -> int:
    eng = spec_mod.load_engine()
    idx = index_mod.ModeIndex.build(args.mode, engine=eng)
    st = idx.stats()
    if args.json:
        print(json.dumps(st, ensure_ascii=False, indent=2))
        return 0
    print(f"模式 {st['mode']} 对象索引")
    for k in ("keys", "targets", "charset", "ac_nodes", "longest_key", "avg_key_len"):
        print(f"  {k:14s} {st[k]}")
    return 0


def cmd_verify(args) -> int:
    eng = spec_mod.load_engine()
    rep = shadow_mod.verify_index_equivalence(
        args.mode, args.src, engine=eng, limit=args.limit)
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        md = shadow_mod.render_markdown(rep)
        if args.out:
            with open(args.out, "w", encoding="utf-8", newline="\n") as f:
                f.write(md + "\n")
            print(f"报告已写入：{args.out}")
        print(f"[verify] {rep['verdict']}  行 {rep['lines']} / 一致 {rep['identical']} / "
              f"差异 {rep['differ']} ({rep['differ_ratio_pct']}%) / "
              f"需重扫 {rep['needs_rescan']} / 回退可复现 {rep['fallback_ok']}")
    return 0 if rep["verdict"].startswith("EQUIVALENT") else 1


def cmd_onepass(args) -> int:
    eng = spec_mod.load_engine()
    rep = shadow_mod.diff_onepass(args.mode, args.src, engine=eng, limit=args.limit)
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        md = shadow_mod.render_markdown(rep)
        if args.out:
            with open(args.out, "w", encoding="utf-8", newline="\n") as f:
                f.write(md + "\n")
            print(f"报告已写入：{args.out}")
        print(f"[onepass] 行 {rep['lines']} / 一致 {rep['identical']} / "
              f"差异 {rep['differ']} ({rep['differ_ratio_pct']}%) / "
              f"原因 {rep['reasons']}")
    return 0


# ---------------------------------------------------------------- 优化补丁


def cmd_source(args) -> int:
    """片源识别：标题/文件名/台词三通道。"""
    lines = guard_mod.read_srt_lines(args.src) if args.src else None
    title = args.title or ""
    if not title and args.src:
        title = os.path.splitext(os.path.basename(args.src))[0]
    rep = guard_mod.infer_mode(title=title, filename=args.src or "", lines=lines)
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        return 0
    print(f"片源模式：{rep['mode']}  置信度 {rep['confidence']}  作品 {rep['work'] or '未判定'}")
    for r in rep["reasons"]:
        print(f"  依据：{r}")
    print("  各作品得分：")
    for work, sc in rep["scores"].items():
        if sc["title"] or sc["filename"] or sc["lines"]:
            print(f"    {work:8s} 标题{sc['title']} 文件名{sc['filename']} 台词{sc['lines']}"
                  + (f"  证据 {', '.join(sc['evidence'])}" if sc["evidence"] else ""))
    return 0


def cmd_scope(args) -> int:
    """作品维度隔离：看哪些词该进、哪些被拦。"""
    eng = spec_mod.load_engine()
    reg = spec_mod.build_registry(eng)
    if args.explain:
        words = [w.strip() for w in args.explain.split(",") if w.strip()]
        rows = scope_mod.explain(reg, args.mode, args.work, words, engine=eng)
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
        else:
            for r in rows:
                print(f"  {r['word']:12s} {r['state']:9s} {r.get('owner',''):10s} {r['why']}")
        return 0
    kept, dropped = scope_mod.filter_registry(reg, args.work)
    kept_t, dropped_t = scope_mod.filter_terms(eng, reg, args.mode, args.work)
    cov = scope_mod.coverage(reg)
    if args.json:
        print(json.dumps({
            "work": args.work, "objects": len(reg), "kept": len(kept),
            "dropped": [{"object": c, "work": w, "why": y} for c, w, y in dropped],
            "terms": {"mode": args.mode, "kept": len(kept_t),
                      "dropped": len(dropped_t),
                      "dropped_items": [{"wrong": w, "right": r, "work": ow, "why": y}
                                        for w, r, ow, y in dropped_t[:50]]},
            "coverage": cov,
        }, ensure_ascii=False, indent=2))
        return 0
    print(f"作品「{args.work}」")
    print(f"  对象级：保留 {len(kept)} / {len(reg)}，隔离 {len(dropped)} 个专名")
    print(f"  词条级（{args.mode}）：保留 {len(kept_t)}，隔离 {len(dropped_t)} 条")
    print(f"  作品可判定率：{cov['work_tagged']}/{cov['objects']} "
          f"({cov['work_tagged_pct']}%)，未标注 {cov['unknown']}")
    print("  按作品：" + "、".join(f"{k}={v}" for k, v in cov["by_work"].items()))
    if dropped_t:
        print("  被隔离的词条（前 10）：")
        for w, r, ow, why in dropped_t[:10]:
            print(f"    ✗ {w} → {r}（{ow}）")
    for c, w, why in dropped[:args.limit]:
        print(f"    ✗ {c:12s} 属于「{w}」 — {why}")
    if len(dropped) > args.limit:
        print(f"    … 另有 {len(dropped) - args.limit} 个")
    return 0


def cmd_inject(args) -> int:
    """知识注入安全化：对比「外文名当错形」与安全口径的规则差。"""
    eng = spec_mod.load_engine()
    reg = spec_mod.build_registry(eng)
    rep = inject_mod.compare(reg, args.mode, args.work)
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    else:
        print(inject_mod.render(rep))
    return 0


def cmd_adopt(args) -> int:
    """采纳报告第四节的官方中文核对条目。"""
    items = adopt_mod.parse_report(args.md)
    keep, drop = adopt_mod.select(items, min_conf=args.min_conf)
    pairs = [(it["wrong"], it["right"]) for it in keep]
    if args.json:
        print(json.dumps({
            "report": args.md, "parsed": len(items),
            "accepted": keep, "dropped": drop,
        }, ensure_ascii=False, indent=2))
    else:
        print(f"报告条目 {len(items)}：采纳 {len(keep)}，丢弃 {len(drop)}")
        for it in keep:
            print(f"  ✓ {it['wrong']} → {it['right']}（把握 {it['confidence']}）")
        for it in drop:
            print(f"  · {it['wrong']} → {it['right']}：{it['why']}")
    if args.emit:
        print()
        print(adopt_mod.emit_python(pairs, table=args.emit))
    if args.apply and pairs:
        res = adopt_mod.apply_srt(args.apply, pairs, out_path=args.out or None)
        print(f"\n已应用 {res['changed']} 处 → {res['out']} "
              f"(CRLF={res['crlf']} BOM={res['bom']})")
        for num, old, new in res["rows"][:10]:
            print(f"  #{num} {old[:40]} → {new[:40]}")
    return 0


def cmd_wiki(args) -> int:
    """从四个 wiki 抓角色名单，补全对象库的作品归属。"""
    eng = spec_mod.load_engine()
    reg = spec_mod.build_registry(eng)
    data = wiki_fetch.fetch_all(pause=args.pause)
    m = wiki_fetch.match(reg, data)
    rep = wiki_fetch.build_report(reg, data, m["matched"], m["patches"])
    if args.json:
        print(json.dumps({"report": rep, "conflicts": m["conflicts"],
                          "patches": m["patches"]}, ensure_ascii=False, indent=2))
    else:
        print(f"对象 {rep['objects']} | 作品标注 {rep['work_tagged_before']} "
              f"({rep['work_tagged_before_pct']}%) -> {rep['work_tagged_after']} "
              f"({rep['work_tagged_after_pct']}%)")
        print(f"  wiki 命中 {rep['work_matched_by_wiki']}：{rep['wiki_counts']}")
        print(f"  置信度 {rep['patch_confidence']}"
              + (f"，冲突 {len(m['conflicts'])}" if m["conflicts"] else ""))
        for p in m["patches"][:args.limit]:
            flag = {"high": "✓", "medium": "·", "low": "?"}.get(p["confidence"], "?")
            print(f"  {flag} {p['id']:12s} -> {p['work']:6s} [{p['confidence']}] {p['evidence']}")
        if len(m["patches"]) > args.limit:
            print(f"  … 另有 {len(m['patches']) - args.limit} 条")
    if args.out:
        import datetime
        payload = {
            "schema": "calib-entity-wiki/1",
            "generated": datetime.datetime.now().isoformat(timespec="seconds"),
            "sources": {w: {"api": d["api"], "per_category": d["per_category"]}
                        for w, d in data.items()},
            "report": rep, "conflicts": m["conflicts"], "patches": m["patches"],
        }
        wiki_fetch.save(payload, args.out)
        print(f"补丁已写入：{args.out}")
    return 0


# ---------------------------------------------------------------- 入口


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="calib_entity",
        description="对象级校准并行包（只读主脚本，不修改 subtitle_calib_merged.py）")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("summary", help="对象库摘要")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_summary)

    s = sub.add_parser("export", help="导出对象库 JSON（P0 产物）")
    s.add_argument("--out", default="")
    s.set_defaults(fn=cmd_export)

    s = sub.add_parser("lint", help="对象级体检")
    s.add_argument("--json", action="store_true")
    s.add_argument("--out", default="")
    s.add_argument("--limit", type=int, default=30)
    s.add_argument("--no-cascade", action="store_true", help="跳过子串级联检查（较慢）")
    s.add_argument("--fail-on", choices=["none", "error", "warn"], default="none")
    s.set_defaults(fn=cmd_lint)

    s = sub.add_parser("index", help="查看某模式的对象索引规模")
    s.add_argument("--mode", default="bi")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_index)

    s = sub.add_parser("verify", help="等价性验证：索引预筛 vs 全表串行（必须 0 差异）")
    s.add_argument("src")
    s.add_argument("--mode", default="bi")
    s.add_argument("--limit", type=int, default=0, help="只扫前 N 行文本（0=全量）")
    s.add_argument("--json", action="store_true")
    s.add_argument("--out", default="")
    s.set_defaults(fn=cmd_verify)

    s = sub.add_parser("onepass", help="语义分叉量化：单遍最长 vs 串行")
    s.add_argument("src")
    s.add_argument("--mode", default="bi")
    s.add_argument("--limit", type=int, default=0)
    s.add_argument("--json", action="store_true")
    s.add_argument("--out", default="")
    s.set_defaults(fn=cmd_onepass)

    # --- 优化补丁 -------------------------------------------------
    s = sub.add_parser("source", help="片源识别（标题/文件名/台词三通道）")
    s.add_argument("src", nargs="?", default="")
    s.add_argument("--title", default="")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_source)

    s = sub.add_parser("scope", help="作品维度隔离（防跨作品词条污染）")
    s.add_argument("--work", required=True, help="目标作品，如 终末地 / 鸣潮 / 明日方舟")
    s.add_argument("--mode", default="bi")
    s.add_argument("--explain", default="", help="逗号分隔，逐个说明进/不进及原因")
    s.add_argument("--limit", type=int, default=20)
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_scope)

    s = sub.add_parser("inject", help="知识注入安全化：外文官方名不该当错形")
    s.add_argument("--mode", default="bi")
    s.add_argument("--work", default="", help="按作品隔离（如 终末地）")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_inject)

    s = sub.add_parser("wiki", help="从四个 wiki 抓角色名单，补全作品归属")
    s.add_argument("--out", default="data/entities/wiki_supplement.json")
    s.add_argument("--limit", type=int, default=15)
    s.add_argument("--pause", type=float, default=0.35)
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_wiki)

    s = sub.add_parser("adopt", help="采纳 .calib.md 第四节的官方中文核对")
    s.add_argument("md")
    s.add_argument("--min-conf", choices=["高", "中"], default="高")
    s.add_argument("--apply", default="", help="直接应用到该 srt（默认原地覆盖）")
    s.add_argument("--out", default="", help="应用时的输出路径（默认原地）")
    s.add_argument("--emit", default="", help="生成术语表片段，参数为表名")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_adopt)

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
