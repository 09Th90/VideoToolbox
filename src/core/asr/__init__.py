# -*- coding: utf-8 -*-
# @version 2.3.1
"""转录域：ASR 全协议适配（OpenAI 兼容 / 百炼原生 / 实时 WS / Deepgram /
ElevenLabs / Gemini / 火山 / AssemblyAI / Azure…）+ vc 转录补丁（协议注入 /
分块 / lazy-cache / 声纹筛选 / 无黑窗）。

行为契约（拆分不许变）：ASR 缓存键算法、分块几何（600s 块 / 10s 重叠 /
并发 3）、幻觉文本过滤、句级 strip 词级不 strip、空语言串不传 language。

施工清单（拆分完成时 __all__ 须覆盖）：

asr_local_override, apply_asr_to_engine, vc_asr_patch_apply,
vc_pydub_nowindow_patch, voiceprint_enabled_names, voiceprint_filter_subtitle,
vc_transcribe_ui_patch, is_realtime_asr_family, is_dashscope_native_asr,
asr_model_hard_guard, asr_strip_endpoint_tail, asr_protocol_fix,
asr_base_guard, asr_model_guard, asr_protocol_of, asr_diarize_of,
asr_separate_of, asr_examples, asr_examples_text, asr_instance_models,
asr_missing_model_hint, is_domestic_ai_endpoint, http_proxies_for,
vc_asr_protocol_patch, vc_asr_chunk_patch, asr_non_zh_en_ratio,
vc_lazy_cache_patch, vc_prepare_settings_file, vc_enforce_runtime_cfg,
vc_migrate_legacy_data, vc_legacy_leftovers
"""

__all__ = []
