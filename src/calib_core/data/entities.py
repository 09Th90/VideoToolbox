# -*- coding: utf-8 -*-
# @version 2.9.0
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
from .music import (_FRACT_ANCHOR, _GINSHI_ANCHOR, _MUSIC_AK, _MUSIC_ENDO,
                    _MUSIC_ENDO_BOSS, _MUSIC_LIMBUS, _MUSIC_WW, _MUSIC_WW_BGM,
                    _MUSIC_WW_BGM_XF, _WW_ANCHOR)

ENTITIES = list(ENTITIES_PART1) + list(ENTITIES_PART2)

for _songs, _modes, _label in (
        (_MUSIC_WW, ("bi", "react"), "鸣潮·先约电台"),
        (_MUSIC_AK, ("ak", "react"), "明日方舟·塞壬唱片"),
        (_MUSIC_ENDO, ("endo", "endobi", "react"), "终末地·铁痕电台")):
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


# 终末地 1.4「向渊行」OST · 阿莱克琉斯战曲 5 段（2026-11-03）：无官方简中 ⇒ 曲名保留拉丁原文，
# 无 variants，只作跨语元数据（同 _MUSIC_LIMBUS 先例）。
for _c, _en, _ja, _ko in _MUSIC_ENDO_BOSS:
    ENTITIES.append(Entity(_c, modes=("endo", "endobi", "react"), en=_en, ja=_ja, ko=_ko,
                           category="曲目/终末地·向渊行OST",
                           note="终末地 1.4「向渊行」最终 BOSS 阿莱克琉斯（千夫长）战曲的官方分段曲名；"
                                "**无官方简体中文**，保留拉丁原文，勿臆造译名。"
                                "官方 credit＝铁痕电台-MSR & Crywolf & YMIR；"
                                "分段顺序＝序章／一阶段／阶段转换／二阶段／尾声。"))


# 同一 OST credit 的两位音乐人（2026-11-03）：无官方简中，只登记跨语知识，不建替换键。
ENTITIES.append(Entity("Crywolf", modes=("react", "endobi", "ak"), en="Crywolf",
                       category="音乐人/终末地·铁痕电台",
                       note="终末地「向渊行」OST 阿莱克琉斯战曲署名人之一（铁痕电台-MSR & Crywolf & "
                            "YMIR），另为《明日方舟》作有 Somniomancer [null set]（众生行记 OST 曲7）。"
                            "无官方简体中文名 ⇒ 保留拉丁原名不译。中文错形 冷狼/哭狼/克雷沃尔夫/"
                            "梦巫师克雷沃尔夫 已由 REACT_TERMS 裸键覆盖，本条**不重复建键**。"
                            "2026-11-08：ak 模式补 '狼来了' 参考行锚定（AK_CONTEXT，Cry wolf 命中才替换）。"))
ENTITIES.append(Entity("YMIR", modes=("react", "endobi"), en="YMIR",
                       category="音乐人/终末地·铁痕电台",
                       note="终末地「向渊行」OST 阿莱克琉斯战曲署名人之一。此前全库只在 misc.py 注释里"
                            "出现、无任何条目（grep 实测 0 命中），本次补齐为可检索实体。"
                            "无官方简体中文名 ⇒ 保留拉丁原名。**不建替换键**：其 ASR 形「希米尔/埃米尔」"
                            "属通用中文词组合，按 2026-09-14 戒律只能逐 cue 侧车，入表必误伤。"))


# 纯音乐 BGM 单独注册（上表 note 明确写「人声」，混入会失真）
for _c, _en, _ja, _ko in _MUSIC_WW_BGM:
    ENTITIES.append(Entity(_c, modes=("bi", "react"), en=_en, ja=_ja, ko=_ko,
                           category="曲目/鸣潮·黎那汐塔 OST",
                           note="纯音乐 BGM（无人声）。官方中文名经黎那汐塔篇 OST Vol.1"
                                "《幻昼狂想》/ Vol.7《无名长诗》曲目表核实（Apple Music 国区"
                                " 1824610259）；日/韩无独立官方名，留空勿臆造。"))


# 2026-11-04：**玄方篇**（3.5-3.7）OST 器乐单独注册。
#   与上面 `_MUSIC_WW_BGM` 分开的原因：那张表的 category/note 出处写死为黎那汐塔 Vol.1
#   《幻昼狂想》，混入即挂错出处。出处依据 Apple Music 美服/国区同条目交叉。
for _c, _en, _ja, _ko in _MUSIC_WW_BGM_XF:
    ENTITIES.append(Entity(_c, modes=("bi", "react"), en=_en, ja=_ja, ko=_ko,
                           category="曲目/鸣潮·玄方篇 OST",
                           note="纯音乐（无人声）。官方中文名经玄方篇 OST Vol.1《万声弥新》/"
                                "Vol.2《云影仙迹》/Vol.3《朝月听尘》曲目表核实（Apple Music 国区"
                                " 6789678123 / 6803333112 / 6817719530）；日/韩无独立官方名，"
                                "留空勿臆造。ASR 常形：Into Xuanfang→'Into the wild fire'、"
                                "The Dreaming Vale→'Dreaming Veil'。"
                                "**⚠《契阔》是 3.7 锁暝角色 PV 标题（TapTap CV 表），不是曲名。**"))


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
    # 2026-11-07 修单数漏校：原 ctx 正则 \bechoes?\b 只匹配 "echoe/echoes"，
    #   **不匹配单数 "echo"**（实测 re.search(r'\bechoes?\b','Echo skill DPS.') == False），
    #   故本片 cue432「回响技能DPS」/ cue481「老回声回声的改造」两处单数 Echo 全漏校。
    #   改为 \becho(?:es)?\b 覆盖单复数；wrong 侧补「回声」以覆盖 ASR 叠词行。
    #   ⚠ 只动 ctx、不动 variants ⇒ 避开 state.py 的投影冲突 SystemExit；
    #   bilingual.py 侧的双 lookahead 锚（要求养成语境词）**保持不动**，
    #   ⇒ 历史片源命中面不变，仅新增单数 Echo 命中（须走历史片源逐字节回归）。
    ("声骸", "Echo", (), ((r"\becho(?:es)?\b", "回响"), (r"\becho(?:es)?\b", "回声")), "术语/鸣潮",
     "本片谷翻把 echoes 直译「回响」（#3596），原表只收「回声」。"
     "2026-11-07 补单数：\bechoes?\b 不匹配单数 echo，故 #432/#481 漏校，"
     "改为 \becho(?:es)?\b 覆盖单复数；wrong 侧新增「回声」以覆盖 ASR 叠词行。"),
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


