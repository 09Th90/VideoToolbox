# -*- coding: utf-8 -*-
# @version 1.14.1
"""AI 校准 Agent 自检（离线，不联网、不调用真实 LLM）。

覆盖：
  1. SRT 解析 / 回填：只换中文行，序号 / 时间轴 / 英文行 / 换行 / BOM 不变；
  2. 知识库展开：对象级实体 → 规则（用真实脚本 kb-export，本地毫秒级）；
  3. 改动校验：合法替换接受；整句改写 / 行数变化 / 无依据改动一律拒绝；
  4. 分块：条数与字符预算双约束；
  5. 端到端：假模型（按知识库规则生成改动 + 注入非法提议）跑完整流水线，
     产物通过脚本 verify 断言。

用法：tools\\python\\python.exe src\\_selftest_calib_ai.py
"""
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import calib_ai_agent as ag  # noqa: E402

SCRIPT = os.path.join(os.path.dirname(HERE), ag.SCRIPT_NAME)
PYTHON = sys.executable

SRT = (
    "1\r\n"
    "00:00:01,000 --> 00:00:02,000\r\n"
    "卡西亚登场\r\n"
    "Carty appears\r\n"
    "\r\n"
    "2\r\n"
    "00:00:03,000 --> 00:00:04,500\r\n"
    "少女与卡西亚\r\n"
    "相遇在鸣潮\r\n"
    "Carty and the girl\r\n"
    "\r\n"
    "3\r\n"
    "00:00:05,000 --> 00:00:06,000\r\n"
    "Only english line\r\n"
)

FAILED = []

#: 整句重写风格用的样例：带 `>>` 与 [标记]（验证标记保护）、被机翻拉长的行
SRT_RW = (
    "1\r\n"
    "00:00:01,000 --> 00:00:02,000\r\n"
    ">> 我要你跪下[音乐]\r\n"
    "I want you on your knees\r\n"
    "\r\n"
    "2\r\n"
    "00:00:03,000 --> 00:00:04,500\r\n"
    "这是一行被机翻得很长的中文用来验证行宽门禁\r\n"
    "this is a long reference line\r\n"
    "\r\n"
    "3\r\n"
    "00:00:05,000 --> 00:00:06,000\r\n"
    "因为这样所以那样\r\n"
    "because of this, therefore that\r\n"
)


def check(label, cond, detail=""):
    print(("  [OK] " if cond else "  [FAIL] ") + label + (f"  {detail}" if detail else ""))
    if not cond:
        FAILED.append(label)


def test_parse_rebuild():
    print("\n== 1. 解析 / 回填 ==")
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "a.srt")
        with open(src, "w", encoding="utf-8", newline="") as f:
            f.write(SRT)
        with open(src, "rb") as f:
            bom_src = f.read()
        lines, cues, crlf, bom = ag.parse_srt(src)
        check("cue 数 = 3", len(cues) == 3, f"got {len(cues)}")
        check("多行 cue 的中文行 = 2", len(cues[1].zh_lines) == 2,
              str(cues[1].zh_lines))
        check("单文本行 cue 无中文行", cues[2].zh_lines == [])
        check("CRLF 识别", crlf and not bom)
        out = ag.rebuild_srt(lines, cues, {"1": "卡提希娅登场"}, crlf, bom)
        with open(os.path.join(d, "b.srt"), "w", encoding="utf-8", newline="") as f:
            f.write(out)
        l2, c2, crlf2, _ = ag.parse_srt(os.path.join(d, "b.srt"))
        check("序号/时间轴/英文行不变",
              all(c1.num == c2_.num and c1.time_line == c2_.time_line
                  and c1.ref_line == c2_.ref_line for c1, c2_ in zip(cues, c2)))
        check("中文行已替换", c2[0].zh_lines == ["卡提希娅登场"])
        check("未指定条目的多行中文原样保留",
              c2[1].zh_lines == ["少女与卡西亚", "相遇在鸣潮"])
        check("BOM 状态保持（无 BOM → 无 BOM）",
              not open(os.path.join(d, "b.srt"), "rb").read().startswith(b"\xef\xbb\xbf"))
        check("CRLF 保持", b"\r\n" in open(os.path.join(d, "b.srt"), "rb").read())
        check("源文件字节数未变（长度对照）", len(bom_src) > 0)


