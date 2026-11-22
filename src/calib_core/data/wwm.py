# -*- coding: utf-8 -*-
# @version 3.2.5
"""《燕云十六声》（Where Winds Meet）片源术语/语境表（--mode wwm，2026-11-21 新增）

片源：《What Is Happening With Where Winds Meet !》（英语原声 + 微软翻译，
343 cue，中文在上/英文参考行在下，CRLF 无 BOM，周年版本「滹沱」实机）。

官方依据（2026-11-21 检索）：
- 游戏名《燕云十六声》（Where Winds Meet，网易 Everstone）。
- 新区域「滹沱」、中渡桥之战镇守（官网周年前瞻/游侠研讨会）。
- 中渡桥守将「霞末」、其上级「萧翰」（GameKee 燕云 wiki；萧翰台词
  “你的剑很快，但你们的朝廷，锈了！你杀得了我，却救不了他们！”）。
- 江叔（江晏）、杜重威（后晋北面行营都招讨使）、江湖遗珍（三条新增故事线）。
- 军库/军库钥匙（滹沱区域新镇守的地下军库玩法，非“军械库”）。
- 周年 12 套高级服装任选其一；50+ 首领；六大区域。

硬契约：
- 本表只在 `--mode wwm` 内生效，与 bi/其它片源表隔离；不污染通用双语表。
- 通用词（老板/头目/副本/地下城/兵工厂）**绝不进裸键**，一律走 WWM_CONTEXT
  的英文参考行锚定。
- 「小莫」在《明日方舟》是莫斯提马昵称，故本表只允许在 wwm 模式内把
  「小莫」判成滹沱追逐战 NPC「霞末」；不得进 BILINGUAL_TERMS。
"""

WWM_TERMS = {
    # ── 作品名（ASR/谷翻的多种错形；长键优先） ──
    "Wyrdson Meet": "《燕云十六声》",
    "Where Windsmeet": "《燕云十六声》",
    "Wheres Winds Meet": "《燕云十六声》",
    "Where Wings Meet": "《燕云十六声》",
    "Where Winds Meet": "《燕云十六声》",
    "Wyrdsmeet": "《燕云十六声》",
    "Wyrdsme": "《燕云十六声》",
    "Wyrdson": "《燕云十六声》",
    "Wings Meet": "《燕云十六声》",
    "Wins Meet": "《燕云十六声》",
    # ── 地名 / 战役 ──
    "呼啦舞河岸": "滹沱河岸",
    "呼啦河岸": "滹沱河岸",
    "胡拉河岸": "滹沱河岸",
    "火拓": "滹沱",
    "火陀": "滹沱",
    "滹陀": "滹沱",
    "中都大桥": "中渡桥",
    "中都桥": "中渡桥",
    # ── 人物 ──
    "杜崇伟": "杜重威",
    "杜重伟": "杜重威",
    "姜叔叔": "江叔",
    "肖翰": "萧翰",
    "萧韩": "萧翰",
    "小莫": "霞末",          # 仅 wwm 模式；明日方舟的「小莫」不走本表
    # ── 任务 / 系统 / 道具 ──
    "江湖传承": "江湖遗珍",
    "江湖遗产": "江湖遗珍",
    "尸体搬运者": "背尸人",
    "军械库": "军库",
    "军火库": "军库",
    "武器库": "军库",
    "12个保费": "12套高级时装",
    "12份保费": "12套高级时装",
}

