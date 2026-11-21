# -*- coding: utf-8 -*-
# @version 3.1.5
"""_api.commands —— 11 命令的业务编排（从 features/<id>/cli.py 机械搬迁）。

统一契约：run(params: dict, log) -> 信封 dict。禁 import CLI/MCP 入口与 Qt。
"""