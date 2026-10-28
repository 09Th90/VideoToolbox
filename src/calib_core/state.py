# -*- coding: utf-8 -*-
# @version 2.8.0
"""术语表注册表、实体投影与上下文缓存

源：subtitle_calib_merged.py L2198-L10667 @ 97d7d463（2026-10-24 冻结快照）
"""
import io
import os
import re
import shutil
import sys
import unicodedata
from .data.ark import (AK_CONTEXT, AK_KO_CONTEXT, AK_KO_TERMS, AK_TERMS,
                       PGR_EN_TERMS, WWOC_CONTEXT, WWOC_TERMS)
from .data.bilingual import (BILINGUAL_TERMS, CONTEXT_MAP, EXCLUDE_CONTEXT,
                             FFRS_CONTEXT, FFRS_TERMS, WORD_MAP)
from .data.endfield import (ENDFIELD_BI_CONTEXT, ENDFIELD_BI_TERMS,
                            ENDFIELD_KO_CONTEXT, ENDFIELD_KO_TERMS,
                            ENDFIELD_TERMS)
from .data.entities import ENTITIES
from .data.ja import (JA_CONTEXT, JA_ENDFIELD_CONTEXT, JA_ENDFIELD_TERMS,
                      JA_TERMS)
from .data.ko import (KO_ASR_CONTEXT, KO_ASR_TERMS, KO_CONTEXT, KO_TERMS)
from .data.limbus import LIMBUS_CONTEXT, LIMBUS_TERMS
from .data.misc import (EN_LINE_TERM_FIXES, HSR_CONTEXT, HSR_TERMS,
                        POKEMON_CONTEXT, POKEMON_TERMS, REACT_CONTEXT,
                        REACT_TERMS, ZELDA_TERMS, ZH_ONLY_TERMS)
from .data.modes import _MODE_CTX_TABLE, _MODE_TERM_TABLE


# 扁平术语表注册表：顺序沿用原文件定义顺序，供 terms-check / kb-sync 扫描。
TABLES = {
    "BILINGUAL_TERMS": BILINGUAL_TERMS,
    "WORD_MAP": WORD_MAP,
    "JA_TERMS": JA_TERMS,
    "JA_ENDFIELD_TERMS": JA_ENDFIELD_TERMS,
    "WWOC_TERMS": WWOC_TERMS,
    "KO_TERMS": KO_TERMS,
    "PGR_EN_TERMS": PGR_EN_TERMS,
    "ENDFIELD_TERMS": ENDFIELD_TERMS,
    "ENDFIELD_BI_TERMS": ENDFIELD_BI_TERMS,
    "ENDFIELD_KO_TERMS": ENDFIELD_KO_TERMS,
    "AK_TERMS": AK_TERMS,
    "AK_KO_TERMS": AK_KO_TERMS,
    "KO_ASR_TERMS": KO_ASR_TERMS,
    "ZH_ONLY_TERMS": ZH_ONLY_TERMS,
    "REACT_TERMS": REACT_TERMS,
    "HSR_TERMS": HSR_TERMS,
    "POKEMON_TERMS": POKEMON_TERMS,
    "EN_LINE_TERM_FIXES": EN_LINE_TERM_FIXES,
    "ZELDA_TERMS": ZELDA_TERMS,
    "LIMBUS_TERMS": LIMBUS_TERMS,
    "FFRS_TERMS": FFRS_TERMS,
}

# 上下文表注册表：包含未接入 _MODE_CTX_TABLE 的 REACT/HSR/KO_ASR 三张。
CTX_TABLES = {
    "CONTEXT_MAP": CONTEXT_MAP,
    "ENDFIELD_BI_CONTEXT": ENDFIELD_BI_CONTEXT,
    "ENDFIELD_KO_CONTEXT": ENDFIELD_KO_CONTEXT,
    "JA_CONTEXT": JA_CONTEXT,
    "JA_ENDFIELD_CONTEXT": JA_ENDFIELD_CONTEXT,
    "AK_CONTEXT": AK_CONTEXT,
    "AK_KO_CONTEXT": AK_KO_CONTEXT,
    "KO_CONTEXT": KO_CONTEXT,
    "KO_ASR_CONTEXT": KO_ASR_CONTEXT,
    "REACT_CONTEXT": REACT_CONTEXT,
    "HSR_CONTEXT": HSR_CONTEXT,
    "POKEMON_CONTEXT": POKEMON_CONTEXT,
    "WWOC_CONTEXT": WWOC_CONTEXT,
    "LIMBUS_CONTEXT": LIMBUS_CONTEXT,
    "FFRS_CONTEXT": FFRS_CONTEXT,
}


