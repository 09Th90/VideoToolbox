# -*- coding: utf-8 -*-
# @version 2.7.0
"""术语/实体数据表

源：subtitle_calib_merged.py L2818-L5275 @ 97d7d463（2026-10-24 冻结快照）
"""
import io
import os
import re
import shutil
import sys
import unicodedata


# 二次元手游 OST 世界杯：游戏名/专名中文统一（错误形式 -> 正确形式，出现即改）
WWOC_TERMS = {
    # 游戏名跨段统一（妮姬/胜利女神 为 NIKKE 的旧译/意译，统一为英文专名）
    "妮姬（NIKKE）": "NIKKE",
    "妮姬(NIKKE)": "NIKKE",
    "妮姬": "NIKKE",
    "胜利女神": "NIKKE",
    "NIKKE（胜利女神）": "NIKKE",
    "禅心在世（ZenExistence）": "绝区零",
    "禅心在世(ZenExistence)": "绝区零",
    "禅心在世": "绝区零",
    "蓝档案": "蔚蓝档案",
    # 综合游戏中文本地化（韩语原声常见音译/残留英文 -> 官方中文）
    "원신": "原神",
    "붕괴": "崩坏",
    "명일방주": "明日方舟",
    "젠레스 존 제로": "绝区零",
    "젠존재": "绝区零",
}


# 3.3 战双帕弥什·英文原声（中英双语片源，2026-09-11 沉淀）
# 片源：Adelyde and Date A Live Collab Have Me HYPED! | Punishing: Gray Raven
#       （EN 主播观看《战双帕弥什》「远信回响」前瞻直播 + 海伦汀·安魂 / 魔鬼教官 PV）
# 只改首中文行，英文参考行一字不动；与 --pgr（音乐会片源侧车整行覆盖）是两套机制，互不干扰。
# 官方依据：战双官网/微博「远信回响」前瞻特别节目（2026-09-10，9/24 开启）、
#   「孑念空行」版本公告（7/17，海伦汀·安魂 S 级 雷/增幅型，PV「HELENTINE: LACRIMOSA」）、
#   库街区《「海伦汀·安魂」角色PV | 完美任务》、《战双帕弥什》×《约会大作战V》联动公告
#   （联动角色 时崎狂三 S 级 暗属性/进攻型、联动剧情「空滞轮旋之梦」、异界装备「刻刻帝」）；
#   中文写法与第 6 节 PGR_NOUNS 保持一致。
# 戒律（同其它片源表）：①裸"惩罚"不进表（#1287 punishment=惩罚 是本义）；
#   ②裸"构建"不进表（#446/600 build your deck=构建你的套牌 是本义），只收「构建研发」；
#   ③"记忆"（memories）在 PGR 里官方作"意识"，但 #1030 memories 是本义，故逐 cue 侧车处理。
PGR_EN_TERMS = {
    # 游戏 / 厂商（EN "Punishing Grey Raven" 官方中文即《战双帕弥什》）
    "惩罚性灰乌鸦": "战双帕弥什", "惩罚灰乌鸦": "战双帕弥什", "惩罚灰鸦": "战双帕弥什",
    "惩罚灰色": "战双帕弥什", "惩罚伟大的乌鸦": "战双帕弥什", "惩罚同性恋乌鸦": "战双帕弥什",
    "Withering Waves": "鸣潮", "枯萎的波浪": "鸣潮", "枯萎波": "鸣潮", "Vuva": "鸣潮",
    "W Crow 游戏": "库洛游戏",
    # 构造体 / 角色（ASR 变体穷举；长键在前，短键在后）
    "Krumi Tokaki": "时崎狂三", "克鲁米·托卡基": "时崎狂三", "时明来未": "时崎狂三",
    "Crew Me": "狂三", "Croomie": "狂三", "Kroomi": "狂三", "Krumi": "狂三", "Kumi": "狂三",
    "克鲁米": "狂三", "库米": "狂三", "久美": "狂三",
    "Adelide": "阿德莱德", "Adelite": "阿德莱德", "Edelite": "阿德莱德", "Adelai": "阿德莱德",
    "Adeline": "阿德莱德", "Edaly": "阿德莱德", "阿德利德": "阿德莱德", "艾德琳": "阿德莱德",
    "Karanina Eulgan": "卡列尼娜·烬燃", "Karanina": "卡列尼娜", "卡维尼娜": "卡列尼娜",
    "Helentine": "海伦汀", "Helenine": "海伦汀", "Heline": "海伦汀", "Helen": "海伦汀",
    # 裸"海伦"不进表：#969 原文已是正确的「海伦汀」，裸键会把"海伦汀"二次替换成"海伦汀汀"，
    # 故 #136/771/1025/1044 的"海伦"逐 cue 侧车处理（长键结果不得被短键命中，见 3.1b2 戒律）
    "海伦娜": "海伦汀", "帕伦汀": "海伦汀", "情人节": "海伦汀",
    "Jatavi": "洁塔薇",
    "纳蒂亚": "涅缇娅", "奈瓦提亚": "涅缇娅", "涅槃": "涅缇娅",
    "露西娅": "露西亚", "Lucia": "露西亚", "逆冠": "逆冕",
    "JenRan": "景燃", "静然": "景燃",
    # 术语（机翻直译 -> 官方用语）
    "编码": "涂装",                 # EN "coding" = 涂装（皮肤），机翻作"编码"
    "服务店": "勤务商店",           # service shop（官方：通过【勤务商店】兑换）
    "构建研发": "构造体研发",       # construct = 构造体
    "快速升级": "一键养成",         # quick upgrade = 一键养成系统
    "赤潮": "红潮",                 # PGR 帕弥什红潮
    "空间震动": "空间震",           # 约会大作战术语 space quake
    "北极航线联盟": "北极航线联合",
    "Data Live": "约会大作战",
    # 其它专名 / 社区词
    "火花": "花火",                 # 星穹铁道角色 Sparkle（官方中文花火）
    "赤壁": "Q版",                  # chibi，机翻误作赤壁
    "抽搐": "Twitch",               # 平台名，机翻误作抽搐
    # 2026-09-11 远信回响版本官方中文确认（战双帕弥什×约会大作战V联动）
    "星星的回忆": "浮影述忆", "恒星回忆": "浮影述忆",   # Stellar Memories 官方涂装研发名（原误作星屿述忆）
    "深色过度链接器": "暗属性、聚变型", "过度链接器": "聚变型",  # overlinker = 聚变型新职业
    "新班级": "全新职业", "全新的类别": "全新职业",     # new class = 职业（非班级）
    "皮肤": "涂装",                  # skins = 涂装（与 coding->涂装 统一）
    "模拟": "回路演算",              # simulation = 回路演算（新玩法）
    "超频": "超频演算",              # overclock = 超频演算（新挑战模式）
}

