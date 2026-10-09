# -*- coding: utf-8 -*-
# @version 1.18.0
"""主播声纹：本地声纹录入 + 字幕筛选（无 Qt，可脱离界面单测）。

把「只出主播的字幕」做成本地**后处理**：
    音频/视频 + 带说话人标注的 SRT  ->  只保留主播的 SRT

为什么必须在本地做：服务端 ASR 只回 `[说话人N]` 标签，既不给声纹向量、
也不回传音频片段，无法在云端判定「谁是主播」。所以这里用本地声纹模型
把每个说话人簇的音频提成向量，与用户录入的主播模板算余弦相似度。

依赖：**onnxruntime + numpy（项目均已内置）**，特征提取是纯 numpy 实现的
kaldi 兼容 fbank，不引入任何新的第三方包。

模型：`tools/asr_model/3dspeaker_speech_campplus_sv_zh-cn_16k-common.onnx`
      3D-Speaker CAM++（中文，16k，输出 192 维），约 27MB，由
      `tools/download_open_source_deps.py --only speaker-model` 下载。

用法（命令行，便于脱离界面验证）：
    python speaker_voiceprint.py enroll --src 视频.mp4 --start 12 --dur 20 --name 主播
    python speaker_voiceprint.py list                     # 列出已录入（x = 已启用）
    python speaker_voiceprint.py use 主播,嘉宾            # 启用多个声纹（并集）
    python speaker_voiceprint.py delete 主播
    python speaker_voiceprint.py score  --src 视频.mp4 --srt 字幕.srt --name 主播,嘉宾
    python speaker_voiceprint.py filter --src 视频.mp4 --srt 字幕.srt --name 主播,嘉宾 \
                                        --threshold 0.5 --out 主播.srt

多声纹是**并集**语义：一条 cue 只要与其中任意一个声纹够像就算「主播」，
对应「一档节目有两位主播 / 常驻嘉宾也算」这类场景。启用名单单独落
`data/voiceprint/selection.json`（**刻意不写进 `data/ai_config.json`**——
那个文件由设置页 `_collect_ai()` 整份重写，未进 schema 的键会被静默丢弃）。
"""
import argparse
import json
import os
import subprocess
import sys
import time
import wave

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import subtitle_editor_core as secore  # noqa: E402

# ---------------------------------------------------------------- 路径 / 常量


def _resolve_dirs():
    """定位 tools / data 两个目录。

    ⚠⚠ **必须优先用引擎（`video_toolbox`）的常量**，别自己按 `__file__` 推层级。
    引擎那套同时处理了三种情形：
      ① 源码运行（本文件在 `APP_DIR\\src` 下）；
      ② **打包后**（`sys.frozen` ⇒ `APP_DIR = exe 所在目录`，而不是 PyInstaller
         onefile 的 `_MEIPASS` 临时解压目录）；
      ③ 用户在「设置 → 工具设置 → 数据目录」改过数据根（`data_dir.txt` 指针）
         或设了 `VT_DATA_ROOT`。
    自己推层级在打包后**必错**：onefile 把模块解压到 `%TEMP%\\_MEIxxxx`，
    算出来的 tools 就成了 `%TEMP%\\tools` —— 表现是「声纹模型缺失：C:\\Users\\
    …\\Temp\\tools\\asr_model\\…」，而且模板会落到 C 盘临时目录、退出即丢。

    引擎导入失败时才回落自算（口径与引擎保持一致，勿改语义）。
    """
    try:
        import video_toolbox as _e
        return _e.TOOLS_DIR, _e.DATA_DIR
    except Exception:  # noqa: BLE001
        pass
    if getattr(sys, "frozen", False):
        app = os.path.dirname(os.path.abspath(sys.executable))
    else:
        app = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tools = os.path.join(app, "tools")
    if not os.path.isdir(tools):        # 直接跑构建产物时向上找（同引擎口径）
        d = app
        for _ in range(5):
            cand = os.path.join(d, "tools")
            if os.path.isdir(cand):
                tools = cand
                break
            parent = os.path.dirname(d)
            if parent == d:
                break
            d = parent
    root = (os.environ.get("VT_DATA_ROOT") or "").strip().strip('"') or app
    return tools, os.path.join(os.path.abspath(root), "data")


TOOLS_DIR, DATA_DIR = _resolve_dirs()

#: 声纹模型目录（与安装包 `{app}\tools\asr_model` 一致）
MODEL_DIR = os.path.join(TOOLS_DIR, "asr_model")
MODEL_NAME = "3dspeaker_speech_campplus_sv_zh-cn_16k-common.onnx"
MODEL_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/"
             "speaker-recongition-models/" + MODEL_NAME)
#: 模型 sha256 由 download_open_source_deps.py 在下载后就地校验（不落 .sha256）
MODEL_PATH = os.path.join(MODEL_DIR, MODEL_NAME)

#: 声纹模板落盘目录（用户数据，不进安装包）
TEMPLATE_DIR = os.path.join(DATA_DIR, "voiceprint")

FFMPEG = os.path.join(TOOLS_DIR, "ffmpeg.exe")
FFPROBE = os.path.join(TOOLS_DIR, "ffprobe.exe")

SAMPLE_RATE = 16000
FRAME_LENGTH_MS = 25.0
FRAME_SHIFT_MS = 10.0
NUM_BINS = 80
LOW_FREQ = 20.0
HIGH_FREQ = -400.0          # <=0 表示「奈奎斯特 - 该值」，即 8000-400=7600Hz
PREEMPH_COEFF = 0.97
DITHER = 0.0
EMB_DIM = 192

#: 判定阈值。CAM++ 中文实测（3 位说话人 14 条样本）：
#: 同人余弦 **min 0.681** / mean 0.784，异人 **max 0.450** / mean 0.174。
#: 决策边界取两者中点 ≈ 0.566，**向上取整到 0.55**。
DEFAULT_THRESHOLD = 0.55
#: 「存疑区」下界。**取异人相似度的实测上限 0.450**——低于它就基本可以断定
#: 「不是主播」，没必要再留。
#: ⚠ 这个值最初拍成 0.35（凭感觉留宽一点），实测踩坑：真实素材里
#: 「游戏官方中文旁白」聚成一簇、相似度 **0.390**，正好落进 [0.35,0.55) 的
#: 存疑区被**保留**，用户看到的就是「依旧多人混合输出」（164 秒旁白没筛掉）。
#: 教训：存疑区要**窄**且**贴着决策边界**，不能一路宽到"看起来还行"。
DEFAULT_LOW = 0.45


