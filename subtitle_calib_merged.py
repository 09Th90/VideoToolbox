# -*- coding: utf-8 -*-
# @version 1.16.1
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
  EN_ASR_SPLIT_FIXES      英文参考行 ASR「断词/粘连」修正（2026-09-28 新增）：
                          锚定匹配前自动规整参考行（CONTEXT 佐证不再被断词打断），
                          --fix-en 时同时修正英文输出行；另配 scan-split 子命令扫描候选
  ENTITIES                对象级知识层（2026-09-11 起新对照一律以 Entity 追加于此，
                          注册时自动投影进上述扁平表；见文件第 6 节）
注意各片源术语按模式分开应用，勿混（同一个中文词在不同片源里含义可能不同；
终末地术语也不能套到鸣潮片源）。

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
       [--ja|--jpe|--ko|--endo|--ak|--zho|--pgr|--zel] [--fix-en]

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
  --zel    塞尔达传说模式（2026-09-14 新增）：ZELDA_TERMS 统一首中文行专名/官方译名
           （暮光公主->黄昏公主、风之杖->风之律动、海拉尔->海拉鲁、近藤浩二->近藤浩治 等），
           英文参考行一字不动。表与其它片源严格隔离，勿混用；系统性机翻误译（通用中文词）
           不入裸键，走逐 cue 侧车整行覆盖。（第 5.x 节，检索依据见该表注释）
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
  python subtitle_calib_merged.py scan-split <a.srt> [b.srt ...] [--min 1] # 扫描英文/参考行
        # 里的疑似 ASR 断词（"reson ator"/"Water ing lace"），列出候选供补 EN_ASR_SPLIT_FIXES（只读）
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

D. 增量同步通道（v1.12.1 起：本脚本只保留用户侧两个动作，管理动作全部
   移交给独立程序 kb_admin.py，本脚本不再包含任何管理员命令）:
  多用户知识收敛为「哑更新库 = 权威基线 + 各人收件箱」：客户端只读基线、
  只写自己的收件箱，本地确定性合并（baseline ∪ 全部增量，ts+id 全局序）：
  python subtitle_calib_merged.py kb-sync             # 更新：拉取 + 合并 + 三道门 + 应用（校准入口自动执行；幂等）
  python subtitle_calib_merged.py kb-push [--learned 库] [--file 增量.jsonl]
                                                      # 上传增量（learn 收尾、learned-reject 自动调用）
  回滚：VT_SYNC_MODE=legacy 整体停用增量；VT_NO_SYNC=1 强制关闭；
        config.disabled_keys 条目级禁用。增量数据全链路仅 json.load，禁止 eval/exec。
  更新库位置：VT_SYNC_ROOT（缺省 data/calib_sync_remote/）；本机状态 data/calib_sync/。
