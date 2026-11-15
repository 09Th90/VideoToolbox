# -*- coding: utf-8 -*-
"""bili-submit 子命令（原 agent_cli.cmd_bili_submit，行为不变）。"""
from __future__ import annotations

from features._cli import common


def cmd_bili_submit(args):
    """B 站后台自动投稿（透传 bili_auto_submit：UIA 定位 + PostMessage 输入）。"""
    import features.automation.bili_auto_submit as bas
    argv = []
    material = getattr(args, "material", "")
    if material:
        argv.append(material)
    for flag in ("probe", "dry_run", "edit"):
        if getattr(args, flag, False):
            argv.append("--" + flag.replace("_", "-"))
    for name in ("only", "visibility", "topic", "cover", "subtitle"):
        val = getattr(args, name, "")
        if val:
            argv += ["--" + name, str(val)]
    if getattr(args, "as_json", False):
        argv.append("--json")
    return bas.main(argv)


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