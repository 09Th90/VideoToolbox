# -*- coding: utf-8 -*-
# @version 3.2.0
"""声源分离后端（MossFormer2 盲分离 + CAM++ 声纹选轨 + Demucs 歌声辅线）。

WP5 PoC（2026-11-22）。调用方只有一个：``protocol._asr_separate_audio``。

设计要点
--------
· **torch / modelscope / demucs 全部是可选依赖**：当前栈未装 torch，本模块
  顶层只 import 标准库 + numpy；重依赖一律函数内 lazy import，模块加载永不
  崩。依赖缺失时 :func:`probe` 返回 False、:func:`separate` raise
  :class:`BackendUnavailable`，调用方 degraded 回退原轨——绝不阻断转录。
· **显存编排**：真正的分离推理跑在**独立子进程**（本模块以
  ``python -m core.asr.separation_backend __worker__ <job.json>`` 自唤），
  完成（或失败）即退出 → CUDA 上下文随进程释放，8GB 卡与本地 large-v3
  ASR 天然错峰：分离结束后才开始逐轨提交识别。
· **先拆开再认人**：MossFormer2 盲分离出 N 条说话人轨（8k），回程做
  8k→16k 重采样喂 ASR；CAM++（复用现有 27MB onnx，``features.voiceprint``
  同源实现）对每条轨提 192 维向量，与**本地** enrollment 模板算余弦，
  按 ``min_sim`` / ``margin`` 选目标轨。enrollment 声纹只在本地读盘比对，
  **不出本地**（voiceprint_sync 的远端通道与本后端无关，本模块不触碰）。
· **辅线 Demucs htdemucs**（可选）：vocals 人声干声以「歌声」标签返回，
  伴奏（no_vocals）不落返回列表——音乐 reaction「剔除歌声」的素材面。
· **缓存**：键 = preproc 16k 单声道 wav 的 sha256 + model_id + version +
  preproc 标记（+ 目标轨数 / 歌声开关）；产物（各轨 16k wav + manifest）
  落 ``data/asr_separation_cache/<键前缀>/``，命中直接返回，不再进子进程。
· **模型缓存重定向**：MODELSCOPE_CACHE / HF_HOME / TORCH_HOME 未设置时指向
  程序盘 ``data/asr_separation_models``（安装盘通常为 D 盘），避免把
  C 盘用户目录塞爆；只补缺省值，用户显式设置过的环境变量一律尊重。

配置（data/config.json 顶层 ``asr_separation_*`` 键；总开关 ``asr_separate``
由 ``protocol.asr_separate_of`` 读取，默认 off）：

  asr_separation_shadow    影子模式（协议层读，默认 True：分离照跑落缓存，
                           转录仍用原轨——PoC 验证期不影响成品）
  asr_separation_model     MossFormer2 模型 id（默认 damo/speech_mossformer2_
                           separation_temporal_8k）
  asr_separation_num_speakers  目标说话人数（0 = 模型自动）
  asr_separation_vocals    是否跑 Demucs 歌声辅线（默认 off）
  asr_separation_target    enrollment 模板名（逗号分隔；空 = 不选轨，
                           全部说话人轨按能量序编号返回）
  asr_separation_min_sim   选轨最低相似度（默认 0.45）
  asr_separation_margin    选轨置信 margin（默认 0.03）
  asr_separation_cache     产物缓存开关（默认 on）
  asr_separation_timeout   分离子进程超时秒（默认 3600）
  asr_separation_device    auto / cuda / cpu（默认 auto）

⚠ 命名约束：本文件在 core 树内，模块顶层**不得出现全大写常量名**——
``scripts/dev/_selftest_core_api.py`` 会把 core 树所有顶层 UPPERCASE 赋值
收进基线并要求挂到 facade 再导出，新增未再导出的大写常量会把基线打红。
"""

import hashlib
import json
import os
import subprocess
import sys
import time
import wave

import numpy as np

from core.shared.log import _vc_log

#: MossFormer2 盲分离模型（ModelScope 8k 时域模型，双人/多人分离）。
_sep_default_model = "damo/speech_mossformer2_separation_temporal_8k"

