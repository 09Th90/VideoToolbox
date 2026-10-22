# @version 2.5.3
"""并行包自检（正向 + 负向）。

运行：``tools\\python\\python.exe calib_entity/_selftest.py``

铁律：只做正向校验等于没检查。每个「检查能力」都必须配一条**故意弄坏**的负向用例，
且负向用例不能改真实源码（全部在内存里构造假对象/假映射）。

覆盖：
  A 自动机    基本匹配 / 最长优先 / 重叠丢弃 / candidates 全集
  B 等价性    索引预筛 vs 全表串行（真实片源抽样）+ 自吞用例的负向检出
  C 对象库    对象数 / 唯一性 / 重复登记计数
  D 体检      长键序违例、一词多目标的负向检出（假 engine）
  E 汇总      PASS/FAIL 计数与退出码
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_PARENT = os.path.dirname(_HERE)
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)

from calib_entity.index import Automaton, ModeIndex          # noqa: E402
from calib_entity import lint as lint_mod                    # noqa: E402
from calib_entity import shadow as shadow_mod                # noqa: E402
from calib_entity import spec as spec_mod                    # noqa: E402

PASS = 0
SKIP = 0
FAIL = 0
FAILED: list = []

#: 工作树基线（可选）。存在则精确比对；不存在（如安装版）则只跑结构不变式。
#: 这样同一份自检能在「开发树」和「安装环境」都跑，且不变式仍有判别力。
_BASELINE_PATH = os.path.join(_HERE, "_baseline.json")
try:
    import json as _json
    with open(_BASELINE_PATH, encoding="utf-8") as _f:
        BASELINE = _json.load(_f)
except Exception:
    BASELINE = {}


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS {name}")
    else:
        FAIL += 1
        FAILED.append(name + (f" | {detail}" if detail else ""))
        print(f"  FAIL {name}" + (f" | {detail}" if detail else ""))


def check_metric(name: str, key: str, actual, invariant) -> None:
    """有基线则精确比对，无基线则用不变式（并打印实际值供人工核对）。"""
    exp = BASELINE.get(key)
    if exp is not None:
        check(f"{name} = {exp}", actual == exp, f"实际 {actual}")
    else:
        check(f"{name} >= {invariant}（无基线，实际 {actual}）", actual >= invariant,
              f"实际 {actual}")


def skip(name: str, why: str = "") -> None:
    global SKIP
    SKIP += 1
    print(f"  SKIP {name}" + (f" | {why}" if why else ""))


# ---------------------------------------------------------------- A 自动机


def test_automaton() -> None:
    print("\n[A] 自动机")
    a = Automaton({"AB": "X", "ABC": "Y"})
    got = a.scan("zABz")
    check("基本匹配", [(m[2], m[3]) for m in got] == [("AB", "X")], repr(got))
    longest = a.longest("ABC")
    check("最长优先取 ABC", [m[2] for m in longest] == ["ABC"], repr(longest))

    b = Automaton({"ABA": "X", "BAB": "Y"})
    ms = b.longest("ABAB")
    check("重叠只取一个", [m[2] for m in ms] == ["ABA"], repr(ms))
    check("candidates 含重叠全集", b.candidates("ABAB") == {"ABA", "BAB"},
          repr(b.candidates("ABAB")))

    c = Automaton({"清宵 ": "清宵", "Qing Xiao ": "清宵"})
    out, ms = c.replace_longest("' Cause Qing Xiao ' s still here.")
    check("中文键+空格键混排（长键吃空格）",
          out == "' Cause 清宵' s still here.", repr(out))

    e = Automaton({})
    check("空自动机不炸", e.scan("abc") == [] and e.replace_longest("abc") == ("abc", []))


# ---------------------------------------------------------------- B 等价性


def test_equivalence() -> None:
    print("\n[B] 等价性 / 自吞")
    eng = spec_mod.load_engine()

    # 正向：真实片源抽样，索引预筛必须与全表串行一致（含兜底）
    srt = os.path.join(
        spec_mod.project_root(), "outbox",
        "【字幕】WISH GRANTED!! Hsin 3.7 Main Story Quest FULL REACTION ｜ Wuthering Waves-校准终稿.srt")
    if os.path.isfile(srt):
        rep = shadow_mod.verify_index_equivalence("bi", srt, engine=eng, limit=300)
        check("真实片源抽样：回退后 100% 等价",
              rep["verdict"].startswith("EQUIVALENT"),
              f"{rep['verdict']} differ={rep['differ']}")
    else:
        skip("真实片源抽样（本环境无 outbox 样本）", os.path.basename(srt))

    # 负向：自吞用例必须被检出（目标名含更短键，串行会二次命中）
    #   pairs 按长度降序：XX(2) 先 -> Y；Y(1) 后 -> Z  => 全表得 Z
    #   预筛只认识 XX => 得 Y，与基准不同 => verify 必须报差异
    idx = ModeIndex("probe", {"XX": "Y", "Y": "Z"})
    text = "XX"
    base = eng._replace_report(text, idx.pairs, idx.charset, {})
    cand_only, _ = idx.replay_serial(text, only=idx.candidates(text))
    check("负向：自吞行预筛结果与全表不同", cand_only != base,
          f"only={cand_only!r} base={base!r}")
    full, _ = idx.replay_serial(text)
    check("负向：全量串行可复现基准", full == base, f"full={full!r} base={base!r}")

    # 负向：空候选集必然与基准不同（防止 verify 写成恒等返回）
    empty, _ = idx.replay_serial("XX", only=set())
    check("负向：空候选集 != 基准", empty != base, repr(empty))


# ---------------------------------------------------------------- C 对象库


def test_registry() -> None:
    print("\n[C] 对象库")
    eng = spec_mod.load_engine()
    reg = spec_mod.build_registry(eng)
    kv = eng._kb_view()
    check("对象数与 _kb_view 一致", len(reg) == len(kv),
          f"reg={len(reg)} kb_view={len(kv)}")
    check("对象数 > 1000", len(reg) > 1000, str(len(reg)))
    s = spec_mod.summary(reg)
    check_metric("重复登记 canonical 个数", "dup_canonical", s["dup_canonical"], 10)
    check_metric("多余条目", "dup_extra_entries", s["dup_extra_entries"], 1)
    check("多余条目 >= 重复对象数", s["dup_extra_entries"] >= s["dup_canonical"],
          f"{s['dup_extra_entries']} vs {s['dup_canonical']}")
    check("空壳对象 > 100", s["hollow"] > 100, str(s["hollow"]))
    check("EN 覆盖 > 250", s["has_en"] > 250, str(s["has_en"]))

    # modes 修复验证：_kb_view 里空 modes 的对象，本包必须补全
    empty_in_kb = [c for c, e in kv.items() if not e["modes"]]
    still_empty = [c for c in empty_in_kb if not reg[c].modes]
    check("modes 补全（kb_view 空 -> 本包有值）",
          len(empty_in_kb) > 0 and len(still_empty) == 0,
          f"kb_view 空 {len(empty_in_kb)} / 仍空 {len(still_empty)}")

    # 重复登记对象的 note 必须聚合，不能 later-wins 覆盖
    multi = [e for e in reg.values() if e.entity_entries > 1]
    merged = [e for e in multi if len(e.notes) >= 2]
    check("重复登记对象保留多段 note", len(merged) >= len(multi) // 2,
          f"multi={len(multi)} merged={len(merged)}")


# ---------------------------------------------------------------- D 体检


class _FakeEngine:
    """只给 lint 用的假引擎（不改真实源码）。"""
    _MODE_TERM_TABLE = {"bi": "TERMS"}
    _MODE_CTX_TABLE = {"bi": "CTX"}
    TERMS = {}
    CTX = []


def test_lint_negative() -> None:
    print("\n[D] 体检（负向）")
    fake = _FakeEngine()
    fake.CTX = [(r"a", "甲", "A"), (r"a", "甲", "B")]
    recs = lint_mod.check_multi_target(fake)
    check("负向：一词多目标被抓到", len(recs) == 1, repr(recs))

    fake.CTX = [(r"a", "健", "目标"), (r"a", "健康", "目标")]
    recs = lint_mod.check_longkey_order(fake)
    check("负向：短键抢跑被抓到", len(recs) == 1, repr(recs))

    fake.CTX = [(r"a", "健康", "目标"), (r"a", "健", "目标")]
    recs = lint_mod.check_longkey_order(fake)
    check("正向：长键在前不报", len(recs) == 0, repr(recs))

    # 真实库正向计数（工作树有基线时精确比对；安装版走不变式）
    eng = spec_mod.load_engine()
    reg = spec_mod.build_registry(eng)
    res = lint_mod.run_lint(reg, eng, cascade=False)
    check_metric("真实库 longkey_order", "longkey_order",
                 res["by_code"].get("longkey_order", 0), 10)
    check_metric("真实库 dup_canonical", "dup_canonical",
                 res["by_code"].get("dup_canonical", 0), 10)
    check_metric("真实库 multi_target", "multi_target",
                 res["by_code"].get("multi_target", 0), 5)


# ---------------------------------------------------------------- E 优化补丁


def test_opt() -> None:
    import tempfile
    from calib_entity.opt import adopt as adopt_mod
    from calib_entity.opt import kb_inject as inject_mod
    from calib_entity.opt import kb_scope as scope_mod
    from calib_entity.opt import source_guard as guard_mod

    print("\n[E] 优化补丁")
    # --- 片源识别 ---
    r = guard_mod.infer_mode(title="Our Proxy | Arknights: Endfield Operator Story: Si")
    check("标题含 Endfield -> endobi/high",
          r["mode"] == "endobi" and r["confidence"] == "high", str(r["mode"]))
    r = guard_mod.infer_mode(title="Arknights 5th Anniversary Special")
    check("标题只含 Arknights -> ak", r["mode"] == "ak", str(r["mode"]))
    r = guard_mod.infer_mode(title="Suoming Combat Showcase | Wuthering Waves")
    check("标题含 Wuthering -> bi", r["mode"] == "bi", str(r["mode"]))
    r = guard_mod.infer_mode(title="", lines=["hello", "world"])
    check("无信号 -> low + 默认 bi", r["confidence"] == "low" and r["mode"] == "bi", str(r))

    # --- 作品解析 ---
    check("work_of 角色/明日方舟", scope_mod.work_of("角色/明日方舟") == "明日方舟")
    check("work_of 曲目/终末地·铁痕电台", scope_mod.work_of("曲目/终末地·铁痕电台") == "终末地")
    check("work_of 空 -> 空串", scope_mod.work_of("") == "")

    # --- 作品隔离（负向：构造跨作品实体，必须被拦） ---
    fake_reg = {
        "甲": spec_mod.EntitySpec(id="甲", canonical="甲", kind="role",
                                category="角色/鸣潮", modes=("bi",),
                                en="Jia", variants=("假甲",)),
        "乙": spec_mod.EntitySpec(id="乙", canonical="乙", kind="role",
                                category="角色/终末地", modes=("bi",),
                                en="Yi", variants=("假乙",)),
        "丙": spec_mod.EntitySpec(id="丙", canonical="丙", kind="term",
                                category="术语/鸣潮", modes=("bi",),
                                en="Bing", variants=("假丙",)),
    }
    kept, dropped = scope_mod.filter_registry(fake_reg, "终末地")
    check("负向：鸣潮角色被隔离", "甲" not in kept and any(c == "甲" for c, _w, _y in dropped),
          str(list(kept)))
    check("正向：终末地角色保留", "乙" in kept)
    check("正向：术语不隔离（同 IP 通名）", "丙" in kept)

    # --- 注入安全化（负向：外文名不该出现在安全口径里） ---
    rep = inject_mod.compare(fake_reg, "bi")
    check("负向：旧口径规则数 > 安全口径", rep["rules_old"] > rep["rules_new"], str(rep))
    safe, _ex, _nm = inject_mod.build_rules_safe(fake_reg, "bi", include_names=False)
    check("负向：安全口径不含官方外文名",
          all(w not in ("Jia", "Yi", "Bing") for w, _c in safe), str(safe))
    check("正向：安全口径仍含中文错形",
          {w for w, _c in safe} == {"假甲", "假乙", "假丙"}, str(safe))

    # --- 采纳报告（正 + 负） ---
    md = (
        "# t\n\n## 四、官方中文核对\n\n"
        "| 字幕里的写法 | 建议官方中文 | 把握 | 说明 |\n"
        "| --- | --- | --- | --- |\n"
        "| 操作员 | 干员 | 高 | x |\n"
        "| 甲词 | 乙词 | 低 | x |\n"
        "| 丙词 | 待确认 | 高 | x |\n\n"
        "## 五、脚本沉淀建议\n"
    )
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "r.md")
        open(p, "w", encoding="utf-8").write(md)
        items = adopt_mod.parse_report(p)
        keep, drop = adopt_mod.select(items)
        check("解析报告 3 条", len(items) == 3, str(len(items)))
        check("采纳只留「高」且目标明确", [k["wrong"] for k in keep] == ["操作员"], str(keep))
        check("负向：低把握被丢", any(d["wrong"] == "甲词" for d in drop))
        check("负向：待确认目标被丢", any(d["wrong"] == "丙词" for d in drop))

        srt = os.path.join(td, "t.srt")
        open(srt, "wb").write(
            "1\r\n00:00:01,000 --> 00:00:02,000\r\n操作员文件。\r\noperator file.\r\n".encode("utf-8"))
        res = adopt_mod.apply_srt(srt, [("操作员文件", "干员档案")], out_path=srt)
        got = open(srt, "rb").read()
        check("应用：中文行被替换", "干员档案".encode() in got)
        check("应用：CRLF 保持", got.count(b"\r\n") == 4, str(got.count(b"\r\n")))
        check("应用：英文行未动", b"operator file." in got)


# ---------------------------------------------------------------- F 汇总


def main() -> int:
    print("=" * 60)
    print("calib_entity 自检（正向 + 负向）")
    print("=" * 60)
    test_automaton()
    test_equivalence()
    test_registry()
    test_lint_negative()
    test_opt()
    print("\n" + "=" * 60)
    print(f"PASS {PASS} / SKIP {SKIP} / FAIL {FAIL}")
    if BASELINE:
        print(f"基线：{os.path.basename(_BASELINE_PATH)}（精确比对）")
    else:
        print("基线：未登记（仅结构不变式，数字供人工核对）")
    if FAILED:
        for f in FAILED:
            print("  ✗ " + f)
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
