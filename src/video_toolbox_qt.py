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

#: 「双语字幕」判定：cue 内同时出现中文行与非中文行。用于「任务创建」的跳转
#: 分派（单语 → 字幕翻译；双语 → 字幕校准）。
_ZH_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")


def _has_non_zh_letters(line):
    """该行是否含「非中文的文字」——拉丁 / 假名 / 谚文 / 西里尔 等都算。

    ⚠️ 不能用 `[A-Za-z]` 判：日文（こんにちは）、韩文（안녕하세요）里一个
    拉丁字母都没有，那样「日中对照」「韩中对照」会被误判成单语。
    """
    for ch in line:
        if _ZH_CHAR_RE.match(ch):
            continue
        if unicodedata.category(ch)[0] == "L":      # L* = 字母类
            return True
    return False


def iter_subtitle_cues(txt, max_cues=200):
    """把字幕文本拆成 cue 列表（每个 cue = 该条目的若干行文本）。

    兼容 SRT/VTT（`-->` 时间轴行切分）与 ASS/SSA（`Dialogue:` 行，`\\N` 换行）。
    ⚠️ **不能按"空行分隔"切块**：大量 SRT 的 cue 之间根本没有空行（导出器各异），
    那样整份文件会被当成一个块，双语判定必然失败（实测踩过）。
    """
    cues, cur = [], []
    for ln in (txt or "").splitlines():
        s = ln.strip()
        if "-->" in ln:                       # SRT / VTT 时间轴行
            if cur:
                cues.append(cur)
            cur = []
            continue
        if s.startswith("Dialogue:"):         # ASS / SSA
            if cur:
                cues.append(cur)
            cur = []
            body = ln.split(",", 9)[-1] if ln.count(",") >= 9 else s
            cur = [p.strip() for p in body.split("\\N") if p.strip()]
            cues.append(cur)
            cur = []
            continue
        if s and not s.isdigit() and not s.startswith(("[", "{")):
            cur.append(s)
        if len(cues) >= max_cues:
            break
    if cur:
        cues.append(cur)
    return cues


def subtitle_looks_bilingual(path, max_cues=200, need=3):
    """字幕是不是「双语」（中外对照）？

    判据用「同一个 cue 里既有中文行、又有非中文行」，而不是"文件里出现过
    中文"——否则带中文注释的外语字幕、单语中文字幕都会被误判成双语送去校准。
    取前 ``max_cues`` 个 cue，命中 ``need`` 个即认为双语（少量行内混排不算）。
    """
    try:
        txt = engine.read_text_any(path)
    except Exception:  # noqa: BLE001
        return False
    hits = 0
    for lines in iter_subtitle_cues(txt, max_cues=max_cues):
        if not lines:
            continue
        has_zh = any(_ZH_CHAR_RE.search(ln) for ln in lines)
        # 「非中文行」= 不含汉字、但含别的文字（假名/谚文/拉丁…）
        has_other = any((not _ZH_CHAR_RE.search(ln)) and _has_non_zh_letters(ln)
                        for ln in lines)
        if has_zh and has_other:
            hits += 1
            if hits >= need:
                return True
    return False


def make_task_creation_drop_handler(tc):
    """给「任务创建」页换一个 dropEvent：额外接受**字幕**文件。

    引擎原实现只认 SupportedVideoFormats / SupportedAudioFormats，拖 `.srt`
    进去会弹「格式错误 srt / 不支持该文件格式」；可字幕本就是这个工作台的合法
    输入（任务创建 → 字幕翻译 / 字幕校准）。这里只放宽"接受哪些扩展名"：
    是字幕就自己收下，**其余一律交回原实现**（保留它原有的提示与行为）。
    """
    orig_drop = tc.dropEvent

    def _drop(event):
        try:
            files = [u.toLocalFile() for u in event.mimeData().urls()]
        except Exception:  # noqa: BLE001
            files = []
        subs = [p for p in files
                if p and os.path.isfile(p)
                and os.path.splitext(p)[1].lower() in SUBTITLE_EXTS]
        if not subs:
            return orig_drop(event)
        tc.search_input.setText(subs[0])
        try:
            tc.status_label.setText("导入成功")
            InfoBar.success(
                "导入成功", "已导入字幕文件，点右侧按钮继续",
                duration=3000, position=InfoBarPosition.BOTTOM_RIGHT, parent=tc)
        except Exception:  # noqa: BLE001
            pass
    return _drop


















