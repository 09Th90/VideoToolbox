# -*- coding: utf-8 -*-
# @version 2.9.0
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
# 2026-10-25 二次校准沉淀（片源：《반타쿠 버튜버의 서브컬쳐 게임 OST 월드컵 128강!!》，
#   6199 cue，韩语原声 + 谷翻；官方中文依据：各作品官网/官方中文服公告 + 萌娘百科/GameKee。
#   戒律：Red / Trigger / Star Seed / 十字军 / 德州 / 家具 等短词或通用词**绝不进裸键**，
#   只能走下方 WWOC_CONTEXT 的参考行锚定；英文长键（Silver and Blood 等）可进本表。
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
    # “蓝档案”是“蔚蓝档案”的子串，不能进裸键（会把正确形叠成“蔚蔚蓝档案”）；
    # 改由 WWOC_CONTEXT 参考行锚定。
    "NIKKE耐克": "NIKKE",
    "胜利女神耐克": "NIKKE",
    "胜利者耐克": "NIKKE",
    "林布斯公司": "边狱公司",
    # 综合游戏中文本地化（韩语原声常见音译/残留英文 -> 官方中文）
    "원신": "原神",
    "붕괴": "崩坏",
    "명일방주": "明日方舟",
    "젠레스 존 제로": "绝区零",
    "젠존재": "绝区零",
    # --- 2026-10-25 官方中文名（英/中错形 -> 官方中文）---
    "Alice Fiction": "漂眇群像",              # Alice fiction 漂眇群像
    "Silver and Blood": "银与血",
    "Silver and blood": "银与血",
    "Lost Sword": "失落之剑",
    "Eversoul": "永恒灵魂",
    "World Flipper": "弹射世界",
    "Starseed: Asnia Trigger": "星链计划：未来少女",
    "Starseed:Asnia Trigger": "星链计划：未来少女",
    "Asnia Trigger": "星链计划：未来少女",
    "Red: Pride of Eden": "红色：伊甸园的骄傲",
    "Heaven Burns Red": "炽焰天穹",
    "Limbus Company": "边狱公司",
    "CounterSide": "异界事务所",
    "King's Raid": "王之逆袭",
    "Crusaders Quest": "克鲁赛德战记",
    "Tower of Fantasy": "幻塔",
    "Punishing: Gray Raven": "战双帕弥什",
    "Punishing Gray Raven": "战双帕弥什",
    "Neural Cloud": "云图计划",
    "Brown Dust 2": "棕色尘埃2",
    "Brown Dust": "棕色尘埃",
    "Dead by Daylight": "黎明杀机",
    "Jujutsu Kaisen": "咒术回战",
    "Umamusume": "赛马娘",
    "Arknights": "明日方舟",
    "Wuthering Waves": "鸣潮",
    "Genshin Impact": "原神",
    "Honkai: Star Rail": "崩坏：星穹铁道",
    "Honkai Star Rail": "崩坏：星穹铁道",
    "Zenless Zone Zero": "绝区零",
    "Reverse: 1999": "重返未来：1999",
    "Reverse 1999": "重返未来：1999",
    "Epic Seven": "第七史诗",
    "Girls' Frontline": "少女前线",
    "Shadowverse: Worlds Beyond": "影之诗：超凡世界",
    "Persona 5: The Phantom X": "女神异闻录：夜幕魅影",
    "Persona 5 The Phantom X": "女神异闻录：夜幕魅影",
    "La vaguelette": "轻涟",
    # --- 2026-10-25 r3 精校（同一 OST 世界杯片源，6199 cue）---
    "Aether Gazer": "深空之眼",
    "Ether Gazer": "深空之眼",
    "Archeland": "阿彻兰",
    "Billie Eilish": "比莉·艾利什",
    "Blue Rose": "BLUE ROSE",
    "Sdorica": "万象物语",
    "Sudorica": "万象物语",
    "Everool": "永恒灵魂",
    # 安全中文错形（非通用词，可裸键）
    "林布斯": "边狱公司",
    "国王的突袭": "王之逆袭",
    "神经云": "云图计划",
    "幻想之塔": "幻塔",
    "奉艺学园2": "崩坏学园2",
    "少年前线": "少女前线",
    "明一芳秀": "明日方舟",
    "德瓦德": "黎明杀机",
    "咒术大战": "咒术回战",
    # --- 2026-11-06 《샘웨 다시보기 23.07.01 ｜ 서브컬쳐 OST 월드컵 최신판》r3 精校沉淀（4082 cue）---
    # 键形一律取自**机翻基线中文行的实际写法**（先跑反查，见 _doc.py 同日条目），不取谚文/英文原形。
    # 谚文作品与曲名原形（mono 片源与中文行谚文残留兜底）
    "백야극광": "白夜极光",
    "아르케랜드": "阿彻兰",
    "에버소울": "永恒灵魂",
    "에버스울": "永恒灵魂",
    "에버서울": "永恒灵魂",
    "아이언사가": "机动战队大作战",
    "아터리 기어": "机动战姬：聚变",
    "아타리 기억": "机动战姬：聚变",
    "순백의 예고장": "纯白的预告信",
    "천년의 깃털": "千年之羽",
    "시인의 업무": "诗人的工作",
    "정토 심판": "何妄何执",
    "물레캐스마일": "皎洁的笑颜",
    "캔터베리 숲": "坎特伯雷森林",
    "우인호": "愚人号",
    # 唯一性强的中文/拉丁错形（正常中文不会连写，裸键安全；terms-check 已核）
    "葬礼上的自由职业者": "葬送的芙莉莲",
    "石板石之门": "泰坦纪元",
    "穆勒卡斯迈尔": "皎洁的笑颜",
    "纯土判断": "何妄何执",
    "多米纳托斯": "《Dominatus》",
    "Munhalo": "Moon Halo",
    "Munharo": "Moon Halo",
    "Undertied": "Under Tides",
    "Tender Strangest": "同伴的力量",
    "Tender Strangestic": "同伴的力量",
    # ⚠ Wlfmstr 的中文官方名存证冲突：PRTS「叙拉古人OST」第03曲作「狼之主」，
    #   而项目 memory `gacha-music-tracklist`（2026-10-26）判为「无官中、保留英文」。
    #   本轮只**规范拼写**（Wlfmster→Wlfmstr），不强改成中文，留待裁决。
    "Wlfmster": "Wlfmstr",
    # 拉丁原形 -> 官方中文（用户口径：曲名有官中用官中，无则保留原文；以下均有官方中文）
    "Polumnia Omnia": "三千娑世御咏歌",
    "For Riddles, for Wonders": "几初的智愿",
    "Rage Beneath the Mountains": "岩壑之崩",
    "Surasthana Fantasia": "净善的遐歌",
    "Winding Through Avidya": "绰巡林风",
    "Tender Strength": "同伴的力量",
    "Interstellar Journey": "星间旅行",
    "Moonlike Smile": "皎洁的笑颜",
    "Snow-Buried Tales": "雪掩的往事",
    "Maidens of Sanctity!": "花与树的女儿们",
    "Maidens of Sanctity": "花与树的女儿们",
    "Take the Journey": "踏上旅途",
    "诗人的职务": "诗人的工作",
    "启程去旅行": "踏上旅途",
    "踏上旅程": "踏上旅途",
    "净土审判": "何妄何执",
    "木勒卡斯迈尔": "皎洁的笑颜",
    "雪埋的故事": "雪掩的往事",
    "雪埋的童话": "雪掩的往事",
    "花与树的少女们": "花与树的女儿们",
    "Towerfierce": "Tower Fierce",
    "towerfierce": "Tower Fierce",
    "贝里塔斯": "真理社",
    "维里塔斯": "真理社",
    "贝丽塔斯": "真理社",
    "青白大战": "总力战",
    "赫塞德": "赫赛德",
    "瑟尔基": "鹤城",
    "奈露": "妮露",
}

# 综合手游 OST 世界杯·参考行锚定（正则, 错形, 正确形）
# 2026-10-25：多游戏片源的歧义错形必须由参考行韩语/英语佐证，避免通用词误伤。
WWOC_CONTEXT = [
    (r"크루세이더|Crusader", "十字军", "克鲁赛德战记"),
    (r"퍼니싱", "家具", "战双帕弥什"),
    (r"킹스레이드", "国王的突袭", "王之逆袭"),
    (r"리버스", "反向", "重返未来：1999"),
    (r"리버스", "反转", "重返未来：1999"),
    (r"발로란트", "勇敢", "无畏契约"),
    (r"붕계학원", "奉艺学园", "崩坏学园2"),
    (r"림버스", "林布斯", "边狱公司"),
    (r"카운터사이드", "计数器", "异界事务所"),
    (r"뉴럴 클라우드", "神经云", "云图计划"),
    (r"타워 오브 판타지", "幻想之塔", "幻塔"),
    (r"블루 아카이브|Blue Archive", "蓝色档案", "蔚蓝档案"),
    (r"소녀전선", "少年前线", "少女前线"),
    (r"명일방주", "明一芳秀", "明日方舟"),
    (r"젠레스", "禅心在世", "绝区零"),
    (r"명조", "明祖", "鸣潮"),
    (r"명조", "明朝", "鸣潮"),
    (r"붕괴", "崩溃", "崩坏"),
    (r"니케", "耐克", "NIKKE"),
    (r"덕후|덕공|덕구", "德州人", "宅友"),
    (r"덕후|덕공|덕구", "德州", "宅友"),
    (r"도트", "点图片", "像素图"),
    (r"스타시드", "Star Seed", "星链计划：未来少女"),
    (r"스타시드", "StarSeed", "星链计划：未来少女"),
    (r"아스니아 트리거|Asnia Trigger", "Asnia Trigger", "星链计划：未来少女"),
    (r"레드라는 게임", "《Red》", "红色：伊甸园的骄傲"),
    (r"레드도", "Red 也", "《红色：伊甸园的骄傲》也"),
    (r"잔물결", "涟漪", "轻涟"),
    # 2026-10-25 r3 精校：通用词/短词继续走参考行锚定
    (r"페르소나", "Persona", "女神异闻录"),
    (r"아델", "Adele", "阿黛尔"),
    (r"헤이즈|헤즈", "Hez", "Heize"),
    (r"소녀산", "少女山", "少女前线"),
    (r"레드 후드", "Red Hood", "小红帽"),
    # --- 2026-11-06 《샘웨 다시보기 23.07.01 ｜ 서브컬쳐 OST 월드컵 최신판》r3 精校沉淀 ---
    # 全部按**机翻基线中文行的实际形态**登记（反查脚本 probe_forms.py 逐条数过），
    # 通用词/正常语境词一律走参考行锚定，不入裸键：
    (r"천년의 깃털", "千年羽毛", "千年之羽"),
    (r"시인", "诗人职责", "诗人的工作"),
    (r"백악관", "白宫", "白夜极光"),
    (r"심해군단", "深海军团", "《Under Tides》"),
    (r"캔녀", "Can Girl", "资格"),
    (r"캔녀", "坎尼", "资格"),
    (r"홀아비", "鳏夫", "《Promise》"),
    (r"여행을 떠나요", "出发旅行吧", "踏上旅途"),
    (r"언더타이즈", "紧身裤", "《Under Tides》"),
    (r"언더타이즈", "解开绑带", "《Under Tides》"),
    (r"메멘토모리", "记忆碎片", "《Memento Mori》"),
    (r"레이지 베니시", "懒惰的本尼什", "岩壑之崩"),
    (r"텐더스트랭", "Tender Strongest", "同伴的力量"),
    (r"인터스텔라", "星际过渡", "星间旅行"),
    (r"스노우 버리드|Snow-Buried", "Snow Berry Tale", "雪掩的往事"),
    (r"나이트글로우", "夜辉", "《Nightglow》"),
    (r"시대를 초월한", "永恒之心", "穿越时代的心"),
    (r"루미너스 메모리", "光辉记忆", "《Luminous Memory》"),
    (r"라이브 피기스", "活猪", "《Life Begins As Gone》"),
    (r"어크로스터", "阿克洛斯特风", "《Across the wind》"),
    (r"아이언사가", "机动战争铁篇", "机动战队大作战"),
    (r"네루|내루", "涅露", "妮露"),
    (r"내루", "内侧溪流", "妮露"),
    (r"내루", "内侧流", "妮露"),
    (r"체르기", "切尔吉", "鹤城"),
    (r"청년전", "青少年比赛", "总力战"),
    (r"헤세드", "黑塞德", "赫赛德"),
    (r"장송의 프리", "Funeral Freelancers", "葬送的芙莉莲"),
    # 明确**不入表**的（留逐 cue 判，理由写在这里免得后人再塞）：
    #  ① 베리타스→「真理」：裸键/锚定都会把已成形的「真理社」叠成「真理社社」，只留「贝里塔斯→真理社」裸键；
    #  ② 검사→「检察/测试」：正常中文词，且本片 5 处命中里 3 处与黑色沙漠无关；
    #  ③ 밀레니엄→「千年」：单字级通用词；
    #  ④ 비스마르크→「俾斯麦」：碧蓝航线里是角色名，正常语境要用；
    #  ⑤ 킹스레이드「资格」/라스트 샌드「最后的沙滩」：整串通用，只在决赛等单一片段成立，逐 cue 处理。
    #  ⑥ **既有 (r"리버스", "反向", "重返未来：1999) 一条本轮实测与屏上证据冲突**：
    #     本片 c3187 参考行只作「리버스 그리고」，而 60/64 对阵页左标签是 [림버스 컴퍼니] Canto Ⅳ Boss 1 Battle
    #     （리버스 컴퍼니 判为 림버스 컴퍼니 的 OCR/拼写误形）⇒ 正确产出应是**边狱公司**，脚本按现规则给
    #     重返未来：1999。冲突源是「参考行不含 컴퍼니，无法锚定区分」，属**片源级判断**，
    #     故**不改该条行为**（改了会波及其它 OST 世界杯片），留给逐 cue 复核覆盖。
]


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
    # 2026-11-04《Jadealy Reacts to A Comet's Afterglow Trailers》（4.9「流光抛诸寰宇」）新增的
    #   莱娅->莱亚、灰乌鸦->战双帕弥什、以实玛利->伊什梅尔、九郎->库洛 **不写在这里**：
    #   按第 6 节约定，新沉淀一律追加为 ENTITIES 里的 Entity(modes=("pgren",))，由
    #   _register_entities 投影进本表（跑 `terms-check PGR_EN_TERMS` 仍会覆盖，因为它读的是
    #   注册后的 TABLES 视图）。写在扁平表里会丢掉 en/category/note，kb-export 与 AI Agent 拿不到。
}


