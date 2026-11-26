# -*- coding: utf-8 -*-
# @version 3.3.1
"""学习库与 learn/learned-*

源：subtitle_calib_merged.py L11185-L11554 @ 97d7d463（2026-10-24 冻结快照）
"""
import io
import os
import re
import shutil
import sys
import unicodedata
from .data.modes import _MODE_TERM_TABLE, normalize_mode
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
#    2026-11-24 状态机加固（版式/证据/审查）：
#      · 版式：cue 的中文行/参考行由 srt._cue_zh_ref 按字符集判定，
#        英文在上片源不再把英文当中文行学成「英文->英文」；
#      · count = 不同源文件数（candidate.files: 文件名 -> {n,alt,first,last}），
#        同一片源重复投喂不累加；旧库 count 作为 __legacy__ 伪文件基数迁移；
#      · uncorrected 分文件记录（unc_files），重投该片源即以本次重扫结果替换，
#        不再只增不减导致假反例永久锁死；
#      · 自动 confirmed 前两道审查：right 撞既有 canonical（互为子串/编辑距<=1，
#        置 conflict=target-collides-canonical:xxx）与命中内建表（置
#        conflict=already-in-builtin-table，不再静默删候选）；
#      · 单片快路径：应用形态属 canonicals 或显式 --force 时 count>=1 即确认。
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
    """解析 SRT -> [(num, 中文行(多行\\n连接), 参考行(多行\\n连接))]。结构容错同主引擎。

    2026-11-24 版式修复：旧实现写死「末行=参考行」（texts[:-1] / texts[-1]），
    遇到英文 ASR 在上、谷翻中文在下的双语片源整列错位——中文行被当成英文行、
    英文行被当成参考行，learn 于是学出「英文→英文」。这里改调 srt._cue_zh_ref
    按字符集判版式（中文在上/英文在上都兼容）；其余版式仍走位置约定，
    与旧行为逐字节一致。
    """
    from .srt import _cue_zh_ref
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
                    zh_idx, ref_idx = _cue_zh_ref(texts)
                    cues.append((int(s),
                                 "\n".join(texts[x] for x in zh_idx),
                                 "\n".join(texts[x] for x in ref_idx)))
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
    "皇帝",                # 2026-11-02 EP17 反应片：bi|皇帝→英白拉多 曾以 confirmed 注入 bi 趟，
                           # 把方舟片里字面读作 "Was that just Emperor over there?" 改成鸣潮专名。
                           # 存量条目已 learned-reject；此处补名单，防今后再次自动跃迁 confirmed。
})



def _learn_src_key(path):
    """源文件身份键：只用 basename（跨目录/换盘重投同一片源时仍算同一文件）。
    空名兜底为绝对路径，避免候选的 files 字典出现空键。"""
    base = os.path.basename(path or "")
    return base or os.path.abspath(path or "")


def _learn_migrate_candidate(c):
    """旧库候选（无 files/unc_files）就地迁移，保证向后兼容。

    2026-11-24 count 改为「不同源文件数」：旧库的 count 是**出现次数**聚合，
    无法还原文件归属，故整体记为 __legacy__ 伪文件（n=旧 count），后续只有
    新出现的源文件才 +1——旧 confirmed 仍满足 count>=2，状态不因迁移抖动。
    同理旧 uncorrected 聚合值挂 __legacy__，待该候选首次被真实文件命中时，
    以那次文件级重扫结果取代（不可复核的历史反例不再永久锁死规则）。
    """
    if not isinstance(c.get("files"), dict):
        c["files"] = {}
        if int(c.get("count") or 0) > 0:
            c["files"]["__legacy__"] = {"n": int(c.get("count") or 0), "alt": 0,
                                        "first": c.get("first", ""), "last": c.get("last", "")}
    if not isinstance(c.get("unc_files"), dict):
        c["unc_files"] = {}
        if int(c.get("uncorrected") or 0) > 0:
            c["unc_files"]["__legacy__"] = int(c.get("uncorrected") or 0)


