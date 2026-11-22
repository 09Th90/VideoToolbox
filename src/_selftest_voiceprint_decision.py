#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# @version 3.3.0
"""声纹决策 Schema v2 自检（WP3 part 2，离线：mock client 零网络、零模型、零 ffmpeg）。

覆盖：
  · vp_decision_schema：三层 Schema 版本并存（vt.decision.v1 信封 /
    vt.voiceprint.shadow.v1 R0 历史 / vt.voiceprint.filter.v2 业务层）；
    STATE_FIELD_GLOSSARY 数值口径键齐全；route 四值 / content_role 四值 /
    evidence_quality 4 级有序 criteria（score 0..3 ↔ 展示级 2..5）；
    detect_text_lang 粗分类；hard_route_conflict 硬规则矩阵；
  · 5 问/cue、每请求最多 3 cue（decision_batch_size 语义 = 每请求 cue 数上限，
    默认 3；5×3=15 ≤ 客户端单请求上限 16）；问题键唯一且逐 cue 成套；
  · state.item v2 字段齐全（REQUIRED_ITEM_FIELDS 全覆盖）、全程可 JSON
    序列化（allow_nan=False，NaN/Inf 一律不发）、policy 随 field_glossary
    与阈值快照下发、separation_backend 恒 "none"；
  · apply_shadow（R0）：只选 review、只追加 details[i].jev、verdict 逐字节
    不动、keep/drop 无 jev；异常整批 degraded；jev 记录 5 问答案；
  · apply_assist（R1 骨架）：默认关闭零行为；启用后本地闸门先行
    （evidence_missing 不调 Jev）、白名单三件事（priority_manual 置前 /
    建议列 / conflict 标注）、A.3 约束（cannot_determine→review、声学冲突
    不得仅凭文本改、硬规则优先、低置信/分散→待复核不丢弃）、请求失败本批
    退回原规则、连续 N 批失败跳过剩余；
  · apply_auto（R2 骨架）：默认关闭零行为；场景白名单为空永不生效；全部门禁
    （T1=0.98 / P1 / quality≥级4 / 声学不冲突 / 场景白名单 / 硬规则一致）
    逐项生效；只改路由三值，文本/时间轴/结构不动；低置信 100% 待复核；
    请求失败停止扩大自动化；
  · 引擎纯度：voiceprint_decision / vp_decision_schema 不 import 网络/
    引擎模块。

运行：PYTHONIOENCODING=utf-8 PYTHONPATH=src VT_NO_SYNC=1 \\
      tools/python/python.exe src/_selftest_voiceprint_decision.py
"""
import copy
import inspect
import json
import math
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("VT_NO_PIPELINE", "1")
os.environ.setdefault("VT_NO_SYNC", "1")
os.environ.setdefault("VT_NO_VP_SYNC", "1")

from features.voiceprint import vp_decision_schema as S          # noqa: E402
from features.voiceprint import voiceprint_decision as VD        # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "data", "tmp", "dev_out", "_voiceprint_decision_test")
LINES, FAILS = [], []


def say(m):
    LINES.append(str(m))
    print(m)


def check(name, cond, extra=""):
    line = "  [%s] %s%s" % ("PASS" if cond else "FAIL", name,
                            (" -> " + str(extra)) if extra else "")
    say(line)
    if not cond:
        FAILS.append(name)


THRESHOLD, LOW = 0.55, 0.45


def _verdict_equal(a, b):
    """NaN 感知的 verdict 比较（无分条目 score 是 NaN，nan==nan 恒 False）。

    cue 对象按属性比较（deepcopy 后身份不同但内容应逐字段一致）。
    """
    def _cue(c):
        return (getattr(c, "num", None), str(getattr(c, "text", "")),
                str(getattr(c, "speaker", "")), int(getattr(c, "start", 0)),
                int(getattr(c, "end", 0)))

    if len(a) != len(b):
        return False
    for (ca, sa, ra), (cb, sb, rb) in zip(a, b):
        if _cue(ca) != _cue(cb) or str(sa) != str(sb):
            return False
        fa = ra == ra and ra is not None
        fb = rb == rb and rb is not None
        if fa != fb:
            return False
        if fa and abs(float(ra) - float(rb)) > 1e-12:
            return False
    return True


# ---------------------------------------------------------------- mock client

class MockClient:
    """模拟 Jev 决策客户端：零网络，按 spec 生成协议合法答案。

    spec 按问题后缀配置：{"route": {"choice": .., "confidence": .., "p": ..
    [, "probabilities": {...}]}, "conflict": {"noul": ..},
    "quality": {"score": ..}, "role": {"choice": ..}, "split": {...}}。
    fail_after=N 表示前 N 次请求成功、之后开始失败（测停止扩大自动化）。
    """

    ROUTE_BASE = ("keep", "drop", "review", "cannot_determine")

    def __init__(self, *, active=True, mode="shadow", config=None, spec=None,
                 error=False, fail_after=None):
        self.active = active
        self.status = {"active": active, "mode": mode,
                       "model": "decision-model-preview",
                       "endpoint": "https://token-plan.example/compatible-mode/v1",
                       "reason": "" if active else "not_configured"}
        self.config = dict(config or {"decision_max_items": 32,
                                      "decision_batch_size": 8})
        self.spec = dict(spec or {})
        self.error = error
        self.fail_after = fail_after
        self.calls = []

    def decide(self, state, questions):
        self.calls.append((state, questions))
        if self.error or (self.fail_after is not None
                          and len(self.calls) > self.fail_after):
            raise RuntimeError("模拟网络超时")
        return {"model": "decision-model-preview",
                "request_id": "req-%d" % len(self.calls),
                "answers": {name: self._answer(name, q)
                            for name, q in questions.items()}}

    def _answer(self, name, q):
        sfx = name.rsplit("_", 1)[-1]
        spec = dict(self.spec.get(sfx) or {})
        if q["type"] == "choice":
            if sfx == "role":
                choice = str(spec.get("choice") or "host_commentary")
                others = [k for k in q["criteria"] if k != choice]
                probs = {choice: 0.70}
                w = round(0.30 / max(1, len(others)), 4)
                for k in others:
                    probs[k] = w
                return {"type": "choice", "choice": choice,
                        "confidence": float(spec.get("confidence", 0.9)),
                        "probabilities": probs}
            # route
            choice = str(spec.get("choice") or "review")
            probs = spec.get("probabilities")
            if probs is None:
                p = float(spec.get("p", 0.85))
                rest = round((1.0 - p) / (len(self.ROUTE_BASE) - 1), 4)
                probs = {k: rest for k in self.ROUTE_BASE}
                probs[choice] = p
            else:
                probs = {str(k): float(v) for k, v in probs.items()}
            return {"type": "choice", "choice": choice,
                    "confidence": float(spec.get("confidence", 0.9)),
                    "probabilities": probs}
        if q["type"] == "noul":
            return {"type": "noul", "noul": float(spec.get("noul", 0.05))}
        # score
        score = float(spec.get("score", 2.0))
        levels = len(q["criteria"])
        top = min(max(int(round(score)), 0), levels - 1)
        probs = {str(i): 0.05 for i in range(levels)}
        probs[str(top)] = round(1.0 - 0.05 * (levels - 1), 4)
        return {"type": "score", "score": score, "confidence": 0.9,
                "probabilities": probs,
                "legend": {str(i): q["criteria"][i] for i in range(levels)}}


