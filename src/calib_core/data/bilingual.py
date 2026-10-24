# -*- coding: utf-8 -*-
# @version 2.7.0
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
    "Jingjo": "Jinzhou", "Jingo": "Jinzhou", "Gingjo": "Jinzhou",
    "Hang Long": "Huanglong", "Wang Long": "Huanglong", "Guang Long": "Huanglong",
    "Fraidus": "Fractsidus", "Fraid": "Fractsidus",        # 残星会官方英文名（依 md 中英对照）
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
    "shling鸟": "天鹅灵鸟",                                       # Xuanling/Lling bird（#5455）
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
    "skyarch": "天弧", "academyy": "学院", "N'avorora": "恩沃拉",
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
    "吴阿": "鸣潮",
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
    "Flova": "弗洛瓦",
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
    "塔塞特人": "残象", "塔塞特": "残象", "Tacet 不和": "残象",
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
    "Lucilla": "洛瑟菈", "露西拉": "洛瑟菈", "卢西拉": "洛瑟菈", "洛西拉": "洛瑟菈",
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
    # "朱锁->玄朱锁" 不入表：terms-check 报 7 处二次命中（"朱红锁/Vermillion lock" 已产出"玄朱锁"，
    #   短键会再咬成"玄玄朱锁"）；按既有判例退回逐 cue 覆盖（本片 #2886/#5168/#5346）。
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
}


# 保留英文不译的专名（仅提示，不替换）
KEEP_EN = {"Crywolf"}


# 上下文相关替换：仅当 参考行 命中该英文正则时才把中文里的错误形式替换掉（仅双语模式）
# 2026-10-20 3.7 后日谈：Schwanqing/Swan Ching 的英文锚点（旧规则目标曾误沉淀为「玄方清」）
_XQ_RX = r"\bSchwanqing\b|\bSchwan\s*Ching\b|\bSwan\s*Ching\b|\bSchwan\s*ching\b|\bSwanching\b"

CONTEXT_MAP = [
    # (英文正则, 仅当英文行匹配时才把中文里的某错误形式替换为正确形式)
    (r"\bScar\b", "疤痕", "伤痕"),
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
    (r"\bSushi\b", "寿司", "穗穗"),              # Sushi=Suisui 穗穗
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
    (r"\bfarming\b", "种田", "刷本"),             # farming 抽卡游戏=刷本/肝，非"种田"
    (r"\bfarming\b", "务农", "刷本"),
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
    (r"\bCarla\b", "卡拉", "珂莱塔"),                   # Carlotta ASR 截断（cue168，2.0 trailer/娃娃语境）
    (r"\bcara\b", "卡拉", "卡提希娅"),                  # Cartethyia 截断（cue389，"2.0/2.x 的耶稣"=圣女救世主梗）
    (r"\bUno\b", "Uno", "尤诺"),                        # Iuno ASR 变体（cue443，与奥古斯塔日/月对比语境）
    (r"\bUnun\b", "Unun", "尤诺"),                      # 同上变体（cue444）
    (r"\bShakona\b", "Shakona", "夏空"),                # Ciaccona=夏空·托卡塔；韩国主播读"샤콘"致 ASR Shakona（cue193，EP/暮光歌词）
    (r"\bAusta\b", "澳大利亚", "奥古斯塔"),             # Augusta ASR 截断被谷翻当国名（cue700，歌手讨论）
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
    (r"\bSchwan ?Lling\b", "施万林鸟", "天鹅灵鸟"),  # #760 清宵身边的灵鸟
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
    (r"\bYang\b", "杨", "秧秧"),                   # #12/#609 秧秧
    # --- 2026-09-08 【字幕】I cannot believe this is a gacha game - WW 2.7 Story Quest Highlight 校准新增 ---
    # 利维亚坦（Leviathan=2.7 鸣式 BOSS 官方译名；防误解作神话"利维坦"）
    (r"\bLeviathan\b", "利维坦", "利维亚坦"),
    # 坎特蕾拉（Cantarella=坎特蕾拉·翡萨烈）各 ASR/主播口误变体
    (r"\bCanell?a\b|\bCaner?a\b", "卡内拉", "坎特蕾拉"),   # #513/#574/#1006
    (r"\bCanerella\b", "卡内雷拉", "坎特蕾拉"),     # #317
    (r"\bCanellilla\b", "卡内利拉", "坎特蕾拉"),    # #574
    (r"\bContella\b", "康特拉", "坎特蕾拉"),        # #657/#660
    (r"\bCartilla\b", "卡提拉", "坎特蕾拉"),        # #768
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
    (r"\bAn ?anta\b", "Anta", "异环"),                                 # Ananta 谷翻残留（#1715）
    (r"\bAn ?anta\b", "Ananta", "异环"),                               # 中文行英文残留（#414/3986/3994）
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
    (r"\bpsycho\b", "心理", "疯子"),               # #559
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
]


