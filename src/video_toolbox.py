#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# @version 1.15.0
"""
视频工具箱 v1.12.0（单文件整合版）
==================================================
v1.12.2：校准知识收集通道调整（用户拍板）——
  ① 恢复 GitHub 整文件同步通道（_gh_* / sync_calib_to_github / _pull_and_merge）：
  用于收集不同使用者在校准过程中产生的增量内容；条目级三方合并保证
  多用户互不覆盖、收敛到并集；
  ② 所有上传全自动、隐藏在后台：校准 learn 实时写本地学习库，退出程序时
  派生隐藏子进程自动推送 GitHub（界面不提供也不显示任何上传入口）；
  ③ 连接参数统一使用内置 github_proxy.yaml 的 vt-github 段
  （owner/repo/branch/api/token/files）；直连失败回退同文件的代理规则；
  ④ 程序界面仅保留「更新」选项（启动自动 + 手动立即更新）；
  ⑤ v1.12.1 的本地增量镜像通道（kb-sync/kb-push + baseline/inbox）保留为
  可选增强：管理员用独立程序 kb_admin.exe 配了共享更新库时自动叠加启用。
v1.12.1：（已被 v1.12.2 部分取代）工具箱曾只保留「更新 + 上传增量」两动作、
  GitHub 通道全部移交独立程序；现按要求恢复 GitHub 收集通道。
v1.12.0：翻译链路全面修缮（配套 site-packages 里的引擎改动，均由
  src\apply_vc_official.py 归档可复现）：① 谷歌翻译改抓 Chrome 内置翻译同源
  免费接口（translate_a/t?client=dict-chrome-ex）并加全局请求节流（≥0.12s/次，
  约 8 QPS）——官方旧端点 translate.google.com/m 已被 302 到验证码页；
  ② 必应翻译换 translatetext 端点取 token（官方匿名 token 方案已失效）；
  ③ 翻译基类对失败译文（ERROR / 空 / xxx||ERROR）不写缓存，块级失败可重试；
  ④ LLM 翻译并发上限 `_LLM_THREAD_CAP=5`（免费/共享模型速率限制很紧，50 并发
  会 429 刷屏）与限流处理；⑤ 任务取消立即停掉翻译/优化线程池（原先取消后
  仍把剩余批次跑完）；⑥ 「启用 AI」关闭时，翻译兜底与引擎 LLM 注入都不介入。
v1.11.0：① LLM 拆分为**两条各自独立的 API 通道**——接口 A（工具箱自身：
  标题/语言识别与视觉，Anthropic 兼容）与接口 B（字幕引擎优化/翻译/拆分与
  AI 校准，OpenAI 兼容），地址、密钥、模型都能分别填写，接口 B 密钥留空则
  沿用 A（旧配置平滑迁移）；② 新增全局 ASR（语音识别）配置：可接自有 ASR
  服务（OpenAI 兼容 /audio/transcriptions）或本地独立 faster-whisper 模型
  （模型名 + 模型目录自定义），保存即写入引擎「转录配置」——服务模式切到
  Whisper [API]，本地模式切到 FasterWhisper 并由 vc_asr_patch_apply() 覆盖
  模型名/目录；③ 新增 Agent 级 AI 校准入口 calib_ai_run（实现见
  src\\calib_ai_agent.py）；④ 修复启动同步长期静默失败：_pull_and_merge 调用
  的 _read_sync_text / _atomic_write 此前**未定义**（日志反复出现
  「启动同步异常（忽略）: name '_read_sync_text' is not defined」）；
  ⑤ vc_lazy_cache_patch()：引擎在模块级建 5 个 diskcache 库（每个约 0.9s）
  改为惰性代理，进入「字幕处理」页的等待从数秒降到亚秒级。
v1.10.5：校准脚本升级为对象级知识库版本（ENTITIES 对象层 + learn 学习系统）；
  校准界面模式列表与脚本实际支持的全部 12 种模式对齐，移除脚本已删除的
  「长句拆两行（--layout）」开关；新增退出时自动同步校准脚本到 GitHub
  （sync_calib_on_exit，挂接 QApplication.aboutToQuit）：静默后台、不阻塞退出、
  不弹窗，直连失败回退内置 mihomo 代理（仅 api.github.com），日志见
  logs 目录下的 calib_sync.log。
v1.10.4：界面与设置整合——左侧导航宽度按「最长项文字 + 2 个字符」自适应
  （不再固定 322px）；新增导航底部「设置」页，工具设置与字幕引擎设置统一
  入口（原「字幕处理」页右下「引擎设置…」对话框并入）；跨屏拖拽按相对位置
  平滑移动（不再因两屏缩放比不同而瞬移）；DPI 取整策略改为 PassThrough，
  100%/125%/150%/200% 缩放比表现一致；字幕引擎界面后台预热，消除首次进入
  「字幕处理」页的数秒卡顿。
v1.10.2：字幕引擎改为内嵌——不再唤起独立窗口，「字幕处理」页直接呈现引擎
  界面（品牌水印/捐助入口在嵌入层隐藏，engine_ui_brand_patch 中性化用户可见
  文案；许可与来源声明保留在 docs 目录下）；界面布局重做：页面「标题区固定 +
  内容滚动」，窗口尺寸按屏幕自适应，高分屏矢量渲染；随包 wheel 与独立进程
  唤起链路（launch_vc_gui / vc_install_from_wheel）移除。
v1.10.1：① 界面整体重写为 Fluent 风格（FluentWindow +
  左侧导航 + 卡片分组，PyQt5 + PyQt-Fluent-Widgets），原 tkinter 界面退役；
  ② 移除「B站投稿」板块及其 Playwright 引擎（tools/uploader_src、tools/ms-playwright
  不再随包分发），AI 客户端独立为 tools/ai_client.py 供字幕语言识别继续使用；
  ③ 修复：直接运行构建产物时找不到 tools/python 的问题（向上逐级查找）。
v1.10.0：字幕链路整体替换为第三方开源字幕引擎（GPL-3.0 组件）——
  语音转录 / 字幕优化 / 翻译 / 配音 / 合成全部交由引擎承担；
  原自带 ASR 实现（src\asr_subtitle_worker.py + tools\asr_model 模型引导）已移除；
  「字幕校准」页仍调用自建术语库脚本 subtitle_calib_merged.py 做终校。
v1.9.0：接入全局 AI（智谱 GLM：glm-4.7-flash 文本 + glm-4.6v-flash 视觉，
  配置 data\ai_config.json）；字幕语言由 AI 识别标题语言自动匹配（下载侧）。
目录结构（v1.7 按功能划分，程序目录顶层只留主程序）：
  视频工具箱.exe | tools/ 运行时 | src/ 源代码 | docs/ 文档
  data/ 用户数据（下载/配置/缓存/登录态/任务/分区缓存）| logs/ 日志
功能 1 - 视频下载：
  拖入链接（.url 快捷方式 / 含链接的 txt / 直接粘贴链接）
  -> 自定义保存位置（回车 = 上次使用的目录，长期记忆）
  -> 自动检测画质：仅 >=720p、同分辨率只保留最大文件、优先 60fps
  -> 下载并合并为 mp4（音频始终最高质量）
  -> 每个视频打包到独立文件夹：视频 + 封面.jpg（1280x720）+ 视频信息.txt

功能 2 - 音视频智能合并（整合自 merge_audio_video v3.2）：
  扫描文件夹，按文件名/时长智能配对 mp4 + m4a/weba + srt/ass，合并为完整视频
  m4a -> 直接封装 | weba -> 转 AAC | SRT -> 软字幕 | ASS -> 烧录/MKV/忽略

首次运行自动在脚本旁 tools\\ 目录下载 yt-dlp 与 ffmpeg（仅一次）
"""

import os
import sys
import json
import glob
import shutil
import base64
import subprocess
import urllib.request
import zipfile
import re
import time
import atexit
import threading
import tempfile
import codecs
from datetime import datetime
from pathlib import Path

# ========== 统一文本编解码：同时兼容 UTF-8 / GBK(GB18030) / ASCII ==========
# 设计原则：读取任何“外部/用户产生”的文本（字幕、.url、第三方子进程输出、远程
# 同步内容等）都走 decode_bytes_any / read_text_any，按 BOM → UTF-8 → GB18030
# 顺序探测，绝不因编码不同而崩溃或乱码；本程序自己写出的文件统一用 UTF-8
# （给用户用记事本看的用 utf-8-sig）。ASCII 是 UTF-8 的子集，天然被覆盖。
# 说明：GB18030 是 GBK 的超集（兼容 GBK/GB2312），用于解码老式中文 Windows、
# 部分播放器与字幕工具导出的 GBK 字幕；另兼容 Big5 与带 BOM 的 UTF-16。
_TEXT_BOMS = (
    (codecs.BOM_UTF8, "utf-8-sig"),
    # UTF-32 的 BOM 以 UTF-16 BOM 为前缀，必须先判 32 再判 16；
    # 用 utf-16/utf-32（非 -le/-be）可据 BOM 自动定字节序并剥掉 BOM。
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)
# 无 BOM 时的探测顺序：先 UTF-8（ASCII 也在此命中），失败再按中文编码回退
TEXT_ENCODINGS = ("utf-8", "gb18030", "big5", "shift_jis", "latin-1")


def decode_bytes_any(data, encodings=TEXT_ENCODINGS):
    """把 bytes 稳健解码为 str：识别 BOM，依次尝试 UTF-8/GB18030/Big5/...。

    - 传入 str 原样返回；None 返回空串；永不抛 UnicodeDecodeError。
    - UTF-8（含纯 ASCII）优先；不是合法 UTF-8 时按 GB18030（GBK 超集）等回退，
      最后才用 replace 兜底，最大化还原中文内容、避免崩溃。
    """
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    if isinstance(data, (bytearray, memoryview)):
        data = bytes(data)
    if not isinstance(data, (bytes,)):
        return str(data)
    for bom, enc in _TEXT_BOMS:
        if data.startswith(bom):
            try:
                return data.decode(enc, errors="replace")
            except (UnicodeDecodeError, LookupError):
                break
    for enc in encodings:
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def read_text_any(path, encodings=TEXT_ENCODINGS):
    """以二进制读取文件并用 decode_bytes_any 解码（兼容 UTF-8/GBK/ASCII）。"""
    with open(path, "rb") as f:
        return decode_bytes_any(f.read(), encodings)


def write_text_utf8(path, text, bom=False, newline=None):
    """规范写出文本：默认无 BOM 的 UTF-8；bom=True 写 utf-8-sig（记事本友好）。"""
    enc = "utf-8-sig" if bom else "utf-8"
    kw = {} if newline is None else {"newline": newline}
    with open(path, "w", encoding=enc, **kw) as f:
        f.write(text)


def decode_process_output(value):
    """兼容子进程 text/bytes 两种返回：bytes 走智能解码，str 原样返回。"""
    return decode_bytes_any(value)


def configure_stdio_utf8():
    """让标准输出/错误流以 UTF-8、replace 容错，避免在 GBK 控制台打印生僻字/Emoji
    时 UnicodeEncodeError 崩溃。幂等，可重复调用。"""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
            except Exception:
                pass
    # 子进程默认也用 UTF-8 与我们通信（个别工具仍可能输出 GBK，读取侧再智能解码）
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ.setdefault("PYTHONUTF8", "1")

# ========== 路径与常量（v1.7 按功能分目录） ==========
# 目录规划（安装后 / 开发期一致）：
#   APP_DIR\ 视频工具箱.exe      主程序（顶层唯一可执行）
#   APP_DIR\tools\               运行时（ffmpeg/yt-dlp/内嵌python/chromium/投稿引擎/模型）
#   APP_DIR\src\                 源代码与脚本启动器（脚本方式运行/查阅）
#   APP_DIR\docs\                使用说明等文档
#   APP_DIR\data\                用户数据（配置/下载/缩略图缓存/登录态/投稿任务/分区缓存）
#   APP_DIR\logs\                全部日志（投稿日志与失败截图在 logs\uploader）
if getattr(sys, "frozen", False):
    # PyInstaller 打包后，锚定到 exe 所在目录
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    # 源码位于 APP_DIR\src，故取本文件上两级为程序根
    APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# SCRIPT_DIR 保留旧名（语义=程序根目录），避免全项目改动
SCRIPT_DIR = APP_DIR


def _resolve_tools_dir():
    """定位 tools 运行时目录。

    正常安装形态：就在 exe 同级的 tools\\。但直接运行构建产物
    （如 dist\\视频工具箱.exe，旁边只有 exe）时它不存在——此时向上逐级查找，
    便于开发期调试；都找不到则返回默认位置（后续报错文案会指出实际查找位置）。
    """
    d = APP_DIR
    for _ in range(5):
        cand = os.path.join(d, "tools")
        if os.path.isdir(cand):
            return cand
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return os.path.join(APP_DIR, "tools")


TOOLS_DIR = _resolve_tools_dir()
SRC_DIR = os.path.join(APP_DIR, "src")
DOCS_DIR = os.path.join(APP_DIR, "docs")

# ===== 数据根目录（v1.10.6：运行期产物一律落此，不回写系统盘）=====
# 设计目标：程序运行中产生的全部文件（配置/下载/缓存/日志/临时文件/字幕引擎
# 数据）都集中到同一个根目录下，默认就在程序目录，**不写系统盘（C 盘）**。
#
# 优先级：
#   1. 环境变量 VT_DATA_ROOT（便于便携部署 / 脚本指定）
#   2. data_dir.txt 指针文件（用户在「设置 → 工具设置 → 数据目录」里改的位置）
#   3. 默认 APP_DIR（程序目录，即"绿色便携"体验）
#
# 注意：指针文件本身必须放在固定位置才能被发现，故放程序目录下；它是唯一
# 允许写在程序目录的引导文件，不含用户数据。
DATA_ROOT_POINTER = os.path.join(APP_DIR, "data_dir.txt")


def _resolve_data_root():
    """解析数据根目录：环境变量 > 指针文件 > 程序目录默认值。"""
    env = (os.environ.get("VT_DATA_ROOT") or "").strip().strip('"')
    if env:
        try:
            return os.path.abspath(env)
        except OSError:
            pass
    try:
        if os.path.isfile(DATA_ROOT_POINTER):
            with open(DATA_ROOT_POINTER, encoding="utf-8-sig") as f:
                v = f.read().strip().strip('"')
            if v:
                return os.path.abspath(v)
    except OSError:
        pass
    return APP_DIR


DATA_ROOT = _resolve_data_root()
DATA_DIR = os.path.join(DATA_ROOT, "data")
LOGS_DIR = os.path.join(DATA_ROOT, "logs")
DEFAULT_DOWNLOAD_DIR = os.path.join(DATA_DIR, "downloads")
THUMB_CACHE_DIR = os.path.join(DATA_DIR, "thumb_cache")
# 运行期临时文件（下载分片、转码中间件、字幕引擎工作目录）——不落系统 Temp
TMP_DIR = os.path.join(DATA_DIR, "tmp")

YTDLP_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
FFMPEG_ZIP_URL = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
# yt-dlp 提取 YouTube 需要 JS 运行时（deno，官方默认启用）；缺失时部分视频
# 的格式会缺失或提取失败（2026 版起已弃用无 JS 提取）。deno.exe 与 yt-dlp.exe
# 放同目录即被自动发现。镜像：https://gh-proxy.com/ + 官方 URL
DENO_URL = ("https://github.com/denoland/deno/releases/latest/download/"
            "deno-x86_64-pc-windows-msvc.zip")
DENO_MIRROR_URL = ("https://gh-proxy.com/" + DENO_URL)

YTDLP_PATH = os.path.join(TOOLS_DIR, "yt-dlp.exe")
FFMPEG_PATH = os.path.join(TOOLS_DIR, "ffmpeg.exe")
FFPROBE_PATH = os.path.join(TOOLS_DIR, "ffprobe.exe")
DENO_PATH = os.path.join(TOOLS_DIR, "deno.exe")

# ===== 内置代理（mihomo/ClashMeta 核心，与 FlClash 同源，随安装包分发）=====
# 用途：程序从 GitHub/HuggingFace 等开源库下载依赖、yt-dlp 下载 YouTube 视频
#       与字幕时自动启用，其余流量直连。
# 端口固定 7897，与本机其他代理（FlClash 等占用 7890）互不冲突。
MIHOMO_DIR = os.path.join(TOOLS_DIR, "mihomo")
MIHOMO_EXE = os.path.join(MIHOMO_DIR, "mihomo.exe")
MIHOMO_CONFIG = os.path.join(MIHOMO_DIR, "config.yaml")
#: 引擎编译出的运行配置（节点取自订阅，端口/规则/代理组固定程序专用）
MIHOMO_RUNTIME_CONFIG = os.path.join(MIHOMO_DIR, "runtime.yaml")
MIHOMO_PROXY = "http://127.0.0.1:7897"
MIHOMO_PORT = 7897
#: mihomo 控制端口（RESTful API）：程序用来主动触发节点测速 / 切换节点。
#: 只绑 127.0.0.1，无密钥，仅本机可访问。
MIHOMO_CONTROLLER = "127.0.0.1:9098"
MIHOMO_API = "http://" + MIHOMO_CONTROLLER
#: 节点测活 URL（mihomo 惯例 204 探测）
MIHOMO_TEST_URL = "https://www.gstatic.com/generate_204"

CONFIG_PATH = os.path.join(DATA_DIR, "config.json")


def _migrate_legacy_layout():
    """v1.6 及以前版本散落在程序根/tools 下的用户数据，一次性迁移到 data/logs（幂等）。"""
    # (旧位置, 新位置)；仅当新位置为空且旧位置存在时迁移
    moves = [
        (os.path.join(APP_DIR, "config.json"), CONFIG_PATH),
        (os.path.join(APP_DIR, "downloads"), DEFAULT_DOWNLOAD_DIR),
        (os.path.join(APP_DIR, "thumb_cache"), THUMB_CACHE_DIR),
    ]
    for old, new in moves:
        try:
            if not os.path.exists(old) or os.path.exists(new):
                continue
            os.makedirs(os.path.dirname(new), exist_ok=True)
            shutil.move(old, new)
        except OSError:
            pass


_migrate_legacy_layout()

# 运行时数据/日志目录统一预建（安装包也会预建空壳，这里兜底）
for _d in (DATA_DIR, LOGS_DIR, DEFAULT_DOWNLOAD_DIR, THUMB_CACHE_DIR, TMP_DIR):
    try:
        os.makedirs(_d, exist_ok=True)
    except OSError:
        pass

# 把本进程及其所有子进程的临时目录指向 TMP_DIR：避免 tempfile / 第三方库
# （VideoCaptioner、faster-whisper 等）把中间产物写进系统 Temp（通常在 C 盘）。
# 子进程经 worker_subprocess_env() 继承同一设置。
os.environ["TEMP"] = TMP_DIR
os.environ["TMP"] = TMP_DIR
tempfile.tempdir = TMP_DIR
# 数据根目录同样注入环境变量：tools/ai_client.py 等独立加载的模块据此把配置
# 写到软件文件夹（而非按 __file__ 层级猜目录、或退回用户目录/C 盘）。
os.environ.setdefault("VT_DATA_ROOT", DATA_ROOT)


def _fallback_config_path():
    """配置回退位置。

    v1.10.6 起：配置一律写在数据根目录下（默认程序目录），**不再回退到
    %LOCALAPPDATA%（C 盘）**。仅当数据根目录也写不进去时，才退到程序目录，
    保证"配置永不落系统盘"这一约束优先于可用性。
    """
    cand = os.path.join(DATA_DIR, "config.json")
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        return cand
    except OSError:
        return os.path.join(APP_DIR, "data", "config.json")

DEFAULT_INPUT_DIR = r"D:\剪辑"
DURATION_THRESHOLD = 1.0
URL_RE = re.compile(r'https?://[^\s"<>\)\]]+')
# =============================


# ========== 内置运行时（字幕处理） ==========
# tools\python 为随安装包分发的 CPython 3.12 运行时：faster-whisper、
# VideoCaptioner 及其依赖全部装在其 site-packages 下。
EMBEDDED_PYTHON_DIR = os.path.join(TOOLS_DIR, "python")
EMBEDDED_SITE_PACKAGES = os.path.join(EMBEDDED_PYTHON_DIR, "Lib", "site-packages")


def _is_self_exe(path):
    """path 是否就是本程序自身（打包后 sys.executable 指向 exe 自己）。

    一旦把自身 exe 当作「Python 解释器」去 Popen，Windows 会拉起一个全新的
    主程序实例——v1.12.0 的退出同步就是这么写的，结果退出时不断自启、表现为
    「关不掉的反复重启」。所有解析解释器 / 启动子进程的地方都必须过这道闸。
    """
    if not path or not getattr(sys, "frozen", False):
        return False
    try:
        return (os.path.normcase(os.path.abspath(path)) ==
                os.path.normcase(os.path.abspath(sys.executable)))
    except Exception:  # noqa: BLE001
        return False


def system_python():
    """运行字幕处理 / 投稿 worker 的 Python：优先用工具箱内 tools\\python\\python.exe；
    否则源码模式用当前解释器，打包后用系统 PATH 中的 python（找不到返回 ""）。"""
    embedded = os.path.join(EMBEDDED_PYTHON_DIR, "python.exe")
    if os.path.isfile(embedded):
        return embedded
    if not getattr(sys, "frozen", False):
        return sys.executable
    found = shutil.which("python") or ""
    return "" if _is_self_exe(found) else found


def worker_subprocess_env():
    """worker 子进程环境：内嵌解释器已完整自包含，无需注入 PYTHONPATH；
    仅当回退到系统 Python 时，把内嵌 site-packages 追加进去以免缺包。
    v1.10.6 起同时把 TEMP/TMP 指向数据根目录，避免子进程把中间产物
    写进系统盘；并传递 VT_DATA_ROOT 供子进程内的引擎解析同一根目录。"""
    env = os.environ.copy()
    if system_python() != os.path.join(EMBEDDED_PYTHON_DIR, "python.exe"):
        env["PYTHONPATH"] = (EMBEDDED_SITE_PACKAGES + os.pathsep +
                             env.get("PYTHONPATH", "")).rstrip(os.pathsep)
    try:
        os.makedirs(TMP_DIR, exist_ok=True)
        env["TEMP"] = TMP_DIR
        env["TMP"] = TMP_DIR
    except OSError:
        pass
    env["VT_DATA_ROOT"] = DATA_ROOT
    return env
# =============================


# ========== 字幕处理：内嵌第三方字幕引擎（GPL-3.0 组件，随包分发） ==========
# v1.10.2 起，字幕引擎界面直接内嵌在主程序「字幕处理」页中（不再唤起独立
# 窗口）。引擎以第三方开源组件形式随包分发：打包形态打进 exe（见
# 视频工具箱.spec），源码形态装在 tools\python\Lib\site-packages 下。
# 工具箱负责：环境探测 → 引擎界面内嵌 → 用户可见文案中性化（品牌水印、
# 捐助入口等在嵌入层隐藏；许可与来源见 docs\ 下声明文件）。
VC_NAME = "VideoCaptioner"
VC_VERSION = "1.4.2"
VC_LICENSE = "GPL-3.0"
VC_HOMEPAGE = "https://github.com/WEIFENG2333/VideoCaptioner"
VC_DOCS = "https://weifeng2333.github.io/VideoCaptioner/"
VC_PKG_DIR = os.path.join(EMBEDDED_SITE_PACKAGES, "videocaptioner")
VC_LICENSE_FILE = os.path.join(DOCS_DIR, "VideoCaptioner_GPL-3.0.txt")
VC_SOURCE_FILE = os.path.join(DOCS_DIR, "VideoCaptioner_组件来源.txt")


def vc_importable():
    """内嵌字幕引擎在当前进程是否可用（源码模式依赖 tools\\python 的包）。"""
    try:
        import importlib.util
        return importlib.util.find_spec("videocaptioner") is not None
    except Exception:
        return False


def vc_missing_deps():
    """引擎界面运行所需依赖缺哪些（PyQt5 / qfluentwidgets）；齐全返回空列表。"""
    import importlib.util
    need = {"PyQt5": "PyQt5", "qfluentwidgets": "PyQt-Fluent-Widgets"}
    return [pip_name for mod, pip_name in need.items()
            if importlib.util.find_spec(mod) is None]


def vc_env_ready():
    """字幕引擎是否可在当前进程内嵌：包与 Qt 依赖齐全。"""
    return vc_importable() and not vc_missing_deps()


def vc_state():
    """环境状态文案，供 GUI 显示。返回 (是否就绪, 主文案, 细节文案)。"""
    if vc_env_ready():
        return True, "字幕引擎已就绪（内嵌运行）", ""
    if not vc_importable():
        return (False, "未安装字幕引擎组件",
                "当前进程找不到字幕引擎组件。安装版自带（打进主程序）；"
                "源码方式运行请用 src\\视频工具箱.bat（走 tools\\python 运行时）。")
    return (False, "字幕引擎依赖不完整：缺少 " + "、".join(vc_missing_deps()),
            "请使用完整版安装包重新安装（依赖随机带运行时分发）")


def vc_data_dir():
    """字幕引擎的配置/日志数据目录。

    v1.10.6 起不再使用 platformdirs 的 %LOCALAPPDATA%（C 盘）约定，
    改为数据根目录下的 data/VideoCaptioner，与工具箱其余运行期产物同处，
    便于整体搬迁与清理。
    """
    return os.path.join(DATA_DIR, VC_NAME)


# 字幕引擎在 C 盘的历史数据位置（用于一次性迁移与"残留检测"）
_VC_LEGACY_DIRS = (
    os.path.join(os.environ.get("LOCALAPPDATA", ""), VC_NAME),
    os.path.join(os.environ.get("APPDATA", ""), VC_NAME),
    os.path.join(os.path.expanduser("~"), VC_NAME),
)


def vc_bundled_resource_dir():
    """随包分发的引擎只读静态资源目录（assets/fonts/subtitle_style/translations）。

    VideoCaptioner 的纯代码 wheel 只含 .py、不含 resource/，故我们把与所集成
    版本一致的上游 resource 静态文件随包放在 tools/videocaptioner/resource 下，
    既不落到系统盘，也保证离线环境下界面图片、默认字幕样式、烧录字体齐全。
    """
    return os.path.join(TOOLS_DIR, "videocaptioner", "resource")


def vc_redirect_paths():
    """在导入 videocaptioner 之前，把引擎的数据/工作/日志目录重定向到数据根目录，
    并把静态资源、ffmpeg 接到随包目录，使字幕引擎真正自包含、成为程序的一部分。

    上游 config.py 在导入时即固化一批常量：
      · ROOT_PATH  = platformdirs.user_data_dir("VideoCaptioner")  → AppData\\Local
      · WORK_PATH  = Path.home() / "VideoCaptioner"                → 用户目录
      · RESOURCE_PATH/ASSETS_PATH/BIN_PATH/FONTS_PATH/...          → 上述目录下
    pip 形态下 wheel 只有代码、没有 resource（界面图片/默认样式缺失），且空的
    BIN_PATH 不会被加入 PATH，导致引擎内部裸调 "ffmpeg" 时找不到二进制。这里在不
    改动第三方源码的前提下统一打补丁：
      · 可写运行数据（日志/缓存/模型/工作目录/设置/用户字幕样式）→ data\\VideoCaptioner
      · 只读静态资源（图片/字体/翻译/默认样式）→ tools\\videocaptioner\\resource
      · ffmpeg/ffprobe 复用工具箱自带 tools\\ffmpeg.exe（BIN_PATH=TOOLS_DIR 并加入 PATH）
    """
    import sys as _sys
    if "videocaptioner.config" in _sys.modules:
        return  # 已导入过，路径常量已固化；补丁只在首次导入时有效
    target = Path(vc_data_dir())
    user_style_dir = target / "resource" / "subtitle_style"
    try:
        target.mkdir(parents=True, exist_ok=True)
        for sub in ("logs", "cache", "models", "work-dir"):
            (target / sub).mkdir(parents=True, exist_ok=True)
        user_style_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass

    from videocaptioner import config as _vc_cfg

    # —— 可写运行数据，全部收进软件文件夹（不写系统盘）——
    _vc_cfg.ROOT_PATH = target
    _vc_cfg.APPDATA_PATH = target
    _vc_cfg.WORK_PATH = target / "work-dir"
    _vc_cfg.LOG_PATH = target / "logs"
    _vc_cfg.LLM_LOG_FILE = _vc_cfg.LOG_PATH / "llm_requests.jsonl"
    _vc_cfg.SETTINGS_PATH = target / "settings.json"
    _vc_cfg.CACHE_PATH = target / "cache"
    _vc_cfg.MODEL_PATH = target / "models"

    # —— 只读静态资源：优先随包目录；缺失时回退数据目录（保持旧行为、不崩）——
    bundled = Path(vc_bundled_resource_dir())
    res_root = bundled if bundled.is_dir() else (target / "resource")
    try:
        res_root.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    _vc_cfg.RESOURCE_PATH = res_root
    _vc_cfg.ASSETS_PATH = res_root / "assets"
    _vc_cfg.TRANSLATIONS_PATH = res_root / "translations"
    fonts_dir = res_root / "fonts"
    if not fonts_dir.is_dir():
        # 回退到包内自带字体（videocaptioner/resources/fonts）
        fonts_dir = getattr(_vc_cfg, "_BUNDLED_FONTS", fonts_dir)
    _vc_cfg.FONTS_PATH = fonts_dir

    # —— 用户字幕样式放可写数据目录，并从随包默认样式补齐缺失预设（不覆盖用户）——
    _vc_cfg.SUBTITLE_STYLE_PATH = user_style_dir
    try:
        seed = bundled / "subtitle_style"
        if seed.is_dir():
            for jf in seed.glob("*.json"):
                dst = user_style_dir / jf.name
                if not dst.exists():
                    shutil.copyfile(jf, dst)
    except OSError:
        pass

    # —— ffmpeg/ffprobe：复用工具箱自带二进制（BIN_PATH 指向 TOOLS_DIR）——
    bin_dir = Path(TOOLS_DIR)
    _vc_cfg.BIN_PATH = bin_dir
    _vc_cfg.FASTER_WHISPER_PATH = bin_dir / "Faster-Whisper-XXL"
    # config 导入期那次 PATH 注入用的是空 BIN（目录不存在即跳过），这里自行补上，
    # 保证引擎内部裸调 "ffmpeg"/"ffprobe" 能命中随包二进制。
    try:
        cur = os.environ.get("PATH", "")
        parts = cur.split(os.pathsep) if cur else []
        if str(bin_dir) not in parts:
            os.environ["PATH"] = str(bin_dir) + os.pathsep + cur
        if _vc_cfg.FASTER_WHISPER_PATH.is_dir() and \
                str(_vc_cfg.FASTER_WHISPER_PATH) not in parts:
            os.environ["PATH"] = str(_vc_cfg.FASTER_WHISPER_PATH) + \
                os.pathsep + os.environ["PATH"]
    except OSError:
        pass

    for _p in (_vc_cfg.WORK_PATH, _vc_cfg.LOG_PATH, _vc_cfg.CACHE_PATH,
               _vc_cfg.MODEL_PATH):
        try:
            Path(_p).mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

    # CLI 子模块另有一套 user_config_dir 约定（默认 AppData\\Roaming），
    # 它按需导入，故用 sys.modules 预置桩模块的方式覆盖其常量。
    try:
        from videocaptioner.cli import config as _vc_cli
        _vc_cli.CONFIG_DIR = target / "cli"
        _vc_cli.CONFIG_FILE = _vc_cli.CONFIG_DIR / "config.toml"
        _vc_cli.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


