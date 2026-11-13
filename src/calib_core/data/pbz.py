# -*- coding: utf-8 -*-
# @version 2.9.0
"""影之刃零（Phantom Blade Zero）片源术语/语境表（--pbz，2026-10-30 新增）

片源：《[Hellwalker] Phantom Blade Zero!!! pt2》（MarcoMeatball，英语原声 + 谷歌翻译，
3761 cue，每 cue 中文 + 英文参考行，CRLF 无 BOM，4h45m 综合直播）。

官方依据（2026-10-30 检索）：
- 游戏名《影之刃零》（灵游坊 / S-GAME，pbz.s-game.com）。
- 主角「魂」（Soul）；「组织」/「天命」为设定势力；「杀气」（shachi）为核心资源；
  「架势」（posture/stagger）为计量条；「地狱行者」（Hellwalker）为困难模式。
- 「左殇」（Zol Shang）、「魔渊」（Demon Abyss，甄子丹饰）、「血肉雕刻师」、
  「血肉莉莉」（Flesh Lily）、「彼岸花」（spider lily）、「面具行者」（mask walkers）。
- 醉剑为官方武器名（B 站官方演示亦作「醉剑」）。

硬契约：
- 本表只收**可安全全局替换的长键/专名**（pbz 模式内部生效，与 bi 表隔离）。
- 通用词（姿势/硬直/授权/教团/香槟/声骸/北风/青狼/武藏/相遇之地）**绝不进裸键**，
  一律走 PBZ_CONTEXT 的英文参考行锚定。
- ⚠ 「Wooa」在本片是 **wuxia（武侠）** 的 ASR，不是《鸣潮》；《鸣潮》只由
  Withering/Wing Waves 触发（2026-10-30 二校实证 #56/#283/#1316/#1474/#2739）。
"""

PBZ_TERMS = {
    # 游戏名（谷翻逐词直译）
    "幽灵传说": "《影之刃零》",
    "刀锋零号": "《影之刃零》",
    "幻影之刃": "《影之刃零》",
    # 设定/角色（长键、非通用词）
    "佐尔尚": "左殇",
    "肉体雕刻师": "血肉雕刻师",
    "肉体莉莉": "血肉莉莉",
    "肉身莉莉": "血肉莉莉",
    "恶魔深渊": "魔渊",
    "蜘蛛百合": "彼岸花",
    "沙奇": "杀气",
    # 外部作品（谷翻常见错形）
    "牧师兽": "圣职者野兽",
    "猩红沙漠": "《红色沙漠》",
    "王牌空战": "《皇牌空战》",
    "远征33": "《光与影：33号远征队》",
    "方舟骑士": "《明日方舟》",
    "弧线骑士": "《明日方舟》",
    "弧骑士": "《明日方舟》",
    "枯萎波浪": "《鸣潮》",
    "凋零波浪": "《鸣潮》",
    "翼浪": "《鸣潮》",
    "肉类在哪里": "《燕云十六声》",
    # 原文已带书名号时整段替换，避免出现《《…》》
    "《幽灵传说》": "《影之刃零》",
    "《刀锋零号》": "《影之刃零》",
    "《幻影之刃》": "《影之刃零》",
    "《枯萎波浪》": "《鸣潮》",
    "《凋零波浪》": "《鸣潮》",
    "《翼浪》": "《鸣潮》",
    "《方舟骑士》": "《明日方舟》",
    "《弧线骑士》": "《明日方舟》",
    "《弧骑士》": "《明日方舟》",
    "《猩红沙漠》": "《红色沙漠》",
    "《王牌空战》": "《皇牌空战》",
    "《王牌空战8》": "《皇牌空战8》",
    "《青狼》": "《只狼》",
    "《清郎》": "《只狼》",
    "《远征33》": "《光与影：33号远征队》",
    "《肉类在哪里》": "《燕云十六声》",
    # ── 2026-11-07 EP.1（Shylily Gaming，英语原声 + 微软翻译）实证 ──
    # 专名级错形（通用词一律走 PBZ_CONTEXT，不入裸键）
    "库亚寺": "苦叶寺",
    "北熙大师": "碧海大师",
    "北希大师": "碧海大师",
    "北熙": "碧海",
    "北希": "碧海",
    "蓬仁": "庞镇",
    "蓬占": "庞镇",
    "蓬灿": "庞镇",
    "潘根": "庞镇",
    "蓬镇": "庞镇",
    "查奇": "杀气",
    "呼啸波涛": "《鸣潮》",
    "血腥成就": "血色成就",
    "血质成就": "血色成就",
    "伊诺尼斯": "虚空",
    "伊纳尼斯": "虚空",
    "安妮丝": "虚空",
    "斧头大师": "斧老大",
    "恐怖之斧": "巨凶斧",
    "锯齿钢刃": "残钢刃",
    "福尔奇": "炼邪",
    "面具行者": "怪面",
    "幻影边缘": "幻刃",
    "桑奎因": "血色",
    "绝地组织": "组织",
    "绝地武士团": "组织",
    "血肉百合": "血肉莉莉",
}

