# -*- coding: utf-8 -*-
# @version 3.1.3
"""CLI 输出 golden 基线（2026-11-20 三层独立改造 P0.5 验收底座）。

改造前捕获 11 命令的 --json 信封 / --help 文本，改造后重采对比，
**旧字段逐项一致、允许只增字段**（P1 信封增强 changes/candidates 等）。

分级策略（确定性 vs 环境依赖）：
  full      确定性命令，归一化后全量比对（status/info/calibrate/stabilize/audit）
  structure 网络/ffmpeg 相关，只比键集 + ok（translate/compose/split）
  help      重副作用命令不实跑，只冻 --help 文本（download/transcribe/bili-submit）

隔离措施：校准/审计用 --kb 指向临时副本，**不写根目录学习库**（并行会话资产）；
产物全部显式 --out 落 data/tmp/cli_golden_fixtures/，规避同秒目录冲突。

用法：
  tools\\python\\python.exe scripts\\dev\\_cli_golden.py --rebase   # 捕获基线
  tools\\python\\python.exe scripts\\dev\\_cli_golden.py            # 重采对比
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(ROOT, "src")
PY = os.path.join(ROOT, "tools", "python", "python.exe")
CLI = os.path.join(SRC, "agent_cli.py")
FIX = os.path.join(ROOT, "data", "tmp", "cli_golden_fixtures")
GOLDEN = os.path.join(HERE, "_golden", "cli")

NET_ERR = re.compile(r"10054|10061|Connection|429|421|timed? ?out|网络|代理", re.I)

#: 透传三件的产物断言（堵「空输入打印帮助 rc=0 与真成功同信封」的假通过盲区）
ARTIFACTS = {"calibrate": ["cal.srt"], "stabilize": ["st.srt"], "audit": ["audit.md"]}


def _norm(obj):
    """递归把程序根/夹具绝对路径归一为占位符，消除机器相关差异。"""
    if isinstance(obj, str):
        return obj.replace(FIX, "<FIX>").replace(ROOT, "<ROOT>")
    if isinstance(obj, dict):
        return {k: _norm(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_norm(v) for v in obj]
    return obj


def _fixtures():
    os.makedirs(FIX, exist_ok=True)
    srt = os.path.join(FIX, "sample.srt")
    with open(srt, "w", encoding="utf-8", newline="\n") as f:
        f.write("1\n00:00:01,000 --> 00:00:03,000\n"
                "Welcome to Endfield.\n欢迎来到恩德菲尔德。\n\n"
                "2\n00:00:04,000 --> 00:00:06,000\n"
                "The Administrator is here.\n管理员来了。\n\n"
                "3\n00:00:07,000 --> 00:00:09,000\n"
                "Endfield awaits.\n终末地等着你。\n\n")
    kb = os.path.join(FIX, "kb.json")
    root_kb = os.path.join(ROOT, "subtitle_learned_kb.json")
    if os.path.isfile(root_kb):
        shutil.copyfile(root_kb, kb)          # 副本隔离，根学习库只读不写
    else:
        with open(kb, "w", encoding="utf-8") as f:
            f.write("{}")
    # stabilize 脏样例：稳定化契约「无候选不写文件」，干净样例无法验证产物落盘；
    # 超长含标点 cue（拆分候选）+ 相邻碎片（合并候选）确保有改动、必落盘。
    dirty = os.path.join(FIX, "dirty.srt")
    with open(dirty, "w", encoding="utf-8", newline="\n") as f:
        f.write("1\n00:00:01,000 --> 00:00:02,000\n嗯。\n\n"
                "2\n00:00:02,100 --> 00:00:03,000\n啊。\n\n"
                "3\n00:00:04,000 --> 00:00:12,000\n"
                "这是一条非常长的字幕行，里面包含了很多个分句，"
                "用来触发稳定化层的超长 cue 拆分候选，确保产物落盘断言有效。\n\n")
    mp4 = os.path.join(FIX, "tiny.mp4")
    if not os.path.isfile(mp4):
        sys.path.insert(0, SRC)
        import video_toolbox as engine        # noqa: PLC0415
        ff, _ = engine.ensure_ffmpeg()
        subprocess.run(
            [ff, "-y", "-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=10",
             "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-t", "3",
             "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
             "-shortest", mp4],
            capture_output=True, check=True)
    return srt, kb, mp4, dirty


def _cases(srt, kb, mp4, dirty):
    j = lambda *a: list(a) + ["--json"]       # noqa: E731
    return [
        ("status", "full", j("status"), ["features"]),
        ("info", "full", j("info", srt), []),
        ("translate", "structure",
         j("translate", srt, "--engine", "bing", "--out", os.path.join(FIX, "tr.zh.srt")), []),
        ("calibrate", "full",
         j("calibrate", srt, "--endobi", "--out", os.path.join(FIX, "cal.srt"),
           "--report", os.path.join(FIX, "cal.tsv"), "--kb", kb), []),
        ("stabilize", "full",
         j("stabilize", dirty, "--out", os.path.join(FIX, "st.srt")), []),
        ("audit", "full",
         j("audit", srt, "--mode", "bi", "--out", os.path.join(FIX, "audit.md"),
           "--kb", kb), []),
        ("compose", "structure",
         j("compose", mp4, srt, "--mode", "soft", "--out", os.path.join(FIX, "comp.mp4")), []),
        ("split", "structure",
         j("split", mp4, "--durations", "1s,1s", "--mode", "auto",
           "--out", os.path.join(FIX, "split"), "--verify", "quick"), []),
        ("download", "help", ["download", "--help"], []),
        ("transcribe", "help", ["transcribe", "--help"], []),
        ("bili-submit", "help", ["bili-submit", "--help"], []),
    ]


def _capture(argv):
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    r = subprocess.run([PY, CLI] + argv, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=ROOT, env=env,
                       timeout=300)
    return r


def _snapshot(case):
    name, policy, argv, ignore = case
    r = _capture(argv)
    if policy == "help":
        return {"cmd": name, "policy": policy, "ignore_keys": ignore,
                "text": _norm(r.stdout), "rc": r.returncode}
    try:
        payload = json.loads(r.stdout)
    except ValueError:
        payload = {"_parse_error": r.stdout[:400], "rc": r.returncode,
                   "stderr_tail": r.stderr[-300:]}
    return {"cmd": name, "policy": policy, "ignore_keys": ignore,
            "payload": _norm(payload), "rc": r.returncode,
            "artifacts": {n: os.path.isfile(os.path.join(FIX, n))
                          for n in ARTIFACTS.get(name, [])}}


def _compare(old, new):
    """返回 (ok, detail)。full=去 ignore 键后全量；structure=键集+ok；help=文本。"""
    if old["policy"] == "help":
        same = old["text"] == new["text"] and old["rc"] == new["rc"]
        return same, "" if same else "help 文本或退出码变化"
    op, np = old["payload"], new["payload"]
    if "_parse_error" in np:
        if old["policy"] == "structure" and NET_ERR.search(str(np)):
            return True, "ENV：网络抖动，结构基线跳过"
        return False, "stdout 非 JSON：%s" % str(np)[:160]
    if old["policy"] == "structure":
        ok = set(op) == set(np) and op.get("ok") == np.get("ok")
        if not ok and NET_ERR.search(str(np.get("error", ""))):
            return True, "ENV：网络抖动，结构基线跳过"
        return ok, "" if ok else "键集/ok 变化：%s → %s" % (sorted(op), sorted(np))
    op = {k: v for k, v in op.items() if k not in old["ignore_keys"]}
    np = {k: v for k, v in np.items() if k not in old["ignore_keys"]}
    # 产物断言：透传三件必须真落盘（信封同值不等于行为正确）
    missing = [n for n, ex in new.get("artifacts", {}).items() if not ex]
    if missing:
        return False, "产物缺失=%s（信封可能假通过）" % missing
    # 只增字段允许：旧键必须逐项一致，新键放行
    drift = [k for k in op if k not in np or op[k] != np[k]]
    added = [k for k in np if k not in op]
    return not drift, ("漂移键=%s" % drift if drift
                       else ("只增字段=%s" % added if added else ""))


def main():
    rebase = "--rebase" in sys.argv
    srt, kb, mp4, dirty = _fixtures()
    os.makedirs(GOLDEN, exist_ok=True)
    fails, notes = [], []
    for case in _cases(srt, kb, mp4, dirty):
        name = case[0]
        path = os.path.join(GOLDEN, name.replace("-", "_") + ".json")
        snap = _snapshot(case)
        if rebase:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                json.dump(snap, f, ensure_ascii=False, indent=2)
            print("[BASE] %-12s rc=%s keys=%s" % (
                name, snap["rc"],
                sorted(snap.get("payload", {})) if "payload" in snap else "help"))
            continue
        if not os.path.isfile(path):
            fails.append("%s: 缺基线（先 --rebase）" % name)
            continue
        with open(path, encoding="utf-8") as f:
            old = json.load(f)
        ok, detail = _compare(old, snap)
        print("%s %-12s %s" % ("[OK]" if ok else "[DIFF]", name, detail))
        if not ok:
            fails.append("%s: %s" % (name, detail))
        elif detail:
            notes.append("%s: %s" % (name, detail))
    print("\n==== golden：%s ====" % ("全部一致" if not fails else "%d 处漂移" % len(fails)))
    for n in notes:
        print("  注:", n)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())