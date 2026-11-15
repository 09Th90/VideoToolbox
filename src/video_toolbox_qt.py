#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# @version 2.9.1
"""视频工具箱 GUI v1.11.0 —— Fluent 矢量界面
====================================================================
界面形态（v1.10.0 起，原 tkinter 界面退役）：
  · FluentWindow + 左侧 NavigationInterface 导航（顶部功能区 + 底部分隔项；
    v1.10.4 起新增底部「设置」入口，宽度按最长项文字自适应）；
  · 每页「标题区固定 + 内容滚动区」：内容放进 QScrollArea（水平滚动禁用，
    滚动区内一律不用自动换行标签，避免 heightForWidth 与滚动区互相触发重排），
    窗口最小尺寸不再被内容撑爆，任何屏幕尺寸下都完整可用；
  · 卡片内：标题 StrongBodyLabel / 说明 CaptionLabel / 控件行；
  · 全矢量渲染：图标为 FluentIcon 矢量字体图标，高分屏按逻辑像素缩放
    （AA_EnableHighDpiScaling + AA_UseHighDpiPixmaps + PassThrough 取整策略），
    100%/125%/150%/200% 任意缩放比例下表现一致、不发虚。
页面（v1.10.0 起共 5 个，v1.10.4 增加设置页共 6 个，B站投稿板块已移除）：
  视频下载 · 视频库 · 音视频合并 · 字幕处理（内嵌第三方字幕引擎）· 字幕校准 · 设置
v1.13.0 起合并为 5 个导航页：
  视频下载（含「音画合并」子板块）· 视频库 · 字幕处理（含「字幕校准」子板块）·
  字幕编辑 · 设置；「字幕优化与翻译」更名为「字幕翻译」。
  支持把文件（视频/音频/字幕/文档/链接）直接拖进窗口自动分派。
v1.13.0 变更要点：
  ① 文件拖入：窗口级 drag&drop，视频/音频/字幕/文档/目录按类型分派到对应页面
     （媒体→字幕编辑、字幕→字幕编辑、链接文本→下载页、目录→视频库、其余→
     默认程序），命令行拖入同一套逻辑；
  ② 字幕编辑全格式：打开媒体对话框与视频库扫描覆盖 av1 / h264 / h265 / x264
     等裸流及更多封装（libmpv 本身即可解，此前只是过滤串没放开）；
  ③ 页面合并：「音视频合并」更名「音画合并」并入「视频下载」页、「字幕校准」
     并入「字幕处理」页，均以页内分段（SegmentedWidget）切换；引擎工作台
     「字幕优化与翻译」更名「字幕翻译」；
  ④ 自适应布局：修复窗口缩小/跨 PPI 拖动后页面扭曲——视频库卡片网格重排
     立即收缩 holder、设置页内嵌引擎设置界面宽度跟随宿主（原硬编码 1000px）、
     输入行最小宽度收紧、屏幕/DPI 变化强制全页重排。
v1.19.1：修「中止下载没有真正生效」——v1.19.0 的取消只覆盖了下载进程一段，
  而任务实际要过 引导/提取/下载/兜底重试/换源/NPE解析/NPE下载/封面 八个阶段，
  其中提取(fetch_info_json)、NPE 解析、封面三处用的是 subprocess.run（跑满
  180s×4、(45+25)s×2、60s 超时），且这些子进程都没登记进 _procs ⇒ 取消按钮
  根本拿不到它们；`proc.kill()` 也只杀父进程，yt-dlp/ffmpeg fork 的孙进程继续
  写 .part、继续吃带宽；`with _EXTRACT_LOCK` 更是不可中断阻塞，排队等锁时取消
  毫无反应。现全阶段接通：run→Popen+轮询、新增 cancel/register 形参、所有
  子进程经 _register_proc 登记、改用 kill_process_tree（taskkill /F /T）、
  提取锁改可中断、退避改 sleep_cancellable、引导阶段抛 _CancelledEarly。
  另修 UI 回弹（on_dl_progress 无条件把状态写回「下载中」，把刚点完取消的
  界面顶回去 —— 用户判定「没生效」的直接观感）：取消时先置「取消中」，
  on_dl_progress/on_dl_log 对取消中/已取消/完成/失败直接丢弃。
  自检 `scripts/dev/_selftest_download_cancel.py` 29/29。
v1.19.0：下载可中止——任务列表新增「取消选中任务」：置取消标志 + 强杀
  yt-dlp/ffmpeg 子进程，下载/兜底重试/字幕各阶段都会即时响应，已取消任务清理
  .part/.ytdlp 等临时分片并标记「已取消」（可重新加入同一链接）。
v1.12.0：翻译链路修缮配套——任务取消立即停掉翻译/优化线程池（原先取消后台
  仍跑完剩余批次）；LLM 翻译并发上限 5（防 429 刷屏）；「启用 AI」关闭时翻译
  兜底不介入 LLM；新增 `apply_version.py`（版本号一键同步）与
  `apply_vc_official.py`（官方实现套用）。
v1.11.0：① 全局 AI 拆为两条**独立通道**（接口 A 工具箱 / 接口 B 字幕引擎与
  AI 校准，各自地址+密钥+模型，可分别测试）；② 设置页新增「ASR 语音识别
  （转录配置）」卡片（自有 ASR 服务 / 本地独立模型）与「AI 校准（Agent 级）」
  卡片（校准通道 / 分块条数 / 字符预算 / 输出上限）；③ 字幕校准页新增
  「AI 校准」开关与「再次校准」（Agent 流程：脚本基线 → 抽取 cue 表 →
  载入知识库 → 自行分块 → 逐块复校 → 证据校验 → 合并回填 → 独立校验）；
  ④ 字幕处理页提速：预热只导入 home_interface（设置界面按需懒加载）、预热
  时机提前到首帧之后、引擎界面构造 0.7s 级（diskcache 延迟化），耗时留痕在
  logs\\startup.log。
v1.10.8：设置收敛为「唯一全局设置页」——取消工具/引擎分段与独立引擎对话框；
 新增全局 AI（LLM）卡片，工具箱 AI 与字幕引擎共用一套密钥/接口（引擎内不再
 单独配 LLM）；引擎工作目录等默认位置全部强制到软件文件夹（不再落 C 盘）；
 新增校准知识同步开关与「立即同步」。校准知识仍保持 v1.10.7 对等并集同步：
 启动自动拉取合并、退出先并再推，多用户互不覆盖、收敛到全体条目并集。
v1.10.5：字幕校准页模式列表与脚本实际支持的 12 种模式对齐（去掉脚本已删除的
  --layout 开关）；退出时静默同步校准脚本到 GitHub（挂 aboutToQuit）。
线程模型沿用旧界面：后台线程只往 app.q 投消息，主线程用 QTimer 泵出后更新控件。
调试钩子（供打包验证/截图）：VT_GUI_SELFTEST=1 自检自退；VT_SHOT_TAB/VT_SHOT_FILE 截图。
"""