ENTITIES.append(Entity("超验", modes=("bi", "react"),
                       en="TRANSCENDO",
                       category="版本/鸣潮3.8",
                       note="3.8 世界观 PV 官方中文名「超验 TRANSCENDO」；"
                            "副标题「闭环重启，潮声再循」；谷翻常作「超越」。"))

# ===== 影之刃零（Phantom Blade Zero，--pbz，2026-10-30） =====
# 官方依据：灵游坊 pbz.s-game.com / 官方公开角色（魂/左殇/魔渊/虚空/圣母娘娘）/
# 甄子丹饰魔渊（2026-08 官方 State of Play）；醉剑为官方武器名。
ENTITIES.append(Entity("《影之刃零》", modes=("pbz",), en="Phantom Blade Zero",
                       category="作品/影之刃零",
                       variants=("幽灵传说", "刀锋零号", "幻影之刃"),
                       ctx=((r"\bPhantom\s+Blade\b", "幽灵传说"),),
                       note="灵游坊官方中文《影之刃零》；谷翻把 Phantom Blade Zero "
                            "逐词直译成「幽灵传说」「刀锋零号」。"))
ENTITIES.append(Entity("魂", modes=("pbz",), en="Soul",
                       category="角色/影之刃零",
                       ctx=((r"\bSoul\b", "索尔"),),
                       note="主角魂（Soul）；谷翻按人名音译成「索尔」。"))
ENTITIES.append(Entity("左殇", modes=("pbz",), en="Zol Shang",
                       category="角色/影之刃零",
                       variants=("佐尔尚",),
                       note="官方公开角色左殇；谷翻音译「佐尔尚」。"))
ENTITIES.append(Entity("地狱行者", modes=("pbz",), en="Hell Walker",
                       category="难度/影之刃零",
                       note="Hellwalker 困难模式；本片标题 [Hellwalker] 所指。"))
ENTITIES.append(Entity("杀气", modes=("pbz",), en="shachi / Sha Qi",
                       category="资源/影之刃零",
                       variants=("沙奇",),
                       ctx=((r"\bsha?chi\b", "沙池"),),
                       note="核心资源杀气（shachi）；谷翻音译「沙奇/沙池」。"))
ENTITIES.append(Entity("架势", modes=("pbz",), en="posture / stagger",
                       category="系统/影之刃零",
                       ctx=((r"\bposture\b", "姿势"), (r"\bstagger\b", "硬直")),
                       note="posture/stagger 统一译作「架势」；「姿势/硬直」为通用词，只走参考行锚定。"))
ENTITIES.append(Entity("血肉雕刻师", modes=("pbz",), en="Flesh Sculptor",
                       category="敌人/影之刃零",
                       variants=("肉体雕刻师",),
                       note="Flesh Sculptor；谷翻把 flesh 译成「肉体」。"))
ENTITIES.append(Entity("血肉莉莉", modes=("pbz",), en="Flesh Lily",
                       category="敌人/影之刃零",
                       variants=("肉体莉莉", "肉身莉莉"),
                       note="Flesh Lily；花名场景亦作「血肉百合」。"))
ENTITIES.append(Entity("魔渊", modes=("pbz",), en="Demon Abyss",
                       category="角色/影之刃零",
                       variants=("恶魔深渊", "魔之深渊"),
                       note="甄子丹饰演的隐藏 BOSS、主角魂生父、暗魔天堡末代堡主。"))
ENTITIES.append(Entity("甄子丹", modes=("pbz",), en="Donnie Yen",
                       category="演员/影之刃零",
                       variants=("甄敦",),
                       ctx=((r"\bDonn", "唐尼"),),
                       note="Donnie Yen 饰魔渊；谷翻作「甄敦/唐尼」。"))
ENTITIES.append(Entity("彼岸花", modes=("pbz",), en="spider lily",
                       category="植物/影之刃零",
                       variants=("蜘蛛百合",),
                       note="spider lily=彼岸花；谷翻直译「蜘蛛百合」。"))
ENTITIES.append(Entity("天命", modes=("pbz",), en="the Mandate",
                       category="势力/影之刃零",
                       ctx=((r"\bmandate\b", "授权"),),
                       note="设定势力 the mandate=天命；谷翻作「授权」。"))
ENTITIES.append(Entity("组织", modes=("pbz",), en="the Order",
                       category="势力/影之刃零",
                       ctx=((r"\bthe\s+order\b", "教团"),),
                       note="主角所属 the Order=组织；谷翻作「教团」。"))
ENTITIES.append(Entity("香囊", modes=("pbz",), en="sachet",
                       category="道具/影之刃零",
                       ctx=((r"\bsachet?\b", "香槟"),),
                       note="sachet=香囊；谷翻误作「香槟」。"))
