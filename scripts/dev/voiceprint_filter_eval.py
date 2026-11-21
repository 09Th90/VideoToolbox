#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# @version 3.1.5
"""真实标注集上的声纹筛选评估（不改媒体、模板或原 SRT）。

Manifest（version=1）：
{
  "version": 1,
  "items": [{
    "id": "video-001",
    "media": "D:/media/a.mp4",
    "srt": "D:/media/a.srt",
    "language": "ja",
    "templates": ["主播A"],
    "cues": [
      {"num": 1, "label": "target"},
      {"num": 2, "label": "non_target"},
      {"num": 3, "label": "overlap"},
      {"num": 4, "label": "unknown"}
    ]
  }]
}

cue 可另带非负 `duration_ms`，或成对的毫秒 `start/end` 作为人工时间标签；
未提供时使用决策明细中的原 SRT 时长。item/cue 均可带 language，cue 优先。

用法：
  # 直接跑现有本地模型；out_path=None，不写筛选 SRT / 报告 / 备份
  tools/python/python.exe scripts/dev/voiceprint_filter_eval.py \
      --manifest labeled.json --run --mode precision --output eval.json

  # 评估已保存的 filter_srt 结果；单条结果、结果 list 或 {"results": [...]} 均可
  tools/python/python.exe scripts/dev/voiceprint_filter_eval.py \
      --manifest labeled.json --decisions decisions.json

  # 只用合成数据验证 Schema 和指标，不产生也不代表业务准确率
  tools/python/python.exe scripts/dev/voiceprint_filter_eval.py --self-test

指标口径：
  * 主指标只用 target / non_target；overlap / unknown 单列，不混入分母。
  * precision = target keep / 全部 keep；recall = target keep / 全部 target。
    因此 target review 会降低自动保留 recall，但不计入硬误删 false_drop。
  * false_keep = non_target keep；false_drop = target drop；review_rate 为存疑占比。
  * output 是按模式折算正式 SRT 的指标：recall 模式把 review 当保留，precision
    模式把 review 当未进入正式成品。cue 与 duration（秒）两种口径同时输出。
"""
import argparse
import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)
os.environ.setdefault("VT_NO_PIPELINE", "1")
os.environ.setdefault("VT_NO_SYNC", "1")
os.environ.setdefault("VT_NO_VP_SYNC", "1")

import features.voiceprint.speaker_voiceprint as SV  # noqa: E402

LABELS = {"target", "non_target", "overlap", "unknown"}
STATES = {"keep", "drop", "review"}


def _err(message):
    raise ValueError(message)


def validate_manifest(obj):
    """校验并返回 manifest；失败时给出可定位的字段错误。"""
    if not isinstance(obj, dict) or obj.get("version") != 1:
        _err("manifest 必须是对象且 version=1")
    items = obj.get("items")
    if not isinstance(items, list) or not items:
        _err("manifest.items 必须是非空数组")
    seen_ids = set()
    for ii, item in enumerate(items):
        where = "items[%d]" % ii
        if not isinstance(item, dict):
            _err(where + " 必须是对象")
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id.strip():
            _err(where + ".id 必须是非空字符串")
        if item_id in seen_ids:
            _err("重复 item id：" + item_id)
        seen_ids.add(item_id)
        for key in ("media", "srt"):
            if not isinstance(item.get(key), str) or not item[key].strip():
                _err("%s.%s 必须是路径字符串" % (where, key))
        templates = item.get("templates")
        if (not isinstance(templates, list) or not templates
                or any(not isinstance(x, str) or not x.strip() for x in templates)):
            _err(where + ".templates 必须是非空模板名数组")
        cues = item.get("cues")
        if not isinstance(cues, list) or not cues:
            _err(where + ".cues 必须是非空数组")
        nums = set()
        for ci, cue in enumerate(cues):
            cw = "%s.cues[%d]" % (where, ci)
            if not isinstance(cue, dict):
                _err(cw + " 必须是对象")
            num = cue.get("num")
            if not isinstance(num, int) or isinstance(num, bool) or num <= 0:
                _err(cw + ".num 必须是正整数")
            if num in nums:
                _err("%s 重复 cue num=%d" % (where, num))
            nums.add(num)
            if cue.get("label") not in LABELS:
                _err(cw + ".label 必须为 target/non_target/overlap/unknown")
            if "duration_ms" in cue:
                value = cue["duration_ms"]
                if (not isinstance(value, (int, float)) or isinstance(value, bool)
                        or value < 0):
                    _err(cw + ".duration_ms 必须是非负数字")
            has_start, has_end = "start" in cue, "end" in cue
            if has_start or has_end:
                start, end = cue.get("start"), cue.get("end")
                if (not has_start or not has_end
                        or not isinstance(start, (int, float)) or isinstance(start, bool)
                        or not isinstance(end, (int, float)) or isinstance(end, bool)
                        or start < 0 or end < start):
                    _err(cw + " 的可选 start/end 必须成对出现且满足 0<=start<=end")
    return obj