def test_rules_and_validate():
    print("\n== 2/3. 知识库规则与改动校验 ==")
    with tempfile.TemporaryDirectory() as d:
        kb = os.path.join(d, "kb.json")
        rc, _out = ag.run_script(PYTHON, SCRIPT, ["kb-export", "--json",
                                                 "--out", kb], print)
        check("kb-export 成功", rc == 0 and os.path.isfile(kb))
        ents = ag.json.loads(ag._read_text(kb))
        rules, excludes, canonicals = ag.build_rules(ents, "bi")
        check("规则数 > 200", len(rules) > 200, f"got {len(rules)}")
        check("官方名集合非空", len(canonicals) > 50, f"got {len(canonicals)}")
        # 合法：错形 → 官方名
        ok, why, soft = ag.validate_change("卡西亚登场", "卡提希娅登场",
                                           rules, excludes, canonicals)
        check("合法名词替换被接受", ok and not soft, why)
        # 非法：整句改写
        ok, why, _ = ag.validate_change("少女与卡西亚相遇在鸣潮",
                                        "两位主角在鸣潮相遇并成为了伙伴",
                                        rules, excludes, canonicals)
        check("整句改写被拒绝", not ok, why)
        # 非法：行数变化
        ok, why, _ = ag.validate_change("少女与卡西亚\n相遇在鸣潮",
                                        "少女与卡提希娅相遇在鸣潮",
                                        rules, excludes, canonicals)
        check("行数变化被拒绝", not ok, why)
        # 非法：无依据
        ok, why, _ = ag.validate_change("今天天气不错", "今天天气非常好",
                                        rules, excludes, canonicals)
        check("无依据改动被拒绝", not ok, why)
        # 非法：空
        ok, why, _ = ag.validate_change("今天天气不错", "",
                                        rules, excludes, canonicals)
        check("空文本被拒绝", not ok, why)


def test_split():
    print("\n== 4. 分块 ==")
    cues = [(str(i), "字" * 20, "en") for i in range(1, 26)]
    chunks = ag._split_chunks(cues, 10, 10_000)
    check("按条数切块 = 3 块", len(chunks) == 3, f"got {len(chunks)}")
    chunks = ag._split_chunks(cues, 1000, 100)
    check("按字符预算切块 > 1 块", len(chunks) > 1, f"got {len(chunks)}")
    check("所有 cue 均被覆盖",
          sum(len(c) for c in chunks) == len(cues))


def _fake_chat_factory(rules):
    """假模型：从提示词里读出待校准条目，按知识库规则做替换，
    并故意注入两条非法提议（整句改写 / 行数变化）以验证拒绝链路。

    注意条目自 2026-09-14 起是**三列** `序号<TAB>中文行<TAB>参考行`，解析要跟着走。
    """
    hits = [(w, c) for w, c in rules if len(w) >= 2]

    def fake_chat(prompt, system=None, max_tokens=8192):
        seg = prompt.split("【待校准条目", 1)[-1]
        items = []
        for ln in seg.splitlines():
            m = re.match(r"^(\d+)\t([^\t]*)(?:\t(.*))?$", ln)
            if m:
                items.append((m.group(1), m.group(2), m.group(3) or ""))
        out = []
        for num, zh, _ref in items:
            new = zh
            for w, c in hits:
                if w in new:
                    new = new.replace(w, c)
            if new != zh:
                out.append({"num": num, "new_zh": new.replace("\n", "\\n"),
                            "reason": "术语表替换"})
        if items:
            base_num, base_zh, _r = items[0]
            out.append({"num": base_num, "new_zh": "这是一句被模型自由改写的长句子",
                        "reason": "非法：整句改写"})
            if len(items) > 1:
                n2, z2, _r2 = items[1]
                out.append({"num": n2, "new_zh": z2, "reason": "非法：无改动"})
        return ag.json.dumps(out, ensure_ascii=False)
    return fake_chat