# ---------- 引擎 settings.json：路径全部收进软件文件夹 + 全局 LLM 注入 ----------
def vc_settings_path():
    """字幕引擎的 settings.json 路径（数据根下，绝不在系统盘）。"""
    return os.path.join(vc_data_dir(), "settings.json")


def _vc_read_settings():
    """读取引擎 settings.json；缺失/损坏返回空 dict（绝不抛异常）。"""
    try:
        data = json.loads(read_text_any(vc_settings_path()))
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {}


def _vc_write_settings(data):
    """原子写回引擎 settings.json（缩进与上游 qconfig 落盘风格一致）。"""
    path = vc_settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".vt_tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    os.replace(tmp, path)


def _path_on_system_drive(p):
    """绝对路径是否落在系统盘（默认 C:）的用户目录/AppData/ProgramData。

    用于揪出引擎历史设置里仍指向 C 盘的路径项；非绝对路径（相对/空）一律
    视为安全（上游会按重定向后的常量解析到软件文件夹）。
    """
    if not p or not isinstance(p, str) or not os.path.isabs(p):
        return False
    s = p.replace("/", "\\").lower()
    drive = os.path.splitdrive(s)[0]
    sys_drive = (os.environ.get("SystemDrive") or "C:").lower()
    if not drive or drive != sys_drive:
        return False
    home = os.path.expanduser("~").replace("/", "\\").lower()
    return (bool(home) and s.startswith(home)) or ("\\appdata\\" in s) \
        or ("\\programdata\\" in s) or ("\\users\\" in s)


def _vc_force_local_paths(settings):
    """把 settings 里仍指向系统盘的路径项改到软件文件夹。返回是否有改动。"""
    changed = False
    # 工作目录：无条件收敛到数据根下的 work-dir（上游用正斜杠存储）
    work_posix = os.path.join(vc_data_dir(), "work-dir").replace(os.sep, "/")
    save = settings.setdefault("Save", {})
    if str(save.get("Work_Dir", "")).replace("\\", "/") != work_posix:
        save["Work_Dir"] = work_posix
        changed = True
    # 转录模型目录：空值=用重定向后的 models 目录；若被指到系统盘则清空回默认
    fw = settings.get("FasterWhisper")
    if isinstance(fw, dict) and _path_on_system_drive(fw.get("ModelDir", "")):
        fw["ModelDir"] = ""
        changed = True
    # 字幕样式预览图若残留在系统盘历史目录，清空（样式参数本身保留）
    ss = settings.get("SubtitleStyle")
    if isinstance(ss, dict) and _path_on_system_drive(ss.get("PreviewImage", "")):
        ss["PreviewImage"] = ""
        changed = True
    return changed


def apply_global_llm_to_engine(ai_cfg=None):
    """把全局 AI 配置写入引擎的 OpenAI 兼容槽。

    v1.10.8 起字幕引擎不再保留独立 LLM 设置；v1.12.0 起全局 AI 合并为单通道
    （base_url / api_key / model 一套），工具箱、字幕引擎、AI 校准共用。
    同时若引擎 QConfig 已在本进程加载，把内存里的对应项一并改掉（免重启生效）。
    返回 (是否成功, 说明)。
    """
    try:
        ai = ai_cfg or ai_load_config()
        data = _vc_read_settings()
        llm = data.setdefault("LLM", {})
        if not bool(ai.get("enabled", True)):
            # 「启用 AI」已关闭：清空引擎 LLM 槽（含内存态）。引擎的优化
            # 会明确提示需配置 AI，而不是拿着历史注入的密钥偷偷消耗额度。
            wiped = False
            for k in ("OpenAI_API_Key", "OpenAI_API_Base", "OpenAI_Model"):
                if llm.get(k):
                    llm[k] = ""
                    wiped = True
            if wiped:
                _vc_write_settings(data)
            try:
                from videocaptioner.ui.common.config import cfg as _cfg
                _cfg.set(_cfg.openai_api_key, "")
            except Exception:
                pass
            return True, "AI 已关闭，未写入引擎 LLM 槽"
        base = str(ai.get("base_url") or "").strip()
        key = str(ai.get("api_key") or "").strip()
        model = str(ai.get("model") or "").strip()
        llm["LLMService"] = "OpenAI 兼容"
        if base:
            llm["OpenAI_API_Base"] = base
        if key:
            llm["OpenAI_API_Key"] = key
        if model:
            llm["OpenAI_Model"] = model
        _vc_write_settings(data)
        # 内存态同步（引擎界面已构建、QConfig 已导入时）
        try:
            from videocaptioner.ui.common.config import cfg as _cfg
            from videocaptioner.core.entities import LLMServiceEnum
            if base:
                _cfg.set(_cfg.openai_api_base, base)
            if key:
                _cfg.set(_cfg.openai_api_key, key)
            if model:
                _cfg.set(_cfg.openai_model, model)
            _cfg.set(_cfg.llm_service, LLMServiceEnum.OPENAI)
        except Exception:
            pass
        return True, "ok"
    except Exception as e:  # noqa: BLE001
        return False, str(e)


# ---------- 引擎「转录配置」：独立 ASR（自有服务 / 本地模型） ----------
# 引擎的转录模型是枚举项（B 接口 / J 接口 / Whisper [API] ✨ / FasterWhisper ✨），
# 这里把全局 ASR 配置映射过去：service → Whisper [API]（自有 ASR 服务），
# local → FasterWhisper ✨ + 独立模型名/目录。
#: FasterWhisper.Model 是枚举项，枚举外的自定义模型名写不进 settings.json
#: （读盘会被枚举校验拦下），只能靠 vc_asr_patch_apply() 在建任务时覆盖。
FW_MODEL_ENUM = ("tiny", "base", "small", "medium", "large-v1", "large-v2",
                 "large-v3", "large-v3-turbo")
#: 与 videocaptioner.core.entities.TranscribeModelEnum 的值保持一致
TM_WHISPER_API = "Whisper [API] ✨"
TM_FASTER_WHISPER = "FasterWhisper ✨"


def asr_local_override(ai_cfg=None):
    """本地独立 ASR 的覆盖参数：返回 (模型名, 模型目录)；非本地模式返回 None。"""
    try:
        ac = ai_mod().asr_config(ai_cfg or ai_load_config())
    except Exception:  # noqa: BLE001
        return None
    if ac.get("mode") != "local":
        return None
    model = str(ac.get("local_model") or "").strip()
    model_dir = str(ac.get("local_model_dir") or "").strip()
    if not model and not model_dir:
        return None
    return model, model_dir


def apply_asr_to_engine(ai_cfg=None):
    """把全局 ASR 配置写进引擎「转录配置」：转录模型 + WhisperAPI / FasterWhisper。

    service：WhisperAPI 槽写入自有 ASR 服务（地址/密钥/模型/提示词），转录模型切
      到 Whisper [API] ✨；local：转录模型切到 FasterWhisper ✨，模型名（枚举内）
      与模型目录写入 FasterWhisper 槽，枚举外的自定义模型由运行期补丁生效。
    返回 (是否成功, 说明)。
    """
    try:
        ac = ai_mod().asr_config(ai_cfg or ai_load_config())
        data = _vc_read_settings()
        changed = False
        want = TM_FASTER_WHISPER if ac["mode"] == "local" else TM_WHISPER_API
        tr = data.setdefault("Transcribe", {})
        if tr.get("TranscribeModel") != want:
            tr["TranscribeModel"] = want
            changed = True
        if ac["mode"] == "service":
            wa = data.setdefault("WhisperAPI", {})
            for k, v in (("WhisperApiBase", ac["base_url"]),
                         ("WhisperApiKey", ac["api_key"]),
                         ("WhisperApiModel", ac["model"]),
                         ("WhisperApiPrompt", ac["prompt"])):
                if v and wa.get(k) != v:
                    wa[k] = v
                    changed = True
        else:
            fw = data.setdefault("FasterWhisper", {})
            if ac["local_model"] in FW_MODEL_ENUM \
                    and fw.get("Model") != ac["local_model"]:
                fw["Model"] = ac["local_model"]
                changed = True
            if ac["local_model_dir"] \
                    and fw.get("ModelDir") != ac["local_model_dir"]:
                fw["ModelDir"] = ac["local_model_dir"]
                changed = True
        if changed:
            _vc_write_settings(data)
        # 内存态同步（引擎界面/QConfig 已加载时免重启生效）
        try:
            from videocaptioner.ui.common.config import cfg as _cfg
            from videocaptioner.core.entities import (FasterWhisperModelEnum,
                                                      TranscribeModelEnum)
            _cfg.set(_cfg.transcribe_model,
                     TranscribeModelEnum.FASTER_WHISPER if ac["mode"] == "local"
                     else TranscribeModelEnum.WHISPER_API)
            if ac["mode"] == "service":
                if ac["base_url"]:
                    _cfg.set(_cfg.whisper_api_base, ac["base_url"])
                if ac["api_key"]:
                    _cfg.set(_cfg.whisper_api_key, ac["api_key"])
                if ac["model"]:
                    _cfg.set(_cfg.whisper_api_model, ac["model"])
                if ac["prompt"]:
                    _cfg.set(_cfg.whisper_api_prompt, ac["prompt"])
            elif ac["local_model"] in FW_MODEL_ENUM:
                for m in FasterWhisperModelEnum:
                    if m.value == ac["local_model"]:
                        _cfg.set(_cfg.faster_whisper_model, m)
                        break
        except Exception:
            pass
        detail = (f"转录模型 → {'FasterWhisper（本地独立模型）' if ac['mode'] == 'local' else 'Whisper [API]（自有 ASR 服务）'}")
        return True, detail
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def vc_asr_patch_apply():
    """运行期补丁：让「独立 ASR 模型」真正生效（幂等，best-effort）。

    引擎的 TaskFactory.create_transcribe_task 把 faster_whisper_model_dir 硬编码
    成数据根 models 目录、模型名取自枚举项；本地独立模型（自定义模型名/模型目录，
    如自训练/微调的 faster-whisper 模型）必须在这里覆盖进 TranscribeConfig 才会
    被 used。service 模式不干预（引擎自己读 WhisperAPI 配置）。
    """
    try:
        from videocaptioner.ui import task_factory as _tf
    except Exception:  # noqa: BLE001
        return False
    if getattr(_tf, "_vt_asr_patched", False):
        return True
    orig = _tf.TaskFactory.create_transcribe_task

    def _patched(*args, **kwargs):
        task = orig(*args, **kwargs)
        try:
            ov = asr_local_override()
            if ov:
                model, model_dir = ov
                tcfg = getattr(task, "transcribe_config", None)
                if tcfg is not None:
                    if model:
                        tcfg.faster_whisper_model = model
                    if model_dir:
                        tcfg.faster_whisper_model_dir = model_dir
        except Exception:
            pass
        return task

    _tf.TaskFactory.create_transcribe_task = staticmethod(_patched)
    _tf._vt_asr_patched = True
    return True


def _vc_log(msg):
    """引擎侧运行期补丁日志（logs\\vc_fallback.log，best-effort）。"""
    try:
        os.makedirs(LOGS_DIR, exist_ok=True)
        with open(os.path.join(LOGS_DIR, "vc_fallback.log"), "a",
                  encoding="utf-8") as f:
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")
    except OSError:
        pass
    try:
        logger_note = msg  # noqa: F841  （保留给调试，不写标准输出）
    except Exception:
        pass


# ---------- v1.14.1：转录体验补丁（黑窗 / 下拉收敛 / 完成回填） ----------

def vc_pydub_nowindow_patch():
    """消掉「开启转录时闪黑色控制台窗口」（幂等，仅 Windows 生效）。

    根因：转录统一走 ChunkedASR，其 _split_audio() 必经 pydub 的
    AudioSegment.from_file()——pydub 内部裸调 ffprobe/ffmpeg 且不带
    CREATE_NO_WINDOW，GUI 进程下每次转录开始都会闪出黑色控制台窗口
    （分块导出 mp3、whisper_cpp 的 CLI 子进程同理）。引擎与 pydub 本体
    都不改：把 pydub / whisper_cpp 模块命名空间里的 subprocess 换成
    「默认补 CREATE_NO_WINDOW」的 shim，只影响这几个调用点。
    """
    if os.name != "nt":
        return True
    if getattr(subprocess, "_vt_nowindow", False):
        return True
    try:
        import types
        orig = subprocess.Popen

        def _popen(*args, **kwargs):
            try:
                if not kwargs.get("creationflags"):
                    kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            except Exception:
                pass
            return orig(*args, **kwargs)

        shim = types.ModuleType("subprocess_vt_nowindow_shim")
        shim.__dict__.update(subprocess.__dict__)
        shim.Popen = _popen
        patched = []
        try:
            import pydub.audio_segment as _pas
            _pas.subprocess = shim
            patched.append("pydub.audio_segment")
        except Exception:
            pass
        try:
            import pydub.utils as _pu          # from subprocess import Popen
            _pu.Popen = _popen
            patched.append("pydub.utils")
        except Exception:
            pass
        try:
            from videocaptioner.core.asr import whisper_cpp as _wc
            _wc.subprocess = shim
            patched.append("whisper_cpp")
        except Exception:
            pass
        subprocess._vt_nowindow = True
        subprocess._vt_nowindow_orig = orig
        _vc_log("黑窗隐藏补丁已挂：Popen shim → " + ", ".join(patched))
        return True
    except Exception as e:  # noqa: BLE001
        _vc_log(f"黑窗隐藏补丁失败：{e}")
        return False


#: 转录下拉显示名：「默认」= 引擎免费接口（B 接口）；「ASR」= 全局 ASR 配置
TM_DISPLAY_DEFAULT = "默认"
TM_DISPLAY_ASR = "ASR"


def vc_transcribe_ui_patch():
    """工作台转录下拉收敛为「默认 / ASR」+ 独立转录完成回填「字幕翻译」。

    v1.14.1 用户需求，全部运行期补丁（引擎 site-packages 保持原版）：
      ① 命令栏转录模型菜单只建「默认 / ASR」两项——J 接口 / FasterWhisper /
         WhisperCpp / Whisper [API] 不再出现；
      ② 选「ASR」时实时调 apply_asr_to_engine()（以全局设置「ASR 语音识别」
         卡片为准，按 asr_mode 落到 Whisper [API] / FasterWhisper）；
         选「默认」时落回 B 接口；历史残留取值一并收敛；
      ③ 引擎转录页自带的 Whisper API / FasterWhisper 配置块随下拉收敛
         不再可达（重复入口，从根上消除「与全局设置不一致」的两张页面），
         空位留一行提示；
      ④ 在转录页单独转录（拖入媒体，need_next_task=False）完成后，引擎原
         逻辑不做任何事——这里把生成的字幕装载进「字幕翻译」并自动切换
         过去（不自动开跑优化/翻译，等用户按「开始」）。
    幂等；必须在 HomeInterface 导入之后、实例构造之前调用。
    """
    try:
        from videocaptioner.ui.view import transcription_interface as ti
        from videocaptioner.ui.components import transcription_setting_card as tsc
        from videocaptioner.core.entities import TranscribeModelEnum
        from videocaptioner.ui.common.config import cfg as _cfg
        from qfluentwidgets import (Action, BodyLabel, FluentIcon, InfoBar,
                                    InfoBarPosition, RoundMenu)
        from PyQt5.QtWidgets import QVBoxLayout as _QVBox
    except Exception as e:  # noqa: BLE001
        _vc_log(f"转录 UI 补丁导入失败：{e}")
        return False
    if getattr(ti, "_vt_transcribe_ui_patched", False):
        return True

    def _asr_not_ready():
        """全局 ASR 是否还没配好（用于给出设置指引提示）。"""
        try:
            ac = ai_mod().asr_config(ai_load_config())
            if ac.get("mode") == "local":
                return not (ac.get("local_model") or ac.get("local_model_dir"))
            return not (ac.get("base_url") and ac.get("api_key"))
        except Exception:  # noqa: BLE001
            return False

    def _asr_missing_hint():
        """**已保存的**配置里缺什么 —— 说清楚，用户才知道该改哪一格。

        ⚠️ 读的是磁盘配置（不是界面输入框）：实测最常踩的坑是"设置页填好了
        但没点「保存并应用」"，这时磁盘上还是旧值/空值，转录页就说未配置。
        """
        try:
            ac = ai_mod().asr_config(ai_load_config())
            if ac.get("mode") == "local":
                if not (ac.get("local_model") or ac.get("local_model_dir")):
                    return "本地模式还没填模型名或目录"
                return ""
            miss = []
            if not ac.get("base_url"):
                miss.append("接口地址")
            if not ac.get("api_key"):
                miss.append("密钥")
            return ("已保存的配置里缺：" + "、".join(miss)) if miss else ""
        except Exception:  # noqa: BLE001
            return ""

    # ① 命令栏菜单：只留「默认 / ASR」
    orig_setup_bar = ti.TranscriptionInterface._setup_command_bar

    def _setup_command_bar(self):
        orig_setup_bar(self)
        try:
            menu = RoundMenu(parent=self)
            menu.addActions([
                Action(FluentIcon.GLOBE, TM_DISPLAY_DEFAULT),
                Action(FluentIcon.MICROPHONE, TM_DISPLAY_ASR),
            ])
            self.model_menu = menu          # _setup_signals 遍历的是这个菜单
            self.model_button.setMenu(menu)
        except Exception:  # noqa: BLE001
            pass

    ti.TranscriptionInterface._setup_command_bar = _setup_command_bar

    # ② 模型切换：显示名 ↔ 引擎枚举映射
    def _on_model_changed(self, model_name: str):
        # 防重入：cfg 信号 → 本槽 → cfg 信号 的环路在此截断
        if getattr(self, "_vt_model_busy", False):
            return
        try:
            asr_values = (TranscribeModelEnum.WHISPER_API.value,
                          TranscribeModelEnum.FASTER_WHISPER.value)
            if model_name == TM_DISPLAY_ASR:
                # 用户点了「ASR」：以全局「ASR 语音识别」设置为准实时同步
                self._vt_model_busy = True
                try:
                    self.model_button.setText(TM_DISPLAY_ASR)
                    self.transcription_setting_card.on_model_changed(
                        TM_DISPLAY_ASR)
                    ok, detail = apply_asr_to_engine()
                    if not ok:
                        _vc_log(f"ASR 应用失败：{detail}")
                    if _asr_not_ready():
                        InfoBar.warning(
                            "ASR 未配置",
                            ("%s；" % _asr_missing_hint() if _asr_missing_hint()
                             else "")
                            + "请到 设置 → ASR 语音识别 填好后点「保存并应用」"
                              "（只填不保存不生效）",
                            duration=8000, parent=self.window())
                finally:
                    self._vt_model_busy = False
                return
            if model_name == TM_DISPLAY_DEFAULT:
                # 用户点了「默认」：落回 B 接口
                self._vt_model_busy = True
                try:
                    self.model_button.setText(TM_DISPLAY_DEFAULT)
                    self.transcription_setting_card.on_model_changed(
                        TM_DISPLAY_DEFAULT)
                    _cfg.set(_cfg.transcribe_model, TranscribeModelEnum.BIJIAN)
                finally:
                    self._vt_model_busy = False
                return
            # 其余为启动恢复/signalBus 广播（传引擎枚举值）：只做显示映射，
            # 不回写配置，避免构造期触发配置环路
            if model_name in asr_values:
                self.model_button.setText(TM_DISPLAY_ASR)
                self.transcription_setting_card.on_model_changed(TM_DISPLAY_ASR)
            else:
                # 「B 接口」及被移除的历史取值（J 接口/WhisperCpp）→ 显示「默认」
                self.model_button.setText(TM_DISPLAY_DEFAULT)
                self.transcription_setting_card.on_model_changed(
                    TM_DISPLAY_DEFAULT)
                if model_name != TranscribeModelEnum.BIJIAN.value:
                    self._vt_model_busy = True
                    try:
                        _cfg.set(_cfg.transcribe_model,
                                 TranscribeModelEnum.BIJIAN)
                    finally:
                        self._vt_model_busy = False
        except Exception as e:  # noqa: BLE001
            self._vt_model_busy = False
            _vc_log(f"转录模型切换异常：{e}")

    ti.TranscriptionInterface.on_transcription_model_changed = _on_model_changed

    # ③ 独立转录完成 → 回填「字幕翻译」
    orig_finished = ti.TranscriptionInterface._on_transcript_finished

    def _home_of(widget):
        """沿 parent 链向上找 HomeInterface（判定标准：持有字幕翻译子界面）。

        ⚠️ 不能用 `self.parent()`：HomeInterface 构造时把各子界面
        `stackedWidget.addWidget(...)`，Qt 会顺手把父级改成那个
        QStackedWidget，于是 parent() 返回的是容器而不是 HomeInterface，
        `getattr(home, "subtitle_optimization_interface", None)` 恒为 None，
        整段回填被静默跳过（v1.14.1「转录完不自动跳字幕翻译」的根因）。
        这里逐级向上找，并以属性为准而非类名，宿主层级怎么改都不会再失联。
        """
        w = widget
        while w is not None:
            if getattr(w, "subtitle_optimization_interface", None) is not None:
                return w
            w = w.parent()
        # 兜底：宿主窗口里扫一遍（parent 链被重挂接打断时仍能找到）
        try:
            from PyQt5.QtWidgets import QApplication, QWidget as _QWidget
            for tl in QApplication.topLevelWidgets():
                if getattr(tl, "subtitle_optimization_interface", None) is not None:
                    return tl
                for ch in tl.findChildren(_QWidget):
                    if getattr(ch, "subtitle_optimization_interface",
                               None) is not None:
                        return ch
        except Exception:  # noqa: BLE001
            pass
        return None

    def _produced_subtitle(path):
        """定位转录产物：引擎按 output_format 落盘（base_path + 实际后缀），
        task.output_path 的后缀未必等于真实文件名，这里按同基名补齐。"""
        if not path:
            return None
        try:
            if os.path.isfile(path):
                return path
            base = os.path.splitext(path)[0]
            for ext in (".srt", ".ass", ".vtt"):
                cand = base + ext
                if os.path.isfile(cand):
                    return cand
            # 输出格式设成「全部」等自定义后缀时，同目录同基名的字幕文件
            d, stem = os.path.split(base)
            if os.path.isdir(d):
                for name in sorted(os.listdir(d)):
                    low = name.lower()
                    if (name.startswith(stem + ".")
                            and low.endswith((".srt", ".ass", ".vtt"))):
                        return os.path.join(d, name)
        except Exception:  # noqa: BLE001
            pass
        return None

    def _on_transcript_finished(self, task):
        try:
            if task is not None and not getattr(task, "need_next_task", False):
                out = _produced_subtitle(getattr(task, "output_path", None))
                home = _home_of(self) if out else None
                sub = (getattr(home, "subtitle_optimization_interface", None)
                       if home is not None else None)
                if sub is not None:
                    from videocaptioner.ui.task_factory import TaskFactory
                    st = TaskFactory.create_subtitle_task(
                        out, getattr(task, "file_path", None),
                        need_next_task=False,
                        task_id=getattr(home, "_current_task_id", None))
                    sub.set_task(st)
                    # 切到「字幕翻译」并让分段控件同步高亮（原生跳转同款两连）
                    home.stackedWidget.setCurrentWidget(sub)
                    home.pivot.setCurrentItem("SubtitleInterface")
                    _vc_log(f"独立转录完成 → 已装载「字幕翻译」：{out}")
                    InfoBar.success(
                        "转录完成",
                        "生成的字幕已装载到「字幕翻译」，可直接开始优化 / 翻译",
                        duration=5000,
                        position=InfoBarPosition.BOTTOM,
                        parent=home)
                    return
                if out:
                    _vc_log("独立转录完成，但未定位到工作台首页，回退引擎原逻辑")
        except Exception as e:  # noqa: BLE001
            _vc_log(f"转录完成回填异常：{e}")
        orig_finished(self, task)

    ti.TranscriptionInterface._on_transcript_finished = _on_transcript_finished

    # ④ 转录设置卡片空位提示（默认/ASR 都不再展示引擎内置 ASR 配置块）
    orig_card_init = tsc.TranscriptionSettingCard.__init__

    def _card_init(self, parent=None):
        orig_card_init(self, parent)
        try:
            lay = _QVBox(self.empty_widget)
            lay.setContentsMargins(24, 4, 24, 4)
            tip = BodyLabel(
                "默认：内置免费语音识别；ASR：使用设置页「ASR 语音识别」的模型"
                "（自有服务 / 本地模型），统一在全局设置中维护",
                self.empty_widget)
            tip.setStyleSheet("color: #8a8a8a;")
            lay.addWidget(tip)
            lay.addStretch(1)
        except Exception:  # noqa: BLE001
            pass

    tsc.TranscriptionSettingCard.__init__ = _card_init

    # ⑤ ASR 服务模式多协议适配（auto / openai / azure / dashscope）
    try:
        vc_asr_protocol_patch()
    except Exception:  # noqa: BLE001
        pass

    ti._vt_transcribe_ui_patched = True
    _vc_log("转录 UI 补丁已挂：下拉=默认/ASR，独立转录完成回填「字幕翻译」")
    return True


# ---------- v1.14.1 起：ASR 服务模式全协议适配 ----------

#: 支持的协议（= 配置里 asr_protocol 的取值；auto 为自动识别）
#: ⚠️ `dashscope` 是历史键：它其实就是 chat_audio 那一族（百炼兼容模式），
#:    保留是为了让老配置继续能用，新推断一律产出 `chat_audio`。
ASR_PROTOCOLS = ("auto", "openai", "azure", "chat_audio", "dashscope",
                 "deepgram", "elevenlabs", "gemini",
                 "volcengine", "assemblyai", "dashscope_realtime")

#: 协议说明（供界面下拉提示与日志引用）
ASR_PROTOCOL_NOTES = {
    "openai": "OpenAI Whisper 兼容（multipart /audio/transcriptions）——"
              "覆盖 OpenAI / 硅基流动 / Groq / Fireworks / DeepInfra / "
              "Mistral Voxtral / 自建 whisper.cpp、faster-whisper 服务等",
    "azure": "Azure OpenAI（deployments 端点 + api-key 头）",
    "chat_audio": "OpenAI 兼容 chat/completions + input_audio（音频以 Data URL "
                  "传入）——阿里云百炼 Qwen-ASR（qwen3-asr-flash）、"
                  "小米 MiMo（mimo-v2.5-asr）等",
    "dashscope": "同 chat_audio（历史键，保留兼容）",
    "deepgram": "Deepgram（POST /v1/listen，Authorization: Token + 原始音频，"
                "带词级时间轴）",
    "elevenlabs": "ElevenLabs Scribe（POST /v1/speech-to-text，xi-api-key，"
                  "带词级时间轴）",
    "gemini": "Google Gemini（generateContent + inline_data，返回纯文本，"
              "时间轴按句兜底）",
    "volcengine": "火山引擎（豆包）录音识别极速版——一次请求即返回，本地文件"
                  "直传；密钥填「APPID:AccessToken」或新版 API Key，"
                  "模型填 Resource ID（默认 volc.bigasr.auc_turbo）",
    "assemblyai": "AssemblyAI（上传 → 提交 → 轮询；Authorization 头**不带** "
                  "Bearer，模型名可逗号分隔多个做回退，带词级时间轴）",
    "dashscope_realtime": "百炼实时（WebSocket）——把本地音频切片推给 "
                          "wss://…/api-ws/v1/inference/，覆盖**只有实时形态**"
                          "的模型（fun-asr-flash-8k-realtime / fun-asr-realtime"
                          " / qwen3-asr-flash-realtime 等），带原生句级时间轴",
}

#: 实时（WebSocket 流式）模型的识别特征：这些模型**不能**一次性上传调用
ASR_REALTIME_HINTS = ("realtime", "-rt-", "streaming")


#: 「完整端点」的常见尾巴 —— 用户从服务商文档抄地址时容易连路径一起抄进来
ASR_ENDPOINT_TAILS = ("/audio/transcriptions", "/audio/translations",
                      "/chat/completions", "/v2/upload", "/v2/transcript")