class VoiceprintError(RuntimeError):
    """声纹链路可预期的失败（模型缺失、ffmpeg 缺失、音频读不出等）。"""


# ---------------------------------------------------------------- 模型下载
#: 模型 sha256（与 tools/download_open_source_deps.py 的 SPEAKER_MODEL_SHA256 一致）
MODEL_SHA256 = ("f682b514c05d947ee3fa91cd6ec6c5c7543479a128373fa29b1f"
                "aedccd21fd11")


def model_present():
    """模型是否已就位（存在且非空）。"""
    try:
        return os.path.getsize(MODEL_PATH) > 0
    except OSError:
        return False


def download_model(progress=None, timeout=300, force=False,
                   stall_seconds=20.0):
    """把声纹模型下到 `TOOLS_DIR\\asr_model\\`。

    `progress(done, total)` 每读一块回调一次（total 可能为 0 = 未知）；返回
    模型绝对路径。

    取源顺序（**为什么不照搬 `download_open_source_deps.py` 的"直连失败才用代理"**）：
      ① **内置 mihomo 已在运行** → 直接用它。GitHub release 直连实测 190KB/s
         （27MB 要 125~155 秒），走代理 3.3MB/s（8 秒），差一个数量级；而
         "已在运行"是瞬时探测（0.3s 连一下 7897 端口），不触发 mihomo 启动。
      ② 直连。
      ③ 前面都失败 → 拉起内置 mihomo 再试一次。
    ⚠ 试过"速率太慢就切代理"，**弃用**：实测直连慢时代理也可能慢，
    切换反而把总耗时从 125s 拖到 155s。按"谁已经在跑"取源比按速率猜稳。

    另保留 `stall_seconds` 秒收不到任何数据的兜底（防连接挂死）。

    ⚠ 落盘位置只认 `MODEL_PATH`（= 引擎解析出的 tools 目录，打包后在 exe 同级），
    **不会写 C 盘**。先写 `.part` 再 `os.replace`，中断不留半截文件。
    """
    import hashlib
    import urllib.request

    if model_present() and not force:
        return MODEL_PATH
    os.makedirs(MODEL_DIR, exist_ok=True)
    tmp = MODEL_PATH + ".part"
    req = urllib.request.Request(MODEL_URL,
                                 headers={"User-Agent": "VideoToolbox/1.18"})

    def _opener(proxy):
        if not proxy:
            return None
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy}))

    def _fetch(proxy=None):
        op = _opener(proxy)
        resp = (op.open(req, timeout=timeout) if op is not None
                else urllib.request.urlopen(req, timeout=timeout))
        started = time.time()
        with resp:
            total = int(resp.headers.get("Content-Length") or 0)
            got = 0
            with open(tmp, "wb") as fh:
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    fh.write(chunk)
                    got += len(chunk)
                    if progress:
                        try:
                            progress(got, total)
                        except Exception:  # noqa: BLE001
                            pass
                    if got < (1 << 16) and time.time() - started > stall_seconds:
                        raise VoiceprintError(
                            "连接 %d 秒仍无数据（%s）"
                            % (stall_seconds, "代理" if proxy else "直连"))

    def _cleanup():
        try:
            os.remove(tmp)
        except OSError:
            pass

    def _proxy_if_up():
        """内置代理**已经在跑**才返回地址；不触发启动（瞬时探测）。"""
        import socket
        for port in (7897,):
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                    return "http://127.0.0.1:%d" % port
            except OSError:
                pass
        return None

    running = _proxy_if_up()
    tried = [("代理（已在运行）", running)] if running else []
    tried.append(("直连", None))
    last = None
    ok = False
    for label, px in tried:
        try:
            _fetch(px)
            ok = True
            break
        except Exception as e:  # noqa: BLE001
            last = (label, e)
            _cleanup()

    if not ok:
        px = None
        try:
            import video_toolbox as _e
            px = _e.ensure_builtin_proxy()
        except Exception:  # noqa: BLE001
            px = None
        if not px:
            raise VoiceprintError(
                "下载失败（%s：%s）；内置代理也不可用，可手动下载后放到 %s"
                % (last[0] if last else "直连",
                   str(last[1])[:120] if last else "未知", MODEL_DIR))
        try:
            _fetch(px)
            ok = True
        except Exception as e:  # noqa: BLE001
            _cleanup()
            raise VoiceprintError(
                "下载失败（%s：%s / 内置代理：%s）"
                % (last[0] if last else "直连",
                   str(last[1])[:80] if last else "未知", str(e)[:80]))

    got = hashlib.sha256(open(tmp, "rb").read()).hexdigest()
    if got != MODEL_SHA256:
        _cleanup()
        raise VoiceprintError("模型校验不一致（期望 %s…，实际 %s…），已丢弃"
                              % (MODEL_SHA256[:12], got[:12]))
    os.replace(tmp, MODEL_PATH)
    return MODEL_PATH


# ---------------------------------------------------------------- 音频读取


def find_ffmpeg():
    """返回可用的 ffmpeg 路径（优先随包 tools/ffmpeg.exe，其次 PATH）。"""
    if os.path.isfile(FFMPEG):
        return FFMPEG
    from shutil import which
    found = which("ffmpeg")
    if found:
        return found
    raise VoiceprintError("未找到 ffmpeg（%s），请先运行 "
                          "tools/download_open_source_deps.py --only ffmpeg" % FFMPEG)


def read_pcm(src, sample_rate=SAMPLE_RATE, start=None, dur=None):
    """把音频/视频解码成 16k 单声道 float32（[-1,1]），返回 numpy 数组。

    `start`/`dur` 单位为秒，用于只取片段（录入声纹时截一段即可）。
    一次性解码整段再切片，比逐条 cue 各调一次 ffmpeg 快得多。
    """
    ff = find_ffmpeg()
    cmd = [ff, "-v", "error", "-nostdin"]
    if start:
        cmd += ["-ss", "%.3f" % float(start)]
    cmd += ["-i", str(src)]
    if dur:
        cmd += ["-t", "%.3f" % float(dur)]
    cmd += ["-vn", "-sn", "-dn", "-ac", "1", "-ar", str(sample_rate),
            "-f", "s16le", "-acodec", "pcm_s16le", "-"]
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except OSError as e:
        raise VoiceprintError("调用 ffmpeg 失败：%s" % e)
    if p.returncode != 0:
        msg = (p.stderr or b"").decode("utf-8", "replace").strip()[:300]
        raise VoiceprintError("ffmpeg 解码失败（%s）：%s" % (p.returncode, msg))
    if not p.stdout:
        raise VoiceprintError("ffmpeg 未输出音频：%s" % src)
    return np.frombuffer(p.stdout, dtype="<i2").astype(np.float32) / 32768.0


