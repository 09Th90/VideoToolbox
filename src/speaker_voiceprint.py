# -*- coding: utf-8 -*-
# @version 2.5.3
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
    # **推荐**：自动选段录入（全片扫描 → 主说话人 → 频谱门控排 BGM → 分箱取 12 段
    # → 录完当场做素材体检 + 库内混淆检查；体检判为 risky 时退出码 3）
    python speaker_voiceprint.py enroll --src 视频.mp4 --name 主播 --auto
    # 手工选段（已知哪一段干净时更快）：
    python speaker_voiceprint.py enroll --src 视频.mp4 --start 12 --dur 20 --name 主播
    # 多片段录入（先做同人一致性校验，再取均值，模板更稳）：
    python speaker_voiceprint.py enroll --src 视频.mp4 --start 12 --dur 20 --name 主播 \
                                        --clip "另一段.mp4,30,15" --clip "另一段.mp4,90,10"
    # 追加到已有同名声纹（扩充校准，不覆盖；--auto 同样支持）：
    python speaker_voiceprint.py enroll --src 视频.mp4 --start 200 --dur 15 \
                                        --name 主播 --append
    python speaker_voiceprint.py assess --src 视频.mp4 [--name 主播]   # 素材体检（不落盘）
    python speaker_voiceprint.py audit                              # 声纹库体检 + 混淆矩阵
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

上面两道是**提特征时**的预处理，录入片段与待筛 cue 一视同仁。此外还有一道只
作用于**选段阶段**的判据（v2.2.0，见 `gate_speech_runs`）：
    ③ 频谱门控（谱平坦度 + 4k-8k 高频衰减）挑出「像人声」的时刻。能量 VAD 判不了
       「是不是人声」——BGM / 游戏音同样有能量，`trim_silence` 照单全收（其
       docstring 已明说剪不掉 BGM）。实测口径（逐 0.2 秒帧）：干净人声素材谱平坦度
       中位 0.005、4k-8k 衰减 -19.6 dB；全程铺 BGM 的素材是 0.030 / -9.1 dB。
       门控**只挑时间区间、不改音频**：筛选时 cue 是原样切出来直接提向量的，录入侧
       任何独有的滤波（低通 / 谱减 / 降噪）都会造成两侧口径不一致，反而拉低实战得分。

配套两项**录入后自查**，因为「坏模板」在录入当下不会报任何错：
  · `assess_material` 素材体检——一份全程铺着 BGM 的录播能录出批内一致性 0.87、
    对本片每个窗口都给 0.91~0.97 的模板，常规指标全漂亮，可它认的是这段录音的
    **声学底**而不是嗓音：换一份同主播、不同 BGM 的素材就会整体掉分（误丢主播
    字幕）。体检按六项实测标定的门槛把它点出来（背景音能量占比 / 最长人声连续段 /
    背景帧电平 / 频谱形态 / 有无低分对照窗 / 人声段与背景音段的等长落差）。
    ⚠ 判读输出分**告警**与**提示**两类：单人干净素材本来就该 100% 判为本人、本来
    就没有纯背景音段，把这类「没测到」算成告警会把好素材误判成有风险（第一版就
    踩了，已知可用的素材被判 risky）。
  · `check_confusion` 库内混淆检查——新声纹与已录入声纹逐对算余弦，超过 keep 线
    当场告警（实测某库 8 个模板里有 4 对 ≥0.55，最高 0.663，录入时全程无感）。
    纯余弦、不解码音频，所以手工录入也照样跑。全库矩阵用 `audit` 一次看完。
  结论会写进模板的 `quality` / `auto` 字段（本机录入溯源，不参与同步收敛）。

自动选段（`suggest_clips` / `enroll_auto`，界面默认走这条）把上面这些串成一条：
全片扫描 → 按声纹聚簇取**主说话人**（多人素材自动剔掉嘉宾，并按主簇时间区间
裁剪人声段）→ 频谱门控排掉 BGM 最响的时刻 → 按时间**分箱**拼接（不分箱时片段
会全挤在视频开头，后段音色变化进不来）→ 录入 → 体检 + 混淆检查。实测复现：对
同一份 17 分钟素材，自动选段得到的模板与人工挑段逐轮验证出来的模板余弦 **0.999**。

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
import unicodedata
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
#: gh-proxy 直连镜像（deno 同款通道：镜像**直连通常可用，不需要代理**）。
#: 为什么必须有它——在线安装形态**不随包分发 mihomo**（config.yaml 含节点
#: 凭据，v1.14.1 安全整改），GitHub 直连不通的机器上「下载模型」的最后
#: 生路就是这道镜像；官方源失败自动切镜像，无需用户任何配置。
MODEL_MIRROR_URL = "https://gh-proxy.com/" + MODEL_URL
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
      ③ **gh-proxy 直连镜像**（v1.19.1）：不挂代理直接请求镜像 URL。在线安装
         形态没有内置 mihomo（不随包分发），直连又不通的机器全靠这一步；
         镜像在国内直连可用（deno 已实测同通道）。
      ④ 前面都失败 → 拉起内置 mihomo 再试一次（仅离线完整版有 mihomo）。
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

    def _opener(proxy):
        if not proxy:
            return None
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy}))

    def _fetch(url, proxy=None):
        op = _opener(proxy)
        req2 = urllib.request.Request(
            url, headers={"User-Agent": "VideoToolbox/1.18"})
        resp = (op.open(req2, timeout=timeout) if op is not None
                else urllib.request.urlopen(req2, timeout=timeout))
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
    tried = []
    if running:
        tried.append(("代理（已在运行）", MODEL_URL, running))
    tried.append(("直连", MODEL_URL, None))
    tried.append(("gh-proxy 镜像", MODEL_MIRROR_URL, None))
    last = None
    ok = False
    for label, url, px in tried:
        try:
            _fetch(url, px)
            ok = True
            break
        except Exception as e:  # noqa: BLE001
            last = (label, e)
            _cleanup()

    if not ok:
        px = None
        try:
            import video_toolbox as _e
            _pa = _e.ytdlp_proxy_args()
            px = _pa[1] if _pa else None
        except Exception:  # noqa: BLE001
            px = None
        if not px:
            raise VoiceprintError(
                "下载失败（%s：%s）；系统代理与内置代理均不可用。可手动下载（官方或镜像）"
                "后放到 %s\n镜像地址：%s"
                % (last[0] if last else "直连",
                   str(last[1])[:120] if last else "未知", MODEL_DIR,
                   MODEL_MIRROR_URL))
        try:
            _fetch(MODEL_URL, px)
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


