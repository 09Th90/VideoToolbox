# -*- coding: utf-8 -*-
# @version 2.7.0
"""下载依赖引导（yt-dlp / ffmpeg / deno / libmpv，首次运行自动落 tools\\）。

P2：依赖下载优先走 Range 分段（core.download.segment），失败回退 urllib 单流。
公开函数签名保持不变；VT_DEPS_SEGMENTED=0 可强制回退旧单流。
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlparse

from core.shared.paths import (
    DENO_MIRROR_URL, DENO_PATH, DENO_URL,
    FFMPEG_PATH, FFMPEG_ZIP_URL, FFPROBE_PATH,
    TOOLS_DIR, YTDLP_PATH, YTDLP_URL,
)
from core.shared.proc import _BOOTSTRAP_LOCK
from core.shared.proxy import ensure_builtin_proxy, ytdlp_proxy_args
from core.shared.runtime import vc_bundled_resource_dir

#: 仅使用已验证可用、可配置的 GitHub 前缀镜像；不随机抓公共反代。
_GITHUB_MIRRORS = ("https://gh-proxy.com/",)
_GITHUB_HOSTS = frozenset({
    "github.com", "codeload.github.com", "objects.githubusercontent.com",
    "raw.githubusercontent.com", "release-assets.githubusercontent.com",
})
_MPV_DLL_SHA256 = "6f059354c5c45b41192cc52d867d94c0044edb48207c4efd2ea1244208c55359"
_MIN_YTDLP_SIZE = 1 << 20
_MIN_DENO_SIZE = 1 << 20
_MIN_FFMPEG_SIZE = 1 << 20
_YTDLP_SUMS_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/SHA2-256SUMS"


def _log(message: str, log=None) -> None:
    if log is not None:
        try:
            log(message)
            return
        except Exception:
            pass
    print(message)


def _sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _verify(path, *, expected_size=None, expected_sha256="") -> None:
    actual = os.path.getsize(path)
    if expected_size is not None and actual != expected_size:
        raise RuntimeError("大小不一致：%s/%s" % (actual, expected_size))
    if expected_sha256 and _sha256_file(path).lower() != expected_sha256.lower():
        raise RuntimeError("SHA256 不一致")


def _githubMirrors(url: str) -> tuple[str, ...]:
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return ()
    if host not in _GITHUB_HOSTS:
        return ()
    return tuple(prefix + url for prefix in _GITHUB_MIRRORS)


def _proxyMap():
    args = ytdlp_proxy_args()
    if not args:
        return None
    url = args[1] if len(args) > 1 else ""
    if not url:
        return None
    return {"http": url, "https": url}


def _fetch_text(url: str, timeout=10, log=None) -> str:
    """取小型文本（校验清单）；直连/镜像尝试，不用 Cookie。"""
    candidates = (*_githubMirrors(url), url)
    headers = {"User-Agent": "VideoToolbox/2.7.0"}
    for candidate in dict.fromkeys(candidates):
        try:
            request = urllib.request.Request(candidate, headers=headers)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read(1 << 20).decode("utf-8", errors="ignore")
        except Exception as e:  # noqa: BLE001
            _log("[setup] 取校验清单失败（%s）: %s" % (candidate, e), log)
    return ""


def _fetch_ytdlp_sha256(log=None) -> str:
    text = _fetch_text(_YTDLP_SUMS_URL, log=log)
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[-1].rstrip("*").lower() == "yt-dlp.exe":
            value = parts[0].strip().lower()
            if len(value) == 64:
                return value
    return ""


def _download_single(url, dest, label, *, expected_size=None, expected_sha256="",
                     timeout=180, proxy="", log=None) -> None:
    """旧 urllib 单流回退：先写 .part，校验后原子替换。"""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "VideoToolbox/2.7.0"})
        opener = (urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
            if proxy else urllib.request)
        open_url = opener.open if proxy else urllib.request.urlopen
        with open_url(request, timeout=timeout) as response, open(tmp, "wb") as out:
            declared = response.headers.get("Content-Length")
            shutil.copyfileobj(response, out)
        if declared:
            try:
                if tmp.stat().st_size != int(declared):
                    raise RuntimeError("连接提前结束：%s/%s" % (tmp.stat().st_size, declared))
            except ValueError:
                pass
        _verify(tmp, expected_size=expected_size, expected_sha256=expected_sha256)
        os.replace(tmp, dest)
    finally:
        try:
            if tmp.is_file():
                tmp.unlink()
        except OSError:
            pass


def _download(url, dest, label, use_proxy=True, *, expected_size=None,
              expected_sha256="", mirrors=(), connections=4, progress=None, log=None):
    """分段优先、单流回退；最终路径只在校验通过后替换。"""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    _log("[setup] 正在下载 %s ..." % label, log)
    candidates = list(dict.fromkeys(
        [url, *[m for m in mirrors if m], *_githubMirrors(url)]
    ))
    expected_sha256 = (expected_sha256 or "").strip().lower()

    def segmented(proxy_map=None, tag=""):
        try:
            from core.download.segment import DownloadRequest, download_file
        except Exception as e:  # noqa: BLE001
            _log("[setup] 分段下载不可用（%s），回退单流" % e, log)
            return False
        try:
            result = download_file(DownloadRequest(
                url=url,
                dest=dest,
                mirrors=tuple(m for m in candidates if m != url),
                expected_size=expected_size,
                expected_sha256=expected_sha256,
                connections=max(1, int(connections)),
                proxies=proxy_map,
                overwrite=True,
            ), progress=progress, log=lambda m: _log(m, log))
        except Exception as e:  # noqa: BLE001
            _log("[setup] 分段下载异常（%s）: %s" % (tag or "direct", e), log)
            return False
        if result.ok:
            _log("[setup] %s 下载完成（分段 %s 个 Range）" % (label, result.ranges), log)
            return True
        _log("[setup] 分段下载失败（%s）: %s" % (tag or "direct", result.error), log)
        return False

    is_http = urlparse(url).scheme.lower() in ("http", "https")
    if is_http and os.environ.get("VT_DEPS_SEGMENTED", "1") != "0" and segmented():
        return
    if is_http and use_proxy and os.environ.get("VT_DEPS_SEGMENTED", "1") != "0":
        proxy_map = _proxyMap()
        if proxy_map and segmented(proxy_map, "proxy"):
            return

    errors = []
    for candidate in candidates:
        try:
            _download_single(candidate, dest, label,
                             expected_size=expected_size,
                             expected_sha256=expected_sha256, log=log)
            _log("[setup] %s 下载完成（单流）" % label, log)
            return
        except Exception as e:  # noqa: BLE001
            errors.append("%s: %s" % (candidate, e))
            _log("[setup] 单流下载失败（%s）: %s" % (candidate, e), log)

    if use_proxy:
        _pa = ytdlp_proxy_args()
        proxy = _pa[1] if _pa and len(_pa) > 1 else ""
        if proxy:
            for candidate in candidates:
                try:
                    _download_single(candidate, dest, label,
                                     expected_size=expected_size,
                                     expected_sha256=expected_sha256,
                                     proxy=proxy, log=log)
                    _log("[setup] %s 下载完成（代理单流）" % label, log)
                    return
                except Exception as e:  # noqa: BLE001
                    errors.append("%s (proxy): %s" % (candidate, e))
                    _log("[setup] 代理下载失败（%s）: %s" % (candidate, e), log)
    raise RuntimeError("下载失败：%s；%s" % (label, " | ".join(errors[-3:])))


def _ensure_deno(log=None):
    """yt-dlp 提取 YouTube 需要 JS 运行时 deno；缺失时自动下载到 tools\\deno.exe。"""
    if os.path.isfile(DENO_PATH) and os.path.getsize(DENO_PATH) >= _MIN_DENO_SIZE:
        return True
    os.makedirs(TOOLS_DIR, exist_ok=True)
    zip_path = os.path.join(TOOLS_DIR, "deno.zip")
    try:
        _download(DENO_URL, zip_path, "deno",
                  mirrors=tuple(dict.fromkeys((DENO_MIRROR_URL, *_githubMirrors(DENO_URL)))),
                  log=log)
        with zipfile.ZipFile(zip_path) as z:
            bad = z.testzip()
            if bad:
                raise RuntimeError("deno zip 损坏: %s" % bad)
            with z.open("deno.exe") as src:
                tmp = DENO_PATH + ".part"
                with open(tmp, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                os.replace(tmp, DENO_PATH)
        _log("[setup] deno 就绪: %s" % DENO_PATH, log)
        return True
    except Exception as e:  # noqa: BLE001
        _log("[setup] deno 下载失败: %s" % e, log)
        _log("[setup] 可手动下载 deno-x86_64-pc-windows-msvc.zip 解压出 deno.exe 放到 "
             "%s 目录" % TOOLS_DIR, log)
        return False
    finally:
        try:
            if os.path.isfile(zip_path):
                os.remove(zip_path)
        except OSError:
            pass


def ensure_ytdlp():
    with _BOOTSTRAP_LOCK:
        if os.path.isfile(YTDLP_PATH) and os.path.getsize(YTDLP_PATH) >= _MIN_YTDLP_SIZE:
            _ensure_deno()
            return YTDLP_PATH
        os.makedirs(TOOLS_DIR, exist_ok=True)
        sha = _fetch_ytdlp_sha256()
        _download(YTDLP_URL, YTDLP_PATH, "yt-dlp",
                  expected_sha256=sha,
                  mirrors=_githubMirrors(YTDLP_URL))
        return YTDLP_PATH


def ensure_ffmpeg():
    """返回 (ffmpeg, ffprobe) 路径；优先 tools 目录，其次系统 PATH，最后自动下载。"""
    if (os.path.isfile(FFMPEG_PATH) and os.path.getsize(FFMPEG_PATH) >= _MIN_FFMPEG_SIZE
            and os.path.isfile(FFPROBE_PATH) and os.path.getsize(FFPROBE_PATH) >= _MIN_FFMPEG_SIZE):
        return FFMPEG_PATH, FFPROBE_PATH
    with _BOOTSTRAP_LOCK:
        if (os.path.isfile(FFMPEG_PATH) and os.path.getsize(FFMPEG_PATH) >= _MIN_FFMPEG_SIZE
                and os.path.isfile(FFPROBE_PATH) and os.path.getsize(FFPROBE_PATH) >= _MIN_FFMPEG_SIZE):
            return FFMPEG_PATH, FFPROBE_PATH
        sys_ff = shutil.which("ffmpeg")
        sys_fp = shutil.which("ffprobe")
        if sys_ff and sys_fp:
            return sys_ff, sys_fp
        os.makedirs(TOOLS_DIR, exist_ok=True)
        zip_path = os.path.join(TOOLS_DIR, "ffmpeg.zip")
        try:
            _download(FFMPEG_ZIP_URL, zip_path, "ffmpeg（约 170MB，仅首次）",
                      mirrors=_githubMirrors(FFMPEG_ZIP_URL))
            with zipfile.ZipFile(zip_path) as z:
                bad = z.testzip()
                if bad:
                    raise RuntimeError("ffmpeg zip 损坏: %s" % bad)
                found = {"ffmpeg.exe": False, "ffprobe.exe": False}
                for name in z.namelist():
                    low = name.replace("\\", "/").lower()
                    if low.endswith("/bin/ffmpeg.exe") or low.endswith("/bin/ffprobe.exe"):
                        base = os.path.basename(name)
                        target = FFMPEG_PATH if base.lower() == "ffmpeg.exe" else FFPROBE_PATH
                        tmp = target + ".part"
                        with z.open(name) as src, open(tmp, "wb") as dst:
                            shutil.copyfileobj(src, dst)
                        os.replace(tmp, target)
                        found[base.lower()] = True
            if not all(found.values()):
                raise RuntimeError("ffmpeg zip 缺少 ffmpeg.exe/ffprobe.exe")
        finally:
            try:
                if os.path.isfile(zip_path):
                    os.remove(zip_path)
            except OSError:
                pass
        return FFMPEG_PATH, FFPROBE_PATH


MPV_DLL_URL = ("https://github.com/09Th90/VideoToolbox/releases/download/"
               "deps-mpv-lgpl-20260914/libmpv-2.zip")


def ensure_mpv_dll(mpv_dir):
    """确保 <mpv_dir>\\libmpv-2.dll 就位；缺失时从自有 release 下载解压。

    返回 (True, "") 或 (False, 错误说明)。P2：分段下载 + 镜像候选 + DLL SHA256 校验。
    """
    dll = os.path.join(mpv_dir, "libmpv-2.dll")
    if os.path.isfile(dll) and os.path.getsize(dll) > 10 * 1024 * 1024:
        try:
            if _sha256_file(dll).lower() == _MPV_DLL_SHA256:
                return True, ""
        except OSError:
            pass
    os.makedirs(mpv_dir, exist_ok=True)
    zpath = os.path.join(TOOLS_DIR, "_libmpv.zip")
    try:
        _download(MPV_DLL_URL, zpath, "libmpv 播放组件（约 39MB，仅首次）",
                  mirrors=_githubMirrors(MPV_DLL_URL))
        with zipfile.ZipFile(zpath) as z:
            bad = z.testzip()
            if bad:
                raise RuntimeError("libmpv zip 损坏: %s" % bad)
            name = next(n for n in z.namelist()
                        if n.replace("\\", "/").lower().endswith("libmpv-2.dll"))
            tmp = dll + ".part"
            with z.open(name) as src, open(tmp, "wb") as dst:
                shutil.copyfileobj(src, dst)
        actual = _sha256_file(tmp)
        if actual.lower() != _MPV_DLL_SHA256:
            raise RuntimeError("libmpv SHA256 不一致：%s" % actual)
        os.replace(tmp, dll)
        return True, ""
    except Exception as e:  # noqa: BLE001
        try:
            if os.path.isfile(dll + ".part"):
                os.remove(dll + ".part")
        except OSError:
            pass
        return False, ("下载/解压 libmpv-2.dll 失败：%s\n"
                       "可到发布页手动下载 %s 解压到 %s"
                       % (e, MPV_DLL_URL, mpv_dir))
    finally:
        try:
            if os.path.isfile(zpath):
                os.remove(zpath)
        except OSError:
            pass


__all__ = [
    "ensure_ytdlp",
    "ensure_ffmpeg",
    "ensure_mpv_dll",
    "MPV_DLL_URL",
]
