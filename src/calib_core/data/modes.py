# -*- coding: utf-8 -*-
# @version 3.2.5
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

# 2026-11-22 鸣潮 4.0「永明的烬焰」先行映像 日文实况（1194 cue，2h03m）—— 二次校准 + 逐 cue 侧车整行覆盖
# 用法：python subtitle_calib_merged.py --wuwa40ja
#   片源为日语 ASR + 微软翻译双语（中文在上/日语参考行在下），CRLF 无 BOM。
#   模式走 ja（JA_TERMS + JA_CONTEXT）；侧车 1194 条收全片终稿，命中即整行覆盖、不叠加术语表。
#   官方依据：4.0 年度篇章「永明的烬焰」、新联邦/布法罗山脉、隧铠、安娜/露希尔/莉莉/格尔黛、
#     星炬学院/黑海岸/莫宁/莫特斐/千咲/嘉贝莉娜/秋水/砂；谐度破坏/协奏能量/共鸣解放。
WW40JA_INFO = {
    "src": r"D:\原片\【鳴潮】Ver4.0先行映像がぶっ飛んでる【Wuthering Waves】 (2)\【字幕】【鳴潮】Ver4.0先行映像がぶっ飛んでる【Wuthering Waves】.ja-微软翻译.srt",
    "dst": r"D:\原片\【鳴潮】Ver4.0先行映像がぶっ飛んでる【Wuthering Waves】 (2)\【字幕】【鳴潮】Ver4.0先行映像がぶっ飛んでる【Wuthering Waves】.ja-微软翻译_calibrated_v2.srt",
}
WW40JA_OVERRIDES_SRC = r"D:\Agent Work\软件开发\视频工具箱\data\calib_sidecars\ww40ja_preview_bi_override.tsv"

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

# 2026-11-21 鸣潮全短片 Reaction《Star Rail Player REACTS To ALL Wuthering Waves Cinematic Shorts》
#   （636 cue，英文 ASR + 谷歌翻译双语，中文在上/英文参考行在下，CRLF 无 BOM）
#   首轮人工重写 481 条，二校净改 23 条（#29/#173/#183-184/#198-200/#290/#293-294/#310/#327/
#     #334/#345/#370/#416-417/#438/#459/#488/#520/#616-617）。
#   用法：python subtitle_calib_merged.py --wuwaall
#   与 --wuwa38h 同构（bi 规则 + 逐 cue 侧车整行覆盖，无 >> 前缀），侧车收全片终稿 636 条。
WUWAALL_INFO = {
    "src": r"D:\原片\Star Rail Player REACTS To ALL Wuthering Waves Cinematic Shorts\【字幕】Star Rail Player REACTS To ALL Wuthering Waves Cinematic Shorts-谷歌翻译.srt",
    "dst": r"D:\原片\Star Rail Player REACTS To ALL Wuthering Waves Cinematic Shorts\【字幕】Star Rail Player REACTS To ALL Wuthering Waves Cinematic Shorts-谷歌翻译_calibrated_v2.srt",
}
WUWAALL_OVERRIDES_SRC = r"D:\Agent Work\软件开发\视频工具箱\data\calib_sidecars\wuwaall_all_shorts_bi_override.tsv"







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