# ------------------------------------------------- 频谱门控 / 自动选段 / 素材体检
#: **能量 VAD 判不了「是不是人声」**：BGM 与游戏音同样有能量，`trim_silence`
#: 会照单全收（其 docstring 已明说「剪不掉 BGM」）。这里补一道**频谱**判据，
#: 门限来自实测（2026-10-14，两份主播录播逐 0.2 秒帧统计）：
#:   干净人声素材    谱平坦度中位 0.041、4k-8k 相对 500-2k 衰减 -14.4 dB
#:   带连续 BGM 素材 谱平坦度中位 0.168、衰减 -2.7 dB
#: 取两者之间偏人声一侧。⚠ 门控**只用于挑参考片段的时间区间**，不改音频本身：
#: 筛选时 cue 是原样切出来直接提向量的，录入侧任何独有的滤波（低通、谱减、
#: 降噪）都会造成两侧口径不一致，反而拉低实战得分。
GATE_FRAME_SEC = 0.2
SPEECH_FLAT_MAX = 0.08
SPEECH_HF_MAX_DB = -8.0
GATE_CLOSE_GAP_SEC = 0.4
GATE_MIN_RUN_SEC = 1.0
GATE_LEVEL_HEADROOM_DB = 45.0
#: 严格档：专门用来挑「背景音对照段」（判为非人声的段落），素材体检靠它算落差
STRICT_FLAT_MAX = 0.05
STRICT_HF_MAX_DB = -12.0
STRICT_MIN_RUN_SEC = 3.0
#: 自动选段：片段数 / 每片段目标人声秒数 / 单片段最短人声秒数
AUTO_CLIPS = 12
AUTO_CLIP_SEC = 12.0
AUTO_MIN_CLIP_SEC = 3.0
#: 扫描窗口与步长；长素材按 `AUTO_MAX_SCAN_WINDOWS` 自动放大步长
#: （2 小时的片子若按 6 秒步长要提 1200 个向量，白等十几分钟）
AUTO_SCAN_WIN_SEC = 12.0
AUTO_SCAN_STEP_SEC = 6.0
AUTO_MAX_SCAN_WINDOWS = 200
AUTO_WIN_SPEECH_RATIO = 0.3    # 窗内门控人声帧占比下限，低于则不参与聚簇
#: 自动选段的最短素材长度。**要能按声纹聚簇分辨主说话人**，至少得有 3 个扫描窗
#: （= 3×步长 + 窗长 ≈ 30 秒），再短就退化成「把全片都当主说话人」——多人素材
#: 会把嘉宾一起录进去，最后被 `enroll_pcm` 的一致性校验拦下，报错却指向「片段
#: 不干净」，用户看不出真因。所以这里直接拒并指路手工选段。
AUTO_MIN_TOTAL_SEC = 45.0
#: 拼接处的升余弦淡变长度。直接对接会留下阶跃（咔哒声），而咔哒声是宽频毛刺，
#: 会实打实污染嵌入（同 `normalize_rms` 防爆音的顾虑）。
STITCH_FADE_SEC = 0.010
#: 素材体检判读门槛。**按两份真实主播录播标定**（2026-10-14，
#: `scripts/dev/voiceprint_material_calib.py` 可复跑）：一份干净人声素材
#: （判「可用」）、一份全程铺 BGM 的素材（判「可疑」）。门槛一律取在两组实测值
#: 之间并留余量：
#:   指标                    可用       可疑       门槛
#:   背景音能量占比           1.6%      31.1%     > 15%
#:   最长人声连续段          150.6s     13.6s     < 30s
#:   全片最低窗口得分         0.255     0.909     > 0.60（且无低分窗）
#:   4k-8k 高频衰减         -19.6dB    -9.1dB    > -12dB
#:   谱平坦度 中位 / p75     0.005/0.017 0.030/0.080  > 0.02 / > 0.05
#:   背景帧电平（相对最响）   -14.8dB   -6.9dB    > -12dB
#: ⚠ 只有 2 份样本，门槛的作用是「把这两类分开」，不是精确边界；换新素材实测后
#:   应当再校。
#: ⚠⚠ 旧判据「人声段 vs 背景音段落差 < 0.05 就告警」在正对照上**误报**：可用素材
#:   +0.008、可疑素材 +0.001，毫无区分力。根因是对照段用**严格档**门控挑，在干净
#:   素材里那些段仍然是人声（擦音/笑声的谱平坦度本来就偏高），于是两侧都在测同
#:   一个人的嗓音。现改为：对照段用**松档**门控的补集（连松档都不像人声才算背景
#:   音），且只保留「落差为负」这一强信号（背景音比人声还像本人 = 模板认错了东西）。
QUALITY_FLAT_WARN = 0.02           # 逐帧谱平坦度中位高于此值 = 宽频成分多
QUALITY_FLAT_P75_WARN = 0.05       # 谱平坦度 p75 高于此值 = 相当比例的时刻是宽频音
QUALITY_HF_WARN_DB = -12.0         # 4k-8k 高频衰减不足此值 = 高频一直在响
QUALITY_BG_LEVEL_WARN_DB = -12.0   # 背景帧电平高出此值（相对最响帧）= 背景音几乎不停
QUALITY_BG_ENERGY_WARN_PCT = 15.0  # 背景音能量占比高于此值 = 背景音压得人声无处躲
QUALITY_VOICE_RUN_WARN_SEC = 30.0  # 最长人声连续段短于此值 = 人声被背景音打碎
QUALITY_WIN_MIN_WARN = 0.60        # 全片最低窗口得分高于此值 = 素材没有低分对照窗
QUALITY_MARGIN_INVERTED = 0.0      # 落差低于此值（背景音比人声更像本人）才告警
#: 自动选段的「人声太碎」提示门槛。刻意比体检的 30 秒宽：拼接本身是正常做法，
#: 只有碎到 10 秒以下才值得提醒用户「这份素材的背景音很密」。
AUTO_FRAGMENT_WARN_SEC = 10.0
QUALITY_MAX_WINDOWS = 40           # 体检逐窗打分的窗口上限
QUALITY_MAX_VOICE_SEGS = 12        # 体检用的人声段上限
QUALITY_MAX_BG_SEGS = 8            # 体检用的背景音对照段上限
QUALITY_VOICE_RATIO_MIN = 0.6      # 人声段候选窗的门控人声占比下限


