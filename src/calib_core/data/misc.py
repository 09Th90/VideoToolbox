# -*- coding: utf-8 -*-
# @version 2.6.0
"""术语/实体数据表

源：subtitle_calib_merged.py L6542-L7171 @ 97d7d463（2026-10-24 冻结快照）
"""
import io
import os
import re
import shutil
import sys
import unicodedata

# 裸键表在 calibrate() 内惰性编译（_compile_map 定义于本文件后部，模块级不可用）

# =============================================================
# 3.1b2 ERROR 占位行批量回填（2026-09-10，명일방주 PV 월드컵 112강 _ko_auto 谷歌翻译）
#   源文件 5031 处 "ERROR" 占位（一些 cue 拆成多行共覆盖 5606 序号），经韩语 ASR
#   重译后以 ERROR行_中文映射.json 回填到首文本列，保留第二行韩语原文。
#   步骤一：ak_ko_err_extract.py 提取 ERROR 序号/时间轴/韩语行 -> ERROR行_提取.tsv
#   步骤二：分批翻译写入 side_001.tsv ~ side_029.tsv（Tab分隔）-> ERROR行_中文映射.json
#   步骤三：merge_final.py 按序号回填，字节级校验：cue 数、序号、时间轴与备份全等，
#     保持 CRLF 换行、无 BOM。对照清册见 对照_PV世界杯_ERROR行.tsv。
#   可确认的官方专名（频率高者）：干员/博士/凯尔希/特蕾西娅/罗德岛/拉芙希妮/
#     临光/瑕光/夜刀/谢拉格/叙拉古/乌萨斯(俄罗斯/苏联主题PV)/萨卡兹/维什戴尔/
#     泥岩/炎熔/赫默/煌/灰烬/傀影/幽灵鲨/霜华/驮兽/龙门/迷迭香。
#   不确定/保留项：语料多为主播 ASR 口语闲聊，机翻专名（如距 雷瓦 相关、스노우샤인
#     Snowshine 等）无官方中文时而保留原文，切勿强行音译进全局表以防误伤。
# =============================================================

# =============================================================
# 3.1c1 流水线 merge --fix 的跨段统一表（2026-08-31 沉淀自 ak_newplayer_qa_calib
#     merge_rebuild.py FIXES；该 6 条既不在 AK_TERMS（未命中=无色差输入），又需在
#     回填后整句统一，故选做 merge 阶段的可选规范化，原 AK 侧车已含人工产物故不双叠）
# =============================================================
MERGE_FIXES = [
    ("巫师", "维什戴尔"),        # Wizard/Wizardell = Wisadel
    ("巫泽尔", "维什戴尔"),      # Wizardell
    ("特蕾迪亚", "酒神"),        # Tradia = Tragodia
    ("可露希尔", "克洛丝"),      # closure = Kroos（抽卡语境）
    ("阿雷迪亚", "arkpedia"),    # Aredia = arkpedia（网站）
    ("夏·新约", "新约能天使"),   # Xia the new covenant
]


# =============================================================
# 3.1c 中文行专属英文噪音替换（2026-08-31 并入 apply_zh_only.py，复用模式 --zho）
#    仅改每个 cue 的首中文行，绝不动英文/参考行；因为 key 原串同时存在于英文行，
#    若写进 ENDFIELD_TERMS/ENDFIELD 全文本遍历会污染英文行，故须独立中文行专属模式。
#    2026-08-31 从终末地评论片（endo_wwstate/endo_state_comments 两处同逻辑）沉淀：
#      Genchin Impact->原神、Nfield(s)->终末地
# =============================================================
ZH_ONLY_TERMS = {
    # 中文行残留的英文游戏名噪音 -> 官方中文（原串同时出现在英文权威行，勿入其它术语表）
    "Genchin Impact": "原神",
    "Nfields": "终末地",
    "Nfield": "终末地",
    # 2026-09-10 ko PV 世界杯（명일방주 PV 월드컵 112강）二次校准：中文首行残留的
    # 明日方舟官方名词英文/音译 -> 官方中文（子代理按 PRTS 等权威源核实）：
    "恩菲尔德": "终末地",                  # Endfield 明日方舟：终末地
    "Mureung": "武陵",                    # 终末地炎国区域（무릉）
    "Mudrock": "泥岩",                    # 重装干员（雇佣兵希瓦）
    "Melantha": "玫兰莎",                  # 近卫干员 N009
    "Majella": "麦哲伦",                  # 辅助/医疗干员（黎博利）
    "Melansarae": "麦哲伦",
    "Magellan": "麦哲伦",
    "Crown Slayer": "弑君者",            # 近卫干员 柳德米拉
    "Guiding Ahead": "吾导先路",          # SideStory（凯尔希，勿译长夜临光）
    "Under Tides": "覆潮之下",            # SideStory（伊比利亚/深海）
    "Undertides": "覆潮之下",
    "Undertide": "覆潮之下",
    "Walk in the Dust": "遗尘漫步",        # SideStory（凯尔希/异客，哥伦比亚）
}