#: Demucs 歌声辅线模型（vocals / no_vocals 双干声）。
_sep_demucs_model = "htdemucs"

#: 产物/键版本：预处理或后处理语义变更时 +1，旧缓存自动失效。
_sep_version = "poc1"

#: 缓存统计（进程内累计；供日志与 PoC 评测读取）。
_stats = {
    "calls": 0,              # separate() 进入次数
    "ok": 0,                 # 成功产出多轨
    "cache_hit": 0,          # 缓存命中
    "backend_unavailable": 0,  # torch/modelscope 缺失
    "worker_failed": 0,      # 分离子进程失败
    "tracks_returned": 0,    # 累计返回轨数
    "tracks_dropped": 0,     # 选轨弃轨数（不静默删，逐条有日志）
}


def stats():
    """返回分离统计的只读快照（PoC 评测 / 日志自检用）。"""
    return dict(_stats)


class BackendUnavailable(RuntimeError):
    """分离后端不可用（torch / modelscope 等可选依赖缺失）。

    调用方（protocol._asr_separate_audio）捕获后 degraded 回退原轨，
    绝不向上抛——转录永远不被分离挡住。
    """


class SeparationInputError(RuntimeError):
    """分离输入不可用（音频路径缺失且拿不到字节流）。"""


# ---------------------------------------------------------------- 路径