def _answers_of(client, call_index):
    """重放第 call_index 次请求的协议合法答案（mock 确定性 → 与真实响应一致）。"""
    _state, questions = client.calls[call_index]
    return {name: client._answer(name, q) for name, q in questions.items()}


def _validate_locally(questions, answers):
    """本地轻量校验（镜像协议约束，不 import part1 正在改的 decision_client）：
    1-16 问、类型合法、choice 选项在 criteria、概率归一（±0.08）、
    score 在 [0, levels-1] 且 legend 覆盖全级。返回错误串列表。"""
    errs = []
    if not (1 <= len(questions) <= 16):
        errs.append("问题数 %d 越界" % len(questions))
    for name, q in questions.items():
        a = answers.get(name)
        if not isinstance(a, dict) or a.get("type") != q["type"]:
            errs.append("%s 答案缺失或类型不符" % name)
            continue
        if q["type"] == "choice":
            if a.get("choice") not in q["criteria"]:
                errs.append("%s 返回未声明选项 %r" % (name, a.get("choice")))
            probs = a.get("probabilities") or {}
            if any(str(k) not in probs for k in q["criteria"]):
                errs.append("%s probabilities 缺选项" % name)
            if abs(sum(probs.values()) - 1.0) > 0.08:
                errs.append("%s probabilities 未归一（%s）"
                            % (name, sum(probs.values())))
        elif q["type"] == "noul":
            v = a.get("noul")
            if not isinstance(v, (int, float)) or not (0.0 <= v <= 1.0):
                errs.append("%s noul 越界" % name)
        else:
            levels = len(q["criteria"])
            v = a.get("score")
            if not isinstance(v, (int, float)) or not (0.0 <= v <= levels - 1):
                errs.append("%s score 越界" % name)
            legend = a.get("legend")
            if not isinstance(legend, dict) or any(
                    str(i) not in legend for i in range(levels)):
                errs.append("%s legend 不全" % name)
    return errs


# ---------------------------------------------------------------- fixture

def fixture():
    """6 条 cue：2 keep / 1 drop / 3 review（三种组形态）。

    review 三条各司其职：
      #3 —— 说话人1 组（簇内有 0.90 keep 先验）：测 prior/一致性/先验挡 drop；
      #4 —— 无簇无分（target None）：测 R1 本地闸门 evidence_missing；
      #5 —— 说话人2 组（单条、无先验、0.50 贴边）：测 R2 自动 drop 的合格靶子。
    """
    texts = ["大家好欢迎收看节目", "我是嘉宾", "今天我们聊点别的",
             "这一局打法很关键", "（无声段）", "那么让我们进入正题"]
    speakers = ["说话人1", "", "说话人1", "说话人1", "", "说话人2"]
    states = ["keep", "drop", "keep", "review", "review", "review"]
    scores = [0.90, 0.10, 0.90, 0.50, None, 0.50]
    clusters = [-1, 0, -1, -1, -1, 1]
    reasons = ["", "", "", "borderline", "audio_missing", "borderline"]
    cues, details, verdict = [], [], []
    for i in range(6):
        cue = SimpleNamespace(num=i + 1, text=texts[i], speaker=speakers[i],
                              start=1000 * i, end=1000 * i + 800)
        cues.append(cue)
        details.append({"num": i + 1, "start": cue.start, "end": cue.end,
                        "duration_ms": 800, "state": states[i],
                        "score": scores[i], "source": "cue_fallback",
                        "reason": reasons[i], "speaker": speakers[i],
                        "cluster": clusters[i]})
        verdict.append((cue, states[i],
                        scores[i] if scores[i] is not None else float("nan")))
    group_scores = {
        "说话人1": {"score": 0.90, "n": 3, "seconds": 6.0, "best": "主播"},
        "说话人2": {"score": 0.50, "n": 1, "seconds": 1.2, "best": ""},
        "0": {"score": 0.10, "n": 1, "seconds": 1.5, "best": ""},
        "1": {"score": 0.50, "n": 1, "seconds": 1.1, "best": ""},
    }
    return cues, details, verdict, group_scores


