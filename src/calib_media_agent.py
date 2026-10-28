# -*- coding: utf-8 -*-
# @version 2.8.0
"""校准 Agent 的音画证据工具（2026-10-12 新增）。

定位
====
AI 校准 Agent（calib_ai_agent）此前只有两条证据腿：注入的术语知识库与
`calib_web_agent` 的联网查证。对标 FineSub（downloads/finesub v0.5.1）
的多模态纠错 harness，本模块补上第三条腿——**音频/画面证据**：

  · `audio_evidence(start, end)`：按 cue 时间轴从源媒体裁一段音频
    （前后各留 padding），走 OpenAI 兼容 `/audio/transcriptions`
    **重转写**，把「第二模型在这段音频里听到了什么」作为只读证据回填
    ——FineSub「第二模型否决/确认」的平价替代；
  · `frame_evidence(start, end)`：同区间等间隔抽帧（默认 0.25fps 思路，
    上限 4 帧、≤720p），走视觉通道描述画面文字/界面/场景。

设计约束（与 calib_web_agent 一致）
====================================
* 零第三方依赖：ffmpeg 子进程裁切 + urllib multipart POST；
* 只读证据：本模块只返回文本，采纳与否仍由 calib_ai_agent 的证据校验
  与模型判断把关，绝不参与写盘/回填；
* 失败降级：无 ffmpeg / 无 ASR 配置 / 协议不兼容 / 网络异常，全部返回
  「证据获取失败：…」文本（与联网查证同一降级哲学），主流程绝不被打断；
* 进程内缓存：同一区间不重复裁切/请求。

协议门控：只有 OpenAI 兼容（whisper 系 multipart）ASR 端点会被调用；
realtime / dashscope 原生 / deepgram 等异构协议由引擎层解析后传
`protocol != "openai"` 进来，本模块直接返回不可用文本，不做猜测性请求。

证据规则（prompt 侧，MEDIA_TOOL_NOTE 与之同构，源自 FineSub
fragment_corr_role_audio / fragment_evidence_pack_usage）：
  1. 证据只读，可能出错——采信前与 ASR 文本、知识库交叉验证；
  2. 「听成了什么」以音频证据为准（可推翻前置结论），但知识库沉淀的
     固定译名与设定不由听觉裁决；
  3. 画面文字只是证据，不是字幕——不为画面上出现、但未说出的文字输出内容；
  4. 证据与知识库冲突时不静默取舍，把冲突写进 reason；
  5. `[unresolved]` 式的不确定内容禁止当作确定事实。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request

#: 单次裁切前后各留的 padding（秒）。FineSub 常规窗口用 5s，但那是给
#: 几十秒的整窗口；cue 级证据取 2s 足够覆盖首尾呼吸。
CLIP_PAD_SECONDS = 2.0
#: 单段证据音频时长上限（秒），超出按上限截取（防误传整片）。
MAX_CLIP_SECONDS = 60.0
#: 抽帧参数：0.25fps 思路（FineSub VIDEO_SAMPLE_FPS），上限 4 帧。
FRAME_FPS = 0.25
MAX_FRAMES = 4
#: 抽帧缩放：短边 720（FineSub scale=-2:720 同思路）。
FRAME_MAX_HEIGHT = 720
#: ASR 重转写请求超时（秒）——整段音频上传+识别比对话慢。
ASR_TIMEOUT = 90

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

#: 画面证据的视觉提问词（FineSub fragment_corr_role_video 的证据化改写）：
# 画面只作证据、不是字幕；不推测未说出口的内容。
FRAME_PROMPT = (
    "以下是字幕校验的画面证据。下面的图片来自同一个时间区间的等间隔采样。"
    "请只描述画面上可见的、可能与字幕内容相关的信息：屏幕上的文字"
    "（UI、标题、人名条、系统提示、对话字幕）、场景与角色、明显的界面状态。"
    "逐条列出，不要推测主播没有说出口的内容；不要因为画面上有文字就认为它"
    "被念了出来——画面文字只是证据，不是字幕。若画面与字幕明显无关或无法"
    "辨认，直接说明。"
)


# ============================ ffmpeg 原语 ============================

def _ffmpeg_bin(ffmpeg=None):
    if ffmpeg and os.path.isfile(str(ffmpeg)):
        return str(ffmpeg)
    found = shutil.which("ffmpeg")
    if found:
        return found
    return None


def _run_ffmpeg(ffmpeg, args, timeout):
    cmd = [ffmpeg, "-v", "error", "-nostdin"] + args
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                           timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise RuntimeError("ffmpeg 调用失败：%s" % e)
    if p.returncode != 0:
        msg = (p.stderr or b"").decode("utf-8", "replace").strip()[:200]
        raise RuntimeError("ffmpeg 退出 %d：%s" % (p.returncode, msg))
    return p.stdout


def extract_audio_segment(media_path, start, end, ffmpeg=None, pad=CLIP_PAD_SECONDS):
    """裁 [start-pad, end+pad] 的 16k 单声道 MP3 字节（evidence 用）。"""
    ff = _ffmpeg_bin(ffmpeg)
    if not ff:
        raise RuntimeError("未找到 ffmpeg")
    s = max(0.0, float(start) - pad)
    e = float(end) + pad
    if e - s > MAX_CLIP_SECONDS:
        e = s + MAX_CLIP_SECONDS
    if e <= s:
        raise RuntimeError("区间无效：%s ~ %s" % (start, end))
    return _run_ffmpeg(ff, [
        "-ss", "%.3f" % s, "-to", "%.3f" % e, "-i", str(media_path),
        "-vn", "-sn", "-dn", "-ac", "1", "-ar", "16000",
        "-b:a", "64k", "-f", "mp3", "-",
    ], timeout=max(30, int(e - s) * 2 + 30))


def extract_frames(media_path, start, end, ffmpeg=None, pad=CLIP_PAD_SECONDS,
                   fps=FRAME_FPS, max_frames=MAX_FRAMES,
                   max_height=FRAME_MAX_HEIGHT):
    """同区间等间隔抽帧 → PNG 字节列表（至少 1 帧，至多 max_frames）。"""
    ff = _ffmpeg_bin(ffmpeg)
    if not ff:
        raise RuntimeError("未找到 ffmpeg")
    s = max(0.0, float(start) - pad)
    e = float(end) + pad
    if e - s > MAX_CLIP_SECONDS:
        e = s + MAX_CLIP_SECONDS
    if e <= s:
        raise RuntimeError("区间无效：%s ~ %s" % (start, end))
    dur = e - s
    count = max(1, min(max_frames, int(round(dur * fps)) or 1))
    frames = []
    for k in range(count):
        # 帧中心时刻：均匀铺在 [s, e] 上（首末不贴边，留半格）
        offset = s + dur * (k + 0.5) / count
        png = _run_ffmpeg(ff, [
            "-ss", "%.3f" % offset, "-i", str(media_path),
            "-frames:v", "1", "-vf", "scale=-2:%d" % max_height,
            "-f", "image2", "-c:v", "png", "-",
        ], timeout=60)
        if png:
            frames.append(png)
    return frames


# ============================ ASR 重转写 ============================

def asr_url(base):
    """OpenAI 兼容 ASR 地址归一化（与 tools/ai_client._asr_url 同规则）。"""
    b = (base or "").rstrip("/")
    if not b:
        return ""
    if b.endswith("/audio/transcriptions"):
        return b
    tail = b.rsplit("/", 1)[-1].lower()
    if tail.startswith("v") and tail[1:2].isdigit():
        return b + "/audio/transcriptions"
    return b + "/v1/audio/transcriptions"


def _multipart_post(url, fields, files, api_key, timeout):
    """零依赖 multipart/form-data POST。files: [(字段名, 文件名, 字节, MIME)]。"""
    boundary = "----finesubEvidence%d" % (time.time() * 1000)
    body = bytearray()
    for name, value in fields:
        body += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n"
                 % (boundary, name, value)).encode("utf-8")
    for name, filename, data, mime in files:
        body += ("--%s\r\nContent-Disposition: form-data; name=\"%s\"; "
                 "filename=\"%s\"\r\nContent-Type: %s\r\n\r\n"
                 % (boundary, name, filename, mime)).encode("utf-8")
        body += data
        body += b"\r\n"
    body += ("--%s--\r\n" % boundary).encode("utf-8")
    req = urllib.request.Request(url, data=bytes(body), method="POST")
    req.add_header("Content-Type", "multipart/form-data; boundary=%s" % boundary)
    req.add_header("User-Agent", _UA)
    if api_key:
        req.add_header("Authorization", "Bearer %s" % api_key)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def transcribe_audio(asr, audio_bytes, timeout=ASR_TIMEOUT):
    """OpenAI 兼容 /audio/transcriptions 重转写 → 文本。

    asr: {"base_url","api_key","model","protocol","language","prompt"}；
    protocol 必须是 "openai"（引擎层解析后传入），否则抛错由调用方降级。
    """
    base = str(asr.get("base_url") or "").strip()
    key = str(asr.get("api_key") or "").strip()
    model = str(asr.get("model") or "").strip()
    if not base or not key or not model:
        raise RuntimeError("ASR 配置不完整（base_url/api_key/model）")
    if str(asr.get("protocol") or "").strip().lower() not in ("openai", ""):
        raise RuntimeError("ASR 协议 %r 非 OpenAI 兼容 multipart，证据工具不代请求"
                           % asr.get("protocol"))
    url = asr_url(base)
    fields = {"model": model, "response_format": "json"}
    lang = str(asr.get("language") or "").strip()
    if lang:
        fields["language"] = lang
    prompt = str(asr.get("prompt") or "").strip()
    if prompt:
        fields["prompt"] = prompt
    raw = _multipart_post(url, list(fields.items()),
                          [("file", "evidence.mp3", audio_bytes, "audio/mpeg")],
                          key, timeout)
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
        text = str(data.get("text") or "").strip()
    except ValueError:
        text = raw.decode("utf-8", "replace").strip()
    if not text:
        raise RuntimeError("ASR 返回空文本")
    return text


# ============================ 对外工具工厂 ============================

def make_tools(media_path, *, asr=None, vision=None, ffmpeg=None, log=None,
               pad=CLIP_PAD_SECONDS, timeout=ASR_TIMEOUT):
    """返回 {"audio_evidence": fn(start, end) -> str,
            "frame_evidence":  fn(start, end) -> str}。

    media_path  源视频/音频路径（ffmpeg 能解码即可）；None/不存在 → 两个
                工具都返回不可用文本（行为与旧版离线一致）。
    asr          ai_client.asr_config() 产物（protocol 已由引擎层解析）；
                 None 或协议不兼容 → 音频证据不可用。
    vision       callable(prompt, images: list[bytes|path]) -> str
                 （如 AIClient.chat_vision 绑定方法）；None → 画面证据不可用。
    ffmpeg       ffmpeg 路径；None 时先查 media_path 同族 tools 目录、再 PATH。
    log          可选日志回调 log(msg, level="dim")。
    """
    cache = {}
    lock = threading.Lock()
    _log = log or (lambda m, level="dim": None)
    media_ok = bool(media_path) and os.path.isfile(str(media_path))

    def _note(msg):
        try:
            _log(msg, "dim")
        except TypeError:
            _log(msg)

    def _cached(key, fn):
        with lock:
            if key in cache:
                return cache[key]
        try:
            text = fn()
        except Exception as e:  # noqa: BLE001 —— 证据失败绝不打断校准主流程
            text = "证据获取失败：%s: %s" % (type(e).__name__, e)
        with lock:
            cache[key] = text
        return text

    def audio_evidence(start, end):
        start, end = float(start or 0), float(end or 0)
        if not media_ok:
            return "音频证据不可用：未提供源媒体文件（%r）。" % (media_path,)
        if not asr:
            return "音频证据不可用：未配置 ASR 服务。"
        if str(asr.get("protocol") or "").strip().lower() not in ("openai", ""):
            return ("音频证据不可用：ASR 协议 %r 非 OpenAI 兼容 multipart。"
                    % asr.get("protocol"))
        key = ("a", round(start, 1), round(end, 1))
        if key in cache:
            return cache[key]

        def _go():
            audio = extract_audio_segment(media_path, start, end, ffmpeg=ffmpeg, pad=pad)
            text = transcribe_audio(asr, audio, timeout=timeout)
            return ("【音频证据（第二模型重转写 %s ~ %s，只读）】\n%s\n"
                    "（重转写可能出错：采信前与 ASR 文本、知识库交叉验证；"
                    "「听成了什么」以此为准，知识库固定译名不由听觉裁决。）"
                    % (_fmt(start), _fmt(end), text))

        return _cached(key, _go)

    def frame_evidence(start, end):
        start, end = float(start or 0), float(end or 0)
        if not media_ok:
            return "画面证据不可用：未提供源媒体文件（%r）。" % (media_path,)
        if not vision:
            return "画面证据不可用：未配置视觉通道。"
        key = ("f", round(start, 1), round(end, 1))

        def _go():
            frames = extract_frames(media_path, start, end, ffmpeg=ffmpeg, pad=pad)
            if not frames:
                raise RuntimeError("未抽到帧（区间无画面或解码失败）")
            desc = vision(FRAME_PROMPT, frames)
            desc = str(desc or "").strip()
            if not desc:
                raise RuntimeError("视觉通道返回空描述")
            return ("【画面证据（%s ~ %s，%d 帧，只读）】\n%s\n"
                    "（画面文字只是证据，不是字幕：不要为画面上出现、"
                    "但主播没有说出的文字输出内容。）"
                    % (_fmt(start), _fmt(end), len(frames), desc))

        return _cached(key, _go)

    return {"audio_evidence": audio_evidence, "frame_evidence": frame_evidence}


def _fmt(sec):
    sec = max(0.0, float(sec))
    m, s = divmod(int(sec), 60)
    return "%02d:%05.2f" % (m, s)


if __name__ == "__main__":  # 手工连通性小样（不走缓存，仅调试用）
    _tools = make_tools(os.environ.get("VT_MEDIA") or None)
    print(_tools["audio_evidence"](0, 5))