AK_TERMS = {
    # --- 本片机翻英文残留 -> 官方中文 ---
    "AK": "明日方舟", "Ark Knights": "明日方舟", "Arknights": "明日方舟",
    "sanity": "理智", "LMD": "龙门币", "XP": "经验", "exp": "经验",
    # 角色/阵营（本片 ASR 变体 -> 官方中文）
    "Kelsey": "凯尔希", "Kelip": "凯尔希", "Kelit": "凯尔希", "Kelty": "凯尔希",
    "Amya": "阿米娅", "Wang": "W", "Wong": "W",
    "Lapland": "拉普兰德", "Suzuran": "铃兰", "Dusk": "夕",
    "Indra": "因陀罗", "Valkcon": "火神", "Sara": "塞雷娅",
    "Silver Ash": "银灰", "Jessica": "杰西卡", "Meteor": "流星",
    "Blue": "蓝毒", "Angelina": "安洁莉娜", "Reed": "苇草", "Hoshi": "星熊",
    "Suso": "苏苏洛", "Pure Stream": "清流", "Perfumer": "调香师",
    "Breeze": "微风", "Malberry": "桑葚", "Mulberry": "桑葚",
    "Wizard": "维什戴尔", "Wizardell": "维什戴尔",  # Wisadel W异格
    "Land": "兰德", "Widel": "威德尔",  # ASR 不明的限定位（存疑，保留音译）
    "Cruz": "克洛丝", "cruise": "克洛丝", "closure": "克洛丝",
    "Milanta": "米兰塔", "Srausa": "斯劳萨", "Rydian": "瑞迪安",
    "cookie": "库奇", "Cookie": "库奇", "Chennis": "陈尼斯",
    "Enfield": "终末地",
    "Nearlight": "临光",           # 英文干员名漏进中文行（ニアライト=临光）
    "新药能天使": "新约能天使",     # ASR 把新約听成新薬，谷歌直译"新药"
    "普里基亚": "光之美少女",       # プリキュア ASR 变体プリキア的谷歌音译（VTuber 常引用）
    # --- 2026-09-11 沉淀：《NIKKE Player Reacts to Typhoeus Operator Story & Combat Demo》
    #     注意：此片实为终末地(Endfield) reaction，应用 --endo 模式；此处仅沉淀明日方舟本体术语。
    #     提丰(Typhon)=明日方舟本体六星狙击；终末地"再旅者"形态官方名=提弗洛斯(Typhoeus)，见 ENDFIELD_TERMS。
    #     "操作员"为 operator 直译，明日方舟本体语境统一为"干员"（仅 --ak 模式；终末地侧用长键"操作员故事"防误伤）。
    "Typhon": "提丰", "T-Phone": "提丰", "T-phone": "提丰",  # 提丰=明日方舟本体六星狙击；T-Phone/T-phone 为韩语 티폰 机翻形（源自 Endfield 评论片，归 ak）
    "操作员": "干员",
    # 玩法模式
    "RA": "生息演算", "Reclamation": "生息演算",
    "CC": "危机合约", "Contingency": "危机合约",
    "SSS": "保全派驻", "IS-6": "集成战略", "IS6": "集成战略",
    "IS-5": "集成战略", "IS-2": "集成战略", "IS-3": "集成战略",
    "Annihilation": "剿灭", "annihilation": "剿灭",
    "orundum": "合成玉", "orandom": "合成玉", "Prime": "至纯源石",
    # 术语
    "E2": "精英化2", "E1": "精英化1", "elite": "精英化",
    "module": "模组", "hyperinvest": "重点培养", "hyper": "鹰角",
    "Hypergryph": "鹰角", "banner": "卡池", "endame": "终局内容",
    "welfare": "赠送干员", "M3": "专精3",
    # 联动/活动
    "Monster Hunter": "怪物猎人", "Rainbow 6": "彩虹六号", "Rainbow 6": "彩虹六号",
    "Persona": "女神异闻录",
    # 网站（用户搭建，保留英文）
    "Aripedia": "arkpedia", "Aredia": "arkpedia",
    # --- 2026-09-11 沉淀：《Someone save HYRMKM | VTuber Arknights Blind Music Reaction》
    #     英语原声 + 谷歌翻译中文行（3465 cue）。ASR 把 Arknights 听成
    #     Arc Night / arc nights / Arg Nights / Argite / Archite / Arg / AK 等，
    #     谷歌据此直译成 方舟骑士 / 弧光之夜 / 弧夜 / 阿尔吉特 / 阿格内茨，统一回官方名 明日方舟。
    "方舟骑士团": "明日方舟", "方舟骑士队": "明日方舟",  # 机翻把 Knights 直译成 团/队，需整段吃掉
    "方舟骑士": "明日方舟", "弧光之夜": "明日方舟", "弧光骑士": "明日方舟",
    "方舟之夜": "明日方舟", "弧夜": "明日方舟", "圣弧骑士": "我的明日方舟啊",
    "方舟之战": "明日方舟",                              # 2026-10-06 沉淀（Angelina Alter Event reaction 片）
    "youtube": "YouTube",                               # 谷翻保留小写品牌名 -> 官方拼写（非中文词，裸键安全）
    "Arc Night": "明日方舟", "Arc Knights": "明日方舟", "arc nights": "明日方舟",
    "Arg Nights": "明日方舟", "Arg Knights": "明日方舟",
    "Argite": "明日方舟", "Archite": "明日方舟", "Argis": "明日方舟", "Arg": "明日方舟",
    "阿尔吉特": "明日方舟", "阿格内茨": "明日方舟", "阿基特": "明日方舟",
    # 地名/剧情官方写法（ARKNIGHTS_NOUNS 底表佐证：卡兹戴尔 / 离解复合(第15章) / 龙门 / 海嗣 / 蕾缪安）
    "卡兹德尔": "卡兹戴尔", "解离重组": "离解复合", "恩菲尔德": "终末地",
    "龙曼": "龙门", "肺人": "龙门", "Lungman": "龙门", "lungman": "龙门",
    "莱穆因": "蕾缪安", "seaborn": "海嗣", "Seaborn": "海嗣",
    # 主播自称/粉丝名，机翻不一致，统一（Moami Madness 被 ASR 成 Mocomi）
    "莫科米": "莫阿米",
    # Twitch 用户名：机翻按普通名词直译（驳船/赤红/深红/猩红），统一回拉丁原名
    "驳船宾格斯": "Barge Bingus", "驳船宾吉特": "Barge Bingus",
    "平格斯驳船": "Barge Bingus", "驳船": "Barge",
    "深红色的猫": "Crimson Cats", "深红深红猫": "Crimson Cats",
    "赤红卡斯": "Crimson Cass", "深红卡斯": "Crimson Cass",
    "红猫": "Crimson Cat", "猩红": "Crimson", "赤红": "Crimson", "深红": "Crimson",
    "科沃斯": "cowoos",
    # --- 2026-09-14 沉淀：《Music Composer Reacts - Mortal Eye (Arknights)》reaction
    #     片源：英文原声 + 谷歌翻译中文行。Mortal Eye = 明日方舟提丰角色歌（衍生音乐，
    #     作曲 Adam Gubman，主唱 BONZIE，和声 Christine Hals；曲名无官方中文保留直译"凡人之眼"）。
    #     参考行 ASR 把 Christine Hals 串改成 Christine House；"逆转1999"为 Reverse 1999 直译。
    "Christine House": "Christine Hals",   # 主唱/和声名 ASR 串改 House
    "Bonsie": "BONZIE",                    # 主唱 BONZIE 大小写统一
    "逆转1999": "重返未来：1999",           # Reverse 1999 官方中文名（其它手游引述）
    "Adam Gubman": "亚当·古布曼",           # 作曲/作词/编曲官方中文名（酷狗/塞壬唱片）
    # Mortal Eye 官方中文名不存在（PRTS/塞壬唱片均保留英文《Mortal Eye》），
    # 中文行保留直译"凡人之眼"，勿强改；"提丰"官方中文已在上表 "Typhon".
    # --- 2026-10-09 沉淀：《Arknights OST "Awaken" Reaction + Analysis》音乐分析片
    #     片源：英文原声 + 谷歌翻译中文行（155 cue）。Awaken=归溟幽灵鲨(Specter the
    #     Unchained)角色曲，Adam Gubman 作词作曲，塞壬唱片发行，曲名官方保留英文。
    #     博主为音乐作曲人，全程乐理分析（Dorian调式/sea shanty/转调/乐句等），
    #     谷翻把大量音乐术语译错。以下为音译残留/非普通中文词，裸键安全。
    "多里安": "多利亚",               # Dorian mode 标准中文乐理术语=多利亚调式，谷翻误译"多里安"
    "海什蚂蚁": "水手歌",             # sea shanties 谷翻音译错误
    "海上棚屋": "水手歌",             # sea shanty 谷翻误译（shanty≠棚屋）
    "梅尔奥迪克": "旋律",             # melodic 谷翻音译错误
    "B自然": "还原B",                 # B natural 标准乐理术语=还原B
    "音调中心": "调性中心",           # tonal center 标准乐理术语=调性中心
    # --- 2026-10-12 沉淀：《【字幕】All You Should Know in Arknights Next Update!》
    #     17章前瞻片（英文原声+谷歌翻译中文行，132 cue）。Kal'tsit ASR 成 Kal sey、
    #     Ursus 音译乌尔苏斯、Mystic Caster 译"神秘施法者"、Closure 大写形（可露希尔）、
    #     IS3 音译《我之剑3》等。注意：closure(小写)=克洛丝 为旧片 ASR 沉淀，
    #     Closure(大写)=可露希尔，大小写敏感替换二者不冲突。
    "乌尔苏斯": "乌萨斯",              # Ursus 官方=乌萨斯
    # 2026-10-14 二轮回改：旧表暂称"凯尔希异格"经官网核实为全名「凯尔希·思衡托」
    #（ak.hypergryph.com 七周年页/2026-05-01 版本公告：首位医疗·守望者分支限定六星）
    "卡尔·塞·阿尔特": "凯尔希·思衡托",  # Kal'tsit alter ASR+谷翻串形
    "Kal sey alter": "凯尔希·思衡托",
    "卡尔·赛": "凯尔希", "卡尔·塞": "凯尔希",
    "Kal Sey": "凯尔希", "Kal sey": "凯尔希",
    "Closure": "可露希尔",             # Closure 官方=可露希尔（大写形）
    # --- 2026-10-14 二次校准（同片逐句复查）新增：英文/音译残留裸键 ---
    "Viy": "维伊",                     # 七周年 EP17 免费六星术师·秘术师，官方=维伊
    "克拉克伯恩": "裂响",              # Crackborne 谷翻音译，官方=裂响（五星重装·本源铁卫）
    "Thumphy": "珊比",                 # Thumpy（ASR 多写一个 h）=六星重装·本源铁卫 珊比
    "Gallus": "GALLUS²",               # 一星术师官方名保留拉丁原形（带²）
    "泰丰": "提丰",                     # Typhon 音译变体，官方=提丰
    "幽灵祭坛": "归溟幽灵鲨",          # Specter alter（alter 被谷翻成"祭坛"）
    "德州祭坛": "缄默德克萨斯",        # Texas the Omertosa 官方=缄默德克萨斯
    "Sankta爷爷": "信仰搅拌机",        # 官方英文名 Sankta Miksaparato（六周年赠送六星重装）
    "守望人": "守望者",                 # Watcher 医疗子职业官方=守望者
    "神秘施法者": "秘术师",            # Mystic Caster 官方子职业=秘术师
    "新算符": "新干员", "运营商": "干员",   # operator 谷翻误译（仅 --ak 模式生效）
    "限量卡池": "限定卡池", "限量赛": "限定干员",
    "罐体单元": "坦克单位",            # tank unit 谷翻
    "《我之剑3》": "集成战略3",        # IS3 谷翻音译
    "Orundum": "合成玉",               # 大写形（小写 orundum 已有）
    "Degen": "锏",                     # Degenbrecher 官方=锏
    "Savage": "暴行",                  # Savage 官方=暴行
    "穆穆": "缪尔赛思",                # 2026-10-14 二轮回改：Muelsyse 官方=缪尔赛思（旧目标"缪缪"是昵称非官方）
    "穆缪": "缪尔赛思",                # ASR 变体穆缪 同改；"缪缪"本身是合法昵称，不收裸键
    "模块": "模组",                    # 明日方舟 module 官方=模组（--ak 模式隔离，编程语境不入）
}

