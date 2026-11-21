# -*- coding: utf-8 -*-
# @version 3.1.6
"""server —— MCP Server 装配（SDK 惰性 import；仅 mcp_server 启动路径导入本模块）。

用 lowlevel Server + 构造回调直注册 schema（**不用高层签名内省**——
SDK 2.3.0 的 MCPServer.tool 会把 **kwargs 建模成必填字段，schema 失真）。
inputSchema 完全来自 tool_specs（→ _api/spec.py 唯一真源）。

结果映射（计划书 §5）：structured_content 原样信封 + text 人读摘要（≤2KB）+
resource_link 产物；audit 退出码 1 不置 is_error（检查结果非故障）。
Server 自身日志走 stderr，stdout 只有协议帧。
"""
from __future__ import annotations

import json
import os


def tool_objects() -> list:
    """注册用 Tool 对象列表（parity 门禁也读它，校验实际发布 schema）。"""
    from mcp.types import Tool, ToolAnnotations  # noqa: PLC0415 —— SDK 惰性
    from features.mcp import tool_specs
    objs = []
    for td in tool_specs.tool_defs():
        objs.append(Tool(
            name=td["name"], title=td["title"], description=td["description"],
            input_schema=td["input_schema"],
            annotations=ToolAnnotations(read_only_hint=td["read_only"],
                                        open_world_hint=td["open_world"],
                                        destructive_hint=False)))
    return objs


def build_server():
    from mcp.server.lowlevel import Server  # noqa: PLC0415
    from mcp.types import CallToolResult, ListToolsResult, TextContent  # noqa: PLC0415
    from features._api.runtime import API_VERSION
    from features.mcp import tool_specs

    defs = tool_specs.tool_defs()
    by_name = {td["name"]: td for td in defs}

    async def _on_list(ctx, params):
        return ListToolsResult(tools=tool_objects())

    async def _on_call(ctx, params):
        td = by_name.get(params.name)
        if td is None:
            return CallToolResult(
                is_error=True,
                content=[TextContent(type="text",
                                     text="未知工具：%s" % params.name)])
        return _dispatch(td, params.arguments or {})

    return Server(
        "video-toolbox", version=API_VERSION,
        instructions="视频工具箱 MCP 服务：与 CLI 入口共用 features._api 业务层。"
                     "长任务（下载/转录/硬烧）本轮同步上限 300s，异步任务句柄见 P2。",
        on_list_tools=_on_list, on_call_tool=_on_call)


def _dispatch(td, kwargs):
    from mcp.types import CallToolResult, ResourceLink, TextContent  # noqa: PLC0415
    from features.mcp import runner, tool_specs

    params, err = tool_specs.to_params(td, kwargs)
    if err:
        return CallToolResult(is_error=True,
                              content=[TextContent(type="text", text=err)])
    payload = runner.run_command(td["cmd"], params, td["timeout_s"])
    ok = bool(payload.get("ok"))
    # audit 退出码 1＝有候选，属检查结果而非工具故障
    is_error = (not ok) and not (td["cmd"] == "audit"
                                 and payload.get("exit_code") == 1)
    content = [TextContent(type="text", text=_summary(payload))]
    for key in ("output", "video", "out_dir"):
        p = payload.get(key)
        if isinstance(p, str) and p and os.path.exists(p):
            content.append(_link(p))
    for o in (payload.get("outputs") or [])[:20]:
        p = o.get("path") if isinstance(o, dict) else None
        if p and os.path.exists(p):
            content.append(_link(p))
    return CallToolResult(structured_content=payload, content=content,
                          is_error=is_error)


def _link(path):
    from mcp.types import ResourceLink  # noqa: PLC0415
    return ResourceLink(type="resource_link",
                        uri="file:///" + path.replace("\\", "/"),
                        name=os.path.basename(path))


def _summary(payload):
    lines = ["ok: %s" % payload.get("ok")]
    for k, v in payload.items():
        if k in ("ok", "outputs", "stdout"):
            continue
        if isinstance(v, (dict, list)):
            v = json.dumps(v, ensure_ascii=False)
        lines.append("%s: %s" % (k, v))
    return "\n".join(lines)[:2000]