def _find_app_root():
    """程序根：从本文件向上找 AGENTS.md 标记（≤6 级），找不到回落 cwd。"""
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(6):
        if os.path.isfile(os.path.join(d, "AGENTS.md")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return os.getcwd()


_app_root = _find_app_root()


def _dir(*parts):
    return os.path.join(_app_root, *parts)


def _cache_root():
    """分离产物缓存根：``data/asr_separation_cache``。"""
    return _dir("data", "asr_separation_cache")


def _models_root():
    """模型缓存根（D 盘重定向落点）：``data/asr_separation_models``。"""
    return _dir("data", "asr_separation_models")


def _tmp_root():
    """分离中间态根：``data/tmp/separation``。"""
    return _dir("data", "tmp", "separation")


_env_redirected = False


def _ensure_model_cache_env():
    """把模型缓存环境变量重定向到程序盘（只补缺省，不覆盖用户显式设置）。

    ModelScope 默认缓存到 ``~/.cache/modelscope``、HF/Torch 到
    ``~/.cache/huggingface`` / ``~/.cache/torch``—— mossformer2 + demucs
    两个模型数 GB，塞 C 盘用户目录很快见顶。这里统一指到
    ``data/asr_separation_models``（程序盘）。幂等：只在本进程第一次
    进入 worker / separate 时各执行一次。
    """
    global _env_redirected
    if _env_redirected:
        return
    _env_redirected = True
    root = _models_root()
    os.makedirs(root, exist_ok=True)
    for var, sub in (("MODELSCOPE_CACHE", "modelscope"),
                     ("HF_HOME", "huggingface"),
                     ("TORCH_HOME", "torch"),
                     ("DEMUCS_CACHE_DIR", "demucs")):
        os.environ.setdefault(var, os.path.join(root, sub))
    _vc_log("[ASR] 分离模型缓存目录（缺省补齐，程序盘）：%s" % root)


# ---------------------------------------------------------------- 依赖探针


def probe():
    """可选依赖探针（零 import，find_spec 只查元数据，毫秒级）。

    返回 dict(torch, modelscope, demucs, numpy_ok)；
    ``demucs`` 缺失只影响「歌声」辅线，不算后端不可用。
    """
    import importlib.util
    out = {"torch": False, "modelscope": False, "demucs": False,
           "numpy_ok": True}
    try:
        out["torch"] = importlib.util.find_spec("torch") is not None
    except Exception:  # noqa: BLE001
        pass
    try:
        out["modelscope"] = importlib.util.find_spec("modelscope") is not None
    except Exception:  # noqa: BLE001
        pass
    try:
        out["demucs"] = importlib.util.find_spec("demucs") is not None
    except Exception:  # noqa: BLE001
        pass
    return out


def available():
    """分离主链（MossFormer2）当前是否可用——torch 与 modelscope 齐备。"""
    dep = probe()
    return bool(dep.get("torch") and dep.get("modelscope"))


# ---------------------------------------------------------------- 输入落定


def _crc8(data):
    """内容指纹前 8 位 hex（临时文件名去重用）。"""
    return hashlib.sha256(data).hexdigest()[:8]


def _resolve_source(audio_path, asr_obj=None):
    """把调用侧输入落成**磁盘文件**：路径直用；字节流 dump 到 tmp。

    分块链路（ChunkedASR）传进 _submit 的 audio_input 是**字节**，此时
    protocol 侧会传空串并携带 asr_obj——从 ``asr_obj.file_binary`` 取
    原始容器字节落盘（扩展名取不到时用 .bin，交给 ffmpeg 解容器）。
    返回 (src_path, created_tmp or None)。
    """
    if audio_path and os.path.isfile(str(audio_path)):
        return str(audio_path), None
    blob = getattr(asr_obj, "file_binary", None) or b""
    if not blob:
        raise SeparationInputError(
            "分离输入不可用：路径不存在且拿不到音频字节（audio_path=%r）"
            % (audio_path,))
    ext = "bin"
    src = getattr(asr_obj, "audio_input", None)
    if isinstance(src, str) and "." in os.path.basename(src):
        ext = src.rsplit(".", 1)[-1].lower()[:5] or "bin"
    os.makedirs(_tmp_root(), exist_ok=True)
    tmp = os.path.join(_tmp_root(),
                       "src_%s_%s.%s" % (_crc8(blob), int(time.time()), ext))
    with open(tmp, "wb") as fh:
        fh.write(blob)
    return tmp, tmp


# ---------------------------------------------------------------- ffmpeg 预处理


def _ffmpeg_path():
    """ffmpeg 定位：core.download 的规范解析，失败回落 tools/ffmpeg.exe。"""
    try:
        from core.download.deps import ensure_ffmpeg
        p = ensure_ffmpeg()
        if p and os.path.isfile(str(p)):
            return p
    except Exception:  # noqa: BLE001
        pass
    for cand in (_dir("tools", "ffmpeg.exe"), "ffmpeg"):
        if cand == "ffmpeg" or os.path.isfile(cand):
            return cand
    raise SeparationInputError("未找到 ffmpeg，无法做分离预处理")


def _run_ffmpeg(src, dst, rate):
    """转码：任意容器 → 单声道 PCM wav（16k 供声纹/缓存键，8k 供模型）。"""
    cmd = [_ffmpeg_path(), "-y", "-nostdin", "-i", src,
           "-vn", "-ac", "1", "-ar", str(rate),
           "-f", "wav", "-sample_fmt", "s16", dst]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    r = subprocess.run(cmd, capture_output=True, timeout=1800,
                       creationflags=flags if os.name == "nt" else 0)
    if r.returncode != 0 or not os.path.isfile(dst):
        err = (r.stderr or b"")[-300:].decode("utf-8", "replace")
        raise SeparationInputError("分离预处理失败（ffmpeg %s→%s）：%s"
                                   % (rate, os.path.basename(dst), err))


def _preproc(src_path, work_dir):
    """两路预处理：16k（声纹/缓存键）+ 8k（MossFormer2 输入口径）。

    幂等：work_dir 里已有同名产物且 mtime 新于源文件则直接复用。
    """
    p16 = os.path.join(work_dir, "preproc_16k.wav")
    p8 = os.path.join(work_dir, "preproc_8k.wav")
    src_m = os.path.getmtime(src_path)
    need16 = not (os.path.isfile(p16) and os.path.getmtime(p16) >= src_m)
    need8 = not (os.path.isfile(p8) and os.path.getmtime(p8) >= src_m)
    if need16:
        _run_ffmpeg(src_path, p16, 16000)
    if need8:
        _run_ffmpeg(src_path, p8, 8000)
    return p16, p8


# ---------------------------------------------------------------- 缓存


def _cache_key(p16_path, cfg):
    """缓存键：preproc 16k 内容 sha256 + model + version + preproc + 形态。"""
    h = hashlib.sha256()
    with open(p16_path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    payload = "|".join([
        h.hexdigest(),
        str(cfg.get("model") or _sep_default_model),
        _sep_version,
        "mono16k+mono8k",
        "n%d" % int(cfg.get("num_speakers") or 0),
        "vocals=%d" % (1 if cfg.get("vocals") else 0),
    ])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _read_manifest(cdir):
    p = os.path.join(cdir, "manifest.json")
    if not os.path.isfile(p):
        return None
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return None


def _write_manifest(cdir, obj):
    p = os.path.join(cdir, "manifest.json")
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, p)
    return p


def _tracks_complete(cdir, tracks):
    for _label, path in tracks or []:
        if not path or not os.path.isfile(path):
            return False
    return bool(tracks)


# ---------------------------------------------------------------- wav 读写


def _read_wav_mono(path):
    """stdlib wave 读单声道 PCM wav → float32 样本 + 采样率。"""
    with wave.open(path, "rb") as w:
        rate = w.getframerate()
        nch = w.getnchannels()
        sw = w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if sw != 2:
        raise SeparationInputError("分离产物须为 16bit PCM wav：%s" % path)
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if nch > 1:
        x = x.reshape(-1, nch).mean(axis=1)
    return x, rate


def _write_wav_mono(path, samples, rate):
    """float32 样本 → 16bit 单声道 PCM wav（限幅防削波）。"""
    x = np.asarray(samples, dtype=np.float32).reshape(-1)
    peak = float(np.max(np.abs(x))) if x.size else 0.0
    if peak > 1.0:
        x = x / peak
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(rate))
        w.writeframes((np.clip(x, -1.0, 1.0) * 32767.0).astype(np.int16)
                      .tobytes())
    return path


