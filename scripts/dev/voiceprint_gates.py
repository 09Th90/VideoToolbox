#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# @version 3.2.5
"""G0/G1 门禁判定：数据可用性 + 冻结 + 可重复 + 回归 + 结构不变量。

定位：eval 设计落地序 step3 之二。WP1 `voiceprint_filter_eval.py`（指标口径
与 --self-test）、本目录 `voiceprint_baseline.py`（基线报告 + lock 冻结 +
报告哈希）是它的上游——本脚本只做判定，消费上述产出，不重复实现。

G0（数据可用，全过才 PASS）：
  * G0-1 标签口径：labeling_guide_version 已登记；test split 四类标签
    （target/non_target/overlap/unknown）非零；test 集困难样本（带
    hard_flags 或 overlap 标签）≥ 200；语言 zh/en/ja/ko 各 ≥1 片；
    视频 5~8；总 cue ≥ 600。
  * G0-2 测试集冻结：重算 manifest 全文与每片 media/srt 的 sha256 与 lock
    相等（复用 voiceprint_baseline.verify_lock）；无视频跨 split；
    同说话人不跨 split（item.speakers 登记后校验，未登记判 FAIL 提示补登）。
  * G0-3 报告可重复：重算 canonical 哈希 == report_sha256（并读
    <report>.sha 交叉比对）；config_snapshot 显式；reproducibility 完整。

G1（全过才 PASS）：
  * G1-1 完整自检：subprocess 跑 voiceprint_filter_eval.py --self-test，
    exit 0 才过。
  * G1-2 聚类回归：sv_ref（C:\\bld\\sv_ref\\wavs）不存在时 SKIP 显式标注、
    不算 FAIL；存在时跑 voiceprint_accuracy.py，C 纯度 ≥ 记录-0.02、
    A 最小边际 ≥ 记录-0.02。基线数字首次运行用 --g1-record 写
    data/eval/voiceprint_baseline_meta.json 锁定；check 模式下记录缺失
    标 no_baseline（提示先 record，按未过计）。
  * G1-3 结构不变量：基线报告 structure_invariants 的
    cue_count_preserved_pct == 100 且 timeline_unchanged_pct == 100 且
    newline_bom_preserved（index_renumbered 仅记录，不判）。

无真实数据集时 G0 输出「待数据」overall=False 不放行（不伪造基线数字）。

用法：
  tools/python/python.exe scripts/dev/voiceprint_gates.py \
      --manifest labeled.json --report baseline.json [--g1-record]

  tools/python/python.exe scripts/dev/voiceprint_gates.py --dry-run
  tools/python/python.exe scripts/dev/voiceprint_gates.py --self-test

输出 JSON：{g0:{G0-1:{pass,detail}...}, g1:{...}, overall, verdict}。
exit code：0=放行（overall=True）；1=不放行（含「待数据」）；2=执行错误。
"""
import argparse
import copy
import json
import os
import re
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

import voiceprint_filter_eval as FE  # noqa: E402
import voiceprint_baseline as VB  # noqa: E402

#: G0-1 数据量门槛（G0 理论设计冻结值）
MIN_VIDEOS, MAX_VIDEOS = 5, 8
MIN_CUES = 600
MIN_HARD_OR_OVERLAP_TEST = 200
REQUIRED_LANGS = ("zh", "en", "ja", "ko")
REQUIRED_LABELS = ("target", "non_target", "overlap", "unknown")
#: G1-2 回归容差：聚类纯度 / A 最小边际允许的最大回退
EPS_PURITY = 0.02
EPS_MARGIN = 0.02
SV_REF_DIR = r"C:\bld\sv_ref\wavs"
FILTER_EVAL_PATH = os.path.join(HERE, "voiceprint_filter_eval.py")
ACCURACY_PATH = os.path.join(HERE, "voiceprint_accuracy.py")
BASELINE_META_PATH = os.path.join(ROOT, "data", "eval",
                                  "voiceprint_baseline_meta.json")

_VERDICT_AWAIT = "待数据：G0 数据集未冻结，不放行（不伪造基线数字）"


def _cell(passed, **detail):
    out = {"pass": bool(passed)}
    out.update(detail)
    return out


# ------------------------------------------------------------------ G0-1


