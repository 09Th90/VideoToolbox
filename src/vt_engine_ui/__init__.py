# -*- coding: utf-8 -*-
# @version 2.5.3
"""自研字幕引擎工作台 UI 视觉层（P3 / 档 C）。

本包以**自研代码**重建视频工具箱内嵌的字幕工作台界面，视觉与交互与既有引擎界面
逐像素对齐；原先散落在 ``video_toolbox*.py`` 里的 36 处运行期 monkey-patch 中，
所有**UI 视觉/交互类**补丁都已内建为本包各页的显式逻辑（品牌中性化、下拉收敛、
声纹录入/多选/筛选、陈旧状态自愈、独立转录回填、任务创建收字幕、按类型分派等）。

设计要点：
  · **零 ``videocaptioner.ui`` 依赖**——各页只通过 :mod:`._seams` 访问后端
    （配置 / 任务工厂 / 线程 / 核心数据模型），后者属档 A/B（P1~P2）范畴；
    P2 完成后仅需改 ``_seams`` 取值来源，本包各页无需改动。
  · qfluentwidgets / PySide6 为**保留组件**（见 docs 许可声明），本包只用它们搭界面，
    不改写其实现。
  · 所有构造均**独立容错**：单个可选能力（声纹卡、vlc 预览）缺失不影响整页构建。

公开入口（供宿主 ``video_toolbox_qt.py`` 导入）：
  · :class:`HomeInterface`    —— 内嵌工作台首页（分段 + 堆叠页）
  · :class:`SettingInterface` —— 内嵌设置页（滚动区）
"""
from __future__ import annotations

__all__ = [
    "HomeInterface",
    "SettingInterface",
    "TaskCreationInterface",
    "TranscriptionInterface",
    "SubtitleInterface",
    "VideoSynthesisInterface",
    "MyVideoWidget",
    "TranscriptionSettingCard",
    "TranscriptionSettingDialog",
    "SubtitleSettingDialog",
    "self_ui_available",
    "self_ui_error",
]

_ERR = None


def _import_all():
    from .home_interface import HomeInterface
    from .setting_interface import SettingInterface
    from .task_creation_interface import TaskCreationInterface
    from .transcription_interface import TranscriptionInterface
    from .subtitle_interface import SubtitleInterface
    from .video_synthesis_interface import VideoSynthesisInterface
    from .components import TranscriptionSettingCard, TranscriptionSettingDialog
    from .subtitle_setting_dialog import SubtitleSettingDialog
    from .my_video_widget import MyVideoWidget
    return (HomeInterface, SettingInterface, TaskCreationInterface,
            TranscriptionInterface, SubtitleInterface, VideoSynthesisInterface,
            TranscriptionSettingCard, TranscriptionSettingDialog,
            SubtitleSettingDialog, MyVideoWidget)


def self_ui_available() -> bool:
    """自研 UI 是否可导入（不实例化，仅静态可用性）——供宿主选择/兜底。"""
    global _ERR
    try:
        _import_all()
        from . import _seams
        ok = _seams.backend_available()
        if not ok:
            _ERR = _seams.backend_error()
        return ok
    except Exception as e:  # noqa: BLE001
        _ERR = f"{type(e).__name__}: {e}"
        return False


def self_ui_error():
    return _ERR


# 便捷直接导入（失败时不阻断包导入，由 self_ui_available() 报告原因）
try:  # pragma: no cover
    (HomeInterface, SettingInterface, TaskCreationInterface, TranscriptionInterface,
     SubtitleInterface, VideoSynthesisInterface, TranscriptionSettingCard,
     TranscriptionSettingDialog, SubtitleSettingDialog, MyVideoWidget) = _import_all()
except Exception as _e:  # noqa: BLE001
    _ERR = f"{type(_e).__name__}: {_e}"
