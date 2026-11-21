#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# @version 3.1.5
"""视频切片核心（V2.10.0 新增）：按「时间点」或「时长」把一个视频拆成多段。

本模块只依赖标准库 + ffmpeg，**不 import 任何 Qt**，因此 GUI（视频处理页的
「视频切片」子板块）与 CLI（`agent_cli split …`）共用同一套解析 / 执行 / 校验。

对外 API：
  · tokenize / classify         —— 拆词 + 判定「时间点」还是「时长」
  · parse_hms / parse_duration  —— 单个 token 解析（秒）
  · plan_split                  —— 生成切分方案（段列表 + 告警）
  · split_video                 —— 逐段切片（copy / encode / auto）+ 逐段校验
  · probe_media / verify_segment—— ffprobe / ffmpeg 探测与「能不能播」的校验

两条硬约束（2026-11-15 实测依据）：
  1. **切点**：`-c copy` 只能落在关键帧上，实际起点最多早于请求点一个 GOP
     （直播录像常见 2–10 秒）。`-avoid_negative_ts make_zero` 保证每段时间戳
     从 0 起——否则部分播放器/剪辑软件会把整段判成空或时间轴错乱。
  2. **可播**：每段产出都要过「结构校验（有视频流 + 时长对得上）+ 解码抽检
     （片头/片尾各 3 秒送空解码器）」。校验不过时 auto 模式自动改用 H.264/AAC
     重编码重做，保证「拆出来的每个视频都能正常播放」。

输入语法（同一份输入里两种语法不能混用）：
  · 时间点：`00:00:00, 01:00:00, 02:00:00`（HH:MM:SS；也接受 MM:SS）
            分隔符支持 逗号 / 中文逗号 / 分号 / 顿号 / 空格 / 换行
  · 时长：  `1h, 1h`、`1h30m`、`90m`、`2h5m30s`（h/m/s 亦可写 时/分/秒）
"""

import json
import os
import re
import subprocess
import threading

__version__ = "1.0.0"

#: 最短一段（秒）。小于这个值的切点直接判非法——一秒不到的碎片没有意义，
#: 且 copy 模式下根本落不到关键帧。
MIN_SEGMENT = 1.0

#: mp4 容器能「直接 copy」的视频 / 音频编码白名单。不在名单里的（vp8 / vorbis
#: 等）先退 MKV 无损封装，MKV 也失败再退重编码。
_MP4_VCODECS = {"h264", "hevc", "av1", "vp9", "mpeg4", "mpeg2video"}
_MP4_ACODECS = {"aac", "mp3", "ac3", "eac3", "alac"}

_DUR_RE = re.compile(
    r"^(?:(\d+(?:\.\d+)?)\s*(?:h|时|小时))?"
    r"(?:(\d+(?:\.\d+)?)\s*(?:m|分|分钟))?"
    r"(?:(\d+(?:\.\d+)?)\s*(?:s|秒))?$",
    re.I,
)

_SPLIT_RE = re.compile(r"[\s,，;；、|\n\r\t]+")


class SplitError(ValueError):
    """输入 / 方案层面的用户可见错误（GUI 直接弹提示，CLI 进 error 字段）。"""


# ============================================================
# 一、输入解析
# ============================================================
def tokenize(text):
    """把一整段输入拆成 token 列表（容忍各种分隔符与换行）。"""
    return [t for t in _SPLIT_RE.split((text or "").strip()) if t]


def parse_hms(token):
    """`HH:MM:SS`（也接受 `MM:SS` / `SS`）→ 秒（float）。"""
    raw = str(token).strip().replace("：", ":").replace("．", ".")
    if not raw:
        raise SplitError("时间点为空")
    parts = raw.split(":")
    if len(parts) > 3:
        raise SplitError("时间点格式不对：%s（应为 HH:MM:SS）" % token)
    try:
        nums = [float(p) if "." in p else int(p) for p in parts]
    except ValueError:
        raise SplitError("时间点格式不对：%s（应为 HH:MM:SS）" % token)
    while len(nums) < 3:
        nums.insert(0, 0)
    h, m, s = nums
    if h < 0 or m < 0 or s < 0:
        raise SplitError("时间点不能为负：%s" % token)
    if m >= 60 or s >= 60:
        raise SplitError("时间点越界：%s（分/秒必须 < 60）" % token)
    return float(h * 3600 + m * 60 + s)


