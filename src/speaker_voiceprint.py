# -*- coding: utf-8 -*-
# @version 1.19.0
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
    # 多片段录入（先做同人一致性校验，再取均值，模板更稳）：
    python speaker_voiceprint.py enroll --src 视频.mp4 --start 12 --dur 20 --name 主播 \
                                        --clip "另一段.mp4,30,15" --clip "另一段.mp4,90,10"
    # 追加到已有同名声纹（扩充校准，不覆盖）：
    python speaker_voiceprint.py enroll --src 视频.mp4 --start 200 --dur 15 \
                                        --name 主播 --append
    python speaker_voiceprint.py list                     # 列出已录入（x = 已启用）
    python speaker_voiceprint.py use 主播,嘉宾            # 启用多个声纹（并集）
    python speaker_voiceprint.py delete 主播
    python speaker_voiceprint.py score  --src 视频.mp4 --srt 字幕.srt --name 主播,嘉宾
    python speaker_voiceprint.py filter --src 视频.mp4 --srt 字幕.srt --name 主播,嘉宾 \
                                        --threshold 0.5 --out 主播.srt

提特征前会做两道预处理（见 `trim_silence` / `normalize_rms`）：
    ① 能量 VAD 剪掉头尾静音与句间长停顿——静音帧经 log(eps) 截断后会污染
       嵌入向量，实测给判定边际带来 0.2~0.3 的塌缩；
    ② RMS 归一化到 -20 dBFS——峰值归一化会被单个爆音/咔哒声带偏（增益被
      爆音吃掉，人声被压到地板），RMS 对这类毛刺稳健且同样增益不变。

多声纹是**并集**语义：一条 cue 只要与其中任意一个声纹够像就算「主播」，
对应「一档节目有两位主播 / 常驻嘉宾也算」这类场景。启用名单单独落
`data/voiceprint/selection.json`（**刻意不写进 `data/ai_config.json`**——
那个文件由设置页 `_collect_ai()` 整份重写，未进 schema 的键会被静默丢弃）。