def _resample_to(x, src_rate, dst_rate):
    """8k→16k 线性重采样（numpy 手写，喂 ASR 前的统一口径）。

    优先复用 features.voiceprint 的同源实现（kaldi 系自测覆盖）；导入
    失败（features 链缺失等极端场景）回落本模块纯 numpy 线性插值。
    """
    if int(src_rate) == int(dst_rate):
        return np.asarray(x, dtype=np.float32).reshape(-1)
    try:
        import features.voiceprint.speaker_voiceprint as sv
        return sv.resample_linear(np.asarray(x, dtype=np.float32),
                                  int(src_rate), int(dst_rate))
    except Exception:  # noqa: BLE001
        if not x.size:
            return np.zeros(0, dtype=np.float32)
        n_out = int(round(len(x) * float(dst_rate) / float(src_rate)))
        idx = np.clip(np.linspace(0, len(x) - 1, n_out), 0, len(x) - 1)
        lo = np.floor(idx).astype(np.int64)
        hi = np.minimum(lo + 1, len(x) - 1)
        frac = (idx - lo).astype(np.float32)
        return ((1.0 - frac) * x[lo] + frac * x[hi]).astype(np.float32)


# ---------------------------------------------------------------- CAM++ 选轨


def _target_template_vectors(target_names):
    """本地读 enrollment 模板向量（**不出本地**：只读盘，不发起任何网络）。

    返回 [(模板名, 192 维单位向量), ...]；模板缺失跳过并记日志。
    """
    import features.voiceprint.speaker_voiceprint as sv
    out = []
    for name in target_names:
        try:
            tpl = sv.load_template(name)
            vec = np.asarray(tpl.get("embedding"), dtype=np.float32)
            n = float(np.linalg.norm(vec))
            if n > 1e-9:
                out.append((str(name), vec / n))
        except Exception as e:  # noqa: BLE001
            _vc_log("[ASR] 分离选轨：声纹模板缺失，跳过 %s：%s" % (name, e))
    return out


