#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# @version 3.3.1
"""G0 基线报告器：冻结校验 + 只读评估 + 可重复哈希（eval 设计落地序 step3）。

定位：WP1 `voiceprint_filter_eval.py` 提供指标口径（precision/recall/F1、
hard_flags 切片、split 分列、效率采集）；本脚本消费它，不重复实现。本脚本
负责「可复现实验」的外壳——G0 架构件之一：

  * lock 冻结校验：manifest 全文与每片 media/srt 的 sha256 逐项比对，
    不符拒绝出报告（不伪造基线数字）。
  * reproducibility 快照：seed / manifest_sha256 / inputs（逐片哈希）/
    versions（git describe、评估器版本、Schema、模型、config_snapshot）。
  * 结构不变量（--emit-products 产物模式）：cue 账目平衡、时间轴不动、
    BOM/换行原样；只读模式该字段为 null。
  * 报告哈希自证：report_sha256（canonical 口径，排除计时字段）写
    `<报告>.sha`，同输入重跑逐字节一致。
  * 阈值网格扫描（P0③ 廉价校准路径）：读已保存 decisions + SV 的
    `_state_for_score` 逐阈值重算 state，不重提特征。

lock（version=1，由 --build-lock 生成，随 manifest 一起冻结）：
{
  "version": 1,
  "manifest": "labeled.json",
  "manifest_sha256": "...",
  "items": [{"item_id": "video-001",
             "media_sha256": "...", "srt_sha256": "..."}]
}

用法：
  # 冻结 manifest（投喂时执行一次；写入 <manifest>.lock.json）
  tools/python/python.exe scripts/dev/voiceprint_baseline.py \
      --manifest labeled.json --build-lock

  # 只读评估已有决策 -> 报告（--report 才写盘，并同时写 <报告>.sha）
  tools/python/python.exe scripts/dev/voiceprint_baseline.py \
      --manifest labeled.json --decisions decisions.json --report baseline.json

  # 只读重跑本地模型（tracemalloc + perf_counter 效率采集；不写筛选产物）
  tools/python/python.exe scripts/dev/voiceprint_baseline.py \
      --manifest labeled.json --run --report baseline.json

  # 产物模式：filter_srt 真写 data/eval/tmp 临时产物 -> 结构不变量，用完即删
  tools/python/python.exe scripts/dev/voiceprint_baseline.py \
      --manifest labeled.json --run --emit-products

  # 阈值网格扫描（与 --decisions 搭配）
  tools/python/python.exe scripts/dev/voiceprint_baseline.py \
      --manifest labeled.json --decisions d.json \
      --threshold-grid "0.55:0.45,0.60:0.50,0.65:0.55"

  # 报告计划（不执行；无 manifest 时输出「待数据」）
  tools/python/python.exe scripts/dev/voiceprint_baseline.py --dry-run

  # 合成数据自测（零真实音频 / 零网络；不代表业务精准率）
  tools/python/python.exe scripts/dev/voiceprint_baseline.py --self-test

exit code：0=报告产出（或 dry-run / self-test）；1=门禁性未过（lock 不符、
manifest 校验失败——拒绝出报告）；2=执行错误（文件缺失 / IO / 参数错误）。

确定性承诺：报告正文不含绝对路径、时间戳；`--run` 的 efficiency 计时字段
参与展示但被排除在 report_sha256 之外（HASH_EXCLUDES）——因此同输入重跑
（--decisions 路径）哈希逐字节一致，可重复自证。
"""
import argparse
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)
sys.path.insert(0, HERE)
os.environ.setdefault("VT_NO_PIPELINE", "1")
os.environ.setdefault("VT_NO_SYNC", "1")
os.environ.setdefault("VT_NO_VP_SYNC", "1")

import features.voiceprint.speaker_voiceprint as SV  # noqa: E402
import voiceprint_filter_eval as FE  # noqa: E402
import subtitle_editor_core as secore  # noqa: E402

EVALUATOR_VERSION = "baseline-1"
TEMPLATE_SCHEMA = "manifest-v1.1"
SEED = 0
#: 参与 report_sha256 时剔除的非确定字段（--run 计时每次必然不同）。
HASH_EXCLUDES = ("efficiency",)
_CHUNK = 1 << 20  # 1MB 流式哈希块
_TMP_ROOT = os.path.join(ROOT, "data", "eval", "tmp")


# ---------------------------------------------------------------- 哈希与锁


def sha256_file(path):
    """流式计算文件 sha256（视频可能数 GB，不整读）。"""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(_CHUNK)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def canonical_json(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2,
                      allow_nan=False)


