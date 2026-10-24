# -*- coding: utf-8 -*-
# @version 2.6.0
"""学习库与 learn/learned-*

源：subtitle_calib_merged.py L11185-L11554 @ 97d7d463（2026-10-24 冻结快照）
"""
import io
import os
import re
import shutil
import sys
import unicodedata
from .data.modes import _MODE_TERM_TABLE
from .state import TABLES
from .text import _decode_any



# =============================================================
# 7. 学习系统（规则引擎 + 从人工修正中学习，2026-09-11）
#
#    闭环：每次人工校准产出的 [原始srt + 校准srt] 配对即训练样本。
#      learn 配对投喂 -> difflib 抽取 cue 内 错形->正形 片段 ->
#      写入持久化候选库(默认 ./subtitle_learned_kb.json，--kb 改路径)。
#    候选状态机（自我迭代核心）：
#      candidate  首次/低频出现；count<2 或有未纠正反例
#      confirmed  count>=2 且从未出现"同一错形在原文中保留未改"的反例
#                 -> 校准运行时按记录的模式自动注入术语表（无需人工）
#      降级       confirmed 候选在后续投喂中出现反例 -> 自动降回
#                 candidate，并从纠正/未纠正两类参考行的词元差异
#                 自动生成"上下文佐证正则"建议（ctx_regex 字段）
#      rejected   learned-reject 人工否决，永不应用（保留证据备查）
#    投喂原则：
#      · 投喂时 --mode 必须等于该校准任务实际使用的模式，候选按模式隔离；
#      · 同一错形被改成不同目标 -> 记 conflict，不自动应用，人工裁决；
#      · 整句重写/ERROR 重译不属于"名词级校准"，不学习（span>30字跳过）；
#      · 固化路径：confirmed 积累到一定量后 learned-promote --entities
#        导出 Entity 桩代码，人工审阅后粘贴进第 6 节 ENTITIES，
#        学习成果即沉淀为对象级知识。
# =============================================================

LEARNED_KB_DEFAULT = "subtitle_learned_kb.json"



def _load_learned_kb(path):
    """读取学习库；不存在则返回空库。"""
    import json
    if path and os.path.exists(path):
        try:
            with open(path, "rb") as f:
                kb = json.loads(_decode_any(f.read()))
            if isinstance(kb, dict) and "candidates" in kb:
                return kb
        except Exception as e:
            print(f"⚠ 学习库读取失败（{e}），按空库继续")
    return {"version": 1, "candidates": {}}



def _save_learned_kb(kb, path):
    import json
    with open(path, "w", encoding="utf-8") as f:
        json.dump(kb, f, ensure_ascii=False, indent=1)



def _parse_cue_pairs(path):
    """解析 SRT -> [(num, 中文行(多行\\n连接), 参考行)]。结构容错同主引擎。"""
    raw = open(path, "rb").read()
    lines = _decode_any(raw).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    cues, i, n = [], 0, len(lines)
    while i < n:
        s = lines[i].strip()
        if s.isdigit() and (i == 0 or lines[i - 1].strip() == ""):
            j = i + 1
            if j < n and "-->" in lines[j]:
                kk = j + 1
                while kk < n and lines[kk].strip() != "":
                    kk += 1
                if kk - 1 >= j + 1:
                    texts = lines[j + 1:kk]
                    cues.append((int(s), "\n".join(texts[:-1]), texts[-1]))
                i = kk
                continue
        i += 1
    return cues



def _diff_spans(old, new):
    """difflib 抽取 old->new 的最小替换片段，返回
    [(wrong, right, left_old, right_old, left_new, right_new)]（前后文采样，
    供跨出现处公共词缀扩展用）。整句重写（span>30字）不学习。"""
    import difflib
    out = []
    for tag, a1, a2, b1, b2 in difflib.SequenceMatcher(
            None, old, new, autojunk=False).get_opcodes():
        if tag != "replace":
            continue
        wrong, right = old[a1:a2].strip(), new[b1:b2].strip()
        if not wrong or not right or wrong == right:
            continue
        if len(wrong) < 2 or len(wrong) > 30 or len(right) > 30:
            continue                      # 单字噪音/整句重写 不入候选
        if wrong.isdigit():
            continue
        out.append((wrong, right, old[:a1], old[a2:], new[:b1], new[b2:]))
    return out



def _common_prefix(strs, cap=6):
    """字符串列表的最长公共前缀（cap 封顶）。"""
    if not strs:
        return ""
    p = strs[0][:cap]
    for s in strs[1:]:
        while p and not s.startswith(p):
            p = p[:-1]
    return p



def _common_suffix(strs, cap=6):
    if not strs:
        return ""
    p = strs[0][-cap:]
    for s in strs[1:]:
        while p and not s.endswith(p):
            p = p[1:]
    return p



