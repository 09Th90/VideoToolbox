# -*- coding: utf-8 -*-
# @version 3.2.0
"""agent_cli —— 视频工具箱「第三方 Agent 接入」统一命令行入口（v1.0.0）。

定位与边界
----------
把工具箱核心能力封装成**无 Qt 依赖**的稳定 CLI，供任意第三方 AI agent
（Claude Code / Trae / Codex …）把工具箱当成一个 "skill" 直接调用。
技能说明书在程序根目录 ``SKILL.md``（与本文件的 ``--help`` 内容同源）；
现有「AI 托管」（harness 方向）与本 CLI 互不影响，两者共存。

2026-11-15 功能解耦
-------------------
子命令的声明与实现已迁到 ``src/features/<功能>/cli.py``（每个功能独立成包），
本文件收为**注册表驱动的薄壳**：build_parser 按注册表装配子命令，main 统一
把功能异常转成 JSON 错误信封（缺依赖不再裸 traceback）。命令名 / 旗标 /
退出码 / --json 契约完全不变；旧符号保留兼容再导出。新增子命令 = 新增功能包，
无需改本文件（见 features/_template/README.md）。

运行方式（与 SKILL.md 一致）::

    tools\\python\\python.exe src\\agent_cli.py <子命令> [参数]
    tools\\python\\python.exe src\\agent_cli.py <子命令> --help

全局约定
--------
* ``--json``          结构化输出（stdout 只落一个 JSON 对象；过程日志走 stderr）
* ``--data-root <D>`` 数据根目录（import 引擎**之前**设 ``VT_DATA_ROOT``；
  引擎侧优先级：环境变量 > data_dir.txt 指针 > 程序根，见
  ``video_toolbox._resolve_data_root``）
* AI 参数一律读 ``data\\ai_config.json``（设置页唯一落点），本 CLI 不设
  密钥参数，避免密钥泄进 shell history。
* 产物默认落 ``<数据根>\\data\\agent_out\\<时间戳>\\``，各子命令 ``--out`` 可覆盖。
* 退出码：0 成功；1 失败；``calibrate`` / ``stabilize`` / ``audit`` 原样保留
  校准退出码（length 子命令用退出码当门禁）。

子命令与引擎复用点（都已验证无 Qt 可调）
----------------------------------------
* status      环境/AI 配置自检（engine 常量 + ``ai_load_config``，--ping 实测连通）
* info        媒体元信息（ffprobe JSON）与字幕摘要（``ASRData.from_subtitle_file``）
* download    yt-dlp 原语：``ensure_ytdlp`` / ``ensure_ffmpeg`` / ``fetch_info_json``
              / ``ytdlp_proxy_args`` / ``ytdlp_cookie_args`` / ``output_template``
* transcribe  ``apply_asr_to_engine`` 同步 ASR 槽 → ``engine_asr.set_ffmpeg``
              → ``engine_asr.transcribe``（视频先用 ffmpeg 抽 m4a）
* translate   ``engine_translate.make_translator``（bing/google/deeplx 免认证端点）
* calibrate   同进程直连 ``calib_core.cli.main_argv``（术语/规则校准，参数表与
              根脚本完全同源；``VT_CALIB_SUBPROCESS=1`` 或导入失败时回退
              subprocess 透传根目录 ``subtitle_calib_merged.py``；cwd=程序根，
              学习库落根目录）
* stabilize   同上（calib_core 内建子命令）
* audit       同上 ``audit`` 子命令——**校准完成后的收口体检**：
               扫 1 拉丁残留（白名单外的英文/罗马字）、扫 2 知识库错形残留
               （变体/条件错形命中中文行而官方名不在该行）、
               扫 3 同词族一致性（参考行命中锚点而中文行缺官方名）。
               退出码 1＝有候选，可直接当 CI 门禁。
* compose     软封装走 ``subtitle_compose_core.build_command``（纯函数无 Qt）；
              硬烧录/带独立音轨走 ``video_toolbox.merge_pair``
* split       视频切片（``features.split.video_split``：时间点/时长拆分，逐段校验）
* bili-submit B 站后台自动投稿（``features.automation.bili_auto_submit``：UIA + PostMessage）
"""
from __future__ import annotations

import argparse
import sys

from features import registry as _registry_fn, resolve
from features._cli import (APP_ROOT, VERSION, _agent_out_dir, _apply_data_root,
                           _data_root, _emit, _engine, _fail, _human_lines,
                           _mod, _say, common)
from features.calibrate.cli import (CALIB_MODE_FLAGS, CALIB_SCRIPT,
                                    cmd_audit, cmd_calibrate, cmd_stabilize)
from features.status.cli import cmd_status
from features.info.cli import cmd_info
from features.download.cli import cmd_download
from features.transcribe.cli import cmd_transcribe
from features.translate.cli import cmd_translate
from features.compose.cli import cmd_compose
from features.split.cli import cmd_split
from features.automation.cli import cmd_bili_submit

