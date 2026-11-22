# -*- coding: utf-8 -*-
# @version 3.2.0
"""包C-1：Jev mention 消歧评测集构建（真实双语字幕 + 合成补足）。

三层金标来源：
  * G1  outbox 成品（人工复审发布稿）的 dis=True 正例——人工抽检层；
  * G2  data/pipeline_work 的双语 .zh.srt 原译（**非 .calib 产物**）的 dis=True 正例；
  * G3  合成补足（真实文本跨 cue 配对 / 同行错形换目标），全部打 synthetic 标记。

子集：
  * T1  dis=True 正例（≥120，天然 <80 时允许合成补足）——「给足候选证据的分类」能力集；
  * T2  tb_fail 待人工金标（≥40，人工标注清单随集产出）——Jev 唯一价值空间；
  * T3  音乐/通用词假候选（≥30，Jev 应答 cannot_determine）。

硬负例三类：neg_wrong_pick（同 T 换 zh 目标）/ neg_no_anchor（T 与 zh 不相交，复刻 #207）
/ neg_false_candidate（音乐/通用词假候选）。正负约 1:2；hash 20% 切 eval。

金标污染防线：任何 case 的 source/ref_source 都不得指向 *.calib.srt
（构建器跳过 + 落盘前断言 + 汇总报告），G2 只收 .zh.srt 原译。

用法：
  tools\\python\\python.exe scripts\\dev\\build_jev_mention_dataset.py            # 全量构建
  tools\\python\\python.exe scripts\\dev\\build_jev_mention_dataset.py --t1-target 140
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from calib_core.asr import _ref_for_match  # noqa: E402
from calib_core.mention import (  # noqa: E402
    MentionPairer, build_maps, longest_bounded, scope_state,
    _is_generic, _is_music, _parent_tiebreak)
from calib_core.text import _split_cue_text  # noqa: E402

SCHEMA = "jev-mention-benchmark/1"
UNCERTAIN = ""          # gold 为空串 = 无法从证据判定（cannot_determine）
MIN_ZH, MAX_ZH = 4, 300

#: 单字金标噪声黑名单：如「心」在中文行任意位置都会被 AC 命中（担心/开心…），
#: 作为 dis=True 金标会产生假正例，T1 一律不收。
NOISE_GOLD = {"心"}

_CUE_RX = re.compile(
    r"(?ms)^\s*(\d+)\s*\n"
    r"(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})\s*\n"
    r"(.+?)(?=\n\s*\n\s*\d+\s*\n|\Z)")


# ---------------------------------------------------------------- SRT 解析


_PARSE_CACHE = {}


def parse_bilingual_cues(path):
    """带缓存的解析（构建器要多次全量扫描，避免重复 IO/正则）。"""
    """按 engine 同款口径拆双语 cue，返回 [(num, zh, ref, context_dict)]。

    context 携带 ±2 邻 cue 的 (zh, ref)，供 T2 人工标注。
    """
    raw = open(path, "r", encoding="utf-8", errors="replace").read()
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    if raw.startswith("\ufeff"):
        raw = raw[1:]
    cues = []
    if path in _PARSE_CACHE:
        return _PARSE_CACHE[path]
    for m in _CUE_RX.finditer(raw):
        num = int(m.group(1))
        texts = [ln for ln in m.group(4).split("\n") if ln.strip()]
        if len(texts) < 2:
            continue
        zh_pos, ref_pos = _split_cue_text(texts)
        if not zh_pos or not ref_pos:
            continue
        zh = texts[zh_pos[0]].strip()
        ref = " ".join(texts[p].strip() for p in ref_pos)
        cues.append((num, zh, ref))
    out = []
    for idx, (num, zh, ref) in enumerate(cues):
        ctx = {}
        for tag, off in (("prev", -2), ("prev1", -1), ("next1", 1), ("next", 2)):
            j = idx + off
            if 0 <= j < len(cues):
                _n, _z, _r = cues[j]
                ctx[tag] = {"zh": _z, "ref": _r}
        out.append((num, zh, ref, ctx))
    _PARSE_CACHE[path] = out
    return out


def iter_sources():
    """(group, path) 列表；**绝不**包含 *.calib.srt（金标污染防线第一道）。"""
    out = []
    base = os.path.join(ROOT, "data", "pipeline_work")
    for dirpath, _dn, filenames in os.walk(base):
        for fn in sorted(filenames):
            if fn.endswith(".zh.srt"):
                out.append(("pipeline_work", os.path.join(dirpath, fn)))
    outbox = os.path.join(ROOT, "outbox")
    for dirpath, _dn, filenames in os.walk(outbox):
        for fn in sorted(filenames):
            if not fn.endswith(".srt") or fn.endswith(".calib.srt"):
                continue
            out.append(("outbox", os.path.join(dirpath, fn)))
    return out


# ---------------------------------------------------------------- 挖掘


def _zh_anchor_present(M, zh, targets):
    """字符串级（大小写不敏感、无词边界）锚点检测：zh 行是否含 T 候选的任何
    注册形式。引擎自动机有大小写+CJK 邻字符边界盲区（如「这是Meta的秀」），
    人眼可见的锚点必须按字符串判定——有锚点归 T2（人工裁决），真无锚点才复刻 #207。"""
    low = (zh or "").lower()
    for key, tg in M["zh_map"].items():
        if tg and (set(tg) & set(targets)) and key and key.lower() in low:
            return True
    return False