def big_fixture():
    """12 条 cue：1 keep（说话人1）+ 1 drop（簇1）+ 10 review（簇0 无先验）。

    review 10 条 → 批次 [3,3,3,1]：测连续失败跳过（R1）与停止扩大自动化（R2）。
    簇0 内全是 0.50（无 ≥keep 先验）→ R2 自动 drop 的硬规则全通过。
    """
    cues, details, verdict = [], [], []
    for i in range(12):
        if i == 0:
            cue = SimpleNamespace(num=1, text="大家好欢迎收看节目",
                                  speaker="说话人1", start=0, end=800)
            row = {"state": "keep", "score": 0.90, "speaker": "说话人1",
                   "cluster": -1, "reason": ""}
        elif i == 1:
            cue = SimpleNamespace(num=2, text="我是嘉宾", speaker="",
                                  start=1000, end=1800)
            row = {"state": "drop", "score": 0.10, "speaker": "",
                   "cluster": 1, "reason": ""}
        else:
            cue = SimpleNamespace(num=i + 1, text="第%d句存疑内容" % (i + 1),
                                  speaker="", start=1000 * i,
                                  end=1000 * i + 800)
            row = {"state": "review", "score": 0.50, "speaker": "",
                   "cluster": 0, "reason": "borderline"}
        cues.append(cue)
        details.append({"num": i + 1, "start": cue.start, "end": cue.end,
                        "duration_ms": 800, "source": "cue_fallback",
                        **row})
        verdict.append((cue, row["state"], float(row["score"])))
    group_scores = {"说话人1": {"score": 0.90, "n": 1, "seconds": 0.8,
                                "best": "主播"},
                    "0": {"score": 0.50, "n": 10, "seconds": 8.0, "best": ""},
                    "1": {"score": 0.10, "n": 1, "seconds": 0.8, "best": ""}}
    return cues, details, verdict, group_scores


def _route_jev(details, index):
    return (details[index].get("jev") or {}) if 0 <= index < len(details) else {}


# ================================================================ 1) Schema 基础

def test_schema_basics():
    say("\n== 1) Schema v2 基础（三层版本并存 / GLOSSARY / 5 问定义）==")
    check("业务层版本 = vt.voiceprint.filter.v2",
          S.SCHEMA_VERSION == "vt.voiceprint.filter.v2", S.SCHEMA_VERSION)
    check("R0 历史版本 = vt.voiceprint.shadow.v1",
          S.LEGACY_SHADOW_VERSION == "vt.voiceprint.shadow.v1")
    check("协议信封版本 = vt.decision.v1",
          S.PROTOCOL_ENVELOPE_VERSION == "vt.decision.v1")
    check("voiceprint_decision.SCHEMA_VERSION 指向业务 v2",
          VD.SCHEMA_VERSION == S.SCHEMA_VERSION)
    check("voiceprint_decision.SHADOW_SCHEMA_V1 保留 R0 历史",
          VD.SHADOW_SCHEMA_V1 == "vt.voiceprint.shadow.v1")
    check("v1 三值优先级词汇 ROUTES 历史保留",
          set(VD.ROUTES) == {"routine_review", "priority_manual",
                             "insufficient_evidence"}, set(VD.ROUTES))
    for key in ("target_score", "best_competitor_score", "score_margin",
                "cluster_consistency", "keep_threshold", "low_threshold",
                "cluster_score", "cluster_size", "cluster_has_target_prior",
                "asr_speaker_is_target", "evidence_conflict",
                "cluster_split_needed", "evidence_quality"):
        check("GLOSSARY 数值口径：%s" % key,
              key in S.STATE_FIELD_GLOSSARY
              and isinstance(S.STATE_FIELD_GLOSSARY[key], str)
              and S.STATE_FIELD_GLOSSARY[key])
    check("GLOSSARY 口径措辞含阈值语义（keep_threshold）",
          "keep" in S.STATE_FIELD_GLOSSARY["keep_threshold"]
          or "下界" in S.STATE_FIELD_GLOSSARY["keep_threshold"])
    check("route 四值词汇", set(S.ROUTE_OPTIONS) ==
          {"keep", "drop", "review", "cannot_determine"}, set(S.ROUTE_OPTIONS))
    check("content_role 四值词汇", set(S.CONTENT_ROLE_OPTIONS) ==
          {"host_commentary", "game_dialogue", "official_narration", "other"},
          set(S.CONTENT_ROLE_OPTIONS))
    check("evidence_quality criteria 为 4 元素有序 list",
          isinstance(S.EVIDENCE_QUALITY_LEVELS, list)
          and len(S.EVIDENCE_QUALITY_LEVELS) == 4
          and all(isinstance(x, str) for x in S.EVIDENCE_QUALITY_LEVELS))
    check("score 0..3 映射展示级 2..5（legend 0 起）",
          [S.quality_level(i) for i in range(4)] == [2, 3, 4, 5],
          [S.quality_level(i) for i in range(4)])
    check("quality_level 无效值返回 None",
          S.quality_level(None) is None and S.quality_level(float("nan")) is None)
    check("每请求 cue 数上限 3（5×3=15 ≤ 16）",
          S.QUESTIONS_PER_CUE == 5 and S.MAX_CUES_PER_REQUEST == 3
          and S.QUESTIONS_PER_CUE * S.MAX_CUES_PER_REQUEST <= 16)
    check("R2 门禁草案常量：T1=0.98 / P1=0.90",
          S.AUTO_CONF_T1 == 0.98 and S.AUTO_PROB_P1 == 0.90)

    qs = S.question_set("c0")
    check("5 问/cue 键齐全且唯一", len(qs) == 5 and len(set(qs)) == 5, list(qs))
    check("问题类型：role/route=choice，conflict/split=noul，quality=score",
          qs["c0_role"]["type"] == "choice"
          and qs["c0_route"]["type"] == "choice"
          and qs["c0_conflict"]["type"] == "noul"
          and qs["c0_split"]["type"] == "noul"
          and qs["c0_quality"]["type"] == "score")
    check("route criteria 对齐 ROUTE_OPTIONS",
          qs["c0_route"]["criteria"] == S.ROUTE_OPTIONS)
    check("role criteria 对齐 CONTENT_ROLE_OPTIONS",
          qs["c0_role"]["criteria"] == S.CONTENT_ROLE_OPTIONS)
    check("quality criteria 对齐 4 级有序 list",
          qs["c0_quality"]["criteria"] == S.EVIDENCE_QUALITY_LEVELS)
    check("instructions 写明引擎边界（不能听音频/不凭台词猜身份）",
          "不能听到音频" in qs["c0_route"]["instructions"]
          and "不得凭台词猜测说话人身份" in qs["c0_route"]["instructions"])
    check("content_role 只识别文本角色不判声音身份",
          "不判定声音身份" in qs["c0_role"]["instructions"])
    check("conflict 高值只标冲突不覆盖声学",
          "不得作为仅凭文本改判的依据" in qs["c0_conflict"]["instructions"])
    check("split 触发局部重算不全量删",
          "局部重算" in qs["c0_split"]["instructions"]
          and "全量删除" in qs["c0_split"]["instructions"])
    check("route 锚定到本条 item（c0_route）",
          all("c0_route" in q["instructions"] for q in qs.values()))
    check("多 cue 前缀互不串扰（c1 锚定 c1_route）",
          all("c1_route" in q["instructions"]
              for q in S.question_set("c1").values()))

    check("detect_text_lang：中文", S.detect_text_lang("大家好欢迎收看") == "zh")
    check("detect_text_lang：日文假名", S.detect_text_lang("こんにちは、世界") == "ja")
    check("detect_text_lang：韩文谚文",
          S.detect_text_lang("안녕하세요 반갑습니다") == "ko")
    check("detect_text_lang：英文",
          S.detect_text_lang("Hello there everyone") == "en")
    check("detect_text_lang：空文本返回空串", S.detect_text_lang("") == "")
    check("detect_text_lang：其他", S.detect_text_lang("…！？12345") == "other")

    check("硬规则：keep 且 target<low 冲突（below_low）",
          S.hard_route_conflict("keep", 0.40, 0.55, 0.45, False) == "below_low")
    check("硬规则：drop 且 target>=keep 冲突（above_keep）",
          S.hard_route_conflict("drop", 0.60, 0.55, 0.45, False) == "above_keep")
    check("硬规则：drop 且簇内有 keep 先验冲突（cluster_target_prior）",
          S.hard_route_conflict("drop", 0.50, 0.55, 0.45, True)
          == "cluster_target_prior")
    check("硬规则：target 无效时 keep/drop 一律冲突",
          S.hard_route_conflict("keep", None, 0.55, 0.45, False)
          == "score_unavailable"
          and S.hard_route_conflict("drop", float("nan"), 0.55, 0.45, False)
          == "score_unavailable")
    check("硬规则：review/cannot_determine 永不冲突",
          S.hard_route_conflict("review", 0.90, 0.55, 0.45, True) == ""
          and S.hard_route_conflict("cannot_determine", None, 0.55, 0.45,
                                    True) == "")
    check("硬规则：存疑区内 keep/drop 无先验时不冲突",
          S.hard_route_conflict("drop", 0.50, 0.55, 0.45, False) == ""
          and S.hard_route_conflict("keep", 0.50, 0.55, 0.45, False) == "")
    check("冲突判定线：noul>=0.5 视为冲突，None 不冲突",
          S.is_conflicted(0.5) and S.is_conflicted(0.9)
          and not S.is_conflicted(0.3) and not S.is_conflicted(None))
    check("概率分散：最大概率 <0.60 视为分散",
          S.is_dispersed({"keep": 0.4, "drop": 0.35, "review": 0.25})
          and not S.is_dispersed({"keep": 0.7, "drop": 0.3})
          and S.is_dispersed(None))


