# -*- coding: utf-8 -*-
# @version 2.9.0
"""本地 ASR 全链自检（可复跑；正向 + **负向**验证）。

覆盖：目录解析优先级、完全离线加载、GPU→CPU 自动降级、缺模型/坏文件报错、
端到端转录（无外部 exe）、缓存键形式、幻觉过滤、声纹模型不受影响、
云端配置未被改动；负向用例包含「屏蔽目录」「弄坏模型文件」「GPU/CPU 双失败」，
并验证错误路径生效后**能自愈**。

运行（cwd = 程序根，铁律：程序根用 os.getcwd()）::

    tools\\python\\python.exe src\\_selftest_local_asr.py

设计约束：所有负向用例都在 ``data\\tmp`` 的临时沙盒里做，或靠「注入不存在的
tools_dir / monkeypatch WhisperModel」实现，**绝不改动真实权重文件**。
"""

from __future__ import annotations

import glob
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import wave

ROOT = os.getcwd()
SRC_DIR = os.path.join(ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

# 完全离线：杜绝任何 HF 联网尝试；日志隔离到 *_selftest.log
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("VT_SELFTEST", "1")

import asr_local_paths as paths  # noqa: E402
import engine_asr_local as local  # noqa: E402
from engine_asr_data import ASRData  # noqa: E402

RESULTS = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    """记录一项断言并即时打印。"""
    ok = bool(ok)
    RESULTS.append((name, ok, str(detail)))
    print("[%s] %s%s" % ("PASS" if ok else "FAIL", name,
                         (" | " + str(detail)[:300]) if detail else ""),
          flush=True)
    return ok


def sha256_of(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def make_silence_wav(path: str) -> None:
    """1 秒 16 kHz 单声道静音，供真实推理用。"""
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 16000)


def make_fake_model_dir(directory: str, source: str, corrupt: bool) -> None:
    """在沙盒里造一个「结构完整但内容可控」的模型目录。

    ``corrupt=True`` 时写坏 config.json / model.bin，用于验证加载报错路径；
    为 False 时从真实 small.en 复制小体积元数据，仅 model.bin 用占位字节。
    """
    os.makedirs(directory, exist_ok=True)
    for name in ("config.json", "tokenizer.json", "vocabulary.txt"):
        src = os.path.join(source, name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(directory, name))
    if corrupt:
        with open(os.path.join(directory, "config.json"), "w",
                  encoding="utf-8") as f:
            f.write("{ 这不是合法 JSON")
        with open(os.path.join(directory, "tokenizer.json"), "w",
                  encoding="utf-8") as f:
            f.write("{}")
        with open(os.path.join(directory, "vocabulary.txt"), "w",
                  encoding="utf-8") as f:
            f.write("{}")
        with open(os.path.join(directory, "model.bin"), "wb") as f:
            f.write(b"NOT-A-CTRANSFORMERS-MODEL")
    else:
        with open(os.path.join(directory, "model.bin"), "wb") as f:
            f.write(b"\x00" * 4096)


def latest_relocate_log():
    """取最新的搬移审计日志，读声纹模型 SHA-256 基线。"""
    items = sorted(glob.glob(os.path.join(ROOT, "logs",
                                         "asr_model_relocate_*.log")))
    if not items:
        return "", ""
    text = ""
    with open(items[-1], encoding="utf-8", errors="replace") as f:
        text = f.read()
    for line in reversed(text.splitlines()):
        if "BASELINE voiceprint " in line:
            parts = line.split("BASELINE voiceprint ", 1)[1].strip().split()
            if len(parts) >= 2:
                return parts[0], parts[1]
    return "", ""


def main() -> int:
    print("SELFTEST local ASR | root=%s | python=%s"
          % (ROOT, sys.executable), flush=True)
    sandbox = tempfile.TemporaryDirectory(prefix="vt_asr_selftest_")
    tmp = sandbox.name
    silence = os.path.join(tmp, "silence.wav")
    make_silence_wav(silence)

    root = paths.model_root()
    print("MODEL_ROOT=%s" % root, flush=True)

    # T09 的 large-v3 独立子进程验证必须放在**任何真实模型加载之前**：
    # CTranslate2/MKL 工作区在同进程反复加载后会持续占内存，父进程若已加载
    # small.en，子进程再加载 3 GiB 的 large-v3 会 mkl_malloc 失败（本机可用
    # 内存约 4~6 GiB）。干净父进程 + 干净子进程 = 真实用户「只开一个模型」场景。
    large_v3_load_ok = False
    large_v3_load_out = ""
    try:
        import subprocess
        code = (
            "import os, sys\n"
            "sys.path.insert(0, %r)\n"
            "os.environ.setdefault('HF_HUB_OFFLINE', '1')\n"
            "os.environ.setdefault('HF_HUB_DISABLE_TELEMETRY', '1')\n"
            "from engine_asr_local import load_local_model\n"
            "m, d, c = load_local_model(%r, 'cpu')\n"
            "print('SUBPROCESS_LOAD_OK', d, c)\n"
            % (SRC_DIR, os.path.join(root, "large-v3"))
        )
        proc = subprocess.run([sys.executable, "-c", code],
                              capture_output=True, text=True, timeout=300)
        large_v3_load_out = ((proc.stdout or "") + " "
                             + (proc.stderr or "")).strip()
        large_v3_load_ok = (proc.returncode == 0
                            and "SUBPROCESS_LOAD_OK" in large_v3_load_out)
    except Exception as exc:  # noqa: BLE001
        large_v3_load_out = repr(exc)

    # ---------- T01 目录解析：工具箱内模型齐备 ----------
    avail = paths.list_available_models()
    check("T01 工具箱内完整模型清单", "large-v3" in avail and "small.en" in avail,
          "available=%s" % avail)
    p_large = ""
    p_small = ""
    try:
        p_large = paths.resolve_model_dir("large-v3")
        p_small = paths.resolve_model_dir("small.en")
        check("T01b large-v3/small.en 解析到工具箱",
              os.path.normcase(p_large) == os.path.normcase(
                  os.path.join(root, "large-v3"))
              and os.path.normcase(p_small) == os.path.normcase(
                  os.path.join(root, "small.en")),
              "large=%s small=%s" % (p_large, p_small))
        for label, p in (("large-v3", p_large), ("small.en", p_small)):
            check("T01c %s 权重完整" % label,
                  paths.is_complete_model_dir(p), p)
    except Exception as exc:  # noqa: BLE001
        check("T01b large-v3/small.en 解析到工具箱", False, repr(exc))

    # ---------- T02 目录解析优先级 ----------
    fake_dir = os.path.join(tmp, "fake_model")
    make_fake_model_dir(fake_dir, p_small, corrupt=False)
    try:
        got = paths.resolve_model_dir("small.en", explicit_dir=fake_dir)
        check("T02 显式有效目录优先",
              os.path.normcase(got) == os.path.normcase(fake_dir), got)
    except Exception as exc:  # noqa: BLE001
        check("T02 显式有效目录优先", False, repr(exc))

    empty_dir = os.path.join(ROOT, "data", "videocaptioner", "models")
    try:
        got = paths.resolve_model_dir("large-v3", explicit_dir=empty_dir)
        check("T02b 无效显式目录（引擎写死的空 models）自动回退工具箱",
              os.path.normcase(got) == os.path.normcase(p_large), got)
    except Exception as exc:  # noqa: BLE001
        check("T02b 无效显式目录自动回退工具箱", False, repr(exc))

    # ---------- T03 [负向] 屏蔽工具箱目录 → 清晰中文错误 ----------
    blocked_tools = os.path.join(tmp, "no_such_tools")
    old_hf = os.environ.get("HF_HOME")
    os.environ["HF_HOME"] = os.path.join(tmp, "empty_hf_home")
    try:
        try:
            paths.resolve_model_dir("large-v3", tools_dir=blocked_tools)
            check("T03 [负向] 屏蔽目录后报中文错误", False, "未抛异常")
        except paths.ModelDirNotFound as exc:
            msg = str(exc)
            check("T03 [负向] 屏蔽目录后报中文错误",
                  ("未找到" in msg and "config.json" in msg
                   and "asr_model" in msg and "设置" in msg),
                  msg.replace("\n", " / ")[:260])
    finally:
        if old_hf is None:
            os.environ.pop("HF_HOME", None)
        else:
            os.environ["HF_HOME"] = old_hf

    # ---------- T04 [负向] 显式目录缺权重 → 被忽略且报错 ----------
    broken_dir = os.path.join(tmp, "only_config")
    os.makedirs(broken_dir, exist_ok=True)
    with open(os.path.join(broken_dir, "config.json"), "w",
              encoding="utf-8") as f:
        f.write("{}")
    old_hf = os.environ.get("HF_HOME")
    os.environ["HF_HOME"] = os.path.join(tmp, "empty_hf_home")
    try:
        try:
            paths.resolve_model_dir("large-v3", explicit_dir=broken_dir,
                                   tools_dir=blocked_tools)
            check("T04 [负向] 缺权重目录不被误当模型", False, "未抛异常")
        except paths.ModelDirNotFound as exc:
            check("T04 [负向] 缺权重目录不被误当模型",
                  "候选路径" in str(exc) and "缺权重文件" in str(exc),
                  str(exc).replace("\n", " / ")[:220])
    finally:
        if old_hf is None:
            os.environ.pop("HF_HOME", None)
        else:
            os.environ["HF_HOME"] = old_hf

    # ---------- T05 [负向] 弄坏模型文件 → 加载报错 + 自愈 ----------
    corrupt_dir = os.path.join(tmp, "corrupt_model")
    make_fake_model_dir(corrupt_dir, p_small, corrupt=True)
    local.clear_model_cache()
    local.clear_log_records()
    try:
        try:
            local.load_local_model(corrupt_dir, device="cpu")
            check("T05 [负向] 坏 config/model.bin 触发中文加载错误", False,
                  "未抛异常")
        except RuntimeError as exc:
            msg = str(exc)
            check("T05 [负向] 坏 config/model.bin 触发中文加载错误",
                  "模型加载失败" in msg and "请检查模型目录" in msg,
                  msg.replace("\n", " / ")[:260])
    except Exception as exc:  # noqa: BLE001
        check("T05 [负向] 坏 config/model.bin 触发中文加载错误", False,
              repr(exc))
    # 自愈：把 config.json 修好（目录层）+ 清缓存后真实模型重新可加载
    if os.path.isfile(os.path.join(p_small, "config.json")):
        shutil.copy2(os.path.join(p_small, "config.json"),
                     os.path.join(corrupt_dir, "config.json"))
    check("T05b 弄坏文件后修复（目录层自愈）",
          paths.is_complete_model_dir(corrupt_dir), corrupt_dir)
    local.clear_model_cache()
    try:
        _m, dev, compute = local.load_local_model(p_small, device="cpu")
        check("T05c 错误路径后清缓存重新加载成功（运行层自愈）",
              dev == "cpu" and compute == "int8", "%s/%s" % (dev, compute))
    except Exception as exc:  # noqa: BLE001
        check("T05c 错误路径后清缓存重新加载成功（运行层自愈）", False,
              repr(exc))

    # ---------- T06 GPU→CPU 自动降级（注入 cuBLAS 异常） ----------
    import faster_whisper
    original_cls = faster_whisper.WhisperModel
    calls = []

    class FakeWhisperModel:
        """cuda 抛 cuBLAS 缺失；cpu 返回可用桩。"""

        def __init__(self, path, device="auto", compute_type="default",
                     local_files_only=False, **_kw):
            calls.append((str(path), device, compute_type,
                          bool(local_files_only)))
            if device == "cuda":
                raise RuntimeError(
                    "Library cublas64_12.dll is not found or cannot be loaded")
            self.path = str(path)

        def transcribe(self, audio, **_kw):
            info = type("Info", (), {"duration": 0.0, "language": "en"})()
            return iter([]), info

    local.clear_model_cache()
    local.clear_log_records()
    try:
        faster_whisper.WhisperModel = FakeWhisperModel
        model, dev, compute = local.load_local_model(p_small, device="cuda")
        check("T06 GPU(cuda/float16) 失败自动降级 CPU/int8",
              dev == "cpu" and compute == "int8" and model is not None,
              "%s/%s calls=%s" % (dev, compute, calls))
        records = local.get_log_records()
        check("T06b 降级写日志（不静默）",
              any("降级" in r for r in records)
              and any("cublas" in r.lower() for r in records),
              " | ".join(records[-3:])[:260])
        check("T06c 全程 local_files_only=True 且 HF_HUB_OFFLINE=1",
              all(c[3] for c in calls)
              and os.environ.get("HF_HUB_OFFLINE") == "1",
              "calls=%s" % calls)
    except Exception as exc:  # noqa: BLE001
        check("T06 GPU(cuda/float16) 失败自动降级 CPU/int8", False, repr(exc))
    finally:
        faster_whisper.WhisperModel = original_cls
        local.clear_model_cache()

    # ---------- T07 [负向] GPU 与 CPU 都失败 → 不静默、抛中文错误 ----------
    class AlwaysFailModel:
        def __init__(self, path, device="auto", compute_type="default",
                     local_files_only=False, **_kw):
            raise RuntimeError("%s/%s 加载失败（注入）" % (device, compute_type))

        def transcribe(self, audio, **_kw):
            return iter([]), None

    local.clear_log_records()
    try:
        faster_whisper.WhisperModel = AlwaysFailModel
        try:
            local.load_local_model(p_small, device="cuda")
            check("T07 [负向] 双失败时不静默", False, "未抛异常")
        except RuntimeError as exc:
            msg = str(exc)
            check("T07 [负向] 双失败时不静默（含两次异常摘要）",
                  "模型加载失败" in msg and "cuda/float16" in msg
                  and "cpu/int8" in msg,
                  msg.replace("\n", " / ")[:260])
        check("T07b 双失败写日志",
              len(local.get_log_records()) >= 2,
              "records=%d" % len(local.get_log_records()))
    finally:
        faster_whisper.WhisperModel = original_cls
        local.clear_model_cache()

    # ---------- T06d [负向] 推理阶段 cuBLAS 失败 → 端到端自动降级 ----------
    # 本机实测：cuda/float16 模型**能加载**，直到 transcribe 才抛
    # "Library cublas64_12.dll is not found"。只覆盖加载阶段的降级是不够的。
    class GpuInferFailModel:
        def __init__(self, path, device="auto", compute_type="default",
                     local_files_only=False, **_kw):
            self.device = device

        def transcribe(self, audio, **_kw):
            if self.device == "cuda":
                raise RuntimeError(
                    "Library cublas64_12.dll is not found or cannot be loaded")
            info = type("Info", (), {"duration": 0.0, "language": "en"})()
            return iter([]), info

    local.reset_gpu_state()
    local.clear_log_records()
    try:
        faster_whisper.WhisperModel = GpuInferFailModel
        asr = local.FasterWhisperASR(
            silence, whisper_model="small.en", device="cuda", language="",
            vad_filter=False, use_cache=False)
        data = asr.run(callback=lambda _p, _m: None)
        check("T06d [负向] 推理阶段 cuBLAS 失败自动降级 CPU/int8",
              isinstance(data, ASRData) and asr._device_used == "cpu",
              "device=%s compute=%s segments=%d"
              % (asr._device_used, asr._compute_used, len(data)))
        records = local.get_log_records()
        check("T06e 推理阶段降级写日志（不静默）",
              any("推理失败" in r and "降级" in r for r in records),
              " | ".join(records[-3:])[:260])
    except Exception as exc:  # noqa: BLE001
        check("T06d [负向] 推理阶段 cuBLAS 失败自动降级 CPU/int8", False,
              repr(exc))
    finally:
        faster_whisper.WhisperModel = original_cls
        local.reset_gpu_state()

    # ---------- T08 真实离线加载 small.en + 1s 静音推理 ----------
    local.clear_model_cache()
    try:
        model, dev, compute = local.load_local_model(p_small, device="cpu")
        check("T08 small.en 完全离线加载（CPU/int8）",
              dev == "cpu" and compute == "int8", "%s/%s" % (dev, compute))
        segments, info = model.transcribe(
            silence, language=None, beam_size=1, vad_filter=False,
            temperature=0)
        n = len(list(segments))
        check("T08b 1s 静音离线推理成功",
              isinstance(n, int) and info is not None,
              "segments=%d lang=%s" % (n, getattr(info, "language", "")))
    except Exception as exc:  # noqa: BLE001
        check("T08 small.en 完全离线加载（CPU/int8）", False, repr(exc))

    # ---------- T09 真实离线加载 large-v3（结果由启动阶段的干净子进程取得） ----------
    check("T09 large-v3 完全离线加载（CPU/int8，独立子进程）",
          large_v3_load_ok, large_v3_load_out[-300:])

    # ---------- T10 端到端：无外部 exe 完成转录 + 缓存键形式 ----------
    local.clear_model_cache()
    local.clear_log_records()
    try:
        asr = local.FasterWhisperASR(
            silence, whisper_model="small.en", device="cpu", language="",
            vad_filter=False, use_cache=False, need_word_time_stamp=False)
        data = asr.run(callback=lambda _p, _m: None)
        check("T10 端到端转录（无任何外部 exe）",
              isinstance(data, ASRData),
              "segments=%d device=%s compute=%s dir=%s"
              % (len(data), asr._device_used, asr._compute_used,
                 asr._resolved_model_dir))
        key = asr._get_key()
        check("T10b 缓存键形式 crc32hex-md5(cmd) 未变",
              re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{32}", key) is not None, key)
    except Exception as exc:  # noqa: BLE001
        check("T10 端到端转录（无任何外部 exe）", False, repr(exc))

    # ---------- T11 引擎分支：字符串模型名覆盖不再崩 ----------
    try:
        import engine_asr
        from engine_entities import TranscribeModelEnum

        class FakeConfig:
            """模拟 asr_local_override() 把枚举覆盖成字符串后的 TranscribeConfig。"""
            transcribe_model = TranscribeModelEnum.FASTER_WHISPER
            need_word_time_stamp = False
            transcribe_language = "yue"
            whisper_api_model = "whisper-1"
            whisper_api_key = ""
            whisper_api_base = ""
            whisper_api_prompt = ""
            faster_whisper_model = "large-v3"          # 字符串（补丁覆盖）
            faster_whisper_model_dir = empty_dir       # 空的 models 目录
            faster_whisper_device = "cuda"
            faster_whisper_vad_filter = True
            faster_whisper_vad_threshold = 0.4
            faster_whisper_vad_method = "silero_v4"
            faster_whisper_ff_mdx_kim2 = False
            faster_whisper_one_word = True
            faster_whisper_prompt = ""

        chunked = engine_asr._create_asr_instance(silence, FakeConfig())
        kw = chunked.asr_kwargs
        check("T11 FASTER_WHISPER 分支构造不再抛 EnvironmentError",
              chunked.asr_class is local.FasterWhisperASR
              and kw.get("whisper_model") == "large-v3",
              "model=%r dir=%r device=%r"
              % (kw.get("whisper_model"), kw.get("model_dir"),
                 kw.get("device")))
    except Exception as exc:  # noqa: BLE001
        check("T11 FASTER_WHISPER 分支构造不再抛 EnvironmentError", False,
              repr(exc))

    # ---------- T12 幻觉过滤 / 音乐标记（行为契约） ----------
    try:
        srt = ("1\n00:00:00,000 --> 00:00:02,000\n请不吝点赞 订阅 转发\n\n"
               "2\n00:00:02,000 --> 00:00:04,000\n【音乐】\n\n"
               "3\n00:00:04,000 --> 00:00:06,000\n正常台词\n")
        segs = local.FasterWhisperASR._make_segments(None, srt)
        check("T12 幻觉文本 / 音乐标记过滤保留",
              len(segs) == 1 and segs[0].text.strip() == "正常台词",
              "kept=%s" % [s.text for s in segs])
    except Exception as exc:  # noqa: BLE001
        check("T12 幻觉文本 / 音乐标记过滤保留", False, repr(exc))

    # ---------- T13 云端配置未被改动 ----------
    try:
        with open(os.path.join(ROOT, "data", "ai_config.json"),
                  encoding="utf-8-sig") as f:
            ai = json.load(f)
        with open(os.path.join(ROOT, "data", "videocaptioner", "settings.json"),
                  encoding="utf-8-sig") as f:
            st = json.load(f)
        check("T13 asr_mode 保持 service（云端回归不受影响）",
              ai.get("asr_mode") == "service", str(ai.get("asr_mode")))
        check("T13b settings.json TranscribeModel 保持 Whisper [API]",
              st.get("Transcribe", {}).get("TranscribeModel")
              == "Whisper [API] ✨",
              str(st.get("Transcribe", {}).get("TranscribeModel")))
        check("T13c FasterWhisper.Program 不再是必需项",
              st.get("FasterWhisper", {}).get("Program", None) == "",
              str(st.get("FasterWhisper", {}).get("Program")))
    except Exception as exc:  # noqa: BLE001
        check("T13 云端配置未被改动", False, repr(exc))

    # ---------- T14 声纹模型不受影响 ----------
    try:
        vp = os.path.join(ROOT, "tools", "asr_model",
                          paths.VOICEPRINT_MODEL_NAME)
        exists = os.path.isfile(vp)
        size = os.path.getsize(vp) if exists else -1
        sha = sha256_of(vp) if exists else ""
        base_sha, base_size = latest_relocate_log()
        check("T14 声纹模型仍在且与搬移日志基线一致",
              exists and size == 28281138
              and (not base_sha or sha == base_sha)
              and (not base_size or str(size) == base_size),
              "size=%d sha=%s baseline=%s/%s" % (size, sha[:16],
                                                 base_sha[:16], base_size))
        top = sorted(os.listdir(os.path.join(ROOT, "tools", "asr_model")))
        check("T14b tools/asr_model 根目录未被破坏",
              paths.VOICEPRINT_MODEL_NAME in top and "faster-whisper" in top,
              str(top))
    except Exception as exc:  # noqa: BLE001
        check("T14 声纹模型不受影响", False, repr(exc))

    # ---------- T15 [负向] 屏蔽目录报错后恢复解析（自愈） ----------
    old_hf = os.environ.get("HF_HOME")
    os.environ["HF_HOME"] = os.path.join(tmp, "empty_hf_home")
    try:
        blocked = False
        try:
            paths.resolve_model_dir("large-v3", tools_dir=blocked_tools)
        except paths.ModelDirNotFound:
            blocked = True
        check("T15 [负向] 屏蔽目录 → 报错生效", blocked)
        healed = paths.resolve_model_dir("large-v3")
        check("T15b 屏蔽解除后解析成功（自愈）",
              os.path.normcase(healed) == os.path.normcase(p_large), healed)
    except Exception as exc:  # noqa: BLE001
        check("T15b 屏蔽解除后解析成功（自愈）", False, repr(exc))
    finally:
        if old_hf is None:
            os.environ.pop("HF_HOME", None)
        else:
            os.environ["HF_HOME"] = old_hf

    # ---------- T16 降级日志确实落盘 ----------
    try:
        log_path = os.path.join(ROOT, "logs", "vc_fallback_selftest.log")
        text = ""
        if os.path.isfile(log_path):
            with open(log_path, encoding="utf-8", errors="replace") as f:
                text = f.read()
        check("T16 本地 ASR 运行日志已落盘",
              "本地ASR" in text, "log=%s bytes=%d" % (log_path, len(text)))
    except Exception as exc:  # noqa: BLE001
        check("T16 本地 ASR 运行日志已落盘", False, repr(exc))

    sandbox.cleanup()

    passed = sum(1 for _n, ok, _d in RESULTS if ok)
    failed = [n for n, ok, _d in RESULTS if not ok]
    negative = [n for n, _ok, _d in RESULTS if "[负向]" in n]
    print("-" * 72, flush=True)
    print("NEGATIVE_CASES=%s" % json.dumps(negative, ensure_ascii=False),
          flush=True)
    print("SUMMARY passed=%d/%d failed=%s" % (passed, len(RESULTS), failed),
          flush=True)
    verdict = "PASS" if passed == len(RESULTS) else "FAIL"
    print("SELFTEST_RESULT=%s" % verdict, flush=True)
    print("SELFTEST_JSON=" + json.dumps({
        "result": verdict, "passed": passed, "total": len(RESULTS),
        "negative_cases": negative, "failed": failed,
        "large_v3_dir": p_large, "small_en_dir": p_small,
    }, ensure_ascii=False), flush=True)
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