def _learn_extended(c):
    """跨出现处的公共词缀扩展：把最小差异片段扩展为稳定词元。

    依据：同一专名的多次 ASR 误听/修正中，差异最小片段（佩莉->珀）的
    两侧上下文在 old 各出现处共享的部分（西娅…），即该词元的真实边界。
    样本>=2 才扩展（单次出现无法区分词元与句子），两侧各封顶 6 字。
    返回 (应用形态 wrong, right)；样本不足返回原始最小片段。"""
    samples = c.get("samples") or []
    if len(samples) < 2:
        return c["wrong"], c["right"]
    lo = _common_suffix([s[0] for s in samples])
    ln_ = _common_suffix([s[2] for s in samples])
    n = min(len(lo), len(ln_))
    lsuf = lo[-n:] if n else ""
    ro = _common_prefix([s[1] for s in samples])
    rn = _common_prefix([s[3] for s in samples])
    m = min(len(ro), len(rn))
    rpfx = ro[:m] if m else ""
    return lsuf + c["wrong"] + rpfx, lsuf + c["right"] + rpfx



def _ref_tokens(ref):
    """参考行词元（拉丁词；用于生成上下文佐证正则建议）。"""
    return set(re.findall(r"[A-Za-z][A-Za-z'\-]{2,}", ref))



# 常用中文词黑名单：**禁止自动 confirmed**（2026-10-04 沉淀）。
# 戒律：常用词义错位（明朝/骑士/法官/哨兵/拖车/哀叹/谐振器/枯萎…）绝不作为裸键进术语表，
# 只能走 ctx（参考行正则锚定）或 subfix（逐 cue 侧车）。learn 的自动 confirmed 会绕过这条戒律，
# 导致跨片源误伤（实测：枯萎→鸣潮 改坏 blight way；骑士→明日方舟 改坏 Knights 本义）。
# 命中此表者仅保留候选，须人工 learned-promote 审阅后才生效。
# 2026-10-12 WuWa3.3 反应片双教训：
#   ① "骑士"历史 confirmed（AK 片源 Knights 语境）跨片源误伤 WuWa 的 Exor Rider 语境 5 处，
#      已 learned-reject；本片 Exor Rider(Exo Strider/Exorder/Exorrider) 官方中文=「隧者」，
#      "艾克索/埃克索/外骨骼 骑士"整词修法见 side 表 wuwa33_fix.tsv（num<TAB>old<TAB>new）。
#      注意同步通道 _sync_apply_learned_candidate 只尊重 rejected，降级 candidate 会被回写覆盖。
#   ② "做了很多"同批 reject 并入 DENY（本义短语 I do a lot of，绝不作裸键）。
LEARN_AUTOCONFIRM_DENY = frozenset({
    "明朝", "明州", "明祖", "明朝", "明植",
    "骑士", "法官", "哨兵", "拖车", "哀叹", "谐振器", "谐振腔", "枯萎",
    "图案", "溪流", "班车", "航天飞机", "外骨骼", "流动站", "银杏", "鲁斯",
    "三和", "京城", "典范", "帕拉贡", "太恶心了", "海岸守护者", "金龙", "蒙祖",
    "做了很多",            # 2026-10-12 WuWa3.3 反应片：本义短语裸键（I do a lot of），
                           # 历史 confirmed 曾把 "我做了很多探索" 误改为 "我做得更探索"
})



def _learn_update_status(c):
    """候选状态机：count/uncorrected 驱动 确认/降级，并生成上下文建议。
    返回 True 表示本次发生了 confirmed->candidate 反例降级。"""
    if c["status"] == "rejected":
        return False
    if c.get("conflict"):
        c["status"] = "candidate"
        return False
    if c["count"] >= 2 and c["uncorrected"] == 0:
        if c["wrong"] in LEARN_AUTOCONFIRM_DENY:
            # 常用词裸键：绝不允许自动 confirmed（戒律：常用词义错位只走 ctx/subfix）。
            # 候选保留，须人工 learned-promote 才会生效（2026-10-04 3.7 反应片实测沉淀）。
            c["needs_review"] = True
            c["status"] = "candidate"
            return False
        c["status"] = "confirmed"
        c.pop("ctx_regex", None)
        return False
    demoted = c["status"] == "confirmed" and c["uncorrected"] > 0
    if demoted:
        c["demoted"] = True                   # confirmed -> 反例降级标记
    c["status"] = "candidate"
    # 上下文建议：纠正实例参考行词元中、未纠正实例里不出现的，取前 3
    corr, unc = c.get("ref_tokens", {}), c.get("unc_ref_tokens", {})
    sig = sorted(((t, n) for t, n in corr.items() if t not in unc),
                 key=lambda kv: -kv[1])[:3]
    c["ctx_regex"] = "|".join(rf"\b{re.escape(t)}\b" for t, _ in sig) if sig else ""
    return demoted



