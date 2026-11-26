# -*- coding: utf-8 -*-
# @version 3.3.1
"""第二音色影子链路（WP2）：第二路声纹编码器 + 影子打分 + 缓存 + 校准建档。

「第二音色」= 第二个声纹编码器模型：wespeaker ResNet34（中文 cnceleb，256 维，
sherpa-onnx hub 的 `wespeaker_zh_cnceleb_resnet34_LM.onnx`），与主路 CAM++
（192 维，`speaker_voiceprint`）**同一批模板、同一批音频、两条独立编码管线**。
动机：单模型同人/异人的分布间隙是唯一防线，第二路提供**独立族源**的相似度
证据，供 G0 后做分数校准与升辅助（keep→review 降级）。

============================================================
影子纪律（复刻 voiceprint_decision.apply_shadow，验收口径）
============================================================
  · **默认 off**：开关 `second_voice` 存 selection.json（读-改-写，与
    auto_filter 同一文件同一模式），出厂 False；
  · off 时 `filter_srt` 行为与 WP1 **逐字节一致**（连 res 都不新增键）；
  · on 影子模式：只把 trace 记进 `res["second_voice"]` + 影子缓存 + 校准
    建档，**绝不参与 decide / 不改 verdict / 不增删产物**（报告一字不加）；
  · 模型缺失 / 下载失败 / 编码异常 → degraded 摘要，主筛选照常；
  · `run_shadow` 是 filter_srt 尾部**唯一**影子入口，内部永不抛出。

============================================================
前处理对齐检查（一次性沙箱，架构先行）
============================================================
  第二路的预处理链是 `trim_silence → normalize_rms → fbank80 → 减均值`，其中
  「减均值」的口径**以模型元数据为准、不盲抄 CAM++**（CAM++ 元数据是
  global-mean——整块减一个标量；wespeaker 通常是 CMN——逐维减时间均值，
  两种口径不可混）。但元数据只能信一半：真正的验收是拿**官方 sherpa-onnx
  管线**在沙箱里对同一批音频出的参考向量，与本模块 `SecondVoiceEncoder.embed`
  的输出逐对算余弦，**全部 cos >= 0.995**（`ALIGN_COS_MIN`）才写对齐标记、
  允许影子启用；不达标则保持 off 并记录原因。本任务（G0）只交检查函数与
  标记读写，不下载模型、不跑真实对齐——真实对齐在后期运行时执行。

============================================================
缓存
============================================================
  影子打分的输入是「整段音频 × 簇划分 × 模板集」，重跑一次就是几十次推理。
  cache_key = media_sha256 前 16 位 + model_id + version + preproc，trace 整体
  落 `data/voiceprint/shadow_cache/<key>.json`；命中直接回放（cached=True），
  零推理、零建档（同输入同结果，回放不该重复累积分布样本）。

依赖：numpy（项目内置）；onnxruntime **lazy import**——模块导入零网络零
onnx 依赖，模型缺失只影响 `run_shadow` 的 degraded 分支。
"""
import hashlib
import json
import os
import time

import numpy as np

import features.voiceprint.speaker_voiceprint as sv

# ---------------------------------------------------------------- 常量

#: 第二路模型文件名（sherpa-onnx hub，wespeaker ResNet34，中文 cnceleb，
#: 输出 256 维）。**本任务不下载**——后期运行时按需走 `ensure_model`。
SECOND_MODEL_NAME = "wespeaker_zh_cnceleb_resnet34_LM.onnx"
SECOND_MODEL_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/"
                    "speaker-recongition-models/" + SECOND_MODEL_NAME)
#: gh-proxy 直连镜像（与主路模型同通道；官方源失败自动切镜像）
SECOND_MODEL_MIRROR_URL = "https://gh-proxy.com/" + SECOND_MODEL_URL
#: 模型 sha256 由下载后就地校验；hub 侧未固化前保持 None（下载时跳过校验，
#: 依赖 gh 仓库自身的完整性；固化后在此填入并升 MODEL_VERSION）。
SECOND_MODEL_SHA256 = None
#: 第二路模型目录与路径（与主路同目录 tools/asr_model）
SECOND_MODEL_PATH = os.path.join(sv.MODEL_DIR, SECOND_MODEL_NAME)