def report_payload(report):
    """canonical 口径：剔除 report_sha256 与计时字段后的可重复正文。"""
    payload = {k: v for k, v in report.items() if k not in ("report_sha256",)
               and k not in HASH_EXCLUDES}
    return payload


def report_sha256(report):
    return hashlib.sha256(canonical_json(report_payload(report)).encode("utf-8")).hexdigest()


def build_lock(manifest_path):
    """由当前 manifest 与其引用的 media/srt 生成冻结 lock（不校验内容）。"""
    with open(manifest_path, encoding="utf-8") as fh:
        manifest = FE.validate_manifest(json.load(fh))
    items = []
    for item in manifest["items"]:
        for key in ("media", "srt"):
            if not os.path.isfile(item[key]):
                raise FileNotFoundError("%s：%s 不存在：%s"
                                        % (item["id"], key, item[key]))
        items.append({"item_id": item["id"],
                      "media_sha256": sha256_file(item["media"]),
                      "srt_sha256": sha256_file(item["srt"])})
    return {"version": 1,
            "manifest": os.path.basename(manifest_path),
            "manifest_sha256": sha256_file(manifest_path),
            "items": items}


def verify_lock(manifest_path, lock_path):
    """逐项比对：manifest 全文 sha256 + 每片 media/srt sha256。

    返回 (ok, problems)；problems 每条是一句可定位的人话。lock 文件本身
    缺失/格式错也算不符——G0 冻结语义不允许「没有锁的评估」。
    """
    problems = []
    if not os.path.isfile(lock_path):
        return False, ["lock 文件不存在：%s（先 --build-lock 冻结）" % lock_path]
    try:
        with open(lock_path, encoding="utf-8") as fh:
            lock = json.load(fh)
    except (OSError, ValueError) as exc:
        return False, ["lock 文件不可读/非 JSON：%s" % exc]
    if not isinstance(lock, dict) or lock.get("version") != 1:
        return False, ["lock 必须 version=1"]
    manifest_sha = sha256_file(manifest_path)
    if lock.get("manifest_sha256") != manifest_sha:
        problems.append("manifest_sha256 与 lock 不符（manifest 被改动？）")
    with open(manifest_path, encoding="utf-8") as fh:
        manifest = FE.validate_manifest(json.load(fh))
    locked = {x.get("item_id"): x for x in lock.get("items") or []
              if isinstance(x, dict)}
    for item in manifest["items"]:
        entry = locked.get(item["id"])
        if entry is None:
            problems.append("%s：lock 中缺少该片" % item["id"])
            continue
        for key, field in (("media", "media_sha256"), ("srt", "srt_sha256")):
            if not os.path.isfile(item[key]):
                problems.append("%s.%s 不存在：%s" % (item["id"], key, item[key]))
                continue
            actual = sha256_file(item[key])
            if entry.get(field) != actual:
                problems.append("%s：%s sha256 与 lock 不符" % (item["id"], key))
    return (not problems), problems


# ------------------------------------------------------- reproducibility


def _git_describe():
    """只读 git 描述；失败（无 git/无 tag）返回 None，不阻塞报告。"""
    try:
        out = subprocess.run(["git", "describe", "--tags"], cwd=ROOT,
                             capture_output=True, text=True, timeout=15)
        if out.returncode == 0:
            return out.stdout.strip() or None
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def _model_info():
    """编码器名 + 实际模型文件 sha256；模型缺失时显式 null（不猜）。"""
    info = {"encoder_name": SV.MODEL_NAME, "model_sha256": None,
            "model_present": os.path.isfile(SV.MODEL_PATH)}
    if info["model_present"]:
        info["model_sha256"] = sha256_file(SV.MODEL_PATH)
    return info


def config_snapshot(mode, threshold=None, low=None, threshold_source=None,
                    results=None):
    """显式记录评估时的阈值/聚类口径；--run 有实际结果时以实际值为准。"""
    if results:
        thrs = {r.get("threshold") for r in results if isinstance(r, dict)}
        lows = {r.get("low") for r in results if isinstance(r, dict)}
        sources = sorted({str(r.get("threshold_source")) for r in results
                          if isinstance(r, dict) and r.get("threshold_source")})
        if len(thrs) == 1 and None not in thrs:
            threshold = threshold if threshold is not None else thrs.pop()
        if len(lows) == 1 and None not in lows:
            low = low if low is not None else lows.pop()
        if sources and threshold_source is None:
            threshold_source = sources
    return {
        "threshold": SV.DEFAULT_THRESHOLD if threshold is None else float(threshold),
        "low": SV.DEFAULT_LOW if low is None else float(low),
        "cluster_threshold": float(SV.CLUSTER_THRESHOLD),
        "cluster_min_seconds": float(SV.CLUSTER_MIN_SECONDS),
        "mode": mode,
        "min_keep_ratio": 0,          # 评估口径固定关闭误杀熔断
        "threshold_source": threshold_source or "explicit_or_factory",
    }


