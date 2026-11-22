# -*- coding: utf-8 -*-
# @version 3.2.0
"""features._api —— 命令级 API 层（L1 共享接缝，2026-11-20 三层独立改造）。

CLI（agent_cli + features/<id>/cli.py）与 MCP（mcp_server + features/mcp）
两个入口**各自只依赖本层**，互不 import（门禁 check_entry_isolation.py）。

* 下划线前缀：注册表 discover() 跳过，不是功能包、不进 status features 段。
* 零副作用：命令模块按需惰性 import；本 __init__ 不拉引擎。
* 依赖红线：禁 import CLI/MCP 入口层（features._cli / agent_cli / features.mcp /
  mcp_server）与 Qt；可 import L0 引擎（core/* / calib_core/* / video_toolbox /
  features/<id>/<impl>.py）。
* 契约：dispatch(cmd, params, log) -> 信封 dict（{"ok": …}）；
  透传三件（calibrate/stabilize/audit）信封含 exit_code，调用方原样保留退出码。
"""
from __future__ import annotations

import importlib

#: 命令名 → commands/<模块>.py（11 命令；bili-submit 模块名下划线化）
_COMMAND_MODULES = {
    "status": "status",
    "info": "info",
    "download": "download",
    "transcribe": "transcribe",
    "translate": "translate",
    "calibrate": "calibrate",
    "stabilize": "stabilize",
    "audit": "audit",
    "compose": "compose",
    "split": "split",
    "bili-submit": "bili_submit",
}


def command_names() -> tuple:
    return tuple(_COMMAND_MODULES)


def dispatch(cmd: str, params: dict | None = None, log=None) -> dict:
    """执行命令，返回信封 dict。log(msg) 收过程日志（调用方决定落 stdout/stderr）。

    未知命令/异常一律落 {"ok": False, "error": …}，绝不外抛（与 CLI 信封兜底同源）。
    """
    if log is None:
        def log(_msg):
            pass
    mod_name = _COMMAND_MODULES.get(cmd)
    if mod_name is None:
        return {"ok": False, "error": "未知命令：%s" % cmd}
    try:
        mod = importlib.import_module("features._api.commands." + mod_name)
        return mod.run(dict(params or {}), log)
    except Exception as e:  # noqa: BLE001 —— 与 agent_cli.main 兜底同口径
        return {"ok": False, "error": str(e)}