ENTITIES.append(Entity("回声", modes=("pbz",), en="echoes of the past",
                       category="系统/影之刃零",
                       ctx=((r"\bechoes?\s+of\s+the\s+past\b", "声骸"),),
                       note="echoes of the past=过去的回声；鸣潮词表曾把「回声」误改成「声骸」。"))
ENTITIES.append(Entity("影守卫", modes=("pbz",), en="Shadow Warden",
                       category="NPC/影之刃零",
                       ctx=((r"\bwarden\b", "典狱长"),),
                       note="Shadow Warden=影守卫；谷翻作「典狱长」。"))
# =============================================================
# 2026-10-31 明日方舟 × 韵律源点（Arcaea）联动 reaction（DREAM COLLAB!）
#   官方依据：Arcaea 中文名「韵律源点」（2026-02-13 官方公告）；Kou=红、Titi=缇缇、
#   Liino=梨诺、Kal'tsit alter=凯尔希·思衡托、Specter alter=归溟幽灵鲨；
#   CC 曲目 Operation Basepoint=起源行动、Operation Blade=利刃行动、Operation Pyrite=黄铁行动、
#   Operation Dawnseeker=寻昼行动；All hail Savior!、ManiFesto:、冲破穹顶（理想城OST）。
#   普通词/短名只走 ctx；带括号曲名不做英文裸键。危机合约已有 endobi 实体，ak 侧只留 AK_TERMS 键。
# =============================================================
ENTITIES.append(Entity("韵律源点", modes=("ak",), en="Arcaea", ja="アーケア", ko="아르케아",
                       category="作品/音游",
                       variants=("Arcaea", "Arcea", "阿尔凯亚", "阿尔西亚"),
                       ctx=((r"\bArcaea\b", "阿卡亚"),),
                       note="Arcaea 官方中文名「韵律源点」（2026-02-13 官方公告）；阿卡亚/阿尔凯亚/阿尔西亚 为谷翻/ASR 变体。"))
ENTITIES.append(Entity("终末地", modes=("ak",), en="Endfield",
                       category="作品/明日方舟：终末地",
                       variants=("Endfield", "恩德菲尔德"),
                       note="Endfield 官方中文《明日方舟：终末地》；Enfieldy/Endfieldy 为形容词，已在 AK_TERMS 单独映射「终末地风格」。"))
ENTITIES.append(Entity("红", modes=("ak",), en="Kou",
                       category="角色/韵律源点",
                       ctx=((r"\bCoal\b", "煤炭"), (r"\bCoal\b", "煤"), (r"\bKou\b", "寇")),
                       note="Arcaea 搭档 Kou 官方中文「红」；Coal 为 ASR 误听，只走 ctx；成片可显示「红（Kou）」以便与方舟干员红区分。"))
ENTITIES.append(Entity("缇缇", modes=("ak",), en="Titi",
                       category="干员/明日方舟",
                       variants=("Titi",),
                       ctx=((r"\bTT\b", "TT"),),
                       note="PRTS：缇缇 Titi，2026-01-09 实装；TT 为 ASR 缩写，只走 ctx。"))
ENTITIES.append(Entity("梨诺", modes=("ak",), en="Liino",
                       category="干员/终末地",
                       ctx=((r"\bLinus'?\b", "Linus"), (r"\bLinus'?\b", "利诺")),
                       note="终末地六星干员梨诺 Liino（2026-08-09 实装）；Linus 为 ASR 误听，只走 ctx；成片可显示「梨诺（Liino）」。"))
ENTITIES.append(Entity("凯尔希·思衡托", modes=("ak",), en="Kal'tsit alter",
                       category="干员/异格",
                       variants=("Kal'tsit alter", "Kal'tsit Alter", "Kaltsit alter"),
                       note="凯尔希异格官方名「凯尔希·思衡托」（官方公告/周边）。"))
ENTITIES.append(Entity("归溟幽灵鲨", modes=("ak",), en="Specter alter",
                       category="干员/异格",
                       variants=("Specter alter",),
                       ctx=((r"\bspecter alter\b", "幽灵鲨异格"),),
                       note="幽灵鲨异格官方名「归溟幽灵鲨」；幽灵鲨异格只走 ctx。"))
ENTITIES.append(Entity("佩佩", modes=("ak",), en="Pepe",
                       category="干员/明日方舟",
                       variants=("Pepe",),
                       ctx=((r"\bPepper'?s?\b", "Pepper"), (r"\bPepper'?s?\b", "佩珀")),
                       note="Pepe 官方中文「佩佩」；Pepper 为 ASR 误听，只走 ctx。"))
ENTITIES.append(Entity("嘉维尔", modes=("ak",), en="Gavial",
                       category="干员/明日方舟",
                       variants=("Gavial",),
                       note="Gavial 官方中文「嘉维尔」；alter 形由 AK_CONTEXT 的百炼嘉维尔规则处理。"))
ENTITIES.append(Entity("阿米娅", modes=("ak",), en="Amiya",
                       category="干员/明日方舟",
                       variants=("Amiya",),
                       note="Amiya 官方中文「阿米娅」。"))
ENTITIES.append(Entity("重启锚点", modes=("ak",), en="Relaunch Anchor",
                       category="玩法/生息演算",
                       variants=("Relaunch Anchor", "relaunch anchor"),
                       note="生息演算模式官方中文「重启锚点」。⚠ 2026-11-02 复核：EP17「相变临界」"
                            "官网公告（ak.hypergryph.com/news/3046）与 PRTS/BWIKI 本章系统名清单里"
                            "**查无「生息演算·重启锚点」这一本章项**，此前把它记作本章系统名属误，"
                            "待复核；本条只保留生息演算自身口径，不再关联 EP17。"))
