# -*- coding: utf-8 -*-
# @version 3.1.5
"""术语/实体数据表

源：subtitle_calib_merged.py L2797-L7340 @ 97d7d463（2026-10-24 冻结快照）
"""
import io
import os
import re
import shutil
import sys
import unicodedata


# =============================================================
# 2. 韩语原声片源资产（原 calib_input_ko_out.py）
#    鸣潮官方韩文译名参见《鸣潮_故事相关专有名词中英日韩对照.md》韩语列
#    （如 残象=잔상、今州=금주、瑝珑=황룡），校准韩语片源新对照时先查该表。
# =============================================================

KO_INFO = {
    "src": r"g:\SOLO工作\input_ko_out.srt",
    "dst": r"g:\SOLO工作\input_ko_out_calib\input_ko_out_已校准.srt",
}


# 2.2 二次元手游 OST 理想型世界杯（韩语原声·综合手游节目）片源资产
# 2026-09-01 沉淀：跨段统一 妮姬/胜利女神->NIKKE、禅心在世->绝区零、蓝档案->蔚蓝档案，
#   以及主播常规口癖/机翻误词。该片源覆盖 崩坏/原神/明日方舟/绝区零/NIKKE/蔚蓝档案/
#   女神异闻录/Limbus/反转移期/国王突袭/歧路旅人 等综合游戏，勿与 KO_TERMS(鸣潮)混用。
# 用法：python subtitle_calib_merged.py <input.srt> --wwoc --out out.srt --report diff.md
WWOC_INFO = {
    "src": r"g:\SOLO工作\ost_worldcup_calib\input.srt",
    "dst": r"g:\SOLO工作\ost_worldcup_calib\calibrated.srt",
}


# =============================================================
# 3. 终末地（Arknights: Endfield）片源资产（原 calibrate_srt.py）
# =============================================================

ENDO_INFO = {
    "src": r"c:\Users\LENOVO\.trae-cn\attachments\6a8e517006175886fb7bf086\1c9fb9b8-cba8-4629-9055-d1cad976d527_efc96848-b18d-4832-8392-806dd67fe7ad_videoplayback (3).srt",
    "dst": r"g:\SOLO工作\videoplayback(3)_已校准.srt",
}


# 3.2 战双帕弥什（PGR）音乐会片源 —— 侧车整行覆盖模式
# 用法：python subtitle_calib_merged.py --pgr （不带文件）一键重跑；
#       或 python subtitle_calib_merged.py <PGR输入.srt> --pgr --out 输出.srt --report diff.md
PGR_INFO = {
    "src": r"g:\SOLO工作\pgr_rhythm_rough\input.srt",
    "dst": r"g:\SOLO工作\pgr_rhythm_rough\PGR_OneHeartOneHertz_calibrated.srt",
}

PGR_OVERRIDES_SRC = r"g:\SOLO工作\pgr_rhythm_rough\pgr_overrides.tsv"   # 序号<TAB>校准后中文


# 3.3 鸣潮 3.8 主线「予以明日的花束」莉莉实况片 —— 双语逐 cue 侧车整行覆盖
# 用法：python subtitle_calib_merged.py --wuwa38
#   等价于 <src> --mode bi --bi-override <sidecar>：规则先跑，侧车命中即整行覆盖（不叠加术语表）。
#   侧车只收「规则层改不出来」的逐句改动（官方名/上下文润色），规则层负责可泛化错形。
WW38_INFO = {
    "src": r"D:\原片\I Cried So Much... Wuthering Waves 3.8 Main Story Playthrough\【字幕】I Cried So Much... Wuthering Waves 3.8 Main Story Playthrough-微软翻译.srt",
    "dst": r"D:\原片\I Cried So Much... Wuthering Waves 3.8 Main Story Playthrough\【字幕】I Cried So Much... Wuthering Waves 3.8 Main Story Playthrough-微软翻译_校准_v2.srt",
}
WW38_OVERRIDES_SRC = r"D:\Agent Work\软件开发\视频工具箱\data\calib_sidecars\ww38_lily_main_bi_override.tsv"