def asr_strip_endpoint_tail(base, *tails):
    """削掉"用户把**完整端点**抄进地址栏"的那截尾巴。

    为什么要削：无论 OpenAI SDK 还是我们自己的拼接，都是「base + 固定路径」
    的写法，而服务商文档给的常常是完整 URL —— 例如智谱的
    `https://open.bigmodel.cn/api/paas/v4/audio/transcriptions`。照抄进去就会
    拼成 `.../audio/transcriptions/audio/transcriptions` → 404。
    宁可在这里削一次，也不该让用户对着 404 猜。

    不传 tails 时按 `ASR_ENDPOINT_TAILS` 里的常见端点尾巴削。
    """
    tails = tails or ASR_ENDPOINT_TAILS
    b = str(base or "").strip().rstrip("/")
    changed = True
    while changed and b:
        changed = False
        low = b.lower()
        for tail in tails:
            t = str(tail or "").strip().lower().rstrip("/")
            if t and low.endswith(t):
                b = b[: -len(t)].rstrip("/")
                changed = True
                break
    return b


def _infer_asr_protocol(base_url, model):
    """按地址与模型名推断协议（auto 档的唯一实现）。

    顺序有讲究：先认**域名独有的**服务（小米 MiMo / deepgram / elevenlabs /
    gemini），再认 Azure，最后才是"看着像 OpenAI 兼容"的兜底。

    ⚠️ 「chat/completions + input_audio」这族（百炼 Qwen-ASR、小米 MiMo ASR）
    必须与 `openai` 分开：这类服务**没有** `/audio/transcriptions` 端点，
    按 openai 协议去调只会 404（小米 MiMo 官方明确说明 ASR 走 chat completions）。
    """
    base = str(base_url or "").lower()
    mdl = str(model or "").lower()
    if "openspeech.bytedance.com" in base or "volcengine" in base:
        return "volcengine"
    if "assemblyai.com" in base:
        return "assemblyai"
    if ("aliyuncs.com" in base or "dashscope" in base) and any(
            h in mdl for h in ASR_REALTIME_HINTS):
        # 百炼系域名 + 实时模型：这类模型只有 WebSocket 形态 → 走实时协议。
        # （它们连 compatible-mode 的 chat/completions 都调不了，官方模型表
        #   标注「模式=即时、API=WebSocket」。）
        return "dashscope_realtime"
    if "deepgram.com" in base:
        return "deepgram"
    if "elevenlabs.io" in base:
        return "elevenlabs"
    if "generativelanguage.googleapis.com" in base:
        return "gemini"
    if ("openai.azure.com" in base or "/openai/deployments/" in base
            or "azure.com" in base):
        return "azure"
    if ("xiaomimimo.com" in base or "mimo-v2" in mdl
            or "compatible-mode" in base or "dashscope" in base
            or ("qwen" in mdl and ("audio" in mdl or "asr" in mdl))
            or "paraformer" in mdl or "fun-asr" in mdl):
        return "chat_audio"
    return "openai"


def asr_base_guard(base_url):
    """ASR 地址守卫：地址填成了「文本对话端点」时给出能照着改的提示。

    最常见的错误是把 Anthropic / chat 这类**只收文本**的端点当成 ASR 地址
    （音频走 multipart 或 input_audio，那些端点根本不收），表现就是五花八门
    的 404 / 415 —— 与其让用户对着状态码猜，不如直接说"该填什么"。
    """
    b = str(base_url or "").lower()
    if "anthropic" in b:
        return ("ASR 地址填的是 Anthropic 文本对话端点（%s）——它收不了音频。"
                "请改填 OpenAI 兼容端点：公共百炼 "
                "https://dashscope.aliyuncs.com/compatible-mode/v1，"
                "或专属实例的 …/compatible-mode/v1" % base_url)
    return ""


def asr_model_guard(model):
    """实时（流式）模型守卫：返回给用户看的提示，可放行时返回空串。

    ⚠️ 只在**非实时协议**下调用：实时模型在「百炼实时（WebSocket）」协议下
    是能正常出字幕的（_asr_dashscope_realtime_submit），不该被拦。
    """
    m = str(model or "").lower()
    if any(h in m for h in ASR_REALTIME_HINTS):
        return ("模型「%s」是实时（WebSocket 流式）语音识别，本协议用不了它。"
                "把「接口协议」改为「百炼实时（WebSocket）」（留自动识别也会"
                "选中），或改用录音文件识别模型：公共百炼 qwen3-asr-flash、"
                "硅基流动 FunAudioLLM/SenseVoiceSmall、OpenAI whisper-1" % model)
    return ""


def asr_protocol_of(ai_cfg=None):
    """解析 ASR 服务模式当前应使用的接口协议。

    显式协议直接用；auto 按 base_url 与模型名推断（与 tools\\ai_client.py
    resolve_asr_protocol 同一套规则，这里独立实现避免依赖 ai_mod 失败）。
    """
    try:
        ac = ai_mod().asr_config(ai_cfg or ai_load_config())
        p = str(ac.get("protocol") or "auto").strip().lower()
        if p in ("dashscope", "chat_audio"):
            return "chat_audio"      # 历史键归一到 chat_audio（两者同一实现）
        if p in ASR_PROTOCOLS and p != "auto":
            return p
        return _infer_asr_protocol(ac.get("base_url"), ac.get("model"))
    except Exception:  # noqa: BLE001
        pass
    # v1.14.2：ai_client 读取失败不再盲返 openai（实时模型经 OpenAI SDK 必断、
    # qwen-audio 族在 maas 无 /audio/transcriptions）——退一步直读磁盘配置推断。
    try:
        raw = ai_cfg if ai_cfg else ai_load_config()
    except Exception:  # noqa: BLE001
        raw = {}
    raw = raw or {}
    p = str(raw.get("asr_protocol") or "auto").strip().lower()
    if p in ("dashscope", "chat_audio"):
        return "chat_audio"
    if p in ASR_PROTOCOLS and p != "auto":
        return p
    return _infer_asr_protocol(str(raw.get("asr_base_url") or ""),
                               str(raw.get("asr_model") or ""))


def asr_examples(cfg=None):
    """生成当前 ASR 配置对应的**非流式**调用示例（curl + Python）。

    为什么要有它：设置页「测试 ASR 配置」失败时，或者要在别的程序 / 脚本里
    集成同一套服务时，用户需要一条**自己能跑通**的命令，用来区分"是我程序
    的问题"还是"密钥 / 账号 / 模型的问题"。示例里的请求与引擎 `_asr_*_submit`
    一一对应（同一端点、同样的头与 body 形态），跑通它即等于验证了本程序。

    密钥一律用环境变量占位，不把明文写进可复制文本。
    返回 dict(protocol, title, curl, python, env, notes)。
    """
    try:
        ac = ai_mod().asr_config(cfg or ai_load_config())
    except Exception:  # noqa: BLE001
        ac = {"mode": "service", "base_url": "", "model": "", "api_key": ""}
    mode = str(ac.get("mode") or "service")
    base = str(ac.get("base_url") or "").strip().rstrip("/")
    model = str(ac.get("model") or "").strip()
    proto = "local" if mode == "local" else asr_protocol_of(cfg)
    notes = ["非流式：一次请求（或上传→提交→轮询）返回完整结果，"
             "不是 WebSocket 实时流；实时模型（*realtime*）用不了这种调用。",
             "示例与程序内实现一一对应：跑通它 = 这套密钥/地址/模型可用。"]

    if proto == "local":
        return {
            "protocol": "local", "title": "本地 faster-whisper（不联网）",
            "env": {},
            "curl": "（本地模式不涉及 HTTP，没有 curl 示例）",
            "python": "\n".join([
                "from faster_whisper import WhisperModel",
                "",
                "model = WhisperModel(%r, device=\"auto\")   # 或模型目录" % (model or "large-v3"),
                "segments, info = model.transcribe(\"audio.mp3\", language=\"zh\")",
                "print(\"\".join(s.text for s in segments))",
            ]),
            "notes": notes + ["本地模型在本程序的「设置 → ASR 语音识别 → 本地独立模型」里配。"],
        }

    # ⚠️ 只给变量名与说明，**不把密钥明文写进可复制文本**（方便安全地
    #    贴文档 / 发同事；也让示例本身不因换密钥而失效）
    env = {"ASR_API_KEY": "设置页「ASR 密钥」里填的那个"}
    title = {
        "openai": "OpenAI Whisper 兼容", "azure": "Azure OpenAI",
        "chat_audio": "Chat 音频转写（百炼 Qwen-ASR / 小米 MiMo 等）",
        "dashscope": "Chat 音频转写（百炼 Qwen-ASR / 小米 MiMo 等）",
        "deepgram": "Deepgram",
        "elevenlabs": "ElevenLabs Scribe", "gemini": "Google Gemini",
        "volcengine": "火山引擎（豆包）录音识别极速版",
        "assemblyai": "AssemblyAI",
    }.get(proto, proto)

    if proto == "openai":
        sd_base = asr_strip_endpoint_tail(base or "https://api.openai.com/v1",
                                          "/audio/transcriptions",
                                          "/audio/translations")
        url = sd_base + "/audio/transcriptions"
        mdl = model or "whisper-1"
        curl = "\n".join([
            'curl -X POST "%s" \\' % url,
            '  -H "Authorization: Bearer $ASR_API_KEY" \\',
            '  -F "file=@audio.mp3" \\',
            '  -F "model=%s" \\' % mdl,
            '  -F "response_format=verbose_json" \\',
            '  -F "timestamp_granularities[]=word"',
        ])
        py = "\n".join([
            "import os",
            "from openai import OpenAI",
            "",
            "client = OpenAI(base_url=%r, api_key=os.environ[\"ASR_API_KEY\"])" % sd_base,
            "with open(\"audio.mp3\", \"rb\") as f:",
            "    r = client.audio.transcriptions.create(",
            "        model=%r, file=f, response_format=\"verbose_json\",  # 非流式" % mdl,
            "        timestamp_granularities=[\"word\"])",
            "print(r.text)",
        ])
    elif proto == "azure":
        res = base or "https://<你的资源名>.openai.azure.com"
        dep = model or "<部署名>"
        if "/openai/deployments/" in res:
            url = res if res.lower().endswith("/audio/transcriptions") else \
                res + "/audio/transcriptions"
        else:
            url = "%s/openai/deployments/%s/audio/transcriptions" % (res, dep)
        if "api-version=" not in url:
            url += "?api-version=2024-10-21"
        curl = "\n".join([
            'curl -X POST "%s" \\' % url,
            '  -H "api-key: $ASR_API_KEY" \\',
            '  -F "file=@audio.mp3" \\',
            '  -F "response_format=verbose_json"',
        ])
        py = "\n".join([
            "import os",
            "from openai import AzureOpenAI",
            "",
            "client = AzureOpenAI(azure_endpoint=%r, api_key=os.environ[\"ASR_API_KEY\"],"
            % res,
            "                       api_version=\"2024-10-21\")",
            "with open(\"audio.mp3\", \"rb\") as f:",
            "    r = client.audio.transcriptions.create(",
            "        model=%r, file=f, response_format=\"verbose_json\")   # 非流式" % dep,
            "print(r.text)",
        ])
    elif proto in ("chat_audio", "dashscope"):
        url = (base or "https://dashscope.aliyuncs.com/compatible-mode/v1") \
            + "/chat/completions"
        mdl = model or "qwen3-asr-flash"
        # body 用 python 现造：base64 的引号嵌套交给 shell 太脆，
        # 而且 base64 -w0 在 macOS 上不支持（GNU 专有参数）
        _body = ("python -c \"import base64,json;b=base64.b64encode("
                 "open('audio.mp3','rb').read()).decode();"
                 "print(json.dumps({'model':'%s','messages':[{'role':'user',"
                 "'content':[{'type':'input_audio','input_audio':{'data':"
                 "'data:audio/mp3;base64,'+b}}]}],'stream':False}))\"" % mdl)
        curl = "\n".join([
            "BODY=$(%s)" % _body,
            'curl -X POST "%s" \\' % url,
            '  -H "Authorization: Bearer $ASR_API_KEY" \\',
            '  -H "Content-Type: application/json" \\',
            '  -d "$BODY"',
        ])
        py = "\n".join([
            "import base64, os",
            "from openai import OpenAI",
            "",
            "client = OpenAI(base_url=%r, api_key=os.environ[\"ASR_API_KEY\"])"
            % (base or "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            "b64 = base64.b64encode(open(\"audio.mp3\", \"rb\").read()).decode()",
            "r = client.chat.completions.create(          # 非流式",
            "    model=%r," % mdl,
            "    messages=[{\"role\": \"user\", \"content\": [",
            "        {\"type\": \"input_audio\",",
            "         \"input_audio\": {\"data\": \"data:audio/mp3;base64,\" + b64}}]}],",
            "    stream=False)",
            "print(r.choices[0].message.content)",
        ])
        notes.append("音频走 input_audio 的 **Data URL**（自带 MIME）；"
                     "`stream=false` 才是非流式。")
        if "xiaomimimo" in base.lower() or "mimo" in mdl.lower():
            notes.append("小米 MiMo：ASR 也走 chat/completions（**没有** "
                         "/audio/transcriptions 端点，别填成 OpenAI Whisper 那样），"
                         "仅支持 mp3 / wav，返回纯文本（时间轴由本程序按句兜底）。")
    elif proto == "deepgram":
        b = base or "https://api.deepgram.com"
        url = b if b.lower().endswith("/listen") else \
            (b + "/listen" if b.lower().endswith("/v1") else b + "/v1/listen")
        mdl = model or "nova-3"
        curl = "\n".join([
            'curl -X POST "%s?model=%s&smart_format=true&language=zh-CN" \\'
            % (url, mdl),
            '  -H "Authorization: Token $ASR_API_KEY" \\',
            '  -H "Content-Type: audio/mp3" \\',
            '  --data-binary @audio.mp3',
        ])
        py = "\n".join([
            "import os",
            "import requests      # 官方 SDK（deepgram-sdk）各版本写法差异较大，",
            "                     # 这里给等价的裸 HTTP 版本，最稳",
            "r = requests.post(",
            "    %r," % (url + "?model=%s&smart_format=true&language=zh-CN" % mdl),
            "    headers={\"Authorization\": \"Token \" + os.environ[\"ASR_API_KEY\"],",
            "             \"Content-Type\": \"audio/mp3\"},",
            "    data=open(\"audio.mp3\", \"rb\").read(),   # 原始字节，不是 multipart",
            "    timeout=600)",
            "j = r.json()[\"results\"][\"channels\"][0][\"alternatives\"][0]",
            "print(j[\"transcript\"])",
            "for w in j.get(\"words\", []):        # 词级时间轴（秒）",
            "    print(w[\"start\"], w[\"end\"], w[\"word\"])",
        ])
        notes.append("鉴权头是 `Authorization: Token <key>`（不是 Bearer）；"
                     "音频以原始字节放在 body 里。")
    elif proto == "elevenlabs":
        b = base or "https://api.elevenlabs.io"
        url = b if b.lower().endswith("/speech-to-text") else b + "/v1/speech-to-text"
        mdl = model or "scribe_v1"
        curl = "\n".join([
            'curl -X POST "%s" \\' % url,
            '  -H "xi-api-key: $ASR_API_KEY" \\',
            '  -F "model_id=%s" \\' % mdl,
            '  -F "timestamps_granularity=word" \\',
            '  -F "file=@audio.mp3"',
        ])
        py = "\n".join([
            "import os",
            "from elevenlabs.client import ElevenLabs",
            "",
            "client = ElevenLabs(api_key=os.environ[\"ASR_API_KEY\"])",
            "with open(\"audio.mp3\", \"rb\") as f:",
            "    r = client.speech_to_text.convert(        # 非流式",
            "        model_id=%r, file=f, timestamps_granularity=\"word\")" % mdl,
            "print(r.text)",
        ])
    elif proto == "gemini":
        b = base or "https://generativelanguage.googleapis.com"
        mdl = model or "gemini-2.5-flash"
        url = "%s/v1beta/models/%s:generateContent" % (b, mdl)
        _body = ("python -c \"import base64,json;b=base64.b64encode("
                 "open('audio.mp3','rb').read()).decode();"
                 "print(json.dumps({'contents':[{'parts':[{'inline_data':"
                 "{'mime_type':'audio/mp3','data':b}},{'text':"
                 "'请把这段音频逐字转写为文本，只输出转写内容。'}]}]}))\"")
        curl = "\n".join([
            "BODY=$(%s)" % _body,
            'curl -X POST "%s" \\' % url,
            '  -H "x-goog-api-key: $ASR_API_KEY" \\',
            '  -H "Content-Type: application/json" \\',
            '  -d "$BODY"',
        ])
        py = "\n".join([
            "import base64, os",
            "from google import genai            # pip install google-genai",
            "",
            "client = genai.Client(api_key=os.environ[\"ASR_API_KEY\"])",
            "b64 = base64.b64encode(open(\"audio.mp3\", \"rb\").read()).decode()",
            "r = client.models.generate_content(        # 非流式",
            "    model=%r," % mdl,
            "    contents=[{\"inline_data\": {\"mime_type\": \"audio/mp3\", \"data\": b64}},",
            "              \"请把这段音频逐字转写为文本，只输出转写内容。\"])",
            "print(r.text)",
        ])
        notes.append("Gemini 返回纯文本、没有时间轴；本程序按句切分后再按句长占比"
                     "给出近似时间轴。")
    elif proto == "volcengine":
        url = (base or "https://openspeech.bytedance.com") + \
            ("" if base.endswith("/recognize/flash")
             else "/api/v3/auc/bigmodel/recognize/flash")
        res_id = model or VOLC_DEFAULT_RESOURCE
        env = {"VOLC_APP_ID": "控制台的 APP ID",
               "VOLC_ACCESS_KEY": "控制台的 Access Token"}
        _body = ("python -c \"import base64,json,os;b=base64.b64encode("
                 "open('audio.mp3','rb').read()).decode();"
                 "print(json.dumps({'user':{'uid':os.environ['VOLC_APP_ID']},"
                 "'audio':{'data':b},'request':{'model_name':'bigmodel',"
                 "'enable_punc':True,'show_utterances':True}}))\"")
        curl = "\n".join([
            "BODY=$(%s)" % _body,
            'curl -X POST "%s" \\' % url,
            '  -H "X-Api-App-Key: $VOLC_APP_ID" \\',
            '  -H "X-Api-Access-Key: $VOLC_ACCESS_KEY" \\',
            '  -H "X-Api-Resource-Id: %s" \\' % res_id,
            '  -H "X-Api-Request-Id: $(uuidgen)" \\',
            '  -H "X-Api-Sequence: -1" \\',
            '  -H "Content-Type: application/json" \\',
            '  -d "$BODY"',
        ])
        py = "\n".join([
            "import base64, json, os, uuid",
            "import requests        # 火山没有官方同步 Python SDK，这是等价实现",
            "",
            "r = requests.post(",
            "    %r," % url,
            "    headers={\"X-Api-App-Key\": os.environ[\"VOLC_APP_ID\"],",
            "             \"X-Api-Access-Key\": os.environ[\"VOLC_ACCESS_KEY\"],",
            "             \"X-Api-Resource-Id\": \"%s\"," % res_id,
            "             \"X-Api-Request-Id\": str(uuid.uuid4()),",
            "             \"X-Api-Sequence\": \"-1\",",
            "             \"Content-Type\": \"application/json\"},",
            "    data=json.dumps({\"user\": {\"uid\": os.environ[\"VOLC_APP_ID\"]},",
            "                     \"audio\": {\"data\": base64.b64encode(",
            "                         open(\"audio.mp3\", \"rb\").read()).decode()},",
            "                     \"request\": {\"model_name\": \"bigmodel\",",
            "                                 \"show_utterances\": True}}),",
            "    timeout=600)",
            "print(r.headers.get(\"X-Api-Status-Code\"))     # 20000000 = 成功（在响应头！）",
            "print(r.json()[\"result\"][\"text\"])",
        ])
        notes.append("状态码在**响应头** `X-Api-Status-Code`（`20000000` 为成功）；"
                     "新版控制台只有一个 API Key 时，把前两个头换成 "
                     "`X-Api-Key: $ASR_API_KEY`。")
    else:   # assemblyai
        b = base or "https://api.assemblyai.com"
        models = [x.strip() for x in (model or "").split(",") if x.strip()] \
            or list(ASSEMBLYAI_DEFAULT_MODELS)
        models_json = "[\"" + "\", \"".join(models) + "\"]"
        curl = "\n".join([
            "# 1) 上传本地文件（raw bytes，不是 multipart）",
            'UP=$(curl -s -X POST "%s/v2/upload" \\' % b,
            '  -H "authorization: $ASR_API_KEY" --data-binary @audio.mp3 | jq -r .upload_url)',
            "# 2) 提交转写任务",
            'ID=$(curl -s -X POST "%s/v2/transcript" \\' % b,
            '  -H "authorization: $ASR_API_KEY" -H "content-type: application/json" \\',
            "  -d '{\"audio_url\": \"'$UP'\", \"speech_models\": %s}' | jq -r .id)"
            % models_json,
            "# 3) 轮询到完成（非流式：结果一次性取回）",
            'while :; do',
            '  S=$(curl -s "%s/v2/transcript/$ID" -H "authorization: $ASR_API_KEY"' % b,
            "        | jq -r .status)",
            '  [ "$S" = "completed" ] && break; [ "$S" = "error" ] && break; sleep 3',
            'done',
            'curl -s "%s/v2/transcript/$ID" -H "authorization: $ASR_API_KEY" | jq -r .text' % b,
        ])
        py = "\n".join([
            "import os",
            "import assemblyai as aai           # pip install assemblyai",
            "",
            "aai.settings.api_key = os.environ[\"ASR_API_KEY\"]",
            "cfg = aai.TranscriptionConfig(speech_models=%r, language_detection=True)"
            % models,
            "t = aai.Transcriber().transcribe(\"audio.mp3\", config=cfg)   # 阻塞到完成",
            "print(t.text)",
            "for w in (t.words or []):          # 词级时间轴（毫秒）",
            "    print(w.start, w.end, w.text)",
        ])
        notes.append("鉴权头是 `authorization: <key>`（**不带 Bearer**）；"
                     "`speech_models` 必填（官方无默认值）；词级时间轴单位是**毫秒**。"
                     "curl 示例用到 jq（Windows 上直接看 Python 版即可）。")

    return {"protocol": proto, "title": title, "curl": curl, "python": py,
            "env": env, "notes": notes}


def asr_examples_text(cfg=None):
    """把 asr_examples() 拼成一份可直接给人看 / 另存的纯文本。"""
    ex = asr_examples(cfg)
    out = ["# %s（协议：%s）" % (ex["title"], ex["protocol"]), ""]
    if ex.get("env"):
        out.append("# 先设置环境变量：")
        for k, note in ex["env"].items():
            out.append("#   export %s='%s'" % (k, note))
        out.append("")
    out += ["# ---- curl（非流式）----", ex["curl"], "",
            "# ---- Python（非流式）----", ex["python"], "", "# 说明"]
    out += ["#  · " + n for n in ex.get("notes", [])]
    return "\n".join(out)


def _asr_audio_format(data: bytes) -> str:
    """按魔数识别音频容器（DashScope input_audio 需要显式 format）。"""
    head = bytes(data[:16]) if data else b""
    if head.startswith(b"RIFF") and head[8:12] == b"WAVE":
        return "wav"
    if head.startswith(b"ID3") or (len(head) > 2 and head[0] == 0xFF
                                   and (head[1] & 0xE0) == 0xE0):
        return "mp3"
    if head.startswith(b"OggS"):
        return "ogg"
    if head.startswith(b"fLaC"):
        return "flac"
    return "mp3"


def _asr_text_to_segments(text, duration_sec):
    """把无时间戳的纯文本识别结果按句切分并按时长占比分配时间轴。

    返回与引擎 WhisperAPI._make_segments 兼容的
    [{"text":…, "start":秒, "end":秒}, …]；文本为空返回空表。
    """
    import re
    text = str(text or "").strip()
    if not text:
        return []
    # 先按句末标点/换行切句，再把超长句按逗号级标点二次切
    pieces = [p for p in re.split(r"(?<=[。！？!?；;…])\s*|\n+", text) if p.strip()]
    refined = []
    for p in pieces:
        p = p.strip()
        if len(p) > 42:
            parts = [q for q in re.split(r"(?<=[，,、])", p) if q.strip()]
        else:
            parts = [p]
        refined.extend(parts)
    if not refined:
        refined = [text]
    weights = [max(len(s), 1) for s in refined]
    total = float(sum(weights))
    dur_ms = max(int(float(duration_sec or 0) * 1000), 1000)
    segs, t = [], 0
    for s, w in zip(refined, weights):
        d = int(dur_ms * w / total)
        segs.append({"text": s, "start": round(t / 1000.0, 3),
                     "end": round((t + d) / 1000.0, 3)})
        t += d
    if segs:
        segs[-1]["end"] = round(dur_ms / 1000.0, 3)
    return segs


def _asr_is_cjk(ch):
    return bool(ch) and ord(ch) > 0x2E7F


def _asr_join_words(tokens):
    """拼词成句：中文之间不加空格，拉丁词之间加。"""
    out = ""
    for t in tokens:
        if out and not _asr_is_cjk(out[-1]) and not _asr_is_cjk(t[:1]):
            out += " "
        out += t
    return out


def _asr_is_sentence_end(tok):
    """词尾是否句末（词级 ASR 的 punctuated_word 会带标点）。

    英文句点一律算句末 —— **不需要**给小数开特例：词级结果不会把 `3.5`
    切成 `3.` + `5`（`3.5` 的末位是 `5`，本来就落不进句点分支）。
    """
    if not tok:
        return False
    return tok[-1] in "。！？!?；;…."


def _asr_words_to_segments(words, max_gap=0.9, max_chars=42):
    """词级时间轴 → 句级 segments（Deepgram / ElevenLabs 用）。

    断句三条件：句末标点、停顿超过 max_gap 秒、当前句超长。这样拿到的是
    **原生时间轴**，比"按句时长占比猜"准得多。
    """
    segs, cur, start, end = [], [], None, None
    for w in words or []:
        tok = str(w.get("word") or w.get("text") or "").strip()
        if not tok:
            continue
        try:
            s = float(w.get("start") or 0)
            e = float(w.get("end") or s)
        except (TypeError, ValueError):
            continue
        if cur and (s - (end if end is not None else s) > max_gap
                    or sum(len(x) for x in cur) >= max_chars):
            segs.append({"text": _asr_join_words(cur),
                         "start": round(start or 0, 3),
                         "end": round(end if end is not None else s, 3)})
            cur, start = [], None
        if start is None:
            start = s
        cur.append(tok)
        end = e
        if _asr_is_sentence_end(tok):
            segs.append({"text": _asr_join_words(cur),
                         "start": round(start, 3), "end": round(end, 3)})
            cur, start = [], None
    if cur:
        segs.append({"text": _asr_join_words(cur),
                     "start": round(start or 0, 3), "end": round(end or 0, 3)})
    return segs


def _asr_words_response(text, words):
    """统一成 {text, segments, words}：引擎两条消费路径（句级 / 词级）都能吃。"""
    clean = []
    for w in words or []:
        tok = str(w.get("word") or w.get("text") or "").strip()
        if not tok:
            continue
        try:
            s = float(w.get("start") or 0)
            e = float(w.get("end") or s)
        except (TypeError, ValueError):
            continue
        clean.append({"word": tok, "start": s, "end": e})
    out = {"text": str(text or ""), "segments": _asr_words_to_segments(clean)}
    if clean:
        out["words"] = clean
    return out


def _asr_err_hint(resp):
    """把 HTTP 错误响应转成"能照着修"的提示（密钥 / 模型名 / 其它）。"""
    text = ""
    try:
        text = (resp.text or "")[:300]
    except Exception:  # noqa: BLE001
        pass
    low = text.lower()
    if resp.status_code in (401, 403):
        return ("HTTP %d（密钥被拒：确认密钥属于这个服务/实例，并且在设置页按过"
                "「保存并应用」）: %s" % (resp.status_code, text))
    if "too large" in low or "file size" in low:
        # v1.14.2：百炼多模态端点对单次请求内嵌音频有体积上限，整段直传
        # （尤其降级 qwen3-asr-flash 时）会撞 This Multimodal file size is
        # too large——提示必须给"切短/压缩"出路，且不能被下面的实时误判分支吞掉。
        return ("HTTP %d（音频体积超过该端点单次上限：程序会自动把超限音频压成"
                "低码率 MP3 再传，仍超限说明音频太长——请把音频切短分段后分别转录，"
                "或改用支持大文件的服务端点）: %s" % (resp.status_code, text))
    if "too long" in low:
        return ("HTTP %d（音频时长超过该端点单次上限：程序会自动对半切分重试，"
                "仍失败则请把音频切短分段，或换支持长音频的模型）: %s"
                % (resp.status_code, text))
    if ("invalidparameter" in low or "invalid parameter" in low
            or "model not" in low or "unsupported" in low):
        return ("HTTP %d（参数或模型名不被该端点支持——注意实时（realtime）"
                "模型不能一次性上传调用）: %s" % (resp.status_code, text))
    return "HTTP %d: %s" % (resp.status_code, text)


def _asr_normalize_resp(resp, asr_obj):
    """把各协议响应归一成引擎 _make_segments 可解析的 dict。

    已含 segments/words（带原生时间轴）→ 原样返回；纯文本/仅 text →
    按句切分 + 时长占比生成近似时间轴（无时间戳协议的兜底）。
    """
    if isinstance(resp, dict) and ("segments" in resp or "words" in resp):
        return resp
    if isinstance(resp, dict):
        text = str(resp.get("text") or "")
    else:
        text = str(resp or "")
    return {"text": text,
            "segments": _asr_text_to_segments(text, getattr(asr_obj,
                                                            "audio_duration",
                                                            0))}


def _asr_azure_submit(asr_obj):
    """Azure OpenAI 语音转文字：POST …/deployments/<部署>/audio/transcriptions。

    地址允许填资源根或填到 deployments/<部署名>（自动补齐路径与 api-version），
    鉴权用 api-key 头（与 LLM 的 Azure 适配同一套约定）。
    """
    import requests
    base = (asr_obj.base_url or "").strip().rstrip("/")
    model = (asr_obj.model or "").strip()
    if "/openai/deployments/" not in base.lower():
        base = f"{base}/openai/deployments/{model}" if model else \
            f"{base}/openai/deployments"
    low = base.lower()
    if not low.endswith("/audio/transcriptions"):
        base = base + "/audio/transcriptions"
    if "api-version=" not in base:
        base = f"{base}{'&' if '?' in base else '?'}api-version=2024-10-21"
    fmt = _asr_audio_format(asr_obj.file_binary or b"")
    form = {"response_format": "verbose_json"}
    if asr_obj.language:
        form["language"] = asr_obj.language
    if asr_obj.prompt:
        form["prompt"] = asr_obj.prompt
    r = requests.post(
        base, headers={"api-key": asr_obj.api_key}, data=form,
        files={"file": (f"audio.{fmt}", asr_obj.file_binary or b"",
                        f"audio/{fmt}")},
        timeout=300)
    if r.status_code != 200:
        raise RuntimeError(f"Azure ASR HTTP {r.status_code}: {r.text[:200]}")
    try:
        return r.json()
    except ValueError:
        return {"text": r.text}


#: 多模态请求（chat_audio 的 Data URL / gemini 的 inline_data）内嵌音频的
#: 原始字节上限：base64 会再放大约 4/3，6.5MB 原始 ≈ 8.7MB 编码后，贴着百炼
#: compatible-mode 多模态请求体上限留余量。超限先压缩，再不行由服务端报体积错。
ASR_INLINE_AUDIO_MAX_RAW = 6_500_000

#: "audio is too long" 自动对半切分的最大递归层数（2^3=8 段封顶，防无限拆）
ASR_SPLIT_MAX_DEPTH = 3


def _asr_shrink_audio_blob(blob, max_raw_bytes):
    """超过内嵌上限的音频 → ffmpeg 压成低码率单声道 MP3（v1.14.2）。

    chat_audio / gemini 这类"音频进 JSON"的协议，原始文件直接 base64 会撑爆
    请求体上限（百炼报 Multimodal file size is too large）。语音识别对码率不
    敏感，32k/16k 单声道 MP3 足够。任何一步失败（无 ffmpeg/解码失败/越压越大）
    都**原样返回**，让服务端回它自己的错误码——绝不把用户音频弄丢或弄坏。
    """
    blob = blob or b""
    if len(blob) <= max_raw_bytes:
        return blob
    try:
        ffmpeg, _ffprobe = ensure_ffmpeg()
    except Exception:  # noqa: BLE001
        ffmpeg = ""
    if not ffmpeg:
        return blob
    import subprocess as _sp
    import tempfile as _tf
    src = dst = ""
    try:
        with _tf.NamedTemporaryFile(suffix="." + _asr_audio_format(blob),
                                    delete=False) as tf:
            tf.write(blob)
            src = tf.name
        dst = src + ".shrink.mp3"
        for br in ("48k", "32k", "16k"):
            try:
                os.unlink(dst)
            except OSError:
                pass
            _sp.run([ffmpeg, "-y", "-i", src, "-vn", "-ac", "1",
                     "-b:a", br, dst],
                    capture_output=True, check=True, timeout=300,
                    creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0)
                    if os.name == "nt" else 0)
            data = open(dst, "rb").read()
            if data and len(data) <= max_raw_bytes:
                return data
        return blob          # 压到底仍超限/全部失败：原样交给服务端判
    except Exception:  # noqa: BLE001 非音频坏数据或 ffmpeg 报错
        return blob
    finally:
        for p in (src, dst):
            if p:
                try:
                    os.unlink(p)
                except OSError:
                    pass


def _asr_split_audio_blob(blob):
    """按中点切成（前半, 后半）两段 wav；切不了返回 None（v1.14.2）。

    服务端回 "The audio is too long" 时的自动补救：单请求超长 ⇒ 对半切开分别
    提交、文本顺序拼回（时间轴由本程序按段占比近似，见 _asr_normalize_resp）。
    """
    if not blob:
        return None
    try:
        ffmpeg, ffprobe = ensure_ffmpeg()
    except Exception:  # noqa: BLE001
        return None
    if not ffmpeg or not ffprobe:
        return None
    import json as _json
    import subprocess as _sp
    import tempfile as _tf
    src = o1 = o2 = ""
    try:
        with _tf.NamedTemporaryFile(suffix="." + _asr_audio_format(blob),
                                    delete=False) as tf:
            tf.write(blob)
            src = tf.name
        pr = _sp.run([ffprobe, "-v", "error", "-show_entries",
                      "format=duration", "-of", "json", src],
                     capture_output=True, text=True, timeout=60,
                     creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0)
                     if os.name == "nt" else 0)
        dur = float((_json.loads(pr.stdout or "{}")
                     .get("format") or {}).get("duration") or 0)
        if dur < 2:
            return None                       # 太短不值得切
        half = dur / 2.0
        o1, o2 = src + ".a.wav", src + ".b.wav"
        _sp.run([ffmpeg, "-y", "-i", src, "-t", "%.3f" % half,
                 "-vn", "-ac", "1", o1],
                capture_output=True, check=True, timeout=300,
                creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0)
                if os.name == "nt" else 0)
        _sp.run([ffmpeg, "-y", "-i", src, "-ss", "%.3f" % half,
                 "-vn", "-ac", "1", o2],
                capture_output=True, check=True, timeout=300,
                creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0)
                if os.name == "nt" else 0)
        a = open(o1, "rb").read()
        b = open(o2, "rb").read()
        return (a, b) if a and b else None
    except Exception:  # noqa: BLE001
        return None
    finally:
        for p in (src, o1, o2):
            if p:
                try:
                    os.unlink(p)
                except OSError:
                    pass


