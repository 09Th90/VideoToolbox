<!-- @version 3.1.5 -->
# 视频工具箱 · MCP 接入说明

> 2026-11-20 三层独立改造（P0+P0.5+P1）交付。CLI（`agent_cli`）与 MCP
> （`mcp_server`）是同一套 **API 层**（`src\features\_api`）的两个原生入口，
> 文件上互不 import（门禁 `scripts\dev\check_entry_isolation.py` 防回退）。

## 一、前提

- 源码 + 内置 Python 在位（安装包已带 `src\` 与 `tools\python\`）。
- MCP SDK（**仅外部客户端需要**，GUI/CLI 运行不依赖）：

```bat
tools\python\python.exe -m pip install mcp==2.3.0
```

安装版若缺 SDK，按上式补装即可（`tools\python` 随包分发，pip 在位）。

## 二、启动

```bat
tools\python\python.exe src\mcp_server.py
```

stdio 常驻；**必须用内置 Python 启动**（GUI 主 exe 是窗口态冻结体，无 stdio，
不能当 server）。Server 自动 chdir 程序根（学习库相对路径契约）。

## 三、host 配置（argv 数组，中文/空格路径不拼串）

### Claude Desktop（`claude_desktop_config.json`）

```json
{
  "mcpServers": {
    "video-toolbox": {
      "command": "D:\\Agent Work\\软件开发\\视频工具箱\\tools\\python\\python.exe",
      "args": ["D:\\Agent Work\\软件开发\\视频工具箱\\src\\mcp_server.py"],
      "cwd": "D:\\Agent Work\\软件开发\\视频工具箱"
    }
  }
}
```

### Claude Code（项目根 `.mcp.json`）

```json
{
  "mcpServers": {
    "video-toolbox": {
      "type": "stdio",
      "command": "D:\\Agent Work\\软件开发\\视频工具箱\\tools\\python\\python.exe",
      "args": ["D:\\Agent Work\\软件开发\\视频工具箱\\src\\mcp_server.py"],
      "cwd": "D:\\Agent Work\\软件开发\\视频工具箱"
    }
  }
}
```

### Cursor（`.cursor/mcp.json`）/ 其它 host

同构：`command` + `args` 数组 + `cwd`。安装版把路径换成 `{app}`
（如 `D:\VideoToolbox\tools\python\python.exe`）。部分 host 会给工具加
`mcp__video-toolbox__` 前缀，那是 host 行为；服务端原始名稳定。

## 四、工具面（10 个，全 `vt_` 前缀）

| 工具 | 对应 CLI | 超时档 | 备注 |
|---|---|---|---|
| `vt_status` | status | 30s | 只读；`ping=true` 会发一次真实 LLM 请求 |
| `vt_info` | info | 30s | 只读；媒体/字幕摘要 |
| `vt_translate` | translate | 300s | engine 默认 bing（google 本机不可用） |
| `vt_calibrate` | calibrate | 300s | `mode_flag`（33 枚举）与 `mode` 二选一；不给 out 只统计 |
| `vt_stabilize` | stabilize | 300s | drop/merge/split 默认 true |
| `vt_audit` | audit | 300s | 只读；**退出码 1＝有候选，不置 isError** |
| `vt_compose` | compose | 300s | soft 同步；burn/mkv 重编码可能触顶（P2 异步） |
| `vt_split` | split | 300s | points/durations 恰好给一个（schema oneOf） |
| `vt_transcribe` | transcribe | 300s | 长视频可能触顶（P2 异步） |
| `vt_download` | download | 300s | 同上 |

- 结果：`structuredContent`（原样 JSON 信封）+ 文本摘要 + `resource_link` 产物。
- 透传三件支持 `extra_args` 逃生舱，但**未登记旗标直接拒绝**（calib_core 对
  未知旗标静默跳过，是最危险的失败形态；白名单以 `_api\spec.py` 为准）。
- `vt_bili_submit` 本轮不上架（交互桌面 + B 站登录态依赖 + 真实外部副作用），
  随 P2/P3；需要时走 CLI `bili-submit`。

## 五、排障

| 症状 | 原因/处置 |
|---|---|
| host 报连接失败/立即退出 | 缺 SDK：按 §一 补装；或 command 路径错（必须内置 Python） |
| 工具列表只有 `kwargs` 字段 | 旧版高层装配缺陷，已改 lowlevel 直注册；确认代码在 637a035 之后 |
| 中文路径起不来 | 配置必须 argv 数组 + `cwd`，不要拼命令行字符串 |
| 长任务返回超时 | 本轮同步上限 300s；下载/转录/硬烧异步句柄见 P2 规划 |
| 校准「成功但没效果」 | 旗标拼错被白名单拒绝（看 isError 文本）；或 calibrate 未给 out（只统计） |
| 学习库落错目录 | cwd 必须是程序根（配置里显式给） |

## 六、打包前门禁（不过不出包）

```bat
tools\python\python.exe scripts\dev\check_entry_isolation.py
tools\python\python.exe scripts\dev\check_schema_parity.py
tools\python\python.exe scripts\dev\_selftest_api.py
tools\python\python.exe scripts\dev\_selftest_mcp.py
tools\python\python.exe scripts\dev\_cli_golden.py
```

## 七、边界（本期明确不做）

HTTP/SSE 传输与远程鉴权（P5+）；异步任务句柄 vt_task_*（P2）；resources/
progressToken/工具级开关（P3）；GUI 页面编排收敛到 _api（后续可选）。
详见 `docs\MCP兼容改造计划_2026-11-20.md`。