def spectral_frame_features(pcm, frame_sec=GATE_FRAME_SEC,
                            sample_rate=SAMPLE_RATE):
    """逐帧 (谱平坦度, 4k-8k 相对 500-2k 的 dB, 帧电平 dB)——纯 numpy 整批算。

    两个判据的取舍：
      · **谱平坦度** = 功率谱（100~7000Hz）的几何均值 / 算术均值。谐波结构清晰
        的语音低（能量集中在少数 formant 峰上），宽频的音乐/游戏音/噪声高。
      · **高频衰减** = 4k-8k 与 500-2k 的频带能量差。语音能量集中在 formant 区，
        4kHz 以上迅速掉落；镲片、枪声、合成器 pad 则一路平推到高频。
    两者都要，是因为单看任一个都会误判：气声/擦音（低能量的宽频语音）谱平坦度
    偏高但高频衰减仍明显；低音铺底（bass pad）高频衰减够但谱平坦度极低。
    """
    a = np.asarray(pcm, dtype=np.float32).reshape(-1)
    n = max(8, int(round(frame_sec * sample_rate)))
    cnt = int(a.size // n)
    if cnt == 0:
        z = np.zeros(0, dtype=np.float64)
        return z, z.copy(), z.copy()
    fr = a[:cnt * n].reshape(cnt, n)
    sp = np.abs(np.fft.rfft(fr * np.hanning(n).astype(np.float32), axis=1)) ** 2
    f = np.fft.rfftfreq(n, 1.0 / sample_rate)

    def _band(lo, hi):
        m = (f >= lo) & (f < hi)
        return 10.0 * np.log10(np.maximum(sp[:, m].sum(axis=1), 1e-12))

    p = sp[:, (f >= 100.0) & (f < 7000.0)]
    flat = (np.exp(np.log(np.maximum(p, 1e-12)).mean(axis=1))
            / np.maximum(p.mean(axis=1), 1e-12))
    rms = np.sqrt(np.maximum((fr.astype(np.float64) ** 2).mean(axis=1), 1e-20))
    return flat, _band(4000.0, 8000.0) - _band(500.0, 2000.0), 20.0 * np.log10(rms)


def gate_speech_runs(pcm, flat_max=SPEECH_FLAT_MAX, hf_max=SPEECH_HF_MAX_DB,
                     close_gap=GATE_CLOSE_GAP_SEC, min_run=GATE_MIN_RUN_SEC,
                     frame_sec=GATE_FRAME_SEC, sample_rate=SAMPLE_RATE):
    """频谱门控 -> `(mask, runs, features)`；`runs` = [(起点秒, 时长秒), ...]。

    三条判据同时成立才算「像人声」的帧：谱平坦度低、高频衰减够、电平不在地板上
    （最后一条排除静音帧——静音的谱平坦度是随机的，会把纯静音段误判成人声）。
    随后走与 `trim_silence` **同一套**形态学（`_close_gaps` / `_drop_blips`）：
    ≤`close_gap` 秒的间断填回（语句停顿不该把一句话切成两半），<`min_run` 秒
    的孤立段丢弃（碎段拼进参考片段只会增加拼接痕迹）。
    """
    flat, hf, db = spectral_frame_features(pcm, frame_sec, sample_rate)
    if flat.size == 0:
        return np.zeros(0, dtype=bool), [], (flat, hf, db)
    # 电平判据取「相对最响帧 -45dB」与「绝对数字静音地板 -75dB」中较严的一个，
    # 口径同 `trim_silence`：整段录音很轻（最响帧才 -50dB）时，纯相对判据会把
    # -95dB 的数字静音也放进来，而静音帧的谱平坦度是随机值，可能蒙混过关。
    floor = max(float(db.max()) - GATE_LEVEL_HEADROOM_DB, VAD_ABS_SILENCE_DB)
    mask = (flat < flat_max) & (hf < hf_max) & (db > floor)
    mask = _drop_blips(_close_gaps(mask, max(1, int(round(close_gap / frame_sec)))),
                       max(1, int(round(min_run / frame_sec))))
    runs = [(s * frame_sec, (e - s) * frame_sec) for s, e in _runs(mask)]
    return mask, runs, (flat, hf, db)


def stitch_runs(pcm, runs, target_sec=AUTO_CLIP_SEC, n_bins=None,
                min_sec=AUTO_MIN_CLIP_SEC, fade_sec=STITCH_FADE_SEC,
                sample_rate=SAMPLE_RATE, total_sec=None):
    """把门控挑出的人声段拼成参考片段；给 `n_bins` 则**按时间分箱、每箱一片**。

    为什么必须分箱：不分箱时开头几分钟的人声段就能凑满全部片段，模板只覆盖
    视频开头——后段的音色变化（喊叫、低语、疲劳）一点没进模板，换素材就掉分。
    分箱后每箱各出一段，铺满全片（2026-10-14 实测：不分箱的 12 段全挤在前
    240 秒，分箱后覆盖 0~1030 秒全片）。

    拼接处做 `fade_sec` 升余弦淡变：直接对接会留下阶跃（咔哒声），而咔哒声是
    宽频毛刺，会污染嵌入。返回 [(samples, [(起点秒, 时长秒), ...]), ...]，
    人声不足 `min_sec` 的箱直接跳过（宁缺毋滥）。
    """
    a = np.asarray(pcm, dtype=np.float32).reshape(-1)
    total = float(total_sec if total_sec is not None
                  else a.size / float(sample_rate))
    rs = [(float(s), float(d)) for s, d in (runs or [])
          if d > 0 and s >= 0 and s + d <= total + 1e-6]
    if not rs:
        return []
    nb = max(1, int(n_bins or 1))
    edges = np.linspace(0.0, total, nb + 1)
    fn = max(1, int(round(fade_sec * sample_rate)))
    ramp = (0.5 - 0.5 * np.cos(np.linspace(0.0, 2.0 * np.pi, fn))).astype(np.float32)
    out = []
    for bi in range(nb):
        buf, spans, acc = [], [], 0.0
        for s, d in rs:
            if acc >= target_sec or not (edges[bi] <= s < edges[bi + 1]):
                continue
            x = a[int(s * sample_rate):int((s + d) * sample_rate)].copy()
            if x.size == 0:
                continue
            if x.size > fn * 2:
                x[:fn] *= ramp
                x[-fn:] *= ramp[::-1]
            buf.append(x)
            spans.append((round(s, 3), round(d, 3)))
            acc += d
        if buf and acc >= min_sec:
            out.append((np.concatenate(buf).astype(np.float32), spans))
    return out


def _clip_to_intervals(runs, intervals, pad=1.0):
    """把人声段裁剪到若干时间区间的并集内：跨界的段被**切开**，界外部分丢掉。

    为什么不是「整段取舍」：早先的实现按段中点判断归属，于是一个横跨两位说话人
    的长段会被整段收下（实测合成素材里 0~60 秒一段直通，把第二个人一起录进了
    模板，最后只被 `enroll_pcm` 的一致性校验兜住，报错还指向「片段不干净」）。
    按区间裁剪后，长段会在主说话人窗口的边界处被切断。

    ⚠ 粒度上限就是扫描窗（12 秒）：**同一个窗口内**插话的嘉宾仍然切不掉，那道
    兜底是 `enroll_pcm` 的批内一致性校验（相似度 < 0.55 拒绝落盘）。
    `pad` 给区间两端各留一点余量，避免把边界上的半个字切掉。
    """
    iv = sorted((float(lo) - pad, float(hi) + pad) for lo, hi in (intervals or []))
    if not iv:
        return list(runs)
    pieces = []
    for s, d in runs:
        e = float(s) + float(d)
        for lo, hi in iv:
            a, b = max(float(s), lo), min(e, hi)
            if b - a > 1e-6:
                pieces.append((a, b - a))
    pieces.sort()
    out = []
    for s, d in pieces:                      # pad 造成的重叠合并回去
        if out and s <= out[-1][0] + out[-1][1] + 1e-6:
            p, pd = out[-1]
            out[-1] = (p, max(pd, s + d - p))
        else:
            out.append((s, d))
    return out


def _progress(progress, msg):
    """阶段回调（best-effort）：全片扫描要跑一两分钟，没反馈用户会以为卡死。"""
    if not progress:
        return
    try:
        progress(str(msg))
    except Exception:  # noqa: BLE001  回调坏了不能挡住主流程
        pass


class _ScanWin:
    """给 `cluster_cues` 复用的轻量时间窗（只需 start/end，单位毫秒）。

    刻意**不另写一份聚类**：`cluster_cues` 是两遍聚类（√时长加权立簇 + 整体
    重指派 + 歧义拒分 + 近重复簇合并），有自检 5c/5d 两节盯着。再写一份贪心
    就是两份会各自漂移的实现——自动选段与筛选判定用的必须是同一套簇口径，
    否则「选段时认的主说话人」和「筛选时认的主播」可能不是同一个人。
    """

    __slots__ = ("start", "end", "speaker", "text")

    def __init__(self, start_sec, end_sec):
        self.start = float(start_sec) * 1000.0
        self.end = float(end_sec) * 1000.0
        self.speaker = ""
        self.text = ""


def suggest_clips(src, n_clips=AUTO_CLIPS, clip_sec=AUTO_CLIP_SEC, encoder=None,
                  progress=None, pcm=None, sample_rate=SAMPLE_RATE):
    """自动挑参考片段：全片扫描 → 声纹聚簇取主说话人 → 频谱门控 → 分箱拼接。

    为什么需要它（手工给 `--start/--dur` 的三个实测坑，2026-10-14）：
      ① 人耳挑「这段是主播」挑不出 BGM 之外的干净时刻——能量 VAD 也挑不出，
         于是背景音被一起录进模板；
      ② 顺手挑开头一段 → 模板只覆盖视频开头，后段的音色变化一点没进去；
      ③ 素材里有第二位说话人（嘉宾 / 游戏旁白）时，手工很容易把他录进去，
         而 `enroll_pcm` 的一致性校验只有在两人差得够远时才拦得住。
    这里用**主说话人簇**过滤：先按声纹把全片窗口聚簇（复用 `cluster_cues`），
    只保留落在最大簇里的人声段，多人素材因此也能自动只取主播。

    `pcm` 可选：调用方已解码就传进来，省一次全片解码（`enroll_auto` 就是这么用的）。
    返回 dict：`clips`（[(samples, spans)]，直接喂 `enroll_pcm`）、`spans`、
    `dominant`、`speech`、`warnings`（人话告警）等。
    """
    enc = encoder or VoiceprintEncoder()
    if pcm is None:
        _progress(progress, "正在解码音频…")
        pcm = read_pcm(src, sample_rate=sample_rate)
    a = np.asarray(pcm, dtype=np.float32).reshape(-1)
    total = a.size / float(sample_rate)
    warns = []
    if total < AUTO_MIN_TOTAL_SEC:
        raise VoiceprintError(
            "素材太短（%.1f 秒）：自动选段至少要 %.0f 秒才能按声纹聚簇分辨出"
            "主说话人；请改用手工选段（--start/--dur，界面里取消勾选「自动选段」），"
            "或换一段更长的素材" % (total, AUTO_MIN_TOTAL_SEC))

    _progress(progress, "正在做频谱门控（挑人声、排背景音）…")
    mask, runs, (flat, hf, db) = gate_speech_runs(a, sample_rate=sample_rate)
    speech_sec = sum(d for _s, d in runs)
    if not runs:
        raise VoiceprintError(
            "全片找不到「像人声」的段落（谱平坦度 <%.2f 且 4k-8k 衰减 <%.0fdB）。"
            "素材可能以音乐为主，或背景音乐压过了人声——请换一段没有 BGM 的"
            "说话音频，或用手工选段指定区间" % (SPEECH_FLAT_MAX, SPEECH_HF_MAX_DB))
    if speech_sec < AUTO_MIN_CLIP_SEC * 2:
        raise VoiceprintError("门控后只剩 %.1f 秒人声，不足以录入（至少 %.0f 秒）"
                              % (speech_sec, AUTO_MIN_CLIP_SEC * 2))

    _progress(progress, "正在扫描全片、按声纹聚簇（找主说话人）…")
    step = max(AUTO_SCAN_STEP_SEC, total / float(AUTO_MAX_SCAN_WINDOWS))
    wins = []
    t = 0.0
    while t + AUTO_SCAN_WIN_SEC <= total:
        i0 = int(t / GATE_FRAME_SEC)
        i1 = min(int(mask.size), int((t + AUTO_SCAN_WIN_SEC) / GATE_FRAME_SEC))
        if i1 > i0 and float(mask[i0:i1].mean()) >= AUTO_WIN_SPEECH_RATIO:
            wins.append(_ScanWin(t, t + AUTO_SCAN_WIN_SEC))
        t += step
    dom_iv, share, n_clusters = [(0.0, total)], 1.0, 1
    if len(wins) >= 3:
        labels, sizes = cluster_cues(a, wins, enc, sample_rate=sample_rate)
        n_clusters = max(1, len(sizes))
        dom = max(sizes, key=lambda k: (sizes[k], -k))
        iv = [(w.start / 1000.0, w.end / 1000.0)
              for w, l in zip(wins, labels) if l == dom]
        if iv:
            dom_iv, share = iv, float(sizes[dom]) / float(len(wins))
    if len(dom_iv) < len(wins):
        kept = _clip_to_intervals(runs, dom_iv)
        if sum(d for _s, d in kept) >= AUTO_MIN_CLIP_SEC * 2:
            drop = speech_sec - sum(d for _s, d in kept)
            if drop >= 1.0:
                warns.append("素材里检测到多个说话人：已剔除主说话人之外的 %.0f 秒"
                             "人声（主簇占 %.0f%% 扫描窗）" % (drop, share * 100.0))
            runs, speech_sec = kept, sum(d for _s, d in kept)
        else:
            warns.append("主说话人簇内的人声不足（%.0f 秒），已退回使用全部门控人声段"
                         % sum(d for _s, d in kept))
    if share < 0.6:
        warns.append("主说话人只占 %.0f%% 的扫描窗：素材可能是多人对谈，"
                     "自动选段的结果请人工确认" % (share * 100.0))

    longest = max(d for _s, d in runs)
    if longest < AUTO_FRAGMENT_WARN_SEC:
        warns.append("最长人声连续段只有 %.1f 秒：人声被背景音打碎，参考片段由"
                     "多段拼接而成（拼接处已做 %.0fms 淡变）。素材背景音的强弱"
                     "由录入后的素材体检给出结论"
                     % (longest, STITCH_FADE_SEC * 1000.0))
    flat_med = float(np.median(flat)) if flat.size else 0.0
    hf_med = float(np.median(hf)) if hf.size else 0.0

    _progress(progress, "正在按时间分箱拼接参考片段…")
    packed = stitch_runs(a, runs, target_sec=clip_sec, n_bins=n_clips,
                         sample_rate=sample_rate, total_sec=total)
    if not packed:
        raise VoiceprintError("门控人声段拼不出任何 ≥%.0f 秒的参考片段；"
                              "请改用手工选段，或换更长的素材" % AUTO_MIN_CLIP_SEC)
    return {"clips": packed,
            "spans": [s for _c, sp in packed for s in sp],
            "total_sec": round(total, 1),
            "dominant": {"share": round(share, 3), "clusters": n_clusters,
                         "windows": len(dom_iv), "scanned": len(wins)},
            "speech": {"sec": round(speech_sec, 1),
                       "ratio": round(float(mask.mean()), 3) if mask.size else 0.0,
                       "runs": len(runs), "longest_run": round(longest, 1),
                       "flat_median": round(flat_med, 4),
                       "hf_median": round(hf_med, 1)},
            "gate": {"flat_max": SPEECH_FLAT_MAX, "hf_max_db": SPEECH_HF_MAX_DB,
                     "frame_sec": GATE_FRAME_SEC},
            "scan": {"win_sec": AUTO_SCAN_WIN_SEC, "step_sec": round(step, 2)},
            "warnings": warns}


def _quality_verdict(m):
    """素材体检指标 → `(档位, 告警, 提示)`。纯函数，自检可直接钉判读口径。

    档位：`clean`（无告警）/ `caution`（1 条）/ `risky`（≥2 条）。
    **告警**是「这份素材撑不起可靠声纹」的证据，**提示**（infos）是「这一项没测
    到」的说明——两者必须分开：把「没测到」算成告警，单人干净素材（本来就该
    100% 判为本人、本来就没有纯背景音段）会被误判成有风险，实测踩过。

    每条门槛的标定依据见 `QUALITY_*` 常量注释（两份真实素材的实测值）。
    """
    w, info = [], []
    if (m.get("bg_energy_pct") or 0.0) > QUALITY_BG_ENERGY_WARN_PCT:
        w.append("背景音占了 %.0f%% 的能量（干净人声素材实测约 2%%）：人声几乎"
                 "没有「独占」的时刻，模板会连背景音一起录进去"
                 % (m.get("bg_energy_pct") or 0.0))
    if (m.get("voice_run_max") or 0.0) < QUALITY_VOICE_RUN_WARN_SEC:
        w.append("最长人声连续段只有 %.1f 秒（干净人声素材实测可达 150 秒）："
                 "人声被背景音打碎，参考片段全靠拼接"
                 % (m.get("voice_run_max") or 0.0))
    if m.get("bg_level_db") is not None \
            and m["bg_level_db"] > QUALITY_BG_LEVEL_WARN_DB:
        w.append("背景音几乎不停：非人声帧电平只比最响帧低 %.1f dB"
                 % abs(m["bg_level_db"]))
    if (m.get("hf_median") or -99.0) > QUALITY_HF_WARN_DB \
            or (m.get("flat_median") or 0.0) > QUALITY_FLAT_WARN \
            or (m.get("flat_p75") or 0.0) > QUALITY_FLAT_P75_WARN:
        w.append("频谱不像干净人声：4k-8k 衰减 %.1f dB、谱平坦度 中位 %.3f / "
                 "p75 %.3f（干净人声素材实测 -19.6 dB、0.005 / 0.017）"
                 % (m.get("hf_median") or 0.0, m.get("flat_median") or 0.0,
                    m.get("flat_p75") or 0.0))
    if m.get("windows") and not m.get("pct_below_threshold") \
            and (m.get("win_min") or 0.0) > QUALITY_WIN_MIN_WARN:
        # 「没有低分对照窗」本身**不是缺点**：单人连续说话的素材本来就该 100%
        # 判为本人（实测干净素材 40 窗最低 0.717、无一低于 keep 线）。只有当素材
        # 同时表现出背景音偏重时，它才升级成告警——那时候「全片都判为本人」更可能
        # 是模板在匹配声学底，而不是真的每句都是主播。
        txt = ("全片 %d 个窗口最低也有 %.3f、无一低于 keep 线：素材里没有「不像"
               "本人」的对照窗，模板的筛选能力等于没测到"
               % (m["windows"], m.get("win_min") or 0.0))
        bg_heavy = ((m.get("bg_energy_pct") or 0.0) > QUALITY_BG_ENERGY_WARN_PCT
                    or (m.get("voice_run_max") or 1e9) < QUALITY_VOICE_RUN_WARN_SEC)
        if bg_heavy:
            w.append(txt + "（且这份素材背景音偏重，更需要一份干净素材来验证：换一份"
                           "关掉 BGM 的说话素材重录或追加）")
        else:
            info.append(txt + "（单人连续说话的素材本该如此，属正常）")
    mg = m.get("margin")
    if mg is not None and mg < QUALITY_MARGIN_INVERTED:
        w.append("模板在「纯背景音段」上比在「人声段」上更像本人（等长 %.1f 秒"
                 "连续窗，中位 %.3f vs %.3f，落差 %+.3f）：它认的极可能是这段"
                 "录音的声学底而不是嗓音，换素材就会整体掉分"
                 % (float(m.get("seg_len") or 0.0), m.get("bg_median") or 0.0,
                    m.get("voice_median") or 0.0, mg))
    if m.get("bg_kind") == "none":
        info.append("素材里找不到 ≥%.0f 秒的纯背景音对照段：无法用「人声段 vs "
                    "背景音段」的落差验证模板认的是不是嗓音（干净素材通常如此，"
                    "属正常；这一项是没测到，不是通过）" % STRICT_MIN_RUN_SEC)
    return (("clean" if not w else ("caution" if len(w) == 1 else "risky")), w, info)


def assess_material(pcm, template, encoder=None, max_windows=QUALITY_MAX_WINDOWS,
                    win_sec=AUTO_SCAN_WIN_SEC, progress=None,
                    sample_rate=SAMPLE_RATE):
    """素材体检：这份素材撑不撑得起一个「认嗓音」的模板。

    为什么必须有它（2026-10-14 实测教训）：一份全程铺着 BGM 的主播录播，按能量
    切段录入会得到一个**自洽但认不出人**的模板——批内一致性 0.87、对本片每个
    窗口都给 0.91~0.97，各项常规指标都漂亮，可它认的是这段录音的**声学底**：
    换一份同主播、不同 BGM 的素材就可能整体掉分（误丢主播字幕），而录入全程
    不报任何错。这类模板必须在录入当场被点出来，不能等用户拿到错字幕才发现。

    判据（门槛按两份真实素材标定，见 `QUALITY_*` 常量注释）：背景音能量占比、
    最长人声连续段、背景帧电平、频谱形态（高频衰减 / 谱平坦度 中位与 p75）、
    全片逐窗得分分布、以及「人声段 vs 纯背景音段」的等长连续窗落差。
    ⚠ 判读输出**分「告警」与「提示」两类**：单人干净素材本来就该 100% 判为本人、
    本来就没有纯背景音段，把这类「没测到」算成告警会把好素材误判成有风险
    （第一版就踩了这个坑：已知可用的素材被判 risky）。

    `template` 可以是模板 dict / 名字 / 裸向量（落盘前用候选向量体检）。
    """
    enc = encoder or VoiceprintEncoder()
    tpls = _as_template_list(template)
    if not tpls:
        raise VoiceprintError("没有可用于体检的声纹向量")
    tv = tpls[0][1]
    a = np.asarray(pcm, dtype=np.float32).reshape(-1)
    total = a.size / float(sample_rate)
    mask, runs, (flat, hf, db) = gate_speech_runs(a, sample_rate=sample_rate)
    if not runs:
        return {"total_sec": round(total, 1), "verdict": "risky",
                "warnings": ["全片找不到「像人声」的段落，无法体检：素材可能以音乐"
                             "为主，或 BGM 压过了人声"],
                "infos": [], "speech_sec": 0.0, "voice_run_max": 0.0,
                "bg_kind": "none", "windows": 0}

    # 背景音对照段：**松档**门控的补集里 ≥3 秒的最长几段。
    # ⚠ 不能用严格档：严格档在干净人声素材里挑出的「非人声段」其实仍然是人声
    # （擦音/笑声的谱平坦度本来就偏高），拿它当对照，两侧都在测同一个人的嗓音，
    # 落差恒≈0 —— 实测可用素材 +0.008 / 可疑素材 +0.001，判据完全失效并且误报。
    # 松档补集的语义是「连松档都不像人声」，才是真正的背景音；干净素材通常一段
    # 都没有（实测 0 段），此时如实报 bg_kind=none、不做落差判定。
    bg_runs = sorted([(s * GATE_FRAME_SEC, (e - s) * GATE_FRAME_SEC)
                      for s, e in _runs(~mask)
                      if (e - s) * GATE_FRAME_SEC >= STRICT_MIN_RUN_SEC],
                     key=lambda r: -r[1])
    # ⚠ 两侧必须**等长且都是连续原样切**的音频。人声侧若直接用门控拼接出来的
    # 参考片段，拼接处的淡变与断口会被算成「不像本人」，落差就成了测量口径的
    # 假象而不是素材的性质——实测同一素材：拼接人声段 vs 连续背景段 = **-0.081**
    # （符号都是错的），等长连续窗对比 = +0.05。
    seg_len = min(float(win_sec), bg_runs[0][1]) if bg_runs else float(win_sec)
    bg = [(s, seg_len) for s, _d in bg_runs[:QUALITY_MAX_BG_SEGS]]
    vs, t = [], 0.0
    while t + seg_len <= total:
        i0 = int(t / GATE_FRAME_SEC)
        i1 = min(int(mask.size), int((t + seg_len) / GATE_FRAME_SEC))
        ratio = float(mask[i0:i1].mean()) if i1 > i0 else 0.0
        if ratio >= QUALITY_VOICE_RATIO_MIN:
            vs.append((t, ratio))
        t += seg_len
    vs = [(x, seg_len) for x, _r in
          sorted(sorted(vs, key=lambda v: -v[1])[:QUALITY_MAX_VOICE_SEGS])]

    def _sim(s, d):
        try:
            return float(cosine(enc.embed(a[int(s * sample_rate):
                                            int((s + d) * sample_rate)],
                                          sample_rate), tv))
        except VoiceprintError:
            return float("nan")

    _progress(progress, "正在体检：人声段 %d 个 / 背景音对照段 %d 个…"
              % (len(vs), len(bg)))
    vsc = [x for x in (_sim(s, d) for s, d in vs) if x == x]
    bsc = [x for x in (_sim(s, d) for s, d in bg) if x == x]
    n_win = max(1, min(int(max_windows), int(total // win_sec) or 1))
    starts = (np.linspace(0.0, max(0.0, total - win_sec), n_win)
              if n_win > 1 else np.zeros(1))
    wsc = [x for x in (_sim(float(t), win_sec) for t in starts) if x == x]

    pw = np.power(10.0, db / 10.0) if db.size else np.zeros(0)
    m = {"total_sec": round(total, 1),
         "speech_sec": round(sum(d for _s, d in runs), 1),
         "speech_ratio": round(float(mask.mean()), 3) if mask.size else 0.0,
         "flat_median": round(float(np.median(flat)), 4) if flat.size else None,
         "flat_p75": (round(float(np.percentile(flat, 75)), 4)
                      if flat.size else None),
         "hf_median": round(float(np.median(hf)), 1) if hf.size else None,
         "bg_level_db": (round(float(np.median(db[~mask]) - db.max()), 1)
                         if (~mask).any() else None),
         "bg_energy_pct": (round(100.0 * float(pw[~mask].sum())
                                 / max(float(pw.sum()), 1e-12), 1)
                           if pw.size else None),
         "voice_run_max": round(max(d for _s, d in runs), 1),
         "seg_len": round(float(seg_len), 2),
         "bg_kind": "windows" if bg else "none",
         "n_voice_segs": len(vsc), "n_bg_segs": len(bsc),
         "voice_median": round(float(np.median(vsc)), 4) if vsc else None,
         "voice_min": round(min(vsc), 4) if vsc else None,
         "bg_median": round(float(np.median(bsc)), 4) if bsc else None,
         "bg_max": round(max(bsc), 4) if bsc else None,
         "margin": (round(float(np.median(vsc) - np.median(bsc)), 4)
                    if vsc and bsc else None),
         "windows": len(wsc),
         "win_min": round(min(wsc), 4) if wsc else None,
         "win_p10": round(float(np.percentile(wsc, 10)), 4) if wsc else None,
         "win_median": round(float(np.median(wsc)), 4) if wsc else None,
         "win_max": round(max(wsc), 4) if wsc else None,
         "pct_below_threshold": (round(
             100.0 * sum(1 for s in wsc if s < DEFAULT_THRESHOLD)
             / float(len(wsc)), 1) if wsc else None)}
    m["verdict"], m["warnings"], m["infos"] = _quality_verdict(m)
    return m


def _compact_quality(q):
    """体检结果落进模板元信息的精简版（完整指标只在返回值 / 报告里）。

    只留判读用的几个数与告警文本：模板会经声纹同步上传给其他客户端，别把逐窗
    明细塞进去。远端折叠（`voiceprint_sync.apply_upserts`）重建模板时不带这个
    键，所以它是**本机录入的溯源信息**，不参与同步收敛。
    """
    if not q:
        return None
    keep = ("verdict", "flat_median", "flat_p75", "hf_median", "bg_level_db",
            "bg_energy_pct", "voice_run_max", "speech_ratio", "voice_median",
            "bg_median", "margin", "bg_kind", "seg_len", "win_min", "win_median",
            "win_max", "pct_below_threshold", "windows")
    out = {k: q[k] for k in keep if q.get(k) is not None}
    out["warnings"] = [str(x) for x in (q.get("warnings") or [])]
    out["infos"] = [str(x) for x in (q.get("infos") or [])]
    return out


def check_confusion(template, low=DEFAULT_LOW, threshold=DEFAULT_THRESHOLD,
                    skip=None):
    """本声纹与库内其它声纹的混淆检查（纯余弦，不解码音频，成本可忽略）。

    为什么要主动查（2026-10-14 实测）：新录的「Pixel Tree」与库内 MarcoMeatball
    相似度 **0.578**、SmugSlav **0.565**——都超过 keep 线 0.55，意味着拿它去筛
    那两位的素材会把对方的字幕当主播保留（多声纹是并集语义，同时启用时更糟）。
    这种风险录入时不会报错，只有逐对比对才看得见，所以录入/追加后自动跑一次。

    顺带说明阈值口径：0.55/0.45 是按**中文 3 人**语料定的（见 DEFAULT_THRESHOLD
    注释），英语素材上不同主播之间挤到 0.5~0.66 是实测常态，所以这里的告警是
    「注意」而非「录错了」。

    `template` 可以是模板 dict / 名字 / 裸向量；`skip` 是要跳过的模板名
    （传裸向量时 `_as_template_list` 会给出占位名「主播」，靠 skip 才排得掉自己）。
    返回 [(名字, 相似度, 级别)]，级别 `keep`/`review`/`ok`，按相似度降序。
    """
    tpls = _as_template_list(template)
    if not tpls:
        return []
    self_name, vec = tpls[0]
    out = []
    for n in list_templates():
        if n == self_name or (skip is not None and n == skip):
            continue
        try:
            v = load_template(n)["embedding"]
        except VoiceprintError:
            continue
        s = cosine(vec, v)
        if s != s:
            continue
        s = float(s)
        out.append((n, round(s, 4),
                    "keep" if s >= threshold else ("review" if s >= low else "ok")))
    out.sort(key=lambda r: (-r[1], r[0]))
    return out


def format_confusion(rows, min_level="keep"):
    """把 `check_confusion` 的结果格式成人话告警（CLI 与界面共用同一份措辞）。

    `min_level="keep"`（默认）只输出**会真误判**的那一档（相似度 ≥ keep 线）：
    录入当下的回显要给得克制，存疑区那种「会进存疑保留」的提示留到 `audit`
    全库体检时再看，否则库里模板一多，告警会把真正要紧的那条淹掉
    （实测 8 个模板的库能出 11 条告警，其中只有 4 条是 keep 级）。
    `min_level="review"` 则两档都输出。
    """
    out = []
    for n, s, lvl in rows or []:
        if lvl == "keep":
            out.append("与已录入的「%s」相似度 %.3f ≥ keep 线 %.2f：拿本声纹去筛"
                       "他的素材会把他的字幕当主播保留（两者别同时启用；若确实是"
                       "同一人，考虑合并成一个声纹）" % (n, s, DEFAULT_THRESHOLD))
        elif lvl == "review" and min_level == "review":
            out.append("与已录入的「%s」相似度 %.3f 落在存疑区 [%.2f, %.2f)："
                       "筛他的素材时会进「存疑保留」" % (n, s, DEFAULT_LOW,
                                                         DEFAULT_THRESHOLD))
    return out


def audit_library(low=DEFAULT_LOW, threshold=DEFAULT_THRESHOLD):
    """声纹库体检：各模板元信息 + 两两混淆矩阵 + 告警。返回 dict（CLI 负责排版）。

    库里模板攒多了以后，「哪两个声纹其实分不开」是看不见的——只有逐对比对才
    暴露（实测某库 8 个模板里有 3 对 ≥0.55，最高 0.663，且跨素材的对反而比同
    素材的对更高，说明不是共用背景音、而是音色本身接近）。
    """
    names = list_templates()
    vecs, metas = {}, {}
    for n in names:
        try:
            t = load_template(n)
        except VoiceprintError:
            continue
        vecs[n] = t["embedding"]
        q = t.get("quality") or {}
        metas[n] = {"clips": int(t.get("clips") or 1),
                    "seconds": float(t.get("seconds") or 0.0),
                    "created": str(t.get("created") or ""),
                    "source": os.path.basename(str(t.get("source") or "")),
                    "consistency": t.get("consistency"),
                    "auto": bool(t.get("auto")),
                    "verdict": q.get("verdict"),
                    "quality_warnings": list(q.get("warnings") or [])}
    keys = sorted(vecs)
    matrix = {}
    warns = []
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            s = cosine(vecs[a], vecs[b])
            if s != s:
                continue
            s = round(float(s), 4)
            matrix.setdefault(a, {})[b] = s
            matrix.setdefault(b, {})[a] = s
            if s >= threshold:
                warns.append((s, "「%s」与「%s」相似度 %.3f ≥ keep 线 %.2f：互相会把"
                                 "对方的字幕判成本人" % (a, b, s, threshold)))
            elif s >= low:
                warns.append((s, "「%s」与「%s」相似度 %.3f 落在存疑区 [%.2f, %.2f)"
                                 % (a, b, s, low, threshold)))
    # 按相似度降序：最危险的（互相误判为本人）排最前，库里模板多时不被淹没
    warns.sort(key=lambda t: (-t[0], t[1]))
    return {"names": keys, "meta": metas, "matrix": matrix,
            "warnings": [t for _s, t in warns]}


def enroll_auto(src, name="主播", n_clips=AUTO_CLIPS, clip_sec=AUTO_CLIP_SEC,
                encoder=None, append=False, assess=True, progress=None,
                sample_rate=SAMPLE_RATE, pcm=None):
    """**自动选段录入（推荐入口）**：选段 + 录入 + 素材体检 + 库内混淆检查。

    = `suggest_clips` → `enroll_pcm` → `assess_material` → `check_confusion`，
    一次跑完。返回值在 `enroll_pcm` 的字段之外另带：
      `quality`    素材体检完整指标（含 verdict / warnings）
      `confusion`  与库内其它声纹的相似度表
      `warnings`   人话告警汇总（选段 + 体检 + 混淆），界面与 CLI 直接回显
      `spans`      实际用到的参考片段时间明细
      `suggest`    选段过程统计（主簇占比 / 门控统计 / 扫描参数）

    比手工给 `--start/--dur` 稳在哪（都是实测踩到的）：① 多片段而非单片段
    （`enroll_pcm` 文档：判定边际 +0.04~+0.09）；② 片段按时间分箱铺满全片；
    ③ 频谱门控避开 BGM 最响的时刻；④ 多人素材只取主说话人簇；⑤ 录完当场体检
    + 查库内混淆，坏模板不会静默入库。

    `assess=False` 可跳过体检（省约 60 次推理）；体检不改模板向量，只产出告警
    与元信息，所以**默认开着**——精准度优先于这几秒。
    `pcm` 可选：调用方已解码好的 16k 单声道波形（自检注入假音频用，也省一次
    全片解码）；给了就不再读 `src` 的音频，但 `src` 仍用于模板的 `source` 字段。
    """
    enc = encoder or VoiceprintEncoder()
    if pcm is None:
        _progress(progress, "正在解码音频…")
        pcm = read_pcm(src, sample_rate=sample_rate)
    sug = suggest_clips(src, n_clips=n_clips, clip_sec=clip_sec, encoder=enc,
                        progress=progress, pcm=pcm, sample_rate=sample_rate)
    packed = sug["clips"]
    clips = [c for c, _sp in packed]
    base = None
    if append:
        if not os.path.isfile(template_path(name)):
            raise VoiceprintError("没有已录入的声纹「%s」，无法追加（先关掉追加"
                                  "正常录入，或换个名字）" % name)
        base = load_template(name)
    spans = [s for _c, sp in packed for s in sp]
    # 体检用「候选向量」= 本批片段的归一均值：新建时与最终落盘向量逐位相同；
    # 追加时最终向量还会与旧叶子折叠，体检结论描述的是**本批素材**（旧叶子是
    # 历史事实，不该被新素材翻旧账）。
    cand = _mean_unit([enc.embed(c, sample_rate) for c in clips])
    quality = None
    if assess:
        _progress(progress, "正在体检素材（人声段 / 背景音段 / 全片逐窗）…")
        quality = assess_material(pcm, cand, encoder=enc, progress=progress,
                                  sample_rate=sample_rate)
    try:
        r = enroll_pcm(clips, name=name, encoder=enc,
                       source=os.path.basename(str(src)),
                       start=round(spans[0][0], 2) if spans else None,
                       dur=round(sum(len(c) for c in clips) / float(sample_rate), 2),
                       base=base, quality=_compact_quality(quality),
                       auto={"clips": len(clips), "bins": int(n_clips),
                             "clip_sec": float(clip_sec),
                             "gate_flat_max": SPEECH_FLAT_MAX,
                             "gate_hf_max_db": SPEECH_HF_MAX_DB,
                             "dominant_share": sug["dominant"]["share"],
                             "speech_sec": sug["speech"]["sec"]})
    except VoiceprintError as e:
        # 自动选段已经按「主说话人簇 + 频谱门控」过滤过还被拦下，说明素材本身
        # 分不开人（多人音色接近 / 背景音压过人声）。原始报错只说「片段间声纹
        # 不一致」，用户看不出下一步该做什么，这里补一条可操作的指路。
        raise VoiceprintError(
            "%s\n（自动选段已按主说话人簇 + 频谱门控过滤；仍被拦下通常是素材里"
            "多人声音接近、或背景音压过了人声。可取消「自动选段」改用手工选段，"
            "挑一段只有主播说话的音频，或换一份素材）" % e)
    confusion = check_confusion(load_template(name), skip=name)
    w_sel = list(sug["warnings"])
    w_q = list((quality or {}).get("warnings") or [])
    w_conf = format_confusion(confusion)
    r.update({"quality": quality, "confusion": confusion,
              "infos": list((quality or {}).get("infos") or []),
              # 三类告警分开存：CLI 的体检段已经打过 w_q，末尾只补选段与混淆两类，
              # 否则同一条 ⚠ 会出现两遍（第一版就是这样，噪音盖住重点）
              "warnings_select": w_sel, "warnings_quality": w_q,
              "warnings_confusion": w_conf,
              "warnings": w_sel + w_q + w_conf,
              "spans": spans,
              "suggest": {k: v for k, v in sug.items() if k != "clips"}})
    return r


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


#: 体检档位的中文说法（CLI 回显用）
_VERDICT_CN = {"clean": "可用", "caution": "可用，但有保留", "risky": "有风险"}


def verdict_text(verdict):
    """体检档位的中文说法（CLI 与界面共用同一份措辞，别各写一套）。"""
    return _VERDICT_CN.get(verdict, verdict or "—")


def _disp_w(s):
    """终端显示宽度：全角（中/日/韩）算 2 列。声纹名常是韩文，用 `%-18s`
    按字符数补齐会让矩阵错位（实测韩文名的行整体往左挤两列）。"""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1
               for c in str(s))


def _pad(s, w):
    """按显示宽度右侧补空格到 `w` 列。"""
    s = str(s)
    return s + " " * max(0, int(w) - _disp_w(s))


def _print_quality(q):
    """把素材体检结果打成人话（`enroll --auto` 与 `assess` 子命令共用）。"""
    if not q:
        return
    print("\n=== 素材体检：%s ===" % verdict_text(q.get("verdict")))

    def _f(v, fmt="%.3f"):
        return (fmt % v) if isinstance(v, (int, float)) else "—"

    print("  人声占比 %s（%s 秒），最长人声连续段 %s 秒（干净素材实测可达 150 秒）"
          % (_f(100.0 * float(q.get("speech_ratio") or 0.0), "%.0f%%"),
             _f(q.get("speech_sec"), "%.0f"), _f(q.get("voice_run_max"), "%.1f")))
    print("  谱平坦度 中位 %s / p75 %s，4k-8k 衰减 %s dB"
          "（干净人声素材实测 0.005 / 0.017、-19.6 dB）"
          % (_f(q.get("flat_median")), _f(q.get("flat_p75")),
             _f(q.get("hf_median"), "%.1f")))
    if q.get("bg_level_db") is not None:
        print("  背景音电平 %s dB（相对最响帧），占能量 %s%%（干净素材实测约 2%%）"
              % (_f(q["bg_level_db"], "%.1f"), _f(q.get("bg_energy_pct"), "%.0f")))
    if q.get("voice_median") is not None:
        if q.get("bg_median") is not None:
            print("  等长 %.1f 秒连续窗：人声段 中位 %s / 最低 %s ；纯背景音段 中位 %s"
                  " / 最高 %s  → 落差 %s（为负即模板更认背景音）"
                  % (float(q.get("seg_len") or 0.0), _f(q.get("voice_median")),
                     _f(q.get("voice_min")), _f(q.get("bg_median")),
                     _f(q.get("bg_max")), _f(q.get("margin"), "%+.3f")))
        else:
            print("  人声段得分 中位 %s / 最低 %s ；无纯背景音对照段（bg_kind=%s）"
                  % (_f(q.get("voice_median")), _f(q.get("voice_min")),
                     q.get("bg_kind")))
    if q.get("windows"):
        print("  全片逐窗（%d 窗，连续音频）：min %s  p10 %s  中位 %s  max %s；"
              "低于 keep 线的占 %s%%"
              % (q["windows"], _f(q.get("win_min")), _f(q.get("win_p10")),
                 _f(q.get("win_median")), _f(q.get("win_max")),
                 _f(q.get("pct_below_threshold"), "%.0f")))
    for w in (q.get("warnings") or []):
        print("  ⚠ %s" % w)
    for i in (q.get("infos") or []):
        print("  · %s" % i)


def _configure_stdio():
    """标准流按 UTF-8 容错——声纹名常是韩文/日文（「미니보기」「감군장」），
    GBK 控制台下打印会 UnicodeEncodeError：`list` 直接崩在半截、名单显示不全，
    `use` / `delete` / `score` 的回显同理。管道与重定向到文件时 Python 也用
    locale 编码（cp936），所以命令行里 `| head` 一样会炸。

    优先复用引擎的 `configure_stdio_utf8`（与引擎 CLI / GUI 同一口径，幂等）；
    引擎导入失败才本地兜底，理由同 `_resolve_dirs`。**只在命令行入口调用**：
    界面 import 本模块时不去动全局标准流。
    """
    try:
        import video_toolbox as _e
        _e.configure_stdio_utf8()
        return
    except Exception:  # noqa: BLE001
        pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass


def main(argv=None):
    _configure_stdio()
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
    p1.add_argument("--auto", action="store_true",
                    help="**自动选段（推荐）**：全片扫描 → 声纹聚簇取主说话人 → "
                         "频谱门控排 BGM → 按时间分箱拼 %d 段，录完自动做素材体检"
                         "与库内混淆检查；给了本开关就忽略 --start/--dur/--clip"
                         % AUTO_CLIPS)
    p1.add_argument("--clips", type=int, default=AUTO_CLIPS,
                    help="自动选段的片段数（默认 %d，每段约 %.0f 秒人声）"
                         % (AUTO_CLIPS, AUTO_CLIP_SEC))
    p1.add_argument("--no-assess", action="store_true",
                    help="自动选段后跳过素材体检（省约 60 次推理，不建议）")

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

    p7 = sub.add_parser("assess",
                        help="素材体检（不落盘）：这份素材撑不撑得起一个「认嗓音」的模板")
    p7.add_argument("--src", required=True)
    p7.add_argument("--name", default=None,
                    help="用哪个已录入声纹体检；不给则先自动选段、用候选向量体检")
    p7.add_argument("--json", default=None, help="完整指标另写成 JSON")

    p8 = sub.add_parser("audit",
                        help="声纹库体检：各模板元信息 + 两两混淆矩阵 + 告警")
    p8.add_argument("--json", default=None, help="完整结果另写成 JSON")

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
        sayp = lambda m: print("[声纹] %s" % m, flush=True)   # noqa: E731
        if args.auto:
            r = enroll_auto(args.src, args.name, n_clips=max(1, int(args.clips)),
                            append=args.append, assess=not args.no_assess,
                            progress=sayp)
        else:
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
            # 手工录入也查一次库内混淆：纯余弦、不解码音频，成本可忽略，而
            # 「新声纹跟库里某人分不开」正是录入当下最该知道的事
            try:
                r["warnings"] = format_confusion(
                    check_confusion(load_template(r["name"]), skip=r["name"]))
            except VoiceprintError:
                r["warnings"] = []
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
        sug = r.get("suggest") or {}
        if sug:
            d, sp = sug.get("dominant") or {}, sug.get("speech") or {}
            print("  自动选段：主说话人占 %s%% 扫描窗（共 %s 簇），门控人声 %s 秒"
                  "（%s 段，最长 %s 秒）"
                  % (int(100.0 * float(d.get("share") or 0)), d.get("clusters"),
                     sp.get("sec"), sp.get("runs"), sp.get("longest_run")))
        _print_quality(r.get("quality"))     # 体检段自带 ⚠ 告警与 · 提示
        for w in ((r.get("warnings_select") or [])
                  + (r.get("warnings_confusion") or r.get("warnings") or [])):
            print("⚠ %s" % w)
        if (r.get("quality") or {}).get("verdict") == "risky":
            return 3
        return 0
    if args.cmd == "assess":
        sayp = lambda m: print("[声纹] %s" % m, flush=True)   # noqa: E731
        pcm = read_pcm(args.src)
        enc = VoiceprintEncoder()
        warns = []
        if args.name:
            vec = load_template(args.name)["embedding"]
            label = "已录入声纹「%s」" % args.name
        else:
            sug = suggest_clips(args.src, encoder=enc, pcm=pcm, progress=sayp)
            vec = _mean_unit([enc.embed(c) for c, _s in sug["clips"]])
            label = "自动选段候选向量（%d 段，未落盘）" % len(sug["clips"])
            warns = list(sug["warnings"])
        q = assess_material(pcm, vec, encoder=enc, progress=sayp)
        print("\n体检对象：%s" % label)
        for w in warns:
            print("⚠ %s" % w)
        _print_quality(q)
        if args.json:
            with open(args.json, "w", encoding="utf-8") as fh:
                json.dump({"src": args.src, "target": label, "select_warnings": warns,
                           "quality": q}, fh, ensure_ascii=False, indent=1)
            print("\n已写 %s" % args.json)
        return 3 if q.get("verdict") == "risky" else 0
    if args.cmd == "audit":
        rep = audit_library()
        if not rep["names"]:
            print("（还没有录入任何声纹；先跑 enroll --auto）")
            return 0
        print("=== 声纹库体检（%d 个）===" % len(rep["names"]))
        for n in rep["names"]:
            m = rep["meta"][n]
            print("  %s %2d 片段 %6.1f 秒  一致性 %s  %s  %s%s"
                  % (_pad(n, 18), m["clips"], m["seconds"],
                     _pad(("%.3f" % m["consistency"]) if m["consistency"] else "—", 6),
                     (m["created"] or "")[:16],
                     "自动选段" if m["auto"] else "手工选段",
                     ("  体检:%s" % verdict_text(m["verdict"]))
                     if m["verdict"] else ""))
            for w in m["quality_warnings"]:
                print("      ⚠ %s" % w)
        keys = rep["names"]
        print("\n=== 两两相似度（≥%.2f 互相误判为本人 / ≥%.2f 存疑）==="
              % (DEFAULT_THRESHOLD, DEFAULT_LOW))
        for a in keys:
            cells = "".join(
                "%8s" % ("-" if a == b else
                         ("%.3f" % rep["matrix"].get(a, {}).get(b, float("nan"))))
                for b in keys)
            print("  %s%s" % (_pad(a, 20), cells))
        print("  列顺序同上行顺序：%s"
              % "、".join("%d=%s" % (i + 1, n) for i, n in enumerate(keys)))
        for w in rep["warnings"]:
            print("⚠ %s" % w)
        if not rep["warnings"]:
            print("  没有互相混淆的声纹对")
        if args.json:
            with open(args.json, "w", encoding="utf-8") as fh:
                json.dump(rep, fh, ensure_ascii=False, indent=1)
            print("\n已写 %s" % args.json)
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
