# -*- coding: utf-8 -*-
"""下载开源依赖（不参与安装包构建，一律从网上拉取）。

所有第三方开源组件都由本脚本在安装后/运行时从官方开源地址下载到 tools/ 目录：
  - yt-dlp.exe          GitHub Releases
  - deno.exe            GitHub Releases（yt-dlp 提取 YouTube 所需的 JS 运行时）
  - ffmpeg.exe/ffprobe  BtbN/FFmpeg-Builds GitHub Releases
  - Chromium 内核       通过 tools/python 的 Playwright CLI 下载（版本自动匹配）
  - VideoCaptioner      字幕处理引擎：从随包 wheel 解包到 tools/python 的
                        site-packages（v1.10.0 起，纯 Python 包，无需 pip）
  - Python 环境         python.org 官方 embeddable（占位下载，见 --python）

用法：
  python tools/download_open_source_deps.py                 # 下载全部
  python tools/download_open_source_deps.py --only yt-dlp,ffmpeg
  python tools/download_open_source_deps.py --skip chromium
  python tools/download_open_source_deps.py --only videocaptioner
  python tools/download_open_source_deps.py --python 3.12.9 # 额外下载 Python embeddable
"""
import argparse
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

TOOLS = Path(__file__).resolve().parent

# 内置代理（mihomo，随安装包分发）：下载开源库依赖失败时自动启用
MIHOMO_DIR = TOOLS / "mihomo"
MIHOMO_EXE = MIHOMO_DIR / "mihomo.exe"
MIHOMO_CONFIG = MIHOMO_DIR / "config.yaml"
MIHOMO_PORT = 7897
_MIHOMO_PROC = None

# 下载清单：name -> (url, 目标相对路径, 说明)
YT_DLP = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
FFMPEG_ZIP = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
DENO_ZIP = ("https://github.com/denoland/deno/releases/latest/download/"
            "deno-x86_64-pc-windows-msvc.zip")


