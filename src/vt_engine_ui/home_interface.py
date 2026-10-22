# -*- coding: utf-8 -*-
# @version 2.5.4
"""自研工作台首页（分段控件 + 堆叠页组合）。

忠实复现引擎 ``HomeInterface`` 的组合结构与信号连线（``pivot`` / ``stackedWidget``
/ 四个子界面 / ``switch_to_*`` / ``addSubInterface`` / ``onCurrentIndexChanged`` /
``closeEvent``），并把补丁 ⑧ 内建为显式逻辑：

  ⑧ 走「任务创建 → 语音转录 → 字幕翻译」这条链时（``need_next_task=True``，
     引擎只在此路 emit ``finished``），若启用了主播声纹，先后台筛选再切换到字幕
     翻译——否则用户选择的声纹筛选在这条路径上不生效（2026-10-09 实测缺陷）。

宿主 ``_build_engine`` 随后做的实例级整形（摘除合成页、改名「字幕翻译」、并入
「字幕校准」分段、按类型分派任务创建、隐藏品牌入口等）保持不变，作用在同名同构
的对象上，最终 GUI 与替换前一致。
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QSizePolicy, QStackedWidget, QVBoxLayout, QWidget
from vt_fluent import InfoBar, InfoBarPosition, SegmentedWidget

from . import _seams
from .subtitle_interface import SubtitleInterface
from .task_creation_interface import TaskCreationInterface
from .transcription_interface import TranscriptionInterface
from .video_synthesis_interface import VideoSynthesisInterface


class HomeInterface(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_task_id: Optional[str] = None

        self.setObjectName("HomeInterface")
        self.setStyleSheet("HomeInterface{background: white}")

        self.pivot = SegmentedWidget(self)
        self.pivot.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.stackedWidget = QStackedWidget(self)
        self.vBoxLayout = QVBoxLayout(self)

        self.task_creation_interface = TaskCreationInterface(self)
        self.transcription_interface = TranscriptionInterface(self)
        self.subtitle_optimization_interface = SubtitleInterface(self)
        self.video_synthesis_interface = VideoSynthesisInterface(self)

        self.addSubInterface(self.task_creation_interface, "TaskCreationInterface", self.tr("任务创建"))
        self.addSubInterface(self.transcription_interface, "TranscriptionInterface", self.tr("语音转录"))
        self.addSubInterface(self.subtitle_optimization_interface, "SubtitleInterface", self.tr("字幕优化与翻译"))
        # v2.1.0：「字幕视频合成」**不再注册进分段/堆叠**。合成能力已并入
        # 「字幕编辑」页（工具条「内嵌字幕」入口），这里保留实例只是为了让
        # 宿主与 closeEvent 的对象清单不变——它从未被 addSubInterface，
        # 因此任何路径都不会把用户带到一个已废弃的分段上。
        self.video_synthesis_interface.setParent(None)
        self.video_synthesis_interface.hide()

        self.vBoxLayout.addWidget(self.pivot)
        self.vBoxLayout.addWidget(self.stackedWidget)
        self.vBoxLayout.setContentsMargins(30, 10, 30, 30)

        self.stackedWidget.currentChanged.connect(self.onCurrentIndexChanged)
        self.stackedWidget.setCurrentWidget(self.task_creation_interface)
        self.pivot.setCurrentItem("TaskCreationInterface")

        self.task_creation_interface.finished.connect(self.switch_to_transcription)
        self.transcription_interface.finished.connect(self.switch_to_subtitle_optimization)
        # v2.1.0：不再把「字幕翻译完成」连到合成页（合成页已废弃，见上）。
        # 字幕翻译完成后停在翻译页，由用户自行决定下一步。

    def switch_to_transcription(self, file_path):
        self._current_task_id = _seams.generate_task_id()
        transcribe_task = _seams.TaskFactory.create_transcribe_task(
            file_path, need_next_task=True, task_id=self._current_task_id)
        self.transcription_interface.set_task(transcribe_task)
        self.transcription_interface.process()
        self.stackedWidget.setCurrentWidget(self.transcription_interface)
        self.pivot.setCurrentItem("TranscriptionInterface")

    def switch_to_subtitle_optimization(self, file_path, video_path):
        # 补丁 ⑧（内建）：任务创建路径的声纹筛选，筛完再切换
        if _seams.voiceprint_enabled_names() and self._start_voiceprint_filter(
                file_path, video_path,
                lambda: self._do_switch_to_subtitle(file_path, video_path)):
            return
        self._do_switch_to_subtitle(file_path, video_path)

    def _do_switch_to_subtitle(self, file_path, video_path):
        subtitle_task = _seams.TaskFactory.create_subtitle_task(
            file_path, video_path, need_next_task=True, task_id=self._current_task_id)
        self.subtitle_optimization_interface.set_task(subtitle_task)
        self.subtitle_optimization_interface.process()
        self.stackedWidget.setCurrentWidget(self.subtitle_optimization_interface)
        self.pivot.setCurrentItem("SubtitleInterface")

    def _start_voiceprint_filter(self, out, media, then) -> bool:
        """后台声纹筛选，完成后回调 then()；返回是否已接管流程。"""
        try:
            parent = self.window() or self
            bar = InfoBar.info("正在按声纹筛选", "只保留主播台词，请稍候（长片约需半分钟）…",
                               duration=-1, position=InfoBarPosition.BOTTOM, parent=parent)
        except Exception:  # noqa: BLE001
            parent = self
            bar = None

        class _VpWorker(QThread):
            done = Signal(object)

            def run(self):
                try:
                    r = _seams.voiceprint_filter_subtitle(out, media)
                except Exception as e:  # noqa: BLE001
                    _seams.vc_log(f"声纹筛选失败：{e}")
                    r = {"error": str(e)}
                self.done.emit(r)

        def _finish(res):
            try:
                if bar is not None:
                    bar.close()
            except Exception:  # noqa: BLE001
                pass
            try:
                import os
                if isinstance(res, dict) and res.get("error"):
                    InfoBar.error("声纹筛选失败", str(res["error"])[:200] + "\n字幕已保留未筛选版本",
                                  duration=9000, position=InfoBarPosition.BOTTOM, parent=parent)
                elif res is None:
                    InfoBar.warning("声纹筛选未执行",
                                    "声纹模型还没下载：到「语音转录 → 主播声纹」点「下载模型」",
                                    duration=8000, position=InfoBarPosition.BOTTOM, parent=parent)
                else:
                    InfoBar.success(
                        "声纹筛选完成",
                        "保留 %d 条（其中存疑 %d）/ 丢弃 %d；原件已备份为「%s」"
                        % (res["kept_total"], res["review"], res["drop"],
                           os.path.basename(res.get("backup") or "")),
                        duration=9000, position=InfoBarPosition.BOTTOM, parent=parent)
            except Exception:  # noqa: BLE001
                pass
            try:
                then()
            except Exception as e:  # noqa: BLE001
                _seams.vc_log(f"声纹筛选后切换异常：{e}")

        try:
            w = _VpWorker()
            w.done.connect(_finish)
            self._vt_vp_worker = w   # 防 GC
            w.start()
            return True
        except Exception as e:  # noqa: BLE001
            _seams.vc_log(f"声纹筛选线程启动失败：{e}")
            return False

    def switch_to_video_synthesis(self, video_path, subtitle_path):
        """v2.1.0 起为**永久 no-op**。

        「字幕视频合成」分段已从分段控件与堆叠页里彻底摘除（合成能力并入
        「字幕编辑」页的「内嵌字幕」入口）。保留这个方法只为兼容宿主与旧
        代码里可能残留的调用——**任何实现都会把用户带到一个已经不存在
        的页面上**，故直接返回，不做任何切换。
        """
        self._current_task_id = None
        return

    def addSubInterface(self, widget, objectName, text):
        widget.setObjectName(objectName)
        self.stackedWidget.addWidget(widget)
        self.pivot.addItem(routeKey=objectName, text=text,
                           onClick=lambda: self.stackedWidget.setCurrentWidget(widget))

    def onCurrentIndexChanged(self, index):
        widget = self.stackedWidget.widget(index)
        if widget:
            self.pivot.setCurrentItem(widget.objectName())

    def closeEvent(self, event):
        # ⚠ 任务创建页可能已被宿主摘走挂到「首页」（见
        # ``video_toolbox_qt.HomePage.adopt``）。此时它不再是本页的子控件，
        # 这里再 close() 会把首页上的那个控件一起关掉——表现为"程序关到一半
        # 首页内容凭空消失"。故逐个检查父对象，只关仍属于本页的。
        for w in (self.task_creation_interface,
                  self.transcription_interface,
                  self.subtitle_optimization_interface,
                  self.video_synthesis_interface):
            try:
                if w is not None and w.parent() is self:
                    w.close()
            except Exception:  # noqa: BLE001
                pass
        super().closeEvent(event)
