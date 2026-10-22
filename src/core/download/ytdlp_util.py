# -*- coding: utf-8 -*-
# @version 2.5.4
"""yt-dlp 参数与信息探测（画质/字幕/格式）、下载模式判定、输出模板（v2.3.1 拆分工程 · 自 video_toolbox.py 原样搬入）。

core/download 域：yt-dlp 全链 / cookie / NPE / 媒体合并；依赖规则见 core/__init__.py。
"""

import json
import os
import re
import subprocess
import tempfile
import time

from core.download.cookies import (cookie_load_failure_reason,
                                   invalidate_cookie_cache, ytdlp_cookie_args)
from core.download.deps import ensure_ffmpeg, ensure_ytdlp
from core.download.npe import npe_available, npe_engine_mode, npe_proxy_url
from core.download.util import (format_size, make_cover_1280x720, open_folder,
                                sanitize_folder_name, unique_folder,
                                write_info_txt)
from core.shared.config import get_saved_download_dir, set_saved_download_dir
from core.shared.paths import DATA_DIR, clean_path
from core.shared.proc import kill_process_tree, popen_process, sleep_cancellable
from core.shared.proxy import ytdlp_proxy_args
from core.shared.textio import decode_bytes_any, write_text_utf8

YTDLP_CHUNK_SIZE = "5M"

#: HLS/DASH 分片并发数（yt-dlp `-N`，默认 1 = 串行）。分片源提速**最有效**的
#: 一项：实测 226 片的 HLS 串行下载慢到不可用，并发后是数倍差距。
#: 别调太高——请求都经本地代理出去，并发过高会加剧代理断连（实测过）。
#: DOWNLOAD.md 另记：NPE 侧实测「同 IP 对 googlevideo 开 2 条连接即触发限流」，
#: 所以默认 5 是稳定性优先的折中，需要提速时用 VT_YTDLP_FRAGMENTS 自行调整。
YTDLP_CONCURRENT_FRAGMENTS = "5"


def ytdlp_concurrent_fragments():
    """分片并发数（可用 ``VT_YTDLP_FRAGMENTS`` 覆盖，取值 1~16）。

    为什么允许覆盖：2026-10-17 完整监控显示 5 并发下 IEPL 节点只有 1.34 MB/s
    均速，但 CDN 对单 IP 并发敏感（并发过高会触发限流/断连），不存在一个对
    所有节点都最优的值。固定值必然有一部分用户吃亏，故开放环境变量自行试探。
    非法值（非数字/越界）静默回落到默认，不抛异常。
    """
    v = (os.environ.get("VT_YTDLP_FRAGMENTS") or "").strip()
    if v.isdigit():
        n = int(v)
        if 1 <= n <= 16:
            return str(n)
    return YTDLP_CONCURRENT_FRAGMENTS


def ytdlp_dl_args():
    """yt-dlp 下载通用参数表（提速 + 抗断流）。下载页与流水线共用同一份。

    与 ``YTDLP_DL_COMMON_ARGS`` 常量的区别：本函数每次调用都重新生成，
    以便 ``VT_YTDLP_FRAGMENTS`` 之类环境变量在进程内改动后立即生效
    常量在 import 时定死，改环境变量要重启进程才认）。
      · ``--socket-timeout``：代理断连时快速失败。此前没设，实测一次
        ``Unable to connect to proxy`` 让任务**干等了 9 分钟**才报错；
      · ``--retries/--fragment-retries``：网络抖动重试（分片级重试只重下那一片，
        不像整文件重来）；
      · ``--retry-sleep exp=1:20``：指数退避（1→20s），避免连续撞风控。
        ⚠ 对 EOF（链接作废）属负资产——直链场景 GUI 会主动结束进程走重新提取，
        不依赖这里的退避；分片场景退避有价值，故保留。
      · ``--concurrent-fragments``：见 ``ytdlp_concurrent_fragments()``。
    """
    return [
        "--socket-timeout", "20",
        "--retries", "10",
        "--fragment-retries", "10",
        "--retry-sleep", "exp=1:20",
        "--concurrent-fragments", ytdlp_concurrent_fragments(),
    ]