def check_labeling(manifest):
    """标签口径六格判定；每格独立 {pass, detail}，全过才 G0-1 过。"""
    cells = {}
    guide = manifest.get("labeling_guide_version")
    cells["labeling_guide_version"] = _cell(
        isinstance(guide, str) and bool(guide.strip()),
        value=guide if isinstance(guide, str) else None)

    items = manifest.get("items") or []
    test_cues = [c for it in items if it.get("split") == "test"
                 for c in (it.get("cues") or [])]
    counts = {label: sum(1 for c in test_cues if c.get("label") == label)
              for label in REQUIRED_LABELS}
    cells["test_label_coverage"] = _cell(
        bool(test_cues) and all(counts[l] > 0 for l in REQUIRED_LABELS),
        counts=counts,
        missing=[l for l in REQUIRED_LABELS if counts[l] == 0])

    hard = sum(1 for c in test_cues
               if c.get("hard_flags") or c.get("label") == "overlap")
    cells["hard_or_overlap_test"] = _cell(
        hard >= MIN_HARD_OR_OVERLAP_TEST, count=hard,
        required=MIN_HARD_OR_OVERLAP_TEST)

    langs = {str(it.get("language") or "") for it in items}
    missing = [l for l in REQUIRED_LANGS if l not in langs]
    cells["language_coverage"] = _cell(not missing,
                                       present=sorted(l for l in langs if l),
                                       missing=missing)

    n_items = len(items)
    cells["video_count"] = _cell(MIN_VIDEOS <= n_items <= MAX_VIDEOS,
                                 count=n_items,
                                 range_=[MIN_VIDEOS, MAX_VIDEOS])

    total_cues = sum(len(it.get("cues") or []) for it in items)
    cells["cue_total"] = _cell(total_cues >= MIN_CUES, count=total_cues,
                               required=MIN_CUES)

    passed = all(c["pass"] for c in cells.values())
    return {"pass": passed, "cells": cells}


# ------------------------------------------------------------------ G0-2


def check_frozen(manifest, manifest_path, lock_path):
    """测试集冻结：lock 逐项哈希 + 无视频跨集 + 同说话人不跨 split。"""
    cells = {}
    ok, problems = VB.verify_lock(manifest_path, lock_path)
    cells["lock_hashes"] = _cell(ok, problems=problems[:10])

    # 无视频跨集：同一 media 不得分属不同 split（同 split 重复引用也登记）。
    by_media = {}
    for it in manifest.get("items") or []:
        key = os.path.normcase(os.path.normpath(it.get("media") or ""))
        by_media.setdefault(key, set()).add(str(it.get("split") or "(unspecified)"))
    crossed = {m: sorted(s) for m, s in by_media.items() if len(s) > 1}
    cells["no_video_across_splits"] = _cell(not crossed, crossed=crossed)

    # 同说话人不跨 split：依赖 item.speakers 登记；未登记判 FAIL（提示补登）。
    by_speaker = {}
    missing = []
    for it in manifest.get("items") or []:
        speakers = it.get("speakers")
        if not isinstance(speakers, list) or not speakers:
            missing.append(it.get("id"))
            continue
        split = str(it.get("split") or "(unspecified)")
        for spk in speakers:
            by_speaker.setdefault(str(spk), set()).add(split)
    crossed_speakers = {s: sorted(v) for s, v in by_speaker.items()
                        if len(v) > 1}
    cells["speaker_not_across_splits"] = _cell(
        not missing and not crossed_speakers,
        missing_speakers=missing, crossed=crossed_speakers,
        detail=None if not missing else
        "items 未登记 speakers 字段，无法校验同说话人不跨 split（投喂时补登）")

    passed = all(c["pass"] for c in cells.values())
    return {"pass": passed, "cells": cells}


# ------------------------------------------------------------------ G0-3


def check_reproducible(report_path, report):
    """报告可重复：canonical 哈希交叉验证 + config_snapshot + 快照完整。"""
    cells = {}
    if not isinstance(report, dict) or report.get("kind") != \
            "voiceprint_baseline_report":
        return {"pass": False,
                "cells": {"report_readable": _cell(
                    False, detail="不是 voiceprint_baseline_report（kind 不符）")}}
    claimed = report.get("report_sha256")
    recomputed = VB.report_sha256(report)
    sha_ok = bool(claimed) and claimed == recomputed
    sha_file = report_path + ".sha" if report_path else None
    sha_file_note = None
    if sha_ok and sha_file and os.path.isfile(sha_file):
        with open(sha_file, encoding="utf-8") as fh:
            sha_file_note = fh.read().split()[0] == claimed
    cells["report_sha256"] = _cell(sha_ok, claimed=claimed,
                                   recomputed=recomputed,
                                   sha_file_match=sha_file_note)

    rep = report.get("reproducibility") or {}
    versions = rep.get("versions") or {}
    snap = versions.get("config_snapshot") or {}
    snap_keys = ("threshold", "low", "cluster_threshold",
                 "cluster_min_seconds", "mode", "min_keep_ratio")
    cells["config_snapshot_explicit"] = _cell(
        all(snap.get(k) is not None for k in snap_keys), snapshot=snap)

    inputs = rep.get("inputs")
    expected_inputs = len((report.get("metrics") or {}).get("items") or [])
    complete = (isinstance(rep.get("seed"), int)
                and bool(rep.get("manifest_sha256"))
                and isinstance(inputs, list) and bool(inputs)
                and all(isinstance(x, dict) and x.get("item_id")
                        and x.get("media_sha256") and x.get("srt_sha256")
                        for x in inputs)
                and bool(versions.get("toolbox_git_describe"))
                and bool(versions.get("evaluator_version"))
                and isinstance(versions.get("model"), dict))
    cells["reproducibility_complete"] = _cell(
        complete, inputs_count=(len(inputs) if isinstance(inputs, list) else None),
        expected_inputs=expected_inputs,
        detail=None if complete else "seed/manifest_sha256/inputs/versions 存在缺口")

    passed = all(c["pass"] for c in cells.values())
    return {"pass": passed, "cells": cells}


