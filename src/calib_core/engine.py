# -*- coding: utf-8 -*-
# @version 3.1.6
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
from .data.arcak import ARCAK_TERMS
from .data.ark import AK_JA_TERMS, AK_KO_TERMS, AK_TERMS, PGR_EN_TERMS, WWOC_TERMS
from .data.bilingual import BILINGUAL_TERMS, FFRS_TERMS, WORD_MAP
from .data.endfield import ENDFIELD_BI_TERMS, ENDFIELD_KO_TERMS, ENDFIELD_TERMS
from .data.ja import JA_ENDFIELD_TERMS, JA_PGR_TERMS, JA_TERMS, RETIRED_JA_KEYS
from .data.ko import KO_ASR_TERMS, KO_TERMS, RETIRED_KO_KEYS
from .data.limbus import LIMBUS_TERMS
from .data.misc import EN_LINE_TERM_FIXES, FF14_TERMS, HSR_TERMS, POKEMON_TERMS, REACT_TERMS, ZELDA_TERMS, ZH_ONLY_TERMS
from .data.pbz import PBZ_TERMS
from .data.ssv import SSV_TERMS
from .data.tga import TGA_TERMS
from .data.wwm import WWM_TERMS
from .data.gfl2 import GFL2_TERMS
from .learn import _learned_terms_for_mode
from .data.modes import MODE_REGISTRY
from .modes import endfield_auto_markers
from .replace import _compile_map, _ctx_replace, _replace_report
from .acindex import ModeIndex, replace_serial_ac
from .state import (
    TABLES,
    _AK_CONTEXT_COMPILED, _AK_JA_CONTEXT_COMPILED, _AK_KO_CONTEXT_COMPILED,
    _ARCAK_CONTEXT_COMPILED, _CONTEXT_COMPILED, _ENDFIELD_BI_CONTEXT_COMPILED,
    _ENDFIELD_KO_CONTEXT_COMPILED, _EXCLUDE_COMPILED, _FF14_CONTEXT_COMPILED,
    _FFRS_CONTEXT_COMPILED, _GFL2_CONTEXT_COMPILED, _HSR_CONTEXT_COMPILED,
    _JA_CONTEXT_COMPILED, _JA_ENDFIELD_CONTEXT_COMPILED, _JA_PGR_CONTEXT_COMPILED,
    _KO_ASR_CONTEXT_COMPILED, _KO_CONTEXT_COMPILED, _LIMBUS_CONTEXT_COMPILED,
    _PBZ_CONTEXT_COMPILED, _PGR_EN_CONTEXT_COMPILED, _POKEMON_CONTEXT_COMPILED,
    _REACT_CONTEXT_COMPILED, _SSV_CONTEXT_COMPILED, _TGA_CONTEXT_COMPILED,
    _WW40IGN_CONTEXT_COMPILED, _WW40KO_CONTEXT_COMPILED, _WWM_CONTEXT_COMPILED,
    _WWOC_CONTEXT_COMPILED,
)
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



def _restore_override_prefix(old, new):
    """侧车整行覆盖时保留原行的 >> 前缀形态（'>> ' / '>>' / 无前缀）。

    2026-11-19 鸣潮 3.8 终章片（--wuwa38h）：481 条旁白带 >>，侧车不必重复写前缀，
    由被覆盖行的原形态决定补法；若侧车自带前缀先剥离，避免生成 '>> >> xxx'。
    """
    if new.startswith(">> "):
        new = new[3:]
    elif new.startswith(">>"):
        new = new[2:]
    if old.startswith(">> "):
        return ">> " + new
    if old.startswith(">>"):
        return ">>" + new
    return new


def _resolve_terms(mode):
    """按注册表解析模式术语表。akja=AK_TERMS∪AK_JA_TERMS 合并表、pgr=空表为特例；
    未知模式落 BILINGUAL_TERMS（与原 else 分支一致）。表对象取自 state.TABLES。"""
    spec = MODE_REGISTRY.get(mode)
    tname = spec["terms"] if spec else "BILINGUAL_TERMS"
    if tname == "__AKJA_MERGE__":
        # 合并而非链式跑两遍：两遍会让第一遍产出被第二遍短键二次命中；
        # 合并成一张表后由 _compile_map 键长降序单遍扫描兜住（同名键以 AK_JA_TERMS 为准）。
        merged = dict(AK_TERMS)
        merged.update(AK_JA_TERMS)
        return merged
    if tname == "__EMPTY__":
        return {}
    if not tname:
        return BILINGUAL_TERMS
    return TABLES[tname]