# ================================================================ 2/3) state 与分批

def test_state_and_batching():
    say("\n== 2) Schema v2 state 字段齐全（默认影子只追加 jev）==")
    cues, details, verdict, group_scores = fixture()
    original_verdict = copy.deepcopy(verdict)
    client = MockClient(spec={"route": {"choice": "review", "confidence": 0.9}})
    summary = VD.apply_shadow(verdict, details, client, threshold=THRESHOLD,
                              low=LOW, group_scores=group_scores)
    check("影子只选 review（3 条）",
          summary["review_total"] == 3 and summary["selected"] == 3
          and summary["evaluated"] == 3, summary)
    check("默认影子：verdict 逐字节不动（NaN 感知）",
          _verdict_equal(verdict, original_verdict))
    check("keep/drop 行无 jev",
          "jev" not in details[0] and "jev" not in details[1]
          and "jev" not in details[2])
    check("review 行 jev 状态 ok、schema 为业务 v2",
          all(_route_jev(details, i).get("status") == "ok"
              and _route_jev(details, i).get("schema") == S.SCHEMA_VERSION
              for i in (3, 4, 5)))
    check("jev 记录 route 主答案（choice/confidence/probabilities）",
          all("choice" in _route_jev(details, i)
              and "confidence" in _route_jev(details, i)
              and isinstance(_route_jev(details, i).get("probabilities"), dict)
              for i in (3, 4, 5)))
    check("jev 记录其余四问原始答案（questions 4 键）",
          all(isinstance(_route_jev(details, i).get("questions"), dict)
              and len(_route_jev(details, i)["questions"]) == 4
              for i in (3, 4, 5)))
    check("jev 记录解析后的辅助答案（role/conflict/split/quality）",
          _route_jev(details, 5).get("content_role") == "host_commentary"
          and _route_jev(details, 5).get("evidence_conflict") == 0.05
          and _route_jev(details, 5).get("cluster_split_needed") == 0.05
          and _route_jev(details, 5).get("evidence_quality") == 4,
          _route_jev(details, 5))

    state, questions = client.calls[0]
    items = state["items"]
    check("state 业务标识与版本",
          state["schema_version"] == S.SCHEMA_VERSION
          and state["business"] == "voiceprint_review_routing")
    check("policy 随 field_glossary 与阈值快照下发",
          state["policy"]["field_glossary"] == S.STATE_FIELD_GLOSSARY
          and state["policy"]["keep_threshold"] == THRESHOLD
          and state["policy"]["low_threshold"] == LOW
          and state["policy"]["shadow_only"] is True
          and state["policy"]["allow_verdict_change"] is False)
    for it in items:
        missing = S.REQUIRED_ITEM_FIELDS - set(it)
        check("item #%s v2 字段齐全（缺 %s）" % (it["num"], sorted(missing) or "无"),
              not missing, sorted(missing))
    check("state 全程 JSON 可序列化（allow_nan=False，NaN 一律不发）",
          json.dumps(state, ensure_ascii=False, allow_nan=False) is not None)
    it3 = next(it for it in items if it["num"] == 4)      # cue3（说话人1 组）
    it4 = next(it for it in items if it["num"] == 5)      # cue4（无簇无分）
    it5 = next(it for it in items if it["num"] == 6)      # cue5（说话人2 组）
    check("竞争者分差：说话人1 组 margin = 0.50-0.50 = 0.0",
          it3["target_score"] == 0.50 and it3["best_competitor_score"] == 0.50
          and it3["score_margin"] == 0.0, it3["score_margin"])
    check("簇分数/簇大小取自 spk_scores（n=3）",
          it3["cluster_score"] == 0.90 and it3["cluster_size"] == 3)
    check("簇一致性 = 组内分数标准差（[0.90,0.90,0.50] ≈ 0.189）",
          it3["cluster_consistency"] is not None
          and abs(it3["cluster_consistency"] - 0.189) < 0.01,
          it3["cluster_consistency"])
    check("簇先验：说话人1 组内有 ≥keep 分成员",
          it3["cluster_has_target_prior"] is True)
    check("ASR 标签组命中主播（组簇分 0.90 ≥ 0.55）",
          it3["asr_speaker_is_target"] is True)
    check("无簇无分条目：target/margin/簇字段/asr 布尔全为 null",
          it4["target_score"] is None and it4["score_margin"] is None
          and it4["cluster_score"] is None and it4["cluster_size"] is None
          and it4["cluster_consistency"] is None
          and it4["asr_speaker_is_target"] is None
          and it4["cluster_has_target_prior"] is False,
          (it4["target_score"], it4["cluster_size"]))
    check("单成员簇一致性为 null（无从谈一致）、无先验",
          it5["cluster_consistency"] is None
          and it5["cluster_has_target_prior"] is False
          and it5["cluster_size"] == 1)
    check("竞争者 = 其他组最高簇分（说话人2 组看到说话人1 的 0.90）",
          it5["best_competitor_score"] == 0.90
          and it5["score_margin"] == -0.40, it5["score_margin"])
    check("asr_speaker_is_target：说话人2 组簇分 0.50 < 0.55 → False",
          it5["asr_speaker_is_target"] is False)
    check("邻接文本+邻接状态（prev=keep 句、next=review 句）",
          it3["prev_text"] == "今天我们聊点别的" and it3["prev_state"] == "keep"
          and it3["next_state"] == "review")
    check("original_route 保留原路由（review）",
          all(it["original_route"] == "review" for it in items))
    check("local_state 恒 review、local_reason 透传",
          all(it["local_state"] == "review" for it in items)
          and it4["local_reason"] == "audio_missing")
    check("separation_backend 恒 none（WP5 预留）",
          all(it["separation_backend"] == "none" for it in items))
    check("text_lang 粗分类随文本（中/中/中；other 分支已在 §1 直测）",
          it3["text_lang"] == "zh" and it4["text_lang"] == "zh"
          and it5["text_lang"] == "zh",
          (it3["text_lang"], it4["text_lang"], it5["text_lang"]))
    errs = _validate_locally(questions, _answers_of(client, 0))
    check("答案本地轻量校验零错误（协议形状镜像）", not errs, errs[:3])

    say("\n== 3) 5 问/cue、每请求最多 3 cue 分批 ==")
    check("3 条 review 恰好 1 个请求（batch 默认 3）",
          len(client.calls) == 1, len(client.calls))
    check("每请求 15 问（3 cue × 5）且 ≤ 客户端上限 16",
          len(questions) == 15 and len(questions) <= 16, len(questions))
    check("问题键逐 cue 成套且互不重复",
          len(set(questions)) == 15
          and {n for n in questions if n.startswith("c0_")} ==
          {"c0_role", "c0_conflict", "c0_split", "c0_route", "c0_quality"},
          sorted(n for n in questions if n.startswith("c0_")))
    check("items 与 questions 一一锚定（question=c{i}_route）",
          all(it["question"] == "c%d_route" % p for p, it in enumerate(items)))

    client1 = MockClient(spec={"route": {"choice": "review"}})
    VD.apply_shadow(verdict, details, client1, threshold=THRESHOLD, low=LOW,
                    batch_size=1, group_scores=group_scores)
    check("batch_size=1 → 每请求 1 条 cue、5 问、共 3 请求",
          len(client1.calls) == 3
          and all(len(c[1]) == 5 for c in client1.calls),
          [len(c[1]) for c in client1.calls])
    client8 = MockClient(config={"decision_max_items": 32,
                                 "decision_batch_size": 8})
    VD.apply_shadow(verdict, details, client8, threshold=THRESHOLD, low=LOW,
                    group_scores=group_scores)
    check("decision_batch_size=8 被 clamp 到 3（每请求 3 cue/15 问）",
          len(client8.calls) == 1 and len(client8.calls[0][1]) == 15,
          (len(client8.calls), len(client8.calls[0][1]) if client8.calls else 0))
    client_off = MockClient(active=False)
    before = copy.deepcopy(details)
    s_off = VD.apply_shadow(verdict, details, client_off, threshold=THRESHOLD,
                            low=LOW, group_scores=group_scores)
    check("客户端未激活 → 零请求零 jev、details 逐字节不动",
          not client_off.calls and details == before
          and s_off["evaluated"] == 0 and s_off["active"] is False)


