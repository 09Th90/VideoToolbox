#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# @version 3.2.5
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
# 2026-11-15 模块独立文件夹：真身迁入 features/split/，此处兼容再导出。
import features.split.video_split as vsplit
# yt-dlp 单轨/合并临时文件识别与清理（私有 helper，facade 不导出）：
# 下载成功后补删 .fNNN / .temp 残留，避免片源目录多出无音轨大文件。
from core.download.ytdlp_util import (
    _finished_video as _dl_finished_video,
    _track_leftovers as _dl_track_leftovers,
)
# 流水线（v1.14.0）：目录感知 + 阶段调度。两个模块都是引擎侧（无 Qt 控件依赖），
# UI 只订阅它们抛出的状态，跨线程一律走 app.q。
import features.library.media_registry as mreg
import features.pipeline.pipeline as pl
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
from features.subtitle_edit.subtitle_editor import CueTable, SubtitlePropsPanel, WaveformTimeline
from features.subtitle_edit.subtitle_editor_media import MpvPlayer, WaveformCache
from features.subtitle_edit.subtitle_overlay import SubtitleStage
# 内嵌字幕对话框（原引擎工作台「字幕视频合成」那一段，v1.13.x 挪到这里）
from features.compose.subtitle_compose import ComposeDialog
# 自动化页（v1.16.0）：视觉自动化 demo，参考 MAA 的「抓帧→识别→声明式任务→点击」。
# 单独成模块（自带卡片/滚动壳），因此**不反向 import 本文件**，无循环导入。
# 2026-10-20 启动优化：该模块顶层拖入 numpy/PIL/视觉引擎（实测合计 ≈364ms），
# 却只服务「自动化」一个导航页——改为惰性加载，首帧后约 1.5s 才构造页面
# （导航项随之晚现，NAV_TEXTS 静态文案不变所以导航宽度无感），
# 构造入口见 MainWindow._build_auto_page。
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
# 壳层再导出（2026-11-15 阶段③）：首页/主窗口已拆到 vt_app，入口保留旧名，
# 自检/截图/外部脚本按 gui.MainWindow / gui.PAGE_TITLES 取用零改动。
from vt_app.home_page import HomePage
from vt_app.main_window import (GOLDEN_RATIO, PAGE_TITLES, MainWindow,
                                _build_auto_page_entry,
                                _build_harness_page_entry)
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

VERSION = "3.2.5"
# 更新检查同时服务源码运行与安装版：以界面显示的 VERSION 为唯一运行版本，
# 避免 vt_update_check 里的独立常量再次漂移。
vt_update_check.SELF_VERSION = VERSION

# 全格式媒体/字幕/文档扩展名（v1.13.0）：
#   视频：常见容器 + av1 / h264 / h265 / x264 等裸流与更多封装；
#   音频：常见音频容器；
#   字幕：常见字幕文本格式。
# 这些集合既用于「视频库」扫描，也用于「把文件拖进程序」时的类型分派。

































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
    # 声纹模板同步是**独立通道**（src\features\voiceprint\voiceprint_sync.py，与校准知识同步互不
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
    # 主线程挂起看门狗（2026-11-20）：>5s 没处理消息即 dump 全线程栈到
    # logs/hang_watchdog.log——设置页 5 秒级 AppHangTransient 无日志可查，
    # 下次复现直接定位卡住帧。daemon 线程 + 主线程 QTimer 心跳，零界面影响。
    try:
        from vt_app.hang_watchdog import start as _start_hang_watchdog
        app._hang_watchdog_timer = _start_hang_watchdog(engine.APP_DIR)
    except Exception:  # noqa: BLE001 —— 看门狗失败不拖累启动
        pass
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
    # 2026-11-14：由 3.5s → 9s → 25s。实测 9s 起线程时，两条后台同步会在
    # T+13s / T+14s 各引发一次约 600–720ms 的 GIL 争用（网络请求与解析在主线程
    # 抢解释器锁），正好落在用户刚启动、开始操作的窗口里。
    # 2026-11-21（v3.1.5 卡死修复）：25s → **45s**，与 75s 的 import 预热拉开
    # 30s 窗口；同步本身已改单线程顺序（boot._start_startup_sync_threads）且
    # 校准合并加了 sha 前置跳过 + splitlines 索引，CPU 窗口大幅收缩，错峰为兜底。
    _defer("startup_sync", _start_startup_sync_threads, 45000, 95,
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