import contextlib
import hashlib
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time

# 启动计时起点（2026-10-21 启动调度专项）：
# main() 里的 _T0 只能覆盖 QApplication 之后的链路，本文件第 130 行起的顶层
# import 树（PySide6 / vt_fluent / video_toolbox / subtitle_editor…）实测
# ≈0.7s（源码态），全部落在计时盲区里——用户体感的「双击到能点」与日志数字
# 对不上，根因就在这。这里在任何重 import **之前**落一个起点，main() 首行
# 把差值写进 logs\startup.log（[BOOT+x.xxx s] 行）。
_BOOT_T0 = time.perf_counter()




import traceback
import unicodedata
from collections import deque
from datetime import datetime


# ============================================================================
# ⚠⚠ 必须在**任何 PySide6 导入之前**执行：修 MSVC 运行时的 DLL 遮蔽
# ----------------------------------------------------------------------------
# 历史背景（旧版 Qt5 绑定时代，2026-10-09 实测踩坑）：当时的绑定把 Qt5\bin
# 一并带入，其中自带一份旧版 msvcp140.dll / vcruntime140.dll（14.26.28720.3），
# 而系统 System32 里的是 14.50.35719.0。QtCore 一导入就把 Qt5\bin 加进
# DLL 搜索路径，于是**旧版把系统新版顶掉**；onnxruntime 的 pyd 是按新版 MSVC
# 运行时编译的，之后加载就报：
#     ImportError: DLL load failed while importing onnxruntime_pybind11_state:
#     动态链接库(DLL)初始化例程失败。
# 解法：先把 System32 的运行时按文件名装进进程——同名 DLL 已在进程里时
# Windows 直接复用，旧副本就没机会被选中。开销可忽略（几次 WinDLL）。
#
# PySide6 迁移后（2026-10-14）：实测 PySide6 已**不自带** MSVC runtime
# （Qt6 各目录下均无 MSVCP140* / VCRUNTIME140*），该冲突的根源随之消失，
# 本函数成为无害的防御性冗余——**保留**（零成本），调用时机也不变
# （仍在任何 Qt 导入之前）。详见 docs/PySide6迁移方案书 第四节。
#
# 影响面：声纹筛选（`speaker_voiceprint` 依赖 onnxruntime）。**将来任何引入
# onnxruntime 的功能都受这条约束——别把这段挪到 PySide6 导入之后。**
# ============================================================================
def _fix_msvc_runtime_shadow():
    if os.name != "nt":
        return
    import ctypes
    sysdir = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                          "System32")
    for name in ("msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll",
                 "vcruntime140.dll", "vcruntime140_1.dll", "concrt140.dll"):
        p = os.path.join(sysdir, name)
        if not os.path.isfile(p):
            continue
        try:
            ctypes.WinDLL(p)      # 已加载过同名模块时是 no-op
        except OSError:
            pass


_fix_msvc_runtime_shadow()

from PySide6.QtCore import (Qt, QTimer, QEvent, QObject, QPoint, QRect, QRectF,
                          QSize, QUrl, QAbstractNativeEventFilter, Signal,
                          QLockFile)
from PySide6.QtGui import (QColor, QDesktopServices, QFont, QFontMetrics,
                         QGuiApplication, QIcon, QKeyEvent, QKeySequence,
                         QPainter, QPen, QPixmap, QShortcut, QTextCursor)
from PySide6.QtWidgets import (QAbstractButton, QAbstractItemView, QApplication,
                             QDialog, QFileDialog, QFrame, QGridLayout,
                             QHBoxLayout, QHeaderView, QLabel, QMessageBox,
                             QPlainTextEdit, QSizePolicy, QSplitter,
                             QStackedWidget, QTableWidgetItem, QTabWidget,
                             QVBoxLayout, QWidget)

