# -*- coding: utf-8 -*-
# @version 2.8.0
"""边狱巴士（Limbus Company）片源术语/语境表（--limbus，2026-10-26 新增）

片源：《Music Composer Reacts - Canto X Boss 3 Battle Theme (Limbus Company)》
（Everything Fantasy，英语原声 + 谷歌翻译，133 cue，每 cue 中文 + 英文参考行，CRLF 无 BOM）。

背景与命名（2026-10-26 核实）：
- 本作**没有官方中文**：Steam appdetails 仅 English/Japanese/Korean，官方公告也只支持三语。
- 用户指定以社区/零协汉化为基准；游戏常用名《边狱巴士》，游戏内组织名仍作《边狱公司》。
- BGM 曲名官方仅英文（Canto X Boss 3 Battle Theme / Canto X Battle Theme C /
  Canto IX Boss 10 Battle Theme 等），保留英文，勿臆造中文。
- 句子级误译（#33/#38/#54/#58/#80/#113/#115/#116/#125）走 fix.tsv，不进术语表。

硬契约：本表只收可安全全局替换的长键/专名；「边狱公司／老大／字符串／大剧院／
结束生命／男声合唱团」等正常中文词不收裸键，避免误伤剧情/其它语境。
"""

LIMBUS_TERMS = {
    # 游戏名：社区常用《边狱巴士》；“边狱公司”是游戏内组织，不作裸键
    "炼狱之舞": "边狱巴士",
    "奥林匹斯公司": "边狱巴士",
    "林布斯公司": "边狱巴士",
    "林布连": "边狱巴士",
    "林布斯": "边狱巴士",
    # 频道名（Everything Fantasy 保留英文）
    "万物幻想": "Everything Fantasy",
    "万物的科里": "Everything Fantasy 的科里",
}

LIMBUS_CONTEXT = [
    # (参考行正则, 中文行错形, 正确形)
    # 旧视频回顾：Boss 1 / Boss 5 / Battle Theme C / Boss 2
    (r"\bcanto\s*10\b.*\bboss\s*five\b", "第五章 Boss", "第5个Boss"),
    (r"\bcanto\s*10\b.*\bboss\s*five\b", "第五章Boss", "第5个Boss"),
    (r"\bboss\s*one\b", "老大一号的意见", "第1个Boss"),
    (r"\bboss\s*one\b", "老大一号", "第1个Boss"),
    (r"\bboss\s*one\b", "老板一号", "第1个Boss"),
    # Canto IX Boss 10 曲名
    (r"\bcanto\s*9\s*boss\s*10\b", "第九章 Boss 10 战斗主题", "第九章第10个Boss的战斗主题"),
    (r"\bcanto\s*9\s*boss\s*10\b", "第九章Boss 10战斗主题", "第九章第10个Boss的战斗主题"),
    (r"\bcanto\s*9\s*boss\s*10\b", "第九章Boss10战斗主题", "第九章第10个Boss的战斗主题"),
    # 曲名标签 / 乐理术语
    (r"\bbattle\s*theme\s*c\b", "战斗主题C", "战斗主题 C"),
    (r"\bshort\s+start\s+of\s+strings\b", "短开头的字符串", "弦乐短促的起音"),
    (r"\bstring\s+phrase\b", "弦乐短语", "弦乐乐句"),
    (r"\brhythmic\s+pulse\b", "节律脉搏", "节奏脉动"),
    (r"\bcallbacks?\b", "回调", "呼应"),
    # Boss 编号口播
    (r"\bboss\s*three\b", "老大三号", "第3个Boss"),
    (r"\bboss\s*three\b", "老板三号", "第3个Boss"),
    # 游戏名：只限“游戏音乐/原声带”语境统一为边狱巴士；剧情里的组织名保持边狱公司
    (r"\bmusic\s+from\s+.*\bCompany\b", "边狱公司", "边狱巴士"),
    (r"\bCompany\s+soundtrack\b", "边狱公司", "边狱巴士"),
]
