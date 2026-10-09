# -*- coding: utf-8 -*-
# @version 1.18.2
"""NPE（NewPipe Extractor）后端冒烟测试：解析 → 选流 → ffmpeg 实际下载。

用法：
    python scripts/dev/_selftest_npe.py
    python scripts/dev/_selftest_npe.py <url> [<proxy>]

判定标准：至少有一条视频流能被 ffmpeg 拉下来并产出非空文件。
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, os.path.join(_ROOT, "src"))

import npe_backend as npe  # noqa: E402

DEFAULT_URLS = [
    "https://www.youtube.com/watch?v=jNQXAC9IVRw",
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
]
PROXY = "http://127.0.0.1:7897"
COOKIE_FILE = os.path.join(_ROOT, "data", "guest_cookies.txt")
FFMPEG = os.path.join(_ROOT, "tools", "ffmpeg.exe")


def _dec(b) -> str:
    return npe._decode(b or b"")


def run_one(url: str, proxy: str) -> bool:
    print("\n=== %s ===" % url)
    cookie = COOKIE_FILE if os.path.isfile(COOKIE_FILE) else ""
    info = npe.probe(url, proxy=proxy, cookie_file=cookie)
    if not info.get("ok") and info.get("errorType") not in ("unavailable", "spawn"):
        # 风控偶发：换一次会话再试，仍失败才算失败
        print("首次解析失败（%s），重试一次…" % info.get("errorType"))
        info = npe.probe(url, proxy=proxy, cookie_file=cookie)
    if not info.get("ok"):
        print("解析失败：%s" % npe.error_hint(info))
        return False

    print("标题   : %s" % info.get("title"))
    print("上传者 : %s | 时长 %ss | 类型 %s" %
          (info.get("uploader"), info.get("duration"), info.get("streamType")))
    print("流统计 : videoOnly=%d audioOnly=%d muxed=%d subtitles=%d" %
          (len(info.get("videoOnly") or []), len(info.get("audioOnly") or []),
           len(info.get("muxed") or []), len(info.get("subtitles") or [])))

    # 测试只下 720p，别真去拉 4K
    v, a = npe.pick_streams(info, max_height=720)
    if not v:
        print("无可用流")
        return False
    print("选中   : video=%s %s | audio=%s" %
          (v.get("resolution") or v.get("quality"), v.get("codec"),
           (a.get("bitrate") if a else "(无，muxed 单流)")))

    if not os.path.isfile(FFMPEG):
        print("缺少 %s，跳过下载" % FFMPEG)
        return False

    def _ext(s: dict) -> str:
        e = (s.get("suffix") or "").strip().lstrip(".")
        return "." + (e or "mp4")

    base = os.path.join(tempfile.gettempdir(), "npe_selftest_%s" % info.get("id"))
    out = base + ".mp4"
    v_path = base + "_v" + _ext(v)
    a_path = base + "_a" + (_ext(a) if a else ".m4a")
    for p in (out, v_path, a_path):
        if os.path.isfile(p):
            os.remove(p)

    def _run(cmd: list, what: str) -> bool:
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=240)
        except subprocess.TimeoutExpired:
            print("%s 超时" % what)
            return False
        if r.returncode == 0:
            return True
        print("%s 失败（%s）" % (what, _dec(r.stderr).strip()[:200]))
        return False

    ref = "https://www.youtube.com/"
    if not _run(npe.build_stream_cmd(v, v_path, FFMPEG, referer=ref, proxy=proxy),
                "视频流下载"):
        return False
    vs = os.path.getsize(v_path) if os.path.isfile(v_path) else 0
    print("视频流 : OK，%d 字节" % vs)

    if a:
        if not _run(npe.build_stream_cmd(a, a_path, FFMPEG, referer=ref, proxy=proxy),
                    "音频流下载"):
            return False
        print("音频流 : OK，%d 字节" % (os.path.getsize(a_path)
                                        if os.path.isfile(a_path) else 0))
        if not _run(npe.build_mux_cmd(v_path, a_path, out, FFMPEG), "合流"):
            return False
    else:
        os.replace(v_path, out)

    size = os.path.getsize(out) if os.path.isfile(out) else 0
    if size > 0:
        print("下载   : OK，%d 字节 → %s" % (size, out))
        return True
    print("下载   : 失败（输出为空）")
    return False


def main() -> int:
    args = sys.argv[1:]
    urls = [args[0]] if args else DEFAULT_URLS
    proxy = args[1] if len(args) > 1 else PROXY

    ok, why = npe.is_available()
    print("java   : %s" % (why if ok else "不可用 —— " + why))
    if not ok:
        return 1
    print("jar    : %s" % npe.JAR_PATH)

    passed = 0
    for u in urls:
        try:
            if run_one(u, proxy):
                passed += 1
        except Exception as e:  # noqa: BLE001
            print("异常：%s" % e)
    print("\n结果：%d/%d 通过" % (passed, len(urls)))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
