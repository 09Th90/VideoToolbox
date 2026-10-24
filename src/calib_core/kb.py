# -*- coding: utf-8 -*-
# @version 2.7.0
"""对象级知识库 audit/export/lookup/lint

源：subtitle_calib_merged.py L10668-L11184 @ 97d7d463（2026-10-24 冻结快照）
"""
import io
import os
import re
import shutil
import sys
import unicodedata
from .data.bilingual import EXCLUDE_CONTEXT
from .data.entities import ENTITIES
from .data.modes import _MODE_CTX_TABLE, _MODE_NAMES, _MODE_TERM_TABLE
from .state import CTX_TABLES, TABLES
from .srt import _detect_layout
from .text import _decode_any



def _kb_view():
    """把 扁平表 + ENTITIES 折叠成对象级视图：{canonical: dict}。

    同一 canonical 跨表/跨模式的全部变体、条件规则、负向排除聚合为一个对象；
    ENTITIES 的 en/ja/ko/category/note 元数据覆盖进对应对象。"""
    kb = {}

    def ent(c):
        return kb.setdefault(c, {
            "canonical": c, "en": "", "ja": "", "ko": "",
            "category": "", "modes": [], "variants": [],
            "ctx": [], "exclude": [], "note": ""})

    for mode, tname in _MODE_TERM_TABLE.items():
        for wrong, right in (TABLES.get(tname) or {}).items():
            e = ent(right)
            if mode not in e["modes"]:
                e["modes"].append(mode)
            if wrong not in e["variants"]:
                e["variants"].append(wrong)
    # EN_LINE_TERM_FIXES 修正的是外文行（目标非中文官方名），单独挂 fix-en 模式
    for wrong, right in (TABLES.get("EN_LINE_TERM_FIXES") or {}).items():
        e = ent(right)
        if "fix-en" not in e["modes"]:
            e["modes"].append("fix-en")
        if wrong not in e["variants"]:
            e["variants"].append(wrong)
    for mode, cname in _MODE_CTX_TABLE.items():
        for rx, wrong, right in (CTX_TABLES.get(cname) or []):
            if not wrong or not right:
                continue
            e = ent(right)
            if mode not in e["modes"]:
                e["modes"].append(mode)
            if (rx, wrong) not in e["ctx"]:
                e["ctx"].append((rx, wrong))
    for wrong, (right, rxs) in (EXCLUDE_CONTEXT or {}).items():
        e = ent(right)
        if "bi" not in e["modes"]:
            e["modes"].append("bi")
        for rx in rxs:
            if (wrong, rx) not in e["exclude"]:
                e["exclude"].append((wrong, rx))
    for e0 in ENTITIES:
        e = ent(e0.canonical)
        e["en"], e["ja"], e["ko"] = e0.en, e0.ja, e0.ko
        e["category"] = e0.category
        if e0.note:
            e["note"] = (e["note"] + "；" + e0.note) if e["note"] else e0.note
    return kb



#: audit 扫 1 白名单：中文行里出现这些拉丁串属正常（抽卡分级术语、中文语境通用外来词），
#: 不算「未翻译残留」；其余一律进候选交人工裁决。
_AUDIT_LATIN_OK = re.compile(
    r"^(?:"
    r"[A-FS]\+?|S\d+(?:\s*R\d+)?|SR\d+(?:\s*R\d+)?|SSS|SSR|EX|UR|"
    r"YouTube|YouTuber|VOD|Xbox|NPC|MVP|PNG|JPG|DNA|OK|PC|PS5|HP|DPS|UI|AI|"
    r"bug|Boss|Incel|Discord|Gacha|gacha|NTE"
    r")$", re.I)


#: 从 ctx 参考行正则里抠「纯外文字面量」时要剥掉的正则噪声。
_AUDIT_RX_NOISE = re.compile(
    r"\\[bBsSdDwWzZ]|\(\?:|\(\?!|\(\?=|[\r\n\t()\[\]{}+*?^$|.\\:]")

