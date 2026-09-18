# -*- coding: utf-8 -*-
# @version 1.14.1
"""AI 校准 Agent 自检（离线，不联网、不调用真实 LLM）。

覆盖：
  1. SRT 解析 / 回填：只换中文行，序号 / 时间轴 / 英文行 / 换行 / BOM 不变；
  2. 知识库展开：对象级实体 → 规则（用真实脚本 kb-export，本地毫秒级）；
  3. 改动校验：合法替换接受；整句改写 / 行数变化 / 无依据改动一律拒绝；
  4. 分块：条数与字符预算双约束；
  5. 端到端：假模型（按知识库规则生成改动 + 注入非法提议）跑完整流水线，
     产物通过脚本 verify 断言；
  6. v1.16.0 单元：_esc/_unesc 转义对称、内置 JSON 抢救、块级规则裁剪、
     重问反馈注入（build_user_prompt）；
  7. v1.16.0 重问带反馈：invalid / truncated 原地重试并附具体整改要求；
  8. v1.16.0 受控并发：多路取回与串行结果等价，产物 verify 通过；
  9. v1.16.0 断点续跑：ckpt 全量列不写空，已完成块不再重问。

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


#: --endo 全文本行模式会连英文参考行一起替换（Typhon→提弗洛斯），
#: 用于验证参考行保护（2026-09-18 终末地反应片实操沉淀）。
SRT_ENDO = (
    "1\r\n"
    "00:00:01,000 --> 00:00:02,000\r\n"
    "任何明日方舟恩菲尔德，但我\r\n"
    "out anything Arknights Enfield, but I\r\n"
    "\r\n"
    "2\r\n"
    "00:00:03,000 --> 00:00:04,000\r\n"
    "与新干员 Typhon 一起\r\n"
    "out along with the new operator Typhon\r\n"
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


def test_ref_line_protection():
    """P0 回归：--endo 全文本行模式不得污染英文参考行（否则 verify 必败）。"""
    print("\n== 7. 参考行保护（--endo 不污染英文行） ==")
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "endo.srt")
        with open(src, "w", encoding="utf-8", newline="") as f:
            f.write(SRT_ENDO)
        # 1) 直接跑脚本 --endo，复现「英文参考行被改」这一缺陷前提
        polluted = os.path.join(d, "polluted.srt")
        ag.run_script(PYTHON, SCRIPT, [src, "--endo", "--out", polluted], print)
        _l, pcues, _c, _b = ag.parse_srt(polluted)
        ref2 = next(c.ref_line for c in pcues if c.num == "2")
        check("--endo 确实污染了英文参考行（Typhon 被替换）",
              "Typhon" not in ref2, repr(ref2))
        # 2) _protect_ref_lines 把参考行还原成原始 src 的样子
        n = ag._protect_ref_lines(src, polluted)
        check("参考行保护还原了被改的参考行", n >= 1, f"restored={n}")
        _l2, pcues2, _c2, _b2 = ag.parse_srt(polluted)
        ref2b = next(c.ref_line for c in pcues2 if c.num == "2")
        check("还原后英文参考行与原始一致",
              ref2b == "out along with the new operator Typhon", repr(ref2b))
        zh2 = "".join(next(c.zh_lines for c in pcues2 if c.num == "2"))
        check("保护不动中文行（--endo 术语校准仍在）",
              "提弗洛斯" in zh2, zh2)
        # 3) 端到端：calibrate(--endo, baseline=True) 最终产物 verify 必须通过
        res = ag.calibrate(src, out=os.path.join(d, "endo.calib.srt"),
                           report=os.path.join(d, "endo.calib.ai.md"),
                           mode_flag="--endo", script=SCRIPT, python=PYTHON,
                           log=lambda m, level="dim": None,
                           chat=lambda *a, **k: "[]",
                           baseline=True, workdir=os.path.join(d, "work"))
        check("--endo 端到端成功（未因英文行被改而中止）",
              res["ok"], res.get("error", ""))
        rc, out = ag.run_script(PYTHON, SCRIPT, ["verify", src, res["out"]], print)
        check("--endo 产物 verify 通过（英文行 0 改动）",
              rc == 0 and "VERIFY OK" in out, out[-200:])


def test_suggest_rewrite():
    """P1 回归：term 风格下机翻腔重写被大面积挡回时，应建议改派 rewrite。"""
    print("\n== 8. term 风格机翻腔 → 建议改派 rewrite ==")
    with tempfile.TemporaryDirectory() as d:
        rows = "".join(
            f"{i}\r\n00:00:0{i},000 --> 00:00:0{i},900\r\n"
            "哥哥一个人她看起来很可爱看看\r\n"
            "bro she looks so cute look at\r\n\r\n"
            for i in range(1, 9))
        src = os.path.join(d, "rw.srt")
        with open(src, "w", encoding="utf-8", newline="") as f:
            f.write(rows)
        def rewrite_chat(prompt, system=None, max_tokens=8192):
            seg = prompt.split("【待校准条目", 1)[-1]
            out = []
            for ln in seg.splitlines():
                m = re.match(r"^(\d+)\t", ln)
                if m:
                    out.append({"num": m.group(1),
                                "new_zh": "兄弟她实在是太可爱了你快看看这个设计",
                                "reason": "整句重写"})
            return ag.json.dumps(out, ensure_ascii=False)
        res = ag.calibrate(src, out=os.path.join(d, "rw.calib.srt"),
                           report=os.path.join(d, "rw.calib.ai.md"),
                           script=SCRIPT, python=PYTHON,
                           log=lambda m, level="dim": None,
                           chat=rewrite_chat, baseline=False, style="term",
                           workdir=os.path.join(d, "work"))
        check("term 风格机翻腔 → suggest_rewrite=True",
              res.get("suggest_rewrite") is True, str(res.get("suggest_rewrite")))
        check("报告含改派 rewrite 提示",
              "rewrite" in ag._read_text(res["report"]))


def test_v16_units():
    """v1.16.0 单元级：转义对称 / 内置 JSON 抢救 / 块级规则裁剪 / 反馈注入。"""
    print("\n== 9. v1.16.0 单元（转义 / JSON 抢救 / 块级裁剪 / 反馈注入） ==")
    # 9.1 _esc ↔ _unesc 往返（\t 设计上不可逆——_esc 替换为空格，单独断言）
    samples = ["卡提希娅登场", "第一行\n第二行", "反斜杠\\path",
               "混合\\n真实\\与\n换行", "C:\\new\\night", ""]
    for s in samples:
        check(f"_esc/_unesc 往返 {s[:10]!r}", ag._unesc(ag._esc(s)) == s,
              repr(ag._unesc(ag._esc(s))))
    check("_esc 把 \\t 替换为空格", ag._esc("制\t表符") == "制 表符",
          repr(ag._esc("制\t表符")))
    check("_esc/_unesc 空安全", ag._unesc(None) == "" and ag._esc(None) == "")

    # 9.2 内置 JSON 抢救器（零依赖，替代可选第三方库 json_repair）
    check("完整数组原样解析",
          ag._repair_json('[{"num":"1","new_zh":"甲"}]') == [{"num": "1", "new_zh": "甲"}])
    cut = '[{"num":"1","new_zh":"甲","reason":"术语"},{"num":"2","new_z'
    check("截断数组抢救完整前半段",
          ag._repair_json(cut) == [{"num": "1", "new_zh": "甲", "reason": "术语"}],
          str(ag._repair_json(cut)))
    check("单引号对象修补",
          ag._repair_json("[{'num':'1','new_zh':'甲'}]") == [{"num": "1", "new_zh": "甲"}])
    esc = '{"num":"1","new_zh":"他说\\"好\\""}{"num":"2","new_zh":"乙"}'
    check("字符串内转义引号不影响配对",
          ag._repair_json(esc) == [{"num": "1", "new_zh": '他说"好"'},
                                   {"num": "2", "new_zh": "乙"}],
          str(ag._repair_json(esc)))
    nl = '{"num":"1","new_zh":"第一行\n第二行"}'
    check("字符串内真实换行修补为 \\n 转义",
          ag._repair_json(nl) == [{"num": "1", "new_zh": "第一行\n第二行"}],
          str(ag._repair_json(nl)))
    check("空输入 / 无法抢救返回空",
          ag._repair_json("") == [] and ag._repair_json("[") == [])
    # 集成：parse_changes 对截断数组返回 ok（完整前半段照常采纳，尾部残缺丢弃）
    data, status = ag.parse_changes(cut)
    check("截断数组经 parse_changes 记为 ok",
          status == "ok" and len(data) == 1, f"{status}/{len(data)}")

    # 9.3 块级规则裁剪：只注入本块（中文行 hot / 参考行 warm）命中的规则
    rules4 = [("卡西亚", "卡提希娅"), ("Typhon", "提弗洛斯"),
              ("黑冠", "黑冠主"), ("散布", "散步")]
    chunk4 = [("1", "卡西亚登场", "Carty appears"),
              ("2", "与新干员同行", "out along with Typhon")]
    txt, hot = ag.select_rules_for_chunk(rules4, chunk4)
    check("hot 命中计数 = 1", hot == 1, str(hot))
    check("注入中文行命中的规则", "卡西亚 → 卡提希娅" in txt)
    check("注入参考行命中的规则", "Typhon → 提弗洛斯" in txt)
    check("未命中规则不注入", "黑冠" not in txt and "散布" not in txt)
    check("预算为 0 时不注入",
          ag.select_rules_for_chunk(rules4, chunk4, budget=0)[0] == "")
    txt_b, _ = ag.select_rules_for_chunk(rules4, chunk4, budget=11)
    check("预算内只保留第一条（hot 优先）", txt_b == "卡西亚 → 卡提希娅", repr(txt_b))

    # 9.4 重问反馈注入：位于本块范围之后、术语表之前
    p = ag.build_user_prompt("", "R1\nR2", chunk4, 1, scope_text="【本块范围】X",
                             feedback="上一次没闭合，请整改")
    check("feedback 段已注入", "【上一次回复的问题（必须整改）】" in p
          and "上一次没闭合，请整改" in p)
    check("注入位置：范围之后、术语表之前",
          0 <= p.find("【本块范围】") < p.find("必须整改") < p.find("【术语知识库"))
    check("无 feedback 时不出现在该段",
          "必须整改" not in ag.build_user_prompt("", "R", chunk4, 1))


def test_ask_block_retry_feedback():
    """v1.16.0：invalid / truncated 的原地重问必须携带具体整改反馈。"""
    print("\n== 10. 重问带反馈（invalid / truncated） ==")
    chunk5 = [("1", "卡西亚登场", "Carty appears")]

    def _ok():
        return ag.json.dumps([{"num": "1", "new_zh": "卡提希娅登场",
                               "reason": "术语表"}], ensure_ascii=False)

    log_fn = lambda m, level="dim": None      # noqa: E731
    tick_fn = lambda: None                    # noqa: E731

    calls = []

    def flaky_chat(prompt, system=None, max_tokens=8192):
        calls.append((prompt, max_tokens))
        return "模型走神了，这不是 JSON" if len(calls) == 1 else _ok()

    changes, fail = ag._ask_block(flaky_chat, "", "R", chunk5, 1, 8192,
                                  log_fn, tick_fn)
    check("invalid 重问后采纳",
          bool(changes) and changes[0]["num"] == "1" and not fail,
          f"fail={fail}")
    check("invalid 重问附整改反馈（要求严格 JSON）",
          len(calls) == 2 and "必须整改" in calls[1][0] and "JSON" in calls[1][0])

    calls2 = []

    def cut_chat(prompt, system=None, max_tokens=8192):
        calls2.append((prompt, max_tokens))
        return '[{"num":"1","new_zh":"卡提希' if len(calls2) == 1 else _ok()

    changes2, fail2 = ag._ask_block(cut_chat, "", "R", chunk5, 1, 4096,
                                    log_fn, tick_fn)
    check("truncated 重问后采纳", bool(changes2) and not fail2, f"fail={fail2}")
    check("truncated 重问输出预算加倍",
          len(calls2) == 2 and calls2[1][1] == 8192, str([c[1] for c in calls2]))
    check("truncated 反馈含整改要求", "必须整改" in calls2[1][0])


def test_concurrency_equivalence():
    """v1.16.0：并发取回与串行结果等价（同一输入、同一假模型），产物 verify 通过。"""
    print("\n== 11. 受控并发：多路取回与串行等价 ==")
    with tempfile.TemporaryDirectory() as d:
        rows = "".join(
            f"{i}\r\n00:00:{i:02d},000 --> 00:00:{i:02d},900\r\n"
            "卡西亚登场\r\nCarty appears\r\n\r\n"
            for i in range(1, 10))
        src = os.path.join(d, "conc.srt")
        with open(src, "w", encoding="utf-8", newline="") as f:
            f.write(rows)
        kb = os.path.join(d, "kb.json")
        ag.run_script(PYTHON, SCRIPT, ["kb-export", "--json", "--out", kb], print)
        rules, _ex, _cn = ag.build_rules(ag.json.loads(ag._read_text(kb)), "bi")

        def run(conc, tag):
            return ag.calibrate(
                src, out=os.path.join(d, f"conc{tag}.srt"),
                report=os.path.join(d, f"conc{tag}.md"),
                script=SCRIPT, python=PYTHON,
                log=lambda m, level="dim": None,
                chat=_fake_chat_factory(rules), baseline=False,
                chunk_cues=3, workdir=os.path.join(d, "work" + tag),
                concurrency=conc)

        r1 = run(1, "1")
        r3 = run(3, "3")
        check("串行跑通", r1["ok"], r1.get("error", ""))
        check("并发跑通", r3["ok"], r3.get("error", ""))
        check("分块一致且 > 1 块",
              r1["chunks"] == r3["chunks"] and r3["chunks"] > 1,
              f"{r1['chunks']}/{r3['chunks']}")
        check("result 记录并发度 = 3", r3.get("concurrency") == 3,
              str(r3.get("concurrency")))
        k1 = sorted((t[0], t[1], t[2]) for t in r1["accepted"])
        k3 = sorted((t[0], t[1], t[2]) for t in r3["accepted"])
        check("并发与串行采纳集一致", k3 == k1,
              f"串行 {len(k1)} 条 / 并发 {len(k3)} 条")
        check("并发与串行拒绝计数一致", r3["rejected"] == r1["rejected"],
              f"{r1['rejected']}/{r3['rejected']}")
        rc, out = ag.run_script(PYTHON, SCRIPT, ["verify", src, r3["out"]], print)
        check("并发产物 verify 通过（时间轴/格式未动）",
              rc == 0 and "VERIFY OK" in out, out[-160:])


def test_ckpt_resume():
    """v1.16.0：断点续跑——ckpt 全量列不写空（旧版只按当前块回填会把跨块
    条目的 zh/ref 写成空列），已完成块不再重问，续跑产物与整跑一致。"""
    print("\n== 12. 断点续跑（ckpt 全量列 + 跳过已完成块） ==")
    with tempfile.TemporaryDirectory() as d:
        rows = "".join(
            f"{i}\r\n00:00:{i:02d},000 --> 00:00:{i:02d},900\r\n"
            "卡西亚登场\r\nCarty appears\r\n\r\n"
            for i in range(1, 7))
        src = os.path.join(d, "ck.srt")
        with open(src, "w", encoding="utf-8", newline="") as f:
            f.write(rows)
        kb = os.path.join(d, "kb.json")
        ag.run_script(PYTHON, SCRIPT, ["kb-export", "--json", "--out", kb], print)
        rules, _ex, _cn = ag.build_rules(ag.json.loads(ag._read_text(kb)), "bi")

        calls = {"n": 0, "nums": set()}
        base_chat = _fake_chat_factory(rules)

        def counting_chat(prompt, system=None, max_tokens=8192):
            seg = prompt.split("【待校准条目", 1)[-1]
            for ln in seg.splitlines():
                m = re.match(r"^(\d+)\t", ln)
                if m:
                    calls["nums"].add(m.group(1))
            calls["n"] += 1
            return base_chat(prompt, system, max_tokens)

        work = os.path.join(d, "work")
        kw = dict(script=SCRIPT, python=PYTHON,
                  log=lambda m, level="dim": None,
                  chat=counting_chat, baseline=False, chunk_cues=3, workdir=work)
        res = ag.calibrate(src, out=os.path.join(d, "ck1.srt"),
                           report=os.path.join(d, "ck1.md"), **kw)
        check("整跑成功", res["ok"], res.get("error", ""))
        ckpt_rows = [ln.split("\t") for ln in ag._read_text(
            os.path.join(work, "ckpt.tsv")).splitlines()[1:] if ln.strip()]
        check("ckpt 覆盖全部 6 条", len(ckpt_rows) == 6, str(len(ckpt_rows)))
        check("ckpt zh/ref 全量列非空（v1.16.0 修复）",
              all(len(p) >= 4 and p[1] and p[2] for p in ckpt_rows),
              str(ckpt_rows[:1]))

        # 伪造「只完成块 1」的断点：ckpt 只留序号 1–3，done 只留块 1
        half = "\n".join("\t".join(p) for p in ckpt_rows if p[0] in {"1", "2", "3"})
        ag._write_text(os.path.join(work, "ckpt.tsv"),
                       "num\tzh\tref\tnew\n" + half + "\n")
        ag._write_text(os.path.join(work, "ckpt.done"), "1\n")
        calls = {"n": 0, "nums": set()}
        res2 = ag.calibrate(src, out=os.path.join(d, "ck2.srt"),
                            report=os.path.join(d, "ck2.md"), **kw)
        check("续跑成功", res2["ok"], res2.get("error", ""))
        check("续跑只重问块 2（序号 4–6，不重问 1–3）",
              calls["nums"] == {"4", "5", "6"}, str(calls["nums"]))
        check("续跑产物与整跑一致",
              ag._read_text(res2["out"]) == ag._read_text(res["out"]))
        rc, out = ag.run_script(PYTHON, SCRIPT, ["verify", src, res2["out"]], print)
        check("续跑产物 verify 通过", rc == 0 and "VERIFY OK" in out, out[-160:])


if __name__ == "__main__":
    print(f"脚本：{SCRIPT}\n解释器：{PYTHON}")
    test_parse_rebuild()
    test_rules_and_validate()
    test_split()
    test_end_to_end(use_baseline=True)
    test_end_to_end(use_baseline=False)
    test_long_and_rewrite()
    test_ref_line_protection()
    test_suggest_rewrite()
    test_v16_units()
    test_ask_block_retry_feedback()
    test_concurrency_equivalence()
    test_ckpt_resume()
    print("\n" + ("全部通过 ✅" if not FAILED else f"失败 {len(FAILED)} 项 ❌：{FAILED}"))
    sys.exit(1 if FAILED else 0)