# =============================================================
# 3.1d 音乐/演唱点评通用术语（模式 --react，2026-09-09 新增）
#    源自《Opera Singer Critiques Libera Me From Hell》二次校准（官方中文已检索）：
#      Mori Calliope->森美声（hololive EN 官译）；
#      Elizabeth Rose Bloodflame->伊丽莎白·露丝·布拉德弗雷姆（萌百/官方罗马音）；
#      Gurren Lagann->天元突破红莲螺岩；"Libera Me From Hell" 为拉丁语歌名保留英文。
#    并沉淀声乐/演唱类常用机翻错词（软腭/颤音/换气/高音区/转调/滑音/咏叹调/直声…）。
#    与游戏术语表互斥；仅当显式传 --react 时才套用，避免污染其它片源。
#    注释标注“歧义键”者只在本批演唱语境下正确，慎于它类字幕复用以免误改本义。
# 用法：python subtitle_calib_merged.py <input.srt> --react --out out.srt --report diff.md
# =============================================================
REACT_TERMS = {
    # ---- 人名 / 歌名 / 片名（官方中文）----
    "莫里·卡利俄珀 (Mori Calliope)": "森美声 (Mori Calliope)",
    "莫里·卡利俄珀": "森美声",
    "莫里·卡利彭": "森美声",
    "卡利彭": "森美声",
    "莫里": "森美声",            # 仅指 Mori Calliope 的口语称呼“Mori”
    "伊丽莎白·罗斯·血焰": "伊丽莎白·露丝·布拉德弗雷姆",
    "伊丽莎白·罗丝·血焰": "伊丽莎白·露丝·布拉德弗雷姆",
    "罗斯·血焰": "露丝·布拉德弗雷姆",
    "罗丝·血焰": "露丝·布拉德弗雷姆",
    "血德的": "露丝·布拉德弗雷姆的",
    "格伦·洛根": "天元突破红莲螺岩",
    "古兰贷款": "天元突破红莲螺岩",
    "古林·洛根": "天元突破红莲螺岩",
    "Grun Logan": "天元突破红莲螺岩",
    "Guran Logan": "天元突破红莲螺岩",
    "Gurin Logan": "天元突破红莲螺岩",
    "Liidame": "Libera Me From Hell",
    "利比达姆": "Libera Me From Hell",
    # ---- 声乐 / 演唱通用机翻错词 ----
    "测量 VB": "克制的颤音",
    "VBR": "颤音（Vibrato）",   # vibrato 之 ASR 缩写
    "verd": "颤音",
    "软托盘": "软腭",            # soft palate；歧义键（“托盘”实为“腭”之误）
    "上层寄存器": "高音区",
    "直语": "直声",              # straight tone
    "更改密钥": "转调",          # change key
    "一部分是球场": "一部分在于音高",   # pitch
    "还有很多幻灯片": "还有很多滑音",     # slides ≈ glissando
    "歌剧艾莉亚": "歌剧咏叹调",  # aria
    "杂乱的歌声": "歌剧式演唱",  # operatic
    "干净的oporatic": "干净的歌剧演唱",
    "远离标准的 oporadic": "远离标准的歌剧式唱法",
    "过度发音和宣告": "过度咬字和清晰的吐字",   # overarticulation & enunciation
    "我喜欢咬一口": "我喜欢那种咬字的力度",       # bite of the text；歧义键
    "重新列出它": "再重听一遍",  # relist ≈ relisten
    "10,00%": "100%",
    "凉爽的": "很酷",            # cool；歧义键（温度义的“凉爽”会被误改）
    "谈论两个非常非常的谎言": "聊聊两位非常非常有才华的人（的演绎）",
    "对抗权力。触摸不可触摸的东西": "对抗强权。触摸那不可触碰之物",
    "排，排，对抗力量，就像这样": "划呀，划呀，对抗那力量，就像这样",
    "权力给窥视者。电源为": "力量属于大家。力量为",
    # ---- 2026-09-14 终末地音乐 reaction 片沉淀 ----
    # 片源：《Music Composer Reacts - Alleikhreos Boss Theme (Arknights: Endfield)》
    #   （Everything Fantasy 频道，英语原声 + 谷歌翻译，468 cue；逐 cue 整行覆盖 400 处，
    #    verify 全通过。完整流程见 skill `subtitle-calib-script`。）
    # 官方依据（已检索）：终末地 1.4 最终 BOSS 官方中文＝阿莱克琉斯（千夫长），
    #   主题曲作曲 Crywolf / YMIR、演唱 Crywolf（《众生行记》OST 曲 7 ＝
    #   Somniomancer [null set]，Crywolf，2025-05-04 塞壬唱片-MSR）。
    # 戒律：本片机翻误形绝大部分是**通用中文词**——梦舞者/嗜睡/索曼瑟/歌曼/老板/钥匙/
    #   希米尔/埃米尔/蝙蝠/未成年/通俗圣经/教堂台阶——按硬契约第 4 条**一律不入表**
    #   （会误伤正常语境），只能逐 cue 侧车整行覆盖；下面只收非正常中文词的安全键。
    "冷狼": "Crywolf", "哭狼": "Crywolf",   # crywolf 机翻直译；社区昵称恰为"哭狼"，字幕仍统一保留英文名
    "梦巫师克雷沃尔夫": "Crywolf", "克雷沃尔夫": "Crywolf",
    "我们改变了钥匙": "我们转调了",          # change key 机翻直译（长键，避免误伤"钥匙"本义）
    # ---- 2026-09-21 gacha 争议片《Gacha Games Are Soulless Copies Of Actual Games》沉淀 ----
    # 片源：英语原声 + 谷翻，694 cue（每 cue 恰 2 行：中文 + 英文参考行），主题为
    #   「抽卡游戏(gacha)是否是现实游戏『无灵魂复制品』」的辩论，大量游戏/角色专名。
    # 处理：extract→逐 cue 对着英文参考行整行重写中文→二次检索官方中文后精修；verify+length 全过。
    # 官方依据（均已检索确认）：
    #   Noticefall / Nodusfall = 米哈游新作《源初之结》（类怪物猎人多人共斗 ARPG，Gamescom 2026 首曝，
    #     被指像《艾尔登法环》+《怪物猎人》）；Ananta = 网易《异环》（Naked Rain，
    #     与 Hotta Studio 的 NTE《无限大》是两款不同作品，2026-10-21 订正）；
    #   Duet Night Abyss(DNA) = 英雄游戏《二重螺旋》（Pan Studio，被指抄袭 Warframe）；
    #   Mighty = 万敌（崩坏：星穹铁道角色，与 Fate 吉尔伽美什立绘撞车引争议）；
    #   Jane Doe = 简·杜（绝区零）；Uncus/Unctus = Eunectes 森蚺（明日方舟萨尔贡重装，盾+斧+机甲）。
    # 戒律：以下键均为**英文专名/特殊串**，作源键安全；替换目标不带书名号（中文行若已用《》包裹会自动衔接）。
    #   ⚠️ DNA / 深空之眼 **不在此表**——"DNA"是通用词（脱氧核糖核酸，本片就有"脱氧核糖核酸"直译）、
    #      "深空之眼"是真实游戏（Aether Gazer）官方名，裸键会误伤正常语境；
    #      它们已通过下方 `REACT_CONTEXT` 参考行佐证机制（英文 \bDNA\b / D Night Abyss 命中才替换）安全入表。
    "Noticefall": "源初之结", "notice fall": "源初之结", "Nodusfall": "源初之结",
    "Neverness to Everness": "无限大", "NTE": "无限大",   # NTE 官方中文《无限大》（长键先行）
    "Ananta": "异环",                                     # Ananta 官方中文《异环》，勿与 NTE 混
    "Jane Doe": "简·杜",
    "Mighty": "万敌",
    "Uncus": "森蚺", "Unctus": "森蚺",
    # ---- 2026-10-22 鸣潮 OST reaction 二校（官方 credit 全名 / Persona 中文化）----
    "奥巴代亚·布朗-比奇": "Obadiah Brown-Beach",
    "奥巴代亚·布朗": "Obadiah Brown-Beach",
    "奥巴代亚布朗": "Obadiah Brown-Beach",
    "Persona音乐": "《女神异闻录》音乐",
    "Persona 音乐": "《女神异闻录》音乐",
}

