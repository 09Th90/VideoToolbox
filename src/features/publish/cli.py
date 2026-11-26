# -*- coding: utf-8 -*-
# @version 3.3.1
"""publish 子命令参数壳（L2 CLI）。编排在 features/_api/commands/publish.py。"""
from __future__ import annotations

from features._api import dispatch
from features._cli import _emit, _say, common


def cmd_publish(args) -> int:
    params = {"srt": args.srt, "video": args.video, "game": args.game,
              "streamer": args.streamer, "title_en": args.title_en, "out": args.out}
    return _emit(args, dispatch("publish", params, log=lambda m: _say(args, m)))


def setup_publish(sub) -> None:
    s = sub.add_parser("publish", parents=[common],
                       help="发布素材：从字幕生成 10 段时间轴 + 10 tag + 中文标题（投稿信息.txt）")
    s.add_argument("srt", help="字幕文件（校准产物优先）")
    s.add_argument("--video", default="", help="源视频（取时长；缺省用字幕末条时间）")
    s.add_argument("--game", default="", help="游戏名（标题【游戏名】，缺省读配置默认）")
    s.add_argument("--streamer", default="", help="主播名（标题【主播名】，缺省读配置默认）")
    s.add_argument("--title-en", default="", help="英文原始标题（缺省从视频信息.txt/文件名推断）")
    s.add_argument("--out", default="", help="素材输出目录（缺省字幕同目录 <名>_素材）")
    s.set_defaults(fn=cmd_publish)