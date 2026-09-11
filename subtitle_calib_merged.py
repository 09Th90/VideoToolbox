# -*- coding: utf-8 -*-
"""字幕校准统一脚本（唯一入口，可复用，每次校准任务优先调用本脚本）

本文件是工作区全部历史校准脚本的统一沉淀（双语 calib_rules、韩语
calib_input_ko_out、终末地 calibrate_srt、排版 layout_merge2 已全部并入；
2026-08-29 再并入 srt_calibrator.py / fix_srt.py / fix_all.py / fix_simple.py
的通用术语表与 ERROR 行翻译表，以及 7 月 WW 演唱会脚本的通用专名），
其它脚本已删除，勿再另建平行脚本，新对照直接追加进本文件各表。
2026-08-29 起删除逐句台词改写（原 OVERRIDES / ENDFIELD_OVERRIDES / ERROR 行翻译），台词文案保留原始机翻，本脚本只做名词级校准。
2026-09-01 算法优化（输出与原实现逐字节一致）：术语表预编译为 长键序+键字符集（行级预筛、
命中统计与替换单遍完成）、CONTEXT_MAP 正则预编译、官方名词建首字索引（--layout 断行
保护不再对 2300+ 名词逐条 find）。

2026-09-10 新增【行宽上限】规则：每行字幕不宜超过 32 个汉字或 64 个英文字符
（等宽折算为 MAX_LINE_WIDTH=32，判据同一条）。`--layout` 会把超宽行递归拆到达标；
新增只读子命令 `length`，`verify` 也会自动体检并报告超宽行。详见第 4 节。

SRT 结构：序号 / 时间轴 / 中文行(被改) / 参考行(默认不改)。逐行原位替换，
严格保留 序号、时间轴、空行、换行(CRLF/LF) 与 BOM 一字不变；
参考行只有在显式加 --fix-en 时才会被修正。

术语沉淀（按用户规则，每次校准后把新发现的 错误->正确 对照追加进下表）：
  BILINGUAL_TERMS     中英双语片源专名/译名统一（鸣潮等，出现即改）
  CONTEXT_MAP         仅当参考行命中英文正则时才替换（仅双语模式）
  EXCLUDE_CONTEXT     负向排除：BILINGUAL_TERMS 高歧义词被替换后，参考行命中
                      英文正则（如 thank you 语境）则回滚（仅双语模式，2026-09-08）
  WORD_MAP            常见机翻错词（误译普通词）
  KO_TERMS            韩语原声片源（鸣潮）术语统一
  JA_TERMS/JA_CONTEXT 日语原声片源（鸣潮）术语统一 + 日语参考行上下文佐证
  ENDFIELD_TERMS      终末地片源术语统一
  EN_LINE_TERM_FIXES      英文/参考行 ASR 错词修正（仅 --fix-en 时应用）
  WW_OFFICIAL_NOUNS     鸣潮官方专有名词表（wiki.kurobbs.com + 中英日韩对照 md）
  ENDFIELD_NOUNS        终末地官方专有名词表（中英日韩对照 md，213 条）
  ARKNIGHTS_NOUNS       明日方舟官方专有名词表（中英日韩对照 md，581 条）
  PGR_NOUNS             战双帕弥什官方专有名词表（中英日韩对照 md，253 条）
                        四表并集供 --layout 断行保护，亦作后续匹配的官方名词底表
注意各片源术语按模式分开应用，勿混（如"谢谢你=能天使"是鸣潮角色名，
在韩语片源里是"谢谢"本意；终末地术语也不能套到鸣潮片源）。

ERROR 占位行回填（谷翻批量失败的高频场景；2026-09-10 3.6 日语反应片 492/663 条即此例）：
  ① 先统计首文本列 == "ERROR" 的 cue 占比；占比高即整体重译回填，勿只做术语替换；
  ② 按参考行（日语/韩语）分 6~8 批人工重译 -> 写 side_*.tsv（num<TAB>中文）。
     注：Write 工具写出的 side_*.tsv 带 BOM，读取必须 encoding="utf-8-sig"，
     否则首个 cue 号变成 "\ufeff2" 会被误判为缺失。
  ③ 生成 fix.tsv：num<TAB>ERROR<TAB>中文（old 用 "ERROR" 比空串更稳：等价整行覆盖，
     且只命中占位行）；真实机翻行的错译修正另表 num<TAB>old<TAB>new，两表可 cat 合并。
  ④ `subfix` 一次性回填 -> `verify`。真实机翻行的系统性误译（图片=え、一个=あ、
     は=牙齿、这是正确的=そうだな、マジ=真的 等）已沉淀进 JA_CONTEXT（日语正则锚定），
     戒律：这类"普通中文词"绝不可作为裸键进术语表，只能靠参考行正则锚定。

用法（双入口：术语校准 / 流水线子命令）：

A. 术语校准（REPLACE 入口，唯一通用校准脚本，可复用）:
  python subtitle_calib_merged.py <input.srt> [--out out.srt] [--report diff.md]
       [--ja|--jpe|--ko|--endo|--ak|--zho|--pgr] [--layout] [--fix-en]

  默认模式（中英/双语）：BILINGUAL_TERMS + CONTEXT_MAP + WORD_MAP 统一中文行。
  --ko     韩语原声模式：KO_TERMS 统一中文行术语（OVERRIDES 已删除）。
  --ja     日语原声模式：JA_TERMS 统一无歧义词，JA_CONTEXT 仅在日语参考行佐证时改歧义词（如 ハロー=你好而非"晕"）。
           （不带文件时用内置 KO_INFO 一键重跑）
  --jpe    日语原声·终末地模式：JA_ENDFIELD_TERMS 统一中文行（阿达希尔/佩丽卡/聂菲斯/庄方宜/
           终末地/武陵/巨兽心脏/星门 等），JA_ENDFIELD_CONTEXT 依日语行佐证。2026-09-10 沉淀。
  --endo   终末地模式：ENDFIELD_TERMS 统一全部文本行（ENDFIELD_OVERRIDES 已删除）。
  --ak     明日方舟本体模式：AK_TERMS 统一首中文行术语。（不带文件时用内置 AK_INFO 一键重跑）
  --zho    中文行专属模式：ZH_ONLY_TERMS 只改每个 cue 首中文行的英文噪音
           （仅首中文行，绝不动英文/参考行）。（不带文件时用内置 ZHO_INFO 一键重跑）
  --pgr    战双帕弥什模式：PGR_OVERRIDES_SRC 侧车逐 cue 整行覆盖（序号<TAB>校准后中文）。
           覆盖后不再叠加术语表（校准中文即终稿）。（不带文件时用内置 PGR_INFO 一键重跑）
  --layout 中文行排版：≥14 字长句在标点处拆两行（不切括号/官方专名，专名表见第 6 节
           WW/ENDFIELD/ARKNIGHTS/PGR 四表并集），短句保持单行。
           【行宽上限】每行字幕不宜超过 32 个汉字或 64 个英文字符（等宽换算，判据同一条）；
           拆两行后仍超宽的行按同一断行规则继续递归拆分，故一行可能拆出 2 行以上。
           上限常量见第 4 节 MAX_LINE_ZH / MAX_LINE_EN / MAX_LINE_WIDTH。
  --fix-en 英文/参考行修正：对 cue 内中文行以外的文本行应用 EN_LINE_TERM_FIXES
           （仅双语模式；默认参考行一字不动）。
  不传 --out 则只做"术语命中统计"，不改写文件。

B. 流水线子命令（原各项目分散脚本 extract_cues/split_segs/merge_rebuild/verify/
   gen_compare/scan_names/merge_compare 的统一入口，2026-08-31 并入）:
  python subtitle_calib_merged.py extract  <src.srt> <cues.tsv>            # 抽 cue 表 num/中文/英文
  python subtitle_calib_merged.py split    <cues.tsv> <outprefix> --n 6    # 切分段（用于并行校准）
  python subtitle_calib_merged.py merge    <src.srt> <表|目录> --out out.srt
        [--compare 对照.tsv] [--side 覆盖.tsv] [--letters ABCDEF]          # 回填校准段重建 SRT
  python subtitle_calib_merged.py verify   <src.srt> <out.srt>             # 校验结构零改动
  python subtitle_calib_merged.py compare  <src.srt> <out.srt> <对照.tsv>   # 生成 错误vs正确 对照
  python subtitle_calib_merged.py scan     <cues.tsv> [--min 2]            # 扫描待校准高频英文词
  python subtitle_calib_merged.py subfix   <src.srt> <fix.tsv> --out out.srt
        [--compare 对照.tsv] [--side 覆盖.tsv]                             # 逐 cue 子串修正（见下）
  python subtitle_calib_merged.py length   <a.srt> [b.srt ...] [--all]     # 行宽体检（只读）
        # length：逐行报告超过 32 汉字 / 64 英文字符的行（超限退出码 1，可作流水线门禁）；
        #   verify 也会自动附带同一体检。判据与上限见第 4 节。
        #   默认只查内容行（中文行）；--all 连参考行（原片语言，本脚本按契约不改）一并列出。
  python subtitle_calib_merged.py terms-check [表名...]                     # 术语表二次命中隐患自查
        # terms-check：检测“短键会命中另一条目替换结果”的二次替换隐患（长键降序 str.replace
        #   的固有陷阱，2026-09-10 终末地 ja_auto 项目沉淀：达希尔->阿阿达希尔、末地->终终末地）。
        # subfix：fix.tsv 每行 num<TAB>old<TAB>new；old 为空串=整行覆盖（ERROR 补译）。
        #   等价于原先各项目手写的 fix.py，今后逐条精修统一用本子命令，勿再另建 fix.py。
"""
import io
import os
import re
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
    "金阁": "金戈",                                                # Gigo / Jingo 地名
    "丹金": "丹瑾", "达宁": "丹瑾",                                # Danjin
    "迅哨": "岁主",                                                # Sentinel 岁主
    "哀歌者": "鸣式",                                              # 鸣式（鸣潮怪物）
    "灵魂誓约者": "昭日者",                                        # soul sworn 官方译名
    "光属性": "衍射属性",                                          # spectro 元素
    "谢谢你": "能天使",                                            # 角色名“能天使”被误译为“谢谢你”（仅名字语境）
    "沃奥": "阿尔图罗",                                            # Arcturo
    "日雪": "绯雪",                                                # Xueli?  绯雪
    "大建筑师": "残星会会长",                                      # Fractsidus 首领
    "暮羽": "木禺",                                                # Mu-Yu? 木禺
    "战狼": "Crywolf",                                             # 保留英文专名
    "男爵勋爵": "巴伦阁下",                                        # Lord Baron

    # --- 2026-08-29 并入：srt_calibrator.py CHINESE_TERM_FIXES ---
    "泰莎不和谐": "残象不和谐",                                    # Tacet Discord 整词优先
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
    "Gian": "Jiyan", "Chizzy": "Jiyan",
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
    "Mongo": "梦州",                                               # Mongjo/Mong 误听
    "Nethermancer": "幽客",                                        # 中文行残留英文
    "枯萎波": "鸣潮",                                              # Withering Wave -> Wuthering Waves（注意 枯萎 作动词"wither"时不改）
    # --- 2026-09-01 "This is the most I've ever cried over a game"(鸣潮) 校对沉淀 ---
    "西罗诺德": "鸣式",                                            # Thronodian（英文 asr 变体误音译 -> 官方名 鸣式）
    "伊梅思": "爱弥斯",                                            # Imeth/Immeth（asr 变体 -> 爱弥斯）
    "拉海洛伊": "拉海洛",                                          # Lahai-Roi（2026-09-09 依官方对照表/wiki 修正：官方中文=拉海洛，原误统一为"拉海罗伊"）
    "拉海罗伊": "拉海洛",                                          # 同上：旧沉淀目标"拉海罗伊"收敛回官方名（长键"拉海洛伊"先行）
    "西吉鲁姆": "辛吉勒姆",                                        # Sigilum（asr 变体，官方中文 辛吉勒姆，2026-09-10 依官方3.1内容说明/鸣潮助手修正）
    "埃克斯德": "隧者",                                            # Exorder（音译残留 -> 官方中文 隧者，依库街区/鸣潮助手图鉴）
    # --- 2026-09-01 同一鸣潮片源二次精修(fixin round2) 补充沉淀 ---
    "狄奥德": "鸣式",                                              # Theodian（asr 变体 -> 鸣式）
    "Exoriders": "隧者", "Exorider": "隧者",                       # Exostrider 复/单数变体（中文残留英文时统一为官方名 隧者）
    "舰队雪花": "弗利特·斯诺芙", "雪绒舰队": "弗利特·斯诺芙",      # Fleet Snowfl(uff)（VTuber 名，音译统一）
    "舰队雪绒": "弗利特·斯诺芙", "舰队雪绒花": "弗利特·斯诺芙",     # 长词优先；裸"雪绒/雪花/雪绒花"是普通词勿在此改
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
    # 弗利特·斯诺芙(Fleet Snowfluff) 英文残留（长键先行）
    "Fleet Snowfluff": "弗利特·斯诺芙", "Fleet Snowfl": "弗利特·斯诺芙",
    # 其它专名/术语
    "Syncrate": "同步率", "Solaris": "索拉里斯",
    "Strider Gate": "隧门", "Stridergate": "隧门",
    "逆雨": "溯洄雨", "风化浪": "鸣潮", "星火学院": "星炬学院",
    # --- 同片三次校准补充（Resonator/Lament/Astrite/Crownless 等鸣潮官方词 + ASR 变体）---
    "风化波": "鸣潮",                                              # Weathering Wave 系列
    "路虎": "漂泊者", "漫游车": "漂泊者",                          # Rover 被译成汽车品牌/火星车
    "同步员": "同步者",                                            # synchronist 统一
    "异能跨步者": "隧者", "跨行者": "隧者",                  # exor strider 机翻/简写
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
    "虚空风暴": "虚质风暴", "虚空风暴潮": "虚质风暴潮",             # Void Storm 官方中文=虚质风暴（拉海洛灾难，依官方剧情文本）
    "星游学园": "星炬学院",                                         # Star Tour Academy = 星炬学院 ASR 变体（#15214）
    "Laai Roy": "拉海洛",                                           # Lahai-Roi ASR 变体（#4278 Laai Roy is my responsibility）
    "舰队雪毛": "弗利特·斯诺芙",                                    # Fleet Snowfluff（#18043）
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
    "塔塞特人": "残象", "塔塞特": "残象", "Tacet 不和": "残象不和谐",
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
    # 西格莉卡（Sigrika，星矩学院新生/返归者；官方中文依库街区，英文 Sigrika/西格莉卡已有名词表）
    "Sigi": "西格莉卡", "Sigy": "西格莉卡", "Siga": "西格莉卡", "Sigria": "西格莉卡",
    "西吉": "西格莉卡", "西加": "西格莉卡", "锡格利亚": "西格莉卡", "西格琳卡": "西格莉卡",
    # 洛瑟菈（Lucilla，星矩学院校长；官方中文依库街区 wiki/3DM/sina 确认）
    "Lucilla": "洛瑟菈", "露西拉": "洛瑟菈", "卢西拉": "洛瑟菈", "洛西拉": "洛瑟菈",
    # 绯雪（Hiuki/Hyuki，星矩学院巫女，官方 ja 名=ひゆき；英文形残留入表）+ 中文机翻"希希"
    "Hiuki": "绯雪", "Hyuki": "绯雪", "希希": "绯雪",
    # 千咲（Chisa，星矩学院/解弦之眼；已有英文键，补中文机翻形态）
    "奇莎": "千咲", "奇萨": "千咲",
    # 达妮娅（Denia/Dana，星矩学院学生；"达纳"为 Dana 中文机翻）
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
    "鲁瓦扬": "罗伊", "鲁瓦安": "罗伊", "鲁扬": "罗伊", "罗亚内斯": "罗伊", "Royanes": "罗伊",
    # 弗洛洛(Phrolova) 机翻变体
    "Froolova": "弗洛洛", "Froloova": "弗洛洛", "芙罗洛娃": "弗洛洛",
    # 残星会会长(Grand Architect)：修"伟大建筑师"被"大建筑师"键咬出"伟残星会会长"的半截残形
    # 注意：必须同时收 "伟大建筑师"（5 字），否则会被既有 "大建筑师"(4 字) 键咬成 "伟残星会会长"
    "伟大的建筑师": "残星会会长", "伟大建筑师": "残星会会长", "盛大建筑师": "残星会会长",
    "Grand Architect": "残星会会长", "grand architect": "残星会会长",
    # 漂泊者(Rover) ASR 变体 Wover
    "Wover": "漂泊者", "沃弗": "漂泊者",
    # 库洛(Kuro Games) 英文残留
    "Kuro games": "库洛", "Curo Games": "库洛",
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
    # 琳奈(Linny/Lenna，星炬学院预科班学生)：ASR 变体 Lenny/Linny
    "Linny": "琳奈", "Lenny": "琳奈", "林尼": "琳奈", "莱尼": "琳奈",
    # 莫宁(Mornye，深空联合研究院学者/星炬学院教授)：ASR 变体 Mouier/Mor
    "Mouier": "莫宁", "Mornye": "莫宁", "莫尔教授": "莫宁教授", "穆耶教授": "莫宁教授",
    # 西格莉卡(Sigrika，星炬学院学生/罗伊符文共鸣者)：ASR 变体 Skiprika/Skip Raa
    "Skiprika": "西格莉卡", "Skip Raa": "西格莉卡", "斯基普里卡": "西格莉卡",
    # 铃(Suzu)：绯雪共鸣能力「预求身」的引子，官方中文=铃；ASR 作 sudsu
    "sudsu": "铃", "Suzu": "铃",
}

# 保留英文不译的专名（仅提示，不替换）
KEEP_EN = {"Crywolf"}

# 上下文相关替换：仅当 参考行 命中该英文正则时才把中文里的错误形式替换掉（仅双语模式）
CONTEXT_MAP = [
    # (英文正则, 仅当英文行匹配时才把中文里的某错误形式替换为正确形式)
    (r"\bScar\b", "疤痕", "伤痕"),
    (r"\bDena\n?Denia\n?Denu\b", None, None),  # 占位示例，无实际用途
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
    (r"\bShin\b", "申", "心月狐"),          # Shin = Sheen 心月狐（仅英文佐证时改，防误伤"申请/申明"）
    # --- 2026-09-04 THIS_IS_CRAZY_Hsin 二次校准：需英文佐证的常见机翻错词（可复用于抽卡 Reaction 片源）---
    (r"\bswimming\b", "游泳", "锁暝"),             # swimming 是 Suoming(锁暝) 的 ASR 误听，非"游泳"
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
    # 梦州(Mengzhou/Mango/Mongjo) 变体
    (r"\bMango\b", "芒果", "梦州"),               # #61 带他们游梦州
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
    # 景燃(Jingran，寻幽客=幽客，幕间「幽客销残声」主角；Nethermancer) ASR 变体
    (r"\bJing Rang\b", "靖让", "景燃"),            # #332 景燃的狮子（白泽）
    (r"\bJingron\b", "靖荣", "景燃"),              # #336/#990
    (r"\bJingron\b", "靖隆", "景燃"),              # #649
    (r"\bJron\b", "杰伦", "景燃"),                 # #861 Jron=Jingron
    (r"\bnethermancer\b", "虚空巫师", "幽客"),      # #524
    (r"\bnethermaner\b|\bnethermancer\b", "虚空者", "幽客"),   # #858
    # 心月狐(Sheen/Shin/Shane，月狐岁主) ASR 变体
    (r"\bShane\b", "肖恩", "心月狐"),              # #1031
    (r"\bShin\b", "辛", "心月狐"),                 # #85 心月狐发来消息
    (r"\bShin\b", "胫", "心月狐"),                 # #86
    # 炽霞(Chixia) 变体
    (r"\bChisha\b", "赤煞", "炽霞"),               # #406 炽霞与秧秧
    # 吟霖(Yinlin) 变体
    (r"\bYin Llin\b", "尹琳", "吟霖"),             # #1244 我的精灵女王
    # 木禺(Muyu) 变体（圆圈/圆形的/穆/穆约）
    (r"\bMuyu\b", "圆圈", "木禺"),                 # #364
    (r"\bMuyu\b", "圆形的", "木禺"),               # #1177
    (r"\bMuyo\b", "穆约", "木禺"),                 # #283
    (r"\bWhere is Mu\b", "穆", "木禺"),            # #882
    # 残象(Tacet) ASR 变体（泰泰特/tacid话语）
    (r"\btacet\b", "泰泰特", "残象"),              # #1045
    (r"\btacid\b", "冷漠的话语", "残象不和谐"),      # #278 These tacid discourses
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
    (r"\bpsycho\b", "心理", "疯子"),               # #559
    (r"\bmastermind\b", "大师", "主谋"),           # #594
    (r"\bmaintain the lane\b", "车道", "链接"),     # #671 维持链接
    (r"\bsowed\b|\bswed\b", "瑞典", "播下的"),      # #1069 木禺播下的混乱
    (r"\bmain frames?\b", "主要框架", "主框架"),    # #1082
    (r"\bcivilization capsule\b", "文明舱", "文明胶囊"),   # #957
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
    (r"\bAngel\b", "天使", "安吉尔"),               # #719/#954
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
    (r"\bKnights\b", "骑士", "明日方舟"),             # 名字跨 cue 被拆成 方舟/骑士 时后半补全（#886）
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
]