def ytdlp_prefer_hls():
    """YouTube 是否**优先**走 HLS 分片源（默认开）。

    直链（videoplayback）在 2026-09 后单条服务能力有限（约 5 次请求 / 数十 MB
    即失效 → 403），大文件几乎必然失败；实测直链要先白等十几分钟才切到 HLS。
    HLS 每片独立取、可并发，稳定性与速度都更好，所以**直接首选 HLS**，把直链
    降级为兜底。设 ``VT_YTDLP_PREFER_HLS=0`` 可退回旧的"直链优先"行为。
    """
    v = (os.environ.get("VT_YTDLP_PREFER_HLS") or "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def ytdlp_part_leftovers(folder):
    """任务目录里的 yt-dlp 分片/临时残留（*.part、*.ytdl）。

    正常完成的下载不会有这些文件：HLS 每片完成即拼入主临时文件并自删，
    全部完成后 .part 改名为成品。出现残留 = yt-dlp 重试耗尽后**跳过了
    不可用分片**（--skip-unavailable-fragments 默认开、返回码仍为 0）——
    成品可能缺对应分片的几秒内容，调用方应告警用户并清掉残骸。
    """
    out = []
    try:
        for fn in os.listdir(folder):
            if fn.lower().endswith((".part", ".ytdl")):
                out.append(os.path.join(folder, fn))
    except OSError:
        pass
    return out

#: yt-dlp 可重试错误关键词（风控 / 网络抖动）。**下载页、流水线、信息提取三处
#: 共用同一份判定** —— 此前各写各的，流水线只认 412，遇到 403/429 直接放弃，
#: 而 YouTube 直链失效正好回 403（"下载失败但手动重试又能成"的由来）。
YTDLP_RETRY_HINTS = (
    "412", "429", "403", "500", "502", "503", "504",
    "timed out", "timeout", "Read timed out", "Incomplete",
    "Unable to download webpage", "Unable to extract",
    "Sign in to confirm", "bot check", "bot detection", "throttl",
    "network", "Connection", "connection", "socket",
    "Temporary failure", "EOF", "reset", "Remote end closed",
    "Name or service not known", "SSL", "TLS", "giving up",
)

#: 「重试同一条 URL 没有意义」的错误特征——必须**重新提取**才是有效动作。
#: videoplayback 直链在签发时把当时的出口 IP 写进了 URL（`ip=` 参数），
#: 代理一换节点，CDN 就按旧 IP 校验并直接掐断 TLS：表现就是
#: `Got error: EOF occurred in violation of protocol (_ssl.c:1007). Retrying`
#: ——重试用的还是那条死链，退避 6→12→24s 纯属白耗，用户看到"一直 Retrying"。
YTDLP_REEXTRACT_HINTS = (
    "eof occurred in violation of protocol",   # 本次要解决的主角
    "_ssl.c",                                   # 上面那行的 Python 出处
    "remote end closed",
    "connection closed without response",
    "http error 403",                           # CDN 按旧 IP 校验不通过
    "fragment not found",                       # HLS 分片 URL 同因失效
    "unable to download video data",
)


def ytdlp_error_retryable(text):
    """yt-dlp 输出是否属「可重试」的临时失败（风控 / 网络抖动）。

    非临时错误（参数写错、视频私享/不存在、地区限制等）返回 False，
    避免无意义的退避等待。
    """
    low = str(text or "").lower()
    return any(k.lower() in low for k in YTDLP_RETRY_HINTS)


def ytdlp_err_brief(text, limit=120):
    """从 yt-dlp 输出里挑一行最能说明问题的（ERROR 优先），用于日志/报错。"""
    lines = [ln.strip() for ln in str(text or "").splitlines() if ln.strip()]
    for ln in reversed(lines):
        if "ERROR" in ln or "error" in ln:
            return ln[:limit]
    return lines[-1][:limit] if lines else "未知错误"


def ytdlp_error_needs_reextract(text):
    """yt-dlp 输出是否属于「链接本身已失效、必须重新提取」的失败。

    与 ``ytdlp_error_retryable`` 的分工：后者判「是不是临时故障、值不值得
    原地再试一次」；本函数判「再试同一条 URL 是不是纯属浪费」。
    EOF / TLS 断连在 YouTube 上几乎都是出口 IP 变了——直链绑定了签发时的
    IP，CDN 直接掐连接（403 同理）。这类失败唯一有效的动作是**重新提取**，
    拿到绑定新 IP 的新链接；原地重试只会白耗退避时间。

    注意容错：判据全部小写化后比较，且不依赖 "giving up" 这类位于输出末尾、
    可能因缓冲问题缺失的行——只要出现核心特征就判定成立。
    """
    low = str(text or "").lower()
    if not low:
        return False
    if not any(k in low for k in YTDLP_REEXTRACT_HINTS):
        return False
    # 二次确认：output 里的 Retrying 计数行本身不构成证据（它只是转述错误），
    # 必须有真正的 ERROR/WARNING 行佐证，否则空文本误判。
    return "error" in low or "warning" in low


def fetch_info_json(ytdlp, url, attempts=4, log=None, wait_base=5,
                    cancel=None, register=None):
    """运行 yt-dlp -J 获取视频信息原始 JSON。

    部分站点（如 B 站）对无 cookie 的连续请求有风控，随机返回 HTTP 412；
    YouTube 等站点在无 JS 运行时 / 网络抖动 / 风控时也会间歇失败（403/429/
    "Sign in to confirm" / 连接被重置等）。这里把网络类与风控类错误都纳入
    自动重试，并把每一次的具体失败原因透出给 log，方便定位问题。
    log 为可选回调，用于向 GUI / 命令行透出重试进度与错误详情。

    v1.19.1：`cancel`（threading.Event）+ `register`（登记当前子进程的回调）。
    原先用 `subprocess.run` 跑到结束，**提取阶段完全无法中止**——用户点取消
    后这里还要白等最多 180s×4 次 + 退避；而 GUI 的杀进程逻辑也拿不到这个
    子进程（没登记），于是「取消」对正在提取/换源重试的任务彻底无效。
    """
    def _log(msg):
        if log:
            try:
                log(msg)
            except Exception:
                pass

    def _cancelled():
        return cancel is not None and cancel.is_set()

    def _unregister():
        if register:
            try:
                register(None)
            except Exception:  # noqa: BLE001
                pass

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
    # 游客 cookie 反风控（v1.15.8）：YouTube 对无 cookie 请求间歇性弹
    # "Sign in to confirm"，自动索取的站方游客 cookie 实测能压低触发率
    cookie_args = ytdlp_cookie_args(log=_log)
    #: 浏览器 cookie 库被锁（yt-dlp #7271）时自救一次：失效缓存 → 换来源 →
    #: 立刻重试。只做一次，避免「所有来源都读不出」时反复空转。
    cookie_rescued = False
    for i in range(attempts):
        if _cancelled():
            _unregister()
            return None
        proc = None
        out_f = err_f = None
        try:
            # v1.16.5 修复：此前无 timeout——yt-dlp 在网络挂起（半开连接 /
            # 站点不响应）时会无限期干等，GUI 表现即「提取画质」永远转圈。
            # 180s 覆盖慢速站点首包 + 站点侧风控延迟的实测上限。
            # v1.19.1：改 Popen + 轮询，取消标志一置位立刻杀整棵进程树。
            # ⚠ v2.3.2 修复 PIPE 死锁：原先 stdout/stderr 用 subprocess.PIPE，
            # 而下面的轮询循环只 poll() 不读管道 —— `-J` 对长视频输出的 JSON
            # （实测 7.6h 直播录像达 660KB）写满 Windows 管道缓冲后，yt-dlp
            # 阻塞在 write 永不退出 → 每次必然 180s 超时（把 stdout 重定向到
            # 文件则同一命令 24s 成功，即此因）。改写到临时文件、结束再读。
            out_f = tempfile.TemporaryFile()
            err_f = tempfile.TemporaryFile()
            proc = popen_process([ytdlp, "-J", "--no-playlist", *cookie_args,
                                  url, *proxy_args],
                                 stdout=out_f, stderr=err_f)
        except Exception:  # noqa: BLE001
            for _f in (out_f, err_f):
                if _f is not None:
                    try:
                        _f.close()
                    except Exception:  # noqa: BLE001
                        pass
            _unregister()
            raise
        if register:
            try:
                register(proc)
            except Exception:  # noqa: BLE001
                pass
        deadline = time.time() + 180
        out_b = err_b = b""
        timed_out = False
        cancelled = False
        try:
            while True:
                if _cancelled():
                    cancelled = True
                    kill_process_tree(proc)
                    break
                if proc.poll() is not None:
                    break
                if time.time() > deadline:
                    timed_out = True
                    kill_process_tree(proc)
                    break
                time.sleep(0.15)
            try:
                out_f.seek(0)
                out_b = out_f.read()
                err_f.seek(0)
                err_b = err_f.read()
            except Exception:  # noqa: BLE001
                out_b, err_b = b"", b""
        finally:
            for _f in (out_f, err_f):
                try:
                    _f.close()
                except Exception:  # noqa: BLE001
                    pass
            _unregister()
        if cancelled:
            return None
        if timed_out:
            _log(f"[信息] 提取超时（180s，{i + 1}/{attempts}）")
            if i == attempts - 1:
                _log("[错误] 画质提取超时")
                return None
            wait = wait_base * (i + 1)
            _log(f"[信息] {wait}s 后自动重试 ...")
            if sleep_cancellable(wait, cancel):
                return None
            continue
        out = decode_bytes_any(out_b)
        if proc.returncode == 0 and out.strip().startswith("{"):
            return out
        err = decode_bytes_any(err_b) + out
        detail = _detail(err)
        # cookie 读不出来跟风控 / 网络无关：退避重试同一套参数永远失败。
        # 这里就地失效缓存、重新解析 cookie 来源，然后**立刻**重试（不吃退避）。
        if not cookie_rescued:
            why = cookie_load_failure_reason(err)
            if why:
                cookie_rescued = True
                _log(f"[警告] cookie 读取失败：{why}")
                _log("[信息] 已自动重新选择 cookie 来源，立即重试 ...")
                invalidate_cookie_cache()
                cookie_args = ytdlp_cookie_args(refresh=True, log=_log)
                continue
        if i < attempts - 1:
            _log(f"[信息] 提取失败（{i + 1}/{attempts}）: {detail}")
        retryable = ytdlp_error_retryable(err)
        if not retryable or i == attempts - 1:
            _log(f"[错误] 画质提取失败: {detail}")
            return None
        wait = wait_base * (i + 1)
        _log(f"[信息] {wait}s 后自动重试 ...")
        if sleep_cancellable(wait, cancel):
            return None
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


def output_template(folder, filename_tpl="%(title)s.%(ext)s"):
    """构造 yt-dlp 的 -o 输出模板。

    yt-dlp 会把 -o 里的 % 当模板变量解析，因此保存路径中若含 %
    （例如 D:\\100%素材\\某视频）会导致下载直接报错。这里把路径部分的
    % 转义为 %%，模板占位符保持原样。
    """
    safe_folder = str(folder).replace("%", "%%")
    return os.path.join(safe_folder, filename_tpl)


def hls_alt_format(meta, fid):
    """给定 itag，找出「同画质、同编码家族」的 m3u8 分片源 itag。

    2026-09 起 YouTube 的 videoplayback 直链有两条新限制：
      1. 不带 Range 请求的一律 HTTP 403（yt-dlp 默认整体 GET 正好踩中）；
      2. 单条直链服务能力有限（实测约 5 次请求 / 数十 MB 后失效），
         大文件几乎不可能一次下完。
    HLS(m3u8) 分片源每片独立取、每片天然是分段请求，实测 1080p 也能稳定下完，
    所以要能在直链失败时改走 HLS。这里负责挑出对应的 HLS itag。

    找不到（该画质没有 HLS 源，或 meta 不是 YouTube 的）返回 None，
    调用方应保持原行为，不要因为这个函数出问题而中断下载。
    """
    try:
        fmts = (meta or {}).get("formats") or []
        cur = next((f for f in fmts if str(f.get("format_id")) == str(fid)), None)
        if not cur:
            return None
        height = cur.get("height")
        if not height:
            return None
        codec = (cur.get("vcodec") or "").split(".")[0]
        cands = [f for f in fmts
                 if f.get("height") == height
                 and "m3u8" in str(f.get("protocol") or "")
                 and (f.get("vcodec") or "none") != "none"]
        if not cands:
            return None
        same = [f for f in cands
                if (f.get("vcodec") or "").split(".")[0] == codec]
        pick = (same or cands)[0]
        return str(pick.get("format_id")) if pick.get("format_id") else None
    except Exception:  # noqa: BLE001
        return None


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

    # v1.16.5 修复：此前 base_cmd 未带代理与 cookie——命令行模式（download_mode）
    # 下 YouTube 直连必失败，而同文件的 fetch_info_json 与 GUI / 流水线路径都带。
    # 与提取信息同口径，补上「本地代理 + 游客 cookie」。
    proxy_args = ytdlp_proxy_args()
    if proxy_args:
        print(f"[信息] 下载经代理 {proxy_args[1]}")
    cookie_args = ytdlp_cookie_args(log=print)

    base_cmd = [
        "-f", f"{fid}+ba/b",
        "--merge-output-format", "mp4",
        "--ffmpeg-location", os.path.dirname(ffmpeg_path),
        "--newline", "--no-playlist",
        "--write-thumbnail", "--convert-thumbnails", "jpg",
        "-o", output_template(task_folder),
        *cookie_args, *proxy_args,
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




__all__ = [
    "YTDLP_CHUNK_SIZE",
    "YTDLP_CONCURRENT_FRAGMENTS",
    "ytdlp_concurrent_fragments",
    "ytdlp_dl_args",
    "YTDLP_RETRY_HINTS",
    "ytdlp_prefer_hls",
    "ytdlp_part_leftovers",
    "ytdlp_error_retryable",
    "ytdlp_err_brief",
    "ytdlp_error_needs_reextract",
    "fetch_info_json",
    "parse_qualities",
    "save_info_json",
    "output_template",
    "hls_alt_format",
    "probe_qualities",
    "download_mode",
]
