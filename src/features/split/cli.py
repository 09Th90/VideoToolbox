# -*- coding: utf-8 -*-
# @version 3.1.1
"""split 子命令（原 agent_cli.cmd_split，行为不变）。"""
from __future__ import annotations

import os

from features._cli import _agent_out_dir, _emit, _engine, _fail, _say, common


def cmd_split(args) -> int:
    """按时间点 / 时长把一条视频拆成多段，逐段校验可播放。

    `split <file> --points "00:00:00,01:00:00"` 或 `split <file> --durations "1h,1h"`。
    与 GUI「视频处理 → 视频切片」共用 src\\video_split.py，行为完全一致。
    """
    import features.split.video_split as vsp  # noqa: PLC0415 —— 与 GUI 同源的纯标准库模块

    engine = _engine()
    src = os.path.abspath(args.file)
    if not os.path.isfile(src):
        return _fail(args, "源视频不存在：%s" % src)
    points = (args.points or "").strip()
    durations = (args.durations or "").strip()
    if bool(points) == bool(durations):
        return _fail(args, "只给一种切分输入：--points \"00:00:00,01:00:00\" "
                           "或 --durations \"1h,1h\"（两者择一）")
    kind = "points" if points else "durations"
    spec = points or durations
    ffmpeg_path, ffprobe_path = engine.ensure_ffmpeg()
    try:
        info = vsp.probe_media(ffprobe_path, src)
        plan = vsp.plan_split(info["duration"], spec, kind)
    except vsp.SplitError as e:
        return _fail(args, str(e))
    base = os.path.splitext(os.path.basename(src))[0]
    out_dir = os.path.abspath(args.out) if args.out else os.path.join(
        _agent_out_dir(), base + "_split")

    def _evt(kind_, payload=None):
        if kind_ == "log" and payload is not None:
            _say(args, payload[0] if isinstance(payload, tuple) else str(payload))

    _say(args, "[信息] 片长 %s，%d 段，模式 %s"
         % (vsp.hms(info["duration"]), len(plan["segments"]), args.mode))
    for w in plan.get("warnings") or []:
        _say(args, "[信息] " + w)
    try:
        result = vsp.split_video(src, plan["segments"], out_dir, mode=args.mode,
                                 ffmpeg=ffmpeg_path, ffprobe=ffprobe_path,
                                 on_event=_evt,
                                 verify_full=(args.verify == "full"))
    except Exception as e:  # noqa: BLE001
        return _fail(args, "切片失败：%s" % e)

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
    return _emit(args, payload)


def setup_split(sub) -> None:
    s = sub.add_parser("split", parents=[common],
                       help="视频切片：按时间点（HH:MM:SS）或时长（xHyMzS）拆成多段，逐段校验可播放")
    s.add_argument("file", help="源视频")
    s.add_argument("--points", default="",
                   help="时间点列表（HH:MM:SS），如 \"00:00:00,01:00:00,02:00:00\"")
    s.add_argument("--durations", default="",
                   help="时长列表（xHyMzS），如 \"1h,1h\" / \"1h30m,30m,45s\"")
    s.add_argument("--mode", default="auto", choices=["copy", "auto", "encode"],
                   help="copy=无损快切；auto=快切校验不过就重编码（默认）；encode=精确重编码")
    s.add_argument("--out", default="",
                   help="输出目录（默认 data\\agent_out\\<时间戳>\\<名>_split）")
    s.add_argument("--verify", default="quick", choices=["quick", "full"],
                   help="逐段校验强度：quick=片头片尾抽检（默认）；full=整段全解码")
    s.set_defaults(fn=cmd_split)