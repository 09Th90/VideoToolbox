# -*- coding: utf-8 -*-
"""主窗口（2026-11-15 功能解耦阶段③：从 video_toolbox_qt.py 拆出，逐字同源）。

壳层编排：FluentWindow + 注册表驱动的功能页挂载 + 消息总线 + 跨屏收敛 +
全局拖放分派 + 流水线装配。功能页一律经 features 注册表 GuiSpec 挂载，
壳层不 import 具体功能实现（harness/自动化页经既有外部模块惰性构造）。

阶段③收尾：旧 _dispatch 路由表整体删除——业务消息已由功能页/设置页 bus
自订阅，壳层编排消息 pipe_ready 改由本窗口 bus 订阅。
"""
import os
import queue
import sys
import threading
import time
import traceback
from datetime import datetime

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QApplication, QSizePolicy, QVBoxLayout, QWidget)

from vt_fluent import (BodyLabel, FluentIcon as FIF, FluentWindow, InfoBar,
                       InfoBarPosition, NavigationItemPosition)

import video_toolbox as engine
import ui_theme
import features.library.media_registry as mreg
import features.pipeline.pipeline as pl

from features import registry as _registry_fn, resolve as _feature_resolve
from features._media import AUDIO_EXTS, SUBTITLE_EXTS, VIDEO_EXTS

from vt_app.boot import _perf_note
from vt_app.scheduler import _SCHED, _defer
from vt_app.engine_ui import _engine_prewarm_done
from vt_app.lazy_shell import _LazyPageShell, _lazy_real
from vt_app.win_resize import RESIZE_MARGIN, _ResizeHitFilter
from vt_app.bus import MessageBus
from vt_app.widgets import nav_width_for
from vt_app.home_page import HomePage
from vt_app.settings_page import SettingsPage

# AI 托管（v2.1.0）：harness 适配层 + 托管页。两者都设计成「harness 不在场
# 也零影响」——bridge 只依赖标准库、探测失败只返回状态；页面也只在
# ``harness_bridge.available()`` 为真时才创建并挂导航。import 本身依旧兜底，
# 确保任何意外都不会拖垮既有功能。
try:
    import features.harness.harness_bridge as harness_bridge
    import features.harness.harness_page as _harness_page_mod
    _HARNESS_IMPORT_OK = True
except Exception as _e:  # noqa: BLE001
    harness_bridge = None
    _harness_page_mod = None
    _HARNESS_IMPORT_OK = False
    try:
        _perf_note(f"harness 模块导入失败（不影响既有功能）：{_e}")
    except Exception:  # noqa: BLE001
        pass


def _load_auto_vision_page():
    """惰性导入 auto_vision_page，返回其页面类（重依赖只在这里付一次）。"""
    import features.automation.auto_vision_page as auto_vision_page
    return auto_vision_page.AutoVisionPage


def _version():
    """版本号单一来源在入口 video_toolbox_qt.py（apply_version 锚点），懒导入避循环。"""
    from video_toolbox_qt import VERSION  # noqa: PLC0415
    return VERSION


# ========== 主窗口 ==========
# v1.13.x：页面合并后共 5 个导航页（音画合并并入视频处理、字幕校准并入字幕处理）。
# 内嵌子板块仍有自己的 objectName（MergePage / CalibPage），保留映射便于标题定位。
# 类名/objectName 一律保持 DownloadPage 不变，避免牵动既有样式与自检。
PAGE_TITLES = {"HomePage": "首页", "DownloadPage": "视频处理", "LibraryPage": "视频库",
               "SubtitlePage": "字幕处理", "SubtitleEditPage": "字幕编辑",
               "AutoVisionPage": "自动化", "HarnessPage": "AI 托管",
               "SettingsPage": "设置",
               "MergePage": "音画合并", "CalibPage": "字幕校准"}

#: 黄金比例（宽 : 高）。窗口默认尺寸与「按屏幕收敛」后的尺寸都按它算——
#: 比 1.38 的默认值更接近主流视频区（16:10 / 16:9）留白后的观感。
GOLDEN_RATIO = 1.6180339887