def _learn_canonicals():
    """既有官方名集合（kb._kb_view 的 canonical 键）。导入/构建异常时返回空集，
    审查自动降级为不启用，不影响 learn 主流程。"""
    try:
        from .kb import _kb_view
        return set(_kb_view().keys())
    except Exception:
        return set()


def _edit_within_one(a, b):
    """编辑距离是否 <=1 且**至少 2 个字符相同**（纯 2 字目标与无关 2 字官名撞车不算）。

    2026-11-24：只判距离会把「甲甲」这类二字目标与「机甲/明庭」等表内二字词条
    一并判撞（共有字符仅 1），误伤面过大；要求共享 >=2 字后，
    「西格莉卡兰 vs 西格莉卡」「鸣潮亚 vs 鸣潮」这类真污染仍能拦下。
    """
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        same = sum(1 for x, y in zip(a, b) if x == y)
        return (len(a) - same) <= 1 and same >= 2
    if len(a) > len(b):
        a, b = b, a
    # b 比 a 长 1：能删掉 b 的某个字符得到 a 才算距离 1（共有字符 = len(a)）
    return len(a) >= 2 and any(b[:k] + b[k + 1:] == a for k in range(len(b)))


_LEARN_TERM_PUNCT = re.compile(r"[\s。，、！？；：…—\-·,.!?;:'\"()（）\[\]【】《》「」『』]")


def _learn_is_term_like(s):
    """目标形是否「名词级」：2-12 字、无空白/标点。

    learn 的候选里混有整句片段重写（「，至少当时的山城会是这样」）；
    它们不是专名目标，不参与子串撞名审查（编辑距<=1 的近似名仍审查）。
    """
    return bool(s) and 2 <= len(s) <= 12 and not _LEARN_TERM_PUNCT.search(s)


def _canonical_collision(right, canonicals):
    """right 是否"撞"既有官方名：编辑距 <=1，或（名词级目标）互为子串。

    2026-11-24 新增审查：learn 自动 confirmed 前必须过这一关，拦「机甲名→西格莉卡兰」
    这类把官名当子串/近似形的污染（right 含『西格莉卡』→ 判撞）。完全相等不算撞
    （那是官方名本身，属单片高置信快路径）。命中返回该 canonical，未命中返回 None；
    单字名噪音过大，不参与子串判定。
    """
    if not right or not canonicals or right in canonicals:
        return None
    term = _learn_is_term_like(right)
    for c in canonicals:
        if not c or c == right:
            continue
        if term and len(c) >= 3 and (right in c or c in right):
            # 只用 >=3 字的官方名做子串判定：二字表内词条（测试/机甲/装置…）泛用性
            # 太强，任何含它的短语目标都会被误判（实测「测试乙乙」撞「测试」）；
            # 二字官名的近似形（鸣潮亚 vs 鸣潮）由下方编辑距分支兜住。
            return c
        if _edit_within_one(right, c):
            return c
    return None