# 2026-11-19 鸣潮 3.8 主线「予以明日的花束」终章 EmiMatcha Reaction 片（2534 cue）二次校准
# 用法：python subtitle_calib_merged.py --wuwa38h
#   与 --wuwa38 同构（bi 规则 + 逐 cue 侧车整行覆盖），区别是侧车覆盖时**保留原行 >> 前缀形态**，
#   避免本片 481 条旁白/画外音前缀被覆盖抹掉（engine.bi_override_preserve）。
WW38H_INFO = {
    "src": r"D:\原片\A HAPPY ENDING ! 3.8 Lily Main Story Quest FINALE REACTION Wuthering Waves\【字幕】A HAPPY ENDING？! 3.8 Lily Main Story Quest FINALE REACTION ｜ Wuthering Waves.en-微软翻译.srt",
    "dst": r"D:\原片\A HAPPY ENDING ! 3.8 Lily Main Story Quest FINALE REACTION Wuthering Waves\【校准v2】A HAPPY ENDING？! 3.8 Lily Main Story Quest FINALE REACTION ｜ Wuthering Waves.zh-CN.srt",
}
WW38H_OVERRIDES_SRC = r"D:\Agent Work\软件开发\视频工具箱\data\calib_sidecars\ww38h_lily_happy_ending_bi_override.tsv"

# 2026-11-19 鸣潮 3.8「literally broke me」Reaction 完整片（7045 cue）二次校准
# 用法：python subtitle_calib_merged.py --wuwa38b
#   与 --wuwa38h 同构（bi 规则 + 逐 cue 侧车整行覆盖）；侧车收全片终稿（含 >> 前缀），
#   供一键重跑与增量校准时对位。
WW38B_INFO = {
    "src": r"D:\原片\Wuthering Waves 3.8 literally broke me\【字幕】Wuthering Waves 3.8 literally broke me..en-微软翻译.srt",
    "dst": r"D:\原片\Wuthering Waves 3.8 literally broke me\【字幕】Wuthering Waves 3.8 literally broke me..zh-Hans-人工校准_v2.srt",
}
WW38B_OVERRIDES_SRC = r"D:\Agent Work\软件开发\视频工具箱\data\calib_sidecars\ww38b_literally_broke_me_bi_override.tsv"

# 3.8 鸣潮 3.8 主线「予以明日的花束」Jadealy 反应片 —— 双语逐 cue 侧车整行覆盖
# 用法：python subtitle_calib_merged.py --wuwa38j
WW38_J_INFO = {
    "src": r"D:\原片\I Lost Count of How Many Times I Cried Wuthering Waves 3.8 Main Quest Reaction\【字幕】I Lost Count of How Many Times I Cried ｜ Wuthering Waves 3.8 Main Quest Reaction.en-谷歌翻译.srt",
    "dst": r"D:\原片\I Lost Count of How Many Times I Cried Wuthering Waves 3.8 Main Quest Reaction\【字幕】I Lost Count of How Many Times I Cried ｜ Wuthering Waves 3.8 Main Quest Reaction.en-谷歌翻译_calibrated.r2.srt",
}
WW38_J_OVERRIDES_SRC = r"D:\Agent Work\软件开发\视频工具箱\data\calib_sidecars\ww38_jadealy_main_bi_override.tsv"


