# -*- coding: utf-8 -*-
# @version 3.1.3
"""启动预热期间保存设置：不得二次 import 引擎配置而等待导入锁。"""
import builtins
import copy
import enum
import os
import sys
import types
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))

from core.asr import engine_config
from core.shared import vcsettings

CONFIG_MODULE = "videocaptioner.ui.common.config"
ENTITIES_MODULE = "videocaptioner.core.entities"
ENGINE_ENTITIES_MODULE = "engine_entities"
PASS = 0
FAIL = 0


def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print("PASS", name)
    else:
        FAIL += 1
        print("FAIL", name, detail)


class LLMServiceEnum(enum.Enum):
    OTHER = "其他"
    OPENAI = "OpenAI 兼容"


class TranscribeModelEnum(enum.Enum):
    BCUT = "B 接口"
    WHISPER_API = engine_config.TM_WHISPER_API
    FASTER_WHISPER = engine_config.TM_FASTER_WHISPER


class FasterWhisperModelEnum(enum.Enum):
    MEDIUM = "medium"
    LARGE_V3 = "large-v3"


class TranscribeLanguageEnum(enum.Enum):
    AUTO = "自动检测"
    JA = "日本語"


class FakeCfg:
    def __init__(self):
        self.openai_api_base = "openai_api_base"
        self.openai_api_key = "openai_api_key"
        self.openai_model = "openai_model"
        self.llm_service = "llm_service"
        self.transcribe_model = "transcribe_model"
        self.faster_whisper_model = "faster_whisper_model"
        self.transcribe_language = "transcribe_language"
        self.whisper_api_base = "whisper_api_base"
        self.whisper_api_key = "whisper_api_key"
        self.whisper_api_model = "whisper_api_model"
        self.whisper_api_prompt = "whisper_api_prompt"
        self.values = {
            self.llm_service: LLMServiceEnum.OTHER,
            self.transcribe_model: TranscribeModelEnum.BCUT,
            self.faster_whisper_model: FasterWhisperModelEnum.MEDIUM,
            self.transcribe_language: TranscribeLanguageEnum.AUTO,
        }

    def get(self, item):
        return self.values.get(item)

    def set(self, item, value):
        self.values[item] = value


def modules(cfg, with_enums):
    config = types.ModuleType(CONFIG_MODULE)
    if cfg is not None:
        config.cfg = cfg
    entities = types.ModuleType(ENTITIES_MODULE) if with_enums else None
    if entities is not None:
        entities.TranscribeModelEnum = TranscribeModelEnum
        entities.FasterWhisperModelEnum = FasterWhisperModelEnum
        entities.TranscribeLanguageEnum = TranscribeLanguageEnum
    engine_entities = types.ModuleType(ENGINE_ENTITIES_MODULE) if with_enums else None
    if engine_entities is not None:
        engine_entities.LLMServiceEnum = LLMServiceEnum
    return {
        CONFIG_MODULE: config,
        ENTITIES_MODULE: entities,
        ENGINE_ENTITIES_MODULE: engine_entities,
    }


def forbid_engine_imports():
    real_import = builtins.__import__
    blocked = (CONFIG_MODULE, ENTITIES_MODULE, ENGINE_ENTITIES_MODULE)

    def guarded(name, *args, **kwargs):
        if any(name == mod or name.startswith(mod + ".") for mod in blocked):
            raise AssertionError("配置同步不得再次导入：" + name)
        return real_import(name, *args, **kwargs)

    return mock.patch("builtins.__import__", side_effect=guarded)


AI = {
    "enabled": True,
    "base_url": "https://example.com/v1",
    "api_key": "test-only",
    "model": "test-model",
}
ASR = {
    "mode": "service",
    "base_url": "https://asr.example.com/v1",
    "api_key": "asr-test-only",
    "model": "sensevoice",
    "prompt": "输出简体中文",
    "language_label": "日本語",
    "local_model": "",
    "local_model_dir": "",
}


def run_global(cfg, with_enums, ai=None):
    disk = {"LLM": {}}
    writes = []
    with mock.patch.dict(sys.modules, modules(cfg, with_enums)), \
            mock.patch.object(vcsettings, "_vc_read_settings",
                              return_value=copy.deepcopy(disk)), \
            mock.patch.object(vcsettings, "_vc_write_settings",
                              side_effect=lambda data: writes.append(copy.deepcopy(data))), \
            forbid_engine_imports():
        result = vcsettings.apply_global_llm_to_engine(dict(ai or AI))
    return result, writes


def run_asr(cfg, with_enums):
    disk = {"Transcribe": {}}
    writes = []
    fake_ai_mod = types.SimpleNamespace(asr_config=lambda _cfg: dict(ASR))
    with mock.patch.dict(sys.modules, modules(cfg, with_enums)), \
            mock.patch.object(engine_config, "ai_mod", return_value=fake_ai_mod), \
            mock.patch.object(engine_config, "_vc_read_settings",
                              return_value=copy.deepcopy(disk)), \
            mock.patch.object(engine_config, "_vc_write_settings",
                              side_effect=lambda data: writes.append(copy.deepcopy(data))), \
            forbid_engine_imports():
        result = engine_config.apply_asr_to_engine({"test": True})
    return result, writes


for with_enums, label in ((True, "已加载枚举"), (False, "现值类型兜底")):
    cfg = FakeCfg()
    (ok, _), writes = run_global(cfg, with_enums)
    check("全局 LLM 磁盘同步 / " + label,
          ok and writes and writes[-1]["LLM"].get("OpenAI_Model") == "test-model")
    check("全局 LLM 内存同步 / " + label,
          cfg.get(cfg.openai_api_base) == AI["base_url"]
          and cfg.get(cfg.openai_api_key) == AI["api_key"]
          and cfg.get(cfg.openai_model) == AI["model"]
          and cfg.get(cfg.llm_service) == LLMServiceEnum.OPENAI)

    cfg = FakeCfg()
    (ok, _), writes = run_asr(cfg, with_enums)
    check("ASR 磁盘同步 / " + label,
          ok and writes and writes[-1]["Transcribe"].get("TranscribeModel")
          == engine_config.TM_WHISPER_API)
    check("ASR 内存同步 / " + label,
          cfg.get(cfg.transcribe_model) == TranscribeModelEnum.WHISPER_API
          and cfg.get(cfg.whisper_api_base) == ASR["base_url"]
          and cfg.get(cfg.whisper_api_key) == ASR["api_key"]
          and cfg.get(cfg.whisper_api_model) == ASR["model"]
          and cfg.get(cfg.whisper_api_prompt) == ASR["prompt"]
          and cfg.get(cfg.transcribe_language) == TranscribeLanguageEnum.JA)

(ok, _), writes = run_global(None, False)
check("导入中的模块不等待全局 LLM 导入锁", ok and bool(writes))
(ok, _), writes = run_global(None, False, dict(AI, enabled=False,
                                               base_url="", api_key="", model=""))
check("禁用全局 AI 的导入竞态也不阻塞", ok)
(ok, _), writes = run_asr(None, False)
check("导入中的模块不等待 ASR 导入锁", ok and bool(writes))

print("RESULT PASS=%d FAIL=%d" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
