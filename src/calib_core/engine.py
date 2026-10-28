# -*- coding: utf-8 -*-
# @version 2.8.0
"""校准主引擎 process()

源：subtitle_calib_merged.py L11610-L11977 @ 97d7d463（2026-10-24 冻结快照）
"""
import io
import os
import re
import shutil
import sys
import unicodedata
from .asr import _ref_for_match
from .data.ark import AK_KO_TERMS, AK_TERMS, PGR_EN_TERMS, WWOC_TERMS
from .data.bilingual import BILINGUAL_TERMS, FFRS_TERMS, WORD_MAP
from .data.endfield import ENDFIELD_BI_TERMS, ENDFIELD_KO_TERMS, ENDFIELD_TERMS
from .data.ja import JA_ENDFIELD_TERMS, JA_TERMS, RETIRED_JA_KEYS
from .data.ko import KO_ASR_TERMS, KO_TERMS, RETIRED_KO_KEYS
from .data.limbus import LIMBUS_TERMS
from .data.misc import EN_LINE_TERM_FIXES, HSR_TERMS, POKEMON_TERMS, REACT_TERMS, ZELDA_TERMS, ZH_ONLY_TERMS
from .learn import _learned_terms_for_mode
from .modes import endfield_auto_markers
from .replace import _compile_map, _ctx_replace, _replace_report
from .state import _AK_CONTEXT_COMPILED, _AK_KO_CONTEXT_COMPILED, _CONTEXT_COMPILED, _ENDFIELD_BI_CONTEXT_COMPILED, _ENDFIELD_KO_CONTEXT_COMPILED, _EXCLUDE_COMPILED, _FFRS_CONTEXT_COMPILED, _HSR_CONTEXT_COMPILED, _JA_CONTEXT_COMPILED, _JA_ENDFIELD_CONTEXT_COMPILED, _KO_ASR_CONTEXT_COMPILED, _KO_CONTEXT_COMPILED, _LIMBUS_CONTEXT_COMPILED, _POKEMON_CONTEXT_COMPILED, _REACT_CONTEXT_COMPILED, _WWOC_CONTEXT_COMPILED
from .text import _KO_HANGUL, _decode_any, _split_cue_text



def _load_override_tsv(path):
    """读取 序号<TAB>校准后中文 侧车覆盖表 -> {str: text}。行分隔可为 TAB/全角空格。"""
    over = {}
    if not os.path.exists(path):
        return over
    for ln in _decode_any(open(path, "rb").read()).splitlines():
        ln = ln.strip("\ufeff").rstrip("\r")
        m = re.match(r"(\d+)", ln)
        if not m:
            continue
        txt = ln[m.end():].lstrip("\t \u3000\u3000").strip()
        if txt:
            over[m.group(1)] = txt
    return over



