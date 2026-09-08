#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ASR 字幕生成 worker（由工具箱内置运行时以子进程运行）。

工具箱完全自包含：不依赖任何外部 ASR 程序。本脚本由工具箱内嵌解释器
（tools\\python\\python.exe）以子进程运行，faster-whisper 运行时与模型均
内嵌在工具箱内，模型用工具箱自带的 large-v3-turbo。

通过 stdout 协议与 GUI 通信：
    @@PROGRESS {"pct": 12.3, "chunk": 2, "chunks": 5}
    @@LOG     {"msg": "..."}
    @@DONE    {"srt": "...", "segments": 123}
    @@ERROR   {"msg": "..."}
其余 stdout 输出一律视为日志。

转写流程（长视频内存恒定）：
  1. ffprobe 取总时长；
  2. 逐块用 ffmpeg 抽 16kHz 单声道 wav（-ss/-t，块间重叠 OVERLAP 秒），
     任意时刻内存中只有一块音频；
  3. 每块 faster-whisper 转写（VAD 过滤静音），段时间戳加块偏移回全局；
     重叠区去重：丢弃起始落在上一块已覆盖区的段；
  4. GPU(float16) 优先，失败自动回退 CPU(int8)；
  5. 完成写 SRT（utf-8）到 --out。
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile


CHUNK_SEC = 600      # 每块 10 分钟
OVERLAP = 2.0        # 块间重叠秒数，防止句首/句尾被切断


def emit(kind, **data):
    print(f"@@{kind} {json.dumps(data, ensure_ascii=False)}", flush=True)


def log(msg):
    emit("LOG", msg=msg)


def run_ffmpeg(bin_path, args, timeout=600):
    cmd = [bin_path, "-hide_banner", "-loglevel", "error", "-y", *args]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg 失败: {(r.stderr or '').strip()[-400:]}")
    return r


def probe_duration(ffprobe, video):
    r = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=duration",
         "-of", "json", video],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe 失败: {(r.stderr or '').strip()[-300:]}")
    return float(json.loads(r.stdout or "{}").get("format", {}).get("duration") or 0)


def fmt_ts(t):
    if t < 0:
        t = 0
    ms = int(round(t * 1000))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def pick_compute_type(model_dir):
    """GPU float16 优先；加载失败回退 CPU int8。返回 (model, compute_type 描述)"""
    from faster_whisper import WhisperModel
    try:
        m = WhisperModel(model_dir, device="cuda", compute_type="float16")
        return m, "CUDA float16"
    except Exception as e:
        log(f"GPU 初始化失败，改用 CPU int8：{str(e)[:200]}")
    return WhisperModel(model_dir, device="cpu", compute_type="int8"), "CPU int8"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--ffmpeg", required=True)
    ap.add_argument("--ffprobe", required=True)
    ap.add_argument("--language", default="")   # 空 = 自动检测
    args = ap.parse_args()

    if not os.path.isfile(args.video):
        emit("ERROR", msg=f"视频不存在: {args.video}")
        return 1
    if not os.path.isdir(args.model) or not os.path.isfile(
            os.path.join(args.model, "model.bin")):
        emit("ERROR", msg=f"模型目录无效（缺 model.bin）: {args.model}")
        return 1

    total = probe_duration(args.ffprobe, args.video)
    if total <= 0:
        emit("ERROR", msg="无法读取视频时长")
        return 1

    log(f"加载 Whisper 模型（large-v3-turbo）…")
    model, dev = pick_compute_type(args.model)
    log(f"识别引擎就绪：{dev}；总时长 {int(total // 60)} 分 {int(total % 60)} 秒")

    lang = None if (args.language or "").strip().lower() in ("", "auto") else args.language
    tmpdir = tempfile.mkdtemp(prefix="vtasr_")
    segments_out = []
    done_sec = 0.0
    step = CHUNK_SEC
    idx = 0
    chunks = max(1, int((total - 1) // step) + 1)
    prev_covered_until = 0.0    # 重叠去重：全局时间轴上已确认覆盖的终点

    try:
        while done_sec < total - 0.01:
            idx += 1
            span = min(step + OVERLAP, total - done_sec)
            wav = os.path.join(tmpdir, f"chunk_{idx}.wav")
            run_ffmpeg(args.ffmpeg,
                       ["-ss", f"{done_sec:.3f}", "-t", f"{span:.3f}",
                        "-i", args.video, "-vn", "-ac", "1", "-ar", "16000",
                        "-f", "wav", wav])
            segs, info = model.transcribe(
                wav, language=lang, vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 500},
                beam_size=5, condition_on_previous_text=False)
            kept = 0
            for s in segs:
                abs_start = done_sec + s.start
                abs_end = done_sec + s.end
                if abs_start < prev_covered_until - 0.01:
                    continue          # 落在与上一块的重叠区，丢弃
                abs_end = min(abs_end, done_sec + span - OVERLAP
                              if done_sec + span < total else abs_end)
                text = (s.text or "").strip()
                if not text:
                    continue
                segments_out.append((abs_start, abs_end, text))
                kept += 1
                # 块内段级进度
                pct = min(99.0, (done_sec + s.end) / total * 100.0)
                emit("PROGRESS", pct=round(pct, 1), chunk=idx, chunks=chunks)
            prev_covered_until = done_sec + span - OVERLAP
            done_sec += step
            try:
                os.remove(wav)
            except OSError:
                pass
            emit("PROGRESS", pct=round(min(99.0, done_sec / total * 100.0), 1),
                 chunk=idx, chunks=chunks)

        with open(args.out, "w", encoding="utf-8-sig") as f:
            for i, (a, b, text) in enumerate(segments_out, 1):
                f.write(f"{i}\n{fmt_ts(a)} --> {fmt_ts(b)}\n{text}\n\n")
        emit("DONE", srt=args.out, segments=len(segments_out))
        return 0
    except Exception as e:
        emit("ERROR", msg=str(e))
        return 1
    finally:
        try:
            for n in os.listdir(tmpdir):
                os.remove(os.path.join(tmpdir, n))
            os.rmdir(tmpdir)
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
