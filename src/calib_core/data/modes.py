# -*- coding: utf-8 -*-
# @version 3.3.2
"""术语/实体数据表

源：subtitle_calib_merged.py L2797-L7340 @ 97d7d463（2026-10-24 冻结快照）
"""
import io
import os
import re
import shutil
import sys
import unicodedata

# 片源自动识别特征词（P2-1 markers 字段 / P2-5 detect 打分表共用同一份数据，
#   不再由 modes.py 与 engine.py 各自引用 ENDFIELD_AUTO_MARKERS 常数）。
from .endfield import ENDFIELD_AUTO_MARKERS


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

# 2026-11-25 鸣潮 3.8 第四章第五幕「予以明日的花束」莉莉线 韩语直播生肉（8934 cue）
# 用法：python subtitle_calib_merged.py --wuwa38lilyko
#   版式 ko_zh（韩语 ASR 在上、中文在下，CRLF 无 BOM），走 ko_override 逐 cue 整行覆盖；
#   侧车收全片 8934 条人工终稿，命中即用、不叠加 KO_TERMS（终稿含刻意保留的口语断句）。
#   二校口径（库街区该幕剧情全文 + 3.8 版本页）：카산드라=卡瓦莎、제도 다이아=杰凯德、
#     골드러너=淘金客、제오구역=第五战区、마음의 영역=心之集域、스타토치=星炬学院。
WW38LILY_KO_INFO = {
    "src": r"D:\原片\[2026.11.20] 역대급 또대급 고점 명조 3.8 4장 5막 릴리 스토리 + 가챠\[2026.11.20] 역대급 또대급 고점 ｜ 명조 3.8 4장 5막 릴리 스토리 + 가챠.ko-orig.zh.srt",
    "dst": r"D:\原片\[2026.11.20] 역대급 또대급 고점 명조 3.8 4장 5막 릴리 스토리 + 가챠\[2026.11.20] 역대급 또대급 고점 ｜ 명조 3.8 4장 5막 릴리 스토리 + 가챠.ko-orig.zh.calibrated.srt",
}
WW38LILY_KO_OVERRIDES_SRC = r"D:\Agent Work\软件开发\视频工具箱\data\calib_sidecars\ww38lily_ko_zh.tsv"

# 2026-11-26 鸣潮 3.8 第四章第五幕「予以明日的花束」Streamers Reaction 英中双语片（628 cue）
# 用法：python subtitle_calib_merged.py --wuwa38s
#   与 --wuwa38 同构（bi 规则 + 逐 cue 侧车整行覆盖）；侧车收全片 628 条人工终稿。
#   二校口径（库街区该幕剧情全文）：Rover=漂泊者、Resonator Forces=共鸣者军队、
#     Federated Cities=联邦城、Somnoire/Somnium=心之集域、Mr. Grimm=格姆先生、
#     Cassandra=卡瓦莎、Herman=赫利曼、Meta/Meto=梅塔、Blin=卜灵、Siggy=西格莉卡、
#     Miss Dora=这扇门、Madam Servant=乘务员哥哥、Federica girl=联邦人、Day 728=第727天。
WW38S_INFO = {
    "src": r"D:\原片\Streamers Reaction To The Lily Arc\【字幕】Streamers Reaction To The Lily Arc.en-谷歌翻译.srt",
    "dst": r"D:\原片\Streamers Reaction To The Lily Arc\【字幕】Streamers Reaction To The Lily Arc.zh-CN校准_v2.srt",
}
WW38S_OVERRIDES_SRC = r"D:\Agent Work\软件开发\视频工具箱\data\calib_sidecars\ww38s_streamers_lily_arc_bi_override.tsv"

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

# 2026-11-24 鸣潮 3.8/3.7/3.6 混合 reaction《Kuro Games Keeps Traumatizing Gigguk》（620 cue）二次人工校准
# 用法：python subtitle_calib_merged.py --wuwa38g
#   与 --wuwa38b 同构（bi 规则 + 逐 cue 侧车整行覆盖）；侧车收全片终稿（含 >> 前缀，无需 preserve）。
#   本轮官中依据：3.8 联邦城/莉莉医生/调香师、3.7 梦州/心月狐/朝月会/玲珑球/锁暝/岁主、
#   3.4 洛瑟菈；ASR 形修正 Balinaphora→巴利诺拉、Jer/Jouer→角、genuine→真实的。
WW38G_INFO = {
    "src": r"D:\原片\Kuro Games Keeps Traumatizing Gigguk\【字幕】Kuro Games Keeps Traumatizing Gigguk.en-微软翻译.srt",
    "dst": r"D:\原片\Kuro Games Keeps Traumatizing Gigguk\【字幕】Kuro Games Keeps Traumatizing Gigguk.zh-官方名词精校-v2.srt",
}
WW38G_OVERRIDES_SRC = r"D:\Agent Work\软件开发\视频工具箱\data\calib_sidecars\ww38g_traumatizing_gigguk_bi_override.tsv"


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

