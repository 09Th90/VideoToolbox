# -*- coding: utf-8 -*-
# @version 1.17.0
"""音频复核法 · 通用探针（2026-10-07 沉淀自终末地「塔卫二：一号简报」反应片校准）

用途：字幕与英文参考行都不可信时，用**原片音频**定案。
      截取指定时段 → 百炼原生 ASR（qwen-audio-3.0-asr-flash）→ 打印真实文本。
      遇到「官方有中文配音」的预告片/宣传片，往往能直接吐回**官方中文文案**。

依赖：tools/python/python.exe（含 requests）、tools/ffmpeg.exe、data/ai_config.json。
用法：
  # 按 SRT 的 cue 号（可给区间）复核
  python scripts/dev/asr_probe.py --video 原片.mp4 --srt 字幕.srt 91 94-96 190-191
  # 按秒数滑窗全片扫（step 秒一段）
  python scripts/dev/asr_probe.py --video 原片.mp4 --sec 0 1084 30
说明：国内端点用 proxies={} 直连；无语音片段回 HTTP 400 空体属正常。
"""
import argparse
import base64
import json
import os
import re
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
FFMPEG = os.path.join(ROOT, "tools", "ffmpeg.exe")
NATIVE_PATH = "/api/v1/services/aigc/multimodal-generation/generation"


def load_cfg(path=None):
    with open(path or os.path.join(ROOT, "data", "ai_config.json"), encoding="utf-8") as f:
        return json.load(f)


def native_url(base):
    b = (base or "").strip().rstrip("/")
    if b.lower().endswith(NATIVE_PATH.lower()):
        return b
    if "//" in b:
        scheme, rest = b.split("//", 1)
        return scheme + "//" + rest.split("/", 1)[0] + NATIVE_PATH
    return "https://" + b.split("/", 1)[0] + NATIVE_PATH


def parse_srt(path):
    raw = open(path, "rb").read().decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    out = {}
    for m in re.finditer(r"(?m)^(\d+)\n(\d\d):(\d\d):(\d\d),(\d+) --> (\d\d):(\d\d):(\d\d),(\d+)\s*$", raw):
        n = int(m.group(1))
        st = int(m.group(2)) * 3600 + int(m.group(3)) * 60 + int(m.group(4)) + int(m.group(5)) / 1000.0
        ed = int(m.group(6)) * 3600 + int(m.group(7)) * 60 + int(m.group(8)) + int(m.group(9)) / 1000.0
        out[n] = (st, ed)
    return out


def cut_wav(video, st, ed, out):
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-ss", "%.3f" % st, "-to", "%.3f" % ed,
                    "-i", video, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", out], check=True)


def asr(cfg, wav):
    import requests
    blob = open(wav, "rb").read()
    body = {"model": cfg.get("asr_model", "qwen-audio-3.0-asr-flash"),
            "input": {"messages": [{"role": "user", "content": [
                {"type": "input_audio", "input_audio": {
                    "data": "data:audio/wav;base64," + base64.b64encode(blob).decode("ascii")}}]}]},
            "parameters": {"format": "wav", "sample_rate": "16000"}}
    r = requests.post(native_url(cfg.get("asr_base_url", "")), json=body,
                      headers={"Authorization": "Bearer " + cfg.get("asr_api_key", ""),
                               "Content-Type": "application/json"}, proxies={}, timeout=600)
    if r.status_code != 200:
        return "HTTP %s %s" % (r.status_code, (r.text or "")[:200])
    d = r.json()
    if isinstance(d, dict) and isinstance(d.get("text"), str):
        return d["text"]
    try:
        node = d["output"]["choices"][0]["message"]["content"][0]
        return node.get("text") if isinstance(node, dict) else str(node)
    except Exception:
        return json.dumps(d, ensure_ascii=False)[:600]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--srt")
    ap.add_argument("--sec", nargs=3, metavar=("A", "B", "STEP"))
    ap.add_argument("--config")
    ap.add_argument("cues", nargs="*")
    a = ap.parse_args()
    cfg = load_cfg(a.config)
    tmp = os.path.join(os.path.dirname(os.path.abspath(a.video)), "_probe_tmp")
    os.makedirs(tmp, exist_ok=True)

    def run(st, ed, tag):
        wav = os.path.join(tmp, "_clip_%s.wav" % tag)
        cut_wav(a.video, st, ed, wav)
        print("### %s  %.3f-%.3f  (%.1fs)" % (tag, st, ed, ed - st), flush=True)
        print(asr(cfg, wav), flush=True)

    if a.sec:
        t, b, step = float(a.sec[0]), float(a.sec[1]), float(a.sec[2])
        while t < b:
            run(t, min(t + step, b), "%d" % int(t))
            t += step
        return
    cues = parse_srt(a.srt)
    for spec in a.cues:
        if "-" in spec:
            x, y = spec.split("-")
            run(cues[int(x)][0], cues[int(y)][1], spec)
        else:
            run(*cues[int(spec)], spec)


if __name__ == "__main__":
    sys.exit(main())
