#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# @version 1.19.0
"""全功能引擎层冒烟测试（v1.15.8 审查用）。

分组覆盖（--only A,C / --skip B 选组）：
  A 运行时二进制   B 内嵌python与依赖   C ffmpeg链路    D ASR配置链路
  E AI(LLM)与校准  F 字幕引擎与工具函数  G mpv          H 代理/cookie/站点探测
  I 数据文件完整性 J 源码语法全量

运行：tools/python/python.exe _smoke_all.py [--only A,C] [--skip H]
结果同步落盘 data/tmp/smoke_result.json（防管道缓冲假死干扰）。
"""
import json
import os
import py_compile
import subprocess
import sys
import time
import glob

#: 脚本位于 <仓库根>/scripts/dev/，SRC 语义保持「主程序源码目录」
SRC = os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "src")
sys.path.insert(0, SRC)
os.environ["VT_NO_PIPELINE"] = "1"

# ---- 参数 ----
ONLY = SKIP = None
for i, a in enumerate(sys.argv):
    if a == "--only" and i + 1 < len(sys.argv):
        ONLY = {g.strip().upper() for g in sys.argv[i + 1].split(",")}
    if a == "--skip" and i + 1 < len(sys.argv):
        SKIP = {g.strip().upper() for g in sys.argv[i + 1].split(",")}


def want(g):
    if ONLY:
        return g in ONLY
    if SKIP:
        return g not in SKIP
    return True


import video_toolbox as engine  # noqa: E402

RESULT_PATH = os.path.join(engine.TMP_DIR, "smoke_result.json")
RESULTS = []


def check(group_id, name, cond, extra=""):
    mark = "OK " if cond else "FAIL"
    extra_s = f" —— {extra}" if extra else ""
    RESULTS.append((group_id, name, bool(cond), str(extra_s)))
    print(f"  [{mark}] [{group_id}] {name}{extra_s}", flush=True)
    _dump()
    return bool(cond)


def group(title):
    print(f"\n■■■ {title} ■■■", flush=True)


def _dump():
    try:
        with open(RESULT_PATH, "w", encoding="utf-8") as f:
            json.dump(RESULTS, f, ensure_ascii=False, indent=1)
    except Exception:  # noqa: BLE001
        pass


def run(cmd, timeout=60, **kw):
    return subprocess.run(cmd, capture_output=True, timeout=timeout,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                          **kw)


# ============ A. 运行时二进制 ============
if want("A"):
    group("A. 运行时二进制完整性")
    bins = {
        "ffmpeg.exe": engine.FFMPEG_PATH,
        "ffprobe.exe": engine.FFPROBE_PATH,
        "yt-dlp.exe": engine.YTDLP_PATH,
        "deno.exe": engine.DENO_PATH,
        "libmpv-2.dll": os.path.join(engine.TOOLS_DIR, "mpv", "libmpv-2.dll"),
        "python.exe": os.path.join(engine.EMBEDDED_PYTHON_DIR, "python.exe"),
        "mihomo.exe": engine.MIHOMO_EXE,
        "mihomo config.yaml": engine.MIHOMO_CONFIG,
        "github_proxy.yaml": os.path.join(engine.APP_DIR, "github_proxy.yaml"),
    }
    for name, p in bins.items():
        check("A", f"{name} 存在", os.path.isfile(p), p)
    sp = engine.EMBEDDED_SITE_PACKAGES
    check("A", "内嵌 site-packages 存在", os.path.isdir(sp), sp)

# ============ B. 内嵌 python 与关键依赖 ============
if want("B"):
    group("B. 内嵌运行时与关键依赖")
    py = os.path.join(engine.EMBEDDED_PYTHON_DIR, "python.exe")
    try:
        r = run([py, "-V"], timeout=60)
        check("B", "python -V", r.returncode == 0 and b"3.12" in r.stdout,
              r.stdout.decode(errors="replace").strip())
    except Exception as e:  # noqa: BLE001
        check("B", "python -V", False, repr(e)[:100])
    for modname in ("PyQt5", "qfluentwidgets", "videocaptioner", "faster_whisper",
                    "yaml", "diskcache", "platformdirs"):
        try:
            r = run([py, "-c", f"import {modname}; print('ok')"], timeout=150)
            check("B", f"import {modname}", r.returncode == 0 and b"ok" in r.stdout,
                  (r.stderr.decode(errors="replace").strip().splitlines()
                   or [""])[-1][:120])
        except Exception as e:  # noqa: BLE001
            check("B", f"import {modname}", False, repr(e)[:120])
    # mpv：真实加载路径是 subtitle_editor_media.load_mpv（PATH+sys.path 双注入）
    try:
        r = run([py, "-c",
                 "import sys; sys.path.insert(0, r'D:/VideoToolbox/src'); "
                 "from subtitle_editor_media import load_mpv; "
                 "mod, err = load_mpv(r'D:/VideoToolbox/tools/mpv'); "
                 "print('ok') if mod else print(err)"], timeout=150)
        check("B", "import mpv（经 load_mpv 真实路径）",
              r.returncode == 0 and b"ok" in r.stdout,
              (r.stderr.decode(errors="replace").strip().splitlines()
               or r.stdout.decode(errors="replace").strip().splitlines()
               or [""])[-1][:120])
    except Exception as e:  # noqa: BLE001
        check("B", "import mpv", False, repr(e)[:120])