# 2026-11-23 鸣潮 4.0「永明的烬焰」新地区 PV + 新角色实机 韩语反应片（951 cue，53m39s）
#   用法：python subtitle_calib_merged.py --wuwa40pv
#   片源为韩语 ASR + 微软翻译双语（中文在上/韩语参考行在下），UTF-8 无 BOM、CRLF、末尾单 CRLF。
#   与 --wuwa40ko/--wuwa40ign 同构：KO_TERMS + WW40PV_CONTEXT + 951 条逐 cue 侧车整行覆盖
#   （命中即整行覆盖、不叠加术语表）。二校净改 25 条（#63/#79/#91/#95/#98/#99/#100/#120/#121/
#     #145/#177/#200/#237/#243/#318/#377/#439/#598/#643/#815/#830/#856-857/#921/#949），
#     其中 #856-857 为「나도 릴리도 쉬어가는 버전」主语漏译修复。
#   官方依据：4.0 年度篇章「永明的烬焰」、新联邦/旧联邦遗址、七角色、PV 台词、
#     系统词 声痕/守岸人/残星会/隧铠/黎那汐塔。
WW40PV_INFO = {
    "src": r"D:\原片\[명조] 누가 탈것을 아이언맨을 내주나요 ! ! 신규 지역 PV, 신캐 쇼츠, 공식 유출 4.0 신캐릭터 선행 플레이 영상 같이보기\【字幕】[명조] 누가 탈것을 아이언맨을 내주나요？!？! ｜ 신규 지역 PV, 신캐 쇼츠, 공식 유출 4.0 신캐릭터 선행 플레이 영상 같이보기.ko-微软翻译.srt",
    "dst": r"D:\原片\[명조] 누가 탈것을 아이언맨을 내주나요 ! ! 신규 지역 PV, 신캐 쇼츠, 공식 유출 4.0 신캐릭터 선행 플레이 영상 같이보기\【字幕】[명조] 누가 탈것을 아이언맨을 내주나요？!？! ｜ 신규 지역 PV, 신캐 쇼츠, 공식 유출 4.0 신캐릭터 선행 플레이 영상 같이보기.ko-人工精校_v2.srt",
}
WW40PV_OVERRIDES_SRC = r"D:\Agent Work\软件开发\视频工具箱\data\calib_sidecars\ww40pv_newfed_pv_ko_zh.tsv"

# 2026-11-24 鸣潮 4.0「永明的烬焰」新联邦实机 英语 reaction 片（251 cue）二次校准 + 逐 cue 侧车整行覆盖
#   用法：python subtitle_calib_merged.py --wuwa40reveal
#   片源为英语 ASR + 微软翻译双语（中文在上/英文参考行在下），UTF-8 无 BOM、CRLF、末尾单 CRLF。
#   与 --wuwa40 同构（bi 规则 + 251 条侧车整行覆盖，命中即不叠加术语表）。
#   二校净改 11 条（#20/#33/#46-47/#103-104/#136-137/#169-170/#235）；
#   官方依据：4.0 年度篇章「永明的烬焰」、新联邦/旧联邦城市、穿戴式机甲「隧铠」、
#     深海模式、共鸣解放、漂泊者、露希尔/小沧龙、PV《在普罗米厄的怀抱下》。
WW40REVEAL_INFO = {
    "src": r"D:\字幕\【字幕】They REVEALED New Federation Gameplay For Wuthering Waves!.en-微软翻译.srt",
    "dst": r"D:\字幕\【字幕】They REVEALED New Federation Gameplay For Wuthering Waves!.en-微软翻译_calibrated_v2.srt",
}
WW40REVEAL_OVERRIDES_SRC = r"D:\Agent Work\软件开发\视频工具箱\data\calib_sidecars\ww40reveal_newfed_bi_override.tsv"

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
# 模式注册表（单一真源，2026-11-21 工程重构；2026-11-22 变体键降级为「游戏-细类」子键）
#   新增一个片源模式 = 新建 data/<mode>.py 词表 + 本表加一条注册。
#   字段：
#     terms         引擎术语表名（__AKJA_MERGE__=AK_TERMS∪AK_JA_TERMS，__EMPTY__={}）
#     ctx           引擎语境表名（None=无语境槽）
#     project_terms 实体投影术语槽（_MODE_TERM_TABLE 值；None=不投影，如 zel/hsr/pgr）
#     project_ctx   实体投影语境槽（_MODE_CTX_TABLE 值；None=不投影，如 endo/zho/react）
#     name          显示名（_MODE_NAMES 值；None=不进显示名表，如 zel/hsr/pgr）
#     parent        父游戏 ASCII 键（顶层=None；纯分组/显示字段，引擎不依赖 parent 键存在——
#                   如 wuwa-ja/wuwa-ko 的 parent="wuwa" 是逻辑组名，registry 并无 wuwa 键）
#   2026-11-24 P2-1 图层驱动（新增四字段，引擎不再硬编码模式集合）：
#     layout        版式/分发骨架，取值见 LAYOUTS：
#                     first_zh  规则「首中文行」通用路径（术语 + 语境锚定）
#                     bilingual 双语版式（首中文行 + EXCLUDE 回滚 + WORD_MAP + 侧车覆盖）
#                     ko_zh     韩语原声（改**全部**中文行，锚点=同 cue 谚文行逐行配对）
#                     ak_zh     明日方舟式（改全部中文行，锚点=全部英文行拼接）
#                     endo_zh   终末地单语（只改中文行，无锚点）
#                     sidecar   纯侧车整行覆盖（无术语表，如 pgr）
#     layers        该模式实际启用的图层（LAYER_TOKENS 子集，顺序不敏感）：
#                     term             术语表替换
#                     ctx              语境锚定（ctx 字段那张表）
#                     exclude          EXCLUDE_CONTEXT 负向回滚
#                     word_map         WORD_MAP（不计命中统计）
#                     override:bi      侧车覆盖取 bi_override
#                     override:ko      侧车覆盖取 ko_override
#                     override:pgr     侧车覆盖取 pgr_override
#                     override_nocjk  无中文行 cue 也允许侧车整行覆盖
#                   同一模式至多一个 override:*；wuwa-40reveal 与 bi 同表同版式，
#                   2026-11-24 起图层完全对齐（侧车全覆盖 → 对齐后逐字节零漂移）。
#     markers       片源自动识别特征词（detect 打分表，见 modes.detect_mode_score）
#     sidecar       该模式的缺省侧车 TSV（None=无内置侧车，由一键重跑/--bi-override 装配）
#   2026-11-22 重命名（12 个变体校准键 → 父游戏 ASCII 子键「游戏-细类」，纯重命名零行为漂移：
#     terms/ctx/project_*/表名全部不变；旧键经 _MODE_ALIASES + normalize_mode 兼容归一）：
#     akja→ak-ja、akko→ak-ko、arcak→ak-arcaea、endobi→endo-bi、endoko→endo-ko、jpe→endo-ja、
#     ja→wuwa-ja、ko→wuwa-ko、wuwa40ko→wuwa-40ko、wuwa40ign→wuwa-40ign、pgren→pgr-en、pgrja→pgr-ja
#   三张投影视图（_MODE_TERM_TABLE/_MODE_CTX_TABLE/_MODE_NAMES）由本表推导；
#   monolith 生成时由 build_calib_monolith 序列化为字面量（兼容旧 merge core / ast_compat）。
#   ⚠ project_terms/project_ctx 决定 ENTITIES 投影目标，与引擎 terms/ctx 是两回事：
#     ak-ja 引擎用合并表但投影只登记增量 AK_JA_TERMS；zel/hsr 引擎有表但无投影槽。
# =============================================================
#: 版式骨架取值（P2-1）。新增模式必须从这些值里选一个，引擎按它分发。
LAYOUTS = ("first_zh", "bilingual", "ko_zh", "ak_zh", "endo_zh", "sidecar")
#: 图层 token 取值（P2-1）。引擎只认这些 token，未知 token 直接构建失败。
LAYER_TOKENS = frozenset({"term", "ctx", "exclude", "word_map",
                          "override:bi", "override:ko", "override:pgr",
                          "override_nocjk", "auto_terms", "fix_en"})

