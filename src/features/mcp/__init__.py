# -*- coding: utf-8 -*-
# @version 3.1.2
"""mcp 功能包：对外 MCP Server（stdio），与 CLI 并列的一等入口。

依赖红线：本包与 mcp_server.py 禁 import CLI 入口层（agent_cli / features.*.cli），
禁出现 CLI 入口脚本路径串；业务一律经 features._api（L1）。
mcp SDK 只在 server.py / runner 启动路径惰性 import（不进 GUI 启动链）。
"""