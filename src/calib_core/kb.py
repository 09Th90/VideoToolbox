# -*- coding: utf-8 -*-
# @version 3.3.1
"""对象级知识库 audit/export/lookup/lint

源：subtitle_calib_merged.py L10668-L11184 @ 97d7d463（2026-10-24 冻结快照）
"""
import io
import os
import re
import shutil
import sys
import unicodedata
from .data.bilingual import BILINGUAL_TERMS, EXCLUDE_CONTEXT
from .data.entities import ENTITIES
from .data.modes import (MODE_REGISTRY, _MODE_CTX_TABLE, _MODE_NAMES,
                         _MODE_TERM_TABLE, normalize_mode)
from .engine import _resolve_terms
from .state import CTX_TABLES, TABLES
from .srt import _cue_zh_ref, _detect_layout
from .text import _decode_any



def _terms_tables_of(mode):
    """本模式执行集合覆盖的术语表名（P2-3 单源）。

    ``__AKJA_MERGE__`` 展开为并表两源（ak-ja 执行 AK_TERMS∪AK_JA_TERMS）；
    ``terms=None``（fix-en）按引擎口径落 BILINGUAL_TERMS；``__EMPTY__``（pgr）无表。
    """
    spec = MODE_REGISTRY.get(mode) or {}
    t = spec.get("terms")
    if t == "__AKJA_MERGE__":
        return ("AK_TERMS", "AK_JA_TERMS")
    if t == "__EMPTY__":
        return ()
    if not t:
        return ("BILINGUAL_TERMS",)
    return (t,)


def _table_exec_modes():
    """术语表名 → 会执行它的注册表模式（注册表顺序，确定性）。"""
    out = {}
    for m in MODE_REGISTRY:
        for t in _terms_tables_of(m):
            out.setdefault(t, []).append(m)
    return out


_TABLE_EXEC_MODES = _table_exec_modes()


def kb_scope_modes(mode):
    """执行口径的模式闭包：与本模式共享任一术语表的注册表模式 ∪ {本模式}。

    ak-ja 与 ak 共用 AK_TERMS（ak-ja 是增量表并表执行）→ 两者互在闭包内；
    这正是 audit / AI 必须与引擎（_resolve_terms）对齐的口径。
    """
    mode = normalize_mode(mode)
    mine = set(_terms_tables_of(mode))
    out = {mode}
    if mine:
        for m in MODE_REGISTRY:
            if mine & set(_terms_tables_of(m)):
                out.add(m)
    return out


def kb_mode_scope(mode):
    """单一对象级真源（P2-3）：引擎 / audit / AI 三面共用同一 mode 视图。

    返回 dict：
      mode          归一后的模式键；
      scope_modes   执行口径闭包（o. 共享术语表的模式）；
      layout/layers 注册表版式与图层（P2-1 字段，供 audit/报告解释实际启用了哪些层）；
      terms         引擎真正用于替换的术语表对象（_resolve_terms，含 ak-ja 并表）；
      ctx           注册表 ctx 槽对应的原始语境表（未编译，供抠锚点字面量）；
      exclude       本模式是否消费 EXCLUDE 回滚（layers 有 exclude 才给表）；
      objects       _kb_view() 中 tagged 了本模式的对象（字面量顺序不变）。
    """
    mode = normalize_mode(mode)
    spec = MODE_REGISTRY.get(mode) or {}
    layers = tuple(spec.get("layers") or ())
    return {
        "mode": mode,
        "scope_modes": kb_scope_modes(mode),
        "layout": spec.get("layout"),
        "layers": layers,
        "terms": _resolve_terms(mode),
        "ctx": CTX_TABLES.get(spec.get("ctx") or "") or [],
        "exclude": EXCLUDE_CONTEXT if "exclude" in layers else {},
        "objects": [e for e in _kb_view().values() if mode in e["modes"]],
    }