MODE_REGISTRY = {
    "ak": {"terms": "AK_TERMS", "ctx": "AK_CONTEXT",
           "project_terms": "AK_TERMS", "project_ctx": "AK_CONTEXT",
           "name": "明日方舟", "parent": None,
           "layout": "ak_zh", "layers": ("term", "ctx", "exclude"),
           # 2026-11-25 自动选模式：高判别方舟特征词
           "markers": ("明日方舟", "罗德岛", "阿米娅", "凯尔希", "干员", "泰拉",
                       "Arknights", "整合运动", "霜星", "塔露拉", "能天使",
                       "德克萨斯", "源石技艺", "斯卡蒂", "浊心"),
           "sidecar": None},
    # 2026-11-03 明日方舟日语原声（奈渡ナオト 首播）：引擎 AK_TERMS∪AK_JA_TERMS，投影只登记增量表
    # 2026-11-22 降级子键：akja → ak-ja（parent=ak）
    "ak-ja": {"terms": "__AKJA_MERGE__", "ctx": "AK_JA_CONTEXT",
              "project_terms": "AK_JA_TERMS", "project_ctx": "AK_JA_CONTEXT",
              "name": "明日方舟-日语", "parent": "ak",
              "layout": "first_zh", "layers": ("term", "ctx"),
              "markers": (), "sidecar": None},
    "ak-ko": {"terms": "AK_KO_TERMS", "ctx": "AK_KO_CONTEXT",
              "project_terms": "AK_KO_TERMS", "project_ctx": "AK_KO_CONTEXT",
              "name": "明日方舟-韩语", "parent": "ak",
              "layout": "first_zh", "layers": ("term", "ctx"),
              "markers": (), "sidecar": None},
    # 2026-11-18 Arcaea×明日方舟联动直播（英语 ASR + 微软翻译）
    # 2026-11-22 降级子键：arcak → ak-arcaea（parent=ak）
    "ak-arcaea": {"terms": "ARCAK_TERMS", "ctx": "ARCAK_CONTEXT",
                  "project_terms": "ARCAK_TERMS", "project_ctx": "ARCAK_CONTEXT",
                  "name": "明日方舟-Arcaea", "parent": "ak",
                  "layout": "ak_zh", "layers": ("term", "ctx", "exclude", "override:bi"),
                  "markers": (), "sidecar": None},
    "bi": {"terms": "BILINGUAL_TERMS", "ctx": "CONTEXT_MAP",
           "project_terms": "BILINGUAL_TERMS", "project_ctx": "CONTEXT_MAP",
           "name": "中英双语", "parent": None,
           "layout": "bilingual",
           "layers": ("term", "ctx", "exclude", "word_map", "override:bi",
                      "override_nocjk", "auto_terms", "fix_en"),
           "markers": (), "sidecar": None},
    # endo 单语片每 cue 仅一行，ref 即中文行本身，英文锚定永不命中 → 不建语境槽
    "endo": {"terms": "ENDFIELD_TERMS", "ctx": None,
             "project_terms": "ENDFIELD_TERMS", "project_ctx": None,
             "name": "终末地", "parent": None,
             "layout": "endo_zh", "layers": ("term",),
             "markers": (), "sidecar": None},
    # 2026-10-20 endobi 补语境槽（通用中文词类官方名靠英文参考行锚定）
    # 2026-11-22 降级子键：endobi → endo-bi（parent=endo）
    "endo-bi": {"terms": "ENDFIELD_BI_TERMS", "ctx": "ENDFIELD_BI_CONTEXT",
                "project_terms": "ENDFIELD_BI_TERMS", "project_ctx": "ENDFIELD_BI_CONTEXT",
                "name": "终末地-双语", "parent": "endo",
                "layout": "first_zh", "layers": ("term", "ctx"),
                "markers": ENDFIELD_AUTO_MARKERS, "sidecar": None},
    # 2026-11-22 降级子键：endoko → endo-ko（parent=endo）
    "endo-ko": {"terms": "ENDFIELD_KO_TERMS", "ctx": "ENDFIELD_KO_CONTEXT",
                "project_terms": "ENDFIELD_KO_TERMS", "project_ctx": "ENDFIELD_KO_CONTEXT",
                "name": "终末地-韩语", "parent": "endo",
                "layout": "first_zh", "layers": ("term", "ctx"),
                "markers": (), "sidecar": None},
    # 2026-11-01 最终幻想14（FFXIV）英语原声+谷翻 reaction
    "ff14": {"terms": "FF14_TERMS", "ctx": "FF14_CONTEXT",
             "project_terms": "FF14_TERMS", "project_ctx": "FF14_CONTEXT",
             "name": "最终幻想14", "parent": None,
             "layout": "first_zh", "layers": ("term", "ctx", "fix_en"),
             "markers": (), "sidecar": None},
    # 2026-10-28 最终幻想：共鸣（FFRS）HD-2D 实况
    "ffrs": {"terms": "FFRS_TERMS", "ctx": "FFRS_CONTEXT",
             "project_terms": "FFRS_TERMS", "project_ctx": "FFRS_CONTEXT",
             "name": "最终幻想：共鸣", "parent": None,
             "layout": "first_zh", "layers": ("term", "ctx"),
             "markers": (), "sidecar": None},
    "fix-en": {"terms": None, "ctx": None,
               "project_terms": None, "project_ctx": None,
               "name": "英文参考行修正", "parent": None,
               "layout": "bilingual",
               "layers": ("term", "ctx", "exclude", "word_map", "override:bi", "override_nocjk"),
               "markers": (), "sidecar": None},
    # 2026-11-21 少女前线2：追放（GFL2 Exilium）二周年反应片
    "gfl2": {"terms": "GFL2_TERMS", "ctx": "GFL2_CONTEXT",
             "project_terms": "GFL2_TERMS", "project_ctx": "GFL2_CONTEXT",
             "name": "少女前线2：追放", "parent": None,
             "layout": "first_zh", "layers": ("term", "ctx"),
             # 2026-11-25 自动选模式：高判别少前2特征词
             "markers": ("少女前线2", "追放", "Exilium", "Girls' Frontline 2",
                         "克莱妲", "伊利昂", "纳美西丝", "寇尔芙", "佩里缇亚",
                         "克罗丽科", "黛烟", "玛绮朵", "苏米", "托洛洛"),
             "sidecar": None},
    # 2026-10-20 崩坏：星穹铁道（引擎用 HSR_CONTEXT，但无实体投影槽）
    "hsr": {"terms": "HSR_TERMS", "ctx": "HSR_CONTEXT",
            "project_terms": None, "project_ctx": None,
            "name": None, "parent": None,
            "layout": "first_zh", "layers": ("term", "ctx"),
            "markers": (), "sidecar": None},
    # 2026-11-22 降级子键：ja → wuwa-ja（parent=wuwa 为逻辑组名，registry 无 wuwa 键）
    "wuwa-ja": {"terms": "JA_TERMS", "ctx": "JA_CONTEXT",
                "project_terms": "JA_TERMS", "project_ctx": "JA_CONTEXT",
                "name": "鸣潮-日语", "parent": "wuwa",
                "layout": "first_zh",
                "layers": ("term", "ctx", "override:bi", "override_nocjk"),
                "markers": (), "sidecar": None},
    # 2026-11-22 降级子键：jpe → endo-ja（parent=endo）
    "endo-ja": {"terms": "JA_ENDFIELD_TERMS", "ctx": "JA_ENDFIELD_CONTEXT",
                "project_terms": "JA_ENDFIELD_TERMS", "project_ctx": "JA_ENDFIELD_CONTEXT",
                "name": "终末地-日语", "parent": "endo",
                "layout": "first_zh", "layers": ("term", "ctx"),
                "markers": (), "sidecar": None},
    # 2026-11-22 降级子键：ko → wuwa-ko（parent=wuwa 为逻辑组名）
    "wuwa-ko": {"terms": "KO_TERMS", "ctx": "KO_CONTEXT",
                "project_terms": "KO_TERMS", "project_ctx": "KO_CONTEXT",
                "name": "鸣潮-韩语", "parent": "wuwa",
                # 2026-11-25：补 override:ko 图层——wuwa-ko 此前无侧车槽，导致 _RERUN 的 ko=True
                #   （ko_override）在 ko_zh 分支永不生效，整片退化为术语表替换（330 处误改）。
                #   无侧车传入时 ko_override=None，条件短路，历史行为零变化。
                #   override_nocjk：中文行整行为纯拉丁残片（Ppongi/Ana/Ys → 人工终稿改中文）
                #   时无 CJK 可判，需该图层才允许按侧车整行覆盖（本片 94 处）。
                "layout": "ko_zh", "layers": ("term", "ctx", "exclude",
                                              "override:ko", "override_nocjk"),
                "markers": (), "sidecar": None},
    # 2026-10-26 边狱巴士（Limbus Company）音乐 reaction
    "limbus": {"terms": "LIMBUS_TERMS", "ctx": "LIMBUS_CONTEXT",
               "project_terms": "LIMBUS_TERMS", "project_ctx": "LIMBUS_CONTEXT",
               "name": "边狱巴士", "parent": None,
               "layout": "first_zh", "layers": ("term", "ctx"),
               # 2026-11-25 自动选模式：高判别边狱特征词
               "markers": ("边狱巴士", "边狱公司", "Limbus", "Limbus Company",
                           "但丁", "维吉尔", "浮士德", "堂吉诃德", "希斯克利夫",
                           "以实玛利", "良秀", "辛克莱", "罗佳", "格里高尔"),
               "sidecar": None},
    # 2026-10-30 影之刃零（Phantom Blade Zero）英语原声+谷翻实况
    "pbz": {"terms": "PBZ_TERMS", "ctx": "PBZ_CONTEXT",
            "project_terms": "PBZ_TERMS", "project_ctx": "PBZ_CONTEXT",
            "name": "影之刃零", "parent": None,
            "layout": "first_zh", "layers": ("term", "ctx"),
            "markers": (), "sidecar": None},
    # pgr 侧车整行覆盖模式：无术语表（引擎 __EMPTY__），无投影槽
    "pgr": {"terms": "__EMPTY__", "ctx": None,
            "project_terms": None, "project_ctx": None,
            "name": None, "parent": None,
            "layout": "sidecar", "layers": ("override:pgr",),
            "markers": (), "sidecar": PGR_OVERRIDES_SRC},
    # 2026-11-04 战双英文原声（余辉/光伏/丝带/克洛伊 全是正常中文词，禁裸键）
    # 2026-11-22 降级子键：pgren → pgr-en（parent=pgr）
    "pgr-en": {"terms": "PGR_EN_TERMS", "ctx": "PGR_EN_CONTEXT",
               "project_terms": "PGR_EN_TERMS", "project_ctx": "PGR_EN_CONTEXT",
               "name": "战双-英文", "parent": "pgr",
               "layout": "first_zh", "layers": ("term", "ctx", "exclude"),
               # 2026-11-25 自动选模式：高判别战双特征词（≥2 命中认出，避免泛词误判）
               "markers": ("战双", "帕弥什", "Punishing Gray Raven", "PGR", "构造体",
                           "卡列尼娜", "比安卡", "库洛姆", "赛琳娜", "薇拉", "露西亚",
                           "丽芙", "神威", "渡边", "艾拉", "七实", "蒲牢"),
               "sidecar": None},
    # 2026-11-03 战双日语原声（联动朗读直播）：参考行日语，与 pgr-en 互斥
    # 2026-11-22 降级子键：pgrja → pgr-ja（parent=pgr）
    "pgr-ja": {"terms": "JA_PGR_TERMS", "ctx": "JA_PGR_CONTEXT",
               "project_terms": "JA_PGR_TERMS", "project_ctx": "JA_PGR_CONTEXT",
               "name": "战双-日语", "parent": "pgr",
               "layout": "first_zh", "layers": ("term", "ctx"),
               "markers": (), "sidecar": None},
    # 2026-10-21 宝可梦城镇主题
    "pkm": {"terms": "POKEMON_TERMS", "ctx": "POKEMON_CONTEXT",
            "project_terms": "POKEMON_TERMS", "project_ctx": "POKEMON_CONTEXT",
            "name": "宝可梦城镇主题", "parent": None,
            "layout": "first_zh", "layers": ("term", "ctx"),
            "markers": (), "sidecar": None},
    # react 引擎用 REACT_CONTEXT，但无实体投影语境槽
    "react": {"terms": "REACT_TERMS", "ctx": "REACT_CONTEXT",
              "project_terms": "REACT_TERMS", "project_ctx": None,
              "name": "音乐点评", "parent": None,
              "layout": "first_zh", "layers": ("term", "ctx"),
              "markers": (), "sidecar": None},
    # 2026-11-15 星之救援者（Star Savior）英语原声+谷翻评测
    "ssv": {"terms": "SSV_TERMS", "ctx": "SSV_CONTEXT",
            "project_terms": "SSV_TERMS", "project_ctx": "SSV_CONTEXT",
            "name": "星之救援者", "parent": None,
            "layout": "first_zh", "layers": ("term", "ctx"),
            "markers": (), "sidecar": None},
    # 2026-11-18 TGA 2026 游戏大奖直播（英语原声 + 微软翻译）
    "tga26": {"terms": "TGA_TERMS", "ctx": "TGA_CONTEXT",
              "project_terms": "TGA_TERMS", "project_ctx": "TGA_CONTEXT",
              "name": "TGA 2026 游戏大奖", "parent": None,
              "layout": "first_zh", "layers": ("term", "ctx"),
              "markers": (), "sidecar": None},
    # 2026-11-21 鸣潮 4.0 IGN 实机演示韩语反应片
    # 2026-11-22 降级子键：wuwa40ign → wuwa-40ign（parent=wuwa 为逻辑组名）
    "wuwa-40ign": {"terms": "KO_TERMS", "ctx": "WW40IGN_CONTEXT",
                   "project_terms": "KO_TERMS", "project_ctx": "WW40IGN_CONTEXT",
                   "name": "鸣潮-4.0IGN", "parent": "wuwa",
                   "layout": "ko_zh",
                   "layers": ("term", "ctx", "exclude", "override:ko", "override_nocjk"),
                   "markers": (), "sidecar": WW40IGN_OVERRIDES_SRC},
    # 2026-11-19 鸣潮 4.0 新联邦 PV 韩语反应片
    # 2026-11-22 降级子键：wuwa40ko → wuwa-40ko（parent=wuwa 为逻辑组名）
    "wuwa-40ko": {"terms": "KO_TERMS", "ctx": "WW40KO_CONTEXT",
                  "project_terms": "KO_TERMS", "project_ctx": "WW40KO_CONTEXT",
                  "name": "鸣潮-4.0韩语", "parent": "wuwa",
                  "layout": "ko_zh",
                  "layers": ("term", "ctx", "exclude", "override:ko", "override_nocjk"),
                  "markers": (), "sidecar": WW40KO_OVERRIDES_SRC},
    # 2026-11-23 鸣潮 4.0 新地区 PV/新角色实机 韩语反应片（951 cue）
    # 2026-11-23 降级子键：wuwa40pv → wuwa-40pv（parent=wuwa 为逻辑组名）
    "wuwa-40pv": {"terms": "KO_TERMS", "ctx": "WW40PV_CONTEXT",
                  "project_terms": "KO_TERMS", "project_ctx": "WW40PV_CONTEXT",
                  "name": "鸣潮-4.0新地区PV", "parent": "wuwa",
                  "layout": "ko_zh",
                  "layers": ("term", "ctx", "exclude", "override:ko", "override_nocjk"),
                  "markers": (), "sidecar": WW40PV_OVERRIDES_SRC},
    # 2026-11-24 鸣潮 4.0 新联邦实机 英语 reaction 片（251 cue）
    #   P2-1：与 bi 同表同版式 → 图层完全对齐（侧车 251 条全覆盖，对齐后零漂移）
    "wuwa-40reveal": {"terms": "BILINGUAL_TERMS", "ctx": "CONTEXT_MAP",
                      "project_terms": "BILINGUAL_TERMS", "project_ctx": "CONTEXT_MAP",
                      "name": "鸣潮-4.0新联邦实机", "parent": "wuwa",
                      "layout": "bilingual",
                      "layers": ("term", "ctx", "exclude", "word_map",
                                 "override:bi", "override_nocjk"),
                      "markers": (), "sidecar": WW40REVEAL_OVERRIDES_SRC},
    # 2026-11-21 燕云十六声（Where Winds Meet）滹沱实机片
    "wwm": {"terms": "WWM_TERMS", "ctx": "WWM_CONTEXT",
            "project_terms": "WWM_TERMS", "project_ctx": "WWM_CONTEXT",
            "name": "燕云十六声", "parent": None,
            "layout": "first_zh", "layers": ("term", "ctx", "override:bi"),
            "markers": (), "sidecar": None},
    # 2026-10-25 wwoc 补语境槽（多游戏韩语片歧义错形）
    "wwoc": {"terms": "WWOC_TERMS", "ctx": "WWOC_CONTEXT",
             "project_terms": "WWOC_TERMS", "project_ctx": "WWOC_CONTEXT",
             "name": "综合手游OST", "parent": None,
             "layout": "first_zh", "layers": ("term", "ctx"),
             "markers": (), "sidecar": None},
    # 2026-09-14 塞尔达传说（引擎用 ZELDA_TERMS，无语境槽、无投影槽）
    "zel": {"terms": "ZELDA_TERMS", "ctx": None,
            "project_terms": None, "project_ctx": None,
            "name": None, "parent": None,
            "layout": "first_zh", "layers": ("term",),
            "markers": (), "sidecar": None},
    "zho": {"terms": "ZH_ONLY_TERMS", "ctx": None,
            "project_terms": "ZH_ONLY_TERMS", "project_ctx": None,
            "name": "中文行专属", "parent": None,
            "layout": "first_zh", "layers": ("term",),
            "markers": (), "sidecar": None},
}

