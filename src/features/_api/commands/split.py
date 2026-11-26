# -*- coding: utf-8 -*-
# @version 3.3.1
"""split 命令编排（原 features/split/cli.py cmd_split，行为不变）。

与 GUI「视频处理 → 视频切片」共用 features/split/video_split.py（L0 纯标准库）；
GUI 页面编排本期不动（计划书 §11.3）。
"""
from __future__ import annotations

import os

from features._api.errors import fail
from features._api.runtime import _agent_out_dir, _engine


def run(params: dict, log) -> dict:
    import features.split.video_split as vsp  # noqa: PLC0415 —— 与 GUI 同源的纯标准库模块

    engine = _engine()
    src = os.path.abspath(params.get("file", ""))
    if not os.path.isfile(src):
        return fail("源视频不存在：%s" % src)
    points = (params.get("points") or "").strip()
    durations = (params.get("durations") or "").strip()
    if bool(points) == bool(durations):
        return fail("只给一种切分输入：--points \"00:00:00,01:00:00\" "
                    "或 --durations \"1h,1h\"（两者择一）")
    kind = "points" if points else "durations"
    spec = points or durations
    mode = params.get("mode", "auto")
    ffmpeg_path, ffprobe_path = engine.ensure_ffmpeg()
    try:
        info = vsp.probe_media(ffprobe_path, src)
        plan = vsp.plan_split(info["duration"], spec, kind)
    except vsp.SplitError as e:
        return fail(str(e))
    base = os.path.splitext(os.path.basename(src))[0]
    out_dir = os.path.abspath(params["out"]) if params.get("out") else os.path.join(
        _agent_out_dir(), base + "_split")

    def _evt(kind_, payload=None):
        if kind_ == "log" and payload is not None:
            log(payload[0] if isinstance(payload, tuple) else str(payload))

    log("[信息] 片长 %s，%d 段，模式 %s"
        % (vsp.hms(info["duration"]), len(plan["segments"]), mode))
    for w in plan.get("warnings") or []:
        log("[信息] " + w)
    try:
        result = vsp.split_video(src, plan["segments"], out_dir, mode=mode,
                                 ffmpeg=ffmpeg_path, ffprobe=ffprobe_path,
                                 on_event=_evt,
                                 verify_full=(params.get("verify", "quick") == "full"))
    except Exception as e:  # noqa: BLE001
        return fail("切片失败：%s" % e)

    payload = {
        "ok": result["ok"],
        "source": src,
        "out_dir": out_dir,
        "segments": len(result["outputs"]),
        "outputs": [{"index": o["index"], "path": o["path"], "mode": o["mode"],
                     "seconds": o["seconds"], "size": o["size"],
                     "verified": o["verified"]} for o in result["outputs"]],
        "warnings": result.get("warnings") or [],
        "failed": result.get("failed") or [],
    }
    if not result["ok"]:
        payload["error"] = result.get("error") or "切片失败"
    return payload