def process(path, out_path=None, report_path=None, mode="bi",
            fix_en=False, pgr_override=None, learned_kb=None):
    """对 SRT 校准。返回 (改动行rows, 术语命中hits)。
      mode="bi"   双语模式：BILINGUAL_TERMS + CONTEXT_MAP + WORD_MAP 改首中文行。
      mode="ko"   韩语模式：KO_TERMS 统一中文行术语。
      mode="ja"   日语模式：JA_TERMS + JA_CONTEXT（日语参考行佐证）统一中文行术语。
      mode="endo" 终末地模式：ENDFIELD_TERMS 统一全部文本行。
      mode="ak"   明日方舟本体模式：AK_TERMS + AK_CONTEXT（英文参考行佐证）统一**全部**中文行。
                  2026-10-14 起：谷翻片「中文2行+英文2行」结构下逐行校准全部含汉字行，
                  ctx 锚点=该 cue 全部英文行拼接（规整空白）；不含汉字的文本行一律不动。
      mode="zho"  中文行专属模式：ZH_ONLY_TERMS 只改首中文行英文噪音（不动英文/参考行）。
      fix_en=True   双语模式下用 EN_ASR_SPLIT_FIXES + EN_LINE_TERM_FIXES 修正英文/参考行（默认不动）。
    参考行锚定（CONTEXT/EXCLUDE）一律先经 _ref_for_match 规整（ASR 断词容错），
    但默认输出的参考行保持原样，只有 fix_en=True 才写回。
    """
    if mode == "ko":
        terms = KO_TERMS
    elif mode == "ja":
        terms = JA_TERMS
    elif mode == "jpe":                 # 日语原声·终末地：JA_ENDFIELD_TERMS + 上下文佐证
        terms = JA_ENDFIELD_TERMS
    elif mode == "wwoc":
        terms = WWOC_TERMS
    elif mode == "endo":
        terms = ENDFIELD_TERMS
    elif mode == "endobi":     # 终末地·中英双语片源：只改首中文行（英文参考行不动）
        terms = ENDFIELD_BI_TERMS
    elif mode == "endoko":     # 终末地·韩语原声片源：只改首中文行（韩语参考行不动）
        terms = ENDFIELD_KO_TERMS
    elif mode in ("ak", "zho"):
        terms = AK_TERMS if mode == "ak" else ZH_ONLY_TERMS
    elif mode == "pgren":       # 战双帕弥什·英文原声（中英双语片源）：PGR_EN_TERMS 统一首中文行
        terms = PGR_EN_TERMS
    elif mode == "akko":        # 明日方舟韩语原声：AK_KO_TERMS + AK_KO_CONTEXT(韩语佐证)
        terms = AK_KO_TERMS
    elif mode == "react":
        terms = REACT_TERMS
    elif mode == "zel":         # 塞尔达传说片源（2026-09-14 新增）：ZELDA_TERMS 统一首中文行，独立于其它片源表
        terms = ZELDA_TERMS
    elif mode == "hsr":         # 崩坏：星穹铁道片源（2026-10-20 新增）：HSR_TERMS + HSR_CONTEXT，独立于其它片源表
        terms = HSR_TERMS
    elif mode == "pkm":         # 宝可梦片源（2026-10-21 新增）：POKEMON_TERMS + POKEMON_CONTEXT，独立于其它片源表
        terms = POKEMON_TERMS
    elif mode == "limbus":      # 边狱巴士片源（2026-10-26 新增）：LIMBUS_TERMS + LIMBUS_CONTEXT，独立于其它片源表
        terms = LIMBUS_TERMS
    elif mode == "ffrs":        # 最终幻想：共鸣（2026-10-28 新增）：FFRS_TERMS + FFRS_CONTEXT
        terms = FFRS_TERMS
    elif mode == "pgr":
        terms = {}
    else:
        terms = BILINGUAL_TERMS
    # 学习系统注入：confirmed 规则并入本模式术语表（与既有键冲突时跳过并告警）
    if learned_kb:
        lt = _learned_terms_for_mode(learned_kb, mode)
        if lt:
            terms = dict(terms)
            skipped = 0
            for w, r in lt.items():
                if w in terms and terms[w] != r:
                    skipped += 1
                    continue
                terms.setdefault(w, r)
            if skipped:
                print(f"⚠ {skipped} 条学习规则与既有术语表目标冲突，已跳过"
                      f"（learned-show 查看，人工裁决）")
    # 2026-10-06 危险裸键闸门：RETIRED_KO_KEYS 无论来自静态表、learned_kb 还是
    #   applied.json 注入，一律在编译前剔除（保证"信信→辛夷"等已下线键绝不误伤）。
    if mode == "ko" and any(k in terms for k in RETIRED_KO_KEYS):
        terms = {k: v for k, v in terms.items() if k not in RETIRED_KO_KEYS}
    # 2026-10-14 日语同款闸门：'笛卡尔' 会在运行期被 applied.json 复活，必须一并剔除，
    #   否则它抢跑 Entity("卡提希娅") 的 ctx（笛卡尔西亚 -> 卡提希娅西亚）。
    if mode == "ja" and any(k in terms for k in RETIRED_JA_KEYS):
        terms = {k: v for k, v in terms.items() if k not in RETIRED_JA_KEYS}
    # 术语表只编译一次（长键序 + 键字符集），逐行替换走 _replace_report 单遍扫描
    term_pairs, term_chars = _compile_map(terms)
    word_pairs, word_chars = _compile_map(WORD_MAP)
    enfix_pairs, enfix_chars = _compile_map(EN_LINE_TERM_FIXES)

    raw = open(path, "rb").read()
    crlf = b"\r\n" in raw
    bom = raw.startswith(b"\xef\xbb\xbf")
    norm = _decode_any(raw).replace("\r\n", "\n").replace("\r", "\n")
    lines = norm.split("\n")
    out = list(lines)

    # 片源自适应（2026-10-07）：默认 bi 模式自动识别终末地双语片源并并入其术语表。
    #   不加这段，流水线/GUI 默认（都不传片源模式）对本类片源一处不改。
    if mode == "bi" and os.environ.get("VT_NO_AUTO_TERMS", "") != "1":
        _mk = endfield_auto_markers(lines)
        if len(_mk) >= 2:
            _merged = dict(terms)
            for _w, _r in ENDFIELD_BI_TERMS.items():
                _merged.setdefault(_w, _r)
            terms = _merged
            term_pairs, term_chars = _compile_map(terms)
            print("片源自适应：检测到终末地双语片源（特征词 %d 个：%s）→ 已并入 ENDFIELD_BI_TERMS"
                  % (len(_mk), "、".join(_mk[:6])))

    hits, rows = {}, []
    i, n = 0, len(lines)
    while i < n:
        s = lines[i].strip()
        if s.isdigit() and (i == 0 or lines[i - 1].strip() == ""):
            j = i + 1
            if j < n and "-->" in lines[j]:
                kk = j + 1
                while kk < n and lines[kk].strip() != "":
                    kk += 1
                if kk - 1 >= j + 1:            # 存在文本行
                    num = int(s)
                    # 2026-10-23：按语言定位中文行/参考行，兼容「英文在上、中文在下」
                    # 的双语片源。此前固定取首文本行，会把英文参考行当中文改。
                    text_tis = list(range(j + 1, kk))
                    zh_pos, ref_pos = _split_cue_text([lines[ti] for ti in text_tis])
                    zh_idx = text_tis[zh_pos[0]] if zh_pos else j + 1
                    ref = lines[text_tis[ref_pos[-1]]] if ref_pos else lines[kk - 1]
                    if mode != "endo" and kk - 1 == j + 1:
                        # 单文本行 cue：该行即参考行（无独立中文行）。
                        # 例外（2026-10-12）：--ko 纯韩语片源（韩国主播直播 ASR，每 cue
                        # 单行韩语）——该行含谚文即应用 KO_ASR 层（韩语错形→官方韩语），
                        # 否则整块跳过，防止把术语替换误写到参考/英文行上。
                        only = lines[j + 1]
                        if mode == "ko" and _KO_HANGUL.search(only):
                            if "_ko_asr_pairs" not in dir():
                                _ko_asr_pairs, _ko_asr_chars = _compile_map(KO_ASR_TERMS)
                            new = _replace_report(only, _ko_asr_pairs, _ko_asr_chars, hits)
                            for crx, wrong, right in _KO_ASR_CONTEXT_COMPILED:
                                if wrong in new and crx.search(new):
                                    new = _ctx_replace(new, wrong, right)
                            if new != only:
                                rows.append((num, only, new, only))
                                out[j + 1] = new
                        i = kk
                        continue
                    if not zh_pos:
                        # 多文本行且无法识别中文行（全拉丁/全参考行）：绝不写参考行
                        i = kk
                        continue
                    old = lines[zh_idx]
                    if fix_en and mode == "bi":  # --fix-en：修正英文/参考行术语（仅双语模式）
                        for ti in [text_tis[p] for p in ref_pos]:
                            eold = out[ti]
                            e1 = _ref_for_match(eold)     # 先修 ASR 断词/粘连，再修术语
                            enew = _replace_report(e1, enfix_pairs, enfix_chars, hits)
                            if enew != eold:
                                rows.append((num, eold, enew, eold))
                                out[ti] = enew
                        if ref_pos:               # 上下文匹配/ERROR 翻译改用修正后参考行
                            ref = " ".join(out[text_tis[p]] for p in ref_pos)
                    # 锚定匹配用参考行（断词/误听容错）：输出仍用 ref，结构零改动
                    ref_m = _ref_for_match(ref)
                    if mode == "pgr" and pgr_override and str(num) in pgr_override:
                        # PGR 模式：侧车整行覆盖（校准后中文已是终稿，不再叠加术语表）
                        new = pgr_override[str(num)]
                        if new != old:
                            rows.append((num, old, new, ref))
                            out[zh_idx] = new
                    elif mode == "react":     # 音乐/演唱点评：REACT_TERMS 统一首中文行 + REACT_CONTEXT 参考行佐证歧义词
                        new = _replace_report(old, term_pairs, term_chars, hits)
                        for crx, wrong, right in _REACT_CONTEXT_COMPILED:
                            if wrong in new and crx.search(ref_m):
                                new = _ctx_replace(new, wrong, right)
                        if new != old:
                            rows.append((num, old, new, ref))
                            out[zh_idx] = new
                    elif mode == "hsr":       # 崩坏：星穹铁道：HSR_TERMS 统一首中文行 + HSR_CONTEXT 英文参考行佐证
                        new = _replace_report(old, term_pairs, term_chars, hits)
                        for crx, wrong, right in _HSR_CONTEXT_COMPILED:
                            if wrong in new and crx.search(ref_m):
                                new = _ctx_replace(new, wrong, right)
                        if new != old:
                            rows.append((num, old, new, ref))
                            out[zh_idx] = new
                    elif mode == "pkm":       # 宝可梦：POKEMON_TERMS 统一首中文行 + POKEMON_CONTEXT 英文参考行佐证
                        new = _replace_report(old, term_pairs, term_chars, hits)
                        for crx, wrong, right in _POKEMON_CONTEXT_COMPILED:
                            if wrong in new and crx.search(ref_m):
                                new = _ctx_replace(new, wrong, right)
                        if new != old:
                            rows.append((num, old, new, ref))
                            out[zh_idx] = new
                    elif mode == "limbus":    # 边狱巴士：LIMBUS_TERMS 统一首中文行 + LIMBUS_CONTEXT 英文参考行佐证
                        new = _replace_report(old, term_pairs, term_chars, hits)
                        for crx, wrong, right in _LIMBUS_CONTEXT_COMPILED:
                            if wrong in new and crx.search(ref_m):
                                new = _ctx_replace(new, wrong, right)
                        if new != old:
                            rows.append((num, old, new, ref))
                            out[zh_idx] = new
                    elif mode == "ffrs":      # 最终幻想：共鸣：FFRS_TERMS + FFRS_CONTEXT 英文参考行佐证
                        new = _replace_report(old, term_pairs, term_chars, hits)
                        for crx, wrong, right in _FFRS_CONTEXT_COMPILED:
                            if wrong in new and crx.search(ref_m):
                                new = _ctx_replace(new, wrong, right)
                        if new != old:
                            rows.append((num, old, new, ref))
                            out[zh_idx] = new
                    elif mode == "ko":       # 韩语原声·鸣潮：KO_TERMS + KO_CONTEXT 校准**全部中文行**
                        # 2026-10-06 修复（梦州 4장4막 二次校准定位的根因）：谷翻反应片每 cue
                        #   常见「中文 2 行 + 谚文 2 行」结构。旧实现只改首文本行、锚点只取末行
                        #   谚文 → ①第二中文行整片漏校（该批 112 处残留 111 处在第二行）；
                        #   ②ctx 锚点落在非末行谚文时失效（방랑자/수호신/혈령/만상 等 355 处漏校）。
                        #   现按“含谚文=参考行”划分：中文区全部行过术语表+ctx；锚点与中文行
                        #   **逐行配对**（zh_i↔kr_i，谷翻分句顺序一致；行数不齐时回退为整 cue
                        #   谚文拼接），从根上避免 성격/캐릭터 混在一个 cue 时的跨句误伤
                        #   （v1 报告回滚点 cue 497）。谚文参考行仍一字不动（结构零改动不变）。
                        zh_tis = [ti for ti in range(j + 1, kk) if not _KO_HANGUL.search(lines[ti])]
                        kr_tis = [ti for ti in range(j + 1, kk) if _KO_HANGUL.search(lines[ti])]
                        if not zh_tis and kr_tis:
                            # 纯韩语片源（2026-10-12 新增）：每 cue 全部文本行都含谚文
                            # （韩国主播直播 ASR 等），旧表键全是中文错形无法命中。
                            # 对韩语行应用 KO_ASR_TERMS(韩语错形→官方韩语) + KO_ASR_CONTEXT
                            # （锚定对象 = 行自身）。双语片源 zh_tis 非空，不进本分支。
                            if "_ko_asr_pairs" not in dir():
                                _ko_asr_pairs, _ko_asr_chars = _compile_map(KO_ASR_TERMS)
                            for ti in kr_tis:
                                lold = lines[ti]
                                new = _replace_report(lold, _ko_asr_pairs, _ko_asr_chars, hits)
                                for crx, wrong, right in _KO_ASR_CONTEXT_COMPILED:
                                    if wrong in new and crx.search(new):
                                        new = _ctx_replace(new, wrong, right)
                                if new != lold:
                                    rows.append((num, lold, new, ref))
                                    out[ti] = new
                            i = kk
                            continue
                        kr_all = " ".join(_ref_for_match(lines[ti]) for ti in kr_tis)
                        for zi, ti in enumerate(zh_tis):
                            if len(zh_tis) == len(kr_tis):
                                anchor = _ref_for_match(lines[kr_tis[zi]])   # 逐行配对佐证
                            else:
                                anchor = kr_all                              # 行数不齐回退拼接
                            lold = lines[ti]
                            new = _replace_report(lold, term_pairs, term_chars, hits)
                            for crx, wrong, right in _KO_CONTEXT_COMPILED:
                                if wrong in new and crx.search(anchor):
                                    new = _ctx_replace(new, wrong, right)
                            if new != lold:
                                rows.append((num, lold, new, ref))
                                out[ti] = new
                    elif mode == "wwoc":      # 综合手游 OST 世界杯：术语表 + 参考行佐证的歧义错形
                        new = _replace_report(old, term_pairs, term_chars, hits)
                        for crx, wrong, right in _WWOC_CONTEXT_COMPILED:
                            if wrong in new and crx.search(ref_m):
                                new = _ctx_replace(new, wrong, right)
                        if new != old:
                            rows.append((num, old, new, ref))
                            out[zh_idx] = new
                    elif mode in ("pgren", "zel"):  # 战双英文原声/塞尔达：统一首中文行术语（不动参考行）
                        new = _replace_report(old, term_pairs, term_chars, hits)
                        if new != old:
                            rows.append((num, old, new, ref))
                            out[zh_idx] = new
                    elif mode == "ja":          # 日语原声：JA_TERMS + JA_CONTEXT(日语行佐证) 统一首中文行
                        new = _replace_report(old, term_pairs, term_chars, hits)
                        for crx, wrong, right in _JA_CONTEXT_COMPILED:
                            if wrong in new and crx.search(ref_m):
                                new = _ctx_replace(new, wrong, right)
                        if new != old:
                            rows.append((num, old, new, ref))
                            out[zh_idx] = new
                    elif mode == "jpe":         # 日语原声·终末地：JA_ENDFIELD_TERMS + 上下文佐证
                        new = _replace_report(old, term_pairs, term_chars, hits)
                        for crx, wrong, right in _JA_ENDFIELD_CONTEXT_COMPILED:
                            if wrong in new and crx.search(ref_m):
                                new = _ctx_replace(new, wrong, right)
                        if new != old:
                            rows.append((num, old, new, ref))
                            out[zh_idx] = new
                    elif mode == "akko":        # 明日方舟韩语原声：AK_KO_TERMS + AK_KO_CONTEXT(韩语行佐证) 统一首中文行
                        new = _replace_report(old, term_pairs, term_chars, hits)
                        for crx, wrong, right in _AK_KO_CONTEXT_COMPILED:
                            if wrong in new and crx.search(ref_m):
                                new = _ctx_replace(new, wrong, right)
                        if new != old:
                            rows.append((num, old, new, ref))
                            out[zh_idx] = new
                    elif mode == "ak":          # 明日方舟本体：AK_TERMS + AK_CONTEXT(英文参考行佐证)
                        # 2026-10-14 改造（《All You Should Know in Arknights Next Update!》逐句复查定位根因）：
                        #   谷翻片每 cue 常见「中文 2 行 + 英文 2 行」。旧实现只改首中文行、锚点只取末行英文 →
                        #   ①第二中文行整片漏校（本片约六成改动落在第二行：#4 出生、#11 旗帜、#12 卡尔·塞·阿尔特、
                        #   #30 缪缪、#87 名次、#101 屏风、#102 旧水井、#103 黄色石头、#110 Sankta爷爷 等）；
                        #   ②佐证词在英文首行时 ctx 失效（#54 potential、#55 specter alter、#72 tiles、
                        #   #75 stun counter、#101 tap the screen）。
                        #   现按"含汉字=中文行"划分：中文行全部过术语表+ctx；锚点=全部英文行拼接后规整空白
                        #   （ASR 行尾空格会把 "gavial alter" 变双空格，跨行佐证正则漏命中——本片 #56 加维尔即此因）。
                        #   英文/参考行一律不动，结构零改动原则不变。
                        ak_zh = [text_tis[p] for p in zh_pos]
                        ak_en = [text_tis[p] for p in ref_pos]
                        if ak_zh and ak_en:
                            ak_anchor = re.sub(r"\s+", " ",
                                               _ref_for_match(" ".join(lines[_ti] for _ti in ak_en)))
                            for _ti in ak_zh:
                                lold = lines[_ti]
                                new = _replace_report(lold, term_pairs, term_chars, hits)
                                for crx, wrong, right in _AK_CONTEXT_COMPILED:
                                    if wrong in new and crx.search(ak_anchor):
                                        new = _ctx_replace(new, wrong, right)
                                if new != lold:
                                    rows.append((num, lold, new, ref))
                                    out[_ti] = new
                        elif ak_zh:             # 无参考行的纯中文 cue：退回首中文行口径
                            new = _replace_report(old, term_pairs, term_chars, hits)
                            if new != old:
                                rows.append((num, old, new, ref))
                                out[zh_idx] = new
                    elif mode == "zho":         # 中文行专属：统一首中文行
                        new = _replace_report(old, term_pairs, term_chars, hits)
                        if new != old:
                            rows.append((num, old, new, ref))
                            out[zh_idx] = new
                    elif mode == "endobi":     # 终末地·中英双语：只改首中文行
                        new = _replace_report(old, term_pairs, term_chars, hits)
                        # 2026-10-20 补：ENDFIELD_BI_CONTEXT 用英文参考行佐证「错形本身是通用
                        #   中文词」的官方名（枯萎→侵蚀 / 主管→监督 / 以太→超域 / 觉醒→苏醒 /
                        #   蚁人→管理员 / 前哨基地→据点 / 崩溃→猛击…）。此前 endobi 无语境槽，
                        #   这类错形只能逐 cue 手改；锚点匹配的是文件里实际存在的 ASR 英文。
                        for crx, wrong, right in _ENDFIELD_BI_CONTEXT_COMPILED:
                            if wrong in new and crx.search(ref_m):
                                new = _ctx_replace(new, wrong, right)
                        if new != old:
                            rows.append((num, old, new, ref))
                            out[zh_idx] = new
                    elif mode == "endoko":     # 终末地·韩语原声：ENDFIELD_KO_TERMS 只改首中文行，
                        #   并用 ENDFIELD_KO_CONTEXT（韩语参考行正则佐证）修「普通中文词」误译
                        #   —— 2026-10-13 新增：恶魔→邪魔 / 按摩→安玛 / 排名第三→萨米
                        #   （这三条都是通用中文词，裸键会误伤，必须韩语行锚定）。
                        new = _replace_report(old, term_pairs, term_chars, hits)
                        for crx, wrong, right in _ENDFIELD_KO_CONTEXT_COMPILED:
                            if wrong in new and crx.search(ref_m):
                                new = _ctx_replace(new, wrong, right)
                        if new != old:
                            rows.append((num, old, new, ref))
                            out[zh_idx] = new
                    elif mode == "endo":       # 终末地模式：ENDFIELD_TERMS 统一全部中文行
                        # 2026-10-23：改为只改中文行；单语终末地片源等价于原“全部文本行”，
                        # 双语片源不会再误改英文参考行（应改用 --endobi）。
                        for ti in [text_tis[p] for p in zh_pos]:
                            lold = lines[ti]
                            new = _replace_report(lold, term_pairs, term_chars, hits)
                            if new != lold:
                                rows.append((num, lold, new, ref))
                                out[ti] = new
                    else:                      # 双语模式：统一每个 cue 的首中文行
                        new = _replace_report(old, term_pairs, term_chars, hits)
                        for crx, wrong, right in _CONTEXT_COMPILED:
                            if wrong in new and crx.search(ref_m):
                                new = _ctx_replace(new, wrong, right)
                        # 负向排除（EXCLUDE_CONTEXT）：高歧义词被替换后，若参考行命中
                        # 排除正则（如 thank you/written tent 语境），回滚该替换并从命中统计移除
                        for wrong, (right, rxs) in _EXCLUDE_COMPILED.items():
                            if wrong in old and wrong not in new and any(rx.search(ref_m) for rx in rxs):
                                new = new.replace(right, wrong)
                                hits.pop(wrong, None)
                        new = _replace_report(new, word_pairs, word_chars, {})  # WORD_MAP 命中不计入统计
                        if new != old:
                            rows.append((num, old, new, ref))
                            out[zh_idx] = new
                i = kk
                continue
        i += 1

    if out_path:
        body = "\n".join(out)
        if crlf:
            body = body.replace("\n", "\r\n")
        data = ("\ufeff" if bom else "") + body
        with open(out_path, "w", encoding="utf-8", newline="") as f:
            f.write(data)

    if report_path:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("# 字幕校准对照报告\n\n序号 | 原文中文(机翻) | 校准后中文 | 参考行\n")
            f.write("--- | --- | --- | ---\n")
            for num, old, new, ref in rows:
                f.write(f"`{num}` | {old} | **{new}** | {ref}\n")

    return rows, hits

