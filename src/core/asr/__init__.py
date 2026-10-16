# -*- coding: utf-8 -*-
# @version 2.3.1
"""转录域（core/asr）：ASR 全协议适配 + vc 引擎转录补丁。

子模块：
  · ``protocol``  协议推断/纠偏/守卫 + 各服务商 submit（OpenAI 兼容/百炼原生/
                  filetrans/实时 WS/Deepgram/ElevenLabs/Gemini/火山/AssemblyAI/
                  Azure）+ 词级时间轴聚合
  · ``patches``   vc_asr_protocol_patch / vc_asr_chunk_patch / asr_non_zh_en_ratio
  · （A2b 待入）  vc_engine_patches / vc_ui_patch

行为契约（拆分不许变）：ASR 缓存键算法、分块几何（600s 块 / 10s 重叠 /
并发 3）、幻觉文本过滤、句级 strip 词级不 strip、空语言串不传 language。
"""
from .protocol import *  # noqa: F401,F403
from .patches import *  # noqa: F401,F403

from .protocol import __all__ as _protocol_all
from .patches import __all__ as _patches_all

__all__ = sorted(set(_protocol_all + _patches_all))
