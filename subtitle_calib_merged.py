# -*- coding: utf-8 -*-
"""字幕校准统一脚本（唯一入口，可复用，每次校准任务优先调用本脚本）

本文件是工作区全部历史校准脚本的统一沉淀（双语 calib_rules、韩语
calib_input_ko_out、终末地 calibrate_srt 已全部并入；
2026-08-29 再并入 srt_calibrator.py / fix_srt.py / fix_all.py / fix_simple.py
的通用术语表与 ERROR 行翻译表，以及 7 月 WW 演唱会脚本的通用专名），
其它脚本已删除，勿再另建平行脚本，新对照直接追加进本文件各表。
2026-08-29 起删除逐句台词改写（原 OVERRIDES / ENDFIELD_OVERRIDES / ERROR 行翻译），台词文案保留原始机翻，本脚本只做名词级校准。
2026-09-01 算法优化（输出与原实现逐字节一致）：术语表预编译为 长键序+键字符集（行级预筛、
命中统计与替换单遍完成）、CONTEXT_MAP 正则预编译。

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
  ENTITIES                对象级知识层（2026-09-11 起新对照一律以 Entity 追加于此，
                          注册时自动投影进上述扁平表；见文件第 6 节）
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
       [--ja|--jpe|--ko|--endo|--ak|--zho|--pgr] [--fix-en]

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
  --pgren  战双帕弥什·英文原声模式（中英双语片源：中文机翻 + 英文参考行）：PGR_EN_TERMS
           统一首中文行专名/术语（惩罚灰乌鸦->战双帕弥什、Kumi->狂三、Adelite->阿德莱德、
           编码->涂装 等），英文参考行一字不动。（第 3.3 节，2026-09-11）
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
  python subtitle_calib_merged.py terms-check [表名...]                     # 术语表二次命中隐患自查
  python subtitle_calib_merged.py kb-export [--json] [--out 路径]           # 导出对象级知识库（MD/JSON，投喂用）
  python subtitle_calib_merged.py kb-lookup <词>                            # 按任意形态反查实体全部知识
  python subtitle_calib_merged.py kb-lint                                   # 对象级体检（跨实体冲突/级联/冗余）

C. 学习系统（规则引擎 + 从人工修正中学习，自我迭代闭环，2026-09-11）:
  python subtitle_calib_merged.py learn <原始.srt> <人工校准.srt> [--mode bi] [--kb 库.json]
        # 投喂配对：difflib 挖 错形->正形 候选，记录频次/证据cue/参考行词元/反例。
        # count>=2 且无反例 -> confirmed，之后校准该模式时自动注入生效；
        # confirmed 后出现反例 -> 自动降级并生成上下文佐证正则建议。
  python subtitle_calib_merged.py learned-show [--mode bi] [--kb 库.json]   # 查看候选/状态/建议
  python subtitle_calib_merged.py learned-promote [--kb 库.json]            # confirmed 导出 Entity 桩代码，
        # 人工审阅后粘贴进第 6 节 ENTITIES = 学习成果固化为对象级知识
  python subtitle_calib_merged.py learned-reject <错形> [--mode bi]         # 人工否决候选（永不应用）
  运行时：校准入口加 --kb 库.json 显式加载；cwd 存在 subtitle_learned_kb.json 时自动加载。
        # terms-check：检测“短键会命中另一条目替换结果”的二次替换隐患（长键降序 str.replace
        #   的固有陷阱，2026-09-10 终末地 ja_auto 项目沉淀：达希尔->阿阿达希尔、末地->终终末地）。
        # subfix：fix.tsv 每行 num<TAB>old<TAB>new；old 为空串=整行覆盖（ERROR 补译）。
        #   等价于原先各项目手写的 fix.py，今后逐条精修统一用本子命令，勿再另建 fix.py。
"""
import io
import os
import re
import sys
import codecs
import unicodedata


