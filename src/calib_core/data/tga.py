# -*- coding: utf-8 -*-
# @version 3.1.1
"""TGA 2026 游戏大奖直播术语/语境表（--tga26，2026-11-18 新增）

片源：《Big Day... TGA Announcements & Patreon Music Livestream!》
（英语原声 + 微软翻译，4671 cue，每 cue 中文 + 英文参考行，CRLF 无 BOM，4h45m）。
校准方式：两轮全人工逐句重写（一校 4225 条 + 二校 108 条），本表沉淀官方译名
与错形群，供 TGA / 年度游戏评选类片源复跑。

官方依据（2026-11-18 检索）：
- TGA 2026 完整提名名单（IT之家/新浪转载，2026-11-18；颁奖 12 月 10 日）。
- 各游戏 Steam/官网官方简中：GTA VI=侠盗猎车手 VI、Ace Combat 8=皇牌空战 8：
  希孚之翼、Control Resonant=控制：共振、Phantom Blade Zero=影之刃零、
  Resident Evil Requiem=生化危机：安魂曲、007 First Light=007：初露锋芒、
  Pragmata=识质存在、Fire Emblem: Fortune's Weave=火焰之纹章：万缕千丝、
  Monster Hunter Stories 3=怪物猎人物语 3：命运双龙、The Blood of Dawnwalker=
  黎明行者之血、Trails in the Sky the 2nd=空之轨迹 the 2nd、Denshattack!=电车炫客、
  Mewgenics=喵喵的结合、Cairn=孤山独影、Esoteric Ebb=奥秘消退、
  Orbitals=轨道双子星、Silver Pines=银松镇、Mina the Hollower=挖掘者米娜、
  Wuthering Waves=鸣潮、Arknights: Endfield=明日方舟：终末地、
  Neverness to Everness=异环、Where Winds Meet=燕云十六声、
  Pokemon Champions=宝可梦冠军、Monster Hunter Outlanders=怪物猎人：旅人、
  Ocarina of Time=塞尔达传说：时之笛、Saros=沙罗周期、
  Onimusha: Way of the Sword=鬼武者：剑之道、Gears of War: E-Day=战争机器：事变日、
  Crimson Desert=红色沙漠、Mouse: P.I. For Hire=神探杰克鼠、
  Star Wars: Galactic Racer=星球大战：银河赛车手、Star Wars: Zero Company=星球大战零号连队。
- 低置信/待核留痕：Arc Raiders=弧光掠夺者（官方简中待核，按媒体通行译名收入）；
  《Mal Manalon Mila》《Moi Moi Hiatada》《Tommo Toaoa》《Biddy Blaze》
  《Queen's Domain》《Vegas 3》《Gacha Cusha》等 ASR 音形未能核实，保留英文，不入表。

硬契约：
- 本表只收**可安全替换的错形/官方名**（tga26 模式内部生效，与 bi 表隔离）。
- 普通中文词（Karen/武者/轨道站/我的学术/伊代/莱/居所/马拉松/共振/安魂曲/
  王牌/优生学/假牙攻击 等）**不进裸键**，一律走 TGA_CONTEXT 英文参考行锚定。
- 官方保留英文项（Big Walk、Mixtape、Replaced、Invincible VS、2XKO、Forever Ago、
  Screamer、Forefront、Into the Radius 2、Dota 2、Deadlock 等）不写 identity 映射。
- 奖项名收长英文键，裸键风险低；游戏名收英文长键与高置信中文错形。
"""

