# -*- coding: utf-8 -*-
# @version 2.9.0
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
                (r"やんやん|ヤんやん|にゃんやん", "妮艳"),
                 (r"やや|ヤヤ|やんやん", "丫丫")),   # 2026-11-01 r2 cue 1612
           note="鸣潮 4★ 今州共鸣者。日语昵称=やんやん；谷翻音译成 燕燕/延雅/Nyanyan/ヤ。"
                "'燕燕'为正常中文词，只走日语行锚定 ctx（本片主播也昵称其为'鹿'）。"),
    Entity("今州", modes=("ja",), ja="今州",
           category="地名/鸣潮",
           ctx=((r"今週場|今州城", "本周的场外"), (r"今週場|今州城", "本周场"),
                (r"今週場|今州城", "今周场"), (r"今週場|今州城", "今正场"),
                (r"今週(?!場)(?!って|だった|に|は|の|も|から|まで|末|中|や|、|。|$)|今州", "本周"),
                (r"今週(?!場)(?!って|だった|に|は|の|も|から|まで|末|中|や|、|。|$)|今州", "这周"),
                (r"今週(?!場)(?!って|だった|に|は|の|も|から|まで|末|中|や|、|。|$)|今州", "纳迦")),
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
                (r"ショアキーパー", "海岸看守"),
                # 2026-11-01 r2《鸣潮 世界观PV/锁暝PV》ja 直播新增：
                # ASR 给出 シャーキーパー/ケートキーパー/シュアキーパー/ゲートキーパー，
                # 并存在截短 シャキ——cue 574「シャキだよね。シャキーパー」同行给出全形，
                # 证明截短与全形同指，故锚点含 シャーキ。谷翻产出 摇晃者/稳妥守料/守门人/
                # 鲨鱼守护者/沙基，或干脆留拉丁 Keto Keeper/Shore。
                # ⚠ 裸 "Shore" 会咬英文 Shorekeeper（_replace_report 是无词边界的 str.replace）
                #   ⇒ 一律走锚定；「鲨鱼守护者」不得入裸键（本片真出现过「鲨鱼」语境）。
                #   长形排前，防短形抢咬。
                (r"キーパー|シャーキ|ショアキ|ケートキ|シュアキ", "守门人Perme-dama"),
                (r"キーパー|シャーキ|ショアキ|ケートキ|シュアキ", "Perme-dama"),
                (r"キーパー|シャーキ|ケートキ|シュアキ", "鲨鱼守护者"),
                (r"キーパー|シャーキ|ケートキ|シュアキ", "鲨鱼饲养员"),
                (r"キーパー|ケートキ|シュアキ", "Keto Keeper"),
                (r"キーパー|シュアキ", "稳妥守料"), (r"キーパー", "守门员"),
                (r"キーパー|ゲートキーパー|ゲート守", "守门人"),
                (r"ゲート守", "守门的人"), (r"シャキ", "摇晃者"),
                (r"シャーキ", "沙基")),
           note="鸣潮角色，官方中文=守岸人（Shorekeeper）。谷翻把 ショアキーパー 按字面译成'岸上看守'。"
                "2026-11-01 r2 扩：シャキ 系截短与 摇晃者/稳妥守料/守门人/鲨鱼守护者/Keto Keeper/"
                "沙基 走锚定；裸键 Shore 会咬 Shorekeeper 故禁用，且 cue 2094 的 ショア 经与 2093/2098 同句"
                "互证实为 ブラックショア(黑海岸)，故 Shore 只逐 cue 处理、不入表。"),
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
                (r"フローヴァ|フローバ|フロバ|ブローバ|フロー", "弗洛巴"),
                 # 2026-11-01 r2：ASR 作 フローマ/フロボ，谷翻出 弗洛拉大人/Probo大人
                 (r"フローマ|フロボ", "弗洛拉"),
                 (r"フローマ|フロボ", "Probo")),
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
                (r"カルテジア|カテジア|カルデジア", "Cartégia"),
                 # 2026-11-01 r2（世界观PV/锁暝PV 直播）：ASR 作 カルテア/カルテー
                 (r"カルテア|カルテー", "Cartea"),
                 (r"カルテア|カルテー", "卡特酱")),
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
                (r"セブン(?!イレブン)", "7-Eleven"),
                (r"セブン(?!イレブン)", "七个"),
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
                (r"名式|鳴式|明識", "纳西克"),
                 # 2026-11-01 r2：めいしき→名式 被谷翻拆成"名称/公式/名字"
                 (r"名式|鳴式", "名称和公式"), (r"名式|鳴式", "名称公式"),
                 (r"名式|鳴式", "知名名字")),
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
                (r"フラクト|シデス", "果糖"),
                # 2026-11-01 r2《鸣潮 世界观PV/锁暝PV》ja 直播新增：
                # フラクトシデス 的**子词直译**整条路径表内全缺——Fracto(折断)→骨折/断裂、
                # fructose→分叉酸/碎片酸、sidus→灭绝罪犯，谷翻还给出 分裂城/果实果树/
                # 苞叶/断乳石/果苷念 这类瞎拆。印证「三条产出路径」教训：音译形已收 20+，
                # 子词直译形一条没有。这些全是正常中文词 ⇒ 只走锚定，长形排前。
                (r"フラクト|シデス|ブラクト", "弗鲁克托西斯"),
                (r"フラクト|シデス|ブラクト", "弗拉克塔西德"),
                (r"フラクト|シデス|ブラクト", "弗拉克托西"),
                (r"フラクト|シデス|ブラクト", "断裂灭者"),
                (r"フラクト|シデス|ブラクト", "果实果树"),
                (r"フラクト|シデス|ブラクト", "灭绝罪犯"),
                (r"フラクト|シデス|ブラクト", "分叉酸"),
                (r"フラクト|シデス|ブラクト", "碎片酸"),
                (r"フラクト|シデス|ブラクト", "fractosi"),
                (r"フラクト|シデス|ブラクト", "分裂城"),
                (r"フラクト|シデス|ブラクト", "果苷念"),
                (r"フラクト|シデス|ブラクト", "断乳石"),
                (r"フラクト|シデス|ブラクト", "骨折"),
                (r"フラクト|シデス|ブラクト", "断裂"),
                (r"フラクト|シデス|ブラクト", "苞叶"),
                (r"フラクト|シデス|ブラクト", "Fract")),
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
           ctx=((r"インペラトル", "叶轮"),),   # 2026-11-01 r2：叶轮是正常词，只走锚定
           note="官方中文=英白拉多（英 Imperator / 日 インペラトル）。"
                "谷翻把英文残留 imperator/impirator 直接抄进中文行，生僻裸键安全。"),
    Entity("黎那汐塔", modes=("ja",), en="Rinascita", ja="リナシータ",
           category="地点/鸣潮2.x",
           variants=("Linashita", "Linasy", "莉娜西塔", "莉娜·西塔"),
           ctx=((r"リナシー", "莉娜·西格"),),   # 2026-11-01 r2：ASR 截断成 リナシーグ
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
           ctx=((r"オーガスタ|おおがさ", "小笠"), (r"オーガスタ|おおがさ", "大笠")),
           note="鸣潮 2.x 七丘总督奥古斯塔（18183《尤诺》「向总督奥古斯塔指控」；3.x 实装 5★）。"
                "日 オーガスタ。谷翻作「奥古斯特」，官方用字为「奥古斯塔」。"
                "2026-10-30 补：ASR おおがさ 被谷翻成 小笠/大笠（#605/#623），走日语锚定。"),
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
           ctx=((r"\bJue\b", "朱"), (r"\bJer\b", "杰尔"),
                (r"\bJouer\b", "乔尔"), (r"^(?!.*\b2B\b).*\b2A\b", "2A")),
           note="今州岁主，官方中文=角（单字）。⚠ 高风险术语：canonical'角'与错形'朱'均极常用，"
                "'朱'（姓氏/红色）只走参考行 \\bJue\\b 强锚定才改，绝不裸键；英文残留 Jue 生僻裸键。"
                "ASR 变体 Ju 太短歧义，本轮不收。"
                "2026-10-27 ABRAXAS 片 ASR `Joy`→谷翻「乔伊」，抽帧为龙形岁主；"
                "Joy 为常见名，只做本片 sidecar，不入全局 ctx/裸键。"),
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
           variants=("Fractsidus", "Fractidus", "弗赖杜斯", "Fraidus", "Fractus", "fractus"),
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
                "「危机演习」是特定错形，但仍以英文 crisis drill/contract 锚定，避免泛化。"
                "2026-10-25 多游戏 --react 片源（Gacha Tier List）8 处 CC 用侧车改；"
                "#2401 NIKKE 段 'Okay, CC' 是反例，不能套用方舟危机合约规则。"),
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
    # --- 2026-10-26 二校沉淀：终末地 1.6「未来版本前瞻」reaction（115 cue，--endobi）---
    #   官方依据：官方中配《塔卫二：一号简报》、1.6 特别节目未来前瞻、
    #   1.7 前瞻摘要（B站 BV1fTpP6YEjn / BV1mPpA62E87）；画面 3:20 GOLDEN BRANCH、
    #   9:40 Games of Wonder、9:55 Shattered Protocol。
    #   ⚠ 明晦炉/泰拉之海取脚本既有官方口径；B站文字「明晖炉/泰拉的海洋」作为变体。
    Entity("金绒树", modes=("endo", "endobi"), en="Golden Branch",
           category="地点/终末地1.7",
           variants=("金流苏",),
           note="白垩洲巨型树木，官方中配「金绒树」；英文 UI GOLDEN BRANCH。"
                "⚠ 不与边狱公司「金枝」（golden bough）共用裸键；金枝只在 golden branch 英文锚定下改。"),
    Entity("明晦炉", modes=("endo", "endobi"), en="",
           category="设施/终末地1.7",
           variants=("明晖炉", "明慧炉"),
           note="1.7 阵列科技设施，官方中文口径「明晦炉」（脚本既有；B站基建总结写「明晖炉」，按变体处理）。"
                "官方英文名未公布，en 留空。"),
    Entity("明晦赤铜矿", modes=("endo", "endobi"), en="",
           category="资源/终末地1.7",
           variants=("明晖赤铜矿",),
           note="明晦炉随机转化产物（B站基建总结写「明晖赤铜矿」）；与明晦炉同字符口径，待官方 UI 最终核实。"),
    Entity("息壤气", modes=("endo", "endobi"), en="",
           category="资源/终末地",
           variants=(),
           note="明晦炉接入后激活阵法的气体资源；官方中文「息壤气」。纯元数据，无错形规则。"),
    Entity("持阵法", modes=("endo", "endobi"), en="Sustained Array",
           category="机制/终末地1.7",
           variants=(),
           note="明晦炉 5×5 区域周期执行的阵法；官方中文「持阵法」。不收裸「持阵」（通用词）。"),
    Entity("集成核心区域", modes=("endo", "endobi"), en="Integrated Core Area",
           category="地点/终末地1.7",
           variants=(),
           note="1.7 新开放、与武陵城同级的集成核心地块；官方中文「集成核心区域」。"
                "⚠ 不收「集成核心区」短变体：它是正确名的子串，直接替换会产出「区域域」。"),
    Entity("妙趣游乐", modes=("endo", "endobi"), en="Games of Wonder",
           category="玩法/终末地1.7",
           variants=("妙趣横乐",),
           note="1.7 新打牌/联机玩法；画面英文 Games of Wonder，官方中文「妙趣游乐」。"
                "⚠ 勿改作「妙趣横乐」。"),
    Entity("破碎协议", modes=("endo", "endobi"), en="Shattered Protocol",
           category="玩法/终末地1.7",
           variants=(),
           note="高随机性大型肉鸽玩法；画面英文 Shattered Protocol，官方中文「破碎协议」。"
                "本片 SRT 的 RoC strategy 即此模式（不是妙趣游乐）。"),
    Entity("致幻孢子", modes=("endo", "endobi"), en="",
           category="设定/终末地1.7",
           variants=(),
           note="蘑境幻境来源；官方中配「致幻孢子」。纯元数据，无错形规则。"),
    Entity("蜜饼", modes=("endo", "endobi"), en="",
           category="食物/终末地",
           variants=(),
           note="小刻最爱的食物；官方中配「蜜饼」。纯元数据，无错形规则。"),
    Entity("泰拉之海", modes=("endo", "endobi"), en="",
           category="地名/终末地",
           variants=("泰拉的海洋",),
           note="《塔卫二：一号简报》旁白的海域概念，脚本既有官方口径「泰拉之海」；"
                "B站文字「泰拉的海洋」作为变体归一。"),
    Entity("南大洋", modes=("endo", "endobi"), en="Southern Ocean",
           category="地名/终末地",
           variants=(),
           note="《塔卫二：一号简报》南方海域；官方中文「南大洋」。纯元数据，无错形规则。"),
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
           variants=("心月狐骨", "Sheena", "Shina"),
           ctx=((r"\btwo shins?\b|\bshins?\b", "小腿"),
                (r"\bChin\b", "下巴")),
           note="3.7 五星导电音感仪、梦州岁主、梦州文明引导者，官方角色名单字「心」"
                "（CV 菊花花）；「心月狐」为岁主全称/狐狸形态称谓（旧实体保留，二者勿互删）。"
                "谷翻把 Shin 错拆成「心月狐骨」（cue332/335，绝无歧义，裸键->心）；"
                "two shins 按 shin(胫骨) 译「小腿」、Chin 按 chin(下巴) 译「下巴」，"
                "均极常用词，只走参考行 shin/Chin 锚定改「心」，绝不裸键（\\bChin\\b 词边界"
                "不会咬进 Chinshi 等串）。⚠ 旧 ctx 有 Shin->心月狐（错形 申/辛/胫），"
                "与本条（错形 小腿/下巴->心）错形不同可共存；人工精修按语境在「心/心月狐」间取舍。"
                "2026-11-06《I Played 300 Days》二校扩 Sheena/Shina 裸键（微软翻译通道 ASR 形；"
                "Sheena 亦《最终幻想X-2》主角、Shina 北野武「菊次郎」片常见拼写，**跨游戏片慎用**，"
                "鸣潮 bi 片内出现即心）；岁主本体语境仍走 the Moon Fox/Sheen->心月狐。"),
    Entity("角", modes=("bi",), en="Jue / JER / Jerame",
           category="角色/岁主·鸣潮3.7",
           variants=("杰拉姆",),
           ctx=((r"\bJer\b", "杰尔"), (r"\bJouer\b", "乔尔"),
                (r"^(?!.*\b2B\b).*\b2A\b", "2A")),
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
                (r"\bGuardian\b", "卫报"),
                (r"\bSentinels?\b", "哨兵"),
                (r"\bSentinels?\b", "哨兵们")),
           note="梦州岁主（国际服 Sentinel；3.7 心为 Mengzhou's first playable Sentinel、"
                "心月狐为前任岁主）。第三部片主播 LightfulWings 口播中常以 Guardian/Watcher "
                "代指 Sentinel。谷翻把 Guardian 误作法律词'监护人'（cue51/145/156）、报纸名"
                "'卫报'（cue187/190/218），均常用词，只走参考行 Guardian 锚定归岁主。"
                "⚠ '守护者'是 Guardian 的正确中文且 cue35 'Shin's Guardian' 取『心的守护者』"
                "关系义（指心月狐），不入规则、留人工 pair 在守护者/岁主间取舍；Watcher 语境"
                "的'守望者'见 EXCLUDE_CONTEXT 负向排除（不得归守岸人 Shorekeeper），"
                "'监视者->守望者'挂 CONTEXT_MAP。"
                "⚠ 2026-11-11 莉莉 PV 片（LightfulWings，80 cue）#71/#74：YouTube ASR 把 Shorekeeper "
                "听成 'Reliable Keeper'/'reliable Guardian'，本地 ASR 实证为 surekeeper=守岸人；"
                "本条 Guardian→岁主 ctx 会把「可靠的监护人」误改成「可靠的岁主」。凡参考行作 "
                "reliable Guardian/Reliable Keeper（带 reliable）且语境为『想救所有人却救不了』者，"
                "归守岸人而非岁主——高碰撞，逐 cue 回退，不加全局回滚规则以免伤 3.7 岁主锚。"),
    Entity("心之集域", modes=("bi",), en="dream realm / dream realms / Somnoire",
           category="地点/鸣潮",
           ctx=((r"\bdream realms?\b", "梦境领域"),
                (r"\bdream realms?\b", "梦之领域"),
                (r"\bdream realms?\b", "梦境之境"),
                (r"\bdream realms?\b", "梦境")),
           note="鸣潮心之集域，白猫/黑猫为心之集域的守门人。2026-10-27 ABRAXAS 反应片"
                "（Rubee，173 cue）实证：谷翻固定作「梦境领域」，属常用组合，只走参考行 "
                "dream realm 锚定，不进裸键。"),
    Entity("守门人", modes=("bi",), en="gatekeeper / gatekeepers",
           category="设定/鸣潮",
           ctx=((r"\bgatekeepers?\b", "看门人"),
                (r"\bgatekeepers?\b", "守门者"),
                (r"\bgatekeepers?\b", "门卫")),
           note="心之集域的守门人（白猫/黑猫）。谷翻「看门人」为常用词，只走参考行 "
                "gatekeeper 锚定；2026-10-27 ABRAXAS 片沉淀。"),
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
           variants=("斯沃明", "Suwamin", "Suvamin", "Slonmin", "Slongming",
                     "Somin", "So Min", "Swimin"),
           ctx=((r"\bSwaming\b", "游水"), (r"\bSwinging\b", "摇摆")),
           note="本片补录：Swaming 的谷翻音译'斯沃明'（生僻裸键）；ASR 形 Swaming->谷翻"
                "'游水'、Swinging->'摇摆'（均常用词，只走参考行锚定）。"
                "2026-11-06《I Played 300 Days》微软翻译通道扩：Suwamin/Suvamin/Slonmin/"
                "Slongming/Somin/So Min/Swimin 皆 Suoming 的 ASR 音译残留（生僻串，"
                "裸键安全；So Min 含空格由表键长降序先于 Somin 咬合）。"),
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
           ctx=((r"(?<!my )\bNightmare\b(?!\s+Before\b)", "噩梦"),),
           note="AC8 曲目 57（Moon 11 女声独唱）。『噩梦』是常用词，只走参考行 Nightmare 锚定；《圣诞夜惊魂》片名用负向前瞻排除。2026-11-13 鸣潮莉莉 3.8 反应片判例：PV 台词 \"My nightmare.\" 是普通词，前置 (?<!my ) 排除（lookbehind 必须放在 \\b 之前才检查命中起点左侧），防跨片吃掉「我的噩梦」。"),
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
           variants=("Zany", "Zunny", "Zanie", "善尼"),
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
           ctx=((r"\bAmia\b", "阿米娅"),
                (r"\bAmth\b|\bAmoth\b", "阿姆斯"),
                (r"\bAmeth\b|\bAmoth\b", "紫草酸")),
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
    # --- 2026-10-25 鸣潮 4.0 新联邦 reaction 片：无官方中文的术语只登记知识，不做替换 ---
    Entity("Ichor", modes=("bi",), en="Ichor",
           category="术语/鸣潮4.0",
           variants=("Icor",),
           note="4.0 新联邦概念/金色神血；截至 2026-10-25 无官方中文。字幕保留 Ichor 并加意译「神血」，"
                "不设扁平替换（不做无依据音译）。"),
    Entity("Overthrown", modes=("bi",), en="Overthrown",
           category="敌人/鸣潮4.0",
           note="4.0 预告眼球状存在；截至 2026-10-25 无官方中文。字幕保留 Overthrown（Overthrow），"
                "不臆造中文名；不配置任何替换，避免与 Overthrown 子串互相误伤。"),
    # --- 2026-10-25 明日方舟 CN 7.5 周年感谢庆典：新干员 / 活动 / 地点 ---
    Entity("塔露拉", modes=("ak",), en="Talulah", category="干员/明日方舟7.5",
           variants=("塔罗拉", "优斯塔露拉"),
           note="6★ 近卫·本源近卫（灼燃），限定；2026-10-24 CN 7.5 周年感谢庆典前瞻；"
                "天赋「绝不妥协」「我即火焰」，技能「照霎白夜」「阂断骤雪」「日冕重烈」；"
                "第二天赋留下「足迹」，三技能召唤「簇火」。"),
    Entity("冻河", modes=("ak",), en="Toska", category="干员/明日方舟7.5",
           variants=("动合", "动核", "冻核", "Fyodor", "费奥多尔"),
           ctx=((r"\b(?:Toska|Fyodor|taka)\b", "冻和"),),
           note="6★ 辅助·游击手；英文代号 Toska，本名费奥多尔（Fyodor，官方微博 #冻河# #费奥多尔#）；"
                "天赋「夜的哑然」「雪的印痕」，技能「一无所有之人」「意欲呼啸之心」「踽踽独行之春」；核心=触发型效果（技力拐）。"
                "2026-11-11：裸键「冻和」咬「冰冻和眩晕」→「冰冻河眩晕」，改 ctx 锚定；补 Fyodor/费奥多尔→冻河。"),
    Entity("国度", modes=("ak",), category="干员/明日方舟7.5",
           note="6★ 特种·伏击客，赠送；天赋「国度」，技能「停步」「受戮」「无人的国度」；"
                "国度为普通词，不设裸变体，仅按上下文逐 cue 处理。"),
    Entity("奥尔佳", modes=("ak",), en="Olga", category="干员/明日方舟7.5",
           variants=("奥尔加",),
           note="5★ 近卫·教官；2026-10-24 CN 7.5 周年感谢庆典前瞻。"),
    Entity("镜匠", modes=("ak",), en="Caleido", category="干员/明日方舟7.5",
           note="5★ 重装·本源铁卫；采购凭证商店兑换；英文名 Caleido。"),
    Entity("行铃", modes=("ak",), en="Herd Bells", category="干员/明日方舟7.5",
           note="4★ 特种·调度者；采购凭证商店兑换；本名梅里塔（官方微博），英文名 Herd Bells。"),
    Entity("梅里塔", modes=("ak",), en="Melitta", category="角色/明日方舟7.5",
           note="行铃本名；官方微博 2026-10-25「我叫梅里塔」。"),
    Entity("将雪投火", modes=("ak",), category="活动/卡池/明日方舟7.5",
           note="7.5 周年限定寻访，11/1–11/15。"),
    Entity("沉沦者的黑流树海", modes=("ak",), category="活动/集成战略/明日方舟7.5",
           note="集成战略主题，内容拓展II。"),
    Entity("梦城堡", modes=("ak",), category="活动/特别映像/明日方舟7.5",
           note="特别映像：乌萨斯、维多利亚（梦城堡）。"),
    Entity("墨菲斯", modes=("ak",), en="Morphus", category="角色/明日方舟7.5",
           variants=("Morphus",),
           note="维多利亚特别映像相关角色；官方中文墨菲斯。"),
    Entity("卫戍协议", modes=("ak",), category="玩法/明日方舟7.5",
           note="卫戍协议「规程·序列I」，11/8 常驻。"),
    Entity("弹雨作战", modes=("ak",), category="玩法/危机合约/明日方舟7.5",
           note="危机合约#6「弹雨作战」。"),
    # --- 2026-11-11 明日方舟《Should You Save for Talulah?》新干员（仅元数据，错形键在 ark.py 2026-11-11 块）---
    Entity("克莱门莎", modes=("ak",), en="Clementia", category="干员/明日方舟",
           note="6★ 近卫·本源近卫（侵蚀），2026.10.9「昨日海」；天赋「生死定夺」（暴击，目标防御低于初始值时概率提升）"
                "「习得性防御」（前方物理/法术减伤30%，对海怪提高）；技能「冲蚀」「风暴潮」「与海为敌」；"
                "S2 召唤「浮游放逐舱」（累计重量≤8 可推任意敌人，含 Boss）并留下漩涡（每秒侵蚀损伤，固定值）；"
                "S3 弹药 10 发，侵蚀爆发触发时核爆（3 次物理+元素伤害）；主播戏称 Hydro mommy/水系妈妈、water Changli/水系长离。"
                "官名依据 PRTS 2026-11-11 二校核实（稀有度字段 0 起始，5=6★）。"),
    Entity("妮芙", modes=("ak",), en="Nymph", category="干员/明日方舟",
           note="6★ 术师·本源术师（凋亡损伤），2024.7；S2 上恐惧，恐惧体系首选。"),
    Entity("烛煌", modes=("ak",), en="Blaze the Igniting Spark", category="干员/明日方舟",
           note="6★ 术师·本源术师（灼燃），2025 春节，煌异格；弹药机制，S3 高频多段灼燃输出。"),
    Entity("酒神", modes=("ak",), en="Tragodia", category="干员/明日方舟",
           note="6★ 辅助·巫役（神经损伤），傀影异格，本名卢西恩，2025.6.5 标准寻访；维多利亚。"),
    Entity("波卜", modes=("ak",), en="Bobbing", category="干员/明日方舟",
           note="5★ 辅助·巫役（灼燃），本名埃利西奥，2024.10「追迹日落以西」；灼燃远程拐，"
                "天赋「焦点诱导」，S2「此路不通」。谷翻「摇摆」走 ark.py ctx 锚定。"),
    Entity("霍尔海雅", modes=("ak",), en="Ho'olheyak", category="干员/明日方舟",
           note="6★ 术师；萨尔贡梅兰德基金会。AK_JA_TERMS 已有霍尔海亚→霍尔海雅，2026-11-11 补 --ak 侧。"),
    # --- 2026-11-11 《Clementia VS Potential Woman》新实体（仅元数据；错形键在 ark.py 同日块）---
    Entity("伯塔尼", modes=("ak",), en="Botani", category="干员/明日方舟",
           note="5★ 辅助·巫役（侵蚀），SideStory「人们，我们」活动赠送（2026.4.7），首位侵蚀损伤核心干员；"
                "乌萨斯学生自治团；天赋「背弃沉默」，技能「谐波破坏」「静域回声」。PRTS 2026-11-11 核实。"),
    Entity("余", modes=("ak",), en="Yu", category="干员/明日方舟",
           note="6★ 重装·本源铁卫（灼燃），限定，2025.1.22 春节「炽吾生平」；灼燃损伤拐，S3「灶里乾坤」火墙拐。"
                "PRTS 2026-11-11 核实。单字官方名，不设裸键（会误伤），仅元数据供跨语识别。"
                "英语 ASR 常把 Yu 听成 you（《Should You Save for Talulah?》#20「bobbing or you」/#95「someone like You」），"
                "需人工按灼燃拐语境判余，禁 you→余 全局键。"),
    Entity("浮游放逐舱", modes=("ak",), category="技能实体/明日方舟",
           note="克莱门莎 S2「风暴潮」召唤物：推开累计重量≤8 的任意敌人（含 Boss），附带漩涡（每秒侵蚀损伤，固定值不受防御影响）。"
                "「放逐舱」短键会咬自身产出「浮游浮游放逐舱」，不入裸键，逐 cue 处理。"),
    # --- 2026-10-25 多游戏音乐 Tier List（2747 cue）二次校准沉淀 ---
    # 片源：英语原声 + 谷翻，17 款作品、103 条分章；官方中文依据：
    #   庄方宜 endo_glossary.tsv:62；少女前线官方无「1」；
    #   TRUE FIREPOWER NIKKE 官名全大写；BATTLEPLAN ARCLIGHT PRTS 危机合约弧光作战OST；
    #   Der Hexenkönig PRTS 崔林特尔梅之金OST；
    #   灼火之心/骄阳炽燎/斩雾破竹/洄映的漩流/新月的摇篮曲/白鸽之诗、耀斑/踏上旅途/拂晓
    #   均为官方 OST/QQ音乐/萌娘百科核实。
    # 只收可复用官方名；视频特有的 Booba/H/NGE/art nights/Hyperver/Arc Light/Royal Fair/
    #   Columbina/Columbia/Voila/Zimminger/Tsar/Dual Channel Theme 留在侧车，不入裸键。
    Entity("庄方宜", modes=("jpe", "react"), en="Zhuang Fangyi",
           category="角色/终末地",
           variants=("Zhuang Fang Yi", "Zhuang Fangyi", "Zhuang FangYi", "庄芳怡"),
           note="终末地角色；endo_glossary.tsv:62；2026-10-25 二校 #1672；"
                "2026-10-26 四校 #1693 ASR Fungi=Fangyi（不设裸键）。"),
    Entity("少女前线", modes=("react",), en="Girls' Frontline",
           category="作品/游戏", variants=("少女前线1",),
           note="官方无「1」；GFL1 是视频分章标识；2026-10-25 二校 #1640。"),
    Entity("TRUE FIREPOWER", modes=("react",), en="TRUE FIREPOWER",
           category="曲目/NIKKE",
           variants=("True Fire Power", "True Firepower", "True Fire power"),
           note="NIKKE 曲名官方全大写；无官方中文，保留英文；视频信息 02:38。"),
    Entity("BATTLEPLAN ARCLIGHT", modes=("react",), en="BATTLEPLAN ARCLIGHT",
           category="曲目/明日方舟",
           variants=("Battleplan Arclight", "Battleplan arclight"),
           note="PRTS 危机合约弧光作战OST；官方全大写；2026-10-25 二校 #2023。"),
    Entity("灼火之心", modes=("react",), en="Blazing Heart",
           category="曲目/原神", variants=("Blazing Heart", "Blazing Hearts"),
           note="原神玛薇卡 EP/角色PV曲，官方中文「灼火之心」；QQ音乐/萌娘百科。"),
    Entity("耀斑", modes=("react",), en="Flares of the Blazing Sun",
           category="曲目/崩坏：星穹铁道",
           variants=("Flares of the Blazing Sun",),
           note="HSR 白厄动画短片单曲，官方中文「耀斑」；B站/萌娘/百度百科。"),
    Entity("踏上旅途", modes=("react",), en="Take The Journey",
           category="曲目/崩坏：星穹铁道",
           variants=("Take The Journey", "Take the Journey"),
           note="HSR 官方演唱会曲目，官方中文「踏上旅途」；米游社/萌娘/网易云。"),
    Entity("骄阳炽燎", modes=("react",), en="Fervent Flare",
           category="曲目/原神", variants=("Fervent Flare",),
           note="原神迪希雅角色演示曲，官方中文「骄阳炽燎」；闪耀的群星4/酷我。"),
    Entity("斩雾破竹", modes=("react",), en="Duel in the Mist",
           category="曲目/原神", variants=("Duel in the Mist",),
           note="原神稻妻战斗曲，官方中文「斩雾破竹」；寂远无妄之国/酷我。"),
    Entity("洄映的漩流", modes=("react",), en="Swirls of the Stream",
           category="曲目/原神", variants=("Swirls of the Stream",),
           note="原神须弥OST，官方中文「洄映的漩流」；智妙明论之林/酷我。"),
    Entity("新月的摇篮曲", modes=("react",), en="Lullaby of the New Moon",
           category="曲目/原神", variants=("Lullaby of the New Moon",),
           note="原神哥伦比娅摇篮曲，官方中文「新月的摇篮曲（其一）：伴月同眠」；QQ音乐/萌娘。"),
    Entity("白鸽之诗", modes=("react",), en="Columbina's Poem",
           category="曲目/原神", variants=("Columbina's Poem", "哥伦比娜诗"),
           note="原神哥伦比娅曲，官方中文「白鸽之诗」；QQ音乐/Fandom/酷狗。"),
    Entity("拂晓", modes=("react",), en="Proi Proi",
           category="曲目/崩坏：星穹铁道",
           variants=("Proi Proi", "proy proy"),
           note="HSR 官方 EP「拂晓 Proi Proi」；萌娘/百度百科/米游社。"),
    Entity("Der Hexenkönig", modes=("react",), en="Der Hexenkönig",
           category="曲目/明日方舟", variants=("Der Hexenkonig",),
           note="PRTS 崔林特尔梅之金OST；官方拼写含 ö；跨 cue 碎片由侧车处理。"),
    Entity("Sing For The Queen", modes=("react",), en="Sing For The Queen",
           category="曲目/NIKKE",
           note="官方曲名；ASR Hail the Queen 是误记，逐 cue 处理，不设裸键。"),
    Entity("Within Temptation", modes=("react",), en="Within Temptation",
           category="音乐人/乐队",
           note="乐队名保留英文，不加书名号；2026-10-25 二校 #2588/#2603。"),
    Entity("Red Ash", modes=("react",), en="Red Ash",
           category="曲目/NIKKE",
           note="曲名保留英文，中文行加《》；2026-10-25 二校 #210。"),
    Entity("雪凇幽梦", modes=("endobi",), en="Dreamscape Winter Snow",
           category="版本/终末地",
           note="终末地 1.5 版本名，官方中文；2026-10-25 二校 #1904。"),
    Entity("全球总决赛", modes=("react",), en="Worlds",
           category="赛事/英雄联盟",
           note="Worlds=英雄联盟全球总决赛；2026-10-25 二校 #752/#753；不设裸变体。"),
    # --- 2026-10-26 多游戏音乐 Tier List 四校（r4）官方名沉淀 ---
    # 片源：I Made A Gacha Game Music Tier-List...（2747 cue，react）。
    # 官方依据：R99 中文维基/官方微博、ZZZ BWIKI/官方、HSR 官方、终末地官方、
    #   GFL1/2 官方、鸣潮官方 OST、明日方舟官方、Apple Music；详见 official_names_r3/r4.tsv。
    # 戒律：通用英文短语（Prophecy/Come Alive/On the Journey/I Loved You/Fungi）不设裸键；
    #   双语标题（论灵魂 De Anima / 酣梦于彼岸深红 The Lost Beyond）只登记不设变体，防自级联。
    Entity("赞颂的回声", modes=("react",), en="Glory Reclaimed",
           category="曲目/重返未来1999", variants=("Glory Reclaimed",),
           note="R99 官方 EP《赞颂的回声 Glory Reclaimed》；2026-10-25/26 #130/#131/#1252。"),
    Entity("为惑·一", modes=("react",), en="Bewildered Heart I",
           category="曲目/重返未来1999",
           variants=("Bewildered Heart I", "Bewildered Heart Ⅰ", "Bewildered Heart1"),
           note="R99 中文维基 OST；官方 Ⅰ/Ⅱ 两版，只收带数字变体，不收裸名。"),
    Entity("为惑·二", modes=("react",), en="Bewildered Heart II",
           category="曲目/重返未来1999",
           variants=("Bewildered Heart II", "Bewildered Heart Ⅱ", "Bewildered Heart2"),
           note="R99 中文维基 OST；官方 Ⅰ/Ⅱ 两版，只收带数字变体，不收裸名。"),
    Entity("诸相非相", modes=("react",), en="Empty Phenomena",
           category="曲目/重返未来1999", variants=("Empty Phenomena",),
           note="R99 中文维基 OST：诸相非相·序/一/二；取系列名。"),
    Entity("Ice & Blood", modes=("react",), en="Ice & Blood",
           category="曲目/少女前线",
           variants=("Ice Blood", "Ice and Blood"),
           note="GFL1 官方 OST/Apple Music；英文官名补 &；2026-10-25 #1639。"),
    Entity("一诺为家", modes=("react",), en="A Promise Makes a Home",
           category="曲目/终末地",
           variants=("A Promise Makes a Home", "以诺维加"),
           note="终末地官方/汤汤 EP《一诺为家 A Promise Makes a Home》；2026-10-25 #1155/#1156。"),
    Entity("电梯音乐档", modes=("react",), category="术语/档位",
           variants=("电梯档",),
           note="Tier list 档位术语；2026-10-25 r3 统一 #1657/#1802/#2187/#2256；非官方名。"),
    Entity("论灵魂", modes=("react",), en="De Anima",
           category="曲目/鸣潮",
           note="官方双语名《论灵魂 De Anima》（黑海岸篇《五浔深处》）；双语标题不设变体，防自级联。"),
    Entity("酣梦于彼岸深红", modes=("react",), en="The Lost Beyond",
           category="曲目/鸣潮",
           note="官方 2.5 OST《酣梦于彼岸深红 The Lost Beyond》；失亡彼岸是场景名，不作曲名；不设变体。"),
    Entity("预言", modes=("react",), en="Prophecy",
           category="曲目/绝区零",
           note="ZZZ 官方《预言 Prophecy》；通用英文词不设裸键，逐 cue。"),
    Entity("覆灭重生", modes=("react",), en="Come Alive",
           category="曲目/绝区零",
           note="ZZZ 官方《覆灭重生 Come Alive》；通用英文短语不设裸键，逐 cue。"),
    Entity("不虚此行", modes=("react",), en="On the Journey",
           category="曲目/崩坏：星穹铁道",
           note="HSR 官方《不虚此行 On the Journey》；通用英文短语不设裸键，逐 cue。"),
    Entity("我曾经爱过你", modes=("react",), en="I Loved You",
           category="曲目/原神",
           note="原神至冬篇 OST《悯宥慈怜之垠》曲 21《我曾经爱过你 I Loved You》；2026-10-26 #773。"),
    Entity("少女前线2：追放", modes=("react",), en="Girls' Frontline 2",
           category="作品/游戏",
           note="官方全名；《少女前线2》为简写，裸键会自级联，故只登记不设变体；2026-10-25 #1647。"),
    Entity("Hikari", modes=("react",), en="Hikari",
           category="曲目/战双帕弥什",
           note="PGR 九龙环城主题曲官方单曲名 Hikari；ASR Hikaru/pig 需逐 cue，不设裸键；2026-10-26 #636。"),
    Entity("Remember", modes=("react",), en="Remember",
           category="曲目/重返未来1999",
           note="R99 3.0 EP 曲名 Remember；勿按动词意译；2026-10-26 #244。"),
    Entity("In Hell We Live, Lament", modes=("react",), en="In Hell We Live, Lament",
           category="曲目/边狱公司",
           note="Mili 官方全名（Limbus Company）；无官方中文，保留英文；视频章节简称 In Hell We Live；2026-10-26 #2007。"),
    Entity("巅峰档", modes=("react",), category="术语/档位",
           note="Tier list 档位术语；顶级档→巅峰档 逐 cue；2026-10-25 #81；非官方名。"),
    Entity("Awaken", modes=("react",), en="Awaken",
           category="曲目/明日方舟",
           note="明日方舟官方 EP 曲名 Awaken；Awakening 为误写；2026-10-26 #2372/#2373；通用词不设裸键。"),
    # --- 2026-10-27 《Back from Vacay! Music Listening Stream》二次校准 ---
    Entity("花雨旋律", modes=("bi", "react"), en="DEEMO II",
           category="作品/游戏",
           note="雷亚 DEEMO II 官方中文；Demo 2/Dimma 2 为 ASR 变体，通用词不设裸键；Demo 1=《古树旋律》。"),
    Entity("古树旋律", modes=("bi", "react"), en="DEEMO",
           category="作品/游戏",
           note="雷亚 DEEMO 官方中文；Demo 1 为口语，通用词不设裸键。"),
    Entity("默尔塔", modes=("bi", "react"), en="Mohrta",
           variants=("Morta",),
           category="作品/游戏",
           note="Mohrta 非线性 FPS；Steam 官方描述与 #2563 逐句吻合；勿与 Children of Morta《莫塔守山人》混；Mort 为口语缩写，逐 cue。"),
    Entity("巫术：狂王的试炼场", modes=("bi", "react"), en="Wizardry: Proving Grounds of the Mad Overlord",
           category="作品/游戏",
           note="媒体通用名；Steam 简中页仍为英文名，属无官方中文；2026-10-27 #2057。"),
    Entity("白银之城", modes=("bi", "react"), en="Silver Palace",
           category="作品/游戏",
           note="乐元素官方中文（silverpalace.leyuansu.com）；部分媒体作银色宫殿；2026-10-27 #434。"),
    Entity("GUNDAM 异轨征途", modes=("bi", "react"), en="Gundam Rogue Orbit",
           category="作品/游戏",
           note="万代/PlayStation 官方简中；2026-10-27 #536。"),
    Entity("魔御：STAR DIVE", modes=("bi", "react"), en="Mongil: Star Dive",
           variants=("Mongol Star Dive",),
           category="作品/游戏",
           note="网石官方中文；NVIDIA 官方稿；2026-10-27 #1386/#1387。"),
    Entity("Moonlit Wilderness", modes=("bi", "react"), en="Moonlit Wilderness",
           variants=("Moonlight Wilderness",),
           category="曲目/铁拳5",
           note="铁拳5 官方曲名 Moonlit；主播口播 Moonlight；无官方中文，保留英文；2026-10-27 #1604/#1660。"),
    Entity("拙皮", modes=("bi", "react"), en="Drippy",
           category="角色/二之国",
           note="《二之国：白色圣灰的女王》官方中文妖精名；2026-10-27 #1524/#1525。"),
    # --- 2026-10-30 Jadealy《TRANSCENDO》reaction 片二次校准 ---
    Entity("黑石", modes=("bi",), en="Tacetite",
           category="设定/鸣潮",
           note="官方专有名词：黑石=Tacetite（《鸣潮》专有名词中英对照）；谷翻作菱镁石/菱镁矿，"
                "走参考行锚定；2026-10-30 #190/#191/#196。"),
    Entity("纯白之塔", modes=("bi",), en="White Tower",
           category="设定/鸣潮",
           note="鸣式纯白之塔；英文 White Tower；「白塔」为通用词，只走参考行锚定；"
                "2026-10-30 #628/#629。"),
    Entity("会监", modes=("bi",), en="Overseer",
           category="组织/残星会",
           note="残星会五会监；英文 Overseer；谷翻作监工/监督者/监督员，走参考行锚定；"
                "2026-10-30 #424/#425/#431/#434/#664。"),
    # ============================================================
    # 2026-10-30 鸣潮 2.6「第二章·第九幕 今夜，注定属于月亮」日语原声 VTuber 实况沉淀
    #   片源：【#鳴潮】完全初見～２章９幕～ユーノが忘れられてる！？？
    #        （2761 cue，日语参考行 + 谷翻中字，CRLF 无 BOM，--ja）
    #   官方依据：2.6 版本说明第九幕（布里奥=礼官 / 英雄王 / 庆典 / 花雨）、
    #             萌娘百科 NPC 表（莉莉贝=谕女之首·婆婆，七丘桑古伊斯狩原四方殿）、
    #             官方活动「七丘四方殿」（四方殿=窥察命运、转述记录预言之所，谕女居处）。
    #   戒律：优诺/优野/中本聪/前农民/小笠/七个 等都是真实中文词或常见音译，
    #         一律走 ctx（日语参考行佐证），绝不裸键。
    # ============================================================
    Entity("尤诺", modes=("ja",), en="Iuno", ja="ユウノ/ユーノ/ユノ",
           category="角色/鸣潮2.6七丘",
           ctx=((r"ユウ[ノナ]|ユノ|ゆうの", "优诺"),
                (r"ユウ[ノナ]|ユノ|ゆうの", "优野"),
                (r"ユウ[ノナ]|ユノ|ゆうの", "优乃"),
                (r"ユウ[ノナ]|ユノ|ゆうの", "优牛"),
                (r"ユウ[ノナ]|ユノ|ゆうの", "优音"),
                (r"ユウ[ノナ]|ユノ|ゆうの", "尤娜"),
                (r"ユウ[ノナ]|ユノ|ゆうの", "尤那"),
                (r"ユウ[ノナ]|ユノ|ゆうの", "勇乃"),
                (r"ユウ[ノナ]|ユノ|ゆうの", "由乃"),
                (r"ユウ[ノナ]|ユノ|ゆうの", "结野"),
                (r"ユウ[ノナ]|ユノ|ゆうの", "艾尤")),
           note="鸣潮 2.6 七丘「谕女」尤诺（Iuno，姓氏西比尔；官方档案「月相轮转之间，我以我为锚点」）。"
                "ASR ユウノ/ユーノ/ユノ/ユウナ 被谷翻成 优诺/优野/优乃/优牛/优音/尤娜/尤那/勇乃/由乃/结野/艾尤。"
                "「优诺」是酸奶品牌、「优野」是日本人名，全部走日语锚定；2026-10-30 #50/#52/#261/#605 等。"),
    Entity("莉莉贝", modes=("ja",), ja="リリベル",
           category="角色/鸣潮2.6七丘",
           ctx=((r"リリベル.*おばあ", "莉莉贝尔奶奶"),
                (r"リリベル.*おばあ", "Lilibel奶奶"),
                (r"リリベル.*おばあ", "莉莉贝尔的祖母"),
                (r"リリベル.*おばあ", "莉莉贝的祖母"),
                (r"リリベル", "莉莉贝尔"),
                (r"リリベル", "Lilibel"),
                (r"リリベル", "莉莉伯")),
           note="鸣潮 2.6 七丘谕女之首「莉莉贝」婆婆（萌娘百科 NPC 表：莉莉贝 / 谕女之首 / 婆婆 / 七丘桑古伊斯狩原四方殿）。"
                "官方中文=莉莉贝（非莉莉贝尔）；谷翻音译 莉莉贝尔/Lilibel/莉莉伯，走日语锚定；2026-10-30 #726/#984/#995 等。"),
    Entity("谕女", modes=("ja",), ja="諭し/サトシの女",
           category="组织/鸣潮2.6七丘",
           ctx=((r"サトシの女|さとしの女", "中本聪家族的女性"),
                (r"サトシの女|さとしの女", "中本聪家族"),
                (r"サトシの女|さとしの女", "中本聪的女人"),
                (r"サトシの女|さとしの女", "中本聪女性"),
                (r"サトシの女|さとしの女", "中本聪"),
                (r"サトシの女|さとしの女", "中智的女人"),
                (r"サトシの女|さとしの女", "中智女性"),
                (r"サトシの女|さとしの女", "中智"),
                (r"サトシの女|さとしの女", "聪家的女性"),
                (r"サトシの女|さとしの女", "聪的女人"),
                (r"サトシの女|さとしの女", "聪女"),
                (r"サトシの女|さとしの女", "中本的女人"),
                (r"サトシの女|さとしの女", "中本女性"),
                (r"サトシの女|さとしの女", "小智的女人"),
                (r"サトシの女|さとしの女", "小聪的女人")),
           note="鸣潮 2.6 七丘「谕女」（七丘的预言家；官方「谕女给出的预言通常具有绝对的效力」）。"
                "日语 ASR 把 諭し(さとし) 写成 サトシ，谷翻当成中本聪：中本聪/中智/聪女/中本女性 等 14 形。"
                "锚点强制 サトシの女/さとしの女（裸 サトシ 可能是观众名），绝不裸键；2026-10-30 #211/#328/#1361 等。"),
    Entity("四方殿", modes=("ja",), ja="テトラゴン神殿",
           category="地点/鸣潮2.6七丘",
           ctx=((r"テトラゴン神殿", "四边神庙"),
                (r"テトラゴン神殿", "四边形神殿"),
                (r"テトラゴン神殿", "四角神庙"),
                (r"テトラゴン神殿", "寺庙")),
           note="鸣潮 2.6 七丘四方殿（官方「四方殿，窥察命运、转述记录预言之所，亦为七丘谕女们的居处」）。"
                "日 テトラゴン神殿；谷翻 四边神庙/四边形神殿/四角神庙/寺庙，全部走日语锚定；2026-10-30 #703/#1350/#1805 等。"),
    Entity("元老院", modes=("ja",), ja="元老院/元農院",
           category="组织/鸣潮2.6七丘",
           ctx=((r"元[老農]院", "前农民"),
                (r"元[老農]院", "参议院")),
           note="鸣潮 2.6 七丘元老院（与总督奥古斯塔对立）。ASR 元農院 被谷翻成「前农民」（#123），"
                "「参议院」为另一误译（#1970）；走日语锚定。"),
    Entity("布里奥", modes=("ja",), ja="ブリオ",
           category="角色/鸣潮2.6七丘",
           ctx=((r"ブリオ", "布利奥"), (r"ブリオ", "布里欧")),
           note="鸣潮 2.6 第九幕礼官布里奥（官方版本说明：「名为布里奥的礼官邀你重返营地」）。"
                "日 ブリオ；2026-10-30 #121/#122/#861。"),
    Entity("英雄王", modes=("ja",), ja="英雄王",
           category="称号/鸣潮2.6七丘",
           ctx=((r"英雄王", "英勇的国王"),),
           note="鸣潮 2.6 七丘预言中的英雄王（官方「为新诞生的英雄王…所设的庆典」）。"
                "谷翻「英勇的国王」走日语锚定；2026-10-30 #2107/#2110/#2112。"),
    Entity("新王", modes=("ja",), ja="新王/新たな王",
           category="称号/鸣潮2.6七丘",
           ctx=((r"新王|新たな王", "新国王"),),
           note="鸣潮 2.6 七丘「新王」（伪作的神王；官方第九幕「神王已死」）。"
                "谷翻「新国王」走日语锚定；2026-10-30 #287/#303/#333 等 8 处。"),
    Entity("月石金枝", modes=("ja",), ja="ルナオーラム",
           category="素材/鸣潮2.6",
           ctx=((r"ルナオーラム", "露娜·奥拉姆"),
                (r"ルナオーラム", "露娜·奥鲁姆"),
                (r"ルナオーラム", "露娜·欧拉姆"),
                (r"ルナオーラム", "月亮金币")),
           note="鸣潮 2.6 弓匠剧情素材 ルナオーラム = **月石金枝**（官方剧情原文「想要用你最喜欢的月石金枝来做这把弓」）。"
                "谷翻音译 露娜·奥拉姆/露娜·奥鲁姆/露娜·欧拉姆/月亮金币，全部走日语锚定；2026-10-30 #1390/#2192/#2217 等。"),
    Entity("镯子", modes=("ja",), ja="ブレスレット/腕輪",
           category="道具/鸣潮2.6",
           ctx=((r"ブレスレット|腕輪", "手链"),),
           note="鸣潮 2.6 尤诺的镯子（官方剧情「这只镯子，是尤诺的」）。谷翻统一作「手链」，"
                "本片按官方改「镯子」；走日语锚定，2026-10-30 #747/#861/#971 等。"),
    Entity("筹花人", modes=("ja",), ja="花配り/花を配る",
           category="称号/鸣潮2.6庆典",
           ctx=((r"花配り|花を配る", "发花的人"),
                (r"花配り|花を配る", "分发花瓣的人"),
                (r"花配り|花を配る", "负责发花瓣的人")),
           note="鸣潮 2.6 庆典角色「筹花人」（官方「邀请你作为本场庆典的筹花人之一，将象征荣耀与凯旋的玫瑰分发给大家」）。"
                "谷翻作 发花/分发花瓣；只作元数据与日语锚定，不裸键（「发花」是通用动词）。"),
    Entity("解离症", modes=("ja",), ja="解離症/脅迫症",
           category="术语/鸣潮2.6",
           ctx=((r"解離症|脅迫症", "强迫症"),),
           note="鸣潮 2.6 医生对黑潮侵蚀症状的诊断「解离症」（官方剧情）。ASR/谷翻误作「强迫症」（#930）；"
                "走日语锚定，不裸键（强迫症是真实医学词）。"),
    Entity("忒修特", modes=("ja",), ja="テセウス",
           category="角色/鸣潮2.6庆典",
           ctx=((r"テセウス", "忒修斯"),),
           note="鸣潮 2.6 庆典 NPC 忒修特（官方剧情「告诉我和忒修特」）。谷翻作「忒修斯」（希腊神话 Theseus），"
                "走日语锚定；2026-10-30 #206。"),

    # ===== 2026-10-30 韩语直播片《이환 1.5 공식방송》（8194 cue，中文在上/韩语在下） =====
    #   官方依据：《异环》App Store 官方简介（海特洛市/异象/异象管理局/鉴定师/伊波恩）、
    #   17173/ali213 1.5 通稿（曳尔沐 Elyms / EXE / 明音凛 Akane Rin / 1.5「致电，空想迷数」）、
    #   百度百科「鉴定师」（Appraiser）、ntegame 攻略（海特洛/鉴定师/异象）。
    #   戒律：下列错形几乎全是**通用中文词**（评估师/售完/闪光/柚子/橙子/能力/异常），
    #   一律走韩语参考行锚定 ctx，绝不入裸键。
    Entity("鉴定师", modes=("ko",), ko="감정사",
           category="角色/异环",
           ctx=((r"감정사", "估价师"), (r"감정사", "评估师"),
                (r"감정사", "鉴定员"), (r"감정사", "鉴定人")),
           note="《异环》玩家主控「鉴定师」（Appraiser，官方 App Store 简介＋百度百科；"
                "韩语 감정사）。谷翻误作 估价师/评估师/鉴定员/鉴定人；本片 #1581–#2399 共 15 处。"),
    Entity("曳尔沐", modes=("ko",), ko="엘림",
           category="角色/异环1.5",
           ctx=((r"엘림", "Elim"), (r"엘림", "以琳"), (r"엘림", "以利姆"),
                (r"엘림", "埃琳"), (r"엘림", "艾琳")),
           note="异环 1.5 新 S 级角色「曳尔沐」（Elyms，17173/ali213 通稿；韩语 엘림）。"
                "谷翻误作 Elim/以琳/以利姆/埃琳/艾琳；本片 #1633–#2413 共 29 处。"
                "「艾琳」是常见人名，只走韩语锚定。"),
    Entity("EXE", modes=("ko",), ko="엑/엑세/엑셀",
           category="角色/异环1.5",
           ctx=((r"엑(?!스칼리버|수)", "Ek"), (r"엑(?!스칼리버|수)", "Excel"),
                (r"엑(?!스칼리버|수)", "Exega"), (r"엑(?!스칼리버|수)", "Exewa"),
                (r"엑(?!스칼리버|수)", "艾克森")),
           note="异环 1.5 新 S 级角色「EXE」（17173 通稿；韩语 엑）。谷翻误作 Ek/Excel/Exega/"
                "Exewa/艾克森；本片 #1633/#1647/#1944/#1974/#1982/#2023 等。"
                "⚠ 汉字「X」在片中亦指 EXE，但 X 亦出现在 UI/XL 等语境，不设裸键，逐条人工处理。"),
    Entity("海特洛", modes=("ko",), ko="해태로/헤테로",
           category="地名/异环",
           ctx=((r"해태로|헤테로", "海泰路"), (r"해태로|헤테로", "灰太路"),
                (r"해태로|헤테로", "海泰"), (r"해태로|헤테로", "Haitairo"),
                (r"해태로|헤테로", "Hetero"), (r"해태로|헤테로", "异质性")),
           note="《异环》主舞台「海特洛市」（Hethereau，官方 App Store 简介；韩语 해태로/헤테로）。"
                "谷翻误作 海泰路/灰太路/海泰/Haitairo/Hetero/异质性；本片 #1603–#2409。"
                "⚠ 2070「海泰物流中心」是跨 cue 断句，术语替换后需整行修正。"),
    Entity("克莱门学院", modes=("ko",), ko="클레멘트 아카데미",
           category="地点/异环",
           ctx=((r"클레멘트", "克莱门特学院"),),
           note="异环地点「克莱门学院」（Clement Academy；韩语 클레멘트 아카데미）。"
                "谷翻多一个「特」：克莱门特学院；本片 #1593。"),
    Entity("娜娜莉", modes=("ko",), ko="나나리",
           category="角色/异环",
           ctx=((r"나나리", "Nanari"), (r"나나리", "纳纳里"), (r"나나리", "娜娜里")),
           note="异环看板角色「娜娜莉」（Nanally；韩语 나나리）。谷翻误作 Nanari/纳纳里/娜娜里；"
                "本片 #1825/#2292/#6391/#6425/#6568/#8055。"),
    Entity("异象", modes=("ko",), ko="이상",
           category="术语/异环",
           ctx=((r"이상\s*(관련|과|이|을|의|리|순례|급|같은|판타지)", "异常"),
                (r"이상\s*(관련|과|이|을|의|리|순례|급|같은|판타지)", "李尚利")),
           note="《异环》核心设定「异象」（Anomaly，官方 App Store 简介）。谷翻按普通词译成「异常」"
                "或音译「李尚利」；「异常」是通用词，只收 이상+宾语/修饰语的语法组合做锚，"
                "不收裸键（이상하다「奇怪」不得命中）。本片 #1641/#1644/#1862 等。"),
    Entity("异能", modes=("ko",), ko="이능력",
           category="术语/异环",
           ctx=((r"이능력", "能力"),),
           note="《异环》异能设定（官方 App Store 简介「异能者」）。韩语 이능력；谷翻常省成「能力」。"
                "本片 #1786/#1931/#1944（#1929 的「异质性」由海特洛条目处理）。"),
    Entity("策划", modes=("ko",), ko="기획자",
           category="职位/异环直播",
           ctx=((r"기획자", "规划师"), (r"기획자", "计划者"), (r"기획자", "策划者")),
           note="异环官方前瞻节目主持头衔「策划」（기획자）。谷翻 规划师/计划者/策划者；"
                "本片 #1586/#1590/#1592。"),
    Entity("方斯", modes=("ko",), ko="폰즈/폰지",
           category="术语/异环",
           ctx=((r"폰즈|폰지", "庞氏"), (r"폰즈|폰지", "橙子"), (r"폰즈|폰지", "池塘")),
           note="《异环》货币「方斯」（Fons；官方社区文案「赚够方斯就收手」；韩语 폰즈）。"
                "谷翻误作 庞氏/橙子/池塘；「橙子」是通用词，只走韩语锚定。本片 #2150/#2430/#2432–#2445/#5742。"),
    Entity("优雅的腐败者", modes=("ko",), ko="우아한 부패자",
           category="异象/异环1.5",
           ctx=((r"우아한 부패자", "优雅腐败者"),),
           note="异环 1.5 新异象「优雅的腐败者」（韩语 우아한 부패자；官方简中名待确认，按韩语直译）。"
                "谷翻少「的」；本片 #1862/#1866/#2383。"),
    Entity("明日方舟", modes=("ko",), ko="명방/명일방주",
           category="作品/游戏",
           ctx=((r"명방|명일방주", "明房"), (r"명방|명일방주", "阿明芳"),
                (r"명방|명일방주", "明邦"), (r"명방|명일방주", "名室")),
           note="《明日方舟》（韩语 명일방주/명방）。谷翻误作 明房/阿明芳/明邦/名室；"
                "本片 #483/#484/#2551/#4402/#4623。"),
    Entity("绝区零", modes=("ko",), ko="젠존재/젠존지/젠존제/젠레스 존 제로",
           category="作品/游戏",
           ctx=((r"젠존", "禅宗"), (r"젠존", "善宗寺"), (r"젠존", "Zenjonje")),
           note="《绝区零》（Zenless Zone Zero；韩语 젠존재/젠존지/젠레스 존 제로）。"
                "谷翻误作 禅宗/善宗寺/Zenjonje；本片 #3278/#3373/#3443/#3713/#4166/#4473/#4493。"),
    Entity("星穹铁道", modes=("ko",), ko="스타레일",
           category="作品/游戏",
           ctx=((r"스타\s*레일", "Starrail"),),
           note="《崩坏：星穹铁道》（韩语 스타레일）。谷翻 Starrail；「星轨」已有既有 KO_CONTEXT 规则"
                "映射到「星穹铁道」。本片 #2670/#3007/#3009/#3051/#3712/#3718/#4531。"),
    Entity("原神", modes=("ko",), ko="원신",
           category="作品/游戏",
           ctx=((r"원신", "原神冲击"), (r"원신", "Genshin Impact")),
           note="《原神》（韩语 원신）。谷翻 原神冲击/Genshin Impact；本片 #3066/#3069/#4638。"),
    Entity("藿藿", modes=("ko",), ko="곽향",
           category="角色/星穹铁道",
           ctx=((r"곽향", "郭香"), (r"곽향", "夸扬"), (r"곽향", "夸赫阳"),
                (r"곽향", "夸香"), (r"곽향", "Kwakhyang"), (r"곽향", "Kwak Hyang")),
           note="星穹铁道角色「藿藿」（Huohuo；韩语 곽향）。谷翻误作 郭香/夸扬/夸赫阳/夸香/Kwakhyang；"
                "本片 #145–#4541 共 18 处。"),
    Entity("阮·梅", modes=("ko",), ko="완매",
           category="角色/星穹铁道",
           ctx=((r"완매", "已售完"), (r"완매", "已售罄"), (r"완매", "售完"),
                (r"완매", "售罄"), (r"완매", "卖完了"), (r"완매", "完卖")),
           note="星穹铁道角色「阮·梅」（Ruan Mei；官方写法带间隔号；韩语 완매）。"
                "谷翻按字面译成 售完/售罄/卖完了；这些是通用词，只走韩语锚定。本片 14 处。"),
    Entity("花火", modes=("ko",), ko="스파클",
           category="角色/星穹铁道",
           ctx=((r"스파클", "闪闪发光"), (r"스파클", "闪闪"), (r"스파클", "闪光"),
                (r"스파클", "火花")),
           note="星穹铁道角色「花火」（Sparkle；韩语 스파클）。谷翻误作 闪闪发光/闪闪/闪光/火花；"
                "「火花」「闪光」是通用词，只走韩语锚定。本片 #2770–#4541 共 8 处。"),
    Entity("耀嘉音", modes=("ko",), ko="아스트라",
           category="角色/绝区零",
           ctx=((r"아스트라", "阿斯特拉"), (r"아스트라", "Astra")),
           note="绝区零角色「耀嘉音」（Astra Yao；韩语 아스트라）。谷翻音译成 阿斯特拉/Astra；"
                "本片 #463–#5423 共 23 处（#463「阿斯特拉耀正」需整行修正）。"),
    Entity("柚叶", modes=("ko",), ko="유즈아/유즈/유자",
           category="角色/绝区零",
           ctx=((r"유즈아|유즈|유자", "柚子"), (r"유즈아|유즈|유자", "尤祖亚"),
                (r"유즈아|유즈|유자", "尤兹"), (r"유즈아|유즈|유자", "尤莎"),
                (r"유즈아|유즈|유자", "Yuzu")),
           note="绝区零角色「浮波柚叶」（Yuzuha；韩语 유즈아）。谷翻误作 柚子/尤祖亚/尤兹；"
                "「柚子」是水果名，只走韩语锚定。本片 #3291/#3302/#3308/#3342/#3349。"),
    Entity("露西", modes=("ko",), ko="루시아",
           category="角色/绝区零",
           ctx=((r"루시아", "露西亚"),),
           note="绝区零角色「露西」（Lucy；韩语 루시아）。谷翻写成 露西亚；本片 #3340/#3341/#3364/#3366。"),
    Entity("班尼特", modes=("ko",), ko="베넷",
           category="角色/原神",
           ctx=((r"베넷", "贝内特"), (r"베넷", "贝尼特")),
           note="原神角色「班尼特」（Bennett；韩语 베넷）。谷翻 贝内特/贝尼特；本片 #2505/#3123。"),
    Entity("枫原万叶", modes=("ko",), ko="카즈아",
           category="角色/原神",
           ctx=((r"카즈아", "卡祖亚"), (r"카즈아", "卡祖"), (r"카즈아", "Kazua"),
                (r"카즈아", "卡兹阿"), (r"카즈아", "风贺")),
           note="原神角色「枫原万叶」（Kazuha；韩语 카즈아，ASR 掉 하）。谷翻 卡祖亚/卡祖/Kazua；"
                "本片 #2561–#4635 共 12 处。"),
    Entity("知更鸟", modes=("ko",), ko="로빈",
           category="角色/星穹铁道",
           ctx=((r"로빈", "罗宾"),),
           note="星穹铁道角色「知更鸟」（Robin；韩语 로빈）。谷翻音译 罗宾；本片 #2911/#3017 等。"),

    # ===== 2026-10-30 r2 二次校准：跨游戏官方名与高频术语（韩语直播片） =====
    #   官方依据：妮姬官方名单（拉毗/小红帽/红莲/红莲：暗影/阿妮斯/塞壬）、
    #   崩坏：星穹铁道官方角色表（砂金/流萤/符玄/白露/杰帕德/灵砂/缇宝/万敌/遐蝶/风堇/大黑塔）、
    #   明日方舟（桃金娘）、赛马娘（北部玄驹）、边狱公司（堂吉诃德/奥提斯）。
    #   戒律：错形多为通用词（红木/黑莲/萤火虫/白鹭/领事/我的一天/风信子/黑色），一律韩语锚定 ctx。
    Entity("小红帽", modes=("ko",), ko="레드후드/레드우드/레두드",
           category="角色/妮姬",
           ctx=((r"레드후드|레드우드|레두드", "红木"), (r"레드후드|레드우드|레두드", "红帽"),
                (r"레드후드|레드우드|레두드", "红头罩"), (r"레드후드|레드우드|레두드", "Redud")),
           note="妮姬「小红帽」（Red Hood；韩语 레드후드/레드우드/레두드）。谷翻误作 红木/红帽/红头罩/Redud；"
                "2026-10-30 r2 #3786/#3804/#3949/#4097 等。"),
    Entity("拉毗", modes=("ko",), ko="라피",
           category="角色/妮姬",
           ctx=((r"라피", "拉皮"), (r"라피", "拉拉菲"), (r"라피", "拉菲")),
           note="妮姬「拉毗」（Rapi；韩语 라피）。谷翻误作 拉皮/拉拉菲/拉菲；"
                "「拉菲」是红酒名，只走韩语锚定。2026-10-30 r2 #3480/#3948/#4561。"),
    Entity("红莲", modes=("ko",), ko="홍련/흥년",
           category="角色/妮姬",
           ctx=((r"홍련|흥년", "兴莲"), (r"홍련|흥년", "香莲")),
           note="妮姬「红莲」（Scarlet/Hongryeon；韩语 홍련，ASR 常作 흥년）。谷翻误作 兴莲/香莲；"
                "2026-10-30 r2 #3869/#3914。"),
    Entity("红莲：暗影", modes=("ko",), ko="흑련/흑년",
           category="角色/妮姬",
           ctx=((r"흑련|흑년", "黑莲"),),
           note="妮姬「红莲：暗影」（Scarlet: Black Shadow；韩语 흑련/흑년）。谷翻误作 黑莲；"
                "2026-10-30 r2 #3929。"),
    Entity("阿妮斯", modes=("ko",), ko="아니스",
           category="角色/妮姬",
           ctx=((r"아니스", "安妮斯"), (r"아니스", "八角茴香")),
           note="妮姬「阿妮斯」（Anis；韩语 아니스）。谷翻误作 安妮斯/八角茴香；"
                "2026-10-30 r2 #3480/#3783/#4028。"),
    Entity("塞壬", modes=("ko",), ko="세이렌",
           category="角色/妮姬",
           ctx=((r"세이렌", "警报"), (r"세이렌", "警笛"), (r"세이렌", "海妖")),
           note="妮姬「塞壬」（Siren；韩语 세이렌）。谷翻误作 警报/警笛/海妖；"
                "2026-10-30 r2 #3778/#3869/#4090。"),
    Entity("砂金", modes=("ko",), ko="어벤추린/어벤/출린",
           category="角色/星穹铁道",
           ctx=((r"어벤추린|어벤|출린", "东陵"), (r"어벤추린|어벤|출린", "阿文图"),
                (r"어벤추린|어벤|출린", "艾文"), (r"어벤추린|어벤|출린", "楚林"),
                (r"어벤추린|어벤|출린", "冒险")),
           note="星穹铁道「砂金」（Aventurine；韩语 어벤추린，ASR 常作 어벤/출린）。谷翻误作 东陵/阿文图/艾文/楚林/冒险；"
                "2026-10-30 r2 #2788/#2895/#2953/#2954。"),
    Entity("流萤", modes=("ko",), ko="반디",
           category="角色/星穹铁道",
           ctx=((r"반디", "萤火虫"), (r"반디", "班迪"), (r"반디", "Bandi")),
           note="星穹铁道「流萤」（Firefly；韩语 반디）。谷翻误作 萤火虫/班迪/Bandi；"
                "2026-10-30 r2 #2824/#2826。"),
    Entity("符玄", modes=("ko",), ko="부연",
           category="角色/星穹铁道",
           ctx=((r"부연", "扶颜"), (r"부연", "扶余"), (r"부연", "补充")),
           note="星穹铁道「符玄」（Fu Xuan；韩语 부연）。谷翻误作 扶颜/扶余/补充；"
                "「补充」是通用词，只走韩语锚定。2026-10-30 r2 #2721/#2786。"),
    Entity("白露", modes=("ko",), ko="백로",
           category="角色/星穹铁道",
           ctx=((r"백로", "白鹭"),),
           note="星穹铁道「白露」（Bailu；韩语 백로）。谷翻误作 白鹭；2026-10-30 r2 #2740。"),
    Entity("杰帕德", modes=("ko",), ko="개파드",
           category="角色/星穹铁道",
           ctx=((r"개파드", "加法德"), (r"개파드", "盖帕德")),
           note="星穹铁道「杰帕德」（Gepard；韩语 개파드）。谷翻误作 加法德/盖帕德；2026-10-30 r2 #2740。"),
    Entity("灵砂", modes=("ko",), ko="영사",
           category="角色/星穹铁道",
           ctx=((r"영사", "领事"), (r"영사", "英泰")),
           note="星穹铁道「灵砂」（Lingsha；韩语 영사）。谷翻误作 领事/英泰；"
                "「领事」是通用词，只走韩语锚定。2026-10-30 r2 #2924/#2952/#3022。"),
    Entity("缇宝", modes=("ko",), ko="트립",
           category="角色/星穹铁道",
           ctx=((r"트립", "Trip"), (r"트립", "行程"), (r"트립", "特里维")),
           note="星穹铁道「缇宝」（Tribbie；韩语 트립）。谷翻误作 Trip/行程/特里维；"
                "2026-10-30 r2 #2935/#2942/#2992。"),
    Entity("万敌", modes=("ko",), ko="마이데이",
           category="角色/星穹铁道",
           ctx=((r"마이데이", "我的一天"),),
           note="星穹铁道「万敌」（Mydei；韩语 마이데이）。谷翻直译「我的一天」；2026-10-30 r2 #2946/#2950。"),
    Entity("遐蝶", modes=("ko",), ko="카스토리",
           category="角色/星穹铁道",
           ctx=((r"카스토리", "卡斯托里"), (r"카스토리", "卡斯托里斯")),
           note="星穹铁道「遐蝶」（Castorice；韩语 카스토리）。谷翻音译 卡斯托里/卡斯托里斯；2026-10-30 r2 #2950。"),
    Entity("风堇", modes=("ko",), ko="히아킨",
           category="角色/星穹铁道",
           ctx=((r"히아킨", "风信子"), (r"히아킨", "哈肯")),
           note="星穹铁道「风堇」（Hyacine；韩语 히아킨）。谷翻误作 风信子/哈肯；"
                "「风信子」是花名，只走韩语锚定。2026-10-30 r2 #3023/#3025。"),
    Entity("大黑塔", modes=("ko",), ko="더헤르타",
           category="角色/星穹铁道",
           ctx=((r"더헤르타", "Herta"),),
           note="星穹铁道「大黑塔」（Herta 的大黑塔形态；韩语 더헤르타）。谷翻留英文 Herta；"
                "2026-10-30 r2 #2948。"),
    Entity("桃金娘", modes=("ko",), ko="머틀",
           category="角色/明日方舟",
           ctx=((r"머틀", "默特尔"), (r"머틀", "香桃木")),
           note="明日方舟「桃金娘」（Myrtle；韩语 머틀）。谷翻误作 默特尔/香桃木；2026-10-30 r2 #2552。"),
    Entity("北部玄驹", modes=("ko",), ko="키타산 블랙/타산 블랙/기타산 블랙",
           category="角色/赛马娘",
           ctx=((r"키타산|타산|기타산", "吉他的黑色"), (r"키타산|타산|기타산", "黑人"),
                (r"키타산|타산|기타산", "黑色"), (r"키타산|타산|기타산", "Kitasan Black")),
           note="赛马娘「北部玄驹」（Kitasan Black；韩语 키타산 블랙）。谷翻误作 吉他的黑色/黑人/黑色/Kitasan Black；"
                "「黑色」是通用词，只走韩语锚定。2026-10-30 r2 #4950/#5015/#5187。"),
    Entity("堂吉诃德", modes=("ko",), ko="동키",
           category="角色/边狱公司",
           ctx=((r"동키", "驴子"),),
           note="边狱公司囚人「堂吉诃德」（Don Quixote；韩语 동키）。谷翻按字面作「驴子」；2026-10-30 r2 #884。"),
    Entity("奥提斯", modes=("ko",), ko="오티스",
           category="角色/边狱公司",
           ctx=((r"오티스", "奥蒂斯"),),
           note="边狱公司囚人「奥提斯」（Outis；韩语 오티스）。谷翻误作 奥蒂斯；2026-10-30 r2 #885。"),
    Entity("蔚蓝档案", modes=("ko",), ko="블루 아카이브",
           category="作品/游戏",
           ctx=((r"블루\s*아카이브", "蓝色档案"), (r"블루\s*아카이브", "蓝档案")),
           note="《蔚蓝档案》（Blue Archive；韩语 블루 아카이브）。谷翻误作 蓝色档案/蓝档案；2026-10-30 r2 #578。"),
    Entity("边狱公司", modes=("ko",), ko="림버스 컴퍼니",
           category="作品/游戏",
           ctx=((r"림버스\s*컴퍼니", "林布斯公司"), (r"림버스\s*컴퍼니", "Limbus Company")),
           note="《边狱公司》（Limbus Company；韩语 림버스 컴퍼니）。谷翻误作 林布斯公司/Limbus Company；"
                "2026-10-30 r2 #1295/#1464。"),
    Entity("重返未来：1999", modes=("ko",), ko="리버스",
           category="作品/游戏",
           ctx=((r"리버스", "逆向"), (r"리버스", "里弗斯"), (r"리버스", "这辆巴士")),
           note="《重返未来：1999》（Reverse: 1999；韩语 리버스）。谷翻误作 逆向/里弗斯/这辆巴士；"
                "2026-10-30 r2 #4727/#4729/#4731。"),
    Entity("崩坏3", modes=("ko",), ko="붕괴드",
           category="作品/游戏",
           ctx=((r"붕괴드", "折叠代码"),),
           note="《崩坏3》（韩语 붕괴드）。谷翻误作「折叠代码」；2026-10-30 r2 #4669。"),
    Entity("星铁", modes=("ko",), ko="스타레",
           category="作品/游戏",
           ctx=((r"스타레", "凝视"),),
           note="《崩坏：星穹铁道》简称「星铁」（韩语 스타레）。谷翻误作「凝视」；2026-10-30 r2 #4564。"),
    Entity("斯卡哈", modes=("ko",), ko="스카사",
           category="角色/FGO",
           ctx=((r"스카사", "斯卡萨"),),
           note="FGO「斯卡哈」（Scáthach；韩语 스카사）。谷翻误作 斯卡萨；2026-10-30 r2 #5066/#5117。"),
    Entity("高扬斯卡娅", modes=("ko",), ko="코얀 스칼",
           category="角色/FGO",
           ctx=((r"코얀\s*스칼", "科扬斯卡尔"),),
           note="FGO「高扬斯卡娅」（Koyanskaya；韩语 코얀 스칼）。谷翻音译错位 科扬斯卡尔；2026-10-30 r2 #5139。"),
    Entity("赛马娘", modes=("ko",), ko="말딸",
           category="作品/游戏",
           ctx=((r"말딸", "月底"),),
           note="《赛马娘》（韩语 말딸）。谷翻误作「月底」；2026-10-30 r2 #5031。"),
    Entity("宝具", modes=("ko",), ko="필사기",
           category="术语/FGO",
           ctx=((r"필사기", "转录机"), (r"필사기", "转录器"), (r"필사기", "特杀")),
           note="FGO「宝具」（필사기）。谷翻误作 转录机/转录器/特杀；2026-10-30 r2 #5053/#5054/#5093。"),
    Entity("干员", modes=("ko",), ko="오퍼",
           category="术语/明日方舟",
           ctx=((r"오퍼", "优惠"), (r"오퍼", "培训机会")),
           note="明日方舟「干员」（오퍼）。谷翻误作 优惠/培训机会；2026-10-30 r2 #5195/#5196。"),
    Entity("关服", modes=("ko",), ko="섭종",
           category="术语/通用",
           ctx=((r"섭종(?!사)", "Seopjong"), (r"섭종(?!사)", "涉宗寺")),
           note="「关服/停服」（韩语 섭종）。谷翻留罗马字 Seopjong 或音译涉宗寺；2026-10-30 r2 #2484/#2487/#4131。"),
    Entity("复刻", modes=("ko",), ko="복각",
           category="术语/通用",
           ctx=((r"복각", "重印"), (r"복각", "转载"), (r"복각", "福盖尔")),
           note="抽卡「复刻」（韩语 복각）。谷翻误作 重印/转载/福盖尔；2026-10-30 r2 #2024/#2624/#4512。"),
    Entity("常驻", modes=("ko",), ko="통상",
           category="术语/通用",
           ctx=((r"통상", "这很正常"),),
           note="抽卡「常驻」（韩语 통상）。谷翻误作「这很正常」；2026-10-30 r2 #3759。"),
    Entity("保底", modes=("ko",), ko="천장",
           category="术语/通用",
           ctx=((r"천장", "天花板"), (r"천장", "吸顶")),
           note="抽卡「保底/天井」（韩语 천장）。谷翻误作 天花板/吸顶；2026-10-30 r2 #5197/#5754。"),
    Entity("0 档", modes=("ko",), ko="영티어",
           category="术语/通用",
           ctx=((r"영티어", "年轻阶层"), (r"영티어", "少年组"), (r"영티어", "青年队")),
           note="强度榜「0 档/T0」（韩语 영티어 = 0티어）。谷翻误作 年轻阶层/少年组/青年队；"
                "2026-10-30 r2 #5079/#5111/#5137。"),
    Entity("终末侠", modes=("ko",), ko="종말맨",
           category="主播/昵称",
           ctx=((r"종말맨", "末日人"), (r"종말맨", "天启人"), (r"종말맨", "末世侠")),
           note="主播圈昵称「终末侠」（韩语 종말맨）。谷翻误作 末日人/天启人/末世侠；"
                "2026-10-30 r2 #4324/#4408/#4431/#5210。"),
    Entity("Raven", modes=("ko",), ko="레이븐",
           category="角色/妮姬",
           ctx=((r"레이븐", "乌鸦"),),
           note="妮姬角色「Raven」（韩语 레이븐）。谷翻按字面作「乌鸦」；2026-10-30 r2 #6033/#6536。"),
    Entity("保时捷", modes=("ko",), ko="뽀르쉐/보르쉐/포르스",
           category="术语/通用",
           ctx=((r"뽀르쉐|보르쉐|포르스", "罗宋汤"), (r"뽀르쉐|보르쉐|포르스", "眼影"),
                (r"뽀르쉐|보르쉐|포르스", "福斯")),
           note="《异环》载具「保时捷」（韩语 뽀르쉐/보르쉐/포르스）。谷翻误作 罗宋汤/眼影/福斯；"
                "2026-10-30 r2 #5493/#5614/#5734/#5749。"),
    Entity("立绘", modes=("ko",), ko="일러",
           category="术语/通用",
           ctx=((r"일러", "早点"),),
           note="游戏术语「立绘」（韩语 일러）。谷翻误作「早点」；2026-10-30 r2 #5647。"),
    Entity("Smilegate 公司", modes=("ko",), ko="스마게",
           category="公司/厂商",
           ctx=((r"스마게", "聪明"), (r"스마게", "苏马加")),
           note="Smilegate（韩语 스마게）。谷翻误作 聪明/苏马加；2026-10-30 r2 #4865/#4868。"),
    Entity("正统", modes=("ko",), ko="정배",
           category="术语/通用",
           ctx=((r"정배", "正裴"),),
           note="「正统打法」简称「正统」（韩语 정배）。谷翻误作人名「正裴」；2026-10-30 r2 #5769。"),
    Entity("停车", modes=("ko",), ko="주차",
           category="术语/通用",
           ctx=((r"주차", "公园"),),
           note="「停车」（韩语 주차）。谷翻误作「公园」；2026-10-30 r2 #5830。"),
    Entity("承认", modes=("ko",), ko="인종/인정",
           category="术语/通用",
           ctx=((r"인종|인정", "种族"),),
           note="「承认/认了」（韩语 인정，ASR 作 인종）。谷翻误作「种族」；2026-10-30 r2 #6521。"),
    # =========================================================
    # 2026-11-01 r2 沉淀：《#鳴潮 引換コード配布》世界観PV / 鎖暝PV 直播
    #   （日本 VTuber Manmaru，2391 cue，日语 ASR + 微软翻译中文，--ja 模式）
    #   逐句二次校准发现：下列术语在表内**只有 bi/react 行、或根本没有实体**，
    #   故 --ja 下一律不产出规则（同一 canonical 按 modes 分行是本仓约定）。
    #   含通用中文词的形一律走 ctx 日语行锚定，禁入裸键。
    #   官方依据：鸣潮日服官网（「共鳴者の仲間たちと「悲鳴」を乗り越えていく」⇒ 悲鳴=悲鸣）、
    #   官博/TapTap 官方帖（全称「深空联合：星炬学院」⇒ 日服 ASR スタート学園）、
    #   百度百科「锁暝 / 心月狐 / 岁主 / 新联邦 / 阿布」、译名对照表 Rinascita=黎那汐塔。
    # =========================================================
    Entity("悲鸣", modes=("ja",), ja="悲鳴", category="术语/鸣潮世界观",
           ctx=((r"悲鳴", "尖叫声"), (r"悲鳴", "呐喊"),
                (r"悲鳴観測", "尖叫观察"), (r"悲鳴", "尖叫")),
           note="鸣潮世界观词「悲鸣」，日服官网原文即「悲鳴」；谷翻按日语普通词'尖叫'直译。"
                "r2 cue 873/874/875/880/881/892/895/906/907/909/1265/1347/1379/1944/1985。"
                "戒律：尖叫/呐喊 是正常中文词，只走锚定，且长形在前（ctx 按列表顺序执行）。"),
    Entity("实例", modes=("ja",), en="Instance", ja="インスタンス", category="术语/鸣潮4.0",
           ctx=((r"インスタンス", "第三次审理"), (r"インスタンス", "第三次"),
                (r"インスタンス", "法庭"), (r"インスタンス", "例子"),
                (r"インスタンス", "第一次"), (r"インスタンス", "第二次")),
           note="4.0「融合漂泊者/多个漂泊者」讨论里的 インスタンス=实例（第1/第2/第3 インスタンス）。"
                "谷翻按字面给 例子/法庭/审理/第N次。r2 cue 1087/1103/1209/1240/1249/1283/1442。"
                "戒律：例子/法庭/序数词全是通用词，禁入裸键。"),
    Entity("想象与心灵的边界", modes=("ja",), category="PV台词/鸣潮",
           ctx=((r"想像と心の", "想象与心灵教会"), (r"想像と心の", "想象与心灵的教堂"),
                (r"想像と心の", "想象力与心灵")),
           note="世界观PV 旁白「想像と心の境界で僕は取引を守ってるだろう」。境界/教会 同音"
                "きょうかい，ASR 多数听成 教会⇒谷翻'教堂/教会'；cue 1727 同行 ASR 作 境界，"
                "即片内自证。r2 cue 597/1841/1851/1852/1855/1861/1863/1885/2009。"),
    Entity("黑海岸", modes=("ja",), en="Black Shores", ja="ブラックショア", category="组织/鸣潮",
           ctx=((r"ブラック", "黑色淋浴"), (r"ブラック", "黑名单股份"), (r"ブラック", "布莱克郡"),
                (r"ブラック", "布莱克肖尔"), (r"ブラック", "黑股票"), (r"ブラック", "黑西亚"),
                (r"ブラック", "黑谢亚"), (r"ブラック", "黑查尔"), (r"ブラック", "黑共享"),
                (r"ブラック", "BlackShare"), (r"ブラック", "黑色秀"), (r"ブラック", "《黑人》"),
                (r"ブラックシア|ブラックシュア", "布莱克谢")),
           note="官方组织=黑海岸。ja.py 已有裸键「黑岸→黑海岸」与 ブラックシア/シュア 的"
                "「布莱克谢亚集团→黑海岸组」⇒ 本条**只补 r2 新出现的拆译形**"
                "（シャワー淋浴/シェア共享/ストック股票 被按字面直译），cue 1028/1064/1403/"
                "1405/1533/1616/1617/1641/1643/1707/1708/2026/2046/2049/2093/2098。"
                "⚠ 不收裸「布莱克谢」——会把已正确的「布莱克谢亚集团」咬成'黑海岸亚集团'"
                "（扁平表先于 ctx，ja.py:42 笛卡尔前科）；ブラックホール=黑洞（cue 1190/1191/"
                "1258/1259 是黑洞，勿并入本条）。"),
    Entity("岁主", modes=("ja",), ja="サイシャ", category="术语/鸣潮世界观",
           ctx=((r"最主|最種", "赛兽"),),
           note="梦州岁主（心月狐=首位可玩岁主，百度百科）。ASR 作 最主/最種（さいしゅ）"
                "⇒谷翻按字面给'赛兽/主要是'。r2 cue 148/2198。"
                "戒律：'主要是' 是超常用串，绝不入表；裸「最主」⊂「最主要」也只走锚定。"),
    Entity("星炬学院", modes=("ja",), en="Startorch Academy", ja="スタート学園",
           category="地点/学院·鸣潮",
           ctx=((r"スタート学園", "Start Academy"),),
           note="官方中文=星炬学院（英 Startorch Academy，见本文件 bi/react 行）。"
                "日服 ASR 把 Startorch 听成 スタート(Start)⇒谷翻直译 'Start Academy'。"
                "r2 cue 522/524。依据：官博/TapTap 官方帖「深空联合：星炬学院」。"),
    Entity("新联邦", modes=("ja",), en="New Federation", ja="ネオユニオン", category="地区/鸣潮4.0",
           ctx=((r"ネオンユニ", "霓虹大学"), (r"ネオユニ", "新大学")),
           note="4.0 新地区=新联邦（bi/react 行已有）。ASR 截短成 ネオユニ/ネオンユニ，"
                "谷翻给 新大学/霓虹大学。r2 cue 1577/2098。"),
    Entity("陆老师", modes=("ja",), ja="りく先生", category="角色/鸣潮4.0",
           ctx=((r"龍ク先生", "龙九老师"), (r"でりク先生", "Deriku博士"),
                (r"緑先生", "绿小姐"), (r"り?ク先生", "琉久")),
           note="暗影中队（Lux Lunae）的陆·赫斯，日语带先生敬称⇒中文按片内既成写法统一"
                "「陆老师」（cue 734 原文已是陆老师）。ASR 变体 でりク/龍ク/緑 ⇒ 谷翻给 "
                "Deriku博士/龙九老师/绿小姐/琉久。r2 cue 513/729/731/2193。"),
    Entity("Manmaru", modes=("ja",), ja="まんまる", category="作者/VTuber",
           variants=("金丸", "真丸"),
           note="主播自介「月から来た季節を司る青い鬼神 まんまる」；ASR 听成 こんまる/ままる"
                "⇒谷翻给 金丸/真丸/丸。r2 cue 3/4/5/7。⚠ 中文侧不能写假名「まんまる」——"
                "首中文行一旦含假名会被 _split_cue_text 判成参考行，双语版式断言直接失败（本次踩过），"
                "故 canonical 取频道自述罗马字 Manmaru；单字「丸」风险过大，只逐 cue 处理不入表。"
                "另：形容詞 まんまる(圆润) 不是人名（cue 2289 属误命中，勿改）。"),
    Entity("阿布", modes=("ja",), en="Abby", ja="アブ", category="角色/鸣潮3.7",
           ctx=((r"アブ", "木贼"),),
           note="3.7 角色阿布（Abby，本文件 bi 行已有）。アブ 被谷翻按日语'虻/木贼'直译成 "
                "马蝇/木贼。r2 cue 1348。"),
    Entity("阿列夫一", modes=("ja",), en="ALF1", ja="アレフ1", category="敌人/鸣式",
           ctx=((r"アレフ1", "Aleph 1"), (r"アレフ1", "阿勒夫 1"), (r"アルフ1", "Alf 1")),
           note="鸣式 ALF1=阿列夫一（bi 行已有）。谷翻留拉丁 Aleph 1/Alf 1 或另音译 阿勒夫 1。"
                "r2 cue 974/1185/1186。"),
    Entity("爱弥斯", modes=("ja",), en="Aemeath", ja="エイメス", category="角色/鸣潮",
           ctx=((r"エニメス", "Enimes"),),
           note="官方中文=爱弥斯。ASR 作 エニメス⇒谷翻留拉丁 Enimes。r2 cue 2080。"),
    Entity("拉海洛", modes=("ja",), en="Lahai-Roi", ja="ラハイロイ", category="地区/鸣潮3.x",
           ctx=((r"ラハ色イ", "拉哈色"),),
           note="3.0 地区=拉海洛（Lahai-Roi）。ASR 拆字 ラハ色イ⇒谷翻给 拉哈色。r2 cue 976。"),
    Entity("隧者", modes=("ja",), en="Exostrider", ja="エクソストライダー", category="术语/鸣潮",
           ctx=((r"エクソス?トライダー", "外骨骼游者"), (r"エクサス?トライダー", "Exustrider"),
                (r"クソストライダー", "该死的游侠"), (r"ストライダー", "外骨骼行者"),
                (r"ストライダー", "游侠")),
           note="「外骨骼行者」等形只登记在 bi 行的 variants，故 --ja 下不产出⇒本行补 ja 锚定。"
                "印证'三条产出路径'教训：子词直译(Exo=外骨骼 + strider=行者)最常见却最易漏。"
                "r2 cue 587/672/1455/1484/1999。"),
    Entity("伤痕", modes=("ja",), en="Scar", ja="スカー", category="角色/鸣潮残星会",
           ctx=((r"スカー", "疤痕"),),
           note="残星会会监 Scar 官方中文=伤痕（2026-10-30 已定）。ASR スカー⇒谷翻按字面'疤痕'。"
                "r2 cue 1568。"),
    Entity("世界观PV", modes=("ja",), category="PV类型/鸣潮",
           ctx=((r"世界観PV", "世界设定的PV"), (r"世界観PV", "设定世界的PV"),
                (r"世界観PV", "世界设定PV"), (r"世界観PV", "世界PV"),
                (r"世界観", "世界虚拟")),
           note="官方宣传物料名=世界观PV（标题与 cue 13/189 同行即 世界観PV）。谷翻拆成 "
                "世界设定/设定世界/世界PV，cue 15 更把 観 误作'虚拟'。r2 cue 13/21/83/424/546/548。"),
    Entity("心", modes=("ja",), ja="シン", category="角色/鸣潮3.7",
           ctx=((r"シ様", "师父"),),
           note="心月狐自称「心」、梦州岁主（官方演示「共鸣者『心』」/百度百科）。ASR 的 シ様 被"
                "谷翻按日语「師匠」误给「师父」。r2 cue 219/459/645/1585/2221。"
                "单字 canonical 只作替换目标、不参与匹配，故不入扁平表。"),
    Entity("阿布拉克萨斯", modes=("ja",), en="Abraxas", ja="アブラクサス", category="术语/鸣潮",
           ctx=((r"アブラクサス", "Abraxas"),),
           note="片内两形并存：cue 898 已作「阿布拉克萨斯」、1364 留拉丁 Abraxas ⇒ 取低频异形。"
                "官方中文=阿布拉克萨斯。r2 cue 1364。"),
    Entity("纯白之塔", modes=("ja",), en="White Tower", ja="純白の塔", category="意象/鸣潮4.0",
           ctx=((r"純白[なぬ]?の塔", "纯白塔"), (r"純白[なぬ]?の塔", "纯白色的塔")),
           note="4.0 世界观意象，片内 纯白塔/纯白之塔/纯白色的塔 三形并存（cue 835/1816/1843/"
                "1860）⇒ 归多数形。r2 cue 1816。"),
    Entity("章鱼", modes=("ja",), ja="ダコ", category="意象/鸣潮PV",
           ctx=((r"ダ[コ子]", "警察"), (r"ダ[コ子]", "达科"), (r"ダ[コ子]", "奥科"),
                (r"ダ[コ子]", "多子"), (r"ダ[コ子]", "Nedako")),
           note="世界观PV 旁白与解说里的 ダコ（锁暝的章鱼意象，cue 142「ダコは根を借り暗き場所に"
                "身を隠す」/cue 299「サめちゃんとね、ダコのこのね、密接な」）。谷翻两条错路：按发音"
                "抓 达科/奥科/多子/Nedako，按「逮捕」联想抓成「警察」（cue 296）。"
                "戒律：警察/达科 是普通词，只走 ダコ 锚定；r2 cue 142/177/213/245/277/288/296/351。"),
    Entity("时雨", modes=("ja",), ja="しぐれ", category="曲目/鸣潮",
           ctx=((r"しぐれ", "时车"), (r"しぐれ", "时香")),
           note="片内しぐれにて 多指曲目/PV 名『时雨』（cue 434/437/446/535 已成「时雨」），"
                "cue 440 被给成「时车」⇒ 取低频异形归一。cue 53「しぐりかちゃん」是歌手"
                "异世界情緒相关，不并入本条（存疑）。r2 cue 440。"),
    Entity("实机预告", modes=("ja",), category="PV类型/鸣潮",
           ctx=((r"実践トレーラー", "实用预告片"),),
           note="実践トレーラー=实机预告（谷翻按 practical 直译成'实用预告片'）。r2 cue 433。"),
    Entity("会长", modes=("ja",), ja="組織長", category="职衔/鸣潮",
           ctx=((r"組織長", "组织负责人"), (r"組織長", "组织首领"), (r"組織長", "老板"),
                (r"組織長", "组织领导者"),
                (r"組式長", "组长"), (r"庁が", "该机构"), (r"長が", "局长")),
           note="本片讨论的黑海岸会长（ja.py 既有 組織長→会长 裸键）。ASR 截短/换字 ⇒ 谷翻给 "
                "组织首领/老板/组长/该机构/局长。r2 cue 410/685/1154/1163/1654/1657/1662/1681/"
                "2074/2183/2188/2208/2240。戒律：老板/组长/局长 都是通用词，只走锚定。"),
    # 2026-11-01《How Did You Join Arknights or Endfield?》（英文原声+微软翻译，3700 cue）
    #   此前仓库无「鹰角网络」canonical 实体（只有 Entity("海猫", category="作者/鹰角网络")），
    #   导致 Hyper/海珀格里/hyperf 三个 ASR 形态无处归口（本片 #1342/#1347/#2069/#2367/#2500/#1655）。
    #   只挂 endobi：ENDFIELD_BI_TERMS 既有 Hyper Griff/HyperGriff/Hypergryph→鹰角网络，本条补齐同源异形；
    #   刻意不挂 ak —— AK_TERMS 里 Hypergryph→「鹰角」（短形式），改它会牵动其它方舟片源的 ak 通路输出。
    #   裸 Hyper 是通用前缀（hyper grave/hypermonetized），必须锚定，禁作裸键。
    #   刻意不写 en="Hypergryph"：Hypergryph→鹰角网络 已在 ENDFIELD_BI_TERMS:1029 登记，
    #   而另一实体把 Hypergryph 归到「鹰角」（ak 通路短形式）——再投影一次 kb-lint 报变体冲突。
    Entity("鹰角网络", modes=("endobi",), category="公司/终末地",
           variants=("海珀格里", "hyperf"),
           ctx=((r"\bhyper\b(?!\s*(?:grave|monetiz))", "Hyper"),),
           note="鹰角网络（Hypergryph）。微软翻译把裸 Hyper 原样留在中文行；"
                "海珀格里/hyperf 是 ASR 音译。cue 1342/1347/1655/2069/2367/2500。"),
    # --- 2026-11-02 《Music Listening Stream! HALLOWEEN EDITION》三次校准（MarcoMeatball，3376 cue）---
    # 依据逐条见 _doc.py 同日 changelog 与片源目录 verify_terms.md；无官方简中的一律 note 标注"保留原语言"。
    Entity("静谧田园",
           modes=("bi",),
           en="Village in the Shade",
           category="作品/游戏",
           variants=("荫村", "阴影村庄"),
           note="NIS America 2026-07-29 恐怖农场模拟。Steam 简中商店页 app/3934250「name: 静谧田园」。"
                "谷翻按字面直译成《荫村》；片源 cue 446/447/2941/2942/3003/3040/3065。"),
    Entity("夜回",
           modes=("bi",),
           en="Yomawari",
           category="作品/游戏",
           variants=("Yonowari", "夜廻"),
           note="Nippon Ichi Software 的恐怖系列。官方简中文案用字「夜回」（Steam 简中页「由『夜回』系列制作团队打造」，"
                "三作商店名「夜回三」）。Yonowari 是 ASR 形。cue 3005。"),
    Entity("魔兽世界：无限",
           modes=("bi",),
           en="World of Warcraft: Forever",
           category="作品/游戏",
           variants=("WoW Forever", "Wow Forever", "W forever"),
           note="BlizzCon 2026 公布的暴雪**正式产品（不是私服）**，国际服 11-04、国服 11-05。"
                "官方简体形「《魔兽世界》：" + chr(34) + "无限" + chr(34) + "」见 wow.blizzard.cn/news/20261013/43836_1316404.html；"
                "媒体另作《永恒》属非官方。本片 16 处/9 cue。"),
    Entity("银海之天舟",
           modes=("bi",),
           en="Evercold",
           category="作品/资料片",
           variants=("至冷", "极冷", "常冷"),
           note="《最终幻想14》8.0 资料片。盛趣官方专题站 actff1.web.sdo.com/project/20260425evercold；"
                "官方预告文案「8.0版本资料片" + chr(34) + "银海之天舟（Evercold）" + chr(34) + "」。"
                "主播口播 1 月上线，实际已延期至 2027-02-23（口播事实照原样译，不改）。"),
    Entity("克拉苏",
           modes=("bi",),
           en="The Krasue",
           category="作品/角色",
           variants=("Krasue",),
           note="《黎明杀机》章节《邪恶恩典》(Sinister Grace) 的泰国飞头鬼杀手，官方简体「克拉苏」"
                "（Steam 简中页 app/4019590「双重形态的恐怖杀手" + chr(34) + "克拉苏" + chr(34) + "」，Epic/Xbox zh-CN 同）。"
                "The Krauss 是 ASR 形，不是另一个名字。cue 2451/2476。"),
    Entity("Dragonsong",
           modes=("bi",),
           en="Dragonsong",
           category="作品/曲目",
           variants=("Dragon Song", "龙歌"),
           note="《最终幻想14》3.0 苍穹之禁城主题曲。国服客户端形《Dragonsong　-千年龙诗-》（**英文主标题保留、连写**），"
                "「龙歌」是谷翻意译。本段演唱者是《光与影：33号远征队》作曲兼演唱 Alice Duport-Percier；"
                "主播说的乐团名 Hollow Nest Orchestra 查无对应（FFXIV 官方演出品牌只有 THE PRIMALS / Eorzean Symphony / Distant Worlds），判 ASR。"),
    Entity("Hortus Regis Alti",
           modes=("bi",),
           en="Hortus Regis Alti",
           category="作品/曲目",
           variants=("Horus Stes Alti",),
           note="《皇牌空战8：希孚之翼》曲目（Lindsey Stirling 演奏），拉丁语意为" + chr(34) + "高王之园" + chr(34) +
                "。无官方简中曲名 ⇒ 保留拉丁。片内 #1540 的 Ros Grease 疑为同一曲名的 Regis Alti 误听，未确证。"),
    Entity("米斯蒂娅·萝蕾拉",
           modes=("bi",),
           en="Mystia Lorelei",
           category="作品/角色",
           variants=("Mistia",),
           note="东方 Project 角色，官方简体中文见设定集《东方Project人物名鉴 宵暗篇》（天闻角川出品）目录"
                "「019 米斯蒂娅·萝蕾拉」。东方游戏本体（红魔乡等）无官方简中。cue 3092。"),
    Entity("维鲁德拉",
           modes=("bi",),
           en="Veldora",
           category="作品/角色",
           variants=("维尔德拉", "Vdora"),
           note="《关于我转生变成史莱姆这档事》暴风龙。正版简体作「维鲁德拉」（B站番剧声优表 + 百科主词条"
                "「维鲁德拉·特恩佩斯特」，别名才作维尔德拉）。Vora/Dora 只是 Veldora 的 ASR 断词，不作独立条目。cue 1301-1303。"),
    Entity("魔物娘的同居日常",
           modes=("bi",),
           en="Monster Musume",
           category="作品/动画",
           variants=("Monster Musu", "怪物穆苏"),
           note="モンスター娘のいる日常；官网域名 monmusu.tv 即" + chr(34) + "MonMusu" + chr(34) + "，正是 ASR 的 Musu 来源。"
                "大陆无正版引进 ⇒ 此为**通用简体名而非官方简中**，用作检索锚点。cue 237。"),
    Entity("吃豆人 吃遍世界",
           modes=("bi",),
           en="PAC-MAN WORLD Re-PAC",
           category="作品/游戏",
           variants=("吃豆人世界", "Pac-Man World Repack"),
           note="万代南梦宫官方简中游戏名（bandainamcoent.asia 公告 + Steam app/1859470 字幕简中）；"
                "冒险舞台官方简中作「幽灵之岛」，但关卡/曲目名（Ghostly Garden、Haunted Boardwalk）无官中 ⇒ 保留英文。"
                "续作官方简中《吃豆人 吃遍世界2》。cue 436/437/1727/1836。"),
    Entity("米歇尔",
           modes=("bi",),
           en="Michaela",
           category="作品/角色",
           variants=("米凯拉",),
           note="《地下城与勇士》第十使徒，官方简体「米歇尔」（外文名即 Michaela/ミカエラ；dnf.qq.com 官方前瞻"
                "「梅尔文·米歇尔攻坚战」）。同段另三个官方简体：大天使米迦勒、第六使徒狄瑞吉（瘟疫）、太初神明雷米迪奥斯。"
                "⚠ 「米凯拉」是他作同名角色的通行译形，本条只对 DNF 片源成立，遇到别的 Michaela 需人工裁决。cue 603-625/670/707/721。"),
    Entity("Final Fantasy Resonance",
           modes=("bi",),
           en="FINAL FANTASY RESONANCE",
           category="作品/游戏",
           variants=("最终幻想：共振",),
           note="SE×LANCARSE 的 HD-2D 作品（2026-10-22 发售，FFBE 第一章重制）。Steam 简中页**名称未译**"
                "（store.steampowered.com/app/3259780/?l=schinese「名称: FINAL FANTASY RESONANCE」）⇒ 保留英文。"
                "「共振」「新共鸣」都是谷翻按子词直译的误形；《最终幻想：共鸣》仅媒体/台版译名，非官方简中。"
                "⚠ 「共振」本身是物理通用词，禁作裸键，故本实体只收 6 字长形。cue 1780/3009/3021/3037。"),
    # ============================================================
    # 2026-11-04 战双帕弥什 4.9「流光抛诸寰宇」英语原声 reaction 片
    #   片源《Jadealy Reacts to A Comet's Afterglow Trailers ｜ Punishing: Gray Raven》
    #   （216 cue，英语原声 + 谷歌翻译中文，--pgren）。
    #   一手出处：官网版本更新公告 pns.kurogames.com/news/5682 + TapTap 官方版本预约页
    #   taptap.cn/app/130651/game-event + 官方动态/B站预告PV「时尚大师」BV1EGJ96YEnj。
    #   ⚠ 全部只挂 pgren，不挂 bi/react：这些错形（莱娅/以实玛利/九郎）在别的游戏片里各有归属，
    #     进跨游戏兜底表即污染（同 2026-11-02「扩模式另立同 canonical 第二条，不改原条目」约定）。
    # ============================================================
    Entity("莱亚", modes=("pgren",), category="角色/战双帕弥什",
           variants=("莱娅",),
           note="官方机体全名「莱亚·祈星」：S 级泛用机体，◇属性/冰 ◇机体类型/破甲型 "
                "◇武器/遣光鞭绳 ◇效应/覆冰，必杀「群星起舞」，属**清庭白鹭小队**"
                "（指挥官为凡妮莎）；中配赵灵泽、日配悠木碧。"
                "官方台词（预约页逐字）：「锵锵~莱亚大英雄——登场！咳咳……按照淑女的方式，"
                "应该说……清庭白鹭小队莱亚，向您致意。」→ 本片 #128「铛铛！」→「锵锵~」、"
                "#130「我来啦，莱娅」→「莱亚大英雄——登场！」即取用此句。"
                "谷翻把 Leia 写成「莱娅」，同 2026-11-03 日语通道已定的 图层/蕾雅->莱亚。"),
    Entity("伊什梅尔", modes=("pgren",), category="角色/战双帕弥什",
           variants=("以实玛利",),
           note="官方机体全名「伊什梅尔·幻日」：**空属性**/**观测者**，武器**钥杖**，"
                "漫游·主宰双形态，核心技能「蜃幻浮影」，专属意识「索托斯」，伴生皮肤「御衡圣翼」，"
                "五周年「锈夜逐光」2024-11-07 上线，CV 姜英俊。"
                "4.9 新增特效涂装「霜尘拥月」——本片 #81 'Ishmael's getting a new coding as well' 即指它。"
                "⚠ 官中是「伊什梅**尔**」（梅），旧 BILINGUAL_TERMS 目标形「伊什麦尔」已于同日订正；"
                "⚠ 「以实玛利」同时是《边狱巴士》主角官中名，两侧英配同写 Ishmael 无从锚定区分，"
                "故本条**只挂 pgren**，边狱片走 --limbus/逐 cue。cue 80/81/151。"),
    Entity("战双帕弥什", modes=("pgren",), category="作品/游戏",
           variants=("灰乌鸦",),
           note="Punishing: Gray Raven 官方中文。本条只补「灰乌鸦」短形——"
                "ASR 常只带 'Gray Raven' 半截（本片 #43 'Gray Raven a comments a comments'），"
                "既有长键「惩罚灰乌鸦」覆盖不到。长键降序执行，短形不会咬长键产出。cue 43。"),
    Entity("库洛", modes=("pgren",), en="Kuro Games", category="公司/战双帕弥什",
           variants=("九郎",),
           note="库洛游戏，战双帕弥什/鸣潮 研发方。**ASR 把 Kuro 听成 Chloe**（谷翻落「克洛伊」）"
                "是本片头号隐性漏校：#45 'Chloe always cook with the soundtrack' 与 #205 "
                "'Kuro cooked. Again.' 同一说话人 + 同一动词 cook，且 #39 'same company for PGR' "
                "紧跟 #40 'right? Yep.' 在谈公司 ⇒ 铁证为库洛。"
                "「cook」按社区口径译「发力/杀疯了」，不直译「煮」——同 2026-10-XX 既有判例"
                "（'Kuro cooked=库洛杀疯了'里的「煮熟」是普通口语词，不能裸键）。"
                "错形「克洛伊」是通用音译串，**禁 variants**，走 PGR_EN_CONTEXT 的 \\bChloe\\b 锚定。"
                "cue 39/45/205。"),
    Entity("指挥官", modes=("pgren",), category="称谓/战双帕弥什",
           note="官方对玩家角色的统一称谓（官网公告「欢迎指挥官前往收听」「指挥官想要试试看吗？」）。"
                "英配作 Player/Commandant。⚠ **禁把「玩家」设为 variants**：reaction 杂谈里 "
                "'players' 大量指真实玩家，裸键必误伤——本片 #33 '>> Player.' 属 PV 台词，逐 cue 改。"),
    Entity("流光抛诸寰宇", modes=("pgren",), en="A Comet's Afterglow",
           category="作品/版本",
           note="战双帕弥什 4.9 版本名，2026-11-05 开启。本片英文标题与 ASR 的 "
                "'a comments (after glow)' 即 'A Comet's' 的误听。"
                "⚠ 中文错形「余辉/余晖/一条评论」全是通用词，**禁 variants**，"
                "改走 PGR_EN_CONTEXT 的 afterglow / 'a comments' 英文行锚定。cue 43/109。"),
    Entity("揽光一瞬", modes=("pgren",), category="涂装/战双帕弥什",
           note="莱亚·祈星 特效涂装（「流光抛诸寰宇」伴生涂装，11-05 起售）。"
                "官方文案逐字：「我要拍咯——3、2、1，茄子！」耀眼的花火在少女指尖流淌，"
                "短暂的一瞬过后，只留下鲜明而温馨的回忆，深深印在那张相纸上。"
                "→ 本片 #114 'Come and check out my new camera' 的出处。"
                "⚠ 英配与官中文案**语义相近而非逐字对应**，故不回写官方整句（2026-11-02 ⑥ 分级纪律）。"
                "同系列武器涂装「绯色慕意」（适用武器类型：遣光鞭绳）。"),
    Entity("霜尘拥月", modes=("pgren",), category="涂装/战双帕弥什",
           note="伊什梅尔·幻日 特效涂装，官方归入「游诗歌谣」系列。文案逐字：「在广袤宇宙中，"
                "有一颗星，它既不寒冷，也不滚烫。这是一颗尚且年轻、充满希望的星球，"
                "正逢来自封冻世界的女王投来一瞥。」同系列武器涂装「银漪曳星」（钥杖）。"
                "⚠ 本片 #163-171 的英配独白（'life is as brittle as a frozen bubble…'）主题相近、"
                "句式不对应 ⇒ 按英文行意译，不回写官方句。"),
    Entity("秧秧·玄翎", modes=("bi",), en="Yangyang: Xuanling",
           category="角色/鸣潮3.5",
           variants=("杨杨玄林",),
           ctx=((r"\bXuan\s*[Ll]in\b|\bXuanling\b", "杨杨"),),
           note="秧秧的新形态（官方英文 Yangyang: Xuanling，bilingual.py:1082 早有该长键）。"
                "2026-11-06 All 60 Gacha REACTION：微软翻译把 'Yang Yang Xuan Lin.' 整串落成"
                "「杨杨玄林」（#347）——整串非通用词，故收裸键；单「杨杨」是常见人名叠字，"
                "只能靠 Xuan Lin 参考行锚定。⚠ 与 Entity('秧秧') 的变体「杨阳」不同字"
                "（杨杨≠杨阳），两条互不咬合。其官方初奏=「……好久不见，{PlayerName}。」"
                "⇒ 台词中的玩家名占位符中文侧作『漂泊者』，切勿再判成弗洛洛。"),
    Entity("回旋于微光之上", modes=("pgren",), en="Dance With The Gleam",
           category="曲目/战双帕弥什",
           note="莱亚角色曲，中文版与日文版陆续上架 QQ音乐/网易云/酷狗。"
                "署名逐字：演唱 小缘（中/日），作词 Drew(中)/小泉果奈 Kana Koizumi(日)，"
                "作曲·编曲 DALCEXY，混音·母带 Bloop Studio，吉他 欧阳瑞声，监制 Grass/DALCEXY，"
                "出品 战双帕弥什。⚠ 日文版存在但**日文曲名未公布 ⇒ ja 留空不臆造**"
                "（2026-09-22 戒律 2：只有单一语种官方名的不翻译、保留原语言）。"),

    # ============================================================
    # 2026-11-09 《【Punishing: Gray Raven】A Comet's Afterglow ☄️ !pgr #ad》
    #   （姫宮りえ / Phase Connect，4667 cue，4:05:34 赞助直播 reaction，英语原声 + 谷翻中文，
    #     中文在上/英文参考行在下，CRLF 无 BOM，--pgren）
    #   一手出处：App Store 官方英文 4.9 更新公告 × TapTap/微博官方中文公告**逐项对齐**
    #   （版本名/角色/武器/意识/辅助机/涂装/活动名六项以上一一对应，反向锁定英→官中）：
    #     A Comet's Afterglow=流光抛诸寰宇、Leia: Fortunaster=莱亚·祈星、
    #     Edges of the Twisted Ribbon=扭曲缎带的边陲、Mousme=莫斯梅、Vulpecula=聆璃、
    #     Brilliant Instant=揽光一瞬、Cradled Moonfrost=霜尘拥月、Ishmael: Parhelion=伊什梅尔·幻日、
    #     Vera: Geiravor=薇拉·灼惘、Nanami: Startrail=七实·芒星之迹、Beauty Sefirah=美丽质点。
    #   世界观官中（App Store 官方简介原文）：Corrupted=感染体、Construct=构造体、
    #     Commandant=指挥官、Babylonia=空中花园、Memory=意识、Coating=涂装、CUB=辅助机、
    #     Ascendant=升格者、Gray Raven=灰鸦小队、Egret Squad=清庭白鹭小队、Strike Hawk=突击鹰小队。
    #   ⚠ 全部只挂 pgren：感染体/空中花园/意识/构造体 等错形在别的游戏片里各有归属，
    #     进跨游戏兜底表即污染（同 2026-11-04 约定）。
    # ============================================================
    Entity("感染体", modes=("pgren",), en="Corrupted", category="世界观/战双帕弥什",
           ctx=((r"\bcorrupted\b", "腐化者"),
                (r"\bcorrupted\b", "腐化"),
                (r"\bcorrupted\b", "腐败者")),
           note="PGR 官方中文=**感染体**（App Store 官方简介与中文公告对齐）。本片英文参考行 "
                "corrupt* 出现 50 次，是最高频漏校项；谷翻落成「腐化/腐化者/腐败者」。"
                "⚠ 三者全是通用中文词（腐化=道德败坏、腐败者=贪腐者），**禁 variants**，走英文行锚定。"
                "⚠ **ctx 按列表顺序执行（engine.py 的 pgren 分支非长键降序）**，故「腐化者」必须排在"
                "「腐化」之前，否则产出「感染体者」叠字。"
                "⚠ 锚定只在**本 cue 参考行**含 corrupted 时生效；本片 #2470/#2491/#2583/#3047/#3056 "
                "的 corrupted 落在邻接 cue（ASR 跨条断句），机械 pass 抓不到，属预期，由逐 cue 收口。"
                "corrupted hordes→感染体潮/群，the corrupted→感染体。"),
    Entity("空中花园", modes=("pgren",), en="Babylonia", category="地点/战双帕弥什",
           variants=("巴比伦尼亚",),
           ctx=((r"\bBabylonia\b", "巴比伦"),),
           note="PGR 空间站 Babylonia 官方中文=**空中花园**，不是「巴比伦尼亚/巴比伦」。"
                "本片 4 处（#357/#1878/#2001/#2012）参考行均明写 Babylonia，铁证。"
                "⚠ 「巴比伦尼亚」是专名音译串、非通用词 ⇒ 收 variants（无条件）；"
                "裸「巴比伦」是真实历史地名（本片 #1620-1752 主播正在聊奥斯曼/君士坦丁堡历史，"
                "但那段参考行无 Babylonia）⇒ **禁裸键**，走英文锚定。"
                "⚠ 长键「巴比伦尼亚」在 TERMS 阶段先替换，ctx 的短键「巴比伦」 afterwards 找不到它，"
                "故不会产出「空中花园尼亚」；顺序反了就会（TERMS 先于 CTX 是 engine 的既定次序）。"),
    Entity("凡妮莎", modes=("pgren",), en="Vanessa", category="角色/战双帕弥什",
           ctx=((r"\bVanessa\b", "瓦妮莎"),),
           note="清庭白鹭小队指挥官。官方中文=**凡妮莎**（4.9 公告与莱亚·祈星档案对齐）。"
                "本片参考行 Vanessa 出现 37 次，谷翻落成「瓦妮莎」12 处。"
                "⚠ 「瓦妮莎」是常见真实人名音译串 ⇒ 按 2026-11-04「克洛伊」判例**禁 variants**，"
                "走 \\bVanessa\\b 英文行锚定。"),
    Entity("清庭白鹭小队", modes=("pgren",), en="Egret Squad", category="组织/战双帕弥什",
           ctx=((r"\bEgret\b", "白鹭队"),),
           note="4.9 新机体的所属小队：指挥官**凡妮莎**，队员**莱亚·祈星**、**忒修**(Theseus)、"
                "**邦比娜塔**(Bambinata)。官方中文=清庭白鹭小队（BWIKI 世界观/突击鹰小队页 + "
                "莱亚·祈星官方台词「清庭白鹭小队莱亚，向您致意」）。"
                "⚠ 「白鹭」是真实鸟名 ⇒ **禁裸键**，只收复合错形「白鹭队」并锚 \\bEgret\\b。"
                "⚠ 替换结果「清庭白鹭小队」不含连续子串「白鹭队」（中间有「小」），无叠字风险。"
                "本片 #3571/#3572 跨 cue 断句：'a member of Vanessa's' / 'Egret squad.'，"
                "锚只在后一条命中，前一条需逐 cue。"),
    Entity("突击鹰小队", modes=("pgren",), en="Strike Hawk", category="组织/战双帕弥什",
           ctx=((r"\bstrike (?:hawk|clock)\b", "打击鹰"),
                (r"\bstrike (?:hawk|clock)\b", "击钟")),
           note="PGR 执行部队下属小队，官方中文=**突击鹰小队**（BWIKI 世界观页）。"
                "本片 #2765 参考行明写 'strike hawk to provide support.'，谷翻落「打击鹰」；"
                "#2698 ASR 把 Strike Hawk 听成 'Strike clock'，谷翻据此直译「击钟」——"
                "两种错形同指一个小队，故锚同时收 hawk|clock。"
                "⚠ 「击钟」是通用动宾串（敲钟）、「打击」是高频通用词 ⇒ **禁裸键**，只收"
                "「打击鹰」「击钟」两个完整错形并锚英文行。长形「打击鹰」在前。"
                "⚠ #2816-2818 英文是 'strike. Strike what?' —— 主播拿 strike 这个词开玩笑，"
                "参考行无 hawk/clock ⇒ 锚不命中，正确保留「打击」，不要逐 cue 改成小队名。"
                "⚠ #2915/#2916 把 Strike Hawk 拆成两条（'redirecting Strike. Strike up.' / 'Sport,'），"
                "锚不命中，属跨 cue 碎片，逐 cue 收口。"),
    Entity("帕弥什病毒", modes=("pgren",), en="Punishing Virus", category="世界观/战双帕弥什",
           variants=("惩罚性病毒", "惩罚病毒"),
           note="PGR 世界观核心：the Punishing (virus) 官方中文=**帕弥什病毒**（游戏名即由此而来）。"
                "本片参考行 'punishing virus' 出现 11 次，谷翻直译「惩罚性病毒」8 处 / 「惩罚病毒」3 处。"
                "⚠ 裸「惩罚」绝不进表（ark.py 3.3a 戒律①：punishment=惩罚 是本义）；"
                "这里收的是**完整复合错形**「惩罚性病毒」「惩罚病毒」，非通用词，故可作 variants"
                "（同既有「惩罚性灰乌鸦」判例）。"
                "⚠ 两键互不为子串（惩罚性病毒 含「性」，惩罚病毒 不含），长键降序无叠字；"
                "替换结果「帕弥什病毒」不含任一错形，幂等。"),
    Entity("升格者", modes=("pgren",), en="Ascendant", category="世界观/战双帕弥什",
           ctx=((r"\bascendant\b", "上升者"),),
           note="PGR 官方中文=**升格者**（ Ascendant，代行者/升格网络体系）。本片 #2712 "
                "'ascendant is pulling the strings.' 谷翻落「上升者」。"
                "⚠ 「上升者」是通用中文词 ⇒ **禁裸键**，锚 \\bascendant\\b。"
                "⚠ 形容词 ascendant（占优势的）在本作语境罕见，若日后误伤需收窄锚定。"),
    Entity("莫斯梅", modes=("pgren",), en="Mousme", category="意识/战双帕弥什",
           note="4.9「流光抛诸寰宇」新增 6★意识，莱亚·祈星 专属。官方英文公告 Mousme × "
                "中文公告「莫斯梅」逐项对齐确证。⚠ 本片参考行零命中、无实测错形 ⇒ "
                "**仅登记元数据、不带 variants/ctx**（同 2026-09-22 音乐实体判例：无实测错形不造键），"
                "供 kb-export / AI Agent 跨语识别。⚠ 官中是「莫斯梅」，不要按日文「娘」义臆造「少女」。"),
    Entity("聆璃", modes=("pgren",), en="Vulpecula", category="辅助机/战双帕弥什",
           note="4.9 新增辅助机（CUB），莱亚·祈星 配套。官方英文公告 Vulpecula（狐狸座）× "
                "中文公告「聆璃」逐项对齐确证。⚠ 本片参考行零命中、无实测错形 ⇒ "
                "**仅登记元数据、不带 variants/ctx**。⚠ 官中是「聆璃」，**不是**星座直译「狐狸座」，"
                "也不是「 vulpecula 」音译；CUB 官方中文=辅助机。"),
    Entity("邦比娜塔", modes=("pgren",), en="Bambinata", category="角色/战双帕弥什",
           variants=("阿米纳塔",),
           note="官方机体全名「邦比娜塔·琉璃」：A 级进攻型构造体，机体编号 **BPM-11**，武器螳螂刃"
                "「静谧人形之声」，2022-08「未语庭言」版本上线，属**清庭白鹭小队**（指挥官凡妮莎）。"
                "出处：维基百科《战双帕弥什角色列表》直接给出「邦比娜塔（バンビナータ，**Bambinata**）」"
                "+ BWIKI 世界观/邦比娜塔 + 萌娘百科导航「清庭白鹭小队（凡妮莎·忒修·邦比娜塔）」三源一致。"
                "⚠ **本片头号隐性漏校**：谷翻按 ASR 噪声直译成「阿米纳塔」9 处，参考行分别是 "
                "Aminata / Vamada / Babinatada / Bab / Ainatada / Amada / Babinada / Baminata —— "
                "一簇变体同指一人。判据＝①三处以上变体以 Baminata/Babinada 最接近 Bambinata；"
                "②该角色全程与凡妮莎/莱亚同框，正是清庭白鹭小队 roster；③BWIKI 载邦比娜塔出自"
                "**黑野**福利院、被黑野研究员收养成为凡妮莎的「妹妹」，与本片 #3569-3571"
                "（Mio Kurono / 黑野澪 / 凡妮莎）的黑野线完全吻合。"
                "⚠ 「阿米纳塔」是完整音译串非通用词 ⇒ 可作 variants（同「阿德利德→阿德莱德」判例）。"),
    Entity("阿西莫夫", modes=("pgren",), en="Asimov", category="角色/战双帕弥什",
           variants=("Asimov", "Asimoth", "阿斯莫斯", "阿斯玛"),
           note="**科学理事会现任负责人（首席技官）**、空中花园议会一员，主管科技事务，助手洛莎，CV 马正阳。"
                "出处：BWIKI 世界观/阿西莫夫 + 萌娘百科导航「科学理事会 阿西莫夫」。"
                "⚠ 本片 #1902/#1935/#1972 已正确作「阿西莫夫」，而 #2055/#2073/#2641 却保留拉丁"
                "（Asimoth / Asma / Asimov）—— 正是「同一专名多种写法，出现次数少的那个是异形」判例。"
                "⚠ 片内铁证：#2073 'Nicola pats Asma on the shoulder' 与 BWIKI 载「雷文治事件后阿西莫夫被"
                "**尼科拉**调用、远程对露西亚做意识海手术」的人物关系吻合。"
                "⚠⚠ **短形 `Asma` 禁入 variants**：它是 `plasma`（等离子体）的子串，而 `_replace_report` "
                "是裸 str.replace 无词边界，会产出「pl阿西莫夫」。本片 #4259 参考行就有 plasma"
                "（中文行恰好无拉丁才没炸）⇒ 拉丁 `Asma` 只逐 cue 处理，不入表。"
                "⚠ 但其中文音译形「**阿斯玛**」可安全入表（汉字串不是 plasma 的子串）——本片 #2073 "
                "原始谷翻正是「尼古拉拍拍阿斯玛的肩膀」，与拉丁形 `Asma` 是同一错形的两条产出路径"
                "（同 2026-09-22 Exostrider 判例：沉淀必须覆盖音译/简写/子词直译全部路径）。"
                "⚠ 收的是完整形 Asimov / Asimoth / 阿斯莫斯 / 阿斯玛，互不为子串，替换结果不含任一错形，幂等。"),
    Entity("尼科拉", modes=("pgren",), en="Nicola", category="角色/战双帕弥什",
           ctx=((r"\bNicol", "尼古拉斯"),
                (r"\bNicol", "尼古拉")),
           note="**指挥中心**成员（与哈桑/希尔达/赛利卡同列），官方中文=**尼科拉**不是「尼古拉」。"
                "出处：萌娘百科战双导航「指挥中心 哈桑·尼科拉·希尔达·赛利卡」（多页面一致）"
                "+ BWIKI 阿西莫夫页对话原文「尼科拉：你……对保护构造体的意识这件事情好像有些特别的执着」。"
                "本片谷翻一律落成通用俄式音译「尼古拉」29 处（参考行 Nicola 18 / Nicolola 1 / Nicole 1）。"
                "⚠ 「尼古拉」是通用人名音译串（尼古拉·特斯拉）⇒ **禁裸键**，锚英文参考行。"
                "⚠⚠ **锚 `\\bNicol` 天然不匹配 `Nicholas`**（Nic**h**olas vs Nic**o**la，第4字符 h≠o）"
                "⇒ 本片 #1595/#1596/#1598 的历史炼金术士 **Nicolas Flamel**（Nicholas Lamel / Palamel，"
                "谷翻作「尼古拉斯·拉梅尔/帕拉梅尔」）**不会被误伤**，这是本轮实测确认的安全边界。"
                "⚠ 长形「尼古拉斯」必须排在「尼古拉」前（ctx 按列表顺序执行），否则产出「尼科拉斯」。"
                "⚠ 代价：#2522 'Under Nicholas's orders' / #2540 'Commander Nicholas' 实为 Nicola 的 "
                "ASR 变体（与 #2921 'Following Nicola's orders' / #3025 'Commander Nicola' 同句式同角色），"
                "但锚不命中 ⇒ 保守漏放，由逐 cue 收口。**不要为此把锚放宽到 \\bNichol\\b**，那会炸 Flamel。"),

    # =============================================================
    # 2026-11-10 二校沉淀：《This Is Gacha Worldbuilding at Its Peak》
    #   SmugSlav reaction，英语原声 + 谷歌翻译；1004 cue，中文在上/英文参考在下。
    #   依据：Arknights 官方中文（references/Arknights_Lore_Terminology_EN_CN_JP_KR.md）；
    #         Limbus 无官方简中，沿用项目既定零协/社区口径（游戏名《边狱巴士》）。
    #   约定：拉丁/生僻错形走 variants；正常中文词（恐怖/圣人/午睡/修复/翅膀…）
    #         走 ctx 锚英文参考行，避免裸键误伤其它片源。
    #   ⚠ ctx 按 ENTITIES 顺序追加，专名/长短语实体必须排在通用词实体之前。
    # =============================================================
    # --- Arknights：国家/种族/灾害/源石技艺 ---
    Entity("泰拉", modes=("ak",), en="Terra", category="世界观/明日方舟",
           ctx=((r"\bterror\b", "恐怖"),),
           note="片内 ASR 反复把 Terra 听成 terror，谷翻全译「恐怖」；"
                "#129/#527/#557 按此归一。#438 terrorist France 为整句错位，走 subfix。"),
    Entity("伊比利亚", modes=("ak",), en="Iberia", category="国家/明日方舟",
           variants=("Earia",), ctx=((r"\bpast\s+IA\b", "IA"),),
           note="本片 ASR 把 Iberia 拼作 Earia（#221/#240/#243）与 IA（#227）。"
                "#221 的 Leair=Liberi 见黎博利条。"),
    Entity("黎博利", modes=("ak",), en="Liberi", category="种族/明日方舟",
           variants=("Leair",),
           note="拉特兰主要种族之一；本片 #221 'Leair from Earia' 谷翻保留拉丁。"),
    Entity("萨科塔", modes=("ak",), en="Sankta", category="种族/明日方舟",
           ctx=((r"\bsanctum\b", "圣所"), (r"\bSanctas?\b", "圣人")),
           note="本片 #211 sanctum、#216/#221 Sanctas 被谷翻成「圣所/圣人」；"
                "Sankta 裸键已在 AK_TERMS（ark.py:622），此处只补普通中文词锚定。"),
    Entity("叙拉古", modes=("ak",), en="Siracusa", category="国家/明日方舟",
           variants=("Sierrausa", "Sirusa", "塞拉卢萨", "西鲁莎"),
           ctx=((r"\bSyracuse\b", "锡拉丘兹"),),
           note="本片 ASR 变体：Sierrausa(#199/#200/#205)、Sirusa(#174)、"
                "Syracuse(#346)；谷翻音译塞拉卢萨/西鲁莎/锡拉丘兹。"),
    Entity("汐斯塔", modes=("ak",), en="Siesta", category="城邦/明日方舟",
           ctx=((r"\bSiesta\b", "午睡"), (r"\bSiesta\b", "午休")),
           note="独立城邦汐斯塔；本片 #251/#265 谷翻按普通词译「午睡/午休」。"),
    Entity("萨尔贡", modes=("ak",), en="Sargon", category="国家/明日方舟",
           variants=("Zargon",),
           note="本片 #121 ASR 把 Sargon 拼作 Zargon，中文行保留拉丁。"),
    Entity("萨卡兹", modes=("ak",), en="Sarkaz", category="种族/明日方舟",
           ctx=((r"\bsarcas\b", "讽刺"),),
           note="本片 #543 'wars with the sarcas' 谷翻成「讽刺」；"
                "#364 'Sarcos royal court' 是萨卡兹王庭，走 subfix 整句。"),
    Entity("乌萨斯", modes=("ak",), en="Ursus", category="国家/明日方舟",
           variants=("Ersus", "埃尔苏斯"),
           note="本片 #403/#405 ASR 把 Ursus 拼作 Ersus，谷翻音译「埃尔苏斯」。"),
    Entity("高卢帝国", modes=("ak",), en="Gaul", category="国家/明日方舟",
           variants=("加尔帝国",),
           note="本片 #409 'Empire of Gal' 谷翻「加尔帝国」；替换后保留「帝国」二字。"),
    Entity("卡西米尔", modes=("ak",), en="Kazimierz", category="国家/明日方舟",
           ctx=((r"\bKashmir\b", "克什米尔"),),
           note="本片 #351 'invade Kashmir' 谷翻按现实克什米尔；明日方舟官方=卡西米尔。"),
    Entity("鹰角", modes=("ak",), en="Hypergryph", category="公司/明日方舟",
           variants=("Hypergraph",),
           note="《This Is Gacha Worldbuilding at Its Peak》#558 ASR 把 Hypergryph 拼作 Hypergraph，"
                "中文行保留拉丁。canonical 用既有 AK_TERMS 的「鹰角」（短形式），"
                "不写「鹰角网络」以免与 Hypergryph→鹰角 产生双目标冲突；"
                "endobi 侧的「鹰角网络」见本文件 2026-11-01 条目。"),
    Entity("矿石病", modes=("ak",), en="Oripathy", category="设定/明日方舟",
           ctx=((r"\brock\s+cancer\b", "岩癌"), (r"\brock\s+cancer\b", "岩石癌"),
                (r"the more cancer you get", "癌症")),
           note="本片 #375/#379 谷翻「岩癌/岩石癌」，#927 直接「癌症」；"
                "#272 现实语境 'nuclear bombs, cancer' 保留不动。"),
    Entity("天灾信使", modes=("ak",), en="Catastrophe Messenger", category="设定/明日方舟",
           ctx=((r"\bcatastrophe\s+messengers?\b", "灾难使者"),),
           note="本片 #393 'catastrophe messengers' 谷翻「灾难使者」。"),
    Entity("天灾", modes=("ak",), en="Catastrophe", category="设定/明日方舟",
           ctx=((r"\bcatastroph\w*\b", "灾难"), (r"\bdisaster\b", "灾难")),
           note="本片 #368/#380/#390 谷翻「灾难」；明日方舟官方=天灾。"),
    Entity("源石技艺", modes=("ak",), en="Originium Arts", category="设定/明日方舟",
           ctx=((r"\borigin\s+arts\b", "艺术"), (r"\bsong\s+of\s+arts\b", "艺术"),
                (r"\bcomplex\s+arts\b", "艺术"), (r"\bbest\s+arts\b", "艺术")),
           note="本片 #154/#163/#331/#332/#343 把 Arts 当普通「艺术」；"
                "#147 explored arts / #564 art books 是字面艺术，保留。"),
    Entity("移动城市", modes=("ak",), en="Nomadic City", category="设定/明日方舟",
           ctx=((r"\bnomatic\s+platforms\b", "nomatic"),),
           note="本片 #382 'nomatic platforms' 谷翻保留拉丁；官方=移动城市。"),
    Entity("四皇会战", modes=("ak",), en="Battle of the Four Emperors", category="历史事件/明日方舟",
           variants=("四人之战", "四皇之战"),
           ctx=((r"\bfour\s+emperors\b", "皇帝们"),),
           note="本片 #313/#419 作「四人之战」、#404/#434 作「四皇之战」、"
                "#314/#420 拆成「皇帝们」；统一四皇会战。"),
    Entity("世界观构建", modes=("ak", "limbus"), en="world building", category="术语/通用",
           variants=("世界建筑", "世界建设", "世界大厦"),
           ctx=((r"\bworld\s+building\b", "建筑"),),
           note="本片主题词，一校 11 处已归一但只落侧车；二校回灌。"
                "#37/#41/#977 的 world 在上一 cue、building 在本 cue，走 subfix。"),
    Entity("设定", modes=("ak",), en="lore", category="术语/通用",
           ctx=((r"\blore\b", "传说"),),
           note="lore=世界观设定，不是「传说」；一校 #75/#134/#266/#558 已归一，二校回灌。"),
    Entity("服务型游戏", modes=("ak", "limbus"), en="live service game", category="术语/通用",
           variants=("现场服务游戏",),
           note="一校 #28 已归一，二校回灌。"),
    Entity("服务型", modes=("ak", "limbus"), en="live service", category="术语/通用",
           ctx=((r"\blive\s+service\b", "生活服务"),),
           note="一校 #31 已归一，二校回灌。"),
    Entity("奇点", modes=("limbus",), en="Singularity", category="设定/边狱巴士",
           ctx=((r"\bsingularity\b", "独特之处"), (r"\bsingularity\b", "奇异性")),
           note="一校 #661/#709/#824 已归一，二校回灌。"),
    Entity("滑铁卢", modes=("ak",), en="Battle of Waterloo", category="现实典故",
           ctx=((r"\bwateroo\b", "沃特卢"),),
           note="本片 #435 ASR 'wateroo'，谷翻「沃特卢」；中文行已有「战役」，"
                "故 canonical 只作「滑铁卢」，避免产出「滑铁卢战役战役」。"),
    Entity("源石", modes=("ak",), en="Originium", category="设定/明日方舟",
           ctx=((r"\boriginian\b", "原产地"),),
           note="本片 #563 'originian' 谷翻「原产地」；明日方舟官方=源石。"),

    # --- Limbus Company：作品/都市/公司/核心术语 ---
    Entity("废墟图书馆", modes=("limbus",), en="Library of Ruina", category="作品/边狱巴士",
           variants=("Library of Verona", "瑞纳图书馆", "维罗纳图书馆"),
           ctx=((r"\bRena\b", "瑞纳"), (r"\bRunna\b", "润娜"), (r"\bruna\b", "runa")),
           note="本片 #587 Library of Verona、#632 瑞纳图书馆、#658 润娜、"
                "#668 runa、#791 Rena；统一官方中文《废墟图书馆》。"),
    Entity("脑叶公司", modes=("limbus",), en="Lobotomy Corporation", category="作品/边狱巴士",
           variants=("Labbotomy Corp", "Labon Corporation", "Labon 公司",
                     "Lob Corp", "Lock Corp", "Lock 公司"),
           note="本片 #630 Labbotomy Corp、#650 Labon Corporation、#665 Lob Corp、"
                "#668 Lock Corp；统一《脑叶公司》。#665/#668 的所属格/跨 cue 走 subfix。"),
    Entity("R公司", modes=("limbus",), en="R Corp", category="公司/边狱巴士",
           variants=("Arcore",),
           ctx=((r"\bArp\b", "Arp"),),
           note="R公司奇点=克隆；本片 #650 Arcore、#658/#661 Arp。"
                "Arp 裸键有误伤风险，只在参考行命中时替换。"),
    Entity("F公司", modes=("limbus",), en="F Corp", category="公司/边狱巴士",
           variants=("FC Corp", "FC 公司"),
           ctx=((r"\bFC\b", "FC"),),
           note="本片 #706/#707 'FC Corp' 跨 cue 拆成 FC + 公司；"
                "妖精（Fairy）见妖精条。"),
    Entity("G公司", modes=("limbus",), en="G Corp", category="公司/边狱巴士",
           variants=("GC Corp", "GC公司", "GC 公司"),
           note="本片 #709/#714 GC Corp/GC公司；旧型G公司昆虫强化。"),
    Entity("J公司", modes=("limbus",), en="J Corp", category="公司/边狱巴士",
           variants=("JC Corp",),
           note="本片 #716 JC Corp；概念层面锁定/窃取。"),
    Entity("K公司", modes=("limbus",), en="K Corp", category="公司/边狱巴士",
           variants=("KC Corp", "KC Corps", "KC 公司", "KC军团"),
           note="本片 #719 KC Corps、#763/#768 KC Corp/KC 公司；治愈安瓿。"),
    Entity("M公司", modes=("limbus",), en="M Corp", category="公司/边狱巴士",
           variants=("MC Corp",),
           ctx=((r"\bMC\s+Corp\b", "三菱商事公司"),),
           note="本片 #720 谷翻把 MC Corp 当成三菱商事；官方/社区=M公司。"),
    Entity("N公司", modes=("limbus",), en="N Corp", category="公司/边狱巴士",
           variants=("Encorp",),
           ctx=((r"\bEncorp\b", "安科普"),),
           note="本片 #729 Encorp 谷翻「安科普」；N公司=罐头体验。"),
    Entity("P公司", modes=("limbus",), en="P Corp", category="公司/边狱巴士",
           variants=("PC Corp", "PC公司"),
           ctx=((r"\bPissorp\b", "皮索普"),),
           note="本片 #735 PC Corp、#739 Pissorp 谷翻「皮索普」。"),
    Entity("T公司", modes=("limbus",), en="T Corp", category="公司/边狱巴士",
           variants=("TC Corp", "TCP"),
           ctx=((r"\bTorp\b", "托普罐头"), (r"\bTorp\b", "托普")),
           note="本片 #600/#737 Torp、#605/#823 TCP、#822/#826/#845 TC Corp；"
                "T公司=时间控制。"),
    Entity("U公司", modes=("limbus",), en="U Corp", category="公司/边狱巴士",
           ctx=((r"\bUK\s+is\s+known\b", "英国"),),
           note="本片 #739 'UK is known for their ability to keep food in stasis' "
                "谷翻「英国」；此 UK=U Corp，只在锚定句替换。"),
    Entity("W公司", modes=("limbus",), en="W Corp", category="公司/边狱巴士",
           variants=("WC Corp", "WC公司"),
           ctx=((r"\bWC\b", "卫生间"),),
           note="本片 #750 谷翻把 WC 当卫生间；#771/#776/#808/#837/#821 WC Corp；"
                "W公司=跃迁列车。"),
    Entity("后巷", modes=("limbus",), en="Backstreets", category="设定/边狱巴士",
           ctx=((r"\bback\s+streets\b", "背部街道"),),
           note="本片 #593/#594 'back streets' 被拆行，谷翻「背部街道」；走 subfix 整句。"),
    Entity("色彩收尾人", modes=("limbus",), en="Color Fixer", category="设定/边狱巴士",
           ctx=((r"\bcolored\s+fixers?\b", "彩色固定剂"),),
           note="本片 #833 'colored fixers' 谷翻「彩色固定剂」；社区标准=色彩收尾人。"),
    Entity("收尾人", modes=("limbus",), en="Fixer", category="设定/边狱巴士",
           ctx=((r"\bfixers?\b", "修复方法"), (r"\bfixers?\b", "修复了"),
                (r"\bfixes?\b", "修复")),
           note="本片 #880/#884 谷翻把 Fixer/fixes 当「修复方法/修复了」；"
                "#833 colored fixers 另见色彩收尾人。"),
    Entity("帮派", modes=("limbus",), en="Syndicate", category="设定/边狱巴士",
           ctx=((r"\bsyndicates?\b", "辛迪加"),),
           note="本片 #869/#882 'syndicates' 谷翻音译「辛迪加」；社区标准=帮派。"),
    Entity("妖精", modes=("limbus",), en="Fairy", category="设定/边狱巴士",
           ctx=((r"\bfair(?:y|ies)\b", "仙女"),),
           note="本片 #707 F公司 Fairy 谷翻「仙女」；社区标准=妖精。"),
    Entity("翼", modes=("limbus",), en="Wing", category="设定/边狱巴士",
           ctx=((r"\bthese\s+wings\b", "翅膀"), (r"\brival\s+wing\b", "机翼"),
                (r"\bcausing\s+the\s+wing\b", "机翼"), (r"\bother\s+wings\b", "翅膀"),
                (r"\bother\s+wings\b", "翼队"), (r"\ba\s+wing\s+fell\b", "翅膀")),
           note="本片 #705/#758/#760/#767/#772/#773 把 Wing 译成翅膀/机翼/翼队；"
                "#212 halos and wings 是字面翅膀，不锚定。"),
    Entity("跃迁列车", modes=("limbus",), en="Warp Train", category="设定/边狱巴士",
           ctx=((r"\bwarp\s+trains?\b", "经纱"), (r"\bwarp\s+trains?\b", "扭曲"),
                (r"\bwork\s+trains?\b", "工作列车")),
           note="本片 #777/#778/#803/#816 把 warp train 译成扭曲/经纱/工作列车；"
                "跨 cue 的「火车」走 subfix。"),
    Entity("月光石", modes=("limbus",), en="Moonlight Stone", category="设定/边狱巴士",
           variants=("月光石头",),
           note="本片 #722/#723 Moonlight Stone 被拆成「月光/石头」；走 subfix 整句。"),
    Entity("概念焚化炉", modes=("limbus",), en="Concept Incinerator", category="设定/边狱巴士",
           ctx=((r"\bconcept\s+incinerator\b", "焚化炉的概念"),),
           note="本片 #898 'concept incinerator' 谷翻「焚化炉的概念」；官方/社区=概念焚化炉。"),
    Entity("L公司", modes=("limbus",), en="L Corp", category="公司/边狱巴士",
           ctx=((r"\bElor\b", "埃洛尔"),),
           note="本片 #842 'They got energy from Elor' 谷翻「埃洛尔」；Elor=L Corp。"),
    Entity("边狱巴士", modes=("limbus",), en="Limbus Company", category="作品/游戏",
           variants=("Limba's company", "Limba 公司", "Limbbus Company", "Lumus Company"),
           ctx=((r"\bLimba\b", "Limba"),),
           note="本片 #599 'until Limba's' 谷翻保留 Limba；"
                "游戏名统一《边狱巴士》，游戏内组织名另作《边狱公司》。"),
    Entity("月亮计划", modes=("limbus",), en="Project Moon", category="公司/边狱巴士",
           variants=("月球计划",),
           note="本片 #568/#572/#628/#702/#704/#848/#891 把 Project Moon 直译「月球计划」；"
                "中文社区通行「月亮计划」（无官方简中）。"),
    Entity("莱塔尼亚", modes=("ak",), en="Leithanien", category="国家/明日方舟",
           variants=("Lar Night",),
           note="本片 #143 ASR 把 Lethania 听成 Lar Night，中文行保留拉丁；"
                "官方中文=莱塔尼亚。"),
    Entity("明日方舟维基百科", modes=("ak",), en="Arknights Wikipedia", category="站点/明日方舟",
           variants=("arknet 维基百科",),
           note="本片 #422 'arknet Wikipedia' 谷翻保留 arknet；指明日方舟 Wiki。"),
    Entity("明日方舟", modes=("ak",), en="Arknights", category="作品/游戏",
           ctx=((r"\bArcNet\b", "ArcNet"),),
           note="本片 #473 'if they get interested in ArcNet' 的 ArcNet 是 Arknights 的 ASR 变体；"
                "只在参考行命中 ArcNet 时替换，避免误伤其它片源的专名。"),
    # ============================================================
    # 2026-11-10 鸣潮 3.5 Story（I'M BACK ON WUTHERING WAVES，Gigguk）
    #   二校沉淀：本片残留的 ASR/谷翻错形。官方依据：
    #   BWIKI「设定拾遗/秧秧」「角色/秧秧」「名词注释/玄翎雀」、
    #   3.5 第四章·第二幕「玄翎振骸定澜音」、首页/探索报告。
    #   戒律：生僻拉丁/中文错形可进 variants；常用词走 ctx 英文锚定。
    # ============================================================
    Entity("今州", modes=("bi",), en="Jinzhou", category="地名/鸣潮",
           variants=("Jino",),
           note="本片 #996/#1036/#1351/#1631/#1967 等 ASR 把 Jingo 写成 Jino，谷翻保留拉丁；"
                "官方中文=今州。"),
    Entity("梦州", modes=("bi",), en="Mengzhou", category="地名/鸣潮",
           variants=("Moonjo", "Mongj", "Mong Jojo"),
           note="本片 #1020/#12008/#15338 等 ASR 变体；官方中文=梦州。"),
    Entity("玄方城", modes=("bi",), en="Schwanfong Hold", category="地名/鸣潮",
           variants=("Shwangfong", "Shwang", "Halt"),
           ctx=((r"\bSchwan\w*\b|\bSwan\w*\b", "天鹅方"),
                (r"\bSchwan\w*\b|\bSwan\w*\b", "天鹅房"),
                (r"\bSchwan\w*\b|\bSwan\w*\b", "天鹅坊")),
           note="本片 #3009 天鹅方、#7978 天鹅房、#2560 天鹅坊、#1024 Shwang Thong、"
                "#1039 Halt 等；官方中文=玄方城（梦州·玄方地界）。"
                "⚠ 天鹅* 是通用词，只在英文行出现 Schwan/Swan 时锚定。"),
    Entity("炽霞", modes=("bi",), en="Chixia", category="角色/鸣潮",
           variants=("Chisia", "Chushia", "Chija", "Juicia"),
           note="本片 #1014/#1016/#1205/#1228 等 ASR 变体；官方中文=炽霞。"),
    Entity("凌阳", modes=("bi",), en="Lingyang", category="角色/鸣潮",
           variants=("Leangu", "Leangui"),
           note="本片 #2111/#2175/#2579/#4661 等 ASR 变体；官方中文=凌阳。"),
    Entity("华胥院", modes=("bi",), en="Huashu Academy", category="地点/鸣潮3.5",
           variants=("Hashu Academy", "哈树星炬学院", "胡阿什学院"),
           note="本片 #1689/#1889/#4676 等；官方中文=华胥院（3.5 玄方地界机构），"
                "不是星炬学院。"),
    Entity("星炬学院", modes=("bi",), en="Startorch Academy", category="地点/鸣潮",
           variants=("Starch Academy", "Star Tour Academy", "淀粉星炬学院"),
           note="本片 #316/#585/#1489 等谷翻错形；官方中文=星炬学院（拉海洛）。"),
    Entity("玄翎雀", modes=("bi",), en="Xuanling Bird", category="生物/鸣潮3.5",
           variants=("天鹅灵鸟", "Lling"),
           note="本片 #2650/#2755/#5926/#5936 等；官方中文=玄翎雀。"
                "旧表 shling鸟->天鹅灵鸟 已改。"),
    Entity("天工部", modes=("bi",), en="Skyworks", category="势力/鸣潮",
           variants=("Skyworks", "Skywatch", "Skywards", "斯凯沃斯", "天工坊"),
           note="本片 #2933/#3940/#3958/#4114/#2949 等；官方中文=天工部（玄方城机关工业）。"),
    Entity("军策府", modes=("bi",), en="Ministry of War", category="势力/鸣潮",
           ctx=((r"\bMinistry of War\b", "部委"),),
           note="本片 #1590/#3164/#5605；官方中文=军策府。"
                "⚠ 发展部=Ministry of Development，英文为 Development 时不得改。"),
    Entity("渊城", modes=("bi",), en="Yuan Fortress", category="地点/鸣潮",
           variants=("元要塞", "袁堡垒"),
           note="本片 #2851/#3069/#4734 等；官方中文=渊城（云渊之役要塞）。"),
    Entity("瑝珑", modes=("bi",), en="Huanglong", category="国家/鸣潮",
           variants=("恒龙", "洪龙", "宏龙"),
           note="本片 #305/#588/#595 等；官方中文=瑝珑。"),
    Entity("方壶西峰", modes=("bi",), en="Western Fong Peaks", category="地点/鸣潮3.5",
           variants=("方擎西峰", "西玄峰", "西芳峰"),
           ctx=((r"\bWestern\s+(?:Fong|Fang)\s+Peaks?\b", "西方峰"),),
           note="本片 #2926/#2932/#2995 等；官方写法=方壶西峰（BWIKI 首页/探索报告）。"
                "⚠ 旧表 target 方擎西峰 为误写，已改；西方峰 只在英文锚定。"),
    Entity("玄幽东岳", modes=("bi",), en="Eastern Xuan Peaks", category="地点/鸣潮3.5",
           variants=("东天鹅峰", "东玄方山峰"),
           ctx=((r"\bEastern\s+(?:Xuan|Sh\s*uan|Swan)\s+Peaks?\b", "东玄峰"),),
           note="本片 #1818/#3923 等；官方写法=玄幽东岳（BWIKI 探索报告）。"),
    Entity("无相燹主", modes=("bi",), en="Ovathrax", category="敌人/鸣潮",
           variants=("Overthrax", "Ovathrax"),
           note="本片 #333/#3042；官方中文=无相燹主。"),
    Entity("角", modes=("bi",), en="Jue", category="角色/岁主",
           variants=("Jouer", "Jer"),
           ctx=((r"\bJouer\b", "Play"),),
           note="本片 #1033/#1094/#3532；官方中文=角。Play 是谷翻把 Jouer 当法语“玩”的错译。"),
    Entity("心", modes=("bi",), en="Hsin", category="角色/岁主",
           ctx=((r"\bmoonfox sentinel,?\s*Chin\b", "Chin"),),
           note="本片 #1035；官方中文=心（岁主分出的情感模块）。"),
    Entity("穗穗", modes=("bi",), en="Suisui", category="角色/鸣潮",
           ctx=((r"\bSui\b", "隋"),),
           note="本片 #1107/#1109；官方中文=穗穗。"),
    Entity("散华", modes=("bi",), en="Sanhua", category="角色/鸣潮",
           ctx=((r"\bSana\b|\bSanhua\b", "萨娜"), (r"\bSan\b", "桑")),
           note="本片 #950/#970；官方中文=散华。"),
]