from vt_fluent import (BodyLabel, CardWidget, CaptionLabel,
                       ComboBox, FluentIcon as FIF,
                       FluentWindow, InfoBar, InfoBarPosition, LineEdit,
                       ListWidget, MessageBox, NavigationItemPosition,
                       NavigationWidget, PasswordLineEdit, PrimaryPushButton,
                       ProgressBar, PushButton, ScrollArea, SegmentedWidget,
                       Slider, SimpleCardWidget, SpinBox, SubtitleLabel,
                       StrongBodyLabel, SwitchButton, TableWidget, TextEdit,
                       Theme, TitleLabel, ToolButton, setTheme, setThemeColor)

import video_toolbox as engine
# 视频切片（v2.10.0）：纯标准库模块（解析 / 切分 / 逐段校验），GUI 与 CLI 共用。
# 与 subtitle_compose 同思路——独立成模块、不反向 import 本文件，无循环导入。
import video_split as vsplit
# yt-dlp 单轨/合并临时文件识别与清理（私有 helper，facade 不导出）：
# 下载成功后补删 .fNNN / .temp 残留，避免片源目录多出无音轨大文件。
from core.download.ytdlp_util import (
    _finished_video as _dl_finished_video,
    _track_leftovers as _dl_track_leftovers,
)
# 流水线（v1.14.0）：目录感知 + 阶段调度。两个模块都是引擎侧（无 Qt 控件依赖），
# UI 只订阅它们抛出的状态，跨线程一律走 app.q。
import media_registry as mreg
import pipeline as pl
# 界面美化：各导航板块自定义背景图（配置持久化在 data/ui_custom.json）
import ui_theme
# Qt 兼容补丁（2026-10-14）：Qt 6.12.0 的 QStyleSheetStyle 回归会让
# qfluentwidgets 的 SpinBox 数值全空白（见 qt_compat.install_spinbox_fix）
import qt_compat
# 字幕编辑（打轴）三件套：纯逻辑 / 媒体后端 / 控件。
# 页面类暂仍在本文件；壳基建（ScrollPage/card/…）已下沉 vt_app/，
# 「页面反向 import 入口会循环」的障碍已消除——阶段③逐页拆到
# features/<id>/page.py（只经 vt_app 基建 + 注册表服务取能力）。
import subtitle_editor_core as secore
from subtitle_editor import CueTable, SubtitlePropsPanel, WaveformTimeline
from subtitle_editor_media import MpvPlayer, WaveformCache
from subtitle_overlay import SubtitleStage
# 内嵌字幕对话框（原引擎工作台「字幕视频合成」那一段，v1.13.x 挪到这里）
from subtitle_compose import ComposeDialog
# 自动化页（v1.16.0）：视觉自动化 demo，参考 MAA 的「抓帧→识别→声明式任务→点击」。
# 单独成模块（自带卡片/滚动壳），因此**不反向 import 本文件**，无循环导入。
# 2026-10-20 启动优化：该模块顶层拖入 numpy/PIL/视觉引擎（实测合计 ≈364ms），
# 却只服务「自动化」一个导航页——改为惰性加载，首帧后约 1.5s 才构造页面
# （导航项随之晚现，NAV_TEXTS 静态文案不变所以导航宽度无感），
# 构造入口见 MainWindow._build_auto_page。
def _load_auto_vision_page():
    """惰性导入 auto_vision_page，返回其页面类（重依赖只在这里付一次）。"""
    import auto_vision_page
    return auto_vision_page.AutoVisionPage
# 程序更新（v2.0.0）：与自研在线安装器（packaging\online_release）之间的
# 接线层——只做检测/决策/自替换委托，下载逻辑复用安装器侧已验证的实现。
# 该模块对「在线发布组件缺失」是**静默降级**（返回 None 能力），所以
# 这里 import 本身不会因分发形态而失败。
import vt_update_check
# ============================================================================
# GUI 壳基础设施（2026-11-15 功能解耦阶段②）：原 INFRA 已下沉 vt_app/
# （boot / widgets / scheduler / lazy_shell / engine_ui / win_resize / bus），
# 代码逐字同源、行为零变化；下面把名字再导出进本模块命名空间，文件内
# 100+ 调用点零改动。页面拆出（阶段③）后一律改 `from vt_app… import`。
# ============================================================================
from vt_app.boot import (CRASH_LOG, _FAULT_STATE, _apply_app_icon,
                         _crash_log_write, _crash_toast, _ensure_hidden_stdio,
                         _install_faulthandler, _perf_note,
                         _process_age_seconds, _start_startup_sync_threads,
                         configure_qt_plugins, install_crash_guard)
from vt_app.widgets import (NAV_BUTTON_W, NAV_ICON_TEXT_GAP, NAV_SIDE_PADDING,
                            NAV_TEXT_TAIL, AccentDot, LogView, PageBase,
                            ScrollPage, TabPage, _MergeDropSlot, card,
                            expand_h, fit_caption, fit_spin, label_row,
                            nav_width_for, row, srow, tab_caption)
from vt_app.scheduler import _SCHED, _StartupScheduler, _defer
from vt_app.lazy_shell import (_SPINBOX_FIX_STATE, _LazyPageShell,
                               _install_spinbox_fix_once, _lazy_real)
from vt_app.engine_ui import (_ENGINE_PREWARM, _ENGINE_UI_DECISION,
                              _engine_prewarm_done, _engine_prewarm_probe,
                              _engine_prewarm_work, _lower_thread_priority,
                              _resolve_engine_ui, _start_engine_prewarm)
