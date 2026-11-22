# @version 3.2.5
"""未登录对象候选闭环（M3-6）：``candidates`` 子命令实现。

定位 = audit 扫 3 family_gap 的**对象级解释层**：给每条 gap 产出 ref 单目标候选，
并把 mention 层的 unresolved_proper 并入同一清单（M3-1 原型 §5.4「单独产物」落 地）。
精度目标 ≥80%（M3-1 实测 7-10 真 / 41 净候选基线，见 data/tmp/m3_mention_proto_report.md）。

铁律（任务 M3-6）：
  * 候选**只进人工复核清单 / 学习库候选，绝不自动改写字幕**——本模块对任何 srt 只读，
    全部产物（侧车 JSON / adopt 裁决表 / Entity 桩）都必须经人工裁决后走既有 adopt /
    learned-promote 回路才可能生效（cue281 型 lily 大小写丢失只人工）。
  * 不破坏既有 adopt/learn 回路：本模块不改 adopt.py/learn.py/kb.py/mention.py，
    裁决表按 adopt.parse_report 第四节格式输出，**零改动可消费**。

数据流（单一入口 :func:`collect`）::

    MentionPairer(mode).pair(zh, ref)      -> unresolved_proper（对象级漏译候选，cue 级）
    kb 扫 3（与 kb._cmd_audit 同口径）     -> family_gap（锚点命中但官方名未译）
    合流 + 按 (mode, surface) 去重         -> 侧车 / adopt 兼容裁决表 / Entity 桩

固化双路径（文档，:func:`render_stubs`）：
  A. ref 单目标锚点 + zh 同形残留 + 非 human_only
       -> ``Entity(canonical, ctx=((锚正则, 错形),))`` 桩（照 learn.py learned-promote
          :388-400 格式），人工审阅后粘贴进 ENTITIES。
  B. 纯拉丁缩写、无中文目标（多目标挂起 / 命中 kb._AUDIT_LATIN_OK 白名单语义）
       -> 登记「保留英文」裁决进 family_gap 待办（侧车 ``latin_keep`` + 桩段注释），
          不强行改写、**不进 adopt 裁决表**（防 adopt --apply 把「保留英文」当目标替换）。

安全过滤：
  * _is_music/_is_generic（曲目/音乐人/游戏/直播/角色/立绘）：pair_cue 层已剔除
    unresolved_proper；family_gap 合流时二次剔除（双保险）。
  * cue281 型（大小写信号丢失 / 通用词假阳性）标 ``human_only=True``，绝不自动：
    - surface 在 ref 原文仅以全小写词形出现（专名形态缺失，M3-1 报告 §3.4）；
    - surface 命中 kb._AUDIT_STOP 常用英文词表（kb.py:107）；
    - targets 多目标（挂起不盲裁，M3-1 报告 §3.1 cue101 型）。
"""
from __future__ import annotations

import datetime
import re

from calib_core import kb as kb_mod
from calib_core.mention import MentionPairer, _is_generic, _is_music

#: 侧车 schema 版本（字段集变更必须升版本）
SCHEMA = "calib-entity-unresolved/1"

#: adopt 裁决表第四节标题（必须被 adopt.parse_report 的 _SECTION4 正则命中）
_ADJ_SECTION = "## 四、官方中文核对"

#: evidence 聚合上限（防一条多 cue 候选把侧车撑爆；其余以「另有 N 条」汇总）
_EVIDENCE_CAP = 5

_WORD_BOUND = r"(?<![A-Za-z0-9])"
_WORD_TAIL = r"(?![A-Za-z0-9])"


def _flatten(s: str) -> str:
    """evidence/表格安全化：竖线与换行压掉（防破坏 adopt 表列分隔与单行语义）。"""
    return re.sub(r"\s+", " ", str(s or "")).replace("|", "／").strip()


def _latin_surface(surface: str) -> bool:
    """surface 是否纯拉丁词/缩写（允许 ' - . 内部连接符；空格分词）。"""
    s = (surface or "").strip()
    return bool(s) and s.isascii() and all(
        ch.isalpha() or ch in " '-." for ch in s)


def _ref_display_form(surface: str, ref: str) -> str:
    """surface 在 ref 原文中的实际词形（大小写敏感词边界搜索；搜不到回退 surface）。"""
    if not ref:
        return surface
    m = re.search(_WORD_BOUND + re.escape(surface) + _WORD_TAIL, ref)
    return m.group(0) if m else surface


