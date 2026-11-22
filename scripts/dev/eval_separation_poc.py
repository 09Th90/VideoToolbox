# -*- coding: utf-8 -*-
# @version 3.2.0
"""分离 PoC 逐级门禁评测（A 错误归因 → B 人声隔离 → C 目标提取 → D 微调门禁）。

WP5 PoC 评测骨架（2026-11-22）。**架构就位、不跑真实分离**——真实推理需要
torch + modelscope + 分离模型（后期运行时按需安装/下载）；本脚本自带 mock
夹具（``--self-test``），零网络零模型即可全绿，用于验证门禁逻辑本身。

四级门禁（逐级放行，任何一级不过则停在当前级）：

  A 错误归因   残余错误占比统计：BGM / 重叠 / 聚类 / 阈值 / 短句 / 时间轴。
               判定：BGM+重叠 占比 ≥ 30% → 值得进 B（分离才有正收益空间）。
               输入：人工抽检的 (case, 归因桶) 清单（JSON）。
  B 人声隔离   原轨 vs 人声轨 ASR 对比：WER 差 / 精准率差 / 伪影率
               （重复幻觉占比）；有干净参考音轨时算 SI-SDR（numpy 手写）。
               判定：人声轨 WER 降 ≥ 0 且伪影率 ≤ 5% → 进 C。
               输入：原音频 + gold 转写（+ 可选干净人声参考）。
  C 目标提取   CAM++ 选轨纯度：目标轨相似度 margin（target 轨分 − 最高
               非目标轨分）与纯度（选对轨占比）。
               判定：margin ≥ 0.03 且纯度 ≥ 0.9 → 进 D。
               输入：分离产物轨 + 各轨 ground-truth 说话人 + enrollment 模板。
  D 微调门禁   汇总裁决：素材符合度（BGM+重叠 ≥ 30%）且（精准率 ↑ ≥ 10pp
               或 WER 降 ≥ 10pp）且召回下降 ≤ 1pp → 建议「关影子、真实
               分离上线」；否则维持影子或关闭。

用法（cwd = 程序根）::

    tools\\python\\python.exe scripts\\dev\\eval_separation_poc.py --self-test
    tools\\python\\python.exe scripts\\dev\\eval_separation_poc.py --dry-run
    tools\\python\\python.exe scripts\\dev\\eval_separation_poc.py --stage A --input <cases.json>
    tools\\python\\python.exe scripts\\dev\\eval_separation_poc.py --all --input <eval_dir>

真实模式的输入清单格式（eval_dir 下 manifest.json，后期填充）::

    {"cases": [
        {"id": "case01", "audio": "mix01.wav", "gold": "转写文本",
         "error_bucket": "bgm|overlap|cluster|threshold|short|timeline|none",
         "bgm_ratio": 0.4, "overlap_ratio": 0.1,          // A 级
         "clean_ref": "ref01.wav",                        // B 级可选
         "track_gt": {"track_16k_0.wav": "说话人1", ...},  // C 级
         "wer_before": 0.18, "wer_after": 0.08,           // D 级（由 B 汇总）
         "precision_before": 0.71, "precision_after": 0.85,
         "recall_before": 1.00, "recall_after": 0.995}
    ]}

退出码：0 = 全过；1 = 有 FAIL；2 = 真实模式缺输入/依赖（提示后退出）。
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

ROOT = os.getcwd()
SRC_DIR = os.path.join(ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

import numpy as np  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    """记录一项断言并即时打印（与 _selftest_local_asr 同款输出）。"""
    ok = bool(ok)
    RESULTS.append((name, ok, str(detail)))
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name,
                         (" | " + str(detail)[:200]) if detail else ""),
          flush=True)
    return ok


def finish(title):
    fails = [r for r in RESULTS if not r[1]]
    print("=" * 56)
    print("%s: %s（%d 项，FAIL %d）"
          % (title, "PASS" if not fails else "FAIL",
             len(RESULTS), len(fails)))
    return 0 if not fails else 1


# ================================================================ 指标（numpy 手写）


def si_sdr(ref, est):
    """Scale-Invariant SDR（dB）。参考与估计都做零均值，最优增益投影。

    手写实现（B 级人声隔离的客观指标）；ref==est 时返回 +inf 的护栏值
    999.0，避免 JSON 序列化出 Infinity。
    """
    ref = np.asarray(ref, dtype=np.float64).reshape(-1)
    est = np.asarray(est, dtype=np.float64).reshape(-1)
    n = min(len(ref), len(est))
    if n == 0:
        return -99.0
    ref = ref[:n] - ref[:n].mean()
    est = est[:n] - est[:n].mean()
    ref_energy = float(np.dot(ref, ref))
    if ref_energy < 1e-12:
        return -99.0
    alpha = float(np.dot(est, ref)) / ref_energy
    target = alpha * ref
    noise = est - target
    noise_energy = float(np.dot(noise, noise))
    if noise_energy < 1e-12:
        return 999.0
    return 10.0 * math.log10(max(float(np.dot(target, target)), 1e-12)
                             / noise_energy)


def _tokens(text):
    """轻量分词：CJK 逐字成 token，拉丁按连续字母数字成词（PoC 口径）。

    标点不参与对齐（ASR 前后标点漂移不应计入 WER）。
    """
    out = []
    buf = []
    for ch in str(text or ""):
        if ch.isspace():
            if buf:                       # 空白 = 词边界
                out.append("".join(buf))
                buf = []
            continue
        if ord(ch) < 128:
            if ch.isalnum():
                buf.append(ch)
                continue
            if buf:
                out.append("".join(buf))
                buf = []
            continue                    # 标点丢弃
        if buf:
            out.append("".join(buf))
            buf = []
        out.append(ch)                  # CJK 逐字
    if buf:
        out.append("".join(buf))
    return out


def _levenshtein(a, b):
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def wer(ref_text, hyp_text):
    """词级 WER（编辑距离 / 参考词数）；参考为空按 0 处理。"""
    r, h = _tokens(ref_text), _tokens(hyp_text)
    if not r:
        return 0.0 if not h else 1.0
    return min(1.0, _levenshtein(r, h) / len(r))


def precision_recall(ref_text, hyp_text):
    """字符重合口径的精准率 / 召回率（PoC 粗口径；gold n-gram 对齐可后期换）。"""
    r = set(_tokens(ref_text))
    h = set(_tokens(hyp_text))
    if not h:
        return 1.0 if not r else 0.0
    if not r:
        return 0.0, 0.0
    inter = len(r & h)
    return inter / len(h), inter / len(r)


def artifact_rate(hyp_text):
    """伪影率：重复片段（≥6 字的连续块出现 ≥2 次）占总词数比例。

    分离伪影在 ASR 上典型表现为「同一段音频被幻觉成复读」；这里用朴素
    重复块统计近似（PoC 口径，影子期可换更严的 n-gram 复读检测）。
    """
    toks = _tokens(hyp_text)
    if len(toks) < 12:
        return 0.0
    grams = {}
    for n in (6, 8):
        for i in range(len(toks) - n + 1):
            key = " ".join(toks[i:i + n])
            grams.setdefault(key, 0)
            grams[key] += 1
    dup = sum(v - 1 for v in grams.values() if v > 1)
    return min(1.0, dup / max(len(toks), 1))


# ================================================================ A 错误归因


#: 归因桶口径（与 manifest 的 error_bucket 对齐）。
BUCKETS = ("bgm", "overlap", "cluster", "threshold", "short", "timeline",
           "none")

#: A 级放行线：BGM+重叠 占比 ≥ 30%（分离的收益空间）。
STAGE_A_GATE = 0.30


def run_stage_a(cases):
    """A 错误归因：残余错误占比统计。

    输入：cases（每项含 error_bucket / bgm_ratio / overlap_ratio）。
    输出：report{buckets, bgm_overlap_ratio, eligible}。
    """
    buckets = {b: 0 for b in BUCKETS}
    bgm_ratio = overlap_ratio = 0.0
    n = 0
    for c in cases or []:
        b = str(c.get("error_bucket") or "none").strip().lower()
        if b not in buckets:
            b = "none"
        buckets[b] += 1
        bgm_ratio += float(c.get("bgm_ratio") or 0.0)
        overlap_ratio += float(c.get("overlap_ratio") or 0.0)
        n += 1
    if n:
        bgm_ratio /= n
        overlap_ratio /= n
    # 归因桶占比与时长占比双口径取大者（人工抽检粗估时桶数易偏低）
    bucket_ratio = ((buckets["bgm"] + buckets["overlap"]) / n) if n else 0.0
    combined = max(bgm_ratio + overlap_ratio, bucket_ratio)
    return {
        "stage": "A", "cases": n, "buckets": buckets,
        "bgm_overlap_ratio": round(combined, 4),
        "gate": STAGE_A_GATE,
        "eligible": combined >= STAGE_A_GATE,
        "note": "BGM+重叠占比 ≥ %.0f%% 才进 B（分离收益空间）"
                % (STAGE_A_GATE * 100),
    }


# ================================================================ B 人声隔离


#: B 级放行线：WER 不升 + 伪影率 ≤ 5%。
STAGE_B_ARTIFACT_GATE = 0.05


def run_stage_b(cases):
    """B 人声隔离：原轨 vs 人声轨 ASR 对比 + SI-SDR。

    输入：cases（每项含 wer_before / wer_after / hyp_before / hyp_after /
    precision_before / precision_after / 可选 ref_audio+est_audio 实测对）。
    wer/precision 缺省时由 hyp 文本现算（wer() / precision_recall()）。
    SI-SDR：有 clean_ref+est_audio 对时现场读 wav 计算（真实模式），
    mock 夹具直接给样本数组。
    输出：report{wer_gain, precision_gain, artifact, si_sdr, pass}。
    """
    wers_b = wers_a = precs_b = precs_a = rec_b = rec_a = 0.0
    arts = 0.0
    sds = []
    n = 0
    for c in cases or []:
        n += 1
        wb = c.get("wer_before")
        wa = c.get("wer_after")
        if wb is None or wa is None:
            wb = wer(c.get("gold", ""), c.get("hyp_before", ""))
            wa = wer(c.get("gold", ""), c.get("hyp_after", ""))
        wers_b += float(wb)
        wers_a += float(wa)
        pb = c.get("precision_before")
        pa = c.get("precision_after")
        if pb is None or pa is None:
            pb, rb = precision_recall(c.get("gold", ""),
                                      c.get("hyp_before", ""))
            pa, ra = precision_recall(c.get("gold", ""),
                                      c.get("hyp_after", ""))
        else:
            rb = c.get("recall_before", 1.0)
            ra = c.get("recall_after", 1.0)
        precs_b += float(pb)
        precs_a += float(pa)
        rec_b += float(rb)
        rec_a += float(ra)
        arts += float(c.get("artifact")
                      if c.get("artifact") is not None
                      else artifact_rate(c.get("hyp_after", "")))
        pair = c.get("si_sdr_sample")           # (ref 样本, est 样本) 数组对
        if pair:
            sds.append(si_sdr(pair[0], pair[1]))
    report = {
        "stage": "B", "cases": n,
        "wer_before": round(wers_b / n, 4) if n else 0.0,
        "wer_after": round(wers_a / n, 4) if n else 0.0,
        "wer_gain": round((wers_b - wers_a) / n, 4) if n else 0.0,
        "precision_before": round(precs_b / n, 4) if n else 0.0,
        "precision_after": round(precs_a / n, 4) if n else 0.0,
        "precision_gain": round((precs_a - precs_b) / n, 4) if n else 0.0,
        "recall_before": round(rec_b / n, 4) if n else 0.0,
        "recall_after": round(rec_a / n, 4) if n else 0.0,
        "artifact": round(arts / n, 4) if n else 0.0,
        "si_sdr_mean": round(sum(sds) / len(sds), 2) if sds else None,
        "artifact_gate": STAGE_B_ARTIFACT_GATE,
    }
    report["pass"] = (n > 0
                      and report["wer_gain"] >= 0.0
                      and report["artifact"] <= STAGE_B_ARTIFACT_GATE)
    return report


# ================================================================ C 目标提取


#: C 级放行线：margin ≥ 0.03 且选轨纯度 ≥ 0.9。
STAGE_C_MARGIN_GATE = 0.03
STAGE_C_PURITY_GATE = 0.9


def run_stage_c(cases):
    """C 目标提取：CAM++ 选轨纯度与 margin。

    输入：cases（每项含 sims: {轨名: 相似度}, gt: 目标轨名）。真实模式
    由 separation_backend 的选轨结果回填；mock 夹具直接给分值。
    输出：report{margin_mean, purity, pass}。
    """
    margins, hits, n = [], 0, 0
    for c in cases or []:
        n += 1
        sims = {str(k): float(v) for k, v in (c.get("sims") or {}).items()}
        gt = str(c.get("gt") or "")
        if not sims or not gt or gt not in sims:
            continue
        others = [v for k, v in sims.items() if k != gt]
        margin = sims[gt] - max(others) if others else sims[gt]
        margins.append(margin)
        picked = max(sims, key=lambda k: sims[k])
        if picked == gt:
            hits += 1
    purity = (hits / n) if n else 0.0
    margin_mean = (sum(margins) / len(margins)) if margins else 0.0
    return {
        "stage": "C", "cases": n,
        "margin_mean": round(margin_mean, 4),
        "purity": round(purity, 4),
        "margin_gate": STAGE_C_MARGIN_GATE,
        "purity_gate": STAGE_C_PURITY_GATE,
        "pass": (n > 0 and margin_mean >= STAGE_C_MARGIN_GATE
                 and purity >= STAGE_C_PURITY_GATE),
    }


# ================================================================ D 微调门禁


#: D 级门禁：精准率提升 ≥ 10pp（或 WER 降 ≥ 10pp）且召回下降 ≤ 1pp。
STAGE_D_GAIN_GATE = 0.10
STAGE_D_RECALL_DROP_GATE = 0.01


def run_stage_d(rep_a, rep_b, rep_c):
    """D 微调门禁：汇总 A/B/C 产出上线建议。

    判定（全部满足才建议关影子真实上线）：
      ① 素材符合度：A.bgm_overlap_ratio ≥ 30%；
      ② 收益：precision_gain ≥ 10pp **或** wer_gain ≥ 10pp；
      ③ 代价：recall 下降 ≤ 1pp；
      ④ 质量：B.pass 且 C.pass（隔离无伪影、选轨纯度达标）。
    输出：report{verdict: enable|shadow|disable, reasons[]}。
    """
    reasons = []
    rep_a = rep_a or {}
    rep_b = rep_b or {}
    rep_c = rep_c or {}
    if not rep_a.get("eligible"):
        reasons.append("A 未过：BGM+重叠占比 %.1f%% < %.0f%%（收益空间不足）"
                       % (rep_a.get("bgm_overlap_ratio", 0) * 100,
                          STAGE_A_GATE * 100))
    gain = max(rep_b.get("precision_gain", 0.0), rep_b.get("wer_gain", 0.0))
    if gain < STAGE_D_GAIN_GATE:
        reasons.append("D 未过：收益 %.1fpp < %.0fpp（精准率或 WER 改善）"
                       % (gain * 100, STAGE_D_GAIN_GATE * 100))
    drop = rep_b.get("recall_before", 1.0) - rep_b.get("recall_after", 1.0)
    if drop > STAGE_D_RECALL_DROP_GATE:
        reasons.append("D 未过：召回下降 %.2fpp > %.0fpp（漏句代价超线）"
                       % (drop * 100, STAGE_D_RECALL_DROP_GATE * 100))
    if not rep_b.get("pass"):
        reasons.append("B 未过：WER 上升或伪影率超标")
    if not rep_c.get("pass"):
        reasons.append("C 未过：选轨 margin/纯度不达标")
    if reasons:
        # 有收益但未全过 → 维持影子继续收集数据；完全无收益 → 建议关闭
        if gain > 0 and rep_a.get("eligible"):
            verdict = "shadow"
        else:
            verdict = "disable"
    else:
        verdict = "enable"
    return {
        "stage": "D", "verdict": verdict, "reasons": reasons,
        "gain_pp": round(gain * 100, 2),
        "recall_drop_pp": round(drop * 100, 2),
        "note": "enable=关影子真实上线；shadow=维持影子收集数据；"
                "disable=对当前素材关闭分离",
    }


# ================================================================ mock 夹具


def _mock_fixtures():
    """零网络零模型的门禁夹具（--self-test 专用）。

    数值口径：A 级 10 例中 BGM 4 + 重叠 4（占比 80% ≥ 30%）；B 级 WER
    0.18 → 0.08（改善 10pp）、伪影 1%、SI-SDR 用合成样本（est = ref +
    5% 噪声 ≈ 26dB）；C 级 margin 0.51、纯度 1.0；D 级应判 enable。
    """
    ref = np.sin(np.linspace(0, 40 * math.pi, 1600)).astype(np.float64)
    rng = np.random.default_rng(20261122)
    est = ref + 0.05 * rng.standard_normal(len(ref))
    cases_a = [{"error_bucket": b, "bgm_ratio": 0.4, "overlap_ratio": 0.1}
               for b in ("bgm", "bgm", "bgm", "bgm",
                         "overlap", "overlap", "overlap", "overlap",
                         "cluster", "short")]
    cases_b = [{
        "gold": "大家好，欢迎来到今天的直播间",
        "hyp_before": "大家好，欢迎来到今天的直播间",
        "hyp_after": "大家好，欢迎来到今天的直播间",
        "wer_before": 0.18, "wer_after": 0.08,
        "precision_before": 0.71, "precision_after": 0.85,
        "recall_before": 1.00, "recall_after": 0.995,
        "artifact": 0.01, "si_sdr_sample": (ref, est),
    }]
    cases_c = [
        {"sims": {"track_0": 0.82, "track_1": 0.31}, "gt": "track_0"},
        {"sims": {"track_0": 0.79, "track_1": 0.44}, "gt": "track_0"},
    ]
    return cases_a, cases_b, cases_c


# ================================================================ 自检 / dry-run / 真实模式


def self_test():
    """mock 全绿自检：门禁逻辑 + off 零漂移 + 依赖缺失回退（零网络零模型）。"""
    # ---- 指标本身 ----
    ref = np.sin(np.linspace(0, 20 * math.pi, 800))
    est = ref + 0.05 * np.random.default_rng(1).standard_normal(len(ref))
    check("si_sdr 高信噪样本 > 20dB", si_sdr(ref, est) > 20.0,
          "%.2f dB" % si_sdr(ref, est))
    check("si_sdr 全噪声样本 < 0dB",
          si_sdr(ref, np.random.default_rng(2).standard_normal(len(ref))) < 0.0)
    check("WER 相同文本 = 0", wer("你好世界 hello", "你好世界 hello") == 0.0)
    check("WER 一半错 = 0.5", abs(wer("你好世界", "你好天空") - 0.5) < 1e-9,
          "%.3f" % wer("你好世界", "你好天空"))
    pr, rc = precision_recall("你好世界", "你好世界啊")
    check("precision_recall 口径", (pr, rc) == (0.8, 1.0), "p=%.3f r=%.3f" % (pr, rc))
    check("artifact_rate 复读检出",
          artifact_rate(" ".join(["ABCDEF"] * 14)) > 0.0)

    # ---- A/B/C/D 门禁（mock 夹具）----
    ca, cb, cc = _mock_fixtures()
    ra = run_stage_a(ca)
    check("A 级放行（BGM+重叠 ≥ 30%）", ra["eligible"],
          "ratio=%.2f" % ra["bgm_overlap_ratio"])
    rb = run_stage_b(cb)
    check("B 级放行（WER 不升 + 伪影 ≤ 5%）", rb["pass"],
          "wer_gain=%.2f artifact=%.3f si_sdr=%s"
          % (rb["wer_gain"], rb["artifact"], rb["si_sdr_mean"]))
    check("B 级 SI-SDR 合成样本 > 20dB",
          (rb["si_sdr_mean"] or -99) > 20.0, str(rb["si_sdr_mean"]))
    rc_ = run_stage_c(cc)
    check("C 级放行（margin ≥ 0.03 + 纯度 ≥ 0.9）", rc_["pass"],
          "margin=%.2f purity=%.2f" % (rc_["margin_mean"], rc_["purity"]))
    rd = run_stage_d(ra, rb, rc_)
    check("D 级裁决 = enable", rd["verdict"] == "enable",
          "verdict=%s reasons=%s" % (rd["verdict"], rd["reasons"]))
    # D 级回退分支：收益不足 → 维持影子；无收益 → 建议关闭
    rb_weak = run_stage_b([dict(cb[0], wer_before=0.10, wer_after=0.09,
                                precision_before=0.80,
                                precision_after=0.81)])
    rd_shadow = run_stage_d(ra, rb_weak, rc_)
    check("D 级弱收益 → 维持影子", rd_shadow["verdict"] == "shadow",
          rd_shadow["verdict"])
    ra_poor = run_stage_a([{"error_bucket": "short"}])
    rd_disable = run_stage_d(ra_poor, rb_weak, rc_)
    check("D 级无收益无素材 → 建议关闭", rd_disable["verdict"] == "disable",
          rd_disable["verdict"])

    # ---- off 零漂移：protocol._asr_separate_audio off 直通 ----
    try:
        from core.asr.protocol import _asr_separate_audio

        class _Obj:                       # separate=False 的转录对象桩
            separate = False

        got = _asr_separate_audio("x.wav", _Obj())
        check("protocol off 直通 [(None, 原轨)]",
              got == [(None, "x.wav")], repr(got))

        class _OffNone:
            separate = None               # 未挂 → 落配置读（mock 空配置=off）

        got2 = _asr_separate_audio("y.wav", _OffNone())
        check("protocol 开关未挂 → 落配置（off）",
              got2 == [(None, "y.wav")], repr(got2))
    except Exception as e:  # noqa: BLE001
        check("protocol off 直通", False, "import/调用失败：%s" % e)

    # ---- 默认全影子：_asr_separation_cfg({}) 默认 shadow=True ----
    try:
        from core.asr.protocol import _asr_separation_cfg
        cfg = _asr_separation_cfg({})
        check("分离子配置默认 shadow=True", cfg.get("shadow") is True,
              repr(cfg.get("shadow")))
        check("分离子配置默认模型 MossFormer2-8k",
              "mossformer2" in str(cfg.get("model")), str(cfg.get("model")))
    except Exception as e:  # noqa: BLE001
        check("分离子配置默认值", False, "失败：%s" % e)

    # ---- 依赖缺失 graceful degraded：后端探针 + BackendUnavailable ----
    try:
        from core.asr.separation_backend import BackendUnavailable, probe
        dep = probe()
        check("后端探针零 import 不崩", isinstance(dep, dict), repr(dep))
        if not (dep.get("torch") and dep.get("modelscope")):
            # 当前栈无 torch：separate() 必须干净地 raise BackendUnavailable
            try:
                from core.asr.separation_backend import separate
                separate("nonexistent.wav", {"shadow": True}, asr_obj=None)
                check("依赖缺失 → BackendUnavailable", False,
                      "未抛异常（不该发生）")
            except BackendUnavailable:
                check("依赖缺失 → BackendUnavailable", True, "按预期抛出")
            except Exception as e:  # noqa: BLE001
                check("依赖缺失 → BackendUnavailable", False,
                      "抛了别的异常：%s" % e)
        else:
            check("依赖缺失 → BackendUnavailable", True,
                  "本机已装 torch/modelscope，跳过该负向用例")
    except Exception as e:  # noqa: BLE001
        check("后端探针/回退自测", False, "失败：%s" % e)

    return finish("SELF-TEST")


def dry_run():
    """只读配置与后端可用性，打印四级门禁计划，不跑真实分离。"""
    print("=" * 56)
    print("[DRY-RUN] 分离 PoC 评测计划（只读，零网络零模型）")
    try:
        from core.asr.protocol import asr_separate_of, _asr_separation_cfg
        cfg = _asr_separation_cfg()
        print("  asr_separate 总开关   : %s" % ("on" if asr_separate_of()
                                                else "off（默认）"))
        print("  asr_separation_shadow : %s（默认 True=影子）"
              % cfg.get("shadow"))
        print("  separation model      : %s" % cfg.get("model"))
        print("  num_speakers / vocals : %s / %s"
              % (cfg.get("num_speakers"), cfg.get("vocals")))
        print("  target 模板           : %r" % cfg.get("target"))
        print("  min_sim / margin      : %s / %s"
              % (cfg.get("min_sim"), cfg.get("margin")))
        print("  cache / timeout       : %s / %ss"
              % (cfg.get("cache"), cfg.get("timeout")))
    except Exception as e:  # noqa: BLE001
        print("  配置读取失败：%s" % e)
    try:
        from core.asr.separation_backend import probe, stats
        dep = probe()
        print("  后端探针（零 import）  : torch=%s modelscope=%s demucs=%s"
              % (dep.get("torch"), dep.get("modelscope"), dep.get("demucs")))
        print("  分离主链可用          : %s"
              % ("yes" if dep.get("torch") and dep.get("modelscope")
                 else "no（缺 torch/modelscope → 调用方 degraded 回退原轨）"))
        print("  进程内统计            : %s" % stats())
    except Exception as e:  # noqa: BLE001
        print("  后端探针失败：%s" % e)
    print("  门禁计划              : A(BGM+重叠≥30%) → B(WER不升+伪影≤5%)"
          " → C(margin≥0.03+纯度≥0.9) → D(收益≥10pp 且召回降≤1pp)")
    print("=" * 56)
    return 0


def run_real(stage, input_path):
    """真实模式骨架：读 manifest → 跑对应级门禁（需要真实素材 + torch 运行时）。

    架构就位、真实推理留接口：A/B 级的 ASR 对比在这里接引擎转录
    （protocol._asr_separate_audio + 分离产物轨逐轨提交），C 级读
    separation_backend 选轨结果。素材/依赖缺失时退出码 2 并说明，绝不
    伪造结果。
    """
    if not input_path or not os.path.isfile(input_path):
        print("[REAL] 输入缺失：%r——真实模式需要 eval_dir/manifest.json"
              "（格式见本文件头注）" % (input_path,))
        return 2
    from core.asr.separation_backend import probe
    dep = probe()
    if not (dep.get("torch") and dep.get("modelscope")):
        print("[REAL] torch/modelscope 未安装（后期运行时按需安装），"
              "真实分离不可跑；先用 --self-test 验证门禁逻辑")
        return 2
    with open(input_path, encoding="utf-8") as fh:
        data = json.load(fh)
    cases = data.get("cases") or []
    if stage == "A":
        rep = run_stage_a(cases)
    elif stage == "B":
        # 真实 ASR 对比接口位：对每例 mix / vocals 轨各跑一次引擎转录再汇总
        rep = run_stage_b(cases)
    elif stage == "C":
        rep = run_stage_c(cases)
    else:
        reps = [run_stage_a(cases), run_stage_b(cases), run_stage_c(cases)]
        rep = run_stage_d(*reps)
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    ok = rep.get("pass", rep.get("eligible", True)) if stage != "D" \
        else rep.get("verdict") == "enable"
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="分离 PoC 逐级门禁评测")
    ap.add_argument("--self-test", action="store_true",
                    help="mock 全绿自检（零网络零模型）")
    ap.add_argument("--dry-run", action="store_true",
                    help="只读配置与后端可用性，不跑评测")
    ap.add_argument("--stage", choices=["A", "B", "C", "D", "all"],
                    help="真实模式跑某一级门禁")
    ap.add_argument("--input", default="",
                    help="真实模式输入：cases.json 或 eval_dir/manifest.json")
    args = ap.parse_args()
    if args.self_test:
        return self_test()
    if args.dry_run:
        return dry_run()
    if args.stage:
        return run_real(args.stage, args.input)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