PBZ_CONTEXT = [
    # (参考行正则, 中文行错形, 正确形)
    # 游戏名（跨 cue 拆分：Phantom / Blade Zero）
    (r"\bPhantom\s+Blade\b", "幽灵传说", "《影之刃零》"),
    (r"\bPhantom\s+Blade\b", "幻影之刃", "《影之刃零》"),
    # 主角：谷翻把 Soul 译成「索尔」
    (r"\bSoul\b", "索尔", "魂"),
    # 设定势力
    (r"\bthe\s+order\b", "教团", "组织"),
    (r"\bmandate\b", "授权", "天命"),
    # 核心资源 / 计量条
    (r"\bsha?chi\b", "沙池", "杀气"),
    (r"\bposture\b", "姿势", "架势"),
    (r"\bstagger\b", "硬直", "架势"),
    # 角色 / 敌人
    (r"\bDonn", "唐尼", "甄子丹"),
    (r"\bDemon\s+Abyss\b", "恶魔深渊", "魔渊"),
    (r"\bspider\s+lil", "蜘蛛百合", "彼岸花"),
    (r"\bwarden\b", "典狱长", "影守卫"),
    # 道具 / 剧情词
    (r"\bsachet?\b", "香槟", "香囊"),
    (r"\bechoes?\s+of\s+the\s+past\b", "声骸", "回声"),
    (r"\bprimal\s+stone\b", "原始之石", "原石"),
    # 外部作品（ASR/谷翻错形；只在本片锚定）
    (r"\b(?:Seiro|Surro|Siro)\b", "青狼", "《只狼》"),
    (r"\b(?:Seiro|Surro|Siro)\b", "清郎", "《只狼》"),
    (r"\bMusha\b", "武藏", "《鬼武者》"),
    (r"\bWhere(?:ins?)?\b.*\bMeet\b", "相遇之地", "《燕云十六声》"),
    (r"\bWhere(?:ins?)?\b.*\bMeet\b", "风交汇之地", "《燕云十六声》"),
    # ⚠ 本片 Wooa = wuxia（武侠），不是《鸣潮》
    (r"\bWooa\b", "鸣潮", "武侠"),
    (r"\bWooa\b", "《鸣潮》", "武侠"),
    (r"\bWithering\s+Waves\b|\bWing\s+Waves\b", "枯萎波浪", "《鸣潮》"),
    (r"\bWithering\s+Waves\b|\bWing\s+Waves\b", "凋零波浪", "《鸣潮》"),
    (r"\bArc\s+Knights?\b", "方舟骑士", "《明日方舟》"),
    (r"\bArc\s+Knights?\b", "弧线骑士", "《明日方舟》"),
    (r"\bZZZ\b|\bZCZ\b", "ZZ", "《绝区零》"),
    (r"\bZZZ\b|\bZCZ\b", "ZCZ", "《绝区零》"),
    (r"\bCrimson\s+Desert\b", "猩红沙漠", "《红色沙漠》"),
    (r"\bAce\s+Combat\b", "王牌空战", "《皇牌空战》"),
    (r"\belder\s+ring\b", "长老戒指", "《艾尔登法环》"),
    # ── 2026-11-07 EP.1 实证（通用词/短键一律用英文参考行锚定） ──
    (r"\bAnise\b|\bInonis\b|\bInanis\b", "安妮丝夫人", "虚空大人"),
    (r"\bAnise\b|\bInonis\b|\bInanis\b", "安妮丝", "虚空"),
    (r"\bAnise\b|\bInonis\b|\bInanis\b", "伊诺尼斯", "虚空"),
    (r"\bAnise\b|\bInonis\b|\bInanis\b", "伊纳尼斯", "虚空"),
    (r"\bPhantom\s+Edge\b", "幻影边缘", "幻刃"),
    (r"\bBeihi\b|\bBeihai\b", "北熙", "碧海"),
    (r"\bBeihi\b|\bBeihai\b", "北希", "碧海"),
    (r"\bKuya\b", "库亚寺", "苦叶寺"),
    (r"\bflesh\s+lily\b", "肉百合", "血肉莉莉"),
    (r"\bPangen\b|\bPongjen\b|\bPongjan\b|\bPongchan\b|\bPong\s+Jen\b", "蓬仁", "庞镇"),
    (r"\bPangen\b|\bPongjen\b|\bPongjan\b|\bPongchan\b|\bPong\s+Jen\b", "蓬占", "庞镇"),
    (r"\bPangen\b|\bPongjen\b|\bPongjan\b|\bPongchan\b|\bPong\s+Jen\b", "蓬灿", "庞镇"),
    (r"\bPangen\b|\bPongjen\b|\bPongjan\b|\bPongchan\b|\bPong\s+Jen\b", "潘根", "庞镇"),
    (r"\bPangen\b|\bPongjen\b|\bPongjan\b|\bPongchan\b|\bPong\s+Jen\b", "蓬镇", "庞镇"),
    (r"\bPangen\b|\bPongjen\b|\bPongjan\b|\bPongchan\b|\bPong\s+Jen\b", "旁镇", "庞镇"),
    (r"\baxe\s*master\b", "斧头大师", "斧老大"),
    (r"\baxe\s+of\s+terror\b", "恐怖之斧", "巨凶斧"),
    (r"\bjagged\s+steel\b", "锯齿钢刃", "残钢刃"),
    (r"\bForge\b", "福尔奇", "炼邪"),
    (r"\bmasked\s+walkers?\b", "面具行者", "怪面"),
    (r"\bmasked\s+man\b", "面具人", "怪面"),
    (r"\bshadow\s+sovereign\b", "影主", "冥主"),
    (r"\bshadow\s+sovereign\b", "前任影主", "前任冥主"),
    (r"\bshadow\s+edict\b", "暗影诏令", "冥使"),
    (r"\bSanguine\b", "血腥成就", "血色成就"),
    (r"\bSanguine\b", "血质成就", "血色成就"),
    (r"\bSanguine\b", "桑奎因", "血色"),
    (r"\bor(?:der)?\b", "凤凰社", "组织"),
    (r"\bor(?:der)?\b", "骑士团", "组织"),
    (r"\bor(?:der)?\b", "勋章", "组织"),
    (r"\baxe\b", "轴心国", "斧头"),
    (r"\bbumper\b", "保险杠", "右键"),
    (r"\bkeys?\b", "密钥", "按键"),
    (r"\bboss(?:es)?\b", "老板", "Boss"),
    (r"\bmortar\b", "迫击炮", "灰浆"),
    (r"\bcharge[ds]?\b", "冲锋", "蓄力"),
    (r"\bcamera\b", "摄像头", "镜头"),
    (r"\bcamera\b", "摄像机", "镜头"),
    (r"\binvisible\s+wall\b", "隐形墙", "空气墙"),
    (r"\bNuggets\b", "掘金队", "病人"),
    (r"\bHerald\b", "先驱者", "传令官"),
    (r"\bWuthering\s+Waves\b", "呼啸波涛", "《鸣潮》"),
]