# =============================================================
# 3.1c AK_CONTEXT：明日方舟**双语**片源（英文原声 + 谷歌翻译中文行）的条件变体。
# 2026-10-06 新增能力：此前 --ak 只有无条件表（AK_TERMS），凡是"普通中文词义错位"
#   都无法安全沉淀——裸键必然跨片源误伤（例：寒冷/乐观/声音/空缺/一切幻想）。
#   本表以**英文参考行正则**锚定，与 bi 的 CONTEXT_MAP 同构，但只在 --ak 生效。
# 戒律：错形必须是**正常中文词**（字面义误译），且能由参考行唯一佐证；
#   非词错形（音译残留/英文残留）仍走 AK_TERMS 裸键，不入本表。
#   整句语序问题（断句跨 cue、修饰语错位）本表无解，仍走 subfix。
# 用法：python subtitle_calib_merged.py <in.srt> --ak --out out.srt
# =============================================================
AK_CONTEXT = [
    # (参考行正则, 中文行错形, 正确形)
    (r"\bchilled\b", "寒冷", "慵懒"),          # #78 It's just so chilled and relaxed（chilled=慵懒，非"寒冷"）
    (r"\ban opening\b", "空缺", "开场曲"),      # #94 this sounds like an opening, if anything（开场曲，非"空缺"）
    (r"\bvoicings?\b", "声音", "音色"),         # #103 the chords and voicings（voicing=音色/和声配置；ASR 断词 vo ic ings 已入 EN_ASR_SPLIT_FIXES）
    (r"\bEverything Fantasy\b", "一切幻想", "Everything Fantasy"),  # #3 博主频道名，保留拉丁原名（与 #145/#146 网址写法统一）
    (r"\bupbeat\b", "乐观", "欢快"),            # #14 very upbeat so far（音乐语境=欢快，非"乐观"）
    # --- 2026-10-09 沉淀：《Awaken》音乐分析片，乐理术语普通中文词义错位（参考行锚定）
    (r"\bphrases?\b", "词组", "乐句"),          # 音乐分析中 phrases=乐句，谷翻误译"词组"
    (r"\bphrases?\b", "短语", "乐句"),          # 同上，谷翻另一误译形"短语"
    (r"\bkey\s+changes?\b", "按键变化", "转调"), # key change=转调，谷翻误译"按键变化"
    (r"\bkey\s+changes?\b", "关键变化", "转调"), # 同上，谷翻另一误译形"关键变化"
    (r"\bmodal\b", "模态", "调式"),              # modal ambiguity=调式歧义，谷翻误译"模态"
    (r"\bsubdued\b", "压抑", "弱化"),            # 音乐/配器语境 subdued=弱化，谷翻误译"压抑"
    # --- 2026-10-12 沉淀：《All You Should Know in Arknights Next Update!》普通中文词义错位 ---
    (r"\barchetypes?\b", "典型", "职业分支"),       # #18 this archetype=职业分支，谷翻"典型"
    (r"\barchetypes?\b", "原型", "职业分支"),       # #109 archetype=职业分支（"原型"字面义错位）
    (r"\btalent\b", "才华", "天赋"),                # #19 talent=明日方舟机制"天赋"
    (r"true damage", "真伤害", "真实伤害"),         # #21 true damage 官方=真实伤害
    (r"\bpotential\b", "潜力", "潜能"),             # #54 potential=明日方舟"潜能"
    (r"\bspecter alter\b", "幽灵变形", "归溟幽灵鲨"),  # #55 Specter alter 官方=归溟幽灵鲨
    (r"\bgavial alter\b", "加维尔", "百炼嘉维尔"),  # #56 Gavial alter 官方=百炼嘉维尔
    (r"\bspark\b", "火花", "黄票兑换"),             # #55 spark cost=黄票兑换消耗
    (r"\brate up\b", "卡率提升", "概率提升"),       # #53 rate up
    (r"\benablers?\b", "纵容者", "启动器"),        # #47 corrosion enabler（2026-10-14 修正旧正则笔误 \bbenablers?\b 无法命中 "enabler"）
    (r"\brerun\b", "重播的皮肤", "复刻皮肤"),       # #59 rerun skins
    (r"\bstages\b", "各个阶段", "各个关卡"),        # #62 examine the stages
    (r"\bstages\b", "赛段", "关卡"),                # #78 The stages will also have
    (r"[Ee]pisode 17", "第17集", "第17章"),         # #63 主线 episode=章节
    (r"\bepisode\b", "这一集", "这一章"),           # #74 this episode
    (r"\bboss\b", "老板", "Boss"),                  # #81 As for the boss
    (r"\bmedics?\b", "医疗兵", "医疗干员"),         # #66 bring enough medic
    (r"leak source", "漏水源", "泄漏源"),           # #69
    (r"leak mark", "漏水痕迹", "泄漏标记"),         # #78
    (r"\btiles?\b", "瓷砖", "格子"),                # #72 4 tiles（明日方舟 tile=格子）
    (r"\bstunned?\b", "昏迷", "眩晕"),              # #73 stun=明日方舟"眩晕"
    (r"old well", "旧水井", "旧井"),                # #102 bring back the old well
    (r"yellow rocks", "黄色石头", "至纯源石"),      # #103 主线通关奖励=至纯源石俗称
    (r"arts damage", "术技伤害", "法术伤害"),       # #85 arts damage=法术伤害
    (r"\bscreen\b", "屏风", "屏幕"),                # #101 tap the screen
    (r"\breclamation\b", "收复局", "生息演算"),     # #117 Reclamation Algorithm=生息演算
    (r"\bwrong\b", "买到", "弄错"),                 # #61 get some things wrong
    (r"will be life", "出生", "上线"),              # #4 will be live（ASR life）
    (r"\bbanner\b", "旗帜", "卡池"),                # #11 limited banner
    (r"stun\s+counter", "晕眩装备", "眩晕对策"),    # #75 stun counter
    (r"to start your stage", "结局", "可露希尔"),   # #31 ref 尾行锚定（Closure 不在尾行）
    (r"in the squad", "闭合", "可露希尔"),          # #34 ref 尾行锚定（同上）
    (r"Compared to Kal", "卡尔", "凯尔希"),         # #38（"卡尔"裸键过宽，仅此句式锚定）
    (r"\boperator records?\b", "干员记录", "干员密录"),  # #112 Operator Record 官方=干员密录
    # --- 2026-10-12 二次校准沉淀（同片第二轮，普通中文词义错位）---
    (r"chem\s*leak", "泄露", "泄漏"),               # 化学泄漏机制名用字统一（泄漏≠泄露）
    (r"same resistance", "抵抗", "法术抗性"),       # #93 resistance=明日方舟"法术抗性"
    (r"total login", "总登录", "累计登录"),         # #122/123 total login reward=累计登录奖励
    (r"\bselectors?\b", "选择器", "自选券"),        # #119/126 6 star selector=六星自选券
    # --- 2026-10-14 三次校准（同片逐句复查 + 全中文行覆盖）沉淀：普通中文词义错位 ---
    #   ⚠ 本批多条错形位于 cue 的**第二中文行**，旧 --ak 只改首中文行故漏校，
    #   已随本次 process 改造（ak 分支改走"全部中文行"）一并生效。
    (r"\blimited\b", "限量版", "限定"),             # #11 new limited banner
    (r"\blimited\b", "限制", "限定"),               # #12 The limited in this event=限定（干员）
    (r"new 1\s+star", "明星", "一星"),              # #50 new 1 star 断行，谷翻"明星"
    (r"standard 6 star", "标准的6星", "常驻六星"),  # #27 standard=常驻池干员
    (r"CN server", "CN 服务器", "国服"),            # #6 CN server=国服
    (r"\bredeploy", "重新部署", "再部署"),          # #25 redeployment 官方术语=再部署
    (r"\belemental\b", "元素伤害", "元素损伤"),      # #89 elemental=元素损伤（非伤害）
    (r"\bplace\b", "名次", "放置"),                 # #87 place 断行，谷翻"名次"
    (r"total of", "总共登录", "累计登录"),          # #123 a total of ... days of login
    (r"\bresistance\b", "阻力", "法术抗性"),        # #51 reduce enemy resistance=GALLUS²天赋"使敌人法术抗性降低"
    (r"life\s+stream", "人生中", "直播"),           # #129 livestream 被 ASR 断成 life stream，谷翻"人生中见过"
    (r"\bmedics?\b", "医护人员", "医疗干员"),        # #17/75 medic=医疗干员
    (r"corrosion", "腐蚀", "侵蚀"),                 # #46/47 corrosion=侵蚀损伤
    (r"primal defender", "原始防御者", "本源铁卫"),  # #46 Primal Defender 官方子职业=本源铁卫
    (r"\bcasters?\b", "施法者", "术师"),            # #51 Caster 官方职业名=术师（谷翻"施法者"）
    (r"\btherapists?\b", "治疗师", "疗养师"),        # #75 Therapist 官方医疗子职业=疗养师（流明/锡兰/絮雨/清流）
    (r"red token", "红色令牌", "采购凭证"),          # #115 red token shop=采购凭证商店（官方公告用语）
    (r"certificate shop", "证书商店", "凭证交易所"),  # #115 certificate shop=凭证交易所（采购中心分区）
    (r"kernel", "kernel", "中坚甄选"),              # #127 Kernel Locating=官方活动名（ak.hypergryph.com/news/0867 中坚甄选开启），中文行残留英文
    (r"standard pool", "标准池", "标准寻访"),        # #127 standard pool=常驻标准寻访卡池
    (r"savage bride", "暴行新娘皮肤", "暴行「又一年秋季」皮肤"),  # #125 官方活动服饰名（忒斯特收藏系列-又一年秋季-暴行）
    (r"\btactician\b", "战术先锋", "战术家"),       # #30 Tactician 官方分支=战术家
    (r"\bstages\b", "这些阶段", "这些关卡"),        # #65 In these stages
    (r"\bstages\b", "章节阶段", "章节关卡"),        # #103 this episode stages
    (r"\bbenablers?\b", "纵容者", "启动器"),        # #47 corrosion enabler
]