# =============================================================
# 2026-09-09 I_Was_Wrong_Completely_About_Wuthering_Waves（鸣潮 椿伴星任务 Reaction 片）校准总结
#   片源：I_Was_Wrong_Completely_About_Wuthering_Waves_en_auto.srt（中英双语，1315 cues）
#   模式：bi。78 处中文行改动，序号/时间轴/参考行/空行/换行/BOM 原样保留。
#   错误形式 -> 正确形式（对照，均依官方名/原文修正，已入 BILINGUAL_TERMS/CONTEXT_MAP）：
#     罗孚/路虎/漫游者/Ruva/Ruver/鲁瓦/鲁弗 -> 漂泊者（Rover ASR 变体）
#     岸边管理员/海岸警卫队/海岸守护者/做空者/岸守/肖战守护者/Shawkeeper -> 守岸人（Shorekeeper）
#     Chamellia/Chameleia/Chamelia/Camila/卡米拉/茶花属/茶花/变色龙 -> 椿（Camellya，黑海岸执花）
#     布隆伯/布卢姆伯/绽放者 -> 执花（Bloombearer，黑海岸成员称号）
#     塔塞特(人)/Tacet 不和 -> 残象（Tacet Discord）
#     Tethus/teth系统 -> 泰缇斯（Tethys 系统，守岸人辅助的运算核心）
#     斯特拉矩阵 -> 恒星矩阵（Stellar Matrix）
#     布莱克酒店/黑色海岸/黑岸/布莱克的领导者 -> 黑海岸（Black Shores）
#     Wolvering Waves/翼波 -> 鸣潮（Wuthering Waves ASR 误听）
#   [手动修复] ERROR 占位 3 处（#740/#916/#1181）按参考行补译；#515 布莱克绽放=黑花(Black blooms)；
#   #9 上集回顾 翼波->《鸣潮》；#704/#707/#708/#1144 黑海岸跨行断句理顺；#1287 TVA=时间变异管理局。
#   [不确定项] ①Aalto(#13 阿尔托)官方中文名待核(疑阿托)；②Enrew(#20 恩鲁)疑 Encore 安可，未改；
#   ③Beatrice(#532/#534/#1180) 音译 比阿特丽斯 待官方核实；④Pedalfall Village 官方译名未知，保留音译；
#   ⑤stellar matrix 官方译名待核(暂用 恒星矩阵)；⑥forte=强项、rebel test=反叛者测试 官方术语待核；
#   ⑦aerosel=气溶胶、Blasar=布拉萨尔、Eden=伊登、Yugi=勇利、梅伊(mey) 等玩梗/歌词按音译保留。
#   二次校准（检索官方中文后，累计 88 处）：
#     恩鲁/Enrew -> 安可（Encore，黑海岸客卿，官方）
#     踏板落村/Pedalfall(Village)/Pedaphor村/Petal Fall -> 落香村（椿被救村庄，官方依鸣潮助手图鉴/剧情）
#     死灵星/Necrostar -> 噬亡星（黑海岸黑洞，官方依库街区 wiki）
#     调制大厅/modulation hall -> 调律大厅（黑海岸设施，官方依库街区 wiki）
#   [二次校准确认无误] Aalto=阿尔托（Theria 中文指南），不改；泰缇斯(Tethys) 确认。
# =============================================================

# =============================================================
# 256 2026-09-08 WW 2.7 Story Quest Highlight（gacha reaction）校准总结
#   片源：【字幕】I cannot believe this is a gacha game - WW 2.7
#   模式：bi（中英双语）。51+ 处文本改动，序号/时间轴/空行/换行/BOM 原样保留。
#   错误形式 -> 正确形式（对照）：
#     基督波弗罗/克里斯托弗罗 -> 克里斯托弗   (Christophoro 各变体)
#     坎特雷拉/卡内拉/卡内雷拉/卡内利拉/康特拉/卡提拉/卡蒂/克特雷拉
#                           -> 坎特蕾拉       (Cantarella=坎特蕾拉·翡萨烈)
#     利维坦                  -> 利维亚坦       (Leviathan=2.7 鸣式 BOSS)
#     漫游者/漫游车/罗孚/罗弗 -> 漂泊者         (Rover)
#     阳阳                    -> 秧秧           (Yangyang)
#     蒙特利斯                -> 莫塔里         (Montelli=珂莱塔·莫塔里家族)
#     靖州/荆乔                -> 今州           (Jingjo/Jing Joe)
#     天使                    -> 安吉尔         (Angel 角色名；参考行为 Angel 时)
#     谐振器                  -> 共鸣者         (Resonator 官方译名)
#     疤痕                    -> 伤痕           (Scar 角色；拉链人)
#     原真                    -> 原神           (Genshin)
#     Wua/瓦阿                -> 鸣潮           (主播对 WuWa 的昵称)
#   [二期对照；2026-09-08 二次校准，检索官方中文后统一] 共 61 处
#     waifu 佐证 外婆->老婆；Frover 佐证 弗漂泊者->弗罗弗(自动救回 BILINGUAL 误伤,不再人工)
#     Abby/Aby 佐证 艾比->阿布（官方名，真名阿布拉克萨斯）；Abbyus/Abrais 佐证 阿布雷斯->阿布拉克萨斯
#     Septimont 佐证 塞普蒂蒙->七丘；Lupa/Lup 佐证 卢帕/卢普->露帕
#   [不确定项] ①Ginshi->今汐(#221,主播口音,疑为 Jinhsi)；②Trinodian/Throdian/Sorodians
#   阵营名音译不一(疑鸣式阵营,无官方对应),保留音译未统一；③"索罗狄安""弗罗弗和莫尔"等主播自造词按音译保留。
#   已解决边界：BILINGUAL"罗弗"->漂泊者 对"弗罗弗"的子串误伤，已用 CONTEXT_MAP Frover->弗罗弗 自动兜底。
# =============================================================

# 预编译上下文规则：正则只编译一次，占位规则(wrong/right 为 None)剔除；
# 应用时先查 wrong 是否出现在中文行，再跑正则，避免无谓匹配。
_CONTEXT_COMPILED = [(re.compile(rx, re.I), wrong, right)
                     for rx, wrong, right in CONTEXT_MAP if wrong and right]

# --- 2026-09-08 负向排除上下文（高歧义词防护，仅双语模式）---
# BILINGUAL_TERMS/CONTEXT_MAP 中个别词在特定口语/非游戏语境会误伤。例：
#   谢谢你=能天使 是角色名译名，但口语/闲聊片源（如 Thanks La 讨论片）整片"谢谢你"
#   都是字面 thank you；帐篷=十连 是抽卡术语，但语言讨论语境 tent 是 text 的 ASR 误听。
# 机制：术语被替换后，若参考行(英文)命中下列任一排除正则，回滚该替换并从命中统计移除。
# 结构：{wrong: (right, (排除正则...))}，right 用于回滚（须与所在术语表的 value 一致）。
# 比无条件替换更精准，不依赖人工负例注释。新增歧义词时按此结构追加。
EXCLUDE_CONTEXT = {
    "谢谢你": ("能天使", (r"\bthanks?\b", r"\bthank you\b", r"\bty\b")),   # 字面致谢语境
    "帐篷": ("十连", (r"\bwritten tent\b",)),                              # 语言讨论语境 tent=text 误听
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
}
_EXCLUDE_COMPILED = {w: (right, [re.compile(rx, re.I) for rx in rxs])
                     for w, (right, rxs) in EXCLUDE_CONTEXT.items()}

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
# 1.5 日语原声片源资产（鸣潮；2026-09 锁暝/心 战斗先行片沉淀）
#   参考行为日语 ASR、中文行为机译，两类资产：
#     JA_TERMS    无歧义中文机译错形 -> 正确（仅收正常中文里不会出现的错形，鸣潮日语片专用）
#     JA_CONTEXT  (日语参考行正则, 中文错形, 正确)：必须日语行佐证才改，防普通词误伤
#   戒律：日语片 ありがとう=谢谢本意，故日语模式绝不加载 BILINGUAL_TERMS
#   （其"谢谢你->能天使"在日语片是误伤）；ジラ 前半=自分(自己)、后半抽卡语境=心，
#   这类随语境翻转的词不进自动表，留给 extract/split 后的人工分段校准。
# =============================================================
JA_TERMS = {
    # —— 锁暝（サメイ/サメちゃん = Suoming）的机译/音译错形 ——
    "鲫美酱": "锁暝", "鲛美酱": "锁暝", "鲇美酱": "锁暝", "萨米酱": "锁暝",
    "鲨鱼酱": "锁暝", "萨姆酱": "锁暝", "小沙姆": "锁暝", "萨梅伊": "锁暝",
    "鲛名酱": "锁暝",
    # —— 心（シ様/シン様 = 心月狐 Hsin）的机译错形（鸣潮片专用）——
    "师大人": "心", "辛大人": "心", "史大人": "心", "新様": "心",
    # ⚠ 2026-09-10 反证（3.6《烟云幽远心剑鸣》ja_auto 片，官方剧情逐句对上）：
    #   该片 ASR「聖書／聖式／聖／聖長さん」实为「清宵（司骑）」（セイショウ），非心。
    #   本条「聖書様→心」保留（可能在更早的 心＆鎖瞑 前瞻片语境下成立），但遇 3.6 主线片
    #   须先按 cue 判断说话人：心=シ/シン様、清宵=聖/聖書/聖式。本次全程未触发本条。
    "聖書様": "心", "圣书様": "心", "C様": "心",
    # 2026-09-10 3.6 片（烟云幽远心剑鸣）：谷翻音译残留 + 官方用字归一
    "亚彦": "秧秧",                                   # Yangyang 音译残留
    "锁瞑": "锁暝",                                   # 官方用字为「锁暝」（外部资料常误作「锁瞑」）
    "谛天监": "谛天鉴",                               # 锁暝执掌的组织（官方「谛天鉴」）
    # —— 其他鸣潮角色/专名 ——
    "艾姆斯": "爱弥斯", "艾梅斯": "爱弥斯",            # エメス/エイメス = Imeth
    "笛卡尔": "卡提希娅",                            # カルテジア = Cartethyia（鸣潮片，非哲学家笛卡尔）
    "坎塔雷拉": "坎特蕾拉",                          # カンタレラ = Cantarella
    # —— 鸣潮玩法/系统术语 ——
    "联合攻击": "协同攻击",                          # 共同攻撃 = 协同攻击
    "共鸣释放": "共鸣解放",                          # 共鳴解放 = 共鸣解放（大招）
    "贝壳币": "贝币",                                # シェルコイン = 贝币
    "扩音器": "增幅器",                              # 増幅機 = 增幅器（武器类型）
    "席大人": "心",                                  # シ様 = 心（心月狐），2026-09-09 心＆鎖暝先行片
    "丹尼娅": "达妮娅",                              # ダーニャ = 达妮娅（Denia，官方对照表）
    "丹妮娅": "达妮娅",
}

# (日语参考行正则, 中文错形, 正确)：仅当日语行命中正则、且中文行含错形时才替换
JA_CONTEXT = [
    (r"ハロー|ハロ", "晕", "你好"),                  # ハロー(Hello) 被全篇误译成"晕"
    (r"ノー[ー]?サウンド", "总理", "全程"),           # ノーサウンド総=全程无声，"総"误作"总理"
    (r"チェンソ", "连锁店", "电锯"),                 # チェンソー=电锯，非"连锁"
    (r"センキュー", "仙九", "Thank you"),            # センキュー=Thank you 空耳
    (r"エンドフィールド", "恩菲尔德", "终末地"),       # Endfield=终末地
    (r"インリン?", "映里", "吟霖"),                  # インリン=吟霖（ン可被ASR吞）
    (r"インリン?", "英灵", "吟霖"),
    (r"千里", "战略之路", "千里之行"),                # 千里の道=千里之行
    (r"千里", "受益之路", "千里之行"),
    (r"領域展開", "面积扩张", "领域展开"),            # 領域展開=领域展开
    # --- 2026-09-09 心＆鎖瞑の先行動画（鸣潮 锁暝/心 战斗先行片，ja_auto 谷歌翻译）沉淀 ---
    (r"ラハイロイ", "拉海·雷 (Lahai Loi)", "拉海洛"),  # 官方对照表：拉海洛/Lahai-Roi/ラハイロイ（带谷歌英注整段改）
    (r"ラハイロイ", "拉海洛伊", "拉海洛"),             # 同上（BILINGUAL 目标 2026-09-09 已由"拉海罗伊"修正为官方"拉海洛"）
    (r"エクソ[レラ]イダー", "Exorider", "隧者"),        # エクソストライダー=隧者（官方 ja 名）的 ASR 变体
    (r"ひゆき", "日雪", "绯雪"),                       # 绯雪（3.3 共鸣者，官方 ja 名=ひゆき，wiki 确认）
    (r"ジャン(?!ル)", "吉恩", "忌炎"),                 # ジャン=Jiyan 英语读法（官方 ja 名キエン，日语圈惯用ジャン；排除ジャンル）
    (r"アルフ", "阿尔夫一", "阿列夫一"),               # 先长后短：アルフワン=阿列夫一（鸣式 BOSS，官方名词表内）
    (r"アルフ", "阿尔夫", "阿列夫一"),                 # 吞噬存在的鸣式 Alfan（官方中文 阿列夫一，2026-09-10 统一）
    (r"ソラリス", "Solaris", "索拉里斯"),              # ソラリス=索拉里斯（官方名词表内）
    # --- 2026-09-09 心＆鎖暝先行片 二次校准沉淀（官方对照表/wiki 核实）---
    (r"サメ", "鲨鱼", "锁暝"),                        # サメ=锁暝（サメイ 简称；本片即锁暝实机，伞+锁链变形武器）
    (r"カカロ", "卡卡罗", "珂莱塔"),                   # カカロ=カルロッタ=珂莱塔·莫塔里（官方对照表）
    (r"カカロ", "卡卡洛", "珂莱塔"),
    (r"カロ", "莫卡罗", "珂莱塔"),                     # "も(も)カロ"=也…珂莱塔（助词も被机翻吞）
    (r"カロ", "卡罗", "珂莱塔"),
    (r"インディ", "印度语", "吟霖"),                   # インディ(ン)=インリン=吟霖（ASR 变体；锁链束缚攻击语境佐证）
    (r"インディ", "印第", "吟霖"),
    (r"インディ", "印丁", "吟霖"),
    (r"インディ", "印地", "吟霖"),
    (r"ルパブキ", "卢巴布基", "露帕武器"),              # ルパ+ブキ(武器) 连读被音译
    (r"ルパ", "卢帕", "露帕"),                        # ルパ=露帕（Lupa Silva，官方对照表）
    (r"インペラトル", "Imperator", "英白拉多"),        # インペラトル=英白拉多（Imperator，官方对照表）
    (r"インペラトル", "皇帝", "英白拉多"),
    (r"セブン・?ヒルズ", "七丘陵", "七丘"),             # セブン・ヒルズ=七丘（Septimont，官方对照表）
    (r"アンコ", "Anko", "安可"),                      # アンコ=安可（Encore，官方对照表）
    (r"ロコ", "Loco", "洛可可"),                      # ロコ=洛可可（Roccia，官方对照表）
    (r"共鳴", "同情者", "共鸣者"),                     # 共鳴者=共鸣者（Resonator，官方词，机翻误作"同情者"）
    (r"フィジカル", "体力", "物理"),                   # フィジカル=物理（属性语境，非"体力"）
    (r"オーガサ", "螺旋钻", "奥古斯塔"),               # オーガスタ ASR 吞音变体（机翻瞎译"螺旋钻"）
    (r"シは|シが|シも|シの", "石", "心"),              # シ=心（心月狐），单字片假名被机翻成"石"
    # --- #476 共鳴→表明 ASR 近音误听（きょうめい→ひょうめい），机翻跟着错译成"清单" ---
    (r"表明解放", "清单释放", "共鸣解放"),               # 共鳴解放=共鸣解放（官方词）
    (r"表明回路", "清单电路", "共鸣回路"),               # 共鳴回路=共鸣回路（官方词，攒满触发强化/召唤形态）
    # --- 2026-09-10 3.6《烟云幽远心剑鸣》ja_auto 谷歌翻译片（663 cue / 492 条 ERROR 占位回填）沉淀 ---
    #     谷翻对**超短 ASR 行**的系统性误译；全部用日语参考行正则锚定，
    #     防"一个/所以/肯定/和/牙齿/图片"等普通中文词在别的语境被误伤。
    #     本片 ASR 专名（官方剧情逐句对上）：聖/聖書/聖式=清宵（**非心**）、シ/シン様=心、
    #     やんやん=秧秧、原場/現法地/原闘場=玄方、最主/最種=岁主、調理/チ理=长离、
    #     ひ白者/ひょ君/ひちゃん=漂泊者、停天=谛天鉴、サメ=锁暝、カルッタ=珂莱塔。
    #     官方依据：库街区《烟云幽远心剑鸣》剧情原文 + 3.6/3.7 官方角色档案。
    (r"^\s*え[、,?？]?\s*$", "图片", "诶"),              # え → "图片"（谷翻系统性误译）
    (r"^\s*え、?\s*$", "呃", "诶"),                      # え → "呃"
    (r"^\s*あ[、,]?\s*$", "一个", "啊、"),                # あ、→ "一个"
    (r"^\s*は[、,]?\s*$", "牙齿", "哈"),                 # は → "牙齿"
    (r"そうだな|そうだよ|そうなんだよね", "这是正确的", "是啊"),
    (r"^\s*マジ[?？]?\s*$", "严重地", "真的"),           # マジ? → "严重地？"
    (r"^てめえ", "特米", "你这家伙"),
    (r"^\s*嘘[。、]?\s*$", "说谎", "骗人"),
    (r"^\s*やば\s*$", "哦不", "糟了"),
    (r"^やった", "我做到了", "太好了"),
    (r"^\s*すげえ\s*$|^\s*すご\s*$", "惊人的", "好厉害"),
    (r"^おいおい", "嘿嘿嘿嘿", "喂喂喂喂喂"),
    (r"^\s*おい\s*$|^\s*おえ\s*$", "嘿", "喂"),
    (r"^そんなに", "所以", "那么"),
    (r"^\s*か\s*$", "蚊子", "吗"),
    (r"^\s*確か\s*$", "肯定", "确实"),
    # 谛天鉴：锁暝执掌、专管岁主事务的组织；勿与「天工部」混（日语 ASR 常见 停天/諦天鑑）
    (r"諦天鑑|谛天鑑|停天|ていてん", "天工", "谛天鉴"),
]
_JA_CONTEXT_COMPILED = [(re.compile(rx), wrong, right) for rx, wrong, right in JA_CONTEXT]

# =============================================================
# 1.3 日语原声 · 明日方舟：终末地 片源资产（2026-09-10 沉淀自
#     《JP VTubers LOST THEIR MINDS! (From Ardashir mainly...) Arknights
#      Endfield Chapter 2 [Part 3]》ja_auto 谷歌翻译片，762 cue）
#     用法：python subtitle_calib_merged.py <input.srt> --jpe [--out out.srt] [--report diff.md]
#     只改每个 cue 的首中文行（日语参考行一字不动），与 --ja(鸣潮) 术语严格分开。
#     官方中文依据：萌娘百科《阿达希尔》《佩丽卡》条目、endfield.wiki.gg(Ardashir)、
#     butwhytho.net 1.2 评测、3DM《终末地第二章剧情介绍》：
#       阿达希尔 Ardashir(アルダシル) / 佩丽卡 Perlica(ペリカ) / 陈千语 Chen(チェン) /
#       聂菲斯 Nefarith(ネファリス) / 庄方宜 Zhuang Fangyi(ゾアン・ゾン) / 弧光 Arcane(エン) /
#       管理员 Endministrator(管理人) / 终末地 Endfield(エンドフィールド) /
#       武陵 Wuling(武) / 巨兽心脏 Feranmut Heart(ASR 居住の心臓=巨獣の心臓) /
#       首墩 Marker Stone / 应龙 Yinglung(応龍) / 星门 Cosmic Gate(正門=星門) /
#       超域 Æther(上域) / 耶尔什 Yersh(エルシェ) / 帕夏 Pasha(パーディシャー) /
#       第纳尔金币 Ancient Gold Dinar(ディナール) / 画卷 Ink Scroll(絵巻)。
#     机翻误词（本片统计）：凉爽的=かっこいい(10)、不挂断=待って(10)、图片=え、(5)、
#       管理层/管理人=管理员、结束场/结束字段/末地=终末地、正门=星门。
# =============================================================
JA_ENDFIELD_TERMS = {
    # —— 阿达希尔 Ardashir（机翻音译/英文残留，全部统一）——
    "阿尔达西尔": "阿达希尔", "阿达西尔": "阿达希尔", "阿尔达希尔": "阿达希尔",
    "阿尔达塞尔": "阿达希尔", "阿尔达舍尔": "阿达希尔", "阿尔达谢尔": "阿达希尔",
    "阿尔纳齐尔": "阿达希尔", "阿尔纳希尔": "阿达希尔", "阿尔扎尔": "阿达希尔",
    "阿尔达希": "阿达希尔",
    # 注：不能用裸键"达希尔"——长键先替换成"阿达希尔"后，短键"达希尔"会二次命中得到"阿阿达希尔"；
    #     裸"达希尔"本片仅 #458 一处，逐 cue 侧车处理。
    "Altashell": "阿达希尔", "Ardacil": "阿达希尔", "Aldasil": "阿达希尔",
    "Ardashir": "阿达希尔",
    # —— 佩丽卡 Perlica（终末地工业监督）——
    "费利卡": "佩丽卡", "维莉卡": "佩丽卡", "佩里卡": "佩丽卡", "赫利卡": "佩丽卡",
    "佩莱卡": "佩丽卡", "佩利卡": "佩丽卡", "贝利卡": "佩丽卡", "佩雷卡": "佩丽卡",
    "贝莉卡": "佩丽卡",
    # —— 聂菲斯 Nefarith（第二章反派之一）——
    "奈法里斯": "聂菲斯", "奈里斯": "聂菲斯", "尼法利斯": "聂菲斯",
    "涅法利斯": "聂菲斯", "内法里斯": "聂菲斯",
    # —— 庄方宜 Zhuang Fangyi（武陵执政官，ASR ゾアン/ゾン/ゾワン）——
    "佐安": "庄方宜", "佐恩": "庄方宜", "佐万": "庄方宜", "佐阿": "庄方宜",
    "祖涵": "庄方宜", "祖安": "庄方宜", "Zowan": "庄方宜",
    # —— 终末地 Endfield（机翻把 エンドフィールド 译成"结束场/末地"等）——
    "明日方舟末地": "明日方舟：终末地",
    "恩菲尔德": "终末地", "结束场": "终末地", "结束字段": "终末地",
    "结束的方式": "终末地", "终场": "终末地",
    # 注：不能用裸键"末地"（"明日方舟末地"长键替换成"明日方舟：终末地"后，"末地"会二次命中 -> "终终末地"）
    # —— 武陵 Wuling ——
    "武良": "武陵", "武心": "武陵", "武料": "武陵", "武林": "武陵",
    # —— 巨兽心脏 Feranmut Heart（ASR 居住の心臓 = 巨獣の心臓）——
    "居住中心": "巨兽心脏", "住宅的中心": "巨兽心脏", "居住的心脏": "巨兽心脏",
    "住心": "巨兽心脏", "常住的心": "巨兽心脏",
    "居住之力": "巨兽之力", "居住的力量": "巨兽之力", "居住的力": "巨兽之力",
    "住力": "巨兽之力",
    # —— 星门 Cosmic Gate（正門=星門）/ 超域 / 耶尔什 / 帕夏 / 第纳尔 ——
    "大门的另一边": "星门的另一边",
    "正门": "星门",
    "上界": "超域",
    "埃尔切": "耶尔什",
    "帕迪莎": "帕夏", "帕迪逊": "帕夏", "Padishah": "帕夏",
    "迪纳尔": "第纳尔",
    # —— 管理员 Endministrator（机翻 经理/店长/管理层/管理人）——
    "管理层": "管理员", "管理人": "管理员",
    "经理": "管理员", "经理人": "管理员",
    # —— 应龙 Yinglung（ASR 王龍=応龍，Arcane 所属特种部队）——
    "王龙": "应龙",
    "应龙特种部队": "应龙特勤队",       # 官方中文=应龙特勤队（YSTF）；行动队长=诀（Arcane，JP オクギ）
    # 注：诀(Arcane) 的机翻形最杂——ASR「オクギ」被听成「オウギ=奥義」，机翻出
    #     奥义/神秘/谜/秘技/奥吉 五种；逐 cue 侧车处理，不做全局键（"奥义"可能是普通词）。
    # —— 高频机翻误词（本片统计，均只落在中文行）——
    "凉爽的": "好帅",          # かっこいい（10 处全被译成"凉爽的"）
    "不挂断": "等等",          # 待って（10 处）
    "图片": "呃",              # え、（5 处）
    "严重地": "说真的",        # マジで
    "叹": "唉",                # はあ（单独出现的拟声）
}