"""
import io
import os
import re
import sys
import unicodedata

# =============================================================
# 0. 统一解码：外部/用户文本一律智能解码，绝不因编码而崩
# =============================================================
# 背景（v1.12.0 修复）：本层曾在 v1.11.0 引入，重构时被删，导致输入解码退回
# 硬 `utf-8-sig` —— GBK/GB18030/Big5 编码的字幕直接 UnicodeDecodeError，
# 整条校准链路不可用（_selftest_pack 的「_decode_any 可读 GBK 字幕」即为守门断言）。
# 原则：读取外部/用户文本一律智能解码；写出统一 UTF-8（是否带 BOM / CRLF 按原样保留）。
TEXT_ENCODINGS = ("utf-8-sig", "utf-8", "gb18030", "big5", "shift_jis", "latin-1")


def _decode_any(data, encodings=TEXT_ENCODINGS):
    """把任意字节流解码成文本（永不抛异常）。

    BOM 优先：utf-32 > utf-16 > utf-8（用带 BOM 的编解码器，可自动剥掉 BOM）；
    无 BOM 依次尝试 utf-8 → gb18030（GBK 超集）→ big5 → shift_jis → latin-1，
    最后兜底 utf-8 replace。ASCII 是 UTF-8 子集，天然覆盖。
    """
    if isinstance(data, str):
        return data
    if not data:
        return ""
    if data[:4] in (b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff"):
        try:
            return data.decode("utf-32")
        except UnicodeDecodeError:
            pass
    elif data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        try:
            return data.decode("utf-16")
        except UnicodeDecodeError:
            pass
    if data[:3] == b"\xef\xbb\xbf":
        try:
            return data.decode("utf-8-sig")
        except UnicodeDecodeError:
            pass
    for enc in encodings:
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", "replace")


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
    (r"[Ss]howcase", "展示会", "展示"),
    (r"[Ss]creen ?time", "屏幕时间", "镜头时间"),
    (r"\bPresident\b", "总统", "校长"),
    (r"\bLady\s+Shin'?s\b", "Lady Shin's", "心月狐女士的"),
    (r"\bLady\s+Shin\b|\bShin\s+Lady\b", "Lady Shin", "心月狐女士"),
    (r"\bLady\s+Shin\b|\bShin\s+Lady\b", "Shin Lady", "心月狐女士"),
    (r"\bSwarming\b|\bSuoming\b", "蜂群", "锁暝"),
    (r"\bSwarming\b|\bSuoming\b", "蜂拥", "锁暝"),
    (r"\bSwarming\b|\bSuoming\b", "群聚", "锁暝"),
    (r"\bSwaming\b|\bSuoming\b", "斯瓦明", "锁暝"),     # #4316 Suoming 音译错形（EN 同步修 Swaming）
    (r"\b[Ii]ntendant\b|\b[Aa]ttendant\b", "总监", "州监"),
    (r"\b[Ii]ntendant\b|\b[Aa]ttendant\b", "工作人员", "州监"),
    (r"\bauto[\s-]?puppets?\b|\b[Aa]utopuppets?\b|\b[Pp]uppets?\b", "自动木偶", "机傀"),
    (r"\bauto[\s-]?puppets?\b|\b[Aa]utopuppets?\b|\b[Pp]uppets?\b", "木偶", "机傀"),
    (r"\b[Aa]utopets?\b", "自动宠物", "机关宠物"),
    (r"\bSuming\b|\bSuoming\b", "素明", "锁暝"),
    (r"\b[Aa]rbiter\b|\bAbiter\b", "裁决者", "御者"),
    (r"\b[Ff]ox\b", "福克斯", "狐狸"),
    (r"\bAbiter\b|\bArbiter\b", "阿比特", "御者"),       # #2088 Abiter=Arbiter 漏音节
    (r"\bAby\b|\bAbby\b", "阿比", "阿布"),              # #5846/#5990 Aby=Abby 阿布（小狐狸搭档）
    (r"\bShranong\b|\bSchwanfong\b", "施拉农", "玄方城"),
    (r"\b[Mm]inistr(?:y|ies)\b", "魔法部", "谛天鉴"),
    (r"resonators?\b", "谐振腔", "共鸣者"),         # 同上（"谐振腔"变体，2026-10-04 英文原声 3.7 反应片）
    (r"\bChing\w*", "清莎", "清宵"),
    (r"\bChing\w*", "青石", "清宵"),               # #6593 Ching Shia（"青石"为常用词，须 Ching 佐证）
    (r"\bChing\b", "青", "清宵"),                  # #1015 Suming and Ching 独立简称
    (r"\bChing\b", "程", "清宵"),                  # #6503 呼语 Ching,（程为常用字，须独立 Ching 佐证）
    (r"\bChingan\b|\bJingran\b", "钦安", "景燃"),   # #6776 Chingan（与下句 Jingron 同指一人）
    (r"\bJingron\b|\bJingran\b", "景蓉", "景燃"),   # #6779 Jingron 谷翻错形
    (r"\bcivilization capsule\b", "文明舱", "文明之匣"),   # #957 官方中文=文明之匣（灰机wiki/3.7 剧情帖；旧目标"文明胶囊"作废）
    (r"\bLady\b", "Lady", "心月狐女士"),          # Lady(Shin) 称呼，谷翻留英文（#1662/#3356）
    (r"\bseal\b", "seal", "封印"),                # 玄朱锁语境 seal=封印（#4107）
    (r"\bSector Bing\b", "Bing", "丙"),           # Sector Bing=丙区（天干分区，#1537）
    (r"\bEin said\b", "Ein", "艾因"),             # NPC 艾因（#1944）
    (r"\bbang boo\b|\bbamboo\b", "bang boo", "竹子"),        # bamboo 断词误写（#5757，容纳 EN 修正后形态）
    (r"\bsheen guide\b|\bSheen's guidance\b", "sheen指南", "心月狐指引"),  # Sheen's guide（#5757）
    (r"\b[Tt]ac[ei]t discords?\b", "默契的不和", "残象"),  # Tacet Discord 谷翻系列错形（#3503/#5508）
    (r"\b[Tt]ac[ei]t discords?\b", "默契的分歧", "残象"),  # #4698
    (r"\b[Tt]ac[ei]t discords?\b", "默契的纷争", "残象"),  # #5952
    (r"\bHuang ?Long\b|\bHong ?Long\b|\bHuan ?Long\b", "黄龙", "瑝珑"),   # #85/#1007/#5084
    (r"\bSuing\b", "苏姐", "锁暝姐"),            # #2920/#5005
    (r"\bSuing\b", "起诉", "锁暝"),              # #2851
    (r"\bAlberta\b|\balbat\b", "艾伯塔省", "御者"),   # #5231
    (r"\bAlberta\b|\balbat\b", "阿尔巴特", "御者"),   # #5235
    (r"\bmoving to MJ\b|\bto MJ\b|\bMJ\b", "MJ", "梦州"),   # #51
    (r"\bsanctums?\b", "圣殿", "万相神宫"),      # #241/#244/#456/#693/#757/#987/#1044/#1072/#2048/#4750
    (r"\bsanctums?\b", "圣地", "万相神宫"),      # #590
    (r"\bsanctums?\b", "圣所", "万相神宫"),      # Entity ctx 已覆盖，双保险
    (r"\bcapsules?\b", "文明胶囊", "文明之匣"),  # #1013/#2393/#2427（长键先行）
    (r"\bcapsules?\b", "胶囊", "文明之匣"),      # #867/#2038/#2079/#2086/#2141/#2464/#2490/#3760/#3819/#3983/#4048/#4071/#4091/#4105/#4232/#4538/#4685/#4693/#4818
    (r"\bholds?\b", "货舱", "玄方城"),           # #466/#704/#712/#855/#988/#1103
    (r"\bholds?\b", "山房", "玄方城"),           # #2046/#2996/#3488
    (r"\bintendants?\b|\bintendance\b", "总督", "州监"),   # #2788/#2879/#2921/#2933
    (r"\bintendants?\b|\bintendance\b", "管家", "州监"),   # #690
    (r"\bintendants?\b|\bintendance\b", "管理员", "州监"),
    (r"\bMoon Festival\b|\bWaking Moon\b|\bwaking moon\b", "中秋节", "朝月会"),   # #814
    (r"\bseals?\b", "海豹", "封印"),             # #2888/#5365
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
#   帐篷=十连 是抽卡术语，但语言讨论语境 tent 是 text 的 ASR 误听；
#   简而言之=这个短片里 是机翻错形，但参考行 in short 本就是"简而言之"。
# 机制：术语被替换后，若参考行(英文)命中下列任一排除正则，回滚该替换并从命中统计移除。
# 结构：{wrong: (right, (排除正则...))}，right 用于回滚（须与所在术语表的 value 一致）。
# 比无条件替换更精准，不依赖人工负例注释。新增歧义词时按此结构追加。
EXCLUDE_CONTEXT = {
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
#   （其指向游戏专名的映射在日语片会误伤本意）；ジラ 前半=自分(自己)、后半抽卡语境=心，
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
    # —— 2026-09-15 沉淀自《JP VTubers Hyped Over the Smol Purple Huntress! Arknights
    #     Endfield Operator Story Typhoeus》ja_auto 谷歌翻译片（86 cue，日语原声）——
    #     本片主角=提弗洛斯（Typhoeus，终末地 1.5「雪凇幽梦」2026-09-02 实装，罗德岛再旅者/荒野猎手；
    #     官方中文见 endfield.hypergryph.com/operator 与官方「干员叙事：提弗洛斯·萨米维格的孩子」）。
    #     日语 ASR 三种读法 ティフォロス/ティフォン/ティボロス 被谷翻成
    #     「Typhoros/提丰/Typholos/提波洛斯」；本表仅 --jpe(终末地日语片) 生效，
    #     不会误伤明日方舟本体干员「提丰」(Typhon，属 AK_TERMS)。
    "提丰": "提弗洛斯", "提波洛斯": "提弗洛斯", "提波罗斯": "提弗洛斯",
    "Typhoros": "提弗洛斯", "Typholos": "提弗洛斯",
    # 注：本片 大の字->"大字符"、LINE(线条)->"LINE"、パタパタ->"小嘴"、かよ->"嘉代"
    #     均属逐句误译（裸键是通用中文词），不进表，走 subfix 侧车整行覆盖。
    "泰弗罗斯": "提弗洛斯",   # 2026-09-23 本片再现谷翻音译形「泰弗罗斯」(#33)，并入统一
}

# (日语参考行正则, 中文错形, 正确)：仅当日语行命中正则、且中文行含错形时才替换
JA_ENDFIELD_CONTEXT = [
    (r"正門|大門", "大门", "星门"),                  # 正門=星门（Cosmic Gate）；"陈"->陈千语 逐 cue 侧车处理，避免子串二次替换
    # --- 2026-09-15 沉淀自《JP VTubers Hyped Over ... Operator Story Typhoeus》ja_auto 谷歌翻译片 ---
    #     官方中文依据：endfield.hypergryph.com 干员叙事《提弗洛斯：萨米维格的孩子》+
    #     1.5「雪凇幽梦」版本说明（雪松林 / 老雪祀 / 安玛 / 冬猎 / 幽林之怒 / 挽弓试炼）。
    #     用 context 而非裸键：「雪祭」「惊人的」都是通用中文词，裸键会误伤正常语境。
    (r"雪祭祀|雪祀", "雪祭", "雪祀"),                # 雪祀=萨米萨满祭司（官方「老雪祀」），ASR 常作「雪祭祀」
    (r"すご|すげえ|すごい", "惊人的", "好厉害"),      # すごい/すげえ 谷翻系统译成"惊人的"（本片 #36/#55）
    (r"雪", "Yuki", "雪"),
    (r"はあ|はぁ|ふぅ", "叹", "唉"),                  # はあ 拟声谷翻成"叹"，仅在日语行为叹息拟声时改"唉"（防误伤"惊叹/感叹"）
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
    # —— 2026-09-22 沉淀：《[명조] 이게 쿠로의 맛인가.. 2주년 PV + 데니아 PV + 3장 5막 에필로그》
    #     韩语原声 + 谷翻中文行（4543 cue）。以下键均逐条对照韩语参考行确认无误后才入表：
    #     卡蒂西亚(카르티시아)=卡提希娅 / 守望者(파수인)=守岸人 / 外骨骼行者(엑소스트라이더)=隧者 /
    #     星触(스타터치)=星炬 / 虚空计量器·空隙计(보이드메터)=虚空计量表 / 丹雅·多尼娅(데니아/되니아)=达妮娅 /
    #     莱罗伊·拉海·罗伊(라하이로이)=拉海洛 / 弗洛雷罗·弗洛拉(플로러로)=弗洛洛 / 莉纳西塔(리나시타)=黎那汐塔 /
    #     兰贾(랑자)=漂泊者 / 残像会议(잔상회)·山城会(잔성회)·全成(전성)=残星会 / 斯塔托赫(스타토치)=星炬。
    #     ⚠ 裸键"流浪者/残酷/著名"是通用中文词（流浪者可能正常语境），禁入表，只能韩语佐证逐 cue 覆盖。
    '卡蒂西亚': '卡提希娅',
    '守望者': '守岸人',
    '外骨骼行者': '隧者',
    '星触学院': '星炬学院',
    '斯塔托赫学院': '星炬学院',
    '虚空计量器': '虚空计量表',
    '空隙计': '虚空计量表',
    '丹雅': '达妮娅',
    '多尼娅': '达妮娅',
    '莱罗伊': '拉海洛',
    '拉海·罗伊': '拉海洛',
    '弗洛雷罗': '弗洛洛',
    '弗洛拉': '弗洛洛',
    '莉纳西塔': '黎那汐塔',
    '兰贾': '漂泊者',
    '残像会议': '残星会',
    '山城会': '残星会',
    '全成': '残星会',
    # —— 2026-09-22 第4轮（检索官方中文后）追加。来源：库洛官网版本说明/百度百科/灰机WIKI/fandom。
    #     西格莉卡(시그리카)=星炬学院学生·罗伊符文共鸣者，官方名"西格莉卡"（本片31处机翻"西格丽卡"）；
    #     阿列夫一(알레프원)=鸣式 Aleph One 官方名"阿列夫一"（残星会资产/容器为达妮娅）；
    #     秘日六席(헬리오틱6)=Heliotix Six，西格莉卡为罗伊族未来"秘日六席"之一，能力称"昭日者"；
    #     苇原(아시노하라)=绯雪(Hiyuki)故乡，官方"苇原"（本片"芦原/芦花"→苇原）。
    #     ⚠ 绯雪(Hiyuki) 的中文错形（日向/日雪/日置/雪女/日向木）均为通用中文词，禁入表，只能韩语佐证逐 cue 覆盖。
    '西格丽卡': '西格莉卡',
    '阿拉夫一号': '阿列夫一',
    '阿列夫一号': '阿列夫一',
    '阿勒夫一号': '阿列夫一',
    '日心6号': '秘日六席',
    '芦原': '苇原',
    '明卓': '鸣潮',
    "深月狐": "心月狐",
    "沈月悠": "心月狐", "沈汝宇": "心月狐", "沈汝雨": "心月狐",
    "沈月悠": "心月狐", "沈汝宇": "心月狐", "沈汝雨": "心月狐",
    "沈月悠": "心月狐", "沈汝宇": "心月狐", "沈汝雨": "心月狐",
    "沈月娥": "心月狐", "沈丽宇": "心月狐", "御乡佐良": "心月狐",
    "沈月娥": "心月狐", "沈丽宇": "心月狐", "御乡佐良": "心月狐",
    "沈月娥": "心月狐", "沈丽宇": "心月狐", "御乡佐良": "心月狐",
    "深月狐犬": "心月狐大人", "深月女性精英": "心月狐大人",
    "深月狐犬": "心月狐大人", "深月女性精英": "心月狐大人",
    "十月狐狸": "心月狐", "十月福克斯": "心月狐", "十月狐": "心月狐",
    "十月狐狸": "心月狐", "十月福克斯": "心月狐", "十月狐": "心月狐",
    "十月狐狸": "心月狐", "十月福克斯": "心月狐", "十月狐": "心月狐",
    "十月赖夫": "心月狐",
    "福克斯星座": "心", "狐狸星座": "心", "狐星座": "心",
    "福克斯星座": "心", "狐狸星座": "心", "狐星座": "心",
    "福克斯星座": "心", "狐狸星座": "心", "狐星座": "心",
    "福克斯星": "狐星",
    "水新落日狐": "守护神心月狐",        # 수오신 시몰 여우（#1157 组合错形）
    "蒙州": "梦州", "蒙珠": "梦州", "蒙乔": "梦州",
    "蒙州": "梦州", "蒙珠": "梦州", "蒙乔": "梦州",
    "蒙州": "梦州", "蒙珠": "梦州", "蒙乔": "梦州",
    "梦主": "梦州", "梦珠": "梦州", "文珠": "梦州",
    "梦主": "梦州", "梦珠": "梦州", "文珠": "梦州",
    "梦主": "梦州", "梦珠": "梦州", "文珠": "梦州",
    "蒙乔城": "梦州城", "蒙珠焕": "梦州焕", "蒙乔万": "梦州焕",
    "蒙乔城": "梦州城", "蒙珠焕": "梦州焕", "蒙乔万": "梦州焕",
    "蒙乔城": "梦州城", "蒙珠焕": "梦州焕", "蒙乔万": "梦州焕",
    "玄邦城": "玄方城", "咸邦城": "玄方城", "贤邦生": "玄方城",
    "玄邦城": "玄方城", "咸邦城": "玄方城", "贤邦生": "玄方城",
    "玄邦城": "玄方城", "咸邦城": "玄方城", "贤邦生": "玄方城",
    "贤芳道": "玄方城", "玄纺织": "玄方城", "玄邦道": "玄方城",
    "贤芳道": "玄方城", "玄纺织": "玄方城", "玄邦道": "玄方城",
    "贤芳道": "玄方城", "玄纺织": "玄方城", "玄邦道": "玄方城",
    "玄邦堡": "玄方城", "贤芳城": "玄方城", "贤芳市": "玄方城",
    "玄邦堡": "玄方城", "贤芳城": "玄方城", "贤芳市": "玄方城",
    "玄邦堡": "玄方城", "贤芳城": "玄方城", "贤芳市": "玄方城",
    "玄房堡": "玄方城", "玄邦": "玄方城", "现代线": "玄方城",
    "玄房堡": "玄方城", "玄邦": "玄方城", "现代线": "玄方城",
    "玄房堡": "玄方城", "玄邦": "玄方城", "现代线": "玄方城",
    "显星": "玄方城",
    "文明盒子": "文明之匣", "文明盒": "文明之匣", "文明之箱": "文明之匣",
    "文明盒子": "文明之匣", "文明盒": "文明之匣", "文明之箱": "文明之匣",
    "文明盒子": "文明之匣", "文明盒": "文明之匣", "文明之箱": "文明之匣",
    "黑客神权": "核心权限",              # 핵심 권한（#258）
    "赞星辉": "残星会",                  # 잔성회（#332）
    "千城会": "残星会",                  # 잔성회（#1464）
    "北平草": "浮萍草",                  # 부평초（#219）
    "利维坦": "利维亚坦",                # 레비아탄（英白拉多，#166）
    "恩德菲尔德": "终末地",              # 엔드필드（#2694）
    "阿洛克拉斯": "阿莱克琉斯",          # 알레오크래스=Alleikhreos（#2749，与 SKILL 终末地专名表同源）
    "新杨班": "新年派对",                # 신년방（#2272）
    "云燕": "云渊",                      # 운연 전쟁=云渊之役（#1319）
    "把肉鞠躬": "鱼儿低头",              # 고기 숙여라（고기=鱼口语，朝月鱼涌口令 #1390/#2702）
    "索拉里达": "索拉里斯",              # 솔라리스（#151/#2790）
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
    ("特蕾迪亚", "酒神"),        # Tradia = Tragodia
    ("可露希尔", "克洛丝"),      # closure = Kroos（抽卡语境）
    ("阿雷迪亚", "arkpedia"),    # Aredia = arkpedia（网站）
    ("夏·新约", "新约能天使"),   # Xia the new covenant
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
    # ---- 2026-09-14 终末地音乐 reaction 片沉淀 ----
    # 片源：《Music Composer Reacts - Alleikhreos Boss Theme (Arknights: Endfield)》
    #   （Everything Fantasy 频道，英语原声 + 谷歌翻译，468 cue；逐 cue 整行覆盖 400 处，
    #    verify 全通过。完整流程见 skill `subtitle-calib-script`。）
    # 官方依据（已检索）：终末地 1.4 最终 BOSS 官方中文＝阿莱克琉斯（千夫长），
    #   主题曲作曲 Crywolf / YMIR、演唱 Crywolf（《众生行记》OST 曲 7 ＝
    #   Somniomancer [null set]，Crywolf，2025-05-04 塞壬唱片-MSR）。
    # 戒律：本片机翻误形绝大部分是**通用中文词**——梦舞者/嗜睡/索曼瑟/歌曼/老板/钥匙/
    #   希米尔/埃米尔/蝙蝠/未成年/通俗圣经/教堂台阶——按硬契约第 4 条**一律不入表**
    #   （会误伤正常语境），只能逐 cue 侧车整行覆盖；下面只收非正常中文词的安全键。
    "冷狼": "Crywolf", "哭狼": "Crywolf",   # crywolf 机翻直译；社区昵称恰为"哭狼"，字幕仍统一保留英文名
    "梦巫师克雷沃尔夫": "Crywolf", "克雷沃尔夫": "Crywolf",
    "我们改变了钥匙": "我们转调了",          # change key 机翻直译（长键，避免误伤"钥匙"本义）
    # ---- 2026-09-21 gacha 争议片《Gacha Games Are Soulless Copies Of Actual Games》沉淀 ----
    # 片源：英语原声 + 谷翻，694 cue（每 cue 恰 2 行：中文 + 英文参考行），主题为
    #   「抽卡游戏(gacha)是否是现实游戏『无灵魂复制品』」的辩论，大量游戏/角色专名。
    # 处理：extract→逐 cue 对着英文参考行整行重写中文→二次检索官方中文后精修；verify+length 全过。
    # 官方依据（均已检索确认）：
    #   Noticefall / Nodusfall = 米哈游新作《源初之结》（类怪物猎人多人共斗 ARPG，Gamescom 2026 首曝，
    #     被指像《艾尔登法环》+《怪物猎人》）；Ananta = 网易《无限大》（Naked Rain）；
    #   Duet Night Abyss(DNA) = 英雄游戏《二重螺旋》（Pan Studio，被指抄袭 Warframe）；
    #   Mighty = 万敌（崩坏：星穹铁道角色，与 Fate 吉尔伽美什立绘撞车引争议）；
    #   Jane Doe = 简·杜（绝区零）；Uncus/Unctus = Eunectes 森蚺（明日方舟萨尔贡重装，盾+斧+机甲）。
    # 戒律：以下键均为**英文专名/特殊串**，作源键安全；替换目标不带书名号（中文行若已用《》包裹会自动衔接）。
    #   ⚠️ DNA / 深空之眼 **不在此表**——"DNA"是通用词（脱氧核糖核酸，本片就有"脱氧核糖核酸"直译）、
    #      "深空之眼"是真实游戏（Aether Gazer）官方名，裸键会误伤正常语境；
    #      它们已通过下方 `REACT_CONTEXT` 参考行佐证机制（英文 \bDNA\b / D Night Abyss 命中才替换）安全入表。
    "Noticefall": "源初之结", "notice fall": "源初之结", "Nodusfall": "源初之结",
    "Ananta": "无限大",
    "Jane Doe": "简·杜",
    "Mighty": "万敌",
    "Uncus": "森蚺", "Unctus": "森蚺",
}
# 用法：python subtitle_calib_merged.py --react <input.srt> --out out.srt
#   --react 与游戏模式互斥；仅套用 REACT_TERMS 统一首中文行（不动英文/参考行）。

# 3.1e reaction 片「参考行佐证」歧义词表（2026-09-21 新增，仅 --react 生效）
# =============================================================
# 与 REACT_TERMS 的区别：REACT_TERMS 是无条件子串替换（适合英文专名键）；
# 这里收的是**歧义中文词**——裸键会误伤正常语境，必须等英文参考行命中正则才替换。
# 结构：[(英文正则, 中文错误形式, 中文正确形式)]，与 CONTEXT_MAP 同构。
# 应用时机：在 REACT_TERMS 替换之后，仅当该 cue 的英文参考行命中正则且中文行含错误形式才替换。
# 2026-09-21 gacha 争议片沉淀（官方依据见 REACT_TERMS 注释块）：
#   DNA = Duet Night Abyss《二重螺旋》——但 "DNA" 是通用词（脱氧核糖核酸，本片就有直译），
#     且 "DNA Tower Fantasy"（二重螺旋+幻塔）也以 DNA 打头，必须英文 \bDNA\b 佐证；
#   「深空之眼」是真实游戏（Aether Gazer）官方名，本片却是 Duet Night Abyss 的 ASR 误听
#     （英文 D Night Abyss = Duet Night Abyss），须英文佐证才敢替换。
REACT_CONTEXT = [
    (r"\bDNA\b", "DNA", "《二重螺旋》"),
    (r"\bDNA\b", "脱氧核糖核酸", "《二重螺旋》"),
    (r"[Dd] ?[Nn]ight ?[Aa]byss", "深空之眼", "《二重螺旋》"),
]
_REACT_CONTEXT_COMPILED = [(re.compile(rx, re.I), wrong, right)
                           for rx, wrong, right in REACT_CONTEXT if wrong and right]

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
    "Fractus": "Fractsidus",
    "YangYang": "Yangyang", "TongNing": "Tongning", "JingRan": "Jingran",
    "YangYang": "Yangyang", "TongNing": "Tongning", "JingRan": "Jingran",
    "YangYang": "Yangyang", "TongNing": "Tongning", "JingRan": "Jingran",
    "tacid discourses": "Tacet Discords", "tacid discourse": "Tacet Discord",
    "tacid discourses": "Tacet Discords", "tacid discourse": "Tacet Discord",
    "tacid discords": "Tacet Discords", "tacid discord": "Tacet Discord",
    "tacid discords": "Tacet Discords", "tacid discord": "Tacet Discord",
    "Hong Lang": "Huanglong",                                   # 瑝珑（与 Hang Long 同组）
    "Shrungfang hold": "Schwanfong Hold", "Shrung fun hold": "Schwanfong Hold",
    "Shrungfang hold": "Schwanfong Hold", "Shrung fun hold": "Schwanfong Hold",
    "Schwan Funk": "Schwanfong", "Schwanf.": "Schwanfong.",     # 玄方碎形（land of Schwanf.）
    "Schwan Funk": "Schwanfong", "Schwanf.": "Schwanfong.",     # 玄方碎形（land of Schwanf.）
    "moving to MJ": "moving to Mengzhou",                       # MJ=Mengzhou 梦州（短键防误伤）
    "Mojo and the": "Mengzhou and the", "to Mango": "to Mengzhou",
    "Mojo and the": "Mengzhou and the", "to Mango": "to Mengzhou",
    "balanaphora": "balanophora",                               # 蛇菰英文生词拼写修正
    "Shind": "Shin",                                            # 心月狐 ASR 吞音
    "Evedropping": "Eavesdropping", "Evedroping": "Eavesdropping",
    "Evedropping": "Eavesdropping", "Evedroping": "Eavesdropping",
    "wibes": "vibes",                                           # 氛围错拼
    "practal": "fractal",                                       # fractal 口胡形（fractal proliferation）
    "Fox Fox shadow": "Fox shadow",                             # ASR 重复 Fox（Nexus Fox Shadow）
    "S Surgeon Rex": "Surgeon Rex",                             # 句首碎词 S
    "those tacit discords": "those Tacet Discords",             # 残象（tacit=tacet 变体）
    "like Shane": "like Sheen",                                 # Shane=Sheen 心月狐（组合键防常见人名误伤）
    "Swimming said": "Suoming said", "adore swimming": "adore Suoming",
    "Swimming said": "Suoming said", "adore swimming": "adore Suoming",
    "get to swimming": "get to Suoming",                        # Swimming=Suoming 锁暝（组合键防游泳语境）
    "Tang Tang Ning": "Tongning",                               # 同宁结巴重复形
    "Tanging": "Tongning",
    "Strongfang's": "Schwanfong's", "Strongfang": "Schwanfong Hold",
    "Strongfang's": "Schwanfong's", "Strongfang": "Schwanfong Hold",
    "Shrung": "Schwan", "fun hold": "fong Hold",                # 跨行碎形 miniature Shrung / fun hold
    "Shrung": "Schwan", "fun hold": "fong Hold",                # 跨行碎形 miniature Shrung / fun hold
    "Schwanfunhold": "Schwanfong Hold",
    "Schwangfunhold's": "Schwanfong Hold's", "Schwangfunhold": "Schwanfong Hold",
    "Schwangfunhold's": "Schwanfong Hold's", "Schwangfunhold": "Schwanfong Hold",
    "Schwangfong": "Schwanfong",
    "Shwanfong Hold": "Schwanfong Hold", "Shwanfang": "Schwanfong",
    "Shwanfong Hold": "Schwanfong Hold", "Shwanfang": "Schwanfong",
    "Schwangfang's": "Schwanfong's", "Schwangfangjo": "Schwanfong",
    "Schwangfang's": "Schwanfong's", "Schwangfangjo": "Schwanfong",
    "Schwang Fong": "Schwanfong",
    "Lor keeper": "Shorekeeper",
    "MJ Joe": "Mengzhou", "Mang Joe": "Mengzhou",
    "MJ Joe": "Mengzhou", "Mang Joe": "Mengzhou",
    "Simakum Nexus": "Simulacrum Nexus", "Sumacum Nexus": "Simulacrum Nexus",
    "Simakum Nexus": "Simulacrum Nexus", "Sumacum Nexus": "Simulacrum Nexus",
    "simakum nexus": "Simulacrum Nexus", "sumacum nexus": "Simulacrum Nexus",
    "simakum nexus": "Simulacrum Nexus", "sumacum nexus": "Simulacrum Nexus",
    "tessid discords": "Tacet Discords", "Tessid Discords": "Tacet Discords",
    "tessid discords": "Tacet Discords", "Tessid Discords": "Tacet Discords",
    "Tessid Discord": "Tacet Discord", "Tasa Discord": "Tacet Discord",
    "Tessid Discord": "Tacet Discord", "Tasa Discord": "Tacet Discord",
    "Tacit discord": "Tacet Discord", "Tacit discords": "Tacet Discords",
    "Tacit discord": "Tacet Discord", "Tacit discords": "Tacet Discords",
    "tacit discords": "Tacet Discords", "those tacit": "those Tacet",
    "tacit discords": "Tacet Discords", "those tacit": "those Tacet",
    "Nintendent": "Intendant",
    "Jingan": "Jingran",
    "Susheen": "Suxin", "susheen": "Suxin",
    "Susheen": "Suxin", "susheen": "Suxin",
    "Wii Moon Festival": "Waking Moon Festival",
    "bang boo": "bamboo", "sheen guide": "Sheen's guidance",
    "bang boo": "bamboo", "sheen guide": "Sheen's guidance",
    "Moonf Fox": "Moon Fox", "moonf fox": "Moon Fox",   # 心月狐英文称号漏 f（8 处，含小写）
    "Moonf Fox": "Moon Fox", "moonf fox": "Moon Fox",   # 心月狐英文称号漏 f（8 处，含小写）
    "Shwanfong": "Schwanfong",                          # 玄方城 ASR 形（注意不收短键 Shwan：Shwan School=玄元境学派保留）
    "Swarming": "Suoming",                              # 锁暝 ASR 误听（swarm 蜂群；大写专名形态，小写普通词不动）
    "Swaming": "Suoming",                               # 锁暝 ASR 误听（少 r 形，#4316 Sister Swaming）
    "Auto Puppets": "Autopuppets", "Auto Puppet": "Autopuppet",
    "Auto Puppets": "Autopuppets", "Auto Puppet": "Autopuppet",
    "auto puppets": "autopuppets", "auto puppet": "autopuppet",  # 机傀官方英文 autopuppet 合写
    "auto puppets": "autopuppets", "auto puppet": "autopuppet",  # 机傀官方英文 autopuppet 合写
    "the attendant ordered": "the Intendant ordered",  # #927 attendant=intendant(州监) ASR 漏音节，组合键防误伤普通 attendant
    "Suming": "Suoming",                                # 锁暝 ASR 形（#1015 Suming and Ching）
    "Chingan": "Jingran",                               # 景燃 ASR 形（#6776，下句自我纠正为 Jingron）
    "Jingron": "Jingran",                               # 景燃 ASR 形（#6779 等）
    "Abiter": "Arbiter",                                # 御者 Arbiter 漏音节（#2088）
    "Aby": "Abby",                                      # 阿布 Abby ASR 形（#5846/#5990 Aby's）
    "Shranong": "Schwanfong",                           # 玄方城 ASR 形（#5677 land of Shranong）
}

# =============================================================
# 5.x 塞尔达传说（Zelda）片源术语表（--zel 模式，2026-09-14 新增）
#   片源：《ZELDA NINTENDO DIRECT!!!! OOT RELEASE DATEEEE WHENN》——英文直播反应录像
#     （英语原声 + 谷歌翻译，1596 cue，逐 cue 整行覆盖，verify 全通过）。
#   本表仅供**未来塞尔达片源**的一键术语校准，与鸣潮/方舟/终末地等表严格隔离，勿混用。
#   官方简体中文译名依据（已联网检索 2026-09-14，任天堂 / 萌娘百科 / 百度百科）：
#     Ocarina of Time＝时之笛；Twilight Princess＝黄昏公主；The Wind Waker＝风之律动
#     （旧俗译“风之杖”，官方简体现为“风之律动”，故收录 风之杖→风之律动）；
#     Majora's Mask＝梅祖拉的假面；Phantom Hourglass＝幻影沙漏；Spirit Tracks＝灵魂轨迹；
#     Breath of the Wild＝旷野之息；Tears of the Kingdom＝王国之泪；
#     Hyrule＝海拉鲁；Triforce＝三角力量；Link＝林克；Zelda＝塞尔达；Ganondorf＝加农多夫；
#     Navi＝娜薇；Kokiri＝科奇里；Kakariko＝卡卡利科；Zora＝卓拉；Goron＝鼓隆族；
#     Koji Kondo＝近藤浩治；Eiji Aonuma＝青沼英二；Shigeru Miyamoto＝宫本茂；
#     Hisashi Fujibayashi＝藤林秀麿；Xenoblade Chronicles＝异度神剑（决定版）。
#   戒律（硬契约第 4 条）：本片机翻的系统性误译绝大多数是**通用中文词**——呼吸/狂野/
#     好吃的食物/伟大的一天/精神·曲目(Spirit tracks)/合并曲等——一律**不入裸键**（必误伤正常
#     语境），只能逐 cue 侧车整行覆盖；下面只收专名级、非正常中文词的安全键，长词优先。
ZELDA_TERMS = {
    # ---- 各作标题：俗译/旧译/机翻误形 -> 官方简体中文 ----
    "暮光公主": "黄昏公主",            # Twilight Princess（谷哥常直译“暮光”）
    "风之杖": "风之律动",              # The Wind Waker 官方简体（旧俗译“风之杖”）
    "风之节拍器": "风之律动",          # Wind Waker 另一种直译
    "穆祖拉": "梅祖拉", "姆祖拉": "梅祖拉", "姆朱拉": "梅祖拉",   # Majora 变体
    "穆休拉": "梅祖拉",                # 繁中“穆修拉”系直落简体的误形
    # ---- 地名 / 族名 / 角色（Hyrule 谷哥高频误作“海拉尔”）----
    "海拉尔": "海拉鲁", "海鲁尔": "海拉鲁",   # Hyrule
    "佐拉": "卓拉",                    # Zora；歧义低，卓拉为官方
    "哥隆": "鼓隆", "郭隆": "鼓隆",    # Goron
    "基里森林": "科奇里森林", "可奇里": "科奇里",   # Kokiri
    "卡卡尔里科": "卡卡利科", "卡卡尔·里科": "卡卡利科",  # Kakariko
    "那比": "娜薇", "纳美人": "娜薇", "纳维": "娜薇",   # Navi（“纳美人”系 Avatar 误入，塞尔达语境＝娜薇）
    # ---- 制作人 / 作曲家（人名 ASR·机翻误形 -> 官方）----
    "近藤浩二": "近藤浩治",            # Koji Kondo
    "宫本猫": "宫本茂",                # Shigeru Miyamoto
    # ---- 同场异业作品 ----
    "泽诺之刃": "异度神剑", "割裂之刃": "异度神剑",   # Xenoblade 机翻直译
}

# =============================================================
# 5.9 英文参考行「ASR 断词/粘连」容错层（2026-09-28 新增）
#
#   问题（用户实测）：英文 ASR 常在**单词内部插空格**——"reson ator"=resonator，
#     "Water ing lace"=Wuthering Waves（断词 + 误听）。谷歌翻译按**字面**直译这些
#     断片，产出中文残渣："浇水蕾丝刚刚在共鸣者展示柜上发布"（正确应为"鸣潮…"）。
#     既有机制挡不住，因为：① 中文残渣是**无穷生成**的，术语表永远列不全；
#     ② CONTEXT_MAP 的英文锚定正则（\bWuthering\b / resonators?）因断词**匹配不上**，
#        所有佐证规则集体失效——这才是根因（事后往中文表补键，挡不住下一部新片）。
#
#   本层只作用于「参考行匹配」这一路（对既有输出零侵入，verify 仍逐字节保结构）：
#     ① EN_ASR_SPLIT_FIXES：人工沉淀的「断词/误听英文形 -> 规范英文」，锚定前先规整；
#        --fix-en 时同时修正英文输出行（与 EN_LINE_TERM_FIXES 同风格，长键优先）。
#     ② _rejoin_known()：通用重组——相邻两段纯字母若拼起来是**已知英文专名**
#        （词表自动取自 ENTITIES 的 en 名 + 两张英文修正表的目标），去掉中间空格。
#        纯断词（reson ator）无需人工补表；误听（Water ing lace）仍须走 ①。
#     ③ _ref_for_match()：①②合体，供 CONTEXT/EXCLUDE 锚定使用；报告里的参考行
#        仍按原样输出（除 --fix-en），保证 verify 结构零改动。
#     ④ scan-split 子命令：扫全片英文行、列出疑似断词候选（只读），便于补 ①。
# =============================================================
EN_ASR_SPLIT_FIXES = {
    # --- 鸣潮：Wuthering Waves 的断词/误听（2026-09-28 用户实测片源）---
    # 实测参考行："Water ing lace just released shin the reson ator showcase,"
    "Water ing lace": "Wuthering Waves",     # Water ing（断词）+ lace（Waves 误听）
    "Watering lace": "Wuthering Waves",
    "Watering Lace": "Wuthering Waves",
    "Wuthering lace": "Wuthering Waves",
    "Watering Ways": "Wuthering Waves",      # 对应既有中文键"浇水方式"（原误置于 ENDFIELD_TERMS）
    "Watering Waves": "Wuthering Waves",
    "Withering Waves": "Wuthering Waves",    # Withering 错拼
    "Weathering Waves": "Wuthering Waves",
    "Wuthering wave": "Wuthering Waves",
    "released shin the": "released in the",  # "shin"=s+in 粘连（存疑，待原片复核）
    # --- 纯断词：resonator 被切成 reson + ator ---
    "reson ator": "resonator",
    "reson ators": "resonators",
    "Reson ator": "Resonator",
    "Reson ators": "Resonators",
}

# ASR 断词可疑"尾巴"片段（右片段命中即视为被切断的单词后缀，供 scan-split 报警）
_ASR_SPLIT_SUFFIXES = frozenset((
    "ing", "ings", "ator", "ators", "tor", "tors", "ers", "er", "ed",
    "ly", "tion", "tions", "sion", "sions", "ance", "ence",
    "able", "ible", "ness", "ment", "ments", "ic", "ical", "ive", "ous",
))
# 常见独立英文词（任一片段本身即完整单词 -> 不报；同时**禁止**进已知词表，
#   防 "We re"->Were、"Sh ing"->Shing 这类把正常词边界误当断词重组）
_ASR_COMMON_WORDS = frozenset((
    "a", "an", "the", "and", "or", "of", "to", "in", "on", "at", "by", "for",
    "with", "from", "is", "are", "was", "were", "be", "been", "it", "its",
    "this", "that", "these", "those", "i", "you", "he", "she", "we", "they",
    "me", "my", "your", "his", "her", "our", "their", "not", "no", "so", "up",
    "out", "all", "one", "two", "new", "now", "day", "way", "man", "men",
    "get", "got", "let", "may", "can", "will", "just", "very", "more", "most",
    "also", "but", "have", "has", "had", "do", "does", "did", "go", "see",
    "say", "like", "love", "good", "bad", "big", "small", "here", "there",
    "what", "when", "how", "why", "who", "which", "than", "then", "them", "us",
    "him", "as", "if", "into", "water", "waves", "wave", "showcase", "time",
    "when", "were", "give", "know", "life", "come", "take", "make", "made",
    "work", "well", "only", "over", "such", "play", "game", "show", "open",
    "next", "last", "long", "high", "free", "full", "down", "back", "away",
    "much", "many", "need", "want", "feel", "look", "seem", "talk", "call",
    "said", "says", "went", "gone", "done", "left", "right", "music", "video",
    "sound", "world", "story", "react", "boss", "final", "level", "first",
    "second", "third", "fourth", "fifth", "chapter", "version", "update",
    "stream", "beautiful", "people", "song", "best", "ever", "thing", "things",
))

_KNOWN_EN_CACHE = None
_KNOWN_EN_MIN_LEN = 5          # 已知词最短长度：过短易被正常词边界污染（were/when/this…）


def _known_en_tokens():
    """已知英文专名词表（小写纯字母 token），惰性构建并缓存。
    来源：ENTITIES 的 en 名 + EN_LINE_TERM_FIXES / EN_ASR_SPLIT_FIXES 的目标值。
    护栏：只收长度 >= _KNOWN_EN_MIN_LEN 且不在 _ASR_COMMON_WORDS 的 token——
    防长句歌名（如 "When We Were the Most Beautiful"）把 were/when/most 等常用词
    混进词表，进而让 _rejoin_known 把正常词边界误判成断词。"""
    global _KNOWN_EN_CACHE
    if _KNOWN_EN_CACHE is not None:
        return _KNOWN_EN_CACHE
    toks = set()

    def _add(s):
        for t in re.findall(r"[A-Za-z]+", s or ""):
            tl = t.lower()
            if len(tl) >= _KNOWN_EN_MIN_LEN and tl not in _ASR_COMMON_WORDS:
                toks.add(tl)

    for e in globals().get("ENTITIES", ()):      # ENTITIES 在本段之后定义，运行时已就绪
        _add(getattr(e, "en", ""))
    for v in EN_LINE_TERM_FIXES.values():
        _add(v)
    for v in EN_ASR_SPLIT_FIXES.values():
        _add(v)
    _KNOWN_EN_CACHE = frozenset(toks)
    return _KNOWN_EN_CACHE


def _rejoin_known(text, known=None):
    """把相邻两段纯字母之间的空格去掉——**仅当**拼起来是已知英文专名。
    纯断词（"reson ator"->"resonator"）自动修复；正常词边界不动。
    护栏：左片段 >=3 字符（挡 "We re"/"Sh ing"），拼接结果须在已知词表内。
    迭代至稳定，可处理三段连续断词。"""
    if not text or " " not in text:
        return text
    known = known if known is not None else _known_en_tokens()
    if not known:
        return text
    parts = re.split(r"([ \t]+)", text)          # 奇数位为空白，保留原结构
    changed = True
    while changed:
        changed = False
        out, i = [], 0
        while i < len(parts):
            if (i + 2 < len(parts)
                    and re.fullmatch(r"[A-Za-z]{3,}", parts[i])
                    and re.fullmatch(r"[A-Za-z]+", parts[i + 2])
                    and (parts[i] + parts[i + 2]).lower() in known):
                out.append(parts[i] + parts[i + 2])   # 吃掉空白 + 右片段
                i += 3
                changed = True
            else:
                out.append(parts[i])
                i += 1
        parts = out
    return "".join(parts)


_SPLIT_FIX_CACHE = None


def _split_fix_pairs():
    """EN_ASR_SPLIT_FIXES 的编译缓存（长键优先 + 键字符集）。"""
    global _SPLIT_FIX_CACHE
    if _SPLIT_FIX_CACHE is None:
        _SPLIT_FIX_CACHE = _compile_map(EN_ASR_SPLIT_FIXES)
    return _SPLIT_FIX_CACHE


def _ref_for_match(ref):
    """锚定匹配专用：先套断词/误听修正表，再通用重组，返回规整后的参考行。
    只用于 CONTEXT/EXCLUDE 的正则匹配与 --fix-en 输出；
    **绝不**改动默认输出里的参考行（结构零改动原则）。"""
    if not ref:
        return ref
    pairs, chars = _split_fix_pairs()
    ref = _replace_report(ref, pairs, chars, {})
    return _rejoin_known(ref)


def _scan_split_line(line, known=None):
    """返回一行里疑似 ASR 断词的候选：[(左片段, 右片段, 拼接, 可自动重组)]。
    左片段须 >=3 字符（与 _rejoin_known 同护栏，挡 "We re"/"Sh ing" 类误报）。"""
    known = known if known is not None else _known_en_tokens()
    hits = []
    for m in re.finditer(r"\b([A-Za-z]{3,})[ \t]+([A-Za-z]{2,})\b", line or ""):
        l, r = m.group(1), m.group(2)
        joined = l + r
        if joined.lower() in known:
            hits.append((l, r, joined, True))        # 拼起来即已知专名 -> 可直接自动重组
            continue
        if l.lower() in _ASR_COMMON_WORDS or r.lower() in _ASR_COMMON_WORDS:
            continue                                 # 任一片段是完整单词 -> 不是断词
        if r.lower() in _ASR_SPLIT_SUFFIXES:
            hits.append((l, r, joined, False))       # 右片段是单词尾巴 -> 疑似断词，待人工确认
    return hits


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
    "akko": "AK_KO_CONTEXT", "ko": "KO_CONTEXT",
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
    """

    def __init__(self, canonical, modes=("bi",), en="", ja="", ko="",
                 category="", variants=(), ctx=(), exclude=(), note=""):
        self.canonical = canonical
        self.modes = tuple(modes)
        self.en, self.ja, self.ko = en, ja, ko
        self.category = category
        self.variants = tuple(variants)
        self.ctx = tuple(ctx)
        self.exclude = tuple(exclude)
        self.note = note

    def __repr__(self):
        return f"Entity({self.canonical!r}, modes={self.modes!r}, variants={len(self.variants)})"


