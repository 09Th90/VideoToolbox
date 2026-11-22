# -*- coding: utf-8 -*-
# @version 3.2.5
"""_selftest_api —— L1 API 层自检（2026-11-20 三层独立改造）。

  1  spec  sanity：11 命令 / 8 可反射命令 35 参数 / calibrate 33 模式旗标
  2  dispatch 11 命令信封结构（轻命令实跑 + 重命令错误信封，无副作用）
  3  透传三件 exit_code 语义 + 只增字段（calibrate changes/mode_name、audit candidates）
  4  api_worker 子进程往返 + stdout 零字节（OS 级隔离）
  5  依赖 purity：dispatch 后 sys.modules 无 agent_cli / features._cli / features.mcp

用法：tools\\python\\python.exe scripts\\dev\\_selftest_api.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(ROOT, "src")
PY = os.path.join(ROOT, "tools", "python", "python.exe")
FIX = os.path.join(ROOT, "data", "tmp", "api_selftest_fix")
sys.path.insert(0, SRC)

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("%s %s%s" % ("[OK]" if ok else "[FAIL]", name,
                       (" —— " + detail) if detail else ""))


def _fixtures():
    os.makedirs(FIX, exist_ok=True)
    srt = os.path.join(FIX, "sample.srt")
    with open(srt, "w", encoding="utf-8", newline="\n") as f:
        f.write("1\n00:00:01,000 --> 00:00:03,000\n"
                "Welcome to Endfield.\n欢迎来到恩德菲尔德。\n\n"
                "2\n00:00:04,000 --> 00:00:06,000\n"
                "Endfield awaits.\n终末地等着你。\n\n")
    kb = os.path.join(FIX, "kb.json")
    root_kb = os.path.join(ROOT, "subtitle_learned_kb.json")
    if os.path.isfile(root_kb):
        import shutil
        shutil.copyfile(root_kb, kb)
    else:
        with open(kb, "w", encoding="utf-8") as f:
            f.write("{}")
    return srt, kb


def main():
    from features._api import command_names, dispatch
    from features._api import spec

    # 1 —— spec sanity
    check("spec 11 命令", len(spec.COMMANDS) == 11, str(len(spec.COMMANDS)))
    n_params = sum(len(c.params) for c in spec.COMMANDS if not c.passthrough)
    check("8 可反射命令 35 参数", n_params == 35, str(n_params))
    check("calibrate 33 模式旗标",
          len(spec.get_command("calibrate").mode_flags) == 33)
    check("command_names 与 spec 同源",
          set(command_names()) == {c.name for c in spec.COMMANDS})

    srt, kb = _fixtures()
    log_lines = []
    log = log_lines.append

    # 2 —— 轻命令实跑
    r = dispatch("status", {}, log)
    check("status 信封", r.get("ok") is True and "features" in r
          and r.get("version") == "1.0.0")
    r = dispatch("info", {"file": srt}, log)
    check("info 信封", r.get("ok") is True and r.get("n_cues") == 2, str(r)[:120])
    r = dispatch("info", {"file": os.path.join(FIX, "不存在.srt")}, log)
    check("info 缺文件错误信封", r.get("ok") is False and "error" in r)

    # 3 —— 透传三件（exit_code 语义 + 只增字段）
    out = os.path.join(FIX, "cal.srt")
    rep = os.path.join(FIX, "cal.tsv")
    r = dispatch("calibrate", {"input": [srt],
                               "extra": ["--endobi", "--out", out,
                                         "--report", rep, "--kb", kb]}, log)
    check("calibrate exit_code 语义", "exit_code" in r and r["exit_code"] == 0
          and os.path.isfile(out), str(r)[:120])
    check("calibrate 只增字段", r.get("mode_name") == "endobi"
          and isinstance(r.get("changes"), int), str(r)[:160])
    out2 = os.path.join(FIX, "st.srt")
    dirty = os.path.join(FIX, "dirty.srt")
    with open(dirty, "w", encoding="utf-8", newline="\n") as f:
        f.write("1\n00:00:01,000 --> 00:00:12,000\n"
                "这是一条非常长的字幕行，里面包含了很多个分句，"
                "用来触发稳定化层的超长 cue 拆分候选，确保产物落盘。\n\n")
    r = dispatch("stabilize", {"input": [dirty], "extra": ["--out", out2]}, log)
    check("stabilize exit_code + 产物", r.get("exit_code") == 0
          and os.path.isfile(out2), str(r)[:120])
    rep3 = os.path.join(FIX, "audit.md")
    r = dispatch("audit", {"input": [srt],
                           "extra": ["--mode", "bi", "--out", rep3, "--kb", kb]}, log)
    check("audit exit_code（0/1 均合法）", r.get("exit_code") in (0, 1)
          and os.path.isfile(rep3), str(r)[:120])
    check("audit 只增字段 candidates", isinstance(r.get("candidates"), int),
          str(r)[:160])
    r = dispatch("calibrate", {"input": [], "extra": []}, log)
    check("透传缺输入错误信封", r.get("ok") is False and "exit_code" not in r)

    # 2b —— 重命令错误信封（无副作用：缺文件/空参在引擎调用前或本地报错）
    r = dispatch("transcribe", {"file": os.path.join(FIX, "不存在.mp4")}, log)
    check("transcribe 缺文件错误信封", r.get("ok") is False and "error" in r)
    r = dispatch("bili-submit", {}, log)
    check("bili-submit 空参错误信封", "exit_code" in r and r["exit_code"] != 0,
          str(r)[:120])
    r = dispatch("不存在", {}, log)
    check("未知命令错误信封", r.get("ok") is False)

    # 4 —— api_worker 往返 + stdout 纯净
    wf = os.path.join(FIX, "worker.json")
    req = json.dumps({"cmd": "info", "params": {"file": srt}})
    p = subprocess.run([PY, os.path.join(SRC, "api_worker.py"), "--out", wf],
                       input=req.encode("utf-8"), capture_output=True,
                       cwd=ROOT, timeout=120)
    ok = p.returncode == 0 and len(p.stdout) == 0
    try:
        with open(wf, encoding="utf-8") as f:
            d = json.load(f)
        ok = ok and d.get("ok") is True and d.get("n_cues") == 2
    except (OSError, ValueError):
        ok = False
    check("api_worker 往返 + stdout 零字节", ok,
          "rc=%s stdout=%dB" % (p.returncode, len(p.stdout)))

    # 5 —— 依赖 purity（status 经 registry 发现 mcp 纯清单属设计内；
    #       禁的是 SDK 本体、CLI 层、MCP 实现模块 server/runner/tool_specs）
    leaked = [m for m in sys.modules
              if m == "agent_cli" or m == "features._cli"
              or m == "mcp" or m.startswith("mcp.")
              or (m.startswith("features.mcp.") and m != "features.mcp.feature")]
    check("dispatch 不拉 SDK/CLI/MCP 实现层", not leaked, str(leaked))

    print("\n==== 结果：%d 通过 / %d 失败 ====" % (len(PASS), len(FAIL)))
    for f in FAIL:
        print("  FAIL:", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())