# ========== 字幕处理（内嵌第三方字幕引擎） ==========
class SubtitlePage(QWidget):
    """字幕处理：内嵌字幕引擎工作台（任务创建 / 语音转录 / 优化翻译 / 合成）。

    v1.10.2 起不再唤起独立窗口，引擎界面直接嵌入本页：
      · 引擎以第三方开源组件形式随包内置，界面在宿主窗口内呈现；
      · 品牌水印与捐助入口在嵌入层隐藏（许可与来源见 docs/ 下声明文件）；
      · 引擎背景改为透明，跟随宿主深色主题（其自带样式是白底，会与
        宿主界面割裂）。

    v1.10.4 起解决首次进入卡顿：
      · `prewarm()` 在主窗口首帧之后由后台线程提前 import 引擎模块
        （videocaptioner 及其 Qt 子模块的导入是卡顿的主要来源），
        再回到主线程按空闲时机建好界面——用户点进来时已是现成控件；
      · `showEvent` 仍保留兜底构建，预热失败时行为与旧版一致。
    """

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setObjectName("SubtitlePage")
        self._engine = None
        self._built = False
        self._prewarming = False
        self._prewarm_ready = False
        # 首页在预热完成前就收下文件时，先记在这里，工作台建好后再分派。
        self._pending_dispatch = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # v1.13.0：移除页内一级分段「字幕处理 / 字幕校准」——SegmentedWidget
        # 对每项固定 stretch=1 等分，只有两个标签时会被拉开大片空隙、下划线
        # 与文字错位（观感「区域不对齐」）。「字幕校准」改为并入下方引擎工作台
        # 分段，排在「字幕翻译」之后（见 _build_engine 中的挂载）。
        self.work_tab = QWidget(self)
        wlay = QVBoxLayout(self.work_tab)
        wlay.setContentsMargins(20, 10, 20, 12)
        wlay.setSpacing(8)
        outer.addWidget(self.work_tab, 1)
        self.vbox = wlay

        # 中部：引擎界面宿主；底部一行：引擎状态 + 设置/许可入口
        # （第三方组件的许可与来源见 docs\ 声明文件）
        self.host = QWidget(self.work_tab)
        self.host_lay = QVBoxLayout(self.host)
        self.host_lay.setContentsMargins(0, 0, 0, 0)
        self.vbox.addWidget(self.host, 1)

        foot = QWidget(self.work_tab)
        flay = QHBoxLayout(foot)
        flay.setContentsMargins(0, 0, 0, 0)
        flay.setSpacing(12)
        self.foot = foot                      # v1.12.0：引擎就绪后整行收起
        self.state_label = fit_caption(
            CaptionLabel("正在加载字幕引擎界面 …", foot))
        # v1.10.4：引擎设置并入「设置」页的「字幕引擎」分组，这里只留跳转
        self.set_btn = PushButton(FIF.SETTING, "打开设置", foot)
        self.set_btn.clicked.connect(self.open_settings)
        self.lic_btn = PushButton(FIF.CERTIFICATE, "许可与来源…", foot)
        self.lic_btn.clicked.connect(self.show_license)
        flay.addWidget(self.state_label, 1)
        flay.addWidget(self.set_btn)
        flay.addWidget(self.lic_btn)
        self.vbox.addWidget(foot)

        # ——「字幕校准」独立内容页：不进入任何宿主导航，待引擎工作台
        #    构建完成后并入其分段（见 _build_engine） ——
        # 2026-10-20 启动 <5s 专项：CalibPage 构造改惰性（真实平台实测
        # 211ms，只服务引擎工作台的一个分段，而工作台本身就在首帧后构建）。
        # app 必须传主窗口（消息队列 q 挂在主窗口上；此前传 SubtitlePage
        # 导致 AI 校准线程投递日志即抛 AttributeError 而死，校准等于没跑）。
        self._calib_page = None

    @property
    def calib_page(self):
        """「字幕校准」页——惰性构造（首次取用才建，幂等）。

        阶段③：经注册表服务 calibrate.build_page 组装；calibrate 功能缺失时
        返回 None，_build_engine 的挂载段自带 try/except 会跳过校准分段。
        """
        if self._calib_page is None:
            try:
                from features import registry
                self._calib_page = registry().service(
                    "calibrate", "build_page")(self.app, self)
            except Exception as _e:  # noqa: BLE001
                _perf_note(f"字幕校准页不可用（不影响工作台其它分段）：{_e}")
                return None
        return self._calib_page

    # ---------- 预热（消除首次进入卡顿） ----------
    def prewarm_import_only(self):
        """只预热 import，**不登记界面构建**（2026-11-14 启动修复）。

        启动期不再自动建工作台（见 MainWindow.__init__ 中 prewarm 那段的说明），
        但可以趁用户还没点进来，把引擎模块的 import 在后台线程先做掉。import
        不碰主线程（只抢 GIL，且 main() 已把切换间隔压到 1ms），用户首次进入
        「字幕处理」时只需付纯构造的代价（热态实测 0.36s）。

        与 :meth:`prewarm` 的区别：这里**不登记** ``prewarm_done`` /
        ``build_engine``，界面构建仍然只在页面真正显示时发生。
        """
        if self._built:
            return
        # 已因用户进入页面而起了预热线程：不要重复记日志，也不要另起一份
        # （两个预热线程互抢 GIL，实测导入会从 3s 劣化到 20s）。
        if _ENGINE_PREWARM["thread"] is not None:
            return
        _perf_note("prewarm_import_only() 被调用（起线程，不建界面）")
        self._prewarm_thread = _start_engine_prewarm()

    def prewarm(self):
        """空闲时预导入引擎模块。

        卡顿的根因有三块，v1.11.0 起逐条拆掉：
          1. `videocaptioner.core.utils.cache` 在模块级建 5 个 diskcache 库
             （每个约 0.9s）——已在 prepare_runtime_env 里用惰性代理消除；
          2. `videocaptioner.ui.view.home_interface` 依赖树（qtawesome 图标
             字体、platformdirs、transcribe/llm 子模块、vlc 探测）首次 import；
             本预热把它丢到后台线程完成（Python 的 import 锁让主线程的后续
             import 命中缓存）；
          3. 界面构造本身（引擎界面 30 多张卡片）。第 2 步完成后自动回主线程
             构建，做到「用户点进来时已是现成控件」。
        设置界面（setting_interface）不在这里预热：它属于设置页，由设置页
        自己懒加载，避免白等一份当前用不到的导入。
        """
        if self._built or self._prewarming:
            return
        _perf_note("prewarm() 被调用（起线程）")
        self._prewarming = True
        # 2026-10-20 第三波：统一走**模块级**预热线程（幂等）。本方法可能
        # 先于 main() 的 _defer_after_show 到达（QTimer 注册顺序），所以这里
        # 自己负责起线程——但绝不另起第二份导入：实测两个预热线程互抢 GIL，
        # 导入从 3.0s 劣化到 19.97s。
        self._prewarm_thread = _start_engine_prewarm()
        # 2026-10-21（启动调度专项）：不再 200ms 自轮询。交给调度器：
        #   · prewarm_done —— 探针任务，线程未结束就返回 False，64ms 后重问；
        #   · build_engine —— 依赖 prewarm_done，满足后回主线程构建，
        #     单帧预算 400ms（实测 HomeInterface 0.13s + 引擎界面 0.26s）。
        # 好处：完成瞬间即被感知（不再被 200ms 栅格拖后），且不再每轮写日志。
        _defer("prewarm_done", _engine_prewarm_probe, 0, 3, budget_ms=1)
        _defer("build_engine", self._build_when_ready, 0, 30,
               depends_on=("prewarm_done",), budget_ms=400)

    def _build_when_ready(self):
        """预热结束后的主线程构建（调度器任务体，见 prewarm）。"""
        if self._built:
            return True
        # 界面模块已就绪即可构建（后端 ASR 补丁可能还在跑，见 ui_ready 说明）
        self._prewarm_ready = bool(_ENGINE_PREWARM["ok"]
                                   or _ENGINE_PREWARM["ui_ready"])
        self._build_now("正在准备字幕引擎界面 …")
        return True

    def _wait_prewarm(self):
        """旧版 200ms 自轮询（2026-10-21 起由调度器的 prewarm_done 接管）。

        保留仅作兼容兜底：外部脚本/自检若显式调用仍能工作。
        """
        t = getattr(self, "_prewarm_thread", None)
        if t is not None and t.is_alive():
            QTimer.singleShot(200, self._wait_prewarm)
            return
        if self._built:
            return
        self._prewarm_ready = bool(_ENGINE_PREWARM["ok"])
        self._build_now("正在准备字幕引擎界面 …")

    # ---------- 构建 ----------
    def _build_engine(self):
        """创建并内嵌字幕工作台；隐藏品牌水印与捐助入口。

        v1.21.0（P3 引擎自研化）：默认使用自研 UI 包 ``vt_engine_ui``，其各页已把
        原先的 UI 视觉/交互补丁内建为显式逻辑；构造失败时自动回退引擎 UI。走自研
        路径时不再挂 ``engine_ui_brand_patch`` / ``vc_transcribe_ui_patch``（那些是
        打在引擎类上的运行期补丁，自研页无需），但**后端**协议补丁照挂。
        """
        HomeInterface, _setting_cls, is_self, ui_err = _resolve_engine_ui()
        if ui_err:
            _perf_note(f"自研 UI 不可用，回退引擎：{ui_err}")
        if HomeInterface is None:
            self.state_label.setText("字幕引擎加载失败：无可用 UI 实现")
            _perf_note("字幕引擎 import 失败：home_cls=None")
            return None
        if not is_self:
            # 引擎路径：品牌中性化 + 转录 UI 补丁（类级，须在实例化前挂上）
            engine.engine_ui_brand_patch()   # 用户可见文案中性化（见 docs\ 声明）
            # v1.14.1：转录下拉收敛「默认/ASR」+ 独立转录完成回填「字幕翻译」
            try:
                engine.vc_transcribe_ui_patch()
            except Exception as e:  # noqa: BLE001
                # 别再静默：UI 补丁一旦失败，协议补丁（在它的 ⑤ 里挂）就跟着
                # 没了，表现为"百炼端点被拿去打 /audio/transcriptions 而断连"
                try:
                    engine._vc_log(f"转录 UI 补丁失败：{e}")
                except Exception:  # noqa: BLE001
                    pass
        # 协议补丁独立再挂一次（幂等）：它才是"走哪条协议"的决定因素（后端，两条路径都要）
        try:
            engine.vc_asr_protocol_patch()
        except Exception:  # noqa: BLE001
            pass
        t0 = time.perf_counter()
        try:
            home = HomeInterface()
        except Exception as e:  # noqa: BLE001
            if not is_self:
                self.state_label.setText(f"字幕引擎加载失败：{e}")
                _perf_note(f"HomeInterface 构造失败：{e}")
                return None
            # 自研构造失败 → 回退引擎，界面绝不能打不开
            _perf_note(f"自研 HomeInterface 构造失败，回退引擎：{e}")
            try:
                engine._vc_log(f"自研 UI 构造失败，回退引擎：{e}")
            except Exception:  # noqa: BLE001
                pass
            try:
                from videocaptioner.ui.view.home_interface import HomeInterface as _EH
                engine.engine_ui_brand_patch()
                engine.vc_transcribe_ui_patch()
            except Exception as e2:  # noqa: BLE001
                self.state_label.setText(f"字幕引擎加载失败：{e2}")
                return None
            home = _EH()
        _perf_note(f"HomeInterface 构造：{time.perf_counter() - t0:.2f}s"
                   f"（{'自研' if is_self else '引擎'}）")
        # v1.12.0：工作台优化——
        #   · 隐藏「字幕校正」按钮（校准类功能统一到「字幕校准」板块）；
        #   · 收紧主布局间距、字幕表格吃满剩余空间（调整页面比例）。
        sub_if = getattr(home, "subtitle_optimization_interface", None)
        if sub_if is not None:
            opt_btn = getattr(sub_if, "optimize_button", None)
            cmd_bar = getattr(sub_if, "command_bar", None)
            if opt_btn is not None and cmd_bar is not None:
                # optimize_button 是 QAction（非 QWidget），从命令栏移除；
                # CommandBar.removeAction 只删按钮不清 actions 列表，
                # 再补一次 QWidget 基类的 removeAction 把 action 摘干净
                cmd_bar.removeAction(opt_btn)
                try:
                    from PySide6.QtWidgets import QWidget as _QW
                    _QW.removeAction(cmd_bar, opt_btn)
                except Exception:
                    pass
            lay = getattr(sub_if, "main_layout", None)
            table = getattr(sub_if, "subtitle_table", None)
            if lay is not None:
                lay.setSpacing(10)
                if table is not None:
                    lay.setStretch(lay.indexOf(table), 1)
        # 引擎自带白色页面背景，内嵌到深色宿主里改为透明、随主题配色
        home.setStyleSheet("HomeInterface{background:transparent;}")
        # v1.13.0：引擎工作台分段项「字幕优化与翻译」更名「字幕翻译」
        try:
            home.pivot.setItemText("SubtitleInterface", "字幕翻译")
        except Exception:  # noqa: BLE001
            pass
        # v2.1.0：彻底摘掉「字幕视频合成」分段——用户要求「去掉这块多余内容，
        # 剩下三个平铺」。合成能力早已并入「字幕编辑」页的「内嵌字幕」入口。
        #
        # ⚠ 这里**不能只调** ``pivot.removeWidget()``：它内部是
        # ``items.pop`` + ``hBoxLayout.removeWidget`` + ``item.deleteLater()``，
        # 而 ``QLayout.removeWidget`` **只解除布局管理、不隐藏控件**，控件在
        # 被真正 delete 之前仍会照常绘制（用户截图里那个孤立残留的
        # 「字幕视频合成」小块就是这么来的）。所以额外显式 hide 一次。
        try:
            syn = getattr(home, "video_synthesis_interface", None)
            if syn is not None:
                try:
                    home.subtitle_optimization_interface.finished.disconnect(
                        home.switch_to_video_synthesis)
                except Exception:  # noqa: BLE001
                    pass
                # 兜底：万一还有别的路径调过来，也不该切到一个已摘掉的页面
                home.switch_to_video_synthesis = lambda *a, **k: None
                item = home.pivot.items.get("VideoSynthesisInterface")
                if item is not None:
                    item.hide()
                home.pivot.removeWidget("VideoSynthesisInterface")
                # removeWidget 内部是 deleteLater()，**延迟**到事件循环才真正
                # 销毁；在那之前它仍是 SegmentedWidget 的子控件（多出一个
                # sibling 下标，且仍有一帧绘制）。立即脱父，顺带彻底切断
                # 残留来源，也与自研路径（构造期就 setParent(None)）结构一致。
                if item is not None:
                    item.setParent(None)
                home.stackedWidget.removeWidget(syn)
                syn.hide()
                syn.setParent(None)
        except Exception:  # noqa: BLE001
            pass
        tc = getattr(home, "task_creation_interface", None)
        if tc is not None:
            self.wire_task_creation(tc, lambda: home)
            # v2.1.0：「任务创建」已提为应用首页 ⇒ 工作台**构建时就永久摘除**
            # 该分段——**不能**依赖 adopt 的时机或成败（用户实机出现过分段
            # 仍在的情况，原因难追，必须结构性保证）。摘掉后 tc 成为孤儿
            # （引用仍挂在 home 上），随后 adopt 把它认领到首页；即使 adopt
            # 没跑，工作台也绝无这个分段。
            #   · pivot 项：hide → removeWidget → setParent(None)（三件套，
            #     原因同上「字幕视频合成」：QLayout.removeWidget 不隐藏控件）；
            #   · 堆叠页：removeWidget（会顺手 hide，正好）。
            try:
                # ⚠ 摘除前先把当前页切走：构造期当前页就是 tc 本身，
                # 直接 removeWidget 会让 currentIndex 自动落到「语音转录」，
                # 引擎回退路径的转录页 showEvent 会 **lazy 创建第二个
                # RoundMenu**（自研页无此 lazy）⇒ golden 结构比对失衡，
                # 且引擎路径下用户会凭空看到一次转录页闪现。
                home.stackedWidget.setCurrentWidget(
                    home.subtitle_optimization_interface)
                _item = home.pivot.items.get("TaskCreationInterface")
                if _item is not None:
                    _item.hide()
                home.pivot.removeWidget("TaskCreationInterface")
                if _item is not None:
                    _item.setParent(None)
                home.stackedWidget.removeWidget(tc)
                # 摘掉首段后堆叠/分段的当前项可能悬空，落到第一个存在的分段
                if home.stackedWidget.count():
                    _first = home.stackedWidget.widget(0)
                    home.stackedWidget.setCurrentWidget(_first)
                    home.pivot.setCurrentItem(_first.objectName())
            except Exception as e:  # noqa: BLE001
                _perf_note(f"工作台摘除任务创建分段失败：{e}")
        # v1.13.0：把「字幕校准」并入引擎工作台分段，排在工作台「字幕翻译」
        # 之后（用户要求：校准并入「字幕翻译排」）。只加引擎界面 + 分段项，
        # 不改动引擎本体的处理流程。
        try:
            self.calib_page.setObjectName("CalibrationInterface")
            home.stackedWidget.addWidget(self.calib_page)
            keys = list(home.pivot.items.keys())
            if "SubtitleInterface" in keys:
                idx = keys.index("SubtitleInterface") + 1
            else:
                idx = -1   # 没找到「字幕翻译」时追加到末尾
            home.pivot.insertItem(
                idx, "CalibrationInterface", "字幕校准",
                onClick=lambda: home.stackedWidget.setCurrentWidget(
                    self.calib_page))
        except Exception:  # noqa: BLE001
            pass
        # v2.1.0：三个分段**平铺**这件事**不需要任何额外干预**——
        # ``Pivot.insertWidget`` 内部就是 ``hBoxLayout.insertWidget(idx, w, 1)``，
        # stretch=1，SegmentedWidget 又随外层容器同宽扩张，三项自然等宽均分
        # （实测 252/253/252@757）。曾在这里加过一套「setAlignment /
        # setSizePolicy(Expanding) / setSizeConstraint(0)」，负向验证
        # （``_negtest_synth_tabs.py`` N2：整段撤掉）证明撤掉后几何**一模一样**
        # ⇒ 属多余代码，已删。教训：别凭"看起来该这么配"加设置，
        # 先用负向验证证明它是必要的。
        #
        # ⚠ 但若将来真要加分段边距：**绝不能设在 SegmentedWidget 自身上**——
        # 它的 paintEvent 用 ``item.rect().adjusted(1,1,-1,-1).translated(
        # slideAni,0)`` 画选中底框，完全无视布局 y；一旦加上下边距，
        # 选中框会和文字错位。要留白就加在外层容器（HomeInterface 的
        # vBoxLayout）上。
        self._engine_home = home
        return home

    def wire_task_creation(self, tc, home_getter=None):
        """给「任务创建」控件做实例整形 + 信号接线（幂等）。

        首页在预热之前就构造独立的 TaskCreationInterface（见
        ``HomePage.ensure_task_creation``），因此接线不能再只放在
        ``_build_engine`` 里；这里成为唯一入口。``home_getter`` 延迟解析
        工作台实例——首页早期它可能还是 None。
        """
        if tc is None or getattr(tc, "_vt_wired", False):
            return
        try:
            tc._vt_wired = True
        except Exception:  # noqa: BLE001
            pass
        for attr in ("info_label", "donate_button"):
            w = getattr(tc, attr, None)
            if w is not None:
                w.hide()

        def _home():
            try:
                return home_getter() if callable(home_getter) else None
            except Exception:  # noqa: BLE001
                return None

        # 工作台的 HomeInterface 构造时把 finished 接到了 switch_to_transcription；
        # 首页接管后必须断开，改走宿主自己的类型分派。
        try:
            home = _home()
            if home is not None:
                tc.finished.disconnect(home.switch_to_transcription)
        except Exception:  # noqa: BLE001
            pass
        try:
            tc.finished.connect(
                lambda fp: self._dispatch_created_task(_home(), fp))
        except Exception as e:  # noqa: BLE001
            _perf_note(f"任务创建页分派接线失败：{e}")
        # v1.16.4：任务创建页原本只收音视频，拖 .srt 会弹「格式错误」。
        # 字幕本就是本工作台的合法输入，这里放宽接收（见工厂函数说明）。
        try:
            tc.dropEvent = make_task_creation_drop_handler(tc)
        except Exception as e:  # noqa: BLE001
            _perf_note(f"任务创建页字幕接收补丁失败：{e}")
        # v2.1.0：识别到网页链接 → 跳「视频处理 / 视频下载」。
        try:
            sig = getattr(tc, "url_detected", None)
            if sig is not None:
                sig.connect(self.app.goto_video_download)
        except Exception as e:  # noqa: BLE001
            _perf_note(f"任务创建页链接跳转接线失败：{e}")
        # v2.1.0：harness 就绪时，纯文本输入 → AI 托管。
        try:
            sig = getattr(tc, "ai_requested", None)
            if sig is not None:
                sig.connect(self._on_ai_requested)
        except Exception as e:  # noqa: BLE001
            _perf_note(f"任务创建页 AI 托管接线失败：{e}")

    def _on_ai_requested(self, text):
        """首页任务框识别到「纯文本」→ 交给 AI 托管页执行（v2.1.0）。

        只在 harness 就绪时才会收到这个信号（发送方判过 ``available()``）；
        宿主没建 AI 托管页（harness 不在场）时这里是静默 no-op。
        """
        try:
            win = self.app if hasattr(self, "app") else self.window()
            goto = getattr(win, "goto_ai_console", None)
            if goto is not None:
                goto(text)
        except Exception as e:  # noqa: BLE001
            _perf_note(f"AI 托管跳转失败：{e}")

    def _dispatch_created_task(self, home, file_path):
        """任务创建完成后**按文件类型**跳转到对应工作台（见 _build_engine 说明）。

        · 视频 / 音频           → 语音转录（引擎原行为）；
        · 单语字幕（无中文对照） → 字幕翻译；
        · 双语字幕（中英对照）   → 字幕校准。

        v2.1.0：任务创建已提为**首页**，用户此刻停在首页而不是工作台内，
        所以每次分派都要先把宿主窗口切到「字幕处理」——否则分段切了、
        窗口还停在首页，用户看到的是"点了没反应"。
        """
        path = str(file_path or "")
        if home is None:
            home = getattr(self, "_engine_home", None)
        if home is None:
            # 首页任务框现在先于引擎预热就绪（2026-10-23 启动专项）。
            # 此时用户已经给了文件：切到字幕处理页显示占位，等工作台构建完
            # 再自动续跑，绝不在主线程同步等 6～18 秒的导入。
            self._pending_dispatch = path
            self._reveal_workbench()
            try:
                self.state_label.setText("正在准备字幕引擎，就绪后自动继续 …")
            except Exception:  # noqa: BLE001
                pass
            self.ensure_built()
            return
        ext = os.path.splitext(path)[1].lower()
        self._reveal_workbench()
        if ext not in SUBTITLE_EXTS:
            home.switch_to_transcription(path)
            return
        if subtitle_looks_bilingual(path):
            self.calib_page.accept_subtitle(path)
            self.switch_to_calib()
        else:
            self._open_subtitle_translate(home, path)

    def _reveal_workbench(self):
        """把宿主窗口切到「字幕处理」页（工作台所在的导航页）。"""
        try:
            win = self.window()
            if getattr(win, "stackedWidget", None) is not None:
                cur = win.stackedWidget.currentWidget()
                if cur is not self:
                    win.switchTo(self)
        except Exception as e:  # noqa: BLE001
            _perf_note(f"切到字幕处理页失败：{e}")

    def _open_subtitle_translate(self, home, sub_path):
        """把字幕送进引擎「字幕翻译」页并切过去。

        字幕没有配套视频，`video_path` 传 None（引擎的 `create_subtitle_task`
        本来就允许）；task_id 沿用 home 当前的，保持同一条任务链。
        """
        try:
            # 走自研工厂：命名会剥掉应用自己的【字幕】前缀，避免叠成双层
            from engine_task_factory import TaskFactory
            task = TaskFactory.create_subtitle_task(
                sub_path, None, need_next_task=True,
                task_id=getattr(home, "_current_task_id", "") or "")
            home.subtitle_optimization_interface.set_task(task)
            home.pivot.setCurrentItem("SubtitleInterface")
            home.stackedWidget.setCurrentWidget(
                home.subtitle_optimization_interface)
        except Exception as e:  # noqa: BLE001
            _perf_note(f"跳转字幕翻译失败：{e}")
            # 兜底：切不过去就退回引擎原行为，至少别把用户卡在任务创建页
            try:
                home.switch_to_transcription(sub_path)
            except Exception:  # noqa: BLE001
                pass

    def switch_to_calib(self):
        """外部跳转：切到引擎工作台的「字幕校准」子页（拖拽定位/截图用）。"""
        home = getattr(self, "_engine_home", None)
        if home is None:
            return
        try:
            home.pivot.setCurrentItem("CalibrationInterface")
            home.stackedWidget.setCurrentWidget(self.calib_page)
        except Exception:  # noqa: BLE001
            pass

    def calib_active(self):
        """当前是否停在「字幕校准」子页（引擎工作台分段的当前项）。

        供主窗口的全局拖放分派器判断：用户在校准页上拖字幕时，拖到本页
        之外的位置（页面边缘、导航条）也应就地填入校准输入框，而不是跳页。
        """
        home = getattr(self, "_engine_home", None)
        if home is None:
            return False
        try:
            return home.stackedWidget.currentWidget() is self.calib_page
        except Exception:  # noqa: BLE001
            return False

    def _build_now(self, busy_text):
        if self._built:
            return
        self._built = True
        # 引擎工作台可能含 SpinBox：补丁必须先于它存在（幂等，通常早已装好）
        _install_spinbox_fix_once()
        self._build_t0 = time.perf_counter()
        if busy_text:
            self.state_label.setText(busy_text)
            # 2026-11-14：先把「正在准备…」推到屏幕上再进构建。整段构建实测可达
            # 30s 级且全程占着主线程，没有这一步用户只会看到上一个页面的残帧，
            # 体感是「点进来先死一下」。
            try:
                QApplication.processEvents()
            except Exception:  # noqa: BLE001
                pass
        # 2026-11-14：构建拆成三段，段与段之间回一次事件循环。
        # 冷缓存下整段实测可达 33–42s（logs\startup.log 2026-11-12/11-14），
        # 一段做完期间窗口会被系统判成「未响应」；分段后每次连续占用短一截，
        # 用户也还能在间隙里切回别的页面。热态下三段合计仍是 0.6s 量级。
        self.state_label.setText("正在准备字幕引擎界面 …（1/3 构建控件）")
        QTimer.singleShot(0, self._build_stage_engine)

    def _build_stage_engine(self):
        """第 1/3 段：构造引擎工作台（HomeInterface + 整形）。"""
        t0 = self._build_t0
        try:
            self._engine = self._build_engine()
        except Exception as e:  # noqa: BLE001
            _perf_note(f"工作台构建异常：{e}")
            self._engine = None
        _perf_note("工作台[1/3 构建控件] %.2fs（返回 %s）"
                   % (time.perf_counter() - t0,
                      "None" if self._engine is None else "ok"))
        if self._engine is None:
            self.state_label.setText("字幕引擎加载失败，详见 logs\\startup.log")
            return
        self.state_label.setText("正在准备字幕引擎界面 …（2/3 并入页面）")
        QTimer.singleShot(0, self._build_stage_mount)

    def _build_stage_mount(self):
        """第 2/3 段：把工作台塞进宿主布局（首次 polish/布局最贵的一段）。"""
        t0 = self._build_t0
        try:
            self.host_lay.addWidget(self._engine)
        except Exception as e:  # noqa: BLE001
            _perf_note(f"工作台装箱失败：{e}")
            return
        _perf_note("工作台[2/3 并入页面] %.2fs" % (time.perf_counter() - t0))
        self.state_label.setText("正在准备字幕引擎界面 …（3/3 收尾）")
        QTimer.singleShot(0, self._build_stage_adopt)

    def _build_stage_adopt(self):
        """第 3/3 段：任务创建移交首页、运行期配置、状态行、导航收敛。"""
        t0 = self._build_t0
        # v2.1.0：任务创建分段已提升为应用首页（见 HomePage）。把它从工作台
        # 摘出来交给首页——**必须在 addWidget 到本页之后**，否则首页先拿到
        # 控件、工作台随后又把同一个控件 addWidget 一次，Qt 只会保留最后一次。
        try:
            win = self.window()
            hp = getattr(win, "home_page", None)
            if hp is not None:
                hp.adopt(self._engine)
                # 首页若已在预热前建好任务框，工作台自带的那个就是孤儿：
                # 它已从分段/堆叠摘除，这里直接销毁，避免重复信号源。
                orphan = getattr(self._engine, "task_creation_interface", None)
                if (orphan is not None and hp.task_creation is not None
                        and orphan is not hp.task_creation):
                    orphan.deleteLater()
        except Exception as e:  # noqa: BLE001
            _perf_note(f"任务创建页移交首页失败：{e}")
        # 引擎 QConfig 已随 HomeInterface 导入并读盘，再做一次运行期兜底：
        # 强制工作目录等收敛到软件文件夹（防止历史 C 盘值在内存里复活）
        try:
            engine.vc_enforce_runtime_cfg()
        except Exception:
            pass
        self.state_label.setText("字幕引擎已就绪（内嵌运行，无需联网下载模型）")
        # v1.12.0：引擎就绪后收起底部状态行（打开设置/许可走导航栏），
        # 把页面高度全部让给工作台（调整页面比例）
        self.foot.hide()
        # 首页在预热前收下的文件：等界面真正并入主树后再续跑分派。
        pending = self._pending_dispatch
        self._pending_dispatch = None
        if pending:
            QTimer.singleShot(
                0, lambda p=pending: self._dispatch_created_task(self._engine, p))
        # 引擎界面（自带字体）进来后，导航宽度重新按宿主的统一口径收敛一次
        try:
            self.window().refresh_nav_width()
        except Exception:
            pass
        _perf_note(f"字幕引擎界面构建完成：{time.perf_counter() - t0:.2f}s"
                   f"（预热 {'已就绪' if self._prewarm_ready else '未完成'}，"
                   f"三段构建）")

        # 引擎界面刚并入主树。
        # 2026-10-21（启动调度专项）：这里原本挂一个「空闲时分片扫全树、预热
        # 主题色小表」的任务（更早是 singleShot(300) 一次性全量，首次 ≈1.8s）。
        # 实测**两头都不划算**：
        #   · 分片版每片 200 个控件在冷缓存下仍要 200ms+，连跑 10 余轮 →
        #     UI 心跳探针在首帧后 3–6s 持续报「主线程被占用」，正是用户说的
        #     「刚进来点不动」；
        #   · 而它想预热的东西其实**已经被预热了**——`_PlainAccentFilter`
        #     在每次 Polish（首绘前）就算过 plain_accent_qss，缓存本就是热的，
        #     用户第一次改主题色不会再有 1.8s。
        # 故直接移除，不再启动期扫全树。改主题色时 set_accent() 里的全量刷新
        # 仍在（缓存热态 ~30ms），语义不变。

    def showEvent(self, event):
        """首次显示时才加载引擎界面（内嵌 QWidget，随主题自动配色）。

        2026-10-20：**不在主线程同步导入**引擎 UI 树（openai 6.2s +
        qfluentwidgets 2.8s + ASR 链，合计 ≈14s，整窗冻死）。改为起预热
        线程、显示占位文案，由 _wait_prewarm 在后台导入完成后回主线程构建
        ——界面全程可响应，用户可先去别的页。
        """
        super().showEvent(event)
        if self._built:
            return
        self.state_label.setText("正在准备字幕引擎界面 …")
        self.ensure_built()

    def ensure_built(self):
        """确保工作台已构建（幂等）——供首页在启动时提前触发。

        v2.1.0：任务创建成为应用默认落地页，构建时机从「用户点进本页」
        提前到「首页首次显示」。预热线程仍在跑时不等它（:meth:`_wait_prewarm`
        会在预热结束后自行构建），直接返回即可。

        2026-10-20 第四波（启动 <5s 专项）：**绝不在 show() 的同步路径里
        起导入线程**。原实现经 HomePage.showEvent → ensure_built → prewarm()
        在 window.show() 内部就把 CPU 密集的引擎导入线程拉起来，首帧 paint
        （posted 事件）随后在事件循环里与导入线程抢 GIL——实测窗口可见
        从亚秒劣化到 10s 级（整链 25.8s 的直接根因）。改为只挂号
        singleShot(0)：show() 返回、首帧 paint 落定之后才起线程。
        """
        if self._built:
            return
        if self._prewarming:
            # 预热线程在跑：用户可能已经点进本页 → 把相关任务插到队首，
            # 预热一结束立刻构建（而不是排在库页/自动化页后面）。
            s = _SCHED["inst"]
            if s is not None:
                s.run_now("prewarm_done", priority=0)
                s.run_now("build_engine", priority=0)
            return
        _defer("prewarm_kick", self.prewarm, 0, 5, budget_ms=5)

    def open_settings(self):
        """跳到唯一的全局设置页，并定位到字幕引擎参数区。

        v1.10.8 起不再保留独立引擎设置对话框：所有设置（含 LLM、保存位置）
        都在主设置页这一处。
        """
        win = self.window()
        try:
            if hasattr(win, "open_engine_settings"):
                win.open_engine_settings()
        except Exception:  # noqa: BLE001
            pass

    def show_license(self):
        if os.path.isfile(engine.VC_LICENSE_FILE):
            try:
                os.startfile(engine.VC_LICENSE_FILE)     # noqa: S606
                return
            except OSError:
                pass
        MessageBox("第三方组件许可与来源",
                   "本工具内置第三方开源字幕引擎，其许可全文与来源声明见安装目录 "
                   "docs/ 下的 VideoCaptioner_GPL-3.0.txt 与 VideoCaptioner_组件来源.txt。",
                   self).exec()