def _asr_chat_audio_submit(asr_obj, depth=0):
    """Chat 音频转写（OpenAI 兼容 chat/completions + input_audio）：

    POST {base}/chat/completions，音频以 input_audio 进多模态 messages。
    这一族目前包括：**阿里云百炼** Qwen-ASR（qwen3-asr-flash / qwen-audio-asr，
    含 maas 专属实例）、**小米 MiMo**（mimo-v2.5-asr）。

    ⚠️ `data` 必须是 **Data URL**（`data:audio/mp3;base64,…`）：两家官方示例
    都是这个形态，它自带 MIME、不必再给 format；只发裸 base64 会被判成无效
    音频。⚠️ 这些服务**没有** `/audio/transcriptions` 端点，别按 openai 协议调。
    ⚠️ 音频格式支持有限（百炼/MiMo 都主打 mp3、wav），其它容器请先转码。
    """
    import base64
    import requests
    base = (asr_obj.base_url or "").strip().rstrip("/")
    if not base.lower().endswith("/chat/completions"):
        base = base + "/chat/completions"
    # v1.14.2：整段直传是「Multimodal file size is too large」的头号来源
    # （尤其实时模型断连后自动降级 qwen3-asr-flash 走的就是这条路）——
    # 超过内嵌上限先压成低码率 MP3 再进 Data URL。
    blob = _asr_shrink_audio_blob(asr_obj.file_binary or b"",
                                  ASR_INLINE_AUDIO_MAX_RAW)
    fmt = _asr_audio_format(blob)
    b64 = base64.b64encode(blob).decode("ascii")
    content = [{"type": "input_audio",
                "input_audio": {"data": "data:audio/%s;base64,%s" % (fmt, b64)}}]
    if asr_obj.prompt:
        content.append({"type": "text", "text": asr_obj.prompt})
    body = {"model": asr_obj.model,
            "messages": [{"role": "user", "content": content}],
            "stream": False}
    lang = str(getattr(asr_obj, "language", "") or "").strip()
    if lang and lang not in ("auto", "zh"):
        body["asr_options"] = {"language": lang}
    r = requests.post(
        base, json=body,
        headers={"Authorization": "Bearer " + asr_obj.api_key,
                 "Content-Type": "application/json"},
        timeout=600)
    if r.status_code != 200:
        low = (r.text or "").lower()
        if ("too long" in low or "duration" in low) \
                and depth < ASR_SPLIT_MAX_DEPTH:
            halves = _asr_split_audio_blob(blob)
            if halves:
                import types as _types
                parts = []
                for hb in halves:
                    sub = _types.SimpleNamespace(
                        base_url=asr_obj.base_url, model=asr_obj.model,
                        api_key=asr_obj.api_key,
                        language=getattr(asr_obj, "language", ""),
                        prompt=getattr(asr_obj, "prompt", ""),
                        file_binary=hb)
                    parts.append(_asr_chat_audio_submit(sub, depth + 1))
                return "".join(parts)
        if "too long" in low or "duration" in low:
            raise RuntimeError(
                "ASR 服务：音频时长超限且自动切分重试已到底（不再继续切短），"
                "请把音频切短分段后分别转录，或换支持长音频的模型。"
                "原始错误：" + _asr_err_hint(r))
        raise RuntimeError("ASR 服务 " + _asr_err_hint(r))
    try:
        data = r.json()
        cont = data["choices"][0]["message"].get("content")
        if isinstance(cont, list):        # 多模态响应可能是 [{text:…}]
            cont = "".join(str(x.get("text") or "") for x in cont
                           if isinstance(x, dict))
        return str(cont or "")
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"ASR 响应格式无法解析：{e}; body={r.text[:200]}")


#: 历史名（可能出现在旧配置 / 日志 / 自检里）：两个名字指同一实现
_asr_dashscope_submit = _asr_chat_audio_submit


def _asr_deepgram_submit(asr_obj):
    """Deepgram 预录音频识别：POST {base}/v1/listen，原始音频字节 + Token 头。

    地址允许填 https://api.deepgram.com 或填到 /v1（自动补 /listen）。
    响应带词级时间轴（results.channels[0].alternatives[0].words），
    这里聚合成句级 segments 交给引擎。
    """
    import requests
    b = (asr_obj.base_url or "").strip().rstrip("/") or "https://api.deepgram.com"
    low = b.lower()
    if low.endswith("/listen"):
        url = b
    elif low.endswith("/v1"):
        url = b + "/listen"
    else:
        url = b + "/v1/listen"
    fmt = _asr_audio_format(asr_obj.file_binary or b"")
    params = {"model": (asr_obj.model or "nova-3"),
              "smart_format": "true", "punctuate": "true"}
    lang = str(getattr(asr_obj, "language", "") or "").strip()
    if lang and lang not in ("auto", "zh"):
        params["language"] = lang
    elif lang == "zh":
        params["language"] = "zh-CN"
    r = requests.post(
        url, params=params, data=asr_obj.file_binary or b"",
        headers={"Authorization": "Token " + asr_obj.api_key,
                 "Content-Type": "audio/%s" % fmt},
        timeout=600)
    if r.status_code != 200:
        raise RuntimeError("ASR 服务 " + _asr_err_hint(r))
    try:
        alt = r.json()["results"]["channels"][0]["alternatives"][0]
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"ASR 响应格式无法解析：{e}; body={r.text[:200]}")
    return _asr_words_response(
        alt.get("transcript") or "",
        [{"word": w.get("punctuated_word") or w.get("word"),
          "start": w.get("start"), "end": w.get("end")}
         for w in (alt.get("words") or [])])


def _asr_elevenlabs_submit(asr_obj):
    """ElevenLabs Scribe：POST {base}/v1/speech-to-text（multipart + xi-api-key）。

    响应 {text, words:[{text,start,end}], language_code} —— 同样聚合成句级。
    """
    import requests
    b = (asr_obj.base_url or "").strip().rstrip("/") or "https://api.elevenlabs.io"
    url = b if b.lower().endswith("/speech-to-text") else b + "/v1/speech-to-text"
    fmt = _asr_audio_format(asr_obj.file_binary or b"")
    form = {"model_id": (asr_obj.model or "scribe_v1"),
            "timestamps_granularity": "word"}
    lang = str(getattr(asr_obj, "language", "") or "").strip()
    if lang and lang not in ("auto", "zh"):
        form["language_code"] = lang
    r = requests.post(
        url, data=form,
        files={"file": ("audio.%s" % fmt, asr_obj.file_binary or b"",
                        "audio/%s" % fmt)},
        headers={"xi-api-key": asr_obj.api_key},
        timeout=600)
    if r.status_code != 200:
        raise RuntimeError("ASR 服务 " + _asr_err_hint(r))
    try:
        data = r.json()
    except ValueError as e:
        raise RuntimeError(f"ASR 响应格式无法解析：{e}; body={r.text[:200]}")
    return _asr_words_response(
        data.get("text") or "",
        [{"word": w.get("text") or w.get("word"),
          "start": w.get("start"), "end": w.get("end")}
         for w in (data.get("words") or [])])


def _asr_gemini_submit(asr_obj):
    """Google Gemini 多模态音频理解：POST models/<model>:generateContent。

    返回纯文本（无时间轴），由 _asr_normalize_resp 按句切分兜底；提示词优先
    用用户填的「识别提示词」，没填就给一句"逐字转写"的指令。
    """
    import base64
    import requests
    b = (asr_obj.base_url or "").strip().rstrip("/") \
        or "https://generativelanguage.googleapis.com"
    model = (asr_obj.model or "gemini-2.5-flash").strip()
    url = "%s/v1beta/models/%s:generateContent" % (b, model)
    # v1.14.2：与 chat_audio 同理，inline_data 的体积上限先压缩再编码
    blob = _asr_shrink_audio_blob(asr_obj.file_binary or b"",
                                  ASR_INLINE_AUDIO_MAX_RAW)
    fmt = _asr_audio_format(blob)
    b64 = base64.b64encode(blob).decode("ascii")
    instruction = (getattr(asr_obj, "prompt", "") or "").strip() \
        or "请把这段音频逐字转写为文本，只输出转写内容，不要加解释或标注。"
    body = {"contents": [{"parts": [
        {"inline_data": {"mime_type": "audio/%s" % fmt, "data": b64}},
        {"text": instruction}]}]}
    r = requests.post(url, json=body,
                      headers={"x-goog-api-key": asr_obj.api_key,
                               "Content-Type": "application/json"},
                      timeout=600)
    if r.status_code != 200:
        raise RuntimeError("ASR 服务 " + _asr_err_hint(r))
    try:
        parts = r.json()["candidates"][0]["content"]["parts"]
        return "".join(str(p.get("text") or "") for p in parts)
    except (ValueError, KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"ASR 响应格式无法解析：{e}; body={r.text[:200]}")


#: 火山（豆包）录音识别极速版默认资源 ID
VOLC_DEFAULT_RESOURCE = "volc.bigasr.auc_turbo"

#: AssemblyAI 默认模型（官方的 speech_models 必填，没有默认值）
ASSEMBLYAI_DEFAULT_MODELS = ("universal-3-pro", "universal-2")


def _asr_volcengine_submit(asr_obj):
    """火山引擎（豆包）录音文件识别**极速版**：一次请求即返回，无需轮询。

    鉴权两种形态都吃（零配置改动）：
      · 新版控制台：`api_key` 填 API Key → 走 `X-Api-Key`；
      · 旧版控制台：`api_key` 填 `APPID:AccessToken`（冒号分隔）→ 走
        `X-Api-App-Key` + `X-Api-Access-Key`。
    `model` 填 Resource ID（默认 `volc.bigasr.auc_turbo`）。
    ⚠️ 状态码在**响应头** `X-Api-Status-Code`（`20000000` = OK），不在 body；
    `show_utterances=true` 才有时间轴（毫秒 → 秒）。
    """
    import base64
    import json
    import uuid
    import requests
    base = (asr_obj.base_url or "").strip().rstrip("/") \
        or "https://openspeech.bytedance.com"
    url = base if base.endswith("/recognize/flash") else \
        base + "/api/v3/auc/bigmodel/recognize/flash"
    key = str(asr_obj.api_key or "")
    headers = {"Content-Type": "application/json",
               "X-Api-Resource-Id": (asr_obj.model or VOLC_DEFAULT_RESOURCE),
               "X-Api-Request-Id": str(uuid.uuid4()),
               "X-Api-Sequence": "-1"}
    uid = ""
    if ":" in key:
        uid, _, acc = key.partition(":")
        headers["X-Api-App-Key"] = uid.strip()
        headers["X-Api-Access-Key"] = acc.strip()
    else:
        headers["X-Api-Key"] = key
    body = {"user": {"uid": uid or key},
            "audio": {"data": base64.b64encode(
                asr_obj.file_binary or b"").decode("ascii")},
            "request": {"model_name": "bigmodel", "enable_itn": True,
                        "enable_punc": True, "show_utterances": True}}
    lang = str(getattr(asr_obj, "language", "") or "").strip()
    if lang and lang not in ("auto", "zh"):
        body["request"]["language"] = lang
    r = requests.post(url, data=json.dumps(body, ensure_ascii=False),
                      headers=headers, timeout=600)
    code = r.headers.get("X-Api-Status-Code", "")
    if r.status_code != 200 or (code and code != "20000000"):
        raise RuntimeError("ASR 服务 " + _asr_err_hint(r)
                           + "（X-Api-Status-Code=%s %s）"
                           % (code or r.status_code,
                              r.headers.get("X-Api-Message", "")))
    try:
        res = (r.json() or {}).get("result") or {}
    except ValueError as e:
        raise RuntimeError(f"ASR 响应格式无法解析：{e}; body={r.text[:200]}")
    utts = res.get("utterances") or []
    ms = 1000.0
    if any(u.get("words") for u in utts):
        words = []
        for u in utts:
            for w in u.get("words") or []:
                words.append({
                    "word": w.get("text"),
                    "start": float(w.get("start_time") or 0) / ms,
                    "end": float(w.get("end_time") or 0) / ms})
        return _asr_words_response(res.get("text") or "", words)
    if utts:
        segs = [{"text": (u.get("text") or "").strip(),
                 "start": round(float(u.get("start_time") or 0) / ms, 3),
                 "end": round(float(u.get("end_time") or 0) / ms, 3)}
                for u in utts if (u.get("text") or "").strip()]
        return {"text": res.get("text") or "", "segments": segs}
    return res.get("text") or ""


def _asr_assemblyai_submit(asr_obj):
    """AssemblyAI：上传本地文件 → 提交任务 → 轮询结果（三步，异步）。

    ⚠️ 三个易错点：鉴权头是 `Authorization: <key>`（**没有 Bearer 前缀**）；
    `speech_models` 必填（不填直接报错，官方没有默认值）；词级时间轴单位是
    **毫秒**（别当秒用）。`model` 支持逗号分隔多个模型做回退。
    """
    import time
    import requests
    base = asr_strip_endpoint_tail(asr_obj.base_url, "/v2/upload",
                                   "/v2/transcript") \
        or "https://api.assemblyai.com"
    headers = {"authorization": str(asr_obj.api_key or "").strip()}
    # 1) 上传：必须是 raw bytes（不发 multipart，否则下游 Transcoding failed）
    up = requests.post(base + "/v2/upload", data=asr_obj.file_binary or b"",
                       headers=headers, timeout=600)
    if up.status_code != 200:
        raise RuntimeError("ASR 服务 上传失败 " + _asr_err_hint(up))
    try:
        audio_url = up.json()["upload_url"]
    except (ValueError, KeyError, TypeError) as e:
        raise RuntimeError(f"上传响应异常：{e}; body={up.text[:200]}")
    # 2) 提交
    models = [m.strip() for m in str(asr_obj.model or "").split(",")
              if m.strip()] or list(ASSEMBLYAI_DEFAULT_MODELS)
    payload = {"audio_url": audio_url, "speech_models": models}
    lang = str(getattr(asr_obj, "language", "") or "").strip()
    if lang and lang not in ("auto", "zh"):
        payload["language_code"] = lang
    else:
        payload["language_detection"] = True
    if getattr(asr_obj, "prompt", ""):
        payload["prompt"] = asr_obj.prompt
    sub = requests.post(base + "/v2/transcript", json=payload, headers=headers,
                        timeout=120)
    if sub.status_code != 200:
        raise RuntimeError("ASR 服务 " + _asr_err_hint(sub))
    try:
        tid = (sub.json() or {}).get("id")
    except ValueError as e:
        raise RuntimeError(f"提交响应异常：{e}; body={sub.text[:200]}")
    if not tid:
        raise RuntimeError("提交未返回 transcript id：%s" % sub.text[:200])
    # 3) 轮询（官方建议 3 秒一次；20 分钟上限，避免任务卡死时无限等）
    url = base + "/v2/transcript/" + str(tid)
    for _ in range(400):
        time.sleep(3)
        got = requests.get(url, headers=headers, timeout=60)
        if got.status_code != 200:
            raise RuntimeError("ASR 服务 查询失败 " + _asr_err_hint(got))
        data = got.json() or {}
        state = data.get("status")
        if state == "completed":
            words = [{"word": w.get("text"),
                      "start": float(w.get("start") or 0) / 1000.0,
                      "end": float(w.get("end") or 0) / 1000.0}
                     for w in (data.get("words") or [])]
            if words:
                return _asr_words_response(data.get("text") or "", words)
            return data.get("text") or ""
        if state == "error":
            raise RuntimeError("ASR 任务失败：" + str(data.get("error"))[:200])
    raise RuntimeError("ASR 任务超时（轮询 20 分钟仍未完成）")


def _asr_ws_url(base_url):
    """从「接口地址」推导百炼实时 ASR 的 WebSocket 端点。

    · 留空 / dashscope 公共 → wss://dashscope.aliyuncs.com/api-ws/v1/inference/
    · 专属实例（https://xxx.cn-beijing.maas.aliyuncs.com/…）→ 同域名换 wss，
      API 路径与公共端点一致（/api-ws/v1/inference/）
    · 用户直接填 wss://… → 尊重原样，只在缺路径时补 /api-ws/v1/inference/
    """
    b = str(base_url or "").strip().rstrip("/")
    if not b:
        return "wss://dashscope.aliyuncs.com/api-ws/v1/inference/"
    if b.lower().startswith(("wss://", "ws://")):
        low = b.lower()
        if low.endswith("/inference/"):
            return b
        if low.endswith("/inference"):
            return b + "/"
        return b + "/api-ws/v1/inference/"
    if b.lower().startswith("https://"):
        host = b[8:]
    elif b.lower().startswith("http://"):
        host = b[7:]
    else:
        host = b
    host = host.strip("/")
    if "/" in host:                       # 只取域名，路径一律换成 API 路径
        host = host.split("/", 1)[0]
    return "wss://%s/api-ws/v1/inference/" % host


#: 实时 ASR 的音频帧大小。官方示例按 100ms/3200 字节（16k/16bit）模拟实时，
#: 但批量转录要的是"尽快灌完"——64KB 一帧不 sleep，一小时音频几十秒发完；
#: 服务端按到达顺序处理，不需要对齐真实时间。
ASR_WS_FRAME_BYTES = 65536

#: 实时 ASR 推流倍速（相对 16bit 单声道 PCM 的实时字节率）。
#: ⚠️ 全速灌发实测会被服务端掐断连接（Connection to remote host was lost）：
#: 实时识别服务端按流式消费音频，输入速率远超实时会撑爆内部缓冲。默认
#: 20 倍速折中（6 分钟音频约 19 秒灌完）；VT_ASR_WS_SPEED 可调，最小 1 倍。
ASR_WS_SPEED = max(float(os.environ.get("VT_ASR_WS_SPEED") or 20), 1.0)


def _asr_collect_sentence(msg, segments, texts):
    """把 result-generated 里的句子收进 segments（毫秒 → 秒）。

    实时流里同一句会先来"中间态"（end_time 为空、文本逐渐变长），说完才有
    带 begin/end 的最终事件 —— 只收**有终点的**，天然去重。
    """
    out = (msg.get("payload") or {}).get("output") or {}
    sent = out.get("sentence") or {}
    text = str(sent.get("text") or "").strip()
    if not text:
        return
    texts.append(text)
    b, e = sent.get("begin_time"), sent.get("end_time")
    if b is None or e is None:
        return                            # 句子还没说完，等最终事件
    try:
        b, e = float(b) / 1000.0, float(e) / 1000.0
    except (TypeError, ValueError):
        return
    if e > b:
        segments.append({"text": text, "start": round(b, 3),
                         "end": round(e, 3)})