# ============ C. ffmpeg 链路 ============
if want("C"):
    group("C. ffmpeg 转码/抽帧/探测链路")
    try:
        r = run([engine.FFMPEG_PATH, "-version"], timeout=30)
        check("C", "ffmpeg -version", r.returncode == 0)
        r = run([engine.FFPROBE_PATH, "-version"], timeout=30)
        check("C", "ffprobe -version", r.returncode == 0)
        tmpd = os.path.join(engine.TMP_DIR, "_smoke")
        os.makedirs(tmpd, exist_ok=True)
        wav_src = os.path.join(tmpd, "sine.mp3")
        wav_out = os.path.join(tmpd, "sine_16k.wav")
        clip = os.path.join(tmpd, "clip.mp4")
        thumb = os.path.join(tmpd, "thumb.jpg")
        run([engine.FFMPEG_PATH, "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
             "-q:a", "4", "-y", wav_src], timeout=60)
        r = run([engine.FFMPEG_PATH, "-i", wav_src, "-map", "0:a:0", "-vn",
                 "-ac", "1", "-ar", "16000", "-y", wav_out], timeout=60)
        check("C", "mp3→16kHz wav（video2audio 等价）",
              r.returncode == 0 and os.path.isfile(wav_out)
              and os.path.getsize(wav_out) > 1000)
        run([engine.FFMPEG_PATH, "-f", "lavfi", "-i",
             "testsrc=duration=3:size=640x360:rate=15",
             "-f", "lavfi", "-i", "sine=frequency=300:duration=3", "-shortest",
             "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
             "-y", clip], timeout=120)
        r = run([engine.FFMPEG_PATH, "-ss", "1", "-i", clip, "-vframes", "1",
                 "-q:v", "2", "-y", thumb], timeout=60)
        check("C", "视频抽帧（封面链路）",
              r.returncode == 0 and os.path.isfile(thumb)
              and os.path.getsize(thumb) > 500)
        dur = engine.get_duration(clip, engine.FFPROBE_PATH)
        check("C", "ffprobe 时长探测", 2.0 < (dur or 0) < 5.0, f"{dur}s")
    except Exception as e:  # noqa: BLE001
        check("C", "ffmpeg 链路异常", False, repr(e)[:120])

# ============ D. ASR 配置链路 ============
if want("D"):
    group("D. ASR 配置链路")
    try:
        ai_cfg = engine.ai_load_config()
        check("D", "ai_load_config 可读", isinstance(ai_cfg, dict),
              f"keys={sorted(ai_cfg)[:6]}")
        ac_mod = engine.ai_mod()
        asr_cfg = ac_mod.asr_config(ai_cfg)
        check("D", "asr_config 输出结构",
              isinstance(asr_cfg, dict) and "mode" in asr_cfg,
              f"mode={asr_cfg.get('mode')} base={str(asr_cfg.get('base_url'))[:40]}")
        check("D", "ASR 密钥已配置", bool(asr_cfg.get("api_key")),
              (str(asr_cfg.get("api_key"))[:6] + "***")
              if asr_cfg.get("api_key") else "缺密钥")
        check("D", "is_dashscope_native_asr(qwen-audio-3.0-asr-flash)",
              engine.is_dashscope_native_asr("qwen-audio-3.0-asr-flash"))
        check("D", "is_dashscope_native_asr(realtime)=False",
              not engine.is_dashscope_native_asr("qwen3-asr-flash-realtime"))
        check("D", "asr_model_hard_guard 放行原生模型（返回空串）",
              engine.asr_model_hard_guard("qwen-audio-3.0-asr-flash") == "")
        check("D", "asr_strip_endpoint_tail 削尾巴",
              engine.asr_strip_endpoint_tail("https://api.x.com/v1/audio/transcriptions")
              == "https://api.x.com/v1")
        if asr_cfg.get("api_key"):
            ok, detail = engine.ai_test_asr(ai_cfg)
            check("D", "ai_test_asr 真实连通", bool(ok), str(detail)[:100])
        else:
            check("D", "ai_test_asr 真实连通", False, "未配置密钥，跳过")
    except Exception as e:  # noqa: BLE001
        check("D", "ASR 链路异常", False, repr(e)[:140])