# --- 2026-09-08 负向排除上下文（高歧义词防护，仅双语模式）---
# BILINGUAL_TERMS/CONTEXT_MAP 中个别词在特定口语/非游戏语境会误伤。例：
#   帐篷=十连 是抽卡术语，但语言讨论语境 tent 是 text 的 ASR 误听；
#   简而言之=这个短片里 是机翻错形，但参考行 in short 本就是"简而言之"。
# 机制：术语被替换后，若参考行(英文)命中下列任一排除正则，回滚该替换并从命中统计移除。
# 结构：{wrong: (right, (排除正则...))}，right 用于回滚（须与所在术语表的 value 一致）。
# 比无条件替换更精准，不依赖人工负例注释。新增歧义词时按此结构追加。
EXCLUDE_CONTEXT = {
    # --- 2026-10-22 Tenha 鸣潮全 EP reaction 片负例 ---
    # ① \bAngel\b=安吉尔 的负例：歌词里的“天使”。本片 #945 "angel consumes"、
    #    #1854 独立成行 ">> Angel" 都被基线误改成“安吉尔”，歌词语境回滚。
    "天使": ("安吉尔", (r"\bangel consumes\b", r"^\s*>>?\s*angel\s*$",
                        r"\b50\s*/\s*50\s*angel\b")),   # 2026-10-22 #66 频道名 50/50 Angel
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
    "简而言之": ("这个短片里", (r"\bin short\b",)),
    # #1041/#1078/#1086 main frame=主框架（玄方城主系统/主机），非"画面"；
    # 参考行命中 main frame 时回滚 \bframe\b=画面 规则（防把主机误译成画面）。
    "框架": ("画面", (r"\bmain frame\b",)),
    # --- 2026-09-10 WW 3.1 Story Reaction (Stream #2) 负例 ---
    # \bseal\b=封印 规则的负例：官方名词"雪绒海豹"（Snowplush Seal）语境下回滚，
    # 参考行命中 seal 时先被 CONTEXT 改成"雪绒封印"再整词换回，不影响行内其他"封印"。
    "雪绒海豹": ("雪绒封印", (r"\bseal\b",)),
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
    "典范": ("Paragon", (r"\bparagon of\b", r"\bparagon\.?\s+(?:of|for)\b")),
    # ④ \bswimming\b -> 锁暝(Suoming) 的负例：**真·游泳/固定短语与比喻**。
    #    up 主常把 Suoming 玩梗念成 swimming（归锁暝），但 "go swimming"（双关梗，
    #    原文保留游泳二字更忠实原声）与 "swimming in an ocean/sea"（情感比喻）须回滚。
    "游泳": ("锁暝", (
        r"\bgo swimming\b", r"\bgoes swimming\b", r"\bwent swimming\b",
        r"\bswimming in\b", r"\bocean\b", r"\bsea\b", r"\bpool\b", r"\bunderwater\b",
    )),
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
    "满的": ("全部", (r"\bso love\b", r"\blots of love\b", r"\bfull of longing\b")),
    # --- 2026-10-24 Journey Well'ed 二校负例 ---
    # 学习库 bi|溪流(confirmed) 把游戏台词 stream=溪流改成直播；参考行 taint this stream 回滚。
    "溪流": ("直播", (r"\btaint this stream\b", r"\bwith that curse\b")),
    # seal=封印 规则误伤雪原动物海豹（#676/#677）；comforting/kill 语境回滚。
    "海豹": ("封印", (r"\bcomforting the seals?\b", r"\bkill a seal\b")),
    # 尤诺 Entity 的 Juno 裸变体误伤主播 Juno Umezono；参考行 Juno Umezono/Amazon 回滚。
    "Juno Umezono": ("尤诺Umezono", (r"\bJuno\s+(?:Umezono|Amazon)\b", r"@JunoUmezono\b")),
    # ⑩ "莱昂" -> 伺夜(Vigil，明日方舟) 的负例：**其他游戏联动角色里昂（Leon）**。
    #    2026-10-12 演唱会反应片 #996/#1008 主播聊某游戏摩托车联动皮肤 "the Leon and ADA
    #    skin"（里昂×艾达），伺夜 Entity 的 \bLeon\b 锚定误伤成"伺夜"。ref 同时命中
    #    ADA 即生化危机联动语境回滚；明日方舟片源 Leon 与 ADA 同现概率低，不影响。
    "莱昂": ("伺夜", (r"\bADA\b",)),
}


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