def _asr_ws_prepare_audio(blob, model):
    """8k 专版模型 → ffmpeg 重采样为 8kHz 单声道 wav；其它模型原样返回。

    引擎提取音频固定 16kHz（video2audio `-ar 16000`），而
    fun-asr-flash-8k-realtime 等 8k 电话音专版模型**只收 8kHz**——16k 音频
    直接发过去服务端会异常断连（Connection to remote host was lost）。
    ffmpeg 不可用或转码失败时按原样返回，让服务端回具体错误码。
    """
    if "8k" not in str(model or "").lower():
        return blob, 16000
    if blob[:4] == b"RIFF" and blob[8:12] == b"WAVE":
        try:
            if int.from_bytes(blob[24:28], "little") == 8000:
                return blob, 8000              # 已是 8k wav，免转
        except Exception:  # noqa: BLE001
            pass
    try:
        ffmpeg, _ = ensure_ffmpeg()
    except Exception:  # noqa: BLE001
        ffmpeg = ""
    if not ffmpeg or not blob:
        return blob, 16000
    import subprocess as _sp
    import tempfile as _tf
    src = dst = ""
    try:
        with _tf.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
            tf.write(blob)
            src = tf.name
        dst = src + ".8k.wav"
        _sp.run([ffmpeg, "-y", "-i", src, "-vn", "-ac", "1", "-ar", "8000", dst],
                capture_output=True, check=True,
                creationflags=getattr(_sp, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0)
        with open(dst, "rb") as f:
            out = f.read()
        return (out or blob, 8000) if out else (blob, 16000)
    except Exception:  # noqa: BLE001
        return blob, 16000
    finally:
        for p in (src, dst):
            if p:
                try:
                    os.unlink(p)
                except OSError:
                    pass


def _asr_dashscope_realtime_submit(asr_obj):
    """DashScope 实时语音识别（WebSocket，协议见官方「实时语音识别 API」）。

    覆盖**只有实时形态**的模型：fun-asr-flash-8k-realtime / fun-asr-realtime /
    qwen3-asr-flash-realtime（官方模型表标注「模式=即时、API=WebSocket」，
    compatible-mode 的 chat/completions 与 /audio/transcriptions 都调不了它们）。

    交互时序：run-task → task-started → 二进制音频帧 → finish-task →
    result-generated… → task-finished。要点：
      · 握手鉴权 `Authorization: Bearer <key>`，密钥无效直接握手失败；
      · result-generated 的 `payload.output.sentence` 带 begin/end（毫秒），
        即实时模型也有**原生时间轴**，聚合成句级 segments；
      · 60 秒无消息服务端会断连 —— 推帧循环不会空闲，finish 后服务端继续
        推结果，不受影响；
      · 推帧按 ASR_WS_SPEED 倍速限速（全速灌发会被服务端断连）；
      · 8k 专版模型自动把 16k 音频重采样为 8kHz（_asr_ws_prepare_audio）；
      · 断连/超时自动重试 1 次；task-failed（参数/模型错误）不重试。
    """
    import json as _json
    import time as _time
    import uuid as _uuid

    try:
        import websocket                     # websocket-client
    except ImportError as e:
        raise RuntimeError("实时协议缺少依赖 websocket-client，"
                           "请先安装：pip install websocket-client") from e

    url = _asr_ws_url(getattr(asr_obj, "base_url", ""))
    key = str(getattr(asr_obj, "api_key", "") or "").strip()
    lang = str(getattr(asr_obj, "language", "") or "").strip()
    blob, sample_rate = _asr_ws_prepare_audio(
        asr_obj.file_binary or b"", getattr(asr_obj, "model", ""))
    fmt = _asr_audio_format(blob)
    params = {"sample_rate": sample_rate, "format": fmt}
    if lang and lang not in ("auto", "zh"):
        params["language"] = lang

    # 推帧节奏：按 16bit 单声道 PCM 字节率折算每帧"音频时长"，倍速发送
    frame_gap = ASR_WS_FRAME_BYTES / (2.0 * max(sample_rate, 1)) / ASR_WS_SPEED

    class _Transient(Exception):
        """瞬态错误（断连/超时）——值得整段重发一次。"""

    def _ws_send(ws, payload):
        """ws.send 统一包装：服务端掐断后继续 send 会抛
        WebSocketConnectionClosedException（"socket is already closed"，既不是
        _Transient 也不是 RuntimeError）——不包的话既不会自动重试、也进不了
        _submit 的降级分支，用户只会看到裸异常。统一转 _Transient，让
        「重试一次 → 仍失败 → 降级 qwen3-asr-flash 文件识别」的链路生效。
        """
        try:
            ws.send(payload)
        except Exception as e:  # noqa: BLE001
            raise _Transient("实时 ASR 连接中断（发送）：%s" % e)

    def _recv_until(ws, want, deadline, segments, texts):
        """收事件直到 want；途中的 result-generated 顺路收集。"""
        while _time.monotonic() < deadline:
            try:
                raw = ws.recv()
            except Exception as e:  # noqa: BLE001
                raise _Transient("实时 ASR 连接中断：%s" % e)
            if not raw or isinstance(raw, bytes):
                continue
            try:
                msg = _json.loads(raw)
            except ValueError:
                continue
            header = msg.get("header") or {}
            event = str(header.get("event") or "")
            if event == "result-generated":
                _asr_collect_sentence(msg, segments, texts)
            elif event == "task-failed":
                # 参数/模型/密钥类错误，重试也不会好 → 直接抛
                raise RuntimeError("实时 ASR 任务失败：%s %s"
                                   % (header.get("error_code"),
                                      header.get("error_message")))
            elif event == want:
                return
        raise _Transient("实时 ASR 等待 %s 超时" % want)

    def _run_once():
        try:
            ws = websocket.create_connection(
                url, timeout=60,
                header={"Authorization": "Bearer " + key,
                        "user-agent": "VideoToolbox-ASR"})
        except Exception as e:  # noqa: BLE001
            raise _Transient("实时 ASR 连接失败（%s）——密钥无效时握手会直接"
                             "被拒（HTTP 401/403）：%s" % (url, e))
        segments, texts = [], []
        task_id = _uuid.uuid4().hex[:32]     # 每次尝试新 task_id（服务端要求唯一）
        try:
            deadline = _time.monotonic() + 30 * 60      # 整体上限 30 分钟
            _ws_send(ws, _json.dumps({
                "header": {"action": "run-task", "task_id": task_id,
                           "streaming": "duplex"},
                "payload": {"task_group": "audio", "task": "asr",
                            "function": "recognition", "model": asr_obj.model,
                            "parameters": params, "input": {}}}))
            _recv_until(ws, "task-started", deadline, segments, texts)
            for i, off in enumerate(range(0, len(blob), ASR_WS_FRAME_BYTES)):
                if i and frame_gap > 0:
                    _time.sleep(frame_gap)              # 限速：防服务端断连
                _ws_send(ws, blob[off:off + ASR_WS_FRAME_BYTES])   # 二进制帧=原始音频
            _ws_send(ws, _json.dumps({"header": {"action": "finish-task",
                                                 "task_id": task_id,
                                                 "streaming": "duplex"},
                                      "payload": {"input": {}}}))
            _recv_until(ws, "task-finished", deadline, segments, texts)
        finally:
            try:
                ws.close()
            except Exception:  # noqa: BLE001
                pass
        return segments, texts

    segments = texts = None
    for attempt in (1, 2):
        try:
            segments, texts = _run_once()
            break
        except _Transient as e:
            if attempt == 1:
                _time.sleep(2)                          # 稍候重发整段
            else:
                hint = ""
                if "8k" in str(getattr(asr_obj, "model", "") or "").lower():
                    hint = ("；模型是 8k 电话音专版，已自动重采样为 8kHz 仍中断，"
                            "多为网络/服务端问题，可改用 16k 模型"
                            " fun-asr-flash-realtime")
                raise RuntimeError("%s（自动重试 1 次仍失败）%s" % (e, hint))
    if segments:
        return {"text": "".join(texts), "segments": segments}
    text = "".join(texts or [])
    if text:
        return text                     # 没拿到时间轴 → 按句兜底
    raise RuntimeError("实时 ASR 未返回任何识别结果")


#: 实时 WebSocket 会话级降级记忆：服务端掐断实时连接一经确认（官方 dashscope
#: SDK 也复现），本进程后续转录直接走文件识别，不再重复浪费重试时间。
_ASR_WS_DEGRADED = False


def _asr_fallback_chat_audio(asr_obj, reason=""):
    """实时 ASR 不可用 → 同端点换 qwen3-asr-flash 文件识别（chat_audio）。

    实测（2026-09-17）：maas 专属实例与公共百炼的 qwen3-asr-flash 文件识别
    均可用；⚠️ 专属实例的 asr 任务不支持 audio+text 混合输入——带 text
    提示词会 HTTP 400（"does not support this input"），必须裸音频。
    """
    if reason:
        _vc_log("实时 ASR 不可用（%s）→ 自动降级 qwen3-asr-flash 文件识别"
                % str(reason)[:80])
    asr_obj.model = "qwen3-asr-flash"
    asr_obj.prompt = ""
    return _asr_chat_audio_submit(asr_obj)


def vc_asr_protocol_patch():
    """ASR 服务模式全协议适配（幂等运行期补丁，引擎 WhisperAPI 不改本体）。

    在引擎 WhisperAPI._submit 前加协议分发：
      · openai     → 原实现（multipart /audio/transcriptions，verbose_json）；
      · azure      → deployments 端点 + api-key 头；
      · chat_audio → chat/completions + input_audio（百炼 Qwen-ASR、小米 MiMo）；
      · deepgram   → /v1/listen，Token 头 + 原始音频（原生词级时间轴）；
      · elevenlabs → /v1/speech-to-text，xi-api-key（原生词级时间轴）；
      · gemini     → generateContent + inline_data（纯文本，按句兜底）；
      · volcengine → 豆包录音识别极速版（一次请求返回，本地文件直传）；
      · assemblyai → /v2/upload + /v2/transcript + 轮询（词级时间轴）。
    各协议响应统一经 _asr_normalize_resp 归一：原生时间轴原样保留，
    纯文本响应（Azure json / Qwen-Audio / Gemini 等）按句切分 + 时长占比
    生成近似时间轴。缓存键追加协议名，防止换协议后吃到旧结果。
    ⚠️ 实时（WebSocket 流式）模型由 asr_model_guard 提前拦下并给出改法。
    """
    try:
        from videocaptioner.core.asr.whisper_api import WhisperAPI
    except Exception as e:  # noqa: BLE001
        _vc_log(f"ASR 协议补丁导入失败：{e}")
        return False
    if getattr(WhisperAPI, "_vt_proto_patched", False):
        return True
    orig_submit = WhisperAPI._submit
    orig_key = WhisperAPI._get_key

    def _submit(self):
        global _ASR_WS_DEGRADED
        proto = asr_protocol_of()
        # v1.14.2 协议自动纠偏：显式/旧配置判成 openai，但端点与模型特征指向
        # 别族时按推断改走——百炼 maas + 实时模型拿 OpenAI SDK 打必被服务端
        # 断连；qwen-audio/paraformer 族在 maas 上根本没有 /audio/transcriptions。
        if proto == "openai":
            auto = _infer_asr_protocol(getattr(self, "base_url", ""),
                                       getattr(self, "model", ""))
            if auto and auto != "openai":
                proto = auto
                _vc_log(f"ASR 协议与端点/模型不符，自动由 openai 改走 {auto}")
        if proto != "dashscope_realtime":
            # 实时模型只有走实时协议才有救：其它协议下提前拦，别等服务端 404。
            # 走实时协议时**不能**拦（那正是让实时模型出字幕的路）。
            guard = asr_base_guard(getattr(self, "base_url", ""))
            if not guard:
                guard = asr_model_guard(getattr(self, "model", ""))
            if guard:
                raise RuntimeError(guard)
            # 非 openai 协议不走引擎原实现，它那段"简体中文提示词预设"要自己补
            if (getattr(self, "language", "") == "zh"
                    and not getattr(self, "prompt", "")):
                self.prompt = "你好，我们需要使用简体中文，以下是普通话的句子"
        if proto == "dashscope_realtime" and not _ASR_WS_DEGRADED:
            try:
                resp = _asr_dashscope_realtime_submit(self)
            except RuntimeError as e:
                # 实时 WebSocket 被服务端中途掐断（握手/task-started 正常、音频
                # 发送中或完成后无 Close 码断连；官方 dashscope SDK 同样无法
                # 使用——2026-09-17 实测，与客户端实现/网络路径无关）。
                _e = str(e)
                if "连接" not in _e and "超时" not in _e:
                    raise              # task-failed 等确定性错误，降级无意义
                _ASR_WS_DEGRADED = True
                resp = _asr_fallback_chat_audio(self, _e)
        elif proto == "dashscope_realtime":
            # 本进程已确认实时通道被服务端掐断 → 直接走文件识别，不再试 WS
            resp = _asr_fallback_chat_audio(self)
        elif proto == "azure":
            resp = _asr_azure_submit(self)
        elif proto in ("chat_audio", "dashscope"):
            resp = _asr_chat_audio_submit(self)
        elif proto == "deepgram":
            resp = _asr_deepgram_submit(self)
        elif proto == "elevenlabs":
            resp = _asr_elevenlabs_submit(self)
        elif proto == "gemini":
            resp = _asr_gemini_submit(self)
        elif proto == "volcengine":
            resp = _asr_volcengine_submit(self)
        elif proto == "assemblyai":
            resp = _asr_assemblyai_submit(self)
        else:
            # openai 协议走引擎原实现（OpenAI SDK）。SDK 会在 base_url 后面再
            # 拼一次 /audio/transcriptions，所以先把"完整端点"的尾巴削掉并
            # 重建 client —— 内存里改 base_url 不会影响已经建好的 client。
            clean = asr_strip_endpoint_tail(self.base_url, "/audio/transcriptions",
                                            "/audio/translations")
            if clean and clean != self.base_url:
                self.base_url = clean
                _vc_log(f"ASR 地址含完整端点，已规范化为 {clean}")
                try:
                    from openai import OpenAI
                    self.client = OpenAI(base_url=clean, api_key=self.api_key)
                except Exception as e:  # noqa: BLE001
                    _vc_log(f"规范化后重建 ASR 客户端失败：{e}")
            resp = orig_submit(self)
        return _asr_normalize_resp(resp, self)

    def _get_key(self):
        try:
            return f"{orig_key(self)}-{asr_protocol_of()}"
        except Exception:  # noqa: BLE001
            return orig_key(self)

    WhisperAPI._submit = _submit
    WhisperAPI._get_key = _get_key
    WhisperAPI._vt_proto_patched = True
    _vc_log("ASR 协议补丁已挂：openai/azure/chat_audio/deepgram/elevenlabs/"
            "gemini/volcengine/assemblyai（纯文本响应按句兜底；实时模型提前拦截）")
    try:
        vc_asr_chunk_patch()
    except Exception as e:  # noqa: BLE001
        _vc_log(f"分块补丁挂载失败：{e}")
    return True


#: chat_audio 族（百炼 compatible-mode）单请求音频时长上限约 3 分钟，
#: 引擎默认按 600s 切块必超 → 该协议下把块长压到 170s（留转发/编码余量）。
ASR_CHAT_AUDIO_CHUNK_MS = 170_000


def vc_asr_chunk_patch():
    """chat_audio 协议下把引擎的 ASR 音频分块长度压到 3 分钟内（幂等补丁）。

    引擎的 ChunkedASR 默认 chunk_length_ms=600s，对 OpenAI/Deepgram 这类
    长音频服务没问题；但百炼 compatible-mode 多模态单次请求上限约 3 分钟，
    600s 的块必被服务端拒（The audio is too long）。这里包住
    transcribe._create_whisper_api_asr：构造完成后按当前协议把块长改到 170s，
    让「切块→逐块提交」在提交前就合规，而不是等 400 再对半救火。
    """
    try:
        import importlib as _il
        # ⚠️ asr 包属性 transcribe 是**函数**（遮蔽同名子模块），普通
        # import ... as _tr 拿到的是函数；必须 importlib 按模块名取真模块。
        _tr = _il.import_module("videocaptioner.core.asr.transcribe")
    except Exception as e:  # noqa: BLE001
        _vc_log(f"分块补丁导入 transcribe 失败：{e}")
        return False
    if getattr(_tr, "_vt_chunk_patched", False):
        return True
    orig = getattr(_tr, "_create_whisper_api_asr", None)
    if orig is None:
        return False

    def _create(*a, **k):
        inst = orig(*a, **k)
        try:
            if asr_protocol_of() in ("chat_audio", "dashscope"):
                inst.chunk_length_ms = ASR_CHAT_AUDIO_CHUNK_MS
        except Exception as e:  # noqa: BLE001
            _vc_log(f"分块长度调整失败：{e}")
        return inst

    _tr._create_whisper_api_asr = _create
    _tr._vt_chunk_patched = True
    _vc_log("ASR 分块补丁已挂：chat_audio 协议块长压到 170s（默认 600s 超上限）")
    return True


def asr_non_zh_en_ratio(text):
    """文本中「非中/英」字符占比（0~1）；无有效字符返回 0。

    判据：跳过空白与标点符号；ASCII（字母数字）与**汉字**算"中/英"，其余
    书写系统（假名/谚文/西里尔/泰文…）算"非中英"。日文句子里的汉字计入中英，
    假名为主时占比仍过半 → 用于「默认接口语言提示」判断片源是不是中文/英文，
    非中英占比高时不再注入简体中文提示词。
    """
    import unicodedata
    total = other = 0
    for ch in str(text or ""):
        if ch.isspace():
            continue
        if unicodedata.category(ch)[0] in ("P", "S"):
            continue
        o = ord(ch)
        total += 1
        if o < 128:
            continue                                  # ASCII 字母数字
        if (0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF
                or 0xF900 <= o <= 0xFAFF
                or 0x3007 == o or 0x00AA == o or 0x00BA == o):
            continue                                  # 汉字（日文汉字同源）
        other += 1
    return (other / total) if total else 0.0


#: 引擎翻译服务枚举值（videocaptioner.core.entities.TranslatorServiceEnum）。
#: v1.12.0 起字幕翻译板块仅支持机翻（微软 / 谷歌 / DeepLx），LLM 翻译入口
#: 已全部移除；TS_LLM 仅用于把历史配置迁回机翻。
TS_LLM = "LLM 大模型翻译"
TS_BING = "微软翻译"

#: 免费翻译端点预检结果缓存（进程内，避免每条字幕重复探测）
_TS_PROBE_CACHE = {}


def _ts_probe_ok(kind):
    """免费翻译端点连通性探测（3 秒超时，结果进程内缓存）——诊断/备用。

    v1.12.0 实测：微软 ``edge.microsoft.com/translate/translatetext``（免认证）
    直连 200；谷歌 ``translate.googleapis.com/translate_a/single?client=gtx``
    需走系统代理（requests 默认信任），代理未开则超时。本函数**不用于短路**，
    只保留给诊断与后续"可用性提示"复用。
    """
    if kind in _TS_PROBE_CACHE:
        return _TS_PROBE_CACHE[kind]
    ok = True
    if kind == "google":
        try:
            import requests
            r = requests.get(
                "https://translate.googleapis.com/translate_a/single",
                params={"client": "gtx", "sl": "auto", "tl": "zh-CN",
                        "dt": "t", "q": "ok"},
                headers={"User-Agent": "Mozilla/5.0"}, timeout=3)
            ok = r.status_code == 200
        except Exception:  # noqa: BLE001
            ok = False
    _TS_PROBE_CACHE[kind] = ok
    return ok


def vc_lazy_cache_patch():
    """把 diskcache.Cache 换成惰性代理，省掉引擎导入时建库的 2~4 秒（幂等）。

    引擎在 videocaptioner.core.utils.cache 模块级创建 5 个 diskcache 实例
    （LLM / ASR / TTS / 翻译 / 版本状态），每个都会真实打开 SQLite 建库并做
    维护：本机实测每个约 0.9 秒（慢盘更久），合计 2.5~4.5 秒——而进入「字幕
    处理」页并不需要任何缓存。这里在引擎导入**之前**替换 diskcache.Cache：
    首个属性访问才真正建库，`memoize` 也延迟到首次调用才建库，语义不变。
    必须在任何 videocaptioner 导入之前调用（prepare_runtime_env 最前面）。
    """
    try:
        import diskcache
    except Exception:  # noqa: BLE001
        return False
    if getattr(diskcache, "_vt_lazy_patched", False):
        return True
    real_cache = diskcache.Cache

    class _LazyCache:
        """diskcache.Cache 的惰性代理：真正用到时才建库。"""

        def __init__(self, directory, **kwargs):
            self.__dict__["_lc_args"] = (directory,)
            self.__dict__["_lc_kwargs"] = kwargs
            self.__dict__["_lc_real"] = None

        def _lc(self):
            obj = self.__dict__["_lc_real"]
            if obj is None:
                obj = self.__dict__["_lc_real"] = real_cache(
                    *self.__dict__["_lc_args"], **self.__dict__["_lc_kwargs"])
            return obj

        def __getattr__(self, name):
            return getattr(self._lc(), name)

        def __len__(self):
            return len(self._lc())

        def __contains__(self, key):
            return key in self._lc()

        def __getitem__(self, key):
            return self._lc()[key]

        def __setitem__(self, key, value):
            self._lc()[key] = value

        def __delitem__(self, key):
            del self._lc()[key]

        def __iter__(self):
            return iter(self._lc())

        def memoize(self, **kwargs):
            def deco(func):
                holder = {}

                def wrapper(*a, **kw):
                    m = holder.get("m")
                    if m is None:
                        m = holder["m"] = self._lc().memoize(**kwargs)(func)
                    return m(*a, **kw)
                wrapper.__name__ = getattr(func, "__name__", "wrapper")
                wrapper.__doc__ = getattr(func, "__doc__", None)
                wrapper.__wrapped__ = func
                return wrapper
            return deco

    diskcache.Cache = _LazyCache
    diskcache._vt_lazy_patched = True
    return True


def vc_prepare_settings_file():
    """引擎界面导入前规整 settings.json（幂等，在 prepare_runtime_env 调用）。

    1) 工作目录等路径项全部收进软件文件夹（修掉历史 C 盘 Work_Dir）；
    2) 把全局 LLM 配置注入引擎 OpenAI 兼容槽。
    必须在 videocaptioner.ui.common.config（qconfig 读盘）之前完成。
    """
    try:
        os.makedirs(vc_data_dir(), exist_ok=True)
        existed = os.path.isfile(vc_settings_path())
        data = _vc_read_settings()
        changed = _vc_force_local_paths(data)
        ai = ai_load_config()
        llm = data.setdefault("LLM", {})
        if not bool(ai.get("enabled", True)):
            # 「启用 AI」已关闭：清空引擎 LLM 槽（历史注入的密钥一并清掉），
            # 引擎的优化 / LLM 翻译会明确提示需配置 AI，而不是偷偷消耗额度
            for k in ("OpenAI_API_Key", "OpenAI_API_Base", "OpenAI_Model"):
                if llm.get(k):
                    llm[k] = ""
                    changed = True
        else:
            # v1.12.0：全局 AI 单通道（base_url / api_key / model 一套）
            want = {
                "LLMService": "OpenAI 兼容",
                "OpenAI_API_Base": str(ai.get("base_url") or "").strip(),
                "OpenAI_API_Key": str(ai.get("api_key") or "").strip(),
                "OpenAI_Model": str(ai.get("model") or "").strip(),
            }
            for k, v in want.items():
                if v and llm.get(k) != v:
                    llm[k] = v
                    changed = True
        # v1.12.0：微软翻译已改用 Edge 免认证端点、谷歌翻译已改用 gtx 免费网页版
        # 接口（docs/vc_translate_impl/*.py），两者恢复直连可用。
        # v1.12.0 起字幕翻译板块全面去 AI（仅机翻）：历史配置若被 v1.11.0 迁到
        # 「LLM 大模型翻译」，这里迁回「微软翻译」；翻译失败不再回退 LLM，
        # 如实报错（失败率 ≥50% 时引擎会抛 RuntimeError 提示检查网络）。
        tr = data.setdefault("Translate", {})
        cur_ts = str(tr.get("TranslatorServiceEnum") or "").strip()
        if cur_ts == TS_LLM:
            tr["TranslatorServiceEnum"] = TS_BING
            changed = True
            _vc_log("字幕翻译仅支持机器翻译，已把翻译服务由「LLM 大模型翻译」"
                    "迁回「微软翻译」")
        if changed or not existed:
            _vc_write_settings(data)
        # v1.11.0：ASR（转录配置）与接口 B 同样在引擎读盘前注入
        apply_asr_to_engine(ai)
    except Exception:
        pass


def vc_enforce_runtime_cfg():
    """引擎 QConfig 已加载后的运行期兜底：强制工作目录收敛到软件文件夹。

    防止历史 settings.json 的 C 盘 Work_Dir 在内存里复活、或被界面回写。
    在引擎界面/设置界面构建之后调用（best-effort）。
    """
    try:
        from videocaptioner.ui.common.config import cfg as _cfg
        work_posix = os.path.join(vc_data_dir(), "work-dir").replace(os.sep, "/")
        try:
            cur = str(_cfg.get(_cfg.work_dir) or "")
        except Exception:
            cur = ""
        if cur.replace("\\", "/") != work_posix:
            _cfg.set(_cfg.work_dir, work_posix)
    except Exception:
        pass
    # v1.11.0：转录配置（自有 ASR 服务 / 本地独立模型）与本地模型覆盖补丁
    # 一并在此兜底——引擎界面构建完成后调用，保证内存 QConfig 与磁盘一致。
    try:
        apply_asr_to_engine()
    except Exception:
        pass
    try:
        vc_asr_patch_apply()
    except Exception:
        pass
    # v1.12.0：翻译板块已全面去 AI（仅机翻），「创建失败/无有效产出回退 LLM」
    # 兜底补丁（vc_translate_fallback_patch）整体移除；翻译失败如实报错。


def vc_migrate_legacy_data():
    """把字幕引擎在 C 盘的历史数据迁移到数据根目录（幂等，一次有效）。

    上游在不同版本用过两种布局，都要处理：
      · <legacy>/settings.json、<legacy>/logs/...    —— 直接以 legacy 为数据根
      · <legacy>/VideoCaptioner/settings.json、...   —— 多套了一层同名子目录
    做法：逐个把 legacy 下的「数据项」（settings.json / logs / cache / models /
    resource / work-dir）搬到目标根；若发现 legacy 下还有嵌套的 VideoCaptioner
    子目录，则把它的内容也视作数据项一并搬走，避免出现 VideoCaptioner\\VideoCaptioner。
    目标已存在同名项时不覆盖（保留新位置的数据）。返回迁移的条目数。
    """
    dst_root = vc_data_dir()
    # 需要搬运的数据项名（白名单，避免搬进无关文件）
    DATA_ITEMS = ("settings.json", "logs", "cache", "models", "resource",
                  "work-dir", "cli", "llm_requests.jsonl")
    moved = 0

    def _merge(src_dir, depth=0):
        """把 src_dir 下的数据项合并到 dst_root；遇到嵌套同名目录则下钻。"""
        nonlocal moved
        if depth > 2:
            return
        try:
            names = os.listdir(src_dir)
        except OSError:
            return
        nested = []
        for name in names:
            src = os.path.join(src_dir, name)
            # 兼容旧布局：<legacy>/VideoCaptioner/... 下钻一层（稍后处理，
            # 先搬完本层的数据项，避免父目录自己的 settings.json 被漏掉）
            if (name == VC_NAME and os.path.isdir(src)
                    and os.path.abspath(src) != os.path.abspath(dst_root)):
                nested.append(src)
                continue
            if name not in DATA_ITEMS:
                continue
            dst = os.path.join(dst_root, name)
            if os.path.exists(dst):
                # 目录已存在则合并内容（同名文件不覆盖）
                if os.path.isdir(src) and os.path.isdir(dst):
                    moved += _merge_into(src, dst)
                continue
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.move(src, dst)
                moved += 1
            except OSError:
                pass
        for sub in nested:
            _merge(sub, depth + 1)

    def _merge_into(src_dir, dst_dir):
        """递归合并目录，同名不覆盖；返回搬动的条目数。"""
        n = 0
        try:
            names = os.listdir(src_dir)
        except OSError:
            return 0
        for name in names:
            s = os.path.join(src_dir, name)
            d = os.path.join(dst_dir, name)
            if os.path.isdir(s):
                try:
                    os.makedirs(d, exist_ok=True)
                except OSError:
                    continue
                n += _merge_into(s, d)
            elif not os.path.exists(d):
                try:
                    shutil.move(s, d)
                    n += 1
                except OSError:
                    pass
        return n

    try:
        os.makedirs(dst_root, exist_ok=True)
    except OSError:
        return 0

    for legacy in _VC_LEGACY_DIRS:
        if not legacy or not os.path.isdir(legacy):
            continue
        if os.path.abspath(legacy) == os.path.abspath(dst_root):
            continue
        _merge(legacy)
        _prune_empty(legacy)
    return moved


def _prune_empty(root):
    """自底向上删除 root 下的空目录（不含 root 自身）。best-effort。"""
    for cur, dirs, files in os.walk(root, topdown=False):
        if os.path.abspath(cur) == os.path.abspath(root):
            continue
        if files:
            continue
        try:
            os.rmdir(cur)
        except OSError:
            pass


def _dir_has_content(d):
    """目录下是否存在任何文件（含被占用/无权访问的，保守判为有内容）。"""
    try:
        for _cur, _dirs, files in os.walk(d):
            if files:
                return True
    except OSError:
        return True
    return False


def vc_legacy_leftovers():
    """列出仍在 C 盘、且真的含有效数据的历史字幕引擎目录。

    判据是「有文件，且该文件在数据根下还不存在」——迁移后遗留的重复文件
    （数据根已有同名同路径的副本）不算残留，避免误导用户去清理一个已经
    迁空的路径。仅剩空目录树的一律不提示。
    """
    out = []
    dst_root = vc_data_dir()

    def _has_unique_file(d):
        """d 下是否存在数据根里没有对应文件的文件。"""
        try:
            walker = os.walk(d)
        except OSError:
            return False
        for cur, _dirs, files in walker:
            if not files:
                continue
            rel_dir = os.path.relpath(cur, d)
            # <legacy>/ 与 <legacy>/VideoCaptioner/ 两种布局都映射到数据根
            base = os.path.basename(cur)
            for f in files:
                cands = []
                if rel_dir in (".", ""):
                    cands.append(os.path.join(dst_root, f))
                else:
                    cands.append(os.path.join(dst_root, rel_dir, f))
                    # 多套一层同名目录的情况（.../VideoCaptioner/cache/x.db）
                    if base != VC_NAME and VC_NAME in rel_dir.split(os.sep):
                        tail = rel_dir.split(VC_NAME, 1)[1].lstrip(os.sep)
                        cands.append(os.path.join(dst_root, tail, f))
                if not any(os.path.exists(c) for c in cands):
                    return True
        return False

    for d in _VC_LEGACY_DIRS:
        if d and os.path.isdir(d) and _dir_has_content(d) and _has_unique_file(d):
            out.append(d)
    return out


def prepare_runtime_env():
    """统一准备运行期环境（幂等，可重复调用）。

    0. diskcache 延迟化补丁（v1.11.0：省掉引擎导入时建 5 个缓存库的数秒）；
    1. 迁移字幕引擎在 C 盘的历史数据到数据根目录；
    2. 重定向字幕引擎的路径常量为数据根目录；
    3. 兜底确保临时目录指向数据根目录（不落系统 Temp）。
    在导入 videocaptioner *之前* 调用；GUI 启动与自检都会走这里。
    """
    # 必须最先：任何 videocaptioner 导入之前替换 diskcache.Cache
    try:
        vc_lazy_cache_patch()
    except Exception:
        pass
    # v1.14.1：转录时 pydub 裸调 ffprobe/ffmpeg 闪黑窗 → 子进程默认隐藏窗口
    try:
        vc_pydub_nowindow_patch()
    except Exception:
        pass
    # 标准流统一 UTF-8 容错，避免 GBK 控制台打印生僻字/Emoji 时崩溃
    try:
        configure_stdio_utf8()
    except Exception:
        pass
    try:
        vc_migrate_legacy_data()
    except Exception:
        pass
    try:
        vc_redirect_paths()
    except Exception:
        pass
    try:
        # 引擎界面读盘前规整 settings.json：路径收进软件文件夹 + 注入全局 LLM
        vc_prepare_settings_file()
    except Exception:
        pass
    try:
        os.makedirs(TMP_DIR, exist_ok=True)
        os.environ["TEMP"] = TMP_DIR
        os.environ["TMP"] = TMP_DIR
        tempfile.tempdir = TMP_DIR
    except OSError:
        pass


def data_root_info():
    """返回 (当前数据根目录, 是否为默认位置, 来源说明)，供界面展示。"""
    root = _resolve_data_root()
    if os.environ.get("VT_DATA_ROOT"):
        src = "环境变量 VT_DATA_ROOT"
    elif os.path.isfile(DATA_ROOT_POINTER):
        src = "用户自定义（data_dir.txt）"
    else:
        src = "默认（程序目录）"
    return root, os.path.abspath(root) == os.path.abspath(APP_DIR), src


def set_data_root(new_root, migrate=True):
    """切换数据根目录（写指针文件），返回 (是否成功, 说明文案)。

    只改指针文件，不立刻搬数据；migrate=True 时把当前 data/logs/tmp 下的内容
    尽量搬到新位置（同名不覆盖）。切换需重启程序后完全生效（路径常量在导入
    时已固化）。
    """
    try:
        new_root = os.path.abspath(str(new_root).strip().strip('"'))
    except OSError as e:
        return False, "路径无效：%s" % e
    if not new_root:
        return False, "路径为空"
    try:
        os.makedirs(new_root, exist_ok=True)
        # 探针：确认真的可写（避免只读盘/权限问题）
        probe = os.path.join(new_root, ".vt_write_test")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
    except OSError as e:
        return False, "该位置不可写：%s" % e

    if os.path.abspath(new_root) == os.path.abspath(APP_DIR):
        # 切回默认：删掉指针文件
        try:
            if os.path.isfile(DATA_ROOT_POINTER):
                os.remove(DATA_ROOT_POINTER)
        except OSError as e:
            return False, "无法移除指针文件：%s" % e
        return True, "已切回默认位置（程序目录），重启后生效"

    try:
        with open(DATA_ROOT_POINTER, "w", encoding="utf-8") as f:
            f.write(new_root)
    except OSError as e:
        return False, "无法写入指针文件：%s" % e

    if migrate:
        moved, failed = _move_data_to(new_root)
        return True, "已切换，并迁移 %d 项数据%s，重启后生效" % (
            moved, ("（%d 项被占用未迁移）" % failed) if failed else "")

    return True, "已切换，重启后生效"


def _move_data_to(new_root):
    """把当前数据根下的 data/logs/tmp 内容搬到新根（同名不覆盖）。"""
    moved = failed = 0
    for sub in ("data", "logs"):
        src_dir = os.path.join(DATA_ROOT, sub)
        dst_dir = os.path.join(new_root, sub)
        if not os.path.isdir(src_dir):
            continue
        try:
            os.makedirs(dst_dir, exist_ok=True)
        except OSError:
            failed += 1
            continue
        for name in os.listdir(src_dir):
            s = os.path.join(src_dir, name)
            d = os.path.join(dst_dir, name)
            if os.path.exists(d):
                continue
            try:
                shutil.move(s, d)
                moved += 1
            except OSError:
                failed += 1
    return moved, failed


def engine_ui_brand_patch():
    """对内嵌引擎的用户可见文案与布局做中性化补丁（幂等，仅改运行时行为）。

    · 视频预览弹窗标题/图标跟随宿主，去除上游品牌；
    · 任务创建页隐藏品牌 logo、收紧独立窗口时代的大留白。
    各部分独立容错：某一模块导入失败（如缺 vlc）不影响其余补丁生效。
    第三方组件的许可全文与来源声明见 docs 目录下两个声明文件（必须保留）。
    """
    # 视频预览弹窗补丁为 best-effort：缺可选依赖 vlc 时跳过，不算失败
    try:
        from videocaptioner.ui.components.MyVideoWidget import MyVideoWidget
    except Exception:
        MyVideoWidget = None
    if MyVideoWidget is not None:
        _patch_video_widget(MyVideoWidget)
    # 任务创建页补丁是内嵌界面真正依赖的（隐藏 logo/水印、收紧留白）
    try:
        from videocaptioner.ui.view.task_creation_interface import (
            TaskCreationInterface)
    except Exception:
        return False
    _patch_task_creation(TaskCreationInterface)
    return True


def _patch_video_widget(MyVideoWidget):
    """视频预览弹窗：标题与图标跟随宿主。"""
    if getattr(MyVideoWidget, "_vt_patched", False):
        return

    orig_init = MyVideoWidget.__init__

    def _init(self, parent=None):
        orig_init(self, parent)
        # 视频预览弹出窗口：标题与图标跟随宿主，去除上游品牌
        self.setWindowTitle("视频预览")
        try:
            from PyQt5.QtWidgets import QApplication
            icon = QApplication.windowIcon()
            if not icon.isNull():
                self.setWindowIcon(icon)
        except Exception:
            pass

    MyVideoWidget.__init__ = _init
    MyVideoWidget._vt_patched = True


def _patch_task_creation(TaskCreationInterface):
    """任务创建页：隐藏品牌 logo、收紧独立窗口时代的大留白。"""
    if getattr(TaskCreationInterface, "_vt_layout_patched", False):
        return

    orig_setup = TaskCreationInterface.setup_ui

    def _setup(self):
        orig_setup(self)
        logo = getattr(self, "logo_label", None)
        if logo is not None:
            logo.hide()
        lay = getattr(self, "main_layout", None)
        if lay is not None:
            for i in reversed(range(lay.count())):
                item = lay.itemAt(i)
                spacer = item.spacerItem() if item is not None else None
                if spacer is not None and spacer.sizeHint().height() >= 100:
                    lay.removeItem(item)
            lay.setSpacing(18)
            lay.insertSpacing(0, 24)

    TaskCreationInterface.setup_ui = _setup
    TaskCreationInterface._vt_layout_patched = True
# =============================


# ========== 全局 AI（智谱 GLM：字幕/标题语言识别） ==========
# AI 客户端实现在 tools\ai_client.py（仅标准库依赖，原投稿引擎内模块独立化），
# 按路径直接加载；配置在 data\ai_config.json，首次调用自动生成默认配置。
_AI_MOD = None


def ai_mod():
    """按路径加载内嵌 AI 客户端模块（缓存单例）。"""
    global _AI_MOD
    if _AI_MOD is None:
        import importlib.util
        path = os.path.join(TOOLS_DIR, "ai_client.py")
        spec = importlib.util.spec_from_file_location("vt_ai_client", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _AI_MOD = mod
    return _AI_MOD


def ai_detect_language(text):
    """AI 识别文本主要语言代码（zh/en/ja/...）；AI 不可用或失败返回 ''。"""
    try:
        if not ai_mod().is_enabled():
            return ""
        return ai_mod().detect_language(text)
    except Exception:
        return ""


def ytdlp_sub_langs(lang_code, default=""):
    """语言代码 → yt-dlp --sub-langs 参数（下载字幕跟随标题语言用）。"""
    try:
        return ai_mod().ytdlp_sub_langs(lang_code, default)
    except Exception:
        return default


# ========== 设置持久化 ==========
def load_config():
    for path in (CONFIG_PATH, _fallback_config_path()):
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            if isinstance(cfg, dict) and cfg:
                return cfg
        except Exception:
            continue
    return {}


def save_config(cfg):
    """写入配置；脚本目录只读时自动改写到用户本地目录，保证「长期固定」不失效"""
    candidates = [CONFIG_PATH]
    fb = _fallback_config_path()
    if os.path.abspath(fb) != os.path.abspath(CONFIG_PATH):
        candidates.append(fb)
    for path in candidates:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            continue
    return False


def get_saved_download_dir():
    """上次使用的下载目录。

    即使该目录当前不存在（如外接硬盘未插入）也照样返回，
    以免用户的长期设置被静默丢掉；下载时会按需创建。
    """
    d = str(load_config().get("download_dir", "")).strip()
    return d if d else DEFAULT_DOWNLOAD_DIR


def set_saved_download_dir(path):
    """记住下载目录，下次启动自动填入（长期固定）"""
    path = clean_path(str(path or ""))
    if not path:
        return
    try:
        path = os.path.abspath(path)
    except Exception:
        pass
    cfg = load_config()
    cfg["download_dir"] = path
    save_config(cfg)


# ========== 全局 AI / LLM 配置（v1.10.8：唯一一套，工具箱与字幕引擎共用） ==========
# 配置实体仍在 data\ai_config.json（由 tools\ai_client.py 读写），这里提供给
# 界面使用的加载 / 保存 / 连通性测试接口；保存后立即把 OpenAI 兼容槽同步给
# 字幕引擎，做到「LLM 配置只在全局设置里出现一次」。
AI_CONFIG_PATH = os.path.join(DATA_DIR, "ai_config.json")


def ai_load_config():
    """读取全局 AI/LLM 配置（缺失字段用出厂默认补齐）。ai_client 不可用时直接读文件。"""
    try:
        return ai_mod().load_config()
    except Exception:
        try:
            with open(AI_CONFIG_PATH, encoding="utf-8-sig") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}


def ai_save_config(cfg):
    """保存全局 AI/LLM 配置：落盘 ai_config.json + 重置客户端单例 + 同步给字幕引擎。

    只保留默认 schema 内的键（避免界面写入杂字段）。返回清洗后的配置 dict。
    v1.11.0 起含两条通道（A 工具箱 / B 引擎）与 ASR、AI 校准参数；保存后统一
    把接口 B 注入字幕引擎、把 ASR 注入引擎转录配置。
    """
    mod = ai_mod()
    clean = dict(getattr(mod, "DEFAULT_CONFIG", {}))
    for k in list(clean.keys()):
        if k in cfg and cfg[k] is not None:
            clean[k] = cfg[k]
    mod.save_config(clean)
    try:
        mod.reset_clients()     # 强制下次调用重建客户端（两条通道一起丢）
    except Exception:
        pass
    try:
        apply_global_llm_to_engine(clean)
    except Exception:
        pass
    try:
        apply_asr_to_engine(clean)
    except Exception:
        pass
    return clean


def ai_test_connection(cfg=None, channel="a"):
    """连通性自检：返回 (是否成功, 说明)。用传入配置或已保存配置。

    v1.12.0 起单通道（channel 参数保留兼容，忽略）。
    """
    mod = ai_mod()
    probe = ai_save_config(cfg) if cfg is not None else None
    try:
        client = mod.AIClient(probe) if probe is not None else mod.get_client()
        reply = client.chat_text("收到请只回复两个字：正常", max_tokens=512)
        return True, (reply or "(空回复)") + \
            f"（全局 AI，模型 {client.model}）"
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def ai_test_asr(cfg=None):
    """ASR（语音识别）配置自检：返回 (是否成功, 说明)。"""
    try:
        return ai_mod().asr_test_connection(cfg if cfg is not None else ai_load_config())
    except Exception as e:  # noqa: BLE001
        return False, str(e)


# ========== AI 校准（Agent 级）入口 ==========
# 界面开启「AI 校准」后点「开始校准」，等价于向 Agent 下达：基于脚本
# subtitle_calib_merged 校准字幕，不改变时间轴与格式，仅调整文字内容，
# 一次读不完就自行拆分，最后合并。实现见 src\calib_ai_agent.py。
def calib_ai_chat(prompt, system=None, max_tokens=None, on_reasoning=None):
    """AI 校准的 LLM 回调：走全局 AI 单通道（v1.12.0 起不再选通道）。

    on_reasoning（v1.14.2）：思考链上报回调，透传给 AIClient，把推理模型返回的
    思考过程（reasoning_content）实时交给校准日志显示。
    """
    client = ai_mod().get_client()
    return client.chat_text(prompt, system=system,
                            max_tokens=int(max_tokens or 8192),
                            on_reasoning=on_reasoning)


def calib_ai_run(src, out=None, report=None, mode_flag="", fix_en=False,
                 log=None, round_no=1, cancel=None, workdir=None,
                 style=None, resume_from=None, prev_changes=None):
    """跑一轮 Agent 级 AI 校准，返回结果 dict（见 calib_ai_agent.calibrate）。

    style：None=读配置 `calib_style`——`term` 术语级（只替换名词，默认）/
           `rewrite` 整句重写（针对机翻腔、跨 cue 断句的片源，长双语片常用）。
    resume_from：起点文件。长片源「再次校准」应传上一轮产物：这样会**跳过脚本基线**
           直接在上轮成果上继续；否则从原始源重跑会把上轮已采纳的改动丢掉。
    prev_changes：上轮采纳明细 [(num, old, new), ...]，注入提示词禁止回退。
    concurrency：逐块 LLM 调用并发路数，None=读配置 `calib_concurrency`（默认 1＝串行）。
    """
    import calib_ai_agent as _agent
    ai = ai_load_config()
    style = style or str(ai.get("calib_style") or "term")
    return _agent.calibrate(
        src, out=out, report=report, mode_flag=mode_flag, fix_en=fix_en,
        script=os.path.join(APP_DIR, "subtitle_calib_merged.py"),
        python=system_python(), log=log, chat=calib_ai_chat,
        chunk_cues=int(ai.get("calib_chunk_cues") or 120),
        max_chars=int(ai.get("calib_max_chars") or 6000),
        max_tokens=int(ai.get("calib_max_tokens") or 8192),
        concurrency=int(ai.get("calib_concurrency") or 1),
        round_no=round_no, cancel=cancel, workdir=workdir,
        style=style, resume_from=resume_from, prev_changes=prev_changes,
        sentence_aware=bool(ai.get("calib_sentence_aware", True)),
        strict_width=bool(ai.get("calib_strict_width", False)))


# ========== 校准知识多用户同步开关（持久化在 config.json） ==========
def calib_sync_enabled():
    """是否启用校准知识自动同步（默认启用；VT_NO_CALIB_SYNC 仍可强制关闭）。"""
    if os.environ.get("VT_NO_CALIB_SYNC"):
        return False
    return bool(load_config().get("calib_sync_enabled", True))


def set_calib_sync_enabled(flag):
    cfg = load_config()
    cfg["calib_sync_enabled"] = bool(flag)
    save_config(cfg)
# =============================


# ========== 子进程窗口控制 ==========
# 保留原始入口，供命令行模式继续显示 yt-dlp 进度；
# run_process / popen_process 用于 GUI 或捕获输出的场景，避免弹出黑色控制台。
_SUBPROCESS_RUN = subprocess.run
_SUBPROCESS_POPEN = subprocess.Popen


def _hide_console_kwargs(kwargs):
    if sys.platform.startswith("win"):
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        kwargs.setdefault("startupinfo", startupinfo)
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | subprocess.CREATE_NO_WINDOW
    return kwargs


def run_process(*args, **kwargs):
    return _SUBPROCESS_RUN(*args, **_hide_console_kwargs(kwargs))


def popen_process(*args, **kwargs):
    return _SUBPROCESS_POPEN(*args, **_hide_console_kwargs(kwargs))
# =============================


# ========== 工具引导 ==========
# 并行下载任务会同时调用 ensure_*；加锁防止首次运行时多个线程重复下载同一文件
_BOOTSTRAP_LOCK = threading.Lock()
_MIHOMO_PROC = None


def _port_listening(port, timeout=0.5):
    """探测本地端口是否已被监听（判断内置代理是否已在运行）"""
    import socket
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


#: mihomo 的运行日志（配置写错 / 节点不通时唯一能查的地方）
MIHOMO_LOG = os.path.join(LOGS_DIR, "mihomo.log")


def _mihomo_log(msg):
    """把 mihomo 相关事件追加到 logs\\mihomo.log（失败静默，绝不影响主流程）。"""
    try:
        os.makedirs(LOGS_DIR, exist_ok=True)
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(MIHOMO_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{stamp}] {msg}\n")
    except OSError:
        pass


def _load_proxy_nodes(path):
    """从 Clash/mihomo yaml 提取节点定义（proxies 段原样保留，含密钥字段）。

    返回节点 dict 列表；文件不存在/解析失败/没有节点返回 []。
    只取节点不取规则与代理组 —— 分流规则固定用内置模板（GitHub/YouTube 走
    代理、国内直连），避免订阅里 "MATCH,SELECT" 之类规则把所有流量推进代理。
    """
    try:
        import yaml
        with open(path, encoding="utf-8-sig") as f:
            data = yaml.safe_load(f) or {}
        nodes = [n for n in (data.get("proxies") or [])
                 if isinstance(n, dict) and n.get("name")]
        return nodes
    except Exception:
        return []


def _build_runtime_config():
    """编译 mihomo 运行配置，返回 (runtime.yaml 路径或 None, 节点数)。

    结构（v1.13.8，参考 FlClash 的内核用法，补上自动选活）：
      · 节点源：config.json proxy_yaml 指向的订阅/自定义 yaml 优先；
        为空时用内置 config.yaml 自带的节点快照兜底。
      · mixed-port 固定 7897（与 FlClash 7890 互不冲突，也不再从订阅里
        读端口 —— 旧逻辑订阅写 7890 就监听 7890，和 FlClash 撞车风险）。
      · 代理组重写为自动收敛结构：
          AUTO   url-test 全部节点，自动选延迟最低的活节点；
          SELECT fallback，成员 = [AUTO] + 全部节点 —— 死节点自动跳过、
                 每分钟健康检查，即使程序不做任何干预也能自愈。
      · 分流规则/dns/log-level 沿用内置 config.yaml 模板。
    """
    import yaml
    base = {}
    try:
        with open(MIHOMO_CONFIG, encoding="utf-8-sig") as f:
            base = yaml.safe_load(f) or {}
    except Exception:
        base = {}
    nodes = []
    sub = get_proxy_yaml()
    if sub and os.path.isfile(sub):
        nodes = _load_proxy_nodes(sub)
    if not nodes:
        nodes = [n for n in (base.get("proxies") or [])
                 if isinstance(n, dict) and n.get("name")]
    if not nodes:
        return None, 0
    names = [str(n["name"]) for n in nodes]
    cfg = dict(base) if isinstance(base, dict) else {}
    cfg["mixed-port"] = MIHOMO_PORT
    cfg["allow-lan"] = False
    cfg["mode"] = "rule"
    cfg["ipv6"] = False
    cfg["external-controller"] = MIHOMO_CONTROLLER
    cfg["secret"] = ""
    cfg["proxies"] = nodes
    cfg["proxy-groups"] = [
        {"name": "AUTO", "type": "url-test", "url": MIHOMO_TEST_URL,
         "interval": 300, "tolerance": 50, "proxies": names},
        {"name": "SELECT", "type": "fallback", "url": MIHOMO_TEST_URL,
         "interval": 60, "proxies": ["AUTO"] + names},
    ]
    if not cfg.get("rules"):
        cfg["rules"] = ["MATCH,SELECT"]
    try:
        os.makedirs(MIHOMO_DIR, exist_ok=True)
        with open(MIHOMO_RUNTIME_CONFIG, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False,
                           default_flow_style=False)
    except Exception as e:  # noqa: BLE001
        _mihomo_log(f"写入运行配置失败：{e}")
        return None, len(names)
    return MIHOMO_RUNTIME_CONFIG, len(names)


def _mihomo_api(path, method="GET", body=None, timeout=10):
    """调用 mihomo 控制端口 RESTful API；失败返回 None。"""
    import json as _json
    import urllib.parse
    url = MIHOMO_API + path
    data = None
    if body is not None:
        data = _json.dumps(body).encode("utf-8")
    try:
        req = urllib.request.Request(url, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "replace")
        return _json.loads(raw) if raw.strip() else {}
    except Exception:
        return None


def _proxy_http_ok(proxy, timeout=6):
    """经代理真实出网一次（gstatic 204 探测），确认"端口活着且节点可用"。"""
    try:
        import urllib.parse
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
        opener.addheaders = [("User-Agent", "Mozilla/5.0")]
        with opener.open(MIHOMO_TEST_URL, timeout=timeout) as r:
            return getattr(r, "status", 200) == 204
    except Exception:
        return False


def _group_alive_delays(group="AUTO", timeout_ms=4000):
    """让 mihomo 对组内全部节点并发测速，返回 {节点名: 延迟ms}（只含成功的）。

    对应 mihomo 扩展接口 GET /group/:name/delay；核心不支持该接口时返回 None。
    """
    import urllib.parse
    q = urllib.parse.urlencode({"url": MIHOMO_TEST_URL, "timeout": timeout_ms})
    res = _mihomo_api(f"/group/{urllib.parse.quote(group)}/delay?{q}",
                      timeout=max(12.0, timeout_ms / 1000.0 + 8.0))
    if not isinstance(res, dict):
        return None
    return {k: int(v) for k, v in res.items()
            if isinstance(v, (int, float)) and v > 0}


def _probe_each_node(names, timeout_ms=2500, workers=8):
    """逐节点测速兜底（组级接口不可用时），并发执行，返回 {节点名: 延迟ms}。"""
    import urllib.parse
    from concurrent.futures import ThreadPoolExecutor

    def _one(name):
        q = urllib.parse.urlencode(
            {"url": MIHOMO_TEST_URL, "timeout": timeout_ms})
        res = _mihomo_api(
            f"/proxies/{urllib.parse.quote(name)}/delay?{q}",
            timeout=timeout_ms / 1000.0 + 6.0)
        if isinstance(res, dict) and isinstance(res.get("delay"), (int, float)) \
                and res["delay"] > 0:
            return name, int(res["delay"])
        return name, None

    out = {}
    try:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for name, delay in ex.map(_one, names):
                if delay:
                    out[name] = delay
    except Exception:
        pass
    return out


def _pick_alive_node():
    """启动后主动收敛节点：触发 AUTO 组测速并确保 SELECT 走在活节点上。

    返回 (当前选中节点名或 None, {节点: 延迟})。链路：
      1) 组级测速（一次拿全组延迟，mihomo 内部并发）；
      2) 失败则逐节点并发兜底，找到活节点后 PUT 切换 SELECT；
      3) 都失败说明订阅节点全死，返回 (None, {})。
    """
    delays = _group_alive_delays("AUTO")
    names = []
    info = _mihomo_api("/proxies", timeout=5)
    if isinstance(info, dict):
        auto = (info.get("proxies") or {}).get("AUTO") or {}
        names = [str(n) for n in (auto.get("all") or [])]
    if delays is None:
        delays = _probe_each_node(names) if names else {}
    if not delays:
        return None, {}
    best = min(delays, key=lambda k: delays[k])
    # SELECT(fallback) 正常情况会自动落在 AUTO 上；若 fallback 卡在死节点，
    # 显式把 SELECT 切到实测最快的节点（对 select/fallback 组都合法）。
    sel = _mihomo_api("/proxies/SELECT", timeout=4)
    if isinstance(sel, dict) and sel.get("now") not in ("AUTO", best):
        _mihomo_api("/proxies/SELECT", "PUT", {"name": best}, timeout=4)
    return best, delays


def ensure_builtin_proxy():
    """确保内置 mihomo 代理可用，返回代理地址或 None。

    幂等设计：目标端口已被监听（本程序残留进程）时校验可用后复用；否则
    编译运行配置并启动 tools/mihomo/mihomo.exe（隐藏窗口）等端口就绪。

    v1.12.0：允许用户接入自己的 Clash/mihomo yaml（设置页选择，路径存
    config.json 的 proxy_yaml 键）；留空用内置配置。

    v1.13.7 修正：mihomo 的 stdout/stderr 落 logs\\mihomo.log（此前丢进
    DEVNULL，配置写错、节点不通全无痕迹）。

    v1.13.8（内置网络代理 v2）——修复"yaml 正常、下载全超时"：
      · 旧链路直接拿订阅 yaml 启动：订阅的 SELECT 组是**手选**类型，永远
        默认第一个节点；第一个节点一死（i/o timeout），所有请求跟着死，
        mihomo 不会自己换。FlClash 能用是因为有人在界面上手动选过活节点。
      · 现在改为：节点从订阅提取 → 编译成程序专用 runtime.yaml（固定
        7897 + AUTO 自动测速 + SELECT 故障切换）→ 启动后主动触发全组
        测速收敛到活节点 → 经代理真实出网 204 校验后才算"可用"。
      · 端口不再从订阅读取：mixed-port 固定 7897，避免与 FlClash(7890)
        互相复用踩踏。
    """
    global _MIHOMO_PROC
    proxy = f"http://127.0.0.1:{MIHOMO_PORT}"
    if _port_listening(MIHOMO_PORT):
        # 已在跑（本程序上次拉起的常驻实例）：校验真的能出网，不能就重新选节点
        if _proxy_http_ok(proxy):
            return proxy
        best, delays = _pick_alive_node()
        _mihomo_log("7897 已监听但 204 校验失败；重新测速%s"
                    % (f"后选中 {best}（{delays.get(best, '?')}ms）" if best else "仍无可用节点"))
        if best and _proxy_http_ok(proxy):
            return proxy
        _mihomo_log("复用失败：代理端口活着但节点不可用（订阅可能已过期）")
        return None
    if not os.path.isfile(MIHOMO_EXE):
        _mihomo_log(f"缺少 mihomo 可执行文件：{MIHOMO_EXE}")
        return None
    runtime, n_nodes = _build_runtime_config()
    cfg_path = runtime or MIHOMO_CONFIG
    if runtime is None:
        if n_nodes == 0:
            _mihomo_log("订阅/内置配置里没有可用节点（proxies 为空），无法启动")
            return None
        cfg_path = MIHOMO_CONFIG
    try:
        os.makedirs(MIHOMO_DIR, exist_ok=True)
        os.makedirs(LOGS_DIR, exist_ok=True)
        handle = open(MIHOMO_LOG, "ab", buffering=0)
        handle.write(("\n=== %s 启动 mihomo（配置 %s，端口 %d）===\n"
                      % (time.strftime("%Y-%m-%d %H:%M:%S"), cfg_path, MIHOMO_PORT)
                      ).encode("utf-8"))
        _MIHOMO_PROC = subprocess.Popen(
            [MIHOMO_EXE, "-d", MIHOMO_DIR, "-f", cfg_path],
            stdin=subprocess.DEVNULL, stdout=handle, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception as e:  # noqa: BLE001
        _mihomo_log(f"启动 mihomo 失败：{e}")
        return None
    # 等待端口就绪（AUTO 组节点首次测速约需数秒）
    for _ in range(40):
        if _port_listening(MIHOMO_PORT):
            break
        if _MIHOMO_PROC.poll() is not None:
            _mihomo_log(f"mihomo 进程已退出（exit={_MIHOMO_PROC.returncode}），"
                        "多为配置语法错误或端口被占用；详见本文件上文输出")
            return None
        time.sleep(0.5)
    else:
        _mihomo_log(f"等待 20 秒后 127.0.0.1:{MIHOMO_PORT} 仍未监听")
        return None
    # 首次收敛：主动测速，让 AUTO/fallback 立刻落在活节点上（不等周期检查）
    best, delays = _pick_alive_node()
    if best:
        _mihomo_log(f"节点测速完成：{len(delays)} 个可用，当前 {best}"
                    f"（{delays[best]}ms）")
    else:
        _mihomo_log("警告：全部节点测速失败 —— 订阅可能已过期，"
                    "请在 FlClash 里更新订阅后重新导出，或在设置页更换代理配置")
    if _proxy_http_ok(proxy):
        return proxy
    _mihomo_log("mihomo 已启动，但经代理出网校验失败（节点全部不可达？）")
    return None


#: 代理地址缓存（进程内）。ensure_builtin_proxy 每次都要探测端口/等 20 秒，
#: 而下载链路每个任务、每次拉字幕都会问一次，必须记住结果。
_PROXY_CACHE = {"checked": False, "proxy": None}


def ytdlp_proxy_args(refresh=False):
    """给 yt-dlp 的 `--proxy` 参数表；拿不到代理时返回 []（退回直连）。

    为什么下载链路必须带这个：`ensure_builtin_proxy()` 此前只服务于 GitHub
    相关请求，yt-dlp 全程直连 —— 在国内那就是"YouTube 永远连不上"。带上本地
    mihomo 之后，分流仍由 yaml 的 rules 决定（规则没覆盖的域名它自己也走
    直连），所以对 B 站等本来直连的站点没有副作用。
    """
    if not refresh and _PROXY_CACHE["checked"]:
        return ["--proxy", _PROXY_CACHE["proxy"]] if _PROXY_CACHE["proxy"] else []
    proxy = None
    try:
        proxy = ensure_builtin_proxy()
    except Exception as e:  # noqa: BLE001
        _mihomo_log(f"ensure_builtin_proxy 异常：{e}")
    _PROXY_CACHE["checked"] = True
    _PROXY_CACHE["proxy"] = proxy
    return ["--proxy", proxy] if proxy else []


def proxy_status():
    """给界面用：(是否可用, 代理地址或空, 一句话说明)。附当前节点名。"""
    args = ytdlp_proxy_args()
    if args:
        info = _mihomo_api("/proxies/SELECT", timeout=3)
        now = info.get("now") if isinstance(info, dict) else None
        if now:
            return True, args[1], f"代理可用：{args[1]}（当前节点：{now}）"
        return True, args[1], "代理可用：" + args[1]
    if not os.path.isfile(MIHOMO_EXE):
        return False, "", "未安装内置代理组件（tools\\mihomo\\mihomo.exe）"
    return False, "", "代理未能启动或节点不可用，详见 logs\\mihomo.log"


def get_proxy_yaml():
    """用户接入的 Clash/mihomo yaml（多为机场订阅导出）；空 = 内置节点快照。

    v1.13.8 起语义变化：这份文件只用来**提取节点（proxies 段）**，端口与
    分流规则由引擎编译进 runtime.yaml（固定 7897），不再整份直接启动。
    """
    return str(load_config().get("proxy_yaml", "")).strip()


def set_proxy_yaml(path):
    """记住用户自定义代理 yaml 路径（长期固定）；空串 = 恢复内置默认。

    文件必须存在；仅做存在性校验，格式/端口在 ensure_builtin_proxy 时解析
    （解析失败回退默认端口 7897）。
    """
    path = clean_path(str(path or "")).strip()
    if path:
        path = os.path.abspath(path)
        if not os.path.isfile(path):
            raise FileNotFoundError(path)
    cfg = load_config()
    cfg["proxy_yaml"] = path
    save_config(cfg)
    return path


def _proxy_yaml_port(path):
    """从 Clash/mihomo yaml 解析监听端口（mixed-port > port > socks-port）。"""
    try:
        import yaml
        with open(path, encoding="utf-8-sig") as f:
            data = yaml.safe_load(f)
        if isinstance(data, dict):
            for key in ("mixed-port", "port", "socks-port"):
                try:
                    val = int(data.get(key) or 0)
                except (TypeError, ValueError):
                    continue
                if 0 < val < 65536:
                    return val
    except Exception:
        pass
    return None


def _stop_builtin_proxy():
    global _MIHOMO_PROC
    if _MIHOMO_PROC is not None and _MIHOMO_PROC.poll() is None:
        try:
            _MIHOMO_PROC.terminate()
        except OSError:
            pass
    _MIHOMO_PROC = None


atexit.register(_stop_builtin_proxy)


# ========== 校准知识同步（v1.12.2：GitHub 整文件通道收集 + 可选本地增量镜像） ==========
# 架构：
#   · 更新（界面唯一入口，启动自动 + 手动）：从内置 github_proxy.yaml 指向的
#     GitHub 仓库拉取全体使用者沉淀，条目级三方合并进本地；若管理员另配了
#     共享更新库（VT_SYNC_ROOT 下有 baseline.json），叠加本地增量镜像 kb-sync；
#   · 上传：全自动、隐藏在后台——learn 实时写本地学习库，退出程序时派生
#     隐藏子进程把「校准脚本 + 学习库」推回 GitHub（先拉后推，互不覆盖），
#     镜像启用时同时 kb-push 进收件箱；界面上不存在任何上传按钮；
#   · 折叠基线、清理更新库等管理动作全部在独立程序 kb_admin.exe。
# 连接参数统一在 github_proxy.yaml 的 vt-github 段（owner/repo/branch/api/
#   token/files），改仓库只动 yaml。
# 策略：静默、不阻塞、不弹窗，结果写 logs/calib_sync.log；失败一律降级为
#   "本地功能照常可用"，绝不因同步失败影响校准。
SYNC_LOG = os.path.join(LOGS_DIR, "calib_sync.log")
#: 用户侧同步脚本与更新库路径（打包后随包分发在程序根目录）
CALIB_SCRIPT = os.path.join(APP_DIR, "subtitle_calib_merged.py")
CALIB_KB_PATH = os.path.join(APP_DIR, "subtitle_learned_kb.json")
#: 更新库根目录（管理员维护、可指向网络盘）与本机同步状态目录
SYNC_REMOTE_DIR = os.path.join(DATA_DIR, "calib_sync_remote")
SYNC_LOCAL_DIR = os.path.join(DATA_DIR, "calib_sync")


def _sync_log(msg):
    """追加一行同步日志（best-effort，绝不因日志失败影响主流程）。"""
    try:
        os.makedirs(LOGS_DIR, exist_ok=True)
        with open(SYNC_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")
    except OSError:
        pass


def sync_env_into(env):
    """给校准/同步子进程补齐增量通道路径变量（外部显式设置优先，setdefault 语义）。

    引擎导入时对 os.environ 调用一次：此后所有子进程（校准 worker、AI 校准、
    同步子进程）自动继承，保证 learn 自动上传、退出补传、启动更新指向同一库。
    """
    env.setdefault("VT_DATA_ROOT", DATA_ROOT)
    env.setdefault("VT_SYNC_ROOT", SYNC_REMOTE_DIR)
    env.setdefault("VT_SYNC_DIR", SYNC_LOCAL_DIR)
    env.setdefault("VT_SYNC_KB", CALIB_KB_PATH)
    return env


for _d in (SYNC_REMOTE_DIR, SYNC_LOCAL_DIR):
    try:
        os.makedirs(_d, exist_ok=True)
    except OSError:
        pass
sync_env_into(os.environ)


def _calib_py():
    """跑增量通道子命令的 Python：工具箱内嵌运行时优先，其次系统 python。

    拿不到可用解释器时返回 ""（调用方据此跳过），**绝不回退到 exe 自身**——
    打包后 sys.executable 就是本程序，拿它 Popen 会拉起一个新实例。
    """
    py = system_python()
    if not py or _is_self_exe(py) or not os.path.isfile(py):
        return ""
    return py


# ---------- GitHub 整文件通道（v1.12.2 恢复：收集各使用者校准增量） ----------
# 连接参数统一来自内置 github_proxy.yaml 的 vt-github 段（owner/repo/branch/
# api/token/files）；改仓库或加同步文件只动 yaml、不动代码。上传全部自动、
# 隐藏在后台完成（退出时自动推送）；界面只保留「更新」。
# 全程静默、直连失败回退内置 mihomo 代理、任何异常只写 logs/calib_sync.log，
# 绝不影响校准主流程。
GITHUB_PROXY_YAML = os.path.join(APP_DIR, "github_proxy.yaml")
#: yaml 缺失/解析失败时的兜底默认（与内置 yaml 的 vt-github 段一致）
_SYNC_CONN_DEFAULTS = {
    "owner": "09Th90", "repo": "VideoToolbox", "branch": "main",
    "api": "https://api.github.com", "token": "",
    "files": ["subtitle_calib_merged.py", "subtitle_learned_kb.json"],
}
#: 兼容旧引用（自检/文档仍以此名访问）；实际目标文件以 yaml files 段为准
SYNC_REL_PATH = _SYNC_CONN_DEFAULTS["files"][0]
SYNC_KB_REL_PATH = _SYNC_CONN_DEFAULTS["files"][1]
#: 上次同步成功内容快照 = 条目级三方合并的「公共祖先」（放数据根，不入库不分发）
CALIB_BASE_SNAPSHOT = os.path.join(DATA_DIR, "calib_sync_base.py")
CALIB_KB_BASE_SNAPSHOT = os.path.join(DATA_DIR, "calib_sync_kb_base.json")

_SYNC_CONN_CACHE = None


def _sync_conn(refresh=False):
    """读内置 github_proxy.yaml 的 vt-github 段（模块级缓存；缺字段用默认补齐）。"""
    global _SYNC_CONN_CACHE
    if _SYNC_CONN_CACHE is not None and not refresh:
        return _SYNC_CONN_CACHE
    cfg = {k: (list(v) if isinstance(v, list) else v)
           for k, v in _SYNC_CONN_DEFAULTS.items()}
    try:
        import yaml
        with open(GITHUB_PROXY_YAML, encoding="utf-8-sig") as f:
            data = yaml.safe_load(f) or {}
        vg = data.get("vt-github") or {}
        for key in ("owner", "repo", "branch", "api", "token"):
            val = str(vg.get(key) or "").strip()
            if val:
                cfg[key] = val
        files = vg.get("files")
        if isinstance(files, list) and files:
            cfg["files"] = [str(p).strip() for p in files if str(p).strip()]
    except Exception as e:  # noqa: BLE001  解析失败退回默认，不阻断同步
        _sync_log(f"读取 github_proxy.yaml 失败，改用内置默认连接：{e}")
    if not refresh:
        _SYNC_CONN_CACHE = cfg
    return cfg


def _gh_token(cfg=None):
    """取 GitHub token：内置 yaml 显式配置 > 环境变量 > gh keyring；取不到返回空串。"""
    cfg = cfg or _sync_conn()
    tok = (cfg.get("token") or "").strip()
    if tok:
        return tok
    tok = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if tok:
        return tok.strip()
    for exe in ("gh", os.path.join(TOOLS_DIR, "gh.exe")):
        try:
            p = run_process([exe, "auth", "token"], capture_output=True,
                            text=True, timeout=15)
            if p.returncode == 0 and p.stdout.strip():
                return p.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            continue
    return ""


def _gh_request(method, path, token, payload=None, proxy="", timeout=30):
    """访问 GitHub API（用 curl，避开 requests 的代理问题）。返回 (ok, 数据或错误)。"""
    url = f"{_sync_conn()['api']}/{path}"
    cmd = ["curl", "-sS", "--max-time", str(timeout), "-X", method]
    if proxy:
        cmd += ["-x", proxy]
    if token:  # 公开库匿名读时不带认证头
        cmd += ["-H", f"Authorization: Bearer {token}"]
    cmd += ["-H", "Accept: application/vnd.github+json",
            "-H", "X-GitHub-Api-Version: 2022-11-28",
            "-H", "User-Agent: VideoToolbox-sync",
            "-w", "\n%{http_code}"]
    stdin = b""
    if payload is not None:
        cmd += ["-H", "Content-Type: application/json", "--data-binary", "@-"]
        stdin = json.dumps(payload).encode("utf-8")
    cmd.append(url)
    try:
        p = run_process(cmd, input=stdin, capture_output=True,
                        timeout=timeout + 10)
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"curl 调用失败: {e}"
    if p.returncode != 0:
        return False, f"curl 退出码 {p.returncode}: {decode_bytes_any(p.stderr)[:150]}"
    body, _, code = decode_bytes_any(p.stdout).rpartition("\n")
    try:
        code = int(code.strip() or 0)
    except ValueError:
        code = 0
    if code >= 400:
        return False, f"HTTP {code}: {body[:200]}"
    try:
        return True, (json.loads(body) if body.strip() else {})
    except ValueError:
        return True, {}


def _gh_request_any(method, path, token, payload=None):
    """先直连，失败再走内置代理（仅 GitHub 流量）。认证/参数类错误不重试代理。"""
    ok, data = _gh_request(method, path, token, payload)
    if ok:
        return True, data
    msg = str(data)
    if any(code in msg for code in ("HTTP 401", "HTTP 403", "HTTP 404", "HTTP 422")):
        return False, data
    _sync_log(f"直连 {method} {path} 失败（{msg[:80]}），改用内置代理")
    proxy = ensure_builtin_proxy()
    if not proxy:
        return False, f"{data}；内置代理不可用"
    return _gh_request(method, path, token, payload, proxy=proxy)


def _gh_fetch_file(token, rel_path, cfg):
    """拉仓库单文件最新内容。返回 (ok, 文本或错误, blob_sha)；公开库可匿名读。"""
    path = (f"repos/{cfg['owner']}/{cfg['repo']}/contents/{rel_path}"
            f"?ref={cfg['branch']}")
    ok, data = _gh_request_any("GET", path, token)
    if not ok:
        return False, str(data), ""
    try:
        content = data.get("content")
        if not content and data.get("git_url"):
            blob_path = str(data["git_url"]).replace(cfg["api"] + "/", "")
            ok2, blob = _gh_request_any("GET", blob_path, token)
            if not ok2:
                return False, str(blob), ""
            data, content = blob, blob.get("content")
        text = decode_bytes_any(base64.b64decode(content or ""))
        return True, text, data.get("sha", "")
    except (ValueError, KeyError, TypeError, OSError) as e:
        return False, f"解码失败: {e}", ""


def _read_sync_text(path):
    """读同步目标文件（兼容 UTF-8/GBK/无 BOM）；不存在返回空串。"""
    try:
        return read_text_any(path)
    except OSError:
        return ""


def _atomic_write(path, text):
    """原子写回同步文件：先写同目录临时文件再 os.replace，避免半截文件。"""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp = path + ".vt_tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    os.replace(tmp, path)


def _pull_and_merge(token, rel_path, base_path, cfg):
    """拉远程单文件与本地做条目级三方合并，结果回写本地与基线。返回本地是否有更新。

    files 段第一个同步文件视为「校准脚本」（走 merge_calib_script），其余视为
    「学习库」（走 merge_learned_kb）。任何失败只记日志，绝不阻断启动/退出。"""
    is_script = (rel_path == cfg["files"][0])
    local_path = os.path.join(APP_DIR, rel_path)
    local_text = _read_sync_text(local_path)
    base_text = _read_sync_text(base_path)
    ok, remote_text, _sha = _gh_fetch_file(token, rel_path, cfg)
    if not ok:
        _sync_log(f"拉取[{rel_path}]跳过合并：{str(remote_text)[:100]}")
        return False
    if not local_text.strip():
        _atomic_write(local_path, remote_text)
        _atomic_write(base_path, remote_text)
        _sync_log(f"拉取[{rel_path}]：本地缺失，已采用远程版（{len(remote_text)} 字符）")
        return True
    if remote_text == local_text:
        if base_text != local_text:
            _atomic_write(base_path, local_text)
        return False
    if is_script:
        merged, added, conflicts = merge_calib_script(local_text, remote_text, base_text)
    else:
        merged, added, conflicts = merge_learned_kb(local_text, remote_text)
    if merged == local_text:
        if conflicts:
            _sync_log(f"合并[{rel_path}]：无可并入"
                      f"（{'; '.join(str(c) for c in conflicts)[:200]}）")
        return False
    _atomic_write(local_path, merged)
    _atomic_write(base_path, merged)
    n_conf = len(conflicts) if isinstance(conflicts, list) else conflicts
    _sync_log(f"合并[{rel_path}]：并入 {added} 条，冲突 {n_conf} 条（保留本地）")
    return True


def sync_calib_to_github(cfg=None):
    """把本地校准脚本与学习库推到 GitHub（推送前先拉远程合并；静默，返回 (ok, 说明)）。"""
    cfg = cfg or _sync_conn()
    token = _gh_token(cfg)
    if not token:
        _sync_log("跳过上传：未取得 GitHub token（需 gh auth login 或设 GH_TOKEN）")
        return False, "未取得 GitHub token"
    # 先拉远程把他人增量并进来再推，多用户互不覆盖、最终收敛到并集
    for idx, rel in enumerate(cfg["files"]):
        base_path = (CALIB_BASE_SNAPSHOT if idx == 0 else CALIB_KB_BASE_SNAPSHOT)
        _pull_and_merge(token, rel, base_path, cfg)
    entries = []  # (rel, bytes, text)
    for rel in cfg["files"]:
        try:
            with open(os.path.join(APP_DIR, rel), "rb") as f:
                b = f.read()
            entries.append((rel, b, decode_bytes_any(b)))
        except (OSError, UnicodeDecodeError) as e:
            if rel == cfg["files"][0]:
                _sync_log(f"跳过上传：读取失败 {e}")
                return False, f"读取失败: {e}"
            _sync_log(f"上传[{rel}]跳过：{e}")
    base = f"repos/{cfg['owner']}/{cfg['repo']}"
    ok, head = _gh_request_any("GET", f"{base}/git/ref/heads/{cfg['branch']}", token)
    if not ok:
        _sync_log(f"失败：读取分支 head {head}")
        return False, f"读取分支失败: {head}"
    head_sha = head["object"]["sha"]
    ok, commit = _gh_request_any("GET", f"{base}/git/commits/{head_sha}", token)
    if not ok:
        return False, f"读取 commit 失败: {commit}"
    base_tree = commit["tree"]["sha"]
    tree_entries = []
    for rel, b, _text in entries:
        ok, blob = _gh_request_any("POST", f"{base}/git/blobs", token, {
            "content": base64.b64encode(b).decode("ascii"), "encoding": "base64"})
        if not ok:
            return False, f"创建 blob 失败: {blob}"
        tree_entries.append({"path": rel, "mode": "100644",
                             "type": "blob", "sha": blob["sha"]})
    ok, tree = _gh_request_any("POST", f"{base}/git/trees", token, {
        "base_tree": base_tree, "tree": tree_entries})
    if not ok:
        return False, f"创建 tree 失败: {tree}"
    ok, new_commit = _gh_request_any("POST", f"{base}/git/commits", token, {
        "message": (f"chore(calib): 同步校准知识 "
                    f"（{datetime.now():%Y-%m-%d %H:%M:%S}，来自视频工具箱）"),
        "tree": tree["sha"], "parents": [head_sha]})
    if not ok:
        return False, f"创建 commit 失败: {new_commit}"
    ok, res = _gh_request_any("PATCH", f"{base}/git/refs/heads/{cfg['branch']}",
                              token, {"sha": new_commit["sha"], "force": False})
    if not ok:
        return False, f"更新分支失败: {res}"
    _sync_log(f"成功：已上传 {len(entries)} 个文件 -> {cfg['owner']}/{cfg['repo']}"
              f"@{cfg['branch']} commit {new_commit['sha'][:12]}")
    # 推送成功：基线快照对齐本次内容（下次三方合并的公共祖先）
    for idx, (rel, _b, text) in enumerate(entries):
        try:
            _atomic_write(CALIB_BASE_SNAPSHOT if idx == 0
                          else CALIB_KB_BASE_SNAPSHOT, text)
        except OSError as e:
            _sync_log(f"基线快照写入失败[{rel}]（忽略）: {e}")
    return True, f"已上传 commit {new_commit['sha'][:12]}"


# ---------- 本地增量镜像（可选：管理员配了共享盘更新库才启用） ----------
def _local_delta_enabled():
    """VT_SYNC_ROOT 下存在 baseline.json 才启用 kb-sync/kb-push 增量镜像。"""
    try:
        root = os.environ.get("VT_SYNC_ROOT") or SYNC_REMOTE_DIR
        return os.path.isfile(os.path.join(root, "baseline.json"))
    except OSError:
        return False


def sync_calib_push_local():
    """退出子进程内部调用：把学习库新增增量写进本地更新库收件箱（若启用镜像）。"""
    try:
        if not _local_delta_enabled():
            return
        py = _calib_py()
        if not py or not os.path.isfile(CALIB_SCRIPT):
            return
        env = sync_env_into(os.environ.copy())
        env.setdefault("PYTHONIOENCODING", "utf-8")
        run_process([py, CALIB_SCRIPT, "kb-push", "--learned", CALIB_KB_PATH],
                    capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=120, cwd=APP_DIR, env=env)
    except Exception as e:  # noqa: BLE001
        _sync_log(f"本地增量上传异常（忽略）: {e}")


def _exit_sync_child_script():
    """退出子进程入口源码：本地增量补传（若启用镜像）+ GitHub 整文件上传。"""
    src_dir = os.path.join(APP_DIR, "src")
    return ("import sys; sys.path.insert(0, r'%s');"
            "import video_toolbox as e;"
            "e.sync_calib_push_local();"
            "e.sync_calib_to_github()" % src_dir)


def sync_calib_on_startup(force=False):
    """更新：从 GitHub 拉全体使用者沉淀并条目级合并进本地；可选叠加本地增量镜像。

    幂等、静默、best-effort；任何失败只写日志，本地校准功能照常可用。
    force 为兼容设置页「立即更新」参数，可忽略。"""
    try:
        if os.environ.get("VT_NO_CALIB_SYNC") or not calib_sync_enabled():
            return False, "同步已禁用"
        updated, notes = False, []
        # 1) GitHub 整文件通道（默认收集渠道；公开库可匿名读）
        cfg = _sync_conn()
        token = _gh_token(cfg)
        for idx, rel in enumerate(cfg["files"]):
            base_path = (CALIB_BASE_SNAPSHOT if idx == 0 else CALIB_KB_BASE_SNAPSHOT)
            if _pull_and_merge(token, rel, base_path, cfg):
                updated = True
                notes.append(rel)
        # 2) 本地增量镜像（管理员配置了共享盘更新库时）
        py = _calib_py()
        if py and os.path.isfile(CALIB_SCRIPT) and _local_delta_enabled():
            env = sync_env_into(os.environ.copy())
            env.setdefault("PYTHONIOENCODING", "utf-8")
            try:
                p = run_process([py, CALIB_SCRIPT, "kb-sync"],
                                capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=180, cwd=APP_DIR, env=env)
                if p.returncode == 0:
                    updated = True
                    notes.append("本地增量")
                else:
                    _sync_log(f"本地增量更新失败（降级）：rc={p.returncode}")
            except Exception as e:  # noqa: BLE001
                _sync_log(f"本地增量更新异常（忽略）: {e}")
        if updated:
            _sync_log("更新完成：" + "、".join(notes))
            return True, "校准知识已更新（" + "、".join(notes) + "）"
        return False, "无可用更新或已是最新"
    except Exception as e:  # noqa: BLE001
        _sync_log(f"更新异常（忽略）: {e}")
        return False, str(e)


def sync_calib_on_exit():
    """退出时自动上传：派生隐藏子进程完成「本地增量补传 + GitHub 整文件上传」。

    用子进程而非线程：主进程退出后线程会被强杀，子进程能自行跑完。
    上传对用户完全无感——不阻塞退出、不弹窗、不出现在任何界面。"""
    try:
        if os.environ.get("VT_NO_CALIB_SYNC") or not calib_sync_enabled():
            return
        py = _calib_py()
        if not py:
            _sync_log("退出上传跳过：无可用 Python 运行时")
            return
        env = sync_env_into(os.environ.copy())
        env.setdefault("PYTHONIOENCODING", "utf-8")
        popen_process([py, "-c", _exit_sync_child_script()],
                      stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL, cwd=APP_DIR, env=env,
                      close_fds=True)
        _sync_log("已派生退出上传子进程（GitHub 整文件 + 本地增量）")
    except Exception as e:  # noqa: BLE001
        _sync_log(f"派生退出上传子进程失败（忽略）: {e}")


# ---------- 条目级三方合并（v1.10.8：纯函数核心抽到 calib_merge_core） ----------
# 多用户知识收敛的合并算法是纯函数、零副作用，统一放在 calib_merge_core，
# 便于 GUI 引擎、退出同步子进程与脚本/CI 复用；这里只做导入并保留向后兼容
# 别名（自检与外部仍以 engine.merge_* 调用），并把合并期日志接到同步日志。
#
# 同步语义保持 v1.10.7 的对等并集模型（用户最终拍板，不采用 contrib/CI
# 中心化方案）：启动自动拉取 GitHub main 最新校准知识并把其他用户沉淀的
# 新条目并入本地；退出时先把远程新内容并进来再推送，多用户互不覆盖，
# 所有人的脚本最终收敛到全体条目的并集。
from calib_merge_core import (
    _MERGE_MISSING,
    _ast_module_tables,
    _dict_entries,
    _entity_fields,
    _registry_conflicts,
    merge_calib_script,
    merge_learned_kb,
)
import calib_merge_core as _calib_core
_calib_core._log = _sync_log  # 合并期冲突日志写入 logs/calib_sync.log


def _download(url, dest, label, use_proxy=True):
    """下载文件；直连失败时自动启用内置代理重试（GitHub/HuggingFace 等开源库场景）。"""
    print(f"[setup] 正在下载 {label} ...")
    try:
        urllib.request.urlretrieve(url, dest)
        return
    except Exception as e:
        if not use_proxy:
            raise
        print(f"[setup] 直连失败（{e}），启用内置代理重试 ...")
        proxy = ensure_builtin_proxy()
        if not proxy:
            print("[setup] 内置代理不可用，下载失败")
            raise
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
        try:
            with opener.open(url, timeout=180) as resp, open(dest, "wb") as f:
                shutil.copyfileobj(resp, f)
            print("[setup] 代理下载完成")
        except Exception as e2:
            raise RuntimeError(f"直连与代理下载均失败: {e2}") from e2


def _ensure_deno():
    """yt-dlp 提取 YouTube 需要 JS 运行时 deno；缺失时自动下载到 tools\\deno.exe。

    官方源失败时尝试 gh-proxy 镜像（镜像直连通常可用，不需代理）；
    仍失败仅提示，不阻断 yt-dlp 使用。
    """
    if os.path.isfile(DENO_PATH):
        return True
    os.makedirs(TOOLS_DIR, exist_ok=True)
    zip_path = os.path.join(TOOLS_DIR, "deno.zip")
    import zipfile
    for tag, url in (("官方源", DENO_URL), ("镜像", DENO_MIRROR_URL)):
        try:
            print(f"[setup] 正在下载 deno（YouTube 提取所需 JS 运行时，约 43MB）{tag} ...")
            _download(url, zip_path, "deno")
            with zipfile.ZipFile(zip_path) as z:
                with z.open("deno.exe") as src, open(DENO_PATH, "wb") as dst:
                    dst.write(src.read())
            try:
                os.remove(zip_path)
            except OSError:
                pass
            print(f"[setup] deno 就绪: {DENO_PATH}")
            return True
        except Exception as e:
            print(f"[setup] deno 下载失败（{tag}: {e}）")
    print("[setup] deno 下载失败；YouTube 提取可能不稳定。"
          "可手动下载 deno-x86_64-pc-windows-msvc.zip 解压出 deno.exe 放到 "
          f"{TOOLS_DIR} 目录")
    return False


def ensure_ytdlp():
    with _BOOTSTRAP_LOCK:
        if os.path.isfile(YTDLP_PATH):
            _ensure_deno()
            return YTDLP_PATH
        os.makedirs(TOOLS_DIR, exist_ok=True)
        _download(YTDLP_URL, YTDLP_PATH, "yt-dlp")
        return YTDLP_PATH


def ensure_ffmpeg():
    """返回 (ffmpeg, ffprobe) 路径；优先 tools 目录，其次系统 PATH，最后自动下载"""
    if os.path.isfile(FFMPEG_PATH) and os.path.isfile(FFPROBE_PATH):
        return FFMPEG_PATH, FFPROBE_PATH
    with _BOOTSTRAP_LOCK:
        if os.path.isfile(FFMPEG_PATH) and os.path.isfile(FFPROBE_PATH):
            return FFMPEG_PATH, FFPROBE_PATH
        sys_ff = shutil.which("ffmpeg")
        sys_fp = shutil.which("ffprobe")
        if sys_ff and sys_fp:
            return sys_ff, sys_fp
        os.makedirs(TOOLS_DIR, exist_ok=True)
        zip_path = os.path.join(TOOLS_DIR, "ffmpeg.zip")
        _download(FFMPEG_ZIP_URL, zip_path, "ffmpeg（约 170MB，仅首次）")
        with zipfile.ZipFile(zip_path) as z:
            for name in z.namelist():
                low = name.replace("\\", "/").lower()
                if low.endswith("/bin/ffmpeg.exe"):
                    with z.open(name) as src, open(FFMPEG_PATH, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                elif low.endswith("/bin/ffprobe.exe"):
                    with z.open(name) as src, open(FFPROBE_PATH, "wb") as dst:
                        shutil.copyfileobj(src, dst)
        os.remove(zip_path)
        if not (os.path.isfile(FFMPEG_PATH) and os.path.isfile(FFPROBE_PATH)):
            print("[错误] ffmpeg 解压失败")
            sys.exit(1)
        return FFMPEG_PATH, FFPROBE_PATH


MPV_DLL_URL = ("https://github.com/09Th90/VideoToolbox/releases/download/"
               "deps-mpv-lgpl-20260914/libmpv-2.zip")


def ensure_mpv_dll(mpv_dir):
    """确保 <mpv_dir>\\libmpv-2.dll 就位；缺失时从自有 release 下载解压。

    v1.14.1：字幕编辑页的播放组件（LGPL 构建）不随安装包分发，而原提示
    让用户手动跑 tools\\download_open_source_deps.py——该脚本既不进 exe
    也不随安装包分发，对安装版用户等于死路。这里内联最小实现：复用
    _download（直连失败自动走内置 mihomo 代理），zip 约 39MB、解压约 95MB。

    返回 (True, "") 或 (False, 错误说明)。供界面在后台线程调用。
    """
    dll = os.path.join(mpv_dir, "libmpv-2.dll")
    if os.path.isfile(dll) and os.path.getsize(dll) > 10 * 1024 * 1024:
        return True, ""
    os.makedirs(mpv_dir, exist_ok=True)
    zpath = os.path.join(TOOLS_DIR, "_libmpv.zip")
    try:
        _download(MPV_DLL_URL, zpath, "libmpv 播放组件（约 39MB，仅首次）")
        with zipfile.ZipFile(zpath) as z:
            name = next(n for n in z.namelist()
                        if n.replace("\\", "/").lower().endswith("libmpv-2.dll"))
            with z.open(name) as src, open(dll + ".part", "wb") as dst:
                shutil.copyfileobj(src, dst)
        os.replace(dll + ".part", dll)
        return True, ""
    except Exception as e:  # noqa: BLE001
        return False, ("下载/解压 libmpv-2.dll 失败：%s\n"
                       "可到发布页手动下载 %s 解压到 %s"
                       % (e, MPV_DLL_URL, mpv_dir))
    finally:
        try:
            if os.path.isfile(zpath):
                os.remove(zpath)
        except OSError:
            pass


# =============================


# ========== 通用小函数 ==========
def clean_path(path):
    path = path.strip()
    if len(path) >= 2 and ((path[0] == '"' and path[-1] == '"') or (path[0] == "'" and path[-1] == "'")):
        path = path[1:-1]
    return path.strip()


def format_size(size_bytes):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.2f} TB"


def format_time(seconds):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}.{ms:03d}"
    return f"{minutes:02d}:{secs:02d}.{ms:03d}"


def open_folder(path):
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)
    except Exception:
        pass
# =============================


# ========== 功能 1：视频下载 ==========
def extract_url(arg):
    """从 .url 快捷方式 / 文本文件 / 原始字符串中提取第一个 http 链接"""
    if os.path.isfile(arg):
        try:
            text = read_text_any(arg)
        except Exception:
            return None
        m = URL_RE.search(text)
        return m.group(0) if m else None
    m = URL_RE.search(arg)
    return m.group(0) if m else None


def fetch_info_json(ytdlp, url, attempts=4, log=None, wait_base=5):
    """运行 yt-dlp -J 获取视频信息原始 JSON。

    部分站点（如 B 站）对无 cookie 的连续请求有风控，随机返回 HTTP 412；
    YouTube 等站点在无 JS 运行时 / 网络抖动 / 风控时也会间歇失败（403/429/
    "Sign in to confirm" / 连接被重置等）。这里把网络类与风控类错误都纳入
    自动重试，并把每一次的具体失败原因透出给 log，方便定位问题。
    log 为可选回调，用于向 GUI / 命令行透出重试进度与错误详情。
    """
    def _log(msg):
        if log:
            try:
                log(msg)
            except Exception:
                pass

    # 命中任一关键词即视为可重试的临时性失败；不含这些词的错误（如参数错误）
    # 直接放弃，避免无意义等待。
    RETRY_HINTS = ("412", "429", "403", "502", "503", "timed out",
                   "timeout", "Unable to download webpage", "Unable to extract",
                   "Sign in to confirm", "bot check", "bot detection",
                   "network", "Connection", "connection", "socket",
                   "Temporary failure", "EOF", "reset", "Remote end closed",
                   "Name or service not known", "SSL", "TLS")

    def _detail(err_text):
        """从输出里提取最后一行 ERROR 或非空行，作为给用户看的失败原因。"""
        lines = [ln.strip() for ln in err_text.splitlines() if ln.strip()]
        for ln in reversed(lines):
            if "ERROR:" in ln or "Error" in ln or "error" in ln:
                return ln[:200]
        return lines[-1][:200] if lines else "未知错误"

    # 走本地代理（有则用、无则直连）：YouTube 在国内必须经代理才能提取信息
    proxy_args = ytdlp_proxy_args()
    if proxy_args:
        _log(f"[信息] 提取视频信息经代理 {proxy_args[1]}")
    for i in range(attempts):
        result = run_process([ytdlp, "-J", "--no-playlist", url, *proxy_args],
                             capture_output=True)
        out = decode_bytes_any(result.stdout)
        if result.returncode == 0 and out.strip().startswith("{"):
            return out
        err = decode_bytes_any(result.stderr) + out
        detail = _detail(err)
        if i < attempts - 1:
            _log(f"[信息] 提取失败（{i + 1}/{attempts}）: {detail}")
        retryable = any(k.lower() in err.lower() for k in RETRY_HINTS)
        if not retryable or i == attempts - 1:
            _log(f"[错误] 画质提取失败: {detail}")
            return None
        wait = wait_base * (i + 1)
        _log(f"[信息] {wait}s 后自动重试 ...")
        time.sleep(wait)
    return None


def parse_qualities(json_text):
    """解析 -J JSON：仅 >=720p；同分辨率优先 60fps，再取文件最大者。按分辨率降序返回"""
    data = json.loads(json_text)

    groups = {}
    for f in data.get("formats", []):
        h = f.get("height") or 0
        if f.get("vcodec") in (None, "none") or h < 720:
            continue
        groups.setdefault(h, []).append(f)

    best = []
    for h, items in groups.items():
        hi_fps = [f for f in items if (f.get("fps") or 0) > 30]
        pool = hi_fps if hi_fps else items
        top = max(pool, key=lambda f: f.get("filesize") or f.get("filesize_approx") or 0)
        best.append(top)
    best.sort(key=lambda f: f.get("height") or 0, reverse=True)
    return best


def save_info_json(json_text):
    """把 -J 结果写入临时文件，供下载时 --load-info-json 复用，
    避免下载阶段二次提取网页再次触发站点风控。"""
    fd, path = tempfile.mkstemp(prefix="vtinfo_", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json_text)
    return path


# ---------- 每个视频独立文件夹：文件夹名 / 信息 txt / 封面 ----------
_WIN_RESERVED = {"CON", "PRN", "AUX", "NUL",
                 *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def sanitize_folder_name(name, fallback="video"):
    """把视频标题净化为 Windows 安全的文件夹名（% 会破坏 yt-dlp 输出模板，一并替换）"""
    name = re.sub(r'[\\/:*?"<>|%]', " ", str(name or ""))
    name = re.sub(r"\s+", " ", name).strip(" .")
    if not name:
        name = fallback
    if name.upper() in _WIN_RESERVED:
        name = "_" + name
    return name[:80].rstrip(" .") or fallback


def unique_folder(dest, name):
    """在 dest 下取不冲突的文件夹名；已存在的空文件夹直接复用"""
    folder = os.path.join(dest, name)
    n = 2
    while os.path.exists(folder):
        try:
            if not os.listdir(folder):
                break
        except OSError:
            pass
        folder = os.path.join(dest, f"{name} ({n})")
        n += 1
    return folder


def output_template(folder, filename_tpl="%(title)s.%(ext)s"):
    """构造 yt-dlp 的 -o 输出模板。

    yt-dlp 会把 -o 里的 % 当模板变量解析，因此保存路径中若含 %
    （例如 D:\\100%素材\\某视频）会导致下载直接报错。这里把路径部分的
    % 转义为 %%，模板占位符保持原样。
    """
    safe_folder = str(folder).replace("%", "%%")
    return os.path.join(safe_folder, filename_tpl)


# ========== 下载字幕的「滚动式重叠」整理（v1.13.7） ==========
# 平台（YouTube 等）给出的自动字幕是**滚动**结构：同一条的结束时间会一直延伸
# 到"下一条的结束"，于是整份字幕大面积互相压住（实测某 3566 条的字幕里有
# 3028 条与下一条重叠，占比 84.9%）。后果是播放时同一时刻两条并行、切轴抖动，
# 后续翻译与打轴也跟着错乱。
#
# 整理方式只有一件事：把每条压到"下一条的起始"。文本、起始时间、序号、空行、
# 换行风格（CRLF/LF）、BOM 全部原样保留 —— 实测这样处理后的结果与用户手工整理
# 出来的"正确字幕"逐条一致（3566/3566）。
_SRT_TL_RE = re.compile(
    r"^(?P<pre>[ \t]*)(?P<t1>\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})"
    r"(?P<sep>[ \t]*-->[ \t]*)"
    r"(?P<t2>\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})(?P<post>.*)$")
_SRT_TS_RE = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})([,.])(\d{1,3})")