WWM_CONTEXT = [
    # (英文参考行正则, 中文行错形, 正确形)
    # 作品名跨 cue 拆分 / 只出现“相遇之地”等意译
    (r"\bWhere(?:'s|s)?\s+(?:the\s+)?Winds?\s+Meet\b|\bWyrds?me+\b|\bWyrdson\b|\bWins\s+Meet\b|\bWings\s+Meet\b",
     "相遇之地", "《燕云十六声》"),
    (r"\bWhere(?:'s|s)?\s+(?:the\s+)?Winds?\s+Meet\b|\bWyrds?me+\b|\bWyrdson\b|\bWins\s+Meet\b|\bWings\s+Meet\b",
     "风相遇之地", "《燕云十六声》"),
    # 江叔（江晏）：Uncle Chiang/Jiang 锚定，防「姜叔」在生活类片源误伤
    (r"\bUncle\s+(?:Chiang|Jiang)\b", "姜叔", "江叔"),
    (r"\bUncle\s+(?:Chiang|Jiang)\b", "江叔叔", "江叔"),
    # 萧翰：小寒是节气常用词，必须 Xiao Han 锚定
    (r"\bXiao\s*Han\b|\bXiaohan\b", "小寒", "萧翰"),
    # 霞末：小莫已由 WWM_TERMS 处理；夏末是常用词，锚定 Xia/Xiao Mo
    (r"\bXi[a]?o\s*Mo\b|\bXiamo\b", "夏末", "霞末"),
    # 丁晓（滹沱书信 NPC；无官方条目，按音译保留）
    (r"\bDing\s*Xiao\b", "丁校", "丁晓"),
    # 背尸人：抬尸人是常用说法，corpse bearer 锚定
    (r"\bcorpse\s+bearer\b", "抬尸人", "背尸人"),
    # 军库：armory 锚定兵工厂等通用译法
    (r"\barm(?:ou?ry|ory)\b", "兵工厂", "军库"),
    # 首领：boss 在游戏语境统一官方称“首领”
    (r"\bboss(?:es)?\b", "老板", "首领"),
    (r"\bboss(?:es)?\b", "头目", "首领"),
    # 镇守：燕云官方把 dungeon 称“镇守”
    (r"\bdungeon\b", "副本", "镇守"),
    (r"\bdungeon\b", "地下城", "镇守"),
    # premium outfits：机翻“保费/保险费”是典型错形
    (r"\bpremium\s+outfits?\b", "保费", "高级时装"),
    (r"\bpremium\s+outfits?\b", "保险费", "高级时装"),
]

# 漏译体检（供 missing --mode wwm 使用；只收高置信专名）
WWM_MISSING_CHECK = [
    (r"\bWhere(?:'s|s)?\s+(?:the\s+)?Winds?\s+Meet\b|\bWyrds?me+\b|\bWyrdson\b|\bWins\s+Meet\b|\bWings\s+Meet\b",
     ("燕云十六声", "《燕云十六声》"), "Where Winds Meet 官方中文=《燕云十六声》"),
    (r"\bHu(?:o)?tuo\b|\bHula\b", ("滹沱", "滹沱河岸"),
     "Huotuo/Hula=滹沱/滹沱河岸（官方新区域「滹沱」）"),
    (r"\bZhongdu\b|\bZhong\s+du\b", ("中渡桥",),
     "Zhongdu Bridge=中渡桥（不是“中都桥”）"),
    (r"\bDu\s+Chong\s*Wei\b", ("杜重威",), "Du Chong Wei=杜重威"),
    (r"\bXiao\s*Han\b|\bXiaohan\b", ("萧翰",), "Xiao Han=萧翰（官方写法）"),
    (r"\bXi[a]?o\s*Mo\b", ("霞末",), "Xia Mo/Xiao Mo=霞末（中渡桥追逐战 NPC）"),
    (r"\bUncle\s+(?:Chiang|Jiang)\b", ("江叔", "江晏"), "Uncle Chiang=江叔（江晏）"),
    (r"\bJianghu\s+Legacy\b", ("江湖遗珍",), "Jianghu Legacy=江湖遗珍"),
    (r"\bdungeon\b", ("镇守", "副本"), "dungeon 在燕云官方称“镇守”"),
    (r"\barm(?:ou?ry|ory)\b", ("军库", "军械库", "地下军库"),
     "armory=军库/地下军库（官方玩法名）"),
]
