# -*- coding: utf-8 -*-
# @version 3.1.4
"""runner —— MCP 执行通道：子进程 api_worker（stdout 隔离，崩溃/取消在子进程内）。

每次调用独立进程（--data-root / 引擎状态不串味）；argv 数组 shell=False；
cwd=程序根；PYTHONUTF8=1；CREATE_NO_WINDOW。产物命令强制显式 out（带调用 id，
规避 _agent_out_dir 同秒目录冲突）。长任务异步句柄留 P2。
"""
from __future__ import annotations

import json
import os
import subprocess
import uuid

from features._api.runtime import APP_ROOT, _agent_out_dir


def run_command(cmd: str, params: dict, timeout_s: int) -> dict:
    params = dict(params)
    cid = uuid.uuid4().hex[:8]
    if cmd == "download" and not params.get("dir"):
        params["dir"] = os.path.join(_agent_out_dir(), "mcp-" + cid)
    elif cmd in ("transcribe", "translate", "split") and not params.get("out"):
        params["out"] = os.path.join(_agent_out_dir(), "mcp-" + cid)
    elif cmd == "compose" and not params.get("out"):
        params["out"] = os.path.join(_agent_out_dir(), "mcp-" + cid + ".composed.mp4")

    out_file = os.path.join(APP_ROOT, "data", "tmp", "vt_mcp_%s.json" % cid)
    os.makedirs(os.path.dirname(out_file), exist_ok=True)
    worker = os.path.join(APP_ROOT, "src", "api_worker.py")
    py = os.path.join(APP_ROOT, "tools", "python", "python.exe")
    req = json.dumps({"cmd": cmd, "params": params}, ensure_ascii=False)
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    try:
        proc = subprocess.run(
            [py, worker, "--out", out_file], input=req.encode("utf-8"),
            capture_output=True, cwd=APP_ROOT, env=env, timeout=timeout_s,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return {"ok": False,
                "error": "执行超时（%ss）：下载/转录/硬烧等长任务异步句柄见 P2 规划" % timeout_s}
    try:
        with open(out_file, encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, ValueError):
        payload = {"ok": False,
                   "error": "api_worker 未产出有效信封（退出码 %s）" % proc.returncode}
    finally:
        try:
            os.remove(out_file)
        except OSError:
            pass
    return payload