def reproducibility(manifest_path, manifest, mode, threshold=None, low=None,
                    results=None, threshold_source=None):
    inputs = []
    for item in manifest["items"]:
        inputs.append({
            "item_id": item["id"],
            "media_sha256": sha256_file(item["media"]) if os.path.isfile(item["media"]) else None,
            "srt_sha256": sha256_file(item["srt"]) if os.path.isfile(item["srt"]) else None,
        })
    return {
        "seed": SEED,
        "manifest_sha256": sha256_file(manifest_path),
        "inputs": inputs,
        "versions": {
            "toolbox_git_describe": _git_describe(),
            "evaluator_version": EVALUATOR_VERSION,
            "template_schema": TEMPLATE_SCHEMA,
            "filter_eval_version": "wp1-eval-1",
            "model": _model_info(),
            "config_snapshot": config_snapshot(
                mode, threshold, low, threshold_source, results),
        },
    }


# ------------------------------------------------------------- 结构不变量


def _srt_index_sequence(text):
    """提取产物 SRT 的块编号序列（独立数字行且下一行是时间行）。"""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    import re as _re
    time_re = _re.compile(r"^\s*\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}\s*-->\s*")
    seq, i, n = [], 0, len(lines)
    while i < n:
        if lines[i].strip().isdigit() and i + 1 < n and time_re.match(lines[i + 1]):
            seq.append(int(lines[i].strip()))
        i += 1
    return seq


def compute_structure_invariants(src_srt, product_paths, decisions):
    """比对原 SRT、决策与产物：cue 账目平衡 / 时间轴不动 / 风格原样。

    口径（G1-3 消费）：
      * cue_count_preserved_pct —— 决策为 keep/review 的 (start,end) 多重集
        在产物（正式 + 待复核）中的覆盖率；100% = 无 cue 凭空丢失。
      * timeline_unchanged_pct —— 产物 cue 中时间轴与决策来源一致的比例；
        100% = 产物没有挪动时间轴。
      * newline_bom_preserved —— 产物换行风格与 BOM 与源一致。
      * index_renumbered —— 产物是否采用连续 1..N 重编号（SubtitleDoc.dump
        的既定行为；有丢弃时与原编号错位属预期，G1-3 不以它为门禁条件）。
    """
    from collections import Counter
    src_doc = secore.SubtitleDoc()
    src_doc.load_file(src_srt)
    expected = Counter()
    for d in decisions:
        if not isinstance(d, dict) or d.get("state") not in ("keep", "review"):
            continue
        start, end = d.get("start"), d.get("end")
        if isinstance(start, (int, float)) and isinstance(end, (int, float)):
            expected[(int(start), int(end))] += 1
    produced = Counter()
    style_ok = True
    renumbered = False
    for path in product_paths:
        doc = secore.SubtitleDoc()
        doc.load_file(path)
        for cue in doc.cues:
            produced[(int(cue.start), int(cue.end))] += 1
        if doc.newline != src_doc.newline or doc.has_bom != src_doc.has_bom:
            style_ok = False
        with open(path, "rb") as fh:
            raw = fh.read()
        text = raw.decode("utf-8-sig", errors="replace")
        seq = _srt_index_sequence(text)
        if seq and seq == list(range(1, len(seq) + 1)) and len(seq) < len(src_doc.cues):
            renumbered = True
    total_expected = sum(expected.values())
    total_produced = sum(produced.values())
    matched = sum((expected & produced).values())
    return {
        "cue_count_preserved_pct": (round(100.0 * matched / total_expected, 4)
                                    if total_expected else None),
        "timeline_unchanged_pct": (round(100.0 * matched / total_produced, 4)
                                   if total_produced else None),
        "newline_bom_preserved": bool(style_ok) if product_paths else None,
        "index_renumbered": renumbered,
        "expected_keep_review": total_expected,
        "produced_cues": total_produced,
    }


# ------------------------------------------------------------ 报告构建


