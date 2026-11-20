# mcp 功能包（对外 MCP Server）

与 CLI 并列的一等入口：外部 MCP host（Claude Desktop / Code / Cursor / Codex /
Trae…）经 stdio 挂载，模型直接把「翻译字幕」「切片」当工具调用。

## 分层

- `feature.py`：纯清单（注册表发现，status 可见性；探针只 find_spec，不拉 SDK）
- `tool_specs.py`：从 `features/_api/spec.py`（参数唯一真源）生成工具定义，纯数据
- `runner.py`：子进程 `src/api_worker.py` 执行（stdout 隔离、独立 env、显式 out）
- `server.py`：MCPServer 装配（SDK 惰性 import）、结果映射（structuredContent +
  text + resource_link；audit 退出码 1 不置 isError）

## 硬约束

- 禁 import `agent_cli` / `features.*.cli`，禁出现 `agent_cli.py` 路径串
- mcp SDK 只在启动路径惰性 import（不进 GUI 启动链）
- 本轮 P1 上架 10 工具；`bili-submit` 随 P2/P3（桌面依赖 + 外部副作用）
- 长任务异步句柄（vt_task_*）留 P2；当前同步上限 fast 30s / medium·async 300s

## 启动

```bat
tools\python\python.exe src\mcp_server.py
```

接入配置见 `docs/MCP接入说明.md`。