#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
视频工具箱 v1.10.5（单文件整合版）
==================================================
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
from datetime import datetime
from pathlib import Path

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
# 用途：程序从 GitHub/HuggingFace 等开源库下载依赖时自动启用，其余流量直连。
# 端口固定 7897，与本机其他代理（FlClash 等占用 7890）互不冲突。
MIHOMO_DIR = os.path.join(TOOLS_DIR, "mihomo")
MIHOMO_EXE = os.path.join(MIHOMO_DIR, "mihomo.exe")
MIHOMO_CONFIG = os.path.join(MIHOMO_DIR, "config.yaml")
MIHOMO_PROXY = "http://127.0.0.1:7897"
MIHOMO_PORT = 7897

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


def system_python():
    """运行字幕处理 / 投稿 worker 的 Python：优先用工具箱内 tools\\python\\python.exe；
    否则源码模式用当前解释器，打包后用系统 PATH 中的 python。"""
    embedded = os.path.join(EMBEDDED_PYTHON_DIR, "python.exe")
    if os.path.isfile(embedded):
        return embedded
    if not getattr(sys, "frozen", False):
        return sys.executable
    return shutil.which("python") or ""


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


def vc_redirect_paths():
    """在导入 videocaptioner 之前，把它的数据/工作/日志目录重定向到数据根目录。

    上游 config.py 在导入时即固化 ROOT_PATH / WORK_PATH 等常量：
      · ROOT_PATH  = platformdirs.user_data_dir("VideoCaptioner")  → AppData\\Local
      · WORK_PATH  = Path.home() / "VideoCaptioner"                → 用户目录
      · LOG_PATH   = ROOT_PATH / "logs"
      · CACHE/MODEL_PATH = ROOT_PATH 下
    这些都在 C 盘。做法是在其模块首次导入时打补丁（不修改第三方源码文件，
    保证许可合规与可升级），把它们全部指到 <DATA_ROOT>\\data\\VideoCaptioner。
    """
    import sys as _sys
    if "videocaptioner.config" in _sys.modules:
        return  # 已导入过，路径常量已固化；补丁只在首次导入时有效
    target = Path(vc_data_dir())
    try:
        target.mkdir(parents=True, exist_ok=True)
        for sub in ("logs", "cache", "models", "resource"):
            (target / sub).mkdir(parents=True, exist_ok=True)
    except OSError:
        return

    from videocaptioner import config as _vc_cfg
    _vc_cfg.ROOT_PATH = target
    _vc_cfg.APPDATA_PATH = target
    _vc_cfg.RESOURCE_PATH = target / "resource"
    _vc_cfg.WORK_PATH = target / "work-dir"
    _vc_cfg.LOG_PATH = target / "logs"
    _vc_cfg.LLM_LOG_FILE = _vc_cfg.LOG_PATH / "llm_requests.jsonl"
    _vc_cfg.SETTINGS_PATH = target / "settings.json"
    _vc_cfg.CACHE_PATH = target / "cache"
    _vc_cfg.MODEL_PATH = target / "models"
    for _p in (_vc_cfg.WORK_PATH, _vc_cfg.LOG_PATH, _vc_cfg.CACHE_PATH,
               _vc_cfg.MODEL_PATH, _vc_cfg.RESOURCE_PATH):
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

    1. 迁移字幕引擎在 C 盘的历史数据到数据根目录；
    2. 重定向字幕引擎的路径常量为数据根目录；
    3. 兜底确保临时目录指向数据根目录（不落系统 Temp）。
    在导入 videocaptioner *之前* 调用；GUI 启动与自检都会走这里。
    """
    try:
        vc_migrate_legacy_data()
    except Exception:
        pass
    try:
        vc_redirect_paths()
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


def ensure_builtin_proxy():
    """确保内置 mihomo 代理可用，返回代理地址或 None。

    幂等设计：7897 已被监听（本程序或残留进程已启动 mihomo）时直接复用；
    否则启动 tools/mihomo/mihomo.exe（隐藏窗口）并等待端口就绪。
    依赖下载失败时才调用，直连成功不会触发。
    """
    global _MIHOMO_PROC
    if _port_listening(MIHOMO_PORT):
        return MIHOMO_PROXY
    if not (os.path.isfile(MIHOMO_EXE) and os.path.isfile(MIHOMO_CONFIG)):
        return None
    try:
        os.makedirs(MIHOMO_DIR, exist_ok=True)
        _MIHOMO_PROC = subprocess.Popen(
            [MIHOMO_EXE, "-d", MIHOMO_DIR, "-f", MIHOMO_CONFIG],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:
        return None
    # 等待端口就绪（AUTO 组节点首次测速约需数秒）
    for _ in range(40):
        if _port_listening(MIHOMO_PORT):
            return MIHOMO_PROXY
        if _MIHOMO_PROC.poll() is not None:
            return None
        time.sleep(0.5)
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


# ========== 校准脚本 GitHub 同步（v1.10.5，退出时静默执行） ==========
# 需求：每次退出程序，把 subtitle_calib_merged.py 同步到 GitHub 仓库 main 分支。
# 通道：GitHub Git Data API（api.github.com 可达，git 协议在本机网络不可达）；
#       直连失败时回退内置 mihomo 代理（127.0.0.1:7897）。
# 该代理只为 api.github.com 服务，不代理其它流量。
# 策略：静默后台、不阻塞退出、不弹窗，结果只写 logs/calib_sync.log；
#       内容是否变化都提交（用户明确要求每次都提交）。
SYNC_OWNER = "09Th90"
SYNC_REPO = "VideoToolbox"
SYNC_BRANCH = "main"
SYNC_API = "https://api.github.com"
#: 仓库内目标路径（与本地 APP_DIR 下的相对路径一致）
SYNC_REL_PATH = "subtitle_calib_merged.py"
#: 学习库（learn 候选）v1.10.7 起纳入同步：这是各用户日常差异的最大来源
SYNC_KB_REL_PATH = "subtitle_learned_kb.json"
#: 基线快照：上次同步成功后的本地内容，即三方合并的「公共祖先」。
#: 放数据根目录（不入库不分发）；缺失时退化为保守的并集合并策略
CALIB_BASE_SNAPSHOT = os.path.join(DATA_DIR, "calib_sync_base.py")
CALIB_KB_BASE_SNAPSHOT = os.path.join(DATA_DIR, "calib_sync_kb_base.json")
SYNC_LOG = os.path.join(LOGS_DIR, "calib_sync.log")


def _sync_log(msg):
    """追加一行同步日志（best-effort，绝不因日志失败影响主流程）。"""
    try:
        os.makedirs(LOGS_DIR, exist_ok=True)
        with open(SYNC_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")
    except OSError:
        pass


def _gh_token():
    """取 GitHub token：环境变量优先，其次 gh keyring。取不到返回空串。"""
    tok = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if tok:
        return tok.strip()
    for exe in ("gh", os.path.join(TOOLS_DIR, "gh.exe")):
        try:
            p = subprocess.run([exe, "auth", "token"], capture_output=True,
                               text=True, timeout=15)
            if p.returncode == 0 and p.stdout.strip():
                return p.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            continue
    return ""


def _gh_request(method, path, token, payload=None, proxy="", timeout=30):
    """访问 GitHub API。返回 (ok, 数据或错误消息)。用 curl，避开 requests 的代理问题。"""
    url = f"{SYNC_API}/{path}"
    cmd = ["curl", "-sS", "--max-time", str(timeout), "-X", method]
    if proxy:
        cmd += ["-x", proxy]
    if token:  # 匿名读公开库时不带认证头（启动拉取可无 token）
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
        p = subprocess.run(cmd, input=stdin, capture_output=True, timeout=timeout + 10,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"curl 调用失败: {e}"
    if p.returncode != 0:
        return False, f"curl 退出码 {p.returncode}: {p.stderr.decode(errors='replace')[:150]}"
    body, _, code = p.stdout.decode(errors="replace").rpartition("\n")
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
    """先直连，失败再走内置代理（仅 GitHub 流量）。返回 (ok, 数据或错误)。

    仅当失败【疑似网络问题】时才启用代理：认证错误（401/403）与参数错误
    （404/422）走代理也不会变好，直接返回，避免白白拉起 mihomo。
    """
    ok, data = _gh_request(method, path, token, payload)
    if ok:
        return True, data
    msg = str(data)
    # 认证/权限/资源类错误：非网络问题，回退无意义
    if any(code in msg for code in ("HTTP 401", "HTTP 403", "HTTP 404", "HTTP 422")):
        return False, data
    _sync_log(f"直连 {method} {path} 失败（{msg[:80]}），改用内置代理")
    proxy = ensure_builtin_proxy()
    if not proxy:
        return False, f"{data}；内置代理不可用"
    ok2, data2 = _gh_request(method, path, token, payload, proxy=proxy)
    return (ok2, data2)


def sync_calib_to_github():
    """把本地校准脚本与学习库推到 GitHub main 分支（静默，返回 (ok, 说明)）。

    v1.10.7 起推送前先拉远程做条目级三方合并（pull-merge-then-push）：
    把其他用户沉淀的新条目并入后再推，多用户不再互相覆盖。
    内容未变也提交（用户要求）。任何异常都被吞掉并记日志，绝不影响退出流程。
    """
    local = os.path.join(APP_DIR, SYNC_REL_PATH)
    if not os.path.isfile(local):
        _sync_log(f"跳过：本地脚本不存在 {local}")
        return False, "本地校准脚本不存在"

    token = _gh_token()
    if not token:
        _sync_log("跳过：未取得 GitHub token（需 gh auth login 或设 GH_TOKEN）")
        return False, "未取得 GitHub token"

    # 推送前先合并远程新沉淀（结果回写本地与基线），失败则按本地直推
    _pull_and_merge(token, SYNC_REL_PATH, True)
    _pull_and_merge(token, SYNC_KB_REL_PATH, False)

    entries = []  # (rel_path, bytes, text)
    for rel in (SYNC_REL_PATH, SYNC_KB_REL_PATH):
        try:
            with open(os.path.join(APP_DIR, rel), "rb") as f:
                b = f.read()
            entries.append((rel, b, b.decode("utf-8")))
        except (OSError, UnicodeDecodeError) as e:
            if rel == SYNC_REL_PATH:
                _sync_log(f"跳过：读取失败 {e}")
                return False, f"读取失败: {e}"
            # 学习库尚不存在（从未 learn 过）则本轮不推
            _sync_log(f"推送[{rel}]跳过：{e}")

    base = f"repos/{SYNC_OWNER}/{SYNC_REPO}"
    # 1. 取分支当前 head（同时拿到 base_tree）
    ok, head = _gh_request_any("GET", f"{base}/git/ref/heads/{SYNC_BRANCH}", token)
    if not ok:
        _sync_log(f"失败：读取分支 head {head}")
        return False, f"读取分支失败: {head}"
    head_sha = head["object"]["sha"]

    ok, commit = _gh_request_any("GET", f"{base}/git/commits/{head_sha}", token)
    if not ok:
        _sync_log(f"失败：读取 commit {commit}")
        return False, f"读取 commit 失败: {commit}"
    base_tree = commit["tree"]["sha"]

    # 2. 上传 blob（脚本 + 学习库）
    tree_entries = []
    for rel, b, _text in entries:
        ok, blob = _gh_request_any("POST", f"{base}/git/blobs", token, {
            "content": base64.b64encode(b).decode("ascii"),
            "encoding": "base64",
        })
        if not ok:
            _sync_log(f"失败：创建 blob[{rel}] {blob}")
            return False, f"创建 blob 失败: {blob}"
        tree_entries.append({"path": rel, "mode": "100644",
                             "type": "blob", "sha": blob["sha"]})

    # 3. 建 tree（只动这几个文件，其余保留）
    tree_payload = {
        "base_tree": base_tree,
        "tree": tree_entries,
    }
    ok, tree = _gh_request_any("POST", f"{base}/git/trees", token, tree_payload)
    if not ok:
        _sync_log(f"失败：创建 tree {tree}")
        return False, f"创建 tree 失败: {tree}"

    # 4. 提交
    commit_payload = {
        "message": (f"chore(calib): 同步字幕校准脚本 "
                    f"（{datetime.now():%Y-%m-%d %H:%M:%S}，来自视频工具箱）"),
        "tree": tree["sha"],
        "parents": [head_sha],
    }
    ok, new_commit = _gh_request_any("POST", f"{base}/git/commits", token, commit_payload)
    if not ok:
        _sync_log(f"失败：创建 commit {new_commit}")
        return False, f"创建 commit 失败: {new_commit}"

    # 5. 推进分支
    ok, res = _gh_request_any("PATCH", f"{base}/git/refs/heads/{SYNC_BRANCH}",
                              token, {"sha": new_commit["sha"], "force": False})
    if not ok:
        _sync_log(f"失败：更新分支 {res}")
        return False, f"更新分支失败: {res}"

    _sync_log(f"成功：已同步 {len(entries)} 个文件（{', '.join(r for r, _b, _t in entries)}）"
              f" -> {SYNC_OWNER}/{SYNC_REPO}@{SYNC_BRANCH} commit {new_commit['sha'][:12]}")
    # 推送成功：基线快照对齐本次推送内容（下次三方合并的公共祖先）
    for rel, _b, text in entries:
        try:
            _atomic_write(CALIB_BASE_SNAPSHOT if rel == SYNC_REL_PATH
                          else CALIB_KB_BASE_SNAPSHOT, text)
        except OSError as e:
            _sync_log(f"基线快照写入失败[{rel}]（忽略）: {e}")
    return True, f"已同步 commit {new_commit['sha'][:12]}"


def sync_calib_on_exit():
    """退出时后台触发同步：起独立子进程，不阻塞退出、不弹窗。

    用子进程而非线程：主进程退出后线程会被强杀，子进程能自行跑完。
    """
    try:
        if not os.environ.get("VT_NO_CALIB_SYNC"):
            script = os.path.join(APP_DIR, SYNC_REL_PATH)
            if not os.path.isfile(script):
                return
            # 以自身引擎模块为入口，子进程里跑同步逻辑
            args = [sys.executable, "-c",
                    "import sys; sys.path.insert(0, r'%s');"
                    " import video_toolbox as e; e.sync_calib_to_github()"
                    % os.path.join(APP_DIR, "src")]
            subprocess.Popen(
                args, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                close_fds=True,
            )
            _sync_log("已派生退出同步子进程")
    except Exception as e:  # noqa: BLE001
        _sync_log(f"派生同步子进程失败（忽略）: {e}")


# ---------- 条目级三方合并（v1.10.7 多用户知识收敛） ----------
# 需求：不同用户使用中会沉淀不一样的校准内容，启动时自动拿到全体最新版。
# 做法是「启动拉取 + 条目级合并 + 退出推送」，合并单位从整个文件降到条目：
#   · 纯字符串字面量 dict（各模式术语表等）：按 错形键 合并；
#   · 常量二元组列表（CONTEXT_MAP 等上下文佐证规则）：按整元组合并；
#   · ENTITIES（Entity(...) 调用列表）：按 canonical 合并；
#   · 学习库 JSON：按 "模式|错形" 候选合并。
# 只做并集、从不删除，任意多用户反复拉推最终收敛到全体条目的并集。
# 用 ast 而非文本 diff：脚本是合法 Python，AST 能精确定位表与条目且免误伤。
import ast as _ast_m
_ast_Dict, _ast_List, _ast_Const, _ast_Constant = (
    _ast_m.Dict, _ast_m.List, _ast_m.Constant, _ast_m.Constant)
_MERGE_MISSING = object()


def _read_sync_text(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            return f.read()
    except OSError:
        return ""


def _atomic_write(path, text):
    """同目录临时文件 + os.replace 原子落盘；newline='' 不改写换行符。"""
    tmp = path + ".sync_tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    os.replace(tmp, path)


def _ast_module_tables(src):
    """解析模块级「名称 = Dict/List 字面量」赋值，返回 {名称: value 节点}。
    解析失败返回 None。"""
    import ast as _ast
    try:
        tree = _ast.parse(src)
    except SyntaxError:
        return None
    out = {}
    for node in tree.body:
        if (isinstance(node, _ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], _ast.Name)
                and isinstance(node.value, (_ast.Dict, _ast.List))):
            out[node.targets[0].id] = node.value
    return out


def _dict_entries(dnode):
    """Dict 节点中「字符串键 -> 字符串值」的条目 {key: (键节点, 值节点)}。
    含任何非常量成员的表返回的映射会缺项——调用方以此跳过非纯字面量表。"""
    out = {}
    if not isinstance(dnode, _ast_Dict):
        return out
    for k, v in zip(dnode.keys, dnode.values):
        if (isinstance(k, _ast_Const) and isinstance(v, _ast_Const)
                and isinstance(k.value, str) and isinstance(v.value, str)):
            out[k.value] = (k, v)
    return out


def _entity_fields(call):
    """从 Entity(...) 调用节点提取 (canonical, modes, variants)。"""
    import ast as _ast
    canonical = None
    if call.args and isinstance(call.args[0], _ast.Constant):
        canonical = call.args[0].value
    modes, variants = (), ()
    for kw in call.keywords:
        if kw.arg == "canonical" and isinstance(kw.value, _ast.Constant):
            canonical = kw.value.value
        elif kw.arg in ("modes", "variants") and isinstance(kw.value, (_ast.Tuple, _ast.List)):
            try:
                vals = tuple(_ast.literal_eval(kw.value))
            except ValueError:
                continue
            if kw.arg == "modes":
                modes = vals
            else:
                variants = vals
    return canonical, modes, variants


def _registry_conflicts(src):
    """静态复算脚本 _register_entities 的注册冲突检查（同变体不同目标）。

    合并器绝不制造这种冲突——它会 raise SystemExit 让整个校准脚本起不来。
    返回冲突描述列表（空列表 = 通过）。"""
    import ast as _ast
    try:
        tree = _ast.parse(src)
    except SyntaxError:
        return ["语法解析失败"]
    tables, entities = {}, []
    for node in tree.body:
        if (isinstance(node, _ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], _ast.Name)):
            name = node.targets[0].id
            if isinstance(node.value, _ast.Dict):
                try:
                    tables[name] = _ast.literal_eval(node.value)
                except ValueError:
                    pass
            if name == "ENTITIES" and isinstance(node.value, _ast.List):
                for elt in node.value.elts:
                    if isinstance(elt, _ast.Call):
                        c, modes, variants = _entity_fields(elt)
                        if c is not None:
                            entities.append((c, modes, variants))
    mode_table = tables.get("_MODE_TERM_TABLE") or {}
    bad = []
    for canonical, modes, variants in entities:
        for m in modes:
            tname = mode_table.get(m)
            tbl = tables.get(tname) if tname else None
            if not isinstance(tbl, dict):
                continue
            for v in variants:
                if v in tbl and tbl[v] != canonical:
                    bad.append(f"{v!r}->{tbl[v]!r} 与实体 {canonical!r} 冲突")
    return bad


def merge_calib_script(local_src, remote_src, base_src=""):
    """校准脚本条目级三方合并。返回 (merged, added, conflicts)。

    三方 = 本地 / 远程 / 基线快照（上次同步后的内容，即公共祖先）：
      · 远程新增条目 -> 并入本地（保留远程原文行，含行尾注释）；
      · 基线有而本地已删 -> 本地有意删除，不复活；
      · 本地未动、远程修改 -> 采用远程；
      · 两边都改且不同 -> 冲突，保留本地并记录（退出推送交由人工裁决）；
      · 本地新增/修改 -> 保留本地（推送时带给别人）。
    合并结果必须同时通过 语法编译 与 实体注册冲突 两道门，任一不过整体
    放弃、返回本地原文——宁可少并一次，绝不产出起不来的脚本。
    """
    import ast as _ast
    crlf = "\r\n" in local_src
    norm = lambda s: (s or "").replace("\r\n", "\n")
    local_src, remote_src, base_src = norm(local_src), norm(remote_src), norm(base_src)
    keep_local = (local_src, 0, ["nothing"])
    if not remote_src.strip() or not local_src.strip():
        return (local_src.replace("\n", "\r\n") if crlf else local_src), 0, []
    L, R = _ast_module_tables(local_src), _ast_module_tables(remote_src)
    B = _ast_module_tables(base_src) or {}
    if L is None or R is None:
        return (local_src.replace("\n", "\r\n") if crlf else local_src), 0, \
            ["远程或本地脚本解析失败，放弃合并"]

    lines = local_src.split("\n")
    rlines = remote_src.split("\n")
    edits = []          # (start0, end0_exclusive, 替换行列表)；start==end 表示插入
    added, conflicts = 0, []

    for name, rnode in R.items():
        lnode = L.get(name)
        if lnode is None or type(lnode) is not type(rnode):
            continue

        if isinstance(rnode, _ast.Dict):
            # 只合并纯「字符串->字符串」表；结构复杂的表（INFO/映射表）不动
            le, re_ = _dict_entries(lnode), _dict_entries(rnode)
            be = _dict_entries(B.get(name)) if name in B else {}
            if len(le) != len(lnode.keys) or len(re_) != len(rnode.keys):
                continue
            pos = lnode.end_lineno - 1          # 收尾 } 独占一行才可插入
            if lines[pos].strip() != "}":
                continue
            new_rows = []
            for key, (rk, rv) in re_.items():
                rval = rv.value
                if key not in le:
                    if key in be:
                        continue                 # 本地删除，尊重本地
                    row = rlines[rk.lineno - 1:rv.end_lineno]
                    new_rows.extend(row)
                    added += 1
                    continue
                lk, lv = le[key]
                if lv.value == rval:
                    continue                     # 两边一致
                bval = be[key][1].value if key in be else _MERGE_MISSING
                if bval is _MERGE_MISSING:
                    continue                     # 本地新增，保留
                if lv.value == bval:
                    # 本地未动、远程修改 -> 采用远程整行
                    edits.append((lk.lineno - 1, lv.end_lineno,
                                  rlines[rk.lineno - 1:rv.end_lineno]))
                else:
                    conflicts.append(f"{name}[{key!r}] 两边不同：保留本地 {lv.value!r}")
            if new_rows:
                edits.append((pos, pos, new_rows))

        elif isinstance(rnode, _ast.List):
            pos = lnode.end_lineno - 1
            if lines[pos].strip() != "]":
                continue
            if name == "ENTITIES":
                # Entity 调用列表：按 canonical 合并
                def _canon_map(node, src):
                    out = {}
                    for e in node.elts:
                        if isinstance(e, _ast.Call):
                            c, _m, _v = _entity_fields(e)
                            if c is not None:
                                out[c] = (e, _ast.get_source_segment(src, e) or "")
                    return out
                lmap_e = _canon_map(lnode, local_src)
                rmap_e = _canon_map(rnode, remote_src)
                bmap_e = _canon_map(B[name], base_src) if isinstance(B.get(name), _ast.List) else {}
                new_rows = []
                for canon, (enode, rseg) in rmap_e.items():
                    if canon not in lmap_e:
                        if canon in bmap_e:
                            continue             # 本地删除，尊重本地
                        new_rows.extend(rlines[enode.lineno - 1:enode.end_lineno])
                        added += 1
                        continue
                    lnode_e, lseg = lmap_e[canon]
                    bnode_e = bmap_e.get(canon)
                    if (bnode_e is not None and lseg == bmap_e[canon][1]
                            and rseg != bmap_e[canon][1]):
                        # 本地未动、远程更新 -> 整段替换
                        edits.append((lnode_e.lineno - 1, lnode_e.end_lineno,
                                      rlines[enode.lineno - 1:enode.end_lineno]))
                if new_rows:
                    edits.append((pos, pos, new_rows))
            else:
                # 常量列表（CONTEXT_MAP 等元组规则）：按整元素并集
                def _elts(node):
                    out = []
                    for e in node.elts:
                        try:
                            out.append((_ast.literal_eval(e), e))
                        except ValueError:
                            return None
                    return out
                lels, rels = _elts(lnode), _elts(rnode)
                bels = _elts(B[name]) if isinstance(B.get(name), _ast.List) else []
                if lels is None or rels is None or bels is None:
                    continue
                lvals = {v for v, _ in lels}
                bvals = {v for v, _ in bels}
                new_rows = []
                for val, enode in rels:
                    if val in lvals or val in bvals:
                        continue
                    new_rows.extend(rlines[enode.lineno - 1:enode.end_lineno])
                    lvals.add(val)
                    added += 1
                if new_rows:
                    edits.append((pos, pos, new_rows))

    if not edits:
        merged = local_src
    else:
        for s0, e0, repl in sorted(edits, key=lambda t: (t[0], t[1]), reverse=True):
            lines[s0:e0] = repl
        merged = "\n".join(lines)
        try:
            compile(merged, "merged_calib", "exec")
        except SyntaxError as e:
            return (local_src.replace("\n", "\r\n") if crlf else local_src), 0, \
                [f"合并结果语法不过（{e.msg}，行 {e.lineno}），已放弃并入"]
        reg = _registry_conflicts(merged)
        if reg:
            return (local_src.replace("\n", "\r\n") if crlf else local_src), 0, \
                ["合并会触发实体注册冲突：" + "；".join(reg[:3]) + "，已放弃并入"]
    if conflicts:
        _sync_log(f"脚本合并冲突 {len(conflicts)} 条（保留本地）：{conflicts[0]}")
    merged = merged.replace("\n", "\r\n") if crlf else merged
    return merged, added, conflicts


def merge_learned_kb(local_text, remote_text):
    """学习库（subtitle_learned_kb.json）候选级合并。返回 (合并文本, 新增数, 冲突数)。

    键为 "模式|错形"，语义与脚本 learn 状态机对齐：
      · 单边独有 -> 直接并入；
      · 同键：count/uncorrected 取较大值，cues/samples 取并集（沿用脚本 20/10
        封顶），ref_tokens/unc_ref_tokens 计数求和，first/last 取更早/更晚；
      · 同键不同目标 -> 置 conflict（脚本会停止自动应用，留人工裁决），alts 并入；
      · status 就高：rejected（人工否决）不被对方的 candidate/confirmed 抵消。
    任一侧解析失败返回本地原文，绝不产出坏库。
    """
    import json as _json
    empty = _json.dumps({"version": 1, "candidates": {}}, ensure_ascii=False)
    try:
        L = _json.loads(local_text) if local_text.strip() else {"candidates": {}}
        R = _json.loads(remote_text) if remote_text.strip() else {"candidates": {}}
        lc, rc = dict(L["candidates"]), R["candidates"]
    except (ValueError, KeyError, TypeError):
        return (local_text if local_text.strip() else empty), 0, 0
    added = conflicts = 0
    for k, r in rc.items():
        l = lc.get(k)
        if l is None:
            lc[k] = r
            added += 1
            continue
        if l == r:
            continue
        m = dict(l)
        rejected = (l.get("status") == "rejected" or r.get("status") == "rejected")
        if rejected:
            m["status"] = "rejected"
        elif r.get("right") != l.get("right"):
            m["conflict"] = True
            alts = dict(m.get("alts") or {})
            alts[r.get("right", "")] = alts.get(r.get("right", ""), 0) + max(r.get("count", 1), 1)
            m["alts"] = alts
            conflicts += 1
        m["count"] = max(l.get("count", 0), r.get("count", 0))
        m["uncorrected"] = max(l.get("uncorrected", 0), r.get("uncorrected", 0))
        m["cues"] = list(dict.fromkeys(
            list(l.get("cues") or []) + list(r.get("cues") or [])))[:20]
        ls = l.get("samples") or []
        m["samples"] = (ls + [s for s in (r.get("samples") or []) if s not in ls])[:10]
        for f in ("ref_tokens", "unc_ref_tokens"):
            d = dict(l.get(f) or {})
            for t, n in (r.get(f) or {}).items():
                d[t] = d.get(t, 0) + n
            m[f] = d
        firsts = [x for x in (l.get("first"), r.get("first")) if x]
        lasts = [x for x in (l.get("last"), r.get("last")) if x]
        if firsts:
            m["first"] = min(firsts)
        if lasts:
            m["last"] = max(lasts)
        if l.get("demoted") or r.get("demoted"):
            m["demoted"] = True
        lc[k] = m
    return _json.dumps({"version": 1, "candidates": lc},
                       ensure_ascii=False, indent=1), added, conflicts


def _gh_fetch_file(token, rel_path):
    """拉取仓库单文件最新内容。返回 (ok, 文本或错误消息, blob_sha)。

    公开库可匿名读（token 为空不带认证头）；>1MB 文件 contents API 不内联，
    回退 git blobs 接口取全量 base64。"""
    path = (f"repos/{SYNC_OWNER}/{SYNC_REPO}/contents/{rel_path}"
            f"?ref={SYNC_BRANCH}")
    ok, data = _gh_request_any("GET", path, token)
    if not ok:
        return False, str(data), ""
    try:
        content = data.get("content")
        if not content and data.get("git_url"):
            blob_path = str(data["git_url"]).replace(SYNC_API + "/", "")
            ok2, blob = _gh_request_any("GET", blob_path, token)
            if not ok2:
                return False, str(blob), ""
            data, content = blob, blob.get("content")
        text = base64.b64decode(content or "").decode("utf-8")
        return True, text, data.get("sha", "")
    except (ValueError, KeyError, TypeError, OSError) as e:
        return False, f"解码失败: {e}", ""


def _pull_and_merge(token, rel_path, is_script):
    """拉取远程单文件并与本地做条目级三方合并，结果回写本地与基线快照。

    供「启动拉取」与「推送前防覆盖」共用。返回 True 表示本地文件有更新。
    任何失败只记日志，绝不影响启动/退出主流程。"""
    local_path = os.path.join(APP_DIR, rel_path)
    base_path = CALIB_BASE_SNAPSHOT if is_script else CALIB_KB_BASE_SNAPSHOT
    local_text = _read_sync_text(local_path)
    base_text = _read_sync_text(base_path)
    ok, remote_text, _sha = _gh_fetch_file(token, rel_path)
    if not ok:
        _sync_log(f"拉取[{rel_path}]跳过合并：{str(remote_text)[:100]}")
        return False
    if not local_text.strip():
        # 本地缺失（新装机/误删）：直接采用远程最新版
        _atomic_write(local_path, remote_text)
        _atomic_write(base_path, remote_text)
        _sync_log(f"拉取[{rel_path}]：本地缺失，已采用远程版（{len(remote_text)} 字符）")
        return True
    if remote_text == local_text:
        if base_text != local_text:              # 修复基线缺失/漂移
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
    _sync_log(f"合并[{rel_path}]：并入 {added} 条，"
              f"冲突 {len(conflicts) if isinstance(conflicts, list) else conflicts} 条（保留本地）")
    return True


def sync_calib_on_startup():
    """启动时后台同步：拉取仓库最新校准知识并入本地（多用户收敛的「拉」半程）。

    与退出推送（sync_calib_on_exit）构成闭环：启动 拉取+合并，退出 合并+推送，
    每个用户每次启动都拿到全体用户沉淀的并集。幂等、静默、best-effort；
    VT_NO_CALIB_SYNC 同样禁用本入口。返回 (ok, 说明)。
    """
    try:
        if os.environ.get("VT_NO_CALIB_SYNC"):
            return False, "已禁用同步"
        token = _gh_token()          # 可为空：公开库匿名读
        changed_s = _pull_and_merge(token, SYNC_REL_PATH, True)
        changed_k = _pull_and_merge(token, SYNC_KB_REL_PATH, False)
        return (changed_s or changed_k), "ok"
    except Exception as e:  # noqa: BLE001
        _sync_log(f"启动同步异常（忽略）: {e}")
        return False, str(e)


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
            text = Path(arg).read_text(encoding="utf-8", errors="ignore")
        except Exception:
            try:
                text = Path(arg).read_text(encoding="gbk", errors="ignore")
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

    for i in range(attempts):
        result = run_process([ytdlp, "-J", "--no-playlist", url],
                             capture_output=True, text=True,
                             encoding="utf-8", errors="replace")
        out = result.stdout or ""
        if result.returncode == 0 and out.strip().startswith("{"):
            return out
        err = (result.stderr or "") + out
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
        result = run_process(cmd, capture_output=True, text=True, check=True)
        return float(result.stdout.strip())
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

    result = run_process(cmd, capture_output=True, text=True)
    success = result.returncode == 0
    if not success:
        print(f"     [错误] {result.stderr[-200:]}")
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