#: 判定"滚动式字幕"的门槛：重叠占比 + 重叠条数 + 最少条数。
#: 保守取值，避免误伤"双人对话/双语对齐"这类**有意**重叠的普通字幕。
_ROLLING_RATIO = 0.15
_ROLLING_MIN_OVERLAP = 4
_ROLLING_MIN_CUES = 8


def srt_time_to_ms(text):
    """`00:01:02,345` / `00:01:02.345` → 毫秒；解析不了返回 None。"""
    m = _SRT_TS_RE.search(str(text or ""))
    if not m:
        return None
    h, mi, s, _dot, frac = m.groups()
    return (int(h) * 3600 + int(mi) * 60 + int(s)) * 1000 + int(frac.ljust(3, "0"))


def ms_to_srt_time(ms, sep=",", frac=3):
    """毫秒 → `00:01:02,345`；`frac` 保留原文件的小数位数。"""
    ms = max(0, int(ms))
    h, rem = divmod(ms, 3600000)
    mi, rem = divmod(rem, 60000)
    s, f = divmod(rem, 1000)
    digits = ("%03d" % f)[:frac].ljust(frac, "0")
    return "%02d:%02d:%02d%s%s" % (h, mi, s, sep, digits)


def normalize_rolling_srt(path, dry_run=False, stats=None):
    """把「滚动式」字幕整理成不重叠的常规 SRT（原地改写）；命中则返回 True。

    只改**结束时间**。判定门槛见 `_ROLLING_*`：只有大范围重叠才动手，
    条数太少或只是零散重叠的文件原样不动（那多半是有意的重叠）。

    `dry_run=True` 时只判断、不落盘（返回"本来会改"），供体检工具用；
    `stats` 传 dict 会填进 cues / overlaps / ratio / fixed 便于报告。
    任何异常都吞掉并返回 False —— 整理失败绝不能影响"下载已成功"这个事实。
    """
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError:
        return False
    if not raw:
        return False
    bom = raw.startswith(codecs.BOM_UTF8)
    text = decode_bytes_any(raw)
    if "\r\n" in text:
        nl, text = "\r\n", text.replace("\r\n", "\n")
    elif "\r" in text:
        nl, text = "\r", text.replace("\r", "\n")
    else:
        nl = "\n"

    lines = text.split("\n")
    cues = []      # (行号, 起始 ms, 结束 ms, 结束列起, 结束列止, 分隔符, 小数位)
    for i, line in enumerate(lines):
        m = _SRT_TL_RE.match(line)
        if not m or m.group("pre"):
            # 行首要空格的（缩进）一律不认：真时间轴行都从第 0 列开始，
            # 这样也不会误伤正好长成时间轴的**正文**
            continue
        start_ms = srt_time_to_ms(m.group("t1"))
        end_ms = srt_time_to_ms(m.group("t2"))
        if start_ms is None or end_ms is None:
            continue
        sep = "," if "," in m.group("t2") else "."
        frac = len(m.group("t2").split(sep)[-1])
        cues.append((i, start_ms, end_ms,
                     m.start("t2"), m.end("t2"), sep, frac))

    n = len(cues)
    if stats is not None:
        stats["cues"] = n
    if n < _ROLLING_MIN_CUES:
        if stats is not None:
            stats.update(overlaps=0, ratio=0.0, fixed=0)
        return False
    overlaps = sum(1 for k in range(n - 1) if cues[k][2] > cues[k + 1][1])
    if stats is not None:
        stats.update(overlaps=overlaps, ratio=overlaps / float(n - 1))
    if overlaps < _ROLLING_MIN_OVERLAP:
        if stats is not None:
            stats["fixed"] = 0
        return False
    if overlaps / float(n - 1) < _ROLLING_RATIO:
        if stats is not None:
            stats["fixed"] = 0
        return False

    edits = []     # (行号, 起列, 止列, 新文本)
    for k in range(n - 1):
        line_no, start_ms, end_ms, c0, c1, sep, frac = cues[k]
        next_start = cues[k + 1][1]
        if next_start <= start_ms or end_ms <= next_start:
            continue          # 起始倒挂 / 本来就不重叠：不动
        edits.append((line_no, c0, c1, ms_to_srt_time(next_start, sep, frac)))
    if stats is not None:
        stats["fixed"] = len(edits)
    if not edits:
        return False
    if dry_run:
        return True

    for line_no, c0, c1, new in reversed(edits):
        lines[line_no] = lines[line_no][:c0] + new + lines[line_no][c1:]
    out = nl.join(lines)
    data = out.encode("utf-8")
    if bom:
        data = codecs.BOM_UTF8 + data

    tmp = path + ".vtnew"
    try:
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False
    return True