# 3.9 鸣潮 4.0 前瞻「Drip Marketing」Xlice reaction 片 —— 双语逐 cue 侧车整行覆盖
# 用法：python subtitle_calib_merged.py --wuwa40
#   等价于 <src> --mode bi --bi-override <sidecar>；规则层负责可泛化错形（4.0 七角色/术语/标语），
#   侧车收逐句人工精校（口语衔接、断句、读音讨论处保留拉丁、跨 cue 承接）。
WW40_INFO = {
    "src": r"D:\原片\AN INSANE NEW CAST! Xlice Reacts to Wuthering Waves Version 4.X Drip Marketing\【字幕】AN INSANE NEW CAST!？ Xlice Reacts to Wuthering Waves Version 4.X Drip Marketing.en-微软翻译.srt",
    "dst": r"D:\原片\AN INSANE NEW CAST! Xlice Reacts to Wuthering Waves Version 4.X Drip Marketing\【字幕】AN INSANE NEW CAST!？ Xlice Reacts to Wuthering Waves Version 4.X Drip Marketing.zh校准.r2.srt",
}
WW40_OVERRIDES_SRC = r"D:\Agent Work\软件开发\视频工具箱\data\calib_sidecars\ww40_drip_bi_override.tsv"

# 2026-11-19 鸣潮 4.0 新联邦 PV 韩语反应片 —— 韩语原声 + KO_TERMS + WW40KO_CONTEXT
# 用法：python subtitle_calib_merged.py --wuwa40ko
#   片源为韩语 ASR + 微软翻译双语（中文在上/韩语参考行在下，349 cue）。
#   与 --ko 的区别：① 追加 4.0 专用语境（岁主/声痕/瑝珑/残星会/拉海洛）；
#   ② 侧车 349 条逐 cue 整行覆盖，命中即不叠加术语表；③ 侧车已是终稿，含 >> 前缀。
WW40KO_INFO = {
    "src": r"D:\原片\[명조] 신연방 신규 캐릭터 대거 공개!「프로메우스의 품에 깃들어」PV 분석 & 캐릭터 쇼츠 감상\【字幕】[명조] 신연방 신규 캐릭터 대거 공개!「프로메우스의 품에 깃들어」PV 분석 & 캐릭터 쇼츠 감상.ko-微软翻译.srt",
    "dst": r"D:\原片\[명조] 신연방 신규 캐릭터 대거 공개!「프로메우스의 품에 깃들어」PV 분석 & 캐릭터 쇼츠 감상\【字幕】[명조] 신연방 신규 캐릭터 대거 공개!「프로메우스의 품에 깃들어」PV 분석 & 캐릭터 쇼츠 감상.ko-微软翻译_人工精校_v2.srt",
}
WW40KO_OVERRIDES_SRC = r"D:\Agent Work\软件开发\视频工具箱\data\calib_sidecars\ww40ko_newfed_pv_zh.tsv"

# 2026-11-21 鸣潮 4.0「永明的烬焰」IGN 独家实机演示 韩语反应片 —— 二次校准 + 逐 cue 侧车整行覆盖
# 用法：python subtitle_calib_merged.py --wuwa40ign
#   片源为韩语 ASR + 微软翻译双语（中文在上/韩语参考行在下，162 cue）。
#   KO_TERMS + WW40IGN_CONTEXT；侧车 162 条为终稿（含 >> 前缀），命中即整行覆盖、不叠加术语表。
WW40IGN_INFO = {
    "src": r"D:\原片\명조 초대박 공식 유출 떴다 ㅋㅋㅋㅋㅋㅋㅋㅋㅋㅋㅋㅋㅋㅋ\【字幕】명조 초대박 공식 유출 떴다 ㅋㅋㅋㅋㅋㅋㅋㅋㅋㅋㅋㅋㅋㅋ.ko-微软翻译.calib.srt",
    "dst": r"D:\原片\명조 초대박 공식 유출 떴다 ㅋㅋㅋㅋㅋㅋㅋㅋㅋㅋㅋㅋㅋㅋ\【字幕】명조 초대박 공식 유출 떴다 ㅋㅋㅋㅋㅋㅋㅋㅋㅋㅋㅋㅋㅋㅋ.ko-微软翻译.calib.精校_v2.srt",
}
WW40IGN_OVERRIDES_SRC = r"D:\Agent Work\软件开发\视频工具箱\data\calib_sidecars\ww40ign_ign_preview_zh.tsv"