# 3.3b 战双帕弥什·英文原声语境槽（2026-11-04 新增，锚点=英文参考行）
#   动机：这几条错形本身是**正常中文词**（硬契约第 4 条禁裸键），只能靠英文参考行佐证。
#   登记共 8 处，见 _doc.py 2026-11-04 条目（漏 sync.py 会让 kb 增量被 _sync_validate 拒收）。
#   ⚠ 本表只在 mode="pgren" 生效；--pgr（音乐会侧车片）与 --pgrja（日语原声片）不加载。
PGR_EN_CONTEXT = [
    (r"\bafter ?glow\b", "余辉", "「流光抛诸寰宇」"),   # EN afterglow 在本作即 4.9 版本名
    (r"\bafter ?glow\b", "余晖", "「流光抛诸寰宇」"),   # 同一错形的另一种谷翻产出
    # ASR 把 "A Comet's" 听成 "a comments"，谷翻据此落成"一条评论"。
    #   ⚠ 锚定写 **a comments**（复数）——误听形恒为复数；单数 "a comment" 是正常语义，不动。
    #   ⚠ ASR 有时重复（本片 #43 'a comments a comments'），机械替换会产双名，属已知"半成品"，
    #     由逐 cue 收口（2026-11-04 本片 #43 成品作「的「流光抛诸寰宇」预告片」）。
    (r"\ba comments\b", "一条评论", "「流光抛诸寰宇」"),
    (r"\bPV\b", "光伏", "PV"),                    # 谷翻把 PV 直译成"光伏"（同 JA_PGR_CONTEXT 判例）
    (r"\bribbon\b", "丝带", "缎带"),               # 官方用"缎带"（6 星武器「扭曲缎带的边陲」）
    # Kuro 被 ASR 听成 Chloe，谷翻落成"克洛伊"。片内铁证：#45 "Chloe always cook with the
    #   soundtrack" 与 #205 "Kuro cooked. Again." 同一说话人 + 同一动词 cook。
    #   ⚠ 判据假设"战双片里没有真名叫 Chloe 的角色/主播"，若日后出现需收窄锚定。
    (r"\bChloe\b", "克洛伊", "库洛"),
]


# 3.3c 战双帕弥什·英文原声 漏译体检（只报不改，供 missing --mode pgren --window 1）
#   ⚠ 2026-11-09 二校修两处**误报缺陷**（实测《A Comet's Afterglow》4667 cue，17 处疑似漏译里绝大多数是假警报）：
#     ① 原规则1 `\bPunishing\b|\bGray ?Raven\b|\bPGR\b` → 须含「战双」，会把 **punishing virus** 判成漏译
#        （中文已正确译「帕弥什病毒」，不含「战双」二字），也会把 **Gray Raven=灰鸦小队** 判成漏译。
#        修法：游戏名锚收窄到完整形 + PGR/GGR；virus 与灰鸦各自另立规则。
#     ② 原规则6 `\bPlayer\b` → 须含「指挥官」，会把 'you are a Nikki player'（妮姬玩家）、
#        'I was a GBF player'（碧蓝幻想玩家）判成漏译——跨游戏语境译「玩家」正确。
#        修法：可接受词扩为 ("指挥官","玩家")。**missing 只查漏译不查错译**，故放宽是安全的。
#   ⚠ 本表**不由 _register_entities 投影**（state.py 只投影 TERMS/CTX/EXCLUDE），新增实体后必须手工同步这里，
#     否则 audit 扫3 有锚、missing 却查不到（二校实测的断层）。
PGR_MISSING_CHECK = [
    (r"\bPGR\b|\bGGR\b|\bPunishing:?\s*Gr[ae]y\s*Raven\b", ("战双",),
     "Punishing: Gray Raven 官方中文=《战双帕弥什》；⚠ 不锚裸 Punishing（会误命中 punishing virus）"),
    (r"\bpunishing virus\b", ("帕弥什",),
     "the Punishing virus 官方中文=帕弥什病毒；接受「帕弥什」子串即可，不强求「病毒」二字"),
    (r"\bGr[ae]y ?Raven\b", ("灰鸦", "战双"),
     "Gray Raven 单独出现多指灰鸦小队（faction），亦可能是游戏名半截，两者任一即算已译"),
    (r"\bcoding", ("涂装",), "coding=涂装（PGR 官方把外观叫涂装，不叫皮肤/编码）"),
    (r"\bIshmael\b|\bIshmail\b", ("伊什梅尔",), "Ishmael=伊什梅尔·幻日（空属性/观测者/钥杖）"),
    (r"\bLeia\b|\bLayia\b|\bLatia\b|\bLeah\b", ("莱亚",), "Leia=莱亚·祈星（冰/破甲型/遣光鞭绳/覆冰）"),
    (r"\bKuro\b|\bChloe\b|\bCur Games\b|\bCrew Games\b", ("库洛",),
     "Kuro=库洛游戏；ASR 常误听成 Chloe/Cur Games/Crew Games"),
    (r"\bPlayer\b", ("指挥官", "玩家"),
     "Player=指挥官（官方对玩家的统一称谓）；⚠ 跨游戏语境（Nikki player/GBF player）译「玩家」正确，故两者任一即可"),
    (r"\bribbon\b", ("缎带",), "ribbon=缎带（官方用词，非丝带）"),
    (r"after ?glow|\ba comments\b", ("流光抛诸寰宇",),
     "A Comet's Afterglow=4.9 版本「流光抛诸寰宇」；ASR 常把 Comet's 听成 a comments"),
    (r"\bice\b", ("冰",), "莱亚=冰属性，覆冰效应"),
    # --- 2026-11-09 二校新增：与 ENTITIES 的 pgren 实体手工同步（本表不被 _register_entities 投影）---
    (r"\bcorrupted\b|\bcorrupt\b", ("感染体",), "Corrupted 官方中文=感染体，不是腐化/腐化者/腐败者"),
    (r"\bBabylonia\b|\bRabalonia\b", ("空中花园",), "Babylonia 官方中文=空中花园；Rabalonia 是 ASR 变体"),
    (r"\bVanessa\b|\bNessa\b|\bAnessa\b", ("凡妮莎",), "凡妮莎=清庭白鹭小队指挥官；Nessa/Anessa 是 ASR 截断"),
    (r"\bEgret\b", ("清庭白鹭", "白鹭"), "Egret Squad 官方中文=清庭白鹭小队"),
    (r"\bstrike (?:hawk|clock)\b", ("突击鹰",), "Strike Hawk 官方中文=突击鹰小队；ASR 常听成 Strike clock"),
    (r"\bascendant\b", ("升格者",), "Ascendant 官方中文=升格者，不是上升者/晋升者"),
    (r"\bBambinata\b|\bAminata\b|\bBaminata\b|\bBabinada\b|\bBabinatada\b|\bAinatada\b", ("邦比娜塔",),
     "邦比娜塔·琉璃（BPM-11，清庭白鹭小队）；ASR 变体簇极多，一校曾直译成「阿米纳塔」"),
    (r"\bAsimov\b|\bAsimoth\b|\bAsimol\b|\bEsimo\b", ("阿西莫夫",),
     "阿西莫夫=科学理事会首席技官；⚠ 不锚短形 Asma（是 plasma 子串）"),
    (r"\bNicol", ("尼科拉",),
     "尼科拉=指挥中心成员；⚠ 锚 Nicol **天然不匹配 Nicholas**（Nic-h-olas 第4字符 h≠o），"
     "故历史人名 Nicolas Flamel 不会被误报。**严禁放宽到 Nichol**"),
    (r"\bscience council\b", ("科学理事会",), "Science Council 官方中文=科学理事会，不是科学委员会"),
    (r"\bPyroath\b|\bPyro\b|\bpyroflucia\b", ("誓焰",), "Lucia: Pyroath 官方中文=露西亚·誓焰，不是火焰兵/喷火兵"),
    (r"\bAtlas\b", ("阿特拉斯",), "Atlas shield=阿特拉斯之盾；⚠ 不是雅典娜(Athena)"),
    (r"\bWatanabe\b|\bWatab\b|\bWatanabi\b", ("渡边",), "Watanabe 官方中文=渡边"),
    (r"\bRoland\b", ("罗兰",), "Roland=升格者阵营角色，官方中文罗兰"),
    (r"\bDisciples?\b", ("弟子", "门徒"), "Disciples 二校统一作弟子；门徒为可接受旧形"),
    (r"\bOmega\b|\bMega Gear\b|\bmega gear\b", ("欧米茄",), "Omega gear 二校统一作欧米茄装备"),
    (r"\bmistress\b", ("主人",), "游戏角色对玩家的称谓=主人；⚠ 不是情妇"),
    (r"\bMio\b|\bKurono\b|\bMioono\b|\bMokurono\b", ("澪", "黑野"), "Mio Kurono=黑野澪"),
    (r"\bheterero\b|\bhetero\b|\bheader creatures\b", ("异种生物",), "heterero creatures 二校统一作异种生物"),
    (r"\bephemer", ("蜉蝣族",), "ephemeran/effirmer(ASR) 统一作蜉蝣族，不是肯定者"),
    (r"\bLimbus\b|\bLimba's company\b|\blimbbus\b", ("边狱巴士", "边狱公司"), "Limbus Company 通行中文边狱巴士"),
]