#: 常见英文虚词/普通词：从正则里抠出来也绝不作为锚点，避免扫 3 噪声。
_AUDIT_STOP = {
    "the", "and", "for", "are", "was", "were", "with", "that", "this", "you",
    "your", "his", "her", "its", "they", "them", "she", "him", "not", "but",
    "all", "any", "can", "will", "would", "could", "should", "have", "has",
    "had", "from", "into", "over", "out", "one", "two", "way", "ways", "wave",
    "waves", "thing", "things", "stuff", "people", "man", "men", "woman",
    "girl", "boy", "time", "day", "life", "world", "game", "story", "good",
    "bad", "big", "new", "old", "more", "most", "much", "many", "some",
    "only", "just", "like", "love", "hate", "want", "need", "get", "got",
    "going", "come", "came", "see", "look", "know", "think", "say", "said",
    "tell", "make", "made", "take", "give", "find", "feel", "keep", "let",
    "put", "turn", "play", "work", "call", "ask", "try", "use", "move",
    "live", "right", "left", "same", "other", "another", "there", "here",
    "what", "when", "where", "why", "how", "who", "because", "about",
    "after", "before", "again", "still", "even", "very", "really", "back",
    "first", "last", "next", "name", "part", "side", "hand", "head", "end",
    "now", "then", "than", "too", "also", "being", "been", "does", "did",
    "space", "character", "release", "beginning", "norm", "pull", "anger",
    "able", "poor", "little", "ions", "sick", "aura", "shin", "meth",
    "line", "form", "type", "kind", "sort", "case", "point", "place",
    "team", "group", "level", "order", "power", "light", "dark", "fire",
    "water", "earth", "wind", "sound", "voice", "song", "music", "art",
    "meta", "plot", "start", "main", "nothing", "eggs", "creep", "well",
    "chosen", "telling", "maintain", "gameplay", "setting", "legend",
    "moon", "war", "sun", "star", "sky", "sea", "land", "king", "queen",
    "lord", "lady", "god", "angel", "demon", "dragon", "tiger", "wolf",
    "guardian", "guard", "solar", "solaris", "festival", "lang", "alto",
}



def _iter_cue_triples(src):
    """SRT → (版式, [(序号, 中文行, 参考行)])；mono 版式的参考行为空串。"""
    raw = open(src, "rb").read()
    norm = _decode_any(raw).replace("\r\n", "\n").replace("\r", "\n")
    lines = norm.split("\n")
    layout = _detect_layout(lines)
    out, i, n = [], 0, len(lines)
    while i < n:
        s = lines[i].strip()
        if s.isdigit() and (i == 0 or lines[i - 1].strip() == ""):
            j = i + 1
            if j < n and "-->" in lines[j]:
                kk = j + 1
                while kk < n and lines[kk].strip() != "":
                    kk += 1
                texts = lines[j + 1:kk]
                if texts:
                    if layout == "mono":
                        out.append((s, "\n".join(texts), ""))
                    else:
                        zh = "\n".join(texts[:-1]) if len(texts) > 1 else texts[0]
                        out.append((s, zh, texts[-1]))
                i = kk
                continue
        i += 1
    return layout, out



def _audit_names(en, ja, ko):
    """官方外文名（en/ja/ko）拆成可锚定片段（≥3 字符、纯外文）。"""
    pool = []
    for nm in (en, ja, ko):
        if not nm:
            continue
        for part in re.split(r"[/,;]", nm):
            part = part.strip()
            if len(part) < 3 or not re.match(r"^[A-Za-z][A-Za-z' \-\.]*$", part):
                continue
            pool.append(part)
    return pool



def _audit_ctx_literals(rx, variants_lc=()):
    """把一条 ctx 参考行正则拆成可用于锚定的**专名型**外文字面量。

    例：`\\brover` → rover（"Rover" 是该实体的已知错形）；`Fractus|fracters`
    → Fractus / fracters（首字母大写）。

    ⚠ 只认「像专名」的字面量：首字母大写，或本来就是该实体 variants 里的错形。
    否则 bi 模式那张跨片源共用的 CONTEXT_MAP 会把 gameplay / plot / nothing /
    start 这类常用词锚点全带进来，实测扫 3 从 ~60 条虚高到 986 条。
    """
    out = []
    for part in str(rx).split("|"):
        s = _AUDIT_RX_NOISE.sub(" ", part)
        for tok in s.split():
            t = tok.strip("'\"-")
            if len(t) < 3 or not re.match(r"^[A-Za-z][A-Za-z'\-]*$", t):
                continue
            low = t.lower()
            if low in _AUDIT_STOP:
                continue
            if not (t[0].isupper() or low in variants_lc):
                continue
            out.append(t)
    return out