class MainWindow(FluentWindow):
    """FluentWindow + 左侧导航（结构与主流 Fluent 桌面应用一致）。

    v1.10.4 起：
      · 导航宽度按最长项文字自适应（最长文字 + 2 个字符），不再固定 322px；
      · 设置页统一挂在导航底部，字幕引擎设置并入其中；
      · 跨屏拖拽保持相对位置，不再因两屏缩放比不同而瞬移；
      · 字幕引擎界面后台预热，消除首次进入本页的数秒卡顿。
    v1.13.0 起：
      · 页面合并为 5 个导航页：「音画合并」并入「视频处理」（原「视频下载」）、
        「字幕校准」并入「字幕处理」，均以页内分段（SegmentedWidget）切换；
      · 支持把文件（视频/音频/字幕/文档/链接）直接拖进程序窗口自动分派；
      · 屏幕 DPI/缩放变化时强制全部页面重新布局，避免拖窗/换屏后扭曲。
    v2.1.0 起：
      · 新增「首页」（= 原「任务创建」分段），并作为**启动默认页**；
      · 导航面板顶部的返回箭头改为「定位到首页」——原先它调 qrouter.pop
        回退到"上一个访问过的页面"，而本程序几乎总是"从首页出发、到某页
        干活、再回首页"，回退语义反而不符合直觉（用户反馈：点返回后停在
        了没去过的页面）。改成固定跳首页，语义唯一、无歧义。
    """

    #: 导航项文案（宽度按其中最长的一项计算）
    #: v1.13.x：原「视频下载」更名「视频处理」——该页已同时承载「视频下载」与
    #: 「音画合并」两个板块，只叫"下载"名不副实。页内子板块名保持不变。
    NAV_TEXTS = ["首页", "视频处理", "视频库", "字幕处理", "字幕编辑", "流水线",
             "自动化", "设置"]

    #: 默认窗口宽度（高度由黄金比例推）。 以它为上界，
    #: 而不是以"窗口当前宽度"为上界——后者会把布局撑出来的尺寸固化下来。
    DEFAULT_WIDTH = 1180

    def __init__(self, argv=None):
        # 建窗分段计时（2026-10-21）：MainWindow 构造实测 1.0–3.9s 波动，
        # 是首帧前最大的不确定项。这几行埋点定位到具体页/步骤，别再靠猜。
        _mt = time.perf_counter()
        # 跨屏拖拽状态必须在 super().__init__() 之前建立：窗口构造过程中
        # Qt 就会派发 moveEvent，届时 moveEvent 会读这些属性
        self._last_screen = None
        self._last_screen_geo = None
        self._drag_anchor = None      # (相对屏宽的左/右比例) 用于跨屏重定位
        self._last_dpr = None         # 上次所在屏的设备像素比（跨屏后要对比）
        self._settle_pending = False  # 跨屏收敛是否已排队（防抖，只跑一轮）
        self._settle_tries = 0        # 拖拽中延后收敛的重试次数（有上限）
        super().__init__()
        _perf_note("mw[super] %.2fs" % (time.perf_counter() - _mt))
        # 切断"页面 → 堆叠 → 窗口"的最小尺寸传导链（2026-10-21 前移）。
        # ⚠ 必须在**第一次 addSubInterface 之前**设置：QStackedWidget.addWidget
        #   会重新计算自身 sizeHint/minimumSize（取所有页的最大值），而页里
        #   控件越多越贵。cProfile 实测 12 次 addWidget 累计 **1.49s**，就是
        #   这笔尺寸计算。提前把策略设为 Ignored 后，addWidget 不再递归量页。
        #   原位置（addSubInterface 之后）的同一段保留为幂等兜底。
        try:
            self.stackedWidget.setMinimumSize(0, 0)
            _sp = self.stackedWidget.sizePolicy()
            _sp.setHorizontalPolicy(QSizePolicy.Ignored)
            _sp.setVerticalPolicy(QSizePolicy.Ignored)
            self.stackedWidget.setSizePolicy(_sp)
        except Exception:  # noqa: BLE001
            pass
        self.q = queue.Queue()
        # 功能解耦阶段②/③：消息总线（订阅式路由）。业务消息由功能页/设置页
        # 各自 bus.subscribe；壳层编排消息 pipe_ready 由本窗口订阅。旧
        # _dispatch 路由表已整体删除（阶段③收尾）。
        self.bus = MessageBus(self.q, on_error=self._log_error)
        self.bus.subscribe("pipe_ready", self._on_pipe_ready)
        self.setWindowTitle(f"视频工具箱 v{_version()}")
        # 应用图标（v2.1.0）：main() 已挂在 QApplication 上了，这里再显式给
        # 主窗口设一份——MainWindow 若被自检/截图脚本**不经 main()** 直接
        # 构造（VT_GUI_SELFTEST 等路径就是），就只靠这一行拿到图标。
        try:
            _p = engine.app_icon_path()
            if _p:
                _ic = QIcon(_p)
                if not _ic.isNull():
                    self.setWindowIcon(_ic)
        except Exception:  # noqa: BLE001
            pass
        # 默认尺寸按**黄金比例**：1180 / 1.618 ≈ 729。窗口本身可以自由拖拽缩放，
        # 这里只是给一个观感上最舒服的起始比例（大多数屏幕/分栏都落在这个比例
        # 附近时才不会显得"扁"）。fit_to_screen() 收敛时也保持该比例。
        self.resize(self.DEFAULT_WIDTH,
                    int(round(self.DEFAULT_WIDTH / GOLDEN_RATIO)))
        self.setMinimumSize(880, 620)
        # 接受把文件/链接拖进窗口（v1.13.0）
        self.setAcceptDrops(True)
        # 边框缩放热区必须在**应用级**接住：载入视频后 Qt 会把导航条 / 标题栏 /
        # 页面一并提升成原生子窗口，它们从窗口边缘铺开、盖住边框带，于是主窗口
        # 的 nativeEvent 根本收不到 WM_NCHITTEST（详见 _ResizeHitFilter 的说明）。
        # 只对属于本窗口的消息生效，其它窗口与对话框原样放行。
        self._resize_hit_filter = None
        try:
            if sys.platform == "win32":
                self._resize_hit_filter = _ResizeHitFilter(self)
                _app = QApplication.instance()
                if _app is not None:
                    _app.installNativeEventFilter(self._resize_hit_filter)
        except Exception:  # noqa: BLE001
            self._resize_hit_filter = None

        try:
            # 云母档持久化在 ui_custom.json（设置页「界面」卡片可开关）；
            # Win10 无 Mica，qfluentwidgets 内部直接忽略，保持原样
            self.setMicaEffectEnabled(ui_theme.get_mica())
        except Exception:
            pass

        self.home_page = HomePage(self, self)
        _perf_note("mw[HomePage] %.2fs" % (time.perf_counter() - _mt))
        # 2026-11-15 功能解耦阶段②：功能页改**注册表驱动挂载**——GuiSpec 来自
        # 各 features/<id>/feature.py，builder 指向功能页 build_page。行为与
        # 旧硬编码逐项一致：惰性外壳 / 常驻真身（lazy=False）/ 底部导航 /
        # 分隔线，objectName 与挂载顺序不变；功能缺席或 builder 失败只跳过
        # 该页（降级模式①：导航缺席 + startup.log 留痕），绝不影响其它页。
        _reg = _registry_fn()
        self._feature_pages = {}
        for _fid, _g in _reg.gui_specs():
            setattr(self, _g.attr, None)   # 预置属性：发现失败也不缺引用
        for _fid, _g in _reg.gui_specs():
            try:
                _builder = _feature_resolve(_g.builder)
                if _g.lazy:
                    _page = _LazyPageShell(
                        self, lambda b=_builder: b(self), _g.nav, _g.object_name)
                else:
                    _page = _builder(self)
            except Exception as _e:  # noqa: BLE001
                _perf_note(f"功能页 {_fid} 挂载失败（不影响其它功能）：{_e}")
                continue
            setattr(self, _g.attr, _page)
            self._feature_pages[_fid] = _page
            _perf_note("mw[%s] %.2fs" % (_g.object_name, time.perf_counter() - _mt))
        self._pending_ai_text = ""
        # 设置页属壳（非可选功能），固定挂导航底部
        self.settings_page = _LazyPageShell(
            self, lambda: SettingsPage(self, self), "设置", "SettingsPage")
        # 被合并的子板块：仍挂到宿主页的堆叠里，保留快捷引用便于消息路由/自检
        # （download_page 是惰性外壳，merge_page 随之惰性属性；calib_page 同理）
        for page in (self.home_page, self.download_page, self.library_page,
                     self.subtitle_page,
                     self.subtitle_edit_page, self.pipeline_page,
                     self.settings_page):
            if page is not None:
                page.installEventFilter(self)

        # v2.1.0：「首页」= 任务创建，导航第一项 + 启动默认页
        self.addSubInterface(self.home_page, FIF.HOME, "首页")
        # 功能页按 GuiSpec.order 挂载：top 进主列表，bottom 固定导航底部
        # （「AI 托管」「自动化」是辅助页，设置上方）；sep_before 插分隔线。
        for _fid, _g in _reg.gui_specs():
            _page = getattr(self, _g.attr, None)
            if _page is None:
                continue
            if _g.sep_before:
                self.navigationInterface.addSeparator()
            _pos = (NavigationItemPosition.BOTTOM if _g.position == "bottom"
                    else NavigationItemPosition.TOP)
            self.addSubInterface(_page, getattr(FIF, _g.icon), _g.nav,
                                 position=_pos)
        self.addSubInterface(self.settings_page, FIF.SETTING, "设置",
                             position=NavigationItemPosition.BOTTOM)
        _perf_note("mw[addSubInterface] %.2fs" % (time.perf_counter() - _mt))
        # v2.1.0：导航面板顶部的返回箭头 → 固定跳首页（见 _setup_home_button）
        self._setup_home_button()
        # 窗口标题跟随当前页。v2.1.0 起「返回」键不再走 qrouter.pop
        # （改成跳首页，见 _setup_home_button），但仍挂 currentChanged：
        # 谁切的页（导航点击 / switchTo / 拖放分派）标题都跟得上。
        try:
            self.stackedWidget.currentChanged.connect(self._on_page_changed)
        except Exception:  # noqa: BLE001
            pass

        # 界面美化：五个导航页挂上「自定义背景图」绘制能力（v1.13.x）。
        # 未设置背景图时 paintEvent 原样透传，视觉与改造前逐像素一致；
        # 配置在 data/ui_custom.json，设置页「界面美化」卡片里改。
        try:
            ui_theme.install_for_window(self)
        except Exception:
            pass

        # 侧边导航常驻展开（默认窄条只有图标），宽度按最长项自适应
        self.navigationInterface.setCollapsible(False)
        self._apply_nav_width()
        _perf_note("mw[nav_width] %.2fs" % (time.perf_counter() - _mt))
        # 首帧后 + 字体度量就绪后再各收敛一次：任何时刻导航宽度都是
        # 「最长项文字 + 2 个字符」，不会出现「启动时一个宽度、稍后另一个宽度」
        _defer("nav_width_0", self._apply_nav_width, 0, 25, budget_ms=20)
        _defer("nav_width_400", self._apply_nav_width, 400, 40, budget_ms=20)

        # 切断"页面 → 堆叠 → 窗口"的最小尺寸传导链。
        # QStackedWidget 的最小尺寸取**所有页面**的最大值，页面里只要有内容
        # 偏大的（引擎工作台、波形时间轴），整个窗口就缩不下去 —— 实测拖右边缘
        # 往左、拖右下角，窗口纹丝不动，而拖上边缘看着"能动"只是因为它在移动
        # 而不是在缩放。用户的原话："左右、对角依旧无法"。
        try:
            self.stackedWidget.setMinimumSize(0, 0)
            _sp = self.stackedWidget.sizePolicy()
            _sp.setHorizontalPolicy(QSizePolicy.Ignored)
            _sp.setVerticalPolicy(QSizePolicy.Ignored)
            self.stackedWidget.setSizePolicy(_sp)
        except Exception:
            pass

        # v2.1.0：默认落地页 = 首页（任务创建），不再是「视频处理」。
        # 首页控件来自字幕工作台，这里只落页；控件由 HomePage.showEvent
        # → subtitle_page.ensure_built() 就绪后换上（先显示占位文案）。
        self.switchTo(self.home_page)
        self._apply_argv(argv or [])
        # 视频库首扫改为「真身建好后再跑」：`_LazyPageShell.defer` 只在用户
        # 第一次打开视频库页、真身构造完成时才执行回调。原先排在启动后
        # 1500ms 自动触发 `auto_load()`，等于启动 1.5 秒后自己去建整页再扫盘，
        # 也是「启动后自己先忙一阵」的一部分（2026-11-14 启动修复）。
        self.library_page.defer(lambda page: page.auto_load())
        # ⚠ _pump 是 120ms 常驻业务消息泵（跨线程队列），语义与启动调度不同，
        #   不并入调度器，保持原样。
        QTimer.singleShot(120, self._pump)
        # 流水线：延后启动，避开首屏与字幕引擎预热（v1.14.0）
        self.pipeline_registry = None
        self.pipeline = None
        _defer("start_pipeline", self._start_pipeline, 4000, 80,
               depends_on=("home_ui",), budget_ms=300)
        # ⚠ 启动期**不再**自动给「字幕处理」页预热/建工作台（2026-11-14 启动修复）。
        # 原先这里排着 800ms 的 prewarm_kick：后台线程导入完就回主线程建整个引擎
        # 工作台。日志（logs\startup.log，2026-11-14 19:37 那次）实测：窗口
        # T+2.43s 就可见，但紧接着这次构建把主线程独占 **33.18s**
        # （HomeInterface 构造 7.49s + 工作台整形/装箱 25.7s），期间界面完全
        # 点不动；后面的启动任务全部排队，直到 T+75s「自动化」页才收尾——
        # 正是用户说的「启动后自己先忙一阵，过一会儿才恢复」。
        # 现在改成纯按需：只有用户真的进入「字幕处理」页（或拖入文件触发分派，
        # 见 _dispatch_created_task 的 _pending_dispatch 兜底）才走
        # showEvent → ensure_built → prewarm。首页任务创建不依赖工作台
        # （HomePage.ensure_task_creation 直接构造 TaskCreationInterface），
        # 启动期没有任何「必须提前建它」的理由。
        #
        # 「自动化」页已改为惰性外壳（见 __init__ 里的说明），启动后不再自己
        # 构造——原先这里排的 20s auto_page 任务已删除。
        # 后台 import 预热：只把引擎模块的 import 在后台线程先做掉（不碰
        # 主线程、**不建界面**），延后到 30s——实测 10s 起线程时，后台 import
        # 会在 T+13s 附近引发一次约 700ms 的 GIL 争用，放在用户刚启动的操作
        # 窗口里不划算。用户首次进入「字幕处理」时只需付纯构造的代价
        # （热态实测 0.36s）；冷态由页面上的占位文案接住（见 _build_now 分段）。
        _defer("prewarm_import", self.subtitle_page.prewarm_import_only,
               30000, 95, depends_on=("home_ui",), budget_ms=5)
        # 主屏 DPI 变化（改缩放比/换主屏）时重新计算导航宽度。
        # 注意必须用 QApplication 实例的信号：PySide6 里类的同名属性是未绑定的
        # Signal 描述符，直接 .connect 会抛 AttributeError。
        try:
            QApplication.instance().primaryScreenChanged.connect(
                lambda *_: self._on_screen_changed())
        except Exception:
            pass
        # 显示器增删（拔插外接屏 / KVM 切屏 / 笔记本合盖）同样要收敛：Qt 会把
        # 窗口迁到剩下的那块屏上，DPI 与可用区域都可能跟着变。窗口**所在屏**
        # 的变化走 _watch_window_screen() 里的 QWindow.screenChanged（见 showEvent）。
        try:
            _app = QApplication.instance()
            _app.screenAdded.connect(lambda *_: self._schedule_screen_settle())
            _app.screenRemoved.connect(lambda *_: self._schedule_screen_settle())
        except Exception:
            pass

    def _on_screen_changed(self):
        """屏幕变化（换主屏 / 改缩放比 / 显示器增删）→ 排队一次跨屏收敛。

        v1.14.2 起改成**只转发**：所有"显示器变了"的入口（primaryScreenChanged
        / logicalDotsPerInchChanged / screenAdded / screenRemoved / 窗口的
        screenChanged / moveEvent 越过屏幕边界）统一汇聚到
        `_settle_after_screen_switch()`，一条路径做完全部收敛动作，
        不会出现"某条信号只重排不重建表面"的半吊子状态。
        """
        self._schedule_screen_settle()

    # ---------- 跨屏 / 显示器变化收敛（v1.14.2） ----------
    def _watch_window_screen(self):
        """把窗口所在显示器的 screenChanged 接上。

        为什么非接不可：`primaryScreenChanged` 只有**主屏**变了才响，
        `logicalDotsPerInchChanged` 只有**那块屏的缩放比被人改过**才响 ——
        把窗口从一块屏拖到另一块屏，这两个信号都不会触发，于是跨屏后
        既不重排也不重绘，页面就停在旧几何上（用户看到的"换屏后整个页面
        挤成一团"）。`QWindow.screenChanged` 是**唯一**在这种情况下必定触发
        的信号。

        构造期 windowHandle() 还是空，所以只能等首帧之后再挂；挂上一次即够。
        """
        if getattr(self, "_screen_sig_ready", False):
            return
        try:
            wh = self.windowHandle()
        except Exception:
            wh = None
        if wh is None:
            QTimer.singleShot(200, self._watch_window_screen)
            return
        try:
            wh.screenChanged.connect(self._on_window_screen_changed)
            self._screen_sig_ready = True
        except Exception:
            pass

    def _on_window_screen_changed(self, *_):
        """窗口换了显示器 → 排队一次跨屏收敛。"""
        self._schedule_screen_settle()

    def _schedule_screen_settle(self):
        """跨屏收敛的防抖入口：多次触发只跑一轮。"""
        if getattr(self, "_settle_pending", False):
            return
        self._settle_pending = True
        self._settle_tries = 0
        # 三次是刻意的：0ms 让本轮事件先跑完，160ms 等 Qt/DWM 把新 DPI 落实
        # 到窗口几何上，480ms 再兜一遍，避免"拖过去看着还是歪的，动一下才好"。
        for delay in (0, 160, 480):
            QTimer.singleShot(delay, self._settle_after_screen_switch)

    def _settle_after_screen_switch(self):
        """跨屏/DPI 变化后的统一收敛：重排页面 → 收敛进新屏 → 重建窗口表面。

        四步缺一不可：
          1) 记账新屏 + 把窗口收进新屏可用区（两屏缩放比不同时 Qt 会保持
             逻辑尺寸，个别前提下窗口会伸出新屏之外）；
          2) `_apply_nav_width()` + `_relayout_pages()`：重算导航宽度、
             全页 updateGeometry + 下一帧重排；
          3) 字幕编辑页重设分割条比例、让字幕层重新贴合画面（两次是刻意的：
             第一次等本轮重排落定，第二次在 DWM 提交新帧之后兜一遍）；
          4) `_rebuild_window_surface()`：无边框 + 云母窗口在 DPI 切换后
             DWM 会保留旧尺寸的窗口表面，只重画客户区清不掉它 —— 表现为
             "页面被挤到一侧、旁边还挂着上一份界面"。

        用户还按着鼠标（正在拖窗口）时不抢：拖拽中重排会跟他的操作打架，
        而且窗口还在继续跨屏，等松手后再结算（有重试上限，不会一直挂着）。
        """
        try:
            if QApplication.mouseButtons() != Qt.NoButton:
                if self._settle_tries < 20:
                    self._settle_tries += 1
                    QTimer.singleShot(300, self._settle_after_screen_switch)
                    return
        except Exception:
            pass
        self._settle_pending = False
        self._settle_tries = 0
        try:
            scr = self.screen()
        except Exception:
            scr = None
        if scr is not None:
            try:
                self._last_screen = scr
                self._last_screen_geo = scr.geometry()
                self._last_dpr = self._dpr_of(self)
            except Exception:
                pass
            self._clamp_to_screen(scr)
        # 导航宽度 + 全页几何刷新（原先由 _on_screen_changed 承担）
        self._apply_nav_width()
        self._relayout_pages()
        for delay in (0, 200):
            QTimer.singleShot(
                delay,
                lambda: self.subtitle_edit_page.relayout_after_screen_change())
        self._rebuild_window_surface()

    @staticmethod
    def _dpr_of(widget):
        try:
            return float(widget.devicePixelRatioF() or 1.0)
        except Exception:
            return 1.0

    def _clamp_to_screen(self, scr):
        """把窗口收进所在屏的可用区（只在确实超出时才缩，不主动放大）。

        两屏缩放比不同时 Qt 保持窗口的**逻辑尺寸**不变，物理尺寸随之改变 ——
        在物理分辨率不变、缩放比更大的那块屏上，窗口就可能伸出屏幕之外，
        边缘够不到鼠标。这里只做单向收敛，不动用户自己调好的尺寸。
        """
        try:
            avail = scr.availableGeometry()
        except Exception:
            return
        try:
            max_w = max(self.minimumWidth(), int(avail.width() * 0.96))
            max_h = max(self.minimumHeight(), int(avail.height() * 0.96))
            w = min(self.width(), max_w)
            h = min(self.height(), max_h)
            if w != self.width() or h != self.height():
                self.resize(w, h)
        except Exception:
            pass

    def _rebind_native_children_screen(self, scr):
        """把主窗口与原生子窗口重新挂到 `scr` 上，让 Qt 按新显示器重算表面。

        为什么必须做：mpv 通过 `wid` 嵌进 `video_host` 会调用 `winId()`，Qt
        随之把导航条 / 标题栏 / 页面这些 widget 一并**提升成原生子窗口**，
        而且原生窗口一旦创建就不会撤销（见 `_ResizeHitFilter` 的注释）。这些
        原生子窗口各自持有 QWindow，**不会**跟着主窗口的显示器变化走：跨屏
        到另一块缩放比不同的屏后，它们仍按旧 DPI 渲染 —— 画面上就是"导航条
        出现在窗口中间、页面被拆成两块"。把它们的 QWindow 逐个 setScreen 到
        当前屏，Qt 才会重新分配各自的 backing store。

        `QWidget.windowHandle()` 对普通子控件返回的是顶层窗口的句柄（于是这
        里会跳过），只有真正持有自己 QWindow 的原生子窗口才会被处理。
        """
        try:
            top = self.windowHandle()
        except Exception:
            top = None
        try:
            if top is not None and top.screen() is not scr:
                top.setScreen(scr)
        except Exception:
            pass
        try:
            children = self.findChildren(QWidget)
        except Exception:
            return
        for w in children:
            try:
                h = w.windowHandle()
                if h is None or h is top or h.screen() is scr:
                    continue
                h.setScreen(scr)
            except Exception:
                continue
        # 强制各窗口立刻重建表面（Qt 5.12+；老版本没有此方法，静默跳过）
        try:
            if top is not None:
                top.requestUpdate()
        except Exception:
            pass

    def _rebuild_window_surface(self):
        """强制重建窗口表面，清掉跨屏后残留的旧画面。

        无边框 + 云母（Mica）的窗口在显示器 DPI 切换时，DWM 会留着上一份
        尺寸的窗口表面；Qt 的 update()/repaint() 只重画客户区，碰不到那层
        旧表面，用户看到的就是"页面被压到一侧、右边又冒出半份界面"。三步：
          1) 把主窗口与**原生子窗口**重新挂到当前显示器：载入过视频后 Qt 会
             把导航条 / 标题栏 / 页面提升成原生子窗口（见 `_ResizeHitFilter`
             的注释），这些原生子窗口不会自己跟随显示器 DPI 变化，跨屏后
             仍按旧 DPI 渲染 —— 画面就是"导航条跑到窗口中间、页面被拆成
             两块"。重新 setScreen 后 Qt 才会按新 DPI 重算它们的表面；
          2) SetWindowPos + SWP_FRAMECHANGED：让系统按新 DPI 重算窗口框架，
             再抖动 1px 迫使系统连带重画窗口**原先占的**那块屏幕区域
             （残影就贴在那里）；
          3) repaint()：立刻提交新帧，不等下一次合成。
        任何一步失败都只影响观感，不影响功能，全部包 try。
        """
        scr = None
        try:
            scr = self.screen()
        except Exception:
            scr = None
        if scr is not None:
            self._rebind_native_children_screen(scr)
        try:
            import win32con
            import win32gui
            flags = (win32con.SWP_NOMOVE | win32con.SWP_NOSIZE
                     | win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE
                     | win32con.SWP_FRAMECHANGED)
            win32gui.SetWindowPos(int(self.winId()), 0, 0, 0, 0, 0, flags)
        except Exception:
            pass
        try:
            x, y = self.x(), self.y()
        except Exception:
            return
        # 逻辑尺寸没变时 Qt 不会走 resizeEvent，backing store 可能仍按旧 DPR
        # 分配；抖动 1px 触发一次完整的 resize → 布局重排 → 缓冲重建。
        # 最大化/全屏时不动（那时尺寸由系统管，抖动会被忽略或打架）。
        try:
            if not self.isMaximized() and not self.isFullScreen():
                w, h = self.width(), self.height()
                self.resize(w + 1, h)
                self.resize(w, h)
        except Exception:
            pass
        try:
            self.move(x, y + 1)

            def _back(_x=x, _y=y):
                # 用户恰好在这 30ms 里拖动窗口时别把他拽回去
                try:
                    if QApplication.mouseButtons() == Qt.NoButton:
                        self.move(_x, _y)
                except Exception:
                    pass
            QTimer.singleShot(30, _back)
        except Exception:
            pass
        try:
            self.updateGeometry()
            self.update()
            self.repaint()
        except Exception:
            pass

    def _relayout_pages(self):
        """PPI/缩放/导航宽度变化后强制全部页面重排，消除旧几何残留导致的扭曲。

        每个页面：先 updateGeometry 让布局管理器重新计算尺寸提示，再在下一帧
        由 Qt 完成实际重排；滚动区把内容高度重新贴合视口。整体包 try，任何
        一个页面出问题都不影响其余页面。
        """
        for page in (self.download_page, self.library_page, self.subtitle_page,
                     self.subtitle_edit_page, self.pipeline_page,
                     self.settings_page):
            # 惰性外壳：已构造的用真身，没构造的空外壳无可重排（跳过即可）
            real = getattr(page, "real", None) or page
            try:
                real.updateGeometry()
                for sub in (getattr(real, "dl_tab", None),
                            getattr(real, "work_tab", None)):
                    if sub is not None:
                        sub.updateGeometry()
                for area in real.findChildren(QWidget):
                    if getattr(area, "widgetResizable", False):
                        try:
                            area.widget().updateGeometry()
                        except Exception:
                            pass
            except Exception:
                pass
        try:
            self.stackedWidget.adjustSize()
            cur = self.stackedWidget.currentWidget()
            if cur is not None:
                cur.updateGeometry()
        except Exception:
            pass

    # ---------- 惰性页快捷引用 ----------
    @property
    def merge_page(self):
        """「音画合并」子板块（挂在下载页里）——惰性：首次取用才建下载页。

        2026-10-20 启动专项：download_page 改外壳后，这个快捷引用不能
        再在 __init__ 里取值（那会把整页建出来），改成惰性属性。
        """
        return self.download_page.merge_page

    @property
    def calib_page(self):
        """「字幕校准」页（挂在字幕处理页里）——惰性：首次取用才建。"""
        return self.subtitle_page.calib_page

    # ---------- 首页 / 返回箭头 ----------
    def goto_home(self):
        """回首页（任务创建）。导航返回箭头、外部跳转都走这里。"""
        page = getattr(self, "home_page", None)
        if page is None:
            return
        try:
            self.switchTo(page)
        except Exception as e:  # noqa: BLE001
            _perf_note(f"回首页失败：{e}")

    def goto_video_download(self, url):
        """把一个网页链接交给「视频处理 / 视频下载」页并跳过去。

        任务创建输入框识别到链接时走这里（见 ``url_detected``）。选下载页
        而不是让任务创建页自己下载，是因为下载页有画质选择 / 并行队列 /
        中止 / 代理 / 字幕打包，引擎那套 VideoDownloadThread 只有裸下一条。

        ⚠ 必须在下载页已可用时调用；若页面尚未构建完（理论上不会——它随
        主窗口一起建），只填链接不跳页，避免把用户卡住。
        """
        url = str(url or "").strip()
        if not url:
            return
        try:
            dp = self.download_page
            dp.url_edit.setText(url)
            try:
                dp.seg.setCurrentItem("download")
                dp.stack.setCurrentIndex(0)
            except Exception:  # noqa: BLE001
                pass
            self.switchTo(dp)
            # 自动开一次画质检测：用户粘链接的意图就是「下载」，替他省掉
            # 切页后还要点一次「检测画质」。检测是后台线程，不卡 UI。
            QTimer.singleShot(0, dp.detect)
            InfoBar.success(
                "已识别视频链接", "已跳转到「视频下载」，正在检测可用画质…",
                duration=4000, position=InfoBarPosition.BOTTOM, parent=self)
        except Exception as e:  # noqa: BLE001
            _perf_note(f"跳转视频下载失败：{e}")

    # ---------- AI 托管（v2.1.0） ----------
    def goto_ai_console(self, text=""):
        """把一段纯文本交给「AI 托管」页执行并跳过去。

        首页任务框 ``ai_requested`` 的落点。harness 不在场时
        ``self.harness_page`` 为 None，这里静默返回——调用方（任务创建页）
        在没 harness 时压根不会发信号，双保险。
        """
        page = getattr(self, "harness_page", None)
        if page is None:
            # 首页任务框现在先于 AI 托管页（4s）就绪；用户若在页面建好前
            # 就输入纯文本，先记住内容并插队构建，建好后自动续跑。
            self._pending_ai_text = text
            _defer("harness_page", self._build_harness_page, 0, 0,
                   budget_ms=1200)
            s = _SCHED["inst"]
            if s is not None:
                s.run_now("harness_page", 0)
            return
        try:
            self.switchTo(page)
            if text:
                page.run_task(text)
        except Exception as e:  # noqa: BLE001
            _perf_note(f"AI 托管跳转失败：{e}")

    def ai_settings_summary(self):
        """「设置」页 AI 配置的一行摘要（AI 托管页状态卡展示用）。

        harness 的模型 / 密钥 / 接口地址**唯一事实来源就是这份配置**
        （harness_bridge.sync_provider_config 每次运行前同步）。
        """
        try:
            import json as _json
            p = os.path.join(engine.DATA_DIR, "ai_config.json")
            with open(p, encoding="utf-8-sig") as f:
                d = _json.load(f) or {}
            model = (d.get("model") or "").strip()
            base = (d.get("base_url") or "").strip()
            key = (d.get("api_key") or "").strip()
            if not (model and base and key):
                return "「设置」页尚未配置 AI（接口地址 / 密钥 / 模型）"
            masked = key[:4] + "…" + key[-4:] if len(key) > 10 else "…"
            return "AI 配置（来自「设置」页）：模型 %s · 接口 %s · 密钥 %s" % (
                model, base, masked)
        except Exception:  # noqa: BLE001
            return ""

    def _setup_home_button(self):
        """把导航面板顶部的返回箭头改成「定位到首页」。

        原实现（qfluentwidgets 默认）：``returnButton.clicked → qrouter.pop``，
        且 ``history.emptyChanged → setDisabled``——历史栈空了就灰掉。
        问题是本程序的访问模式几乎总是「首页 → 某页干活 → 想回首页」，pop
        回退到"上一个访问过的页面"并不等于"回首页"，用户反馈点返回后停在
        了没去过的页面。

        改成固定跳首页：语义唯一、任何时候可点。图标 RETURN→HOME，
        tooltip 「Back」→「定位到首页」。另外顺手断开 push：历史栈既然
        没人消费，每切一次页就往里塞一条，纯属无谓增长。
        """
        try:
            panel = getattr(self.navigationInterface, "panel", None)
            btn = getattr(panel, "returnButton", None)
            if btn is None:
                return
            # 断开 qrouter.pop（原 clicked 槽）
            try:
                btn.clicked.disconnect()
            except Exception:  # noqa: BLE001
                pass
            btn.clicked.connect(self.goto_home)
            # 断开"历史空即禁用"，否则启动后栈空 → 按钮灰着点不动
            try:
                panel.history.emptyChanged.disconnect(btn.setDisabled)
            except Exception:  # noqa: BLE001
                pass
            # 断开 qrouter.push（_onCurrentInterfaceChanged 里的那一行）：
            # 它把每次切页都记进全局历史栈，而本程序已不用 pop 语义。
            # 只改 push 会连带影响 setCurrentItem，必须整段替换。
            try:
                self.stackedWidget.currentChanged.disconnect(
                    self._onCurrentInterfaceChanged)
            except Exception:  # noqa: BLE001
                pass

            def _sync_nav(index):
                try:
                    w = self.stackedWidget.widget(index)
                    if w is not None and w.objectName():
                        self.navigationInterface.setCurrentItem(w.objectName())
                    self._updateStackedBackground()
                except Exception:  # noqa: BLE001
                    pass

            self.stackedWidget.currentChanged.connect(_sync_nav)
            # 图标/提示改成"定位到首页"
            try:
                from vt_fluent import FluentIcon as _FI
                btn.setIcon(_FI.HOME)
            except Exception:  # noqa: BLE001
                pass
            try:
                btn.setToolTip(self.tr("定位到首页"))
            except Exception:  # noqa: BLE001
                pass
            # ⚠ NavigationPanel.__init__ 里**直接调过**一次
            # ``returnButton.setDisabled(True)``（不只是连了 emptyChanged）。
            # 只 disconnect 信号不够——那一刀早就砍下去了，必须显式恢复，
            # 否则按钮永远灰着、点了没反应（正是这次要修的那个症状）。
            btn.setEnabled(True)
        except Exception as e:  # noqa: BLE001
            _perf_note(f"返回箭头改造失败：{e}")

    # ---------- 导航宽度 ----------
    def refresh_nav_width(self):
        """外部调用：内容/字体变化后重新收敛导航宽度（幂等）。"""
        self._apply_nav_width()

    def _apply_nav_width(self):
        """按最长导航文案重算展开宽度：最长项文字 + 2 个中文字 + 面板固有占位。

        展开宽度用逻辑像素计算，Qt 会按当前屏幕缩放比自动换算物理像素，
        因此 100% / 125% / 150% / 200% 下呈现的视觉宽度一致。

        v1.11.0 统一口径：字体取**导航面板实际使用的字体**（panel.font()），
        不再在「窗口字体 / 默认雅黑」之间取较宽者——那样在引擎字体与宿主不同
        时会把导航撑宽，观感上就是「程序开启时宽度是原样、过一会儿才变」。
        重算时机：窗口构造后、首帧后、引擎界面/设置页引擎区构建后、DPI 变化时。
        """
        try:
            panel = getattr(self.navigationInterface, "panel", None)
            font = panel.font() if panel is not None else self.font()
            width = int(nav_width_for(self.NAV_TEXTS, font))
            self.navigationInterface.setExpandWidth(width)
            _perf_note(f"导航宽度 = {width}px"
                       f"（{font.family()} {font.pointSize()}pt）")
        except Exception:
            pass

    # ---------- 页面/状态 ----------
    def fit_to_screen(self):
        """按所在屏幕可用区域收敛窗口尺寸并居中，**始终保持黄金比例**。

        旧版分别对宽高取 min()，屏幕矮一点就会出现"宽度被砍、高度不动"的扁
        窗口（1180x860 → 1180x780 之类），比例跑掉。现在先按默认宽度定高度，
        高度超屏就反过来按高度反推宽度，比例恒定。

        全程用**逻辑像素**（Qt 的 geometry 在开启高 DPI 缩放后即为逻辑像素），
        因此 100% / 125% / 150% / 200% 下占用屏幕的比例保持一致。
        """
        try:
            avail = self.screen().availableGeometry()
        except Exception:
            return
        max_w = max(self.minimumWidth(), int(avail.width() * 0.92))
        max_h = max(self.minimumHeight(), int(avail.height() * 0.92))
        # ⚠️ 基准必须用**默认尺寸**，不能用 。
        #    窗口从构造到显示之间会被布局按 sizeHint 撑大（实测 1440x889，
        #    在 1280/1440 这类屏幕上等于满屏甚至超屏），拿"当前宽度"当上限
        #    等于把这个错误尺寸固化下来 —— 用户看到的窗口则贴满屏幕，
        #    左右边缘与屏幕边缘重合，鼠标够不着，正是"左右、对角依旧无法"
        #    "只能拉顶部"。
        # 窗口宽高比**跟随屏幕**（16:9 屏→16:9、16:10 屏→16:10、16:9 以下同），
        # 不再锁定固定 GOLDEN_RATIO —— 用户实测「比例只兼容 16:9，不兼容 16:10」：
        # 固定 1.618 的窗口在 16:10 屏上与屏幕比例错位（窗口看着偏扁/偏方），
        # 且竖直方向利用不足。这里取屏幕可用区的宽高比作为窗口比例。
        ratio = (avail.height() / avail.width()) if avail.width() else 1.0
        w = min(self.DEFAULT_WIDTH, max_w)
        h = int(round(w * ratio))
        if h > max_h:
            h = max_h
            w = int(round(h / ratio))
        w = max(w, self.minimumWidth())
        h = max(h, self.minimumHeight())
        self.resize(w, h)
        self.move(avail.x() + (avail.width() - w) // 2,
                  avail.y() + (avail.height() - h) // 2)
        self._remember_screen()

    # ---------- 尺寸约束 ----------
    def sizeHint(self):
        """窗口的理想尺寸由我们给，不让"所有页面 sizeHint 取最大值"说了算。

        实测主窗口的 sizeHint 被堆到 1756x991（各页面 sizeHint 的最大值），
        而布局会拿它当尺寸下限 ——  立即是 620，**一拍之后
        被布局改回 991**； 干脆完全无效。
        窗口因此比屏幕还大，下边缘跑到屏幕外，用户的原话是
        "左右、对角依旧无法""只能拉顶部，底部依旧无法调整"。
        """
        return QSize(self.DEFAULT_WIDTH,
                      int(round(self.DEFAULT_WIDTH / GOLDEN_RATIO)))

    def minimumSizeHint(self):
        """把窗口能缩到多小**交还给 **，不听布局的。

        为什么必须覆写： 的最小尺寸取的是**所有子页面的最大值**，
        而"字幕处理"页嵌着引擎工作台，内容天然偏大——实测整个窗口的最小尺寸
        被顶到 **1440x889**。后果不是"窗口太大"这么温和，而是：

          · 左右方向**只能拉大、不能缩小**（拖右边缘往左毫无反应）；
          · 对角同理（含左右分量）；
          · 在 1280x720 这类屏幕上窗口比屏幕还大，上下边缘直接跑到屏幕外，
            连拖都够不着——用户的原话就是"左右、对角依旧无法"。

        内容超出应该由各页面自己的滚动区消化，而不是反过来把窗口顶大。
        """
        ms = self.minimumSize()
        if ms.width() > 0 and ms.height() > 0:
            return ms
        return super().minimumSizeHint()

    # ---------- 窗口缩放（边缘拖拽） ----------
    def nativeEvent(self, eventType, message):
        """放宽 Windows 的边缘拖拽热区，让四边/四角都能稳稳拖住。

        背景：无边框窗口的缩放全靠 WM_NCHITTEST 返回 HTLEFT / HTBOTTOMRIGHT 等
        让系统接管。上游 `qframelesswindow` 的热区是 `BORDER_WIDTH` **物理像素**
        （仅 5px），在 125%/150% 缩放的高分屏上折算成逻辑像素只剩 3~4px，
        实际表现就是「窗口边缘拖不动」。这里不碰上游实现，只在自己的
        nativeEvent 里按**设备像素比**放大热区；命中则直接返回，未命中仍交给
        基类（`maxBtn` 悬停高亮等逻辑照常）。

        非 Windows 平台 / pywin32 不可用时静默回退到基类行为。
        """
        if sys.platform == "win32":
            try:
                import ctypes
                from ctypes.wintypes import MSG
                import win32con
                import win32gui

                msg = MSG.from_address(message.__int__())
                if (msg.message == win32con.WM_NCHITTEST
                        and getattr(self, "_isResizeEnabled", True)
                        and not self.isMaximized() and not self.isFullScreen()):
                    # ⚠️ 坐标必须取 **lParam**（低 16 位 x、高 16 位 y，屏幕坐标），
                    #    不要用 `GetCursorPos()`：后者返回的是"此刻"的鼠标位置，
                    #    与消息携带的坐标在系统连发多条命中测试时并不一致，
                    #    表现为边缘偶尔点不中、光标不变成双向箭头 —— 用户感受
                    #    就是"窗口拖不动"。（上游 qframelesswindow 也是这么写的，
                    #    所以我们自己的这份要写对。）
                    sx = ctypes.c_short(msg.lParam & 0xFFFF).value
                    sy = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
                    dpr = float(self.devicePixelRatioF() or 1.0)
                    bw = max(5, int(round(RESIZE_MARGIN * dpr)))
                    x, y = win32gui.ScreenToClient(msg.hWnd, (sx, sy))
                    rect = win32gui.GetClientRect(msg.hWnd)
                    cw, ch = rect[2] - rect[0], rect[3] - rect[1]
                    # 窗口本身就比热区大不了多少时不做命中，免得整窗都成了"边缘"
                    if cw > bw * 4 and ch > bw * 4:
                        left, right = x < bw, x > cw - bw
                        top, bottom = y < bw, y > ch - bw
                        hit = None
                        if left and top:
                            hit = win32con.HTTOPLEFT
                        elif right and bottom:
                            hit = win32con.HTBOTTOMRIGHT
                        elif right and top:
                            hit = win32con.HTTOPRIGHT
                        elif left and bottom:
                            hit = win32con.HTBOTTOMLEFT
                        elif left:
                            hit = win32con.HTLEFT
                        elif right:
                            hit = win32con.HTRIGHT
                        elif top:
                            hit = win32con.HTTOP
                        elif bottom:
                            hit = win32con.HTBOTTOM
                        if hit is not None:
                            return True, hit
                        # ⚠️ 没命中边缘时**明确回 HTCLIENT，不要交给上游**。
                        #    上游 qframelesswindow 取坐标用的是 
                        #    而不是消息自带的 lParam，窗口被移动过、或命中测试
                        #    连发时会算错——实测窗口**正中央**会返回
                        #    HTBOTTOMLEFT，于是"拖窗口中间"变成了缩放窗口，
                        #    看起来就是"点哪儿都在缩放、没法正常操作"。
                        #    我们这份用 lParam，判定可信，整条命中测试由此接管。
                        return True, win32con.HTCLIENT
            except Exception:
                pass
        return super().nativeEvent(eventType, message)

    # ---------- 跨屏拖拽 ----------
    def _remember_screen(self):
        scr = self.screen()
        if scr is None:
            return
        if scr is not self._last_screen:
            self._last_screen = scr
            self._last_screen_geo = scr.geometry()
            self._last_dpr = self._dpr_of(self)
            # 监听该屏幕的 DPI 变化（用户改缩放比时需重算导航宽度并重排页面）
            try:
                scr.logicalDotsPerInchChanged.connect(
                    lambda *_: self._on_screen_changed())
            except Exception:
                pass

    def showEvent(self, event):
        """首次显示后把窗口尺寸收敛回默认值。

        为什么非做不可：从构造到显示之间，布局会按各页面的 sizeHint 把窗口
        撑大（实测 1180x729 变成 1440x889）。在 1280/1440 这类屏幕上，被撑大
        的窗口等于满屏甚至超屏——左右边缘与屏幕边缘重合，鼠标根本够不着，
        用户的原话就是"左右、对角依旧无法""只能拉顶部，底部依旧无法调整"。
        显示后连收敛三次（0/200/600ms）是刻意的：这一段时间里还可能有一次
        布局重排，兜住它。
        """
        super().showEvent(event)
        # 首帧之后 windowHandle 才存在，此时才能接住"窗口换显示器"的信号
        QTimer.singleShot(0, self._watch_window_screen)
        if getattr(self, "_first_sized", False):
            return
        self._first_sized = True
        for delay in (0, 200, 600):
            QTimer.singleShot(delay, self.fit_to_screen)

    def moveEvent(self, event):
        """跨屏拖拽时保持窗口在两屏上的相对位置。

        Windows 上两屏缩放比不同时，Qt 会在窗口跨过屏幕边界后按新屏的
        缩放比重新换算逻辑坐标，窗口因此被「拉」回新屏左缘（瞬移）。
        这里的做法：检测到窗口进入另一块屏幕时，按窗口中心在**原屏**的
        相对位置（0~1）映射到新屏上，再把窗口放到对应位置——这样从右屏
        拖到左屏会停在左屏右侧的对应位置，而不是贴到左屏最左边。

        注意：本方法会在构造函数里 `super().__init__()` 期间就被 Qt 调用，
        那时实例属性还没建立，因此状态一律用 getattr 兜底取，且整个过程
        包在 try 里——虚拟方法里抛出未捕获异常会让 Qt 直接 abort 进程。
        """
        super().moveEvent(event)
        try:
            prev = getattr(self, "_last_screen", None)
            prev_geo = getattr(self, "_last_screen_geo", None)
            scr = self.screen()
            if scr is None:
                return
            geo = scr.geometry()
            if prev is not None and prev is not scr:
                # 窗口刚越过屏幕边界：无论用户是拖过去的还是程序性移动，
                # 都要排一次跨屏收敛（重排页面 + 重建窗口表面）。这条是兜底，
                # 主路径是 QWindow.screenChanged（见 _watch_window_screen）。
                self._schedule_screen_settle()
            self._last_screen = scr
            self._last_screen_geo = geo
            if prev is None or prev_geo is None or prev is scr:
                return
            if prev_geo.width() <= 0 or geo.width() <= 0:
                return
            # 仅在非用户拖拽（程序主动 setGeometry）时才做重定位，避免与拖拽打架
            if QApplication.mouseButtons() != Qt.NoButton:
                return

            def _reposition():
                try:
                    # 用窗口中心的相对位置跨屏映射（钳制在 0~1，保证整窗可见）
                    cx = self.x() + self.width() / 2.0
                    nx = (cx - prev_geo.x()) / float(prev_geo.width())
                    nx = min(max(nx, 0.0), 1.0)
                    target = geo.x() + nx * geo.width() - self.width() / 2.0
                    target = max(geo.x(),
                                 min(target, geo.x() + geo.width() - self.width()))
                    if abs(target - self.x()) > 1:
                        self.move(int(round(target)), self.y())
                except Exception:
                    pass
            QTimer.singleShot(0, _reposition)
        except Exception:
            pass

    def _page_title(self, page):
        """当前页对应的标题后缀（PAGE_TITLES 未收录时返回 ""）。"""
        try:
            return PAGE_TITLES.get(page.objectName(), "")
        except Exception:  # noqa: BLE001
            return ""

    def _on_page_changed(self, _index=None):
        """窗口标题跟随堆叠的当前页。

        此前标题只在 switchTo 里写。导航「返回」键走 qrouter.pop →
        stackedWidget.setCurrentWidget，**绕过 switchTo**，于是页面回去了
        而标题停在上一页（用户反馈：跳转后顶部一直显示「字幕编辑」）。
        挂到 currentChanged 上，无论谁切的页，标题都跟得上。
        """
        try:
            page = self.stackedWidget.currentWidget()
            if page is None:
                return
            suffix = self._page_title(page)
            self.setWindowTitle(
                f"视频工具箱 v{_version()}" + (f" — {suffix}" if suffix else ""))
        except Exception:  # noqa: BLE001
            pass

    def switchTo(self, page):
        # 切页时布局会按新页面的 sizeHint 把窗口撑大（实测 1180x729 → 1440x889），
        # 而用户并没有要求变大 —— 撑大后窗口可能超出屏幕，边缘够不着鼠标。
        # 记下切页前的尺寸，切页后若被撑大就还原回去（用户自己拖大的尺寸不会丢）。
        before = self.size()
        self.stackedWidget.setCurrentWidget(page, popOut=False)
        self._on_page_changed()

        def _clamp():
            try:
                if not self.isVisible() or self.size() == before:
                    return
                # ⚠️ 三条护栏，缺任何一条都会表现成"窗口拖不动"：
                #   1) 用户手还按着鼠标（正在拖边缘）—— 别跟他的操作抢；
                #   2) 只在**被布局撑大**时收敛。缩小时是用户自己的意图，
                #      这里再 resize 一次会把他刚拖出来的尺寸直接吃掉；
                #   3) 收敛目标不超出屏幕可用区，免得把窗口摆成"边缘够不到"。
                if QApplication.mouseButtons() != Qt.NoButton:
                    return
                if (self.width() <= before.width()
                        and self.height() <= before.height()):
                    return
                self.resize(before)
            except Exception:  # noqa: BLE001
                pass
        # 两次：切页动画/布局重排都要置完之后再纠正
        QTimer.singleShot(0, _clamp)
        QTimer.singleShot(300, _clamp)

    def _make_harness_page(self):
        """构造「AI 托管」页真身（`_LazyPageShell` 的 builder）。

        2026-11-14 启动修复：构造实测 0.34–1.31s（harness 适配层探测 + 30 余张
        卡片 QSS 首渲染），启动期不再自己建，等用户第一次点开该页。
        """
        t0 = time.perf_counter()
        page = _harness_page_mod.HarnessPage(self, self)
        _perf_note("AI 托管页惰性构造完成：%.2fs"
                   % (time.perf_counter() - t0))
        return page

    def _build_harness_page(self):
        """确保「AI 托管」页可用（幂等）——按需路径的唯一入口。

        外壳模式下等价于 ``harness_page.ensure()``；真身已存在时直接取。
        保留这个方法名，是因为 ``goto_ai_console`` / 截图 / 自检都从这里进。
        失败时该页缺席（导航项仍在，点开得到空白外壳），不影响其余功能。
        """
        page = getattr(self, "harness_page", None)
        if page is None:
            return True
        if isinstance(page, _LazyPageShell):
            try:
                page.ensure()
            except Exception as e:  # noqa: BLE001
                _perf_note(f"AI 托管页创建失败（不影响既有功能）：{e}")
                return True
            page = page.real
        if page is None:
            return True
        pending = getattr(self, "_pending_ai_text", "")
        if pending:
            self._pending_ai_text = ""
            QTimer.singleShot(0, lambda t=pending: self.goto_ai_console(t))
        return True

    def _maybe_build_auto_page(self, attempt=0):
        """预热未完成时顺延自动化页构造（最多等 12s，超时照常构造）。"""
        if not _engine_prewarm_done() and attempt < 30:
            QTimer.singleShot(400, lambda: self._maybe_build_auto_page(attempt + 1))
            return
        self._build_auto_page()

    def _make_auto_page(self):
        """构造「自动化」页真身（`_LazyPageShell` 的 builder）。

        2026-11-14：冷态实测 52.6s（视觉引擎/numpy/PIL 首次导入），因此必须是
        惰性 builder，绝不能出现在启动路径上。构造失败时返回一个占位控件——
        外壳的 ``layout().addWidget()`` 不接受 None。
        """
        t0 = time.perf_counter()
        try:
            cls = _load_auto_vision_page()
            page = cls(self, self)      # (app, parent) 均为 MainWindow
            try:
                page.installEventFilter(self)
            except Exception:  # noqa: BLE001
                pass
            _perf_note("自动化页惰性构造完成：%.2fs"
                       % (time.perf_counter() - t0))
            return page
        except Exception as e:  # noqa: BLE001 —— 起不来绝不影响主程序
            _perf_note(f"自动化页构造失败（不影响既有功能）：{e}")
            ph = QWidget(self)
            lay = QVBoxLayout(ph)
            lay.setContentsMargins(30, 30, 30, 30)
            lb = BodyLabel("「自动化」页当前不可用（视觉引擎未就绪），"
                           "详见 logs\\startup.log", ph)
            lb.setAlignment(Qt.AlignCenter)
            lay.addWidget(lb)
            return ph

    def _build_auto_page(self):
        """确保「自动化」页可用（幂等）——按需路径的唯一入口。

        外壳模式下等价于 ``auto_page.ensure()``；真身已存在时直接返回。
        保留方法名，是因为 main() 的 `VT_SHOT_TAB=auto` 截图路径与 GUI 自检
        都从这里进。失败时返回占位控件（见 :meth:`_make_auto_page`）。
        """
        page = getattr(self, "auto_page", None)
        if page is None:
            return None
        if isinstance(page, _LazyPageShell):
            try:
                page.ensure()
            except Exception as e:  # noqa: BLE001
                _perf_note(f"自动化页构造失败（不影响既有功能）：{e}")
                return page.real
            return page.real
        return page

    def page_by_key(self, key):
        """按键取页面：download/library/subtitle/edit/settings 为导航页；
        merge/calib 定位到宿主页并切到对应子板块（供截图/外部跳转）。"""
        if key == "merge":
            self.download_page.seg.setCurrentItem("merge")
            self.download_page.stack.setCurrentIndex(1)
            return self.download_page
        if key == "calib":
            self.switchTo(self.subtitle_page)
            self.subtitle_page.switch_to_calib()
            return self.subtitle_page
        return {"home": self.home_page,
                "download": self.download_page, "library": self.library_page,
                "subtitle": self.subtitle_page, "edit": self.subtitle_edit_page,
                "pipeline": self.pipeline_page,
                "auto": self.auto_page,
                "harness": getattr(self, "harness_page", None),
                "settings": self.settings_page}.get(key)

    # ---------- 流水线（v1.14.0） ----------
    def _start_pipeline(self):
        """延迟启动目录感知 + 流水线（不拖慢首屏）。

        registry 监视「上次使用的下载目录 + data\\downloads」，变更事件接给
        VT_NO_PIPELINE=1 可完全关闭目录感知（自检/排障用）。

        2026-10-21（启动调度专项）：``MediaRegistry.start()`` 内部的首次
        ``refresh()`` 是**同步**的 ``os.walk`` + 逐文件 ``os.stat``。下载目录
        大时实测把主线程卡住 **6.18s**——这是「窗口出来了但点不动」的**最大
        单块**（比 SpinBox 探测 + 主题色全树刷新加起来还长），而且它排在
        2.5s 定时器上，正好落在用户刚想操作的时候。

        改法：首扫丢后台线程（纯文件 IO，内部有锁保护），扫完往 app.q 投
        ``pipe_ready``，主线程再 ``start()``——此刻 refresh 已命中缓存，只剩
        watcher / QTimer 装配（毫秒级）。⚠ 不能把整个 ``start()`` 丢后台：
        它要创建 QTimer，QTimer 必须在有事件循环的主线程创建。
        """
        if os.environ.get("VT_NO_PIPELINE"):
            return
        try:
            t0 = time.perf_counter()
            reg = mreg.MediaRegistry(use_watcher=True)
            _perf_note("pipeline[registry 构造] %.2fs"
                       % (time.perf_counter() - t0))
            pipe = pl.Pipeline(reg)
            _perf_note("pipeline[Pipeline 构造] %.2fs"
                       % (time.perf_counter() - t0))
            pipe.add_listener(lambda p: self.q.put(("pipe_state", p)))
            reg.add_listener(pipe.on_files_changed)
            self.pipeline_registry = reg
            self.pipeline = pipe
            # ⚠ 流水线页是惰性外壳：直接 `self.pipeline_page.attach(...)` 会经
            #   ``__getattr__`` **立刻构造整页**——实测 3.82s（QSS 冷缓存 +
            #   TabPage/LogView/SpinBox 组合），比首扫本身慢一个数量级，正是
            #   「刚进入点不动」的最大单块。改为登记延迟绑定：用户首次打开
            #   该页时才接上（defer 在 ensure() 之后执行）。
            self.pipeline_page.defer(lambda page: page.attach(pipe))
            _perf_note("pipeline[页 defer] %.2fs"
                       % (time.perf_counter() - t0))
            t0 = time.perf_counter()

            def _boot():
                try:
                    reg.refresh()          # 纯文件 IO，MediaRegistry 内部有锁
                except Exception:  # noqa: BLE001
                    pass
                _perf_note("pipeline[首扫] %.2fs（后台线程）"
                           % (time.perf_counter() - t0))
                self.q.put(("pipe_ready", None))

            threading.Thread(target=_boot, daemon=True,
                             name="pipeline-boot").start()
        except Exception:  # noqa: BLE001 - 流水线起不来绝不能影响主程序
            self._log_error(traceback.format_exc())

    def _on_pipe_ready(self, msg):
        """流水线首扫完成（bus 订阅）→ 回主线程装配 watcher + 补一次评估。

        此刻 refresh() 命中缓存，主线程只付毫秒级代价。原 _dispatch 的最后
        一个分支，阶段③收尾改为 bus 订阅。
        """
        try:
            self.pipeline_registry.start()
            self.pipeline.manual_evaluate()
        except Exception:  # noqa: BLE001
            self._log_error(traceback.format_exc())

    def closeEvent(self, e):
        try:
            dp = _lazy_real(getattr(self, "download_page", None))
            if dp is not None:
                dp.shutdown()
        except Exception:  # noqa: BLE001
            pass
        try:
            if getattr(self, "pipeline_registry", None) is not None:
                self.pipeline_registry.stop()
            if getattr(self, "pipeline", None) is not None:
                self.pipeline.close()
        except Exception:  # noqa: BLE001
            pass
        super().closeEvent(e)

    def open_engine_settings(self):
        """跳到统一设置页的「字幕引擎」分组（供其他页面调用）。"""
        self.switchTo(self.settings_page)
        self.settings_page.scroll_to_engine()

    def _apply_argv(self, argv):
        """命令行/拖入到程序图标的文件：提取链接填到下载页，或直接分派。

        v1.13.0：不再只认「含链接的文件」——视频/音频/字幕/目录也按类型
        分派（与拖进窗口同一套逻辑 `_handle_dropped_files`）。
        """
        args = [engine.clean_path(a) for a in (argv or [])]
        args = [a for a in args if a]
        if not args:
            return
        self._handle_dropped_files(args)

    # ---------- 文件拖入（v1.13.0） ----------
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):
        urls = e.mimeData().urls() if e.mimeData().hasUrls() else []
        paths = [u.toLocalFile() for u in urls if u.isLocalFile()]
        paths = [p for p in paths if p]
        if paths:
            # ⚠️ 必须**等 Drop 返回后再处理**（延后一帧）。分派里可能弹模态确认框，
            #    而此刻 OLE 拖放循环仍握着鼠标捕获、前台锁也在拖放源（资源管理器）
            #    手上 —— 直接在 Drop 回调里 exec() 出来的模态框会完全点不动，
            #    Esc/回车也没反应。延后一帧，拖放循环已结束，框就正常了。
            #    注意 paths 要在事件有效期内先取出（mimeData 出了事件就不可靠）。
            QTimer.singleShot(
                0, lambda ps=list(paths): self._handle_dropped_files(ps))
        e.acceptProposedAction()

    def _in_subtitle_workbench(self):
        """当前是否停在「字幕处理」页（引擎工作台，含其字幕校准子页）。

        边缘拖放分派要用它判断"该不该按字幕类型跳转"，而不是一律去字幕编辑。
        v2.1.0：首页（任务创建）也是同一套分派的入口——它就是原来工作台的
        第一个分段，拖字幕进来同样该按类型分流。
        """
        try:
            cur = self.stackedWidget.currentWidget()
            return cur is self.subtitle_page or cur is self.home_page
        except Exception:  # noqa: BLE001
            return False

    def _handle_dropped_files(self, paths):
        """把拖进窗口的文件按类型分派到对应页面（视频/音频/字幕/文档/目录）。

        优先级：目录 → 设为视频库目录；字幕/视频/音频 → 字幕编辑页载入；
        .url 或含链接的文本 → 下载页填链接；其余文档 → 用默认程序打开。
        一次拖入多个时取同类型第一个，逐类处理并给出汇总提示。
        """
        dirs, videos, audios, subs, docs = [], [], [], [], []
        for p in paths:
            if os.path.isdir(p):
                dirs.append(p)
                continue
            ext = os.path.splitext(p)[1].lower()
            if ext in SUBTITLE_EXTS:
                subs.append(p)
            elif ext in VIDEO_EXTS:
                videos.append(p)
            elif ext in AUDIO_EXTS:
                audios.append(p)
            else:
                docs.append(p)

        msgs = []
        # 0) 「音画合并 → 手动合并」子页在前台：音视频/字幕**就地**归位到拖放槽，
        #    与页面内 dropEvent 同一入口。拖到页面边缘 / 顶部导航条 / 窗口边框时
        #    MergePage 收不到 dragEnter，事件会冒泡到这里；此前一律跳「字幕编辑」，
        #    用户看到的就是"拖到边缘就跳页"（与 v1.15.8 给 CalibPage 补的兜底同理）。
        if ((videos or audios or subs)
                and self.merge_page is not None
                and self.merge_page.accept_media(videos + audios + subs)):
            msgs.append("已载入到音画合并（手动合并）")
            videos, audios, subs = [], [], []
        # 1) 目录 → 视频库
        if dirs:
            d = dirs[0]
            self.library_page.dir_edit.setText(d)
            self.library_page.refresh()
            self.switchTo(self.library_page)
            msgs.append(f"已把「{os.path.basename(d)}」设为视频库目录")
        # 2) 字幕/视频/音频 → 字幕编辑
        #    例外（v1.15.8）：正停在「字幕处理 → 字幕校准」子页时，字幕**就地**
        #    填进校准输入框、不跳页。CalibPage 只覆盖引擎工作台那块矩形，拖到
        #    页面边缘、顶部导航条、窗口边框时事件收不到它的 dragEnter，会冒泡
        #    到这里；此前一律 switchTo 到「字幕编辑」，用户看到的就是
        #    "字幕拖到边缘就跳页"。（混拖的视频/音频仍走原逻辑，与 CalibPage
        #    dropEvent 里"其它文件交全局分派"的处理保持一致。）
        # v1.16.4：字幕的落点按「当前所在页」决定 ——
        #   · 停在「字幕处理」页（引擎工作台，含其字幕校准子页）→ 走与
        #     「任务创建」**完全同一套**分派：双语 → 字幕校准、单语 → 字幕翻译；
        #   · 其他页面 → 原逻辑（字幕编辑）。
        # 此前一律 switchTo 到「字幕编辑」：拖到页面边缘 / 顶部导航条 / 窗口
        # 边框时（这些位置任务创建页收不到 dragEnter，事件冒泡到这里）就会
        # 莫名跳页，用户看到的就是"拖到边缘跳字幕编辑"。
        if subs:
            home = getattr(self.subtitle_page, "_engine_home", None)
            if home is not None and self._in_subtitle_workbench():
                try:
                    self.subtitle_page._dispatch_created_task(home, subs[0])
                    msgs.append("已载入到字幕处理：" + os.path.basename(subs[0]))
                    subs = []
                except Exception as e:  # noqa: BLE001
                    _perf_note(f"边缘拖放分派字幕失败：{e}")
        if subs or videos or audios:
            ed = self.subtitle_edit_page
            self.switchTo(ed)
            media = videos + audios
            if media:
                ed.load_media(media[0])
            if subs:
                ed.load_subtitle(subs[0])
            msgs.append("已载入到字幕编辑：" +
                        (os.path.basename(media[0]) if media else "") +
                        (" + " + os.path.basename(subs[0]) if subs else ""))
        # 3) 链接/文档
        for d in docs:
            url = None
            try:
                url = engine.extract_url(d)
            except Exception:
                url = None
            if url:
                self.download_page.url_edit.setText(url)
                self.switchTo(self.download_page)
                msgs.append(f"已从「{os.path.basename(d)}」提取链接")
            else:
                engine.open_folder(d)
                msgs.append(f"已用默认程序打开「{os.path.basename(d)}」")
        if msgs:
            try:
                InfoBar.success("已接收文件", "；".join(msgs[:3]), duration=5000,
                                position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            except Exception:
                pass

    # ---------- 消息泵 ----------
    def _pump(self):
        try:
            # 每轮限量排空：队列积压时一次性全量处理会把主线程连续占用数秒
            # （界面冻结脉冲），分批消化让每轮之间留出事件循环响应窗口。
            for _ in range(200):
                msg = self.q.get_nowait()
                self.bus.dispatch(msg)
        except queue.Empty:
            pass
        QTimer.singleShot(120, self._pump)

    @staticmethod
    def _log_error(text):
        try:
            os.makedirs(engine.LOGS_DIR, exist_ok=True)
            with open(os.path.join(engine.LOGS_DIR, "gui_errors.log"),
                      "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {text}\n")
        except OSError:
            pass


# ============================================================================
# 功能页 builder thunks（harness/自动化页仍在外部模块，经主窗口方法构造）：
# 注册表 GuiSpec.builder 指向这里。其余功能页的 builder 已直指定
# features/<id>/page.py:build_page，无需 thunk。
# ============================================================================
def _build_harness_page_entry(app):
    if not _HARNESS_IMPORT_OK:
        raise RuntimeError("harness 适配层不可用（_HARNESS_IMPORT_OK=False）")
    return app._make_harness_page()


def _build_auto_page_entry(app):
    return app._make_auto_page()