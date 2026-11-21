# -*- coding: utf-8 -*-
# @version 3.1.6
"""《少女前线2：追放》（Girls' Frontline 2: Exilium）片源术语/语境表（--mode gfl2，2026-11-21 新增）

片源：《I Finally Played Girls' Frontline 2 Exilium… and It's Wild》（SmugSlav，
英语原声 + 微软翻译，290 cue，中文在上/英文参考行在下，CRLF 无 BOM，
全球服二周年 Boomiversary：新角色 Koleda、精英AR Chernobog、Iliad 版本实机）。

官方依据（2026-11-21 检索）：
- 游戏名《少女前线2：追放》（官网 gf2exilium.sunborn.com）。
- 二周年特别版本「伊利昂之围」分上/中/下篇（官方公告；全球服 Part 1/1.5/2 对应）。
- 新精英人形「克莱妲」（Koleda，AK-12 对应人形）、精英AR「切尔诺伯格」
  （Chernobog，Google Play 官方页/百度百科）。
- 召唤跑车「隐罪者」（Sinveiler），技能「去兜风咯！/全速冲刺/战术路书/动能释放」
  （官方 wiki gf2-bbs.exiliumgf.com/wiki/doll?id=1079）。
- 周年奖励 115 抽 + 12000「坍塌晶条」（官方二周年福利公告；繁中作坍塌晶條）。
- 衣装：海伦「惑心夜魅」（Nocturnal Desires）/妮基塔「无垢契约」（Immaculate
  Devotion）/夏克里「代理店长」（B站官方更新公告）；罗蕾莱「暮色絮语」（Twilight
  Whisper，IOP Wiki/Reddit 官方帖）。
- 艾莫号房间：Refitting Room=整备室、Crew Deck=活动层（IOP Wiki Crew Deck 页，
  loading screen 官方描述 ops room/engine room/refitting room/hangar）。
- 可露凯（Klukai，HK416 对应人形，404 小队队长，萌娘百科）；妮基塔（Nikketa，百度百科）。

硬契约：
- 本表只在 `--mode gfl2` 内生效，与 bi/其它片源表隔离；不污染通用双语表。
- 通用词（全速前进/改装间）**绝不进裸键**，一律走 GFL2_CONTEXT 的英文参考行锚定。
- 「切尔诺贝利」在现实语境是真实地名，故仅限 gfl2 模式内判成武器「切尔诺伯格」。
- ASR 变体（Colette/Michael Leda/Elliot/Ghost Frontline/Kluke）已收敛进裸键/体检表。
"""

GFL2_TERMS = {
    # ── 作品名（ASR/机翻错形；长键优先） ──
    "女孩前线II": "少女前线2",        # Girls Frontline II 机翻（cue2/7）
    "女孩前线2": "少女前线2",         # Girls Frontline 2 机翻（同根；官方中文=少女前线2）
    "女孩前线": "少女前线",           # Girls' Frontline 直译兜底（官方中文=少女前线）
    "幽灵前线": "少女前线",           # ASR "Ghost Frontline"（cue263/278）
    # ── 人物 ──
    "科莱特": "克莱妲",               # Koleda 机翻（cue14/29-32/41/157/174）
    "科勒达": "克莱妲",               # Koleda 机翻变体（cue63/67）
    "科莱达": "克莱妲",               # Koleda 机翻变体（cue83/86）
    "迈克尔·莱达": "克莱妲",          # ASR "Michael Leda"（cue120）
    "克鲁克": "可露凯",               # Klukai ASR（cue70/74；HK416 对应人形）
    # ── 武器 / 版本 / 道具 ──
    "切尔诺贝利": "切尔诺伯格",       # Chernobog ASR（cue50；仅 gfl2 模式）
    "伊利亚特": "伊利昂之围",         # Iliad 机翻（cue25；二周年版本官方名）
    "可折叠的拼块": "坍塌晶条",       # Collapse Pieces 机翻（cue10；周年奖励道具）
    # ── 衣装 ──
    "夜间欲望": "惑心夜魅",           # Nocturnal Desires 机翻（cue208；海伦衣装）
    "无玷虔诚": "无垢契约",           # Immaculate Devotion 机翻（cue216；妮基塔衣装）
    "暮光耳语": "暮色絮语",           # Twilight Whispers 机翻（cue167；罗蕾莱衣装）
    # ── 艾莫号房间 / 系统 ──
    "装修室": "整备室",               # refitting room 机翻（cue220；IOP Wiki）
    "船员甲板": "活动层",             # Crew Deck 机翻（cue220/225；IOP Wiki）
}

GFL2_CONTEXT = [
    # (英文参考行正则, 中文行错形, 正确形)
    # 全速冲刺：克莱妲 kit 官方技能名；「全速前进」是正常中文短语，禁裸键
    (r"\bfull\s+speed\b", "全速前进", "全速冲刺"),
    # 整备室：refitting room 官方名（IOP Wiki）；「改装间」是通用词，禁裸键
    (r"\brefitting\s+room\b|\brefit\w*\b|\bretrofit\w*\b", "改装间", "整备室"),
]

# 漏译体检（供 missing --mode gfl2 使用；只收高置信专名）
GFL2_MISSING_CHECK = [
    (r"\bKoleda\b|\bColette\b|\bMichael\s+Leda\b", ("克莱妲",),
     "Koleda/Colette/Michael Leda=克莱妲（二周年新角色，官方中文名）"),
    (r"\bChernobog\b|\bChernobyl\b", ("切尔诺伯格",),
     "Chernobog=切尔诺伯格（克莱妲精英AR）"),
    (r"\bIliad\b|\bElliot\b", ("伊利昂之围",),
     "Iliad/Elliot ASR=伊利昂之围（二周年特别版本，官方分上/中/下篇）"),
    (r"\bKluke\b|\bKlukai\b", ("可露凯",), "Klukai=可露凯（HK416 对应人形）"),
    (r"\bNiketta\b|\bNikketa\b", ("妮基塔",), "Niketta/Nikketa=妮基塔"),
    (r"\bNocturnal\s+Desires\b", ("惑心夜魅",),
     "Nocturnal Desires=海伦衣装「惑心夜魅」"),
    (r"\bImmaculate\s+Devotion\b", ("无垢契约",),
     "Immaculate Devotion=妮基塔衣装「无垢契约」"),
    (r"\bTwilight\s+Whispers?\b", ("暮色絮语",),
     "Twilight Whisper=罗蕾莱衣装「暮色絮语」"),
    (r"\bCrew\s+Deck\b", ("活动层",), "Crew Deck=活动层（艾莫号宿舍系统）"),
    (r"\brefitting\s+room\b", ("整备室",), "refitting room=整备室（艾莫号房间）"),
    (r"\bCollapse\s+Pieces\b", ("坍塌晶条",),
     "Collapse Pieces=坍塌晶条（二周年奖励道具）"),
    (r"\bGirls'?s?\s+Frontline\b", ("少女前线",),
     "Girls' Frontline=少女前线（不是女孩前线/幽灵前线）"),
]