def _select_target_tracks(track_paths, cfg):
    """「先拆开再认人」：CAM++ 相似度 margin 选目标轨。

    规则（PoC 口径，影子期收集数据再收紧）：
      · 未给 target → 不选轨：全部说话人轨按**能量降序**编 说话人1..N；
      · 给了 target → 每轨提 192 维向量，与模板最大余弦 = 该轨目标分；
        sim ≥ min_sim 的轨入选；一条都不达标时**保底**取最高分轨（不静默删）；
      · margin 置信：入选最低分 − 落选最高分 < margin 时记低置信日志
        （不回退——影子验证就是拿来量这个的）；
      · 落选轨逐条日志 + ``stats()["tracks_dropped"]`` 计数。
    返回 labels 列表（与 track_paths 一一对应，"" = 该轨被弃）。
    """
    labels = [""] * len(track_paths)
    names = [n.strip() for n in str(cfg.get("target") or "").split(",")
             if n.strip()]
    energies = []
    for p in track_paths:
        try:
            x, _rate = _read_wav_mono(p)
            energies.append(float(np.mean(x.astype(np.float64) ** 2)) if
                            x.size else 0.0)
        except Exception:  # noqa: BLE001
            energies.append(0.0)
    if not names:
        order = sorted(range(len(track_paths)),
                       key=lambda i: -energies[i])
        for rank, i in enumerate(order, 1):
            labels[i] = "说话人%d" % rank
        return labels
    # 依赖探针：声纹模型缺失 → 不选轨（保持能量序全量返回），日志说明
    import features.voiceprint.speaker_voiceprint as sv
    if not sv.model_present():
        _vc_log("[ASR] 分离选轨：CAM++ 模型缺失，跳过选轨（全量按能量序）")
        return _select_target_tracks(track_paths,
                                     dict(cfg, target=""))
    tpls = _target_template_vectors(names)
    if not tpls:
        _vc_log("[ASR] 分离选轨：无可用 enrollment 模板，跳过选轨")
        return _select_target_tracks(track_paths, dict(cfg, target=""))
    enc = sv.VoiceprintEncoder()
    min_sim = float(cfg.get("min_sim") if cfg.get("min_sim") is not None
                    else 0.45)
    margin = float(cfg.get("margin") if cfg.get("margin") is not None
                   else 0.03)
    sims = []
    for p in track_paths:
        try:
            x, rate = _read_wav_mono(p)
            v = enc.embed(x, sample_rate=rate)
            sims.append(max(float(np.dot(v, tv)) for _n, tv in tpls))
        except Exception as e:  # noqa: BLE001
            _vc_log("[ASR] 分离选轨：轨向量提取失败（%s），按 0 分处理：%s"
                    % (os.path.basename(p), e))
            sims.append(0.0)
    sel = [i for i, s in enumerate(sims) if s >= min_sim]
    if not sel:
        sel = [int(np.argmax(sims))]
        _vc_log("[ASR] 分离选轨：无轨达 min_sim=%.2f，保底取最高分轨（%.3f）"
                % (min_sim, float(np.max(sims))))
    rej = [i for i in range(len(sims)) if i not in sel]
    if rej:
        conf = min(sims[i] for i in sel) - max(sims[i] for i in rej)
        if conf < margin:
            _vc_log("[ASR] 分离选轨：低置信（margin %.3f < %.3f），"
                    "影子验证记录" % (conf, margin))
    order = sorted(sel, key=lambda i: -sims[i])
    for rank, i in enumerate(order, 1):
        labels[i] = "说话人%d" % rank
    for i in rej:
        _stats["tracks_dropped"] += 1
        _vc_log("[ASR] 分离选轨：弃轨 #%d（sim=%.3f < %.2f，非目标说话人）"
                % (i + 1, sims[i], min_sim))
    return labels


# ---------------------------------------------------------------- 分离主体


def separate(audio_path, cfg=None, asr_obj=None):
    """主入口：混合音频 → [(标签, 16k wav 路径), ...]。

    全链路异常一律 raise 给调用方（protocol 侧 degraded 回退原轨）；
    本函数内部只在「可恢复」处降级（选轨失败→全量编号、demucs 缺失→
    跳过歌声辅线）并记日志。

    cfg 键见模块 docstring；调用方（protocol._asr_separation_cfg）负责
    读配置与填默认值。
    """
    cfg = dict(cfg or {})
    _stats["calls"] += 1
    dep = probe()
    if not (dep.get("torch") and dep.get("modelscope")):
        _stats["backend_unavailable"] += 1
        _vc_log("[ASR] 语音分离后端不可用（torch=%s modelscope=%s），"
                "degraded 回退原轨——安装 torch + modelscope 后启用"
                % (dep.get("torch"), dep.get("modelscope")))
        raise BackendUnavailable(
            "声源分离依赖缺失：需要 torch + modelscope（可选依赖，"
            "未安装时不阻断转录）")
    _ensure_model_cache_env()

    src, tmp_src = _resolve_source(audio_path, asr_obj)
    try:
        return _separate_impl(src, cfg, dep)
    finally:
        if tmp_src and not cfg.get("keep_temp"):
            try:
                os.remove(tmp_src)
            except OSError:
                pass