# =============================================================
# 2026-09-09 I_Was_Wrong_Completely_About_Wuthering_Waves（鸣潮 椿伴星任务 Reaction 片）校准总结
#   片源：I_Was_Wrong_Completely_About_Wuthering_Waves_en_auto.srt（中英双语，1315 cues）
#   模式：bi。78 处中文行改动，序号/时间轴/参考行/空行/换行/BOM 原样保留。
#   错误形式 -> 正确形式（对照，均依官方名/原文修正，已入 BILINGUAL_TERMS/CONTEXT_MAP）：
#     罗孚/路虎/漫游者/Ruva/Ruver/鲁瓦/鲁弗 -> 漂泊者（Rover ASR 变体）
#     岸边管理员/海岸警卫队/海岸守护者/做空者/岸守/肖战守护者/Shawkeeper -> 守岸人（Shorekeeper）
#     Chamellia/Chameleia/Chamelia/Camila/卡米拉/茶花属/茶花/变色龙 -> 椿（Camellya，黑海岸执花）
#     布隆伯/布卢姆伯/绽放者 -> 执花（Bloombearer，黑海岸成员称号）
#     塔塞特(人)/Tacet 不和 -> 残象（Tacet Discord）
#     Tethus/teth系统 -> 泰缇斯（Tethys 系统，守岸人辅助的运算核心）
#     斯特拉矩阵 -> 恒星矩阵（Stellar Matrix）
#     布莱克酒店/黑色海岸/黑岸/布莱克的领导者 -> 黑海岸（Black Shores）
#     Wolvering Waves/翼波 -> 鸣潮（Wuthering Waves ASR 误听）
#   [手动修复] ERROR 占位 3 处（#740/#916/#1181）按参考行补译；#515 布莱克绽放=黑花(Black blooms)；
#   #9 上集回顾 翼波->《鸣潮》；#704/#707/#708/#1144 黑海岸跨行断句理顺；#1287 TVA=时间变异管理局。
#   [不确定项] ①Aalto(#13 阿尔托)官方中文名待核(疑阿托)；②Enrew(#20 恩鲁)疑 Encore 安可，未改；
#   ③Beatrice(#532/#534/#1180) 音译 比阿特丽斯 待官方核实；④Pedalfall Village 官方译名未知，保留音译；
#   ⑤stellar matrix 官方译名待核(暂用 恒星矩阵)；⑥forte=强项、rebel test=反叛者测试 官方术语待核；
#   ⑦aerosel=气溶胶、Blasar=布拉萨尔、Eden=伊登、Yugi=勇利、梅伊(mey) 等玩梗/歌词按音译保留。
#   二次校准（检索官方中文后，累计 88 处）：
#     恩鲁/Enrew -> 安可（Encore，黑海岸客卿，官方）
#     踏板落村/Pedalfall(Village)/Pedaphor村/Petal Fall -> 落香村（椿被救村庄，官方依鸣潮助手图鉴/剧情）
#     死灵星/Necrostar -> 噬亡星（黑海岸黑洞，官方依库街区 wiki）
#     调制大厅/modulation hall -> 调律大厅（黑海岸设施，官方依库街区 wiki）
#   [二次校准确认无误] Aalto=阿尔托（Theria 中文指南），不改；泰缇斯(Tethys) 确认。
# =============================================================