# ------------------------------------------------------------------ G1-1


def run_filter_eval_selftest(timeout=180):
    """subprocess 跑 voiceprint_filter_eval.py --self-test；exit 0 才过。"""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        proc = subprocess.run(
            [sys.executable, FILTER_EVAL_PATH, "--self-test"],
            cwd=ROOT, capture_output=True, text=True, timeout=timeout, env=env)
        ok = proc.returncode == 0
        tail = (proc.stdout or "").strip().splitlines()
        return _cell(ok, exit_code=proc.returncode,
                     last_line=tail[-1] if tail else None,
                     stderr=(proc.stderr or "").strip()[-300:] or None)
    except subprocess.TimeoutExpired:
        return _cell(False, detail="self-test 超时（%ds）" % timeout)
    except OSError as exc:
        return _cell(False, detail="无法启动子进程：%s" % exc)


# ------------------------------------------------------------------ G1-2


_PURITY_RE = re.compile(r"pairwise purity = ([0-9.]+)（(\d+) 对）")
_NUM_RE = re.compile(r"\d+\.\d+")


def parse_accuracy_output(text):
    """解析 voiceprint_accuracy.py 输出：C 纯度 + A 段最小边际。"""
    purity = pairs = None
    m = _PURITY_RE.search(text or "")
    if m:
        purity, pairs = float(m.group(1)), int(m.group(2))
    margins, in_a = [], False
    for line in (text or "").splitlines():
        if line.startswith("== A."):
            in_a = True
            continue
        if in_a:
            if line.startswith("=="):
                break
            nums = _NUM_RE.findall(line)
            if len(nums) == 3:            # 同人min / 异人max / 边际
                margins.append(float(nums[-1]))
    return {"purity": purity, "pairs": pairs,
            "min_margin_a": min(margins) if margins else None}


def _run_accuracy(timeout=900):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run([sys.executable, ACCURACY_PATH], cwd=ROOT,
                          capture_output=True, text=True, timeout=timeout,
                          env=env)
    return proc.returncode, proc.stdout or "", (proc.stderr or "").strip()


def check_cluster_regression(record=False, meta_path=None, runner=None):
    """聚类回归：基线数字锁定（record）或比对（check）。

    runner None 时 subprocess 真跑；self-test 注入假 runner 零耗时验证比对
    逻辑。sv_ref 不存在 -> SKIP 显式标注，不算 FAIL。
    """
    meta_path = meta_path or BASELINE_META_PATH
    if not os.path.isdir(SV_REF_DIR):
        return {"pass": True, "status": "skipped",
                "detail": "sv_ref 语料不存在（%s）——SKIP 显式标注，不算 FAIL"
                          % SV_REF_DIR}
    meta = None
    if os.path.isfile(meta_path):
        try:
            with open(meta_path, encoding="utf-8") as fh:
                meta = json.load(fh)
        except (OSError, ValueError):
            meta = None
    if record:
        runner = runner or _run_accuracy
        code, out, err = runner()
        parsed = parse_accuracy_output(out)
        ok = (code == 0 and parsed["purity"] is not None
              and parsed["min_margin_a"] is not None)
        if not ok:
            return {"pass": False, "status": "error", "exit_code": code,
                    "parsed": parsed, "stderr": (err or "")[-300:],
                    "detail": "accuracy 运行/解析失败，拒绝锁定基线"}
        os.makedirs(os.path.dirname(meta_path), exist_ok=True)
        locked = {"version": 1, "purity": parsed["purity"],
                  "pairs": parsed["pairs"], "min_margin_a": parsed["min_margin_a"],
                  "eps_purity": EPS_PURITY, "eps_margin": EPS_MARGIN}
        with open(meta_path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(locked, ensure_ascii=False, indent=2) + "\n")
        return {"pass": True, "status": "locked", "locked": locked,
                "detail": "基线数字已锁定：%s" % meta_path}
    if meta is None or not isinstance(meta.get("purity"), (int, float)) \
            or not isinstance(meta.get("min_margin_a"), (int, float)):
        return {"pass": False, "status": "no_baseline",
                "detail": ("基线数字未锁定（%s 缺失/损坏）：先 --g1-record 首跑锁定，"
                           "再走门禁比对" % meta_path)}
    runner = runner or _run_accuracy
    code, out, err = runner()
    parsed = parse_accuracy_output(out)
    if code != 0 or parsed["purity"] is None or parsed["min_margin_a"] is None:
        return {"pass": False, "status": "error", "exit_code": code,
                "parsed": parsed, "stderr": (err or "")[-300:],
                "detail": "accuracy 运行/解析失败"}
    purity_ok = parsed["purity"] >= meta["purity"] - EPS_PURITY
    margin_ok = parsed["min_margin_a"] >= meta["min_margin_a"] - EPS_MARGIN
    return {"pass": bool(purity_ok and margin_ok), "status": "checked",
            "recorded": {"purity": meta["purity"],
                         "min_margin_a": meta["min_margin_a"]},
            "current": parsed,
            "eps": {"purity": EPS_PURITY, "margin": EPS_MARGIN},
            "purity_ok": purity_ok, "margin_ok": margin_ok}