# --- 实体注册表（新沉淀追加于此）---
# 示范条目：变体已存在于扁平表（注册为幂等 no-op），en/ja/ko/category/note
# 是本层新增的对象级元数据。实体覆盖的既有键会在 kb-export 视图中带上这些属性。
ENTITIES = [
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
                (r"脅迫者|評白者", "威胁的人")),
           note="鸣潮主角。日语官方名=漂泊者（ひょうはくしゃ）；ASR 常咬成 脅迫者(きょうはくしゃ)"
                "/評白者/表白者/漂白者/ひ白者。谷翻把 脅迫者 按字面译成 勒索者/威胁者/胁迫者。"
                "戒律：勒索者/威胁者/胁迫者/白先生/白物先生 都是正常中文词，只走日语行锚定 ctx，"
                "绝不进 variants。'百士/百紫' 属白芷（ビクシ），另见该实体。"),
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
    Entity("达妮娅", modes=("ko",), en="Denia", ja="ダーニャ", ko="데니아",
           category="角色/鸣潮",
           variants=("德尼娅", "德妮亚", "丹妮亚", "达妮亚"),
           note="鸣潮 3.3 版本五星角色（热熔/音感仪），星炬学院学生。韩语 데니아；谷翻常作'德尼娅'。"),
    Entity("陆·赫斯", modes=("bi",), en="Luuk Herssen",
           category="角色/星炬学院校医",
           variants=("路克",),
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
           ctx=((r"\bNvidia\b", "英伟达"), (r"\bNvidia\b", "Nvidia")),
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
           variants=("Monier", "莫尼尔"),
           note="星炬学院隧者工学部教授/深空联合研究院工程师（百度百科·琳奈词条）。"
                "Mouier/Mor 变体已在扁平表；本片 #169 Professor Monier、#184 Professor Mona(侧车)。"),
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
           category="组织/鸣潮",
           variants=("Fractsidus", "Fractidus"),
           note="英文残留补录：Fractsidus/Fractidus 英文残留整词留行（'Fraidus' 既有表"
                "已映射为正确英文 Fractsidus，此处不重复登记）。"),
    Entity("琳奈", modes=("bi",), en="Linny / Lenna",
           category="角色",
           variants=("Linn",),
           note="星炬学院预科班学生（百度百科）。扁平表已有 Linny/Lenny/林尼/莱妮丝；"
                "'Linn\\'s'(#736) 为所有格 ASR 残留。"),
    Entity("拉贝尔学部", modes=("bi",), en="Labell College",
           category="地点/星炬学院学部",
           variants=("Rebel Collegeg", "拉贝尔学院"),
           note="星炬学院学部（官方知识库：'经拉贝尔学部判断其频率……'）。"
                "#31 机翻'Rebel Collegeg'音译残留。"),
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
    Entity("梦枢天罗", modes=("bi",), en="Simulacrum Nexus",
           category="地点/新地区",
           variants=("Simakum Nexus", "Sumacum Nexus", "simakum nexus", "sumacum nexus",
                     "Simakum", "Sumacum"),
           note="英文残留补录（第二部片）：Simakum/Sumacum 为 Simulacrum 的 ASR 咬断形，"
                "谷翻留英文整词（#1462/#3266）。"),
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
           variants=("十重器", "十重起", "十重气", "石重契"),
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
    Entity("洛瑟菈", modes=("ko",), en="Lucilla", ja="ルシラ", ko="루실라",
           category="角色/鸣潮",
           variants=("露西拉", "卢西拉", "鲁西拉", "洛瑟拉", "罗瑟菈"),
           note="鸣潮角色（冷凝/记忆宫殿），星炬学院学院长，2026-06 上线。韩语 루실라；"
                "谷翻按音译作'露西拉'，官方中文名为'洛瑟菈'。"),
    Entity("千咲", modes=("ja",), ja="千咲",
           category="角色/鸣潮",
           variants=("チさ", "ちさ", "地さ", "チサ"),
           ctx=((r"千咲|チさ|地さ|千崎|ちさ", "千崎"),
                (r"千咲|チさ|地さ|千崎|ちさ", "地咲")),
           note="鸣潮角色千咲（3.7 复刻）。日语 ASR 作 チさ/ちさ/地さ（じさ/ちさ 混淆），"
                "谷翻给出 千崎/地咲 等错形，统一为 千咲。"),
    Entity("尤诺", modes=("bi",), en="Juno",
           category="角色",
           variants=(
               # --- 中文同音/音近（yóu nuò）---
               "由诺", "犹诺", "油诺", "尤那", "尤娜", "尤糯",
               "尤洛", "尤珞", "游诺", "柚诺", "佑诺",
               # --- 英文 ASR 音近（Juno）---
               "Juno", "Juno's", "Juno`s", "Junno", "Juno!",
               "Jueno", "Juneau", "Junoe", "Junoo", "Juno ",
           ),
           note="鸣潮角色（3.7 复刻池'漫于盈缺时轴'）。官方中文'尤诺'，英文 Juno。"
                "ASR 音近错形：'尤诺'易咬成'由诺/犹诺/油诺/尤那/尤娜/尤糯/尤洛/尤珞/游诺/柚诺/佑诺'；"
                "英文侧 Juno 易咬成 Junno/Jueno/Juneau/Junoe/Junoo。"),
    Entity("清宵", modes=("bi",), en="Qingxiao",
           category="角色/鸣潮3.7",
           ctx=((r"\bSha\b", "Sha"),),
           note="英文残留补录（第二部片）：Sha 为清宵简称（#1016/#1152），只走 ctx。"),
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
           variants=("Monster Siren Records", "MSR", "MSR-MSR", "音角"),
           note="《明日方舟》官方音乐企划 / 虚构唱片公司，鹰角网络旗下。"
                "官方英文 Monster Siren Records（缩写 MSR），社区昵称'音角'。"
                "日/韩服**沿用英文名**（アークナイツ 侧亦作 Monster Siren Records / MSR），"
                "无独立日/韩文名——按单语保留原语言，ja/ko 留空。"
                "官网 monster-siren.hypergryph.com。来源：萌娘百科、Genius MSR 页。"
                "（bi 模式已有参考行锚定 (Monster Siren → 怪物海妖唱片 → 塞壬唱片)，勿重复。）"),
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
    Entity("夏空", modes=("ja",), ja="シャコンヌ",
           category="角色/鸣潮",
           ctx=((r"シャコンヌ", "恰空舞"), (r"シャコンヌ", "恰空")),
           note="鸣潮 5★。日语 シャコンヌ（Ciaccona）；谷翻按音乐术语译成'恰空舞'。"),
    Entity("鸣潮", modes=("ja",), ja="鳴潮",
           category="作品名",
           ctx=((r"名長|名朝|鳴潮", "有名的领袖"), (r"名長|名朝|鳴潮", "著名领袖"),
                (r"名長|名朝|鳴潮", "纳迦"), (r"名長|名朝|鳴潮", "名长"),
                (r"名長|名朝|鳴潮", "著名的领袖")),
           note="作品名。日语 鳴潮(めいちょう) 被 ASR 咬成同音的 名長(めいちょう)，"
                "谷翻直译成'有名的领袖/著名领袖'，或音译'纳迦/名长'。"
                "（'纳迦'出现在 cue 1000 '鸣潮的快速传送是世界第一'。）"),
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
           category="角色/鸣潮",
           variants=("Lor keeper",),
           note="英文残留补录（第二部片 #1192）：Lor keeper 为 The Shorekeeper 的 ASR 漏音形。"),
    Entity("共鸣者", modes=("ja",), ja="共鳴者",
           category="术语/鸣潮",
           ctx=((r"共鳴者|共鳴", "共振者"), (r"共鳴者|共鳴", "共振腔"),
                (r"共鳴者|共鳴", "谐振腔"), (r"共鳴者|共鳴", "谐振器"),
                (r"共鳴者|共鳴", "共鸣器"), (r"共鳴者|共鳴", "同情者")),
           note="鸣潮核心术语，官方中文=共鸣者（Resonator）。谷翻对 共鳴者 的固定错译："
                "共振者/共振腔/谐振腔/共鸣器/同情者。均为普通中文词，只走日语行 ctx。"),
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
    Entity("卡提希娅", modes=("ja",), ja="カルテジア",
           category="角色/鸣潮",
           ctx=((r"カルテジア|カテジア", "笛卡尔西亚"), (r"カルテジア|カテジア", "卡尔特西亚"),
                (r"カルテジア|カテジア", "卡特吉亚"), (r"カルテジア|カテジア", "塔尔提加"),
                (r"カルテジア|カテジア", "卡特迪亚")),
           note="鸣潮 5★。日语 カルテジア；谷翻音译残留 笛卡尔西亚/卡尔特西亚/卡特吉亚/塔尔提加。"
                "（JA_TERMS 另有 '笛卡尔'->卡提希娅 的无条件键，防哲学家笛卡尔误伤。）"),
    # ============================================================
    # 2026-09-27 学习库 confirmed 固化（learned-promote 人工审阅版）
    #   来源：subtitle_learned_kb.json 各机人工校对 confirmed 条目（89 条，
    #   GitHub main 收集分支与本机完全一致，sha256 同源核对）。
    #   甄别戒律：专名/生僻错形才固化进内置表；'明朝/明州/枯萎/骑士/典范/法官/
    #   哨兵/拖车/哀叹/谐振器/漫游者/太恶心了/圆形/图案/溪流/外骨骼/京城/金龙/
    #   露西尔/Nvidia' 等常用词义错位不固化（留学习库运行时注入+反例降级，
    #   详见学习库 bi|<词> 条目）；句子级扩展形态（'谢谢你，鸣潮亚'等）同样不固化。
    # ============================================================
    Entity("吟霖", modes=("bi",), en="Yinlin",
           category="角色/鸣潮",
           ctx=((r"\bYinlin\b", "尹兰"),),
           note="英文残留补录（第二部片 #7265）：谷翻'尹兰'为 Yinlin 音译错形，参考行锚定。"),
    Entity("今汐", modes=("ja",), ja="今汐",
           category="角色/鸣潮/今州",
           ctx=((r"今師|今汐", "今石"), (r"今師|今汐", "今师")),
           note="今州令尹。日语 ASR 常作 今師（きんし）；谷翻作 '今石'（'本周的敬拜成员是今石'）。"),
    Entity("秧秧", modes=("ja",), ja="やんやん",
           category="角色/鸣潮/今州",
           ctx=((r"やんやん|ヤんやん|にゃんやん", "燕燕"),
                (r"やんやん|ヤんやん|にゃんやん", "延雅"),
                (r"やんやん|ヤんやん|にゃんやん", "燕"),
                (r"やんやん|ヤんやん|にゃんやん", "妮艳")),
           note="鸣潮 4★ 今州共鸣者。日语昵称=やんやん；谷翻音译成 燕燕/延雅/Nyanyan/ヤ。"
                "'燕燕'为正常中文词，只走日语行锚定 ctx（本片主播也昵称其为'鹿'）。"),
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
    Entity("鸣潮之波", modes=("bi",),
           category="术语/鸣潮",
           variants=("枯萎之波",),
           note="学习库固化(#908/3500)：Wuthering Waves 错拼/误拆的机翻残留，整串安全。"),
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
           category="地名/鸣潮",
           variants=("Septimont", "Septtoont"),
           note="鸣潮 2.4 地区 Septimont，官方中文=七丘（百度百科/萌娘百科；黎那汐塔下属城邦）。"),
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
    Entity("鸣式", modes=("bi",), en="Threnodian",
           category="术语/鸣潮",
           variants=("Henodian",),
           note="英文残留补录：Threnodian 的 ASR 变体 Henodian。"),
    Entity("玄Paragon", modes=("bi",),
           category="称号/鸣潮2.x",
           variants=("天鹅典范",),
           note="学习库固化(#3022/4027)：'天鹅'=Schwan 音译、'典范'=Paragon 机翻，组合残留。"),
    Entity("玄元境", modes=("bi",),
           category="地点/术语·鸣潮2.x",
           variants=("施瓦努安", "Shwanuan"),
           note="学习库固化(#2069/9876/9888)：Schwanuan 音译残留；Shwanuan 为少 c 的 ASR 形"
                "（2026-10-05 第二部 3.7 片 #653/#655/#1509）。"),
    Entity("玄方城", modes=("bi",), en="Schwanfong Hold",
           category="地名/鸣潮3.7",
           variants=("Strongfang", "Shrungfang", "Shwanfong Hold", "Shwanfang",
                     "Schwangfang's", "Schwangfangjo", "Schwang Fong",
                     "Schwanfunhold", "Schwangfunhold"),
           note="英文残留补录（第二部片）：ASR 把 Schwanfong 咬成 Strongfang/Shrungfang/"
                "Shwanfang/Schwangfang/Schwanfunhold 等，谷翻留英文整词，均生僻裸键安全。"
                "⚠ 'Shrungfang hold'/'Shrung fun hold' 会产生 Hold hold 重复，走 EN_LINE "
                "组合键；'Schwan Funk'/'Schwanf.' 碎形同走 EN_LINE 组合键。"),
    Entity("蜃境", modes=("bi",),
           category="地点/术语",
           variants=("幻界",),
           note="学习库固化(#2315/2325/5263/5866/6580/12255)：mirage 机翻'幻界'归蜃境。"),
    Entity("爱弥斯", modes=("bi",),
           category="角色/鸣潮2.x",
           variants=("艾姆斯",),
           note="学习库固化(#1644/1645/4470)：Amess 音译残留；'伊梅'(Imeth)走学习库 ctx。"),
    Entity("露帕", modes=("ko",), en="Lupa", ja="ルパ", ko="루파",
           category="角色/鸣潮",
           variants=("鲁帕", "卢帕"),
           ctx=((r"루파", "Rupa"), (r"루파", "Lupa")),
           note="鸣潮 2.4 版本（2025-07-03）五星角色，七丘阵营。韩语 루파；谷翻残留'鲁帕/Rupa/Lupa'。"
                "英文 Lupa 走 ctx（防误伤拉丁语 lupa=母狼 / 其它语境）。"),
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
    Entity("残象", modes=("bi",), en="Tacet Discord",
           category="术语/鸣潮",
           variants=("Tessid Discords", "Tessid Discord", "tessid discords",
                     "Tasa Discord", "特莎Discord"),
           ctx=((r"\b[Tt]ac[ei]t\b", "默许"),),
           note="英文残留补录（第二部片）：Tessid/Tasa 为 Tacet 的 ASR 变体，"
                "谷翻'特莎Discord'；'默许'仅在参考行 tacit 佐证下改残象（#5047，discords 跨行）；"
                "'默契的不和/分歧/纷争'等谷翻错形见 CONTEXT_MAP。"),
    Entity("无音区", modes=("ja",), ja="無音区",
           category="术语/鸣潮",
           ctx=((r"無音", "沉默"), (r"無音", "寂静"), (r"無音", "静寂"),
                (r"無音", "无声"), (r"無音", "沉寂")),
           note="鸣潮术语，官方中文=无音区（Tacet Field），残象的诞生区域，伴随'倒悬之海'与"
                "十字星状声痕（灰机wiki）。日语 ASR 作 無音/無恩ク/無恩音，谷翻按字面译成"
                "'沉默/寂静'（本片 cue 83/84/109/290/294/301/308 全是该术语）。"
                "戒律：沉默/寂静是正常中文词，只走日语行锚定 ctx。"),
    Entity("天空海", modes=("ja",), ja="天空海",
           category="术语/鸣潮",
           ctx=((r"天空会|天空海", "天空会"),),
           note="鸣潮现象名，官方中文=天空海（包裹覆盖整个索拉里斯天空的特殊现象，灰机wiki）。"
                "日语 天空海(てんくうかい) 被 ASR 咬成同音的 天空会(てんくうかい)，谷翻照抄'天空会'。"),
    Entity("今州", modes=("bi",), en="Jinzhou",
           category="地名/鸣潮",
           variants=("Ginjo", "Jinjo", "Jinzhou"),
           note="英文残留补录：ASR 把 Jingo 咬成 Ginjo/Jinjo，谷翻留英文 'Jinzhou'。"),
    Entity("瑝珑", modes=("bi",), en="Huanglong",
           category="地名/鸣潮",
           ctx=((r"\bHong Lang\b|\bHuanglong\b", "洪朗"),),
           note="英文残留补录（第二部片 #175）：Hong Lang 为 Huanglong 的 ASR 形，"
                "谷翻'洪朗'，走参考行锚定（正则同时容纳修正后 Huanglong）；英文行走 EN_LINE 组合键。"),
    Entity("数据坞", modes=("ja",), ja="データドッグ",
           category="系统/鸣潮",
           ctx=((r"データドッ?[ッグ]|データドック", "数据狗"),
                (r"データドッ?[ッグ]|データドック", "数据犬")),
           note="鸣潮声骸管理系统，官方中文=数据坞（Data Bank）。日语 データドッグ 被谷翻"
                "按 dog 直译成'数据狗'。'数据狗'非正常中文词，但仍走 ctx 以防万一。"),
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
    Entity("超频", modes=("ja",), ja="オーバークロック",
           category="术语/鸣潮",
           note="鸣潮术语：频率能量异常带来的危险状态（灰机wiki《无音区》提到'超频'）。"
                "本片谷翻已正确输出'超频'，仅登记元数据，无替换。"),
    Entity("终奏技能", modes=("ja",), ja="収走スキル",
           category="术语/鸣潮",
           note="鸣潮技能体系：共鸣技能/共鸣回路/共鸣解放 + 变奏技能/终奏技能（Outro Skill）。"
                "日语 ASR 作 収走スキル(しゅうそう)，谷翻译成'跑步技能/逃跑/收走'。"
                "⚠ 本条只登记元数据、不加规则：'终奏/延奏'的官方中文用字尚未坐实，"
                "本片按'终奏'处理并留待后续片源验证，勿贸然固化为规则。"),
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
    Entity("华亭", modes=("ko",), ko="화정", category="地名/鸣潮",
           ctx=((r"화정", "花亭"), (r"화정을 위해", "和谐")),
           note="梦州华亭（锁暝故乡，官方档案'梦州华亭人'）。谷翻作'花亭/和谐'，走 ctx。"),
    Entity("恶瘴", modes=("bi",), en="Evil Miasma",
           category="术语/灾厄·鸣潮3.7",
           variants=("邪恶瘴气", "Evil Miasma", "evil Miasma"),
           note="华亭故乡灾厄（官方档案'故乡「恶瘴」之厄'），官方中文=恶瘴（ko 模式 악장->恶瘴 已沉淀）。"
                "谷翻'邪恶瘴气'生僻组合裸键安全；戒律：'Miasma' 单独歧义（瘴气普通词）不裸键，"
                "只收带 Evil 词组。"),
    Entity("伏笔", modes=("ko",), ko="떡밥", category="术语",
           ctx=((r"떡밥", "诱饵"),),
           note="떡밥=伏笔/后续钩子（韩语网络语）。谷翻直译成'诱饵'（钓鱼义），走 ctx 锚定。"),
    Entity("天人", modes=("bi",), en="Celestials",
           category="术语/群体·鸣潮3.7",
           ctx=((r"\b[Cc]elestials\b", "天体"),),
           note="玄方/梦州的'天人'群体（与凡人相对），官方中文=天人（ko 模式 천인->天人 已沉淀）。"
                "谷翻按字面把 celestials 出'天体'（天文常用词），必须走参考行锚定，绝不裸键。"
                "⚠ 佐证正则强制复数 celestials（2026-10-05 实测：单数 'celestial bodies "
                "twinkle'=真天体，被误改成'天人'）；指群体的天人英文用复数，故收窄不漏。"
                "canonical'天人'本身无错形裸键。"),
    Entity("正贤", modes=("ko",), ko="정현", category="角色/鸣潮",
           ctx=((r"정현", "郑贤"),),
           note="玄方地界人物 정현（正贤）。谷翻同片混用'正贤/郑贤'，走 ctx 统一为正贤。"),
    Entity("昭明商会", modes=("ko",), ko="소명 상인회", category="组织/鸣潮",
           ctx=((r"소명 상인회", "锁暝商会"),),
           note="昭明商会（穗穗任理事的商会，官方百科'担任昭明商会年轻理事'）。ASR 소명 与 쇠명(锁暝) 同音，"
                "谷翻把 소명 상인회 误作'锁暝商会'，走 ctx 锚定。"),
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
    Entity("车尔尼", modes=("bi",), en="Czerny", category="角色/明日方舟",
           variants=("Chney",),
           note="5★ 驭法铁卫重装（尘影余音活动）。ASR 常把 Czerny 咬成 Chney，'Chney'是英文残留可裸键。"),
    Entity("安多恩", modes=("bi",), en="Andoain", category="角色/明日方舟",
           variants=("Andwin",),
           note="拉特兰'寻路者'领袖（殉道者），吾导先路/众生行记。ASR 常作 Andwin，'Andwin'是英文残留可裸键。"),
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
    Entity("玄方", modes=("bi",), en="Xuan / Schwan",
           category="地名/鸣潮3.7",
           ctx=((r"\bShenfang\b", "申方"),),
           note="英文残留补录（第二部片）：Shenfang 为 Xuanfang/Schwan 的 ASR 音近形，"
                "谷翻'申方'，走参考行锚定。"),
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
           category="称号/鸣潮3.7",
           variants=("Nintendent",),
           note="英文残留补录（第二部片 #4367）：'a Nintendent' 为 an intendant 粘连误写。"),
    Entity("稷廷", modes=("bi",), en="Court of Savantae",
           category="势力/组织·鸣潮3.7",
           variants=("萨凡特宫廷", "Court of Savante", "Savante", "Sante", "Cante"),
           note="旧时代机巧科研组织，官方中文=稷廷（韩语模式 직정->稷廷 已沉淀）。"
                "ASR 变体 Court of Savante/Sante/Cante；谷翻'萨凡特宫廷'生僻组合裸键安全。"),
    Entity("军策府", modes=("bi",), en="Ministry of War",
           category="势力/官署·鸣潮3.7",
           variants=("Ministry of War",),
           ctx=((r"\bMinistry of War\b", "战争部"),),
           note="梦州军事官署，官方中文=军策府。谷翻按字面出'战争部'（普通词组），"
                "走参考行 Ministry of War 锚定；英文整词残留裸键安全。"),
    Entity("朝月会", modes=("bi",), en="Waking Moon Festival",
           category="活动/鸣潮3.7",
           variants=("醒中月节", "舜丰醒中月节", "Wii Moon Festival", "Wii月球节", "清醒月节"),
           note="英文残留补录：Waking Moon Festival 官方中文=朝月会；谷翻生僻错形"
                "'醒中月节/舜丰醒中月节/清醒月节/Wii月球节'；ASR 把 Waking 咬成 Wii。"),
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
           category="物品/鸣潮3.7",
           variants=("Villion lock", "Villion locks", "Vermillion lock", "Vermillion locks"),
           note="英文残留补录：Vermillion→Villion 的 ASR 变体，谷翻留英文整词。"),
    Entity("解形煞", modes=("bi",), en="Form Renders",
           category="敌人/术语·鸣潮3.7",
           variants=("形态渲染器", "forenders"),
           note="玄方篇敌对存在，官方中文=解形煞。ASR 把 Form Renders 咬成 for renters/"
                "forenders；谷翻按字面出'形态渲染器'（render=渲染）生僻组合裸键安全；"
                "英文残留 forenders 生僻裸键，'form renders/for renters' 歧义不裸键。"),
    Entity("玄翎雀", modes=("bi",), en="Xuanling Bird",
           category="生物/鸣潮3.7",
           variants=("Shenling", "Schwrenling"),
           note="英文残留补录：Shrenling 的 ASR 变体 Shenling/Schwrenling。"),
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
    Entity("拉海洛", modes=("bi",), en="Lahai-Roi",
           category="地名/鸣潮",
           variants=("La Hai Roy", "La Hyroy", "La Hairoy", "Lahiroy"),
           note="英文残留补录：Lahai-Roi 的 ASR/谷翻残留 La Hai Roy/La Hyroy/Lahiroy。"),
    Entity("天罗狐影", modes=("bi",), en="Nexus Fox Shadow",
           category="地点/鸣潮3.7",
           variants=("Nexus Fox Shadow", "Fox Shadow"),
           note="英文残留补录：官方中文=天罗狐影（梦枢天罗的巨大狐影）。"),
    Entity("黎那汐塔", modes=("bi",), en="Rinascita",
           category="地名/鸣潮",
           variants=("Rinascita",),
           ctx=((r"\bRena\b", "Rena"),),
           note="鸣潮 2.x 国家 Rinascita，官方中文=黎那汐塔。'Rena' 亦为人名常用拼写，"
                "只走 ctx 参考行锚定。"),
    Entity("维里奈", modes=("bi",), en="Verina",
           category="角色/鸣潮",
           variants=("Verina", "维丽娜"),
           note="英文残留补录（第二部片 #4179）：谷翻'维丽娜'为 Verina 音译错形。"),
    Entity("阿布", modes=("bi",), en="Abby",
           category="角色/鸣潮3.7",
           ctx=((r"\bAbby\b", "Abby"),),
           note="3.7 角色阿布（真名阿布拉克萨斯），英文 ASR 作 Abby；'Abby' 是常见英文名，"
                "只走 ctx 参考行锚定（#2231）。"),
    Entity("菈梵朵玛", modes=("bi", "endo"), en="La Fantoma / La Fantôme",
           category="地名/终末地",
           variants=("La Fantoma", "La Fantôme", "La Fant ome", "LaFantoma",
                    "拉法尔", "幻想城", "拉环朵玛"),
           note="终末地塔卫二文明环带滨海度假城市，环塔商会核心城市，'自由市'。"
                "官方中文=菈梵朵玛（endfield.wiki.gg 多语对照 Chinese=菈梵朵玛；"
                "官方知识库作'拉环朵玛自由市'，两者并存，反应片字幕取 wiki 全条目写法"
                "菈梵朵玛）。⚠ 裸键 'La Fant' 不入表（法语冠词误伤风险），只收完整形态；"
                "主播语境常说 La Fantome=夏日度假城市，与泰拉汐斯塔对应。"),
    Entity("终末地蓬蓬", modes=("bi", "endo"), en="Peng Peng / Endfield Pengpeng",
           category="官号/终末地",
           variants=("蓬蓬干员", "Peng peng", "Peng Peng", "乒乓球", "乒乓",
                    "Ping Pong", "Pingpong"),
           note="《明日方舟：终末地》官方运营/幕后分享账号（微博/B站/知乎同名'终末地蓬蓬'），"
                "发干员采访问答（'蓬蓬采访'系列）、EP下架公告、前瞻精华等幕后内容。"
                "英文 ASR 听成 'Peng Peng'，谷翻常作'乒乓/Ping Pong'；'特别干员问答'=蓬蓬的"
                "干员采访栏目。⚠ 裸键'乒乓'危险（真实乒乓球运动语境），只收组合形态，"
                "单字场景走逐 cue 侧车。"),
]