def _result_decisions(result):
    if isinstance(result, dict) and isinstance(result.get("decisions"), list):
        return result["decisions"]
    if isinstance(result, list) and all(isinstance(x, dict) for x in result):
        return result
    _err("每个结果必须是 filter_srt 结果（含 decisions）或 decision 数组")


def load_saved_results(path):
    with open(path, encoding="utf-8") as fh:
        obj = json.load(fh)
    if isinstance(obj, dict) and isinstance(obj.get("results"), list):
        return obj["results"]
    if isinstance(obj, dict) and "decisions" in obj:
        return [obj]
    if isinstance(obj, list):
        if obj and all(isinstance(x, dict) and "state" in x for x in obj):
            return [{"decisions": obj}]
        return obj
    _err("decisions JSON 应为单条结果、结果数组或 {\"results\": [...]}")


def run_manifest(manifest, mode, threshold=None, low=None):
    """只读执行：filter_srt 的 out_path=None，因此不产生任何字幕产物。"""
    results = []
    for item in manifest["items"]:
        for key in ("media", "srt"):
            if not os.path.isfile(item[key]):
                _err("%s：%s 不存在：%s" % (item["id"], key, item[key]))
        templates = [SV.load_template(name) for name in item["templates"]]
        kw = {"threshold": SV.DEFAULT_THRESHOLD if threshold is None else threshold,
              "low": SV.DEFAULT_LOW if low is None else low}
        result = SV.filter_srt(item["media"], item["srt"], templates,
                               out_path=None, report=False, mode=mode,
                               min_keep_ratio=0, **kw)
        result["id"] = item["id"]
        results.append(result)
    return results


def _align_results(manifest, results):
    if not isinstance(results, list) or len(results) != len(manifest["items"]):
        _err("结果数量必须与 manifest.items 一致")
    by_id = {r.get("id"): r for r in results
             if isinstance(r, dict) and isinstance(r.get("id"), str)}
    aligned = []
    for item, fallback in zip(manifest["items"], results):
        result = by_id.get(item["id"], fallback)
        decisions = _result_decisions(result)
        by_num = {}
        for di, d in enumerate(decisions):
            where = "%s.decisions[%d]" % (item["id"], di)
            if not isinstance(d, dict):
                _err(where + " 必须是对象")
            num = d.get("num")
            if not isinstance(num, int) or isinstance(num, bool) or num <= 0:
                _err(where + ".num 必须是正整数")
            if num in by_num:
                _err("%s 重复 decision num=%d" % (item["id"], num))
            if d.get("state") not in STATES:
                _err(where + ".state 必须为 keep/drop/review")
            by_num[num] = d
        expected = {c["num"] for c in item["cues"]}
        if set(by_num) != expected:
            _err("%s：decision num 集合与 manifest.cues 不一致" % item["id"])
        aligned.append((item, by_num))
    return aligned


def _duration_ms(decision, cue=None):
    # 可选人工时间标签优先；缺省使用决策器从原 SRT 保留下来的时间轴。
    cue = cue or {}
    if "duration_ms" in cue:
        return float(cue["duration_ms"])
    if "start" in cue and "end" in cue:
        return float(cue["end"] - cue["start"])
    value = decision.get("duration_ms")
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
        return float(value)
    start, end = decision.get("start"), decision.get("end")
    if (isinstance(start, (int, float)) and isinstance(end, (int, float))
            and end >= start):
        return float(end - start)
    _err("decision num=%s 缺少有效 duration_ms 或 start/end" % decision.get("num"))


def _div(a, b):
    return (a / b) if b else None