def build_report(manifest_path, manifest, results, mode, *,
                 structure=None, grid=None, threshold=None, low=None,
                 threshold_source=None):
    """评估（复用 FE.evaluate）+ reproducibility + 哈希自证，纯内存。"""
    metrics = FE.evaluate(manifest, results, mode)
    report = {
        "schema_version": 1,
        "kind": "voiceprint_baseline_report",
        "status": "ok",
        "hash_scope": ("report_sha256 为 canonical 口径（sort_keys，排除 %s）"
                       % ", ".join(HASH_EXCLUDES)),
    }
    for key in ("dataset_id", "labeling_guide_version", "provenance"):
        if key in manifest:
            report[key] = manifest[key]
    report["reproducibility"] = reproducibility(
        manifest_path, manifest, mode, threshold, low, results, threshold_source)
    report["metrics"] = metrics
    report["structure_invariants"] = structure
    if grid is not None:
        report["threshold_grid"] = grid
    report["report_sha256"] = report_sha256(report)
    return report


def write_report(report, path):
    """写报告 JSON（含 report_sha256 键）+ <报告>.sha（sha256sum 风格）。"""
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(canonical_json(report) + "\n")
    sha_path = path + ".sha"
    with open(sha_path, "w", encoding="utf-8") as fh:
        fh.write("%s  %s\n" % (report["report_sha256"],
                               os.path.basename(path)))
    return sha_path


# ------------------------------------------------------- 阈值网格扫描


def rescore_states(results, threshold, low):
    """用 SV._state_for_score 逐条重算 state（不重提特征）。

    score 缺失/None/NaN 一律 review，与决策器 `decide()` 的 NaN 分支一致。
    """
    out = copy.deepcopy(results)
    for result in out:
        decisions = result.get("decisions") if isinstance(result, dict) else None
        if not isinstance(decisions, list):
            continue
        for d in decisions:
            score = d.get("score")
            if (isinstance(score, (int, float)) and not isinstance(score, bool)):
                d["state"] = SV._state_for_score(float(score), threshold, low)
            else:
                d["state"] = "review"
    return out


def threshold_grid_scan(manifest, results, grid, mode):
    """逐 (threshold, low) 重算 state 并复用 FE.evaluate 聚合精简指标。"""
    scan = []
    for threshold, low in grid:
        resc = rescore_states(results, threshold, low)
        rep = FE.evaluate(manifest, resc, mode)
        point = {"threshold": float(threshold), "low": float(low)}
        for scope in ("cue", "duration"):
            m = rep["overall"][scope]
            point[scope] = {k: m.get(k) for k in
                            ("precision", "recall", "f1", "false_keep",
                             "false_drop", "review_rate")}
        scan.append(point)
    return scan


def parse_grid(text):
    """'0.55:0.45,0.60:0.50' -> [(0.55,0.45), ...]；格式错抛 ValueError。"""
    grid = []
    for part in (text or "").split(","):
        part = part.strip()
        if not part:
            continue
        bits = part.split(":")
        if len(bits) != 2:
            raise ValueError("阈值网格项必须是 threshold:low：%s" % part)
        grid.append((float(bits[0]), float(bits[1])))
    if not grid:
        raise ValueError("阈值网格为空")
    return grid


# ---------------------------------------------------------------- 自测