# (日语参考行正则, 中文错形, 正确)：仅当日语行命中正则、且中文行含错形时才替换
JA_ENDFIELD_CONTEXT = [
    (r"正門|大門", "大门", "星门"),                  # 正門=星门（Cosmic Gate）；"陈"->陈千语 逐 cue 侧车处理，避免子串二次替换
]
_JA_ENDFIELD_CONTEXT_COMPILED = [(re.compile(rx), wrong, right) for rx, wrong, right in JA_ENDFIELD_CONTEXT]

# =============================================================
# 2. 韩语原声片源资产（原 calib_input_ko_out.py）
#    鸣潮官方韩文译名参见《鸣潮_故事相关专有名词中英日韩对照.md》韩语列
#    （如 残象=잔상、今州=금주、瑝珑=황룡），校准韩语片源新对照时先查该表。
# =============================================================

KO_INFO = {
    "src": r"g:\SOLO工作\input_ko_out.srt",
    "dst": r"g:\SOLO工作\input_ko_out_calib\input_ko_out_已校准.srt",
}

# 2.2 二次元手游 OST 理想型世界杯（韩语原声·综合手游节目）片源资产
# 2026-09-01 沉淀：跨段统一 妮姬/胜利女神->NIKKE、禅心在世->绝区零、蓝档案->蔚蓝档案，
#   以及主播常规口癖/机翻误词。该片源覆盖 崩坏/原神/明日方舟/绝区零/NIKKE/蔚蓝档案/
#   女神异闻录/Limbus/反转移期/国王突袭/歧路旅人 等综合游戏，勿与 KO_TERMS(鸣潮)混用。
# 用法：python subtitle_calib_merged.py <input.srt> --wwoc --out out.srt --report diff.md
WWOC_INFO = {
    "src": r"g:\SOLO工作\ost_worldcup_calib\input.srt",
    "dst": r"g:\SOLO工作\ost_worldcup_calib\calibrated.srt",
}

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

# 2.1 韩语片源术语统一（错误形式 -> 正确形式）
# 2026-08-29 依 wiki 名词注释-背景修正：官方写法为 归魂互助会（旧表误作 鬼魂互助会）
# 2026-09-03 新增：[명조]4장3막 음림/장리 _ko_auto 校准。依 库街区/鸣潮WIKI/官方配音表 核实官方名：
#   言使/归魂互助会/今州/乘霄山/虹镇/礼荣/媛媛/吟霖/长离/玄渺真人/梧黎/伏翎/吴盛/明庭/残星会。
# 2026-09-03 二次校准新增（依 离火弈长生 剧本 wuthering.wiki/quest_121000035 核实）：
#   辛夷(신이)/令尹(영윤대인)/鸣式(명식)/稷廷(직정)/夜归军(야귀군)/先行公约(선행공약)/
#   参事大人(참사대인=长离)/岁主(소호신)。并修正第一轮 #3106 侧车重复键导致的 胜利奖 漏改。
#   注意：旧表 长丽->张黎、胜苏山/圣沼山->升沼山 依官方名修正为 长离、乘霄山。
KO_TERMS = {
    '归云互助会': '归魂互助会',
    '恩思大人': '言使大人',
    '恩思': '言使',
    '言士': '言使',
    '元世': '言使',
    '翁士': '言使',
    '元使': '言使',
    # —— 归魂互助会(귀혼 상조회) 变体 ——
    '鬼魂互助会': '归魂互助会',
    '幽灵互助会': '归魂互助会',
    '鬼互助会': '归魂互助会',
    '鬼祖会': '归魂互助会',
    '桂园互助': '归魂互助会',
    '桂恩上祖': '归魂互助会',
    'Gwion Sangjo': '归魂互助会',
    'Gwion': '归魂互助会',
    # —— 言使(언사/원사) 变体 ——
    'Eonsa': '言使',
    'unsara': '言使',
    'Unsa': '言使',
    'Unsaga': '言使',
    'Unsaday': '言使大人',
    'Unsa Daein': '言使大人',
    'Unsadein': '言使大人',
    'Eonsadaein': '言使大人',
    '恩萨达因': '言使大人',
    '永萨台院': '言使大人',
    # —— 礼荣(예영) 变体（官方：礼荣）——
    '艺英': '礼荣',
    '叶英': '礼荣',
    '艺荣': '礼荣',
    '艺亨': '礼荣',
    '艺兴': '礼荣',
    'Yeyoung': '礼荣',
    # —— 媛媛(원원) 变体（官方：媛媛）——
    '元元': '媛媛',
    'Wonwon': '媛媛',
    '元冶': '媛媛',
    # —— 吟霖(음림) 变体 ——
    'Eumrim': '吟霖',
    'Eumlim': '吟霖',
    'eumlim': '吟霖',
    'eumrim': '吟霖',
    'Eum': '吟霖',
    '尤姆林': '吟霖',
    '乌姆林': '吟霖',
    # —— 长离(장리/장미) 变体（官方：长离；旧表 长丽->张黎 修正）——
    '长丽': '长离',
    '张丽': '长离',
    '张黎': '长离',
    '张离': '长离',
    '姜里': '长离',
    '江里': '长离',
    '江利': '长离',
    '江日': '长离',
    '江尼朗': '长离',
    '江丽': '长离',
    '江嘎': '长离',
    '张丽仁': '长离大人',
    'Jangri': '长离',
    'Jangli': '长离',
    'Jangridaein': '长离大人',
    '金美大仁': '长离大人',
    '张美大仁': '长离大人',
    '金美大学': '长离大人',
    '江美大学': '长离大人',
    '江日大学': '长离大人',
    '蔷薇大仁': '长离大人',
    # —— 乘霄山(승소산) 变体（官方：乘霄山；旧表 胜苏/圣沼山->升沼山 修正）——
    '胜苏山': '乘霄山',
    '圣沼山': '乘霄山',
    '升沼山': '乘霄山',
    '承素山': '乘霄山',
    '胜水山': '乘霄山',
    '升水山': '乘霄山',
    '承水': '乘霄山',
    '升西': '乘霄山',
    '胜利之山': '乘霄山',
    '承素桑': '乘霄山',
    '升素桑': '乘霄山',
    '胜小山': '乘霄山',
    '升小山': '乘霄山',
    # —— 残星会(잔성회) 变体 ——
    '詹星会': '残星会',
    '詹成会': '残星会',
    '建城会': '残星会',
    '建成会': '残星会',
    '詹森': '残星会',
    '詹城会': '残星会',
    '詹城': '残星会',
    '詹成爱': '残星会',
    'Janseong': '残星会',
    # —— 虹镇(홍진) 变体（官方：虹镇）——
    '红金村': '虹镇',
    '红锦村': '虹镇',
    '洪锦村': '虹镇',
    '洪金村': '虹镇',
    # —— 玄渺真人(현묘진인) 变体 ——
    '贤妙真仁': '玄渺真人',
    '贤明真人': '玄渺真人',
    '贤明真太': '玄渺真人',
    # —— 梧黎(우혁) 变体（官方：梧黎）——
    '宇赫': '梧黎',
    '佑赫': '梧黎',
    '吴赫': '梧黎',
    # —— 伏翎(복령) 变体（官方：伏翎）——
    '福翎': '伏翎',
    '福岭': '伏翎',
    '富京': '伏翎',
    '福京': '伏翎',
    '福明': '伏翎',
    # —— 鸣潮(명조) 变体 ——
    '明祖': '鸣潮',
    '明州': '鸣潮',
    '明乔': '鸣潮',
    '明朝': '鸣潮',
    'Mungjo': '鸣潮',
    # —— 明庭(명정) 变体 ——
    '明亭': '明庭',
    '明正': '明庭',
    # —— 辛夷(신이) 变体（官方：辛夷，与长离相识互信；离火弈长生剧本核实）——
    'Shin先生': '辛夷',
    '信信': '辛夷',
    '向进': '辛夷',
    '申大仁': '辛夷大人',
    # —— 令尹(영윤대인) 变体（官方：令尹，今州执政；영영 为 ASR 变体）——
    '英允大仁': '令尹大人',
    'Youngyun Daein': '令尹大人',
    # —— 鸣式(명식)（官方：鸣式，与岁主相对；见 库街区 鸣式考据）——
    '明植': '鸣式',
    # —— 稷廷(직정)（官方：稷廷，旧时代机巧科研组织）——
    '直井': '稷廷',
    '紫井': '稷廷',
    # —— 夜归军(야귀군)（官方：夜归军）——
    '夜鬼兵': '夜归军士',
    # —— 先行公约(선행공약)（官方：先行公约，探险家组织）——
    '发誓做好事': '先行公约',
    '预先承诺': '先行公约',
    '承诺做好事': '先行公约',
    # —— 参事大人(참사대인)（官方：参事大人=长离）——
    'Chamsa': '参事大人',
    # —— 岁主(소호신/수호신)（官方：岁主；梧黎日记提及）——
    'Soho God': '岁主',
    # —— 归魂互助会(귀혼 상조회) 变体补充 ——
    '鬼魂互助': '归魂互助会',
    '幽灵居民会议': '归魂互助会',
    '幽灵报价': '归魂的引用',
    # —— 长离(장리) 变体补充 ——
    '张里': '长离',
    # —— 乘霄山(승소산) 变体补充 ——
    '胜利奖': '乘霄山',
}

# =============================================================
# 3. 终末地（Arknights: Endfield）片源资产（原 calibrate_srt.py）
# =============================================================

ENDO_INFO = {
    "src": r"c:\Users\LENOVO\.trae-cn\attachments\6a8e517006175886fb7bf086\1c9fb9b8-cba8-4629-9055-d1cad976d527_efc96848-b18d-4832-8392-806dd67fe7ad_videoplayback (3).srt",
    "dst": r"g:\SOLO工作\videoplayback(3)_已校准.srt",
}

# 3.2 战双帕弥什（PGR）音乐会片源 —— 侧车整行覆盖模式
# 用法：python subtitle_calib_merged.py --pgr （不带文件）一键重跑；
#       或 python subtitle_calib_merged.py <PGR输入.srt> --pgr --out 输出.srt --report diff.md
PGR_INFO = {
    "src": r"g:\SOLO工作\pgr_rhythm_rough\input.srt",
    "dst": r"g:\SOLO工作\pgr_rhythm_rough\PGR_OneHeartOneHertz_calibrated.srt",
}
PGR_OVERRIDES_SRC = r"g:\SOLO工作\pgr_rhythm_rough\pgr_overrides.tsv"   # 序号<TAB>校准后中文

# 3.1 终末地片源术语统一（错误形式 -> 正确形式）
# 2026-08-29 依《终末地_故事专有名词_中英日韩对照表.md》修正：
#   普切娜系 -> 噗切娜（官方名 Puchena）；五菱/武林 -> 武陵（Wuling）；
#   并补回韩语片源 恩德菲尔德 等 -> 终末地（原 calibrate_srt2.py，엔드필드 音译）。
ENDFIELD_TERMS = {
    "阿莱克荔厄斯": "阿莱克琉斯",
    "阿莱克修斯": "阿莱克琉斯",
    "阿莱克留斯": "阿莱克琉斯",
    "提夫罗斯": "提弗洛斯",
    "提夫洛斯": "提弗洛斯",
    "提莫罗斯": "提弗洛斯",
    "提芙罗斯": "提弗洛斯",
    "提普洛斯": "提弗洛斯",
    "皮夫洛斯": "提弗洛斯",
    "皮弗洛斯": "提弗洛斯",
    "疾风洛斯": "提弗洛斯",
    "其弗洛斯": "提弗洛斯",
    "吉弗洛斯": "提弗洛斯",
    "吉克洛斯": "提弗洛斯",
    "提罗斯": "提弗洛斯",
    "弗鲁斯": "提弗洛斯",
    "普切纳": "噗切娜",
    "普奇娜": "噗切娜",
    "普希娜": "噗切娜",
    "迫切娜": "噗切娜",
    "库奇娜": "噗切娜",
    "付辛娜": "噗切娜",
    "普吉娜": "噗切娜",
    "普辛娜": "噗切娜",
    "普切娜": "噗切娜",
    "中落地": "终末地",
    "恩德菲尔德": "终末地",
    "恩菲尔德": "终末地",
    "艾姆菲尔德": "终末地",
    "汉德菲尔德": "终末地",
    "遂名城": "遂明城",
    # --- 2026-08-30 Vtuber 观看终末地预告节目 校准新增（中文文本内才出现的机翻残留）---
    "石田明": "石田彰",                                           # 声优 石田彰 音误
    # 注：更多逐句/专名对照见 g:\SOLO工作\vtuber_endo_preview_calib\对照_错误vs正确.tsv
    #      与 GLOSSARY.md（管理人=管理员/干员/侦察/卡池、萨卡兹/萨科塔/罗德岛 等约定）
    "五菱": "武陵",
    "武林": "武陵",
    "索幸": "所幸",
    # 终末地评论/反应片源常见 ASR 错词 -> 公认游戏名（2026-08-30 评论片沉淀）
    "安菲尔德": "终末地",              # Anfield
    # --- 2026-09-05 Gloomwald's Rage Boss Theme Reaction 片源沉淀 ---
    "格洛姆瓦尔德": "幽林之怒",                                    # Gloomwald's Rage 官方中文 幽林之怒
    "格洛姆沃德": "幽林之怒",
    "原心": "原神",                                                # Genshin 误听（"原心不哭"=Genshin's Nod-Krai）
    "风化波浪": "鸣潮",                # Weathering/Witting Waves -> Wuthering Waves
    "风化浪潮": "鸣潮",
    "浇水方式": "鸣潮",                # Watering Ways
    "根钦": "原神",                    # Genchin Impact
    "史诗 7": "第七史诗",              # Epic Seven
    "阪堺星轨": "崩坏：星穹铁道",        # Hankai Star Rail
    "启星轨道": "崩坏：星穹铁道",        # Kai Star Rail
    # --- 2026-09-07 엔드필드 1.5버전 티프로스 스토리（韩语机翻片源）校准沉淀 ---
    # 관리자 被通用机翻成"经理"（终末地官方主角称谓=管理员；本韩语片源 26 处全部对应 관리자）
    "经理人": "管理员", "经理": "管理员",
    # 안마(Anma，1.5 雪原角色"安玛")被按韩语本意"按摩"机翻（本韩语片源 22 处全部对应 안마）
    "按摩师": "安玛",
    "按摩": "安玛",
    # 티프로스/티프루스(提弗洛斯) 的机翻/ASR 变体（德语"斑疹伤寒"Typhus 误形等）
    "斑疹伤寒": "提弗洛斯",
    "T-Prus": "提弗洛斯", "Typhros": "提弗洛斯", "Typrus": "提弗洛斯",
    "泰弗鲁斯": "提弗洛斯",   # 长键先行：裸"弗鲁斯"会把"泰弗鲁斯"拆成"泰提弗洛斯"
    # 아마/암마 = 안마(安玛) 的 ASR 省写（#363/#983/#1445 韩文行佐证）
    "阿玛": "安玛",
    # 벨보스 / 베에모스·베모스 / 아겔로스·악계로스 同一韩文词跨段音译不统一，片内归一
    "贝尔沃斯": "贝尔博斯", "比莫斯": "贝莫斯",
    "阿格罗蒂亚": "阿格罗斯", "阿吉罗斯": "阿格罗斯",
    # 4번 협곡/짐승군주 -> 官方名（ENDFIELD_NOUNS：四号谷地、兽主）
    "4号峡谷": "四号谷地", "兽王": "兽主",
    "泰弗罗斯": "提弗洛斯", "迪普罗斯": "提弗洛斯", "杰弗罗斯": "提弗洛斯",
    "感谢泰弗罗斯": "感谢提弗洛斯",
    # 엔드필드 其余机翻形
    "终点场": "终末地",
    # 안드레/안드리(安德烈) 音译不统一变体（裸"安德"会命中"安德烈"造成级联，留给分段人工）
    "安德里": "安德烈", "安德鲁": "安德烈", "Nandre": "安德烈",
    # 명예방주(명일방주=明日方舟 的 ASR 误形)机翻"荣誉方舟"
    "荣誉方舟": "明日方舟",
    # 로그라이크 统一
    "类 Rogue": "Roguelike",
    # 탈로스(Talos，官方名词表作 塔罗斯) / 탈로소 2(Talos II，官方星球名 塔卫二)
    "塔洛索 2": "塔卫二", "塔洛索2": "塔卫二", "塔洛斯": "塔罗斯",
    # --- 2026-09-08 엔드필드 1.5버전 티프로스 스토리（韩语机翻片源）二次人工校准沉淀 ---
    # 对照全量见 i:\Agent Work\字幕校准\对照_엔드필드1.5.tsv（1593 处 错误vs正确）；
    # 完整报告 diff_report_엔드필드1.5_完整.md。以下为系统性/可复用对照：
    # 관리자 机翻除"经理"外还有"店长"；제사장 机翻"牧师/神父"；재단 机翻"基金会"（剧中=祭坛/基座）
    "店长": "管理员",
    "牧师": "祭司", "神父": "祭司",
    "基金会": "祭坛",
    # 벨보스(bellhop 行李员=贝尔博斯) / 안들레(안드레 ASR=安德烈) / 벨버스(벨보스 ASR)
    "行李员": "贝尔博斯", "安黛尔": "安德烈", "贝尔布斯": "贝尔博斯",
    # 티폰=Typhon(提丰)，机翻 T-Phone/T-phone；수르트=Surtr(明日方舟干员史尔特尔)，机翻 苏特尔/购物车(수레)
    "T-Phone": "提丰", "T-phone": "提丰",
    "苏特尔": "史尔特尔", "Surut": "史尔特尔",
    # 원석충(源石虫) 机翻 宝石虫/元石忠
    "宝石虫": "源石虫", "元石忠": "源石虫",
    # 명조(鸣潮) 在终末地评论片中出现，机翻 明乔/明祖
    "明乔": "鸣潮", "明祖": "鸣潮",
    # 디프로스/디프리스/티프러스/제프로스 均为 티프로스(提弗洛斯) ASR 变体
    "Depros": "提弗洛斯", "Depros 是": "提弗洛斯是",
    # 브금/부금=BGM（机翻"分期付款/星期五/bgeum"），本片语境均为背景音乐
    "bgeum": "BGM", "分期付款": "BGM",
    # --- 2026-09-08 二次校准：检索官方中文确认（官网 endfield.hypergryph.com + NGA/网易/17173 攻略）---
    # 티프로스=提弗洛斯(Typhoeus，罗德岛萨卡兹荒野猎手)、안마=安玛（萨米鹿兽主/白鹿"老妈妈"）、
    # 응룡 관문=应龙关、소나무 숲=雪松林、깊은 숲의 분노=幽林之怒(区域Boss)、무릉성=武陵城、
    # 살카족=萨卡兹、크레송=克雷松(邪魔，安玛撞星门封印)、뿌리 없는 꽃=无根花、遂明城、티폰=提丰(本体)
    "应用网关": "应龙关",                                   # 응용 관문(응룡 관문 的 ASR/机翻形)
    "克莱松": "克雷松",                                     # 크레송
    "无根之花": "无根花",                                   # 뿌리 없는 꽃
    # --- 2026-09-10 沉淀自《What Do You Get When You Mix Arknights Endfield, with the Swedish?》（谷歌翻译中英双语反应片，270 cues）---
    # 校准流水线：--endo(16处) -> merge 侧车(22条，含2条原样保护) -> verify 31 处净变化全通过。
    # 完整错误->正确对照（详见工作区 对照_Swedish.tsv / diff_report_Swedish.md）。
    # 2026-09-10 二次校准（官方中文检索，官网 endfield.hypergryph.com + TapTap《雪凇幽梦》更新说明 + NGA/网易）：
    #   武陵(Wuwang，雪凇幽梦新增区域"武陵-雪松林"/"武陵-遂明" 官方)、安玛(Amaro/Amma，萨米鹿兽主/白鹿"老妈妈" 官方)、
    #   提弗洛斯(Typhoeus，罗德岛萨卡兹荒野猎手)、佩丽卡(Paralica，终末地工业监督)、
    #   萨米维格(Samiverg，官方故事标题《提弗洛斯：萨米维格的孩子》；萨米语"萨米之路")、
    #   安德烈(1.5 总工程师，迷失于应龙关外树林)、应龙关/雪松林/遂明/幽林之怒(区域Boss)/克雷松/无根花 均官方中文。
    # 原文对照：
    #   内场(Infield ASR)->终末地；鹰眼高夫->鹰眼戈夫；恩菲尔德->终末地；接线员/运营商->干员(官方)；
    #   伤寒(Typhoeus/Typhus 混淆)->提弗洛斯；台风(EP名语境)->提弗洛斯；道达尔(Total War)->全面战争；
    #   i 框架->无敌帧；帕拉利卡->佩丽卡(官方，头衔"监督"非"主管")；武王(Wuwang ASR)->武陵(官方中文)；
    #   英文残留侧车：Typhoeus->提弗洛斯、Chifoya->提弗洛斯(ASR变体，英文键严禁进表防污染英文行)；
    #   ERROR 空行补译4条(#147/149/153/184/198)；"Fragmented Dreams"(EP名)无官方中文保留英文；
    #   Amma->安玛(错误形态"妈妈/但是/但"逐cue侧车)；Amaro 剧情语境->安玛(#155)。
    #   Samiverg 中文行音译变体(萨米尔维格/萨米沃格)统一 -> 萨米维格(#74)；英文行 Samiverg/Samiwerg 不动。
    # 【教训】--endo 全文本行模式的通用词误伤：本片"牧师"是 D&D 语境(#165)不能变"祭司"、
    #   "阿玛罗"含子串"阿玛"会被拆成"安玛罗"(#189)——做法：侧车写回原样行阻断，
    #   通用键(牧师/神父/妈妈等)永不进 ENDFIELD_TERMS。
    # Infield=Endfield ASR 误听机翻形；Typhoeus/Typhus 混淆（"伤寒"）；EP 语境"台风"同为 Typhoeus 误译
    "内场": "终末地",
    "伤寒": "提弗洛斯", "台风": "提弗洛斯",
    # Total War: Warhammer 机翻"道达尔"（石油公司名）
    "道达尔": "全面战争",
    # Hawkeye Gough（黑暗之魂鹰眼戈夫）通行译名
    "鹰眼高夫": "鹰眼戈夫",
    # i-frame 机翻直译
    "i 框架": "无敌帧",
    # operator 官方译名=干员（机翻 接线员/运营商）
    "接线员": "干员", "运营商": "干员",
    # Paralica=佩丽卡（终末地工业监督，官方）；中文行音译变体统一
    "帕拉利卡": "佩丽卡",
    # Wuwang ASR 误听 -> 武陵（雪凇幽梦新增区域 官方中文）
    "武王": "武陵",
    # Samiverg=萨米维格（提弗洛斯之子，官方故事名）；萨米尔维格/萨米沃格 中文行音译变体统一
    "萨米尔维格": "萨米维格", "萨米沃格": "萨米维格",
}