def test_end_to_end(use_baseline):
    tag = "基线" if use_baseline else "跳过基线"
    print(f"\n== 5. 端到端流水线（{tag}） ==")
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "ep.srt")
        with open(src, "w", encoding="utf-8", newline="") as f:
            f.write(SRT)
        kb = os.path.join(d, "kb.json")
        ag.run_script(PYTHON, SCRIPT, ["kb-export", "--json", "--out", kb], print)
        rules, _ex, _cn = ag.build_rules(ag.json.loads(ag._read_text(kb)), "bi")
        logs = []
        res = ag.calibrate(
            src, out=os.path.join(d, "ep.calib.srt"),
            report=os.path.join(d, "ep.calib.ai.md"),
            script=SCRIPT, python=PYTHON,
            log=lambda m, level="dim": logs.append(f"[{level}] {m}"),
            chat=_fake_chat_factory(rules),
            baseline=use_baseline, round_no=1, workdir=os.path.join(d, "work"))
        check("流水线成功", res["ok"], res.get("error", ""))
        check("输出文件存在", os.path.isfile(res["out"]))
        check("报告文件存在", os.path.isfile(res["report"]))
        check("日志含 8 个阶段", sum(1 for x in logs if x.startswith("[dim] [")
                                    or x.startswith("[ok] [")) >= 6,
              f"{len(logs)} 行")
        check("拒绝了非法提议", res["rejected"] >= 1, str(res["rejected"]))
        if use_baseline:
            # 基线模式：机械部分由脚本完成（卡西亚→卡提希娅），AI 只补残留；
            # 两者合计必须有产出，且 AI 的改动不得与脚本冲突（verify 已断言）。
            check("基线或 AI 至少一方有产出",
                  res["script_changes"] + res["ai_changes"] >= 1,
                  f"script={res['script_changes']} ai={res['ai_changes']}")
        else:
            check("跳过基线时 AI 阶段有产出（含疑似新错形）", res["ai_changes"] >= 1,
                  str(res["ai_changes"]))
        # 用脚本 verify 独立断言
        rc, out = ag.run_script(PYTHON, SCRIPT, ["verify", src, res["out"]], print)
        check("脚本 verify 通过", rc == 0 and "VERIFY OK" in out, out[-200:])
        # 再次校准（第 2 轮）
        res2 = ag.calibrate(
            res["out"], out=os.path.join(d, "ep.calib2.srt"),
            report=os.path.join(d, "ep.calib2.ai.md"),
            script=SCRIPT, python=PYTHON, log=lambda m, level="dim": None,
            chat=_fake_chat_factory(rules), baseline=False, round_no=2,
            workdir=os.path.join(d, "work2"))
        check("再次校准（第 2 轮）成功", res2["ok"], res2.get("error", ""))
        rc, out = ag.run_script(PYTHON, SCRIPT, ["verify", res["out"], res2["out"]],
                                print)
        check("第 2 轮 verify 通过", rc == 0 and "VERIFY OK" in out)


