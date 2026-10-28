# -*- coding: utf-8 -*-
# @version 2.8.0
"""术语/实体数据表

源：subtitle_calib_merged.py L10374-L10590 @ 97d7d463（2026-10-24 冻结快照）
"""
import io
import os
import re
import shutil
import sys
import unicodedata
from .entities_base import Entity
from .entities_part1 import ENTITIES_PART1
from .entities_part2 import ENTITIES_PART2
from .music import _FRACT_ANCHOR, _GINSHI_ANCHOR, _MUSIC_AK, _MUSIC_ENDO, _MUSIC_LIMBUS, _MUSIC_WW, _MUSIC_WW_BGM, _WW_ANCHOR

ENTITIES = list(ENTITIES_PART1) + list(ENTITIES_PART2)

for _songs, _modes, _label in (
        (_MUSIC_WW, ("bi", "react"), "鸣潮·先约电台"),
        (_MUSIC_AK, ("ak", "react"), "明日方舟·塞壬唱片"),
        (_MUSIC_ENDO, ("endo", "react"), "终末地·铁痕电台")):
    for _c, _en, _ja, _ko in _songs:
        ENTITIES.append(Entity(_c, modes=_modes, en=_en, ja=_ja, ko=_ko,
                               category=f"曲目/{_label}",
                               note="有歌词（人声）歌曲。空字段=该语种无独立官方名，"
                                    "按'单语保留原语言'处理，勿臆造译名。"))


# 边狱巴士 OST：官方仅英/日/韩，曲名保留英文；无 variants，只作多语元数据。
for _c, _en, _ja, _ko in _MUSIC_LIMBUS:
    ENTITIES.append(Entity(_c, modes=("limbus", "react"), en=_en, ja=_ja, ko=_ko,
                           category="曲目/边狱巴士",
                           note="官方仅英/日/韩；曲名保留英文，勿臆造中文译名。"))


# 纯音乐 BGM 单独注册（上表 note 明确写「人声」，混入会失真）
for _c, _en, _ja, _ko in _MUSIC_WW_BGM:
    ENTITIES.append(Entity(_c, modes=("bi", "react"), en=_en, ja=_ja, ko=_ko,
                           category="曲目/鸣潮·黎那汐塔 OST",
                           note="纯音乐 BGM（无人声）。官方中文名经黎那汐塔篇 OST Vol.1"
                                "《幻昼狂想》曲目表核实；日/韩无独立官方名，留空勿臆造。"))


