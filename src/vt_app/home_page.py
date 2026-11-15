# -*- coding: utf-8 -*-
# @version 3.0.0
"""首页（2026-11-15 功能解耦阶段③：从 video_toolbox_qt.py 拆出，逐字同源）。

壳层页面：程序入口（原「字幕处理」工作台里的「任务创建」分段）。
TaskCreationInterface 单件直载 + adopt 认领，行为与旧实现完全一致。
"""
import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QVBoxLayout, QWidget

from vt_fluent import BodyLabel

from vt_app.boot import _perf_note, _process_age_seconds
from vt_app.scheduler import _SCHED, _defer
from vt_app.widgets import fit_caption


class HomePage(QWidget):
    """首页：程序入口（原「字幕处理」工作台里的「任务创建」分段）。

    v2.1.0：用户要求把「任务创建」提升为**应用首页**——它是整个工具箱的
    起点（拖文件、粘链接），却原先藏在「字幕处理」页的第二个分段里，
    要先点进字幕处理才看得见。

    这里**不是新建一个长得像的页面**，而是把工作台里那一个
    ``TaskCreationInterface`` 实例原样搬过来（见 :meth:`adopt`），
    因此拖放、字幕接收、链接跳转、按类型分派等行为全部是同一份代码，
    不存在两处实现漂移。搬走后工作台分段变成「语音转录 / 字幕翻译 /
    字幕校准」——任务创建完成后的后续流程仍在那里进行。

    引擎界面是懒加载的（后台预热 + 首次显示时构建），所以构造时先占位，
    控件就绪后由 :meth:`adopt` 换上真身。
    """

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setObjectName("HomePage")
        self.setAcceptDrops(True)
        self._task_creation = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.vbox = outer

        # 占位：引擎工作台还没构建好（预热中 / 构建失败）时显示这一行
        self.host = QWidget(self)
        self.host_lay = QVBoxLayout(self.host)
        self.host_lay.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.host, 1)
        self.state_label = fit_caption(
            BodyLabel("正在准备任务创建界面 …", self.host))
        self.state_label.setAlignment(Qt.AlignCenter)
        self.state_label.setStyleSheet("font-size: 14px; color: #888888;")
        self.host_lay.addWidget(self.state_label)
        # 首帧后立刻用“任务创建页单件”替换占位，不再等工作台整树预热。
        # 必须先于 MainWindow 的 prewarm_kick 注册（依赖名缺失会被当成
        # 未阻塞而提前开跑）。
        _defer("home_ui", self.ensure_task_creation, 0, 0, budget_ms=600)

    # ---------- 启动专项：预热前先给出可用的任务创建框 ----------
    def ensure_task_creation(self):
        """直接构造 TaskCreationInterface，不等 HomeInterface/引擎预热。

        首页只需要这一个控件；以前要等整个工作台（4 个子界面 + videocaptioner
        配置链）建完才 adopt，实测 6～18s。这里走 ``task_creation_interface``
        子模块直载，不触碰 ``home_interface``/transcription/subtitle。
        失败/强制引擎 UI 时退回旧的 ensure_built 路径。
        """
        if self._task_creation is not None:
            return True
        mode = (os.environ.get("VT_ENGINE_UI", "self") or "self").strip().lower()
        if mode == "engine":
            try:
                self.app.subtitle_page.ensure_built()
            except Exception:  # noqa: BLE001
                pass
            return True
        try:
            from vt_engine_ui.task_creation_interface import TaskCreationInterface
            tc = TaskCreationInterface(self.host)
            self.app.subtitle_page.wire_task_creation(
                tc, lambda: getattr(self.app.subtitle_page, "_engine_home", None))
            lay = self.host_lay
            while lay.count():
                item = lay.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.setParent(None)
            tc.setParent(self.host)
            lay.addWidget(tc)
            tc.show()
            self._task_creation = tc
            self.state_label = None
            QTimer.singleShot(0, self._log_home_ready)
            return True
        except Exception as e:  # noqa: BLE001
            _perf_note(f"首页直载任务创建页失败，回退旧路径：{e}")
            try:
                self.app.subtitle_page.ensure_built()
            except Exception:  # noqa: BLE001
                pass
            return True

    def _log_home_ready(self):
        age = _process_age_seconds()
        if age is None:
            _perf_note("[HOME] 首页任务创建控件已就绪")
        else:
            _perf_note(f"[HOME] 首页任务创建可交互（进程启动后 {age:.3f}s）")

    # ---------- 装载真正的任务创建控件 ----------
    def adopt(self, home, widget=None):
        """把工作台的 ``TaskCreationInterface`` 搬进首页（只搬一次）。

        v2.1.0：分段摘除已**前移到工作台构建时**（``_build_engine``，结构性
        保证工作台绝无此分段）；本方法只负责**认领**这个孤儿控件——setParent
        挂到首页 + show。下面的 removeWidget 保留为幂等兜底（key 已不在
        items 时是 no-op），万一调用顺序颠倒也不会出现"一个控件被两个父
        容器持有"。
        """
        if widget is None:
            widget = getattr(home, "task_creation_interface", None)
        if widget is None or self._task_creation is not None:
            return
        try:
            self.app.subtitle_page.wire_task_creation(widget, lambda: home)
            try:
                home.pivot.removeWidget("TaskCreationInterface")
            except Exception:  # noqa: BLE001
                pass
            try:
                home.stackedWidget.removeWidget(widget)
            except Exception:  # noqa: BLE001
                pass
            lay = self.host_lay
            while lay.count():
                item = lay.takeAt(0)
                w = item.widget()
                if w is not None:
                    w.setParent(None)
            widget.setParent(self.host)
            lay.addWidget(widget)
            # ⚠ 必须显式 show：``QStackedWidget.removeWidget`` 会顺手把控件
            # **hide()** 掉（它只管"移出当前显示"，不管搬去哪儿）。忘了这一句
            # 的症状极隐蔽——探针各项断言全过（对象在、isAncestorOf 为真），
            # 可首页就是一片空白：父容器是 visible 的，控件自己 hidden，
            # 于是没有一次 paint 被派发。只能在真机截图里看出来。
            widget.show()
            self._task_creation = widget
            self.state_label = None
            # 摘掉首段后工作台的当前分段可能悬空，显式落到一个存在的分段上
            try:
                if home.stackedWidget.count():
                    first = home.stackedWidget.widget(0)
                    home.stackedWidget.setCurrentWidget(first)
                    home.pivot.setCurrentItem(first.objectName())
            except Exception:  # noqa: BLE001
                pass
        except Exception as e:  # noqa: BLE001
            _perf_note(f"首页装载任务创建页失败：{e}")

    @property
    def task_creation(self):
        """已装载的任务创建控件；未就绪时为 ``None``。"""
        return self._task_creation

    def showEvent(self, event):
        """首次显示时优先把任务创建框装上；不再同步触发整树预热。"""
        super().showEvent(event)
        _perf_note("HomePage.showEvent 首次显示")
        if self._task_creation is not None:
            return
        s = _SCHED["inst"]
        if s is not None and s.run_now("home_ui", 0):
            return
        QTimer.singleShot(0, self.ensure_task_creation)

    def dragEnterEvent(self, event):
        # 首页由「任务创建」控件本体收拖放（它 setAcceptDrops(True)）；
        # 这里只保证空白处拖入时事件不被吞掉，交给主窗口的全局分派。
        try:
            if event.mimeData().hasUrls():
                event.acceptProposedAction()
            else:
                event.ignore()
        except Exception:  # noqa: BLE001
            event.ignore()