def _failing_targets(M, zh, anchor, pairer):
    """重放 scope_state 的 tb_fail 裁决顺序，返回 (T, true_no_anchor, any_fail)。

    true_no_anchor：T 与 zh 在**字符串级**都不相交（复刻 #207 形态；
    金标=uncertain 硬负例）。zh 行保留了 T 候选形式（如大写 Meta）但引擎
    因大小写/词边界判不出的，归 T2 待人工金标。
    """
    ref_ms = longest_bounded(M["ref_auto"], anchor.lower()) if anchor else []
    zh_ms = longest_bounded(M["zh_auto"], zh)
    targets, any_fail = set(), False
    for i, (_, _, _, rt) in enumerate(ref_ms):
        if len(rt) <= 1:
            continue
        zt = set(zh_ms[i][3]) if i < len(zh_ms) else set()
        if len(rt & zt) == 1:
            continue                      # 规则1 已裁决
        if _parent_tiebreak(set(rt)):     # 规则2（当前数据为空，防御保留）
            continue
        any_fail = True
        targets |= set(rt)
    if not any_fail:
        return set(), False, False
    no_anchor = not _zh_anchor_present(M, zh, targets)
    return targets, no_anchor, True



def mine_corpus(modes=("bi", "ak")):
    """全量扫描，返回 (mining, hits)。

    mining：全库计数（ambiguous/dis_true/tb_fail/music_generic/未解析专名）。
    hits：按 (group, path, mode) 保留命中 cue 的原始四元组，供子集构造复用。
    """
    mining = Counter()
    hits = defaultdict(list)
    for group, path in iter_sources():
        try:
            cues = parse_bilingual_cues(path)
        except OSError:
            continue
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        for mode in modes:
            M = build_maps(mode)
            pairer = MentionPairer(mode)
            for num, zh, ref, ctx in cues:
                if not (MIN_ZH <= len(zh) <= MAX_ZH) or len(ref) > 800:
                    continue
                anchor = _ref_for_match(ref)
                res = pairer.pair(zh, ref)
                enabled, R, st = scope_state(M, zh, anchor)
                amb = res.get("ambiguous") or []
                if amb:
                    mining["ambiguous_mentions"] += len(amb)
                    if any(_is_music(set(a[2])) for a in amb):
                        mining["ambiguous_music_mentions"] += 1
                    if any(_is_generic(set(a[2])) for a in amb):
                        mining["ambiguous_generic_mentions"] += 1
                dis_true = [a for a in amb if a[5]]
                dis0 = [a for a in amb if not a[5]]
                if dis_true:
                    mining["dis_true_mentions"] += len(dis_true)
                if dis0:
                    mining["ambiguous_dis0_mentions"] += len(dis0)
                up = res.get("unresolved_proper") or []
                mining["unresolved_proper_mentions"] += len(up)
                tb = int((st or {}).get("tb_fail", 0))
                if enabled and tb > 0:
                    mining["tb_fail_cues"] += 1
                    T, no_anchor, _ = _failing_targets(M, zh, anchor, pairer)
                    if _is_music(T):
                        mining["tb_fail_music_cues"] += 1
                    elif _is_generic(T):
                        mining["tb_fail_generic_cues"] += 1
                    if no_anchor:
                        mining["tb_fail_true_no_anchor_cues"] += 1
                    hits[(group, rel, mode)].append(
                        {"cue": num, "zh": zh, "ref": ref, "ctx": ctx,
                         "kind": "tb_fail", "T": sorted(T),
                         "no_anchor": no_anchor, "stats": dict(st)})
                elif dis_true and not (enabled and tb > 0):
                    # dis=True 正例：多目标 ref 被 zh 序次交集唯一裁决（非 .calib 产物）
                    for a in dis_true:
                        rt = set(a[2])
                        gold_set = rt & set(a[4])
                        if len(gold_set) != 1:
                            continue
                        gold = sorted(gold_set)[0]
                        if gold in NOISE_GOLD or _is_music(rt) or _is_generic(rt):
                            mining["dis_true_skipped_noise"] += 1
                            continue
                        mining["dis_true_usable"] += 1
                        hits[(group, rel, mode)].append(
                            {"cue": num, "zh": zh, "ref": ref, "ctx": ctx,
                             "kind": "dis_true", "T": sorted(rt), "gold": gold,
                             "surface": a[1], "stats": dict(st)})
                        break
    for key in ("ambiguous_mentions", "ambiguous_music_mentions",
                "ambiguous_generic_mentions", "ambiguous_dis0_mentions",
                "dis_true_mentions", "dis_true_usable",
                "dis_true_skipped_noise", "unresolved_proper_mentions",
                "tb_fail_cues", "tb_fail_true_no_anchor_cues",
                "tb_fail_music_cues", "tb_fail_generic_cues"):
        mining.setdefault(key, 0)
    return mining, hits


