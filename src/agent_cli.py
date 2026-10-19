# -*- coding: utf-8 -*-
# @version 2.4.0
"""agent_cli —— 视频工具箱「第三方 Agent 接入」统一命令行入口（v1.0.0）。

定位与边界
----------
把工具箱核心能力封装成**无 Qt 依赖**的稳定 CLI，供任意第三方 AI agent
（Claude Code / Trae / Codex …）把工具箱当成一个 "skill" 直接调用。
技能说明书在程序根目录 ``SKILL.md``（与本文件的 ``--help`` 内容同源）；
现有「AI 托管」（harness 方向）与本 CLI 互不影响，两者共存。

运行方式（与 SKILL.md 一致）::

    tools\\python\\python.exe src\\agent_cli.py <子命令> [参数]
    tools\\python\\python.exe src\\agent_cli.py <子命令> --help

全局约定
--------
* ``--json``          结构化输出（stdout 只落一个 JSON 对象；过程日志走 stderr）
* ``--data-root <D>`` 数据根目录（import 引擎**之前**设 ``VT_DATA_ROOT``；
  引擎侧优先级：环境变量 > data_dir.txt 指针 > 程序根，见
  ``video_toolbox._resolve_data_root``）
* AI 参数一律读 ``data\\ai_config.json``（设置页唯一落点），本 CLI 不设
  密钥参数，避免密钥泄进 shell history。
* 产物默认落 ``<数据根>\\data\\agent_out\\<时间戳>\\``，各子命令 ``--out`` 可覆盖。
* 退出码：0 成功；1 失败；``calibrate`` / ``stabilize`` 原样透传
  ``subtitle_calib_merged.py`` 的退出码（length 子命令用退出码当门禁）。

子命令与引擎复用点（都已验证无 Qt 可调）
----------------------------------------
* status      环境/AI 配置自检（engine 常量 + ``ai_load_config``，--ping 实测连通）
* info        媒体元信息（ffprobe JSON）与字幕摘要（``ASRData.from_subtitle_file``）
* download    yt-dlp 原语：``ensure_ytdlp`` / ``ensure_ffmpeg`` / ``fetch_info_json``
              / ``ytdlp_proxy_args`` / ``ytdlp_cookie_args`` / ``output_template``
* transcribe  ``apply_asr_to_engine`` 同步 ASR 槽 → ``engine_asr.set_ffmpeg``
              → ``engine_asr.transcribe``（视频先用 ffmpeg 抽 m4a）
* translate   ``engine_translate.make_translator``（bing/google/deeplx 免认证端点）
* calibrate   subprocess 透传根目录 ``subtitle_calib_merged.py``（术语/规则校准，
              参数表与该脚本完全同源；cwd=程序根，学习库落根目录）
* stabilize   同上透传（该脚本内建子命令）
* audit       同上透传 ``audit`` 子命令——**校准完成后的收口体检**：
               扫 1 拉丁残留（白名单外的英文/罗马字）、扫 2 知识库错形残留
               （变体/条件错形命中中文行而官方名不在该行）、
               扫 3 同词族一致性（参考行命中锚点而中文行缺官方名）。
               退出码 1＝有候选，可直接当 CI 门禁。
* compose     软封装走 ``subtitle_compose.build_command``；硬烧录/带独立音轨走
              ``video_toolbox.merge_pair``
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time

#: 程序根（``<根>\src\agent_cli.py`` → ``<根>``）
APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
#: 根目录校准统一脚本（透传目标）
CALIB_SCRIPT = os.path.join(APP_ROOT, "subtitle_calib_merged.py")
VERSION = "1.0.0"

#: 校准脚本支持的语言旗标（与 subtitle_calib_merged.main_argv 同步，2026-10-15）
CALIB_MODE_FLAGS = ("--ja", "--jpe", "--ko", "--wwoc", "--ak", "--akko",
                    "--zho", "--endo", "--endobi", "--fix-en")


# ============================================================
# 基础设施：数据根 / 输出 / 引擎惰性加载
# ============================================================
def _apply_data_root(args) -> None:
    """把 --data-root 落成 VT_DATA_ROOT（必须在 import 引擎之前调用）。"""
    dr = (getattr(args, "data_root", "") or "").strip().strip('"')
    if dr and os.environ.get("VT_DATA_ROOT", "") != dr:
        os.environ["VT_DATA_ROOT"] = os.path.abspath(dr)


def _engine():
    """惰性加载引擎单文件（体量大，且要求 VT_DATA_ROOT 先就位）。"""
    import video_toolbox as engine  # noqa: PLC0415 —— 惰性
    return engine


def _data_root() -> str:
    """解析后的数据根（与引擎同口径，供不 import 引擎的轻路径使用）。"""
    env = (os.environ.get("VT_DATA_ROOT") or "").strip().strip('"')
    if env:
        return os.path.abspath(env)
    pointer = os.path.join(APP_ROOT, "data_dir.txt")
    try:
        if os.path.isfile(pointer):
            with open(pointer, encoding="utf-8-sig") as f:
                v = f.read().strip().strip('"')
            if v:
                return os.path.abspath(v)
    except OSError:
        pass
    return APP_ROOT


def _agent_out_dir() -> str:
    return os.path.join(_data_root(), "data", "agent_out",
                        time.strftime("%Y%m%d-%H%M%S"))


def _say(args, msg: str) -> None:
    """过程日志：人读模式走 stdout，--json 模式走 stderr（stdout 留给 JSON）。"""
    if getattr(args, "as_json", False):
        print(msg, file=sys.stderr)
    else:
        print(msg)


def _emit(args, payload: dict) -> int:
    """最终结果输出。--json 落单个 JSON 到 stdout；否则人读摘要。返回退出码。"""
    ok = bool(payload.get("ok"))
    if getattr(args, "as_json", False):
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if ok else 1
    for line in _human_lines(payload):
        print(line)
    return 0 if ok else 1


def _human_lines(payload: dict) -> list:
    """把结果 dict 转成人读摘要（只挑关键键，其余进 detail）。"""
    lines = ["ok: %s" % payload.get("ok")]
    for k, v in payload.items():
        if k in ("ok",):
            continue
        if isinstance(v, (dict, list)):
            v = json.dumps(v, ensure_ascii=False)
        lines.append("%s: %s" % (k, v))
    return lines


def _fail(args, error: str, **extra) -> int:
    return _emit(args, {"ok": False, "error": error, **extra})


# ============================================================
# status：环境 / AI 配置自检
# ============================================================
def cmd_status(args) -> int:
    engine = _engine()
    tools = engine.TOOLS_DIR
    tools_list = sorted(os.listdir(tools)) if os.path.isdir(tools) else []

    def _has(name):
        return name if os.path.isfile(os.path.join(tools, name)) else ""

    ai = engine.ai_load_config()
    asr = {}
    try:
        asr = engine.ai_mod().asr_config(ai)
    except Exception as e:  # noqa: BLE001
        asr = {"error": str(e)[:120]}

    result = {
        "ok": True,
        "version": VERSION,
        "app_root": APP_ROOT,
        "data_root": engine.DATA_ROOT,
        "data_dir": engine.DATA_DIR,
        "python": sys.executable,
        "tools_dir": tools,
        "ffmpeg": _has("ffmpeg.exe") or shutil.which("ffmpeg") or "缺失（首次用时自动下载）",
        "ffprobe": _has("ffprobe.exe") or shutil.which("ffprobe") or "缺失",
        "yt_dlp": _has("yt-dlp.exe") or "缺失（首次用时自动下载）",
        "deno": _has("deno.exe") or "缺失（YouTube 提取需要）",
        "tools_files": tools_list[:20],
        "ai": {
            "configured": bool((ai.get("base_url") or "").strip()
                               and (ai.get("api_key") or "").strip()
                               and (ai.get("model") or "").strip()),
            "base_url": (ai.get("base_url") or "").strip(),
            "model": (ai.get("model") or "").strip(),
            "vision_model": (ai.get("vision_model") or "").strip(),
            "asr": {"mode": asr.get("mode"),
                    "base_url": asr.get("base_url"),
                    "model": asr.get("model"),
                    "ready": bool(asr.get("base_url") and asr.get("api_key"))
                    if asr.get("mode") != "local"
                    else bool(asr.get("local_model") or asr.get("local_model_dir"))},
        },
    }
    # 可选：实测 LLM 连通（会花一次真实请求）
    if getattr(args, "ping", False):
        try:
            ok, detail = engine.ai_test_connection()
        except Exception as e:  # noqa: BLE001
            ok, detail = False, str(e)[:200]
        result["ai"]["ping"] = {"ok": ok, "detail": detail}
        if not ok:
            result["ok"] = False
    return _emit(args, result)


# ============================================================
# info：媒体 / 字幕元信息
# ============================================================
def cmd_info(args) -> int:
    path = os.path.abspath(args.file)
    if not os.path.isfile(path):
        return _fail(args, "文件不存在：%s" % path)
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    engine = _engine()
    if ext in ("srt", "ass", "vtt", "ssa", "txt", "json"):
        return _info_subtitle(args, path, ext)
    if ext in ("mp3", "m4a", "wav", "flac", "aac", "ogg", "opus"):
        return _info_av(args, path, kind="audio")
    if ext in ("mp4", "mkv", "webm", "mov", "avi", "flv", "ts", "m4v",
               "weba", "mka", "mpg", "mpeg"):
        return _info_av(args, path, kind="video")
    # 未知扩展名按 ffprobe 探测结果判定
    probe = _ffprobe_json(engine, path)
    if probe is None:
        return _fail(args, "无法识别的文件类型：%s" % ext)
    fmt = (probe.get("format") or {}).get("format_name", "")
    if any(k in fmt for k in ("mp3", "aac", "flac", "wav", "ogg", "opus", "m4a")):
        return _info_av(args, path, kind="audio")
    return _info_av(args, path, kind="video")


def _ffprobe_json(engine, path):
    try:
        proc = subprocess.run(
            [engine.FFPROBE_PATH, "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", path],
            capture_output=True, timeout=60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if proc.returncode != 0:
            return None
        return json.loads(proc.stdout.decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        return None


def _info_av(args, path, kind):
    engine = _engine()
    probe = _ffprobe_json(engine, path)
    if probe is None:
        return _fail(args, "ffprobe 解析失败：%s" % path)
    fmt = probe.get("format") or {}
    streams = probe.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    result = {
        "ok": True,
        "file": path,
        "kind": kind,
        "duration_sec": _to_float(fmt.get("duration")),
        "size_bytes": _to_int(fmt.get("size")),
        "format": fmt.get("format_name"),
        "video": None if video is None else {
            "codec": video.get("codec_name"),
            "width": video.get("width"), "height": video.get("height"),
            "fps": _to_float(video.get("avg_frame_rate") and
                             _rate(video.get("avg_frame_rate"))),
        },
        "audio": None if audio is None else {
            "codec": audio.get("codec_name"),
            "channels": audio.get("channels"),
            "sample_rate": _to_int(audio.get("sample_rate")),
        },
        "n_streams": len(streams),
    }
    return _emit(args, result)


def _info_subtitle(args, path, ext):
    from engine_asr_data import ASRData  # noqa: PLC0415 —— 惰性
    try:
        data = ASRData.from_subtitle_file(path)
    except Exception as e:  # noqa: BLE001
        return _fail(args, "字幕解析失败：%s" % e)
    segs = list(getattr(data, "segments", []) or [])
    span = ""
    if segs:
        first = getattr(segs[0], "start_time", None)
        last = getattr(segs[-1], "end_time", None)
        fmt = lambda ms: "%02d:%02d:%06.3f" % (ms // 3600000, ms // 60000 % 60, (ms % 60000) / 1000) \
            if isinstance(ms, int) else str(ms)
        span = "%s → %s" % (fmt(first), fmt(last))
    result = {
        "ok": True,
        "file": path,
        "kind": "subtitle",
        "format": ext,
        "n_cues": len(segs),
        "time_span": span,
        "n_translated": sum(1 for s in segs
                            if (getattr(s, "translated_text", "") or "").strip()),
    }
    return _emit(args, result)


def _to_float(v):
    try:
        return round(float(v), 3)
    except (TypeError, ValueError):
        return None


def _to_int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _rate(txt):
    try:
        num, _, den = txt.partition("/")
        d = float(den or 1)
        return float(num) / d if d else None
    except (TypeError, ValueError):
        return None


# ============================================================
# download：yt-dlp 下载
# ============================================================
def cmd_download(args) -> int:
    engine = _engine()
    ytdlp = engine.ensure_ytdlp()
    ffmpeg_path, _ = engine.ensure_ffmpeg()
    url = args.url
    _say(args, "[1/3] 提取视频信息 …")
    try:
        raw = engine.fetch_info_json(ytdlp, url, log=lambda m: _say(args, str(m)))
    except Exception as e:  # noqa: BLE001
        return _fail(args, "提取视频信息失败：%s" % e)
    if not raw:
        return _fail(args, "提取视频信息失败（网络/风控），详见上方日志")
    try:
        meta = json.loads(raw)
    except ValueError:
        meta = {}
    title = (meta.get("title") or "video").strip()
    duration = _to_float(meta.get("duration"))

    out_dir = os.path.abspath(args.dir) if args.dir else os.path.join(
        engine.DATA_DIR, "downloads", "agent",
        re.sub(r'[\\/:*?"<>|]+', "_", title)[:80] or "video")
    os.makedirs(out_dir, exist_ok=True)

    proxy_args = engine.ytdlp_proxy_args()
    if proxy_args:
        _say(args, "[信息] 下载经代理 %s" % proxy_args[1])
    cookie_args = engine.ytdlp_cookie_args(log=lambda m: _say(args, str(m)))
    height = ("[height<=%d]" % args.height) if args.height else ""
    argv = [ytdlp, "-f", f"bv*{height}+ba/b",
            "--merge-output-format", "mp4",
            "--ffmpeg-location", os.path.dirname(ffmpeg_path),
            "--newline", "--no-playlist",
            # 与下载页/流水线共用同一份提速+抗断流参数（--concurrent-fragments 5、
            # --socket-timeout/--retries/--fragment-retries/--retry-sleep）。
            # 此前 CLI 未采用 → 分片串行下载，实测长视频仅 ~300KB/s。
            # ⚠ 用函数而非常量：A3-1 拆分已把 YTDLP_DL_COMMON_ARGS 改为
            #   ytdlp_dl_args()，旧名不存在（引旧名必 AttributeError）。
            *engine.ytdlp_dl_args(),
            "-o", engine.output_template(out_dir),
            *cookie_args, *proxy_args, url]
    _say(args, "[2/3] 开始下载：%s" % title)
    proc = subprocess.run(argv)
    if proc.returncode != 0:
        return _fail(args, "yt-dlp 退出码 %d" % proc.returncode,
                     title=title, dir=out_dir)
    files = [os.path.join(out_dir, n) for n in sorted(os.listdir(out_dir))
             if os.path.isfile(os.path.join(out_dir, n))]
    videos = [f for f in files if f.lower().endswith((".mp4", ".mkv", ".webm"))]
    _say(args, "[3/3] 下载完成")
    return _emit(args, {"ok": True, "title": title,
                        "duration_sec": duration, "dir": out_dir,
                        "video": videos[0] if videos else "",
                        "n_files": len(files)})


# ============================================================
# transcribe：ASR 转录
# ============================================================
def cmd_transcribe(args) -> int:
    engine = _engine()
    src = os.path.abspath(args.file)
    if not os.path.isfile(src):
        return _fail(args, "文件不存在：%s" % src)

    # ① 同步「设置」页 ASR 配置进引擎 settings（与 GUI「保存并应用」同款）
    ok, detail = engine.apply_asr_to_engine()
    if not ok:
        return _fail(args, "ASR 配置未就绪：%s（请先在「设置 → ASR 语音识别」配置）"
                     % detail)

    # ② 视频先抽音频（engine_asr 只吃 flac/m4a/mp3/wav）
    ffmpeg_path, _ = engine.ensure_ffmpeg()
    ext = os.path.splitext(src)[1].lower().lstrip(".")
    if ext in ("flac", "m4a", "mp3", "wav"):
        audio_path = src
    else:
        out_dir = os.path.abspath(args.out) if args.out else _agent_out_dir()
        out_path = out_dir if out_dir.lower().endswith(".srt") else \
            os.path.join(out_dir, os.path.splitext(os.path.basename(src))[0] + ".srt")
        audio_path = os.path.splitext(out_path)[0] + ".tmpaudio.m4a"
        _say(args, "[1/3] 抽取音频 → %s" % audio_path)
        proc = subprocess.run(
            [ffmpeg_path, "-y", "-nostdin", "-i", src, "-vn",
             "-c:a", "aac", "-b:a", "192k", audio_path],
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if proc.returncode != 0 or not os.path.isfile(audio_path):
            tail = proc.stderr.decode("utf-8", "replace").strip().splitlines()[-6:]
            return _fail(args, "抽取音频失败：\n" + "\n".join(tail))

    # ③ 构造转录配置：以引擎 settings 为底，CLI --lang 可覆盖
    from engine_task_factory import TaskFactory  # noqa: PLC0415
    task = TaskFactory.create_transcribe_task(src, need_next_task=False)
    config = task.transcribe_config
    if args.lang:
        code = _lang_code(args.lang)
        if code is None:
            return _fail(args, "无法识别的语言：%r（可用 ISO 码或引擎标签，"
                               "如 ja / en / zh / 日本語 / 英语）" % args.lang)
        config.transcribe_language = code
        _say(args, "[信息] 识别语言：%s" % (code or "自动检测"))

    # ④ 转录
    engine_asr = _mod("engine_asr")
    engine_asr.set_ffmpeg(ffmpeg_path)
    out_dir = os.path.abspath(args.out) if args.out else _agent_out_dir()
    out_path = out_dir if out_dir.lower().endswith(".srt") else \
        os.path.join(out_dir, os.path.splitext(os.path.basename(src))[0] + ".srt")
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    _say(args, "[2/3] 开始转录（模型：%s）…" % config.transcribe_model)

    def _cb(pct, msg):
        _say(args, "[%3d%%] %s" % (pct, msg))

    try:
        asr_data = engine_asr.transcribe(audio_path, config, callback=_cb)
    except Exception as e:  # noqa: BLE001
        return _fail(args, "转录失败：%s" % e)
    asr_data.save(out_path)
    if audio_path != src:
        try:
            os.remove(audio_path)
        except OSError:
            pass
    _say(args, "[3/3] 转录完成")
    return _emit(args, {"ok": True, "source": src, "output": out_path,
                        "language": config.transcribe_language or "自动检测"})


def _mod(name):
    import importlib  # noqa: PLC0415
    return importlib.import_module(name)


def _lang_code(v: str):
    """语言参数 → 引擎识别语言的 ISO 码（也接受引擎标签）。"""
    from engine_entities import LANGUAGES  # noqa: PLC0415
    v = (v or "").strip()
    if not v or v in ("auto", "自动检测"):
        return ""
    if v in LANGUAGES.values():      # 已是 ISO 码
        return v
    if v in LANGUAGES:               # 引擎标签
        return LANGUAGES[v]
    alias = {"zh": "zh-Hans", "zt": "zh-Hant", "jp": "ja", "kr": "ko", "ko": "ko"}
    code = alias.get(v.lower())
    return code if code and code in LANGUAGES.values() else None


# ============================================================
# translate：字幕翻译（免认证端点）
# ============================================================
def cmd_translate(args) -> int:
    from engine_asr_data import ASRData      # noqa: PLC0415
    from engine_translate import make_translator  # noqa: PLC0415
    src = os.path.abspath(args.file)
    if not os.path.isfile(src):
        return _fail(args, "文件不存在：%s" % src)
    try:
        data = ASRData.from_subtitle_file(src)
    except Exception as e:  # noqa: BLE001
        return _fail(args, "字幕解析失败：%s" % e)
    segs = list(getattr(data, "segments", []) or [])
    if not segs:
        return _fail(args, "字幕没有任何 cue")

    target = _lang_label(args.to)
    if target is None:
        return _fail(args, "无法识别的目标语言：%r" % args.to)
    try:
        translator = make_translator(args.engine, thread_num=args.threads,
                                     batch_num=args.batch,
                                     target_language=target)
    except KeyError as e:
        return _fail(args, str(e))
    ok, why = translator.probe()
    if not ok:
        return _fail(args, "翻译端点不可用（%s）：%s" % (args.engine, why))

    out_dir = os.path.abspath(args.out) if args.out else _agent_out_dir()
    out_path = out_dir if out_dir.lower().endswith((".srt", ".ass", ".txt")) else \
        os.path.join(out_dir, os.path.splitext(os.path.basename(src))[0]
                     + ".zh.srt")
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    # 引擎 chunk 协议是 SubtitleProcessData(original_text/translated_text)，
    # 而 ASRData 段的原文字段叫 text——包一层适配，译后回写 seg.translated_text，
    # save() 按 ORIGINAL_ON_TOP（原文在上、译文在下）出双语字幕。
    from videocaptioner.core.entities import SubtitleProcessData  # noqa: PLC0415
    items = [SubtitleProcessData(index=i, original_text=(s.text or ""))
             for i, s in enumerate(segs)]

    from concurrent.futures import ThreadPoolExecutor, as_completed  # noqa: PLC0415
    chunks = [items[i:i + args.batch] for i in range(0, len(items), args.batch)]
    _say(args, "[信息] %d 条 cue → %d 块（%s → %s，%d 线程）"
         % (len(segs), len(chunks), args.engine, target, args.threads))
    failed = 0
    with ThreadPoolExecutor(max_workers=args.threads) as pool:
        futs = {pool.submit(translator.translate, c): c for c in chunks}
        for i, fut in enumerate(as_completed(futs), 1):
            try:
                fut.result()
            except Exception:  # noqa: BLE001
                failed += 1
            _say(args, "[%d/%d] 块完成" % (i, len(chunks)))
    n_bad = 0
    for seg, item in zip(segs, items):
        zh = (item.translated_text or "").strip()
        if not zh or zh == "ERROR":
            n_bad += 1
            continue                      # 失败条目不写译文（保留纯原文）
        seg.translated_text = zh
    data.save(out_path)
    return _emit(args, {"ok": n_bad == 0, "source": src,
                        "output": out_path, "target": target,
                        "engine": args.engine,
                        "n_cues": len(segs),
                        "n_failed_chunks": failed,
                        "n_failed_lines": n_bad})


def _lang_label(v: str):
    """目标语言三套口径都收：引擎标签（中文/英语…）、翻译器标签（简体中文…）、
    ISO 码（zh-Hans/zh/en/ja…）。无法识别返回 None（由调用方报错）。"""
    from engine_entities import LANGUAGES  # noqa: PLC0415
    v = (v or "").strip()
    if not v:
        return "简体中文"
    if v in LANGUAGES or v in LANGUAGES.values():
        return v
    try:
        import engine_translate as et  # noqa: PLC0415
        probes = getattr(et, "TRANSLATOR_PROBES", {}) or {}
    except Exception:  # noqa: BLE001
        probes = {}
    for cls in probes.values():
        lm = getattr(cls, "lang_map", {}) or {}
        if v in lm or v in lm.values():
            return v
    #: ISO 简码 → 翻译器标签（端点代码由翻译器自己的 lang_map 解析）
    iso = {"zh": "简体中文", "zh-cn": "简体中文", "zh-hans": "简体中文",
           "zh-tw": "繁体中文", "zh-hant": "繁体中文", "zt": "繁体中文",
           "en": "英语", "ja": "日本語", "jp": "日本語", "ko": "韩语", "kr": "韩语",
           "yue": "粤语", "fr": "法语", "de": "德语", "es": "西班牙语",
           "ru": "俄语", "pt": "葡萄牙语", "tr": "土耳其语"}
    return iso.get(v.lower())


# ============================================================
# calibrate / stabilize：透传 subtitle_calib_merged.py
# ============================================================
def _run_calib_passthrough(args, sub: str | None, extra: list) -> int:
    """透传给根目录校准统一脚本（subprocess 隔离；exit code 原样返回）。"""
    if not os.path.isfile(CALIB_SCRIPT):
        return _fail(args, "校准脚本不存在：%s" % CALIB_SCRIPT)
    argv = [sys.executable, CALIB_SCRIPT]
    if sub:
        argv.append(sub)
    argv.extend(extra)
    _say(args, "[信息] %s" % " ".join(os.path.relpath(a, APP_ROOT)
                                      if os.path.isabs(a) and a.startswith(APP_ROOT)
                                      else a for a in argv[1:]))
    # 不捕获输出：校准进度/报告直接过终端；--json 时也要透传 exit code
    proc = subprocess.run(argv, cwd=APP_ROOT)
    if getattr(args, "as_json", False):
        print(json.dumps({"ok": proc.returncode == 0,
                          "script": os.path.relpath(CALIB_SCRIPT, APP_ROOT),
                          "exit_code": proc.returncode},
                         ensure_ascii=False, indent=2))
        return proc.returncode
    return proc.returncode


def cmd_calibrate(args) -> int:
    """术语/规则校准：`calibrate <input.srt> [--out F] [--report F] [--ja|--ko|…]`。

    其余未识别参数原样透传给 subtitle_calib_merged.py（参数表完全同源）。
    """
    if not args.input:
        return _fail(args, "缺少输入字幕（用法：calibrate <input.srt> [--out F] "
                           "[--report F] [--ja|--ko|--endo|--ak|…]）")
    return _run_calib_passthrough(args, None, args.input + args.extra)


def cmd_stabilize(args) -> int:
    """cue 稳定化：`stabilize <input.srt> [该脚本 stabilize 子命令的其余参数]`。"""
    if not args.input:
        return _fail(args, "缺少输入字幕（用法：stabilize <input.srt> [--out F] …）")
    return _run_calib_passthrough(args, "stabilize", args.input + args.extra)


def cmd_audit(args) -> int:
    """名词漏校三扫：`audit <校准后.srt> [--mode bi] [--out 报告.md] [--json] [--loose]`。

    透传 subtitle_calib_merged.py 的 audit 子命令：拉丁残留 / 知识库错形残留 /
    同词族一致性。退出码 1＝有候选（可当门禁）。
    """
    if not args.input:
        return _fail(args, "缺少输入字幕（用法：audit <校准后.srt> [--mode bi] "
                           "[--out 报告.md] [--json] [--loose]）")
    return _run_calib_passthrough(args, "audit", args.input + args.extra)


# ============================================================
# compose：字幕合成
# ============================================================
def cmd_compose(args) -> int:
    engine = _engine()
    ffmpeg_path, _ = engine.ensure_ffmpeg()
    video = os.path.abspath(args.video)
    sub = os.path.abspath(args.sub)
    for label, p in (("视频", video), ("字幕", sub)):
        if not os.path.isfile(p):
            return _fail(args, "%s文件不存在：%s" % (label, p))
    audio = os.path.abspath(args.audio) if args.audio else ""
    if audio and not os.path.isfile(audio):
        return _fail(args, "音轨文件不存在：%s" % audio)
    ext = os.path.splitext(sub)[1].lower()
    out = os.path.abspath(args.out) if args.out else os.path.join(
        _agent_out_dir(),
        os.path.splitext(os.path.basename(video))[0] + ".composed.mp4")
    if os.path.abspath(out) == video:
        return _fail(args, "输出文件不能就是原视频本身")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)

    # —— 带独立音轨（下载产物合并场景）→ 引擎 merge_pair ——
    if audio:
        atype = "m4a" if audio.lower().endswith(".m4a") else "weba"
        sub_type = "srt" if ext == ".srt" else "ass"
        _say(args, "[信息] 走引擎 merge_pair（%s 音轨 + %s 字幕，%s）"
             % (atype, sub_type, "硬烧" if (sub_type == "ass" and
                                            args.mode != "mkv") else "封装"))
        engine.merge_pair(video, audio, atype, sub, sub_type, out,
                          ffmpeg_path,
                          ass_mode="burn" if args.mode == "burn" else
                          ("mkv" if out.lower().endswith(".mkv") else "burn"))
        if not os.path.isfile(out):
            return _fail(args, "合成失败（merge_pair 未产出文件），详见上方输出")
        return _emit(args, {"ok": True, "video": video, "subtitle": sub,
                            "audio": audio, "output": out, "mode": "merge"})

    # —— 无独立音轨：soft（封装软字幕，不重编码）/ burn（ASS 硬烧，重编码）——
    if args.mode == "burn":
        sub_clean = sub.replace("\\", "/").replace("'", "\\'")
        argv = [ffmpeg_path, "-y", "-nostdin", "-i", video,
                "-vf", "subtitles='%s'" % sub_clean,
                "-c:v", "libx264", "-crf", "18", "-preset", "fast",
                "-c:a", "copy", out]
        _say(args, "[信息] 硬烧录字幕（视频重编码 H.264）…")
    else:
        import subtitle_compose  # noqa: PLC0415
        argv, err = subtitle_compose.build_command(ffmpeg_path, video, sub, out)
        if err:
            return _fail(args, err)
        _say(args, "[信息] 软字幕封装（音视频 copy，不重编码）…")
    proc = subprocess.run(argv, capture_output=True,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if proc.returncode != 0 or not os.path.isfile(out):
        tail = proc.stderr.decode("utf-8", "replace").strip().splitlines()[-6:]
        return _fail(args, "ffmpeg 退出码 %s：\n%s"
                     % (proc.returncode, "\n".join(tail)))
    return _emit(args, {"ok": True, "video": video, "subtitle": sub,
                        "output": out, "mode": args.mode})


# ============================================================
# argparse 装配
# ============================================================
#: 全局选项的「子命令级副本」：Agent 写成 ``status --json``（选项在后）是本能，
#: 两种位置都必须认。default=SUPPRESS 保证未提供时不会用 False/"" 覆盖全局值。
common = argparse.ArgumentParser(add_help=False)
common.add_argument("--json", dest="as_json", action="store_true",
                    default=argparse.SUPPRESS,
                    help="结构化输出（stdout 只落一个 JSON；日志走 stderr）")
common.add_argument("--data-root", default=argparse.SUPPRESS,
                    help="数据根目录（默认：VT_DATA_ROOT > data_dir.txt > 程序根）")


def build_parser() -> argparse.ArgumentParser:
    epilog = "\n".join([
        "示例：",
        "  %(prog)s status --ping",
        "  %(prog)s status --json",
        "  %(prog)s info D:\\media\\ep01.mp4",
        "  %(prog)s download \"https://www.youtube.com/watch?v=xxx\" --height 1080",
        "  %(prog)s transcribe ep01.mp4 --lang ja --out data\\agent_out\\ep01.srt",
        "  %(prog)s translate ep01.srt --to zh-Hans --engine bing",
        "  %(prog)s calibrate ep01.srt --ja --out ep01_calib.srt --report ep01_r.tsv",
        "  %(prog)s stabilize ep01.srt",
        "  %(prog)s compose ep01.mp4 ep01_calib.srt --out ep01_final.mp4",
        "  %(prog)s compose ep01.mp4 ep01.ass --audio ep01.m4a --out ep01_final.mp4",
        "技能说明书：程序根目录 SKILL.md（与本帮助同源）。",
    ])
    p = argparse.ArgumentParser(
        prog="agent_cli",
        description="视频工具箱「第三方 Agent 接入」统一 CLI（无 GUI 依赖；"
                    "AI 模型/密钥/接口地址读 data\\ai_config.json，"
                    "由工具箱「设置」页配置）。")
    p.add_argument("--json", dest="as_json", action="store_true",
                   help="结构化输出（stdout 只落一个 JSON；日志走 stderr）")
    p.add_argument("--data-root", default="",
                   help="数据根目录（默认：VT_DATA_ROOT > data_dir.txt > 程序根）")
    p.add_argument("--version", action="version",
                   version="agent_cli %s" % VERSION)
    sub = p.add_subparsers(dest="cmd", required=True, metavar="<子命令>")

    s = sub.add_parser("status", parents=[common],
                       help="环境/AI 配置自检（工具在位性、AI/ASR 槽是否已配）")
    s.add_argument("--ping", action="store_true",
                   help="实测全局 AI 连通性（发一次真实请求）")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("info", parents=[common],
                       help="媒体/字幕元信息（ffprobe；字幕给 cue 数与时间跨度）")
    s.add_argument("file", help="视频 / 音频 / 字幕文件路径")
    s.set_defaults(fn=cmd_info)

    s = sub.add_parser("download", parents=[common],
                       help="下载视频（yt-dlp，自动代理+游客 cookie，合并 mp4）")
    s.add_argument("url", help="视频链接（YouTube/B站等 yt-dlp 支持的站点）")
    s.add_argument("--dir", default="", help="输出目录（默认 data\\downloads\\agent\\<标题>\\）")
    s.add_argument("--height", type=int, default=0,
                   help="限制最大分辨率高度（如 1080；0=不限制）")
    s.set_defaults(fn=cmd_download)

    s = sub.add_parser("transcribe", parents=[common],
                       help="ASR 转录出 SRT（模型/密钥读设置页 ASR 槽）")
    s.add_argument("file", help="视频或音频文件")
    s.add_argument("--lang", default="", help="识别语言：ISO 码或引擎标签（ja/en/zh/日本語…；空=自动检测）")
    s.add_argument("--out", default="", help="输出 .srt 或目录（默认 data\\agent_out\\<时间戳>\\）")
    s.set_defaults(fn=cmd_transcribe)

    s = sub.add_parser("translate", parents=[common],
                       help="翻译字幕（bing/google/deeplx 免认证端点）")
    s.add_argument("file", help="输入字幕（.srt/.ass/.vtt）")
    s.add_argument("--to", default="zh-Hans", help="目标语言（zh-Hans/简体中文/en…）")
    s.add_argument("--engine", default="bing",
                   choices=["bing", "google", "deeplx", "微软翻译", "谷歌翻译", "DeepLx 翻译"],
                   help="翻译服务（默认 bing）")
    s.add_argument("--threads", type=int, default=4, help="并发线程数（默认 4）")
    s.add_argument("--batch", type=int, default=20, help="每块 cue 数（默认 20）")
    s.add_argument("--out", default="", help="输出字幕或目录（默认 data\\agent_out\\<时间戳>\\<名>.zh.srt）")
    s.set_defaults(fn=cmd_translate)

    s = sub.add_parser("calibrate", parents=[common],
                       help="字幕术语校准（透传 subtitle_calib_merged.py，只改文字不动时间轴）")
    s.set_defaults(fn=cmd_calibrate, input=[], extra=[])

    s = sub.add_parser("stabilize", parents=[common],
                       help="cue 稳定化（透传 subtitle_calib_merged.py 的 stabilize 子命令）")
    s.set_defaults(fn=cmd_stabilize, input=[], extra=[])

    s = sub.add_parser("audit", parents=[common],
                       help="名词漏校三扫（透传 subtitle_calib_merged.py 的 audit 子命令；"
                            "拉丁残留 / 错形残留 / 同词族一致性，退出码 1＝有候选）")
    s.set_defaults(fn=cmd_audit, input=[], extra=[])

    s = sub.add_parser("compose", parents=[common],
                       help="字幕合成：软封装（copy）/ 硬烧录 / 带独立音轨合并")
    s.add_argument("video", help="视频文件")
    s.add_argument("sub", help="字幕文件（.srt/.ass）")
    s.add_argument("--audio", default="", help="独立音轨（.m4a/.weba，如下载产物分离音轨；可选）")
    s.add_argument("--mode", default="soft", choices=["soft", "burn", "mkv"],
                   help="soft=软封装不重编码（默认）；burn=硬烧录（ASS，重编码）；mkv=封装进 MKV")
    s.add_argument("--out", default="", help="输出文件（默认 data\\agent_out\\<时间戳>\\<名>.composed.mp4）")
    s.set_defaults(fn=cmd_compose)

    # epilog 里的反斜杠路径保持原样
    for a in (p, *[a for a in sub.choices.values()]):
        a.formatter_class = argparse.RawDescriptionHelpFormatter
    p.epilog = epilog
    return p


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # calibrate / stabilize 的透传参数可能与 argparse 冲突（如 --out 本 CLI 不认）：
    # 先把「这两个子命令之后的所有参数」原样截下，只解析全局项与子命令名。
    passthrough = None
    for i, a in enumerate(argv):
        if a in ("calibrate", "stabilize", "audit"):
            passthrough = argv[i + 1:]
            argv = argv[:i + 1]
            break
    # ``calibrate --help`` 是要帮助、不是透传参数：交还 argparse 打印子命令帮助
    if passthrough is not None and passthrough and passthrough[0] in ("--help", "-h"):
        build_parser().parse_args(argv + ["--help"])
    parser = build_parser()
    args = parser.parse_args(argv)
    if passthrough is not None:
        # 透传段里剔除全局项（--json / --data-root 允许出现在末尾）
        rest = []
        it = iter(passthrough)
        for a in it:
            if a == "--json":
                args.as_json = True
            elif a == "--data-root":
                args.data_root = next(it, "")
            else:
                rest.append(a)
        # 透传段第一个非旗标参数 = 输入字幕（含其参数值，如 --out x.srt 里的 x.srt
        # 已由透传脚本自行消费；这里只切出"第一个位置参数"）
        args.input = []
        args.extra = list(rest)
        for i, a in enumerate(args.extra):
            if not a.startswith("-"):
                args.input = [a]
                args.extra = args.extra[:i] + args.extra[i + 1:]
                break
    _apply_data_root(args)
    try:
        return args.fn(args)
    except KeyboardInterrupt:
        print("[中断] 用户取消", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