# ================================================================ 4) 异常 degraded

def test_degraded():
    say("\n== 4) 异常整批 degraded（影子永不影响本地筛选）==")
    cues, details, verdict, group_scores = fixture()
    original_verdict = copy.deepcopy(verdict)
    client = MockClient(error=True)
    summary = VD.apply_shadow(verdict, details, client, threshold=THRESHOLD,
                              low=LOW, group_scores=group_scores)
    check("异常批 evaluated=0、errors=1",
          summary["evaluated"] == 0 and len(summary["errors"]) == 1, summary)
    check("所有 review 行 jev degraded 且带原因",
          all(_route_jev(details, i).get("status") == "degraded"
              and _route_jev(details, i).get("reason") for i in (3, 4, 5)))
    check("降级不改 verdict", _verdict_equal(verdict, original_verdict))
    check("降级不写 schema/questions 等成功字段",
          all("schema" not in _route_jev(details, i) for i in (3, 4, 5)))


# ================================================================ 5) R1 assist

def test_assist():
    say("\n== 5) R1 辅助路由骨架（默认关闭 / 白名单三件事 / A.3 约束）==")
    cues, details, verdict, group_scores = fixture()
    original_verdict = copy.deepcopy(verdict)
    original_details = copy.deepcopy(details)

    say("  -- 默认关闭（零行为）--")
    client = MockClient()
    s0 = VD.apply_assist(verdict, details, client, threshold=THRESHOLD,
                         low=LOW, group_scores=group_scores)
    check("默认 enable=False：零请求", not client.calls)
    check("默认 enable=False：不写 assist 键、details 不动",
          details == original_details)
    check("默认 enable=False：summary 标记 assist_disabled",
          s0["stage"] == "assist" and s0["reason"] == "assist_disabled",
          s0.get("reason"))
    check("默认 enable=False：verdict 不动",
          _verdict_equal(verdict, original_verdict))

    say("  -- 启用：本地闸门先行 + 建议折算 --")
    spec = {"route": {"choice": "drop", "confidence": 0.95, "p": 0.90},
            "conflict": {"noul": 0.05}, "quality": {"score": 3.0}}
    client = MockClient(spec=spec)
    s1 = VD.apply_assist(verdict, details, client, threshold=THRESHOLD,
                         low=LOW, group_scores=group_scores, enable=True)
    check("启用后 selected=review 全量、evidence_missing 被闸门拦截（1 条）",
          s1["selected"] == 3 and s1["gated"] == 1
          and s1["gate_reasons"].get("evidence_missing") == 1, s1)
    check("被闸门拦截的条目不进 Jev 请求（pending 2 条只发 1 批 10 问）",
          len(client.calls) == 1 and len(client.calls[0][1]) == 10,
          (len(client.calls), len(client.calls[0][1]) if client.calls else 0))
    check("闸门条目 assist 标记 gated + suggestion=review",
          details[4]["assist"]["status"] == "gated"
          and details[4]["assist"]["suggestion"] == "review"
          and details[4]["assist"]["gate"] == "evidence_missing")
    check("高置信 drop 无冲突 → suggestion=drop、priority=routine",
          details[5]["assist"]["suggestion"] == "drop"
          and details[5]["assist"]["priority"] == "routine",
          details[5]["assist"])
    check("建议值白名单：只有 keep/drop/review 三值",
          details[3]["assist"]["suggestion"] in ("keep", "drop", "review")
          and details[5]["assist"]["suggestion"] in ("keep", "drop", "review"))
    check("assist 只写 details[i].assist，不碰 jev/verdict",
          "jev" not in details[5] and _verdict_equal(verdict, original_verdict))
    check("summary 建议列（items）含闸门+Jev 全部 3 条；routes 只计 Jev 建议",
          len(s1["items"]) == 3
          and s1["routes"].get("drop") == 1 and s1["routes"].get("review") == 1,
          (len(s1["items"]), s1["routes"]))

    say("  -- A.3：cannot_determine / 声学冲突 / 低置信 / 分散 --")
    spec_cd = {"route": {"choice": "cannot_determine", "confidence": 0.99,
                         "p": 0.95}}
    details_cd = copy.deepcopy(original_details)
    client_cd = MockClient(spec=spec_cd)
    s_cd = VD.apply_assist(verdict, details_cd, client_cd, threshold=THRESHOLD,
                           low=LOW, group_scores=group_scores, enable=True)
    check("cannot_determine 一律折算 review + priority_manual 置前",
          details_cd[5]["assist"]["suggestion"] == "review"
          and details_cd[5]["assist"]["priority"] == "priority_manual"
          and details_cd[5]["assist"]["gate"] == "cannot_determine")
    check("cannot_determine 批次：#6 排在未定条目 #5 之前（#4 同为 manual）",
          s_cd["priority_nums"].index(6) < s_cd["priority_nums"].index(5)
          and len(s_cd["priority_nums"]) == 3, s_cd["priority_nums"])
    check("cannot_determine 计入 priority_manual 统计（#4/#6 两条）",
          s_cd["priority_manual"] == 2, s_cd["priority_manual"])

    spec_cf = {"route": {"choice": "drop", "confidence": 0.99, "p": 0.95},
               "conflict": {"noul": 0.90}}
    details_cf = copy.deepcopy(original_details)
    client_cf = MockClient(spec=spec_cf)
    s_cf = VD.apply_assist(verdict, details_cf, client_cf, threshold=THRESHOLD,
                           low=LOW, group_scores=group_scores, enable=True)
    check("声学冲突 0.90：drop 建议折回 review + conflict 标注",
          details_cf[5]["assist"]["suggestion"] == "review"
          and details_cf[5]["assist"]["conflict"] is True
          and details_cf[5]["assist"]["conflict_noul"] == 0.90)
    check("冲突计数（spec 全局 → 2 条）与置前（#6 先于 #5）",
          s_cf["conflicts"] == 2
          and s_cf["priority_nums"].index(6) < s_cf["priority_nums"].index(5),
          (s_cf["conflicts"], s_cf["priority_nums"]))

    spec_lc = {"route": {"choice": "drop", "confidence": 0.30, "p": 0.85}}
    details_lc = copy.deepcopy(original_details)
    client_lc = MockClient(spec=spec_lc)
    VD.apply_assist(verdict, details_lc, client_lc, threshold=THRESHOLD,
                    low=LOW, group_scores=group_scores, enable=True)
    check("低置信 0.30：建议折回 review（不丢弃）+ 置前",
          details_lc[5]["assist"]["suggestion"] == "review"
          and details_lc[5]["assist"]["priority"] == "priority_manual"
          and "low_confidence" in details_lc[5]["assist"]["gate"])

    spec_dp = {"route": {"choice": "drop", "confidence": 0.99,
                         "probabilities": {"keep": 0.40, "drop": 0.35,
                                           "review": 0.20,
                                           "cannot_determine": 0.05}}}
    details_dp = copy.deepcopy(original_details)
    client_dp = MockClient(spec=spec_dp)
    VD.apply_assist(verdict, details_dp, client_dp, threshold=THRESHOLD,
                    low=LOW, group_scores=group_scores, enable=True)
    check("概率分散（最大 0.40 < 0.60）：建议折回 review + 置前",
          details_dp[5]["assist"]["suggestion"] == "review"
          and details_dp[5]["assist"]["priority"] == "priority_manual")

    say("  -- A.3：硬规则优先 --")
    spec_hr = {"route": {"choice": "keep", "confidence": 0.99, "p": 0.95}}
    details_hr = copy.deepcopy(original_details)
    details_hr[5]["score"] = 0.30      # 模拟脏数据行：state 仍 review 但分低于 low
    client_hr = MockClient(spec=spec_hr)
    s_hr = VD.apply_assist(verdict, details_hr, client_hr, threshold=THRESHOLD,
                           low=LOW, group_scores=group_scores, enable=True)
    check("keep 建议撞硬规则（#6 分数 0.30 < low 0.45 → below_low 折回 review）",
          details_hr[5]["assist"]["suggestion"] == "review"
          and details_hr[5]["assist"]["gate"] == "hard_rule:below_low",
          details_hr[5]["assist"]["gate"])
    check("硬规则冲突条目置前（#6 第一位）",
          s_hr["priority_nums"][:1] == [6], s_hr["priority_nums"])

    say("  -- 请求失败：本批退回原规则 / 连续 N 批跳过剩余 --")
    details_f = copy.deepcopy(original_details)
    client_f = MockClient(error=True)
    s_f = VD.apply_assist(verdict, details_f, client_f, threshold=THRESHOLD,
                          low=LOW, group_scores=group_scores, enable=True,
                          max_failed_batches=2)
    check("全失败（1 批）：evaluated 只含闸门 1 条、errors=1、本批退回原规则",
          s_f["evaluated"] == 1 and s_f["gated"] == 1
          and len(s_f["errors"]) == 1
          and details_f[3]["assist"]["status"] == "degraded"
          and details_f[3]["assist"]["suggestion"] == "review",
          (s_f["evaluated"], s_f["gated"], len(s_f["errors"])))
    check("失败批 verdict 不动", _verdict_equal(verdict, original_verdict))

    # big fixture：10 条 review → 批次 [3,3,3,1]；连续失败 2 批后跳过剩余 4 条
    _bc, bd, bv, bg = big_fixture()
    bv_original = copy.deepcopy(bv)
    client_big = MockClient(error=True)
    s_big = VD.apply_assist(bv, bd, client_big, threshold=THRESHOLD, low=LOW,
                            group_scores=bg, enable=True, max_failed_batches=2)
    check("连续 2 批失败后跳过剩余（attempted=2、skipped=4、failed_batches=2）",
          len(client_big.calls) == 2 and s_big["skipped"] == 4
          and s_big["failed_batches"] == 2,
          (len(client_big.calls), s_big["skipped"], s_big["failed_batches"]))
    check("跳过的条目不写 assist（留待人工）、verdict 不动",
          all("assist" not in bd[i] for i in range(8, 12))
          and all(bd[i]["assist"]["status"] == "degraded" for i in range(2, 8))
          and _verdict_equal(bv, bv_original))