# 用法：python subtitle_calib_merged.py --react <input.srt> --out out.srt
#   --react 与游戏模式互斥；仅套用 REACT_TERMS 统一首中文行（不动英文/参考行）。

# 3.1e reaction 片「参考行佐证」歧义词表（2026-09-21 新增，仅 --react 生效）
# =============================================================
# 与 REACT_TERMS 的区别：REACT_TERMS 是无条件子串替换（适合英文专名键）；
# 这里收的是**歧义中文词**——裸键会误伤正常语境，必须等英文参考行命中正则才替换。
# 结构：[(英文正则, 中文错误形式, 中文正确形式)]，与 CONTEXT_MAP 同构。
# 应用时机：在 REACT_TERMS 替换之后，仅当该 cue 的英文参考行命中正则且中文行含错误形式才替换。
# 2026-09-21 gacha 争议片沉淀（官方依据见 REACT_TERMS 注释块）：
#   DNA = Duet Night Abyss《二重螺旋》——但 "DNA" 是通用词（脱氧核糖核酸，本片就有直译），
#     且 "DNA Tower Fantasy"（二重螺旋+幻塔）也以 DNA 打头，必须英文 \bDNA\b 佐证；
#   「深空之眼」是真实游戏（Aether Gazer）官方名，本片却是 Duet Night Abyss 的 ASR 误听
#     （英文 D Night Abyss = Duet Night Abyss），须英文佐证才敢替换。
REACT_CONTEXT = [
    (r"\bDNA\b", "DNA", "《二重螺旋》"),
    (r"\bDNA\b", "脱氧核糖核酸", "《二重螺旋》"),
    (r"[Dd] ?[Nn]ight ?[Aa]byss", "深空之眼", "《二重螺旋》"),
]


# =============================================================
# 3.1f 《崩坏：星穹铁道》（HSR）片源术语表（模式 --hsr，2026-10-20 新增）
# =============================================================
# 片源：《WuWa Player REACTS To EVERY HSR Animated Short (It Was Epic)》——鸣潮玩家
#   AmethystAbrams 反应崩铁 12 部官方动画短片，英语原声 + 谷歌翻译中文，684 cue，
#   每 cue 恰 2 文本行（首中文、次英文参考行），CRLF、无 BOM。
#   此前工具箱**没有任何崩铁资产**：--react 命中 0；--bi 会把崩铁语境误改成鸣潮/终末地
#   专名（实测 13 处，其中「骑士们->明日方舟们」4 处、「罪孽->心月狐孽」2 处、「幽灵骑士->
#   幽灵隧者」等全是误伤），故必须独立建表并按模式隔离。
# 官方依据（2026-10-20 联网检索：米哈游官网公告 / 星穹铁道 BWIKI 官方视频页 / 萌娘百科 /
#   维基百科「遐蝶」「黄泉」/ 豆瓣短片条目原文简介）：
#   动画短片 12 部（发布顺序）：「飞光」(景元·彦卿·镜流)、「玄黄」(丹恒·饮月/丹枫)、
#     「永劫轮舞」(黄泉·黑天鹅)、「格拉默的余烬」(流萤·卡芙卡)、「清闲自在身」(景元·飞霄·
#     椒丘·怀炎)、「银河忍法帖•乱武驱魔破邪斩月之卷」(乱破)、「大黑塔的魔法厨房」、
#     「那安息的长夜」(遐蝶)、「跋涉」(丹恒·腾荒)、「你好，世界」、「这游戏还能不能玩了？」
#     (银狼LV.999)、「听！狂欢在那神佑的山巅」(白厄)。
#   世界观：星神(Aeon)／令使(Emanator)／绝灭大君(Lord Ravager，「焚风」「幻胧」等)／
#     反物质军团／云骑军／仙舟「罗浮」／魔阴（身）／长生种／流光忆庭／假面愚者／无名客／
#     星际和平公司／巡海游侠／星穹列车／匹诺康尼／翁法罗斯／格拉默／母虫／女皇陛下／
#     阮·梅（中点为官方写法）／乱破（Rappa，ASR 常吞成 rapper）／银狼LV.999。
# 【硬契约第 4 条】本片大量机翻错形是**通用中文词**（银河战士/亚伦/说唱歌手/东方/赫拉/
#   永恒/阿翁/努克/快递队伍/回忆花园/恐慌篇章/玛拉），裸键必误伤，一律走 HSR_CONTEXT
#   英文参考行锚定；下面只收**专名级、非正常中文词**的安全键（含英文噪音键，谷翻常把
#   它们原样留在中文行里）。
HSR_TERMS = {
    # ---- 阵营 / 组织 ----
    "地狱公爵": "绝灭大君·焚风",          # Duke Inferno（谷翻按字面译）
    "歼灭帮": "反物质军团", "毁灭帮派": "反物质军团",
    # ---- 角色名音译错形 -> 官方中文 ----
    "卡斯特鲁斯": "遐蝶", "卡斯特里斯": "遐蝶",   # Castorice（Caster/Casterus 太短，不收）
    "圣波姆": "帕姆",                       # St Pom pom
    "赫特": "黑塔", "赫特尔": "黑塔",       # Herter/Herta
    #   二次校准补（2026-10-20，同片 #426/#427 实证）：官方「黑塔」是四星**人偶**，
    #   五星成年形态另有专名**大黑塔**；机翻只会写"赫特/黑塔"，故必须收这三条长键，
    #   且要排在「赫特」之前（_replace_report 长键降序），否则会先被短键拆成"黑塔娃娃"。
    "五星级赫特": "大黑塔", "四星级赫特": "四星黑塔", "赫特娃娃": "黑塔人偶",
    "罗恩·梅": "阮·梅", "罗恩梅": "阮·梅", "阮梅": "阮·梅",
    "敦恒": "丹恒", "丹洪": "丹恒", "东恒": "丹恒",   # Dunhung/Dan Hung
    "景流": "镜流", "景柳": "镜流",         # Jinglyu
    "金君": "景元",                          # Jinguen
    "菲南": "白厄",                          # Phainon
    "埃利奥": "艾利欧",                      # Elio（星核猎手首领）
    "Kuffka": "卡芙卡", "Nook": "纳努克",   # 中文行里的英文噪音
    # ---- 仙舟 / 世界观专名 ----
    "西恩霍": "仙舟", "云骑士": "云骑军",   # Cienjo / cloud knight
    "格拉姆母亲": "格拉默", "格拉姆之母": "格拉默",   # Glamoth 被 ASR 拆成 Glam's mother
    "虫群母亲": "母虫", "虫群妈妈": "母虫",
    "发散者": "令使",                        # Emanator
    # ---- 片名 / 作品名 ----
    "黑色四叶草": "黑色五叶草",             # Black Clover 官方简体
    "恶魔泣": "鬼泣",                        # Devil May Cry
    "Panicon": "匹诺康尼",
    "Hongkey Starl": "崩坏：星穹铁道", "Hankai Starl": "崩坏：星穹铁道",
    "半海星": "星穹铁道",                    # Hankai Starl 的汉字化
}


