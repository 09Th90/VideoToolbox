# -*- coding: utf-8 -*-
# @version 3.2.0
"""Arcaea × 明日方舟 联动直播片源术语/语境表（--arcak，2026-11-18 新增）

片源：《ARCAEA X ARKNIGHTS IS LIVE NOW!》（kukkikaze，英语直播 ASR + 微软翻译，
2340 cue，每 cue 中文 + 英文参考行，CRLF 无 BOM，5h40m 打歌/剧情实况）。
校准方式：两轮全人工逐句（一校 1503 条 + 二校 30 条），本表沉淀可规则化判例，
供同系列（Arcaea×方舟联动直播/reaction）复跑。

官方依据（2026-11-18 检索/核实）：
- 明日方舟国服官方中文：阿米娅、凯尔希、博士、干员、源石、矿石病、感染者、
  天灾、泰拉、维多利亚、罗德岛、卡兹戴尔、整合运动、巴别塔、魔王（Lord of
  Fiends）、黑色王冠、陆地舰。
- Arcaea 官方中文名「韵律源点」；本片按用户裁决**Arcaea/Lethe 保留英文原名**
  （Arcaea 无国服，社区通行英文；曲名同样保留英文）。
- Arcaea 官方中文角色名：Lethe=忘却、光=Hikari、对立=Tairitsu、咲弥=Saya、
  红=Kou、依莉丝=Ilith（萌娘百科/官方中文）；片内首次出现即按此口径，Lethe
  因是剧情叙述者按用户要求保留英文。
  ※ 本表把 Sia/Tyu/Hikari 等 ASR 变体拉回片内既有中文口径；Lethe 的反向
    （中文音译→Lethe）也在表内，防止机翻把它译成「勒忒/忘却」。

硬契约：
- 裸键只收**唯一错形**（ASR 误听串、方舟游戏名错形、音译曲名）；普通中文词
  （医生/操作员/老板/光谱/叛徒/光辉/奇点/活着/弧线）一律走 ARCAK_CONTEXT
  英文参考行锚定，禁走裸键。
- 曲名按用户口径保留英文：机翻把 Renegade/Spectrum/Radiant/Singularity/Alive
  译成中文时，只用 ctx 拉回英文，不做「英文→带括号中文名」的裸键。
- 与 --ak 严格隔离：AK_TERMS 里的 Arcaea→韵律源点、Radiant→《Radiant》等
  与本片口径冲突的键**不并入**，本模式只用自己的表。
- 本模式分支消费 EXCLUDE_CONTEXT（与 --ak 同构），但表内键与既有 EXCLUDE
  的 wrong 无交集（terms-check 已验证），不会互相回滚。

2026-11-19 增补：271 cue《Motion Amiya Partner Play｜All Songs Pure Memory》歌词向二校。
- 本片走 --arcakamiya（本表 + 271 条逐 cue 侧车），不直接跑 --arcak：直播模式的
  曲名回拉（叛徒/叛逆者→Renegade）会把歌词本义改回英文，属误伤。
- 可规则化判例：`\bHP\b` 马力→HP（cue 266「9 马力」）、`\bHeat\b` 热量→热
  （Heat 段机翻名词化时回拉）；ASR「Cannibate」实为「gonna bait」，不得沉淀为
  「蚕食」——该处由侧车逐句处理。
"""