def _case_signal_lost(surface: str, ref: str) -> bool:
    """cue281 型信号：surface 在 ref 原文**仅以全小写词形出现**（大小写信号丢失）。

    M3-1 报告 §3.4：ref=`a field of lily purple cloud.` 的 lily（莉莉 vs 百合花）
    上游全小写已丢失专名信号，mention 层无法自动排除 -> 只能人工。
    仅对含拉丁字母的 surface 生效——谚文/假名/汉字无大小写概念，不适用本信号。
    """
    if not ref or not any(ch.isalpha() and ch.isascii() for ch in surface):
        return False
    hits = [m.group(0) for m in
            re.finditer(_WORD_BOUND + re.escape(surface) + _WORD_TAIL, ref)]
    if not hits:
        return False                       # 原文词形与归一键不同（如首字母大写）→ 有信号
    return all(h == h.lower() for h in hits)


def _zh_residual_form(surface: str, zh: str) -> str:
    """zh 行中 surface 的同形残留实际形态（ctx 替换大小写敏感，必须逐字节同形）。"""
    m = re.search(re.escape(surface), zh, re.I)
    return m.group(0) if m else ""


def collect(mode: str, src: str, window: int = 1) -> dict:
    """跑一条片源：unresolved_proper + family_gap 合流、去重、安全过滤。

    返回可 json.dumps 的 dict（侧车骨架）；绝不写任何文件、绝不改写 srt。
    扫 3 与 ``calib_core audit --window N`` 同口径（复用 kb._audit_mode_scope /
    kb._audit_build_alt / zh_around 语义），保证 family_gap 数字可对账 baseline。
    """
    layout, cues = kb_mod._iter_cue_triples(src)
    pairer = MentionPairer(mode)
    wrong2right, anchor_pairs = kb_mod._audit_mode_scope(mode)
    arx, aidx = kb_mod._audit_build_alt(anchor_pairs)

    # ---- audit 扫 3 口径复刻（kb.py:310-357，含 window zh_around）----
    order = sorted(n for n, _z, _r in cues)
    pos = {n: k for k, n in enumerate(order)}
    zmap = {n: z for n, z, _r in cues}

    def zh_around(n, zh):
        if window <= 0:
            return zh
        k = pos[n]
        return " ".join(zmap[m] for m in order[max(0, k - window):k + window + 1])

    proper_rows = []        # (num, surface_ref_form, targets, zh, ref)
    gap_rows = []           # (num, anchor_lit, canon, zh, ref)
    st = dict(cues=len(cues), ref_mentions=0, unresolved=0, unresolved_proper=0,
              family_gap=0)
    for num, zh, ref in cues:
        if ref:
            pair = pairer.pair(zh, ref)
            st["ref_mentions"] += len(pair["ref_ms"])
            st["unresolved"] += len(pair["unresolved"])
            for _i, rs, rt in pair["unresolved_proper"]:
                st["unresolved_proper"] += 1
                proper_rows.append((num, _ref_display_form(rs, ref), list(rt),
                                    zh, ref))
        # ---- 扫 3（仅 ref 行为外文时有效；audit 同款）----
        zhw = zh_around(num, zh)
        ref_targets = {}
        if ref and arx is not None:
            for m in arx.finditer(ref):
                grp = aidx[m.group(0)]
                if any(c in zhw for c in grp):
                    continue                          # 官方名已在（含邻 cue）→ 已译
                for canon in grp:
                    ref_targets.setdefault(canon, m.group(0))
        for canon, lit in ref_targets.items():
            if canon and canon not in zhw:
                if _is_music({canon}) or _is_generic({canon}):
                    continue                          # 音乐/通用词：无消歧价值，剔除
                st["family_gap"] += 1
                gap_rows.append((num, lit, canon, zh, ref))

    # ---- 合流去重：键 (mode, surface.lower())；unresolved_proper 优先 ----
    merged = {}
    for num, surf, targets, zh, ref in proper_rows:
        ent = merged.setdefault(surf.lower(), {
            "surface": surf, "targets": [], "sources": [],
            "hits": [], "official": ""})
        ent["targets"] = list(dict.fromkeys(ent["targets"] + list(targets)))
        if "unresolved_proper" not in ent["sources"]:
            ent["sources"].insert(0, "unresolved_proper")
        ent["hits"].append((num, zh, ref))
    for num, lit, canon, zh, ref in gap_rows:
        ent = merged.setdefault(lit.lower(), {
            "surface": lit, "targets": [], "sources": [],
            "hits": [], "official": ""})
        if canon and canon not in ent["targets"]:
            ent["targets"].append(canon)
        if not ent["official"]:
            ent["official"] = canon
        if "family_gap" not in ent["sources"]:
            ent["sources"].append("family_gap")
        if not any(h[0] == num for h in ent["hits"]):
            ent["hits"].append((num, zh, ref))    # 同 cue 多 canon 只记一次佐证

    candidates = []
    latin_keep = []
    for key in sorted(merged):
        ent = merged[key]
        surf = ent["surface"]
        targets = ent["targets"]
        sources = sorted(set(ent["sources"]),
                         key=lambda s: (s != "unresolved_proper", s))
        hits = ent["hits"]
        notes, human_only = [], False

        if len(targets) > 1:
            human_only = True
            notes.append("多目标挂起（%s）" % "、".join(targets))
        if key in kb_mod._AUDIT_STOP:
            human_only = True
            notes.append("常用英文词假阳性（_AUDIT_STOP）")
        lost = any(_case_signal_lost(surf, ref) for _n, _z, ref in hits)
        if lost:
            human_only = True
            notes.append("大小写信号丢失（cue281 型：ref 仅全小写词形）")

        # ---- 固化路径判定 ----
        verdict = "human-review"
        zh_form = ""
        ref_form = _ref_display_form(surf, hits[0][2])
        for num, z, _ref in hits:                 # 任一 cue 有同形残留即可作错形候选
            zh_form = _zh_residual_form(surf, z)
            if zh_form:
                break
        latin = _latin_surface(surf)
        if latin and (len(targets) > 1
                      or kb_mod._AUDIT_LATIN_OK.match(surf) is not None
                      or not zh_form):
            verdict = "keep-latin"
            latin_keep.append({
                "surface": surf, "targets": targets, "source": sources[0],
                "note": ("多目标挂起" if len(targets) > 1
                         else ("_AUDIT_LATIN_OK 白名单语义" if
                               kb_mod._AUDIT_LATIN_OK.match(surf) is not None
                               else "zh 行无同形残留，改无可改"))
                        + "；登记「保留英文」待办，不建替换键、不进 adopt 表",
            })
            if not notes:
                notes.append("纯拉丁无中文目标：保留英文（不强行改写）")
        elif (len(targets) == 1 and not human_only and zh_form
              and not kb_mod._AUDIT_LATIN_OK.match(surf)):
            verdict = "stub-eligible"

        evid = []
        seen_cues = set()
        for num, z, ref in hits:
            if num in seen_cues:
                continue                     # 同 cue 多 canon/多位置只记一次佐证
            seen_cues.add(num)
            if len(evid) < _EVIDENCE_CAP:
                evid.append("cue %s ref「%s」zh「%s」"
                            % (num, _flatten(ref) or "-", _flatten(z) or "-"))
        n_cues = len(seen_cues)
        if n_cues > _EVIDENCE_CAP:
            evid.append("…另有 %d 条" % (n_cues - _EVIDENCE_CAP))
        if sources[0] == "unresolved_proper" and len(sources) > 1:
            notes.append("与 audit family_gap 重合（双源互证）")

        candidates.append({
            "cue": int(hits[0][0]),
            "zh": hits[0][1],
            "ref": hits[0][2],
            "surface": surf,
            "targets": targets,
            "source": sources[0],
            "evidence": "；".join(evid),
            "official": ent["official"],
            "confidence": "",                     # 人工/子模型填写（高/中）
            "human_only": human_only,
            "verdict": verdict,
            "cues": [int(n) for n in dict.fromkeys(h[0] for h in hits)],
            "sources": sources,
            "ref_form": ref_form,
            "zh_form": zh_form,
            "note": "；".join(notes) + (
                "；命中 %d cue" % n_cues if n_cues > 1 else ""),
        })

    st["dedup_from"] = st["unresolved_proper"] + st["family_gap"]
    st["candidates"] = len(candidates)
    st["human_only"] = sum(1 for c in candidates if c["human_only"])
    st["latin_keep"] = len(latin_keep)
    st["stub_eligible"] = sum(1 for c in candidates if c["verdict"] == "stub-eligible")

    return {
        "schema": SCHEMA,
        "mode": mode,
        "src": src,
        "generated": datetime.datetime.now().isoformat(timespec="seconds"),
        "layout": layout,
        "stats": st,
        "candidates": candidates,
        "latin_keep": latin_keep,
    }