def read_wav_mono(path, sample_rate=SAMPLE_RATE):
    """直接读 16k 单声道 PCM wav（测试与已解码素材用，不依赖 ffmpeg）。"""
    with wave.open(str(path), "rb") as w:
        n_ch, sw, sr = w.getnchannels(), w.getsampwidth(), w.getframerate()
        raw = w.readframes(w.getnframes())
    if sw == 2:
        a = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    elif sw == 4:
        a = np.frombuffer(raw, dtype="<i4").astype(np.float32) / 2147483648.0
    elif sw == 1:
        a = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        raise VoiceprintError("不支持的采样位宽：%d" % sw)
    if n_ch > 1:
        a = a.reshape(-1, n_ch).mean(axis=1)
    if sr != sample_rate:
        a = resample_linear(a, sr, sample_rate)
    return a


def resample_linear(x, src_rate, dst_rate):
    """线性插值重采样。

    仅在读 wav 且采样率不符时兜底；ffmpeg 路径已按目标采样率解码，
    正常流程不会走到这里。声纹对重采样质量不敏感（fbank 会做平滑）。
    """
    if src_rate == dst_rate or len(x) == 0:
        return x
    n_out = int(round(len(x) * float(dst_rate) / float(src_rate)))
    idx = np.arange(n_out, dtype=np.float64) * (float(src_rate) / float(dst_rate))
    i0 = np.floor(idx).astype(np.int64)
    i1 = np.minimum(i0 + 1, len(x) - 1)
    frac = (idx - i0).astype(np.float32)
    return (x[i0] * (1.0 - frac) + x[i1] * frac).astype(np.float32)


# ---------------------------------------------------------------- fbank 特征
# 纯 numpy 复刻 kaldi 的 fbank（kaldi-native-fbank / sherpa-onnx 同源）。
# 参数取自 sherpa-onnx `FeatureExtractorConfig` 默认值（见 features.h）：
#   snip_edges=False, frame 25/10ms, remove_dc_offset=True, preemph=0.97,
#   window_type="povey", round_to_power_of_two=True, num_bins=80,
#   low_freq=20, high_freq=-400(=7600Hz), use_energy=False, use_log_fbank=True,
#   use_power=True。模型元数据 normalize_samples=1 -> 波形保持在 [-1,1]。
# 窗口用 povey 而非 hamming：实测 povey 的同人/异人间隔更大（0.231 vs 0.221）。

_POVEY_CACHE = {}


def _povey_window(n):
    w = _POVEY_CACHE.get(n)
    if w is None:
        i = np.arange(n, dtype=np.float64)
        a = 2.0 * np.pi / (n - 1)
        w = np.power(0.5 - 0.5 * np.cos(a * i), 0.85).astype(np.float32)
        _POVEY_CACHE[n] = w
    return w


def _mel_scale(f):
    """kaldi 的 mel 刻度：1127 * ln(1 + f/700)（非 librosa/slaney 版本）。"""
    return 1127.0 * np.log(1.0 + np.asarray(f, dtype=np.float64) / 700.0)


def _mel_filterbank(num_bins=NUM_BINS, sample_rate=SAMPLE_RATE,
                    n_fft=512, low_freq=LOW_FREQ, high_freq=HIGH_FREQ):
    """kaldi 风格三角 mel 滤波器组 -> (num_bins, n_fft//2+1) 稀疏权重矩阵。

    kaldi 不做带宽归一化（is_librosa=False），故此处直接返回三角权重。
    """
    num_fft_bins = n_fft // 2 + 1
    fft_bin_width = float(sample_rate) / float(n_fft)
    hi = (sample_rate / 2.0 + high_freq) if high_freq <= 0 else high_freq
    mel_low = float(_mel_scale(low_freq))
    mel_high = float(_mel_scale(hi))
    delta = (mel_high - mel_low) / float(num_bins + 1)
    freqs = fft_bin_width * np.arange(num_fft_bins, dtype=np.float64)
    mel = _mel_scale(freqs)
    mat = np.zeros((num_bins, num_fft_bins), dtype=np.float32)
    for b in range(num_bins):
        left = mel_low + b * delta
        center = mel_low + (b + 1) * delta
        right = mel_low + (b + 2) * delta
        up = (mel > left) & (mel < center)
        dn = (mel >= center) & (mel < right)
        if center > left:
            mat[b, up] = ((mel[up] - left) / (center - left)).astype(np.float32)
        if right > center:
            mat[b, dn] = ((right - mel[dn]) / (right - center)).astype(np.float32)
    return mat


_FB_CACHE = {}


def _fbank_matrix():
    m = _FB_CACHE.get("m")
    if m is None:
        m = _mel_filterbank()
        _FB_CACHE["m"] = m
    return m