def _decode_any(raw, encodings=("utf-8", "gb18030", "big5", "shift_jis", "latin-1")):
    """把字幕文件的原始字节稳健解码为 str，同时兼容 UTF-8 / GBK(GB18030) / ASCII。

    先识别 BOM（UTF-8/UTF-16/UTF-32），无 BOM 则按 UTF-8（ASCII 也在此命中）→
    GB18030（GBK 超集，兼容老式中文 Windows 与字幕工具导出的 GBK 字幕）→ Big5
    顺序尝试，最后用 replace 兜底，绝不因编码不同而 UnicodeDecodeError 崩溃。
    注意：调用方仍按原始字节判断 BOM/CRLF，本函数只负责得到处理用的文本；GBK
    输入经处理后统一以 UTF-8 写出（换行/BOM 策略由各模式自行决定）。
    """
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    for bom, enc in ((codecs.BOM_UTF8, "utf-8-sig"),
                     (codecs.BOM_UTF32_LE, "utf-32"),
                     (codecs.BOM_UTF32_BE, "utf-32"),
                     (codecs.BOM_UTF16_LE, "utf-16"),
                     (codecs.BOM_UTF16_BE, "utf-16")):
        if raw.startswith(bom):
            try:
                return raw.decode(enc, errors="replace")
            except (UnicodeDecodeError, LookupError):
                break
    for enc in encodings:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")

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
    "逆雨": "溯洄雨", "风化波浪": "鸣潮", "风化浪潮": "鸣潮", "风化浪": "鸣潮", "星火学院": "星炬学院",
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
    # 琳奈(Linny/Lenna，星炬学院预科班学生)：ASR 变体 Lenny/Linny/Lenise；中文机翻"莱妮丝/林尼/莱尼"
    "Linny": "琳奈", "Lenny": "琳奈", "Lenise": "琳奈", "林尼": "琳奈", "莱尼": "琳奈", "莱妮丝": "琳奈",
    # 莫宁(Mornye，深空联合研究院学者/星炬学院教授)：ASR 变体 Mouier/Mor
    "Mouier": "莫宁", "Mornye": "莫宁", "莫尔教授": "莫宁教授", "穆耶教授": "莫宁教授",
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
    # 注：不再保留 (r"\bWua\b", "Wua", "鸣潮") —— wrong 与 right 同为"鸣潮"是空操作；
    #     而 "Wua" 本身已由 BILINGUAL_TERMS 无条件覆盖，该条永不可能生效（kb-lint 条件冗余）。
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
    # --- 2026-09-11 NIKKE Player Reacts to Typhoeus Operator Story & Combat Demo 沉淀 ---
    # 终末地官方英文名 Typhoeus（中文行常残留英文/ASR听成 Typhon）；
    # 注意：明日方舟本体同角色叫"提丰"(Typhon)，在 AK_TERMS 中；终末地"再旅者"形态官方名=提弗洛斯。
    "Typhon": "提弗洛斯", "Typhoeus": "提弗洛斯",
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
    # 2026-09-11 NIKKE Player Reacts to Typhoeus 沉淀：operator story 机翻"操作员故事"。
    # 裸键"操作员"是通用中文词（机器操作员）不进表，只收带"故事"的长键避免误伤。
    "操作员故事": "干员故事",
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
    # --- 2026-09-11 沉淀：《NIKKE Player Reacts to Typhoeus Operator Story & Combat Demo》
    #     注意：此片实为终末地(Endfield) reaction，应用 --endo 模式；此处仅沉淀明日方舟本体术语。
    #     提丰(Typhon)=明日方舟本体六星狙击；终末地"再旅者"形态官方名=提弗洛斯(Typhoeus)，见 ENDFIELD_TERMS。
    #     "操作员"为 operator 直译，明日方舟本体语境统一为"干员"（仅 --ak 模式；终末地侧用长键"操作员故事"防误伤）。
    "Typhon": "提丰",
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
# 6. 对象级知识层（Entity Knowledge Base，2026-09-11）
#
#    动机：扁平表时代，一个"对象"（如 漂泊者）的知识散落在几十条
#    互无关联的 错形->正确 键里；它的官方 EN/JA/KO 名、适用片源模式、
#    哪些变体需要参考行佐证、哪些语境要负向回滚，只存在于注释中，
#    机器不可读、投喂给 AI 校准时也无法整体携带。
#
#    本层把知识单元从"字符串对"提升为"实体对象"：
#      Entity(canonical="漂泊者", en="Rover", ja="漂泊者", ko="방랑자",
#             category="角色", modes=("bi", "ja"),
#             variants=(...),            # 无条件变体：ASR/机翻错形，出现即改
#             ctx=((r"\brover\b", "漫游者"), ...),  # 条件变体：参考行佐证才改
#             exclude=(r"\bLand Rover\b", ...),     # 负向排除：参考行命中则回滚
#             note="...")
#
#    工作机制（对校准引擎零侵入、行为与扁平表逐字节一致）：
#      import 时 _register_entities() 把 ENTITIES 投影进既有扁平表
#      （variants->*_TERMS / ctx->*_CONTEXT / exclude->EXCLUDE_CONTEXT），
#      并重建各正则缓存；process() 主路径一字未改。
#      冲突即报错：实体变体与扁平表既有键映射到不同目标时直接 SystemExit，
#      防止新旧两套知识静默打架。
#
#    维护约定（自本层起）：
#      · 新校准沉淀一律追加为 ENTITIES 里的 Entity，不再直接改扁平表；
#      · 旧扁平表保持冻结（历史资产，零回归），kb-export 会把它们与
#        ENTITIES 折叠成统一的对象级视图；
#      · 新增 Entity 后跑 `kb-lint` 自查（变体冲突/级联/模式错放），
#        再跑 `terms-check` 查二次命中。
#
#    子命令：
#      kb-export [--json] [--out 路径]   导出完整对象级知识库（默认 MD，
#                                        扁平表按 canonical 折叠 + ENTITIES
#                                        元数据合并；即"投喂用"知识文件）
#      kb-lookup <词>                    按任意形态（中文名/EN/JA/KO/变体）
#                                        反查实体，列出它的全部知识
#      kb-lint                           对象级体检：跨实体变体冲突、
#                                        变体⊂他实体官方名（同模式级联）、
#                                        条件变体与无条件变体重复、
#                                        ENTITIES 元数据完整性
# =============================================================

# 模式 -> 无条件变体表 / 条件变体表（实体注册时的投影目标）
_MODE_TERM_TABLE = {
    "bi": "BILINGUAL_TERMS", "ja": "JA_TERMS", "jpe": "JA_ENDFIELD_TERMS",
    "ko": "KO_TERMS", "wwoc": "WWOC_TERMS", "endo": "ENDFIELD_TERMS",
    "ak": "AK_TERMS", "akko": "AK_KO_TERMS", "zho": "ZH_ONLY_TERMS",
    "pgren": "PGR_EN_TERMS", "react": "REACT_TERMS",
}
_MODE_CTX_TABLE = {
    "bi": "CONTEXT_MAP", "ja": "JA_CONTEXT", "jpe": "JA_ENDFIELD_CONTEXT",
    "akko": "AK_KO_CONTEXT",
}
_MODE_NAMES = {
    "bi": "中英双语", "ja": "日语原声·鸣潮", "jpe": "日语原声·终末地",
    "ko": "韩语原声·鸣潮", "wwoc": "综合手游OST", "endo": "终末地",
    "ak": "明日方舟", "akko": "明日方舟韩语", "zho": "中文行专属",
    "pgren": "战双英文原声", "react": "音乐点评", "fix-en": "英文参考行修正",
}


class Entity:
    """对象级知识单元：一个角色/地点/势力/术语的全部校准知识。

    canonical  官方中文名（替换目标，唯一标识）
    modes      适用片源模式（bi/ja/jpe/ko/ak/akko/endo/zho/pgren/wwoc/react）
    en/ja/ko   官方外文原名（知识属性与投喂元数据，不直接参与替换）
    category   角色/地点/势力/术语/作品/主播/乐理…（对象级检索用）
    variants   无条件变体（ASR/机翻错形，出现即改 -> canonical）
    ctx        条件变体 ((参考行正则, 错形), ...)，佐证命中才把 错形->canonical
    exclude    负向排除正则（仅双语模式）：替换后参考行命中则回滚
    note       来源/依据/戒律（官方文本出处、易混对象提醒）
    subst      子串安全声明（对象级新增，2026-09-12）：
               ((被包含的键, 兜底正则, 兜底目标), ...) —— 声明"我的 canonical 里
               含另一个实体的变体键，但已用 CONTEXT_MAP 兜底规则救回"。
               kb-lint 读到本声明后不再把该级联报为问题，是"已知边界"的机器可读化。
    multiplex  模式内多义声明（对象级新增，2026-09-12）：
               ((错形, 本实体的模式, 另一 canonical), ...) —— 声明"该错形在
               我负责的模式里归另一实体，属刻意分派，非变体冲突"。
               典型：英文 Typhon 在 endo=提弗洛斯 / ak=提丰，同一串在两个
               模式各有所指；本声明让 kb-lint 区分"设计如此"与"真冲突"。
    """ 

    def __init__(self, canonical, modes=("bi",), en="", ja="", ko="",
                 category="", variants=(), ctx=(), exclude=(), note="",
                 subst=(), multiplex=()):
        self.canonical = canonical
        self.modes = tuple(modes)
        self.en, self.ja, self.ko = en, ja, ko
        self.category = category
        self.variants = tuple(variants)
        self.ctx = tuple(ctx)
        self.exclude = tuple(exclude)
        self.note = note
        self.subst = tuple(subst)
        self.multiplex = tuple(multiplex)

    def __repr__(self):
        return f"Entity({self.canonical!r}, modes={self.modes!r}, variants={len(self.variants)})"