from vt_app.win_resize import RESIZE_MARGIN, _ResizeHitFilter
from vt_app.bus import MessageBus
from features import resolve as _feature_resolve
# 功能解耦阶段③（第一批）：已拆出页面与共享媒体常量的兼容再导出。
# 页面真身在 features/<id>/page.py（只经 vt_app 基建 + 注册表服务），
# 本文件保留旧名，存量调用方（自检/截图/拖放分派）零改动。
from features._media import (AUDIO_EXTS, AUDIO_FILE_FILTER, MEDIA_FILE_FILTER,
                             SUB_FILE_FILTER, SUBTITLE_EXTS, VIDEO_EXTS,
                             VIDEO_FILE_FILTER)
from features.library.page import (CARD_W, LIB_EXTS, THUMB_DIR, THUMB_H,
                                   THUMB_W, LibraryPage, fmt_hms,
                                   thumb_cache_name)
from features.merge.page import MergePage
from features.split.page import SplitPage
from features.calibrate.page import CalibPage
from features.pipeline.page import PipelinePage
from features.subtitle_edit.page import ConfirmDialog, SubtitleEditPage
from features.download.page import DownloadPage
from vt_app.settings_page import (AsrExampleDialog, SettingsPage,
                                   UpdateProgressDialog, _BgPathEdit,
                                   _InnerScrollToContent)
from features.workbench.page import (SubtitlePage,
                                       _has_non_zh_letters,
                                       iter_subtitle_cues,
                                       make_task_creation_drop_handler,
                                       subtitle_looks_bilingual)
# AI 托管（v2.1.0）：harness 适配层 + 托管页。两者都设计成「harness 不在场
# 也零影响」——bridge 只依赖标准库、探测失败只返回状态；页面也只在
# ``harness_bridge.available()`` 为真时才创建并挂导航。import 本身依旧兜底，
# 确保任何意外都不会拖垮既有功能。
try:
    import harness_bridge
    import harness_page as _harness_page_mod
    _HARNESS_IMPORT_OK = True
except Exception as _e:  # noqa: BLE001
    harness_bridge = None
    _harness_page_mod = None
    _HARNESS_IMPORT_OK = False
    try:
        _perf_note(f"harness 模块导入失败（不影响既有功能）：{_e}")
    except Exception:  # noqa: BLE001
        pass

VERSION = "2.9.1"
# 更新检查同时服务源码运行与安装版：以界面显示的 VERSION 为唯一运行版本，
# 避免 vt_update_check 里的独立常量再次漂移。
vt_update_check.SELF_VERSION = VERSION

# 全格式媒体/字幕/文档扩展名（v1.13.0）：
#   视频：常见容器 + av1 / h264 / h265 / x264 等裸流与更多封装；
#   音频：常见音频容器；
#   字幕：常见字幕文本格式。
# 这些集合既用于「视频库」扫描，也用于「把文件拖进程序」时的类型分派。































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
        # 功能解耦阶段②：消息总线（订阅式路由）。页面拆出后各自
        # bus.subscribe(前缀, handler)；未认领的消息回退旧 _dispatch 路由表。
        self.bus = MessageBus(self.q, fallback=self._dispatch,
                              on_error=self._log_error)
        self.setWindowTitle(f"视频工具箱 v{VERSION}")
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
        # 各 features/<id>/feature.py，builder 指向本文件 thunks（阶段③页面
        # 拆出后改指 features/<id>/page.py:build_page）。行为与旧硬编码逐项
        # 一致：惰性外壳 / 常驻真身（lazy=False）/ 底部导航 / 分隔线，
        # objectName 与挂载顺序不变；功能缺席或 builder 失败只跳过该页
        # （降级模式①：导航缺席 + startup.log 留痕），绝不影响其它页。
        _reg = _feature_resolve("features:registry")()
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
                f"视频工具箱 v{VERSION}" + (f" — {suffix}" if suffix else ""))
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
        #    填进校准输入框、不跳页。CalibPage 只覆盖引擎工作台那一块矩形，拖到
        #    页面边缘 / 顶部导航条 / 窗口边框时事件收不到它的 dragEnter，会冒泡
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

    def _dispatch(self, msg):
        """旧路由表（bus 未认领消息的 fallback）。

        2026-11-15 功能解耦阶段③：业务消息已全部由功能页/设置页 bus 自订阅。
        本表只剩 pipe_ready（流水线装配，属 MainWindow 壳层编排）；待主窗口
        拆出时改为 bus 订阅，本表整体删除。
        """
        kind, args = msg[0], msg[1:]
        try:
            if kind == "pipe_ready":
                # 首扫已在后台完成（见 _start_pipeline）→ 回主线程装配
                # watcher + QTimer，并补一次评估。此刻 refresh() 命中缓存，
                # 主线程只付毫秒级代价。
                try:
                    self.pipeline_registry.start()
                    self.pipeline.manual_evaluate()
                except Exception:  # noqa: BLE001
                    self._log_error(traceback.format_exc())
        except Exception as e:
            import traceback
            self._log_error(traceback.format_exc())
            InfoBar.error("界面更新出错", str(e)[:200], duration=5000,
                          position=InfoBarPosition.BOTTOM_RIGHT, parent=self)

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
# 功能页 builder thunks（2026-11-15 功能解耦阶段②）：注册表 GuiSpec.builder
# 指向这里；阶段③页面拆出后把指向改到 features/<id>/page.py:build_page，
# 并删除本文件对应 thunk。
# ============================================================================
def _build_download_page(app):
    return DownloadPage(app, app)