for _c, _en, _v, _ctx, _cat, _note in (
    ("鸣潮", "Wuthering Waves", (),
     tuple((_WW_ANCHOR, w) for w in (
         "抵御波浪", "风浪风浪", "风浪风暴", "风浪之风", "风浪风霜", "风浪风云",
         "风化之浪", "风化之夜", "风化之道", "风化之路", "天气之子", "天气游戏",
         "天气现象", "凋零")),
     "作品/游戏",
     "谷翻把 Weathering Waves 译成 20+ 形态（抵御波浪 / 风浪风浪 / 天气之子 …），"
     "全部靠参考行锚定。收的都是多字成词形，不收裸 波浪/浪花/风化/风浪/天气。"),
    ("漂泊者", "Rover", (),
     ((r"\brover", "月球车"), (r"\brover", "流浪车"),
      (r"\brover", "罗伯特"), (r"\brover", "罗伯")),
     "角色/鸣潮",
     "本片谷翻又把 Rover 译成 月球车 / 流浪车 / 罗伯特 / 罗伯（原表只收 探测车）。"
     "「罗伯特」是常见人名、「罗伯」过短，一律靠 rover 参考行锚定；"
     "罗伯特 必须排在 罗伯 之前，否则会被截成「漂泊特」。"),
    ("残星会", "Fractsidus", (),
     tuple((_FRACT_ANCHOR, w) for w in
           ("弗拉克图斯", "裂形体", "裂隙", "断裂")),
     "势力/组织·鸣潮",
     "本片谷翻把 Fractus 又译成 裂隙 / 断裂 / 裂形体 / 弗拉克图斯。"
     "「裂隙 / 断裂」是常用词，一律靠参考行锚定，长键在前。"),
    ("伤痕", "Scar", (),
     ((r"\bScar\b", "伤疤"), (r"\bScar\b", "斯卡"), (r"\bScar\b", "刀疤")),
     "角色/鸣潮/残星会",
     "⚠ Scar 官方中文名 = 伤痕（百度百科「残星会」：核心成员会监伤痕、弗洛洛、"
     "克里斯托弗）。原表只收「疤痕」；本片又出现 伤疤 / 斯卡 / 刀疤。"
     "**绝不收裸「疤」**：#3117「你觉得伤痕身上有疤吗」里第二个「疤」是字面义。"),
    ("心月狐", "Hsin the Moon Fox", (), ((r"\bHin\b", "欣"),),
     "角色/岁主·鸣潮",
     "本片 ASR 把 Hsin 截成 Hin，谷翻作「欣」（#988/#1867/#2630/#2632/#2839）。"
     "「欣」是常用字，仅 \\bHin\\b 参考行锚定才改。"),
    ("木禺", "Muyu", (), ((r"Muyu|Amuyu", "阿梦优"),),
     "角色/鸣潮",
     "本片谷翻把 Amuyu 译成「阿梦优」（#3440），与既有 8 形同类，靠参考行锚定。"),
    ("爱弥斯", "Aemeath", (), ((r"\bAmethy\b|Aemeath", "紫水晶"),),
     "角色/鸣潮",
     "本片 ASR 把 Aemeath 截成 Amethy，谷翻按字面译成「紫水晶」（#1999 "
     "Where's my Amethy?）。常用词，靠参考行锚定。"),
    ("今汐", "Jinhsi", (),
     tuple((_GINSHI_ANCHOR, w) for w in ("银司", "银石", "银士", "银时")),
     "角色/鸣潮/今州",
     "本片 ASR 把 Jinhsi/Ginshi 译成 银司 / 银石 / 银士 / 银时（#5609/#5610/"
     "#5615/#5617/#5630/#5635）。「银时」是《银魂》人名，必须参考行锚定。"),
    ("尤诺", "Iuno", ("露诺",), (), "角色/鸣潮",
     "本片谷翻音译「露诺」（#1152/#1726/#1839），生僻组合，无条件变体安全。"),
    ("卡提希娅", "Cartethyia", ("卡尔蒂娅",), (), "角色/鸣潮",
     "本片又出「卡尔蒂娅」（#2529），与既有 卡尔蒂亚/卡蒂亚/卡蒂娅 同类。"),
    ("千咲", "Chisa", ("奇泽",), (), "角色/鸣潮",
     "本片 ASR 把 Chisa 译成「奇泽」（#6738 My personal bias puts Chiser "
     "above her），生僻组合，无条件变体安全。"),
    ("赞妮", "Zani", ("扎尼",), (), "角色/鸣潮",
     "本片谷翻音译「扎尼」（#5765 unlike Phoebe and Zany），生僻组合。"),
    ("守岸人", "The Shorekeeper", ("肖基普", "肖里珀"), (), "角色/鸣潮",
     "本片 Shawkeeper 又被音译成「肖基普」（#5754），与既有「肖基珀」同类。"),
    ("嘉贝莉娜", "Galbrena", ("加尔布里纳", "加尔比娜", "格布林"), (), "角色/鸣潮",
     "本片 Galbrena 又出 加尔布里纳 / 加尔比娜 / 格布林（#1123/#1503/#4197），"
     "与既有 加尔布丽娜 / 吉尔布丽娜 同类，均为生僻长键。"),
    ("七丘", "Septimont", ("塞普提蒙", "塞普顿"), (), "地名/鸣潮",
     "本片谷翻音译 塞普提蒙 / 塞普顿（#394/#397/#1398/#1630），"
     "与既有 塞普蒂蒙 / 塞普蒂蒙特 同类。官方：库洛 2.4「全新区域：七丘」。"),
    ("拉海洛", "Lahai-Roi", ("拉哈罗伊",), (), "地名/鸣潮",
     "本片谷翻音译「拉哈罗伊」（#574/#648/#2884/#2890），生僻长键安全。"),
    ("黎那汐塔", "Rinascita", ("雷奈亚",), (), "地名/鸣潮",
     "本片 ASR 把 Rinascita 念成 Renaia，谷翻「雷奈亚」（#3596），生僻组合。"),
    ("库洛", "Kuro Games", ("Curro Games", "Kurame"), (), "公司/鸣潮",
     "本片 ASR 又出 Curro Games / Kurame（#5270/#1931/#653），长键安全。"
     "「Ko」两字母过短，不收录。"),
    ("腾讯", "Tencent", ("Tensent", "Tenset"), (), "公司",
     "本片 ASR 把 Tencent 念成 Tensent / Tenset（#47/#4927），长键安全。"),
    ("战双帕弥什", "Punishing Gray Raven", ("Weathering Grave Raven",), (),
     "作品/游戏",
     "本片 #41 谷翻把 PGR 混成「Weathering Grave Raven」。⚠ 不设 Raven 的 ctx："
     "#55「惩罚灰Raven」里「惩罚灰」也会被替换，两次叠加成「惩罚灰战双帕弥什」垃圾串；"
     "该条交人工/侧车。"),
    ("边狱公司", "Limbus Company",
     ("边狱巴士", "林布斯公司", "林布连", "林布斯", "林布", "Lim Bus"), (), "作品/游戏",
     "本作无官方中文；游戏常用名《边狱巴士》，游戏内组织名《边狱公司》。"
     "本片谷翻译成「林布斯公司 / 林布连」（#452/#3848）。"
     "「边狱巴士」保留为变体；本条 canonical 用于既有 bi/ak 模式，"
     "新 --limbus 模式以边狱巴士为准（见 data/limbus.py）。"),
    ("终末地", "Arknights: Endfield", ("Enfield",), (), "作品/游戏",
     "本片把《明日方舟：终末地》说成 Enfield（#452），生僻长键安全。"),
    ("声骸", "Echo", (), ((r"\bechoes?\b", "回响"),), "术语/鸣潮",
     "本片谷翻把 echoes 直译「回响」（#3596），原表只收「回声」。"),
    ("残象", "Tacet Discord", (),
     ((r"[Dd]iscord monsters?", "Discord怪物"),), "术语/鸣潮",
     "本片谷翻把 Tacet Discord 直译「Discord怪物」（#3601/#3606），靠参考行锚定。"),
    ("利维亚坦", "Leviathan", (), ((r"Leviathan", "利维坦"),), "角色/鸣潮",
     "本片谷翻按通用译名作「利维坦」（#3000/#3004），鸣潮官方名为利维亚坦。"),
    ("英白拉多", "Imperator", (), ((r"Empera|Imperator", "帝国"),), "角色/鸣潮",
     "本片 #1392/#1813 谷翻把 Imperator/Emphera 译成「帝国 / Empirata」，"
     "「帝国」是常用词，靠参考行锚定。"),
    ("吟霖", "Yinlin", (), ((r"\bYin\b", "尹氏"),), "角色/鸣潮",
     "本片 #5610 谷翻把 Yin 译成「尹氏」（the jiggle. Yin's），靠参考行锚定。"),
    ("异环", "Neverness to Everness", ("NTE", "Neverness to Everness"), (), "作品/游戏",
     "NTE = Neverness to Everness = 官方中文《异环》（Hotta Studio/完美世界）。"
     "2026-10-26 官方站/维基复核：NTE《异环》与 Ananta《无限大》是两款不同作品；"
     "旧条目（2026-10-21）把两者写反，已纠正。"),
    ("无限大", "Ananta", ("Ananta",), (), "作品/游戏",
     "Ananta = 官方中文《无限大》（网易 Naked Rain，官网 ananta.163.com）。"
     "与 NTE《异环》严格区分；2026-10-26 复核纠正。"),
    ("边缘行者", "Edgerunners", ("Edge Runners", "Edgeunners", "Edge 跑者",
                                 "边缘跑者"), (), "作品/动画",
     "本片 #2725/#6024/#6035/#6039 提到《赛博朋克：边缘行者》，"
     "谷翻作 Edge 跑者 / 边缘跑者 / Edgeunners，统一为官方译名。"),
    ("使命召唤", "Call of Duty", ("COD",), (), "作品/游戏",
     "本片 #2174「傻乎乎的COD后果」，COD 即 Call of Duty 官方中文名。"),
    ("少女前线", "Girls' Frontline", ("女孩前线",), (), "作品/游戏",
     "本片 #3842/#3843 谷翻把 Girls' Frontline 直译「女孩前线」。"),
    # ---- 2026-10-21 Fobm4ster 年度抽卡评选片（1782 cue，谷翻）二校沉淀 ----
    # 依据：官方账号/百科/台服公告（2026-10-21 检索）。均为生僻长键或英文专名，裸键安全。
    ("挪德卡莱", "Nod-Krai", ("诺德哭吧", "点头哭泣", "诺德卡莱", "Nod Cry", "Nod Krai"),
     (), "地点/原神",
     "原神 6.x 地区 Nod-Krai 官方中文「挪德卡莱」；本片谷翻把 Nod Cry 直译成"
     "「诺德哭吧/点头哭泣」，#608-#624 已逐条订正。"),
    ("无期迷途", "Path to Nowhere", ("通往无处之路", "Path to Nowhere"), (), "作品/游戏",
     "本片 #1498 谷翻把 Path to Nowhere 直译「通往无处之路」，官方中文「无期迷途」。"),
    ("燕云十六声", "Where Winds Meet", ("Where's Me", "Where Winds Meet"), (), "作品/游戏",
     "本片 #543 的 Where's Me 是 Where Winds Meet 的 ASR 误听，官方中文「燕云十六声」。"),
    ("嘟嘟脸恶作剧", "Trickcal: Revive", ("Trickal", "Trickcal", "Trickcal Revive"),
     (), "作品/游戏",
     "本片 #383-#386 的 Trickal 即 Epid Games《Trickcal: Revive》，台服官方中文「嘟嘟脸恶作剧」。"),
    ("地平线行者", "Horizon Walker", ("Horizon Walker",), (), "作品/游戏",
     "本片 #1621 的 Horizon Walker 官方中文「地平线行者」（韩系回合制 SRPG）。"),
    ("云图计划X", "Neural Cloud X", ("Neural Cloud X",), (), "作品/游戏",
     "本片 #1758-#1776 的 Neural Cloud X 属《少女前线：云图计划》系列；"
     "X 为官方副标未另译，中文行统一「云图计划X」。"),
    ("雨雾之都", "Varsapura", ("Varsapura", "Varso Pro"), (), "作品/游戏",
     "米哈游 UE5 新作 Varsapura，2026-06 官方中文名「雨雾之都」；本片 #1685/#1695 已订正。"),
    ("魔御：STAR DIVE", "Mongil: Star Dive",
     ("Stardive", "Star Dive", "Mongil", "MONGIL"), (), "作品/游戏",
     "网石 Netmarble《魔御：STAR DIVE》（MONGIL: STAR DIVE）；本片 2026 年度评选讨论的"
     "「Stardive」即此作，官方中文见百科/台服公告。"),
    ("地狱有什么不好", "What in Hell is Bad?",
     ("What in Hell is Bad?", "What in Hell is Bad"), (), "作品/游戏",
     "Prettybusy 乙女塔防《What in Hell is Bad?》，中文名「地狱有什么不好」；#1463 已订正。"),
    ("鸣式", "Threnodian", ("瑟诺迪人", "Thurnodians", "Thurnodian"), (), "术语/鸣潮",
     "鸣潮世界威胁 Threnodian 官方中文「鸣式」；本片 #982 谷翻音译「瑟诺迪人」，已订正。"),
    ("爱弥斯", "Aemeath", ("伊米斯", "Imyth"), (), "角色/鸣潮",
     "鸣潮 3.1 五星共鸣者 爱弥斯（2026-02-06 实装）；本片谷翻音译「伊米斯」/英文残留"
     " Imyth（ASR 也作 I'm it），已逐条订正。"),
    ("鸣潮", "Wuthering Waves", ("呼啸波浪", "呼啸波涛"), (), "作品/游戏",
     "级联修复：裸键「呼啸波->鸣潮」会把「呼啸波浪」咬成「鸣潮浪」（本片基线 9 处）；"
     "4 字长键先行即可整体归「鸣潮」。"),
    # --- 2026-10-22《Gacha Games Have A Villain Problem》二校（官方中文，检索确认）---
    ("雷横", "Lei Heng", ("Lee Heng", "李恒"), (), "角色/边狱公司",
     "《边狱公司》第八章「不思观望」角色，拇指指挥官/东部十刃；官方中文雷横。"
     "本片 #1085/#1091 谷翻作「李恒/李」，英文参考行 ASR 作 Lee Heng/Lee。"),
    ("亚哈", "Ahab", (), (), "角色/边狱公司",
     "《边狱公司》第五章「定义为恶」BOSS，官方中文亚哈；本片 #16/#352/#1221。"),
    ("里卡多", "Ricardo", (), (), "角色/边狱公司",
     "《边狱公司》拇指「大兄弟」，官方中文里卡多；本片 #848 起。"),
    ("来古士", "Lygus", (), ((r"\bLogos\b", "Logos"),), "角色/崩坏：星穹铁道",
     "翁法罗斯管理员/天才俱乐部第一席分身，官方中文来古士；"
     "本片 ASR 作 Logos（#974/#978/#992），靠参考行锚定。"),
    ("翁法罗斯", "Amphoreus", ("Am Farious", "Amforius"), (), "地名/崩坏：星穹铁道",
     "《崩坏：星穹铁道》3.x 主舞台，官方中文翁法罗斯；本片 ASR 作 Am Farious/Amforius。"),
    ("博识尊", "Nous", (), ((r"\bNous\b", "诺斯"),), "角色/崩坏：星穹铁道",
     "智识星神，官方中文博识尊；本片 #957 谷翻作「诺斯」。"),
    ("冥火大公", "Duke Inferno", (), (), "角色/崩坏：星穹铁道",
     "永火官邸首领，官方中文冥火大公；本片 #950 谷翻「公爵的舞会地狱」。"),
    ("幻胧", "Phantylia", (), (), "角色/崩坏：星穹铁道",
     "绝灭大君·幻胧，官方中文幻胧；本片 ASR 作 Fontaine/Fontainlia（#650/#950），"
     "与《原神》枫丹同形，故不设裸变体，走逐 cue。"),
    ("黄泉", "Acheron", (), (), "角色/崩坏：星穹铁道",
     "官方中文黄泉；本片 #668 谷翻音译「阿刻隆」。"),
    ("路易·圭亚贝伦", "Louis Guiabern", ("Luis Guayabero",), (), "角色/暗喻幻想",
     "《暗喻幻想：ReFantazio》反派，官方中文路易·圭亚贝伦（17173/中文维基）；"
     "本片 ASR 作 Luis Guayabero（#533）。"),
    ("金属脸", "Metal Face", (), (), "角色/异度神剑",
     "《异度神剑》机神兵，官方中文金属脸；本片 #441/#487/#491。"),
    ("修尔克", "Shulk", (), (), "角色/异度神剑", "《异度神剑》主角，官方中文修尔克。"),
    ("丹邦", "Dunban", (), (), "角色/异度神剑", "《异度神剑》角色，官方中文丹邦。"),
    ("菲奥伦", "Fiora", (), (), "角色/异度神剑", "《异度神剑》角色，官方中文菲奥伦。"),
    ("莱恩", "Reyn", (), (), "角色/异度神剑", "《异度神剑》角色，官方中文莱恩。"),
    ("莫纳德", "Monado", (), (), "武器/异度神剑", "《异度神剑》神剑，官方中文莫纳德。"),
    ("机神兵", "Mechon", (), (), "种族/异度神剑", "《异度神剑》敌方种族，官方中文机神兵。"),
):
    ENTITIES.append(Entity(_c, modes=("bi",), en=_en, variants=_v, ctx=_ctx,
                           category=_cat, note=_note))


# 边狱巴士：章节/BOSS/角色仅作元数据（本片未点名，不参与替换）
ENTITIES.append(Entity("第十章「凝视之下」", modes=("limbus",),
                       en="Canto X: The Gaze Bearing",
                       category="章节/边狱巴士",
                       note="本作无官方中文；零协/社区译名「凝视之下」；本片仅称 Canto 10。"))
ENTITIES.append(Entity("默尔索", modes=("limbus",),
                       en="Meursault",
                       category="角色/边狱巴士",
                       note="Canto X 主线聚焦罪人；本片未点名，仅登记。"))
ENTITIES.append(Entity("赤红之神", modes=("limbus",),
                       en="The Crimson God",
                       category="BOSS/边狱巴士",
                       note="Canto X Part 3；[Adulthood] 社区有「成熟/完熟」两派写法；"
                            "本片未点名，仅登记。"))