def _cmd_learn(src, calib, kb_path=LEARNED_KB_DEFAULT, mode="bi"):
    """learn：投喂 [原始srt + 人工校准srt] 配对，挖掘候选规则并更新学习库。
    v1.11.0：收尾自动导出本次新增 confirmed 条目为增量并上传（FR-2）。"""
    import datetime
    import copy
    sc, oc = _parse_cue_pairs(src), _parse_cue_pairs(calib)
    if len(sc) != len(oc):
        print(f"⚠ cue 数不一致（原 {len(sc)} / 校准 {len(oc)}），按序号交集学习")
    smap, omap = {n: (z, r) for n, z, r in sc}, {n: (z, r) for n, z, r in oc}
    kb = _load_learned_kb(kb_path)
    kb_before = copy.deepcopy(kb)
    cands = kb["candidates"]
    today = datetime.date.today().isoformat()
    new_cnt = upd_cnt = skip_same = 0

    def key(mode_, wrong):
        return f"{mode_}|{wrong}"

    # 第一遍：挖替换片段（纠正实例）
    touched = set()
    for num in sorted(smap.keys() & omap.keys()):
        oz, ref = smap[num]
        nz, _ = omap[num]
        if oz == nz:
            skip_same += 1
            continue
        if oz.strip() == "ERROR":
            continue                          # ERROR 重译属整句补译，不学习
        for wrong, right, lo, ro, ln, rn in _diff_spans(oz, nz):
            k = key(mode, wrong)
            c = cands.get(k)
            if c is None:
                c = {"wrong": wrong, "right": right, "mode": mode,
                     "count": 0, "uncorrected": 0, "status": "candidate",
                     "cues": [], "samples": [], "ref_tokens": {},
                     "unc_ref_tokens": {},
                     "first": today, "last": today, "alts": {}}
                cands[k] = c
                new_cnt += 1
            else:
                upd_cnt += 1
            if c["right"] != right:
                c["alts"][right] = c["alts"].get(right, 0) + 1
                c["conflict"] = True          # 同一错形被改成不同目标：人工裁决
            else:
                c["count"] += 1
                if len(c["samples"]) < 10:
                    c["samples"].append((lo[-12:], ro[:12], ln[-12:], rn[:12]))
            if num not in c["cues"] and len(c["cues"]) < 20:
                c["cues"].append(num)
            for t in _ref_tokens(ref):
                c["ref_tokens"][t] = c["ref_tokens"].get(t, 0) + 1
            c["last"] = today
            touched.add(k)
    # 第二遍：反例扫描——本模式所有候选（按扩展形态）在原文出现但校准后仍保留 = 未纠正反例
    for k, c in cands.items():
        if c["mode"] != mode or c["status"] == "rejected":
            continue
        w, _r = _learn_extended(c)
        for num, (oz, ref) in smap.items():
            if w not in oz:
                continue
            nz = omap.get(num, (oz,))[0]
            if w in nz:                       # 原文有、校准后仍在 -> 反例
                c["uncorrected"] += 1
                for t in _ref_tokens(ref):
                    c["unc_ref_tokens"][t] = c["unc_ref_tokens"].get(t, 0) + 1
    # 状态机更新 + 既有术语表查重（已沉淀的不再作为候选）
    tname = _MODE_TERM_TABLE.get(mode)
    builtin = TABLES.get(tname) or {}
    confirmed = demoted = conflicts = dup_builtin = 0
    for k in list(cands.keys()):
        c = cands[k]
        if c["mode"] == mode:
            ew, er = _learn_extended(c)
            if builtin.get(ew) == er or builtin.get(c["wrong"]) == c["right"]:
                del cands[k]                  # 已进扁平表/实体层，无需学习
                dup_builtin += 1
                continue
        if c["mode"] != mode:
            continue
        if _learn_update_status(c):
            demoted += 1
        confirmed += c["status"] == "confirmed"
        conflicts += bool(c.get("conflict"))
    _save_learned_kb(kb, kb_path)
    print(f"learn[{mode}]：cue {len(smap.keys() & omap.keys())}（无改动 {skip_same}）"
          f" | 新增候选 {new_cnt}，命中既有候选 {upd_cnt}，已沉淀去重 {dup_builtin}")
    print(f"学习库 {kb_path}：confirmed {confirmed} / 反例降级 {demoted} / 冲突待裁决 {conflicts}")
    if demoted:
        print("  ⚠ 有 confirmed 规则出现反例被降级，请 learned-show 查看 ctx_regex 建议")
    from .sync import _sync_export_learn_entries
    _sync_export_learn_entries(kb, kb_before, mode)



