# -*- coding: utf-8 -*-
# @version 3.2.5
"""转录域（core/asr）：ASR 全协议适配 + vc 引擎转录补丁。

子模块：
  · ``protocol``  协议推断/纠偏/守卫 + 各服务商 submit（OpenAI 兼容/百炼原生/
                  filetrans/实时 WS/Deepgram/ElevenLabs/Gemini/火山/AssemblyAI/
                  Azure）+ 词级时间轴聚合
  · ``patches``   vc_asr_protocol_patch / vc_asr_chunk_patch /
                  vc_asr_local_model_patch / vc_asr_print_config_patch /
                  vc_builtin_asr_error_patch / asr_non_zh_en_ratio
  · ``enum_compat``        ASR 配置字段的「枚举 / 字符串」双兼容取值（EnumLike）
  · ``engine_config``      引擎「转录配置」注入（asr_local_override /
                    apply_asr_to_engine / vc_asr_patch_apply）
  · ``mode_switch``        本地 / 云端模式切换（写 ai_config + 注入引擎 + 体检）
  · ``voiceprint``         黑窗抑制 + 主播声纹筛选
  · ``ui_patch``           转录 UI 补丁（下拉拆「本地/云端」+ 完成回填）
  · ``runtime_patches``    lazy-cache / settings 预备 / 运行时强制 / 历史迁移

行为契约（拆分不许变）：ASR 缓存键算法、分块几何（600s 块 / 10s 重叠 /
并发 3）、幻觉文本过滤、句级 strip 词级不 strip、空语言串不传 language。
"""
from .protocol import *  # noqa: F401,F403
from .patches import *  # noqa: F401,F403
from .engine_config import *  # noqa: F401,F403
from .mode_switch import *  # noqa: F401,F403
from .voiceprint import *  # noqa: F401,F403
from .ui_patch import *  # noqa: F401,F403
from .runtime_patches import *  # noqa: F401,F403

from .protocol import __all__ as _protocol_all
from .patches import __all__ as _patches_all
from .engine_config import __all__ as _ec_all
from .mode_switch import __all__ as _ms_all
from .voiceprint import __all__ as _vp_all
from .ui_patch import __all__ as _uip_all
from .runtime_patches import __all__ as _rp_all

__all__ = sorted(set(_protocol_all + _patches_all + _ec_all + _ms_all
                        + _vp_all + _uip_all + _rp_all))
