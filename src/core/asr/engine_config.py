# -*- coding: utf-8 -*-
# @version 2.7.0
"""引擎「转录配置」注入（自有 ASR 服务 / 本地模型 → 引擎 settings.json）（v2.3.1 拆分工程 · 自 video_toolbox.py 原样搬入）。

v2.3.1 拆分工程；域间依赖规则见 core/__init__.py。
"""
import json
import os
import sys

from core.shared.ai import ai_load_config, ai_mod
from core.shared.paths import DATA_DIR
from core.shared.vcsettings import (apply_global_llm_to_engine,
                                     vc_settings_path,
                                     _vc_read_settings,
                                     _vc_write_settings)

# ---------- 引擎「转录配置」：独立 ASR（自有服务 / 本地模型） ----------
# 引擎的转录模型是枚举项（B 接口 / J 接口 / Whisper [API] ✨ / FasterWhisper ✨），
# 这里把全局 ASR 配置映射过去：service → Whisper [API]（自有 ASR 服务），
# local → FasterWhisper ✨ + 独立模型名/目录。
#: FasterWhisper.Model 是枚举项，枚举外的自定义模型名写不进 settings.json
#: （读盘会被枚举校验拦下），只能靠 vc_asr_patch_apply() 在建任务时覆盖。
FW_MODEL_ENUM = ("tiny", "base", "small", "medium", "large-v1", "large-v2",
                 "large-v3", "large-v3-turbo")
#: 与 videocaptioner.core.entities.TranscribeModelEnum 的值保持一致
TM_WHISPER_API = "Whisper [API] ✨"
TM_FASTER_WHISPER = "FasterWhisper ✨"


def asr_local_override(ai_cfg=None):
    """本地独立 ASR 的覆盖参数：返回 (模型名, 模型目录)；非本地模式返回 None。"""
    try:
        ac = ai_mod().asr_config(ai_cfg or ai_load_config())
    except Exception:  # noqa: BLE001
        return None
    if ac.get("mode") != "local":
        return None
    model = str(ac.get("local_model") or "").strip()
    model_dir = str(ac.get("local_model_dir") or "").strip()
    if not model and not model_dir:
        return None
    return model, model_dir


