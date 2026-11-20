# -*- coding: utf-8 -*-
# @version 3.1.4
"""_api.spec —— 11 命令参数的**唯一真源**（纯数据，2026-11-20 三层独立）。

MCP inputSchema 从本模块生成；CLI argparse 是受 check_schema_parity.py
约束的镜像（过渡期双份定义，parity 强制等价；后续可选改为生成式）。

禁 import argparse / agent_cli / features.*.cli / features.mcp / Qt。
数据以 2026-11-20 实测为准（计划书「33 参数」有误，实为 35；
features/calibrate/cli.py 的 CALIB_MODE_FLAGS 18 项已过期，不作真源）。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ParamSpec:
    name: str                      # "file" / "--height"
    dest: str                      # argparse dest
    kind: str                      # "positional" | "option"
    type: str = "string"           # string|integer|boolean|path
    default: object = None
    required: bool = False
    choices: tuple = ()
    action: str = "store"          # store | store_true
    nargs: str | None = None
    negatable: bool = False        # stabilize --drop / --no-drop
    help: str = ""
    source: str = ""


@dataclass(frozen=True)
class ModeFlagSpec:
    flag: str                      # "--endobi"
    mode: str                      # 结果 mode
    one_click: bool = False        # 鸣潮一键重跑（带内置侧车）
    info_const: str = ""
    override_const: str = ""
    preserve: bool = False         # --wuwa38h 保留 >> 前缀
    ko_override: bool = False      # --wuwa40ko
    amiya: bool = False            # --arcakamiya 阿米娅侧车
    source: str = ""


@dataclass(frozen=True)
class ConstraintSpec:
    kind: str                      # "one_of"（恰好一个）
    params: tuple = ()
    required: bool = True
    note: str = ""


@dataclass(frozen=True)
class CommandSpec:
    name: str
    help: str
    params: tuple = ()
    mode_flags: tuple = ()
    constraints: tuple = ()
    passthrough: bool = False
    timeout: str = "medium"        # fast 30s | medium 300s | async（P2 任务句柄）
    read_only: bool = False
    open_world: bool = False       # 外部副作用（bili-submit 真实投稿）
    source: str = ""


#: 全局参数（顶层 + 子命令级 parents=[common]；default=SUPPRESS 由 parity 归一）
GLOBAL_PARAMS = (
    ParamSpec("--json", "as_json", "option", "boolean", default=False,
              action="store_true",
              help="结构化输出（stdout 只落一个 JSON；日志走 stderr）",
              source="features/_cli.py:140-142"),
    ParamSpec("--data-root", "data_root", "option", "path", default="",
              help="数据根目录（默认：VT_DATA_ROOT > data_dir.txt > 程序根）",
              source="features/_cli.py:143-144"),
)

_P = ParamSpec
_M = ModeFlagSpec
_C = ConstraintSpec

#: calibrate 33 个模式旗标（calib_core/cli.py:92-171 逐行核对）
CALIBRATE_MODE_FLAGS = (
    _M("--ko", "ko", source="calib_core/cli.py:92"),
    _M("--ja", "ja", source="calib_core/cli.py:94"),
    _M("--jpe", "jpe", source="calib_core/cli.py:96"),
    _M("--pgrja", "pgrja", source="calib_core/cli.py:98"),
    _M("--akja", "akja", source="calib_core/cli.py:100"),
    _M("--wwoc", "wwoc", source="calib_core/cli.py:102"),
    _M("--ak", "ak", source="calib_core/cli.py:104"),
    _M("--akko", "akko", source="calib_core/cli.py:106"),
    _M("--zho", "zho", source="calib_core/cli.py:108"),
    _M("--endo", "endo", source="calib_core/cli.py:110"),
    _M("--endobi", "endobi", source="calib_core/cli.py:112"),
    _M("--endoko", "endoko", source="calib_core/cli.py:114"),
    _M("--pgr", "pgr", source="calib_core/cli.py:116"),
    _M("--pgren", "pgren", source="calib_core/cli.py:118"),
    _M("--react", "react", source="calib_core/cli.py:120"),
    _M("--limbus", "limbus", source="calib_core/cli.py:122"),
    _M("--ffrs", "ffrs", source="calib_core/cli.py:124"),
    _M("--pbz", "pbz", source="calib_core/cli.py:126"),
    _M("--ff14", "ff14", source="calib_core/cli.py:128"),
    _M("--ssv", "ssv", source="calib_core/cli.py:130"),
    _M("--arcak", "arcak", source="calib_core/cli.py:132"),
    _M("--arcakamiya", "arcak", amiya=True, source="calib_core/cli.py:134"),
    _M("--tga26", "tga26", source="calib_core/cli.py:137"),
    _M("--zel", "zel", source="calib_core/cli.py:139"),
    _M("--hsr", "hsr", source="calib_core/cli.py:141"),
    _M("--pkm", "pkm", source="calib_core/cli.py:143"),
    _M("--wuwa38", "bi", one_click=True, info_const="WW38_INFO",
       override_const="WW38_OVERRIDES_SRC", source="calib_core/cli.py:151"),
    _M("--wuwa38h", "bi", one_click=True, info_const="WW38H_INFO",
       override_const="WW38H_OVERRIDES_SRC", preserve=True,
       source="calib_core/cli.py:154"),
    _M("--wuwa38b", "bi", one_click=True, info_const="WW38B_INFO",
       override_const="WW38B_OVERRIDES_SRC", source="calib_core/cli.py:157"),
    _M("--wuwa38j", "bi", one_click=True, info_const="WW38_J_INFO",
       override_const="WW38_J_OVERRIDES_SRC", source="calib_core/cli.py:160"),
    _M("--wuwa40", "bi", one_click=True, info_const="WW40_INFO",
       override_const="WW40_OVERRIDES_SRC", source="calib_core/cli.py:163"),
    _M("--wuwa40ko", "wuwa40ko", one_click=True, info_const="WW40KO_INFO",
       override_const="WW40KO_OVERRIDES_SRC", ko_override=True,
       source="calib_core/cli.py:166"),
    _M("--wuwasol", "bi", one_click=True, info_const="WUSOL_INFO",
       override_const="WUSOL_OVERRIDES_SRC", source="calib_core/cli.py:169"),
)

COMMANDS = (
    CommandSpec(
        name="status",
        help="环境/AI 配置自检（工具在位性、AI/ASR 槽是否已配）",
        params=(_P("--ping", "ping", "option", "boolean", default=False,
                   action="store_true",
                   help="实测全局 AI 连通性（发一次真实请求）",
                   source="features/status/cli.py:90"),),
        timeout="fast", read_only=True,
        source="features/status/cli.py"),
    CommandSpec(
        name="info",
        help="媒体/字幕元信息（ffprobe；字幕给 cue 数与时间跨度）",
        params=(_P("file", "file", "positional", "path", required=True,
                   help="视频 / 音频 / 字幕文件路径",
                   source="features/info/cli.py:113"),),
        timeout="fast", read_only=True,
        source="features/info/cli.py"),
    CommandSpec(
        name="download",
        help="下载视频（yt-dlp，自动代理+游客 cookie，合并 mp4）",
        params=(
            _P("url", "url", "positional", "string", required=True,
               help="视频链接（YouTube/B站等 yt-dlp 支持的站点）",
               source="features/download/cli.py:141"),
            _P("--dir", "dir", "option", "path", default="",
               help="输出目录（默认 data\\downloads\\agent\\<标题>\\）",
               source="features/download/cli.py:142"),
            _P("--height", "height", "option", "integer", default=0,
               help="限制最大分辨率高度（如 1080；0=不限制）",
               source="features/download/cli.py:143"),
            _P("--subs", "subs", "option", "boolean", default=False,
               action="store_true",
               help="同时下载字幕（job 编排模式下生效）",
               source="features/download/cli.py:145"),),
        timeout="async",
        source="features/download/cli.py"),
    CommandSpec(
        name="transcribe",
        help="ASR 转录出 SRT（模型/密钥读设置页 ASR 槽）",
        params=(
            _P("file", "file", "positional", "path", required=True,
               help="视频或音频文件", source="features/transcribe/cli.py:115"),
            _P("--lang", "lang", "option", "string", default="",
               help="识别语言：ISO 码或引擎标签（ja/en/zh/日本語…；空=自动检测）",
               source="features/transcribe/cli.py:116"),
            _P("--out", "out", "option", "path", default="",
               help="输出 .srt 或目录（默认 data\\agent_out\\<时间戳>\\）",
               source="features/transcribe/cli.py:117"),),
        timeout="async",
        source="features/transcribe/cli.py"),
    CommandSpec(
        name="translate",
        help="翻译字幕（bing/google/deeplx 免认证端点）",
        params=(
            _P("file", "file", "positional", "path", required=True,
               help="输入字幕（.srt/.ass/.vtt）",
               source="features/translate/cli.py:117"),
            _P("--to", "to", "option", "string", default="zh-Hans",
               help="目标语言（zh-Hans/简体中文/en…）",
               source="features/translate/cli.py:118"),
            _P("--engine", "engine", "option", "string", default="bing",
               choices=("bing", "google", "deeplx", "微软翻译", "谷歌翻译", "DeepLx 翻译"),
               help="翻译服务（默认 bing）",
               source="features/translate/cli.py:119"),
            _P("--threads", "threads", "option", "integer", default=4,
               help="并发线程数（默认 4）", source="features/translate/cli.py:122"),
            _P("--batch", "batch", "option", "integer", default=20,
               help="每块 cue 数（默认 20）", source="features/translate/cli.py:123"),
            _P("--out", "out", "option", "path", default="",
               help="输出字幕或目录（默认 data\\agent_out\\<时间戳>\\<名>.zh.srt）",
               source="features/translate/cli.py:124"),),
        timeout="medium",
        source="features/translate/cli.py"),
    CommandSpec(
        name="calibrate",
        help="字幕术语校准（透传 subtitle_calib_merged.py，只改文字不动时间轴）",
        params=(
            _P("input", "input", "positional", "path", required=True,
               help="输入 SRT（透传段第一个非旗标 token）",
               source="agent_cli.py:151-170"),
            _P("--out", "out", "option", "path", default=None,
               help="输出 SRT；不给只做命中统计、不改文件",
               source="calib_core/cli.py:88"),
            _P("--report", "report", "option", "path", default=None,
               help="TSV 差异报告", source="calib_core/cli.py:90"),
            _P("--kb", "kb", "option", "path", default=None,
               help="学习库路径（默认 CWD 下 subtitle_learned_kb.json）",
               source="calib_core/cli.py:147"),
            _P("--bi-override", "bi_override", "option", "path", default=None,
               help="逐 cue 侧车 TSV（序号+终稿整行；回退 VT_BI_OVERRIDE）",
               source="calib_core/cli.py:149"),
            _P("--fix-en", "fix_en", "option", "boolean", default=False,
               action="store_true", help="修正英文参考行 ASR 错词",
               source="calib_core/cli.py:145"),
            _P("--mode", "mode", "option", "string", default="bi",
               help="模式别名通道（bi/ja/ko/ak/endo/…；不能表达全部旗标模式）",
               source="calib_core/cli.py:172"),),
        mode_flags=CALIBRATE_MODE_FLAGS,
        passthrough=True, timeout="medium",
        source="features/calibrate/cli.py + calib_core/cli.py:86-207"),
    CommandSpec(
        name="stabilize",
        help="cue 稳定化（透传 subtitle_calib_merged.py 的 stabilize 子命令）",
        params=(
            _P("input", "input", "positional", "path", required=True,
               help="输入 SRT", source="agent_cli.py:151-170"),
            _P("--out", "out", "option", "path", default=None,
               help="不给只出报告（退出码 1＝有候选）",
               source="calib_core/cli.py:443-453"),
            _P("--report", "report", "option", "path", default=None,
               help="报告路径", source="calib_core/cli.py:358"),
            _P("--drop", "drop", "option", "boolean", default=True,
               negatable=True, help="丢弃候选（--no-drop 关）",
               source="calib_core/cli.py:354-357"),
            _P("--merge", "merge", "option", "boolean", default=True,
               negatable=True, help="碎片合并（--no-merge 关）",
               source="calib_core/cli.py:354-357"),
            _P("--split", "split", "option", "boolean", default=True,
               negatable=True, help="超长 cue 拆分（--no-split 关）",
               source="calib_core/cli.py:354-357"),),
        passthrough=True, timeout="medium",
        source="features/calibrate/cli.py + calib_core/cli.py:443-453"),
    CommandSpec(
        name="audit",
        help="名词漏校三扫（透传 subtitle_calib_merged.py 的 audit 子命令；"
             "拉丁残留 / 错形残留 / 同词族一致性，退出码 1＝有候选）",
        params=(
            _P("input", "input", "positional", "path", required=True,
               help="校准后 SRT", source="agent_cli.py:151-170"),
            _P("--mode", "mode", "option", "string", default="bi",
               help="术语族（_audit_mode_scope 解析）",
               source="calib_core/cli.py:456-466"),
            _P("--out", "out", "option", "path", default=None,
               help="Markdown 报告（MCP 侧建议必填）",
               source="calib_core/cli.py:358"),
            _P("--loose", "loose", "option", "boolean", default=False,
               action="store_true", help="追加无佐证低置信项",
               source="calib_core/cli.py:363"),
            _P("--window", "window", "option", "integer", default=0,
               help="扫 2/3 判官方名已译时向前后各看 N 条（0=严格逐 cue）",
               source="calib_core/cli.py:342"),),
        passthrough=True, timeout="medium", read_only=True,
        source="features/calibrate/cli.py + calib_core/cli.py:456-466"),
    CommandSpec(
        name="compose",
        help="字幕合成：软封装（copy）/ 硬烧录 / 带独立音轨合并",
        params=(
            _P("video", "video", "positional", "path", required=True,
               help="视频文件", source="features/compose/cli.py:78"),
            _P("sub", "sub", "positional", "path", required=True,
               help="字幕文件（.srt/.ass）", source="features/compose/cli.py:79"),
            _P("--audio", "audio", "option", "path", default="",
               help="独立音轨（.m4a/.weba，如下载产物分离音轨；可选）",
               source="features/compose/cli.py:80"),
            _P("--mode", "mode", "option", "string", default="soft",
               choices=("soft", "burn", "mkv"),
               help="soft=软封装不重编码（默认）；burn=硬烧录（ASS，重编码）；mkv=封装进 MKV",
               source="features/compose/cli.py:81"),
            _P("--out", "out", "option", "path", default="",
               help="输出文件（默认 data\\agent_out\\<时间戳>\\<名>.composed.mp4）",
               source="features/compose/cli.py:83"),),
        timeout="medium",   # burn/mkv 属 async 档（P2）；soft 同步
        source="features/compose/cli.py"),
    CommandSpec(
        name="split",
        help="视频切片：按时间点（HH:MM:SS）或时长（xHyMzS）拆成多段，逐段校验可播放",
        params=(
            _P("file", "file", "positional", "path", required=True,
               help="源视频", source="features/split/cli.py:75"),
            _P("--points", "points", "option", "string", default="",
               help="时间点列表（HH:MM:SS），如 \"00:00:00,01:00:00,02:00:00\"",
               source="features/split/cli.py:76"),
            _P("--durations", "durations", "option", "string", default="",
               help="时长列表（xHyMzS），如 \"1h,1h\" / \"1h30m,30m,45s\"",
               source="features/split/cli.py:78"),
            _P("--mode", "mode", "option", "string", default="auto",
               choices=("copy", "auto", "encode"),
               help="copy=无损快切；auto=快切校验不过就重编码（默认）；encode=精确重编码",
               source="features/split/cli.py:80"),
            _P("--out", "out", "option", "path", default="",
               help="输出目录（默认 data\\agent_out\\<时间戳>\\<名>_split）",
               source="features/split/cli.py:82"),
            _P("--verify", "verify", "option", "string", default="quick",
               choices=("quick", "full"),
               help="逐段校验强度：quick=片头片尾抽检（默认）；full=整段全解码",
               source="features/split/cli.py:84"),),
        constraints=(_C("one_of", ("points", "durations"), required=True,
                        note="恰好给一个；都空或都给都报错（运行时校验）"),),
        timeout="async",
        source="features/split/cli.py"),
    CommandSpec(
        name="bili-submit",
        help="B 站后台自动投稿（UI Automation 定位 + 后台输入；素材目录内含投稿信息.txt）",
        params=(
            _P("material", "material", "positional", "path", default="",
               nargs="?", help="素材目录",
               source="features/automation/cli.py:31"),
            _P("--probe", "probe", "option", "boolean", default=False,
               action="store_true", help="只输出当前页面 UIA 结构",
               source="features/automation/cli.py:32"),
            _P("--dry-run", "dry_run", "option", "boolean", default=False,
               action="store_true", help="填完但不点立即投稿",
               source="features/automation/cli.py:33"),
            _P("--edit", "edit", "option", "boolean", default=False,
               action="store_true", help="修复当前编辑页（不新上传视频）",
               source="features/automation/cli.py:34"),
            _P("--only", "only", "option", "string", default="",
               help="只跑阶段：basic,chapters,cover,topic,subtitle,visibility",
               source="features/automation/cli.py:35"),
            _P("--visibility", "visibility", "option", "string", default="self",
               choices=("self", "public"),
               help="可见范围（默认 self=仅自己可见）",
               source="features/automation/cli.py:36"),
            _P("--topic", "topic", "option", "string", default="",
               help="覆盖参与话题", source="features/automation/cli.py:38"),
            _P("--cover", "cover", "option", "path", default="",
               help="覆盖封面图片", source="features/automation/cli.py:39"),
            _P("--subtitle", "subtitle", "option", "path", default="",
               help="覆盖 SRT 字幕", source="features/automation/cli.py:40"),),
        timeout="async", open_world=True,
        source="features/automation/cli.py"),
)


def get_command(name: str) -> CommandSpec:
    for c in COMMANDS:
        if c.name == name:
            return c
    raise KeyError(name)


def iter_commands() -> tuple:
    return COMMANDS