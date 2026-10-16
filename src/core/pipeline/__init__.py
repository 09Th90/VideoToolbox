# -*- coding: utf-8 -*-
# @version 2.3.1
"""流水线域：入口编排（main）+ SRT 工具链（时间轴换算 / 滚动字幕稳定化）。

任务级流水线主体在 ``pipeline.py``（目录感知 + 阶段调度）；本域收单体里
残存的编排入口与 SRT 后处理工具。施工清单（拆分完成时 __all__ 须覆盖）：

main, srt_time_to_ms, ms_to_srt_time, normalize_rolling_srt
"""

__all__ = []