def apply_asr_to_engine(ai_cfg=None):
    """把全局 ASR 配置写进引擎「转录配置」：转录模型 + WhisperAPI / FasterWhisper。

    service：WhisperAPI 槽写入自有 ASR 服务（地址/密钥/模型/提示词），转录模型切
      到 Whisper [API] ✨；local：转录模型切到 FasterWhisper ✨，模型名（枚举内）
      与模型目录写入 FasterWhisper 槽，枚举外的自定义模型由运行期补丁生效。
    返回 (是否成功, 说明)。
    """
    try:
        ac = ai_mod().asr_config(ai_cfg or ai_load_config())
        data = _vc_read_settings()
        changed = False
        want = TM_FASTER_WHISPER if ac["mode"] == "local" else TM_WHISPER_API
        tr = data.setdefault("Transcribe", {})
        if tr.get("TranscribeModel") != want:
            tr["TranscribeModel"] = want
            changed = True
        if ac["mode"] == "service":
            wa = data.setdefault("WhisperAPI", {})
            for k, v in (("WhisperApiBase", ac["base_url"]),
                         ("WhisperApiKey", ac["api_key"]),
                         ("WhisperApiModel", ac["model"]),
                         ("WhisperApiPrompt", ac["prompt"])):
                if v and wa.get(k) != v:
                    wa[k] = v
                    changed = True
        else:
            fw = data.setdefault("FasterWhisper", {})
            if ac["local_model"] in FW_MODEL_ENUM \
                    and fw.get("Model") != ac["local_model"]:
                fw["Model"] = ac["local_model"]
                changed = True
            if ac["local_model_dir"] \
                    and fw.get("ModelDir") != ac["local_model_dir"]:
                fw["ModelDir"] = ac["local_model_dir"]
                changed = True
        # 识别语言（2026-10-12）：显式语言才写——「自动检测」时刻意不碰
        # TranscribeLanguage，让引擎保留自己的取值（默认也是自动检测），
        # 避免工具箱的默认值把用户在引擎里设过的语言覆盖掉。
        _lang_label = str(ac.get("language_label") or "").strip()
        if _lang_label and _lang_label != "自动检测":
            if tr.get("TranscribeLanguage") != _lang_label:
                tr["TranscribeLanguage"] = _lang_label
                changed = True
        if changed:
            _vc_write_settings(data)
        # 内存态同步（引擎界面/QConfig 已加载时免重启生效）
        # ⚠ 仅在引擎配置**已加载**时才做：没加载时为同步而导入它只会白付
        # ~1s（qfluentwidgets 整库，冷缓存 ~6s），而此后引擎首次读盘拿到
        # 的就是我们刚写的 settings.json——启动路径上的这段同步纯属重复。
        # 引擎界面构建后的 vc_enforce_runtime_cfg() 会再跑一次做真同步。
        if "videocaptioner.ui.common.config" in sys.modules:
            try:
                from videocaptioner.ui.common.config import cfg as _cfg
                from engine_entities import (FasterWhisperModelEnum,
                                             TranscribeModelEnum)
                _cfg.set(_cfg.transcribe_model,
                         TranscribeModelEnum.FASTER_WHISPER if ac["mode"] == "local"
                         else TranscribeModelEnum.WHISPER_API)
                if ac["mode"] == "service":
                    if ac["base_url"]:
                        _cfg.set(_cfg.whisper_api_base, ac["base_url"])
                    if ac["api_key"]:
                        _cfg.set(_cfg.whisper_api_key, ac["api_key"])
                    if ac["model"]:
                        _cfg.set(_cfg.whisper_api_model, ac["model"])
                    if ac["prompt"]:
                        _cfg.set(_cfg.whisper_api_prompt, ac["prompt"])
                elif ac["local_model"] in FW_MODEL_ENUM:
                    for m in FasterWhisperModelEnum:
                        if m.value == ac["local_model"]:
                            _cfg.set(_cfg.faster_whisper_model, m)
                            break
                # 识别语言内存同步（与 settings.json 写入同口径：仅显式语言）
                _lang_label = str(ac.get("language_label") or "").strip()
                if _lang_label and _lang_label != "自动检测":
                    from engine_entities import TranscribeLanguageEnum
                    _cfg.set(_cfg.transcribe_language,
                             TranscribeLanguageEnum(_lang_label))
            except Exception:
                pass
        detail = (f"转录模型 → {'FasterWhisper（本地独立模型）' if ac['mode'] == 'local' else 'Whisper [API]（自有 ASR 服务）'}"
                  + (f"；识别语言 → {ac.get('language_label')}"
                     if str(ac.get("language_label") or "").strip()
                     and ac.get("language_label") != "自动检测" else ""))
        return True, detail
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def vc_asr_patch_apply():
    """运行期补丁：让「独立 ASR 模型」真正生效（幂等，best-effort）。

    引擎的 TaskFactory.create_transcribe_task 把 faster_whisper_model_dir 硬编码
    成数据根 models 目录、模型名取自枚举项；本地独立模型（自定义模型名/模型目录，
    如自训练/微调的 faster-whisper 模型）必须在这里覆盖进 TranscribeConfig 才会
    被 used。service 模式不干预（引擎自己读 WhisperAPI 配置）。
    另：识别语言（asr_language，2026-10-12）为显式非自动值时，同样在这里写进
    TranscribeConfig.transcribe_language（apply_asr_to_engine 的兜底）。
    """
    try:
        from videocaptioner.ui import task_factory as _tf
    except Exception:  # noqa: BLE001
        return False
    if getattr(_tf, "_vt_asr_patched", False):
        return True
    orig = _tf.TaskFactory.create_transcribe_task

    def _patched(*args, **kwargs):
        task = orig(*args, **kwargs)
        try:
            ov = asr_local_override()
            if ov:
                model, model_dir = ov
                tcfg = getattr(task, "transcribe_config", None)
                if tcfg is not None:
                    if model:
                        tcfg.faster_whisper_model = model
                    if model_dir:
                        tcfg.faster_whisper_model_dir = model_dir
            # 识别语言（2026-10-12）：显式语言时直接写进 TranscribeConfig。
            # apply_asr_to_engine 已同步 settings.json 与内存 cfg，这里是兜底——
            # 任务在内存同步之前创建（或 cfg 尚未加载）时同样生效。
            try:
                ac = ai_mod().asr_config(ai_load_config())
            except Exception:  # noqa: BLE001
                ac = {}
            _label = str(ac.get("language_label") or "").strip()
            if _label and _label != "自动检测":
                tcfg = getattr(task, "transcribe_config", None)
                if tcfg is not None:
                    try:
                        from engine_entities import LANGUAGES
                        tcfg.transcribe_language = LANGUAGES.get(_label, "")
                    except Exception:  # noqa: BLE001
                        tcfg.transcribe_language = \
                            ai_mod().asr_language_code(_label)
        except Exception:
            pass
        return task

    _tf.TaskFactory.create_transcribe_task = staticmethod(_patched)
    _tf._vt_asr_patched = True
    return True




__all__ = [
    "asr_local_override",
    "apply_asr_to_engine",
    "vc_asr_patch_apply",
    "FW_MODEL_ENUM",
    "TM_WHISPER_API",
    "TM_FASTER_WHISPER",
]
