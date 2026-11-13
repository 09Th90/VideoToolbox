# -*- coding: utf-8 -*-
# @version 2.9.0
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
    ("致新世界（Saving Light）", "Saving Light", "", ""),
    ("Waking of a World", "Waking of a World", "", ""),
    # --- 2026-10-24 《致予新世界》演唱会二校补目（官方中文名）---
    ("「拉海洛」之心", "Heart of Lahai-Roi", "", ""),
    ("致予新世界", "To the New World", "", ""),
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
    # --- 2026-10-27 鸣潮演唱会/3.3 片二次校准补登 ---
    # 2026-11-07 补 en：《旋律渐叙 Melodic Verses》曲序表官方英文＝When the Bird Glides
    #   Across the Sky；一轮记的 "Glides In" 是 ASR 截断（本片 #53 主播读的才是全名）。
    ("当飞鸟划过天空", "When the Bird Glides Across the Sky", "", ""),
    ("愿戴荣光坠入天渊", "", "", ""),
    ("星炬不熄", "", "", ""),
    ("坠入虚无（Decensus Ad Nihilum）", "Decensus Ad Nihilum", "", ""),
    ("直到下次再见（Dasvidaniya）", "Dasvidaniya", "", ""),
    ("愿（One More Wish）", "One More Wish", "", ""),
    # 2026-10-22 补：3.5 玄方区域主题曲，黄霄雲演唱（官方中文《定玄》，英 Eisodus；
    #   杨秉音作曲、申名利作词）。
    ("定玄（Eisodus）", "Eisodus", "", ""),
    ("Replay（重映）", "Replay", "", ""),
    # 2026-11-04 补 en：穗穗 先约电台 EP3.5 印象曲，官方中文《待春归》（钱润玉演唱）。
    #   依据：鸣潮官方微博 EP3.5 投稿 + Apple Music 美服单曲条目 6795498274
    #   （"When Spring Returns" = 鳴潮先約電台 & 錢潤玉），两源交叉一致。
    #   日/韩无独立官方曲名，留空勿臆造（多语戒律）。
    ("待春归", "When Spring Returns", "", ""),
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
    # --- 2026-11-04 沉淀：SenWarchief《Wuthering Waves Reaction! Character and Area
    #     Songs, ver 3.5 - 3.7》（574 cue，英语原声 + 谷翻）逐句复核。
    #     依据：Apple Music 美服/国区同一发行条目交叉（玄方篇 OST Vol.2《云影仙迹》
    #     6803333112；先约电台锁暝 EP 四语版本），曲名互不直译，逐语查证。 ---
    #   清宵角色主题曲，玄觞演唱，杨秉音系；日/韩无独立官方名，留空。
    ("清仙谣", "Clarity of the Transcendent", "", ""),
    #   锁暝 先约电台 EP3.7 印象曲（中：子弥／英：Lime／日：Hanon／韩：이루리，
    #   四语各自独立发行；日/韩**曲名**未逐条核实，留空勿臆造）。
    #   ⚠《契阔》是 3.7 锁暝**角色 PV 标题**（TapTap CV 表），不是曲名，勿混。
    ("千劫起，一念生", "Oaths Unbent", "", ""),
    # --- 2026-11-07 鸣潮 OST 6 reaction（Yuuma，331 cue）二校补登 ---
    #   官方依据：《无名长诗》＝黎那汐塔篇 OST Vol.7（2025-07-05，Apple Music 国区
    #   1824610259 / TapTap 上架公告，19 曲逐条对齐）；悠忽舞于梦中＝罗蕾莱飞行挑战
    #   BGM（Shazam/NGA），人声（VISION SOUND credit）；誓约之枷，应许之愿＝英文演唱、
    #   无官方中文歌词（酷我译文明确标注 AI 生成）。日/韩无独立官方名，留空勿臆造。
    ("悠忽舞于梦中", "Dancing Through Fantasies", "", ""),
    ("誓约之枷，应许之愿", "Chains of Oath, Echoes of Promise", "", ""),
    ("致以无名的抗争者", "Ode to the Nameless Martyr", "", ""),
]