# =============================================================
# 3.1b 明日方舟（本尊）系统片源资产（2026-08-31 沉淀自《The Grand Arknights
#     New Player QA》2465 cue 校准；非终末地，独立 AK_TERMS）
#    ENFIELD_TERMS 是"终末地"游戏术语；本片是"明日方舟"本体 Q&A，
#    术语（生息演算/危机合约/集成战略/保全派驻/要塞协议 等）不得与 ENDFIELD_TERMS 混用。
# =============================================================
AK_INFO = {
    "src": r"g:\SOLO工作\ak_newplayer_qa_calib\input.srt",
    "dst": r"g:\SOLO工作\ak_newplayer_qa_calib\calibrated_merged.srt",
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
}
# AK_MODE 并入 process：与 endo 类似，但仅精调 ARKNIGHTS 中文行（首中文行）

# =============================================================
# 3.1b1 明日方舟 PV 世界杯（韩语原声，명일방주 PV 월드컵 112강，_ko_auto 谷歌翻译）专用资产
# 2026-09-10 沉淀：第一轮人工对照 117 处（对照_PV世界杯_第一轮.tsv）+ 第二轮新增。
# 参考行为韩语 ASR（如 이네스=Ines、머드락=Mudrock），中文行为谷歌机翻。
# 模式 --akko：AK_KO_TERMS（无歧义全局替换）+ AK_KO_CONTEXT（韩语参考行佐证）。
# 戒律：歧义词（医生/沉默/火焰/铅/熔岩/幻影/沙拉/霜 等）必须韩语佐证，防误伤普通词义；
#   韩语片绝不加载 KO_TERMS（鸣潮）或 WWOC_TERMS（综合手游）表。
# 用法：python subtitle_calib_merged.py <input.srt> --akko --out out.srt --report diff.md
# =============================================================
AK_KO_INFO = {
    "src": r"D:\字幕\【字幕】게임 PV 만든거 맞죠  명일방주 PV 월드컵 112강_ko_auto-谷歌翻译.srt",
    "dst": r"D:\字幕\【字幕】게임 PV 만든거 맞죠  명일방주 PV 월드컵 112강_ko_auto-谷歌翻译_校准.srt",
}
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
_AK_KO_CONTEXT_COMPILED = [(re.compile(rx), wrong, right) for rx, wrong, right in AK_KO_CONTEXT]

# =============================================================
# 3.1b2 ERROR 占位行批量回填（2026-09-10，명일방주 PV 월드컵 112강 _ko_auto 谷歌翻译）
#   源文件 5031 处 "ERROR" 占位（一些 cue 拆成多行共覆盖 5606 序号），经韩语 ASR
#   重译后以 ERROR行_中文映射.json 回填到首文本列，保留第二行韩语原文。
#   步骤一：ak_ko_err_extract.py 提取 ERROR 序号/时间轴/韩语行 -> ERROR行_提取.tsv
#   步骤二：分批翻译写入 side_001.tsv ~ side_029.tsv（Tab分隔）-> ERROR行_中文映射.json
#   步骤三：merge_final.py 按序号回填，字节级校验：cue 数、序号、时间轴与备份全等，
#     保持 CRLF 换行、无 BOM。对照清册见 对照_PV世界杯_ERROR行.tsv。
#   可确认的官方专名（频率高者）：干员/博士/凯尔希/特蕾西娅/罗德岛/拉芙希妮/
#     临光/瑕光/夜刀/谢拉格/叙拉古/乌萨斯(俄罗斯/苏联主题PV)/萨卡兹/维什戴尔/
#     泥岩/炎熔/赫默/煌/灰烬/傀影/幽灵鲨/霜华/驮兽/龙门/迷迭香。
#   不确定/保留项：语料多为主播 ASR 口语闲聊，机翻专名（如距 雷瓦 相关、스노우샤인
#     Snowshine 等）无官方中文时而保留原文，切勿强行音译进全局表以防误伤。
# =============================================================

# =============================================================
# 3.1c1 流水线 merge --fix 的跨段统一表（2026-08-31 沉淀自 ak_newplayer_qa_calib
#     merge_rebuild.py FIXES；该 6 条既不在 AK_TERMS（未命中=无色差输入），又需在
#     回填后整句统一，故选做 merge 阶段的可选规范化，原 AK 侧车已含人工产物故不双叠）
# =============================================================
MERGE_FIXES = [
    ("巫师", "维什戴尔"),        # Wizard/Wizardell = Wisadel
    ("巫泽尔", "维什戴尔"),      # Wizardell
    ("夏·新约", "新约能天使"),   # Xia the new covenant
    ("特蕾迪亚", "酒神"),        # Tradia = Tragodia
    ("可露希尔", "克洛丝"),      # closure = Kroos（抽卡语境）
    ("阿雷迪亚", "arkpedia"),    # Aredia = arkpedia（网站）
]

# =============================================================
# 3.1c 中文行专属英文噪音替换（2026-08-31 并入 apply_zh_only.py，复用模式 --zho）
#    仅改每个 cue 的首中文行，绝不动英文/参考行；因为 key 原串同时存在于英文行，
#    若写进 ENDFIELD_TERMS/ENDFIELD 全文本遍历会污染英文行，故须独立中文行专属模式。
#    2026-08-31 从终末地评论片（endo_wwstate/endo_state_comments 两处同逻辑）沉淀：
#      Genchin Impact->原神、Nfield(s)->终末地
# =============================================================
ZH_ONLY_TERMS = {
    # 中文行残留的英文游戏名噪音 -> 官方中文（原串同时出现在英文权威行，勿入其它术语表）
    "Genchin Impact": "原神",
    "Nfields": "终末地",
    "Nfield": "终末地",
    # 2026-09-10 ko PV 世界杯（명일방주 PV 월드컵 112강）二次校准：中文首行残留的
    # 明日方舟官方名词英文/音译 -> 官方中文（子代理按 PRTS 等权威源核实）：
    "恩菲尔德": "终末地",                  # Endfield 明日方舟：终末地
    "Mureung": "武陵",                    # 终末地炎国区域（무릉）
    "Mudrock": "泥岩",                    # 重装干员（雇佣兵希瓦）
    "Melantha": "玫兰莎",                  # 近卫干员 N009
    "Majella": "麦哲伦",                  # 辅助/医疗干员（黎博利）
    "Melansarae": "麦哲伦",
    "Magellan": "麦哲伦",
    "Crown Slayer": "弑君者",            # 近卫干员 柳德米拉
    "Guiding Ahead": "吾导先路",          # SideStory（凯尔希，勿译长夜临光）
    "Under Tides": "覆潮之下",            # SideStory（伊比利亚/深海）
    "Undertides": "覆潮之下",
    "Undertide": "覆潮之下",
    "Walk in the Dust": "遗尘漫步",        # SideStory（凯尔希/异客，哥伦比亚）
}
# 用法：python subtitle_calib_merged.py --zho <input.srt> --out out.srt
#   --zho 与 --endo/--ak/--ko 互斥；同属"仅改首中文行"，但只套用 ZH_ONLY_TERMS 这一张表。
ZHO_INFO = {
    "src": r"g:\SOLO工作\endo_wwstate_calib\input.srt",
    "dst": r"g:\SOLO工作\endo_wwstate_calib\calibrated.srt",
}

# =============================================================
# 3.1d 音乐/演唱点评通用术语（模式 --react，2026-09-09 新增）
#    源自《Opera Singer Critiques Libera Me From Hell》二次校准（官方中文已检索）：
#      Mori Calliope->森美声（hololive EN 官译）；
#      Elizabeth Rose Bloodflame->伊丽莎白·露丝·布拉德弗雷姆（萌百/官方罗马音）；
#      Gurren Lagann->天元突破红莲螺岩；"Libera Me From Hell" 为拉丁语歌名保留英文。
#    并沉淀声乐/演唱类常用机翻错词（软腭/颤音/换气/高音区/转调/滑音/咏叹调/直声…）。
#    与游戏术语表互斥；仅当显式传 --react 时才套用，避免污染其它片源。
#    注释标注“歧义键”者只在本批演唱语境下正确，慎于它类字幕复用以免误改本义。
# 用法：python subtitle_calib_merged.py <input.srt> --react --out out.srt --report diff.md
# =============================================================
REACT_TERMS = {
    # ---- 人名 / 歌名 / 片名（官方中文）----
    "莫里·卡利俄珀 (Mori Calliope)": "森美声 (Mori Calliope)",
    "莫里·卡利俄珀": "森美声",
    "莫里·卡利彭": "森美声",
    "卡利彭": "森美声",
    "莫里": "森美声",            # 仅指 Mori Calliope 的口语称呼“Mori”
    "伊丽莎白·罗斯·血焰": "伊丽莎白·露丝·布拉德弗雷姆",
    "伊丽莎白·罗丝·血焰": "伊丽莎白·露丝·布拉德弗雷姆",
    "罗斯·血焰": "露丝·布拉德弗雷姆",
    "罗丝·血焰": "露丝·布拉德弗雷姆",
    "血德的": "露丝·布拉德弗雷姆的",
    "格伦·洛根": "天元突破红莲螺岩",
    "古兰贷款": "天元突破红莲螺岩",
    "古林·洛根": "天元突破红莲螺岩",
    "Grun Logan": "天元突破红莲螺岩",
    "Guran Logan": "天元突破红莲螺岩",
    "Gurin Logan": "天元突破红莲螺岩",
    "Liidame": "Libera Me From Hell",
    "利比达姆": "Libera Me From Hell",
    # ---- 声乐 / 演唱通用机翻错词 ----
    "测量 VB": "克制的颤音",
    "VBR": "颤音（Vibrato）",   # vibrato 之 ASR 缩写
    "verd": "颤音",
    "软托盘": "软腭",            # soft palate；歧义键（“托盘”实为“腭”之误）
    "上层寄存器": "高音区",
    "直语": "直声",              # straight tone
    "更改密钥": "转调",          # change key
    "一部分是球场": "一部分在于音高",   # pitch
    "还有很多幻灯片": "还有很多滑音",     # slides ≈ glissando
    "歌剧艾莉亚": "歌剧咏叹调",  # aria
    "杂乱的歌声": "歌剧式演唱",  # operatic
    "干净的oporatic": "干净的歌剧演唱",
    "远离标准的 oporadic": "远离标准的歌剧式唱法",
    "过度发音和宣告": "过度咬字和清晰的吐字",   # overarticulation & enunciation
    "我喜欢咬一口": "我喜欢那种咬字的力度",       # bite of the text；歧义键
    "重新列出它": "再重听一遍",  # relist ≈ relisten
    "10,00%": "100%",
    "凉爽的": "很酷",            # cool；歧义键（温度义的“凉爽”会被误改）
    "谈论两个非常非常的谎言": "聊聊两位非常非常有才华的人（的演绎）",
    "对抗权力。触摸不可触摸的东西": "对抗强权。触摸那不可触碰之物",
    "排，排，对抗力量，就像这样": "划呀，划呀，对抗那力量，就像这样",
    "权力给窥视者。电源为": "力量属于大家。力量为",
}
# 用法：python subtitle_calib_merged.py --react <input.srt> --out out.srt
#   --react 与游戏模式互斥；仅套用 REACT_TERMS 统一首中文行（不动英文/参考行）。

# =============================================================
# 4. 中文双行排版（原 layout_merge2.py 的 layout 函数）
#    规则：≥14 字长句拆两行，优先在标点/闭括号后断行，不切开括号；
#    2026-08-29 起接入第 6 节 WW_OFFICIAL_NOUNS，断点不落在官方专名内部。
#    2026-09-10 新增【行宽上限】：每行字幕不宜超过 32 个汉字或 64 个英文字符。
#    统一折算为显示宽度 MAX_LINE_WIDTH = 32（汉字/全角/假名/韩文计 1，半角计 0.5），
#    故「汉字 ≤ 32」与「英文字符 ≤ 64」是同一条判据（32×1 = 64×0.5）。
#    拆两行后任一半仍超宽的，按同一断行规则继续递归拆分至达标；
#    单词内部、括号内部、官方专名内部一律不切；实在拆不动则原样保留（宁可超宽，不破语义）。
#    体检：verify 会对成品逐行报告超宽行；length 子命令可只读体检任意 SRT。
# =============================================================
PUNCT = set('，。！？；：、…')
CLOSING = set('”』」】）)】]〕＞>')
OPEN = set('“『「【（([〈《<·—–-‐')
SPACE = ' 　'

# 行宽上限（2026-09-10）：32 汉字 或 64 英文字符
MAX_LINE_ZH = 32                        # 汉字上限
MAX_LINE_EN = 64                        # 英文字符上限（= 2 × 32，等宽）
MAX_LINE_WIDTH = float(MAX_LINE_ZH)     # 统一显示宽度上限；半角字符按 0.5 计
LINE_FULL = ("W", "F", "A")             # 东亚全角/宽/歧义：按 1.0 宽计


def _is_alpha(ch):
    return ch.isalnum() or ch in '%.'


def char_width(ch):
    """单字符显示宽度：汉字/全角标点/假名/韩文 = 1.0，ASCII 等半角 = 0.5。"""
    return 1.0 if unicodedata.east_asian_width(ch) in LINE_FULL else 0.5


def line_width(s):
    """整行显示宽度（汉字 = 1，英文字符 = 0.5）；> MAX_LINE_WIDTH 即违规。

    等价判据：汉字 ≤ 32 或英文字符 ≤ 64（纯汉字 32 字 = 32.0，纯英文 64 字符 = 32.0）。"""
    return sum(char_width(ch) for ch in s)


def is_line_too_long(s):
    """该行是否超过 32 汉字 / 64 英文字符上限（严格大于才算超标）。"""
    return line_width(s) > MAX_LINE_WIDTH


def _split_once(s, allow_cjk=False):
    """在 s 中找最佳断点，返回 (前半, 后半)；拆不动则返回 None。

    优先子句标点/闭括号之后，其次词边界中点附近；不切括号内部与官方专名内部。
    allow_cjk=True 追加"汉字之间可断"的强制换行档，仅超宽行（>32 汉字）用；
    默认 False 与既有行为逐字节一致（纯汉字无标点行不拆）。
    （原 layout_line 的单次断行逻辑，2026-09-10 抽出，供超宽行递归拆分复用。）"""
    n = len(s)
    if n < 8:
        return None
    mid = n / 2.0
    best = None
    bestscore = None
    spans = _noun_spans(s)             # 官方专名区间（第 6 节），断点不得落入其内部
    # (1) 优先在子句标点 / 闭括号之后断行
    for i, ch in enumerate(s):
        if i + 1 >= n:
            break
        if ch not in PUNCT and ch not in CLOSING:
            continue
        pos = i + 1
        if pos < 6 or (n - pos) < 4:
            continue
        if _inside_noun(spans, pos):   # 不切官方专名
            continue
        if s[min(i + 1, n - 1)] in CLOSING:      # 紧跟闭括号则后移
            continue
        if '[' in s and (s.count('[', 0, pos) > s.count(']', 0, pos)):
            continue
        bonus = 2 if ch in PUNCT else 0          # 真标点优先于闭括号
        sc = abs(pos - mid) - bonus
        if best is None or sc < bestscore:
            bestscore = sc
            best = pos
    if best is not None:
        return s[:best].rstrip(SPACE), s[best:].lstrip(SPACE)
    # (2) 兜底：在词边界中点附近断（避开开引号/括号、词内部与官方专名内部）
    for i in range(6, n - 4 + 1):
        a = s[i - 1]
        b = s[i]
        if a in OPEN or b in OPEN:
            continue
        if _inside_noun(spans, i):     # 不切官方专名
            continue
        if _is_alpha(a) and _is_alpha(b):
            continue
        if a.isalnum() and b.isalnum() and (a.isalpha() == b.isalpha()):
            continue
        sc = abs(i - mid)
        if best is None or sc < bestscore:
            bestscore = sc
            best = i
    if best is not None:
        return s[:best].rstrip(SPACE), s[best:].lstrip(SPACE)
    if not allow_cjk:
        return None
    # (3) 强制换行档（仅超宽行）：允许在汉字之间断，用于无标点的超长中文行。
    #     仍不切拉丁词/数字内部、不切方括号内部、不在闭括号前断。
    for i in range(6, n - 4 + 1):
        a = s[i - 1]
        b = s[i]
        if a in OPEN or b in OPEN or b in CLOSING:
            continue
        if _inside_noun(spans, i):                # 不切官方专名
            continue
        if a.isascii() and b.isascii():           # 不切拉丁单词/数字内部
            continue
        if '[' in s and (s.count('[', 0, i) > s.count(']', 0, i)):
            continue
        sc = abs(i - mid)
        if best is None or sc < bestscore:
            bestscore = sc
            best = i
    if best is not None:
        return s[:best].rstrip(SPACE), s[best:].lstrip(SPACE)
    return None


def _wrap_width(s, out, depth=0):
    """把超宽行 s 递归拆成若干 ≤ 上限的行，依次追加进 out（行宽上限硬约束）。"""
    if not is_line_too_long(s) or depth >= 8:
        out.append(s)
        return
    parts = _split_once(s, allow_cjk=True)
    if parts is None or not parts[0] or not parts[1]:   # 拆不动（超长单词/专名）则保留
        out.append(s)
        return
    _wrap_width(parts[0], out, depth + 1)
    _wrap_width(parts[1], out, depth + 1)


def layout_line(s):
    """中文行排版：≥14 字长句拆两行（不切括号/官方专名）；若某半行仍超过
    32 汉字 / 64 英文字符则继续递归拆分，保证每行不超上限。短句/标记行原样返回。"""
    if not s:
        return s
    if re.match(r'^\[[^\]]+\]$', s.strip()):
        return s
    if len(s) < 14:
        return s
    parts = _split_once(s)                    # 既有档：标点/词边界，行为不变
    if parts is None:
        if not is_line_too_long(s):           # 既有行为：拆不动且不超宽 -> 原样返回
            return s
        out = []                              # 新规则兜底：超宽则强制换行
        _wrap_width(s, out)
        return "\n".join(out)
    out = []
    _wrap_width(parts[0], out)
    _wrap_width(parts[1], out)
    return "\n".join(out)


# =============================================================
# 5. 英文参考行修正资产（2026-08-29 并入；原 ERROR 占位行翻译表已于同日删除）
#    来源：srt_calibrator.py、fix_srt.py、7月 WW 演唱会脚本通用专名。
#    默认不启用：--fix-en 才动英文/参考行。
# =============================================================