# --- 实体注册表（新沉淀追加于此）---
# 示范条目：变体已存在于扁平表（注册为幂等 no-op），en/ja/ko/category/note
# 是本层新增的对象级元数据。实体覆盖的既有键会在 kb-export 视图中带上这些属性。
ENTITIES = [
    Entity("漂泊者", modes=("bi",), en="Rover", ja="漂泊者", ko="방랑자",
           category="角色",
           variants=("罗弗", "罗孚", "罗浮", "路虎", "漫游车",
                     "Rover", "Ruva", "Ruver", "鲁瓦", "鲁弗", "Wover", "沃弗"),
           ctx=((r"\brover\b", "漫游者"),),
           note="鸣潮主角。'鲁瓦'长键须先于'鲁瓦扬->罗伊'(罗伊古文明)处理，防误伤；"
                "主播昵称'弗罗弗'(Frover)由 CONTEXT_MAP 兜底，防'罗弗'键子串误伤。"),
    Entity("心月狐", modes=("bi",), en="Sheen / Hsin", ja="シン",
           category="角色/岁主",
           variants=("Sheen", "月狐希恩", "希恩", "谢恩"),
           ctx=((r"\bSheen\b", "辛"), (r"\bSheen\b", "光泽"),
                (r"\bShin\b", "申"), (r"\bShin\b", "辛"), (r"\bShin\b", "胫"),
                (r"\bShane\b", "肖恩")),
           note="月狐岁主，官方全名 心月狐；独立指代用全名。日语片'シ/シン様'归 心"
                "（见 JA_TERMS），3.6 片'聖/聖書'=清宵(セイショウ)非心，勿混。"),
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
           note="星炬学院学生。昵称 Denny/Dennia 机翻'丹尼/丹尼娅'亦归此；"
                "Daniela=丹妮拉 是另一人，勿收。"),
    Entity("残星会会长", modes=("bi",), en="Grand Architect",
           category="势力/角色",
           note="残星会(Fractsidus)首领。'伟大建筑师/伟大的建筑师/盛大建筑师'必须"
                "长键先行，否则被'大建筑师'(4字)键咬成'伟残星会会长'。"),
    # --- 2026-09-12 补录：把 kb-lint 报出的两处"已知边界"对象化 ---
    Entity("弗罗弗", modes=("bi",), en="Frover",
           category="主播/昵称",
           subst=(("罗弗", r"\bFrover\b", "弗罗弗"),),
           note="鸣潮主播昵称。canonical 内含漂泊者变体'罗弗'子串：若无兜底，"
                "替换到'弗漂泊者'后会被'罗弗'键二次咬合。已用 CONTEXT_MAP "
                "/\\bFrover\\b/ 佐证规则还原为'弗罗弗'（自动救回，不再人工）。"
                "subst 声明把该边界机器可读化，kb-lint 据此不再报警。"),
    Entity("提弗洛斯", modes=("endo",), en="Typhoeus",
           category="角色",
           variants=("Typhon", "Typhoeus"),
           multiplex=(("Typhon", "endo", "提丰"),),
           note="终末地'再旅者'形态官方名=提弗洛斯(英文 Typhoeus)。"
                "明日方舟本体同角色叫'提丰'(Typhon)，在 AK_TERMS 中（--ak 模式）。"
                "英文 'Typhon' 在两模式下的不同归属是合法的模式内多义："
                "endo 片源里 Typhoeus/Typhon 一律指终末地形态 提弗洛斯。"),
    Entity("提丰", modes=("ak", "endo"), en="Typhon",
           category="角色",
           variants=("T-Phone", "T-phone"),
           multiplex=(("Typhon", "ak", "提弗洛斯"),),
           note="明日方舟本体六星狙击（--ak）。终末地韩语片源里 티폰 的机翻残留"
                "T-Phone/T-phone 亦归此（故 modes 含 endo）。戒律：英文 'Typhon' "
                "在 endo 模式归 提弗洛斯，只有韩语 ASR 残留的 T-Phone 走本实体，"
                "两者错形不重叠、无冲突。"),
]


def _register_entities(entities=ENTITIES):
    """把 ENTITIES 投影进扁平表，并重建正则缓存（import 时执行一次）。

    幂等：变体键已存在且目标一致 -> 跳过；目标不一致 -> 报错（新旧知识冲突）。
    """
    g = globals()
    for e in entities:
        for m in e.modes:
            tname = _MODE_TERM_TABLE.get(m)
            if tname and e.variants:
                tbl = g[tname]
                for v in e.variants:
                    if v in tbl and tbl[v] != e.canonical:
                        raise SystemExit(
                            f"ENTITIES 注册冲突：变体 {v!r} 在 {tname} 已映射 "
                            f"{tbl[v]!r}，实体要求 {e.canonical!r}")
                    tbl.setdefault(v, e.canonical)
            cname = _MODE_CTX_TABLE.get(m)
            if cname and e.ctx:
                lst = g[cname]
                for rx, wrong in e.ctx:
                    if not any(r == rx and w == wrong and rt == e.canonical
                               for r, w, rt in lst):
                        lst.append((rx, wrong, e.canonical))
        if e.exclude:
            exc = g["EXCLUDE_CONTEXT"]
            for v in e.variants:
                if v in exc:
                    right, rxs = exc[v]
                    exc[v] = (right, tuple(rxs) + tuple(
                        r for r in e.exclude if r not in rxs))
                else:
                    exc[v] = (e.canonical, tuple(e.exclude))


def _rebuild_context_caches():
    """实体注册可能追加 CONTEXT/EXCLUDE 条目，重建各预编译缓存。"""
    global _CONTEXT_COMPILED, _EXCLUDE_COMPILED, _JA_CONTEXT_COMPILED
    global _JA_ENDFIELD_CONTEXT_COMPILED, _AK_KO_CONTEXT_COMPILED
    _CONTEXT_COMPILED = [(re.compile(rx, re.I), wrong, right)
                         for rx, wrong, right in CONTEXT_MAP if wrong and right]
    _EXCLUDE_COMPILED = {w: (right, [re.compile(rx, re.I) for rx in rxs])
                         for w, (right, rxs) in EXCLUDE_CONTEXT.items()}
    _JA_CONTEXT_COMPILED = [(re.compile(rx), wrong, right) for rx, wrong, right in JA_CONTEXT]
    _JA_ENDFIELD_CONTEXT_COMPILED = [(re.compile(rx), wrong, right)
                                     for rx, wrong, right in JA_ENDFIELD_CONTEXT]
    _AK_KO_CONTEXT_COMPILED = [(re.compile(rx), wrong, right) for rx, wrong, right in AK_KO_CONTEXT]


_register_entities()
_rebuild_context_caches()