# ------------------------------------------------------------------ G1-3


def check_structure_invariants(report):
    """G1-3：结构不变量 100% + BOM/换行保留（无产物模式数据时判 FAIL）。"""
    if not isinstance(report, dict):
        return _cell(False, detail="无基线报告：G1-3 待数据（需 --report）")
    si = report.get("structure_invariants")
    if not isinstance(si, dict):
        return _cell(False,
                     detail="报告为只读模式（structure_invariants=null）："
                            "需以 --run --emit-products 重出报告")
    overall = si.get("overall") or si
    cc = overall.get("cue_count_preserved_pct")
    tl = overall.get("timeline_unchanged_pct")
    nb = overall.get("newline_bom_preserved")
    passed = (cc == 100.0 and tl == 100.0 and nb is True)
    return _cell(passed, cue_count_preserved_pct=cc, timeline_unchanged_pct=tl,
                 newline_bom_preserved=nb, index_renumbered=overall.get("index_renumbered"),
                 detail=None if passed else "结构不变量未达 100%/风格被改（G1-3 拦截）")


# ------------------------------------------------------------------ 汇总


def run_gates(manifest_path=None, lock_path=None, report_path=None,
              g1_record=False, meta_path=None, runner=None,
              skip_g1_selftest=False):
    """汇总 G0/G1 判定；无 manifest 时 G0「待数据」不放行。"""
    result = {"schema_version": 1, "kind": "voiceprint_gates_result",
              "inputs": {"manifest": bool(manifest_path),
                         "lock": bool(lock_path),
                         "report": bool(report_path)}}

    if not manifest_path:
        awaiting = {"pass": False, "status": "awaiting_data",
                    "detail": "G0 数据集未冻结：提供 manifest + lock + 基线报告"
                              "后再跑门禁；不伪造基线数字"}
        result["g0"] = {"status": "awaiting_data", "overall": False,
                        "G0-1": awaiting, "G0-2": awaiting, "G0-3": awaiting}
        result["g1"] = {"status": "not_evaluated", "overall": False,
                        "detail": "G0 未过，G1 不评估（不放行优先）"}
        result["overall"] = False
        result["verdict"] = _VERDICT_AWAIT
        return result

    data_ok = True
    report = None
    manifest = None
    try:
        with open(manifest_path, encoding="utf-8") as fh:
            manifest = FE.validate_manifest(json.load(fh))
    except (OSError, ValueError) as exc:
        data_ok = False
        g01 = {"pass": False, "detail": "manifest 不可读/校验失败：%s" % exc}
        g02 = {"pass": False, "detail": "manifest 不可读，冻结校验未执行"}
        g03 = {"pass": False, "detail": "manifest 不可读"}
    if data_ok:
        lock_path = lock_path or (manifest_path + ".lock.json")
        g01 = check_labeling(manifest)
        g02 = check_frozen(manifest, manifest_path, lock_path)
        if report_path and os.path.isfile(report_path):
            try:
                with open(report_path, encoding="utf-8") as fh:
                    report = json.load(fh)
            except (OSError, ValueError) as exc:
                g03 = {"pass": False,
                       "detail": "报告不可读：%s" % exc}
            else:
                g03 = check_reproducible(report_path, report)
        else:
            g03 = {"pass": False,
                   "detail": "无基线报告（--report）：G0-3 待数据；"
                             "先用 voiceprint_baseline.py --report 出报告"}
    g0_pass = g01["pass"] and g02["pass"] and g03["pass"]
    result["g0"] = {"status": "pass" if g0_pass else "fail",
                    "overall": g0_pass,
                    "G0-1": g01, "G0-2": g02, "G0-3": g03}

    # G1：G0 未过时 G1-1 子进程可跳过（skip 参数），其余照常评估以便定位。
    if g0_pass or not skip_g1_selftest:
        g11 = run_filter_eval_selftest()
    else:
        g11 = _cell(True, skipped=True,
                    detail="G0 未过，G1-1 子进程自检跳过（--skip-g1-selftest）")
    g12 = check_cluster_regression(record=g1_record, meta_path=meta_path,
                                   runner=runner)
    g13 = check_structure_invariants(report if data_ok else None)
    g1_ok = (g11["pass"] and (g12["pass"] or g12.get("status") == "skipped")
             and g13["pass"])
    result["g1"] = {"status": "pass" if g1_ok else "fail",
                    "overall": g1_ok,
                    "G1-1": g11, "G1-2": g12, "G1-3": g13}
    result["overall"] = bool(g0_pass and g1_ok)
    result["verdict"] = ("PASS 放行" if result["overall"]
                         else "FAIL 不放行：见 g0/g1 各格 detail")
    return result