AK_TERMS = {
    # --- 本片机翻英文残留 -> 官方中文 ---
    "AK": "明日方舟", "Ark Knights": "明日方舟", "Arknights": "明日方舟",
    "sanity": "理智", "LMD": "龙门币", "exp": "经验",
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
    "Reclamation": "生息演算",
    "Contingency": "危机合约",
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
    # 2026-11-08 沉淀（众生行记 OST reaction 片）：Arknights 的另一种谷翻直译；光环环球化=Halo Universalization 机翻直译
    "方舟战争": "明日方舟",
    "光环环球化": "Halo Universalization",
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
    # --- 2026-11-02 三校沉淀（EP17「相变临界」预告片反应片，394 cue，链 bi→ak）---
    # 凯尔希召唤物的**官方书写是 Mon3tr**（首字母大写、以 3 代 i）：游戏内「共享终端」线索原文
    # `◀ Mon3tr的线索`、「一枚方解石-Mon3tr的线索」。本片谷翻/自译曾整片写成小写 mon3tr（14 处），
    # 故补一条**大小写敏感**的裸键把规范机械固化进表（键≠值，不会自咬成 Mon3tr/Mon3tr）。
    # 「怪物/愈伤组织」这类常用中文词仍不入裸键，走 AK_CONTEXT 的 monster/callus 英文锚定。
    "mon3tr": "Mon3tr",
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
    # --- 2026-10-25 沉淀：《THESE ARKNIGHTS CN 7.5 ANNIVERSARY OPERATORS ARE UNREAL》 ---
    #   官方中文依据（2026-10-24 检索）：塔露拉/冻河/国度/奥尔佳/镜匠/行铃；
    #   将雪投火、卫戍协议「规程·序列I」、危机合约#6「弹雨作战」、
    #   沉沦者的黑流树海·内容拓展II、梦城堡、墨菲斯。
    #   只收 ASR/机翻错形；正确形不入表；国度为普通词，不设裸变体。
    "动合": "冻河", "动核": "冻河", "冻核": "冻河",   # 2026-11-11 移除裸键"冻和"：会咬"冰冻和眩晕"→"冰冻河眩晕"，改走冻河实体 ctx 锚定
    "塔罗拉": "塔露拉", "优斯塔露拉": "塔露拉",
    "中间寻访": "中坚寻访", "中间干员": "中坚干员",
    "中间市场": "中坚寻访", "中间甄选": "中坚甄选",
    # --- 2026-10-31 明日方舟 7.5 周年 reaction（Arknights 7.5 Anniversary is INSANE!，
    #   183 cue，英原声+谷翻，--ak）：谷翻系统性错形，只收长键；艺术/烧伤/腐蚀/障碍/
    #   瓷砖/格子 等裸词会误伤正常语境，禁入表，逐 cue 处理。
    "艺术伤害": "法术伤害",
    "艺术DoT": "法术持续伤害",
    "艺术攻击": "法术攻击",
    "艺术破坏": "法术伤害",
    "限量横幅": "限定寻访",
    "伏击专家": "伏击客",
    "原始守卫": "本源近卫",
    "原始防御者": "本源铁卫",
    # --- 2026-10-31 二次校准（同片，183 cue，--ak）：官方天赋/技能名核对后的专名与机制词 ---
    #   官方依据：行铃本名梅里塔/分支调度者（官方微博）；塔露拉「绝不妥协」「我即火焰」/
    #   「照霎白夜」「阂断骤雪」「日冕重烈」/「足迹」「簇火」；冻河「夜的哑然」「雪的印痕」/
    #   「一无所有之人」「意欲呼啸之心」「踽踽独行之春」；国度「国度」/「停步」「受戮」「无人的国度」。
    #   只收专名与多词长键；裸词（羽/火球/足迹/烧伤/腐蚀/障碍）不入表，走 ctx 或逐 cue。
    "梅丽塔": "梅里塔",
    "牧群钟声": "行铃",
    "卡莱多": "镜匠",
    "托斯卡": "冻河",
    "霍恩": "号角",
    "年轻的不锈钢": "年轻的白铁",
    "银灰圣物": "凛御银灰",
    "德克萨斯改变": "缄默德克萨斯",
    "卡尔西改变": "凯尔希·思衡托",
    "里德改变": "焰影苇草",
    "杰西卡改变": "涤火杰西卡",
    "星熊改变": "斩业星熊",
    "Lappy": "荒芜拉普兰德",
    "Zima Alt Story": "凛冬异格",
    "Zima Alt": "凛冬异格",
    "蒂蒂": "缇缇",
    "L2D 皮肤": "动态皮肤",
    "支援游侠": "游击手",
    "支持者原型": "辅助分支",
    "触发效应": "触发型效果",
    "超载效果": "过载效果",
    "燃烧爆发": "灼燃损伤爆发",
    "燃烧和元素损伤": "灼燃与元素损伤",
    "护卫教官": "近卫·教官",
    "火花成本": "兑换所需抽数",
    "黄色岩石皮肤": "源石皮肤",
    "记录恢复": "记录修复",
    "比例图见解": "比例手办",
    "联营旗帜": "联合行动寻访",
    "招聘干员": "公开招募干员",
    "Melitta": "梅里塔",
    "herd bells": "行铃", "Herd Bells": "行铃",
    "Caleido": "镜匠",
    "Toska": "冻河",
    "Primal Guard": "本源近卫", "primal guard": "本源近卫",
    "Primal Defender": "本源铁卫", "primal defender": "本源铁卫",
    "triggered effects": "触发型效果", "trigger effect": "触发型效果",
    "supportive ranger": "游击手", "Supportive Ranger": "游击手",
    "ambushed specialist": "伏击客", "Ambush Specialist": "伏击客",
    "instructor guard": "教官", "Instructor Guard": "教官",
    "burn damage": "灼燃损伤", "Burn damage": "灼燃损伤",
    "burn burst": "灼燃损伤爆发", "Burn burst": "灼燃损伤爆发",
    "arts damage": "法术伤害", "Arts damage": "法术伤害",
    "arts DoT": "法术持续伤害", "Arts DoT": "法术持续伤害",
    "green cert": "资质凭证",
    "joint operation": "联合行动", "Joint Operation": "联合行动",
    "assistant randomizer": "助理随机",
    "medal sets": "勋章套组",
    "scale figure": "比例手办",
    "artbook": "画集",
    "paradox simulation": "悖论模拟",
    "operator record": "干员密录",
    "record restoration": "记录修复",
    "spark cost": "兑换所需抽数",
    "SilverAsh alter": "凛御银灰", "SilverAsh Alter": "凛御银灰",
    "apple pie alter": "新约能天使", "Exusiai alter": "新约能天使",
    "Lappland alter": "荒芜拉普兰德",
    "Reed alter": "焰影苇草", "Jessica alter": "涤火杰西卡",
    "Hoshiguma alter": "斩业星熊", "Astgenne alter": "溯光星原",
    "Astgenne": "星源", "Mumu": "缪尔赛思",
    "Viviana": "薇薇安娜", "Alanna": "阿兰娜", "Catherine": "凯瑟琳",
    "CrownSlayer": "弑君者", "Eblana": "爱布拉娜", "Morpheus": "墨菲斯",
    "修度伤害": "灼燃损伤",
    "ending five": "第五结局",       # CJK+CJK 重复参考行无外文锚点，用长键兜底
    # --- 2026-10-28 ark_glossary.tsv 并入（128 行→本表 67 条；行号=原表行号，原表已归档）---
    # 依据：明日方舟官方中文（EN/ASR 误拼 → 官方中文）。只收专名/单义音译名；
    #   通用词（Terra/Operator/Reunion/Yan）走 AK_MISSING_CHECK 只体检不改写。
    "Originium": "源石",                                  # ark:12
    "Oripathy": "矿石病",                                 # ark:13
    "Sanity": "理智",                                     # ark:17（小写 sanity 已在表）
    "EXP": "经验",                                        # ark:19（小写 exp 已在表）
    "Elite": "精英化",                                    # ark:22（小写 elite 已在表）
    "Module": "模组",                                     # ark:25（小写 module 已在表）
    "Mystic Caster": "秘术师",                            # ark:28
    "Contingency Contract": "危机合约",                   # ark:30
    "Integrated Strategies": "集成战略",                  # ark:32
    "Reclamation Algorithm": "生息演算",                  # ark:38
    "Sankta": "萨科塔",                                   # ark:62
    "Sarkaz": "萨卡兹",                                   # ark:63
    "Reverse 1999": "重返未来：1999",                     # ark:133
    # 地名/国家
    "Rhodes Island": "罗德岛",                            # ark:10
    "Kazdel": "卡兹戴尔",                                 # ark:42
    "Lungmen": "龙门",                                    # ark:43
    "Chernobog": "切尔诺伯格",                            # ark:44
    "Ursus": "乌萨斯",                                    # ark:46
    "Victoria": "维多利亚",                               # ark:47
    "Kazimierz": "卡西米尔",                              # ark:49
    "Leithanien": "莱塔尼亚",                             # ark:50
    "Siracusa": "叙拉古",                                 # ark:51
    "Iberia": "伊比利亚",                                 # ark:53
    "Ægir": "阿戈尔",                                     # ark:54
    "Rim Billiton": "雷姆必拓",                           # ark:55
    "Bolívar": "玻利瓦尔",                                # ark:56
    "Sargon": "萨尔贡",                                   # ark:57
    "Minos": "米诺斯",                                    # ark:58
    "Karlan": "谢拉格",                                   # ark:59
    "Londinium": "伦蒂尼姆",                              # ark:60
    # 组织/阵营
    "Abyssal Hunters": "深海猎人",                        # ark:65
    "Penguin Logistics": "企鹅物流",                      # ark:66
    "Rhine Lab": "莱茵生命",                              # ark:67
    "Black Steel": "黑钢国际",                            # ark:68
    "Babel": "巴别塔",                                    # ark:69
    # 角色
    "Amiya": "阿米娅",                                    # ark:71
    "Kal'tsit": "凯尔希",                                 # ark:74
    "Kaltsit": "凯尔希",                                  # ark:75
    "Lappland": "拉普兰德",                               # ark:78
    "Vulcan": "火神",                                     # ark:82
    "Saria": "塞雷娅",                                    # ark:83
    "Sussurlo": "苏苏洛",                                 # ark:92
    "Purestream": "清流",                                 # ark:93
    "Wisadel": "维什戴尔",                                # ark:98
    "Nearl": "临光",                                      # ark:99
    "Ch'en": "陈",                                        # ark:101
    "Texas": "德克萨斯",                                  # ark:102
    "Exusiai": "能天使",                                  # ark:103
    "Siege": "推进之王",                                  # ark:104
    "Zima": "凛冬",                                       # ark:105
    "Ifrit": "伊芙利特",                                  # ark:106
    "Eyjafjalla": "艾雅法拉",                             # ark:107
    "Shining": "闪灵",                                    # ark:108
    "Nightingale": "夜莺",                                # ark:109
    "Skadi": "斯卡蒂",                                    # ark:110
    "Specter": "幽灵鲨",                                  # ark:111
    "Mudrock": "泥岩",                                    # ark:112
    "Rosmontis": "迷迭香",                                # ark:113
    "Ascalon": "阿斯卡纶",                                # ark:114
    "Patriot": "爱国者",                                  # ark:116
    "FrostNova": "霜星",                                  # ark:118
    "Faust": "浮士德",                                    # ark:119
    "Mephisto": "梅菲斯特",                               # ark:120
    "Surtr": "史尔特尔",                                  # ark:121
    "Blemishine": "瑕光",                                 # ark:122
    "Degenbrecher": "锏",                                 # ark:124
    "Muelsyse": "缪尔赛思",                               # ark:128
    # --- 2026-10-31 明日方舟 × 韵律源点（Arcaea）联动 reaction（DREAM COLLAB!）---
    #   官方依据：Arcaea 中文名「韵律源点」（2026-02-13 官方公告）；Kou=红、Titi=缇缇、
    #   Liino=梨诺、Kal'tsit alter=凯尔希·思衡托、Specter alter=归溟幽灵鲨；
    #   CC 曲目 Operation Basepoint=起源行动、Operation Blade=利刃行动、Operation Pyrite=黄铁行动、
    #   Operation Dawnseeker=寻昼行动；All hail Savior!、ManiFesto:、冲破穹顶（理想城OST）。
    #   戒律：Coal/Kou/TT/Linus/Pepper/Cookie/Lowlight/Pyrite/Play 等普通词或短名只走 AK_CONTEXT；
    #   带括号曲名不做「英文名→带括号名」裸键，防自嵌套。
    "Arcaea": "韵律源点", "Arcea": "韵律源点",
    "阿尔凯亚": "韵律源点", "阿尔西亚": "韵律源点",
    "Endfield": "终末地", "Enfieldy": "终末地风格", "Endfieldy": "终末地风格",
    "恩德菲尔德": "终末地",
    "Amiya": "阿米娅", "Gavial": "嘉维尔", "Pepe": "佩佩", "Titi": "缇缇",
    "Kal'tsit alter's": "凯尔希·思衡托", "Kaltsit alter's": "凯尔希·思衡托",
    "Kal'tsit alter": "凯尔希·思衡托", "Kal'tsit Alter": "凯尔希·思衡托",
    "Specter alter": "归溟幽灵鲨",
    "Relaunch Anchor": "重启锚点", "Orienteering banner": "定向寻访卡池",
    "Contingency Contract": "危机合约",
    "Don't Seeker": "《Operation Dawnseeker》（寻昼行动）",
    "Dont Seeker": "《Operation Dawnseeker》（寻昼行动）",
    "Base Point": "《Operation Basepoint》（起源行动）",
    "All Hail the Savior": "《All hail Savior!》",
    "Manifesto": "《ManiFesto:》",
    "Breakthrough the Dome": "《冲破穹顶》",
    "Honkai Impacted": "《崩坏3》", "Star Ocean": "《星之海洋》", "Destiny 2": "《命运2》",
    "Ideal City": "《理想城》",
    # --- 2026-11-08 明日方舟 × 韵律源点 联动歌单 reaction（kukkikaze，204 cue，英声+谷翻）---
    #   官方依据：TapTap 韵律源点官方公告（2026-11-03）+ Arcaea 中文维基 + PRTS。
    #   谷翻固定误译：trailer→「拖车/拖车光伏」（通用性强）；IS5 现有表只有 IS-5/IS6 等，缺无连字符形。
    #   戒律：Aikatsu（动漫 IP 名）/门萨（IQ 组织）/网络导弹/老虎莉莉/凡人/Ajurika/Nekomancer
    #   全是普通词或专名短形，一律只走 AK_CONTEXT，禁止裸键。
    "拖车光伏": "预告 PV", "拖车 PV": "预告 PV",
    "IS5": "集成战略5",
    # --- 2026-11-10 明日方舟 7.5 周年反应片（WE FINALLY GET TALULAH!，228 cue，英声+微软翻，--ak）---
    #   官方依据：references/Arknights_Lore_Terminology 364 行 Talulah=塔露拉、791 行 Emperor's Blade=皇帝的内卫；
    #   2026-11-10 检索：塔露拉=限定六星近卫·本源近卫；冻河=Toska 辅助·游击手；Horn 官方=号角（烘焙皮肤即主播口中的 Granny）。
    "塔卢拉": "塔露拉",    # AK_KO_TERMS 2026-09-10 同键补齐 --ak 侧
    "塔布拉": "塔露拉",    # ASR Tabula 变体（#119 got to get Tabula）
    "皇帝之刃": "皇帝的内卫",    # references 791（#33 emperor's blade）
    "支持性的游侠": "游击手",    # supportive ranger=游击手官方分支（冻河）；同系列上片键"支援游侠"的本片微软翻变体
    "操作员": "干员",    # operator 机翻误译（#117 must pull operators）；--ak 模式隔离，编程语境不入其他表
    # --- 2026-11-10 二校（同片 228 cue 机器查漏+人工裁决补齐）---
    "警卫操作员": "近卫干员",    # guard operator：Guard 官方职业=近卫；长键降序优先于短键"操作员"，#73 终态近卫干员
    # --- 2026-11-11 明日方舟《Should You Save for Talulah?》（FrostByte262，130 cue，英声+谷翻，--ak）二次校准沉淀 ---
    #   官方依据：PRTS 塔露拉页（照霎白夜/阂断骤雪/日冕重烈/庇护/簇火/足迹）、萌百/百科（妮芙/酒神/波卜/烛煌）、
    #   官方微博 #冻河# #费奥多尔#（Fyodor=冻河本名）；参考件 ChatGLM 克莱门莎片校准对话（2026-11-11 提取）。
    #   新干员实体注册在 entities_part2.py（仅元数据，沿用镜匠/行铃模式），错形键直写本表；普通词错形走 AK_CONTEXT 锚定。
    "克莱门蒂亚": "克莱门莎", "克莱门西亚": "克莱门莎", "Clementia": "克莱门莎",  # 2026.10.9「昨日海」6★本源近卫
    "妲露拉": "塔露拉",    # ASR 变体（#88）
    "Nymph": "妮芙",       # 6★本源术师，凋亡损伤，S2 恐惧（2024.7）
    "Tragodia": "酒神", "特蕾迪亚": "酒神",  # 6★辅助巫役，傀影异格（2025.6.5）；misc MERGE_FIXES 同键互不冲突
    "Bobbing": "波卜",     # 5★辅助巫役，本名埃利西奥，灼燃远程拐（2024.10 追迹日落以西）
    "Ho'olheyak": "霍尔海雅", "霍尔海亚": "霍尔海雅",  # 6★术师（AK_JA_TERMS 已有，补 --ak 侧）
    "Stainless": "白铁",   # 6★术师，S3 炮塔（bi ENT 已有，补 --ak 侧）
    "Blaze alter": "烛煌", "Blaze S3": "烛煌S3",  # 2025 春节本源术师，灼燃弹药机制
    "SP buff": "技力增益",  # SP=技力（#49）
    "回收算法": "生息演算",  # Reclamation Algorithm 中文直译错形（--ak 隔离，编程语境不入）
    "艺术损害": "法术伤害", "艺术损坏": "法术伤害",  # arts damage 谷翻变体（艺术伤害已有）
    "IS 5": "集成战略5",   # IS5 带空格形（IS5 已有）
    # --- 2026-11-11 明日方舟《Clementia VS Potential Woman｜Who is Better?》（FrostByte262，142 cue，英声+谷翻，--ak）校准沉淀 ---
    #   官方依据：PRTS 伯塔尼/余页、参考件 ChatGLM 克莱门莎片精校对话（2026-11-11 提取，官方名词已查证）。
    #   通用词错形（老板/才华/圣所/车道/垃圾邮件/水昌黎等）走 AK_CONTEXT 锚定；语法级重写逐 cue。
    "克莱门蒂娅": "克莱门莎",  # 谷翻变体（克莱门蒂亚已有）
    "塔鲁拉": "塔露拉",        # ASR 变体（#97）
    "Talulah": "塔露拉", "talulah": "塔露拉",  # 中文行拉丁残留（#29/48/59/65/102/125/132）
    "Botani": "伯塔尼",        # 5★辅助·巫役（侵蚀），「人们，我们」活动赠送（PRTS 2026-11-11 核实）
    "原始警卫": "本源近卫",    # primal guard 谷翻变体（原始守卫已有，#3）
    "IS模式": "集成战略",      # IS mode（#105/133）；长键安全，产出不含自身
    "sp成本": "技力消耗",      # sp cost（#90）；SP=技力
}