ARCAK_TERMS = {
    # ── 游戏名 / 组织（ASR 误听 + 机翻错形；cue 2/130/190/828/1755 判例） ──
    "Ark Knights": "明日方舟",
    "Arknights": "明日方舟",
    "Arknates": "明日方舟",
    "Arthates": "明日方舟",
    "Akunit": "明日方舟",
    "Art Knights": "明日方舟",
    "方舟骑士": "明日方舟",
    "阿克奈特": "明日方舟",
    "阿恩斯": "明日方舟",
    "阿库尼特": "明日方舟",
    "Roads Island Pharmaceuticals Incorporated": "罗德岛制药公司",
    "Roads Island": "罗德岛",
    "罗兹岛": "罗德岛",
    # ── 人物（cue 316/518/600/832 判例；大小写变体逐条列） ──
    "Amiya": "阿米娅",
    "Amia": "阿米娅",
    "Amya": "阿米娅",
    "Amiia": "阿米娅",
    "Amir": "阿米娅",
    # 注意：不要加裸键 "Amma"->"阿米娅"——Endfield 表已把 Amma 映射到终末地角色「安玛」，
    #   kb-lint 会判跨模式变体冲突；本片的 Amma 走 ARCAK_CONTEXT 锚定。
    #   「阿妈」同理不进裸键（正常义=妈妈），只由 ARCAK_CONTEXT 的 \bAmma\b 锚定。
    "阿米亚": "阿米娅",
    # ── Arcaea 侧（用户口径：Arcaea/Lethe 保留英文） ──
    "IKEA": "Arcaea",              # cue 739-741 ASR 把 Arcaea 听成宜家
    "archa": "Arcaea",             # cue 1701-1702
    # 注意：不要加裸键 "Arca"->"Arcaea"——terms-check 判它会咬住 archa/IKEA 的替换结果
    #   「Arcaea」中的前缀（cue 687 的 Arca 由人工逐句处理，收益不值风险）。
    "Lrange": "Lethe",             # cue 1206/1245/1272 ASR 误听群
    "Lrrench": "Lethe",            # cue 1240
    "Grrench": "Lethe",            # cue 1210
    "Grinch": "Lethe",             # cue 1241/1290
    "Granch": "Lethe",             # cue 1281/1283
    "Lranch": "Lethe",             # cue 1272
    "勒忒": "Lethe",
    "蕾忒": "Lethe",
    "Sia": "咲弥",                  # cue 1227（Saya ASR）
    "Tyu": "对立",                  # cue 1231（Tairitsu ASR）
    "Hikari": "光",                # cue 1232
    # ── 曲名/曲师（保留英文；机翻音译回拉） ──
    "Somnium Maner": "Somnium",
    "Sio Mensor": "Somnium",       # cue 67-68
    "Somnio Menser": "Somnium",    # cue 69
    "Sonia Manson": "Somnium",     # cue 61
    "Sonia Mensor": "Somnium",     # cue 65
    "Somnia Menser": "Somnium",    # cue 821
    "Reagan": "Renegade",          # cue 2283
    "Dawnseker": "Dawnseeker",     # cue 500 拼写
    "Mustache": "Muse Dash",       # cue 741 ASR 误听
    "L2D": "Live2D",               # cue 320
    # ── 方舟名词（唯一错形；cue 1051/1067/1077 判例） ──
    "原始嫩芽": "源石晶簇",
    "原版芽": "源石晶簇",
    "奥利皮": "矿石病",
}