def _metrics(rows, mode, duration=False):
    def weight(row):
        return row["duration_ms"] / 1000.0 if duration else 1

    labelled = [r for r in rows if r["label"] in ("target", "non_target")]
    target = [r for r in labelled if r["label"] == "target"]
    non_target = [r for r in labelled if r["label"] == "non_target"]
    tp = sum(weight(r) for r in target if r["state"] == "keep")
    fp = sum(weight(r) for r in non_target if r["state"] == "keep")
    fn = sum(weight(r) for r in target if r["state"] == "drop")
    target_review = sum(weight(r) for r in target if r["state"] == "review")
    other_review = sum(weight(r) for r in non_target if r["state"] == "review")
    total = sum(weight(r) for r in labelled)
    target_total = sum(weight(r) for r in target)
    non_target_total = sum(weight(r) for r in non_target)
    review_total = target_review + other_review

    # 折算正式 SRT：recall 的 review 进成品，precision 的 review 进待复核。
    out_tp = tp + (target_review if mode == "recall" else 0)
    out_fp = fp + (other_review if mode == "recall" else 0)
    out_fn = target_total - out_tp
    label_summary = {}
    for label in sorted(LABELS):
        selected = [r for r in rows if r["label"] == label]
        label_summary[label] = {
            "total": sum(weight(r) for r in selected),
            "keep": sum(weight(r) for r in selected if r["state"] == "keep"),
            "drop": sum(weight(r) for r in selected if r["state"] == "drop"),
            "review": sum(weight(r) for r in selected if r["state"] == "review"),
        }
    return {
        "precision": _div(tp, tp + fp),
        "recall": _div(tp, target_total),
        "false_keep": fp,
        "false_drop": fn,
        "target_review": target_review,
        "review_rate": _div(review_total, total),
        "output": {
            "precision": _div(out_tp, out_tp + out_fp),
            "recall": _div(out_tp, target_total),
            "false_keep": out_fp,
            "false_drop": out_fn,
        },
        "support": {
            "total": total, "target": target_total, "non_target": non_target_total,
            "keep": sum(weight(r) for r in labelled if r["state"] == "keep"),
            "drop": sum(weight(r) for r in labelled if r["state"] == "drop"),
            "review": review_total,
        },
        "labels": label_summary,
    }


def _metric_bundle(rows, mode):
    return {"cue": _metrics(rows, mode, duration=False),
            "duration": _metrics(rows, mode, duration=True)}


def evaluate(manifest, results, mode="precision"):
    """对齐 manifest 与 decisions，输出整体、单片和三类分组指标。"""
    validate_manifest(manifest)
    if mode not in ("recall", "precision"):
        _err("mode 必须为 recall / precision")
    aligned = _align_results(manifest, results)
    rows = []
    item_reports = []
    for item, by_num in aligned:
        item_rows = []
        for cue in item["cues"]:
            d = by_num[cue["num"]]
            row = {
                "item_id": item["id"], "num": cue["num"], "label": cue["label"],
                "language": cue.get("language") or item.get("language") or "unknown",
                "asr_label": str(d.get("speaker") or "(unlabeled)"),
                "asr_presence": "labeled" if d.get("speaker") else "unlabeled",
                "reason": str(d.get("reason") or "(none)"),
                "source": str(d.get("source") or "unknown"),
                "state": d["state"], "score": d.get("score"),
                "duration_ms": _duration_ms(d, cue),
            }
            item_rows.append(row)
        rows.extend(item_rows)
        item_reports.append({"id": item["id"], **_metric_bundle(item_rows, mode)})

    groups = {}
    for field in ("reason", "language", "asr_presence", "asr_label"):
        groups[field] = {}
        for value in sorted({str(r[field]) for r in rows}):
            selected = [r for r in rows if str(r[field]) == value]
            groups[field][value] = _metric_bundle(selected, mode)
    return {
        "schema_version": 1,
        "mode": mode,
        "metric_scope": "target/non_target 主指标；overlap/unknown 仅在 labels 中单列",
        "items": item_reports,
        "overall": _metric_bundle(rows, mode),
        "groups": groups,
    }


def _synthetic_case():
    manifest = {
        "version": 1,
        "items": [
            {"id": "a", "media": "C:/synthetic/a.mp4", "srt": "C:/synthetic/a.srt",
             "language": "zh", "templates": ["合成主播"],
             "cues": [
                 {"num": 1, "label": "target"},
                 {"num": 2, "label": "non_target"},
                 {"num": 3, "label": "target"},
                 {"num": 4, "label": "non_target"},
                 {"num": 5, "label": "overlap"},
                 {"num": 6, "label": "unknown"}]},
            {"id": "b", "media": "C:/synthetic/b.mp4", "srt": "C:/synthetic/b.srt",
             "language": "ja", "templates": ["合成主播"],
             "cues": [{"num": 1, "label": "target"},
                      {"num": 2, "label": "non_target"}]},
        ],
    }

    def d(num, state, duration, reason="", speaker=""):
        return {"num": num, "state": state, "duration_ms": duration,
                "score": None, "reason": reason, "source": "synthetic",
                "speaker": speaker, "cluster": -1}

    results = [
        {"id": "a", "decisions": [
            d(1, "keep", 1000, speaker="说话人1"),
            d(2, "keep", 2000, speaker="说话人2"),
            d(3, "drop", 3000, speaker="说话人1"),
            d(4, "review", 4000, "borderline", "说话人2"),
            d(5, "keep", 5000),
            d(6, "drop", 6000)]},
        {"id": "b", "decisions": [
            d(1, "review", 1000, "too_short"),
            d(2, "drop", 1000)]},
    ]
    return manifest, results