# =============================================================
# 3.1c AK_CONTEXT：明日方舟**双语**片源（英文原声 + 谷歌翻译中文行）的条件变体。
# 2026-10-06 新增能力：此前 --ak 只有无条件表（AK_TERMS），凡是"普通中文词义错位"
#   都无法安全沉淀——裸键必然跨片源误伤（例：寒冷/乐观/声音/空缺/一切幻想）。
#   本表以**英文参考行正则**锚定，与 bi 的 CONTEXT_MAP 同构，但只在 --ak 生效。
# 戒律：错形必须是**正常中文词**（字面义误译），且能由参考行唯一佐证；
#   非词错形（音译残留/英文残留）仍走 AK_TERMS 裸键，不入本表。
#   整句语序问题（断句跨 cue、修饰语错位）本表无解，仍走 subfix。
#   注意：CJK+CJK 重复行（参考行也是中文）没有外文参考，ctx 规则不生效；
#   这类错形走 AK_TERMS 长键或逐 cue subfix（如 ending five / cc）。
# 用法：python subtitle_calib_merged.py <in.srt> --ak --out out.srt
# =============================================================
AK_CONTEXT = [
    # 2026-11-10 二校沉淀（《This Is Gacha Worldbuilding at Its Peak》，1004 cue）：
    #   泰拉/伊比利亚/黎博利/萨科塔/叙拉古/汐斯塔/萨尔贡/萨卡兹/乌萨斯/高卢帝国/
    #   卡西米尔/鹰角网络/矿石病/天灾/天灾信使/源石技艺/移动城市/四皇会战/
    #   世界观构建 等条目按项目约定追加在 data/entities_part2.py 的
    #   「2026-11-10 二校沉淀」段（modes=("ak",) / ("ak","limbus")），
    #   由 _register_entities 投影回 AK_TERMS/AK_CONTEXT；本文件不作为重复登记点。
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
    (r"\btalents?\b", "才华", "天赋"),               # #19 talent=明日方舟机制"天赋"；2026-11-11 补复数 talents（Clementia VS 片 #29 漏命中）
    (r"true damage", "真伤害", "真实伤害"),         # #21 true damage 官方=真实伤害
    (r"(?<!damage )\bpotential\b", "潜力", "潜能"),   # #54 potential=明日方舟"潜能"；2026-11-11 二校排除 damage potential（伤害潜力，Clementia VS 片 #97 误伤根因；锚点经空白规整，定宽 lookbehind 可用）
    (r"\bspecter alter\b", "幽灵变形", "归溟幽灵鲨"),  # #55 Specter alter 官方=归溟幽灵鲨
    (r"\bgavial alter\b", "加维尔", "百炼嘉维尔"),  # #56 Gavial alter 官方=百炼嘉维尔
    (r"\bspark\b", "火花", "黄票兑换"),             # #55 spark cost=黄票兑换消耗
    (r"\brate up\b", "卡率提升", "概率提升"),       # #53 rate up
    (r"\benablers?\b", "纵容者", "损伤拐"),        # #47 enabler；2026-11-11 统一口径 启动器→损伤拐（社区通用语，参考件全片用此）
    (r"\benablers?\b", "推动者", "损伤拐"),        # 2026-11-11 谷翻"元素推动者/实际推动者"
    (r"\benablers?\b", "推动器", "损伤拐"),        # 2026-11-11 谷翻"射程推动器"
    (r"\benablers?\b", "促成者", "损伤拐"),        # 2026-11-11 备形
    (r"\benablers?\b", "启动器", "损伤拐"),        # 2026-11-11 旧目标形回滚（前向修正）
    (r"\benablers?\b", "促成因素", "损伤拐"),      # 2026-11-11 Clementia VS 片 #22/24 谷翻变体
    (r"\brerun\b", "重播的皮肤", "复刻皮肤"),       # #59 rerun skins
    (r"\bstages\b", "各个阶段", "各个关卡"),        # #62 examine the stages
    (r"\bstages\b", "赛段", "关卡"),                # #78 The stages will also have
    (r"[Ee]pisode 17", "第17集", "第17章"),         # #63 主线 episode=章节
    (r"\bepisode\b", "这一集", "这一章"),           # #74 this episode
    (r"\bboss(?:es)?\b", "老板", "Boss"),             # #81 As for the boss；2026-11-11 补复数 bosses（Clementia VS 片 #72/111/120 漏命中）
    # 2026-11-08：Crywolf（曲师）谷翻直译"狼来了"；狼来了是普通成语，禁裸键，靠参考行 Cry wolf 锚定
    (r"[Cc]ry\s*wolf", "狼来了", "Crywolf"),
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
    (r"\belemental\s+injur", "元素伤害", "元素损伤"),  # #89 elemental injury=元素损伤；2026-11-11 二校收窄：官方口径积累=损伤、爆发数值=伤害，elemental damage（爆发/buff语境）不再误改（Clementia VS 片 #12/110/118 误伤根因）
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
    # 2026-11-11 删除笔误锚 \bbenablers?\b（永不命中 enabler，与 :768 正确锚重复）
    # --- 2026-10-25 沉淀：7.5 周年前瞻 reaction（官方中文 + 英文参考行锚定）---
    #   戒律：错形是普通中文词/短英文，必须由参考行唯一佐证；不恢复 XP/RA/CC 裸键。
    (r"\bTexas (?:out|alter)\b", "德克萨斯州", "缄默德克萨斯"),  # #176/#179 Texas out=Texas alter
    (r"(?i)\bCNY? banner\b", "新年横幅", "国服卡池"),              # #184 ASR 把 CN 听成 CNY
    (r"\bglobal (?:race|range) skill\b", "全球比赛技能", "全图攻击技能"),  # #82 global race=range
    (r"\bglobal range\b", "全局范围", "全图范围"),                 # #161
    (r"\bannihilation\b", "湮灭", "剿灭"),                         # #435 Annihilation=剿灭
    (r"\bStrong\s*hold\b|\bStrong hole\b", "强洞", "据点"),        # #429 Stronghold
    (r"\bending five\b", "ending five", "第五结局"),               # #446 IS ending five
    (r"\bfoul beast\b", "邪恶的野兽", "污秽兽"),                   # #283 Terra Fact
    (r"\bXP\b", "XP", "经验"),                                     # 仅独立 XP；不再命中 EXP
    (r"\bRA\b", "RA", "生息演算"),                                 # 仅独立 RA；不再命中 SSHELLEOPERATE
    (r"(?i)\bcc\b", "cc", "危机合约"),                             # 仅独立 cc；不再命中 GUCCIGUCCI
    (r"(?i)\bcc\b", "CC", "危机合约"),
    (r"\bCC effects?\b", "危机合约效果", "控制效果"),  # 2026-11-11 CC effects=crowd control 控制效果（回滚 CC→危机合约 误伤，#111）
    # --- 2026-11-11 《Should You Save for Talulah?》普通中文词义错位（参考行锚定）---
    (r"\bsanctuary\b", "庇护所", "庇护"),          # #56 塔露拉 S2「阂断骤雪」/余天赋「礼尚往来」官方=庇护
    (r"\bStainless\b", "不锈钢", "白铁"),          # #104 Stainless 官方=白铁
    (r"\bbobbing\b", "摇摆", "波卜"),              # #20 Bobbing=波卜（谷翻"摇摆"）
    (r"\bReed\b", "里德", "苇草"),                 # #22 Reed 官方=苇草
    (r"\bblock count\b", "区块计数", "阻挡数"),    # #12 block count 官方=阻挡数
    (r"\bblock count\b", "方块数", "阻挡数"),      # #61
    (r"\bhigh res\b", "高分辨率", "高法抗"),       # #27 high res=高法术抗性
    (r"\blow res\b", "低分辨率", "低法抗"),        # #38
    (r"\bresistance\b", "抵抗力", "法术抗性"),     # #17/25/39/93（阻力形已有）
    (r"\bfrozen\b", "冰冻", "冻结"),               # #112 frozen 官方=冻结
    (r"\btrash\s+mob\b", "垃圾暴徒", "杂兵"),      # #72 trash mob=杂兵
    (r"\bburning tiles?\b", "格子", "足迹"),    # #33/34/37 塔露拉 S2 天赋地面火焰官方=足迹（tile→格子 已有，级联再转足迹）
    (r"\bfireballs?\b", "火球", "簇火"),        # #76/79/87/89 塔露拉 S3「日冕重烈」火焰弹官方=簇火
    # --- 2026-11-11 《Clementia VS Potential Woman｜Who is Better?》普通中文词义错位（参考行锚定）---
    (r"\bsanctuary\b", "圣所", "庇护"),            # #87 塔露拉 S2 官方=庇护（庇护所形已有）
    (r"[Hh]ydro mommy", "水力妈妈", "水系妈妈"),   # #30 主播对克莱门莎的戏称（Hydro mommy）
    (r"[Hh]ydro mommy", "Hydro妈咪", "水系妈妈"),  # #123 同戏称中英混排形
    (r"(?i)water Changli", "水昌黎", "水系长离"),  # #139 克莱门莎戏称=鸣潮长离的水版（音译残留）
    (r"burn enabler", "刻录使能器", "灼燃损伤拐"), # #121 burn enabler 谷翻直译
    (r"\blane\s+hold", "车道保持", "守路"),        # #53/54 lane holding=守路（玩法术语）
    (r"\blane\s+hold", "对线", "守路"),            # #134 同语境谷翻变体
    (r"solo lane", "单独车道", "单守一路"),        # #54 solo lane
    (r"\bspamable\b", "是垃圾邮件", "可以频繁释放"), # #90 spamable 谷翻直译（整短语锚定防误伤）
    # --- 2026-10-31 明日方舟 × 韵律源点联动 reaction ---
    #   普通词/短名/歧义曲名只走参考行锚定；wrong 是机翻中文或保留英文形。
    (r"\bArcaea\b", "阿卡亚", "韵律源点"),
    (r"(?<!mobile )\bapps?\b", "应用程序", "音弧"),
    (r"\barcs?\b", "弧线", "音弧"),
    (r"\bnotes?\b", "注释", "音符"),
    (r"\bvertical scrolling\b", "垂直滚动", "垂直下落式"),
    (r"\bcharting\b", "图表", "谱面"),
    (r"\bCoal\b", "煤炭", "红"),
    (r"\bCoal\b", "煤", "红"),
    (r"\bKou\b", "寇", "红"),
    # 2026-10-31 7.5 周年二次校准：\bTT\b 不匹配 TTS（原 \bTT'?s?\b 会把 TTS 咬成「缇缇S」）
    (r"\bTT\b", "TT", "缇缇"),
    (r"\bYu\b", "羽", "余"),
    (r"\bYu\b", "禹", "余"),
    (r"\bapple pie alter\b", "苹果派", "新约能天使"),
    (r"\bLinus'?\b", "Linus", "梨诺"),
    (r"\bLinus'?\b", "利诺", "梨诺"),
    (r"\bPepper'?s?\b", "Pepper", "佩佩"),
    (r"\bPepper'?s?\b", "佩珀", "佩佩"),
    (r"how could you not name", "库奇", "Kukki"),
    (r"how could you not name", "Cookie", "Kukki"),
    (r"\bLow Light\b", "Low Light", "海猫"),
    (r"\bLowlight\b", "Lowlight", "海猫"),
    (r"\bPyrite\b", "黄铁矿", "《Operation Pyrite》（黄铁行动）"),
    (r"\bPlay,\s*Pyrite\b", "播放", "《Operation Blade》（利刃行动）"),
    (r"\bPlay,\s*Pyrite\b", "Play", "《Operation Blade》（利刃行动）"),
    (r"\bBase Point\b", "基点", "《Operation Basepoint》（起源行动）"),
    (r"\bBase Point\b", "基点行动", "《Operation Basepoint》（起源行动）"),
    (r"\bDon'?t Seeker\b", "不要寻找者", "《Operation Dawnseeker》（寻昼行动）"),
    (r"\bDon'?t Seeker\b", "别寻找者", "《Operation Dawnseeker》（寻昼行动）"),
    (r"\bRadiant\b", "光辉灿烂", "《Radiant》"),
    (r"\bRadiant\b", "光辉", "《Radiant》"),
    (r"\bGranite Gate\b", "花岗岩之门", "《Granite Gate》"),
    (r"\bManifesto\b", "宣言", "《ManiFesto:》"),
    (r"\bCry of Dawn\b", "黎明之声", "Cry of Dawn"),
    (r"\bAll Hail the Savior\b", "万岁", "《All hail Savior!》"),
    (r"\bAll Hail the Savior\b", "救主", "《All hail Savior!》"),
    (r"\bBreakthrough the Dome\b", "突破穹顶", "《冲破穹顶》"),
    (r"\bSystem Malfunction\b", "系统故障", "《System Malfunction》"),
    (r"\bAwaken\b", "觉醒", "《Awaken》"),
    (r"\bMystic Light Quest\b", "神秘之光之旅", "《Mystic Light Quest》"),
    (r"\bHonkai Impact(?:ed)?\b", "《崩坏》", "《崩坏3》"),
    (r"\bDestiny 2\b", "《命运 2》", "《命运2》"),
    (r"\bspecter alter\b", "幽灵鲨异格", "归溟幽灵鲨"),
    # --- 2026-11-08 明日方舟 × 韵律源点 联动歌单 reaction（kukkikaze，204 cue）---
    #   本片 ASR 把 Arcaea 一路听成 Aikatsu（动漫 IP 名，禁裸键）与「爱胜」；
    #   顺序敏感：联动全名 → staff（指方舟团队）→ 其余一律按韵律源点。改动顺序会让规则互相吃掉，勿重排。
    #   目标形必须用权威裸形「明日方舟 / 韵律源点」（不带书名号），否则 kb-lint 报双规范冲突。
    (r"\bAikatsu\s*x\s*Aikatsu\b", "Aikatsu x Aikatsu", "明日方舟×韵律源点"),
    (r"\bAikatsu\s+staff\b", "Aikatsu", "明日方舟"),
    (r"\bAikatsu\b", "爱胜", "韵律源点"),
    (r"\bAikatsu\b", "Aikatsu", "韵律源点"),
    #   曲师/曲名：官方 8 曲表（cybermiso / tigerlily / AJURIKA / Somniomancer [null set]）。
    #   ⚠ 锚点必须写 ASR 原形（Cyber Missile / Tiger Lily），写官方拼写不会命中——实测踩过。
    (r"\bCyber\s+Missile\b", "网络导弹", "cybermiso"),
    (r"\bTiger\s+Lily\b", "老虎莉莉", "tigerlily"),
    (r"\bAjurika\b", "阿朱里卡", "AJURIKA"),
    (r"\bJurika\b", "Jurika", "AJURIKA"),
    (r"\bNekomancer\b", "Nekomancer", "Somniomancer [null set]"),
    #   方舟×太鼓之达人（2025-07-22）拿到皮肤的是桃金娘（Myrtle）；ASR 把 Myrtle 听成 mortal。
    (r"\bmortal\s+Taiko\s+skin\b", "凡人太鼓皮肤", "桃金娘的太鼓联动皮肤"),
    #   主播说的「双 CC」实为黄铁行动/利刃行动，谷翻把 Pirate/Blade 直译成海盗与刀锋。
    (r"\bPirate\s+and\s+Blade\b", "《海盗与刀锋》", "黄铁行动和利刃行动"),
    (r"\bPirate\s+and\s+Blade\b", "《海盗》和《刀锋战士》", "黄铁行动和利刃行动"),
    #   Mensa 是 IQ 组织名（禁裸键）；本片指官方曲「……已至。」（官方 8 曲表第 1 首）。
    (r"\bMensa\b", "门萨", "「……已至。」"),
    #   2026-11-10 Talulah 反应片（228 cue，英声+微软翻，--ak）：主播读新干员名 Toska 被 ASR 写为
    #   Taka，微软翻把「高」落在中文行；冻河=Toska（俄语 Тоска），辅助·游击手分支（2026-11-10 检索）。
    (r"\btaka\b", "高", "冻河"),          # #90 Taka=冻河 ASR 变体
    #   主播用 Granny 称 Horn（烘焙皮肤），微软翻直译「奶奶」；锚定参考行 granny 才改。
    (r"\bgranny\b", "奶奶", "号角"),      # #135-136 Granny=Horn 官方名号角
    #   2026-11-10 二校（同片）：trailer 机翻固定错译「拖车」——裸键不入（通用性强，2026-11-08 戒律），锚参考行才改。
    (r"\btrailers?\b", "拖车", "预告片"),      # #52/#56 this trailer
]