ARCAK_CONTEXT = [
    # (参考行英文正则, 中文行错形, 正确形)
    # ── 方舟术语：普通中文词，只能靠英文参考行锚定 ──
    (r"\bAmma\b", "阿妈", "阿米娅"),                 # cue 518/2071（避免与终末地安玛冲突）
    (r"\bdoctor\b", "医生", "博士"),                 # cue 1059/1082
    (r"\boperators?\b", "操作员", "干员"),           # cue 1165
    (r"\bOriginium\b", "原石", "源石"),              # cue 1051
    (r"\bOriginium\b", "原汁原味", "源石"),          # cue 1053 机翻成语化
    (r"\bOripathy\b", "源石病", "矿石病"),           # cue 1067
    (r"\bLord of Fiends\b", "恶魔之王", "魔王"),     # cue 1117
    (r"\bLord of Fiends\b", "魔王之王", "魔王"),
    (r"\blandship\b", "陆船", "陆地舰"),             # cue 981/1018
    (r"\bInfected\b", "被感染的人", "感染者"),
    # ── 音游术语（chart/note/slide/arc/boss；全是普通词，禁裸键） ──
    (r"\bchart(?:s|ed|ing)?\b", "图表", "谱面"),     # cue 501/598/795
    (r"\bchart(?:s|ed|ing)?\b", "记录", "谱面"),
    (r"\bnotes?\b", "笔记", "音符"),                 # cue 537/678
    (r"\bslides?\b", "幻灯片", "滑条"),              # cue 412
    (r"\barcs?\b", "弧线", "音弧"),                  # cue 714/721（Arcaea 官方中文=音弧）
    (r"\bwhat boss\b", "老板", "Boss"),              # cue 1805
    (r"\bfull combo\b", "全连招", "full combo"),
    (r"\bHP\b", "马力", "HP"),                       # 2026-11-19 cue 266「9 马力」→9 HP
    (r"\bHeat\b", "热量", "热"),                     # 2026-11-19 歌词段 Heat 直译回拉
    # ── 曲名：机翻中文→英文原名（用户口径保留英文） ──
    (r"\bRenegade\b", "叛徒", "Renegade"),          # cue 86-90/328/539
    (r"\bRenegade\b", "叛逆者", "Renegade"),        # cue 334/539
    (r"\bSpectrum\b", "光谱", "Spectrum"),          # cue 55/717
    (r"\bRadiant\b", "光辉", "Radiant"),            # cue 45/540
    (r"\bSingularity\b", "奇点", "Singularity"),    # cue 752
    (r"\bAlive\b", "活着", "Alive"),                # cue 716/718/765
    (r"\bInsomnia Master\b", "失眠症", "Insomnia Master"),  # cue 1312
    # 注意：曲名 Miss You / Speed of Light 这两条歌词线**不建 ctx**——片内歌词
    #   "at the speed of light" 译作「以光速」、"I really miss you" 译作「我真的很想你」
    #   都是歌词本义，锚定会误伤（r2 幂等实测各命中 3-4 处）；曲名语境由人工保留英文。
    (r"\bFading Sky\b", "消逝的天空", "Fading Sky"),  # cue 487-492
    # ── Arcaea 侧：防止机翻把角色名/游戏名译成中文 ──
    (r"\bArcaea\b", "韵律源点", "Arcaea"),          # 片内口径保留英文
    (r"\bLethe\b", "忘却", "Lethe"),
    # ── ASR 短词，靠自身或邻近英文锚定（禁裸键，防咬人名） ──
    (r"\bKou\b|\bCole\b", "科尔", "红"),             # cue 1228
    (r"\bSaya\b|\bSia\b", "西亚", "咲弥"),
    (r"\bTairitsu\b|\bTyu\b", "提亚", "对立"),
    (r"\bAKA\b", "AKA", "Arcaea"),                   # cue 1204-1217 主播简称
]

# 漏译体检（只收高置信专名；供 missing --mode arcak --window 1）
ARCAK_MISSING_CHECK = [
    (r"\bAmiya\b|\bAmia\b", ("阿米娅",), "Amiya 官方中文=阿米娅"),
    (r"\bKal'?tsit\b", ("凯尔希",), "Kal'tsit 官方中文=凯尔希"),
    (r"\bRhodes Island\b|\bRoads Island\b", ("罗德岛",),
     "Rhodes Island 官方中文=罗德岛"),
    (r"\bOriginium\b", ("源石",), "Originium 官方中文=源石"),
    (r"\bOripathy\b", ("矿石病",), "Oripathy 官方中文=矿石病"),
    (r"\bInfected\b", ("感染者",), "Infected 官方中文=感染者"),
    (r"\bLord of Fiends\b", ("魔王",), "Lord of Fiends 官方中文=魔王"),
    (r"\bVictoria\b", ("维多利亚",), "Victoria 官方中文=维多利亚"),
    (r"\bTerra\b", ("泰拉",), "Terra 官方中文=泰拉"),
    (r"\bDoctor\b", ("博士",), "Doctor 官方中文=博士"),
    (r"\boperators?\b", ("干员",), "Operator 官方中文=干员"),
]