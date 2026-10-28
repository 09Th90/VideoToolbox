# @version 2.8.0
"""音视频工具（自研，替代 videocaptioner.core.utils.video_utils 的公开面）。

可观察契约
----------
* :func:`video2audio` —— ffmpeg 提音频：``-map 0:a:{音轨序号} -vn -ac 1
  -ar 16000``，成功且文件落盘才返回 True；
* :func:`probe_video_info` —— 媒体探测，产出 :class:`VideoInfo`
  （纯音频文件视频类字段为 0；探测失败返回 ``None`` 而非抛异常）；
* :func:`extract_thumbnail` —— 30% 时长处截一帧（引擎同款时间点）；
* :func:`check_cuda_available` —— ffmpeg hwaccels + 设备初始化双检。

与引擎的有意分歧（记录在案，避免后人"对齐"回去）
------------------------------------------------
引擎的 ``AudioStreamInfo.index`` 存**文件内绝对流号**，而
``video2audio(audio_track_index)`` 的语义是 ``0:a:N`` 的**音频序数**——
多音轨文件下二者不一致（单音轨文件都是 0，恰好掩盖）。本模块统一为
音频序数：``probe_video_info`` 产出的 ``index`` 可直接喂给
``video2audio``，自洽优先。二进制定位走显式解析
（环境变量 → 随包 tools → PATH），不依赖引擎 import 期的 PATH 注入。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

from vt_engine.entities import AudioStreamInfo, VideoInfo
from vt_engine.log import setup_logger

logger = setup_logger("vt_engine.media")

__all__ = [
    "find_ffmpeg",
    "find_ffprobe",
    "video2audio",
    "probe_video_info",
    "extract_thumbnail",
    "check_cuda_available",
]


def _tools_dir() -> str:
    """随包 tools 目录（ffmpeg/ffprobe 所在）。"""
    try:
        from vt_engine.paths import default_engine_paths
        return str(default_engine_paths().bin_path)
    except Exception:  # noqa: BLE001
        return ""


def find_ffmpeg() -> Optional[str]:
    """定位 ffmpeg：环境变量 → 随包 tools → PATH。"""
    for key in ("VT_FFMPEG", "FFMPEG_PATH"):
        v = (os.environ.get(key) or "").strip().strip('"')
        if v and os.path.isfile(v):
            return v
    cand = os.path.join(_tools_dir(), "ffmpeg.exe")
    if os.path.isfile(cand):
        return cand
    return shutil.which("ffmpeg")


def find_ffprobe() -> Optional[str]:
    """定位 ffprobe：环境变量 → 随包 tools → PATH → ffmpeg 同目录替换名。"""
    for key in ("VT_FFPROBE", "FFPROBE_PATH"):
        v = (os.environ.get(key) or "").strip().strip('"')
        if v and os.path.isfile(v):
            return v
    cand = os.path.join(_tools_dir(), "ffprobe.exe")
    if os.path.isfile(cand):
        return cand
    found = shutil.which("ffprobe")
    if found:
        return found
    ff = find_ffmpeg()
    if ff:
        sibling = os.path.join(os.path.dirname(ff),
                               "ffprobe.exe" if os.name == "nt"
                               else "ffprobe")
        if os.path.isfile(sibling):
            return sibling
    return None


def _popen_kwargs() -> dict:
    """Windows 下不弹黑窗。"""
    if os.name == "nt":
        return {"creationflags": getattr(
            subprocess, "CREATE_NO_WINDOW", 0)}
    return {}


def video2audio(input_file: str, output: str = "",
                audio_track_index: int = 0) -> bool:
    """视频提音频（16kHz 单声道 wav，ASR 标准输入）。

    ``audio_track_index`` 为**音频序数**（0 = 第一条音频流），与
    :func:`probe_video_info` 产出的 ``AudioStreamInfo.index`` 同语义。
    成功条件：ffmpeg 返回码 0 **且**输出文件真实存在——早年的实现只
    看返回码，ffmpeg 个别失败路径仍返回 0，会产出 0 字节音频让 ASR
    报看不懂的错。
    """
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        logger.error("未找到 ffmpeg，无法提取音频")
        return False
    if not os.path.isfile(input_file):
        logger.error("输入文件不存在: %s", input_file)
        return False
    if not output:
        # 与引擎一致：默认落输入文件同目录同名 .wav
        output = str(Path(input_file).with_suffix(".wav"))
    out_path = Path(output)
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.error("无法创建输出目录: %s", out_path.parent)
        return False

    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error",
           "-i", input_file,
           "-map", "0:a:%d" % max(0, int(audio_track_index or 0)),
           "-vn", "-ac", "1", "-ar", "16000", "-y", output]
    try:
        result = subprocess.run(cmd, capture_output=True, check=False,
                                encoding="utf-8", errors="replace",
                                timeout=1800, **_popen_kwargs())
    except subprocess.TimeoutExpired:
        logger.error("音频提取超时（30 分钟）: %s", input_file)
        return False
    except Exception as e:  # noqa: BLE001
        logger.exception("音频提取出错: %s", e)
        return False
    if result.returncode == 0 and Path(output).is_file() \
            and Path(output).stat().st_size > 0:
        return True
    logger.error("音频提取失败 (rc=%s): %s",
                 result.returncode,
                 (result.stderr or "")[-500:])
    return False


#: ffprobe JSON 探测的超时（秒）。
_PROBE_TIMEOUT = 60


def _ffprobe_json(ffprobe: str, path: str) -> Optional[dict]:
    cmd = [ffprobe, "-v", "error", "-print_format", "json",
           "-show_streams", "-show_format", path]
    try:
        r = subprocess.run(cmd, capture_output=True, check=False,
                           encoding="utf-8", errors="replace",
                           timeout=_PROBE_TIMEOUT, **_popen_kwargs())
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.error("ffprobe 执行失败: %s", e)
        return None
    if r.returncode != 0:
        logger.error("ffprobe 返回 %s: %s", r.returncode,
                     (r.stderr or "")[-300:])
        return None
    try:
        return json.loads(r.stdout or "{}")
    except ValueError:
        logger.error("ffprobe 输出不是 JSON")
        return None


def _fps_from(rate) -> float:
    """``"30000/1001"`` / ``"29.97"`` → float。解析失败返回 0。"""
    if not rate:
        return 0.0
    try:
        if "/" in str(rate):
            num, den = str(rate).split("/", 1)
            den_f = float(den)
            return float(num) / den_f if den_f else 0.0
        return float(rate)
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def probe_video_info(file_path: str,
                     thumbnail_path: str = "") -> Optional[VideoInfo]:
    """探测媒体信息（ffprobe JSON，失败返回 None 不抛异常）。

    纯音频文件：视频类字段（width/height/fps/video_codec）为 0/空；
    ``audio_streams`` 只收录音频流，``index`` 为**音频序数**（0 起），
    可直接喂 :func:`video2audio`。
    """
    ffprobe = find_ffprobe()
    if not ffprobe:
        logger.error("未找到 ffprobe，无法探测媒体信息")
        return None
    if not os.path.isfile(file_path):
        logger.error("文件不存在: %s", file_path)
        return None
    data = _ffprobe_json(ffprobe, file_path)
    if not data:
        return None

    streams = data.get("streams") or []
    fmt = data.get("format") or {}
    video = next((s for s in streams
                  if s.get("codec_type") == "video"), None)
    audios = [s for s in streams if s.get("codec_type") == "audio"]
    if video is None and not audios:
        logger.error("文件没有视频/音频流: %s", file_path)
        return None

    width = int(video.get("width") or 0) if video else 0
    height = int(video.get("height") or 0) if video else 0
    fps = _fps_from(video.get("avg_frame_rate")) if video else 0.0
    video_codec = (video.get("codec_name") or "") if video else ""
    try:
        duration_seconds = float(fmt.get("duration") or 0.0)
    except (TypeError, ValueError):
        duration_seconds = 0.0
    try:
        bitrate_kbps = int(round(float(fmt.get("bitrate") or 0) / 1000.0))
    except (TypeError, ValueError):
        bitrate_kbps = 0

    first_audio = audios[0] if audios else None
    audio_codec = (first_audio.get("codec_name") or "") if first_audio else ""
    try:
        audio_sampling_rate = int((first_audio.get("sample_rate") or 0)) \
            if first_audio else 0
    except (TypeError, ValueError):
        audio_sampling_rate = 0

    audio_streams: List[AudioStreamInfo] = []
    for ordinal, s in enumerate(audios):
        tags = s.get("tags") or {}
        audio_streams.append(AudioStreamInfo(
            index=ordinal,
            codec=s.get("codec_name") or "",
            language=tags.get("language") or tags.get("LANGUAGE") or "",
            title=tags.get("title") or tags.get("TITLE") or "",
        ))

    final_thumbnail = ""
    if thumbnail_path and duration_seconds > 0 and video is not None:
        if extract_thumbnail(file_path, duration_seconds * 0.3,
                             thumbnail_path):
            final_thumbnail = thumbnail_path

    return VideoInfo(
        file_name=Path(file_path).stem,
        file_path=file_path,
        width=width,
        height=height,
        fps=fps,
        duration_seconds=duration_seconds,
        bitrate_kbps=bitrate_kbps,
        video_codec=video_codec,
        audio_codec=audio_codec,
        audio_sampling_rate=audio_sampling_rate,
        thumbnail_path=final_thumbnail,
        audio_streams=audio_streams,
    )


def extract_thumbnail(video_path: str, seek_time: float,
                      thumbnail_path: str) -> bool:
    """截一帧存为缩略图（引擎同款 30% 时间点、同款 q:v 2 质量）。"""
    ffmpeg = find_ffmpeg()
    if not ffmpeg or not os.path.isfile(video_path):
        return False
    timestamp = "%02d:%02d:%06.3f" % (
        int(seek_time // 3600), int((seek_time % 3600) // 60),
        seek_time % 60)
    try:
        Path(thumbnail_path).parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(
            [ffmpeg, "-hide_banner", "-loglevel", "error",
             "-ss", timestamp, "-i", Path(video_path).as_posix(),
             "-vframes", "1", "-q:v", "2", "-y",
             Path(thumbnail_path).as_posix()],
            capture_output=True, check=False, encoding="utf-8",
            errors="replace", timeout=120, **_popen_kwargs())
    except Exception as e:  # noqa: BLE001
        logger.exception("提取缩略图出错: %s", e)
        return False
    return r.returncode == 0 and Path(thumbnail_path).is_file()


def check_cuda_available() -> bool:
    """CUDA 可用性：ffmpeg hwaccels 列表含 cuda 且设备初始化无错误输出。"""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        return False
    try:
        r = subprocess.run([ffmpeg, "-hwaccels"], capture_output=True,
                           check=False, encoding="utf-8", errors="replace",
                           timeout=30, **_popen_kwargs())
        if "cuda" not in (r.stdout or "").lower():
            return False
        r2 = subprocess.run([ffmpeg, "-hide_banner", "-init_hw_device",
                             "cuda"], capture_output=True, check=False,
                            encoding="utf-8", errors="replace",
                            timeout=30, **_popen_kwargs())
        err = (r2.stderr or "").lower()
        if any(x in err for x in ("cannot load cuda", "failed to load",
                                  "error")):
            return False
        return True
    except Exception as e:  # noqa: BLE001
        logger.exception("CUDA 检查出错: %s", e)
        return False