def _separate_impl(src, cfg, dep):
    """separate 的实际流程（源文件已落定）。"""
    work = os.path.join(_tmp_root(), "work")
    os.makedirs(work, exist_ok=True)
    p16, p8 = _preproc(src, work)

    cdir = os.path.join(_cache_root(), _cache_key(p16, cfg))
    man = _read_manifest(cdir) if cfg.get("cache", True) else None
    if man and man.get("ok") and _tracks_complete(cdir, man.get("tracks")):
        _stats["cache_hit"] += 1
        _stats["ok"] += 1
        _stats["tracks_returned"] += len(man["tracks"])
        _vc_log("[ASR] 语音分离缓存命中：%d 轨（%s）"
                % (len(man["tracks"]), os.path.basename(cdir)))
        return [(str(t[0]), str(t[1])) for t in man["tracks"]]

    os.makedirs(cdir, exist_ok=True)
    # ① 子进程盲分离（MossFormer2，8k 出轨；完成即退释放显存）
    raw_tracks = _run_worker_separation(p8, p16, cdir, cfg, dep)
    # ② 8k → 16k 重采样落盘（喂 ASR 的统一口径）
    tracks16 = []
    for i, t in enumerate(raw_tracks):
        x, rate = _read_wav_mono(t["path"])
        out = os.path.join(cdir, "track_16k_%d.wav" % i)
        _write_wav_mono(out, _resample_to(x, rate, 16000), 16000)
        tracks16.append({"index": i, "path": out, "energy": t.get("energy")})
    # ③ CAM++ 选轨（本地 enrollment，margin 口径）
    labels = _select_target_tracks([t["path"] for t in tracks16], cfg)
    # ④ Demucs 歌声辅线（可选；失败只跳过，不影响说话人轨）
    vocals_path = None
    if cfg.get("vocals"):
        try:
            vocals_path = _run_worker_demucs(p16, cdir, cfg, dep)
        except Exception as e:  # noqa: BLE001
            _vc_log("[ASR] 分离歌声辅线（Demucs）失败，跳过歌声轨：%s" % (e,))
    tracks = [(labels[i], tracks16[i]["path"])
              for i in range(len(tracks16)) if labels[i]]
    if vocals_path:
        tracks.append(("歌声", vocals_path))
    if not tracks:
        raise SeparationInputError("分离产出为零轨（模型输出为空？）")
    if cfg.get("cache", True):
        _write_manifest(cdir, {
            "ok": True, "version": _sep_version,
            "model": str(cfg.get("model") or _sep_default_model),
            "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            "tracks": [[lbl, path] for lbl, path in tracks],
        })
    _stats["ok"] += 1
    _stats["tracks_returned"] += len(tracks)
    _vc_log("[ASR] 语音分离完成：%d 轨（%s；缓存 %s）"
            % (len(tracks), "、".join(lbl or "?" for lbl, _p in tracks),
               "on" if cfg.get("cache", True) else "off"))
    return tracks


def _spawn_worker(job):
    """起分离子进程并等待（显存编排：进程退出 = CUDA 上下文释放）。"""
    src_root = _dir("src")
    env = dict(os.environ)
    env["PYTHONPATH"] = src_root + (os.pathsep + env["PYTHONPATH"]
                                    if env.get("PYTHONPATH") else "")
    env.setdefault("VT_NO_SYNC", "1")
    cmd = [sys.executable, "-m", "core.asr.separation_backend",
           "__worker__", job]
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    timeout = int(job.get("timeout") or 3600)
    proc = subprocess.run(cmd, capture_output=True, timeout=timeout,
                          cwd=_app_root, env=env,
                          creationflags=flags if os.name == "nt" else 0)
    return proc