ENTITIES.append(Entity("定向寻访卡池", modes=("ak",), en="Orienteering banner",
                       category="卡池",
                       variants=("Orienteering banner", "Orienteering Banner"),
                       note="Orienteering banner 官方卡池「定向寻访」。"))
ENTITIES.append(Entity("音弧", modes=("ak",), en="arcs",
                       category="术语/玩法",
                       ctx=((r"(?<!mobile )\bapps?\b", "应用程序"), (r"\barcs?\b", "弧线")),
                       note="Arcaea 蓝线官方中文「音弧」；应用程序/弧线只走 ctx；mobile apps 不在此列。"))
ENTITIES.append(Entity("海猫", modes=("ak",), en="Lowlight",
                       category="作者/鹰角网络",
                       ctx=((r"\bLow Light\b", "Low Light"), (r"\bLowlight\b", "Lowlight")),
                       note="鹰角网络联合创始人海猫（Lowlight）；英文形只走 ctx；显示可带（Lowlight）。"))
ENTITIES.append(Entity("Kukki", modes=("ak",), en="Kukki",
                       category="主播",
                       ctx=((r"how could you not name", "库奇"), (r"how could you not name", "Cookie")),
                       note="主播 kukkikaze 昵称 Kukki；Cookie/库奇 为 ASR/机翻形，只走 ctx。"))
ENTITIES.append(Entity("《Operation Dawnseeker》（寻昼行动）", modes=("ak",), en="Operation Dawnseeker",
                       category="曲目/危机合约",
                       variants=("Don't Seeker", "Dont Seeker"),
                       ctx=((r"\bDon'?t Seeker\b", "不要寻找者"), (r"\bDon'?t Seeker\b", "别寻找者")),
                       note="危机合约#8 寻昼行动主题曲，官方曲名 Operation Dawnseeker。"))
ENTITIES.append(Entity("《Operation Basepoint》（起源行动）", modes=("ak",), en="Operation Basepoint",
                       category="曲目/危机合约",
                       variants=("Base Point",),
                       ctx=((r"\bBase Point\b", "基点"), (r"\bBase Point\b", "基点行动")),
                       note="危机合约#12 起源行动主题曲，官方曲名 Operation Basepoint。"))
ENTITIES.append(Entity("《Operation Pyrite》（黄铁行动）", modes=("ak",), en="Operation Pyrite",
                       category="曲目/危机合约",
                       ctx=((r"\bPyrite\b", "黄铁矿"),),
                       note="危机合约#1 黄铁行动主题曲，官方曲名 Operation Pyrite；黄铁矿只走 ctx。"))
ENTITIES.append(Entity("《Operation Blade》（利刃行动）", modes=("ak",), en="Operation Blade",
                       category="曲目/危机合约",
                       ctx=((r"\bPlay,\s*Pyrite\b", "播放"), (r"\bPlay,\s*Pyrite\b", "Play")),
                       note="危机合约#2 利刃行动主题曲，官方曲名 Operation Blade；ASR 把 Blade 听成 Play，只走 ctx。"))
ENTITIES.append(Entity("《All hail Savior!》", modes=("ak",), en="All hail Savior!",
                       category="曲目/嘉维尔EP",
                       variants=("All Hail the Savior",),
                       ctx=((r"\bAll Hail the Savior\b", "万岁"), (r"\bAll Hail the Savior\b", "救主")),
                       note="百炼嘉维尔 EP，官方曲名 All hail Savior!（h 小写、带感叹号）。"))
ENTITIES.append(Entity("《ManiFesto:》", modes=("ak",), en="ManiFesto:",
                       category="曲目/音律联觉",
                       variants=("Manifesto",),
                       ctx=((r"\bManifesto\b", "宣言"),),
                       note="音律联觉 Hip-Hop 主题曲，官方曲名 ManiFesto:（含冒号）。"))
ENTITIES.append(Entity("Cry of Dawn", modes=("ak",), en="Cry of Dawn",
                       category="曲目/待考",
                       ctx=((r"\bCry of Dawn\b", "黎明之声"),),
                       note="本片低置信曲名，未检索到官方中文；保留英文，不臆造译名。"))
ENTITIES.append(Entity("《冲破穹顶》", modes=("ak",), en="Breakthrough the Dome",
                       category="曲目/理想城OST",
                       variants=("Breakthrough the Dome",),
                       ctx=((r"\bBreakthrough the Dome\b", "突破穹顶"),),
                       note="《理想城：长夏狂欢季OST》，官方中文曲名《冲破穹顶》。"))
ENTITIES.append(Entity("《Radiant》", modes=("ak",), en="Radiant",
                       category="曲目/临光EP",
                       ctx=((r"\bRadiant\b", "光辉灿烂"), (r"\bRadiant\b", "光辉")),
                       note="耀骑士临光 EP，官方曲名 Radiant；无官方中文，保留英文。"))
ENTITIES.append(Entity("《Granite Gate》", modes=("ak",), en="Granite Gate",
                       category="曲目/明日方舟",
                       ctx=((r"\bGranite Gate\b", "花岗岩之门"),),
                       note="无官方中文，保留英文。"))
ENTITIES.append(Entity("《System Malfunction》", modes=("ak",), en="System Malfunction",
                       category="曲目/明日方舟",
                       ctx=((r"\bSystem Malfunction\b", "系统故障"),),
                       note="无官方中文，保留英文。"))
ENTITIES.append(Entity("《Awaken》", modes=("ak",), en="Awaken",
                       category="曲目/幽灵鲨EP",
                       ctx=((r"\bAwaken\b", "觉醒"),),
                       note="归溟幽灵鲨 EP，官方曲名 Awaken；觉醒只走 ctx。"))
