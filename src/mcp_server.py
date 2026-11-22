# -*- coding: utf-8 -*-
# @version 3.2.0
"""mcp_server —— 视频工具箱 MCP stdio 入口壳（L2，与 CLI 入口同级）。

启动：tools\\python\\python.exe src\\mcp_server.py（stdio 常驻；外部 host 配置
用 argv 数组，路径含中文/空格不拼串）。本壳只做 chdir/sys.path/惰性装配；
协议与工具面在 features/mcp/server.py，业务在 features/_api（L1）。
**禁 import CLI 入口层（agent_cli / features.*.cli）**（门禁 check_entry_isolation）。
"""
from __future__ import annotations

import os
import sys

SRC = os.path.dirname(os.path.abspath(__file__))
APP_ROOT = os.path.dirname(SRC)


def main() -> None:
    os.chdir(APP_ROOT)                      # CWD 契约：学习库相对路径落程序根
    if SRC not in sys.path:
        sys.path.insert(0, SRC)
    import anyio  # noqa: PLC0415 —— SDK 依赖链惰性
    from mcp.server.models import InitializationOptions  # noqa: PLC0415
    from mcp.server.stdio import stdio_server  # noqa: PLC0415
    from features._api.runtime import API_VERSION  # noqa: PLC0415
    from features.mcp.server import build_server  # noqa: PLC0415

    async def _amain():
        server = build_server()
        async with stdio_server() as (read, write):
            await server.run(
                read, write,
                InitializationOptions(
                    server_name="video-toolbox", server_version=API_VERSION,
                    capabilities=server.get_capabilities()))

    anyio.run(_amain)


if __name__ == "__main__":
    main()