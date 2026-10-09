# -*- coding: utf-8 -*-
# @version 1.18.3
"""NewPipe Extractor 后端 —— 视频工具箱的 YouTube 第二解析引擎。

为什么要这个模块
----------------
yt-dlp 是目前的主引擎，但它是单点依赖：一旦上游被 YouTube 的接口变更打挂，
整条下载链路就瘫痪。本模块把 NewPipe Extractor（Java/Kotlin，GPL-3.0，
TeamNewPipe 维护）接成**第二个独立解析引擎**。

调度策略（用户 2026-10-07 选定）：**两者都试，取先成功**。

职责边界
--------
本模块只做「解析出流地址」与「拼装 ffmpeg 下载命令」，不负责真正拉流下载——
下载仍走 ffmpeg，从而与现有链路的代理、进度回调、输出命名保持一致。

典型用法
--------
    from npe_backend import probe, race_engines
    info = probe(url, proxy="http://127.0.0.1:7897", cookie_file="data/guest_cookies.txt")
    name, info = race_engines(url, proxy=proxy, cookie_file=cf)
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JAR_PATH = os.path.join(APP_DIR, "tools", "newpipe-cli", "dist", "npe-cli.jar")

#: 便携 JRE 位置（未来随安装包分发时放这里；现在没有则回落到系统 java）
PORTABLE_JRE = os.path.join(APP_DIR, "tools", "jre", "bin", "java.exe")

#: 桌面 UA：与 Java 侧 NpeDownloader.DEFAULT_UA 保持一致，ffmpeg 拉流要用
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

#: 常见 JDK 安装位置（找不到 java 时的兜底扫描）
#: ⚠️ 不要写死任何具体用户名的路径——本文件要随安装包分发给所有用户，
#:    别人机器上不存在该目录，扫描纯属浪费 IO（真正找不到就回落到 PATH）。
#: 需要指向非标准位置时用环境变量 VT_JAVA 覆盖。
_JDK_HINTS = [
    r"C:\Program Files\Java",
    r"C:\Program Files\Eclipse Adoptium",
    r"C:\Program Files\BellSoft",
    r"C:\Program Files\Microsoft\jdk",
    r"C:\Program Files\Zulu",
]


def _decode(b) -> str:
    for enc in ("utf-8", "gbk", "cp936", "latin-1"):
        try:
            return b.decode(enc)
        except Exception:  # noqa: BLE001
            continue
    return b.decode("utf-8", "replace")


def find_java() -> str:
    """定位可用的 java 可执行文件；找不到返回空串。

    优先级：环境变量 VT_JAVA → 便携 JRE → PATH → 已知 JDK 目录扫描。
    """
    env = os.environ.get("VT_JAVA", "").strip().strip('"')
    if env:
        if os.path.isdir(env):
            for rel in (("bin", "java.exe"), ("bin", "java")):
                p = os.path.join(env, *rel)
                if os.path.isfile(p):
                    return p
        elif os.path.isfile(env):
            return env

    if os.path.isfile(PORTABLE_JRE):
        return PORTABLE_JRE

    w = shutil.which("java") or shutil.which("java.exe")
    if w:
        return w

    for base in _JDK_HINTS:
        if not os.path.isdir(base):
            continue
        try:
            names = sorted(os.listdir(base), reverse=True)
        except Exception:  # noqa: BLE001
            continue
        for n in names:
            for rel in (("bin", "java.exe"), ("bin", "java")):
                p = os.path.join(base, n, *rel)
                if os.path.isfile(p):
                    return p
    return ""


def is_available() -> tuple:
    """返回 (是否可用, 说明)。"""
    java = find_java()
    if not java:
        return False, "未找到 java（设置 VT_JAVA 或安装 JDK 17+，或将便携 JRE 放到 tools/jre）"
    if not os.path.isfile(JAR_PATH):
        return False, "缺少 %s，请先运行 tools/newpipe-cli/build.py" % JAR_PATH
    return True, java


def probe(url: str, proxy: str = "", cookie: str = "", cookie_file: str = "",
          timeout: int = 45, retries: int = 1) -> dict:
    """解析一条视频，返回 info 字典；**失败也返回 dict**（ok=False + errorType）。

    errorType 取值：captcha / unavailable / extract / network / error / spawn。
    只有「CLI 根本没跑起来」才返回 ok=False 且 errorType=spawn。

    ⚠️ 默认重试 1 次：YouTube 的风控是**按 IP 且偶发**的（实测同一视频连跑
    可能一次成功一次 LOGIN_REQUIRED），兜底路径若不带重试，一次风控就白兜了。
    只有「内容不可用」「启动失败」这两种确定性失败不重试。
    """
    info = {}
    for attempt in range(max(0, retries) + 1):
        info = _probe_once(url, proxy=proxy, cookie=cookie,
                           cookie_file=cookie_file, timeout=timeout)
        if info.get("ok") or info.get("errorType") in ("unavailable", "spawn"):
            return info
        if attempt < retries:
            time.sleep(2.0)
    return info


def _probe_once(url: str, proxy: str = "", cookie: str = "", cookie_file: str = "",
                timeout: int = 45) -> dict:
    ok, why = is_available()
    if not ok:
        return {"ok": False, "errorType": "spawn", "error": why}

    cmd = [why, "-jar", JAR_PATH, "--url", url, "--timeout", str(timeout)]
    if proxy:
        cmd += ["--proxy", proxy.replace("http://", "").replace("https://", "")]
    if cookie:
        cmd += ["--cookie", cookie]
    if cookie_file and os.path.isfile(cookie_file):
        cmd += ["--cookie-file", cookie_file]

    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout + 25)
    except subprocess.TimeoutExpired:
        return {"ok": False, "errorType": "network", "error": "NPE 解析超时"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "errorType": "spawn", "error": str(e)}

    out = _decode(r.stdout or b"")
    for line in reversed(out.splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                info = json.loads(line)
            except Exception:  # noqa: BLE001
                break
            info.setdefault("ok", False)
            info["engine"] = "npe"
            return info
    return {"ok": False, "errorType": "spawn",
            "error": (_decode(r.stderr or b"").strip() or "NPE 未输出 JSON")[:400]}


def ytdlp_probe(url: str, proxy: str = "", cookie_file: str = "",
                timeout: int = 60) -> dict:
    """用 yt-dlp 做同样的「只解析不下载」，返回与 :func:`probe` 同构的 dict。

    之所以自己实现一份而不是复用引擎里的函数：避免与 video_toolbox 反向导入
    形成循环依赖，也让两个引擎的探测结果有统一形状可供比较。
    """
    exe = os.path.join(APP_DIR, "tools", "yt-dlp.exe")
    if not os.path.isfile(exe):
        exe = shutil.which("yt-dlp") or ""
    if not exe:
        return {"ok": False, "errorType": "spawn", "error": "未找到 yt-dlp"}

    cmd = [exe, "--dump-single-json", "--simulate", "--no-warnings", url]
    if proxy:
        cmd += ["--proxy", proxy]
    if cookie_file and os.path.isfile(cookie_file):
        cmd += ["--cookies", cookie_file]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "errorType": "network", "error": "yt-dlp 解析超时"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "errorType": "spawn", "error": str(e)}

    out = _decode(r.stdout or b"")
    for line in reversed(out.splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                raw = json.loads(line)
            except Exception:  # noqa: BLE001
                break
            return {"ok": True, "engine": "yt-dlp", "title": raw.get("title", ""),
                    "duration": raw.get("duration") or 0, "raw": raw}
    err = _decode(r.stderr or b"").strip()
    low = err.lower()
    et = "extract"
    if "not a bot" in low or "sign in to confirm" in low:
        et = "captcha"
    elif "unavailable" in low or "private" in low:
        et = "unavailable"
    elif "timed out" in low or "connection" in low:
        et = "network"
    return {"ok": False, "errorType": et, "error": err[:400], "engine": "yt-dlp"}


def race_engines(url: str, proxy: str = "", cookie_file: str = "",
                 timeout: int = 45) -> tuple:
    """两个引擎并行探测，**返回先成功者**：(引擎名, info) 或 (None, None)。

    注意：这会产生双倍请求，风控环境下更容易被标记——属于成功率与隐蔽性的取舍，
    由用户在 2026-10-07 明确选定。
    """
    ok, why = is_available()
    tasks = [("yt-dlp", lambda: ytdlp_probe(url, proxy=proxy, cookie_file=cookie_file))]
    if ok:
        tasks.append(("npe", lambda: probe(url, proxy=proxy,
                                           cookie_file=cookie_file, timeout=timeout)))

    with ThreadPoolExecutor(max_workers=len(tasks)) as ex:
        futs = {ex.submit(fn): name for name, fn in tasks}
        pending = set(futs)
        while pending:
            done, pending = wait(pending, return_when=FIRST_COMPLETED)
            for f in done:
                name = futs[f]
                try:
                    info = f.result()
                except Exception:  # noqa: BLE001
                    info = None
                if info and info.get("ok"):
                    return name, info
        return None, None


def pick_streams(info: dict, max_height: int = 0) -> tuple:
    """从 NPE 解析结果里挑一组可合流的 (video, audio)。

    优先 DASH 分离流（画质更好），没有则退回 muxed（progressive）单流。
    返回 (video_dict|None, audio_dict|None)；两者都 None 表示没有可用流。
    """
    if not info or not info.get("ok"):
        return None, None

    videos = [s for s in (info.get("videoOnly") or []) if s.get("url")]
    audios = [s for s in (info.get("audioOnly") or []) if s.get("url")]
    muxed = [s for s in (info.get("muxed") or []) if s.get("url")]

    if max_height:
        videos = [v for v in videos if (v.get("height") or 0) <= max_height] or videos
        muxed = [m for m in muxed if (m.get("height") or 0) <= max_height] or muxed

    if videos and audios:
        v = max(videos, key=lambda s: (s.get("height") or 0, s.get("bitrate") or 0))
        a = max(audios, key=lambda s: s.get("bitrate") or 0)
        return v, a
    if muxed:
        m = max(muxed, key=lambda s: (s.get("height") or 0, s.get("bitrate") or 0))
        return m, None
    if videos:
        return max(videos, key=lambda s: s.get("height") or 0), None
    return None, None


def build_ffmpeg_cmd(video: dict, audio: dict, out_path: str, ffmpeg: str,
                     referer: str = "", proxy: str = "") -> list:
    """拼装 ffmpeg 合流命令（只拼命令，不执行）。

    ⚠️ `proxy` 在国内几乎是**必填**：NPE 给出的是 googlevideo.com 直链，
    而该域名境内不可达；ffmpeg 默认不跟系统代理，不显式给 `-http_proxy`
    就会直连并收到 5XX / 连接重置。
    """
    cmd = [ffmpeg, "-y", "-loglevel", "error",
           "-user_agent", USER_AGENT]
    if referer:
        cmd += ["-referer", referer]
    if proxy:
        cmd += ["-http_proxy", proxy]
    cmd += ["-i", video["url"]]
    if audio:
        cmd += ["-i", audio["url"]]
    cmd += ["-c", "copy", "-movflags", "+faststart", out_path]
    return cmd


def build_stream_cmd(stream: dict, out_path: str, ffmpeg: str,
                     referer: str = "", proxy: str = "") -> list:
    """单条流的下载命令。

    ⚠️ 为什么要单独下再合流，而不是让 ffmpeg 一次性 `-i video -i audio`：
    实测（2026-10-07）ffmpeg 同时对 googlevideo.com 开两条连接会触发限流，
    第二条输入直接 5XX；拆成两次串行请求则稳定成功。
    """
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-user_agent", USER_AGENT]
    if referer:
        cmd += ["-referer", referer]
    if proxy:
        cmd += ["-http_proxy", proxy]
    cmd += ["-i", stream["url"], "-c", "copy",
            "-movflags", "+faststart", out_path]
    return cmd


def build_mux_cmd(video_file: str, audio_file: str, out_path: str,
                  ffmpeg: str) -> list:
    """本地两个文件合流（此时已无网络，不会触发限流）。"""
    return [ffmpeg, "-y", "-loglevel", "error",
            "-i", video_file, "-i", audio_file,
            "-c", "copy", "-movflags", "+faststart", out_path]


def _default_sanitize(name: str) -> str:
    """文件名净化的兜底实现（调用方通常传引擎里的 sanitize_folder_name）。"""
    bad = '<>:"/\\|?*'
    out = "".join("_" if c in bad else c for c in str(name or "")).strip(" .")
    return out[:120] or "video"


def _run_ffmpeg(cmd: list, duration: float = 0.0, progress=None) -> bool:
    """执行 ffmpeg 并解析 `-progress` 输出回传百分比；返回是否成功。"""
    cmd = list(cmd)
    try:
        pos = cmd.index("-i")
    except ValueError:
        pos = 1
    cmd[pos:pos] = ["-progress", "pipe:1", "-nostats"]
    try:
        # 注意：二进制模式下 bufsize=1 不被支持（会 RuntimeWarning），
        # 按行迭代靠 BufferedReader 即可，不要传 bufsize。
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT)
    except Exception:  # noqa: BLE001
        return False
    for raw in proc.stdout:
        line = _decode(raw).strip()
        if duration > 0 and line.startswith("out_time_us=") and progress:
            try:
                us = int(line.split("=", 1)[1])
            except ValueError:
                continue
            progress(min(99.5, us / 1_000_000.0 / duration * 100.0))
        elif line.startswith("progress=end") and progress:
            progress(100.0)
    return proc.wait() == 0


def download(info: dict, folder: str, ffmpeg: str, proxy: str = "",
             referer: str = "", max_height: int = 0, log=None, progress=None,
             sanitize=None, title_fallback: str = "video") -> tuple:
    """按 NPE 解析结果下载并合流，返回 ``(ok, out_path, error)``。

    ⚠️ 关键策略：**先分别下载视频流与音频流，再本地合流**。实测 ffmpeg 同时对
    googlevideo 开两条连接会触发限流（第二条直接 5XX），串行则稳定。

    - ``log(msg, level)`` / ``progress(pct)``：可选回调，供 GUI 回传。
    - ``sanitize``：文件名净化函数（缺省用内置简单实现）。
    - 失败时清理所有临时分片，不留残骸。
    """
    def _log(m, lv="dim"):
        if log:
            try:
                log(m, lv)
            except Exception:  # noqa: BLE001
                pass

    video, audio = pick_streams(info, max_height=max_height)
    if not video:
        return False, "", "未取到可用视频流"

    title = str(info.get("title") or title_fallback or "video")
    base = (sanitize(title) if sanitize else _default_sanitize(title))
    out_path = os.path.join(folder, base + ".mp4")
    v_tmp = os.path.join(folder, base + ".npe_v" + _stream_ext(video))
    a_tmp = os.path.join(folder, base + ".npe_a" + _stream_ext(audio)) if audio else ""
    duration = float(info.get("duration") or 0)
    made = []

    try:
        if progress:
            progress(0.0)
        if not _run_ffmpeg(build_stream_cmd(video, v_tmp, ffmpeg,
                                            referer=referer, proxy=proxy),
                           duration, progress):
            return False, "", "视频流下载失败"
        made.append(v_tmp)

        if audio:
            if not _run_ffmpeg(build_stream_cmd(audio, a_tmp, ffmpeg,
                                                referer=referer, proxy=proxy),
                               duration, progress):
                return False, "", "音频流下载失败"
            made.append(a_tmp)
            _log("[NPE] 音视频合流 ...")
            if not _run_ffmpeg(build_mux_cmd(v_tmp, a_tmp, out_path, ffmpeg)):
                return False, "", "合流失败"
        else:
            os.replace(v_tmp, out_path)
            made.remove(v_tmp)

        if not (os.path.isfile(out_path) and os.path.getsize(out_path) > 0):
            return False, "", "产物为空"
        return True, out_path, ""
    finally:
        for p in made:
            try:
                if p != out_path and os.path.isfile(p):
                    os.remove(p)
            except OSError:
                pass


def _stream_ext(stream: dict) -> str:
    """流的容器扩展名。

    ⚠️ 必须给 ffmpeg 标准扩展名，否则它无法推断输出容器，直接报
    "Unable to choose an output format"。
    """
    e = str((stream or {}).get("suffix") or "").strip().lstrip(".")
    return "." + (e or "mp4")


def error_hint(info: dict) -> str:
    """把 NPE 的 errorType 翻成给用户看的一句话。"""
    if not info:
        return "解析未返回结果"
    if info.get("ok"):
        return ""
    t = info.get("errorType", "")
    return {
        "captcha": "被 YouTube 判定为机器人（需要登录态 cookie，或换出口节点）",
        "unavailable": "视频不可用：已下架 / 地区限制 / 会员专享",
        "extract": "解析失败（接口可能已变更，需升级 NewPipe Extractor 版本）",
        "network": "网络失败（代理未就绪或超时）",
        "spawn": "NPE 未能启动（缺 java 或 jar）：" + info.get("error", ""),
    }.get(t, info.get("error", "未知错误"))


if __name__ == "__main__":
    import sys

    url = sys.argv[1] if len(sys.argv) > 1 else ""
    if not url:
        print("用法: python npe_backend.py <url> [proxy] [cookie_file]")
        raise SystemExit(1)
    px = sys.argv[2] if len(sys.argv) > 2 else ""
    cf = sys.argv[3] if len(sys.argv) > 3 else ""
    print("java:", find_java())
    info = probe(url, proxy=px, cookie_file=cf)
    print(json.dumps(info, ensure_ascii=False, indent=2)[:2000])
    if not info.get("ok"):
        print("提示:", error_hint(info))
