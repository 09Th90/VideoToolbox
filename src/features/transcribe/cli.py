# -*- coding: utf-8 -*-
# @version 3.1.2
"""transcribe 子命令（原 agent_cli.cmd_transcribe，行为不变）。"""
from __future__ import annotations

import os
import subprocess

from features._cli import (_agent_out_dir, _emit, _engine, _fail, _mod, _say,
                           common)


def cmd_transcribe(args) -> int:
    engine = _engine()
    src = os.path.abspath(args.file)
    if not os.path.isfile(src):
        return _fail(args, "文件不存在：%s" % src)

    # 引擎路径/配置重定向必须早于 videocaptioner 读盘：否则 cfg 会读
    # AppData 默认 settings，转录模型回落成 BIJIAN（与设置页不一致）。
    try:
        engine.prepare_runtime_env()
    except Exception:  # noqa: BLE001 - 环境准备失败仍按原报错暴露
        pass

    # ① 同步「设置」页 ASR 配置进引擎 settings（与 GUI「保存并应用」同款）
    # ASR 协议分发补丁（2026-10-20 起不在 prepare_runtime_env 里装）
    try:
        from core.asr.patches import vc_asr_protocol_patch
        vc_asr_protocol_patch()
    except Exception:  # noqa: BLE001
        pass
    ok, detail = engine.apply_asr_to_engine()
    if not ok:
        return _fail(args, "ASR 配置未就绪：%s（请先在「设置 → ASR 语音识别」配置）"
                     % detail)

    # ② 视频先抽音频（engine_asr 只吃 flac/m4a/mp3/wav）
    ffmpeg_path, _ = engine.ensure_ffmpeg()
    ext = os.path.splitext(src)[1].lower().lstrip(".")
    if ext in ("flac", "m4a", "mp3", "wav"):
        audio_path = src
    else:
        out_dir = os.path.abspath(args.out) if args.out else _agent_out_dir()
        out_path = out_dir if out_dir.lower().endswith(".srt") else \
            os.path.join(out_dir, os.path.splitext(os.path.basename(src))[0] + ".srt")
        audio_path = os.path.splitext(out_path)[0] + ".tmpaudio.m4a"
        _say(args, "[1/3] 抽取音频 → %s" % audio_path)
        proc = subprocess.run(
            [ffmpeg_path, "-y", "-nostdin", "-i", src, "-vn",
             "-c:a", "aac", "-b:a", "192k", audio_path],
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if proc.returncode != 0 or not os.path.isfile(audio_path):
            tail = proc.stderr.decode("utf-8", "replace").strip().splitlines()[-6:]
            return _fail(args, "抽取音频失败：\n" + "\n".join(tail))

    # ③ 构造转录配置：以引擎 settings 为底，CLI --lang 可覆盖
    from engine_task_factory import TaskFactory  # noqa: PLC0415
    task = TaskFactory.create_transcribe_task(src, need_next_task=False)
    config = task.transcribe_config
    if args.lang:
        code = _lang_code(args.lang)
        if code is None:
            return _fail(args, "无法识别的语言：%r（可用 ISO 码或引擎标签，"
                               "如 ja / en / zh / 日本語 / 英语）" % args.lang)
        config.transcribe_language = code
        _say(args, "[信息] 识别语言：%s" % (code or "自动检测"))

    # ④ 转录
    engine_asr = _mod("features.transcribe.engine_asr")
    engine_asr.set_ffmpeg(ffmpeg_path)
    out_dir = os.path.abspath(args.out) if args.out else _agent_out_dir()
    out_path = out_dir if out_dir.lower().endswith(".srt") else \
        os.path.join(out_dir, os.path.splitext(os.path.basename(src))[0] + ".srt")
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    _say(args, "[2/3] 开始转录（模型：%s）…" % config.transcribe_model)

    def _cb(pct, msg):
        _say(args, "[%3d%%] %s" % (pct, msg))

    try:
        asr_data = engine_asr.transcribe(audio_path, config, callback=_cb)
    except Exception as e:  # noqa: BLE001
        return _fail(args, "转录失败：%s" % e)
    asr_data.save(out_path)
    if audio_path != src:
        try:
            os.remove(audio_path)
        except OSError:
            pass
    _say(args, "[3/3] 转录完成")
    return _emit(args, {"ok": True, "source": src, "output": out_path,
                        "language": config.transcribe_language or "自动检测"})


def _lang_code(v: str):
    """语言参数 → 引擎识别语言的 ISO 码（也接受引擎标签）。"""
    from engine_entities import LANGUAGES  # noqa: PLC0415
    v = (v or "").strip()
    if not v or v in ("auto", "自动检测"):
        return ""
    if v in LANGUAGES.values():      # 已是 ISO 码
        return v
    if v in LANGUAGES:               # 引擎标签
        return LANGUAGES[v]
    alias = {"zh": "zh-Hans", "zt": "zh-Hant", "jp": "ja", "kr": "ko", "ko": "ko"}
    code = alias.get(v.lower())
    return code if code and code in LANGUAGES.values() else None


def setup_transcribe(sub) -> None:
    s = sub.add_parser("transcribe", parents=[common],
                       help="ASR 转录出 SRT（模型/密钥读设置页 ASR 槽）")
    s.add_argument("file", help="视频或音频文件")
    s.add_argument("--lang", default="", help="识别语言：ISO 码或引擎标签（ja/en/zh/日本語…；空=自动检测）")
    s.add_argument("--out", default="", help="输出 .srt 或目录（默认 data\\agent_out\\<时间戳>\\）")
    s.set_defaults(fn=cmd_transcribe)