def fbank(samples, sample_rate=SAMPLE_RATE):
    """kaldi 兼容 fbank -> (num_frames, 80) float32，已取 log。

    与 kaldi-native-fbank 逐元素一致（见 `_selftest_speaker_voiceprint.py`
    的对比用例）；不一致时先怀疑窗口类型 / high_freq / snip_edges 三项。
    """
    x = np.asarray(samples, dtype=np.float32)
    if x.ndim != 1:
        x = x.reshape(-1)
    if sample_rate != SAMPLE_RATE:
        x = resample_linear(x, sample_rate, SAMPLE_RATE)
    frame_length = int(round(FRAME_LENGTH_MS * SAMPLE_RATE / 1000.0))   # 400
    frame_shift = int(round(FRAME_SHIFT_MS * SAMPLE_RATE / 1000.0))     # 160
    if DITHER:
        x = x + (np.random.rand(len(x)).astype(np.float32) - 0.5) * 2.0 * DITHER
    n = len(x)
    if n == 0:
        return np.zeros((0, NUM_BINS), dtype=np.float32)
    # snip_edges=False：帧数按 (N + shift/2) // shift，首帧可能越界（补零）
    num_frames = (n + frame_shift // 2) // frame_shift
    if num_frames <= 0:
        return np.zeros((0, NUM_BINS), dtype=np.float32)

    n_fft = 1
    while n_fft < frame_length:          # round_to_power_of_two
        n_fft <<= 1
    pad_front = frame_length // 2                        # 200
    pad_back = frame_length + frame_shift                # 560，足够覆盖尾帧
    padded = np.zeros(n + pad_front + pad_back, dtype=np.float32)
    padded[pad_front:pad_front + n] = x
    # 帧 f 的起点（相对 padded）= pad_front + (shift*f + shift//2 - frame_length//2)
    base = pad_front + frame_shift // 2 - frame_length // 2
    starts = base + frame_shift * np.arange(num_frames, dtype=np.int64)
    win = np.lib.stride_tricks.sliding_window_view(padded, frame_length)
    frames = win[starts]                                  # (T, 400) 视图

    out = np.empty((num_frames, NUM_BINS), dtype=np.float32)
    fb = _fbank_matrix()
    # 分块，避免一次性展开 (T, 512) 复数组把内存顶爆
    chunk = 2048
    w = _povey_window(frame_length)
    for s in range(0, num_frames, chunk):
        e = min(s + chunk, num_frames)
        blk = np.array(frames[s:e], dtype=np.float32)
        if True:                                          # remove_dc_offset
            blk -= blk.mean(axis=1, keepdims=True)
        if PREEMPH_COEFF != 0.0:                          # preemphasis
            blk[:, 1:] -= PREEMPH_COEFF * blk[:, :-1].copy()
            blk[:, 0] -= PREEMPH_COEFF * blk[:, 0]
        blk *= w
        spec = np.fft.rfft(blk, n=n_fft, axis=1)
        power = (spec.real ** 2 + spec.imag ** 2).astype(np.float32)
        mel = power @ fb.T
        np.maximum(mel, np.finfo(np.float32).eps, out=mel)  # 防 log(0)
        out[s:e] = np.log(mel)
    return out


# ---------------------------------------------------------------- 声纹编码器


class VoiceprintEncoder:
    """CAM++ 声纹编码器：fbank -> 192 维单位向量。惰性建会话，可复用。"""

    def __init__(self, model_path=None):
        self.model_path = model_path or MODEL_PATH
        if not os.path.isfile(self.model_path):
            raise VoiceprintError(
                "声纹模型缺失：%s\n请运行：python tools/download_open_source_deps.py "
                "--only speaker-model" % self.model_path)
        self._sess = None
        self._in = None

    def _session(self):
        if self._sess is None:
            try:
                import onnxruntime as ort
            except ImportError as e:
                raise VoiceprintError("未安装 onnxruntime：%s" % e)
            so = ort.SessionOptions()
            so.log_severity_level = 3
            so.intra_op_num_threads = max(1, min(4, (os.cpu_count() or 2)))
            self._sess = ort.InferenceSession(
                self.model_path, sess_options=so,
                providers=["CPUExecutionProvider"])
            self._in = self._sess.get_inputs()[0].name
        return self._sess

    def embed(self, samples, sample_rate=SAMPLE_RATE):
        """一段音频 -> L2 归一化后的 192 维向量。音频过短会抛 VoiceprintError。

        内部先做峰值归一化（见 `normalize_peak`），使结果与录音增益无关。
        """
        feats = fbank(normalize_peak(samples), sample_rate)
        if feats.shape[0] < 10:
            raise VoiceprintError("音频太短（%d 帧），至少需要约 0.2 秒人声"
                                  % feats.shape[0])
        # 模型元数据 feature_normalize_type=global-mean：逐维减时间均值
        feats = feats - feats.mean(axis=0, keepdims=True)
        x = feats[None, :, :].astype(np.float32)
        y = self._session().run(None, {self._in: x})[0][0]
        y = np.asarray(y, dtype=np.float32)
        nrm = float(np.linalg.norm(y))
        return y / (nrm if nrm > 1e-9 else 1.0)

    def embed_many(self, chunks, sample_rate=SAMPLE_RATE):
        """多段音频 -> 逐段向量列表；长度不足的段返回 None（不中断整批）。"""
        out = []
        for c in chunks:
            try:
                out.append(self.embed(c, sample_rate))
            except VoiceprintError:
                out.append(None)
        return out


def normalize_peak(x):
    """把波形峰值归一化到 1.0。

    为什么必要：fbank 取 log 后做「减全局均值」只是把**加性**偏置抵消掉，
    而 log 前的 `max(·, eps)` 截断会破坏这个性质——音量越小，越多 bin 被截断，
    特征就越偏离。实测（CAM++，真实语音）：不归一化时增益降到 0.1，同段自比
    掉到 0.977；**归一化后各增益下恒为 1.0000**。不同 cue / 不同麦克风的音量
    差异在实战中很常见，所以这一步不能省。
    """
    a = np.asarray(x, dtype=np.float32).reshape(-1)
    if a.size == 0:
        raise VoiceprintError("空音频，无法提取声纹")
    m = float(np.max(np.abs(a)))
    if m < 1e-6:
        raise VoiceprintError("音频几乎无声（峰值 %.1e），无法提取声纹" % m)
    return a / m


def cosine(a, b):
    """余弦相似度（两向量已归一化时等价于点积）。"""
    if a is None or b is None:
        return float("nan")
    a = np.asarray(a, dtype=np.float32).reshape(-1)
    b = np.asarray(b, dtype=np.float32).reshape(-1)
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na < 1e-9 or nb < 1e-9:
        return float("nan")
    return float(np.dot(a, b) / (na * nb))


# ---------------------------------------------------------------- 声纹模板


def template_path(name):
    """模板文件名。**刻意与 `selection.json` 保持互斥**：后者是「启用名单」，
    与模板同目录；若允许把声纹命名为 selection，落盘时会把名单文件覆盖掉，
    而 `list_templates()` 又会把它当名单排掉 —— 表现为「录完就消失」。
    这里给撞名的声纹加后缀，既保住用户输入，也保住名单文件。
    """
    safe = "".join(c for c in str(name) if c not in '\\/:*?"<>|').strip() or "主播"
    if safe.lower() == "selection":
        safe += "_声纹"
    return os.path.join(TEMPLATE_DIR, safe + ".json")


def save_template(name, embedding, **meta):
    """把声纹模板落盘为 JSON（192 个浮点，便于人工查看与 diff）。"""
    os.makedirs(TEMPLATE_DIR, exist_ok=True)
    obj = {"name": str(name), "dim": int(len(embedding)),
           "created": time.strftime("%Y-%m-%d %H:%M:%S"),
           "embedding": [round(float(v), 6) for v in embedding]}
    obj.update({k: v for k, v in meta.items() if v is not None})
    p = template_path(name)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
    return p


def load_template(name):
    """读回模板 dict（含 embedding 的 np.float32 数组）。"""
    p = name if os.path.isfile(str(name)) else template_path(name)
    if not os.path.isfile(p):
        raise VoiceprintError("声纹模板不存在：%s（先用 enroll 录入）" % p)
    with open(p, encoding="utf-8") as fh:
        obj = json.load(fh)
    obj["embedding"] = np.asarray(obj.get("embedding") or [], dtype=np.float32)
    if obj["embedding"].size == 0:
        raise VoiceprintError("声纹模板内容为空：%s" % p)
    obj["path"] = p
    return obj


def list_templates():
    """列出已录入的声纹模板名（按文件名排序）。

    ⚠ 必须排除 `selection.json`——「启用名单」与模板同目录，不排掉会被
    当成一个名叫「selection」的声纹，界面上凭空多出一行。
    """
    if not os.path.isdir(TEMPLATE_DIR):
        return []
    skip = {os.path.splitext(os.path.basename(SELECTION_PATH))[0].lower()}
    return sorted(os.path.splitext(f)[0] for f in os.listdir(TEMPLATE_DIR)
                  if f.lower().endswith(".json")
                  and os.path.splitext(f)[0].lower() not in skip)


#: 「当前启用的声纹」清单。刻意**不写进 `data/ai_config.json`**：
#: 那个文件由设置页 `_collect_ai()` 按 UI 控件整份重写，未进 schema 的键会被
#: 静默丢弃（见 ai_client.DEFAULT_CONFIG 的约定）。声纹选择不属于 AI 设置页，
#: 单独落一份小文件最省事、也不会被覆盖。
SELECTION_PATH = os.path.join(TEMPLATE_DIR, "selection.json")


def load_selection():
    """读「已启用的声纹」名单，自动剔除已被删除的模板。"""
    try:
        with open(SELECTION_PATH, encoding="utf-8") as fh:
            obj = json.load(fh)
        names = [str(x) for x in (obj.get("enabled") or [])]
    except (OSError, ValueError):
        return []
    have = set(list_templates())
    return [n for n in names if n in have]


def save_selection(names):
    """写「已启用的声纹」名单；返回实际落盘的名单（已过滤不存在的模板）。"""
    have = set(list_templates())
    keep = []
    for n in names or []:
        n = str(n)
        if n in have and n not in keep:
            keep.append(n)
    os.makedirs(TEMPLATE_DIR, exist_ok=True)
    with open(SELECTION_PATH, "w", encoding="utf-8") as fh:
        json.dump({"enabled": keep,
                   "updated": time.strftime("%Y-%m-%d %H:%M:%S")},
                  fh, ensure_ascii=False, indent=1)
    return keep


def delete_template(name):
    """删除一个声纹模板，并把它从启用名单里摘掉。返回是否真的删了。"""
    p = template_path(name)
    existed = os.path.isfile(p)
    try:
        os.remove(p)
    except OSError:
        existed = False
    sel = load_selection()
    if str(name) in sel:
        save_selection([n for n in sel if n != str(name)])
    return existed


def enroll(src, start=None, dur=None, name="主播", encoder=None):
    """录入声纹：从音频/视频截一段提向量并落盘，返回模板 dict。

    ⚠ 参考片段越干净越好（单人、无 BGM、无重叠说话），建议 10~30 秒。
    """
    enc = encoder or VoiceprintEncoder()
    pcm = read_pcm(src, start=start, dur=dur)
    if len(pcm) < SAMPLE_RATE // 5:
        raise VoiceprintError("参考片段太短（%.2f 秒），建议 10 秒以上"
                              % (len(pcm) / float(SAMPLE_RATE)))
    emb = enc.embed(pcm)
    path = save_template(name, emb, source=os.path.basename(str(src)),
                         start=start, dur=dur,
                         seconds=round(len(pcm) / float(SAMPLE_RATE), 2))
    return {"name": name, "path": path, "embedding": emb,
            "seconds": round(len(pcm) / float(SAMPLE_RATE), 2)}


# ---------------------------------------------------------------- 打分与筛选


def _cue_chunks(pcm, cues, sample_rate=SAMPLE_RATE, pad=0.05):
    """按 cue 时间轴切音频；过短或越界的返回 None。pad 为两侧各留的余量（秒）。"""
    n = len(pcm)
    p = int(pad * sample_rate)
    out = []
    for c in cues:
        a = max(0, int(round(c.start / 1000.0 * sample_rate)) - p)
        b = min(n, int(round(c.end / 1000.0 * sample_rate)) + p)
        out.append(pcm[a:b] if b - a >= sample_rate // 10 else None)
    return out


def _as_template_list(template):
    """把「单个模板 / 模板名 / 列表」统一成 `[(名称, 向量), ...]`（**幂等**）。

    多模板是**并集**语义：一条 cue 只要与其中**任意**一个声纹够像，就算主播
    ——对应「一档节目有两位主播」「常驻嘉宾也算」这类场景。

    幂等很重要：本函数的结果会被 `score_by_speaker` / `filter_srt` 再传一遍，
    若把已归一化的 `(名称, 向量)` 当成「一个模板」会撞上 np.asarray 的
    不等长报错。
    """
    if template is None:
        return []
    items = template if isinstance(template, (list, tuple)) else [template]
    # 单个 (名称, 向量) 二元组要当成「一个模板」，不能当成模板列表
    if (isinstance(template, tuple) and len(template) == 2
            and isinstance(template[0], str)):
        items = [template]
    out = []
    for it in items:
        if isinstance(it, str):
            t = load_template(it)
            out.append((t.get("name") or it,
                        np.asarray(t["embedding"], dtype=np.float32)))
        elif isinstance(it, dict):
            out.append((it.get("name") or "主播",
                        np.asarray(it["embedding"], dtype=np.float32)))
        elif (isinstance(it, (tuple, list)) and len(it) == 2
                and isinstance(it[0], str)):
            out.append((it[0], np.asarray(it[1], dtype=np.float32)))
        else:
            out.append(("主播", np.asarray(it, dtype=np.float32)))
    return out


def score_by_speaker(pcm, cues, template, encoder=None,
                     sample_rate=SAMPLE_RATE):
    """按说话人簇打分（推荐模式）。

    先把 cue 按 `speaker` 标签聚簇，簇内音频拼接后算**一个**向量，再与模板
    比对——短 cue 单独提向量极不稳，聚合后立刻可用。无说话人标签的 cue
    归入 `""` 簇，按逐条打分兜底。

    `template` 可以是单个模板 dict / 模板名 / 模板名列表（多模板取**最大值**，
    即并集语义）。

    返回 `{说话人标签: {"score", "n", "seconds", "best"}}`；`best` 是命中的
    模板名（多声纹时用来回显「这条算谁的」）。
    """
    enc = encoder or VoiceprintEncoder()
    tpls = _as_template_list(template)
    groups = {}
    for i, c in enumerate(cues):
        groups.setdefault(str(getattr(c, "speaker", "") or ""), []).append(i)
    chunks = _cue_chunks(pcm, cues, sample_rate)
    out = {}
    for spk, idxs in groups.items():
        parts = [chunks[i] for i in idxs if chunks[i] is not None]
        secs = sum(len(p) for p in parts) / float(sample_rate)
        if not parts:
            out[spk] = {"score": float("nan"), "n": len(idxs),
                        "seconds": 0.0, "best": ""}
            continue
        joined = np.concatenate(parts)
        try:
            emb = enc.embed(joined, sample_rate)
            scored = [(cosine(e, emb), n) for n, e in tpls] or [(float("nan"), "")]
            sc, best = max(scored, key=lambda x: (x[0] if x[0] == x[0] else -9))
        except VoiceprintError:
            sc, best = float("nan"), ""
        out[spk] = {"score": sc, "n": len(idxs), "seconds": round(secs, 2),
                    "best": best if sc == sc else ""}
    return out


def score_by_cue(pcm, cues, template, encoder=None, sample_rate=SAMPLE_RATE):
    """逐条 cue 打分（无说话人标签时的兜底模式）。返回与 cues 等长的分数表。"""
    enc = encoder or VoiceprintEncoder()
    tpls = _as_template_list(template)
    chunks = _cue_chunks(pcm, cues, sample_rate)
    out = []
    for e in enc.embed_many(chunks, sample_rate):
        if e is None:
            out.append(float("nan"))
        else:
            vals = [cosine(t, e) for _n, t in tpls]
            out.append(max(vals) if vals else float("nan"))
    return out


#: 本地聚簇阈值：两条 cue 的声纹余弦 ≥ 此值视为同一说话人。
#: 与判定阈值同源（实测同人 min 0.681 / 异人 max 0.450，0.5 落在间隔正中）。
CLUSTER_THRESHOLD = 0.5
#: 短于该秒数的 cue 不参与聚类（向量太不稳，会污染簇心）
CLUSTER_MIN_SECONDS = 0.4


def cluster_cues(pcm, cues, encoder=None, sample_rate=SAMPLE_RATE,
                 threshold=CLUSTER_THRESHOLD,
                 min_seconds=CLUSTER_MIN_SECONDS):
    """按声纹把 cue 就地聚成说话人簇（**不依赖 ASR 的 `[说话人N]`**）。

    为什么需要：ASR 端的说话人分离**不是所有端点都支持**——本项目实测
    `qwen-audio-3.0-asr-flash` 走百炼 Token Plan 时，配置里 `asr_diarize=True`
    也照样拿不到标签（只有 3.1 原生 / 火山极速版 / AssemblyAI / Deepgram /
    ElevenLabs / 百炼 Filetrans 支持）。而声纹向量我们本来就算得出来，干脆自己聚。

    做法：逐 cue 提向量 → **按音频时长降序**贪心聚簇（长 cue 的向量更稳，
    先立簇心）→ 新向量与各簇心比余弦，≥ `threshold` 归入并更新簇心，否则新建。
    顺序确定、结果可复现（不用随机初始化，也不需要 sklearn/scipy）。

    返回 `(labels, sizes)`：`labels[i]` 是 cue i 的簇号（**`-1` = 音频不足，
    未参与聚类**），`sizes` 是 `{簇号: 条数}`。
    """
    enc = encoder or VoiceprintEncoder()
    chunks = _cue_chunks(pcm, cues, sample_rate)
    min_len = int(min_seconds * sample_rate)
    order = []                      # [(cue_index, duration_seconds)]，按时长降序
    for i, ch in enumerate(chunks):
        if ch is not None and len(ch) >= min_len:
            order.append((i, len(ch) / float(sample_rate)))
    order.sort(key=lambda t: -t[1])

    labels = [-1] * len(cues)
    centroids = []                  # 每个簇的归一化簇心
    sums = []                       # 簇心累加（未归一化），用于增量更新
    counts = []
    for idx, _dur in order:
        try:
            v = enc.embed(chunks[idx], sample_rate)
        except VoiceprintError:
            continue
        if centroids:
            sims = [float(np.dot(v, c)) for c in centroids]
            best = int(np.argmax(sims))
            if sims[best] >= threshold:
                labels[idx] = best
                sums[best] = sums[best] + v
                counts[best] += 1
                n = sums[best]
                centroids[best] = n / (float(np.linalg.norm(n)) + 1e-9)
                continue
        labels[idx] = len(centroids)
        sums.append(v.copy())
        counts.append(1)
        centroids.append(v.copy())

    sizes = {}
    for lb in labels:
        if lb >= 0:
            sizes[lb] = sizes.get(lb, 0) + 1
    return labels, sizes


def score_clusters(pcm, cues, labels, template, encoder=None,
                   sample_rate=SAMPLE_RATE):
    """每个簇把成员 cue 的音频拼起来算**一个**向量，再与模板比对。

    返回 `{簇号: {"score", "n", "seconds", "best"}}`（键是字符串形式的簇号，
    便于直接喂给 `decide()` 的 `speaker_scores` 与写报告）。
    """
    enc = encoder or VoiceprintEncoder()
    tpls = _as_template_list(template)
    chunks = _cue_chunks(pcm, cues, sample_rate)
    groups = {}
    for i, lb in enumerate(labels):
        if lb >= 0:
            groups.setdefault(lb, []).append(i)
    out = {}
    for lb, idxs in groups.items():
        parts = [chunks[i] for i in idxs if chunks[i] is not None]
        secs = sum(len(p) for p in parts) / float(sample_rate)
        try:
            emb = enc.embed(np.concatenate(parts), sample_rate)
            scored = [(cosine(e, emb), n) for n, e in tpls] or [(float("nan"), "")]
            sc, best = max(scored, key=lambda x: (x[0] if x[0] == x[0] else -9))
        except VoiceprintError:
            sc, best = float("nan"), ""
        out[str(lb)] = {"score": sc, "n": len(idxs), "seconds": round(secs, 2),
                        "best": best if sc == sc else ""}
    return out


def _labels_to_cue_scores(cues, labels, cluster_scores):
    """把「簇分」摊回每条 cue，得到与 cues 等长的分数表。

    `[说话人N]` 标签与本地簇号可以共存：**优先用 cue 自带的标签**（那是 ASR
    分离的结果，比我们聚的更可信），没有标签的 cue 才用本地簇分。
    """
    out = []
    for i, c in enumerate(cues):
        spk = str(getattr(c, "speaker", "") or "")
        if spk:
            info = cluster_scores.get(spk)
            out.append(info["score"] if info else float("nan"))
        else:
            info = cluster_scores.get(str(labels[i])) if labels[i] >= 0 else None
            out.append(info["score"] if info else float("nan"))
    return out


def decide(cues, speaker_scores, threshold=DEFAULT_THRESHOLD,
           low=DEFAULT_LOW, cue_scores=None):
    """判定每条 cue 的归属。

    返回 `[(cue, 状态, 分数)]`，状态取值：
      `keep`   —— 相似度 >= threshold，判为主播
      `drop`   —— 相似度 < low，判为非主播
      `review` —— 落在 [low, threshold) 存疑区，默认**保留**并标记，交人工复核
    """
    out = []
    for i, c in enumerate(cues):
        spk = str(getattr(c, "speaker", "") or "")
        info = speaker_scores.get(spk) if speaker_scores else None
        if info is not None and info.get("score") == info.get("score"):
            sc = info["score"]
        elif cue_scores is not None and cue_scores[i] == cue_scores[i]:
            sc = cue_scores[i]
        else:
            sc = float("nan")
        if sc != sc:
            state = "review"            # 判不了（音频缺失）-> 保留待人工
        elif sc >= threshold:
            state = "keep"
        elif sc < low:
            state = "drop"
        else:
            state = "review"
        out.append((c, state, sc))
    return out


def filter_srt(src, srt_path, template, threshold=DEFAULT_THRESHOLD,
               low=DEFAULT_LOW, out_path=None, encoder=None,
               keep_review=True, report=True, progress=None):
    """端到端：音频 + SRT -> 只保留主播的 SRT。

    `template` 支持单个模板 dict / 模板名，或**模板名列表**（多声纹取并集：
    与其中任意一个够像即保留）。返回 dict（含产物路径与统计）。

    `progress(text)` 可选：在阶段边界回调一句人话（解码 / 提取 / 写盘），
    供界面显示状态——18 分钟的片子要跑一两分钟，没反馈用户会以为卡死。
    """
    def _say(msg):
        if progress:
            try:
                progress(msg)
            except Exception:  # noqa: BLE001
                pass

    tpls = _as_template_list(template)
    if not tpls:
        raise VoiceprintError("没有可用的声纹模板（先 enroll 录入）")
    # ⚠ 走 `load_file` 而非「open 后 encode」：前者直接吃字节，能如实判定
    #   BOM 与源换行（CRLF/LF）；后者先被 utf-8-sig 吃掉 BOM，写出来就没了。
    #   项目一贯要求「BOM / 换行一字不动」，产物风格应当与源字幕一致。
    doc = secore.SubtitleDoc()
    doc.load_file(srt_path)
    cues = list(doc.cues)
    if not cues:
        raise VoiceprintError("字幕里没有解析到任何 cue：%s" % srt_path)

    _say("正在解码音频…")
    pcm = read_pcm(src)
    _say("音频 %.0f 秒，正在提取声纹…" % (len(pcm) / float(SAMPLE_RATE)))
    enc = encoder or VoiceprintEncoder()
    n_labeled = sum(1 for c in cues if str(getattr(c, "speaker", "") or ""))
    local_clusters = 0
    if n_labeled:
        # 有 `[说话人N]`：直接用 ASR 分离的结果（比我们聚的更可信）
        spk_scores = score_by_speaker(pcm, cues, tpls, enc)
        cue_scores = None
        if n_labeled < len(cues):
            # 少数 cue 没标签：用本地簇补上，别让它们走 NaN -> review 白留
            labels, _ = cluster_cues(pcm, cues, enc)
            local_clusters = len({x for x in labels if x >= 0})
            extra = score_clusters(pcm, cues, labels, tpls, enc)
            for k, v in extra.items():
                spk_scores.setdefault("簇" + k, v)
            cue_scores = _labels_to_cue_scores(cues, labels, extra)
    else:
        # 无标签（ASR 端点不支持说话人分离时很常见）：**本地声纹聚类**
        labels, _sizes = cluster_cues(pcm, cues, enc)
        local_clusters = len({x for x in labels if x >= 0})
        spk_scores = score_clusters(pcm, cues, labels, tpls, enc)
        cue_scores = _labels_to_cue_scores(cues, labels, spk_scores)

    verdict = decide(cues, spk_scores, threshold, low, cue_scores)
    kept = [c for c, st, _ in verdict if st == "keep" or (keep_review and st == "review")]
    n_keep = sum(1 for _, st, _ in verdict if st == "keep")
    n_review = sum(1 for _, st, _ in verdict if st == "review")
    n_drop = sum(1 for _, st, _ in verdict if st == "drop")

    if out_path:
        d = secore.SubtitleDoc(cues=list(kept), newline=doc.newline,
                               has_bom=doc.has_bom)
        with open(out_path, "wb") as fh:
            fh.write(d.to_bytes())

    res = {"out": out_path, "total": len(cues), "keep": n_keep,
           "review": n_review, "drop": n_drop,
           "kept_total": len(kept), "speakers": spk_scores,
           "threshold": threshold, "low": low,
           "local_clusters": local_clusters,
           "templates": [n for n, _e in tpls]}
    if report and out_path:
        _write_report(out_path, res, verdict)
    return res


def _write_report(out_path, res, verdict):
    """在产物旁写一份 txt 复核报告：每个说话人得分 + 被丢弃的条目。"""
    lines = ["主播声纹筛选报告",
             "  来源字幕 : %s" % os.path.basename(out_path),
             "  声纹模板 : %s（%d 个，并集）"
             % ("、".join(res.get("templates") or []) or "-",
                len(res.get("templates") or [])),
             "  阈值     : keep>=%.2f / drop<%.2f" % (res["threshold"], res["low"]),
             "  cue 总数 : %d -> 保留 %d（其中存疑 %d）/ 丢弃 %d"
             % (res["total"], res["kept_total"], res["review"], res["drop"]),
             "  分组依据 : %s"
             % ("字幕的 [说话人N] 标签"
                if not res.get("local_clusters")
                else "本地声纹聚类（%d 簇）" % res["local_clusters"]),
             "", "各组得分（按相似度降序）："]
    for spk, info in sorted(res["speakers"].items(),
                            key=lambda kv: -(kv[1]["score"] if kv[1]["score"] == kv[1]["score"] else -9)):
        label = spk or "(无标签)"
        if label.isdigit():                      # 本地聚类：0/1/2 -> 簇 0/1/2
            label = "簇 " + label
        mark = "<= 判为主播" if info["score"] >= res["threshold"] else (
            "存疑" if info["score"] >= res["low"] else "丢弃")
        if info.get("best") and info["score"] >= res["low"]:
            mark += "（像「%s」）" % info["best"]
        lines.append("  %-12s 相似度 %.3f  %d 条 / %.1f 秒  %s"
                     % (label, info["score"], info["n"], info["seconds"], mark))
    dropped = [(c, sc) for c, st, sc in verdict if st == "drop"]
    if dropped:
        lines += ["", "被丢弃的 %d 条：" % len(dropped)]
        for c, sc in dropped[:200]:
            txt = str(getattr(c, "text", "") or "").replace("\n", " ")[:40]
            lines.append("  [%s] %.3f  %s" % (getattr(c, "speaker", "") or "-", sc, txt))
    p = os.path.splitext(out_path)[0] + ".报告.txt"
    with open(p, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return p


# ---------------------------------------------------------------- 命令行


def _print_scores(title, scores):
    print("=== %s ===" % title)
    for spk, info in sorted(scores.items(),
                            key=lambda kv: -(kv[1]["score"] if kv[1]["score"] == kv[1]["score"] else -9)):
        print("  %-12s %.3f   %d 条 / %.1f 秒"
              % (spk or "(无标签)", info["score"], info["n"], info["seconds"]))


def main(argv=None):
    try:
        return _main(argv)
    except VoiceprintError as e:
        # 可预期失败（模型缺失 / 模板未录入 / ffmpeg 解码失败…）只给一行提示，
        # 不打 traceback —— 命令行是给用户和排查用的，堆栈只会盖住真正的原因。
        print("[声纹] %s" % e, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


def _main(argv=None):
    ap = argparse.ArgumentParser(description="主播声纹录入与字幕筛选")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("enroll", help="录入主播声纹")
    p1.add_argument("--src", required=True)
    p1.add_argument("--start", type=float, default=None)
    p1.add_argument("--dur", type=float, default=None)
    p1.add_argument("--name", default="主播")

    p2 = sub.add_parser("score", help="按说话人打印相似度（只看不筛）")
    p2.add_argument("--src", required=True)
    p2.add_argument("--srt", required=True)
    p2.add_argument("--name", default="主播")
    p2.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    p2.add_argument("--low", type=float, default=DEFAULT_LOW)

    p3 = sub.add_parser("filter", help="筛选出主播字幕")
    p3.add_argument("--src", required=True)
    p3.add_argument("--srt", required=True)
    p3.add_argument("--name", default="主播")
    p3.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    p3.add_argument("--low", type=float, default=DEFAULT_LOW)
    p3.add_argument("--out", default=None)
    p3.add_argument("--strict", action="store_true",
                    help="存疑区也丢弃（默认保留并标记）")

    p4 = sub.add_parser("list", help="列出已录入的声纹模板（x = 已启用）")

    p5 = sub.add_parser("use", help="设置启用的声纹（多选用逗号分隔）")
    p5.add_argument("names", help="声纹名，逗号分隔；传空串表示都不启用")

    p6 = sub.add_parser("delete", help="删除一个声纹模板")
    p6.add_argument("name")

    args = ap.parse_args(argv)
    if args.cmd == "list":
        sel = set(load_selection())
        names = list_templates()
        if not names:
            print("（还没有录入任何声纹；先跑 enroll）")
        for n in names:
            print("  [%s] %s" % ("x" if n in sel else " ", n))
        print("\n带 x 的为「已启用」（转录后会自动筛选）。改启用名单："
              "use <名字,名字>")
        return 0
    if args.cmd == "use":
        keep = save_selection([x.strip() for x in str(args.names).split(",")
                               if x.strip()])
        print("已启用 %d 个声纹：%s" % (len(keep), "、".join(keep) or "（空 = 不筛选）"))
        return 0
    if args.cmd == "delete":
        ok = delete_template(args.name)
        print("已删除声纹「%s」" % args.name if ok else "未找到声纹「%s」" % args.name)
        return 0 if ok else 1
    if args.cmd == "enroll":
        r = enroll(args.src, args.start, args.dur, args.name)
        print("已录入声纹「%s」：%.1f 秒 -> %s" % (r["name"], r["seconds"], r["path"]))
        return 0

    names = [x.strip() for x in str(args.name).split(",") if x.strip()]
    tpls = [load_template(n) for n in names]
    text = open(args.srt, encoding="utf-8-sig", errors="replace").read()
    doc = secore.SubtitleDoc()
    doc.load_bytes(text.encode("utf-8"))
    pcm = read_pcm(args.src)
    enc = VoiceprintEncoder()
    scores = score_by_speaker(pcm, list(doc.cues), tpls, enc)
    _print_scores("说话人与「%s」的相似度" % "、".join(names), scores)
    if args.cmd == "score":
        return 0
    out = args.out or os.path.splitext(args.srt)[0] + "_主播.srt"
    res = filter_srt(args.src, args.srt, tpls, args.threshold, args.low,
                     out_path=out, encoder=enc, keep_review=not args.strict)
    print("\n保留 %d / 存疑 %d / 丢弃 %d  ->  %s"
          % (res["keep"], res["review"], res["drop"], out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