def _build_library_page(app):
    return LibraryPage(app, app)


def _build_subtitle_page(app):
    return SubtitlePage(app, app)


def _build_subtitle_edit_page(app):
    return SubtitleEditPage(app, app)


def _build_pipeline_page(app):
    return PipelinePage(app, app)


def _build_harness_page_entry(app):
    if not _HARNESS_IMPORT_OK:
        raise RuntimeError("harness 适配层不可用（_HARNESS_IMPORT_OK=False）")
    return app._make_harness_page()


def _build_auto_page_entry(app):
    return app._make_auto_page()


def main():
    _T0 = time.perf_counter()   # 全链路计时起点，各阶段痕迹写 logs/startup.log
    _ensure_hidden_stdio()
    # 顶层 import 盲区（2026-10-21 启动调度专项）：_BOOT_T0 落在本文件第 83 行
    # 的 import 之间，覆盖 PySide6 / vt_fluent / video_toolbox 等全部重导入。
    # 没有这一行时，「双击到窗口可见」的真实总时长永远无法从日志还原——
    # 日志里的 T+1.0s 只是 main() 之后的那一段。
    _boot = _T0 - _BOOT_T0
    _proc_age = _process_age_seconds()
    _unpack = ""
    _mp = getattr(sys, "_MEIPASS", None)
    # 只有 onefile 的 _MEI* 临时解包目录才有「解包墙钟」语义；onedir 的
    # _MEIPASS 指向安装目录，ctime 可能是几个月前，误报成启动耗时。
    if _mp and os.path.basename(os.path.normpath(_mp)).lower().startswith("_mei"):
        try:
            _unpack = ("，_MEIPASS 解包后墙钟 %.3fs"
                       % (time.time() - os.path.getctime(_mp)))
        except OSError:
            pass
    _perf_note(f"[BOOT+{_boot:6.3f}s] 顶层 import 完成"
               f"（frozen={bool(getattr(sys, 'frozen', False))}{_unpack}）")
    if _proc_age is not None:
        _perf_note(f"[PROC] 进程创建→main {_proc_age:.3f}s")
    # GIL 切换间隔压到 1ms（默认 5ms）：后台线程（校准/声纹同步、引擎预热）
    # 与主线程抢 GIL 时，主线程每次获得 GIL 的最长等待从 5ms 降到 1ms——
    # 首帧 paint 的 Python 回调动辄几百次，累计差距就是「窗口秒现」与
    # 「窗口 10s 级才现」的区别（2026-10-20 启动专项实测）。
    try:
        sys.setswitchinterval(0.001)
    except Exception:
        pass
    # 运行期环境准备（v1.10.6）：必须在任何 videocaptioner 导入之前执行——
    # 1) 把字幕引擎在系统盘的历史数据迁移到数据根目录；
    # 2) 重定向引擎的路径常量（否则它会写 %LOCALAPPDATA%，即 C 盘）；
    # 3) 把临时目录指向数据根目录，避免中间产物落系统 Temp。
    engine.prepare_runtime_env()
    _perf_note(f"[T+{time.perf_counter()-_T0:6.3f}s] prepare_runtime_env 完成")
    # 翻译服务归一**不在这里重复做**（2026-10-20 性能优化）：JSON 层的
    # 「LLM 大模型翻译 → 微软翻译」归一已由上面的 prepare_runtime_env() 经
    # vc_prepare_settings_file()（core/asr/runtime_patches.py）先行完成，
    # 引擎界面首帧后才在预热线程里读盘，拿到的就是归一后的值。
    # 早先这里还要逐个 import videocaptioner 的 core.entities 与
    # ui.common.config 做内存态归一——后者导入链实测 6.3s（整库拖入），
    # 而内存态在启动时根本还没加载，纯属白付；设置页懒加载路径
    # （SettingsPage._ensure_engine_setting）另留着同款兜底。
    # 未捕获异常兜底：装上后 Qt 槽里的异常只记日志 + 提示，不会再让进程 abort
    install_crash_guard()
    # 引擎 UI 树预热**不能在建窗前起**（2026-10-20 实测：与建窗抢 GIL，
    # 首帧从 0.1s 劣化到 9.9s）——改到首帧之后、主线程空闲时启动，
    # 见 show() 后的 _defer_after_show。
    # 启动即拉取最新校准知识并入本地（v1.10.7 多用户收敛的「拉」半程；
    # 后台 daemon 线程，失败静默记 logs/calib_sync.log）
    # 2026-10-23 起改为首页就绪后由 _defer("startup_sync") 启动。
    # 声纹模板同步是**独立通道**（src\voiceprint_sync.py，与校准知识同步互不
    # 干涉：不共用子进程/日志/状态目录），单独一条后台线程，失败静默记
    # logs\vp_sync.log
    configure_qt_plugins()
    _perf_note(f"[T+{time.perf_counter()-_T0:6.3f}s] 启动任务已登记"
               "（后台同步延后）")
    # 矢量化：高分屏缩放与矢量图标在 Qt6 已默认启用（AA_EnableHighDpiScaling /
    # AA_UseHighDpiPixmaps 已废弃，无需再设置）
    # 缩放比不取整：125% / 150% 等非整数倍率下按实际比例换算，
    # 否则 Qt 会把 1.25 四舍五入成 1.0 或 2.0，不同显示器间表现不一致
    try:
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    except Exception:
        pass
    app = QApplication(sys.argv)
    # 启动画面：onedir 冷缓存/杀软扫描仍可能有 1～2s 无界面期，先给即时反馈。
    # 不读大图（QPixmap 现画），自检/截图/显式关闭时跳过。
    splash = None
    if not (os.environ.get("VT_NO_SPLASH")
            or os.environ.get("VT_GUI_SELFTEST")
            or os.environ.get("VT_SHOT_FILE")):
        try:
            from PySide6.QtWidgets import QSplashScreen
            _pm = QPixmap(460, 240)
            _pm.fill(QColor("#1F6F4F"))
            _pt = QPainter(_pm)
            _pt.setPen(QColor("#FFFFFF"))
            _pt.setFont(QFont("Microsoft YaHei UI", 20, QFont.Bold))
            _pt.drawText(_pm.rect().adjusted(0, 48, 0, 0),
                         Qt.AlignHCenter | Qt.AlignTop, "视频工具箱")
            _pt.setPen(QColor("#E6F4EC"))
            _pt.setFont(QFont("Microsoft YaHei UI", 10))
            _pt.drawText(_pm.rect().adjusted(0, 112, 0, 0),
                         Qt.AlignHCenter | Qt.AlignTop, "正在启动 …")
            _pt.end()
            splash = QSplashScreen(_pm)
            splash.show()
            app.processEvents()
        except Exception:  # noqa: BLE001
            splash = None
    # 启动任务调度器（2026-10-21）：必须早于 MainWindow 构造——建窗期与首帧后
    # 注册的后台任务都走它。timer 挂在 app 上，生命周期覆盖全进程。
    # VT_NO_SCHED=1 关闭调度器（退回逐个 singleShot），仅用于性能对照测量。
    if not os.environ.get("VT_NO_SCHED"):
        _SCHED["inst"] = _StartupScheduler(app)
    _perf_note(f"[T+{time.perf_counter()-_T0:6.3f}s] QApplication 就绪")
    # 基底样式（2026-10-20 启动 <5s 专项）：Windows 11 原生样式由**插件**
    # 提供，首个控件 polish 时初始化实测 ≈0.8s（开发态）/ ≈1.5s（frozen，
    # 插件 DLL 从 _MEI 新文件读取 + 三套杀毒扫描），是启动最大单块。
    # 内置样式（Fusion / windowsvista）只要 ≈24ms——本应用控件观感由
    # vt_fluent 的 QSS（QStyleSheetStyle 包裹基底）主导，基底只影响
    # QSS 未覆盖的原生子控件与原生对话框。
    #   默认 fusion（快）；VT_BASE_STYLE=windows11 可恢复原生观感。
    try:
        from PySide6.QtWidgets import QStyleFactory as _QSF
        _bs = (os.environ.get("VT_BASE_STYLE") or "fusion").strip().lower()
        if _bs in ("windows11", "default"):
            pass                      # 显式要原生：什么都不做（Qt 默认）
        elif _bs in ("fusion", "windowsvista", "windows", "macintosh"):
            app.setStyle(_QSF.create(_bs))
    except Exception:
        pass
    # QSS 库 app 级兜底（v2.3.1）：QToolTip/QMenu/QMessageBox 是独立顶层
    # 窗口，套在业务控件子树上的样式表管不到——这里在 QApplication 级
    # 应用 vt_fluent 的兜底 QSS（令牌化，主题/主题色切换自动重应用）。
    # ⚠ 必须在 MainWindow 构造**之前**设置（2026-10-20 实测反证：放到首帧
    # 之后时树已建满，一次全应用 re-polish 要 8.7s；此刻树是空的，代价≈0）。
    from vt_fluent import applyAppStyleSheet
    applyAppStyleSheet(app)
    # Qt 兼容补丁（2026-10-14）：必须在任何 SpinBox 被创建之前打上。
    # 2026-10-20 启动专项：探测函数会建一个真 SpinBox 并跑一轮布局
    # （实测 0.6s，其中含一次性 QStyle 初始化）——原先压在建窗前的关键
    # 路径上。现在**三个重页惰性化**之后，首帧前不存在任何 SpinBox，
    # 探测改到首帧后的 singleShot(0) 里跑（排在引擎预热的 singleShot(0)
    # 之前）；外壳 ensure() 与引擎工作台构建前也会兜底调一次（幂等），
    # 任何路径上「先建 SpinBox、后打补丁」都不会发生。
    # 应用图标（v2.1.0）：挂在 QApplication 上，**所有**窗口（含各对话框、
    # 日志查看器、以及引擎回退路径自己起的那些）都跟着有图标——挂到
    # MainWindow 上只管主窗口，对话框会是空白图标。
    # 2026-10-20：主窗口先 setWindowIcon（见建窗处），app 级图标延后到首帧后。
    try:
        _icon_path = engine.app_icon_path()
        if _icon_path:
            app.setWindowIcon(QIcon(_icon_path))
    except Exception:
        pass
    # 单实例守卫（v1.13.4）：两个实例会各自持有一份内存配置并写穿同一个
    # data\ 目录（ui_custom.json / config.json…），表现为「设置过一会儿自动
    # 复原」「这边改了那边不生效」——正是多窗口交叠写入的典型症状。
    # QLockFile 在进程存活期间持有锁；崩溃残留的锁会按锁内 PID 校验存活后放行。
    _single_lock = QLockFile(os.path.join(engine.DATA_DIR,
                                          "videotoolbox.single.lock"))
    _single_lock.setStaleLockTime(0)
    # 50ms 足够——真正被占用时 QLockFile 会按锁内 PID 判活，超时后走提示分支；
    # 200ms 只是白等（2026-10-20 启动优化）。
    if not _single_lock.tryLock(50):
        QMessageBox.information(
            None, "视频工具箱已在运行",
            "检测到另一个视频工具箱窗口正在运行，本次启动已取消。\n\n"
            "同时运行两个实例会互相覆盖配置（例如「界面美化」的设置会被"
            "另一边的旧值写回，看起来像\"自动复原\"）。\n\n"
            "请改用已打开的窗口；若找不到它，可先在任务管理器结束旧的"
            " python.exe / pythonw.exe 再启动。")
        return
    # 界面美化（v1.13.x）：主题档/主题色读自 data/ui_custom.json（设置页可改），
    # 全局 QSS（输入框/菜单/工具提示/滚动条/进度条）在这里一并挂上
    ui_theme.apply_startup_theme(app)
    _perf_note(f"[T+{time.perf_counter()-_T0:6.3f}s] 启动主题应用完成")
    app.setFont(QFont("Microsoft YaHei UI", 9))   # 9pt 紧凑正文，高分屏随缩放走
    window = MainWindow(sys.argv[1:])
    _perf_note(f"[T+{time.perf_counter()-_T0:6.3f}s] MainWindow 构造完成")
    _perf_note(f"[T+{time.perf_counter()-_T0:6.3f}s] fit_to_screen 开始")
    window.fit_to_screen()
    _perf_note(f"[T+{time.perf_counter()-_T0:6.3f}s] fit_to_screen 完成")

    shot_tab = os.environ.get("VT_SHOT_TAB")
    if shot_tab:
        if shot_tab == "auto":
            window._build_auto_page()   # 惰性页：截图/外部跳转必须同步就位
        page = window.page_by_key(shot_tab)
        if page:
            QTimer.singleShot(700, lambda: window.switchTo(page))
    shot_file = os.environ.get("VT_SHOT_FILE")
    if shot_file:
        def _shot():
            # 只抓本窗口：QScreen.grabWindow(传窗口句柄) 走 PrintWindow，即使被遮挡
            # 也只渲染本窗口，不会把桌面上其它应用的内容截进来（传 0 才是抓屏幕区域）。
            #
            # v1.11.0 修正：刚切换到「字幕处理」这类需要当场构建的重页面时，
            # DWM 尚未提交新帧，PrintWindow 会返回切换前的旧画面（实测截到的是
            # 上一个页面）。这里先强制重绘本窗口再抓，仍为空才回退 QWidget.grab()。
            try:
                window.repaint()
            except Exception:
                pass
            # VT_SHOT_MODE=qt 时改用 QWidget.grab()（纯 Qt 渲染）。
            # PrintWindow 会抓到 DWM 尚未提交的旧帧，窗口刚重排完时尤其明显——
            # 表现为画面上叠着''上一版''的控件（像是控件重复了一份）。
            scr = QApplication.primaryScreen()
            if os.environ.get("VT_SHOT_MODE") == "qt":
                pm = window.grab()
            else:
                try:
                    pm = scr.grabWindow(int(window.winId()))
                except Exception:
                    pm = None
                if pm is None or pm.isNull():
                    pm = window.grab()
            pm.save(shot_file)
            print(f"[shot] saved: {shot_file}")
            QApplication.quit()
        # 页面切换后留足重建/重绘时间；重页面可用 VT_SHOT_DELAY 调到 3500+
        try:
            _delay = int(os.environ.get("VT_SHOT_DELAY") or 2600)
        except ValueError:
            _delay = 2600
        QTimer.singleShot(_delay, _shot)
    if os.environ.get("VT_GUI_SELFTEST"):
        def _ok():
            try:
                with open(os.path.join(engine.DATA_DIR, "GUI_SELFTEST_OK"), "w",
                          encoding="utf-8") as f:
                    f.write("ok:" + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            except OSError:
                pass
            QApplication.quit()
        QTimer.singleShot(2600, _ok)

    # 退出时同步校准脚本到 GitHub（静默后台，不阻塞退出、不弹窗）
    # 用 aboutToQuit 而非 closeEvent：覆盖菜单退出/自检退出等所有路径；
    # 内部再派生独立子进程，主进程退出后子进程仍能跑完。
    app.aboutToQuit.connect(engine.sync_calib_on_exit)
    # 声纹增量的退出推送（独立通道；纯本地文件写、不派生子进程，失败只记
    # logs\vp_sync.log，不阻塞退出）
    app.aboutToQuit.connect(engine.sync_voiceprint_on_exit)
    # 释放 libmpv：不释放的话进程退出后 onefile 的 _MEI*** 临时目录删不掉
    # （2026-10-20：字幕编辑页改惰性外壳，这里只在**真构造过**时才调，
    #  避免为了接这一条线在启动期把整页建出来）
    def _shutdown_subtitle_edit():
        page = getattr(window, "subtitle_edit_page", None)
        real = getattr(page, "real", None)
        if real is not None:
            try:
                real.shutdown()
            except Exception:
                pass
    app.aboutToQuit.connect(_shutdown_subtitle_edit)

    window.show()
    if splash is not None:
        try:
            splash.finish(window)
        except Exception:  # noqa: BLE001
            pass
    _perf_note(f"[T+{time.perf_counter()-_T0:6.3f}s] show() 返回")

    # UI 心跳探针（2026-10-21，仅 VT_SCHED_TRACE=1）：每 50ms 记一次时间，
    # 实际间隔 - 50ms ≈ 主线程被占用的时长。这是「点不动」的直接量化指标
    # ——用户点击时若主线程正卡在某个同步块里，事件就要排队等这么久。
    if os.environ.get("VT_SCHED_TRACE"):
        _hb = {"t": time.perf_counter(), "max": 0.0, "stop": False}

        def _beat():
            # ⚠ 退出路径（aboutToQuit 里的派生/清理）可能阻塞数秒甚至十几秒
            #   （网络慢时实测 19s），那不是用户体感，必须停掉心跳。两个判据
            #   都用：stop 由 aboutToQuit 槽置位，closingDown() 覆盖槽顺序
            #   在前的场景。
            try:
                if _hb["stop"] or QApplication.closingDown():
                    return
            except Exception:  # noqa: BLE001
                if _hb["stop"]:
                    return
            now = time.perf_counter()
            gap = (now - _hb["t"]) * 1000.0
            if gap > _hb["max"]:
                _hb["max"] = gap
                if gap >= 150.0:
                    _perf_note(f"ui[心跳] 主线程被占用 {gap:.0f}ms"
                               f"（T+{now - _T0:.2f}s）")
            _hb["t"] = now
            QTimer.singleShot(50, _beat)

        # ⚠ 退出路径（aboutToQuit 里的同步派生/清理）动辄数秒，必须停掉心跳，
        #   否则会报一条误导性的「主线程被占用 3xxx ms」——那不是用户体感。
        try:
            app.aboutToQuit.connect(lambda *_: _hb.__setitem__("stop", True))
        except Exception:  # noqa: BLE001
            pass
        QTimer.singleShot(50, _beat)
    window.raise_()
    _perf_note(f"[T+{time.perf_counter()-_T0:6.3f}s] raise_() 返回")
    _perf_note(f"[T+{time.perf_counter()-_T0:6.3f}s] 窗口首帧可见")

    # 首帧后再补：app 级图标 + SpinBox 兜底安装（2026-10-20 启动优化）。
    # 2026-10-21（启动调度专项）：原来这里是三个 singleShot(0) 在同一轮事件
    # 循环里连发——SpinBox 探测 ≈0.6s 直接顶在首帧后面，用户「一点就卡」。
    # 现在全部改走调度器：
    #   · app_icon    —— 40ms 预算，很轻；
    #   · spinbox_fix —— 建真 SpinBox 跑一轮布局 ≈0.6s，**solo 预算 900ms**，
    #     并延后到 800ms：此时首帧已稳定；任何真正需要它的路径
    #     （_build_now / 惰性页 ensure）都会自己幂等兜底调用，不会漏。
    # ⚠ 引擎预热不在这里注册：MainWindow.__init__ 已登记 ``prewarm_kick``
    #   → subtitle_page.prewarm()（它除了起线程还要登记 build_engine 任务，
    #   同名任务在调度器里是幂等的，此处重复注册会被忽略）。
    _defer("app_icon", lambda: _apply_app_icon(app), 0, 20, budget_ms=40)
    _defer("spinbox_fix", _install_spinbox_fix_once, 2000, 10,
           depends_on=("home_ui",), budget_ms=900)
    # 校准/声纹同步：首页可交互后再跑，避免 curl/gh/子进程与首屏抢资源。
    # 2026-11-14：由 3.5s → 9s → **25s**。实测 9s 起线程时，两条后台同步会在
    # T+13s / T+14s 各引发一次约 600–720ms 的 GIL 争用（网络请求与解析在主线程
    # 抢解释器锁），正好落在用户刚启动、开始操作的窗口里。同步晚一点没有功能
    # 影响，放到 25s 后并与 30s 的 import 预热错开。
    _defer("startup_sync", _start_startup_sync_threads, 25000, 95,
           depends_on=("home_ui",), budget_ms=1)
    # 技能包（AGENTS.md / SKILL.md 等 9 处）也从 import 期挪到这里。
    if harness_bridge is not None:
        _defer("agent_assets", harness_bridge.ensure_agent_assets, 3000, 90,
               depends_on=("home_ui",), budget_ms=200)

    # 启动自动检测更新（v2.0.0）：延迟 1.5s 起步，先让首屏渲染完再发网络
    # 请求；且由更新模块自己按 12 小时节流 + 用户拒绝记录决定要不要真查。
    # ⚠ 用 QTimer.singleShot 而不是直接调：直调会让检测线程与窗口首帧构建
    #   抢 GIL，表现为「启动那几秒界面卡一下」。
    # ⚠ 自检/截图模式一律不查：VT_GUI_SELFTEST 与 VT_SHOT_FILE 下自动退出，
    #   发起网络请求只会拖慢退出、污染结果。
    if not (os.environ.get("VT_GUI_SELFTEST")
            or os.environ.get("VT_SHOT_FILE")
            or os.environ.get("VT_NO_UPDATE_CHECK")):
        def _auto_update():
            try:
                window.settings_page.auto_check_update()
            except Exception:  # noqa: BLE001 —— 更新功能绝不影响主流程
                pass
        # 2026-10-21：顺延逻辑交给调度器的依赖（prewarm_done），不再自己
        # 400ms 轮询 25 次——网络请求与引擎导入同时抢 GIL 会拖慢任务框就绪。
        _defer("auto_update", _auto_update, 1500, 90,
               depends_on=("prewarm_done",), budget_ms=100)

    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