# 版式分发：首中文行模式（规则版式）由注册表自动归类，特例模式单独分支处理。
#   新增一个「首中文行 + 语境锚定」片源模式 = 注册表加一条（terms/ctx），引擎自动走通用路径。
_SPECIAL_MODES = {"bi", "pgr", "ko", "wuwa40ko", "wuwa40ign", "ak", "arcak", "endo", "fix-en"}
_FIRST_ZH_MODES = {m for m in MODE_REGISTRY if m not in _SPECIAL_MODES}
_FIRST_ZH_EXCLUDE = {"pgren"}        # 首中文行模式里消费 EXCLUDE 回滚层的
_FIRST_ZH_OVERRIDE = {"wwm", "ja"}   # 首中文行模式里支持侧车整行覆盖的（ja：4.0 先行映像全片侧车）

# 语境表名 → 预编译缓存（与 state._CTX_COMPILE_SPEC 同源；供注册表 ctx 字段查缓存）
_COMPILED_BY_CTX = {
    "CONTEXT_MAP": _CONTEXT_COMPILED,
    "JA_CONTEXT": _JA_CONTEXT_COMPILED,
    "JA_ENDFIELD_CONTEXT": _JA_ENDFIELD_CONTEXT_COMPILED,
    "JA_PGR_CONTEXT": _JA_PGR_CONTEXT_COMPILED,
    "AK_CONTEXT": _AK_CONTEXT_COMPILED,
    "AK_JA_CONTEXT": _AK_JA_CONTEXT_COMPILED,
    "AK_KO_CONTEXT": _AK_KO_CONTEXT_COMPILED,
    "KO_CONTEXT": _KO_CONTEXT_COMPILED,
    "WW40KO_CONTEXT": _WW40KO_CONTEXT_COMPILED,
    "WW40IGN_CONTEXT": _WW40IGN_CONTEXT_COMPILED,
    "KO_ASR_CONTEXT": _KO_ASR_CONTEXT_COMPILED,
    "REACT_CONTEXT": _REACT_CONTEXT_COMPILED,
    "LIMBUS_CONTEXT": _LIMBUS_CONTEXT_COMPILED,
    "FFRS_CONTEXT": _FFRS_CONTEXT_COMPILED,
    "HSR_CONTEXT": _HSR_CONTEXT_COMPILED,
    "POKEMON_CONTEXT": _POKEMON_CONTEXT_COMPILED,
    "WWOC_CONTEXT": _WWOC_CONTEXT_COMPILED,
    "PBZ_CONTEXT": _PBZ_CONTEXT_COMPILED,
    "FF14_CONTEXT": _FF14_CONTEXT_COMPILED,
    "PGR_EN_CONTEXT": _PGR_EN_CONTEXT_COMPILED,
    "SSV_CONTEXT": _SSV_CONTEXT_COMPILED,
    "TGA_CONTEXT": _TGA_CONTEXT_COMPILED,
    "ARCAK_CONTEXT": _ARCAK_CONTEXT_COMPILED,
    "WWM_CONTEXT": _WWM_CONTEXT_COMPILED,
    "GFL2_CONTEXT": _GFL2_CONTEXT_COMPILED,
    "ENDFIELD_KO_CONTEXT": _ENDFIELD_KO_CONTEXT_COMPILED,
    "ENDFIELD_BI_CONTEXT": _ENDFIELD_BI_CONTEXT_COMPILED,
}


def _first_zh_ctx(mode):
    """首中文行模式的语境缓存（注册表 ctx 字段查表；None/无槽 → 空表，即纯术语替换）。"""
    return _COMPILED_BY_CTX.get(MODE_REGISTRY[mode]["ctx"]) or []


