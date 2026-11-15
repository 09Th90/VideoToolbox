# -*- coding: utf-8 -*-
"""status 子命令：环境 / AI 配置自检（原 agent_cli.cmd_status，行为不变）。

2026-11-15 功能解耦：追加 features 可用性总览段（只增字段，向后兼容）。
"""
from __future__ import annotations

import os
import shutil
import sys

from features._cli import APP_ROOT, VERSION, _emit, _engine, common


def cmd_status(args) -> int:
    engine = _engine()
    tools = engine.TOOLS_DIR
    tools_list = sorted(os.listdir(tools)) if os.path.isdir(tools) else []

    def _has(name):
        return name if os.path.isfile(os.path.join(tools, name)) else ""

    ai = engine.ai_load_config()
    asr = {}
    try:
        asr = engine.ai_mod().asr_config(ai)
    except Exception as e:  # noqa: BLE001
        asr = {"error": str(e)[:120]}

    result = {
        "ok": True,
        "version": VERSION,
        "app_root": APP_ROOT,
        "data_root": engine.DATA_ROOT,
        "data_dir": engine.DATA_DIR,
        "python": sys.executable,
        "tools_dir": tools,
        "ffmpeg": _has("ffmpeg.exe") or shutil.which("ffmpeg") or "缺失（首次用时自动下载）",
        "ffprobe": _has("ffprobe.exe") or shutil.which("ffprobe") or "缺失",
        "yt_dlp": _has("yt-dlp.exe") or "缺失（首次用时自动下载）",
        "deno": _has("deno.exe") or "缺失（YouTube 提取需要）",
        "tools_files": tools_list[:20],
        "ai": {
            "configured": bool((ai.get("base_url") or "").strip()
                               and (ai.get("api_key") or "").strip()
                               and (ai.get("model") or "").strip()),
            "base_url": (ai.get("base_url") or "").strip(),
            "model": (ai.get("model") or "").strip(),
            "vision_model": (ai.get("vision_model") or "").strip(),
            "asr": {"mode": asr.get("mode"),
                    "base_url": asr.get("base_url"),
                    "model": asr.get("model"),
                    "ready": bool(asr.get("base_url") and asr.get("api_key"))
                    if asr.get("mode") != "local"
                    else bool(asr.get("local_model") or asr.get("local_model_dir"))},
        },
    }
    # 可选：实测 LLM 连通（会花一次真实请求）
    if getattr(args, "ping", False):
        try:
            ok, detail = engine.ai_test_connection()
        except Exception as e:  # noqa: BLE001
            ok, detail = False, str(e)[:200]
        result["ai"]["ping"] = {"ok": ok, "detail": detail}
        if not ok:
            result["ok"] = False

    # 功能可用性总览（注册表探针：find_spec 级、零副作用；只增字段）
    try:
        from features import registry  # noqa: PLC0415
        reg = registry()
        feats = []
        for st in reg.statuses():
            if st.state == "ok":
                ok, detail = reg.probe(st.id)
            else:
                ok, detail = False, st.reason
            feats.append({"id": st.id, "title": st.title,
                          "available": bool(ok), "detail": detail})
        result["features"] = feats
    except Exception as e:  # noqa: BLE001
        result["features"] = {"error": str(e)[:120]}
    return _emit(args, result)


def setup_status(sub) -> None:
    s = sub.add_parser("status", parents=[common],
                       help="环境/AI 配置自检（工具在位性、AI/ASR 槽是否已配）")
    s.add_argument("--ping", action="store_true",
                   help="实测全局 AI 连通性（发一次真实请求）")
    s.set_defaults(fn=cmd_status)