# 3.1g HSR_CONTEXT：崩铁片源的**歧义中文词**锚定表（与 HSR_TERMS 配套，仅 --hsr 生效）
#   结构同 CONTEXT_MAP/AK_CONTEXT：(英文正则, 中文错误形式, 中文正确形式)。
HSR_CONTEXT = [
    (r"\bGalaxy Rangers?\b", "银河战士", "巡海游侠"),
    (r"\bGalaxy Rangers?\b", "银河游侠", "巡海游侠"),
    (r"\bAarons?\b", "亚伦", "黄泉"),                  # Aaron = Acheron 的 ASR 误听
    (r"\brappers?\b|\bRappa\b", "说唱歌手", "乱破"),
    (r"\bexpress crew\b", "快递队伍", "星穹列车组"),
    (r"\bthe Nameless\b", "无名者", "无名客"),
    (r"\bHeras?\b|\bHerters?\b", "赫拉", "黑塔"),
    (r"\bDong\s?Fongs?\b|\bDong\s?Fangs?\b", "东方", "丹枫"),
    (r"\bAons?\b|\bEons?\b|\bAeons?\b", "阿翁", "星神"),
    (r"\bAons?\b|\bEons?\b|\bAeons?\b", "永恒", "星神"),
    (r"\bNooks?\b|\bNanook\b", "努克", "纳努克"),
    (r"\bPanics?\b|\bPanic[kc]\b|\bPanicon\b", "恐慌篇章", "匹诺康尼篇"),
    (r"\bMaras?\b", "被玛拉击中", "身堕魔阴"),
    (r"\bMaras?\b", "玛拉", "魔阴"),
    (r"\bGarden of Recollection\b", "回忆花园", "流光忆庭"),
]


# =============================================================
# 3.1h 《宝可梦 黑／白》城镇主题 reaction 片术语表（模式 --pkm，2026-10-21 新增）
# =============================================================
# 片源：《Pokémon Fans Were Right: Town Themes are ADDICTIVE》——MarcoMeatball
#   英语原声 + 谷歌翻译中文，547 cue，每 cue 恰 2 文本行（首中文、次英文参考行），
#   CRLF、无 BOM。首轮人工逐 cue 复核修正 429 处；本表沉淀可复用的专名规则。
# 官方依据（2026-10-21 检索 52poke / 百度百科 / Bulbapedia）：
#   合众城镇：鹿子镇(Nuvema/カノコ) 唐草镇(Accumula/カラクサ) 三曜市(Striaton/サンヨウ)
#   七宝市(Nacrene/シッポウ) 飞云市(Castelia/ヒウン) 雷文市(Nimbasa/ライモン)
#   帆巴市(Driftveil/ホドモエ) 吹寄市(Mistralton/フキヨセ) 雪花市(Icirrus/セッカ)
#   双龙市(Opelucid/ソウリュウ) 笼目镇(Lacunosa/カゴメ) 海边镇(Undella/サザナミ)
#   金轮镇(Anville/カナワ) 黑色市(Black City) 白色森林(White Forest) 宝可梦联盟。
# ⚠ 谷翻把日文城镇名按罗马音/字面直译，错形与正常中文词高度重叠：
#   「瑞安市」是真实城市、「石浦」是真实地名，「川镇」「黑人/白人」「黑城」「白森林」
#   都可能是正常语义 → 这些**一律走 POKEMON_CONTEXT 英文参考行锚定**，绝不进裸键。
#   只有明确音译错形（可可镇/角草镇/空草镇/索努市/霍德莫市/西鲁市/加贡镇/鹿目镇/
#   索纳米镇/漂移面纱/卡斯特拉城/卡斯特拉市/宝可梦黑…）才作为安全裸键。
POKEMON_TERMS = {
    # ---- 城镇名：谷翻音译/字面直译 -> 官方中文 ----
    "可可镇": "鹿子镇", "角草镇": "鹿子镇",          # Kanoko Town（#75/#52 两处 ASR 变体）
    "空草镇": "唐草镇",                              # Karakusa Town
    "索努市": "三曜市",                              # Sanyou City
    "卡斯特拉城": "飞云市", "卡斯特拉市": "飞云市",    # Castelia City（谷翻按 Castella 音译）
    "霍德莫市": "帆巴市",                            # Hodomoe City
    "霍德莫伊·志布·萨努·卡库萨": "帆巴、七宝、三曜、唐草",  # #236 四城连读
    "漂移面纱": "帆巴市",                            # Drift Veil 字面直译（#210）
    "西鲁市": "双龙市",                              # Souryuu City（Siru/Sour ASR 截断）
    "加贡镇": "笼目镇", "鹿目镇": "笼目镇",          # Kagome Town（#333 自我纠正两次）
    "索纳米镇": "海边镇",                            # Sazanami Town
    "白人代表好": "白色森林",                        # #433 White For Okay 机翻残句
    # ---- 作品名规范化（官方中文用空格/斜杠）----
    "宝可梦黑白": "宝可梦 黑／白",
    "宝可梦黑": "宝可梦 黑",
    "宝可梦白": "宝可梦 白",
}