def _calib_first_zh(old, ref_m, ctx_compiled, term_idx, hits,
                    num, ref, out, zh_idx, rows,
                    exclude=False, bi_override=None, bi_override_preserve=False):
    """规则「首中文行」版式：术语替换 + 语境锚定（ref_m）+ 可选 EXCLUDE 回滚 + 可选侧车覆盖。

    统一 react/hsr/ff14/pkm/limbus/ffrs/pbz/ssv/tga26/wwoc/pgren/zel/ja/jpe/pgrja/
    akja/akko/wwm/gfl2/zho/endobi/endoko 等模式（仅 ctx 缓存与 exclude/override 旗标不同）。
    侧车命中即整行覆盖（不叠加术语表）；否则术语+ctx，exclude 模式再按参考行回滚高歧义词。
    """
    if bi_override and str(num) in bi_override:
        new = bi_override[str(num)]
        if bi_override_preserve:
            new = _restore_override_prefix(old, new)
    else:
        new = replace_serial_ac(old, term_idx, hits)
        for crx, wrong, right in ctx_compiled:
            if wrong in new and crx.search(ref_m):
                new = _ctx_replace(new, wrong, right)
        if exclude:
            for wrong, (right, rxs) in _EXCLUDE_COMPILED.items():
                if wrong in old and wrong not in new and any(rx.search(ref_m) for rx in rxs):
                    new = new.replace(right, wrong)
                    hits.pop(wrong, None)
    if new != old:
        rows.append((num, old, new, ref))
        out[zh_idx] = new