def _learned_terms_for_mode(kb_path, mode):
    """校准运行时注入：confirmed 且属本模式的学习规则 -> {扩展错形: 扩展正形}。"""
    kb = _load_learned_kb(kb_path)
    out = {}
    for c in kb["candidates"].values():
        if c["mode"] == mode and c["status"] == "confirmed" and not c.get("conflict"):
            w, r = _learn_extended(c)
            out[w] = r
    return out



def _cmd_learned_show(kb_path=LEARNED_KB_DEFAULT, mode=None):
    """learned-show：查看学习库候选（可按模式过滤）。"""
    kb = _load_learned_kb(kb_path)
    rows = [c for c in kb["candidates"].values() if not mode or c["mode"] == mode]
    if not rows:
        print("学习库为空" + (f"（模式 {mode}）" if mode else "")); return
    order = {"confirmed": 0, "candidate": 1, "rejected": 2}
    for c in sorted(rows, key=lambda x: (order.get(x["status"], 3), -x["count"])):
        flag = {"confirmed": "✓", "candidate": "…", "rejected": "✗"}[c["status"]]
        w, r = _learn_extended(c)
        ext = "" if (w, r) == (c["wrong"], c["right"]) else f"（应用形态 {w!r}->{r!r}）"
        line = (f"{flag} [{c['mode']}] {c['wrong']!r} -> {c['right']!r}{ext} "
                f"命中{c['count']} 反例{c['uncorrected']} cues{c['cues'][:6]}")
        if c.get("conflict"):
            line += f" ⚠冲突:亦被改为 {list(c['alts'])}"
        if c.get("ctx_regex"):
            line += f" | 建议佐证: /{c['ctx_regex']}/"
        if c.get("demoted"):
            line += " | [曾确认后降级]"
        print(line)
    print(f"合计 {len(rows)} 条（{kb_path}）")



def _cmd_learned_promote(kb_path=LEARNED_KB_DEFAULT, mode=None, entities=False):
    """learned-promote：confirmed 规则导出为 Entity 桩代码（--entities），
    人工审阅后粘贴进第 6 节 ENTITIES，完成 学习成果->对象级知识 的固化。"""
    kb = _load_learned_kb(kb_path)
    rows = [c for c in kb["candidates"].values()
            if c["status"] == "confirmed" and not c.get("conflict")
            and (not mode or c["mode"] == mode)]
    if not rows:
        print("# 无可固化的 confirmed 规则")
    else:
        by_right = {}
        for c in rows:
            w, r = _learn_extended(c)
            by_right.setdefault((r, c["mode"]), []).append((w, c))
        print("# ---- learned-promote 导出（人工审阅后并入 ENTITIES）----")
        for (right, m), cs in sorted(by_right.items()):
            variants = sorted({w for w, _ in cs}, key=len, reverse=True)
            cues = sorted({n for _, c in cs for n in c["cues"]})
            firsts = min(c["first"] for _, c in cs)
            print(f'    Entity({right!r}, modes=({m!r},),')
            print(f"           variants={tuple(variants)!r},")
            print(f"           note='学习库固化：{len(cs)}条规则，证据cue {cues[:8]}，"
                  f"首次 {firsts}。en/ja/ko/category 待人工补全'),")
    sugg = [c for c in kb["candidates"].values()
            if c["status"] == "candidate" and c.get("ctx_regex")
            and not c.get("conflict") and (not mode or c["mode"] == mode)]
    if sugg:
        print("\n# ---- 带反例的候选：建议作为 ctx 条件变体人工确认 ----")
        for c in sugg:
            w, r = _learn_extended(c)
            print(f"#   ctx=(({c['ctx_regex']!r}, {w!r}),)  # Entity({r!r}) 收"
                  f" 命中{c['count']} 反例{c['uncorrected']} [{c['mode']}]")



def _cmd_learned_reject(word, kb_path=LEARNED_KB_DEFAULT, mode=None):
    """learned-reject <错形>：人工否决候选（永不自动应用，保留证据）。
    v1.11.0：否决结果以 tombstone 增量通知其它客户端（FR-2）。"""
    kb = _load_learned_kb(kb_path)
    hit = 0
    modes = []
    for c in kb["candidates"].values():
        if c["wrong"] == word and (not mode or c["mode"] == mode):
            c["status"] = "rejected"
            hit += 1
            if c["mode"] not in modes:
                modes.append(c["mode"])
    if hit:
        _save_learned_kb(kb, kb_path)
        print(f"已否决 {hit} 条候选：{word!r}")
        from .sync import _sync_export_reject_tombstone
        _sync_export_reject_tombstone(word, modes)
    else:
        print(f"未找到候选：{word!r}")