#: 域标识（模板 models 命名空间键 / 叶子 fp 域前缀 / 建档文件名）
MODEL_ID = "wespeaker-zh-cnceleb-resnet34-lm"
#: 模型版本（hub 产物修订号；换模型/换量化必须升版——旧缓存与旧向量随之失效）
MODEL_VERSION = "r1"
#: 预处理链版本（减均值口径经**对齐检查确认**后才允许升版/改动）
PREPROC_VERSION = "fbank80-cmn@v1"
#: 影子 trace schema
TRACE_SCHEMA = "vt.voiceprint.second_shadow.v1"
#: 前处理对齐验收线：本模块 embed 输出与 sherpa 官方参考向量逐对余弦
#: 全部 >= 此值才算对齐通过（留 0.005 余量给浮点/版本差异）。
ALIGN_COS_MIN = 0.995

#: 影子缓存目录覆盖（自检注入；缺省 <data>/voiceprint/shadow_cache）
CACHE_DIR_ENV = "VT_VP_SHADOW_CACHE_DIR"


class BackendUnavailable(RuntimeError):
    """第二路模型 / onnxruntime 缺失（可预期的降级，不是故障）。"""


# ---------------------------------------------------------------- 开关

def second_voice_enabled():
    """「第二音色」开关（selection.json 的 `second_voice` 键，出厂 False）。

    与 `load_auto_filter` 同一读法：文件缺失 / 脏值一律 **False**（安全默认
    ——影子链路宁可不跑，也不让半成品状态影响主筛选）。
    """
    obj = sv._load_selection_obj()
    if not obj:
        return False
    return obj.get("second_voice") is True