def _learn_update_status(c, canonicals=None, force=False):
    """候选状态机：count/uncorrected 驱动 确认/降级，并生成上下文建议。
    返回 True 表示本次发生了 confirmed->candidate 反例降级。

    2026-11-24 补审：
      · 自动 confirmed 前查**应用形态**（_learn_extended 的结果，即真正注入校准的键，
        非最小片段）是否撞既有 canonical，撞则拒确认并置 conflict
        （conflict_reason=target-collides-canonical:xxx）。
        审查只在 candidate->confirmed 跃迁时做（存量 confirmed 祖父条款，避免历史规则
        被一次性打成 conflict 造成注入面骤减）；目标事后进表/撞名解除时自动撤销该标记。
      · 单片快路径：right 属 canonicals 或显式 force 时，count>=1 即可确认；
        否则维持 count>=2。
      · DENY 检查同时看最小片段与应用形态（扩展后可能带前后缀，旧实现只比最小片段易绕过），
        名单本身不动，命中仍只保留候选 + needs_review。
    """
    if c["status"] == "rejected":
        return False
    ew, er = _learn_extended(c)
    cons = canonicals or ()
    if cons and c["status"] != "confirmed":
        # 只审**应用形态** er（= _learn_extended 结果，真正注入校准的键）。
        # 再拿最小片段 right 复判会误伤「right=官名片段、er=完整官名」的良性候选
        # （实测「盒子→之匣」应用形态是官方名『文明之匣』，却被最小片段判撞）。
        hit = None if er in cons else _canonical_collision(er, cons)
        if hit:
            c["conflict"] = True
            c["conflict_reason"] = "target-collides-canonical:" + hit
        elif str(c.get("conflict_reason") or "").startswith("target-collides-canonical:"):
            c.pop("conflict", None)
            c.pop("conflict_reason", None)
    if c.get("conflict"):
        c["status"] = "candidate"
        return False
    deny_hit = c["wrong"] in LEARN_AUTOCONFIRM_DENY or ew in LEARN_AUTOCONFIRM_DENY
    # 快路径认**应用形态**（_learn_extended 结果，即真正注入校准的键）是否官方名；
    # 只看最小片段 right 会放过「right=官名、扩展后=官名+后缀」的情形。
    # count>=1：只出现过 alts（无本目标证据）的候选即便 --force 也不确认。
    fast = c["count"] >= 1 and (bool(force) or er in cons)
    if c["uncorrected"] == 0 and (c["count"] >= 2 or fast):
        if deny_hit:
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



def _cmd_learn(src, calib, kb_path=LEARNED_KB_DEFAULT, mode="bi", force=False):
    """learn：投喂 [原始srt + 人工校准srt] 配对，挖掘候选规则并更新学习库。
    v1.11.0：收尾自动导出本次新增 confirmed 条目为增量并上传（FR-2）。
    2026-11-22 变体键降级：入口 normalize_mode——新沉淀落「游戏-细类」新键；
    库内旧键匹配时经 normalize 归一，无需数据迁移。
    2026-11-24 状态机加固：count 按源文件去重（同片重复投喂不累加）、uncorrected
    分文件记录可随重投重置、自动 confirmed 前过 canonical 撞名审查、
    单片快路径受 canonicals/--force 约束。"""
    import datetime
    import copy
    mode = normalize_mode(mode)
    src_key = _learn_src_key(src)
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
    #   count 语义（2026-11-24）：不同源文件数——同一文件重复投喂不累加；
    #   旧库 count 迁移为 __legacy__ 基数（见 _learn_migrate_candidate）。
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
                     "first": today, "last": today, "alts": {},
                     "files": {}, "unc_files": {}}
                cands[k] = c
                new_cnt += 1
            else:
                upd_cnt += 1
            _learn_migrate_candidate(c)
            fe = c["files"].get(src_key)
            if fe is None:
                # 旧库 count<=1（单次出现、无文件归属）：本文件首次投喂按「同一文件重投」
                # 保守处理，先撤 __legacy__ 再计本文件，避免旧库候选一投喂就凑到 count=2。
                if "__legacy__" in c["files"] and c["count"] <= 1 and len(c["files"]) == 1:
                    c["files"].pop("__legacy__", None)
                    c["count"] = 0
                fe = c["files"][src_key] = {"n": 0, "alt": 0,
                                            "first": today, "last": today}
            if c["right"] != right:
                c["alts"][right] = c["alts"].get(right, 0) + 1
                c["conflict"] = True          # 同一错形被改成不同目标：人工裁决
                fe["alt"] = int(fe.get("alt") or 0) + 1
            else:
                if not int(fe.get("n") or 0):
                    c["count"] += 1           # 只有新源文件才计数：同片重复投喂不累加
                fe["n"] = int(fe.get("n") or 0) + 1
                if len(c["samples"]) < 10:
                    c["samples"].append((lo[-12:], ro[:12], ln[-12:], rn[:12]))
            fe["last"] = today
            if num not in c["cues"] and len(c["cues"]) < 20:
                c["cues"].append(num)
            for t in _ref_tokens(ref):
                c["ref_tokens"][t] = c["ref_tokens"].get(t, 0) + 1
            c["last"] = today
            touched.add(k)
    # 第二遍：反例扫描——本模式所有候选（按扩展形态）在原文出现但校准后仍保留 = 未纠正反例
    # （存量旧键候选经 normalize_mode 归一后同属本模式，一并参与扫描）
    # 2026-11-24：反例按源文件记账（unc_files），本次投喂文件的反例以重扫结果替换而非累加；
    #   旧实现的 uncorrected 只增不减，一片源的历史反例会把规则永久锁死在 candidate。
    for k, c in cands.items():
        if normalize_mode(c["mode"]) != mode or c["status"] == "rejected":
            continue
        _learn_migrate_candidate(c)
        w, _r = _learn_extended(c)
        seen = 0
        observed = False
        for num, (oz, ref) in smap.items():
            if w not in oz:
                continue
            observed = True
            nz = omap.get(num, (oz,))[0]
            if w in nz:                       # 原文有、校准后仍在 -> 反例
                seen += 1
                for t in _ref_tokens(ref):
                    c["unc_ref_tokens"][t] = c["unc_ref_tokens"].get(t, 0) + 1
        if observed:
            c["unc_files"].pop("__legacy__", None)   # 不可复核的旧聚合值：首次文件级重扫即取代
            if seen:
                c["unc_files"][src_key] = seen
            else:
                c["unc_files"].pop(src_key, None)
        c["uncorrected"] = sum(int(v) for v in c["unc_files"].values()
                               if isinstance(v, int) and v > 0)
    # 状态机更新 + 既有术语表查重（已沉淀的标冲突而非静默删除）
    tname = _MODE_TERM_TABLE.get(mode)
    builtin = TABLES.get(tname) or {}
    canonicals = _learn_canonicals()
    confirmed = demoted = conflicts = dup_builtin = 0
    for k in list(cands.keys()):
        c = cands[k]
        c_mode = normalize_mode(c["mode"])    # 存量旧键归一为新键
        if c_mode == mode:
            ew, er = _learn_extended(c)
            if builtin.get(ew) == er or builtin.get(c["wrong"]) == c["right"]:
                # 2026-11-24：命中内建表不再 del 候选（旧实现静默删除，重复投喂看不出来、
                # 也无法纠错），改为 conflict 标记保留证据，人工 learned-show 可见。
                c["conflict"] = True
                c["conflict_reason"] = "already-in-builtin-table"
                c["needs_review"] = True
                dup_builtin += 1
        if c_mode != mode:
            continue
        if _learn_update_status(c, canonicals=canonicals, force=force):
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