# =============================================================
# 256 2026-09-08 WW 2.7 Story Quest Highlight（gacha reaction）校准总结
#   片源：【字幕】I cannot believe this is a gacha game - WW 2.7
#   模式：bi（中英双语）。51+ 处文本改动，序号/时间轴/空行/换行/BOM 原样保留。
#   错误形式 -> 正确形式（对照）：
#     基督波弗罗/克里斯托弗罗 -> 克里斯托弗   (Christophoro 各变体)
#     坎特雷拉/卡内拉/卡内雷拉/卡内利拉/康特拉/卡提拉/卡蒂/克特雷拉
#                           -> 坎特蕾拉       (Cantarella=坎特蕾拉·翡萨烈)
#     利维坦                  -> 利维亚坦       (Leviathan=2.7 鸣式 BOSS)
#     漫游者/漫游车/罗孚/罗弗 -> 漂泊者         (Rover)
#     阳阳                    -> 秧秧           (Yangyang)
#     蒙特利斯                -> 莫塔里         (Montelli=珂莱塔·莫塔里家族)
#     靖州/荆乔                -> 今州           (Jingjo/Jing Joe)
#     天使                    -> 安吉尔         (Angel 角色名；参考行为 Angel 时)
#     谐振器                  -> 共鸣者         (Resonator 官方译名)
#     疤痕                    -> 伤痕           (Scar 角色；拉链人)
#     原真                    -> 原神           (Genshin)
#     Wua/瓦阿                -> 鸣潮           (主播对 WuWa 的昵称)
#   [二期对照；2026-09-08 二次校准，检索官方中文后统一] 共 61 处
#     waifu 佐证 外婆->老婆；Frover 佐证 弗漂泊者->弗罗弗(自动救回 BILINGUAL 误伤,不再人工)
#     Abby/Aby 佐证 艾比->阿布（官方名，真名阿布拉克萨斯）；Abbyus/Abrais 佐证 阿布雷斯->阿布拉克萨斯
#     Septimont 佐证 塞普蒂蒙->七丘；Lupa/Lup 佐证 卢帕/卢普->露帕
#   [不确定项] ①Ginshi->今汐(#221,主播口音,疑为 Jinhsi)；②Trinodian/Throdian/Sorodians
#   阵营名音译不一(疑鸣式阵营,无官方对应),保留音译未统一；③"索罗狄安""弗罗弗和莫尔"等主播自造词按音译保留。
#   已解决边界：BILINGUAL"罗弗"->漂泊者 对"弗罗弗"的子串误伤，已用 CONTEXT_MAP Frover->弗罗弗 自动兜底。
# =============================================================

# 预编译上下文规则：正则只编译一次，占位规则(wrong/right 为 None)剔除；
# 应用时先查 wrong 是否出现在中文行，再跑正则，避免无谓匹配。
_CONTEXT_COMPILED = [(re.compile(rx, re.I), wrong, right)
                     for rx, wrong, right in CONTEXT_MAP if wrong and right]

_EXCLUDE_COMPILED = {w: (right, [re.compile(rx, re.I) for rx in rxs])
                     for w, (right, rxs) in EXCLUDE_CONTEXT.items()}

_JA_CONTEXT_COMPILED = [(re.compile(rx), wrong, right) for rx, wrong, right in JA_CONTEXT]

_JA_ENDFIELD_CONTEXT_COMPILED = [(re.compile(rx), wrong, right) for rx, wrong, right in JA_ENDFIELD_CONTEXT]

_AK_CONTEXT_COMPILED = [(re.compile(rx, re.I), wrong, right) for rx, wrong, right in AK_CONTEXT]

_AK_KO_CONTEXT_COMPILED = [(re.compile(rx), wrong, right) for rx, wrong, right in AK_KO_CONTEXT]

_KO_CONTEXT_COMPILED = [(re.compile(rx), wrong, right) for rx, wrong, right in KO_CONTEXT]

_KO_ASR_CONTEXT_COMPILED = [(re.compile(rx), wrong, right) for rx, wrong, right in KO_ASR_CONTEXT]

_REACT_CONTEXT_COMPILED = [(re.compile(rx, re.I), wrong, right)
                           for rx, wrong, right in REACT_CONTEXT if wrong and right]

_LIMBUS_CONTEXT_COMPILED = [(re.compile(rx, re.I), wrong, right)
                             for rx, wrong, right in LIMBUS_CONTEXT if wrong and right]

_FFRS_CONTEXT_COMPILED = [(re.compile(rx, re.I), wrong, right)
                          for rx, wrong, right in FFRS_CONTEXT if wrong and right]

_HSR_CONTEXT_COMPILED = [(re.compile(rx, re.I), wrong, right)
                         for rx, wrong, right in HSR_CONTEXT if wrong and right]

_POKEMON_CONTEXT_COMPILED = [(re.compile(rx, re.I), wrong, right)
                             for rx, wrong, right in POKEMON_CONTEXT if wrong and right]

_WWOC_CONTEXT_COMPILED = [(re.compile(rx, re.I), wrong, right)
                          for rx, wrong, right in WWOC_CONTEXT if wrong and right]



