# -*- coding: utf-8 -*-
# @version 3.2.0
"""WP4-G0：Jev 生成前分诊数据集构建（架构骨架；真实数据后期投喂）。

从留出片源跑 R0 影子分诊收集 (chunk 状态, ground truth)，产出
data/entities/jev_triage_cases.jsonl 供 eval_jev_triage_gate.py 回放。

每个 case 的字段（与 eval 侧 load_cases 对齐）：
  * id / source / block / cue_total
  * issue_types / gate_local / gate_reason_local
    （calib_triage_decision._gate_route_triage 的本地确定性闸门口径）
  * jev_general / jev_confidence
    （R0 影子期间 apply_triage_shadow 对该块的 Jev 四问中的 general 答案；
    影子未激活时留空，门禁回放退化为纯本地闸门 alone）
  * ground_truth ∈ {skippable, needs_generative}
  * gold_status ∈ {mechanical, human_confirmed, pending_human}

ground truth 口径（任务定义）：对本地闸门判 would_skip 的块，跳过生成式重放
校准（机械基线照常 → verify → learn），与全量产物逐 cue diff 得漏改明细；
零漏改且人工抽检确认 → skippable；有漏改或人工判需改 → needs_generative。

管线步骤（架构骨架，真实执行需 chat 端点，本骨架只到计划层）：
  1. load_holdouts：留出片源清单（jsonl：{source, mode, style}）；
  2. run_source_calibrate：跑 calibrate 主流程（R0 影子挂载开启，client 激活
     或 shadow 记录模式），取 result["triage"]（块级记录 + would_skip）与
     result["decision_review"]；
  3. replay_with_skips：按 would_skip 块集模拟「跳过生成式」的重放产物；
  4. ground_truth_diff：全量产物 vs 重放产物逐 cue diff → 漏改明细；
  5. emit_case：聚合块状态 + ground truth → jsonl。

用法：
  tools\\python\\python.exe scripts\\dev\\build_jev_triage_dataset.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

OUT_DEFAULT = "data/entities/jev_triage_cases.jsonl"
HOLDOUTS_DEFAULT = "data/entities/jev_triage_holdouts.jsonl"

#: 骨架标记：真实校准执行点尚未接端点（G0 投喂时补 chat 工厂即可）
SKELETON = True

CASE_FIELDS = ("id", "source", "block", "cue_total", "issue_types",
               "gate_local", "gate_reason_local", "jev_general",
               "jev_confidence", "ground_truth", "gold_status",
               "missed_changes")


# ---------------------------------------------------------------- 输入


def load_holdouts(path):
    """读留出片源清单（jsonl：{source, mode, style}）。"""
    holdouts = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                h = json.loads(line)
                h.setdefault("mode", "")
                h.setdefault("style", "term")
                holdouts.append(h)
    return holdouts


# ---------------------------------------------------------------- 管线步骤


def run_source_calibrate(holdout, decision_client=None, log=None):
    """步骤 2：对单个留出片源跑 R0 影子校准，收集块级状态。

    骨架说明（G0 投喂时实现）：构造 chat 工厂与 decision_client（shadow 模式
    激活），调 features.calibrate.calib_ai_agent.calibrate(...)；预期产物：
      * result["triage"]["items"]：块级分诊记录（gated=本地闸门 / ok=Jev 四问）
      * result["triage"]["would_skip"]：本地闸门判「本可跳过」的块数
      * result["out"]：全量校准产物路径（ground truth diff 的基准）
    本骨架不联网、不跑真实校准，恒返回 None（调用方跳到 dry-run 计划层）。
    """
    if SKELETON:
        return None
    from core.calibrate.ai import build_chat, decision_client as _mk_client
    from features.calibrate.calib_ai_agent import calibrate
    chat = build_chat(log=log)
    client = decision_client if decision_client is not None else _mk_client()
    return calibrate(
        holdout["source"], mode_flag=holdout.get("mode") or "",
        style=holdout.get("style") or "term",
        chat=chat, decision_client=client, log=log)


def replay_with_skips(result, skip_blocks):
    """步骤 3：按 would_skip 块集模拟「跳过生成式」的重放产物。

    骨架说明（G0 投喂时实现）：对 result["out"] 走机械基线（照常）→ 只对
    非 skip 块跑生成式改动合并 → verify → learn，产出重放产物路径。
    本骨架恒返回 None。
    """
    if SKELETON:
        return None
    raise NotImplementedError("G0 投喂时实现：skip 重放校准")


def ground_truth_diff(full_out, replay_out):
    """步骤 4：全量产物 vs 重放产物逐 cue diff → 漏改明细。

    骨架说明（G0 投喂时实现）：parse_srt 两产物，对重放产物中未改而全量产物
    已改的 cue 记 (num, old, new) 为漏改明细；块内零漏改且人工抽检确认 →
    skippable。本骨架恒返回 None。
    """
    if SKELETON:
        return None
    raise NotImplementedError("G0 投喂时实现：逐 cue 漏改 diff")


def build_case(block_state, ground_truth, gold_status="pending_human",
               missed=None):
    """步骤 5：把块级状态 + ground truth 聚合成 case（字段对齐 eval 侧）。"""
    return {
        "id": "%s#b%s" % (block_state.get("source"),
                          block_state.get("block")),
        "source": block_state.get("source"),
        "block": block_state.get("block"),
        "cue_total": block_state.get("cue_total"),
        "issue_types": list(block_state.get("issue_types") or []),
        "gate_local": block_state.get("route") or "",
        "gate_reason_local": block_state.get("gate") or "",
        "jev_general": block_state.get("choice_general") or "",
        "jev_confidence": block_state.get("confidence"),
        "ground_truth": ground_truth,
        "gold_status": gold_status,
        "missed_changes": missed if missed is not None else [],
    }


def emit_cases(cases, out_path):
    """写 jsonl（目录不存在则创建；字段固定顺序，便于 diff 回填）。"""
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        for c in cases:
            f.write(json.dumps({k: c.get(k) for k in CASE_FIELDS},
                               ensure_ascii=False, sort_keys=False) + "\n")
    return out_path


# ---------------------------------------------------------------- dry-run


def dry_run(args) -> int:
    """--dry-run：打印管线计划与输出 schema，不跑真实校准、不写数据文件。"""
    holdouts_path = os.path.join(ROOT, args.holdouts)
    holdouts = []
    if os.path.isfile(holdouts_path):
        try:
            holdouts = load_holdouts(holdouts_path)
        except (ValueError, OSError) as exc:
            print("留出清单读取失败（dry-run 继续）：%s" % exc)
    plan = {
        "schema": "jev-triage-dataset/1",
        "skeleton": SKELETON,
        "dry_run": True,
        "holdouts_file": args.holdouts,
        "holdouts_found": len(holdouts),
        "holdouts_preview": holdouts[:5],
        "out": args.out,
        "steps": [
            "load_holdouts(%s)" % args.holdouts,
            "run_source_calibrate(each holdout; R0 影子挂载开启)",
            "replay_with_skips(result, would_skip 块集)",
            "ground_truth_diff(全量产物, 重放产物) → 漏改明细",
            "build_case × N → emit_cases(%s)" % args.out,
        ],
        "case_fields": list(CASE_FIELDS),
        "ground_truth_rule": (
            "would_skip 块跳过生成式重放（机械基线/verify/learn 照常）→ "
            "与全量产物 diff：零漏改且人工确认 → skippable；否则 needs_generative"),
        "notes": [
            "骨架不联网：run_source_calibrate/replay_with_skips/"
            "ground_truth_diff 在 SKELETON=True 时恒返回 None；",
            "G0 数据投喂后才可运行 eval_jev_triage_gate.py 的正式回放。",
        ],
    }
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Jev 分诊数据集构建（骨架）")
    ap.add_argument("--holdouts", default=HOLDOUTS_DEFAULT,
                    help="留出片源清单 jsonl：{source, mode, style}")
    ap.add_argument("--out", default=OUT_DEFAULT,
                    help="输出 cases jsonl 路径")
    ap.add_argument("--dry-run", action="store_true",
                    help="只打印管线计划与 schema，不执行真实校准")
    args = ap.parse_args(argv)

    if args.dry_run or SKELETON:
        return dry_run(args)
    holdouts = load_holdouts(os.path.join(ROOT, args.holdouts))
    cases = []
    for h in holdouts:
        result = run_source_calibrate(h)
        if result is None:
            continue
        triage = result.get("triage") or {}
        for it in triage.get("items") or []:
            cases.append(build_case(
                dict(it, source=os.path.basename(h.get("source") or "")),
                ground_truth="pending_human"))
    out = os.path.join(ROOT, args.out)
    emit_cases(cases, out)
    print("已写 %d 个 case → %s（ground truth 待重放/人工回填）"
          % (len(cases), out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