def _kb_view():
    """把 扁平表 + ENTITIES 折叠成对象级视图：{canonical: dict}。

    同一 canonical 跨表/跨模式的全部变体、条件规则、负向排除聚合为一个对象；
    ENTITIES 的 en/ja/ko/category/note/aliases/parent 元数据覆盖进对应对象。

    ⚠ 字面量顺序 = kb-export / kb-lookup / kb-lint 的输出序，**不可改成字母序推导**
      （2026-11-24 注释见 data/modes.py）。P2-3 只做「补字段 + modes 聚合」，
      既有的四段折叠顺序（变体表→英文行修正表→ctx→exclude→ENTITIES）保持不变。

    P2-3 语义：
      · modes  = 扁平表命中模式 ∪ 会执行该表的模式（ak-ja 并表闭包）∪ ENTITIES.modes；
        旧版只从扁平表折叠，纯元数据对象（ENTITY 声明但无变体）恒为 modes=[]，
        228 个对象对 audit/AI 完全不可见。
      · aliases/parent 从 ENTITIES 折叠（无声明则空），与 calib_entity.spec 同口径。
    """
    kb = {}

    def ent(c):
        return kb.setdefault(c, {
            "canonical": c, "en": "", "ja": "", "ko": "",
            "category": "", "modes": [], "variants": [],
            "ctx": [], "exclude": [], "note": "",
            "aliases": [], "parent": ""})

    def _add_mode(e, mode):
        if mode not in e["modes"]:
            e["modes"].append(mode)

    for mode, tname in _MODE_TERM_TABLE.items():
        for wrong, right in (TABLES.get(tname) or {}).items():
            e = ent(right)
            for m in _TABLE_EXEC_MODES.get(tname, (mode,)):
                _add_mode(e, m)
            if wrong not in e["variants"]:
                e["variants"].append(wrong)
    # EN_LINE_TERM_FIXES 修正的是外文行（目标非中文官方名），单独挂 fix-en 模式
    for wrong, right in (TABLES.get("EN_LINE_TERM_FIXES") or {}).items():
        e = ent(right)
        _add_mode(e, "fix-en")
        if wrong not in e["variants"]:
            e["variants"].append(wrong)
    for mode, cname in _MODE_CTX_TABLE.items():
        for rx, wrong, right in (CTX_TABLES.get(cname) or []):
            if not wrong or not right:
                continue
            e = ent(right)
            _add_mode(e, mode)
            if (rx, wrong) not in e["ctx"]:
                e["ctx"].append((rx, wrong))
    for wrong, (right, rxs) in (EXCLUDE_CONTEXT or {}).items():
        e = ent(right)
        _add_mode(e, "bi")
        for rx in rxs:
            if (wrong, rx) not in e["exclude"]:
                e["exclude"].append((wrong, rx))
    for e0 in ENTITIES:
        e = ent(e0.canonical)
        e["en"], e["ja"], e["ko"] = e0.en, e0.ja, e0.ko
        e["category"] = e0.category
        if e0.note:
            e["note"] = (e["note"] + "；" + e0.note) if e["note"] else e0.note
        # P2-3：ENTITY 声明的模式并入对象（无变体/ctx 的纯元数据对象也能被 mode 作用域看见）
        for m in (e0.modes or ()):
            _add_mode(e, m)
        # P2-3：aliases（官方简称/别译）与 parent（复合对象父级）——与 spec.EntitySpec 同口径
        for a in (getattr(e0, "aliases", ()) or ()):
            if a and a not in e["aliases"]:
                e["aliases"].append(a)
        par = getattr(e0, "parent", "") or ""
        if par and not e["parent"]:
            e["parent"] = par
    return kb