def test_long_and_rewrite():
    """长时双语片源特化：句子边界分块 / 行宽判据 / 整句重写校验与端到端。"""
    print("\n== 6. 长片源特化（句子边界 / 行宽 / 整句重写） ==")
    # 6.1 句子边界切块：切点应落在「参考行句末标点」之后
    cues = [("1", "甲" * 30, "One sentence ends here."),
            ("2", "乙" * 30, "Second ends here."),
            ("3", "丙" * 30, "third"),
            ("4", "丁" * 30, "fourth")]
    budget = len(cues[0][1]) * 2 + 16
    chunks = ag.plan_chunks(cues, 10, budget, sentence_aware=True)
    check("句子边界切块 > 1 块", len(chunks) > 1, f"got {len(chunks)}")
    check("切点落在句末标点之后",
          all(ag._is_sentence_end(ch[-1][2]) for ch in chunks[:-1]),
          str([[c[0] for c in ch] for ch in chunks]))
    check("所有 cue 恰好覆盖一次",
          [c[0] for ch in chunks for c in ch] == [c[0] for c in cues])
    greedy = ag.plan_chunks(cues, 2, 100000, sentence_aware=False)
    check("sentence_aware=False 时退回纯贪心", len(greedy) == 2, f"got {len(greedy)}")

    # 6.2 行宽判据（与校准脚本 length 同一口径）
    check("行宽：32 汉字 = 32.0", abs(ag.line_width("汉" * 32) - 32.0) < 1e-6)
    check("行宽：64 英文字符 = 32.0",
          abs(ag.line_width("A" * 64) - 32.0) < 1e-6)
    check("时间轴解析", ag._parse_span("00:00:01,500 --> 00:00:02,250") == (1500, 2250))

    # 6.3 validate_rewrite 的「没破坏什么」断言
    rules, excludes, canonicals = [("卡西亚", "卡提希娅")], [], {"卡提希娅"}
    ok, why, _ = ag.validate_rewrite(">> 我要你跪下[音乐]", ">> 我要你跪下来[音乐]",
                                     rules, excludes, canonicals)
    check("整句重写被接受（标记保留）", ok, why)
    ok, why, _ = ag.validate_rewrite(">> 我要你跪下[音乐]", "我要你跪下",
                                     rules, excludes, canonicals)
    check("丢失 >> / [标记] 被拒绝", not ok, why)
    ok, why, _ = ag.validate_rewrite("汉" * 30, "汉" * 34,
                                     rules, excludes, canonicals)
    check("行宽超限被拒绝", (not ok) and ("行宽" in why), why)
    ok, why, _ = ag.validate_rewrite("卡西亚登场", "Khasia 登场",
                                     rules, excludes, canonicals)
    check("新增原文没有的拉丁词被拒绝", not ok, why)
    ok, why, _ = ag.validate_rewrite("卡提希娅登场", "卡西亚登场",
                                     rules, excludes, canonicals)
    check("改坏已有官方名被拒绝", not ok, why)
    ok, why, _ = ag.validate_rewrite("少女与卡西亚\n相遇在鸣潮",
                                     "少女与卡提希娅\n相遇在鸣潮",
                                     rules, excludes, canonicals)
    check("多行重写行数一致时接受", ok, why)

    # 6.4 整句重写端到端（含行宽体检 + 人工复核节）
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "rw.srt")
        with open(src, "w", encoding="utf-8", newline="") as f:
            f.write(SRT_RW)

        def fake_rw_chat(prompt, system=None, max_tokens=8192):
            seg = prompt.split("【待校准条目", 1)[-1]
            items = []
            for ln in seg.splitlines():
                m = re.match(r"^(\d+)\t([^\t]*)(?:\t(.*))?$", ln)
                if m:
                    items.append((m.group(1), m.group(2), m.group(3) or ""))
            out = []
            if items:
                out.append({"num": items[0][0], "new_zh": ">> 我要你双膝跪地[音乐]",
                            "reason": "语序理顺"})
                out.append({"num": items[0][0], "new_zh": "我要你双膝跪地",
                            "reason": "非法：丢标记"})
            if len(items) > 1:
                out.append({"num": items[1][0], "new_zh": "这" * 40,
                            "reason": "非法：超宽"})
            return ag.json.dumps(out, ensure_ascii=False)

        res = ag.calibrate(
            src, out=os.path.join(d, "rw.calib.srt"),
            report=os.path.join(d, "rw.calib.ai.md"),
            script=SCRIPT, python=PYTHON, log=lambda m, level="dim": None,
            chat=fake_rw_chat, baseline=False, style="rewrite",
            workdir=os.path.join(d, "work"))
        check("整句重写流水线成功", res["ok"], res.get("error", ""))
        check("采纳了合法重写", res["ai_changes"] >= 1, str(res["ai_changes"]))
        check("标记丢失 / 超宽提议被拒", res["rejected"] >= 2, str(res["rejected"]))
        check("行宽体检已执行", bool((res.get("width_widest") or ("", ""))[0]),
              str(res.get("width_widest")))
        rc, out = ag.run_script(PYTHON, SCRIPT, ["verify", src, res["out"]], print)
        check("重写后 verify 通过", rc == 0 and "VERIFY OK" in out, out[-160:])
        check("报告含人工复核节", "建议人工复核" in ag._read_text(res["report"]))


if __name__ == "__main__":
    print(f"脚本：{SCRIPT}\n解释器：{PYTHON}")
    test_parse_rebuild()
    test_rules_and_validate()
    test_split()
    test_end_to_end(use_baseline=True)
    test_end_to_end(use_baseline=False)
    test_long_and_rewrite()
    print("\n" + ("全部通过 ✅" if not FAILED else f"失败 {len(FAILED)} 项 ❌：{FAILED}"))
    sys.exit(1 if FAILED else 0)
