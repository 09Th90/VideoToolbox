# -*- coding: utf-8 -*-
# @version 3.1.4
"""bili-submit 子命令参数壳（L2 CLI）。编排在 features/_api/commands/bili_submit.py。

内层非统一信封：_api 以 stream=True Tee 直写 stdout（内容与流式时序不变），
退出码原样保留；异常经 dispatch 兜底落标准错误信封。
"""
from __future__ import annotations

from features._api import dispatch
from features._cli import _fail, common


def cmd_bili_submit(args):
    params = {"material": getattr(args, "material", ""),
              "probe": getattr(args, "probe", False),
              "dry_run": getattr(args, "dry_run", False),
              "edit": getattr(args, "edit", False),
              "only": getattr(args, "only", ""),
              "visibility": getattr(args, "visibility", ""),
              "topic": getattr(args, "topic", ""),
              "cover": getattr(args, "cover", ""),
              "subtitle": getattr(args, "subtitle", ""),
              "as_json": getattr(args, "as_json", False),
              "stream": True}
    payload = dispatch("bili-submit", params)
    if "exit_code" not in payload:
        return _fail(args, payload.get("error", "投稿失败"))
    return payload["exit_code"]


def setup_bili_submit(sub) -> None:
    s = sub.add_parser("bili-submit", parents=[common],
                       help="B 站后台自动投稿（UI Automation 定位 + 后台输入；素材目录内含投稿信息.txt）")
    s.add_argument("material", nargs="?", default="", help="素材目录")
    s.add_argument("--probe", action="store_true", help="只输出当前页面 UIA 结构")
    s.add_argument("--dry-run", action="store_true", help="填完但不点立即投稿")
    s.add_argument("--edit", action="store_true", help="修复当前编辑页（不新上传视频）")
    s.add_argument("--only", default="", help="只跑阶段：basic,chapters,cover,topic,subtitle,visibility")
    s.add_argument("--visibility", choices=["self", "public"], default="self",
                   help="可见范围（默认 self=仅自己可见）")
    s.add_argument("--topic", default="", help="覆盖参与话题")
    s.add_argument("--cover", default="", help="覆盖封面图片")
    s.add_argument("--subtitle", default="", help="覆盖 SRT 字幕")
    s.set_defaults(fn=cmd_bili_submit)