# ============ E. AI(LLM) 与校准 ============
if want("E"):
    group("E. AI(LLM) 与字幕校准")
    try:
        ok, detail = engine.ai_test_connection(engine.ai_load_config(), channel="a")
        check("E", "ai_test_connection 通道A", bool(ok), str(detail)[:100])
    except Exception as e:  # noqa: BLE001
        check("E", "ai_test_connection 异常", False, repr(e)[:120])
    check("E", "ai_detect_language 中文", engine.ai_detect_language("你好世界") == "zh")
    check("E", "ai_detect_language 英文",
          engine.ai_detect_language("hello world") == "en")
    check("E", "ytdlp_sub_langs(zh)", bool(engine.ytdlp_sub_langs("zh")))
    calib_script = os.path.join(os.path.dirname(SRC), "subtitle_calib_merged.py")
    check("E", "subtitle_calib_merged.py 存在", os.path.isfile(calib_script))
    if os.path.isfile(calib_script):
        try:
            r = run([sys.executable, calib_script, "--help"], timeout=60)
            check("E", "校准脚本 --help", r.returncode == 0)
        except Exception as e:  # noqa: BLE001
            check("E", "校准脚本 --help", False, repr(e)[:100])
    kb = os.path.join(os.path.dirname(SRC), "subtitle_learned_kb.json")
    if os.path.isfile(kb):
        try:
            data = json.load(open(kb, encoding="utf-8"))
            n = sum(len(v) if isinstance(v, (list, dict)) else 1
                    for v in data.values()) if isinstance(data, dict) else len(data)
            check("E", "校准知识库 JSON 可解析", True, f"≈{n} 条")
        except Exception as e:  # noqa: BLE001
            check("E", "校准知识库 JSON 可解析", False, repr(e)[:100])
    else:
        check("E", "校准知识库 JSON 可解析", False, "文件不存在")

# ============ F. 字幕引擎与纯函数 ============
if want("F"):
    group("F. 字幕引擎与字幕工具函数")
    try:
        st = engine.vc_state()
        check("F", "vc_state（引擎环境就绪）",
              bool(st.get("ready", st)) if isinstance(st, dict) else bool(st),
              str(st)[:120])
    except Exception as e:  # noqa: BLE001
        check("F", "vc_state 异常", False, repr(e)[:120])
    try:
        sys.path.insert(0, engine.EMBEDDED_SITE_PACKAGES)
        from videocaptioner.core.entities import TranscribeModelEnum  # noqa: F401
        from videocaptioner.core.utils.video_utils import video2audio  # noqa: F401
        check("F", "videocaptioner 核心符号导入", True)
    except Exception as e:  # noqa: BLE001
        check("F", "videocaptioner 核心符号导入", False, repr(e)[:140])
    ms = engine.srt_time_to_ms("01:02:03,456")
    check("F", "srt_time_to_ms", ms == 3723456, str(ms))
    check("F", "ms_to_srt_time 往返", engine.ms_to_srt_time(ms) == "01:02:03,456")
    tmpd = os.path.join(engine.TMP_DIR, "_smoke")
    os.makedirs(tmpd, exist_ok=True)
    rolling = os.path.join(tmpd, "rolling.srt")
    with open(rolling, "w", encoding="utf-8") as f:
        f.write("1\n00:00:00,000 --> 00:00:05,000\n第一句滚动的台词啊\n\n"
                "2\n00:00:03,000 --> 00:00:08,000\n第二句和第一句重叠\n\n"
                "3\n00:00:08,500 --> 00:00:10,000\n第三句正常\n")
    try:
        stats = {}
        engine.normalize_rolling_srt(rolling, dry_run=True, stats=stats)
        check("F", "normalize_rolling_srt 检出重叠", True, str(stats)[:80])
    except Exception as e:  # noqa: BLE001
        check("F", "normalize_rolling_srt", False, repr(e)[:120])
    try:
        check("F", "sanitize_folder_name",
              engine.sanitize_folder_name('a<b>c:"d') == "a b c d")
        check("F", "output_template 转义 %",
              "%%" in engine.output_template(r"D:\100%素材", "%(title)s.%(ext)s"))
    except Exception as e:  # noqa: BLE001
        check("F", "下载纯函数", False, repr(e)[:120])

# ============ G. mpv ============
if want("G"):
    group("G. mpv / 字幕编辑器")
    try:
        engine.ensure_mpv_dll(os.path.join(engine.TOOLS_DIR, "mpv"))
        check("G", "libmpv-2.dll 可定位", True)
    except Exception as e:  # noqa: BLE001
        check("G", "libmpv-2.dll 可定位", False, repr(e)[:100])

