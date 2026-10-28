# -*- coding: utf-8 -*-
# @version 2.8.0
"""术语/实体数据表

源：subtitle_calib_merged.py L7369-L8839 @ 97d7d463（2026-10-24 冻结快照）
"""
import io
import os
import re
import shutil
import sys
import unicodedata
from .ark import _SEONJEONG_ANCHOR
from .entities_base import Entity



# --- 实体注册表（新沉淀追加于此）---
# 示范条目：变体已存在于扁平表（注册为幂等 no-op），en/ja/ko/category/note
# 是本层新增的对象级元数据。实体覆盖的既有键会在 kb-export 视图中带上这些属性。
ENTITIES_PART1 = [
    Entity("漂泊者", modes=("bi",), en="Rover", ja="漂泊者", ko="방랑자",
           category="角色",
           variants=("罗弗", "罗孚", "罗浮", "路虎", "漫游车",
                     "Rover", "Ruva", "Ruver", "鲁瓦", "鲁弗", "Wover", "沃弗"),
           ctx=((r"\brover\b", "漫游者"),),
           note="鸣潮主角。'鲁瓦'长键须先于'鲁瓦扬->罗伊'(罗伊古文明)处理，防误伤；"
                "主播昵称'弗罗弗'(Frover)由 CONTEXT_MAP 兜底，防'罗弗'键子串误伤。"),
    Entity("心月狐", modes=("bi",), en="Sheen / Hsin", ja="シン",
           category="角色/岁主",
           variants=(
               # --- 既有：Sheen 音译残留 ---
               "Sheen", "月狐希恩", "希恩", "谢恩",
               # --- Hsin 官方罗马音的英文 ASR 高频错听（仅收 Hsin 独有派生形，
               #     歧义短键 Shin/Sin/Xin/Shen/Hshen 走 ctx 参考行锚定，防误伤普通英文）---
               "Hsin", "Hsin the Moon Fox", "Hsin the Moonfox",
               "Xhin", "Hsien", "Hshin", "Hsi",
               "Hsin'", "hsin", "HSIN",
               "Hsin-sama", "Hsin sama", "Lady Hsin", "Lord Hsin",
               # --- 中文机翻义项残留（Sheen=光泽/Hsin=欣/新/馨）---
               "心月胡", "心悦狐", "新月狐", "心月孤", "心月弧",
               "心月湖", "心月葫", "心月蝴", "心月狐岁主",
               # --- 组合词：岁主/月狐的机翻拆字 ---
               "月狐岁主", "月狐 Sentinel", "Sentinel Sheen",
               "Sheen Sentinel", "Moon Fox Sheen", "Moonfox Hsin",
               "月狐辛", "月狐新", "月狐欣", "月狐馨",
           ),
           ctx=((r"\bSheen\b", "辛"), (r"\bSheen\b", "光泽"),
                (r"\bSheen\b", "闪光"), (r"\bSheen\b", "光辉"),
                # 负向后行 (?<![Ss]hu )：Shu Shin=溯心 ASR 变体，排除后才归心月狐
                (r"(?<![Ss]hu )\bShin\b", "申"), (r"(?<![Ss]hu )\bShin\b", "辛"),
                (r"(?<![Ss]hu )\bShin\b", "胫"), (r"(?<![Ss]hu )\bShin\b", "新"),
                # 2026-10-04 移除 (r"\bShin\b", "神")：会把泛指"天神(celestials)"误改成"天心月狐"，
                #   且"神"是常用字，裸 ctx 风险过高（本片 #1770 实测误伤）。
                (r"\bHsin\b", "欣"), (r"\bHsin\b", "新"), (r"\bHsin\b", "馨"),
                (r"\bHsin\b", "心"), (r"\bHsin\b", "辛"),
                # \bXin\b 加负向后行：Shu Xin/Su Xin=溯心 ASR 变体、Suxin=溯心官方名，
                # 这些语境的 欣/新/心 归溯心（见 Entity('溯心')），不得咬成心月狐
                (r"(?<![Ss]hu )(?<![Ss]u )(?<![Ss]uxin)\bXin\b", "欣"),
                (r"(?<![Ss]hu )(?<![Ss]u )(?<![Ss]uxin)\bXin\b", "新"),
                (r"(?<![Ss]hu )(?<![Ss]u )(?<![Ss]uxin)\bXin\b", "心"),
                (r"\bShane\b", "肖恩"),
                # 2026-09-20 移除 (r"\bSentinel\b", "岁主")：岁主=Sentinel 的官方通译（类目词），
                #   心月狐 只是其中一位；该规则会把泛指"岁主形态/sentinel like form"误缩成
                #   "心月狐"，且 \bSentinel\b 走 re.I 会命中小写普通词 sentinel，属系统性误伤。
                # 2026-09-25 《寻心》(Hsin's Trail) 动画短片 reaction 片：Hsin 的 ASR 误拆/误听
                (r"\bisen\b", "他伊森"),        # "Hsin's" 被 ASR 拆成 "he isen ' s"，谷翻成"他伊森"（"他"为误拆残渣）
                (r"\bisen\b", "伊森"),          # 伊森=Ethan 常规译名，仅 isen 佐证时归此（勿入 variants，防误伤真·Ethan）
                (r"\bLady\s+Shen\b", "沉夫人"),  # Lady Shen = Lady Hsin 误听；Shen 走 ctx 锚定，防误伤姓"沈"的人名
                (r"\bLady\s+Shen\b", "沈夫人"),
                (r"\bLady\s+Shen\b", "申夫人"),
                # 2026-10-12 本片声纹筛选版（#97 'this story about Shen'）：ASR 把
                #   Hsin 咬成 Shen，谷翻按姓氏直译'沈'。⚠ '沈'为常见姓氏，
                #   绝不裸键，只走参考行 \bShen\b 锚定（沿 Lady Shen 先例）。
                (r"\bShen\b", "沈"),
                (r"\bMoon Fox\b", "月狐"), (r"\bMoonfox\b", "月狐")),
           exclude=(r"\bLand Rover\b", r"\bDefender\b"),
           note="月狐岁主，官方全名 心月狐；独立指代用全名。3.7 双五星之一（2026-09-30 上线）。"
                "英文侧 Hsin（官方罗马音）与 Sheen（英文服旧译）并存，ASR 常咬成 Xin/Xhin/Shin/Sin/"
                "Hsien/Hshin/Hsi/Shen 等；机翻按字面把 Sheen 译成'光泽/闪光/光辉'，把 Hsin 译成"
                "'欣/新/馨/心/辛'，均靠参考行佐证归此。日语片'シ/シン様'归 心（见 JA_TERMS），"
                "3.6 片'聖/聖書'=清宵(セイショウ)非心，勿混。"
                "2026-09-25《寻心》片：Hsin's 被 ASR 拆成 he isen（谷翻'他伊森'），Lady Hsin "
                "误听 Lady Shen（谷翻'沉夫人'），均 ctx 锚定归此。"
                "exclude 防'Land Rover/Defender'等越野车品牌被 Rover 键误伤（漂泊者=Rover）。"),
    Entity("璇情", modes=("ko",), en="Xuanqing", ko="선정",
           category="角色",
           variants=(
               # 谷翻把人名 선정 按音译/字面义拆出的非词形态（韩语片专属，可无条件改）
               "宣杰", "宣殿", "Seonjeon", "Seonjeong", "宋正成", "宋善",
               "善善先生", "善善的妹妹", "善善如此说道", "善田先生", "善善",
               "善贞",  # ⚠ 2026-10-09 修复：ctx「善」→「璇情」会把「善贞」变成「璇情贞」，长键先吃
               "禅那",  # 선정=禅定 的佛经字面义，本片一律指璇情
           ),
           ctx=(
               # 「选择/善/选型…」是常用中文词，一律靠韩语参考行锚定（排 선정적/선정되다/선정하다）
               # 目标≠canonical 的（宣政台/选定的人/选姐姐）见 KO_CONTEXT 原生三元组。
               (_SEONJEONG_ANCHOR, "选择"),
               (_SEONJEONG_ANCHOR, "选型"),
               (_SEONJEONG_ANCHOR, "选拔"),
               (_SEONJEONG_ANCHOR, "善"),
           ),
           note="3.7 奇谭任务「璇心如月寄尘情」（韩语 기담 임무「달빛에 빌어보는 선정의 그리움」）"
                "新角色；百度百科：心月狐的共鸣者，生活在梦州边陲（后来的玄方地界）的少女，"
                "热情活泼又通情达理。韩语名 선정=璇情（璇=선，情=정）。"
                "谷翻把该人名按普通词/字面义译成 选择/善/禅那/宣杰/Seonjeon/宋正成 等，"
                "故常用词形态只走 ctx，韩语行锚定；선정적인(煽情)/선정되다/선정하다 是动词用法，"
                "锚定正则已用否定前查排除（#1015/#2570/#2612 实测）。"),
    Entity("锁暝", modes=("bi", "ja"), en="Suoming", ja="サメイ",
           category="角色/岁主",
           variants=(
               # --- 中文同音/音近（suǒ míng）---
               "锁瞑", "锁冥", "锁明", "锁名", "锁铭", "锁鸣",
               "所暝", "所冥", "索暝", "索冥", "琐暝", "琐明", "唢暝",
               # --- 既有机翻错形（BILINGUAL_TERMS/JA_TERMS 散落键聚合）---
               "苏明", "苏凌", "苏舒明", "索明", "水明",
               "Suming", "Suling", "Schuming", "Summit",
               # --- 英文 ASR 音近（Suoming 官方罗马音）---
               "Suoming", "Suo Ming", "Swoming", "Suomin", "Somin",
               "SUOMING", "suoming", "Suomimg", "Suorming",
               "Souming", "Suowming", "Suomming", "Suomiing",
               "Suomng", "Suomig", "Suomign", "Suomingg",
               # --- 日语片假名昵称 ---
               "サメイ", "サメちゃん", "サメィ", "鲛美",
               "鲫美酱", "鲛美酱", "鲇美酱", "萨米酱", "鲨鱼酱",
               "萨姆酱", "小沙姆", "萨梅伊", "鲛名酱",
               # --- 组合词：岁主/组织 ---
               "锁暝岁主", "Sentinel Suoming", "Suoming Sentinel",
           ),
           ctx=((r"\bswimming\b", "游泳"), (r"\bSuoming\b", "游泳"),
                (r"\bswimming\b", "苏明"), (r"\bSuoming\b", "锁瞑"),
                (r"\bSuoming\b", "锁冥"), (r"\bSuoming\b", "锁明"),
                (r"\bSuoming\b", "锁名"), (r"\bswimming\b", "锁瞑"),
                (r"\bSentinel\b", "锁暝"), (r"\bMoon\b", "锁暝"),
                (r"\bSuoming\b", "索明"), (r"\bSuoming\b", "水明")),
           note="鸣潮 3.7 双五星之二（2026-09-30 上线），岁主形态，专武'沉冥'。"
                "官方中文'锁暝'（目+冥，非'锁瞑'目+瞑）；执掌组织'谛天鉴'，"
                "所属'禁锁十契'。英文罗马音 Suoming；ASR 常咬成 Swoming/Suomin/Somin/"
                "Suomimg/Suorming/Souming/Suowming；机翻按 swimming 音近误译'游泳/苏明/索明/水明'。"
                "日语片昵称 サメイ/サメちゃん（鲨鱼酱/小沙姆），JA_TERMS 已收；"
                "本 Entity 聚合 bi+ja 双模式全部散落键，防遗漏。"
                "戒律：'游泳'为普通词绝不进 variants，只走 \\bswimming\\b 参考行锚定。"),
    Entity("阿列夫一", modes=("bi",), en="ALF1 / Alfan", ja="アルフワン",
           category="敌人/鸣式",
           variants=("阿尔夫", "ALF1", "LF1", "阿尔凡", "Alfan", "阿尔夫一人",
                     "阿尔夫一定", "阿尔法之一", "ALF one", "Alf one",
                     "ALF 1", "ALF", "Alf"),
           note="虚无鸣式/黑洞形象，官方中文=阿列夫一（2026-09-10 依官方访谈/库街区，"
                "'阿尔凡'沉淀作废）。键序：ALF one/ALF 1/ALF1 长键先行，防裸'Alf'咬半截。"
                "日语片由 JA_CONTEXT 的 /アルフ/ 佐证规则处理。"),
    Entity("阿达希尔", modes=("jpe",), en="Ardashir", ja="アルダシル",
           category="角色", note="终末地第二章。戒律：禁用裸键'达希尔'——长键先替换后"
           "短键二次命中得'阿阿达希尔'（terms-check 会报）。"),
    Entity("达妮娅", modes=("bi", "ja"), en="Denia", ja="ダーニャ",
           category="角色",
           variants=(
               # --- 既有机翻/ASR 乱形 ---
               "Dena", "Denia", "丹妮亚", "塔娜", "Tana", "Tenna",
               "丹雅",   # 谷翻错形（2026-10-12 鳴潮キャラPV鑑賞会 ja 片 cue5447，参考行ダーニャ佐证）
               # --- 中文同音/音近（dá nī yà）---
               "达妮亚", "丹妮娅", "达尼娅", "丹尼亚",
               "达妮雅", "塔妮娅", "达你娅", "达腻娅",
               "达妮押", "达妮鸭", "达妮丫",
               # --- 英文 ASR 音近（Denia）---
               "Denya", "Dennia", "Denny", "Deniya",
               "Danea", "Dania", "Denia's", "Denia`s", "Deina",
               "Denaia", "Deneia", "Denea", "Denia!",
               # --- 日文原形 ---
               "ダーニャ", "ダニア", "でにゃ",
           ),
           # 锚定 \bDa\b 收窄（2026-10-16 音乐反应片踩坑）：原 \bDa\b 大小写不敏感，
           # 会命中人声「da da」哼唱（参考行 da da. What is that song?），把
           # 达达。误并成 达达妮娅。加 负向前后顾：(?<!\bda\s) 排除前置 "da "、
           # (?!\s*da\b) 排除后置 " da"，两道都过才认作达妮娅昵称 Da（如 Da is / Da, / (Da)）。
           ctx=((r"(?<!\bda\s)\bDa\b(?!\s*da\b)", "爸爸"), (r"(?<!\bda\s)\bDa\b(?!\s*da\b)", "Da"), (r"(?<!\bda\s)\bDa\b(?!\s*da\b)", "达的"),
                (r"(?<!\bda\s)\bDa\b(?!\s*da\b)", "达。"), (r"\bmy wife\b", "娜娜"),
                (r"\bTenna\b", "特纳"), (r"\bDia\b", "迪亚"), (r"\bDia\b", "Dia"),
                (r"\bDenia\b", "达妮娅"), (r"\bDenia\b", "丹妮娅"),
                # "迪娜"=Denia/Dena 谷翻音近，通用译名易误伤他片，只走参考行 \bDena\b/\bDenia\b 佐证
                #   （2026-09-23 达妮娅3.3幕间二次校准沉淀，#8/117/613/625/682/731）
                (r"\bDena\b", "迪娜"), (r"\bDenia\b", "迪娜")),
           note="星炬学院虚质科学部学生，3.3 新五星（百度百科/萌娘百科/官方档案确认）。"
                "昵称 Denny/Dennia 机翻'丹尼/丹妮娅'亦归此；"
                "Daniela=丹妮拉 是另一人，勿收。真名达斯维达尼亚。"
                "主播昵称 Da(丹)：机翻常按口癖译成'爸爸'(#139/213/461/473/475/599)、残留英文"
                "Da/DA(#7/55/654/693/601/607)或咬出'达的'(#51/58)、'达。'(#15)，一律靠参考行"
                " \\bDa\\b 佐证归 达妮娅；裸'爸爸/Da/达的/达。'绝不进全局表。"
                "Tenna(#25/26/404)=Denia ASR 乱形（'Tenna is being Tenna'=达妮娅又开始了）；"
                "塔娜(Tana #255)亦 Denia；wife Nana 的 Nana=Denia(#30)；"
                "Dia/迪亚(#226/322 参考行 Dia)=Denia 昵称。"
                "Daniel(#376/378/695) 疑 Denia 乱形，仅侧车，不入全局。"
                "迪娜(#8/117/613/625/682/731 参考行 Dena)=谷翻音近，走 ctx 锚定归达妮娅；"
                "丹尼亚(尼)补完整形防'达妮娅亚'级联。"
                "2026-09-14 / 2026-09-23 《What's wrong with Denia's voice》"
                "(鸣潮3.3「自星海尽处回响」第三章幕间《在熔解的夜空下》Reaction) 沉淀。"
                "官方中文核对：达妮娅(萌娘/灰机/BWIKI)，全名达斯维达尼亚(先约电台EP《直到下次再见》)，"
                "中配戈昕宇/日配伊藤美来，PV《人类伪装指南》。"
                "2026-10-27 ABRAXAS 片 ASR `Donnie`→谷翻「唐尼」；Donnie 为常见西名，"
                "只做本片 sidecar，不入全局 ctx/裸键。"),
    Entity("陆·赫斯", modes=("bi",), en="Luuk Herssen",
           category="角色/星炬学院校医",
           variants=("路克", "Luke Herson", "卢克·赫尔森"),
           ctx=((r"Harrison", "老哈里森博士"),),
           note="星炬学院共鸣医疗科主执校医（百度百科/网易，英文 Luuk Herssen）。"
                "主播口音 ASR 常作 Dr. Luke/Dr. Harrison Senior(Herssen Senior 误听)："
                "#122'路克'、#211'老哈里森博士'（参考行 Harrison 佐证）。"
                "扁平表已有 Luke/Luuk/卢克 英文残留键。"
                "2026-09-14 达妮娅片二次校准沉淀。"),
    # --- 2026-09-14 What's wrong with Denia's voice（鸣潮 3.3 幕间「在熔解的夜空下」
    #     Reaction 片，775 cue）三次校准沉淀。官方依据：百度百科「达妮娅」「自星海尽处回响」、
    #     萌娘百科、官方知识库（娜波摩=残星会会长分身化名潜入星炬学院；
    #     娜斯塔霞=达妮娅挚友；拉贝尔学部；虚质=Void 官方词）与腾讯新闻/网易报道。---
    Entity("娜斯塔霞", modes=("bi",), en="Nastasha / Nastya",
           category="角色",
           variants=("Nastasha", "娜斯塔莎", "娜斯塔夏"),
           note="达妮娅挚友（星炬学院学生，三人组之一）。官方中文'娜斯塔霞'（多源：官方知识库/腾讯新闻OCR）。"
                "'娜塔莎'为常用译名不进全局，逐 cue 侧车。"),
    Entity("娜波摩", modes=("bi",), en="Naborr",
           category="角色/残星会会长分身",
           variants=("Neavor", "Naborr"),
           # ⚠ 2026-10-22 删除 (r"\bNvidia\b", "Nvidia")：Tenha 鸣潮全 EP reaction 片 #1643
           #   中文行原样 "Nvidia" 是主播谈角色性别（"要是他没有那个“他”"），被误改成娜波摩。
           #   仅保留“英伟达”译形锚定；裸 Nvidia 不再自动归娜波摩。
           ctx=((r"\bNvidia\b", "英伟达"),),
           note="残星会会长分身（百度百科/fandom：会长斯瓦茨洛的伪装之一），化名潜入星炬学院；"
                "3.3 幕间追逐环节敌人=娜波摩人偶。"
                "本片 ASR 乱形：#312/315 Nvidia(机翻'英伟达')靠参考行佐证归 娜波摩——"
                "裸'英伟达'绝不进全局表。#381 N'vora doll、#664 means Nora 也指娜波摩，勿与恩沃拉"
                "(N'avorora)混——'N'vora'全局键仍归恩沃拉，本片两处侧车覆盖。"),
    Entity("达斯维达尼亚", modes=("bi",),
           category="角色/达妮娅真名",
           variants=("Dasidia",),
           note="达妮娅全名，源自俄语'直到下次再见'(Dasvidaniya)（官方知识库/萌百）。"
                "#286 机翻'黛西迪亚'/ASR'Dasidia'统一。"),
    Entity("莫宁", modes=("bi",), en="Mornye",
           category="角色",
           variants=("Monier", "莫尼尔", "Mourn"),
           ctx=((r"\bMour\b", "莫尔"), (r"\bMou\b", "穆")),
           note="星炬学院隧者工学部教授/深空联合研究院工程师（百度百科·琳奈词条）。"
                "Mouier/Mor 变体已在扁平表；本片 #169 Professor Monier、#184 Professor Mona(侧车)。"
                "2026-10-24 补 Mourn（角色曲《若能触及群星》段落 ASR）。"
                "2026-10-27 ABRAXAS 片 ASR `Mona`→谷翻「莫娜」；与《原神》莫娜冲突，"
                "只做本片 sidecar，绝不入全局键。"),
    Entity("西格莉卡", modes=("bi",), en="Sigrika",
           category="角色",
           variants=("Sriraka", "Skrika", "Sigrika"),
           ctx=((r"\bSkrika\b", "尖叫"),),
           note="星炬学院学生、达妮娅挚友（3.2 共鸣者）。扁平表已有 Sigrika/Skiprika/Sria 等；"
                "短形 'Skip Ra'(#743)/'skip Raika'(#114) 为 ASR 文字游戏，侧车处理。"
                "Skrika(#109) ASR 形：谷翻把专名误作普通词'尖叫'，故裸键 'Skrika'->西格莉卡 补"
                "英文残留形，另用 ctx 参考行 \\bSkrika\\b 佐证把误译'尖叫'归 西格莉卡"
                "（'尖叫'通用词绝不入裸键）。2026-09-23 沉淀。"),
    Entity("残星会", modes=("bi",), en="Fractsidus",
           category="势力",
           variants=("Fracidus", "Fraidus", "Fraid", "Fractus", "fractus", "弗拉杜斯"),
           note="本片 #554 Fraidus'/Fracidus' door ASR 变体。2026-10-25 4.0 片补 Fraidus/Fraid/"
                "Fractus/弗拉杜斯，中文行统一归残星会。"),
    Entity("琳奈", modes=("bi",), en="Linny / Lenna",
           category="角色",
           variants=("Linn",),
           note="星炬学院预科班学生（百度百科）。扁平表已有 Linny/Lenny/林尼/莱妮丝；"
                "'Linn\\'s'(#736) 为所有格 ASR 残留。"),
    Entity("拉贝尔学部", modes=("bi",), en="Labell College",
           category="地点/星炬学院学部",
           variants=("Rebel Collegeg", "Rebel College", "拉贝尔学院"),
           note="星炬学院学部（官方知识库：'经拉贝尔学部判断其频率……'；官方角色档案："
                "'爱弥斯，星炬学院拉贝尔学部的隧者适格者'）。Rebel College 为 Labell College "
                "ASR 变体；2026-10-24 补无尾 g 形，勿归入上位机构『星炬学院』。"),
    Entity("天槎", modes=("bi",), en="Sky Ark",
           category="地点/鸣潮3.1",
           variants=("Skyark", "天空方舟"),
           note="稷廷研发的科研空间站，官方中文=天槎（天槎空间站），3.1 剧情《远航星》空间站段。"
                "ASR/谷翻变体 Sky Ark/Skyark/天空方舟；2026-10-27 3.1 精校实证"
                "（官方 3.1 内容说明/攻略/剧情文本）。旧扁平键 skyarch->天弧 已改回天槎。"),
    Entity("联运椎骨", modes=("bi",), en="Starward Riseway",
           category="地点/鸣潮3.1",
           variants=("Starwood Riseway", "星木驰道", "星木栈道", "喜达屋的起始道"),
           note="拉海洛区域，官方中文=联运椎骨（官方 3.0 区域名 Starward Riseway）；"
                "ASR Starwood Riseway、谷翻'喜达屋的起始道'；2026-10-27 3.1 精校实证。"),
    Entity("浮光林", modes=("bi",), en="Bjartr Woods",
           category="地点/鸣潮3.1",
           variants=("Bart Woods", "巴特伍兹", "巴特·伍兹"),
           note="拉海洛区域，官方中文=浮光林（官方 3.0 区域名 Bjartr Woods）；"
                "ASR Bart Woods、谷翻'巴特·伍兹'；2026-10-27 3.1 精校实证。"),
    Entity("老婆", modes=("bi",), category="术语",
           variants=("waifuss",),
           note="waifu 复数 ASR 形 waifuss(#43)；'收集 waifuss'=收集老婆。"
                "与 CONTEXT '外婆->老婆'(waifu) 同源，非角色名。"),
    Entity("残星会会长", modes=("bi",), en="Grand Architect",
           category="势力/角色",
           note="残星会(Fractsidus)首领。'伟大建筑师/伟大的建筑师/盛大建筑师'必须"
                "长键先行，否则被'大建筑师'(4字)键咬成'伟残星会会长'。"),
    # --- 2026-09-14 《The Masses Reacts to Arknights Music - Laterano》沉淀
    #     （英语原声 reaction 合集，216 cue，ZimaIsHere 频道；一次全句重译+二次官方核实）。---
    Entity("教堂步", modes=("ak",), en="Church Step / churchstep",
           category="曲风/术语",
           variants=("教会步堂",),
           note="拉特兰配曲曲风梗：圣咏合唱+管风琴融合电子低音，社区俗称'神父打碟'"
                "（多源：知乎 OST 盘点/B站曲师介绍；无官方中文名，音义兼顾取'教堂步'）。"
                "本片#2 机翻错形'教会步堂'(church of church step)归此。"
                "戒律：字面'教堂音乐'(church music)是普通词组，保持原义，勿动。"),
    Entity("The Pilgrimage", modes=("ak",), en="The Pilgrimage",
           category="曲目/众生行记OST",
           variants=("圣徒的旅程",),
           note="《明日方舟》SideStory『众生行记』(The Masses' Travels) OST 官方曲目"
                "（PRTS/塞壬唱片：众生行记OST 共 7 首：Touch of the Law / Halo Universalization"
                " / The Pilgrimage / Faith Enlightenment / The Birth / Underneath the Sanctuary"
                " / Somniomancer [null set]，均无官方中文名，保留英文）。本片#146 口播曲目，"
                "机翻'圣徒的旅程'归此。戒律：活动名官方中文=『众生行记』，曲目名勿意译。"),
    Entity("火焰纹章 风花雪月", modes=("ak",), en="Fire Emblem: Three Houses",
           category="作品",
           variants=("火焰纹章三宫",),
           note="主播联想曲出自《火焰纹章 风花雪月》（本片#207 机翻'火焰纹章三宫'系"
                "Three 直译+省略 Houses）。系列官方中文=《火焰之纹章》，社区/口语"
                "'火焰纹章'亦可，反应片保留口语形。"),
    Entity("拉特兰", modes=("ak",), en="Laterano",
           category="地点",
           variants=("拉特拉", "拉特拉诺"),
           note="政教合一圣城，萨科塔故土，OST 主创 Erik Castro（拉特兰电音）。"
                "'拉特拉'AK_KO 表已有，ak 模式补充防机翻拆名；'拉特兰教''拉特兰玩家'"
                "等组合词自然连带，无裸键误伤风险。"),
    Entity("莫斯提马", modes=("ak",), en="Mostima",
           category="干员/拉特兰",
           variants=("莫斯蒂玛", "莫斯提玛"),
           note="拉特兰六星术士，『吾导先路』核心角色，堕天使。本片#61 口播提及。"
                "ASR/机翻变体归官方译名'莫斯提马'（PRTS）。"),
    # --- 2026-09-14 鸣潮 3.6《I Built Jingran In 24 Hours》(Chiken 抽卡实况，460 cue)
    #     二次校准沉淀。官方依据：百度百科/游民星空/游侠(景燃=热熔长刃主C)、灰机wiki/
    #     fandom(绯雪=Hiyuki、余波珊瑚=Afterglow Coral、星声=Astrite)、3.7 前瞻(锁暝 Suoming
    #     与心月狐/心 Hsin 双五星)与 wuthering.gg(莫特斐=Mortefi、长刃=Broadblade)。---
    Entity("景燃", modes=("bi",), en="Jingran",
           category="角色/鸣潮3.6",
           variants=(
               # --- 既有拆词形 ---
               "晶荣", "景荣", "景隆", "静纶", "靖荣", "靖隆",
               # --- 中文同音/音近（jǐng rán）ASR 高频错形 ---
               "静然", "晶隆", "丁然", "井燃", "镜燃", "警燃",
               "景然", "景冉", "景染", "景焱", "景燃 ", "憬燃",
               "景澜", "景兰", "京燃", "惊燃", "净燃", "劲燃",
               # --- 英文 ASR 音近（Jingran）---
               "Jingran", "Jing Ran", "Jingrang", "Jingrong", "Jingron",
               "Jinran", "Jingram", "Jingrn", "Jingrana", "Jingan",
               "Jing-Ran", "Jingrran", "Jinglan",
               "Jing Ran!", "Jingran's", "Jingran`s",
           ),
           note="3.6 主推 5★ 热熔长刃主C（寻幽客）。既有 Jingron→景燃 走 CONTEXT_MAP"
                "（依赖参考行命中），本片机翻'晶荣/景荣/景隆/静纶'等拆词形无稳定英文佐证，"
                "补无条件键。ASR 音近覆盖'静然/晶隆/丁然/井燃/镜燃/景然/景冉/景染/景焱'等；"
                "英文侧 Jingran/Jing Ran/Jingrang/Jingrong/Jinran/Jingram 为常见拼错。"
                "戒律：'希幸/希希'是 Hiyuki(绯雪)非景燃，勿混。"),
    Entity("绯雪", modes=("bi",), en="Hiyuki", ja="ひゆき",
           category="角色",
           variants=(
               # --- 既有机翻叠字/同音拆字/旧 Entity 合并 ---
               "希希", "希幸", "Hiyoki", "桧纪",
               # --- 中文同音/音近（fēi xuě）ASR 高频错形 ---
               "非雪", "飞雪", "菲雪", "肥雪", "废雪",
               "绯雪酱", "绯雪大人", "绯雪峰", "绯薛", "绯雪儿",
               "费雪", "翡雪", "绯血", "绯鳕",
               # --- 英文 ASR 音近（Hiyuki）---
               "Hiyuki", "Hiuki", "Hyuki", "Hiyuki's",
               "Hiyuki`s", "Hi-yuki", "Hiyukii", "Hiyukie", "Hiyuki!",
               "Huyuki", "Hiyouki", "Hiyuke", "Hiyuk", "Hiyuuki",
               "Hiyuki-chan", "Hiyuki chan",
               # --- 日文原形 ---
               "ひゆき", "ヒユキ", "緋雪", "日雪",
               # --- 2026-09-27 学习库 confirmed 固化(#230/265)：Yuki 音近日名错形 ---
               "由纪",
           ),
           ctx=((r"\bYuki\b", "雪"), (r"\bYuki\b", "悠纪"), (r"\bHiyuki\b", "日雪"),
                (r"\bHiyuki\b", "桧雪"), (r"\bHiyuki\b", "绯雪")),
           note="3.3 共鸣者「灼樱巫女」，主播本命。扁平表已有 Hiyuki/Huki/kiuki/日雪/桧雪；"
                "本片机翻叠字'希希'(my Hyuki)归此，'希幸'亦 Hiyuki（同音拆字）。"
                "ASR 音近错形：'绯雪'易咬成'非雪/飞雪/菲雪/肥雪/废雪/绯薛/费雪/翡雪/绯血/绯鳕'；"
                "英文侧 Hiyuki 易咬成 Hiuki/Hyuki/Huyuki/Hiyouki/Hiyuke/Hiyuuki。"
                "戒律：裸'Yuki'为常用日名不入全局，只走 \\bYuki\\b 参考行锚定。"),
    Entity("星声", modes=("bi",), en="Astrite",
           category="术语/货币",
           variants=("星石",),
           note="鸣潮高级抽卡货币官方中文名=星声（百度百科/fandom）。机翻常误作'星石'。"),
    Entity("余波珊瑚", modes=("bi",), en="Afterglow Coral",
           category="术语/货币",
           variants=("余辉珊瑚",),
           note="重复抽取返还货币，官方中文=余波珊瑚（fandom/17173 兑换指南）。机翻"
                "'余辉珊瑚'归此；勿与'星声'混。"),
    Entity("热熔", modes=("bi",), en="Fusion",
           category="术语/元素",
           ctx=((r"\bfusion\b", "融合"), (r"\bfusion\b", "熔合")),
           note="鸣潮六元素之一 Fusion 官方中文=热熔（火系，景燃即热熔）。机翻按本意误作"
                "'融合'。戒律：'融合'是普通词，绝不作裸键进全局表，只能靠参考行 \\bfusion\\b 锚定。"),
    Entity("长刃", modes=("bi",), en="Broadblade",
           category="术语/武器",
           variants=("Broadblade",),
           ctx=((r"\bbroadblade\b", "大剑"),),
           note="鸣潮武器类型 Broadblade 官方中文=长刃（景燃武器；wuthering.gg/dailiantong 确认）。"
                "机翻易按 Genshin 习惯误作'大剑'。'大剑'为泛用词，只走参考行 \\bbroadblade\\b 锚定。"),
    # --- 2026-09-20 增补：鸣潮 3.7「镜锁妄世，心照红尘」前瞻官方名词（9月30日上线）
    #     依据：wuwa.uk/zh/articles/wuwa-3-7-preview-2026、搜狐 1078561190、TapTap 前瞻直播总结 850470334392963021。
    #     说明：3.7 尚未上线，暂无 ASR/机翻错形沉淀；先登记 canonical+en 元数据，
    #     上线后 reaction 片出现错形再增量追加 variants。 ---
    Entity("梦枢天罗", modes=("bi",), category="地点/新地区",
           variants=("梦书天罗", "梦殊天罗", "梦淑天罗", "门枢天罗",
                     "梦树天罗", "梦墅天罗", "梦枢天锣", "梦枢添罗",
                     "梦枢天萝", "梦舒天罗", "孟枢天罗", "梦枢天洛"),
           note="鸣潮 3.7 新地区（前瞻直播官方名，与梦州城/梦州华亭同域）。"
                "3.7 版本主题「镜锁妄世，心照红尘」核心探索区。"
                "ASR 音近错形：'梦枢'易咬成'梦书/梦殊/梦淑/梦树/梦墅/梦舒/孟枢'；"
                "'天罗'易咬成'天锣/添罗/天萝/天洛'。"),
    Entity("心影映花", modes=("bi",), category="玩法/常驻",
           ctx=((r"\bHsin\b", "心影印花"), (r"\bHsin\b", "心影映华"),
                (r"\bHsin\b", "心影应花"), (r"\bHsin\b", "心影印画"),
                (r"\bgameplay\b", "心影映花"), (r"\bHsin\b", "心影映化")),
           note="鸣潮 3.7 新增常驻玩法（前瞻直播官方名）。"
                "戒律：'心影映花'字面为通用词组，只走参考行 Hsin/gameplay 锚定，"
                "机翻'心影印花/心影映华/心影应花'等错形归此，绝不作裸键入全局表。"),
    Entity("玉阙玄华", modes=("bi",), category="武器/心月狐专武",
           variants=("玉缺玄华", "玉雀玄华", "玉阙宣华", "玉阙玄化",
                     "雨阙玄华", "玉阙悬华", "玉阙玄画", "玉阙玄花",
                     "玉阙玄桦", "玉缺悬华", "御阙玄华", "玉阙旋华"),
           ctx=((r"\bHsin\b", "玉阙玄华"), (r"\bweapon\b", "玉阙玄华"),
                (r"\bsignature weapon\b", "玉阙玄华")),
           note="心月狐（Hsin）3.7 专属武器（前瞻直播官方名）。"
                "ASR 音近错形：'玉阙'易咬成'玉缺/玉雀/雨阙/御阙'；"
                "'玄华'易咬成'宣华/玄化/悬华/玄画/玄花/玄桦/旋华'。"),
    Entity("沉冥", modes=("bi",), category="武器/锁暝专武",
           variants=(),
           ctx=((r"\bSuoming\b", "沉溟"), (r"\bSuoming\b", "沈冥"),
                (r"\bSuoming\b", "深冥"), (r"\bSuoming\b", "沉名"),
                (r"\bSuoming\b", "深名"), (r"\bSuoming\b", "沉明"),
                (r"\bSuoming\b", "沈明"), (r"\bSuoming\b", "深溟"),
                (r"\bweapon\b", "沉冥"), (r"\bsignature weapon\b", "沉冥")),
           note="锁暝（Suoming）3.7 专属武器（前瞻直播官方名）。"
                "戒律：'沉冥'为古汉语常用词（沉冥于思绪），不可作裸键入全局表，"
                "只在参考行出现 Suoming/weapon 时才把'沉溟/沈冥/深冥/沉名/深名/沉明/沈明/深溟'等错形归此。"),
    Entity("凝月辉途", modes=("bi",), category="活动/限时",
           variants=("凝月辉图", "凝月晖途", "凝月辉涂", "宁月辉途",
                     "凝乐辉途", "凝月回途", "凝月惠途", "凝月绘途",
                     "宁月晖途", "凝月辉土", "凝月辉屠", "凝月辉图 "),
           note="鸣潮 3.7 限时活动（前瞻直播官方名）。"
                "ASR 音近错形：'凝月'易咬成'宁月/凝乐'；'辉途'易咬成'辉图/晖途/辉涂/回途/惠途/绘途/辉土/辉屠'。"),
    Entity("团团勇者大乱斗", modes=("bi",), category="活动/特别",
           variants=("团团勇者大乱逗", "团团庸者大乱斗", "团团用者大乱斗",
                     "团团永者大乱斗", "团团勇者大乱抖", "团团涌者大乱斗",
                     "团团勇者大乱陡", "团团勇折大乱斗", "团团庸者大乱逗"),
           note="鸣潮 3.7 特别活动（前瞻直播官方名）。"
                "ASR 音近错形：'勇者'易咬成'庸者/用者/永者/涌者/勇折'；'乱斗'易咬成'乱逗/乱抖/乱陡'。"),
    Entity("朝月赠礼", modes=("bi",), category="活动/特别",
           variants=("朝月赠里", "潮月赠礼", "朝阳赠礼", "朝月赠利",
                     "朝月增礼", "朝月赠丽", "潮月赠里", "朝月赠例",
                     "朝月赠李", "抄月赠礼", "朝乐赠礼"),
           note="鸣潮 3.7 特别活动（前瞻直播官方名）。"
                "ASR 音近错形：'朝月'易咬成'潮月/朝阳/抄月/朝乐'；'赠礼'易咬成'赠里/赠利/增礼/赠丽/赠例/赠李'。"),
    Entity("梦枢心相由心生", modes=("bi",), category="主线/章节",
           note="鸣潮 3.7 新主线章节名（前瞻直播官方名）。"),
    Entity("璇心如月寄尘情", modes=("bi",), category="奇谭",
           note="鸣潮 3.7 新奇谭章节名（前瞻直播官方名）。"),
    # --- 2026-09-20 增补（二次校准）：鸣潮 3.7「镜锁妄世，心照红尘」补充实体。
    #     依据：wuwa.uk/zh/articles/wuwa-3-7-preview-2026、taptap 850470334392963021、
    #     233乐园 2095401601570680832（心月狐/锁暝实机演示）、163.com L77JK0RL05561FYA
    #     （3.7 定档 9/30、梦枢天罗、心之井、同奏/变奏、奇谭任务、团团勇者大乱斗、
    #      无音消除、Wuwa Tappo、轨迹回顾、月追祭/追月节回看、声骸堆叠、编队 20 组）。 ---
    Entity("镜锁妄世，心照红尘", modes=("bi",), category="版本/副标题",
           variants=("镜锁妄世心照红尘", "镜锁妄世 心照红尘",
                     "境锁妄世，心照红尘", "镜锁妄世，心照宏尘",
                     "镜锁妄世，心照红尖"),
           note="鸣潮 3.7 版本副标题（前瞻直播官方名，2026-09-30 上线）。"
                "日文原句『鏡に鎖す妄世、心で照らす紅塵』。"),
    Entity("溢彩荧辉", modes=("bi",), category="武器/音感仪·五星",
           variants=("溢彩荧晖", "溢彩萤辉", "溢采荧辉", "逸彩荧辉",
                     "溢彩银辉", "溢彩迎辉"),
           ctx=((r"\bweapon\b", "溢彩荧辉"), (r"\b5-star\b", "溢彩荧辉")),
           note="鸣潮 3.7 新五星音感仪官方名（与心月狐专武『玉阙玄华』同批上线，"
                "非角色绑定专武）。ASR 音近错形：'荧辉'易咬成'荧晖/萤辉/银辉/迎辉'。"),
    Entity("心之井", modes=("bi",), category="玩法/心域",
           ctx=((r"\bwell\b", "心之井"), (r"\bHsin\b", "心之井"),
                (r"\bheart domain\b", "心之井")),
           note="鸣潮 3.7 新玩法：稳定『心域』并解谜的机制（前瞻直播官方名，"
                "梦枢天罗深层区域）。戒律：'心之井'字面通用，只走 well/Hsin/heart domain 锚定。"),
    Entity("万相分形", modes=("bi",), category="异能/心月狐",
           variants=("万相分型", "万象分形", "万相份形", "万像分形"),
           note="心月狐（心）3.7 官方异能名（前瞻直播/角色演示）。"),
    Entity("十重契", modes=("bi",), category="异能/锁暝",
           variants=("十重器", "十重起", "十重气", "石重契", "十封印"),
           ctx=((r"\bSuoming\b", "十重契"), (r"\bResonance\b", "十重契")),
           note="锁暝 3.7 官方异能名（前瞻直播/角色演示）。"
                "戒律：'十重契'字面通用度低但仍走 Suoming/Resonance 锚定，防误伤'十重契约'等长句。"),
    Entity("同奏", modes=("bi",), category="共鸣模式/心月狐",
           ctx=((r"\bHsin\b", "同奏"), (r"\bResonance Mode\b", "同奏"),
                (r"\bsync\b", "同奏")),
           note="心月狐 3.7 独有共鸣模式之一（与『变奏』成对，前瞻直播官方名）。"
                "戒律：'同奏'为通用动词（同奏一曲），只走 Hsin/Resonance Mode/sync 参考行锚定。"),
    Entity("变奏", modes=("bi",), category="共鸣模式/心月狐",
           ctx=((r"\bHsin\b", "变奏"), (r"\bResonance Mode\b", "变奏"),
                (r"\bvariation\b", "变奏")),
           note="心月狐 3.7 独有共鸣模式之一（与『同奏』成对，切换时触发；前瞻直播官方名）。"
                "戒律：'变奏'为通用音乐术语，只走 Hsin/Resonance Mode/variation 参考行锚定。"),
    Entity("轨迹回顾", modes=("bi",), category="系统/剧情回看",
           variants=("轨迹回看", "轨跡回顾", "轨迹回頋"),
           ctx=((r"\bstory recall\b", "轨迹回顾"), (r"\bplayback\b", "轨迹回顾"),
                (r"\bplot\b", "轨迹回顾")),
           note="鸣潮 3.7 新增剧情回看功能官方名（首发覆盖 Ver1.1~Ver1.3，后续追加）。"),
    Entity("Wuwa Tappo", modes=("bi",), category="周边/桌宠软件",
           variants=("呜哇tap o", "呜哇Tappo", "呜哇塔珀", "呜哇 塔波",
                     "Wuwa Tapo", "Wuwa Tap po", "WuwaTappo", "呜哇拖波"),
           note="鸣潮官方主题桌宠软件（3.7 前瞻直播公布，永久免费上线）。"
                "'呜哇' = Wuwa（鸣潮海外简称）ASR 音译；'tap o' 为 Tappo 拆字。"),
    Entity("声骸堆叠", modes=("bi",), category="系统优化/声骸",
           variants=("声骸叠加", "音骸堆叠", "声骸重合"),
           ctx=((r"\bEcho\b", "声骸堆叠"), (r"\bstack\b", "声骸堆叠")),
           note="鸣潮 3.7 声骸系统优化：满足条件后声骸可堆叠，背包空间实际增加。"
                "戒律：只走 Echo/stack 参考行锚定。"),
    Entity("合鸣效果", modes=("bi",), category="系统/声骸",
           variants=("合鸣效应", "和鸣效果", "共鸣效果套装"),
           ctx=((r"\bSonata\b", "合鸣效果"), (r"\bsonata set\b", "合鸣效果"),
                (r"\bEcho set\b", "合鸣效果")),
           note="鸣潮声骸套装系统官方名（对应英文 Sonata）。3.7 新增三种全新合鸣效果。"
                "戒律：'合鸣效果'为专有名词但'共鸣'为通用机制词，只走 Sonata/Echo set 锚定。"),
    # --- 2026-09-20 增补：明日方舟 ×《女神异闻录3 Reload》联动 SideStory「月行水上」
    #     （9月4日已上线）。依据：ak.hypergryph.com/news/9681.html、百度百科「结城理」、
    #     233乐园 2095371353272860672、新浪新闻 5337291081910764。 ---
    Entity("结城理", modes=("ak",), en="Yuki Makoto", ja="結城理",
           category="干员/联动·P3R",
           variants=(
               # --- 同音字（jié chéng lǐ）ASR 高频错形 ---
               "洁城理", "杰城理", "截城理", "节城理", "解城理", "捷城理",
               "结城礼", "结城利", "结城黎", "结城璃", "结城莉", "结诚理",
               "结成理", "结城李", "结城凛", "结城里", "结城里程",
               "悠城理", "由城理", "结城理世", "结城真理", "结城 理",
               # --- 英文 ASR 音近（Yuki Makoto）---
               "Yuki Makoto", "Makoto Yuki", "Yuki Makato", "Yuki Mokoto",
               "Yuki Makto", "Youki Makoto", "Yuki Machoto", "Yuki Makotto",
               "Yuki Makot", "Yuki Macoto", "Yuki Makotoh", "Makato Yuki",
               # --- 日文原形 ---
               "結城理", "結城 理", "ゆうき まこと", "ユウキ マコト",
           ),
           ctx=((r"\bMakoto\b", "真琴"), (r"\bMakoto\b", "真斗"),
                (r"\bMakoto\b", "诚"), (r"\bMakoto\b", "真"),
                (r"\bYuki\b", "雪"), (r"\bYuki\b", "由纪"),
                (r"\bYuki\b", "悠纪"), (r"\bSEES\b", "西兹"),
                (r"\bSEES\b", " sees")),
           note="明日方舟首位六星男干员，联动《女神异闻录3 Reload》主角（P3 SEES 成员）。"
                "双人格面具'俄耳甫斯/塔纳托斯'三段替身机制。ASR/机翻常把'结城理'咬成"
                "'结城里/结成理/结城李/结城凛/悠城理/洁城理/杰城理'等；英文原名 Yuki Makoto"
                "（日漫姓氏前置）。ctx 处理'真琴/真斗/诚/真'等 Makoto 常见机翻义项，"
                "'雪/由纪/悠纪'等 Yuki 常见日名机翻，仅在参考行佐证时归此。"
                "'SEES'为 P3 特别课外活动部（Specialized Extracurricular Execution Squad），"
                "机翻常拆字成'西兹/sees'。"),
    Entity("埃癸斯", modes=("ak",), en="Aigis", ja="アイギス",
           category="干员/联动·P3R",
           variants=(
               # --- 中文同音/音近字（āi guǐ sī）ASR 高频错形 ---
               "埃吉斯", "艾癸斯", "艾吉斯", "埃基斯", "埃癸期", "埃及斯",
               "埃癸丝", "埃癸思", "唉癸斯", "挨癸斯", "埃鬼斯", "埃贵斯",
               "埃归斯", "埃桂斯", "埃硅斯", "爱癸斯", "艾贵斯", "埃诡斯",
               "埃癸私", "埃癸司", "埃轨斯", "矮癸斯", "埃瑰斯", "爱吉斯",
               # --- 英文 ASR 音近（Aigis / Aegis）---
               "Aigis", "Aegis", "Aigys", "Aiges", "Igis", "Eigis",
               "Aigi", "Aygis", "Aegys", "Iggis", "Aighis", "Aigiss",
               "Ai-gis", "Eegis", "Ageis", "Aegos",
               # --- 日文原形 ---
               "アイギス", "哀癸斯",
           ),
           note="明日方舟 ×《女神异闻录3 Reload》联动五星干员（P3 SEES 成员，机器人少女）。"
                "官方中文'埃癸斯'（Aigis 希腊神话宙斯神盾）；机翻常按 Aegis 直译'埃吉斯/艾吉斯/爱癸斯'。"
                "ASR 音近错形覆盖'埃鬼斯/埃贵斯/埃归斯/埃桂斯/埃硅斯'等同音字，"
                "英文侧 Aigis/Aegis 及 Aigys/Igis/Eigis/Aygis 等常见拼错。"),
    Entity("岳羽由加莉", modes=("ak",), en="Yukari Takeba", ja="岳羽ゆかり",
           category="干员/联动·P3R",
           variants=(
               # --- 姓氏'岳羽'同音/音近（yuè yǔ）---
               "月羽由加莉", "乐羽由加莉", "越羽由加莉", "岳雨由加莉",
               "岳宇由加莉", "岳玉由加莉", "岳瑜由加莉", "岳裕由加莉",
               "岳羽由加丽", "岳羽有加莉", "岳羽尤加莉", "岳羽由加利",
               "岳羽由香里", "岳羽由香莉", "岳羽优加莉", "岳羽悠加莉",
               "岳羽有加丽", "岳羽尤佳莉", "岳羽由嘉莉", "岳羽由佳莉",
               "岳羽佑加莉", "岳羽由家莉", "岳羽由加理", "岳羽优佳莉",
               "岳羽有加利", "岳羽由加梨", "岳羽由加篱",
               # --- 英文 ASR 音近（Yukari Takeba）---
               "Yukari Takeba", "Takeba Yukari", "Yukali", "Yukary",
               "Yokari", "Yukarei", "Yukari Takaba", "Yukali Takeba",
               "Yukarri", "Yukarii", "Youkari", "Yukari Takehara",
               "Yukali Takeba", "Yukari Takeha", "Takeba Yukali",
               # --- 日文原形 ---
               "岳羽ゆかり", "岳羽ユカリ", "たけば ゆかり", "タケバ ユカリ",
           ),
           ctx=((r"\bYukari\b", "雪里"), (r"\bYukari\b", "雪莉"),
                (r"\bYukari\b", "由香里"), (r"\bYukari\b", "雪梨"),
                (r"\bTakeba\b", "竹庭"), (r"\bTakeba\b", "武庭")),
           note="明日方舟 ×《女神异闻录3 Reload》联动五星干员（P3 SEES 成员，弓箭手）。"
                "官方中文'岳羽由加莉'；'ゆかり'机翻易作由加丽/有加莉/尤加莉/由加利/由香里/优加莉/由佳莉，"
                "均归此。日文汉字形'岳羽ゆかり'亦一并统一。ASR 姓氏'岳羽'音近'月羽/乐羽/越羽/岳雨/岳宇'；"
                "英文侧 Yukali/Yukary/Yokari/Takaba 为常见拼错。ctx 处理'雪里/雪莉/由香里/竹庭'等"
                "机翻按普通日名/字面拆译的错形，仅在参考行佐证时归此。"),
    Entity("虎狼丸", modes=("ak",), en="Koromaru", ja="コロマル",
           category="干员/联动·P3R",
           variants=(
               # --- 中文同音/音近（hǔ láng wán）---
               "虎狼凡", "虎狼凡丸", "虎郎丸", "胡狼丸", "虎狼圆",
               "虎朗丸", "虎浪丸", "户狼丸", "浒狼丸", "虎狼完",
               "虎狼玩", "虎狼晚", "虎狼万", "虎狼宛", "虎狼婉",
               "狐狼丸", "古狼丸", "苦狼丸", "虎螂丸", "虎狼皖",
               "浒朗丸", "湖狼丸", "呼狼丸", "琥狼丸", "虎琅丸",
               # --- 英文 ASR 音近（Koromaru）---
               "Koromaru", "Kolomaru", "Koramaru", "Coromaru", "Koromaro",
               "Kuro-maru", "Collomaru", "Koromaruu", "Korumaru",
               "Koromarou", "Koromalo", "Koromalu",
               "Koromari", "Koromally", "Coramaru",
               # --- 日文原形 ---
               "コロマル", "ころまる", "虎狼マル",
           ),
           note="明日方舟 ×《女神异闻录3 Reload》联动一星赠送干员（P3 SEES 成员，忠犬）。"
                "官方中文'虎狼丸'。ASR 常把'丸'咬成'凡/圆/完/玩/晚/万/宛/婉/皖'；"
                "'虎'音近'浒/琥/湖/呼'；'狼'音近'郎/朗/浪/螂/琅'；整体误听'胡狼丸/狐狼丸/古狼丸'。"
                "英文侧 Koromaru 常见拼错 Kolomaru/Koramaru/Coromaru/Koromaro。"),
    Entity("月行水上", modes=("ak",), en="Moonlit Waters",
           category="活动/SideStory",
           variants=("月行水山", "越行水上", "月形水上", "月行税上",
                     "月形水山", "乐行水上", "月型水上", "月行水尚",
                     "月行水赏", "跃行水上", "越形水上", "月行谁上",
                     "月幸水上", "月行瑞上", "月形水赏", "岳行水上"),
           note="明日方舟 × P3R 联动 SideStory 活动名（官方中文'月行水上'，2026-09-04 开启）。"
                "对应限时寻访=圣城春日学生寻访。"
                "ASR 音近错形：'月行'易咬成'越行/乐行/跃行/月形/月型/月幸/岳行'；"
                "'水上'易咬成'水山/水尚/水赏/谁上/瑞上'。"),
    Entity("圣城春日学生寻访", modes=("ak",),
           category="活动/限时寻访",
           variants=("圣城春日生寻访", "圣城春日学生巡访", "圣城春日学生询问",
                     "圣城春日学生训访", "圣城春日学生寻防", "圣城春日学生寻方",
                     "圣城春日学生巡防", "圣成春日学生寻访", "圣城春日学生讯访",
                     "圣城春日学生巡房", "圣城春日学生寻坊", "圣城春瑞学生寻访"),
           note="明日方舟 × P3R 联动限时寻访（卡池）官方名。'圣城春日'为 P3R 中的私立月光馆学园都市名，"
                "'圣城春日学生寻访'=结城理/埃癸斯/岳羽由加莉/虎狼丸联动卡池。"
                "ASR 音近错形：'寻访'易咬成'巡访/询问/训访/寻防/寻方/巡防/讯访/巡房/寻坊'；"
                "'圣城'易咬成'圣成'；'春日'易咬成'春瑞'。"),
    Entity("女神异闻录3 Reload", modes=("ak",), en="Persona 3 Reload", ja="ペルソナ3 リロード",
           category="作品",
           variants=("女神异闻录3重制版", "女神异闻录3 reload", "女神异闻录3RELOAD",
                     "Persona3 Reload", "P3R", "女神異聞錄3 Reload",
                     "女神异闻录三 Reload", "女神异闻录3: Reload", "女神异闻录III Reload",
                     "女神异闻录3R", "Persona3Reload", "女神异闻3 Reload",
                     "女神异闻录3 重制", "女神异闻录3 Reloaded", "女神异闻录3 reloaded",
                     "女神异闻录3重制", "女神异闻录 3 Reload", "Persona 3 R"),
           note="ATLUS 出品 JRPG，2024 年重制版；明日方舟 2026-09-04 联动原作。"
                "官方中文'女神异闻录3 Reload'（Reload 保留英文，非'重制版'）。"
                "ASR 常见错形：数字'3'被读成'三/III'；'Reload'被咬成'reloaded/重制'；"
                "空格丢失'Persona3Reload'。"),
    # --- 2026-09-20 增补：终末地 1.4「向渊行」（7月16日）+ 1.5「雪淞幽梦」（9月2日）
    #     依据：endfield.hypergryph.com、TapTap 官方前瞻 826747279820983499、
    #     百度百科「向渊行」、fz.wiki「干员/梨诺」、end.canmoe.com「梨诺」。 ---
    Entity("梨诺", modes=("endo", "jpe"), en="Liino",
           category="干员",
           variants=(
               # --- 中文同音/音近（lí nuò）ASR 高频错形 ---
               "利诺", "莉诺", "梨络", "梨落", "李诺", "里诺", "黎诺",
               "梨諾", "离诺", "璃诺", "丽诺", "犁诺", "鲤诺", "栗诺",
               "梨那", "梨娜", "梨糯", "梨洛", "梨珞", "梨箩", "梨萝",
               "莉糯", "梨讷", "利那", "丽那", "礼诺", "理诺",
               # --- 英文 ASR 音近（Liino）---
               "Liino", "Lino", "Leeno", "Lyno", "Rino", "Lynor",
               "Liinno", "Liano", "Linuo", "Li-Nuo", "Lieno", "Linoa",
               "Riino", "Linoe", "Leano", "Linao", "Liinoo", "Liina",
           ),
           note="终末地向渊行下半六星辅助干员，官方叙事《梨诺：心与星的焦点》。"
                "ASR/机翻常把'梨诺'咬成'利诺/莉诺/李诺/里诺/黎诺/离诺/璃诺/丽诺/犁诺/鲤诺'；"
                "'诺'音近'那/娜/糯/洛/珞/箩/萝/讷'；英文 Liino（双 i）易漏为 Lino 或误作 Rino/Leeno/Lyno。"
                "戒律：'李娜/莉娜/黎娜'为常见中文人名不入表，防误伤；ctx 处理'丽诺/黎诺/Lino/Rino'等"
                "英文参考行佐证场景。"),
    Entity("北部禁区", modes=("endo", "jpe"),
           category="地点/武陵",
           variants=("北部禁地", "北方禁区", "北区禁区", "贝部禁区",
                     "北部金区", "北部仅区", "北部近区", "北部谨区",
                     "北部浸区", "北部进区", "北部晋区", "北部锦区"),
           note="终末地向渊行版本开放的武陵新区域（官方名'北部禁区'，与'武陵应龙关'同为新区域）。"
                "ASR 音近错形：'北部'易咬成'贝部'；'禁区'易咬成'金区/仅区/近区/谨区/浸区/进区/晋区/锦区'。"),
    Entity("余晖未却", modes=("endo", "jpe"),
           category="章节/主线",
           variants=("余辉未却", "余晖未怯", "余晖未雀", "余晖未确",
                     "余晖未阙", "余辉未怯", "余晖微却", "余晖喂却",
                     "余晖未缺", "鱼晖未却", "余惠未却", "余晖未阕",
                     "余晖为却", "余晖未榷", "余辉未阕"),
           note="终末地向渊行主线第二章进程VII 官方章节名'余晖未却'（武陵决战篇）。"
                "ASR 音近错形：'余晖'易咬成'余辉/鱼晖/余惠'；'未却'易咬成'未怯/未雀/未确/未阙/微却/喂却/未缺/未阕/为却/未榷'。"),
    Entity("蚀影", modes=("endo", "jpe"),
           category="敌人系列",
           variants=("食影", "蚀阴", "蚀穎"),
           ctx=((r"\bEclipse\b", "日蚀"), (r"\bShadow\b", "黑影"),
                (r"\bEclipsed\b", "日蚀"), (r"\bUmbral\b", "暗影"),
                (r"\bUmbra\b", "暗影"), (r"\benemy\b", "蚀影"),
                (r"\bEclipse enemy\b", "蚀影")),
           note="终末地向渊行新敌人系列（官方名'蚀影系列'）。"
                "戒律：'蚀影'是特定敌人名，不可裸键映射通用词；日蚀/黑影/暗影等仅在参考行"
                "Eclipse/Shadow/Umbral/Umbra/enemy 佐证时归此。"),
    Entity("相伴庆典", modes=("endo", "jpe"),
           category="活动/版本",
           variants=("相伴盛殿", "想伴庆典", "相办庆典", "想办庆典",
                     "乡伴庆典", "香伴庆典", "相伴青典", "相伴清典",
                     "相拌庆典", "相伴庆点", "向伴庆典", "湘伴庆典"),
           note="终末地向渊行版本官方庆典活动名（1.4 半周年，与向渊行核心章节同步开启）。"
                "ASR 音近错形：'相伴'易咬成'想伴/相办/想办/乡伴/香伴/相拌/向伴/湘伴'；"
                "'庆典'易咬成'盛殿/青典/清典/庆点'。"),
    Entity("遥望", modes=("endo", "jpe"),
           category="武器/六星",
           ctx=((r"\b6-star weapon\b", "远望"), (r"\bsix-star weapon\b", "远望"),
                (r"\bweapon\b", "遥望远"), (r"\bYao Wang\b", "遥望"),
                (r"\blong-range weapon\b", "远望"), (r"\bfree weapon\b", "远望"),
                (r"\b6\s*★\s*weapon\b", "远望"), (r"\bsignature weapon\b", "远望")),
           note="终末地向渊行版本赠送的六星武器官方名'遥望'。"
                "戒律：'遥望'为普通动词，只走参考行 6-star weapon / weapon / Yao Wang 锚定，"
                "机翻'远望/遥望远'等错形归此，绝不作裸键入全局表。"),
    Entity("嵌晶玉", modes=("endo", "jpe"),
           category="道具/材料",
           variants=("嵌晶石", "崁晶玉", "嵌晶钰", "谦晶玉", "欠晶玉",
                     "千晶玉", "浅晶玉", "嵌金玉", "嵌精玉", "嵌晶羽",
                     "嵌晶瑜", "嵌晶御", "嵌晶裕", "嵌晶郁", "歉晶玉"),
           note="终末地向渊行版本官方道具/材料名'嵌晶玉'（云·终末地相关）。"
                "ASR 音近错形：'嵌'易咬成'崁/谦/欠/千/浅/歉'；'晶'易咬成'金/精'；"
                "'玉'易咬成'钰/羽/瑜/御/裕/郁'。"),
    Entity("云·终末地", modes=("endo", "jpe"), en="Cloud Endfield",
           category="服务/云游戏",
           variants=("云终末地", "云·末地", "云端终末地", "云·终墨地",
                     "云·终陌地", "云·终没地", "云·中末地", "云·终末底",
                     "云·终末帝", "CloudEndfield", "云 终末地", "云·終末地"),
           note="终末地云游戏服务官方名'云·终末地'（向渊行版本同步开启云测试）。"
                "ASR 音近错形：'终末'易咬成'终墨/终陌/终没/中末/终末底/终末帝'；"
                "英文侧 CloudEndfield（空格丢失）；分隔符'·'易被 ASR 吞掉。"),
    Entity("阿莱克琉斯千夫长", modes=("endo", "jpe"), en="Alektios Chiliarch",
           category="BOSS",
           variants=("阿莱克琉斯将军", "阿莱克流斯千夫长", "阿莱克琉斯千人长",
                     "阿莱克鲁斯千夫长", "阿莱克留斯千夫长", "阿莱克硫斯千夫长",
                     "阿莱克柳斯千夫长", "阿莱克琉斯千父长", "阿莱克琉斯前夫长",
                     "阿莱克琉斯千服长", "阿莱克琉斯千付长", "阿莱克琉斯千府长",
                     "阿莱克雷乌斯千夫长", "阿莱克琉斯千妇长", "阿莱克纽斯千夫长",
                     "阿莱克琉斯千夫涨", "阿莱克琉斯千夫章"),
           note="终末地向渊行版本 BOSS 官方全称'阿莱克琉斯千夫长'（1.4 最终 BOSS，"
                "'千夫长'=罗马军制 Chiliarch，非'将军/千人长'）。旧表已收'阿莱克琉斯'短键，此处补全头衔。"
                "ASR 音近错形：'阿莱克琉斯'易咬成'阿莱克鲁斯/阿莱克留斯/阿莱克硫斯/阿莱克柳斯/"
                "阿莱克雷乌斯/阿莱克纽斯'；'千夫长'易咬成'千父长/前夫长/千服长/千付长/千府长/千妇长/千夫涨/千夫章'。"),
    # --- 2026-09-20 增补：鸣潮 3.6-3.7 活跃角色（尚无独立 Entity，散在 BILINGUAL_TERMS）---
    Entity("洛瑟菈", modes=("bi",), en="Lucilla",
           category="角色/星炬学院校长",
           variants=(
               # --- 既有机翻音译残留 ---
               "Lucilla", "露西拉", "卢西拉", "洛西拉", "洛塞拉", "洛瑟拉",
               # --- 中文同音/音近（luò sè lā）---
               "洛色拉", "洛瑟垃", "洛瑟啦", "洛瑟菈大人",
               "罗瑟菈", "锣瑟菈",
               # --- 英文 ASR 音近（Lucilla）---
               "Lucila", "Lucilla", "Lucia", "Luciana", "Lucille",
               "Lusilla", "Lucilla's", "Lucilla`s", "Lu-cilla",
               "Luciela", "Lucillar", "Lucillia",
           ),
           ctx=((r"\bLucilla\b", "露西拉"), (r"\bLucilla\b", "卢西拉"),
                (r"\bLucilla\b", "洛瑟菈")),
           note="星炬学院校长（官方中文'洛瑟菈'，库街区 wiki/3DM/sina 确认）。"
                "身份：学院 President=校长，机翻误作'总统'（已有'洛瑟菈总统→洛瑟菈校长'长键兜底）。"
                "⚠️ 2026-10-04：原 ctx 里的 (r'\\bPresident\\b','总统') 已移出——Entity.ctx"
                "会强制替换成 canonical（洛瑟菈），把'总统'改成'洛瑟菈'会得到'洛瑟菈是学院的"
                "洛瑟菈'；现改挂 CONTEXT_MAP 原生三元组 (President,'总统','校长')。"
                "ASR 音近错形：'洛瑟菈'易咬成'洛色拉/洛瑟垃/洛瑟啦/罗瑟菈/锣瑟菈'；"
                "英文侧 Lucilla 易咬成 Lucila/Lucilla/Lucia/Lucille/Lusilla/Luciela。"),
    Entity("千咲", modes=("bi",), en="Chisa", ja="チサ",
           category="角色/星炬学院",
           variants=(
               # --- 既有机翻错形 ---
               "Chisa", "CHISA", "奇莎", "奇萨", "千笑",
               # --- 中文同音/音近（qiān xiào）---
               "千啸", "千筱", "千晓", "千笑 ", "千霄", "千宵",
               "牵笑", "芊笑", "千效", "千校", "千肖",
               # --- 英文 ASR 音近（Chisa）---
               "Chisa", "Chi-sa", "Chissa", "Chisa's", "Chisa`s",
               "Chiasa", "Chisaa", "Chiisa", "Chisa!",
           ),
           ctx=((r"\bChisa\b", "千咲"), (r"\bChisa\b", "奇莎")),
           note="星炬学院/解弦之眼角色（官方中文'千咲'，日文 チサ；3.7 复刻池）。"
                "英文恰为千咲罗马音 Chisa，ASR 易与 Chisha(炽霞) 混——"
                "已有 CONTEXT_MAP (r'\\bChisha\\b', '千咲'→'炽霞') 回滚规则兜底，防误伤。"
                "⚠️ 2026-10-04 移除本 Entity 的 (r'\\bChisha\\b','炽霞') ctx：它与上面"
                "那条 CONTEXT_MAP 回滚**互逆**且后执行，会把已回滚成'炽霞'的结果又改回"
                "'千咲'（实测 '奇莎'+Chisha 得'千咲'，应为'炽霞'）。Chisha=炽霞(Chixia)，"
                "与千咲(Chisa)无关，该 ctx 本就不该存在。"
                "ASR 音近错形：'千咲'易咬成'千啸/千筱/千晓/千霄/千宵/牵笑/芊笑/千效/千校/千肖'；"
                "英文侧 Chisa 易咬成 Chissa/Chiasa/Chisaa/Chiisa。"),
    Entity("尤诺", modes=("bi",), en="Iuno",
           category="角色",
           variants=(
               # --- 中文同音/音近（yóu nuò）---
               "由诺", "犹诺", "油诺", "尤那", "尤娜", "尤糯",
               "尤洛", "尤珞", "游诺", "柚诺", "佑诺",
               # --- 英文 ASR 音近（Iuno / Juno / Yuno）---
               "Juno", "Juno's", "Juno`s", "Junno", "Juno!",
               "Jueno", "Juneau", "Junoe", "Junoo", "Juno ",
               "Iuno", "Iuno's", "Yuno", "Yuno's",
           ),
           note="鸣潮角色（3.7 复刻池'漫于盈缺时轴'）。官方中文'尤诺'，英文 Iuno"
                "（萌娘百科/百度百科均作 Iuno；名字源自罗马 Juno，游戏拼写为 Iuno，勿写 Juno）。"
                "ASR 音近错形：'尤诺'易咬成'由诺/犹诺/油诺/尤那/尤娜/尤糯/尤洛/尤珞/游诺/柚诺/佑诺'；"
                "英文侧 Iuno 易咬成 Juno/Junno/Jueno/Juneau/Junoe/Junoo/Yuno。"),
    Entity("清宵", modes=("bi",), en="Qingxiao", ja="セイショウ",
           category="角色/鸣潮3.6",
           variants=(
               # --- 既有机翻/ASR 错形 ---
               "青霄", "Ching Xiao", "Chingsha", "Ching Sha",
               "Chingcha", "Chingsho", "Chingo", "Ching",
               "清沙", "清筱", "Chincha", "Chimcha",
               # --- 中文同音/音近（qīng xiāo）---
               "清霄", "清晓", "清笑", "清宵 ", "清哮", "清消",
               "清逍", "青宵", "青晓", "青笑", "清潇", "清萧",
               # --- 英文 ASR 音近（Qingxiao）---
               "Qingxiao", "Qing Xiao", "Chingxiao", "Ching-hsiao",
               "Qingxiaoo", "Qingxiao's", "Qingxiao!",
               # --- 2026-09-27 学习库 confirmed 固化：谷翻/ASR 音近错形
               #     (#10/1344/1729/1795/1829/2057/2366/2456，各片人工确认) ---
               "静莎", "程晓", "钦察", "景沙", "钦查", "青沙", "青莎", "秦莎",
           ),
           note="鸣潮 3.6 新共鸣者（官方中文'清宵'，日文片セイショウ）。"
                "ASR 音近错形：'清宵'易咬成'清霄/清晓/清笑/清哮/清消/清逍/清潇/清萧'；"
                "'青霄'为既有机翻错形；英文侧 Qingxiao/Ching Xiao/Chingsha/Chingcha 等已收。"
                "戒律：日语片'聖/聖書'=清宵(セイショウ)非心月狐(シン)，勿混。"),
    # ============================================================
    # 2026-09-22 音乐台词 · 多语对照（鸣潮 / 明日方舟 / 终末地）
    #   用途：音乐 reaction / OST 分析片（bi / react / ak / endo）中**跨语识别同一专名**。
    #   戒律（用户 2026-09-22 指定）：
    #     ① 曲名/专辑名在四语服常为**各自独立的官方名**（非直译）；有官方外文名才填 en/ja/ko；
    #     ② **只有单一语种官方名的，不翻译、保留原语言**（如明日方舟曲名保留英文、
    #        终末地曲名保留中文），en/ja/ko 一律留空，**不臆造译名**；
    #     ③ 音译/意译错形无片源实测证据前不入 variants（防误伤）。
    #   来源：库街区鸣潮官方 EP 页、bangumi 696519、acgwiki.tw、dengqi.ren 专题、
    #         萌娘百科「塞壬唱片 / Give Me Something」、新浪游戏「向渊行OST上线」、17173。
    # ============================================================
    Entity("鸣潮先约电台", modes=("bi", "react"), en="", ja="", ko="",
           category="厂牌/音乐·鸣潮",
           variants=("先约电台", "先約電臺", "先約电台"),
           note="《鸣潮》官方音乐出品方（角色印象曲 EP 系列；游戏内'先约随心频道'）。"
                "官方**无英文/日文/韩文名**，各语服宣传一律沿用中文（日服作繁体'先約電臺'）"
                "——按'单语保留原语言'原则，en/ja/ko 留空不填。"),
    Entity("尘外客", modes=("bi", "react"),
           en="Outside the Mountain", ja="塵世を見守りて", ko="속세 밖 나그네",
           category="曲目/鸣潮先约电台",
           note="《鸣潮》先约电台 EP3.6——清宵印象曲（2026-08-20）。"
                "**四语官方曲名互不直译**：中 尘外客 / 英 Outside the Mountain / "
                "日 塵世を見守りて（守望着尘世）/ 韩 속세 밖 나그네（尘世外的旅人）。"
                "制作人宫阁，古琴翟忻来（**非古筝**）；四语演唱分别为 蔡明希(不才) / xBay / "
                "DAZBEE / 손디아。来源：库街区 EP3.6 页、bangumi 696519、acgwiki.tw、2cycd credits。"),
    Entity("风之所在", modes=("bi", "react"),
           en="In the Wind", ja="風の在り処", ko="바람이 머무는 곳",
           category="曲目/鸣潮先约电台",
           note="《鸣潮》先约电台 EP3.5——秧秧·玄翎印象曲（2026-07-09）。"
                "四语官方曲名：风之所在 / In the Wind / 風の在り処 / 바람이 머무는 곳。"
                "制作人 Sihan；四语演唱 王诗安 / Natalie Taylor / 秧秧(CV:石川由依) / 안다은。"
                "⚠ 日文版由角色 CV 石川由依演唱，与另三语版歌手不同。"
                "来源：库街区 EP3.5 页、NGA 47141392、dengqi.ren 专题。"),
    Entity("星炬不熄", modes=("bi", "react"),
           en="Unwavering Startorch", ja="絶やさぬスタートーチ",
           ko="흔들리지 않는 스타토치",
           category="曲目/鸣潮先约电台",
           note="《鸣潮》先约电台星炬学院毕业纪念曲（另含'毕业合唱 Ver.'）。"
                "四语官方曲名：星炬不熄 / Unwavering Startorch / 絶やさぬスタートーチ / "
                "흔들리지 않는 스타토치。'Startorch'=星炬学院官方英文（学院 Startorch Academy），"
                "日文写 スタートーチ、韩文写 스타토치。"
                "来源：dengqi.ren 专题（四语并列）、B站鸣潮 WIKI 影像收录。"),
    Entity("塞壬唱片", modes=("ak", "react"), en="Monster Siren Records",
           category="厂牌/音乐·明日方舟",
           variants=("Monster Siren Records", "MSR", "MSR-MSR", "音角",
                     "Monster Sign Records", "Monster Sign Record", "Monster Signs Records"),
           note="《明日方舟》官方音乐企划 / 虚构唱片公司，鹰角网络旗下。"
                "官方英文 Monster Siren Records（缩写 MSR），社区昵称'音角'。"
                "日/韩服**沿用英文名**（アークナイツ 侧亦作 Monster Siren Records / MSR），"
                "无独立日/韩文名——按单语保留原语言，ja/ko 留空。"
                "官网 monster-siren.hypergryph.com。来源：萌娘百科、Genius MSR 页。"
                "（bi 模式已有参考行锚定 (Monster Siren → 怪物海妖唱片 → 塞壬唱片)，勿重复。）"
                "⚠ ASR 常把 Siren 听成 Sign，故变体含 'Monster Sign Records'（2026-10-06 实测命中）。"),
    # ===== 2026-10-06 明日方舟 SideStory《直到大地变成一颗酸橙》OST reaction 片沉淀 =====
    # 片源：《Music Composer Reacts - 连烦恼也融入天空 | Angelina Alter Event (Arknights)》
    #   英文原声 + 谷歌翻译中文行（148 cue，--ak 模式）。
    # ⚠ 以下两条**错形均为普通中文词**（连忧虑都融化了 / 土地变成橙色），
    #   按戒律绝不进 variants 裸键，只能走 subfix 逐 cue 修正（本次已用 outputs/ak_angie_fix.tsv）。
    Entity("连烦恼也融入天空", modes=("ak",), en="Even Worries Melt into the Sky",
           category="曲目/明日方舟",
           note="《直到大地变成一颗酸橙OST》收录曲（2026-08-03 专辑，共 9 首），"
                "塞壬唱片-MSR / F.L.O.A.T（白羽）/ 张晶。"
                "活动 PV 曲；英译 Even worries melt into the sky。"
                "来源：网易云音乐《直到大地变成一颗酸橙OST》、B站夏活 BGM 试听、midishow。"
                "⚠ 机翻错形'连忧虑都融化了/即使是麻烦都融入了天空'是普通中文词，只走 subfix。"),
    Entity("直到大地变成一颗酸橙", modes=("ak",), en="Till the Lands Become an Orange",
           category="活动/明日方舟",
           note="《明日方舟》第 113 次活动（SideStory，2026-08 上线），安洁莉娜异格（予愿安洁莉娜 / "
                "Angelina the Mellow Wish）登场的活动；关卡前缀 TO。"
                "来源：PRTS / BWIKI / 萌娘百科。"
                "⚠ 机翻错形'土地变成橙色'是普通中文词，只走 subfix。"),
    Entity("向渊行", modes=("endo", "react"), en="", ja="", ko="",
           category="专辑/终末地OST",
           note="《明日方舟：终末地》1.4 版本 OST 专辑（2026-07-30 上架 QQ/网易云/酷狗，"
                "20+ 曲：帷幕叩问 / 雄关锦绣 / 启天 / 杀身射影 / 万象丹青 / 渡此墨白 / 百险折锋 / "
                "分雾瘴 / 守心枢 / 空洞灭绝 / 禁土 / 砺剑峥嵘 / 谈此剑 / 堂前事 / 恒流失陷 / "
                "趋向梦境 / 心中的残垣 / 吾乡旧 / 编织光流 (For Your Name) / 在希望斑驳时 / "
                "孤海旧锚 / 明视沉霭 / ADELPHOCLAST / ACHERON / ABYSSUS, ABYSSUM, INVOCAT / "
                "REAPER / AMARANTHUS CAUDATUS / 镇渊回声 / 于旧土响彻 / Vermilion）。"
                "专辑与曲目为**中英混排**、官方未给统一外文名，日/韩服沿用——"
                "按'单语保留原语言'，en/ja/ko 留空。来源：新浪游戏「向渊行OST上线」。"),
    Entity("Give Me Something", modes=("endo", "react"),
           en="Give Me Something", ja="", ko="",
           category="曲目/终末地",
           note="《明日方舟：终末地》公测宣传曲 / 主题曲，副题 'Give Me Something "
                "(for Arknights: Endfield)'，OneRepublic 演唱，BMG 发行，"
                "2025-12-11 TGA 2025 首发。官方**仅英文曲名**"
                "（萌娘百科记中文译名'给我一些指引'，非官方）——按单语保留原语言，"
                "字幕若出现机翻中文应还原为英文，ja/ko 留空。"
                "来源：萌娘百科「Give Me Something」、17173 报道。"),
    Entity("夏空", modes=("bi",), en="Ciaccona",
           category="角色/鸣潮", variants=("沙科纳", "Chiaona", "Chiaakona", "Chakona"),
           note="补 r3 '沙科纳'->夏空（#1683，Shakona 谷翻）。既有 西科纳/萨库娜 保留。"
                "2026-10-24 补英文 ASR 形 Chiaona/Chiaakona/Chakona（Ciaccona 的连读）。"),
    Entity("鸣潮", modes=("bi", "react"), en="Wuthering Waves", ja="鳴潮", ko="명조",
           category="作品/游戏",
           variants=("鸣潮涛",
                     # --- 2026-09-27 学习库 confirmed 固化 ---
                     "Withering Waves",   # 英文名错拼（Wuthering 的常见 ASR/手误形）
                     "明祖",              # Mingchao ASR 音近残留
                     # --- 2026-09-28 ASR 断词 + 硬译残留（用户实测片源）---
                     # 参考行 "Water ing lace just released shin the reson ator showcase,"
                     #   （Wuthering Waves 被 ASR 断词 + 误听），谷翻按字面直译成下形；
                     #   非正常中文词，裸键安全。英文侧规整见 EN_ASR_SPLIT_FIXES。
                     "浇水蕾丝", "浇水蕾斯",
                     # 戒律：'明朝/明州/枯萎/浇水方式/风化波浪' 为常用词/短语，绝不裸键（见下 ctx）
                     ),
           # 歧义形（本身是正常中文短语）只走参考行佐证：英文侧经 EN_ASR_SPLIT_FIXES
           #   规整（"Watering Ways"->"Wuthering Waves"）后 \bWuthering Waves\b 才命中。
           #   注：'风化波浪/风化浪潮' 已是 BILINGUAL_TERMS 无条件变体（第 330/550 行），此处不再重复。
           ctx=((r"\bWuthering Waves\b", "浇水方式"),),   # Watering Ways
           note="库洛游戏《鸣潮》（英文 Wuthering Waves，日文 鳴潮，韩文 명조）。"
                "本表只收**片源实测的非正常中文错形**：'鸣潮涛'为谷翻把 Wuthering Waves "
                "拆译的残留（2026-09-23《尘外客》reaction 片实测）；"
                "'浇水蕾丝'为 ASR 断词+误听（Water ing lace）后的硬译残留（2026-09-28 实测）。"
                "戒律：'凋零波浪/风化波浪/浇水方式'等通用词义错形不得作裸键（见 BILINGUAL_TERMS 同名注释），"
                "改走 ctx 由参考行锚定；无实测证据的音近错形一律不臆造。"),
    Entity("丹瑾", modes=("bi",), en="Danjin",
           category="角色/鸣潮",
           variants=("团津",),                          # #120/121 "who's Tanjin" 谷翻
           ctx=((r"\bTanjin\b|\bDanjin\b", "丹津"),),  # #19/718 "丹津"正常词，锚定才改
           note="4★ 湮灭角色（官方 丹瑾）。r3 错形：团津(#120/121)、丹津(#19/718)。"
                "'丹津'可作正常地名，裸键危险，仅英文 Tanjin/Danjin 佐证才改；"
                "'团津'非正常中文词，安全裸键。既有扁平键 '丹金'->丹瑾 保留。"),
    Entity("凌阳", modes=("bi",), en="Lingyang",
           category="角色/鸣潮", variants=("灵阳",),
           note="补 r3 '灵阳'->凌阳（#350/357/611/715，Lingyang 同音拆字）。既有 '陵阳' 保留。"),
    Entity("相里要", modes=("bi",), en="Xiangli Yao",
           category="角色/鸣潮", variants=("尚丽瑶",),
           note="补 r3 '尚丽瑶'->相里要（#24，Shangli Yao 谷翻）。官方名 相里要。"),
    Entity("洛可可", modes=("bi",), en="Roccia",
           category="角色/鸣潮", variants=("罗蒂亚",),
           note="补 r3 '罗蒂亚'->洛可可（#1212，Roccia 谷翻音译）。非正常中文词，裸键安全。"),
    Entity("守岸人", modes=("bi",), en="The Shorekeeper",
           category="角色/鸣潮", variants=("肖尔基珀", "肖特克守门员"),
           ctx=((r"[Ss]horekeeper", "岸上看守"),
                (r"\bShorekeeper\b|\bShortke\b", "岸上管理员"),
                (r"\bShorekeeper\b|\bShortke\b", "肖特克守门员")),
           note="补 r3：肖尔基珀(#1037，非正常词裸键安全)；岸上看守(#325/961，正常短语，"
                "须 Shorekeeper 佐证才改)。2026-10-25 4.0 片补 岸上管理员/肖特克守门员；"
                "既有 短守/Shawkeeper/岸边管理员/空头/短手 保留。"),
    Entity("共鸣者", modes=("bi",), en="Resonator",
           category="术语/鸣潮",
           ctx=((r"[Rr]esonator", "共振腔"), (r"[Rr]esonator", "共鸣腔")),
           note="补 r3（走 ctx 锚定，正常词不裸进表）：共振腔(#6)/共鸣腔(#169/549/553)->共鸣者。"
                "既有 CONTEXT '谐振器'->共鸣者 保留。"
                "⚠ 展示会/屏幕时间 的目标词（展示/镜头时间）≠本实体 canonical（共鸣者），"
                "不能用 Entity.ctx（会强制替换成 canonical），已改走 CONTEXT_MAP 原生三元组。"),
    Entity("嘉贝莉娜", modes=("bi",), en="Galbrena",
           category="角色/鸣潮", variants=("加尔雷娜",),
           note="补 r3 '加尔雷娜'->嘉贝莉娜（#29，Galrena 谷翻）。官方名 嘉贝莉娜。"),
    Entity("秋水", modes=("bi",), en="Aalto",
           category="角色/鸣潮",
           ctx=((r"\bAlto\b|\bAalto\b", "阿尔托"),),
           note="补 r3 '阿尔托'->秋水（#64 'next up, Alto' 谷翻）。'阿尔托'常见西名绝不裸键。"
                "⚠ 历史片源结论（2026-09-09 注释）称 Aalto=阿尔托 不改——那是 TCG 讨论片语境；"
                "本片'next up, Alto'为角色章节报幕，官方中文=秋水（2026-09-24 官方图鉴复核）。"),
    Entity("散华", modes=("bi",), en="Sanhua",
           category="角色/鸣潮",
           variants=("三和",),                      # 2026-09-27 学习库固化(#170/344)：Sanhua 音近错形
           ctx=((r"\bSana\b|\bSanhua\b", "萨那"),),
           note="补 r3 '萨那'->散华（#5 开场 'from Sana to Ching Xiao'）。'萨那'也门城市绝不裸键。"),
    Entity("卡提希娅", modes=("bi",), en="Cartethyia",
           category="角色/鸣潮", variants=("卡蒂拉",),
           note="补 r3 '卡蒂拉'->卡提希娅（#1694/1784，Cartilla 谷翻）。"
                "与既有 CONTEXT '卡提拉'->坎特蕾拉(TCG 片) 为不同错形键，不冲突。"),
    # ============================================================
    # 2026-09-27 学习库 confirmed 固化（learned-promote 人工审阅版）
    #   来源：subtitle_learned_kb.json 各机人工校对 confirmed 条目（89 条，
    #   GitHub main 收集分支与本机完全一致，sha256 同源核对）。
    #   甄别戒律：专名/生僻错形才固化进内置表；'明朝/明州/枯萎/骑士/典范/法官/
    #   哨兵/拖车/哀叹/谐振器/漫游者/太恶心了/圆形/图案/溪流/外骨骼/京城/金龙/
    #   露西尔/Nvidia' 等常用词义错位不固化（留学习库运行时注入+反例降级，
    #   详见学习库 bi|<词> 条目）；句子级扩展形态（'谢谢你，鸣潮亚'等）同样不固化。
    # ============================================================
    Entity("吟霖", modes=("bi",), en="Yinlin", ko="음림",
           category="角色/鸣潮",
           variants=("Eumrim", "尤姆林"),
           note="学习库固化(#971/972/975/3521-3524，2026-09-20~25 两片实测)："
                "Eumrim=韩服名음림(Eumlim) ASR 残留；尤姆林=音近错形。"),
    Entity("今汐", modes=("bi",), en="Jinhsi",
           category="角色/鸣潮",
           variants=("金熙",),
           note="学习库固化(#55/56)：'金熙'为 Jinhsi 音近错形。"),
    Entity("秧秧", modes=("bi",), en="Yangyang",
           category="角色/鸣潮",
           variants=("杨阳",),
           note="学习库固化(#388/402/570/1512/1844/2796/4689/4692 多片实测)："
                "'杨阳'为 Yangyang 音近错形。"
                "2026-10-27 ABRAXAS 片 ASR `Yinyang`→谷翻「阴阳」；阴阳为通用词，"
                "只做本片 sidecar，不入全局键。"),
    Entity("坎特蕾拉", modes=("bi",), en="Cantarella",
           category="角色/鸣潮",
           variants=("卡内雷拉", "卡内拉"),
           note="学习库固化(#192/197/1487/2151/2251-2254)：Cantarella 音译残留。"),
    Entity("木禺", modes=("bi",),
           category="角色/鸣潮2.x",
           variants=("穆宇", "慕宇"),
           note="学习库固化(#1410/2029/2440/2706/3138/5456/5613)：Muyu 音近错形；"
                "英文侧 Muyu 佐证形（何慕语等）走学习库 ctx，未固化。"),
    Entity("露丝", modes=("bi",),
           category="角色",
           variants=("鲁斯",),
           note="学习库固化(#1/2/3)：'鲁斯'为 ASR 残缺音译。同片'荷鲁斯说你好->荷露丝说你好'"
                "为整句特例，留学习库（'荷鲁斯'=Horus 常规译名绝不裸键）。"),
    # 2026-10-04 删除 Entity("鸣潮之波", variants=("枯萎之波",))：目标"鸣潮之波"是
    #   "枯萎之波"被裸键"枯萎"咬半截的产物，正确形应为"鸣潮"（已并入 BILINGUAL_TERMS 长键）。
    Entity("Paragon", modes=("bi",), en="Paragon",
           category="称号/术语·鸣潮",
           variants=("帕拉贡",),
           note="学习库固化(#2011-8512 多片实测)：'帕拉贡'=Paragon 音译残留。"
                "'典范'为常用词义错位，走学习库 ctx（Sha/Chin/Paragon 佐证），不固化。"),
    Entity("Paragon清宵", modes=("bi",),
           category="称号/鸣潮3.6",
           variants=("百丽宫青沙",),
           note="学习库固化(#1617/5370)：'百丽宫'=Paragon 音译、'青沙'=清宵错形的组合残留。"),
    Entity("清宵Paragon", modes=("bi",),
           category="称号/鸣潮3.6",
           variants=("清沙典范",),
           note="学习库固化(#2338/8264/10767)：语序相反的另一组合错形，与 Paragon清宵 并存。"),
    Entity("inzho", modes=("bi",),
           category="术语·待查证",
           variants=("ingjo",),
           note="学习库固化(#968/3795)：ingjo->inzho 小写英文残留替换，两串均生僻，误伤概率极低。"),
    Entity("七丘", modes=("bi",), en="Septimont",
           category="地点/鸣潮2.x",
           variants=("塞普蒂蒙",),
           note="学习库固化(#967/3913)：Septimont 音译残留。"),
    Entity("云梭", modes=("bi",),
           category="载具/鸣潮2.x",
           variants=("航天飞机",),
           note="学习库固化(#3655-4219 共8处)：shuttle 机翻'航天飞机'归云梭；"
                "'班车'义错位留学习库（日常词不裸键扩散）。"),
    Entity("原神", modes=("bi",), en="Genshin Impact",
           category="作品/游戏",
           variants=("根钦",),
           note="学习库固化(#224/241)：Genshin ASR 错听'根钦'。"),
    Entity("幽客", modes=("bi",),
           category="敌人/术语·鸣潮2.x",
           variants=("地界法师",),
           note="学习库固化(#1147/1162)：nethermancer 机翻'地界法师'归幽客；"
                "'下界法师/下界术士/地狱法师'等 ctx 佐证形留学习库候选。"),
    Entity("强度膨胀", modes=("bi",),
           category="术语",
           variants=("力量蔓延",),
           note="学习库固化(#496/605)：power creep 机翻残留。"),
    Entity("恒星矩阵导航员", modes=("bi",),
           category="职务/术语·鸣潮2.x",
           variants=("斯特拉矩阵导航员",),
           note="学习库固化(#1304/1320)：Stellar Matrix 音译残留。"),
    Entity("梦州", modes=("bi",),
           category="地点/鸣潮2.x",
           variants=("蒙祖",),
           note="学习库固化(#707/5518)：Mongzu 音译残留。"),
    Entity("鸣式", modes=("bi",),
           category="术语/鸣潮2.x",
           variants=("明植",),
           note="学习库固化(#551/2275/2928-4411 共12处多片实测)：Threnodian 专名 ASR/机翻"
                "错形'明植'（生僻组合，裸键安全）。"),
    Entity("玄Paragon", modes=("bi",),
           category="称号/鸣潮2.x",
           variants=("天鹅典范",),
           note="学习库固化(#3022/4027)：'天鹅'=Schwan 音译、'典范'=Paragon 机翻，组合残留。"),
    Entity("玄元境", modes=("bi",),
           category="地点/术语·鸣潮2.x",
           variants=("施瓦努安", "Shwanuan"),
           note="学习库固化(#2069/9876/9888)：Schwanuan 音译残留；Shwanuan 为少 c 的 ASR 形"
                "（2026-10-05 第二部 3.7 片 #653/#655/#1509）。"),
    Entity("玄方城", modes=("bi",),
           category="地点/鸣潮2.x",
           variants=("施万芬霍尔德", "天鹅芳", "施万夫"),
           note="学习库固化(#2269/4364-4365/7528/7617/11047)：Schwanfang Hold 音译残留组合；"
                "其余 Schw* 系错形（海绵牙/施万芳要塞/万丰控股 等数十条）均为依赖参考行锚定的"
                "候选，留学习库 ctx 逐条人工确认，未固化。"),
    Entity("蜃境", modes=("bi",),
           category="地点/术语",
           variants=("幻界",),
           note="学习库固化(#2315/2325/5263/5866/6580/12255)：mirage 机翻'幻界'归蜃境。"),
    Entity("爱弥斯", modes=("bi",),
           category="角色/鸣潮2.x",
           variants=("艾姆斯", "Amus", "Amoth", "Amth"),
           note="学习库固化(#1644/1645/4470)：Amess 音译残留；'伊梅'(Imeth)走学习库 ctx。"
                "2026-10-25 4.0 片补 Amoth/Amth（ASR 形）。"),
    # ===== 2026-10-01 韩语原声·鸣潮 reaction 片（《명조》B站初体验，577 cue）沉淀 =====
    # 官方译名来源：百度百科 / 鸣潮WIKI(BWIKI) / 灰机wiki / Fandom / 萌娘百科《鸣潮/译名对照表》/ namu.wiki。
    # 戒律：官方中文名做 canonical；非正常中文词进 variants（无条件改）；
    #       普通中文词（耐克/广播/个性/比赛/星轨/迷你甜瓜…）一律走 ctx，靠韩语参考行佐证。
    Entity("露帕", modes=("ko",), en="Lupa", ja="ルパ", ko="루파",
           category="角色/鸣潮",
           variants=("鲁帕", "卢帕"),
           ctx=((r"루파", "Rupa"), (r"루파", "Lupa")),
           note="鸣潮 2.4 版本（2025-07-03）五星角色，七丘阵营。韩语 루파；谷翻残留'鲁帕/Rupa/Lupa'。"
                "英文 Lupa 走 ctx（防误伤拉丁语 lupa=母狼 / 其它语境）。"),
    Entity("达妮娅", modes=("ko",), en="Denia", ja="ダーニャ", ko="데니아",
           category="角色/鸣潮",
           variants=("德尼娅", "德妮亚", "丹妮亚", "达妮亚"),
           note="鸣潮 3.3 版本五星角色（热熔/音感仪），星炬学院学生。韩语 데니아；谷翻常作'德尼娅'。"),
    Entity("洛瑟菈", modes=("ko",), en="Lucilla", ja="ルシラ", ko="루실라",
           category="角色/鸣潮",
           variants=("露西拉", "卢西拉", "鲁西拉", "洛瑟拉", "罗瑟菈"),
           note="鸣潮角色（冷凝/记忆宫殿），星炬学院学院长，2026-06 上线。韩语 루실라；"
                "谷翻按音译作'露西拉'，官方中文名为'洛瑟菈'。"),
    Entity("卡提希娅", modes=("ko",), en="Cartethyia", ja="カルテジア", ko="카르티시아",
           category="角色/鸣潮",
           variants=("卡迪萨西亚", "卡提西亚", "卡尔提西亚", "卡提希亚"),
           note="鸣潮角色（气动），黎那汐塔流浪骑士，原名芙露德莉斯。韩语 카르티시아；"
                "ASR 常咬成 카르티샤시아，谷翻'卡迪萨西亚'。"),
    Entity("妮姬", modes=("ko",), en="NIKKE", ko="니케",
           category="作品",
           variants=("尼肯", "尼凯", "妮凯"),
           ctx=((r"니케", "耐克"),),
           note="《胜利女神：妮姬》NIKKE（非鸣潮）。'耐克'是正常中文词(Nike)，"
                "仅参考行含 니케 时替换，防误伤运动品牌。"),
    Entity("星穹铁道", modes=("ko",), ko="스타레일",
           category="作品",
           ctx=((r"스타\s*레일", "星轨"),),
           note="《崩坏：星穹铁道》。'星轨'是正常中文词（另有同名游戏/天文义），"
                "仅参考行含 스타레일 时替换。"),
    Entity("废墟图书馆", modes=("ko",), ko="라이브러리 오브 루이나",
           category="作品",
           variants=("瑞纳图书馆",),
           ctx=((r"루이나", "瑞纳"),),
           note="《Library of Ruina》官方中文名《废墟图书馆》。韩语 라이브러리 오브 루이나。"),
    Entity("迷你梅洛", modes=("ko",), ko="미니멜로",
           category="主播",
           ctx=((r"미니\s*멜로", "迷你甜瓜"), (r"미니\s*멜로", "迷你旋律"),
                (r"도[서수]관", "小型水管")),
           note="韩国 VTuber 미니멜로（Minimallow，YouTube 频道 Minimallow's Library）。"
                "无官方中文译名（B 站搬运标题直接用韩文原名），本库音译统一为「迷你梅洛」；"
                "미니멜로 도서관 = 迷你梅洛图书馆。'迷你甜瓜/迷你旋律'是正常词组，走 ctx。"),
    Entity("微信", modes=("ko",), en="WeChat", ko="위체",
           category="术语",
           variants=("韦切", "Wiche", "威切", "魏彻"),
           note="微信（WeChat）。韩语 위체；谷翻常作'韦切/Wiche'。"),
    Entity("哔哩哔哩", modes=("ko",), ko="빌리빌리",
           category="平台",
           variants=("比里比里", "比利比利", "哔哩比哩"),
           ctx=((r"빌리빌리", "Bilibili"), (r"빌리빌리", "bilibili")),
           note="B站。韩语 빌리빌리；ASR/谷翻常作'比里比里/比利比利'。"
                "英文名 Bilibili 走 ctx（防误伤纯英文语境）。"),
    Entity("直播", modes=("ko",), ko="방송",
           category="术语",
           ctx=((r"방송", "广播"),),
           note="韩语 방송=放送/直播。主播场景谷翻直译'广播'，走 ctx 锚定"
                "（'广播'是正常词，不入 KO_TERMS）。"),
    Entity("专武", modes=("ko",), ko="전무",
           category="术语",
           ctx=((r"전무", "执行董事"),),
           note="전무=전용무기（专属武器）简称。谷翻按公司职位译成'执行董事'，走 ctx。"),
    Entity("角色", modes=("ko",), ko="캐릭터",
           category="术语",
           ctx=((r"캐릭터", "个性"), (r"캐릭터", "性格")),
           note="캐릭터(character) 在游戏语境=角色。谷翻常误作'个性/性格'，走 ctx 锚定。"),
    Entity("游戏", modes=("ko",), ko="게임",
           category="术语",
           ctx=((r"게임", "比赛"),),
           note="게임=游戏。谷翻常误作'比赛'（'我在比赛中很努力'=게임 열심히 해），走 ctx。"),
    Entity("世界级", modes=("ko",), en="World Class", ko="월클",
           category="术语",
           ctx=((r"월클", "沃尔克尔"), (r"월클", "Wolklk")),
           note="韩语网络俚语 월클=World Class（世界级）。谷翻按音译作'沃尔克尔/Wolklk'，走 ctx。"),
    Entity("Kid Sang", modes=("ko",), ko="키드상",
           category="昵称",
           ctx=((r"키드\s*상", "儿童奖"),),
           note="B站用户昵称 키드상(Kid Sang)。谷翻按字面拆译成'儿童奖'（kid=儿童 / 상=奖），走 ctx。"),
    Entity("字幕", modes=("ko",), ko="자막",
           category="术语",
           ctx=((r"자막", "标题"),),
           note="자막=字幕。谷翻偶把'자막'误作'标题'（同段混用），走 ctx 锚定。"),
    Entity("账号", modes=("ko",), ko="아이디",
           category="术语",
           ctx=((r"아이디", "身份证"),),
           note="아이디=ID/账号。谷翻按字面把 ID 译成'身份证'，直播注册场景全错，走 ctx 锚定。"),
    # ===== 2026-10-01 二次校准沉淀（韩服 3.7 心月狐片 여우별 정주행，2804 cue，--ko）=====
    # 官方依据（本轮联网核对）：3.7「镜锁妄世，心照红尘」官方 PV/共鸣者档案前瞻（ourplay/163/
    #   TapTap/搜狐）、灰机wiki《锁暝》/《玄方地界》、Fandom《玄方地界》、百度百科《玄方》《穗穗》、
    #   贴吧 3.7 前瞻剧情汇总。核心事实：**岁主本体=心月狐；祂分出的情感模块=「心」**；
    #   3.7 双五星「心」「锁暝」；锁暝=梦州**华亭**人、州监、执掌**谛天鉴**、异能力「十重契」；
    #   故乡灾厄名**恶瘴**；区域「梦州·玄方地界」/「玄方城」/「梦枢天罗」；文明之匣。
    # 戒律不变：官方名做 canonical；普通中文词（尸体/主体/克隆体/守护灵/诱饵/和谐/星座…）
    #   一律走 ctx，由韩语参考行正则锚定，绝不裸键。
    Entity("玄方城", modes=("ko",), ko="현방성", category="地名/鸣潮",
           ctx=((r"현방성", "玄方道"),
                (r"현방지계", "玄方系统"),
                (r"현방지계", "现任地方政府"),
                (r"현방지 ", "玄智寺"),
                (r"현방의 권세", "现任政府"),
                (r"현방의 백성", "现在省份"),
                (r"현방 백성", "现任办公室")),
           note="玄方城（梦州·玄方地界核心）。谷翻对 현방성/현방지계 产出'玄方道/玄方系统/"
                "现任政府/现任地方政府/玄智寺/现任办公室/现在省份'等正常中文词，全部走 ctx。"),
    Entity("守护神", modes=("ko",), ko="수호신", category="术语/鸣潮",
           ctx=((r"수호시", "Suhosi"),
                (r"수호시는", "须星"),
                (r"수어신에", "单词句"),
                (r"수신", "接收方"),
                (r"수신", "接收者"),
                (r"수호신", "守护灵")),
           note="수호신/수호시/수어신/수신 = 守护神（岁主/守护神统称）。谷翻残留英文'Suhosi'、"
                "字面词'须星/单词句/接收方/接收者'，以及同义不同名的'守护灵'（本片统一为官方'守护神'）。"),
    Entity("心", modes=("ko",), ko="여우의 별자리", category="角色/鸣潮",
           ctx=((r"여우의 별자리", "Fox Constellation"),
                (r"여우의 별리", "心月狐啊"),
                (r"여호의 별리", "心月狐"),
                (r"심이라고 보는", "模拟市民")),
           note="「心」= 岁主心月狐分出的情感模块，韩文名 여우의 별자리（狐狸星座）。"
                "谷翻残留英文'Fox Constellation'与拆字错形'星座的地板/模拟市民/心月狐啊'，走 ctx。"),
    Entity("心月狐", modes=("ko",), ko="심월여우", category="角色/鸣潮",
           ctx=((r"심월여우", "Simwol Fox"),
                (r"수신 심월여우", "Simwol Fox接收")),
           note="岁主本体「心月狐」。谷翻偶把 심월여우 直接留英文'Simwol Fox'，走 ctx。"),
    Entity("本体", modes=("ko",), ko="본체", category="术语/鸣潮",
           ctx=((r"본체", "尸体"), (r"본체", "主体")),
           note="본체=本体（相对 분신 分身）。谷翻把 본체 误作'尸体/主体'，走 ctx。"),
    Entity("分身", modes=("ko",), ko="분신", category="术语/鸣潮",
           ctx=((r"분신", "克隆体"), (r"분신", "另一个身份")),
           note="분신=分身（心的身份）。谷翻按义近译成'克隆体/另一个身份'，走 ctx。"),
    Entity("文明之匣", modes=("ko",), ko="문명의 상자", category="物品/鸣潮",
           ctx=((r"문명의 상자", "文明的盒子"), (r"문명의 상자", "文明之盒"),
                (r"문명의 상자", "文明的文明之匣")),
           note="文明之匣（玄方篇核心道具）。谷翻同段混用'文明的盒子/文明之盒/文明的文明之匣'，走 ctx 统一。"),
    Entity("阿克西翁", modes=("ko",), ko="액시온", category="势力/鸣潮",
           ctx=((r"더 액션", "那场动作戏"),),
           note="阿克西翁（残星会相关势力）。ASR 把 액시온 咬成 액션(action)，谷翻产出'动作戏'，走 ctx。"),
    Entity("守岸人", modes=("ko",), ko="파수인", category="角色/鸣潮",
           ctx=((r"파수인", "守夜人"), (r"파수인 출시", "《Lookout》")),
           note="守岸人（鸣潮角色）。谷翻把 파수인 译成'守夜人'、把 출시(上线)误听成英文片名《Lookout》，走 ctx。"),
    Entity("华亭", modes=("ko",), ko="화정", category="地名/鸣潮",
           ctx=((r"화정", "花亭"), (r"화정을 위해", "和谐")),
           note="梦州华亭（锁暝故乡，官方档案'梦州华亭人'）。谷翻作'花亭/和谐'，走 ctx。"),
    Entity("恶瘴", modes=("ko",), ko="악장", category="术语/鸣潮",
           ctx=((r"악장", "克长静"), (r"악정", "邪恶正义")),
           note="恶瘴（华亭故乡灾厄，官方档案'故乡「恶瘴」之厄'）。ASR 악장/악정，谷翻作'克长静/邪恶正义'，走 ctx。"),
    Entity("伏笔", modes=("ko",), ko="떡밥", category="术语",
           ctx=((r"떡밥", "诱饵"),),
           note="떡밥=伏笔/后续钩子（韩语网络语）。谷翻直译成'诱饵'（钓鱼义），走 ctx 锚定。"),
    Entity("天人", modes=("ko",), ko="천인", category="术语/鸣潮",
           ctx=((r"천인이 되어", "天上的存在"), (r"천인들", "千人"),
                (r"천인들", "天界生物"), (r"천인들에게", "天界")),
           note="천인=天人（玄方/梦州的'天人'群体，与凡人相对）。谷翻作'天上的存在/千人/天界生物/天界'，走 ctx。"),
    Entity("正贤", modes=("ko",), ko="정현", category="角色/鸣潮",
           ctx=((r"정현", "郑贤"),),
           note="玄方地界人物 정현（正贤）。谷翻同片混用'正贤/郑贤'，走 ctx 统一为正贤。"),
    Entity("昭明商会", modes=("ko",), ko="소명 상인회", category="组织/鸣潮",
           ctx=((r"소명 상인회", "锁暝商会"),),
           note="昭明商会（穗穗任理事的商会，官方百科'担任昭明商会年轻理事'）。ASR 소명 与 쇠명(锁暝) 同音，"
                "谷翻把 소명 상인회 误作'锁暝商会'，走 ctx 锚定。"),
    # ===== 2026-10-01 明日方舟·英配解说双语片（男干员「不嫁调查」961 cue）沉淀 =====
    # 官方中文名来源：arknights.wiki.gg 各干员页 `|cnname =` 字段（逐条抓取核对，2026-10-01）。
    # 戒律：**普通中文词/常见音译名一律不进 variants**（阿拉斯加/午夜/兰花/荆棘/标志/内幕/
    #   不锈钢/极简主义/基线/开襟衫/遗嘱执行人/格雷/艾琳/维吉尔/文月/瑞希/阿伦…），
    #   全部走 ctx，由**英文参考行正则**锚定；只有"非正常中文词"（音译残留）才可裸键。
    #   —— 谷翻（谷歌翻译）在英→中时对同一专名会产出"字面义"与"音译"两类错形，
    #      字面义那类几乎都是正常中文词，裸键必然跨片源误伤。
    # ⚠ 注意：脚本**已有** Ark Knights 规则（CONTEXT_MAP 第 907~911 行 + AK_TERMS），
    #   本实体只补 **AK→阿拉斯加** 这一条（此前无任何表覆盖），不重复注册。
    Entity("明日方舟", modes=("bi",), en="Arknights / AK", category="作品",
           ctx=((r"\bAK\b", "阿拉斯加"),),
           note="谷翻把 'AK' 一律误译成'阿拉斯加'（2026-10-01 明日方舟男干员调查片 4 处）。"
                "'阿拉斯加'是正常中文词（Alaska），只走 ctx 由英文参考行锚定，绝不裸键。"),
    Entity("异格", modes=("bi",), en="Alter", category="术语/明日方舟",
           ctx=((r"\bAlter\b", "祭坛"),),
           note="明日方舟官方术语：Alter（异格干员）。谷翻把 Alter 直译成'祭坛'，走 ctx。"),
    Entity("角峰", modes=("bi",), en="Matterhorn", category="角色/明日方舟",
           ctx=((r"Matterhorn|Metahorn|Metal\s*Horn", "金属角"),
                (r"Matterhorn|Metahorn|Metal\s*Horn", "梅塔霍恩")),
           note="4★ 近卫，卡兰贸易的厨师。ASR 常作 Metahorn/Metal Horn；谷翻产出'金属角'(字面)/'梅塔霍恩'(音译)。"),
    Entity("月见夜", modes=("bi",), en="Midnight", category="角色/明日方舟",
           ctx=((r"\bMidnight\b", "午夜"),),
           note="3★ 近卫。'午夜'是正常中文词，只走 ctx。"),
    Entity("梓兰", modes=("bi",), en="Orchid", category="角色/明日方舟",
           ctx=((r"\bOrchid\b", "兰花"), (r"\bOrchid\b", "兰华")),
           note="3★ 术师。'兰花'是正常中文词（orchid 花名），只走 ctx。"),
    Entity("送葬人", modes=("bi",), en="Executor", category="角色/明日方舟",
           ctx=((r"\bExecutor\b", "遗嘱执行人"),),
           note="6★ 狙击。谷翻按字面译成'遗嘱执行人'，走 ctx。"),
    Entity("棘刺", modes=("bi",), en="Thorns", category="角色/明日方舟",
           ctx=((r"\bThorns\b", "荆棘"),),
           note="6★ 近卫。'荆棘'是正常中文词，只走 ctx。"),
    Entity("逻各斯", modes=("bi",), en="Logos", category="角色/明日方舟",
           ctx=((r"\bLogos\b", "标志"), (r"\bLogos\b", "罗各斯")),
           note="罗德岛精英干员。'标志'是正常中文词（logos=标识），只走 ctx。"),
    Entity("隐现", modes=("bi",), en="Insider", category="角色/明日方舟",
           ctx=((r"\bInsider\b", "内幕"),),
           note="'内幕'是正常中文词，只走 ctx。"),
    Entity("白铁", modes=("bi",), en="Stainless", category="角色/明日方舟",
           ctx=((r"\bStainless\b", "不锈钢"),),
           note="'不锈钢'是正常中文词，只走 ctx。"),
    Entity("至简", modes=("bi",), en="Minimalist", category="角色/明日方舟",
           ctx=((r"\bMinimalist\b", "极简主义"),),
           note="'极简主义'是正常中文词，只走 ctx。"),
    Entity("伺夜", modes=("bi",), en="Vigil", category="角色/明日方舟",
           ctx=((r"\bVigil\b", "维吉尔"), (r"Leontuzzo|Leon Tuzo|\bLeon\b", "莱昂")),
           note="本名=莱昂图索·贝洛内（Leontuzzo Bellone），别号'莱昂'（黑手党少爷）。ASR 常把 Leontuzzo 咬成 "
                "Leon Tuzo、'莱昂'被机翻保留；'维吉尔'是常见音译名（Virgil），均走 ctx。"),
    Entity("车尔尼", modes=("bi",), en="Czerny", category="角色/明日方舟",
           variants=("Chney",),
           note="5★ 驭法铁卫重装（尘影余音活动）。ASR 常把 Czerny 咬成 Chney，'Chney'是英文残留可裸键。"),
    Entity("安多恩", modes=("bi",), en="Andoain", category="角色/明日方舟",
           variants=("Andwin",),
           note="拉特兰'寻路者'领袖（殉道者），吾导先路/众生行记。ASR 常作 Andwin，'Andwin'是英文残留可裸键。"),
    Entity("深律", modes=("bi",), en="Bassline", category="角色/明日方舟",
           ctx=((r"\bBassline\b", "基线"),),
           note="ASR 常把 Bassline 咬成 baseline。'基线'是正常中文词，只走 ctx。"),
    Entity("卡缇", modes=("bi",), en="Cardigan", category="角色/明日方舟",
           ctx=((r"\bCardigan\b", "开襟衫"),),
           note="3★ 重装。'开襟衫'是正常中文词（cardigan=开衫毛衣），只走 ctx。"),
    Entity("慑砂", modes=("bi",), en="Sesa", category="角色/明日方舟",
           variants=("塞萨尔", "塞萨"),
           note="5★ 狙击。官方中文名=慑砂，**不是**'塞萨'；'塞萨/塞萨尔'是音译残留（非正常中文词，可裸键）。"
                "⚠ '塞萨尔'必须一并收录：否则长键序下'塞萨'会命中'塞萨尔'的前缀，产出'慑砂尔'。"),
    Entity("格雷伊", modes=("bi",), en="Greyy", category="角色/明日方舟",
           ctx=((r"\bGreyy?\b", "格雷"),),
           note="4★ 术师。ASR 常作 Gray/Grey。'格雷'是常见音译名，走 ctx。"),
    Entity("艾丽妮", modes=("bi",), en="Irene", category="角色/明日方舟",
           ctx=((r"\bIrene\b", "艾琳"),),
           note="6★ 狙击。'艾琳'是常见音译名，走 ctx。"),
    Entity("魏文月", modes=("bi",), en="Fumizuki", category="角色/明日方舟",
           ctx=((r"Fumizuki", "文月"),),
           note="东国干员，官方中文**全名**=魏文月；只写'文月'不完整，且'文月'是常见日文名，走 ctx。"),
    Entity("杰斯顿", modes=("bi",), en="Jesselton", category="角色/明日方舟",
           ctx=((r"Jesselton", "杰桑"),),
           note="官方全名=杰斯顿·威廉姆斯；字幕按口语用简称'杰斯顿'。"),
    Entity("赫德雷", modes=("bi",), en="Hoederer", category="角色/明日方舟",
           ctx=((r"Hoederer", "霍德拉"), (r"Hoederer", "霍多拉")),
           note="ASR 常作 Hodera/Hodora。"),
    Entity("伊内丝", modes=("bi",), en="Ines", category="角色/明日方舟",
           ctx=((r"\bInes\b", "伊尼斯"),),
           note="ASR 常作 Inis。"),
    Entity("空构", modes=("bi",), en="Spuria", category="角色/明日方舟",
           ctx=((r"\bSpuria\b", "斯普拉"),),
           note="拉特兰狙击。ASR 常作 Spura。"),
    Entity("芳汀", modes=("bi",), en="Arene", category="角色/明日方舟",
           ctx=((r"\bArene\b", "阿伦"),),
           note="男性近卫。ASR 常作 Aren。"),
    Entity("黑键", modes=("bi",), en="Ebenholz", category="角色/明日方舟",
           ctx=((r"Ebenholz", "埃文·霍尔斯"),),
           note="莱塔尼亚伯爵（尘影余音）。ASR 把 Ebenholz 咬成 Evan Halls。"),
    Entity("汐斯塔", modes=("bi",), en="Siesta", category="地点/明日方舟",
           variants=("西耶斯塔",),
           note="多索雷斯假日／理想城所在地。官方=汐斯塔；'西耶斯塔'是音译残留，可裸键。"),
    Entity("煌", modes=("bi",), en="Blaze", category="角色/明日方舟",
           variants=("布雷兹",),
           note="ASR 常作 Bla1/Breze。官方=煌；'布雷兹'是音译残留，可裸键。"),
    Entity("凯尔希", modes=("bi",), en="Kal'tsit / Kelsey", category="角色/明日方舟",
           variants=("凯尔西", "凯尔特", "凯尔茨"),
           note="罗德岛医疗主管。谷翻音译残留'凯尔西/凯尔特/凯尔茨'统一为凯尔希。"),
    Entity("水月", modes=("bi",), en="Mizuki", category="角色/明日方舟",
           ctx=((r"\bMizuki\b", "瑞希"),),
           note="'瑞希'是常见日文名音译，走 ctx。"),
    Entity("炎客", modes=("bi",), en="Flamebringer", category="角色/明日方舟",
           ctx=((r"\bFlamebringer\b", "火焰使者"), (r"\bFlamebringer\b", "火焰剑")),
           note="ASR 常作 Flamebrer。谷翻按字面译成'火焰使者'，走 ctx。"),
    Entity("羽毛笔", modes=("bi",), en="La Pluma", category="角色/明日方舟",
           variants=("拉·彪马",),
           note="理想城干员。ASR 常作 La Puma；'拉·彪马'是音译残留，可裸键。"),
    Entity("重岳", modes=("bi",), en="Chongyue", category="角色/明日方舟",
           variants=("钟古",),
           note="岁家大哥。ASR 常作 Chongu；'钟古'是音译残留，可裸键。"),
    Entity("安德切尔", modes=("bi",), en="Adnachiel", category="角色/明日方舟",
           ctx=((r"Adnachiel", "阿纳基尔"),),
           note="3★ 狙击。ASR 常作 Anakil。"),
    Entity("托兰", modes=("bi",), en="Toland Cash", category="角色/明日方舟",
           note="官方全名=托兰·卡什；字幕按口语用简称'托兰'。仅作元数据，无替换。"),
    Entity("卡门", modes=("bi",), en="Carmen", category="角色/明日方舟",
           note="官方全名=卡门·伊·伊比利亚。仅作元数据，无替换（'卡门'亦为常见音译名）。"),

    # =========================================================
    # 2026-10-05 明日方舟男干员婚姻梗 reaction 片沉淀
    #   素材：D:\原片\Why Will You Not Marry This Arknights Operator (2)\…en-谷歌翻译.calib.r2.srt
    #         （961 cue，英语原声 + 谷翻中文，CRLF 无 BOM）
    #   特征：谷翻对大量 AK 男干员/活动的音译错形。官方依据：PRTS/BWIKI/萌娘百科/英文wiki。
    #   通用中文词/常见音译（忏悔/乘客/赫拉/赫尔/尾田/织田/松木/诺西斯/西尔维/门）只走 ctx 英文锚定；
    #   非通用音译错形（特雷斯/多塞勒斯/多尔斯/伊利西姆/赫尔加/赫利格/安赛尔/Lumen/西尔维娅·阿什）进 variants。
    # =========================================================
    Entity("奥达", modes=("bi",), en="Odda", category="角色/明日方舟",
           ctx=((r"\bOda\b", "尾田"), (r"\bOda\b", "织田")),
           note="5★ 撼地者近卫（巴别塔活动）。ASR 常作 Oda。'尾田/织田'是日文姓氏，走 ctx。"),
    Entity("松桐", modes=("bi",), en="Matsukiri", category="角色/明日方舟",
           ctx=((r"\bMatsuki\b", "松木"), (r"\bMatsukiri\b", "松切")),
           note="5★ 先锋（本名森内彻，关东煮摊主）。ASR 常作 Matsuki/Matsukiri。'松木'是木材常见词，走 ctx。"),
    Entity("特雷西斯", modes=("bi",), en="Theresis", category="角色/明日方舟",
           variants=("特雷斯",),
           note="卡兹戴尔摄政王，特蕾西娅之兄。'特雷斯'是音译残留，可裸键。"),
    Entity("灵知", modes=("bi",), en="Gnosis", category="角色/明日方舟",
           ctx=((r"Gnosis|Nosis", "诺西斯"),),
           note="6★ 削弱者辅助，本名诺希斯·埃德怀斯（官方代号=灵知）。ASR 常作 Nosis。'诺西斯'走 ctx。"),
    Entity("赫拉格", modes=("bi",), en="Hellagur", category="角色/明日方舟",
           variants=("赫尔加", "赫利格", "Heliger"),
           ctx=((r"\bHela\b", "赫拉"), (r"\bHel\b", "赫尔")),
           note="6★ 无畏者近卫（乌萨斯老爷子）。ASR 常作 Helga/Heliger/Hela/Hel。"
                "'赫拉/赫尔'是通用中文词/希腊神名，走 ctx；'赫尔加/赫利格'等音译与英文残留可裸键。"),
    Entity("斥罪", modes=("bi",), en="Penance", category="角色/明日方舟",
           ctx=((r"penance", "忏悔"),),
           note="6★ 不屈者重装。'忏悔'是通用中文词，只走 ctx 锚定 penance。"),
    Entity("异客", modes=("bi",), en="Passenger", category="角色/明日方舟",
           ctx=((r"passenger", "乘客"),),
           note="6★ 链术师（凯尔希相关）。'乘客'是通用中文词，只走 ctx 锚定 passenger。"),
    Entity("流明", modes=("bi",), en="Lumen", category="角色/明日方舟",
           variants=("Lumen",),
           note="6★ 疗养师医疗。谷翻残留英文'Lumen'，统一为流明。"),
    Entity("极境", modes=("bi",), en="Elysium", category="角色/明日方舟",
           variants=("伊利西姆",),
           note="5★ 执旗手先锋。ASR 常作 Elisium；'伊利西姆'是音译残留，可裸键。"),
    Entity("银灰", modes=("bi",), en="SilverAsh", category="角色/明日方舟",
           variants=("西尔维娅·阿什", "Sylvia Ash"),
           ctx=((r"\bSylve\b", "西尔维"),),
           note="6★ 领主近卫（谢拉格军阀）。ASR 常作 Sylvia Ash/Sylve；'西尔维娅·阿什'是音译残留可裸键，'西尔维'走 ctx。"),
    Entity("多索雷斯假日", modes=("bi",), en="Dossoles Holiday", category="活动/明日方舟",
           variants=("多塞勒斯", "多尔斯"),
           ctx=((r"Door?s Holiday|Dors|Doselus", "门"),),
           note="SideStory 活动。ASR 常作 Dors/Doselus/Doors；'多塞勒斯/多尔斯'是音译残留可裸键，'门'是通用中文词走 ctx。"),
    Entity("安赛尔", modes=("bi",), en="Ansel", category="角色/明日方舟",
           variants=("Anel",),
           note="3★ 医师医疗（外形清秀）。ASR 常作 Anel（残留英文）。"),

    # =========================================================
    # 2026-10-01 鸣潮 3.7「镜锁妄世，心照红尘」日语初见直播（ガチ初見）片源沉淀
    #   素材：D:\原片\【ガチ初見】…【鳴潮 Wuthering Waves】\…ja-谷歌翻译.srt
    #         （3154 块 / 3132 cue，日语 ASR 参考行 + 谷翻中文，CRLF 无 BOM）
    #   特征：主播首次玩鸣潮 3.7（从今州序章开始），谷翻对**日语 ASR 的专名/术语**
    #         系统性误译。以下全部走 modes=("ja",)：普通中文词只进 ctx（日语行锚定），
    #         只有正常中文里不会出现的错形才进 variants。
    #   官方依据：库街区/BWIKI《鸣潮》名词表、灰机wiki（瑝珑/岁主/无音区/残象/天空海）、
    #             百度百科《心月狐》《岁主》、鸣潮JP wiki3.jp（白芷=ビャクシ）。
    # =========================================================
    Entity("漂泊者", modes=("ja",), ja="漂泊者",
           category="角色/主角/鸣潮",
           variants=("評白者", "ひ白者"),
           ctx=((r"脅迫者|評白者|表白者|漂白者|白者さん|ひ白者", "表白者"),
                (r"脅迫者|評白者|表白者|漂白者|白者さん|ひ白者", "漂白者"),
                (r"脅迫者|評白者|表白者|漂白者|白者さん|ひ白者", "漂白"),
                (r"脅迫者|評白者|表白者|漂白者|白者さん|ひ白者", "勒索者"),
                (r"脅迫者|評白者|表白者|漂白者|白者さん|ひ白者", "威胁者"),
                (r"脅迫者|評白者|表白者|漂白者|白者さん|ひ白者", "胁迫者"),
                (r"脅迫者|評白者|表白者|漂白者|白者さん|ひ白者", "威吓者"),
                (r"評白者|漂白者", "评白"),
                (r"評白者|漂白者|白者さん", "白物先生"),
                (r"評白者|漂白者|白者さん", "白先生"),
                (r"脅迫者|評白者", "威胁的人"),
                # 2026-10-14 补（鸣潮 2.4 七丘 ja 片实测）：
                (r"脅迫者|評白者|漂白者", "敲诈者"),
                (r"評白者|漂白者|脅迫者", "解说员")),
           note="鸣潮主角。日语官方名=漂泊者（ひょうはくしゃ）；ASR 常咬成 脅迫者(きょうはくしゃ)"
                "/評白者/表白者/漂白者/ひ白者。谷翻把 脅迫者 按字面译成 勒索者/威胁者/胁迫者。"
                "戒律：勒索者/威胁者/胁迫者/白先生/白物先生 都是正常中文词，只走日语行锚定 ctx，"
                "绝不进 variants。'百士/百紫' 属白芷（ビクシ），另见该实体。"),
    Entity("白芷", modes=("ja",), ja="ビャクシ",
           category="角色/鸣潮/今州",
           variants=("ビクシ", "ビク師", "ビクシー", "リクシー", "ヒャクシ"),
           ctx=((r"ビクシ|ビク師|リクシー|百士", "碧西"),
                (r"ビクシ|ビク師|リクシー|百士", "维克西"),
                (r"ビクシ|ビク師|リクシー|百士", "比克西"),
                (r"ビクシ|ビク師|リクシー|百士", "瑞克西"),
                (r"ビクシ|ビク師|リクシー|百士", "百紫"),
                (r"ビクシ|ビク師|リクシー|百士", "百石"),
                (r"ビクシ|ビク師|リクシー|百士", "白志"),
                (r"ビクシ|ビク師|リクシー|百士", "百志")),
           note="今州研究员，凝缩属性，武器种=增幅器，所属今州（wiki3.jp/WutheringWaves 确认 JP 名=ビャクシ）。"
                "日语 ASR 常作 ビクシ/ビク師/リクシー/百士；谷翻给出 碧西/Bikushi/维克西/比克西/瑞克西/"
                "百紫/百石 等不一致音译。'百士'亦见于 '私たち百士の友人'（我们是白芷的朋友）。"),
    Entity("令尹", modes=("ja",), ja="レイン",
           category="职衔/鸣潮/今州",
           variants=("霊員", "レ員", "礼員"),
           ctx=((r"レイン|霊員|レ員|礼員", "雷恩"),
                (r"レイン|霊員|レ員|礼員", "玲"),
                (r"レイン|霊員|レ員|礼員", "灵员"),
                (r"レイン|霊員|レ員|礼員", "礼员")),
           note="今州执政职衔=令尹（れいいん）；3.7 时任令尹=今汐（きんせき）。"
                "日语 ASR 咬成 レイン/霊員/レ員/礼員，谷翻音译成 雷恩/玲/河野玲。"
                "注：'今師/今石' 属今汐（见下一条），勿与令尹混。"),
    Entity("今汐", modes=("ja",), ja="今汐",
           category="角色/鸣潮/今州",
           ctx=((r"今師|今汐", "今石"), (r"今師|今汐", "今师")),
           note="今州令尹。日语 ASR 常作 今師（きんし）；谷翻作 '今石'（'本周的敬拜成员是今石'）。"),
    Entity("共鸣者", modes=("ja",), ja="共鳴者",
           category="术语/鸣潮",
           ctx=((r"共鳴者|共鳴", "共振者"), (r"共鳴者|共鳴", "共振腔"),
                (r"共鳴者|共鳴", "谐振腔"), (r"共鳴者|共鳴", "谐振器"),
                (r"共鳴者|共鳴", "共鸣器"), (r"共鳴者|共鳴", "同情者")),
           note="鸣潮核心术语，官方中文=共鸣者（Resonator）。谷翻对 共鳴者 的固定错译："
                "共振者/共振腔/谐振腔/共鸣器/同情者。均为普通中文词，只走日语行 ctx。"),
    Entity("残象", modes=("ja",), ja="残像",
           category="术语/鸣潮",
           ctx=((r"残像|残響", "残像"), (r"残像|残響", "残影"),
                (r"残像|残響", "残留影像")),
           note="鸣潮怪物统称，官方中文=残象（非'残像'；日语官方亦用 残像 但中文行须归一到 残象）。"
                "灰机wiki《残象》：'残象能够通过吞噬融合其他客观事物的频率来维持自身稳定'。"),
    Entity("无音区", modes=("ja",), ja="無音区",
           category="术语/鸣潮",
           ctx=((r"無音", "沉默"), (r"無音", "寂静"), (r"無音", "静寂"),
                (r"無音", "无声"), (r"無音", "沉寂")),
           note="鸣潮术语，官方中文=无音区（Tacet Field），残象的诞生区域，伴随'倒悬之海'与"
                "十字星状声痕（灰机wiki）。日语 ASR 作 無音/無恩ク/無恩音，谷翻按字面译成"
                "'沉默/寂静'（本片 cue 83/84/109/290/294/301/308 全是该术语）。"
                "戒律：沉默/寂静是正常中文词，只走日语行锚定 ctx。"),

    # --- 2026-10-25 鸣潮 4.0 新联邦 reaction 片（474 cue）二校沉淀 ---
    # 官方中文依据：百度百科「新联邦」「星炬学院」「无归的谬误」「阿布」、
    # 萌娘百科「爱弥斯」「伊冯」、鸣潮译名对照表（Sonoro Sphere / Tacet Mark）。
    Entity("新联邦", modes=("bi", "react"), en="New Federation",
           category="地区/鸣潮4.0",
           variants=("新灌溉",),
           ctx=((r"\bFederation\b", "联邦"), (r"\bNew\s*$", "New")),
           note="新联邦，鸣潮 4.0 新地区；官方中文=新联邦。谷翻「新灌溉」/「联邦」/残留 New "
                "均靠参考行锚定归此；裸「联邦」是通用词，不入扁平表。"),
    Entity("星炬学院", modes=("bi", "react"), en="Startorch Academy",
           category="势力/学院·鸣潮",
           variants=("星火学院", "星游学园", "星游学院", "罗伊斯塔尔学院"),
           ctx=((r"\bAcademy\b", "学院"),),
           note="官方中文=星炬学院（Startorch Academy）；学院 President=校长洛瑟菈。"
                "Academy 参考行锚定「学院」；EXCLUDE_CONTEXT 已排除 Academy Awards 等通用语境。"),
    Entity("索诺拉", modes=("bi", "react"), en="Sonoro Sphere",
           category="术语/鸣潮",
           variants=("Sonaro 球体", "Sonoro 球体", "Somnoire", "Som Noir", "Somnir", "Somnoir"),
           ctx=((r"\bSon(?:oro|aro)\s+spheres?\b", "球体"),),
           note="回音能量富集形成的超自然空间，官方中文=索诺拉（又称声之领域；Sonoro Sphere）。"
                "谷翻「Sonaro 球体」归此；「球体」通用词只走参考行锚定。"),
    Entity("无归的谬误", modes=("bi", "react"), en="Fallacy of No Return",
           category="敌人/声骸·鸣潮",
           variants=("回报的谬误", "归来的谬误"),
           note="泰缇斯系统构筑的最终防卫程序，官方中文=无归的谬误（Fallacy of No Return）。"
                "本片 ASR「fallacy of return」漏 No，谷翻「回报的谬误」归此。"),
    Entity("阿布拉克萨斯", modes=("bi", "react"), en="Abraxas",
           category="角色/鸣潮",
           variants=("Abrais", "A Brais", "A Braxis", "Arais",
                     "阿布拉伊斯", "阿布雷斯", "一个brais", "布拉克西斯人", "布拉克西斯"),
           ctx=((r"\b[Bb]raxis\b", "Braxis"),),
           note="阿布全名（Abraxas）；3.7 角色阿布的真名。本片 ASR Abrais/A Brais/A Braxis/Arais "
                "与谷翻「阿布拉伊斯/一个brais/布拉克西斯人」统一归此；昵称「阿布」另见 Entity(阿布)。"),
    Entity("莉莉", modes=("bi", "react"), en="Lily",
           category="角色/鸣潮3.8",
           note="3.8 衍射角色，官方中文=莉莉；本片 #333-336 提及，未实装。"),
    Entity("长离", modes=("bi", "react"), en="Changli",
           category="角色/鸣潮",
           variants=("Chang Lee",),
           ctx=((r"\bChang\s+Lee\b", "张李"),),
           note="今州角色，官方中文=长离（Changli）。本片 ASR「Chang Lee」，谷翻「张李」；"
                "中置信保留，若画面/音频另有指代则回退。"),
    Entity("伊冯", modes=("bi", "react"), en="Yvonne",
           category="角色/终末地",
           variants=("Ivonne", "Ivon", "伊冯娜"),
           note="《明日方舟：终末地》角色，官方中文=伊冯（Yvonne）。本片 #350 以「Ivonne」作对比；"
                "bi 模式补录，避免跨游戏片源残留音译。"),
    # ==== 2026-10-27 鸣潮 4.0 Lore Trailer《超越者》reaction 二次校准沉淀 ====
    # ASR 把官方英文专名听成常用词，谷翻再按字面直译；以下变体只在中文行残留英文串时
    # 无条件替换，字面错译（店主/塞罗诺德人/被动不和谐…）一律靠英文参考行锚定的 ctx 改。
    Entity("守岸人", modes=("bi", "react"), en="The Shorekeeper",
           category="角色/鸣潮",
           variants=("Shopkeeper",),
           ctx=((r"\b(?:Shopkeeper|Shorekeeper|Shortkeeper)\b", "店主"),
                (r"\b(?:Shopkeeper|Shorekeeper|Shortkeeper)\b", "掌柜")),
           note="4.0 预告 reaction #47/49/72/121：ASR 把 Shorekeeper 听成 Shopkeeper，"
                "谷翻字面「店主/掌柜」；两词是通用词，只走英文参考行锚定，不进扁平表。"),
    Entity("鸣式", modes=("bi", "react"), en="Threnodian",
           category="术语/鸣潮",
           variants=("Theronodian", "Thernodian"),
           ctx=((r"\b(?:Theronodian|Thernodian|Threnodian)\b", "塞罗诺德人"),
                (r"\b(?:Theronodian|Thernodian|Threnodian)\b", "塞罗诺迪安"),
                (r"\b(?:Theronodian|Thernodian|Threnodian)\b", "瑟诺迪亚人"),
                (r"\b(?:Theronodian|Thernodian|Threnodian)\b", "特诺迪安")),
           note="4.0 预告 reaction #151/152/180/185：ASR Theronodian/Thernodian，谷翻"
                "「塞罗诺德人/塞罗诺迪安/瑟诺迪亚人/特诺迪安」；旧元组已有瑟诺迪人/Thurnodian。"),
    Entity("残象", modes=("bi", "react"), en="Tacet Discord",
           category="术语/鸣潮",
           variants=("passive discord",),
           ctx=((r"\b(?:passive|tacet|tacid|taca)\s+discords?\b", "被动不和谐"),
                (r"\b(?:passive|tacet|tacid|taca)\s+discords?\b", "被动不和")),
           note="4.0 预告 reaction #48：ASR 把 Tacet Discord 听成 passive discord，"
                "谷翻「被动不和谐的大事」；通用短语只走英文锚定。"),
    Entity("残星会", modes=("bi", "react"), en="Fractsidus",
           category="势力/鸣潮",
           variants=("Fractious",),
           ctx=((r"\b(?:Fractious|Fractsidus)\b", "脾气暴躁"),),
           note="4.0 预告 reaction #140/141：ASR Fractious（Fractsidus 误听），谷翻「脾气暴躁」；"
                "既有 Fraidus/Fractus/Fracidus 变体保留。"),
    Entity("岁主", modes=("bi", "react"), en="Sentinel",
           category="术语/鸣潮",
           variants=("Sentinels",),
           note="鸣潮官方术语 Sentinel=岁主；扁平表已有 Sentinel->岁主、哨兵->岁主。"
                "补 Entity 供 audit 同词族扫描（4.0 预告 #119/149/181/185）。"),
    Entity("角", modes=("bi", "react"), en="Jue",
           category="角色/鸣潮",
           ctx=((r"\bJua\b", "朱阿"), (r"\bJua\b", "胡阿"),
                (r"\bJewel\s*A\b", "宝石A")),
           note="今州岁主「角」，官方英文 Jué（扁平表已有 哨兵 Chuy/Ju'e -> 岁主·角）。"
                "4.0 预告 reaction #44/45/119：ASR Jua/Jewel A，谷翻「胡阿/宝石A」；"
                "Jua 不入裸键（防咬 Juan），只走 \\bJua\\b 锚定。"),
    # --- 2026-10-27 Kiri Ahri 鸣潮演唱会/3.3 片二次校准沉淀 ---
    Entity("露米", modes=("bi",), en="Lumi",
           category="角色/鸣潮",
           variants=("Lumi", "卢米"),
           ctx=((r"\bLumi\b", "卢米"),),
           note="鸣潮 3.x 索诺拉活动物流队长露米（Lumi）；官方中文=露米。"),
    Entity("埃露西亚", modes=("bi",), en="Elucia",
           category="角色/鸣潮",
           variants=("Elucia", "埃露西娅", "埃卢西亚"),
           note="鸣潮 3.x 索诺拉活动角色埃露西亚（Elucia）；音译以官方中文为准。"),
    Entity("唐唐", modes=("bi",), en="Tang Tang",
           category="角色/鸣潮",
           variants=("Tang Tang", "Tanhoo"),
           note="鸣潮索诺拉活动物流队员唐唐（Tang Tang）；勿与终末地汤汤混淆，不入扁平表。"),
    Entity("吱吱", modes=("bi",), en="Squeaky",
           category="角色/鸣潮",
           variants=("Squeaky", "斯奎基"),
           ctx=((r"\bSqueaky\b", "斯奎基"),),
           note="鸣潮索诺拉活动中的小老鼠伙伴吱吱（Squeaky）。"),
    Entity("阿博拉", modes=("bi",), en="Abora",
           category="生物/鸣潮",
           variants=("Abora", "阿波拉"),
           ctx=((r"\bAbora\b", "阿波拉"),),
           note="鸣潮索诺拉活动背景中的生物阿博拉（Abora）。"),
    Entity("秘日六席", modes=("bi", "react"), en="Heliotix Six",
           category="设定/鸣潮",
           variants=("Heliotix Six", "Heliotic Six", "Helionic Six", "Heliodic Six", "赫利奥六号"),
           note="罗伊族长老团，官方中文=秘日六席；扁平表已有赫利奥六号等中文错形。"),
    Entity("罗伊族", modes=("bi", "react"), en="Roya",
           category="种族/鸣潮",
           variants=("Roya",),
           note="鸣潮罗伊族（Roya）；西格莉卡所属种族。"),
    # --- 2026-10-27 3.X 巡演/EP 二次校准补漏 ---
    Entity("日灵", modes=("bi",), en="Sun Spirit",
           category="生物/鸣潮",
           variants=("Sun Spirit", "Day Spirit", "Solless", "soul skin"),
           ctx=((r"\b(?:Solless|soul ?skin)\b", "小皮肤"),),
           note="罗伊族圣地浮光林的生灵，官方中文=日灵；ASR Solless/soul skin 需按语境归此。"),
    Entity("向彼方行", modes=("bi",), en="Alissium",
           category="动画/鸣潮",
           variants=("Alissium",),
           ctx=((r"\bAlissium\b", "极乐"), (r"\bAlissium\b", "伊利西姆")),
           note="《鸣潮：向彼方行》/Wuthering Waves: Elysium。戒律：不裸收 Elysium（明日方舟极境），只走 Alissium 或动画语境。"),
    Entity("怨鸟泽", modes=("bi",), en="Whining Aix's Mire",
           category="地名/鸣潮",
           variants=("Whining Aix's Mire", "whining Ajax's meer", "哀声鸷沼泽"),
           note="灯灯剧情发生地，官方中文=怨鸟泽；不是哀声鸷沼泽。"),
    Entity("乘霄山", modes=("bi",), en="Mt. Firmament",
           category="地名/鸣潮",
           variants=("Mt. Firmament", "Mount Firmament", "天穹山"),
           note="官方中文=乘霄山，不是天穹山。"),
]