def parse_duration(token):
    """`xHyMzS` → 秒（float）。至少带一个单位，纯数字不猜。"""
    raw = str(token).strip().replace("：", ":").replace("，", ",")
    if not raw:
        raise SplitError("时长片段为空")
    m = _DUR_RE.match(raw)
    if not m or not any(m.groups()):
        raise SplitError("时长格式不对：%s（应形如 1h / 30m / 1h30m / 45s）" % token)
    h, mi, se = (float(g) if g else 0.0 for g in m.groups())
    total = h * 3600 + mi * 60 + se
    if total <= 0:
        raise SplitError("时长必须大于 0：%s" % token)
    return total


def classify(tokens):
    """判定整份输入的语法：`points`（时间点）还是 `durations`（时长）。

    含冒号的一律按时间点解析；同一份输入混用两种语法 → 直接报错，避免
    「1h」被当成「1 秒」这种静默错拆。
    """
    if not tokens:
        raise SplitError("没有可解析的切分输入")
    has_colon = [(":" in t or "：" in t) for t in tokens]
    if all(has_colon):
        for t in tokens:
            parse_hms(t)                       # 逐个校验，坏的那个直接抛
        return "points"
    if not any(has_colon):
        for t in tokens:
            parse_duration(t)
        return "durations"
    bad = [t for t, c in zip(tokens, has_colon) if c][:1]
    raise SplitError(
        "同一份输入里不要混用两种语法（既有时间点 %s，又有 %s）；"
        "请统一成 HH:MM:SS 或 xHyMzS"
        % (bad[0], next(t for t, c in zip(tokens, has_colon) if not c)))


