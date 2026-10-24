# -*- coding: utf-8 -*-
# @version 2.7.0
"""术语/实体数据表

源：subtitle_calib_merged.py L10202-L10409 @ 97d7d463（2026-10-24 冻结快照）
"""
import io
import os
import re
import shutil
import sys
import unicodedata



# ============================================================
# 2026-09-22 音乐曲库 · **有歌词（人声）歌曲**多语对照
#   ⚠ 只收**有人声演唱**的歌（角色印象曲 / 主题曲 / 活动曲 / 合作曲，
#     含游戏内出现过的人声曲与官方 PV 人声曲）；**不收**纯器乐 BGM/OST 伴奏。
#   戒律（用户 2026-09-22 指定）：
#     ① 曲名在四语服常为**各自独立的官方名**（非直译），**有官方外文名才填**；
#     ② **只有单一语种官方名的，不翻译、保留原语言**（en/ja/ko 留空）；
#     ③ 严禁臆造译名；本表只作多语元数据（variants 一律留空，音译错形待片源实测沉淀）。
#   格式：(官方曲名, en, ja, ko)；空串 = 该语种无独立官方名。
#   来源：百度百科「鸣潮」游戏原声、萌娘百科「鸣潮音乐列表/塞壬唱片」、歌词坊 gecifang、
#         觅歌词「鸣潮人声歌曲合集」、巴哈姆特 EP 一览、Wikiwand 鸣潮音乐列表、Shazam MSR。
# ============================================================
_MUSIC_WW = [                       # 鸣潮 · 先约电台 EP（角色印象曲）+ 单曲
    # --- EP0 / 公测 EP ---
    ("Saving Light", "Saving Light", "", ""),
    ("Waking of a World", "Waking of a World", "", ""),
    # --- 2026-10-24 《致予新世界》演唱会二校补目（官方中文名）---
    ("拉海洛之心", "Heart of Laoy", "", ""),
    ("小小奇迹", "A Small Miracle", "", ""),
    ("远航星的告别", "Bon Voyage", "", ""),
    # --- EP1.x ---
    ("往岁乘霄", "Thawing Fates", "過ぎし乗霄山の歳月", "승소산의 메아리"),
    ("月华如愿", "", "", ""),
    ("未尽之歌", "An Unfinished Song", "未完成の歌", "끝나지 않은 노래"),
    ("一千万种可能", "A Million Possibilities", "", ""),
    # --- EP2.x ---
    ("昼梦盛宴", "Grand Feast Daydream", "昼夢グランドフィースト", "꿈의 카니발"),
    ("ONE", "ONE", "", ""),
    ("Daisy Crown", "Daisy Crown", "", ""),
    ("不羁灵魂之王（虽然是自封）（但包的）",
     "THE KING OF WAYWARD SOULS (SELF PROCLAIMED)(BUT DESTINED)", "", ""),
    ("沉沦幻海", "Elusive Seas", "沈む幻海", "바닷속 환상의 자장가"),
    ("下班？", "", "", ""),
    ("Lulala! Lululala!", "", "", ""),
    ("Against the Tide（逆潮）", "Against the Tide", "", ""),
    ("RUNNING FOR YOUR LIFE（无所遁藏）", "RUNNING FOR YOUR LIFE", "", ""),
    ("彼岸的安魂曲", "Requiem of the Beyond", "彼岸のレクイエム", "피안의 진혼곡"),
    ("Endless Pulse（烈血湍流）", "Endless Pulse", "", ""),
    ("今夜不属于月亮（There's No Moonlight This Night）",
     "There's No Moonlight This Night", "", ""),
    ("远光点（APHELION [Galbrena's Lullaby]）",
     "APHELION [Galbrena's Lullaby]", "", ""),
    ("不辞远", "", "", ""),
    ("破茧之华", "Slashing Bloom", "切り咲く", ""),
    # --- EP3.x ---
    ("Catch Me If You Can", "Catch Me If You Can", "", ""),
    ("Unwritten in the Stars（若能触及群星）", "Unwritten in the Stars", "", ""),
    ("纸飞机", "", "", ""),
    ("Thawing Light（融光）", "Thawing Light", "", ""),
    ("L!!!!ght", "L!!!!ght", "", ""),
    ("坠入虚无（Decensus Ad Nihilum）", "Decensus Ad Nihilum", "", ""),
    ("直到下次再见（Dasvidaniya）", "Dasvidaniya", "", ""),
    ("愿（One More Wish）", "One More Wish", "", ""),
    # 2026-10-22 补：3.5 玄方区域主题曲，黄霄雲演唱（官方中文《定玄》，英 Eisodus；
    #   杨秉音作曲、申名利作词）。
    ("定玄（Eisodus）", "Eisodus", "", ""),
    ("Replay（重映）", "Replay", "", ""),
    ("待春归", "", "", ""),
    # --- 飞行雪绒 EP / 特辑 / 周年 ---
    ("碎花", "", "", ""),
    ("靛青宇宙", "", "", ""),
    ("夏空的歌", "", "", ""),
    ("Everflow", "Everflow", "", ""),
    # --- 单曲（官方发行，有人声）---
    ("Never Let It Go", "Never Let It Go", "", ""),
    ("奔流，因你不息", "", "", ""),
    ("潮骚レゾナンス", "", "潮騒レゾナンス", ""),
    ("Turning Around（余烬重燃）", "Turning Around", "", ""),
    ("Brand New Sky（新世界的天空）", "Brand New Sky", "", ""),
    ("星祝", "", "", ""),
    ("To the Finale（未黯之光）", "To the Finale", "", ""),
    ("Beautiful Tomorrow", "Beautiful Tomorrow", "", ""),
    ("Dawnbreaker", "Dawnbreaker", "", ""),
    ("Deadline Disco（极限迪斯科）", "Deadline Disco", "", ""),
]