# 5.1 英文/参考行 ASR 错词修正（错误形式 -> 正确形式，子串替换，长词优先）
# 注意：纯子串替换，个别短 key（TD/toa/fract 等）可能误伤含该子串的单词，
# 仅在对照双语片源确认需要时开启 --fix-en。
EN_LINE_TERM_FIXES = {
    # 角色名（srt_calibrator.py；fix_srt.py 的 Jouer->Jinhsi 自承存疑，跳过）
    "Arctites": "Arknights", "Amiia": "Amiya",
    "Mortafe": "Mortefi", "Mortifi": "Mortefi",
    "Senoa": "Chixia", "Yap Yap": "Yangyang",
    "Chizzy": "Jiyan", "Gian": "Jiyan",
    "Yinllin": "Yinlin", "Yindllin": "Yinlin", "Yinland": "Yinlin",
    "Ginshi": "Jinhsi",
    # 地名
    "Jingo City": "Jinzhou City",                          # 长词优先于 Jingo
    "Jingo": "Jinzhou", "Jingjo": "Jinzhou", "Gingjo": "Jinzhou", "Jindo": "Jinzhou",
    "Hang Long": "Huanglong", "Wang Long": "Huanglong", "Guang Long": "Huanglong",
    # 阵营 / 敌人
    "Fraidus": "Fractsidus", "Fraid": "Fractsidus",        # 残星会官方英文名（依 md 中英对照）
    "fractur": "Fractsidus", "fract": "Fractsidus",        # 短子串，注意 fracture 类误伤；官方英文名 Fractsidus
    "Thrronodians": "Threnodians", "Thrronodian's": "Threnodian's",
    "Thrronodian'": "Threnodian'", "Thrronodian": "Threnodian",
    "Throdian": "Threnodian", "Trinodian": "Threnodian", "Frenodian": "Threnodian",
    "Renoians": "Lament",
    # 游戏术语
    "sauna disc": "sono disc",
    "symphidi": "symphony", "symphodi": "symphony", "symphi": "symphony",
    "tacid": "tacet",
    "Tessa discords": "Tacet discords", "Tessa": "Tacet",  # 长词优先
    "ExoRiders": "Exostrider", "Exoriders": "Exostrider",  # Exostrider 大小写变体（中文残留英文 / 英文参考行）
    "Alisium": "illusion", "Pificant": "insignificant", "Shov": "Sure",
    # 哨兵 / NPC（fix_srt.py 决定保留 Jer 不改，故无 Jer->Jue）
    "Jouer": "Jue", "Jueer": "Jue",
    # fix_srt.py 独有
    "Sono": "sono",                                        # 句中保持小写
    "MSQ": "main story quest",
    "TDs": "Tacet Discords", "TD": "Tacet Discord",        # 短子串，注意误伤
    "tacet discords": "Tacet Discords", "tacet discord": "Tacet Discord",
    "the crownless": "the Crownless", "crownless": "Crownless",
    "Miss Magistrate": "Madame Magistrate", "magistrate": "Magistrate",
    # 7月 WW 演唱会脚本通用专名（calibrate_ww.py / calibrate_ww_v2.py / auto_correct.py）
    "Shortke keeper": "Shorekeeper", "Shortke": "Shorekeeper",
    "Chamilleia": "Camellya", "Chameleia": "Camellya",
    "Chamilia": "Camellya", "Camillia": "Camellya",
    "base drops": "bass drops", "base drop": "bass drop",  # 仅 drop 语境，单词 base 不改
    "Tik Tok": "TikTok", "tik tok": "TikTok",
    "toa": "TOA", "Toa": "TOA",                            # 逆境深塔缩写，注意 toad 类误伤
    # --- 2026-09-09 明日方舟 OST 分析片（Ratio Ultima）ASR 错词 ---
    # 证据：arknights.wiki.gg/wiki/Episode_14/OST（Arknights / Yuka Kitamura）
    "Ark Knights": "Arknights",                            # ASR 误拆
    "Kamura": "Kitamura",                                  # 作曲家 Yuka Kitamura（片内 #258/#709/#736 作 Kitamura）
}

# =============================================================
# 6. 官方专有名词表 WW_OFFICIAL_NOUNS / ENDFIELD_NOUNS / ARKNIGHTS_NOUNS / PGR_NOUNS
#    鸣潮部分：2026-08-29 抓自 wiki.kurobbs.com 鸣潮 wiki（接口 catalogue/item/getPage）：
#    共鸣者(1105) 武器(1106) 声骸(1107) 敌人(1158) 合鸣效果(1219) BOSS(1290)
#    全息战略(1313) 名词注释-背景/技能/活动(1461/1462/1608) 任务剧情(1330-1332)
#    地图文本(1605) 地域风光(1620) + 区域探索地名
#    + 鸣潮_故事相关专有名词中英日韩对照.md（截至 3.6 版本，含日/韩官方译名列），去重共 1262 条。
#    终末地部分：《终末地_故事专有名词_中英日韩对照表.md》中文列，213 条。
#    明日方舟部分：《Arknights_Lore_Terminology_EN_CN_JP_KR.md》中文列，581 条。
#    战双部分：《战双帕弥什_专有名词中英日韩对照表.md》中文列，253 条。
#    用途：--layout 断行保护（断点不落在专名内部，四表并集 ALL_OFFICIAL_NOUNS）；
#    亦作后续校准匹配的官方名词底表。官方名词更新时重抓/重建本表即可。
# =============================================================
_WW_NOUNS_RAW = """
清宵 达妮娅 锁暝 景燃 穗穗 秧秧·玄翎 漂泊者-女-导电 漂泊者-男-导电 洛瑟菈 露西 丽贝卡 绯雪 西格莉卡 陆·赫斯 爱弥斯 莫宁 琳奈 千咲 仇远 嘉贝莉娜 尤诺 奥古斯塔 弗洛洛
露帕 夏空 卡提希娅 赞妮 坎特蕾拉 菲比 布兰特 洛可可 珂莱塔 守岸人 相里要 折枝 长离 今汐 吟霖 忌炎 漂泊者-女-气动 漂泊者-男-气动 鉴心 卡卡罗 安可 维里奈 凌阳
漂泊者-男-衍射 漂泊者-女-衍射 漂泊者-男-湮灭 漂泊者-女-湮灭 卜灵 灯灯 秧秧 釉瑚 白芷 炽霞 散华 秋水 丹瑾 莫特斐 渊武 桃祈 云琅 赝作的矮星 栖霞饮露 永远的启明星
时和岁稔 赫奕流明 琼枝冰绡 掣傀之手 诸方玄枢 苍鳞千嶂 天之苍苍 白昼之脊 存帧 蜃影 溢彩荧辉 碎骨 不屈命定之冠 昙切 幽冥的忘忧章 灼霜 宙算仪轨 万物持存的注释 和光回唱 焰光裁定
昭日译注 裁竹 光影双生 焰痕 驭冕铸雷之权 林间的咏叹调 镭射切变 玻色星仪 脉冲协臂 相位涟漪 源能机锋 海的呢喃 死与舞 星序协响 翼锋 曜光 凌空 阳焰 金穹 不灭航路 血誓盟约
大海的馈赠 虚饰的华尔兹 叙别的罗曼史 酩酊的英雄志 风流的寓言诗 容赦的沉思录 悲喜剧 渊海回声 裁春 心之锚 凋亡频移 永续坍缩 悖论喷流 尘云旋臂 核熔星盘 浩境粼光 千古洑流 停驻之烟
擎渊怒涛 漪澜浮录 飞景 奔雷 金掌 清音 异响空灵 行进序曲 华彩乐段 呼啸重音 奇幻变奏 重破刃-41型 瞬斩刀-18型 纹秋 穿击枪-26型 钢影拳-21丁型 鸣动仪-25型 永夜长明
不归孤军 无眠烈火 袍泽之固 今州守望 东落 西升 飞逝 骇行 异度 钧天正音 戍关长刃·定军 戍关迅刀·镇海 戍关佩枪·平云 戍关臂铠·拔山 戍关音感仪·留光 远行者长刃·辟路
远行者迅刀·旅迹 远行者佩枪·洞察 远行者臂铠·破障 远行者矩阵·探幽 源能长刃·测壹 源能迅刀·测贰 源能佩枪·测叁 源能臂铠·测肆 源能音感仪·测五 暗夜长刃·玄明 暗夜迅刀·黑闪
暗夜佩枪·暗星 暗夜臂铠·夜芒 暗夜矩阵·暝光 原初长刃·朴石 原初迅刀·鸣雨 原初佩枪·穿林 原初臂铠·磐岩 原初音感仪·听浪 教学长刃 教学迅刀 教学佩枪 教学臂铠 教学音感仪 天傀劫煞
融躯战士 万囮牢·朽躯 霁息兽尊 不熄猎手 霁息兽尊·首 霁息兽尊·身 心傀·恐 心傀·悲 心傀·思 心傀·忧 心傀·怒 心傀·喜 金庭候 石庭候 瓷庭候 封庭械囿 千傀重楼
共鸣回响·梦魇亚当·重锤 共鸣回响·达妮娅 共鸣回响·鸣式·虚造神型 辛吉勒姆 无铭探索者 海维夏 炉芯机骸 迷胧幻蛾 格洛犸图 共鸣回响·冠顶苍隼 冠顶械隼 风鳞蜃甲 锯袭铁影 隐迹铁影
霜鳞蜃甲 重工铁蹄 探隧重机 双极·渊陨重锋 双极·星升辉铳 矿岩机麋 莳植机麋 冰盈舞者 噼啪啪 岩蛛S4型 矿岩熊蜂 影烁者 莳植熊蜂 颤栗战士 共鸣回响·鸣式·利维亚坦 梦魇·赫卡忒
共鸣回响·芬莱克 赫卡忒 鸣钟之龟 梦魇·凯尔匹 梦魇·辉萤军势 梦魇·哀声鸷 梦魇·燎照之骑 梦魇·无冠者 梦魇·朔雷之鳞 梦魇·云闪之鳞 梦魇·无常凶鹭 梦魇·飞廉之猩 海之女 伪作的神王
共鸣回响·芙露德莉斯 无妄者 荣耀狮像 叹息古龙 异构武装 罗蕾莱 无归的谬误 辉萤军势 燎照之骑 哀声鸷 无冠者 无常凶鹭 飞廉之猩 聚械机偶 云闪之鳞 朔雷之鳞 梦魇·刺玫菇 梦魇·绿熔蜥
蚀脊龙 梦魇·青羽鹭 梦魇·紫羽鹭 梦魇·振铎乐师 角鳄 传道者的遗形 重塑雕像的拳砾 飓力熊 巨布偶 荣光节使 浮灵偶 凝水贵族 持刃贵族 毒冠贵族 暗夜骑士 幻昼骑士 琉璃刀伶 巡游骑士
游鳞机枢 雪鬃狼 巡哨机傀 绿熔蜥 踏光兽 磐石守卫 振铎乐师 暗鬃狼 刺玫菇 青羽鹭 戏猿 车刃镰 奏谕乐师 紫羽鹭 箭簇熊 坚岩斗士 冥渊守卫 梦魇·呜咔咔 梦魇·侏侏鸵
梦魇·刺玫菇（稚形） 梦魇·绿熔蜥（稚形） 梦魇·惊蛰猎手 梦魇·巡徊猎手 梦魇·啾啾河豚 梦魇·咕咕河豚 梦魇·审判战士 梦魇·破霜猎手 小翼龙·衍射 小翼龙·热熔 小翼龙·湮灭
苦信者的作俑 慈悲节使 赦罪节使 卫冕节使 小翼龙·气动 小翼龙·导电 小翼龙·冷凝 气动棱镜 愚金幼岩 釉变幼岩 霜鬃狼 雷鬃狼 风鬃狼 欺诈奇藏 工头布偶 寂寞小姐 魔术先生 云海妖精
幽翎火 浮灵偶·莱特 浮灵偶·蕾弗 浮灵偶·海德 叮咚咚 破霜猎手 寒霜陆龟 咕咕河豚 冷凝棱镜 热熔棱镜 绿熔蜥（稚形） 鸣泣战士 融火虫 火鬃狼 咔嚓嚓 阿嗞嗞 通行灯偶 衍射棱镜 游弋蝶
审判战士 呜咔咔 湮灭棱镜 刺玫菇（稚形） 呼咻咻 啾啾河豚 巡徊猎手 幼猿 惊蛰猎手 晶螯蝎 遁地鼠 先锋幼岩 裂变幼岩 碎獠猪 侏侏鸵 孪面 云海列车 留声奏者 祖渊海触 西莫斯先生
贡多拉 卫冕节使（公） 章鱼先生 拉里奥 浴缸犬 焙焙 高天讯使 弄臣 墨丘利机 颂诏节使 流明灯使 哈德良角斗士的肖像 饰音歌姬 梦魇亚当·重锤 噬影人·喜忧 噬影人·狂喜 噬影人·悲戚
冠顶苍隼 残星·刑锯帽匠 残星·餮餍袖匠 残星·扼拊爪匠 雷杖流民 执刃流民 鸣式·利维亚坦 芙露德莉斯 伤痕 芬莱克 裁夺者 残星·深海造匠 冥冠角斗家 雷冠角斗家 凛冠角斗家 耀冠角斗家
羽冠角斗家 炽冠角斗家 躁乱戏猿 嚣风戏猿 流放者首领 处刑人 阿兹兹 残星·枭面造匠 残星-枪支造匠 残星·重锤造匠 流放者工匠 冥途夜行之灯 清邪荡煞之心 羽落空尘之歌 碎梦亡鬼之魇
剪心辑梦之影 雪落无声之愿 听唤语义之愿 斑驳粉饰之沫 长路启航之星 逆光跃彩之约 星构寻辉之环 流金溯真之式 凝夜白霜 熔山裂谷 浮星祛暗 沉日劫明 啸谷长风 彻空冥雷 不绝余音 轻云出月
隐世回光 凌冽决断之心 高天共奏之曲 此间永驻之光 幽夜隐匿之帷 无惧浪涛之勇 流云逝尽之空 奔狼燎原之焰 愿戴荣光之旅 失序彼岸之梦 息界同调之律 荣斗铸锋之冠 焚羽猎魔之影 命理崩毁之弦
全息战略·燎照之骑 全息战略·无冠者 全息战略·万囮牢·朽躯 全息战略·达妮娅 全息战略·无铭探索者 全息战略·辛吉勒姆 全息战略·海维夏 全息战略·炉芯机骸 全息战略·无妄者
全息战略·伪作的神王 全息战略·荣耀狮像 全息战略·海之女 全息战略·凯尔匹 全息战略·罗蕾莱 全息战略·芙露德莉斯 全息战略·叹息古龙 全息战略·赫卡忒 全息战略·飞镰之猩
全息战略·无常凶鹭 全息战略·朔雷之鳞 全息战略·哀声鸷 全息战略·无归的谬误 全息战略·异构武装 凌空栈 护玄屏 异生雾 玄元境 内景 文明之匣 山猫妖 本命剑意 渐水舵 宿镜 偃师
归魂互助会 祀声之人 流息 玄翎雀 云渊之役 渊城 梁鸢 悬天构 定玄卫 外事府 后玄骑使 后玄三骑 咎庭 咎笼 歧路司 夜之城 超梦 黯原 隧锚 灼樱封印 换日庆典 学院暗面 折影
密涅瓦宝藏 涡心 诺维尔再生医药 日髓 雪绒海豹 虚质空间 天槎空间站 模块架构器 虚质不稳态 隧门 天空海 镇抚司 谛天鉴 心镜 奇美拉 法比亚纳 异维无音区 本兵 明庭 军策府 兰台
芬莱克一世 玄方地界 虚诞虫 医务室 拉贝尔磁带 频录装置 隧者 适格者 炉芯 联运椎骨 巨剑 虚质防壁 罗伊族 换日仪式 赫利俄斯 引日殿 日轮 秘日六席 浮光林 隧群 隧群元件 牧者
昭日者 日灵 日树 归源之仪 拉海洛 狩猎 黑潮造物 彻地之楔 风潮崖 四方殿 赤林猎场 猎号 狭渊 圣火 玛涅斯之底 槲叶勋章 狩王鹫 定向锚 锚定界石 往世花平野 呓语镇 受蚀地 醒真草
蚀像 路标刻像 黄金之歌 庆典蛋糕 第二索拉 团子 诫令院 蜃境 信道 猎犬 《金枝记》 安魂乐园 天马座 旋律 拉贝尔曲线 先天型共鸣者 突变型共鸣者 自然型共鸣者 诱导型共鸣者 声痕 超频
鸣式 悲鸣 回音 索诺拉 无音区 索拉里斯 海蚀 残象 声骸 岁主 令尹 天工 夜归 巡尉 治安署 巡宁所 呜呜物流 今州 华胥研究院 瑝珑 翡萨烈 波蒂维诺堡 拉古那 水星天 隐海修会 教士
莫塔里 狂欢节 桂冠 贝币 英白拉多 溯海之鲸 埃弗拉德银行 愚人剧团 泰缇斯 调律者 今巡尉 飞檐 雷煌拳 龙须酥 岁主「角」 类书 今令尹 「幻梦」 「紫绒梦」 「梦的彼岸」 佩洛 珍奇箱
令尹近卫 「黄金之歌」 悲田院 玄渺真人 今州参事 竞渡会 瑞狮团 狮子舞 狮首 星星花 风仪拳 银行 黑街 第二次黑潮 十年前的狂欢节事件 踏白 忧昙 噬亡星 心之集域 索拉电影院
索拉电影节 梦魇残象 黑色守门人 白色守门人 深水层 大角斗赛 鹫巢石城 饮心 谕女 剧本 梦州 战队 「烈日」酒馆 总督 铜镜 涨潮期 荣耀之间 潮蚀 玛尔斯工业 分界山 角斗士 声骸角斗
古英雄铠 卡庇托山 守护兽声骸 西尔瓦家 元老院 黑潮云 崖港 莉莉贝 「预言书」 「英雄王」 隐海试验场 失亡彼岸 声骸培育舱 黑潮 溯洄雨 代行者 彼世 鸣式宝石 桑古伊斯狩原 虹音塔
往人 虹光 余念 虹晶 星炬学院 虚质磁暴 深空联合 波仔 迷途波仔 苇原 黑海岸 黎那汐塔 烟岚 临界共鸣 霆怒 电涌 流岚 绝息 苍翎 流响 翾舞 重明照影 芳菲信 水云息 濯雨时 浣尘时
仙游碧落 山河水境 春生 润物 欺骗程式 SQL 根权限 【骇破·干涉】 传输协议 算法压缩 【骇破·偏移】 手感火热 狂热 小孩子才做选择！ 过载 铁胆 猎手 追忆状态 变焦 胶卷 照片
熵变强化 印象 霜冻效应 霜结 预求身 常世身 锻雪·归刃 淬寒·枯霜 武霜·居合 寒意 心念 共形能量 熵变强化·布景之形 熵变强化·幻灭之形 虚质粒子 黯核 凝语 解读 日灵能量 回声
专注 「天赋？」 句点 符文 日髓阵列 日髓碎刃 日辉庇覆 日髓能流 终局之释义 聚爆轨迹 震谐轨迹 流溢辉光 合击·突刺 光翼共奏 流光增幅 共鸣率 同步率 星辉破界而来·于此释放 星屑共振
即刻响应 本色 流光 溢彩 颜料 光致变染 绮彩巡游 「光学取样」阶段 强谐振场 谐振场 干涉标记 观测标记 【相对动能】 【静质量能】 广域观测模式 基准模式 【集谐·干涉】 【震谐·干涉】
【集谐·偏移】 【震谐·偏移】 【谐度破坏】 雷法·三才合一 五雷荡煞阵 阴阳相生 卦象 异常效应伤害 电磁爆发 万缕·汇终 命弦·本流 锯环残响 虚湮之线 虚无绞痕 内燃烧 永恒位格
烟云幽远心剑鸣 蜃云灯影凡尘剑心 玄方地界 玄方城 玄方 云梭 云帛机骑 神宫 咎庭 定玄卫 军策府 天工部 御剑飞行 剑意 心剑 玄元境 人境 地境 异生雾 寻幽客 鬼猫挈灯 引歧帘 宿镜 云渊之役 渊城 衔翎村 雾隐阁 梦州 华亭 禁锁十契 十重契 谛天鉴 万相分形 白狐形态 玄翎雀 玄翎 清宵 心月狐 锁暝 秧秧 穗穗 景燃 木禺 小玉 若云 静微 烟舒 秋鸿 椋羽 长离
恶魔位格 阈限状态 净炼火 罪火 余火 竹照 淋漓醉墨 挑灯问剑 俯首之刻 王之界域 威慑 权炳 战势 灵性 苍白死光的祝颂 月相流转 以众愿为冕 指挥状态 余响 定音 乐声 神权剑之影
异权剑之影 人权剑之影 异权之力 神权之意 人权之心 异常效应 决意 荣光 赛点沸腾 追猎 狼魂 狼焰 准备架势 烈阳余烬 焰光 灼焰形态 冗余动能 共振度 音律 音律独奏 合奏音影 行狮
天籁 弦风息 迷梦 蜃境状态 涛声喝彩 戏中人生 燃焰 喝彩 虚实之门 雾气 磐岩护壁 祯祥 问祯 红灯模式 黄灯模式 热压弹 朱蚀之刻 彤华 浮翼狂想 冰川 冰棘 冰棱 暗涌 念意 破阵值
破阵状态 审判值 缚罪标记 灵韵 共鸣能量 可塑晶质 灵萃 解离 变彩 含苞状态 坍缩核 星域 浅析星域 洞见 鹤影 想象力 福音 飞跃幻想 乘岁凌霄 韶光 心眼 离火 光合能量 镜之环
协奏能量 电磁效应 虚湮效应 聚爆效应 霜渐效应 光噪效应 风蚀效应 布倒翁 弱观测时钟 追「布」战记 可动机偶战团 升级 「爆发·震荡冲击」 危险状态 「增幅·咖啡守护」 「爆发·咖啡冲击」
「增幅·心满意足」 「连击·甜品打击·强」 「连击·甜品打击」 「增幅·点心制备」 「异常·海蚀净除」 「连击·援护飞弹」 「连击·援护飞弹·强」 「增幅·疾驰」 「增幅·波仔援护」
「爆发·灼热冲击」 「爆发·灼热火柱」 「连击·米团飞弹·强」 「连击·米团飞弹」 可助力进化 【特型】 【光束】 【召唤】 【弹道】 爆裂征兆 飞廉冲击 无序暗火 炽灼之星 风乐交响
月满今时 灰烬血誓 风息裂象 光炮 闪映华光 猩红轮链 天渊风剑 异构飞弹 猎手陷阱 范围强化 伤害提高 核心 饱和火力 银弹攻势 雷闪无息 库默尼商行 幸运币 导电类装置 气动类装置
热熔类装置 冷凝类装置 声骸类装置 异梦·刺玫菇 梦块·水镜碎域 聚变魔方 相邻 任意稀有度 同排 棱镜 梦块·黑石碎域 刺玫菇（系列声骸） 初始素体 移除 乐园人偶·叮咚咚 集章纪念册
梦境列车 乐园人偶·遁地鼠 发条灯偶 惊喜盲盒 镜中万花 幻梦礼花 梦境·转转转 乐园人偶·咕咕河豚 幸运摇铃 乐园人偶·指挥家 梦块·冰晶碎域 梦块·沙石碎域 定身 换取之物 声骸征聘
频率晶体 乐园券 每日乐园券 融合 换取 吞噬 递变 共通之梦 融合之梦 换取之梦 吞噬之梦 递变之梦 幽客销残声 烟云幽远心剑鸣 灵籁之契冥相因 玄翎振壑定澜音 山雨欲来风满楼 我们选择天空
边缘幻梦 在熔解的夜空下 愿系铃中·续 昨夜群星 愿系铃中 影面颠倒的兔影 影下不落的黄金 日光落处 远航星 致第二次日出 冰原下的星炬 未知的既感 星光流转于眼眸之间 曙光停摆于荒地之上
独在异乡为异客 暗潮将映的黎明 已逝的必将归来 今夜，注定属于月亮 灼我以烈阳 铁锈，剑与烈阳 捕梦于神秘园中 燃烧的心 荣耀暗面 圣者，忤逆者，告死者 老人鱼海 昔我悲伤，今却歌唱
夜与昼，均请摘下面纱 那神圣微风时常吹入 如一叶小舟穿行于茫茫海洋 行至海岸尽头 往岁乘霄醒惊蛰 行路遇新知 欲知天将雨 庭际刀刃鸣 奔策候残星 撞金止行阵 嘤鸣初相召 夜行的焰光
启航日，船长！ 幽夜幻梦 今夜星光灿烂 如果在雨夜，一个家族 小径分岔的星海 小小羊咩大冒险 自问丹青 离火弈长生 此际我独行 啸野归城 长夜将明 团团团团转 暗夜叩响白昼之门
一段像是日记的字迹 贴在墙上的告示 机傀检修报告 旧研究院照片 深空联合人事调动回执 「出口」钥匙 对虚材质研究所留念 残破的学生宿舍照片 泛黄的学生宿舍照片 展览馆核心区照片
来源不明的文字（理查德老了……） 来源不明的文字（那扇门后面连接的是……） 来源不明的文字（“**，真会给我挑时候……”……） 来源不明的文字（“照照镜子吧，约翰……）
来源不明的文字（这座城市的人不断为别人的超梦买单……） 来源不明的文字（“渴望天空的鸟，是不会被笼牢所囚禁的。”……） 来源不明的文字（军用级斯安威斯坦……） 来源不明的文字（只需两分钟……）
来源不明的文字（灌木丛中横躺着昨夜……） 来源不明的文字（作为超梦的导演……） 致老师 事故说明 残留的腐蚀试验报告 残留的腐蚀检测 诊断1 诊断2 爆料电视？ 不准时宝 西格莉卡的日记
《时尚搭配指南》 《星炬学院新闻报》 大团长掉落的笔记 《霸道令尹爱上我》 九星的徽记 非理想光源 光形物语 砂上飞行 虚诞的幽影 可再生能源 五朔之狂 直至无岩以怼 地毯式搜索 隙末凶终
触觉练习 力的注脚 头顶尖尖 协契共舞 似鹅卵石 石鳍与鼠 雪原之裔 甦生的林野 悠远的绿意 温热的一隅 坠落的眼眸 停歇的巨影 漫游的执念 冰封的航路 凝结的欲念 脊椎，生命线 覆雪的归原
星海的旧愿 永冬，先驱者 金枝萌芽 复乐园 好奇的尺度 于黯处闪烁 逾冬的羽翼 北落天悬 曲水逐落英 今时关城 幽花一树明 咫尺月 岁主塑像 旧雨将至 愁永昼 云销雨霁 梦的解析 远眺屏庭山
安全第一！ 失重的摩天楼 港市遗音 罗伊冰原 七丘 阿维纽林 鸣潮 残响 海蚀现象 共鸣者 阿列夫一 频率衰竭 共鸣抑制装置 鸣式残留 漂泊者 马小芳 珂莱塔·莫塔里 坎特蕾拉·翡萨烈
夏空·托卡塔 安吉尔 朽叶千咲 阿布 阿布拉克萨斯 哥舒临 辛夷 瓦莲京娜 史考特·拉贝尔 克里斯托弗 玛格丽特 罗斯玛丽·翡萨烈 蜜芽 阿维狄亚 梁东园 澄夏 扎希拉 德莉珐 查特 越州 重州 诏州
戎州 先行公约 残星会 幽灵猎犬 稷廷 新联邦 黎乔利群岛 埃弗拉德金库 莉莉兰德 穗波 乘霄山 虹镇 云陵谷 虎口山脉 中曲台地 怨鸟泽 无光之森 归墟港市 黑海岸群岛 泰缇斯之底 贝奥海域
三王峰 黑潮异域·巡游天国 时隙废都 牙列石壑 陷足流川 复生丘原 蚀刻平原 隐喙深腹 巨目远野 落日堤屿 封存地 寂静断崖 恒黯之原 梦州·玄方地界 玄方城 玄幽东岳 方擎西峰 落渊南丘
无相燹主 凯尔匹 利维亚坦 梦魇·武装公司狗 梦魇·安保公司狗 梦魇·突击公司狗 未知共鸣者 撞响止钟的行阵 守望永恒 若流星盛放 荣耀尽头的天空 渊底之火 光的来处 车手一号 失落的乐声
紧急事件：核心危机 危构悬天问丹心 雾锁机伶 天上月华人如愿 致缄默以欢歌 真伪倒悬于高塔 焰行夏曲庆"团"圆 轻掷欢呼之冕 生命不灭的轻歌 日以灼锋，月以流明 奔往琥珀之都 我们生而眺望
于影中启明的决心 自星海尽处回响 未选择的梦 遗音扶剑，荡梦而歌 蜃云灯影，凡尘剑心 但觉今州胜旧州 前往尚未亮起的星
"""

