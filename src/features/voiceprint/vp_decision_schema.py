# -*- coding: utf-8 -*-
# @version 3.2.5
"""声纹筛选结构化决策 Schema v2（业务层，WP3 part 2）。

三层 Schema 版本**并存、互不混用**（谁的数据谁声明版本）：

  ============  ==========================  =================================
  层            版本串                      归属
  ============  ==========================  =================================
  协议信封      ``vt.decision.v1``          tools/decision_client.py（WP3
                                            part 1，本模块不重复定义口径）
  R0 影子（史） ``vt.voiceprint.shadow.v1`` voiceprint_decision 旧版影子路由
                                            （v1 三值优先级词汇，历史保留）
  业务筛选      ``vt.voiceprint.filter.v2`` **本模块**（当前 5 问/cue 版）
  ============  ==========================  =================================

为什么业务层单独升版：协议信封关心「state+questions 能不能发、答案是否合法」，
业务层关心「字段叫什么、数值是什么口径、route 有哪些合法值」。两者变更节奏
不同——凭据/端点改造不应牵动业务字段，业务加字段也不该强迫协议层跟着动。

**变更纪律**（附录 A「数值字段必须附带明确业务口径」的落地）：

  1. criteria 或字段业务口径发生任何变更 → bump :data:`SCHEMA_VERSION`；
  2. 升版后回到影子模式重新评估（不直接进 assist/auto）；
  3. 版本随请求 state 与筛选报告快照（summary["schema_version"]）落盘，
     保证任何指标变化可复现、可追踪。

**5 问/cue**（附录 A.1 筛选 Schema，每请求 cue 数 × 5 ≤ 客户端上限 16）：

  1. ``content_role``  choice —— 文本内容角色；**只识别文本角色，不判声音身份**；
  2. ``evidence_conflict``  noul —— P(yes) 越高表示文本/ASR 标签与声学证据
     越冲突；高值**只标冲突**，不得仅凭文本覆盖声学证据；
  3. ``cluster_split_needed``  noul —— 当前簇是否可能需要拆分；触发**局部**
     重算建议，不代表全量删除；
  4. ``route``  choice —— keep / drop / review / cannot_determine；
     ``cannot_determine`` 一律待人工复核；R0 只记录，R1 只建议，R2 按
     「已验收场景白名单」有限自动执行；
  5. ``evidence_quality``  score —— 4 级有序 criteria（score 0..3），展示级
     = score + 2（即 2..5 级）；低分样本始终进入待复核。

**路由约束（附录 A.3，R1/R2 共用）**：

  * 低置信或概率分散 → 待复核，**不丢弃**；
  * 与硬规则（本地阈值三分支）冲突 → 硬规则优先；
  * 与声学证据冲突 → 不得仅凭文本改判；
  * 请求失败 → 本批退回原规则；连续 N 批失败 → 跳过剩余（不扩大自动化）。
"""
from __future__ import annotations

#: 业务层版本（本模块当前）。criteria/字段语义变更时必须 bump 并回影子评估。
SCHEMA_VERSION = "vt.voiceprint.filter.v2"
#: R0 历史：v1 影子路由（三值优先级词汇）的业务版本，仅为历史报告/审计保留。
LEGACY_SHADOW_VERSION = "vt.voiceprint.shadow.v1"
#: 协议信封版本（tools/decision_client.SCHEMA_VERSION 的同值快照，仅供展示；
#: 口径以 part 1 模块为准，本常量不参与任何校验）。
PROTOCOL_ENVELOPE_VERSION = "vt.decision.v1"

#: 每条 cue 的问题数（5 问）。
QUESTIONS_PER_CUE = 5
#: 每请求 cue 数上限：5 问 × 3 条 = 15 ≤ 客户端单请求 16 问。
#: decision_batch_size 的 v2 语义就是「每请求 cue 数上限」，默认值取它。
MAX_CUES_PER_REQUEST = 3

#: route 四值（v2 业务路由词汇）。
#: v1 的 routine_review / priority_manual / insufficient_evidence 是
#: 「复核优先级」词汇（voiceprint_decision.ROUTES，历史保留）；v2 的 route
#: 直接对齐本地 verdict 三值 + 一个显式「判不了」出口。
ROUTE_OPTIONS = {
    "keep": "建议判为主播（字幕保留）",
    "drop": "建议判为非主播（字幕丢弃）",
    "review": "建议保留待人工复核",
    "cannot_determine": "证据不足无法判断；一律转人工复核，不得自动执行",
}