def _audit_mode_scope(mode):
    """按模式取「生效的」错形表与参考行锚点。

    ⚠ 必须**按模式**取：`_kb_view()` 会把各模式的 ctx/变体合并成一个对象，
    直接拿来扫会把别的片源的规则（如某模式的 space→虚质空间）当成漏校。
    返回 (错形→官方名 字典, [(锚点字面量, 官方名)])。
    """
    wrong2right = {}
    anchors = []
    variants_lc = {}          # canonical -> {小写变体}，用于判定 ctx 字面量像不像专名
    ctx_by_canon = {}         # canonical -> [参考行正则]

    def _reg_variant(canon, w):
        if w:
            variants_lc.setdefault(canon, set()).add(str(w).lower())

    # ---- 第一遍：错形表 + 变体 + 外文名锚点 ----
    tname = _MODE_TERM_TABLE.get(mode)
    for wrong, right in (TABLES.get(tname) or {}).items():
        if wrong and right and wrong != right:
            wrong2right.setdefault(wrong, right)
            _reg_variant(right, wrong)
    for e in ENTITIES:
        if mode and mode not in e.modes:
            continue
        for w in e.variants:
            if w and w != e.canonical:
                wrong2right.setdefault(w, e.canonical)
                _reg_variant(e.canonical, w)
        for rx, w in e.ctx:
            if w:
                wrong2right.setdefault(w, e.canonical)
            ctx_by_canon.setdefault(e.canonical, []).append(rx)
        for nm in _audit_names(e.en, e.ja, e.ko):
            anchors.append((nm, e.canonical))

    # ---- 第二遍：ctx 参考行锚点（需先知道该实体的变体集合）----
    cname = _MODE_CTX_TABLE.get(mode)
    for item in (CTX_TABLES.get(cname) or []):
        rx, wrong, right = (list(item) + [None, None])[:3]
        if not right:
            continue
        if wrong:
            wrong2right.setdefault(wrong, right)
            _reg_variant(right, wrong)
        ctx_by_canon.setdefault(right, []).append(rx)
    for canon, rxs in ctx_by_canon.items():
        vl = variants_lc.get(canon, set())
        for rx in rxs:
            for lit in _audit_ctx_literals(rx, vl):
                anchors.append((lit, canon))
    return wrong2right, anchors



def _audit_build_alt(pairs, boundary=True):
    """[(匹配串, 载荷)] → 一次性交替正则（长键优先）+ 索引。

    boundary=True 时整体加拉丁词边界：锚点全是纯外文串，不加边界会把
    「Shin」命中到「China」这类子串上，凭空多出噪声。
    """
    idx = {}
    for key, payload in pairs:
        idx.setdefault(key, []).append(payload)
    keys = sorted(idx, key=len, reverse=True)
    if not keys:
        return None, idx
    body = "|".join(re.escape(k) for k in keys)
    rx = re.compile((r"(?<![A-Za-z0-9])(?:" + body + r")(?![A-Za-z0-9])")
                    if boundary else body)
    return rx, idx