_MUSIC_WW_BGM = [                   # 鸣潮 · 黎那汐塔 OST（纯音乐 BGM；官方中文名已核实）
    # 2026-10-23：鸣潮 2.0 reaction 片沉淀。出处：《鸣潮》黎那汐塔篇 OST Vol.1
    #   《幻昼狂想》（2025-01-03）曲目表，QQ音乐/酷狗/Apple Music 三源一致。
    #   日/韩无独立官方名，留空勿臆造（多语戒律）。
    ("故风吟游之地", "Where Wind Whispers", "", ""),   # 拂风水畔 BGM
    ("微风吹拂的村庄", "Wind-kissed Haven", "", ""),    # 埃格拉镇 BGM
    # 2026-11-07 补：黎那汐塔篇 OST Vol.7《无名长诗》曲16（Apple Music 国区 1824610259）。
    #   credit 仅 Gokou；全辑演唱名单（jkinss/Thena A/Tarokiki/Patrick King/馬場崇）无其名
    #   ⇒ 判器乐。同辑曲1《致以无名的抗争者》有 Thena A/Tarokiki/VISION SOUND 主唱，
    #   故该曲仍留人声表，勿混。
    ("泪焰终响", "A Clash of Water and Fire", "", ""),
]

# 2026-11-04 新建：**玄方篇** OST 器乐（3.5-3.7）。
#   为什么不并进 `_MUSIC_WW_BGM`：那张表的注册循环（entities.py）把
#   category 与 note 写死成「黎那汐塔 OST / 经黎那汐塔篇 OST Vol.1《幻昼狂想》核实」，
#   玄方曲目塞进去就会挂上**错误出处**，且 kb-lint 查不出来。
#   依据：Apple Music 美服/国区同一条目交叉 ——
#     Vol.1《万声弥新》(Myriad Notes Ever New, 6789678123) 含《踏玄方》Into Xuanfang（JINGYAN, 3:07）；
#     Vol.3《朝月听尘》(6817719530) 含《溪山入梦》The Dreaming Vale（jkinss, 4:12，碟1-1）；
#     美服 Vol.3 名《Songs for the Waking Moon》(6817719939)，同轨同长同作曲。
#   日/韩无独立官方名，留空勿臆造。
_MUSIC_WW_BGM_XF = [                # 鸣潮 · 玄方篇 OST（纯音乐；官方中文名已核实）
    ("踏玄方", "Into Xuanfang", "", ""),      # 玄方区域曲（ASR 常听成 "Into the wild fire"）
    ("溪山入梦", "The Dreaming Vale", "", ""),  # 梦州区域曲（ASR 常把 Vale 听成 "Veil"）
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
    # 众生行记OST（2025-05-04 塞壬唱片，7 首均无官方中文名，单语保留英文原题；
    # 2026-11-08 补：此前只有 Somniomancer，另 6 首缺失）
    ("Touch of the Law", "Touch of the Law", "", ""),
    ("Halo Universalization", "Halo Universalization", "", ""),
    ("The Pilgrimage", "The Pilgrimage", "", ""),
    ("Faith Enlightenment", "Faith Enlightenment", "", ""),
    ("The Birth", "The Birth", "", ""),
    ("Underneath the Sanctuary", "Underneath the Sanctuary", "", ""),
    ("Somniomancer [null set]", "Somniomancer [null set]", "", ""),
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
    # 2026-11-08 Arknights × Arcaea 联动歌单（kukkikaze）：危机合约#5 光谱行动 / #8 寻昼行动 OST
    ("Operation Spectrum Battle Theme", "Operation Spectrum Battle Theme", "", ""),
    ("Fading Sky", "Fading Sky", "", ""),
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
    # 2026-11-06《HEAVY FLOW!! Argent Flow Trailer & EP REACTION》二次校准新增。
    #   官方依据：微博「干员明河专属单曲《逐星河》MV现已公开」曲目表＝逐星河 /
    #   逐星河 (English Ver.) / 逐星河 (Instrumental)；专辑介绍「夜幕漫漫，星河长明。
    #   循心之所守，逐星河而去。」。英文官方名取自 UP 主双语标题
    #   "EP - Argent Flow [The Starry Flow Winds On] English / Chinese"，
    #   即同一曲的 EN 名（同 "编织光流/For Your Name" 先例）。日/韩无独立官方名 ⇒ 留空。
    ("逐星河", "The Starry Flow Winds On", "", ""),
    # 2026-11-12《Contingency Contract: Indigo OST - CC#β2》Roguenjosh Plays 二校新增：
    #   1.6 危机合约「浸蓝」人声 OST 主题曲，feat. Essenger（feat. 署名写注不入曲名，
    #   同逐星河先例）。本片 cue 18-37 唱词即此曲。未查到官方中文名 ⇒ 保留原语言
    #   （戒律②），ja/ko 留空。另曲 "Indigo Agitation"（Nhato）为 lobby/战斗动态
    #   器乐曲 ⇒ 按戒律（只收有人声演唱的歌）不入本表。
    ("Upending the Seas", "Upending the Seas", "", ""),
]