# 简单模式旗标（--<mode> 直接设 mode）。排除：bi（默认无旗标）、fix-en（--fix-en 布尔）、
#   12 个「游戏-细类」子键（2026-11-22 变体键降级后不再设顶层简单旗标，原 --ja/--ko/--akja/
#   --akko/--arcak/--endobi/--endoko/--jpe/--pgren/--pgrja 一并移除，子键经 --mode <子键>/别名进入；
#   其中 wuwa-40ko/wuwa-40ign 另走一键重跑链，需 info+侧车装配）、
#   wwm（原 cli 无 --wwm 简单旗标，仅经 --mode wwm 别名进入；擅自补旗标会让 --wwm 从「忽略落 bi」漂移成 wwm）。
_NO_SIMPLE_FLAG = {"bi", "fix-en", "wwm",
                   "ak-ja", "ak-ko", "ak-arcaea",
                   "endo-bi", "endo-ko", "endo-ja",
                   "wuwa-ja", "wuwa-ko", "wuwa-40ko", "wuwa-40ign", "wuwa-40pv", "wuwa-40reveal",
                   "pgr-en", "pgr-ja"}
_MODE_FLAGS = {"--" + m: m for m in MODE_REGISTRY if m not in _NO_SIMPLE_FLAG}

# --mode 别名 → 模式（精确沿用原 elif 链 + 三元兜底的全部别名；未列出的 --mode 值落 bi）。
#   ⚠ 别名集必须与原链逐字一致：react/wwoc 等原本就没有 --mode 别名，不可擅自补全，否则行为漂移。
#   2026-11-22 变体键降级：指向被重命名键的别名值同步改新键（ja/japanese→wuwa-ja、ko/korean→wuwa-ko、
#     akja 组→ak-ja、arcak 组→ak-arcaea）；末段新增「旧顶层键 → 新子键」兼容映射（含原本无
#     --mode 别名的 jpe/endobi/endoko/akko/pgren/pgrja/wuwa40ko/wuwa40ign，仅作旧键归一入口，
#     normalize_mode 同源），除此之外不新增任何别名。
_MODE_ALIASES = {
    # 三元兜底组（值随 2026-11-22 重命名同步改新子键）
    "ja": "wuwa-ja", "japanese": "wuwa-ja",
    "ko": "wuwa-ko", "korean": "wuwa-ko",
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
    "arcak": "ak-arcaea", "arcakn": "ak-arcaea", "arcaea_arknights": "ak-arcaea", "arcaea×arknights": "ak-arcaea",
    "arcaea明日方舟": "ak-arcaea", "arcaea方舟": "ak-arcaea", "arcaea联动": "ak-arcaea",
    "tga26": "tga26", "tga2026": "tga26", "tga": "tga26", "thegameawards": "tga26",
    "gameawards": "tga26", "游戏大奖": "tga26", "tga直播": "tga26",
    "wwm": "wwm", "wherewindsmeet": "wwm", "where_winds_meet": "wwm",
    "燕云十六声": "wwm", "燕云": "wwm", "yanyun": "wwm",
    "gfl2": "gfl2", "gf2": "gfl2", "exilium": "gfl2", "gfl2exilium": "gfl2",
    "少女前线2": "gfl2", "少女前线2：追放": "gfl2", "追放": "gfl2", "少前2": "gfl2",
    "akja": "ak-ja", "ak_ja": "ak-ja", "arknights_ja": "ak-ja", "arknightsja": "ak-ja",
    "明日方舟日语": "ak-ja", "日语原声明日方舟": "ak-ja",
    # 2026-11-22 旧顶层变体键 → 新「游戏-细类」子键（兼容归一映射，供 --mode 旧键与
    #   normalize_mode / learned 库 / KB 旧键解析；jpe/endobi/endoko/akko/pgren/pgrja/
    #   wuwa40ko/wuwa40ign 原本无 --mode 别名，此处属旧→新兼容而非补全模式别名）
    "jpe": "endo-ja", "endobi": "endo-bi", "endoko": "endo-ko",
    "akko": "ak-ko", "pgren": "pgr-en", "pgrja": "pgr-ja",
    "wuwa40ko": "wuwa-40ko", "wuwa40ign": "wuwa-40ign", "wuwa40pv": "wuwa-40pv",
    "wuwa40reveal": "wuwa-40reveal",
}