ENTITIES.append(Entity("《Mystic Light Quest》", modes=("ak",), en="Mystic Light Quest",
                       category="曲目/佩佩EP",
                       ctx=((r"\bMystic Light Quest\b", "神秘之光之旅"),),
                       note="佩佩 EP，官方曲名 Mystic Light Quest；无官方中文，保留英文。"))
ENTITIES.append(Entity("《理想城》", modes=("ak",), en="Ideal City",
                       category="活动/明日方舟",
                       variants=("Ideal City",),
                       note="官方活动「理想城：长夏狂欢季」；曲目语境用《理想城》。"))
ENTITIES.append(Entity("《崩坏3》", modes=("ak",), en="Honkai Impact 3rd",
                       category="作品",
                       variants=("Honkai Impacted",),
                       ctx=((r"\bHonkai Impact(?:ed)?\b", "《崩坏》"),),
                       note="官方中文《崩坏3》；Honkai Impacted 为 ASR 变体；与 ko 实体「崩坏3」区分。"))
ENTITIES.append(Entity("《命运2》", modes=("ak",), en="Destiny 2",
                       category="作品",
                       variants=("Destiny 2",),
                       ctx=((r"\bDestiny 2\b", "《命运 2》"),),
                       note="官方中文《命运2》。"))
ENTITIES.append(Entity("《星之海洋》", modes=("ak",), en="Star Ocean",
                       category="作品",
                       variants=("Star Ocean",),
                       note="官方中文《星之海洋》。"))

# ══ 2026-11-02 沉淀：《명조》 Day 1 팀장이 되었어요「띵킹 2」（7554 cue，韩语原声+机翻中文，--ko）══
#   根因（本轮最值钱的一条）：维里奈/散华/莫宁/千咲/椿/珂莱塔 这些官中名**只登记在 bi（或 ja）行**，
#   而 `_register_entities` 严格按 `e.modes` 投影（variants→_MODE_TERM_TABLE[m]、ctx→_MODE_CTX_TABLE[m]）
#   ⇒ `--ko` 通路一个字都不产出，于是韩语片整批漏校。同 2026-11-01「隧者/星炬学院只在 bi 登记故
#   --ja 不生效」漏校型。凡新增官中名，**按语种逐条检查 modes 是否覆盖到实际片源模式**。
#   官方依据（逐条可点验）：
#     维里奈 ＝ 벨리나（百度百科/萌娘百科「维里奈」外文名 韩：벨리나；韩 CV 강새봄）
#     散华   ＝ 산화（百度百科「散华」外文名；⚠ 산화 在韩语同时是「氧化」，谷翻必出错）
#     莫宁   ＝ 모니에（百度百科「莫宁」外文名 Mornye/モーニエ/모니에；韩 CV 오로아）
#     千咲   ＝ 치사（维基百科「鸣潮角色列表」千咲（Chisa，치사），本名朽叶千咲，星炬学院）
#     椿     ＝ 카멜리아（Wuthering Waves Fandom「Camellya」Other Languages 官方形 + 维基角色列表）
#     珂莱塔 ＝ 카를로타（Carlotta Montelli，萌娘百科「鸣潮/译名对照表」；⚠ 维基角色列表把
#                Carlotta 的韩文写成 카멜리아 是笔误，与 椿 同形，故 珂莱塔 只按 카를로타 记知识）
#     共鸣链 ＝ 官方系统名（百度百科「鸣潮」养成节：每位角色 6 层共鸣链节点，重复角色转化为
#                该角色共鸣链回音频段）
ENTITIES.append(Entity("维里奈", modes=("ko",), en="Verina", ko="벨리나",
                       category="角色/鸣潮",
                       variants=("贝琳娜",),
                       note="ko 侧补登（2026-11-02）：谷翻把 벨리나 直译成音译「贝琳娜」，本片 12 处"
                            "（#1541-1545/7114/7148/7158/7161）。'贝琳娜'是唯一音译串、不是通用词，"
                            "可作裸键；bi 侧既有 维丽娜/Verina 不动。"))
ENTITIES.append(Entity("散华", modes=("ko",), en="Sanhua", ko="산화",
                       category="角色/鸣潮",
                       ctx=((r"산화", "氧化"), (r"산화", "散花"),),
                       note="ko 侧补登（2026-11-02）：韩服官方名 산화 与韩语「氧化」同形，谷翻必出"
                            "「氧化」（本片 #1544「维里奈？还有散华」被翻成「怎么还氧化了」）。"
                            "戒律：'氧化'是正常词，**绝不裸键**，只走 산화 谚文锚定。"))
ENTITIES.append(Entity("莫宁", modes=("ko",), en="Mornye", ko="모니에",
                       category="角色/鸣潮3.0",
                       ctx=((r"모니에|모니", "莫尼"), (r"모니", "气槽"), (r"모니", "钱"),),
                       note="ko 侧补登（2026-11-02）：모니에(莫宁) ASR 缩成 모니/모닝，谷翻按字面出"
                            "「莫尼/气槽/钱」（本片 #198/199/652/6883/7221）。锚定串取 모니，"
                            "不含 머니(money)，故不会咬正常'钱'。'钱/气槽'皆为通用词，禁裸键。"))
ENTITIES.append(Entity("千咲", modes=("ko",), en="Chisa", ko="치사",
                       category="角色/星炬学院",
                       ctx=((r"치사", "智沙"), (r"치사", "千佐渡"), (r"치사", "奇萨"),),
                       note="ko 侧补登（2026-11-02）：치사(千咲) 与形容词 치사하다(卑鄙/寒酸) 同形，"
                            "错形侧只收音译串并按 치사 锚定（本片 #390/392/4904）。bi 侧已有 奇莎/奇萨"
                            "裸键与 Chisha(炽霞) 回滚锚，勿混——Chisha=炽霞，Chisa=千咲。"))
