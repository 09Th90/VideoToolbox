# -*- coding: utf-8 -*-
# @version 3.1.2
"""check_schema_parity —— 参数三方 parity 门禁（计划书 §4.1 / §10）。

  A  _api/spec.py ↔ agent_cli argparse 反射（8 个可反射命令，逐项：
     dest/类型/默认/choices/必填/help；全局 --json/--data-root 的 SUPPRESS 归一）
  B  _api/spec.py ↔ calib_core/cli.py 源码旗标（透传三件正向存在性 +
     calibrate 主循环反向覆盖：源码识别的旗标必须全部登记，防静默跳过）
  C  _api/spec.py ↔ features/mcp/tool_specs 生成的 inputSchema（键集/必填/枚举）

用法：tools\\python\\python.exe scripts\\dev\\check_schema_parity.py
"""
from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)

FAILS = []


def fail(msg):
    FAILS.append(msg)
    print("[DIFF]", msg)


def ok(msg):
    print("[OK]", msg)


def part_a():
    import agent_cli
    from features._api import spec
    parser = agent_cli.build_parser()
    subs = parser._subparsers._group_actions[0].choices
    type_map = {int: "integer", str: "string", None: "string"}
    n = 0
    for cs in spec.iter_commands():
        if cs.passthrough:
            continue
        sp = subs[cs.name]
        actions = {}
        for a in sp._actions:
            if a.dest in ("help", "as_json", "data_root"):
                continue
            actions[a.dest] = a
        seen = set()
        for p in cs.params:
            seen.add(p.dest)
            a = actions.get(p.dest)
            if a is None:
                fail("A %s: spec 有 %s 但 argparse 无" % (cs.name, p.dest))
                continue
            n += 1
            if p.kind == "positional" and a.option_strings:
                fail("A %s.%s: kind 不一致" % (cs.name, p.dest))
            if p.kind == "option" and not a.option_strings:
                fail("A %s.%s: kind 不一致" % (cs.name, p.dest))
            if p.choices and tuple(a.choices or ()) != tuple(p.choices):
                fail("A %s.%s: choices %s ≠ %s" % (cs.name, p.dest, a.choices, p.choices))
            if p.kind == "option":
                ad = a.default
                if ad != p.default and not (ad in (None, "") and p.default in (None, "")):
                    fail("A %s.%s: default %r ≠ %r" % (cs.name, p.dest, ad, p.default))
                at = type_map.get(a.type, "string")
                if a.__class__.__name__ == "_StoreTrueAction":
                    at = "boolean"
                if at != p.type and not (p.type == "path" and at == "string"):
                    fail("A %s.%s: type %s ≠ %s" % (cs.name, p.dest, at, p.type))
            if (a.help or "") != p.help:
                fail("A %s.%s: help 漂移\n  argparse=%r\n  spec    =%r"
                     % (cs.name, p.dest, a.help, p.help))
        for dest in actions:
            if dest not in seen:
                fail("A %s: argparse 有 %s 但 spec 未登记" % (cs.name, dest))
    ok("A spec ↔ argparse：%d 参数逐项比对" % n)


def part_b():
    from features._api import spec
    with open(os.path.join(SRC, "calib_core", "cli.py"), encoding="utf-8") as f:
        src = f.read()
    cal = spec.get_command("calibrate")
    flags = {m.flag for m in cal.mode_flags}
    opts = {p.name for p in cal.params if p.kind == "option"}
    for fl in sorted(flags | opts):
        if '"%s"' % fl not in src:
            fail("B calibrate: %s 在 calib_core/cli.py 源码不存在" % fl)
    # 反向：calibrate 主循环（process 调用前）识别的旗标必须全登记
    main_loop = src.split("内置片源")[0] if "内置片源" in src else src[:12000]
    found = set(re.findall(r'a == "(--[a-z0-9-]+)"', main_loop))
    found |= set(re.findall(r'"(--[a-z0-9-]+)"', main_loop))
    registered = flags | opts | {"--json"}
    for fl in sorted(found - registered):
        fail("B calibrate: 源码识别 %s 但 spec 未登记（静默跳过风险）" % fl)
    for cmd in ("stabilize", "audit"):
        cs = spec.get_command(cmd)
        for p in cs.params:
            if p.kind == "option" and '"%s"' % p.name not in src:
                fail("B %s: %s 在源码不存在" % (cmd, p.name))
    ok("B spec ↔ calib_core 源码：33 模式旗标 + 选项正向/反向覆盖")


def part_c():
    from features._api import spec
    from features.mcp import tool_specs
    defs = {td["cmd"]: td for td in tool_specs.tool_defs()}
    for cs in spec.iter_commands():
        if cs.name in tool_specs.EXCLUDED:
            continue
        td = defs.get(cs.name)
        if td is None:
            fail("C %s: 工具定义缺失" % cs.name)
            continue
        schema = td["input_schema"]
        props = schema["properties"]
        expect = set()
        for p in cs.params:
            expect.add("input" if (cs.passthrough and p.name == "input") else p.dest)
        if cs.passthrough:
            expect.add("extra_args")
            if cs.mode_flags:
                expect.add("mode_flag")
        if set(props) != expect:
            fail("C %s: schema 键集 %s ≠ spec %s" % (cs.name, sorted(props), sorted(expect)))
        req = set(schema.get("required", []))
        exp_req = {("input" if (cs.passthrough and p.name == "input") else p.dest)
                   for p in cs.params if p.required}
        if req != exp_req:
            fail("C %s: required %s ≠ %s" % (cs.name, req, exp_req))
        for p in cs.params:
            key = "input" if (cs.passthrough and p.name == "input") else p.dest
            if p.choices and props.get(key, {}).get("enum") != list(p.choices):
                fail("C %s.%s: enum 漂移" % (cs.name, key))
    ok("C spec ↔ MCP inputSchema：%d 工具键集/必填/枚举" % len(defs))
    # C2 —— 实际注册 schema（lowlevel 直注册；防高层签名内省把 **kwargs 建模失真）
    from features.mcp.server import tool_objects
    objs = {t.name: t for t in tool_objects()}
    for td in tool_specs.tool_defs():
        o = objs.get(td["name"])
        if o is None:
            fail("C2 %s: 未注册" % td["name"])
        elif dict(o.input_schema) != td["input_schema"]:
            fail("C2 %s: 注册 schema ≠ tool_specs（keys=%s）"
                 % (td["name"], sorted(o.input_schema.get("properties", {}))))
    ok("C2 注册 schema ↔ tool_specs：%d 工具逐字一致" % len(objs))


def main():
    part_a()
    part_b()
    part_c()
    print("\n==== parity：%s ====" % ("三方一致" if not FAILS else "%d 处漂移" % len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())