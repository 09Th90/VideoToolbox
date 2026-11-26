# -*- coding: utf-8 -*-
# @version 3.3.1
"""PCM 归一、数字增益与能量 VAD 分段（源：vt-web-server/itxw/audio.py）。

约定输入：16 kHz / 单声道 / 16-bit little-endian，帧长 100 ms（3200 字节）。
本模块不落盘；写 WAV 仅在调用方显式 debug 或引擎请求时使用。
"""
from __future__ import annotations

import array
import io
import math
import wave
from dataclasses import dataclass


@dataclass(frozen=True)
class Segment:
    """一段完整语音，PCM 不可变，供云端/本地后端共用同一份输入。"""
    seq: int
    pcm: bytes
    t0_ms: int
    created: float
    interim: bool = False

    @property
    def duration_s(self) -> float:
        return len(self.pcm) / 32000.0

    @property
    def duration_ms(self) -> int:
        return int(round(self.duration_s * 1000))


def frame_bytes(sample_rate: int = 16000, frame_ms: int = 100) -> int:
    return int(sample_rate * frame_ms / 1000) * 2


def rms(pcm: bytes) -> float:
    if not pcm:
        return 0.0
    a = array.array("h")
    a.frombytes(pcm[: len(pcm) // 2 * 2])
    if not a:
        return 0.0
    total = 0.0
    for v in a:
        total += float(v) * float(v)
    return math.sqrt(total / len(a))


def amplify(pcm: bytes, gain: float) -> bytes:
    """硬削波数字增益。ITX 原版固定 8x；这里可配置，无 AGC。"""
    if gain == 1.0 or not pcm:
        return pcm
    a = array.array("h")
    a.frombytes(pcm[: len(pcm) // 2 * 2])
    for i, v in enumerate(a):
        n = int(v * gain)
        a[i] = 32767 if n > 32767 else (-32768 if n < -32768 else n)
    return a.tobytes()


def to_wav(pcm: bytes, sample_rate: int = 16000) -> bytes:
    """内存中封装 WAV，供云端 Data URL / 本地 multipart POST 使用。"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return buf.getvalue()


def write_wav(path, pcm: bytes, sample_rate: int = 16000) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)


class VAD:
    """能量门限 VAD：静音收尾 / 最长分段 / 预滚，行为与 ITX live.py 一致。

    阈值 = max(vad_min_rms, noise * noise_ratio)，噪声底仅在非说话期以
    0.995/0.005 缓慢自适应（时间常数约 20 s）。
    """

    def __init__(self, audio_cfg: dict):
        self.sample_rate = int(audio_cfg.get("sample_rate", 16000))
        self.frame_ms = int(audio_cfg.get("frame_ms", 100))
        self.frame_size = frame_bytes(self.sample_rate, self.frame_ms)
        self.gain = float(audio_cfg.get("gain", 8.0))
        self.min_rms = float(audio_cfg.get("vad_min_rms", 110))
        self.noise_ratio = float(audio_cfg.get("noise_ratio", 2.2))
        self.silence_ms = int(audio_cfg.get("silence_ms", 400))
        self.max_segment_ms = int(audio_cfg.get("max_segment_ms", 5000))
        self.min_speech_ms = int(audio_cfg.get("min_speech_ms", 400))
        self.preroll_ms = int(audio_cfg.get("preroll_ms", 300))
        self.interim_enabled = bool(audio_cfg.get("interim_enabled", True))
        self.interim_interval_ms = int(audio_cfg.get("interim_interval_ms", 2000))
        self.reset()

    def reset(self) -> None:
        self.noise = 200.0
        self.speaking = False
        self.segment = bytearray()
        self.preroll = bytearray()
        self.silence_ms_elapsed = 0
        self.speech_ms_elapsed = 0
        self.last_speech_len = 0
        self.peak = 0.0
        self._interim_sent_ms = 0

    @property
    def preroll_bytes(self) -> int:
        return int(self.preroll_ms / self.frame_ms) * self.frame_size

    def process_frame(self, raw: bytes) -> bytes:
        """接收一帧原始 PCM，返回放大后的等长帧。"""
        if len(raw) != self.frame_size:
            raw = raw.ljust(self.frame_size, b"\x00")[: self.frame_size]
        return amplify(raw, self.gain)

    def poll_interim(self) -> bytes | None:
        """说话期间累积音频的快照，供预识别先出字；切掉尾部静音。

        每累计 interim_interval_ms 语音触发一次；关闭或未达阈值返回 None。
        快照与最终段共用同一 seq，终版到达后按 seq 覆盖。
        """
        if not self.interim_enabled or not self.speaking:
            return None
        if self.speech_ms_elapsed - self._interim_sent_ms < self.interim_interval_ms:
            return None
        self._interim_sent_ms = self.speech_ms_elapsed
        return bytes(self.segment[:self.last_speech_len])

    def feed(self, frame: bytes) -> bytes | None:
        """输入已放大的一帧；返回完整语音段或 None。"""
        level = rms(frame)
        self.peak = max(self.peak, level)
        if not self.speaking:
            self.noise = min(self.noise * 0.995 + level * 0.005, 4000.0)
        threshold = max(self.min_rms, self.noise * self.noise_ratio)
        is_speech = level > threshold

        if not self.speaking:
            self.preroll += frame
            cap = self.preroll_bytes
            if len(self.preroll) > cap:
                del self.preroll[: len(self.preroll) - cap]
            if is_speech:
                self.speaking = True
                self.segment = bytearray(self.preroll)
                self.last_speech_len = len(self.segment)
                self.speech_ms_elapsed = self.frame_ms
                self.silence_ms_elapsed = 0
            return None

        self.segment += frame
        if is_speech:
            self.speech_ms_elapsed += self.frame_ms
            self.silence_ms_elapsed = 0
            self.last_speech_len = len(self.segment)
        else:
            self.silence_ms_elapsed += self.frame_ms

        seg_ms = len(self.segment) * 1000 // (self.sample_rate * 2)
        done = ((self.silence_ms_elapsed >= self.silence_ms
                 and self.speech_ms_elapsed >= self.min_speech_ms)
                or seg_ms >= self.max_segment_ms)
        if not done:
            return None

        # 保留尾部 100 ms，丢掉多余静音
        cut = min(len(self.segment), self.last_speech_len + self.frame_size)
        seg = bytes(self.segment[:cut])
        self.speaking = False
        self.segment = bytearray()
        self.preroll = bytearray()
        self.silence_ms_elapsed = 0
        self.speech_ms_elapsed = 0
        self.last_speech_len = 0
        self._interim_sent_ms = 0
        return seg

    def stats(self) -> dict:
        return {"peak": round(self.peak, 1), "noise": round(self.noise, 1),
                "speaking": self.speaking}
