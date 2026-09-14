#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
视频工具箱 v1.9.0（单文件整合版）
==================================================
v1.9.0：接入全局 AI（智谱 GLM：glm-4.7-flash 文本 + glm-4.6v-flash 视觉，
  配置 data\ai_config.json）；B站投稿的分区检测/分区选择/简介填写/话题参与
  全部改为 AI 屏幕识别 + 模拟鼠标点击/滚动（不注入页面脚本）；
  字幕语言由 AI 识别标题语言自动匹配（下载与投稿两侧）。
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
import subprocess
import urllib.request
import zipfile
import re
import time
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
TOOLS_DIR = os.path.join(APP_DIR, "tools")
SRC_DIR = os.path.join(APP_DIR, "src")
DOCS_DIR = os.path.join(APP_DIR, "docs")
DATA_DIR = os.path.join(APP_DIR, "data")
LOGS_DIR = os.path.join(APP_DIR, "logs")
DEFAULT_DOWNLOAD_DIR = os.path.join(DATA_DIR, "downloads")
THUMB_CACHE_DIR = os.path.join(DATA_DIR, "thumb_cache")

YTDLP_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
FFMPEG_ZIP_URL = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"

YTDLP_PATH = os.path.join(TOOLS_DIR, "yt-dlp.exe")
FFMPEG_PATH = os.path.join(TOOLS_DIR, "ffmpeg.exe")
FFPROBE_PATH = os.path.join(TOOLS_DIR, "ffprobe.exe")

CONFIG_PATH = os.path.join(DATA_DIR, "config.json")


