# -*- coding: utf-8 -*-
# @version 2.7.0
"""术语/实体数据表

源：subtitle_calib_merged.py L8840-L10200 @ 97d7d463（2026-10-24 冻结快照）
"""
import io
import os
import re
import shutil
import sys
import unicodedata
from .entities_base import Entity

ENTITIES_PART2 = [
    Entity("天空海", modes=("ja",), ja="天空海",
           category="术语/鸣潮",
           ctx=((r"天空会|天空海", "天空会"),),
           note="鸣潮现象名，官方中文=天空海（包裹覆盖整个索拉里斯天空的特殊现象，灰机wiki）。"
                "日语 天空海(てんくうかい) 被 ASR 咬成同音的 天空会(てんくうかい)，谷翻照抄'天空会'。"),
    Entity("秧秧", modes=("ja",), ja="やんやん",
           category="角色/鸣潮/今州",
           ctx=((r"やんやん|ヤんやん|にゃんやん", "燕燕"),
                (r"やんやん|ヤんやん|にゃんやん", "延雅"),
                (r"やんやん|ヤんやん|にゃんやん", "燕"),
                (r"やんやん|ヤんやん|にゃんやん", "妮艳")),
           note="鸣潮 4★ 今州共鸣者。日语昵称=やんやん；谷翻音译成 燕燕/延雅/Nyanyan/ヤ。"
                "'燕燕'为正常中文词，只走日语行锚定 ctx（本片主播也昵称其为'鹿'）。"),
    Entity("今州", modes=("ja",), ja="今州",
           category="地名/鸣潮",
           ctx=((r"今週場|今州城", "本周的场外"), (r"今週場|今州城", "本周场"),
                (r"今週場|今州城", "今周场"), (r"今週場|今州城", "今正场"),
                (r"今週(?!場)(?!って|だった|に|は|の|も|から|まで)|今州", "本周"),
                (r"今週(?!場)(?!って|だった|に|は|の|も|から|まで)|今州", "这周"),
                (r"今週(?!場)(?!って|だった|に|は|の|も|から|まで)|今州", "纳迦")),
           note="瑝珑六州之一（今州）。日语 今州(きんしゅう) 被 ASR 咬成同音的 今週(こんしゅう)，"
                "谷翻一律按'本周'处理（'本周的场外活动'=今州城）。'今週場'=今州城。"
                "戒律：本周/这周是正常中文词，只走日语行锚定 ctx。"
                "2026-10-12 收紧：今週って/今週だった 等 = 现实'这周'（如 3連休 闲聊），"
                "非今州（索拉逐星舞台 S2 同视片 cue5/cue639 实测误改），加负向后顾排除。"),
    Entity("瑝珑", modes=("ja",), ja="瑝珑",
           category="地名/鸣潮",
           note="鸣潮东方文明国名，'一庭六州'，每州由对应东方七宿的岁主掌管（百度百科/灰机wiki）。"
                "日语 瑝珑(こうりゅう) 与 交流(こうりゅう) 同音，ASR 一律作 交流，谷翻译成'交换/交流'。"
                "⚠ 本条只登记元数据、不加规则：'交流'在日语里也是常用词，无可靠锚点，"
                "贸然替换会误伤；本片逐 cue 侧车处理。"),
    Entity("鸣潮", modes=("ja",), ja="鳴潮",
           category="作品名",
           ctx=((r"名長|名朝|鳴潮", "有名的领袖"), (r"名長|名朝|鳴潮", "著名领袖"),
                (r"名長|名朝|鳴潮", "纳迦"), (r"名長|名朝|鳴潮", "名长"),
                (r"名長|名朝|鳴潮", "著名的领袖"),
                # 2026-10-14 补（鸣潮 2.4 七丘 ja 片实测）：名長 又被咬成 直长/直永/七永
                (r"名長|名朝|鳴潮", "直长"), (r"名長|名朝|鳴潮", "直永"),
                (r"名長|名朝|鳴潮", "七永")),
           note="作品名。日语 鳴潮(めいちょう) 被 ASR 咬成同音的 名長(めいちょう)，"
                "谷翻直译成'有名的领袖/著名领袖'，或音译'纳迦/名长'。"
                "（'纳迦'出现在 cue 1000 '鸣潮的快速传送是世界第一'。）"
                "2026-10-14 补 直长/直永/七永（同音再咬字）。"),
    Entity("数据坞", modes=("ja",), ja="データドッグ",
           category="系统/鸣潮",
           ctx=((r"データドッ?[ッグ]|データドック", "数据狗"),
                (r"データドッ?[ッグ]|データドック", "数据犬")),
           note="鸣潮声骸管理系统，官方中文=数据坞（Data Bank）。日语 データドッグ 被谷翻"
                "按 dog 直译成'数据狗'。'数据狗'非正常中文词，但仍走 ctx 以防万一。"),
    Entity("守岸人", modes=("ja",), ja="ショアキーパー",
           category="角色/鸣潮",
           ctx=((r"ショアキーパー", "岸上看守"), (r"ショアキーパー", "岸边看守"),
                (r"ショアキーパー", "海岸看守")),
           note="鸣潮角色，官方中文=守岸人（Shorekeeper）。谷翻把 ショアキーパー 按字面译成'岸上看守'。"),
    Entity("杏鲍菇", modes=("ja",), ja="エリンギ",
           category="梗/鸣潮",
           variants=("エリンギ", "エリンゲ", "エリング", "エリンギー"),
           ctx=((r"エリンギ|エリンゲ|エリング", "帝王平菇"),
                (r"エリンギ|エリンゲ|エリング", "埃林格"),
                (r"エリンギ|エリンゲ|エリング", "艾灵"),
                (r"エリンギ|エリンゲ|エリング", "王蚝菇"),
                (r"エリンギ|エリンゲ|エリング", "王菇")),
           note="主播梗：某残象外形像杏鲍菇（エリンギ），弹幕与主播都以'杏鲍菇'称呼它。"
                "谷翻给出 帝王平菇/埃林格/艾灵 等不一致译名，统一为 杏鲍菇。"),
    Entity("千咲", modes=("ja",), ja="千咲",
           category="角色/鸣潮",
           variants=("チさ", "ちさ", "地さ", "チサ"),
           ctx=((r"千咲|チさ|地さ|千崎|ちさ", "千崎"),
                (r"千咲|チさ|地さ|千崎|ちさ", "地咲")),
           note="鸣潮角色千咲（3.7 复刻）。日语 ASR 作 チさ/ちさ/地さ（じさ/ちさ 混淆），"
                "谷翻给出 千崎/地咲 等错形，统一为 千咲。"),
    Entity("弗洛洛", modes=("ja",), ja="フローヴァ",
           category="角色/鸣潮/残星会",
           ctx=((r"フローヴァ|フローバ|フロバ|ブローバ|フロー", "弗洛瓦"),
                (r"フローヴァ|フローバ|フロバ|ブローバ|フロー", "弗罗巴"),
                (r"フローヴァ|フローバ|フロバ|ブローバ|フロー", "弗洛巴")),
           note="鸣潮 5★（湮灭·音感仪），残星会会监，'游走于生死之间的残星会会监，神秘而危险的指挥家'"
                "（百度百科/灰机wiki）。官方 JP 名=**フローヴァ**（AniBase 标注 Furōvu~a）。"
                "本片主播想看她的主线剧情、并提到'系着丝带、连武器上都有'，均与其设定吻合。"),
    Entity("卜灵", modes=("ja",), ja="ボクレイ",
           category="角色/鸣潮",
           variants=("ボクレイ", "ボクレイー", "卜霊"),
           ctx=((r"ボクレイ|僕レイ|僕霊|牧霊|亡霊", "仆雷"),
                (r"ボクレイ|僕レイ|僕霊|牧霊|亡霊", "仆灵"),
                (r"ボクレイ|僕レイ|僕霊|牧霊|亡霊", "牧灵"),
                (r"ボクレイ|僕レイ|僕霊|牧霊|亡霊", "亡灵"),
                (r"ボクレイ|僕レイ|僕霊|牧霊|亡霊", "博库雷")),
           note="鸣潮 4★ 治疗/增益辅助（3.7 上半卡池陪跑：卜灵、桃祈、釉瑚）。"
                "官方 JP 名=**卜霊（ボクレイ）**（AniBase：'卜灵 (卜霊 (ボクレイ), Bokurei)'）。"
                "日语 ASR 常作 僕レイ/僕霊/牧霊/亡霊；谷翻给出 仆雷/仆灵/牧灵/亡灵 等不一致译名。"
                "主播也拿'卜(ぼく)↔僕'玩梗（'可以说是仆娘吗'），中文侧保留'仆娘'一词。"),
    Entity("安全科", modes=("ja",), ja="安全科",
           category="组织/鸣潮/华胥研究院",
           ctx=((r"安全家|安全化|安全科", "安全家"), (r"安全家|安全化|安全科", "安全化")),
           note="华胥研究院下设科室。莫特斐的官方设定：'**华胥研究院安全科**成员，"
                "黑石应用领域专家'（wuthering.gg）。日语 ASR 作 安全家/安全化，谷翻照抄。"),
    Entity("边庭", modes=("ja",), ja="辺定",
           category="地名/鸣潮/今州城",
           variants=("辺定", "変定"),
           ctx=((r"辺定|変定|边庭", "变定"), (r"辺定|変定|边庭", "辨定")),
           note="今州城内机构。灰机wiki《地区探索报告/今州-今州城》：'一份记载于**边庭**的"
                "天工部的报告书'。日语 ASR 作 変定(へんじょう)；本片中是登记中枢信号、"
                "令尹为漂泊者安排房间的场所。"),
    Entity("天工部", modes=("ja",), ja="天工部",
           category="组织/鸣潮/今州",
           ctx=((r"天校|天工部", "天派"),),
           note="今州部委之一，受众事台管辖，主司工程建设；下设军武科、防事科"
                "（Fandom《天工》）。日语 ASR 作 天校(てんこう)，谷翻按音译作'天派'。"),
    Entity("北落野", modes=("ja",), ja="北落野",
           category="地名/鸣潮/今州",
           ctx=((r"北楽|北落野", "北乐平原"), (r"北楽|北落野", "北乐原")),
           note="今州区域之一（今州城/中曲台地/荒石高地/北落野/云陵谷）。"
                "日语 ASR 把 北落(ほくらく) 写成同音 北楽，谷翻作'北乐平原'。"),
    Entity("荒石高地", modes=("ja",), ja="荒石高地",
           category="地名/鸣潮/今州",
           note="今州区域之一。本片日语 ASR 作'石崩れのコチ'，谷翻作'科奇'；"
                "'石崩れ'→荒石 属**推测**（音形未完全对上），故只登记元数据、不加规则，"
                "本片按'乱石崩落的高地'意译处理。"),
    Entity("桃祈", modes=("ja",), ja="トウキ",
           category="角色/鸣潮",
           ctx=((r"トウキ|桃祈", "托奇"), (r"トウキ|桃祈", "塔奇")),
           note="鸣潮 4★（3.7 上半卡池陪跑）。日语 ASR 作 トキー/たき；谷翻作'托奇'。"
                "本片 cue 1539 的'たき'按同一角色处理（属推测，已标注）。"),
    Entity("釉瑚", modes=("ja",), ja="ユウゴ",
           category="角色/鸣潮",
           note="鸣潮 4★ 冷凝（3.7 上半卡池陪跑）。官方 JP 名=**ユウゴ**（wikiwiki.jp/w-w、AniBase）。"
                "本片 cue 1399 'うが4頂' 按'釉瑚4凸'处理，属推测，故只登记元数据、不加规则。"),
    Entity("莫特斐", modes=("ja",), ja="モルトフィ",
           category="角色/鸣潮/今州",
           ctx=((r"モルトフィ", "莫托菲"), (r"モルトフィ", "莫特菲")),
           note="鸣潮 4★ 热熔·佩枪，出身新联邦上流阶层，'新联邦最年轻的天才'，"
                "以华胥研究院外聘成员身份工作（百度百科/灰机wiki）。谷翻音译作'莫托菲'。"),
    Entity("卡提希娅", modes=("ja",), ja="カルテジア",
           category="角色/鸣潮",
           ctx=((r"カルテジア|カテジア", "笛卡尔西亚"), (r"カルテジア|カテジア", "卡尔特西亚"),
                (r"カルテジア|カテジア", "卡特吉亚"), (r"カルテジア|カテジア", "塔尔提加"),
                (r"カルテジア|カテジア", "卡特迪亚"),
                # 2026-10-14 补（鸣潮 2.4 七丘 ja 片实测；⚠ 长键须先于「笛卡尔」）：
                (r"カルテジア|カテジア|カルデジア", "笛卡尔"),
                (r"カルテジア|カテジア|カルデジア", "卡尔西亚"),
                (r"カルテジア|カテジア|カルデジア", "卡特西亚"),
                (r"カルテジア|カテジア|カルデジア", "卡特齐亚"),
                (r"カルテジア|カテジア|カルデジア", "卡尔德齐亚"),
                (r"カルテジア|カテジア|カルデジア", "卡尔蒂吉亚"),
                (r"カルテジア|カテジア|カルデジア|タルテジア", "塔尔提齐亚"),
                (r"カルテジア|カテジア|カルデジア", "Cartégia")),
           note="鸣潮 5★。日语 カルテジア；谷翻音译残留 笛卡尔西亚/卡尔特西亚/卡特吉亚/塔尔提加。"
                "⚠ 2026-10-14：原先 JA_TERMS 里的无条件键「笛卡尔」会抢跑本条 ctx，"
                "把「笛卡尔西亚」咬成「卡提希娅西亚」；已撤键、改由本条 ctx 统一收口"
                "（笛卡尔/卡尔西亚/卡特西亚/卡特齐亚/卡尔德齐亚/卡尔蒂吉亚/塔尔提齐亚/Cartégia）。"),
    Entity("夏空", modes=("ja",), ja="シャコンヌ",
           category="角色/鸣潮",
           ctx=((r"シャコンヌ", "恰空舞"), (r"シャコンヌ", "恰空")),
           note="鸣潮 5★。日语 シャコンヌ（Ciaccona）；谷翻按音乐术语译成'恰空舞'。"),
    Entity("超频", modes=("ja",), ja="オーバークロック",
           category="术语/鸣潮",
           note="鸣潮术语：频率能量异常带来的危险状态（灰机wiki《无音区》提到'超频'）。"
                "本片谷翻已正确输出'超频'，仅登记元数据，无替换。"),
    Entity("延奏", modes=("ja",), ja="延奏スキル",
           category="术语/鸣潮",
           ctx=((r"収走|収層|延奏", "收走"), (r"収走|収層|延奏", "收层"),
                (r"収走|収層|延奏", "跑步技能"), (r"収走|収層|延奏", "逃跑"),
                (r"収走|収層|延奏", "收奏")),
           note="鸣潮技能体系（2026-10-01 二次校准坐实官方用字）："
                "共鸣技能 / 共鸣回路 / 共鸣解放 + 变奏技能（入场）/ 延奏技能（离场）。"
                "官方描述：'协奏能量充满时切换共鸣者，离场角色会触发延奏技能'"
                "（Fandom《变奏技能》、百度百科《变奏技能》）。日语 ASR 作 収走スキル(しゅうそう)、"
                "谷翻译成'跑步技能/逃跑/收走'。⚠ 首轮曾按同音误作'终奏'，已改正。"
                "canonical 用'延奏'（不带'技能'），因日语行的'スキル'会由机翻补成'技能'。"),
    Entity("终奏技能", modes=("ja",), ja="収走スキル",
           category="术语/鸣潮",
           note="鸣潮技能体系：共鸣技能/共鸣回路/共鸣解放 + 变奏技能/终奏技能（Outro Skill）。"
                "日语 ASR 作 収走スキル(しゅうそう)，谷翻译成'跑步技能/逃跑/收走'。"
                "⚠ 本条只登记元数据、不加规则：'终奏/延奏'的官方中文用字尚未坐实，"
                "本片按'终奏'处理并留待后续片源验证，勿贸然固化为规则。"),
    # ============================================================
    # 2026-10-14 鸣潮 2.4「七丘」篇（第二章第六幕）日语原声 VTuber 反应片沉淀
    #   片源：D:\原片\【#鳴潮 】完全初見～２章第６幕…（2136 cue，ja 参考行 + 谷翻中字）
    #   官方依据：萌娘百科《鸣潮/译名对照表》、库洛 2.4 公告、17173/知乎/NGA 剧情考据、
    #             百度百科《七丘》《克里斯托弗》《起源信标》、18183《尤诺》介绍。
    #   戒律（沿本文件既有约定）：谷翻把同一专名译成多形（蜜芽→宫/米娅/美雅/米安 共 9 形），
    #     故**一律走 ctx（日语参考行佐证）**；variants 裸键只收**生僻非词**形。
    #     常用词（果糖/印象/美式/明式/百合/解说员/敲诈者/银家…）绝不裸键。
    # ============================================================
    Entity("蜜芽", modes=("ja",), en="Mya", ja="ミア", ko="미아",
           category="角色/鸣潮2.4七丘",
           ctx=((r"ミ[ヤやア]|(?<!お)みや", "宫酱"), (r"ミ[ヤやア]|(?<!お)みや", "宫野"),
                (r"ミ[ヤやア]|(?<!お)みや", "野宫"), (r"ミ[ヤやア]|(?<!お)みや", "美宫"),
                (r"ミ[ヤやア]|(?<!お)みや", "宫侑"), (r"ミ[ヤやア]|(?<!お)みや", "宫宫"),
                (r"ミ[ヤやア]|(?<!お)みや", "米安"), (r"ミ[ヤやア]|(?<!お)みや", "米娅"),
                (r"ミ[ヤやア]|(?<!お)みや", "美雅"),
                # ⚠ 谷翻把「宮(人名)」与「宮殿(宫殿)」同译成「宫」：只能靠日语行区分
                (r"宮(?!殿)", "宫殿"),                          # 参照行是裸 宮 -> 宫殿 其实是人名
                (r"^\s*(?!.*宮殿)(?=.*(?:ミ[ヤやア]|(?<!お)みや))", "宫")),   # 有ミや且整行无宮殿 -> 裸宫=人名
           note="鸣潮 2.4 七丘·被鸣式寄宿的角斗士（官方英 Mya，日 ミア）。"
                "⚠ 裸「宫」绝不可作无条件变体：'地下宫殿'是字面宫殿（本片 #913/#1046）。"
                "裸宫用人名判据「整行有ミや且无宮殿」锚定；'宮(?!殿)' 判 宫殿=人名（#184/#192/#455）。"),
    Entity("七丘", modes=("ja",), en="Septimont", ja="セブン・ヒルズ",
           category="地点/鸣潮2.4七丘",
           ctx=((r"セブン", "七脚尖"), (r"セブン", "七山镇"), (r"セブン", "七丘镇"),
                (r"セブン", "七座山丘"), (r"セブン", "七休斯"), (r"セブン", "七脚"),
                (r"セブン", "七山"), (r"セブン", "七杀"),
                (r"セブン", "Seven Hills"), (r"セブン", "Seven Hill"),
                (r"セブン", "Semun Hills"), (r"セブン", "帕塞文山镇"),
                (r"セブン", "7-Eleven"),
                (r"セムン", "Semun Hills"),
                (r"セーヒル", "《萨希尔家族》"), (r"セーヒル", "萨希尔")),
           note="鸣潮 2.4 新区域（库洛 2.4 公告「全新区域：七丘」；英 Septimont / 日 セブン・ヒルズ）。"
                "谷翻译名极乱：七山/七脚/七休斯/七杀/Seven Hills/Semun Hills/7-Eleven/萨希尔(セーヒルズ)。"
                "⚠ 全部走 ctx（锚 セブン），'七山'不裸键（可能是他片真实地名）。"),
    Entity("黑潮", modes=("ja",), en="The Dark Tide", ja="黒潮",
           category="术语/鸣潮2.4七丘",
           ctx=((r"黒塩|黒シオ|クロシオ", "黑盐"), (r"黒塩|黒シオ|クロシオ", "黑汐"),
                (r"クロシオ", "Crocio"), (r"黒塩|黒シオ", "黑色盐云"), (r"黒シオ", "黑西奥格")),
           note="官方中文=黑潮（英 The Dark Tide / 日 黒潮くろしお）。"
                "ASR 把 くろしお 写成 黒塩/黒シオ，谷翻出「黑盐/黑汐/Crocio」（本片 17 处）。"),
    Entity("鸣式", modes=("ja",), en="Threnodian", ja="鳴式",
           category="术语/鸣潮2.4七丘",
           ctx=((r"名式|鳴式|明識", "明植"), (r"名式|鳴式|明識", "明式"),
                (r"名式|鳴式|明識", "明識"), (r"名式|鳴式|明識", "明室"),
                (r"名式|鳴式|明識", "内式"), (r"名式|鳴式|明識", "名式"),
                (r"名式|鳴式|明識", "美石"), (r"名式|鳴式|明識", "美式"),
                (r"名式|鳴式|明識", "纳西克")),
           note="官方中文=鸣式（英 Threnodian / 日 鳴式めいしき）。ASR 把 めいしき 咬成 名式/明識，"
                "谷翻出 明植/明式/明室/内式/美石/美式/纳西克（本片 27 处）。"
                "⚠ 全部走 ctx：'美式'(美式咖啡)、'明式'(明式家具) 都是真实用词，绝不裸键。"),
    Entity("拉古那", modes=("ja",), en="Ragunna", ja="ラグーナ",
           category="地点/鸣潮2.x",
           variants=("拉古纳",),
           note="黎那汐塔地区，官方中文=**拉古那**（萌娘百科译名对照表，非'拉古纳'）。日 ラグーナ。"),
    Entity("残星会", modes=("ja",), en="Fractsidus", ja="残星組織",
           category="势力/鸣潮2.x",
           ctx=((r"フラクト|シデス", "弗拉克西德"), (r"フラクト|シデス", "Fractacides"),
                (r"フラクト|シデス", "弗鲁克托西雷斯"), (r"フラクト|シデス", "断裂酸"),
                (r"フラクト|シデス", "碎酸"), (r"フラクト|シデス", "赛兹"),
                (r"シデス", "《Sides》"), (r"シデス", "Sides"),
                (r"フラクト|シデス", "果糖")),
           note="官方中文=残星会（英 Fractsidus / 日 残星組織フラクトシデス）。"
                "ASR 常截断成 シデス；谷翻出 弗拉克西德/Fractacides/弗鲁克托西雷斯/断裂酸/碎酸/赛兹，"
                "并曾把 フラクトシデス 听成 fructose → 译作「果糖」。⚠ 「果糖」是常用词，必须 ctx 锚定。"),
    Entity("残象", modes=("ja",), en="Tacet Discord", ja="残像",
           category="术语/鸣潮",
           ctx=((r"残像|残響", "印象"), (r"残像|残響", "Afterimage")),
           note="官方中文=残象（英 Tacet Discord / 日 残像ざんぞう）。"
                "谷翻把 残像 当汉语常用词译成「印象」→ 必须 ctx 锚定，绝不裸键。"),
    Entity("英白拉多", modes=("ja",), en="Imperator", ja="インペラトル",
           category="角色/鸣潮2.x",
           variants=("imperator", "impirator", "インピラトル"),
           note="官方中文=英白拉多（英 Imperator / 日 インペラトル）。"
                "谷翻把英文残留 imperator/impirator 直接抄进中文行，生僻裸键安全。"),
    Entity("黎那汐塔", modes=("ja",), en="Rinascita", ja="リナシータ",
           category="地点/鸣潮2.x",
           variants=("Linashita", "Linasy"),
           note="官方中文=黎那汐塔（英 Rinascita / 日 リナシータ）。ASR 常截断成 リナシー，"
                "谷翻出英文残留 Linashita/Linasy，生僻裸键安全。"),
    Entity("尤利娅", modes=("ja",), ja="ユリア",
           category="角色/鸣潮2.4七丘",
           variants=("尤莉娅",),
           ctx=((r"ユリア", "百合"),),
           note="鸣潮 2.4 七丘·**西尔瓦家**家主（保守派，与克里斯托弗交易打捞蜜芽遗体）。"
                "官方中文=尤利娅（17173《2.4版本剧情究竟讲了什么》/ 知乎 2.4 评析）。"
                "谷翻作 尤莉娅，并曾把 ユリア 译成「百合」（本片 #1904）。⚠ 「百合」是常用词，走 ctx 锚定。"),
    Entity("克里斯托弗", modes=("ja",), en="Cristoforo", ja="クリストフォロ",
           category="角色/鸣潮2.x/残星会",
           ctx=((r"クリストフ", "克里斯托弗洛"), (r"クリストフ", "克里斯托弗罗"),
                (r"クリストフ", "克里斯托福尔"), (r"クリストフ", "克里斯托法罗"),
                (r"クリストフ", "克里斯托福罗"), (r"クリストフ", "克里斯托菲罗")),
           note="鸣潮 2.x 幕后布局者、**残星会会监**兼「不入流的剧作家」（百度百科《克里斯托弗》）。"
                "日 クリストフォロ。谷翻给出 6 种音译形（本片 #557/#660/#934/#1095/#1534/#1535）。"),
    Entity("荣耀之间", modes=("ja",), ja="グローリアベイル",
           category="地点/鸣潮2.4七丘",
           ctx=((r"グローリア", "格洛丽亚·韦尔"), (r"グローリア", "荣耀庄园"),
                (r"グローリア", "荣耀面纱"), (r"グローリア", "荣耀镇"),
                (r"グローリア", "Gloriavale"), (r"グローリア", "格洛丽亚")),
           note="鸣潮 2.4 七丘地标（NGA《黎那汐塔时间线》「蜜芽于七丘大角斗赛获胜后前往**荣耀之间**」；"
                "B站「露帕把蜜芽的剑插在荣耀之间」）。日 グローリアベイル/グローリアベール。"
                "谷翻译名 5 种：荣耀镇/荣耀庄园/荣耀面纱/格洛丽亚·韦尔/Gloriavale（本片 6 处）。"),
    Entity("西尔瓦家族", modes=("ja",), en="Silver Family", ja="シルバファミリー",
           category="家族/鸣潮2.4七丘",
           ctx=((r"シルバファミリー|シルバーファミリー", "席尔瓦家族"),
                (r"シルバファミリー|シルバーファミリー", "银家族"),
                (r"シルバファミリー|シルバーファミリー", "银家")),
           note="鸣潮 2.4 七丘望族（18183《尤诺》「西尔瓦家家主尤利娅」；B站人物志「西尔瓦家被逐出七丘」）。"
                "官方中文=**西尔瓦**（非'席尔瓦'）。⚠ 锚点强制全称 シルバファミリー："
                "`シルバーウィーク`(Silver Week 假期) 与 `シルバーメイク`(银色妆容) 都不是家族，绝不裸键「银」。"),
    Entity("总督", modes=("ja",), en="Governor", ja="総督",
           category="官职/鸣潮2.4七丘",
           ctx=((r"総督|相徳|総徳|そうとく", "斋德"),
                (r"総督|相徳|総徳|そうとく", "宗德"), (r"総督|相徳|総徳|そうとく", "总德")),
           note="鸣潮 2.4 七丘执政官（知乎 2.4 剧情评析「看不惯现任**总督**」；现任总督=奥古斯塔）。"
                "ASR 把 総督(そうとく) 咬成 相徳/総徳，谷翻出 斋德/宗德/总德/总德府（本片 4 处）。"),
    Entity("中枢", modes=("ja",), en="Nexus", ja="中数",
           category="术语/鸣潮2.4七丘",
           ctx=((r"中数", "中间的数字"), (r"中数", "中间数字"), (r"中数", "大仲苏")),
           note="七丘/黎那汐塔的设施中枢（17173《主线概览》「你与露帕一同前往**岩间中枢**」）。"
                "ASR 把 中枢(ちゅうすう) 咬成同音 中数，谷翻直译成「中间的数字/大仲苏」。"
                "⚠ 走 ctx（「数字」是常用词）。"),
    Entity("特克斯", modes=("ja",), en="Tex", ja="テクス",
           category="角色/鸣潮2.4七丘（音译待考）",
           variants=("北德克萨斯", "Tex"),
           note="鸣潮 2.4 七丘剧情人物（当时的**总督之子**，雕像原型）。⚠ 官方中文名**未查证**，"
                "沿用谷翻自产音译「特克斯」；「北德克萨斯」（北 Texas）是误译，英文残留 Tex 一并归一。"),
    Entity("奥古斯塔", modes=("ja",), en="Augusta", ja="オーガスタ",
           category="角色/鸣潮2.x",
           variants=("奥古斯特",),
           note="鸣潮 2.x 七丘总督奥古斯塔（18183《尤诺》「向总督奥古斯塔指控」；3.x 实装 5★）。"
                "日 オーガスタ。谷翻作「奥古斯特」，官方用字为「奥古斯塔」。"),
    # --- 2026-10-04 鸣潮 3.7 英文原声反应片（MarcoMeatball「Xuanfang is Over」7225 cue）二次校准沉淀 ---
    Entity("玄方", modes=("bi",), en="Xuan / Schwan",
           category="地名/鸣潮3.7",
           variants=("Schwang", "Schwan", "施万方", "施旺丰",
                     "施万", "施旺", "方旺"),
           note="梦州·玄方地界（3.5 上线，3.7 玄方篇收官）。英文服作 Xuan（ASR 常咬成 Schwan/Schwang），"
                "谷翻音译残留『施万/施旺/方旺』系（施万方堡/施旺丰堡→玄方城，见 Entity('玄方城')）。"
                "⚠ 裸键『施万/施旺』须短于『施万丰/施万夫/施万方堡』等长键，靠长键先行防半截替换。"),
    # ============================================================
    # 2026-10-05《鸣潮》3.7 剧情反应视频字幕精校报告 · 核心术语订正总表沉淀
    #   来源：H:\精校修改对照报告.md（5026 条逐句精校，术语总表 45 项）。
    #   用户裁决：① Arbiter 官方中文=御者（BILINGUAL_TERMS 旧映射'仲裁者'已改，
    #   与韩语模式 어자->御者 一致）；② Sheen/Hsin 保留脚本现有全名'心月狐'，
    #   不按报告简称改'心'（'心'为分身，与本体'心月狐'是两个对象）。
    #   戒律（严格遵循本文件既有约定）：
    #     · 官方中文做 canonical；modes 默认 ("bi",)（报告为中英双语片源）。
    #     · variants（裸键，出现即改）：只放**生僻**中文机翻错形 + **生僻**英文残留专名。
    #     · ctx（参考行正则锚定）：放**歧义常用词**（寿司/圣所/天体/皇帝/朱/战争部…），
    #       靠英文 ASR 变体命中参考行才改，绝不裸键。
    #     · 常用英文词（Sushi/Swimming/Sanctum/Imperator/Celestials…）一律不作裸键。
    # ============================================================
    Entity("溯心", modes=("bi",), en="Suxin",
           category="角色/岁主·鸣潮3.7",
           variants=("Susheen", "susheen", "Sushin", "Sushun"),
           ctx=((r"\bSuxin\b|\bSusheen\b|\bSushin\b|\bSushun\b", "苏珊"),
                (r"\bSuxin\b|\bSusheen\b|\bSushin\b|\bSushun\b", "寿司")),
           note="天罗狐影异变体（3.7 精校报告核心术语表）。ASR 把 Suxin 咬成 "
                "Susheen/Sushin/Sushun/Sushi；谷翻按字面出'苏珊'(Susan)/'寿司'(sushi)。"
                "戒律：'苏珊/寿司'均常用词，绝不裸键，只走参考行 Suxin/Susheen/Sushin/Sushun 系锚定；"
                "⚠ ASR 变体 'Sushi' 与真食物寿司同形，已从佐证正则剔除"
                "（2026-10-05 实测'I love eating sushi'被误改成'溯心'）：宁可漏改被咬成 "
                "sushi 的溯心，不可误伤食物语境；英文残留 Susheen/Sushin/Sushun 生僻，裸键安全。"),
    Entity("御者", modes=("bi",), en="Arbiter",
           category="称号/术语·鸣潮3.7",
           variants=("Abiter",),
           ctx=((r"\bArbiter\b|\bAbiter\b|\bAlberta\b", "仲裁者"),
                (r"\bArbiter\b|\bAbiter\b|\bAlberta\b", "仲裁员"),
                (r"\bArbiter\b|\bAbiter\b|\bAlberta\b", "阿尔伯塔")),
           note="3.7 心对漂泊者的称呼，官方中文=御者（韩语模式 어자->御者 已沉淀）。"
                "本轮用户裁决：BILINGUAL_TERMS 旧映射 Arbiter->'仲裁者' 已改 '御者'。"
                "ASR 变体 Abiter/Alberta；谷翻出'仲裁者/仲裁员/阿尔伯塔'(Alberta=加拿大省)，"
                "均歧义走 ctx；英文残留 Abiter 生僻裸键，Arbiter 裸键已在扁平表(->御者)。"),
    Entity("谛天鉴", modes=("bi",), en="Ministry of Sentinel Affairs",
           category="势力/官署·鸣潮3.7",
           variants=("岁主事务部", "哨兵事务部", "谛天监", "Ministry of Sentinel Affairs"),
           note="锁暝执掌、专管岁主事务的组织，官方中文=谛天鉴（ja 表已有 谛天监->谛天鉴，"
                "本轮补 bi）。机翻两种字面错译均须收：Sentinel 译'哨兵'->'哨兵事务部'、"
                "译'岁主'->'岁主事务部'（2026-10-05 用户指正：'岁主事务部'为错误翻译，"
                "官方中文=谛天鉴）。二者均为生僻组合，裸键安全；英文整词残留同收。"
                "⚠ 级联（有意为之）：中文行'Sentinel事务部' 先由裸键 Sentinel->岁主 得到"
                "'岁主事务部'，再由本键收束成'谛天鉴'（长键先行，terms-check 会列出此级联）。"),
    Entity("州监", modes=("bi",), en="Intendant",
           category="官职/术语·鸣潮3.7",
           variants=("Intendant", "intendence"),
           note="梦州官职（锁暝任州监，官方档案'谛天鉴州监'）。ASR 把 Intendant 咬成 "
                "intended/intendence；戒律：'intended' 是常用英文词，绝不裸键（本轮不收，"
                "防误伤），只收生僻的 Intendant/intendence 英文残留。"),
    Entity("稷廷", modes=("bi",), en="Court of Savantae",
           category="势力/组织·鸣潮3.7",
           variants=("萨凡特宫廷", "桑特宫廷", "Court of Savante", "Savante", "Sante", "Cante"),
           note="旧时代机巧科研组织，官方中文=稷廷（韩语模式 직정->稷廷 已沉淀）。"
                "ASR 变体 Court of Savante/Sante/Cante；谷翻'萨凡特宫廷'生僻组合裸键安全。"),
    Entity("军策府", modes=("bi",), en="Ministry of War",
           category="势力/官署·鸣潮3.7",
           variants=("Ministry of War",),
           ctx=((r"\bMinistry of War\b", "战争部"),),
           note="梦州军事官署，官方中文=军策府。谷翻按字面出'战争部'（普通词组），"
                "走参考行 Ministry of War 锚定；英文整词残留裸键安全。"),
    Entity("朝月会", modes=("bi",), en="Waking Moon Festival",
           category="节日/术语·鸣潮3.7",
           variants=("唤醒月亮节", "Waking Moon Festival", "Moonchasing Festival"),
           note="玄方篇节日，官方中文=朝月会。ASR/旧译 Waking Moon Festival / Moonchasing "
                "Festival；谷翻'唤醒月亮节'生僻组合裸键安全。戒律：脚本别处注释曾提'追月节'，"
                "官方名待核，本轮不收，防误并。"),
    Entity("万相神宫", modes=("bi",), en="(Manifold) Sanctum",
           category="地点/建筑·鸣潮3.7",
           variants=("sectum",),
           ctx=((r"\bManifold Sanctum\b|\bmanifold sanctum\b|\bSanctum\b|\bsectum\b", "圣所"),),
           note="玄方篇建筑，官方中文=万相神宫。ASR 把 Sanctum 咬成 sectum；谷翻'圣所'"
                "（普通词）走参考行 Sanctum 系锚定；英文残留 sectum 生僻裸键，"
                "'Sanctum' 单独歧义不裸键。"),
    Entity("锦妙锁", modes=("bi",), en="Providence Lock",
           category="物品/术语·鸣潮3.7",
           variants=("天意锁", "Providence Lock", "Providence lock",
                     "普罗维登斯锁", "普罗维登斯船闸"),   # 2026-10-05 二次校准：谷翻音译/lock 误译"船闸"
           note="3.7 版本主题'镜锁妄世'相关，官方中文=锦妙锁。谷翻按字面出'天意锁'"
                "（Providence=天意），生僻组合裸键安全；英文词组残留同收。"),
    Entity("玄朱锁", modes=("bi",), en="Vermilion Lock",
           category="物品/术语·鸣潮3.7",
           variants=("朱红锁", "Vermilion Lock", "Vermillion lock"),
           note="与锦妙锁并列的'锁'，官方中文=玄朱锁。ASR 变体 Vermillion；谷翻'朱红锁'"
                "（Vermilion=朱红）生僻组合裸键安全；戒律：'Vermilion' 单独歧义（朱红色）"
                "不裸键，只收带 Lock 的词组。"),
    Entity("天人", modes=("bi",), en="Celestials",
           category="术语/群体·鸣潮3.7",
           ctx=((r"\b[Cc]elestials\b", "天体"),),
           note="玄方/梦州的'天人'群体（与凡人相对），官方中文=天人（ko 模式 천인->天人 已沉淀）。"
                "谷翻按字面把 celestials 出'天体'（天文常用词），必须走参考行锚定，绝不裸键。"
                "⚠ 佐证正则强制复数 celestials（2026-10-05 实测：单数 'celestial bodies "
                "twinkle'=真天体，被误改成'天人'）；指群体的天人英文用复数，故收窄不漏。"
                "canonical'天人'本身无错形裸键。"),
    Entity("解形煞", modes=("bi",), en="Form Renders",
           category="敌人/术语·鸣潮3.7",
           variants=("形态渲染器", "形态渲染", "forenders"),
           note="玄方篇敌对存在，官方中文=解形煞。ASR 把 Form Renders 咬成 for renters/"
                "forenders；谷翻按字面出'形态渲染器/形态渲染'（render=渲染）生僻组合裸键安全；"
                "英文残留 forenders 生僻裸键，'form renders/for renters' 歧义不裸键。"),
    Entity("玄翎雀", modes=("bi",), en="Xuanling Bird",
           category="生物/传说·鸣潮3.7",
           variants=("Shrening Bird", "Shrenling", "Schwanling", "shrening 鸟", "Shrening 鸟",
                     "玄方林鸟", "山陵鸟"),
           note="玄方城传说灵鸟（叼子以身开城门），官方中文=玄翎雀（ko 模式 혈령작->玄翎雀 已沉淀）。"
                "ASR 把 Xuanling 咬成 Shrening/Shrenling/Schwanling；谷翻残留'shrening 鸟'。"
                "英文错形均生僻，裸键安全。"),
    Entity("恶瘴", modes=("bi",), en="Evil Miasma",
           category="术语/灾厄·鸣潮3.7",
           variants=("邪恶瘴气", "邪恶的瘴气", "Evil Miasma", "evil Miasma"),
           note="华亭故乡灾厄（官方档案'故乡「恶瘴」之厄'），官方中文=恶瘴（ko 模式 악장->恶瘴 已沉淀）。"
                "谷翻'邪恶瘴气'生僻组合裸键安全；戒律：'Miasma' 单独歧义（瘴气普通词）不裸键，"
                "只收带 Evil 词组。"),
    Entity("渊城", modes=("bi",), en="Yuan Fortress",
           category="地点/鸣潮3.7",
           variants=("Yuan Fortress", "Yan Fortress", "Tuan Fortress"),
           ctx=((r"\bYuan Fortress\b|\bYan Fortress\b|\bTuan Fortress\b|\bYuan\b", "元堡"),),
           note="云渊之役相关地点，官方中文=渊城。ASR 把 Yuan 咬成 Yan/Tuan；谷翻'元堡'"
                "（'元'常用字）走参考行 Yuan Fortress 锚定；英文词组残留裸键安全。"),
    Entity("云渊之役", modes=("bi",), en="Yuan Fortress–Gorges War",
           category="事件/术语·鸣潮3.7",
           variants=("堡垒与华丽的战争",),
           note="渊城与云凌谷之战（简称云渊之役），官方中文=云渊之役。ASR 把 Gorges 咬成 "
                "gorgeous/Spirits（fortress and gorgeous war / Gorges of Spirits）；"
                "谷翻整句'堡垒与华丽的战争'生僻，裸键安全。"),
    Entity("梦枢", modes=("bi",), en="Nexus Axis",
           category="地点/术语·鸣潮3.7",
           variants=("词典轴", "lexicon axis"),
           note="中枢（Nexus Axis），官方中文=梦枢。⚠ 与 Entity('梦枢天罗')(Simulacrum Nexus) "
                "为不同对象，勿混。ASR 把 Nexus 咬成 lexicon；谷翻'词典轴'（lexicon=词典）"
                "生僻组合裸键安全。canonical'梦枢'(2字)与'梦枢天罗'长键先行不级联。"),
    Entity("芙露德莉丝", modes=("bi",), en="Frudelis",
           category="角色/残星会·鸣潮3.7",
           variants=("芬特利亚", "Frudelis", "Fentellia", "Fentilia"),
           note="残星会成员，官方中文=芙露德莉丝。ASR 把 Frudelis 咬成 Fentellia/Fentilia；"
                "谷翻'芬特利亚'音译残留。英文/中文错形均生僻，裸键安全。"),
    Entity("英白拉多", modes=("bi",), en="Imperator",
           category="角色/残星会·鸣潮3.7",
           variants=("Imperator",),
           ctx=((r"\bImperator\b", "皇帝"),),
           note="残星会首领，官方中文=英白拉多（Imperator 拉丁'统帅/皇帝'）。谷翻按字面出"
                "'皇帝'（极常用词）必须走参考行 Imperator 锚定，绝不裸键；英文残留 Imperator "
                "生僻裸键。"),
    Entity("角", modes=("bi",), en="Jue",
           category="角色/岁主·鸣潮3.7",
           variants=("Jue",),
           ctx=((r"\bJue\b", "朱"),),
           note="今州岁主，官方中文=角（单字）。⚠ 高风险术语：canonical'角'与错形'朱'均极常用，"
                "'朱'（姓氏/红色）只走参考行 \\bJue\\b 强锚定才改，绝不裸键；英文残留 Jue 生僻裸键。"
                "ASR 变体 Ju 太短歧义，本轮不收。"),
    Entity("命运棱镜", modes=("bi",), en="Prism of Fate",
           category="物品/术语·鸣潮3.7",
           variants=("信仰棱镜", "Prisma Fate", "prism of faith", "Prism of Fate"),
           note="官方中文=命运棱镜。ASR 把 Fate 咬成 faith、Prism 咬成 Prisma；谷翻'信仰棱镜'"
                "（faith=信仰）生僻组合裸键安全；英文词组残留同收。"),
    Entity("同宁", modes=("bi",), en="Tongning",
           category="角色/NPC·鸣潮3.7",
           variants=("佟宁", "唐宁", "唐同宁", "Tanging", "Tong Ning", "Tonging"),
           note="NPC（音译，无官方出处，报告标注为音译/语境译）。ASR 把 Tongning 咬成 Tonging；"
                "谷翻'佟宁/唐宁'音译残留。英文/中文错形均生僻，裸键安全。"),
    # ============================================================
    # 2026-10-05《鸣潮》3.7 reaction 片（Wuthering Waves 3.7 Was Absolute Cinema）
    #   二次校准补录：**英文残留专名**。谷翻/ASR 常把官方专名整词留成英文，直接夹在
    #   中文行里（"Lady Shin" "Swanfun hold" "tacet discord"），既有表只覆盖中文错形，
    #   未覆盖英文残留本身。本段按 canonical 追加英文残留错形；canonical 与既有实体
    #   一致，注册走 setdefault，不产生冲突。
    #   戒律：生僻英文残留（Swanfun/Tacid/Henodian…）可裸键；常用英文词
    #   （Shin/Swing/Mojo/tacet/Rena…）一律走 ctx 参考行锚定，绝不裸键。
    # ============================================================
    Entity("心月狐", modes=("bi",), en="Shin",
           category="角色/岁主·鸣潮3.7",
           variants=("Moonf Fox", "Moonfox", "Moonforks", "Boomfox",
                     "Moon Forks", "月亮叉子"),
           ctx=((r"\bShin\b", "Shin"),),
           note="英文残留补录：'Shin'（shin=胫骨，常用英文词）只走 ctx；Moonf Fox/"
                "Moonfox/Moonforks/Moon Forks 为 ASR 咬断残留，生僻可裸键。"
                "⚠ 绝不登记短键 'Moonf'（会咬断 'Moonfox' 成 '心月狐ox'，实测踩坑）。"
                "⚠ 'Lady Shin'→'心月狐女士' 目标≠canonical，见 CONTEXT_MAP。"),
    Entity("玄方城", modes=("bi",), en="Schwanfong Hold",
           category="地名/鸣潮3.7",
           variants=("Swanfun", "Swanfung", "Swanfunhold", "Shrenfong", "Shrenfong Hold",
                     "Shranfong", "Shranong", "Shanfang", "Shung Fang", "Funhold"),
           note="英文残留补录：ASR 把 Schwanfong 咬成 Swanfun/Shrenfong/Shranfong/"
                "Shanfang/Shung Fang/Funhold 等，谷翻整词留英文；均为生僻拼写，裸键安全。"),
    Entity("梦州", modes=("bi",), en="Mengzhou",
           category="地名/鸣潮",
           variants=("MJO", "Mghao", "Monga"),
           ctx=((r"\bMojo\b", "Mojo"),),
           note="英文残留补录：MJO/Mghao/Monga 为 ASR 变体，生僻可裸键；"
                "'Mojo' 是常用英文词（mojo=魔力），只走 ctx。"
                "⚠ 不收 'Monguan'（会咬断专名 'Monguan Veil' 成 '梦州 Veil'，实测踩坑）。"),
    Entity("今州", modes=("bi",), en="Jinzhou",
           category="地名/鸣潮",
           variants=("Ginjo", "Jinjo", "Jinzhou"),
           note="英文残留补录：ASR 把 Jingo 咬成 Ginjo/Jinjo，谷翻留英文 'Jinzhou'。"),
    Entity("清宵", modes=("bi",), en="Qingxiao",
           category="角色/鸣潮3.7",
           variants=("Singsha", "Sing Shiao", "Sing Sha"),
           note="英文残留补录：Ching Sha 的 ASR 变体 Singsha/Sing Shiao/Sing Sha。"),
    Entity("锁暝", modes=("bi",), en="Suoming",
           category="角色/鸣潮3.7",
           variants=("Smain",),
           ctx=((r"\bSwing\b", "Swing"), (r"\bSwinging\b", "Swinging")),
           note="英文残留补录：Suoming→Smain（ASR）；'Swing/Swinging' 是常用英文词，"
                "只走 ctx 参考行锚定。"),
    Entity("蛇菰", modes=("bi",), en="Balanophora",
           category="角色/鸣潮3.7",
           variants=("Balanar", "Belenor", "Balanophora", "巴拉纳尔", "贝勒诺尔",
                     "巴拉诺弗拉", "Bambee", "蛇骨", "an aphora"),
           note="官方中文=蛇菰（TapTap《共鸣者「锁暝」PV | 契阔》CV 表 2026-10-20："
                "蛇菰：卢晓彤）；3.7 剧情：残星会女会监、谛天鉴州监，刺杀心月狐本体。"
                "Balanar/Belenor 是 Balanophora 的 ASR 漏音节形；"
                "⚠ 巴拉纳福是另一形 Balanafor 的旧译，勿混。"),
    Entity("玄翎雀", modes=("bi",), en="Xuanling Bird",
           category="生物/鸣潮3.7",
           variants=("Shenling", "Schwrenling"),
           note="英文残留补录：Shrenling 的 ASR 变体 Shenling/Schwrenling。"),
    Entity("拉海洛", modes=("bi",), en="Lahai-Roi",
           category="地名/鸣潮",
           variants=("La Hai Roy", "La Hyroy", "La Hairoy", "Lahiroy"),
           note="英文残留补录：Lahai-Roi 的 ASR/谷翻残留 La Hai Roy/La Hyroy/Lahiroy。"),
    Entity("残星会", modes=("bi",), en="Fractsidus",
           category="组织/鸣潮",
           variants=("Fractsidus", "Fractidus", "弗赖杜斯"),
           note="英文残留补录：Fractsidus/Fractidus 英文残留整词留行（'Fraidus' 既有表"
                "已映射为正确英文 Fractsidus，此处不重复登记）。"
                "本片补录：谷翻把 Fraidus 音译成'弗赖杜斯'（生僻裸键；既有表另有'弗雷杜斯'）。"),
    Entity("残象", modes=("bi",), en="Tacet Discord",
           category="术语/鸣潮",
           variants=("Tacid", "Taca", "tacetern", "Tacid Discord", "Taca Discord",
                     "tacet discord", "tacet discords"),
           ctx=((r"\btacet\b", "tacet"),),
           note="英文残留补录：Tacet Discord 官方中文=残象。Tacid/Taca/tacetern 为 ASR "
                "变体，生僻可裸键；小写 'tacet' 是乐理词（tacet=休止），只走 ctx。"),
    Entity("鸣式", modes=("bi",), en="Threnodian",
           category="术语/鸣潮",
           variants=("Henodian",),
           note="英文残留补录：Threnodian 的 ASR 变体 Henodian。"),
    Entity("玄朱锁", modes=("bi",), en="Vermilion Lock",
           category="物品/鸣潮3.7",
           variants=("Villion lock", "Villion locks", "Vermillion lock", "Vermillion locks"),
           note="英文残留补录：Vermillion→Villion 的 ASR 变体，谷翻留英文整词。"),
    Entity("梦枢天罗", modes=("bi",), en="Simulacrum Nexus",
           category="地点/新地区",
           variants=("Simulator Nexus", "Simulacrum Nexus", "Simulacrim Nexus",
                     "Simulacum Nexus", "Acrim Nexus"),
           note="英文残留补录：梦枢天罗 = Simulacrum Nexus；ASR 把 Simulacrum 咬成 "
                "Simulator/Simulacrim/Simulacum/Acrim，谷翻把 Nexus 直译'枢纽'。"),
    Entity("天罗狐影", modes=("bi",), en="Nexus Fox Shadow",
           category="地点/鸣潮3.7",
           variants=("Nexus Fox Shadow", "Fox Shadow"),
           note="英文残留补录：官方中文=天罗狐影（梦枢天罗的巨大狐影）。"),
    Entity("七丘", modes=("bi",), en="Septimont",
           category="地名/鸣潮",
           variants=("Septimont", "Septtoont"),
           note="鸣潮 2.4 地区 Septimont，官方中文=七丘（百度百科/萌娘百科；黎那汐塔下属城邦）。"),
    Entity("黎那汐塔", modes=("bi",), en="Rinascita",
           category="地名/鸣潮",
           variants=("Rinascita",),
           ctx=((r"\bRena\b", "Rena"),),
           note="鸣潮 2.x 国家 Rinascita，官方中文=黎那汐塔。'Rena' 亦为人名常用拼写，"
                "只走 ctx 参考行锚定。"),
    Entity("朝月会", modes=("bi",), en="Waking Moon Festival",
           category="活动/鸣潮3.7",
           variants=("醒中月节", "舜丰醒中月节", "Wii Moon Festival", "Wii月球节", "清醒月节"),
           note="英文残留补录：Waking Moon Festival 官方中文=朝月会；谷翻生僻错形"
                "'醒中月节/舜丰醒中月节/清醒月节/Wii月球节'；ASR 把 Waking 咬成 Wii。"),
    # ============================================================
    # 2026-10-05 第二部 3.7 reaction 片（I Wasn't Ready for How Much This Quest Would Hurt）
    #   二次校准补录：与上一部同版本，重复注册 setdefault 追加 variants/ctx。
    # ============================================================
    Entity("玄方城", modes=("bi",), en="Schwanfong Hold",
           category="地名/鸣潮3.7",
           variants=("Strongfang", "Shrungfang", "Shwanfong Hold", "Shwanfang",
                     "Schwangfang's", "Schwangfangjo", "Schwang Fong",
                     "Schwanfunhold", "Schwangfunhold"),
           note="英文残留补录（第二部片）：ASR 把 Schwanfong 咬成 Strongfang/Shrungfang/"
                "Shwanfang/Schwangfang/Schwanfunhold 等，谷翻留英文整词，均生僻裸键安全。"
                "⚠ 'Shrungfang hold'/'Shrung fun hold' 会产生 Hold hold 重复，走 EN_LINE "
                "组合键；'Schwan Funk'/'Schwanf.' 碎形同走 EN_LINE 组合键。"),
    Entity("梦州", modes=("bi",), en="Mengzhou",
           category="地名/鸣潮",
           variants=("MJ Joe", "Mang Joe", "MJ·乔"),
           ctx=((r"\bMJ\b|\bMengzhou\b", "MJ"),
                (r"\bMango\b|\bMengzhou\b", "芒果"),
                (r"\bMojo\b|\bMengzhou\b", "Mojo")),
           note="英文残留补录（第二部片）：MJ Joe/Mang Joe/MJ·乔 为 ASR+谷翻组合错形，"
                "生僻可裸键；单独 'MJ'/'Mojo' 与 '芒果'(Mango) 是常用缩写/常用词，只走 ctx；"
                "ctx 正则同时容纳 --fix-en 修正后的 Mengzhou（锚点先被 EN 组合键改写的情形）；"
                "英文行 'moving to MJ'/'Mojo and the'/'to Mango' 走 EN_LINE 组合键。"),
    Entity("梦枢天罗", modes=("bi",), en="Simulacrum Nexus",
           category="地点/新地区",
           variants=("Simakum Nexus", "Sumacum Nexus", "simakum nexus", "sumacum nexus",
                     "Simakum", "Sumacum"),
           note="英文残留补录（第二部片）：Simakum/Sumacum 为 Simulacrum 的 ASR 咬断形，"
                "谷翻留英文整词（#1462/#3266）。"),
    Entity("残象", modes=("bi",), en="Tacet Discord",
           category="术语/鸣潮",
           variants=("Tessid Discords", "Tessid Discord", "tessid discords",
                     "Tasa Discord", "特莎Discord"),
           ctx=((r"\b[Tt]ac[ei]t\b", "默许"),),
           note="英文残留补录（第二部片）：Tessid/Tasa 为 Tacet 的 ASR 变体，"
                "谷翻'特莎Discord'；'默许'仅在参考行 tacit 佐证下改残象（#5047，discords 跨行）；"
                "'默契的不和/分歧/纷争'等谷翻错形见 CONTEXT_MAP。"),
    Entity("州监", modes=("bi",), en="Intendant",
           category="称号/鸣潮3.7",
           variants=("Nintendent",),
           note="英文残留补录（第二部片 #4367）：'a Nintendent' 为 an intendant 粘连误写。"),
    Entity("守岸人", modes=("bi",), en="The Shorekeeper",
           category="角色/鸣潮",
           variants=("Lor keeper",),
           note="英文残留补录（第二部片 #1192）：Lor keeper 为 The Shorekeeper 的 ASR 漏音形。"),
    Entity("维里奈", modes=("bi",), en="Verina",
           category="角色/鸣潮",
           variants=("Verina", "维丽娜"),
           note="英文残留补录（第二部片 #4179）：谷翻'维丽娜'为 Verina 音译错形。"),
    Entity("阿布", modes=("bi",), en="Abby",
           category="角色/鸣潮3.7",
           ctx=((r"\bAbby\b", "Abby"),),
           note="3.7 角色阿布（真名阿布拉克萨斯），英文 ASR 作 Abby；'Abby' 是常见英文名，"
                "只走 ctx 参考行锚定（#2231）。"),
    Entity("心月狐", modes=("bi",), en="Shin",
           category="角色/岁主·鸣潮3.7",
           ctx=((r"\bShane\b|\bSheen\b", "Shane"),),
           note="英文残留补录（第二部片）：Shane 为 Shin 的 ASR 音近形（常见人名，只走 ctx；"
                "正则同时容纳修正后 Sheen；英文行 'like Shane' 走 EN_LINE 组合键）；"
                "'Lady' 指心月狐女士（目标≠canonical），已挂 CONTEXT_MAP 原生三元组（#1662/#3356）。"),
    Entity("锁暝", modes=("bi",), en="Suoming",
           category="角色/鸣潮3.7",
           ctx=((r"\bSwimming\b|\bSuoming\b", "Swimming"),),
           note="英文残留补录（第二部片）：大写 Swimming 为 Suoming 的 ASR 形（#1057），"
                "走 ctx（正则同时容纳修正后 Suoming）；英文行 Swimming said/adore swimming/"
                "get to swimming 走 EN_LINE 组合键。"),
    Entity("吟霖", modes=("bi",), en="Yinlin",
           category="角色/鸣潮",
           ctx=((r"\bYinlin\b", "尹兰"),),
           note="英文残留补录（第二部片 #7265）：谷翻'尹兰'为 Yinlin 音译错形，参考行锚定。"),
    Entity("清宵", modes=("bi",), en="Qingxiao",
           category="角色/鸣潮3.7",
           ctx=((r"\bSha\b", "Sha"),),
           note="英文残留补录（第二部片）：Sha 为清宵简称（#1016/#1152），只走 ctx。"),
    Entity("玄方", modes=("bi",), en="Xuan / Schwan",
           category="地名/鸣潮3.7",
           ctx=((r"\bShenfang\b", "申方"),),
           note="英文残留补录（第二部片）：Shenfang 为 Xuanfang/Schwan 的 ASR 音近形，"
                "谷翻'申方'，走参考行锚定。"),
    Entity("瑝珑", modes=("bi",), en="Huanglong",
           category="地名/鸣潮",
           ctx=((r"\bHong Lang\b|\bHuanglong\b", "洪朗"),),
           note="英文残留补录（第二部片 #175）：Hong Lang 为 Huanglong 的 ASR 形，"
                "谷翻'洪朗'，走参考行锚定（正则同时容纳修正后 Huanglong）；英文行走 EN_LINE 组合键。"),
    # --- 第二部 3.7 片：CONTEXT_MAP 直挂（无合适实体 canonical 承载）---
    # 封印/丙区/艾因/竹子/心月狐指引：常用词或一次性 NPC，仅在参考行佐证下改。

    # --- 2026-10-05 沉淀自《Arknights: Endfield ACTUALLY Listened》谷歌翻译反应片二次校准 ---
    Entity("菈梵朵玛", modes=("bi", "endo"), en="La Fantoma / La Fantôme",
           category="地名/终末地",
           variants=("La Fantoma", "La Fantôme", "La Fant ome", "LaFantoma",
                    "拉法尔", "幻想城", "拉环朵玛"),
           note="终末地塔卫二文明环带滨海度假城市，环塔商会核心城市，'自由市'。"
                "官方中文=菈梵朵玛（endfield.wiki.gg 多语对照 Chinese=菈梵朵玛；"
                "官方知识库作'拉环朵玛自由市'，两者并存，反应片字幕取 wiki 全条目写法"
                "菈梵朵玛）。⚠ 裸键 'La Fant' 不入表（法语冠词误伤风险），只收完整形态；"
                "主播语境常说 La Fantome=夏日度假城市，与泰拉汐斯塔对应。"),
    Entity("终末地蓬蓬", modes=("endo", "endobi"), en="Peng Peng / Endfield Pengpeng",
           category="官号/终末地",
           variants=("蓬蓬干员", "Peng peng", "Peng Peng", "乒乓球", "乒乓",
                    "Ping Pong", "Pingpong"),
           note="《明日方舟：终末地》官方运营/幕后分享账号（微博/B站/知乎同名'终末地蓬蓬'），"
                "发干员采访问答（'蓬蓬采访'系列）、EP下架公告、前瞻精华等幕后内容。"
                "英文 ASR 听成 'Peng Peng'，谷翻常作'乒乓/Ping Pong'；'特别干员问答'=蓬蓬的"
                "干员采访栏目。⚠ 裸键'乒乓'危险（真实乒乓球运动语境），只收组合形态，"
                "单字场景走逐 cue 侧车。2026-10-23 收窄到 endo/endobi：bi 模式下"
                "'ping pong' 被谷翻作'乒乓球'，曾误改成'终末地蓬蓬'（鸣潮 OST reaction 片"
                "#174，EchoBoy 乒乓延迟）；该语境改由 CONTEXT_MAP 锚定'乒乓延迟'。"),
    # --- 2026-10-21 沉淀：终末地 1.6「丹青渡」祀干员叙事反应片（规则见
    #     ENDFIELD_BI_TERMS / ENDFIELD_BI_CONTEXT 同日注释）---
    Entity("祀", modes=("endobi",), en="Si", ja="スー",
           category="角色/终末地1.6",
           note="六星寒冷辅助，巨兽「岁」的第十三位代理人，缘缘庄掌柜；官方干员叙事"
                "《祀：洒扫庭除》。英文名 Si，日文名「スー」；ASR 常作 Su/Sue/Lady Sa，"
                "谷翻作苏姑娘/苏女士/圣母/萨夫人，规则见 ENDFIELD_BI_CONTEXT。⚠ 裸 S 走 ENDFIELD_BI_CONTEXT 的「S+中文」组合形（S是/S就/S 需要），不可写成裸键 S——str.replace 会把同 cue 的 Boss 咬成 Bo祀。"),
    Entity("缘缘庄", modes=("endobi",), en="Yuanyuan Manor / Enishi Manor",
           category="地点/终末地1.6",
           note="1.6「烟火生缘」乡间客栈，位于武陵·祀的画；官方宣传语「缘缘庄，可是"
                "塔卫二最好的客栈」。英文 ASR 常作 Eso/Enishi/Manor，谷翻作埃索/严府/"
                "萨庄/雅虎庄园等，规则见 ENDFIELD_BI_CONTEXT。"),
    Entity("阿咬", modes=("endobi",), en="Bitey",
           category="生物/终末地1.6",
           note="墨魉，画家祀取名；官方中文名阿咬（Arknights Terra Wiki Bitey）。"
                "本片英文 ASR 作 Bitey/shoe umbrella，谷翻作咬咬/鞋伞。"),
    Entity("巨兽代理人", modes=("endobi",), en="Feranmut Proxy",
           category="设定/终末地",
           note="EN 官方称 Si 为 Feranmut Proxy；中文官方称谓巨兽代理人（官网干员页）。"
                "ASR 常把 Proxy 读成 second person，谷翻作第二个人/第二个。"),
    # --- 2026-10-23 二校沉淀：《Si is Genuinely BUSTED》（kukkikaze，87 cue，--endobi）---
    #   名词漏校：dungeon 全被谷翻直译「地牢」；速腾/墨锯 为 ASR 误听 + 车型误译。
    #   官方依据：终末地高难玩法「危机合约」（官网 news/2659，自选指标 4 波次）、
    #   可重复挑战内容社区通称「副本」；祀核心机制「墨魂」（Ink Spirit）。
    Entity("副本", modes=("endobi",), en="Dungeon", category="玩法/终末地",
           ctx=((r"\bdungeons?\b", "地牢"),),
           note="终末地可重复挑战内容的中文通称「副本」；谷翻一律直译「地牢」。「地牢」是通用词（奇幻地牢），只走英文 dungeon 锚定。"),
    Entity("速通", modes=("endobi",), en="Speedrun", category="术语",
           ctx=((r"\bspeed\s?(?:run|un)s?\b", "速腾"),),
           note="speedrun 被谷翻按大众车型译成「速腾」；「速腾」是真实车名，只走英文锚定。"),
    Entity("墨魂", modes=("endobi",), en="Ink Spirit", category="机制/祀",
           ctx=((r"\bink\s?saw\b", "墨锯"),),
           note="祀核心机制「墨魂」（Ink Spirit）；ASR 把 ink soul 听成 ink saw，谷翻作「墨锯」。⚠ 裸键「灵魂」已于 2026-10-20 撤除，仍只走英文锚定。"),
    # --- 2026-10-24 二次校准补充（同一片源；用户要求官方中文逐句复核 + 回灌脚本）---
    #   官方依据：官网干员页（别礼 Last Rite / 诀 Arcane）、蚀刻章列表（技能提升奖章）、
    #   「战争回响 - 异想赛季」轮换（重伤之围 + 易伤区域）。
    #   只收可复用规则；pro→BOSS / low CC→低难度危机合约 / bed→剑锋 / razor structure
    #   属本片一次性 ASR 残句，按硬契约第 4 条不进表，保留逐 cue 覆盖。
    Entity("别礼", modes=("endobi",), en="Last Rite", category="角色/终末地",
           variants=("Last Rite",),
           ctx=((r"believe in (?:last\b|last\s+rite\b)", "最后"),
                (r"believe in (?:last\b|last\s+rite\b)", "这套")),
           note="Last Rite 官方中文=别礼。ASR 把 Last Rite 听成 last，谷翻按普通词译「最后/这套」；"
                "「最后」是通用词，只在 believe in last 语境锚定，绝不收裸键 last。"),
    Entity("诀", modes=("endobi",), en="Arcane", category="角色/终末地",
           ctx=((r"i think a king|a king should go first", "国王"),),
           note="Arcane 官方中文=诀。本片 ASR 把 Arcane 听成 a king，谷翻译「国王」；"
                "「国王」是通用词，只在 I think a king / A king should go first 语境锚定；"
                "既有的 arcan(e|a)->奥术 ctx 保留。"),
    Entity("技能提升奖章", modes=("endobi",), en="Skill Medal", category="蚀刻章/终末地",
           variants=("技能勋章", "技能奖章", "技能提升勋章"),
           note="官方蚀刻章名「技能提升奖章」（升满 20 个专精的技能类奖章）；"
                "机翻/口语常作技能勋章/技能奖章，均为特定错形，可进裸键。"),
    Entity("危机合约", modes=("endobi",), en="Crisis Drill / Crisis Contract",
           category="玩法/终末地",
           ctx=((r"crisis\s+drill|crisis\s+contract", "危机演习"),),
           note="终末地官方高难玩法「危机合约」；本片 ASR 作 crisis drill，谷翻译「危机演习」。"
                "「危机演习」是特定错形，但仍以英文 crisis drill/contract 锚定，避免泛化。"),
    Entity("易伤区域", modes=("endobi",), en="Vulnerability Zone",
           category="机制/重伤之围",
           ctx=((r"ink\s?saw.{0,40}\bring\b", "环内"),
                (r"ink\s?saw.{0,40}\bring\b", "圈内"),
                (r"ink\s?saw.{0,40}\bring\b", "圈里")),
           note="「重伤之围」场地机制：易伤区域使敌人受到的伤害逐渐增加。"
                "ASR「ink saw in the ring」指墨魂在易伤区域内；ring 是通用词，只在 ink saw 语境锚定。"),
    Entity("重伤之围", modes=("endobi",), en="Grievously Besieged",
           category="关卡/战争回响",
           note="「战争回响 - 异想赛季」轮换关卡；Grievously Besieged 官方中文=重伤之围。"
                "本片 6:12 段落即该关卡；纯元数据，无错形规则。"),
    Entity("聂菲斯", modes=("endobi",), en="Nefarith", category="BOSS/终末地",
           note="危境再现「危境祸影」BOSS；官方中文=聂菲斯。本片 0:00 段落。纯元数据，无错形规则。"),
    Entity("幽林之怒", modes=("endobi",), en="Gloomwald's Rage", category="BOSS/终末地",
           note="1.5「雪凇幽梦」区域 BOSS；官方中文=幽林之怒。本片 3:07 段落。纯元数据，无错形规则。"),
    # ============================================================
    # 2026-10-10《Jadealy REACTS to Every HSIN Trailers – Wuthering Waves》
    #   （鸣潮 3.7「心」全部预告片合集 reaction，中英双语，502 cues）二次校准沉淀。
    #   片源依次：剧情动画《朝月喜事》(Cinematic Short: Hsin's Trail)、3.7 EP《心月辞》
    #   (Ode to Hsin and Moon)、战斗展示、共鸣者展示 PV《梦阑珊》(A DREAM'S END)、
    #   寰宇频道特别栏目《朝月惊梦》(The Waking Moon Dreamscape)。
    #   官方依据：库洛官网 3.7 版本说明、官方抖音 PV《梦阑珊》简介台词、官博《朝月惊梦》
    #   文案、NGA《心月辞·长相望》歌词、gematsu 官方英文片名表。
    # ============================================================
    Entity("心", modes=("bi",), en="Hsin / Shin",
           category="角色/岁主·鸣潮3.7",
           variants=("心月狐骨",),
           ctx=((r"\btwo shins?\b|\bshins?\b", "小腿"),
                (r"\bChin\b", "下巴")),
           note="3.7 五星导电音感仪、梦州岁主、梦州文明引导者，官方角色名单字「心」"
                "（CV 菊花花）；「心月狐」为岁主全称/狐狸形态称谓（旧实体保留，二者勿互删）。"
                "谷翻把 Shin 错拆成「心月狐骨」（cue332/335，绝无歧义，裸键->心）；"
                "two shins 按 shin(胫骨) 译「小腿」、Chin 按 chin(下巴) 译「下巴」，"
                "均极常用词，只走参考行 shin/Chin 锚定改「心」，绝不裸键（\\bChin\\b 词边界"
                "不会咬进 Chinshi 等串）。⚠ 旧 ctx 有 Shin->心月狐（错形 申/辛/胫），"
                "与本条（错形 小腿/下巴->心）错形不同可共存；人工精修按语境在「心/心月狐」间取舍。"),
    Entity("角", modes=("bi",), en="Jue / JER / Jerame",
           category="角色/岁主·鸣潮3.7",
           variants=("杰拉姆",),
           note="梦州另一位说话岁主「角」（英 Jue/Jué，CV 黄莺）。ASR 把 Jue 咬成 JER/Jerame，"
                "谷翻音译「杰拉姆」（cue246/251，生僻裸键->角）；JER 为英文行呼语残留"
                "（默认不改英文行）。旧实体 ctx（Jue 锚定 朱->角）保留。"),
    Entity("梦州", modes=("bi",), en="Mengzhou / Mongol",
           category="地名/鸣潮3.7",
           variants=("蒙古人",),
           note="ASR 把 Mengzhou 咬成 mongol，谷翻作「蒙古人」（cue420「将梦州沐浴在银光之中」）；"
                "鸣潮 bi 片源内出现即梦州，沿 Mongo/Mango/MJO->梦州 先例裸键"
                "（真实蒙古族语境不属鸣潮片；只收「蒙古人」，单「蒙古」过短不收）。"),
    Entity("月灯", modes=("bi",), en="moon lantern",
           category="物品/节日·鸣潮3.7朝月会",
           variants=("月盒", "月亮盒子"),
           note="朝月会习俗点「月灯」、放河灯（3.7 主线「点上月灯」；韩语表 월등->月灯 已沉淀）。"
                "ASR 把 moon lantern/boats 咬成 moon box，谷翻作「月亮盒子/月盒」（cue52）；"
                "均非通用中文词，裸键->月灯安全。"),
    Entity("库洛", modes=("bi",), en="Kuro Games",
           category="公司/鸣潮",
           variants=("库拉",),
           note="库洛游戏(Kuro Games)，ASR 作 Kura，谷翻音译「库拉」（cue6，生僻裸键）；"
                "「Kuro cooked=库洛杀疯了」里的「煮熟」是普通口语词，不能裸键，"
                "走 CONTEXT_MAP 原生条（Kur[ao] cooked 锚定 煮熟->杀疯了）。"),
    Entity("鸣潮", modes=("bi",), en="Wuthering Waves",
           category="作品/游戏",
           variants=("凋零迷宫", "凋零浪潮", "凋零之波", "凋零波"),
           note="Wuthering Waves 谷翻「凋零」系（本片 cue136/194 作凋零波/凋零迷宫；"
                "旧表已收「枯萎」系长键与 ctx 凋零浪潮，本条补 bi 裸键）。长键先行、"
                "「凋零迷宫/凋零浪潮」不与「凋零波」嵌套；wither 作动词的「凋零」本义不收。"),
    Entity("共鸣者", modes=("bi",), en="Resonator",
           category="术语/鸣潮",
           variants=("共鸣器",),
           note="Resonator 官方译名共鸣者；机译常作「共鸣器」（谐振元件本义，cue194），"
                "鸣潮 bi 片源内裸键安全。旧 ctx 已收谐振器/谐振腔->共鸣者，韩语表 공명자->共鸣器 已沉淀。"),
    Entity("寰宇频道", modes=("bi",), en="Insider Channel",
           category="节目/官方栏目·鸣潮",
           variants=("隐现频道",),
           ctx=((r"\b[Ii]nsider [Cc]hannel\b", "内部频道"),),
           note="官方节目系列名「寰宇频道」（英 Insider Channel），3.7 出特别栏目《朝月惊梦》。"
                "谷翻作「隐现频道」（cue345，生僻裸键）与「内部频道」（cue382，常用组合，"
                "走参考行 Insider Channel 锚定）；旧译「内参频道」同属此词，遇片再补。"),
    Entity("朝月惊梦", modes=("bi",), en="The Waking Moon Dreamscape",
           category="节目/皮影戏·鸣潮3.7",
           variants=("梦月醒时的梦境", "苏醒的月亮梦境", "醒月梦境"),
           note="寰宇频道 3.7 特别栏目（皮影戏）《朝月惊梦》，英 The Waking Moon Dreamscape；"
                "官博文案「传说梦州，昔有长夜漫漫，人皆沉沉睡去。唤也不醒，梦也无边」。"
                "谷翻长串「梦月醒时的梦境/苏醒的月亮梦境」（cue346/384）生僻，裸键安全；"
                "长键先于裸键「醒月->朝月」，不产生叠字。"),
    Entity("朝月会", modes=("bi",), en="Waking Moon Festival / Moon-Chasing Festival",
           category="节日/鸣潮3.7",
           variants=("苏醒的月亮节日",),
           note="补漏：谷翻「苏醒的月亮节日」（cue29-30，长键先于醒月/清醒月系短键）。"
                "旧实体已收唤醒月亮节/醒月盛宴/中秋节(ctx) 等形。"),
    Entity("心月辞", modes=("bi",), en="Ode to Hsin and Moon (EP3.7)",
           category="音乐/EP·鸣潮3.7",
           variants=("心月狐 O to 心月狐", "心月狐O to心月狐"),
           note="3.7 心 EP 官方专辑名《心月辞》（英 Ode to Hsin and Moon；含《心月辞·长相望/"
                "何所往》，英文版 Endless Yearning / Whither Away?）。ASR 把 Hsin: Ode to Hsin "
                "咬成 Shin O to Shin，谷翻留「心月狐 O to 心月狐」（cue136，生僻长串裸键）。"
                "⚠ 片名尾部「和月亮」跨 cue 碎在 cue137，术语表单 cue 收不到，留人工 pair 精修。"),
    Entity("梦阑珊", modes=("bi",), en="A DREAM'S END (Resonator Showcase: Hsin)",
           category="作品/PV·鸣潮3.7",
           note="共鸣者展示 PV 官方名《梦阑珊》（英 A DREAM'S END），插曲《月声尽，心灯明》；"
                "官方台词「心月狐，你已伤及根本，若再不寻得共鸣者。梦州与今门关大局在前。"
                "此事自有定数……不必再沉溺此梦了」。本片中文行未现 PV 名机翻错形，仅登记对象知识。"),
    Entity("朝月喜事", modes=("bi",), en="Hsin's Trail (Cinematic Short)",
           category="作品/剧情动画·鸣潮3.7",
           ctx=((r"short trail|Hsin's Trail|cinematic short", "短途"),
                (r"short trail|Hsin's Trail|cinematic short", "电影短途"),
                (r"short trail|Hsin's Trail|cinematic short", "短片预告")),
           note="3.7 剧情动画《朝月喜事》（英 Cinematic Short: Hsin's Trail，六分钟；女孩玉玥"
                "替奶奶玉珏圆梦，心化黑发少女陪逛朝月会、雨中点灯，心愿「同赏人间欢喜，"
                "共守灯火长明」）。ASR 把 Hsin's Trail 咬成 short trail，谷翻作「电影短途/"
                "短片预告」（cue12-13，常用词，走参考行 short trail/Hsin's Trail/cinematic "
                "short 锚定）；cue12 尾「电影」与 cue13「短途」跨行，术语层只收得住 cue13，"
                "完整片名靠人工 pair。"),
    Entity("今门关", modes=("bi",), en="Jinmen Pass",
           category="地名/鸣潮3.7",
           variants=("Geneman", "金门关"),
           note="PV《梦阑珊》官方台词「梦州与今门关大局在前」之关隘「今门关」（梦州-今州方向）。"
                "ASR 作 Geneman（cue256，夹在中文行的英文整词，生僻裸键->今门关；英文参考行"
                "默认不动）；「金门关」为同音误写。「的过去就摆在我面前->大局在前」属整句"
                "台词级改写，不入术语表，走人工 pair。"),
    # ============================================================
    # 2026-10-10《My Thoughts on Wuwa's 3.7 Story | I Have Cried Again》
    #   （LightfulWings 鸣潮 3.7 主线观后感，中英双语，273 cues）二次校准沉淀。
    #   官方依据：国际服 3.7 patch notes（Hsin=心 / Sentinel Hsin / Mengzhou=梦州 /
    #   Xuanfang=玄方 / Qingxiao=清宵 / Suoming=锁暝 / Tacet Discord=残象 /
    #   Simulacrum Nexus=梦枢天罗）、配音表 Muyu=木禺（Xuanfang Ministry of
    #   Development 工匠，3.5 登场）、3.7 开场官方中文台词。
    #   剧情设定：心=岁主心月狐情感面所化分形（国际服 Hsin）；溯心=文明之匣生成的
    #   标准岁主模型、绝对理性面（天罗狐影/Nexus Fox Shadow 异变体）。
    # ============================================================
    Entity("溯心", modes=("bi",), en="Suxin",
           category="角色/岁主·鸣潮3.7",
           variants=("Shu Xin", "Shu Shin", "Su Xin", "Soo Hee",
                     "舒欣", "苏鑫",
                     # --- 2026-10-12 本片声纹筛选版（108 cue）：ASR 三叠碎形 ---
                     "S Ush In", "Sub Shin"),
           ctx=((r"\bShu\s+Xin\b|\bShu\s+Shin\b|\bSu\s+Xin\b|\bSoo\s+Hee\b"
                 r"|\bSuxin\b|\bSusheen\b|\bSushin\b|\bSushun\b", "舒心"),
                (r"\bShu\s+Xin\b|\bShu\s+Shin\b|\bSu\s+Xin\b|\bSoo\s+Hee\b"
                 r"|\bSuxin\b|\bSusheen\b|\bSushin\b|\bSushun\b", "苏...嘻"),
                # 2026-10-12 本片声纹筛选版（#31/35/38/65）：ASR 把 Suxin 咬成
                #   S ush in / Su Hinds / Sub Shin / soup shin；谷翻按字面音译
                #   '徐信'/'苏·欣兹'/'苏真'。三者均为姓名式组合，绝不裸键，
                #   只走参考行锚定（锚点各自独立，互不串味）。
                (r"\bS\s+ush\s+[Ii]n\b", "徐信"),
                (r"\bSub\s*Shin\b", "徐信"),
                (r"\bSu\s*Hinds\b", "苏·欣兹"),
                (r"\bsoup\s*shin\b", "苏真")),
           note="第三部 3.7 片：ASR 把 Suxin 咬成带空格两词串 Shu Xin/Shu Shin/Su Xin/Soo Hee"
                "（cue94/98/110-111/116/187-188）。中文行英文残留四串生僻，裸键->溯心；"
                "谷翻错形：'舒心'(常用词，只走 ctx)、'舒欣/苏鑫'(生僻裸键，沿苏辛/苏珊先例)、"
                "'苏...嘻'(Soo Hee 碎形，走 ctx)。单字碎形'舒/苏/嘻/鑫'(Shu/Su/Hee/Xin 跨 cue)"
                "无法单 cue 收束，留人工 pair 跨行重组。"),
    Entity("清宵", modes=("bi",), en="Qingxiao",
           category="角色/鸣潮3.6",
           variants=("Xingqiao",),
           ctx=((r"\bXingqiao\b|\bQingxiao\b|\bChing\s*Xiao\b", "星桥"),),
           note="第三部 3.7 片（cue201/213）：ASR 把 Qingxiao 声母 q/x 互调咬成 Xingqiao，"
                "谷翻作'星桥'（真实词汇/地名，只走参考行锚定，绝不裸键）；英文残留 Xingqiao "
                "生僻裸键->清宵。语境：清宵 3.6 向漂泊者坦白艰难抉择，主播以心与清宵的相似"
                "心境并论。"),
    Entity("玄方", modes=("bi",), en="Xuanfang / Xuan Feng",
           category="地名/鸣潮3.7",
           variants=("Xuan Feng", "Xuanfeng"),
           ctx=((r"\bXuan\s*Feng\b|\bXuanfang\b|\bLand of Xuanfang\b", "玄风"),),
           note="第三部 3.7 片（cue8/18/97）：国际服官方 Xuanfang（Mengzhou: Land of "
                "Xuanfang 玄方地界；Xuanfang Hold 玄方城）。ASR 拆词咬成 Xuan Feng，"
                "谷翻整串留英文（生僻裸键->玄方）或音译'玄风'（道教真实词，走参考行锚定）。"),
    Entity("梦州", modes=("bi",), en="Mengzhou",
           category="地名/鸣潮3.7",
           ctx=((r"\bXuan\s*Feng\b|\bXuanfang\b|\bMengzhou\b|\bLand of Xuanfang\b|\bSolaris",
                 "Ming Chao"),
                (r"\bXuan\s*Feng\b|\bXuanfang\b|\bMengzhou\b|\bLand of Xuanfang\b|\bSolaris",
                 "Ming Chao's")),
           note="第三部 3.7 片（cue18 'better for Xuan Feng, Ming Chao, and even Solaris'）："
                "ASR 把 Mengzhou 咬成 Ming Chao，谷翻留英文。⚠ 高危：Ming Chao 拼音同"
                "『鸣潮』，**绝不裸键**；只在参考行同时命中 Xuanfang/Mengzhou/Solaris 等"
                "梦州·玄方语境锚点时经 ctx 归梦州。鸣潮语境（WuWa/game/Kuro 等）不含玄方"
                "锚点，不命中，保持鸣潮。"),
    Entity("木禺", modes=("bi",), en="Muyu",
           category="角色/鸣潮3.5",
           variants=("Mu Yu",),
           note="第三部 3.7 片（cue24 'Mu Yu's chaos'）：国际服官方名 Muyu（玄方工部"
                "工匠，3.5 登场，3.7 引发玄方城动乱；官方开场台词『便不会任由木禺引发动乱』）。"
                "ASR 拆词作 Mu Yu，谷翻留英文，生僻串裸键->木禺（扁平表 Muyu/暮羽 已有）。"),
    Entity("残象", modes=("bi",), en="Tacet Discord",
           category="术语/鸣潮",
           variants=("Discord of Tacitus", "Tacitus Discord"),
           ctx=((r"\bDiscord of Tacitus\b|\bTacitus\s+Discord\b|\bTacet\s+Discords?\b", "塔西佗的不和"),
                (r"\bDiscord of Tacitus\b|\bTacitus\s+Discord\b|\bTacet\s+Discords?\b", "塔西佗的 Discord"),
                (r"\bDiscord of Tacitus\b|\bTacitus\s+Discord\b|\bTacet\s+Discords?\b", "塔西佗")),
           note="第三部 3.7 片（cue9-10）：ASR 把 Tacet Discord 词序颠倒且 Tacet->Tacitus"
                "（罗马史学家塔西佗），咬成 Discord of Tacitus，谷翻整串留英文（长串生僻"
                "裸键->残象）或译'塔西佗的不和'（走参考行锚定；长 wrong 先于单'塔西佗'）。"
                "⚠ ctx 锚点必须带 Discord（Discord of Tacitus/Tacitus Discord）：裸 Tacitus "
                "是真实史学家名（'Tacitus was a Roman historian' 实测会误伤），绝不锚定/裸键。"
                "语境：官方台词『残象潮席卷的玄方』。"),
    Entity("库洛", modes=("bi",), en="Kuro Games",
           category="公司/鸣潮",
           variants=("库罗",),
           note="第三部 3.7 片（cue60 'thanks to Kuro for writing it'）：谷翻作'库罗'，"
                "生僻错形裸键->库洛（旧实体 variants 库拉 保留）。"),
    Entity("岁主", modes=("bi",), en="Sentinel",
           category="称号/鸣潮",
           ctx=((r"\bGuardian\b", "监护人"),
                (r"\bGuardian\b", "卫报")),
           note="梦州岁主（国际服 Sentinel；3.7 心为 Mengzhou's first playable Sentinel、"
                "心月狐为前任岁主）。第三部片主播 LightfulWings 口播中常以 Guardian/Watcher "
                "代指 Sentinel。谷翻把 Guardian 误作法律词'监护人'（cue51/145/156）、报纸名"
                "'卫报'（cue187/190/218），均常用词，只走参考行 Guardian 锚定归岁主。"
                "⚠ '守护者'是 Guardian 的正确中文且 cue35 'Shin's Guardian' 取『心的守护者』"
                "关系义（指心月狐），不入规则、留人工 pair 在守护者/岁主间取舍；Watcher 语境"
                "的'守望者'见 EXCLUDE_CONTEXT 负向排除（不得归守岸人 Shorekeeper），"
                "'监视者->守望者'挂 CONTEXT_MAP。"),
    Entity("心", modes=("bi",), en="Hsin / Shin",
           category="角色/岁主·鸣潮3.7",
           note="第三部片补充：reaction 评论段单独 Shin/Hsin 绝大多数指可玩角色『心』"
                "（国际服官方 Hsin，3.7 五星），本体心月狐多作 the Moon Fox/original "
                "Sentinel/Sheen；旧 ctx Shin 锚定（错形 申/辛/胫）->心月狐 为剧情片沉淀，"
                "评论片会系统性偏到心月狐，本条不改旧规则，人工 pair 按语境在心/心月狐间"
                "取舍（本片 20 余处 Shin 评论均归『心』，开场剧情 real Guardian 归岁主）。"),
    # --- 2026-10-12 本片声纹筛选版（108 cue）三次校准补录 ---
    #   官方依据（3.7 前瞻特别节目 / 官方角色档案）：
    #     心月狐（心 / Hsin）五星·导电·音感仪，梦州岁主，首位可玩岁主，异能力『万相分形』
    #       ——化一为众、衍形化象，诸分形各自成形却仍与本源相系、互通所感、亦可复归于一；
    #     锁暝（Suoming）五星·导电·迅刀，异能力『十重契』；
    #     版本主题 Prism's Illusion, Heart's Illumination = 镜锁妄世，心照红尘；
    #     新区域 Simulacrum Nexus of Mengzhou = 梦枢天罗（已收 Entity）。
    Entity("分形", modes=("bi",), en="Fractal / copy",
           category="设定/鸣潮3.7",
           ctx=((r"\blesser copy\b|\bcopy born of\b|\bfragment of\b", "复制品"),
                (r"\blesser copy\b|\bcopy born of\b|\bfragment of\b", "复制体"),
                (r"\blesser copy\b|\bcopy born of\b|\bfragment of\b", "克隆体")),
           note="3.7 官方设定词：心月狐异能力『万相分形』，岁主情感面所生者官方称『分形』"
                "（本片 #61 'lesser copy'、#64 'copy born of the sentinel's emotional "
                "aspect'、#60 'last fragment of Shin'）。谷翻作'复制品/复制体/克隆体'，"
                "三者皆常用词，绝不裸键，只走参考行 lesser copy / copy born of / "
                "fragment of 锚定；'分形'本身生僻，可在中文行直接出现。"),
    # ============================================================
    # 2026-10-10《鸣潮》3.7 主线 reaction 片
    #   （ADHD REACTS to Wuthering Waves Version 3.7 Hsin MAIN QUEST，kettletoro）
    #   二次校准补录：英文 ASR + 谷翻残留错形。戒律：生僻音译/英文残留可裸键；
    #   常用中文词（罪/辛/信/真/成/千/游水/摇摆/天神/天界/枢纽/歧管/领地/吴…）
    #   一律走参考行 ctx 锚定，绝不裸键。ctx 按列表顺序应用，长错形须先于短错形。
    # ============================================================
    Entity("心月狐", modes=("bi",), en="Shin",
           category="角色/岁主·鸣潮3.7",
           ctx=((r"\bSin\b", "辛"), (r"\bSin\b", "罪恶"), (r"\bSin\b", "罪"),
                # 2026-10-22 反例：Tenha EP reaction 片 #1949 歌词 "shing."（拟声，小写）
                # 被本条改成“成→心月狐”；角色 ASR 必为大写 Shing，故改大小写敏感。
                (r"(?-i:\bShing\b)", "成"),
                (r"\bSeen\b", "Seen"), (r"\bShuin\b", "修院")),
           note="本片补录：ASR 把 Shin 听成 Sin/Shing/Seen/Shuin，谷翻一律按常用词直译"
                "（Sin->辛/罪/罪恶、Shing->成、Shuin->修院、Seen 整词留英文）。"
                "全为常用词，只走参考行锚定；'罪恶'须先于'罪'。"
                "⚠ 错形用最窄形：'Shin->信/真' 裸形会误伤（实测裸'真'把 cue415'丑陋的真相'"
                "咬成'丑陋的心月狐相'），改走扁平 CONTEXT_MAP 三元组 '真终于->心月狐终于'、"
                "'叫信->叫心月狐'（保留原句虚词）。"
                "⚠ 不收 'Sen->千'：本片 cue809 'but Sen still has no resonator' 的 Sen 指代"
                "存疑（心月狐本有共鸣者璇情），无官方依据不臆断，留人工。"
                "⚠ 本片为剧情 reaction 片，Shin/Sheen 均指岁主本体心月狐；"
                "评论片中单独 Shin 多指可玩角色「心」，见 Entity('心') 的 note。"),
    Entity("锁暝", modes=("bi",), en="Suoming",
           category="角色/鸣潮3.7",
           variants=("斯沃明",),
           ctx=((r"\bSwaming\b", "游水"), (r"\bSwinging\b", "摇摆")),
           note="本片补录：Swaming 的谷翻音译'斯沃明'（生僻裸键）；ASR 形 Swaming->谷翻"
                "'游水'、Swinging->'摇摆'（均常用词，只走参考行锚定）。"),
    Entity("玄方城", modes=("bi",), en="Schwanfong Hold",
           category="地名/鸣潮3.7",
           variants=("Shwenfong", "Shenfong", "神丰堡", "山坊", "山芳"),
           ctx=((r"\bSchwang\w*\b|\bShanfang\b", "王风"),
                (r"\b[Hh]old's\b", "等待结束"),
                (r"\b[Hh]old\b", "领地"), (r"\b[Hh]old\b", "固定点")),
           note="本片补录：ASR/谷翻把玄方城写成英文残留 Shwenfong/Shenfong 或音译"
                "'神丰堡/山坊/山芳'（均生僻，裸键）；'王风'（Schwangfong 误读）、"
                "'领地/固定点'（剧情里的 the Hold=玄方城）、'等待结束'（Hold's completion）"
                "均为常用词，只走参考行锚定。"),
    Entity("天人", modes=("bi",), en="Celestials",
           category="术语/鸣潮",
           ctx=((r"\b[Cc]elestials\b", "天界生物"), (r"\b[Cc]elestials\b", "天界幻影"),
                 (r"\b[Cc]elestials\b", "天神们"), (r"\b[Cc]elestials\b", "天神"),
                 (r"\b[Cc]elestials\b", "天界"),
                 (r"\b[Cc]elestial\b", "天神")),
           note="本片补录：谷翻把 celestials 按字面译成'天神/天神们/天界/天界生物/天界幻影'"
                 "（均常用词），只走参考行锚定归官方中文'天人'；长错形须先于短'天界'。"
                 "2026-10-10 二次校准增补：①'天神们'整词（防产'天人们'）；②单数 "
                 "\bcelestial\b 只锚错形'天神'（'天体'义不受影响，2026-10-05 的单数禁区"
                 "仅针对错形'天体'）；③'celestial phantom'（单数）->天人幻影改挂 CONTEXT_MAP 三元组。"),
    Entity("溯心", modes=("bi",), en="Sushin",
           category="角色/鸣潮3.7",
           variants=("苏希安",),
           note="本片补录：ASR 把 Sushin 咬成 Sushian，谷翻音译'苏希安'（生僻裸键->溯心）。"),
    Entity("梦枢天罗", modes=("bi",), en="Simulacrum Nexus",
           category="地点/新地区",
           variants=("西米拉克林",),
           ctx=((r"\bnexus\b", "梦枢天罗 枢纽"), (r"\bnexus\b", "枢纽")),
           note="本片补录：ASR 把 Simulacrum 咬成 Simiracrim，谷翻音译'西米拉克林'"
                "（生僻裸键）；'nexus' 被直译'枢纽'（常用词，只走参考行锚定）。"
                "⚠ 'Simiracrim' 已在 BILINGUAL_TERMS 裸键->梦枢天罗，故先落'梦枢天罗 枢纽'"
                "再收敛，组合错形须先于单'枢纽'，否则产'梦枢天罗 梦枢天罗'。"),
    Entity("万相神宫", modes=("bi",), en="(Manifold) Sanctum",
           category="地点/建筑·鸣潮3.7",
           ctx=((r"\bmanifold\b", "歧管"),),
           note="本片补录：'the manifold sanctum'（=万相神宫）被谷翻按机械义译成'歧管'"
                "（常用词），只走参考行 manifold 锚定。"),
    Entity("朝月会", modes=("bi",), en="Waking Moon Festival",
           category="活动/鸣潮3.7",
           ctx=((r"\bMoon Festival\b", "月亮节"),),
           note="本片补录：简称 'the Moon Festival' 被谷翻直译'月亮节'（常用词），"
                "只走参考行锚定归官方中文'朝月会'。"),
    Entity("鸣潮", modes=("bi",), en="Wuthering Waves",
           category="作品/鸣潮",
           variants=("枯萎战争",),
           ctx=((r"\bWua\b", "吴"),),
           note="本片补录：主播口播把 Wuthering Waves 咬成 'Wua'（谷翻当姓氏译'吴'）与"
                "'War of Withering Waves'（谷翻'枯萎战争'）；'吴'是常用姓氏，只走参考行锚定；"
                "'枯萎战争'为生僻组合串，裸键。"),
    Entity("梦州", modes=("bi",), en="Mengzhou",
           category="地名/鸣潮",
           ctx=((r"\b(Mongjo|Mojo|Mongo|Mong Joe)\b", "蒙乔"),),
           note="本片补录：谷翻把 Mongjo 音译'蒙乔'（学习库同名裸键已因跨片源风险被否决，"
                "改走参考行锚定；本片 cue534/690/716/803）。"),
    Entity("今州", modes=("bi",), en="Jinzhou",
           category="地名/鸣潮",
           ctx=((r"\b(Gingjo|Jingo|Ginjo)\b", "银杏"),),
           note="本片补录：谷翻把 Gingjo 误译'银杏'（学习库同名裸键已因跨片源风险被否决，"
                "改走参考行锚定；本片 cue857 'Gingjo patroller'）。"),
    Entity("御者", modes=("bi",), en="Arbiter",
           category="称号/鸣潮",
           ctx=((r"\barbiter\b", "裁判"),),
           note="本片补录：谷翻把 arbiter 按体育/法律义译成'裁判'（常用词），"
                "只走参考行 arbiter 锚定归'御者'（本片 cue537）。"),
    # --- 2026-10-12 WuWa 3.3 Story Reaction（I must save Aemeath!，10653 cue）Entity 沉淀 ---
    #     配套扁平键/锚定见 BILINGUAL_TERMS 与 CONTEXT_MAP 同日追加块；赫龙格（罗伊神话
    #     被巴德尔封印于黯原的灭世邪祇，3.3 公告官方名词）本片未以个体名出现（主播用类别名
    #     Threnodian），故不建 Entity，仅在此留档：官方英文拼写待考。
    Entity("隧门", modes=("bi",), en="Strider Gate",
           category="地点/拉海洛",
           variants=("斯特赖德门", "stridegate", "Stridegate"),
           ctx=((r"strider", "游侠门"), (r"strider", "游侠之门"),
                (r"strider", "游侠河"), (r"strider", "游侠气体"),
                (r"strider", "斯特赖德")),
           note="拉海洛通往地底黯原/隧锚的门户，3.3 隧者计划的穿越对象（官方公告）。"
                "谷翻把 Strider Gate 拆成'游侠门/游侠之门'，ASR 把 gate 咬成河/气体"
                "（'游侠河/游侠气体'）；'游侠'是通用词按戒律只走 strider 参考行锚定，"
                "'斯特赖德门'纯音译组合裸键、裸'斯特赖德'走锚定防人名误伤。"
                "彩蛋：#4283 '德州斯特赖德观测站'是主播玩'德州仪器'梗，'德州'保留。"),
    Entity("迪姆平原", modes=("bi",), en="Dimmr Plains",
           category="地点/拉海洛",
           variants=(),
           note="⚠ 反例留档（不生效）：wuthering.gg 第三方地图 zh-Hans 页名'迪姆平原'"
                "系机翻，实为 3.3 官方新地区「黯原」（Dimmr Plains，#573 既有沉淀）；"
                "variants 刻意留空防止错误映射注册，本条仅记录第三方页名不可轻信的教训。"),
    Entity("特别对策组", modes=("bi",),
           category="组织/鸣潮",
           variants=("特种反应部队",),
           note="绯雪现任所属（3.3 公告：以特别对策组唯一成员的身份在拉海洛停留）。"
                "ASR 'Special Response Force' 谷翻'特种反应部队'归此。"),
    Entity("罗伊冰原", modes=("bi",), en="Roya Frostlands",
           category="地点/鸣潮",
           variants=("罗伊霜原",),
           ctx=((r"Roya Frost", "《Roya Frost》"),),
           note="3.0 大地区，拉海洛位于其地下（官方英文公告：Lahai-Roi ... situated "
                "beneath the Roya Frostlands）。本片 #5417 谷翻保留英文《Roya Frost》、"
                "#5418 断行 'Lands'，ctx 整段归一；裸 'Roya' 英文残留只锚定 "
                "designs/partners/are 窄语境（见 CONTEXT_MAP 同日块），防误伤作品名。"),
    # --- 2026-10-14 I'm Disappointed But Not Suprised, This Is Gacha（蓝色星原英文版延期杂谈，bi，523 cue）沉淀 ---
    Entity("蓝色星原", modes=("bi",), en="Azur Promilia", category="作品/游戏",
           variants=("蔚蓝突击者", "Diya Starborn"),
           ctx=((r"\bAzure Striker\b", "Azure Striker"),),
           note="蛮啾 Manjuu《蓝色星原：旅谣》官方英文名 Azur Promilia（官网 azurpromilia.manjuu.com）。"
                "本片 ASR 把游戏名误听成 Azure Striker（#2 谷翻'蔚蓝突击者'、#27/#51 中文行英文残留）；"
                "#50《Diya Starborn》实为官方帖开头称呼 'Dear Starborn' 被 ASR 连读进游戏名位"
                "（官方帖原文：'Update on the English Release. Dear Starborn, since Azur Promilia was "
                "first revealed...'）。⚠ 勿与本体碧蓝航线混淆：本片 #152/#172/#192/#479 的 Azur Lane "
                "是真指碧蓝航线（角色既视感/玩家群体/开发者语境），#60/#64/#108 的 Azur Lane 才是"
                "Azur Promilia 误听，参考行无法区分，只走本片侧车，绝不入规则。"),
    Entity("星临者", modes=("bi",), en="Starborn", category="游戏称谓",
           variants=(),
           ctx=((r"\bStarborn\b", "星裔"),),
           note="蓝色星原玩家官方称谓（官方微博图绘栏目'星临者'；英文 Starborn）。"
                "'星裔'为常见奇幻词，不裸键，只走参考行 Starborn 锚定。"),
    Entity("蛮啾", modes=("bi",), en="Manjuu", category="厂商",
           variants=("Manjuu",),
           ctx=((r"\bManjuu\b", "万寿"),),
           note="上海蛮啾（Manjuu Games），碧蓝航线/蓝色星原开发商。中文行英文残留 'Manjuu' 裸键归此；"
                "谷翻误作'万寿'（#191/#478）——万寿为常用词（万寿菊），绝不裸键，只走参考行 Manjuu 锚定。"),
    Entity("明日方舟：终末地", modes=("bi",), en="Arknights: Endfield", category="作品/游戏",
           variants=("Arc骑士Enfield", "Arc Knights Enfield"),
           note="bi 双语片源里 Arknights: Endfield 的 ASR/谷翻错形（#277 评论区列举同期上线游戏）。"
                "⚠ 长键必须先于 CONTEXT_MAP 的 (Knights,骑士,明日方舟)（约 L1466）：首轮实测"
                "骑士 被短 ctx 先咬成 'Arc明日方舟Enfield' 畸形；裸键走 BILINGUAL 长键降序先于 ctx 层。"),
    Entity("千里眼", modes=("bi",), en="Clairvoyance", category="抽卡术语",
           variants=(),
           ctx=((r"[Cc]lairvoyance", "通灵"), (r"[Cc]lairvoyance", "预知")),
           note="抽卡社区术语：靠 CN 服进度预知 EN 服内容。谷翻在本片随机输出 通灵/预知/千里眼 三形"
                "（#94/#230/#326/#498），统一'千里眼'。通灵/预知为常用词，只走参考行锚定。"),
    Entity("卡池", modes=("bi",), en="Banner", category="抽卡术语",
           variants=(),
           ctx=((r"\b[Bb]anners?\b", "旗帜"), (r"\b[Bb]anners?\b", "横幅")),
           note="banner=卡池（沿 AK_CONTEXT 先例入 bi）。'横幅'同样参考行 banner 佐证才改"
                "（#336 'giga banner'谷翻'超级横幅'→'超级卡池'，保留'超级'，勿整词'超级横幅'入键丢修饰）；"
                "无 banner 佐证的'横幅'不动。"),
    Entity("meta", modes=("bi",), en="Meta", category="抽卡术语",
           variants=(),
           ctx=((r"\bmeta\b", "元能力者"), (r"\bmeta\b", "元能力"), (r"\bmeta\b", "元玩家")),
           note="meta（版本强度玩法）保留英文，谷翻'元能力/元玩家'为错形（#397/#496）。"
                "⚠ 列表顺序：元能力者 必须先于 元能力（子串），否则出 'meta者' 残留；"
                "meta slave 跨 cue 断行（#397 末 '如果你是meta' + #398 首 '奴隶'），替换后自然拼接。"),
    Entity("字幕", modes=("bi",), en="Subs", category="抽卡术语",
           variants=(),
           ctx=((r"\bsub(s)?\b", "潜艇"),),
           note="subs=字幕（'I only do subs'看动漫只看字幕语境，#371）。潜艇为常用词，只走参考行锚定。"),
    Entity("鸣潮", modes=("bi",), en="Wuthering Waves", category="作品/游戏",
           variants=(),
           ctx=((r"\bwithin waves\b", "波浪"),),
           note="本片 #429 'you see within waves, 40% of its revenue comes from outside CN'——"
                "Wuthering Waves 的 ASR 断词形（Wuthering→within），以鸣潮收入分布（CN 外约 40%）语境佐证；"
                "裸'波浪'为常用词，只走 within waves 整短语锚定。"),
    # === 2026-10-14 皇牌空战8：希孚之翼（ACE COMBAT 8: WINGS OF THEVE）
    #     「暗影中队」主题曲点评（MarcoMeatball，771 cue，英文 ASR+谷翻中英双语）沉淀 ===
    #   官方依据：游民星空《部分登场角色介绍》（约翰·寇普＝Joker 小队队长）；B 站中文剧情
    #   （Lux Lunae 正式名＝索托亚空军第 1 特种作战联队第 11 战术中队，绰号「暗影」；下辖四人
    #   飞行小队编号为 11 的倍数，如第 22/55/77 小队）；官方曲目表（Shadows / Frostwave /
    #   Retaking of Theve II / Gaffed Card / Lurking in the Shadows / Nightmare /
    #   Hortus Regis Alti / Everflow / Wings of Theve）。
    #   ⚠ 常用词错形（撒旦 / 科普 / 噩梦 / 潜伏在阴影里）一律走 ctx 参考行锚定，绝不进裸键。
    #   ⚠ 本片 3 处专名经**音频复核**（scripts/dev/asr_probe.py）定案：Satan→Sotoan（索托亚人）、
    #     Painted Blue→Paint it blue、Peipa→pipa（琵琶）、XD40→XT forty（XT-40）。
    Entity("暗影中队", modes=("bi",), en="Shadow Squadron", category="势力/飞行队",
           variants=("影子中队", "阴影中队", "Shadow中队"),
           note="AC8 敌方飞行队绰号（官方设定：索托亚空军第 1 特种作战联队第 11 战术中队，"
                "真名 Lux Lunae）。⚠ 该队下辖『四人飞行小队』一律译作小队（第22/55/77 小队），"
                "勿与中队混用。"),
    Entity("Lux Lunae", modes=("bi",), en="Lux Lunae", category="势力/飞行队",
           variants=("卢克的伦", "卢克·伦", "卢克的露娜", "卢克是露娜", "陆·赫斯是露娜",
                     "Luke's Lun", "Luke Lun", "Luke's Luna", "Luke的Luna", "Luke 的 Luna"),
           note="暗影中队真名，拉丁语『月之光』。英文 ASR 常听成 Luke's Lun / Luke Luna；"
                "官方罗马字为 Lux Lunae，保留原文不音译。"),
    Entity("Shadow 22", modes=("bi",), en="Shadow 22", category="呼号",
           variants=("影子22", "影子 22", "Shadow22", "暗影22"),
           note="敌方击坠王呼号（暗影中队第 22 小队队长）。中文媒体亦作 Shadow 22，保留英文。"),
    Entity("Moon 11", modes=("bi",), en="Moon 11", category="呼号",
           variants=("月球11", "月球 11", "月亮11", "月亮 11"),
           note="暗影中队第 11 小队队长（角色 卡蜜儿·裘伊）。中文媒体亦作 Moon 11，保留英文。"),
    Entity("索托亚", modes=("bi",), en="Sotoya", category="势力/国家",
           variants=(),
           ctx=((r"\bSatoan|\bSotoan|\bSatan(?!\s+of\s+(?:gotcha|gacha)\s+companies)", "撒旦"),),
           note="AC8 敌国。主播口播 Satoan/Sotoan（索托亚人），英文 ASR 误作 Satan；"
                "『撒旦』是常用词，只走参考行 Satan/Sotoan/Satoan 锚定（音频复核 2026-10-14 定案）。"),
    Entity("寇普", modes=("bi",), en="Jan Cope", category="角色",
           variants=(),
           ctx=((r"\bCope\b", "科普"),),
           note="AC8 主角方 Joker 小队队长约翰·寇普（游民星空角色页官方中文）。"
                "『科普』是常用词（科学普及），只走参考行 Cope 锚定。"),
    Entity("Frostwave", modes=("bi",), en="Frostwave", category="作品/曲目",
           variants=("霜波",),
           note="AC8 曲目 09。中文媒体保留英文曲名，故『霜波』回改为原文。"),
    Entity("Gaffed Card", modes=("bi",), en="Gaffed Card", category="作品/曲目",
           variants=("加夫牌", "Gaff Card", "Gaft Card", "Gafted Card"),
           note="AC8 曲目 26。官方曲名 Gaffed Card。"),
    Entity("Retaking of Theve II", modes=("bi",), en="Retaking of Theve II", category="作品/曲目",
           variants=("盗贼2", "盗贼 2", "夺回盗贼2"),
           note="AC8 曲目 19。副标题 Theve 官方中文译『希孚』，曲名按官方曲目表保留英文。"),
    Entity("Wings of Theve", modes=("bi",), en="Wings of Theve", category="作品/曲目",
           variants=("盗贼之翼",),
           note="AC8 主开场曲/主题动机；亦为游戏官方中文副标题『希孚之翼』（主角呼号）。"
                "曲名沿用官方曲目表英文写法。"),
    Entity("Hortus Regis Alti", modes=("bi",), en="Hortus Regis Alti", category="作品/曲目",
           variants=("Hortus Reis Ali", "王者园"),
           note="AC8 曲目（拉丁语『至高王的庭园』）。英文 ASR 误作 Hortus Reis Ali，谷翻作『王者园』。"),
    Entity("Lurking in the Shadows", modes=("bi",), en="Lurking in the Shadows", category="作品/曲目",
           variants=(),
           ctx=((r"\bLurking in the Shadows\b", "潜伏在阴影里"),
                (r"\bLurking in the Shadows\b", "潜伏在阴影中")),
           note="AC8 曲目 46。反向核查（2026-10-14）发现谷翻译成字面义『潜伏在阴影中/里』而非曲名；"
                "裸短语有字面义，只走参考行整短语锚定。"),
    Entity("Nightmare", modes=("bi",), en="Nightmare", category="作品/曲目",
           variants=(),
           ctx=((r"\bNightmare\b", "噩梦"),),
           note="AC8 曲目 57（Moon 11 女声独唱）。『噩梦』是常用词，只走参考行 Nightmare 锚定。"),
    Entity("Paint It Blue", modes=("bi",), en="Paint It Blue", category="作品/曲目",
           variants=("Painted Blue",),
           note="⭐ 音频复核定案（2026-10-14）：原字幕 Painted Blue 系 ASR 误听，实为 Paint it blue。"),
    Entity("Moonlit Shadow", modes=("bi",), en="Moonlit Shadow", category="作品/曲目",
           variants=("Moollet Shadow",),
           note="⭐ 音频复核定案：主播口播 moonlit shadow（自称曲名后旋即改口为 Gaffed Card）。"),
    Entity("琵琶", modes=("bi",), en="pipa", category="乐器",
           variants=("Peipa", "peipa"),
           note="⭐ 音频复核定案：主播口播 pipa（琵琶），原字幕作 peipa。"),
    Entity("XT-40", modes=("bi",), en="XT-40", category="机体",
           variants=("XD40", "XD-40", "XD 40"),
           note="⭐ 音频复核定案：主播口播 XT forty（Moon 11 座机 XT-40D），原字幕作 XD40。"),
    Entity("哈卡舞", modes=("bi",), en="haka", category="术语",
           variants=("哈卡里",),
           note="毛利战舞 haka。谷翻把『in the haka』译成『在哈卡里』，回改为哈卡舞。"),
    # ============================================================
    # 2026-10-15 《A Complete Crashout Regarding Wuthering Waves》二次校准沉淀
    #   （英文原声·谷歌机翻双语，6934 cue，bi 模式；官方中文逐句复查补名词漏校）。
    #   甄别戒律：生僻音译组合才收裸键；常用词/常见译名一律 ctx 参考行锚定。
    #   不录项：'环形人'(Looper)、'奥古斯都'(Augustus) 系主播自造昵称/凯撒玩梗，
    #   对英文行忠实、无官方对应，保留原译；#1005 '小碎片'(my little fragment)
    #   字面义保留，仅 Fractus 锚定的'碎片'(#2830)收口。
    # ============================================================
    Entity("漂泊者", modes=("bi",),
           ctx=((r"\brover", "探测车"),),
           note="Crashout 片补漏：Rover 谷翻成'探测车'57处（#111 起，全部经英文行 "
                "rover 锚定核验，无失配），'探测车'为正常词绝不裸键。"),
    Entity("达妮娅", modes=("bi",),
           ctx=((r"\bDia\b|\bDia's\b", "迪娅"),),
           note="Crashout 片补漏：Denia 被主播昵称为 Dia，谷翻作'迪娅'13处（#1869 起），"
                "须参考行 Dia 佐证；'迪娅'两字有他片误伤风险，不裸键。"
                "#2747 口误形 Dana 走侧车（常见英文名不建键）。"),
    Entity("守岸人", modes=("bi",), en="The Shorekeeper",
           variants=("肖基珀",),
           note="Crashout 片补漏：Shawkeeper 谷翻音译'肖基珀'7处（#1894 起），生僻组合裸键安全"
                "（同既有'肖尔基珀'）。"),
    Entity("木禺", modes=("bi",),
           ctx=((r"Muyu|Amuyu", "木余"), (r"Muyu|Amuyu", "木雨"),
                (r"Muyu|Amuyu", "木宇"), (r"Muyu|Amuyu", "木羽"),
                (r"Muyu|Amuyu", "穆尤"), (r"Muyu|Amuyu", "穆优"),
                (r"Muyu|Amuyu", "木优"), (r"Muyu|Amuyu", "阿姆优")),
           note="Crashout 片补漏：Muyu/Amuyu 谷翻同音拆字 8 形（#3365/3460 等）。"
                "'木雨/木羽/木优'等均为正常词组合，一律 Muyu 佐证才改，绝不裸键。"),
    Entity("卡提希娅", modes=("bi",),
           ctx=((r"Karthia|Cartethyia", "卡尔蒂亚"), (r"Karthia|Cartethyia", "卡蒂亚"),
                (r"Karthia|Cartethyia", "卡蒂娅"), (r"Karthia|Cartethyia", "卡西娅"),
                (r"\bKia\b", "起亚")),
           note="Crashout 片补漏：Cartethyia 被主播念作 Karthia/Kia，谷翻作卡尔蒂亚/卡蒂亚/"
                "卡蒂娅/卡西娅/起亚 诸形（#1644/2537/4198 等）。'卡蒂娅'是常见译名、"
                "'起亚'是汽车品牌，全部走参考行锚定，绝不裸键。"),
    Entity("嘉贝莉娜", modes=("bi",),
           variants=("加尔布丽娜", "吉尔布丽娜"),
           note="Crashout 片补漏：Galbrena 谷翻音译二形（#966/2276/6862 等），生僻长键裸键安全。"),
    Entity("尤诺", modes=("bi",), en="Iuno",
           variants=("卢诺", "Luno", "Lunos", "Youo"),
           note="Crashout 片补漏：官方英文名 Iuno（英配 Ella Boyes；萌娘百科/百度百科"
                "均作 Iuno，源自罗马 Juno 的拼写变体，勿写成 Juno）。"
                "主播念 Luno/Juno 混杂，谷翻'卢诺'10处、英文残留 Luno/Lunos（#871/6574）。"
                "'Luno 系'拼写生僻裸键安全；'露玛'等其余形本片未出现，不臆造。"),
    Entity("赞妮", modes=("bi",), en="Zani",
           variants=("Zany",),
           note="Crashout 片新增角色实体：Zani（3.5 热熔大剑角色）ASR 成 Zany 残留中文行"
                "8+ 处（#5713 '我有 Zany S6 R2'）。大小写敏感裸键；小写 zany 普通形容词不收。"),
    Entity("弗洛洛", modes=("bi",),
           ctx=((r"Favlova|Havlova|Pavlova", "法夫洛娃"),
                (r"Favlova|Havlova|Pavlova", "哈芙洛娃"),
                (r"Favlova|Havlova|Pavlova", "帕芙洛娃"),
                (r"Favlova|Havlova|Pavlova", "巴甫洛娃")),
           note="Crashout 片补漏：Phrolova 被主播念成 Favlova/Havlova/Pavlova，谷翻作"
                "法夫洛娃/哈芙洛娃/帕芙洛娃/巴甫洛娃 16 处（#3465/3569/5044 等）。"
                "'巴甫洛娃'是常见译名（网坛姓氏），必须参考行锚定，绝不裸键。"),
    Entity("残星会", modes=("bi",),
           ctx=((r"Fractus|fracters", "分叉"), (r"\bFractus\b", "碎片")),
           note="Crashout 片补漏：Fractsidus 被主播口语化成 Fractus/fracters，谷翻作"
                "'分叉'（#2817/3101）；#2830 '碎片'由 Fractus 佐证收口。"
                "⚠ #1005 'my little fragment'（字面 fragment，昵称）的'碎片'无 Fractus 锚定，"
                "必须保留——本条 ctx 只收 \bFractus\b 佐证形。'分叉/碎片'正常词绝不裸键。"),
    Entity("鸣式", modes=("bi",),
           variants=("西奥丹斯", "西奥丹人", "西奥丁", "西奥丹",
                     "Theodin", "theodin", "Theodan", "Theodans", "theodans"),
           note="Crashout 片补漏：Threnodian 被主播念成 Theodin/Theodan（维基百科词条亦载俗称），"
                "谷翻'西奥丁/西奥丹'9处 + 英文残留 6 处（#544/617/3154/6427 等）。"
                "长键'西奥丹斯/西奥丹人'必须先咬（表按键长降序自动保证），防'鸣式斯'畸形。"),
    Entity("心月狐", modes=("bi",),
           ctx=((r"\bHin\b", "Hin"),),
           note="Crashout 片补漏：Hsin 又被 ASR 截成 Hin（#1011/3363/4198，参考行 Hin's 佐证）。"
                "'Hin'三字母裸键会咬 Hindi 等词，仅走 \bHin\b 锚定。"),
    Entity("爱弥斯", modes=("bi",), en="Aemeath",
           ctx=((r"\bAmia\b", "阿米娅"),),
           note="Crashout 片补漏：Aemeath(/ˈiːmɪθ/) 被 ASR 成 Amia，谷翻'阿米娅'1处（#2711）。"
                "'阿米娅'=Arknights 阿米娅常用译名，绝不裸键，仅 Amia 佐证才改。"),
    # --- 2026-10-22 RBGTalk 鸣潮 OST reaction 二校 ---
    #   官方依据：B站《鸣潮》先约电台 EP2.4/EP3.7 发布文案 + Genius 歌词页
    #   （Ode to Hsin and Moon: Endless Yearning）+ 百度百科「定玄」。
    Entity("心月辞·长相望", modes=("bi", "react"),
           en="Ode to Hsin and Moon: Endless Yearning",
           category="曲目/鸣潮3.7·心 EP",
           note="3.7 心《心月辞》EP 收录曲，官方中文《心月辞·长相望》（英 Ode to Hsin and Moon: "
                "Endless Yearning）；苏诗丁演唱，金大洲制作/作曲，吴姝霆/SmileL 作词。"
                "片源正文未直呼曲名，仅用于片源档案/标题/tag 与 AI 跨语识别。"),
    Entity("Forts", modes=("bi", "react"), en="Forts",
           category="音乐人/演唱",
           note="《逆潮》（Against the Tide）官方演唱者（EP2.4 卡提希娅角色曲）；"
                "官方 credit 保留英文名，不音译。片源 cue112 主播读 credit 时点名。"),
    Entity("Obadiah Brown-Beach", modes=("bi", "react"), en="Obadiah Brown-Beach",
           category="音乐人/作曲",
           note="《逆潮》官方词曲/编曲/吉他（EP2.4 卡提希娅角色曲，B站先约电台发布文案）；"
                "官方 credit 保留英文全名。谷翻音译「奥巴代亚·布朗」，BILINGUAL_TERMS/"
                "REACT_TERMS 已收变体。"),
    # --- 2026-10-23 Journey Well'ed（Juno 的鸣潮 3.1 拉海洛实况）二校沉淀 ---
    Entity("辛吉勒姆", modes=("bi",), en="Sigillum", category="BOSS/鸣潮3.1",
           variants=("siblum",),
           note="3.1 主线 BOSS。siblum 为本片 ASR 变体；既有扁平键 西吉鲁姆->辛吉勒姆 同目标，勿重复收。"),
    Entity("电子幽灵", modes=("bi",), en="Digital Ghost", category="设定/鸣潮3.1",
           variants=("数字幽灵", "网络幽灵", "digital ghost", "cyber ghost"),
           note="爱弥斯 3.1 形态，官方作「电子幽灵」；机翻常作 数字幽灵/网络幽灵（本片 #872/#1522）。"),
    Entity("声痕", modes=("bi",), en="Tacet Mark", category="设定/鸣潮",
           variants=("tacent mark",),
           note="共鸣者身上的声痕（Tacet Mark）；tacent 为 Tacet 的 ASR 拼写（本片 #1190）。"),
    Entity("飞行雪绒", modes=("bi",), en="Fleet Snowfluff", ja="フリート・スノーフラッフ",
           category="角色/歌手/鸣潮3.1",
           note="爱弥斯发布歌曲所用化名，官方中文「飞行雪绒」，英文 Fleet Snowfluff"
                "（萌娘百科/Apple Music《飞行雪绒》EP/Bangumi 别名表）；日文 フリート・スノーフラッフ。"
                "旧音译「弗利特·斯诺芙」已于 2026-10-24 修正。"),
    Entity("虚质磁暴", modes=("bi",), en="Voidstorm",
           category="地点/现象/鸣潮3.1",
           note="拉海洛区域性海蚀现象，官方中文「虚质磁暴」（萌娘百科/官方剧情文本）；"
                "旧译「虚质风暴」已于 2026-10-24 收敛。"),
    Entity("炉芯", modes=("bi",), en="Reactor Core",
           category="术语/鸣潮3.1",
           note="隧者动力核心，官方中文「炉芯」；机翻常作反应堆核心/反应堆。"
                "「核心」是通用词，只走英文 reactor 锚定（见 CONTEXT_MAP 2026-10-24 块），不入裸键。"),
]

