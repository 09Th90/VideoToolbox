# -*- coding: utf-8 -*-
# @version 2.5.1
"""下载域通用小函数（格式化/命名/产物文件 write_info_txt/封面）（v2.3.1 拆分工程 · 自 video_toolbox.py 原样搬入）。

core/download 域：yt-dlp 全链 / cookie / NPE / 媒体合并；依赖规则见 core/__init__.py。
"""

import subprocess
import time
from datetime import datetime
from core.shared.proc import kill_process_tree, popen_process

import os
import re
import sys

from core.shared.textio import write_text_utf8

# ========== 通用小函数 ==========


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


def write_info_txt(folder, data, quality_label=""):
    """把 源地址/来源/原简介/标题/博主/画质下载时间 写成 视频信息.txt
    （utf-8-sig，记事本直接可读）。

    用户样版（2026-10-06 定稿，2026-10-08 补回字段）：字段行下一行直接跟内容、
    段间只空一行：

        标题：<视频标题>

        源地址：
        <视频链接>

        来源：<频道主页>

        博主：<UP 主名>

        原简介：
        <简介全文，原样保留换行>

        下载画质：<quality_label>
        下载时间：<当前时间>

    ⚠️ 标题/博主/画质/下载时间 四项在 10-06 定稿时一度被移除，10-08 按用户
    要求补回（AI 校准仍以视频文件名取原始标题，两处互不冲突）。
    """
    def pick(*keys):
        for k in keys:
            v = data.get(k)
            if v not in (None, ""):
                return str(v).strip()
        return ""

    title = pick("title") or "（未知标题）"
    page_url = pick("webpage_url", "original_url") or "（无）"
    uploader = pick("uploader", "channel", "uploader_id")
    up_url = pick("uploader_url", "channel_url")
    if not up_url:
        uid = pick("uploader_id", "channel_id")
        if uid and "bilibili" in page_url:
            up_url = f"https://space.bilibili.com/{uid}"

    desc = pick("description") or "（无简介）"
    text = (f"标题：{title}\n\n"
            f"源地址：\n{page_url}\n\n"
            f"来源：{up_url or '（未知）'}\n\n"
            f"博主：{uploader or '（未知）'}\n\n"
            f"原简介：\n{desc}\n\n"
            f"下载画质：{quality_label or '（未知）'}\n"
            f"下载时间：{datetime.now():%Y-%m-%d %H:%M:%S}\n")

    path = os.path.join(folder, "视频信息.txt")
    with open(path, "w", encoding="utf-8-sig") as f:
        f.write(text)
    return path


def make_cover_1280x720(ffmpeg_path, folder, timeout=60, cancel=None,
                        register=None):
    """把 yt-dlp 下载的封面缩略图转为 1280x720 的 封面.jpg（等比缩放+黑边补齐），删除原图

    v1.19.1：`cancel` + `register` 让打包阶段也能被「取消选中任务」打断
    （原先 subprocess.run 跑满 timeout，用户点取消后还要白等 60s）。
    """
    def _unregister():
        if register:
            try:
                register(None)
            except Exception:  # noqa: BLE001
                pass

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
    proc = None
    try:
        proc = popen_process([ffmpeg_path, "-y", "-i", src, "-vf", vf,
                              "-frames:v", "1", "-q:v", "2", out],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except Exception:  # noqa: BLE001
        _unregister()
        return False
    if register:
        try:
            register(proc)
        except Exception:  # noqa: BLE001
            pass
    deadline = time.time() + timeout
    try:
        while True:
            if cancel is not None and cancel.is_set():
                kill_process_tree(proc)
                return False
            if proc.poll() is not None:
                break
            if time.time() > deadline:
                kill_process_tree(proc)
                return False
            time.sleep(0.1)
    finally:
        _unregister()
    if proc.returncode != 0 or not os.path.isfile(out):
        return False
    for c in cands:
        try:
            os.remove(c)
        except OSError:
            pass
    return True
# ---------- 打包结束 ----------




__all__ = [
    "format_size",
    "format_time",
    "open_folder",
    "sanitize_folder_name",
    "unique_folder",
    "write_info_txt",
    "make_cover_1280x720",
]