# ============================================================
# 二、切分方案
# ============================================================
def plan_split(duration, text, kind="auto"):
    """根据总时长与用户输入生成切分方案。

    参数：
      duration —— 源视频总时长（秒，probe_media 拿到）
      text     —— 用户输入原文（可多行）
      kind     —— `auto` / `points` / `durations`

    返回 dict：
      {"kind", "duration", "tokens", "segments":[
          {"index", "start", "end", "dur"} …], "warnings":[...]}
    """
    dur = float(duration or 0)
    if dur <= 0:
        raise SplitError("拿不到源视频时长（文件损坏或 ffprobe 不可用）")
    tokens = tokenize(text)
    mode = classify(tokens) if kind in ("auto", "", None) else kind
    if mode not in ("points", "durations"):
        raise SplitError("未知的切分方式：%s" % kind)

    warnings = []
    if mode == "points":
        raw = [round(parse_hms(t), 3) for t in tokens]
        points = sorted(set(raw))
        if len(raw) != len(set(raw)):
            warnings.append("有重复时间点，已合并：%d 个 → %d 个"
                            % (len(raw), len(points)))
        elif raw != points:
            # 写反了顺序不报错（用户只是随手罗列），但必须告知已重排，
            # 否则段表顺序和输入对不上，容易让人误以为切错了。
            warnings.append("时间点顺序写反了，已按由小到大重排")
        if points and points[0] <= 0:
            # 用户习惯把「00:00:00」也写进列表（章节编辑器就是这么举例的）：
            # 首段天然从 0 开始，这个点直接忽略，不当作错误。
            points = [p for p in points if p > 0]
            warnings.append("已忽略 00:00:00（首段天然从 0 开始）")
        if not points:
            raise SplitError("没有有效的切点（只剩 00:00:00 等于不拆）")
        for p in points:
            if p >= dur - MIN_SEGMENT:
                raise SplitError(
                    "时间点 %s 已到/超过片尾（片长 %s）" % (hms(p), hms(dur)))
        bounds = [0.0] + points + [dur]
        segs = []
        for i in range(len(bounds) - 1):
            s, e = bounds[i], bounds[i + 1]
            if e - s < MIN_SEGMENT - 1e-6:
                raise SplitError("第 %d 段只有 %.1f 秒（< %.0f 秒），"
                                 "切点挨得太近：%s"
                                 % (i + 1, e - s, MIN_SEGMENT, hms(s)))
            segs.append((s, e))
        warnings.append("按时间点切：%d 个切点 → %d 段" % (len(points), len(segs)))
    else:
        spans = [parse_duration(t) for t in tokens]
        segs, cursor = [], 0.0
        for i, d in enumerate(spans, 1):
            if d < MIN_SEGMENT:
                raise SplitError("第 %d 段只有 %.1f 秒（< %.0f 秒），"
                                 "时长太短：%s"
                                 % (i, d, MIN_SEGMENT, hms(d)))
            if cursor + d > dur + 0.5:
                raise SplitError(
                    "第 %d 段超出片长：累计需要 %s，片长只有 %s"
                    % (i, hms(cursor + d), hms(dur)))
            segs.append((cursor, cursor + d))
            cursor += d
        tail = dur - cursor
        if tail >= MIN_SEGMENT:
            segs.append((cursor, dur))
            warnings.append("时长合计 %s，片尾余 %s 已追加为第 %d 段"
                            % (hms(cursor), hms(tail), len(segs)))
        elif tail > 0.05:
            warnings.append("片尾余 %.2f 秒（< %.0f 秒）未单独成段"
                            % (tail, MIN_SEGMENT))

    out = [{"index": i + 1, "start": round(s, 3), "end": round(e, 3),
            "dur": round(e - s, 3)} for i, (s, e) in enumerate(segs)]
    if len(out) < 2:
        raise SplitError("只解析出 1 段——这不是拆分，请检查输入")
    return {"kind": mode, "duration": dur, "tokens": tokens,
            "segments": out, "warnings": warnings}