ENTITIES.append(Entity("椿", modes=("ko",), en="Camellya", ko="카멜리아",
                       category="角色/黑海岸",
                       ctx=((r"카멜레|카멜리아", "山茶花"), (r"카멜레|카멜리아", "茶花"),),
                       note="ko 侧补登（2026-11-02）：官方韩文形 카멜리아 被谷翻按花名直译成"
                            "「茶花/山茶花」（本片 #2116-2118/#3547/#3560）。'茶花'是通用词禁裸键；"
                            "ctx 里长形 山茶花 必须排在 茶花 之前（KO_CONTEXT 按列表顺序执行）。"
                            "2026-10-13 已有 카멜레언/카멜탈/카메/카밀타 系键，本条只补 카멜리아 "
                            "花名直译这一条产出路径。"))
ENTITIES.append(Entity("珂莱塔", modes=("ko",), en="Carlotta", ko="카를로타",
                       category="角色/黎那汐塔",
                       note="ko 侧知识登记（2026-11-02）：本片 #6946 谷翻整句吞掉角色名、#7153 残留"
                            "拉丁 'Carlta'，属句级漏译/ASR 断词，**不建替换键**（'卡露塔'等音译形未"
                            "在本片实测，凭猜测入表违反沉淀纪律）。官方韩文形=카를로타。"))
ENTITIES.append(Entity("共鸣链", modes=("ko",), en="Resonance Chain", ko="돌파",
                       category="术语/鸣潮养成",
                       ctx=((r"체인", "机制"), (r"영체인", "灵体"), (r"영체인", "五链"),
                            (r"6체인", "六人链条"),),
                       note="官方系统名（百度百科「鸣潮」养成节：每位角色 6 层共鸣链节点）。"
                            "韩服口播有两种写法：돌파（汉字词'突破'）与 체인（chain 音译），"
                            "主播常混用，故 체인->共鸣链 走锚定（'机制'是通用词，绝不裸键）。"
                            "⚠ **禁止** '突破->共鸣链' 裸键或锚定：韩服 돌파 同时是「等级突破/闯关」，"
                            "两义同形，任何锚定都会咬掉等级突破语境。本片 16 处（#169/172/175/177/181/"
                            "1459/1561/2656/2657/2760/2831/2856/6066/7520）按上下文逐 cue 判，"
                            "链义判据=同句出现 여섯 개/重复角色/N돌/N체인 这类链数词；"
                            "闯关·等级突破语境一律保留。영체인=**零链**（영=0），"
                            "本片曾被谷翻成'灵体/五链'（#2321/#3623）。"))

# =============================================================
# 2026-11-02 EP17「相变临界」预告片反应片二校沉淀（The Special K Experience，394 cue，
#   英文 ASR 在上 + 谷翻中文在下，链 bi→ak）。依据：官网公告 ak.hypergryph.com/news/3046、
#   PRTS「相变临界」词条正文、游戏内「共享终端」线索原文。
#   ⚠ 「扩 ak」一律用**同 canonical 的第二条 Entity（modes=("ak",)）**实现，不改原 bi 条目
#     的 modes：_register_entities 逐 modes 投影（state.py:191），整条搬过去会把 bi 侧
#     variants 里的高危常用词（如 凯尔特）一并灌进 AK_TERMS——而 ak 分支 2026-11-02 之前
#     根本没有 EXCLUDE 回滚层，误伤无从撤销。
ENTITIES.append(Entity("Mon3tr", modes=("ak",), en="Mon3tr",
                       category="召唤物/凯尔希",
                       ctx=((r"\bcalluse?s?\b", "愈伤组织"),),
                       note="凯尔希的召唤物，官方书写 **Mon3tr**（首字母大写、3 代 i）：游戏内线索原文"
                            "`◀ Mon3tr的线索`「一枚方解石-Mon3tr的线索」。**不设恒等 variants（Mon3tr）**"
                            "——恒等映射不收（同 endfield.py 既有约定）；小写错形由 AK_TERMS 的"
                            "`mon3tr→Mon3tr` 大小写敏感裸键兜。⚠ **`怪物` 不入表**：2026-11-02 跨片实测，"
                            "旧《How Did You Join Arknights or Endfield?》#3346 \"the monster reset\" 是通用"
                            "怪物义，被 怪物->Mon3tr 锚定误改；怪物是常用词且英文侧无稳定专名特征，"
                            "按戒律只逐 cue 判（本片 EP17 的 14 处已在 _calib_arkch17 侧车改定）。"
                            "愈伤组织=callus 是罕见形、碰撞面为零，保留锚定。"))
ENTITIES.append(Entity("可露希尔", modes=("ak",), en="Closure",
                       category="干员/明日方舟",
                       ctx=((r"\bclosures?\b", "关闭"),),
                       note="Closure 官方中文「可露希尔」（6★ 先锋·战术家，官网 3046）。本片谷翻把"
                            "「Closure is playable」整片译成「关闭」（#335/#338 等）。「关闭」是超常用词"
                            "只走 ctx；大写裸键已在 AK_TERMS:301，小写 closure=克洛丝 是旧片抽卡语境"
                            "沉淀（AK_TERMS:212），str.replace 大小写敏感，两者不冲突。"))
ENTITIES.append(Entity("重装", modes=("ak",), en="Defender",
                       category="职业/明日方舟",
                       ctx=((r"\bdefenders?\b", "后卫"),),
                       note="Defender 是职业名「重装」（裂响＝重装·本源铁卫），谷翻作「后卫」。"
                            "「后卫」是体育常用词，禁裸键，只按英文行锚定。"))