# 3.1i POKEMON_CONTEXT：宝可梦片源的**歧义中文词**锚定表（仅 --pkm 生效）。
#   结构同 HSR_CONTEXT：(英文参考行正则, 中文错误形式, 中文正确形式)。
POKEMON_CONTEXT = [
    (r"\bShipu City\b|\bShipoo City\b", "石浦市", "七宝市"),
    (r"\bRyan City\b", "瑞安市", "雷文市"),
    (r"\bKawa Town\b|\bKanawa Town\b", "川镇", "金轮镇"),
    (r"\bBlack City\b", "黑城", "黑色市"),
    (r"\bBlack City\b", "黑人", "黑色市"),
    (r"\bWhite Forest\b", "白森林", "白色森林"),
    (r"\bWhite Forest\b", "白人", "白色森林"),
    (r"\bBlack City\b.*\bWhite\b", "白人", "白色森林"),   # #433 两城同句
    (r"\bcalled Drift\b", "漂移", "Drift"),             # #220 讨论英文名，保留原文
    (r"\bwalking base\b", "行走底座", "行进贝斯线"),
    (r"\bwalking base\b", "步行基地", "行进贝斯线"),
    (r"\bwalking track\b", "步行跑道", "散步曲"),
    (r"\bA SA city\b|\bSekka [Cc]ity\b", "南非城市", "雪花市"),
]


# =============================================================
# 5. 英文参考行修正资产（2026-08-29 并入；原 ERROR 占位行翻译表已于同日删除）
#    来源：srt_calibrator.py、fix_srt.py、7月 WW 演唱会脚本通用专名。
#    默认不启用：--fix-en 才动英文/参考行。
# =============================================================