WW_OFFICIAL_NOUNS = frozenset(_WW_NOUNS_RAW.split())

# 终末地官方专有名词（2026-08-29 取自《终末地_故事专有名词_中英日韩对照表.md》
# 中文列，截至 1.4「向渊行」；含 · 词尾拆分与 塔罗斯/环塔商会/联盟工团/李织烟/伊库特 等补录）
_ENDO_NOUNS_RAW = """
明日方舟：终末地 终末地 峘形山 鹰角网络 格里芬 跨越边境，直至前线 塔卫二 泰拉 星门 萨米星门 终末地计划 终末地工业 协议回收部门 协议核心 自动化集成工业系统 源石 衍质源石
至纯源石 最初的源石 矿石病 源石技艺 侵蚀 天灾 天使 暴君 再旅者 破土者 裂地者 帝江号 前文明 伐木工 同化宇宙 灰质钉 超域 甚大裂隙 武陵巨型裂谷 枢壤仪 文明环带 开拓区
环带公约 环带居民 息壤仪 泰拉纪元 天使战争 第二次天使战争 殖民纪元 开拓纪元 回归 开拓 罗德岛 炎国 宏山科学院 环塔卫二企业联合商会 塔卫二全联盟工团 三大阵营 众生长地 寂语修会
铁誓军 塞什卡 狼群 碾骨氏族 沙盗 深空联合 锦隆 天师府 武陵城巡卫队 应龙特勤队 序章 基地解围 谷地重启 重整旗鼓 西行入谷 庇护之所 建立据点 踏破雾火 要塞决战 开拓前路 春晓时
寻遗散记 向渊行 曙光不灭 相伴庆典 锈蚀回廊 晨星降临 如流星飞越边界 管理员 佩丽卡 陈千语 狼卫 洁尔佩塔 伊冯 莱万汀 黎风 艾尔黛拉 骏卫 余烬 庄芳仪 弧光 梨诺 赛希 艾维文娜
昼雪 大潘 阿列什 别礼 萤石 埃斯特拉 阿凯 蜜芙 弭弗 唐棠 罗西 卡米尔 噗切娜 秋栗 卡契尔 卡缪 安塔尔 阿克库里 捕手 安洁莉娜 史尔特尔 阿达希尔 聂菲斯 四小姐 阮一 安德烈
阿里曼 洛茜 大山 阿列莎·柯林斯 柯林斯 涅法莉丝 索斯 洪博 阿仔 雪峰猎手 哈茨曼 安吉罗 提弗洛斯 奥里莎师者 武陵 清波寨 方兴衢 应龙关 武陵北部封锁区域 北部禁区 盈天台建设站
填隙柱地 心脏修缮站 月往日来 墟烟 溪然流云播种站 首墩 试验园区 藏剑谷 谷底 四号谷地 萨米 荒野 无人区 悬空城 极地 黎博利 鲁珀 菲林 瓦伊凡 萨卡兹 萨科塔 阿纳萨 沃尔珀
斐迪亚 卡普里尼 萨弗拉 卡特斯 神民 先民 巨兽 岁相 岁代理 巨兽之心 希拉尼特 预言家 普瑞赛斯 特蕾西娅 博士 刚角天使 大角天使 三位一体天使 碾骨先锋 碾骨行刑人 碾骨破城者
源石虫 潜地虬兽 摧山将 开天将 白垩界卫 咆兽 侵蚀人形物 蚀影 千夫长·阿莱克琉斯 阿莱克琉斯 权限芯片 能源控制台 合金门 石馆 墓碑 协议-源石传送 塔罗斯 环塔商会 联盟工团 李织烟
伊库特
幽林之怒 雪凇幽梦 雪松林 遂明 遂明城 巫术造物 兽主 安玛 雪祀 寒夜幽影 苦难的尽头 点心时刻 雾隐冬梦深林中 冬猎 绚丽异彩 重构寻访 幽寒申领 点绘申领 镞砺括羽 影拓丰碑 幽影刻形 挽弓试炼 存续的痕迹 高级认知载体
"""

ENDFIELD_NOUNS = frozenset(_ENDO_NOUNS_RAW.split())

# 明日方舟官方专有名词（2026-08-29 取自《Arknights_Lore_Terminology_EN_CN_JP_KR.md》
# 中文列；去全角括号注、/ 别名拆分、・→·，含主线/别传/故事集/肉鸽/生息演算/危机合约等
# 章节名与角色/阵营/地名/世界观名词，共 581 条）
_AK_NOUNS_RAW = """
不义之财 不觅浪尘 丛林症结 东国 丰蹄 临光 乌尔比安 乌有 乌萨斯 乌萨斯学生自治团 乌萨斯帝国 乌萨斯的孩子们 乔万娜 云兽
人们，我们 仇白 企业骑士 企鹅物流 伊内丝 伊比利亚 伊比利亚王国 伊维格娜德 伊芙利特 伊莎玛拉 众生行记 伦蒂尼姆 伦蒂尼姆城防军 伦蒂尼姆市民自救军
伺夜 佩尔多尼 佩洛 使徒 依特拉 傀影 傀影与猩红孤钻 克丽斯腾 克莱布拉松 冠军骑士 冰原 冰酿 净罪作战 凋零骑士
凛冬 凯尔希 出苍白海 切尔诺伯格 切斯柏 初雪 刻刀 勾吴城 匹特拉姆 医生 十字路口 午间逸话 华法琳 博士
卡兹戴尔 卡兹戴尔军事委员会 卡兹戴尔王室 卡夫卡 卡拉顿 卡普里尼 卡涅利安 卡特斯 卡西米尔 卡西米尔商业联合会 卡西米尔无胄盟 卡西米尔监正会 卡达 去咧嘴谷
双子女皇 双日城 双月 变形者集群 叙拉古 叙拉古人 古米 可露希尔 可颂 史尔特尔 号角 司岁台 吾导先路 呼啸骑士团
和弦 咪波 哥伦比亚 喀兰圣山 喀兰贸易 喧闹法则 四国战争 因陀罗 因非冰原 图耶 圣山 圣约送葬人 圣骏堡 埃拉菲亚
塔尔干主矿脉 塔山生物科技 塔拉 塔露拉 塞拉托 塞雷娅 夏栎 多伦郡 多索雷斯 多索雷斯假日 多萝西 夜刀 夜半 夜莺
大叛乱 大尉 大理寺 大群意志 大荒城 大骑士领 天灾 太傅 太合 太阳甩在身后 太阳谷机械工业 奇美拉 奇象巡展 奥伦
奥斯塔 女妖 女妖王庭 好久不见 威灵顿公爵 子月 孤岛风云 孤星 宁小姐 安努拉 安哲拉 安多恩 安布罗修修道院 安洁莉娜
安赛尔 密林悍将归来 寻昼行动 导火索 将进酒 小丘郡 尘影余音 尘环行动 尚蜀 屠谕者 岁兽 崔林特尔梅 崔林特尔梅之金 崖心
嵯峨 巡林者 左乐 左手骑士 巫妖 巫妖王庭 巫恋 巴别塔 布丁 布洛卡 帕拉斯 幻影弩手 幽灵鲨 序章：黑暗时代·上
库兰塔 开斯特公爵 弑君者 弗莱蒙特 归溟幽灵鲨 彩虹小队 御机 循兽 德克萨斯 德拉克 德米特里 怀黍离 恐鱼 惊蛰
愚人号 愚夜密函 感染者 感染者骑士 战地秘闻 战车 戴菲恩 扎罗 托兰 拉普兰德 拉特兰 拉特兰中庭公证所 拉维妮娅 拉芙希妮
拜松 挽歌燃烧殆尽 探索者的银凇止境 推进之王 提卡伦多 揭幕者们 摩根 教宗 整合运动 文月 斐尔迪南 斐迪亚 斥罪 断崖
斯卡蒂 新沃尔西尼 日暮寻路 早露 明日方舟 明椒 星极 星熊 春分 暴行 曼弗雷德 曼提柯 月禾 札拉克
杏仁 杜林 杜林地下王国 杰西卡 松果 松烟行动 极光 极境 林贡斯 林雨霞 柏喙 柯克西卡 格兰法洛 格劳克斯
格拉斯哥帮 格特鲁德 梁洵 梅兰德基金会 梅尔 梅菲斯特 棘刺 槐琥 歌蕾蒂娅 止颂 正义骑士号 此地之外 水晶箭行动 水月与深蓝之树
汐斯塔 沃伦姆德 沃伦姆德的薄暮 沃尔沃特科钦斯基 沃尔珀 沃尔西尼 沉沦者的黑流树海 沙中之火 沙地兽 沙尔-阿加德 沙洲遗闻 沙滩伞公司 沸血骑士团 法杖
泡影苍霆 泥岩 泰拉 洛洛 洪炉示岁 流明 浊心斯卡蒂 浊燃作战 浮士德 海嗣 海蒂 涤墨作战 深律 深池
深海 深海猎人 深海色 深靛 清流 渊默行动 温德米尔公爵 温蒂 温迪戈 源石 源石技艺 潮曦作战 火山旅梦 火蓝之心
火龙S黑角 灯下定影 灯火序曲 灰毫 灰烬 灵知 炎国 炎客 炎熔 炎狱炎熔 烈夏 烛骑士 焚风热土 焰尾
焰影苇草 照我以火 熠曲丰碑 爱丽丝 爱国者 爱布拉娜 牧群 特蕾西娅 特里蒙 特雷西斯 狩猎时光 独眼巨人 独眼巨人王庭 独立骑士
狮蝎 狼之主 玄铁 玉门 玛恩纳 玛莉娅·临光 玻利瓦尔 玻利瓦尔独立国 玻利瓦尔王国 玻利瓦尔联合政府 理想城：长夏狂欢季 琴柳 瑕光 瑞柏巴
璟屿主矿脉 瓦伊凡 瓦伊凡联盟 瓦拉赫 生于黑夜 生息演算 生路 画中人 瘤兽 登临意 白垩 白金 白铁 白面鸮
百夫长 百灶 百炼嘉维尔 皇帝的内卫 皮洛萨 盐风城 直到大地变成一颗酸橙 相变临界 相见欢 真正玻利瓦尔人解放运动 真理 石棉 矿石病 碎骨
神民 离解复合 科林尼亚 科罗萨主矿脉 科西切 移动城市 稀音 空弦 空想花庭 空构 第一章：黑暗时代·下 第七章：苦难摇篮 第三章：二次呼吸 第九章：风暴瞭望
第二章：异卵同生 第五章：靶向药物 第八章：怒号光明 第六章：局部坏死 第十一章：淬火尘霾 第十三章：恶兆湍流 第十二章：惊霆无声 第十五章：离解复合 第十六章：相变临界 第十四章：慈悲灯塔 第十章：破碎日冕 第四章：急性衰竭 米诺斯 絮雨
红丝绒 红松林 红松骑士团 红豆 约翰老妈 纯烬艾雅法拉 终极大铁屯 绮良 维多利亚 维多利亚帝国 维荻 维谢海姆 绿野幻梦 缄默德克萨斯
缪尔赛思 罗伊 罗塞蒂家族 罗宾 罗德岛 罗德岛-精英干员 罗德岛123 罗德岛制药公司 罗德岛基建 罗德岛本舰 羽蛇 耀骑士 耀骑士临光 老天师
老鲤 耶拉 能天使 腐败骑士 艾丽妮 艾拉 芙兰卡 芙蓉 苦艾 荷谟伊 莉泽洛特 莫尼克 莫斯提马 莱塔尼亚
莱恩哈特 莱茵生命 菲亚梅塔 菲林 萨卡兹 萨卡兹混血 萨卡兹王庭军 萨卡兹的无终奇语 萨卢佐家族 萨尔贡 萨弗拉 萨科塔 萨米 落叶逐火
蒙特卢佩 蒸汽骑士 蓝毒 蔓德拉 蕾缪安 薇薇安娜 蚀清 蛮鳞行动 蜜莓 蜜蜡 血骑士 血魔 血魔大君 行动组A4
行动预备组A1 行动预备组A4 行动预备组A6 裂兽 褐果 西绪福斯 覆巢之下 见行者 角峰 讯使 诗怀雅 诺斯伍德大骑士团 谢拉格 豆苗
贝娜 贝娜德塔 贝洛内家族 贝纳尔多 贾维 贾维团伙 赝波行动 赦罪师 赫尔昏佐伦 赫德雷 赫默 起源行动 踏寻往昔之风 车尔尼
辛嘉斯王朝 辞岁行 达格达 达维镇 远牙 迷迭香 追迹日落以西 送葬人 透明信笺 逐魇骑士 遗尘漫步 重启锚点 重岳 野鬃
钳兽 铃兰 银心湖列车 银灰 锁川 锈铜骑士 锈锤 锡人 长夜临光 长泉镇 闪击 闪灵 阴云火花 阿丽娜
阿列夫 阿加门 阿勒黛 阿卡胡拉 阿尔贝托 阿戈尔 阿戈尔深海 阿撒兹勒 阿斯兰 阿斯卡纶 阿米娅 阿纳缇 阿赫茉妮 阿达克利斯
际崖城 陨星 隐现 雅拉 雅赛努斯 雅赛努斯复仇记 雪怪小队 雪绒 雪踵骑士团 雪雉 雷姆必拓 雷神工业 雷蛇 霍尔海雅
霜华 霜星 青金 鞭刃 音律联觉 风笛 风雪过境 食腐者之王 食腐者之王庭 食铁兽 首言者 香草 驮兽 骏鹰王国
骑兵与猎人 骑士竞技 高卢 高多汀公爵 魏彦吾 魔法与友谊 鲁珀 鲤氏侦探事务所 鸿雪 麒麟 麒麟R夜刀 麦克斯哥伦比亚特区 麦哲伦 黎博利
黑角 黑钢国际 黑键 黑骑士 鼷兽 龙门 龙门近卫局
"""

ARKNIGHTS_NOUNS = frozenset(_AK_NOUNS_RAW.split())

# 战双帕弥什官方专有名词（2026-08-29 取自《战双帕弥什_专有名词中英日韩对照表.md》
# 中文列；去全角括号注（指挥官（玩家）、但丁（DMC5）等）、/ 别名拆分，含构造体/小队/
# 势力/地点/外篇活动名，共 253 条；主线章节名因含半角空格未收录，不影响断行保护）
_PGR_NOUNS_RAW = """
015号城市 21号 21号·XXI 21号·森息 Ω武器 一出好戏 七实 七实·脉冲 七实·芒星之迹 七实·遥星之座 七实·风暴 万世铭 万事 万事·明晰梦
万事·明觉 三头犬小队 世界政府 丽芙 丽芙·仰光 丽芙·极昼 丽芙·流光 丽芙·蚀暗 丽芙·霁梦 九龙众 九龙商会 九龙夜航船 九龙环城 亚特兰蒂斯
亚里莎 亚里莎·回音 代行者 伊什梅尔 伊什梅尔·幻日 但丁 先锋型 八咫 八咫·徊闪 内维尔 冯·内古特 冯·内古特集团 加百列 北极
北极航线联合 千子 升格网络 升格者 卡俄斯 卡列尼娜 卡列尼娜·烬燃 卡列尼娜·烬航 卡列尼娜·爆裂 卡列尼娜·辉晓 卡吉尔 卡穆 厄愿潮声 古茗遗章
名为英雄之物 含英 含英·檀心 含英·清商 咏叹回声 哈卡玛 哈卡玛·隐星 圣甲虫小队 地下城 地球 埃则忒 增幅型 多米尼克 多维演绎
大撤退 奥赛兰姆 守林人 宣叙妄响 寄渊残响 寒羊小队 尼禄 工程部队 巴拉德 布丽姬特 布丽姬特·灼惘 布偶熊 帕弥什 帕弥什病毒
帕弥什红潮 常羽 常羽·游麟 序章 库洛姆 库洛姆·弧光 库洛姆·荣光 库洛游戏 异合人形 异合生物 异聚塔 异聚核心 思维信标 悠悠
惑砂 意识海 意识营救战 感染体 慈悲者 战双帕弥什 执行部队 拉弥亚 拉弥亚·深谣 指挥官 授格者 支援小队 斜奏 斜奏·裁律
斯布纳 新地球政府 时宇漫纪 普利亚森林公园 曲·启明 曲·雀翎 未语庭言 本我回廊 机械先哲 机械教会 极地暗流 构造体 枯朽为灯 柯蕾多尔
格式塔 比安卡 比安卡·晖暮 比安卡·深痕 比安卡·真理 比安卡·零度 法奥斯军事学院 洁塔薇 洁塔薇·破晓 浮点纪实 海伦汀 海伦汀·安魂 涅缇娅 涅缇娅·亡歌
清庭白鹭小队 清理部队 渡边 渡边·夙星 渡边·夜刃 渡边·尘铭 游云鲸梦 湛蓝暑日 湮灭型 灰鸦小队 狄安娜 环大西洋四大家族 生命之星 白色光谱
监察院 相约纪事 矩阵循生 破甲型 神威 神威·不落日 神威·暗能 神威·重能 神寂启示录 科学理事会 空中花园 突击鹰小队 粽子 繁星谣
红潮 维吉尔 维罗妮卡 维罗妮卡·铮骨 维里耶 罗兰 罗兰·戏炎 罗塞塔 罗塞塔·凛冽 罗塞塔·极锋 考古小队 聚噬体 艺术协会 艾拉
艾拉·万华 艾拉·溢彩 花之歌 苏菲亚 苏菲亚·银牙 莉莉丝 莉莉丝·谬影 萨费恩学派 蒲牢 蒲牢·华钟 蓝色小鸟 薇拉 薇拉·灼惘 薇拉·绯耀
虚像破执 虹莺小队 观测者 观测者型 诺克提 诺克提·擎驱 诺安 诺安·逆旅 诺曼国际矿业 调色板战争 贾米拉 赛琳娜 赛琳娜·岚音 赛琳娜·希声
赛琳娜·幻奏 辉耀的行进者 边界公约 迷境刻痕 逆元坍塌 逆元装置 遗忘者 遥岸方舟 邂逅时光 邦比娜塔 邦比娜塔·琉璃 里·乱数 里·异火 里·超刻
重返极地 阿尔卡纳 阿尔法 阿尔法·深红囚影 阿尔法·逆冕 阿迪莱 阿迪莱商业联盟 零点能 零点能反应堆 雾岛悠子 露娜 露娜·终焉 露娜·银冕 露娜集团
露西亚 露西亚·深红之渊 露西亚·深红囚影 露西亚·红莲 露西亚·誓焰 露西亚·逆冕 露西亚·鸦羽 露西亚·黎明 静夜 黄油小狗 黄金之涡 黄金时代 黑岩射手 黑野
黯原
"""