# 3.8 鸣潮「第二索拉：未名之梦」Reaction 片 —— 双语逐 cue 侧车整行覆盖
# 用法：python subtitle_calib_merged.py --wuwasol
#   二校 1407 cue；侧车为六段人工复核合并后的终稿，供一键重跑与后续增量校准时对位。
WUSOL_INFO = {
    "src": r"D:\原片\I Didn't Expect The Wuthering Waves Dating Simulator to be THIS GOOD!\【中文精校】I Didn't Expect The Wuthering Waves Dating Simulator to be THIS GOOD!.srt",
    "dst": r"D:\原片\I Didn't Expect The Wuthering Waves Dating Simulator to be THIS GOOD!\【中文精校v2】I Didn't Expect The Wuthering Waves Dating Simulator to be THIS GOOD!.srt",
}
WUSOL_OVERRIDES_SRC = r"D:\Agent Work\软件开发\视频工具箱\data\calib_sidecars\ww_solaris_bi_override.tsv"


# 2026-11-19 Arcaea×明日方舟《Motion Amiya Partner Play｜All Songs Pure Memory》全曲纯享
#   （271 cue，28m33s，英语 ASR + 微软翻译双语，中文在上/英文参考行在下，CRLF 无 BOM）。
#   歌词向短片：`--arcak` 的曲名回拉（叛徒/叛逆者→Renegade）会把歌词义改回英文，
#   故走 `--arcakamiya` = ARCAK 术语表 + 271 条逐 cue 侧车整行覆盖（命中即不叠加术语表）。
#   用法：python subtitle_calib_merged.py --arcakamiya
ARCAK_AMIYA_INFO = {
    "src": r"D:\原片\Arcaea x Arknights Motion Amiya Partner Play All Songs Pure Memory ( )\【字幕】Arcaea x Arknights ｜ Motion Amiya Partner Play ｜ All Songs Pure Memory (？).en-微软翻译.srt",
    "dst": r"D:\原片\Arcaea x Arknights Motion Amiya Partner Play All Songs Pure Memory ( )\【字幕】Arcaea x Arknights ｜ Motion Amiya Partner Play ｜ All Songs Pure Memory (？)（中文校准版v2）.srt",
}
ARCAK_AMIYA_OVERRIDES_SRC = r"D:\Agent Work\软件开发\视频工具箱\data\calib_sidecars\arcak_amiya_motion_zh.tsv"







# =============================================================
# 3.1b 明日方舟（本尊）系统片源资产（2026-08-31 沉淀自《The Grand Arknights
#     New Player QA》2465 cue 校准；非终末地，独立 AK_TERMS）
#    ENFIELD_TERMS 是"终末地"游戏术语；本片是"明日方舟"本体 Q&A，
#    术语（生息演算/危机合约/集成战略/保全派驻/要塞协议 等）不得与 ENDFIELD_TERMS 混用。
# =============================================================
AK_INFO = {
    "src": r"g:\SOLO工作\ak_newplayer_qa_calib\input.srt",
    "dst": r"g:\SOLO工作\ak_newplayer_qa_calib\calibrated_merged.srt",
}

# AK_MODE 并入 process：与 endo 类似，但仅精调 ARKNIGHTS 中文行（首中文行）

# =============================================================
# 3.1b1 明日方舟 PV 世界杯（韩语原声，명일방주 PV 월드컵 112강，_ko_auto 谷歌翻译）专用资产
# 2026-09-10 沉淀：第一轮人工对照 117 处（对照_PV世界杯_第一轮.tsv）+ 第二轮新增。
# 参考行为韩语 ASR（如 이네스=Ines、머드락=Mudrock），中文行为谷歌机翻。
# 模式 --akko：AK_KO_TERMS（无歧义全局替换）+ AK_KO_CONTEXT（韩语参考行佐证）。
# 戒律：歧义词（医生/沉默/火焰/铅/熔岩/幻影/沙拉/霜 等）必须韩语佐证，防误伤普通词义；
#   韩语片绝不加载 KO_TERMS（鸣潮）或 WWOC_TERMS（综合手游）表。
# 用法：python subtitle_calib_merged.py <input.srt> --akko --out out.srt --report diff.md
# =============================================================
AK_KO_INFO = {
    "src": r"D:\字幕\【字幕】게임 PV 만든거 맞죠  명일방주 PV 월드컵 112강_ko_auto-谷歌翻译.srt",
    "dst": r"D:\字幕\【字幕】게임 PV 만든거 맞죠  명일방주 PV 월드컵 112강_ko_auto-谷歌翻译_校准.srt",
}