def _cmd_audit(src, mode="bi", out=None, as_json=False, limit=300, loose=False):
    """audit：校准后成品的「名词漏校三扫」（机械遍 / AI 校准之后的收口体检）。

    扫 1  拉丁残留      —— 中文行里白名单外的英文/罗马字（分级字母、通用外来词不计）。
    扫 2  错形残留      —— 本模式生效的「无条件变体 / ctx 条件错形」命中中文行、
                           官方名却不在该行；且参考行佐证该实体（命中专名型锚点）。
                           这类可直接采纳。`--loose` 追加「无佐证」的低置信项
                           （错形表里混有常用词作锚点，噪声大，必须人工过筛）。
    扫 3  同词族一致性  —— 参考行命中锚点、中文行却没有对应官方名。反向核查查不出这类
                           （每种错形都不是「官方名缺失」），是漏校的主力来源。

    退出码：1＝有候选（可当门禁），0＝干净。
    """
    if not os.path.isfile(src):
        print(f"文件不存在：{src}")
        return 1
    layout, cues = _iter_cue_triples(src)
    wrong2right, anchor_pairs = _audit_mode_scope(mode)

    # ---- 扫 1：拉丁残留 ----
    s1 = []
    for num, zh, _ref in cues:
        bad = [t for t in re.findall(r"[A-Za-z][A-Za-z'\-\.]*", zh)
               if not _AUDIT_LATIN_OK.match(t)]
        if bad:
            s1.append((num, zh, "、".join(dict.fromkeys(bad))))

    # 参考行锚点 → 本 cue 应出现的官方名（一次正则；供扫 2 定置信、扫 3 找缺口）
    arx, aidx = _audit_build_alt(anchor_pairs)

    # ---- 扫 2 / 扫 3 ----
    wrx, widx = _audit_build_alt(
        [(w, c) for w, c in wrong2right.items() if len(w) >= 2 and w not in c],
        boundary=False)
    s2_hi, s2_lo, s3 = [], [], []
    for num, zh, ref in cues:
        ref_targets = {}
        if ref and arx is not None:
            for m in arx.finditer(ref):
                grp = aidx[m.group(0)]
                # 同一锚点常挂多个官方名（如 Sentinel → 岁主 / 锁暝 / 前任岁主）。
                # 只要其中任意一个已经出现在中文行，就说明这条已校准，全部放过。
                if any(c in zh for c in grp):
                    continue
                for canon in grp:
                    ref_targets.setdefault(canon, m.group(0))
        if wrx is not None:
            for m in wrx.finditer(zh):
                for canon in widx[m.group(0)]:
                    if canon in zh:
                        continue
                    rec = (num, zh, m.group(0), canon)
                    (s2_hi if canon in ref_targets else s2_lo).append(rec)
        for canon, lit in ref_targets.items():
            if canon and canon not in zh:
                s3.append((num, zh, lit, canon))

    dirty = bool(s1 or s2_hi or s3)

    if as_json:
        import json
        print(json.dumps({
            "src": src, "layout": layout, "mode": mode, "cues": len(cues),
            "wrong_forms": len(wrong2right), "anchors": len(set(anchor_pairs)),
            "latin_residue": [{"num": n, "zh": z, "tokens": t} for n, z, t in s1],
            "variant_residue_high": [{"num": n, "zh": z, "wrong": w, "official": c}
                                     for n, z, w, c in s2_hi],
            "variant_residue_low": [{"num": n, "zh": z, "wrong": w, "official": c}
                                    for n, z, w, c in s2_lo],
            "family_gap": [{"num": n, "zh": z, "anchor": lit, "official": c}
                           for n, z, lit, c in s3],
        }, ensure_ascii=False, indent=2))
        return 1 if dirty else 0

    L = [f"名词漏校三扫：{src}",
         f"  版式 {layout} | 模式 {mode} | cue {len(cues)} | "
         f"本模式错形 {len(wrong2right)} 条 / 参考行锚点 {len(set(anchor_pairs))} 条",
         "",
         f"扫 1  拉丁残留              {len(s1)} 处",
         f"扫 2  错形残留（已佐证）    {len(s2_hi)} 处",
         f"扫 2  错形残留（未佐证）    {len(s2_lo)} 处"
         + ("" if loose else "（用 --loose 展开；错形表含常用词锚点，噪声大）"),
         f"扫 3  同词族一致性          {len(s3)} 处",
         ""]
    if s1:
        L.append("【扫 1】中文行白名单外的拉丁串：")
        for num, zh, tok in s1[:limit]:
            L.append(f"  #{num} [{tok}] {zh}")
        if len(s1) > limit:
            L.append(f"  … 另有 {len(s1) - limit} 处")
        L.append("")
    if s2_hi:
        L.append("【扫 2】错形 → 官方名（参考行已佐证，可直接采纳）：")
        for num, zh, w, c in s2_hi[:limit]:
            L.append(f"  #{num} {w} → {c} | {zh}")
        if len(s2_hi) > limit:
            L.append(f"  … 另有 {len(s2_hi) - limit} 处")
        L.append("")
    if loose and s2_lo:
        L.append("【扫 2·未佐证】错形 → 官方名（慎改）：")
        for num, zh, w, c in s2_lo[:limit]:
            L.append(f"  #{num} {w} → {c} | {zh}")
        if len(s2_lo) > limit:
            L.append(f"  … 另有 {len(s2_lo) - limit} 处")
        L.append("")
    if s3:
        L.append("【扫 3】参考行命中锚点、中文行缺官方名：")
        for num, zh, lit, c in s3[:limit]:
            L.append(f"  #{num} [{lit}] 应为「{c}」| {zh}")
        if len(s3) > limit:
            L.append(f"  … 另有 {len(s3) - limit} 处")
        L.append("")
    if not dirty:
        L.append("三扫全过：无高置信漏校候选。")
    text = "\n".join(L)
    if out:
        with open(out, "w", encoding="utf-8", newline="") as f:
            f.write(text + "\n")
        print(f"三扫报告已写入：{out}")
        print("\n".join(text.split("\n")[:9]))
    else:
        print(text)
    return 1 if dirty else 0