def normalize_mode(m):
    """模式键归一：registry 键原样返回；旧顶层变体键/既有别名 → 新「游戏-细类」子键。

    供 engine/cli/kb/learn/audit/sync 在消费入口统一归一（旧键 akja/ja/jpe/… 与别名
    arknights_ja/… 均落新键），保 learned 库/KB 中以旧键沉淀的记录可解析；
    未知键原样返回（是否落 bi 由消费面决策）。
    """
    return m if m in MODE_REGISTRY else _MODE_ALIASES.get(m, m)

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
    "wuwa38lilyko": {"mode": "wuwa-ko", "info": WW38LILY_KO_INFO, "overrides": WW38LILY_KO_OVERRIDES_SRC, "ko": True},
    "wuwa38s": {"mode": "bi", "info": WW38S_INFO, "overrides": WW38S_OVERRIDES_SRC},
    "wuwa38b": {"mode": "bi", "info": WW38B_INFO, "overrides": WW38B_OVERRIDES_SRC},
    "wuwa38j": {"mode": "bi", "info": WW38_J_INFO, "overrides": WW38_J_OVERRIDES_SRC},
    "wuwa38g": {"mode": "bi", "info": WW38G_INFO, "overrides": WW38G_OVERRIDES_SRC},
    "wuwa40": {"mode": "bi", "info": WW40_INFO, "overrides": WW40_OVERRIDES_SRC},
    "wuwa40ko": {"mode": "wuwa-40ko", "info": WW40KO_INFO, "overrides": WW40KO_OVERRIDES_SRC, "ko": True},
    "wuwa40ign": {"mode": "wuwa-40ign", "info": WW40IGN_INFO, "overrides": WW40IGN_OVERRIDES_SRC, "ko": True},
    "wuwa40pv": {"mode": "wuwa-40pv", "info": WW40PV_INFO, "overrides": WW40PV_OVERRIDES_SRC, "ko": True},
    "wuwa40reveal": {"mode": "wuwa-40reveal", "info": WW40REVEAL_INFO, "overrides": WW40REVEAL_OVERRIDES_SRC},
    "wuwa40ja": {"mode": "wuwa-ja", "info": WW40JA_INFO, "overrides": WW40JA_OVERRIDES_SRC},
    "wuwasol": {"mode": "bi", "info": WUSOL_INFO, "overrides": WUSOL_OVERRIDES_SRC},
    "wuwaall": {"mode": "bi", "info": WUWAALL_INFO, "overrides": WUWAALL_OVERRIDES_SRC, "zh_first": True},
    "arcakamiya": {"mode": "ak-arcaea", "info": ARCAK_AMIYA_INFO, "overrides": ARCAK_AMIYA_OVERRIDES_SRC},
}