# 用法：python subtitle_calib_merged.py --zho <input.srt> --out out.srt
#   --zho 与 --endo/--ak/--ko 互斥；同属"仅改首中文行"，但只套用 ZH_ONLY_TERMS 这一张表。
ZHO_INFO = {
    "src": r"g:\SOLO工作\endo_wwstate_calib\input.srt",
    "dst": r"g:\SOLO工作\endo_wwstate_calib\calibrated.srt",
}



# =============================================================
# 6. 对象级知识层（Entity Knowledge Base，2026-09-11）
#
#    动机：扁平表时代，一个"对象"（如 漂泊者）的知识散落在几十条
#    互无关联的 错形->正确 键里；它的官方 EN/JA/KO 名、适用片源模式、
#    哪些变体需要参考行佐证、哪些语境要负向回滚，只存在于注释中，
#    机器不可读、投喂给 AI 校准时也无法整体携带。
#
#    本层把知识单元从"字符串对"提升为"实体对象"：
#      Entity(canonical="漂泊者", en="Rover", ja="漂泊者", ko="방랑자",
#             category="角色", modes=("bi", "ja"),
#             variants=(...),            # 无条件变体：ASR/机翻错形，出现即改
#             ctx=((r"\brover\b", "漫游者"), ...),  # 条件变体：参考行佐证才改
#             exclude=(r"\bLand Rover\b", ...),     # 负向排除：参考行命中则回滚
#             note="...")
#
#    工作机制（对校准引擎零侵入、行为与扁平表逐字节一致）：
#      import 时 _register_entities() 把 ENTITIES 投影进既有扁平表
#      （variants->*_TERMS / ctx->*_CONTEXT / exclude->EXCLUDE_CONTEXT），
#      并重建各正则缓存；process() 主路径一字未改。
#      冲突即报错：实体变体与扁平表既有键映射到不同目标时直接 SystemExit，
#      防止新旧两套知识静默打架。
#
#    维护约定（自本层起）：
#      · 新校准沉淀一律追加为 ENTITIES 里的 Entity，不再直接改扁平表；
#      · 旧扁平表保持冻结（历史资产，零回归），kb-export 会把它们与
#        ENTITIES 折叠成统一的对象级视图；
#      · 新增 Entity 后跑 `kb-lint` 自查（变体冲突/级联/模式错放），
#        再跑 `terms-check` 查二次命中。
#
#    子命令：
#      kb-export [--json] [--out 路径]   导出完整对象级知识库（默认 MD，
#                                        扁平表按 canonical 折叠 + ENTITIES
#                                        元数据合并；即"投喂用"知识文件）
#      kb-lookup <词>                    按任意形态（中文名/EN/JA/KO/变体）
#                                        反查实体，列出它的全部知识
#      kb-lint                           对象级体检：跨实体变体冲突、
#                                        变体⊂他实体官方名（同模式级联）、
#                                        条件变体与无条件变体重复、
#                                        ENTITIES 元数据完整性
# =============================================================