def _kb_view():
    """把 扁平表 + ENTITIES 折叠成对象级视图：{canonical: dict}。

    同一 canonical 跨表/跨模式的全部变体、条件规则、负向排除聚合为一个对象；
    ENTITIES 的 en/ja/ko/category/note 元数据覆盖进对应对象。"""
    g = globals()
    kb = {}

    def ent(c):
        return kb.setdefault(c, {
            "canonical": c, "en": "", "ja": "", "ko": "",
            "category": "", "modes": [], "variants": [],
            "ctx": [], "exclude": [], "note": ""})

    for mode, tname in _MODE_TERM_TABLE.items():
        for wrong, right in (g.get(tname) or {}).items():
            e = ent(right)
            if mode not in e["modes"]:
                e["modes"].append(mode)
            if wrong not in e["variants"]:
                e["variants"].append(wrong)
    # EN_LINE_TERM_FIXES 修正的是外文行（目标非中文官方名），单独挂 fix-en 模式
    for wrong, right in (g.get("EN_LINE_TERM_FIXES") or {}).items():
        e = ent(right)
        if "fix-en" not in e["modes"]:
            e["modes"].append("fix-en")
        if wrong not in e["variants"]:
            e["variants"].append(wrong)
    for mode, cname in _MODE_CTX_TABLE.items():
        for rx, wrong, right in (g.get(cname) or []):
            if not wrong or not right:
                continue
            e = ent(right)
            if mode not in e["modes"]:
                e["modes"].append(mode)
            if (rx, wrong) not in e["ctx"]:
                e["ctx"].append((rx, wrong))
    for wrong, (right, rxs) in (g.get("EXCLUDE_CONTEXT") or {}).items():
        e = ent(right)
        if "bi" not in e["modes"]:
            e["modes"].append("bi")
        for rx in rxs:
            if (wrong, rx) not in e["exclude"]:
                e["exclude"].append((wrong, rx))
    for e0 in ENTITIES:
        e = ent(e0.canonical)
        e["en"], e["ja"], e["ko"] = e0.en, e0.ja, e0.ko
        e["category"] = e0.category
        if e0.note:
            e["note"] = (e["note"] + "；" + e0.note) if e["note"] else e0.note
    return kb