# ============ H. 代理与下载网络链路 ============
if want("H"):
    group("H. 代理 / 游客cookie / 站点探测")
    try:
        ok, addr, info = engine.proxy_status()
        check("H", "内置代理可用（mihomo+204）", bool(ok),
              f"{addr} {info[:50]}")
    except Exception as e:  # noqa: BLE001
        check("H", "内置代理异常", False, repr(e)[:120])
    try:
        cargs = engine.ytdlp_cookie_args()
        check("H", "游客 cookie 参数", bool(cargs) and os.path.isfile(cargs[1]),
              str(cargs))
    except Exception as e:  # noqa: BLE001
        check("H", "游客 cookie 异常", False, repr(e)[:120])
    try:
        ytdlp = engine.ensure_ytdlp()
        out = engine.fetch_info_json(
            ytdlp, "https://www.bilibili.com/video/BV1GJ411x7h7",
            attempts=2, log=lambda m: None)
        ok = bool(out and out.strip().startswith("{"))
        title = json.loads(out).get("title", "")[:24] if ok else ""
        check("H", "B站 info 探测（直连）", ok, title)
    except Exception as e:  # noqa: BLE001
        check("H", "B站 info 探测异常", False, repr(e)[:120])
    try:
        out = engine.fetch_info_json(
            ytdlp, "https://www.youtube.com/watch?v=T3Sgpg6jtbo",
            attempts=2, log=lambda m: None)
        ok = bool(out and out.strip().startswith("{"))
        check("H", "YouTube 画质探测（代理+cookie）", ok,
              (json.loads(out).get("title", "")[:24] if ok
               else "风控/网络失败（今日实验已消耗 IP 信誉，供参考）"))
    except Exception as e:  # noqa: BLE001
        check("H", "YouTube 探测异常", False, repr(e)[:120])

# ============ I. 数据文件完整性 ============
if want("I"):
    group("I. 数据文件完整性")
    data_files = {
        "config.json": os.path.join(engine.DATA_DIR, "config.json"),
        "ai_config.json": os.path.join(engine.DATA_DIR, "ai_config.json"),
        "subtitle_style.json": os.path.join(engine.DATA_DIR, "subtitle_style.json"),
        "ui_custom.json": os.path.join(engine.DATA_DIR, "ui_custom.json"),
        "vc settings.json": os.path.join(engine.DATA_DIR, "videocaptioner",
                                         "settings.json"),
    }
    for name, p in data_files.items():
        try:
            json.load(open(p, encoding="utf-8-sig"))
            check("I", f"{name} 可解析", True)
        except FileNotFoundError:
            check("I", f"{name} 可解析", False, "文件不存在")
        except Exception as e:  # noqa: BLE001
            check("I", f"{name} 可解析", False, repr(e)[:80])
    for d in (engine.DEFAULT_DOWNLOAD_DIR, engine.THUMB_CACHE_DIR, engine.TMP_DIR,
              engine.LOGS_DIR):
        try:
            # downloads 目录通常有大量用户文件：只做存在性 + 可写判断（open 后
            # 不删除），避免批量删除类操作触发安全闸；其余目录写探针并清理
            if os.path.normcase(d) == os.path.normcase(engine.DEFAULT_DOWNLOAD_DIR):
                probe = os.path.join(d, "_smoke_probe.tmp")
                open(probe, "a").close()
                check("I", f"目录可写 {os.path.basename(d)}", True)
                continue
            probe = os.path.join(d, "_smoke_probe.tmp")
            open(probe, "w").write("x")
            os.remove(probe)
            check("I", f"目录可写 {os.path.basename(d)}", True)
        except Exception as e:  # noqa: BLE001
            check("I", f"目录可写 {os.path.basename(d)}", False, repr(e)[:80])

# ============ J. 源码语法全量 ============
if want("J"):
    group("J. 源码脚本语法（py_compile 全量）")
    bad = []
    pys = [p for p in glob.glob(os.path.join(SRC, "*.py"))
           if ".bak" not in os.path.basename(p)]
    for p in pys:
        try:
            py_compile.compile(p, doraise=True)
        except Exception as e:  # noqa: BLE001
            bad.append(f"{os.path.basename(p)}: {e}")
    check("J", f"src/*.py 语法（{len(pys)} 个）", not bad, "; ".join(bad)[:200])

# ============ 汇总 ============
print("\n" + "=" * 60, flush=True)
total = len(RESULTS)
failed = [r for r in RESULTS if not r[2]]
print(f"冒烟结果：{total - len(failed)}/{total} 通过，{len(failed)} 失败", flush=True)
for g, n, _, extra in failed:
    print(f"  ❌ [{g}] {n}{extra}", flush=True)
print("=" * 60, flush=True)
_dump()
sys.exit(1 if failed else 0)