# =============================================================
# 模式注册表（单一真源，2026-11-21 工程重构）
#   新增一个片源模式 = 新建 data/<mode>.py 词表 + 本表加一条注册。
#   字段：
#     terms         引擎术语表名（__AKJA_MERGE__=AK_TERMS∪AK_JA_TERMS，__EMPTY__={}）
#     ctx           引擎语境表名（None=无语境槽）
#     project_terms 实体投影术语槽（_MODE_TERM_TABLE 值；None=不投影，如 zel/hsr/pgr）
#     project_ctx   实体投影语境槽（_MODE_CTX_TABLE 值；None=不投影，如 endo/zho/react）
#     name          显示名（_MODE_NAMES 值；None=不进显示名表，如 zel/hsr/pgr）
#   三张投影视图（_MODE_TERM_TABLE/_MODE_CTX_TABLE/_MODE_NAMES）由本表推导；
#   monolith 生成时由 build_calib_monolith 序列化为字面量（兼容旧 merge core / ast_compat）。
#   ⚠ project_terms/project_ctx 决定 ENTITIES 投影目标，与引擎 terms/ctx 是两回事：
#     akja 引擎用合并表但投影只登记增量 AK_JA_TERMS；zel/hsr 引擎有表但无投影槽。
# =============================================================
MODE_REGISTRY = {
    "ak": {"terms": "AK_TERMS", "ctx": "AK_CONTEXT", "project_terms": "AK_TERMS", "project_ctx": "AK_CONTEXT", "name": "明日方舟"},
    # 2026-11-03 明日方舟日语原声（奈渡ナオト 首播）：引擎 AK_TERMS∪AK_JA_TERMS，投影只登记增量表
    "akja": {"terms": "__AKJA_MERGE__", "ctx": "AK_JA_CONTEXT", "project_terms": "AK_JA_TERMS", "project_ctx": "AK_JA_CONTEXT", "name": "日语原声·明日方舟"},
    "akko": {"terms": "AK_KO_TERMS", "ctx": "AK_KO_CONTEXT", "project_terms": "AK_KO_TERMS", "project_ctx": "AK_KO_CONTEXT", "name": "明日方舟韩语"},
    # 2026-11-18 Arcaea×明日方舟联动直播（英语 ASR + 微软翻译）
    "arcak": {"terms": "ARCAK_TERMS", "ctx": "ARCAK_CONTEXT", "project_terms": "ARCAK_TERMS", "project_ctx": "ARCAK_CONTEXT", "name": "Arcaea×明日方舟"},
    "bi": {"terms": "BILINGUAL_TERMS", "ctx": "CONTEXT_MAP", "project_terms": "BILINGUAL_TERMS", "project_ctx": "CONTEXT_MAP", "name": "中英双语"},
    # endo 单语片每 cue 仅一行，ref 即中文行本身，英文锚定永不命中 → 不建语境槽
    "endo": {"terms": "ENDFIELD_TERMS", "ctx": None, "project_terms": "ENDFIELD_TERMS", "project_ctx": None, "name": "终末地"},
    # 2026-10-20 endobi 补语境槽（通用中文词类官方名靠英文参考行锚定）
    "endobi": {"terms": "ENDFIELD_BI_TERMS", "ctx": "ENDFIELD_BI_CONTEXT", "project_terms": "ENDFIELD_BI_TERMS", "project_ctx": "ENDFIELD_BI_CONTEXT", "name": "终末地·中英双语"},
    "endoko": {"terms": "ENDFIELD_KO_TERMS", "ctx": "ENDFIELD_KO_CONTEXT", "project_terms": "ENDFIELD_KO_TERMS", "project_ctx": "ENDFIELD_KO_CONTEXT", "name": "终末地·韩语原声"},
    # 2026-11-01 最终幻想14（FFXIV）英语原声+谷翻 reaction
    "ff14": {"terms": "FF14_TERMS", "ctx": "FF14_CONTEXT", "project_terms": "FF14_TERMS", "project_ctx": "FF14_CONTEXT", "name": "最终幻想14"},
    # 2026-10-28 最终幻想：共鸣（FFRS）HD-2D 实况
    "ffrs": {"terms": "FFRS_TERMS", "ctx": "FFRS_CONTEXT", "project_terms": "FFRS_TERMS", "project_ctx": "FFRS_CONTEXT", "name": "最终幻想：共鸣"},
    "fix-en": {"terms": None, "ctx": None, "project_terms": None, "project_ctx": None, "name": "英文参考行修正"},
    # 2026-11-21 少女前线2：追放（GFL2 Exilium）二周年反应片
    "gfl2": {"terms": "GFL2_TERMS", "ctx": "GFL2_CONTEXT", "project_terms": "GFL2_TERMS", "project_ctx": "GFL2_CONTEXT", "name": "少女前线2：追放"},
    # 2026-10-20 崩坏：星穹铁道（引擎用 HSR_CONTEXT，但无实体投影槽）
    "hsr": {"terms": "HSR_TERMS", "ctx": "HSR_CONTEXT", "project_terms": None, "project_ctx": None, "name": None},
    "ja": {"terms": "JA_TERMS", "ctx": "JA_CONTEXT", "project_terms": "JA_TERMS", "project_ctx": "JA_CONTEXT", "name": "日语原声·鸣潮"},
    "jpe": {"terms": "JA_ENDFIELD_TERMS", "ctx": "JA_ENDFIELD_CONTEXT", "project_terms": "JA_ENDFIELD_TERMS", "project_ctx": "JA_ENDFIELD_CONTEXT", "name": "日语原声·终末地"},
    "ko": {"terms": "KO_TERMS", "ctx": "KO_CONTEXT", "project_terms": "KO_TERMS", "project_ctx": "KO_CONTEXT", "name": "韩语原声·鸣潮"},
    # 2026-10-26 边狱巴士（Limbus Company）音乐 reaction
    "limbus": {"terms": "LIMBUS_TERMS", "ctx": "LIMBUS_CONTEXT", "project_terms": "LIMBUS_TERMS", "project_ctx": "LIMBUS_CONTEXT", "name": "边狱巴士"},
    # 2026-10-30 影之刃零（Phantom Blade Zero）英语原声+谷翻实况
    "pbz": {"terms": "PBZ_TERMS", "ctx": "PBZ_CONTEXT", "project_terms": "PBZ_TERMS", "project_ctx": "PBZ_CONTEXT", "name": "影之刃零"},
    # pgr 侧车整行覆盖模式：无术语表（引擎 __EMPTY__），无投影槽
    "pgr": {"terms": "__EMPTY__", "ctx": None, "project_terms": None, "project_ctx": None, "name": None},
    # 2026-11-04 战双英文原声（余辉/光伏/丝带/克洛伊 全是正常中文词，禁裸键）
    "pgren": {"terms": "PGR_EN_TERMS", "ctx": "PGR_EN_CONTEXT", "project_terms": "PGR_EN_TERMS", "project_ctx": "PGR_EN_CONTEXT", "name": "战双英文原声"},
    # 2026-11-03 战双日语原声（联动朗读直播）：参考行日语，与 pgren 互斥
    "pgrja": {"terms": "JA_PGR_TERMS", "ctx": "JA_PGR_CONTEXT", "project_terms": "JA_PGR_TERMS", "project_ctx": "JA_PGR_CONTEXT", "name": "日语原声·战双"},
    # 2026-10-21 宝可梦城镇主题
    "pkm": {"terms": "POKEMON_TERMS", "ctx": "POKEMON_CONTEXT", "project_terms": "POKEMON_TERMS", "project_ctx": "POKEMON_CONTEXT", "name": "宝可梦城镇主题"},
    # react 引擎用 REACT_CONTEXT，但无实体投影语境槽
    "react": {"terms": "REACT_TERMS", "ctx": "REACT_CONTEXT", "project_terms": "REACT_TERMS", "project_ctx": None, "name": "音乐点评"},
    # 2026-11-15 星之救援者（Star Savior）英语原声+谷翻评测
    "ssv": {"terms": "SSV_TERMS", "ctx": "SSV_CONTEXT", "project_terms": "SSV_TERMS", "project_ctx": "SSV_CONTEXT", "name": "星之救援者"},
    # 2026-11-18 TGA 2026 游戏大奖直播（英语原声 + 微软翻译）
    "tga26": {"terms": "TGA_TERMS", "ctx": "TGA_CONTEXT", "project_terms": "TGA_TERMS", "project_ctx": "TGA_CONTEXT", "name": "TGA 2026 游戏大奖"},
    # 2026-11-21 鸣潮 4.0 IGN 实机演示韩语反应片
    "wuwa40ign": {"terms": "KO_TERMS", "ctx": "WW40IGN_CONTEXT", "project_terms": "KO_TERMS", "project_ctx": "WW40IGN_CONTEXT", "name": "韩语原声·鸣潮 4.0 IGN 实机"},
    # 2026-11-19 鸣潮 4.0 新联邦 PV 韩语反应片
    "wuwa40ko": {"terms": "KO_TERMS", "ctx": "WW40KO_CONTEXT", "project_terms": "KO_TERMS", "project_ctx": "WW40KO_CONTEXT", "name": "韩语原声·鸣潮 4.0 新联邦 PV"},
    # 2026-11-21 燕云十六声（Where Winds Meet）滹沱实机片
    "wwm": {"terms": "WWM_TERMS", "ctx": "WWM_CONTEXT", "project_terms": "WWM_TERMS", "project_ctx": "WWM_CONTEXT", "name": "燕云十六声"},
    # 2026-10-25 wwoc 补语境槽（多游戏韩语片歧义错形）
    "wwoc": {"terms": "WWOC_TERMS", "ctx": "WWOC_CONTEXT", "project_terms": "WWOC_TERMS", "project_ctx": "WWOC_CONTEXT", "name": "综合手游OST"},
    # 2026-09-14 塞尔达传说（引擎用 ZELDA_TERMS，无语境槽、无投影槽）
    "zel": {"terms": "ZELDA_TERMS", "ctx": None, "project_terms": None, "project_ctx": None, "name": None},
    "zho": {"terms": "ZH_ONLY_TERMS", "ctx": None, "project_terms": "ZH_ONLY_TERMS", "project_ctx": None, "name": "中文行专属"},
}

