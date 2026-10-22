# -*- coding: utf-8 -*-
# @version 2.5.3
"""自研字幕工作台 UI 的**后端接缝层**（single adapter）。

本包（``vt_engine_ui``）只负责「UI 视觉层」——即规格文档 P3 / 档 C 的自研化。
所有**非 UI**能力（配置读写、任务工厂、后台线程、核心数据模型与枚举、路径
常量、AI/声纹助手）属于档 A/B（P1~P2），目前仍由既有引擎与本项目自研模块
提供。为让「UI 自研化」与「后端自研化」解耦，这里把全部后端依赖收敛到唯一
一个适配模块：

  · P3（现在）：接缝指向既有引擎（``videocaptioner.*``）与本项目自研模块
    （``engine_*`` / ``video_toolbox`` / ``speaker_voiceprint_page``）。
  · P2 完成后：只需改本文件取值来源，UI 各页无需改动。

约束：
  1. **惰性**——所有重量级导入放进函数/属性体，``import _seams`` 本身绝不
     触发引擎导入树（保持宿主 prewarm 优化）。
  2. UI 各页只允许通过本模块访问后端，不得直接 ``import videocaptioner``。
"""
from __future__ import annotations

import importlib
from typing import Any, Optional

__all__ = [
    "cfg", "signal_bus", "TaskFactory", "entities", "constants", "vc_config",
    "platform_utils", "subtitle_style", "translate_types", "ASRData", "threads",
    "apply_asr_to_engine", "voiceprint_enabled_names", "voiceprint_filter_subtitle",
    "ai_mod", "ai_load_config", "vc_log", "extract_web_url",
    "TM_DISPLAY_DEFAULT", "TM_DISPLAY_ASR",
    "VoiceprintEnrollCard", "VoiceprintPicker",
    "backend_available", "backend_error",
]

# 转录下拉的两个显示名（本 UI 自有文案；与 video_toolbox.TM_DISPLAY_* 一致）
TM_DISPLAY_DEFAULT = "默认"
TM_DISPLAY_ASR = "ASR"


def _mod(name: str):
    return importlib.import_module(name)


# --------------------------------------------------------------------------
# 惰性后端取值（属性访问触发导入并缓存）
# --------------------------------------------------------------------------
class _Backend:
    def __init__(self):
        self._c: dict[str, Any] = {}

    def _once(self, key: str, loader):
        if key not in self._c:
            self._c[key] = loader()
        return self._c[key]

    # --- 引擎 UI 后端（档 B，P2 待接管） ---
    @property
    def cfg(self):
        return self._once("cfg", lambda: _mod("videocaptioner.ui.common.config").cfg)

    @property
    def TaskFactory(self):
        # 优先自研 engine_task_factory（P2 尾部 / 档 B 已接管，内建 vc_asr_patch_apply
        # 的本地模型/显式语言覆盖，且经 _selftest_engine_task_factory 逐字段比对引擎
        # 已打补丁工厂一致）；缺失时回退引擎工厂（其行为由 vc_asr_patch_apply 补齐）。
        def _load():
            try:
                return _mod("engine_task_factory").TaskFactory
            except Exception:
                return _mod("videocaptioner.ui.task_factory").TaskFactory
        return self._once("tf", _load)

    # --- 信号总线：自研（见 _signals.py），不依赖引擎 ---
    @property
    def signal_bus(self):
        return self._once("sb", lambda: _mod("vt_engine_ui._signals").signalBus)

    # --- 引擎核心（档 A/B） ---
    @property
    def entities(self):
        return self._once("ent", lambda: _mod("videocaptioner.core.entities"))

    @property
    def constants(self):
        return self._once("const", lambda: _mod("videocaptioner.core.constant"))

    @property
    def vc_config(self):
        return self._once("vccfg", lambda: _mod("videocaptioner.config"))

    @property
    def platform_utils(self):
        return self._once("plat", lambda: _mod("videocaptioner.core.utils.platform_utils"))

    @property
    def subtitle_style(self):
        return self._once("ss", lambda: _mod("videocaptioner.core.subtitle"))

    @property
    def translate_types(self):
        return self._once("tt", lambda: _mod("videocaptioner.core.translate.types"))

    @property
    def core_llm(self):
        return self._once("llm", lambda: _mod("videocaptioner.core.llm"))

    @property
    def core_check_llm(self):
        return self._once("chkllm", lambda: _mod("videocaptioner.core.llm.check_llm"))

    @property
    def core_cache(self):
        return self._once("cache", lambda: _mod("videocaptioner.core.utils.cache"))

    # --- 自研数据模型（档 A，已接管；缺失时回退引擎） ---
    @property
    def ASRData(self):
        def _load():
            try:
                return _mod("engine_asr_data").ASRData
            except Exception:
                return _mod("videocaptioner.core.asr.asr_data").ASRData
        return self._once("asr", _load)

    # --- 后台线程（档 B，P2 待接管） ---
    @property
    def threads(self):
        return self._once("th", lambda: _Threads())

    # --- 本项目助手所在模块 ---
    @property
    def engine_mod(self):
        return self._once("eng", lambda: _mod("video_toolbox"))