_MUSIC_WW_BGM = [                   # 鸣潮 · 黎那汐塔 OST（纯音乐 BGM；官方中文名已核实）
    # 2026-10-23：鸣潮 2.0 reaction 片沉淀。出处：《鸣潮》黎那汐塔篇 OST Vol.1
    #   《幻昼狂想》（2025-01-03）曲目表，QQ音乐/酷狗/Apple Music 三源一致。
    #   日/韩无独立官方名，留空勿臆造（多语戒律）。
    ("故风吟游之地", "Where Wind Whispers", "", ""),   # 拂风水畔 BGM
    ("微风吹拂的村庄", "Wind-kissed Haven", "", ""),    # 埃格拉镇 BGM
]

_MUSIC_AK = [                       # 明日方舟 · 塞壬唱片（人声曲；多数无官方中文，保留英文）
    ("Grown-up's Paradise", "Grown-up's Paradise", "", ""),
    ("铁花飞", "TIE HUA FEI", "", ""),
    ("Speed of Light", "Speed of Light", "", ""),
    ("Running In The Dark", "Running In The Dark", "", ""),
    ("Everything's Alright", "Everything's Alright", "", ""),
    ("Radiant", "Radiant", "", ""),
    ("Mystic Light Quest", "Mystic Light Quest", "", ""),
    ("浸春芜", "", "", ""),
    ("Bluish Light", "Bluish Light", "", ""),
    ("Little Wish", "Little Wish", "", ""),
    ("Boiling Blood", "Boiling Blood", "", ""),
    ("Renegade", "Renegade", "", ""),
    ("秋绪", "", "", ""),
    ("春弦", "", "", ""),
    ("示岁", "", "", ""),
    ("独行长路", "", "", ""),
    ("故乡的风", "", "", ""),
    ("夏浪", "", "", ""),
    ("尽波澜", "", "", ""),
    ("更阑影", "", "", ""),
    ("观心", "", "", ""),
    ("冬涤", "", "", ""),
    ("从那高地上远眺", "", "", ""),
    ("Ensheath", "Ensheath", "", ""),
    ("Believing", "Believing", "", ""),
    ("Immutable", "Immutable", "", ""),
    ("Miss You", "Miss You", "", ""),
    ("Blade Catcher", "Blade Catcher", "", ""),
    ("Sealed", "Sealed", "", ""),
    ("The Walk", "The Walk", "", ""),
    ("Paper Boat", "Paper Boat", "", ""),
    ("Follow Your Heart", "Follow Your Heart", "", ""),
    ("When We Were the Most Beautiful", "When We Were the Most Beautiful", "", ""),
    ("Across the Wind", "Across the Wind", "", ""),
    ("Ständchen", "Ständchen", "", ""),
    ("Stainless Heart", "Stainless Heart", "", ""),
    ("Spark For Dream", "Spark For Dream", "", ""),
    ("Echoism", "Echoism", "", ""),
    ("Revealing", "Revealing", "", ""),
    ("The After", "The After", "", ""),
    ("Sentenced", "Sentenced", "", ""),
    ("Somniomancer (Null Set)", "Somniomancer (Null Set)", "", ""),
    ("Dormant Craving", "Dormant Craving", "", ""),
    ("A Sweet Rendez-vous", "A Sweet Rendez-vous", "", ""),
    ("碧い瞳の中に（in your blue eyes）", "in your blue eyes", "碧い瞳の中に", ""),
    ("Untitled world", "Untitled world", "", ""),
    ("Alive", "Alive", "", ""),
    ("R.I.P.", "R.I.P.", "", ""),
    ("ACHE in PULS", "ACHE in PULS", "", ""),
    ("Misty Memory", "Misty Memory", "", ""),
    ("冲破穹顶", "", "", ""),
    ("熠曲丰碑", "", "", ""),
    ("时序花圃", "", "", ""),
    ("雾色秘访", "", "", ""),
    ("镜花水月", "", "", ""),
    ("愚人曲", "", "", ""),
    ("赴大荒", "", "", ""),
    ("Vows of the Sea", "Vows of the Sea", "", ""),
    ("Storyteller", "Storyteller", "", ""),
    ("Broken Sun", "Broken Sun", "", ""),
    ("Muse", "Muse", "", ""),
    ("Whistle Stop", "Whistle Stop", "", ""),
    ("未许之地", "", "", ""),
    ("无名策", "", "", ""),
    ("Wanna Know Me?", "Wanna Know Me?", "", ""),
    ("辞岁行", "", "", ""),
    ("反常光谱", "", "", ""),
    ("次生预案", "", "", ""),
    ("无忧梦呓", "", "", ""),
    ("促融共竞", "", "", ""),
]