# 模式 -> 无条件变体表 / 条件变体表（实体注册时的投影目标）
# ⚠ 字面量顺序被 kb._kb_view 的实体 modes 累积依赖（kb-export/lookup/lint 输出顺序），
#   不可改为字母序推导；与 MODE_REGISTRY 的 project_terms 由文件末守卫强制一致。
_MODE_TERM_TABLE = {
    "bi": "BILINGUAL_TERMS", "wuwa-ja": "JA_TERMS", "endo-ja": "JA_ENDFIELD_TERMS",
    "wuwa-ko": "KO_TERMS", "wuwa-40ko": "KO_TERMS", "wuwa-40ign": "KO_TERMS", "wuwa-40pv": "KO_TERMS", "wwoc": "WWOC_TERMS", "endo": "ENDFIELD_TERMS",
    "wuwa-40reveal": "BILINGUAL_TERMS",
    "ak": "AK_TERMS", "ak-ko": "AK_KO_TERMS", "zho": "ZH_ONLY_TERMS",
    "pgr-en": "PGR_EN_TERMS", "react": "REACT_TERMS",
    "endo-bi": "ENDFIELD_BI_TERMS", "endo-ko": "ENDFIELD_KO_TERMS",
    "pkm": "POKEMON_TERMS",
    "limbus": "LIMBUS_TERMS",
    "ffrs": "FFRS_TERMS",
    "pbz": "PBZ_TERMS",
    "ff14": "FF14_TERMS",
    "ssv": "SSV_TERMS",
    "ak-arcaea": "ARCAK_TERMS",
    "wwm": "WWM_TERMS",
    "gfl2": "GFL2_TERMS",
    "tga26": "TGA_TERMS",
    "pgr-ja": "JA_PGR_TERMS",
    # ak-ja 引擎用 AK_TERMS∪AK_JA_TERMS 合并表，投影只登记增量那张
    "ak-ja": "AK_JA_TERMS",
}