# ---------------------------------------------------------------- adopt 裁决表


def render_adjudication(rep: dict) -> str:
    """输出 adopt.parse_report **零改动可消费**的第四节裁决表。

    表格契约（src/calib_entity/opt/adopt.py:25-63）：
      * 标题行必须命中 ``^##\\s*四[、.]?\\s*官方中文核对``；
      * 4 列：字幕里的写法(wrong) / 官方中文(right) / 把握(confidence) / 依据(note)；
      * ``把握=高`` 且 right 非空、不含「待确认/—/?」等不确定标记才被 select 采纳。

    预填策略：targets 恰一且非 human_only → official 预填建议值（把握留空，
    默认 min_conf=高 下全部丢弃 = 零改动）；human_only/多目标/keep-latin → official 留空。
    keep-latin 条目也进表（official 恒空 + 依据注明），保住人工复核线索；
    其「保留英文」登记另见表尾注释与侧车 latin_keep。
    """
    lines = [_ADJ_SECTION, "",
             "<!-- M3-6 candidates 裁决底稿：%s（mode=%s）。official/把握列由人工或"
             "子模型填写；把握=高 且 official 非空才可被 adopt 消费执行。"
             "human_only 行绝不自动改写。 -->" % (rep["src"], rep["mode"]),
             "",
             "| 字幕里的写法 | 官方中文 | 把握 | 依据 |",
             "| --- | --- | --- | --- |"]
    for c in rep["candidates"]:
        if c["verdict"] == "keep-latin":
            official = ""
            note = "[keep-latin 保留英文待办，不自动；%s] %s [%s]" % (
                c["note"] or "-", c["evidence"], c["source"])
        else:
            official = "" if c["human_only"] or len(c["targets"]) != 1 \
                else c["targets"][0]
            note = "%s [%s] %s" % (c["evidence"], c["source"],
                                   c["note"] or ("-human" if c["human_only"] else ""))
        lines.append("| %s | %s | %s | %s |" % (
            _flatten(c["surface"]), _flatten(official), _flatten(c["confidence"]),
            _flatten(note)))
    if rep.get("latin_keep"):
        lines.append("")
        lines.append("<!-- 保留英文待办（上表对应行 official 恒空、把握未填前绝不生效；"
                     "防 adopt --apply 误替换）："
                     + "；".join("[%s] %s" % (k["surface"], k["note"])
                                 for k in rep["latin_keep"]) + " -->")
    return "\n".join(lines)