def _run_worker_separation(p8, p16, cdir, cfg, dep):
    """跑 MossFormer2 盲分离子进程，返回 [{'index','path','energy'}, ...]。

    失败（子进程非零退出 / manifest 未产出 / 超时）→ ``stats
    ["worker_failed"]`` 计数 + raise（调用方回退原轨）。
    """
    job_path = os.path.join(cdir, "job.json")
    job = {
        "action": "separate",
        "model": str(cfg.get("model") or _sep_default_model),
        "preproc8k": p8,
        "out_dir": cdir,
        "num_speakers": int(cfg.get("num_speakers") or 0),
        "device": str(cfg.get("device") or "auto"),
        "timeout": int(cfg.get("timeout") or 3600),
    }
    with open(job_path, "w", encoding="utf-8") as fh:
        json.dump(job, fh, ensure_ascii=False)
    try:
        proc = _spawn_worker(job_path)
    except subprocess.TimeoutExpired:
        _stats["worker_failed"] += 1
        raise SeparationInputError("分离子进程超时（>%ds），回退原轨"
                                   % (cfg.get("timeout") or 3600))
    except OSError as e:
        _stats["worker_failed"] += 1
        raise SeparationInputError("分离子进程启动失败：%s" % (e,))
    # worker 产物：out_dir（=cdir）下 worker_result.json + track_8k_*.wav
    worker = _read_worker_result(cdir)
    if proc.returncode != 0 or not worker or not worker.get("ok"):
        _stats["worker_failed"] += 1
        err = (worker or {}).get("error") or \
            (proc.stderr or b"")[-300:].decode("utf-8", "replace")
        raise SeparationInputError("分离子进程失败（exit=%s）：%s"
                                   % (proc.returncode, err))
    raw = []
    for t in worker.get("tracks") or []:
        p = t.get("path") if isinstance(t, dict) else t
        if p and os.path.isfile(p):
            raw.append({"index": len(raw), "path": p,
                        "energy": float((t or {}).get("energy") or 0.0)
                        if isinstance(t, dict) else 0.0})
    if not raw:
        _stats["worker_failed"] += 1
        raise SeparationInputError("分离子进程未产出可用音轨")
    return raw


def _read_worker_result(cdir):
    """读 worker 产物清单（worker_result.json，与主 manifest 分离）。"""
    p = os.path.join(cdir, "worker_result.json")
    if not os.path.isfile(p):
        return None
    try:
        with open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001
        return None


def _run_worker_demucs(p16, cdir, cfg, dep):
    """歌声辅线：Demucs htdemucs vocals 干声 → 16k wav，返回路径。

    demucs 包缺失 → 直接跳过（返回 None，不算失败）；子进程失败 raise。
    """
    if not dep.get("demucs"):
        _vc_log("[ASR] 分离歌声辅线：demucs 包缺失，跳过歌声轨")
        return None
    job_path = os.path.join(cdir, "job_demucs.json")
    job = {
        "action": "vocals",
        "model": _sep_demucs_model,
        "preproc16k": p16,
        "out_dir": cdir,
        "device": str(cfg.get("device") or "auto"),
        "timeout": int(cfg.get("timeout") or 3600),
    }
    with open(job_path, "w", encoding="utf-8") as fh:
        json.dump(job, fh, ensure_ascii=False)
    proc = _spawn_worker(job_path)
    worker = _read_worker_result(os.path.join(cdir, "_demucs"))
    if proc.returncode != 0 or not worker or not worker.get("ok"):
        raise SeparationInputError(
            "Demucs 辅线失败（exit=%s）：%s"
            % (proc.returncode,
               (worker or {}).get("error") or
               (proc.stderr or b"")[-300:].decode("utf-8", "replace")))
    out = worker.get("vocals")
    return str(out) if out and os.path.isfile(out) else None


# ---------------------------------------------------------------- worker 子进程侧