def run_self_test():
    """mock 合成 manifest/decisions/lock，全断言零真实音频、零网络。"""
    import re as _re
    results_log = []

    def check(name, cond):
        results_log.append((name, bool(cond)))
        assert cond, "自测失败：%s" % name

    with tempfile.TemporaryDirectory() as tmp:
        # -- 合成素材：假 media 字节 + 真 SRT 文本（含 BOM/CRLF 的一个变体）
        srt_text = ("1\n00:00:01,000 --> 00:00:02,000\n甲\n\n"
                    "2\n00:00:02,000 --> 00:00:03,000\n乙\n\n"
                    "3\n00:00:03,000 --> 00:00:04,000\n丙\n\n")
        srt_b = ("1\n00:00:01,000 --> 00:00:02,500\nだ\n\n"
                 "2\n00:00:02,000 --> 00:00:03,000\nに\n\n")
        media_a = os.path.join(tmp, "a.mp4")
        srt_a = os.path.join(tmp, "a.srt")
        media_b = os.path.join(tmp, "b.mp4")
        srt_b_path = os.path.join(tmp, "b.srt")
        with open(media_a, "wb") as fh:
            fh.write(b"\x00\x01fake-media-a" * 64)
        with open(srt_a, "wb") as fh:
            fh.write(b"\xef\xbb\xbf" + srt_text.replace("\n", "\r\n").encode("utf-8"))
        with open(media_b, "wb") as fh:
            fh.write(b"\x00\x02fake-media-b" * 64)
        with open(srt_b_path, "wb") as fh:
            fh.write(srt_b.encode("utf-8"))
        manifest = {
            "version": 1,
            "dataset_id": "synthetic-baseline-01",
            "labeling_guide_version": "lg-0",
            "items": [
                {"id": "a", "media": media_a, "srt": srt_a,
                 "language": "zh", "templates": ["合成主播"], "split": "train",
                 "cues": [{"num": 1, "label": "target", "hard_flags": ["bgm"]},
                          {"num": 2, "label": "non_target"},
                          {"num": 3, "label": "overlap"}]},
                {"id": "b", "media": media_b, "srt": srt_b_path,
                 "language": "ja", "templates": ["合成主播"], "split": "test",
                 "cues": [{"num": 1, "label": "target"},
                          {"num": 2, "label": "non_target"}]},
            ],
        }
        manifest_path = os.path.join(tmp, "labeled.json")
        with open(manifest_path, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, ensure_ascii=False)

        decisions = [
            {"id": "a", "decisions": [
                {"num": 1, "state": "keep", "start": 1000, "end": 2000,
                 "duration_ms": 1000, "score": 0.72, "source": "synthetic",
                 "reason": "", "speaker": "说话人1", "cluster": 0},
                {"num": 2, "state": "review", "start": 2000, "end": 3000,
                 "duration_ms": 1000, "score": 0.50, "source": "synthetic",
                 "reason": "borderline", "speaker": "说话人2", "cluster": 1},
                {"num": 3, "state": "drop", "start": 3000, "end": 4000,
                 "duration_ms": 1000, "score": None, "source": "synthetic",
                 "reason": "", "speaker": "", "cluster": -1}]},
            {"id": "b", "decisions": [
                {"num": 1, "state": "keep", "start": 1000, "end": 2500,
                 "duration_ms": 1500, "score": 0.65, "source": "synthetic",
                 "reason": "", "speaker": "", "cluster": -1},
                {"num": 2, "state": "drop", "start": 2000, "end": 3000,
                 "duration_ms": 1000, "score": 0.30, "source": "synthetic",
                 "reason": "", "speaker": "", "cluster": -1}]},
        ]
        decisions_path = os.path.join(tmp, "decisions.json")
        with open(decisions_path, "w", encoding="utf-8") as fh:
            json.dump({"results": decisions}, fh, ensure_ascii=False)

        # 1) lock 生成 -> 校验通过；篡改 -> 逐项拒绝
        lock = build_lock(manifest_path)
        lock_path = os.path.join(tmp, "labeled.lock.json")
        with open(lock_path, "w", encoding="utf-8") as fh:
            json.dump(lock, fh, ensure_ascii=False)
        ok, problems = verify_lock(manifest_path, lock_path)
        check("lock 初次校验通过", ok and not problems)
        bad_lock = copy.deepcopy(lock)
        bad_lock["items"][0]["srt_sha256"] = "0" * 64
        bad_path = os.path.join(tmp, "bad.lock.json")
        with open(bad_path, "w", encoding="utf-8") as fh:
            json.dump(bad_lock, fh, ensure_ascii=False)
        ok, problems = verify_lock(manifest_path, bad_path)
        check("lock srt 篡改被拒", not ok and any("srt" in p for p in problems))
        tampered = copy.deepcopy(manifest)
        tampered["items"][0]["cues"][0]["label"] = "non_target"
        tampered_path = os.path.join(tmp, "tampered.json")
        with open(tampered_path, "w", encoding="utf-8") as fh:
            json.dump(tampered, fh, ensure_ascii=False)
        ok, problems = verify_lock(tampered_path, lock_path)
        check("manifest 内容篡改被拒",
              not ok and any("manifest_sha256" in p for p in problems))
        ok, problems = verify_lock(manifest_path,
                                   os.path.join(tmp, "missing.lock.json"))
        check("lock 缺失被拒", not ok)

        # 2) 报告构建：reproducibility 快照齐全
        report = build_report(manifest_path, manifest, decisions, "precision")
        rep = report["reproducibility"]
        check("seed 登记", isinstance(rep.get("seed"), int))
        check("manifest_sha256 快照", rep["manifest_sha256"] == lock["manifest_sha256"])
        check("inputs 逐片哈希",
              len(rep["inputs"]) == 2
              and all(x["media_sha256"] and x["srt_sha256"] for x in rep["inputs"]))
        versions = rep["versions"]
        for key in ("toolbox_git_describe", "evaluator_version",
                    "template_schema", "model", "config_snapshot"):
            check("versions.%s 存在" % key, key in versions)
        snap = versions["config_snapshot"]
        for key in ("threshold", "low", "cluster_threshold",
                    "cluster_min_seconds", "mode", "min_keep_ratio"):
            check("config_snapshot.%s 显式" % key, key in snap and snap[key] is not None)
        check("config_snapshot 阈值与决策器常量一致",
              snap["threshold"] == SV.DEFAULT_THRESHOLD
              and snap["cluster_min_seconds"] == SV.CLUSTER_MIN_SECONDS)
        check("structure_invariants 只读模式为 null",
              report["structure_invariants"] is None)
        check("metrics 复用 FE.evaluate",
              report["metrics"]["overall"]["cue"]["support"]["total"] == 4)

        # 3) 报告哈希可重复：同输入两次构建逐字节一致；输入变化则哈希变化
        report2 = build_report(manifest_path, manifest, decisions, "precision")
        check("同输入重跑哈希一致",
              report["report_sha256"] == report2["report_sha256"]
              and report["report_sha256"])
        other = copy.deepcopy(decisions)
        other[0]["decisions"][0]["state"] = "drop"
        report3 = build_report(manifest_path, manifest, other, "precision")
        check("输入变化哈希变化",
              report3["report_sha256"] != report["report_sha256"])

        # 4) 报告写盘 + .sha 交叉一致
        report_path = os.path.join(tmp, "baseline.json")
        sha_path = write_report(report, report_path)
        with open(sha_path, encoding="utf-8") as fh:
            sha_line = fh.read().split()[0]
        check(".sha 与 report_sha256 一致", sha_line == report["report_sha256"])
        with open(report_path, encoding="utf-8") as fh:
            text = fh.read()
        m = _re.search(r'"report_sha256": "([0-9a-f]{64})"', text)
        check("报告文件含哈希且一致", m and m.group(1) == report["report_sha256"])

        # 5) 阈值网格：_state_for_score 重算 state，指标随阈值变化
        loaded = FE.load_saved_results(decisions_path)
        scan = threshold_grid_scan(manifest, loaded,
                                   [(SV.DEFAULT_THRESHOLD, SV.DEFAULT_LOW),
                                    (0.50, 0.40), (0.20, 0.10)], "precision")
        check("网格 3 点", len(scan) == 3)
        first = rescore_states(loaded, SV.DEFAULT_THRESHOLD, SV.DEFAULT_LOW)
        rescored = {d["num"]: d["state"]
                    for d in first[0]["decisions"]}
        expect = {1: SV._state_for_score(0.72, SV.DEFAULT_THRESHOLD, SV.DEFAULT_LOW),
                  2: SV._state_for_score(0.50, SV.DEFAULT_THRESHOLD, SV.DEFAULT_LOW),
                  3: "review"}  # score=None -> review（与 NaN 分支一致）
        check("重算 state 与 _state_for_score 一致", rescored == expect)
        loose = rescore_states(loaded, 0.50, 0.40)
        check("放宽阈值后 review 转 keep",
              loose[0]["decisions"][1]["state"] == "keep")
        f1_default = scan[0]["cue"]["f1"]
        f1_loose = scan[1]["cue"]["f1"]
        check("F1 随阈值变化", f1_default != f1_loose)
        try:
            parse_grid("0.55")
        except ValueError:
            pass
        else:
            raise AssertionError("非法网格项未被拒绝")

        # 6) 结构不变量：产物=正式(keep)+待复核(review)，100/100/风格一致
        prod_main = os.path.join(tmp, "prod_main.srt")
        prod_review = os.path.join(tmp, "prod_review.srt")
        with open(prod_main, "wb") as fh:
            fh.write(b"\xef\xbb\xbf" + ("1\n00:00:01,000 --> 00:00:02,000\n甲\n\n"
                                        ).replace("\n", "\r\n").encode("utf-8"))
        with open(prod_review, "wb") as fh:
            fh.write(b"\xef\xbb\xbf" + ("1\n00:00:02,000 --> 00:00:03,000\n乙\n\n"
                                        ).replace("\n", "\r\n").encode("utf-8"))
        a_decisions = decisions[0]["decisions"]
        si = compute_structure_invariants(
            srt_a, [prod_main, prod_review], a_decisions)
        check("结构不变量 cue 账目 100%",
              si["cue_count_preserved_pct"] == 100.0, )
        check("结构不变量时间轴 100%", si["timeline_unchanged_pct"] == 100.0)
        check("BOM/换行保留", si["newline_bom_preserved"] is True)
        check("产物重编号记录", si["index_renumbered"] is True)
        # 负例：待复核产物缺失 -> 账目 50%
        si_bad = compute_structure_invariants(srt_a, [prod_main], a_decisions)
        check("产物缺失时账目<100%", si_bad["cue_count_preserved_pct"] == 50.0)
        # 负例：产物挪时间轴
        prod_shift = os.path.join(tmp, "prod_shift.srt")
        with open(prod_shift, "wb") as fh:
            fh.write(b"\xef\xbb\xbf" + ("1\n00:00:01,500 --> 00:00:02,000\n甲\n\n"
                                        ).replace("\n", "\r\n").encode("utf-8"))
        si_shift = compute_structure_invariants(srt_a, [prod_shift], a_decisions)
        check("时间轴被挪时<100%", si_shift["cue_count_preserved_pct"] == 0.0)
        # 负例：换行风格被改（LF）
        prod_lf = os.path.join(tmp, "prod_lf.srt")
        with open(prod_lf, "wb") as fh:
            fh.write(b"\xef\xbb\xbf" + "1\n00:00:01,000 --> 00:00:02,000\n甲\n\n".encode("utf-8"))
        si_lf = compute_structure_invariants(srt_a, [prod_lf], a_decisions)
        check("换行风格改变被记录", si_lf["newline_bom_preserved"] is False)

    passed = sum(1 for _n, ok in results_log if ok)
    print("voiceprint_baseline 自测通过：%d/%d 项断言（mock 合成数据，"
          "不代表业务精准率）" % (passed, len(results_log)))
    return results_log