def _cmd_kb_export(out=None, as_json=False):
    """kb-export：导出完整对象级知识库（MD 或 JSON），供审阅/投喂 AI 校准。"""
    kb = _kb_view()
    ents = sorted(kb.values(), key=lambda e: (-len(e["variants"]), e["canonical"]))
    if as_json:
        import json
        data = [{
            "canonical": e["canonical"], "en": e["en"], "ja": e["ja"],
            "ko": e["ko"], "category": e["category"],
            "modes": e["modes"], "variants": e["variants"],
            "ctx": [{"ref_regex": rx, "wrong": w} for rx, w in e["ctx"]],
            "exclude": [{"variant": w, "ref_regex": rx} for w, rx in e["exclude"]],
            "note": e["note"],
        } for e in ents]
        text = json.dumps(data, ensure_ascii=False, indent=2)
    else:
        L = ["# 字幕校准对象级知识库（kb-export）",
             "",
             f"实体数：{len(ents)} | 由扁平表折叠 + ENTITIES 元数据合并生成，"
             "变体均为 错形->官方中文名。",
             ""]
        for e in ents:
            names = " / ".join(x for x in
                               (f"EN {e['en']}" if e["en"] else "",
                                f"JA {e['ja']}" if e["ja"] else "",
                                f"KO {e['ko']}" if e["ko"] else "") if x)
            head = f"## {e['canonical']}" + (f"（{names}）" if names else "")
            L.append(head)
            meta = []
            if e["category"]:
                meta.append("类别: " + e["category"])
            meta.append("模式: " + ", ".join(
                f"{m}({_MODE_NAMES.get(m, m)})" for m in e["modes"]))
            L.append("- " + " | ".join(meta))
            if e["variants"]:
                L.append(f"- 变体({len(e['variants'])}): " + "、".join(e["variants"]))
            for rx, w in e["ctx"]:
                L.append(f"- 条件变体: [参考行 /{rx}/] {w} → {e['canonical']}")
            for w, rx in e["exclude"]:
                L.append(f"- 负向排除: {w} 替换后若参考行命中 /{rx}/ 则回滚")
            if e["note"]:
                L.append("- 备注: " + e["note"])
            L.append("")
        text = "\n".join(L)
    if out:
        with open(out, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(f"知识库已导出：{out}（实体 {len(ents)} 个）")
    else:
        print(text)


def _cmd_kb_lookup(word):
    """kb-lookup <词>：按 官方名/EN/JA/KO/任意变体 反查实体，列出全部知识。"""
    kb = _kb_view()
    q = word.lower()
    hits = []
    for e in kb.values():
        pool = [e["canonical"], e["en"], e["ja"], e["ko"],
                *e["variants"], *(w for _, w in e["ctx"]),
                *(w for w, _ in e["exclude"])]
        if any(q in str(p).lower() for p in pool if p):
            hits.append(e)
    if not hits:
        print(f"未找到与 {word!r} 相关的实体"); return
    for e in sorted(hits, key=lambda x: x["canonical"]):
        names = " / ".join(x for x in
                           (f"EN {e['en']}" if e["en"] else "",
                            f"JA {e['ja']}" if e["ja"] else "",
                            f"KO {e['ko']}" if e["ko"] else "") if x)
        print(f"◎ {e['canonical']}" + (f"（{names}）" if names else ""))
        if e["category"]:
            print(f"  类别: {e['category']}")
        print("  模式: " + ", ".join(
            f"{m}({_MODE_NAMES.get(m, m)})" for m in e["modes"]))
        if e["variants"]:
            print(f"  变体({len(e['variants'])}): " + "、".join(e["variants"]))
        for rx, w in e["ctx"]:
            print(f"  条件变体: [/{rx}/] {w} → {e['canonical']}")
        for w, rx in e["exclude"]:
            print(f"  负向排除: {w} 命中 /{rx}/ 则回滚")
        if e["note"]:
            print("  备注: " + e["note"])


def _cmd_kb_lint():
    """kb-lint：对象级体检（互补 terms-check 的表内二次命中检查）。

    检查项：
      1. 变体冲突：同一错形在不同实体映射到不同 canonical 且【模式有交集】
         （2026-09-12 起：模式互斥的同形多义不再误报，如 Typhon 在
         endo=提弗洛斯 / ak=提丰 —— 两模式永不并存，属合法多义）；
      2. 级联互含（对象级）：同模式内，甲实体的变体是乙实体 canonical 的子串
         （替换到乙的 canonical 后会被甲的变体二次命中）；
         已显式声明 subst 兜底规则的对象不再报（已知边界机器可读化）；
      3. 条件变体冗余：ctx 错形同模式下已是无条件变体（佐证永远不会生效）、
         或 wrong==right 的空操作规则；
      4. ENTITIES 元数据完整性：缺 en/ja/ko/category/note 的对象级提示。"""
    kb = _kb_view()
    problems, infos = [], []

    # 0. 收集对象级声明：subst 兜底（已知边界）与 multiplex 模式内多义
    subst_ok = set()          # (被包含的变体, 承载它的 canonical)
    for e0 in ENTITIES:
        for vk, rx, tgt in e0.subst:
            subst_ok.add((vk, e0.canonical))
    # multiplex: (错形, 模式) -> 该模式下由别的 canonical 负责，属刻意分派
    multiplex_ok = set()
    for e0 in ENTITIES:
        for v, m, other in e0.multiplex:
            multiplex_ok.add((v, m, e0.canonical, other))
            multiplex_ok.add((v, m, other, e0.canonical))

    # 1. 变体冲突（跨实体，模式有交集才算冲突；multiplex 声明的分派不算）
    seen = {}
    for e in kb.values():
        for v in e["variants"]:
            if v == e["canonical"]:
                continue
            prev = seen.get(v)
            if prev and prev[0] != e["canonical"]:
                shared = set(prev[1]) & set(e["modes"])
                if shared and not all(
                        (v, m, prev[0], e["canonical"]) in multiplex_ok
                        for m in shared):
                    problems.append(
                        f"变体冲突: {v!r} -> {prev[0]!r}（{prev[1]}）与 "
                        f"{e['canonical']!r}（{e['modes']}）共用模式 {sorted(shared)}")
                elif shared:
                    infos.append(
                        f"模式内多义（已声明 multiplex，合法）: {v!r} -> "
                        f"{prev[0]!r} / {e['canonical']!r}（共用 {sorted(shared)}）")
                else:
                    infos.append(
                        f"同形多义（模式互斥，合法）: {v!r} -> {prev[0]!r}"
                        f"（{prev[1]}）/ {e['canonical']!r}（{e['modes']}）")
            else:
                seen.setdefault(v, (e["canonical"], e["modes"]))
    # 2. 级联互含：同模式内 变体 ⊂ 他实体 canonical
    by_mode = {}
    for e in kb.values():
        for m in e["modes"]:
            if m == "fix-en":
                continue
            by_mode.setdefault(m, []).append(e)
    for m, es in by_mode.items():
        for e in es:
            for other in es:
                if other is e or other["canonical"] == e["canonical"]:
                    continue
                if len(e["canonical"]) <= 2:
                    continue
                for v in other["variants"]:
                    if v and v in e["canonical"] and v != e["canonical"]:
                        if (v, e["canonical"]) in subst_ok:
                            continue      # 已声明兜底（已知边界）
                        problems.append(
                            f"级联互含[{m}]: 变体 {v!r}（->{other['canonical']!r}）"
                            f"是 {e['canonical']!r} 的子串，替换后可能二次命中")
    # 3. 条件变体冗余
    g = globals()
    for mode, cname in _MODE_CTX_TABLE.items():
        tname = _MODE_TERM_TABLE.get(mode)
        tbl = g.get(tname) or {}
        for rx, wrong, right in (g.get(cname) or []):
            if not wrong or not right:
                continue
            if wrong == right:
                infos.append(
                    f"条件空操作[{mode}]: {wrong!r}->{right!r} 首尾同形，"
                    f"ctx 规则 /{rx}/ 恒不产生改动，建议删除")
            elif tbl.get(wrong) == right:
                infos.append(
                    f"条件冗余[{mode}]: {wrong!r}->{right!r} 已是 {tname} 无条件变体，"
                    f"ctx 规则 /{rx}/ 永不生效")
    # 4. ENTITIES 元数据完整性
    for e0 in ENTITIES:
        miss = [f for f, v in (("en", e0.en), ("category", e0.category),
                               ("note", e0.note)) if not v]
        if miss:
            infos.append(f"ENTITIES 元数据待补: {e0.canonical!r} 缺 {', '.join(miss)}")
    for p in problems:
        print("⚠", p)
    for p in infos:
        print("ℹ", p)
    if not problems and not infos:
        print("KB-LINT OK：无变体冲突/级联互含/条件冗余")
    else:
        print(f"KB-LINT：{len(problems)} 处问题，{len(infos)} 条提示")


# =============================================================
# 7. 学习系统（规则引擎 + 从人工修正中学习，2026-09-11）
#
#    闭环：每次人工校准产出的 [原始srt + 校准srt] 配对即训练样本。
#      learn 配对投喂 -> difflib 抽取 cue 内 错形->正形 片段 ->
#      写入持久化候选库(默认 ./subtitle_learned_kb.json，--kb 改路径)。
#    候选状态机（自我迭代核心）：
#      candidate  首次/低频出现；count<2 或有未纠正反例
#      confirmed  count>=2 且从未出现"同一错形在原文中保留未改"的反例
#                 -> 校准运行时按记录的模式自动注入术语表（无需人工）
#      降级       confirmed 候选在后续投喂中出现反例 -> 自动降回
#                 candidate，并从纠正/未纠正两类参考行的词元差异
#                 自动生成"上下文佐证正则"建议（ctx_regex 字段）
#      rejected   learned-reject 人工否决，永不应用（保留证据备查）
#    投喂原则：
#      · 投喂时 --mode 必须等于该校准任务实际使用的模式，候选按模式隔离；
#      · 同一错形被改成不同目标 -> 记 conflict，不自动应用，人工裁决；
#      · 整句重写/ERROR 重译不属于"名词级校准"，不学习（span>30字跳过）；
#      · 固化路径：confirmed 积累到一定量后 learned-promote --entities
#        导出 Entity 桩代码，人工审阅后粘贴进第 6 节 ENTITIES，
#        学习成果即沉淀为对象级知识。
# =============================================================

LEARNED_KB_DEFAULT = "subtitle_learned_kb.json"


def _load_learned_kb(path):
    """读取学习库；不存在则返回空库。"""
    import json
    if path and os.path.exists(path):
        try:
            kb = json.loads(_decode_any(open(path, "rb").read()))
            if isinstance(kb, dict) and "candidates" in kb:
                return kb
        except Exception as e:
            print(f"⚠ 学习库读取失败（{e}），按空库继续")
    return {"version": 1, "candidates": {}}


def _save_learned_kb(kb, path):
    import json
    with open(path, "w", encoding="utf-8") as f:
        json.dump(kb, f, ensure_ascii=False, indent=1)


def _parse_cue_pairs(path):
    """解析 SRT -> [(num, 中文行(多行\\n连接), 参考行)]。结构容错同主引擎。"""
    raw = open(path, "rb").read()
    lines = _decode_any(raw).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    cues, i, n = [], 0, len(lines)
    while i < n:
        s = lines[i].strip()
        if s.isdigit() and (i == 0 or lines[i - 1].strip() == ""):
            j = i + 1
            if j < n and "-->" in lines[j]:
                kk = j + 1
                while kk < n and lines[kk].strip() != "":
                    kk += 1
                if kk - 1 >= j + 1:
                    texts = lines[j + 1:kk]
                    cues.append((int(s), "\n".join(texts[:-1]), texts[-1]))
                i = kk
                continue
        i += 1
    return cues


def _diff_spans(old, new):
    """difflib 抽取 old->new 的最小替换片段，返回
    [(wrong, right, left_old, right_old, left_new, right_new)]（前后文采样，
    供跨出现处公共词缀扩展用）。整句重写（span>30字）不学习。"""
    import difflib
    out = []
    for tag, a1, a2, b1, b2 in difflib.SequenceMatcher(
            None, old, new, autojunk=False).get_opcodes():
        if tag != "replace":
            continue
        wrong, right = old[a1:a2].strip(), new[b1:b2].strip()
        if not wrong or not right or wrong == right:
            continue
        if len(wrong) < 2 or len(wrong) > 30 or len(right) > 30:
            continue                      # 单字噪音/整句重写 不入候选
        if wrong.isdigit():
            continue
        out.append((wrong, right, old[:a1], old[a2:], new[:b1], new[b2:]))
    return out


def _common_prefix(strs, cap=6):
    """字符串列表的最长公共前缀（cap 封顶）。"""
    if not strs:
        return ""
    p = strs[0][:cap]
    for s in strs[1:]:
        while p and not s.startswith(p):
            p = p[:-1]
    return p


def _common_suffix(strs, cap=6):
    if not strs:
        return ""
    p = strs[0][-cap:]
    for s in strs[1:]:
        while p and not s.endswith(p):
            p = p[1:]
    return p


def _learn_extended(c):
    """跨出现处的公共词缀扩展：把最小差异片段扩展为稳定词元。

    依据：同一专名的多次 ASR 误听/修正中，差异最小片段（佩莉->珀）的
    两侧上下文在 old 各出现处共享的部分（西娅…），即该词元的真实边界。
    样本>=2 才扩展（单次出现无法区分词元与句子），两侧各封顶 6 字。
    返回 (应用形态 wrong, right)；样本不足返回原始最小片段。"""
    samples = c.get("samples") or []
    if len(samples) < 2:
        return c["wrong"], c["right"]
    lo = _common_suffix([s[0] for s in samples])
    ln_ = _common_suffix([s[2] for s in samples])
    n = min(len(lo), len(ln_))
    lsuf = lo[-n:] if n else ""
    ro = _common_prefix([s[1] for s in samples])
    rn = _common_prefix([s[3] for s in samples])
    m = min(len(ro), len(rn))
    rpfx = ro[:m] if m else ""
    return lsuf + c["wrong"] + rpfx, lsuf + c["right"] + rpfx


def _ref_tokens(ref):
    """参考行词元（拉丁词；用于生成上下文佐证正则建议）。"""
    return set(re.findall(r"[A-Za-z][A-Za-z'\-]{2,}", ref))


def _learn_update_status(c):
    """候选状态机：count/uncorrected 驱动 确认/降级，并生成上下文建议。
    返回 True 表示本次发生了 confirmed->candidate 反例降级。"""
    if c["status"] == "rejected":
        return False
    if c.get("conflict"):
        c["status"] = "candidate"
        return False
    if c["count"] >= 2 and c["uncorrected"] == 0:
        c["status"] = "confirmed"
        c.pop("ctx_regex", None)
        return False
    demoted = c["status"] == "confirmed" and c["uncorrected"] > 0
    if demoted:
        c["demoted"] = True                   # confirmed -> 反例降级标记
    c["status"] = "candidate"
    # 上下文建议：纠正实例参考行词元中、未纠正实例里不出现的，取前 3
    corr, unc = c.get("ref_tokens", {}), c.get("unc_ref_tokens", {})
    sig = sorted(((t, n) for t, n in corr.items() if t not in unc),
                 key=lambda kv: -kv[1])[:3]
    c["ctx_regex"] = "|".join(rf"\b{re.escape(t)}\b" for t, _ in sig) if sig else ""
    return demoted


def _cmd_learn(src, calib, kb_path=LEARNED_KB_DEFAULT, mode="bi"):
    """learn：投喂 [原始srt + 人工校准srt] 配对，挖掘候选规则并更新学习库。"""
    import datetime
    sc, oc = _parse_cue_pairs(src), _parse_cue_pairs(calib)
    if len(sc) != len(oc):
        print(f"⚠ cue 数不一致（原 {len(sc)} / 校准 {len(oc)}），按序号交集学习")
    smap, omap = {n: (z, r) for n, z, r in sc}, {n: (z, r) for n, z, r in oc}
    kb = _load_learned_kb(kb_path)
    cands = kb["candidates"]
    today = datetime.date.today().isoformat()
    new_cnt = upd_cnt = skip_same = 0

    def key(mode_, wrong):
        return f"{mode_}|{wrong}"

    # 第一遍：挖替换片段（纠正实例）
    touched = set()
    for num in sorted(smap.keys() & omap.keys()):
        oz, ref = smap[num]
        nz, _ = omap[num]
        if oz == nz:
            skip_same += 1
            continue
        if oz.strip() == "ERROR":
            continue                          # ERROR 重译属整句补译，不学习
        for wrong, right, lo, ro, ln, rn in _diff_spans(oz, nz):
            k = key(mode, wrong)
            c = cands.get(k)
            if c is None:
                c = {"wrong": wrong, "right": right, "mode": mode,
                     "count": 0, "uncorrected": 0, "status": "candidate",
                     "cues": [], "samples": [], "ref_tokens": {},
                     "unc_ref_tokens": {},
                     "first": today, "last": today, "alts": {}}
                cands[k] = c
                new_cnt += 1
            else:
                upd_cnt += 1
            if c["right"] != right:
                c["alts"][right] = c["alts"].get(right, 0) + 1
                c["conflict"] = True          # 同一错形被改成不同目标：人工裁决
            else:
                c["count"] += 1
                if len(c["samples"]) < 10:
                    c["samples"].append((lo[-12:], ro[:12], ln[-12:], rn[:12]))
            if num not in c["cues"] and len(c["cues"]) < 20:
                c["cues"].append(num)
            for t in _ref_tokens(ref):
                c["ref_tokens"][t] = c["ref_tokens"].get(t, 0) + 1
            c["last"] = today
            touched.add(k)
    # 第二遍：反例扫描——本模式所有候选（按扩展形态）在原文出现但校准后仍保留 = 未纠正反例
    for k, c in cands.items():
        if c["mode"] != mode or c["status"] == "rejected":
            continue
        w, _r = _learn_extended(c)
        for num, (oz, ref) in smap.items():
            if w not in oz:
                continue
            nz = omap.get(num, (oz,))[0]
            if w in nz:                       # 原文有、校准后仍在 -> 反例
                c["uncorrected"] += 1
                for t in _ref_tokens(ref):
                    c["unc_ref_tokens"][t] = c["unc_ref_tokens"].get(t, 0) + 1
    # 状态机更新 + 既有术语表查重（已沉淀的不再作为候选）
    g = globals()
    tname = _MODE_TERM_TABLE.get(mode)
    builtin = g.get(tname) or {}
    confirmed = demoted = conflicts = dup_builtin = 0
    for k in list(cands.keys()):
        c = cands[k]
        if c["mode"] == mode:
            ew, er = _learn_extended(c)
            if builtin.get(ew) == er or builtin.get(c["wrong"]) == c["right"]:
                del cands[k]                  # 已进扁平表/实体层，无需学习
                dup_builtin += 1
                continue
        if c["mode"] != mode:
            continue
        if _learn_update_status(c):
            demoted += 1
        confirmed += c["status"] == "confirmed"
        conflicts += bool(c.get("conflict"))
    _save_learned_kb(kb, kb_path)
    print(f"learn[{mode}]：cue {len(smap.keys() & omap.keys())}（无改动 {skip_same}）"
          f" | 新增候选 {new_cnt}，命中既有候选 {upd_cnt}，已沉淀去重 {dup_builtin}")
    print(f"学习库 {kb_path}：confirmed {confirmed} / 反例降级 {demoted} / 冲突待裁决 {conflicts}")
    if demoted:
        print("  ⚠ 有 confirmed 规则出现反例被降级，请 learned-show 查看 ctx_regex 建议")


def _learned_terms_for_mode(kb_path, mode):
    """校准运行时注入：confirmed 且属本模式的学习规则 -> {扩展错形: 扩展正形}。"""
    kb = _load_learned_kb(kb_path)
    out = {}
    for c in kb["candidates"].values():
        if c["mode"] == mode and c["status"] == "confirmed" and not c.get("conflict"):
            w, r = _learn_extended(c)
            out[w] = r
    return out


def _cmd_learned_show(kb_path=LEARNED_KB_DEFAULT, mode=None):
    """learned-show：查看学习库候选（可按模式过滤）。"""
    kb = _load_learned_kb(kb_path)
    rows = [c for c in kb["candidates"].values() if not mode or c["mode"] == mode]
    if not rows:
        print("学习库为空" + (f"（模式 {mode}）" if mode else "")); return
    order = {"confirmed": 0, "candidate": 1, "rejected": 2}
    for c in sorted(rows, key=lambda x: (order.get(x["status"], 3), -x["count"])):
        flag = {"confirmed": "✓", "candidate": "…", "rejected": "✗"}[c["status"]]
        w, r = _learn_extended(c)
        ext = "" if (w, r) == (c["wrong"], c["right"]) else f"（应用形态 {w!r}->{r!r}）"
        line = (f"{flag} [{c['mode']}] {c['wrong']!r} -> {c['right']!r}{ext} "
                f"命中{c['count']} 反例{c['uncorrected']} cues{c['cues'][:6]}")
        if c.get("conflict"):
            line += f" ⚠冲突:亦被改为 {list(c['alts'])}"
        if c.get("ctx_regex"):
            line += f" | 建议佐证: /{c['ctx_regex']}/"
        if c.get("demoted"):
            line += " | [曾确认后降级]"
        print(line)
    print(f"合计 {len(rows)} 条（{kb_path}）")


def _cmd_learned_promote(kb_path=LEARNED_KB_DEFAULT, mode=None, entities=False):
    """learned-promote：confirmed 规则导出为 Entity 桩代码（--entities），
    人工审阅后粘贴进第 6 节 ENTITIES，完成 学习成果->对象级知识 的固化。"""
    kb = _load_learned_kb(kb_path)
    rows = [c for c in kb["candidates"].values()
            if c["status"] == "confirmed" and not c.get("conflict")
            and (not mode or c["mode"] == mode)]
    if not rows:
        print("# 无可固化的 confirmed 规则")
    else:
        by_right = {}
        for c in rows:
            w, r = _learn_extended(c)
            by_right.setdefault((r, c["mode"]), []).append((w, c))
        print("# ---- learned-promote 导出（人工审阅后并入 ENTITIES）----")
        for (right, m), cs in sorted(by_right.items()):
            variants = sorted({w for w, _ in cs}, key=len, reverse=True)
            cues = sorted({n for _, c in cs for n in c["cues"]})
            firsts = min(c["first"] for _, c in cs)
            print(f'    Entity({right!r}, modes=({m!r},),')
            print(f"           variants={tuple(variants)!r},")
            print(f"           note='学习库固化：{len(cs)}条规则，证据cue {cues[:8]}，"
                  f"首次 {firsts}。en/ja/ko/category 待人工补全'),")
    sugg = [c for c in kb["candidates"].values()
            if c["status"] == "candidate" and c.get("ctx_regex")
            and not c.get("conflict") and (not mode or c["mode"] == mode)]
    if sugg:
        print("\n# ---- 带反例的候选：建议作为 ctx 条件变体人工确认 ----")
        for c in sugg:
            w, r = _learn_extended(c)
            print(f"#   ctx=(({c['ctx_regex']!r}, {w!r}),)  # Entity({r!r}) 收"
                  f" 命中{c['count']} 反例{c['uncorrected']} [{c['mode']}]")


def _cmd_learned_reject(word, kb_path=LEARNED_KB_DEFAULT, mode=None):
    """learned-reject <错形>：人工否决候选（永不自动应用，保留证据）。"""
    kb = _load_learned_kb(kb_path)
    hit = 0
    for c in kb["candidates"].values():
        if c["wrong"] == word and (not mode or c["mode"] == mode):
            c["status"] = "rejected"
            hit += 1
    if hit:
        _save_learned_kb(kb, kb_path)
        print(f"已否决 {hit} 条候选：{word!r}")
    else:
        print(f"未找到候选：{word!r}")


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
    for ln in _decode_any(open(path, "rb").read()).splitlines():
        ln = ln.strip("\ufeff").rstrip("\r")
        m = re.match(r"(\d+)", ln)
        if not m:
            continue
        txt = ln[m.end():].lstrip("\t \u3000\u3000").strip()
        if txt:
            over[m.group(1)] = txt
    return over


def process(path, out_path=None, report_path=None, mode="bi",
            fix_en=False, pgr_override=None, learned_kb=None):
    """对 SRT 校准。返回 (改动行rows, 术语命中hits)。
      mode="bi"   双语模式：BILINGUAL_TERMS + CONTEXT_MAP + WORD_MAP 改首中文行。
      mode="ko"   韩语模式：KO_TERMS 统一中文行术语。
      mode="ja"   日语模式：JA_TERMS + JA_CONTEXT（日语参考行佐证）统一中文行术语。
      mode="endo" 终末地模式：ENDFIELD_TERMS 统一全部文本行。
      mode="ak"   明日方舟本体模式：AK_TERMS 统一中文行术语（仅首中文行）。
      mode="zho"  中文行专属模式：ZH_ONLY_TERMS 只改首中文行英文噪音（不动英文/参考行）。
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
    elif mode == "pgren":       # 战双帕弥什·英文原声（中英双语片源）：PGR_EN_TERMS 统一首中文行
        terms = PGR_EN_TERMS
    elif mode == "akko":        # 明日方舟韩语原声：AK_KO_TERMS + AK_KO_CONTEXT(韩语佐证)
        terms = AK_KO_TERMS
    elif mode == "react":
        terms = REACT_TERMS
    elif mode == "pgr":
        terms = {}
    else:
        terms = BILINGUAL_TERMS
    # 学习系统注入：confirmed 规则并入本模式术语表（与既有键冲突时跳过并告警）
    if learned_kb:
        lt = _learned_terms_for_mode(learned_kb, mode)
        if lt:
            terms = dict(terms)
            skipped = 0
            for w, r in lt.items():
                if w in terms and terms[w] != r:
                    skipped += 1
                    continue
                terms.setdefault(w, r)
            if skipped:
                print(f"⚠ {skipped} 条学习规则与既有术语表目标冲突，已跳过"
                      f"（learned-show 查看，人工裁决）")
    # 术语表只编译一次（长键序 + 键字符集），逐行替换走 _replace_report 单遍扫描
    term_pairs, term_chars = _compile_map(terms)
    word_pairs, word_chars = _compile_map(WORD_MAP)
    enfix_pairs, enfix_chars = _compile_map(EN_LINE_TERM_FIXES)

    raw = open(path, "rb").read()
    crlf = b"\r\n" in raw
    bom = raw.startswith(b"\xef\xbb\xbf")
    norm = _decode_any(raw).replace("\r\n", "\n").replace("\r", "\n")
    lines = norm.split("\n")
    out = list(lines)

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
                    elif mode in ("ko", "wwoc", "react", "pgren"):  # 韩语/综合游戏/音乐点评/战双英文原声：统一首中文行术语（不动参考行）
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
                i = kk
                continue
        i += 1

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
    norm = (_decode_any(raw).replace("\r\n", "\n").replace("\r", "\n"))
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
    rows = _decode_any(open(cues, "rb").read()).splitlines()
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
        for ln in _decode_any(open(p, "rb").read()).splitlines():
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
    norm = _decode_any(raw).replace("\r\n", "\n").replace("\r", "\n")
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
    # （歌词片源）被覆盖成单行后，后续 cue 的行索引静默错位、
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
        lines = _decode_any(raw).replace("\r\n", "\n").replace("\r", "\n").split("\n")
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
    print("VERIFY OK：仅中文行变化，其它全部一致")


def _cmd_compare(src, out, tsv):
    """compare：比对两个 SRT 生成 错误vs正确 对照表（序号/原文中文/校准后中文/英文行）。"""
    def parse(p):
        lines = _decode_any(open(p, "rb").read()).replace("\r\n", "\n").split("\n")
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
    rows = _decode_any(open(cues, "rb").read()).splitlines()
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
    for ln in _decode_any(open(path, "rb").read()).splitlines():
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
    lines = _decode_any(raw).replace("\r\n", "\n").replace("\r", "\n").split("\n")
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
                   "subfix", "terms-check", "termscheck", "terms",
                   "kb-export", "kb-lookup", "kb-lint",
                   "learn", "learned-show", "learned-promote", "learned-reject"):
            _dispatch_subcommand(sub, argv[1:])
            return

    src = None
    out_path = report_path = None
    mode = "bi"
    fix_en = False
    learned_kb = None

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
        elif a == "--pgren":
            mode = "pgren"; i += 1
        elif a == "--react":
            mode = "react"; i += 1
        elif a == "--fix-en":
            fix_en = True; i += 1
        elif a == "--kb" and i + 1 < len(args):
            learned_kb = args[i + 1]; i += 2
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

    # 学习库：--kb 指定；未指定时若 cwd 存在默认库则自动加载（confirmed 规则自动生效）
    if learned_kb is None and os.path.exists(LEARNED_KB_DEFAULT):
        learned_kb = LEARNED_KB_DEFAULT
    pgr_override = _load_override_tsv(PGR_OVERRIDES_SRC) if mode == "pgr" else None
    rows, hits = process(src, out_path, report_path, mode=mode,
                         fix_en=fix_en, pgr_override=pgr_override,
                         learned_kb=learned_kb)
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
             "pgren": "战双帕弥什·英文原声 (PGR_EN_TERMS)",
             "react": "音乐/演唱点评 (REACT_TERMS)"}
    extra = (" + 英文行修正(--fix-en)" if fix_en else "")
    print("模式:", names[mode] + extra)
    if learned_kb:
        n_conf = len(_learned_terms_for_mode(learned_kb, mode))
        print(f"学习库: {learned_kb}（本模式 confirmed 规则 {n_conf} 条已注入）")
    print("存在术语表错误形式的块:", hits if hits else "无（已统一）")
    if out_path:
        print(f"已写入：{out_path}（{len(rows)} 处文本改动，序号/时间轴/空行/换行/BOM 保持原样）")
    if report_path:
        print(f"报告：{report_path}（{len(rows)} 处文本改动）")


def _cmd_lint(cues, calib_src):
    """lint：校验校准表相对 cue 表的完整性与文本质量。
    检查：重复序号 / 缺号（cue表有序号而校准表漏写）/ 越界序号 / 空文案 /
    中文文案中的意外拉丁-变音残留（白名单外的英文单词）/
    2026-09-05 沉淀自 Gloomwald's Rage 二次校准：分段书写 calib_*.tsv 时
    曾出现序号重复（127 写两遍）与外文残留（undeniable/càng/chord shape）。"""
    cue_nums = []
    for ln in _decode_any(open(cues, "rb").read()).splitlines()[1:]:
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
        for ln in _decode_any(open(p, "rb").read()).splitlines():
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
    if problems:
        print(f"LINT {len(problems)} 处问题:")
        for p in problems:
            print(" -", p)
    else:
        print(f"LINT OK：{len(cue_nums)} cue 全覆盖，无重复/越界/空文案/拉丁残留")


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
        elif a == "--json":
            opts["json"] = True; i += 1
        elif a == "--entities":
            opts["entities"] = True; i += 1
        elif a in ("--kb", "--mode") and i + 1 < len(args):
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
    elif sub in ("terms-check", "termscheck", "terms"):
        _cmd_terms_check(pos)
    elif sub == "kb-export":
        _cmd_kb_export(opts.get("out"), as_json=bool(opts.get("json")))
    elif sub == "kb-lookup":
        if not pos:
            print("用法: kb-lookup <词>"); return
        _cmd_kb_lookup(pos[0])
    elif sub == "kb-lint":
        _cmd_kb_lint()
    elif sub == "learn":
        if len(pos) < 2:
            print("用法: learn <原始.srt> <人工校准.srt> [--mode bi] [--kb 学习库.json]"); return
        _cmd_learn(pos[0], pos[1], opts.get("kb", LEARNED_KB_DEFAULT),
                   mode=opts.get("mode", "bi"))
    elif sub == "learned-show":
        _cmd_learned_show(opts.get("kb", LEARNED_KB_DEFAULT), mode=opts.get("mode"))
    elif sub == "learned-promote":
        _cmd_learned_promote(opts.get("kb", LEARNED_KB_DEFAULT),
                             mode=opts.get("mode"), entities=bool(opts.get("entities", True)))
    elif sub == "learned-reject":
        if not pos:
            print("用法: learned-reject <错形> [--mode bi] [--kb 学习库.json]"); return
        _cmd_learned_reject(pos[0], opts.get("kb", LEARNED_KB_DEFAULT),
                            mode=opts.get("mode"))


if __name__ == "__main__":
    main_argv()