# =============================================================
# 3.1d AK_MISSING_CHECK：明日方舟**漏译体检**规则（只报不改）。
#   2026-10-28 由 ark_glossary.tsv 并入（原表已归档）。英语里同时是普通词的官方专名
#   （Terra/Operator/Reunion/Yan）绝不进 AK_TERMS 裸键，只能在此按英文参考行体检，
#   命中后由人工判断是否逐 cue 修。与 ENDFIELD_MISSING_CHECK / WUWA_MISSING_CHECK 同构，
#   由 `--mode ak` 的 verify/lint 装载（见 inspect._load_missing_rules）。
#   XP/RA/CC 已有 AK_CONTEXT 条目，不在此重复。
# =============================================================
AK_MISSING_CHECK = [
    (r"\bTerra\b", ("泰拉",), "Terra 官方中文=泰拉（ark_glossary.tsv:11）"),
    (r"\bOperator\b", ("干员",), "Operator 官方中文=干员（ark_glossary.tsv:14）"),
    (r"\bReunion\b", ("整合运动",), "Reunion 官方中文=整合运动（ark_glossary.tsv:45）"),
    (r"\bYan\b", ("炎",), "Yan 官方中文=炎（ark_glossary.tsv:48）；单字低置信，命中请人工确认"),
]