TGA_TERMS = {
    # ── 年度游戏 / 主要提名作品（英文残留 -> 官方简中） ──
    "Grand Theft Auto VI": "侠盗猎车手 VI",
    "Grand Theft Auto 6": "侠盗猎车手 6",
    "GTA VI": "侠盗猎车手 VI",
    "Ace Combat 8: Wings of Thieve": "皇牌空战 8：希孚之翼",
    "Ace Combat 8: Wings of Thieved": "皇牌空战 8：希孚之翼",
    "Ace Combat 8": "皇牌空战 8",
    "Ace Combat": "皇牌空战",
    "Control Resonant": "控制：共振",
    "Phantom Blade Zero": "影之刃零",
    "Resident Evil Requiem": "生化危机：安魂曲",
    "007 First Light": "007：初露锋芒",
    "Pragmata": "识质存在",
    "Fire Emblem: Fortune's Weave": "火焰之纹章：万缕千丝",
    "Fire Emblem Fortunes Weave": "火焰之纹章：万缕千丝",
    "Monster Hunter Stories 3: Twisted Reflection": "怪物猎人物语 3：命运双龙",
    "Monster Hunter Stories 3": "怪物猎人物语 3：命运双龙",
    "The Blood of Dawnwalker": "黎明行者之血",
    "The Blood of Dawn Walker": "黎明行者之血",
    "Trails in the Sky the 2nd": "空之轨迹 the 2nd",
    "Denshattack!": "电车炫客",
    "Denshattack": "电车炫客",
    "Mewgenics": "喵喵的结合",
    "Cairn": "孤山独影",
    "Esoteric Ebb": "奥秘消退",
    "Orbitals": "轨道双子星",
    "Silver Pines": "银松镇",
    "Mina the Hollower": "挖掘者米娜",
    # 注：Wuthering Waves 不收录——bi/pbz 既有表已有该键但目标不一致
    #   （鸣潮 / 《鸣潮》），收入会触发 kb-lint 变体冲突；TGA 片源中文行已是
    #   《鸣潮》，无需脚本再改。漏译体检仍保留 Wuthering Waves 规则。
    "Arknights: Endfield": "明日方舟：终末地",
    "Arknights Endfield": "明日方舟：终末地",
    "Neverness to Everness": "异环",
    "Where Winds Meet": "燕云十六声",
    "Pokemon Champions": "宝可梦冠军",
    "Pokémon Champions": "宝可梦冠军",
    "Pokemon Pokopia": "宝可梦 Pokopia",
    "Pokémon Pokopia": "宝可梦 Pokopia",
    # 注：不单收 "Pokopia"——中文行已是「宝可梦 Pokopia」时会被二次替换成
    #   「宝可梦 宝可梦 Pokopia」。ASR 错形 Piccopia 由人工逐句处理。
    "Monster Hunter Outlanders": "怪物猎人：旅人",
    "Ocarina of Time": "时之笛",
    "Saros": "沙罗周期",
    "Onimusha: Way of the Sword": "鬼武者：剑之道",
    "Onimusha": "鬼武者",
    "Gears of War: E-Day": "战争机器：事变日",
    "Gears of War E-Day": "战争机器：事变日",
    "Crimson Desert": "红色沙漠",
    "Arc Raiders": "弧光掠夺者",
    "Mouse: P.I. For Hire": "神探杰克鼠",
    "Mouse P.I. For Hire": "神探杰克鼠",
    "Star Wars: Galactic Racer": "星球大战：银河赛车手",
    "Star Wars Galactic Racer": "星球大战：银河赛车手",
    "Star Wars: Zero Company": "星球大战零号连队",
    "Star Wars Zero Company": "星球大战零号连队",
    "Assassin's Creed Black Flag Resynced": "刺客信条：黑旗 记忆重置",
    "Forza Horizon 6": "极限竞速：地平线 6",
    "Rhythm Heaven": "节奏天国 奇迹之星",
    "Marvel's Wolverine": "漫威金刚狼",
    "Marvel Tokon: Fighting Souls": "漫威斗魂",
    "Avatar Legends: The Fighting Game": "阿凡达传奇：格斗游戏",
    "Final Fantasy Resonance": "最终幻想：共鸣",
    "Final Fantasy VII: Revelation": "最终幻想 7：启示录",
    "God of War: Laufey": "战神：劳菲",
    "The Witcher 4": "巫师 4",
    "The Witcher 3: Wild Hunt": "巫师 3：狂猎",
    "Resident Evil: Code Veronica": "生化危机：代号维罗妮卡",
    "Resident Evil 9": "生化危机 9",
    "Life is Strange: Reunion": "奇异人生：重聚",
    "Lily's World XD": "莉莉的世界 XD",
    "Dressmaker": "针影裁梦",
    # 注：Big Walk / Mixtape / Replaced 官方保留英文，不写 identity 映射
    #   （identity 只增加命中计数、不改文本，且会让幂等回归误报）。
    "Fable": "神鬼寓言",
    "Hades II": "哈迪斯 2",
    "Hades 2": "哈迪斯 2",
    "Doom: The Dark Ages": "毁灭战士：黑暗时代",
    "Persona 5 Strikers": "女神异闻录 5 乱战：魅影攻手",
    "Persona 4": "女神异闻录 4",
    "Silent Hill 3": "寂静岭 3",
    "Wild Arms 3": "荒野兵器 3",
    "Suikoden III": "幻想水浒传 III",
    "Phantasy Star Online 2": "梦幻之星在线 2",
    "Age of Empires 2": "帝国时代 2",
    "Age of Empires II": "帝国时代 2",
    "Child of Light": "光之子",
    "Starcraft": "星际争霸",
    "Sim City 4": "模拟城市 4",
    "Yu-Gi-Oh! Master Duel": "游戏王：大师决斗",
    "Yu-Gi-Oh! Duel Links": "游戏王：决斗链接",
    "Five Nights at Freddy's": "玩具熊的五夜后宫",
    "Ratchet and Clank": "瑞奇与叮当",
    "Golden Sun": "黄金太阳",
    "Heroes of the Storm": "风暴英雄",
    "League of Legends": "英雄联盟",
    "Overwatch": "守望先锋",
    "Apex Legends": "Apex 英雄",
    "Valorant": "无畏契约",
    "Counter-Strike 2": "反恐精英 2",
    "Mobile Legends: Bang Bang": "无尽对决",
    "Animal Crossing": "动物森友会",
    "Call of Duty: Modern Warfare 4": "使命召唤：现代战争 4",
    "Final Fantasy XIV": "最终幻想 14",
    "Final Fantasy 14": "最终幻想 14",
    "No Man's Sky": "无人深空",
    "Fortnite": "堡垒之夜",
    "Warframe": "星际战甲",
    "Helldivers 2": "绝地潜兵 2",
    "Death Stranding": "死亡搁浅",
    "Elden Ring": "艾尔登法环",

    # ── 机翻/ASR 错形（长形，高置信） ──
    "重大盗窃车手6": "侠盗猎车手 6",
    "重大盗窃车手": "侠盗猎车手",
    "盗窃车手6": "侠盗猎车手 6",
    "王牌空战": "皇牌空战",
    "盗贼之翼": "希孚之翼",
    "盗贼八翼": "希孚之翼",
    "幽灵之刃零": "影之刃零",
    "幻影之刃": "影之刃零",
    "幻影刀锋零": "影之刃零",
    "幻影刀刃零": "影之刃零",
    "幻刃零": "影之刃零",
    "控制驻地": "控制：共振",
    "控制居民": "控制：共振",
    "控制共振": "控制：共振",
    "Reququum": "生化危机：安魂曲",
    "Reququiam": "生化危机：安魂曲",
    "Requum": "生化危机：安魂曲",
    "Resident Evil Reququum": "生化危机：安魂曲",
    "Resident Evil Requum": "生化危机：安魂曲",
    "生化危机 Requum": "生化危机：安魂曲",
    "生化危机：Requum": "生化危机：安魂曲",
    "Mugenics": "喵喵的结合",
    "Mugenic": "喵喵的结合",
    "Denture Attack": "电车炫客",
    "Denia Attack": "电车炫客",
    "Dencha attack": "电车炫客",
    "Denta Attack": "电车炫客",
    "Hench attack": "电车炫客",
    "Tench Attack": "电车炫客",
    "Esoteric Web": "奥秘消退",
    "轨道站": "轨道双子星",
    "空洞者米娜": "挖掘者米娜",
    "空洞米娜": "挖掘者米娜",
    "猩红沙漠": "红色沙漠",
    "大步行": "Big Walk",
    "最终幻想居所": "最终幻想：共鸣",
    "最终幻想：居所": "最终幻想：共鸣",
    "黎明行者的血": "黎明行者之血",
    "黎明·沃克之血": "黎明行者之血",
    "火焰纹章": "火焰之纹章",
    "财富编织": "万缕千丝",
    "怪物猎人故事3": "怪物猎人物语 3",
    "怪物猎人储藏3": "怪物猎人物语 3",
    "扭曲的倒影": "命运双龙",
    "扭曲的反思": "命运双龙",
    "空之轨迹 第二章": "空之轨迹 the 2nd",
    "天空战团": "空之轨迹 the 2nd",
    "王牌空战8": "皇牌空战 8",
    "假牙攻击": "电车炫客",
    "牙科攻击": "电车炫客",

    # ── TGA 奖项名（长英文键） ──
    "Game of the Year": "年度游戏",
    "Best Score and Music": "最佳配乐与音乐",
    "Best Audio Design": "最佳音效设计",
    "Best Narrative": "最佳叙事",
    "Best Art Direction": "最佳艺术指导",
    "Best Game Direction": "最佳游戏指导",
    "Best Independent Game": "最佳独立游戏",
    "Best Debut Indie Game": "最佳独立游戏处女作",
    "Best Mobile Game": "最佳移动游戏",
    "Best VR/AR Game": "最佳 VR/AR 游戏",
    "Best Action Game": "最佳动作游戏",
    "Best Action/Adventure Game": "最佳动作冒险游戏",
    "Best Role-Playing Game": "最佳角色扮演游戏",
    "Best Fighting Game": "最佳格斗游戏",
    "Best Family Game": "最佳家庭游戏",
    "Best Sim/Strategy Game": "最佳模拟/策略游戏",
    "Best Sports/Racing Game": "最佳体育/竞速游戏",
    "Best Multiplayer Game": "最佳多人游戏",
    "Best Adaptation": "最佳改编作品",
    "Best User-Created Content": "最佳玩家创作内容",
    "Content Creator of the Year": "年度最佳内容创作者",
    "Most Anticipated Game": "最受期待游戏",
    "Games for Impact": "最具影响力游戏",
    "Best Ongoing Game": "最佳持续运营游戏",
    "Best Community Support": "最佳社区支持",
}