PGR_NOUNS = frozenset(_PGR_NOUNS_RAW.split())

# layout 断行保护用的官方名词全集（鸣潮 + 终末地 + 明日方舟 + 战双帕弥什）
ALL_OFFICIAL_NOUNS = WW_OFFICIAL_NOUNS | ENDFIELD_NOUNS | ARKNIGHTS_NOUNS | PGR_NOUNS


# 首字索引：官方名词四表并集 2300+ 条，逐条 find 是 O(名词数×行长)；
# 建索引后 _noun_spans 只需为行内每个字符查一次首字桶，桶内做 startswith。
_NOUN_BY_HEAD = {}
for _w in ALL_OFFICIAL_NOUNS:
    _NOUN_BY_HEAD.setdefault(_w[0], []).append(_w)
_NOUN_BY_HEAD = {c: tuple(ws) for c, ws in _NOUN_BY_HEAD.items()}


def _noun_spans(s):
    """返回 s 中所有官方专名出现的 (起, 止) 区间列表。"""
    spans = []
    for i, ch in enumerate(s):
        for w in _NOUN_BY_HEAD.get(ch, ()):
            if s.startswith(w, i):
                spans.append((i, i + len(w)))
    return spans


def _inside_noun(spans, pos):
    """断点 pos 落在某官方专名内部（不含两端）时为 True。"""
    for st, ed in spans:
        if st < pos < ed:
            return True
    return False


# =============================================================
# 通用校准函数（按模式逐行原位替换，保持格式一字不变）
# =============================================================
def _compile_map(mapping):
    """预编译术语表 -> (按键长降序的 (key, value) 对, 键字符并集)。
    每张表只编译一次，避免逐行重复排序；字符集用于整行快速预筛。"""
    pairs = sorted(mapping.items(), key=lambda kv: len(kv[0]), reverse=True)
    charset = frozenset("".join(mapping)) if mapping else frozenset()
    return pairs, charset


def _replace_report(text, pairs, charset, hits):
    """单遍完成 长键优先替换 + 命中统计。
    行内不包含任何键字符时不可能命中，直接原样返回（整行预筛）。"""
    if not charset or charset.isdisjoint(text):
        return text
    for k, v in pairs:
        if k in text:
            hits[k] = hits.get(k, 0) + 1
            text = text.replace(k, v)
    return text


def apply_map(text, mapping):
    """按错误形式->正确形式替换，长词优先。"""
    pairs, charset = _compile_map(mapping)
    return _replace_report(text, pairs, charset, {})


def _load_override_tsv(path):
    """读取 序号<TAB>校准后中文 侧车覆盖表 -> {str: text}。行分隔可为 TAB/全角空格。"""
    over = {}
    if not os.path.exists(path):
        return over
    for ln in open(path, encoding="utf-8-sig").read().splitlines():
        ln = ln.strip("\ufeff").rstrip("\r")
        m = re.match(r"(\d+)", ln)
        if not m:
            continue
        txt = ln[m.end():].lstrip("\t \u3000\u3000").strip()
        if txt:
            over[m.group(1)] = txt
    return over


def process(path, out_path=None, report_path=None, mode="bi", layout_opt=False,
            fix_en=False, pgr_override=None):
    """对 SRT 校准。返回 (改动行rows, 术语命中hits)。
      mode="bi"   双语模式：BILINGUAL_TERMS + CONTEXT_MAP + WORD_MAP 改首中文行。
      mode="ko"   韩语模式：KO_TERMS 统一中文行术语。
      mode="ja"   日语模式：JA_TERMS + JA_CONTEXT（日语参考行佐证）统一中文行术语。
      mode="endo" 终末地模式：ENDFIELD_TERMS 统一全部文本行。
      mode="ak"   明日方舟本体模式：AK_TERMS 统一中文行术语（仅首中文行）。
      mode="zho"  中文行专属模式：ZH_ONLY_TERMS 只改首中文行英文噪音（不动英文/参考行）。
      layout_opt=True 中文行按 layout_line 拆两行（会增行，仅显式开启时使用）。
      fix_en=True   双语模式下用 EN_LINE_TERM_FIXES 修正英文/参考行（默认不动）。
    """
    if mode == "ko":
        terms = KO_TERMS
    elif mode == "ja":
        terms = JA_TERMS
    elif mode == "jpe":                 # 日语原声·终末地：JA_ENDFIELD_TERMS + 上下文佐证
        terms = JA_ENDFIELD_TERMS
    elif mode == "wwoc":
        terms = WWOC_TERMS
    elif mode == "endo":
        terms = ENDFIELD_TERMS
    elif mode in ("ak", "zho"):
        terms = AK_TERMS if mode == "ak" else ZH_ONLY_TERMS
    elif mode == "akko":        # 明日方舟韩语原声：AK_KO_TERMS + AK_KO_CONTEXT(韩语佐证)
        terms = AK_KO_TERMS
    elif mode == "react":
        terms = REACT_TERMS
    elif mode == "pgr":
        terms = {}
    else:
        terms = BILINGUAL_TERMS
    # 术语表只编译一次（长键序 + 键字符集），逐行替换走 _replace_report 单遍扫描
    term_pairs, term_chars = _compile_map(terms)
    word_pairs, word_chars = _compile_map(WORD_MAP)
    enfix_pairs, enfix_chars = _compile_map(EN_LINE_TERM_FIXES)

    raw = open(path, "rb").read()
    crlf = b"\r\n" in raw
    bom = raw.startswith(b"\xef\xbb\xbf")
    norm = raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    lines = norm.split("\n")
    out = list(lines)
    inserts = []          # --layout 拆行产生的新增行：(行号, 文本)

    hits, rows = {}, []
    i, n = 0, len(lines)
    while i < n:
        s = lines[i].strip()
        if s.isdigit() and (i == 0 or lines[i - 1].strip() == ""):
            j = i + 1
            if j < n and "-->" in lines[j]:
                kk = j + 1
                while kk < n and lines[kk].strip() != "":
                    kk += 1
                if kk - 1 >= j + 1:            # 存在文本行
                    num = int(s)
                    zh_idx = j + 1
                    ref = lines[kk - 1]
                    if mode != "endo" and kk - 1 == j + 1:
                        # 单文本行 cue：该行即参考行（无独立中文行），
                        # 跳过整块，防止把术语替换误写到参考/英文行上
                        i = kk
                        continue
                    old = lines[zh_idx]
                    if fix_en and mode == "bi":  # --fix-en：修正英文/参考行术语（仅双语模式）
                        for ti in range(j + 2, kk):
                            eold = out[ti]
                            enew = _replace_report(eold, enfix_pairs, enfix_chars, hits)
                            if enew != eold:
                                rows.append((num, eold, enew, eold))
                                out[ti] = enew
                        if kk - 1 > zh_idx:      # 上下文匹配/ERROR 翻译改用修正后参考行
                            ref = out[kk - 1]
                    if mode == "pgr" and pgr_override and str(num) in pgr_override:
                        # PGR 模式：侧车整行覆盖（校准后中文已是终稿，不再叠加术语表）
                        new = pgr_override[str(num)]
                        if new != old:
                            rows.append((num, old, new, ref))
                            out[zh_idx] = new
                    elif mode in ("ko", "wwoc", "react"):  # 韩语/综合游戏/音乐点评：统一首中文行术语（不动参考行）
                        new = _replace_report(old, term_pairs, term_chars, hits)
                        if new != old:
                            rows.append((num, old, new, ref))
                            out[zh_idx] = new
                    elif mode == "ja":          # 日语原声：JA_TERMS + JA_CONTEXT(日语行佐证) 统一首中文行
                        new = _replace_report(old, term_pairs, term_chars, hits)
                        for crx, wrong, right in _JA_CONTEXT_COMPILED:
                            if wrong in new and crx.search(ref):
                                new = new.replace(wrong, right)
                        if new != old:
                            rows.append((num, old, new, ref))
                            out[zh_idx] = new
                    elif mode == "jpe":         # 日语原声·终末地：JA_ENDFIELD_TERMS + 上下文佐证
                        new = _replace_report(old, term_pairs, term_chars, hits)
                        for crx, wrong, right in _JA_ENDFIELD_CONTEXT_COMPILED:
                            if wrong in new and crx.search(ref):
                                new = new.replace(wrong, right)
                        if new != old:
                            rows.append((num, old, new, ref))
                            out[zh_idx] = new
                    elif mode == "akko":        # 明日方舟韩语原声：AK_KO_TERMS + AK_KO_CONTEXT(韩语行佐证) 统一首中文行
                        new = _replace_report(old, term_pairs, term_chars, hits)
                        for crx, wrong, right in _AK_KO_CONTEXT_COMPILED:
                            if wrong in new and crx.search(ref):
                                new = new.replace(wrong, right)
                        if new != old:
                            rows.append((num, old, new, ref))
                            out[zh_idx] = new
                    elif mode in ("ak", "zho"):  # 明日方舟本体/中文行专属：统一首中文行
                        new = _replace_report(old, term_pairs, term_chars, hits)
                        if new != old:
                            rows.append((num, old, new, ref))
                            out[zh_idx] = new
                    elif mode == "endo":       # 终末地模式：ENDFIELD_TERMS 统一全部文本行
                        for ti in range(j + 1, kk):
                            lold = lines[ti]
                            new = _replace_report(lold, term_pairs, term_chars, hits)
                            if new != lold:
                                rows.append((num, lold, new, ref))
                                out[ti] = new
                    else:                      # 双语模式：统一每个 cue 的首中文行
                        new = _replace_report(old, term_pairs, term_chars, hits)
                        for crx, wrong, right in _CONTEXT_COMPILED:
                            if wrong in new and crx.search(ref):
                                new = new.replace(wrong, right)
                        # 负向排除（EXCLUDE_CONTEXT）：高歧义词被替换后，若参考行命中
                        # 排除正则（如 thank you/written tent 语境），回滚该替换并从命中统计移除
                        for wrong, (right, rxs) in _EXCLUDE_COMPILED.items():
                            if wrong in old and wrong not in new and any(rx.search(ref) for rx in rxs):
                                new = new.replace(right, wrong)
                                hits.pop(wrong, None)
                        new = _replace_report(new, word_pairs, word_chars, {})  # WORD_MAP 命中不计入统计
                        if new != old:
                            rows.append((num, old, new, ref))
                            out[zh_idx] = new
                    if layout_opt:             # 排版：首中文行 ≥14 字拆两行
                        laid = layout_line(out[zh_idx])
                        if "\n" in laid:
                            a, b = laid.split("\n", 1)
                            out[zh_idx] = a
                            inserts.append((zh_idx, b))
                i = kk
                continue
        i += 1

    for idx, text in sorted(inserts, reverse=True):
        out.insert(idx + 1, text)

    if out_path:
        body = "\n".join(out)
        if crlf:
            body = body.replace("\n", "\r\n")
        data = ("\ufeff" if bom else "") + body
        with open(out_path, "w", encoding="utf-8", newline="") as f:
            f.write(data)

    if report_path:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("# 字幕校准对照报告\n\n序号 | 原文中文(机翻) | 校准后中文 | 参考行\n")
            f.write("--- | --- | --- | ---\n")
            for num, old, new, ref in rows:
                f.write(f"`{num}` | {old} | **{new}** | {ref}\n")

    return rows, hits