def dry_run_plan(manifest_path, args):
    """输出报告计划，不执行任何评估/写盘。"""
    if not manifest_path:
        return {"kind": "voiceprint_baseline_plan",
                "status": "awaiting_data",
                "detail": ("未提供 --manifest：G0 数据集尚未冻结，基线报告待数据，"
                           "不伪造数字。投喂流程：标注 manifest -> --build-lock "
                           "-> --decisions/--run 评估 -> --report 出报告。"),
                "plan": {"manifest": None, "lock": None,
                         "source": None, "mode": args.mode,
                         "emit_products": args.emit_products,
                         "report": args.report}}
    lock_path = args.lock or (manifest_path + ".lock.json")
    steps = [
        "validate_manifest(%s)" % os.path.basename(manifest_path),
        "verify_lock(%s)" % os.path.basename(lock_path),
        ("run_manifest 只读执行（tracemalloc 效率采集）" if args.run
         else "load_saved_results(%s)" % args.decisions),
    ]
    if args.threshold_grid:
        steps.append("threshold_grid_scan(%s)" % args.threshold_grid)
    if args.emit_products:
        steps.append("filter_srt 写临时产物 -> 结构不变量 -> 清理 %s" % _TMP_ROOT)
    if args.report:
        steps.append("write_report(%s + .sha)" % args.report)
    return {"kind": "voiceprint_baseline_plan", "status": "planned",
            "plan": {"manifest": os.path.basename(manifest_path),
                     "lock": os.path.basename(lock_path),
                     "steps": steps}}


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    ap = argparse.ArgumentParser(description="G0 声纹基线报告器（冻结+可重复）")
    ap.add_argument("--manifest", help="frozen 标注 manifest JSON")
    ap.add_argument("--lock", help="lock JSON；缺省 <manifest>.lock.json")
    source = ap.add_mutually_exclusive_group()
    source.add_argument("--run", action="store_true",
                        help="只读重跑本地筛选（out_path=None，效率采集）")
    source.add_argument("--decisions", help="已保存的 filter_srt 决策 JSON")
    ap.add_argument("--mode", choices=("recall", "precision"), default="precision")
    ap.add_argument("--threshold", type=float)
    ap.add_argument("--low", type=float)
    ap.add_argument("--threshold-grid",
                    help="阈值网格扫描 'thr:low,thr:low'（需 --decisions）")
    ap.add_argument("--emit-products", action="store_true",
                    help="产物模式：临时产物 -> 结构不变量（隐含 --run）")
    ap.add_argument("--report", help="基线报告 JSON 输出路径（同时写 <路径>.sha）")
    ap.add_argument("--build-lock", action="store_true",
                    help="由 manifest 生成冻结 lock 并写 <manifest>.lock.json")
    ap.add_argument("--dry-run", action="store_true", help="只输出报告计划")
    ap.add_argument("--self-test", action="store_true",
                    help="合成数据自测（零真实音频/零网络）")
    args = ap.parse_args(argv)

    if args.self_test:
        run_self_test()
        return 0
    if args.dry_run:
        print(json.dumps(dry_run_plan(args.manifest, args), ensure_ascii=False,
                         indent=2))
        return 0
    if args.build_lock:
        if not args.manifest:
            ap.error("--build-lock 需要 --manifest")
        try:
            lock = build_lock(args.manifest)
            lock_path = args.lock or (args.manifest + ".lock.json")
            with open(lock_path, "w", encoding="utf-8") as fh:
                fh.write(canonical_json(lock) + "\n")
            print("lock 已冻结：%s（%d 片）" % (lock_path, len(lock["items"])))
            return 0
        except (OSError, ValueError) as exc:
            print("冻结失败：%s" % exc, file=sys.stderr)
            return 2

    if not args.manifest:
        print(json.dumps({"kind": "voiceprint_baseline_report",
                          "status": "awaiting_data",
                          "detail": "未提供 --manifest：G0 数据集尚未冻结，"
                                    "报告待数据，不伪造数字。"},
                         ensure_ascii=False))
        return 2
    if args.emit_products and not args.run:
        ap.error("--emit-products 隐含 --run（结构不变量必须重跑产物）")
    if args.emit_products and args.threshold_grid:
        ap.error("--threshold-grid 与 --emit-products 不同时使用")
    grid = parse_grid(args.threshold_grid) if args.threshold_grid else None
    if grid and not args.decisions:
        ap.error("--threshold-grid 需要 --decisions（网格扫描不重提特征）")
    try:
        with open(args.manifest, encoding="utf-8") as fh:
            manifest = FE.validate_manifest(json.load(fh))
        lock_path = args.lock or (args.manifest + ".lock.json")
        ok, problems = verify_lock(args.manifest, lock_path)
        if not ok:
            print(json.dumps({"kind": "voiceprint_baseline_report",
                              "status": "lock_mismatch",
                              "problems": problems}, ensure_ascii=False,
                             indent=2))
            return 1

        structure = None
        results = None
        threshold_source = None
        if args.run:
            results = FE.run_manifest(manifest, args.mode, args.threshold,
                                      args.low)
            if args.emit_products:
                structure = _emit_products_invariants(
                    manifest, args.mode, args.threshold, args.low)
        else:
            results = FE.load_saved_results(args.decisions)
        report = build_report(args.manifest, manifest, results, args.mode,
                              structure=structure, grid=grid,
                              threshold=args.threshold, low=args.low,
                              threshold_source=threshold_source)
        if args.report:
            sha_path = write_report(report, args.report)
            print("基线报告已写出：%s（sha256=%s）" % (args.report,
                                                    report["report_sha256"]))
            print("哈希自证文件：%s" % sha_path)
        else:
            print(canonical_json({k: v for k, v in report.items()
                                  if k != "report_sha256"}))
            print("report_sha256: %s" % report["report_sha256"])
        return 0
    except (OSError, ValueError, SV.VoiceprintError) as exc:
        print("基线报告失败：%s" % exc, file=sys.stderr)
        return 2