ENTITIES.append(Entity("博士", modes=("ak",), en="Doctor",
                       category="称谓/明日方舟",
                       ctx=((r"\bdoctors?\b", "医生"),),
                       note="Arknights 的 Doctor 官方称谓「博士」，谷翻常作「医生」（本片 #17 "
                            "\"All right, the doctor.\"，音频复核确为 doctor）。「医生」是常用词，"
                            "禁裸键；与既有 medic→医疗干员 不冲突。"))
ENTITIES.append(Entity("相变临界", modes=("ak",), en="Critical Phase Transition",
                       category="章节/明日方舟",
                       variants=("临界相变",),
                       note="主题曲 EP17 官方简中章名「相变临界」（官网 3046「主题曲EP17【相变临界】」、"
                            "PRTS 相变临界词条）；谷翻按词序直译成「临界相变」是错形。4 字专名、"
                            "非常用词，可裸键。"))
ENTITIES.append(Entity("裂响", modes=("ak",), en="Crackborne",
                       category="干员/明日方舟",
                       variants=("Crackborne", "Crackborn", "Crackorn", "克拉科恩"),
                       note="5★ 重装·本源铁卫「裂响」（官网 3046；本名瑭雅·艾利卢耶娃）。"
                            "「五星守护者」的说法为误，官方分支是本源铁卫。ASR 常作 Crackorn，"
                            "谷翻音译「克拉科恩」（本片 #145）；「克拉克伯恩」已在 AK_TERMS:304，"
                            "同目标幂等不重复登记。"))
ENTITIES.append(Entity("乌萨斯", modes=("ak",), en="Ursus",
                       category="势力/明日方舟",
                       variants=("Ursus", "乌尔苏斯"),
                       note="Ursus 官方「乌萨斯」，EP17 舞台（泽尔格勒＝乌萨斯卫星城）。"
                            "官方 PV 旁白 `乌萨斯。我将为你带来，「永恒的春天」。` 直接确证英文 ASR 的"
                            "「Ersus」即 Ursus——但 **Ersus 不入表**（音近形低置信，逐 cue 判，"
                            "见 _calib_arkch17/r2/gloss2.md 第 3 节）。"))
ENTITIES.append(Entity("凯尔希", modes=("ak",), en="Kal'tsit",
                       category="干员/明日方舟",
                       variants=("Cowset", "Calitha", "凯尔西", "凯尔茨"),
                       note="凯尔希（Kal'tsit）扩 ak，只搬安全形：Cowset/Calitha 是本片 ASR 实测变形"
                            "（英文社区把凯尔希昵称为 Cow，谷翻/ASR 拆成 cowset/cows/cowit/calcite），"
                            "凯尔西/凯尔茨 是非正常中文词。⚠ **`凯尔特` 绝不写进本条 variants**——"
                            "它只在 bi 条目里由 EXCLUDE_CONTEXT 的 \\bCeltic\\b 负例兜住。"
                            "Kelsey/Kelip/Kelit/Kelty 与 卡尔·赛/卡尔·塞 已在 AK_TERMS，同目标幂等；"
                            "Cal/Calit/Calip/Cow/Kyle 一律不入表（短拉丁键会咬 Calcite，Kyle 是真人姓名）。"))
ENTITIES.append(Entity("卡池", modes=("ak",), en="banner",
                       category="术语/明日方舟",
                       ctx=((r"\bbanners?\b", "横幅"), (r"\bbanners?\b", "旗帜")),
                       note="banner→卡池 扩 ak：AK_TERMS 已有裸键 banner，本条只补 ctx——"
                            "谷翻把 banner 译成「横幅/旗帜」的中文错形此前只有 bi 趟能修，"
                            "纯 --ak 片源会漏（本片 #32/#68/#69/#160/#162/#307/#339 共 7 处）。"))


# ══ 2026-11-12 沉淀：《명일방주 종합 PV 월드컵》r2 二校（4946 cue，--akko）══
#   官方依据：鹰角官网活动公告（长夜临光复刻 / 一周年【苦难摇篮】/ 2023 感谢庆典
#   【崔林特尔梅之金】/ 主线「局部坏死」预热）、《明日方舟：终末地》官网、
#   PRTS 泰拉词库 + arknights.wiki.gg 中英日韩对照表。
#   铁律：下列错形均为常用中文词或 ASR 音译，一律只走 ctx（韩语参考行锚定），
#   绝不入 AK_KO_TERMS 裸键；명빵(명방+빵 面包谐音梗)、명주/Landfield/Wispon/
#   APASS/신선 等待考项不收；句子级机翻幻觉（著名的地方/著名房间/公共领域/
#   人很有名 等）走 subfix 侧车，不进 KB。
#   ⚠ 联网点验纠正：Zwillingstürme im Herbst 官方中文为「崔林特尔梅之金」，
#   不是「之秋」（韩语 가을 不对应官方中文名）；本片字幕 0 命中，仅登记备查。
#   ⚠ 니어라이트 = SideStory「长夜临光」，与干员「临光」(니어) 不是同一对象。
ENTITIES.append(Entity("长夜临光", modes=("akko",), en="Near Light", ko="니어라이트",
                       category="活动/明日方舟",
                       ctx=((r"니어\s*라이트|니어라이트", "近光"),),
                       note="鹰角官网 [活动预告]SideStory「长夜临光」复刻即将开启；"
                            "韩语 니어라이트=Near Light，谷翻作「近光/近光线」。"))