# ========== 设置（全程序唯一全局设置，v1.10.8） ==========
class _InnerScrollToContent(QObject):
    """让内嵌的引擎 SettingInterface（自身是滚动区）高度恒等于其内容高度。

    关掉它自身的滚动条后，再把它的固定高度钉到内部 scrollWidget 的实际高度，
    于是内层不再形成独立视口/滚动条，滚动统一交给外层设置页，视觉上是一整页。
    """

    def __init__(self, area, parent=None):
        super().__init__(parent or area)
        self.area = area

    def sync_height(self):
        w = self.area.widget()
        if w is not None and w.height() > 0:
            self.area.setFixedHeight(w.height())

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Resize:
            self.sync_height()
        return False


class _BgPathEdit(LineEdit):
    """背景图路径输入框：支持从资源管理器把图片直接拖进来应用。

    拖入是比手输更防错的填入方式——手输路径打错一个字符就会命中
    isfile 检查失败（旧版此处静默回填，用户毫无感知）。
    """

    def __init__(self, on_file, parent=None):
        super().__init__(parent)
        self._on_file = on_file
        self.setAcceptDrops(True)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            for u in e.mimeData().urls():
                p = u.toLocalFile()
                if p and os.path.isfile(p):
                    e.acceptProposedAction()
                    return
        e.ignore()

    def dropEvent(self, e):
        for u in e.mimeData().urls():
            p = u.toLocalFile()
            if p and os.path.isfile(p):
                self.setText(p)
                self._on_file(p)
                e.acceptProposedAction()
                return
        e.ignore()