# 简单模式旗标（--<mode> 直接设 mode）。排除：bi（默认无旗标）、fix-en（--fix-en 布尔）、
#   wuwa40ko/wuwa40ign（走一键重跑链，需 info+侧车装配）、wwm（原 cli 无 --wwm 简单旗标，
#   仅经 --mode wwm 别名进入；擅自补旗标会让 --wwm 从「忽略落 bi」漂移成 wwm）。
_NO_SIMPLE_FLAG = {"bi", "fix-en", "wuwa40ko", "wuwa40ign", "wwm"}
_MODE_FLAGS = {"--" + m: m for m in MODE_REGISTRY if m not in _NO_SIMPLE_FLAG}

# --mode 别名 → 模式（精确沿用原 elif 链 + 三元兜底的全部别名；未列出的 --mode 值落 bi）。
#   ⚠ 别名集必须与原链逐字一致：jpe/pgrja/akko/endobi/endoko/pgren/react/wwoc 等
#     原本就没有 --mode 别名（--mode jpe 会落 bi），不可擅自补全，否则行为漂移。
_MODE_ALIASES = {
    # 三元兜底组
    "ja": "ja", "japanese": "ja",
    "ko": "ko", "korean": "ko",
    "ak": "ak", "arknights": "ak",
    "zho": "zho", "zhonly": "zho", "zh_only": "zho",
    "endo": "endo", "endfield": "endo",
    "zel": "zel", "zelda": "zel", "legend of zelda": "zel", "zelda_direct": "zel",
    # 显式 elif 组
    "limbus": "limbus", "limbuscompany": "limbus", "边狱巴士": "limbus",
    "ffrs": "ffrs", "ffresonance": "ffrs", "finalfantasyresonance": "ffrs", "共鸣": "ffrs",
    "pkm": "pkm", "pokemon": "pkm", "pokémon": "pkm", "pocket_monsters": "pkm",
    "hsr": "hsr", "starrail": "hsr", "star_rail": "hsr", "honkai_starrail": "hsr", "honkaistarrail": "hsr",
    "pbz": "pbz", "phantomblade": "pbz", "phantombladezero": "pbz", "影之刃零": "pbz", "影之刃": "pbz",
    "ff14": "ff14", "ffxiv": "ff14", "finalfantasy14": "ff14", "finalfantasixiv": "ff14",
    "最终幻想14": "ff14", "最终幻想xiv": "ff14", "银海之天舟": "ff14",
    "ssv": "ssv", "starsavior": "ssv", "star_savior": "ssv", "星之救援者": "ssv",
    "arcak": "arcak", "arcakn": "arcak", "arcaea_arknights": "arcak", "arcaea×arknights": "arcak",
    "arcaea明日方舟": "arcak", "arcaea方舟": "arcak", "arcaea联动": "arcak",
    "tga26": "tga26", "tga2026": "tga26", "tga": "tga26", "thegameawards": "tga26",
    "gameawards": "tga26", "游戏大奖": "tga26", "tga直播": "tga26",
    "wwm": "wwm", "wherewindsmeet": "wwm", "where_winds_meet": "wwm",
    "燕云十六声": "wwm", "燕云": "wwm", "yanyun": "wwm",
    "gfl2": "gfl2", "gf2": "gfl2", "exilium": "gfl2", "gfl2exilium": "gfl2",
    "少女前线2": "gfl2", "少女前线2：追放": "gfl2", "追放": "gfl2", "少前2": "gfl2",
    "akja": "akja", "ak_ja": "akja", "arknights_ja": "akja", "arknightsja": "akja",
    "明日方舟日语": "akja", "日语原声明日方舟": "akja",
}