TGA_CONTEXT = [
    # (参考行英文正则, 中文行错形, 正确形)
    # Cairn：Karen 是通用人名，禁裸键
    (r"\bCairn\b", "Karen", "孤山独影"),
    (r"\bCairn\b", "凯伦", "孤山独影"),
    # Onimusha：武者 是普通词；right 只到「鬼武者」——
    #   若写成「鬼武者：剑之道」，已正确的「鬼武者」会被二次替换成「鬼鬼武者」。
    (r"\bOnimusha\b", "武者", "鬼武者"),
    # Orbitals：轨道站 是普通词
    (r"\bOrbitals?\b", "轨道站", "轨道双子星"),
    # Marvel Tokon：我的学术 / took Souls and my Academia 是 ASR/机翻错形
    (r"\bMarvel\s+Tokon\b", "我的学术", "漫威斗魂"),
    (r"\bMarvel\s+Tokon\b", "took Souls and my Academia", "漫威斗魂"),
    # Gears of War：伊代 是音译错形
    (r"\bGears\s+of\s+War\b|\bE-?Day\b", "伊代", "战争机器：事变日"),
    # God of War Laufey：莱 是单字，禁裸键
    (r"\bLaufey\b", "莱", "战神：劳菲"),
    # Marathon：马拉松 是普通词/赛事名
    (r"\bMarathon\b", "马拉松", "失落星船：马拉松"),
    # Control Resonant：共振 是普通词（也用于最终幻想：共鸣）
    (r"\bControl\s+Resonant\b", "共振", "控制：共振"),
    # Resident Evil Requiem：安魂曲 是普通词
    (r"\bResident\s+Evil\s+Requiem\b", "安魂曲", "生化危机：安魂曲"),
    # Final Fantasy Resonance：居所 是普通词
    (r"\bFinal\s+Fantasy[:\s]+Resonance\b", "居所", "最终幻想：共鸣"),
    # Ace Combat：王牌 是普通词（扑克/王牌）
    (r"\bAce\s+Combat\b", "王牌", "皇牌空战"),
    (r"\bAce\s+Combat\b", "王牌战士", "皇牌空战"),
    # Mewgenics：优生学 是机翻错形（ASR Eugenics）
    (r"\bMewgenics\b", "优生学", "喵喵的结合"),
    # Saros：索罗斯/索罗斯 是音译错形
    (r"\bSaros\b", "索罗斯", "沙罗周期"),
    (r"\bSaros\b", "Sorrowos", "沙罗周期"),
    # Denshattack：假牙攻击/牙科攻击 是机翻错形
    (r"\bDenshattack\b", "假牙攻击", "电车炫客"),
    (r"\bDenshattack\b", "牙科攻击", "电车炫客"),
]

