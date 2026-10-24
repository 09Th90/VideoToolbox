# @version 2.7.0
"""vt_engine —— 完整运行引擎（并行开发线，替代 videocaptioner 内嵌引擎）。

定位
----
本项目历史上内嵌第三方字幕引擎（videocaptioner）执行「转写 → 断句 →
优化 → 翻译 → 保存」全链路；P1~P3 已把枚举/缓存/路径/ASR/翻译器/UI
逐接缝自研化，剩余「设置单例 / 任务数据类 / 线程 / 编排」由本包一次性
补齐，形成**不 import 任何 videocaptioner 符号**的完整运行引擎：

* 设置层 ``vt_engine.config``（cfg 单例，读写同一份 settings.json）；
* 数据层 ``vt_engine.entities``（任务数据类 + 枚举）；
* 执行层 ``vt_engine.asr_core`` / ``vt_engine.translators`` /
  ``vt_engine.llm_client`` / ``vt_engine.subtitle_llm``；
* 编排层 ``vt_engine.tasks`` / ``vt_engine.pipeline``；
* 线程层 ``vt_engine.threads``（PySide6，**惰性导入**，供未来
  ``vt_engine_ui._seams`` 切换，当前不接入主程序）。

接入方式（未来，现在不做）
------------------------
宿主把 ``vt_engine_ui/_seams.py`` 的后端取值从 ``videocaptioner.*``
切到 ``vt_engine.*`` 即可，UI 各页无需改动；``VT_ENGINE_UI`` 开关保持
可回退。本包与已接线的 ``engine_*`` 平铺接缝模块**共享同一份实现**
（asr / cache / paths / translate / asr_data），只是把剩余缺口补齐并
收拢为一个包。

红线（自检守护）
--------------
``import vt_engine``（含全部子模块，threads 除外）后
``'videocaptioner' not in sys.modules``。
"""

from __future__ import annotations

__version__ = "2.3.1"
__all__ = [
    "__version__",
    # 设置与路径
    "cfg",
    "settings_path",
    "default_engine_paths",
    # 缓存
    "CacheHub",
    "default_cache_hub",
    # 数据模型
    "ASRData",
    "ASRDataSeg",
    "entities",
    # ASR 链
    "transcribe",
    "WhisperAPI",
    "ChunkedASR",
    "ASRStatus",
    # 翻译链
    "translate_with_machine_fallback",
    "create_translator_from_config",
    "LLMTranslator",
    "TranslationIncompleteError",
    # 任务与编排
    "TaskFactory",
    "transcribe_media",
    "process_subtitle",
    "run_full_process",
    "PipelineError",
    # LLM
    "chat",
    "check_llm_connection",
    "resolve_llm_settings",
    "LLMError",
    # 媒体
    "video2audio",
    "probe_video_info",
    # 样式
    "load_style",
    "available_style_names",
]

from vt_engine.config import cfg, settings_path  # noqa: E402
from vt_engine.paths import default_engine_paths  # noqa: E402
from vt_engine.cache import CacheHub, default_cache_hub  # noqa: E402
from vt_engine.asr_data import ASRData, ASRDataSeg  # noqa: E402
from vt_engine import entities  # noqa: E402
from vt_engine.asr_core import (  # noqa: E402
    ASRStatus, ChunkedASR, WhisperAPI, transcribe,
)
from vt_engine.translate_base import (  # noqa: E402
    TranslationIncompleteError,
)
from vt_engine.llm_translator import LLMTranslator  # noqa: E402
from vt_engine.translate_factory import (  # noqa: E402
    create_translator_from_config, translate_with_machine_fallback,
)
from vt_engine.tasks import TaskFactory  # noqa: E402
from vt_engine.pipeline import (  # noqa: E402
    PipelineError, process_subtitle, run_full_process, transcribe_media,
)
from vt_engine.llm_client import (  # noqa: E402
    LLMError, chat, check_llm_connection, resolve_llm_settings,
)
from vt_engine.media import probe_video_info, video2audio  # noqa: E402
from vt_engine.style_manager import (  # noqa: E402
    available_style_names, load_style,
)


def __getattr__(name):
    # threads 子包依赖 PySide6——惰性导入，保证无 Qt 环境可用本包核心。
    if name == "threads":
        import vt_engine.threads as _th
        return _th
    raise AttributeError("module %r has no attribute %r"
                         % (__name__, name))


def backend_info() -> dict:
    """引擎自检信息（版本/设置路径/关键链路可用性）。"""
    info = {
        "version": __version__,
        "settings_path": settings_path(),
        "threads_available": False,
    }
    try:
        import importlib
        importlib.import_module("PySide6.QtCore")
        info["threads_available"] = True
    except Exception:  # noqa: BLE001
        pass
    return info