def _migrate_legacy_layout():
    """v1.6 及以前版本散落在程序根/tools 下的用户数据，一次性迁移到 data/logs（幂等）。"""
    # (旧位置, 新位置)；仅当新位置为空且旧位置存在时迁移
    moves = [
        (os.path.join(APP_DIR, "config.json"), CONFIG_PATH),
        (os.path.join(APP_DIR, "downloads"), DEFAULT_DOWNLOAD_DIR),
        (os.path.join(APP_DIR, "thumb_cache"), THUMB_CACHE_DIR),
        (os.path.join(TOOLS_DIR, "uploader_profile"),
         os.path.join(DATA_DIR, "uploader_profile")),
        (os.path.join(TOOLS_DIR, "uploader_tasks"),
         os.path.join(DATA_DIR, "uploader_tasks")),
        (os.path.join(TOOLS_DIR, "uploader_logs"),
         os.path.join(LOGS_DIR, "uploader")),
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
for _d in (DATA_DIR, LOGS_DIR, DEFAULT_DOWNLOAD_DIR, THUMB_CACHE_DIR):
    os.makedirs(_d, exist_ok=True)


def _fallback_config_path():
    """脚本目录只读时（如装在 Program Files）的配置回退位置"""
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    return os.path.join(base, "VideoToolbox", "config.json")

DEFAULT_INPUT_DIR = r"D:\剪辑"
DURATION_THRESHOLD = 1.0
URL_RE = re.compile(r'https?://[^\s"<>\)\]]+')
# =============================


# ========== ASR 本地字幕生成（运行时内置，模型从开源库自行下载） ==========
# 运行时：tools\python 下内嵌的 faster-whisper + ctranslate2（不含 torch/gradio），
# 随安装包分发。识别模型（large-v3-turbo，约 1.5GB）体积过大，不进入安装包，
# 改由用户从开源模型库（Hugging Face）自行下载到 tools\asr_model 后即可使用。
ASR_PYTHON_DIR = os.path.join(TOOLS_DIR, "python")
ASR_MODEL_DIR = os.path.join(TOOLS_DIR, "asr_model")

# 模型开源仓库（CTranslate2 版 Whisper large-v3-turbo，faster-whisper 官方默认源）。
# 需下载其中的 model.bin / config.json / tokenizer.json / vocabulary.json /
# preprocessor_config.json 等文件，放到 tools\asr_model 目录。
ASR_MODEL_REPO = "mobiuslabsgmbh/faster-whisper-large-v3-turbo"
ASR_MODEL_URL_HF = "https://huggingface.co/" + ASR_MODEL_REPO + "/tree/main"
ASR_MODEL_URL_MIRROR = "https://hf-mirror.com/" + ASR_MODEL_REPO + "/tree/main"


def asr_model_missing_hint():
    """模型未下载时给用户的引导文案（含打开镜像直链的说明）。"""
    return ("字幕识别模型（Whisper large-v3-turbo，约 1.5GB）未包含在安装包内，"
            "需自行从开源模型库下载到：\n"
            + ASR_MODEL_DIR + "\n\n"
            "国内网络可访问镜像站下载：\n" + ASR_MODEL_URL_MIRROR + "\n"
            "海外网络可访问：\n" + ASR_MODEL_URL_HF + "\n\n"
            "把仓库里的 model.bin、config.json、tokenizer.json、vocabulary.json、"
            "preprocessor_config.json 下载后放入上述文件夹即可，无需改目录名。")


def system_python():
    """运行 ASR/投稿 worker 的 Python：优先用工具箱内 tools\\python\\python.exe；
    否则源码模式用当前解释器，打包后用系统 PATH 中的 python。"""
    embedded = os.path.join(ASR_PYTHON_DIR, "python.exe")
    if os.path.isfile(embedded):
        return embedded
    if not getattr(sys, "frozen", False):
        return sys.executable
    return shutil.which("python") or ""


def asr_env_ready():
    """内置 ASR 环境是否可用（tools\\\\python 运行时 + 模型齐全）"""
    return os.path.isdir(ASR_PYTHON_DIR) and os.path.isfile(
        os.path.join(ASR_MODEL_DIR, "model.bin")) and bool(system_python())


def asr_worker_script():
    """转写 worker 脚本路径；打包后随 datas 解包到 _MEIPASS，源码模式在 src 目录"""
    if getattr(sys, "frozen", False):
        return os.path.join(getattr(sys, "_MEIPASS", SCRIPT_DIR),
                            "asr_subtitle_worker.py")
    return os.path.join(SRC_DIR, "asr_subtitle_worker.py")


def asr_subprocess_env():
    """ASR 子进程环境：内嵌解释器已完整自包含，无需注入 PYTHONPATH；
    仅当回退到系统 Python 时，把内嵌 site-packages 追加进去以免缺包。"""
    env = os.environ.copy()
    if system_python() != os.path.join(ASR_PYTHON_DIR, "python.exe"):
        sp = os.path.join(ASR_PYTHON_DIR, "Lib", "site-packages")
        env["PYTHONPATH"] = (sp + os.pathsep +
                             env.get("PYTHONPATH", "")).rstrip(os.pathsep)
    return env
# =============================


# ========== B 站自动投稿（工具箱内置 Playwright 引擎，完全自包含） ==========
# 引擎源码内嵌在 tools\uploader_src（modules + 编排 runner），
# 运行时/浏览器内核内嵌在 tools\python 与 tools\ms-playwright；
# 登录态存 tools\uploader_profile（首次扫码）。
UPLOADER_SRC_DIR = os.path.join(TOOLS_DIR, "uploader_src")
UPLOADER_MODULES_DIR = os.path.join(UPLOADER_SRC_DIR, "modules")
UPLOADER_RUNNER = os.path.join(UPLOADER_SRC_DIR, "uploader_runner.py")
# 登录态/任务归 data，投稿日志与截图归 logs（v1.7 分目录）
UPLOADER_PROFILE = os.path.join(DATA_DIR, "uploader_profile")
UPLOADER_LOGS_DIR = os.path.join(LOGS_DIR, "uploader")
UPLOADER_TASKS_DIR = os.path.join(DATA_DIR, "uploader_tasks")
CATALOG_DIR = os.path.join(DATA_DIR, "catalog")
for _d in (UPLOADER_PROFILE, UPLOADER_LOGS_DIR, UPLOADER_TASKS_DIR,
           os.path.join(UPLOADER_LOGS_DIR, "screenshots"), CATALOG_DIR):
    os.makedirs(_d, exist_ok=True)


def uploader_env_ready():
    """内置投稿引擎是否可用：modules + runner + playwright 依赖齐全"""
    py = system_python()
    if not py or not os.path.isfile(UPLOADER_RUNNER) \
            or not os.path.isdir(UPLOADER_MODULES_DIR):
        return False
    if py == sys.executable:
        try:
            import importlib.util
            return importlib.util.find_spec("playwright") is not None
        except Exception:
            return False
    try:
        r = run_process([py, "-c", "import playwright"],
                        capture_output=True, timeout=60)
        return r.returncode == 0
    except Exception:
        return False


def write_uploader_task(job):
    """把投稿任务写成 JSON 落到工具箱 uploader_tasks 目录，返回路径"""
    os.makedirs(UPLOADER_TASKS_DIR, exist_ok=True)
    path = os.path.join(UPLOADER_TASKS_DIR,
                        f"vt_{datetime.now():%Y%m%d_%H%M%S}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(job, f, ensure_ascii=False, indent=2)
    return path


_INFO_STOP_PREFIXES = ("视频链接", "博主", "标签", "分区", "创作声明", "话题",
                       "下载画质", "下载时间", "======")
# 投稿可回填字段（与 sidecar.py / 投稿 GUI 表单一一对应）
_INFO_FIELD_KEYS = ("title", "description", "tags", "zone", "declaration", "topics")


def parse_info_txt(path):
    """解析下载时生成的 视频信息.txt，取出投稿所需全部字段。

    支持键（全/半角冒号均可）：标题 / 简介（多行块）/ 标签 / 分区 /
    创作声明 / 话题 / 视频链接 / 博主主页。返回：
    {"title","description","tags":[], "zone":"", "declaration":"", "topics":[],
     "source_url":"", "uploader_url":""}
    """
    empty = {"title": "", "description": "", "tags": [], "zone": "",
             "declaration": "", "topics": [],
             "source_url": "", "uploader_url": ""}
    try:
        text = Path(path).read_text(encoding="utf-8-sig", errors="ignore")
    except OSError:
        return empty
    title, desc_lines, in_desc = "", [], False
    tags, zone, declaration, topics = [], "", "", []
    source_url, uploader_url = "", ""
    for raw in text.splitlines():
        s = raw.strip()
        key = s.replace("：", ":", 1)
        if key.startswith("标题:"):
            title = key.split(":", 1)[1].strip()
            in_desc = False
            continue
        if key.startswith("简介:"):
            val = key.split(":", 1)[1].strip()
            desc_lines = [val] if val else []
            in_desc = True
            continue
        if in_desc:
            if any(s.startswith(p) for p in _INFO_STOP_PREFIXES):
                in_desc = False          # 简介块结束，落到下面的字段解析
            else:
                desc_lines.append(raw if s else "")
                continue
        if key.startswith("标签:"):
            tags = [t.strip() for t in re.split(r"[,，、;；\s]+",
                    key.split(":", 1)[1]) if t.strip()]
        elif key.startswith("话题:"):
            topics = [t.strip() for t in re.split(r"[,，、;；\s]+",
                      key.split(":", 1)[1]) if t.strip()]
        elif key.startswith("分区:"):
            zone = key.split(":", 1)[1].strip()
        elif key.startswith("创作声明:"):
            declaration = key.split(":", 1)[1].strip()
        elif key.startswith("视频链接:"):
            source_url = key.split(":", 1)[1].strip()
        elif key.startswith("博主主页:"):
            uploader_url = key.split(":", 1)[1].strip()
    while desc_lines and not desc_lines[-1].strip():
        desc_lines.pop()
    return {
        "title": title,
        "description": "\n".join(desc_lines).strip(),
        "tags": tags, "zone": zone,
        "declaration": "" if declaration in ("", "（无）", "无需标注") else declaration,
        "topics": topics,
        "source_url": source_url,
        "uploader_url": uploader_url,
    }
# =============================


def build_posting_description(info):
    """按用户指定的投稿简介格式生成简介文本。

    格式（源地址/来源同一行标签的地址换行填写，原简介换行填写）：
      源地址：
      {视频链接}
      来源：{博主主页}
      原简介：
      {原简介}
    未提供源地址时退回原简介原文。
    """
    desc = str(info.get("description") or "").strip()
    src = str(info.get("source_url") or "").strip()
    up = str(info.get("uploader_url") or "").strip()
    if not src or src == "（无）":
        return desc
    lines = ["源地址：", src, f"来源：{up or '（无）'}"]
    if desc:
        lines.append("原简介：")
        lines.append(desc)
    else:
        lines.append("原简介：")
    return "\n".join(lines)


def find_subtitle_for_video(video, lang_code=""):
    """在视频同目录自动查找“原始字幕” .srt，用于投稿时同步上传。

    优先级：1) 与视频同名（base.srt）  2) 标题语言字幕（base.en.srt 等，
            语言由 AI 识别标题得出，未识别时默认英文）  3) 同名前缀
            （含语言/清晰度后缀）  4) 目录下任意第一个 .srt
    找不到返回空字符串。
    """
    video = clean_path(video or "")
    if not video or not os.path.isfile(video):
        return ""
    d = os.path.dirname(video)
    base = os.path.splitext(os.path.basename(video))[0].lower()
    try:
        names = os.listdir(d)
    except OSError:
        return ""
    srts = [n for n in names if n.lower().endswith(".srt")]
    if not srts:
        return ""
    for n in srts:
        if n.lower() == base + ".srt":
            return os.path.join(d, n)
    # 标题语言优先（AI 识别）；未识别时保持旧行为：英文优先
    suffixes = _subtitle_suffixes_for(lang_code or "en")
    for suf in suffixes:
        for n in srts:
            if re.search(r"[._-]" + re.escape(suf) + r"\.srt$", n.lower()):
                return os.path.join(d, n)
    for n in srts:
        if n.lower().startswith(base):
            return os.path.join(d, n)
    return os.path.join(d, srts[0])


def _subtitle_suffixes_for(lang_code):
    """语言代码 → 字幕文件名后缀列表（经 AI 模块映射，失败时用内置表）。"""
    try:
        return list(ai_mod().SUBTITLE_FILE_SUFFIXES.get(lang_code, ()) \
                    or ai_mod().SUBTITLE_FILE_SUFFIXES["en"])
    except Exception:
        return {
            "zh": ("zh-hans", "zh-cn", "zh-hant", "zh-tw", "zh"),
            "en": ("en", "en-us", "en-gb"),
            "ja": ("ja", "jp"), "ko": ("ko", "kr"),
        }.get(lang_code, ("en", "en-us", "en-gb"))


# ========== 全局 AI（智谱 GLM：屏幕识别 + 内容识别） ==========
# AI 客户端实现内嵌在 tools\uploader_src\modules\ai_client.py（仅标准库依赖），
# GUI 进程按路径直接加载，与投稿引擎子进程共用同一份配置 data\ai_config.json。
_AI_MOD = None


def ai_mod():
    """按路径加载内嵌 AI 客户端模块（缓存单例）。"""
    global _AI_MOD
    if _AI_MOD is None:
        import importlib.util
        path = os.path.join(UPLOADER_MODULES_DIR, "ai_client.py")
        spec = importlib.util.spec_from_file_location("vt_ai_client", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _AI_MOD = mod
    return _AI_MOD


def ai_status():
    """AI 配置概览：(是否启用, 文本模型, 视觉模型)；配置不可读时 enabled=False。"""
    try:
        cfg = ai_mod().load_config()
        return bool(cfg.get("enabled", True)), \
            str(cfg.get("model") or ""), str(cfg.get("vision_model") or "")
    except Exception:
        return False, "", ""


def ai_quick_test():
    """AI 连通性自检：(ok, 信息)。供 GUI「测试 AI」按钮调用（需在线程中跑）。"""
    try:
        return ai_mod().quick_test()
    except Exception as e:
        return False, str(e)


def ai_detect_language(text):
    """AI 识别文本主要语言代码（zh/en/ja/...）；AI 不可用或失败返回 ''。"""
    try:
        if not ai_mod().is_enabled():
            return ""
        return ai_mod().detect_language(text)
    except Exception:
        return ""


def bili_subtitle_lang(lang_code, default=""):
    """语言代码 → B 站字幕语言显示名（投稿表单字幕语言用）。"""
    try:
        return ai_mod().bili_subtitle_lang(lang_code, default)
    except Exception:
        return default


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


def _download(url, dest, label):
    print(f"[setup] 正在下载 {label} ...")
    urllib.request.urlretrieve(url, dest)


def ensure_ytdlp():
    with _BOOTSTRAP_LOCK:
        if os.path.isfile(YTDLP_PATH):
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

    部分站点（如 B 站）对无 cookie 的连续请求有风控，随机返回 HTTP 412，
    这里自动等待后重试；attempts 次仍失败返回 None。
    log 为可选回调，用于向 GUI / 命令行透出重试进度。
    """
    def _log(msg):
        if log:
            try:
                log(msg)
            except Exception:
                pass

    for i in range(attempts):
        result = run_process([ytdlp, "-J", "--no-playlist", url],
                             capture_output=True, text=True,
                             encoding="utf-8", errors="replace")
        out = result.stdout or ""
        if result.returncode == 0 and out.strip().startswith("{"):
            return out
        err = (result.stderr or "") + out
        retryable = ("412" in err or "Unable to download webpage" in err
                     or "timed out" in err.lower())
        if not retryable or i == attempts - 1:
            return None
        wait = wait_base * (i + 1)
        _log(f"[信息] 站点风控/网络拦截，{wait}s 后自动重试 ({i + 2}/{attempts}) ...")
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