# 2026-11-09 学习库注入黑名单（WuWa 3.8 REACTION 片三轮回灌实测）：confirmed 裸键
# 跨片污染的人工裁定登记处——按「无证据不改」只收**本片实测改坏成品**的键；学习库文件
# 本身不动（留待 learned-reject 人工裁决），此处仅在注入层跳过。注意：跳过后打印的
# "confirmed 规则 N 条"会比库内实数少，属预期。实测学习库 bi 模式 <=3 汉字且无
# ref_tokens/ctx_regex 的 confirmed 裸键共 87 条（光泽/溪流/拖车/满的/爱过/班车…），
# 自动判据会误杀「明朝→鸣潮」「由纪→绯雪」类好规则，故只能逐条人工登记，宁缺毋滥。
KB_INJECT_BLOCKLIST = {
    "bi|光泽",   # →心月狐（count 21、ref_tokens 空、2026-10-05~19 单片样本泛化）：
                 #   本片 #617「其他一切看起来都缺乏光泽」→「缺乏心月狐」、#490「夜晚流转的
                 #   光泽」→「夜晚流转的心月狐」产出病句；心月狐非鸣潮共鸣者（wiki 无条目）。
                 #   即 concert-reaction-calib 记忆所述「单 cue 样本泛化的普通词规则跨片污染」再现。
}