def write_info_txt(folder, data, quality_label=""):
    """把标题/简介/视频链接/博主链接等写成 视频信息.txt（utf-8-sig，记事本直接可读）"""
    def pick(*keys):
        for k in keys:
            v = data.get(k)
            if v not in (None, ""):
                return str(v).strip()
        return ""

    title = pick("title") or "（未知标题）"
    desc = pick("description") or "（无简介）"
    page_url = pick("webpage_url", "original_url")
    uploader = pick("uploader", "channel", "uploader_id")
    up_url = pick("uploader_url", "channel_url")
    if not up_url:
        uid = pick("uploader_id", "channel_id")
        if uid and "bilibili" in (page_url or ""):
            up_url = f"https://space.bilibili.com/{uid}"

    # 投稿对齐字段：标签取站点自带 tags（B 站常为空，投稿时可再补）；
    # 分区/话题下载时无法确定，给出空行占位，创作声明默认“无需标注”。
    raw_tags = data.get("tags") or data.get("categories") or []
    if isinstance(raw_tags, str):
        tag_line = raw_tags
    else:
        tag_line = ",".join(str(t).strip() for t in raw_tags if str(t).strip())

    lines = [
        "视频信息",
        "=" * 40,
        "",
        f"标题: {title}",
        "",
        "简介:",
        desc,
        "",
        f"视频链接: {page_url or '（无）'}",
        f"博主: {uploader or '（未知）'}",
        f"博主主页: {up_url or '（未知）'}",
        "",
        "—— 以下字段与「B站投稿」表单一一对应，可按需修改 ——",
        f"标签: {tag_line}",
        "分区: ",
        "创作声明: 无需标注",
        "话题: ",
    ]
    if quality_label:
        lines.append(f"下载画质: {quality_label}")
    lines.append(f"下载时间: {datetime.now():%Y-%m-%d %H:%M:%S}")

    path = os.path.join(folder, "视频信息.txt")
    with open(path, "w", encoding="utf-8-sig") as f:
        f.write("\n".join(lines) + "\n")
    return path