# 5.1 英文/参考行 ASR 错词修正（错误形式 -> 正确形式，子串替换，长词优先）
# 注意：纯子串替换，个别短 key（TD/toa/fract 等）可能误伤含该子串的单词，
# 仅在对照双语片源确认需要时开启 --fix-en。
EN_LINE_TERM_FIXES = {
    # 角色名（srt_calibrator.py；fix_srt.py 的 Jouer->Jinhsi 自承存疑，跳过）
    "Arctites": "Arknights", "Amiia": "Amiya",
    "Mortafe": "Mortefi", "Mortifi": "Mortefi",
    "Senoa": "Chixia", "Yap Yap": "Yangyang",
    "Chizzy": "Jiyan", "Gian": "Jiyan",
    "Yinllin": "Yinlin", "Yindllin": "Yinlin", "Yinland": "Yinlin",
    "Ginshi": "Jinhsi",
    # 地名
    "Jingo City": "Jinzhou City",                          # 长词优先于 Jingo
    "Jingo": "Jinzhou", "Jingjo": "Jinzhou", "Gingjo": "Jinzhou", "Jindo": "Jinzhou",
    "Hang Long": "Huanglong", "Wang Long": "Huanglong", "Guang Long": "Huanglong",
    # 阵营 / 敌人
    "Fraidus": "Fractsidus", "Fraid": "Fractsidus",        # 残星会官方英文名（依 md 中英对照）
    # 2026-10-05 3.7 英文 reaction 片实测：裸短键 fractur/fract 误伤全部 8 处正常英文词
    # （fractal=万相分形 6 处、fractured strand、a fraction of 各 1 处），而真 Fractsidus
    # 的 ASR 误听均作 Fraidus/Fractidus（本片 10 处 Fraidus 已正确修复），故删除裸短键，
    # 改收精确音近形 Fractus；fractal/fracture/fraction/fractured 等常用词从此免疫。
    "Fractus": "Fractsidus",
    # 断词自动重组(_rejoin_known)后的驼峰形 -> 官方拼写大小写（2026-10-05 3.7 英文 reaction 片）
    "YangYang": "Yangyang", "TongNing": "Tongning", "JingRan": "Jingran",
    # tacid + discord(s)/discourse(s) 原始误写组合键，长于 tacid 先行
    # （#3342 tacid discords / #4734 tacid discord / #5260 tacid discourse，2026-10-05 3.7 片）
    "tacid discourses": "Tacet Discords", "tacid discourse": "Tacet Discord",
    "tacid discords": "Tacet Discords", "tacid discord": "Tacet Discord",
    # --- 2026-10-05 第二部 3.7 英文 reaction 片（I Wasn't Ready...）逐 cue 核实补录 ---
    "Hong Lang": "Huanglong",                                   # 瑝珑（与 Hang Long 同组）
    "Shrungfang hold": "Schwanfong Hold", "Shrung fun hold": "Schwanfong Hold",
    "Schwan Funk": "Schwanfong", "Schwanf.": "Schwanfong.",     # 玄方碎形（land of Schwanf.）
    "moving to MJ": "moving to Mengzhou",                       # MJ=Mengzhou 梦州（短键防误伤）
    "Mojo and the": "Mengzhou and the", "to Mango": "to Mengzhou",
    "balanaphora": "balanophora",                               # 蛇菰英文生词拼写修正
    "Shind": "Shin",                                            # 心月狐 ASR 吞音
    "Evedropping": "Eavesdropping", "Evedroping": "Eavesdropping",
    "wibes": "vibes",                                           # 氛围错拼
    "practal": "fractal",                                       # fractal 口胡形（fractal proliferation）
    "Fox Fox shadow": "Fox shadow",                             # ASR 重复 Fox（Nexus Fox Shadow）
    "S Surgeon Rex": "Surgeon Rex",                             # 句首碎词 S
    "those tacit discords": "those Tacet Discords",             # 残象（tacit=tacet 变体）
    "like Shane": "like Sheen",                                 # Shane=Sheen 心月狐（组合键防常见人名误伤）
    "Swimming said": "Suoming said", "adore swimming": "adore Suoming",
    "get to swimming": "get to Suoming",                        # Swimming=Suoming 锁暝（组合键防游泳语境）
    "Tang Tang Ning": "Tongning",                               # 同宁结巴重复形
    # --- 英文行专名规范（实体 variants 只投中文行表，英文行须在此手动登记）---
    "Tanging": "Tongning",
    "Strongfang's": "Schwanfong's", "Strongfang": "Schwanfong Hold",
    "Shrung": "Schwan", "fun hold": "fong Hold",                # 跨行碎形 miniature Shrung / fun hold
    "Schwanfunhold": "Schwanfong Hold",
    "Schwangfunhold's": "Schwanfong Hold's", "Schwangfunhold": "Schwanfong Hold",
    "Schwangfong": "Schwanfong",
    "Shwanfong Hold": "Schwanfong Hold", "Shwanfang": "Schwanfong",
    "Schwangfang's": "Schwanfong's", "Schwangfangjo": "Schwanfong",
    "Schwang Fong": "Schwanfong",
    "Lor keeper": "Shorekeeper",
    "MJ Joe": "Mengzhou", "Mang Joe": "Mengzhou",
    "Simakum Nexus": "Simulacrum Nexus", "Sumacum Nexus": "Simulacrum Nexus",
    "simakum nexus": "Simulacrum Nexus", "sumacum nexus": "Simulacrum Nexus",
    "tessid discords": "Tacet Discords", "Tessid Discords": "Tacet Discords",
    "Tessid Discord": "Tacet Discord", "Tasa Discord": "Tacet Discord",
    "Tacit discord": "Tacet Discord", "Tacit discords": "Tacet Discords",
    "tacit discords": "Tacet Discords", "those tacit": "those Tacet",
    "Nintendent": "Intendant",
    "Jingan": "Jingran",
    "Susheen": "Suxin", "susheen": "Suxin",
    "Wii Moon Festival": "Waking Moon Festival",
    "bang boo": "bamboo", "sheen guide": "Sheen's guidance",
    "Moonf Fox": "Moon Fox", "moonf fox": "Moon Fox",   # 心月狐英文称号漏 f（8 处，含小写）
    "Shwanfong": "Schwanfong",                          # 玄方城 ASR 形（注意不收短键 Shwan：Shwan School=玄元境学派保留）
    "Swarming": "Suoming",                              # 锁暝 ASR 误听（swarm 蜂群；大写专名形态，小写普通词不动）
    "Swaming": "Suoming",                               # 锁暝 ASR 误听（少 r 形，#4316 Sister Swaming）
    "Auto Puppets": "Autopuppets", "Auto Puppet": "Autopuppet",
    "auto puppets": "autopuppets", "auto puppet": "autopuppet",  # 机傀官方英文 autopuppet 合写
    "the attendant ordered": "the Intendant ordered",  # #927 attendant=intendant(州监) ASR 漏音节，组合键防误伤普通 attendant
    "Suming": "Suoming",                                # 锁暝 ASR 形（#1015 Suming and Ching）
    "Chingan": "Jingran",                               # 景燃 ASR 形（#6776，下句自我纠正为 Jingron）
    "Jingron": "Jingran",                               # 景燃 ASR 形（#6779 等）
    "Abiter": "Arbiter",                                # 御者 Arbiter 漏音节（#2088）
    "Aby": "Abby",                                      # 阿布 Abby ASR 形（#5846/#5990 Aby's）
    "Shranong": "Schwanfong",                           # 玄方城 ASR 形（#5677 land of Shranong）
    "Thrronodians": "Threnodians", "Thrronodian's": "Threnodian's",
    "Thrronodian'": "Threnodian'", "Thrronodian": "Threnodian",
    "Throdian": "Threnodian", "Trinodian": "Threnodian", "Frenodian": "Threnodian",
    "Renoians": "Lament",
    # 游戏术语
    "sauna disc": "sono disc",
    "symphidi": "symphony", "symphodi": "symphony", "symphi": "symphony",
    "tacid": "tacet",
    "Tessa discords": "Tacet discords", "Tessa": "Tacet",  # 长词优先
    "ExoRiders": "Exostrider", "Exoriders": "Exostrider",  # Exostrider 大小写变体（中文残留英文 / 英文参考行）
    "Alisium": "illusion", "Pificant": "insignificant", "Shov": "Sure",
    # 哨兵 / NPC（fix_srt.py 决定保留 Jer 不改，故无 Jer->Jue）
    "Jouer": "Jue", "Jueer": "Jue",
    # fix_srt.py 独有
    "Sono": "sono",                                        # 句中保持小写
    "MSQ": "main story quest",
    "TDs": "Tacet Discords", "TD": "Tacet Discord",        # 短子串，注意误伤
    "tacet discords": "Tacet Discords", "tacet discord": "Tacet Discord",
    "the crownless": "the Crownless", "crownless": "Crownless",
    "Miss Magistrate": "Madame Magistrate", "magistrate": "Magistrate",
    # 7月 WW 演唱会脚本通用专名（calibrate_ww.py / calibrate_ww_v2.py / auto_correct.py）
    "Shortke keeper": "Shorekeeper", "Shortke": "Shorekeeper",
    "Chamilleia": "Camellya", "Chameleia": "Camellya",
    "Chamilia": "Camellya", "Camillia": "Camellya",
    "base drops": "bass drops", "base drop": "bass drop",  # 仅 drop 语境，单词 base 不改
    "Tik Tok": "TikTok", "tik tok": "TikTok",
    "toa": "TOA", "Toa": "TOA",                            # 逆境深塔缩写，注意 toad 类误伤
    # --- 2026-09-09 明日方舟 OST 分析片（Ratio Ultima）ASR 错词 ---
    # 证据：arknights.wiki.gg/wiki/Episode_14/OST（Arknights / Yuka Kitamura）
    "Ark Knights": "Arknights",                            # ASR 误拆
    "Kamura": "Kitamura",                                  # 作曲家 Yuka Kitamura（片内 #258/#709/#736 作 Kitamura）
}