# 一键重跑注册表（2026-11-22 M1-A1 数据驱动）。键=旗标名（去 --），**声明序=装配序**。
#   字段：mode（设的模式）/ info（内置片源 dict）/ overrides（缺省侧车路径）/
#         preserve（bi_override_preserve，仅 wuwa38h）/ ko（ko_override 复用 bi_override，仅 wuwa40ko/ign）/
#         zh_first（仅 wuwaall）。
#   ⚠ 三套优先级语义（cli 装配/渲染须保真）：
#     mode = argv 中最后出现的旗标赢；info = 本表声明序最后命中赢；
#     缺省侧车 bi_override_path = 声明序第一命中赢（is None 守卫，显式 --bi-override 优先于一切）；
#     names["bi"] 后缀 = 另一序（wuwa38b→38/38j→38h→40→wuwasol→wuwaall）第一命中赢（见 cli names）。
#   新增一键重跑 = 本表加一条 + cli names 后缀（若 bi）；解析/装配/process 旗标自动表驱动。
_RERUN = {
    "wuwa38": {"mode": "bi", "info": WW38_INFO, "overrides": WW38_OVERRIDES_SRC},
    "wuwa38h": {"mode": "bi", "info": WW38H_INFO, "overrides": WW38H_OVERRIDES_SRC, "preserve": True},
    "wuwa38b": {"mode": "bi", "info": WW38B_INFO, "overrides": WW38B_OVERRIDES_SRC},
    "wuwa38j": {"mode": "bi", "info": WW38_J_INFO, "overrides": WW38_J_OVERRIDES_SRC},
    "wuwa40": {"mode": "bi", "info": WW40_INFO, "overrides": WW40_OVERRIDES_SRC},
    "wuwa40ko": {"mode": "wuwa40ko", "info": WW40KO_INFO, "overrides": WW40KO_OVERRIDES_SRC, "ko": True},
    "wuwa40ign": {"mode": "wuwa40ign", "info": WW40IGN_INFO, "overrides": WW40IGN_OVERRIDES_SRC, "ko": True},
    "wuwa40ja": {"mode": "ja", "info": WW40JA_INFO, "overrides": WW40JA_OVERRIDES_SRC},
    "wuwasol": {"mode": "bi", "info": WUSOL_INFO, "overrides": WUSOL_OVERRIDES_SRC},
    "wuwaall": {"mode": "bi", "info": WUWAALL_INFO, "overrides": WUWAALL_OVERRIDES_SRC, "zh_first": True},
    "arcakamiya": {"mode": "arcak", "info": ARCAK_AMIYA_INFO, "overrides": ARCAK_AMIYA_OVERRIDES_SRC},
}