#: content_role 四值：只识别**文本**角色，不判定声音身份。
CONTENT_ROLE_OPTIONS = {
    "host_commentary": "主播解说/口播/对镜头说话",
    "game_dialogue": "游戏内角色对白或配音",
    "official_narration": "官方旁白/系统提示/教程字幕",
    "other": "其他（歌词、杂项、无法归类）",
}

#: evidence_conflict / cluster_split_needed 的 noul P(yes) 判定线：
#: ≥ 此值视为「存在冲突/需要拆分」（只做标记与降级，从不直接采纳为改判依据）。
CONFLICT_NOUL_THRESHOLD = 0.5

#: evidence_quality：**4 级有序 criteria**（score 0..3，legend 从 0 起）。
#: 展示级 = score + 2，对齐附录 A.1「2–5 级证据充分程度」的口径；
#: 客户端协议要求 score ∈ [0, len(criteria)-1]，legend 为必填映射。
EVIDENCE_QUALITY_LEVELS = [
    "2 级：证据严重不足（无有效分数且缺邻接上下文，只能靠猜测）",
    "3 级：证据不足（分数贴边、簇证据互相矛盾或邻接状态打架）",
    "4 级：基本充分（声学分差与文本角色大体一致，存在小缺口）",
    "5 级：充分（分差、簇一致性、文本角色相互印证）",
]
#: 展示级下界（对齐「2–5 级」口径；score 0 ↔ 级 2）。
QUALITY_LEVEL_MIN = 2
#: R2 自动执行要求的最低展示级（级 4 ⇔ 原始 score ≥ 2）。
QUALITY_AUTO_MIN_LEVEL = 4

#: R1/R2 默认门禁常量（G0 门禁数据集就绪前为**草案值**，冻结前不得调松）：
#: R2 自动执行要求的最低模型置信度（用户裁决：高置信 ≥98%）。
AUTO_CONF_T1 = 0.98
#: R2 自动执行要求的最低 P(route)（路由概率）。
AUTO_PROB_P1 = 0.90
#: 「概率分散」判定线：route 概率最大值低于它视为分散 → 待复核不丢弃。
ASSIST_TOP_PROB_MIN = 0.60
#: R1「低置信」判定线：confidence 低于它 → 建议降级为 review。
ASSIST_CONF_MIN = 0.60
#: R1 连续失败批数上限：连续 N 批请求失败后跳过剩余（不扩大自动化）。
ASSIST_MAX_FAILED_BATCHES = 2

#: v2 state.item 必备字段（相对 v1：start/end→start_ms/end_ms、reason→
#: local_reason、local_score→target_score、previous/next→prev_*/next_*；
#: 其余为新增）。验收口径：items 的键集 ⊇ 此集合。
REQUIRED_ITEM_FIELDS = frozenset({
    "question", "num", "start_ms", "end_ms", "duration_ms", "text",
    "text_lang", "asr_speaker", "asr_speaker_is_target",
    "prev_text", "prev_state", "next_text", "next_state",
    "local_state", "local_reason", "original_route",
    "target_score", "best_competitor_score", "score_margin",
    "cluster_score", "cluster_consistency", "cluster_size",
    "cluster_has_target_prior", "separation_backend",
})

