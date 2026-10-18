# -*- coding: utf-8 -*-
# @version 2.3.1
"""下载依赖引导（yt-dlp / ffmpeg / deno / libmpv，首次运行自动落 tools\）（v2.3.1 拆分工程 · 自 video_toolbox.py 原样搬入）。

core/download 域：yt-dlp 全链 / cookie / NPE / 媒体合并；依赖规则见 core/__init__.py。
"""

from core.shared.paths import DENO_MIRROR_URL, DENO_URL, FFMPEG_ZIP_URL, FFPROBE_PATH, YTDLP_URL
from core.shared.proxy import ensure_builtin_proxy


import os
import shutil
import sys
import urllib.request
import zipfile

from core.shared.paths import (DENO_MIRROR_URL, DENO_PATH, DENO_URL,
                               FFMPEG_PATH, FFMPEG_ZIP_URL, FFPROBE_PATH,
                               TOOLS_DIR, YTDLP_PATH, YTDLP_URL)
from core.shared.proc import _BOOTSTRAP_LOCK
from core.shared.proxy import ensure_builtin_proxy, ytdlp_proxy_args
from core.shared.runtime import vc_bundled_resource_dir

def _download(url, dest, label, use_proxy=True):
    """下载文件；直连失败时自动启用内置代理重试（GitHub/HuggingFace 等开源库场景）。"""
    print(f"[setup] 正在下载 {label} ...")
    try:
        urllib.request.urlretrieve(url, dest)
        return
    except Exception as e:
        if not use_proxy:
            raise
        print(f"[setup] 直连失败（{e}），改用代理重试 ...")
        # 2026-10-16：改走统一代理链路（系统代理优先；内置 mihomo 默认已下线）
        _pa = ytdlp_proxy_args()
        proxy = _pa[1] if _pa else ""
        if not proxy:
            print("[setup] 无可用代理（系统代理未开启且内置代理已停用），下载失败")
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




__all__ = [
    "ensure_ytdlp",
    "ensure_ffmpeg",
    "ensure_mpv_dll",
    "MPV_DLL_URL",
]