def _learned_terms_for_mode(kb_path, mode):
    """校准运行时注入：confirmed 且属本模式的学习规则 -> {扩展错形: 扩展正形}。
    2026-11-09 起按 KB_INJECT_BLOCKLIST 跳过人工裁定的危险裸键（见该清单注释）。
    2026-11-22 变体键降级：mode 与库内候选 mode 均经 normalize_mode 归一，
    旧键沉淀的 confirmed 规则在对应新键运行时照常注入。"""
    mode = normalize_mode(mode)
    kb = _load_learned_kb(kb_path)
    out = {}
    for c in kb["candidates"].values():
        c_mode = normalize_mode(c["mode"])
        if c_mode == mode and c["status"] == "confirmed" and not c.get("conflict"):
            if "{}|{}".format(c_mode, c["wrong"]) in KB_INJECT_BLOCKLIST:
                continue
            w, r = _learn_extended(c)
            out[w] = r
    return out



def _cmd_learned_show(kb_path=LEARNED_KB_DEFAULT, mode=None):
    """learned-show：查看学习库候选（可按模式过滤；旧键经 normalize_mode 归一匹配）。"""
    mode = normalize_mode(mode) if mode else mode
    kb = _load_learned_kb(kb_path)
    rows = [c for c in kb["candidates"].values()
            if not mode or normalize_mode(c["mode"]) == mode]
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
            if c.get("alts"):
                line += f" ⚠冲突:亦被改为 {list(c['alts'])}"
            elif c.get("conflict_reason"):
                # 2026-11-24 审查类冲突（撞官名/命中内建表）无 alts，直接给原因
                line += f" ⚠冲突:{c['conflict_reason']}"
        if c.get("ctx_regex"):
            line += f" | 建议佐证: /{c['ctx_regex']}/"
        if c.get("demoted"):
            line += " | [曾确认后降级]"
        print(line)
    print(f"合计 {len(rows)} 条（{kb_path}）")



def _cmd_learned_promote(kb_path=LEARNED_KB_DEFAULT, mode=None, entities=False):
    """learned-promote：confirmed 规则导出为 Entity 桩代码（--entities），
    人工审阅后粘贴进第 6 节 ENTITIES，完成 学习成果->对象级知识 的固化。
    2026-11-22 变体键降级：模式过滤与导出桩的 modes 均经 normalize_mode 归一（落新键）。"""
    mode = normalize_mode(mode) if mode else mode
    kb = _load_learned_kb(kb_path)
    rows = [c for c in kb["candidates"].values()
            if c["status"] == "confirmed" and not c.get("conflict")
            and (not mode or normalize_mode(c["mode"]) == mode)]
    if not rows:
        print("# 无可固化的 confirmed 规则")
    else:
        by_right = {}
        for c in rows:
            w, r = _learn_extended(c)
            by_right.setdefault((r, normalize_mode(c["mode"])), []).append((w, c))
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
            and not c.get("conflict") and (not mode or normalize_mode(c["mode"]) == mode)]
    if sugg:
        print("\n# ---- 带反例的候选：建议作为 ctx 条件变体人工确认 ----")
        for c in sugg:
            w, r = _learn_extended(c)
            print(f"#   ctx=(({c['ctx_regex']!r}, {w!r}),)  # Entity({r!r}) 收"
                  f" 命中{c['count']} 反例{c['uncorrected']} [{c['mode']}]")



def _cmd_learned_reject(word, kb_path=LEARNED_KB_DEFAULT, mode=None):
    """learned-reject <错形>：人工否决候选（永不自动应用，保留证据）。
    v1.11.0：否决结果以 tombstone 增量通知其它客户端（FR-2）。
    2026-11-22 变体键降级：模式过滤与 tombstone 通知均经 normalize_mode 归一。"""
    mode = normalize_mode(mode) if mode else mode
    kb = _load_learned_kb(kb_path)
    hit = 0
    modes = []
    for c in kb["candidates"].values():
        c_mode = normalize_mode(c["mode"])
        if c["wrong"] == word and (not mode or c_mode == mode):
            c["status"] = "rejected"
            hit += 1
            if c_mode not in modes:
                modes.append(c_mode)
    if hit:
        _save_learned_kb(kb, kb_path)
        print(f"已否决 {hit} 条候选：{word!r}")
        from .sync import _sync_export_reject_tombstone
        _sync_export_reject_tombstone(word, modes)
    else:
        print(f"未找到候选：{word!r}")