_MUSIC_ENDO = [                     # 终末地 · 铁痕电台-MSR（人声曲；曲名多为中文，保留原语言）
    ("宜", "", "", ""),
    ("万象将醒", "", "", ""),
    ("闪焰预兆", "", "", ""),
    ("冷烬", "", "", ""),
    ("日晕", "", "", ""),
    ("折光成像", "", "", ""),
    ("回燃", "", "", ""),
    ("最喜欢的一张", "", "", ""),
    ("造物道别", "", "", ""),
    ("像素绘涂", "", "", ""),
    ("寻觅漫步", "", "", ""),
    ("反引力悬浮", "", "", ""),
    ("夕流", "", "", ""),
    ("编织光流", "For Your Name", "", ""),
]



# ============================================================
# 2026-10-15 《A Complete Crashout Regarding Wuthering Waves》精校沉淀
#   （英文原声·谷歌机翻双语，6934 cue，bi 模式。机械遍 650 处之外仍有 500+
#     名词漏校，靠新增的 `audit` 子命令「三扫」收口后逐条回填；官方名经
#     库洛官网 mc.kurogames.com / 百度百科 / 萌娘百科核验。）
#   戒律：**常用词一律走 ctx 参考行锚定，绝不裸键**——本片谷翻把同一个专名
#     译成 10~20 种形态，其中大量是正常词（波浪/浪花/风化/天气/风浪/断裂/
#     裂隙/帝国/紫水晶/欣/疤…），裸键会满片误伤；生僻音译组合才收无条件变体。
#   ⚠ 另一条硬约束：ctx 是**按列表顺序逐条全量替换**，因此
#     ① 短键必须排在长键之后（罗伯特 先于 罗伯）；
#     ② 同一行可能被多条规则命中的常用词（波浪/浪花/风化/风浪/天气）**一律不收**，
#        否则「风化的波浪」会被替换两次变成「鸣潮的鸣潮」。
#     这类残留交给 `audit` 子命令扫 3 兜底（参考行有 Weathering 而中文行缺 鸣潮）。
#   ⚠ 刻意不收：裸「疤」（#3117「伤痕身上有疤吗」是字面义）。
# ============================================================
_WW_ANCHOR = r"Weathering|Wuthering|Wintering|Withering|Wooa|Wua|Wuar|WOA"

_FRACT_ANCHOR = r"Fractus|fracters|Fractsidus"

_GINSHI_ANCHOR = r"Ginshi|Jinhsi|Ginhi|Jinshi"

