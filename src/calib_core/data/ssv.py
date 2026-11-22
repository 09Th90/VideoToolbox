# -*- coding: utf-8 -*-
# @version 3.2.0
"""星之救援者（Star Savior）评测片源术语/语境表（--ssv，2026-11-15 新增）

片源：《The Over-complicated Gacha Review | Star Savior》（Pseychie，英语原声 +
谷歌翻译，1001 cue，每 cue 中文 + 英文参考行，CRLF 无 BOM，35m15s 游戏评测）。
校准方式：全人工逐句重写（996/1001 + 二校 8 条），本表沉淀错形群供同系列复跑。

官方依据（2026-11-15 检索）：
- 游戏名《星之救援者》（Studio Bside，starsavior.com/tw 繁中官网；Google Play
  简中页面作「星之救世主」非官方，弃用）。
- 世界观 Lavistar=拉维斯塔；育成玩法 Journey=旅程；育成单位 Rescuer=救援者。
- 系统（官方繁中公告/攻略站）：Star Link=星链、Flash Point=闪点、
  Cosmo Gate=宇宙之门、Operation=作战；Nova gauge=新星量表、Arcana=阿尔卡纳
  （gamekee 新手指南 + Star Savior DB 通行写法）；Pulse=星光石（抽卡货币，
  单抽 200 星光石、硬保底 200 抽）。
- limit break=共鸣：巴哈攻略通行（「共鸣8/共鸣3/0命」），未见官方公告原文，
  低置信留痕——机制描述（星链等级取决于四名共鸣角色）与片内完全吻合。
- 装备刷取关卡：gamekee《装备的获取之装备副本》官方叫「装备副本」（relic stage）。
- Chaos Zero Nightmare=卡厄思梦境（Smilegate 官方繁中定名）；片内自动字幕
  把它听成 "KL0 Nightmare"。
- CounterSide=未来战（官方繁中名）；Nikke Pilgrim=朝圣者（妮姬官方阵营）。
- Epic Seven 的 Burn=燒傷（官方繁中公告「以50%的機率造成燒傷」），简中=烧伤。
- Star Sailor（Com2uS 另一款游戏）查无官方中文名，保留英文（勿与星之救援者混淆）。

硬契约：
- 本表只收**可安全替换的错形/专名**（ssv 模式内部生效，与 bi 表隔离）。
- 通用词（尼克/脉搏/烧灼/天井）**不进裸键**，一律走 SSV_CONTEXT 英文参考行锚定。
- 「遗物」两义：旅程模式 roguelike relic=遗物（正确，不动）；装备副本 relic
  stage 只以「遗物关卡」整词入裸键改「装备副本」，防止误伤单独的「遗物」。
"""

SSV_TERMS = {
    # ── 游戏名（谷翻逐词错形） ──
    "明星救世主": "星之救援者",
    "星际救世主": "星之救援者",
    "星之救世主": "星之救援者",
    "星救主": "星之救援者",
    "Star Savior": "星之救援者",
    # ── 卡厄思梦境（自动字幕把 CZN 听成 KL0） ──
    "KL0 Nightmare": "卡厄思梦境",
    "Chaos Zero Nightmare": "卡厄思梦境",
    # ── 外部作品（谷翻错形/英文残留） ──
    "乌玛娘": "赛马娘",
    "海麻娘": "赛马娘",
    "Uma Musume": "赛马娘",
    "崩坏星铁轨": "崩坏：星穹铁道",
    "崩坏之星铁路": "崩坏：星穹铁道",
    "Honkai Star Rail": "崩坏：星穹铁道",
    "Honkai: Star Rail": "崩坏：星穹铁道",
    "倒转1999年": "重返未来：1999",
    "Reverse 1999": "重返未来：1999",
    "Reverse: 1999": "重返未来：1999",
    "CounterSide": "未来战",
    "Counter: Side": "未来战",
    "Counterside": "未来战",
    "Epic Seven": "第七史诗",
    "Epic 7": "第七史诗",
    "Nikke": "妮姬",
    "Arknights": "明日方舟",
    # ── 片内世界观/系统（英文残留键） ──
    "Lavastar": "拉维斯塔",
    "Lavistar": "拉维斯塔",
    "Roberta": "罗贝塔",
    # ── 系统词机翻错形（无歧义整词） ──
    "债券水平": "羁绊等级",
    "满怜结转": "保底全额继承",
    "新星规": "新星量表",
    "遗物关卡": "装备副本",
}