def _cmd_extract(src, out):
    """extract：把双语 SRT 抽为 cue 表 num/中文/英文，中文/英文多行用 \\n 转义。"""
    raw = open(src, "rb").read()
    norm = (raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n"))
    lines = norm.split("\n")
    recs = []
    i, n = 0, len(lines)
    while i < n:
        s = lines[i].strip()
        if s.isdigit() and (i == 0 or lines[i - 1].strip() == ""):
            j = i + 1
            if j < n and "-->" in lines[j]:
                kk = j + 1
                while kk < n and lines[kk].strip() != "":
                    kk += 1
                texts = lines[j + 1:kk]
                if not texts:
                    i = kk; continue
                esc = lambda x: x.replace("\\", "\\\\").replace("\u0009", " ").replace("\n", "\\n")
                zh = "\\n".join(esc(t) for t in texts[:-1]) if len(texts) > 1 else esc(texts[0])
                en = esc(texts[-1])
                recs.append((s, zh, en))
                i = kk
                continue
        i += 1
    with open(out, "w", encoding="utf-8", newline="") as f:
        f.write("序号\t中文行\t英文行\n")
        for num, zh, en in recs:
            f.write(f"{num}\t{zh}\t{en}\n")
    print(f"cues={len(recs)} -> {out}")


def _cmd_split(cues, prefix, n, letters="ABCDEFGHIJKLMNOP"):
    """split：把 cues.tsv 切为 n 段（输入 seg_{X}.tsv + 输出空 calib_{X}.tsv），供并行校准。"""
    segs = min(n, len(letters))
    if n > len(letters):
        segs = n  # 允许超过字母表，用数字后缀
    rows = open(cues, encoding="utf-8").read().splitlines()
    header, data = rows[0], rows[1:]
    ntotal = len(data)
    size = (ntotal + segs - 1) // segs
    for k in range(segs):
        chunk = data[k * size:(k + 1) * size]
        tag = letters[k] if k < len(letters) else str(k + 1)
        with open(f"{prefix}seg_{tag}.tsv", "w", encoding="utf-8", newline="") as f:
            f.write(header + "\n")
            for r in chunk:
                f.write(r + "\n")
        with open(f"{prefix}calib_{tag}.tsv", "w", encoding="utf-8", newline="") as f:
            f.write("num\tnew_zh\n")
        first = chunk[0].split("\t")[0] if chunk else "-"
        last = chunk[-1].split("\t")[0] if chunk else "-"
        print(f"seg_{tag}.tsv: rows={len(chunk)} num=({first}..{last})")


def _load_calib_records(src):
    """加载校准表（单个文件或目录，含 seg_*/calib_* 字样）：鲁棒解析 序号<TAB>校准后中文。"""
    import glob
    new_zh = {}
    if os.path.isdir(src):
        files = []
        for pat in ("calib_*", "seg_*", "cal_*", "_corrected"):
            if pat == "_corrected":
                files += sorted(glob.glob(os.path.join(src, "*_corrected.tsv")))
            else:
                files += sorted(glob.glob(os.path.join(src, f"{pat}*.tsv")))
        files = [f for f in files if os.path.isfile(f)]
    elif "*" in src:
        files = sorted(glob.glob(src))
    else:
        files = [src] if os.path.exists(src) else []
    for p in files:
        for ln in open(p, encoding="utf-8-sig").read().splitlines():
            ln = ln.strip("\ufeff").rstrip("\r")
            m = re.match(r"(\d+)", ln)
            if not m:
                continue
            txt = ln[m.end():].lstrip("\t \u3000\u3000").strip()
            rest = ln[m.end():]
            if rest.count("\t") >= 2:   # seg_*三列原文段(序号\t原文\t参考行)不是校准表，跳过，
                continue                 # 防止目录合并时按文件名序在calib_*后加载、用机译原文反向覆盖人工校准
            if txt:
                new_zh[m.group(1)] = txt
    return new_zh


def _cmd_merge(src, calib_src, out, compare=None, side=None, apply_fix=False):
    """merge：读校准段回填重建 SRT（只替换中文内容行），严格保留序号/时间轴/参考行/换行/BOM。
    另可写出对照表(--compare)与侧车覆盖表(--side)。
    apply_fix=True 时对回填中文再套 MERGE_FIXES 跨段统一（历史 AK 项目 FIXES 沉淀）。"""
    def _norm_fix(s):
        if apply_fix:
            for a, b in MERGE_FIXES:
                s = s.replace(a, b)
        return s
    orig = _load_calib_records(calib_src)
    raw = open(src, "rb").read()
    bom = raw.startswith(b"\xef\xbb\xbf")
    crlf = b"\r\n" in raw
    norm = raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    lines = norm.split("\n")
    spans, timecodes, orig_zh = [], [], {}
    en_by_num = {}            # 序号->参考行：cue 编号不连续时对照表不再错行
    i, n = 0, len(lines)
    while i < n:
        s = lines[i].strip()
        if s.isdigit() and (i == 0 or lines[i - 1].strip() == ""):
            j = i + 1
            if j < n and "-->" in lines[j]:
                kk = j + 1
                while kk < n and lines[kk].strip() != "":
                    kk += 1
                texts = lines[j + 1:kk]
                if not texts:
                    i = kk; continue
                num = s
                timecodes.append(lines[j])
                en_by_num[num] = texts[-1]
                orig_zh[num] = "\n".join(texts[:-1])
                # (st,ed)=中文行区间 [j+1, kk-1)；单文本行 cue 无中文行（st==ed），
                # 回填会毁掉唯一参考行，重建时同样跳过不覆盖
                spans.append((j + 1, kk - 1, num, len(texts) >= 2))
                i = kk
                continue
        i += 1
    # 2026-09-05 重建式回填：旧实现 out_lines[st:ed]=[单行] 在多行中文 cue
    # （--layout 拆行/歌词片源）被覆盖成单行后，后续 cue 的行索引静默错位、
    # 串写到错误位置。按 cue 边界重建输出：单行场景与旧实现逐字节一致；
    # 校准文本自带 \n 时按多行展开，多行原文 cue 无校准也原样保留。
    out_lines, prev = [], 0
    for st, ed, num, has_zh in spans:
        out_lines.extend(lines[prev:st])
        if has_zh and num in orig:
            out_lines.extend(_norm_fix(orig[num]).split("\n"))
        else:
            out_lines.extend(lines[st:ed])
        prev = ed
    out_lines.extend(lines[prev:])
    body = "\n".join(out_lines)
    if crlf:
        body = body.replace("\n", "\r\n")
    with open(out, "w", encoding="utf-8", newline="") as f:
        f.write(("\ufeff" if bom else "") + body)
    print("校准条目:", len(orig), "| 已应用:", sum(1 for k in orig if k in orig_zh),
          "| 校准但原文件无此cue:", [k for k in sorted(orig, key=int) if k not in orig_zh])
    if compare:
        with open(compare, "w", encoding="utf-8", newline="") as f:
            f.write("序号\t原文中文(机翻)\t校准后中文\t英文行\n")
            for k in sorted(orig, key=int):
                f.write(f"{k}\t{orig_zh.get(k, '')}\t{orig[k]}\t{en_by_num.get(k, '')}\n")
        print("对照表:", compare)
    if side:
        with open(side, "w", encoding="utf-8", newline="") as f:
            f.write("num\tnew_zh\n")
            for k in sorted(orig, key=int):
                f.write(f"{k}\t{orig[k]}\n")
        print("侧车覆盖表:", side)
    print("写入:", out)


def _cmd_verify(src, out):
    """verify：校验两个 SRT cue数/序号/时间轴/英文行/换行/BOM 全一致，仅中文行变化。"""
    def parse(p):
        raw = open(p, "rb").read()
        crlf = b"\r\n" in raw; bom = raw.startswith(b"\xef\xbb\xbf")
        lines = raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n").split("\n")
        cues = []
        i, n = 0, len(lines)
        while i < n:
            s = lines[i].strip()
            if s.isdigit() and (i == 0 or lines[i - 1].strip() == ""):
                j = i + 1
                if j < n and "-->" in lines[j]:
                    kk = j + 1
                    while kk < n and lines[kk].strip() != "":
                        kk += 1
                    if kk - 1 >= j + 1:
                        cues.append((int(s), lines[j], lines[j + 1], lines[kk - 1]))
                    i = kk
                    continue
            i += 1
        return cues, crlf, bom
    s, scrlf, sbom = parse(src)
    o, ocrlf, obom = parse(out)
    print(f"src: {len(s)} cues, CRLF={scrlf}, BOM={sbom} | out: {len(o)} cues, CRLF={ocrlf}, BOM={obom}")
    assert len(s) == len(o), "cue count mismatch"
    assert scrlf == ocrlf, "CRLF mismatch"
    assert sbom == obom, "BOM mismatch"
    ts = e = z = 0
    for (n1, t1, z1, e1), (n2, t2, z2, e2) in zip(s, o):
        assert n1 == n2, f"num mismatch {n1}"
        ts += t1 != t2; e += e1 != e2; z += z1 != z2
    assert ts == 0, "TIMESTAMPS CHANGED!"
    assert e == 0, "ENGLISH LINES CHANGED!"
    print(f"timestamp diffs: {ts} | english diffs: {e} | chinese diffs: {z}")
    # 行宽体检（2026-09-10 规则）：每行 ≤ 32 汉字 / 64 英文字符，超标仅告警不改写
    content_bad, ref_bad = _collect_length_violations(out)
    if content_bad:
        print(f"⚠ 内容行超宽 {len(content_bad)} 处（>{MAX_LINE_ZH} 汉字 / >{MAX_LINE_EN} 英文字符，"
              f"建议加 --layout 拆分）：")
        for num, idx, t, w in content_bad[:20]:
            print(f"   #{num} 第{idx}行 宽{w:g}: {t[:30]}{'…' if len(t) > 30 else ''}")
        if len(content_bad) > 20:
            print(f"   ...（其余 {len(content_bad) - 20} 处略）")
    else:
        print(f"行宽 OK：内容行无超过 {MAX_LINE_ZH} 汉字 / {MAX_LINE_EN} 英文字符的行")
    if ref_bad:
        print(f"   注：另有 {len(ref_bad)} 行参考行超宽（原片语言，按契约不改，仅提示）")
    print("VERIFY OK：仅中文行变化，其它全部一致")


def _cmd_compare(src, out, tsv):
    """compare：比对两个 SRT 生成 错误vs正确 对照表（序号/原文中文/校准后中文/英文行）。"""
    def parse(p):
        lines = open(p, "rb").read().decode("utf-8-sig").replace("\r\n", "\n").split("\n")
        cues = []
        i, n = 0, len(lines)
        while i < n:
            s = lines[i].strip()
            if s.isdigit() and (i == 0 or lines[i - 1].strip() == ""):
                j = i + 1
                if j < n and "-->" in lines[j]:
                    kk = j + 1
                    while kk < n and lines[kk].strip() != "":
                        kk += 1
                    if kk - 1 >= j + 1:
                        cues.append((int(s), lines[j + 1], lines[kk - 1]))
                    i = kk
                    continue
            i += 1
        return cues
    sc, oc = parse(src), parse(out)
    assert len(sc) == len(oc)
    with open(tsv, "w", encoding="utf-8") as f:
        f.write("序号\t原文中文(机翻)\t校准后中文\t英文行\n")
        for (n1, z1, e1), (n2, z2, e2) in zip(sc, oc):
            if z1 != z2:
                f.write(f"{n1}\t{z1}\t{z2}\t{e1}\n")
    print("对照表:", tsv, "| 改动行数:", sum(1 for a, b in zip(sc, oc) if a[1] != b[1]))


def _cmd_scan(cues, min_cnt=2):
    """scan：扫描 cues 表英文列高频候选词（辅判定待校准专名/错词）。"""
    from collections import Counter
    rows = open(cues, encoding="utf-8").read().splitlines()
    ens = [ln.split("\t")[2] for ln in rows if len(ln.split("\t")) == 3]
    texts = " ".join(ens)
    words = re.findall(r"[A-Z][a-zA-Z'\-]+", texts)
    c = Counter(words)
    common = set("""I You We They He She It The A An And Or But Of To In On At For With From By
As Is Are Was Were Be Been Being This That These Those There Here Not No Yes So If Then Than
When Where Which Who Whom What How Why Do Does Did Done Doing Have Has Had Having Will Would
Can Could Should Shall May Might Must Okay Ok Yeah Yep Nope Uh Um Well Like Just Really
Actually Also Even Still Already Yet Only Too Very Much More Most Some Any All Both Each Every
Other Another Same Such Own Right Now One Two Three Four Five Six Seven Eight Nine Ten First
Second Third Last Next New Old Good Bad Great Big Small High Low Long Short Fast Slow Easy
Hard Free Play Player Game Mode Time Day Week Month Year Hour Minute Second People Someone
Everyone Everything Nothing Something Anything YouTube Ark Knights RA CC IS LMD E2 E1 AK OG
XP DPS VIP EZ GG""".split())
    for w, cnt in c.most_common(500):
        if w not in common and cnt >= min_cnt and len(w) > 2:
            print(f"{w}: {cnt}")


def _load_subfix_tsv(path):
    """加载逐 cue 子串修正表：num<TAB>old<TAB>new（old 为空串=整行覆盖，用于 ERROR 补译）。
    返回 {num: [(old, new), ...]}，同一 num 可多行（按文件顺序依次应用）。"""
    rules = {}
    for ln in open(path, encoding="utf-8-sig").read().splitlines():
        ln = ln.rstrip("\r")
        parts = ln.split("\t")
        if len(parts) < 3 or not parts[0].strip().isdigit():
            continue
        rules.setdefault(parts[0].strip(), []).append((parts[1], "\t".join(parts[2:])))
    return rules


def _cmd_subfix(src, fixtsv, out, compare=None, side=None):
    """subfix：按 num<TAB>old<TAB>new 逐 cue 修正“首中文行”，其余结构（序号/时间轴/
    空行/换行/BOM/参考行）一字不动。等价于原先各项目手写的 fix.py，统一沉淀为一个子命令。
    old 为空串 -> 整行覆盖（ERROR 补译）。未命中的规则会打印 [MISS] 以便自查。"""
    rules = _load_subfix_tsv(fixtsv)
    raw = open(src, "rb").read()
    bom = raw.startswith(b"\xef\xbb\xbf")
    crlf = b"\r\n" in raw
    lines = raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out_lines = list(lines)
    applied, miss, rows = 0, [], []
    i, n = 0, len(lines)
    while i < n:
        s = lines[i].strip()
        if s.isdigit() and (i == 0 or lines[i - 1].strip() == ""):
            j = i + 1
            if j < n and "-->" in lines[j]:
                kk = j + 1
                while kk < n and lines[kk].strip() != "":
                    kk += 1
                if kk - 1 >= j + 1 and kk - 1 > j + 1 and s in rules:   # 必须有中文行+参考行
                    zh_idx = j + 1
                    old_line = lines[zh_idx]
                    new_line = old_line
                    for old, new in rules[s]:
                        if old == "":
                            new_line = new
                        elif old in new_line:
                            new_line = new_line.replace(old, new)
                        else:
                            miss.append((s, old))
                    if new_line != old_line:
                        out_lines[zh_idx] = new_line
                        rows.append((s, old_line, new_line, lines[kk - 1]))
                        applied += 1
                i = kk
                continue
        i += 1
    body = "\n".join(out_lines)
    if crlf:
        body = body.replace("\n", "\r\n")
    with open(out, "w", encoding="utf-8", newline="") as f:
        f.write(("\ufeff" if bom else "") + body)
    total = sum(len(v) for v in rules.values())
    print(f"subfix：规则 {total} 条 / 命中 {applied} cue" + (f" / 未命中 {len(miss)}" if miss else ""))
    for num, old in miss:
        print(f"  [MISS] #{num}: {old!r}")
    if compare:
        with open(compare, "w", encoding="utf-8", newline="") as f:
            f.write("序号\t原文中文(机翻)\t校准后中文\t参考行\n")
            for num, o, nw, ref in rows:
                f.write(f"{num}\t{o}\t{nw}\t{ref}\n")
        print("对照表:", compare)
    if side:
        with open(side, "w", encoding="utf-8", newline="") as f:
            f.write("num\tnew_zh\n")
            for num, o, nw, ref in rows:
                f.write(f"{num}\t{nw}\n")
        print("侧车覆盖表:", side)
    print("写入:", out)


def _check_term_hazards(mapping):
    """检测术语表的“二次命中”隐患（2026-09-10 沉淀自终末地 ja_auto 项目）。

    `_replace_report` 是**按键长降序逐条 str.replace**，不是单遍扫描。因此若短键 k
    出现在另一条目 k2 的替换结果 value2 里，k2 先替换后，k 会再次命中刚生成的文本：
      {"阿尔达西尔":"阿达希尔", "达希尔":"阿达希尔"} -> 阿达希尔 再被 达希尔 命中 -> 阿阿达希尔
      {"明日方舟末地":"明日方舟：终末地", "末地":"终末地"}   -> 终末地 再被 末地 命中 -> 终终末地
    有意为之的级联（如 金阁->金戈 再 金戈->今州）也会被列出，需人工确认。
    返回 [(短键, 长键, 长键的替换结果, 短键的替换结果), ...]。"""
    bad, seen = [], set()
    pairs = sorted(mapping.items(), key=lambda kv: len(kv[0]), reverse=True)
    for i, (k, vk) in enumerate(pairs):
        if vk == k:                    # 恒等键不参与
            continue
        for k2, v2 in pairs[:i]:       # 只有“先处理”的条目才会留下可被二次命中的结果
            if v2 != k2 and k in v2 and (k, k2) not in seen:
                seen.add((k, k2))
                bad.append((k, k2, v2, vk))
    return bad


def _cmd_terms_check(names):
    """terms-check：列出（指定）术语表的二次命中隐患，供新增对照后自查。"""
    tables = {n: g for n, g in globals().items()
              if n.endswith("TERMS") and isinstance(g, dict) and g}
    todo = [n for n in (names or tables) if n in tables]
    if names:
        unknown = [n for n in names if n not in tables]
        if unknown:
            print("未知表:", unknown, "| 可选:", sorted(tables)); return
    total = 0
    for n in todo:
        bad = _check_term_hazards(tables[n])
        if bad:
            total += len(bad)
            print(f"⚠ {n}: {len(bad)} 处隐患")
            for k, k2, v2, vk in bad:
                print(f"   短键 {k!r} 会命中 {k2!r} 的结果 {v2!r}（{k!r}->{vk!r}）")
        else:
            print(f"✓ {n}: 无二次命中隐患")
    print(f"合计 {len(todo)} 张表，{total} 处隐患")


def main_argv():
    argv = sys.argv[1:]
    if argv and not argv[0].startswith("-"):
        sub = argv[0]
        if sub in ("extract", "split", "merge", "verify", "compare", "scan", "lint",
                   "length", "linelen", "lencheck",
                   "subfix", "terms-check", "termscheck", "terms"):
            _dispatch_subcommand(sub, argv[1:])
            return

    src = None
    out_path = report_path = None
    mode = "bi"
    layout_opt = False
    fix_en = False

    if argv and not argv[0].startswith("-"):
        src = argv[0]
    args = argv[1:] if (argv and not argv[0].startswith("-")) else argv
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--out" and i + 1 < len(args):
            out_path = args[i + 1]; i += 2
        elif a == "--report" and i + 1 < len(args):
            report_path = args[i + 1]; i += 2
        elif a == "--ko":
            mode = "ko"; i += 1
        elif a == "--ja":
            mode = "ja"; i += 1
        elif a == "--jpe":
            mode = "jpe"; i += 1
        elif a == "--wwoc":
            mode = "wwoc"; i += 1
        elif a == "--ak":
            mode = "ak"; i += 1
        elif a == "--akko":
            mode = "akko"; i += 1
        elif a == "--zho":
            mode = "zho"; i += 1
        elif a == "--endo":
            mode = "endo"; i += 1
        elif a == "--pgr":
            mode = "pgr"; i += 1
        elif a == "--react":
            mode = "react"; i += 1
        elif a == "--layout":
            layout_opt = True; i += 1
        elif a == "--fix-en":
            fix_en = True; i += 1
        elif a == "--mode" and i + 1 < len(args):
            m = args[i + 1].lower()
            mode = "ja" if m in ("ja", "japanese") else ("ko" if m in ("ko", "korean") else ("ak" if m in ("ak", "arknights") else ("zho" if m in ("zho", "zhonly", "zh_only") else ("endo" if m in ("endo", "endfield") else "bi"))))
            i += 2
        else:
            i += 1

    info = {"ko": KO_INFO, "ak": AK_INFO, "endo": ENDO_INFO, "pgr": PGR_INFO, "zho": ZHO_INFO, "wwoc": WWOC_INFO, "akko": AK_KO_INFO}.get(mode)
    if src is None and info:
        src = info["src"]                       # 一键重跑内置片源
        if out_path is None:
            out_path = info["dst"]
    if src is None:
        print(__doc__)
        return

    pgr_override = _load_override_tsv(PGR_OVERRIDES_SRC) if mode == "pgr" else None
    rows, hits = process(src, out_path, report_path, mode=mode, layout_opt=layout_opt,
                         fix_en=fix_en, pgr_override=pgr_override)
    names = {"bi": "中英双语 (BILINGUAL_TERMS + CONTEXT_MAP + WORD_MAP)",
             "ko": "韩语原声 (KO_TERMS)",
             "ja": "日语原声 (JA_TERMS + JA_CONTEXT)",
             "jpe": "日语原声·终末地 (JA_ENDFIELD_TERMS + JA_ENDFIELD_CONTEXT)",
             "wwoc": "综合手游OST世界杯 (WWOC_TERMS)",
             "ak": "明日方舟本体 (AK_TERMS)",
             "akko": "明日方舟韩语原声 (AK_KO_TERMS + AK_KO_CONTEXT)",
             "zho": "中文行专属 (ZH_ONLY_TERMS)",
             "endo": "终末地 (ENDFIELD_TERMS)",
             "pgr": "战双帕弥什 (PGR 侧车整行覆盖, {} 条)".format(len(pgr_override) if pgr_override else 0),
             "react": "音乐/演唱点评 (REACT_TERMS)"}
    extra = (" + 双行排版" if layout_opt else "") \
          + (" + 英文行修正(--fix-en)" if fix_en else "")
    print("模式:", names[mode] + extra)
    print("存在术语表错误形式的块:", hits if hits else "无（已统一）")
    if out_path:
        print(f"已写入：{out_path}（{len(rows)} 处文本改动，序号/时间轴/空行/换行/BOM 保持原样）")
    if report_path:
        print(f"报告：{report_path}（{len(rows)} 处文本改动）")


def _collect_length_violations(path):
    """扫描 SRT 每条 cue 的文本行，返回 (内容行超宽, 参考行超宽) 两个列表。

    行宽判据见第 4 节：> 32 汉字 / > 64 英文字符（MAX_LINE_WIDTH=32）即超标。
    每条目为 (cue号, 行序, 文本, 宽度)。双语片源的**最后一个文本行**是参考行
    （原片语言，按契约一字不动），单独归入"参考行"桶仅作提示，与内容行分开统计。"""
    raw = open(path, "rb").read()
    lines = raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    content, refs = [], []
    i, n = 0, len(lines)
    while i < n:
        s = lines[i].strip()
        if s.isdigit() and (i == 0 or lines[i - 1].strip() == ""):
            j = i + 1
            if j < n and "-->" in lines[j]:
                kk = j + 1
                while kk < n and lines[kk].strip() != "":
                    kk += 1
                texts = lines[j + 1:kk]
                for ti, t in enumerate(texts):
                    if not is_line_too_long(t):
                        continue
                    item = (int(s), ti + 1, t, line_width(t))
                    if len(texts) >= 2 and ti == len(texts) - 1:
                        refs.append(item)      # 双语片源末行 = 参考行
                    else:
                        content.append(item)
                i = kk
                continue
        i += 1
    return content, refs


def _cmd_length(paths, include_ref=False):
    """length：只读体检 SRT 每行字幕长度（>32 汉字 / >64 英文字符 即超标）。

    用法: length <a.srt> [b.srt ...] [--all]
    默认只查内容行（中文行）；--all 连参考行（原片语言）一起列出。
    存在超标行时退出码为 1，便于流水线门禁；不改写任何文件。"""
    total = 0
    for p in paths:
        if not os.path.isfile(p):
            print(f"✗ 文件不存在: {p}")
            total += 1
            continue
        content, refs = _collect_length_violations(p)
        shown = content + refs if include_ref else content
        total += len(shown)
        name = os.path.basename(p)
        if shown:
            print(f"⚠ {name}: {len(shown)} 行超宽（> {MAX_LINE_ZH} 汉字 / {MAX_LINE_EN} 英文字符）")
            for num, idx, t, w in shown[:40]:
                print(f"    #{num} 第{idx}行 宽{w:g}: {t[:40]}{'…' if len(t) > 40 else ''}")
            if len(shown) > 40:
                print(f"    ...（其余 {len(shown) - 40} 行略）")
        else:
            print(f"✓ {name}: 内容行全部在 {MAX_LINE_ZH} 汉字 / {MAX_LINE_EN} 英文字符以内")
        if refs and not include_ref:
            print(f"    注：另有 {len(refs)} 行参考行超宽（原片语言，本脚本不改；--all 可查看）")
    print(f"合计 {len(paths)} 个文件，{total} 行超宽")
    return 1 if total else 0


def _cmd_lint(cues, calib_src):
    """lint：校验校准表相对 cue 表的完整性与文本质量。
    检查：重复序号 / 缺号（cue表有序号而校准表漏写）/ 越界序号 / 空文案 /
    中文文案中的意外拉丁-变音残留（白名单外的英文单词）/
    超宽行（>32 汉字 或 >64 英文字符，2026-09-10 规则，按 \\n 拆分后逐行判定）。
    2026-09-05 沉淀自 Gloomwald's Rage 二次校准：分段书写 calib_*.tsv 时
    曾出现序号重复（127 写两遍）与外文残留（undeniable/càng/chord shape）。"""
    cue_nums = []
    for ln in open(cues, encoding="utf-8").read().splitlines()[1:]:
        m = re.match(r"(\d+)\t", ln)
        if m:
            cue_nums.append(int(m.group(1)))
    cue_set = set(cue_nums)
    orig = _load_calib_records(calib_src)
    problems = []
    seen = {}
    # 重复检测需重读原始行（_load_calib_records 已合并去重，这里按文件逐行统计）
    import glob as _glob
    if os.path.isdir(calib_src):
        files = sorted(_glob.glob(os.path.join(calib_src, "calib_*.tsv")))
    elif "*" in calib_src:
        files = sorted(_glob.glob(calib_src))
    else:
        files = [calib_src]
    for p in files:
        for ln in open(p, encoding="utf-8-sig").read().splitlines():
            m = re.match(r"(\d+)\t", ln.lstrip("\ufeff"))
            if not m:
                continue
            n = m.group(1)
            seen[n] = seen.get(n, 0) + 1
    for n, cnt in sorted(seen.items(), key=lambda kv: int(kv[0])):
        if cnt > 1:
            problems.append(f"重复序号 {n}（出现 {cnt} 次）")
        if int(n) not in cue_set:
            problems.append(f"越界序号 {n}（cue 表无此条）")
    missing = sorted(cue_set - {int(k) for k in seen})
    if missing:
        problems.append(f"缺号 {len(missing)} 个: {missing[:20]}{'...' if len(missing) > 20 else ''}")
    # 文本质量：空文案 / 拉丁残留（音名 A-G、变音记号与常用保留词白名单）
    keep_words = {"music", "sus", "add", "flat", "sharp", "boss", "alex", "oreos",
                  "ooh", "oh", "ok", "pvp", "ost", "ost", "ost", "ost", "ost"}
    single_notes = set("abcdefg")          # 音名 A-G 允许
    for k in sorted(orig, key=int):
        txt = orig[k]
        if not txt.strip():
            problems.append(f"#{k} 空文案")
        for w in re.findall(r"[A-Za-zÀ-ɏ]+", txt):
            lw = w.lower()
            if lw in keep_words:
                continue
            if len(w) == 1 and lw in single_notes:
                continue
            problems.append(f"#{k} 拉丁残留: {w}（{txt[:24]}）")
        # 行宽（2026-09-10 规则）：\n 拆分后每行须 ≤32 汉字 / ≤64 英文字符
        for seg in txt.replace("\\n", "\n").split("\n"):
            if is_line_too_long(seg):
                problems.append(f"#{k} 超宽行 宽{line_width(seg):g}: "
                                f"{seg[:24]}{'…' if len(seg) > 24 else ''}")
    if problems:
        print(f"LINT {len(problems)} 处问题:")
        for p in problems:
            print(" -", p)
    else:
        print(f"LINT OK：{len(cue_nums)} cue 全覆盖，无重复/越界/空文案/拉丁残留/超宽行")


def _dispatch_subcommand(sub, args):
    """解析流式子命令参数并执行。"""
    pos = [a for a in args if not a.startswith("-")]
    opts = {}
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--n" and i + 1 < len(args):
            opts["n"] = int(args[i + 1]); i += 2
        elif a == "--min" and i + 1 < len(args):
            opts["min"] = int(args[i + 1]); i += 2
        elif a == "--fix":
            opts["fix"] = True; i += 1
        elif a == "--all":
            opts["all"] = True; i += 1
        elif a in ("--out", "--compare", "--side", "--letters") and i + 1 < len(args):
            opts[a[2:]] = args[i + 1]; i += 2
        else:
            i += 1
    if sub == "extract":
        if len(pos) < 2:
            print("用法: extract <src.srt> <cues.tsv>"); return
        _cmd_extract(pos[0], pos[1])
    elif sub == "split":
        if len(pos) < 2:
            print("用法: split <cues.tsv> <outprefix> --n <N>"); return
        _cmd_split(pos[0], pos[1], opts.get("n", 6))
    elif sub == "merge":
        if len(pos) < 2 or "out" not in opts:
            print("用法: merge <src.srt> <校准表|目录> --out out.srt [--compare tsv] [--side tsv] [--fix]"); return
        _cmd_merge(pos[0], pos[1], opts["out"], opts.get("compare"), opts.get("side"), opts.get("fix", False))
    elif sub == "verify":
        if len(pos) < 2:
            print("用法: verify <src.srt> <out.srt>"); return
        _cmd_verify(pos[0], pos[1])
    elif sub == "compare":
        if len(pos) < 3:
            print("用法: compare <src.srt> <out.srt> <对照.tsv>"); return
        _cmd_compare(pos[0], pos[1], pos[2])
    elif sub == "scan":
        if not pos:
            print("用法: scan <cues.tsv> [--min 2]"); return
        _cmd_scan(pos[0], opts.get("min", 2))
    elif sub == "lint":
        if len(pos) < 2:
            print("用法: lint <cues.tsv> <calib目录|calib_*.tsv>"); return
        _cmd_lint(pos[0], pos[1])
    elif sub == "subfix":
        if len(pos) < 2 or "out" not in opts:
            print("用法: subfix <src.srt> <fix.tsv> --out out.srt [--compare tsv] [--side tsv]"); return
        _cmd_subfix(pos[0], pos[1], opts["out"], opts.get("compare"), opts.get("side"))
    elif sub in ("length", "linelen", "lencheck"):
        if not pos:
            print("用法: length <a.srt> [b.srt ...] [--all]"); return
        sys.exit(_cmd_length(pos, opts.get("all", False)))
    elif sub in ("terms-check", "termscheck", "terms"):
        _cmd_terms_check(pos)


if __name__ == "__main__":
    main_argv()