_MODE_CTX_TABLE = {
    "bi": "CONTEXT_MAP", "wuwa-ja": "JA_CONTEXT", "endo-ja": "JA_ENDFIELD_CONTEXT",
    "wuwa-40reveal": "CONTEXT_MAP",
    "ak-ko": "AK_KO_CONTEXT", "wuwa-ko": "KO_CONTEXT", "wuwa-40ko": "WW40KO_CONTEXT", "wuwa-40ign": "WW40IGN_CONTEXT", "wuwa-40pv": "WW40PV_CONTEXT", "ak": "AK_CONTEXT",
    "endo-ko": "ENDFIELD_KO_CONTEXT", "pkm": "POKEMON_CONTEXT",
    "wwoc": "WWOC_CONTEXT",
    # endo 不建槽：单语片源每 cue 仅一行，ref 即该中文行本身，英文锚定永不命中
    "endo-bi": "ENDFIELD_BI_CONTEXT",
    "limbus": "LIMBUS_CONTEXT",
    "ffrs": "FFRS_CONTEXT",
    "pbz": "PBZ_CONTEXT",
    "ff14": "FF14_CONTEXT",
    "pgr-ja": "JA_PGR_CONTEXT",
    "ak-ja": "AK_JA_CONTEXT",
    "pgr-en": "PGR_EN_CONTEXT",
    "ssv": "SSV_CONTEXT",
    "ak-arcaea": "ARCAK_CONTEXT",
    "wwm": "WWM_CONTEXT",
    "gfl2": "GFL2_CONTEXT",
    "tga26": "TGA_CONTEXT",
}