# 模式 -> 无条件变体表 / 条件变体表（实体注册时的投影目标）
_MODE_TERM_TABLE = {
    "bi": "BILINGUAL_TERMS", "ja": "JA_TERMS", "jpe": "JA_ENDFIELD_TERMS",
    "ko": "KO_TERMS", "wuwa40ko": "KO_TERMS", "wuwa40ign": "KO_TERMS", "wwoc": "WWOC_TERMS", "endo": "ENDFIELD_TERMS",
    "ak": "AK_TERMS", "akko": "AK_KO_TERMS", "zho": "ZH_ONLY_TERMS",
    "pgren": "PGR_EN_TERMS", "react": "REACT_TERMS",
    "endobi": "ENDFIELD_BI_TERMS", "endoko": "ENDFIELD_KO_TERMS",
    "pkm": "POKEMON_TERMS",
    # 2026-10-26 新增：边狱巴士（Limbus Company）音乐 reaction 片源
    "limbus": "LIMBUS_TERMS",
    # 2026-10-28 新增：最终幻想：共鸣（FFRS）HD-2D 实况片源
    "ffrs": "FFRS_TERMS",
    # 2026-10-30 新增：影之刃零（Phantom Blade Zero）英语原声+谷翻实况片源
    "pbz": "PBZ_TERMS",
    # 2026-11-01 新增：最终幻想14（FFXIV）英语原声+谷翻 reaction 片源
    "ff14": "FF14_TERMS",
    # 2026-11-15 新增：星之救援者（Star Savior）英语原声+谷翻评测片源
    "ssv": "SSV_TERMS",
    # 2026-11-18 新增：Arcaea × 明日方舟联动直播（英语 ASR + 微软翻译）
    "arcak": "ARCAK_TERMS",
    # 2026-11-21 新增：燕云十六声（Where Winds Meet）实机片源
    "wwm": "WWM_TERMS",
    # 2026-11-18 新增：TGA 2026 游戏大奖直播（英语原声 + 微软翻译）
    "tga26": "TGA_TERMS",
    # 2026-11-03 新增：战双帕弥什**日语原声**片源（联动朗读直播）。
    #   与既有 `pgren`（战双**英文**原声）互斥：那条通道的参考行是英语，本条是日语。
    "pgrja": "JA_PGR_TERMS",
    # 2026-11-03 新增：明日方舟**日语原声**片源（奈渡ナオト 首播 reaction）。
    #   与既有 `ak`（英语原声/中文行通道）互斥：那条参考行是英语，本条是日语。
    #   运行期 engine 用 AK_TERMS ∪ AK_JA_TERMS 合并表，本表只登记**增量**那张。
    "akja": "AK_JA_TERMS",
}

