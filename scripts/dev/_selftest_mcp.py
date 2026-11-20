# -*- coding: utf-8 -*-
# @version 3.1.4
"""_selftest_mcp —— MCP Server 端到端自检（SDK client 起 stdio 子进程）。

  1  initialize 握手：serverInfo.name = video-toolbox
  2  tools/list：10 个 vt_ 前缀工具，inputSchema 合法
  3  vt_status 实跑：structuredContent.ok True
  4  vt_info 实跑：n_cues 正确
  5  vt_audit：exit_code 1 时 isError False（检查结果非故障）
  6  vt_calibrate：只增字段 changes/mode_name 到达 MCP 层
  7  未登记旗标拒绝（extra_args 白名单）
  8  mode_flag 与 mode 同给拒绝

用法：tools\\python\\python.exe scripts\\dev\\_selftest_mcp.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(ROOT, "src")
PY = os.path.join(ROOT, "tools", "python", "python.exe")
FIX = os.path.join(ROOT, "data", "tmp", "api_selftest_fix")

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("%s %s%s" % ("[OK]" if ok else "[FAIL]", name,
                       (" —— " + detail) if detail else ""))


async def _run():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    os.makedirs(FIX, exist_ok=True)
    srt = os.path.join(FIX, "sample.srt")
    if not os.path.isfile(srt):
        with open(srt, "w", encoding="utf-8", newline="\n") as f:
            f.write("1\n00:00:01,000 --> 00:00:03,000\n"
                    "Welcome to Endfield.\n欢迎来到恩德菲尔德。\n\n"
                    "2\n00:00:04,000 --> 00:00:06,000\n"
                    "Endfield awaits.\n终末地等着你。\n\n")
    kb = os.path.join(FIX, "kb.json")
    root_kb = os.path.join(ROOT, "subtitle_learned_kb.json")
    if not os.path.isfile(kb):
        import shutil
        if os.path.isfile(root_kb):
            shutil.copyfile(root_kb, kb)
        else:
            with open(kb, "w", encoding="utf-8") as f:
                f.write("{}")

    params = StdioServerParameters(
        command=PY, args=[os.path.join(SRC, "mcp_server.py")],
        cwd=ROOT, env=dict(os.environ, PYTHONUTF8="1"))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            check("initialize 握手",
                  init.server_info.name == "video-toolbox",
                  init.server_info.name)

            tools = await session.list_tools()
            names = sorted(t.name for t in tools.tools)
            check("tools/list 10 工具 vt_ 前缀",
                  len(names) == 10 and all(n.startswith("vt_") for n in names)
                  and "vt_bili_submit" not in names, str(names))
            check("inputSchema 合法",
                  all(t.input_schema.get("type") == "object"
                      and "properties" in t.input_schema for t in tools.tools))

            r = await session.call_tool("vt_status", {})
            sc = r.structured_content or {}
            check("vt_status 实跑", sc.get("ok") is True and not r.is_error,
                  str(sc)[:100])

            r = await session.call_tool("vt_info", {"file": srt})
            sc = r.structured_content or {}
            check("vt_info 实跑", sc.get("n_cues") == 2 and not r.is_error,
                  str(sc)[:100])

            r = await session.call_tool("vt_audit", {
                "input": srt, "mode": "bi",
                "out": os.path.join(FIX, "mcp_audit.md"), "kb": kb})
            sc = r.structured_content or {}
            check("vt_audit exit1 不置 isError",
                  sc.get("exit_code") in (0, 1) and not r.is_error
                  and isinstance(sc.get("candidates"), int),
                  "exit=%s isError=%s" % (sc.get("exit_code"), r.is_error))

            out = os.path.join(FIX, "mcp_cal.srt")
            rep = os.path.join(FIX, "mcp_cal.tsv")
            r = await session.call_tool("vt_calibrate", {
                "input": srt, "mode_flag": "--endobi",
                "out": out, "report": rep, "kb": kb})
            sc = r.structured_content or {}
            check("vt_calibrate 实跑 + 只增字段",
                  sc.get("exit_code") == 0 and os.path.isfile(out)
                  and sc.get("mode_name") == "endobi"
                  and isinstance(sc.get("changes"), int),
                  str(sc)[:160])

            r = await session.call_tool("vt_calibrate", {
                "input": srt, "extra_args": ["--bogus-flag"]})
            txt = " ".join(c.text for c in r.content if hasattr(c, "text"))
            check("未登记旗标拒绝", r.is_error and "未登记" in txt, txt[:100])

            r = await session.call_tool("vt_calibrate", {
                "input": srt, "mode_flag": "--endobi", "mode": "bi"})
            txt = " ".join(c.text for c in r.content if hasattr(c, "text"))
            check("mode_flag/mode 同给拒绝", r.is_error and "只能给一个" in txt,
                  txt[:100])


def main():
    import anyio
    try:
        anyio.run(_run)
    except Exception as e:  # noqa: BLE001
        check("MCP 会话异常", False, "%s: %s" % (type(e).__name__, e))
    print("\n==== 结果：%d 通过 / %d 失败 ====" % (len(PASS), len(FAIL)))
    for f in FAIL:
        print("  FAIL:", f)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())