def process(path, out_path=None, report_path=None, mode="bi",
            fix_en=False, pgr_override=None, learned_kb=None, bi_override=None,
            bi_override_preserve=False, ko_override=None, ko_override_preserve=False,
            zh_first=False):
    """对 SRT 校准。返回 (改动行rows, 术语命中hits)。
      zh_first=True 强制「首文本行=中文、其余=参考行」，供版式已知的双语片源
                  跳过语言探测（2026-11-21 全短片片：英文参考行 "Jan。" 含全角句号，
                  被 _split_cue_text 的纯拉丁中文行兜底误判成中文，导致侧车写错行）。
      mode="bi"   双语模式：BILINGUAL_TERMS + CONTEXT_MAP + WORD_MAP 改首中文行。
      mode="ko"   韩语模式：KO_TERMS 统一中文行术语。
      mode="wuwa40ko" 韩语原声·鸣潮 4.0 新联邦 PV：KO_TERMS + WW40KO_CONTEXT，
                  命中侧车时整行覆盖（侧车已是终稿，含 >> 前缀）。
      mode="wuwa40ign" 韩语原声·鸣潮 4.0 IGN 实机演示：KO_TERMS + WW40IGN_CONTEXT，
                  与 wuwa40ko 同构；侧车 162 条为终稿，命中即整行覆盖。
      mode="ja"   日语模式：JA_TERMS + JA_CONTEXT（日语参考行佐证）统一中文行术语。
      mode="endo" 终末地模式：ENDFIELD_TERMS 统一全部文本行。
      mode="ak"   明日方舟本体模式：AK_TERMS + AK_CONTEXT（英文参考行佐证）统一**全部**中文行。
                  2026-10-14 起：谷翻片「中文2行+英文2行」结构下逐行校准全部含汉字行，
                  ctx 锚点=该 cue 全部英文行拼接（规整空白）；不含汉字的文本行一律不动。
      mode="jpe"  日语原声·终末地：JA_ENDFIELD_TERMS + JA_ENDFIELD_CONTEXT（日语行佐证）。
      mode="pgrja" 日语原声·战双（联动朗读直播片）：JA_PGR_TERMS + JA_PGR_CONTEXT。
                  这类片**中文是原文、日语是日服译本**，参考行是日语所以不进 fix_en 允许集。
      mode="akja" 日语原声·明日方舟：terms = AK_TERMS ∪ AK_JA_TERMS（合并后单次编译、
                  长键降序单遍扫描），只改首中文行，AK_JA_CONTEXT 用**日语参考行**佐证。
                  2026-11-03 新增（奈渡ナオト《明日方舟》首播 3856 cue / 每 cue 恰 2 行）。
                  与 --ak 的分工：AK_TERMS 只收会在**英语原声片**出现的错形；日语向错形
                  （音译串/同音汉字误听/旧字体直搬）进 AK_JA_TERMS；正常中文词的官方名
                  （天灾->斯卡蒂、标志->逻各斯、喇叭->号角、团聚->整合运动…）一律只做
                  语境锚定，绝不进任何裸键表。
      mode="zho"  中文行专属模式：ZH_ONLY_TERMS 只改首中文行英文噪音（不动英文/参考行）。
      fix_en=True   双语版式模式（bi / ff14）下用 EN_ASR_SPLIT_FIXES + EN_LINE_TERM_FIXES
                    修正英文/参考行（默认不动）。2026-11-01 起 --ff14 也可搭配 --fix-en。
    参考行锚定（CONTEXT/EXCLUDE）一律先经 _ref_for_match 规整（ASR 断词容错），
    但默认输出的参考行保持原样，只有 fix_en=True 才写回。
    """
    terms = _resolve_terms(mode)
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
    if mode in ("ko", "wuwa40ko", "wuwa40ign") and any(k in terms for k in RETIRED_KO_KEYS):
        terms = {k: v for k, v in terms.items() if k not in RETIRED_KO_KEYS}
    # 2026-10-14 日语同款闸门：'笛卡尔' 会在运行期被 applied.json 复活，必须一并剔除，
    #   否则它抢跑 Entity("卡提希娅") 的 ctx（笛卡尔西亚 -> 卡提希娅西亚）。
    if mode == "ja" and any(k in terms for k in RETIRED_JA_KEYS):
        terms = {k: v for k, v in terms.items() if k not in RETIRED_JA_KEYS}
    # 术语表经 ModeIndex 组装 AC 自动机（term_idx，见下），逐行替换走 replace_serial_ac 预筛串行。
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
            print("片源自适应：检测到终末地双语片源（特征词 %d 个：%s）→ 已并入 ENDFIELD_BI_TERMS"
                  % (len(_mk), "、".join(_mk[:6])))

    # M2 对象索引：AC 预筛串行等价替换（replace_serial_ac 与 _replace_report 逐字节+hits 等价，
    #   级联回退保零漂移）。term_idx 用最终 terms（含学习注入/retired 闸门/片源自适应）。
    term_idx = ModeIndex(mode, terms)
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
                    if zh_first and len(text_tis) >= 2:
                        zh_pos, ref_pos = [0], list(range(1, len(text_tis)))
                    else:
                        zh_pos, ref_pos = _split_cue_text([lines[ti] for ti in text_tis])
                    zh_idx = text_tis[zh_pos[0]] if zh_pos else j + 1
                    ref = lines[text_tis[ref_pos[-1]]] if ref_pos else lines[kk - 1]
                    if mode != "endo" and kk - 1 == j + 1:
                        # 单文本行 cue：该行即参考行（无独立中文行）。
                        # 例外（2026-10-12）：--ko 纯韩语片源（韩国主播直播 ASR，每 cue
                        # 单行韩语）——该行含谚文即应用 KO_ASR 层（韩语错形→官方韩语），
                        # 否则整块跳过，防止把术语替换误写到参考/英文行上。
                        only = lines[j + 1]
                        if mode in ("ko", "wuwa40ko", "wuwa40ign") and _KO_HANGUL.search(only):
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
                        # 多文本行且无法识别中文行（全拉丁/全参考行）：绝不写参考行。
                        # 例外：bi/--wuwa40ko/--wuwa40ja 侧车显式指定的 cue 允许整行覆盖——
                        #   4.0 韩语片 #8/#241 原行是拉丁残片（Subde / Dream），
                        #   4.0 日语片 #487/#1012/#1065/#1074 原行是纯拉丁/纯数字（无 CJK，
                        #   识别不出中文行），人工终稿已改成中文，若不特判会被这里整块跳过。
                        if mode in ("bi", "ja", "wuwa40ko", "wuwa40ign"):
                            ov = bi_override if mode in ("bi", "ja") else ko_override
                            preserve = (bi_override_preserve if mode == "bi"
                                        else ko_override_preserve)
                            if ov and str(num) in ov:
                                old0 = lines[zh_idx]
                                new = ov[str(num)]
                                if preserve:
                                    new = _restore_override_prefix(old0, new)
                                if new != old0:
                                    rows.append((num, old0, new, ref))
                                    out[zh_idx] = new
                        i = kk
                        continue
                    old = lines[zh_idx]
                    if fix_en and mode in ("bi", "ff14"):  # --fix-en：修正英文/参考行术语（双语版式模式）
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
                    elif mode in _FIRST_ZH_MODES:
                        # 规则「首中文行」版式统一路径（ctx/exclude/override 由注册表+旗标集驱动）
                        _calib_first_zh(old, ref_m, _first_zh_ctx(mode), term_idx,
                                        hits, num, ref, out, zh_idx, rows,
                                        exclude=mode in _FIRST_ZH_EXCLUDE,
                                        bi_override=bi_override if mode in _FIRST_ZH_OVERRIDE else None,
                                        bi_override_preserve=bi_override_preserve)
                    elif mode in ("ko", "wuwa40ko", "wuwa40ign"):       # 韩语原声·鸣潮：KO_TERMS + KO_CONTEXT/WW40KO_CONTEXT 校准**全部中文行**
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
                            # 4.0 韩语片 #154 原行两行都是「얜」，人工终稿把首行改成
                            # 「她」；侧车命中时先整行覆盖首行，再走 KO_ASR/continue。
                            if (mode in ("wuwa40ko", "wuwa40ign") and ko_override
                                    and str(num) in ko_override):
                                old0 = lines[kr_tis[0]]
                                new = ko_override[str(num)]
                                if ko_override_preserve:
                                    new = _restore_override_prefix(old0, new)
                                if new != old0:
                                    rows.append((num, old0, new, ref))
                                    out[kr_tis[0]] = new
                                i = kk
                                continue
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
                        ctx_compiled = (_WW40IGN_CONTEXT_COMPILED if mode == "wuwa40ign"
                                        else _WW40KO_CONTEXT_COMPILED if mode == "wuwa40ko"
                                        else _KO_CONTEXT_COMPILED)
                        for zi, ti in enumerate(zh_tis):
                            if len(zh_tis) == len(kr_tis):
                                anchor = _ref_for_match(lines[kr_tis[zi]])   # 逐行配对佐证
                            else:
                                anchor = kr_all                              # 行数不齐回退拼接
                            lold = lines[ti]
                            if (mode in ("wuwa40ko", "wuwa40ign") and ko_override
                                    and zi == 0 and str(num) in ko_override):
                                # 4.0 侧车：命中即整行覆盖，不叠加术语表（终稿可能刻意保留
                                #   拉丁名/口语重复/断句）；侧车已是终稿，含原行 >> 前缀。
                                new = ko_override[str(num)]
                                if ko_override_preserve:
                                    new = _restore_override_prefix(lold, new)
                            else:
                                new = replace_serial_ac(lold, term_idx, hits)
                                for crx, wrong, right in ctx_compiled:
                                    if wrong in new and crx.search(anchor):
                                        new = _ctx_replace(new, wrong, right)
                                # 2026-11-21 3.8 韩语主线二校：ko 分支补负向排除，
                                #   与 bi/pgren 同构（방송 直播/广播、수호시 守护城/神市、
                                #   별자리 心/星座 等歧义词按韩文参考行回滚）。
                                for wrong, (right, rxs) in _EXCLUDE_COMPILED.items():
                                    if wrong in lold and wrong not in new \
                                            and any(rx.search(anchor) for rx in rxs):
                                        new = new.replace(right, wrong)
                                        hits.pop(wrong, None)
                            if new != lold:
                                rows.append((num, lold, new, ref))
                                out[ti] = new
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
                                new = replace_serial_ac(lold, term_idx, hits)
                                for crx, wrong, right in _AK_CONTEXT_COMPILED:
                                    if wrong in new and crx.search(ak_anchor):
                                        new = _ctx_replace(new, wrong, right)
                                # 2026-11-02：ak 分支补「负向排除回滚」，与 bi 分支同一层同构。
                                #   此前 EXCLUDE 只在 bi 生效，但 --ak 同样会被学习库注入高歧义中文词
                                #   （EP17 反应片实测：岁主/英白拉多 串档），错了就无从撤销。
                                for wrong, (right, rxs) in _EXCLUDE_COMPILED.items():
                                    if wrong in lold and wrong not in new \
                                            and any(rx.search(ak_anchor) for rx in rxs):
                                        new = new.replace(right, wrong)
                                        hits.pop(wrong, None)
                                if new != lold:
                                    rows.append((num, lold, new, ref))
                                    out[_ti] = new
                        elif ak_zh:             # 无参考行的纯中文 cue：退回首中文行口径
                            new = replace_serial_ac(old, term_idx, hits)
                            if new != old:
                                rows.append((num, old, new, ref))
                                out[zh_idx] = new
                    elif mode == "arcak":       # Arcaea×明日方舟联动直播：ARCAK_TERMS + ARCAK_CONTEXT
                        # 2026-11-18 新增。与 --ak 同构（改全部中文行、锚点=全部英文行拼接、
                        #   消费 EXCLUDE 回滚），但走独立表：AK_TERMS 里的
                        #   Arcaea→韵律源点 / Radiant→《Radiant》与本片「Arcaea 侧保留英文」
                        #   口径冲突，不能合并。
                        arcak_zh = [text_tis[p] for p in zh_pos]
                        arcak_en = [text_tis[p] for p in ref_pos]
                        if arcak_zh and arcak_en:
                            arcak_anchor = re.sub(
                                r"\s+", " ",
                                _ref_for_match(" ".join(lines[_ti] for _ti in arcak_en)))
                            for _ti in arcak_zh:
                                lold = lines[_ti]
                                if bi_override and str(num) in bi_override and _ti == zh_idx:
                                    # 2026-11-19：歌词向短片逐 cue 侧车整行覆盖
                                    # （--arcakamiya）。命中即用终稿，不叠加术语表，
                                    # 保证侧车与人工成品逐字节一致。
                                    new = bi_override[str(num)]
                                else:
                                    new = replace_serial_ac(lold, term_idx, hits)
                                    for crx, wrong, right in _ARCAK_CONTEXT_COMPILED:
                                        if wrong in new and crx.search(arcak_anchor):
                                            new = _ctx_replace(new, wrong, right)
                                    for wrong, (right, rxs) in _EXCLUDE_COMPILED.items():
                                        if wrong in lold and wrong not in new \
                                                and any(rx.search(arcak_anchor) for rx in rxs):
                                            new = new.replace(right, wrong)
                                            hits.pop(wrong, None)
                                if new != lold:
                                    rows.append((num, lold, new, ref))
                                    out[_ti] = new
                        elif arcak_zh:          # 无参考行的纯中文 cue：退回首中文行口径
                            new = replace_serial_ac(old, term_idx, hits)
                            if new != old:
                                rows.append((num, old, new, ref))
                                out[zh_idx] = new
                    elif mode == "endo":       # 终末地模式：ENDFIELD_TERMS 统一全部中文行
                        # 2026-10-23：改为只改中文行；单语终末地片源等价于原“全部文本行”，
                        # 双语片源不会再误改英文参考行（应改用 --endobi）。
                        for ti in [text_tis[p] for p in zh_pos]:
                            lold = lines[ti]
                            new = replace_serial_ac(lold, term_idx, hits)
                            if new != lold:
                                rows.append((num, lold, new, ref))
                                out[ti] = new
                    else:                      # 双语模式：统一每个 cue 的首中文行
                        if bi_override and str(num) in bi_override:
                            # 逐 cue 侧车整行覆盖（高歧义、规则无法精确处理的一次性 cue，
                            # 如 cue255/2389）：直接用终稿，不叠加术语表，零跨片风险
                            new = bi_override[str(num)]
                            if bi_override_preserve:
                                new = _restore_override_prefix(old, new)
                            if new != old:
                                rows.append((num, old, new, ref))
                                out[zh_idx] = new
                        else:
                            new = replace_serial_ac(old, term_idx, hits)
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