def dry_run_plan(manifest_path, lock_path, report_path):
    if not manifest_path:
        return {"kind": "voiceprint_gates_plan", "status": "awaiting_data",
                "detail": _VERDICT_AWAIT,
                "plan": {"G0-1": "需 manifest（标签口径六格）",
                         "G0-2": "需 manifest + lock（冻结哈希/跨集校验）",
                         "G0-3": "需 --report（哈希自证/快照完整）",
                         "G1-1": "subprocess filter_eval --self-test",
                         "G1-2": "sv_ref 存在才跑；否则 SKIP",
                         "G1-3": "需报告含 structure_invariants"}}
    return {"kind": "voiceprint_gates_plan", "status": "planned",
            "plan": {"manifest": os.path.basename(manifest_path),
                     "lock": os.path.basename(lock_path
                                              or (manifest_path + ".lock.json")),
                     "report": os.path.basename(report_path) if report_path else None,
                     "checks": ["G0-1 标签口径", "G0-2 测试集冻结",
                                "G0-3 报告可重复", "G1-1 完整自检",
                                "G1-2 聚类回归（ε=0.02）",
                                "G1-3 结构不变量"]}}


# ------------------------------------------------------------------ 自测


def _make_gate_manifest(videos=8, cues_per=75, hard_test=True):
    """构造满足 G0-1/G0-2 全格的合成 manifest（600 cue / 4 语言 / 5+3 split）。"""
    items = []
    langs = ("zh", "en", "ja", "ko")
    labels = ("target", "non_target", "overlap", "unknown")
    for i in range(videos):
        split = "test" if i < 5 else "train"
        cues = []
        for j in range(cues_per):
            cue = {"num": j + 1, "label": labels[j % 4]}
            if hard_test and split == "test":
                cue["hard_flags"] = ["bgm"] if j % 2 == 0 else ["fast_speech"]
            cues.append(cue)
        items.append({
            "id": "v%03d" % (i + 1),
            "media": "C:/gate-mock/%s.mp4" % (i + 1),
            "srt": "C:/gate-mock/%s.srt" % (i + 1),
            "language": langs[i % 4], "templates": ["合成主播"],
            "split": split,
            "speakers": (["spkA"] if i % 2 == 0 else ["spkB"])
            if split == "test" else ["spkC"],
            "cues": cues,
        })
    return {"version": 1, "dataset_id": "gate-mock-01",
            "labeling_guide_version": "lg-gate", "items": items}