def make_cover_1280x720(ffmpeg_path, folder, timeout=60):
    """把 yt-dlp 下载的封面缩略图转为 1280x720 的 封面.jpg（等比缩放+黑边补齐），删除原图"""
    try:
        names = os.listdir(folder)
    except OSError:
        return False
    exts = (".jpg", ".jpeg", ".png", ".webp")
    cands = [os.path.join(folder, n) for n in names
             if n.lower().endswith(exts) and n != "封面.jpg"]
    if not cands:
        return False
    src = max(cands, key=lambda p: os.path.getsize(p))
    out = os.path.join(folder, "封面.jpg")
    vf = ("scale=1280:720:force_original_aspect_ratio=decrease,"
          "pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1")
    try:
        r = run_process([ffmpeg_path, "-y", "-i", src, "-vf", vf,
                         "-frames:v", "1", "-q:v", "2", out],
                        capture_output=True, timeout=timeout)
    except Exception:
        return False
    if r.returncode != 0 or not os.path.isfile(out):
        return False
    for c in cands:
        try:
            os.remove(c)
        except OSError:
            pass
    return True
# ---------- 打包结束 ----------


def probe_qualities(ytdlp, url, log=None):
    """检测可用画质（内部带 412 风控重试）；失败返回 None"""
    raw = fetch_info_json(ytdlp, url, log=log)
    if not raw:
        return None
    try:
        return parse_qualities(raw)
    except (ValueError, KeyError, TypeError):
        return None


def download_mode(url=None):
    if not url:
        url = clean_path(input("视频链接: "))
    if not url or not url.lower().startswith("http"):
        print("[错误] 未检测到有效链接")
        return

    default_dest = get_saved_download_dir()
    print(f"\n保存位置（可拖入文件夹；回车 = 上次位置 {default_dest}）")
    dest = clean_path(input("文件夹: ")) or default_dest
    os.makedirs(dest, exist_ok=True)
    set_saved_download_dir(dest)  # 记住本次位置，长期固定

    print(f"\n[链接] {url}")
    print(f"[目录] {dest}")

    ytdlp = ensure_ytdlp()
    raw = fetch_info_json(ytdlp, url, log=print)
    best = parse_qualities(raw) if raw else None
    if not best:
        print("[错误] 获取视频信息失败或未检测到 >=720p 的可用画质（站点风控/网络异常，请稍后重试）")
        return

    print("\n可用画质（>=720p，每个分辨率只保留最大文件）:")
    for i, f in enumerate(best, 1):
        size = f.get("filesize") or f.get("filesize_approx") or 0
        fps = round(f.get("fps") or 0)
        tag = "  <- 最高，默认" if i == 1 else ""
        print(f"  [{i}] {f['height']}p {fps}fps  (~{format_size(size)}){tag}")

    raw_choice = input(f"选择 [1-{len(best)}, 回车 = 1]: ").strip()
    n = int(raw_choice) if raw_choice.isdigit() else 1
    if n < 1 or n > len(best):
        n = 1
    sel = best[n - 1]
    fid = sel["format_id"]
    print(f"[画质] 已选择 {sel['height']}p（format {fid}），音频自动使用最高质量\n")

    ffmpeg_path, _ = ensure_ffmpeg()

    # 每个视频独立文件夹：视频 + 封面 + 视频信息.txt
    try:
        data = json.loads(raw)
    except ValueError:
        data = {}
    task_folder = unique_folder(dest, sanitize_folder_name(data.get("title"), "video"))
    os.makedirs(task_folder, exist_ok=True)
    print(f"[文件夹] {task_folder}")

    base_cmd = [
        "-f", f"{fid}+ba/b",
        "--merge-output-format", "mp4",
        "--ffmpeg-location", os.path.dirname(ffmpeg_path),
        "--newline", "--no-playlist",
        "--write-thumbnail", "--convert-thumbnails", "jpg",
        "-o", output_template(task_folder),
    ]

    info_path = save_info_json(raw)
    try:
        # 复用检测结果下载：不再二次请求网页，规避 B 站等站点的 412 风控
        rc = subprocess.run([ytdlp, "--load-info-json", info_path, *base_cmd]).returncode
        if rc != 0:
            print("\n[信息] 复用检测结果下载失败，改用链接重新提取（若被风控拦截会自动重试）...")
            rc = 1
            for attempt in range(3):
                rc = subprocess.run([ytdlp, *base_cmd, url]).returncode
                if rc == 0:
                    break
                if attempt == 2:
                    break
                wait = 8 * (attempt + 1)
                print(f"[信息] {wait}s 后重试 ({attempt + 2}/3) ...")
                time.sleep(wait)
    finally:
        try:
            os.remove(info_path)
        except OSError:
            pass

    if rc != 0:
        print("\n[错误] 下载失败，请检查上方输出")
        return
    try:
        write_info_txt(task_folder, data, f"{sel['height']}p")
        print("[打包] 视频信息.txt 已写入")
    except Exception as e:
        print(f"[打包] 视频信息写入失败: {e}")
    if make_cover_1280x720(ffmpeg_path, task_folder):
        print("[打包] 封面.jpg（1280x720）已生成")
    else:
        print("[打包] 该视频无可用封面，已跳过")
    print(f"\n[完成] 已保存到: {task_folder}")
    open_folder(task_folder)
# =============================


# ========== 功能 2：音视频智能合并（整合自 v3.2） ==========
def get_duration(filepath, ffprobe_path):
    cmd = [
        ffprobe_path, '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'csv=p=0',
        filepath
    ]
    try:
        result = run_process(cmd, capture_output=True, check=True)
        return float(decode_bytes_any(result.stdout).strip())
    except Exception:
        return 0.0


def scan_media(folder):
    """扫描 mp4, m4a, weba, srt, ass"""
    mp4s = sorted(glob.glob(os.path.join(folder, '*.mp4')) + glob.glob(os.path.join(folder, '*.MP4')),
                  key=lambda x: os.path.basename(x).lower())
    m4as = sorted(glob.glob(os.path.join(folder, '*.m4a')) + glob.glob(os.path.join(folder, '*.M4A')),
                  key=lambda x: os.path.basename(x).lower())
    webas = sorted(glob.glob(os.path.join(folder, '*.weba')) + glob.glob(os.path.join(folder, '*.WEBA')),
                   key=lambda x: os.path.basename(x).lower())
    srts = sorted(glob.glob(os.path.join(folder, '*.srt')) + glob.glob(os.path.join(folder, '*.SRT')),
                  key=lambda x: os.path.basename(x).lower())
    asss = sorted(glob.glob(os.path.join(folder, '*.ass')) + glob.glob(os.path.join(folder, '*.ASS')),
                  key=lambda x: os.path.basename(x).lower())
    return mp4s, m4as, webas, srts, asss


def get_base_name(filepath):
    return os.path.splitext(os.path.basename(filepath))[0]


def find_subtitle(video_base, srts, asss):
    """按基础文件名查找字幕"""
    for s in srts:
        if get_base_name(s) == video_base:
            return s, 'srt'
    for a in asss:
        if get_base_name(a) == video_base:
            return a, 'ass'
    return None, None


def smart_pair(mp4s, m4as, webas, srts, asss, ffprobe_path):
    """智能配对 mp4 + 音频(m4a优先，其次weba)，并关联字幕"""
    mp4_dur = {f: get_duration(f, ffprobe_path) for f in mp4s}
    m4a_dur = {f: get_duration(f, ffprobe_path) for f in m4as}
    weba_dur = {f: get_duration(f, ffprobe_path) for f in webas}

    mp4_by_name = {get_base_name(f): f for f in mp4s}
    m4a_by_name = {get_base_name(f): f for f in m4as}
    weba_by_name = {get_base_name(f): f for f in webas}

    pairs = []
    used_mp4 = set()
    used_audio = set()

    # 阶段1：同名匹配（优先 m4a，其次 weba）
    for name, mp4_path in mp4_by_name.items():
        audio_path = None
        audio_type = None
        if name in m4a_by_name:
            audio_path = m4a_by_name[name]
            audio_type = 'm4a'
        elif name in weba_by_name:
            audio_path = weba_by_name[name]
            audio_type = 'weba'

        if audio_path:
            dur_map = m4a_dur if audio_type == 'm4a' else weba_dur
            diff = abs(mp4_dur[mp4_path] - dur_map[audio_path])
            match_type = "perfect" if diff <= DURATION_THRESHOLD else "name_only"
            sub_path, sub_type = find_subtitle(name, srts, asss)
            pairs.append((mp4_path, audio_path, audio_type, match_type, diff, sub_path, sub_type))
            used_mp4.add(mp4_path)
            used_audio.add(audio_path)

    # 阶段2：未配对的按时长匹配（优先 m4a，其次 weba）
    remaining_mp4 = [f for f in mp4s if f not in used_mp4]
    remaining_m4a = [f for f in m4as if f not in used_audio]
    remaining_weba = [f for f in webas if f not in used_audio]

    for mp4_path in remaining_mp4:
        best_audio = None
        best_type = None
        best_diff = float('inf')

        for m4a_path in remaining_m4a:
            diff = abs(mp4_dur[mp4_path] - m4a_dur[m4a_path])
            if diff < best_diff:
                best_diff = diff
                best_audio = m4a_path
                best_type = 'm4a'

        for weba_path in remaining_weba:
            diff = abs(mp4_dur[mp4_path] - weba_dur[weba_path])
            if diff < best_diff:
                best_diff = diff
                best_audio = weba_path
                best_type = 'weba'

        if best_audio and best_diff <= DURATION_THRESHOLD:
            name = get_base_name(mp4_path)
            sub_path, sub_type = find_subtitle(name, srts, asss)
            pairs.append((mp4_path, best_audio, best_type, "duration", best_diff, sub_path, sub_type))
            used_mp4.add(mp4_path)
            used_audio.add(best_audio)
            if best_type == 'm4a':
                remaining_m4a.remove(best_audio)
            else:
                remaining_weba.remove(best_audio)

    order = {"perfect": 0, "duration": 1, "name_only": 2}
    pairs.sort(key=lambda x: order.get(x[3], 99))

    return pairs, remaining_mp4, remaining_m4a, remaining_weba


def merge_pair(mp4_path, audio_path, audio_type, sub_path, sub_type, output_path, ffmpeg_path, ass_mode='burn'):
    """
    合并一对音视频+字幕
    audio_type: 'm4a' 或 'weba'
    ass_mode: 'burn'=硬字幕, 'mkv'=封装MKV, 'ignore'=忽略
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    audio_codec = ['-c:a', 'copy'] if audio_type == 'm4a' else ['-c:a', 'aac', '-b:a', '192k']

    # 无字幕
    if not sub_path:
        cmd = [
            ffmpeg_path, '-y',
            '-fflags', '+genpts',
            '-i', mp4_path,
            '-i', audio_path,
            '-c:v', 'copy',
            *audio_codec,
            '-map', '0:v:0',
            '-map', '1:a:0',
            '-movflags', '+faststart',
            '-avoid_negative_ts', 'make_zero',
            '-shortest',
            output_path
        ]
    # SRT 软字幕
    elif sub_type == 'srt':
        cmd = [
            ffmpeg_path, '-y',
            '-fflags', '+genpts',
            '-i', mp4_path,
            '-i', audio_path,
            '-i', sub_path,
            '-c:v', 'copy',
            *audio_codec,
            '-c:s', 'mov_text',
            '-map', '0:v:0',
            '-map', '1:a:0',
            '-map', '2:s:0',
            '-metadata:s:s:0', 'language=chi',
            '-movflags', '+faststart',
            '-avoid_negative_ts', 'make_zero',
            '-shortest',
            output_path
        ]
    # ASS 硬字幕烧录（视频必须重编码）
    elif sub_type == 'ass' and ass_mode == 'burn':
        sub_path_clean = os.path.abspath(sub_path).replace('\\', '/').replace("'", "\\'")
        vf = f"subtitles='{sub_path_clean}'"
        cmd = [
            ffmpeg_path, '-y',
            '-i', mp4_path,
            '-i', audio_path,
            '-vf', vf,
            '-c:v', 'libx264',
            '-crf', '18',
            '-preset', 'fast',
            *audio_codec,
            '-movflags', '+faststart',
            '-shortest',
            output_path
        ]
    # ASS 封装 MKV
    elif sub_type == 'ass' and ass_mode == 'mkv':
        output_path = os.path.splitext(output_path)[0] + '.mkv'
        cmd = [
            ffmpeg_path, '-y',
            '-fflags', '+genpts',
            '-i', mp4_path,
            '-i', audio_path,
            '-i', sub_path,
            '-c:v', 'copy',
            *audio_codec,
            '-map', '0:v:0',
            '-map', '1:a:0',
            '-map', '2:s:0',
            '-metadata:s:s:0', 'language=chi',
            '-shortest',
            output_path
        ]
    else:
        return False, output_path

    result = run_process(cmd, capture_output=True)
    success = result.returncode == 0
    if not success:
        print(f"     [错误] {decode_bytes_any(result.stderr)[-200:]}")
    return success, output_path


def merge_mode(input_dir=None):
    print("\n" + "=" * 60)
    print("  音视频智能合并（mp4 + m4a/weba + srt/ass）")
    print("=" * 60)
    ffmpeg_path, ffprobe_path = ensure_ffmpeg()
    print(f"[OK] ffmpeg 就绪\n")

    if input_dir is None:
        input_dir = DEFAULT_INPUT_DIR if os.path.isdir(DEFAULT_INPUT_DIR) else SCRIPT_DIR

    print(f"默认输入文件夹: {input_dir}")
    new_in = clean_path(input("按回车确认，或输入新路径: "))
    if new_in and os.path.isdir(new_in):
        input_dir = new_in

    default_out = os.path.join(input_dir, "合成结果")
    print(f"\n默认输出文件夹: {default_out}")
    new_out = clean_path(input("按回车确认，或输入新路径: "))
    output_dir = new_out or default_out
    os.makedirs(output_dir, exist_ok=True)

    print(f"\n[信息] 正在扫描: {input_dir}")
    mp4s, m4as, webas, srts, asss = scan_media(input_dir)

    if not mp4s:
        print("[错误] 未找到 mp4 视频文件")
        return
    if not m4as and not webas:
        print("[错误] 未找到 m4a 或 weba 音频文件")
        return

    print(f"[OK] 找到 {len(mp4s)} 个 mp4, {len(m4as)} 个 m4a, {len(webas)} 个 weba, {len(srts)} 个 srt, {len(asss)} 个 ass")

    print("\n[信息] 正在分析配对...")
    pairs, rem_mp4, rem_m4a, rem_weba = smart_pair(mp4s, m4as, webas, srts, asss, ffprobe_path)

    has_ass = any(p[6] == 'ass' for p in pairs)

    ass_mode = 'burn'
    if has_ass:
        print("\n" + "-" * 60)
        print("检测到 ASS 字幕文件，请选择处理方式：")
        print("  1. 烧录为硬字幕（保留特效样式，视频会重新编码，较慢）")
        print("  2. 封装为 MKV（不重新编码，播放器需支持 ASS 显示）")
        print("  3. 忽略 ASS 字幕")
        choice = input("请选择 [1/2/3，默认1]: ").strip() or "1"
        if choice == '2':
            ass_mode = 'mkv'
        elif choice == '3':
            ass_mode = 'ignore'

    print("\n" + "=" * 60)
    print("  配对结果")
    print("=" * 60)

    perfect = [p for p in pairs if p[3] == "perfect"]
    duration_match = [p for p in pairs if p[3] == "duration"]
    name_only = [p for p in pairs if p[3] == "name_only"]

    def show_pair(p):
        mp4, audio, audio_type, mt, diff, sub, st = p
        vd = get_duration(mp4, ffprobe_path)
        ad = get_duration(audio, ffprobe_path)
        audio_label = "[m4a→copy]" if audio_type == 'm4a' else "[weba→AAC转码]"
        sub_info = ""
        if st == 'srt':
            sub_info = f" | 字幕: {os.path.basename(sub)} [SRT软字幕]"
        elif st == 'ass':
            if ass_mode == 'burn':
                sub_info = f" | 字幕: {os.path.basename(sub)} [ASS硬字幕]"
            elif ass_mode == 'mkv':
                sub_info = f" | 字幕: {os.path.basename(sub)} [ASS→MKV]"
            else:
                sub_info = " | 字幕: 已忽略"
        print(f"  视频: {os.path.basename(mp4)} ({format_time(vd)})")
        print(f"  音频: {os.path.basename(audio)} ({format_time(ad)}) {audio_label}")
        print(f"  时长差: {diff:.3f}s{sub_info}")
        print()

    if perfect:
        print(f"\n[完美匹配] 同名 + 时长一致 ({len(perfect)} 对):")
        for p in perfect:
            show_pair(p)
    if duration_match:
        print(f"\n[时长匹配] 不同名但时长一致 ({len(duration_match)} 对):")
        for p in duration_match:
            show_pair(p)
    if name_only:
        print(f"\n[同名不匹配] 文件名相同但时长差异大 ({len(name_only)} 对):")
        for p in name_only:
            show_pair(p)

    if rem_mp4:
        print(f"\n[未匹配视频] ({len(rem_mp4)} 个):")
        for f in rem_mp4:
            print(f"  {os.path.basename(f)} ({format_time(get_duration(f, ffprobe_path))})")
    if rem_m4a:
        print(f"\n[未匹配音频-m4a] ({len(rem_m4a)} 个):")
        for f in rem_m4a:
            print(f"  {os.path.basename(f)}")
    if rem_weba:
        print(f"\n[未匹配音频-weba] ({len(rem_weba)} 个):")
        for f in rem_weba:
            print(f"  {os.path.basename(f)}")

    to_merge = perfect + duration_match
    if name_only:
        print("\n" + "-" * 60)
        print("发现同名但时长不匹配的配对，是否强制合成？")
        choice = input("强制合成这些配对? [y/N]: ").strip().lower()
        if choice == 'y':
            to_merge.extend(name_only)

    if not to_merge:
        print("\n[提示] 没有可合成的配对")
        return

    if ass_mode == 'ignore':
        for i, p in enumerate(to_merge):
            mp4, audio, at, mt, diff, sub, st = p
            if st == 'ass':
                to_merge[i] = (mp4, audio, at, mt, diff, None, None)

    print(f"\n[信息] 准备合成 {len(to_merge)} 个视频...")
    print("-" * 60)

    success_count = 0
    fail_count = 0

    for idx, (mp4_path, audio_path, audio_type, match_type, diff, sub_path, sub_type) in enumerate(to_merge, 1):
        base = get_base_name(mp4_path)
        output_name = f"{base}_merged.mp4"
        output_path = os.path.join(output_dir, output_name)

        counter = 1
        orig = output_path
        while os.path.exists(output_path):
            name, ext = os.path.splitext(orig)
            output_path = f"{name}_{counter}{ext}"
            counter += 1

        tag = "[完美]" if match_type == "perfect" else "[时长]" if match_type == "duration" else "[强制]"
        audio_tag = "[m4a]" if audio_type == 'm4a' else "[weba→AAC]"
        sub_tag = ""
        if sub_type == 'srt':
            sub_tag = " [SRT]"
        elif sub_type == 'ass':
            sub_tag = " [ASS硬]" if ass_mode == 'burn' else " [ASS→MKV]" if ass_mode == 'mkv' else ""

        print(f"\n{tag}{audio_tag}{sub_tag} [{idx}/{len(to_merge)}] {base}")
        print(f"     视频: {os.path.basename(mp4_path)}")
        print(f"     音频: {os.path.basename(audio_path)}")
        if sub_path:
            print(f"     字幕: {os.path.basename(sub_path)}")

        ok, final_output = merge_pair(mp4_path, audio_path, audio_type, sub_path, sub_type,
                                      output_path, ffmpeg_path, ass_mode)
        if ok and os.path.exists(final_output):
            out_size = os.path.getsize(final_output)
            print(f"     [OK] 成功 ({format_size(out_size)})")
            success_count += 1
        else:
            print(f"     [X] 失败")
            fail_count += 1

    print("\n" + "=" * 60)
    print("  合成完成")
    print("=" * 60)
    print(f"  成功: {success_count}")
    print(f"  失败: {fail_count}")
    print(f"  输出目录: {output_dir}")
    print("=" * 60)
# =============================


# ========== 主入口 ==========
def main():
    print("=" * 60)
    print("  视频工具箱 v1.6.0")
    print("  [1] 视频下载（链接 -> 选画质 -> mp4，每视频独立文件夹）")
    print("  [2] 音视频智能合并（mp4 + m4a/weba + srt/ass）")
    print("=" * 60)

    arg = clean_path(sys.argv[1]) if len(sys.argv) >= 2 else ""

    try:
        if arg:
            if os.path.isdir(arg):
                # 拖入文件夹 -> 合并模式
                merge_mode(arg)
            else:
                # 拖入链接/文件 -> 下载模式
                url = extract_url(arg)
                if url:
                    download_mode(url)
                else:
                    print("[错误] 无法识别拖入的内容（不是链接也不是文件夹）")
        else:
            choice = input("选择功能 [1/2，回车 = 1]: ").strip() or "1"
            if choice == "2":
                merge_mode()
            else:
                download_mode()
    except KeyboardInterrupt:
        print("\n[取消] 用户中断")

    input("\n按回车键退出...")


if __name__ == "__main__":
    main()
