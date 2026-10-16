# -*- coding: utf-8 -*-
# @version 2.3.1
"""路径与数据根（运行期产物一律落数据根，不回写系统盘）（v2.3.1 拆分工程 · 自 video_toolbox.py 原样搬入）。

本模块是 src/core/shared/ 的组成部分；域间依赖规则见 core/__init__.py。
"""
import os
import re
import shutil
import sys
import tempfile

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
    # 源码态：本文件位于 APP_DIR\src\core\shared\paths.py（v2.3.1 拆分后
    # 比单体时代深了两级），故取本文件上**四级**为程序根。层级数是硬契约：
    # 改浅/改深都会让 APP_DIR 指错（数据根、tools、logs 全歪），动此文件
    # 位置时必须同步改这里，并用 `_selftest_core_api` 的行为抽查兜底。
    APP_DIR = os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
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


def app_icon_path():
    r"""定位应用图标（ico）：冻结态优先读 PyInstaller 解压目录。

    v2.1.0 引入。此前程序**完全没有窗口图标**——exe 文件本身也没有
    （spec 的 ``EXE(icon=...)`` 是这次才加的），任务栏与资源管理器全是
    默认的空白 exe 图标。

    三处候选，依次回退：
      1. ``sys._MEIPASS/assets``：onefile 冻结态，spec 的 ``datas`` 收进来的
         那一份。**必须用 _MEIPASS 而不能用 APP_DIR**——冻结后 exe 旁边
         只有 exe，``assets\`` 并不在磁盘上。
      2. ``APP_DIR/assets``：安装版（iss 把 assets 装到程序目录）——注意
         安装版里这一份其实用不上（窗口图标可从 exe 资源段直接取），留着
         是为了万一将来走"装了就散装"的形态时也能用。
      3. ``APP_DIR/assets`` 的父目录再找一次：源码态 ``APP_DIR`` 是仓库根，
         图标就在 ``assets/`` 下；这一条主要是为开发时从别处启动兜底。
    找不到就返回 ``""``——**绝不抛异常**：图标缺失只是少个图，不能因此
    让程序起不来。
    """
    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(os.path.join(meipass, "assets", "app_icon.ico"))
    candidates.append(os.path.join(APP_DIR, "assets", "app_icon.ico"))
    candidates.append(
        os.path.join(os.path.dirname(APP_DIR), "assets", "app_icon.ico"))
    for p in candidates:
        try:
            if p and os.path.isfile(p):
                return p
        except Exception:  # noqa: BLE001
            continue
    return ""

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


# ========== 配置文件路径（v2.3.1：CONFIG_PATH 归 paths——_migrate_legacy_layout
# 在模块级就要用它，跟设置读写同搬会造成 core.shared 导入循环） ==========
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

# XDG / HuggingFace 缓存目录重定向：huggingface-hub（本地 faster-whisper 权重，
# 单个模型 0.5~1.6 GB）、yt-dlp 等第三方组件默认按 XDG 规范把缓存写到
# %USERPROFILE%\.cache（C 盘）。这里统一改写到数据根目录下的 .cache，
# 与「运行期产物一律不落系统盘」保持一致；已随软件搬迁的既有缓存原样可用，
# 不会触发重新下载。子进程经 worker_subprocess_env() 继承同一设置。
CACHE_DIR = os.path.join(DATA_ROOT, ".cache")
os.environ["XDG_CACHE_HOME"] = CACHE_DIR
os.environ["HF_HOME"] = os.path.join(CACHE_DIR, "huggingface")
os.environ["HF_HUB_CACHE"] = os.path.join(CACHE_DIR, "huggingface", "hub")
# deno（yt-dlp 的 JS 运行时）默认缓存 %LOCALAPPDATA%\deno；modelscope（字幕引擎
# 模型下载通道）默认 ~/.cache/modelscope —— 两者都不认 XDG，必须单独指定。
os.environ["DENO_DIR"] = os.path.join(CACHE_DIR, "deno")
os.environ["MODELSCOPE_CACHE"] = os.path.join(CACHE_DIR, "modelscope")
# XDG 的另外两兄弟一并收编：部分库把配置/数据散在 ~/.config、~/.local/share。
os.environ["XDG_CONFIG_HOME"] = os.path.join(CACHE_DIR, "xdg-config")
os.environ["XDG_DATA_HOME"] = os.path.join(CACHE_DIR, "xdg-data")
try:
    os.makedirs(CACHE_DIR, exist_ok=True)
except OSError:
    pass


# ========== 通用小函数：路径规范化（download 域通用，shared 先行托管） ==========
def clean_path(path):
    path = path.strip()
    if len(path) >= 2 and ((path[0] == '"' and path[-1] == '"') or (path[0] == "'" and path[-1] == "'")):
        path = path[1:-1]
    return path.strip()


__all__ = [
    "APP_DIR",
    "SCRIPT_DIR",
    "TOOLS_DIR",
    "SRC_DIR",
    "DOCS_DIR",
    "app_icon_path",
    "clean_path",
    "DATA_ROOT_POINTER",
    "DATA_ROOT",
    "DATA_DIR",
    "LOGS_DIR",
    "DEFAULT_DOWNLOAD_DIR",
    "THUMB_CACHE_DIR",
    "TMP_DIR",
    "CACHE_DIR",
    "YTDLP_URL",
    "FFMPEG_ZIP_URL",
    "DENO_URL",
    "DENO_MIRROR_URL",
    "YTDLP_PATH",
    "FFMPEG_PATH",
    "FFPROBE_PATH",
    "DENO_PATH",
    "CONFIG_PATH",
]