def _cmd_kb_export(out=None, as_json=False):
    """kb-export：导出完整对象级知识库（MD 或 JSON），供审阅/投喂 AI 校准。"""
    kb = _kb_view()
    ents = sorted(kb.values(), key=lambda e: (-len(e["variants"]), e["canonical"]))
    if as_json:
        import json
        data = [{
            "canonical": e["canonical"], "en": e["en"], "ja": e["ja"],
            "ko": e["ko"], "category": e["category"],
            "modes": e["modes"], "variants": e["variants"],
            "ctx": [{"ref_regex": rx, "wrong": w} for rx, w in e["ctx"]],
            "exclude": [{"variant": w, "ref_regex": rx} for w, rx in e["exclude"]],
            "note": e["note"],
        } for e in ents]
        text = json.dumps(data, ensure_ascii=False, indent=2)
    else:
        L = ["# 字幕校准对象级知识库（kb-export）",
             "",
             f"实体数：{len(ents)} | 由扁平表折叠 + ENTITIES 元数据合并生成，"
             "变体均为 错形->官方中文名。",
             ""]
        for e in ents:
            names = " / ".join(x for x in
                               (f"EN {e['en']}" if e["en"] else "",
                                f"JA {e['ja']}" if e["ja"] else "",
                                f"KO {e['ko']}" if e["ko"] else "") if x)
            head = f"## {e['canonical']}" + (f"（{names}）" if names else "")
            L.append(head)
            meta = []
            if e["category"]:
                meta.append("类别: " + e["category"])
            meta.append("模式: " + ", ".join(
                f"{m}({_MODE_NAMES.get(m, m)})" for m in e["modes"]))
            L.append("- " + " | ".join(meta))
            if e["variants"]:
                L.append(f"- 变体({len(e['variants'])}): " + "、".join(e["variants"]))
            for rx, w in e["ctx"]:
                L.append(f"- 条件变体: [参考行 /{rx}/] {w} → {e['canonical']}")
            for w, rx in e["exclude"]:
                L.append(f"- 负向排除: {w} 替换后若参考行命中 /{rx}/ 则回滚")
            if e["note"]:
                L.append("- 备注: " + e["note"])
            L.append("")
        text = "\n".join(L)
    if out:
        with open(out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(f"知识库已导出：{out}（实体 {len(ents)} 个）")
    else:
        print(text)



def _cmd_kb_lookup(word):
    """kb-lookup <词>：按 官方名/EN/JA/KO/任意变体 反查实体，列出全部知识。"""
    kb = _kb_view()
    q = word.lower()
    hits = []
    for e in kb.values():
        pool = [e["canonical"], e["en"], e["ja"], e["ko"],
                *e["variants"], *(w for _, w in e["ctx"]),
                *(w for w, _ in e["exclude"])]
        if any(q in str(p).lower() for p in pool if p):
            hits.append(e)
    if not hits:
        print(f"未找到与 {word!r} 相关的实体"); return
    for e in sorted(hits, key=lambda x: x["canonical"]):
        names = " / ".join(x for x in
                           (f"EN {e['en']}" if e["en"] else "",
                            f"JA {e['ja']}" if e["ja"] else "",
                            f"KO {e['ko']}" if e["ko"] else "") if x)
        print(f"◎ {e['canonical']}" + (f"（{names}）" if names else ""))
        if e["category"]:
            print(f"  类别: {e['category']}")
        print("  模式: " + ", ".join(
            f"{m}({_MODE_NAMES.get(m, m)})" for m in e["modes"]))
        if e["variants"]:
            print(f"  变体({len(e['variants'])}): " + "、".join(e["variants"]))
        for rx, w in e["ctx"]:
            print(f"  条件变体: [/{rx}/] {w} → {e['canonical']}")
        for w, rx in e["exclude"]:
            print(f"  负向排除: {w} 命中 /{rx}/ 则回滚")
        if e["note"]:
            print("  备注: " + e["note"])



def _cmd_kb_lint():
    """kb-lint：对象级体检（互补 terms-check 的表内二次命中检查）。

    检查项：
      1. 变体冲突：同一错形在不同实体/模式映射到不同 canonical；
      2. 级联互含（对象级）：同模式内，甲实体的变体是乙实体 canonical 的子串
         （替换到乙的 canonical 后会被甲的变体二次命中）；
      3. 条件变体冗余：ctx 错形同模式下已是无条件变体（佐证永远不会生效）；
      4. ENTITIES 元数据完整性：缺 en/ja/ko/category/note 的对象级提示。"""
    kb = _kb_view()
    problems, infos = [], []

    # 1. 变体冲突（跨实体，含模式标注）
    seen = {}
    for e in kb.values():
        for v in e["variants"]:
            if v == e["canonical"]:
                continue
            if v in seen and seen[v][0] != e["canonical"] \
                    and set(seen[v][1]) & set(e["modes"]):
                problems.append(
                    f"变体冲突: {v!r} -> {seen[v][0]!r}（{seen[v][1]}）与 "
                    f"{e['canonical']!r}（{e['modes']}）")
            else:
                seen.setdefault(v, (e["canonical"], e["modes"]))
    # 2. 级联互含：同模式内 变体 ⊂ 他实体 canonical
    by_mode = {}
    for e in kb.values():
        for m in e["modes"]:
            if m == "fix-en":
                continue
            by_mode.setdefault(m, []).append(e)
    for m, es in by_mode.items():
        for e in es:
            for other in es:
                if other is e or other["canonical"] == e["canonical"]:
                    continue
                if len(e["canonical"]) <= 2:
                    continue
                for v in other["variants"]:
                    if v and v in e["canonical"] and v != e["canonical"]:
                        problems.append(
                            f"级联互含[{m}]: 变体 {v!r}（->{other['canonical']!r}）"
                            f"是 {e['canonical']!r} 的子串，替换后可能二次命中")
    # 3. 条件变体冗余
    for mode, cname in _MODE_CTX_TABLE.items():
        tname = _MODE_TERM_TABLE.get(mode)
        tbl = TABLES.get(tname) or {}
        for rx, wrong, right in (CTX_TABLES.get(cname) or []):
            if wrong and right and tbl.get(wrong) == right:
                infos.append(
                    f"条件冗余[{mode}]: {wrong!r}->{right!r} 已是 {tname} 无条件变体，"
                    f"ctx 规则 /{rx}/ 永不生效")
    # 4. ENTITIES 元数据完整性
    for e0 in ENTITIES:
        miss = [f for f, v in (("en", e0.en), ("category", e0.category),
                               ("note", e0.note)) if not v]
        if miss:
            infos.append(f"ENTITIES 元数据待补: {e0.canonical!r} 缺 {', '.join(miss)}")
    for p in problems:
        print("⚠", p)
    for p in infos:
        print("ℹ", p)
    if not problems and not infos:
        print("KB-LINT OK：无变体冲突/级联互含/条件冗余")
    else:
        print(f"KB-LINT：{len(problems)} 处问题，{len(infos)} 条提示")