# ================================================================ 6) R2 auto

def test_auto():
    say("\n== 6) R2 有限自动路由骨架（默认关闭 / 白名单 / 全门禁）==")
    cues, details, verdict, group_scores = fixture()
    original_verdict = copy.deepcopy(verdict)

    say("  -- 默认关闭 / 白名单为空 --")
    client = MockClient(spec={"route": {"choice": "drop", "confidence": 0.99,
                                        "p": 0.95}})
    nv0, s0 = VD.apply_auto(verdict, details, client, threshold=THRESHOLD,
                            low=LOW, group_scores=group_scores)
    check("默认 enable=False：零请求、verdict 原样",
          not client.calls and _verdict_equal(nv0, verdict)
          and s0["reason"] == "auto_disabled")
    nv1, s1 = VD.apply_auto(verdict, details, client, threshold=THRESHOLD,
                            low=LOW, group_scores=group_scores, enable=True)
    check("启用但场景白名单为空：永不生效（零请求、reason=scene_whitelist_empty）",
          not client.calls and _verdict_equal(nv1, verdict)
          and s1["reason"] == "scene_whitelist_empty")

    say("  -- 全门禁通过：只改路由三值 --")
    spec = {"route": {"choice": "drop", "confidence": 0.99, "p": 0.95},
            "conflict": {"noul": 0.0}, "quality": {"score": 3.0},
            "role": {"choice": "host_commentary"}}
    client = MockClient(spec=spec)
    nv, s = VD.apply_auto(verdict, details, client, threshold=THRESHOLD,
                          low=LOW, group_scores=group_scores, enable=True,
                          scene_whitelist={"host_commentary"})
    check("合格靶子 #6（单簇无先验、0.50 贴边）路由改 drop",
          nv[5][1] == "drop" and s["auto_changed"] == 1, s["auto_changed"])
    check("只改路由三值：cue 对象与分数复用原值",
          nv[5][0] is cues[5] and nv[5][2] == verdict[5][2]
          and len(nv) == len(verdict))
    check("文本/时间轴/结构不动（cue 对象未被修改）",
          cues[5].text == "那么让我们进入正题" and cues[5].start == 5000
          and cues[5].end == 5800)
    check("#4（簇内有 keep 先验）被硬规则挡下：保持 review",
          nv[3][1] == "review"
          and s["gates"].get("hard_rule:cluster_target_prior") == 1, s["gates"])
    check("#5（无分数）被硬规则挡下（score_unavailable）：保持 review",
          nv[4][1] == "review"
          and s["gates"].get("hard_rule:score_unavailable") == 1, s["gates"])
    check("keep/drop/keep 三条非 review 条目从不参与自动",
          all(nv[i] == verdict[i] for i in (0, 1, 2)))
    check("白名单与门禁快照进 summary",
          s["scene_whitelist"] == ["host_commentary"]
          and s["conf_t1"] == 0.98 and s["prob_p1"] == 0.90)
    check("原 verdict 输入不被 apply_auto 修改",
          _verdict_equal(verdict, original_verdict))

    say("  -- 门禁逐项生效 --")

    def _auto_with(spec2, **kw):
        d2 = copy.deepcopy(details)
        v2 = copy.deepcopy(verdict)
        c2 = MockClient(spec=spec2)
        nv2, s2 = VD.apply_auto(v2, d2, c2, threshold=THRESHOLD, low=LOW,
                                group_scores=group_scores, enable=True,
                                scene_whitelist={"host_commentary"}, **kw)
        return nv2, s2, c2

    nv2, s2, _c = _auto_with({"route": {"choice": "drop", "confidence": 0.97,
                                        "p": 0.95}})
    check("confidence 0.97 < T1 0.98 → 低置信 100% 待复核",
          nv2[5][1] == "review" and s2["gates"].get("low_confidence") == 3,
          s2["gates"])
    nv3, s3, _c = _auto_with({"route": {"choice": "drop", "confidence": 0.99,
                                        "p": 0.80}})
    check("P(route)=0.80 < P1 0.90 → 不自动",
          nv3[5][1] == "review" and s3["gates"].get("low_route_prob") == 3,
          s3["gates"])
    nv4, s4, _c = _auto_with({"route": {"choice": "drop", "confidence": 0.99,
                                        "p": 0.95},
                              "quality": {"score": 1.0}})
    check("evidence_quality 展示级 3 < 4 → 不自动（低分始终待复核）",
          nv4[5][1] == "review"
          and s4["gates"].get("low_evidence_quality") == 3, s4["gates"])
    nv5, s5, _c = _auto_with({"route": {"choice": "drop", "confidence": 0.99,
                                        "p": 0.95},
                              "conflict": {"noul": 0.90}})
    check("声学冲突 0.90 → 不得仅凭文本改（保持 review）",
          nv5[5][1] == "review" and s5["gates"].get("evidence_conflict") == 3,
          s5["gates"])
    nv6, s6, _c = _auto_with({"route": {"choice": "drop", "confidence": 0.99,
                                        "p": 0.95},
                              "role": {"choice": "game_dialogue"}})
    check("场景不在白名单 → 不自动",
          nv6[5][1] == "review"
          and s6["gates"].get("scene_not_whitelisted") == 3, s6["gates"])
    nv7, s7, _c = _auto_with({"route": {"choice": "cannot_determine",
                                        "confidence": 0.99, "p": 0.95}})
    check("cannot_determine 永不自动（保持 review）",
          nv7[5][1] == "review"
          and s7["gates"].get("cannot_determine_or_unknown") == 3, s7["gates"])
    nv8, s8, _c = _auto_with({"route": {"choice": "review", "confidence": 0.99,
                                        "p": 0.95}})
    check("自动建议 review = 无操作（kept_review 计数）",
          nv8[5][1] == "review" and s8["auto_changed"] == 0
          and s8["kept_review"] == 3, (s8["auto_changed"], s8["kept_review"]))
    nv9, s9, _c = _auto_with({"route": {"choice": "drop", "confidence": 0.99,
                                        "p": 0.95}},
                             confidence_t1=0.5, prob_p1=0.5)
    check("T1/P1 可显式放宽（骨架参数化，冻结前由 G0 数据定值）",
          nv9[5][1] == "drop" and s9["conf_t1"] == 0.5)

    say("  -- 请求失败：停止扩大自动化 --")
    _bc, bd, bv, bg = big_fixture()
    bv_original = copy.deepcopy(bv)
    client3 = MockClient(spec=spec, fail_after=1)
    nv10, s10 = VD.apply_auto(bv, bd, client3, threshold=THRESHOLD, low=LOW,
                              group_scores=bg, enable=True,
                              scene_whitelist={"host_commentary"})
    check("第一批成功后失败：剩余跳过（skipped=4）、不再发请求（attempted=2）",
          len(client3.calls) == 2 and s10["skipped"] == 4
          and len(s10["errors"]) == 1 and s10["auto_changed"] == 3,
          (len(client3.calls), s10["skipped"], len(s10["errors"]),
           s10["auto_changed"]))
    check("失败即停止扩大：第 2 批之后 7 条保持 review",
          all(nv10[i][1] == "review" for i in range(5, 12))
          and all(nv10[i][1] == "drop" for i in range(2, 5)))
    check("输入 verdict 未被修改", _verdict_equal(bv, bv_original))