def _worker_main(job_path):
    """子进程 worker：真实推理在此（torch lazy import）。

    约定：无论成败都写 worker_result.json（ok / error），父进程读它决定
    回退或继续；本进程**必退**——显存随进程释放，与本地 ASR 错峰。
    """
    with open(job_path, encoding="utf-8") as fh:
        job = json.load(fh)
    action = str(job.get("action") or "separate")
    out_dir = job.get("out_dir") or os.path.dirname(job_path)
    if action == "vocals":
        res_dir = os.path.join(out_dir, "_demucs")
        os.makedirs(res_dir, exist_ok=True)
    else:
        res_dir = out_dir
    result = {"ok": False, "error": "unknown"}
    try:
        _ensure_model_cache_env()
        if action == "vocals":
            result = _worker_vocals(job, res_dir)
        else:
            result = _worker_separate(job, res_dir)
    except Exception as e:  # noqa: BLE001
        result = {"ok": False, "error": "%s: %s"
                  % (type(e).__name__, e)}
    # 产物清单：res_dir/worker_result.json（主 manifest 由父进程写，互不覆盖）
    try:
        with open(os.path.join(res_dir, "worker_result.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False)
    except OSError:
        pass
    sys.exit(0 if result.get("ok") else 2)


def _worker_separate(job, res_dir):
    """MossFormer2 盲分离（真实推理；torch/modelscope lazy import）。"""
    import torch  # noqa: F401  可选依赖：缺失即 fail-fast，父进程回退
    from modelscope.pipelines import pipeline
    from modelscope.utils.constant import Tasks
    device = job.get("device") or "auto"
    if device == "auto":
        device = "cuda:0" if torch.cuda.is_available() else "cpu"
    model = job.get("model") or _sep_default_model
    sep = pipeline(task=Tasks.speech_source_separation, model=model,
                   device=device)
    audio_in = job.get("preproc8k")
    res = sep(audio_in=audio_in)
    # 模型输出形态做防御式解包：优先 output_list（ndarray 列表，8k），
    # 兼容 {"output_pcm_list"} / 裸列表等历史口径。
    arrs = None
    if isinstance(res, dict):
        for key in ("output_list", "output_pcm_list", "outputs", "output"):
            v = res.get(key)
            if isinstance(v, (list, tuple)) and v:
                arrs = list(v)
                break
    elif isinstance(res, (list, tuple)) and res:
        arrs = list(res)
    if not arrs:
        raise RuntimeError("模型输出无可解析音轨：%r" % (type(res).__name__,))
    tracks = []
    for i, arr in enumerate(arrs):
        x = np.asarray(arr, dtype=np.float32).reshape(-1)
        if x.size < 160:  # <20ms 的空轨直接丢弃（模型偶发静默源）
            continue
        energy = float(np.mean(x.astype(np.float64) ** 2))
        if energy < 1e-7:  # 近似静音轨丢弃，避免喂给 ASR 产幻觉
            continue
        p = os.path.join(res_dir, "track_8k_%d.wav" % i)
        _write_wav_mono(p, x, 8000)
        tracks.append({"index": i, "path": p, "energy": energy})
    if not tracks:
        raise RuntimeError("分离输出全为静音轨")
    return {"ok": True, "model": model, "sample_rate": 8000,
            "tracks": tracks}


def _worker_vocals(job, res_dir):
    """Demucs htdemucs：vocals 干声 → 16k wav（歌声标签素材面）。"""
    import torch
    from demucs.api import Separator
    device = job.get("device") or "auto"
    if device == "auto":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    sep = Separator(model=str(job.get("model") or _sep_demucs_model),
                    device=device)
    _, stems = sep.separate_audio_file(job.get("preproc16k"))
    vocals = stems.get("vocals")
    if vocals is None:
        raise RuntimeError("Demucs 未产出 vocals 干声（stems=%s）"
                           % sorted(stems))
    x = vocals.detach().cpu().numpy().astype(np.float32)
    if x.ndim == 2:                      # (channels, samples) → 单声道
        x = x.mean(axis=0)
    x = x.reshape(-1)
    out = os.path.join(res_dir, "vocals_16k.wav")
    _write_wav_mono(out, _resample_to(x, sep.samplerate, 16000), 16000)
    return {"ok": True, "vocals": out}


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "__worker__":
        _worker_main(sys.argv[2])
    else:  # 手工诊断：python -m core.asr.separation_backend <job.json>
        _worker_main(sys.argv[1] if len(sys.argv) > 1 else "")
