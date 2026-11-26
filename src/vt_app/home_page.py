# -*- coding: utf-8 -*-
# @version 3.3.1
"""首页（2026-11-15 功能解耦阶段③：从 video_toolbox_qt.py 拆出，逐字同源）。

壳层页面：程序入口（原「字幕处理」工作台里的「任务创建」分段）。
TaskCreationInterface 单件直载 + adopt 认领，行为与旧实现完全一致。
"""
import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout,
                               QWidget)

from vt_fluent import (BodyLabel, CaptionLabel, FluentIcon as FIF, PushButton,
                       StrongBodyLabel)

from vt_app.boot import _perf_note, _process_age_seconds
from vt_app.scheduler import _SCHED, _defer
from vt_app.widgets import card, fit_caption
import ui_theme


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
        outer.setContentsMargins(22, 16, 22, 14)
        outer.setSpacing(10)
        self.vbox = outer

        # 页头：标题 + 说明 + 右侧单任务标记
        head = QWidget(self)
        head.setFixedHeight(58)
        hl = QHBoxLayout(head)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(10)
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        self.title = QLabel("任务创建", head)
        self.title.setObjectName("HomeTitle")
        self.subtitle = QLabel(
            "一个输入框承接链接、文件路径或一句话；不预置任务列表与虚构队列",
            head)
        self.subtitle.setObjectName("HomeSub")
        col.addWidget(self.title)
        col.addWidget(self.subtitle)
        hl.addLayout(col, 1)
        self.single_badge = QLabel("单任务入口", head)
        self.single_badge.setObjectName("HomeBadge")
        self.single_badge.setAlignment(Qt.AlignCenter)
        hl.addWidget(self.single_badge, 0, Qt.AlignVCenter)
        outer.addWidget(head)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(10)
        self.vbox.addLayout(body, 0)

        # 左：任务创建卡（里面仍是 TaskCreationInterface 本体）
        left_box, left_lay = card()
        self.task_card = left_box
        left_box.setMaximumHeight(360)
        left_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        left_lay.setContentsMargins(16, 14, 16, 12)
        left_lay.setSpacing(10)
        hero = QLabel("把链接、文件或一句话交给我", left_box)
        hero.setObjectName("HomeHero")
        hint = QLabel("输入框内有内容时按钮变为开始处理；为空时保持文件入口。",
                      left_box)
        hint.setObjectName("HomeHint")
        left_lay.addWidget(hero)
        left_lay.addWidget(hint)
        chips = QLabel("MP4  MKV  MOV  MP3  SRT    ·    整段分享文案自动识别    ·    支持拖放",
                       left_box)
        chips.setObjectName("HomeChips")
        left_lay.addWidget(chips)
        self.host = QWidget(left_box)
        self.host.setMinimumHeight(240)
        self.host_lay = QVBoxLayout(self.host)
        self.host_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.addWidget(self.host, 1)
        body.addWidget(left_box, 1, Qt.AlignTop)

        # 右：输入后会发生什么（只描述真实分派，不伪造统计）
        right_box, rlay = card()
        self.route_card = right_box
        right_box.setFixedWidth(292)
        right_box.setMaximumHeight(360)
        right_box.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Maximum)
        title = StrongBodyLabel("输入后会发生什么", right_box)
        title.setObjectName("HomeRouteTitle")
        cap = CaptionLabel("按内容类型分派 · 不在这里展开队列", right_box)
        cap.setObjectName("HomeRouteCap")
        rlay.addWidget(title)
        rlay.addWidget(cap)
        self._route_rows = []
        for num, t, d in (
                ("1", "视频链接", "分派到视频处理 / 下载，先检查画质"),
                ("2", "本地视频 / 音频", "分派到字幕处理 / 语音转录"),
                ("3", "SRT 字幕", "分派到字幕编辑；不在本页翻译或校准"),
                ("4", "一句话指令", "交给 AI 托管；在 AI 托管页执行")):
            rlay.addWidget(self._route_row(num, t, d, right_box))
        note = CaptionLabel(
            "任务创建页不提供批量队列、运行环境或统计；那些属于流水线、"
            "设置与视频库。", right_box)
        note.setObjectName("HomeNote")
        note.setWordWrap(True)
        rlay.addWidget(note)
        rlay.addStretch(1)
        body.addWidget(right_box, 0, Qt.AlignTop)

        # 底部：真实导航快捷入口，不伪造任务/统计，只把「下一步去哪」摆出来。
        quick, qlay = card()
        quick.setMaximumHeight(104)
        qlay.setContentsMargins(16, 10, 16, 10)
        qlay.setSpacing(8)
        qtitle = StrongBodyLabel("常用入口", quick)
        qtitle.setObjectName("HomeQuickTitle")
        qcap = CaptionLabel(
            "首页只创建单个任务；批量队列、运行状态与历史都在对应页",
            quick)
        qcap.setObjectName("HomeQuickCap")
        qlay.addWidget(qtitle)
        qlay.addWidget(qcap)
        qrow = QHBoxLayout()
        qrow.setContentsMargins(0, 0, 0, 0)
        qrow.setSpacing(8)
        for icon, text, attr in (
                (FIF.DOWNLOAD, "视频下载", "download_page"),
                (FIF.FONT, "字幕处理", "subtitle_page"),
                (FIF.PLAY, "流水线", "pipeline_page"),
                (FIF.MOVIE, "视频库", "library_page")):
            b = PushButton(icon, text, quick)
            b.clicked.connect(
                lambda _=False, a=attr: self._go(a))
            qrow.addWidget(b, 1)
        qlay.addLayout(qrow)
        outer.addWidget(quick, 0)
        outer.addStretch(1)

        # 占位：引擎工作台还没构建好（预热中 / 构建失败）时显示这一行
        self.state_label = fit_caption(
            BodyLabel("正在准备任务创建界面 …", self.host))
        self.state_label.setAlignment(Qt.AlignCenter)
        self.state_label.setStyleSheet("font-size: 13px; color: #888888;")
        self.host_lay.addWidget(self.state_label)
        # 首帧后立刻用“任务创建页单件”替换占位，不再等工作台整树预热。
        # 必须先于 MainWindow 的 prewarm_kick 注册（依赖名缺失会被当成
        # 未阻塞而提前开跑）。
        _defer("home_ui", self.ensure_task_creation, 0, 0, budget_ms=600)
        self._apply_theme()
        ui_theme.connect_theme(self, lambda w: w._apply_theme())

    def _route_row(self, num, title, desc, parent):
        row_w = QWidget(parent)
        lay = QHBoxLayout(row_w)
        lay.setContentsMargins(0, 5, 0, 5)
        lay.setSpacing(9)
        badge = QLabel(num, row_w)
        badge.setFixedSize(20, 20)
        badge.setAlignment(Qt.AlignCenter)
        badge.setObjectName("HomeRouteNum")
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(1)
        t = QLabel(title, row_w)
        t.setObjectName("HomeRouteRowTitle")
        d = QLabel(desc, row_w)
        d.setObjectName("HomeRouteRowDesc")
        col.addWidget(t)
        col.addWidget(d)
        lay.addWidget(badge, 0, Qt.AlignTop)
        lay.addLayout(col, 1)
        return row_w

    def _go(self, attr):
        """首页快捷入口：切到真实页面，不新建窗口/不改任务状态。"""
        page = getattr(self.app, attr, None)
        if page is None:
            return
        try:
            self.app.switchTo(page)
        except Exception:  # noqa: BLE001
            pass

    def _style_task_input(self, tc):
        if not hasattr(tc, "_v3_input_base"):
            tc._v3_input_base = tc.search_input.styleSheet()
        t = ui_theme.tokens()
        tc.search_input.setStyleSheet(
            tc._v3_input_base
            + "QLineEdit{border-radius:10px;padding:0 14px;"
              "background:%s;border:1px solid %s;color:%s;}"
              "QLineEdit:focus{border:1px solid %s;background:%s;}"
              % (t["input_bg"], t["card_border"], t["text"],
                 ui_theme.get_accent(), t["input_bg_focus"]))

    def _apply_theme(self):
        t = ui_theme.tokens()
        a = QColor(ui_theme.get_accent())
        self.setStyleSheet(
            "QLabel#HomeTitle{font-size:20px;font-weight:600;color:%(text)s;"
            "background:transparent;}"
            "QLabel#HomeSub,QLabel#HomeHint,QLabel#HomeNote,"
            "QLabel#HomeRouteCap,QLabel#HomeRouteRowDesc{font-size:10px;"
            "color:%(dim)s;background:transparent;}"
            "QLabel#HomeBadge{font-size:10px;color:%(dim)s;background:%(hover)s;"
            "border:1px solid %(border)s;border-radius:10px;padding:2px 10px;}"
            "QLabel#HomeHero{font-size:13.5px;font-weight:600;color:%(text)s;"
            "background:transparent;}"
            "QLabel#HomeChips{font-size:10px;color:%(dim)s;background:transparent;}"
            "QLabel#HomeRouteTitle{font-size:13px;font-weight:600;color:%(text)s;"
            "background:transparent;}"
            "QLabel#HomeRouteRowTitle{font-size:11px;font-weight:600;color:%(text)s;"
            "background:transparent;}"
            "QLabel#HomeQuickTitle{font-size:11px;font-weight:600;color:%(text)s;"
            "background:transparent;}"
            "QLabel#HomeQuickCap{font-size:9.5px;color:%(dim)s;"
            "background:transparent;}"
            "QLabel#HomeRouteNum{font-size:10px;font-weight:600;color:%(accent)s;"
            "background:rgba(%(r)d,%(g)d,%(b)d,0.12);border-radius:10px;}"
            % dict(t, accent=ui_theme.get_accent(), r=a.red(), g=a.green(),
                   b=a.blue(), dim=t["text_dim"], hover=t["card_hover"],
                   border=t["card_border"]))

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
            # v3 首页：把引擎任务页收进卡片内，去掉独立窗口时代的 80px 边距和
            # 品牌版权行；拖放、链接识别、文件选择仍走它自己的实现。
            try:
                tc.setStyleSheet(
                    "QWidget#TaskCreationInterface{background:transparent;}")
                tc.main_layout.setContentsMargins(0, 0, 0, 0)
                tc.main_layout.setSpacing(12)
                tc.search_layout.setContentsMargins(0, 0, 0, 0)
                tc.status_layout.setContentsMargins(0, 0, 0, 0)
                for i in reversed(range(tc.main_layout.count())):
                    it = tc.main_layout.itemAt(i)
                    sp = it.spacerItem() if it is not None else None
                    if sp is not None and sp.sizeHint().height() <= 30:
                        tc.main_layout.removeItem(it)
                tc.search_input.setFixedHeight(42)
                self._style_task_input(tc)
                ui_theme.connect_theme(
                    tc.search_input, lambda w, t=tc: self._style_task_input(t))
                tc.info_label.hide()
                tc.donate_button.hide()
                tc.status_label.setText("空闲 · 等待输入")
                tc.status_label.setStyleSheet(
                    "font-size:11px;color:#8a9097;background:transparent;")
                tc.status_label.show()
            except Exception:  # noqa: BLE001
                pass
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