# 漏译体检（只收高置信专名；供 missing --mode pbz --window 1）
PBZ_MISSING_CHECK = [
    (r"\bPhantom\s+Blade(?!\s+Edge)(?:\s+Zero)?\b", ("影之刃零",),
     "Phantom Blade Zero 官方中文=《影之刃零》"),
    (r"\bZol\s+Shang\b", ("左殇",), "Zol Shang 官方中文=左殇"),
    (r"\bDonn(?:ie|e)?\s*Yen\b|\bDonn?en\b", ("甄子丹",),
     "Donnie Yen=甄子丹（饰魔渊）"),
    (r"\bDemon\s+Abyss\b", ("魔渊",), "Demon Abyss 官方中文=魔渊"),
    (r"\bHell\s?Walker\b", ("地狱行者",), "Hellwalker=地狱行者（困难模式）"),
    (r"\bsha?chi\b", ("杀气",), "shachi=杀气"),
    (r"\bposture\b|\bstagger\b|\bshoti\b", ("架势",), "posture/stagger=架势"),
    (r"\bflesh\s+sculptor\b", ("血肉雕刻师",), "Flesh Sculptor=血肉雕刻师"),
    (r"\bflesh\s+lily\b", ("血肉莉莉", "血肉百合"), "Flesh Lily=血肉莉莉/血肉百合"),
    (r"\bspider\s+lil(?:y|ies)\b", ("彼岸花", "莉莉", "百合"),
     "spider lily=彼岸花"),
    (r"\bmask\s+walkers?\b", ("面具行者",), "mask walkers=面具行者"),
    (r"\bthe\s+mandate\b", ("天命",), "the mandate=天命"),
]