def multi_surfaces(M, want="clean"):
    """ref_map 中多目标表面形。want=clean(非音乐/通用) / music / generic。"""
    out = {}
    for s, t in M["ref_map"].items():
        if len(t) < 2:
            continue
        if want == "clean" and not (_is_music(t) or _is_generic(t)):
            out[s] = frozenset(t)
        elif want == "music" and _is_music(t):
            out[s] = frozenset(t)
        elif want == "generic" and _is_generic(t):
            out[s] = frozenset(t)
    return out


def zh_form_for(M, canon):
    """zh_map 中「只映射 canon」的最短表面形（错形换目标用，避免歧义形）。"""
    best = None
    for s, t in M["zh_map"].items():
        if set(t) == {canon}:
            if best is None or len(s) < len(best) or (
                    len(s) == len(best) and s < best):
                best = s
    return best


class DatasetBuilder:
    """按 G1/G2/G3 三层金标 + 三类硬负例装配评测集。"""

    def __init__(self, t1_target=150, t2_target=48, t3_target=32,
                 max_per_file=28, max_per_gold=80):
        self.t1_target = t1_target
        self.t2_target = t2_target
        self.t3_target = t3_target
        self.max_per_file = max_per_file
        self.max_per_gold = max_per_gold
        self.pairers = {}
        self.maps = {}
        self.cases = []
        self.seen_pairs = set()
        self.per_file = Counter()
        self.per_gold = Counter()
        self.trace = Counter()

    def pairer(self, mode):
        if mode not in self.pairers:
            self.pairers[mode] = MentionPairer(mode)
            self.maps[mode] = build_maps(mode)
        return self.pairers[mode]

    def maps_for(self, mode):
        self.pairer(mode)
        return self.maps[mode]

    # -------------------------------------------------- 基础工具

    def _push(self, case):
        key = (case["zh"], case["ref"])
        if key in self.seen_pairs:
            self.trace["dup_pair"] += 1
            return False
        if self.per_file[case["source"]] >= self.max_per_file:
            self.trace["cap_file"] += 1
            return False
        gkey = (case["tier"], case.get("gold", ""), case.get("surface", ""))
        if case["label"] == "positive" and \
                self.per_gold[gkey] >= self.max_per_gold:
            self.trace["cap_gold"] += 1
            return False
        self.seen_pairs.add(key)
        self.per_file[case["source"]] += 1
        self.per_gold[gkey] += 1
        self.cases.append(case)
        return True

    def _base_case(self, tier, label, mode, hit, source, cue):
        return {
            "tier": tier, "label": label, "mode": mode,
            "zh": hit["zh"], "ref": hit["ref"],
            "T": list(hit["T"]), "gold": hit.get("gold", UNCERTAIN),
            "source": source, "cue": cue,
            "ctx": hit.get("ctx") or {},
        }

    # -------------------------------------------------- T1：dis=True 正例

    def build_t1_natural(self, hits):
        """G1(outbox 成品)+G2(pipeline_work 原译) 的天然 dis=True 正例。"""
        n = 0
        for (group, rel, mode), items in sorted(hits.items()):
            for h in items:
                if h["kind"] != "dis_true":
                    continue
                case = self._base_case("T1", "positive", mode, h, rel, h["cue"])
                case["gold_source"] = ("outbox_product" if group == "outbox"
                                       else "pair_dis_true")
                case["gold_status"] = "mechanical"
                case["synthetic"] = ""
                case["surface"] = h.get("surface", "")
                if self._push(case):
                    n += 1
                    self.trace["t1_natural_%s" % group] += 1
        return n

    def build_t1_synthetic(self, hits):
        """G3 合成补足：真实 zh（唯一金标形）× 真实 ref（多目标表面形）跨 cue 配对。

        只拼真实文本，不生成新句子；配对后必须通过真实 pair_cue/scope_state
        验证（存在 dis=True 且金标一致、tb_fail==0），否则弃用。
        """
        # 1) 素材池：多目标表面形（clean）→ 目标集 T
        surf_T = {}
        for mode in ("bi", "ak"):
            for s, t in multi_surfaces(build_maps(mode), want="clean").items():
                key = tuple(sorted(t))
                surf_T.setdefault(key, (mode, s))
        if not surf_T:
            return 0
        # 2) zh 金标行池（该行 zh 自动机命中恰好 T 中一个候选的合法形，记录序位）
        gold_pool = defaultdict(list)      # (T_key, gold, idx) -> [(rel, cue, zh, ctx)]
        ref_pool = defaultdict(list)       # (T_key, idx) -> [(rel, cue, ref, surface)]
        for group, path in iter_sources():
            try:
                cues = parse_bilingual_cues(path)
            except OSError:
                continue
            rel = os.path.relpath(path, ROOT).replace("\\", "/")
            mode = "bi"                     # clean 多目标表面形均在 bi 模式
            M = self.maps_for(mode)
            for num, zh, ref, ctx in cues:
                if not (MIN_ZH <= len(zh) <= MAX_ZH) or len(ref) > 800:
                    continue
                zh_ms = longest_bounded(M["zh_auto"], zh)
                zh_targets = set()
                for _s0, _e0, sf, tg in zh_ms:
                    zh_targets |= set(tg)
                anchor = _ref_for_match(ref)
                ref_ms = longest_bounded(M["ref_auto"], anchor.lower()) if anchor else []
                for i, (_s0, _e0, sf, tg) in enumerate(ref_ms):
                    tkey = tuple(sorted(set(tg)))
                    if tkey in surf_T:
                        ref_pool[(tkey, i)].append((rel, num, ref, sf))
                for tkey, (m0, s0) in surf_T.items():
                    present = set(tkey) & zh_targets
                    absent = set(tkey) - zh_targets
                    if len(present) != 1 or not absent:
                        continue
                    gold = sorted(present)[0]
                    if gold in NOISE_GOLD:
                        continue
                    # 金标承载 mention 的序位（供 ref 侧多目标 mention 序位对齐）
                    gidx = None
                    for j, (_a, _b, _sf, tg2) in enumerate(zh_ms):
                        if set(tg2) & set(tkey) == {gold}:
                            gidx = j
                            break
                    if gidx is None:
                        continue
                    gold_pool[(tkey, gold, gidx)].append(
                        (rel, num, zh, ctx))
        # 3) 配对：序位对齐（zh 金标 mention 序位 == ref 多目标 mention 序位），
        #    优先同文件，其次跨文件；真实引擎验证
        made = 0
        for (tkey, gold, zidx), zh_items in sorted(gold_pool.items(),
                                                   key=lambda kv: -len(kv[1])):
            if self.per_gold[("T1", gold, "")] >= self.max_per_gold:
                continue
            mode, surf = surf_T[tkey]
            refs = ref_pool.get((tkey, zidx)) or []
            if not refs:
                continue
            by_file = defaultdict(list)
            for rel, num, ref, sf in refs:
                by_file[rel].append((num, ref, sf))
            for zrel, zcue, zh, zctx in zh_items:
                if made >= self.t1_target:
                    break
                if self.per_gold[("T1", gold, "")] >= self.max_per_gold:
                    break
                cand = []
                # 合成配对要求跨 cue（同 cue 配对即天然对，走 T1 natural 分支）
                cand.extend((zrel,) + r for r in by_file.get(zrel, ())
                            if r[0] != zcue)
                for rel2, lst in sorted(by_file.items()):
                    if rel2 == zrel:
                        continue
                    cand.extend((rel2,) + r for r in lst)
                # 同一 zh 行最多配 3 条不同 ref（不同 ref 语境=不同用例）
                made_for_zh = 0
                for rsrc, rcue, ref, sf in cand:
                    if made_for_zh >= 3 or made >= self.t1_target:
                        break
                    if self.per_file[zrel] >= self.max_per_file:
                        break
                    case = {
                        "tier": "T1", "label": "positive", "mode": mode,
                        "zh": zh, "ref": ref, "T": list(tkey), "gold": gold,
                        "source": zrel, "cue": zcue,
                        "ref_source": rsrc, "ref_cue": rcue,
                        "surface": surf,
                        "gold_source": "synthetic_cross_cue_pair",
                        "gold_status": "mechanical",
                        "synthetic": "cross_cue_pair",
                        "ctx": zctx,
                    }
                    if not self._verify(case):
                        self.trace["t1_verify_fail"] += 1
                        continue
                    if self._push(case):
                        made += 1
                        made_for_zh += 1
                        self.trace["t1_synthetic"] += 1
        return made

    def _verify(self, case):
        """真实引擎验证：dis=True（交集恰为 gold）且 scope_state 无 tb_fail。"""
        mode = case["mode"]
        M = self.maps_for(mode)
        pairer = self.pairer(mode)
        res = pairer.pair(case["zh"], case["ref"])
        anchor = _ref_for_match(case["ref"])
        enabled, _R, st = scope_state(M, case["zh"], anchor)
        if enabled and int((st or {}).get("tb_fail", 0)) > 0:
            return False
        T = set(case["T"])
        for a in (res.get("ambiguous") or []):
            if not a[5]:
                continue
            rt, zt = set(a[2]), set(a[4])
            inter = rt & zt
            if len(inter) == 1 and sorted(inter)[0] == case["gold"] and rt == T:
                return True
        return False

    # -------------------------------------------------- wrong_pick 硬负例

    def build_wrong_pick(self):
        """同 T 换 zh 目标：把 zh 行中金标形式换成 T 内另一候选的唯一合法形。

        换形后金标 = 新形式的候选（机械可验证）；陷阱在于 ref/上下文仍指向原候选，
        先验偏置的模型会 pick 原候选。全部打 synthetic=form_swap。
        """
        t1_pos = [c for c in self.cases
                  if c["tier"] == "T1" and c["label"] == "positive"]
        made = 0
        for case in t1_pos:
            M = self.maps_for(case["mode"])
            zh_ms = longest_bounded(M["zh_auto"], case["zh"])
            old_form = None
            for s0, e0, sf, tg in zh_ms:
                if set(tg) == {case["gold"]}:
                    old_form = sf
                    break
            if not old_form:
                continue
            others = [c for c in case["T"] if c != case["gold"]]
            if not others:
                continue
            other = others[0]
            new_form = zh_form_for(M, other)
            if not new_form or new_form == old_form:
                self.trace["wrong_pick_no_form"] += 1
                continue
            zh2 = case["zh"].replace(old_form, new_form)
            if zh2 == case["zh"]:
                continue
            zh2_targets = set()
            for _s0, _e0, sf, tg in longest_bounded(M["zh_auto"], zh2):
                zh2_targets |= set(tg)
            if zh2_targets & set(case["T"]) != {other}:
                self.trace["wrong_pick_verify_fail"] += 1
                continue
            neg = dict(case)
            neg["zh"] = zh2
            neg["gold"] = other
            neg["label"] = "negative"
            neg["pair"] = "neg_wrong_pick"
            neg["gold_source"] = "synthetic_form_swap"
            neg["gold_status"] = "mechanical"
            neg["synthetic"] = "form_swap"
            neg["swapped_from"] = case["gold"]
            neg["swapped_form"] = "%s->%s" % (old_form, new_form)
            neg.pop("id", None)
            if self._push(neg):
                made += 1
                self.trace["wrong_pick"] += 1
        return made

    # -------------------------------------------------- T2 待人工金标 + no_anchor

    def build_t2_and_no_anchor(self, hits):
        """T2：tb_fail 且 zh 歧义形存在（人工裁决）→ 待人工金标清单。

        no_anchor：tb_fail 且失败位置 zh 目标全空（复刻 #207）→ 金标=uncertain 硬负例。
        """
        t2_items, no_anchor = [], []
        for (group, rel, mode), items in sorted(hits.items()):
            for h in items:
                if h["kind"] != "tb_fail":
                    continue
                if h.get("no_anchor"):
                    no_anchor.append((group, rel, mode, h))
                elif not (_is_music(set(h["T"])) or _is_generic(set(h["T"]))):
                    t2_items.append((group, rel, mode, h))
        made_t2 = 0
        for group, rel, mode, h in t2_items:
            if made_t2 >= self.t2_target:
                break
            case = self._base_case("T2", "pending", mode, h, rel, h["cue"])
            case["gold"] = UNCERTAIN
            case["gold_source"] = "pending_human"
            case["gold_status"] = "pending_human"
            case["suggested_gold"] = ""
            case["synthetic"] = ""
            case["stats"] = h.get("stats") or {}
            if self._push(case):
                made_t2 += 1
                self.trace["t2_pending"] += 1
        made_na = 0
        na_budget = max(40, 2 * self._count_pos() - self._count_neg() - self.t3_target)
        for group, rel, mode, h in no_anchor:
            if made_na >= na_budget:
                break
            if _is_music(set(h["T"])) or _is_generic(set(h["T"])):
                continue
            case = self._base_case("T2", "negative", mode, h, rel, h["cue"])
            case["gold"] = UNCERTAIN
            case["pair"] = "neg_no_anchor"
            case["gold_source"] = "no_zh_anchor_replicates_207"
            case["gold_status"] = "mechanical"
            case["synthetic"] = ""
            case["stats"] = h.get("stats") or {}
            if self._push(case):
                made_na += 1
                self.trace["no_anchor"] += 1
        if made_na < na_budget:
            made_na += self._synth_no_anchor(na_budget - made_na)
        return made_t2, made_na, len(t2_items), len(no_anchor)

    def _synth_no_anchor(self, budget, refs_per_zh=1):
        """合成 no_anchor 补足：真实 zh 行（字符串级无 T 锚点）× 真实 ref 行
        （含多目标表面形）。引擎验证 tb_fail>0；金标=uncertain（复刻 #207）。"""
        made = 0
        surf_T = {}
        for mode in ("bi", "ak"):
            for s, t in multi_surfaces(build_maps(mode), want="clean").items():
                surf_T.setdefault(tuple(sorted(t)), (mode, s))
        if not surf_T:
            return 0
        ref_by_file = defaultdict(list)     # rel -> [(cue, ref, T_key)]
        zh_pool = []
        for group, path in iter_sources():
            try:
                cues = parse_bilingual_cues(path)
            except OSError:
                continue
            rel = os.path.relpath(path, ROOT).replace("\\", "/")
            M = self.maps_for("bi")
            for num, zh, ref, ctx in cues:
                if not (MIN_ZH <= len(zh) <= MAX_ZH) or len(ref) > 800:
                    continue
                anchor = _ref_for_match(ref)
                for _s0, _e0, sf, tg in (longest_bounded(
                        M["ref_auto"], anchor.lower()) if anchor else []):
                    tkey = tuple(sorted(set(tg)))
                    if tkey in surf_T:
                        ref_by_file[rel].append((num, ref, tkey, surf_T[tkey][0]))
                        break
                zh_pool.append((rel, num, zh, ctx))
        import random as _random
        rng = _random.Random(20261122)
        rng.shuffle(zh_pool)
        for zrel, zcue, zh, zctx in zh_pool:
            if made >= budget:
                break
            if self.per_file[zrel] >= self.max_per_file:
                continue
            # 优先同文件 ref，其次跨文件
            refs = list(ref_by_file.get(zrel, ()))
            for rel2 in sorted(ref_by_file):
                if rel2 != zrel:
                    refs.extend(ref_by_file[rel2])
            for rcue, ref, tkey, rmode in refs:
                if made >= budget or self.per_file[zrel] >= self.max_per_file:
                    break
                M = self.maps_for(rmode)
                if _zh_anchor_present(M, zh, tkey):
                    continue                # zh 行含 T 形 → 非 no_anchor
                anchor = _ref_for_match(ref)
                enabled, _R, st = scope_state(M, zh, anchor)
                if not (enabled and int((st or {}).get("tb_fail", 0)) > 0):
                    self.trace["no_anchor_synth_verify_fail"] += 1
                    continue
                case = {
                    "tier": "T2", "label": "negative", "mode": rmode,
                    "zh": zh, "ref": ref, "T": list(tkey), "gold": UNCERTAIN,
                    "source": zrel, "cue": zcue, "ref_cue": rcue,
                    "surface": surf_T[tkey][1], "ctx": zctx,
                    "pair": "neg_no_anchor",
                    "gold_source": "no_zh_anchor_replicates_207",
                    "gold_status": "mechanical",
                    "synthetic": "cross_cue_pair",
                    "stats": dict(st),
                }
                if self._push(case):
                    made += 1
                    self.trace["no_anchor_synth"] += 1
                    break                   # 每 zh 行 1 条，保证多样性
        return made

    # -------------------------------------------------- T3 假候选

    def build_t3(self, hits):
        """T3：音乐/通用词假候选，金标=uncertain（Jev 应拒绝裁决）。

        音乐：ak 模式真实多目标音乐表面形（曲目条目与其《》变体）× 不含两形
        的真实 zh 行；通用词：真实 zh/ref 行 + 显式通用词候选集（合成探针）。
        """
        made = 0
        # (a) 音乐假候选（真实表面形驱动）
        music_pool = []
        for group, path in iter_sources():
            try:
                cues = parse_bilingual_cues(path)
            except OSError:
                continue
            rel = os.path.relpath(path, ROOT).replace("\\", "/")
            M = self.maps_for("ak")
            for num, zh, ref, ctx in cues:
                if not (MIN_ZH <= len(zh) <= MAX_ZH) or len(ref) > 800:
                    continue
                anchor = _ref_for_match(ref)
                if not anchor:
                    continue
                ref_ms = longest_bounded(M["ref_auto"], anchor.lower())
                for s0, e0, sf, tg in ref_ms:
                    if len(tg) >= 2 and _is_music(set(tg)):
                        zh_targets = set()
                        for _a, _b, _sf, t2 in longest_bounded(M["zh_auto"], zh):
                            zh_targets |= set(t2)
                        if set(tg) & zh_targets:
                            continue          # zh 已含音乐候选形 → 非 no_anchor
                        music_pool.append((rel, num, zh, ref, ctx, sorted(set(tg)), sf))
                        break
        made_music = 0
        for rel, num, zh, ref, ctx, T, sf in music_pool:
            if made_music >= self.t3_target // 2:
                break
            if self.per_file[rel] >= self.max_per_file:
                continue
            case = {
                "tier": "T3", "label": "negative", "mode": "ak",
                "zh": zh, "ref": ref, "T": T, "gold": UNCERTAIN,
                "source": rel, "cue": num, "surface": sf, "ctx": ctx,
                "pair": "neg_false_candidate",
                "gold_source": "music_false_candidate",
                "gold_status": "mechanical", "synthetic": "cross_cue_pair",
                "stats": {},
            }
            if self._push(case):
                made_music += 1
                self.trace["t3_music"] += 1
        # (b) 通用词假候选（合成探针：显式候选集；zh 行不含这些候选形）
        generic_sets = [["游戏", "直播"], ["角色", "立绘"], ["游戏", "角色"]]
        zh_no_generic = []
        for group, path in iter_sources():
            try:
                cues = parse_bilingual_cues(path)
            except OSError:
                continue
            rel = os.path.relpath(path, ROOT).replace("\\", "/")
            for num, zh, ref, ctx in cues:
                if not (MIN_ZH <= len(zh) <= MAX_ZH) or len(ref) > 800:
                    continue
                if any(g in zh for gset in generic_sets for g in gset):
                    continue
                zh_no_generic.append((rel, num, zh, ref, ctx))
        made_gen = 0
        i = 0
        for rel, num, zh, ref, ctx in zh_no_generic:
            if made_gen >= self.t3_target - made_music:
                break
            if self.per_file[rel] >= self.max_per_file:
                continue
            gset = generic_sets[i % len(generic_sets)]
            i += 1
            case = {
                "tier": "T3", "label": "negative", "mode": "bi",
                "zh": zh, "ref": ref, "T": list(gset), "gold": UNCERTAIN,
                "source": rel, "cue": num, "surface": "", "ctx": ctx,
                "pair": "neg_false_candidate",
                "gold_source": "generic_false_candidates",
                "gold_status": "mechanical",
                "synthetic": "generic_candidates_declared",
                "stats": {},
            }
            if self._push(case):
                made_gen += 1
                self.trace["t3_generic"] += 1
        return made_music + made_gen

    # -------------------------------------------------- 汇总

    def _count_pos(self):
        return sum(1 for c in self.cases if c["label"] == "positive")

    def _count_neg(self):
        return sum(1 for c in self.cases if c["label"] == "negative")

    def finalize(self, mining, extra):
        for i, case in enumerate(self.cases, 1):
            case["id"] = "jevm-%04d" % i
            case["split"] = _split(case["id"] + "|" + case["zh"])
        self._assert_no_calib_pollution()
        by_tier = Counter(c["tier"] for c in self.cases)
        by_label = Counter(c["label"] for c in self.cases)
        by_pair = Counter(c.get("pair") or
                          ("positive_%s" % ("synthetic" if c["synthetic"] else "natural")
                           if c["label"] == "positive" else c["label"])
                          for c in self.cases)
        by_split = Counter(c["split"] for c in self.cases)
        by_mode = Counter(c["mode"] for c in self.cases)
        summary = {
            "schema": SCHEMA,
            "generated_from": {
                "G1": "outbox/*.srt（人工复审发布稿，排除 *.calib.srt）",
                "G2": "data/pipeline_work/*.zh.srt（原译，非 .calib 产物）",
                "G3": "真实文本跨 cue 配对/错形换目标（全部打 synthetic 标记）",
            },
            "mining_full_corpus": dict(mining),
            "mining_notes": {
                "modes": ["bi", "ak"],
                "noise_gold_excluded": sorted(NOISE_GOLD),
                "noise_reason": "单字金标（如「心」）会被 AC 自动机在任意词语中命中，作为 dis=True 金标产生假正例，T1 不收",
            },
            "cases": len(self.cases),
            "by_tier": dict(by_tier),
            "by_label": dict(by_label),
            "by_pair": dict(by_pair),
            "by_split": dict(by_split),
            "by_mode": dict(by_mode),
            "by_gold_source": dict(Counter(c["gold_source"] for c in self.cases)),
            "positive_negative_ratio": (
                "%d:%d" % (self._count_pos(), self._count_neg())
                if self._count_neg() else "n/a"),
            "calib_pollution_assert": "passed",
            "acceptance": extra,
            "build_trace": dict(self.trace),
        }
        return summary

    def _assert_no_calib_pollution(self):
        """金标污染断言：任何来源字段都不得指向 .calib.srt。"""
        for c in self.cases:
            for k in ("source", "ref_source"):
                v = c.get(k) or ""
                if v.endswith(".calib.srt") or ".calib.srt" in os.path.basename(v):
                    raise AssertionError(
                        "金标污染：case %s 的 %s 指向校准产物 %s" % (c.get("id"), k, v))