_MODE_CTX_TABLE = {
    "bi": "CONTEXT_MAP", "ja": "JA_CONTEXT", "jpe": "JA_ENDFIELD_CONTEXT",
    "akko": "AK_KO_CONTEXT", "ko": "KO_CONTEXT", "wuwa40ko": "WW40KO_CONTEXT", "wuwa40ign": "WW40IGN_CONTEXT", "ak": "AK_CONTEXT",
    "endoko": "ENDFIELD_KO_CONTEXT", "pkm": "POKEMON_CONTEXT",
    # 2026-10-25 新增：--wwoc 此前无语境槽，多游戏韩语片的歧义错形
    #   （十字军/家具/反向/德州/Star Seed 等）只能逐 cue；现补 WWOC_CONTEXT。
    "wwoc": "WWOC_CONTEXT",
    # 2026-10-20 新增：--endobi 此前无语境槽，通用中文词类官方名（枯萎/主管/以太/觉醒/
    #   蚁人/前哨基地…）无处锚定，只能逐 cue；现补 ENDFIELD_BI_CONTEXT 与 endoko 同构。
    #   --endo **不建槽**：单语片源每 cue 仅一行，ref 即该中文行本身，英文锚定永不命中。
    "endobi": "ENDFIELD_BI_CONTEXT",
    # 2026-10-26 新增：边狱巴士音乐 reaction；Boss/Canto/乐理术语靠英文参考行锚定
    "limbus": "LIMBUS_CONTEXT",
    # 2026-10-28 新增：最终幻想：共鸣；Visions/Stagger/Rain/Terra 等歧义词靠英文参考行锚定
    "ffrs": "FFRS_CONTEXT",
    # 2026-10-30 新增：影之刃零；Wooa=武侠/Withering Waves=鸣潮/姿势=架势 等靠英文参考行锚定
    "pbz": "PBZ_CONTEXT",
    # 2026-11-01 新增：最终幻想14；至冷/黎明/飞艇/地牢/收割者/旅行者/福音派 等
    #   正常中文词的官方名（银海之天舟/金曦之遗辉/飞空艇/迷宫/钐镰客/巡天者/福音战士）
    #   全靠英文参考行锚定，禁走裸键。
    "ff14": "FF14_CONTEXT",
    # 2026-11-03 新增：--pgrja 的语境槽。图层/赤潮/皮肤/空中庭园/瓦妮莎 这类**正常中文词**
    #   的官方名只能靠日语参考行锚定（裸键会把别的片源改花），故必须建槽。
    "pgrja": "JA_PGR_CONTEXT",
    # 2026-11-03 新增：--akja 的语境槽。天灾/标志/徽标/喇叭/团聚/医生/模块/小苏打/流星/坐标/
    #   成本/冰霜新星/深渊猎人 这类**正常中文词**的官方名（斯卡蒂/逻各斯/号角/整合运动/博士/
    #   模组/重装/陨星/搭配/费用/霜星/深海猎人）只能靠日语参考行锚定，禁走裸键。
    "akja": "AK_JA_CONTEXT",
    # 2026-11-04 新增：--pgren 的语境槽。余辉/光伏/丝带/克洛伊 这类**正常中文词**的官方名
    #   （「流光抛诸寰宇」/PV/缎带/库洛）只能靠英文参考行锚定，禁走裸键。
    "pgren": "PGR_EN_CONTEXT",
    # 2026-11-15 新增：--ssv 的语境槽。尼克/脉搏/烧灼/天井 这类**通用人名词/通用中文词**
    #   的官方名（妮姬/星光石/烧伤/保底）只能靠英文参考行锚定，禁走裸键。
    "ssv": "SSV_CONTEXT",
    # 2026-11-18 新增：--arcak 的语境槽。医生/操作员/老板/光谱/叛徒/光辉/奇点/活着/弧线
    #   这类**普通中文词**的官方名（博士/干员/Boss/Spectrum/Renegade/Radiant/Singularity/
    #   Alive/音弧）只能靠英文参考行锚定，禁走裸键。
    "arcak": "ARCAK_CONTEXT",
    # 2026-11-21 新增：--wwm 语境槽（老板/头目/副本/地下城/军械库 等通用词只能靠英文参考行锚定）
    "wwm": "WWM_CONTEXT",
    # 2026-11-18 新增：--tga26 的语境槽。Karen/武者/轨道站/我的学术/伊代/莱/居所/
    #   马拉松/共振/安魂曲/王牌/优生学 这类**普通中文词/人名**的官方名只能靠英文
    #   参考行锚定，禁走裸键。
    "tga26": "TGA_CONTEXT",
}

_MODE_NAMES = {
    "bi": "中英双语", "ja": "日语原声·鸣潮", "jpe": "日语原声·终末地",
    "ko": "韩语原声·鸣潮", "wuwa40ko": "韩语原声·鸣潮 4.0 新联邦 PV", "wuwa40ign": "韩语原声·鸣潮 4.0 IGN 实机", "wwoc": "综合手游OST", "endo": "终末地",
    "ak": "明日方舟", "akko": "明日方舟韩语", "zho": "中文行专属",
    "pgren": "战双英文原声", "react": "音乐点评", "endobi": "终末地·中英双语", "fix-en": "英文参考行修正",
    "endoko": "终末地·韩语原声", "pkm": "宝可梦城镇主题",
    "limbus": "边狱巴士",
    "ffrs": "最终幻想：共鸣",
    "pbz": "影之刃零",
    "ff14": "最终幻想14",
    "pgrja": "日语原声·战双",
    "akja": "日语原声·明日方舟",
    "ssv": "星之救援者",
    "arcak": "Arcaea×明日方舟",
    "tga26": "TGA 2026 游戏大奖",
    "wwm": "燕云十六声",
}