AK_KO_TERMS = {
    # --- 角色名：夜刀(야토) ---
    "雅托": "夜刀", "矢藤": "夜刀", "亚托": "夜刀", "Yato": "夜刀",
    "夜斗": "夜刀", "矢富": "夜刀", "亚托娜": "夜刀",
    # --- 阵营/地名：叙拉古(시라쿠사)、德克萨斯(텍사스) ---
    # ⚠ "拉普兰"→拉普兰德 不入本表：_replace_report 是逐键 str.replace（产出会被后续短键
    #   再扫），底稿含正确形"拉普兰德"时被"拉普兰"键咬成"拉普兰德德"（433강 r2 幂等回归实测
    #   2 处；自映射键在本实现下只做 no-op 挡不住）。改走 AK_KO_CONTEXT 哨兵路径（라플란드 佐证）。
    "锡拉丘兹": "叙拉古", "锡拉库扎": "叙拉古", "雪城": "叙拉古",
    "德克萨斯州": "德克萨斯",
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
    # --- 游戏名：明日方舟(명방=명일방주 缩写)谷翻错形群（433강 OST 월드컵 1일차 2026-11-10）---
    #   이 명방→"李明邦"(cue2)、명방→"明邦"(cue660/730)、"明房"(cue201/410/515/661/662/1009/1138/1208/1210)、
    #   "Mungbang"(cue526 림버스랑 명방 콜라보)；명방사계="明日方舟四季"(cue201 与 비발디《四季》并列)、
    #   명방식="明日方舟式"(cue202，与"明房/明邦"同存靠长键先行)；
    #   "명방노래"意译形"名曲/著名的歌曲/著名的房间"等不入裸键，走 subfix 侧车整行覆盖(cue487/490/524/532/667/1021/1025/1210)。
    "李明邦": "明日方舟", "明邦": "明日方舟", "明房": "明日方舟",
    "明房寺": "明日方舟四季", "Mungbang": "明日方舟",
    # --- 游戏名：终末地(엔필=엔드필드 缩写)谷翻错形群（433강 同上）---
    #   엔필→"N.P.I.L."(cue515/660)/"恩皮尔"(cue518/525/657/670)/"Enpil"(cue655/656)/"N.Pil"(cue657)、
    #   엔드필드→"恩菲尔德"(cue1094/1096)、英文残留"Endfield"(cue639)；무릉 罗马字"Mureung"→武陵
    #   (endfield.py 已收五菱/武林/乌岭 等中文形，此处补罗马字形，cue659)；"端场"(cue1446) 歧义字走 AK_KO_CONTEXT。
    "N.P.I.L.": "终末地", "N.Pil": "终末地", "恩皮尔": "终末地",
    "Enpil": "终末地", "恩菲尔德": "终末地", "Endfield": "终末地",
    "Mureung": "武陵",
    # --- 433강 OST 월드컵 1일차 二校（2026-11-10）：官方中文补漏 ---
    #   角色/种族/势力：能天使(엑시아)、杰西卡(젠시카)、萨卡兹(살카즈)、红豆(비그나)、
    #   特雷西斯(테레시스)、罗德岛(로도스 아일랜드)、边狱巴士(림버스)。
    #   ⚠ "Limbus Company" 必须排在 "Limbus" 之前，否则短键会留下 "边狱巴士 Company"。
    "艾克希亚": "能天使", "艾克西亚": "能天使",
    "詹西卡": "杰西卡",
    "萨尔卡兹": "萨卡兹",
    "比格纳 (Bigna)": "红豆",
    "比格纳": "红豆",
    "Bigna": "红豆",
    "特蕾西斯": "特雷西斯",
    "罗多顿岛": "罗德岛",
    "Limbus Company": "边狱公司",
    "Limbus": "边狱巴士",
    "NeverGiveUp": "Never Give Up",
    "Day by die day by day": "Day by Day",
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
    # --- 433강 OST 월드컵 1일차（2026-11-10）---
    (r"엔드필드", "端场", "终末地"),          # cue1446 엔드필드에서도 잘려서；"端场"裸键有歧义，靠韩语行佐证
    (r"명방식", "明植", "明日方舟式"),        # cue202 명방식 비발디=明日方舟式维瓦尔第
    # 原 AK_KO_TERMS"拉普兰→拉普兰德"迁移至此（2026-11-10 433강）：wrong⊂right 走 _ctx_replace
    # 哨兵，既有正确形"拉普兰德"不被再咬；128강 沉淀键，佐证 라플란드/라플란（cue303/327 等）。
    (r"라플란드|라플란", "拉普兰", "拉普兰德"),
    # --- 433강 OST 월드컵 1일차 二校（2026-11-10）：事件/歌曲/歧义专名，全部韩语行锚定 ---
    #   事件名：莱茵生命(라인랩)、愚人号(스툴티페라)、尘影余音(링거링 에코즈)、
    #   孤星(론트레일)、相见欢(상견완)、画中人(화중인)。
    #   歌曲名：春弦(스프링스 펄스)、Somniomancer [null set](썸뉴어멘서)、
    #   Last of Me(라스트 오브 미)、Across the Wind(어크로스 더 윈드)、
    #   Reversed Time(리버스드 타임)、日落即逝(Alive Until Sunset)。
    #   角色/歧义词：紫野遥(하루카)、真言(만트라)、阿米娅(아미아)、红豆(비그나)、
    #   能天使(엑시아)、杰西卡(젠시카)、萨卡兹(살카즈)、妮姬(니케)、
    #   边狱巴士(림버스)、整合运动(리유니온)、特蕾西娅(트레샤)、罗德岛(로도스 아일랜드)、空弦(알케또)。
    (r"라인랩", "Line Rap", "莱茵生命"),
    (r"라인랩", "Line Lab", "莱茵生命"),
    (r"스툴티페라", "凳子自卸车", "愚人号"),
    (r"스툴티페라", "油菜花", "愚人号"),
    (r"스툴티페라", "斯图尔蒂费拉", "愚人号"),
    (r"스툴티페라", "Stultifera Navis", "愚人号"),
    (r"링거링 에코즈", "Ringer Ringing Echoes", "尘影余音"),
    (r"링거링 에코즈", "铃声", "尘影余音"),
    (r"론트레일", "Lone Trail 发射台", "孤星发射台"),
    (r"론트레일", "Lone Trail", "孤星"),
    (r"상견완", "尚延湾", "相见欢"),
    (r"상견완", "Sanggyeonwan", "相见欢"),
    (r"상견완", "会议", "相见欢"),
    (r"화중인", "华静仁", "画中人"),
    (r"화중인", "华津仁", "画中人"),
    (r"화중인", "花中人", "画中人"),
    (r"스프링스 펄스|스프링 펄스", "弹簧脉冲", "春弦"),
    (r"스프링스 펄스|스프링 펄스", "Sprinkle Pulse", "春弦"),
    (r"스프링스 펄스|스프링 펄스", "Sprin Pulse", "春弦"),
    (r"스프링스 펄스|스프링 펄스", "Springs Pulse", "春弦"),
    (r"썸뉴어멘서|썸미오멘서", "Amencer Nullset", "Somniomancer [null set]"),
    (r"썸뉴어멘서|썸미오멘서", "染米·奥曼瑟", "Somniomancer [null set]"),
    (r"아미아", "Amia", "阿米娅"),
    (r"만트라", "Mantra", "真言"),
    (r"만트라", "曼陀罗", "真言"),
    (r"하루카", "Haruka", "紫野遥"),
    (r"엑시아", "艾克希亚", "能天使"),
    (r"젠시카", "詹西卡", "杰西卡"),
    (r"살카즈", "萨尔卡兹", "萨卡兹"),
    (r"림버스", "角膜缘", "边狱巴士"),
    (r"림버스", "Limbus Company", "边狱公司"),
    (r"림버스", "Limbus", "边狱巴士"),
    (r"림버스", "林布斯", "边狱巴士"),
    (r"니케", "耐克", "妮姬"),
    (r"니케", "Nike", "妮姬"),
    (r"니케", "尼克", "妮姬"),
    (r"AUS|Alive Until Sunset", "AUS", "日落即逝"),
    (r"리유니온", "Reunion", "整合运动"),
    (r"리유니온", "团圆", "整合运动"),
    (r"트레샤", "特雷莎", "特蕾西娅"),
    (r"테레시스", "特蕾西斯", "特雷西斯"),
    (r"로도스 아일랜드|로돠스 아일랜드", "罗多顿岛", "罗德岛"),
    (r"알케또|아르케토", "Alketo", "空弦"),
    (r"라스트 오브 미", "最后的我", "Last of Me"),
    (r"라스트 오브 미", "最后生还者", "Last of Me"),
    (r"어크로스 더 윈드", "乘风破浪", "Across the Wind"),
    (r"리버스드 타임", "倒转时间", "Reversed Time"),
    # 歌曲名误伤回滚：Sami/Terra 先被裸键改成萨米/泰拉，再按韩语歌名还原英文。
    #   《Sami Longla》(cue278)、Terra Bob(cue1454) 是曲名/组合名，不是萨米/泰拉。
    (r"사미룡라", "萨米", "Sami"),
    (r"테라밥", "泰拉", "Terra"),
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
# 선정되다(被选定)/선정하다(选定) 等动词·形容词用法，另排除 선정순(选拔顺序) 这类**名词用法**
# （2026-11-02 实测：鸣潮韩语直播 #5421「팀 선정순이나 팀장 인기 순」=按队伍选拔顺序，
#   被 选拔->璇情 咬成「队伍璇情顺序」；선정 同时是「选拔」这个普通汉语词与角色名，必须双向排除），
# 只留人名（#1015/#2570/#2612 实测）。
_SEONJEONG_ANCHOR = r"선정(?!(적인|적\b|되|했|하니|할|하겠|한다|되는|순))"


# =============================================================
# 2026-11-03 新增：--akja（日语原声·明日方舟）
#   片源：《【#アークナイツ】完全初見で始めたら沼すぎるだろ！…》奈渡ナオト 首播，
#         3856 cue / 4:23:29，每 cue 恰 2 文本行（首中文 + 末日语参考行），CRLF 无 BOM。
#   与 --ak 的分工判据（一句话）：**这个错形会不会出现在英语原声片源里？**
#     · 会（英语 ASR/英文残留驱动：Kelsey、mon3tr、Ifrit、Specter alter…）→ 留 AK_TERMS/AK_CONTEXT；
#     · 不会（日语驱动：片假名音译串、同音汉字误听、旧字体直搬、谷翻把カタカナ写成的拉丁串）→ 进本表；
#     · 两边都产出的同一错形 → 只登记一处（AK_TERMS），本表不重复（已实测同名键 0 条）。
#     · 运行期 engine 用 AK_TERMS ∪ AK_JA_TERMS 的**合并表单次编译**（长键降序单遍扫描），
#       因此两表之间的互相咬键不由 terms-check 覆盖，改由 _calib_nawaton/r2/xtable_check.py 机检。
#   ⚠ 硬契约第 4 条：正常中文词（天灾/标志/徽标/喇叭/团聚/医生/模块/小苏打/流星/坐标/成本/
#     深渊/冰霜新星…）**绝不做裸键**，一律进下面 AK_JA_CONTEXT 用**日语参考行正则**锚定。
#   ⚠ 本表 61 条「纯汉字日语参考行」（#78 四四章、#859 陽光騎士、#2013 塚地…）被
#     _split_cue_text 判成中文行、ref_pos 为空 ⇒ 锚点允许写**日服汉字形**（engine 的 akja 分支
#     照 jpe 形状，锚点缺 ref 时回落末文本行），这类条目是 --ak 分支永远吃不到的靶区。
#   依据一律标本片实测 cue 号（成品 _calib_nawaton\校准.srt 序号）。
# =============================================================

AK_JA_TERMS = {
    # --- 干员/角色名：片假名音译串 → 官方中文 ---
    "苏卡吉": "斯卡蒂",        # #2019/#2022 スカジ 的音译。定案证据链：#2589「シャチで殴ってる」(虎鲸) + #2590 威嚇 + #2611 深海猎人队；百度百科日文条目「スカジ＝アークナイツ ガード(無畏者)・中国語名 斯卡蒂」
    "斯凯吉": "斯卡蒂",
    "斯卡基": "斯卡蒂",
    "乌尔皮亚努斯": "乌尔比安",  # #751/#955/#1121 ウルピアヌス（简称 ウルピ 的「乌尔皮」是正确的，不动）
    "乌鲁比亚诺斯": "乌尔比安",
    "格拉迪亚": "歌蕾蒂娅",    # #955/#2937/#3094 グレイディア；与乌尔比安同属深海猎人，#955 互保机制吻合
    "格蕾蒂亚": "歌蕾蒂娅",
    "格雷蒂亚": "歌蕾蒂娅",
    "瑛哉": "艾雅法拉",        # #2261/#2387 エイヤちゃん；#2260「シンプル強いのはエイヤ」+#2435 与伊芙利特并列为术师
    "尼雅尔": "临光",          # #2017「花澤香菜さん…ニヤールの妹」+ #2011 ブレミシャイン ⇒ ニヤール=临光、其妹=瑕光
    "尼亚鲁": "临光",
    "尼阿尔": "临光",
    "阳光骑士": "耀骑士",      # #859 参考行「陽光騎士」旧字体直搬；官方＝耀骑士临光
    "塔尔达": "塔露拉",        # #3474/#3475/#3635 タルダ 与霜星并列谈「アーツの規模」；整合运动领袖官方中文＝塔露拉
    "华法林": "华法琳",        # #150/#152/#1063/#1663 ワルファリン；「华法林」是药名
    "阿米亚": "阿米娅",        # #3634 谷翻「阿米亚」（AK_TERMS 未覆盖，故登记在本表）
    "阿米雅": "阿米娅",
    "艾克希亚": "能天使",      # #670/#2532 エクシア
    "艾克西亚": "能天使",
    "希尔巴阿什": "银灰",      # #783/#1900 シルバーアッシュ
    "梅特奥里特": "陨星",      # #3507/#3511/#3525 メテオリーテ
    "弗罗斯特利夫": "霜叶",    # #3494/#3500/#3548 フロストリーフ
    "萨莉亚": "塞雷娅",        # #2393/#2398 サリア
    "莎莉亚": "塞雷娅",        # #2394/#2402
    "洁西卡": "杰西卡",        # #746 ジェシカ
    "马德洛克": "泥岩",        # 2026-11-03 二校纠正：PRTS `マドロック`→#redirect[[泥岩]]，
    "麦德洛克": "泥岩",        #   干员信息栏「干员名jp=マドロック / 外文名=Mudrock」；全库检索「疯眼」0 命中，
                               #   旧值系无据臆造（#1963/#1970 语境「マドロックさん…ギャップ萌え」契合泥岩设定）
    "墨菲斯特": "梅菲斯特",    # #3575/#3577/#3582 メフィスト
    "梅维斯托": "梅菲斯特",    # #3637 メビスト
    "法乌斯特": "浮士德",      # #3569/#3572 ファウスト
    "洛罗斯": "逻各斯",        # #153/#1585 ロロス＝ロゴス 的 ASR 变体
    "洛戈斯": "逻各斯",
    "罗各斯": "逻各斯",
    "乌尔萨斯": "乌萨斯",      # #497 ウルサス
    "起源体": "源石",          # オリジニウム 的字面量直搬
    "新银山": "真银斩",        # #522/#538/#1145 シンギンザン 的同音汉字误听；定案：#522「防御-70%换攻击+110%、范围扩大、最多挡3」＝银灰三技能真银斩
    "真银山": "真银斩",        # #499
    "真金山": "真银斩",        # #1584
    "信银山": "真银斩",
    "塔罗二号": "塔卫二",      # #693 タロツー（终末地舞台，官方中文＝塔卫二）
    "阿里萨罗猎人": "深海猎人",  # #2930/#2939 アビサルハンター 的音译串
    "弗罗斯特诺瓦": "霜星",    # #335 フロストノバ（整合运动干部官方中文＝霜星）
    "弗洛斯特诺瓦": "霜星",
    # --- 谷翻把片假名**写成拉丁**的形态（只出现在日语原声片的谷翻里，英语原声片不会有，
    #     故按「能否出现在英语片源」判归 akja 而非 AK_TERMS）。
    #     ⚠ 键必须写**源文件的形态**：src 里是 "Ifrita"，"伊芙利特a" 只是 --ak 跑完的产物，
    #       登记成键永远命中不到（2026-11-03 实测 #2435/#2488/#2542 三处）。
    "Ifrita": "伊芙利特",      # 长键必须排在 AK_TERMS 的 "Ifrit" 之前（_compile_map 按键长降序，合并表单遍扫描已保证）
    "Mostima": "莫斯提马",     # #2463/#2542 モスティマ 的拉丁形
    "Eiya-chan": "艾雅法拉酱",
    "Eiya": "艾雅法拉",        # #2260/#2299/#2390/#2601/#2613 エイヤ 的拉丁形
    "Lark Knight": "明日方舟",  # #3428 アークナイツ 被谷翻拆成 "Lark Knight"
    "伊芙丽塔": "伊芙利特",
    "伊夫利塔": "伊芙利特",
    "艾芙莉塔": "伊芙利特",
    # === 2026-11-05 奈渡ナオト《明日方舟》新米博士穿搭鉴赏直播（3980 cue，日语原声 + 谷翻中文，--akja）===
    #   出处：PRTS 日文名 `#redirect` 页逐字核验（一手），以及页面正文（安洁莉娜档案3、Vigna→红豆、
    #   荆棘→棘刺）。键全部是**非正常中文词的音译形**，可裸键；通用词形一律走 AK_JA_CONTEXT 锚定。
    #   判例与撤销见 AK_JA_CONTEXT 末尾的 2026-11-05 记录块。
    "克鲁兹": "克洛丝",       # クルース（Kroos）#redirect [[克洛丝]]；谷翻 8 cue 全写「克鲁/克鲁兹/克鲁斯」
    "克鲁斯": "克洛丝",
    "安吉丽娜": "安洁莉娜",    # アンジェリーナ #redirect [[安洁莉娜]]
    "阿齐姆": "安心院",        # アジム＝「安心院」的 ASR 形；PRTS 安洁莉娜档案3「本名安心院安洁莉娜」⇒ #3221/#3222/#3224/#3231
    "马特宏": "角峰",          # マッターホルン #redirect [[角峰]]（谷翻「马特宏峰」）
    "阿德纳": "安德切尔",       # アドナキエル #redirect [[安德切尔]]（谷翻「阿德纳奇尔/阿德纳奎尔」）
    "艾里尼": "艾丽妮",         # アイリーニ #redirect [[艾丽妮]]
    "伊里尼": "艾丽妮",
    "卢门": "流明",            # ルーメン #redirect [[流明]]
    "伊内斯": "伊内丝",         # イネス #redirect [[伊内丝]]
    "梅兰莎": "玫兰莎",         # メランサ #redirect [[玫兰莎]]
    "细语雨": "絮雨",           # ウィスパーレイン #redirect [[絮雨]]（谷翻按字面拆成「细语雨」）
    "雨语": "絮雨",             # 《雨语》＝同一 token 的又一直搬形（#2467）
    "维格纳": "红豆",           # Vigna → PRTS「Vigna」页正文 `#redirect [[红豆]]`
    "维尼亚": "红豆",
    "比格纳": "红豆",
    "塔利亚": "塞雷娅",         # サリア 的另一形；⚠ 常与「莎莉亚」同 cue 并存（#335），两处都要改
    "德克萨斯州": "德克萨斯",    # テキサス #redirect [[德克萨斯]]；谷翻把干员名翻成美国州名（#1913/#1914/#1918/#1930/#2879）
    "托塔": "铅踝",             # トター #redirect [[铅踝]]
    "安塞尔": "安赛尔",         # アンセル；本片 8 cue 全是音译变体，官中作「安赛尔」
    "翁塔奇": "音律联觉",        # 参考行写日服汉字「音立」（#479）；PRTS「音律联觉」＝鹰角举办的明日方舟音乐会
    #   ⚠ 本键依据是**旁证**（音立 NOHIT、音律联觉页存在），非逐字重定向，采纳时在对照表已标注。
    # === 2026-11-10 黒月夜桜《新人ドクターのPV鑑賞会》（3094 cue，日语原声+微软翻译中文，--akja）二校沉淀 ===
    #   出处：日服情人节特別動画系列逐年主角对照（2021 アーミヤ/2022 アズリウス/2023 ケオベ/2024 テンニンカ）、
    #   PRTS 干员页 jp 字段（Ho'olheyak=霍尔海雅、Vulpisfoglia=忍冬、Mischa=米莎）、Baidu百科 Ho'olheyak 页。
    #   键全部是**非正常中文词**的音译/拉丁形，可裸键；通用词形一律走 AK_JA_CONTEXT 锚定。
    "Armia": "阿米娅",           # アーミア 的拉丁形（#1625/#1783/#2061/#2262/#2275）
    "Exia": "能天使",            # エクシア 的拉丁形（#379/#421/#590/#599）
    "Mishi": "米莎",             # ミーシ＝乌萨斯的孩子活动 Mischa（#1625/#1627，与碎骨同场）
    "Enfi": "终末地",            # エンドフィールド 缩略形（#1038/#2153）
    "Enfin": "终末地",           # エンフィン＝エンフィ+ん 的 ASR 叠形（#183）
    "Fellene": "菲林",           # フェリーン＝种族 Feline（官中菲林）的拉丁形（#474）
    "费林": "菲林",              # 同上音译形（#474）
    "Gum": "古米",               # グム＝乌萨斯的孩子活动干员 Gummy（#337）
    "尼亚尔": "临光",            # ニヤール 裸键形补全（AK_JA_CONTEXT 已有锚定；#1000）
    "Chonyu": "重岳",            # チョンユエ 的拉丁形（#1199）
    "布雷兹": "煌",              # ブレイズ＝Blaze 官中煌（#1326/#1328/#1353/#1360）
    "佐苏兰": "铃兰",            # さすらん＝すずらん 的 ASR（#1813）
    "罗斯蒙": "迷迭香",          # ロスモン＝Rosmontis 简称（#2260/#2483）
    "洛斯莫": "迷迭香",          # #2731/#2734
    "罗斯莫": "迷迭香",          # #2734 变体
    "霍尔海亚": "霍尔海雅",      # ホルハイヤ＝Ho'olheyak（#511）
    "乌尔皮斯福里亚": "忍冬",    # ウルピスフォリア＝Vulpisfoglia（铃兰母亲干员，#1857/#1858）
    "阿祖利乌斯": "蓝毒",        # アズリウス＝Blue Poison（日服情人节特別動画 2022 主角；#1869 等 9 处）
    "阿祖留斯": "蓝毒",          # 同上 ASR 变体（#2058）
    "阿祖里": "蓝毒",            # アズリ 昵称（#1905）
    "阿莫利亚": "阿米娅",        # アーミア 的 ASR 变形（#2144）
    "Keobe先生": "刻俄柏",       # ケお部さん＝ケオベ（日服情人节特別動画 2023 主角；#2081）
    "Keo-bu": "刻俄柏",          # 同上（#2086/#2092）
    "Kebe先生": "刻俄柏",        # 同上（#2138）
    "瓦肯大姐": "火神姐姐",      # バルカンお姉ちゃん＝Vulcan 官中火神（#2093/#2095）
    "瓦肯": "火神",              # #2138 形（巴尔坎）
    "天忍": "桃金娘",            # テンニンカ＝Myrtle（日服情人节特別動画 2024 主角；#2189）
    "Lingo酱": "苹果酱",         # りんごちゃん＝桃金娘巧克力苹果的拟人昵称（#2169）
    "铃子酱": "苹果酱",          # #2163/#2164 同一昵称的机翻异写
    "铃儿酱": "苹果酱",          # #2198/#2200
    "Lingo": "苹果",             # 真っ赤なりんご（#2196；长键 Lingo酱 先命中）
    "埃克辛": "能天使",          # エクシン＝エクシア 的 ASR（#2340）
    "罗多斯特": "罗德岛",        # ロドスト（#445）
    "罗德斯": "罗德岛",          # ロドス（#985/#1833）
    "罗兹": "罗德岛",            # #2213/#2306
    "罗德规则": "罗德岛的规则",  # ロドスのルール（#545）
    "卢萨斯": "乌萨斯",          # ウルサス 的 ASR（#329/#837）
    "鲁苏斯": "乌萨斯",          # #882
    # ⚠ 活动名错形族必须**一步到终形**：上游「乌尔苏斯→乌萨斯」的产出不入池，
    #   若先产「乌萨斯之子」再等「乌萨斯之子」键处理就会残留非幂等（2026-11-10 实测 5 处）。
    "乌萨斯的孩子们": "乌萨斯的孩子",  # 活动名 ウルサスの子供たち（#858）
    "乌萨斯之子": "乌萨斯的孩子",      # 同上（#841/#848/#867/#872）
    "乌尔苏斯的孩子们": "乌萨斯的孩子",  # 上游错形族一步到终形
    "乌尔苏斯之子": "乌萨斯的孩子",
    "卢萨斯的孩子们": "乌萨斯的孩子",
    "卢萨斯之子": "乌萨斯的孩子",      # #837
    "鲁苏斯的孩子们": "乌萨斯的孩子",
    "鲁苏斯之子": "乌萨斯的孩子",
    "埃贝利亚": "伊比利亚",      # エベリア＝イベリア（#726）
    "原石病": "矿石病",          # オリジニウム症 官中＝矿石病（#457）
    "寡利灯": "源石",            # オリジニウム 的 ASR（#484）
    "弗兰卡利斯卡": "芙兰卡、雷蛇",  # フランカとリスカム（#444；长键先命中）
    "弗兰卡": "芙兰卡",          # フランカ＝Franka（#435）
    "企鹅方块": "企鹅物流",      # ペンギンキューブ＝ペンギン急便 的 ASR（#420）
    "航海家号": "旅行者1号",     # ボイジャー1号 官中统一（#579）
    "赫西": "凯尔希",            # ひルシー＝ケルシー 的 ASR（#1944，阿米娅身世语境）
    "切尔诺盔甲": "切尔诺伯格盔甲",  # チェルノ防具＝切尔诺伯格（#2405）
}

# (参考行正则, 中文行错形, 正确形) —— 锚点一律是**日语参考行**里的形态（片假名或日服汉字）。
# 与 JA_CONTEXT / JA_PGR_CONTEXT 同规：编译时**不带 re.I**（见 state._AK_JA_CONTEXT_COMPILED）。
# ⚠ 同一锚点下长错形必须排在短错形之前（ctx 顺序敏感，terms-check 查不出来，判例见 ja.py:528）。
AK_JA_CONTEXT = [
    (r"スカージ|スカジ", "天灾", "斯卡蒂"),        # #2581/#2590/#2602-2610 谷翻把スカージ当天灾；天灾在方舟是正经词( Catastrophes)，禁裸键
    (r"スカージ|スカジ", "祸害", "斯卡蒂"),       # #2602
    (r"スカージ|スカジ", "苏卡吉", "斯卡蒂"),
    (r"ロゴス", "标志", "逻各斯"),               # #764/#765/#770/#774/#875/#1345/#2703 ロゴス 被当成 "logo"
    (r"ロゴス", "徽标", "逻各斯"),               # #2703
    (r"ロゴス", "徽号", "逻各斯"),
    (r"ホルン", "喇叭", "号角"),                 # #2104/#2105/#2130/#2161 ホルン＝官方中文「号角」，谷翻按 horn 直译
    (r"重曹", "小苏打", "重装"),                 # #1591/#1594-1596/#2139/#2172/#3192 じゅうそう 同音误听（重曹=小苏打）
    (r"レユニオン", "团聚", "整合运动"),          # #3519/#3543/#3632 レユニオン 被字面译成"团聚"
    (r"レユニオン", "重聚", "整合运动"),
    (r"アビサル", "深渊猎人", "深海猎人"),        # #1740/#2720/#2723/#3777 アビサルハンター 官方中文＝深海猎人
    (r"アビサル", "阿比萨尔", "深海猎人"),
    (r"メテオリーテ", "流星", "陨星"),            # #3280/#3285/#3292/#3467 メテオリーテ 官方中文＝陨星；"流星"是正常词，禁裸键
    (r"コーデ", "坐标", "搭配"),                  # #192/#213/#2335 コーデ 被当成 coordinate
    (r"コーデ", "协调", "搭配"),
    (r"コーデ", "服装", "搭配"),                  # #2461/#2860 等；统一按游戏内「时装/搭配」表述
    (r"ドクター", "医生", "博士"),               # #27/#1104/#3176/#3663 ドクター＝玩家称谓官方中文「博士」
    (r"ドクター", "医师", "博士"),
    (r"モジュール", "模块", "模组"),             # #2378 モジュール＝养成系统「模组」
    (r"コスト", "成本", "费用"),                 # #473/#478/#1613 コスト＝部署费用
    (r"フロストノヴァ|フロストノバ|フロースノヴァ", "冰霜新星", "霜星"),  # #3128/#3129/#3131/#3470 游戏通用词，禁裸键
    (r"フロストノヴァ|フロストノバ|フロースノヴァ", "弗罗斯特诺瓦", "霜星"),
    (r"上級エリート|上級エリートタグ", "高级精英", "高级资深干员"),  # #3044/#3045 公开招募 tag 官方中文
    (r"上級エリート", "上级精英", "高级资深干员"),
    (r"エリートタグ", "精英标签", "资深干员 tag"),  # #3040/#3047
    (r"公開求人", "空缺职位", "公开招募"),       # #3030/#3062 屏上汉字形锚点
    (r"購買資格証", "购买资格", "采购凭证"),      # #3006 屏上汉字形锚点
    (r"ニアル|ニヤール", "尼尔", "临光"),        # #2017 ニヤール 的又一音译形
    (r"陽光騎士|眩しい騎士", "阳光骑士", "耀骑士"),  # #859 纯汉字参考行靶区（日服汉字形锚点）
    (r"ワルファリン", "华法林", "华法琳"),       # 双保险：裸键之外再给一条锚定，防其它片源误伤
    (r"ウルピ", "乌鲁皮", "乌尔皮"),             # #544/#575 ウルピ 的 ASR 前缀形
    (r"サリア", "莎莉亚", "塞雷娅"),
    (r"エイヤ", "瑛哉", "艾雅法拉"),
    (r"タルダ|タルラ", "塔尔达", "塔露拉"),
    # --- 2026-11-03 二校由 PRTS 证件新确认的四条（错形全是通用词，一律锚定，禁裸键）---
    (r"カタパルト|タタパルト", "弹射器", "空爆"),  # #2661/#2662 参考行是 ASR 叠形「タタパルト」，锚点须并收
    (r"カタパルト|タタパルト", "投石车", "空爆"),  # #3601/#3605/#3612；PRTS カタパルト→[[空爆]]（干员名 Catapult）。
    #   ⚠ r1 按字面量写成「投石车」＝名词漏校，本片三处已在 r2 回改。
    (r"スカルクラッシャー|スカルシュレッダー|スカルシュレッター|スカルシレッター", "碎颅者", "碎骨"),  # #96/#105/#111/#1458/#1566/#1569/#1620/#3233；
    #   PRTS 敌人页「碎骨」＝整合运动突击部队干部、龙门外环目击、榴弹发射器；cue 序「米莎之死→该 BOSS」
    #   与主线第 5 章完全吻合。谷翻按 crusher 直译出「碎颅者」，属字面量误校。
    (r"ワルファリン|バルファリン", "巴尔法琳", "华法琳"),  # #51/#1541；ヴァ/ワ 混淆，同一干员（#150/#152 已作华法琳）
    (r"メテオリーテ", "陨石", "陨星"),           # #3507/#3511/#3513/#3515/#3525/#3551/#3553；PRTS メテオリーテ→[[陨星]]
    (r"ロンメン|ロンロンメン", "罗门", "龙门"),   # #451/#3623/#3624/#3640/#3644；#3632「津山街からロンメン外縁部へ」、
    #   #3634「アーミヤロンメンが危険にさらされている」⇒ 主线 5-6 的龙门。「罗门」可作人名/婆罗门，禁裸键。
    (r"メフィスト", "墨菲斯托", "梅菲斯特"),      # #3575/#3577/#3582/#3645；官中＝梅菲斯特。
    #   「墨菲斯托」是其它 IP 通用译名，禁裸键，只锚日服片假名参考行。
    (r"タンク", "坦克", "重装"),                 # #120/#3324 タンク＝职业「重装」(Defender)；「坦克」是常用词。
    (r"サポーター", "支持者", "辅助"),            # #1048/#1049/#1052 サポーター＝职业「辅助」(Support)。
    # --- 2026-11-03 二校：r1 按「查无官中」留了音译/拉丁，本轮用 PRTS `干员页面名` 的
    #     jp 字段**双向核验**定案（官中页面里逐字写着这个片假名句柄）。错形全是通用词或拉丁串，
    #     一律锚定，禁裸键。否决项：ライン→深律、マス→休谟斯 系碎片误命中（真形 ベースライン/ヒューマス）。
    (r"ゴールデングロー", "金色光芒", "澄闪"),      # #2230 谷翻字面量。⚠ 长错形在前：ctx 按列表顺序执行，
    (r"ゴールデングロー", "金光", "澄闪"),          #   「金光」若在前会把「金色光芒」咬成「澄闪色的光芒」
    (r"ムリナ", "莫里纳尔", "玛恩纳"),              # #1464/#1571/#1583/#1594/#1595；Młynar。
    (r"ムリナ", "姆纳尔", "玛恩纳"),                 #   ⚠ 键写**谷翻源形**「莫里纳尔」，不是 r1 自定的「穆里纳尔」
    (r"クラウン[・\s]*スレイヤー", "皇冠杀手", "弑君者"),  # #3642/#3653；Crownslayer，主线 5-6 整合运动干部。
    #   ⚠ 谷翻产出的是中文「皇冠杀手」，源侧没有 "Crown Slayer" 这个拉丁形，别按 r1 成品建键。
    (r"サンタラ", "桑塔拉", "寒檀"),               # #1082/#2950；Santalla，术师
    (r"マルシル", "玛西尔", "玛露西尔"),            # #1453/#1454；Marcille（谷翻源形＝玛西尔）
    (r"ファントム", "Phantom", "傀影"),            # #701/#703/#712/#717/#725/#728/#737；Phantom the Fiery，
    #   CV 石田彰（#703「ファントム石田アキラ」）与官方声优表吻合 ⇒ 本片七处 r1 保留拉丁，属名词漏校。
    (r"ファントム", "幻影", "傀影"),
    (r"クーリエ", "快递员", "讯使"),               # #1940；PRTS {{干员页面名|讯使|Courier|クーリエ}}。
    (r"クーリエ", "快递", "讯使"),                  # #1945 长形在前，防「快递员」被咬成「讯使员」
    (r"クーリエ", "信使", "讯使"),                  # #1934 r1 同音误形「信使」⇒ 官中作「讯使」
    # --- 2026-11-03 三方对账（recon 类3）反推出的表缺口，全部只能锚日语行 ---
    (r"はるか(?=が|は|も|の|、|っ|$)|ハルカ", "哈鲁卡", "瑕光"),  # #1060；Nearl 之妹 Blemishine＝瑕光。
    (r"はるか(?=が|は|も|の|、|っ|$)|ハルカ", "遥", "瑕光"),       # #879/#885/#977/#1001/#1013/#1707
    #   ⚠ ASR 把人名写成**平假名「はるか」**，光锚片假名 ハルカ 一条都不出（本轮 recon 实测 13 处漏校）。
    #   ⚠ はるか 作副词＝「远远地」（#998「はるか後か/はるか前」），必须用后置断言只认
    #      「はるか+助词/顿号/句末」的名词用法，否则把「相差很远」改花。
    (r"ブレミシャイン", "瑕疵", "瑕光"),                 # #2011/#2012 谷翻按字面量把 Blemishine 译成「瑕疵」
    (r"ムリナ|ムリな|無理な", "穆利纳", "玛恩纳"),      # 锚点必须并收 ASR 汉字化「無理なある」，
    (r"ムリナ|ムリな|無理な", "穆里纳", "玛恩纳"),      #   否则 #1220/#1594/#1595/#1691/#1692 这类
    #   谷翻把ムリナール当「不可能」或音译成「穆利纳」的行永远捞不到。
    #   ⚠ 不写短语级键（如「不可能，还是→玛恩纳，还是」）：短语键是本项目明令禁止的形态，
    #      那类整句误译留逐 cue 覆盖（#1691/#1692 成品已改）。
    (r"エンドフィールド|フィールド", "端场", "终末地"),   # #1052 谷翻把エンドフィールド截成「端场」
    (r"コーデ", "衣服", "搭配"),                     # #728 「红色衣服」＝赤いコーデ
    (r"重装", "重型", "重装"),                       # #1525 谷翻「重型干员」；锚点取参考行汉字「重装」
    (r"術師", "魔法师", "术师"),                      # #2606 谷翻把術師译成「魔法师」
    (r"アビサル", "深渊", "深海猎人"),                 # #2724/#2924 アビサル 旁的「深渊」一律是阵营名
    #   ⚠ 只走锚定：「深渊」本身在别的语境可合法出现，禁裸键。
    (r"スカージ|スカジ", "斯科奇", "斯卡蒂"),          # #2924 Skadi 的又一音译形
    (r"ロゴス|ロロス", "洛格斯", "逻各斯"),            # #1255 谷翻的又一音译形（源侧是「洛格斯」）
    (r"なまたり", "Naoto Namari", "奈渡直人"),         # #11 主播自报名号的罗马字误拼（正形 Nawatari）
    (r"危機契約", "Crisis Contract", "危机合约"),      # #1832 谷翻原样照搬拉丁
    # ⚠ 2026-11-03 实测撤销的两条（记录以免有人再塞）：
    #   (回復→医疗) 与 (支援→辅助)。回復/支援 在日语里是**通用动词**（回復＝治疗/回血/恢复，
    #   支援＝援助/掩护），只有在「回復を2人置いて」这类**数职业**的句子里才等于职业名医疗/辅助。
    #   入表后实跑产出「它就会医疗」「你医疗的时候为什么不能打我」等胡话（recon 类3 由 22 涨到 34），
    #   已撤销；这类只能在逐 cue 层按句判。判据复述：**词性通用与否决定能不能进表，不看它是否官中词**。
    # ⚠ 刻意不入表的两例（写在这里防后人再塞）：
    #   ①「艾雅→艾雅法拉」自咬：艾雅 是 艾雅法拉 的子串，_ctx_replace 是纯 str.replace，
    #      命中会把「艾雅法拉」撑成「艾雅法拉法拉」（刻帝⊂刻刻帝 同型）。#2603/#2605/#2611 留逐 cue。
    #   ②「皮卡/精选→UP池」：セレクトピックアップ 的谷翻碎形，替换后句子仍不通，属句级问题。
    # ヘラグ＝赫拉格（PRTS 双向核验通过）：r1 全部 cue 已写对，无错形可锚 ⇒ 只登记知识、不建条目。
    # --- 屏上文字/旧汉字形的纯日语参考行（61 条靶区里已定案的一条）---
    (r"四四章", "四四章", "4-4 章"),           # #78 参考行即「四四章」＝关卡号 4-4，谷翻原样照搬；
    #   锚点是日服汉字形 ⇒ 这类行在 --ak 下 ref_pos 为空、ctx 永不命中，只有 akja 分支能吃到。
    #   ⚠ 同形态的「塚地(#2013)/陽光騎士(#859)/生存、(#1789)」等**查无官中的绝不入表**，
    #     宁可留在逐 cue 覆盖层，避免把参考行形态硬编成术语。
    # === 2026-11-05 奈渡ナオト 穿搭片：通用词形只能锚定，以及四条撤销判例 ===
    #   判据同前：**词性通用与否决定能不能进裸键表，不看它是否官中词**。本片把这条又验了一遍：
    (r"ヘイズ", "雾霾", "夜烟"),               # ヘイズ＝夜烟（Haze）。⚠ **绝不可作裸键**：
    (r"ヘイズ", "阴霾", "夜烟"),               #   一校 #229 参考行是「もやばくない?」（も+やばい），
    (r"ヘイズ", "海兹", "夜烟"),               #   谷翻写成「雾霾」本就没错，按禁形裸改成「夜烟」= 凭空造出干员提及。
    (r"ハイビスカス", "木槿", "芙蓉"),          # ハイビスカス＝干员芙蓉；「木槿」是植物通名，禁裸键（#2412/#2444）
    (r"クーリエ", "导游", "讯使"),              # ⚠ 上一片撤「快递/信使」裸键是对的，但**整条跟着撤是错的**：
    #   本片 #3038 参考行确写 クーリエ，谷翻译成「导游」⇒ 锚定条目必须留，通用裸键与整条存废是两件事。
    (r"プロヴァンス|プロパンス", "丙烷", "普罗旺斯"),  # プロヴァンス＝干员 Provence；「丙烷」是化学名，禁裸键（#2914）
    (r"リスカム", "利斯库姆", "雷蛇"),           # Liskarm＝雷蛇（#2293 参考行并给 CV 石川由依互证）
    (r"スカージ", "Scourge", "斯卡蒂"),         # スカージ 被谷翻按英文 scourge 直译成拉丁（#28）；Scourge 是正常英文词 ⇒ 禁裸键
    (r"ソーンズ", "荆棘", "棘刺"),               # ソーンズ＝棘刺（PRTS「荆棘」页正文即 `#REDIRECT [[棘刺]]`）。
    #   ⚠ **绝不作裸键**：本仓库已有两处裁定——entities_part1.py:1370「'荆棘'是正常中文词，只走 ctx」，
    #   且 bilingual.py:876 收着 GW2 资料片「荆棘之心」(Heart of Thorns)，裸键会把它咬成「棘刺之心」。
    #   kb-lint 实测：加裸键后问题数 9→10（级联互含），故降级为锚定。
    (r"(?<!マッター)ホルン", "角峰", "号角"),     # ⚠ 判例 #3052：参考行 `ホルンだったの` 是干员**号角**，
    #   被邻簇的 マッターホルン→角峰 带偏改成「角峰」。锚点**必须带否定回顾**，否则 マッターホルン 会被 substring 命中。
    (r"メテオ(?!リーテ)", "陨星", "流星"),        # ⚠ 方向性判例：现表只有 メテオリーテ→陨星 的正向锚，缺反向保护。
    #   メテオ 的官中**就是「流星」**（PRTS #redirect），把「流星」当成「陨星」的禁形是本片实测的方向性错误
    #   （#996/#998/#1000/#1812 机翻本来就对）。带 (?!リーテ) 才不会被 メテオリーテ 反噬。
    (r"ブローカ", "经纪人", "布洛卡"),            # ⚠ 撤销裸键的替代方案：「经纪人→布洛卡」不能进裸键——
    #   ASR 还会写本词「代理人」（#1555/#2436/#2478 机翻「经纪人」是忠实的），只有参考行确写 ブローカ 才是布洛卡（#1051/#1066）。
    (r"(?<!理)論面", "理论", "龙门"),             # 論面（ロンメン 的日服汉字形）＝龙门；「理论」是常用词禁裸键，
    #   且锚点要排除「理論」（#693 谷翻把「論面の職人」写成「理论工匠」）。
    (r"皇手|御手|コ手", "皇手", "穿搭"),           # コーデ 的 ASR 残形（#2827/#3952「皇手」「御手」）⇒ 与全片定稿形「穿搭」统一
    (r"皇手|御手|コ手", "御手", "穿搭"),
    (r"ペーペイ|ペイペイ", "佩佩i", "Pepei"),      # ⚠ **尾巴类**：AK_TERMS 的裸键 "Pepe"->"佩佩" 咬住 ASR 形
    #   "Pepei"，产「佩佩i」（#2219 参考行「本当にまだペーペイだからさ」）。ペーペイ 是否即干员**佩佩**
    #   查无证件 ⇒ 按「低置信不校名」保留拉丁原形，只把尾巴收回去。
    #   判据：**尾巴只能靠 ctx 兜，别指望 EXCLUDE**——akja 分支没有 EXCLUDE 回滚层，而它的
    #   `right->wrong` 整词回滚在这里会把「佩佩i」换成「Pepeii」（i 还留着）。
    # --- 2026-11-10 黒月夜桜 PV鑑賞会 二校：错形是通用词/生僻乱形，一律锚日语参考行，禁裸键 ---
    (r"アーミ[アヤや]", "军队", "阿米娅"),        # #1909/#1913/#1971/#1996 ぐんたい≠アーミや；「军队」是通用词，禁裸键
    (r"ミや", "宫", "阿米娅"),                    # #2295/#2296 アーミヤ 截断形；「宫」是常用字，禁裸键
    (r"テキサス", "德州", "德克萨斯"),            # #374/#395/#408/#410/#415 テキサス＝官中德克萨斯；「德州」禁裸键
    (r"ライン|LINE\s*生命", "LINE 生命", "莱茵生命"),         # #356 ライン生命＝Rhine Lab 官中莱茵生命
    (r"ライン", "LINE 生活", "莱茵生命"),         # #357（长错形在前，防「LINE 生命」被咬成「莱茵生命 生命」）
    (r"ライン", "LINE", "莱茵生命"),              # #346
    (r"カンイ[ンカ]", "干鱿鱼", "干员"),          # #285 カンイカ＝カンイン（幹員）的 ASR；「干鱿鱼」禁裸键
    (r"ペンキ", "油漆", "企鹅物流"),              # #2720/#2775 ペンキ＝ペンギン（急便）的 ASR；#417/#428/#611 走逐 cue 侧车
    (r"配達", "分娩条件", "配送条件"),            # #2308 配達の条件＝寿司外卖配送条件；机翻「分娩」错译
    (r"けいちゃん", "圭酱", "刻俄柏酱"),          # #2123/#2134/#2144/#2146 けいちゃん＝ケオベちゃん 的 ASR（2023 情人节动画段）
    (r"スカルシレッター", "骷髅Shiletter", "碎骨"),  # #1627 拉丁残形（Skullshatterer 的 ASR；裸锚点已并入碎颅者条目）
    (r"フロストノヴァ|フロストノバ|フロースノヴァ", "霜新星", "霜星"),  # #1557/#2773/#2791 错形并入既有锚点系
]