# =============================================================
# 5.x 塞尔达传说（Zelda）片源术语表（--zel 模式，2026-09-14 新增）
#   片源：《ZELDA NINTENDO DIRECT!!!! OOT RELEASE DATEEEE WHENN》——英文直播反应录像
#     （英语原声 + 谷歌翻译，1596 cue，逐 cue 整行覆盖，verify 全通过）。
#   本表仅供**未来塞尔达片源**的一键术语校准，与鸣潮/方舟/终末地等表严格隔离，勿混用。
#   官方简体中文译名依据（已联网检索 2026-09-14，任天堂 / 萌娘百科 / 百度百科）：
#     Ocarina of Time＝时之笛；Twilight Princess＝黄昏公主；The Wind Waker＝风之律动
#     （旧俗译“风之杖”，官方简体现为“风之律动”，故收录 风之杖→风之律动）；
#     Majora's Mask＝梅祖拉的假面；Phantom Hourglass＝幻影沙漏；Spirit Tracks＝灵魂轨迹；
#     Breath of the Wild＝旷野之息；Tears of the Kingdom＝王国之泪；
#     Hyrule＝海拉鲁；Triforce＝三角力量；Link＝林克；Zelda＝塞尔达；Ganondorf＝加农多夫；
#     Navi＝娜薇；Kokiri＝科奇里；Kakariko＝卡卡利科；Zora＝卓拉；Goron＝鼓隆族；
#     Koji Kondo＝近藤浩治；Eiji Aonuma＝青沼英二；Shigeru Miyamoto＝宫本茂；
#     Hisashi Fujibayashi＝藤林秀麿；Xenoblade Chronicles＝异度神剑（决定版）。
#   戒律（硬契约第 4 条）：本片机翻的系统性误译绝大多数是**通用中文词**——呼吸/狂野/
#     好吃的食物/伟大的一天/精神·曲目(Spirit tracks)/合并曲等——一律**不入裸键**（必误伤正常
#     语境），只能逐 cue 侧车整行覆盖；下面只收专名级、非正常中文词的安全键，长词优先。
ZELDA_TERMS = {
    # ---- 各作标题：俗译/旧译/机翻误形 -> 官方简体中文 ----
    "暮光公主": "黄昏公主",            # Twilight Princess（谷哥常直译“暮光”）
    "风之杖": "风之律动",              # The Wind Waker 官方简体（旧俗译“风之杖”）
    "风之节拍器": "风之律动",          # Wind Waker 另一种直译
    "穆祖拉": "梅祖拉", "姆祖拉": "梅祖拉", "姆朱拉": "梅祖拉",   # Majora 变体
    "穆休拉": "梅祖拉",                # 繁中“穆修拉”系直落简体的误形
    # ---- 地名 / 族名 / 角色（Hyrule 谷哥高频误作“海拉尔”）----
    "海拉尔": "海拉鲁", "海鲁尔": "海拉鲁",   # Hyrule
    "佐拉": "卓拉",                    # Zora；歧义低，卓拉为官方
    "哥隆": "鼓隆", "郭隆": "鼓隆",    # Goron
    "基里森林": "科奇里森林", "可奇里": "科奇里",   # Kokiri
    "卡卡尔里科": "卡卡利科", "卡卡尔·里科": "卡卡利科",  # Kakariko
    "那比": "娜薇", "纳美人": "娜薇", "纳维": "娜薇",   # Navi（“纳美人”系 Avatar 误入，塞尔达语境＝娜薇）
    # ---- 制作人 / 作曲家（人名 ASR·机翻误形 -> 官方）----
    "近藤浩二": "近藤浩治",            # Koji Kondo
    "宫本猫": "宫本茂",                # Shigeru Miyamoto
    # ---- 同场异业作品 ----
    "泽诺之刃": "异度神剑", "割裂之刃": "异度神剑",   # Xenoblade 机翻直译
}