AK_KO_TERMS = {
    # --- 角色名：夜刀(야토) ---
    "雅托": "夜刀", "矢藤": "夜刀", "亚托": "夜刀", "Yato": "夜刀",
    "夜斗": "夜刀", "矢富": "夜刀", "亚托娜": "夜刀",
    # --- 阵营/地名：叙拉古(시라쿠사)、德克萨斯(텍사스)、拉普兰德(라플란드) ---
    "锡拉丘兹": "叙拉古", "锡拉库扎": "叙拉古", "雪城": "叙拉古",
    "德克萨斯州": "德克萨斯",
    "拉普兰": "拉普兰德",
    # --- 角色名：年(니엔)、临光(니어) 系 ---
    "Nien": "年", "尼恩": "年",
    "玛丽亚·尼尔": "玛莉娅·临光", "Maria Near": "玛莉娅·临光",
    "Blamy Shine": "瑕光",
    # --- 角色名：克丽斯腾(크리스틴) ---
    "克里斯汀": "克丽斯腾",
    # --- 角色名：塔露拉(탈룰라)、安洁莉娜(안젤리나)、温蒂(위디)、深靛(인디고) ---
    "塔卢拉": "塔露拉",
    "安吉丽娜": "安洁莉娜",
    "威迪": "温蒂",
    "靛蓝": "深靛",
    # --- 角色名：极境(엘리시움)、星熊(호시구마)、宴(우타게)、凛冬(지마) ---
    "极乐世界": "极境",
    "Hoshigumanuhande": "星熊",
    "Utage": "宴",
    "矢岛": "凛冬",
    # --- 角色名：空弦(아르케토)、爱丽丝(아이리스)、极光(오로라)、薇薇安娜(비비아나) ---
    "阿凯托": "空弦", "阿尔塞托": "空弦",
    "鸢尾花": "爱丽丝",
    "奥罗拉": "极光",
    "比比亚娜": "薇薇安娜",
    # --- 角色名：闪击(블리츠)、麦哲伦(마젤란)、驮兽(버든비스트)、爱国者(패트리어트) ---
    "Blitz": "闪击",
    "Magellan": "麦哲伦",
    "负担兽": "驮兽",
    "爱国牛": "爱国者",
    # --- 角色名：萨科塔(산크타)、伊内丝(이네스)、阿米娅/凯尔希(아미아/켈시) ---
    "桑克塔": "萨科塔",
    "伊内斯": "伊内丝", "Ines": "伊内丝",
    "阿米亚": "阿米娅", "凯尔西": "凯尔希",
    # --- 阵营/地名：泰拉(테라)、拉特兰(라테라노)、谢拉格(쉐라그)、萨尔贡(사르곤)、萨米(사미) ---
    "太拉": "泰拉", "Terra": "泰拉", "地形": "泰拉",
    "拉特拉": "拉特兰", "Latera": "拉特兰", "laterano": "拉特兰", "LATERANO": "拉特兰",
    "Sargon": "萨尔贡",
    "Sami": "萨米",
    # --- 巴别塔(바벨) ---
    "通天塔": "巴别塔", "巴贝尔": "巴别塔", "杠铃": "巴别塔",
    # --- 其它：贝洛内家族(벨로네)、切尔诺伯格(체르노보그)、真理(이스티나) ---
    "Bellone": "贝洛内家族",
    "切尔诺博格": "切尔诺伯格",
    "伊斯蒂娜": "真理",
}