# ---------------------------------------------------------------- Entity 桩（固化路径 A/B）


def render_stubs(rep: dict, mode: str | None = None) -> str:
    """输出固化双路径的 Python 片段（照 learn.py learned-promote :388-400 格式）。

    路径 A：ref 单目标锚点 + zh 同形残留 + 非 human_only → Entity(canonical, ctx=...)
      * canonical = targets[0]（ref 单目标才有唯一官方中文名）；
      * ctx 锚正则 = ``\\b<ref 原文锚词>\\b``（bi/ak 模式 ctx 按 re.I 编译，与引擎一致）；
      * ctx 错形 = zh 行残留的**逐字节实际形态**（_ctx_replace 是大小写敏感替换）。
    路径 B：纯拉丁无中文目标 → 注释形式登记「保留英文」进 family_gap 待办。
    """
    mode = mode or rep["mode"]
    stubs = [c for c in rep["candidates"] if c["verdict"] == "stub-eligible"]
    keeps = rep.get("latin_keep") or []
    L = []
    if stubs:
        L.append("# ---- M3-6 candidates 固化桩（人工审阅后并入 ENTITIES；"
                 "ref 单目标锚定 + zh 同形残留）----")
        for c in stubs:
            anchor_rx = r"\b%s\b" % re.escape(c["ref_form"])
            note = ("M3-6 candidates 固化：ref 单目标锚定 surface=%s；证据 %s。"
                    "en/ja/ko/category 待人工补全" % (c["surface"],
                                                     _flatten(c["evidence"])))
            L.append("    Entity(%r, modes=(%r,)," % (c["targets"][0], mode))
            L.append("           variants=(),")
            L.append("           ctx=((%r, %r),)," % (anchor_rx, c["zh_form"]))
            L.append("           note=%r)," % note)
    if keeps:
        if stubs:
            L.append("")
        L.append("# ---- M3-6 family_gap 待办（保留英文登记，_AUDIT_LATIN_OK 白名单语义；"
                 "不建替换键、不进 adopt 表）----")
        for k in keeps:
            L.append("#   [%s] targets=%s：%s"
                     % (k["surface"], "/".join(k["targets"]) or "-", k["note"]))
    if not L:
        L.append("# 无可固化候选（无 ref 单目标锚点 + zh 同形残留的条目）")
    return "\n".join(L)


def render_summary(rep: dict) -> str:
    """非 JSON 输出：摘要 + adopt 裁决表。"""
    st = rep["stats"]
    L = ["未登录对象候选（M3-6）：%s" % rep["src"],
         "  版式 %s | 模式 %s | cue %d" % (rep.get("layout", "?"), rep["mode"],
                                           st["cues"]),
         "  ref mention %d | unresolved %d | unresolved_proper %d | family_gap %d"
         % (st["ref_mentions"], st["unresolved"], st["unresolved_proper"],
            st["family_gap"]),
         "  合流去重 %d -> %d 条候选（human_only %d / 保留英文 %d / 可固化桩 %d）"
         % (st["dedup_from"], st["candidates"], st["human_only"],
            st["latin_keep"], st["stub_eligible"]),
         "",
         render_adjudication(rep)]
    return "\n".join(L)