class SettingsPage(QWidget):
    """全程序唯一的全局设置页（v1.10.8）。

    不再分「工具设置 / 字幕引擎」两段，也不再有独立引擎设置对话框；一页纵向
    排开：目录 → 全局 AI（两条独立通道）→ ASR 语音识别 → AI 校准 →
    字幕引擎运行参数（内嵌引擎设置界面，隐藏与其重复的 LLM / 保存 / 个性化 /
    关于分组）→ 校准知识同步 → 界面 → 关于。
    v1.11.0 起 LLM 拆为两条**各自独立**的通道：接口 A（工具箱自身，Anthropic
    兼容）与接口 B（字幕引擎 / AI 校准，OpenAI 兼容），地址、密钥、模型都能
    分别填写；另新增 ASR 卡片（自有 ASR 服务或本地独立模型，直接写进引擎的
    「转录配置」）与 AI 校准卡片（校准通道 / 分块粒度 / 输出上限）。
    引擎设置界面约 30 张卡片，首次显示本页时才懒加载，避免拖慢启动。
    """

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setObjectName("SettingsPage")
        self._engine_setting = None
        self._engine_built = False
        self._bg_warned = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.shell = ScrollPage("设置", "全局设置对下载、字幕引擎等所有功能统一生效",
                                self, scrollable=True)
        outer.addWidget(self.shell)
        self.shell.layout().setContentsMargins(24, 12, 24, 12)
        self.shell.layout().setSpacing(8)
        self.vbox = self.shell.content_lay

        self._build_dirs_card()
        self._build_cookie_card()
        # v1.14.1 安全整改：「网络代理」卡片已移除——内置代理降级为纯后台
        # 下载兜底，不再有界面入口与文字说明（节点凭据严禁随包分发）。
        self._build_ai_card()
        self._build_asr_card()
        self._build_calib_ai_card()
        self._build_engine_section()
        self._build_sync_card()
        self._build_update_card()
        self._build_uicustom_card()
        self._build_appearance_card()
        self._build_about_card()
        self.vbox.addStretch(1)

    def showEvent(self, event):
        super().showEvent(event)
        # 首次显示时再懒加载引擎设置（此时后台预热通常已完成）
        QTimer.singleShot(0, self._ensure_engine_setting)
        # 已构建则每次显示重新贴合内层高度（宽度可能变化）
        f = getattr(self, "_engine_fit", None)
        if f is not None:
            QTimer.singleShot(0, f.sync_height)
            QTimer.singleShot(160, f.sync_height)
        # 「界面美化」输入框与实际配置对齐：防止改过配置后界面残留旧值，
        # 造成「页面有背景但输入框显示未设置」的错位观感
        if hasattr(self, "bg_page_edits"):
            self._refresh_bg_edits()
        # 主题色板圆点（自绘 AccentDot）：无样式缓存，首帧即终效；这里
        # 的重刷只是幂等兜底（set_selected 值未变时不会触发重绘）
        if hasattr(self, "_refresh_accent_ring"):
            self._refresh_accent_ring()

    # ------------------------------------------------------------------ #
    # 目录：下载目录 / 数据根目录 / 引擎工作目录（全部默认在软件文件夹）
    # ------------------------------------------------------------------ #
    def _build_dirs_card(self):
        box, blay = card("目录", "所有默认位置都落在软件文件夹，不写系统盘（C 盘）")

        self.dir_edit = LineEdit(box)
        self.dir_edit.setText(engine.get_saved_download_dir())
        self.dir_edit.editingFinished.connect(self._on_dir_changed)
        browse = PushButton(FIF.FOLDER, "浏览…", box)
        browse.clicked.connect(self._browse_dir)
        blay.addWidget(srow("下载目录", self.dir_edit, browse))

        self.dl_max_spin = SpinBox(box)
        self.dl_max_spin.setRange(1, 6)
        self.dl_max_spin.setValue(DownloadPage._load_max_concurrent())
        self.dl_max_spin.valueChanged.connect(self._on_dl_max_changed)
        blay.addWidget(srow("下载并发上限", self.dl_max_spin))

        root, is_default, src = engine.data_root_info()
        self.data_edit = LineEdit(box)
        self.data_edit.setText(root)
        self.data_edit.setPlaceholderText("留空使用程序目录")
        apply_btn = PushButton(FIF.SAVE, "应用", box)
        apply_btn.clicked.connect(self._apply_data_root)
        reset_btn = PushButton(FIF.SYNC, "还原默认", box)
        reset_btn.clicked.connect(self._reset_data_root)
        blay.addWidget(srow("数据根目录", self.data_edit, apply_btn, reset_btn))
        self.data_hint = fit_caption(CaptionLabel(
            f"当前：{src}" + ("" if is_default else f"　·　{root}"), box))
        self.data_hint.setTextColor("#8a8a8a", "#9a9a9a")
        blay.addWidget(self.data_hint)
        self.data_leftover = fit_caption(CaptionLabel("", box))
        self.data_leftover.setTextColor("#8a8a8a", "#9a9a9a")
        blay.addWidget(self.data_leftover)
        self._refresh_data_leftover()

        # 引擎工作目录：只读展示，强制在软件文件夹（用户不可改到系统盘）
        self.engine_dir_edit = LineEdit(box)
        self.engine_dir_edit.setReadOnly(True)
        try:
            self.engine_dir_edit.setText(
                os.path.join(engine.vc_data_dir(), "work-dir"))
        except Exception:
            self.engine_dir_edit.setText("")
        blay.addWidget(srow("引擎工作目录", self.engine_dir_edit))

        expand_h(self.dir_edit)
        expand_h(self.data_edit)
        expand_h(self.engine_dir_edit)
        self.vbox.addWidget(box)

    # ------------------------------------------------------------------ #
    # 下载 Cookie（反「Sign in to confirm you're not a bot」）
    # ------------------------------------------------------------------ #
    def _build_cookie_card(self):
        """cookie 来源三级配置。

        2026-09 起 YouTube 对代理 / 机房 IP 的**游客** cookie 已不放行，必须上
        登录态：要么让 yt-dlp 直接读已登录 YouTube 的浏览器，要么导入浏览器
        扩展导出的 cookies.txt（最稳，不受浏览器锁库影响）。
        """
        box, blay = card(
            "下载 Cookie（反风控）",
            "YouTube 已不再放行游客 cookie —— 需要登录态：从浏览器读取，"
            "或导入浏览器扩展导出的 cookies.txt")

        self.cookie_mode_combo = ComboBox(box)
        self.cookie_mode_combo.addItems([t for t, _k in engine.COOKIE_MODE_LABELS])
        _keys = [k for _t, k in engine.COOKIE_MODE_LABELS]
        _mode = engine.cookie_mode()
        self.cookie_mode_combo.setCurrentIndex(
            _keys.index(_mode) if _mode in _keys else 0)
        self.cookie_mode_combo.currentIndexChanged.connect(
            self._on_cookie_mode_changed)
        blay.addWidget(label_row("Cookie 来源", self.cookie_mode_combo))

        # —— 浏览器登录态（browser / auto） ——
        self.cookie_browser_combo = ComboBox(box)
        self.cookie_browser_combo.addItems(list(engine.COOKIE_BROWSERS))
        _br = engine.cookie_browser()
        if _br in engine.COOKIE_BROWSERS:
            self.cookie_browser_combo.setCurrentIndex(
                list(engine.COOKIE_BROWSERS).index(_br))
        self.cookie_browser_combo.currentIndexChanged.connect(self._save_cookie)
        # 「检测」= 完整诊断（能区分「浏览器在运行」与「App-Bound 加密解不开」）
        _bdiag = PushButton(FIF.SYNC, "检测", box)
        _bdiag.clicked.connect(self._diag_browser_cookie)
        # 「导入浏览器登录态」= 绕开 yt-dlp 的浏览器读取（见下方按钮说明）
        self.cookie_import_btn = PushButton(FIF.DOWNLOAD, "导入浏览器登录态", box)
        self.cookie_import_btn.setToolTip(
            "为什么需要这个按钮：\n"
            "· 现代 Chrome / Edge 的 cookie 是 App-Bound 加密（值前缀 v20），"
            "yt-dlp 只会按老的 DPAPI(v10) 解，必然失败（yt-dlp #10927）；\n"
            "· 浏览器开着时 cookie 库还会被独占锁（yt-dlp #7271）。\n"
            "所以 yt-dlp 自己「读浏览器」这条路在新版 Chrome/Edge 上已经走不通。\n\n"
            "本按钮改走另一条路：用**独立配置目录**启动一个浏览器窗口"
            "（不碰你正在用的那个，所以不受上面两个限制），"
            "你在窗口里登录一次 YouTube，程序借浏览器自己解密、经 CDP 取回"
            "**明文** cookie，导出成 data\\user_cookies.txt 并自动切到该来源。")
        self.cookie_import_btn.clicked.connect(self._import_browser_cookie)
        self.cookie_browser_row = srow("浏览器", self.cookie_browser_combo,
                                       _bdiag, self.cookie_import_btn)
        blay.addWidget(self.cookie_browser_row)

        # —— 自备 cookies.txt（file / auto） ——
        self.cookie_file_edit = LineEdit(box)
        self.cookie_file_edit.setText(engine.cookie_file() or "")
        self.cookie_file_edit.setPlaceholderText(
            r"留空则用 data\user_cookies.txt"
            r"（推荐用浏览器扩展「Get cookies.txt LOCALLY」在 youtube.com 导出）")
        self.cookie_file_edit.editingFinished.connect(self._save_cookie)
        _pick = PushButton(FIF.FOLDER, "选择…", box)
        _pick.clicked.connect(self._browse_cookie_file)
        _check = PushButton(FIF.SYNC, "检测", box)
        # 只有点「检测」才跑浏览器实测（1~3 秒的子进程），构建时不阻塞
        _check.clicked.connect(lambda: self._refresh_cookie_status(probe=True))
        self.cookie_file_row = srow("cookies.txt", self.cookie_file_edit,
                                    _pick, _check)
        blay.addWidget(self.cookie_file_row)

        self.cookie_hint = fit_caption(CaptionLabel("", box))
        self.cookie_hint.setTextColor("#8a8a8a", "#9a9a9a")
        blay.addWidget(self.cookie_hint)

        expand_h(self.cookie_file_edit)
        self.vbox.addWidget(box)
        self._on_cookie_mode_changed()

    def _cookie_mode_key(self):
        keys = [k for _t, k in engine.COOKIE_MODE_LABELS]
        i = self.cookie_mode_combo.currentIndex()
        return keys[i] if 0 <= i < len(keys) else "auto"

    def _on_cookie_mode_changed(self):
        mode = self._cookie_mode_key()
        self.cookie_browser_row.setVisible(mode in ("auto", "browser"))
        self.cookie_file_row.setVisible(mode in ("auto", "file"))
        self._save_cookie()

    def _browse_cookie_file(self):
        p, _f = QFileDialog.getOpenFileName(
            self, "选择 cookies.txt", engine.DATA_DIR,
            "Netscape cookie 文件 (*.txt);;所有文件 (*)")
        if p:
            self.cookie_file_edit.setText(p)
            self._save_cookie()

    def _save_cookie(self):
        try:
            cfg = engine.load_config() or {}
            cfg[engine.CFG_COOKIE_MODE] = self._cookie_mode_key()
            cfg[engine.CFG_COOKIE_BROWSER] = \
                self.cookie_browser_combo.currentText().strip()
            cfg[engine.CFG_COOKIE_FILE] = self.cookie_file_edit.text().strip()
            engine.save_config(cfg)
            engine.invalidate_cookie_cache()
        except Exception as e:  # noqa: BLE001
            _perf_note(f"保存 cookie 配置失败：{e}")
        self._refresh_cookie_status()

    def _refresh_cookie_status(self, probe=False):
        """把当前 cookie 来源的状态写成一行提示，用户不必猜配好没有。

        `probe=True`（点「检测」）才真跑浏览器实测（1~3 秒子进程）；平时用静态
        文案——设置页构建时同步跑子进程会白白卡住界面。
        """
        mode = self._cookie_mode_key()
        try:
            _br = self.cookie_browser_combo.currentText().strip()
            if mode == "browser":
                if probe:
                    ok, why = engine.browser_cookie_probe(_br)
                    txt = ("✅ " if ok else "⚠️ ") + why
                else:
                    txt = (f"将从 {_br} 读取登录态（需已登录 YouTube 且完全退出"
                           f"该浏览器）—— 点「检测」实测")
            elif mode == "guest":
                _ok, _lg, why = engine.cookies_file_status(engine.GUEST_COOKIES_PATH)
                txt = f"仅用自动游客 cookie：{why} —— 2026-09 起多半仍被风控拦"
            else:
                p = self.cookie_file_edit.text().strip() or engine.cookie_file()
                ok, logged, why = engine.cookies_file_status(p)
                if ok and logged:
                    txt = f"✅ 登录态 cookie 可用：{p}"
                elif ok:
                    txt = (f"⚠️ {why}：{p} —— 建议用已登录 YouTube 的浏览器"
                           f"重新导出")
                elif probe:
                    bok, bwhy = engine.browser_cookie_probe(_br)
                    txt = (f"⚠️ cookies.txt 不可用（{why}）；"
                           f"{'浏览器可用：' + bwhy if bok else '浏览器：' + bwhy}")
                else:
                    txt = (f"⚠️ cookies.txt 不可用（{why}）→ 将回退自动游客 cookie"
                           f"；点「检测」实测浏览器登录态")
        except Exception as e:  # noqa: BLE001
            txt = f"状态检查失败：{type(e).__name__}"
        self.cookie_hint.setText(txt)

    def _diag_browser_cookie(self):
        """「检测」浏览器登录态：跑完整诊断，把真因（锁库 / App-Bound）说清楚。"""
        br = self.cookie_browser_combo.currentText().strip()
        try:
            verdict, text = engine.browser_cookie_diagnose(br)
        except Exception as e:  # noqa: BLE001
            InfoBar.error("检测失败", f"{type(e).__name__}: {e}", duration=6000,
                          position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        title = {"ok": "浏览器登录态可读",
                 "locked": "浏览器正在运行 —— cookie 库被独占锁",
                 "appbound": "该浏览器用了 App-Bound 加密，yt-dlp 解不开",
                 "missing": "没找到该浏览器的登录数据"}.get(verdict, "检测结果")
        if verdict == "ok":
            InfoBar.success(title, text, duration=9000,
                            position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
        else:
            InfoBar.warning(title, text, duration=18000,
                            position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
        self._refresh_cookie_status()

    def _import_browser_cookie(self):
        """「导入浏览器登录态」：起独立配置的浏览器，走 CDP 导出明文 cookie。"""
        if getattr(self, "_cookie_import_running", False):
            # 再点一次 = 取消（导入要等用户登录，必须有退路）
            ev = getattr(self, "_cookie_import_cancel", None)
            if ev is not None:
                ev.set()
                InfoBar.info("正在取消导入", "已请求取消：浏览器窗口会被关掉。",
                             duration=5000,
                             position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        br = self.cookie_browser_combo.currentText().strip()
        InfoBar.info(
            "开始导入浏览器登录态",
            f"即将打开一个**独立配置**的 {br} 窗口（你正在用的窗口不受影响）："
            f"请在其中登录 YouTube，登录成功后程序会自动导出 cookie 并关掉它。"
            f"（想中途放弃就再点一次本按钮）",
            duration=12000, position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
        self._cookie_import_running = True
        self._cookie_import_cancel = threading.Event()
        self.cookie_import_btn.setText("取消导入")
        threading.Thread(target=self._import_cookie_worker, args=(br,),
                         daemon=True).start()

    def _import_cookie_worker(self, br):
        try:
            ok, msg, path = engine.export_browser_cookies_via_cdp(
                br, log=lambda m: self.app.q.put(("sys_log", m)),
                cancel=self._cookie_import_cancel)
        except Exception as e:  # noqa: BLE001
            ok, msg, path = False, f"{type(e).__name__}: {e}", ""
        self.app.q.put(("cookie_import_done", ok, msg, path))

    def on_cookie_import_done(self, ok, msg, path):
        """（主线程）导入结束：回填界面 / 提示结果。"""
        self._cookie_import_running = False
        self.cookie_import_btn.setText("导入浏览器登录态")
        if not ok:
            InfoBar.warning("浏览器登录态导入未完成", msg, duration=15000,
                            position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        # 引擎侧已把配置切成 file 模式；先把路径回填，再切下拉
        # （切下拉会触发 _save_cookie，按界面当前值落盘）
        self.cookie_file_edit.setText(path or "")
        try:
            keys = [k for _t, k in engine.COOKIE_MODE_LABELS]
            self.cookie_mode_combo.setCurrentIndex(keys.index("file"))
        except ValueError:
            pass
        self._refresh_cookie_status()
        InfoBar.success("浏览器登录态导入成功", msg, duration=12000,
                        position=InfoBarPosition.BOTTOM_RIGHT, parent=self)

    # ------------------------------------------------------------------ #
    # 网络代理（v1.14.1 起无界面）：原「网络代理」卡片与 _build_proxy_card /
    # _proxy_hint_text / _proxy_start_dir / _browse_proxy_yaml /
    # _apply_proxy_yaml / _reset_proxy_yaml 整组已移除——节点凭据严禁随包
    # 分发，内置代理只作为依赖下载的静默兜底存在（engine.ensure_builtin_proxy）。
    # ------------------------------------------------------------------ #

    # ------------------------------------------------------------------ #
    # 全局 AI（LLM）：全程序唯一一套配置
    # ------------------------------------------------------------------ #
    #: ASR 协议下拉：显示名 ↔ 配置键（顺序一一对应，与引擎侧 ASR_PROTOCOLS 同序）
    ASR_PROTO_LABELS = ("自动识别（推荐）", "OpenAI Whisper 兼容", "Azure OpenAI",
                        "Chat 音频转写（百炼 / MiMo）", "Deepgram",
                        "ElevenLabs Scribe", "Google Gemini",
                        "火山引擎（豆包）", "AssemblyAI",
                        "百炼实时（WebSocket）",
                        "百炼原生（ASR 专用端点）",
                        "百炼 Filetrans（异步转写）")
    ASR_PROTO_KEYS = ("auto", "openai", "azure", "chat_audio",
                      "deepgram", "elevenlabs", "gemini",
                      "volcengine", "assemblyai", "dashscope_realtime",
                      "dashscope_native", "dashscope_filetrans")

    def _build_ai_card(self):
        box, blay = card(
            "全局 AI",
            "一套配置全程序共用（OpenAI 兼容：工具箱、字幕引擎、AI 校准）；"
            "保存后立即写入字幕引擎")
        ai = engine.ai_load_config()

        self.ai_enabled = SwitchButton(box)
        self.ai_enabled.setChecked(bool(ai.get("enabled", True)))
        blay.addWidget(label_row("启用 AI", row(self.ai_enabled, None)))

        self.ai_key = PasswordLineEdit(box)
        # 2026-10-22 安全整改：密钥**不再 setText 回填**——控件文本会进 UI 基线
        # 快照与截图（v2.3.1 泄露事故的直接原因）。凭据存独立只读文件
        # data/credentials.json，这里只反映「是否已配置」。
        self.ai_key.setPlaceholderText(
            "已配置（存于独立凭据文件；留空则保持不变）"
            if str(ai.get("api_key") or "") else "API Key")
        blay.addWidget(srow("密钥", self.ai_key))

        self.ai_base = LineEdit(box)
        self.ai_base.setText(str(ai.get("base_url", "")))
        self.ai_base.setPlaceholderText(
            "如 https://open.bigmodel.cn/api/paas/v4（兼容 OpenAI/DeepSeek/"
            "Gemini 兼容层/Ollama/Azure 等，填到域名或版本段均可；订阅套餐填专属端点）")
        blay.addWidget(srow("接口地址", self.ai_base))

        self.ai_model = LineEdit(box)
        self.ai_model.setText(str(ai.get("model", "")))
        self.ai_model.setPlaceholderText("文本模型，如 glm-4.7-flash")
        blay.addWidget(srow("文本模型", self.ai_model))

        self.ai_vision = LineEdit(box)
        self.ai_vision.setText(str(ai.get("vision_model", "")))
        self.ai_vision.setPlaceholderText("视觉模型，如 glm-4.6v-flash（屏幕识别用）")
        blay.addWidget(srow("视觉模型", self.ai_vision))

        test_btn = PushButton(FIF.SEND, "测试接口", box)
        test_btn.clicked.connect(lambda: self._ai_test())
        # 自动匹配（2026-10-01 v2）：按接口地址把「模型 / 输入输出预算」纠正成
        # 自洽可用的组合。针对的正是「火山 Token Plan 地址 + 非套餐模型」这类
        # 只能靠 404→401 报错才能发现的设置错误——这里一键改对，不用用户猜。
        match_btn = PushButton(FIF.SYNC, "自动匹配", box)
        match_btn.setToolTip(
            "按「接口地址」自动纠正模型与预算，典型场景：\n"
            "· 火山方舟 Token Plan 地址（/api/plan/v3）+ 非套餐模型 → 换成套餐"
            "模型（套餐 Key 打按量端点必 401，模型不匹配必 404，两端都不通）；\n"
            "· 输入/输出预算超所选模型上限 → 夹回该模型可用值。\n"
            "点完请再点「保存并应用」落盘。")
        match_btn.clicked.connect(self._ai_match)
        save_btn = PrimaryPushButton(FIF.SAVE, "保存并应用", box)
        save_btn.clicked.connect(self._ai_save)
        self.ai_dirty_lbl = fit_caption(CaptionLabel("● 有未保存的改动", box))
        self.ai_dirty_lbl.setTextColor("#c07a1a", "#c07a1a")
        self.ai_dirty_lbl.setToolTip("改完要点「保存并应用」才会写入引擎；"
                                     "不保存的话转录/校准用的仍是上次保存的配置")
        self.ai_dirty_lbl.hide()
        blay.addWidget(row(test_btn, match_btn, save_btn, self.ai_dirty_lbl))

        self.ai_hint = fit_caption(CaptionLabel(
            "保存后立即生效；地址填到域名或版本段均可自动补全（含 Azure）。"
            "订阅套餐须填专属端点：百炼 Token Plan token-plan.…/compatible-mode/v1、"
            "火山 Coding Plan …/api/coding/v3、智谱 Coding Plan …/api/coding/paas/v4",
            box))
        self.ai_hint.setTextColor("#8a8a8a", "#9a9a9a")
        blay.addWidget(self.ai_hint)
        # 订阅套餐端点风险提示（2026-10-05 产品口径：**允许接入，只做提示**）——
        # 套餐条款普遍禁止自动化/批量非交互调用，而本软件的转录与字幕校准正是
        # 批量调用；能不能用、会不会被判违规由服务商定，风险用户自负。此处常驻
        # 一行提示，完整条款要点与稳妥替代端点放在悬停提示里（滚动区内不换行）。
        self.ai_plan_warn = fit_caption(CaptionLabel("", box))
        self.ai_plan_warn.setTextColor("#c0392b", "#e0705e")
        self.ai_plan_warn.hide()
        blay.addWidget(self.ai_plan_warn)
        for w in (self.ai_key, self.ai_base, self.ai_model, self.ai_vision):
            expand_h(w)
        # 编辑即亮「未保存」：不保存的话引擎里还是上一版配置
        for w in (self.ai_key, self.ai_base, self.ai_model, self.ai_vision):
            w.textChanged.connect(self._mark_ai_dirty)
        for w in (self.ai_base, self.ai_vision):
            w.textChanged.connect(self._sync_plan_warn)
        self.vbox.addWidget(box)
        self._sync_plan_warn()

    # ------------------------------------------------------------------ #
    # ASR 语音识别：独立 ASR 模型（自有服务 / 本地模型）→ 引擎「转录配置」
    # ------------------------------------------------------------------ #
    def _build_asr_card(self):
        box, blay = card(
            "ASR 语音识别（转录配置）",
            "语音转文字用独立 ASR 模型（自有服务或本地模型）；"
            "保存后自动写入引擎「转录配置」")
        ai = engine.ai_load_config()
        mode = str(ai.get("asr_mode") or "service").lower()

        self.asr_mode_combo = ComboBox(box)
        self.asr_mode_combo.addItems(["自有 ASR 服务（Whisper 兼容接口，推荐）",
                                      "本地独立模型（faster-whisper）"])
        self.asr_mode_combo.setCurrentIndex(1 if mode == "local" else 0)
        self.asr_mode_combo.currentIndexChanged.connect(self._sync_asr_visible)
        blay.addWidget(label_row("转录模型来源", self.asr_mode_combo))

        # 识别语言（2026-10-25 迁到「语音转录」页命令栏）：这里不再提供下拉，
        # 只留去向提示；保存设置时保留转录页写入的现值（见 _collect_ai）。
        lang_hint = fit_caption(CaptionLabel(
            "识别语言已移到「语音转录」页顶部命令栏，随选随用，无需在这里保存",
            box))
        lang_hint.setTextColor("#8a8a8a", "#9a9a9a")
        blay.addWidget(lang_hint)

        # —— 服务模式 ——
        self.asr_service_widget = QWidget(box)
        slay = QVBoxLayout(self.asr_service_widget)
        slay.setContentsMargins(0, 0, 0, 0)
        slay.setSpacing(8)
        self.asr_base = LineEdit(self.asr_service_widget)
        self.asr_base.setText(str(ai.get("asr_base_url", "")))
        self.asr_base.setPlaceholderText(
            "如 https://api.siliconflow.cn/v1（填到版本段即可；直接把文档里的"
            "完整端点粘进来也行，如 .../paas/v4/audio/transcriptions，会自动削尾）")
        slay.addWidget(srow("ASR 接口地址", self.asr_base))
        self.asr_key = PasswordLineEdit(self.asr_service_widget)
        # 同上：不回填明文，只给状态提示。
        self.asr_key.setPlaceholderText(
            "已配置（存于独立凭据文件；留空则保持不变）"
            if str(ai.get("asr_api_key") or "") else "ASR 服务 API Key")
        slay.addWidget(srow("ASR 密钥", self.asr_key))
        self.asr_model = LineEdit(self.asr_service_widget)
        self.asr_model.setText(str(ai.get("asr_model", "")))
        self.asr_model.setPlaceholderText("如 FunAudioLLM/SenseVoiceSmall、whisper-1")
        slay.addWidget(srow("ASR 模型名", self.asr_model))
        self.asr_prompt = LineEdit(self.asr_service_widget)
        self.asr_prompt.setText(str(ai.get("asr_prompt", "")))
        self.asr_prompt.setPlaceholderText("识别提示词（可留空：中文会自动加简体提示）")
        slay.addWidget(srow("识别提示词", self.asr_prompt))
        # 接口协议：全协议适配（v1.14.2 起含 Deepgram / ElevenLabs / Gemini）
        self.asr_proto_combo = ComboBox(self.asr_service_widget)
        self.asr_proto_combo.addItems(list(self.ASR_PROTO_LABELS))
        _saved_proto = str(ai.get("asr_protocol") or "auto").strip().lower()
        if _saved_proto == "dashscope":
            _saved_proto = "chat_audio"      # 历史键 → 新下拉里的同一项
        self.asr_proto_combo.setCurrentIndex(
            self.ASR_PROTO_KEYS.index(_saved_proto)
            if _saved_proto in self.ASR_PROTO_KEYS else 0)
        self.asr_proto_combo.setToolTip(
            "留「自动识别」即可：按接口地址与模型名判断。\n"
            + "\n".join("· %s：%s" % (lb, engine.ASR_PROTOCOL_NOTES[k])
                        for k, lb in zip(self.ASR_PROTO_KEYS[1:],
                                         self.ASR_PROTO_LABELS[1:])))
        slay.addWidget(srow("接口协议", self.asr_proto_combo))
        # 说话人分离（diarization）：让服务端区分「谁在说话」，字幕形如
        # 「[说话人1] 台词」。只在不分不清的端点上有效，其余端点开了也不出标签。
        _dz = ai.get("asr_diarize")
        self.asr_diarize_switch = SwitchButton(self.asr_service_widget)
        self.asr_diarize_switch.setChecked(
            _dz is True
            or str(_dz or "").strip().lower() in ("1", "true", "yes", "on"))
        self.asr_diarize_switch.setToolTip(
            "多人对话 / 访谈 / 播客：服务端按声纹区分说话人，同一段字幕里不会\n"
            "混进两个人（说话人切换处自动断开）。\n"
            "· 支持：火山极速版、AssemblyAI、Deepgram、ElevenLabs、百炼\n"
            "  Filetrans、百炼 3.1 原生端点；\n"
            "· 不支持：OpenAI 兼容 / Azure / Gemini / 本地 faster-whisper——\n"
            "  开了也不会有标签，字幕形态不变；\n"
            "· 百炼另有两条限制：仅单声道音频、建议时长 ≤ 2 小时。")
        # 用 label_row 而不是 srow：srow 会给第一个控件 stretch=1 吃满整行，
        # 开关被横向拉长很难看；label_row 让开关紧跟标签、右侧留白。
        slay.addWidget(label_row("说话人分离", self.asr_diarize_switch))
        # 语音分离（Separation）：两人**同时**说话时的重叠段，先把混合信号分离
        # 成单人轨再逐轨识别；音乐 reaction 场景另有一路"剔除歌声"。当前仅保留
        # 开关与接口占位（引擎侧 asr_separate_of / _asr_separate_audio），不真正
        # 跑分离模型——详见 video_toolbox.py 的说明。
        _sp = ai.get("asr_separate")
        self.asr_separate_switch = SwitchButton(self.asr_service_widget)
        self.asr_separate_switch.setChecked(
            _sp is True
            or str(_sp or "").strip().lower() in ("1", "true", "yes", "on"))
        self.asr_separate_switch.setToolTip(
            "重叠语音分离（Separation）：两人**同时**说话时，普通 ASR 会串音或\n"
            "漏词；开启后先把混合信号分离成单人轨、再逐轨识别，重叠段识别率\n"
            "明显提升；音乐 reaction 场景还可把歌声从人声中剔除。\n"
            "· 需与「说话人分离」同时开启才有意义；\n"
            "· 本版本仅保留开关与接口占位，尚未内置分离模型（Demucs /\n"
            "  MossFormer 等声源分离模型体积与算力开销较大）；\n"
            "· 开启后转录会在日志里记录待分离音频，便于后续接入。")
        slay.addWidget(label_row("语音分离", self.asr_separate_switch))
        blay.addWidget(self.asr_service_widget)

        # —— 本地模型 ——
        self.asr_local_widget = QWidget(box)
        llay = QVBoxLayout(self.asr_local_widget)
        llay.setContentsMargins(0, 0, 0, 0)
        llay.setSpacing(8)
        self.asr_local_model = LineEdit(self.asr_local_widget)
        self.asr_local_model.setText(str(ai.get("asr_local_model", "")))
        self.asr_local_model.setPlaceholderText(
            "模型名：工具箱已内置 large-v3 / small.en，也可填自训练模型目录名")
        self.asr_local_model.setToolTip(
            "内置 faster_whisper.WhisperModel 直连，无需下载 faster-whisper-xxl 等外部程序；\n"
            "模型目录留空时自动定位 tools\\asr_model\\faster-whisper\\<模型名>；\n"
            "GPU 缺少 cuBLAS/cuDNN 时自动降级 CPU int8（日志可查），不会静默切回云端。")
        llay.addWidget(srow("本地模型名", self.asr_local_model))
        self.asr_local_dir = LineEdit(self.asr_local_widget)
        self.asr_local_dir.setText(str(ai.get("asr_local_model_dir", "")))
        self.asr_local_dir.setPlaceholderText(
            "留空 = 自动定位 tools\\asr_model\\faster-whisper\\<模型名>")
        self.asr_local_browse = PushButton(FIF.FOLDER, "浏览…", self.asr_local_widget)
        self.asr_local_browse.clicked.connect(
            lambda: self._browse_into(self.asr_local_dir, "选择 ASR 模型目录"))
        llay.addWidget(srow("目录", self.asr_local_dir, self.asr_local_browse))
        blay.addWidget(self.asr_local_widget)

        asr_test = PushButton(FIF.SEND, "测试 ASR 配置", box)
        asr_test.clicked.connect(self._asr_test)
        asr_save = PrimaryPushButton(FIF.SAVE, "保存并应用", box)
        asr_save.clicked.connect(self._ai_save)
        self.asr_dirty_lbl = fit_caption(CaptionLabel("● 有未保存的改动", box))
        self.asr_dirty_lbl.setTextColor("#c07a1a", "#c07a1a")
        self.asr_dirty_lbl.setToolTip("改完要点「保存并应用」才会写进引擎的转录配置；"
                                      "只填不保存的话，转录页会提示「ASR 未配置」")
        self.asr_dirty_lbl.hide()
        self.asr_example_btn = PushButton(FIF.CODE, "调用示例（curl / Python）", box)
        self.asr_example_btn.setToolTip(
            "生成**非流式**的 curl 与 Python 调用示例：与程序内实现一一对应，"
            "可独立验证这套配置，也可直接复制到别的脚本里用")
        self.asr_example_btn.clicked.connect(self._asr_show_examples)
        blay.addWidget(row(asr_test, asr_save, self.asr_dirty_lbl))
        blay.addWidget(row(self.asr_example_btn, None))

        self.asr_hint = fit_caption(CaptionLabel(
            "服务模式：转录下拉选「ASR」即由自有服务识别；协议全适配"
            "（OpenAI 兼容 / Azure / 阿里云百炼 / Deepgram / ElevenLabs / "
            "Gemini，默认自动识别）；本地模式：内置 faster-whisper 直连，"
            "无需外部 exe，GPU 不可用时自动降级 CPU", box))
        self.asr_hint.setTextColor("#8a8a8a", "#9a9a9a")
        blay.addWidget(self.asr_hint)
        # ASR 侧的套餐端点风险提示（同「全局 AI」卡片口径：允许接入、只提示）
        self.asr_plan_warn = fit_caption(CaptionLabel("", box))
        self.asr_plan_warn.setTextColor("#c0392b", "#e0705e")
        self.asr_plan_warn.hide()
        blay.addWidget(self.asr_plan_warn)
        for w in (self.asr_base, self.asr_key, self.asr_model, self.asr_prompt,
                  self.asr_local_model, self.asr_local_dir):
            expand_h(w)
        # 编辑即亮「未保存」：只填不保存的话，转录页会提示「ASR 未配置」
        for w in (self.asr_base, self.asr_key, self.asr_model, self.asr_prompt,
                  self.asr_local_model, self.asr_local_dir):
            w.textChanged.connect(self._mark_ai_dirty)
        self.asr_base.textChanged.connect(self._sync_plan_warn)
        self.asr_mode_combo.currentIndexChanged.connect(self._mark_ai_dirty)
        self.asr_proto_combo.currentIndexChanged.connect(self._mark_ai_dirty)
        self.asr_diarize_switch.checkedChanged.connect(self._mark_ai_dirty)
        self.asr_separate_switch.checkedChanged.connect(self._mark_ai_dirty)
        self.vbox.addWidget(box)
        self._sync_asr_visible()
        self._sync_plan_warn()

    def _sync_asr_visible(self):
        """按 ASR 模式显隐「服务 / 本地」两组输入。"""
        local = self.asr_mode_combo.currentIndex() == 1
        self.asr_service_widget.setVisible(not local)
        self.asr_local_widget.setVisible(local)
        self.asr_hint.setText(
            "本地模式：转录下拉选「ASR」即用内置 faster-whisper 直连（无需外部 exe）；"
            "优先用上面填写的模型名与目录，目录留空自动定位工具箱内 "
            "large-v3 / small.en；GPU 缺 cuBLAS 时自动降级 CPU int8"
            if local else
            "服务模式：转录下拉选「ASR」即由自有 ASR 服务识别；协议可选"
            "自动识别 / OpenAI 兼容 / Azure / 阿里百炼，无时间戳响应自动"
            "按句切分兜底")

    def _sync_plan_warn(self, *_a):
        """刷新两处「订阅套餐端点」风险提示（全局 AI / ASR）。

        2026-10-05 产品口径：**允许接入套餐端点，只做提示**——能不能用、会不会
        被判违规由服务商定，风险用户自负。提示只读地址栏、不发网络请求，也绝不
        改地址或模型；完整条款要点与稳妥替代端点放在 tooltip（滚动区内不换行）。
        """
        for edit, label in ((getattr(self, "ai_base", None),
                             getattr(self, "ai_plan_warn", None)),
                            (getattr(self, "asr_base", None),
                             getattr(self, "asr_plan_warn", None))):
            if edit is None or label is None:
                continue
            try:
                tip = engine.ai_plan_risk(edit.text())
            except Exception:  # noqa: BLE001
                tip = ""
            if tip:
                label.setText("⚠️ 当前是订阅套餐端点：批量调用可能违反套餐条款，"
                              "风险自负（悬停查看详情）")
                label.setToolTip(tip)
                label.show()
            else:
                label.hide()

    def _browse_into(self, edit, title):
        p = QFileDialog.getExistingDirectory(self, title, edit.text() or engine.APP_DIR)
        if p:
            edit.setText(p)

    # ------------------------------------------------------------------ #
    # AI 校准：Agent 级字幕校准的分块参数（走全局 AI 单通道）
    # ------------------------------------------------------------------ #
    #: 思考强度（v1.15.7，参考模型厂商「高级配置」）：界面档位 → API 值
    CALIB_EFFORT_KEYS = ("low", "medium", "high", "xhigh", "max")
    CALIB_EFFORT_LABELS = ("低", "中", "高", "极高", "极致")

    def _build_calib_ai_card(self):
        box, blay = card(
            "AI 校准（Agent 级）",
            "字幕校准页开启后生效：先跑术语基线，再由 AI 逐块复校（只改文字）；"
            "走上方「全局 AI」同一套配置")
        ai = engine.ai_load_config()

        def _spin(value, lo, hi, step=1, width=200):
            s = SpinBox(box)
            s.setRange(lo, hi)
            s.setSingleStep(step)
            # 落盘值可能超出档位范围（如老配置的 60000）：夹到合法区间内显示，
            # 但**不反向改写配置**——只有用户真去动它才会变。
            try:
                v = int(value or lo)
            except (TypeError, ValueError):
                v = lo
            s.setValue(min(max(v, lo), hi))
            fit_spin(s, width)
            return s

        self.calib_cues = _spin(ai.get("calib_chunk_cues") or 400, 20, 1000, 10)
        blay.addWidget(label_row("每块最多条数", row(self.calib_cues, None)))
        # ⚠️ 上限必须 ≥ 引擎默认 60000：旧版上限 40000 会把默认值静默夹小
        self.calib_chars = _spin(ai.get("calib_max_chars") or 60000,
                                 1000, 200000, 500)
        blay.addWidget(label_row("每块字符预算", row(self.calib_chars, None)))

        # —— 思考模式 / 思考强度（2026-09-20）：随请求体 thinking + reasoning_effort 下发 ——
        self.calib_thinking_switch = SwitchButton(box)
        self.calib_thinking_switch.setChecked(
            bool(ai.get("calib_thinking", True)))
        self.calib_thinking_switch.checkedChanged.connect(
            self._sync_calib_thinking_visible)
        blay.addWidget(label_row("思考模式", self.calib_thinking_switch))

        self.calib_effort_combo = ComboBox(box)
        self.calib_effort_combo.addItems(list(self.CALIB_EFFORT_LABELS))
        _eff = str(ai.get("calib_reasoning_effort") or "high").strip().lower()
        self.calib_effort_combo.setCurrentIndex(
            self.CALIB_EFFORT_KEYS.index(_eff) if _eff in self.CALIB_EFFORT_KEYS
            else 2)
        self.calib_effort_combo.setToolTip(
            "下发到请求体 reasoning_effort：\n"
            "· DeepSeek 认 none/low/high/max，中/极高会被服务端归到 high；\n"
            "· 端点不认识该参数时程序自动去掉重试，不会因此报错；\n"
            "· ⚠️ 强度越高思考链越长，会先吃掉「输出」预算——额度太小时正文\n"
            "  会是空的（程序会明确报「只输出了思考链」而不是静默失败）。")
        blay.addWidget(label_row("思考强度", self.calib_effort_combo))

        # —— 输入 / 输出预算（参考图二的「输入 / 输出」双列 + 快捷档位）——
        self.calib_context = _spin(ai.get("calib_context_tokens") or 1000000,
                                   32768, 1048576, 32768, width=300)
        # 上限 1M（v1.16.1）：随「输出」档位一起提到 1M。DeepSeek 官方 384K，
        # 超出的额度由请求侧「减半自愈」在支持的大额度端点全额下发、小端点自动降级。
        self.calib_tokens = _spin(ai.get("calib_max_tokens") or 65536,
                                  1024, 1048576, 1024, width=300)
        in_col, out_col = QWidget(box), QWidget(box)
        # 档位起点（v1.16.1）：输入 128K 起、输出 256K 起——小额度已无意义
        # （推理模型思考链会吃光输出额度），只留大额度快捷档。
        # 两列固定 300px、按钮等宽铺满：数值框不再撑满半列，数字右对齐后
        # 与步进按钮相邻；880px 最小窗口下 300+16+300 正好放下。
        chips_all = []
        for holder, lbl, spin, presets, chip_w in (
                (in_col, "输入（上下文预算）", self.calib_context,
                 ((131072, "128K"), (262144, "256K"), (524288, "512K"),
                  (1048576, "1M")), 72),
                (out_col, "输出（单次上限）", self.calib_tokens,
                 ((262144, "256K"), (524288, "512K"), (1048576, "1M")), 97)):
            holder.setFixedWidth(300)
            cl = QVBoxLayout(holder)
            cl.setContentsMargins(0, 0, 0, 0)
            cl.setSpacing(4)
            cl.addWidget(BodyLabel(lbl, holder))
            cl.addWidget(spin)
            chips = []
            chip_row = QWidget(holder)
            chl = QHBoxLayout(chip_row)
            chl.setContentsMargins(0, 0, 0, 0)
            chl.setSpacing(4)
            for val, text in presets:
                b = PushButton(text, holder)
                b.setFixedHeight(26)
                b.setFixedWidth(chip_w)
                b.clicked.connect(lambda _c=False, s=spin, v=val: s.setValue(v))
                chips.append(b)
                chl.addWidget(b)
            chips_all.append((lbl, chips))
            cl.addWidget(chip_row)
        # 快捷档按钮留存引用（供自检断言档位起点；见 _selftest_gui）
        self.calib_preset_chips = dict(chips_all)
        blay.addWidget(row(in_col, out_col, None, spacing=16))

        # 校准风格（2026-09-14）：术语级＝只替换名词；整句重写＝理顺机翻腔与断句
        self.calib_style_combo = ComboBox(box)
        self.calib_style_combo.addItems(["术语级（只替换名词，稳妥）",
                                         "整句重写（理顺机翻，双语长片推荐）"])
        self.calib_style_combo.setCurrentIndex(
            1 if str(ai.get("calib_style") or "term") == "rewrite" else 0)
        blay.addWidget(label_row("校准风格", self.calib_style_combo))

        # 联网查证（2026-09-20）：Agent 遇到知识库没有的疑似错形时可自主搜索
        self.calib_web_switch = SwitchButton(box)
        self.calib_web_switch.setChecked(bool(ai.get("calib_web_enabled", False)))
        blay.addWidget(label_row("联网查证", row(self.calib_web_switch, None)))

        # 音画证据（2026-10-12）：Agent 可请求源媒体的音频重转写/抽帧描述，
        # 佐证疑似误听与丢弃候选（对标 FineSub 多模态纠错 harness）。
        # 音频腿要求 ASR 配 OpenAI 兼容端点；画面腿走全局视觉通道。
        self.calib_media_switch = SwitchButton(box)
        self.calib_media_switch.setChecked(bool(ai.get("calib_media_enabled", False)))
        self.calib_media_switch.setToolTip(
            "音画证据：校准时 Agent 可请求源媒体的证据（只读）——\n"
            "· 音频：按 cue 时间轴裁一段音频重转写，回填「第二模型听到了什么」；\n"
            "· 画面：同区间抽帧，回填屏幕文字/界面描述。\n"
            "用于疑似误听（专名/同音词/口误）与丢弃候选的最终确认。\n"
            "要求：① 字幕页已打开源视频；② 音频腿需 ASR 配 OpenAI 兼容端点；\n"
            "③ 画面腿走全局视觉通道。任一缺失自动降级，不打断校准。")
        blay.addWidget(label_row("音画证据", row(self.calib_media_switch, None)))

        # 思考轮次上限（v1.16.1）：每块「思考 → 联网查证 → 再思考」的往返轮数。
        # 0 = 关闭（不限，内部另有 32 轮安全上限兜底防死循环）。
        self.calib_think_rounds = _spin(int(ai.get("calib_think_rounds") or 0),
                                        0, 64, 1, width=200)
        self.calib_think_rounds.setSpecialValueText("关闭（不限）")
        self.calib_think_rounds.setToolTip(
            "每块「思考 → 联网查证 → 再思考」的往返轮数上限：\n"
            "· 0＝关闭（不限；内部仍有 32 轮安全上限防死循环）；\n"
            "· 仅「联网查证」开启时才有意义（没有工具可调就没有往返）；\n"
            "· 日志里的 [x/8] 是校准流水线的 8 个步骤进度，与本项无关。")
        blay.addWidget(label_row("思考轮次上限", self.calib_think_rounds))

        # Agent 集群（v1.16.1，多智能体协作，**默认关闭**）
        self.calib_cluster_switch = SwitchButton(box)
        self.calib_cluster_switch.setChecked(
            bool(ai.get("calib_cluster_enabled", False)))
        self.calib_cluster_switch.checkedChanged.connect(
            self._sync_calib_cluster_visible)
        self.calib_cluster_switch.setToolTip(
            "多智能体协作（Agent Cluster）：把校准拆成「提议 Agent + 评审 Agent」，\n"
            "各角色可走不同端点/密钥/模型；评审不通过不采纳，并可回喂整改。\n"
            "默认关闭——关闭时行为与单智能体完全一致。")
        blay.addWidget(label_row("Agent 集群",
                                 row(self.calib_cluster_switch, None)))

        self.calib_cluster_widget = QWidget(box)
        ccl = QVBoxLayout(self.calib_cluster_widget)
        ccl.setContentsMargins(0, 0, 0, 0)
        ccl.setSpacing(4)
        ccl.addWidget(BodyLabel(
            "集群成员（每行一个：角色|名称|base_url|api_key|模型）",
            self.calib_cluster_widget))
        self.calib_cluster_edit = TextEdit(self.calib_cluster_widget)
        self.calib_cluster_edit.setPlaceholderText(
            "calibrate|主力|https://api.deepseek.com|sk-xxx|deepseek-flash\n"
            "review|评审A|https://open.bigmodel.cn/api/paas/v4|xxx|glm-4.7-flash\n"
            "角色 calibrate=提议 / review=评审；留空的字段回落全局 AI 配置")
        self.calib_cluster_edit.setPlainText(self._cluster_text(ai))
        self.calib_cluster_edit.setFixedHeight(96)
        ccl.addWidget(self.calib_cluster_edit)
        self.calib_cluster_rounds = _spin(int(ai.get("calib_cluster_rounds") or 1),
                                          1, 5, 1, width=200)
        self.calib_cluster_rounds.setToolTip(
            "评审-整改协作轮数：被评审驳回的改动会带着理由回喂提议 Agent 整改，\n"
            "最多往返这么多轮；用尽后仍被驳回的改动直接丢弃（写进报告）。")
        ccl.addWidget(label_row("协作轮数", self.calib_cluster_rounds))
        blay.addWidget(self.calib_cluster_widget)

        calib_save = PrimaryPushButton(FIF.SAVE, "保存并应用", box)
        calib_save.clicked.connect(self._ai_save)
        blay.addWidget(row(calib_save, None))

        self.calib_hint = fit_caption(CaptionLabel(
            "块越小越稳（读不完自动折半重试）；思考关闭更省更快，长片整句重写建议"
            "开「高/极致」；无法用术语知识库解释的改动会被拒绝并写入报告。开启"
            "「联网查证」后，Agent 可对库中没有的疑似错形自主搜索官方名再下结论"
            "（出网走内置代理）", box))
        self.calib_hint.setTextColor("#8a8a8a", "#9a9a9a")
        blay.addWidget(self.calib_hint)
        self.vbox.addWidget(box)
        self._sync_calib_thinking_visible()
        self._sync_calib_cluster_visible()

    @staticmethod
    def _cluster_text(ai):
        """把配置里的集群成员序列化成「角色|名称|base_url|api_key|模型」多行文本。"""
        out = []
        for m in (ai.get("calib_cluster_members") or []):
            if isinstance(m, dict):
                out.append("|".join(str(m.get(k) or "") for k in
                                    ("role", "name", "base_url", "api_key", "model")))
        return "\n".join(out)

    def _sync_calib_cluster_visible(self, *_a):
        """集群关闭时隐藏成员编辑区（默认关闭，界面保持简洁）。"""
        w = getattr(self, "calib_cluster_widget", None)
        if w is not None:
            w.setVisible(self.calib_cluster_switch.isChecked())

    def _sync_calib_thinking_visible(self, *_a):
        """思考模式关闭时隐藏「思考强度」行（强度参数无意义）。"""
        w = getattr(self, "calib_effort_combo", None)
        if w is not None:
            w.setEnabled(self.calib_thinking_switch.isChecked())

    def _collect_ai(self):
        # 2026-10-22：密钥控件不再回填明文，所以「输入框为空」= 用户没改，
        # 必须沿用当前凭据值，否则保存会把密钥清空（下游 apply_global_llm_
        # to_engine 也会拿到空 Key，字幕引擎当场 401）。
        _cur = engine.ai_load_config()
        return {
            "enabled": self.ai_enabled.isChecked(),
            # 全局 AI 单通道（工具箱 / 字幕引擎 / AI 校准共用）
            "api_key": self.ai_key.text().strip() or str(_cur.get("api_key") or ""),
            "base_url": self.ai_base.text().strip(),
            "model": self.ai_model.text().strip(),
            "vision_model": self.ai_vision.text().strip(),
            # ASR：独立 ASR 模型
            "asr_mode": "local" if self.asr_mode_combo.currentIndex() == 1
                        else "service",
            "asr_base_url": self.asr_base.text().strip(),
            "asr_api_key": self.asr_key.text().strip() or str(_cur.get("asr_api_key") or ""),
            "asr_model": self.asr_model.text().strip(),
            "asr_prompt": self.asr_prompt.text().strip(),
            "asr_protocol": self.ASR_PROTO_KEYS[
                min(max(self.asr_proto_combo.currentIndex(), 0),
                    len(self.ASR_PROTO_KEYS) - 1)],
            "asr_local_model": self.asr_local_model.text().strip(),
            "asr_local_model_dir": engine.clean_path(self.asr_local_dir.text()),
            # 说话人分离：服务端原生 diarization（不支持的端点静默忽略）
            "asr_diarize": self.asr_diarize_switch.isChecked(),
            # 语音分离：重叠语音分离 / 剔除歌声（接口占位，尚未内置模型）
            "asr_separate": self.asr_separate_switch.isChecked(),
            # 识别语言（2026-10-25 移到转录页命令栏）：设置页不再提供下拉，
            # 只保留磁盘现值，避免在这里保存其他字段时把转录页选的语言重置。
            "asr_language": (str(_cur.get("asr_language") or "自动检测").strip()
                             or "自动检测"),
            # AI 校准（v1.12.0：通道选择随双通道合并一并移除）
            "calib_chunk_cues": self.calib_cues.value(),
            "calib_max_chars": self.calib_chars.value(),
            "calib_max_tokens": self.calib_tokens.value(),
            # 输入（上下文预算）——2026-09-20 起在设置页可调（此前只能手改文件）
            "calib_context_tokens": self.calib_context.value(),
            # 校准风格（2026-09-14）：term=只替换名词；rewrite=整句重写
            "calib_style": ("rewrite"
                            if self.calib_style_combo.currentIndex() == 1 else "term"),
            # 联网查证（2026-09-20）：AI 校准 Agent 可发起 web_search/web_fetch
            "calib_web_enabled": self.calib_web_switch.isChecked(),
            # 音画证据（2026-10-12）：Agent 可请求源媒体音频重转写/抽帧描述
            "calib_media_enabled": self.calib_media_switch.isChecked(),
            # 思考轮次上限（v1.16.1）：0=关闭（不限）；>0=每块查证往返硬上限
            "calib_think_rounds": self.calib_think_rounds.value(),
            # Agent 集群（v1.16.1，多智能体协作，默认关闭）
            "calib_cluster_enabled": self.calib_cluster_switch.isChecked(),
            "calib_cluster_members": engine.ai_mod().parse_cluster_text(
                self.calib_cluster_edit.toPlainText()),
            "calib_cluster_rounds": self.calib_cluster_rounds.value(),
            # 思考控制（v1.15.7）：随校准请求体 thinking / reasoning_effort 下发
            "calib_thinking": self.calib_thinking_switch.isChecked(),
            "calib_reasoning_effort": self.CALIB_EFFORT_KEYS[
                min(max(self.calib_effort_combo.currentIndex(), 0),
                    len(self.CALIB_EFFORT_KEYS) - 1)],
        }

    def _mark_ai_dirty(self, *_a):
        """AI / ASR 任一字段被编辑 → 亮出「未保存」提示。

        这是"明明配了却说未配置 / 转录报 401 密钥无效"最常见的来源：填完
        不点「保存并应用」，磁盘配置与引擎转录配置都还是上一版（甚至空的）。
        """
        self._ai_dirty = True
        for name in ("ai_dirty_lbl", "asr_dirty_lbl"):
            w = getattr(self, name, None)
            if w is not None:
                w.show()

    def _clear_ai_dirty(self):
        self._ai_dirty = False
        for name in ("ai_dirty_lbl", "asr_dirty_lbl"):
            w = getattr(self, name, None)
            if w is not None:
                w.hide()

    def _is_ai_dirty(self):
        return bool(getattr(self, "_ai_dirty", False))

    def _ai_save(self):
        try:
            engine.ai_save_config(self._collect_ai())
            notes = engine.ai_last_auto_notes()
            self._clear_ai_dirty()
            if notes:
                # 保存时被自动匹配纠正过：必须回填界面，否则界面显示的还是
                # 错的值、用户下次又存一遍错的（这正是"设置错误"反复出现的根源）
                self._reload_ai_fields()
                InfoBar.warning(
                    "已保存（含设置自动匹配）",
                    "已自动纠正：" + "；".join(notes)[:300],
                    duration=8000, position=InfoBarPosition.BOTTOM_RIGHT,
                    parent=self)
            else:
                InfoBar.success(
                    "已保存",
                    "全局 AI 与 ASR 配置已应用：引擎 LLM 槽、转录配置已同步",
                    duration=3000, position=InfoBarPosition.BOTTOM_RIGHT,
                    parent=self)
        except Exception as e:  # noqa: BLE001
            InfoBar.error("保存失败", str(e)[:300], duration=5000,
                          position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        # 保存**已成功**，下面只是合规提示——整体 try 兜底，提示出问题也绝不
        # 影响保存结果（否则会把"已保存"误报成"保存失败"，让人以为配置没落盘）。
        try:
            self._sync_plan_warn()
            risks = engine.ai_plan_risks(engine.ai_load_config())
            if risks:
                # 订阅套餐端点：允许接入，但把条款要点与稳妥替代端点说全（风险自负）。
                # 标题点明「三个地址都查了」，正文每条带【出处】前缀——否则用户会
                # 以为弹窗说的是眼前那张卡片里的地址（实测踩过：全局 AI 填智谱、
                # 弹窗说百炼，只因告警其实来自 ASR 槽）。
                InfoBar.warning(
                    "订阅套餐端点风险提示（全局 AI / 视觉 / ASR 三处地址）",
                    "；".join(risks)[:600],
                    duration=12000, position=InfoBarPosition.BOTTOM_RIGHT,
                    parent=self)
        except Exception:  # noqa: BLE001
            pass

    def _reload_ai_fields(self):
        """把落盘后的 AI 配置回填到界面输入框（自动匹配纠正后调用）。

        2026-10-22 安全整改：密钥字段**一律不回填**（控件文本会进 UI 快照），
        只刷新「已配置」占位提示；非敏感字段照旧回填。
        """
        ai = engine.ai_load_config()
        if getattr(self, "ai_key", None) is not None:
            try:
                self.ai_key.clear()
                self.ai_key.setPlaceholderText(
                    "已配置（存于独立凭据文件；留空则保持不变）"
                    if str(ai.get("api_key") or "") else "API Key")
            except Exception:  # noqa: BLE001
                pass
        for wid, key in ((getattr(self, "ai_base", None), "base_url"),
                         (getattr(self, "ai_model", None), "model"),
                         (getattr(self, "ai_vision", None), "vision_model")):
            if wid is None:
                continue
            try:
                wid.blockSignals(True)       # 回填不算用户编辑，别亮"未保存"
                wid.setText(str(ai.get(key, "")))
            finally:
                try:
                    wid.blockSignals(False)
                except Exception:  # noqa: BLE001
                    pass
        for spin, key in ((getattr(self, "calib_tokens", None),
                           "calib_max_tokens"),
                          (getattr(self, "calib_context", None),
                           "calib_context_tokens")):
            if spin is None:
                continue
            try:
                spin.setValue(int(ai.get(key) or spin.value()))
            except (TypeError, ValueError):
                pass

    def _ai_match(self):
        """「自动匹配」按钮：按当前接口地址纠正模型与预算，并回填界面。

        纯本地计算（不发网络请求），纠正是确定性的规则，所以不必等异步：
        点完立刻能看到改了哪几项；用户再点「保存并应用」落盘。
        """
        try:
            cfg, notes = engine.ai_match_settings(self._collect_ai())
        except Exception as e:  # noqa: BLE001
            InfoBar.error("自动匹配失败", str(e)[:300], duration=5000,
                          position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        self.ai_model.setText(str(cfg.get("model") or ""))
        self.ai_vision.setText(str(cfg.get("vision_model") or ""))
        try:
            self.calib_tokens.setValue(int(cfg.get("calib_max_tokens") or
                                           self.calib_tokens.value()))
            self.calib_context.setValue(int(cfg.get("calib_context_tokens") or
                                            self.calib_context.value()))
        except (TypeError, ValueError):
            pass
        self._mark_ai_dirty()
        if notes:
            InfoBar.success("已自动匹配",
                            "；".join(notes)[:400] + "（点「保存并应用」落盘）",
                            duration=9000, position=InfoBarPosition.BOTTOM_RIGHT,
                            parent=self)
        else:
            InfoBar.info("无需调整",
                         "当前接口地址与模型、预算已自洽（没发现需要纠正的组合）",
                         duration=4000, position=InfoBarPosition.BOTTOM_RIGHT,
                         parent=self)

    def _ai_test(self, channel="a"):
        """测试全局 AI 连通性（v1.12.0 起单通道，channel 参数保留兼容）。"""
        cfg = self._collect_ai()
        InfoBar.info("正在测试", "正在连接全局 AI…", duration=1200,
                     position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
        self._run_bg(lambda: engine.ai_test_connection(cfg),
                     lambda r, e: self._ai_test_done(r, e, "全局 AI"))

    def _asr_test(self):
        """测试 ASR 配置：服务模式校验地址/密钥连通，本地模式校验模型与目录。"""
        cfg = self._collect_ai()
        InfoBar.info("正在测试", "正在检查 ASR 配置…", duration=1200,
                     position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
        self._run_bg(lambda: engine.ai_test_asr(cfg),
                     lambda r, e: self._ai_test_done(r, e, "ASR 语音识别"))

    def _asr_show_examples(self):
        """弹出「非流式调用示例」（curl / Python）。

        用**界面当前值**生成（不必先保存）——用户可以先拿示例把配置跑通，
        再回来点「保存并应用」。
        """
        try:
            AsrExampleDialog(engine.asr_examples(self._collect_ai()),
                             self.window()).exec_()
        except Exception as e:  # noqa: BLE001
            InfoBar.error("无法生成示例", str(e)[:300], duration=5000,
                          position=InfoBarPosition.BOTTOM_RIGHT, parent=self)

    def _ai_test_done(self, result, err, name="AI 接口"):
        if err is not None:
            InfoBar.error(f"{name} 测试失败", str(err)[:300], duration=6000,
                          position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        ok, msg = result
        text = str(msg)[:300]
        if ok and self._is_ai_dirty():
            # 测试用的是界面上的值，转录用的是**已保存**的值 —— 这个错位
            # 最容易被当成"配了却没生效"，所以这里必须说清楚
            text += "（⚠️ 这是界面上的值，还没保存；点「保存并应用」后转录才会用它）"
        (InfoBar.success if ok else InfoBar.error)(
            f"{name} 正常" if ok else f"{name} 不可用", text,
            duration=6000 if not (ok and self._is_ai_dirty()) else 9000,
            position=InfoBarPosition.BOTTOM_RIGHT, parent=self)

    # ------------------------------------------------------------------ #
    # 字幕引擎运行参数（内嵌引擎设置界面，懒加载，隐藏重复分组）
    # ------------------------------------------------------------------ #
    def _build_engine_section(self):
        host = QWidget(self)
        lay = QVBoxLayout(host)
        # 左右边距清零，使内嵌引擎分组与上方/下方的全局卡片严格左右对齐
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(StrongBodyLabel("字幕引擎：转录 / 翻译 / 合成参数", host))
        cap = fit_caption(CaptionLabel(
            "LLM、ASR 与保存位置已上收全局（见上方卡片），这里只保留引擎运行参数",
            host))
        cap.setTextColor("#8a8a8a", "#9a9a9a")
        lay.addWidget(cap)
        self.engine_card = host
        self.engine_holder = QWidget(host)
        self.engine_holder_lay = QVBoxLayout(self.engine_holder)
        self.engine_holder_lay.setContentsMargins(0, 0, 0, 0)
        # 与上游 SettingCardGroup 之间 28px 间距接近，分组之间留出呼吸感
        self.engine_holder_lay.setSpacing(20)
        lay.addWidget(self.engine_holder)
        self.vbox.addWidget(host)

    def _ensure_engine_setting(self):
        """懒加载引擎设置；引擎尚未导入成功时返回 None，下次显示再试。

        布局做法（v1.10.8 修正）：SettingInterface 自身是个滚动区，直接嵌进本页
        会形成双层视口（内层 80px 顶留白、36px 边距、独立滚动条、卡片错位）。
        这里保留它内部全部布局/定高机制（分组高度依赖其 ExpandLayout），只把它
        「拍平成一块」：隐藏大标题与重复分组、关滚动条/边框/内边距，并让其固定
        高度恒等于内容高度，滚动统一交给外层页面，卡片与全局卡片左右对齐。
        """
        if self._engine_built:
            return self._engine_setting
        # 预热期间不要在主线程 import 整棵引擎 UI——那会卡在 Python import
        # 锁上数秒（用户刚启动就点“设置”时的典型卡死）。等后台预热结束再建。
        if not _ENGINE_PREWARM["ui_ready"] and _SCHED["inst"] is not None:
            _start_engine_prewarm()
            _defer("prewarm_done", _engine_prewarm_probe, 0, 3, budget_ms=1)
            _defer("engine_setting", self._ensure_engine_setting, 0, 20,
                   depends_on=("prewarm_done",), budget_ms=900)
            return None
        self._engine_built = True
        try:
            from PySide6.QtWidgets import QFrame
            _home_cls, SettingInterface, is_self, ui_err = _resolve_engine_ui()
            if ui_err:
                _perf_note(f"自研设置页不可用，回退引擎：{ui_err}")
            if SettingInterface is None:
                raise RuntimeError("无可用设置页实现")
            if not is_self:
                engine.engine_ui_brand_patch()
            try:
                setting = SettingInterface(self.engine_holder)
            except Exception as e:  # noqa: BLE001
                if not is_self:
                    raise
                _perf_note(f"自研 SettingInterface 构造失败，回退引擎：{e}")
                from videocaptioner.ui.view.setting_interface import (
                    SettingInterface as _ES)
                engine.engine_ui_brand_patch()
                setting = _ES(self.engine_holder)
            try:
                setting.settingLabel.hide()          # 去掉重复的「设置」大标题
            except Exception:
                pass
            # 隐藏与全局重复或属于上游品牌的分组：
            #   llmGroup      —— LLM 已全局化（全局 AI 卡片）
            #   saveGroup     —— 工作目录已强制软件文件夹、缓存并入全局
            #   personalGroup —— 主题/缩放/语言已在全局「界面」
            #   aboutGroup    —— 上游检查更新/帮助/反馈品牌入口
            for gname in ("llmGroup", "saveGroup", "personalGroup", "aboutGroup"):
                grp = getattr(setting, gname, None)
                if grp is not None:
                    grp.setHidden(True)
            promo = getattr(setting, "openaiOfficialApiCard", None)
            if promo is not None:
                orig = promo.setVisible
                promo.setVisible = lambda _v=True: orig(False)
                orig(False)
            # v1.12.0：字幕翻译板块全面去 AI（仅机翻）——从翻译服务下拉框
            # 移除「LLM 大模型翻译」选项；若引擎 QConfig 当前正选着 LLM，
            # 一并改回「微软翻译」，保证 combo 移除该项后仍有合法选中值。
            # v2.3.1 修两处实测失效（用户报翻译失败文案让查 API key 时发现）：
            # ① 跨类枚举相等恒为 False——``engine_entities.TranslatorServiceEnum``
            #    与 ``videocaptioner.core.entities.TranslatorServiceEnum`` 是两个
            #    类，``==`` 永不成立，旧比较/旧 set 全是死代码（且 set 传异类枚举
            #    还会被 OptionsValidator 拒）。现在一律按**值**比较、用**引擎枚举
            #    成员**赋值；
            # ② 卡片属性名两个设置界面都叫 ``translatorServiceCard``，旧代码找的
            #    ``translateServiceCard`` 不存在——「LLM 大模型翻译」选项因此从来
            #    没被移除过，用户在下拉里选它就会把翻译接进全局 AI。
            try:
                from videocaptioner.core.entities import (
                    TranslatorServiceEnum as _ETE)
                from videocaptioner.ui.common.config import cfg as _vcfg
                _cur_ts = _vcfg.get(_vcfg.translator_service)
                if getattr(_cur_ts, "value", _cur_ts) == _ETE.OPENAI.value:
                    _vcfg.set(_vcfg.translator_service, _ETE.BING)
                ts_card = (getattr(setting, "translatorServiceCard", None)
                           or getattr(setting, "translateServiceCard", None))
                _combo = getattr(ts_card, "comboBox", None) if ts_card else None
                if _combo is not None:
                    for _i in range(_combo.count()):
                        if _combo.itemText(_i) == _ETE.OPENAI.value:
                            _combo.removeItem(_i)
                            break
            except Exception:
                pass
            # v1.12.0：设置板块去重整合 ——
            #   ① 「字幕校正」卡隐藏：校准类功能统一合并到「字幕校准」板块，
            #      不再在字幕处理设置里保留第二入口（引擎工作台的优化开关
            #      仍通过同一配置项生效，功能不受影响）；
            #   ② 「反思翻译」卡隐藏：LLM 四轮反思翻译专属，机翻无意义；
            #   ③ 「翻译服务」与「翻译与优化」两组合并为一个「字幕翻译」组：
            #      翻译服务 → 是否翻译 → 目标语言 → 线程数（→ DeepLx 端点）；
            #   ④ 引擎「转录配置」分组隐藏：ASR 已由全局设置「ASR 语音识别」
            #      卡片统一写进引擎转录配置，此处是重复入口。
            try:
                correct = getattr(setting, "subtitleCorrectCard", None)
                if correct is not None:
                    correct.hide()
                reflect = getattr(setting, "needReflectTranslateCard", None)
                if reflect is not None:
                    reflect.hide()
                # 线程数描述原本面向 LLM 服务商，机翻语境下修正措辞
                tn_card = getattr(setting, "threadNumCard", None)
                if tn_card is not None:
                    tn_card.setContent(
                        "请求并行处理的数量，免费机翻端点已内置全局限速保护，"
                        "设置过大不会更快")
                tr_g = getattr(setting, "transcribeGroup", None)
                if tr_g is not None:
                    tr_g.setHidden(True)
            except Exception:
                pass
            try:
                src_g = getattr(setting, "translate_serviceGroup", None)
                dst_g = getattr(setting, "translateGroup", None)
                if src_g is not None and dst_g is not None:
                    order = ["translatorServiceCard", "subtitleTranslateCard",
                             "targetLanguageCard", "threadNumCard",
                             "deeplxEndpointCard"]
                    dst_lay = dst_g.cardLayout
                    dst_ws = getattr(dst_lay, "_ExpandLayout__widgets", None)
                    # 卡片换组必须同时从「原组」的 ExpandLayout 摘除：
                    # setParent 不会把控件从旧布局的 __widgets 里移走，旧组
                    # 一旦再跑 setGeometry/eventFilter，就会用旧组的坐标系
                    # 给已搬走的卡片摆位置——卡片浮到页面左上角、盖住分组
                    # 标题（v1.15.x「字幕翻译」组重叠 bug 的根因）。
                    src_lay = src_g.cardLayout
                    src_ws = getattr(src_lay, "_ExpandLayout__widgets", None)
                    for _idx, _name in enumerate(order):
                        _card = getattr(setting, _name, None)
                        if _card is None:
                            continue
                        if src_ws is not None and _card in src_ws:
                            src_ws.remove(_card)
                            _card.removeEventFilter(src_lay)
                        _card.setParent(dst_g)
                        if dst_ws is None:        # 兜底：退化为追加
                            dst_g.addSettingCard(_card)
                            continue
                        if _card in dst_ws:
                            dst_ws.remove(_card)
                        dst_ws.insert(min(_idx, len(dst_ws)), _card)
                        _card.installEventFilter(dst_lay)
                    dst_g.titleLabel.setText("字幕翻译")
                    dst_g.titleLabel.adjustSize()
                    dst_g.adjustSize()
                    # 原翻译服务分组已搬空：隐藏并塌缩占位
                    src_g.setHidden(True)
                    src_g.adjustSize()
            except Exception:
                pass
            # —— 消除内层独立视口：无滚条、无边框、零边距、与全局卡片同宽 —— #
            try:
                setting.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                setting.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            except Exception:
                pass
            try:
                setting.setFrameShape(QFrame.NoFrame)
            except Exception:
                pass
            try:
                setting.setViewportMargins(0, 0, 0, 0)
            except Exception:
                pass
            try:  # 与本页其它卡片左右对齐、分组间距统一
                setting.expandLayout.setContentsMargins(0, 0, 0, 0)
                setting.expandLayout.setSpacing(20)
            except Exception:
                pass
            self.engine_holder_lay.addWidget(setting)
            # v1.13.0：引擎设置界面构造时被上游硬编码 resize(1000, 800)，且其
            # 内容按独立窗口尺寸设计——嵌进比它窄的宿主页时会把卡片撑出可视
            # 范围、右侧被裁（设置页「扭曲」的根源）。这里放开最小宽度并把
            # 水平策略改为 Expanding，让宽度跟随宿主卡片；内容卡片是弹性的，
            # 会跟着一起收窄（实测：父容器 793 时界面随之为 793）。
            try:
                setting.setMinimumWidth(0)
                _sp = setting.sizePolicy()
                _sp.setHorizontalPolicy(QSizePolicy.Expanding)
                setting.setSizePolicy(_sp)
            except Exception:
                pass
            # 内层固定高度跟随内容，滚动交给外层
            self._engine_fit = _InnerScrollToContent(setting, self.engine_holder)
            sw = setting.widget()
            if sw is not None:
                sw.installEventFilter(self._engine_fit)
            # 内容完成布局时滚动范围必变，是比定时器更可靠的高度触发源
            try:
                setting.verticalScrollBar().rangeChanged.connect(
                    lambda *_a: self._engine_fit.sync_height())
            except Exception:
                pass

            def _later_fit():
                try:
                    self._engine_fit.sync_height()
                    # v1.13.0：宽度跟随宿主（布局激活后刷新一次，防 1000px 残留）
                    setting.updateGeometry()
                except Exception:
                    pass

            # 初始化期卡片会按默认选项显隐，分几次把高度钉准
            QTimer.singleShot(0, _later_fit)
            QTimer.singleShot(120, _later_fit)
            QTimer.singleShot(500, _later_fit)
            self._engine_setting = setting
            try:
                engine.vc_enforce_runtime_cfg()
            except Exception:
                pass
            # 内嵌引擎设置界面会带入它自己的字体与缩放，导航宽度再收敛一次
            try:
                self.window().refresh_nav_width()
            except Exception:
                pass
        except Exception as e:  # noqa: BLE001
            # 引擎仍在后台预热：放开标记，下次 showEvent 再试
            self._engine_built = False
            tip = fit_caption(CaptionLabel(
                f"字幕引擎仍在预热中，稍后回到本页即可查看（{e}）",
                self.engine_holder))
            tip.setTextColor("#8a8a8a", "#9a9a9a")
            self.engine_holder_lay.addWidget(tip)
        return self._engine_setting

    def scroll_to_engine(self):
        """外部调用：定位到字幕引擎参数区（并确保其已构建）。"""
        self._ensure_engine_setting()
        QTimer.singleShot(0, self._scroll_to_engine_card)

    def _scroll_to_engine_card(self):
        try:
            if self.shell.area is not None:
                self.shell.area.ensureWidgetVisible(self.engine_card, 0, 80)
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # 校准知识同步（界面只有「更新」；上传全自动、隐藏在后台退出时完成）
    # ------------------------------------------------------------------ #
    def _build_sync_card(self):
        box, blay = card(
            "校准知识同步",
            "「更新」从共享仓库拉取全体使用者沉淀的校准知识并在本地合并"
            "（启动时也会自动更新一次）；你校准学到的新内容会在退出程序时"
            "自动上传，全程无需操作、不占用界面。基线整理与过期清理由"
            "管理员独立程序（kb_admin.exe）负责")
        self.sync_switch = SwitchButton(box)
        self.sync_switch.setChecked(engine.calib_sync_enabled())
        self.sync_switch.checkedChanged.connect(self._on_sync_toggle)
        blay.addWidget(label_row("启用自动同步（启动自动更新 + 退出后台上传）",
                                 row(self.sync_switch, None)))

        pull_btn = PushButton(FIF.SYNC, "立即更新", box)
        pull_btn.clicked.connect(self._sync_now)
        blay.addWidget(row(pull_btn, None))

        self.sync_hint = fit_caption(CaptionLabel(
            "只上传校准产生的增量知识、不触碰程序代码；合并确定性幂等，"
            "多用户最终收敛到全体条目的并集",
            box))
        self.sync_hint.setTextColor("#8a8a8a", "#9a9a9a")
        blay.addWidget(self.sync_hint)
        self.vbox.addWidget(box)

    def _on_sync_toggle(self, checked):
        try:
            engine.set_calib_sync_enabled(bool(checked))
            InfoBar.success("已更新", "自动同步已" + ("启用" if checked else "关闭"),
                            duration=2500, position=InfoBarPosition.BOTTOM_RIGHT,
                            parent=self)
        except Exception as e:  # noqa: BLE001
            InfoBar.error("设置失败", str(e)[:200], duration=4000,
                          position=InfoBarPosition.BOTTOM_RIGHT, parent=self)

    def _sync_now(self):
        InfoBar.info("正在更新", "正在从共享仓库拉取校准知识与声纹模板并合并…",
                     duration=1200,
                     position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
        self._run_bg(self._sync_both_channels, self._sync_done)

    def _sync_both_channels(self):
        """设置页「立即更新」：校准知识与声纹模板**两条独立通道**都走一遍。

        声纹通道失败不影响校准结果（各自独立、各自记日志）；返回值仍是校准
        通道的 (ok, msg)，供 _sync_done 原样显示。"""
        try:
            engine.sync_voiceprint_on_startup(force=True)
        except Exception:  # noqa: BLE001
            pass
        return engine.sync_calib_on_startup(force=True)

    # ------------------------------------------------------------------ #
    # 程序更新（v2.0.0）：检测 → 用户确认 → 下载 → 退出替换自身
    # ------------------------------------------------------------------ #
    def _build_update_card(self):
        box, blay = card(
            "程序更新",
            "检查视频工具箱是否有新版本并在本机直接更新（任意版本之间"
            "可升可降；升/降以当前运行版本为基准判断）；源码运行模式下"
            "以本地开发版为准，不自动安装。启动时也会自动检查一次，"
            "仅在有真正的新版本时提示，全程不打扰日常使用")
        self.upd_ver_label = BodyLabel("当前版本 v%s" % VERSION, box)
        blay.addWidget(row(self.upd_ver_label, None))

        self.upd_btn = PushButton(FIF.SYNC, "检查更新", box)
        self.upd_btn.clicked.connect(self._check_update_manual)
        blay.addWidget(row(self.upd_btn, None))

        self.upd_hint = fit_caption(CaptionLabel(
            "更新会下载新版本并在你确认后替换程序文件，完成后自动重新打开；"
            "更新前请先关闭正在进行的下载或字幕处理任务",
            box))
        self.upd_hint.setTextColor("#8a8a8a", "#9a9a9a")
        blay.addWidget(self.upd_hint)
        self.vbox.addWidget(box)

    def _check_update_manual(self):
        """设置页「检查更新」按钮：手动触发一次检测（不受启动节流限制）。"""
        if getattr(self, "_upd_running", False):
            return
        self._upd_running = True
        self.upd_btn.setEnabled(False)
        self.upd_btn.setText("检查中…")
        self._run_bg(self._do_check_update, self._check_update_done)

    def _do_check_update(self):
        """后台线程：跑检测。网络请求可能几十秒，绝不能在界面线程跑。"""
        try:
            return vt_update_check.check_update()
        except Exception as e:  # noqa: BLE001 —— 顶层兜底，别让后台线程静默死掉
            r = vt_update_check.CheckResult()
            r.err = str(e)
            return r

    def _check_update_done(self, result, err):
        self._upd_running = False
        self.upd_btn.setEnabled(True)
        self.upd_btn.setText("检查更新")
        if err is not None:
            InfoBar.error("检查失败", str(err)[:300], duration=6000,
                          position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        r = result
        if not r.ok:
            InfoBar.warning("检查更新失败", r.err[:300], duration=6000,
                            position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        if getattr(r, "source_mode", False):
            # 源码运行没有可替换的程序本体：以本地开发版为准，不写自动
            # 检查状态、也不弹更新确认框。
            msg = "以本地开发版 v%s 为准" % r.baseline_ver
            if r.remote_differs():
                if r.downgrade():
                    msg += "；远端 v%s（低于本地）" % r.remote_ver
                else:
                    msg += "；远端 v%s 可用，请手动更新源码" % r.remote_ver
            InfoBar.info("源码运行模式", msg, duration=6000,
                         position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        vt_update_check.note_auto_checked(r.remote_ver, r.update)
        if not r.update:
            InfoBar.success("已是最新", "当前 v%s 已是最新版本" % r.baseline_ver,
                            duration=4000,
                            position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        # 手动检查不受「以后再说」影响：用户主动点了就给结果。
        self._confirm_update(r)

    def _confirm_update(self, r):
        """弹出更新确认框；同意则开始下载。"""
        dlg = QMessageBox(self)
        # 标题文案由版本方向决定（全新安装 / 升级 / 降级），不再一律
        # 「发现新版本」——运行 v2.0.0 时远端 v1.19.0 是降级不是新版本
        label = r.action_label()
        dlg.setWindowTitle(label)
        dlg.setText("%s %s" % (label, r.remote_ver))
        lines = list(r.detail_lines())
        ok_in_proc, why = vt_update_check.update_available_in_process()
        if not ok_in_proc:
            # 源码运行 / 只读位置：先说清楚会装到哪、为什么不会替换
            # 正在运行的程序，别等几十 MB 下完才告知
            lines.extend(vt_update_check.wrap_lines([
                "",
                "注意：%s。" % why,
                "本次只会把新版本安装到：%s"
                % (r.install_dir or "默认安装目录"),
            ]))
        dlg.setInformativeText("\n".join(lines))
        # detail_lines 已按 30 列折行；给个下限宽度防止 informativeText
        # 被 QMessageBox 的尺寸策略裁掉（截断在半个字形上）
        dlg.setMinimumWidth(520)
        yes = PushButton("立即更新", dlg)
        no = PushButton("以后再说", dlg)
        dlg.addButton(yes, QMessageBox.AcceptRole)
        dlg.addButton(no, QMessageBox.RejectRole)
        dlg.setDefaultButton(no)
        dlg.exec_()
        if dlg.clickedButton() is not yes:
            vt_update_check.record_declined(r.remote_ver)
            InfoBar.info("已跳过", "不再提示 v%s；随时可在设置页点「检查更新」"
                         % r.remote_ver, duration=4000,
                         position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        self._start_update(r)

    def _start_update(self, r):
        """开始下载更新（后台线程，带取消）。"""
        self._upd_result = r
        self._upd_cancel = threading.Event()
        # 标题动词跟着方向走：全新安装 / 回滚 / 升级
        verb = ("正在安装" if r.full else
                ("正在回滚到" if r.downgrade() else "正在更新到"))
        dlg = UpdateProgressDialog(
            self, "%s v%s" % (verb, r.remote_ver),
            "准备下载…\n更新过程中请勿关闭程序",
            on_cancel=lambda: self._upd_cancel.set())
        self._upd_dlg = dlg
        dlg.show()
        self._run_bg(self._do_apply_update, self._apply_update_done)

    def _do_apply_update(self):
        """后台线程：下载 + 校验 + 落地。"""
        r = self._upd_result

        def progress(stage, done, total):
            if self._upd_dlg:
                self._upd_dlg.update_progress(stage, done, total)

        return vt_update_check.apply_update(
            r, progress=progress,
            log=lambda m: self._upd_dlg.append_log(m) if self._upd_dlg else None,
            cancel=self._upd_cancel)

    def _apply_update_done(self, result, err):
        dlg = getattr(self, "_upd_dlg", None)
        if dlg:
            dlg.close()
            dlg.deleteLater()
            self._upd_dlg = None
        if err is not None:
            InfoBar.error("更新失败", str(err)[:300], duration=8000,
                          position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        if self._upd_cancel.is_set():
            InfoBar.info("已取消", "更新已取消，程序保持当前版本", duration=4000,
                         position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        InfoBar.success("更新已就绪",
                        "文件已更新完毕，程序将退出并自动重新打开", duration=5000,
                        position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
        # 落地后需要替换运行中的 exe：派发脚本，等主进程退出后再换。
        self._schedule_self_replace()

    def _schedule_self_replace(self):
        """派发自替换脚本；失败则提示用户手动重装（不要静默失败）。"""
        ok, msg = vt_update_check.schedule_relaunch()
        if not ok:
            InfoBar.error("无法自动替换",
                          "%s\n文件已下载完成，请关闭程序后运行在线安装器完成替换"
                          % msg, duration=0,
                          position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        QTimer.singleShot(1200, QApplication.instance().quit)

    # ---- 启动时自动检测（无新版本则完全不打扰）---- #

    def auto_check_update(self):
        """启动后静默检测一次（供 main() 调用；不是设置页方法）。

        · 源码运行模式：以本地开发版为准，启动时不请求远端；
        · 有节流：距上次询问不足 12 小时不重复发请求；
        · 用户拒绝过的同一版本不再提示；
        · 失败完全静默——更新功能不可用不该在启动时打扰用户。
        """
        if not getattr(sys, "frozen", False):
            return
        try:
            if not vt_update_check.should_auto_check():
                return
        except Exception:  # noqa: BLE001
            return
        self._run_bg(self._do_check_update, self._auto_check_done)

    def _auto_check_done(self, result, err):
        if err is not None or result is None or not getattr(result, "ok", False):
            # 静默失败，但仍记时间戳：远端挂掉不该导致每次启动都重试
            try:
                vt_update_check.note_auto_checked("", False)
            except Exception:  # noqa: BLE001
                pass
            return
        r = result
        if getattr(r, "source_mode", False):
            return
        vt_update_check.note_auto_checked(r.remote_ver, r.update)
        if not r.update or vt_update_check.user_declined(r.remote_ver):
            return
        if r.downgrade() or not r.remote_differs():
            # 远端比当前旧（回滚）、或同版本只存在安装记录/文件差异：
            # 启动时别拿「发现新版本」扰民。想修复的用户会去设置页手动检查。
            return
        InfoBar.info("发现新版本",
                     "v%s 可用（当前 v%s），可在设置页点「检查更新」立即升级"
                     % (r.remote_ver, r.baseline_ver), duration=10000,
                     position=InfoBarPosition.BOTTOM_RIGHT, parent=self)

    def _sync_done(self, result, err):
        if err is not None:
            InfoBar.error("同步失败", str(err)[:300], duration=6000,
                          position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        ok, msg = result
        (InfoBar.success if ok else InfoBar.warning)(
            "同步完成" if ok else "同步未执行", str(msg)[:300], duration=6000,
            position=InfoBarPosition.BOTTOM_RIGHT, parent=self)

    # ------------------------------------------------------------------ #
    # 界面
    # ------------------------------------------------------------------ #
    def _build_appearance_card(self):
        box, blay = card("界面", "主题与缩放；缩放立即生效，主题重启后完全生效")
        self.theme_combo = ComboBox(box)
        self.theme_combo.addItems(["深色", "浅色", "跟随系统"])
        from vt_fluent import isDarkTheme
        self.theme_combo.setCurrentIndex(0 if isDarkTheme() else 1)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        blay.addWidget(label_row("主题", row(self.theme_combo, None)))
        self.zoom_combo = ComboBox(box)
        self.zoom_combo.addItems(["自动（跟随系统）", "100%", "125%", "150%",
                                  "175%", "200%"])
        self.zoom_combo.setCurrentIndex(0)
        self.zoom_combo.currentIndexChanged.connect(self._on_zoom_changed)
        blay.addWidget(label_row("界面缩放", row(self.zoom_combo, None)))
        self.mica_switch = SwitchButton(box)
        self.mica_switch.setChecked(ui_theme.get_mica())
        self.mica_switch.checkedChanged.connect(self._on_mica_changed)
        blay.addWidget(label_row("云母特效", row(self.mica_switch, None)))

        # 主题色：预设色板点选，立即 setThemeColor + 重应用全局 QSS + 持久化
        # （按钮/开关跟随 qfluentwidgets 主题色，输入框聚焦/滑杆/进度条跟随全局 QSS）
        # 圆点用自绘 AccentDot（见类注释）——qfluentwidgets PushButton 的
        # QSS 首帧不生效 + 主题重刷覆盖，正是「必须点击一次才显示」的根源
        self._accent_btns = {}
        accent_holder = QWidget(box)
        ah = QHBoxLayout(accent_holder)
        ah.setContentsMargins(0, 0, 0, 0)
        ah.setSpacing(6)
        for hexc in ui_theme.ACCENT_PRESETS:
            b = AccentDot(hexc, accent_holder)
            b.setToolTip(hexc)
            b.clicked.connect(lambda _=False, c=hexc: self._on_accent_picked(c))
            self._accent_btns[hexc] = b
            ah.addWidget(b)
        ah.addStretch(1)
        blay.addWidget(label_row("主题色", accent_holder))
        self._refresh_accent_ring()
        self.vbox.addWidget(box)

    def _style_accent_btn(self, b, hexc, selected):
        """色板圆点：自绘 AccentDot，选中描白圈，未选中无边框。

        AccentDot 无 QSS 无样式缓存，set_selected 即时 update 生效，
        首帧即为最终效果——不再需要 unpolish/polish 兜底。
        """
        b.set_dot_color(hexc)
        b.set_selected(selected)

    def _refresh_accent_ring(self):
        cur = ui_theme.get_accent().upper()
        for hexc, b in self._accent_btns.items():
            self._style_accent_btn(b, hexc, hexc.upper() == cur)

    def _on_accent_picked(self, hexc):
        ui_theme.set_accent(hexc)
        self._refresh_accent_ring()
        InfoBar.success("主题色已更新", hexc, duration=1800,
                        position=InfoBarPosition.BOTTOM_RIGHT, parent=self)

    def _on_mica_changed(self, checked):
        """云母特效开关：立即启/停主窗口 Mica 并持久化。

        Win10 无 Mica（qfluentwidgets 直接 return），此时开关同步回窗口
        实际状态并提示，避免"切了没反应"的困惑。
        """
        win = self.app
        try:
            win.setMicaEffectEnabled(bool(checked))
        except Exception:
            pass
        actual = bool(win.isMicaEffectEnabled())
        if actual != bool(checked):
            self.mica_switch.blockSignals(True)
            self.mica_switch.setChecked(actual)
            self.mica_switch.blockSignals(False)
            InfoBar.warning(
                "云母特效", "当前系统不支持云母特效（需要 Windows 11）",
                duration=3000, position=InfoBarPosition.BOTTOM_RIGHT,
                parent=self)
            return
        ui_theme.set_mica(bool(checked))

    # ------------------------------------------------------------------ #
    # 界面美化：每个板块自定义背景图（v1.13.x，能力实现在 ui_theme.py）
    # ------------------------------------------------------------------ #
    def _build_uicustom_card(self):
        box, blay = card(
            "界面美化",
            "每个板块可单独设置背景图；未单独设置的板块使用全局背景，"
            "全局也未设置时保持纯色（即现状）。背景遮罩跟随主题：深色"
            "主题压暗、浅色主题雾白，配合可选模糊保证前景文字可读。"
            "「板块遮罩」对每个板块（卡片）统一生效：底色按同一透明度"
            "绘制、透出背景，六页风格一致。支持把图片直接拖进输入框")

        def _make_row(key, name, placeholder):
            edit = _BgPathEdit(lambda p, k=key: self._drop_apply_bg(k, p), box)
            edit.setPlaceholderText(placeholder)
            edit.setText(ui_theme.get_bg(key))
            edit.editingFinished.connect(
                lambda k=key, e=edit: self._on_bg_path_edited(k, e))
            browse = PushButton(FIF.FOLDER, "浏览…", box)
            # ⚠️ clicked 会传出 checked 布尔参数：lambda 首参必须显式接住，
            # 否则 k=checked（False）——set_bg(False,…) 直接 return，
            # 表现即「点浏览/清除毫无反应」（v1.13.4 修复）
            browse.clicked.connect(
                lambda _checked=False, k=key, e=edit: self._pick_bg(k, e))
            clear = PushButton(FIF.DELETE, "清除", box)
            clear.clicked.connect(
                lambda _checked=False, k=key, e=edit: self._clear_bg(k, e))
            expand_h(edit)
            blay.addWidget(srow(name, edit, browse, clear))
            return edit

        self.bg_global_edit = _make_row(
            "global", "全局背景", "未设置（所有板块保持纯色背景）")
        self.bg_page_edits = {}
        for key, name in ui_theme.PAGE_DEFS:
            self.bg_page_edits[key] = _make_row(
                key, name + "背景", "未设置（使用全局背景）")

        self.bg_dim_slider = Slider(Qt.Horizontal, box)
        self.bg_dim_slider.setRange(0, ui_theme.DIM_MAX)
        self.bg_dim_slider.setValue(ui_theme.get_dim())
        self.bg_dim_slider.setMinimumWidth(200)
        self.bg_dim_lbl = BodyLabel(f"{ui_theme.get_dim()}%", box)
        self.bg_dim_slider.valueChanged.connect(self._on_bg_dim_changed)
        blay.addWidget(srow("背景遮罩", self.bg_dim_slider, self.bg_dim_lbl))

        # 板块遮罩（v1.14.x）：与背景图无关，画在每个卡片（UICard）底色的
        # alpha 上——卡片统一半透明、透出背景，六个板块风格一致。
        # （深色压暗、浅色雾白由卡片 token 色本身决定）
        self.sec_dim_slider = Slider(Qt.Horizontal, box)
        self.sec_dim_slider.setRange(0, ui_theme.SECTION_DIM_MAX)
        self.sec_dim_slider.setValue(ui_theme.get_section_dim())
        self.sec_dim_slider.setMinimumWidth(200)
        self.sec_dim_lbl = BodyLabel(f"{ui_theme.get_section_dim()}%", box)
        self.sec_dim_slider.valueChanged.connect(self._on_sec_dim_changed)
        blay.addWidget(srow("板块遮罩", self.sec_dim_slider, self.sec_dim_lbl))

        # 背景模糊（v1.13.x）：预模糊一次并缓存，开关切换不拖累重绘；
        # 大图/亮图模糊后更衬前景文字
        self.bg_blur_switch = SwitchButton(box)
        self.bg_blur_switch.setChecked(ui_theme.get_blur())
        self.bg_blur_switch.checkedChanged.connect(self._on_bg_blur_changed)
        blay.addWidget(label_row("背景模糊", row(self.bg_blur_switch, None)))

        blay.addWidget(fit_caption(CaptionLabel(
            "提示：背景只铺内容区，导航条与标题栏保持原样；"
            "字幕编辑页的视频画面不受影响", box)))
        self.vbox.addWidget(box)

    def _refresh_bg_edits(self):
        """把「界面美化」各输入框/滑杆/开关与当前配置对齐（防界面残留旧值）。"""
        self.bg_global_edit.setText(ui_theme.get_bg("global"))
        for key, edit in self.bg_page_edits.items():
            edit.setText(ui_theme.get_bg(key))
        dim = ui_theme.get_dim()
        self.bg_dim_slider.blockSignals(True)
        self.bg_dim_slider.setValue(dim)
        self.bg_dim_slider.blockSignals(False)
        self.bg_dim_lbl.setText(f"{dim}%")
        sdim = ui_theme.get_section_dim()
        self.sec_dim_slider.blockSignals(True)
        self.sec_dim_slider.setValue(sdim)
        self.sec_dim_slider.blockSignals(False)
        self.sec_dim_lbl.setText(f"{sdim}%")
        self.bg_blur_switch.blockSignals(True)
        self.bg_blur_switch.setChecked(ui_theme.get_blur())
        self.bg_blur_switch.blockSignals(False)

    def _on_bg_dim_changed(self, value):
        """背景遮罩滑杆：改百分比标签 + 立即重绘 + 持久化（写入很小，不怕高频）。"""
        self._warn_no_bg_once()
        self.bg_dim_lbl.setText(f"{value}%")
        ui_theme.set_dim(value)

    def _on_sec_dim_changed(self, value):
        """板块遮罩滑杆：每个卡片底色统一半透明——立即重绘 + 持久化。"""
        self.sec_dim_lbl.setText(f"{value}%")
        ui_theme.set_section_dim(value)

    def _on_bg_blur_changed(self, checked):
        """背景模糊开关：立即重绘（模糊结果按文件缓存，首次稍慢半秒）。"""
        self._warn_no_bg_once()
        ui_theme.set_blur(bool(checked))

    def _warn_no_bg_once(self):
        """一张背景图都没有时，暗化/模糊不会有任何可见变化——仅提示一次。"""
        if self._bg_warned or ui_theme.has_any_bg():
            return
        self._bg_warned = True
        InfoBar.info(
            "背景未设置",
            "当前未设置任何背景图：请先在上方为板块选择背景图，"
            "遮罩与模糊才会生效", duration=4000,
            position=InfoBarPosition.BOTTOM_RIGHT, parent=self)

    def _info_bg_applied(self, key):
        """背景图设置成功后的可见反馈（设置页自身无背景，不提示就看不出变化）。"""
        name = dict(ui_theme.PAGE_DEFS).get(key, "全局")
        InfoBar.success(
            "背景已应用", f"已为「{name}」设置背景图，切换到对应板块即可查看",
            duration=3200, position=InfoBarPosition.BOTTOM_RIGHT, parent=self)

    def _on_bg_path_edited(self, key, edit):
        """手输路径回车/失焦：有效则应用（有反馈）；无效弹明确提示并回填。

        此前是静默回填——用户路径打错（或填了文件夹）时毫无提示，
        表现为「填了图却不生效、回头一看又变回未设置」。
        """
        path = self._normalize_bg_path(edit.text())
        if not path:
            # 清空回车 = 清除该板块背景（与「清除」按钮等效）
            ui_theme.set_bg(key, "")
            return
        if not os.path.isfile(path):
            InfoBar.error(
                "背景图路径无效", f"找不到该文件：{path}",
                duration=6000, position=InfoBarPosition.BOTTOM_RIGHT,
                parent=self)
            edit.setText(ui_theme.get_bg(key))
            return
        ui_theme.set_bg(key, path)
        self._info_bg_applied(key)

    def _normalize_bg_path(self, raw):
        """背景图路径规范化：去引号/空白、接受 file:/// 前缀、统一分隔符。"""
        p = (raw or "").strip().strip('"').strip()
        if not p:
            return ""
        if p.lower().startswith("file:"):
            p = QUrl(p).toLocalFile() or p
        try:
            p = os.path.normpath(p)
        except Exception:  # noqa: BLE001
            pass
        return p

    def _drop_apply_bg(self, key, path):
        """拖入图片直接应用（dragEnter 已确保是存在的本地文件）。"""
        ui_theme.set_bg(key, path)
        self._info_bg_applied(key)

    def _pick_bg(self, key, edit):
        start = os.path.dirname(ui_theme.get_bg(key)) or engine.DATA_DIR
        path, _ = QFileDialog.getOpenFileName(
            self, "选择背景图片", start,
            "图片 (*.png *.jpg *.jpeg *.bmp *.webp)")
        if not path:
            return
        edit.setText(path)
        ui_theme.set_bg(key, path)
        self._info_bg_applied(key)

    def _clear_bg(self, key, edit):
        edit.clear()
        ui_theme.set_bg(key, "")

    # ------------------------------------------------------------------ #
    # 关于
    # ------------------------------------------------------------------ #
    def _build_about_card(self):
        box, blay = card("关于", f"视频工具箱 v{VERSION}")
        blay.addWidget(row(BodyLabel(
            "内置第三方字幕引擎，许可与来源见 docs\\ 下声明文件"), None))
        lic = PushButton(FIF.CERTIFICATE, "打开许可全文", box)
        lic.clicked.connect(self._open_license)
        src = PushButton(FIF.DOCUMENT, "查看组件来源", box)
        src.clicked.connect(self._open_source)
        blay.addWidget(row(lic, src, None))
        self.vbox.addWidget(box)

    # ------------------------------------------------------------------ #
    # 后台任务（线程执行 + 主线程 QTimer 回收，避免网络调用卡住界面）
    # ------------------------------------------------------------------ #
    def _run_bg(self, work, done):
        box = {}

        def worker():
            try:
                box["r"] = work()
            except Exception as e:  # noqa: BLE001
                box["e"] = e

        threading.Thread(target=worker, daemon=True).start()
        timer = QTimer(self)
        timer.setInterval(120)

        def poll():
            if "r" in box or "e" in box:
                timer.stop()
                timer.deleteLater()
                done(box.get("r"), box.get("e"))

        timer.timeout.connect(poll)
        timer.start()

    # ------------------------------------------------------------------ #
    # 槽函数
    # ------------------------------------------------------------------ #
    def _on_dl_max_changed(self, value):
        n = max(1, min(6, int(value)))
        try:
            cfg = engine.load_config()
            cfg["download_max_concurrent"] = n
            engine.save_config(cfg)
        except Exception:
            pass
        try:
            dp = _lazy_real(getattr(self.app, "download_page", None))
            if dp is not None:
                dp.apply_max_concurrent(n, save=False)
        except Exception:
            pass

    def _on_dir_changed(self):
        path = self.dir_edit.text().strip()
        if path:
            engine.set_saved_download_dir(path)
            pw = self.app.page_by_key("download") if hasattr(self.app, "page_by_key") else None
            if pw is not None and hasattr(pw, "dest_edit"):
                pw.dest_edit.setText(path)

    def _browse_dir(self):
        d = QFileDialog.getExistingDirectory(self, "选择下载目录",
                                             self.dir_edit.text() or engine.DATA_DIR)
        if d:
            self.dir_edit.setText(d)
            self._on_dir_changed()

    def _apply_data_root(self):
        path = self.data_edit.text().strip().strip('"')
        if not path:
            self._reset_data_root()
            return
        ok, msg = engine.set_data_root(path, migrate=True)
        if ok:
            InfoBar.success("数据目录已切换", msg, duration=4000,
                            position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            root, _is_default, src = engine.data_root_info()
            self.data_edit.setText(root)
            self.data_hint.setText(f"当前：{src}")
            self._refresh_data_leftover()
        else:
            InfoBar.error("切换失败", msg, duration=5000,
                          position=InfoBarPosition.BOTTOM_RIGHT, parent=self)

    def _reset_data_root(self):
        ok, msg = engine.set_data_root(engine.APP_DIR, migrate=False)
        if ok:
            InfoBar.success("已还原默认数据目录", msg, duration=4000,
                            position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            self.data_edit.setText(engine.APP_DIR)
            self.data_hint.setText("当前：默认（程序目录）")
            self._refresh_data_leftover()
        else:
            InfoBar.error("还原失败", msg, duration=5000,
                          position=InfoBarPosition.BOTTOM_RIGHT, parent=self)

    def _refresh_data_leftover(self):
        try:
            left = engine.vc_legacy_leftovers()
        except Exception:
            left = []
        if left:
            self.data_leftover.setText(
                "检测到系统盘仍有旧版字幕引擎数据：" + "；".join(left) +
                "　（下次启动会自动迁移到数据目录）")
            self.data_leftover.show()
        else:
            self.data_leftover.hide()

    def _on_theme_changed(self, idx):
        # 主题档切换单链走 ui_theme.set_theme_mode（其内部已 setTheme(qtheme)
        # + lazy 刷新 + plain accent 逐控件同步 + 深度重绘）。不要再裸调
        # setTheme——① 无 lazy 的全量刷新在满注册面（~2233 控件）实测 43s；
        # ② updateStyleSheet 历史只捕 RuntimeError，一个坏控件会中断全局
        # 刷新，其余控件既没刷新也没打 dirty（2026-10-20 复现实锤：切档后
        # 670/705 个注册控件停旧档，只能等偶然的鼠标交互补救）。
        # 持久化主题档（深色/浅色/跟随系统），重启保持（v1.13.x 界面美化）
        try:
            ui_theme.set_theme_mode(["dark", "light", "auto"][idx])
        except Exception:
            pass

    def _on_zoom_changed(self, idx):
        """界面缩放档位记进引擎配置 dpiScale，下次启动生效。"""
        if idx <= 0:
            return
        pct = [100, 100, 125, 150, 175, 200][idx]
        try:
            from videocaptioner.ui.common.config import cfg
            cfg.set(cfg.dpiScale, pct)
        except Exception:
            pass
        InfoBar.success("缩放设置已保存", "重新启动后生效", duration=2500,
                        position=InfoBarPosition.BOTTOM_RIGHT, parent=self)

    def _open_license(self):
        if os.path.isfile(engine.VC_LICENSE_FILE):
            try:
                os.startfile(engine.VC_LICENSE_FILE)   # noqa: S606
                return
            except OSError:
                pass
        MessageBox("第三方组件许可", "未找到许可文件（docs/VideoCaptioner_GPL-3.0.txt）。",
                   self).exec()

    def _open_source(self):
        if os.path.isfile(engine.VC_SOURCE_FILE):
            try:
                os.startfile(engine.VC_SOURCE_FILE)   # noqa: S606
                return
            except OSError:
                pass
        MessageBox("第三方组件来源", "未找到来源声明（docs/VideoCaptioner_组件来源.txt）。",
                   self).exec()




# ========== 通用确认框（顶层模态） ==========


class AsrExampleDialog(QDialog):
    """ASR 非流式调用示例（curl / Python）：可复制、可另存。

    用途：设置页「测试 ASR 配置」失败时，或者要在别的脚本里集成同一套服务
    时，用户需要一条自己能跑通的命令来区分"程序的问题"还是"密钥/账号/模型
    的问题"。示例由 `engine.asr_examples()` 生成，与引擎内 `_asr_*_submit`
    一一对应（同端点、同头、同 body 形态），跑通它即等于验证了本程序。

    ⚠️ 与 ThemedColorDialog 同一个坑：主窗口是 Mica 的 FluentWindow，
    `palette.Window` 是黑的（浅色档也是），Qt 建顶层窗口时会把它再解析一遍
    打回黑色 —— 所以皮肤要在「构造 + showEvent + 0ms 补套」三处都上。
    """

    def __init__(self, ex, parent=None):
        super().__init__(parent)
        self.ex = ex or {}
        self.setWindowTitle("ASR 非流式调用示例 — %s"
                            % (self.ex.get("title") or ""))
        self.resize(780, 580)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)

        head = QLabel("协议：%s　示例与程序内实现一一对应，跑通它即代表这套"
                      "密钥 / 地址 / 模型可用" % (self.ex.get("protocol") or ""))
        head.setWordWrap(True)
        head.setObjectName("dlgMeta")
        lay.addWidget(head)

        if self.ex.get("env"):
            env = QLabel("先把环境变量设成你自己的值："
                         + "；".join("%s → %s" % (k, v)
                                     for k, v in self.ex["env"].items()))
            env.setWordWrap(True)
            env.setObjectName("dlgMeta")
            lay.addWidget(env)

        self.tabs = QTabWidget(self)
        self.ed_curl = self._make_edit(self.ex.get("curl") or "")
        self.ed_py = self._make_edit(self.ex.get("python") or "")
        self.tabs.addTab(self.ed_curl, "curl")
        self.tabs.addTab(self.ed_py, "Python")
        lay.addWidget(self.tabs, 1)

        if self.ex.get("notes"):
            tip = QLabel("说明：" + "　".join("· " + n for n in self.ex["notes"]))
            tip.setWordWrap(True)
            tip.setObjectName("dlgMeta")
            lay.addWidget(tip)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.btn_copy = PrimaryPushButton("复制当前页", self)
        self.btn_copy.clicked.connect(self._copy)
        self.btn_save = PushButton("另存为…", self)
        self.btn_save.clicked.connect(self._save)
        btn_close = PushButton("关闭", self)
        btn_close.clicked.connect(self.accept)
        row.addWidget(self.btn_copy)
        row.addWidget(self.btn_save)
        row.addStretch(1)
        row.addWidget(btn_close)
        lay.addLayout(row)
        self._skin()

    def _make_edit(self, text):
        ed = QPlainTextEdit(self)
        ed.setPlainText(text)
        ed.setReadOnly(True)
        ed.setLineWrapMode(QPlainTextEdit.NoWrap)   # 命令行不能折行
        f = ed.font()
        f.setFamily("Consolas")
        f.setPointSize(10)
        ed.setFont(f)
        return ed

    def _current_text(self):
        w = self.tabs.currentWidget()
        return w.toPlainText() if w is not None else ""

    def _copy(self):
        QApplication.clipboard().setText(self._current_text())
        InfoBar.success("已复制", "当前页的示例已复制到剪贴板", duration=2500,
                        position=InfoBarPosition.TOP, parent=self)

    def _save(self):
        name = "asr_%s_%s.txt" % (self.ex.get("protocol") or "example",
                                  "curl" if self.tabs.currentIndex() == 0
                                  else "python")
        path, _ = QFileDialog.getSaveFileName(self, "保存示例", name,
                                              "文本文件 (*.txt);;所有文件 (*.*)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(self._current_text().rstrip() + "\n")
            InfoBar.success("已保存", path, duration=3000,
                            position=InfoBarPosition.TOP, parent=self)
        except OSError as e:
            InfoBar.error("保存失败", str(e)[:200], duration=4000,
                          position=InfoBarPosition.TOP, parent=self)

    def _skin(self):
        import ui_theme
        self.setPalette(ui_theme.dialog_palette())
        self.setStyleSheet(ui_theme.dialog_qss())

    def showEvent(self, ev):
        super().showEvent(ev)
        self._skin()
        QTimer.singleShot(0, self._reskin)      # 建窗之后还要再补一次（见类注释）

    def _reskin(self):
        if self.isVisible():
            self._skin()


class UpdateProgressDialog(QDialog):
    """更新进度窗：阶段文字 + 进度条 + 日志 + 取消（v2.0.0）。

    形态沿用 `ConfirmDialog` 的定论（真·顶层模态窗口）：贴成主窗口子控件
    会被 mpv 原生子窗口压住、收不到键盘焦点，用户看到的是「点不动的框」。
    更新是长耗时操作，必须能取消——下载几百 MB 时不给取消等于绑架。

    线程约定：`update_progress` / `append_log` 由**后台线程**调用，
    内部一律走 Qt 信号切回主线程（直接改控件会跨线程崩）。
    """

    #: 后台线程 → 主线程的信号中转（连接时带 self，保证自动断开）
    sig_progress = Signal(str, int, int)
    sig_log = Signal(str)

    def __init__(self, parent=None, title="正在更新",
                 subtitle="", on_cancel=None):
        super().__init__(parent)
        self._on_cancel = on_cancel
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint
                            | Qt.NoDropShadowWindowHint)
        self.setWindowModality(Qt.ApplicationModal)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowTitle(title)

        dark = False
        try:
            from vt_fluent import isDarkTheme
            dark = bool(isDarkTheme())
        except Exception:  # noqa: BLE001
            pass
        bg = "#2B2B2B" if dark else "#FFFFFF"
        fg = "#F3F3F3" if dark else "#1B1B1B"
        sub = "#C9C9C9" if dark else "#4C4C4C"
        line = "#3D3D3D" if dark else "#E6E6E6"

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame(self, objectName="vtUpdCard")
        card.setAttribute(Qt.WA_StyledBackground, True)
        card.setStyleSheet(
            "#vtUpdCard{background:%s;border:1px solid %s;"
            "border-radius:10px;}" % (bg, line))
        outer.addWidget(card)

        inner = QVBoxLayout(card)
        inner.setContentsMargins(26, 22, 26, 18)
        inner.setSpacing(10)

        t = QLabel(title, card, objectName="vtUpdTitle")
        t.setStyleSheet("#vtUpdTitle{color:%s;font-size:15px;font-weight:600;"
                        "background:transparent;border:none;}" % fg)
        inner.addWidget(t)

        self.stage = QLabel(subtitle or "准备中…", card, objectName="vtUpdStage")
        self.stage.setWordWrap(True)
        self.stage.setMinimumWidth(340)
        self.stage.setMaximumWidth(460)
        self.stage.setStyleSheet("#vtUpdStage{color:%s;font-size:13px;"
                                 "background:transparent;border:none;}" % sub)
        inner.addWidget(self.stage)

        self.prog = ProgressBar(card)
        self.prog.setRange(0, 0)          # 0,0 = 不确定进度（忙碌动画）
        inner.addWidget(self.prog)

        self.log = QPlainTextEdit(card)
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(132)
        self.log.setStyleSheet(
            "QPlainTextEdit{background:transparent;border:1px solid %s;"
            "border-radius:6px;color:%s;font-size:11px;}" % (line, sub))
        inner.addWidget(self.log)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 6, 0, 0)
        buttons.addStretch(1)
        self.cancelButton = PushButton("取消", card)
        self.cancelButton.setFixedWidth(112)
        buttons.addWidget(self.cancelButton)
        inner.addLayout(buttons)

        # 「取消」只是置位标志，真正中止发生在后台任务里——
        # 立即 close() 会让用户以为已经停了，其实还在下。
        self.cancelButton.clicked.connect(self._do_cancel)
        self.sig_progress.connect(self._on_progress)
        self.sig_log.connect(self._on_log)
        self.adjustSize()

    def _do_cancel(self):
        self.stage.setText("正在取消…（当前分块结束后生效）")
        self.cancelButton.setEnabled(False)
        if self._on_cancel:
            try:
                self._on_cancel()
            except Exception:  # noqa: BLE001
                pass

    # ---- 后台线程调用（跨线程安全入口）----

    def update_progress(self, stage, done, total):
        self.sig_progress.emit(str(stage or ""), int(done or 0),
                               int(total or 0))

    def append_log(self, msg):
        self.sig_log.emit(str(msg))

    # ---- 主线程槽 ----

    def _on_progress(self, stage, done, total):
        if stage:
            self.stage.setText(stage)
        if total > 0:
            self.prog.setRange(0, total)
            self.prog.setValue(done)
        else:
            self.prog.setRange(0, 0)

    def _on_log(self, msg):
        # 末尾裁剪，避免长更新把内存吃满（日志只用于即时查看，不落盘）
        self.log.appendPlainText(msg)
        if self.log.blockCount() > 500:
            self.log.document().setMaximumBlockCount(500)

    def showEvent(self, e):
        super().showEvent(e)
        parent = self.parentWidget()
        if parent is not None:
            try:
                center = parent.window().frameGeometry().center()
                self.move(center - self.rect().center())
            except Exception:  # noqa: BLE001
                pass
        self.raise_()
        self.activateWindow()






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

        2026-11-15 功能解耦阶段③：业务消息（lib_* / scan_done / mg_* / mvm_* /
        sp_* / cal_* / pipe_state / detect_done / sys_log / dl_*）已全部由
        功能页 bus 自订阅。本表只剩壳层编排消息：cookie_import_done（设置页，
        待 settings 拆出时认领）与 pipe_ready（流水线装配，属 MainWindow）。
        """
        kind, args = msg[0], msg[1:]
        try:
            if kind == "cookie_import_done":
                self.settings_page.on_cookie_import_done(*args)
            elif kind == "pipe_ready":
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
