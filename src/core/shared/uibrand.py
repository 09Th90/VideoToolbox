# -*- coding: utf-8 -*-
# @version 2.4.1
"""引擎 UI 品牌补丁（用户可见文案中性化 / 水印与捐助入口隐藏）（v2.3.1 拆分工程 · 自 video_toolbox.py 原样搬入）。

v2.3.1 拆分工程；域间依赖规则见 core/__init__.py。
"""
import os

def engine_ui_brand_patch():
    """对内嵌引擎的用户可见文案与布局做中性化补丁（幂等，仅改运行时行为）。

    · 视频预览弹窗标题/图标跟随宿主，去除上游品牌；
    · 任务创建页隐藏品牌 logo、收紧独立窗口时代的大留白。
    各部分独立容错：某一模块导入失败（如缺 vlc）不影响其余补丁生效。
    第三方组件的许可全文与来源声明见 docs 目录下两个声明文件（必须保留）。
    """
    # 视频预览弹窗补丁为 best-effort：缺可选依赖 vlc 时跳过，不算失败
    try:
        from videocaptioner.ui.components.MyVideoWidget import MyVideoWidget
    except Exception:
        MyVideoWidget = None
    if MyVideoWidget is not None:
        _patch_video_widget(MyVideoWidget)
    # 任务创建页补丁是内嵌界面真正依赖的（隐藏 logo/水印、收紧留白）
    try:
        from videocaptioner.ui.view.task_creation_interface import (
            TaskCreationInterface)
    except Exception:
        return False
    _patch_task_creation(TaskCreationInterface)
    return True


def _patch_video_widget(MyVideoWidget):
    """视频预览弹窗：标题与图标跟随宿主。"""
    if getattr(MyVideoWidget, "_vt_patched", False):
        return

    orig_init = MyVideoWidget.__init__

    def _init(self, parent=None):
        orig_init(self, parent)
        # 视频预览弹出窗口：标题与图标跟随宿主，去除上游品牌
        self.setWindowTitle("视频预览")
        try:
            from PySide6.QtWidgets import QApplication
            icon = QApplication.windowIcon()
            if not icon.isNull():
                self.setWindowIcon(icon)
        except Exception:
            pass

    MyVideoWidget.__init__ = _init
    MyVideoWidget._vt_patched = True


def _patch_task_creation(TaskCreationInterface):
    """任务创建页：隐藏品牌 logo、收紧独立窗口时代的大留白。"""
    if getattr(TaskCreationInterface, "_vt_layout_patched", False):
        return

    orig_setup = TaskCreationInterface.setup_ui

    def _setup(self):
        orig_setup(self)
        logo = getattr(self, "logo_label", None)
        if logo is not None:
            logo.hide()
        lay = getattr(self, "main_layout", None)
        if lay is not None:
            for i in reversed(range(lay.count())):
                item = lay.itemAt(i)
                spacer = item.spacerItem() if item is not None else None
                if spacer is not None and spacer.sizeHint().height() >= 100:
                    lay.removeItem(item)
            lay.setSpacing(18)
            lay.insertSpacing(0, 24)

    TaskCreationInterface.setup_ui = _setup
    TaskCreationInterface._vt_layout_patched = True
# =============================




# ========== AI 校准（Agent 级）入口 ==========
# 界面开启「AI 校准」后点「开始校准」，等价于向 Agent 下达：基于脚本
# subtitle_calib_merged 校准字幕，不改变时间轴与格式，仅调整文字内容，
# 一次读不完就自行拆分，最后合并。实现见 src\calib_ai_agent.py。






__all__ = [
    "engine_ui_brand_patch",
]