def run_self_test():
    """mock 合成 manifest/lock/report 跑通全部判定逻辑（零真实音频/零网络）。"""
    results_log = []

    def check(name, cond):
        results_log.append((name, bool(cond)))
        assert cond, "自测失败：%s" % name

    with tempfile.TemporaryDirectory() as tmp:
        # mock manifest（media/srt 不存在的路径——G0-1/G0-2 的跨集/speakers
        # 判定不读文件；lock 哈希判定单独用真文件 mock）
        manifest = _make_gate_manifest()
        # G0-1 全格满足：600 cue、8 视频、4 语言、test 四类非零、困难 375>=200
        g01 = check_labeling(manifest)
        check("G0-1 满格通过", g01["pass"], )
        for key, cell in g01["cells"].items():
            check("G0-1.%s 该格为过" % key, cell["pass"])

        def break_one(mutator, cell_key):
            bad = copy.deepcopy(manifest)
            mutator(bad)
            g = check_labeling(bad)
            return g["pass"] is False and g["cells"].get(cell_key) is not None \
                and g["cells"][cell_key]["pass"] is False

        check("缺 labeling_guide_version -> FAIL",
              break_one(lambda m: m.pop("labeling_guide_version"),
                        "labeling_guide_version"))
        check("少一种语言 -> language_coverage FAIL",
              break_one(lambda m: [it.__setitem__("language", "zh")
                                   for it in m["items"]
                                   if it["language"] == "en"],
                        "language_coverage"))
        check("视频数 4 -> video_count FAIL",
              break_one(lambda m: m.__setitem__("items", m["items"][:4]),
                        "video_count"))

        def drop_last_cue(m):
            for it in m["items"]:
                it["cues"] = it["cues"][:-1]

        check("cue 不足 600 -> cue_total FAIL",
              break_one(drop_last_cue, "cue_total"))

        def wipe_test_unknown(m):
            for it in m["items"]:
                if it["split"] == "test":
                    for c in it["cues"]:
                        if c["label"] == "unknown":
                            c["label"] = "target"

        check("test 无 unknown -> test_label_coverage FAIL",
              break_one(wipe_test_unknown, "test_label_coverage"))
        bad_hard = copy.deepcopy(manifest)
        for it in bad_hard["items"]:
            if it["split"] == "test":
                for c in it["cues"]:
                    c.pop("hard_flags", None)
                    c["label"] = "target"
        g = check_labeling(bad_hard)
        check("test 困难样本 <200 -> hard_or_overlap_test FAIL",
              not g["pass"]
              and g["cells"]["hard_or_overlap_test"]["pass"] is False)

        # G0-2：lock 哈希（真文件 mock，两片两个 split）+ 跨集 + speakers
        media_a = os.path.join(tmp, "v001.mp4")
        srt_a = os.path.join(tmp, "v001.srt")
        media_b = os.path.join(tmp, "v002.mp4")
        srt_b = os.path.join(tmp, "v002.srt")
        with open(media_a, "wb") as fh:
            fh.write(b"gate-media-1" * 128)
        with open(srt_a, "wb") as fh:
            fh.write("1\n00:00:01,000 --> 00:00:02,000\n甲\n\n".encode("utf-8"))
        with open(media_b, "wb") as fh:
            fh.write(b"gate-media-2" * 128)
        with open(srt_b, "wb") as fh:
            fh.write("1\n00:00:01,000 --> 00:00:02,000\n乙\n\n".encode("utf-8"))
        real_manifest = copy.deepcopy(manifest)
        real_manifest["items"] = real_manifest["items"][:2]
        real_manifest["items"][0]["media"] = media_a
        real_manifest["items"][0]["srt"] = srt_a
        real_manifest["items"][0]["cues"] = manifest["items"][0]["cues"][:10]
        real_manifest["items"][0]["speakers"] = ["spkA"]     # test
        real_manifest["items"][1]["media"] = media_b
        real_manifest["items"][1]["srt"] = srt_b
        real_manifest["items"][1]["cues"] = manifest["items"][1]["cues"][:10]
        real_manifest["items"][1]["split"] = "train"
        real_manifest["items"][1]["speakers"] = ["spkC"]     # train
        manifest_path = os.path.join(tmp, "gate.json")
        with open(manifest_path, "w", encoding="utf-8") as fh:
            json.dump(real_manifest, fh, ensure_ascii=False)
        lock = VB.build_lock(manifest_path)
        lock_path = os.path.join(tmp, "gate.lock.json")
        with open(lock_path, "w", encoding="utf-8") as fh:
            json.dump(lock, fh, ensure_ascii=False)
        g02 = check_frozen(real_manifest, manifest_path, lock_path)
        check("G0-2 lock 哈希通过", g02["cells"]["lock_hashes"]["pass"])
        check("G0-2 speakers 合规通过",
              g02["cells"]["speaker_not_across_splits"]["pass"])
        check("G0-2 无视频跨集通过",
              g02["cells"]["no_video_across_splits"]["pass"])
        check("G0-2 整格通过", g02["pass"])

        bad_media = copy.deepcopy(lock)
        bad_media["items"][0]["media_sha256"] = "1" * 64
        bad_path = os.path.join(tmp, "bad_media.lock.json")
        with open(bad_path, "w", encoding="utf-8") as fh:
            json.dump(bad_media, fh, ensure_ascii=False)
        g = check_frozen(real_manifest, manifest_path, bad_path)
        check("G0-2 media 哈希篡改 -> FAIL",
              not g["pass"] and not g["cells"]["lock_hashes"]["pass"])

        cross = copy.deepcopy(real_manifest)
        cross["items"][1]["media"] = media_a        # 复用 test 片的视频
        g = check_frozen(cross, manifest_path, lock_path)
        check("同一视频跨 split -> FAIL",
              not g["cells"]["no_video_across_splits"]["pass"])

        cross_spk = copy.deepcopy(real_manifest)
        cross_spk["items"][1]["speakers"] = ["spkA", "spkC"]  # spkA 已在 test
        g = check_frozen(cross_spk, manifest_path, lock_path)
        check("同说话人跨 split -> FAIL",
              not g["cells"]["speaker_not_across_splits"]["pass"])
        no_spk = copy.deepcopy(real_manifest)
        no_spk["items"][0].pop("speakers")
        g = check_frozen(no_spk, manifest_path, lock_path)
        check("speakers 未登记 -> FAIL（提示补登）",
              not g["cells"]["speaker_not_across_splits"]["pass"])

        # G0-3：用 baseline 构建器出真报告（mock 数据走真实构建器）
        results = []
        for it in real_manifest["items"]:
            decisions = []
            for c in it["cues"]:
                decisions.append({
                    "num": c["num"], "state": "keep",
                    "start": 1000 + 100 * c["num"],
                    "end": 2000 + 100 * c["num"],
                    "duration_ms": 1000, "score": 0.7, "source": "synthetic",
                    "reason": "", "speaker": "", "cluster": -1})
            results.append({"id": it["id"], "decisions": decisions})
        report = VB.build_report(manifest_path, real_manifest, results,
                                 "precision")
        report_path = os.path.join(tmp, "gate_baseline.json")
        VB.write_report(report, report_path)
        g03 = check_reproducible(report_path, report)
        check("G0-3 真报告通过", g03["pass"])
        check("G0-3 sha 文件交叉一致",
              g03["cells"]["report_sha256"]["sha_file_match"] is True)
        tampered = copy.deepcopy(report)
        tampered["report_sha256"] = "0" * 64
        g = check_reproducible(report_path, tampered)
        check("G0-3 报告哈希被篡 -> FAIL",
              not g["cells"]["report_sha256"]["pass"])
        nosnap = copy.deepcopy(report)
        nosnap["reproducibility"]["versions"]["config_snapshot"] = {}
        g = check_reproducible(report_path, nosnap)
        check("config_snapshot 缺失 -> FAIL",
              not g["cells"]["config_snapshot_explicit"]["pass"])
        norep = copy.deepcopy(report)
        norep["reproducibility"]["versions"]["toolbox_git_describe"] = None
        g = check_reproducible(report_path, norep)
        check("reproducibility 缺口 -> FAIL",
              not g["cells"]["reproducibility_complete"]["pass"])

        # G1-2：解析 + 比对 + SKIP，全部注入零耗时
        sample = ("== A. 模板质量（单片段 vs 多片段录入）==\n"
                  "  模板说话人  模板      同人min  异人max   边际\n"
                  "  fangjun    单片段     0.912    0.204   0.708\n"
                  "  fangjun    多片段     0.931    0.198   0.733\n"
                  "== B. 抗劣化（边际 = 同人min - 异人max）==\n"
                  "== C. 聚类纯度（12 条 cue，9 条参与聚类，3 簇）==\n"
                  "  pairwise purity = 0.947（66 对）\n")
        parsed = parse_accuracy_output(sample)
        check("accuracy 解析 purity", parsed["purity"] == 0.947
              and parsed["pairs"] == 66)
        check("accuracy 解析 A 最小边际", parsed["min_margin_a"] == 0.708)
        meta_path = os.path.join(tmp, "meta.json")
        fake_runner = lambda: (0, sample, "")
        with open(meta_path, "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "purity": 0.950, "pairs": 66,
                       "min_margin_a": 0.715}, fh)
        g = check_cluster_regression(record=False, meta_path=meta_path,
                                     runner=fake_runner)
        check("G1-2 纯度回退 0.003<=ε 且边际回退 0.007<=ε -> PASS",
              g["pass"] and g["status"] == "checked")
        meta_bad = os.path.join(tmp, "meta_bad.json")
        with open(meta_bad, "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "purity": 0.950, "pairs": 66,
                       "min_margin_a": 0.900}, fh)
        g = check_cluster_regression(record=False, meta_path=meta_bad,
                                     runner=fake_runner)
        check("G1-2 边际大幅回退 -> FAIL",
              not g["pass"] and g["status"] == "checked")
        g = check_cluster_regression(record=False,
                                     meta_path=os.path.join(tmp, "none.json"),
                                     runner=fake_runner)
        check("G1-2 基线未锁定 -> no_baseline（按未过计）",
              not g["pass"] and g["status"] == "no_baseline")
        g_rec = check_cluster_regression(record=True, meta_path=meta_path,
                                         runner=fake_runner)
        check("G1-2 record 锁定基线", g_rec["pass"]
              and g_rec["status"] == "locked")
        # SKIP 显式标注：注入不存在目录验证 skip 不算 FAIL
        saved_ref = SV_REF_DIR
        try:
            globals()["SV_REF_DIR"] = "Z:/nonexistent/sv_ref"
            g = check_cluster_regression(record=False, meta_path=meta_path,
                                         runner=fake_runner)
            check("sv_ref 不存在 -> SKIP 且不算 FAIL",
                  g["status"] == "skipped" and g["pass"] is True)
        finally:
            globals()["SV_REF_DIR"] = saved_ref

        # G1-3：结构不变量三态
        good_report = copy.deepcopy(report)
        good_report["structure_invariants"] = {
            "overall": {"cue_count_preserved_pct": 100.0,
                        "timeline_unchanged_pct": 100.0,
                        "newline_bom_preserved": True,
                        "index_renumbered": True}}
        check("G1-3 结构不变量全达标 -> PASS",
              check_structure_invariants(good_report)["pass"])
        bad_si = copy.deepcopy(good_report)
        bad_si["structure_invariants"]["overall"][
            "cue_count_preserved_pct"] = 99.5
        check("G1-3 账目 99.5 -> FAIL", not check_structure_invariants(bad_si)["pass"])
        null_si = copy.deepcopy(report)
        null_si["structure_invariants"] = None
        check("G1-3 只读模式(null) -> FAIL（需 --emit-products）",
              not check_structure_invariants(null_si)["pass"])
        check("G1-3 无报告 -> FAIL",
              not check_structure_invariants(None)["pass"])

        # G1-1：真跑 WP1 filter_eval --self-test（复用消费确认）
        g11 = run_filter_eval_selftest()
        check("G1-1 filter_eval --self-test exit 0",
              g11["pass"] and g11.get("exit_code") == 0)

        # 汇总：无 manifest -> 待数据不放行
        agg = run_gates()
        check("无 manifest -> awaiting_data 且 overall=False",
              agg["g0"]["status"] == "awaiting_data"
              and agg["overall"] is False and "待数据" in agg["verdict"])
        agg2 = run_gates(manifest_path=manifest_path, lock_path=lock_path,
                         report_path=report_path, runner=fake_runner,
                         meta_path=os.path.join(tmp, "none.json"))
        # mock manifest 只有 1 片/10 cue：G0-1 必 FAIL（预期），验证汇总链路
        check("汇总链路输出 g0.fail/g1/overall",
              agg2["g0"]["status"] == "fail" and "g1" in agg2
              and isinstance(agg2["overall"], bool))

    passed = sum(1 for _n, ok in results_log if ok)
    print("voiceprint_gates 自测通过：%d/%d 项断言（mock 合成数据，"
          "不代表业务精准率）" % (passed, len(results_log)))
    return results_log


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    ap = argparse.ArgumentParser(description="G0/G1 声纹门禁判定")
    ap.add_argument("--manifest", help="frozen manifest JSON")
    ap.add_argument("--lock", help="lock JSON；缺省 <manifest>.lock.json")
    ap.add_argument("--report", help="voiceprint_baseline 基线报告 JSON")
    ap.add_argument("--g1-record", action="store_true",
                    help="G1-2 首跑锁定基线数字（写 baseline_meta.json）")
    ap.add_argument("--baseline-meta", help="G1-2 基线数字文件（缺省 data/eval/）")
    ap.add_argument("--skip-g1-selftest", action="store_true",
                    help="跳过 G1-1 子进程自检（仅自测/调试用）")
    ap.add_argument("--dry-run", action="store_true", help="只输出门禁计划")
    ap.add_argument("--self-test", action="store_true",
                    help="mock 合成数据自测（零真实音频/零网络）")
    args = ap.parse_args(argv)

    if args.self_test:
        run_self_test()
        return 0
    if args.dry_run:
        print(json.dumps(dry_run_plan(args.manifest, args.lock, args.report),
                         ensure_ascii=False, indent=2))
        return 0
    try:
        result = run_gates(manifest_path=args.manifest, lock_path=args.lock,
                           report_path=args.report, g1_record=args.g1_record,
                           meta_path=args.baseline_meta,
                           skip_g1_selftest=args.skip_g1_selftest)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.manifest is None:
            return 1                    # 待数据 = 不放行
        return 0 if result["overall"] else 1
    except (OSError, ValueError) as exc:
        print("门禁执行错误：%s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