# (韩语参考行正则, 中文错形, 正确)：仅当日语/韩语行命中正则、且中文行含错形时才替换。
# 歧义词保护：医生(박사)、沉默(사일런스)、火焰/烈焰/Blaze(블레이즈)、铅(리드)、
#   熔岩(라바)、泥石(머드락)、幻影(팬텀)、阿什(애쉬/애시)、沙拉(쉐라그)、霜(프로스트)、
#   幽灵(스펙터) 等均属普通中文词，靠韩语参考行佐证，勿提为全局表。
AK_KO_CONTEXT = [
    (r"박사", "医生", "博士"),
    (r"사일런스", "沉默", "赫默"),
    (r"스펙터", "幽灵", "幽灵鲨"),
    (r"블레이즈", "火焰", "煌"),
    (r"블레이즈", "烈焰", "煌"),
    (r"블레이즈", "Blaze", "煌"),
    (r"리드", "铅", "拉芙希妮"),
    (r"라바", "熔岩", "炎熔"),
    (r"머드락", "泥石", "泥岩"),
    (r"팬텀", "幻影", "傀影"),
    (r"애쉬|애시", "阿什", "灰烬"),
    (r"쉐라그", "沙拉", "谢拉格"),
    (r"쉐라그", "Sherag", "谢拉格"),
    (r"프로스트", "弗罗斯特", "霜华"),
    (r"프로스트", "冰霜", "霜华"),
    (r"프로스트", "糖霜", "霜华"),
    (r"프로스트", "霜冻", "霜华"),
    (r"프로스트", "霜人", "霜华"),
    (r"프로스트", "霜刚刚出来", "霜华刚刚出来"),
    (r"쉐라애", "Shera Ae", "耶拉"),
    (r"니어", "近姐", "临光姐"),
    (r"니어", "Nee", "临光"),
    (r"니어", "《Near》", "《临光》"),
    (r"이격지마", "这个人出来就选择他吗", "凛冬出来就选择她吗"),
    (r"슈발 ?리드", "Chevallid", "拉芙希妮"),
]


