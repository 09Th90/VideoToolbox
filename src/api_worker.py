# -*- coding: utf-8 -*-
# @version 3.1.2
"""api_worker —— API 层进程入口（L1，2026-11-20 三层独立改造）。

MCP runner 的执行通道：stdin 读 {"cmd", "params"[, "data_root"]} → 调
features._api.dispatch → 信封写 --out 文件。**stdout 全程重定向到 stderr**
（OS 级 dup2，引擎 424 处裸 print 与子进程继承输出全部隔离，杜绝协议帧污染）。

用法：tools\\python\\python.exe src\\api_worker.py --out <结果.json>
进程 cwd 自动落程序根；每次调用独立进程（--data-root / 引擎状态不串味）。
本文件只依赖 features._api（L1），禁 import CLI/MCP 入口层。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

SRC = os.path.dirname(os.path.abspath(__file__))
APP_ROOT = os.path.dirname(SRC)


def main() -> int:
    ap = argparse.ArgumentParser(description="视频工具箱 API worker（stdin→信封文件）")
    ap.add_argument("--out", required=True, help="信封 JSON 落盘路径")
    args = ap.parse_args()

    # stdout → stderr（OS 级：子进程继承的 fd 一并隔离）；必须早于引擎 import
    try:
        os.dup2(sys.stderr.fileno(), sys.stdout.fileno())
    except (OSError, ValueError, AttributeError):
        pass
    sys.stdout = sys.stderr

    if SRC not in sys.path:
        sys.path.insert(0, SRC)
    os.chdir(APP_ROOT)

    try:
        req = json.load(sys.stdin)
    except ValueError as e:
        req = {}
        print("[api_worker] stdin JSON 解析失败：%s" % e, file=sys.stderr)
    dr = (req.get("data_root") or "").strip().strip('"')
    if dr:
        os.environ["VT_DATA_ROOT"] = os.path.abspath(dr)

    from features._api import dispatch  # noqa: PLC0415 —— 惰性
    payload = dispatch(req.get("cmd", ""), req.get("params") or {},
                       log=lambda m: print(m, file=sys.stderr))
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    if "exit_code" in payload:          # 透传三件：退出码原样保留
        return int(payload["exit_code"])
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())