ENTITIES.append(Entity("孤星", modes=("akko",), en="Lone Trail", ko="론트레일",
                       category="活动/明日方舟",
                       ctx=((r"론트레일", "孤独的踪迹"), (r"론트레일", "孤独的小径")),
                       note="官方 SideStory「孤星」= Lone Trail；韩语 론트레일 音译被"
                            "谷翻作「孤独的踪迹/孤独的小径」。现有 AK_KO_CONTEXT 已收 Lone Trail 拉丁形。"))
ENTITIES.append(Entity("愚人号", modes=("akko",), en="Stultifera Navis", ko="스툴티페라비스",
                       category="活动/明日方舟",
                       ctx=((r"스툴티페라비스|스틀페라비스", "Stultiferavis"),),
                       note="官方 SideStory「愚人号」= Stultifera Navis（机核考据）；"
                            "补拉丁音译残留 Stultiferavis。现有 스툴티페라 规则已覆盖"
                            "凳子自卸车/油菜花/斯图尔蒂费拉 等中文错形。"))
ENTITIES.append(Entity("苦难摇篮", modes=("akko",), ko="고난의 요람",
                       category="章节/明日方舟",
                       ctx=((r"고난의\s*(?:요람|여람)", "苦难的摇篮"),
                            (r"고난의\s*(?:요람|여람)", "苦难的开始")),
                       note="鹰角官网一周年庆典公告「主线第七章节【苦难摇篮】开放」；"
                            "여람 为 요람 口播/ASR 变体。⚠ 普通词「고난=苦难」不是专名，"
                            "必须靠 고난의 요람 全形锚定，不可全局替换。"))
ENTITIES.append(Entity("终末地", modes=("akko",), en="Endfield", ko="엔드필드",
                       category="作品/明日方舟：终末地",
                       ctx=((r"엔드필드|엔더필드|핸드필드|엔필|엔드필더", "安德菲尔德"),
                            (r"엔드필드|엔더필드|핸드필드|엔필|엔드필더", "恩菲尔多"),
                            (r"엔드필드|엔더필드|핸드필드|엔필|엔드필더", "端野"),
                            (r"엔드필드|엔더필드|핸드필드|엔필|엔드필더", "末场"),
                            (r"엔드필더", "终点")),
                       note="官方《明日方舟：终末地》(endfield.hypergryph.com)。"
                            "安德菲尔德/恩菲尔多 为 ASR 音译，端野/末场/终点 为 end·field 直译；"
                            "全部靠韩语行锚定，避免误伤其他片源的「末场/终点」。"))
ENTITIES.append(Entity("塔露拉", modes=("akko",), en="Talulah", ko="탈롤라",
                       category="角色/明日方舟",
                       ctx=((r"탈롤라|탈로라|탈룰러", "塔洛尔"),
                            (r"탈롤라|탈로라|탈룰러", "Talola")),
                       note="官方对照表 塔露拉/Talulah/탈로라；一校已改 塔罗拉/塔卢拉，"
                            "r2 补「塔洛尔」「Talola」两处漏网。"))
ENTITIES.append(Entity("罗德岛", modes=("akko",), en="Rhodes Island", ko="로도스 아일랜드",
                       category="组织/明日方舟",
                       ctx=((r"로도스|로돠스|루도스|로더스", "Rhodes Aland"),
                            (r"루도스|로더스", "鲁多斯岛"),
                            (r"로도스|로돠스|루도스|로더스", "罗德")),
                       note="官方对照表 罗德岛/Rhodes Island/로도스 아일랜드。"
                            "wrong「罗德」⊂right「罗德岛」，靠 _ctx_replace 哨兵保护既有正确形；"
                            "AK_KO_CONTEXT 已有 罗多顿岛→罗德岛，此处补拉丁/音译/漏字形。"))
ENTITIES.append(Entity("拉普兰德", modes=("akko",), en="Lappland", ko="라플란드",
                       category="角色/明日方舟",
                       ctx=((r"라플런드|라플랜드", "拉普兰"),),
                       note="官方对照表 拉普兰德/Lappland/라플란드。现有 AK_KO_CONTEXT 锚点"
                            "라플란드|라플란 不覆盖口播变体 라플런드/라플랜드，此处补锚定；"
                            "wrong⊂right 走哨兵，既有「拉普兰德」不被再咬。"))
ENTITIES.append(Entity("明日方舟", modes=("akko",), en="Arknights", ko="명일방주",
                       category="作品/明日方舟",
                       ctx=((r"명방|명일\s*방주", "Myungbang"),
                            (r"명일\s*방주", "明日之战")),
                       note="官方对照表 明日方舟/Arknights/명일방주；韩语缩略 명방。"
                            "⚠ 명빵 是「명방+빵(面包)」谐音梗，字形不同不会被本锚点命中，"
                            "一校有意保留，禁止改成「明日方舟」。"))
ENTITIES.append(Entity("干员", modes=("akko",), en="Operator", ko="오퍼레이터",
                       category="术语/明日方舟",
                       ctx=((r"후방\s*지원\s*오퍼레이터", "后方支援人员"),),
                       note="官方术语「干员」；一校 decisions.md 已归一 操作员/运营商/接线员/运算符，"
                            "r2 补「后方支援人员」漏网。用完整词锚定，不改裸「人员」。"))
ENTITIES.append(Entity("边狱巴士", modes=("akko",), en="Limbus Company", ko="림버스",
                       category="作品/联动",
                       ctx=((r"림버스", "边缘"),),
                       note="一校 --akko 既定口径「边狱巴士」（decisions.md 明定保留，"
                            "联网点验显示「边狱公司」亦为通行名，属口径变更非漏校）。"
                            "机翻把 림버스 音近词误作「边缘」，靠韩语行锚定。"))