# 模式 -> 无条件变体表 / 条件变体表（实体注册时的投影目标）
# ⚠ 字面量顺序被 kb._kb_view 的实体 modes 累积依赖（kb-export/lookup/lint 输出顺序），
#   不可改为字母序推导；与 MODE_REGISTRY 的 project_terms 由文件末守卫强制一致。
_MODE_TERM_TABLE = {
    "bi": "BILINGUAL_TERMS", "ja": "JA_TERMS", "jpe": "JA_ENDFIELD_TERMS",
    "ko": "KO_TERMS", "wuwa40ko": "KO_TERMS", "wuwa40ign": "KO_TERMS", "wwoc": "WWOC_TERMS", "endo": "ENDFIELD_TERMS",
    "ak": "AK_TERMS", "akko": "AK_KO_TERMS", "zho": "ZH_ONLY_TERMS",
    "pgren": "PGR_EN_TERMS", "react": "REACT_TERMS",
    "endobi": "ENDFIELD_BI_TERMS", "endoko": "ENDFIELD_KO_TERMS",
    "pkm": "POKEMON_TERMS",
    "limbus": "LIMBUS_TERMS",
    "ffrs": "FFRS_TERMS",
    "pbz": "PBZ_TERMS",
    "ff14": "FF14_TERMS",
    "ssv": "SSV_TERMS",
    "arcak": "ARCAK_TERMS",
    "wwm": "WWM_TERMS",
    "gfl2": "GFL2_TERMS",
    "tga26": "TGA_TERMS",
    "pgrja": "JA_PGR_TERMS",
    # akja 引擎用 AK_TERMS∪AK_JA_TERMS 合并表，投影只登记增量那张
    "akja": "AK_JA_TERMS",
}