多用户共享：模板的录入/重录/删除会经 `voiceprint_sync`（**独立通道**，与
字幕校准知识同步互不干涉）排进待传队列，由引擎启动/退出同步或
`python src/voiceprint_sync.py sync` 与其它客户端收敛。**不同用户上传同一
主播的声纹会做「数据迭代」**：同名 alive 条目按向量加权并集折叠
（`fold_leaves`：mix 叶子按 fp 去重、加权求和归一，同人守卫 0.55 挡住
异名同录的脏数据），每份上传都是并集的一份子——声纹库越用越准。
本机也可以随时**追加**同一主播的新片段（`enroll --append`）扩充校准，
与远端折叠走同一条数学路径。`selection.json` 是本地偏好，刻意不同步。
详见 `src/voiceprint_sync.py` 模块文档。
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
    r"""定位 tools / data 两个目录。

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

    引擎导入失败时才回落自算。

    ⚠ 回落分支的口径**刻意比引擎简化**：只认 `VT_DATA_ROOT`，不读
    `data_dir.txt` 指针。理由——引擎导入失败说明运行时环境已经不完整
    （源码搬迁、site-packages 缺失、或 onefile 早期），此时再去猜
    `{app}\data_dir.txt` 的位置并不可靠，猜错会静默写到错误的盘。
    真到了那一步，声纹模型和模板目录保持一致比「尊重用户指针」更重要。
    **引擎能导入时一律走引擎分支，指针逻辑自动生效。**
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
    # 兜底也向上找 data 目录：源码从 src\ 直接跑时 data 在上一层
    root = (os.environ.get("VT_DATA_ROOT") or "").strip().strip('"')
    data_parent = os.path.abspath(root) if root else app
    if not os.path.isdir(os.path.join(data_parent, "data")):
        d = data_parent
        for _ in range(5):
            if os.path.isdir(os.path.join(d, "data")):
                data_parent = d
                break
            parent = os.path.dirname(d)
            if parent == d:
                break
            d = parent
    return tools, os.path.join(data_parent, "data")


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

#: 判定阈值。依据 sherpa 中文说话人测试集（3 位 × 录入/测试共 14 段，
#: scripts/dev/voiceprint_accuracy.py 可复跑）的实测：
#:   旧管线（峰值归一化、无 VAD）：同人余弦 min 0.681 / mean 0.784，
#:                                异人 max 0.450 / mean 0.174；
#:   现行管线（VAD + RMS）：单片段录入 同人 min 0.666 / 异人 max 0.458，
#:                          多片段录入 同人 min 0.768 / 异人 max 0.468。
#: 决策边界取各组中点（≈0.56~0.62）的公共保守值 **0.55**。
#: 语料只有 3 位说话人，0.55 的可靠性来自「同人/异人两段分布之间的空档」
#: 而非精确边界——抗劣化（padding/爆音/底噪）比抠小数点后两位更有用。
DEFAULT_THRESHOLD = 0.55
#: 「存疑区」下界。**取异人相似度的实测上限 0.450**——低于它就基本可以断定
#: 「不是主播」，没必要再留。
#: ⚠ 这个值最初拍成 0.35（凭感觉留宽一点），实测踩坑：真实素材里
#: 「游戏官方中文旁白」聚成一簇、相似度 **0.390**，正好落进 [0.35,0.55) 的
#: 存疑区被**保留**，用户看到的就是「依旧多人混合输出」（164 秒旁白没筛掉）。
#: 教训：存疑区要**窄**且**贴着决策边界**，不能一路宽到"看起来还行"。
DEFAULT_LOW = 0.45

# ---------------------------------------------------------------- 预处理常量
#: RMS 归一化目标电平（-20 dBFS）。语音录音的典型工作电平；语音峰值/RMS
#: 一般在 3~10（10~20dB crest factor），目标 0.1 下归一化后峰值 0.3~1.0，
#: 绝大多数素材不触顶，个别 crest 极大的片段退化为峰值归一化（gain = 1/peak）。
RMS_TARGET = 0.1

#: 能量 VAD（trim_silence）参数。阈值用**相对 dB**（对录音增益天然不变）：
#: 取「最响帧 -40dB」与「低分位 +12dB」中较保守（较低）的一个——
#: 纯人声片段低分位≈最响帧，退化为 -40dB（几乎不剪）；带静音的片段低分位
#: 落在静音上，自适应地把静音排除。40dB 的 headroom 远大于 16bit 编码噪声
#: （-90dB）与正常房间底噪（-60~-50dB），又不会碰到有效语音。
VAD_DB_HEADROOM = 40.0
VAD_DB_FLOOR_MARGIN = 12.0
VAD_FLOOR_PCTL = 25.0
#: 形态学处理：≤0.35s 的间断视为语句停顿予以保留（填回），<0.12s 的孤立响帧
#: 视为毛刺丢弃（爆点/咔哒声）。帧移与 fbank 对齐（10ms）。
VAD_FILL_GAP_MS = 350.0
VAD_MIN_RUN_MS = 120.0
#: 整段检出的人声不足 0.2 秒 -> 视为无人声（与 embed 的最短帧数要求对齐），
#: 调用方拿到 VoiceprintError 后按 NaN 处理（保守保留），不再拿静音硬算向量。
VAD_MIN_SPEECH_SECONDS = 0.2
#: 帧能量低于该绝对值（dB）视为数字静音（16bit 地板约 -90dB，留 15dB 余量）。
VAD_ABS_SILENCE_DB = -75.0


class VoiceprintError(RuntimeError):
    """声纹链路可预期的失败（模型缺失、ffmpeg 缺失、音频读不出等）。"""


#: 单次 onnx 推理的帧数上限（100 帧/秒 ⇒ 6000 = 60 秒）。
#: 实测 onnxruntime 跑 CAM++ 的内存随输入时长**线性**增长（≈2.2MB/秒音频）：
#: 300 秒 ≈ 0.7GB、600 秒 ≈ 1.35GB、1200 秒 ≈ 2.7GB（build/_vp_mem_probe.py）。
#: 簇打分会把同一说话人的全部 cue 拼接后**一次**推理（score_by_speaker /
#: score_clusters 里的 np.concatenate），长片十几分钟的素材在低内存机器上
#: 直接 bad allocation（报错节点 /head/layer1/…/Conv_output_0_nchwc）。
#: 分块推理 + 子向量取均值后：同人语音 240 秒长轨单跑与 60 秒分块对同一模板
#: 的得分偏差 < 1e-4（build/_vp_margin_check.py），647 秒素材峰值内存从
#: 1.5GB 降到 0.34GB 封顶（build/_vp_fresh_mem.py），与素材时长无关。
EMBED_MAX_FRAMES = 6000


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

    def _embed_frames(self, feats):
        """一段 fbank 帧矩阵 -> 单个 L2 归一化向量（一次 onnx 推理）。"""
        x = feats[None, :, :].astype(np.float32)
        y = self._session().run(None, {self._in: x})[0][0]
        y = np.asarray(y, dtype=np.float32)
        nrm = float(np.linalg.norm(y))
        return y / (nrm if nrm > 1e-9 else 1.0)

    def embed(self, samples, sample_rate=SAMPLE_RATE):
        """一段音频 -> L2 归一化后的 192 维向量。音频过短会抛 VoiceprintError。

        内部先做两道预处理（见模块头）：
          ① `trim_silence` 能量 VAD 剪掉静音/长停顿——静音帧经 log(eps) 截断
            后不再能被「减全局均值」抵消，会实打实地污染嵌入；
          ② `normalize_rms` 把电平归一到 -20 dBFS，使结果与录音增益无关
            （比峰值归一化稳：单个爆音不再会把整段人声压到地板）。
        超过 `EMBED_MAX_FRAMES` 帧的长输入按块分别推理、子向量取均值后再归一化
        ——单次推理的内存随输入时长线性增长，不设上限会把长片素材的簇打分
        （整簇音频拼接后一次推理）顶到 bad allocation。
        """
        if sample_rate != SAMPLE_RATE:
            samples = resample_linear(np.asarray(samples, dtype=np.float32),
                                      sample_rate, SAMPLE_RATE)
        x = normalize_rms(trim_silence(samples, SAMPLE_RATE))
        feats = fbank(x, SAMPLE_RATE)
        if feats.shape[0] < 10:
            raise VoiceprintError("音频太短（%d 帧），至少需要约 0.2 秒人声"
                                  % feats.shape[0])
        # 模型元数据 feature_normalize_type=global-mean：逐维减时间均值
        # ⚠ 必须先对**整段**减均值再分块——分块减均值会让每块的直流偏置不同，
        #   与单跑结果产生系统性偏差。
        feats = feats - feats.mean(axis=0, keepdims=True)
        if feats.shape[0] <= EMBED_MAX_FRAMES:
            return self._embed_frames(feats)
        parts = [self._embed_frames(feats[s:s + EMBED_MAX_FRAMES])
                 for s in range(0, feats.shape[0], EMBED_MAX_FRAMES)]
        y = np.mean(np.stack(parts, axis=0), axis=0)
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


def normalize_rms(x, target=RMS_TARGET):
    """把波形 RMS 归一化到目标电平（默认 -20 dBFS），峰值顶格时退化为峰值归一化。

    与 `normalize_peak` 同为增益不变（缩放输入 → 输出逐位一致），但**抗爆音**：
    峰值归一化被一个 0.9 的咔哒声/音效顶着时，整段人声会被压到 -20dB 以下，
    更多 fbank bin 撞上 log 截断、特征系统性偏离（基准 build/_vp_accuracy_*
    实测「干净模板 vs 爆音测试」边际从 0.53 塌到 0.25）。RMS 按**整体能量**定增益，
    单点毛刺几乎不影响；crest 极大的极端素材自动退回峰值语义（gain=1/peak），
    不会削波。
    """
    a = np.asarray(x, dtype=np.float32).reshape(-1)
    if a.size == 0:
        raise VoiceprintError("空音频，无法提取声纹")
    rms = float(np.sqrt(np.mean(a.astype(np.float64) ** 2)))
    if rms < 1e-6:
        raise VoiceprintError("音频几乎无声（RMS %.1e），无法提取声纹" % rms)
    peak = float(np.max(np.abs(a)))
    g = min(target / rms, 1.0 / peak)
    return (a * g).astype(np.float32)


def _runs(mask):
    """True 段列表 [(start, end_excl), ...]（按出现顺序）。"""
    m = np.asarray(mask, dtype=np.int8)
    d = np.diff(np.concatenate(([0], m, [0])))
    starts = np.where(d == 1)[0]
    ends = np.where(d == -1)[0]
    return list(zip([int(s) for s in starts], [int(e) for e in ends]))


def _close_gaps(mask, max_gap):
    """把长度 ≤ max_gap 的 False 间断填成 True（保留语句停顿）。"""
    out = np.asarray(mask, dtype=bool).copy()
    if max_gap <= 0 or not out.any():
        return out
    for s, e in _runs(~out):
        if e - s <= max_gap:
            out[s:e] = True
    return out


def _drop_blips(mask, min_run):
    """把长度 < min_run 的 True 毛刺段清成 False（去爆点/咔哒声）。"""
    out = np.asarray(mask, dtype=bool).copy()
    if min_run <= 1:
        return out
    for s, e in _runs(out):
        if e - s < min_run:
            out[s:e] = False
    return out


def trim_silence(x, sample_rate=SAMPLE_RATE):
    """能量 VAD：剪掉带头尾静音、句间长停顿和孤立爆点，返回「只剩人声」的波形。

    阈值全用**相对 dB**（对录音增益不变，无需先归一化）：
    `thr = min(最响帧 - VAD_DB_HEADROOM, 25% 低分位帧 + VAD_DB_FLOOR_MARGIN)`——
    纯人声片段两者都退到「最响帧 -40dB」，几乎不剪；带头尾静音的片段低分位
    落在静音上，自适应地把静音段排除。随后 ≤0.35s 的间断填回（语句停顿）、
    <0.12s 的孤立响帧丢弃（毛刺），按帧覆盖区间拼接回采样。

    这是**能量** VAD：剪得掉静音，剪不掉 BGM/背景音乐（它们同样有能量），
    重叠说话人也无能为力——那两类要靠声源分离，别指望这里。
    整段人声 < 0.2s 或近乎数字静音（< -75dB）时抛 VoiceprintError，
    让调用方按「判不了」处理（NaN → 保守保留待人工），而不是拿静音硬算一个
    随机向量去污染簇心。
    """
    a = np.asarray(x, dtype=np.float32).reshape(-1)
    if a.size == 0:
        raise VoiceprintError("空音频，无法提取声纹")
    fl = int(round(30.0 * sample_rate / 1000.0))
    sh = int(round(FRAME_SHIFT_MS * sample_rate / 1000.0))
    if a.size < fl:
        return a                                  # 不足一帧：无从判断，原样返回
    n_frames = (a.size - fl) // sh + 1
    # 累计和算帧能量，避免整段展开 (T, 400) 的内存（240s ≈ 24000 帧）
    c = np.concatenate(([0.0], np.cumsum(a.astype(np.float64) ** 2)))
    starts = np.arange(n_frames) * sh
    e = (c[starts + fl] - c[starts]) / float(fl)
    db = 10.0 * np.log10(e + 1e-12)
    mx = float(db.max())
    if mx < VAD_ABS_SILENCE_DB:
        raise VoiceprintError("几乎无人声（最响帧 %.1f dB），无法提取声纹" % mx)
    thr = min(mx - VAD_DB_HEADROOM,
              float(np.percentile(db, VAD_FLOOR_PCTL)) + VAD_DB_FLOOR_MARGIN)
    mask = _drop_blips(
        _close_gaps(db >= thr, int(round(VAD_FILL_GAP_MS / FRAME_SHIFT_MS))),
        int(round(VAD_MIN_RUN_MS / FRAME_SHIFT_MS)))
    parts = [a[s * sh:(k - 1) * sh + fl] for s, k in _runs(mask)]
    kept = sum(len(p) for p in parts)
    if kept < int(VAD_MIN_SPEECH_SECONDS * sample_rate):
        raise VoiceprintError("未检出足够人声（%.2f 秒），无法提取声纹"
                              % (kept / float(sample_rate)))
    return np.concatenate(parts).astype(np.float32)


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


def _vp_sync_queue(kind, name, obj=None, prev_id=None, embedding=None):
    """把录入/删除排进**声纹同步**待传队列（best-effort，绝不影响主流程）。

    声纹同步是独立通道（`src/voiceprint_sync.py`，数据落 `data/vp_sync/` 与
    远端 `vp_inbox/`），与字幕校准知识同步（`subtitle_calib_merged` 的
    kb-sync / kb-push）**互不干涉**。队列由引擎启动/退出同步或
    `python src/voiceprint_sync.py sync|push` 冲刷；`VT_NO_VP_SYNC=1` 可单独关停。
    """
    try:
        import voiceprint_sync as _vps
        if kind == "upsert":
            _vps.queue_upsert(name, obj, prev_id)
        else:
            _vps.queue_tombstone(name, prev_id,
                                 _vps.embedding_fp(embedding or []))
    except Exception:  # noqa: BLE001  同步是附加能力，坏了也不能挡住录入/删除
        pass


def _vp_prev_sync(p):
    """读旧副本的 (sync_id, embedding)——重录/追加时用于构造 supersedes 与指纹。

    同步副本直接取 sync_id；**自录副本没有 sync_id**，改用文件内容确定性重建
    本机条目 id（own_entry_id）——fold 语义下重录若不带 supersedes，旧条目仍
    alive、旧片段会被折进新模板，「重录=替换」会退化成「重录=追加」。
    文件内容 == 当年入队 value（入队前剥同步标记），重建是可靠的。"""
    try:
        with open(p, encoding="utf-8-sig") as fh:
            prev = json.load(fh) or {}
    except (OSError, ValueError):
        return None, []
    emb = prev.get("embedding") or []
    pid = prev.get("sync_id")
    if pid:
        return pid, emb
    try:
        import voiceprint_sync as _vps
        name = os.path.splitext(os.path.basename(p))[0]
        return _vps.own_entry_id(name, prev), emb
    except Exception:  # noqa: BLE001
        return None, emb


def save_template(name, embedding, **meta):
    """把声纹模板落盘为 JSON（192 个浮点，便于人工查看与 diff）。

    落盘后排一条 upsert 进声纹同步待传队列（多用户共享）；同名重录时用旧副本
    的 `sync_id` 作 supersedes——其它客户端据此把旧条目判为「被取代」，而不是
    同名不同向量的冲突。"""
    os.makedirs(TEMPLATE_DIR, exist_ok=True)
    obj = {"name": str(name), "dim": int(len(embedding)),
           "created": time.strftime("%Y-%m-%d %H:%M:%S"),
           "embedding": [round(float(v), 6) for v in embedding]}
    obj.update({k: v for k, v in meta.items() if v is not None})
    p = template_path(name)
    prev_id, _prev_emb = _vp_prev_sync(p) if os.path.isfile(p) else (None, [])
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
    _vp_sync_queue("upsert", name, obj, prev_id)
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
    """删除一个声纹模板，并把它从启用名单里摘掉。返回是否真的删了。

    同时排一条 tombstone 进声纹同步待传队列，带上被删副本的向量指纹——其它
    客户端只在指纹匹配时才删本地副本（防「A 删除后 B 已本地重录同名」被误删；
    B 重录产生的 upsert 会随后收敛全场）。"""
    p = template_path(name)
    existed = os.path.isfile(p)
    prev_id, prev_emb = _vp_prev_sync(p) if existed else (None, [])
    try:
        os.remove(p)
    except OSError:
        existed = False
    sel = load_selection()
    if str(name) in sel:
        save_selection([n for n in sel if n != str(name)])
    if existed:
        _vp_sync_queue("tombstone", name, prev_id=prev_id, embedding=prev_emb)
    return existed


def _mean_unit(vecs):
    """多条 L2 归一化向量取均值再归一化（多片段录入/分块推理共用的池化）。"""
    v = np.mean(np.stack(vecs, axis=0), axis=0)
    nrm = float(np.linalg.norm(v))
    return v / (nrm if nrm > 1e-9 else 1.0)


def _local_author():
    """本机 client_id 前 8 位（叶子的来源标注；同步不可用时为空串）。"""
    try:
        import voiceprint_sync as _vps
        return str(_vps.config()["client_id"])[:8]
    except Exception:  # noqa: BLE001
        return ""


def _embedding_fp(v):
    """向量指纹（与 voiceprint_sync.embedding_fp 同口径；其不可用时本地复刻）。"""
    import hashlib
    try:
        import voiceprint_sync as _vps
        return _vps.embedding_fp(v)
    except Exception:  # noqa: BLE001
        pass
    return hashlib.sha256(json.dumps(
        [round(float(x), 6) for x in v]).encode("utf-8")).hexdigest()[:16]


def _make_leaf(agg, weight, n, author=""):
    """一次录入/追加动作 -> 一个折叠叶子（round(6) 与落盘口径一致）。"""
    v = [round(float(x), 6) for x in np.asarray(agg, dtype=np.float64).reshape(-1)]
    return {"fp": _embedding_fp(v), "v": v, "w": float(weight),
            "n": int(n), "author": str(author or "")}


def _plain_template(obj):
    """load_template 的产物（embedding 是 numpy）-> 纯 Python 结构（喂折叠用）。"""
    if not isinstance(obj, dict):
        return {}
    out = dict(obj)
    e = out.get("embedding")
    if isinstance(e, np.ndarray):
        out["embedding"] = [float(x) for x in e.reshape(-1)]
    return out


def enroll_pcm(clips, name="主播", encoder=None, source=None, base=None, **meta):
    """录入/追加声纹核心：逐片段提向量 →（追加时与旧模板折叠）→ 落盘。

    `clips` 为 16k 单声道 PCM 列表。多片段录入比单片段稳得多（基准
    build/_vp_accuracy_* 实测判定边际 +0.04~+0.09）：单片段容易被
    BGM / 重叠说话 / 爆音带偏，多片段均值把这类随机偏差摊平。
    任两片相似度低于 `DEFAULT_THRESHOLD` 时**拒绝落盘**——片段里混了
    别人比「没录上」更有害：坏模板会让整批 cue 误判。

    `base` 为可选的已有模板 dict（`enroll(append=True)` 传入）——**追加模式**：
    本批片段先内部一致性校验，再与旧模板做加权并集折叠（旧叶子 trusted、
    不会被翻旧账；新叶子对每片旧叶子过 0.55 同人守卫），不通过即拒绝。
    多用户同步到达的同名数据在 voiceprint_sync.apply_upserts 里走同一个
    fold_leaves，本机追加与远端迭代是**同一条数学路径**。

    模板除 embedding 外记录迭代字段：weight（合成长度，折叠权重）、
    clips、mix（叶子列表）、sources（贡献者），供同步折叠与界面展示。

    返回模板 dict（含 `clips` 片段总数与 `consistency` 最低两两相似度）。
    """
    enc = encoder or VoiceprintEncoder()
    if not clips:
        raise VoiceprintError("没有可用的参考片段")
    embs = []
    seconds = 0.0
    for c in clips:
        if len(c) < SAMPLE_RATE // 5:
            raise VoiceprintError("参考片段太短（%.2f 秒），建议 10 秒以上"
                                  % (len(c) / float(SAMPLE_RATE)))
        embs.append(enc.embed(c))
        seconds += len(c) / float(SAMPLE_RATE)
    if len(embs) > 1:
        pairs = [cosine(embs[i], embs[j])
                 for i in range(len(embs))
                 for j in range(i + 1, len(embs))]
        worst = min(pairs)
        if worst < DEFAULT_THRESHOLD:
            raise VoiceprintError(
                "片段间声纹不一致（最低相似度 %.2f < %.2f），疑似混入了他人"
                "声音；请每段只保留目标说话人，或缩短/移动片段后重试"
                % (worst, DEFAULT_THRESHOLD))
    else:
        worst = None
    agg = embs[0] if len(embs) == 1 else _mean_unit(embs)
    # 合成长度 w = |Σ 片段向量|：折叠按 w 加权等效于对全部底层片段向量求均值
    s = np.sum(np.stack(embs, axis=0), axis=0)
    r = float(np.linalg.norm(s))
    leaf = _make_leaf(agg, max(r, 1e-9), len(embs), _local_author())
    appended = base is not None
    if base is None:
        obj = {"embedding": leaf["v"], "weight": leaf["w"],
               "clips": leaf["n"], "mix": [leaf],
               "sources": [leaf["author"]] if leaf["author"] else []}
    else:
        import voiceprint_sync as _vps
        old_leaves = _vps.template_leaves(_plain_template(base))
        if not old_leaves:
            raise VoiceprintError("已有声纹「%s」内容为空，无法追加" % name)
        obj, rejected = _vps.fold_leaves(
            old_leaves + [leaf],
            trusted={l["fp"] for l in old_leaves})
        if obj is None or any(l["fp"] == leaf["fp"] for l in rejected):
            raise VoiceprintError(
                "新片段与已有声纹「%s」不像同一人（相似度 < %.2f）。若这其实是"
                "另一位主播，请换个名字录入；若确认同一人，请检查片段是否"
                "干净（单人、无 BGM、无重叠说话）" % (name, DEFAULT_THRESHOLD))
        seconds += float(base.get("seconds") or 0.0)
        if source is None:
            source = base.get("source")
        meta.setdefault("created", base.get("created"))
        meta.setdefault("start", base.get("start"))
        meta.setdefault("dur", base.get("dur"))
    cons = [c for c in (obj.get("consistency"), worst,
                        (base or {}).get("consistency")) if c is not None]
    if cons:
        obj["consistency"] = round(min(cons), 6)
        meta["consistency"] = obj["consistency"]
    meta["clips"] = obj["clips"]
    meta["weight"] = obj["weight"]
    meta["mix"] = obj["mix"]
    meta["sources"] = obj.get("sources") or []
    path = save_template(name, obj["embedding"], source=source,
                         seconds=round(seconds, 2), **meta)
    return {"name": name, "path": path,
            "embedding": np.asarray(obj["embedding"], dtype=np.float32),
            "seconds": round(seconds, 2), "clips": obj["clips"],
            "consistency": obj.get("consistency"), "appended": appended}


def enroll(src, start=None, dur=None, name="主播", encoder=None, extra=None,
           append=False):
    """录入声纹：从音频/视频截一段（可附多段）提向量并落盘，返回模板 dict。

    `extra` 为可选的 `[(src, start, dur), ...]` 额外参考片段，与主片段一起走
    `enroll_pcm` 的多片段校验 + 均值流程。`append=True` 时**追加到已有同名声纹**
    （旧片段保留、加权并集折叠），而不是覆盖重录——声纹库因此可以不断扩充校准；
    不存在同名声纹则报错提示先录入。⚠ 每段参考越干净越好（单人、无 BGM、
    无重叠说话），建议每段 10~30 秒。
    """
    enc = encoder or VoiceprintEncoder()
    clips = [read_pcm(src, start=start, dur=dur)]
    for s2, st2, du2 in (extra or []):
        clips.append(read_pcm(s2, start=st2, dur=du2))
    base = None
    if append:
        if not os.path.isfile(template_path(name)):
            raise VoiceprintError("没有已录入的声纹「%s」，无法追加（先去掉"
                                  " --append 正常录入，或换个名字）" % name)
        base = load_template(name)
    return enroll_pcm(clips, name=name, encoder=enc,
                      source=os.path.basename(str(src)), start=start, dur=dur,
                      base=base)


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
#: 歧义拒分裕量：最佳簇心相似度领先次佳不足此值时，不强行归簇、自成一簇。
#: 防止「卡在两个说话人中间」的 cue 把某簇的簇心拖向另一簇（该簇整组得分
#: 随之偏移，误判整组 cue）。取 0.04：同人向量在 VAD/归一化后的抖动约 ±0.02。
CLUSTER_ASSIGN_MARGIN = 0.04
#: 近重复簇合并阈值：两个**多 cue** 簇的簇心余弦 ≥ 此值视为同一说话人被拆开，
#: 合并后重指派。取 0.6 依据实测分布（异人上限 0.450 / 同人下限 0.681，0.6 在
#: 空档上半区）；宁可不合并也不误并两个声音相近的不同说话人。
CLUSTER_MERGE_THRESHOLD = 0.6
#: 簇心更新的时长权重指数：0 = 等权（旧行为），1 = 按秒线性加权。取 0.5
#: （√秒数）——向量稳定性随时长提升但趋于饱和：长 cue 应占更大权重，又不该
#: 一票定心。等权会让一条 0.5s 的边界 cue 把 10s 立起来的簇心拖走 1/3。
CLUSTER_LENGTH_WEIGHT = 0.5


def _merge_close(members, centroids_of, threshold=CLUSTER_MERGE_THRESHOLD):
    """近重复簇合并（就地改 members，返回是否动过）。

    `centroids_of(members)` 返回与 members 平行的簇心列表（空簇给 None）。
    **只并 ≥2 成员的簇**：单 cue 簇多半是边界拒分产生的离群簇，并回去会把
    刚拒出去的 cue 又拉进别人的簇。合并是防御性的——0.5 归簇阈值下主流程
    几乎走不到这里（能在 pass1 里共存的簇心相似度天然 < 0.5），它兜的是
    「歧义拒分把同一说话人拆成两个多 cue 簇」的边角。每轮重算簇心，避免
    用过期的合并前方向继续比。
    """
    did = False
    while True:
        cents = centroids_of(members)
        best = None
        for i in range(len(members)):
            if len(members[i]) < 2 or cents[i] is None:
                continue
            for j in range(i + 1, len(members)):
                if len(members[j]) < 2 or cents[j] is None:
                    continue
                s = float(np.dot(cents[i], cents[j]))
                if s >= threshold and (best is None or s > best[0]):
                    best = (s, i, j)
        if best is None:
            return did
        _s, i, j = best
        members[i].extend(members[j])
        members[j] = []
        did = True


def cluster_cues(pcm, cues, encoder=None, sample_rate=SAMPLE_RATE,
                 threshold=CLUSTER_THRESHOLD,
                 min_seconds=CLUSTER_MIN_SECONDS):
    """按声纹把 cue 就地聚成说话人簇（**不依赖 ASR 的 `[说话人N]`**）。

    为什么需要：ASR 端的说话人分离**不是所有端点都支持**——本项目实测
    `qwen-audio-3.0-asr-flash` 走百炼 Token Plan 时，配置里 `asr_diarize=True`
    也照样拿不到标签（只有 3.1 原生 / 火山极速版 / AssemblyAI / Deepgram /
    ElevenLabs / 百炼 Filetrans 支持）。而声纹向量我们本来就算得出来，干脆自己聚。

    **两遍聚类**（旧版是一遍贪心、等权簇心，实测会被边界 cue 拖心、被说话人
    内部抖动拆簇——基准 build/_vp_accuracy_* 场景 C 可复现）：
      第 1 遍 —— 逐 cue 提向量，**按音频时长降序**贪心立簇，簇心按 √时长
                加权更新（长 cue 向量更稳，先立簇心、权重也更大）；
      第 2 遍 —— 重算全部簇心后**整体重指派**：最佳簇心余弦 ≥ threshold 且
                领先次佳 ≥ `CLUSTER_ASSIGN_MARGIN` 才归簇，否则自成一簇
                （歧义拒分，保簇纯度——归错的代价比单飞大得多）；
      合并   —— 近重复多 cue 簇合并（`_merge_close`）后再重指派一轮。
    顺序全程确定（时长降序、同长按 cue 序号），结果可复现，不用随机初始化，
    也不需要 sklearn/scipy。

    返回 `(labels, sizes)`：`labels[i]` 是 cue i 的簇号（**`-1` = 音频不足，
    未参与聚类**），`sizes` 是 `{簇号: 条数}`，簇号按 cue 出现顺序紧凑编号。
    """
    enc = encoder or VoiceprintEncoder()
    chunks = _cue_chunks(pcm, cues, sample_rate)
    min_len = int(min_seconds * sample_rate)
    order = []                      # [(cue_index, duration_seconds)]，时长降序
    for i, ch in enumerate(chunks):
        if ch is not None and len(ch) >= min_len:
            order.append((i, len(ch) / float(sample_rate)))
    order.sort(key=lambda t: (-t[1], t[0]))

    vecs = {}                       # cue_index -> 向量（只提参与者的）
    for idx, _dur in order:
        try:
            vecs[idx] = enc.embed(chunks[idx], sample_rate)
        except VoiceprintError:
            pass
    weights = {i: d ** CLUSTER_LENGTH_WEIGHT for i, d in order if i in vecs}

    def _centroid_of(mem):
        s = np.zeros_like(vecs[mem[0]])
        for i in mem:
            s += vecs[i] * weights[i]
        return s / (float(np.linalg.norm(s)) + 1e-9)

    def _pick(sims, threshold):
        """(是否可归属, 最佳簇号)。歧义拒分：领先次佳不足裕量时不可归属。"""
        ranked = sorted(range(len(sims)), key=lambda k: (-sims[k], k))
        best = ranked[0]
        ok = sims[best] >= threshold and (
            len(ranked) == 1
            or sims[best] - sims[ranked[1]] >= CLUSTER_ASSIGN_MARGIN)
        return ok, best

    labels = [-1] * len(cues)
    if not vecs:
        return labels, {}

    # 第 1 遍：按时长降序贪心立簇（在线 √时长加权更新簇心）
    members = []                    # [ [cue_index...] ]
    cents = []                      # 与 members 平行的归一化簇心
    for idx, _dur in order:
        if idx not in vecs:
            continue
        v = vecs[idx]
        if cents:
            sims = [float(np.dot(v, c)) for c in cents]
            ok, best = _pick(sims, threshold)
            if ok:
                labels[idx] = best
                members[best].append(idx)
                cents[best] = _centroid_of(members[best])
                continue
        labels[idx] = len(cents)
        members.append([idx])
        cents.append(v.copy())

    # 第 2 遍：近重复簇合并 → 重算簇心 → 整体重指派（含歧义拒分）；
    # 两轮兜住「合并改变格局后又有 cue 可落回」的边角。全程确定顺序。
    for _round in range(2):
        _merge_close(members,
                     lambda ms: [_centroid_of(m) if m else None for m in ms])
        new_mem = []
        new_cents = []
        lab = {}
        for idx, _dur in order:
            if idx not in vecs:
                continue
            v = vecs[idx]
            sims = [float(np.dot(v, c)) for c in new_cents]
            if sims:
                ok, best = _pick(sims, threshold)
            else:
                ok, best = False, -1
            if not ok:
                best = len(new_mem)
                new_mem.append([])
            lab[idx] = best
            new_mem[best].append(idx)
            if len(new_mem[best]) == 1:
                new_cents.append(v.copy())
            else:
                new_cents[best] = _centroid_of(new_mem[best])
        members = new_mem

    # 簇号按 cue 出现顺序紧凑编号
    remap = {}
    out = []
    for i in range(len(cues)):
        lb = lab.get(i, -1)
        if lb < 0:
            out.append(-1)
        else:
            out.append(remap.setdefault(lb, len(remap)))
    sizes = {}
    for lb in out:
        if lb >= 0:
            sizes[lb] = sizes.get(lb, 0) + 1
    return out, sizes


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
    p1.add_argument("--clip", action="append", default=[],
                    help="额外参考片段（可多给），格式 \"路径,起点秒,时长秒\"；"
                         "多片段先做同人一致性校验再取均值，模板更稳")
    p1.add_argument("--append", action="store_true",
                    help="追加到已有同名声纹（旧片段保留、加权并集折叠）；"
                         "默认是覆盖重录")

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
        extra = []
        for raw in (args.clip or []):
            # 从右侧切两段逗号：路径里出现逗号也不误伤
            parts = str(raw).rsplit(",", 2)
            if len(parts) != 3:
                raise VoiceprintError("--clip 格式应为 \"路径,起点秒,时长秒\"：%s"
                                      % raw)
            extra.append((parts[0].strip().strip('"'),
                          float(parts[1]), float(parts[2])))
        r = enroll(args.src, args.start, args.dur, args.name, extra=extra,
                   append=args.append)
        if r.get("appended"):
            print("已追加到声纹「%s」：现共 %d 个片段 %.1f 秒 -> %s"
                  % (r["name"], r["clips"], r["seconds"], r["path"]))
        elif r["clips"] > 1:
            print("已录入声纹「%s」：%d 段共 %.1f 秒（一致性 %.3f）-> %s"
                  % (r["name"], r["clips"], r["seconds"],
                     r["consistency"], r["path"]))
        else:
            print("已录入声纹「%s」：%.1f 秒 -> %s"
                  % (r["name"], r["seconds"], r["path"]))
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