def _emit_products_invariants(manifest, mode, threshold, low):
    """产物模式：filter_srt 真写临时产物 -> 结构不变量 -> 用完即删。"""
    os.makedirs(_TMP_ROOT, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="vp_baseline_", dir=_TMP_ROOT)
    per_item = []
    try:
        for item in manifest["items"]:
            out_path = os.path.join(tmp, "%s.srt" % item["id"])
            templates = [SV.load_template(name) for name in item["templates"]]
            kw = {"threshold": SV.DEFAULT_THRESHOLD if threshold is None else threshold,
                  "low": SV.DEFAULT_LOW if low is None else low}
            res = SV.filter_srt(item["media"], item["srt"], templates,
                                out_path=out_path, report=False, mode=mode,
                                min_keep_ratio=0, **kw)
            products = [res["out"]] if res.get("out") else []
            if res.get("review_path"):
                products.append(res["review_path"])
            si = compute_structure_invariants(item["srt"], products,
                                              res["decisions"])
            si["item_id"] = item["id"]
            per_item.append(si)
        overall = None
        if per_item:
            overall = {
                "cue_count_preserved_pct": min(
                    x["cue_count_preserved_pct"] or 0.0 for x in per_item),
                "timeline_unchanged_pct": min(
                    x["timeline_unchanged_pct"] or 0.0 for x in per_item),
                "newline_bom_preserved": all(x["newline_bom_preserved"]
                                             for x in per_item),
                "index_renumbered": all(x["index_renumbered"] for x in per_item),
            }
        return {"per_item": per_item, "overall": overall}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