def _split(key):
    """20% eval，稳定可复现（与 build_jev_calib_dataset 同口径）。"""
    return "eval" if int(hashlib.sha1(key.encode("utf-8")).hexdigest(), 16) % 5 == 0 \
        else "train"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="构建 Jev mention 消歧评测集")
    ap.add_argument("--out", default="data/entities/jev_mention_cases.jsonl")
    ap.add_argument("--summary", default="data/entities/jev_mention_summary.json")
    ap.add_argument("--checklist", default="data/entities/jev_mention_t2_checklist.json")
    ap.add_argument("--t1-target", type=int, default=140)
    ap.add_argument("--t2-target", type=int, default=48)
    ap.add_argument("--t3-target", type=int, default=32)
    ap.add_argument("--max-per-file", type=int, default=28)
    args = ap.parse_args(argv)

    print("全量扫描 pipeline_work + outbox …")
    mining, hits = mine_corpus(modes=("bi", "ak"))
    print(json.dumps(dict(mining), ensure_ascii=False))

    b = DatasetBuilder(t1_target=args.t1_target, t2_target=args.t2_target,
                       t3_target=args.t3_target, max_per_file=args.max_per_file)
    n1n = b.build_t1_natural(hits)
    print("T1 天然正例（G1+G2）：%d" % n1n)
    n1s = 0
    if n1n < 80:                                   # 天然 <80 才允许合成补足
        n1s = b.build_t1_synthetic(hits)
        print("T1 合成补足：%d" % n1s)
    n_wp = b.build_wrong_pick()
    print("硬负例 wrong_pick：%d" % n_wp)
    n_t2, n_na, t2_avail, na_avail = b.build_t2_and_no_anchor(hits)
    print("T2 待人工金标：%d（可用 %d）；no_anchor：%d（可用 %d）"
          % (n_t2, t2_avail, n_na, na_avail))
    n_t3 = b.build_t3(hits)
    print("T3 假候选：%d" % n_t3)

    # 验收核算
    t1 = sum(1 for c in b.cases if c["tier"] == "T1" and c["label"] == "positive")
    extra = {
        "T1_positive": t1, "T1_require": ">=120",
        "T1_natural": n1n, "T1_synthetic_used": n1s,
        "T1_synthetic_allowed": "yes (natural %d < 80)" % n1n if n1n < 80 else "no",
        "T1_pass": t1 >= 120,
        "T2_pending_human": n_t2, "T2_require": ">=40（人工金标清单已产出，金标待人工）",
        "T2_pass": n_t2 >= 40,
        "T3_false_candidates": n_t3, "T3_require": ">=30",
        "T3_pass": n_t3 >= 30,
        "T2_all_human_gold": False,
        "T2_all_human_gold_note": "本次无人工标注通道：T2 全部 gold_status=pending_human，"
                                  "清单含上下文与证据卡待人工确认；金标确认前不参与放行判定",
    }
    summary = b.finalize(mining, extra)

    out_path = os.path.join(ROOT, args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        for case in b.cases:
            f.write(json.dumps(case, ensure_ascii=False) + "\n")
    with open(os.path.join(ROOT, args.summary), "w", encoding="utf-8",
              newline="\n") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
        f.write("\n")

    # T2 人工标注清单（仅 pending_human 条目；no_anchor 负例金标机械确定，无需标注）
    from features.calibrate.calib_mention_decision import build_mention_evidence
    checklist = []
    for c in b.cases:
        if c["tier"] != "T2" or c.get("gold_status") != "pending_human":
            continue
        record = {"kind": "tb_fail", "zh": c["zh"], "ref": c["ref"], "T": c["T"]}
        checklist.append({
            "id": c["id"], "zh": c["zh"], "ref": c["ref"], "T": c["T"],
            "source": c["source"], "cue": c["cue"],
            "context": c.get("ctx") or {},
            "evidence": build_mention_evidence(record).get("text", ""),
            "suggested_gold": c.get("suggested_gold", ""),
            "gold_status": "pending_human",
            "annotate": {"gold": "", "annotator": "", "rationale": ""},
        })
    cl_path = os.path.join(ROOT, args.checklist)
    with open(cl_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"schema": "jev-mention-t2-checklist/1",
                   "usage": "人工逐条确认 gold（T 内候选或 UNCERTAIN=无法判定）；"
                            "确认后回填 annotate.gold 并把 cases.jsonl 对应条目 "
                            "gold_status 改为 human_confirmed",
                   "items": checklist}, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(json.dumps({k: v for k, v in summary.items()
                      if k in ("cases", "by_tier", "by_label", "by_pair",
                               "positive_negative_ratio", "calib_pollution_assert",
                               "acceptance")}, ensure_ascii=False, indent=2))
    print("评测集：%s" % out_path)
    print("T2 人工标注清单：%s" % cl_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
