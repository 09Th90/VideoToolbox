# -*- coding: utf-8 -*-
# @version 3.2.0
"""check_entry_isolation —— 三层入口文件独立性门禁（计划书 §3.0 四条硬规则）。

AST 扫 import + 文本扫路径字面量，命中即非零退出（挂打包前检查/CI）：
  R1  features/mcp/** + src/mcp_server.py：禁 import agent_cli / features.*.cli /
      features._cli；禁出现 "agent_cli.py" 路径串
  R2  features/*/cli.py + agent_cli.py + features/_cli.py：禁 import mcp /
      mcp_server / features.mcp
  R3  features/_api/** + src/api_worker.py：禁 import CLI/MCP 入口层；禁 Qt
  R4  L0 纯度：core/** + calib_core/** + video_toolbox.py + features/<id>/<impl>.py
      禁 import features._api / features.mcp / agent_cli / mcp_server
      （pipeline.py 是 L2 编排消费者，白名单允许 import features._api）

用法：tools\\python\\python.exe scripts\\dev\\check_entry_isolation.py
"""
from __future__ import annotations

import ast
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(ROOT, "src")

# GBK 控制台兜底（与 check_schema_parity 同款，防显示编码崩溃）
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

QT_ROOTS = {"PySide6", "PyQt5", "PyQt6", "qfluentwidgets", "vt_fluent"}
CLI_MODS = {"agent_cli", "features._cli"}
MCP_MODS = {"mcp", "mcp_server", "features.mcp"}


def _imports(path):
    """全部 import 模块名（含函数体内惰性）。"""
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), path)
    mods = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods.append(node.module)
    return mods


def _is_cli(m):
    return m in CLI_MODS or (m.startswith("features.") and m.endswith(".cli"))


def _is_mcp(m):
    return m.split(".")[0] in {"mcp", "mcp_server"} or m.startswith("features.mcp")


def _pyfiles(*dirs):
    for d in dirs:
        if os.path.isfile(d) and d.endswith(".py"):
            yield d
            continue
        for dp, _dn, fns in os.walk(d):
            if "__pycache__" in dp:
                continue
            for fn in fns:
                if fn.endswith(".py"):
                    yield os.path.join(dp, fn)


def main():
    bad = []
    feat = os.path.join(SRC, "features")

    # R1 —— MCP 侧
    for p in list(_pyfiles(os.path.join(feat, "mcp"))) + [os.path.join(SRC, "mcp_server.py")]:
        for m in _imports(p):
            if _is_cli(m):
                bad.append("R1 %s import %s" % (os.path.relpath(p, ROOT), m))
        with open(p, encoding="utf-8") as f:
            if "agent_cli.py" in f.read():
                bad.append("R1 %s 含 agent_cli.py 路径串" % os.path.relpath(p, ROOT))

    # R2 —— CLI 侧
    cli_files = [os.path.join(SRC, "agent_cli.py"), os.path.join(feat, "_cli.py")]
    cli_files += [os.path.join(feat, d, "cli.py") for d in sorted(os.listdir(feat))
                  if os.path.isfile(os.path.join(feat, d, "cli.py"))]
    for p in cli_files:
        for m in _imports(p):
            if _is_mcp(m):
                bad.append("R2 %s import %s" % (os.path.relpath(p, ROOT), m))

    # R3 —— API 侧
    for p in list(_pyfiles(os.path.join(feat, "_api"))) + [os.path.join(SRC, "api_worker.py")]:
        for m in _imports(p):
            if _is_cli(m) or _is_mcp(m):
                bad.append("R3 %s import %s" % (os.path.relpath(p, ROOT), m))
            if m.split(".")[0] in QT_ROOTS:
                bad.append("R3 %s import Qt(%s)" % (os.path.relpath(p, ROOT), m))

    # R4 —— L0 纯度（pipeline.py 白名单：L2 编排消费者）
    l0 = list(_pyfiles(os.path.join(SRC, "core"), os.path.join(SRC, "calib_core")))
    l0.append(os.path.join(SRC, "video_toolbox.py"))
    for d in sorted(os.listdir(feat)):
        sub = os.path.join(feat, d)
        if not os.path.isdir(sub) or d.startswith("_") or d == "mcp":
            continue
        for fn in os.listdir(sub):
            if fn.endswith(".py") and fn not in ("cli.py", "page.py", "feature.py", "__init__.py"):
                if d == "pipeline" and fn == "pipeline.py":
                    continue        # 白名单：允许 import features._api
                l0.append(os.path.join(sub, fn))
    for p in l0:
        for m in _imports(p):
            if m.startswith("features._api") or _is_mcp(m) or m == "agent_cli":
                bad.append("R4 %s import %s" % (os.path.relpath(p, ROOT), m))

    if bad:
        print("入口独立性门禁 FAIL（%d）：" % len(bad))
        for b in bad:
            print("  -", b)
        return 1
    print("入口独立性门禁 PASS（R1 MCP / R2 CLI / R3 API / R4 L0 纯度）")
    return 0


if __name__ == "__main__":
    sys.exit(main())