# @version 2.6.0
"""vt_engine CLI（无头冒烟与单链路执行）。

用法示例::

    python -m vt_engine info
    python -m vt_engine config
    python -m vt_engine styles
    python -m vt_engine check-llm
    python -m vt_engine transcribe 视频.mp4 --output out.srt
    python -m vt_engine subtitle 字幕.srt --video 视频.mp4

退出码：0 成功；1 失败（错误信息打到 stderr）；2 用法错误。
"""

from __future__ import annotations

import argparse
import json
import sys


def _cmd_info(_args) -> int:
    import vt_engine
    print(json.dumps(vt_engine.backend_info(), ensure_ascii=False,
                     indent=2))
    return 0


def _cmd_config(_args) -> int:
    from vt_engine.config import cfg
    print(json.dumps(cfg.dump(), ensure_ascii=False, indent=2))
    return 0


def _cmd_styles(_args) -> int:
    from vt_engine.style_manager import available_style_names
    for n in available_style_names():
        print(n)
    return 0


def _cmd_check_llm(_args) -> int:
    from vt_engine.llm_client import check_llm_connection
    ok, msg = check_llm_connection()
    print(("OK: " if ok else "FAIL: ") + str(msg))
    return 0 if ok else 1


def _cmd_transcribe(args) -> int:
    from vt_engine.pipeline import transcribe_media
    from vt_engine.tasks import TaskFactory
    task = TaskFactory.create_transcribe_task(
        args.file, need_next_task=bool(args.video))
    if args.output:
        task.output_path = args.output
    transcribe_media(task, callback=lambda p, m: print("[%3d%%] %s"
                                                       % (p, m)))
    print("DONE: %s" % task.output_path)
    return 0


def _cmd_subtitle(args) -> int:
    from vt_engine.pipeline import process_subtitle
    from vt_engine.tasks import TaskFactory
    task = TaskFactory.create_subtitle_task(
        args.file, video_path=args.video, need_next_task=bool(args.video))
    if args.output:
        task.output_path = args.output
    process_subtitle(task, callback=lambda p, m: print("[%3d%%] %s"
                                                       % (p, m)))
    print("DONE: %s" % task.output_path)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="vt_engine",
                                     description="视频工具箱自研运行引擎 CLI")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("info", help="引擎信息")
    sub.add_parser("config", help="当前设置（settings.json 实况）")
    sub.add_parser("styles", help="可用字幕样式")
    sub.add_parser("check-llm", help="测试 LLM 连接")
    p_tr = sub.add_parser("transcribe", help="转写视频/音频")
    p_tr.add_argument("file")
    p_tr.add_argument("--output", default="")
    p_tr.add_argument("--video", default="",
                      help="关联视频路径（need_next_task）")
    p_st = sub.add_parser("subtitle", help="处理字幕（断句/优化/翻译）")
    p_st.add_argument("file")
    p_st.add_argument("--output", default="")
    p_st.add_argument("--video", default="")
    args = parser.parse_args(argv)
    handlers = {
        "info": _cmd_info,
        "config": _cmd_config,
        "styles": _cmd_styles,
        "check-llm": _cmd_check_llm,
        "transcribe": _cmd_transcribe,
        "subtitle": _cmd_subtitle,
    }
    if not args.cmd:
        parser.print_help()
        return 2
    try:
        return handlers[args.cmd](args)
    except Exception as e:  # noqa: BLE001
        print("ERROR: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