#: audit 扫 1 白名单：中文行里出现这些拉丁串属正常（抽卡分级术语、中文语境通用外来词），
#: 不算「未翻译残留」；其余一律进候选交人工裁决。
_AUDIT_LATIN_OK = re.compile(
    r"^(?:"
    r"[A-FS]\+?|S\d+(?:\s*R\d+)?|SR\d+(?:\s*R\d+)?|SSS|SSR|EX|UR|"
    # 2026-11-24《What is Kuro Games Even DOING!?》：EA=Electronic Arts（《圣歌》发行方），
    #   与 NPC/PC 同属合法保留英文缩写，不按未译残留报警。
    r"YouTube|YouTuber|VOD|Xbox|NPC|MVP|PNG|JPG|DNA|OK|PC|PS5|HP|DPS|UI|AI|EA|"
    r"bug|Boss|Incel|Discord|Gacha|gacha|NTE|"
    # 2026-11-01《How Did You Join Arknights or Endfield?》：已裁决「保留英文原形」的
    #   主播/频道/平台名，与无第二佐证、按戒律不强判的 ASR 连读专名（见该片 gloss.md 待裁决表）。
    #   加进白名单是为了让扫 1 只报「真该改却没改」的漏译，不再淹死在合法英文里。
    r"Kukki|Billy|Kiara|Kara|Felix|Zephron|Reddit|Twitter|Steam|VTuber|OSU|"
    r"Ardia|Aedia|Preminix|Premik|Reconventor|Escalan|Rosotis|Rozotis|Celer|"
    r"Ryden|Sed|Oka|Hoy|Waring|Lland|Calcul|Yosta|Catcher|Aba|CVT|HSI|ZC|GI|"
    r"WW|GFL|OJK|ZMA|NFL|GA|TCG|IP|RPG|API|meta|based|ED|war|Roy|"
    # 2026-11-02《명조》Day 2「띵킹 2」韩语直播片（5773 cue）：已裁决「查无官方中文 ⇒ 保留
    #   原语言」的选手/队伍/栏目/品牌 ID，逐条出处见 _calib_mingchao_day2/gloss.md §3、§3b。
    #   只收本片实测高频且人工确认过的；低频孤例继续报警，交由后续片源再判，避免把白名单
    #   写成"什么都合法"从而丧失扫 1 的检测力。
    #   ⚠ 另有一批看着像漏译、实为**已定官方中文**的形（Chisa=千咲、Moni=莫宁、Linne=琳奈、
    #     Kartisia=卡提希娅）**故意不入白名单**——它们该被扫 1 报出来，改错才是正确行为。
    r"Thinking|Lucky|AMS|Akriyoung|Akri|Madlife|Mangmang|Sangdeok|Sangdong|"
    r"Sangdang|Sangdo|Sang|Myung|Myungdeok|Heena|Tabi|Hioki|Hiki|Rokki|"
    r"Junseo|Nickyong|Lingyong|Seollim|Minimelon|Denian|Gwanjongdae|"
    r"Chzzk|Aegis|PTST|Venus|Coupang|Naver|What|Day(?:\s*\d+)?|Team|Tier"
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
                        # 2026-11-02：中文行改走 _cue_zh_ref。旧逻辑写死「除末行外都是中文」，
                        # 遇到英文在上的双语片源会把中/英两列整体互换，audit 报的全是乱账。
                        zh_pos, ref_pos = _cue_zh_ref(texts)
                        out.append((s, "\n".join(texts[i] for i in zh_pos) or texts[0],
                                    "\n".join(texts[i] for i in ref_pos)))
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
    """按模式取「生效的」错形表与参考行锚点（P2-3：单一视图 kb_mode_scope）。

    ⚠ 必须**按模式**取：直接拿 `_kb_view()` 全量扫会把别的片源的规则（如某模式的
    space→虚质空间）当成漏校。但「本模式口径」一律以 kb_mode_scope 为准：
      · 错形表 = 引擎执行表（_resolve_terms）——ak-ja 因此自动带上 AK_TERMS，
        不再出现「审计口径 < 执行口径」的漏报（旧版只读增量表 AK_JA_TERMS）；
      · 语境表 = 注册表 ctx 槽（不是 _MODE_CTX_TABLE 的反推）；
      · 对象级元数据按 scope_modes 闭包过滤（共享术语表的模式互见，如 ak↔ak-ja）。
    2026-11-22 变体键降级：入口 normalize_mode——旧顶层变体键与既有别名
    归一到「游戏-细类」新键后查视图。
    返回 (错形→官方名 字典, [(锚点字面量, 官方名)])。
    """
    mode = normalize_mode(mode)
    scope = kb_mode_scope(mode)
    scope_modes = scope["scope_modes"]
    wrong2right = {}
    anchors = []
    variants_lc = {}          # canonical -> {小写变体}，用于判定 ctx 字面量像不像专名
    ctx_by_canon = {}         # canonical -> [参考行正则]

    def _reg_variant(canon, w):
        if w:
            variants_lc.setdefault(canon, set()).add(str(w).lower())

    # ---- 第一遍：错形表（执行口径）+ 变体 + 外文名锚点 ----
    for wrong, right in scope["terms"].items():
        if wrong and right and wrong != right:
            wrong2right.setdefault(wrong, right)
            _reg_variant(right, wrong)
    for e in ENTITIES:
        if mode and not (set(e.modes or ()) & scope_modes):
            continue
        for w in e.variants:
            if w and w != e.canonical:
                wrong2right.setdefault(w, e.canonical)
                _reg_variant(e.canonical, w)
        for nm in _audit_names(e.en, e.ja, e.ko):
            anchors.append((nm, e.canonical))

    # ---- 第二遍：ctx 参考行锚点（单一来源＝本模式注册表 ctx 表）----
    #   ENTITY 上的 ctx 已由 state._register_entities 投影进该模式 ctx 表（无 ctx 槽的
    #   模式根本不会执行它），因此这里只读表：既避免「审计看得到、引擎改不了」的假漏校
    #   （endo 曾因此多报 12 条），也避免把 AK_CONTEXT（ak 的语境表）串进 ak-ja 作用域
    #   （ak-ja 只执行 AK_JA_CONTEXT）。2026-11-24 P2-3 口径对齐。
    for item in scope["ctx"]:
        rx, wrong, right = (list(item) + [None, None])[:3]
        if not right:
            continue
        # wrong == right 的「保护型」no-op 规则对审计无信息量（它不产生任何改动），
        # 若让它先占用 setdefault，会把真正改写的同键规则挡掉（洛瑟菈 例）。
        if wrong and wrong != right:
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



def _cmd_audit(src, mode="bi", out=None, as_json=False, limit=300, loose=False, window=0):
    """audit：校准后成品的「名词漏校三扫」（机械遍 / AI 校准之后的收口体检）。

    扫 1  拉丁残留      —— 中文行里白名单外的英文/罗马字（分级字母、通用外来词不计）。
    扫 2  错形残留      —— 本模式生效的「无条件变体 / ctx 条件错形」命中中文行、
                           官方名却不在该行；且参考行佐证该实体（命中专名型锚点）。
                           这类可直接采纳。`--loose` 追加「无佐证」的低置信项
                           （错形表里混有常用词作锚点，噪声大，必须人工过筛）。
    扫 3  同词族一致性  —— 参考行命中锚点、中文行却没有对应官方名。反向核查查不出这类
                           （每种错形都不是「官方名缺失」），是漏校的主力来源。

    window：扫 2/3 判「官方名是否已译」时向前后各看 N 条中文行（默认 0＝严格逐 cue，旧行为）。
            2026-11-09 新增：ASR 常把专名跨 cue 切断（'a member of Vanessa's' / 'Egret squad.'），
            官方名落在邻接条时逐 cue 判定会**误报漏校**。机制与 missing 的 zh_around 同规。
            ⚠ 只放宽「已译」判定，不改扫 1，也不改报告里展示的中文行文本。

    退出码：1＝有候选（可当门禁），0＝干净。
    """
    mode = normalize_mode(mode)           # 2026-11-22 变体键降级：旧键/别名归一新键
    if not os.path.isfile(src):
        print(f"文件不存在：{src}")
        return 1
    layout, cues = _iter_cue_triples(src)
    wrong2right, anchor_pairs = _audit_mode_scope(mode)

    order = sorted(n for n, _z, _r in cues)
    pos = {n: k for k, n in enumerate(order)}
    zmap = {n: z for n, z, _r in cues}

    def zh_around(n, zh):
        if window <= 0:
            return zh
        k = pos[n]
        return " ".join(zmap[m] for m in order[max(0, k - window):k + window + 1])

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
        zhw = zh_around(num, zh)
        ref_targets = {}
        if ref and arx is not None:
            for m in arx.finditer(ref):
                grp = aidx[m.group(0)]
                # 同一锚点常挂多个官方名（如 Sentinel → 岁主 / 锁暝 / 前任岁主）。
                # 只要其中任意一个已经出现在中文行，就说明这条已校准，全部放过。
                if any(c in zhw for c in grp):
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
            if canon and canon not in zhw:
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


def audit_gate_findings(src, mode="bi", window=0):
    """audit 交付门禁的结构化入口（2026-11-24 P1，附加函数，不改 _cmd_audit）。

    返回 dict：
      anchors  本模式参考行锚点数（0＝无锚点，三扫会「假绿」，门禁应判 inconclusive）；
      s2_hi    高置信错形残留 [(num, wrong, official)]——参考行已佐证、可直接机械补校；
      s1_n / s3_n  拉丁残留 / 同词族缺口计数（仅报告，不自动改）。
    复用 _iter_cue_triples / _audit_mode_scope / _audit_build_alt，与 _cmd_audit 同判据。
    文件不存在或异常返回 {"anchors": 0, "s2_hi": [], "s1_n": 0, "s3_n": 0, "error": ...}。
    """
    res = {"anchors": 0, "s2_hi": [], "s1_n": 0, "s3_n": 0}
    try:
        mode = normalize_mode(mode)
        if not os.path.isfile(src):
            res["error"] = "文件不存在"
            return res
        _layout, cues = _iter_cue_triples(src)
        wrong2right, anchor_pairs = _audit_mode_scope(mode)
        res["anchors"] = len(set(anchor_pairs))
        order = sorted(n for n, _z, _r in cues)
        pos = {n: k for k, n in enumerate(order)}
        zmap = {n: z for n, z, _r in cues}

        def zh_around(n, zh):
            if window <= 0:
                return zh
            k = pos[n]
            return " ".join(zmap[m] for m in order[max(0, k - window):k + window + 1])

        for num, zh, _ref in cues:
            if [t for t in re.findall(r"[A-Za-z][A-Za-z'\-\.]*", zh)
                    if not _AUDIT_LATIN_OK.match(t)]:
                res["s1_n"] += 1
        arx, aidx = _audit_build_alt(anchor_pairs)
        wrx, widx = _audit_build_alt(
            [(w, c) for w, c in wrong2right.items() if len(w) >= 2 and w not in c],
            boundary=False)
        for num, zh, ref in cues:
            zhw = zh_around(num, zh)
            ref_targets = {}
            if ref and arx is not None:
                for m in arx.finditer(ref):
                    grp = aidx[m.group(0)]
                    if any(c in zhw for c in grp):
                        continue
                    for canon in grp:
                        ref_targets.setdefault(canon, m.group(0))
            if wrx is not None:
                for m in wrx.finditer(zh):
                    for canon in widx[m.group(0)]:
                        if canon in zh:
                            continue
                        if canon in ref_targets:
                            res["s2_hi"].append((num, m.group(0), canon))
            for canon, _lit in ref_targets.items():
                if canon and canon not in zhw:
                    res["s3_n"] += 1
    except Exception as e:                               # noqa: BLE001
        res["error"] = f"{type(e).__name__}: {e}"
    return res


def _mode_export_entities(mode):
    """模式作用域导出（P2-3）：把 kb_mode_scope 的执行口径投影成对象列表。

    与全量 `_kb_view` 导出的差别：每个对象的 variants/ctx **只保留本模式真正会执行**
    的错形（ak-ja 因此包含 AK_TERMS 那批，而不是只给增量表），modes 字段只写本模式。
    这样 AI build_rules 的 `mode_key in e["modes"]` 过滤拿到的就是执行口径，
    与引擎、audit 三面同源；对象级元数据（en/ja/ko/category/aliases/parent/note）
    仍从 _kb_view 取（不按模式裁剪）。
    """
    scope = kb_mode_scope(mode)
    view = _kb_view()
    per = {}

    def slot(c):
        return per.setdefault(c, {"variants": [], "ctx": []})

    for wrong, right in scope["terms"].items():
        if not wrong or not right or wrong == right:
            continue
        s = slot(right)
        if wrong not in s["variants"]:
            s["variants"].append(wrong)
    for item in scope["ctx"]:
        rx, wrong, right = (list(item) + [None, None, None])[:3]
        if not right or not wrong:
            continue
        s = slot(right)
        rec = (str(rx), wrong)
        if rec not in s["ctx"]:
            s["ctx"].append(rec)
    has_exclude = "exclude" in scope["layers"]
    out = []
    for canon, s in per.items():
        meta = view.get(canon, {})
        out.append({
            "canonical": canon,
            "en": meta.get("en", ""), "ja": meta.get("ja", ""), "ko": meta.get("ko", ""),
            "category": meta.get("category", ""),
            "modes": [scope["mode"]],
            "variants": s["variants"],
            "aliases": list(meta.get("aliases", [])),
            "parent": meta.get("parent", ""),
            "ctx": s["ctx"],
            "exclude": (list(meta.get("exclude", [])) if has_exclude else []),
            "note": meta.get("note", ""),
        })
    return out


def _cmd_kb_export(out=None, as_json=False, mode=""):
    """kb-export：导出完整对象级知识库（MD 或 JSON），供审阅/投喂 AI 校准。

    mode 非空时导出「该模式执行口径」的对象视图（见 _mode_export_entities）：
    AI 校准用它喂 build_rules，保证与引擎/audit 同一错形集；为空保持全量对象视图。
    """
    ents = None
    scoped_empty = False
    if mode:
        ents = sorted(_mode_export_entities(mode),
                      key=lambda e: (-len(e["variants"]), e["canonical"]))
        if not ents:
            # pgr 这类纯侧车模式（terms=__EMPTY__、ctx=None）没有可执行知识：
            # 退回全量对象视图，保留 AI 侧的「降级为全量」告警通路，不至于规则全空。
            scoped_empty = True
            ents = sorted(_kb_view().values(),
                          key=lambda e: (-len(e["variants"]), e["canonical"]))
    else:
        ents = sorted(_kb_view().values(), key=lambda e: (-len(e["variants"]), e["canonical"]))
    if scoped_empty:
        print(f"kb-export：模式 {normalize_mode(mode)} 无执行口径知识，已退回全量对象视图")
    if as_json:
        import json
        data = [{
            "canonical": e["canonical"], "en": e["en"], "ja": e["ja"],
            "ko": e["ko"], "category": e["category"],
            "modes": e["modes"], "variants": e["variants"],
            "aliases": e["aliases"], "parent": e["parent"],
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
            if e["aliases"]:
                L.append("- 官方别名: " + "、".join(e["aliases"]))
            if e["parent"]:
                L.append("- 父级对象: " + e["parent"])
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
                *e["variants"], *e.get("aliases", ()),
                *(w for _, w in e["ctx"]),
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