#: 数值字段业务口径（随请求 state.policy 下发——「数值字段必须附带明确业务
#: 口径，不能假设模型天然理解 0.55 等项目阈值」）。键名 = state 字段名或
#: 问题名；值 = 一句话口径。**只增不改语义**；语义变更必须 bump SCHEMA_VERSION。
STATE_FIELD_GLOSSARY = {
    "target_score": "CAM++ 目标模板最高余弦相似度，0-1；null 表示音频不可判",
    "best_competitor_score": "最强竞争者分：其他说话人簇对目标模板的最高余弦，"
                             "0-1；无其他簇时为 null",
    "score_margin": "target_score - best_competitor_score，由请求方预计算；"
                    "负值表示本簇不如竞争者像主播",
    "cluster_score": "当前 cue 所属簇（ASR 标签组或本地簇）对目标模板的簇级余弦，"
                     "0-1；无有效簇分时为 null",
    "cluster_consistency": "簇内 cue 分数标准差，0-1，越低越一致；有效分不足 2 条"
                           "时为 null",
    "cluster_size": "当前簇的 cue 条数（≥1）",
    "cluster_has_target_prior": "簇内是否存在分数 ≥ keep_threshold 的 cue（布尔）",
    "asr_speaker_is_target": "该 cue 的 ASR 说话人标签组簇分 ≥ keep_threshold"
                             "（布尔；无标签或无有效簇分为 null）",
    "keep_threshold": "本地 keep 下界：target_score ≥ 此值判主播（0-1）",
    "low_threshold": "本地 drop 上界：target_score < 此值判非主播；"
                     "[low, keep) 为存疑区",
    "evidence_conflict": "noul P(yes)：文本/ASR 标签与声学证据冲突的概率，0-1；"
                         "高值只标记冲突，不覆盖声学证据",
    "cluster_split_needed": "noul P(yes)：当前簇可能需要拆分局部重算的概率，0-1",
    "evidence_quality": "score 0..3 对应证据充分级 2..5（展示级 = score + 2）；"
                        "低分样本始终进入待复核",
}


def detect_text_lang(text):
    """粗分类字幕文本的主要语种（state.text_lang 的口径，随 glossary 下发）。

    只做字符集占比的粗分类，不承担分词/检测库职责（引擎纯度）：
      * 假名（ひらがな/カタカナ）出现即判 ja；
      * 谚文出现即判 ko（谚文与汉字混排的韩文字幕以谚文为准）；
      * 汉字占比 ≥ 0.30 判 zh（纯汉字日文罕见于本项目语料，接受误差）；
      * 拉丁字母占比 ≥ 0.50 判 en；
      * 其余非空文本 other；空文本返回 ""。
    判错的影响面只有模型的 context 理解，不参与任何本地硬规则。
    """
    s = str(text or "")
    if not s:
        return ""
    kana = sum(0x3040 <= ord(ch) <= 0x30FF for ch in s)
    hangul = sum(0xAC00 <= ord(ch) <= 0xD7AF for ch in s)
    han = sum(0x4E00 <= ord(ch) <= 0x9FFF for ch in s)
    latin = sum(ch.isascii() and ch.isalpha() for ch in s)
    total = sum(not ch.isspace() for ch in s) or 1
    if kana:
        return "ja"
    if hangul:
        return "ko"
    if han / total >= 0.30:
        return "zh"
    if latin / total >= 0.50:
        return "en"
    return "other"


def question_set(prefix):
    """一条 cue 的 5 问定义（问题名 -> 问题对象 dict）。

    `prefix` 为该 cue 在本请求内的问题前缀（如 ``c0``），生成的键：
    ``{prefix}_role`` / ``{prefix}_conflict`` / ``{prefix}_split`` /
    ``{prefix}_route`` / ``{prefix}_quality``。instructions 一律锚定到
    ``{prefix}_route`` 对应的 state.items 条目（该条目的 question 键就是
    ``{prefix}_route``），并写明引擎边界：「不能听到音频，不得凭台词猜
    说话人身份」。

    返回 dict 的键序即发送序（content_role → conflict → split → route →
    quality，与附录 A.1 表序一致）。
    """
    route_q = prefix + "_route"
    anchor = ("state.items 中 question=%s 的存疑字幕" % route_q)
    return {
        prefix + "_role": {
            "type": "choice",
            "instructions": ("判断 %s 的字幕文本属于哪种内容角色。只识别文本"
                             "角色，不判定声音身份，不得凭台词猜测说话人。"
                             % anchor),
            "criteria": dict(CONTENT_ROLE_OPTIONS),
        },
        prefix + "_conflict": {
            "type": "noul",
            "instructions": ("估计 %s 的文本、ASR 标签与声学证据相互冲突的概率"
                             " P(yes)。高值只用于标记冲突（检查混簇/重叠/时间轴），"
                             "不得作为仅凭文本改判的依据。" % anchor),
        },
        prefix + "_split": {
            "type": "noul",
            "instructions": ("估计 %s 所属簇可能需要拆分重算的概率 P(yes)。"
                             "高值触发局部重算建议，不代表全量删除。" % anchor),
        },
        route_q: {
            "type": "choice",
            "instructions": ("只评估 %s。你不能听到音频，不得凭台词猜测说话人"
                             "身份；本地声纹分数是主要证据。输出 keep、drop、"
                             "review 或 cannot_determine；cannot_determine "
                             "一律转人工复核。" % anchor),
            "criteria": dict(ROUTE_OPTIONS),
        },
        prefix + "_quality": {
            "type": "score",
            "instructions": ("评估 %s 的证据充分程度（score 0=最弱…3=最强，"
                             "对应展示级 2..5）。低分条目始终进入待复核。"
                             % anchor),
            "criteria": list(EVIDENCE_QUALITY_LEVELS),
        },
    }


