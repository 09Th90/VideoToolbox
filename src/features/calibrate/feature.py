# -*- coding: utf-8 -*-
# @version 3.1.0
"""calibrate 功能清单。三个透传子命令（calibrate/stabilize/audit）同属本功能。

双轨（2026-11-08）：运行时直连 calib_core 包；根目录 subtitle_calib_merged.py
是构建产物/同步载体，VT_CALIB_SUBPROCESS=1 时回退单文件 subprocess。
"""
from features._registry import CliCommand, FeatureSpec

FEATURE = FeatureSpec(
    id="calibrate",
    title="字幕校准",
    summary="术语校准（只改文字不动时间轴）/ cue 稳定化 / 名词漏校三扫",
    backend="calib_core",
    requires=(),
    services={"main_argv": "calib_core.cli:main_argv",
              "build_page": "features.calibrate.page:build_page"},
    cli=(
        CliCommand(name="calibrate",
                   help="字幕术语校准（透传 subtitle_calib_merged.py，只改文字不动时间轴）",
                   setup="features.calibrate.cli:setup_calibrate",
                   passthrough=True),
        CliCommand(name="stabilize",
                   help="cue 稳定化（透传 subtitle_calib_merged.py 的 stabilize 子命令）",
                   setup="features.calibrate.cli:setup_stabilize",
                   passthrough=True),
        CliCommand(name="audit",
                   help="名词漏校三扫（透传 subtitle_calib_merged.py 的 audit 子命令；"
                        "拉丁残留 / 错形残留 / 同词族一致性，退出码 1＝有候选）",
                   setup="features.calibrate.cli:setup_audit",
                   passthrough=True),
    ),
    order=60,
)