class _Threads:
    """后台线程惰性代理（UI 各页不直接 import 引擎线程模块）。"""

    @property
    def TranscriptThread(self):
        return _mod("videocaptioner.ui.thread.transcript_thread").TranscriptThread

    @property
    def VideoInfoThread(self):
        return _mod("videocaptioner.ui.thread.video_info_thread").VideoInfoThread

    @property
    def SubtitleThread(self):
        return _mod("videocaptioner.ui.thread.subtitle_thread").SubtitleThread

    @property
    def RetranslateThread(self):
        return _mod("videocaptioner.ui.thread.subtitle_thread").RetranslateThread

    @property
    def VideoDownloadThread(self):
        return _mod("videocaptioner.ui.thread.video_download_thread").VideoDownloadThread


_bk = _Backend()

# 以模块属性形式暴露惰性后端：``_seams.cfg`` / ``_seams.TaskFactory`` …
_LAZY = {
    "cfg", "TaskFactory", "signal_bus", "entities", "constants", "vc_config",
    "platform_utils", "subtitle_style", "translate_types", "ASRData", "threads",
    "engine_mod", "core_llm", "core_check_llm", "core_cache",
}


def __getattr__(name: str):
    if name in _LAZY:
        return getattr(_bk, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# --------------------------------------------------------------------------
# 本项目助手（AI / 声纹 / 日志）——来自 video_toolbox
# --------------------------------------------------------------------------
def apply_asr_to_engine(ai_cfg=None):
    return _bk.engine_mod.apply_asr_to_engine(ai_cfg)


def voiceprint_enabled_names():
    return _bk.engine_mod.voiceprint_enabled_names()


def voiceprint_filter_subtitle(srt_path, media_path, progress=None):
    return _bk.engine_mod.voiceprint_filter_subtitle(srt_path, media_path, progress)


def ai_mod():
    return _bk.engine_mod.ai_mod()


def ai_load_config():
    return _bk.engine_mod.ai_load_config()


def extract_web_url(text):
    """网页链接识别（宽松：分享文案整段 / 漏协议头 / 带引号 / 尾部标点）。

    纯函数在本项目自研引擎里（``video_toolbox.extract_web_url``）——UI 包不
    自己实现一份，避免同一套判据在两处漂移。
    """
    return _bk.engine_mod.extract_web_url(text)


def vc_log(msg):
    try:
        _bk.engine_mod._vc_log(msg)
    except Exception:
        pass


def generate_task_id() -> str:
    """任务链 ID（引擎 core.llm.context.generate_task_id）。"""
    return _mod("videocaptioner.core.llm.context").generate_task_id()


def self_subtitle_layout(layout):
    """把任意来源的字幕排布枚举规范化为**自研** ``engine_entities.SubtitleLayoutEnum``。

    为什么需要：``_seams.ASRData`` 优先取自研 ``engine_asr_data``，其导出方法
    （``to_srt``/``to_ass``/``save``）按**枚举身份** ``layout == SubtitleLayoutEnum.X``
    分支；而 ``cfg.subtitle_layout.value`` 给的是 **videocaptioner** 的同名枚举——
    两个 Enum 类的成员永不相等，直接传进去会静默落到默认排布（用户选的「译文在上」
    等失效）。两者 ``.value`` 字符串集合一致，故按值归一即可。
    """
    from engine_entities import SubtitleLayoutEnum as _SLE
    if isinstance(layout, _SLE):
        return layout
    return _SLE(layout.value)


# --------------------------------------------------------------------------
# 声纹组件（本项目自研页；缺失时抛异常，调用方 try 兜底）
# --------------------------------------------------------------------------
def VoiceprintEnrollCard(parent=None):
    return _mod("speaker_voiceprint_page").VoiceprintEnrollCard(parent)


def VoiceprintPicker(parent=None):
    return _mod("speaker_voiceprint_page").VoiceprintPicker(parent)


# --------------------------------------------------------------------------
# 自检
# --------------------------------------------------------------------------
_BACKEND_ERR: Optional[str] = None


def backend_available() -> bool:
    """后端（引擎配置 + 核心枚举）是否可导入——供宿主自检/兜底。"""
    global _BACKEND_ERR
    try:
        _ = _bk.cfg
        _ = _bk.entities
        _BACKEND_ERR = None
        return True
    except Exception as e:  # noqa: BLE001
        _BACKEND_ERR = str(e)
        return False


def backend_error() -> Optional[str]:
    return _BACKEND_ERR