# ============================================================
# 三、探测与校验
# ============================================================
def probe_media(ffprobe, path):
    """ffprobe 探测：时长 / 视频编码 / 音频编码 / 分辨率 / 是否有音轨。"""
    cmd = [ffprobe, "-v", "error", "-show_entries",
           "format=duration:stream=codec_type,codec_name,width,height",
           "-of", "json", path]
    try:
        raw = subprocess.run(cmd, capture_output=True, text=True,
                             encoding="utf-8", errors="replace",
                             timeout=120, **_no_window()).stdout
        info = json.loads(raw or "{}")
    except Exception as e:  # noqa: BLE001
        raise SplitError("ffprobe 探测失败：%s（%s）" % (os.path.basename(path), e))
    streams = info.get("streams") or []
    v = next((s for s in streams if s.get("codec_type") == "video"), {})
    a = next((s for s in streams if s.get("codec_type") == "audio"), {})
    try:
        duration = float((info.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    return {
        "duration": duration,
        "vcodec": (v.get("codec_name") or "").lower(),
        "acodec": (a.get("codec_name") or "").lower(),
        "width": int(v.get("width") or 0),
        "height": int(v.get("height") or 0),
        "has_video": bool(v),
        "has_audio": bool(a),
    }


def verify_segment(ffmpeg, ffprobe, path, expect_seconds,
                   decode_head=3.0, decode_tail=3.0, full_decode=False,
                   tol=None):
    """校验一段产出「能不能正常播」，返回 (ok, report dict)。

    检查项：
      1. 存在且非空；2. 有视频流；3. 时长与期望差在容差内；
      4. 片头 / 片尾（或全片）送空解码器不报错。
    """
    rep = {"path": path, "issues": [], "duration": 0.0}
    if not os.path.isfile(path):
        rep["issues"].append("文件不存在")
        return False, rep
    size = os.path.getsize(path)
    rep["size"] = size
    if size < 1024:
        rep["issues"].append("文件过小（%d 字节），疑似空文件" % size)
        return False, rep
    try:
        media = probe_media(ffprobe, path)
    except SplitError as e:
        rep["issues"].append(str(e))
        return False, rep
    rep["duration"] = media["duration"]
    if not media["has_video"]:
        rep["issues"].append("没有视频流")
    if media["duration"] <= 0.2:
        rep["issues"].append("时长异常（%.2f 秒）" % media["duration"])
    if expect_seconds and tol is not None:
        delta = abs(media["duration"] - float(expect_seconds))
        rep["delta"] = round(delta, 2)
        if delta > tol:
            rep["issues"].append("时长偏差 %.2fs（期望 %.1fs，实际 %.1fs）"
                                 % (delta, expect_seconds, media["duration"]))
    # —— 解码抽检 ——
    checks = []
    if full_decode:
        checks.append([ffmpeg, "-v", "error", "-i", path, "-f", "null", "-"])
    else:
        if decode_head > 0:
            checks.append([ffmpeg, "-v", "error", "-t", str(decode_head),
                           "-i", path, "-f", "null", "-"])
        if decode_tail > 0:
            checks.append([ffmpeg, "-v", "error", "-sseof",
                           "-%s" % str(decode_tail), "-i", path,
                           "-f", "null", "-"])
    for cmd in checks:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               encoding="utf-8", errors="replace",
                               timeout=900, **_no_window())
        except Exception as e:  # noqa: BLE001
            rep["issues"].append("解码抽检异常：%s" % e)
            continue
        err = (r.stderr or "").strip()
        if r.returncode != 0 or err:
            rep["issues"].append("解码报错：%s" % err.splitlines()[-1][:160])
    rep["ok"] = not rep["issues"]
    return rep["ok"], rep


def _no_window():
    """Windows 下别让 ffmpeg 弹黑窗（GUI 线程里跑会闪一下）。"""
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


# ============================================================
# 四、执行
# ============================================================
def hms(seconds, frac=False):
    """秒 → `HH:MM:SS`（frac=True 时保留毫秒后两位）。"""
    s = max(0.0, float(seconds or 0))
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = s - h * 3600 - m * 60
    if frac:
        return "%02d:%02d:%05.2f" % (h, m, sec)
    return "%02d:%02d:%02d" % (h, m, int(round(sec)))


def stamp(seconds):
    """文件名用的时间戳：`01-00-00`（Windows 不接受冒号）。"""
    return hms(seconds).replace(":", "-")


def _fmt(sec):
    return ("%.3f" % max(0.0, float(sec))).rstrip("0").rstrip(".") or "0"


def _copy_cmd(ffmpeg, src, out, start, dur):
    return [ffmpeg, "-hide_banner", "-nostdin", "-v", "error",
            "-progress", "pipe:1", "-nostats",
            "-ss", _fmt(start), "-i", src, "-t", _fmt(dur),
            "-map", "0:v:0?", "-map", "0:a?",
            "-c", "copy", "-avoid_negative_ts", "make_zero",
            out]


def _encode_cmd(ffmpeg, src, out, start, dur):
    return [ffmpeg, "-hide_banner", "-nostdin", "-v", "error",
            "-progress", "pipe:1", "-nostats",
            "-ss", _fmt(start), "-i", src, "-t", _fmt(dur),
            "-map", "0:v:0?", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            out]


def _run_ffmpeg(cmd, total=None, on_pct=None, cancel=None):
    """跑 ffmpeg，边读 `-progress` 边回调百分比。返回 (rc, stderr_text)。"""
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True,
                             encoding="utf-8", errors="replace",
                             **_no_window())
    except OSError as e:
        return -1, "ffmpeg 启动失败：%s" % e
    err_lines = []

    def _drain():
        try:
            for line in p.stderr:
                err_lines.append(line)
        except Exception:  # noqa: BLE001
            pass

    t = threading.Thread(target=_drain, daemon=True)
    t.start()
    try:
        for line in p.stdout:
            if cancel is not None and cancel.is_set():
                p.kill()
                break
            if line.startswith("out_time_us="):
                try:
                    cur = int(line.split("=", 1)[1]) / 1e6
                except (ValueError, IndexError):
                    continue
                if total and total > 0 and on_pct:
                    on_pct(max(0.0, min(99.0, cur / float(total) * 100.0)))
        rc = p.wait()
    finally:
        t.join(timeout=2)
        try:
            p.stdout.close()
            p.stderr.close()
        except Exception:  # noqa: BLE001
            pass
    return rc, "".join(err_lines)