# ================================================================ 7) 引擎纯度

def test_purity():
    say("\n== 7) 引擎纯度（不 import 网络/引擎模块）==")
    for mod in (VD, S):
        src = inspect.getsource(mod)
        banned = ("import urllib", "from urllib", "import requests",
                  "from requests", "import socket", "from socket",
                  "import http", "from http", "import onnxruntime",
                  "import numpy", "from numpy", "import subprocess",
                  "import video_toolbox", "from video_toolbox")
        hits = [b for b in banned if b in src]
        check("%s 无网络/引擎/第三方依赖 import" % mod.__name__, not hits, hits)
    check("决策模块只消费 client.decide（无其他出站调用）",
          "client.decide" in inspect.getsource(VD))


# ================================================================ main

def main():
    test_schema_basics()
    test_state_and_batching()
    test_degraded()
    test_assist()
    test_auto()
    test_purity()

    say("\n" + "=" * 62)
    if FAILS:
        say("  结果：%d 项失败" % len(FAILS))
        for x in FAILS:
            say("   · " + x)
    else:
        say("  结果：全部通过")
    say("=" * 62)
    try:
        os.makedirs(OUT, exist_ok=True)
        with open(os.path.join(OUT, "result.txt"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(LINES) + "\n")
    except OSError:
        pass
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