# 韩语原声·鸣潮（--ko）参考行佐证表（2026-10-01 新增）。
#   与 AK_KO_CONTEXT 同构：(韩语参考行正则, 错形, 正确)。条目由 ENTITIES 里
#   modes 含 "ko" 的实体 ctx 投影而来（见 _register_entities），故此处默认空表。
#   这里的"错形"一律是**普通中文词**（耐克/广播/个性/比赛/星轨/迷你甜瓜…），
#   必须由韩语参考行正则佐证才替换，绝不入 KO_TERMS 裸键（防跨片源误伤）。
#   用途：韩语反应片里谷翻把 게임 译成"比赛"、방송 译成"广播"、캐릭터 译成"个性"、
#   니케 译成"耐克"等；此前 --ko 只能逐 cue 写 subfix 侧车，现由本表自动覆盖。
#   —— 2026-10-01 韩服 3.7 心月狐片（여우별 정주행）首批条目：错误形态全是普通
#   中文词（再见/分手/小米/法令/渔民/玉子…），必须韩语行锚定；锚定正则一律是
#   谷翻片的**韩语参考行**里的 ASR 形态，跨片误伤率≈0（여별/어자/잔성회 等非词）。
# 璇情(선정) 锚定正则（Entity「璇情」与 KO_CONTEXT 共用）：排除 선정적인(煽情)/선정적/
# 선정되다(被选定)/선정하다(选定) 等动词·形容词用法，只留人名（#1015/#2570/#2612 实测）。
_SEONJEONG_ANCHOR = r"선정(?!(적인|적\b|되|했|하니|할|하겠|한다|되는))"

