# -*- coding: utf-8 -*-
# @version 3.1.2
"""功能清单模板。复制后：id 改成与目录名一致，按需填 cli/gui/services。"""
from features._registry import CliCommand, FeatureSpec, GuiSpec

FEATURE = FeatureSpec(
    id="_template",                 # ← 必须与目录名一致
    title="模板功能",
    summary="一句话说明这个功能干什么",
    backend="",                     # 主后端模块（惰性 import；无后端留空）
    requires=(),                    # 外部依赖键：ffmpeg/ffprobe/ytdlp/asr/network/qt…
    services={                      # 对外服务：name -> "module:attr"
        # "do_something": "my_backend:do_something",
    },
    cli=(                           # 无 CLI 子命令则留空 tuple
        CliCommand(name="_template",
                   help="模板子命令（--help 里显示）",
                   setup="features._template.cli:setup_template"),
    ),
    gui=None,                       # 有 GUI 页时改成 GuiSpec(...)，见下
    # gui=GuiSpec(nav="模板页", builder="features._template.page:build_page",
    #             position="top", order=100, object_name="templatePage",
    #             messages=("tpl_",)),
    order=100,
)