def quality_level(score):
    """原始 score（0..3）→ 展示级（2..5）；无效值返回 None。"""
    try:
        s = float(score)
    except (TypeError, ValueError):
        return None
    if s != s or s < 0:
        return None
    return int(round(s)) + QUALITY_LEVEL_MIN


def is_conflicted(conflict_noul):
    """evidence_conflict 的 P(yes) 是否达到冲突判定线。None 视为未冲突。"""
    try:
        v = float(conflict_noul)
    except (TypeError, ValueError):
        return False
    return v == v and v >= CONFLICT_NOUL_THRESHOLD


def is_dispersed(probabilities):
    """route 概率分布是否「分散」（最大概率 < ASSIST_TOP_PROB_MIN）。"""
    try:
        vals = [float(v) for v in dict(probabilities or {}).values()]
    except (TypeError, ValueError):
        return True
    vals = [v for v in vals if v == v and v >= 0.0]
    return (max(vals) if vals else 0.0) < ASSIST_TOP_PROB_MIN


def hard_route_conflict(route, target_score, keep_threshold, low_threshold,
                        cluster_has_target_prior=None):
    """建议路由与本地硬规则是否冲突（附录 A.3「硬规则优先」）。

    本地硬规则 = decide() 的三分支口径（target ≥ keep → 主播；target < low →
    非主播）。存疑区 [low, keep) 内本地无定论，交由模型建议；但建议**不得**
    反向穿越硬边界：

      * ``keep`` 且 target < low      → 冲突（硬规则说它连 drop 线都不到）；
      * ``drop`` 且 target ≥ keep     → 冲突（硬规则说它已是主播）；
      * ``drop`` 且簇内存在 ≥ keep 的成员 → 冲突（声学证据：该簇整体像主播，
        不得仅凭文本把簇内成员判死——对应「与声学证据冲突」约束）。

    target 无效（None/NaN）时 keep/drop 一律视为冲突（无法核对硬边界 → 保守）；
    ``review`` / ``cannot_determine`` 永不冲突。
    返回 ""（无冲突）或冲突原因短码。
    """
    route = str(route or "")
    if route in ("review", "cannot_determine"):
        return ""
    valid = target_score is not None and float(target_score) == float(target_score)
    if not valid:
        return "score_unavailable"
    t = float(target_score)
    if route == "keep" and t < float(low_threshold):
        return "below_low"
    if route == "drop":
        if t >= float(keep_threshold):
            return "above_keep"
        if cluster_has_target_prior:
            return "cluster_target_prior"
    return ""


__all__ = [
    "SCHEMA_VERSION", "LEGACY_SHADOW_VERSION", "PROTOCOL_ENVELOPE_VERSION",
    "QUESTIONS_PER_CUE", "MAX_CUES_PER_REQUEST", "ROUTE_OPTIONS",
    "CONTENT_ROLE_OPTIONS", "CONFLICT_NOUL_THRESHOLD",
    "EVIDENCE_QUALITY_LEVELS", "QUALITY_LEVEL_MIN", "QUALITY_AUTO_MIN_LEVEL",
    "AUTO_CONF_T1", "AUTO_PROB_P1", "ASSIST_TOP_PROB_MIN", "ASSIST_CONF_MIN",
    "ASSIST_MAX_FAILED_BATCHES", "REQUIRED_ITEM_FIELDS",
    "STATE_FIELD_GLOSSARY", "detect_text_lang", "question_set",
    "quality_level", "is_conflicted", "is_dispersed", "hard_route_conflict",
]