def run_self_test():
    manifest, results = _synthetic_case()
    report = evaluate(manifest, results, mode="precision")
    cue = report["overall"]["cue"]
    duration = report["overall"]["duration"]
    assert abs(cue["precision"] - 0.5) < 1e-9
    assert abs(cue["recall"] - 1.0 / 3.0) < 1e-9
    assert cue["false_keep"] == 1 and cue["false_drop"] == 1
    assert cue["target_review"] == 1
    assert abs(cue["review_rate"] - 2.0 / 6.0) < 1e-9
    assert abs(duration["precision"] - 1.0 / 3.0) < 1e-9
    assert abs(duration["recall"] - 0.2) < 1e-9
    assert duration["false_keep"] == 2.0 and duration["false_drop"] == 3.0
    assert abs(duration["review_rate"] - 5.0 / 12.0) < 1e-9
    # overlap/unknown 的 11 秒不得混入主指标；只能在 labels 中看见。
    assert cue["support"]["total"] == 6
    assert cue["labels"]["overlap"]["total"] == 1
    assert cue["labels"]["unknown"]["total"] == 1
    assert "borderline" in report["groups"]["reason"]
    assert "ja" in report["groups"]["language"]
    assert "说话人2" in report["groups"]["asr_label"]
    assert "labeled" in report["groups"]["asr_presence"]
    assert "unlabeled" in report["groups"]["asr_presence"]

    timed = copy.deepcopy(manifest)
    timed["items"][1]["cues"][0]["start"] = 0
    timed["items"][1]["cues"][0]["end"] = 2500
    timed_duration = evaluate(timed, results)["overall"]["duration"]
    assert timed_duration["support"]["target"] == 6.5  # 人工时间标签覆盖该 cue 的 1 秒

    recall = evaluate(manifest, results, mode="recall")["overall"]["cue"]
    assert abs(recall["output"]["precision"] - 0.5) < 1e-9
    assert abs(recall["output"]["recall"] - 2.0 / 3.0) < 1e-9
    assert recall["output"]["false_drop"] == 1  # 明确的 target drop 仍是硬误删

    bad = copy.deepcopy(manifest)
    bad["items"][0]["cues"][0]["label"] = "invented"
    try:
        evaluate(bad, results)
    except ValueError:
        pass
    else:
        raise AssertionError("非法 label 未被 Schema 拒绝")
    bad_time = copy.deepcopy(manifest)
    bad_time["items"][0]["cues"][0]["start"] = 100  # 缺少 end
    try:
        evaluate(bad_time, results)
    except ValueError:
        pass
    else:
        raise AssertionError("不成对的人工时间标签未被 Schema 拒绝")
    mismatch = copy.deepcopy(results)
    mismatch[0]["decisions"] = mismatch[0]["decisions"][:-1]
    try:
        evaluate(manifest, mismatch)
    except ValueError:
        pass
    else:
        raise AssertionError("decision 数量不一致未被拒绝")
    return report


def _write_or_print(report, output):
    text = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False)
    if output:
        parent = os.path.dirname(os.path.abspath(output))
        os.makedirs(parent, exist_ok=True)
        with open(output, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print("评估报告已写出：%s" % output)
    else:
        print(text)


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    ap = argparse.ArgumentParser(description="真实标注集上的声纹筛选评估")
    ap.add_argument("--manifest", help="真实标注 manifest JSON")
    source = ap.add_mutually_exclusive_group()
    source.add_argument("--run", action="store_true",
                        help="只读执行本地筛选；不写 SRT/报告/备份")
    source.add_argument("--decisions", help="已保存的 filter_srt 决策 JSON")
    ap.add_argument("--mode", choices=("recall", "precision"), default="precision")
    ap.add_argument("--threshold", type=float)
    ap.add_argument("--low", type=float)
    ap.add_argument("--output", help="评估 JSON 输出路径；缺省打印到 stdout")
    ap.add_argument("--self-test", action="store_true",
                    help="合成数据 Schema/指标自测，不代表业务准确率")
    args = ap.parse_args(argv)
    if args.self_test:
        report = run_self_test()
        print("合成数据 Schema/指标自测通过；不代表业务精准率。")
        _write_or_print(report, args.output)
        return 0
    if not args.manifest:
        ap.error("除 --self-test 外必须提供 --manifest")
    if not args.run and not args.decisions:
        ap.error("必须选择 --run 或 --decisions")
    try:
        with open(args.manifest, encoding="utf-8") as fh:
            manifest = validate_manifest(json.load(fh))
        results = (run_manifest(manifest, args.mode, args.threshold, args.low)
                   if args.run else load_saved_results(args.decisions))
        report = evaluate(manifest, results, args.mode)
        _write_or_print(report, args.output)
        return 0
    except (OSError, ValueError, SV.VoiceprintError) as exc:
        print("评估失败：%s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