# =============================================================
# 5.9 英文参考行「ASR 断词/粘连」容错层（2026-09-28 新增）
#
#   问题（用户实测）：英文 ASR 常在**单词内部插空格**——"reson ator"=resonator，
#     "Water ing lace"=Wuthering Waves（断词 + 误听）。谷歌翻译按**字面**直译这些
#     断片，产出中文残渣："浇水蕾丝刚刚在共鸣者展示柜上发布"（正确应为"鸣潮…"）。
#     既有机制挡不住，因为：① 中文残渣是**无穷生成**的，术语表永远列不全；
#     ② CONTEXT_MAP 的英文锚定正则（\bWuthering\b / resonators?）因断词**匹配不上**，
#        所有佐证规则集体失效——这才是根因（事后往中文表补键，挡不住下一部新片）。
#
#   本层只作用于「参考行匹配」这一路（对既有输出零侵入，verify 仍逐字节保结构）：
#     ① EN_ASR_SPLIT_FIXES：人工沉淀的「断词/误听英文形 -> 规范英文」，锚定前先规整；
#        --fix-en 时同时修正英文输出行（与 EN_LINE_TERM_FIXES 同风格，长键优先）。
#     ② _rejoin_known()：通用重组——相邻两段纯字母若拼起来是**已知英文专名**
#        （词表自动取自 ENTITIES 的 en 名 + 两张英文修正表的目标），去掉中间空格。
#        纯断词（reson ator）无需人工补表；误听（Water ing lace）仍须走 ①。
#     ③ _ref_for_match()：①②合体，供 CONTEXT/EXCLUDE 锚定使用；报告里的参考行
#        仍按原样输出（除 --fix-en），保证 verify 结构零改动。
#     ④ scan-split 子命令：扫全片英文行、列出疑似断词候选（只读），便于补 ①。
# =============================================================
EN_ASR_SPLIT_FIXES = {
    # --- 鸣潮：Wuthering Waves 的断词/误听（2026-09-28 用户实测片源）---
    # 实测参考行："Water ing lace just released shin the reson ator showcase,"
    "Water ing lace": "Wuthering Waves",     # Water ing（断词）+ lace（Waves 误听）
    "Watering lace": "Wuthering Waves",
    "Watering Lace": "Wuthering Waves",
    "Wuthering lace": "Wuthering Waves",
    "Watering Ways": "Wuthering Waves",      # 对应既有中文键"浇水方式"（原误置于 ENDFIELD_TERMS）
    "Watering Waves": "Wuthering Waves",
    "Withering Waves": "Wuthering Waves",    # Withering 错拼
    "Weathering Waves": "Wuthering Waves",
    "Wuthering wave": "Wuthering Waves",
    "released shin the": "released in the",  # "shin"=s+in 粘连（存疑，待原片复核）
    # --- 纯断词：resonator 被切成 reson + ator ---
    "reson ator": "resonator",
    "reson ators": "resonators",
    "Reson ator": "Resonator",
    "Reson ators": "Resonators",
    # --- 明日方舟：voicing（音色/和声配置）被切成 vo + ic + ings ---
    # 2026-10-06 实测："I think the chords and vo ic ings of the instruments"
    "vo ic ings": "voicings",
    "vo ic ing": "voicing",
    "Vo ic ings": "Voicings",
    "Vo ic ing": "Voicing",
    # --- 2026-10-09 终末地 1.6「丹青渡」前瞻 reaction 片实测断词 ---
    "En field": "Endfield", "En Field": "Endfield",
    "Del phi": "Delphi",
    "Umb ro": "Umbro",
    "Min us": "Minus", "Radi ant": "Radiant",
    "Vind rian": "Vindrian", "Bl azing": "Blazing", "St ove": "Stove",
    "Inf lict ion": "Infliction",
    "Tal os": "Talos",
    "Sark az": "Sarkaz",
    "Sesh ka": "Seshka",
    "La Fant oma": "La Fantoma",
    "Gyp socea": "Gypsocea",
    "Had amis": "Hadamis",
    "Cre taceous": "Cretaceous",
    "N VIDIA": "NVIDIA",
    "Follow s": "Followers",
    "ep ilogue": "epilogue",
    "tyr ant": "tyrant",
    "ban anas": "bananas",
    "Command er": "Commander",
    "Cook ing": "Cooking",
    "Support er": "Supporter",
    "hyp ed": "hyped",
    "S word": "Sword",
    "neutral ized": "neutralized",
    "anom alous": "anomalous",
    "Cret aceous": "Cretaceous",
    "so cea": "socea",
    "G yp so cea": "Gypsocea", "G yp socea": "Gypsocea",
    "Land ship": "Landship",
    "RTS Spark": "RTX Spark",
    # --- 2026-10-09 终末地片第二轮：人工通读英文参考行补录 ---
    "Real imag iner": "Real imagineer",
    "G onna": "Gonna",
    "imp lore": "implore",
    "in the PBR": "in the banner",
    "Intel lect": "Intellect",
    "Effic acy": "Efficacy",
    "Sus ie": "Susie",
    "Echo es": "Echoes",
    "Ind igo": "Indigo",
    "a bite y": "a bitey",
    "finish er thing": "finisher thing",
    "exp iring": "expiring",
    "ok ami": "okay to me",
    "Se ems": "Seems",
    "what NCU is": "what AIC is",
    "Dn B": "DnB",
    "Fac ilities": "Facilities",
    "the the stream": "the stream",
    "s uff iciency": "sufficiency",
    "Talo ' s": "Talos '",
    "Sam my ' s": "Sami's",
    "Sam i field": "Sami field",
    "witch craft": "witchcraft",
    "for 1 0 0 years": "for 100 years",
    "ex panse": "expanse",
    "Art ificial": "Artificial",
    "unf org iving": "unforgiving",
    "Minoy an": "Minoan",
    "Sav on": "Sargon",
    "U ss is": "Who's this",
    "very kel": "very Kal'tsit",
    "that kel": "that Kal'tsit",
    "more kel": "more Kal'tsit",
    "M 3": "M3",
    "rog uel ike": "roguelike",
    "sh room": "shroom",
    "R ogue": "Rogue",
    "Hong shan": "Hongshan",
    "1 5 2 years": "152 years",
    "un bidden": "unbidden",
    "stre ngthen": "strengthen",
    "Origin ium": "Originium",
    "thr ives": "thrives",
    "livest ream": "livestream",
    "7 0 minutes": "70 minutes",
    "7 : 3 0, 8 : 4 0": "7:30, 8:40",
    "bigger up nights": "bigger update nights",
    "to the to the damage": "to the damage",
}


# ASR 断词可疑"尾巴"片段（右片段命中即视为被切断的单词后缀，供 scan-split 报警）
_ASR_SPLIT_SUFFIXES = frozenset((
    "ing", "ings", "ator", "ators", "tor", "tors", "ers", "er", "ed",
    "ly", "tion", "tions", "sion", "sions", "ance", "ence",
    "able", "ible", "ness", "ment", "ments", "ic", "ical", "ive", "ous",
))

# 常见独立英文词（任一片段本身即完整单词 -> 不报；同时**禁止**进已知词表，
#   防 "We re"->Were、"Sh ing"->Shing 这类把正常词边界误当断词重组）
_ASR_COMMON_WORDS = frozenset((
    "a", "an", "the", "and", "or", "of", "to", "in", "on", "at", "by", "for",
    "with", "from", "is", "are", "was", "were", "be", "been", "it", "its",
    "this", "that", "these", "those", "i", "you", "he", "she", "we", "they",
    "me", "my", "your", "his", "her", "our", "their", "not", "no", "so", "up",
    "out", "all", "one", "two", "new", "now", "day", "way", "man", "men",
    "get", "got", "let", "may", "can", "will", "just", "very", "more", "most",
    "also", "but", "have", "has", "had", "do", "does", "did", "go", "see",
    "say", "like", "love", "good", "bad", "big", "small", "here", "there",
    "what", "when", "how", "why", "who", "which", "than", "then", "them", "us",
    "him", "as", "if", "into", "water", "waves", "wave", "showcase", "time",
    "when", "were", "give", "know", "life", "come", "take", "make", "made",
    "work", "well", "only", "over", "such", "play", "game", "show", "open",
    "next", "last", "long", "high", "free", "full", "down", "back", "away",
    "much", "many", "need", "want", "feel", "look", "seem", "talk", "call",
    "said", "says", "went", "gone", "done", "left", "right", "music", "video",
    "sound", "world", "story", "react", "boss", "final", "level", "first",
    "second", "third", "fourth", "fifth", "chapter", "version", "update",
    "stream", "beautiful", "people", "song", "best", "ever", "thing", "things",
))