def _target_ext(info, prefer_mp4=True):
    """按编码白名单决定 copy 模式的容器后缀。"""
    if not prefer_mp4:
        return ".mkv"
    if info.get("vcodec") in _MP4_VCODECS and (
            not info.get("has_audio") or info.get("acodec") in _MP4_ACODECS):
        return ".mp4"
    return ".mkv"


def _unique(path):
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    i = 2
    while os.path.exists("%s_%d%s" % (stem, i, ext)):
        i += 1
    return "%s_%d%s" % (stem, i, ext)


def split_video(src, segments, out_dir, mode="auto", ffmpeg=None, ffprobe=None,
                on_event=None, cancel=None, verify_full=False, prefix=None):
    """逐段切片并逐段校验。

    参数：
      src      —— 源视频
      segments —— plan_split()["segments"]（或等价的 [(start, end)] 列表）
      out_dir  —— 输出目录（不存在会自动建）
      mode     —— `copy` 无损快切 / `encode` 精确重编码 / `auto` 先 copy 失败再重编码

    返回 dict：{"ok", "error", "outputs":[…], "warnings":[…], "duration"}
    每段输出带 `verified` / `mode` / `size` / `report`；任一段最终失败 → ok=False。
    """
    ffmpeg = ffmpeg or "ffmpeg"
    ffprobe = ffprobe or "ffprobe"
    src = os.path.abspath(src)
    if not os.path.isfile(src):
        raise SplitError("源视频不存在：%s" % src)
    segs = []
    for s in segments:
        if isinstance(s, dict):
            segs.append((float(s["start"]), float(s["end"])))
        else:
            segs.append((float(s[0]), float(s[1])))
    if not segs:
        raise SplitError("没有切分方案")

    def _emit(kind, payload=None):
        if on_event:
            try:
                on_event(kind, payload)
            except Exception:  # noqa: BLE001
                pass

    info = probe_media(ffprobe, src)
    if not info["has_video"]:
        raise SplitError("源文件没有视频流：%s" % os.path.basename(src))
    total = info["duration"] or 0.0

    os.makedirs(out_dir, exist_ok=True)
    base = prefix or os.path.splitext(os.path.basename(src))[0]
    outputs, warnings, failed = [], [], []
    n = len(segs)
    _emit("log", ("[信息] 源：%s（%s，%s MB）"
                  % (os.path.basename(src), hms(total),
                     "%.0f" % (os.path.getsize(src) / 1048576)), "dim"))
    _emit("log", ("[信息] 切分方式 %s，共 %d 段"
                  % ("无损快切" if mode == "copy" else
                     ("精确重编码" if mode == "encode" else "自动"),
                     n), "dim"))

    for i, (start, end) in enumerate(segs, 1):
        seg_dur = max(0.05, end - start)
        tag = "第 %d/%d 段" % (i, n)
        if cancel is not None and cancel.is_set():
            warnings.append("用户中止于第 %d 段" % i)
            break
        _emit("log", ("[进行] %s：%s → %s（%s）"
                      % (tag, hms(start, True), hms(end, True), hms(seg_dur)), "dim"))

        def _pct(p):
            _emit("progress", ((i - 1) + min(1.0, p / 100.0)) / n * 100.0)

        produced = None       # (path, mode_used, report)
        tried = []

        def _attempt(copy_mode, ext):
            out = _unique(os.path.join(
                out_dir, "%s_part%02d_%s-%s%s"
                % (base, i, stamp(start), stamp(end), ext)))
            cmd = (_copy_cmd(ffmpeg, src, out, start, seg_dur) if copy_mode
                   else _encode_cmd(ffmpeg, src, out, start, seg_dur))
            rc, err = _run_ffmpeg(cmd, total=seg_dur, on_pct=_pct, cancel=cancel)
            mode_used = "copy" if copy_mode else "encode"
            if rc != 0:
                tried.append("%s/%s 失败：%s"
                             % (mode_used, ext, (err or "").strip().splitlines()[-1][:140]
                                if err else "rc=%d" % rc))
                try:
                    if os.path.isfile(out) and os.path.getsize(out) < 1024:
                        os.remove(out)
                except OSError:
                    pass
                return None
            tol = max(1.5, min(5.0, seg_dur * 0.01)) if mode_used == "copy" else 1.0
            ok, rep = verify_segment(ffmpeg, ffprobe, out, seg_dur,
                                     full_decode=verify_full, tol=tol)
            if ok:
                return (out, mode_used, rep)
            tried.append("%s/%s 校验不过：%s"
                         % (mode_used, ext, "；".join(rep["issues"])[:160]))
            try:
                os.remove(out)
            except OSError:
                pass
            return None

        if mode in ("copy", "auto"):
            produced = _attempt(True, _target_ext(info))
            if not produced and _target_ext(info) == ".mp4":
                # mp4 装不下（字幕流 / 罕见编码）→ 先试 MKV 无损封装
                _emit("log", ("[信息] %s：mp4 封装不成，改试 MKV 无损" % tag, "dim"))
                produced = _attempt(True, ".mkv")
        if not produced and mode in ("auto", "encode"):
            _emit("log", ("[信息] %s：改走 H.264/AAC 重编码（会慢，但切点精确）" % tag, "dim"))
            produced = _attempt(False, ".mp4")

        if not produced:
            failed.append({"index": i, "start": start, "end": end,
                           "error": "；".join(tried)[:400]})
            _emit("log", ("[X] %s 失败：%s" % (tag, "；".join(tried)[:200]), "err"))
            continue

        path, used, rep = produced
        outputs.append({
            "index": i, "path": path, "mode": used,
            "start": round(start, 3), "end": round(end, 3),
            "seconds": rep.get("duration", seg_dur),
            "size": rep.get("size", os.path.getsize(path)),
            "verified": True,
        })
        _emit("log", ("[完成] %s → %s（%s，%s）"
                      % (tag, os.path.basename(path),
                         hms(rep.get("duration", seg_dur)),
                         "%0.1f MB" % (rep.get("size", 0) / 1048576)), "ok"))
        _emit("progress", (i / n) * 100.0)

    result = {"ok": not failed, "duration": total,
              "outputs": outputs, "warnings": warnings,
              "failed": failed, "source": src, "out_dir": out_dir}
    if failed:
        result["error"] = ("%d/%d 段未能产出可播放文件：%s"
                           % (len(failed), n, failed[0]["error"]))
    return result


def summarize(result):
    """把 split_video 的结果整理成一句人读摘要（GUI 日志 / CLI 共用）。"""
    if not result:
        return "无结果"
    outs = result.get("outputs") or []
    total = sum(o.get("seconds") or 0 for o in outs)
    size = sum(o.get("size") or 0 for o in outs)
    return ("%d 段 / 合计 %s / %0.1f MB"
            % (len(outs), hms(total), size / 1048576))
