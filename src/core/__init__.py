# -*- coding: utf-8 -*-
# @version 2.5.4
"""视频工具箱 · 核心域包（v2.3.1 拆分工程）。

``video_toolbox.py``（9221 行单体）按域拆入本包的子包，原文件退化为
facade（显式再导出层）。施工图与接口契约见
``scripts/dev/_selftest_core_api.py`` 的 DOMAIN_MAP；方案见
``docs/核心拆分与QSS主题迁移方案.md``。

依赖规则（负向桩：本包禁止 import Qt/qfluentwidgets）：
  · ``shared`` 不依赖任何域；
  · ``download`` / ``asr`` / ``translate`` / ``calibrate`` 只准依赖 ``shared``；
  · ``pipeline`` 可依赖全部（编排层）；
  · 域间横向依赖一律经 ``shared`` 或由 ``pipeline`` 组装。
"""
