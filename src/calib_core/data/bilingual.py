# -*- coding: utf-8 -*-
# @version 2.9.0
"""术语/实体数据表

源：subtitle_calib_merged.py L493-L2378 @ 97d7d463（2026-10-24 冻结快照）
"""
import io
import os
import re
import shutil
import sys
import unicodedata



# =============================================================
# 1. 通用“中文 + 参考行”双语片源资产（原 calib_rules.py）
# =============================================================

# 1.1 专名/译名统一（错误形式 -> 正确形式，出现即改，无条件）
BILINGUAL_TERMS = {
    # 角色 / 专名（无条件，出现即改）
    # 2026-11-01《How Did You Join Arknights or Endfield?》：ASR 把 "AK, Endfield" 连读成
    #   AKfield/AKMfield。必须登记在**本表**而不是只放 ENDFIELD_BI_TERMS——默认 bi 趟先跑且含裸键
    #   AK→明日方舟，若本表无长键，"AKfield" 会先被咬成「明日方舟field」，endobi 趟再长的键也救不回来。
    "AKMfield": "明日方舟和终末地", "AKfield": "明日方舟和终末地",
    "Aklands": "明日方舟",           # "AK's" 的 ASR 连读形（#1460/#2560）
    "罗弗": "漂泊者", "罗孚": "漂泊者", "罗浮": "漂泊者",          # Rover
    "德妮雅": "达妮娅", "德娜": "达妮娅", "德尼亚": "达妮娅",      # Dena / Denia
    "拉德娜": "达妮娅",
    "艾美斯": "爱弥斯", "伊穆斯": "爱弥斯",                        # Améis / Immus
    "维丽娜": "维里奈", "维莉娜": "维里奈", "维琳娜": "维里奈",   # Verina
    "出奇西亚": "炽霞",                                            # Chixia
    "阳阳": "秧秧",                                                # Yangyang
    "金汐": "今汐", "今析": "今汐",                                # Jinsy
    "陵阳": "凌阳",                                                # Lingyang
    "金阁": "今州",                                                # Gigo/Jingo 地名→今州（Jinzhou 官方译名；不再经“金戈”中转，消除级联金戈->今州隐患）
    "丹金": "丹瑾", "达宁": "丹瑾",                                # Danjin
    "迅哨": "岁主",                                                # Sentinel 岁主
    "哀歌者": "鸣式",                                              # 鸣式（鸣潮怪物）
    "灵魂誓约者": "昭日者",                                        # soul sworn 官方译名
    "光属性": "衍射属性",                                          # spectro 元素
    "沃奥": "阿尔图罗",                                            # Arcturo
    "日雪": "绯雪",                                                # Xueli?  绯雪
    "大建筑师": "残星会会长",                                      # Fractsidus 首领
    "暮羽": "木禺",                                                # Mu-Yu? 木禺
    "战狼": "Crywolf",                                             # 保留英文专名
    "男爵勋爵": "巴伦阁下",                                        # Lord Baron

    # --- 2026-10-24 《致予新世界》音乐会 reaction 二校（官方中文名）---
    # 曲名（书名号键，避免误伤普通语义）；依据见文件头 docstring。
    "《为你的生命奔跑》": "《无所遁藏》", "《为我的生命奔跑》": "《无所遁藏》",
    "《Unwritten》（未书写）": "《若能触及群星》", "《Unwritten》": "《若能触及群星》",
    "《Light》": "《L!!!!ght》",
    "《Dawn Breaker》": "《Dawnbreaker》", "Dawn Breaker": "Dawnbreaker",
    "《Deadline Disco》": "《极限迪斯科》",
    "《世界觉醒》": "《Waking of a World》",
    "《远航星》": "《远航星的告别》",
    # 夏空（Ciaccona）的英文 ASR 变体；同族 Shakona 已由 CONTEXT_MAP 处理。
    "Chiaona": "夏空", "Chiaakona": "夏空", "Chakona": "夏空",

    # --- 2026-08-29 并入：srt_calibrator.py CHINESE_TERM_FIXES ---
    "泰莎不和谐": "残象",                                          # Tacet Discord 整词优先（勿留中间形态，2026-10-20 修）
    "泰莎": "残象",                                                # Tessa -> Tacet -> 残象
    "吉恩": "忌炎",                                                # Jiyan
    "金戈市政厅": "今州市政厅",                                    # Jinzhou City Hall（长词优先）
    "金戈": "今州",                                                # Jinzhou（"金阁"->金戈 会再级联成今州）
    "静乔": "今州",                                                # Jingjo 音译
    "煌龙": "瑝珑", "煌珑": "瑝珑",                                # Huanglong，官方写法瑝珑（2026-08-29 依 wiki 区域名修正）
    "弗雷杜斯": "残星会",                                          # Fractsidus
    "弗拉德": "残星会",                                            # Fractsidus 官方英文名（fix_srt.py 曾作 ->Fractus），取官方中文
    "声诺光盘": "声碟",                                            # sono disc（长词优先）
    "声诺": "声碟",                                                # sono
    # --- 2026-08-29 并入：fix_srt.py TERM_FIXES_ZH（中文行里的英文残留名） ---
    "Jingjo": "今州", "Jingo": "今州", "Gingjo": "今州",
    # ↑ 2026-11-02 目标由 Jinzhou 改为官方中文「今州」。旧值是「拉丁→拉丁」归一化：
    #   中文行被改成 Jinzhou 后，下游 ctx (r"\bJinzhou\b"…) 锚的是**参考行**，而 ASR 参考行
    #   实际写 Jingjo/Jingo（不含 Jinzhou），于是一辈子命不中，中文行永久卡着拉丁残留。
    #   实测：鸣潮 reaction Part 1 #881「是Jinzhou的未来。」。同批 :76 Fraidus→残星会 已是正确范式。
    "Hang Long": "Huanglong", "Wang Long": "Huanglong", "Guang Long": "Huanglong",
    "Fraidus": "残星会", "Fraid": "残星会",                # 2026-10-25 中文行直接归官方中文（英文残留另由 EN_LINE 处理）
    "Gian": "忌炎", "Chizzy": "忌炎",
    "sono 光盘": "声碟", "sono disc": "声碟",
    "Sono 光盘": "声碟", "Sono disc": "声碟",
    # --- 2026-08-29 并入：7月 WW 演唱会脚本通用专名（calibrate_ww/auto_correct） ---
    "short守": "守岸人", "Short守": "守岸人",                      # Shorekeeper 半音译
    "查米莉亚": "椿",                                              # 椿（Camellya）官方中文名，依 md 中英对照
    "基地掉落": "贝斯 drop", "基地下降": "贝斯下降", "那个基地": "那个贝斯",  # bass 误听
    # --- 2026-08-29 依 wiki.kurobbs.com 官方名词校准 ---
    "飞镰之猩": "飞廉之猩",                                        # wiki 声骸/敌人条目作 飞廉之猩（全息战略条目"飞镰"为笔误）
    # 注：fix_srt.py 的 刀疤/疤痕->Scar、Threnodian 等->无冠者 存疑/与 CONTEXT_MAP 冲突，未并入

    # --- 2026-08-29 鸣潮 3.6 片源（蜃云灯影，凡尘剑心）名词级校准 ---
    # 清宵（Qingxiao，3.6 新共鸣者）的 ASR 音译残留
    "青霄": "清宵",
    "Ching Xiao": "清宵", "Chingsha": "清宵", "Ching Sha": "清宵",
    "Chingcha": "清宵", "Chingsho": "清宵", "Chingo": "清宵",
    "Ching": "清宵",                                               # 长 key 先行，裸 "Ching" 殿后（本表按键长降序应用）
    # 玄方城（Xuanfang Hold）
    "Schwanfong Hold": "玄方城", "Shwanfong Hold": "玄方城",
    "Schwan Fong": "玄方城", "Schwangfong": "玄方城",
    "Schwanfong": "玄方城", "Shwanfong": "玄方城",
    "Schwanfang": "玄方城", "Schwangfun": "玄方城",
    # 梦州（Mengzhou）
    "Menjo市": "梦州城", "Mong Joe": "梦州", "Mongjo": "梦州",
    "Menjo": "梦州", "Mjo": "梦州",
    # 其它专名
    "Muyu": "木禺",                                                # 3.5 反派木禺
    "月狐岁主希恩": "岁主心月狐",                                  # Sentinel Sheen the Moon Fox（长词优先）
    "Sheen": "心月狐",                                             # 月狐 Sheen 官方全名 心月狐（独立指代用全名，长词规则先行不会重复）
    "月狐希恩": "心月狐",                                          # 语序调整为官方名
    "希恩": "心月狐",                                              # 旧译名统一为官方全名 心月狐
    "哨兵谐振器": "岁主共鸣者",                                    # Sentinel resonator（岁主共鸣者=官方 Resonator；长键先于 ctx 哨兵->岁主）
    "岁主谐振器": "岁主共鸣者",                                    # 防御性收录：ctx 哨兵->岁主 跑过一遍后的中间形态（谐振器=机翻 resonator）
    "谢恩": "心月狐",                                              # Shane（Sheen 音近变体）
    "Sentinel": "岁主",                                            # 中文行残留的英文 Sentinel
    "虚空法师": "幽客",                                            # Nethermancer（幕间官方名「幽客销残声」）
    "tacet标记": "声痕",                                           # tacet mark 官方名 声痕
    "Tazid": "残象", "tusset": "残象",                             # Tacet Discord 误听（沿 泰莎->残象 先例）
    "Jangghue": "江湖", "Jangghu": "江湖",                         # jianghu 误听
    "Fogville Pagoda": "Fogveil Pagoda", "Fogville Pagota": "Fogveil Pagoda",
    "Fog Val": "Fogveil Pagoda",                                   # 统一为正确英文拼写（官方中文名待核）
    "福格维尔宝塔": "Fogveil Pagoda", "福格维尔巴戈塔": "Fogveil Pagoda",  # 同上，音译残留
    "福格维尔皮戈塔": "Fogveil Pagoda",                            # 同上（Fogville Pigota 变体）
    # --- 2026-08-30 清宵与景燃 3.6 主线 Reaction 片源 校准新增 ---
    "清沙": "清宵",                                                # Ching Sha
    "清筱": "清宵",                                                # Ching Shiao
    "施万丰（玄方城）": "玄方城",                                  # 双重写法去重（长 key 先行）
    "施万丰": "玄方城",                                            # Schwanfong 音译残留
    "Schwanfung": "玄方城", "Schwanfun": "玄方城",                 # Schwanfong Hold 变体
    # --- 2026-10-04 英文原声 3.7 反应片：Schwan(=Xuan 玄) 音译残留（施万/施旺/方旺 系）---
    "施万方堡": "玄方城", "施旺丰堡": "玄方城", "施万丰堡": "玄方城",
    "施万方": "玄方", "施旺丰": "玄方",
    "施万": "玄方", "施旺": "玄方", "方旺": "玄方",
    # 英文原声残留：Nexus 未被谷翻，且被裸键"exus->隧者"误咬成"N隧者"（长键 Nexus 先行即可）
    "Nexus": "枢纽", "nexus": "枢纽",
    # 英文原声残留（2026-10-04 3.7 反应片）：谷翻整词未译，中文行内留英文专名
    "Swaming": "锁暝", "Swarming": "锁暝", "Mhjo": "梦州", "mjo": "梦州",
    "Tacet": "残象", "Arbiter": "御者",   # 2026-10-05 用户裁决：Arbiter 官方中文=御者（原误沉淀"仲裁者"；与韩语模式 어자->御者 及 3.7 精校报告一致）
    # 2026-10-04 二次校准补：英文整词残留（官方中文已核）
    "Taca Discord": "残象", "Tacit Discord": "残象", "Tacet Discord": "残象",
    "Wither Waves": "鸣潮", "Withering Waves": "鸣潮",
    "Schwang": "玄方", "Schwan": "玄方",
    "Mongo": "梦州",                                               # Mongjo/Mong 误听
    "Nethermancer": "幽客",                                        # 中文行残留英文
    # 2026-10-05 第二部 3.7 reaction 片（I Wasn't Ready...）二次校准：中文行英文/生僻错形残留
    "Nexus Fox": "天罗狐影", "枢纽 Fox": "天罗狐影", "枢纽Fox": "天罗狐影",  # 长键先于 Nexus->枢纽
    "Prolog": "序章",                                              # 序章（#5147）
    "Evedroping": "偷听",                                         # eavesdropping 漏听（#2537）
    "Wibes": "感觉", "wibes": "感觉",                             # vibes 错拼（#5739）
    "Thingabob": "那玩意儿", "thingabob": "那玩意儿", "abobb": "玩意儿",  # thingamabob 断词（#5731/#5733）
    "Autopet": "机关宠物", "autopet": "机关宠物",                  # 玄方城机关宠物维修（#1908）
    "shling鸟": "玄翎雀",                                         # Xuanling/Lling bird（#5455；2026-11-10 二校改官方名 玄翎雀，旧目标「天鹅灵鸟」废止）
    "玄方城hold": "玄方城",                                       # Schwanfong Hold 中英混合残留
    "玄方fangjo": "玄方城", "玄方fang": "玄方城",                 # 长键先行
    "玄方 Fong": "玄方", "玄方f": "玄方",                         # 玄方碎形（#3303/#7174）
    "Shrung": "玄方城",                                           # miniature Schwan(fong Hold) 跨行残段（#5680）
    "唐唐宁": "同宁",                                             # Tang Tang Ning 谷翻（长键先于"唐宁"，防单遍残留"唐同宁"，#200）
    # 2026-10-04 补全长键：裸键"枯萎"（学习库 bi|枯萎->鸣潮）会抢先命中，把"枯萎的波浪/枯萎波浪/
    #   枯萎浪潮"咬成"鸣潮的波浪/鸣潮浪/鸣潮潮"；补这些长键（长键先行）即可整体归"鸣潮"。
    "枯萎的波浪": "鸣潮", "枯萎浪潮": "鸣潮", "枯萎波浪": "鸣潮",
    "枯萎之波": "鸣潮", "枯萎浪": "鸣潮",
    "枯萎波": "鸣潮",                                              # Withering Wave -> Wuthering Waves（注意 枯萎 作动词"wither"时不改）
    # --- 2026-09-01 "This is the most I've ever cried over a game"(鸣潮) 校对沉淀 ---
    "西罗诺德": "鸣式",                                            # Thronodian（英文 asr 变体误音译 -> 官方名 鸣式）
    "伊梅思": "爱弥斯",                                            # Imeth/Immeth（asr 变体 -> 爱弥斯）
    # --- 2026-10-16 鸣潮同人番组「二回目のエイメス潮汐任務」二次校准（名词漏校/漏译修正）---
    "埃姆斯": "爱弥斯", "海姆斯": "爱弥斯", "Emes": "爱弥斯",       # Aemeath/爱弥斯（标题「エイメス潮汐任務」）ASR 音译残留：译文 Emes/海姆斯/埃姆斯 三种写法统一回官方名 爱弥斯
    "石头调整任务": "潮汐任务", "石钻任务": "潮汐任务",             # 調石任務 为 潮汐任務(chōseki) 同音 ASR 误识，bing 按字面直译错；依标题「潮汐任務」订正
    "拉海洛伊": "拉海洛",                                          # Lahai-Roi（2026-09-09 依官方对照表/wiki 修正：官方中文=拉海洛，原误统一为"拉海罗伊"）
    "拉海罗伊": "拉海洛",                                          # 同上：旧沉淀目标"拉海罗伊"收敛回官方名（长键"拉海洛伊"先行）
    "西吉鲁姆": "辛吉勒姆",                                        # Sigilum（asr 变体，官方中文 辛吉勒姆，2026-09-10 依官方3.1内容说明/鸣潮助手修正）
    "埃克斯德": "隧者",                                            # Exorder（音译残留 -> 官方中文 隧者，依库街区/鸣潮助手图鉴）
    # --- 2026-09-01 同一鸣潮片源二次精修(fixin round2) 补充沉淀 ---
    "狄奥德": "鸣式",                                              # Theodian（asr 变体 -> 鸣式）
    "Exoriders": "隧者", "Exorider": "隧者",                       # Exostrider 复/单数变体（中文残留英文时统一为官方名 隧者）
    "舰队雪花": "飞行雪绒", "雪绒舰队": "飞行雪绒",              # Fleet Snowfluff = 飞行雪绒（爱弥斯歌手化名，2026-10-24 依萌娘百科/Apple Music《飞行雪绒》EP 修正旧音译）
    "舰队雪绒": "飞行雪绒", "舰队雪绒花": "飞行雪绒",             # 长词优先；裸"雪绒/雪花/雪绒花"是普通词勿在此改
    # --- 2026-09-04 THIS_IS_CRAZY_Hsin（Suoming Gameplay Reaction，鸣潮 3.6）校准新增 ---
    "苏明": "锁暝", "苏凌": "锁暝", "苏舒明": "锁暝",              # Suoming 锁暝（3.6 共鸣者，ASR 音译残留）
    "Suming": "锁暝", "Suling": "锁暝", "Schuming": "锁暝", "Summit": "锁暝",
    "静然": "景燃", "晶隆": "景燃", "Jing Rang": "景燃", "Jingron": "景燃",  # Jing Ran/Jing Rang/Jingron = 景燃
    "丁然": "景燃", "riping ran": "景燃",                          # Ding Ran / riping ran（ASR 变体）= 景燃
    "Yangyang": "秧秧",                                          # 秧秧 英文残留
    "Yang Yang": "秧秧",                                         # 2026-11-09 二次校准：分写英文残留（本片 cue2131/2357），仅作用于中文行
    "Wua": "鸣潮",                                              # Wuthering Waves 误听
    "Mango": "梦州",                                            # Mengzhou 误听（沿 Mongo->梦州 先例）
    "莲吉": "恋次",                                             # Renji（死神）官方中文 恋次
    # --- 2026-09-09 Streamers React to Hsin & Suoming Gameplay Leaks（鸣潮 3.7 心月狐/锁暝 英文谷歌翻译 Reaction 片）首轮验证 ---
    # 首轮 10 处改动全由既有映射覆盖：希恩/Sheen->心月狐、swimming->锁暝、枯萎波(blight wave)->鸣潮、
    # 哨兵->岁主；用户确认 blight wave 保持「鸣潮」不改成 枯萎浪。
    # 二次校准（检索官方中文后新增，2026-09-09）：
    "弗罗洛娃": "弗洛洛", "弗罗洛瓦": "弗洛洛",                    # Frolova（鸣潮湮灭角色，所属残星会）官方 弗洛洛
    "Frolova": "弗洛洛", "Phrolova": "弗洛洛",                     # 英文残留（wuthering.gg 作 Phrolova）
    "Chisa": "千咲", "CHISA": "千咲",                              # Chisa=千咲（英文恰为千咲罗马音；解弦之眼/剪刀角色）
    "恶魔杀手": "鬼灭之刃",                                        # Demon Slayer 官方中文 鬼灭之刃
    "无限城堡": "无限城",                                          # Infinity Castle（鬼灭之刃场景）官方 无限城
    "域扩展": "领域展开",                                         # domain expansion（咒术回战）官方 领域展开；不设"域展开"键，避免与结果"领域展开"的子串级联
    # --- 2026-09-05 This_is_the_most_Ive_ever_cried_over_a_game（鸣潮 3.x 拉海罗伊/星炬学院片）三次校准沉淀 ---
    # 鸣式(Threnodian) ASR/机翻变体全覆盖（西罗诺德/狄奥德 已有）
    "狄奥迪亚": "鸣式", "瑟罗诺德": "鸣式", "瑟罗诺迪安": "鸣式",
    "瑟罗诺迪亚": "鸣式", "斯罗诺多尼亚": "鸣式",
    "索罗诺德人": "鸣式", "索罗诺德": "鸣式",
    "索诺德人": "鸣式", "索诺德": "鸣式",
    "Thronodian": "鸣式", "Thrronodonian": "鸣式", "Thronodonian": "鸣式",
    "Thenodian": "鸣式", "Theodian": "鸣式", "Zenodian": "鸣式", "Tenodian": "鸣式",
    # 鸣式·阿列夫一（ALF1/Alf one/Alfan，官方中文=阿列夫一，虚无鸣式/黑洞形象；2026-09-10 依官方访谈/库街区修正，"阿尔凡"沉淀作废）
    # 注意键序：Alf one/ALF one/ALF 1/ALF1 长键先行，防"Alf"裸键咬出半截
    "阿尔夫": "阿列夫一", "ALF1": "阿列夫一", "LF1": "阿列夫一",
    "阿尔凡": "阿列夫一", "Alfan": "阿列夫一",
    "阿尔夫一人": "阿列夫一", "阿尔夫一定": "阿列夫一", "阿尔法之一": "阿列夫一",
    "ALF one": "阿列夫一", "Alf one": "阿列夫一", "ALF 1": "阿列夫一",
    "ALF": "阿列夫一", "Alf": "阿列夫一",
    # Exostrider 变体（官方中文 隧者，2026-09-08 依库街区/鸣潮助手图鉴确认后统一）
    "Exorder": "隧者", "Exorrider": "隧者",
    "Exo Strider": "隧者", "exor strider": "隧者",
    # Sigilum（黑色机兵/声骸）变体 -> 辛吉勒姆（官方中文，2026-09-10 依官方3.1内容说明/鸣潮助手修正）
    "Sigilum": "辛吉勒姆", "Sigulum": "辛吉勒姆", "Sigilm": "辛吉勒姆", "Sigilium": "辛吉勒姆",
    "Sidelum": "辛吉勒姆", "西古鲁姆": "辛吉勒姆",
    # 爱弥斯(Imeth) ASR 变体补全（伊穆斯 已有）
    "伊莫斯": "爱弥斯", "伊梅斯": "爱弥斯", "伊茅斯": "爱弥斯",
    "阿莫斯": "爱弥斯", "阿梅斯": "爱弥斯",
    "Immeth": "爱弥斯", "Ameth": "爱弥斯",
    # 拉海洛(Lahai-Roi) 地名变体（长键先行，"拉希罗"殿后）；2026-09-09 目标由"拉海罗伊"修正为官方"拉海洛"
    "拉希罗伊": "拉海洛", "拉希罗": "拉海洛",
    "莱艾·罗伊": "拉海洛", "莱伊·罗伊": "拉海洛",
    "La Hairoy": "拉海洛", "La Hyroy": "拉海洛", "La Hyro": "拉海洛",
    # 飞行雪绒(Fleet Snowfluff) 英文残留（长键先行；2026-10-24 修正旧音译"弗利特·斯诺芙"）
    "Fleet Snowfluff's": "飞行雪绒的", "Fleet Snowflow's": "飞行雪绒的",
    "Fleet Snowfluff": "飞行雪绒", "Fleet Snowflow": "飞行雪绒", "Fleet Snowfl": "飞行雪绒",
    # 其它专名/术语
    "Syncrate": "同步率", "Solaris": "索拉里斯",
    "Strider Gate": "隧门", "Stridergate": "隧门",
    "逆雨": "溯洄雨", "风化波浪": "鸣潮", "风化浪潮": "鸣潮", "风化浪": "鸣潮", "星火学院": "星炬学院",
    # --- 同片三次校准补充（Resonator/Lament/Astrite/Crownless 等鸣潮官方词 + ASR 变体）---
    "风化波": "鸣潮",                                              # Weathering Wave 系列
    "路虎": "漂泊者", "漫游车": "漂泊者",                          # Rover 被译成汽车品牌/火星车
    # --- 2026-11-08 Jadealy《鸣潮》3.8 前瞻 Reaction 片二校回灌 ---
    #   键一律取中文行实际形态、整串唯一且非通用词；官方依据写行尾（T1=片内官中台词 cue）。
    "海浪版": "《鸣潮》版本",                    # T1 #43「欢迎来到《鸣潮》3 .」；wuth ering waves version
    "Mother ing Waves": "《鸣潮》",             # T1 #43；Wuthering Waves 的 ASR 误听残形
    "VU VA": "鸣潮",                            # T1 #43；WuWa 的 ASR 误听残形
    "wuva livest ream": "鸣潮直播",             # T1 #44「8版本前瞻通讯」；WuWa livestream
    "火星车头": "漂泊者头",                     # T1 #42/#50「漂泊者」；rover head
    "Brand t": "布兰特",                        # T2 Brant=布兰特（bilingual.py:1096）；ASR 断词
    "卢伊拉": "洛瑟菈",                         # T2 Lucilla=洛瑟菈（bilingual.py:450）
    "同步员": "同步者",                                            # synchronist 统一
    "异能跨步者": "隧者", "跨行者": "隧者",                  # exor strider 机翻/简写
    # 2026-09-22 补：Exostrider 的**子词直译**机翻形态（Exo=外骨骼 + strider=行者/跨步者）。
    # 此前只收了音译/简写错形（异能跨步者/跨行者/步行者），漏了这条最高频的直译，导致校准后仍留"外骨骼行者"。
    # 键序无需手排（_replace_report 自动长键优先），但**必须补复数形态**防短键咬出"…们"。
    "外骨骼行者们": "隧者", "外骨骼行者": "隧者",
    "外骨骼的行者": "隧者", "外骨骼跨步者": "隧者",
    "小伊斯": "小爱弥斯", "利莫斯": "爱弥斯",                      # little Ith / Limoth
    "Imeth": "爱弥斯", "IMATH": "爱弥斯", "IMth": "爱弥斯", "IMAD": "爱弥斯",
    "Sigon": "辛吉勒姆",                                           # Sigilum 变体
    "Strider 门": "隧门", "strider门": "隧门", "跨门": "隧门", "跨步门": "隧门",
    "Exor": "隧者",                                              # 裸词残留（Exostrider 不含子串 Exor，安全）
    "skyarch": "天槎",  # Sky Ark=天槎空间站（3.1 稷廷科研站）；旧目标"天弧"为误沉淀，2026-10-27 依官方 3.1 内容说明修正
    "academyy": "学院", "N'avorora": "恩沃拉",
    "Hanglo": "瑝珑",                                              # Huanglong 误听
    "广珠": "广州", "坎特雷拉": "坎特蕾拉", "空隙物质": "虚空物质",
    "Amorei": "OMORI",                                             # 2023 催泪游戏 Omori 误听
    # --- 2026-09-05 补漏（伊思/Rover 残留）---
    "伊思": "爱弥斯",                                              # Ith（#563 伊思的房子）
    "Rover": "漂泊者",                                             # 中文行英文残留（#23/#561）
    # --- 2026-09-08 二次校准沉淀（Thanks La 声优讨论片 + 官方名词检索）---
    # Buling=卜灵（鸣潮 2.4+ 角色，梦州方士；官方中文名依 wiki/genshin-builds 配音表核实；
    # 中文配音 张晔，英文配音 Elizabeth Chu。本片正文未出现，沉淀供后续片源）
    "Buling": "卜灵", "布灵": "卜灵",
    # --- 2026-09-08 NIKKE Player Reacts to WW's BEST Story Cinematics（鸣潮三短片 Reaction）新增 ---
    "呼啸波": "鸣潮",                                              # Wuthering Waves 直译
    "阿马斯": "爱弥斯",                                            # Amath = Aemeath（3.1 共鸣者）
    "卡西亚": "卡提希娅",                                          # Carthia = Cartethyia（2.2 共鸣者）
    "哨兵 Chuy": "岁主·角",                                        # Sentinel Chuy = 岁主角（今州岁主，官方英文 Jué）
    "哨兵 Ju'e": "岁主·角",                                        # Sentinel Ju'e = 岁主角
    "金州爵": "今州角",                                            # Jinzhou Jue（"爵"为"角"音译，整词优先）
    "Carthea": "卡提希娅",                                         # Carthea 王国 = 卡提希娅
    "Exos Rider": "隧者",                                         # Exos Rider = Exostrider 变体（官方中文 隧者）
    "她得救的人": "她拯救的人",                                    # the people she's saved
    "年龄已定": "岁月已定",                                        # age has decreed（岁月已注定）
    "Strider": "隧者",                                             # 《拯救》短片爱弥斯唤醒的隧者机甲（Exostrider 简称）
    # --- 2026-09-10 Wuthering Waves 3.1 Story Reaction (Stream #2) 二次校准沉淀 ---
    # 长键不完整残留根因：首轮只有部分变体键，导致 "Immethy"->"爱弥斯y"、"Exordder"->"隧者dder"、
    # "Exorid"->"隧者id"、"exor striders"->"隧者s" 这类半截替换；本块补全变体键。
    "Immethy": "爱弥斯", "Imethy": "爱弥斯",                       # Aemeath 变体（长键优先，防 Immeth 键先咬出"爱弥斯y"）
    "Exordder": "隧者", "Exorid": "隧者",                          # Exostrider ASR 变体
    "exor striders": "隧者",                                       # 复数键（长键优先，防 exor strider 键咬出"隧者s"）
    "拉罗伊": "拉海洛",                                            # Lahai-Roi 碎片（拉海-罗伊被机翻截断）
    "海罗伊": "拉海洛",                                            # Lahai-Roi 缺"拉"前缀截断（#18628/21408/25153/25543；长键"拉海罗伊"先行不冲突）
    "Thrronodian": "鸣式", "Thrronodians": "鸣式",                 # Threnodian 双r ASR 变体（含复数）
    # --- 2026-09-10 二次校准（依官方中文检索修正）新增 ---
    "虚空风暴潮": "虚质磁暴", "虚质风暴潮": "虚质磁暴",             # 长键先行；官方词条=虚质磁暴（2026-10-24 依萌娘百科/官方剧情文本修正旧目标"虚质风暴"）
    "虚空风暴": "虚质磁暴", "虚质风暴": "虚质磁暴",                 # Voidstorm 官方中文=虚质磁暴（拉海洛区域性海蚀现象）
    "星游学园": "星炬学院",                                         # Star Tour Academy = 星炬学院 ASR 变体（#15214）
    "Laai Roy": "拉海洛",                                           # Lahai-Roi ASR 变体（#4278 Laai Roy is my responsibility）
    # --- 2026-10-12 WuWa 3.3 Story Reaction（I must save Aemeath!，10653 cue）二次校准沉淀 ---
    # 官方依据：库洛 3.3 公告 mc.kurogames.com/news/4551（绯雪=特别对策组唯一成员、隧者计划、
    # 黯原/恒黯之原、罗伊神话中赫龙格被巴德尔封印）、官方英文站（Lahai-Roi = Solaris's
    # Extreme，situated beneath the Roya Frostlands，Spacetrek Collective's Startorch
    # Academy）、NGA 拉海洛考据帖
    # （巴德尔=万米最大隧者/太阳朔尔化身，与灭世邪祇赫龙格终焉之战）、日文 wiki 用语翻译
    # （绯雪=Hiyuki、鸣式=Threnodian）。
    # Lahai-Roi 本片谷翻错形：ASR "La Hyroy/Lyroy" 被谷翻拆成"拉·伊鲁罗伊"等碎片
    "拉·伊鲁罗伊": "拉海洛", "拉·伊鲁伊": "拉海洛", "拉·伊鲁罗": "拉海洛",
    "海洛伊": "拉海洛", "拉伊罗伊罗伊": "拉海洛", "拉伊罗": "拉海洛",
    "莱罗伊": "拉海洛",                                             # 双语表补录（韩语表虽有同名键，双语模式勿依赖他表）
    # ASR "the demer" 谷翻"德默尔"=黯原（Dimmr Plains，#573 既有沉淀：3.3 官方新地区）。
    # ⚠ 教训：wuthering.gg 第三方地图 zh-Hans 页名"迪姆平原"系机翻，一度误导本轮判为
    # "迪姆平原"，与 #573 官方沉淀冲突后被 ENTITIES 注册冲突检查拦下纠正——第三方站
    # 页名不可直接当官方译名，须以库洛公告/游戏内地名为准。
    "德默尔": "黯原",
    # Lahai-Roi 谷翻独立形"拉伊罗伊"（长键须先于"拉伊罗"应用，否则短键咬出"拉海洛伊"畸形；
    # #1062/1148/1170/5683 实测）。同理"海洛伊"的后缀粘连形须先行，防替换后残留"河/气象"：
    "拉伊罗伊": "拉海洛", "海洛伊河": "拉海洛", "海洛伊气象": "拉海洛气象学",
    # Exor Rider 谷翻形：整词"艾克索/埃克索 骑士"->隧者（#396/4015，参考行 exor rider 语境；
    # 裸"骑士"戒律禁入，走 CONTEXT_MAP \brider\b 锚定 #2269）
    "艾克索骑士": "隧者", "埃克索骑士": "隧者",
    # '日向/日行'与 ASR 粘连字的组合（'日树/日纪'先例 #523；组合词无通用歧义，且 BILINGUAL
    # 先于 CONTEXT_MAP 应用，长键先行消化后 ctx 的裸"日向"不再误命中）：
    "日向树": "绯雪", "日向月": "绯雪", "日向梦": "绯雪", "日向木": "绯雪",
    "日行城": "绯雪", "日向城": "绯雪",
    # 特别对策组：3.3 公告官方组织名；ASR "Special Response Force" 谷翻"特种反应部队"
    "特种反应部队": "特别对策组",
    # Thrronodonian：本片 ASR 比先例键 Thrronodian(#448) 多一音节，谷翻当国名"索罗诺多尼亚"；
    # 主播复述剧情用的是类别名 Threnodian=鸣式（"封印隧门之外的那只鸣式"即官方设定中被
    # 巴德尔封印于黯原的赫龙格；个体名主播未念出，勿擅自升级为专名）
    "索罗诺多尼亚人": "鸣式", "索罗诺多尼亚": "鸣式",
    # Nastasha 谷翻错形（诺斯塔系）
    "诺斯塔希亚": "娜斯塔霞", "诺斯塔希": "娜斯塔霞",
    # N'ora/Nav'ora：库内 3.2 片 confirmed "N'vora"->恩沃拉，本片同角色 ASR 变体随库内目标
    "N'ora": "恩沃拉", "Nav'ora": "恩沃拉",
    # Exo Strider 整词错形："隧者游侠"仅 Exo Strider 语境组合，安全裸键
    "隧者游侠": "隧者",
    # Strider Gate 纯音译组合（"斯特赖德门"明确组合可裸键；裸"斯特赖德"走 ctx 防人名误伤）
    "斯特赖德门": "隧门",
    "舰队雪毛": "飞行雪绒",                                          # Fleet Snowfluff（#18043；2026-10-24 修正旧音译）
    # --- 2026-10-12 WUWA CONCERT WATCHPARTY REACTION（演唱会观看派对反应片，3470 cue）校准新增 ---
    # Lahai-Roi 谷翻"拉伊鲁瓦/拉·伊鲁瓦"形：长键须先于"鲁瓦->漂泊者"（Rover ASR 变体键），
    # 否则"拉伊鲁瓦"被咬出"拉伊漂泊者"畸形（#392/2752/2753 实测）：
    "拉伊鲁瓦": "拉海洛", "拉·伊鲁瓦": "拉海洛",
    # Septimont 官方=七丘（库洛 2.4 公告 mc.kurogames.com/news/2744「全新区域：七丘」）；
    # 长键先于学习库"塞普蒂蒙->七丘"，防残尾"七丘特"（#392 实测）：
    "塞普蒂蒙特": "七丘",
    # Dennia ASR 变体 Daniel 谷翻"丹尼尔"：长键先于"丹尼->达妮娅"，防残尾"达妮娅尔"（#2288/2300/2343/2594 实测）：
    "丹尼尔": "达妮娅",
    # Wua 谷翻整体形"吴阿"：长键先于 ctx 裸"吴->鸣潮"，防残尾"鸣潮阿"（#434 实测）：
    "吴阿": "鸣潮", "武阿": "鸣潮",
    # 银林（Yinlin 谷翻错形，与"尹琳->吟霖"同类，#664 漏校）：
    "银林": "吟霖",
    # resonator 机翻"共振器"（学习库已有"谐振器->共鸣者" confirmed，同类补齐，#541 漏校）：
    "共振器": "共鸣者",
    "共振者": "共鸣者",                                             # 共振≠共鸣 错字变体（#827 resonator->共振者）
    "王峰堡": "玄方城", "王方堡": "玄方城",                       # Schwanfong Hold 机翻错形（#976/#1258/#1333/#1189；不碰"王方"本人）
    # Lupa ASR 错形"露巴"（参考行 Luba，#2579 漏校；"露巴"非常用词裸键安全）：
    "露巴": "露帕",
    # Wuthering Waves ASR "Weathering wave" 谷翻"耐候波浪"（#2787；"耐候波浪"裸键安全）：
    "耐候波浪": "鸣潮",
    # Flova 英文残留（拉海洛漫游车"弗洛瓦·达妮娅·西格莉卡号"命名三人组，#3184；裸键安全）：
    "Flova": "弗洛洛", "弗洛瓦": "弗洛洛",
    # --- 2026-10-12 演唱会反应片二次校准（官方中文逐句复查，英文残留/ASR 变体补漏）---
    "Shorekeeper": "守岸人",                                       # #451/474 谷翻保留英文（Shortkeeper 变体已有键，本尊补齐）
    "Ith": "爱弥斯",                                               # #597 "sell as much as Ith" 谷翻保留英文（CONTEXT \bIth\b 只锚中文"伊斯"，补英文残留）
    "Kultcharo": "卡卡罗", "Kolaro": "卡卡罗", "Kcharo": "卡卡罗",
    "Karo": "卡卡罗",                                              # Calcharo 卡卡罗 ASR 变体族（#609/611 长键先行防短键"Karo"咬残）
    "Mangzo": "梦州",                                              # #625 "part of the not Mangzo region"=非梦州地区（Mengjo/Mongjo 同族）
    "PGR": "战双帕弥什",                                           # #633/635/638/648/725 谷翻保留缩写（官方中文全称；#641 被谷翻误译"研究生"走侧车）
    "Wooa": "鸣潮",                                                # #933 WuWa ASR 双 O 变体
    "Immoth": "爱弥斯",                                            # #994 "my bike was playing the Immoth songs"（Imeth 同族 ASR）
    "VUA": "鸣潮",                                                 # #1672 "the actual like VUA concert tour"（WuWa ASR 变体，LA/新加坡巡演语境）
    "Zenless": "绝区零",                                           # #822/896/921/1541 绝区零官方英文名（用户规则：绝区零）
    "Ginsi": "今汐",                                               # #334 Jinhsi ASR（"姜吉"=Gingi 误译走侧车）
    "Dingron": "景燃",                                             # #346 Ding Ran ASR 粘连（"可惜我还没有景燃"抽卡语境）
    "Jiyan": "忌炎",                                               # #661/664 中文行英文残留改官方中文（原沉淀 Gian->Jiyan 保留英文，二次校准统一改中文）
    "Encore": "安可",                                              # 三轮补漏：鸣潮角色官方中文=安可（#2440"她太年轻不能工作"=小孩子角色铁证、
                                                                   #   #2951/2952；zh 行均为角色指代，英文"再来一个"义在中文行未出现）
    # ⚠ 勿收 "Woola"->鸣潮：#1139 "the Woola character" 指代不明（聊配音角色，非 WuWa 本体），留观
    # --- 2026-09-08 NO ONE CAN CONTROL THEMSELVES!（WuWa 3.6 Story Streamers REACTIONS）校准新增 ---
    # 玄方城(Schwanfong Hold) ASR/英文残留变体（3.6 梦州玄方城）
    "Shranong": "玄方城", "Swanfong": "玄方城", "Fong Hold": "玄方城",
    "Swanfang": "玄方城", "Swan Fang": "玄方城",
    # 吟霖(Yinlin，今州共鸣者，本片以“精灵女王”登场) ASR 变体残留
    "Yin Lingling": "吟霖", "Yin Llin": "吟霖", "Yian Llin": "吟霖",
    # 清宵(Ching Sha/Ching Xiao) ASR 变体残留
    "Chincha": "清宵", "Chimcha": "清宵",
    # 残象(Tacet) ASR 变体
    "Tuset": "残象",
    # --- 2026-09-09 I_Was_Wrong_Completely_About_Wuthering_Waves（鸣潮 椿伴星任务 Reaction 片）校准新增 ---
    # 椿（Camellya，黑海岸执花）ASR/机翻变体 -> 官方中文名 椿（查米莉亚 已有）
    "Chamellia": "椿", "Chameleia": "椿", "Chamelia": "椿", "Camila": "椿", "卡米拉": "椿",
    "茶花属": "椿", "茶花": "椿",
    # 漂泊者（Rover）ASR 误听变体（Ruva/Ruver/鲁瓦/鲁弗）
    "Ruva": "漂泊者", "Ruver": "漂泊者", "鲁瓦": "漂泊者", "鲁弗": "漂泊者",
    # 守岸人（Shorekeeper）ASR/机翻变体
    "Shawkeeper": "守岸人", "肖战守护者": "守岸人", "岸边管理员": "守岸人",
    "海岸警卫队": "守岸人", "海岸守护者": "守岸人", "做空者": "守岸人", "岸守": "守岸人",
    # 残象（Tacet Discord）变体
    # 2026-10-28：裸键「塔塞特」会把 tacet mark 咬成「残象标记」，删除并补长键
    # 「塔塞特标记」→声痕（《INSANE LORE DROPS》737 cue #73 实证）。
    "塔塞特人": "残象", "塔塞特标记": "声痕", "Tacet 不和": "残象",
    # 泰缇斯（Tethys 系统，守岸人辅助的运算核心）
    "Tethus": "泰缇斯", "teth系统": "泰缇斯系统",
    # 执花（Bloombearer，黑海岸成员称号）
    "布隆伯": "执花", "布卢姆伯": "执花", "绽放者": "执花",
    # 恒星矩阵（Stellar Matrix）
    "斯特拉矩阵": "恒星矩阵",
    # 黑海岸（Black Shores）机翻变体
    "布莱克酒店": "黑海岸", "黑色海岸": "黑海岸", "黑岸": "黑海岸",
    # 鸣潮（Wuthering Waves）ASR 误听
    "Wolvering Waves": "鸣潮", "翼波": "鸣潮",
    # --- 2026-10-27 ABRAXAS 世界观 PV 反应片（Rubee，173 cue）二校沉淀 ---
    # 官方中文 PV「超验TRANSCENDO」；谷翻把 lore trailer 误作传说/领主预告片、
    # The Land Before Time 误作「土地时间之前的东西」。
    "传说预告片": "世界观预告片",
    "领主预告片": "世界观预告片",
    "较低的拖车": "世界观预告片",
    "土地时间之前的东西": "《小脚板走天涯》",
    "时间之前的东西": "《小脚板走天涯》",
    # --- 2026-09-15 二次校准（检索官方中文后新增，鸣潮 TCG 开包片沉淀）---
    # 燎照之骑（Inferno Rider，归墟港市怒涛级残象；官方中文依萌娘百科+官网《威胁集录》）
    "Inferno Rider": "燎照之骑", "地狱骑士": "燎照之骑", "炼狱骑士": "燎照之骑",
    # 辉萤军势（Lampylumen Myriad，虎口山脉怒涛级残象；官方中文依鸣潮WIKI声骸页）
    "Lampylumen Myriad": "辉萤军势", "Lampylumen": "辉萤军势", "Lampy Lumen": "辉萤军势",
    "Lampulum": "辉萤军势", "兰皮流明": "辉萤军势", "灯管腔": "辉萤军势", "兰普拉姆": "辉萤军势",
    # 桃祈（Taoqi，天工边防事务负责人）ASR 变体
    "Taoi": "桃祈", "陶伊": "桃祈",
    # --- 2026-09-09 同片二次校准（检索官方中文后新增）---
    # 安可（Encore，黑海岸客卿）ASR 误听（Enrew）
    "Enrew": "安可", "恩鲁": "安可",
    # 落香村（Pedalfall Village，椿被救的村庄；官方中文依鸣潮助手图鉴/剧情）
    "踏板落村": "落香村", "Pedalfall Village": "落香村", "Pedalfall": "落香村",
    "Pedaphor村": "落香村", "Petal Fall": "落香村",
    # 噬亡星（Necrostar，黑海岸黑洞；官方中文依库街区 wiki）
    "死灵星": "噬亡星", "Necrostar": "噬亡星",
    # 调律大厅（Modulation Hall，黑海岸设施；官方中文依库街区 wiki）
    "调制大厅": "调律大厅", "modulation hall": "调律大厅",
    # --- 2026-09-10 ARC WuWa Ep.7（she just want to live）二次校准新增：星炬学院角色官方中文 ---
    # 西格莉卡（Sigrika，星炬学院新生/返归者；官方中文依库街区，英文 Sigrika/西格莉卡已有名词表）
    "Sigi": "西格莉卡", "Sigy": "西格莉卡", "Siga": "西格莉卡", "Sigria": "西格莉卡",
    "西吉": "西格莉卡", "西加": "西格莉卡", "锡格利亚": "西格莉卡", "西格利亚": "西格莉卡", "西格琳卡": "西格莉卡",
    # 洛瑟菈（Lucilla，星炬学院校长；官方中文依库街区 wiki/3DM/sina 确认）
    "Lucilla": "洛瑟菈", "露西拉": "洛瑟菈", "卢西拉": "洛瑟菈",
    # --- 2026-10-30 鸣潮 3.5 主线 reaction（8126 cue，英语原声+谷翻）校准沉淀 ---
    # 华胥院(Huashu Academy，3.5 玄方地界官方区域名)：裸键「学院→星炬学院」会把
    #   「胡阿什学院」咬成「胡阿什星炬学院」，长键先行（5 字 > 2 字）即可拦住。
    "胡阿什学院": "华胥院", "胡阿克斯学院": "华胥院", "胡灰乌学院": "华胥院",
    "玄方之地": "玄方地界", "洛西拉": "洛瑟菈",
    # 绯雪（Hiuki/Hyuki，星炬学院巫女，官方 ja 名=ひゆき；英文形残留入表）+ 中文机翻"希希"
    "Hiuki": "绯雪", "Hyuki": "绯雪", "希希": "绯雪",
    # 千咲（Chisa，星炬学院/解弦之眼；已有英文键，补中文机翻形态）
    "奇莎": "千咲", "奇萨": "千咲",
    # 达妮娅（Denia/Dana，星炬学院学生；"达纳"为 Dana 中文机翻）
    "达纳": "达妮娅", "达娜": "达妮娅",
    # 鸣式(Threnodian) 更多 ASR 变体（Turnodian/Therodian，本片英文原形出现）
    "图尔诺迪安": "鸣式", "图尔诺迪亚": "鸣式", "塞罗德": "鸣式",
    # --- 2026-09-10 How is this POSSIBLE - WuWa 3.3 Story Quest Highlight 校准新增 ---
    # 官方中文依库洛官网 3.3 版本公告《自星海尽处回响》(Reverbs From the End of Galaxies) 核实：
    # 第三章·第五幕《昨夜群星》Starlights from Yesterdays / 幕间《愿系铃中》Wishes in the Bell
    # 深空联合 Spacetrek Collective / 星炬学院 Startorch Academy / 地下黯原 Dimmr Plains
    # 绯雪 Hiyuki / 爱弥斯 Aemeath / 达妮娅 Denia / 洛瑟菈 Lucilla / 隧者 Exostrider
    # 绯雪(Hiyuki) ASR/机翻变体（"桧雪""日纪""日树""胡姬""胡基"）
    "桧雪": "绯雪", "日纪": "绯雪", "日树": "绯雪", "胡姬": "绯雪", "胡基": "绯雪",
    "Huki": "绯雪", "kiuki": "绯雪",                                 # 英文/ASR 残留（kiuki=dark Hiuki）
    # 爱弥斯(Aemeath) ASR 变体（Imus/Imameth/Himoth 为本片新见）
    "伊玛美斯": "爱弥斯", "伊美斯": "爱弥斯", "希莫斯": "爱弥斯",
    "Imus": "爱弥斯", "Imameth": "爱弥斯", "Himoth": "爱弥斯",
    # 鸣式(Threnodian) 本片新变体（英文原形 + 中文机翻）
    "Therodian": "鸣式", "Trinodian": "鸣式", "Frenodian": "鸣式", "Folodian": "鸣式",
    "索罗尼亚": "鸣式", "索罗诺迪安": "鸣式", "弗雷诺迪安": "鸣式", "弗洛迪安": "鸣式",
    # 隧者(Exostrider) 小写/连写变体（exus/Exos/exo strider/Exost/Exoswarm）
    "exus": "隧者", "Exos": "隧者", "exos": "隧者", "Exost": "隧者", "Exoswarm": "隧者",
    "exo strider": "隧者", "Exos 骑手": "隧者", "exos 骑手": "隧者",
    "exor": "隧者", "exo 跨步者": "隧者", "Therenodian": "鸣式", "Hyroy": "拉海洛",
    "Imth": "爱弥斯", "Christophoro": "克里斯托弗",
    # 鸣潮(Wuthering Waves) ASR 变体 Bua
    "Bua": "鸣潮",
    # 深空联合(Spacetrek Collective) 机翻变体（"太空集体/空间集体/太空迷航集体/太空轨迹"）
    "太空集体": "深空联合", "空间集体": "深空联合", "太空迷航集体": "深空联合",
    "太空轨迹": "深空联合", "Spacetrek": "深空联合", "space track": "深空联合",
    # 幕间(Segue)：3.x 主线章节类型；机翻误作"赛格威"(Segway 平衡车)
    "赛格威": "幕间", "Segue": "幕间", "Segway": "幕间",
    # 原神(Genshin) ASR 误听 Genchin
    "Genchin Impact": "原神", "Genchin": "原神",
    # 黯原(Dimmr Plains，3.3 新增区域；官方地区名=黯原，含落日堤屿/封存地/寂静断崖/恒黯之原)
    "德梅尔平原": "黯原", "demer plains": "黯原", "Dimmr": "黯原",
    # 残星会(Fractsidus) 变体
    "弗莱杜斯": "残星会",
    # 恩沃拉(N'avorora) ASR 变体（Nivora/Nvora/尼奥拉/尼沃拉）
    "尼沃拉": "恩沃拉", "尼奥拉": "恩沃拉", "Nivora": "恩沃拉", "Nvora": "恩沃拉",
    # 拉海洛(Lahai-Roi) 本片新变体（Hyroid/Royer/High Roy/莱艾罗伊）
    "莱艾罗伊": "拉海洛", "Hyroid": "拉海洛", "Royer": "拉海洛",
    "High Roy": "拉海洛", "high roy": "拉海洛", "高罗": "拉海洛",
    # 罗伊(Roya/Royan，拉海洛古文明；官方中文"罗伊神话") —— 长键先于"鲁瓦->漂泊者"防误伤
    "鲁瓦扬": "罗伊", "鲁瓦安": "罗伊", "鲁扬": "罗伊", "罗亚内斯": "罗伊", "罗耶": "罗伊", "Royanes": "罗伊",
    # 弗洛洛(Phrolova) 机翻变体
    "Froolova": "弗洛洛", "Froloova": "弗洛洛", "芙罗洛娃": "弗洛洛",
    # 残星会会长(Grand Architect)：修"伟大建筑师"被"大建筑师"键咬出"伟残星会会长"的半截残形
    # 注意：必须同时收 "伟大建筑师"（5 字），否则会被既有 "大建筑师"(4 字) 键咬成 "伟残星会会长"
    "伟大的建筑师": "残星会会长", "伟大建筑师": "残星会会长", "盛大建筑师": "残星会会长",
    "Grand Architect": "残星会会长", "grand architect": "残星会会长",
    # 漂泊者(Rover) ASR 变体 Wover
    "Wover": "漂泊者", "沃弗": "漂泊者",
    # 库洛(Kuro Games) 英文残留
    "Kuro games": "库洛游戏", "Curo Games": "库洛游戏", "Kuro Games": "库洛游戏",   # 公司全名（2026-10-24 补"游戏"；旧目标"库洛"会留下简称）
    "Kuro系列": "库洛系列",                                              # 同上（cue1340）
    # 艾尔登法环(Elden Ring) ASR 误听"长老戒指/elder ring"
    "长老戒指": "艾尔登法环", "elder ring": "艾尔登法环",
    # --- 2026-09-10 同片二次校准（检索官方中文后修正/新增）---
    # 苇原(Ashinohara)：绯雪故乡，官方中文=苇原（库洛 3.3 公告/库街区 wiki）。
    # 注意：首轮据 ASR 片段"Ashino"推断为"芦野原"有误，官方为"苇原"。
    "Ashinohara": "苇原", "Ashohara": "苇原", "Shinahara": "苇原", "Ashara": "苇原",
    "Ashino": "苇原", "亚夏拉": "苇原", "阿夏拉": "苇原", "阿育王": "苇原",
    "品原": "苇原", "芦野": "苇原", "苇原原": "苇原",
    # 灼樱(Flaming Sakura)：绯雪称号官方=「灼樱巫女/永世灼樱巫女」，非"火樱"
    "火焰樱花": "灼樱", "火樱花": "灼樱", "火樱": "灼樱",
    "Flaming Sakura": "灼樱", "flaming Sakura": "灼樱",
    # 陆·赫斯(Luuk Herssen，星炬学院共鸣医疗科主执校医)：英文 ASR 常作 Luke/Luuk
    "Luke": "陆·赫斯", "Luuk": "陆·赫斯", "卢克": "陆·赫斯",
    # 2026-10-22 Tenha 鸣潮全 EP reaction 片（2015 cue）补录：ASR 整名 Luke Carson / Luke Hson。
    #   必须长键先行，否则短键 "卢克"/"Luke" 命中后留下「陆·赫斯·卡森 / 陆·赫斯·赫森」残尾
    #   （本片 #1343/#1394 基线实测）。“陆·赫斯·卡森”键同时保证二次运行幂等。
    "Luke Carson": "陆·赫斯", "Luke Hson": "陆·赫斯",
    "Luuk Herssen": "陆·赫斯", "Luuk Herrsen": "陆·赫斯",
    "卢克·卡森": "陆·赫斯", "卢克·赫森": "陆·赫斯",
    "陆·赫斯·卡森": "陆·赫斯", "陆·赫斯·赫森": "陆·赫斯",
    # 琳奈(Linny/Lenna，星炬学院预科班学生)：ASR 变体 Lenny/Linny/Lenise；中文机翻"莱妮丝/林尼/莱尼"
    "Linny": "琳奈", "Lenny": "琳奈", "Lenise": "琳奈", "林尼": "琳奈", "莱尼": "琳奈", "莱妮丝": "琳奈",
    # 莫宁(Mornye，深空联合研究院学者/星炬学院教授)：ASR 变体 Mouier/Mor
    "Mouier": "莫宁", "Mornye": "莫宁", "莫尔教授": "莫宁教授", "穆耶教授": "莫宁教授",
    # --- 2026-10-22 Tenha 鸣潮全 EP reaction 片补录（均为非词专名/ASR 整名，裸键安全）---
    #   Suisui=穗穗、Canellilla=坎特蕾拉、Carthais=卡提希娅、Loopa=露帕、Pearlova=弗洛洛；
    #   “卡内利亚”为谷翻对 Cantarella 的音译错形（本片 #350）。
    #   Galena(方铅矿)/Galina(加琳娜)/Bourne(伯恩)/Brand(品牌)/Gian(吉安) 是常用词，
    #   一律走下方 CONTEXT_MAP 参考行锚定，绝不裸键。
    "Suisui": "穗穗", "Canellilla": "坎特蕾拉", "Canelilla": "坎特蕾拉",
    "Carthais": "卡提希娅", "Loopa": "露帕", "Pearlova": "弗洛洛",
    "卡内利亚": "坎特蕾拉",
    # 西格莉卡(Sigrika，星炬学院学生/罗伊符文共鸣者)：ASR 变体 Skiprika/Skip Raa
    "Skiprika": "西格莉卡", "Skip Raa": "西格莉卡", "斯基普里卡": "西格莉卡",
    # 铃(Suzu)：绯雪共鸣能力「预求身」的引子，官方中文=铃；ASR 作 sudsu
    "sudsu": "铃", "Suzu": "铃",
    # --- 2026-09-11 FINALLY MEETING SIGRIKA（鸣潮 3.2 Part 1 反应片）新增 ---
    # 秘日六席（Heliodic Six，罗伊族长老团/六席：视界·灵悉·织星·镌律·拨缕·归律）
    #   官方中文=秘日六席（breeze wiki 多语对照 Chinese(S) 秘日六席；灰机 wiki 罗伊冰原条目同）
    #   英文 ASR 变体 Heliotic/Helionic/Heliodic；中文机翻"赫利奥提/赫利奥六号/太阳六号"
    #   注意："赫利奥六号/赫利奥提人"必须长键先行，否则被"赫利奥"咬成"秘日六席六号"
    "赫利奥六号": "秘日六席", "赫利奥提人": "秘日六席", "赫利奥提病": "秘日六席", "赫利奥提": "秘日六席",
    "赫利奥": "秘日六席", "太阳六号": "秘日六席",
    "Heliotic 6": "秘日六席", "Heliotic Six": "秘日六席", "Helionic 6": "秘日六席", "Helionic Six": "秘日六席", "Heliotic": "秘日六席", "Helionic": "秘日六席", "Heliodic": "秘日六席",
    # 学院暗面（Startorch Academy's Dark Side，学院情绪映照出的空间）
    #   官方中文=暗面/学院暗面（3.2 成就"于学院暗面中见到西格莉卡"）
    #   机翻混用"阴暗面/黑暗面/黑暗的一面"，统一为"暗面"；长键"黑暗的一面"先行
    "黑暗的一面": "暗面", "黑暗面": "暗面", "阴暗面": "暗面",
    # 西格莉卡(Sigrika) 本片新见形态：简称 Sria 及其音译"斯里亚/西格里亚"
    "Sria": "西格莉卡", "斯里亚": "西格莉卡", "西格里亚": "西格莉卡",
    # 恩沃拉(N'avorora) 变体 Navora/纳沃拉
    "纳沃拉": "恩沃拉", "Navora": "恩沃拉",
    # 达妮娅(Denia) 昵称 Denny/Dennia 机翻作"丹尼/丹尼娅"（注意：Daniela=丹妮拉，非同一人，勿收）
    "丹尼娅": "达妮娅", "丹尼": "达妮娅",
    # 星炬学院(Startorch Academy) ASR 误听 Star Tour → 机翻"星游学院"
    "星游学院": "星炬学院", "罗伊斯塔尔学院": "星炬学院",
    # 洛瑟菈(Lucilla) 身份：学院 President=校长，机翻误作"总统"
    #   注意："卢西拉总统/露西拉总统"必须直接映射，否则先被"卢西拉→洛瑟菈"级联成"洛瑟菈总统"后单遍不再回改
    "洛瑟菈总统": "洛瑟菈校长", "露西拉总统": "洛瑟菈校长", "卢西拉总统": "洛瑟菈校长",
    # --- 2026-09-11 同片二次校准新增变体（ERROR行回填时发现）---
    "Hiyuki": "绯雪", "N'vora": "恩沃拉",
    "Sig Gria": "西格莉卡", "Ziggria": "西格莉卡", "saggria": "西格莉卡",
    "Dennia": "达妮娅", "Shortkeeper": "守岸人", "fraodus": "残星会",
    # --- 2026-10-27 3.X 巡演/EP 二次校准补漏 ---
    "哀声鸷沼泽": "怨鸟泽", "whining Ajax's meer": "怨鸟泽",
    "巴耶特林地": "浮光林", "残象领域": "无音区",
    "新世界上海场": "「致予新世界」上海场",
    "Heart of Laoy": "「拉海洛」之心",
    # --- 2026-10-20 Kiri Ahri 洛杉矶演唱会周边开箱片（3531 cue）沉淀 ---
    # 仅收本片实测、且非普通英文词的 ASR 连读形；普通词（cheese=千咲、ameth=a mess、
    #   cardi=card/Cartethyia 两义）一律不裸进表，走逐 cue 侧车。
    "Shorkeeper": "守岸人", "shorkeeper": "守岸人",
    # Camalias 复数须先于 Camalia 命中，否则残留"椿s"；Camelia 为同片异形；
    # 同句连写的 "Camelia Camalia" 用长键折叠，避免产出"椿 椿"
    "Camelia Camalia": "椿", "Camelia camalia": "椿",
    "Camalias": "椿", "camalias": "椿", "Camelia": "椿", "camelia": "椿",
    "Camalia": "椿", "camalia": "椿",
    "Sigiball": "西格莉卡", "sigiball": "西格莉卡",
    "Gingshi": "今汐", "gingshi": "今汐",
    # 2026-10-20 第三轮（官方名核查）补充：非鸣潮 IP 与 WuWa EP 名。
    #   Nikke=《胜利女神：妮姬》/妮姬；RED ASH 官方活动名「RED ASH 不熄之红」；
    #   Elegg/Eluge=伊莱格；Grave=格拉维；Uma Musume=赛马娘；NieR=《尼尔》；
    #   LIFA=西格莉卡 EP《L!!!!ght》；Segreae=西格莉卡。
    #   未入表（普通词/歧义，全部走逐 cue 侧车）：红帽→小红帽（裸键会误伤普通"红帽"）、
    #   Bon Voyage→《远航星的告别》（法语常用语）、Peacock→孔雀剧院（流媒体同名）、
    #   Coron→库洛（人名歧义）、Jen→今汐（常见英文名）、Libby→莉莉（常见英文名）。
    "Nikke": "妮姬", "Nikk": "妮姬", "nikk": "妮姬",
    "Red Ash": "RED ASH",
    "Elegg": "伊莱格", "Eluge": "伊莱格", "eluge": "伊莱格",
    # ⚠ 待收窄隐患（2026-11-02 记录，本轮不动）：裸键 "Grave"→"格拉维"（鸣潮块）会咬任何含
    #   Graveyard/grave 的正当拉丁串——实测《大师决斗》外观名 Graveyard of the Myriad Souls 被咬成
    #   「格拉维yard of…」。正解是挪进 CONTEXT_MAP 加词边界与负向前瞻；因该外观官方简中名不可考，
    #   本片改用语义等价的中文描述形规避，勿据此判定字幕有误。
    "Grave": "格拉维",
    "Uma Musume": "赛马娘",
    "NieR": "《尼尔》", "Nier": "《尼尔》",
    "LIFA": "《L!!!!ght》",
    "Segreae": "西格莉卡", "segreeae": "西格莉卡", "《Segreae》": "西格莉卡",
    "Crypto.com 体育馆": "Crypto.com 球馆",
    "tab 出去": "切出去",
    # --- 2026-09-15 Opera Singer Reacts 鸣潮清宵/景燃 EP（二次校准沉淀）---
    # 古琴：清宵 EP《尘外客》官方 credit「古琴：翟忻来」（Guqin: Xinlai Di），**不是古筝**；
    #   博主口中的 guqin 被 ASR 听成 Cuchen / cooeng / coogen，谷翻作"库根/库恩/气"。
    #   ⚠ 早期误译为"古筝"，2026-09-15 二次校准依官方 credit 更正为"古琴"。
    "库根": "古琴", "库恩": "古琴", "Cuchen": "古琴", "cooeng": "古琴", "coogen": "古琴",
    "喉咙歌唱": "呼麦",                                             # throat singing（本片两处）
    "铁匠悟空": "黑神话：悟空",                                      # Blackmith Wukong = Black Myth: Wukong
    "凋零波浪": "鸣潮", "风化波浪": "鸣潮",                           # Withering/Weathering Waves 机翻残留
    # --- 2026-09-20 ECHO OPTIMIZATIONS!! Wuthering Waves 3.7 Livestream Reaction（微软翻译前瞻反应片）二次校准沉淀 ---
    # 微软翻译官方前瞻字幕片特性：口播段本身就是中文，痛点是 ASR 同音错形，且"深海/换取/明朝/今夕/
    # 供应者/漂浮者/微型任务/恶障/天宫/灵智异常/林奈/弹切/决心破/玄琴(韩国乐器 가야금)"等误形源自
    # **通用中文词**，按硬契约第 4 条不得入裸键表，只能逐 cue 整行覆盖（见 _calib_tmp_37live/rebuild.py）。
    # 以下仅收专名级安全错形（均为 3.7「镜锁妄世，心照红尘」官方名词的错形，检索依据：官网前瞻通讯+库街区）：
    "索明": "锁暝", "水明": "锁暝",                                  # Suoming 锁暝 微软翻译同音错形
    "星月湖": "心月狐",                                              # 心月狐 Hsin 错形
    "昭昭和年月": "朝朝何年月",                                      # 危行任务官方名
    "梦书天罗": "梦枢天罗", "梦书天炉": "梦枢天罗",                  # 3.7 新区域官方名
    "西米拉克林": "梦枢天罗", "Simiracrim": "梦枢天罗",              # similacrim ASR/机翻残留（同 梦书天罗 家族）
    "天罗湖影": "天罗狐影",                                          # 梦枢天罗巨大狐影
    "信誉稳定值": "心域稳定值",                                      # 心钥井玩法数值
    "全方城": "玄方城",                                              # 玄方城错形
    "图音消除": "无音消除",                                          # 休闲活动官方名
    "洛塞拉": "洛瑟菈", "洛瑟拉": "洛瑟菈",                          # Lucilla 官方名 洛瑟菈
    "潜影于明日": "显影于明日",                                      # 洛瑟菈唤取池官方名
    "玉雀玄华": "玉阙玄华",                                          # 心专武官方名
    "应感仪": "音感仪", "灵感仪": "音感仪",                          # 武器类型官方名
    "星湖年糕": "心狐粘糕",                                          # 心最爱食物官方名
    "千笑": "千咲",                                                  # Qiuxiao? Chisa 千咲 错形
    "成春": "承春", "陈琉璃": "沉琉璃",                              # 心/锁暝饰品官方名
    "巡骁枪卫": "巡霄枪卫",                                          # 新声骸官方名
    "于心所向": "余心所向",                                          # 锁暝唤取池「余心所向九死未悔」
    "慢于银缺石轴": "漫于盈缺时轴", "宠物银线之间": "曙暮一线之间",  # 尤诺/千咲 复刻池官方名
    "雾梦寻迹": "故梦寻契",                                          # 留影收集活动官方名
    "烧烤摩托": "科考摩托",                                          # 奖励载具官方名
    "净世之器": "禁锁十契", "净所时期": "禁锁十契", "禁所实际": "禁锁十契",  # 锁暝组织官方名错形
    "既成琴": "璇情",                                                # 奇谭任务『璇心如月寄尘情』少女名
    "天宫寻物": "天工寻物",                                          # 四字活动名整体专名（"天宫"裸词危险，不加）
    "深海背包": "声骸背包", "深海体系": "声骸体系", "深海装配": "声骸装配",  # 声骸组合词（"深海"裸键危险，只收三字以上组合）
    "深海编队": "声骸编队", "深海推荐": "声骸推荐", "深海种类": "声骸种类",
    "深海们": "声骸们",
    "星月琳琅集": "心月琳琅集",                                      # 飞讯礼包官方名
    # "达尼亚->达妮娅" 不入表：terms-check 报与既有键 "Dasidia->达斯维达尼亚" 级联
    #   （长键先替换后，短键会咬掉"达斯维达尼亚"里的"达尼亚"）；本片该错形走逐 cue 覆盖。
    # --- 2026-10-05 ABSOLUTE HSINEMA｜Wuthering Waves 3.7 主线 reaction（en-谷翻，5423 cue）二次校准沉淀 ---
    # 官方中文依据（本轮检索确认）：瑝珑=Huanglong（百度百科/萌娘百科/鸣潮 huijiwiki；别称皇龙，
    #   所辖今州·梦州·诏州·越州·重州·戎州）；玄方城=瑝珑机关都市（科技源自岁主心月狐，3.5 梦州·玄方地界）；
    #   稷廷=Court of Savantae（官中即"稷廷"，非"稷庭"）；鸣式=Threnodian；残星会=Fractsidus；
    #   玄翎雀=岁主信使；木禺之乱；文明之匣；岁主「心」（梦州）；追月节（典故「心狐追月」）。
    # ⚠ 「黄龙」非官方名（官中=瑝珑）且属同音误写词 → 走 CONTEXT_MAP 英文锚定，不进本裸键表。
    # ⚠ 「苏姐/起诉」同属误译，也用 CONTEXT_MAP 由 \bSuing\b 锚定，不进裸键表。
    # 残象(Tacet Discord) 机翻残留
    "言语不和谐": "残象",                                            # tacet discords（#53）
    # 机傀(auto puppet) 机翻残留
    "汽车傀儡": "机傀",                                              # auto puppets（#419）
    # 稷廷(Court of Savantae) 英文/机翻残留
    "Zeante": "稷廷",                                                # Court of Savantae（#2143）
    "Gju Natalier": "乔贾·纳塔利娅",                                 # 同 #2368「乔贾·纳塔利娅 Joja Natalia」
    "圣工匠": "稷廷工匠",                                            # court of sante artisan（#905）
    # 玄翎雀(Shenling/Shrenling bird，岁主信使) 机翻残留
    "雪万灵鸟": "玄翎雀", "栓灵鸟": "玄翎雀",                         # #2988/#3520
    # 万相神宫(manifold sanctum) 机翻残留
    "密室深处": "万相神宫深处",                                      # deep in the sanctum（#1322）
    # 漂泊者(Rover) 机翻残留
    "轨道飞行器": "漂泊者",                                          # orbiter（#622/#2639）
    # 谛天鉴(Ministry of Sentinel Affairs) 头衔机翻残留
    "岁主事务总管": "谛天鉴州监",                                    # intendant of Sentinel Affairs（#2937）
    # 鸣式(Threnodian) 本片新见 ASR/机翻形态（长键先行，避免残留「鸣式人」）
    "特罗迪亚人": "鸣式", "特罗迪亚": "鸣式", "鸣式人": "鸣式",       # Trodian/Thrronian（#3470/#3545）
    # 溯心(Susheen) / 锁暝(Swarming) 英文残留（出现在中文行 = 未译专名）
    "Sushi": "溯心", "Sushin": "溯心", "Susheen": "溯心",             # #4171/#4172
    "Suing": "锁暝", "Swaming": "锁暝",                               # #4771
    # --- 2026-11-06 《I Played 300 Days of Wuthering Waves》（微软翻译，508 cue）二校沉淀 ---
    #   ⚠ 官方 3.7 公告（mc.kurogames.com/main/news/detail/5569）分档：可玩角色「心」
    #   （Hsin，Shin/Sheena/Shina 皆其 ASR 形）；岁主本体才作 the Moon Fox/Sheen=心月狐。
    #   旧 ctx Shin->心月狐 为剧情片沉淀，评论/抽卡片系统性偏到心月狐（判例见
    #   Entity('心') note）；Sheena/Shina 仅reaction 片指角色「心」，剧情片慎用。
    #   锁暝拉丁音译形（Suwamin/Suvamin/Slonmin/Slongming/Somin/So Min/Swimin）与
    #   Sheena/Shina 归 Entity("锁暝")/Entity("心") variants，本表不重复登记。
    #   ⚠ **禁裸键 "Wuwa"**（terms-check 实测 6 处隐患、kb-lint 9→10 级联互含）：本表已有
    #   实体 "Wuwa Tappo"->呜哇塔波（他游戏角色名），裸键 Wuwa 是其子串，替换后二次咬合。
    #   改由 WUWA_MISSING_CHECK 的 \bWuwa\b 锚「只报不改」，命中交人工逐 cue 判。
    "呼啸的波浪": "鸣潮",                                              # Wuthering Waves 直译（与"呼啸波"无子串关系）
    "Forte面板": "共鸣回路面板", "强项链": "共鸣回路",                  # Forte Circuit 官中=共鸣回路（强力面板/强项链为直译）
    "标志性武器": "专属武器",                                           # signature weapon（中置信：官公告只写武器名+唤取）
    "晶体溶剂": "结晶溶剂",                                             # crystal solvent 微软语序颠倒（官中=结晶溶剂）
    "QB Wars": "团团勇者大乱斗", "Cubie Wars": "团团勇者大乱斗",        # 官中逐字（3.7 公告；QB Wars 为 ASR 形）
    # --- 2026-10-22 3.7 Hsin reaction 二次校准沉淀（官方中文依据：ENTITIES + 3.7 剧情）---
    #   解形煞(Form Renders) / 玄翎雀(Xuanling Bird) / 十重契(锁暝异能) 官方中文名；
    #   旧译「形态渲染(器)」「玄方林鸟」「山陵鸟」「十封印」为谷翻/ASR 直译残留。
    "形态渲染器": "解形煞", "形态渲染": "解形煞",
    "玄方林鸟": "玄翎雀", "山陵鸟": "玄翎雀",
    "十封印": "十重契",
    #   务安面纱/玄元境域/稷廷 中文错形（同片英译残留）
    "梦州帷": "务安面纱", "玄方领域": "玄元境域",
    # 务安面纱(Muan Veil，梦枢天罗内静修处) 英文/机翻残留
    "Monguan Veil": "务安面纱", "Monuan Veil": "务安面纱", "莫努安面纱": "务安面纱",
    # 朝月会(Waking Moon Festival) 机翻直译残留；「醒月」非通用中文词，可安全收表
    #   （更长键「醒月盛宴/醒月节」->朝月会 已先行，按键长降序不会被子串误咬）
    "醒着的月亮": "朝月", "醒来的月光": "朝月的月光", "苏醒之月": "朝月",
    "醒着的月灯": "朝月的月灯", "醒月": "朝月",
    "Raiki Moon Festival": "朝月会", "Shran Hall": "玄方城要塞",     # #3384 英文整段未译
    # 玄元境域(Schwanuan/Shreuan domain) 英文/机翻残留
    "Shreuan 域": "玄元境域", "Schwanuan": "玄元境域",                # #4689（同 #863 玄元境域）
    # 瑝珑(Huanglong) 错形
    "鸿隆": "瑝珑",                                                  # #85
    # 本片确认正确的既有专名补入脚本（此前脚本内 0 处，便于复用）
    # 注：Providence lock 官方中文=锦妙锁（见 ENTITIES），2026-10-05 删除早先误沉淀的音译键"普罗维登斯锁"
    "Mind Watcher": "心灵观察者",
    # --- 2026-10-05 同片二次校准：把上一轮「只走逐 cue 覆盖、未入表」的 3.7 玄方专名补全为脚本规则 ---
    # 硬契约第 4 条：以下只收**非通用中文词**的错形；「圣殿/圣地/胶囊/货舱/总督/管家/蜂拥而至/
    #   中秋节/海豹/山房/宋国」等属通用词或历史名词，一律不进裸键表 → 走 CONTEXT_MAP 英文锚定或保留逐 cue。
    # 梦州(Mengjo/Mhjo/Mong Joe) 机翻错形
    "梦祖": "梦州", "孟乔": "梦州", "姆乔": "梦州", "孟乔万": "梦州",
    # 玄方城(Schwangfong Hold) 机翻音译错形（长键先行）
    "玄方芳": "玄方城", "玄方芬": "玄方城", "玄方方": "玄方城",
    "玄方 fang": "玄方城", "玄方fang": "玄方城", "玄方 Fong": "玄方城",
    "山峰控股": "玄方城", "上风控股": "玄方城", "仁丰控股": "玄方城",
    "身芳": "玄方城", "丰丰堡": "玄方城", "山通堡": "玄方城",
    "栓握会": "玄方城", "海绵牙": "玄方城", "宋国芳": "玄方城",
    "玄方要塞": "玄方城要塞", "玄方之地": "玄方地界",
    # 命运棱镜(Prism of Fate) —— ASR 把 prism 听成 prison
    "命运监狱": "命运棱镜", "命运的监狱": "命运棱镜",
    "命运的牢狱": "命运棱镜", "命运的牢笼": "命运棱镜",
    # 朝月会(Waking Moon Festival)：长键必须显式收，否则会先被「醒月->朝月」咬成「朝月盛宴/朝月节」
    "醒月盛宴": "朝月会", "醒月节": "朝月会", "朝月盛宴": "朝月会", "朝月节": "朝月会",
    # --- 2026-10-06 HSIN玄方终章 reaction 二次校准沉淀（修复裸键"醒月"级联叠字）---
    #   根因：Waking Moon 被谷翻成"清醒月/觉醒月"（清醒/觉醒=通用词，不能裸键入表），
    #   但内含子串"醒月"会被长键降序里最后的裸键「醒月->朝月」咬掉前半"清/觉"，
    #   级联产出无意义叠字"清朝月亮/觉朝月会"。补"清醒月/觉醒月"系长键，
    #   按键长降序先于"醒月"命中，从根上消除叠字（对全部 Waking Moon 片源通用）。
    "清醒月亮": "朝月", "觉醒月亮": "朝月", "清醒月光": "朝月光",
    "清醒月节": "朝月会", "觉醒月节": "朝月会", "清醒月会": "朝月会", "觉醒月会": "朝月会",
    "清醒月": "朝月", "觉醒月": "朝月", "清朝月": "朝月",
    # 瑝珑(Huanglong) 错形
    "还龙": "瑝珑",
    # 秧秧(Yangyang) / 同宁(Tonging)
    "林秧秧": "秧秧", "童宁": "同宁", "通宁": "同宁",
    # 稷廷(Court of Savante) 机翻变体
    "桑特宫廷": "稷廷", "萨万特法院": "稷廷", "萨万特宫廷": "稷廷",
    "桑特法院": "稷廷", "萨万特": "稷廷",
    # 玄翎雀(Shenling，岁主信使) / 玄朱锁(Vermillion lock)
    "神铃": "玄翎雀",
    # --- 2026-11-12 鸣潮 3.7 梦州终章 reaction 二校沉淀（官方依据：H 盘 3.7 精校总表 + ENTITIES）---
    #   一校手工覆盖导致官方形回退；均为非通用长键，按键长降序不会误咬。
    "天意锁": "锦妙锁",
    "心月狐年糕": "心狐粘糕",
    "堡垒与峡谷战争": "云渊之役", "要塞与峡谷战争": "云渊之役",
    "芬蒂莉亚": "芙露德莉丝",
    "景商会": "江陵商会",
    "蒙关帷幕": "梦川帷", "蒙古帷幕": "梦川帷",
    "坎特宫廷": "稷廷",
    "第九封印": "第九重契",
    # "朱锁->玄朱锁" 不入表：terms-check 报 7 处二次命中（"朱红锁/Vermillion lock" 已产出"玄朱锁"，
    #   短键会再咬成"玄玄朱锁"）；按既有判例退回逐 cue 覆盖（本片 #2886/#5168/#5346）。
    # "苏铭->锁暝" 亦不入表：Suming 在多片源可能作人名，属高碰撞逐 cue 覆盖。
    # 机傀(auto puppet)
    "自动木偶": "机傀", "自动人偶": "机傀",
    # 残象(Tacet Discord) 机翻错形
    "塔卡不和谐": "残象", "泰塞特不和": "残象", "策略不和谐": "残象",
    "冷漠的不和谐": "残象", "沉默不和谐": "残象",
    "Tesset 不和谐": "残象", "Tesset不和谐": "残象", "Tesset 不和": "残象",   # #1465
    # 锁暝(Swarming)：swarming 被直译成成语"蜂拥而至"；补长键，收掉裸键"蜂拥"留下的"而至"尾巴
    "蜂拥而至": "锁暝",                                              # #549/#789/#2030/#2872/#2885/#2957
    # 溯心(Susheen) 机翻音译变体
    "苏辛": "溯心", "苏珊": "溯心", "苏夏": "溯心", "苏夏": "溯心",
    # --- 2026-10-06 HSIN!!! XUANFANG FINALE 3.7 reaction 二次校准沉淀 ---
    #   依据官方：溯心=Susheen/Sushin、锁暝=Swarming/Swaming/Swinging(EN ASR)、
    #   天罗狐影=Nexus Fox、梦枢天罗=Simulac(r/m/) Nexus、残星会=Fractsidus/Fraidus。
    #   戒律（同 683 行硬契约）：只收"该英文串出现即鸣潮专名、且不会被短键/子串误咬"
    #   的无歧义**长**键。有歧义的一律留逐 cue 覆盖，不入裸键——
    #     · sin=「心」：sin 是英文常用词，且"罪"有本义(blame/treason)语境 → 逐 cue；
    #     · sushi=「溯心」：与 3.5 共鸣者穗穗(Suisui，脚本裸键 Sushi->穗穗)冲突 → 逐 cue；
    #     · Yuki/Tendant/Cien/Suin 等：会咬进 Hiyuki/Intendant/正常词 → 逐 cue。
    "Sister Swarming": "锁暝姐妹", "Sister Swimming": "锁暝姐妹",
    "Sister Swaming": "锁暝姐妹", "Sister Swinging": "锁暝姐妹",
    "Simulator Lake Nexus": "梦枢天罗",
    "Fractsidus": "残星会",
    # 鸣潮(Wuthering Waves) 的 EN ASR 误听（"Wu"→"Water"），出现即游戏名，无歧义
    "Watering Waves": "鸣潮", "Watering Wave": "鸣潮",
    # --- 2026-10-13 WISH GRANTED!! Hsin 3.7 Main Story Quest FULL REACTION（2341 cue）二次校准沉淀 ---
    #   根因诊断：上一轮只收了 "Sister Swarming" 这类**带前缀的长键**，而本片中文行里的
    #   拉丁残留是**裸名**形态（"Sw ami"、"Sw arming"、"SW 武装"、"Arb iter"、"Sim ul ac rum"），
    #   长键匹配不到 ⇒ 术语 pass 几乎全落空（基线仅 166 处）。本块补裸名长键。
    #   官方依据（3.7 版本内容说明 / 百度百科谛天鉴条 / wutheringwaves.fandom）：
    #     锁暝=Suoming（州监，执掌谛天鉴）  岁主=心月狐  谛天鉴=Ministry of Sentinel Affairs
    #     州监=Intendant（**非"智力"**，机翻把 Intendant 听成"智力"的音译陷阱）
    #     玄方城=Xuanfang Hold（ASR 常听成 Shuangfeng/Shuangfang ⇒ 同指玄方城）
    #     残星会=Fractsidus  稷廷=Court of Savantae  天民=Celestials（**非 Sentinels**，
    #     本片大量 "Sentin els" 其实是 celestial 的 ASR 误听，语境为玄方城匠人）
    #     仲裁者=Arbiter  机傀=Autopuppet（**非"反对宠物"**）
    #     共鸣者=Resonator  梦枢天罗=Simulacrum Nexus
    # 戒律：只收"该串出现即该专名、且不会被通用短键/子串误咬"的**长**键；
    #   "智力/智力代言/智力应答者"是通用中文词 → 不入裸键，走 CONTEXT_MAP 英文锚定。
    # --- 锁暝 Suoming：裸名 ASR 变体（"Sw"+"aming" 之间的空格是 ASR 断词痕迹）---
    "Sw aming": "锁暝", "Sw aming ": "锁暝",
    "Sw aming": "锁暝", "Sw amin": "锁暝", "Sw ami": "锁暝",
    "Sw arming": "锁暝", "Sw arming": "锁暝", "Sw arming": "锁暝",
    "Sw AM": "锁暝", "SW AM": "锁暝", "Sw ammings": "锁暝",
    "sw ammings": "锁暝", "Sw imming": "锁暝", "Sw imming": "锁暝",
    "SW武装": "锁暝", "SW 武装": "锁暝", "sw arming": "锁暝",
    # --- 仲裁者 Arbiter：ASR 把 -bi- 听成空格 ---
    "Arb iter": "仲裁者", "Ar b iter": "仲裁者", "Arb iter": "仲裁者",
    # --- 玄方城 Xuanfang：ASR 把 Xuan 听成 Shuang ---
    "Sh uang f eng Hold": "玄方城", "Sh uang f ang": "玄方地界",
    "Sh uang Fang": "玄方地界", "Sh uang f eng hold": "玄方城",
    "Sh uang y uan": "玄元", "Sh uangling": "玄翎",
    "Xuan f eng Hold": "玄方城", "Xuan f eng": "玄方城",
    # --- 梦枢天罗 Simulacrum Nexus：ASR 把 -la- 听成空格 ---
    "Sim ul ac rum": "梦枢天罗", "simul ac rum": "梦枢天罗",
    "Simulacrum Nexus": "梦枢天罗", "Sim ul ac rum Nexus": "梦枢天罗",
    # --- 残星会 Fractsidus：ASR 把 -ct- 听成 x ---
    "Fr ax id us": "残星会", "Fr ax idus": "残星会", "Fr ax inus": "残星会",
    "Fr ax idas": "残星会", "Fr ax id us": "残星会",
    # --- 2026-10-13 WuWa Exploration Quests and Tales（4349 cue）补键 ---
    "重振器": "共鸣者",                                            # 谷翻 resonator 错形（#917，官方=共鸣者）
    "金习": "今汐",                                                # Jin Xi ASR 音译残留（#2759，"作为岁主"语境）
    # --- 稷廷 Court of Savantae / 天民 Celestials / 岁主 Sheen ---
    "Sav ante": "稷廷", "Sav anti": "稷廷", "Sav ante": "稷廷",
    "Sentin els": "天民", "Sentin el": "天民", "Sentinel s": "天民",
    "森廷": "天民", "森廷艾尔": "天民", "森廷·埃尔斯": "岁主",
    "Cele stials": "天民", "Cele stial": "天民", "Cele stil": "天民",
    "cele stials": "天民",
    "Sh ien": "岁主", "She en": "岁主", "she en": "岁主",
    # --- 其余拉丁残留（长键，无通用词歧义）---
    "Tyr Ant": "暴君", "glo om": "阴郁", "REM": "疏忽",
    "M uyu": "牧羽", "Par agon": "帕尔阿贡", "Bal anafor": "巴拉纳福",
    # --- 2026-10-24 鸣潮 3.7 锁暝 PV「契阔」reaction 二校（英文原声 + 谷翻，165 cue）---
    #   官方依据：TapTap《鸣潮》共鸣者「锁暝」PV | 契阔 CV 表（2026-10-20：蛇菰：卢晓彤）、
    #   3.7 剧情（蛇菰=残星会女会监 / 谛天鉴州监，刺杀心月狐本体）、百度百科「锁暝」。
    #   蛇菰=Balanophora；Balanar/Belenor 是 ASR 漏音节形。⚠ 巴拉纳福 是另一形
    #   Balanafor 的旧译（上一条），不可把本片 Balanar/Belenor 映射成它。
    "Balanar": "蛇菰", "Belenor": "蛇菰", "Balanophora": "蛇菰",
    "巴拉纳尔": "蛇菰", "贝勒诺尔": "蛇菰",
    "Bal ana": "巴拉纳福",                       # 旧键保留：Bal anafor/Bal ana 是另一实体
    "Bal an oph ora": "蛇菰",                    # 修正旧键「巴拉诺弗拉」：官方中文=蛇菰
    # --- 2026-10-24 《Jadealy｜Suoming Trailers》（293 cue）二校补录 ---
    #   长键安全：均为音译专名/基线半成品收口，无通用词歧义。
    "弗拉克萨斯": "残星会",                       # Fraxus，本片 #39/#53
    #   ⚠ 必须用源形态「游泳」：BILINGUAL_TERMS 先于 CONTEXT_MAP 执行，
    #   写中间形「登登锁暝/意图锁暝」不会命中（实测 #48/#145 未收口）。
    "在登登游泳方面": "，州监锁暝",                 # #145 Dendon swimming=Intendant Suoming
    "意图游泳": "州监锁暝",                       # #48 Intended swimming 的源形态
    "在登登锁暝方面": "，州监锁暝",                 # 中间形兜底
    "意图锁暝": "州监锁暝",                       # 中间形兜底
    #   ⚠ 「亚斯玛」不入扁平表：裸键会得到「邪恶的恶瘴」，走 CONTEXT_MAP 整段替换。
    #   Intendant Swamy = 州监锁暝（Swamy 是 Suoming 的 ASR 误听；长键先行，
    #   避免既有 ctx Intendant->总监->州监 留下「斯瓦米州监」残形）
    "斯瓦米总监": "州监锁暝", "斯瓦米州监": "州监锁暝",
    "S assy Ab ird": "萨西·艾伯德", "Saf ar": "萨法尔",
    "Tats": "塔茨", "Y asuri ice": "雅苏里", "Fr ax idus": "残星会",
    "Sim ul ac rum": "梦枢天罗", "Arb iter": "仲裁者",
    "Em i M acha": "AnyMatcha", "Em i M acha": "AnyMatcha",
    "Rover,": "漂泊者", "Lex icon Axis": "轴心图标",
    "Allegs": "小巷", "alle ys": "小巷",
    # --- 2026-10-13 WuWa Exploration Quests and Tales（4349 cue）二次校准 round2 沉淀 ---
    #   side_r2.tsv 侧车回填 466 处（verify OK：时间轴/参考行零变更）；cue 级明细见
    #   wuwa_explore_tales_diff.md「二次校准（round2）」章节。以下为重复模式归纳成的
    #   通用键（该串出现即该专名/该错形、无通用词歧义；歧义条目走 CONTEXT_MAP 英文锚定）。
    "王牌空战": "皇牌空战",                                        # Ace Combat 官方名（#46/52/80/133/180/3555/3596/4156/4240）
    "Gens hin": "原神", "Gens": "原神",                            # Genshin 裸/撕裂残留（#107/200）
    "三华": "散华", "San hua": "散华",                             # Sanhua（#345）
    "库查尔罗": "卡卡罗", "K uchar ro": "卡卡罗", "K Uchar Ro": "卡卡罗",  # Calcharo（#323/324）
    "陆佩": "露帕", "Lu pe": "露帕",                               # Lupa（#333/334）
    "香丽乌": "相里要",                                            # Xiangli Yao（#336）
    "岸上守门员": "守岸人", "岸上守卫": "守岸人",                  # Shorekeeper（#287/298）
    "Card itth ia": "卡提希娅",                                    # Cartethyia（#288）
    "Cam ellia": "椿",                                             # Camellia（#2087/2089/2138）
    # 2026-10-21 废除裸键 "金时"->"今汐"：会误伤「黄金时代」（Fobm4ster 片 #184 实测
    # 「黄今汐代」）。今汐统一走 CONTEXT_MAP 英文锚定（\bJinshi\b / \bJinhsi\b），
    # 短中文裸键不得入表（硬契约第 4 条）。
    "景跑": "忌炎", "Jing ran": "忌炎",                            # Jiyan（#3084/3112）
    "清朝×嚷": "清宵",                                             # Qingxiao（#3317）
    "拉海罗": "拉海洛",                                            # Lahai Roi（"拉海罗伊"长键先行）
    "千佐": "千咲",                                                # Chisa（#3066）
    "Fro lo va": "弗洛洛",                                         # Phrolova（#285）
    "汤呆子": "汤包",                                              # soup dumplings（#2373）
    "拿坡里战争": "拿破仑战争", "拿坡路战争": "拿破仑战争",        # Napoleonic Wars（#1016/3830）
    "全息公羊": "全息投影",                                        # hologram（#617/2785）
    "退货奖励": "回归奖励",                                        # returner rewards（#628）
    "格里菲斯塔": "格里菲斯天文台",                                # Griffith Observatory（#630）
    "鳄梨": "牛油果",                                              # avocado（#636）
    "Pier Ogi": "波兰饺子",                                        # pierogi（#653）
    "Like Wars": "华沙", "Var sh ava": "华沙",                     # Warsaw ASR（#668/673）
    "St arry Stage": "星舞台", "圣艾利2阶段": "星舞台2", "圣艾瑞第二阶段": "星舞台2",  # Starry Stage（#678/691/695/696）
    "红色空缺": "救赎",                                            # Redemption（#693）
    "贝利·瓦布尔": "难以置信",                                     # Unbelievable（#880）
    "森特·里克": "为中心",                                         # centric（#889）
    "幽灵奔跑者": "幽灵行者",                                      # Ghostrunner（#1023）
    "女巫ER3": "巫师3", "女巫ER": "巫师",                          # Witcher 3（#1105/1855/4165）
    "Res 识别 Evil": "生化危机",                                   # Resident Evil（#1073）
    "Onim ush a": "鬼武者",                                        # Onimusha（#1077）
    "Crim son Desert": "红色沙漠",                                 # Crimson Desert（#1097）
    "Dawn Walker": "黎明行者",                                     # Dawnwalker（#1100/1101）
    "Dig Imon": "数码宝贝",                                        # Digimon（#1117）
    "S cri b bl en aut s": "涂鸦冒险家",                           # Scribblenauts（#1120）
    "勇敢前人5": "勇气启示录",                                     # Brave Exvius（#1124）
    "王国红心": "王国之心",                                        # Kingdom Hearts（#1139）
    "Nik Ke": "NIKKE", "Nik kei": "NIKKE", "Nik ke i": "NIKKE",    # NIKKE（#1249/1373）
    "LAR Per": "跑团扮演者", "LAR PER": "跑团扮演者",              # LARPer（#1182/1184）
    "地下城大吃怪": "魔物饭大冒险",                                # Dungeon Munchies（#1412）
    "第一阶梯的后奏": "第一后裔",                                  # First Descendant（#1452）
    "SH罩": "遮罩",                                                # shroud（#1520）
    "月亮雷弗伦斯舞蹈团": "崇月舞团",                              # Moon Reverence Dance Fellowship（#1595）
    "黑色神话": "黑神话", "Wuk ong": "悟空",                       # Black Myth Wukong（#1841/1865）
    "Met aph or": "暗喻幻想",                                      # Metaphor ReFantazio（#1843/1847）
    "光辉之路": "苍炎之轨迹",                                      # Path of Radiance（#1803）
    "Heart of Th orns": "荆棘之心",                                # GW2 Heart of Thorns（#1755）
    "卡门光的动机": "卡门主导动机",                                # Carmen leitmotif（#1781）
    "瓦尔伊里亚的阴影": "瓦伦西亚之影",                            # Shadows of Valyria（#1794）
    "新灌溉": "新联邦",                                            # new fed 谷翻（#1964）
    "孟周": "孟舟",                                                # Meng Zhou 统一写法（#1951/3205）
    "天讯": "腾讯",                                                # Tencent 谷翻（#2288）
    "梅兰克奥利": "忧郁",                                          # melancholy（#2627）
    "偏见主义": "部分主义",                                        # particularism（#2576）
    "雷·阿彦·阿米": "绫波丽",                                      # Rei Ayanami（#2567）
    "神父斧": "残星会",                                            # Frax ASR（#2677）
    "乐初叔": "楚叔",                                              # Uncle Chu（#2697）
    "Ab igail": "阿布",                                            # Abby（#846）
    "Steel Ball Run": "飙马野郎",                                  # JoJo SBR 官方名（#867）
    "Sentin els Res on ator": "岁主共鸣者", "Sentin els reson ator": "岁主共鸣者",  # Sentinel's Resonator（长键先行于 "Sentin els"->天民）
    "Valor Mort": "死之勇气",                                      # Valor Mortis 官方中文名（#277/1012/1110/1806；跨行"Val orm ort is"形态不误咬）
    "Wither ing Waves": "鸣潮", "Wuth ering Waves": "鸣潮",        # WuWa ASR 拉丁残留（#3150/3171/3191 等）
    "吴乐队": "鸣潮", "吴巴": "鸣潮", "WU HA": "鸣潮",             # WuWa ASR 变体（#1458/3718/1904）
    "吴演唱会": "鸣潮演唱会",                                      # Wu concert（#618）
    "他的战斗8": "皇牌空战8",                                      # Ace Combat 8 谷翻（#1336）
    "迷你帽": "缩小帽",                                            # Minish Cap 官方名（#4137）
    "Xen obl ade Chronicles": "异度神剑", "Xen obl ade": "异度神剑",  # Xenoblade（#4180/4192）
    "绝地被放逐": "绝地武士：放逐者",                              # Jedi Outcast（#4040）
    "荒野大人": "荒野大镖客", "荒野大杀人": "荒野大镖客",          # Red Dead 2 谷翻（#4218/4221/4261/4271）
    "Arm ored Core": "装甲核心", "Arm Ored Core": "装甲核心",      # Armored Core 6（#4116-4120）
    "Where Wins Me": "战舰世界",                                   # World of Warships ASR（#3883/3885）
    "莫克斯·伊": "莫克茜", "M ox ie": "莫克茜", "Mox ie": "莫克茜",  # Moxie（#3589-3591）
    "共生症": "共生关系",                                          # symbiotic（#3618）
    "Roc吃了": "回报大家",                                         # reciprocate ASR（#3625）
    "被疏离": "被疏远",                                            # alienated（#3667）
    "传送机": "传送点",                                            # teleporter（#3780）
    "Fires IDE聊天": "炉边谈话",                                   # fireside chat（#4299）
    "VT大学": "虚拟主播", "VT的学生": "虚拟主播",                  # VTubers ASR（#4331/4339）
    "不是艾德": "记下了",                                          # Noted ASR（#4341）
    "西南阿曼": "锁暝",                                            # Swoman=Swarming ASR（#3048）
    "分隔方式": "过渡段", "分离方式": "过渡段", "分隔的方式": "过渡段", "seg ways": "过渡段",  # segue（#3055-3064）
    "H arem": "后宫烂活", "后宫慢速": "后宫烂活",                  # harem slop（#860/861/3404）
    "Gl acio": "冷凝",                                             # Glacio 官方属性=冷凝（#751/753）
    "Day of Def eat": "胜利之日",                                  # Day of Defeat（#4034/4039）
    # --- 2026-10-20 3.7 后日谈《璇心如月寄尘情》reaction 二次校准沉淀（官方中文：璇情）---
    #   官方依据：3.7 奇谭任务「璇心如月寄尘情」攻略（9game/233/18183）明确新 NPC=璇情。
    #   ⚠ 修正旧沉淀：2026-10-16 块曾把 Schwanqing 记作「玄方清」；实际官方名为「璇情」。
    #   长键先行：「施万庆/施万清」必须先于裸键「施万」->玄方 命中，否则会产「玄方庆」。
    "施万庆": "璇情", "施万清": "璇情",
    "玄方庆": "璇情", "玄方清": "璇情",
    #   辛月狐 -> 心月狐：整名替换必须先于 ctx 的「辛」「月狐」短键，否则叠成 心月狐心月狐
    "辛月狐": "心月狐",
    "tacet不和谐": "残象", "tacet 不和谐": "残象",
    "tacet不和": "残象", "tacet 不和": "残象",
    "施万姐姐": "璇情姐姐", "玄方姐姐": "璇情姐姐",
    "施万·辛格": "璇情·辛格", "玄方·辛格": "璇情·辛格",
    #   上级替换的常见级联/叠字（本片基线 report 实际出现；均非通用中文词，可安全裸键）
    "云云梭": "云梭",
    "心月狐心月狐": "心月狐",
    "玄方城 Hold": "玄方城", "玄方城Hold": "玄方城",
    "领领域": "领域",
    "时空梦枢天罗": "梦枢天罗",
    "残象不和谐": "残象",   # 兼作旧键「泰莎/塔塞特/Tacet 不和」的收敛兜底
    #   长键先行，防止短键先跑留下「时空/云」前缀：云班车/云航天飞机->云梭
    #   （「时空枢纽」属可独立成词的通用短语，不入裸键，改走 CONTEXT_MAP 的 Nexus 锚定）
    "云班车": "云梭", "云航天飞机": "云梭",
    # --- 2026-10-22 RBGTalk《MUSICIAN DISCOVERS Wuthering Waves' INSANE OST!》二校 ---
    #   官方 credit（B站《鸣潮》先约电台 EP2.4 卡提希娅《Against the Tide（逆潮）》）：
    #   作曲/作词/编曲/吉他=Obadiah Brown-Beach。谷翻「奥巴代亚·布朗」是音译残留；
    #   长键先于短键，防止短键把「-比奇」叠成残尾。
    #   Persona 只收「音乐」组合，避免误伤 Persona 3 Reload 等作品名（AK_TERMS 已有裸键）。
    "奥巴代亚·布朗-比奇": "Obadiah Brown-Beach",
    "奥巴代亚·布朗": "Obadiah Brown-Beach",
    "奥巴代亚布朗": "Obadiah Brown-Beach",
    "Persona音乐": "《女神异闻录》音乐",
    "Persona 音乐": "《女神异闻录》音乐",
    # --- 2026-10-22 Gacha Games Have A Villain Problem 二校沉淀 ---
    #   生僻长键；「枫丹」因与《原神》枫丹同形不入表（#650 幻胧走逐 cue）。
    #   边狱公司：官方名订正（旧 canonical「边狱巴士」见 ENTITIES 同步修正）。
    "边狱巴士": "边狱公司",
    "林布斯公司": "边狱公司", "林布连": "边狱公司",
    "方丹利亚": "幻胧",                       # Phantylia（#950；ASR Fontainlia）
    "公爵的舞会地狱": "冥火大公",              # Duke Inferno（#950）
    "绝对的身体": "借来的身体",                # A borrowed body（#651）
    "掠夺者领主": "绝灭大君",                  # Lord Ravager（#651）
    "阿姆·法瑞厄斯": "翁法罗斯",              # Amphoreus（#954）
    "阿刻隆": "黄泉",                          # Acheron（#668）
    "崩坏星穹铁道": "《崩坏：星穹铁道》",
    "《崩坏星穹铁道》": "《崩坏：星穹铁道》",
    # --- 2026-10-23 Journey Well'ed（Juno 的鸣潮 3.1 拉海洛实况）二校沉淀 ---
    #   鸣式 / 拉海洛 / 爱弥斯 的 ASR 变体，均为唯一串、无级联风险。
    #   ⚠ 阿列夫->阿列夫一 绝不进扁平表（扁平表无哨兵，已存在的「阿列夫一」会被咬成「阿列夫一一」），只走 CONTEXT_MAP。
    "Fernodian": "鸣式", "tenonian": "鸣式", "Thronodium": "鸣式",   # Threnodian 误听（与 Frenodian/Threnodian 可共存）
    "highroys": "拉海洛",                                            # the highroys people（#1001）
    "Amth": "爱弥斯",                                                # Aemeath 截断（#275）
    # --- 2026-10-24 鸣潮新加坡音乐会 vlog（zKodla，578 cue）二校沉淀 ---
    #   官方依据：巡演《致予新世界》、安可 Encore、露帕 Lupa、百胜站 Bras Basah。
    #   英文键均区分大小写（_replace_report 用 str.replace），不会误伤普通 anchor。
    #   裸键「水浪」「锚点」「锚」是普通词，只走下面的 CONTEXT_MAP 参考行锚定。
    "Weathering Waves": "鸣潮", "Weathering Wave": "鸣潮",   # ASR "Wu"->"Weathering"
    "浇水波浪": "鸣潮",                                      # Watering Waves 谷翻直译
    "水浪经历": "鸣潮经历",                                  # watery wave 谷翻（长键，避免裸「水浪」误伤）
    "安科尔": "安可", "Ankor": "安可", "Anoro": "安可",       # Encore 角色（#536/#547/#551）
    "卢帕": "露帕",                                          # Lupa（#544/#572；非 ko 实体可复用）
    "Zikatla": "zKodla",                                     # 主播名 ASR（频道 @Kodla）
    "铜巴萨站": "百胜站",                                    # Bras Basah 地铁站（#55）
    "西班牙戏剧领域": "滨海艺术中心剧院",                     # Esplanade Theatre 误译（#535）

    # --- 2026-10-25 鸣潮 4.0 新联邦 reaction 片（474 cue）二校沉淀 ---
    # 官方中文依据：新联邦/星炬学院/泰缇斯系统/无归的谬误/索诺拉/角/残星会/守岸人/
    # 漂泊者/陆·赫斯/莫宁/洛瑟菈/爱弥斯/阿布拉克萨斯/伊冯。扁平键只收生僻长键；
    # 通用词（学院/联邦/莫尔/穆/杰尔/乔尔）一律走 CONTEXT_MAP 参考行锚定。
    "茶系统": "泰缇斯系统", "茶叶系统": "泰缇斯系统",
    "Tea system": "泰缇斯系统", "Tea System": "泰缇斯系统",
    "Luke Herson": "陆·赫斯", "卢克·赫尔森": "陆·赫斯",
    "Ivonne": "伊冯", "Ivon": "伊冯",
    "Sonaro 球体": "索诺拉", "Sonoro 球体": "索诺拉",
    "弗拉杜斯": "残星会",
    "Fractus": "残星会", "fractus": "残星会",

    # --- 2026-10-25 《How Did You Join Arknights or Endfield?》首轮+二校沉淀 ---
    # 只收长专名/唯一键；「阿拉斯加」「Aen/Aken」「ZZ」走 CONTEXT_MAP，不做裸键。
    "Arthates": "明日方舟", "阿克兰大": "明日方舟",
    "Alter卡纳": "异格卡池",
    "Union Manor": "缘缘庄",
    "Ancient Forge": "《洪炉示岁》",
    "Dragon's Doma": "龙之信条",
    "Sylve": "银灰",
    "Warframe": "《星际战甲》",
    "Sony": "索尼",
    "Halo 战斗": "《光环》战斗",

    # --- 2026-10-25 TRANSCENDO 单文件补丁回灌（源码此前未同步）---
    "X跨步者": "隧者", "额外的跨步者": "隧者",
    "加尔布隆": "嘉贝莉娜",
    "Roachcha": "洛可可",
    "Sonoras": "索诺拉", "Sonora": "索诺拉",
    "索诺拉州": "索诺拉",
    "Canorilla": "坎特蕾拉",
    "卡诺里拉": "坎特蕾拉",
    "丹尼斯": "达妮娅",
    "达妮娅斯": "达妮娅",
    "岁主共鸣器": "岁主共鸣者",
    "字符泄漏": "泄露角色",
    "Woo 刚刚丢": "鸣潮刚刚丢",
    "Transcendo": "超验",
    "超致器": "超验",
    "卡拉西亚": "卡提希娅",
    "屋顶海": "黎那汐塔",
    "雷纳·西": "黎那汐塔",
    # 2026-11-04 官中定案为「伊什梅**尔**」（官网 4.9「流光抛诸寰宇」公告：新增涂装「霜尘拥月」
    #   适用角色 伊什梅尔·幻日），旧目标形「伊什麦尔」系错知识；改对后「伊什梅尔→自身」成恒等键，
    #   故删除。⚠ 该裸键仍会吃掉《边狱巴士》主角官中「以实玛利」，两侧英配同为 Ishmael 无从锚定区分。
    "以实玛利": "伊什梅尔",
    # --- 2026-10-27 鸣潮「索诺拉」活动 / Kiri Ahri 演唱会片二次校准沉淀 ---
    # 2026-10-30 修正：官方译名对照「心之集域 = Somnoire」，索诺拉是 Sonoro Sphere；
    #   原映射把梦境领域改成了另一个活动名（Jadealy TRANSCENDO 片 #635 实证）。
    "Somnoire": "心之集域", "Som Noir": "心之集域", "Somnir": "心之集域", "Somnoir": "心之集域",
    "Sonoro Sphere": "索诺拉", "Sonoro Spheres": "索诺拉",
    # 抓包玩家/书呆子是 gacha ASR 误译的限定长键，不影响技术语境「抓包」。
    "抓包玩家": "抽卡玩家", "抓包书呆子": "抽卡书呆子",
    # --- 2026-10-27 《Back from Vacay! Music Listening Stream》二次校准沉淀 ---
    # 片源 2794 cue，英语原声 + 谷翻；官方依据见脚本技能卡与本片 -校准-r2说明.md。
    # 戒律：只收安全长键/专名；通用词（Demo 2 / Morta / Wua / 陶笛 / 恩菲尔德 / 努尼）
    #       一律走 CONTEXT_MAP 参考行锚定，禁止裸键。
    "无限裸体": "无限暖暖",
    "水枪2": "斯普拉遁2", "Suicadin 2": "斯普拉遁2",
    "卡比星球罗博特": "星之卡比：机器人星球", "罗布特星球": "星之卡比：机器人星球",
    "Hungai Impact Third": "崩坏3", "Hankai impact": "崩坏3",
    "Phenom Blade Zero": "影之刃零",
    "Expedition 33": "光与影：33号远征队", "远征33号": "光与影：33号远征队", "远征33": "光与影：33号远征队",
    "Final Fantasy Residence": "最终幻想：共鸣",
    "Beer Leos": "柏辽兹", "symphony fantastic": "《幻想交响曲》",
    "Alzo Sarathustra": "《查拉图斯特拉如是说》", "harps accord": "大键琴",
    "Heart Seal": "HEARTSTEEL",
    "Kayla Mena Kyn": "凯恩",
    "Moonlight Wilderness": "Moonlit Wilderness",
    "Gundam Rogue Orbit": "GUNDAM 异轨征途",
    "Mongol Star Dive": "魔御：STAR DIVE", "Mongil Star Dive": "魔御：STAR DIVE",
    "Silver Palace": "白银之城",
    "Drippy": "拙皮",
    "Wizardry Proving Grounds of the Mad Overlord": "巫术：狂王的试炼场",
    "特瑟斯": "泰缇斯", "特图斯": "泰缇斯",
    # --- 2026-11-13 《I KNEW WUTHERING WAVES WAS COOKING》（MarcoMeatball，324 cue，默认 bi）TRANSCENDO 精校回灌 ---
    # Tethys 官方中文=泰缇斯（BWIKI 守岸人档案正文统一用字，泰+绞丝旁缇）；机翻/ASR/误沉淀错形一并归正：
    "特提斯": "泰缇斯", "Tedha": "泰缇斯", "忒提斯": "泰缇斯", "泰提斯": "泰缇斯",
    "Short Keeper": "守岸人", "短守门": "守岸人",                  # Shorekeeper 机翻/ASR 错形
    "弗里洛娃": "弗洛洛", "Furilova": "弗洛洛",                    # Phrolova 弗洛洛
    "弗拉克西努斯": "残星会", "Fraxinus": "残星会",                # Fractsidus 残星会（Hydra 系成员代号，官方中文未实装，保留英文）
    "Juet": "角",                                                  # Jué 官方中文「角」（今州岁主；长键防裸键 Jue 咬剩「角t」）
    "乌玛·米苏姆": "赛马娘", "乌姆·米苏姆": "赛马娘",
    "Dimma 2": "花雨旋律",
    "Demo 1 and Demo 2": "《古树旋律》和《花雨旋律》",
    # --- 2026-10-27 鸣潮 5h47 巡演/EP 二次校准（BILINGUAL）---
    # 依据：Roya=罗伊族；Blade Runner=《银翼杀手》；First and Last Gift=《最初和最后的礼物》；
    #       Itasha Coffee 产品名 Driving Me Nuts。
    "罗伊人": "罗伊族",
    "Bladeunner": "《银翼杀手》",
    "Blade Runner": "《银翼杀手》",
    "《First and Last Gift》": "《最初和最后的礼物》",
    "Drive Immune Nuts": "Driving Me Nuts",
    # --- 2026-10-28 wuwa_glossary.tsv 并入（104 行→本表 40 条；行号=原表行号，原表已归档）---
    # 依据：鸣潮官方中文（EN/ASR 误拼 → 官方中文）。只收专名/单义音译名；
    #   通用词与武器类（Sword/Pistol/Gauntlet/Rectifier 等）走 WUWA_MISSING_CHECK 只体检不改写。
    #   ⚠ 华胥研究院：原表写作「华虚学院」为错译，按 entities_part2.py 的官方名纠正。
    # 角色
    "Yangyang: Xuanling": "秧秧·玄翎",                    # wuwa:4
    "Xuanling": "玄翎",                                   # wuwa:5
    "Chixia": "炽霞",                                     # wuwa:6
    "Baizhi": "白芷",                                     # wuwa:7
    "Jianxin": "鉴心",                                    # wuwa:10
    "Taoqi": "桃祈",                                      # wuwa:11
    "Yuanwu": "渊武",                                     # wuwa:12
    "Mortefi": "莫特斐",                                  # wuwa:14
    "Zhezhi": "折枝",                                     # wuwa:16
    "Youhu": "釉瑚",                                      # wuwa:18
    "Camellya": "椿",                                     # wuwa:22
    "Phoebe": "菲比",                                     # wuwa:25
    "Brant": "布兰特",                                    # wuwa:26
    "Carlotta": "珂莱塔",                                 # wuwa:29
    "Qiuyuan": "仇远",                                    # wuwa:38
    "Lynae": "琳奈",                                      # wuwa:40
    # 机制/技能名
    "Resonance Liberation": "共鸣解放",                   # wuwa:61
    "Forte Circuit": "共鸣回路",                          # wuwa:62
    "Inherent Skill": "固有技能",                         # wuwa:63
    "Tune Rupture": "谐度破坏",                           # wuwa:64
    "Cadence Interference": "集谐·干涉",                  # wuwa:65
    "Cadence Shift": "集谐·偏移",                         # wuwa:66
    "Nameless Hero": "无名英雄",                          # wuwa:69
    "Tacet Field": "无音区",                              # wuwa:75（原表写「残象领域」，表内已纠正为无音区）
    "Aleph One": "阿列夫一",                              # wuwa:86
    "Remnant Energy": "残响能量",                         # wuwa:87
    "Stattrace": "深塔",                                  # wuwa:102
    "Whimpering Wastes": "海墟",                          # wuwa:103
    "Simulated Universe": "模拟域",                       # wuwa:104
    # 地名
    "Black Shore": "黑海岸",                              # wuwa:70
    "Huaxu Academy": "华胥研究院",                        # wuwa:72
    "Seven Hills": "七丘",                                # wuwa:81
    "Xuanfang": "玄方",                                   # wuwa:82
    "Mingting": "明庭",                                   # wuwa:84
    # 属性（鸣潮专名，非通用词）
    "Spectro": "衍射",                                    # wuwa:89
    "Havoc": "湮灭",                                      # wuwa:90
    "Glacio": "冷凝",                                     # wuwa:92
    "Electro": "导电",                                    # wuwa:93
    "Aero": "气动",                                       # wuwa:94
    # --- 2026-10-28 《索拉逐星舞台 第二季》reaction 片（774 cue，英语原声+谷翻，bi）---
    #   官方依据：B站官方节目 BV1DzpG6CEEH 节目单 + 官方角色名 + 抽帧目视
    #   （Startorch Kindergarten / Battle of The Mascot / 罗伊冰原片尾 credit）。
    #   仅收唯一长键；通用词/短名一律走下方 CONTEXT_MAP 参考行锚定。
    "皇家霜地的救世主": "罗伊冰原的小小救世主",   # #434 官方节目名 Savior from Royal Frostland
    "超级环球师": "超级露帕",                     # #348 Super Looper 谷翻音译错形
    "卢瓦法": "露帕",                             # #216 Loofa's 谷翻音译
    "游侠踢": "隧者这一脚",                       # #521 Strider=隧者（片尾 credit：LahaiRoi-Human Glazer Exostrider）
    "流浪者队": "漂泊者",                         # #5 Rovers 复数，既有 \bRover\b 锚不命中
    "Lufa": "露帕",                               # #221 中文行残留拉丁
    "Loofa": "露帕", "Loofa's": "露帕",            # 未来中文行残留拉丁
    "Super Looper": "超级露帕",
    # --- 2026-10-28 《INSANE LORE DROPS…TRANSCENDO》reaction 片（737 cue，英语原声+谷翻，bi）---
    #   官方依据：世界观 PV「超验 TRANSCENDO」官方中文；瑝珑岁主「角」/梦州「心月狐」/
    #   泰缇斯系统/索诺拉/黎那汐塔/无归的谬误。只收实测错形，通用词走 CONTEXT_MAP。
    "索姆诺尔": "心之集域",                     # somnoir 旧译形（#496/#518）；2026-10-30 由「索诺拉」修正
    "岸守者": "守岸人",                         # 裸键「岸守」叠出的残形（#439）
    "守岸人者": "守岸人",                       # 上一条替换后的机械残形，兜底
    "巴拉纳夫拉": "蛇菰", "巴拉诺尔瓦": "蛇菰", "贝拉纳弗拉": "蛇菰",  # Balanophora ASR 三形（#159/#162/#171）
    "克里斯托福罗": "克里斯托弗",               # Cristoforo 谷翻音译（#188）
    "克罗诺迪安": "鸣式",                       # Threnodian 音译（#505）
    "theodians": "鸣式", "cronodian": "鸣式",   # 中文行残留拉丁（#542/#505）
    "Slayer 3": "索拉里斯-3",                   # Solaris 3 的 ASR 形（#336）
    "Solaris 3": "索拉里斯-3",                  # 统一官方写法（长键先行）
    "Hangla": "瑝珑",                           # 中文行残留拉丁（#640）
    # --- 2026-10-30 Jadealy《TRANSCENDO》reaction 片二次校准沉淀 ---
    # 只收官方长键/专名；通用词一律走 CONTEXT_MAP 参考行锚定（见下方同名日期块）。
    "Tacetite": "黑石", "tacetite": "黑石",      # 官方专有名词：黑石=Tacetite
    "White Tower": "纯白之塔",                  # 官方：纯白之塔（鸣式）
    "Luuk Herssen": "陆·赫斯",                  # 官方全名 LUUK HERSSEN
    "祖尼": "赞妮", "祖妮": "赞妮", "赞尼": "赞妮",  # Zani 的 ASR 变体（本片 #358-#362）
    # --- 2026-11-02 《Music Listening Stream! HALLOWEEN EDITION》三次校准沉淀 ---
    # 片源：MarcoMeatball 万圣节音乐点听直播，3376 cue，英文 ASR + 谷翻中文。
    # 只收「错形为拉丁专名」或「唯一多字中文形」的安全长键；每个官方简中形都有官方来源（见 _doc.py 同日 changelog）。
    # ⚠ 刻意不收（禁裸键，只能逐 cue 重写）：共振（物理通用词，且本名 FINAL FANTASY RESONANCE 官方**无简中译名**）、
    #   影障守护者（它是正确形《龙腾世纪：影障守护者》的子串，入表会自咬成双前缀）、
    #   米卡伊尔/沃拉/朵拉（同一角色的 ASR 断词，收裸键会伤他作同名）、Carman/Kman（常见姓氏与短串）、
    #   地狱不/病得很厉害/音乐反应器/非常富有（通用词误译，术语表管不到）。
    "Evercold": "银海之天舟",                     # 盛趣官方专题站；FFRS_TERMS 早有，但 bi 通路必须同表登记才生效
    "Village in the Shade": "静谧田园", "荫村": "静谧田园",   # Steam 简中商店页 app/3934250「name: 静谧田园」
    "WoW Forever": "魔兽世界：无限", "Wow Forever": "魔兽世界：无限",  # 暴雪国服公告 wow.blizzard.cn（正式产品，非私服）
    # 2026-11-04：ASR 常把 Wuthering Waves 缩写成 "WoWa"，谷翻原样留在中文行（实测
    #   SenWarchief 鸣潮音乐片 #3/#8/#18 共 3 处）。拉丁专名键，与上一行的 "WoW Forever"
    #   不互相命中（_replace_report 按长键降序，先咬 11 字符那条）。
    #   ⚠ 只收 WoWa，**不收裸 "WoW"**：真·魔兽片的参考行同样写 WoW，全局改会把
    #   「魔兽世界」咬成「鸣潮」——实测本片 #98 "WoW has to offer"、#555 "other World of
    #   Warcraft music" 只能逐 cue 覆盖（见 _doc.py 2026-11-04 条）。
    "WoWa": "鸣潮",
    "Yonowari": "夜回", "Yomawari": "夜回",       # Steam 简中页「由"夜回"系列制作团队打造」；Yonowari 是 ASR 形
    "Krasue": "克拉苏",                           # Steam 简中页 app/4019590「恐怖杀手"克拉苏"…《黎明杀机：邪恶恩典》」
    "Dragon Song": "Dragonsong",                  # FFXIV 国服客户端形为连写《Dragonsong　-千年龙诗-》
    "Horus Stes Alti": "Hortus Regis Alti",       # 皇牌空战8 曲目（Lindsey Stirling），ASR 切碎形
    "Mistia": "米斯蒂娅·萝蕾拉",                    # 官方简中设定集《东方Project人物名鉴 宵暗篇》（天闻角川）
    "Monster Musu": "魔物娘的同居日常", "怪物穆苏": "魔物娘的同居日常",  # Monster Musume（官网域名 monmusu.tv 自证）
    "Veldora": "维鲁德拉", "维尔德拉": "维鲁德拉",   # B站正版番剧声优表 + 百科主词条「维鲁德拉·特恩佩斯特」
    "吃豆人世界": "吃豆人 吃遍世界",                 # 万代南梦宫官方简中游戏名（PAC-MAN WORLD Re-PAC）
    "Craman": "摄像师", "Kraman": "摄像师",          # cameraman 的吞音连读，**不是**合作者姓名（片内「摄像师不是我妻子」自证）
    "Lemidos": "雷米迪奥斯", "雷米多斯": "雷米迪奥斯",  # DNF 官方简体（太初神明 Remedios）
    "米凯拉": "米歇尔",                             # DNF 第十使徒官方简体，外文名即 Michaela（dnf.qq.com 官方前瞻）
    "Paulina Oatinskaya": "Polina Osetinskaya",   # 原神官方通稿用拉丁原名，且 ASR 拼错
    # --- 2026-11-02 《鸣潮》First Time Reacting to ALL Resonator & Combat Showcases! Part 1
    #     （英语原声+谷翻中文，3546 cue，英文参考行在上）二次校准沉淀 ---
    # 收录纪律：只收「本片中文行里实测出现过该形态」的键。拉丁名若**仅**出现在参考行
    # （Changli/Cartethyia/Cantarella/Galbrena/Zani/Augusta 实测中文行 0 次），一律不建裸键，
    # 改登记到 WUWA_MISSING_CHECK 做体检——否则是永远命中不到的死键，还会污染跨游戏默认表。
    "Genshin": "原神", "Genshin Impact": "原神",
    # ↑ 上游长键。旧表只有 "Gens hin"/"Gens"(短键)，_replace_report 逐条 replace 时
    #   短键吃掉 Genshin 的前 4 字母，产出「原神hin」尾巴（本片 #184/#776/#3127 实测 3 处）。
    "Zenless Zone Zero": "绝区零", "Zenless Zone": "绝区零",
    # ↑ 同理，旧 "Zenless" 单独命中会产出「绝区零 Zone」（本片 #1690 实测）。
    #   ⚠ 必须同时收 "Zenless Zone"：#1690 参考行是 ASR 吞尾的 "Nicole from Zenless Zone"，
    #   没有 Zero，只收全名会漏（2026-11-02 候选基线实测残留）。长键降序保证
    #   Zenless Zone Zero > Zenless Zone > Zenless 依次先命中。
    "Amethy": "爱弥斯",   # 旧 "Amth" 咬出「爱弥斯y」（本片 #94）。⚠ 已知代价：Amethy 是
                          #   Amethyst 的子串，收 Amethyst→爱弥斯 会误伤方舟/FFRS 片，故**不收**，
                          #   宁可留 Amethyst 的既有产出。
    "Ragon": "拉古那",     # ASR 吞掉词尾，官方 Raguna/Ragunna=拉古那（本片 #1625 中文行实测残留）
    "Mavika": "玛薇卡", "Mavica": "玛薇卡", "Mabuika": "玛薇卡", "马维卡": "玛薇卡",
    # ↑ 原神纳塔官方中文=玛薇卡。⚠ 勿与「玛拉妮」(Mualani/Malani) 混：本片 #3356 参考行
    #   确为 Malani，故该处「玛拉妮」是正解，不建 玛拉妮→玛薇卡 的键。
    "蒙特利": "莫塔里",    # Montelli 家族官方中文=莫塔里（库街区 WIKI 名词注释+角色页互证）。
                          #   旧 ctx 只锚「蒙特利斯」，覆盖不到「蒙特利」→ 本片 #1530/#1537 漏校。
                          #   ⚠ 蒙特利 ⊂ 蒙特利尔(Montreal)，已配 EXCLUDE_CONTEXT 负例兜底。
    "查米利亚": "椿",      # 旧表只有「查米莉**亚**」(莉≠里)，本片 #2734 实测作「查米利亚」
    "卡蒂亚": "卡提希娅",  # Cartethyia 官方中文；#2746 同句并存 卡蒂亚/卡地亚 两形
    "伍霸": "鸣潮",        # Wuba=WuWa 口播；本片 #3076 漏校（#3405 同类已由人工改）
    # （此处不留「机傀师→傀儡师」裸键：实测产出是「机傀动画」#1090 与「机傀戏」#2080，
    #   长键覆盖不到；统一交给 CONTEXT_MAP 用 \bpuppeteer 参考行锚定，见该表末尾。）
    "想象剧场": "幻想真境剧诗",  # 原神玩法官方中文名（本片 #3155 与 Spiral Abyss 并列提及）
    # --- 2026-11-06 《All 60 Wuthering Waves Gacha Animations REACTION 1.0→3.7》三校沉淀 ---
    # 片源：Izaya's Hub，449 cue，英语原声 + 微软翻译中文。bi 术语基线仅命中 15 处，
    # 价值全在逐 cue 重写；本块只收「本片中文行实测出现过该形态、且错形本身非通用词」的长键。
    # ⚠ 刻意不收（入表必误伤，只能逐 cue 覆盖）：
    #   赤刃/风之冠/果壳/死局/冰原/恶性循环/日间问诊/健康维护/春天在等待/藏在心里/抬头查找——
    #     这些是**官方「初奏」台词与机翻回译之间的措辞差异**（绯刃/流风冠冕/果壳中/切开这个死局/
    #     冻土之下/午后谈心时间/调息养生/自有春山可望…）。台词串不是通用术语，收裸键等于拿
    #     另一款片的句子去改正常句子。
    #   终极者（ultimates 误译）、转动横幅/转动卡池（spin the banners）——通用词/动宾结构，
    #     交逐 cue 重写；「大招/抽卡」本身也绝不入表。
    #   纳维娅/艾什莉/露比/丽贝卡（原神·生化危机·RWBY·赛博浪客的另一音译）——现实常见译名，
    #     跨 IP 且可能同名真人，只走窄英文锚定或参考行体检，不建中文裸键。
    "四维超方": "宇宙魔方",   # Tesseract 的**子词直译路径**（与 Exo+strider 判例同族）；本片 #104
    "韦尔特": "瓦尔特",        # Welt 官方简中=瓦尔特（星穹铁道/崩坏3）；本片 #44 三次「韦尔特」
    "Jing Jo": "今州",     # 带空格 ASR 形（#884 实测），与 :75 的 Jingjo/Jingo 同族

    # --- 2026-11-06 奏咲ルリ《鸣潮 3.2 完全初見 PV 鉴赏会》（日语原声+微软翻译，3164 cue）二次校准回灌 ---
    # ★ 本轮漏校的**结构性根因**：下面 5 个官中名早已登记在 JA_TERMS（ja.py:30/68/123）与
    #   JA_CONTEXT（ja.py:394），但 bi 表一条都没有；而 detect_source_mode 只认终末地，
    #   日语原声片一律落 bi ⇒ --bi 通路对 名長/超月会/新様/师大人/脅迫者 全程零产出，
    #   整片留在这批机翻错形上（实测同一片 ja 通路命中 11 键、bi 通路 16 键但**无一个交集**）。
    #   同 2026-11-02「ko 只挂 bi/ja」、2026-11-01「只在 bi 登记故 --ja 不产出」——第四次踩同坑。
    #   修法沿用既有约定：bi 侧补同形裸键，不删 ja 条目、不改 modes 投影，令两通路等价。
    # ★★ 键一律取**中文行实际形态**（谷翻把日文错转成中文错形，日文原形不落中文行；
    #   登记日文形＝死键，永远命中不到。同 2026-11-03「键必须写源文件形态」判例）。
    #   下列计数为改前机翻源中文行实测：七永2 超月会1 日光六号5 日光式3 弗拉西德斯1
    #   Fractacid1 Start Academy2 卡特西亚1 果糖1 游击者1 勒索者1 硅藻土1 新大人3 志士大人2
    #   师大人2 石先生2 石族1 名式0（名式在参考行侧，非中文行）
    "七永": "鸣潮",              # ← 名長（#9「诶，七永，嗯？」/#2895/#3060）；ja.py:123 同族形
    "名長": "鸣潮",              # 兜日文汉字原形直搬的片源（本片中文行 0 次，ja 通路主用）
    "超月会": "朝月会",            # ← ちょうげつかい（#2151/#2154/#2196）；ja.py:68 既有，bi 补齐
    "日光六号": "秘日六席",         # ← ヘリオディックシックス 直译（5 处：#311/#322/#323/#364/#375）
    "日光式": "秘日六席",           # ← ヘリオディック 按"式"直译（3 处：#312/#336/#391）
    "弗拉西德斯": "残星会",         # ← フラクシデス=Fractsidus（#481；同族 弗拉杜斯/弗莱杜斯 已在表）
    "Fractacid": "残星会",        # ← フラクトシデス 被 ASR 听成英语后原样保留（#124）
    "Start Academy": "星炬学院",     # ← スタート学園（#36/#948）；官方全称「深空联合：星炬学院」
    "卡特西亚": "卡提希娅",         # ← カルテジア（#2849）；2026-11-02 已裁定官中=卡提希娅
    # ↓ 其余本片错形本身是**常用中文词**（新大人/果糖/游击者/勒索者/硅藻土/仪式…），
    #   按硬契约第 4 条禁裸键。其中只有 シリカ→硅藻土（西格莉卡错形）在 CONTEXT_MAP
    #   补了一条窄锚（见该表末尾「奏咲ルリ」块）；其它 心(Shin)/残星会/隧者/漂泊者 的
    #   同形异义族已由 **ja 通路 JA_CONTEXT 承担**（ja.py:394 脅迫者、果糖、隧者锚等），
    #   bi 通路**不重复登记**——这些日文锚一旦进跨游戏默认表就会误伤别的日语片，
    #   留待逐片 --ja 或人工逐 cue（同 2026-11-04「不为单片收窄全局规则」判例）。
    #   ⚠「日光六号/日光式/七永/超月会」等虽含常用字，但作为**整体串**在正常中文里
    #   不会连写（实测全库仅本族错形命中），故留裸键安全；terms-check 已验 0 二次命中。

    # --- 2026-11-07《I have NO Idea What to Expect!! Wuthering Waves 3.8 Dev Stream》
    #     英语原声 reaction（MarcoMeatball，2699 cue，bi，CRLF 无 BOM）二次校准回灌 ---
    # 只收「整体串唯一、不撞常用词」的系统性错形；裸键 陷阱/小径/隐喻/星轨/哈农/韩龙/
    # 田霏宇/声纳/相扑/帕隆 等按硬契约第 4 条一律不入本表，改走 CONTEXT_MAP 英文锚定。
    "新美联储": "新联邦", "新任美联储": "新联邦", "新的美联储": "新联邦", "新喂养": "新联邦",
    "索莫尔": "心之集域", "索米尔": "心之集域",       # Somnoire 音译错形（索诺拉/声纳/相扑 走锚定）
    "幻影之刃": "影之刃零", "幻刃零式": "影之刃零", "幻刃零": "影之刃零", "芬之刃零": "影之刃零",
    "加尔雷纳": "嘉贝莉娜", "Alrena": "嘉贝莉娜", "Galrena": "嘉贝莉娜",
    "雷尼塔": "黎那汐塔",                             # Renita=Rinascita 音译错形
    "须梅鲁": "须弥", "Sumeu": "须弥", "Sumero": "须弥", "苏美罗": "须弥",
    "胡安龙": "瑝珑",                                 # Huanglong（韩龙/弘工/哈农 走英文锚定）
    "南岛之魂": "对马岛之魂", "泽尔传说": "塞尔达传说",
    "信任第二": "空之轨迹 the 2nd", "星辰之刃": "剑星",
    "博德斯之门": "博德之门", "弧光明日方舟": "明日方舟",
    "星轨铁路": "星穹铁道",                           # 裸「星轨」走锚定（本片 #617 star path≠Star Rail）
    "原神溪": "原神直播",
    "Genchin": "原神", "Ginchin": "原神", "Kenchin": "原神", "Genjin": "原神",
    "inuma": "稻妻", "Inuma": "稻妻",
    "Pentaconi": "匹诺康尼", "Scaramoosh": "散兵",
    "Laairoyy": "拉海洛", "La Hiroya": "拉海洛", "La Hiroy": "拉海洛", "La Heroy": "拉海洛",
    "Yangyuk": "秧秧", "Yangyong": "秧秧", "Yongyong": "秧秧", "Yongyang": "秧秧",
    # --- 2026-11-08 鸣潮 3.8 Lily 前瞻 reaction 片二校回灌 ---
    # 雪平贵飞=Hiyuki 的 ASR/机翻乱码，整串唯一；第二索拉里斯学院→官中「第二索拉学院」。
    "雪平贵飞": "绯雪",
    "第二索拉里斯学院": "第二索拉学院",

    # --- 2026-11-09 同片二次校准回灌（二校漏校补全；键均为完整串/整句，子串替换不误伤）---
    "天魁劫煞": "天傀劫煞",                          # 官中声骸名（ko.py 已收 ASR 族，bi 表补齐缺映射）
    "金属动机丝带": "金属图案丝带",                  # Metallic pattern ribbon；pattern=图案（CONTEXT_MAP 另锚，区别 motif）
    #   ⚠ 2026-11-09 WuWa 3.8 REACTION 片三轮**移除**「绩为目标→以成绩为目标」（原 11-09
    #   同批回灌）：键虽标"整串唯一"，却是 4 字片段，会命中正常句「以取得最高成绩为目标」
    #   （成[绩为目标]子串），产出病句「以取得最高成以成绩为目标」——本片 cue374 实测 A 类
    #   真跑改坏。按「不入裸键」沉淀：原片错形若复发，须以**完整错形句**为键或带参考行锚
    #   回灌，不得恢复裸片段键（2026-11-09 三轮实测教训）。
    "不过他是怎么和列车甚至亡魂扯上关系的呢": "不过她是怎么和列车甚至亡魂扯上关系的呢",  # 指莉莉，人称漏改
    "因此，I need one more Cam ell ia.": "所以我还需要再抽一个椿",  # 中英混合漏译整句（整句唯一）
}


# 保留英文不译的专名（仅提示，不替换）
KEEP_EN = {"Crywolf", "Among Us"}
# ↑ Crywolf＝曲师名（终末地「向渊行」OST credit），Among Us＝游戏本名，均无官方中文。
#   ⚠ Saving Light **2026-11-07 移出本集合**：官方中文名《致新世界》（萌娘百科
#   《Saving Light（致新世界）》+ QQ音乐/酷我「致新世界 Saving Light」+ 官方 OST 上架公告），
#   music.py `_MUSIC_WW` 早已登记 `致新世界（Saving Light）`；2026-11-02 那句"官方题名保留英文"
#   只看了官方英文视频标题，是把**英文名**当成"无中文名"，已由 CONTEXT_MAP 同名锚定纠正。
#   注意本集合仅作知识登记，引擎不据此改写。


# 上下文相关替换：仅当 参考行 命中该英文正则时才把中文里的错误形式替换掉（仅双语模式）
# 2026-10-20 3.7 后日谈：Schwanqing/Swan Ching 的英文锚点（旧规则目标曾误沉淀为「玄方清」）
_XQ_RX = r"\bSchwanqing\b|\bSchwan\s*Ching\b|\bSwan\s*Ching\b|\bSchwan\s*ching\b|\bSwanching\b"

CONTEXT_MAP = [
    # (英文正则, 仅当英文行匹配时才把中文里的某错误形式替换为正确形式)
    # --- 2026-11-11 鸣潮 3.8 莉莉 PV《忘记恐惧》reaction 二校：Dr. Lily 官方中配=莉莉医生 ---
    # 谷翻把 Dr. Lily 译「莉莉博士」，官方中配 PV（B 站 BV1VmW46bEfC p1，large-v3 中文 ASR）实为「莉莉医生」；
    # 「莉莉博士」含 canonical「莉莉」，不能走 Entity ctx（会归到莉莉），故用 CONTEXT_MAP 指定正确形。
    (r"\bDr\.?\s+Lily\b", "莉莉博士", "莉莉医生"),
    # --- 2026-11-12 鸣潮 3.8 莉莉 PV 韩语反应片二校：谚文锚定官方定名 ---
    # 英文锚（Dr. Lily）命不中韩语参考行；同一组错形再挂 릴리/릴님 锚。
    (r"\bDr\.?\s+Lily\b", "莉尔医生", "莉莉医生"),
    (r"\bDr\.?\s+Lily\b", "莉莉·韩博士", "莉莉医生"),
    (r"릴리|릴님", "莉莉博士", "莉莉医生"),
    (r"릴리|릴님", "莉尔医生", "莉莉医生"),
    (r"릴리|릴님", "莉莉·韩博士", "莉莉医生"),
    # 연방/공방/전선/정신적 외상：只做韩语参考行锚定，禁裸键（英联邦/联合会/车间 是正常中文词）。
    (r"연방", "英联邦", "联邦"),
    (r"연방", "联合会", "联邦"),
    (r"연방", "为联邦城工作", "为联邦城服务"),
    (r"공방", "车间", "工坊"),
    (r"전선", "线化", "前线"),
    (r"전선", "电汇", "前线"),
    (r"정신적\s*외상|향수\s*치료", "心理创伤", "精神创伤"),
    # --- 2026-11-13 선약 방송국 EP3.8 韩语反应片（bi）：发声标注统一，微软译法漂移 ---
    # [콧방귀]（哼鼻声）本片误译 [哼哼屁声]/[哼哼声]/[嗤之以鼻]；只挂韩语锚、禁裸键。
    # 不收 [웃음] 的「（笑）」：「（笑声）」含该子串，逐键 replace 会产出「[笑声]声」残字，
    # 该形（本片 cue46 落叶（笑））走 sidecar 覆盖，不入 CONTEXT_MAP。
    (r"\[콧방귀\]", "[哼哼屁声]", "[哼声]"),
    (r"\[콧방귀\]", "[哼哼声]", "[哼声]"),
    (r"\[콧방귀\]", "[嗤之以鼻]", "[哼声]"),
    # --- 2026-11-01 How Did You Join Arknights or Endfield?（英文原声+微软翻译，3700 cue）---
    # niche/segment 被微软翻译直译成「细分市场/市场细分」（本片 #1372/#1373/#1374/#2326/#2796/#3395）。
    # 「细分市场」是正常中文商业词，禁止作裸键，只在英文确有 niche/segment 时纠正。
    (r"\bniches?\b|\bsegment of the industry\b", "细分市场", "小众领域"),
    (r"\bniches?\b|\bsegment of the industry\b", "市场细分", "小众领域"),
    # --- 2026-10-27 Kiri Ahri 鸣潮演唱会/3.3 片二次校准沉淀 ---
    # Somnoire 类英文锚定：本片谷翻把 somnoir 译成「睡眠」，只在英文行命中时纠正。
    # 2026-10-30 修正目标：Somnoire=心之集域（官方译名对照），不是「索诺拉」。
    (r"\bSomnoire\b|\bSom\s*Noir\b|\bSomnoir\b|\bSomnir\b", "睡眠", "心之集域"),
    (r"\bSomnoire\b|\bSom\s*Noir\b|\bSomnoir\b|\bSomnir\b", "索姆尼尔", "心之集域"),
    # gacha/gotcha ASR 被谷翻成「抓包」；只在英文行命中时纠正。
    (r"\bgot?cha\b|\bgacha\b", "抓包", "抽卡"),
    # coffee addict 被谷翻成「复制者」；只在英文行命中时纠正。
    (r"\bcoffee addict\b", "复制者", "咖啡成瘾者"),
    # 专名常见音译错形（英文行锚定，避免裸键误伤）。
    (r"\bLumi\b", "卢米", "露米"),
    (r"\bElucia\b", "埃露西娅", "埃露西亚"),
    (r"\bElucia\b", "埃卢西亚", "埃露西亚"),
    (r"\bSqueaky\b", "斯奎基", "吱吱"),
    (r"\bAbora\b", "阿波拉", "阿博拉"),
    (r"\bScar\b", "疤痕", "伤痕"),
    # --- 2026-10-25 《How Did You Join Arknights or Endfield?》二校 ---
    (r"\bAK\b", "阿拉斯加", "明日方舟"),
    (r"\bAK\b", "阿拉斯加州", "明日方舟"),
    (r"\bAen\b|\bAken\b", "艾恩", "秋栗"),
    (r"\bAen\b|\bAken\b", "阿肯", "秋栗"),
    (r"\bAen\b|\bAken\b", "Aen", "秋栗"),
    (r"\bAen\b|\bAken\b", "Aken", "秋栗"),
    (r"\bZezy\b", "ZZ", "绝区零"),
    (r"\bZezy\b", "Zezy", "绝区零"),
    # 2026-10-24 《致予新世界》二校：Mourn 是英文普通词，必须靠参考行锚定，
    # 才能安全落到角色莫宁（Mornye）；裸键「哀悼/Mor」不入扁平表。
    (r"\bMourn\b", "《Mourn》", "《莫宁》"),
    (r"\bMourn\b", "哀悼歌", "莫宁的歌"),
    (r"\bMourn\b", "Mor 的歌", "莫宁的歌"),
    (r"\bDena\n?Denia\n?Denu\b", None, None),  # 占位示例，无实际用途
    # --- 2026-10-22 Gacha Games Have A Villain Problem 二校（官方名）---
    # 李恒->雷横 已由 ENTITIES 的无条件变体覆盖，不再重复 context 规则。
    (r"\bLogos\b", "Logos", "来古士"),           # #974/#978/#992 星铁翁法罗斯管理员（ASR 作 Logos）
    (r"\bNous\b", "诺斯", "博识尊"),             # #957 智识星神 Nous
    # --- 2026-08-29 鸣潮 3.6 片源：需参考行佐证的替换 ---
    (r"\bSentinel\b", "哨兵", "岁主"),           # Sentinel 官方译名 岁主
    (r"\bSentinel\b", "月狐岁主心", "岁主心月狐"),  # 语序调整（须在 哨兵->岁主 之后）
    # ── 2026-11-07 收紧 Sushi 锚（实测：本片 cue51/60/69/164/166 五处真食物寿司被误改成「穗穗」）──
    #   原锚 (r"\bSushi\b","寿司","穗穗") 只看「参考行出现 Sushi」，无法区分
    #   ① 鸣潮共鸣者穗穗(Suisui) 的 ASR 形 ② 直播里真·寿司（food）。
    #   本片实证 5 处真食物寿司：c51「>> sushi.」（**参考行只有孤词，无任何食物词可锚**）、
    #   c60「while I indulge in my sushi.」、c69「Man, sushi is a great invention.」、
    #   c164「in love with my sushi.」、c166「that was um a bowl of sushi.」——
    #   说明「靠 EXCLUDE 负例回滚」对 c51 **根本无效**（无词可匹配），
    #   故锚本身必须收紧：改为**双 lookahead**，要求同参考行另见养成/游戏语境词才认定是穗穗。
    #   负例词表（EXCLUDE_CONTEXT["寿司"]）同步扩为第二道防线（享受/器皿/发明/热恋/购买语境）。
    #   官方依据：库洛官网 mc.kurogames.com/main/news/detail/3638「穗穗 SUISUI」为官方名，
    #   本条只保证「ASR 把 Suisui 听成 Sushi」时仍能归正，不动真食物语义。
    (r"(?=.*\bSushi\b)(?=.*\b(?:wuthering|resonator|suisui|gacha|pull(?:ing|s|ed)?|banner|rover|echo|tacet|sentinel|cartethyia|calcharo|chixia|shorekeeper|phrolova|xiagl|concerto|artifacts?|account|server|patch|version|character(?:s)?)\b)",
     "寿司", "穗穗"),
    (r"\bYang\b", "杨和", "秧秧和"),             # Yang=Yangyang 秧秧
    (r"\bYanging\b", "阳绫", "秧秧"),
    (r"\bMirage\b", "幻界", "蜃境"),             # Mirage realm 官方名 蜃境
    (r"\bMirage\b", "幻境", "蜃境"),
    (r"\bSheen\b", "辛", "心月狐"),              # 月狐 Sheen=心月狐，"辛"作名字译官方全名
    (r"\bSheen\b", "光泽", "心月狐"),            # sheen 被按本意误译
    (r"\bTacit\b", "心照不宣", "残象"),          # Tacit=Tacet Discord 误听（沿 泰莎->残象 先例）
    (r"[Cc]entric", "中心笼", "咎笼"),           # centric cage=Censure 系 咎笼
    (r"[Cc]entric", "中心法院", "咎庭"),         # centric court=Censure Court 咎庭
    (r"\bSchwan Paragon\b", "天鹅典范", "玄Paragon"),  # Schwan=Xuan，须先于"典范"
    (r"\bParagon\b", "帕拉贡沙", "Paragon"),
    (r"\bParagon\b", "帕拉贡", "Paragon"),
    (r"\bParagon\b", "百丽宫", "Paragon"),
    (r"\bParagon\b", "典范", "Paragon"),         # Xuan Paragon 称号保留英文
    (r"\bParagon\b", "至尊者", "Paragon"),
    (r"\bChing\w*", "青沙", "清宵"),             # \b 防 watching 误命中
    (r"\bChing\w*", "青晓", "清宵"),
    (r"\bChing\w*", "清晓", "清宵"),
    (r"\bChing\w*", "清秀秀", "清宵"),
    (r"\bChing\w*", "清秀", "清宵"),
    (r"\bChing\w*", "青茶", "清宵"),
    (r"\bChing\w*", "青查", "清宵"),
    (r"\bChing\w*", "肖晴", "清宵"),
    (r"\bChing\w*", "焦伟杰", "清宵"),
    (r"\bChing\w*", "清修", "清宵"),             # Chingsho（清修亦为普通词，故须参考行佐证）
    (r"\bChing\.$", ">> 清.", ">> 清宵。"),
    (r"\bMuyu\b", "木鱼", "木禺"),               # 反派 Muyu 官方名 木禺（防误伤普通"木鱼"）
    (r"\bTacit\b", "Tacit", "残象"),             # 中文行残留英文 Tacit -> 残象
    (r"\bSentinels\b", "哨兵", "岁主"),          # Sentinel 复数形式
    # --- 2026-09-01 同一鸣潮片源二次精修 补充（带英文佐证，防误伤普通词） ---
    (r"\bFodian\b|\bFedian\b", "佛殿", "鸣式"),   # Fodian/Fedian = Threnodian 变体，仅英文佐证时改
    # 爱弥斯：片源英文原形为完整人名 Imeth/Immeth/Ameth（勿用裸 \bmeth\b——
    #   会误伤 "cosplay meth / little eye meth / Lil Meth" 等非人名场合）
    (r"\b(?:Imeth|Immeth|Ameth)\b", "这个存在", "爱弥斯"),
    # 负向后行 (?<![Ss]hu )：Shu Shin 是溯心(Suxin)的 ASR 变体，不可把其中 Shin 当心月狐
    (r"(?<![Ss]hu )\bShin\b", "申", "心月狐"),  # Shin=Sheen 心月狐（仅英文佐证时改，防误伤"申请/申明"）
    # 2026-10-05 3.7 reaction 片：'Lady Shin'/'Shin Lady' 整词英文残留 → 心月狐女士。
    #   目标≠canonical(心月狐)，必须走 CONTEXT_MAP 三元组；长键先行于实体 ctx 的
    #   单字 'Shin'（ctx 条目在 CONTEXT_MAP 之后追加，故本条先命中、不会残留 "Lady"）。
    (r"\bLady\s+Shin'?s\b", "Lady Shin's", "心月狐女士的"),
    (r"\bLady\s+Shin\b|\bShin\s+Lady\b", "Lady Shin", "心月狐女士"),
    (r"\bLady\s+Shin\b|\bShin\s+Lady\b", "Shin Lady", "心月狐女士"),
    # --- 2026-09-04 THIS_IS_CRAZY_Hsin 二次校准：需英文佐证的常见机翻错词（可复用于抽卡 Reaction 片源）---
    (r"\bswimming\b", "游泳", "锁暝"),             # swimming 是 Suoming(锁暝) 的 ASR 误听，非"游泳"
    # 2026-10-05 3.7 reaction 片：Swarming 同为 Suoming(锁暝) ASR 误听，谷翻按 swarm 本意译成
    #   蜂群/蜂拥/群聚（锚点须同时容纳 EN 修正后的 Suoming，--fix-en 先于 ctx 执行）
    (r"\bSwarming\b|\bSuoming\b", "蜂群", "锁暝"),
    (r"\bSwarming\b|\bSuoming\b", "蜂拥", "锁暝"),
    (r"\bSwarming\b|\bSuoming\b", "群聚", "锁暝"),
    (r"\bSwaming\b|\bSuoming\b", "斯瓦明", "锁暝"),     # #4316 Suoming 音译错形（EN 同步修 Swaming）
    # 2026-10-05 3.7 reaction 片：intendant(州监) 被谷翻成"总监/工作人员"（attendant 为 ASR 漏音节形）
    (r"\b[Ii]ntendant\b|\b[Aa]ttendant\b", "总监", "州监"),
    (r"\b[Ii]ntendant\b|\b[Aa]ttendant\b", "工作人员", "州监"),
    # autopuppet(机傀) 被谷翻成"木偶/自动木偶"（鸣潮片 puppet 均指机傀，ctx 锚英文 puppet 防误伤比喻义）
    (r"\bauto[\s-]?puppets?\b|\b[Aa]utopuppets?\b|\b[Pp]uppets?\b", "自动木偶", "机傀"),
    (r"\bauto[\s-]?puppets?\b|\b[Aa]utopuppets?\b|\b[Pp]uppets?\b", "木偶", "机傀"),
    # autopet(机关宠物) 被谷翻成"自动宠物"
    (r"\b[Aa]utopets?\b", "自动宠物", "机关宠物"),
    # 2026-10-05 3.7 reaction 片：Suming(锁暝) 音译"素明"；Arbiter 官方中文即"御者"（岁主对玩家的
    #   称呼，心月狐官方台词"御者，我们终于见面了"），谷翻两处异译"裁决者"统一回御者
    (r"\bSuming\b|\bSuoming\b", "素明", "锁暝"),
    (r"\b[Aa]rbiter\b|\bAbiter\b", "裁决者", "御者"),
    # 2026-10-05 3.7 reaction 片：小狐狸搭档/呼语 Fox 被音译成"福克斯"（普通名词，应译狐狸；
    #   Moon Fox 称号组合的跨 cue 处由 subfix 整行覆盖为"月狐"）
    (r"\b[Ff]ox\b", "福克斯", "狐狸"),
    (r"\bAbiter\b|\bArbiter\b", "阿比特", "御者"),       # #2088 Abiter=Arbiter 漏音节
    (r"\bAby\b|\bAbby\b", "阿比", "阿布"),              # #5846/#5990 Aby=Abby 阿布（小狐狸搭档）
    (r"\bABBY\b", "ABBY", "阿布"),                      # 中文行大写英文残留（Abby=阿布官方伙伴"Little One"，fandom wiki+学习库 confirmed；2026-10-25 TRANSCENDO 反应片 cue206"与阿布战斗"=PV 岁主-阿布循环语境）
    (r"\bLupa\b", "Lupa", "露帕"),                      # 中文行英文残留（官方中文=露帕；JA ルパ 锚不适用英文片，补英文行锚；2026-10-25 TRANSCENDO 反应片 cue105）
    # 2026-10-05 3.7 reaction 片二次校准：
    # Shranong=Schwanfong(玄方城) ASR 形；Ministry 在梦州语境=谛天鉴（Ministry of Sentinel
    #   Affairs），谷翻按哈利波特梗译成"魔法部"；Ministry of War=军策府/兵部 不含"魔法部"不受影响
    (r"\bShranong\b|\bSchwanfong\b", "施拉农", "玄方城"),
    (r"\b[Mm]inistr(?:y|ies)\b", "魔法部", "谛天鉴"),
    # --- 2026-10-24 鸣潮 3.7 锁暝 PV「契阔」reaction 二校（英文原声 + 谷翻，165 cue）---
    #   官方依据：TapTap 官方 PV「契阔」CV 表（锁暝/蛇菰/九契）、3.7 版本说明、百度百科「锁暝」。
    #   以下错形均为通用中文词/短语，禁止裸键，全部靠英文参考行锚定。
    #   已有规则复用、不重复：Intendant->州监、Ministry->谛天鉴、苏明->锁暝、swimming/Swarming->锁暝。
    (r"\bThe warming is coming out\b", "暖化", "锁暝"),    # #1 Suoming 被听成 the warming
    (r"\bher and Shen\b", "沈", "心月狐"),                  # #13 Shen = Hsin = 心月狐
    (r"\bCycle sever\b", "循环中断", "斩断轮回"),           # #15 招式名意译
    (r"\bSix fold collapse\b", "崩溃六倍", "六重崩解"),     # #22 招式名意译
    (r"\bMetal canopy, full ambush\b", "金属遮阳篷，全面伏击", "铁伞如盖，伏击尽出"),  # #11
    (r"\bIntendant swing\b", "督导挥棒", "州监挥伞"),       # #25 Intendant=州监
    (r"\bAll alone victory\b", "孤独的胜利", "孤身取胜"),   # #100
    (r"\bscale that\b", "把它按比例来衡量", "爬上那玩意儿"),  # #88 scale=攀爬
    (r"\brelieving that day\b", "那天的缓解", "重温那一天"),  # #89 reliving 误听
    (r"\bShe's killed sensible\b", "她杀了理智的人", "她杀过岁主"),  # #65 sensible=Sentinel
    (r"\bgotcha games\b", "明白了，游戏", "抽卡游戏"),       # #109 gotcha=gacha
    # --- 2026-10-24 《Jadealy｜Suoming Trailers》二校（293 cue，英语原声 + 谷翻，bi）---
    #   官方依据：TapTap「锁暝」PV｜契阔 CV 表（锁暝/蛇菰/九契）、3.7 版本说明、
    #   萌娘百科「残星会」、官方 PV 台词「此道，孤身难行，所以……且再陪我多走一程吧。」
    #   蛇菰=Balanophora：An offer / an aphora / Offer a crawl 都是 ASR 形，**不是「巴拉纳福」**
    #   （巴拉纳福是另一形 Balanafor 的旧译）。以下错形均为通用中文/短语，禁止裸键。
    (r"\bAn offer\b", "一种从根部爬行的提议", "蛇菰，在根须间爬行"),
    (r"\ban aphora\b", "一股恐惧从根部爬行", "蛇菰在根须间爬行"),
    (r"\bOffer a crawl\b", "提供一条穿越蛇群的爬行", "蛇菰，在蛇群间爬行"),
    #   已有规则复用、不重复：Intendant->州监、swimming->锁暝、Metal canopy, full ambush->铁伞如盖。
    (r"\bMetal canopy,? full unleash\b", "金属罩全面展开", "铁伞如盖，全面展开"),
    (r"\bSeal evil (?:reign|rain)\b", "封印恶雨", "封印邪恶的统治"),
    (r"\bSeal evil (?:reign|rain)\b", "封印邪恶统治", "封印邪恶的统治"),
    (r"\bFraxus overseer\b", "残星会监督者", "残星会会监"),   # Fraxus=残星会；overseer=会监
    (r"\bthe evil Yasma\b", "邪恶的亚斯玛", "恶瘴"),          # Yasma=Evil Miasma ASR
    #   ⚠ 不沉淀：#157 Keep swimming（无官方台词，直译）、#37/38 tacet mark（本片跨 cue 拆词，
    #   走 subfix）、#145 Dendon swimming（整句特化）、#41 Thundering peace（低置信）、
    #   P word / pulling / aura farm（主播梗或有近似规则）。
    (r"\balt\b|\balult\b|\balted\b|\balsated\b", "替代音", "变身形态"),   # alt=alternate form 变身形态
    (r"\balt\b|\balult\b|\balted\b|\balsated\b", "替代项", "变身"),
    (r"\balt\b|\balult\b|\balted\b|\balsated\b", "替代品", "变身形态"),
    (r"\balt\b|\balult\b|\balted\b|\balsated\b", "替代形态", "变身形态"),
    (r"\balsated\b", "阿尔萨德", "变身"),
    (r"\bpower creep\b", "力量蔓延", "强度膨胀"),   # power creep 抽卡游戏术语 强度膨胀
    (r"\bpower creep\b", "权力蠕变", "强度膨胀"),
    (r"\bpower creep\b", "动画力量", "动画强度膨胀"),
    (r"\bsick\b", "太恶心了", "太帅了"),           # sick 俚语=帅，非"恶心"
    # farming 在抽卡语境=刷本/肝，非「种田」。2026-11-01 加 crop 守卫：
    #   《How Did You Join Arknights or Endfield?》#788 英文 "to crop farming are a massive
    #   quality improvement" —— 终末地 1.6 的真实种地玩法，此处「种田」才正确，不能被吃掉。
    (r"(?<!crop )\bfarming\b", "种田", "刷本"),
    (r"(?<!crop )\bfarming\b", "务农", "刷本"),
    (r"\bpulse\b", "脉搏", "抽卡"),               # pulse=pulls 抽卡误听
    (r"\btent\b", "帐篷", "十连"),               # tent=ten(-pull) 十连误听
    # 2026-09-08 负例沉淀（Thanks La 声优讨论片）：#351 “日本人偷了你写的帐篷”
    # 参考行 Japanese stole your written tent——语境为“日本人借用/偷用中文书面文字”（tent 疑为 text 的
    # ASR 误听），与抽卡无关，勿改“十连”。抽卡话题片源才套用本条。
    (r"\b10p\b", "10点", "十连"),                # 10p=10-pull 十连
    (r"\bfried\b", "油炸", "焦头烂额"),           # fried 俚语同 cooked=焦头烂额，非"油炸"
    (r"\bmusts?\b|musles", "肌肉", "必抽"),        # musles=musts 必抽
    (r"[Tt]s?undere", "Tundere/h", "傲娇"),       # tsundere 傲娇
    (r"\boutro\b", "其他动画", "收招动画"),        # outro animation 收招动画
    (r"\bdetract\b", "减弱", "收缩"),             # detract=retract 收缩
    (r"\bto nothing\b", "无所事事", "消散"),       # to nothing 消散，非成语"无所事事"
    (r"\bto nothing\b", "什么都没有", "消散"),
    (r"\ball falls\b", "瀑布", "坠落"),           # all falls 坠落，非"瀑布"
    (r"\bsentinel health\b", "哨点", "岁主"),      # sentinel health inspector 岁主卫生督察
    (r"\bis let down\b|hair is let down", "很失望", "披散下来"),  # hair is let down 头发披散，非"失望"
    (r"\bReturn to\b", "返回房间", "重归废墟"),    # "Return to room/walls" 均为 Return to ruin(重归废墟) ASR 变体
    (r"\bReturn to\b", "返回所有墙壁", "重归废墟"),
    # --- 2026-09-05 This_is_the_most 片源三次校准：需英文佐证的语境替换 ---
    (r"[Ss]igil", "印记", "辛吉勒姆"),             # 印记 与"封印/seal"歧义，仅 Sigilum 语境改（官方中文 辛吉勒姆）
    (r"[Ss]triders?\b", "步行者", "隧者"),          # exor striders 被译"步行者"（官方中文 隧者）
    (r"Exoriders?\b", "驱除者", "隧者"),            # Exorider 被译"驱除者"
    (r"synchronist", "同步器", "适格者"),           # 人被译成器件；Synchronist 官方中文=适格者（隧者驾驶员，2026-09-10 修正）
    (r"synchronist", "同步员", "适格者"),           # #10944 学院明星（爱弥斯是隧者适格者；"同步员"无条件键先转中间态，此处收敛）
    (r"synchronist", "同步者", "适格者"),           # 官方中文 适格者（同参考行佐证收敛）
    (r"chosen synchronist", "被选中的同步者", "适格者"),  # #20993 chosen synchronist=适格者（整词先行）
    (r"resonators?\b", "谐振器", "共鸣者"),         # Resonator 官方译名 共鸣者
    (r"resonators?\b", "谐振腔", "共鸣者"),         # 同上（"谐振腔"变体，2026-10-04 英文原声 3.7 反应片）
    # --- 2026-09-28 ASR 断词片源（reacting to resonator showcases）：硬译残留 ---
    # "reson ator showcase" 经 EN_ASR_SPLIT_FIXES 规整后锚定；"展示柜"是正常词，须英文佐证
    (r"\bresonators? showcases?\b", "展示柜", "展示"),   # resonator showcase=共鸣者展示
    (r"reverberation", "混响", "残响"),             # reverberation 语境=残响（官方词；依 NGA/剧情“机傀附着的残响”，2026-09-08 修正）
    (r"\blament\b", "哀叹", "悲鸣"),                # the Lament 官方译名 悲鸣
    (r"\blament\b", "叹息", "悲鸣"),
    (r"asterit|astrite", "星星", "星尘"),           # Astrite 货币误译"星星"
    (r"\bethic\b", "道德怪物", "以太怪物"),         # ethic=aetheric 误听
    (r"\bethic\b", "道德水滴", "以太水滴"),
    (r"\bNora\b|N'avora", "诺拉", "恩沃拉"),        # Nora=N'avorora 简称
    (r"exos swarm", "外星群体", "隧群"),           # 隧者零件分化的机器动物群（官方《寰宇人类注疏》称"隧群"）
    (r"\bexosworm\b", "外蠕虫", "虚诞虫"),          # Voidworm ASR 变体（#1554；官方声骸 虚诞虫，2026-09-10 依游民星空/英文任务名，存疑标注）
    (r"[Cc]rownless", "无冕之王", "无冠者"),        # Crownless 官方译名 无冠者
    (r"talisman", "符咒", "护身符"),                # talisman 统一为 护身符
    # --- 2026-09-05 补漏：meth=Imeth 变体 / 驱逐者 / 救主 / Astrite 官方名 ---
    (r"little eye meth", "小眼睛的方法", "小爱弥斯"),   # little Imeth（须先于裸 meth 规则）
    (r"\bLil Meth\b", "莉尔·梅斯", "小爱弥斯"),        # Lil Meth = 小爱弥斯
    (r"cosplay meth", "冰毒", "爱弥斯"),               # cosplay meth = cosplay 爱弥斯（"冰毒"为误译）
    (r"\bmeth\b", "方法", "爱弥斯"),                   # meth=Imeth 残留（"You look toward meth"被译"方法"）
    (r"Exoriders?\b", "驱逐者", "隧者"),               # Exoriders 被译"驱逐者"（#831 驱逐者的脚）
    (r"\bSavior\b", "救主", "救世主"),                  # savior 统一 救世主
    (r"asterit|astrite", "星尘", "星声"),              # Astrite 官方中文 星声（修正前条"星尘"）
    (r"asterit|astrite", "天星石", "星声"),            # Astrite 谷翻异形"天星石"（2026-10-12 演唱会反应片 #2559/2561 实测；
                                                       #   长键先于"星石"形锚定，否则咬出畸形"天星声"）
    (r"\bfigure\b", "Changi", "长离"),                 # #1868 "new Changi figure"=长离（Changli）手办；Changi 樟宜为新加坡地名，
                                                       #   仅 figure（手办）语境锚定，防误伤旅行话题（2026-10-12 二次校准）
    # --- 2026-09-08 Thanks La 声优讨论片 二次校准：ASR 变体误译（参考行佐证）---
    # #236 "the Ian" = EN(英文版) 的 ASR 误听（语境对比 English VA vs Chinese version 评分）
    (r"\bthe Ian\b", "伊恩", "英文"),
    # #277 "the man drinking" = Mandarin(普通话) 的 ASR 误听（语境：Chinese more used than Cantonese）
    (r"\bman drinking\b", "那个喝酒的人", "普通话"),
    # #335 "menrine" = Mandarin(普通话) 的 ASR 变体（中文行英文残留 -> 官方词）
    (r"\bmenrine\b", "menrine", "普通话"),
    # --- 2026-09-08 NIKKE Player Reacts to WW's BEST Story Cinematics（鸣潮三短片 Reaction）新增 ---
    (r"\bJinzhou\b", "锦州", "今州"),               # Jinzhou 官方译名 今州
    (r"\bJinzhou\b", "晋州", "今州"),
    (r"\bJinzhou\b", "金州", "今州"),               # 裸"金州"（"金州爵"已整词处理，防误伤大连金州）
    (r"\bJinshi\b", "金石", "今汐"),                # Jinshi = Jinhsi 今汐（须英文佐证防误伤"金石"）
    (r"\bWuthering\b", "呼啸山庄", "鸣潮"),          # Wuthering Waves 被误作《呼啸山庄》
    (r"\bscales?\b", "秤", "鳞片"),                  # scales（龙鳞）被误译"秤"
    # --- 2026-10-11 鸣潮音乐会反应片（This actually BROKE me）：学习库裸键治理 ---
    # ⚠ 2026-10-13 废除 (r"\bactually\b", "真的", "其实")：WuWa Exploration Quests 片
    # 实测 9+ 处误改——谷翻把 really/true 也译"真的"，锚定词形过宽（"这是真的"true
    # 被改成"这是其实"病句）。"真的→其实"是风格偏好非专名校准，永久否决，勿再收编。
    # (r"\bactually\b", "真的", "其实"),
    # --- 2026-10-11 同片二次校准（逐句核查 1415 cue；官方名依 references/鸣潮对照表、灰机/萌娘/fandom wiki）---
    (r"\bChisa\b", "千纱", "千咲"),                     # Chisa=千咲（表内已有英文键，谷翻中文形"千纱"漏校，cue75/77）
    (r"\bFroova\b", "弗鲁娃", "弗洛洛"),               # Phrolova ASR 变体（cue310，"杀NPC/撒谎"反派语境）
    (r"\bThrodian\b|\bThrenodian\b", "索德人", "鸣式"), # Threnodian 官方中文=鸣式（cue499，2.7 主线最终战）
    (r"\bThrodian\b|\bThrenodian\b", "索罗迪亚人", "鸣式"),  # 同上谷翻另一音译形（索罗迪亚=Throdian 谷翻；2026-10-25 TRANSCENDO 反应片 cue109）
    (r"\bCarla\b", "卡拉", "珂莱塔"),                   # Carlotta ASR 截断（cue168，2.0 trailer/娃娃语境）
    (r"\bcara\b", "卡拉", "卡提希娅"),                  # Cartethyia 截断（cue389，"2.0/2.x 的耶稣"=圣女救世主梗）
    (r"\bUno\b", "Uno", "尤诺"),                        # Iuno ASR 变体（cue443，与奥古斯塔日/月对比语境）
    (r"\bUnun\b", "Unun", "尤诺"),                      # 同上变体（cue444）
    (r"\bShakona\b", "Shakona", "夏空"),                # Ciaccona=夏空·托卡塔；韩国主播读"샤콘"致 ASR Shakona（cue193，EP/暮光歌词）
    (r"\bAusta\b", "澳大利亚", "奥古斯塔"),             # Augusta ASR 截断被谷翻当国名（cue700，歌手讨论）
    # 2026-11-09 二次校准补：完整拼写 Augusta 英文残留（本片 cue91/104/387，谷翻未译直接保留）。
    # 走参考行佐证（英文行含 Augusta），wrong=英文噪音"Augusta"，不建裸键，沿用奥古斯塔既有口径。
    (r"\bAugusta\b", "Augusta", "奥古斯塔"),
    (r"\bSahroy\b", "萨罗伊", "拉海洛"),                # Lahai-Roi ASR 变体（cue740 介绍）
    (r"\bLa ?Hyroi\b", "拉·希罗伊", "拉海洛"),          # 同上带点形（cue751）
    (r"\bginshi\b", "银人", "今汐"),                    # Jinhsi ASR 变体（cue1135，观众席今汐应援气球）
    (r"I miss'?s\b", "我很想念", "爱弥斯"),             # Immeth ASR 变体被谷翻当短语（cue935）
    (r"\bGata\b", "Gata", "抽卡"),                      # gacha ASR 变体谷翻未译（cue1300）
    (r"\benchor\b", "魔咒", "安可"),                    # encore ASR 变体（cue1357，返场语境）
    (r"\bKur\b", "库尔", "库洛"),                       # Kuro robots ASR 截断（cue1338，"库洛机器人集结"）
    (r"\bIris\b", "艾瑞斯", "I.R.I.S."),                # 星炬学院 AI NPC 官方名不意译（cue1124，灰机/萌娘/fandom 均用 I.R.I.S.）
    (r"\bIMTH\b|\bim{2,}ith\b", "IMTH", "爱弥斯"),      # Immeth ASR 变体英文残留（cue658）
    (r"\bIMTH\b|\bim{2,}ith\b", "Immmith", "爱弥斯"),   # 同上三重m形（cue1318）
    (r"\bImmeth\b", "伊米斯", "爱弥斯"),                # 谷翻音译与表内"爱弥斯"不一致（cue659）
    (r"\bITH\b", "ITH", "爱弥斯"),                      # Immeth 截断英文残留（cue734）
    (r"right has concluded|rite has concluded", "权利已结束", "仪式已结束"),  # right=rite 误听
    (r"\bmagistrate\b", "地方法官", "令尹"),           # 长词先行，防"地方法官"被"法官"规则拆开
    (r"\bmagistrate\b", "法官", "令尹"),               # magistrate 官方译名 令尹（今州管理者）
    (r"\bmagistrate\b", "知县", "令尹"),
    (r"\bA ?Math\b|\bAmath\b", "一道数学题", "爱弥斯"),   # A Math = Aemeath（须先于裸"数学"规则）
    (r"\bA ?Math\b|\bAmath\b", "数学", "爱弥斯"),
    (r"for this short", "现在就这么短", "就这个短片来说"),
    (r"\bshort\b", "简而言之", "这个短片里"),           # short=短片 被误译成语"简而言之"
    (r"\bframe\b", "框架", "画面"),                    # frame=画面/镜头
    (r"\btrailer\b", "拖车", "宣传片"),                # Resonator trailer 共鸣者宣传片
    (r"\bNier\b", "提醒我的尼尔", "让我想起尼尔"),     # reminds me of Nier
    (r"set off", "没想到会出发", "没想到会引爆"),       # set off a volcano 引爆火山
    (r"dial back", "拨回设置", "调低设置"),             # Dial back settings 调低设置
    (r"\bbusted\b", "被抓了", "失灵了"),                # It's like busted 机甲失灵（非"被抓"）
    (r"if you want to synchronize", "我是如果你想同步", "我是说如果你想同步"),
    (r"in the beginning of this", "在本文开头", "在这个短片开头"),
    (r"or like the speed", "或喜欢速度", "或者说速度"),
    # --- 2026-09-08 二次校准（检索官方中文后补充）---
    (r"\bSalvation\b", "救赎", "拯救"),            # 爱弥斯动画短片官方标题《拯救》
    (r"the Moras of", "莫拉斯的泥潭", "战争的泥沼"),  # morass of war 误听，岁主角将今州从战争泥沼中救出
    # --- 2026-09-10 WW 3.1 Story Reaction (Stream #2) 二次校准新增（参考行佐证）---
    (r"\bIth\b", "伊斯", "爱弥斯"),                # Ith = Aemeath 简称，机翻"伊斯"（#1581；"伊思"已由 BILINGUAL_TERMS 覆盖）
    (r"\bBodian\b", "博典", "鸣式"),               # Bodian = Threnodian ASR 变体（#2826 Rover's personal Bodian）
    (r"\bseal\b", "海豹", "封印"),                 # seal 动词"封印"被译"海豹"（#4129 rider seal the Threnodian；雪绒海豹由 EXCLUDE 回滚）
    (r"\bVoid\b", "空白", "虚空"),                 # Void 官方术语"虚空"（#3085 拉海洛上空的虚空，存疑已向用户报告）
    (r"\bRaguna\b", "拉古纳", "拉古那"),           # Raguna = Ragunna 官方中文 拉古那（#408）
    (r"chasing after", "一扑扑救", "去救"),        # #1688 "to to to save" 口吃噪音被机翻"一扑扑救"（Alf one=Alfan 连读误拆）
    (r"save La\b", "拯救La", "拯救拉海洛"),        # #4281 Lahai-Roi 跨行截断（下条 Hyroy 续行，见 4282）
    # --- 2026-09-10 二次校准（依官方中文检索修正）新增 ---
    (r"\bVoid\b", "空白", "虚质"),                 # Void=虚质（深空联合对黑洞的称呼；#3085/#4808；官方名词表已有"虚质空间"）
    (r"\bVoid\b", "虚空", "虚质"),                 # #1734 数字幽灵后的孤立 Void（拉海洛语境，勿与黎那汐塔虚空混淆）
    (r"void matter", "虚空物质", "虚质物质"),      # #3004 void matter=虚质物质
    (r"void space", "虚空", "虚质空间"),           # #3014 掉进 void space=虚质空间（隧门之后）
    (r"high void\b", "空隙率", "虚质浓度"),        # #1613 深处 high void=高虚质浓度
    (r"\bRoya\b", "罗亚", "罗伊"),                 # #6949 Roya outfit=罗伊族装束（Roya Civilization=罗伊文明）
    (r"[Ss]igil", "印章", "辛吉勒姆"),             # #2798 "No, it's Sigilium"被机翻"印章"
    (r"[Ss]igilum\b", "海豹", "辛吉勒姆"),         # #14113 sigilum 被机翻"海豹"（非 seal 动词，勿与 \bseal\b 规则混淆）
    (r"\bSnowfluff seals?\b", "雪绒密封", "雪绒海豹"),  # #4149 Snowfluff Seal=雪绒海豹（爱弥斯配件，官方确认）
    (r"\bSnowfluff seals?\b", "雪毛海豹", "雪绒海豹"),  # #3261 snowfluff seals（复数）被机翻"雪毛海豹"
    # --- 2026-09-08 NO ONE CAN CONTROL THEMSELVES!（WuWa 3.6 Streamers REACTIONS）校准新增 ---
    (r"\bMongjo\b", "蒙乔", "梦州"),              # #1277
    # 今州(Jinzhou/Jingjo) 变体
    (r"\bJingjo\b", "京城", "今州"),              # #1276 今州巡卫（防误伤“京城”普通词义）
    # 瑝珑(Huanglong) 变体（恒隆/环龙/斯旺龙）
    (r"\bHang Long\b", "恒隆", "瑝珑"),           # #184
    (r"\bHuan Long\b", "环龙", "瑝珑"),           # #405
    (r"\bSwang Long\b", "斯旺龙", "瑝珑"),        # #1151
    # 玄方城(Schwanfong Hold) ASR 变体（施万夫/双芳抱/什拉农/沙风/天鹅芳）
    (r"\bSchwanf\b", "施万夫", "玄方城"),          # #1275
    (r"\bShuanfang\b", "双芳抱", "玄方城"),        # #137
    (r"\bShranong\b", "什拉农要塞", "玄方城"),     # #105
    (r"\bSha Fong\b", "沙风要塞", "玄方城"),       # #663
    (r"\bSchwanfang\b", "天鹅芳", "玄方城"),       # #1209
    (r"\bSchwan ?Lling\b", "施万林鸟", "玄翎雀"),  # #760 清宵身边的灵鸟（2026-11-10 官方名 玄翎雀）
    # 玄元境(Schwan Yuan domain，3.6 新区域，官方名 玄元境)
    (r"\bSchwan Yuan\b", "天鹅园域", "玄元境"),    # #1078
    (r"\bSchwanuan\b", "施瓦努安", "玄元境"),      # #1096
    # 清宵(Ching Xiao/Ching Sha) ASR 变体（钦戈/清孝/奇姆查河/Ching残留/Chang/Ting* 昵称群）
    (r"\bChingo\b", "钦戈", "清宵"),              # #411
    (r"\bChing Shiao\b", "清孝", "清宵"),          # #711
    (r"\bChimcha\b", "奇姆查河", "清宵"),          # #889 超越清宵
    (r"\bChing[,.]", "清,", "清宵,"),            # #459 清→清宵（防误伤普通“清”；句末无 \b 匹配）
    (r"\bChang's\b", "张", "清宵"),                # #211 清宵正要单挑（Chang=Ching 误听）
    (r"\bTing Xiao\b", "霆骁", "清宵"),            # #99 为清宵而来的姐姐能量
    (r"\bTing Shao\b", "丁绍", "清宵"),            # #136 Paragon 丁绍=清宵（主播昵称群）
    (r"\bTing Sao\b", "婷嫂", "清宵"),             # #1129
    # 2026-10-05 3.7 reaction 片补录：Ching Sha/Ching Shia/独立 Ching 的谷翻错形
    (r"\bChing\w*", "清莎", "清宵"),
    (r"\bChing\w*", "青石", "清宵"),               # #6593 Ching Shia（"青石"为常用词，须 Ching 佐证）
    # ⚠ 2026-10-22 反例：Tenha EP reaction 片 #1077 主播模仿中文韵脚 "ching, right?"，
    #   中文行"是青，对吧？"被本条改成"是清宵"。角色简称必为大写，故改用大小写敏感正则；
    #   原 #1015 "Suming and Ching"（大写）仍命中。
    (r"(?-i:\bChing\b)", "青", "清宵"),             # #1015 Suming and Ching 独立简称
    (r"\bChing\b", "程", "清宵"),                  # #6503 呼语 Ching,（程为常用字，须独立 Ching 佐证）
    # 景燃(Jingran) 2026-10-05 补录
    (r"\bChingan\b|\bJingran\b", "钦安", "景燃"),   # #6776 Chingan（与下句 Jingron 同指一人）
    (r"\bJingron\b|\bJingran\b", "景蓉", "景燃"),   # #6779 Jingron 谷翻错形
    # 景燃(Jingran，寻幽客=幽客，幕间「幽客销残声」主角；Nethermancer) ASR 变体
    (r"\bJing Rang\b", "靖让", "景燃"),            # #332 景燃的狮子（白泽）
    (r"\bJingron\b", "靖荣", "景燃"),              # #336/#990
    (r"\bJingron\b", "靖隆", "景燃"),              # #649
    (r"\bJron\b", "杰伦", "景燃"),                 # #861 Jron=Jingron
    (r"\bnethermancer\b", "虚空巫师", "幽客"),      # #524
    (r"\bnethermaner\b|\bnethermancer\b", "虚空者", "幽客"),   # #858
    # 心月狐(Sheen/Shin/Shane，月狐岁主) ASR 变体
    (r"\bShane\b", "肖恩", "心月狐"),              # #1031
    (r"(?<![Ss]hu )\bShin\b", "辛", "心月狐"),     # #85 心月狐发来消息（负向后行排溯心 Shu Shin）
    (r"(?<![Ss]hu )\bShin\b", "胫", "心月狐"),     # #86
    # 炽霞(Chixia) 变体
    (r"\bChisha\b", "赤煞", "炽霞"),               # #406 炽霞与秧秧
    # --- 2026-09-15 鸣潮 TCG 开包片（DOZEN RARES / 54 Booster Packs，英语原声+谷翻）新增 ---
    # 该片 ASR 变体极多，两条硬经验：
    #   ① Chisha=炽霞(Chixia) 与 Chisa=千咲 仅一字之差，而 BILINGUAL_TERMS 有裸键"奇莎->千咲"，
    #      在英文行是 Chisha 时会误判成千咲 => 下方用参考行锚定把已变成"千咲"的结果回滚为炽霞。
    #   ② "奇莎/桑/空头/短手/基尼系数/三和/岸边妈妈"等属通用中文词，严禁裸键，一律走本表锚定。
    (r"\bChisha\b", "千咲", "炽霞"),
    (r"\bChishia\b|\bShishia\b", "奇希亚", "炽霞"),
    # ── 2026-11-07 补：本片 cue437「什希亚,」/ EN "Shishia," —— 谷翻音译形，
    #   官方中文=炽霞（库洛官网 mc.kurogames.com/main/news/detail/160「炽霞 CHIXIA」；
    #   库街区 wiki item/1240039812638883840）。上方 Chishia 锚的 wrong 侧是「奇希亚」，
    #   本片是「什希亚」故不命中 ⇒ 补一条同锚条目。
    #   「什希亚」为生僻音译形、非通用词，但仍走参考行锚定（硬契约第 4 条），不进裸键表。
    (r"\bShishia\b", "什希亚", "炽霞"),
    (r"\bchameleas?\b|\bchameleons?\b", "变色龙", "椿"),
    (r"\bKamea\b", "卡美亚", "椿"),
    (r"\bChamilleia\b", "夏米勒", "椿"),
    (r"\bChamele\b", "夏梅尔", "椿"),
    (r"\bChinshi\b|\bChinchi\b|\bGinshi\b|\bGinchi\b|\bGinhi\b|\bGishi\b|\bShinshi\b", "钦希", "今汐"),
    (r"\bChinshi\b|\bChinchi\b|\bGinshi\b|\bGinchi\b|\bGinhi\b|\bGishi\b|\bShinshi\b", "钦奇", "今汐"),
    (r"\bGinchi\b|\bGinhi\b|\bGishi\b", "金奇", "今汐"),
    (r"\bGinhi\b|\bGinshi\b", "金希", "今汐"),
    (r"\bShinshi\b|\bGinshi\b", "新石", "今汐"),
    (r"\bRover\b", "流浪者", "漂泊者"),
    (r"\bRober\b", "罗伯", "漂泊者"),                   # Rover ASR 加 r 变体（Re:Zero 死亡回归梗"罗伯回来了吗"；2026-10-25 TRANSCENDO 反应片 cue221）
    (r"\bgini\b", "基尼系数", "今汐"),
    (r"\bsan(?:oa|ho|wa|ua|hoa|has|anga|ang)\b", "萨诺亚", "散华"),
    (r"\bsan(?:oa|ho|wa|ua|hoa|has|anga|ang)\b", "三和", "散华"),
    (r"\bsan(?:oa|ho|wa|ua|hoa|has|anga|ang)\b", "萨努阿", "散华"),
    (r"\bsan(?:oa|ho|wa|ua|hoa|has|anga|ang)\b", "萨南加", "散华"),
    (r"\bsan(?:oa|ho|wa|ua|hoa|has|anga|ang)\b", "萨南", "散华"),
    (r"\bsan(?:has|anga|ang)\b", "桑哈斯", "散华"),
    (r"\bSharkkeeper\b", "鲨鱼饲养员", "守岸人"),
    (r"\bSharkkeeper\b|\bShorekeeper\b", "鲨鱼守护者", "守岸人"),
    (r"\bShorekeeper\b", "岸管家", "守岸人"),
    (r"\bShorekeeper\b|\bShortkeeper\b", "空头", "守岸人"),
    (r"\bShortkeeper\b", "短手", "守岸人"),
    (r"\bShortkeeper\b", "矮子", "守岸"),
    (r"\bTruck\s+Keeper\b", "卡车管理员", "守岸人"),
    (r"\bWithering Waves\b", "枯萎", "鸣潮"),
    (r"\bWithering Waves\b", "枯萎的波浪", "鸣潮"),
    (r"\bWithering Waves\b", "凋零浪潮", "鸣潮"),
    # --- 2026-09-15 同片二次校准（检索官方中文后新增）---
    # 辉萤军势：Lampy Lumen/lumin 被谷翻直译成"灯火通明"（成语）—— 成语禁裸键，走锚定
    (r"\bLampy\s*lum(?:en|in)\b|\bLampylumen\b|\bLampulum\b", "灯火通明", "辉萤军势"),
    # 哀声鸷（Whining Aix，怨鸟泽怒涛级残象）：
    #   ASR 把 Whining Aix 听成 Morning Aix / morning eggs，谷翻再切成"早鸡蛋/我们喜欢早上"。
    #   链路属推断（Whining→Morning 的 M/W 混淆 + 尾音脱落），故只锚定 ASR 形态、不做裸键，
    #   且正则严格限定为 ASR 误形，避免误伤真实语境里的 morning / eggs。
    (r"\b(?:Whining|Morning|Mourning|Wining)\s+(?:Aix|eggs?|Iikes|ikes|Aikes)\b", "早鸡蛋", "哀声鸷"),
    (r"\b(?:Whining|Morning|Mourning|Wining)\s+(?:Aix|eggs?|Iikes|ikes|Aikes)\b", "我们喜欢早上", "哀声鸷"),
    (r"\b(?:Whining|Morning|Mourning|Wining)\s+(?:Aix|eggs?|Iikes|ikes|Aikes)\b", "早上喜欢", "哀声鸷"),
    (r"\b(?:Whining|Morning|Mourning|Wining)\s+(?:Aix|eggs?|Iikes|ikes|Aikes)\b", "Morning Aix", "哀声鸷"),
    # 椿(Camellya)：Camille/Chamille 误形（注："卡米尔/Camille"是西方常见人名，禁裸键）
    (r"\bCamille\b|\bChamille\b|\bCamelle\b", "卡米尔", "椿"),
    # 吟霖(Yinlin) 变体
    (r"\bYin Llin\b", "尹琳", "吟霖"),             # #1244 我的精灵女王
    # 木禺(Muyu) 变体（圆圈/圆形的/穆/穆约）
    (r"\bMuyu\b", "圆圈", "木禺"),                 # #364
    (r"\bMuyu\b", "圆形的", "木禺"),               # #1177
    (r"\bMuyo\b", "穆约", "木禺"),                 # #283
    (r"\bWhere is Mu\b", "穆", "木禺"),            # #882
    # 残象(Tacet) ASR 变体（泰泰特/tacid话语）
    (r"\btacet\b", "泰泰特", "残象"),              # #1045
    (r"\btacid\b", "冷漠的话语", "残象"),            # #278 These tacid discourses（2026-10-20 直归残象，勿留中间形态）
    # 咎庭(Censure Court) 变体（中心球场/中央法院/中央法庭）
    (r"(?:centric|centure|centra|censure)[\s-]?courts?", "中心球场", "咎庭"),   # #248
    (r"(?:centric|centure|centra|censure)[\s-]?courts?", "中央法院", "咎庭"),   # #263/#280
    (r"(?:centric|centure|centra|censure)[\s-]?courts?", "中央法庭", "咎庭"),   # #1044
    # 机傀(autopuppet) 官方词=机傀（琢钧堂/天工部所造、附身死者残响的傀儡；2026-09-08 二次校准由"刃偶"纠正为官方"机傀"）
    (r"autopuppets?\b|auto puppets?\b", "自动傀儡", "机傀"),   # #470/#535/#541/#544/#952/#953/#1043
    # 云梭(cloud shuttle) 机翻残留（航天飞机/班车；#1115 云云梭由侧车处理）
    (r"\bshuttles?\b", "航天飞机", "云梭"),         # #631
    (r"\bshuttles?\b", "班车", "云梭"),             # #487/#491
    # 残响(reverberations) 其它变体
    (r"reverberations?\b", "回响", "残响"),          # #523/#869 死者的残响
    (r"\blingering sessions\b", "挥之不去的会话", "挥之不去的残响"),   # #526
    # 常见机翻错词（参考行佐证）
    # ⚠ 2026-10-13 废除 (r"\bpsycho\b", "心理", "疯子")：WuWa Exploration Quests 片
    # #3563 "psychoanalyze"=心理分析，改"疯子分析"为病句；psychoanalyze 心理学义优先，永久否决。
    # (r"\bpsycho\b", "心理", "疯子"),               # #559
    (r"\bmastermind\b", "大师", "主谋"),           # #594
    (r"\bmaintain the lane\b", "车道", "链接"),     # #671 维持链接
    (r"\bsowed\b|\bswed\b", "瑞典", "播下的"),      # #1069 木禺播下的混乱
    (r"\bmain frames?\b", "主要框架", "主框架"),    # #1082
    (r"\bcivilization capsule\b", "文明舱", "文明之匣"),   # #957 官方中文=文明之匣（灰机wiki/3.7 剧情帖；旧目标"文明胶囊"作废）
    (r"\brover\b", "漫游者", "漂泊者"),            # #582/#693
    (r"^(?!.*\bYang\s*yang\b).*\bYang\b", "杨", "秧秧"),  # #12/#609 秧秧；参考行含 Yang Yang 时不触发，交给下方整词"杨洋/杨阳"规则，避免只咬首字残留"洋"
    # --- 2026-09-08 【字幕】I cannot believe this is a gacha game - WW 2.7 Story Quest Highlight 校准新增 ---
    # 利维亚坦（Leviathan=2.7 鸣式 BOSS 官方译名；防误解作神话"利维坦"）
    (r"\bLeviathan\b", "利维坦", "利维亚坦"),
    # 坎特蕾拉（Cantarella=坎特蕾拉·翡萨烈）各 ASR/主播口误变体
    (r"\bCanell?a\b|\bCaner?a\b", "卡内拉", "坎特蕾拉"),   # #513/#574/#1006
    (r"\bCanerella\b", "卡内雷拉", "坎特蕾拉"),     # #317
    (r"\bCanellilla\b", "卡内利拉", "坎特蕾拉"),    # #574
    (r"\bContella\b", "康特拉", "坎特蕾拉"),        # #657/#660
    (r"\bCartilla\b", "卡提拉", "卡提希娅"),        # #768；Cartilla≈Cartethyia（卡提希娅），非 Cantarella（2026-10-30 修正）
    (r"\bCarti\b", "卡蒂", "坎特蕾拉"),             # #774/#801/#818
    (r"\bCterella\b", "克特雷拉", "坎特蕾拉"),      # #309
    # 莫塔里家族（Montelli=珂莱塔·莫塔里的家族，官方译名 莫塔里）
    (r"\bMontellis?\b", "蒙特利斯", "莫塔里"),      # #353
    # 今州（Jingjo/Jing Joe 音频变体）
    (r"\bJingjo\b", "靖州", "今州"),                # #410
    (r"\bJing ?Joe\b", "荆乔", "今州"),             # #536
    # 安吉尔（Angel=官方角色名；参考行为 Angel 时才改，防神话"天使"误伤）
    #   ⚠ 2026-10-22 反例：Tenha EP reaction 片歌词 "angel consumes"（#945）、
    #   独立成行的 ">> Angel"（#1854）就是天使，被本条误改成"安吉尔"。
    #   歌词语境由 EXCLUDE_CONTEXT 的“天使”负例回滚（见 EXCLUDE_CONTEXT 2026-10-22 段）。
    (r"\bAngel\b", "天使", "安吉尔"),               # #719/#954
    # --- 2026-10-22 Tenha 鸣潮全 EP reaction 片（2015 cue）：普通词被谷翻直译的角色名 ---
    #   全部为常用词，必须参考行锚定；本片实测各 1 处。
    (r"\bGian\b", "吉安", "忌炎"),                  # #51 Gian as their first banner（1.0 首池）
    (r"\bpulling for brand\b", "品牌", "布兰特"),   # #346 not pulling for brand
    (r"\bBrand's personality\b", "布兰德", "布兰特"),
    # 2026-11-08 Jadealy 3.8：Brand 是 Brant 的常见 ASR 形（#407/#434）。
    #   (?!\s+person) 排除「brand person」主播梗（#665/#666 中文「品牌人」）；通用词不建裸键。
    (r"\bBrand\b(?!\s+person)", "布兰德", "布兰特"),
    (r"\bGalena\b", "方铅矿", "嘉贝莉娜"),          # #1017 Galena one（矿物名被直译）
    (r"\bGalina\b", "加琳娜", "嘉贝莉娜"),          # #936 this one's for Galina
    (r"\bBourne\b", "伯恩", "莫宁"),                # #1237 And Bourne（Mornye ASR 变体）
    (r"\bCarthais\b", "迦太", "卡提希娅"),          # #591 Carthais（被当成迦太基截断）
    # 克里斯托弗（Christopho*/Christophoro 变体）
    (r"Christopho", "克里斯托弗罗", "克里斯托弗"),
    # 今汐（Ginshi≈Jinhsi 今汐，主播口音；存疑待人工复核）
    (r"\bGinshi\b", "Ginshi", "今汐"),
    # 原神（Genshin/Genin/Genjin 变体）
    (r"\bGenjin\b|\bGenin\b", "原真", "原神"),
    # 鸣潮（WuWa 主播昵称 Wua）
    (r"\bWua\b", "Wua", "鸣潮"),
    (r"\bWua\b", "瓦阿", "鸣潮"),               # #995 Wua 被音译为"瓦阿"
    # --- 2026-09-08 WW 2.7 二次校准（检索官方中文后补充）---
    (r"\bwaifu", "外婆", "老婆"),              # waifu 被误译"外婆"(主播口语，真义 wife/老婆)
    (r"\bFrover\b", "弗漂泊者", "弗罗弗"),      # 救回 BILINGUAL"罗弗"->漂泊者 对"弗罗弗"(主播昵称)的子串误伤
    (r"\bAbby\b", "艾比", "阿布"),             # Abby 官方名"阿布"(真名阿布拉克萨斯)
    (r"\bAby\b", "艾比", "阿布"),              # Aby = Abby 的 ASR 变体
    (r"\bAbbyus\b|\bAbrais\b", "阿布雷斯", "阿布拉克萨斯"),  # 阿布全名 Abraxas 的主播变体
    (r"\bSeptimont\b", "塞普蒂蒙", "七丘"),      # Septimont 官方"七丘"
    (r"\bLupa\b", "卢帕", "露帕"),              # Lupa 官方"露帕"
    (r"\bLup\b", "卢普", "露帕"),               # Lup ASR 变体
    # --- 2026-09-09 明日方舟 OST 分析片（Analyzing "Ratio Ultima" Arknights OST, Basterd's LFA）新增 ---
    # 证据：arknights.wiki.gg/wiki/Episode_14/OST —— RATIO ULTIMA（14 章「Absolved Will Be the Seekers」OST，
    #       作曲 Yuka Kitamura 北村友香，厂牌 Monster Siren Records 官方中文名 塞壬唱片）
    (r"Monster Siren", "怪物海妖唱片", "塞壬唱片"),   # Monster Siren Records 官方中文 塞壬唱片
    (r"\bArk Knights\b", "方舟骑士团", "明日方舟"),   # Arknights 官方中文 明日方舟（ASR 误拆 Ark Knights）
    (r"\bArk Knights\b", "方舟骑士", "明日方舟"),
    (r"\bArknights\b", "方舟骑士团", "明日方舟"),     # 双保险：EN 行拼写正确时中文行仍是机翻拆名
    (r"\bArknights\b", "方舟骑士", "明日方舟"),
    (r"\bArc Knights\b", "弧骑士", "明日方舟"),       # #495 Arc Knights(=Arknights 误读成 Arc) 弧骑士→明日方舟；须置于通用 Knights 规则之前，否则会被咬成《弧明日方舟》畸形
    # 2026-10-22 反例：Batman: Arkham Knights 的「骑士」被本条改成「明日方舟」
    #   （Gacha Games Have A Villain Problem #61），负向后顾排除 Arkham 前缀。
    (r"(?<!Arkham )\bKnights\b", "骑士", "明日方舟"),  # 名字跨 cue 被拆成 方舟/骑士 时后半补全（#886）
    (r"\bDragon Guard\b", "龙卫", "龙背上的骑兵"),       # #223/#252 Dragon Guard=ASR 误听 Drakengard(龙背上的骑兵)；龙卫→龙背上的骑兵（须英文佐证，防误伤普通词）
    (r"\bDragon Guard\b", "龙之守卫", "龙背上的骑兵"),   # #238/#252 同上，龙之守卫→龙背上的骑兵
    (r"\bStellar Blade\b", "星刃", "剑星"),             # #279/#284/#308 Stellar Blade 官方中文 剑星（星刃为早期海报译名，非现用官方名）
    (r"\bKamura\b|\bKitamura\b", "由加村", "北村"),   # Yuka Kitamura 官方中文 北村（友香）
    (r"\bKamura\b|\bKitamura\b", "卡村", "北村"),     # Kamura 为 Kitamura 的 ASR 误听（片内 #258/#709/#736 作 Kitamura）
    (r"\bRatio Ultima\b", "比率终极", "Ratio Ultima"),     # 曲名保留英文（wiki 曲名 RATIO ULTIMA，无官方中文）
    (r"\bRatio Ultima\b", "比率创世纪", "Ratio Ultima"),   # #1030 机器把 Ultima 误作"创世纪"
    (r"\bRatio Ultima\b", "比率 Ultima", "Ratio Ultima"),
    # --- 2026-09-09 Ratio Ultima 二次校准：音乐术语通行官方中译（参考行佐证，防误伤普通词义）---
    # 依据：通行乐理中译 motif=动机 / counterpoint=对位 / tubular bells=管钟 /
    #       instrumentation=乐器法 / orchestration=配器法 / conductor=指挥 / harmony=和声 /
    #       alto=女低音；Looney Tunes 华纳官方中文《乐一通》
    (r"\bmotifs?\b", "图案", "动机"),                  # motif 全片"主题/图案"混用，统一为 动机
    (r"\bmotifs?\b", "主题", "动机"),
    # 2026-11-09 pattern≠motif：英文 pattern 被谷翻误当 motif 译成"动机"，官中应为"图案"。
    # 不做泛化 pattern 裸锚（pattern 多义：图案/模式/花样），用具体短语锚定最安全。
    (r"\bMetallic pattern ribbon\b", "金属动机丝带", "金属图案丝带"),
    (r"\bcounterpoint\b", "反驳", "对位"),             # counterpoint 误译"反驳"
    (r"tubular", "管状钟", "管钟"),                    # 长词先行
    (r"tubular", "管状", "管钟"),                      # 名字被拆到下一 cue 时
    (r"Looney", "《鲁尼", "《乐一通"),                 # Looney Tunes 官方中文《乐一通》（名字跨 cue，前半）
    (r'Tunes', "曲调”", "》"),                        # 后半：删去误译"曲调"（#376 实际用全角引号）
    (r"\bconduct(?:s|ed)?\b", "进行", "指挥"),         # conduct 误译"进行"
    (r"\bconduct(?:s|ed)?\b", "行为", "指挥"),         # conduct 误译"行为"
    (r"\bconducted\b", "进行过", "指挥过"),
    (r"\bconducting\b", "传导", "指挥"),               # conducting 误译"传导"
    (r"\bconductor\b", "导体", "指挥家"),              # conductor 误译"导体"
    (r"instrumentation", "仪器仪表", "乐器法"),        # instrumentation 误译"仪器仪表"
    (r"orchestration", "编排", "配器法"),              # orchestration 误译"编排"
    (r"\binstruments?\b", "仪器", "乐器"),             # instrument 误译"仪器"
    (r"\bharmony\b", "和谐", "和声"),                  # harmony 音乐语境=和声
    (r"\barrowheads\b", "箭头，由", "箭镞，由"),       # arrowhead=箭镞（锻打语境）
    (r"\bAltos?\b", "中音", "女低音"),                 # alto 声部标准译名 女低音
    (r"\bstreams?\b", "溪流", "直播"),                 # stream 误译"溪流"
    (r"\bstreams?\b", "在流上", "在直播时"),
    (r"stream schedule", "流时间表", "直播时间表"),
    (r"stream schedule", "流式传输您的时间表", "直播时间表"),
    (r"\bstreams\b", "流，然后", "直播，然后"),
    # --- 2026-09-09 I_Was_Wrong_Completely_About_Wuthering_Waves 校准新增 ---
    # 椿（Camellya）机翻变体"变色龙"，仅英文行佐证 Chameleia/Chamellia 时改（防普通词误伤）
    (r"\bChameleia\b|\bChamellia\b", "变色龙", "椿"),
    (r"[Ss]howcase", "展示会", "展示"),
    (r"[Ss]creen ?time", "屏幕时间", "镜头时间"),
    # --- 2026-10-04 修正：洛瑟菈（Lucilla）的「总统→校长」必须走本表原生三元组 ---
    #   原挂在 Entity("洛瑟菈").ctx 里写成 (r"\bPresident\b", "总统")，而 Entity.ctx
    #   的语义是「强制替换成 canonical（洛瑟菈）」——于是"露西拉是学院的总统"会被
    #   改成"洛瑟菈是学院的洛瑟菈"。目标词（校长）≠ canonical，必须用本表三元组。
    (r"\bPresident\b", "总统", "校长"),
    # --- 2026-10-05 第二部 3.7 reaction 片（I Wasn't Ready...）二次校准新增 ---
    (r"\bLady\b", "Lady", "心月狐女士"),          # Lady(Shin) 称呼，谷翻留英文（#1662/#3356）
    (r"\bseal\b", "seal", "封印"),                # 玄朱锁语境 seal=封印（#4107）
    (r"\bSector Bing\b", "Bing", "丙"),           # Sector Bing=丙区（天干分区，#1537）
    (r"\bEin said\b", "Ein", "艾因"),             # NPC 艾因（#1944）
    (r"\bbang boo\b|\bbamboo\b", "bang boo", "竹子"),        # bamboo 断词误写（#5757，容纳 EN 修正后形态）
    (r"\bsheen guide\b|\bSheen's guidance\b", "sheen指南", "心月狐指引"),  # Sheen's guide（#5757）
    (r"\b[Tt]ac[ei]t discords?\b", "默契的不和", "残象"),  # Tacet Discord 谷翻系列错形（#3503/#5508）
    (r"\b[Tt]ac[ei]t discords?\b", "默契的分歧", "残象"),  # #4698
    (r"\b[Tt]ac[ei]t discords?\b", "默契的纷争", "残象"),  # #5952
    # --- 2026-10-05 ABSOLUTE HSINEMA｜WuWa 3.7 主线 reaction（5423 cue）二次校准：英文锚定新增 ---
    # 瑝珑(Huanglong)：官中=瑝珑（别称皇龙），「黄龙」是同音误写词，必须英文锚定，禁入裸键表
    (r"\bHuang ?Long\b|\bHong ?Long\b|\bHuan ?Long\b", "黄龙", "瑝珑"),   # #85/#1007/#5084
    # 锁暝(Swimming/Swaming 系) 名称被 ASR 作 Suing，谷翻误译成"苏姐/起诉"
    (r"\bSuing\b", "苏姐", "锁暝姐"),            # #2920/#5005
    (r"\bSuing\b", "起诉", "锁暝"),              # #2851
    # Arbiter 被 ASR 作 Alberta/albat，谷翻误作加拿大省名"艾伯塔省"
    (r"\bAlberta\b|\balbat\b", "艾伯塔省", "御者"),   # #5231
    (r"\bAlberta\b|\balbat\b", "阿尔巴特", "御者"),   # #5235
    # 梦州(Mongjo) 被主播简写作 MJ，谷翻原样保留
    (r"\bmoving to MJ\b|\bto MJ\b|\bMJ\b", "MJ", "梦州"),   # #51
    # --- 2026-10-05 同片二次校准：**通用词/歧义词**错形一律英文锚定，绝不进裸键表（硬契约第 4 条）---
    # 万相神宫(Manifold Sanctum)：sanctum 被直译成"圣殿/圣地/圣所"
    (r"\bsanctums?\b", "圣殿", "万相神宫"),      # #241/#244/#456/#693/#757/#987/#1044/#1072/#2048/#4750
    (r"\bsanctums?\b", "圣地", "万相神宫"),      # #590
    (r"\bsanctums?\b", "圣所", "万相神宫"),      # Entity ctx 已覆盖，双保险
    # 文明之匣(civilization capsule)：capsule 被直译成"胶囊"
    (r"\bcapsules?\b", "文明胶囊", "文明之匣"),  # #1013/#2393/#2427（长键先行）
    (r"\bcapsules?\b", "胶囊", "文明之匣"),      # #867/#2038/#2079/#2086/#2141/#2464/#2490/#3760/#3819/#3983/#4048/#4071/#4091/#4105/#4232/#4538/#4685/#4693/#4818
    # 玄方城(the hold)：hold 被直译成"货舱/山房"（名词义；动词义"持有"按上一轮判例不动）
    (r"\bholds?\b", "货舱", "玄方城"),           # #466/#704/#712/#855/#988/#1103
    (r"\bholds?\b", "山房", "玄方城"),           # #2046/#2996/#3488
    # 州监(Intendant)：intendant 被直译成"总督/管家/管理员"
    (r"\bintendants?\b|\bintendance\b", "总督", "州监"),   # #2788/#2879/#2921/#2933
    (r"\bintendants?\b|\bintendance\b", "管家", "州监"),   # #690
    (r"\bintendants?\b|\bintendance\b", "管理员", "州监"),
    # 2026-10-30：「管理者/总管」原本是学习库裸键，改为英文锚定（裸键会误伤「岸管家→岸州监」）
    (r"\bintendants?\b|\bintendance\b", "管理者", "州监"),
    (r"\bintendants?\b|\bintendance\b", "总管", "州监"),
    # 朝月会(Waking Moon Festival)：中秋节是通用节日名，必须英文锚定
    (r"\bMoon Festival\b|\bWaking Moon\b|\bwaking moon\b", "中秋节", "朝月会"),   # #814
    # 封印(seal)：seal 被直译成"海豹"（动物名）
    (r"\bseals?\b", "海豹", "封印"),             # #2888/#5365
    # --- 2026-10-10 ADHD REACTS to Wuthering Waves 3.7 Hsin MAIN QUEST（kettletoro）二次校准 ---
    # celestial phantom（单数）->天人幻影：Entity ctx 正确形恒=canonical 会丢"幻影"，故走三元组
    (r"\bcelestial phantom\b", "天界幻影", "天人幻影"),
    # --- 2026-10-10 Jadealy REACTS to Every HSIN Trailers（鸣潮3.7「心」预告片合集 reaction）二次校准 ---
    #   目标非专名的口语/俚语错译，无合适 Entity canonical 承载，直挂本表。
    # 抽卡俚语：pull for=抽（卡）、pools=卡池（旧条 pulse/tent 在上方）
    (r"\bpull(?:ing|ed|s)?\b", "拉力", "抽卡"),       # pull for Shin 被译"为心月狐拉力"
    (r"\bpools?\b", "游泳池", "卡池"),               # our pools=我们的卡池
    (r"\bpools?\b", "泳池", "卡池"),
    # gems：主播对粉丝的昵称（呼语），非宝石；锚定呼语句式防材料/货币语境误伤
    (r"(?:thank you|telling me|you),?\s*gems?\b|\byou gems?\b", "宝石", "宝贝们"),
    # go=gold（金狐/红狐是不是两个心的讨论），谷翻作围棋；锚点收紧到 fox 讨论句（go 为超常用词，绝不裸锚）
    (r"separate like go\b|\bgo(?:ld)? and red fox\b", "围棋", "金"),
    # cinema/cinematics：主播俚语 peak/pure cinema=顶级大片，cinematics=过场动画；非电影院/电影学
    (r"\bcinema\b", "电影院", "大片"),
    (r"\bcinematics?\b", "电影学", "过场动画"),
    # Kuro cooked：褒义俚语"库洛杀疯了/做爆了"，非煮熟（ASR 作 Kura cooked，锚点兼容）
    #   目标用"杀疯"不带"了"：机译"煮熟了"替换后自然成"杀疯了"，避免"杀疯了了"叠字
    (r"\bKur[ao] cooked\b|\bcooked with (?:Shin|Hsin)\b", "煮熟", "杀疯"),
    # sister coded：网络词 sister-coded=姐姐感，非姐姐编码
    (r"\bsister[\s-]?coded\b", "姐姐编码", "姐姐感"),
    # --- 2026-10-10 My Thoughts on Wuwa's 3.7 Story（I Have Cried Again）二次校准 ---
    # Watcher：主播 LightfulWings 对梦州岁主心月狐的换称（the Watcher/Guardian），
    #   非黑海岸守岸人(Shorekeeper)；谷翻 cue45 作"监视者"，参考行 Watcher 锚定归"守望者"。
    #   （"守望者"被误归守岸人的回滚见 EXCLUDE_CONTEXT；"守护者"为 Guardian 正确译法不收。）
    (r"\bwatchers?\b", "监视者", "守望者"),
    # --- 2026-10-12 本片声纹筛选版（108 cue）三次校准 ---
    # past/previous/former Sentinel：官方作『前任岁主』；谷翻按字面出"过去的岁主"。
    #   ⚠ 必须走三元组：Entity('岁主').ctx 的 2 元组目标恒为 canonical「岁主」，
    #   会把"过去的岁主"整串吞成"岁主"、丢掉"前任"这一层（实测 #83 踩坑）。
    (r"\bpast\s+Sentinel\b|\bprevious\s+Sentinel\b|\bformer\s+Sentinel\b", "过去的岁主", "前任岁主"),
    (r"\bpast\s+Sentinel\b|\bprevious\s+Sentinel\b|\bformer\s+Sentinel\b", "以前的岁主", "前任岁主"),
    # --- 2026-10-10 ADHD REACTS to WuWa 3.7 Hsin MAIN QUEST（本片二次校准）---
    # 谷翻把心月狐(Shin)按常用词直译，但目标需保留原句虚词（非 canonical），
    # 只能走扁平 CONTEXT_MAP 三元组（Entity.ctx 的 2 元组目标恒为 canonical）：
    (r"\bShin\b", "真终于", "心月狐终于"),
    (r"\bShin\b", "叫信", "叫心月狐"),
    # --- 2026-10-12 WuWa 3.3 Story Reaction（I must save Aemeath!，10653 cue）二次校准 ---
    # '日向/日行/早之'（Hiyuki 错形）已挂绯雪 Entity.ctx；以下为无 Entity 挂靠点的锚定：
    (r"strider", "游侠门", "隧门"), (r"strider", "游侠之门", "隧门"),   # Strider Gate 谷翻拆词
    (r"strider", "游侠河", "隧门"), (r"strider", "游侠气体", "隧门"),   # ASR gate->河 / gase->气体
    (r"strider", "斯特赖德", "隧门"),                                  # 裸音译（观测站/裂隙等无"门"形）
    (r"\bvoidthirst\b", "虚空摇篮", "虚质渴望摇篮"),                    # Voidthirst Cradle 与 #9068 统一
    (r"\bvoidish\b", "虚空", "虚质色"),                                # gold -> voidish 颜色变化
    (r"\bvoids\b", "虚空", "虚质"),                                    # 复数形（\bVoid\b 命不中 voids/voidish）
    (r"and sol\.?", "太阳系", "太阳"),                                 # voids, storms, and sol（拉海洛地底无太阳）
    (r"\bbatter\b", "虚质击球科学", "虚质科学"),                        # ASR matter->batter（星炬学院虚质科学部）
    (r"\briders?\b", "骑士", "隧者"),                                  # Exor Rider 裸"骑士"（Rider 本义戒律禁裸键；#2269 参考行 rider 佐证）
    (r"Roya (?:designs|partners|are\b)", "Roya", "罗伊"),              # Roya 英文残留窄语境；作品名《Roya Frost》=罗伊冰原走 Entity.ctx
    # --- 2026-10-13 WuWa Exploration Quests and Tales round2：需参考行佐证的歧义错词 ---
    (r"\bChong Li\b", "重力", "长离"),                                 # Chong Li=长离 ASR（#286；"重力"通用词不进裸键）
    (r"\bHi\s?y?uki\b|\bHi\s?[Uu]ki\b", "浮喜", "绯雪"),               # Hiyuki=绯雪（#284）
    (r"\bHi\s?y?uki\b|\bHi\s?[Uu]ki\b", "宇基", "绯雪"),               # （#232）
    # --- 2026-11-08 Jadealy《鸣潮》3.8 前瞻片深度二校：Yuki 族拉丁 ASR 残形 → 绯雪 ---
    #   官中依据：萌娘百科译名对照表 Hiyuki=绯雪；官微「绯雪特别定制『月沉霜』」（3.8 服饰）。
    #   学习库 bi|由纪→绯雪 只处理中文「由纪」；残留的 Y uki / Yuki / Fy uka 由下列
    #   英文锚定三元组收口（长错形先行；一律不建裸键，避免跨片误伤）。
    #   ⚠ EXCLUDE_CONTEXT["由纪"] 已反转为「非 Yuki 语境才回滚」，不会回滚本组替换
    #     （engine.py 触发条件为 wrong in old，本组 old 不含「由纪」）。
    #   ⚠ CONTEXT_MAP 是 AST 字面量表（standalone/kb_admin.py 用 literal_eval 读），
    #     正则必须逐条写全，不可抽成变量。
    (r"\bYuki\b|\bY\s*u\s*ki\b|\bFy\s*u\s*ka\b|\bHi\s?y?uki\b", "Y uki", "绯雪"),
    (r"\bYuki\b|\bY\s*u\s*ki\b|\bFy\s*u\s*ka\b|\bHi\s?y?uki\b", "Yuki", "绯雪"),
    (r"\bYuki\b|\bY\s*u\s*ki\b|\bFy\s*u\s*ka\b|\bHi\s?y?uki\b", "Fy uka", "绯雪"),
    (r"\bpers ?im ?mons\b", "人鱼", "柿子"),                           # persimmons（#2299）
    (r"\bsc ?all ?ions\b", "离子", "葱花"),                            # scallions（#2456）
    (r"\bno rate\b", "没有命运", "没有概率公示"),                      # no rate->no fate ASR（#2431）
    (r"blow smoke up", "吹烟", "溜须拍马"),                            # blow smoke up ass（#2386）
    (r"rebuild", "重构版", "新剧场版"),                                # Evangelion rebuild（#2539/2544）
    (r"rebuild", "福音复兴剧", "EVA新剧场版"),                         # （#2565）
    (r"\bher ?esy\b", "她是这样", "这是异端"),                         # heresy（#2599）
    (r"\bavoid ?ant\b", "避开蚂蚁", "回避型"),                         # avoidant（#2625）
    (r"unt ?angling", "不划船", "解开纠葛"),                           # untangling（#2744）
    (r"rip ?pling", "撕裂着方向", "泛起涟漪"),                         # rippling（#2762）
    (r"\bre ?birth\b", "反叛军", "重生"),                              # rebirth（#2766）
    (r"aura ?farming", "刷气", "攒气场"),                              # aura farming（#2822）
    (r"got ?cha game", "有魅力的游戏", "抽卡游戏"),                    # gacha game（#2855/2906）
    (r"booty ?cheeks", "超级臀部", "烂透了"),                          # booty cheeks（#2889）
    (r"decomp", "分解", "反编译"),                                     # decompiling（#729/730）
    (r"\bGlacial\b", "冰川", "冷凝"),                                  # Glacial Damage Bonus（#733）
    (r"\bechoes\b", "回声", "声骸"),                                   # echoes=声骸（#721）
    # --- 2026-11-06 《I Played 300 Days of Wuthering Waves》（微软翻译，508 cue）二校沉淀 ---
    #   ⚠ **单复数就是判据**（同 2026-11-02 ④ a comments 判例）：上面 \bechoes\b 只认复数，
    #   本片单数 Echo 13 处全程漏校。裸键「回声」是通用词不可收（会误伤他游戏 literal echo），
    #   故补双 lookahead 锚：同参考行须另有养成语境词才改，命中面窄但可复跑。
    (r"(?=.*\b[Ee]cho(?:es)?\b)(?=.*\b(?:level|leveling|build|builds|set|sets|stat|stats|crit|farm|farming|max|roll|slot|substat|strategy|assembly|upgrade|imperfect|awful|valued|worst|best|only|good|option|options)\b)",
     "回声", "声骸"),
    #   ⚠ pity 锚**必须锁 good pity 专形**：#461 "It's a pity, a great pity"（普通可惜义）
    #   首版裸 \bpity\b 命中，把"真遗憾"咬成畸形"真保底"。抽卡黑话只出现在 good pity。
    (r"\bgood\s+pity\b", "好遗憾", "好保底"),                            # pity=抽卡保底（#447"好遗憾"）
    #   微软翻译通道 Sheena/Shina 的**中文侧音译**错形（拉丁侧 Sheena/Shina->心 已投影
    #   BILINGUAL_TERMS；错形长在哪侧规则就写哪侧——希娜/志奈 在中文行，须锚参考行）。
    #   ⚠ "真"（#69 Shin 音译）系超常用字，禁入表，只逐 cue。
    (r"\bSheena?\b|\bShina\b", "希娜", "心"),
    (r"\bSheena?\b|\bShina\b", "志奈", "心"),
    (r"\b(?:introductory|intro)\s+skills?\b", "入门技能", "变奏技能"),   # Introductory skill 官中=变奏技能（延奏=Outro，勿混）
    (r"\bsub-?genres?\b|\bsubstats?\b", "子流派", "副属性"),             # subgenres=ASR 形，官中=副属性（"副词条"为玩家语）
    (r"\bwave\s?(?:band|bands|plate|plates)\b", "波形板", "结晶波片"),   # wave plates 官中=结晶波片
    (r"\bwave\s?(?:band|bands|plate|plates)\b", "波带", "结晶波片"),
    (r"\btowers?\s+of\s+(?:trials?|discord)\b", "试炼之塔", "逆境深塔"),  # Tower of Trials 官中=逆境深塔
    (r"\btowers?\s+of\s+(?:trials?|discord)\b", "混乱之塔", "逆境深塔"),  # #327 同玩法的 ASR 异形
    (r"\bblooming\s+jade\s*hav?or?\b", "盛开的翡翠港", "玉阙玄华"),       # 心的专武（机翻把 Harbor 拆成"港"）
    (r"start the tails", "反面", "传说任务"),                          # story tails 撕裂（#704）
    (r"\bCritical\b", "关键难度", "Critical难度"),                     # Kingdom Hearts Critical（#1322）
    (r"\bpick ?y\b", "选择Y", "挑剔"),                                 # picky（#1457）
    (r"soft ?locked", "软锁", "卡死"),                                 # softlocked（#1523）
    (r"\barr ?anger\b", "愤怒", "编曲师"),                             # arranger ASR（#1590）
    (r"press in this track", "媒体", "贝斯"),                          # bass ASR->press（#1593）
    (r"tre ?acher ?ous", "非常强烈", "非常凶险"),                      # treacherous（#1607）
    (r"vocal ?fry", "声部炸弹", "气泡音"),                             # vocal fry（#1612）
    (r"imm ?olation", "免疫口服", "自焚"),                             # immolation（#1642）
    (r"gre ?asy", "紧张", "油腻"),                                     # Luna greasy（#1768）
    (r"gre ?asy", "你很有意思", "你好油腻"),                           # （#1770/1773）
    (r"gre ?asy", "全是灰色的", "全是油"),                             # （#1771）
    (r"disillusion ?ed", "失望", "幻灭"),                              # （#1776）
    (r"three houses", "三座房子", "风花雪月"),                         # FE Three Houses（#1802）
    (r"Unicorn Over ?lord", "独角兽", "圣兽之王"),                     # Unicorn Overlord（#1815/1816）
    (r"Hex ?agram", "六角星", "六芒星"),                               # Hexagram（#1190）
    (r"spl ?urge", "SPL有点冲动", "挥霍一下"),                         # splurge（#1432）
    (r"inc ?ensed", "很有把握", "被激怒"),                             # incensed（#881）
    (r"fer ?ocious", "非常神秘", "非常凶猛"),                          # ferocious（#884）
    (r"被药物折磨得很糟糕", "被药物折磨得很糟糕", "真的很失落"),       # bummed out（#1037；英文行锚定）
    (r"service ?able", "还算可以维修", "还算凑合"),                    # serviceable（#1040）
    (r"go ?oner game", "普通的游戏", "卖肉游戏"),                      # gooner game（#3401）
    (r"waif ?us", "我们", "老婆"),                                     # waifus（#3952）
    (r"norm ?ie", "正常的", "普通玩家"),                               # normie（#3985）
    (r"norm ?ie", "常态", "普通玩家"),                                 # （#3991）
    (r"pilled", "迷糊", "入坑"),                                       # pilled（#4005）
    (r"co ?- ?op", "合作社", "联机"),                                  # co-op（#3889）
    (r"co ?- ?op", "合作教育", "联机"),                                # （#3890）
    (r"\bSon ?ny\b", "儿子", "桑尼"),                                  # Sonny 观众名（#3797）
    (r"run ?backs", "回溯", "跑尸流程"),                               # run backs（#3783）
    (r"alien ?ate", "外星人吃掉", "疏远"),                             # alienate（#3657）
    (r"engaged", "订婚", "投入"),                                      # engaged（#4285）
    (r"before the tip", "提示", "旅行"),                               # tip=trip（#4297）
    (r"pass as Ace", "以艾斯的身份", "以王牌难度"),                    # Ace=Ace difficulty（#4158）
    (r"\bdeadlock\b", "僵局", "Deadlock"),                             # Deadlock 保留英文（#4130）
    (r"\bMiho\b", "美穗", "米哈游"),                                   # miHoYo（#3959/3960）
    (r"\bIm ?eth\b", "我是eth", "爱弥斯"),                             # Imeth（#3948）
    (r"\bAn ?anta\b", "Anta", "无限大"),                               # Ananta 谷翻残留（#1715）
    (r"\bAn ?anta\b", "Ananta", "无限大"),                             # 中文行英文残留（#414/3986/3994）
    (r"\bLim ?bus\b", "林巴斯", "边狱公司"),                           # Limbus Company（#409）
    (r"\bLim ?bus\b", "林巴士", "边狱公司"),                           # （#422）
    (r"\bLim ?bus\b", "林姆公交", "边狱公司"),                         # （#455/456）
    (r"bus Company videos", "公交公司", "边狱公司"),                   # （#464）
    (r"behind a pass", "传球后面", "战令后面"),                        # battle pass（#2159）
    (r"\bWu\b", "吴博士", "鸣潮"),                                     # Wu=WuWa（#4231）
    (r"\bWua\b", "演吴", "玩鸣潮"),                                    # （#3880）
    (r"\bWu\b", "锁定在吴", "锁定鸣潮的"),                             # （#3702）
    (r"\bWulu\b", "Wulu", "鸣潮"),                                     # WuWa ASR（#598；英文行佐证）
    (r"from San\b", "从San身上", "从散华身上"),                        # Sanhua（#2186）
    # 2026-11-12 删除重复生效条：该规则已由上方 2026-10-13 废除条永久否决（psychoanalyze 病句）。
    # (r"\bpsycho\b", "心理", "疯子"),               # #559
    # --- 2026-10-14 蓝色星原延期杂谈片 二次校准沉淀（谷翻常用词义错位，全部窄锚定）---
    (r"\bcharacter\b", "追求品格", "追求角色"),     # #321 seek character releases（character=角色，品格义错位）
    (r"\bcharacter\b", "那个性格", "那个角色"),     # #332 get that character（性格=角色 错译）
    (r"\bmultiple tests?\b", "检查", "测试"),       # #254 multiple tests=多次测试（抽卡封闭/内测）
    (r"\bsimultaneous release\b", "释放", "发布"),  # #267 simultaneous release=同步发布
    (r"\bpoor showing\b", "这场比赛", "这次展示"),  # #144 poor showing=这次展示很差（showing 比赛义错位）
    (r"\bdiscus- ?discussions?\b", "Discus讨论", "讨论"),  # #56 ASR 口吃残片 discus- discussions，清残留
    # --- 2026-10-16 3.7 Epilogue reaction 二次校准沉淀（英文佐证，防误伤普通词）---
    (r"\bnexus\b", "核心", "梦枢天罗"),          # #1719 "within the nexus"->核心（#835 proliferation core 正确，故须佐証）
    (r"\bcapsule\b", "舱体", "文明之匣"),        # #169/#183/#326/#393/#1297 全为 capsule，与其余 cue 的文明之匣一致
    (r"\bSentinel\b", "守护者", "岁主"),         # #602/#1747 sentinel->守护者（岁主为本片既定译法）
    # 2026-10-22 撤销：Susheen/Sushin 是 3.7 独立角色「溯心」（ENTITIES canonical），
    #   不是 Sheen 的误读。旧规则会把正确的「溯心」二次改成「心月狐」，本片实测大面积误伤。
    # (r"\bSusheen\b", "溯心", "心月狐"),
    (r"\bSchwanqing\b", "天清", "玄方清"),       # #1046/#1275 Schwanqing->天清（玄方清 形近错字）
    (r"\bShin\b", "信", "心月狐"),               # #692 Shin(=Sheen)机翻单字->信，应为心月狐（信为常见字，须佐証）
    # --- 2026-10-20 谷翻「游戏音乐 WTF reaction」片沉淀（MarcoMeatball，582cue）---
    # 本类片头号漏校模式：英文曲名/游戏名被谷翻**当普通词直译**，中文侧看着是好词
    # （黑帮/失落/沉默街/欲望流下），裸键必误伤正常语境，一律走参考行英文锚定。
    # 依据：本片 verify src↔成品 逐条对照 + kb-lookup 交叉确认（剑星/龙背上的骑兵/明日方舟已有）。
    (r"\bYakuza\b", "黑帮", "人中之龙"),                     # #329 Yakuza->黑帮（SEGA 官方简中 人中之龙，旧译/口语 如龙）
    (r"\bSoken\b", "宗研", "祖坚正庆"),                        # #401 Soken->宗研（FF14 作曲，官方中文 祖坚正庆）
    (r"\b(?:Stellar Blade|Seller\s?blade)\b", "卖家之刃", "剑星"),  # #315 Sellerblade(ASR 连写断词)->卖家之刃，同 #1523 星刃
    (r"\bFire Emblem Fates\b", "火焰纹章命运", "火焰之纹章 if"),    # #157 Fates 被直译成"命运"；本作**无官方简中**，if 为维基/萌百通行形
    (r"\bFire Emblem Fates\b", "火焰纹章：命运", "火焰之纹章 if"),   # #160 同错形的带冒号变体
    (r"\bDesire Below Flow\b", "欲望流下", "Desire Below Flow"),    # #159 曲名直译；单语官方名→保留原语言
    (r"\bSilent Street\b", "沉默街807号", "Silent Street 807"),     # #279 先吃带"号"的整形，防中英粘连
    (r"\bSilent Street\b", "沉默街", "Silent Street"),              # #279 Stellar Blade 曲名直译，同上
    (r"\bTitan Lost\b", "泰坦：失落", "Titan Lost"),                # #365 FF16 曲名直译，同上（不带冒号的"失落"不收）
    # --- 2026-10-20 3.7 后日谈《璇心如月寄尘情》reaction 二次校准沉淀（英文佐证，防误伤通用词）---
    #   官方依据同上；旧条目 (r"\bSchwanqing\b", "天清", "玄方清") 目标有误，本块在其后回滚为璇情。
    #   Swan Ching 曾被裸键 "Ching"->清宵 误咬成「清宵」，须拉回「璇情」。
    (_XQ_RX, "玄方清", "璇情"),
    (_XQ_RX, "玄方 清宵", "璇情"),
    (_XQ_RX, "玄方清宵", "璇情"),
    (_XQ_RX, "清宵", "璇情"),
    (_XQ_RX, "Swan 璇情", "璇情"),
    (_XQ_RX, "Swan璇情", "璇情"),
    #   天鹅=swan 是通用词，只在英文确指人名（Schwan 整词，或整行 Swan/Swan Ching）时才改
    (r"\bSchwan\b", "天鹅", "璇情"),
    (r"(?i)^\s*Swan[,.!?]?\s*$|\bSwan\s+Ching\b", "天鹅", "璇情"),
    #   Schwanfang Wardens=玄方守望者；基线把 Wardens 误映射成守岸人
    (r"\bSchwanfang\s+Wardens\b", "守岸人", "守望者"),
    (r"\bSchwanfang\s+Wardens\b", "天鹅坊", "玄方"),
    #   Heart of Ruin=墟心（3.7 墟心域）；修基线「废墟之心/毁灭之心」
    (r"\bheart of ruin\b|\bHeart of Ruin\b", "废墟之心", "墟心"),
    (r"\bheart of ruin\b|\bHeart of Ruin\b", "毁灭之心", "墟心"),
    #   新任岁主「心」(Hsin) vs 原岁主「心月狐」：new/current day Sheen 指心
    (r"\bnew\s+sheen\b|\bcurrent\s+day\s+sheen\b", "新的心月狐", "新的心"),
    (r"\bnew\s+sheen\b|\bcurrent\s+day\s+sheen\b", "如今的心月狐", "如今的心"),
    (r"\bnew\s+sheen\b|\bcurrent\s+day\s+sheen\b", "现在的心月狐", "现在的心"),
    #   Schwangfong Hold 的「玄方城要塞/玄方要塞」在本片统一为玄方城；不碰其他片的要塞用法
    (r"\bSchwangfong(?:\s+Hold)?\b|\bSchwanfong(?:\s+Hold)?\b|\bSchwanfang\b|\bShwang\s*Fong\b", "玄方城要塞", "玄方城"),
    (r"\bSchwangfong(?:\s+Hold)?\b|\bSchwanfong(?:\s+Hold)?\b|\bSchwanfang\b|\bShwang\s*Fong\b", "玄方要塞", "玄方城"),
    #   「尚方/尚方堡」= Shwang Fong(玄方城) 同音残留；尚方宝剑等历史词不在英文锚点内，安全
    (r"\bShwang\s*Fong\b|\bSchwangfong\b|\bSchwanfong\b", "尚方堡", "玄方城"),
    (r"\bShwang\s*Fong\b|\bSchwangfong\b|\bSchwanfong\b", "尚方", "玄方城"),
    #   级联兜底（长键短键同长度时，中间形态可能落在短键之后，故在 term pass 后再收一次）
    (r"\bShin\b|\bSheen\b|\bMoon\s*Fox\b|\bMoonf\s*Fox\b", "心月狐心月狐", "心月狐"),
    (r"\bNexus\b", "时空枢纽", "梦枢天罗"),
    (r"\bNexus\b", "时空梦枢天罗", "梦枢天罗"),
    (r"\btacet discord\b|\btacid\b", "残象不和谐", "残象"),
    (r"cloud shuttle", "云云梭", "云梭"),
    # --- 2026-10-23 鸣潮 2.0 OST reaction（EchoBoy 音效段）---
    #   ping pong delay = 乒乓延迟；谷翻作「乒乓球」，按英文锚定纠正，
    #   不再依赖 ENTITIES「终末地蓬蓬」的裸变体（该实体已收窄到 endo/endobi）。
    (r"\bping[- ]?pong\b", "乒乓球", "乒乓延迟"),
    # --- 2026-10-23 Journey Well'ed（Juno 的鸣潮 3.1 拉海洛实况）二校沉淀 ---
    #   均为「参考行锚定 + 中文错形」；_ctx_replace 对 wrong⊂right 有 \x00 哨兵保护。
    (r"\bMorier\b", "莫里尔", "莫宁"),        # Professor Morier = 莫宁教授（Mornye 的 ASR 变体）
    (r"\bsynchronous\b", "同步者", "适格者"),  # synchronist 的 ASR 变体（旧锚点只认 synchronist，本片 #178 漏校）
    (r"\bAlf\b", "阿列夫", "阿列夫一"),        # 半截名补全（#1205/#1210/#1214/#1260）；既有「阿列夫一」由哨兵保护
    # --- 2026-10-24 Journey Well'ed 二校补漏（官方中文再核）---
    #   官方依据：萌娘百科「虚质磁暴」「飞行雪绒」、官方角色档案「星炬学院拉贝尔学部」、
    #   官方 3.1 内容说明。以下均为通用中文词/英文 ASR 误听，必须英文锚定，禁止裸键。
    (r"\bRebel College\b", "星炬学院", "拉贝尔学部"),       # 本片 #101-102：Rebel College=拉贝尔学部，非上位机构
    (r"\bKako home\b", "卡可家", "回家"),                  # #690 Kako=back 的 ASR 误听
    (r"\bShawinger'?s cat\b", "Shawinger 的猫", "薛定谔的猫"),  # #815 Schrödinger's cat
    (r"\bAidious\b", "Aidious", "观众"),                    # #1090 audience 误听
    (r"\bInsane (?:lord )?lore drop\b", "疯了一样的掉率", "这剧情爆料太猛了"),  # #396 lore drop≠掉率（整句覆盖，防"疯了一样的剧情爆料"）
    (r"\b(?:Curl|Kuro|Curo) [Gg]ames\b", "抽卡游戏", "库洛游戏"),  # #175 Curl games=Kuro Games；抽卡游戏是通用词，只走英文锚定
    # ── 2026-11-07 补：本片 cue1260「[ __ ] 展示。不像库洛品质，但是」/ EN "Not like in Kuro quality, but"
    #   Kuro Games 官方中文=库洛游戏（官网 kurogame.com「库洛游戏 KURO GAMES」；
    #   库洛用户协议 mc.kurogame.com/p/agreement_public.html 1.1 条「『库洛』或『库洛游戏』」）。
    #   wrong 侧「库洛品质」含通用词「品质」⇒ 只走参考行锚定，禁裸键。
    (r"\bKuro\s+quality\b", "库洛品质", "库洛游戏品质"),
    (r"\bSave her\b", "存档", "救她"),                      # #269 Save her≠存档
    (r"\bI am Ian, the Academy star\b", "我是伊恩", "我是爱弥斯"),  # #771 Ian=Aemeath 误听；Ian 是常见名，只走窄锚定
    (r"\breactor (?:core|drive)\b", "反应堆核心", "炉芯"),    # #189/#492/#1226/#1308 reactor=炉芯
    (r"\breactor (?:core|drive)\b", "反应堆", "炉芯"),
    (r"\breactor (?:core|drive)\b", "核心", "炉芯"),
    # --- 2026-10-24 沉淀 wuwa_explore_tales 侧车 11 条中的通用规则 ---
    #   其余 5 条（月狐罪 ctx 级联 / 阳光玲 / 库洛空格等）属错位或一次性整行，仍按侧车处理。
    (r"\bMid\s*na\b|\bMidna\b", "米达妮娅", "米德娜"),          # #152 Midna 是塞尔达角色，勿套鸣潮达妮娅
    (r"\brem\s*aster\b|\bremaster\b", "疏忽的Aster", "重制版"),    # #1857 rem aster ASR 断词
    (r"\bSentin\s*els?\b", "天民", "岁主"),                      # #2307 Sentin els = Sentinel
    (r"\bSentinel\b", "守护者", "岁主"),                         # #2788 Sentinel 被误译守护者
    (r"\bRes\s*on\s*ator\b", "岁主 Res", "岁主共鸣者"),           # #2307 跨行断词（长键先行）
    (r"\bRes\s*on\s*ator\b", "雷斯", "共鸣者"),                  # #2788/#2307 Res on ator 断词
    # --- 2026-10-24 鸣潮新加坡音乐会 vlog（zKodla）二校沉淀 ---
    #   参考行 Ankor/Anoro/Anchor 才把中文「锚点/锚」还原成角色安可。
    #   ⚠ 不用单字「锚」规则：会把「抛锚」咬成「抛安可」（本片 #510 实测），改用具体短语。
    (r"\bAnkor\b|\bAnoro?\b|\bAnchor\b", "锚点", "安可"),      # #541/#549/#571
    (r"\bAnkor\b|\bAnoro?\b|\bAnchor\b", "抛锚", "安可"),      # #510/#554（整词，防「抛安可」）
    (r"\bAnkor\b|\bAnoro?\b|\bAnchor\b", "那个锚", "那个安可"), # #551
    (r"\bAnkor\b|\bAnoro?\b|\bAnchor\b", "像锚一样", "像安可一样"),  # #553
    (r"\banor\b", "Anor", "安可"),                             # #545 参考行 anor 的英文残留
    (r"\bBras Basah\b|\bbrass basa\b", "铜巴萨站", "百胜站"),   # #55 新加坡地铁 CC2
    # 既有规则的精确回滚（本片实测误伤）：
    (r"\bback Daniel\b", "达妮娅", "Daniel"),                   # #96 工作人员 Daniel≠Dennia

    # --- 2026-10-27 鸣潮 3.1「赠予雪中的你」精校沉淀（官方中文再核）---
    #   官方依据：3.1 内容说明/剧情文本/角色档案；通用词一律英文参考行锚定，禁止裸键。
    (r"\bvoid matter\b", "虚空物质", "虚质"),                    # Fodian void matter=虚质
    (r"\bvoid matter\b", "佛达虚空物质", "虚质"),                # 谷翻'佛达虚空物质'
    (r"\bFodian\b", "佛地亚", "虚质"),                           # ASR Fodian -> 虚质
    (r"\bthe void\b", "虚空", "虚质"),                            # the void=虚质
    (r"\bFrostlands\b", "霜原", "冰原"),                          # Frostlands=冰原
    # 3.1 官方原句（逐行锚定；仅在本片/同场景命中）
    (r"\bI hope to make you proud\b", "但愿我能让你骄傲", "但愿我会让你感到骄傲"),
    (r"\bI haven't made it\.", "我还没做到。", "但愿我没有让你失望。"),
    (r"\bI wish that in your long long life\b", "我希望在你漫长的一生里，", "我希望，在你未来漫长的生命中，"),
    (r"\bnever forget how to \[music\] feel the\b", "永远不要忘记如何[音乐]感受", "仍旧能够感知悲伤，"),
    (r"\bsorrow and the joy\.", "悲伤与喜悦。", "也能时常觉得幸福。"),
    (r"\bTo live a happy life\.", "就是幸福地活着。", "我只希望你能轻松快乐地活着。"),
    (r"\bI will be there for everyone as we head\b", "我会陪在大家身边，一起走向", "我想留在大家身边……"),
    (r"\btoward our shared future, leaving the\b", "共同的未来，把过去留在", "从过去，"),
    (r"\bpast behind\.", "身后。", "一同迈向明天。"),
    (r"\bRover, their pain is no different from\b", "漂泊者，他们的痛苦", "漂泊者，我的痛苦和他们中任意一者的，"),
    (r"^mine\.$", "和我的一样。", "并无区别。"),
    (r"\bNeither is their joy\.", "他们的喜悦也是。", "我的幸福，也与他们无异。"),

    # --- 2026-10-25 鸣潮 4.0 新联邦 reaction 片（474 cue）二校沉淀 ---
    (r"\bSon(?:oro|aro)\s+spheres?\b", "Sonaro 球体", "索诺拉"),
    (r"\bSon(?:oro|aro)\s+spheres?\b", "Sonoro 球体", "索诺拉"),
    (r"\bSon(?:oro|aro)\s+spheres?\b", "球体", "索诺拉"),
    (r"\bFallacy of (?:No )?Return\b", "回报的谬误", "无归的谬误"),
    (r"\bFallacy of (?:No )?Return\b", "归来的谬误", "无归的谬误"),
    (r"\btacit marks?\b", "默认标记", "声痕"),
    (r"\bJer\b", "杰尔", "角"),
    (r"\bJouer\b", "乔尔", "角"),
    # 2026-11-13 负向守卫：含 2B 的行是尼尔梗（2B/2A，TRANSCENDO reaction #173 实测误伤），
    # 不触发 2A→角；无 2B 的行仍按 4.0 新联邦片 Jué 误听修正。
    (r"^(?!.*\b2B\b).*\b2A\b", "2A", "角"),
    (r"\bMour\b", "莫尔", "莫宁"),
    (r"\bMou\b", "穆", "莫宁"),
    (r"\bAbrais\b", "阿布拉伊斯", "阿布拉克萨斯"),
    (r"\bA\s+brais\b", "一个brais", "阿布拉克萨斯"),
    (r"\bArais\b", "Arais", "阿布拉克萨斯"),
    (r"\bA\s+Braxis\b", "布拉克西斯人", "阿布拉克萨斯"),
    (r"\bAmth\b|\bAmoth\b", "阿姆斯", "爱弥斯"),
    (r"\bAmeth\b|\bAmoth\b", "紫草酸", "爱弥斯"),
    (r"\bFederation\b", "联邦", "新联邦"),
    (r"\bFederation\b", "新的新联邦", "新联邦"),   # #355 原文「新的联邦」被通用规则叠成「新的新联邦」
    (r"\bNew\s*$", "New", "新联邦"),
    (r"\bAcademy\b", "学院", "星炬学院"),
    (r"\bShorekeeper\b|\bShortke\b", "岸上管理员", "守岸人"),
    (r"\bShortke\b", "肖特克守门员", "守岸人"),
    (r"\bChang\s+Lee\b", "张李", "长离"),
    # --- 2026-11-13 《I KNEW WUTHERING WAVES WAS COOKING》（MarcoMeatball，324 cue，默认 bi）TRANSCENDO 精校同步 ---
    # 官中台词依据：B 站官中 PV BV1p8nh61Efm 中配音频本地 large-v3 ASR（VAD 阈值 0.15）。
    # 全部英文参考行锚定，仅对应 trailer 台词出现才触发；encounters/be made 跨 cue 断行，用 ^ 锚定行首。
    # 通用词（我还是/打扰一下）不收，防跨片误伤。
    (r"\bdawn of change\b", "变革的黎明", "一切改变的开始"),
    (r"\bof what'?s to come\b", "害怕未来的未来", "成为未来的终局"),
    (r"^encounters\b", "遭遇", "邂逅"),
    (r"\b[Aa] choice\b", "一个选择", "一个抉择"),
    (r"^be made\b", "被制造出来", "做出"),
    (r"\bshall find new life\b", "将找到新生命", "将获得新生"),
    (r"aren'?t you forgetting\b", "但你是不是忘了什么", "还忘了点什么"),
    (r"\bbeyond their gaze\b", "在过去，超越了他们的视线", "在他们目光都无法触及的过去"),
    (r"\bend of the deal\b", "履行我的承诺", "履行着与你的交易哦"),
    (r"\bI know you'?re anxious\b", "我知道你很焦虑", "我知道你很着急"),
    (r"\bplan on dropping by\b", "我打算去看看", "也准备小小的放个风"),
    # Hydra=残星会成员代号（与 Eris/Phrolova 并列），官方中文未实装，保留英文不臆造九头蛇/海德拉：
    (r"\bHydra\b", "九头蛇", "Hydra"),
    # --- 2026-10-25 TRANSCENDO 单文件补丁回灌（源码此前未同步）---
    (r"\bCanorilla\b", "卡诺里拉", "坎特蕾拉"),
    (r"it's Cruel Games\b", "残酷游戏", "库洛游戏"),
    (r"\bArais\b", "阿赖斯", "阿布拉克萨斯"),
    (r"\bARais\b|\bARAIS\b", "阿莱斯", "阿布拉克萨斯"),
    (r"\b[Ll]oop\b.*\bwolf\b|\bwolf\b.*\b[Ll]oop\b", "Loop", "露帕"),
    (r"\b[Cc]arter\s+thers\b", "卡特", "卡提希娅"),
    (r"\b[Ff]allac[iy]", "法拉奇", "无归的谬误"),
    (r"\b[Ff]ouse", "福斯", "无归的谬误"),
    (r"\b[Ii]shmael\b", "以实玛利", "伊什梅尔"),   # 2026-11-04 目标形改对；同表的恒等条目已删
    (r"\blight\s+[Ll]ily\b", "光百合", "光之莉莉"),
    # ── 2026-11-07 补：本片 cue1244「对百合销量影响不大。是的」/ EN "doesn't affect Lily sales much."
    #   Lily=莉莉（鸣潮 3.8 新共鸣者；库洛 3.8 前瞻官方中文「莉莉」，国服媒体同证；
    #   本项目 data/ja.py 已记「官方中文=莉莉（片内一手 #2032/#2035 官方繁中）」）。
    #   「百合」是高频通用词（花卉/食品/俚语），按硬契约第 4 条**禁裸键**，
    #   只走 CONTEXT_MAP 英文参考行锚定；并配 EXCLUDE_CONTEXT["百合"] 防二次咬坏
    #   「光百合 / 光之莉莉」等既有正确形（terms-check 的 ctx 叠字检查查不出「百合」∉「莉莉」）。
    (r"\bLily\b", "百合", "莉莉"),
    # 2026-11-09 二次校准补：中文行直接保留英文 Lily（谷翻整词未译，本片 cue256/2977/2978）。
    # 上条锚 wrong=中文错形"百合"，咬不到英文残留；补 wrong="Lily"，参考行 \bLily\b 佐证。
    (r"\bLily\b", "Lily", "莉莉"),
    # 2026-11-08：Lili 是莉莉的英文 ASR 异形（3.8 Lily 前瞻片 cue66 实测「丽丽」）。
    # 只锚 Lili + 中文错形，不并入 Lily 的「百合」锚，避免复用「光百合」负例语义。
    (r"\bLili\b", "丽丽", "莉莉"),
    (r"\bLili\b", "莉丽", "莉莉"),
    # 2026-11-08 Jadealy 3.8：#39 "Lilies for Lily." 是「花 + 角色」双关。
    #   \bLily\b 锚会把「百合给百合」双改成「莉莉给莉莉」；EXCLUDE 的全行回滚
    #   又会把人工精确修好的「百合给莉莉」一并退回（历史铁律：负例非逐词回滚）。
    #   故改用幂等收口条：源形与终稿经锚后都到「莉莉给莉莉」，再统一收成「百合给莉莉」，
    #   保证「成品再跑一遍 = 0 改动」。
    (r"\blilies\s+for\s+lily\b", "莉莉给莉莉", "百合给莉莉"),
    # --- 2026-10-27 Back from Vacay 二次校准：歧义/短键走参考行锚定 ---
    (r"\bMorta\b|\bMohrta\b", "Morta", "默尔塔"),
    (r"\bWua\b", "Wua", "鸣潮"),
    (r"\bOcarina of Time\b|\bOcarine of Time\b", "陶笛", "时之笛"),
    (r"\bOcarina of Time\b|\bOcarine of Time\b", "时间之笛", "时之笛"),
    # 2026-11-02：锚点补 \bEnfield\b —— ASR 常吞掉 d 只给 Enfield，旧正则命不中导致
    # 「恩菲尔德」漏校（本片 #286/#3241/#3242 实测）。Enfield 亦可指李-恩菲尔德步枪，
    # 故保留「参考行须含 Enfield + 中文行须已出现恩菲尔德」双条件，不做裸键。
    (r"\bEndfield\b|\bEnfield\b|\bArk Knight's Endfield\b", "恩德菲尔德", "终末地"),
    (r"\bEndfield\b|\bEnfield\b|\bArk Knight's Endfield\b", "恩菲尔德", "终末地"),
    (r"\bNouni\b|\bNi no Kuni\b", "努尼", "二之国"),
    (r"\bHeart Seal\b|\bSeal song\b", "封印之歌", "HEARTSTEEL"),
    (r"\bWar of the Worlds\b", "战争之战", "世界大战"),
    (r"Nightmare Before", "噩梦", "《圣诞夜惊魂》"),
    (r"Nightmare Before", "Nightmare", "《圣诞夜惊魂》"),
    (r"for your name, Arkan Knights", "阿尔坎骑士", "Arkan Knights"),
    (r"for your name, Arkan Knights", "阿尔坎明日方舟", "Arkan Knights"),
    # --- 2026-10-27 3.X 巡演/EP 二次校准补漏 ---
    (r"\b(?:Solless|soul ?skin)\b", "小皮肤", "日灵"),
    (r"\bAlissium\b", "极乐", "向彼方行"),
    (r"\bAlissium\b", "伊利西姆", "向彼方行"),
    # --- 2026-10-27 鸣潮 5h47 巡演/EP 二次校准（CONTEXT）---
    (r"\bSeptimont?\b", "Septimon", "七丘"),
    (r"\bSeptimo\b", "Septimo", "七丘"),
    (r"\bJing\b.*\boutshines\b|\boutshines\b.*\bJing\b", "Jing", "景燃"),
    (r"\bEncor\b.*\barea\b|\barea\b.*\bEncor\b", "Encor", "安可"),
    (r"\bchat\.\s*Blade\b", "Blade", "《银翼杀手》"),
    (r"\bThat's (?:just )?Blade\b|\bBlade correct\b", "Blade", "《刀锋战士》"),
    # --- 2026-10-28 《索拉逐星舞台 第二季》reaction 片（同一片源）---
    #   错形均为通用中文词/短名，全部参考行锚定；已排除与既有 Chisa/千纱、Yuki/雪、
    #   Rover/流浪者 的重复。Daniela 旧注“=丹妮拉，非同一人，勿收”，本片只加
    #   “Daniela the teacher”窄锚（#141/#164 抽帧确认幼儿园老师是达妮娅）。
    (r"\bSolar Stage\b|\bSolar story stage\b", "太阳阶段", "索拉逐星舞台"),      # #592
    (r"\bSolar Stage\b|\bSolar story stage\b", "太阳故事阶段", "索拉逐星舞台"),  # #751
    (r"\bBecoming taboo\b", "变成禁忌", "渐成禁忌"),                              # #239 官方节目名
    (r"\bSavior from Royal Frostland\b", "皇家霜地", "罗伊冰原"),                 # #434
    (r"\bSavior from Royal Frostland\b", "皇家冰原", "罗伊冰原"),
    (r"\bthe new world live tour\b", "新世界巡演", "「致予新世界」巡演"),          # #581 官方节目名
    (r"\bLooping June\b|\bLupin June\b", "循环六月", "Loop in June"),             # #693/#704 官方曲名
    (r"\bLooper\b", "环形人", "露帕"),                                            # #33
    (r"\bLooper\b", "环形者", "露帕"),                                            # #33
    (r"\bLooper\b", "环形灯塔", "露帕"),                                          # #38
    (r"\bLoofa\b", "丝瓜络", "露帕"),                                             # #215
    (r"\bLupo\b", "卢波", "露帕"),                                                # #362
    (r"\bLupus world\b", "狼疮", "露帕"),                                         # #408 Lupus=Lupa's ASR
    (r"\bCarlotta\b", "卡洛塔", "珂莱塔"),                                        # #673
    (r"\bBrent\b", "布伦特", "布兰特"),                                           # #223/#224
    (r"\bDaniela the teacher\b", "丹妮拉", "达妮娅"),                             # #141 窄锚
    (r"\bMori\b", "森", "莫宁"),                                                  # #160 抽帧推断（星炬学院教授）
    (r"\bCamellia\b", "山椿地区", "《Camellia》"),                                # #284 长形先行（此处 Camellia 是曲名，非角色椿）
    (r"\bCamellia\b", "山椿", "椿"),                                              # #411/#415/#712/#742
    (r"\bDenia Kindergarten\b", "达妮娅幼儿园", "星炬幼儿园"),                    # #706 官方节目名 Startorch Kindergarten
    (r"\bStrider\b", "游侠", "隧者"),                                             # #521 中文“游侠踢”
    (r"\bYuno\b", "优诺", "尤诺"),                                                # “优诺”是品牌词，禁裸键
    (r"\bRovers\b", "流浪者", "漂泊者"),                                          # #5 复数形
    # --- 2026-10-28 《INSANE LORE DROPS…TRANSCENDO》737 cue ---
    #   通用词/短名一律参考行锚定（定论/洛娃/雷纳/泰图斯）。
    (r"\btheodians?\b|\bThrodian\b", "定论", "鸣式"),                            # #542
    (r"\bLova\b", "洛娃", "弗洛洛"),                                              # #155/#158
    (r"\bRena\b", "雷纳", "黎那汐塔"),                                            # #450
    (r"\bTeeta\b|\bTeta\b|\bTethus\b|\bTethys\b", "泰图斯", "泰缇斯"),            # #579
    # --- 2026-10-30 Jadealy《TRANSCENDO》reaction 片二次校准沉淀 ---
    #   Somnoire=心之集域：旧规则已把部分成品改成「索诺拉」，此处按英文行兜底回滚。
    (r"\bSomnoire\b|\bSom\s*Noir\b|\bSomnoir\b|\bSomnir\b", "索诺拉", "心之集域"),
    #   黑石=Tacetite：谷翻把 tacetite 译成「菱镁石/菱镁矿」。
    (r"\btacetites?\b|\btacetides?\b", "菱镁石", "黑石"),
    (r"\btacetites?\b|\btacetides?\b", "菱镁矿", "黑石"),
    #   2026-10-30《INSANE LORE DROPS》#256：谷翻把 tacetite 逐字直译成「斜斜晶石」。
    #   长键先行，否则 "斜晶石" 会把 "斜斜晶石" 咬成 "斜黑石"。
    (r"\btacetites?\b|\btacetides?\b", "斜斜晶石", "黑石"),
    (r"\btacetites?\b|\btacetides?\b", "斜晶石", "黑石"),
    #   残象=Tacet Discord：谷翻把 tacet discourse 译成「残象话语」。
    (r"\btacet\s+discourses?\b", "残象话语", "残象"),
    #   声痕=Tacet Mark：ASR 把 tet marks 听成「春节标记」。
    (r"\btet\s+marks?\b|\btac[ei]t\s+marks?\b", "春节标记", "声痕"),
    (r"\btet\s+marks?\b|\btac[ei]t\s+marks?\b", "新年标记", "声痕"),
    #   纯白之塔=White Tower（鸣式）；「白塔」是通用词，只在英文行命中时纠正。
    (r"\bWhite Tower\b", "白塔", "纯白之塔"),
    (r"\bWhite Tower\b", "白色之塔", "纯白之塔"),
    #   会监=Overseer（残星会五会监）；监工/监督者/监督员 均为通用词，只在英文行命中时纠正。
    (r"\boverseers?\b", "监工", "会监"),
    (r"\boverseers?\b", "监督者", "会监"),
    (r"\boverseers?\b", "监督员", "会监"),
    #   Shorty Bear = Shorekeeper 的 ASR 误听（2026-10-30《INSANE LORE DROPS》#400
    #   谷翻作「小熊的蝴蝶」；蝴蝶是守岸人的标志）。「小熊」是通用词，只在英文行命中时纠正。
    (r"\bShorty\s+Bear'?s?\b", "小熊", "守岸人"),
    # --- 2026-10-30 鸣潮 3.5 主线 reaction（8126 cue，英语原声+谷翻）---
    # 夜归(Midnight Rangers)：裸键「午夜→月见夜」是明日方舟干员名，跨游戏误伤；
    #   英文行命中时把已替换出的「月见夜」回滚为「夜归」。
    (r"\bMidnight\s*Rangers?\b", "月见夜", "夜归"),
    (r"\bMidnight\s*Rangers?\b", "午夜游侠", "夜归"),
    # 秧秧(Yangyang)：谷翻把拆写人名原样保留；Yap Yap 是主播对她的昵称。
    (r"\bYang\s*yang\b|\bYap\s*Yap\b", "杨阳", "秧秧"),
    (r"\bYang\s*yang\b|\bYap\s*Yap\b", "杨洋", "秧秧"),
    (r"\bYang\s*yang\b|\bYap\s*Yap\b", "杨莹", "秧秧"),
    (r"\bYang\s*yang\b|\bYap\s*Yap\b", "杨宇", "秧秧"),
    # 穗穗(Suisui)：ASR 把姓名拆成 "Sui Sui"，谷翻留拉丁或音译成「隋岁/隋河」。
    (r"\bSui\s*Sui\b", "隋岁", "穗穗"),
    (r"\bSui\s*Sui\b", "隋河", "穗穗"),
    # 洛瑟菈(Lucilla) 被学习库规则并成「陆·赫斯·伊拉」（两个角色混为一人），按 Lucilla 锚定回滚。
    (r"\bLuc\s*illa\b|\bLucilla\b", "陆·赫斯·伊拉", "洛瑟菈"),
    # 华胥院 被「学院→星炬学院」二次替换后的形态回滚。
    (r"\bHu\s*ash\s*u\b", "胡阿什星炬学院", "华胥院"),
    # --- 2026-10-30 r2 官方名复核（3.5 玄方篇）---
    # 天工部(Sky works，玄方地界官方区域名)：谷翻按 works 直译成「天工坊」。
    (r"\bSky\s*works?\b|\bSkyworks\b", "天工坊", "天工部"),
    # 苇原(Ashinohara)：ASR 把地名拆成 "Ash in ohara"，谷翻译成「阿什」。
    (r"\bAsh\s*in\s*ohara\b|\bAshinohara\b", "阿什", "苇原"),
    # 穗波市(Honami/Hanami City)：谷翻音译成「韩美市」。
    (r"\bHan\s*ami\b|\bHon\s*ami\b", "韩美市", "穗波市"),
    # 方擎西峰 / 玄幽东岳（玄方地界官方区域名）：谷翻按 Fang/Xuan Peaks 直译。
    (r"\bWestern\s+Fang\s+Peaks?\b", "西玄峰", "方壶西峰"),  # 2026-11-10 BWIKI 核实：官方写法=方壶西峰，旧 target「方擎西峰」为误写
    (r"\bEastern\s+(?:Xuan|Sh\s*uan)\s+Peaks?\b", "东玄峰", "玄幽东岳"),
    # 灼樱巫女(Miko of Flaming Sakura)：官方中文为「灼樱」，谷翻作「绯樱」。
    (r"\bMiko\s+of\s+Fl\s*aming\s+Sakura\b", "绯樱巫女", "灼樱巫女"),
    # Wardens（玄方巡守）被跨片规则改写成「守岸人」（Shorekeeper），按英文锚定回滚。
    (r"\bWardens?\b", "守岸人", "巡守"),
    # Shang fang Hold 实为玄方城（片中只有这一座 Hold）。
    (r"\bShang\s*fang\s+Hold\b", "上方堡", "玄方城"),
    # Scar（伤痕，残星会成员）被音译成「疤痕」。
    (r"\bScar\b", "疤痕", "伤痕"),
    # --- 2026-11-02 鸣潮 Reaction Part 1 二次校准：以下错形全是**通用中文词**，
    #     按硬契约第 4 条禁入裸键表，只能靠参考行英文佐证。追加在本表**末尾**，
    #     使其天然晚于被锚定的肇事条目（CONTEXT_MAP 按列表顺序执行）：
    #     :1601 (\bYang\b,杨,秧秧)、:1269-1270 puppet→机傀、:2111-2113 overseers、实体投影 ctx。
    (r"\bcharacters?\b", "字符", "角色"),          # #3046/#3167/#3394 等 7 处 character→字符
    (r"\bJing\s?Jo\w*\b|\bJingjo\b|\bJingo\b|\bJinzhou\b", "靖国神社", "今州"),
    # ↑ 谷翻把 ASR 的 Jingjo 整词译成「靖国神社」（#420 实测），属**严重错译**，必须锚定回正。
    (r"\bJing\s?Jo\w*\b|\bJingjo\b|\bJingo\b", "Jinzhou", "今州"),
    # ↑ 兜旧「拉丁→拉丁」归一化留下的 Jinzhou 残留（#881）。:75 已改目标，此处再兜一层。
    (r"\bSaving\s+Light\b", "节能灯", "《Saving Light》"),
    # ↑ 谷翻把 saving light 译成「节能灯」（#280 实测）。官方题名保留英文：先约电台EP0「Saving Light」。
    (r"\bacolytes?\b|\bPhoebe\b", "侍僧", "见习教士"),
    # ↑ 菲比官方身份＝见习教士（隐海修会），非「侍僧」（#1763/#1832 实测）。
    (r"\bImperator\b", "大君", "英白拉多"),
    # ↑ Sentinel Imperator＝岁主英白拉多（黎那汐塔的岁主，名词注释）；「大君」是日译腔（#1739）。
    (r"\bChana\b|\bCiaccona\b", "查娜", "夏空"),
    # ↑ 夏空官方 EP「我们依旧歌唱」，#2284 实测「查娜」。⚠ 不做裸键：查娜是通用音译名。
    (r"\b(?:Kartia|Kartilla|Karthia|Cartethyia)\b", "卡地亚", "卡提希娅"),
    # ↑ 卡地亚是 Cartier 官方中文（奢侈品牌），禁裸键；须参考行 Kartia/Kartilla 佐证（#2746）。
    #   ⚠ 2026-11-02 纠错：上一版写成 \bKartil?ia\b，展开要求 Karti+ia 共 7 字符，
    #   而实际 Kartia 只有 6 字符，**永远匹配不上**（候选基线实测「卡地亚」残留）。
    #   枚举 ASR 形，别用可选字符凑拼写。
    (r"\bLing\s*Yang\b|\bLingyang\b", "凌秧秧", "凌阳"),
    # ↑ 兜 :1601 裸键 Yang→秧秧 把「凌杨」咬成「凌秧秧」（#616 实测）。wrong 必须写**被咬坏之后**的形态。
    (r"\boverseers?\b", "大监", "会监"),
    # ↑ Lord Overseer＝会监（残星会职位）；「大监」是本片二次校准中发现的新错形（#1072）。
    (r"\bpuppeteer", "机傀", "傀儡"),
    # ↑ 兜 :1269-1270 把 puppeteering 译成崩铁词「机傀」的产出。实测本片是「机傀动画」(#1090)
    #   与「机傀戏」(#2080)，只收「机傀师」覆盖不到，故 wrong 用 机傀、由参考行 \bpuppeteer 限定。
    #   真正的鸣潮「机傀」（参考行 Auto Puppet / puppet）不落在此锚下，不会被误改；
    #   也因此**不建裸键** 机傀→傀儡（会咬 :645 汽车傀儡→机傀 / :722 自动木偶→机傀 的产出）。
    # --- 2026-11-04 SenWarchief《Wuthering Waves Reaction! Character and Area Songs,
    #     ver 3.5 - 3.7》沉淀（574 cue，英语原声 + 谷翻，bi）。官方依据与逐条考证见片源目录
    #     `-校准说明.md`；曲名一律官方中文 + 书名号，不并注英文。
    # 曲名错译/ASR 误听 → 官方中文曲名。**全部走参考行英文锚，禁裸键**：
    #   清晰度/面纱/野火/等值/进入 都是通用中文词，裸键必误伤（硬契约第 4 条）。
    (r"\bClarity of the\s+Transcendent\b", "超越的清晰度", "《清仙谣》"),
    #   ↑ 玄方篇 OST Vol.2《云影仙迹》清宵角色主题曲，官方中文《清仙谣》(Apple Music 国区 6803333112)。
    (r"\bDreaming\s+(?:Vale|Veil|Vail)\b", "梦中的面纱", "《溪山入梦》"),
    #   ↑ 玄方篇 OST Vol.3《朝月听尘》梦州区域曲《溪山入梦》；ASR 把 Vale 听成 Veil，
    #   谷翻遂译作「面纱」。⚠ 与 :674-676 的官方名「务安面纱」(Muan Veil) 无关，只在本锚下生效。
    #   ⚠ 2026-11-04 首版误写 `Va(?:il|le)`，展开只认 Vail/Vale、**认不到实际 ASR 形 Veil**
    #   （真片回归实测 #388 零命中才发现）。枚举完整词形，别用可选字符凑拼写（同 :2213 Kartia 判例）。
    (r"\bInto the\s*wild\s*fire\b|\bInto\s+Xuanfang\b", "进入野火", "《踏玄方》"),
    #   ↑ 玄方篇 OST Vol.1《万声弥新》器乐曲《踏玄方》；ASR 把 Xuanfang 听成 "wild fire"。
    (r"\bIsodes\b|\bEisodus\b", "等值", "《定玄》"),
    #   ↑ 3.5 玄方区域主题曲《定玄》(Eisodus，黄霄雲)；ASR 听成 Isodes，谷翻译作「等值」。
    (r"\bOld\s+Shin\s+and\s+Moon\b|\bOde\s+to\s+Hsin\b", "老心月狐和月亮", "《心月辞》"),
    (r"\bOld\s+Shin\s+and\s+Moon\b|\bOde\s+to\s+Hsin\b", "老辛和月亮", "《心月辞》"),
    #   ↑ 3.7 心 EP 官方中文《心月辞》；ASR 把 Hsin 听成 Shin，:1553 辛系锚先咬成「心月狐」
    #   ⇒ 两条 wrong 分别覆盖咬前/咬后形态，**长形态（咬后）那条在前**（CONTEXT_MAP 按列表序执行）。
    #   ⚠ 同片 #436 参考行只有单词 "Shin."：3.7 语境指新任岁主「心」、历史片（2026-10-05/10-10）
    #   指「心月狐」，单行无法判别 ⇒ **不做表规则也不加 EXCLUDE 负例**（负例会把历史片一起翻掉），
    #   只逐 cue 覆盖。删 :1553/:1554 同理禁止。
    # 歌词锚：《定玄》**有官方英文词**（Forts / Oil Li，同专辑第 2 曲 Eisodus），第一行
    #   "Time fleets over the fort like a kite in the wind" ⇔ 官方中文「鸢鸟起 轻点流云 画一城涟漪」。
    #   ASR 听成 "like a guiding wind"，谷翻出「像一股引导风一样越过堡垒」。
    #   ⚠ 第二段同位置是「细雨穿檐 拢一池涟漪」（池非城）；本锚只收实测错形串，不做泛化。
    (r"\bguiding\s+wind\b|\bkite\s+in\s+the\s+wind\b", "像一股引导风一样越过堡垒",
     "鸢鸟起 轻点流云 画一城涟漪"),
    # 角色名 ASR 形 → 官方中文（同样必须英文锚佐证）。
    (r"\bQing\s+Shao\b", "青少", "清宵"),                # 谷翻把 Qing Shao 缩成「青少」
    (r"\bYa\s+Ya\b", "丫丫", "秧秧"),                    # 秧秧(Yangyang) 的昵称式 ASR 形
    (r"\bYoung\s*young\b|\bYang\s*yang\b|\bYap\s*Yap\b", "年轻年轻", "秧秧"),
    #   ↑ 谷翻把 "Young young"（Yangyang 的 ASR 形）直译成「年轻年轻」。wrong 与
    #   :2161-2165 的 杨阳/杨洋/杨莹/杨宇 各族不同，不互咬。
    (r"\bSuisei\b", "水成", "穗穗"),                     # 穗穗(Suisui) 另一 ASR 形；负例见 EXCLUDE_CONTEXT
    (r"\bShiori\b", "沙织", "诗织·诺薇拉"),
    #   ↑ hololive English -Advent- 的 Shiori Novella，官方中文「诗织·诺薇拉」。
    #   判据：全 Hololive Production 罗马字为 Shiori 的**仅此一人**（JP 侧只有紫咲シオン、
    #   獅白ぼたん=Shion，无 しおり；holostars 村野しとり 罗马字是 Shitori 且本身男性，
    #   "gender bend" 讲不通）。其招牌造型即黑白不对称发，与鸣潮景燃同构。
    #   ⚠ 本片谷翻根本没译该词（中文行是拉丁 "Shiori"），本锚只兜「被音译成沙织」的情形。
    # 游戏名与通用术语。
    (r"\bWoWa\b|\bWoW\b", "呃哇", "鸣潮"),
    #   ↑ 谷翻把 "WoWa" 整词漏译成「呃哇」；裸键 WoWa→鸣潮 管保留拉丁的情形，本锚管漏译形态。
    (r"\bgacha\b", "扭蛋", "抽卡"),
    #   ↑ "gacha game" 谷翻作「扭蛋游戏」；中文社区与官方口径通行「抽卡」。⚠ 不建裸键
    #   扭蛋→抽卡（扭蛋是通用词，实体周边语境会误伤）。
    (r"\bHonkai\s+Impact\b", "崩坏冲击", "崩坏"),
    #   ↑ "Honkai Impact" 谷翻直译「崩坏冲击」，官方中文系列名无「冲击」二字。
    # --- 2026-11-06 All 60 Gacha Animations REACTION（英语原声 + 微软翻译）：全部走参考行锚定 ---
    #   共同点：错形本身是**常用中文词**，裸键必伤他片，所以只让参考行的拉丁名作证据。
    (r"\bB?ankai\b", "一家进化银行", "进化的卍解"),
    (r"\bB?ankai\b", "银行", "卍解"),
    #   ↑ 《BLEACH》Bankai 官方中文=卍解；微软翻译按 bank 译成「银行」。本片 #436 实测
    #   「鲁奇亚的银行，一家进化银行」。**长形态那条必须在前**：CONTEXT_MAP 按列表序执行，
    #   若先跑短锚会留下「一家进化卍解」的畸形。
    (r"\bRukia\b", "鲁奇亚", "露琪亚"),
    #   ↑ Rukia 官方中文=露琪亚。本片 #306 已是正形、#436 却作「鲁奇亚」⇒ 同专名异形，收锚。
    (r"\bHuaxi\b|\bHuaxu\b", "华溪星炬学院", "华胥"),
    (r"\bHuaxi\b|\bHuaxu\b", "华溪", "华胥"),
    #   ↑ 官方机构=华胥研究院（bilingual.py:1114 已收 "Huaxu Academy"；entities_part2.py 的
    #   「华胥研究院安全科」、维基「鸣潮角色列表」同证；白芷官方初奏逐字「华胥研究员，白芷。」）。
    #   ASR 把 Huaxu 听成 Huaxi ⇒ 同一机构。
    #   ⚠ 第一条 wrong 是**通用锚 \bAcademy\b 的产物形**：它先把「华溪学院」咬成「华溪星炬学院」，
    #   故必须按「咬后形态」再兜一次（咬后长形在前）；根因负例见 EXCLUDE_CONTEXT 的「学院」条。
    (r"\bDan\s+Heung\b|\bDan\s+Hyun\b|\bDan\s+Heng\b", "丹香", "丹恒"),
    (r"\bDan\s+Heung\b|\bDan\s+Hyun\b|\bDan\s+Heng\b", "丹贤", "丹恒"),
    #   ↑ 星穹铁道丹恒；微软翻译把 Dan Heng 落成常用汉字「丹香/丹贤」（本片 #37/#38，主播自己
    #   就在纠正读音 'Not Dan Hyun, sorry'）。丹香/丹贤是中文好词，禁裸键。
    # --- 2026-11-06 奏咲ルリ《鸣潮 3.2 PV 鉴赏会》（日语原声，3164 cue）二校回灌 ---
    #   シリカ（ASR 把 西格莉卡 シグリカ 缩读成 シリカ，谷翻按矿物义直译「硅藻土」，#309）。
    #   ⚠ 「硅藻土」是正常矿物词，**禁裸键**（硬契约第 4 条）；只走参考行锚定，并配
    #   EXCLUDE_CONTEXT 负例（同 2026-10-30「经纪人/雾霾只走锚定」判例）。
    (r"シリカ|シグリカ", "硅藻土", "西格莉卡"),
    # --- 2026-11-07 Velo City Extra《THESE ARE LIKE MOVIES! First Time Reacting to Wuthering Waves Cinematics》二校回灌 ---
    #   本片参考行是**日语**（英语原声→日语机翻→谷翻中文）：2026-09-08 NIKKE 三短片片沉淀的英文锚
    #   （\bWuthering\b→呼啸山庄、\bJinshi\b、\bJinzhou\b）在本片一个字都咬不到，术语基线只命中 3 处。
    #   故给同一批专名补**日语锚定**同义条；既有英文锚不动（两种片源各走各的）。
    #   ⚠ 错形侧是地名/神话人物/常见人名/普通短语（济阳=山东地名、金赛⊂韩国演员「金赛纶」、嫦娥=神话人物、
    #   琪琪=常见人名、老板歌=普通短语、谐振器=声学术语）⇒ 按硬契约第 4 条一律**禁裸键**，只走参考行锚定。
    (r"嵐が丘", "呼啸山庄", "鸣潮"),                       # Wuthering Waves 被谷翻直译成小说名（#64）
    (r"ジヤン", "济阳", "忌炎"),                           # Jiyan 的日语 ASR（#92）
    (r"ジン・セイ|ジンセイ", "金赛", "今汐"),              # Jinhsi 日语 ASR（#107/#125）
    (r"ジン・セイ|ジンセイ", "Jin Sei ", "今汐"),          # 同一 ASR 在中文行里残留的拉丁形（#125，带尾空格防留空）
    (r"ジン・セイ|ジンセイ", "Jin Sei", "今汐"),           # 兜底：行尾/无空格形态
    (r"ジンジョ", "金乔", "今汐"),                         # 同一 ASR 的另一种听法（#113/#116）
    (r"自信を持って前進", "嫦娥", "长离"),                # 1.1 篇 ASR 把 Changli 听成嫦娥（#151）
    (r"自信を持って前進", "改变", "长离"),                # 同句谷翻把专名当动词译成「改变」（#151 实际源形）
    (r"チーチー", "琪琪", "七七"),                         # 原神七七串场（#169）
    (r"ボス曲", "老板歌", "Boss曲"),                       # boss theme 直译（#47）
    (r"共鳴器", "谐振器", "共鸣者"),                       # Resonator（#19）
    (r"\dつ星選手|プレーヤー", "球员", "角色"),            # 「五星选手/プレーヤー」直译（#91/#108）
    (r"予告編", "拖车", "宣传片"),                         # trailer（英文锚 \btrailer\b 的日语等价条）
    (r"夜明けがやってきた", "黎明已经到来", "《天明》"),   # Dawn Arrives 官方中文《天明》（#182）
    # --- 2026-11-07 鸣潮 3.8 开发者直播 reaction 二校（MarcoMeatball，英语原声，2699 cue）---
    # Somnoire 家族：谷翻把 Somoir/Sonoir/Sonor/Sonora/sonar/somir/sumoir 分别译成
    #   索莫尔/索米尔/索诺拉/声纳/相扑(者)。官中=心之集域（2026-10-30 已裁定）。
    #   错形本身是常用词（声纳/相扑）或墨西哥州名（索诺拉）⇒ 禁裸键，只走英文锚定。
    (r"(?i)\b(?:Somnoire|Somnoir|Somnir|Somoir|Sonoir|Sonor|Sonora|sonar|somir|sumoir)\b",
     "索诺拉", "心之集域"),
    (r"(?i)\b(?:Somnoire|Somnoir|Somnir|Somoir|Sonoir|Sonor|Sonora|sonar|somir|sumoir)\b",
     "声纳", "心之集域"),
    (r"(?i)\b(?:Somnoire|Somnoir|Somnir|Somoir|Sonoir|Sonor|Sonora|sonar|somir|sumoir)\b",
     "相扑者", "心之集域"),
    (r"(?i)\b(?:Somnoire|Somnoir|Somnir|Somoir|Sonoir|Sonor|Sonora|sonar|somir|sumoir)\b",
     "相扑", "心之集域"),
    # gotcha/gacha 抽卡语境：本片谷翻把 gotcha 译成 陷阱/陷阱游戏/陷阱玩家/陷阱空间。
    #   CONTEXT_MAP 按列表顺序执行 ⇒ 长形在前、裸「陷阱」最后。
    (r"\bgot?cha\b|\bgacha\b", "陷阱游戏", "抽卡游戏"),
    (r"\bgot?cha\b|\bgacha\b", "陷阱玩家", "抽卡玩家"),
    (r"\bgot?cha\b|\bgacha\b", "陷阱空间", "抽卡游戏圈"),
    (r"\bgot?cha\b|\bgacha\b", "陷阱", "抽卡"),
    # 2026-11-08：鸣潮 bi 语境把已统一的「抽卡」再收敛到官中「唤取」。
    # 必须同参考行另见明确鸣潮锚，通用 gacha games 保持「抽卡」（Lily 3.8 片 cue92 人工处理）。
    (r"(?=.*\b(?:gacha|convene)\b)(?=.*\b(?:wuthering|wuwa|resonator|rover|lily|hiyuki|phoebe|cartethyia|shorekeeper|solaris|jinzhou|huanglong)\b)",
     "抽卡", "唤取"),
    # Star Rail（星穹铁道）：裸「星轨」不入表——本片 #617 的 star path 是抽卡赠礼，不是 Star Rail。
    (r"\bStar\s*Rail\b|\bStarrail\b", "星轨铁路", "星穹铁道"),
    (r"\bStar\s*Rail\b|\bStarrail\b", "星轨", "星穹铁道"),
    # Tinari=提纳里（原神）；「田霏宇」是 UCCA 馆长 Philip Tinari 的中文名（机翻知识库撞车）
    (r"\bTinari\b", "田霏宇", "提纳里"),
    # Raiden Shogun=雷电将军（ASR 作 Ryden Shogun，谷翻成「莱登将军」）
    (r"\b(?:Raiden|Ryden)\s+Shogun\b", "莱登将军", "雷电将军"),
    # Inazuma=稻妻（谷翻按本意译成「闪电」）
    (r"\bInazuma\b", "闪电", "稻妻"),
    # Huanglong=瑝珑（ASR 作 Han Long/Juan Long/Hongong/Hanong）
    (r"\bHuanglong\b|\bHan\s*Long\b|\bJuan\s*Long\b|\bHongong\b|\bHanong\b", "韩龙", "瑝珑"),
    (r"\bHuanglong\b|\bHan\s*Long\b|\bJuan\s*Long\b|\bHongong\b|\bHanong\b", "弘工", "瑝珑"),
    (r"\bHuanglong\b|\bHan\s*Long\b|\bJuan\s*Long\b|\bHongong\b|\bHanong\b", "哈农", "瑝珑"),
    # Spectro=衍射（元素名；「光谱」是通用物理词）
    (r"\bSpectro\b", "光谱", "衍射"),
    # Resonance=共鸣（鸣潮核心术语；「共振」是通用物理词）
    (r"\bresonance\b", "共振能力", "共鸣能力"),
    # Metaphor: ReFantazio=《暗喻幻想》；「隐喻」是通用修辞词。
    # 2026-11-08 收紧：必须同参考行另见 ReFantazio/Atlus，普通 metaphor 不再误改（3.8 Lily 片 cue45 实证）。
    (r"(?=.*\bMetaphor\b)(?=.*\b(?:Re\s*Fantazio|Atlus)\b)", "隐喻", "《暗喻幻想》"),
    # 第二索拉学院：3.8 活动「Second Solaris Academy」官中公告统一作「第二索拉学院」。
    (r"\bSecond\s+Solaris\s+Academy\b|\bSecond\s+Coming\s+of\s+Solaris\b", "第二索拉里斯学院", "第二索拉学院"),
    # 通用 \bAcademy\b→星炬学院 会把上一行的产物二次咬成「第二索拉星炬学院」，此处收口。
    (r"\bSecond\s+Solaris\s+Academy\b|\bSecond\s+Coming\s+of\s+Solaris\b", "第二索拉星炬学院", "第二索拉学院"),
    # Paimon=派蒙（ASR 作 Palon）；「帕隆」同时是藏语地名「帕隆藏布」用字
    (r"\bPalon\b|\bPaimon\b", "帕隆", "派蒙"),
    # tribalism=阵营对立（「部落主义」是人类学术语）
    (r"\btribalism\b", "部落主义", "阵营对立"),
    # --- 2026-11-07 鸣潮 OST 6 reaction（Yuuma，英语原声 + 谷翻，331 cue）二校回灌 ---
    #   曲名一律官方中文 + 书名号（官方名见 music.py `_MUSIC_WW` / `_MUSIC_WW_BGM`）。
    #   错形侧不是通用中文词就是拉丁残留 ⇒ 按硬契约第 4 条禁裸键，只走参考行英文锚定。
    #   依据：萌娘百科《Saving Light（致新世界）》+ QQ音乐/酷我「致新世界 Saving Light」；
    #         《鸣潮》黎那汐塔篇 OST Vol.7《无名长诗》（Apple Music 国区 1824610259）；
    #         萌娘百科译名对照表 先约电台=Pioneer Podcast（日 先駆ラジオ / 韩 선약 방송국）。
    # Saving Light＝《致新世界》：谷翻四态 节能灯/节能/节约光线/拯救光明，拉丁原形亦未译。
    #   长形在前（CONTEXT_MAP 按列表序执行）：节能灯→节约光线→拯救光明→节能→《》→拉丁。
    #   ⚠ 带书名号的形态必须排在裸形之前：裸形会替换书名号**内部**，产出《《…》》双括号
    #   （本片 #136「《拯救光明》」实测）。四态各配一条括号形。
    (r"\bSaving\s*Light\b", "《节能灯》", "《致新世界》"),
    (r"\bSaving\s*Light\b", "《节约光线》", "《致新世界》"),
    (r"\bSaving\s*Light\b", "《拯救光明》", "《致新世界》"),
    (r"\bSaving\s*Light\b", "《节能》", "《致新世界》"),
    (r"\bSaving\s*Light\b", "《Saving Light》", "《致新世界》"),
    (r"\bSaving\s*Light\b", "节能灯", "《致新世界》"),
    (r"\bSaving\s*Light\b", "节约光线", "《致新世界》"),
    (r"\bSaving\s*Light\b", "拯救光明", "《致新世界》"),
    (r"\bSaving\s*Light\b", "节能", "《致新世界》"),
    (r"\bSaving\s*Light\b", "Saving Light", "《致新世界》"),
    # Dancing Through Fantasies＝《悠忽舞于梦中》（罗蕾莱飞行挑战 BGM，人声曲）。
    (r"\bDancing\s+Through\s+Fantas(?:y|ies)\b", "《Dancing Through Fantasies》",
     "《悠忽舞于梦中》"),
    (r"\bDancing\s+Through\s+Fantas(?:y|ies)\b", "舞蹈穿越幻想", "《悠忽舞于梦中》"),
    (r"\bDancing\s+Through\s+Fantas(?:y|ies)\b", "舞动着幻想", "《悠忽舞于梦中》"),
    (r"\bDancing\s+Through\s+Fantas(?:y|ies)\b", "《舞动幻想》", "《悠忽舞于梦中》"),
    (r"\bDancing\s+Through\s+Fantas(?:y|ies)\b", "舞动幻想", "《悠忽舞于梦中》"),
    # Chains of Oath, Echoes of Promise＝《誓约之枷，应许之愿》（#242 标题、#279 歌词碎片）。
    #   ⚠ 「回声→声骸」是更早的 BILINGUAL 键（Echo=声骸，鸣潮核心术语），
    #   故 承诺的声骸/《承诺的声骸》 必须同时登记，否则本锚在基线跑完后已不命中（#242 实测）。
    (r"\bEchoes\s+of\s+Promise\b", "《承诺的声骸》", "《誓约之枷，应许之愿》"),
    (r"\bEchoes\s+of\s+Promise\b", "《承诺的回声》", "《誓约之枷，应许之愿》"),
    (r"\bEchoes\s+of\s+Promise\b", "承诺的声骸", "《誓约之枷，应许之愿》"),
    (r"\bEchoes\s+of\s+Promise\b", "承诺的回声", "《誓约之枷，应许之愿》"),
    (r"\bchains?\s+of\s+oaths?\b", "誓言的链条", "誓约之枷"),
    # Oath to the Nameless Martyr＝《致以无名的抗争者》（《无名长诗》曲1，人声）。
    (r"\bOath\s+to\s+the\s+Nameless\s+Martyr\b", "无名烈士的誓言", "《致以无名的抗争者》"),
    # A Clash of Water and Fire＝《泪焰终响》（《无名长诗》曲16，器乐）。
    #   #92 参考行只剩 "of Water and Fire."（前半被切到上一条 cue），故补行尾锚形态。
    (r"\bClash\s+of\s+Water\s+and\s+Fire\b|\bof\s+Water\s+and\s+Fire\.?\s*$",
     "水与火", "《泪焰终响》"),
    # When the Bird Glides Across the Sky＝《当飞鸟划过天空》。
    (r"\bWhen\s+the\s+Bird\s+Glides?\b", "《当鸟儿滑翔时》", "《当飞鸟划过天空》"),
    (r"\bWhen\s+the\s+Bird\s+Glides?\b", "当鸟儿滑过天空时", "《当飞鸟划过天空》"),
    # 先约电台＝Pioneer Podcast（游戏内的电台/厂牌频道，非「先锋播客」）。
    (r"\bPioneer\s+Podcast\b", "先锋播客", "先约电台"),
    # WoWa/WuWa/Woobles＝鸣潮：谷翻漏译成「哇哇」、音译成「伍布尔斯」，或保留拉丁原形。
    (r"\bWoWa\b|\bWuWa\b|\bWoobles\b", "哇哇", "鸣潮"),
    (r"\bWoobles\b", "伍布尔斯", "鸣潮"),
    (r"\bWoWa\b|\bWuWa\b", "WoWa", "鸣潮"),
    # 《直到下次再见》＝Dasvidaniya（达妮娅 EP3.3，官方 credit Cxssidy 演唱 / Crywolf 制作）；
    #   ASR「Denia, Madania」实为 Denia, Dasvidaniya（NGA 实证俄语「再见」谐音彩蛋）。
    (r"\bMadania\b|\bDasvidaniya\b", "Madania", "《直到下次再见》"),
    (r"\bDenia\b", "Denia", "达妮娅"),
    # Ru＝鸣潮（上下文推断，中高置信）：#65 "the vocalists they have for Ru"、
    #   #91 "Ru song along with Denia…" 均合 WuWa 语义；同片他处 ASR 作 WoWa/Woobles。
    #   ⚠ 只收这两条限定锚，不建裸 \bRu\b（Ru 亦可能是人名缩写或他作专名）。
    (r"\bRu\s+song\b", "Ru Song", "鸣潮歌曲"),
    (r"\bfor\s+Ru\b", "Ru 的", "鸣潮的"),
    (r"\bfor\s+Ru\b|\bRu\s+song\b|\bRu\s+content\b", "Ru", "鸣潮"),
    # #91 句末 "and Clash" 的拉丁残留（同句 Madania 之后）。
    (r"\band\s+Clash\s*$", "Clash", "《泪焰终响》"),
    # 「doesn't have many views」＝没多少播放量：本片 #137 被旧键译成「没有太多的次」。
    (r"\bmany\s+views\b|\bthe\s+views\b", "太多的次", "太多播放量"),
    # --- 2026-11-07 《ソラリス・スターリーステージ Season 2》日语 reaction 片二校沉淀 ---
    #   鷺原鈴音 476 cue，日语原声 + 谷翻中文（bi）。本片实测错形，全部参考行锚定、禁裸键：
    #   菜鸟君（名長君=鳴潮 ASR）、阿尔托/阿尔（アルト=秋水）、拉海莱（ラハイロイ）、
    #   里纳西（リナシ）、Cartesia（カルテジア）、开始短/开始上幼儿园（スタートーチ幼稚園）。
    #   千咲的「千咲n」残留由 Entity('千咲') 补 "Chi-san" 变体修复（长键先行）。
    (r"名長君|鳴潮", "菜鸟君", "鸣潮"),
    (r"スタートーチ幼稚園|スタートちよち", "开始短", "星炬幼儿园"),
    (r"スタートーチ幼稚園|スタート幼稚園", "开始上幼儿园", "星炬幼儿园"),
    (r"アルト|アールト", "阿尔托", "秋水"),
    (r"アル(?:のキャラ|は|が)", "阿尔", "秋水"),
    (r"ラハイロイ?", "拉海莱", "拉海洛"),
    (r"リナシ", "里纳西", "黎那汐塔"),
    (r"カルテジア", "Cartesia", "卡提希娅"),

    # --- 2026-11-09 WuWa 3.8 Looks REACTION 片三轮回灌（二次校准以官方中文为依据）---
    # 本片交付 5 条补丁中 4 条（#311/#320/#385/#511）是词表未覆盖的漏校根因，逐条沉淀；
    # 错形全部取自片内实证、锚取英文参考行，防跨片误伤（无证据不改、禁裸键）。
    (r"\bChang\s*Li\b", "张莉", "长离"),
    #   ↑ #385「我的天啊，张莉看起来太性感了」EN "Chang Li looks hot as fuck"——
    #     长离=鸣潮共鸣者（wiki.biligame.com/wutheringwaves 共鸣者/长离，今州令尹参事/瑝珑）。
    #     原表仅 \bChang\s+Lee\b→「张李」（见 2239 区），漏了 Li 形与片内错形「张莉」。
    #     歧义由中文错形限定（真名张莉的拼音是 Zhang Li，英文不会写 Chang Li）。
    #     ⚠ \s* 而非 \s+：_ref_for_match 会把 "Chang Li" 重组为 "ChangLi"（known 词表
    #       命中 changli，2026-11-09 实测 ref_m='…ChangLi looks hot.'），带 \s+ 必失配。
    (r"\bSuise\s*i\b", "Suise i", "穗穗"),
    #   ↑ #311「一个 Suise i」拉丁 ASR 碎片残留（gloss §2 拉丁须译出）；穗穗=3.5 共鸣者
    #     （Suisui，L534 区沉淀），与 L2458 wrong="水成" 族同锚互补（该条只咬"水成"形）。
    #     同复刻列举内有官方角色秧秧（#313 Yang Yang rerun），鸣潮语境排除 hololive 星街彗星；
    #     EXCLUDE 尾部同日段带同组负锚（EXCLUDE 按 wrong 键匹配，新错形必须自带）。
    (r"\bCamellia\b", "Camellia", "椿"),
    #   ↑ #320「您可以选择Camellia」EN "You can choose from Camellia"——椿=Camellia
    #     （L864 "Cam ellia"→椿、L2321 wrong="山椿"→椿、11-09 整句键三处既有沉淀；
    #     B站 wiki 搜索 Camellia 命中「角色/椿」）。本条覆盖**裸拉丁残留**形；
    #     曲名《Camellia》由 EXCLUDE 尾部负锚保护（L2320 曲名长形先行条不动）。
    (r"\bEcho(?:es)?\b|\bsound\s+skeleton\b", "声音骨架", "声骸"),
    #   ↑ #511（B 类两行不同 cue，本轮用户口径放开）第 1 行谷翻「声音骨架」直译，
    #     同 cue 第 2 行即官方「声骸」（内证）；Echo=声骸 bilingual.py:642 沉淀 + 词表
    #     38 处声骸组合词 + FORBIDDEN 已注册「声音骨架」错形。锚含 sound skeleton
    #     （"声音骨架"的英文字面源形）双保险。
]


# --- 2026-09-08 负向排除上下文（高歧义词防护，仅双语模式）---
# BILINGUAL_TERMS/CONTEXT_MAP 中个别词在特定口语/非游戏语境会误伤。例：
#   帐篷=十连 是抽卡术语，但语言讨论语境 tent 是 text 的 ASR 误听；
#   简而言之=这个短片里 是机翻错形，但参考行 in short 本就是"简而言之"。
# 机制：术语被替换后，若参考行(英文)命中下列任一排除正则，回滚该替换并从命中统计移除。
# 结构：{wrong: (right, (排除正则...))}，right 用于回滚（须与所在术语表的 value 一致）。
# 比无条件替换更精准，不依赖人工负例注释。新增歧义词时按此结构追加。
EXCLUDE_CONTEXT = {
    # --- 2026-11-08 Jadealy 3.8 片深度二校：由纪→绯雪 正向归正（一校误判已纠正）---
    #   一校把「由纪→绯雪」判为跨片误伤，按参考行含 Yuki 就回滚；实测本片 Yuki/Y uki/Fy uka
    #   均指官中「绯雪」（萌娘百科译名对照表 Hiyuki=绯雪；官微「绯雪特别定制『月沉霜』」；
    #   T1 #363「飞雪的活动换取/将开启」与 #364「又是由纪」呼应；#663-723 绯雪服饰展示段）。
    #   现改为「参考行**不含** Yuki 族锚点才回滚」：本片 Yuki 语境让学习库 confirmed 裸键
    #   bi|由纪→绯雪 正常生效；其它片非 Yuki 语境的真名「由纪」仍原样保留，零跨片误伤。
    #   ⚠ 表达「整行不含 X」必须用 ^ 行首否定环视；re.search 下 (?!.*X) 会从 X 之后的位置误匹配。
    "由纪": ("绯雪", (r"^(?!.*(?:\bYuki\b|\bY\s*u\s*ki\b|\bFy\s*u\s*ka\b|\bHi\s?y?uki\b))",)),
    #   bi|快捷方式→快捷径 把正常词改造成生造词，按 shortcuts / exposition 参考行回滚。
    "快捷方式": ("快捷径", (r"\bshortcuts?\b", r"\bexposition\b")),
    #   2026-11-09 战双「A Comet's Afterglow」二校：#1232 参考行 'Dark skin'（指角色肤色）
    #   被 PGR_EN_TERMS 的裸键「皮肤→涂装」改成「黑涂装」，语义全错。肤色语境按参考行回滚。
    #   ⚠ 只处理「肤色」这一路。#760「These are coatings, I guess, like skins」里的「皮肤」
    #     是对英文 skins 的**注释词**，看似可用 `coatings…like skins` 窄正则一并回滚——
    #     **实测不可行**：EXCLUDE 回滚是 `new.replace(right, wrong)` 的**全行替换**
    #     （已知限制，见 _doc.py 2026-11-07 条目），该行回滚前已含两个「涂装」
    #     （原有的 + 本规则产出的），回滚会把两者一并变回「皮肤」，得到
    #     「我想这些是皮肤，就是皮肤」，比不回滚更糟。故只留肤色两条，#760 作为
    #     可接受残差（幂等检查会显示这 1 处），成品侧保留正确写法。
    #   ⚠ 本条同时约束 bi/ak/pgren 三个分支（pgren 的 EXCLUDE 回滚层同日补上）。
    "皮肤": ("涂装", (r"\bdark skin\b", r"\bskin (?:colou?r|tone)\b")),
    #   T1 官中台词 #363 原文即「飞雪的活动换取」：Entity("绯雪") 的 variants 含「飞雪」，
    #   无条件裸键会改坏官方一手台词。按官中参考行回滚，T1 优先；不收紧 Entity 本体，
    #   以免影响其他片里「飞雪」作为 ASR 错形的正常归正。
    "飞雪": ("绯雪", (r"飞雪的活动换取",)),
    # --- 2026-11-08 鸣潮 3.8 Lily 前瞻片：列车乘客≠明日方舟干员「异客」 ---
    # Entity("异客") 的 ctx 只有裸 passenger，且 _CONTEXT_COMPILED 用 re.I；
    # 交通语境回滚为「乘客」，不收紧 Entity 本体，避免影响明日方舟正常 Passenger 命中。
    "乘客": ("异客", (
        r"\b(?:train|trains|railway|rail|station|platform|lounge|coach|bus|flight|airline|airport|subway|metro|taxi|ferry|cruise)\b",
        r"\ball\s+kinds\s+of\s+passengers\b",   # 2026-11-08 Jadealy #190：泛指列车乘客，非干员
        r"\battention\s+passengers?\b",          # 2026-11-09 WuWa3.8 #57 列车广播"Attention passengers, dinner…"，交通语境铁证
    )),
    # --- 2026-10-22 Tenha 鸣潮全 EP reaction 片负例 ---
    # ① \bAngel\b=安吉尔 的负例：歌词里的“天使”。本片 #945 "angel consumes"、
    #    #1854 独立成行 ">> Angel" 都被基线误改成“安吉尔”，歌词语境回滚。
    "天使": ("安吉尔", (r"\bangel consumes\b", r"^\s*>>?\s*angel\s*$",
                        r"\b50\s*/\s*50\s*angel\b",      # 2026-10-22 #66 频道名 50/50 Angel
                        r"\bfallen\s+angel\b",           # 2026-11-09 本片 cue484：fallen angel 普通"堕落天使"，非角色安吉尔
                        r"\bpurgatory\s+angel\b")),      # 2026-11-09 WuWa3.8 #202 "Purgatory angel"普通意象，非角色安吉尔（re.I 使小写 angel 也命中正向锚）
    "帐篷": ("十连", (r"\bwritten tent\b",)),                              # 语言讨论语境 tent=text 误听
    # --- 2026-10-22 Gacha Games Have A Villain Problem 基线误伤 ---
    # #61 Batman: Arkham Knights 的「骑士」被学习库 bi|骑士（confirmed）改成「明日方舟」；
    #   CONTEXT_MAP 的负向后顾管不到学习库注入，这里按参考行回滚。
    "骑士": ("明日方舟", (r"\bArkham Knights?\b",)),
    # #238 conducted an online survey 被 conduct->指挥 改成「指挥了在线调查」；
    #   调查/研究/访谈语境回滚（音乐语境 conduct=指挥 的规则保持不变）。
    "进行": ("指挥", (r"\bconduct(?:s|ed|ing)?\b[^\n]*\b(?:survey|research|study|interview|investigation|experiment)s?\b",)),
    "行为": ("指挥", (r"\bconduct(?:s|ed|ing)?\b[^\n]*\b(?:survey|research|study|interview|investigation|experiment)s?\b",)),
    # --- 2026-09-08 NO ONE CAN CONTROL THEMSELVES! 负例沉淀 ---
    # #1049 "In short, Fong Hold has weathered..."——In short 本就是"简而言之"，
    # 参考行命中 in short 时回滚，防 \bshort\b=短片 规则误伤。
    "简而言之": ("这个短片里", (r"\bin short\b", r"^\s*short\b", r"\bshort,\s*it\b")),
    # #1041/#1078/#1086 main frame=主框架（玄方城主系统/主机），非"画面"；
    # 参考行命中 main frame 时回滚 \bframe\b=画面 规则（防把主机误译成画面）。
    "框架": ("画面", (r"\bmain frame\b",
                    r"\bwelcome\s+to\s+the\s+frame\b")),  # 2026-11-09 本片 cue773：welcome to the frame 普通"框架"
    # --- 2026-09-10 WW 3.1 Story Reaction (Stream #2) 负例 ---
    # \bseal\b=封印 规则的负例：官方名词"雪绒海豹"（Snowplush Seal）语境下回滚，
    # 参考行命中 seal 时先被 CONTEXT 改成"雪绒封印"再整词换回，不影响行内其他"封印"。
    # 2026-10-27 补：复数 seals / 小海豹（seal pup）两种语境，防止 3.1 雪绒海豹被误改。
    "雪绒海豹": ("雪绒封印", (r"\bseals?\b",)),
    "小海豹": ("小封印", (r"\bseal\b",)),
    # --- 2026-10-05《鸣潮》3.7 精校报告沉淀复查所得高歧义负例（用户："以官方中文为准"）---
    # ① \bSushi\b -> 穗穗(Suisui) 的负例：**真食物寿司**。
    #    实测 "I love eating sushi with my friends" + 中文行"我喜欢吃寿司" 被误改成
    #    "穗穗很好吃"。食物语境回滚；穗穗被 ASR 咬成 Sushi 时不含食物词，仍正确归穗穗。
    "寿司": ("穗穗", (
        r"\beat(?:ing|en|s)?\b", r"\bfood\b", r"\bmeal\b", r"\brestaurant\b",
        r"\bmenu\b", r"\bchef\b", r"\bcook(?:ing|ed)?\b", r"\border(?:ed|ing)?\b",
        r"\bdelicious\b", r"\btasty\b", r"\byummy\b", r"\bsnack\b", r"\brecipe\b",
        r"\brice\b", r"\braw fish\b", r"\bsoy sauce\b", r"\bchopsticks\b",
        r"\bbreakfast\b", r"\blunch\b", r"\bdinner\b", r"\bhungry\b", r"\bplate\b",
        # ── 2026-11-07 补：本片 cue60/69/164/166 四处真食物寿司实证漏网（原词表全不命中）──
        #   c60 "while I indulge in my sushi." / c69 "Man, sushi is a great invention." /
        #   c164 "in love with my sushi." / c166 "that was um a bowl of sushi."
        #   全部用**精确短语**，禁 \bmy\b（过宽会把「穗穗被 ASR 咬成 Sushi」的真场景一起回滚）。
        r"\bindulge\b", r"\binvention\b", r"\binvented\b", r"\bbowl\ of\b",
        r"\bin\ love\ with\b", r"\bsushi\s+bar\b", r"\bpick\ up\b",
        r"\bbuy(?:ing)?\b", r"\bself\b", r"\bsome\b", r"\bgot\s+myself\b",
    )),
    # ── 2026-11-07 补：\bLily\b -> 百合->莉莉 的负例 ——「光百合/光之莉莉」是既有正确形，
    #   不得被 \bLily\b 锚二次咬成「光莉莉」。回滚语义见 engine.py 的 EXCLUDE_CONTEXT 段
    #   （替换后若参考行命中负例正则，则 new.replace(right, wrong) 还原）。
    #   ⚠ 2026-11-07 历史片源回归再补：**「百合」在鸣潮 3.8 是版本标题「旧梦凋零的百合」**，
    #   官方英文 "Lily blooming alone in the crossfire of war" / "Lily weaves fleeting
    #   dreamlands"，此时 Lily 指版本名而非共鸣者「莉莉」；另有关卡元素「几个百合踏板」
    #   （few lily pedals）。两者皆非角色 ⇒ 一并列入负例回滚。
    #   实证：3.8 日语片 src_old.srt #478/#479/#527 + 38dev_before_r3.srt #881 共 4 处误伤。
    #   本片 #1244「doesn't affect Lily sales much.」（角色销量）与 #1364「Lily.」（角色）
    #   不命中以下任一负例 ⇒ 仍正确归「莉莉」。
    "百合": ("莉莉", (
        r"\blight\s+[Ll]ily\b",
        r"\blily\s+blooming\b",
        r"\blily\s+weaves\b",
        r"\blily\s+blooms?\b",
        r"\bdreamlands?\b",
        r"\blily\s+pedals?\b",
        # 2026-11-08 Jadealy 3.8：#281 "a field of lily purple cloud." 是官方百合花田意象，
        #   非共鸣者莉莉；命中则回滚（该 cue 终稿与源同形，回滚后幂等 0 改动）。
        #   #39 "Lilies for Lily." 双关句不在此列：全行回滚会吃掉人工精确修好的第二个「莉莉」，
        #   改由 CONTEXT_MAP 的「幂等收口条」处理（见 3.8 Lily 段）。
        r"\bfield\s+of\s+lily\b",
        r"\blily\s+purple\b",
        # 2026-11-09 WuWa3.8 #18：主播念花义 lilies（ASR 碎片 "l ilies"），中文「百合花呀」
        #   是花非角色；s* 同时覆盖碎片与完整 lilies。负前瞻排除 #39 "Lilies for Lily."
        #   双关句——其幂等收口条要求先到「莉莉给莉莉」，全行回滚会打断链（见 CONTEXT_MAP 收口条）。
        r"\bl\s*ilies\b(?!\s+for\s+lily)",
    )),
    # 2026-11-04：①号负例的姊妹条——\bSuisei\b -> 穗穗 的负例：**hololive 星街すいせい**。
    #   Suisei 这个罗马字在 VTuber 语境里首先是星街彗星（Hoshimachi Suisei），
    #   而鸣潮 3.5 角色穗穗的 ASR 形也是 Suisei；靠企划词回滚，鸣潮语境不受影响。
    "水成": ("穗穗", (
        r"\bhoshimachi\b", r"\bsuper\s*nova\b", r"\bcomet\b", r"\basteroid\b",
        r"\bhololive\b", r"\bfubuki\b", r"\bpekora\b", r"\bkyaruko\b",
    )),
    # ② \bSanctum\b -> 万相神宫 的负例：**普通"圣所/密室"**。实测 "a holy sanctum" 被误改。
    #    宗教/建筑通用语境回滚；Manifold Sanctum 与 ASR 错形 sectum 不含这些词，仍正确归万相神宫。
    "圣所": ("万相神宫", (
        r"\bholy\b", r"\bsacred\b", r"\bshrine\b", r"\btemple\b", r"\bsanctuary\b",
        r"\bchurch\b", r"\bcathedral\b", r"\bmonastery\b", r"\bchapel\b",
        r"\binner sanctum\b", r"\bsanctum sanctorum\b", r"\baltar\b", r"\bdeity\b",
    )),
    # ③ \bParagon\b -> Paragon(称号) 的负例：英语成语 "a paragon of virtue/excellence"
    #    =楷模/典范（普通语义）。实测 "a paragon of virtue" 被误改成称号 Paragon。
    #    注：第 3745/5068 行已注明"'典范'为常用词义错位，不固化"，此处补齐回滚保护。
    "典范": ("Paragon", (r"\bparagon of\b", r"\bparagon\.?\s+(?:of|for)\b",
                        r"\bits\s+paragon\b")),                # 2026-11-09 本片 cue2507：its paragon 普通名词"典范"，非称号
    # ④ \bswimming\b -> 锁暝(Suoming) 的负例：**真·游泳/固定短语与比喻**。
    #    up 主常把 Suoming 玩梗念成 swimming（归锁暝），但 "go swimming"（双关梗，
    #    原文保留游泳二字更忠实原声）与 "swimming in an ocean/sea"（情感比喻）须回滚。
    "游泳": ("锁暝", (
        r"\bgo swimming\b", r"\bgoes swimming\b", r"\bwent swimming\b",
        r"\bswimming in\b", r"\bocean\b", r"\bsea\b", r"\bpool\b", r"\bunderwater\b",
        r"swimming instructor", r"learn(?:ed)? to swim", r"learn how to swim",
    )),
    "游泳教练": ("锁暝州监", (r"swimming instructor",)),
    # ⑤ "守望者" -> 守岸人(Shorekeeper) 的负例：**真·Watcher（守望/观察者）**。
    #    2026-10-10 鸣潮 3.7 reaction 片（I Have Cried Again）：主播把梦州岁主心月狐
    #    称作 the Watcher/Guardian（cue38/45），谷翻作"守望者/监视者"，与黑海岸守岸人
    #    (Shorekeeper) 毫无关系；学习库 bi|守望者->守岸人 候选在此语境误伤。
    #    Shorekeeper 不会被 ASR 咬成 watcher（音不近），命中 \bwatchers?\b 即回滚
    #    （watches 不含 watcher 形，Shorekeeper watches over... 不误回滚，实测）。
    "守望者": ("守岸人", (r"\bwatchers?\b",)),
    # ⑥ "监护人" -> 岁主（Guardian ctx）的负例：**法律/家庭语境的 guardian**。
    #    2026-10-10 实测 "the child's guardian must be present" 被误改成岁主。
    "监护人": ("岁主", (
        r"\bchild(?:'s)?\s+guardian\b", r"\blegal guardian\b",
        r"\bguardians?\s+of\s+(?:a|an|the)?\s*(?:minor|child|children)\b",
        r"\bcustody\b", r"\bminor\b", r"\borphan(?:ed)?\b", r"\bfoster\b",
    )),
    # ⑦ "卫报" -> 岁主（Guardian ctx）的负例：**英国《卫报》(The Guardian)**。
    #    2026-10-10 实测 "The Guardian is a British newspaper" 被误改成岁主。
    "卫报": ("岁主", (
        r"\bnewspaper\b", r"\bBritish\b", r"\beditorial\b", r"\bjournalist\b",
        r"\breporter\b", r"\bheadline\b", r"\bcolumn(?:ist)?\b", r"\btabloid\b",
    )),
    # ⑧ "融合" -> 热熔(Fusion 属性) 的负例：**combine 动词语境**（2026-10-12 演唱会反应片）。
    #    #2125 "This song kind of combines so many elements" 谷翻"这首歌融合了许多元素"
    #    （动词融合），被学习库"融合->热熔"误改成"热熔了许多元素"。参考行命中
    #    combines/combination 即回滚；Fusion 属性语境（fusion girl 热熔女孩）不误回滚。
    "融合": ("热熔", (r"\bcombin\w+\b",)),
    # ⑨ "满的" -> 全部 的负例：**"满满的爱"被子串咬伤**（2026-10-12 演唱会反应片）。
    #    #2925 "so love" 谷翻"满满的爱"、#3696 "lots of love" 同理：学习库"满的->全部"
    #    子串命中"满满【的】爱"，咬出畸形"满全部爱"。参考行命中 so love/lots of love 即回滚。
    #    2026-11-06《I Played 300 Days》二校补：**"不【满的】声音"同被咬坏**（#102
    #    "很多不满的声音"→"很多不全部声音"，参考行 disgruntled）。"不满"表情绪者一律回滚。
    "满的": ("全部", (r"\bso love\b", r"\blots of love\b", r"\bfull of longing\b",
                    r"\bupset\b", r"\bfullest\b", r"\bcompass\b", r"\bfull\s+shot\b",
                    r"\bfull love\b", r"\bso full\b", r"\bdisgruntled\b",
                    r"\bdis(?:a)?satisf\w+\b", r"\bunhappy\b", r"\bnot\s+satisfied\b")),
    # --- 2026-10-27 演唱会/3.3 片：普通 nightmare 不应被 AC8 曲目 Nightmare 实体吃掉；
    #   RV/烧烤语境的 trailer 不是电影宣传片。
    "噩梦": ("Nightmare", (r"\bnightmare\s+loop\b", r"\bthat nightmare\.", r"^nightmare\.$",
                          r"^nightmare\.\s+i\s+messed\b",   # 2026-11-09 本片 cue1314：普通 nightmare
                          r"\bthe\s+nightmare\s+\[music\]")), # 2026-11-09 本片 cue2243：普通 nightmare
    "拖车": ("宣传片", (r"\bbarbecues?\b", r"\bRV\b", r"\bcamper\b")),
    # --- 2026-10-24 Journey Well'ed 二校负例 ---
    # 学习库 bi|溪流(confirmed) 把游戏台词 stream=溪流改成直播；参考行 taint this stream 回滚。
    # 2026-11-06 All 60 Gacha REACTION 补两条负例：白芷/穗穗卡池段的官方初奏是
    # 「清流往复处，自有春山可望。」，英文侧 "Where clean streams flow" 属**歌词意象**而非直播；
    # 同片 #6 "in future streams we'll be able to take a look at those" 才是直播 ⇒ 只能按句式回滚。
    "溪流": ("直播", (r"\btaint this stream\b", r"\bwith that curse\b",
                     r"\bclean\s+streams?\b", r"\bstreams?\s+flow\b",
                     r"\bstreams?\s+beckoned\b")),            # 2026-11-09 本片 cue2182：the streams beckoned 诗意"溪流"，非直播
    # seal=封印 规则误伤雪原动物海豹（#676/#677）；comforting/kill 语境回滚。
    "海豹": ("封印", (r"\bcomforting the seals?\b", r"\bkill a seal\b")),
    # 尤诺 Entity 的 Juno 裸变体误伤主播 Juno Umezono；参考行 Juno Umezono/Amazon 回滚。
    "Juno Umezono": ("尤诺Umezono", (r"\bJuno\s+(?:Umezono|Amazon)\b", r"@JunoUmezono\b")),
    # ⑩ "莱昂" -> 伺夜(Vigil，明日方舟) 的负例：**其他游戏联动角色里昂（Leon）**。
    #    2026-10-12 演唱会反应片 #996/#1008 主播聊某游戏摩托车联动皮肤 "the Leon and ADA
    #    skin"（里昂×艾达），伺夜 Entity 的 \bLeon\b 锚定误伤成"伺夜"。ref 同时命中
    #    ADA 即生化危机联动语境回滚；明日方舟片源 Leon 与 ADA 同现概率低，不影响。
    "莱昂": ("伺夜", (r"\bADA\b",)),
    # --- 2026-10-25 鸣潮 4.0 片源：Academy/Federation 参考行锚定的通用语境回滚 ---
    "学院": ("星炬学院", (r"\bAcademy Awards?\b", r"\bPolice Academy\b",
                          r"\bMilitary Academy\b", r"\bAcademy of\b",
                          # 2026-11-06 根因修复：通用锚 \bAcademy\b 会把「华胥/华溪学院」咬成
                          # 「华溪星炬学院」（实测片源 #62＝白芷卡池段）。凡参考行是 Huaxi/Huaxu/
                          # Huashu Academy 一律回滚，交给 CONTEXT_MAP 的 华溪→华胥 窄锚处理。
                          r"\bHuax[iu]\s+Academy\b", r"\bHuashu\s+Academy\b")),
    "联邦": ("新联邦", (r"\bFederation of\b", r"\bRussian Federation\b",
                        r"\bGalactic Federation\b")),
    # --- 2026-10-25 《How Did You Join Arknights or Endfield?》负例 ---
    "卡米尔": ("椿", (r"\bcompanion story\b",)),
    # 「凯尔特」是 凯尔希 的机翻错形，但英文真是 Celtic（历史名词）时必须回滚。
    # 2026-11-01 收窄：《How Did You Join Arknights or Endfield?》#1444 英文
    #   "until just before OG Celtic banner" —— 此处 Celtic 是 ASR 误听 Kelsey，
    #   原 \bCeltic\b 会把正确替换一并回滚，故排除 "Celtic banner" 这一形态。
    "凯尔特": ("凯尔希", (r"\bCeltic\b(?! banner)",)),
    "专注于": ("聚焦于", (r"\bfocus(?:ing|ed)?\b", r"\bfixat\w*\b")),
    # --- 2026-10-27 Back from Vacay 音乐点听直播：旧裸键误伤回滚 ---
    # 观众 Daniel 被 WuWa Dennia 的裸键改成达妮娅；问候语境回滚。
    "丹尼尔": ("达妮娅", (r"\bDaniel\b.*(?:what's up|hi|hey)|(?:what's up|hi|hey).*\bDaniel\b",)),
    # 音乐 pulse（脉搏/律动）被 gacha pulse=pulls 规则改成抽卡；音乐语境回滚。
    "脉搏": ("抽卡", (r"\bpulse\b.*\b(?:pumping|rhythm|beat|tempo|music|track|song)\b|(?:pumping|rhythm|beat|tempo|music|track|song)\b.*\bpulse\b",)),
    # 捐赠者用户名 Enfield Arcane 被终末地 Entity 的 Enfield 变体误改。
    "Enfield": ("终末地", (r"\bEnfield Arcane\b",)),
    # 乐队 The Lumineers 被露米 Entity 的 Lumi 变体咬成「露米neers」（ASR 作 Lumers）。
    "Lumi": ("露米", (r"\bLumers?\b|\bLumineers?\b",)),
    # sub activity=支线活动被「subs=字幕」抽卡术语误改（本片 #1037）。
    "潜艇": ("字幕", (r"\bsub activ\w*\b",)),
    # --- 2026-11-02 EP17「相变临界」英语反应片：鸣潮术语跨片串档 ---
    # 根因不在手写表，在学习库：`bi|哨兵→岁主`、`bi|皇帝→英白拉多` 两条 status=confirmed
    # 由 _learned_terms_for_mode 无条件并入 bi 趟裸键层，于是方舟片里
    # #148 "Sentry be duty."（讨论干员职业）被改成「岁主当值」、
    # #302 "Was that just Emperor over there?"（音频两引擎一致，字面就是 emperor）被改成「英白拉多」。
    # 已 learned-reject 这两个裸形；此处再补参考行负例，兜住今后同类（鸣潮的 Sentinel 不会
    # ASR 成 sentry、官方形是 Imperator，说 emperor/tsar 即字面「皇帝」）。
    # 注：EXCLUDE 只能写在字面量表里，不能靠 Entity(exclude=)——那按 variants 建键，
    #     而 岁主/英白拉多 两条的 variants 取不到「哨兵/皇帝」这两个中文错形键。
    "哨兵": ("岁主", (r"\bsentr(?:y|ies)\b",)),
    "皇帝": ("英白拉多", (r"\bemperors?\b", r"\btsar\b", r"\bkaiser\b")),
    "蒙特利": ("莫塔里", (r"\bMontreal\b",)),
    # ↑ 2026-11-02 兜裸键「蒙特利→莫塔里」：蒙特利 同时是 Montreal（蒙特利尔）的既有译名。
    #   ⚠ 机制限制（见本表头注释）：回滚是**整行** right→wrong，若同行另有一处合法「莫塔里」
    #   会被一起倒回去，故本条仅在「蒙特利」于该行单独出现时才安全（本片 #1530/#1537 均为单提）。
    # --- 2026-11-07 鸣潮 OST 6 reaction（Yuuma）---
    # ⚠ 不在本表加「先约电台 → 鸣潮先约电台」回滚：EXCLUDE 的判据是「wrong in old 且
    #   wrong not in new」，而 right（鸣潮先约电台）**包含** wrong（先约电台）⇒ 永远不进回滚
    #   分支（见 engine.py 负向排除段）。本片 #143 人工定稿用短名、脚本产出全称，属口径
    #   差异不是错误，已在 changelog 注明；要统一只能改 BILINGUAL 键本身，影响面过大。

    # ===== 2026-11-09 鸣潮全共鸣者 reaction Part 2（Bellow City/Ars）二次校准幂等收口 =====
    # 下列均为「为其他片源加的静态规则」在本片普通语境/观众名/ASR 乱码上的误伤，
    # 用高度特定于本片参考行的负向正则回滚，不影响其他片源（他片不会出现这些句子）。
    "抽卡": ("唤取", (r"\bgacha\s+game\w*\b",)),                # cue41：gacha game(w) 类型词，"抽卡游戏"固定搭配；\w 兼容 ASR Gamew
    "崩坏星穹铁道": ("《崩坏：星穹铁道》", (r"\bHong\s+Kong\s+Star\s+Rail\b",)),  # cue53：ASR Honkai→Hong Kong
    "Ananta": ("无限大", (r"\bAnanta\s+is\s+there\b",            # cue60：观众名 Ananta
                         r"\bAnanta\s+um\s+comment\b")),         # cue61：观众名（seen...comment）
    # cue255（wrong=新，行内含多个心月狐，全行回滚会误伤）改用逐 cue 侧车，见 process 的 bi_override。
    "救赎": ("拯救", (r"\bthis\s+is\s+Salvation\b",)),           # cue1128：普通"救赎"，非短片标题《拯救》
    "罪": ("心月狐", (r"\bnot\s+a\s+sin\b",)),                   # cue1181：sin 普通"罪"，非心月狐
    "黑暗面": ("暗面", (r"\bdark\s+side\b",)),                   # cue1767：dark side 通行译"黑暗面"
    "Edge Runners": ("边缘行者", (r"\bunfamiliar\s+with\s+Edge\b",)),  # cue1984：终稿保留英文
    "罗伊人": ("罗伊族", (r"\bis\s+a\s+Roya\b",)),               # cue2068：终稿"罗伊人"
    "Schwan": ("玄方", (r"\bYangyang\s+Schwan\b",                # cue2122：无法确认的 ASR 乱码，不臆测
                      r"\bSchwan\s+Ling\b")),                    # cue2126：同上
    # cue2389（裸键 Ching Sha 与 Sha 语境，行内多同形词，全行回滚误伤）改用逐 cue 侧车。

    # --- 2026-11-09 WuWa 3.8 REACTION 三轮回灌负例（配套 CONTEXT_MAP 尾部同日段）---
    "Suise i": ("穗穗", (
        r"\bhoshimachi\b", r"\bsuper\s*nova\b", r"\bcomet\b", r"\basteroid\b",
        r"\bhololive\b", r"\bfubuki\b", r"\bpekora\b", r"\bkyaruko\b")),
    #   ↑ 复制 L2762 "水成" 族负锚：EXCLUDE 按 wrong 键匹配（见 L12472 循环），
    #     新错形「Suise i」必须自带同组，否则 VTuber 星街彗星语境无从回滚。
    "Camellia": ("椿", (
        r"\bsong\b", r"\btrack\b", r"\bost\b", r"\balbum\b",
        r"\bmusical\s+reference\b")),
    #   ↑ 曲名《Camellia》保护（L2320 注释：本片系存在曲名实证 #284）。right="椿" 为
    #     单字，回滚是全句 replace——曲名句同时含角色「椿」的概率极低，按既有机制接受。
}


# 鸣潮专名漏译体检（2026-10-27 4.0 Lore Trailer《超越者》reaction 二次校准沉淀）。
# 结构同 ENDFIELD_MISSING_CHECK：(英文参考行正则, (中文必现词…), 说明)。
# 用法：missing <英> <中> --mode wuwa --window 1（专名常跨 cue 断行，务必带窗口）。
# 只收「官方英文专名或其 ASR 误听」，不收泛指词；「角」单字高频，标注为低置信。
WUWA_MISSING_CHECK = [
    (r"\b(?:Shorekeeper|Shortkeeper|Shopkeeper)\b", ("守岸人",),
     "Shorekeeper 官方中文=守岸人；ASR Shopkeeper/Shortkeeper"),
    (r"\b(?:Threnodian|Theronodian|Thernodian|throne\s+odian)\b", ("鸣式",),
     "Threnodian 官方中文=鸣式；ASR Theronodian/Thernodian"),
    (r"\b(?:passive|tacet|tacid|taca)\s+discords?\b", ("残象",),
     "Tacet Discord 官方中文=残象；ASR passive discord"),
    (r"\b(?:Fractsidus|Fractious|Fraidus|Fractus|Fracidus)\b", ("残星会",),
     "Fractsidus 官方中文=残星会；ASR Fractious"),
    (r"\b(?:Jue|Jua|Jewel\s*A)\b", ("角",),
     "岁主·角（Jue）；ASR Jua/Jewel A。单字低置信，命中请人工确认"),
    (r"(?<!lull\s)\b(?:Abby|Aby)\b", ("阿布",),
     "Abby=阿布（昵称；全名阿布拉克萨斯）。2026-11-09 加 lull 定长后顾："
     "『The lull aby.』的 aby 是摇篮曲分写碎片，WuWa3.8 cue261/298 曾报假漏译"),
    (r"\bAbraxas\b", ("阿布拉克萨斯", "阿布"),
     "Abraxas 官方中文=阿布拉克萨斯"),
    (r"\bNew\s+Federation\b", ("新联邦",),
     "New Federation 官方中文=新联邦"),
    (r"\bSentinels?\b", ("岁主",),
     "Sentinel(s) 官方中文=岁主"),
    # --- 2026-10-27 鸣潮 3.1「赠予雪中的你」精校：补 3.1 官方专名（--mode wuwa）---
    (r"\b(?:Aemeath|Immeth|Imth|Immoth|iMath)\b", ("爱弥斯",),
     "Aemeath 官方中文=爱弥斯"),
    (r"\b(?:Sigilum|Sigilium|Sigulum)\b", ("辛吉勒姆",),
     "Sigilum 官方中文=辛吉勒姆"),
    (r"\b(?:Exostrider|Exorrider|Exor Strider|Exorder|Exor Rider)\b", ("隧者",),
     "Exostrider 官方中文=隧者"),
    (r"\b(?:Aleph-1|Alfan|ALF one)\b", ("阿列夫一",),
     "Aleph-1 官方中文=阿列夫一"),
    (r"\b(?:Lahai-Roi|La Hyroy|La Hai Roy|La Hairoy|Laai Roy|Leah Hairoy)\b", ("拉海洛",),
     "Lahai-Roi 官方中文=拉海洛"),
    (r"\b(?:Starward Riseway|Starwood Riseway)\b", ("联运椎骨",),
     "Starward Riseway 官方中文=联运椎骨"),
    (r"\b(?:Bjartr Woods|Bart Woods)\b", ("浮光林",),
     "Bjartr Woods 官方中文=浮光林"),
    (r"\b(?:Sky Ark|Skyark)\b", ("天槎",),
     "Sky Ark 官方中文=天槎"),
    (r"\b(?:Court of Savantae|Court of Sante|Cord of Savante)\b", ("稷廷",),
     "Court of Savantae 官方中文=稷廷"),
    (r"\bFleet Snowfluff\b", ("飞行雪绒",),
     "Fleet Snowfluff 官方中文=飞行雪绒"),
    (r"\bSnowfluff Seal\b", ("雪绒海豹",),
     "Snowfluff Seal 官方中文=雪绒海豹"),
    (r"\b(?:Reactor Core|Reactor Drive)\b", ("炉芯",),
     "Reactor Core 官方中文=炉芯"),
    (r"\bStrider Gate\b", ("隧门",),
     "Strider Gate 官方中文=隧门"),
    (r"\bExoswarm\b", ("隧群",),
     "Exoswarm 官方中文=隧群"),
    (r"\b(?:Void matter|Void space|Void storm)\b", ("虚质", "虚质空间", "虚质磁暴"),
     "Void 官方中文=虚质/虚质空间/虚质磁暴"),
    (r"\b(?:Tacet Mark|tacet mark)\b", ("声痕",),
     "Tacet Mark 官方中文=声痕"),
    (r"\bResonators?\b", ("共鸣者",),
     "Resonator 官方中文=共鸣者"),
    (r"\bLuuk Herssen\b", ("陆·赫斯",),
     "Luuk Herssen 官方中文=陆·赫斯"),
    (r"\b(?:Naborr|Navora)\b", ("娜波摩",),
     "Naborr 官方中文=娜波摩"),
    (r"\b(?:Labell College|Rebell College|Rabelle College)\b", ("拉贝尔学部",),
     "Labell College 官方中文=拉贝尔学部"),
    (r"\b(?:Roya Frostlands|Frostlands)\b", ("罗伊冰原", "冰原"),
     "Frostlands 官方中文=罗伊冰原/冰原"),
    (r"\bStartorch Academy\b", ("星炬学院",),
     "Startorch Academy 官方中文=星炬学院"),
    (r"\bBlack Shores\b", ("黑海岸",),
     "Black Shores 官方中文=黑海岸"),
    (r"\bMoonchasing Festival\b", ("追月节",),
     "Moonchasing Festival 官方中文=追月节"),
    (r"\b(?:Jinzhou|Jing\s?Jo\w*|Jingo|Gingjo)\b", ("今州",),
     "Jinzhou 官方中文=今州；ASR 常吞音作 Jingjo/Jing Jo/Jingo（2026-11-02 本片 #420/#881/#884 实测，"
     "#420 更被谷翻整词译成「靖国神社」，见 CONTEXT_MAP 同名锚定）"),
    (r"\bLeviathan\b", ("利维亚坦",),
     "Leviathan 官方中文=利维亚坦"),
    # --- 2026-10-27 3.X 巡演/EP 二次校准补漏 ---
    (r"\b(?:Sun|Day)\s+Spirits?\b", ("日灵",),
     "Sun Spirit 官方中文=日灵"),
    (r"\bAlissium\b", ("向彼方行",),
     "Alissium=《鸣潮：向彼方行》；勿裸收 Elysium（明日方舟极境）"),
    (r"\b(?:Whining Aix'?s Mire|whining Ajax'?s meer)\b", ("怨鸟泽",),
     "Whining Aix's Mire 官方中文=怨鸟泽"),
    (r"\bMt?\.?\s*Firmament\b", ("乘霄山",),
     "Mt. Firmament 官方中文=乘霄山"),
    (r"\b(?:Heliotic|Heliodic|Heliotix)\s+Six\b", ("秘日六席",),
     "Heliotic Six 官方中文=秘日六席"),
    (r"\bRoya\b", ("罗伊族",),
     "Roya 官方中文=罗伊族（低置信，需语境）"),
    (r"\bTo the New World\b", ("致予新世界",),
     "To the New World 官方中文=「致予新世界」"),
    (r"\bDecensus Ad Nihilum\b", ("坠入虚无",),
     "Decensus Ad Nihilum 官方中文=坠入虚无"),
    (r"\bDasvidaniya\b", ("直到下次再见",),
     "Dasvidaniya 官方中文=直到下次再见"),
    (r"\bL!!!!ght\b", ("L!!!!ght",),
     "L!!!!ght 官方名保留英文"),
    # --- 2026-10-27 鸣潮 5h47 巡演/EP 二次校准（MISSING）---
    (r"\bRover\b", ("漂泊者",), "Rover 官方中文=漂泊者"),
    (r"\b(?:Nikke|NIKKE)\b", ("妮姬",), "NIKKE 官方中文=胜利女神：妮姬/妮姬"),
    (r"\b(?:Septimont?|Septimo)\b", ("七丘",), "Septimont 官方中文=七丘"),
    (r"\b(?:Bladeunner|Blade Runner)\b", ("银翼杀手",), "Blade Runner 官方中文=银翼杀手"),
    (r"\bEncor\b", ("安可",), "Encore 官方中文=安可"),
    (r"\bFirst and Last Gift\b", ("最初和最后的礼物",), "3.3 达妮娅曲官方名"),
    (r"\bDrive Immune Nuts\b", ("Driving Me Nuts",), "Itasha Coffee 产品名"),
    (r"\b(?:Jingron|Jingran|Dingron)\b", ("景燃",),
     "Jingron/Jingran=景燃（2026-11-02 移除裸 Jing：会咬 Jing Jo=今州，本片 #884 实测误报；"
     "outshines 语境的裸 Jing 已由 CONTEXT_MAP 的 \\bJing\\b.*outshines 专项锚定覆盖）"),
    # --- 2026-10-28 wuwa_glossary.tsv 并入（只体检不改写）---
    # 通用词/武器名做裸键会误伤，只按英文参考行体检，命中后人工判断是否逐 cue 修。
    # ⚠ Blade 不入表：CONTEXT_MAP 已按「银翼杀手/刀锋战士」语境处理，泛化会冲突。
    (r"\bMidreal\b", ("在野",), "Midreal 官方中文=在野（wuwa_glossary.tsv:71）；低置信"),
    (r"\bLament\b", ("悲鸣",), "Lament 官方中文=悲鸣（wuwa_glossary.tsv:74）"),
    (r"\bAnnihilation\b", ("湮灭",), "Annihilation 官方中文=湮灭（wuwa_glossary.tsv:88）"),
    (r"\bPistol\b", ("佩枪", "手枪"), "Pistol 官方中文=佩枪（wuwa_glossary.tsv:96）；2026-11-09 补「手枪」为可接受译——WuWa3.8 cue71/cue298 谷翻「她的手枪/五星级手枪」语义正确，非漏译"),
    (r"\bRectifier\b", ("音感仪",), "Rectifier 官方中文=音感仪（wuwa_glossary.tsv:97）"),
    (r"\bSword\b", ("迅刀",), "Sword 官方中文=迅刀（wuwa_glossary.tsv:98）"),
    (r"\bGauntlet\b", ("臂铠",), "Gauntlet 官方中文=臂铠（wuwa_glossary.tsv:99）"),
    (r"\bConvene\b", ("唤取",), "Convene 官方中文=唤取（wuwa_glossary.tsv:101）"),
    # --- 2026-11-02 鸣潮 Reaction Part 1（3546 cue，英文参考行在上）二次校准 ---
    # 这批**只在参考行出现拉丁原名、中文行要么没有要么是别的音译**，建裸键永远命中不到
    # （实测中文行 0 次），所以按本表纪律只登记为体检项，命中后人工逐 cue 判断。
    (r"\b(?:Changli|Chang\s*Lee|Chang\s*Lee)\b", ("长离",),
     "Changli 官方中文=长离（今州令尹参事，1.1）"),
    (r"\b(?:Cartethyia|Kartia|Kartilla|Carilla)\b", ("卡提希娅",),
     "Cartethyia 官方中文=卡提希娅（2.4，动画短片《天明》主演）"),
    (r"\b(?:Cantarella|Canerella|Canterella)\b", ("坎特蕾拉",),
     "Cantarella 官方中文=坎特蕾拉（2.2，勿与珂莱塔 Carlotta 混）"),
    (r"\bGalbrena\b", ("嘉贝莉娜",), "Galbrena 官方中文=嘉贝莉娜（2.7）"),
    (r"\bZani\b", ("赞妮",), "Zani 官方中文=赞妮（2.4；ASR 形 Zany 已作裸键收录）"),
    (r"\bAugusta\b", ("奥古斯塔",),
     "Augusta 官方中文=奥古斯塔（2.6「日以灼锋，月以流明」，七丘总督，导电/长刃）"),
    (r"\b(?:Xiangli\s*Yao|Shang\s*Shangi\s*Yao)\b", ("相里要",),
     "Xiangli Yao 官方中文=相里要（1.2）；ASR 常粘连成 Shang Shangi Yao"),
    (r"\b(?:Montelli|Montter|Montellis)\b", ("莫塔里",),
     "Montelli 官方中文=莫塔里（珂莱塔家族，拉古那黑手党；库街区名词注释三处互证）"),
    (r"\bImperator\b", ("英白拉多",),
     "Sentinel Imperator＝岁主英白拉多（黎那汐塔的岁主）；非「大君」"),
    (r"\bacolytes?\b", ("见习教士", "教士", "圣职者"),
     "Acolyte 菲比官方身份=见习教士（隐海修会）；低置信，命中请核对上下文"),
    (r"\b(?:Chana|Ciaccona|Sia\s*Chana)\b", ("夏空",),
     "Ciaccona 官方中文=夏空（2.4，EP「我们依旧歌唱」）；ASR 常作 Chana/Sia Chana"),
    (r"\bCombat\s+Showcases?\b", ("战斗演示",),
     "Combat Showcase 官方中文=共鸣者战斗演示（片源类型词，官方 B站/微博口径）"),
    (r"\bResonator\s+Showcases?\b", ("共鸣者展示", "展示"),
     "Resonator Showcase 官方中文=共鸣者展示 / 共鸣者「XX」展示PV"),
    # --- 2026-11-06 《I Played 300 Days of Wuthering Waves》（微软翻译，508 cue）二校沉淀 ---
    (r"\b(?:Introductory|Intro)\s+skills?\b", ("变奏技能",),
     "Introductory/Intro skill 官中=变奏技能（延奏技能=Outro，2026-11-06 官方核实纠偏）"),
    (r"\bsub-?genres?\b", ("副属性",),
     "声骸 subgenre 官中=副属性（『副词条』为玩家语；微软翻译直译『子流派』）"),
    (r"\bwave\s?(?:band|bands|plate|plates)\b", ("结晶波片",),
     "wave band(s)/plate(s) 官中=结晶波片（Echo 强化材料）"),
    (r"\bTowers?\s+of\s+(?:Trials?|Discord)\b", ("逆境深塔",),
     "Tower of Trials 官中=逆境深塔（官网逐字；Tower of Discord 为同玩法 ASR 异形）"),
    (r"\bBlooming\s+Jade\s*Hav(?:en|or)\b", ("玉阙玄华",),
     "Blooming Jade Harbor/Jadehaven=心的五星音感仪专武官中「玉阙玄华」（3.7 公告逐字）"),
    (r"\bQB\s*Wars\b|\bCubie\s+Wars\b", ("团团勇者大乱斗",),
     "Cubie Wars（QB Wars 为 ASR 形）官中=团团勇者大乱斗（3.7 公告逐字）"),
    (r"\bWuwa\b", ("鸣潮",),
     "Wuthering Waves 缩写 Wuwa（2026-11-06 实测）；⚠禁裸键——本表实体 'Wuwa Tappo'->呜哇塔波 为其超串，裸键会二次咬合（terms-check 6 处/kb-lint 级联互含），只报不改交人工逐 cue 判"),
    (r"\bgood\s+pity\b", ("保底",),
     "pity 抽卡保底（微软翻译误『好遗憾』，#447 实证；⚠只锁 good pity——#461 great pity 属普通可惜义，裸锚会过咬）"),
    (r"\b(?:Suwamin|Suvamin|Slonmin|Slongming|Somin|So Min|Swimin)\b", ("锁暝",),
     "Suoming（锁暝）微软翻译通道 ASR 音译族（2026-11-06 沉淀，实体见 Entity('锁暝')）"),
    (r"\b(?:Sheena|Shina)\b", ("心",),
     "Hsin（心）的 ASR 形 Sheena/Shina（reaction 片指可玩角色，岁主本体作 Moon Fox/Sheen；跨游戏片慎用）"),
    (r"\b(?:Zeni|Zany|Zunny|Zanie)\b", ("赞妮",),
     "Zani（赞妮）的 ASR 形 Zeni/Zany 族；微软翻译落成「善尼」（本片 #220 'This is Zeni, the one "
     "with the big sword'）。⚠ 本条只查「赞妮」是否在位，不查武器类别：她官方武器类型是臂铠"
     "（库街区 role.info），所以 \\bSword\\b→迅刀 那条对本片是误报，勿据此把「大剑」改成「迅刀」。"),
    (r"\bXuan\s*[Ll]in\b|\bXuanling\b", ("秧秧·玄翎",),
     "秧秧·玄翎（3.5 新形态）；微软翻译把 'Yang Yang Xuan Lin.' 落成「杨杨玄林」（本片 #347）。"
     "其官方初奏=「……好久不见，{PlayerName}。」⇒ 台词里被 ASR 写成 Frowere 的那一格是**玩家名"
     "占位符**（中文侧作『漂泊者』），不是弗洛洛（上一轮误判已于 2026-11-06 撤销）。"),
    (r"\bAeon\b", ("星神",),
     "低置信：主播把今州岁主类比成《崩坏：星穹铁道》的星神（Aeon 官中=星神，HSR_CONTEXT:283）。"
     "官方英文里岁主「角」作 Jue/Jué，**不是 Aeon** ⇒ 出现 Aeon 时要分清是星铁类比还是我方误读，"
     "命中请人工裁决，不自动改名。"),
    (r"\b(?:Svarog|Svaroz)\b", ("声骸", "套装"),
     "⚠查无：微软翻译片 #304『Sheen's set on Svaroz』，官方 3.7 三套新合鸣为 衔梦照世之心/镜影流电之瞬/茜染怀想之花，Svarog/Svaroz 无对应官方名，命中请人工裁决（低置信不校名）"),
]


# 常见机翻错词（在参考行语境下被误译的普通词）
WORD_MAP = {
    "换钥匙": "转调",      # changed key（音乐语境）
    "暴跌": "下落攻击",    # plunging attack（游戏招式）
    # --- 2026-09-04 THIS_IS_CRAZY_Hsin 二次校准沉淀（特定错词短语，出现即改）---
    "allult 线": "变身台词", "allult": "变身",   # alult=alt 变身（长词优先）
    "她的一切": "她的变身",                       # Her alt（非"一切"）
    "老板地图": "Boss地图",                       # boss map（非"老板"）
    "归于毁灭": "归于废墟",                       # return to ruin（ruin=废墟）
    # --- 2026-09-08 NO ONE CAN CONTROL THEMSELVES! 校准新增（出现即改的固定错形）---
    "什至": "甚至",                                # 甚至 误形（#106 我什至）
    "种光环": "刷光环",                            # aura farming（#67 她只是在刷光环）
}


# =============================================================
# 最终幻想：共鸣（FFRS）专用词表（--ffrs，2026-10-28 新增）
#
# 片源：MarcoMeatball《FINAL FANTASY RESONANCE!!!!!!!!! PART 1》
#   （英语原声 + 微软翻译，4378 cue，每 cue 中文 + 英文参考行，CRLF 无 BOM）
# 官方中文依据：SE 官方中文剧情稿 + FFRS 中文攻略（ali213/139y/dvg/gamersky）+
#   FFBE 中文；本表只收 FFRS 专属、可安全全局替换的长键。
# 歧义词（雨/云/雷恩/泰拉/幻象/眩晕/极限技 等）一律走 FFRS_CONTEXT 参考行锚定，
#   严禁裸键（会误伤天气、普通名词、FF14 的“极限技”等）。
# 句子级重写/一次性道具名（Divine Signate、Oblivion Pallet、Pteranigma、
#   Astral Jacket、D Shell、重弩 等）留在字幕 fix 表，不进本表。
# =============================================================

FFRS_TERMS = {
    # 游戏名
    "最终幻想居民": "《最终幻想：共鸣》",
    "最终幻想住所": "《最终幻想：共鸣》",
    "幻想住宅": "《最终幻想：共鸣》",
    "勇敢修斯": "《最终幻想：勇气启示录》",
    "勇敢的修斯": "《最终幻想：勇气启示录》",
    "勇者Exus": "《最终幻想：勇气启示录》",
    "Brave Xius": "《最终幻想：勇气启示录》",
    # 原文已带书名号时，整段替换，避免出现《《…》》
    "《最终幻想居民》": "《最终幻想：共鸣》",
    "《最终幻想住所》": "《最终幻想：共鸣》",
    "《幻想住宅》": "《最终幻想：共鸣》",
    "《勇敢修斯》": "《最终幻想：勇气启示录》",
    "《勇敢的修斯》": "《最终幻想：勇气启示录》",
    "《勇者Exus》": "《最终幻想：勇气启示录》",
    "《Brave Xius》": "《最终幻想：勇气启示录》",
    "《王牌空战》": "《皇牌空战》",
    "《王牌空战8》": "《皇牌空战8》",
    "《最终幻想：勇者Exus》": "《最终幻想：勇气启示录》",
    "《幻影之刃零》": "《影之刃零》",
    "《幻影之刃》": "《影之刃零》",
    "《光辉之路》": "《火焰纹章：苍炎之轨迹》",
    "《时间之笛》": "《塞尔达传说：时之笛》",
    "《魔兽世界永远》": "《魔兽世界》",
    # 地名
    "地球神社": "土之神殿",
    "地神社": "土之神殿",
    "大地神社": "土之神殿",
    "土神社": "土之神殿",
    "格尔沙尔特": "格兰谢尔特",
    "格谢尔特": "格兰谢尔特",
    "格兰德歇尔": "格兰谢尔特",
    "祖拉德": "索尔达德",
    "科洛波斯": "科洛博斯",
    "科拉博斯": "科洛博斯",
    "科洛布斯": "科洛博斯",
    # 人名/称谓
    "里根爵士": "雷根爵士",
    "拉兹韦尔": "拉斯韦尔",
    "拉斯威尔": "拉斯韦尔",
    "拉兹维尔": "拉斯韦尔",
    "塞弗罗": "萨菲罗斯",
    "齐顿": "吉坦",
    "Zidon": "吉坦",
    "提图斯": "提达",
    "弗里昂": "弗利奥尼尔",
    "光明战士": "光之战士",
    # 作品名
    "王牌空战": "《皇牌空战》",
    "幻影之刃零": "《影之刃零》",
    "幻影之刃": "《影之刃零》",
    "光辉之路": "《火焰纹章：苍炎之轨迹》",
    "时间之笛": "《塞尔达传说：时之笛》",
    "魔兽世界永远": "《魔兽世界》",
    # 系统/道具
    "水晶圣殿": "水晶圣祠",
    "幻视水晶": "幻兵水晶",
    "对价性": "二元性",
    "海妖之塔": "塞壬之塔",
    "平板碎片": "石板碎片",
    "魔药课": "魔药",
    "湿婆": "希瓦",
    "巴哈米特": "巴哈姆特",
    "天秤座": "天秤",
    "魔石碎片": "魔晶石碎片",
    "魔法科技装甲": "魔导装甲",
    "魔法科技护甲": "魔导装甲",
    "多重掩体": "多重掩护",
}

# (英文参考行正则, 中文行错形, 正确形)；只对首中文行生效，参考行一字不动。
FFRS_CONTEXT = [
    # Visions：排除 “true vision of the game”（真正的愿景）
    (r"\bvisions?\b(?!\s+of the game)", "幻象", "幻兵"),
    (r"\bvisions?\b(?!\s+of the game)", "异象", "幻兵"),
    (r"\bvisions?\b(?!\s+of the game)", "愿景", "幻兵"),
    # Stagger
    (r"\bstagger(?:ing|ed|s)?\b", "眩晕", "破防"),
    (r"\bstagger(?:ing|ed|s)?\b", "击退", "破防"),
    (r"\bstagger(?:ing|ed|s)?\b", "踉跄", "破防"),
    (r"\bstagger(?:ing|ed|s)?\b", "蹒跚", "破防"),
    # Rain（大小写敏感，避免 weather 的 rain）
    (r"(?-i:\bRain\b)", "雨", "雷因"),
    (r"(?-i:\bRain\b)", "雷恩", "雷因"),
    # Terra（FF6=蒂娜；KH Birth by Sleep 的 Terra=泰拉，排除）
    (r"^(?!.*Birth by).*\bTerra\b", "地云", "蒂娜"),
    (r"^(?!.*Birth by).*\bTerra\b", "泰拉", "蒂娜"),
    # Cloud（大小写敏感，避免普通“云”）
    (r"(?-i:\bCloud\b)", "云", "克劳德"),
    # 其他角色/系统
    (r"(?-i:\bLeah\b)", "莉娅", "莉亚"),
    (r"(?-i:\bRaegen\b)", "里根", "雷根"),
    (r"(?-i:\bTronn?\b)", "《创：战记》", "特隆"),
    (r"(?-i:\bTronn?\b)", "《创》", "特隆"),
    (r"(?-i:\bTronn?\b)", "创：战记", "特隆"),
    (r"(?-i:\bUmbra\b)", "暗影", "安布拉"),
    (r"(?-i:\bVaan\b)", "沃恩", "梵"),
    # Limit Break（FF14 官方=极限技；FFRS/FF16 官方=极限爆发）
    (r"^(?!.*(?:14|XIV|fourteen)).*limit break", "极限技", "极限爆发"),
    (r"^(?!.*(?:14|XIV|fourteen)).*\bLB\b", "极限技", "极限爆发"),
]