_MODE_CTX_TABLE = {
    "bi": "CONTEXT_MAP", "ja": "JA_CONTEXT", "jpe": "JA_ENDFIELD_CONTEXT",
    "akko": "AK_KO_CONTEXT", "ko": "KO_CONTEXT", "wuwa40ko": "WW40KO_CONTEXT", "wuwa40ign": "WW40IGN_CONTEXT", "ak": "AK_CONTEXT",
    "endoko": "ENDFIELD_KO_CONTEXT", "pkm": "POKEMON_CONTEXT",
    "wwoc": "WWOC_CONTEXT",
    # endo 不建槽：单语片源每 cue 仅一行，ref 即该中文行本身，英文锚定永不命中
    "endobi": "ENDFIELD_BI_CONTEXT",
    "limbus": "LIMBUS_CONTEXT",
    "ffrs": "FFRS_CONTEXT",
    "pbz": "PBZ_CONTEXT",
    "ff14": "FF14_CONTEXT",
    "pgrja": "JA_PGR_CONTEXT",
    "akja": "AK_JA_CONTEXT",
    "pgren": "PGR_EN_CONTEXT",
    "ssv": "SSV_CONTEXT",
    "arcak": "ARCAK_CONTEXT",
    "wwm": "WWM_CONTEXT",
    "gfl2": "GFL2_CONTEXT",
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
    "gfl2": "少女前线2：追放",
}


# =============================================================
# 一致性守卫：MODE_REGISTRY 是声明真源，三视图是保序字面量镜像。
#   新增/修改模式时两处必须同步（值相等，顺序无关）；不一致即导入失败，
#   防止注册表与投影表静默打架。引擎 terms/ctx 与投影 project_* 故意不同
#   （akja 合并表 vs 增量投影、zel/hsr 有引擎表无投影槽），守卫只校验投影字段。
# =============================================================
def _check_registry_consistency():
    proj_t = {m: e["project_terms"] for m, e in MODE_REGISTRY.items() if e["project_terms"]}
    proj_c = {m: e["project_ctx"] for m, e in MODE_REGISTRY.items() if e["project_ctx"]}
    proj_n = {m: e["name"] for m, e in MODE_REGISTRY.items() if e["name"]}
    for label, proj, view in (("project_terms/_MODE_TERM_TABLE", proj_t, _MODE_TERM_TABLE),
                              ("project_ctx/_MODE_CTX_TABLE", proj_c, _MODE_CTX_TABLE),
                              ("name/_MODE_NAMES", proj_n, _MODE_NAMES)):
        if proj != view:
            only_reg = sorted(set(proj) - set(view))
            only_view = sorted(set(view) - set(proj))
            diff = sorted(k for k in set(proj) & set(view) if proj[k] != view[k])
            raise SystemExit(
                f"MODE_REGISTRY 与视图不一致 [{label}]：仅注册表 {only_reg} / "
                f"仅视图 {only_view} / 值不同 {diff}")


_check_registry_consistency()

