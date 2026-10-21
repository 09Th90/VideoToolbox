# @version 2.4.1
"""运行期常量（自研，替代 videocaptioner.core.constant 的可观察取值）。

只收**运行期可观察**的常量：提示时长来自引擎界面的 InfoBar 行为，
缓存有效期来自引擎翻译/LLM 链路的落盘行为（``expire`` 实参）。
这两类值改动会改变用户可见行为，故以具名常量固化。
"""

from __future__ import annotations

__all__ = [
    "INFOBAR_DURATION_FOREVER",
    "INFOBAR_DURATION_ERROR",
    "INFOBAR_DURATION_WARNING",
    "INFOBAR_DURATION_INFO",
    "INFOBAR_DURATION_SUCCESS",
    "TRANSLATE_CACHE_EXPIRE",
    "LLM_CACHE_EXPIRE",
    "DEFAULT_THREAD_NUM",
    "DEFAULT_BATCH_SIZE",
    "VT_ENGINE_NAME",
]

#: InfoBar 显示时长（毫秒）——与引擎 core.constant 逐值一致。
INFOBAR_DURATION_FOREVER = 24 * 60 * 60 * 1000  # 永久提示: 1天
INFOBAR_DURATION_ERROR = 10000  # Error提示: 10秒
INFOBAR_DURATION_WARNING = 5000  # 警告提示: 5秒
INFOBAR_DURATION_INFO = 3000  # 信息提示: 3秒
INFOBAR_DURATION_SUCCESS = 2000  # 成功提示: 2秒

#: 翻译结果缓存有效期（秒，7 天）。引擎 ``translate/base.py`` 的
#: ``_safe_translate_chunk`` 实参 ``expire=86400 * 7``——失败条目不写缓存，
#: 成功条目 7 天；改动会让历史翻译缓存全部失效、同一段字幕重复计费。
TRANSLATE_CACHE_EXPIRE = 86400 * 7

#: LLM 响应缓存有效期（秒，1 小时）。引擎 ``llm/client.py`` 的
#: ``@memoize(get_llm_cache(), expire=3600, typed=True)``。
LLM_CACHE_EXPIRE = 3600

#: 翻译并发/批量默认值（引擎 SubtitleConfig 字段默认）。
DEFAULT_THREAD_NUM = 10
DEFAULT_BATCH_SIZE = 10

#: 本引擎名称（日志/诊断用）。
VT_ENGINE_NAME = "vt_engine"