def save_second_voice_enabled(value):
    """读-改-写开关（与 save_auto_filter 同模式：只动自己的键，未知键原样
    保留——同一份 selection.json 还住着 enabled / auto_filter / filter_mode /
    threshold_override，整份重建会静默抹掉它们）。"""
    obj = sv._load_selection_obj() or {}
    obj["second_voice"] = bool(value)
    obj["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    os.makedirs(sv.TEMPLATE_DIR, exist_ok=True)
    with open(sv.SELECTION_PATH, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
    return obj["second_voice"]


# ---------------------------------------------------------------- 模型

def model_present():
    """第二路模型是否已就位（存在且非空）。"""
    try:
        return os.path.getsize(SECOND_MODEL_PATH) > 0
    except OSError:
        return False


def ensure_model(progress=None, timeout=300, force=False, stall_seconds=20.0):
    """按需下载第二路模型（后期运行时入口；本任务不调用、不联网）。

    取源顺序与主路 `sv.download_model` 同思路：直连 → gh-proxy 镜像。
    sha256 校验在 `SECOND_MODEL_SHA256` 固化前跳过（None = 未固化）。
    先写 `.part` 再 `os.replace`，中断不留半截文件。失败抛 BackendUnavailable
    ——调用方（run_shadow / enroll 第二路）按 degraded 处理。
    """
    import urllib.request

    if model_present() and not force:
        return SECOND_MODEL_PATH
    os.makedirs(sv.MODEL_DIR, exist_ok=True)
    tmp = SECOND_MODEL_PATH + ".part"

    def _fetch(url):
        req = urllib.request.Request(
            url, headers={"User-Agent": "VideoToolbox/1.18"})
        started = time.time()
        with urllib.request.urlopen(req, timeout=timeout) as resp:
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
                        raise BackendUnavailable(
                            "连接 %d 秒仍无数据" % stall_seconds)

    last = None
    for url in (SECOND_MODEL_URL, SECOND_MODEL_MIRROR_URL):
        try:
            _fetch(url)
            last = None
            break
        except Exception as e:  # noqa: BLE001
            last = e
            try:
                os.remove(tmp)
            except OSError:
                pass
    if last is not None:
        raise BackendUnavailable(
            "第二路模型下载失败：%s；可手动下载后放到 %s\n官方：%s\n镜像：%s"
            % (str(last)[:160], sv.MODEL_DIR, SECOND_MODEL_URL,
               SECOND_MODEL_MIRROR_URL))
    if SECOND_MODEL_SHA256:
        got = hashlib.sha256(open(tmp, "rb").read()).hexdigest()
        if got != SECOND_MODEL_SHA256:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise BackendUnavailable(
                "第二路模型校验不一致（期望 %s…，实际 %s…），已丢弃"
                % (SECOND_MODEL_SHA256[:12], got[:12]))
    os.replace(tmp, SECOND_MODEL_PATH)
    return SECOND_MODEL_PATH


# ---------------------------------------------------------------- 编码器

def apply_feature_norm(feats, norm_type):
    """按模型元数据套「减均值」口径（**不盲抄 CAM++** 的 global-mean）。

    · "global-mean"：整块减**一个标量**均值（CAM++ 的元数据口径）；
    · 其它/"1"/缺省：**CMN**——逐维减时间均值（wespeaker 族的常见口径，
      与 PREPROC_VERSION 的 "cmn" 对应）。
    元数据读不出时按 CMN 走——最终裁决权在 `check_preproc_alignment`
    （cos >= 0.995 才放行），口径写错会在那里被拦成 off。
    """
    x = np.asarray(feats, dtype=np.float32)
    if x.size == 0:
        return x
    if str(norm_type or "").strip().lower() == "global-mean":
        return x - np.float32(float(x.mean()))
    return x - x.mean(axis=0, keepdims=True)


class SecondVoiceEncoder:
    """wespeaker ResNet34 声纹编码器：fbank80 -> 256 维 L2 单位向量。

    与 `sv.VoiceprintEncoder` 同构的**惰性 CPU 会话**（intra_op<=4、
    CPUExecutionProvider），差异只有三点：
      ① 模型缺失抛 `BackendUnavailable`（主路抛 VoiceprintError）——语义是
        「可预期的缺料」，run_shadow / enroll 第二路按 degraded 处理；
      ② 「减均值」口径读模型元数据（见 `apply_feature_norm`）；
      ③ 分块推理上限沿用主路 `EMBED_MAX_FRAMES`（长簇拼接同理受内存约束）。
    """

    EMB_DIM = 256

    def __init__(self, model_path=None):
        self.model_path = model_path or SECOND_MODEL_PATH
        try:
            if os.path.getsize(self.model_path) <= 0:
                raise OSError(self.model_path)
        except OSError:
            raise BackendUnavailable(
                "第二路声纹模型缺失：%s（后期运行时按需下载："
                "second_voiceprint.ensure_model）" % self.model_path)
        self._sess = None
        self._in = None
        self._norm_type = None

    def _session(self):
        if self._sess is None:
            try:
                import onnxruntime as ort
            except ImportError as e:
                raise BackendUnavailable("未安装 onnxruntime：%s" % e)
            so = ort.SessionOptions()
            so.log_severity_level = 3
            so.intra_op_num_threads = max(1, min(4, (os.cpu_count() or 2)))
            sess = ort.InferenceSession(
                self.model_path, sess_options=so,
                providers=["CPUExecutionProvider"])
            self._sess = sess
            self._in = sess.get_inputs()[0].name
            try:
                meta = sess.get_modelmeta().custom_metadata_map or {}
            except Exception:  # noqa: BLE001  元数据读不出 = 按 CMN 走
                meta = {}
            self._norm_type = str(meta.get("feature_normalize_type") or "")
        return self._sess

    def _embed_frames(self, feats):
        x = feats[None, :, :].astype(np.float32)
        y = self._session().run(None, {self._in: x})[0][0]
        y = np.asarray(y, dtype=np.float32)
        nrm = float(np.linalg.norm(y))
        return y / (nrm if nrm > 1e-9 else 1.0)

    def embed(self, samples, sample_rate=sv.SAMPLE_RATE):
        """一段音频 -> L2 归一化 256 维向量。预处理链与主路同源：
        trim_silence（能量 VAD）→ normalize_rms（-20 dBFS）→ fbank80
        → 按元数据减均值 → 分块推理取均值 → L2。音频过短抛 VoiceprintError
        （与主路同一口径，调用方按「判不了」处理）。"""
        if sample_rate != sv.SAMPLE_RATE:
            samples = sv.resample_linear(np.asarray(samples, dtype=np.float32),
                                         sample_rate, sv.SAMPLE_RATE)
        x = sv.normalize_rms(sv.trim_silence(samples, sv.SAMPLE_RATE))
        feats = sv.fbank(x, sv.SAMPLE_RATE)
        if feats.shape[0] < 10:
            raise sv.VoiceprintError(
                "音频太短（%d 帧），至少需要约 0.2 秒人声" % feats.shape[0])
        feats = apply_feature_norm(feats, self._norm_type)
        if feats.shape[0] <= sv.EMBED_MAX_FRAMES:
            return self._embed_frames(feats)
        parts = [self._embed_frames(feats[s:s + sv.EMBED_MAX_FRAMES])
                 for s in range(0, feats.shape[0], sv.EMBED_MAX_FRAMES)]
        y = np.mean(np.stack(parts, axis=0), axis=0)
        nrm = float(np.linalg.norm(y))
        return y / (nrm if nrm > 1e-9 else 1.0)

    def embed_many(self, chunks, sample_rate=sv.SAMPLE_RATE):
        out = []
        for c in chunks:
            try:
                out.append(self.embed(c, sample_rate))
            except sv.VoiceprintError:
                out.append(None)
        return out


# ---------------------------------------------------------------- 对齐检查

def cache_root():
    """影子缓存根（对齐标记 + trace 缓存同住；环境变量可覆盖，自检注入用）。"""
    r = (os.environ.get(CACHE_DIR_ENV) or "").strip().strip('"')
    if r:
        return os.path.abspath(r)
    return os.path.join(sv.TEMPLATE_DIR, "shadow_cache")


def alignment_state_path(model_id=MODEL_ID):
    """对齐标记文件：shadow_cache/alignment_<model_id>.json。"""
    safe = "".join(c for c in str(model_id) if c not in '\\/:*?"<>|')
    return os.path.join(cache_root(), "alignment_%s.json" % (safe or "model"))


def save_alignment_result(result, model_id=MODEL_ID):
    """把沙箱对齐结果写进标记（best-effort）。result 见 `check_preproc_alignment`。

    `preproc` 以**沙箱实际验证的版本**为准（result 里带了就原样保留）——
    沙箱验的是哪个口径，标记就写哪个口径；这样预处理升版后旧标记自动失效
    （`alignment_ok` 比对版本），强制重查而不是拿旧结论蒙混。result 未带时
    才按当前 PREPROC_VERSION 补。"""
    try:
        p = alignment_state_path(model_id)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        obj = dict(result or {})
        obj.setdefault("preproc", PREPROC_VERSION)
        obj.update({"model_id": str(model_id),
                    "checked": time.strftime("%Y-%m-%d %H:%M:%S")})
        tmp = p + ".part"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, p)
        return True
    except (OSError, TypeError, ValueError):
        return False


def load_alignment_state(model_id=MODEL_ID):
    """读对齐标记；缺失/损坏返回 None。"""
    try:
        with open(alignment_state_path(model_id), encoding="utf-8") as fh:
            obj = json.load(fh)
        return obj if isinstance(obj, dict) else None
    except (OSError, ValueError):
        return None


def alignment_ok(model_id=MODEL_ID):
    """对齐是否通过（标记存在、ok、且 preproc 版本与当前一致——升版即失效）。"""
    st = load_alignment_state(model_id)
    if not st:
        return False
    return (st.get("ok") is True
            and (st.get("preproc") or "") == PREPROC_VERSION)


def check_preproc_alignment(samples, references, encoder2=None,
                            threshold=ALIGN_COS_MIN):
    """前处理对齐检查（一次性沙箱跑，本任务只交骨架 + mock 自测）。

    `samples`    同一批音频 PCM 列表（与出参考向量时完全一致）；
    `references` 官方 sherpa-onnx 管线对同一批音频出的参考向量列表（256 维）；
    `encoder2`   本模块编码器（缺省现建；模型缺失抛 BackendUnavailable，
                 属于「没法对齐」——调用方按 off 处理）。
    返回 {"ok", "min_cos", "threshold", "per_item": [{cos}, ...], "reason"}：
    全部成对 cos >= threshold 才 ok=True；数量对不上 / 任一无效 -> ok=False
    并写明原因。通过后用 `save_alignment_result` 落标记，`run_shadow` 的
    对齐门（`alignment_ok`）才放行。
    """
    enc = encoder2 or SecondVoiceEncoder()
    out = {"ok": False, "min_cos": None, "threshold": float(threshold),
           "per_item": [], "reason": ""}
    refs = [np.asarray(r, dtype=np.float32).reshape(-1) for r in (references
                                                                 or [])]
    if len(refs) != len(samples or []) or not refs:
        out["reason"] = "samples/references 数量不一致（%d vs %d）" % (
            len(samples or []), len(refs))
        return out
    coses = []
    for pcm, ref in zip(samples, refs):
        try:
            v = enc.embed(pcm)
        except (sv.VoiceprintError, BackendUnavailable) as e:
            out["reason"] = "本模块编码失败：%s" % str(e)[:120]
            return out
        if ref.size != v.size:
            out["reason"] = "维度不一致（参考 %d vs 本模块 %d）" % (
                ref.size, v.size)
            return out
        coses.append(float(sv.cosine(v, ref)))
    out["per_item"] = [round(c, 6) for c in coses]
    if not coses or any(c != c for c in coses):
        out["reason"] = "存在无效余弦"
        return out
    out["min_cos"] = round(min(coses), 6)
    if out["min_cos"] >= float(threshold):
        out["ok"] = True
    else:
        out["reason"] = ("最低 cos %.4f < 验收线 %.3f：预处理口径与官方管线"
                         "不一致，第二路保持 off" % (out["min_cos"], threshold))
    return out


# ---------------------------------------------------------------- 缓存

def _media_key(media_path, pcm):
    """media_sha256 前 16 位：文件存在按文件字节流算（canonical）；
    文件缺席（自测/纯 PCM 场景）按 PCM float32 字节算（确定性）。"""
    h = hashlib.sha256()
    p = str(media_path or "")
    if p and os.path.isfile(p):
        try:
            with open(p, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            return h.hexdigest()[:16]
        except OSError:
            pass
    h.update(np.asarray(pcm, dtype=np.float32).tobytes())
    return h.hexdigest()[:16]


def cache_key(media_path, pcm):
    """缓存键 = media_sha256前16 + model_id + version + preproc。"""
    return "%s.%s.%s.%s" % (_media_key(media_path, pcm), MODEL_ID,
                            MODEL_VERSION, PREPROC_VERSION.replace("@", "-"))


def _cache_path(key):
    safe = "".join(c for c in str(key) if c not in '\\/:*?"<>|')
    return os.path.join(cache_root(), safe + ".json")


def load_cached(key):
    """读缓存 trace（损坏/缺键返回 None，不抛）。"""
    try:
        with open(_cache_path(key), encoding="utf-8") as fh:
            obj = json.load(fh)
        if isinstance(obj, dict) and obj.get("key") == str(key) \
                and isinstance(obj.get("trace"), dict) \
                and obj["trace"].get("schema") == TRACE_SCHEMA:
            return obj
    except (OSError, ValueError):
        pass
    return None


def save_cached(key, trace):
    """落缓存（best-effort；先 .part 再 replace，失败静默）。"""
    try:
        p = _cache_path(key)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        obj = {"key": str(key), "schema": TRACE_SCHEMA,
               "saved": time.strftime("%Y-%m-%d %H:%M:%S"), "trace": trace}
        tmp = p + ".part"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(obj, fh, ensure_ascii=False)
        os.replace(tmp, p)
        return True
    except (OSError, TypeError, ValueError):
        return False


# ---------------------------------------------------------------- 影子打分

def _r6(x):
    """JSON 安全的分数：None / NaN -> None，其余 round(6)。"""
    if x is None or x != x:
        return None
    return round(float(x), 6)


def _load_second_vecs(names, models_key=MODEL_ID):
    """按模板名收集第二路向量 [(名, 向量)]；缺第二路向量的模板跳过。"""
    out = []
    for n in names or []:
        try:
            t = sv.load_template(n)
        except (sv.VoiceprintError, OSError):
            continue
        models = t.get("models") if isinstance(t.get("models"), dict) else {}
        entry = models.get(models_key) if isinstance(
            models.get(models_key), dict) else {}
        emb = entry.get("embedding")
        if emb is None:
            continue
        v = np.asarray(emb, dtype=np.float32).reshape(-1)
        if v.size:
            out.append((t.get("name") or n, v))
    return out


def score_shadow_clusters(pcm, cues, labels, chunks, tpls_second, enc2,
                          competitor_vecs=None, sample_rate=sv.SAMPLE_RATE):
    """簇级影子打分（复用 filter_srt 已算 labels/chunks，零重复解码）。

    分组口径：本地簇号（labels[i] >= 0）优先；无簇号但带 `[说话人N]` 标签的
    cue 归 "s:<标签>" 组（ASR 分离口径）；两者皆无（音频缺失/过短）跳过——
    这类 cue 本来就进 review，由 `score_shadow_cues` 逐条兜底。

    返回 {簇键: {"target", "competitors", "margin", "best", "n", "seconds"}}：
      target      = 与启用第二路模板（并集，多原型沿用 mix max）的最高余弦；
      competitors = 与**非启用**第二路模板的最高余弦（底噪池样本，建档用）；
      margin      = target - competitors（无底噪池时 None）；
      best        = 命中的启用模板名。
    全部字段 JSON 安全（NaN -> None），可整块进 trace。
    """
    tpls = [(n, np.asarray(v, dtype=np.float32).reshape(-1))
            for n, v in (tpls_second or [])]
    comps = [(n, np.asarray(v, dtype=np.float32).reshape(-1))
             for n, v in (competitor_vecs or [])]
    if chunks is None:
        chunks = sv._cue_chunks(pcm, cues, sample_rate)
    groups, secs = {}, {}
    for i, c in enumerate(cues):
        lb = labels[i] if i < len(labels) else -1
        if lb >= 0:
            key = str(lb)
        else:
            spk = str(getattr(c, "speaker", "") or "")
            if not spk:
                continue
            key = "s:" + spk
        ch = chunks[i] if i < len(chunks) else None
        if ch is None:
            continue
        groups.setdefault(key, []).append(ch)
        secs[key] = secs.get(key, 0.0) + len(ch) / float(sample_rate)
    out = {}
    for key, parts in groups.items():
        row = {"target": None, "competitors": None, "margin": None,
               "best": "", "n": len(parts),
               "seconds": round(secs.get(key, 0.0), 2)}
        try:
            emb = enc2.embed(np.concatenate(parts), sample_rate)
        except (sv.VoiceprintError, BackendUnavailable):
            out[key] = row
            continue
        if tpls:
            scored = [(float(np.dot(emb, v)), n) for n, v in tpls]
            sc, best = max(scored, key=lambda x: x[0])
            row["target"], row["best"] = _r6(sc), best
        if comps:
            cs = [float(np.dot(emb, v)) for _n, v in comps]
            row["competitors"] = _r6(max(cs))
        if row["target"] is not None and row["competitors"] is not None:
            row["margin"] = _r6(row["target"] - row["competitors"])
        out[key] = row
    return out


def score_shadow_cues(pcm, cues, indexes, tpls_second, enc2, chunks=None,
                      competitor_vecs=None, sample_rate=sv.SAMPLE_RATE):
    """review 态 cue 逐条兜底（镜像 `_refine_review_decisions` 的逐 cue 分支）。

    与主路二次判定同一批 index、同一套簇/兜底口径，只是换第二路编码器；
    返回 [{index, num, target, competitors, margin, best}, ...]，供校准
    建档按 (template_fp × language) 累积逐条分布，以及升辅助降级的证据。
    """
    tpls = [(n, np.asarray(v, dtype=np.float32).reshape(-1))
            for n, v in (tpls_second or [])]
    comps = [(n, np.asarray(v, dtype=np.float32).reshape(-1))
             for n, v in (competitor_vecs or [])]
    if chunks is None:
        chunks = sv._cue_chunks(pcm, cues, sample_rate)
    out = []
    for i in indexes or []:
        if not (0 <= i < len(cues)):
            continue
        row = {"index": int(i), "num": getattr(cues[i], "num", i + 1),
               "target": None, "competitors": None, "margin": None, "best": ""}
        ch = chunks[i] if i < len(chunks) else None
        if ch is None:
            out.append(row)
            continue
        try:
            emb = enc2.embed(ch, sample_rate)
        except (sv.VoiceprintError, BackendUnavailable):
            out.append(row)
            continue
        if tpls:
            scored = [(float(np.dot(emb, v)), n) for n, v in tpls]
            sc, best = max(scored, key=lambda x: x[0])
            row["target"], row["best"] = _r6(sc), best
        if comps:
            row["competitors"] = _r6(max(float(np.dot(emb, v))
                                         for _n, v in comps))
        if row["target"] is not None and row["competitors"] is not None:
            row["margin"] = _r6(row["target"] - row["competitors"])
        out.append(row)
    return out


def produce_shadow_trace(media_key, clusters, cues, language="",
                         degraded=None, template_names=None):
    """组装影子 trace（schema=vt.voiceprint.second_shadow.v1）。"""
    return {"schema": TRACE_SCHEMA,
            "media_key": str(media_key or ""),
            "model_id": MODEL_ID,
            "version": MODEL_VERSION,
            "preproc": PREPROC_VERSION,
            "language": str(language or ""),
            "clusters": clusters or {},
            "cues": cues or [],
            "degraded": [str(x) for x in (degraded or [])],
            "template_names": [str(x) for x in (template_names or [])],
            "generated": time.strftime("%Y-%m-%d %H:%M:%S")}


# ---------------------------------------------------------------- 影子入口

def _say(progress, msg):
    if progress:
        try:
            progress(str(msg))
        except Exception:  # noqa: BLE001
            pass


def _record_calibration(clusters, tpls_second, language):
    """把簇级 (target, competitor) 喂给校准建档（best-effort，失败不影响影子）。

    template_fp 用命中模板第二路向量的指纹（与 voiceprint_sync.embedding_fp
    同口径）——同一模板重录会换 fp，分布自然按版本分键，不会混档。
    """
    try:
        import features.voiceprint.score_calibration as sc
        import features.voiceprint.voiceprint_sync as _vps
        fp_by_name = {n: _vps.embedding_fp([float(x) for x in np.asarray(
            v, dtype=np.float32).reshape(-1)]) for n, v in tpls_second or []}
        for key, row in (clusters or {}).items():
            if row.get("target") is None:
                continue
            sc.record(MODEL_ID, fp_by_name.get(row.get("best")) or "-",
                      language, row["target"], row.get("competitors"),
                      extra={"cluster": key})
    except Exception:  # noqa: BLE001  建档失败绝不影响影子摘要
        pass


def run_shadow(media_path, pcm, cues, labels, chunks=None, decisions=None,
               enabled_names=None, progress=None, sample_rate=sv.SAMPLE_RATE,
               language="", encoder2=None):
    """filter_srt 尾部**唯一**影子入口（off 时 filter_srt 根本不该调到这里）。

    门序：开关 → 对齐标记 → 模型 → 模板 → 缓存 → 计算。任何一步不满足都
    返回 off/degraded 摘要并**绝不抛出**；影子输出只写 res["second_voice"]，
    永不改 verdict、不增删产物。缓存命中直接回放（零推理、零建档）。
    """
    summary = {"mode": "shadow", "status": "off", "schema": TRACE_SCHEMA,
               "model_id": MODEL_ID, "model_version": MODEL_VERSION,
               "preproc": PREPROC_VERSION, "language": str(language or ""),
               "reason": "", "cached": False, "clusters": {}, "cues": [],
               "n_clusters": 0, "n_cues": 0, "degraded": [],
               "template_names": [], "media_key": ""}
    try:
        if not second_voice_enabled():
            summary["reason"] = "second_voice_disabled"
            return summary
        if not alignment_ok():
            summary["reason"] = "preproc_alignment_pending"
            return summary
        # 模板门：启用名单里有第二路向量的才算是影子目标
        names = [str(n) for n in (enabled_names or [])]
        tpls_second = _load_second_vecs(names)
        if not tpls_second:
            summary["status"] = "degraded"
            summary["reason"] = "no_second_templates"
            return summary
        summary["template_names"] = [n for n, _v in tpls_second]
        # 竞争者底噪池：库里其余模板的第二路向量（同一模型域，才是可比底噪）
        comp_names = [n for n in sv.list_templates() if n not in set(names)]
        competitor_vecs = _load_second_vecs(comp_names)
        # 模型门
        enc = encoder2
        if enc is None:
            enc = SecondVoiceEncoder()          # 缺模型抛 BackendUnavailable
        key = cache_key(media_path, pcm)
        summary["media_key"] = key.split(".")[0]
        cached = load_cached(key)
        if cached is not None:
            trace = cached["trace"]
            summary.update({"status": "ok", "cached": True,
                            "reason": "cache_hit",
                            "clusters": trace.get("clusters") or {},
                            "cues": trace.get("cues") or [],
                            "language": trace.get("language")
                            or summary["language"],
                            "template_names": trace.get("template_names")
                            or summary["template_names"]})
            summary["n_clusters"] = len(summary["clusters"])
            summary["n_cues"] = len(summary["cues"])
            _say(progress, "第二音色影子：缓存命中，回放 %d 簇 / %d 条"
                 % (summary["n_clusters"], summary["n_cues"]))
            return summary
        # 计算（任何异常 -> degraded，主筛选不受影响）
        try:
            if chunks is None:
                chunks = sv._cue_chunks(pcm, cues, sample_rate)
            clusters = score_shadow_clusters(
                pcm, cues, labels, chunks, tpls_second, enc,
                competitor_vecs=competitor_vecs, sample_rate=sample_rate)
            review_idx = [i for i, row in enumerate(decisions or [])
                          if isinstance(row, dict)
                          and row.get("state") == "review"]
            cue_scores = score_shadow_cues(
                pcm, cues, review_idx, tpls_second, enc, chunks=chunks,
                competitor_vecs=competitor_vecs, sample_rate=sample_rate)
        except Exception as e:  # noqa: BLE001  影子计算绝不能伤主流程
            summary["status"] = "degraded"
            summary["reason"] = "%s: %s" % (type(e).__name__, str(e)[:200])
            return summary
        trace = produce_shadow_trace(summary["media_key"], clusters,
                                     cue_scores, language=language,
                                     template_names=summary["template_names"])
        save_cached(key, trace)
        _record_calibration(clusters, tpls_second, language)
        summary.update({"status": "ok", "clusters": clusters,
                        "cues": cue_scores,
                        "n_clusters": len(clusters), "n_cues": len(cue_scores)})
        _say(progress, "第二音色影子：%d 簇 / %d 条 review cue 已记录"
             % (summary["n_clusters"], summary["n_cues"]))
        return summary
    except BackendUnavailable as e:
        summary["status"] = "degraded"
        summary["reason"] = "model_missing: %s" % str(e)[:160]
        return summary
    except Exception as e:  # noqa: BLE001  最外层兜底：永不抛出
        summary["status"] = "degraded"
        summary["reason"] = "%s: %s" % (type(e).__name__, str(e)[:200])
        return summary


__all__ = ["SECOND_MODEL_NAME", "SECOND_MODEL_URL", "SECOND_MODEL_MIRROR_URL",
           "SECOND_MODEL_PATH", "MODEL_ID", "MODEL_VERSION", "PREPROC_VERSION",
           "TRACE_SCHEMA", "ALIGN_COS_MIN", "CACHE_DIR_ENV",
           "BackendUnavailable", "second_voice_enabled",
           "save_second_voice_enabled", "model_present", "ensure_model",
           "apply_feature_norm", "SecondVoiceEncoder",
           "cache_root", "alignment_state_path", "save_alignment_result",
           "load_alignment_state", "alignment_ok", "check_preproc_alignment",
           "cache_key", "load_cached", "save_cached",
           "score_shadow_clusters", "score_shadow_cues",
           "produce_shadow_trace", "run_shadow", "_load_second_vecs"]