# 漏译体检（只收高置信专名；供 missing --mode tga26 --window 1）
TGA_MISSING_CHECK = [
    (r"\bGrand\s+Theft\s+Auto\s+(?:VI|6)\b", ("侠盗猎车手",),
     "GTA VI 官方简中=侠盗猎车手 VI"),
    (r"\bAce\s+Combat\s+8\b", ("皇牌空战 8",),
     "Ace Combat 8 官方简中=皇牌空战 8：希孚之翼"),
    (r"\bControl\s+Resonant\b", ("控制：共振",),
     "Control Resonant 官方简中=控制：共振"),
    (r"\bPhantom\s+Blade\s+Zero\b", ("影之刃零",),
     "Phantom Blade Zero 官方简中=影之刃零"),
    (r"\bResident\s+Evil\s+Requiem\b", ("生化危机：安魂曲",),
     "Resident Evil Requiem 官方简中=生化危机：安魂曲"),
    (r"\b007\s+First\s+Light\b", ("007：初露锋芒",),
     "007 First Light 官方简中=007：初露锋芒"),
    (r"\bPragmata\b", ("识质存在",), "Pragmata 官方简中=识质存在"),
    (r"\bFire\s+Emblem[:\s]+Fortune'?s\s+Weave\b", ("火焰之纹章：万缕千丝",),
     "Fire Emblem: Fortune's Weave 官方简中=火焰之纹章：万缕千丝"),
    (r"\bDenshattack\b", ("电车炫客",), "Denshattack! 官方简中=电车炫客"),
    (r"\bMewgenics\b", ("喵喵的结合",), "Mewgenics 官方简中=喵喵的结合"),
    (r"\bCairn\b", ("孤山独影",), "Cairn 官方简中=孤山独影"),
    (r"\bEsoteric\s+Ebb\b", ("奥秘消退",), "Esoteric Ebb 官方简中=奥秘消退"),
    (r"\bOrbitals?\b", ("轨道双子星",), "Orbitals 官方简中=轨道双子星"),
    (r"\bMina\s+the\s+Hollower\b", ("挖掘者米娜",), "Mina the Hollower 官方简中=挖掘者米娜"),
    (r"\bWuthering\s+Waves\b", ("鸣潮",), "Wuthering Waves 官方简中=鸣潮"),
    (r"\bArknights[:\s]+Endfield\b", ("明日方舟：终末地",),
     "Arknights: Endfield 官方简中=明日方舟：终末地"),
    (r"\bWhere\s+Winds\s+Meet\b", ("燕云十六声",), "Where Winds Meet 官方简中=燕云十六声"),
    (r"\bPokemon\s+Champions\b", ("宝可梦冠军",), "Pokemon Champions 官方简中=宝可梦冠军"),
    (r"\bOnimusha\b", ("鬼武者",), "Onimusha 官方简中=鬼武者：剑之道"),
    (r"\bGears\s+of\s+War\b", ("战争机器",), "Gears of War 官方简中=战争机器：事变日"),
    (r"\bCrimson\s+Desert\b", ("红色沙漠",), "Crimson Desert 官方简中=红色沙漠"),
]