SSV_CONTEXT = [
    # (参考行英文正则, 中文行错形, 正确形)
    # 妮姬（「尼克」是通用人名词，禁裸键）
    (r"\bNikke\b", "尼克", "妮姬"),
    # 第七史诗 Burn=燒傷（官方繁中公告），谷翻「烧灼」
    (r"\bburn(?:s|ed|ing)?\b", "烧灼", "烧伤"),
    # 抽卡货币 Pulse=星光石
    (r"\bpulse\b", "脉搏", "星光石"),
    (r"\bpulse\b", "脉冲", "星光石"),
    # limit break=共鸣（巴哈通行；「极限突破」是妮姬语境词）
    (r"\blimit\s+breaks?\b", "极限突破", "共鸣"),
    # pity=保底（谷翻「天井」变体）
    (r"\bpit(?:y|ied)\b", "天井", "保底"),
    # Arcana/Arcanus=阿尔卡纳（谷翻缩写「阿卡纳」）
    (r"\bArca(?:na|nus|nas)\b", "阿卡纳", "阿尔卡纳"),
    # 闪点/宇宙之门/星链 谷翻变体
    (r"\bFlash\s+Point\b", "闪光点", "闪点"),
    (r"\bCosmo\s+Gate\b", "宇宙门", "宇宙之门"),
    (r"\bStar\s+Link\b", "星际链接", "星链"),
    # 妮姬朝圣者
    (r"\bpilgrims?\b", "巡礼者", "朝圣者"),
    # 罗贝塔（谷翻「罗伯塔」变体）
    (r"\bRoberta\b", "罗伯塔", "罗贝塔"),
    # KL0 单独残留（整词走裸键；孤残走语境）
    (r"\bKL0\b", "KL0", "卡厄思梦境"),
    # Operation 模式谷翻「运营模式/操作阶段」（ssv 片源内特指作战）
    (r"\boperations?\b", "运营模式", "作战模式"),
    (r"\boperations?\b", "操作阶段", "作战关卡"),
    (r"\boperation\s+stage\b", "运营阶段", "作战关卡"),
]

# 漏译体检（只收高置信专名；供 missing --mode ssv --window 1）
SSV_MISSING_CHECK = [
    (r"\bStar\s+Savior\b", ("星之救援者",),
     "Star Savior 官方中文=星之救援者（starsavior.com/tw）"),
    (r"\bNikke\b", ("妮姬",), "Nikke=妮姬"),
    (r"\bEpic\s+(?:Seven|7)\b", ("第七史诗",), "Epic Seven=第七史诗"),
    (r"\bUma\s+Musume\b", ("赛马娘",), "Uma Musume=赛马娘"),
    (r"\bHonkai\s+Star\s+Rail\b", ("星穹铁道",),
     "Honkai Star Rail=崩坏：星穹铁道"),
    (r"\bCounter:?\s?Side\b", ("未来战",), "CounterSide 官方繁中=未来战"),
    (r"\bChaos\s+Zero\s+Nightmare\b|\bKL0\b", ("卡厄思梦境",),
     "Chaos Zero Nightmare 官方繁中=卡厄思梦境"),
    (r"\bLavastar\b|\bLavistar\b", ("拉维斯塔",), "Lavistar=拉维斯塔"),
    (r"\bCosmo\s+Gate\b", ("宇宙之门",), "Cosmo Gate=宇宙之门（官方公告）"),
    (r"\bFlash\s+Point\b", ("闪点",), "Flash Point=闪点（官方公告）"),
    (r"\bStar\s+Link\b", ("星链",), "Star Link=星链（官方公告）"),
    (r"\bArca(?:na|nus|nas)\b", ("阿尔卡纳",), "Arcana=阿尔卡纳（gamekee/StarSaviorDB）"),
    (r"\bpulse\b", ("星光石",), "Pulse=星光石（抽卡货币）"),
    (r"\bpilgrims?\b", ("朝圣者",), "Nikke Pilgrim=朝圣者"),
    (r"\bRoberta\b", ("罗贝塔",), "Roberta=罗贝塔"),
]