def _port_listening(port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def ensure_mihomo_proxy() -> str | None:
    """确保内置 mihomo 代理可用；返回代理地址或 None（幂等，直连可用时不触发）。"""
    global _MIHOMO_PROC
    if _port_listening(MIHOMO_PORT):
        return f"http://127.0.0.1:{MIHOMO_PORT}"
    if not (MIHOMO_EXE.exists() and MIHOMO_CONFIG.exists()):
        return None
    try:
        MIHOMO_DIR.mkdir(parents=True, exist_ok=True)
        _MIHOMO_PROC = subprocess.Popen(
            [str(MIHOMO_EXE), "-d", str(MIHOMO_DIR), "-f", str(MIHOMO_CONFIG)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:
        return None
    for _ in range(40):
        if _port_listening(MIHOMO_PORT):
            return f"http://127.0.0.1:{MIHOMO_PORT}"
        if _MIHOMO_PROC.poll() is not None:
            return None
        time.sleep(0.5)
    return None


def _stream_to_file(resp, tmp: Path, total: int) -> None:
    got = 0
    with open(tmp, "wb") as fh:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)
            got += len(chunk)
            if total:
                print(f"\r  {got / 1048576:.0f}/{total / 1048576:.0f}MB "
                      f"{got * 100 // total}%", end="")


def _download(url: str, dest: Path) -> None:
    """带简单进度条的下载；dest 不存在时才下载。直连失败自动启用内置代理重试。"""
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  已存在，跳过: {dest.name} ({dest.stat().st_size / 1048576:.0f}MB)")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "VideoToolbox/1.9.3"})
    print(f"  下载 {url}")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            _stream_to_file(resp, tmp, int(resp.headers.get("Content-Length") or 0))
        print()
    except Exception as e:
        print(f"  直连失败（{e}），启用内置代理重试 ...")
        proxy = ensure_mihomo_proxy()
        if not proxy:
            print("  内置代理不可用，下载失败")
            raise
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
        with opener.open(req, timeout=180) as resp:
            _stream_to_file(resp, tmp, int(resp.headers.get("Content-Length") or 0))
        print()
        print("  代理下载完成")
    tmp.replace(dest)
    print(f"  完成: {dest} ({dest.stat().st_size / 1048576:.0f}MB)")


def install_ytdlp() -> None:
    print("[1/5] yt-dlp")
    _download(YT_DLP, TOOLS / "yt-dlp.exe")


def install_deno() -> None:
    """deno：yt-dlp 提取 YouTube 所需的 JS 运行时（2026 版起弃用无 JS 提取）。

    与 yt-dlp.exe 放同目录即被自动发现；官方源失败时尝试 gh-proxy 镜像。
    """
    print("[2/5] deno（YouTube 提取 JS 运行时，约 43MB）")
    if (TOOLS / "deno.exe").exists():
        print("  已存在，跳过")
        return
    zpath = TOOLS / "_deno.zip"
    try:
        _download(DENO_ZIP, zpath)
    except Exception as e:
        print(f"  官方源失败（{e}），改用 gh-proxy 镜像 ...")
        _download("https://gh-proxy.com/" + DENO_ZIP, zpath)
    with zipfile.ZipFile(zpath) as zf:
        with zf.open("deno.exe") as src, open(TOOLS / "deno.exe", "wb") as dst:
            dst.write(src.read())
    zpath.unlink(missing_ok=True)
    print(f"  完成: {TOOLS / 'deno.exe'}")


def install_ffmpeg() -> None:
    print("[3/5] ffmpeg / ffprobe")
    if (TOOLS / "ffmpeg.exe").exists() and (TOOLS / "ffprobe.exe").exists():
        print("  已存在，跳过")
        return
    zpath = TOOLS / "_ffmpeg_builds.zip"
    _download(FFMPEG_ZIP, zpath)
    print("  解压 ffmpeg/ffprobe ...")
    with zipfile.ZipFile(zpath) as zf:
        for name in zf.namelist():
            base = Path(name).name
            if base in ("ffmpeg.exe", "ffprobe.exe"):
                with zf.open(name) as src, open(TOOLS / base, "wb") as dst:
                    dst.write(src.read())
                print(f"  提取 {base}")
    zpath.unlink(missing_ok=True)


def install_chromium() -> None:
    print("[4/5] Chromium 内核（Playwright）")
    py = TOOLS / "python" / "python.exe"
    if not py.exists():
        print("  未找到 tools/python，跳过（先安装 Python 环境）")
        return
    import subprocess
    r = subprocess.run([str(py), "-m", "playwright", "install", "chromium"],
                       cwd=str(TOOLS))
    if r.returncode:
        print("  Playwright chromium 安装失败，可稍后重试")
        sys.exit(1)


def install_videocaptioner() -> None:
    """把随包 wheel 解包安装到内嵌运行时的 site-packages（纯 Python 包，无需 pip）。

    v1.10.0 起字幕链路由 VideoCaptioner 承担：完整版安装包已随包分发装好的
    环境，此步骤用于「轻量安装形态」或用户误删后的修复。
    """
    print("[5/5] VideoCaptioner 字幕处理引擎")
    site = TOOLS / "python" / "Lib" / "site-packages"
    if not site.is_dir():
        print(f"  跳过：内嵌运行时不存在（{site}），请先用完整版安装包安装")
        return
    if (site / "videocaptioner").is_dir():
        print("  已安装，跳过")
        return
    wheels = sorted((TOOLS / "videocaptioner").glob("videocaptioner-*.whl"))
    if not wheels:
        print(f"  跳过：随包 wheel 缺失（{TOOLS / 'videocaptioner'}）")
        return
    wheel = wheels[-1]
    print(f"  从 {wheel.name} 解包 …")
    n = 0
    with zipfile.ZipFile(wheel) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            dest = site / info.filename.replace("/", os.sep)
            dest.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(dest, "wb") as fh:
                shutil.copyfileobj(src, fh)
            n += 1
    if not (site / "videocaptioner").is_dir():
        raise RuntimeError("解包完成但未找到 videocaptioner 包目录")
    missing = [m for m in ("PyQt5", "qfluentwidgets") if not (site / m).is_dir()]
    print(f"  已写入 {n} 个文件" + (f"；仍缺少依赖 {missing}" if missing else ""))


def install_python(ver: str) -> None:
    """下载 python.org 官方 embeddable 包（占位实现，最终建议使用完整安装器+requirements）。"""
    print("[*] Python embeddable（占位）")
    url = (f"https://www.python.org/ftp/python/{ver}/"
           f"python-{ver}-embed-amd64.zip")
    _download(url, TOOLS / f"python-{ver}-embed-amd64.zip")
    print("  注意：embeddable 不含第三方库；完整环境请使用官方安装器并 pip 安装依赖")


def main():
    ap = argparse.ArgumentParser(description="下载开源依赖到 tools/ 目录")
    ap.add_argument("--only", help="仅下载指定项，逗号分隔："
                                   "yt-dlp,deno,ffmpeg,chromium,videocaptioner")
    ap.add_argument("--skip", help="跳过指定项，逗号分隔")
    ap.add_argument("--python", metavar="VER", help="额外下载 Python embeddable，如 3.12.9")
    args = ap.parse_args()

    only = set(x.strip() for x in args.only.split(",")) if args.only else None
    skip = set(x.strip() for x in args.skip.split(",")) if args.skip else set()

    def want(name: str) -> bool:
        return (only is None or name in only) and name not in skip

    steps = [("yt-dlp", install_ytdlp),
             ("deno", install_deno),
             ("ffmpeg", install_ffmpeg),
             ("chromium", install_chromium),
             ("videocaptioner", install_videocaptioner)]
    for name, fn in steps:
        if want(name):
            try:
                fn()
            except Exception as e:  # noqa: BLE001
                print(f"  {name} 下载失败: {e}")

    if args.python:
        install_python(args.python)

    print("\n全部完成。缺失项可重跑本脚本，已下载的会自动跳过。")


if __name__ == "__main__":
    main()