# ============================================================
# 终末地 1.4「向渊行」OST · 阿莱克琉斯（千夫长）战曲分段（2026-11-03 新增）
# 曲名**只有拉丁文官方名、无官方简体中文** ⇒ 按"单语保留原语言"处理，ja/ko 留空，
# 严禁臆造中文译名（同 _MUSIC_LIMBUS 的先例）。
# 依据（逐条可点验）：TapTap 官方动态 moment/831623591383533608 的「向渊行」OST 曲目表、
#   官方微博 5326333804282930（2026-07-30 上架，30 首）、musicbrainz release
#   5c10e8d8-941a-410e-a8d3-01c6d0eda9e9；署名 **铁痕电台-MSR & Crywolf & YMIR**。
# 官方分段顺序＝序章 / 一阶段 / 阶段转换 / 二阶段 / 尾声（下表同序）。
# ⇒ 推论（判据级）：音乐 reaction 片里 "HE HAS ANOTHER PHASE" / "it was like a
#   multi-part" 这类**分段感叹是可信的**，可直接按官方阶段数校；但曲名未在字幕中
#   出现时不强行插入，本表只作 kb-export 的跨语识别元数据（音乐实体不带 variants）。
# ⚠ 人声侧的拉丁词取自维吉尔《埃涅阿斯纪》VII "Flectere si nequeo superos,
#   Acheronta movebo"，并含英语嘶吼唱腔 ⇒ shrieking 归「嘶吼」而非「尖叫」，
#   该条已落 REACT_CONTEXT（misc.py）。
# ============================================================
_MUSIC_ENDO_BOSS = [
    ("ADELPHOCLAST", "ADELPHOCLAST", "", ""),
    ("ACHERON", "ACHERON", "", ""),
    ("ABYSSUS, ABYSSUM, INVOCAT", "ABYSSUS, ABYSSUM, INVOCAT", "", ""),
    ("REAPER", "REAPER", "", ""),
    ("AMARANTHUS CAUDATUS", "AMARANTHUS CAUDATUS", "", ""),
]


# ============================================================
# 边狱巴士（Limbus Company）OST（2026-10-26 新增）
# 本作无官方中文；以下为 Project Moon / Studio EIM 正式发行的英文曲名。
# 单语保留原语言；ja/ko 留空，严禁臆造中文译名。
# ============================================================
_MUSIC_LIMBUS = [
    ("Canto X Boss 3 Battle Theme", "Canto X Boss 3 Battle Theme", "", ""),
    ("Canto X Boss 2 Battle Theme", "Canto X Boss 2 Battle Theme", "", ""),
    ("Canto X Boss 1 Battle Theme", "Canto X Boss 1 Battle Theme", "", ""),
    ("Canto X Boss 5 Battle Theme", "Canto X Boss 5 Battle Theme", "", ""),
    ("Canto X Battle Theme C", "Canto X Battle Theme C", "", ""),
    ("Canto IX Boss 10 Battle Theme", "Canto IX Boss 10 Battle Theme", "", ""),
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