# ============================================================
# 2026-09-22 音乐曲库 · **有歌词（人声）歌曲**多语对照
#   ⚠ 只收**有人声演唱**的歌（角色印象曲 / 主题曲 / 活动曲 / 合作曲，
#     含游戏内出现过的人声曲与官方 PV 人声曲）；**不收**纯器乐 BGM/OST 伴奏。
#   戒律（用户 2026-09-22 指定）：
#     ① 曲名在四语服常为**各自独立的官方名**（非直译），**有官方外文名才填**；
#     ② **只有单一语种官方名的，不翻译、保留原语言**（en/ja/ko 留空）；
#     ③ 严禁臆造译名；本表只作多语元数据（variants 一律留空，音译错形待片源实测沉淀）。
#   格式：(官方曲名, en, ja, ko)；空串 = 该语种无独立官方名。
#   来源：百度百科「鸣潮」游戏原声、萌娘百科「鸣潮音乐列表/塞壬唱片」、歌词坊 gecifang、
#         觅歌词「鸣潮人声歌曲合集」、巴哈姆特 EP 一览、Wikiwand 鸣潮音乐列表、Shazam MSR。
# ============================================================
_MUSIC_WW = [                       # 鸣潮 · 先约电台 EP（角色印象曲）+ 单曲
    # --- EP0 / 公测 EP ---
    ("Saving Light", "Saving Light", "", ""),
    ("Waking of a World", "Waking of a World", "", ""),
    # --- EP1.x ---
    ("往岁乘霄", "Thawing Fates", "過ぎし乗霄山の歳月", "승소산의 메아리"),
    ("月华如愿", "", "", ""),
    ("未尽之歌", "An Unfinished Song", "未完成の歌", "끝나지 않은 노래"),
    ("一千万种可能", "A Million Possibilities", "", ""),
    # --- EP2.x ---
    ("昼梦盛宴", "Grand Feast Daydream", "昼夢グランドフィースト", "꿈의 카니발"),
    ("ONE", "ONE", "", ""),
    ("Daisy Crown", "Daisy Crown", "", ""),
    ("不羁灵魂之王（虽然是自封）（但包的）",
     "THE KING OF WAYWARD SOULS (SELF PROCLAIMED)(BUT DESTINED)", "", ""),
    ("沉沦幻海", "Elusive Seas", "沈む幻海", "바닷속 환상의 자장가"),
    ("下班？", "", "", ""),
    ("Lulala! Lululala!", "", "", ""),
    ("Against the Tide（逆潮）", "Against the Tide", "", ""),
    ("RUNNING FOR YOUR LIFE（无所遁藏）", "RUNNING FOR YOUR LIFE", "", ""),
    ("彼岸的安魂曲", "Requiem of the Beyond", "彼岸のレクイエム", "피안의 진혼곡"),
    ("Endless Pulse（烈血湍流）", "Endless Pulse", "", ""),
    ("今夜不属于月亮（There's No Moonlight This Night）",
     "There's No Moonlight This Night", "", ""),
    ("远光点（APHELION [Galbrena's Lullaby]）",
     "APHELION [Galbrena's Lullaby]", "", ""),
    ("不辞远", "", "", ""),
    ("破茧之华", "Slashing Bloom", "切り咲く", ""),
    # --- EP3.x ---
    ("Catch Me If You Can", "Catch Me If You Can", "", ""),
    ("Unwritten in the Stars（若能触及群星）", "Unwritten in the Stars", "", ""),
    ("纸飞机", "", "", ""),
    ("Thawing Light（融光）", "Thawing Light", "", ""),
    ("L!!!!ght", "L!!!!ght", "", ""),
    ("坠入虚无（Decensus Ad Nihilum）", "Decensus Ad Nihilum", "", ""),
    ("直到下次再见（Dasvidaniya）", "Dasvidaniya", "", ""),
    ("愿（One More Wish）", "One More Wish", "", ""),
    ("Replay（重映）", "Replay", "", ""),
    ("待春归", "", "", ""),
    # --- 飞行雪绒 EP / 特辑 / 周年 ---
    ("碎花", "", "", ""),
    ("靛青宇宙", "", "", ""),
    ("夏空的歌", "", "", ""),
    ("Everflow", "Everflow", "", ""),
    # --- 单曲（官方发行，有人声）---
    ("Never Let It Go", "Never Let It Go", "", ""),
    ("奔流，因你不息", "", "", ""),
    ("潮骚レゾナンス", "", "潮騒レゾナンス", ""),
    ("Turning Around（余烬重燃）", "Turning Around", "", ""),
    ("Brand New Sky（新世界的天空）", "Brand New Sky", "", ""),
    ("星祝", "", "", ""),
    ("To the Finale（未黯之光）", "To the Finale", "", ""),
    ("Beautiful Tomorrow", "Beautiful Tomorrow", "", ""),
    ("Dawnbreaker", "Dawnbreaker", "", ""),
    ("Deadline Disco（极限迪斯科）", "Deadline Disco", "", ""),
]
_MUSIC_AK = [                       # 明日方舟 · 塞壬唱片（人声曲；多数无官方中文，保留英文）
    ("Grown-up's Paradise", "Grown-up's Paradise", "", ""),
    ("铁花飞", "TIE HUA FEI", "", ""),
    ("Speed of Light", "Speed of Light", "", ""),
    ("Running In The Dark", "Running In The Dark", "", ""),
    ("Everything's Alright", "Everything's Alright", "", ""),
    ("Radiant", "Radiant", "", ""),
    ("Mystic Light Quest", "Mystic Light Quest", "", ""),
    ("浸春芜", "", "", ""),
    ("Bluish Light", "Bluish Light", "", ""),
    ("Little Wish", "Little Wish", "", ""),
    ("Boiling Blood", "Boiling Blood", "", ""),
    ("Renegade", "Renegade", "", ""),
    ("秋绪", "", "", ""),
    ("春弦", "", "", ""),
    ("示岁", "", "", ""),
    ("独行长路", "", "", ""),
    ("故乡的风", "", "", ""),
    ("夏浪", "", "", ""),
    ("尽波澜", "", "", ""),
    ("更阑影", "", "", ""),
    ("观心", "", "", ""),
    ("冬涤", "", "", ""),
    ("从那高地上远眺", "", "", ""),
    ("Ensheath", "Ensheath", "", ""),
    ("Believing", "Believing", "", ""),
    ("Immutable", "Immutable", "", ""),
    ("Miss You", "Miss You", "", ""),
    ("Blade Catcher", "Blade Catcher", "", ""),
    ("Sealed", "Sealed", "", ""),
    ("The Walk", "The Walk", "", ""),
    ("Paper Boat", "Paper Boat", "", ""),
    ("Follow Your Heart", "Follow Your Heart", "", ""),
    ("When We Were the Most Beautiful", "When We Were the Most Beautiful", "", ""),
    ("Across the Wind", "Across the Wind", "", ""),
    ("Ständchen", "Ständchen", "", ""),
    ("Stainless Heart", "Stainless Heart", "", ""),
    ("Spark For Dream", "Spark For Dream", "", ""),
    ("Echoism", "Echoism", "", ""),
    ("Revealing", "Revealing", "", ""),
    ("The After", "The After", "", ""),
    ("Sentenced", "Sentenced", "", ""),
    ("Somniomancer (Null Set)", "Somniomancer (Null Set)", "", ""),
    ("Dormant Craving", "Dormant Craving", "", ""),
    ("A Sweet Rendez-vous", "A Sweet Rendez-vous", "", ""),
    ("碧い瞳の中に（in your blue eyes）", "in your blue eyes", "碧い瞳の中に", ""),
    ("Untitled world", "Untitled world", "", ""),
    ("Alive", "Alive", "", ""),
    ("R.I.P.", "R.I.P.", "", ""),
    ("ACHE in PULS", "ACHE in PULS", "", ""),
    ("Misty Memory", "Misty Memory", "", ""),
    ("冲破穹顶", "", "", ""),
    ("熠曲丰碑", "", "", ""),
    ("时序花圃", "", "", ""),
    ("雾色秘访", "", "", ""),
    ("镜花水月", "", "", ""),
    ("愚人曲", "", "", ""),
    ("赴大荒", "", "", ""),
    ("Vows of the Sea", "Vows of the Sea", "", ""),
    ("Storyteller", "Storyteller", "", ""),
    ("Broken Sun", "Broken Sun", "", ""),
    ("Muse", "Muse", "", ""),
    ("Whistle Stop", "Whistle Stop", "", ""),
    ("未许之地", "", "", ""),
    ("无名策", "", "", ""),
    ("Wanna Know Me?", "Wanna Know Me?", "", ""),
    ("辞岁行", "", "", ""),
    ("反常光谱", "", "", ""),
    ("次生预案", "", "", ""),
    ("无忧梦呓", "", "", ""),
    ("促融共竞", "", "", ""),
]
_MUSIC_ENDO = [                     # 终末地 · 铁痕电台-MSR（人声曲；曲名多为中文，保留原语言）
    ("宜", "", "", ""),
    ("万象将醒", "", "", ""),
    ("闪焰预兆", "", "", ""),
    ("冷烬", "", "", ""),
    ("日晕", "", "", ""),
    ("折光成像", "", "", ""),
    ("回燃", "", "", ""),
    ("最喜欢的一张", "", "", ""),
    ("造物道别", "", "", ""),
    ("像素绘涂", "", "", ""),
    ("寻觅漫步", "", "", ""),
    ("反引力悬浮", "", "", ""),
    ("夕流", "", "", ""),
    ("编织光流", "For Your Name", "", ""),
]
for _songs, _modes, _label in (
        (_MUSIC_WW, ("bi", "react"), "鸣潮·先约电台"),
        (_MUSIC_AK, ("ak", "react"), "明日方舟·塞壬唱片"),
        (_MUSIC_ENDO, ("endo", "react"), "终末地·铁痕电台")):
    for _c, _en, _ja, _ko in _songs:
        ENTITIES.append(Entity(_c, modes=_modes, en=_en, ja=_ja, ko=_ko,
                               category=f"曲目/{_label}",
                               note="有歌词（人声）歌曲。空字段=该语种无独立官方名，"
                                    "按'单语保留原语言'处理，勿臆造译名。"))


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
      1. 变体冲突：同一错形在不同实体/模式映射到不同 canonical；
      2. 级联互含（对象级）：同模式内，甲实体的变体是乙实体 canonical 的子串
         （替换到乙的 canonical 后会被甲的变体二次命中）；
      3. 条件变体冗余：ctx 错形同模式下已是无条件变体（佐证永远不会生效）；
      4. ENTITIES 元数据完整性：缺 en/ja/ko/category/note 的对象级提示。"""
    kb = _kb_view()
    problems, infos = [], []

    # 1. 变体冲突（跨实体，含模式标注）
    seen = {}
    for e in kb.values():
        for v in e["variants"]:
            if v == e["canonical"]:
                continue
            if v in seen and seen[v][0] != e["canonical"] \
                    and set(seen[v][1]) & set(e["modes"]):
                problems.append(
                    f"变体冲突: {v!r} -> {seen[v][0]!r}（{seen[v][1]}）与 "
                    f"{e['canonical']!r}（{e['modes']}）")
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
                        problems.append(
                            f"级联互含[{m}]: 变体 {v!r}（->{other['canonical']!r}）"
                            f"是 {e['canonical']!r} 的子串，替换后可能二次命中")
    # 3. 条件变体冗余
    g = globals()
    for mode, cname in _MODE_CTX_TABLE.items():
        tname = _MODE_TERM_TABLE.get(mode)
        tbl = g.get(tname) or {}
        for rx, wrong, right in (g.get(cname) or []):
            if wrong and right and tbl.get(wrong) == right:
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
            with open(path, "rb") as f:
                kb = json.loads(_decode_any(f.read()))
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
    """learn：投喂 [原始srt + 人工校准srt] 配对，挖掘候选规则并更新学习库。
    v1.11.0：收尾自动导出本次新增 confirmed 条目为增量并上传（FR-2）。"""
    import datetime
    import copy
    sc, oc = _parse_cue_pairs(src), _parse_cue_pairs(calib)
    if len(sc) != len(oc):
        print(f"⚠ cue 数不一致（原 {len(sc)} / 校准 {len(oc)}），按序号交集学习")
    smap, omap = {n: (z, r) for n, z, r in sc}, {n: (z, r) for n, z, r in oc}
    kb = _load_learned_kb(kb_path)
    kb_before = copy.deepcopy(kb)
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
    _sync_export_learn_entries(kb, kb_before, mode)


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
    """learned-reject <错形>：人工否决候选（永不自动应用，保留证据）。
    v1.11.0：否决结果以 tombstone 增量通知其它客户端（FR-2）。"""
    kb = _load_learned_kb(kb_path)
    hit = 0
    modes = []
    for c in kb["candidates"].values():
        if c["wrong"] == word and (not mode or c["mode"] == mode):
            c["status"] = "rejected"
            hit += 1
            if c["mode"] not in modes:
                modes.append(c["mode"])
    if hit:
        _save_learned_kb(kb, kb_path)
        print(f"已否决 {hit} 条候选：{word!r}")
        _sync_export_reject_tombstone(word, modes)
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
      fix_en=True   双语模式下用 EN_ASR_SPLIT_FIXES + EN_LINE_TERM_FIXES 修正英文/参考行（默认不动）。
    参考行锚定（CONTEXT/EXCLUDE）一律先经 _ref_for_match 规整（ASR 断词容错），
    但默认输出的参考行保持原样，只有 fix_en=True 才写回。
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
    elif mode == "zel":         # 塞尔达传说片源（2026-09-14 新增）：ZELDA_TERMS 统一首中文行，独立于其它片源表
        terms = ZELDA_TERMS
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
                            e1 = _ref_for_match(eold)     # 先修 ASR 断词/粘连，再修术语
                            enew = _replace_report(e1, enfix_pairs, enfix_chars, hits)
                            if enew != eold:
                                rows.append((num, eold, enew, eold))
                                out[ti] = enew
                        if kk - 1 > zh_idx:      # 上下文匹配/ERROR 翻译改用修正后参考行
                            ref = out[kk - 1]
                    # 锚定匹配用参考行（断词/误听容错）：输出仍用 ref，结构零改动
                    ref_m = _ref_for_match(ref)
                    if mode == "pgr" and pgr_override and str(num) in pgr_override:
                        # PGR 模式：侧车整行覆盖（校准后中文已是终稿，不再叠加术语表）
                        new = pgr_override[str(num)]
                        if new != old:
                            rows.append((num, old, new, ref))
                            out[zh_idx] = new
                    elif mode == "react":     # 音乐/演唱点评：REACT_TERMS 统一首中文行 + REACT_CONTEXT 参考行佐证歧义词
                        new = _replace_report(old, term_pairs, term_chars, hits)
                        for crx, wrong, right in _REACT_CONTEXT_COMPILED:
                            if wrong in new and crx.search(ref_m):
                                new = new.replace(wrong, right)
                        if new != old:
                            rows.append((num, old, new, ref))
                            out[zh_idx] = new
                    elif mode in ("ko", "wwoc", "pgren", "zel"):  # 韩语/综合游戏/战双英文原声/塞尔达：统一首中文行术语（不动参考行）
                        new = _replace_report(old, term_pairs, term_chars, hits)
                        if new != old:
                            rows.append((num, old, new, ref))
                            out[zh_idx] = new
                    elif mode == "ja":          # 日语原声：JA_TERMS + JA_CONTEXT(日语行佐证) 统一首中文行
                        new = _replace_report(old, term_pairs, term_chars, hits)
                        for crx, wrong, right in _JA_CONTEXT_COMPILED:
                            if wrong in new and crx.search(ref_m):
                                new = new.replace(wrong, right)
                        if new != old:
                            rows.append((num, old, new, ref))
                            out[zh_idx] = new
                    elif mode == "jpe":         # 日语原声·终末地：JA_ENDFIELD_TERMS + 上下文佐证
                        new = _replace_report(old, term_pairs, term_chars, hits)
                        for crx, wrong, right in _JA_ENDFIELD_CONTEXT_COMPILED:
                            if wrong in new and crx.search(ref_m):
                                new = new.replace(wrong, right)
                        if new != old:
                            rows.append((num, old, new, ref))
                            out[zh_idx] = new
                    elif mode == "akko":        # 明日方舟韩语原声：AK_KO_TERMS + AK_KO_CONTEXT(韩语行佐证) 统一首中文行
                        new = _replace_report(old, term_pairs, term_chars, hits)
                        for crx, wrong, right in _AK_KO_CONTEXT_COMPILED:
                            if wrong in new and crx.search(ref_m):
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
                            if wrong in new and crx.search(ref_m):
                                new = new.replace(wrong, right)
                        # 负向排除（EXCLUDE_CONTEXT）：高歧义词被替换后，若参考行命中
                        # 排除正则（如 thank you/written tent 语境），回滚该替换并从命中统计移除
                        for wrong, (right, rxs) in _EXCLUDE_COMPILED.items():
                            if wrong in old and wrong not in new and any(rx.search(ref_m) for rx in rxs):
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


# =============================================================
# 行宽体检（length 子命令，2026-09-14 新增）
#
#   动机：verify 只断言「结构未变」（cue 数/序号/时间轴/参考行/CRLF/BOM），
#   不查行宽；而逐 cue 整行重写（subfix 空 old 覆盖）最容易把中文行写长。
#   本子命令按 A 版「排版线」既有判据把关，两版口径一致：
#   东亚 W/F/A 宽字符计 1.0、半角计 0.5 ⇒ 「32 汉字」等价于「64 英文字符」。
#
#   默认只统计**内容行**（每个 cue 除最后一行参考行外的文本行），参考行
#   只做提示（双语片源的参考行本来就常超宽，混在一起会很吵）；
#   `--all` 把参考行一并计入判定与门禁。
#   超限退出码 1，可直接在流水线里当门禁用。
#   用法：length <a.srt> [b.srt ...] [--all]
# =============================================================

MAX_LINE_ZH = 32            # 内容行上限（汉字当量）
MAX_LINE_EN = 64            # 与 32 汉字等价（半角计 0.5）
MAX_LINE_WIDTH = 32.0


def char_width(ch):
    """东亚宽字符（W/F/A）计 1.0，其余（半角）计 0.5。"""
    return 1.0 if unicodedata.east_asian_width(ch) in ("W", "F", "A") else 0.5


def line_width(s):
    """整行显示宽度（以汉字为单位）。"""
    return sum(char_width(c) for c in s)


def is_line_too_long(s, limit=MAX_LINE_WIDTH):
    return line_width(s) > limit


def _iter_cue_lines(path):
    """产出 (序号, 内容行列表, 参考行)。与 process()/subfix 同一套块判据。"""
    raw = open(path, "rb").read()
    lines = _decode_any(raw).replace("\r\n", "\n").replace("\r", "\n").split("\n")
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
                if texts:
                    yield s, texts[:-1], texts[-1]
                i = kk
                continue
        i += 1


def _cmd_length(paths, show_all=False):
    """length：内容行行宽体检（>MAX_LINE_ZH 汉字当量即超限，退出码 1）。"""
    bad_total = 0
    for path in paths:
        if not os.path.exists(path):
            print(f"[跳过] 文件不存在: {path}")
            continue
        bad, ref_bad, cues = [], [], 0
        widest, ref_widest = (0.0, ""), (0.0, "")
        for num, zh_lines, ref in _iter_cue_lines(path):
            cues += 1
            for t in zh_lines:
                L = line_width(t)
                if L > widest[0]:
                    widest = (L, t)
                if L > MAX_LINE_WIDTH:
                    bad.append((num, L, t))
            L = line_width(ref)
            if L > ref_widest[0]:
                ref_widest = (L, ref)
            if L > MAX_LINE_WIDTH:
                ref_bad.append((num, L, ref))
        print(f"{path}: {cues} cues")
        if bad:
            print(f"  内容行超限 {len(bad)} 处（>{MAX_LINE_ZH} 汉字当量）:")
            for num, L, t in bad[:20]:
                print(f"    #{num} {L:.1f} {t}")
            if len(bad) > 20:
                print(f"    ... 另有 {len(bad) - 20} 处")
        else:
            print("  内容行超限 0 处")
        print(f"  最宽内容行 {widest[0]:.1f}: {widest[1]}")
        if ref_bad:
            tag = "" if show_all else "（提示，不计入门禁；--all 才纳入）"
            print(f"  参考行超限 {len(ref_bad)} 处{tag}:")
            for num, L, t in ref_bad[:10]:
                print(f"    #{num} {L:.1f} {t}")
        bad_total += len(bad) + (len(ref_bad) if show_all else 0)
    if bad_total:
        print(f"LENGTH FAIL：{bad_total} 处超限")
        return 1
    print(f"LENGTH OK：全部在 {MAX_LINE_ZH} 汉字当量内")
    return 0


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


def _iter_ref_lines(path):
    """逐 cue 产出 (序号, 参考行)：双语 SRT 里中文行(首个文本行)以外的文本行。"""
    raw = open(path, "rb").read()
    lines = _decode_any(raw).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    i, n = 0, len(lines)
    while i < n:
        s = lines[i].strip()
        if s.isdigit() and (i == 0 or lines[i - 1].strip() == ""):
            j = i + 1
            if j < n and "-->" in lines[j]:
                kk = j + 1
                while kk < n and lines[kk].strip() != "":
                    kk += 1
                if kk - 1 >= j + 2:              # 存在独立参考行
                    for ti in range(j + 2, kk):
                        yield int(s), lines[ti]
                i = kk
                continue
        i += 1


def _cmd_scan_split(paths, min_cnt=1):
    """scan-split：扫描英文/参考行里的疑似 ASR 断词（只读，不改文件）。
    根因定位用：ASR 在单词内部插空格（"reson ator"/"Water ing lace"）会让
    CONTEXT 英文锚定失效、并让谷翻产出中文残渣。输出候选（片段对 + 频次 + 样例序号），
    人工确认后按  "断词形": "规范英文"  追加进 EN_ASR_SPLIT_FIXES 即生效。"""
    if isinstance(paths, str):
        paths = [paths]
    agg = {}          # (l, r, joined) -> [cnt, [nums], auto]
    for p in paths:
        try:
            for num, line in _iter_ref_lines(p):
                for l, r, joined, auto in _scan_split_line(line):
                    rec = agg.setdefault((l, r, joined), [0, [], auto])
                    rec[0] += 1
                    if len(rec[1]) < 6:
                        rec[1].append(num)
                    rec[2] = rec[2] or auto
        except Exception as e:  # noqa: BLE001  单文件异常不影响其余
            print(f"  ⚠ 跳过 {p}: {e}")
    rows = [(k, v) for k, v in agg.items() if v[0] >= min_cnt]
    if not rows:
        print("未发现疑似 ASR 断词（参考行正常）。")
        return 0
    rows.sort(key=lambda kv: (-kv[1][2], -kv[1][0], kv[0][0]))
    auto_n = sum(1 for _, v in rows if v[2])
    print(f"疑似 ASR 断词候选 {len(rows)} 组（其中拼接即已知专名、可直接自动重组 {auto_n} 组）：")
    for (l, r, joined), (cnt, nums, auto) in rows:
        tag = "可自动重组" if auto else "需人工确认"
        print(f"  {l} + {r}  ->  {joined}   [{tag}]  x{cnt}  例序号: {nums}")
    print("\n确认后把条目追加进 EN_ASR_SPLIT_FIXES（\"断词形\": \"规范英文\"）即自动生效。")
    return 0


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
                   "scan-split", "scansplit", "subfix", "terms-check", "termscheck",
                   "terms", "length",
                   "kb-export", "kb-lookup", "kb-lint",
                   "learn", "learned-show", "learned-promote", "learned-reject",
                   "kb-sync", "kb-push"):
            # length 用退出码当门禁（超限 1），其余子命令返回 None -> 0
            sys.exit(_dispatch_subcommand(sub, argv[1:]) or 0)

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
        elif a == "--zel":
            mode = "zel"; i += 1
        elif a == "--fix-en":
            fix_en = True; i += 1
        elif a == "--kb" and i + 1 < len(args):
            learned_kb = args[i + 1]; i += 2
        elif a == "--mode" and i + 1 < len(args):
            m = args[i + 1].lower()
            mode = "ja" if m in ("ja", "japanese") else ("ko" if m in ("ko", "korean") else ("ak" if m in ("ak", "arknights") else ("zho" if m in ("zho", "zhonly", "zh_only") else ("endo" if m in ("endo", "endfield") else ("zel" if m in ("zel", "zelda", "legend of zelda", "zelda_direct") else "bi")))))
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
    _sync_maybe_auto()          # v1.11.0：校准入口自动拉取+应用增量（幂等，失败静默降级）
    _sync_inject_all()          # 兜底：applied.json 生效条目注入本地表
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
             "react": "音乐/演唱点评 (REACT_TERMS)",
             "zel": "塞尔达传说 (ZELDA_TERMS)"}
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
        elif a in ("--out", "--compare", "--side", "--letters", "--file") and i + 1 < len(args):
            opts[a[2:]] = args[i + 1]; i += 2
        elif a == "--json":
            opts["json"] = True; i += 1
        elif a == "--entities":
            opts["entities"] = True; i += 1
        elif a in ("--kb", "--mode", "--learned") and i + 1 < len(args):
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
    elif sub in ("scan-split", "scansplit"):
        if not pos:
            print("用法: scan-split <a.srt> [b.srt ...] [--min 1]"); return
        return _cmd_scan_split(pos, opts.get("min", 1))
    elif sub == "lint":
        if len(pos) < 2:
            print("用法: lint <cues.tsv> <calib目录|calib_*.tsv>"); return
        _cmd_lint(pos[0], pos[1])
    elif sub == "subfix":
        if len(pos) < 2 or "out" not in opts:
            print("用法: subfix <src.srt> <fix.tsv> --out out.srt [--compare tsv] [--side tsv]"); return
        _cmd_subfix(pos[0], pos[1], opts["out"], opts.get("compare"), opts.get("side"))
    elif sub == "length":
        if not pos:
            print("用法: length <a.srt> [b.srt ...] [--all]"); return 0
        return _cmd_length(pos, show_all=bool(opts.get("all")))
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
    elif sub == "kb-sync":
        _cmd_kb_sync()
    elif sub == "kb-push":
        _cmd_kb_push(learned=opts.get("learned") or opts.get("kb"),
                     file=opts.get("file"))


# =============================================================
# 8. 增量同步通道（v1.11.0：条目级增量日志架构，2026-09-13）
#
#    目标（任务书 v1.11.0）：把同步对象从"文件快照"翻转为"条目级
#    增量日志"；服务端退化为哑存储，合并下沉到本地脚本，AI 不参与合并。
#
#    数据通道布局：
#      远端哑存储（VT_SYNC_ROOT 或 config.sync_root，默认 data/calib_sync_remote/）
#        baseline.json                      折叠基线（schema/seq/meta + entries）
#        archive/                           旧 baseline 与已折叠 inbox 归档
#        inbox/<client_id>/<ts>.jsonl       增量日志（只新建，绝不改写他人文件）
#      本地状态（VT_SYNC_DIR，默认 data/calib_sync/）
#        config.json       client_id / last_seq / last_baseline_seq /
#                          sync_root / maintainers / disabled_keys
#        applied.json      应用生效的条目（键控，(table,mode,key) -> entry）
#        conflict.json     冲突隔离区（永不自动应用）
#        local_log/<client_id>/<ts>.jsonl   本机导出留档（未上传则下次补传）
#        calib_sync.log    全量日志（上传/拉取/合并/拒绝/冲突，含条目 id）
#
#    增量条目格式（FR-1，JSON Lines 一行一个对象）：
#      {"id": uuid, "author": client_uuid, "ts": ISO8601+时区,
#       "op": "upsert|tombstone",
#       "table": "BILINGUAL_TERMS|CONTEXT_MAP|EXCLUDE_CONTEXT|
#                ENTITIES_VARIANT|LEARNED_CANDIDATE",
#       "mode": "bi|ja|jpe|ko|ak|akko|endo|zho|pgren|wwoc|react",
#       "key": 错形, "value": 正形, "supersedes": 被取代条目id|null,
#       "evidence": {"count":..,"cues":[..],"kb_status":..},
#       "trust": "maintainer|observed"(可选), "rx": 正则(仅 CONTEXT/EXCLUDE)}
#    CONTEXT_MAP / EXCLUDE_CONTEXT 条目必须携带 "rx"（参考行佐证正则，
#    可多值）；"supersedes" 用于修正旧错误（不留痕不算完成）。
#
#    合并语义（确定性、幂等，NFR-1/2）：
#      生效集 = baseline.entries ∪ 增量（全局序按 ts+id 字典序；同 key 取
#      ts 最新且非 tombstone 的一条；tombstone 显式删除；supersedes 使被
#      取代条目失效；同 key 不同 value 且无取代关系 -> 冲突隔离区）。
#      应用前三道门（实体注册冲突 / kb-lint / terms-check），不通过则该批
#      增量整批拒绝并记日志。信任分级：author ∈ maintainers 直接应用；
#      普通用户条目应用但标"待观察"；冲突条目永不自动应用。
#
#    子命令（v1.12.1 起仅剩用户侧两个；管理员命令见独立程序 kb_admin.py）：
#      kb-sync            更新：拉取 + 合并 + 应用（校准入口自动执行；幂等）
#      kb-push [--learned 库] [--file 增量.jsonl]
#                         上传增量（learn 收尾、learned-reject 自动调用）
#
#    回滚（NFR-5）：VT_SYNC_MODE=legacy 停用增量（不拉取、不合并、不应用）；
#    条目级可通过 config.disabled_keys 单独禁用；VT_NO_SYNC=1 强制关闭。
#    增量数据全链路仅 json.load，禁止
#    eval/exec/import（安全约束，违反即返工）。
# =============================================================

import uuid as _uuid
import datetime as _dt


def json_load(text):
    """统一 JSON 读取（增量数据全链路仅 json.load，禁止 eval/exec）。"""
    return __import__("json").loads(text)


def json_dumps(obj):
    return __import__("json").dumps(obj, ensure_ascii=False)


_SYNC_TABLES = ("BILINGUAL_TERMS", "CONTEXT_MAP", "EXCLUDE_CONTEXT",
                "ENTITIES_VARIANT", "LEARNED_CANDIDATE")
_SYNC_MODES = ("bi", "ja", "jpe", "ko", "ak", "akko", "endo", "zho",
               "pgren", "wwoc", "react")
_SYNC_MODE_CTX_TABLE = {"bi": "CONTEXT_MAP", "ja": "JA_CONTEXT",
                        "jpe": "JA_ENDFIELD_CONTEXT", "akko": "AK_KO_CONTEXT"}


def _sync_env_mode():
    return os.environ.get("VT_SYNC_MODE", "delta").strip().lower() or "delta"


def _sync_enabled():
    if os.environ.get("VT_NO_SYNC"):
        return False
    return _sync_env_mode() != "legacy"


def _sync_local_dir():
    return os.environ.get("VT_SYNC_DIR") or os.path.join("data", "calib_sync")


def _sync_remote_dir():
    return os.environ.get("VT_SYNC_ROOT") or ""


def _sync_cfg_path():
    return os.path.join(_sync_local_dir(), "config.json")


def _sync_cfg():
    """读取本机同步配置；不存在则生成 client_id（安装时一次）。"""
    cfg = {"client_id": "", "last_seq": "", "last_baseline_seq": 0,
           "sync_root": "", "maintainers": [], "disabled_keys": []}
    p = _sync_cfg_path()
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                cfg.update(json_load(f.read()))
        except Exception:
            pass
    if not cfg.get("client_id"):
        cfg["client_id"] = str(_uuid.uuid4())
        _sync_save_cfg(cfg)
    return cfg


def _sync_save_cfg(cfg):
    os.makedirs(_sync_local_dir(), exist_ok=True)
    with open(_sync_cfg_path(), "w", encoding="utf-8") as f:
        f.write(json_dumps(cfg) + "\n")


def _sync_log(msg):
    """追加一行同步日志（best-effort，绝不因日志失败影响主流程）。"""
    try:
        os.makedirs(_sync_local_dir(), exist_ok=True)
        p = os.path.join(_sync_local_dir(), "calib_sync.log")
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"[{_dt.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")
    except OSError:
        pass


def _sync_root(cfg=None):
    cfg = cfg if cfg is not None else _sync_cfg()
    root = _sync_remote_dir() or cfg.get("sync_root") or ""
    if not root:
        root = os.path.join("data", "calib_sync_remote")
    return root


def _sync_ts():
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="milliseconds")


def _sync_entry(author, table, mode, key, value="", op="upsert",
                supersedes=None, evidence=None, trust=None, rx=None):
    id_src = f"calib|{author}|{table}|{mode}|{key}|{value}"
    if rx is not None:
        id_src += "|" + (rx if isinstance(rx, str) else "|".join(rx))
    e = {"id": str(_uuid.uuid5(_uuid.NAMESPACE_URL, id_src)),
         "author": author, "ts": _sync_ts(), "op": op, "table": table,
         "mode": mode, "key": key, "value": value,
         "supersedes": supersedes or None,
         "evidence": dict(evidence or {})}
    if trust:
        e["trust"] = trust
    if rx is not None:
        e["rx"] = rx
    return e


def _sync_entry_key(e):
    """生效/合并键。CONTEXT_MAP 是多规则共存表：同一 wrong 词在不同 rx
    条件下可映射不同目标，键必须含 rx，否则同词多规则会被误判冲突。"""
    k = (e.get("table"), e.get("mode", ""), e.get("key"))
    if e.get("table") == "CONTEXT_MAP" and e.get("rx") is not None:
        rx = tuple(e["rx"]) if isinstance(e["rx"], list) else e["rx"]
        k = k + (rx,)
    return k


def _sync_validate(e):
    """增量条目 schema 校验（FR-1 字段缺一不可；只读不执行）。"""
    if not isinstance(e, dict):
        return False, "非对象"
    for f in ("id", "author", "ts", "op", "table", "mode", "key", "value",
              "supersedes", "evidence"):
        if f not in e:
            return False, f"缺字段 {f}"
    if not isinstance(e["id"], str) or not e["id"]:
        return False, "id 非法"
    if e["op"] not in ("upsert", "tombstone"):
        return False, f"op 非法: {e['op']!r}"
    if e["table"] not in _SYNC_TABLES:
        return False, f"table 非法: {e['table']!r}"
    if e["mode"] not in _SYNC_MODES:
        return False, f"mode 非法: {e['mode']!r}"
    if not isinstance(e["key"], str) or not e["key"]:
        return False, "key 非法"
    if not isinstance(e["value"], str):
        return False, "value 非法"
    if e["op"] == "upsert" and not e["value"]:
        return False, "upsert 的 value 为空"
    if e["supersedes"] is not None and not isinstance(e["supersedes"], str):
        return False, "supersedes 非法"
    if e["table"] in ("CONTEXT_MAP", "EXCLUDE_CONTEXT") and not e.get("rx"):
        return False, f"{e['table']} 条目缺少 rx 正则"
    if e.get("rx") is not None:
        rx = e["rx"]
        if isinstance(rx, str):
            try:
                re.compile(rx)
            except re.error:
                return False, f"rx 非法正则: {rx!r}"
        elif isinstance(rx, list):
            for r in rx:
                try:
                    re.compile(r)
                except re.error:
                    return False, f"rx 非法正则: {r!r}"
        else:
            return False, "rx 类型非法"
    return True, ""


def _sync_read_jsonl(path, log_prefix="读取"):
    """读取增量文件 -> (条目列表, 畸形行数)。畸形/非 JSON 行只跳过并记日志。"""
    entries, bad = [], 0
    if not os.path.isfile(path):
        return entries, bad
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        for ln, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                e = json_load(line)
            except Exception:
                bad += 1
                _sync_log(f"{log_prefix} {path} 行{ln} 非 JSON，已跳过（安全拦截）")
                continue
            ok, why = _sync_validate(e)
            if not ok:
                bad += 1
                _sync_log(f"{log_prefix} {path} 行{ln} schema 拒绝: {why}")
                continue
            entries.append(e)
    if bad:
        _sync_log(f"{log_prefix} {path} 共 {len(entries)} 条有效 / {bad} 条畸形拒绝")
    return entries, bad


def _sync_write_jsonl(path, entries):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json_dumps(e) + "\n")


def _sync_read_baseline(root):
    """读远端 baseline -> (meta, entries: {key: entry})。缺失返回 ({}, {})。
    seq 存文件顶层，并入 meta 返回（下游统一用 meta.get('seq')）。"""
    p = os.path.join(root, "baseline.json")
    if not os.path.isfile(p):
        return {}, {}
    try:
        with open(p, encoding="utf-8-sig") as f:
            data = json_load(f.read())
    except Exception as e:
        _sync_log(f"baseline 读取失败（{e}），按空基线处理")
        return {}, {}
    entries = {}
    for k, e in (data.get("entries") or {}).items():
        ok, why = _sync_validate(e)
        if not ok:
            _sync_log(f"baseline 条目拒绝: {why}")
            continue
        entries[e["id"]] = e
    meta = dict(data.get("meta") or {})
    if data.get("seq") is not None:
        meta["seq"] = data["seq"]
    return meta, entries


def _sync_write_baseline(root, seq, meta, entries):
    os.makedirs(root, exist_ok=True)
    p = os.path.join(root, "baseline.json")
    data = {"schema": 1, "seq": int(seq),
            "meta": dict(meta or {}), "entries": entries}
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json_dumps(data) + "\n")
    os.replace(tmp, p)


def _sync_inbox_files(root):
    """列出远端全部增量文件 -> [(client_id, ts, path)]，按 ts 字典序。"""
    out = []
    inbox = os.path.join(root, "inbox")
    if not os.path.isdir(inbox):
        return out
    for cid in sorted(os.listdir(inbox)):
        cdir = os.path.join(inbox, cid)
        if not os.path.isdir(cdir):
            continue
        for fn in sorted(os.listdir(cdir)):
            if fn.endswith(".jsonl"):
                ts = fn[:-6]
                if "-" in ts:
                    ts = ts.rsplit("-", 1)[0]   # 去掉唯一后缀，取毫秒前缀
                out.append((cid, ts, os.path.join(cdir, fn)))
    return out


def _sync_flush_local_log(cfg, root):
    """把本机留档中未上传的增量补传（幂等：远端已有同名文件跳过）。"""
    base = os.path.join(_sync_local_dir(), "local_log", cfg["client_id"])
    if not os.path.isdir(base):
        return 0
    sent = 0
    for fn in sorted(os.listdir(base)):
        if not fn.endswith(".jsonl"):
            continue
        dst = os.path.join(root, "inbox", cfg["client_id"], fn)
        if os.path.exists(dst):
            continue
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(os.path.join(base, fn), "rb") as f:
                data = f.read()
            with open(dst, "wb") as f:
                f.write(data)
            sent += 1
            _sync_log(f"补传 {fn} -> inbox/{cfg['client_id']}/")
        except OSError as e:
            _sync_log(f"补传失败（{e}），静默跳过（离线/只读远端）")
            return sent
    if sent:
        _sync_log(f"补传完成：{sent} 个本地留档")
    return sent


def _sync_push_entries(entries, cfg=None):
    """本地留档 + 上传远端 inbox（FR-2：只新建文件，绝不改写他人文件）。
    无远端/断网：静默跳过，本地功能完整可用，记日志。"""
    cfg = cfg if cfg is not None else _sync_cfg()
    if not entries:
        return False
    if not _sync_enabled():
        _sync_log(f"跳过上传（{len(entries)} 条）：同步未启用/legacy 模式")
        return False
    fn = _sync_ts().replace(":", "").replace("+00:00", "") \
        + f"-{_uuid.uuid4().hex[:4]}.jsonl"
    local = os.path.join(_sync_local_dir(), "local_log", cfg["client_id"], fn)
    _sync_write_jsonl(local, entries)
    try:
        local_show = os.path.relpath(local)
    except ValueError:
        local_show = local          # 跨盘符（临时目录在 C:，cwd 在 I:）
    _sync_log(f"本地留档 {len(entries)} 条 -> {local_show}："
              + ";".join(e["id"] for e in entries[:5]))
    root = _sync_root(cfg)
    if not os.path.isdir(root):
        _sync_log("远端不可用，上传静默跳过（留档保留，下次补传）")
        return False
    dst = os.path.join(root, "inbox", cfg["client_id"], fn)
    if os.path.exists(dst):
        return True
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "w", encoding="utf-8") as f:
            for e in entries:
                f.write(json_dumps(e) + "\n")
        _sync_log(f"上传 {len(entries)} 条 -> inbox/{cfg['client_id']}/{fn}"
                  + "；".join(e["id"] for e in entries[:5]))
        return True
    except OSError as e:
        _sync_log(f"上传失败（{e}），静默跳过（断网/只读远端）")
        return False


def _sync_merge(baseline_entries, pending):
    """确定性合并（NFR-1/2 纯函数，同输入必同输出）。

    baseline_entries: {id: entry}；pending: 增量条目列表（已按 ts+id 排序）。
    返回 (applied: {key: entry}, conflicts: {key: [entry...]}, report)。
    幂等键 = 条目 id；同 key 多条全部保留参与裁决：不同 value 且无取代
    关系 -> 冲突隔离（不应用）；单值 -> 取 ts+id 最新；最新为 tombstone
    则整键删除（人工否决优先，不可被覆盖）；supersedes 使被取代条目失效。
    """
    by_id = dict(baseline_entries)
    for e in sorted(pending, key=lambda x: (x["ts"], x["id"])):
        old = by_id.get(e["id"])
        if old is not None and (old["ts"], old["id"]) > (e["ts"], e["id"]):
            continue                      # 旧副本，跳过（幂等）
        by_id[e["id"]] = e
    superseded = {e.get("supersedes") for e in by_id.values()
                  if e.get("supersedes")}
    groups = {}
    for eid, e in by_id.items():
        if eid in superseded:
            continue                      # 被取代：历史可查但不生效
        groups.setdefault(_sync_entry_key(e), []).append(e)
    # 冲突判定仅适用于单值语义表：同 key 不同 value -> 冲突隔离。
    # CONTEXT_MAP/EXCLUDE_CONTEXT 为多规则共存表（同词不同 rx 各存一条），
    # 同键多条取最新，由 _sync_apply 天然聚合。
    single_valued = ("BILINGUAL_TERMS", "ENTITIES_VARIANT", "LEARNED_CANDIDATE")
    applied, conflicts = {}, {}
    for key, es in groups.items():
        es.sort(key=lambda x: (x["ts"], x["id"]))
        if es[-1]["op"] == "tombstone":
            continue                      # 最新裁决为否决：整键删除，不应用
        if key[0] in single_valued:
            vals = {}
            for e in es:
                vals.setdefault(e["value"], e)
            if len(vals) > 1:
                conflicts[key] = es       # 同 key 不同值：冲突隔离，永不自动应用
                continue
        applied[key] = es[-1]
    report = {"total": len(by_id), "applied": len(applied),
              "conflicts": len(conflicts),
              "tombstones": sum(1 for e in by_id.values()
                                if e["op"] == "tombstone" and e["id"] not in superseded),
              "superseded": len(superseded)}
    return applied, conflicts, report


def _sync_gates(applied):
    """三道门（FR-3：不通过则该批增量整批拒绝并记日志）。

    门1 实体注册冲突：同 (table, mode, key) 与本地生效知识（内置表 +
    已应用）映射不同目标；
    门2 kb-lint：变体与既有 ENTITIES canonical 冲突（同 mode 下
    key->value 与已有 Entity 冲突）或目标即键自身；
    门3 terms-check：并入后相关表出现【新增】二次命中隐患。
    返回 (ok, 原因列表)。
    """
    g = globals()
    bad = []
    # 门1：与内置表/已应用冲突
    cur = _sync_current_terms()
    for key, e in applied.items():
        table, mode, k, v = key[0], key[1], e["key"], e["value"]
        if table == "ENTITIES_VARIANT":
            tname = _MODE_TERM_TABLE.get(mode)
            tbl = g.get(tname) or {}
            if tbl.get(k) and tbl[k] != v:
                bad.append(f"门1 {k!r}->{v!r} 与内置表 {tname}[{k}]={tbl[k]!r} 冲突")
            if cur.get(key) and cur[key] != v:
                bad.append(f"门1 {k!r}->{v!r} 与已应用 {cur[key]!r} 冲突")
        elif table == "BILINGUAL_TERMS":
            tbl = g.get("BILINGUAL_TERMS") or {}
            if tbl.get(k) and tbl[k] != v:
                bad.append(f"门1 {k!r}->{v!r} 与内置 BILINGUAL_TERMS 冲突")
    # 门2：目标合法性
    for key, e in applied.items():
        k, v = e["key"], e["value"]
        if v == k:
            bad.append(f"门2 恒等键 {k!r}->{v!r}")
        if "\n" in v or "\r" in v:
            bad.append(f"门2 目标含换行: {k!r}")
    # 门3：terms-check 新增隐患（并入前 vs 并入后）
    base_haz = _sync_hazard_keys()
    for key, e in applied.items():
        table, mode, k, v = key[0], key[1], e["key"], e["value"]
        tname = None
        if table in ("ENTITIES_VARIANT", "BILINGUAL_TERMS"):
            tname = (_MODE_TERM_TABLE.get(mode) if table == "ENTITIES_VARIANT"
                     else "BILINGUAL_TERMS")
        elif table in _SYNC_MODE_CTX_TABLE.values():
            continue
        if not tname:
            continue
        tbl = dict(g.get(tname) or {})
        tbl[k] = v
        newhaz = [h for h in _check_term_hazards(tbl)
                  if h not in base_haz.get(tname, ())]
        for h in newhaz:
            bad.append(f"门3 {tname} 新增二次命中隐患: {h[0]!r} 命中 {h[1]!r} 结果 {h[2]!r}")
    if bad:
        _sync_log("三道门拒绝该批增量：" + "；".join(bad[:8]))
        return False, bad
    return True, []


def _sync_current_terms():
    """当前已应用的生效值：{key: value}（applied.json 视图）。"""
    out = {}
    p = os.path.join(_sync_local_dir(), "applied.json")
    if os.path.isfile(p):
        try:
            with open(p, encoding="utf-8-sig") as f:
                data = json_load(f.read())
            for k, e in (data.get("entries") or {}).items():
                out[tuple(k.split("\x1f"))] = e["value"]
        except Exception:
            pass
    return out


def _sync_hazard_keys():
    """当前各术语表的二次命中隐患（用于对比新增）。"""
    g = globals()
    out = {}
    for n, t in g.items():
        if n.endswith("TERMS") and isinstance(t, dict) and t:
            out[n] = tuple(_check_term_hazards(t))
    return out


def _sync_apply(applied):
    """应用生效集：写 applied.json + 注入 globals() 扁平表（键控，只 json）。"""
    p = os.path.join(_sync_local_dir(), "applied.json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    keyed = {("\x1f".join(k)): v for k, v in applied.items()}
    with open(p, "w", encoding="utf-8") as f:
        f.write(json_dumps({"schema": 1, "entries": keyed}) + "\n")
    g = globals()
    n_terms = n_ctx = n_kb = 0
    for key, e in applied.items():
        table, mode, k, v = key[0], key[1], e["key"], e["value"]
        if table == "ENTITIES_VARIANT":
            tname = _MODE_TERM_TABLE.get(mode)
            if tname and isinstance(g.get(tname), dict):
                if g[tname].get(k) != v:
                    g[tname][k] = v
                    n_terms += 1
        elif table == "BILINGUAL_TERMS":
            if isinstance(g.get("BILINGUAL_TERMS"), dict) \
                    and g["BILINGUAL_TERMS"].get(k) != v:
                g["BILINGUAL_TERMS"][k] = v
                n_terms += 1
        elif table == "CONTEXT_MAP":
            cname = _SYNC_MODE_CTX_TABLE.get(mode) or "CONTEXT_MAP"
            lst = g.get(cname)
            if isinstance(lst, list):
                rxs = e["rx"] if isinstance(e.get("rx"), list) else [e.get("rx")]
                for rx in rxs:
                    row = (rx, k, v)
                    if row not in lst:
                        lst.append(row)
                        n_ctx += 1
        elif table == "EXCLUDE_CONTEXT":
            exc = g.get("EXCLUDE_CONTEXT")
            if isinstance(exc, dict):
                rxs = e["rx"] if isinstance(e.get("rx"), list) else [e.get("rx")]
                old = exc.get(k)
                if old:
                    right, rr = old
                    exc[k] = (right, tuple(rr) + tuple(r for r in rxs if r not in rr))
                else:
                    exc[k] = (v, tuple(rxs))
                n_ctx += 1
        elif table == "LEARNED_CANDIDATE":
            n_kb += _sync_apply_learned_candidate(mode, k, v, e)
    if n_terms or n_ctx:
        _rebuild_context_caches()
    _sync_log(f"应用 {len(applied)} 条（terms {n_terms} / ctx {n_ctx} / 学习库 {n_kb}）")
    return n_terms + n_ctx + n_kb


def _sync_apply_learned_candidate(mode, wrong, right, e):
    """LEARNED_CANDIDATE -> 学习库 confirmed 候选（键 "模式|错形"，自然对接
    校准运行时的 learned 注入）。"""
    ev = e.get("evidence") or {}
    kb_path = (os.environ.get("VT_SYNC_KB") or "").strip() or LEARNED_KB_DEFAULT
    kb = _load_learned_kb(kb_path)
    k = f"{mode}|{wrong}"
    c = kb["candidates"].get(k)
    if c is not None and (c.get("status") == "rejected"
                          or (c.get("right") and c["right"] != right)):
        return 0                        # 本地已有裁决/冲突，不覆盖
    import datetime as _dt
    today = _dt.date.today().isoformat()
    c = {"wrong": wrong, "right": right, "mode": mode,
         "count": int(ev.get("count") or 1), "uncorrected": 0,
         "status": "confirmed", "cues": list(ev.get("cues") or [])[:20],
         "samples": [], "ref_tokens": {}, "unc_ref_tokens": {},
         "first": today, "last": today, "alts": {},
         "sync": True}
    kb["candidates"][k] = c
    _save_learned_kb(kb, kb_path)
    return 1


def _sync_write_conflicts(conflicts):
    p = os.path.join(_sync_local_dir(), "conflict.json")
    os.makedirs(os.path.dirname(p), exist_ok=True)
    data = {"schema": 1,
            "conflicts": {"\x1f".join(k): v for k, v in conflicts.items()}}
    with open(p, "w", encoding="utf-8") as f:
        f.write(json_dumps(data) + "\n")
    for k, es in conflicts.items():
        _sync_log(f"冲突隔离 {k}: " + ";".join(
            f"{e['id']}({e['author']}@{e['ts'][:19]})={e['value']!r}" for e in es))


def _cmd_kb_sync(quiet=False):
    """kb-sync：拉取 + 合并 + 三道门 + 信任分级应用（FR-3）。幂等。"""
    if not _sync_enabled():
        if not quiet:
            print("同步未启用（VT_SYNC_MODE=legacy 或 VT_NO_SYNC），跳过 kb-sync")
        return False
    cfg = _sync_cfg()
    root = _sync_root(cfg)
    if not os.path.isdir(root):
        if not quiet:
            print("远端不可用（离线），同步静默跳过")
        _sync_log("kb-sync 跳过：远端不可用")
        return False
    _sync_flush_local_log(cfg, root)
    meta, base_entries = _sync_read_baseline(root)
    files = _sync_inbox_files(root)
    # 全量重放（不按水位线过滤）：生效集 = baseline ∪ 全部增量，确定性合并，
    # id 幂等保证重复拉取结果一致（NFR-1/2）；水位线仅作状态展示/日志。
    pending = []
    for cid, ts, path in files:
        es, _bad = _sync_read_jsonl(path, "拉取")
        pending.extend(es)
    pending.sort(key=lambda x: (x["ts"], x["id"]))
    applied, conflicts, report = _sync_merge(base_entries, pending)
    # 三道门只针对"本次增量引入"的条目：baseline 是管理员已折叠的权威，直通
    new_keys = {_sync_entry_key(e) for e in pending}
    new_applied = {k: v for k, v in applied.items() if k in new_keys}
    ok, reasons = _sync_gates(new_applied)
    if not ok:
        print(f"三道门拒绝该批增量（{len(pending)} 条），水位线不推进：{reasons[0]}")
        return False
    # NFR-5 条目级禁用：disabled_keys 中的键不应用
    dis = {tuple(x) for x in (cfg.get("disabled_keys") or [])}
    if dis:
        applied = {k: v for k, v in applied.items() if k not in dis}
    # 信任分级标注（维护者直接应用；普通用户标待观察——均应用，仅日志区分）
    maint = set(cfg.get("maintainers") or [])
    for e in applied.values():
        if e.get("author") in maint or e.get("trust") == "maintainer":
            e["trust"] = "maintainer"
        else:
            e["trust"] = "observed"
    n_applied = _sync_apply(applied)
    if conflicts:
        _sync_write_conflicts(conflicts)
    cfg["last_seq"] = files[-1][1] if files else cfg.get("last_seq", "")
    cfg["last_baseline_seq"] = int(meta.get("seq") or 0)
    _sync_save_cfg(cfg)
    _sync_log(f"kb-sync 完成：baseline seq={meta.get('seq')} 增量 {len(pending)} 条 "
              f"（{len(files)} 文件），应用 {len(applied)}，"
              f"冲突 {report['conflicts']}，tombstone {report['tombstones']}，"
              f"superseded {report['superseded']}")
    if not quiet:
        print(f"kb-sync：应用 {n_applied} 条 / 冲突隔离 {len(conflicts)} 条 / "
              f"水位线 {cfg['last_seq'] or '（无）'}")
        if conflicts:
            print("  冲突条目已进隔离区（conflict.json），永不自动应用")
    return True


def _cmd_kb_push(learned=None, file=None):
    """kb-push：把学习库 confirmed 候选或指定增量文件导出并上传（FR-2）。
    候选导出用扩展形态（_learn_extended），保证增量是完整词元而非最小片段。

    v1.12.1「只上传当前增量」：候选条目 id 是
    (作者,表,模式,键,值) 的确定性哈希，本机用 pushed_ids.json 台账记录
    已成功上传的 id，重复导出时跳过——退出/手动触发的整库导出因此只补传
    「没传过的」条目；远端不可用时不记账，下次再传。"""
    cfg = _sync_cfg()
    entries = []
    ledger_path = os.path.join(_sync_local_dir(), "pushed_ids.json")
    try:
        with open(ledger_path, encoding="utf-8") as f:
            ledger = set(json_load(f.read()) or [])
    except (OSError, ValueError):
        ledger = set()
    n_skipped = 0
    if learned:
        kb = _load_learned_kb(learned)
        for c in kb.get("candidates", {}).values():
            if c.get("status") == "confirmed" and not c.get("conflict"):
                w, r = _learn_extended(c)
                e = _sync_entry(
                    cfg["client_id"], "LEARNED_CANDIDATE", c.get("mode", "bi"),
                    w, r,
                    evidence={"count": c.get("count", 1),
                              "cues": list(c.get("cues") or [])[:20],
                              "kb_status": c.get("status", "confirmed")})
                if e["id"] in ledger:
                    n_skipped += 1
                    continue
                entries.append(e)
    if file:
        es, bad = _sync_read_jsonl(file, "kb-push")
        entries.extend(es)
    if not entries:
        print(f"没有需要上传的增量"
              + (f"（{n_skipped} 条此前已上传，跳过）" if n_skipped else "（学习库无新 confirmed 候选）"))
        return False
    ok = _sync_push_entries(entries, cfg)
    if ok:
        ledger.update(e["id"] for e in entries)
        try:
            os.makedirs(_sync_local_dir(), exist_ok=True)
            with open(ledger_path, "w", encoding="utf-8") as f:
                f.write(json_dumps(sorted(ledger)) + "\n")
        except OSError:
            pass
    print(f"kb-push：上传 {len(entries)} 条"
          + (f"（另 {n_skipped} 条已上传过，跳过）" if n_skipped else "")
          + ("（留档 + 上传）" if ok else "（远端不可用，仅本机留档，下次补传）"))
    return ok


def _sync_export_learn_entries(kb, kb_before, mode):
    """learn 收尾（FR-2）：本次新增/变更的 confirmed 候选导出为增量并上传。
    导出扩展形态（_learn_extended），保证增量是完整词元而非最小片段。"""
    cfg = _sync_cfg()
    before = (kb_before or {}).get("candidates", {})
    entries = []
    for k, c in kb.get("candidates", {}).items():
        if c.get("mode") != mode or c.get("status") != "confirmed" \
                or c.get("conflict"):
            continue
        old = before.get(k)
        if old and old.get("status") == "confirmed" \
                and old.get("right") == c.get("right"):
            continue                    # 非本次新增/变更
        w, r = _learn_extended(c)
        entries.append(_sync_entry(
            cfg["client_id"], "LEARNED_CANDIDATE", mode, w, r,
            evidence={"count": c.get("count", 1),
                      "cues": list(c.get("cues") or [])[:20],
                      "kb_status": c.get("status", "confirmed")}))
    if entries:
        _sync_push_entries(entries, cfg)
        _sync_log(f"learn 收尾导出 {len(entries)} 条 confirmed 增量")
    return len(entries)


def _sync_export_reject_tombstone(word, modes):
    """learned-reject（FR-2）：人工否决 = tombstone 增量，通知其它客户端。"""
    cfg = _sync_cfg()
    entries = [_sync_entry(cfg["client_id"], "LEARNED_CANDIDATE", m, word, "",
                           op="tombstone",
                           evidence={"kb_status": "rejected"})
               for m in modes]
    if entries:
        _sync_push_entries(entries, cfg)
    return len(entries)


def _sync_maybe_auto():
    """校准入口自动同步（v1.11.0）：delta 模式且远端可用时拉取+应用。
    任何失败都静默降级，绝不影响校准主流程（离线/legacy 同 v1.10.7）。"""
    if not _sync_enabled():
        return False
    try:
        return _cmd_kb_sync(quiet=True)
    except Exception as e:  # noqa: BLE001
        _sync_log(f"自动同步异常已静默降级：{e}")
        return False


def _sync_inject_all():
    """把 applied.json 中生效条目注入本地表（校准运行时兜底；kb-sync 已注入）。"""
    ap = os.path.join(_sync_local_dir(), "applied.json")
    if not os.path.isfile(ap):
        return 0
    try:
        with open(ap, encoding="utf-8-sig") as f:
            data = json_load(f.read())
    except Exception:
        return 0
    applied = {}
    for k, v in (data.get("entries") or {}).items():
        applied[tuple(k.split("\x1f"))] = v
    return _sync_apply(applied)


if __name__ == "__main__":
    main_argv()