def _register_entities(entities=ENTITIES):
    """把 ENTITIES 投影进扁平表，并重建正则缓存（import 时执行一次）。

    幂等：变体键已存在且目标一致 -> 跳过；目标不一致 -> 报错（新旧知识冲突）。
    """
    for e in entities:
        for m in e.modes:
            tname = _MODE_TERM_TABLE.get(m)
            if tname and e.variants:
                tbl = TABLES[tname]
                for v in e.variants:
                    if v in tbl and tbl[v] != e.canonical:
                        raise SystemExit(
                            f"ENTITIES 注册冲突：变体 {v!r} 在 {tname} 已映射 "
                            f"{tbl[v]!r}，实体要求 {e.canonical!r}")
                    tbl.setdefault(v, e.canonical)
            cname = _MODE_CTX_TABLE.get(m)
            if cname and e.ctx:
                lst = CTX_TABLES[cname]
                for rx, wrong in e.ctx:
                    if not any(r == rx and w == wrong and rt == e.canonical
                               for r, w, rt in lst):
                        lst.append((rx, wrong, e.canonical))
        if e.exclude:
            exc = EXCLUDE_CONTEXT
            for v in e.variants:
                if v in exc:
                    right, rxs = exc[v]
                    exc[v] = (right, tuple(rxs) + tuple(
                        r for r in e.exclude if r not in rxs))
                else:
                    exc[v] = (e.canonical, tuple(e.exclude))



_ENDFIELD_KO_CONTEXT_COMPILED = [
    (re.compile(rx), wrong, right) for rx, wrong, right in ENDFIELD_KO_CONTEXT
]


_ENDFIELD_BI_CONTEXT_COMPILED = [
    (re.compile(rx, re.I), wrong, right) for rx, wrong, right in ENDFIELD_BI_CONTEXT
]



def _rebuild_context_caches():
    """实体注册可能追加 CONTEXT/EXCLUDE 条目，重建各预编译缓存。

    缓存必须原地更新：engine/其他模块在 import 时已持有这些 list/dict 的引用，
    重新绑定会让 kb-sync 运行期注入静默失效。
    """
    _CONTEXT_COMPILED[:] = [(re.compile(rx, re.I), wrong, right)
                            for rx, wrong, right in CONTEXT_MAP if wrong and right]
    _EXCLUDE_COMPILED.clear()
    _EXCLUDE_COMPILED.update(
        {w: (right, [re.compile(rx, re.I) for rx in rxs])
         for w, (right, rxs) in EXCLUDE_CONTEXT.items()})
    _JA_CONTEXT_COMPILED[:] = [(re.compile(rx), wrong, right) for rx, wrong, right in JA_CONTEXT]
    _JA_ENDFIELD_CONTEXT_COMPILED[:] = [(re.compile(rx), wrong, right)
                                        for rx, wrong, right in JA_ENDFIELD_CONTEXT]
    _AK_KO_CONTEXT_COMPILED[:] = [(re.compile(rx), wrong, right) for rx, wrong, right in AK_KO_CONTEXT]
    _KO_CONTEXT_COMPILED[:] = [(re.compile(rx), wrong, right) for rx, wrong, right in KO_CONTEXT]
    _AK_CONTEXT_COMPILED[:] = [(re.compile(rx, re.I), wrong, right) for rx, wrong, right in AK_CONTEXT]
    _ENDFIELD_KO_CONTEXT_COMPILED[:] = [(re.compile(rx), wrong, right)
                                        for rx, wrong, right in ENDFIELD_KO_CONTEXT]
    _ENDFIELD_BI_CONTEXT_COMPILED[:] = [(re.compile(rx, re.I), wrong, right)
                                        for rx, wrong, right in ENDFIELD_BI_CONTEXT]
    _HSR_CONTEXT_COMPILED[:] = [(re.compile(rx, re.I), wrong, right)
                                for rx, wrong, right in HSR_CONTEXT if wrong and right]
    _LIMBUS_CONTEXT_COMPILED[:] = [(re.compile(rx, re.I), wrong, right)
                                   for rx, wrong, right in LIMBUS_CONTEXT if wrong and right]
    _FFRS_CONTEXT_COMPILED[:] = [(re.compile(rx, re.I), wrong, right)
                                 for rx, wrong, right in FFRS_CONTEXT if wrong and right]
    _POKEMON_CONTEXT_COMPILED[:] = [(re.compile(rx, re.I), wrong, right)
                                    for rx, wrong, right in POKEMON_CONTEXT if wrong and right]
    _WWOC_CONTEXT_COMPILED[:] = [(re.compile(rx, re.I), wrong, right)
                                 for rx, wrong, right in WWOC_CONTEXT if wrong and right]



_register_entities()

_rebuild_context_caches()

