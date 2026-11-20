# -*- coding: utf-8 -*-
# @version 3.1.4
"""tool_specs —— 从 features._api.spec（参数唯一真源）生成 MCP 工具定义。

**纯数据，不 import mcp SDK / agent_cli / features.*.cli**（SDK 类型转换在
server.py）。本轮 P1 上架 10 个业务工具；bili-submit 不上架（桌面依赖 +
外部副作用 + 非统一信封，随 P2/P3，计划书 §7/§9 风险 9）。
"""
from __future__ import annotations

from features._api import spec

TOOL_PREFIX = "vt_"
EXCLUDED = {"bili-submit"}

TITLES = {
    "status": "环境自检", "info": "媒体元信息", "download": "视频下载",
    "transcribe": "语音转录", "translate": "字幕翻译", "calibrate": "术语校准",
    "stabilize": "cue 稳定化", "audit": "漏校三扫", "compose": "字幕合成",
    "split": "视频切片",
}

#: 超时档（秒）：async 档本轮同步上限，P2 改异步任务句柄
TIMEOUT_S = {"fast": 30, "medium": 300, "async": 300}

_TYPE_MAP = {"string": "string", "integer": "integer",
             "boolean": "boolean", "path": "string"}


def _param_schema(p) -> dict:
    s = {"type": _TYPE_MAP[p.type]}
    if p.type == "path":
        s["format"] = "path"
        s["description"] = (p.help or "") + "（绝对路径或相对程序根）"
    elif p.help:
        s["description"] = p.help
    if p.choices:
        s["enum"] = list(p.choices)
    if p.kind == "option" and p.default is not None:
        s["default"] = p.default
    if p.negatable:
        s["description"] = (s.get("description", "")
                            + "（true=开启；false 对应 --no-%s）" % p.dest)
    return s


def build_schema(cs) -> dict:
    props, required = {}, []
    for p in cs.params:
        if cs.passthrough and p.name == "input":
            props["input"] = {"type": "string", "format": "path",
                              "description": p.help + "（绝对路径或相对程序根）"}
            required.append("input")
            continue
        props[p.dest] = _param_schema(p)
        if p.required:
            required.append(p.dest)
    if cs.passthrough:
        if cs.mode_flags:
            props["mode_flag"] = {
                "type": "string", "enum": [m.flag for m in cs.mode_flags],
                "description": "模式旗标（与 mode 二选一，同时给会被拒绝）"}
        props["extra_args"] = {
            "type": "array", "items": {"type": "string"}, "default": [],
            "description": "逃生舱：仅允许 spec 已登记旗标（未登记拒绝，"
                           "防 calib_core 静默跳过）；默认空"}
    schema = {"type": "object", "properties": props,
              "required": required, "additionalProperties": False}
    if cs.name == "bili-submit" and "material" in props:
        props["material"]["description"] += ("（非 --probe 时实际必填；"
                                             "依赖交互桌面 + B 站客户端登录）")
    for c in cs.constraints:
        if c.kind == "one_of":
            schema["oneOf"] = [{"required": [n]} for n in c.params]
            schema["description"] = c.note
    return schema


def tool_defs() -> list:
    defs = []
    for cs in spec.iter_commands():
        if cs.name in EXCLUDED:
            continue
        defs.append({
            "name": TOOL_PREFIX + cs.name.replace("-", "_"),
            "cmd": cs.name,
            "title": TITLES.get(cs.name, cs.name),
            "description": cs.help,
            "input_schema": build_schema(cs),
            "read_only": cs.read_only,
            "open_world": cs.open_world,
            "timeout_s": TIMEOUT_S[cs.timeout],
            "passthrough": cs.passthrough,
        })
    return defs


def _allowlist(cs) -> set:
    names = {p.name for p in cs.params if p.kind == "option"}
    names |= {m.flag for m in cs.mode_flags}
    return names


def to_params(td: dict, kwargs: dict):
    """MCP 入参 → _api params。返回 (params, error)；error 非空即拒绝。"""
    cs = spec.get_command(td["cmd"])
    if not td["passthrough"]:
        return dict(kwargs), ""
    inp = kwargs.get("input")
    if not inp:
        return {}, "缺少 input（输入字幕路径）"
    extra = []
    mode_flag = kwargs.get("mode_flag")
    mode = kwargs.get("mode")
    if mode_flag and mode:
        return {}, "mode_flag 与 mode 只能给一个"
    if mode_flag:
        if mode_flag not in {m.flag for m in cs.mode_flags}:
            return {}, "未登记的模式旗标：%s" % mode_flag
        extra.append(mode_flag)
    if mode:
        extra += ["--mode", str(mode)]
    for dest, flag in (("out", "--out"), ("report", "--report"),
                       ("kb", "--kb"), ("bi_override", "--bi-override")):
        v = kwargs.get(dest)
        if v:
            extra += [flag, str(v)]
    if kwargs.get("fix_en"):
        extra.append("--fix-en")
    if kwargs.get("loose"):
        extra.append("--loose")
    if kwargs.get("window"):
        extra += ["--window", str(int(kwargs["window"]))]
    for dest in ("drop", "merge", "split"):
        if dest in kwargs and kwargs[dest] is False:
            extra.append("--no-" + dest)
    # extra_args 白名单校验（calib_core 对未知旗标静默跳过——最危险的失败形态）
    allow = _allowlist(cs)
    ea = kwargs.get("extra_args") or []
    for tok in ea:
        if str(tok).startswith("-") and str(tok) not in allow:
            return {}, "未登记旗标被拒绝：%s（extra_args 仅允许 spec 已登记项）" % tok
        if str(tok) == "--json" and td["cmd"] == "audit":
            return {}, "audit 内层 --json 不可达（会被入口 redirect 吞掉），请用 out 报告"
    extra += [str(t) for t in ea]
    return {"input": [str(inp)], "extra": extra}, ""