_MODE_NAMES = {
    "bi": "中英双语", "wuwa-ja": "鸣潮-日语", "endo-ja": "终末地-日语",
    "wuwa-ko": "鸣潮-韩语", "wuwa-40ko": "鸣潮-4.0韩语", "wuwa-40ign": "鸣潮-4.0IGN", "wuwa-40pv": "鸣潮-4.0新地区PV", "wwoc": "综合手游OST", "endo": "终末地",
    "wuwa-40reveal": "鸣潮-4.0新联邦实机",
    "ak": "明日方舟", "ak-ko": "明日方舟-韩语", "zho": "中文行专属",
    "pgr-en": "战双-英文", "react": "音乐点评", "endo-bi": "终末地-双语", "fix-en": "英文参考行修正",
    "endo-ko": "终末地-韩语", "pkm": "宝可梦城镇主题",
    "limbus": "边狱巴士",
    "ffrs": "最终幻想：共鸣",
    "pbz": "影之刃零",
    "ff14": "最终幻想14",
    "pgr-ja": "战双-日语",
    "ak-ja": "明日方舟-日语",
    "ssv": "星之救援者",
    "ak-arcaea": "明日方舟-Arcaea",
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
def _check_registry_layers():
    """P2-1 图层字段守卫：四条新字段必须齐全且取值合法。

    2026-11-24 起引擎的版式分发、图层开关、片源识别、缺省侧车全部只读本表，
    因此这四字段写成非法值（拼错的 layout / 未知 layer token / 两个 override 槽 /
    非 tuple 的 markers）必须在 import 期炸掉，而不是运行期静默降级。
    """
    for m, e in MODE_REGISTRY.items():
        for f in ("layout", "layers", "markers", "sidecar"):
            if f not in e:
                raise SystemExit(f"MODE_REGISTRY[{m!r}] 缺字段 {f!r}（P2-1 图层驱动必填）")
        if e["layout"] not in LAYOUTS:
            raise SystemExit(
                f"MODE_REGISTRY[{m!r}].layout={e['layout']!r} 非法，可选 {LAYOUTS}")
        layers = e["layers"]
        if not isinstance(layers, (tuple, list)) or not layers:
            raise SystemExit(f"MODE_REGISTRY[{m!r}].layers 必须是非空 tuple/list")
        unknown = [x for x in layers if x not in LAYER_TOKENS]
        if unknown:
            raise SystemExit(f"MODE_REGISTRY[{m!r}].layers 含未知图层 {unknown}")
        ov = [x for x in layers if str(x).startswith("override:")]
        if len(ov) > 1:
            raise SystemExit(f"MODE_REGISTRY[{m!r}].layers 只能有一个 override 槽，实得 {ov}")
        if ov and e["layout"] not in ("first_zh", "bilingual", "ko_zh", "ak_zh", "sidecar"):
            raise SystemExit(
                f"MODE_REGISTRY[{m!r}] layout={e['layout']} 不支持侧车覆盖，却声明 {ov[0]}")
        if e["layout"] == "sidecar" and not ov:
            raise SystemExit(f"MODE_REGISTRY[{m!r}] layout=sidecar 必须声明 override 槽")
        if "override_nocjk" in layers and not ov:
            raise SystemExit(f"MODE_REGISTRY[{m!r}] override_nocjk 需配合 override:*")
        if "word_map" in layers and e["layout"] != "bilingual":
            raise SystemExit(f"MODE_REGISTRY[{m!r}] word_map 仅 bilingual 版式可用")
        if not isinstance(e["markers"], (tuple, list)):
            raise SystemExit(f"MODE_REGISTRY[{m!r}].markers 必须是 tuple/list")
        if e["sidecar"] is not None and not isinstance(e["sidecar"], str):
            raise SystemExit(f"MODE_REGISTRY[{m!r}].sidecar 必须是 str 或 None")


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
_check_registry_layers()