# 兼容再导出：全仓无 Python 代码 import 本模块符号（只有 subprocess 路径引用），
# 此面纯防御——外部脚本若按旧名取符号仍可用。
__all__ = ["APP_ROOT", "VERSION", "CALIB_SCRIPT", "CALIB_MODE_FLAGS",
           "build_parser", "main",
           "cmd_status", "cmd_info", "cmd_download", "cmd_transcribe",
           "cmd_translate", "cmd_calibrate", "cmd_stabilize", "cmd_audit",
           "cmd_compose", "cmd_split", "cmd_bili_submit"]


# ============================================================
# argparse 装配（注册表驱动）
# ============================================================
def build_parser() -> argparse.ArgumentParser:
    epilog = "\n".join([
        "示例：",
        "  %(prog)s status --ping",
        "  %(prog)s status --json",
        "  %(prog)s info D:\\media\\ep01.mp4",
        "  %(prog)s download \"https://www.youtube.com/watch?v=xxx\" --height 1080",
        "  %(prog)s transcribe ep01.mp4 --lang ja --out data\\agent_out\\ep01.srt",
        "  %(prog)s translate ep01.srt --to zh-Hans --engine bing",
        "  %(prog)s calibrate ep01.srt --ja --out ep01_calib.srt --report ep01_r.tsv",
        "  %(prog)s stabilize ep01.srt",
        "  %(prog)s compose ep01.mp4 ep01_calib.srt --out ep01_final.mp4",
        "  %(prog)s compose ep01.mp4 ep01.ass --audio ep01.m4a --out ep01_final.mp4",
        "  %(prog)s split ep01.mp4 --points \"00:00:00,01:00:00\"",
        "  %(prog)s split ep01.mp4 --durations \"1h,1h\" --mode copy --verify full",
        "技能说明书：程序根目录 SKILL.md（与本帮助同源）。",
    ])
    p = argparse.ArgumentParser(
        prog="agent_cli",
        description="视频工具箱「第三方 Agent 接入」统一 CLI（无 GUI 依赖；"
                    "AI 模型/密钥/接口地址读 data\\ai_config.json，"
                    "由工具箱「设置」页配置）。")
    p.add_argument("--json", dest="as_json", action="store_true",
                   help="结构化输出（stdout 只落一个 JSON；日志走 stderr）")
    p.add_argument("--data-root", default="",
                   help="数据根目录（默认：VT_DATA_ROOT > data_dir.txt > 程序根）")
    p.add_argument("--version", action="version",
                   version="agent_cli %s" % VERSION)
    sub = p.add_subparsers(dest="cmd", required=True, metavar="<子命令>")

    # 各功能包自带 setup(sub)：add_parser + 参数 + set_defaults(fn=handler)。
    # 功能缺失/损坏时注册表已隔离，这里只装配可用功能的子命令。
    for _fid, cmd in _registry_fn().cli_commands():
        resolve(cmd.setup)(sub)

    # epilog 里的反斜杠路径保持原样
    for a in (p, *[a for a in sub.choices.values()]):
        a.formatter_class = argparse.RawDescriptionHelpFormatter
    p.epilog = epilog
    return p


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # calibrate / stabilize / audit 的透传参数可能与 argparse 冲突（如 --out 本 CLI 不认）：
    # 先把「这些子命令之后的所有参数」原样截下，只解析全局项与子命令名。
    passthrough_names = tuple(_registry_fn().passthrough_names())
    passthrough = None
    for i, a in enumerate(argv):
        if a in passthrough_names:
            passthrough = argv[i + 1:]
            argv = argv[:i + 1]
            break
    # ``calibrate --help`` 是要帮助、不是透传参数：交还 argparse 打印子命令帮助
    if passthrough is not None and passthrough and passthrough[0] in ("--help", "-h"):
        build_parser().parse_args(argv + ["--help"])
    parser = build_parser()
    args = parser.parse_args(argv)
    if passthrough is not None:
        # 透传段里剔除全局项（--json / --data-root 允许出现在末尾）
        rest = []
        it = iter(passthrough)
        for a in it:
            if a == "--json":
                args.as_json = True
            elif a == "--data-root":
                args.data_root = next(it, "")
            else:
                rest.append(a)
        # 透传段第一个非旗标参数 = 输入字幕（含其参数值，如 --out x.srt 里的 x.srt
        # 已由透传脚本自行消费；这里只切出"第一个位置参数"）
        args.input = []
        args.extra = list(rest)
        for i, a in enumerate(args.extra):
            if not a.startswith("-"):
                args.input = [a]
                args.extra = args.extra[:i] + args.extra[i + 1:]
                break
    _apply_data_root(args)
    try:
        return args.fn(args)
    except KeyboardInterrupt:
        print("[中断] 用户取消", file=sys.stderr)
        return 130
    except Exception as e:  # noqa: BLE001
        # 降级加固（2026-11-15）：功能异常（ensure_* 缺依赖、后端损坏等）
        # 一律落 JSON 错误信封 / 人读错误行，不再裸 traceback 崩 CLI。
        return _fail(args, str(e) or type(e).__name__)


if __name__ == "__main__":
    sys.exit(main())