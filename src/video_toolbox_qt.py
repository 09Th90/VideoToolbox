#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# @version 1.14.1
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

import hashlib
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime

from PyQt5.QtCore import (Qt, QTimer, QEvent, QObject, QPoint, QRect, QRectF,
                          QSize, QUrl, QAbstractNativeEventFilter, pyqtSignal,
                          QLockFile)
from PyQt5.QtGui import (QColor, QDesktopServices, QFont, QFontMetrics,
                         QGuiApplication, QKeyEvent, QKeySequence, QPainter,
                         QPen, QPixmap, QTextCursor)
from PyQt5.QtWidgets import (QAbstractButton, QAbstractItemView, QApplication,
                             QDialog, QFileDialog, QFrame, QGridLayout,
                             QHBoxLayout, QHeaderView, QLabel, QMessageBox,
                             QPlainTextEdit, QShortcut, QSizePolicy, QSplitter,
                             QStackedWidget, QTableWidgetItem, QTabWidget,
                             QVBoxLayout, QWidget)

from qfluentwidgets import (BodyLabel, CardWidget, CaptionLabel,
                            ComboBox, FluentIcon as FIF,
                            FluentWindow, InfoBar, InfoBarPosition, LineEdit,
                            ListWidget, MessageBox, NavigationItemPosition,
                            PasswordLineEdit, PrimaryPushButton, ProgressBar,
                            PushButton, ScrollArea, SegmentedWidget, Slider,
                            SimpleCardWidget, SpinBox, SubtitleLabel,
                            StrongBodyLabel, SwitchButton, TableWidget,
                            TextEdit, Theme, TitleLabel, ToolButton, setTheme,
                            setThemeColor)
from qfluentwidgets.components.navigation.navigation_widget import NavigationWidget

import video_toolbox as engine
# 流水线（v1.14.0）：目录感知 + 阶段调度。两个模块都是引擎侧（无 Qt 控件依赖），
# UI 只订阅它们抛出的状态，跨线程一律走 app.q。
import media_registry as mreg
import pipeline as pl
# 界面美化：各导航板块自定义背景图（配置持久化在 data/ui_custom.json）
import ui_theme
# 字幕编辑（打轴）三件套：纯逻辑 / 媒体后端 / 控件。
# 页面类放在本文件（与其余 6 个页面一致）——若把页面单独成模块，它会
# 反过来 import 本文件的 ScrollPage，形成循环导入。
import subtitle_editor_core as secore
from subtitle_editor import CueTable, SubtitlePropsPanel, WaveformTimeline
from subtitle_editor_media import MpvPlayer, WaveformCache
from subtitle_overlay import SubtitleStage
# 内嵌字幕对话框（原引擎工作台「字幕视频合成」那一段，v1.13.x 挪到这里）
from subtitle_compose import ComposeDialog

VERSION = "1.14.1"

# 全格式媒体/字幕/文档扩展名（v1.13.0）：
#   视频：常见容器 + av1 / h264 / h265 / x264 等裸流与更多封装；
#   音频：常见音频容器；
#   字幕：常见字幕文本格式。
# 这些集合既用于「视频库」扫描，也用于「把文件拖进程序」时的类型分派。
VIDEO_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv", ".ts", ".m4v",
              ".webm", ".av1", ".264", ".h264", ".x264", ".265", ".h265",
              ".x265", ".hevc", ".m2ts", ".mts", ".vob", ".ogv", ".3gp",
              ".mpg", ".mpeg", ".divx", ".rm", ".rmvb", ".asf", ".mxf"}
AUDIO_EXTS = {".mp3", ".m4a", ".wav", ".aac", ".flac", ".ogg", ".oga",
              ".opus", ".wma", ".amr", ".ape", ".ac3", ".dts", ".wv",
              ".aiff", ".aif", ".caf"}
SUBTITLE_EXTS = {".srt", ".ass", ".ssa", ".vtt", ".sub", ".smi", ".sbv", ".lrc"}

LIB_EXTS = set(VIDEO_EXTS)
THUMB_DIR = engine.THUMB_CACHE_DIR
CARD_W, THUMB_W, THUMB_H = 232, 200, 118

# 字幕编辑「打开媒体」对话框的完整格式过滤串（与 VIDEO_EXTS + AUDIO_EXTS 对应）
MEDIA_FILE_FILTER = ("媒体文件 (" + " ".join("*" + e for e in
                      sorted(VIDEO_EXTS | AUDIO_EXTS, key=str.lower)) +
                     ");;所有文件 (*.*)")


def thumb_cache_name(path):
    """缩略图缓存文件名：净化文件名 + 完整路径哈希 + 修改时间戳（含目录，防串图）。

    v1.10.0 起输出 .jpg —— 旧 tkinter 版用 .ppm（Tk 能读、Qt 读不了），
    换界面后旧缓存不会再被命中，会自动按新名重新生成，无需手工清理。
    """
    stem = os.path.splitext(os.path.basename(path))[0]
    try:
        stamp = int(os.path.getmtime(path))
    except OSError:
        stamp = 0
    digest = hashlib.md5(os.path.abspath(path).encode("utf-8", "replace")).hexdigest()[:8]
    return re.sub(r"[^\w.-]", "_", stem)[:60] + "__" + digest + "__" + str(stamp) + ".jpg"


def fmt_hms(seconds):
    seconds = int(seconds or 0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


# ========== 崩溃兜底：未捕获异常不再让进程「瞬间消失」（v1.12.0） ==========
# PyQt5 的默认行为是：槽函数 / 回调里抛出未捕获异常时调用 qFatal() → 进程立刻
# abort（用户看到的就是「点一下按钮，程序没了」，且没有任何提示）。只要我们自己
# 装上 sys.excepthook，PyQt5 就会改为调用它、不再 abort。
# 这类 bug 最常见的成因是漏定义名字（例如 duration=INFOBAR_DURATION_SUCCESS 却没定义），
# 静态检查见 src/check_names.py，自检里已加断言防回归。
CRASH_LOG = os.path.join(engine.LOGS_DIR, "crash.log")


def _crash_log_write(kind, exc_type, exc, tb, thread_name=""):
    """把 traceback 落盘 + 打到 stderr（best-effort，本身绝不抛）。"""
    try:
        os.makedirs(engine.LOGS_DIR, exist_ok=True)
        with open(CRASH_LOG, "a", encoding="utf-8") as f:
            f.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} [{kind}] "
                    f"线程={thread_name} =====\n")
            f.write("".join(traceback.format_exception(exc_type, exc, tb)))
    except Exception:
        pass
    try:
        traceback.print_exception(exc_type, exc, tb)
    except Exception:
        pass


def _crash_toast(title, text):
    """尽力在界面上提示一次；非主线程 / 无窗口时静默跳过。"""
    try:
        if threading.current_thread() is not threading.main_thread():
            return
        app = QApplication.instance()
        if app is None:
            return
        win = app.activeWindow()
        if win is None:
            return
        InfoBar.error(title, text[:300], duration=6000,
                      position=InfoBarPosition.BOTTOM_RIGHT, parent=win)
    except Exception:
        pass


def install_crash_guard():
    """装上未捕获异常钩子（main() 里、创建 QApplication 之前调用）。"""
    def _hook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        _crash_log_write("主线程", exc_type, exc, tb,
                         threading.current_thread().name)
        _crash_toast("界面遇到一个错误（程序已继续运行）",
                     f"{exc_type.__name__}: {exc}（详情见 logs/crash.log）")

    def _thread_hook(args):
        if issubclass(args.exc_type, SystemExit):
            return
        _crash_log_write("后台线程", args.exc_type, args.exc_value,
                         args.exc_traceback,
                         getattr(getattr(args, "thread", None), "name", ""))

    sys.excepthook = _hook
    threading.excepthook = _thread_hook


# ========== 导航宽度（按最长项文字自适应） ==========
# 导航项宽度的构成（见 qfluentwidgets.components.navigation.navigation_widget）：
#   1. FluentWindow 左侧栏 → panel 左侧内边距（NaviPanel 边距 4+4）
#   2. Expand 按钮 40px（收起态图标条宽度）
#   3. 图标与文字之间的间距
#   4. 文字宽度（QFontMetrics.horizontalAdvance）
#   5. 右侧呼吸空间
NAV_BUTTON_W = 40          # 收起态按钮宽度，也是展开态图标区宽度
NAV_ICON_TEXT_GAP = 14     # 图标右缘到文字左缘
NAV_SIDE_PADDING = 8       # panel 左右各自的内边距
NAV_TEXT_TAIL = 6          # 文字右侧余量，避免紧贴滚动条


def nav_width_for(texts, font=None):
    """按导航项文案计算展开态宽度：最长一项文字宽 + 2 个字符 + 固有占位。

    用户要求「单行最大字数宽度 + 2 个字符的宽度」——2 个字符用中文字宽
    （em 宽）计，保证任何文案下右侧都留出约两个汉字的空间。

    字体默认取**应用字体**（main() 里 app.setFont 设定的那个）；只有显式传入
    font、或 QApplication 尚未建立时才回退雅黑 9pt。硬编码字体名会在「系统装的
    字体与 app 字体不同」时量出偏差宽度，表现为「程序刚开启时导航宽度不对、
    过一会儿才收敛」（v1.11.0 修正）。
    """
    if font is None:
        try:
            font = QApplication.font()
        except Exception:  # noqa: BLE001
            font = None
    fm = QFontMetrics(font or QFont("Microsoft YaHei UI", 9))
    longest = max((fm.horizontalAdvance(t or "") for t in texts), default=0)
    two_chars = fm.horizontalAdvance("字字")
    return (NAV_SIDE_PADDING * 2 + NAV_BUTTON_W + NAV_ICON_TEXT_GAP
            + longest + two_chars + NAV_TEXT_TAIL)


def _perf_note(msg):
    """启动/预热耗时诊断：静默追加到 logs\\startup.log（best-effort）。

    用于日后排查「进入某页卡顿」——把各阶段耗时留痕，避免只能靠反复计时复现。
    """
    try:
        os.makedirs(engine.LOGS_DIR, exist_ok=True)
        with open(os.path.join(engine.LOGS_DIR, "startup.log"), "a",
                  encoding="utf-8") as f:
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")
    except OSError:
        pass


# ========== 通用控件 ==========
class LogView(CardWidget):
    """日志卡片：等宽字体、按级别着色、自动滚动到底。

    v1.13.x 主题感知：深色主题保持「控制台」深底，浅色主题换浅底深字，
    跟随主题档/系统深浅实时切换（不再固定深底——浅色页面里一块黑日志
    过于突兀）。
    """

    def __init__(self, title="运行日志", height=150, parent=None):
        super().__init__(parent)
        self.text = TextEdit(self)
        self.text.setReadOnly(True)
        self.text.setMinimumHeight(height)
        self._apply_log_theme()
        # 主题切换时重应用样式表（ui_theme 回调；weakref 不拖住本控件）
        ui_theme.connect_theme(self, lambda v: v._apply_log_theme())

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 14, 20, 18)
        lay.setSpacing(10)
        lay.addWidget(CaptionLabel(title, self))
        lay.addWidget(self.text)

    def _apply_log_theme(self):
        """按当前主题给日志文本区上色（深色=控制台深底，浅色=浅底深字）。"""
        t = ui_theme.tokens()
        # 固定底色的由来：qfluentwidgets 的 TextEdit 在深色主题下不会自动
        # 变色，默认白底放在深色卡片里非常突兀——改为按主题 token 上色。
        self.text.setStyleSheet(
            f"TextEdit{{background:{t['log_bg']};color:{t['log_text']};"
            "border:none;"
            "font-family:Consolas,'Microsoft YaHei UI';font-size:12px;}")

    def _colors(self):
        """按级别着色（浅色主题下把过浅的级别色加深，保证白底可读）。"""
        if ui_theme.is_dark():
            return {"dim": "#8A8A8A", "ok": "#2E9E5B",
                    "err": "#D64545", "info": "#B0B0B0"}
        return {"dim": "#787F87", "ok": "#1F8A4C",
                "err": "#C0392B", "info": "#4A5057"}

    def line(self, msg, level="dim"):
        colors = self._colors()
        color = colors.get(level, colors["dim"])
        stamp = datetime.now().strftime("%H:%M:%S")
        t = ui_theme.tokens()
        self.text.setTextColor(QColor(t["log_dim"]))
        self.text.insertPlainText(f"{stamp}  ")
        self.text.setTextColor(QColor(color))
        self.text.insertPlainText(str(msg) + "\n")
        self.text.setTextColor(QColor(t["log_text"]))
        self.text.moveCursor(QTextCursor.End)
        self.text.ensureCursorVisible()

    def clear(self):
        self.text.clear()


def card(title=None, caption=None):
    """新建一张卡片，返回 (卡片, 其内部竖向布局)。

    卡片会被放进滚动区，说明文字不自动换行（避免 heightForWidth 与滚动区
    互相触发重排）；文案一律保持一行能放下的长度。
    v1.13.x 界面美化：换用 ui_theme.UICard 统一皮肤（圆角 10、1px 描边、
    hover 提亮），所有页面共用一套卡片观感。
    """
    box = ui_theme.UICard()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(14, 12, 14, 14)
    lay.setSpacing(8)
    if title:
        lay.addWidget(StrongBodyLabel(title, box))
    if caption:
        lay.addWidget(fit_caption(CaptionLabel(caption, box)))
    return box, lay


class AccentDot(QAbstractButton):
    """主题色预设圆点（自绘）。

    之前用 qfluentwidgets PushButton + QSS 上色，有两个绕不开的坑：
    ① QSS 的 background 在**首帧**不生效（样式缓存），必须等鼠标碰一下
    才上色；② qfluentwidgets 切主题/页面首显时会按 FluentStyleSheet 给
    控件重新 setStyleSheet，把自定义背景**覆盖回默认灰**。修补（repolish、
    showEvent 重刷）都只是治标，用户实测仍是「主题色按键必须点击一次才会
    显示」。圆点本质是个色块，直接自绘最稳：无 QSS、无样式缓存、无主题
    重刷覆盖，任何主题下首帧即为最终效果。
    """

    def __init__(self, hexcolor, parent=None):
        super().__init__(parent)
        self._color = QColor(hexcolor)
        self._selected = False
        self._hover = False
        self.setFixedSize(24, 24)
        self.setCursor(Qt.PointingHandCursor)

    def set_dot_color(self, hexcolor):
        c = QColor(hexcolor)
        if c.isValid() and c != self._color:
            self._color = c
            self.update()

    def set_selected(self, on):
        on = bool(on)
        if on != self._selected:
            self._selected = on
            self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(1, 1, -1, -1)
        p.setPen(Qt.NoPen)
        p.setBrush(self._color)
        p.drawEllipse(r)
        # 选中描白圈，hover 描浅灰圈（与旧 QSS 行为一致）
        if self._selected:
            ring = QColor("#FFFFFF")
        elif self._hover:
            ring = QColor("#E8EAED")
        else:
            return
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(ring, 2))
        p.drawEllipse(r.adjusted(1, 1, -1, -1))


def row(*widgets, spacing=8):
    """把若干控件排成一行（末尾自动补弹性空间）。"""
    holder = QWidget()
    lay = QHBoxLayout(holder)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(spacing)
    for w in widgets:
        if w is None:
            lay.addStretch(1)
        else:
            lay.addWidget(w)
    return holder


def label_row(text, widget, spacing=8):
    return row(BodyLabel(text), widget, None, spacing=spacing)


def srow(label, *widgets):
    """设置页输入行：标签 + 输入控件，第一个控件 stretch=1 吃满剩余宽度。

    与 label_row 的区别：label_row 行尾有 addStretch(1)，把布局里额外的横向
    空白全部吸到右侧，输入框只保持 sizeHint 宽度——长 URL/路径被横向截断
    （v1.13.0「设置页文字显示不全」的根因）。这里让输入框吃掉行内多余宽度，
    窗口放大时输入框随之变宽、长文本完整显示；后续按钮自然靠右排列。
    """
    holder = QWidget()
    lay = QHBoxLayout(holder)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(8)
    lay.addWidget(BodyLabel(label, holder))
    ws = [w for w in widgets if w is not None]
    if ws:
        lay.addWidget(ws[0], 1)
        for w in ws[1:]:
            lay.addWidget(w)
    return holder


def expand_h(widget, minimum=160):
    """让输入框横向自适应填满所在行（长 URL/路径不被截断）。

    v1.13.0：最小宽度由 360 → 220 → 160 逐步收紧——窗口缩小 / 导航变宽 /
    换到低分辨率屏时，卡片内的输入行不再把卡片撑出可视范围（页面扭曲的
    主要来源之一）；Expanding 策略保证宽度允许时仍会吃满整行。输入框在
    窄于内容时内部自动滚动，不丢失已有文字。
    """
    try:
        widget.setMinimumWidth(minimum)
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    except Exception:
        pass
    return widget


def fit_caption(label):
    """说明文字「宁可被裁也不撑宽卡片」（滚动区内不能换行的统一兜底）。

    QScrollArea 内一律不能用自动换行标签——heightForWidth 与滚动区会互相触发
    重排，事件循环卡死。于是长文案只有两种命运：把卡片撑宽（页面横向滚动又被
    禁用，结果就是超出可视范围、按钮被挤出屏幕），或者被裁。
    这里把水平方向的 sizeHint 置为忽略（Ignored 会连带忽略最小提示），
    卡片宽度改由输入框 / 按钮决定，文案再长也不会撑破布局。
    v1.11.0 起统一应用于 card() 的说明与各页手写的提示标签。
    """
    try:
        label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        label.setMinimumWidth(0)
    except Exception:
        pass
    return label


class PageBase(QWidget):
    """页面基类：统一标题区 + 内容区。"""

    def __init__(self, title, subtitle, parent=None):
        super().__init__(parent)
        self.vbox = QVBoxLayout(self)
        self.vbox.setContentsMargins(32, 22, 32, 24)
        self.vbox.setSpacing(14)
        self.vbox.addWidget(TitleLabel(title, self))
        if subtitle:
            cap = CaptionLabel(subtitle, self)
            cap.setWordWrap(True)
            self.vbox.addWidget(cap)

    def add(self, widget, stretch=0):
        self.vbox.addWidget(widget, stretch)


class ScrollPage(QWidget):
    """页面壳：标题区固定 + 内容区。

    scrollable=True 时内容放进滚动区（水平滚动禁用）：
      · 窗口最小尺寸不再被页面内容撑爆——此前四个重页面的布局最小高度
        叠加把 FluentWindow 撑到 1300px+，小屏幕上窗口超出屏幕、底部
        控件（任务表/日志）不可见，这是 v1.10.2 布局重做的直接原因；
      · 滚动区内一律不用自动换行标签（见 card() 注释），防止
        heightForWidth 与滚动区互相触发重排导致事件循环卡死。

    scrollable=False 时内容直接铺满（供内嵌引擎界面等自带滚动的页面）。
    """

    def __init__(self, title, subtitle, parent=None, scrollable=True):
        super().__init__(parent)
        self.view = self
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 16, 24, 18)
        outer.setSpacing(10)
        outer.addWidget(SubtitleLabel(title, self))
        self.cap = None
        if subtitle:
            cap = CaptionLabel(subtitle, self)
            cap.setWordWrap(True)
            outer.addWidget(cap)
            # v1.13.x：暴露给子类。自动换行标签的 heightForWidth 会在首次布局时
            # 再算一遍高度（1 行 → 2 行），下方内容整体下移，表现就是「进页面
            # 上下闪一下」。子类可 `fit_caption(self.cap)` 把它压成不参与重排。
            self.cap = cap

        if scrollable:
            self.area = ScrollArea(self)
            self.area.setWidgetResizable(True)
            self.area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.area.setStyleSheet("QScrollArea{background:transparent;border:none;}")
            self.holder = QWidget(self.area)
            self.holder.setStyleSheet("QWidget{background:transparent;}")
            self.content_lay = QVBoxLayout(self.holder)
            self.content_lay.setContentsMargins(4, 2, 12, 16)
            self.content_lay.setSpacing(12)
            self.area.setWidget(self.holder)
            outer.addWidget(self.area, 1)
            self.vbox = self.content_lay
        else:
            self.area = None
            self.holder = QWidget(self)
            self.holder.setStyleSheet("QWidget{background:transparent;}")
            self.content_lay = QVBoxLayout(self.holder)
            self.content_lay.setContentsMargins(0, 0, 0, 0)
            outer.addWidget(self.holder, 1)
            self.vbox = self.content_lay

    def add_card(self, widget, stretch=0):
        self.vbox.addWidget(widget, stretch)


class TabPage(QWidget):
    """页内子板块的内容壳：可滚动、无大标题（标题由页内分段控件承担）。

    v1.13.0：页面合并（音画合并并入视频下载、字幕校准并入字幕处理）后，
    被合并的板块放进页内分段（SegmentedWidget）+ 本壳，各自独立滚动、
    互不挤占。与 ScrollPage 的区别只是没有 SubtitleLabel 大标题；其余
    （滚动区 / 卡片宽度跟随视口 / 水平滚动禁用）完全一致。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.view = self
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)
        self.area = ScrollArea(self)
        self.area.setWidgetResizable(True)
        self.area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.area.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        self.holder = QWidget(self.area)
        self.holder.setStyleSheet("QWidget{background:transparent;}")
        self.content_lay = QVBoxLayout(self.holder)
        self.content_lay.setContentsMargins(24, 10, 24, 16)
        self.content_lay.setSpacing(12)
        self.area.setWidget(self.holder)
        outer.addWidget(self.area, 1)
        self.vbox = self.content_lay

    def add_card(self, widget, stretch=0):
        self.vbox.addWidget(widget, stretch)


def tab_caption(text, parent=None):
    """子板块顶部的灰色说明（TabPage 无大标题，用一行说明补上下文）。"""
    cap = fit_caption(CaptionLabel(text, parent))
    cap.setTextColor("#8a8a8a", "#9a9a9a")
    return cap


# ========== 视频下载（含「音画合并」板块，v1.13.0 合并） ==========
class DownloadPage(QWidget):
    """单个链接反复添加；每个下载任务独立线程，互不阻塞。

    v1.13.0：原「音视频合并」板块更名为「音画合并」并并入本页——
    页内用 SegmentedWidget 分段切换「视频下载 / 音画合并」两个子板块，
    参考字幕处理页的「一页多板块」形态。
    """

    _EXTRACT_LOCK = threading.Lock()
    SUB_LANGS = "en,zh,ja,zh-Hans,zh-Hant,ko,es,fr,de"

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setObjectName("DownloadPage")
        self.qualities = []
        self.detected_url = ""
        self.info_json_path = None
        self.detecting = False
        self.task_seq = 0
        self.tasks = {}
        self.active_task = None
        self._dest_syncing = False
        self._row_of = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # —— 页内分段：视频下载 / 音画合并 ——
        # v1.13.x：改为**铺满整行**（与「字幕处理」页观感对齐）。SegmentedWidget 对
        # 每项固定 stretch=1 等分：铺满后两个标签各占半行、文字居中、下划线跟文字走，
        # 不再缩在左上角一小团。旧版为了躲"窗口变宽被拉开空隙"把宽度收缩到内容并
        # 靠左对齐，结果就是"挤在一边"。
        # ⚠️ 边距必须加在**外层容器**上，绝不能设在 SegmentedWidget 自己身上：
        #    qfluentwidgets 的 `SegmentedWidget.paintEvent` 画选中框用的是
        #    `item.rect()`，而 `item.rect()` 恒为 (0,0,w,h)——它**忽略了 item
        #    在布局里的实际 y**。一旦控件自身带 contentsMargins，item 被整体
        #    下压 12px，框却仍画在 y=1，于是就成了「灰色区域贴顶、文字偏下」
        #    的错位（用户反馈的那张图）。边距挪到外层容器后两者重新对齐。
        self.seg = SegmentedWidget(self)
        self.seg.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        seg_wrap = QWidget(self)
        seg_lay = QHBoxLayout(seg_wrap)
        seg_lay.setContentsMargins(24, 12, 24, 0)
        seg_lay.setSpacing(0)
        seg_lay.addWidget(self.seg)
        outer.addWidget(seg_wrap)

        self.stack = QStackedWidget(self)
        outer.addWidget(self.stack, 1)

        # —— 子板块 1：视频下载（可滚动卡片区） ——
        self.dl_tab = TabPage(self)
        self.stack.addWidget(self.dl_tab)
        self.vbox = self.dl_tab.content_lay
        self.vbox.setSpacing(12)
        self.vbox.addWidget(tab_caption(
            "检测一个链接后即可加入并行下载；每个视频自动打包成独立文件夹"
            "（视频 + 封面.jpg + 视频信息.txt）", self))

        # —— 链接 ——
        self.url_edit = LineEdit(self)
        self.url_edit.setPlaceholderText("粘贴视频链接（支持 B 站 / YouTube 等）")
        box, lay = card("视频链接")
        paste_btn = PushButton(FIF.PASTE, "粘贴", self)
        paste_btn.clicked.connect(self.paste_url)
        lay.addWidget(row(self.url_edit, paste_btn))
        self.vbox.addWidget(box)

        # —— 保存位置 ——
        self.dest_edit = LineEdit(self)
        self.dest_edit.setText(engine.get_saved_download_dir())
        self.dest_edit.textChanged.connect(self._on_dest_change)
        browse_btn = PushButton(FIF.FOLDER, "浏览…", self)
        browse_btn.clicked.connect(self.browse_dest)
        box, lay = card("保存位置", "改动会立即记住，下次启动自动沿用")
        lay.addWidget(row(self.dest_edit, browse_btn))
        self.vbox.addWidget(box)

        # —— 画质 ——
        self.qlist = ListWidget(self)
        self.qlist.setMinimumHeight(84)
        self.qlist.setMaximumHeight(110)
        self.detect_btn = PrimaryPushButton(FIF.SEARCH, "检测画质", self)
        self.detect_btn.clicked.connect(self.detect)
        box, lay = card("画质", "仅列出 ≥720p；同分辨率取最大文件，优先 60fps")
        lay.addWidget(row(CaptionLabel("可用画质", self), None, self.detect_btn))
        lay.addWidget(self.qlist)
        self.vbox.addWidget(box)

        # —— 下载 ——
        self.sub_switch = SwitchButton(self)
        self.sub_switch.setChecked(True)
        self.prog = ProgressBar(self)
        self.pct_label = CaptionLabel("等待检测", self)
        self.dl_btn = PrimaryPushButton(FIF.DOWNLOAD, "加入并行下载", self)
        self.dl_btn.clicked.connect(self.start_download)
        box, lay = card("下载")
        lay.addWidget(row(BodyLabel("同时下载字幕（博主上传 + 自动生成，自动转 SRT）", self),
                          self.sub_switch, None))
        lay.addWidget(row(self.prog, self.pct_label, self.dl_btn))
        self.vbox.addWidget(box)

        # —— 任务列表 ——
        self.task_table = TableWidget(self)
        self.task_table.setBorderVisible(True)
        self.task_table.setBorderRadius(8)
        self.task_table.setWordWrap(False)
        self.task_table.setColumnCount(6)
        self.task_table.setHorizontalHeaderLabels(
            ["任务", "链接", "画质", "进度", "状态", "保存位置"])
        self.task_table.verticalHeader().hide()
        self.task_table.setMinimumHeight(130)
        self.task_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.task_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        for i, w in enumerate((56, 250, 76, 76, 76, 260)):
            self.task_table.setColumnWidth(i, w)
        self.task_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.task_table.itemSelectionChanged.connect(self.on_task_select)
        box, lay = card("并行下载任务", "点击任务行可查看对应进度")
        lay.addWidget(self.task_table)
        self.vbox.addWidget(box)

        self.log = LogView("下载日志", 130, self)
        self.vbox.addWidget(self.log)
        self.vbox.addStretch(1)

        # —— 子板块 2：音画合并（原「音视频合并」板块整体迁入） ——
        self.merge_page = MergePage(self, self)
        self.stack.addWidget(self.merge_page)

        # —— 分段联动 ——
        self.seg.addItem("download", "视频下载",
                         onClick=lambda: self.stack.setCurrentIndex(0))
        self.seg.addItem("merge", "音画合并",
                         onClick=lambda: self.stack.setCurrentIndex(1))
        self.seg.setCurrentItem("download")
        self.switch_tab = lambda i: self.stack.setCurrentIndex(i)

    # ---------- 交互 ----------
    def paste_url(self):
        cb = QApplication.clipboard()
        self.url_edit.setText((cb.text() or "").strip())

    def browse_dest(self):
        d = QFileDialog.getExistingDirectory(self, "选择保存位置",
                                             self.dest_edit.text() or engine.APP_DIR)
        if d:
            self.dest_edit.setText(d)
            self.log.line(f"[设置] 保存位置已改为：{d}（已记住）", "ok")

    def _on_dest_change(self, text):
        if self._dest_syncing:
            return
        raw = self.dest_edit.text()
        d = engine.clean_path(raw)
        self._dest_syncing = True
        try:
            if d and d != raw:
                self.dest_edit.setText(d)
            if d:
                engine.set_saved_download_dir(d)
        finally:
            self._dest_syncing = False

    def set_detecting(self, busy):
        self.detecting = busy
        self.detect_btn.setEnabled(not busy)

    def detect(self):
        url = engine.clean_path(self.url_edit.text())
        if not url.lower().startswith("http"):
            self._warn("请先填入有效的 http 链接")
            return
        if self.detecting:
            return
        self.set_detecting(True)
        self.log.line("[信息] 正在检测可用画质 ...", "dim")
        threading.Thread(target=self._detect_worker, args=(url,), daemon=True).start()

    def _detect_worker(self, url):
        try:
            ytdlp = engine.ensure_ytdlp()
            with DownloadPage._EXTRACT_LOCK:
                raw = engine.fetch_info_json(
                    ytdlp, url, log=lambda m: self.app.q.put(("sys_log", m)))
            if not raw:
                self.app.q.put(("detect_done", url, None, None,
                                "站点风控或网络异常，请稍后重试（具体原因已写入日志）"))
                return
            best = engine.parse_qualities(raw)
            info_path = engine.save_info_json(raw) if best else None
            self.app.q.put(("detect_done", url, best, info_path, None))
        except Exception as e:
            self.app.q.put(("detect_done", url, None, None, str(e)))

    def on_detect_done(self, url, best, info_path, err):
        self.set_detecting(False)
        if err or not best:
            self.log.line(f"[错误] 画质检测失败{': ' + err if err else '，未找到 ≥720p 格式'}", "err")
            return
        self.detected_url = url
        self.qualities = best
        self._drop_info_json()
        self.info_json_path = info_path
        self.qlist.clear()
        for i, f in enumerate(best, 1):
            size = f.get("filesize") or f.get("filesize_approx") or 0
            fps = round(f.get("fps") or 0)
            tag = "   （最高，推荐）" if i == 1 else ""
            self.qlist.addItem(f"{f['height']}p {fps}fps   ~{engine.format_size(size)}{tag}")
        self.qlist.setCurrentRow(0)
        self.log.line(f"[OK] 检测到 {len(best)} 档画质；点击「加入并行下载」后可继续添加新链接", "ok")

    def _drop_info_json(self):
        if self.info_json_path:
            try:
                os.remove(self.info_json_path)
            except OSError:
                pass
            self.info_json_path = None

    def start_download(self):
        url = engine.clean_path(self.url_edit.text())
        if not url.lower().startswith("http"):
            self._warn("请先填入有效的 http 链接")
            return
        if url != self.detected_url or not self.qualities:
            self._warn("当前链接尚未检测画质，请先点击「检测画质」")
            return
        if not self.info_json_path or not os.path.isfile(self.info_json_path):
            self._warn("画质检测结果已失效，请重新点击「检测画质」")
            return
        sel = self.qlist.currentRow()
        if sel < 0:
            self._warn("请选择一档画质")
            return
        for item in self.tasks.values():
            if item["url"] == url and item["status"] == "下载中":
            # 同一链接不重复加入
                self._info("这个视频正在下载中，无需重复添加")
                return

        dest = engine.clean_path(self.dest_edit.text()) or engine.DEFAULT_DOWNLOAD_DIR
        os.makedirs(dest, exist_ok=True)
        engine.set_saved_download_dir(dest)
        fmt = self.qualities[sel]
        fid, height = fmt["format_id"], fmt["height"]

        try:
            raw_text = engine.read_text_any(self.info_json_path)
            task_info = engine.save_info_json(raw_text)
        except OSError:
            self._warn("画质检测结果已失效，请重新点击「检测画质」")
            return

        try:
            meta = json.loads(raw_text)
        except ValueError:
            meta = {}
        task_folder = engine.unique_folder(
            dest, engine.sanitize_folder_name(meta.get("title"), "video"))
        try:
            os.makedirs(task_folder, exist_ok=True)
        except OSError as e:
            self._error("创建文件夹失败", f"{task_folder}\n{e}")
            return

        self.task_seq += 1
        task_id = f"T{self.task_seq}"
        with_subs = self.sub_switch.isChecked()
        self.tasks[task_id] = {
            "url": url, "quality": f"{height}p", "pct": 0.0, "status": "下载中",
            "dest": dest, "folder": task_folder, "with_subs": with_subs,
        }
        self._add_task_row(task_id, url, f"{height}p", "0.0%", "下载中", task_folder)
        self.active_task = task_id
        self.prog.setValue(0)
        self.pct_label.setText("0.0%")
        sub_note = "（含字幕）" if with_subs else ""
        self.log.line(f"[任务 {task_id}] {height}p 开始下载{sub_note} → {task_folder}", "dim")
        self.log.line("[提示] 该任务已在后台运行，可以继续检测并添加下一个视频", "dim")
        threading.Thread(
            target=self._download_worker,
            args=(task_id, url, fid, task_folder, with_subs, task_info, meta, f"{height}p"),
            daemon=True).start()

    # ---------- 任务表 ----------
    def _add_task_row(self, task_id, url, quality, pct, status, dest):
        r = self.task_table.rowCount()
        self.task_table.insertRow(r)
        for c, text in enumerate((task_id, self._display_url(url), quality, pct, status, dest)):
            item = QTableWidgetItem(str(text))
            item.setToolTip(str(text))
            self.task_table.setItem(r, c, item)
        self._row_of[task_id] = r
        self.task_table.selectRow(r)

    def _set_cell(self, task_id, col, text):
        r = self._row_of.get(task_id)
        if r is None or r >= self.task_table.rowCount():
            return
        item = self.task_table.item(r, col)
        if item is None:
            item = QTableWidgetItem()
            self.task_table.setItem(r, col, item)
        item.setText(str(text))

    def on_task_select(self):
        rows = self.task_table.selectionModel().selectedRows()
        if not rows:
            return
        r = rows[0].row()
        for tid, rr in self._row_of.items():
            if rr == r:
                self.active_task = tid
                item = self.tasks.get(tid)
                if item:
                    self.prog.setValue(int(item["pct"]))
                    self.pct_label.setText(
                        f"{item['pct']:.1f}%" if item["status"] == "下载中" else item["status"])
                break

    @staticmethod
    def _display_url(url, limit=44):
        return url if len(url) <= limit else url[: limit - 3] + "..."

    # ---------- 下载线程（与旧界面逻辑一致） ----------
    def _download_worker(self, task_id, url, fid, folder, with_subs=False,
                         info_json_path=None, meta=None, quality_label=""):
        try:
            ytdlp = engine.ensure_ytdlp()
            ffmpeg_path, _ = engine.ensure_ffmpeg()
            # 代理：YouTube 等站点在国内必须经代理才能下载（B 站等本来直连的
            # 站点，代理的 rules 里是 DIRECT，没有副作用）。拿不到代理就直连。
            proxy_args = engine.ytdlp_proxy_args()
            if proxy_args:
                self.app.q.put(("dl_log", task_id,
                                f"[代理] 下载经本地代理 {proxy_args[1]}"))
            opts = ["-f", f"{fid}+ba/b", "--merge-output-format", "mp4",
                    "--ffmpeg-location", os.path.dirname(ffmpeg_path),
                    "--newline", "--no-playlist",
                    "--write-thumbnail", "--convert-thumbnails", "jpg",
                    *proxy_args,
                    "-o", engine.output_template(folder)]
            rc = 1
            if info_json_path and os.path.isfile(info_json_path):
                rc, _ = self._run_ytdlp(
                    [ytdlp, "--load-info-json", info_json_path, *opts], task_id)
            if rc != 0:
                self.app.q.put(("sys_log", f"[任务 {task_id}] 复用检测结果下载失败"
                                          "（多为 CDN 链接过期），改用链接重新提取"))
                self.app.q.put(("dl_progress", task_id, 0.0))
                rc = self._fallback_download(task_id, ytdlp, url, opts)
            if rc == 0:
                self._pack_task(task_id, ffmpeg_path, folder, meta, quality_label)
                if with_subs:
                    self._fetch_subtitles(task_id, ytdlp, url, folder,
                                          info_json_path, meta=meta)
            self.app.q.put(("dl_done", task_id, rc, folder))
        except Exception as e:
            self.app.q.put(("dl_done", task_id, 1, f"出错: {e}"))
        finally:
            if info_json_path:
                try:
                    os.remove(info_json_path)
                except OSError:
                    pass

    def _fallback_download(self, task_id, ytdlp, url, opts):
        """复用检测结果失败时的兜底：重新提取后继续；提取阶段全局串行防风控。"""
        def slog(m):
            self.app.q.put(("sys_log", f"[任务 {task_id}] {m}"))

        with DownloadPage._EXTRACT_LOCK:
            fresh = engine.fetch_info_json(ytdlp, url, log=slog)
        if fresh:
            tmp = engine.save_info_json(fresh)
            try:
                rc, _ = self._run_ytdlp([ytdlp, "--load-info-json", tmp, *opts], task_id)
            finally:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            if rc == 0:
                return 0
        with DownloadPage._EXTRACT_LOCK:
            return self._run_ytdlp_with_retry([ytdlp, *opts, url], task_id)

    @staticmethod
    def _srt_state(folder, before=None):
        """目录里 .srt 的 {路径: (mtime_ns, 大小)} 快照。

        给了 `before` 就只返回**新增或刚被改写**的那些 —— 拉字幕前后各取一次，
        就能准确知道"这一轮到底拿到了哪几份"，不用猜文件名。
        """
        now = {}
        try:
            names = os.listdir(folder)
        except OSError:
            return {} if before is None else []
        for name in names:
            if not name.lower().endswith(".srt"):
                continue
            p = os.path.join(folder, name)
            try:
                st = os.stat(p)
            except OSError:
                continue
            now[p] = (st.st_mtime_ns, st.st_size)
        if before is None:
            return now
        return sorted(p for p, sig in now.items() if before.get(p) != sig)

    def _fetch_subtitles_once(self, task_id, ytdlp, url, folder,
                              info_json_path, sub_langs, proxy_args):
        """跑一轮字幕拉取；返回 yt-dlp 的返回码（0 只代表"命令没报错"）。"""
        opts = ["--skip-download", "--newline", "--no-playlist",
                "--socket-timeout", "15", "--retries", "3",
                "--write-subs", "--write-auto-subs", "--sub-langs", sub_langs,
                "--sub-format", "srt/best", "--convert-subs", "srt",
                *proxy_args,
                "-o", engine.output_template(folder)]
        if info_json_path and os.path.isfile(info_json_path):
            rc, _ = self._run_ytdlp(
                [ytdlp, "--load-info-json", info_json_path, *opts], task_id)
            if rc == 0:
                return 0
        # ⚠️ 这里必须走带 412 重试的版本：字幕请求比视频请求更容易撞上站点风控，
        #    此前只跑一次 `_run_ytdlp`，一次 412 就白等（用户看到的"字幕下载失败"）。
        with DownloadPage._EXTRACT_LOCK:
            return self._run_ytdlp_with_retry([ytdlp, *opts, url], task_id)

    def _fetch_subtitles(self, task_id, ytdlp, url, folder, info_json_path, meta=None):
        """视频下载完成后单独拉字幕；失败只写日志，不影响任务成功状态。

        v1.13.7 三处加固：
          · 全程带代理（此前 yt-dlp 直连，YouTube 字幕根本拉不下来）；
          · AI 语言识别猜错 / 首轮空手时，改用多语言列表补拉一轮；
          · 拉到的每份字幕都做「去重叠」整理（平台自动字幕是滚动式，
            条条互相压住，见 engine.normalize_rolling_srt）。
        """
        sub_langs = self.SUB_LANGS
        title = ""
        if isinstance(meta, dict):
            title = str(meta.get("title") or "").strip()
        if title:
            code = engine.ai_detect_language(title)
            if code:
                langs = engine.ytdlp_sub_langs(code)
                if langs:
                    sub_langs = langs
                    self.app.q.put(("dl_log", task_id,
                                    f"[字幕] AI 识别标题语言为 {code}，按标题语言拉取字幕（{langs}）"))
            else:
                self.app.q.put(("dl_log", task_id,
                                "[字幕] AI 语言识别不可用，按多语言列表拉取字幕"))

        proxy_args = engine.ytdlp_proxy_args()
        before = self._srt_state(folder)
        self._fetch_subtitles_once(task_id, ytdlp, url, folder,
                                   info_json_path, sub_langs, proxy_args)
        fresh = self._srt_state(folder, before)
        if not fresh and sub_langs != self.SUB_LANGS:
            # 首轮空手：多半是"标题语言"猜错了（比如英文字幕挂在 ja 上）。
            # 换成覆盖最广的多语言列表再试一次，这是唯一能纠正它的机会。
            self.app.q.put(("dl_log", task_id,
                            "[字幕] 首轮没取到字幕，改用多语言列表补拉一次"))
            self._fetch_subtitles_once(task_id, ytdlp, url, folder,
                                       info_json_path, self.SUB_LANGS, proxy_args)
            fresh = self._srt_state(folder, before)

        fixed = 0
        for p in fresh:
            try:
                if engine.normalize_rolling_srt(p):
                    fixed += 1
            except Exception as e:  # noqa: BLE001
                self.app.q.put(("sys_log",
                                f"[字幕] 整理 {os.path.basename(p)} 失败：{e}"))
        if fresh:
            extra = f"，其中 {fixed} 份做了去重叠整理" if fixed else ""
            self.app.q.put(("dl_log", task_id,
                            f"[字幕] 已下载 {len(fresh)} 份字幕（.srt）{extra}，"
                            "已存入该视频文件夹"))
        else:
            self.app.q.put(("dl_log", task_id,
                            "[字幕] 该视频没有可用字幕，或字幕拉取失败"
                            "——不影响视频/封面/信息文件，任务仍算完成"))

    def _pack_task(self, task_id, ffmpeg_path, folder, meta, quality_label):
        data = meta if isinstance(meta, dict) else {}
        try:
            engine.write_info_txt(folder, data, quality_label)
            self.app.q.put(("dl_log", task_id, "[打包] 视频信息.txt 已生成"))
        except Exception as e:
            self.app.q.put(("dl_log", task_id, f"[打包] 视频信息.txt 写入失败: {e}"))
        if engine.make_cover_1280x720(ffmpeg_path, folder):
            self.app.q.put(("dl_log", task_id, "[打包] 封面.jpg（1280x720）已生成"))
        else:
            self.app.q.put(("dl_log", task_id, "[打包] 该视频无可用封面，已跳过封面步骤"))

    def _run_ytdlp(self, cmd, task_id):
        try:
            # 按字节读取、逐行智能解码（兼容 yt-dlp 输出 UTF-8/GBK；CJK 多字节
            # 不会跨越 0x0A 换行，故按行解码不会切断字符）
            proc = engine.popen_process(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        bufsize=1)
        except Exception as e:
            self.app.q.put(("dl_log", task_id, f"[错误] 无法启动下载器: {e}"))
            return 1, []
        lines = []
        pct_re = re.compile(r"\[download\]\s+([\d.]+)%")
        for raw in proc.stdout:
            line = engine.decode_bytes_any(raw).rstrip()
            lines.append(line)
            m = pct_re.search(line)
            if m:
                self.app.q.put(("dl_progress", task_id, float(m.group(1))))
            elif line and "Deprecated" not in line and "WARNING" not in line:
                self.app.q.put(("dl_log", task_id, line))
        return proc.wait(), lines

    def _run_ytdlp_with_retry(self, cmd, task_id, attempts=3):
        wait = 6
        rc, lines = 1, []
        for i in range(attempts):
            rc, lines = self._run_ytdlp(cmd, task_id)
            if rc == 0:
                return 0
            joined = "\n".join(lines)
            if "412" not in joined and "Unable to download webpage" not in joined:
                return rc
            if i < attempts - 1:
                self.app.q.put(("sys_log",
                                f"[任务 {task_id}] 站点风控拦截（HTTP 412），{wait}s 后重试 "
                                f"({i + 2}/{attempts}) ..."))
                time.sleep(wait)
                wait *= 2
        return rc

    # ---------- 主线程更新 ----------
    def on_dl_progress(self, task_id, pct):
        item = self.tasks.get(task_id)
        if not item:
            return
        item["pct"] = pct
        self._set_cell(task_id, 3, f"{pct:.1f}%")
        self._set_cell(task_id, 4, "下载中")
        if task_id == self.active_task:
            self.prog.setValue(int(pct))
            self.pct_label.setText(f"{pct:.1f}%")
        n = self.active_count()
        if n:
            self.pct_label.setToolTip(f"并行下载中：{n} 个任务")

    def on_dl_log(self, task_id, text):
        self.log.line(f"[任务 {task_id}] {text}", "dim")

    def on_dl_done(self, task_id, rc, folder):
        item = self.tasks.get(task_id)
        if item:
            item["pct"] = 100.0 if rc == 0 else item["pct"]
            item["status"] = "完成" if rc == 0 else "失败"
        self._set_cell(task_id, 3, "100%" if rc == 0 else "—")
        self._set_cell(task_id, 4, "完成" if rc == 0 else "失败")
        if rc == 0:
            self._set_cell(task_id, 5, folder)
        if task_id == self.active_task:
            if rc == 0:
                self.prog.setValue(100)
            self.pct_label.setText("完成" if rc == 0 else "失败")
        if rc == 0:
            self.log.line(f"[任务 {task_id}] [完成] 已打包到独立文件夹: {folder}", "ok")
            if item and item.get("with_subs"):
                self.log.line(f"[任务 {task_id}] 字幕（.srt，若有）已存入该视频文件夹", "dim")
            root_dir = (item or {}).get("dest") or os.path.dirname(folder)
            self.app.library_page.set_dir(root_dir)
            self.app.library_page.refresh()
            if self.active_count() == 0:
                engine.open_folder(folder)
        else:
            self.log.line(f"[任务 {task_id}] [错误] 下载失败，请查看上方日志"
                          "（多为站点风控或网络问题）", "err")

    def active_count(self):
        return sum(1 for item in self.tasks.values() if item["status"] == "下载中")

    # ---------- 提示 ----------
    def _warn(self, text):
        InfoBar.warning("提示", text, duration=3000, position=InfoBarPosition.BOTTOM_RIGHT,
                        parent=self)
        self.log.line(f"[提示] {text}", "err")

    def _info(self, text):
        InfoBar.info("提示", text, duration=3000, position=InfoBarPosition.BOTTOM_RIGHT,
                     parent=self)

    def _error(self, title, text):
        MessageBox(title, text, self).exec()


# ========== 视频库 ==========
class LibraryPage(QWidget):
    """视频库：自动加载 + 缩略图卡片；单击播放，右键打开所在文件夹。"""

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setObjectName("LibraryPage")
        self.cards = {}
        self.videos = []
        self._pixmaps = {}
        self._busy = False
        self._cols = 4

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.shell = ScrollPage("视频库",
                                "打开软件自动加载；缩略图自动生成并缓存；"
                                "单击卡片播放，右键打开所在文件夹", self, scrollable=False)
        outer.addWidget(self.shell)
        self.vbox = self.shell.content_lay
        self.vbox.setSpacing(12)

        self.dir_edit = LineEdit(self)
        self.dir_edit.setText(engine.get_saved_download_dir())
        browse = PushButton(FIF.FOLDER, "浏览…", self)
        browse.clicked.connect(self.browse)
        sync = PushButton(FIF.SYNC, "同步下载目录", self)
        sync.clicked.connect(self.sync_download_dir)
        self.refresh_btn = PushButton(FIF.UPDATE, "刷新", self)
        self.refresh_btn.clicked.connect(self.refresh)
        open_btn = PushButton(FIF.FOLDER_ADD, "打开文件夹", self)
        open_btn.clicked.connect(self.open_dir)
        box, lay = card("视频库文件夹")
        lay.addWidget(row(self.dir_edit, browse, sync, self.refresh_btn, open_btn))
        self.count_label = CaptionLabel("尚未扫描", self)
        lay.addWidget(self.count_label)
        self.vbox.addWidget(box)

        area = ScrollArea(self)
        area.setWidgetResizable(True)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.holder = QWidget()
        self.grid = QGridLayout(self.holder)
        self.grid.setContentsMargins(2, 2, 2, 2)
        self.grid.setSpacing(12)
        area.setWidget(self.holder)
        self.area = area
        self.empty_label = CaptionLabel("", self)
        self.vbox.addWidget(self.empty_label)
        self.vbox.addWidget(area, 1)
        self.area.installEventFilter(self)

    # ---------- 操作 ----------
    def set_dir(self, path):
        self.dir_edit.setText(path)

    def browse(self):
        d = QFileDialog.getExistingDirectory(self, "选择视频库文件夹",
                                             self.dir_edit.text() or engine.APP_DIR)
        if d:
            self.dir_edit.setText(d)
            self.refresh()

    def sync_download_dir(self):
        self.dir_edit.setText(self.app.download_page.dest_edit.text())
        self.refresh()

    def open_dir(self):
        d = engine.clean_path(self.dir_edit.text())
        if os.path.isdir(d):
            engine.open_folder(d)

    def auto_load(self):
        if os.path.isdir(engine.clean_path(self.dir_edit.text())):
            self.refresh()

    def refresh(self):
        if self._busy:
            return
        folder = engine.clean_path(self.dir_edit.text())
        if not os.path.isdir(folder):
            self.empty_label.setText("视频库文件夹不存在，请先选择一个有效文件夹")
            return
        self._busy = True
        self.refresh_btn.setEnabled(False)
        self.empty_label.setText("")
        self.count_label.setText("正在扫描视频 …")
        threading.Thread(target=self._scan_worker, args=(folder,), daemon=True).start()

    # ---------- 后台 ----------
    def _scan_worker(self, folder):
        try:
            _, ffprobe = engine.ensure_ffmpeg()
            paths = []
            for root, dirs, files in os.walk(folder):
                dirs[:] = [d for d in dirs
                           if not d.startswith(".") and d != "thumb_cache"]
                for n in files:
                    if os.path.splitext(n)[1].lower() in LIB_EXTS:
                        paths.append(os.path.join(root, n))
            paths.sort(key=lambda p: os.path.basename(p).lower())
            videos = []
            for p in paths:
                try:
                    size = os.path.getsize(p)
                except OSError:
                    size = 0
                rel = os.path.relpath(p, folder)
                name = rel if os.path.dirname(rel) else os.path.basename(p)
                videos.append({
                    "path": p, "name": name, "size": size,
                    "dur": engine.get_duration(p, ffprobe),
                    "thumb": os.path.join(THUMB_DIR, thumb_cache_name(p)),
                })
            self.app.q.put(("lib_scan_done", videos, None))
        except Exception as e:
            self.app.q.put(("lib_scan_done", None, str(e)))

    def _thumb_worker(self, videos):
        try:
            ffmpeg, _ = engine.ensure_ffmpeg()
        except Exception as e:
            self.app.q.put(("lib_log", f"[缩略图] ffmpeg 不可用：{e}"))
            return
        os.makedirs(THUMB_DIR, exist_ok=True)
        for v in videos:
            if os.path.isfile(v["thumb"]):
                continue
            seek = 5 if (v["dur"] or 0) >= 12 else 0
            ok = self._extract_frame(ffmpeg, v["path"], v["thumb"], seek)
            if not ok and seek:
                ok = self._extract_frame(ffmpeg, v["path"], v["thumb"], 0)
            if ok and os.path.isfile(v["thumb"]):
                self.app.q.put(("lib_thumb", v["path"], v["thumb"]))
            else:
                self.app.q.put(("lib_thumb_fail", v["path"]))

    @staticmethod
    def _extract_frame(ffmpeg, video, thumb, seek):
        cmd = [ffmpeg, "-y"]
        if seek:
            cmd += ["-ss", str(seek)]
        cmd += ["-i", video, "-frames:v", "1", "-vf", f"scale={THUMB_W}:-2", thumb]
        try:
            return engine.run_process(cmd, capture_output=True, timeout=120).returncode == 0
        except Exception:
            return False

    # ---------- 主线程 ----------
    def on_scan_done(self, videos, err):
        self._busy = False
        self.refresh_btn.setEnabled(True)
        self._clear_cards()
        if err:
            self.count_label.setText("")
            self.empty_label.setText(f"扫描失败：{err}")
            return
        self.videos = videos or []
        if not self.videos:
            self.count_label.setText("共 0 个视频")
            self.empty_label.setText("该文件夹下没有找到视频文件")
            return
        total = sum(v["size"] for v in self.videos)
        self.count_label.setText(f"共 {len(self.videos)} 个视频 · {engine.format_size(total)}")
        for v in self.videos:
            self._make_card(v)
        self._reflow()
        missing = [v for v in self.videos if not os.path.isfile(v["thumb"])]
        if missing:
            threading.Thread(target=self._thumb_worker, args=(missing,), daemon=True).start()

    def on_thumb(self, path, thumb_path):
        cardd = self.cards.get(path)
        if not cardd:
            return
        pm = QPixmap(thumb_path)
        if pm.isNull():
            cardd["img"].setText("缩略图损坏")
            return
        self._pixmaps[path] = pm
        cardd["img"].setPixmap(pm.scaled(THUMB_W, THUMB_H, Qt.KeepAspectRatio,
                                         Qt.SmoothTransformation))
        cardd["img"].setText("")

    def on_thumb_fail(self, path):
        cardd = self.cards.get(path)
        if cardd:
            cardd["img"].setText("缩略图生成失败")

    def on_log(self, text):
        self.count_label.setText(text)

    # ---------- 卡片 ----------
    def eventFilter(self, obj, event):
        if obj is self.area and event.type() == QEvent.Resize:
            self._schedule_reflow()
        return super().eventFilter(obj, event)

    def showEvent(self, event):
        # v1.13.0：换屏/改 DPI/窗口缩小后回到本页时，按当前视口宽度重排卡片；
        # 延迟两档：视口尺寸可能晚于 show 更新，holder 重排后也要一次布局收敛。
        super().showEvent(event)
        QTimer.singleShot(0, self._reflow)
        QTimer.singleShot(60, self._reflow)

    def _clear_cards(self):
        for c in self.cards.values():
            c["box"].setParent(None)
            c["box"].deleteLater()
        self.cards.clear()
        self._pixmaps.clear()

    def _make_card(self, v):
        if v["path"] in self.cards:
            return
        # v1.13.x 界面美化：缩略图卡与全局 card() 共用 UICard 皮肤
        box = ui_theme.UICard(self.holder)
        box.setFixedWidth(CARD_W)
        lay = QVBoxLayout(box)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(6)
        img = BodyLabel("生成缩略图中 …", box)
        img.setAlignment(Qt.AlignCenter)
        img.setFixedSize(THUMB_W, THUMB_H)
        img.setStyleSheet("border-radius:6px;")
        name = BodyLabel(self._elide(v["name"], 26), box)
        name.setToolTip(v["path"])
        meta = CaptionLabel(f"{engine.format_size(v['size'])} · {fmt_hms(v['dur'])}", box)
        lay.addWidget(img)
        lay.addWidget(name)
        lay.addWidget(meta)
        box.mousePressEvent = lambda e, p=v["path"]: self._on_card_click(e, p)
        box.setContextMenuPolicy(Qt.CustomContextMenu)
        box.customContextMenuRequested.connect(
            lambda _pos, p=v["path"]: engine.open_folder(os.path.dirname(p)))
        self.cards[v["path"]] = {"box": box, "img": img}
        if os.path.isfile(v["thumb"]):
            self.on_thumb(v["path"], v["thumb"])

    @staticmethod
    def _elide(text, limit):
        return text if len(text) <= limit else "…" + text[-(limit - 1):]

    def _on_card_click(self, event, path):
        if event.button() == Qt.LeftButton:
            engine.open_folder(os.path.dirname(path))
            self._open_file(path)

    @staticmethod
    def _open_file(path):
        try:
            os.startfile(path)     # noqa: S606
        except OSError:
            pass

    def _reflow(self, *_):
        """按当前视口宽度重排卡片列数（v1.13.0：改为可靠触发）。

        旧实现直接在 ScrollArea 的 Resize 事件里读 viewport().width()——
        事件派发时视口可能还是旧尺寸，窗口缩小/换 DPI 屏后网格仍按旧列数
        排布，卡片超出视口、右侧被裁（横向滚动又禁用 → 视觉扭曲）。
        现在：每次都用「视口宽度」重算；若发现与当前列数不一致再重排；
        并延迟到事件循环空闲后再做一次兜底，覆盖视口晚于区域 resize 的情况。
        """
        if not self.cards:
            return
        try:
            vw = self.area.viewport().width()
        except Exception:
            vw = self.area.width()
        if vw <= 0:
            vw = self.area.width()
        width = max(vw, CARD_W + 8)
        cols = max(1, width // (CARD_W + 12))
        if cols == self._cols and self.grid.count() == len(self.cards):
            return
        self._cols = cols
        while self.grid.count():
            self.grid.takeAt(0)
        for i, c in enumerate(self.cards.values()):
            self.grid.addWidget(c["box"], i // cols, i % cols)
        self.grid.setRowStretch(self.grid.rowCount(), 1)
        # v1.13.0：重排后立刻把 holder 收缩到视口宽度——widgetResizable 的
        # 自动收缩发生在下一事件循环，期间旧列数仍把 holder 撑宽（横向滚动
        # 已禁用 → 卡片被右侧裁掉，即用户看到的「页面扭曲」）。
        try:
            vp = self.area.viewport().width()
            if vp > 0 and self.holder.width() != vp:
                self.holder.resize(vp, self.holder.height())
        except Exception:
            pass

    def _schedule_reflow(self):
        """滚动区尺寸变化后：本帧 + 下一帧各重排一次，消除视口/holder 时序差。"""
        self._reflow()
        QTimer.singleShot(0, self._reflow)
        QTimer.singleShot(50, self._reflow)


# ========== 音画合并（v1.13.0 由「音视频合并」更名，并入「视频下载」页） ==========
class MergePage(QWidget):
    ASS_MODES = {"烧录为硬字幕": "burn", "封装为 MKV": "mkv", "忽略": "ignore"}

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setObjectName("MergePage")
        self.pairs = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.shell = TabPage(self)
        outer.addWidget(self.shell)
        self.vbox = self.shell.content_lay
        self.vbox.setSpacing(12)
        self.vbox.addWidget(tab_caption(
            "自动配对 mp4 + m4a/weba + srt/ass；m4a 直封，weba 转 AAC", self))

        self.in_edit = LineEdit(self)
        self.in_edit.setText(engine.DEFAULT_INPUT_DIR)
        in_browse = PushButton(FIF.FOLDER, "浏览…", self)
        in_browse.clicked.connect(lambda: self._browse(self.in_edit))
        self.out_edit = LineEdit(self)
        out_browse = PushButton(FIF.FOLDER, "浏览…", self)
        out_browse.clicked.connect(lambda: self._browse(self.out_edit))
        box, lay = card("输入 / 输出文件夹", "输出留空则默认写入「输入文件夹\合成结果」")
        lay.addWidget(label_row("输入文件夹", self.in_edit))
        lay.addWidget(in_browse, 0, Qt.AlignLeft)
        lay.addWidget(label_row("输出文件夹", self.out_edit))
        lay.addWidget(out_browse, 0, Qt.AlignLeft)
        self.vbox.addWidget(box)

        self.ass_combo = ComboBox(self)
        self.ass_combo.addItems(list(self.ASS_MODES))
        self.ass_combo.setCurrentIndex(0)
        self.force_switch = SwitchButton(self)
        self.scan_btn = PrimaryPushButton(FIF.SEARCH, "扫描配对", self)
        self.scan_btn.clicked.connect(self.scan)
        box, lay = card("配对选项")
        lay.addWidget(label_row("ASS 字幕处理", self.ass_combo))
        lay.addWidget(row(BodyLabel("同名但时长不一致也强制合成", self),
                          self.force_switch, None))
        lay.addWidget(row(None, self.scan_btn))
        self.vbox.addWidget(box)

        self.table = TableWidget(self)
        self.table.setBorderVisible(True)
        self.table.setBorderRadius(8)
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["视频", "音频", "字幕", "匹配", "时长差"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        for i, w in enumerate((240, 240, 150, 80, 80)):
            self.table.setColumnWidth(i, w)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        box, lay = card("配对结果")
        lay.addWidget(self.table)
        self.table.setMinimumHeight(200)
        self.vbox.addWidget(box)

        row3 = row(self.prog_bar(), None, self.merge_btn())
        self.vbox.addWidget(row3)
        self.log = LogView("合并日志", 120, self)
        self.vbox.addWidget(self.log)
        self.vbox.addStretch(1)

    def prog_bar(self):
        self.progress = ProgressBar(self)
        return self.progress

    def merge_btn(self):
        self.merge_button = PrimaryPushButton(FIF.MEDIA, "开始合成", self)
        self.merge_button.clicked.connect(self.start_merge)
        return self.merge_button

    def _browse(self, edit):
        d = QFileDialog.getExistingDirectory(self, "选择文件夹", edit.text() or engine.APP_DIR)
        if d:
            edit.setText(d)

    def set_busy(self, busy):
        self.scan_btn.setEnabled(not busy)
        self.merge_button.setEnabled(not busy)

    def scan(self):
        in_dir = engine.clean_path(self.in_edit.text())
        if not os.path.isdir(in_dir):
            InfoBar.warning("提示", "输入文件夹不存在", duration=3000,
                            position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        self.set_busy(True)
        self.log.line(f"[信息] 正在扫描: {in_dir}", "dim")
        threading.Thread(target=self._scan_worker, args=(in_dir,), daemon=True).start()

    def _scan_worker(self, in_dir):
        try:
            _, ffprobe = engine.ensure_ffmpeg()
            mp4s, m4as, webas, srts, asss = engine.scan_media(in_dir)
            pairs, rem_mp4, rem_m4a, rem_weba = engine.smart_pair(
                mp4s, m4as, webas, srts, asss, ffprobe)
            self.app.q.put(("scan_done", pairs, (rem_mp4, rem_m4a, rem_weba),
                            (len(mp4s), len(m4as), len(webas), len(srts), len(asss)), None))
        except Exception as e:
            self.app.q.put(("scan_done", None, None, None, str(e)))

    def on_scan_done(self, pairs, remaining, counts, err):
        self.set_busy(False)
        if err:
            self.log.line(f"[错误] 扫描失败: {err}", "err")
            return
        self.pairs = pairs or []
        self.table.setRowCount(0)
        name = {"perfect": "完美", "duration": "时长", "name_only": "仅同名"}
        for p in self.pairs:
            mp4, audio, at, mt, diff, sub, st = p
            r = self.table.rowCount()
            self.table.insertRow(r)
            for c, text in enumerate((
                    os.path.basename(mp4), os.path.basename(audio),
                    os.path.basename(sub) if sub else "—",
                    name.get(mt, mt), f"{diff:.2f}s")):
                item = QTableWidgetItem(str(text))
                item.setToolTip(str(text))
                self.table.setItem(r, c, item)
        n_mp4, n_m4a, n_weba, n_srt, n_ass = counts
        self.log.line(f"[OK] 找到 {n_mp4} 个 mp4 / {n_m4a} 个 m4a / {n_weba} 个 weba / "
                      f"{n_srt} 个 srt / {n_ass} 个 ass，配对 {len(self.pairs)} 对", "ok")
        rem_mp4, rem_m4a, rem_weba = remaining
        if rem_mp4:
            self.log.line(f"[未匹配视频] {len(rem_mp4)} 个：" +
                          "、".join(os.path.basename(f) for f in rem_mp4), "dim")
        if rem_m4a or rem_weba:
            self.log.line(f"[未匹配音频] {len(rem_m4a) + len(rem_weba)} 个", "dim")

    def start_merge(self):
        if not self.pairs:
            InfoBar.warning("提示", "请先「扫描配对」", duration=3000,
                            position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        in_dir = engine.clean_path(self.in_edit.text())
        out_dir = engine.clean_path(self.out_edit.text()) or os.path.join(in_dir, "合成结果")
        os.makedirs(out_dir, exist_ok=True)
        ass_mode = self.ASS_MODES.get(self.ass_combo.currentText(), "burn")
        to_merge = [p for p in self.pairs
                    if p[3] in ("perfect", "duration") or self.force_switch.isChecked()]
        if not to_merge:
            InfoBar.warning("提示", "没有可合成的配对（可勾选强制合成）", duration=3000,
                            position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        self.set_busy(True)
        self.progress.setValue(0)
        threading.Thread(target=self._merge_worker,
                         args=(to_merge, out_dir, ass_mode), daemon=True).start()

    def _merge_worker(self, to_merge, out_dir, ass_mode):
        ok_n = fail_n = 0
        try:
            ffmpeg_path, _ = engine.ensure_ffmpeg()
            total = len(to_merge)
            for idx, p in enumerate(to_merge, 1):
                mp4, audio, at, mt, diff, sub, st = p
                if st == "ass" and ass_mode == "ignore":
                    sub, st = None, None
                base = engine.get_base_name(mp4)
                out_path = os.path.join(out_dir, f"{base}_merged.mp4")
                counter, orig = 1, out_path
                while os.path.exists(out_path):
                    stem, ext = os.path.splitext(orig)
                    out_path = f"{stem}_{counter}{ext}"
                    counter += 1
                self.app.q.put(("mg_log", f"[{idx}/{total}] {base}"))
                ok, final_out = engine.merge_pair(mp4, audio, at, sub, st,
                                                  out_path, ffmpeg_path, ass_mode)
                if ok and os.path.exists(final_out):
                    ok_n += 1
                    self.app.q.put(("mg_log", f"     [OK] "
                                              f"{engine.format_size(os.path.getsize(final_out))}"))
                else:
                    fail_n += 1
                    self.app.q.put(("mg_log", "     [X] 失败"))
                self.app.q.put(("mg_progress", idx / total * 100))
            self.app.q.put(("mg_done", ok_n, fail_n, out_dir))
        except Exception as e:
            self.app.q.put(("mg_done", ok_n, fail_n, f"出错: {e}"))

    def on_mg_done(self, ok_n, fail_n, out_dir):
        self.set_busy(False)
        self.progress.setValue(100)
        self.log.line(f"[完成] 成功 {ok_n} / 失败 {fail_n} → {out_dir}",
                      "ok" if fail_n == 0 else "err")
        if fail_n == 0:
            engine.open_folder(out_dir)


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
        self.calib_page = CalibPage(self, self)

    # ---------- 预热（消除首次进入卡顿） ----------
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
        self._prewarming = True

        def _work():
            t0 = time.perf_counter()
            try:
                engine.engine_ui_brand_patch()
            except Exception:  # noqa: BLE001
                pass
            try:
                engine.vc_asr_patch_apply()      # 本地独立 ASR 的模型覆盖补丁
            except Exception:  # noqa: BLE001
                pass
            # v1.12.0：翻译板块已全面去 AI（仅机翻），不再挂 LLM 回退兜底
            try:
                import videocaptioner.ui.view.home_interface  # noqa: F401
                ok = True
            except Exception:  # noqa: BLE001
                ok = False
            self._prewarm_ready = ok
            _perf_note(f"prewarm 线程：import={'ok' if ok else 'fail'} "
                       f"{time.perf_counter() - t0:.2f}s")

        t = threading.Thread(target=_work, daemon=True, name="vc-prewarm")
        t.start()
        self._prewarm_thread = t
        # 轮询等待后台 import 结束，然后回主线程建界面（不阻塞事件循环）
        QTimer.singleShot(200, self._wait_prewarm)

    def _wait_prewarm(self):
        t = getattr(self, "_prewarm_thread", None)
        if t is not None and t.is_alive():
            QTimer.singleShot(200, self._wait_prewarm)
            return
        if self._built:
            return
        self._build_now("正在准备字幕引擎界面 …")

    # ---------- 构建 ----------
    def _build_engine(self):
        """创建并内嵌引擎工作台；隐藏品牌水印与捐助入口。"""
        engine.engine_ui_brand_patch()   # 用户可见文案中性化（见 docs\ 声明）
        try:
            from videocaptioner.ui.view.home_interface import HomeInterface
        except Exception as e:  # noqa: BLE001
            self.state_label.setText(f"字幕引擎加载失败：{e}")
            _perf_note(f"字幕引擎 import 失败：{e}")
            return None
        # v1.14.1：转录下拉收敛「默认/ASR」+ 独立转录完成回填「字幕翻译」
        # （类级运行期补丁，必须在 HomeInterface 实例化之前挂上）
        try:
            engine.vc_transcribe_ui_patch()
        except Exception as e:  # noqa: BLE001
            # 别再静默：UI 补丁一旦失败，协议补丁（在它的 ⑤ 里挂）就跟着
            # 没了，表现为"百炼端点被拿去打 /audio/transcriptions 而断连"
            try:
                engine._vc_log(f"转录 UI 补丁失败：{e}")
            except Exception:  # noqa: BLE001
                pass
        # 协议补丁独立再挂一次（幂等）：它才是"走哪条协议"的决定因素
        try:
            engine.vc_asr_protocol_patch()
        except Exception:  # noqa: BLE001
            pass
        t0 = time.perf_counter()
        home = HomeInterface()
        _perf_note(f"HomeInterface 构造：{time.perf_counter() - t0:.2f}s")
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
                    from PyQt5.QtWidgets import QWidget as _QW
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
        # v1.13.x：摘掉引擎工作台的「字幕视频合成」分段——用户要求把合成并到
        # 「字幕编辑」页（那边攥着正在编辑、可能还没保存的字幕，不必先导出
        # 再喂回来）。只动界面、不碰引擎本体：
        #   · 先断掉「字幕翻译完成 → 自动跳合成」的连线；
        #   · 再把分段项与堆叠页摘掉；
        #   · 实例本身留着（HomeInterface.closeEvent 还会调它的 close()）。
        # 换到编辑页的入口是工具条上的「内嵌字幕」（只加轨道、不重编码）。
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
                home.pivot.removeWidget("VideoSynthesisInterface")
                home.stackedWidget.removeWidget(syn)
                syn.hide()
        except Exception:  # noqa: BLE001
            pass
        tc = getattr(home, "task_creation_interface", None)
        if tc is not None:
            for attr in ("info_label", "donate_button"):
                w = getattr(tc, attr, None)
                if w is not None:
                    w.hide()
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
        self._engine_home = home
        return home

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

    def _build_now(self, busy_text):
        if self._built:
            return
        self._built = True
        t0 = time.perf_counter()
        if busy_text:
            self.state_label.setText(busy_text)
        self._engine = self._build_engine()
        if self._engine is None:
            return
        self.host_lay.addWidget(self._engine)
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
        _perf_note(f"字幕引擎界面构建完成：{time.perf_counter() - t0:.2f}s"
                   f"（预热 {'已就绪' if self._prewarm_ready else '未完成'}）")
        # 引擎界面（自带字体）进来后，导航宽度重新按宿主的统一口径收敛一次
        try:
            self.window().refresh_nav_width()
        except Exception:
            pass

    def showEvent(self, event):
        """首次显示时才加载引擎界面（内嵌 QWidget，随主题自动配色）。"""
        super().showEvent(event)
        if self._built:
            return
        # 预热尚未完成时也直接建（用户已点进来，等不了）；import 缓存已热，
        # 即便预热线程还在跑，主线程这里也只是等 import 锁，比冷启动快
        self._build_now("正在准备字幕引擎界面 …")

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
        self._build_proxy_card()
        self._build_ai_card()
        self._build_asr_card()
        self._build_calib_ai_card()
        self._build_engine_section()
        self._build_sync_card()
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
    # 网络代理：内置 mihomo（GitHub 加速），允许用户接入自己的 Clash yaml
    # ------------------------------------------------------------------ #
    def _build_proxy_card(self):
        box, blay = card(
            "网络代理",
            "内置 mihomo 代理服务于依赖下载、校准知识同步与 YouTube 下载；"
            "自动测速选择可用节点，死节点自动切换。"
            "可接入自己的 Clash/订阅 yaml（仅取其中节点，端口固定 7897）")
        cur = engine.get_proxy_yaml()
        self.proxy_edit = LineEdit(box)
        self.proxy_edit.setPlaceholderText(
            "留空使用内置节点快照（tools/mihomo/config.yaml，端口 7897）")
        self.proxy_edit.setText(cur)
        self.proxy_edit.setReadOnly(True)
        browse = PushButton(FIF.FOLDER, "浏览…", box)
        browse.clicked.connect(self._browse_proxy_yaml)
        reset = PushButton(FIF.SYNC, "恢复", box)
        reset.clicked.connect(self._reset_proxy_yaml)
        blay.addWidget(srow("代理配置文件", self.proxy_edit, browse, reset))
        self.proxy_hint = fit_caption(CaptionLabel(self._proxy_hint_text(), box))
        self.proxy_hint.setTextColor("#8a8a8a", "#9a9a9a")
        blay.addWidget(self.proxy_hint)
        expand_h(self.proxy_edit)
        self.vbox.addWidget(box)

    @staticmethod
    def _proxy_hint_text():
        port = engine._proxy_yaml_port(engine.get_proxy_yaml()) if \
            engine.get_proxy_yaml() else engine.MIHOMO_PORT
        if engine.get_proxy_yaml():
            return (f"当前：自定义配置（端口 {port or 7897}），程序只提取其中的"
                    f"节点，监听端口固定 7897、自动选择可用节点。"
                    f"修改后重启生效。")
        return ("程序自动测速并选择可用节点，节点失效自动切换（端口 7897）。"
                "也可接入自己的 Clash/订阅 yaml，仅提取其中节点。"
                "修改后重启生效。")

    def _proxy_start_dir(self):
        """文件对话框起始目录：上次选的 yaml 所在目录 > 程序目录 > 当前目录。"""
        try:
            cur = engine.get_proxy_yaml()
            if cur and os.path.isdir(os.path.dirname(cur)):
                return os.path.dirname(cur)
            if os.path.isdir(engine.APP_DIR):
                return engine.APP_DIR
        except Exception:
            pass
        return os.getcwd()

    def _browse_proxy_yaml(self):
        p, _ = QFileDialog.getOpenFileName(
            self, "选择 Clash/mihomo 配置", self._proxy_start_dir(),
            "Clash 配置 (*.yaml *.yml)")
        if not p:
            return
        self._apply_proxy_yaml(p)

    def _apply_proxy_yaml(self, path):
        """套用自定义代理 yaml（对话框选完后走这里；自检也直接调它）。

        v1.12.0 修复：原实现在这里用了未定义的常量 INFOBAR_DURATION_SUCCESS，
        点击即 NameError → PyQt5 abort → **闪退**；现已改为字面量并整段兜底，
        任何异常都只提示、不崩界面。
        """
        try:
            if engine._proxy_yaml_port(path) is None:
                InfoBar.warning(
                    "未能识别端口", "配置里没有 mixed-port / port / socks-port，"
                    "将回退使用默认端口 7897", duration=4000, parent=self)
            engine.set_proxy_yaml(path)
        except (OSError, ValueError) as e:
            InfoBar.error("保存失败", str(e)[:200], duration=4000, parent=self)
            return False
        except Exception as e:                      # 兜底：任何异常都不该让界面崩
            InfoBar.error("设置代理失败", f"{type(e).__name__}: {e}"[:200],
                          duration=5000, parent=self)
            return False
        self.proxy_edit.setText(path)
        self.proxy_hint.setText(self._proxy_hint_text())
        InfoBar.success("已保存", "自定义代理配置已生效，重启程序后应用",
                        duration=3000, parent=self)
        return True

    def _reset_proxy_yaml(self):
        try:
            engine.set_proxy_yaml("")
        except Exception:
            pass
        self.proxy_edit.setText("")
        self.proxy_hint.setText(self._proxy_hint_text())
        InfoBar.success("已恢复", "将使用内置 GitHub 专用代理配置，重启程序后生效",
                        duration=3000, parent=self)

    # ------------------------------------------------------------------ #
    # 全局 AI（LLM）：全程序唯一一套配置
    # ------------------------------------------------------------------ #
    #: ASR 协议下拉：显示名 ↔ 配置键（顺序一一对应，与引擎侧 ASR_PROTOCOLS 同序）
    ASR_PROTO_LABELS = ("自动识别（推荐）", "OpenAI Whisper 兼容", "Azure OpenAI",
                        "Chat 音频转写（百炼 / MiMo）", "Deepgram",
                        "ElevenLabs Scribe", "Google Gemini",
                        "火山引擎（豆包）", "AssemblyAI",
                        "百炼实时（WebSocket）")
    ASR_PROTO_KEYS = ("auto", "openai", "azure", "chat_audio",
                      "deepgram", "elevenlabs", "gemini",
                      "volcengine", "assemblyai", "dashscope_realtime")

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
        self.ai_key.setText(str(ai.get("api_key", "")))
        self.ai_key.setPlaceholderText("API Key")
        blay.addWidget(srow("密钥", self.ai_key))

        self.ai_base = LineEdit(box)
        self.ai_base.setText(str(ai.get("base_url", "")))
        self.ai_base.setPlaceholderText(
            "如 https://open.bigmodel.cn/api/paas/v4（兼容 OpenAI/DeepSeek/"
            "Gemini 兼容层/Ollama/Azure 等，填到域名或版本段均可）")
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
        save_btn = PrimaryPushButton(FIF.SAVE, "保存并应用", box)
        save_btn.clicked.connect(self._ai_save)
        self.ai_dirty_lbl = fit_caption(CaptionLabel("● 有未保存的改动", box))
        self.ai_dirty_lbl.setTextColor("#c07a1a", "#c07a1a")
        self.ai_dirty_lbl.setToolTip("改完要点「保存并应用」才会写入引擎；"
                                     "不保存的话转录/校准用的仍是上次保存的配置")
        self.ai_dirty_lbl.hide()
        blay.addWidget(row(test_btn, save_btn, self.ai_dirty_lbl))

        self.ai_hint = fit_caption(CaptionLabel(
            "保存后立即生效；地址填到域名或版本段均可自动补全（含 Azure）",
            box))
        self.ai_hint.setTextColor("#8a8a8a", "#9a9a9a")
        blay.addWidget(self.ai_hint)
        for w in (self.ai_key, self.ai_base, self.ai_model, self.ai_vision):
            expand_h(w)
        # 编辑即亮「未保存」：不保存的话引擎里还是上一版配置
        for w in (self.ai_key, self.ai_base, self.ai_model, self.ai_vision):
            w.textChanged.connect(self._mark_ai_dirty)
        self.vbox.addWidget(box)

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
        self.asr_key.setText(str(ai.get("asr_api_key", "")))
        self.asr_key.setPlaceholderText("ASR 服务 API Key")
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
        blay.addWidget(self.asr_service_widget)

        # —— 本地模型 ——
        self.asr_local_widget = QWidget(box)
        llay = QVBoxLayout(self.asr_local_widget)
        llay.setContentsMargins(0, 0, 0, 0)
        llay.setSpacing(8)
        self.asr_local_model = LineEdit(self.asr_local_widget)
        self.asr_local_model.setText(str(ai.get("asr_local_model", "")))
        self.asr_local_model.setPlaceholderText("模型名，如 large-v3、large-v3-turbo 或自训练模型目录名")
        llay.addWidget(srow("本地模型名", self.asr_local_model))
        self.asr_local_dir = LineEdit(self.asr_local_widget)
        self.asr_local_dir.setText(str(ai.get("asr_local_model_dir", "")))
        self.asr_local_dir.setPlaceholderText("留空 = 用软件 data\\VideoCaptioner\\models")
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
            "Gemini，默认自动识别）；本地模式：选「ASR」即用 faster-whisper "
            "本地模型/目录", box))
        self.asr_hint.setTextColor("#8a8a8a", "#9a9a9a")
        blay.addWidget(self.asr_hint)
        for w in (self.asr_base, self.asr_key, self.asr_model, self.asr_prompt,
                  self.asr_local_model, self.asr_local_dir):
            expand_h(w)
        # 编辑即亮「未保存」：只填不保存的话，转录页会提示「ASR 未配置」
        for w in (self.asr_base, self.asr_key, self.asr_model, self.asr_prompt,
                  self.asr_local_model, self.asr_local_dir):
            w.textChanged.connect(self._mark_ai_dirty)
        self.asr_mode_combo.currentIndexChanged.connect(self._mark_ai_dirty)
        self.asr_proto_combo.currentIndexChanged.connect(self._mark_ai_dirty)
        self.vbox.addWidget(box)
        self._sync_asr_visible()

    def _sync_asr_visible(self):
        """按 ASR 模式显隐「服务 / 本地」两组输入。"""
        local = self.asr_mode_combo.currentIndex() == 1
        self.asr_service_widget.setVisible(not local)
        self.asr_local_widget.setVisible(local)
        self.asr_hint.setText(
            "本地模式：转录下拉选「ASR」即用本地 faster-whisper，"
            "优先用上面填写的模型名与目录；目录留空则用内置 models 目录"
            if local else
            "服务模式：转录下拉选「ASR」即由自有 ASR 服务识别；协议可选"
            "自动识别 / OpenAI 兼容 / Azure / 阿里百炼，无时间戳响应自动"
            "按句切分兜底")

    def _browse_into(self, edit, title):
        p = QFileDialog.getExistingDirectory(self, title, edit.text() or engine.APP_DIR)
        if p:
            edit.setText(p)

    # ------------------------------------------------------------------ #
    # AI 校准：Agent 级字幕校准的分块参数（走全局 AI 单通道）
    # ------------------------------------------------------------------ #
    def _build_calib_ai_card(self):
        box, blay = card(
            "AI 校准（Agent 级）",
            "字幕校准页开启后生效：先跑术语基线，再由 AI 逐块复校（只改文字）；"
            "走上方「全局 AI」同一套配置")
        ai = engine.ai_load_config()

        def _spin(value, lo, hi, step=1):
            s = SpinBox(box)
            s.setRange(lo, hi)
            s.setSingleStep(step)
            s.setValue(int(value or lo))
            return s

        self.calib_cues = _spin(ai.get("calib_chunk_cues") or 120, 20, 1000, 10)
        blay.addWidget(label_row("每块最多条数", row(self.calib_cues, None)))
        self.calib_chars = _spin(ai.get("calib_max_chars") or 6000, 1000, 40000, 500)
        blay.addWidget(label_row("每块字符预算", row(self.calib_chars, None)))
        self.calib_tokens = _spin(ai.get("calib_max_tokens") or 8192, 1024, 65536, 512)
        blay.addWidget(label_row("单次最大输出 token", row(self.calib_tokens, None)))

        # 校准风格（2026-09-14）：术语级＝只替换名词；整句重写＝理顺机翻腔与断句
        self.calib_style_combo = ComboBox(box)
        self.calib_style_combo.addItems(["术语级（只替换名词，稳妥）",
                                         "整句重写（理顺机翻，双语长片推荐）"])
        self.calib_style_combo.setCurrentIndex(
            1 if str(ai.get("calib_style") or "term") == "rewrite" else 0)
        blay.addWidget(label_row("校准风格", self.calib_style_combo))

        calib_save = PrimaryPushButton(FIF.SAVE, "保存并应用", box)
        calib_save.clicked.connect(self._ai_save)
        blay.addWidget(row(calib_save, None))

        self.calib_hint = fit_caption(CaptionLabel(
            "块越小越稳（读不完自动折半重试）；双语片源带英文参考行、按句子边界"
            "切块；无法用术语知识库解释的改动会被拒绝并写入报告", box))
        self.calib_hint.setTextColor("#8a8a8a", "#9a9a9a")
        blay.addWidget(self.calib_hint)
        self.vbox.addWidget(box)

    def _collect_ai(self):
        return {
            "enabled": self.ai_enabled.isChecked(),
            # 全局 AI 单通道（工具箱 / 字幕引擎 / AI 校准共用）
            "api_key": self.ai_key.text().strip(),
            "base_url": self.ai_base.text().strip(),
            "model": self.ai_model.text().strip(),
            "vision_model": self.ai_vision.text().strip(),
            # ASR：独立 ASR 模型
            "asr_mode": "local" if self.asr_mode_combo.currentIndex() == 1
                        else "service",
            "asr_base_url": self.asr_base.text().strip(),
            "asr_api_key": self.asr_key.text().strip(),
            "asr_model": self.asr_model.text().strip(),
            "asr_prompt": self.asr_prompt.text().strip(),
            "asr_protocol": self.ASR_PROTO_KEYS[
                min(max(self.asr_proto_combo.currentIndex(), 0),
                    len(self.ASR_PROTO_KEYS) - 1)],
            "asr_local_model": self.asr_local_model.text().strip(),
            "asr_local_model_dir": engine.clean_path(self.asr_local_dir.text()),
            # AI 校准（v1.12.0：通道选择随双通道合并一并移除）
            "calib_chunk_cues": self.calib_cues.value(),
            "calib_max_chars": self.calib_chars.value(),
            "calib_max_tokens": self.calib_tokens.value(),
            # 校准风格（2026-09-14）：term=只替换名词；rewrite=整句重写
            "calib_style": ("rewrite"
                            if self.calib_style_combo.currentIndex() == 1 else "term"),
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
            self._clear_ai_dirty()
            InfoBar.success("已保存",
                            "全局 AI 与 ASR 配置已应用：引擎 LLM 槽、转录配置已同步",
                            duration=3000, position=InfoBarPosition.BOTTOM_RIGHT,
                            parent=self)
        except Exception as e:  # noqa: BLE001
            InfoBar.error("保存失败", str(e)[:300], duration=5000,
                          position=InfoBarPosition.BOTTOM_RIGHT, parent=self)

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
        self._engine_built = True
        try:
            from PyQt5.QtWidgets import QFrame
            from videocaptioner.ui.view.setting_interface import SettingInterface
            engine.engine_ui_brand_patch()
            setting = SettingInterface(self.engine_holder)
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
            try:
                from videocaptioner.core.entities import TranslatorServiceEnum as _TSE
                from videocaptioner.ui.common.config import cfg as _vcfg
                if _vcfg.get(_vcfg.translator_service) == _TSE.OPENAI:
                    _vcfg.set(_vcfg.translator_service, _TSE.BING)
                ts_card = getattr(setting, "translateServiceCard", None)
                _combo = getattr(ts_card, "comboBox", None) if ts_card else None
                if _combo is not None:
                    for _i in range(_combo.count()):
                        if _combo.itemText(_i) == "LLM 大模型翻译":
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
                    for _idx, _name in enumerate(order):
                        _card = getattr(setting, _name, None)
                        if _card is None:
                            continue
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
        InfoBar.info("正在更新", "正在从共享仓库拉取校准知识并合并…", duration=1200,
                     position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
        self._run_bg(lambda: engine.sync_calib_on_startup(force=True),
                     self._sync_done)

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
        from qfluentwidgets import isDarkTheme
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
        try:
            setTheme([Theme.DARK, Theme.LIGHT, Theme.AUTO][idx])
        except Exception:
            pass
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


# ========== 字幕校准（v1.13.0 并入「字幕处理」页的子板块） ==========
class CalibPage(QWidget):
    MODES = [
        ("中英双语（默认，BILINGUAL_TERMS）", ""),
        ("日语原声·鸣潮（--ja）", "--ja"),
        ("日语原声·终末地（--jpe）", "--jpe"),
        ("韩语原声·鸣潮（--ko）", "--ko"),
        ("明日方舟（--ak）", "--ak"),
        ("明日方舟·韩语（--akko）", "--akko"),
        ("终末地（--endo）", "--endo"),
        ("中文行专属（--zho）", "--zho"),
        ("战双帕弥什（--pgr）", "--pgr"),
        ("战双英文原声（--pgren）", "--pgren"),
        ("综合手游OST（--wwoc）", "--wwoc"),
        ("音乐点评（--react）", "--react"),
    ]

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setObjectName("CalibPage")
        self.running = False
        self.ai_running = False
        self._cancel_flag = False   # AI 校准取消标志（关闭页面/再次点击）
        self._round = 0             # 已完成的 AI 校准轮次（「再次校准」据此递增）
        self._last_out = ""         # 上一轮 AI 校准输出（再次校准的输入）
        self._last_accepted = []    # 上一轮 AI 采纳明细 [(num, old, new)]，续跑时禁止回退
        self._base_stem = ""        # 第 1 轮确定的输出基名（后续轮次派生命名）
        self._thread = None         # 当前校准工作线程（脚本/AI 共用），卡死自检依据
        self._gen = 0               # 任务代号：每轮 +1，旧线程残留消息按代号丢弃
        self._last_beat = 0.0       # 最近一次收到校准日志/完成消息的时刻（心跳）
        self._script = os.path.join(engine.APP_DIR, "subtitle_calib_merged.py")

        # 子板块壳：可滚动、无大标题（标题由字幕处理页的分段控件承担）。
        # 保留 ScrollPage 时代的 `view` / `add_card` API，调用方不受影响。
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.shell = TabPage(self)
        outer.addWidget(self.shell)
        self.view = self.shell
        self.add_card = self.shell.content_lay.addWidget
        self.vbox = self.shell.content_lay
        self.vbox.setSpacing(12)
        self.vbox.addWidget(tab_caption(
            "调用统一校准脚本 subtitle_calib_merged.py 做名词级术语校准；"
            "序号 / 时间轴 / 空行 / 换行 / BOM 一字不动", self.view))

        if not os.path.isfile(self._script):
            warn = fit_caption(CaptionLabel(f"校准脚本缺失：{self._script}", self.view))
            warn.setWordWrap(True)
            warn.setTextColor(Qt.darkRed)
            self.add_card(warn)

        self.in_edit = LineEdit(self)
        self.in_edit.setPlaceholderText("选择 .srt 字幕文件")
        in_btn = PushButton(FIF.DOCUMENT, "浏览…", self)
        in_btn.clicked.connect(self.browse_in)
        self.out_edit = LineEdit(self)
        self.out_edit.setPlaceholderText("留空自动：同目录 原名.calib.srt（重名自动加序号）")
        out_btn = PushButton(FIF.SAVE, "浏览…", self)
        out_btn.clicked.connect(self.browse_out)

        box, lay = card("字幕文件（.srt）")
        lay.addWidget(row(self.in_edit, in_btn))
        lay.addWidget(row(self.out_edit, out_btn))
        self.add_card(box)

        self.mode_combo = ComboBox(self)
        self.mode_combo.addItems([m[0] for m in self.MODES])
        self.mode_combo.setCurrentIndex(0)
        self.fix_switch = SwitchButton(self)
        self.report_switch = SwitchButton(self)
        self.report_switch.setChecked(True)
        self.stats_switch = SwitchButton(self)
        # AI 校准（Agent 级）：开启后「开始校准」等价于让 AI 基于校准脚本
        # 逐块复校——只改文字、不动时间轴与格式，读不完自动拆分再合并。
        self.ai_switch = SwitchButton(self)
        self.ai_switch.checkedChanged.connect(self._on_ai_toggle)
        self.run_btn = PrimaryPushButton(FIF.PLAY, "开始校准", self.view)
        self.run_btn.clicked.connect(self.start)
        self.again_btn = PushButton(FIF.SYNC, "再次校准", self.view)
        self.again_btn.setEnabled(False)
        self.again_btn.clicked.connect(self.start_again)
        # 刷新：程序卡死（异常/线程僵住导致按钮永久禁用）时，一键复位界面状态，
        # 之后可正常点「开始校准」重新执行；正常运行时点它只提示不打断任务。
        self.refresh_btn = PushButton(FIF.UPDATE, "刷新", self.view)
        self.refresh_btn.clicked.connect(self.refresh_state)
        self.stage_label = fit_caption(CaptionLabel("", self.view))

        box, lay = card("片源模式与选项")
        lay.addWidget(label_row("片源模式", self.mode_combo))
        lay.addWidget(row(BodyLabel("修正英文/参考行（--fix-en，仅双语模式生效）", self.view),
                          self.fix_switch, None))
        lay.addWidget(row(BodyLabel("生成改动对照报告（同名 .md）", self.view),
                          self.report_switch, None))
        lay.addWidget(row(BodyLabel("仅统计术语命中，不写输出文件", self.view),
                          self.stats_switch, None))
        lay.addWidget(row(BodyLabel("AI 校准（Agent 级，接入你自己的 AI 辅助校准）",
                                    self.view), self.ai_switch, None))
        # 说明文案保持「一行放得下」：滚动区内不能换行，长文案会撑破卡片
        self.ai_hint = fit_caption(CaptionLabel(
            "开启后 = 让 AI 基于校准脚本逐块复校：只改文字，不动时间轴与格式",
            self.view))
        self.ai_hint.setTextColor("#8a8a8a", "#9a9a9a")
        lay.addWidget(self.ai_hint)
        lay.addWidget(row(self.stage_label, None,
                          self.refresh_btn, self.again_btn, self.run_btn))
        self.add_card(box)

        self.log = LogView("校准日志", 170, self.view)
        self.add_card(self.log)
        self.vbox.addStretch(1)

    def browse_in(self):
        p, _ = QFileDialog.getOpenFileName(self, "选择字幕文件",
                                           self.in_edit.text() or engine.APP_DIR,
                                           "字幕文件 (*.srt);;所有文件 (*.*)")
        if p:
            self.in_edit.setText(p)

    def browse_out(self):
        p, _ = QFileDialog.getSaveFileName(self, "选择输出文件",
                                           self.in_edit.text() or engine.APP_DIR,
                                           "字幕文件 (*.srt);;所有文件 (*.*)")
        if p:
            self.out_edit.setText(p)

    # 卡死判定阈值（秒）：任务标志挂着但超过该时长没有任何日志/完成心跳 → 视为卡死
    STUCK_AFTER = 120

    def _is_stuck(self):
        """运行标志挂着、但工作线程已死或长时间无心跳 → 判定卡死。"""
        if not (self.running or self.ai_running):
            return False
        th = self._thread
        if th is not None and not th.is_alive():
            return True
        return (time.time() - self._last_beat) > self.STUCK_AFTER

    def _reset_controls(self, stage_text):
        """复位运行态控件（开始/再次按钮、阶段标签）。

        逐项单独容错：这是"脱离卡死"的最后出口，任何一个控件调用失败都不能
        中断其余复位，否则界面又回到按钮永久禁用的卡死状态。
        """
        for fn in (lambda: self.run_btn.setEnabled(True),
                   lambda: self.again_btn.setEnabled(
                       bool(self.ai_switch.isChecked() and self._last_out)),
                   lambda: self.stage_label.setText(stage_text)):
            try:
                fn()
            except Exception:  # noqa: BLE001
                pass

    def refresh_state(self, silent=False):
        """刷新：复位校准页运行状态，脱离卡死。任务正常心跳时不打断。"""
        if (self.running or self.ai_running) and not self._is_stuck():
            if not silent:
                InfoBar.info("提示", "校准任务正在正常运行，无需刷新",
                             duration=3000,
                             position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return False
        was_stuck = self.running or self.ai_running
        self.running = False
        self.ai_running = False
        self._cancel_flag = True     # 通知可能残留的旧线程尽快退出
        self._gen += 1               # 旧线程后续投来的消息按代号丢弃
        self._thread = None
        self._reset_controls("已刷新，可重新校准")
        if was_stuck:
            self.log.line("[刷新] 检测到上一轮校准已中断，界面状态已复位；"
                          "现在可以重新点「开始校准」", "info")
        return True

    def start(self):
        if self.running or self.ai_running:
            if self._is_stuck():
                # 卡死自愈：先复位再按本次点击重新执行（用户要求：报错则重新执行）
                self.refresh_state(silent=True)
                self.log.line("[刷新] 检测到上一轮校准已卡死，已自动复位并重新执行",
                              "info")
            else:
                InfoBar.info("提示", "校准任务进行中，请稍候", duration=3000,
                             position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
                return
        if not os.path.isfile(self._script):
            MessageBox("错误", f"校准脚本缺失：{self._script}", self).exec()
            return
        src = engine.clean_path(self.in_edit.text())
        if not src or not os.path.isfile(src):
            InfoBar.warning("提示", "请先选择一个 .srt 字幕文件", duration=3000,
                            position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        mode_flag = self.MODES[self.mode_combo.currentIndex()][1]
        if self.ai_switch.isChecked():
            self._start_ai(src, again=False, mode_flag=mode_flag)
            return
        stats_only = self.stats_switch.isChecked()

        out = ""
        if not stats_only:
            out = engine.clean_path(self.out_edit.text())
            if not out:
                out = os.path.splitext(src)[0] + ".calib.srt"
            out = self._unique(out)

        args = [engine.system_python(), self._script, src]
        if out:
            args += ["--out", out]
            if self.report_switch.isChecked():
                args += ["--report", os.path.splitext(out)[0] + ".md"]
        if mode_flag:
            args.append(mode_flag)
        if self.fix_switch.isChecked():
            args.append("--fix-en")

        self.running = True
        self._cancel_flag = False
        self._gen += 1
        gen = self._gen
        self._last_beat = time.time()
        try:
            self.run_btn.setEnabled(False)
            self.stage_label.setText("正在校准…")
            self.log.line(f"[校准] 模式: {self.mode_combo.currentText()}"
                          + ("（仅统计）" if stats_only else ""), "dim")
            self.log.line(f"[校准] 输入: {os.path.basename(src)}", "dim")
            if out:
                self.log.line(f"[校准] 输出: {out}", "dim")
            t = threading.Thread(target=self._worker, args=(gen, args, out),
                                 daemon=True)
            self._thread = t
            t.start()
        except Exception as e:  # noqa: BLE001
            self._reset_after_crash(f"校准启动失败：{type(e).__name__}: {e}")

    # ---------- AI 校准（Agent 级） ----------
    @staticmethod
    def _unique(path):
        """输出文件重名时自动加序号（与脚本模式的旧行为一致）。"""
        if not os.path.exists(path):
            return path
        stem, ext = os.path.splitext(path)
        n = 2
        while os.path.exists(f"{stem}({n}){ext}"):
            n += 1
        return f"{stem}({n}){ext}"

    def _on_ai_toggle(self, checked):
        """AI 校准开关：与「仅统计」互斥，并决定「再次校准」是否可用。"""
        if checked and self.stats_switch.isChecked():
            self.stats_switch.setChecked(False)
        self.stats_switch.setEnabled(not checked)
        self.again_btn.setEnabled(bool(checked and self._last_out))
        self.ai_hint.setText(
            "已开启：先跑机械校准，再由 AI 逐块补齐残留错形（不动时间轴与格式）"
            if checked else
            "开启后 = 让 AI 基于校准脚本逐块复校：只改文字，不动时间轴与格式")

    def start_again(self):
        """再次校准：以上一轮 AI 校准的输出为输入再跑一轮，专挑残留错形。"""
        if self.running or self.ai_running:
            if self._is_stuck():
                self.refresh_state(silent=True)
                self.log.line("[刷新] 检测到上一轮校准已卡死，已自动复位并重新执行",
                              "info")
            else:
                InfoBar.info("提示", "校准任务进行中，请稍候", duration=3000,
                             position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
                return
        if not self.ai_switch.isChecked():
            InfoBar.warning("提示", "「再次校准」需要先开启 AI 校准",
                            duration=3000,
                            position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        if not self._last_out or not os.path.isfile(self._last_out):
            InfoBar.warning("提示", "还没有可续跑的结果，请先完成一轮 AI 校准",
                            duration=3000,
                            position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        mode_flag = self.MODES[self.mode_combo.currentIndex()][1]
        self._start_ai(self._last_out, again=True, mode_flag=mode_flag)

    def _start_ai(self, src, again, mode_flag):
        """发起一轮 AI 校准（后台线程跑 Agent，日志经消息队列回主线程）。"""
        if not os.path.isfile(self._script):
            MessageBox("错误", f"校准脚本缺失：{self._script}", self).exec()
            return
        if again:
            n = self._round + 1
            out = self._unique(f"{self._base_stem or os.path.splitext(src)[0]}.r{n}.srt")
        else:
            out = engine.clean_path(self.out_edit.text())
            if not out:
                out = os.path.splitext(src)[0] + ".calib.srt"
            out = self._unique(out)
            self._base_stem = os.path.splitext(out)[0]
            self._round = 0
            self._last_out = ""
        report = os.path.splitext(out)[0] + ".md" if self.report_switch.isChecked() else ""
        round_no = self._round + 1

        self.ai_running = True
        self._cancel_flag = False
        self._gen += 1
        gen = self._gen
        self._last_beat = time.time()
        try:
            self.run_btn.setEnabled(False)
            self.again_btn.setEnabled(False)
            self.stage_label.setText(f"AI 校准中（第 {round_no} 轮）…")
            self.log.line(f"===== AI 校准 · 第 {round_no} 轮 =====", "info")
            self.log.line(f"[AI] 模式: {self.mode_combo.currentText()}", "dim")
            # 校准风格属于全局设置（设置页「AI 校准」卡片），本页无对应控件；
            # 与 engine.calib_ai_run 内部 style=None 时的取值口径保持一致，仅用于日志。
            _style = str((engine.ai_load_config() or {}).get("calib_style") or "term")
            self.log.line(f"[AI] 风格: "
                          + ("整句重写（可理顺机翻语序）"
                             if _style == "rewrite" else "术语级")
                          + ("；以上轮结果为起点续跑（跳过脚本基线、禁止回退）"
                             if again else ""), "dim")
            self.log.line(f"[AI] 输入: {src}", "dim")
            self.log.line(f"[AI] 输出: {out}", "dim")
            if report:
                self.log.line(f"[AI] 报告: {report}", "dim")
            t = threading.Thread(target=self._ai_worker,
                                 args=(gen, src, out, report, mode_flag,
                                       round_no, again),
                                 daemon=True)
            self._thread = t
            t.start()
        except Exception as e:  # noqa: BLE001
            self._reset_after_crash(f"AI 校准启动失败：{type(e).__name__}: {e}")

    def _reset_after_crash(self, msg):
        """主线程启动任务时抛异常：立即复位运行状态，保证界面不会卡死。

        复位必须"无论控件本身是否还能用都要执行完"（见 _reset_controls），
        否则又回到卡死状态。
        """
        self.running = False
        self.ai_running = False
        self._cancel_flag = True     # 通知可能残留的旧线程尽快退出
        self._gen += 1               # 旧线程后续投来的消息按代号丢弃
        self._thread = None
        self._reset_controls("校准失败")
        self.log.line(f"[错误] {msg}", "err")
        self.log.line("界面状态已自动复位，可直接重新点「开始校准」", "info")

    def _ai_worker(self, gen, src, out, report, mode_flag, round_no, again=False):
        def _log(msg, level="dim"):
            self.app.q.put(("cal_log", str(msg), level, gen))

        try:
            res = engine.calib_ai_run(
                src, out=out, report=(report or None), mode_flag=mode_flag,
                fix_en=self.fix_switch.isChecked(), log=_log, round_no=round_no,
                cancel=lambda: self._cancel_flag,
                # 续跑：以上轮产物为起点（跳过脚本基线），并把上轮采纳明细注入提示词
                resume_from=(src if again else None),
                prev_changes=(self._last_accepted if again else None))
        except Exception as e:  # noqa: BLE001
            res = {"ok": False, "out": out, "error": f"{type(e).__name__}: {e}",
                   "script_changes": 0, "ai_changes": 0, "rejected": 0,
                   "round": round_no}
        self.app.q.put(("cal_done", 0 if res.get("ok") else 1,
                        res.get("out") or out, res, gen))

    def _worker(self, gen, args, out):
        try:
            env = dict(os.environ, PYTHONIOENCODING="utf-8")
            proc = engine.popen_process(args, cwd=os.path.dirname(self._script),
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, encoding="utf-8", errors="replace",
                                        bufsize=1, env=env)
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    self.app.q.put(("cal_log", line, "dim", gen))
            rc = proc.wait()
        except Exception as e:  # noqa: BLE001
            self.app.q.put(("cal_log", f"[错误] 校准进程异常: {e}", "dim", gen))
            rc = 1
        self.app.q.put(("cal_done", rc, out, None, gen))

    def on_cal_done(self, rc, out, res=None, gen=None):
        """校准结束（脚本模式 res 为 None；AI 模式 res 为 Agent 结果 dict）。"""
        if gen is not None and gen != self._gen:
            return                      # 已被刷新/新任务取代的旧线程消息，丢弃
        self.running = False
        self.ai_running = False
        self._thread = None
        self.run_btn.setEnabled(True)
        res = res or {}
        if res.get("round"):                    # AI 轮次
            if rc == 0:
                self._round = int(res.get("round") or self._round)
                self._last_out = out
                # 保存采纳明细：下一轮 resume 时作为「不得回退」清单注入提示词
                self._last_accepted = [(n, o, x)
                                       for n, o, x, *_ in res.get("accepted", [])]
            self.again_btn.setEnabled(bool(self.ai_switch.isChecked()
                                           and self._last_out))
        if rc == 0:
            self.stage_label.setText("校准完成")
            if res:
                self.log.line(
                    f"[OK] AI 校准完成（第 {self._round} 轮）：术语脚本 "
                    f"{res.get('script_changes', 0)} 处 + AI {res.get('ai_changes', 0)} 处，"
                    f"拒绝 {res.get('rejected', 0)} 处"
                    + (f"，耗时 {res.get('seconds')}s" if res.get("seconds") else ""),
                    "ok")
                if out:
                    self.log.line(f"[输出] {out}", "ok")
                if res.get("report"):
                    self.log.line(f"[报告] {res['report']}（含采纳明细与拒绝原因）", "dim")
                if res.get("width_over"):
                    self.log.line(f"[行宽] {res['width_over']} 处中文行超过 32 汉字当量，"
                                  f"已列进报告（检查报告第四节）", "err")
                elif (res.get("width_widest") or ("", ""))[0]:
                    self.log.line(f"[行宽] 体检通过（最宽 {res['width_widest'][0]} / 32）",
                                  "dim")
                self.log.line("可点「再次校准」再跑一轮：以上轮结果为起点，"
                              "已确认的改动不会被改回去", "info")
            else:
                self.log.line("[OK] 校准完成" +
                              (f"，输出: {out}" if out else
                               "（仅统计模式，未改写文件）"), "ok")
        else:
            self.stage_label.setText("校准失败")
            msg = res.get("error") or f"退出码 {rc}"
            self.log.line(f"[错误] 校准失败：{msg}", "err")
            if res:
                self.log.line("[提示] 已拒绝的模型提议会写进报告，便于人工复核", "dim")


# ========== 通用确认框（顶层模态） ==========
# ========== 流水线（v1.14.0：目录感知 + 阶段自动调度） ==========
class _StageDot(ToolButton):
    """阶段圆点：灰=等待 / 蓝=运行 / 绿=完成 / 红=失败 / 斜杠=跳过。

    点击跳到对应功能页（点的是"哪一步出问题了"的人，下一步自然是去那页看）。
    """

    COLORS = {"waiting": "#6E6E6E", "ready": "#9AA3AD", "running": "#2E7FD6",
              "done": "#2E9E5B", "failed": "#D64545", "skipped": "#6E6E6E"}
    LABELS = {"waiting": "等待", "ready": "待执行", "running": "进行中",
              "done": "已完成", "failed": "失败", "skipped": "已跳过"}

    def __init__(self, stage_key, label, parent=None):
        super().__init__(parent)
        self.stage_key = stage_key
        self.label = label
        self.state = "waiting"
        self.detail = ""
        self.setFixedSize(20, 20)
        self.setCursor(Qt.PointingHandCursor)
        self.setText("")
        self._tip()

    def _tip(self):
        tip = f"{self.label}：{self.LABELS.get(self.state, self.state)}"
        if self.detail:
            tip += f"\n{self.detail[:200]}"
        tip += "\n（点击跳到对应功能页）"
        self.setToolTip(tip)

    def set_stage(self, state, detail=""):
        self.state = state or "waiting"
        self.detail = str(detail or "")
        self._tip()
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        color = QColor(self.COLORS.get(self.state, "#6E6E6E"))
        r = QRectF(2.5, 2.5, self.width() - 5, self.height() - 5)
        if self.state in ("waiting", "ready", "skipped"):
            p.setPen(QPen(color, 2))
            p.setBrush(Qt.NoBrush)
        else:
            p.setPen(Qt.NoPen)
            p.setBrush(color)
        p.drawEllipse(r)
        if self.state == "skipped":      # 跳过：斜杠
            p.setPen(QPen(color, 2))
            p.drawLine(r.topRight(), r.bottomLeft())
        p.end()


class _JobCard(SimpleCardWidget):
    """单个视频的流水线卡片：名称 + 状态 + 阶段圆点（按任务链动态）+ 重试。"""

    def __init__(self, job, on_jump, on_retry, parent=None):
        super().__init__(parent)
        self.job_id = job.get("id") or ""
        self.on_jump = on_jump
        self.on_retry = on_retry
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 12)
        lay.setSpacing(6)
        self.name_label = StrongBodyLabel(job.get("name") or "(未命名)", self)
        self.status_label = BodyLabel(job.get("status") or "", self)
        self.status_label.setTextColor("#8a8a8a", "#9a9a9a")
        lay.addWidget(row(self.name_label, None, self.status_label))
        self.dots_holder = QWidget(self)
        self.dots_lay = QHBoxLayout(self.dots_holder)
        self.dots_lay.setContentsMargins(0, 0, 0, 0)
        self.dots_lay.setSpacing(10)
        self.dots = {}
        self._chain = tuple(job.get("chain") or ())
        for key in self._chain:
            dot = _StageDot(key, pl.STAGE_LABELS.get(key, key), self)
            dot.clicked.connect(lambda _c=False, k=key: self._jump(k))
            self.dots[key] = dot
            self.dots_lay.addWidget(dot)
        self.dots_lay.addStretch(1)
        self.retry_btn = PushButton(FIF.UPDATE, "执行", self)
        self.retry_btn.setFixedHeight(26)
        self.retry_btn.clicked.connect(self._retry)
        self.dots_lay.addWidget(self.retry_btn)
        lay.addWidget(self.dots_holder)
        self.update_job(job)

    def _jump(self, key):
        if callable(self.on_jump):
            self.on_jump(self.job_id, key)

    def _retry(self):
        if callable(self.on_retry):
            self.on_retry(self.job_id)

    def update_job(self, job):
        self.job_id = job.get("id") or self.job_id
        chain = tuple(job.get("chain") or ())
        if chain != self._chain:          # 链变了（旧状态迁移）→ 重建圆点
            self._chain = chain
            for dot in self.dots.values():
                self.dots_lay.removeWidget(dot)
                dot.setParent(None)
                dot.deleteLater()
            self.dots = {}
            for key in chain:
                dot = _StageDot(key, pl.STAGE_LABELS.get(key, key), self)
                dot.clicked.connect(lambda _c=False, k=key: self._jump(k))
                self.dots[key] = dot
                self.dots_lay.insertWidget(self.dots_lay.count() - 2, dot)
        stages = job.get("stages") or {}
        failed = False
        for key, dot in self.dots.items():
            st = stages.get(key) or {}
            state = st.get("state") or "waiting"
            dot.set_stage(state, st.get("error") or st.get("reason") or "")
            if state == "failed":
                failed = True
        self.status_label.setText(job.get("status") or "")
        self.name_label.setText(job.get("name") or "(未命名)")
        # 失败 → 重试；其余（含存量任务）→ 执行
        self.retry_btn.setText("重试" if failed else "执行")
        self.retry_btn.setVisible(True)


class PipelinePage(QWidget):
    """流水线页：订阅引擎侧 Pipeline 的状态，只读展示 + 开关/重试。

    线程边界：pipeline 的回调来自后台线程，这里一律不碰控件，只往 app.q 投
    消息，等主线程 _pump/_dispatch 回来再更新界面（与其余页面同一套模型）。
    """

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.pipe = None
        self.cards = {}
        self.setObjectName("PipelinePage")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.shell = TabPage(self)
        outer.addWidget(self.shell)
        vbox = self.shell.content_lay
        vbox.addWidget(tab_caption(
            "填入链接即可自动完成：下载（原片/字幕/封面/信息）→ 谷歌翻译 → "
            "字幕校准 → 二次校准 → 成品打包；下载目录里新出现的视频也会自动接管", self))

        # ---- 新建任务（链接驱动） ----
        self.link_edit = LineEdit(self)
        expand_h(self.link_edit, 220)
        self.link_edit.setPlaceholderText(
            "粘贴视频链接（YouTube/B站等），回车或点「添加任务」")
        self.link_edit.returnPressed.connect(self._add_link)
        self.add_btn = PrimaryPushButton(FIF.DOWNLOAD, "添加任务", self)
        self.add_btn.clicked.connect(self._add_link)
        box, lay = card("新建任务", None)
        lay.addWidget(row(self.link_edit, self.add_btn, None))
        vbox.addWidget(box)

        # ---- 自动开关与操作 ----
        self.auto_switch = SwitchButton(self)
        self.auto_switch.setChecked(True)
        self.auto_switch.checkedChanged.connect(self._on_auto)
        self.scan_btn = PushButton(FIF.SYNC, "立即扫描", self)
        self.scan_btn.clicked.connect(self._scan)
        self.retry_btn = PushButton(FIF.UPDATE, "重试失败项", self)
        self.retry_btn.clicked.connect(self._retry_all)
        self.open_btn = PushButton(FIF.FOLDER, "打开成品目录", self)
        self.open_btn.clicked.connect(self._open_out)
        box, lay = card("自动流水线")
        lay.addWidget(row(BodyLabel("自动执行后续阶段", self), self.auto_switch, None))
        lay.addWidget(row(self.scan_btn, self.retry_btn, self.open_btn, None))
        vbox.addWidget(box)

        self.list_box, self.list_lay = card("任务进度")
        self.empty = fit_caption(CaptionLabel("暂无任务：下载目录里出现视频后会自动建卡", self))
        self.list_lay.addWidget(self.empty)
        vbox.addWidget(self.list_box)

        self.log = LogView("流水线日志", 130, self)
        vbox.addWidget(self.log)
        vbox.addStretch(1)

    # ---------- 绑定 ----------
    def attach(self, pipe):
        """接上引擎侧 Pipeline（主线程调用）。"""
        self.pipe = pipe
        try:
            self.auto_switch.setChecked(bool(pipe.auto))
        except Exception:  # noqa: BLE001
            pass
        self._refresh()

    # ---------- 状态更新（主线程） ----------
    def on_state(self, payload):
        """主线程消息入口（MainWindow._dispatch 转进来）。"""
        if not isinstance(payload, dict):
            return
        kind = payload.get("type")
        if kind == "log":
            self.log.line(payload.get("text", ""), "dim")
        elif kind == "jobs":
            self._rebuild(payload.get("jobs") or [])
            auto = payload.get("auto")
            if auto is not None:
                self.auto_switch.blockSignals(True)
                self.auto_switch.setChecked(bool(auto))
                self.auto_switch.blockSignals(False)
        elif kind == "auto":
            self.auto_switch.blockSignals(True)
            self.auto_switch.setChecked(bool(payload.get("auto")))
            self.auto_switch.blockSignals(False)

    def _refresh(self):
        if self.pipe is not None:
            self._rebuild(self.pipe.job_list())

    def _rebuild(self, jobs):
        self.empty.setVisible(not jobs)
        seen = set()
        for job in jobs:
            jid = job.get("id") or ""
            if not jid:
                continue
            seen.add(jid)
            card_w = self.cards.get(jid)
            if card_w is None:
                card_w = _JobCard(job, self._jump, self._retry, self.list_box)
                self.list_lay.addWidget(card_w)
                self.cards[jid] = card_w
            else:
                card_w.update_job(job)
        for jid in list(self.cards):
            if jid not in seen:
                w = self.cards.pop(jid)
                self.list_lay.removeWidget(w)
                w.setParent(None)
                w.deleteLater()

    # ---------- 操作 ----------
    def _add_link(self):
        url = engine.extract_url(self.link_edit.text()) or self.link_edit.text().strip()
        if self.pipe is None:
            InfoBar.warning("提示", "流水线尚未启动，请稍候", duration=3000,
                            position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        jid, msg = self.pipe.add_link(url)
        if jid:
            self.link_edit.clear()
            self.log.line(f"[任务] {msg}（{url if len(url) <= 60 else url[:60] + '...'}）", "ok")
        else:
            InfoBar.warning("提示", msg, duration=3000,
                            position=InfoBarPosition.BOTTOM_RIGHT, parent=self)

    def _jump(self, job_id, stage_key):
        key = pl.STAGE_JUMP.get(stage_key, "download")
        try:
            page = self.app.page_by_key(key)
            if page is not None:
                self.app.switchTo(page)
        except Exception:  # noqa: BLE001
            pass

    def _retry(self, job_id, _stage=None):
        if self.pipe is not None:
            self.pipe.retry(job_id)

    def _retry_all(self):
        if self.pipe is None:
            return
        n = 0
        for job in self.pipe.job_list():
            stages = job.get("stages") or {}
            stalled = any((s or {}).get("state") in (pl.FAILED, pl.WAITING)
                          for s in stages.values())
            if stalled and not job.get("bootstrap"):
                self.pipe.retry(job.get("id") or "")
                n += 1
        self.log.line(f"[重试] 已重新排队 {n} 个任务" if n else "[重试] 没有停滞的任务",
                      "ok" if n else "dim")

    def _scan(self):
        if self.pipe is not None:
            self.pipe.manual_evaluate()
            self.log.line("[扫描] 已触发一次目录评估", "dim")

    def _open_out(self):
        if self.pipe is not None and os.path.isdir(self.pipe.out_root):
            engine.open_folder(self.pipe.out_root)

    def _on_auto(self, checked):
        if self.pipe is not None:
            self.pipe.set_auto(bool(checked))
            self.log.line(f"[开关] 自动流水线：{'开' if checked else '关'}", "dim")


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


class ConfirmDialog(QDialog):
    """确认框：**真·顶层模态窗口**，不是贴在主窗口里的自绘遮罩。

    为什么不能用 `qfluentwidgets.MessageBox`（v1.13.7 定论）：
    它在传了 parent 时会退化成**普通子控件** —— 探针实测
    `isWindow()==False`、`WS_CHILD==True`、`GetParent()` 就是主窗口、
    几何等于主窗口整块（见 `_workspace/probes/_probe_msgbox.py`）。而字幕编辑
    页的视频区是 **mpv 的原生子窗口**（`wid` 嵌进 `video_host`），原生子窗口在
    Windows 上永远盖在同级 Qt 自绘控件之前，并且播放器通常握着键盘焦点 ——
    于是用户看到的就是「这个框点不动、Esc/空格/回车全无反应」。

    顶层窗口由系统独立管理，不参与主窗口内部的层级之争，鼠标/键盘都稳。
    """

    def __init__(self, title, message, parent=None,
                 yes_text="确定", no_text="取消"):
        super().__init__(parent)
        # ⚠️ 必须是 Qt.Dialog：只给 FramelessWindowHint 会丢掉窗口类型
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint
                            | Qt.NoDropShadowWindowHint)
        self.setWindowModality(Qt.ApplicationModal)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowTitle(title or "确认")

        dark = False
        try:
            from qfluentwidgets import isDarkTheme
            dark = bool(isDarkTheme())
        except Exception:  # noqa: BLE001
            pass
        bg = "#2B2B2B" if dark else "#FFFFFF"
        fg = "#F3F3F3" if dark else "#1B1B1B"
        sub = "#C9C9C9" if dark else "#4C4C4C"
        line = "#3D3D3D" if dark else "#E6E6E6"

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame(self, objectName="vtConfirmCard")
        card.setAttribute(Qt.WA_StyledBackground, True)
        card.setStyleSheet(
            "#vtConfirmCard{background:%s;border:1px solid %s;"
            "border-radius:10px;}" % (bg, line))
        outer.addWidget(card)

        inner = QVBoxLayout(card)
        inner.setContentsMargins(26, 22, 26, 18)
        inner.setSpacing(10)

        lbl_title = QLabel(title or "确认", card, objectName="vtConfirmTitle")
        lbl_title.setStyleSheet(
            "#vtConfirmTitle{color:%s;font-size:15px;font-weight:600;"
            "background:transparent;border:none;}" % fg)
        lbl_body = QLabel(message or "", card, objectName="vtConfirmBody")
        lbl_body.setWordWrap(True)
        lbl_body.setStyleSheet(
            "#vtConfirmBody{color:%s;font-size:13px;background:transparent;"
            "border:none;}" % sub)
        lbl_body.setMinimumWidth(300)
        lbl_body.setMaximumWidth(420)
        inner.addWidget(lbl_title)
        inner.addWidget(lbl_body)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 8, 0, 0)
        buttons.setSpacing(10)
        buttons.addStretch(1)
        self.cancelButton = PushButton(no_text, card)
        self.yesButton = PrimaryPushButton(yes_text, card)
        for b in (self.cancelButton, self.yesButton):
            b.setFixedWidth(112)
        buttons.addWidget(self.cancelButton)
        buttons.addWidget(self.yesButton)
        inner.addLayout(buttons)

        self.cancelButton.clicked.connect(self.reject)
        self.yesButton.clicked.connect(self.accept)
        # 焦点落在"确定"上：回车即确认、Esc 即取消（QDialog 内建）
        self.yesButton.setFocus()
        self.adjustSize()

    def showEvent(self, e):
        super().showEvent(e)
        parent = self.parentWidget()
        if parent is not None:
            try:
                center = parent.window().frameGeometry().center()
                self.move(center - self.rect().center())
            except Exception:  # noqa: BLE001
                pass
        # 顶层窗口也可能被别的东西压在下面 / 没拿到前台，显式抬一次
        self.raise_()
        self.activateWindow()
        self.yesButton.setFocus()

    @staticmethod
    def release_stale_capture():
        """放掉可能残留的鼠标捕获（Windows 的 SetCapture 是独占的）。

        拖放（OLE）与视频窗口都会留下这种残留：谁握着捕获，鼠标消息就全归谁
        —— 对话框画得出来也点不动。ReleaseCapture 作用于**调用线程**，
        正是 GUI 线程自己。
        """
        if not sys.platform.startswith("win"):
            return
        try:
            import ctypes
            user32 = ctypes.windll.user32
            if user32.GetCapture():
                user32.ReleaseCapture()
        except Exception:  # noqa: BLE001
            pass

    @classmethod
    def ask(cls, parent, title, message, yes_text="确定", no_text="取消"):
        """弹一次确认；返回 True = 用户点了 yes。顶层模态，稳定可交互。"""
        cls.release_stale_capture()
        dlg = cls(title, message, parent, yes_text, no_text)
        try:
            return dlg.exec() == QDialog.Accepted
        finally:
            dlg.deleteLater()


# ========== 字幕编辑（打轴） ==========
class _VideoHost(QWidget):
    """播放器宿主：最小尺寸由 `setMinimumSize` 说了算。

    为什么不直接用 QWidget：mpv 是用 `wid` **嵌入**进来的原生子窗口，
    Qt 会把它的尺寸算进宿主控件的 `minimumSizeHint()` —— 载入视频后实测
    整个主窗口的最小高度从 620 涨到 810，于是窗口再也缩不下去（下边缘跑到
    屏幕外，"只能拉顶部、底部调不了"）。视频区该多小由我们声明，
    不该由播放器的原生窗口替我们决定。
    """

    def minimumSizeHint(self):
        # ⚠️ 判据必须是 **or**，不能写成 `and`：
        #    `setMinimumWidth` / `setMinimumHeight` 只要有一边没设（高度是 0），
        #    `and` 就不成立，于是回落到 `super().minimumSizeHint()` —— 而那个值
        #    里含着 mpv 原生子窗口的尺寸：载入视频后整个主窗口的最小高度会从
        #    620 一路涨到 810，窗口再也缩不下去（下边缘跑到屏幕外，"只能拉顶部、
        #    底部调不了"）。只要有一边是我们自己声明的，就以声明为准，
        #    视频区该多小由我们说了算，不该由播放器的原生窗口替我们决定。
        ms = self.minimumSize()
        if ms.width() > 0 or ms.height() > 0:
            return QSize(ms.width(), ms.height())
        return super().minimumSizeHint()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        # 尺寸一变就通知页面重算"视频框贴合比例"（见 SubtitleEditPage.
        # _fit_video_frame）。用回调而不是页面装 eventFilter：本类已经是
        # 播放器宿主的专有壳子，回调链路更短、也更好排查。
        cb = getattr(self, "resized_cb", None)
        if cb:
            try:
                cb()
            except Exception:  # noqa: BLE001
                pass


class SubtitleEditPage(ScrollPage):
    """字幕编辑（打轴）：播放器 + 波形时间轴 + 字幕表。

    结构照搬开源实现（Nosub 的三件套、KDE Subtitle Composer 的波形轨）：
      · 播放器  = libmpv 嵌进 QWidget（`subtitle_editor_media.MpvPlayer`）
      · 波形轨  = ffmpeg 解峰值 + 自绘字幕块（`subtitle_editor.WaveformTimeline`）
      · 字幕表  = 序号/起止/时长/文本（`subtitle_editor.CueTable`）
    数据层是 `subtitle_editor_core.SubtitleDoc` + `UndoStack`，时间一律 **int 毫秒**。

    三条底线：
      1. **许可**：libmpv 用 **LGPL** 构建，动态链接；
      2. **体积**：dll 不进安装包，由 `tools/download_open_source_deps.py`
         运行时拉取（沿用既有依赖拉取方案），缺失时本页只提示、不崩；
      3. **退出**：`aboutToQuit` 必须调 `shutdown()` 释放 libmpv，否则
         打包后 onefile 的 `_MEI***` 临时目录删不掉（v1.12.0 踩过）。
    """

    _wave_progress = pyqtSignal(int)          # 波形构建进度（0-100）
    _wave_ready = pyqtSignal(object, float)   # (peaks bytearray, 时长秒)
    _wave_failed = pyqtSignal(str)
    _mpv_ready = pyqtSignal(bool, str)        # 播放组件补装结果 (成功?, 错误)

    SPEEDS = ("0.25", "0.5", "0.75", "1.0", "1.25", "1.5", "2.0")
    #: 文本列里换行以 " / " 呈现（表格行高不随多行文本变化）；
    #: 提交时按同一分隔符还原。字幕里出现 " / " 的概率极低，且只在编辑该格时生效。
    NL_SEP = " / "

    def __init__(self, app, parent=None):
        # v1.13.x：副标题缩短到一行放得下，并 fit 掉自动换行。否则首次布局时
        # heightForWidth 会把 1 行算成 2 行 → 整页内容下移，就是「进页面上下闪一下」。
        super().__init__("字幕编辑",
                         "拖波形改起止时间，双击切分，[ ] 取起止点，空格播放暂停",
                         parent, scrollable=False)
        fit_caption(self.cap)
        self.app = app
        self.setObjectName("SubtitleEditPage")

        self.doc = secore.SubtitleDoc()
        self.undo = secore.UndoStack()
        self.video_path = ""
        self.sub_path = ""
        self.dirty = False
        self.ffmpeg = ""
        self.ffprobe = ""
        self._wave_stop = threading.Event()
        self._wave_busy = False
        # 播放器不可用提示的去重节流（拖时间轴会高频触发 _ensure_player，
        # 不去重的话 libmpv 缺失时错误 InfoBar 会连珠炮刷屏——用户实测截图）
        self._player_err_shown = ""
        self._player_err_at = 0.0
        self._mpv_installing = False
        self._mpv_pending_path = ""      # 补装完成后来不及 load 的媒体路径
        self._pre_drag = None            # 拖拽开始前的整档快照
        self._drag_pushed = False
        self._shortcuts = []
        # 画面字幕预览：cues -> ASS -> mpv 的 sub-add/sub-reload
        self._ass_sig = None             # 上次下发的 cues 指纹（相同就不重建）
        # 预览样式（字体 / 字号 / 颜色 / 描边 / 对齐 / 边距）**持久化**：
        # 这是用户一句句调出来的，重启就回默认等于白调。存数据根目录，不进 .srt。
        self._preview_style = dict(secore.ASS_DEFAULT_STYLE)
        self._preview_style.update(self._load_preview_style())
        self._cur_index = -2             # 面板正在显示的下标；-2 = 强制刷新

        self.mpv_dir = os.path.join(engine.TOOLS_DIR, "mpv")
        self.wave_cache = None
        self.player = MpvPlayer(self.mpv_dir, self)
        self.player.position_changed.connect(self._on_position)
        self.player.duration_changed.connect(self._on_duration)
        self.player.playing_changed.connect(self._on_playing)

        self._wave_progress.connect(self._on_wave_progress)
        self._wave_ready.connect(self._on_wave_ready)
        self._wave_failed.connect(self._on_wave_failed)
        self._mpv_ready.connect(self._on_mpv_ready)

        self._build_ui()
        self._install_shortcuts()
        self._refresh_status()

    # ---------------------------------------------------------
    # 界面
    # ---------------------------------------------------------
    def _build_ui(self):
        # 时间码放**状态栏右侧**（原来挂在工具条尾部，960px 窗口下会被压成
        # "00:02.000 /(" 什么都说不清）。
        self.lbl_time = StrongBodyLabel("--:--.--- / --:--.---", self)

        # —— 画面 + 右栏（右栏 = 字幕属性；字幕本身在**画面上**直接操作）——
        self.video_host = _VideoHost(self)
        self.video_host.setStyleSheet("background:#000;")
        self.video_host.setMinimumWidth(280)
        self.video_host.setMinimumHeight(160)
        # 视频框自适应长宽比：宿主尺寸一变就按视频比例重算高度（v1.14.3）
        self.video_host.resized_cb = self._fit_video_frame
        self.video_hint = CaptionLabel("尚未打开视频", self.video_host)
        self.video_hint.setStyleSheet("color:#777;background:transparent;")
        vlay = QVBoxLayout(self.video_host)
        vlay.setContentsMargins(0, 0, 0, 0)
        vlay.addWidget(self.video_hint, 0, Qt.AlignCenter)

        # v1.13.2：右栏不再保留字幕框/字幕列表，改为「字幕属性」面板。
        # 字幕本身是要"看得见、点得到、能拖"的东西，所以挪到画面上直接操作
        # （SubtitleStage），右侧只留外观参数；两边共用同一份样式字典。
        # 视频底部的一排图标控制栏：原来铺在页面顶部的两行文字按钮（工具条 +
        # 编辑条）全部并到这里，页面因此省下近 80px 高度还给画面。
        self.media_bar = self._build_media_bar()
        self.video_col = QWidget(self)
        vclay = QVBoxLayout(self.video_col)
        vclay.setContentsMargins(0, 0, 0, 0)
        vclay.setSpacing(2)
        vclay.addWidget(self.video_host, 1)
        vclay.addWidget(self.media_bar)
        # 视频框按比例压矮后，多出来的竖向空间要**上下均分**（视频块垂直
        # 居中）：前后各放一个 0 因子伸缩项。host 没封顶时 stretch=1 仍吃掉
        # 全部余量、两个伸缩项拿不到空间；被封顶后余量在两个伸缩项间对半
        # 分，控制条始终紧贴画面下沿。
        self._vclay = vclay
        vclay.insertStretch(0, 0)
        vclay.addStretch(0)

        self.props = SubtitlePropsPanel(self)

        # 画面字幕层：**顶层无边框透明窗口**，贴在视频的**实际显示区域**上。
        # 为什么不贴满 video_host：视频有黑边时（竖屏/异形比例）整块 widget 里
        # 只有中间一块是画面，贴满会让选框和真实字幕错位——字幕的坐标基准必须
        # 与画面一致，这是「浮层位置与字幕真实位置绑定」的关键。
        self.stage = SubtitleStage(self.video_host, self.window(),
                                   rect_provider=self._video_rect)

        self.hsplit = QSplitter(Qt.Horizontal, self)
        self.hsplit.setChildrenCollapsible(False)
        self.hsplit.addWidget(self.video_col)
        self.hsplit.addWidget(self.props)
        self.hsplit.setStretchFactor(0, 4)
        self.hsplit.setStretchFactor(1, 1)
        self.hsplit.setSizes([700, 300])

        self.timeline = WaveformTimeline(self)
        self.timeline.setMinimumHeight(110)

        # 全量列表（批量多选 / 合并 / 删除）挪到时间轴下方的抽屉里、默认收起：
        # 右栏让给了属性面板，但"批量改时间"的能力不能跟着丢。
        self.table = CueTable(self)
        self.table.setMinimumHeight(96)
        self.table_shell = QWidget(self)
        tlay = QVBoxLayout(self.table_shell)
        tlay.setContentsMargins(0, 0, 0, 0)
        tlay.setSpacing(0)
        tlay.addWidget(self.table)
        self.table_shell.hide()

        self.vsplit = QSplitter(Qt.Vertical, self)
        self.vsplit.setChildrenCollapsible(False)
        self.vsplit.addWidget(self.hsplit)
        self.vsplit.addWidget(self.timeline)
        self.vsplit.setStretchFactor(0, 1)
        self.vsplit.setStretchFactor(1, 0)
        self.vsplit.setSizes([520, 150])
        self.vbox.addWidget(self.vsplit, 1)
        self.vbox.addWidget(self.table_shell)

        # —— 状态区（左：状态文字；右：时间码）——
        srow = QHBoxLayout()
        srow.setSpacing(12)
        self.status = CaptionLabel("就绪", self)
        self.status.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        srow.addWidget(self.status, 1)
        srow.addWidget(self.lbl_time, 0)
        self.shell_status = QWidget(self)
        self.shell_status.setLayout(srow)
        self.vbox.addWidget(self.shell_status)
        # v1.13.x：进度条必须放进**固定高度容器**再显隐。直接 addWidget 后 hide()，
        # 它一出现/一消失就带着下方内容上下位移（4px + 布局间距），
        # 表现出来正是「进页面上下闪一下」。容器常驻，显隐只影响它自己。
        self.wave_slot = QWidget(self)
        self.wave_slot.setFixedHeight(6)
        slot_lay = QVBoxLayout(self.wave_slot)
        slot_lay.setContentsMargins(0, 0, 0, 0)
        slot_lay.setSpacing(0)
        self.wave_bar = ProgressBar(self.wave_slot)
        self.wave_bar.setFixedHeight(4)
        slot_lay.addWidget(self.wave_bar)
        self.wave_bar.hide()
        self.vbox.addWidget(self.wave_slot)

        # —— 信号 ——
        # 控制栏上那批按钮的信号在 `_build_media_bar` 里已经连好，这里不再重复连
        # （连两次会让每次点击都触发两遍）。

        self.timeline.position_clicked.connect(self.seek_ms)
        self.timeline.cue_selected.connect(self._on_timeline_cue_selected)
        self.timeline.drag_started.connect(self._on_drag_started)
        self.timeline.cue_dragged.connect(self._on_cue_dragged)
        self.timeline.drag_finished.connect(self._on_drag_finished)
        self.timeline.split_requested.connect(self._on_split_requested)
        self.table.selection_changed.connect(self._on_table_selection)
        self.table.cell_committed.connect(self._on_cell_committed)
        self.btn_list.clicked.connect(self.toggle_list)
        self.props.step_requested.connect(self.goto_cue)
        self.props.style_changed.connect(self._on_style_changed)
        self.props.export_requested.connect(self.export_subtitle)
        self.props.set_style(self._preview_style)

        # —— 画面字幕层（点选 / 拖动 / 就地改字 / 双击空白播放暂停）——
        self.stage.cue_clicked.connect(self._on_stage_cue_clicked)
        self.stage.cue_followed.connect(self._on_stage_cue_followed)
        self.stage.delete_requested.connect(self._on_stage_delete)
        self.stage.selection_cleared.connect(self._on_stage_cleared)
        self.stage.command_requested.connect(self._on_stage_command)
        self.stage.text_committed.connect(self._on_stage_text)
        self.stage.layout_changed.connect(self._on_stage_layout)
        self.stage.layout_preview.connect(self._on_stage_layout_preview)
        self.stage.play_toggled.connect(self.toggle_play)
        self.stage.set_style(self._preview_style)
        self.stage.set_cues(self.doc.cues)

    # ---------------------------------------------------------
    # 视频底部的一排图标控制栏
    # ---------------------------------------------------------
    #: 控制栏图标按钮的边长（逻辑像素）。19 个图标 + 5 条分隔线 + 倍速下拉要在
    #: 一排里放下（1280 屏上窗口收敛后视频区只有 ~610px 宽），26 是实测算得下
    #: 的最大值——再大就会挤到裁切。
    BAR_ICON = 22

    def _build_media_bar(self):
        """视频**底部**的一排图标控制栏（原顶部两行文字按钮的替代）。

        两组考虑：
          · **放视频下面，不叠进画面**——video_host 里跑的是 mpv 的**原生
            子窗口**，任何 Qt 控件叠进去都会被它盖住，一个图标都看不见；
          · **全图标 + tooltip**——18 个中文按钮并排必然放不下，纯图标才能
            在一排里排开，完整说明留在 tooltip 与快捷键里。
        """
        bar = QWidget(self)
        bar.setObjectName("MediaBar")
        bar.setFixedHeight(self.BAR_ICON + 4)
        # 用 #MediaBar 限定，避免样式级联到里面的图标按钮上；
        # 配色主题感知（_apply_media_bar_theme），不再写死深色。
        self._media_dividers = []
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(8, 2, 8, 2)
        # 20 个图标 + 5 条分组竖线要在一排里放得下：按最小窗口（880 宽 → 视频区
        # 约 467px）反推，图标 22px、间距 1px 刚好富裕一点。再大就会互相重叠。
        lay.setSpacing(1)

        def ibtn(icon, tip, slot, checkable=False):
            b = ToolButton(icon, self)
            b.setFixedSize(self.BAR_ICON, self.BAR_ICON)
            b.setToolTip(tip)
            if checkable:
                b.setCheckable(True)
            b.clicked.connect(slot)
            # stretch=1：按钮本身是固定尺寸，多出来的空间由布局均分，于是
            # 图标沿整条栏**均匀铺开**，而不是全堆在左边（右边留一大片空）。
            lay.addWidget(b, 1)
            return b

        def divider():
            line = QWidget(bar)
            line.setFixedSize(1, 14)
            self._media_dividers.append(line)
            lay.addWidget(line)

        # —— 文件 ——
        self.btn_video = ibtn(FIF.VIDEO, "打开视频（Ctrl+O）", self.open_video)
        self.btn_sub = ibtn(FIF.FONT, "打开字幕（Ctrl+Shift+O）", self.open_subtitle)
        self.btn_save = ibtn(FIF.SAVE, "保存（Ctrl+S）", self.save)
        self.btn_save_as = ibtn(FIF.SAVE_AS, "另存为（Ctrl+Shift+S）", self.save_as)
        self.btn_close_media = ibtn(FIF.CLOSE, "关闭视频：卸下当前视频并复位波形"
                                              "（字幕不动）", self.close_video)
        divider()

        # —— 播放 ——
        self.btn_prev_frame = ibtn(FIF.CARE_LEFT_SOLID, "上一帧（← 或 ,）",
                                   lambda: self.step_frames(-1))
        self.btn_play = ibtn(FIF.PLAY_SOLID, "播放 / 暂停（空格）", self.toggle_play)
        self.btn_next_frame = ibtn(FIF.CARE_RIGHT_SOLID, "下一帧（→ 或 .）",
                                   lambda: self.step_frames(1))
        self.speed_box = ComboBox(bar)
        self.speed_box.addItems(self.SPEEDS)
        self.speed_box.setCurrentText("1.0")
        self.speed_box.setFixedWidth(62)
        self.speed_box.setToolTip("播放倍速")
        self.speed_box.currentTextChanged.connect(self._on_speed)
        lay.addWidget(self.speed_box, 1)
        divider()

        # —— 编辑 ——
        self.ops = []
        self.btn_split = ibtn(FIF.CUT, "切分：在播放头处把选中条目切成两条"
                                       "（Ctrl+K，或在波形上双击）", self.split_at_playhead)
        self.btn_merge = ibtn(FIF.CONSTRACT, "合并：把选中的多条合并为一条",
                              self.merge_selected)
        self.btn_del = ibtn(FIF.DELETE, "删除选中条目（Del）", self.delete_selected)
        self.btn_ins = ibtn(FIF.ADD, "插入：在播放头处插入一条 1.5s 空白字幕",
                            self.insert_at_playhead)
        self.ops.extend([self.btn_split, self.btn_merge, self.btn_del, self.btn_ins])
        divider()

        # —— 起止点 / 平移 ——
        self.btn_start = ibtn(FIF.PAGE_LEFT, "取起点：把选中条目的起点设为播放头（[）",
                              self.set_start_here)
        self.btn_end = ibtn(FIF.PAGE_RIGHT, "取终点：把选中条目的终点设为播放头（]）",
                            self.set_end_here)
        self.btn_fwd = ibtn(FIF.LEFT_ARROW, "前移 0.1s（Shift+←）",
                            lambda: self.shift_selected(-100))
        self.btn_bwd = ibtn(FIF.RIGHT_ARROW, "后移 0.1s（Shift+→）",
                            lambda: self.shift_selected(100))
        self.ops.extend([self.btn_start, self.btn_end])
        divider()

        # —— 历史 ——
        self.btn_undo = ibtn(FIF.HISTORY, "撤销（Ctrl+Z）", self.undo_edit)
        self.btn_redo = ibtn(FIF.SYNC, "重做（Ctrl+Y）", self.redo_edit)
        divider()

        # —— 工具 ——
        self.btn_compose = ibtn(FIF.MOVIE, "内嵌字幕：把当前字幕作为独立轨道内嵌"
                                           "进视频，音视频原样复制、不重新编码",
                                self.open_compose)
        self.btn_list = ibtn(FIF.MENU, "展开时间轴下方的全量列表"
                                       "（多选合并 / 批量删除 / 改时间）",
                             self.toggle_list, checkable=True)
        # 不加 addStretch —— 靠每项的 stretch=1 均分，图标才是「均匀排列」
        self._apply_media_bar_theme(bar)
        try:
            import ui_theme
            ui_theme.connect_theme(bar, lambda w: self._apply_media_bar_theme())
        except Exception:
            pass
        return bar

    def _apply_media_bar_theme(self, bar=None):
        """媒体条配色主题感知（v1.14.1）：深色=深控制台条，浅色=浅灰条。

        此前写死 #1b1b1b 深底 + #3d3d3d 分隔线，浅色主题下与整页白卡片
        割裂（用户截图反馈「浅色背景中不协调」）。浅色底改取 log_bg 同款
        #F4F6F8、分隔线取 border_hover，与日志控制台保持同一设计语言；
        深色下 log_bg 恰好就是原来的 #1b1b1b，观感不变。
        `bar` 可显式传入——构建期 self.media_bar 还没挂上（先建后赋值）。
        """
        bar = bar if bar is not None else getattr(self, "media_bar", None)
        if bar is None:
            return
        import ui_theme
        t = ui_theme.tokens()
        bar.setStyleSheet(
            "QWidget#MediaBar{background:%s;border-top:1px solid %s;}"
            % (t["log_bg"], t["border"]))
        for line in getattr(self, "_media_dividers", []):
            line.setStyleSheet("background:%s;" % t["border_hover"])

    # ---------------------------------------------------------
    # 字幕列表抽屉（批量改时间用；右栏已让给属性面板）
    # ---------------------------------------------------------
    def toggle_list(self):
        """展开/收起时间轴下方的全量列表。"""
        show = self.btn_list.isChecked()
        self.table_shell.setVisible(show)
        if show:
            self.table.load(self.doc.cues)
            idx = self.timeline.selected
            if idx >= 0:
                self.table.select_row(idx)
            self.table.setFocus()
        else:
            self.timeline.setFocus()
        self._refresh_status("已展开字幕列表" if show else "")

    # ---------------------------------------------------------
    # 快捷键（WidgetWithChildren：焦点在本页时才生效，不抢别的页面）
    # ---------------------------------------------------------
    def _install_shortcuts(self):
        def add(seq, slot):
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(slot)
            self._shortcuts.append(sc)

        add("Space", self.toggle_play)
        # 逐帧：Aegisub 的 , / . 是行业习惯；←/→ 同时可用（表格内编辑时让路）
        add(",", lambda: self.step_frames(-1))
        add(".", lambda: self.step_frames(1))
        add("Left", lambda: self.step_frames(-1))
        add("Right", lambda: self.step_frames(1))
        add("Shift+Left", lambda: self.nudge(-100))
        add("Shift+Right", lambda: self.nudge(100))
        add("Alt+Left", lambda: self.nudge(-1000))
        add("Alt+Right", lambda: self.nudge(1000))
        add("Up", lambda: self.goto_cue(-1))
        add("Down", lambda: self.goto_cue(1))
        add("[", self.set_start_here)
        add("]", self.set_end_here)
        add("Ctrl+K", self.split_at_playhead)
        add("Ctrl+A", self.select_all_cues)
        add("Del", self.delete_selected)
        add("Ctrl+Z", self.undo_edit)
        add("Ctrl+Y", self.redo_edit)
        add("Ctrl+Shift+Z", self.redo_edit)
        add("Ctrl+S", self.save)
        add("Ctrl+Shift+S", self.save_as)
        add("Ctrl+O", self.open_video)
        add("Ctrl+Shift+O", self.open_subtitle)
        add("Ctrl+=", lambda: self.timeline.zoom(1.25))
        add("Ctrl+-", lambda: self.timeline.zoom(1 / 1.25))
        add("Ctrl+0", self.timeline.fit_all)
        add("Ctrl+Shift+F", self.fit_selected)

    def _table_editing(self):
        """表格正在改单元格时，方向键要还给文本编辑框。"""
        try:
            if self.table.state() == QAbstractItemView.EditingState:
                return True
            w = QApplication.focusWidget()
            return w is not None and w.metaObject().className() in (
                "QLineEdit", "QTextEdit", "QPlainTextEdit")
        except Exception:
            return False

    def _forgive_key(self, seq):
        """把被快捷键吃掉的按键原样转发给当前焦点控件（表格内编辑用）。"""
        try:
            fw = QApplication.focusWidget()
            if fw is None:
                return
            key = QKeySequence(seq)[0]
            ev = QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier)
            QApplication.sendEvent(fw, ev)
        except Exception:
            pass

    # ---------------------------------------------------------
    # 生命周期
    # ---------------------------------------------------------
    def relayout_after_screen_change(self):
        """跨屏 / DPI 变化后重新收敛本页布局。

        必须做两件事：
          · **重设分割条比例**。Qt 在 PPI 变化后按各子项的 sizeHint 重排
            splitter，把视频区压扁、属性面板顶宽——用户看到的就是"跨屏
            拖动后页面扭曲变形"；而比例只在首次 show 时设过一次。
          · **让字幕层重新贴合画面**。它是顶层窗口，不会跟着主窗口的重排走，
            跨屏后会停在旧坐标上（看起来像浮在别处）。
        """
        self._apply_split_defaults()
        try:
            self._sync_stage_visible()
            self.stage.snap_to_host()
        except Exception:  # noqa: BLE001
            pass

    def _apply_split_defaults(self):
        """按黄金比例分配上下 / 左右两个分割条。

        为什么不能只在 `_build_ui` 里 `setSizes()` 就完事：构造时 splitter 的
        尺寸还是 0，Qt 会把这次 setSizes 当成"比例提示"记下来，随后又按各子项
        的 sizeHint 重新分配——结果视频区被压成一条（实测 531x173），属性面板
        也跟着挤到最小宽度。必须等**首次 show 之后**再设一次，这时尺寸才是真的。

        左右 72:28、上下 84:16：这是让视频画面接近 16:9、右栏刚好放得下属性
        面板、时间轴又不至于缩到看不见的一组值（按 1180x729 与 1280 屏实测
        收敛后的 1080x667 两档算的——后者上下空间更紧，取 84 才不至于把画面
        压成一条）。
        """
        try:
            w = self.hsplit.width()
            if w > 0:
                left = int(w * 0.72)
                self.hsplit.setSizes([left, w - left])
            h = self.vsplit.height()
            if h > 0:
                top = int(h * 0.84)
                self.vsplit.setSizes([top, h - top])
        except Exception:  # noqa: BLE001
            pass

    def showEvent(self, ev):
        super().showEvent(ev)
        QTimer.singleShot(0, lambda: self.timeline.setFocus())
        # 首次进页面时把属性面板对齐到播放头（此时还没有播放器）
        QTimer.singleShot(0, self._sync_current)
        # 字幕层是顶层窗口，页面不走它自己那一套显隐，必须手动跟
        QTimer.singleShot(0, self._sync_stage_visible)
        if not getattr(self, "_split_done", False):
            self._split_done = True
            QTimer.singleShot(0, self._apply_split_defaults)
            QTimer.singleShot(150, self._apply_split_defaults)

    def hideEvent(self, ev):
        # 页面切走后立刻暂停：mpv 在后台解码只是白烧 CPU
        try:
            if self.player.is_playing():
                self.player.pause()
        except Exception:
            pass
        try:
            self.stage.hide_stage()
        except Exception:
            pass
        super().hideEvent(ev)

    def shutdown(self):
        """退出前释放画面字幕层与 libmpv。

        两件事都必须做：
          · libmpv 不 `terminate()` 会留下 _MEI*** 删不掉的毛病（v1.12.0 踩过）；
          · 画面字幕层是个**顶层窗口**，进程退出时若它还活着，Qt 会在
            销毁顺序上踩空——实测收尾阶段访问冲突（0xC0000005，无 traceback），
            所以显式关掉再解引用。
        """
        self._wave_stop.set()
        try:
            self.stage.hide_stage()
            self.stage.close()
            self.stage.setParent(None)
            self.stage.deleteLater()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.player.terminate()
        except Exception:  # noqa: BLE001
            pass

    # ---------------------------------------------------------
    # 画面字幕层
    # ---------------------------------------------------------
    def _video_rect(self):
        """视频在 video_host 里的**实际显示矩形**（逻辑像素，已去掉黑边）。

        字幕的坐标基准必须和画面一致：竖屏视频、异形比例、或者窗口被拉成
        别的比例时，widget 里只有中间一块是画面，其余是黑边。字幕层贴
        "画面"而不是"widget"，选框和真实字幕才不会错位。
        """
        w, h = self.video_host.width(), self.video_host.height()
        if w < 8 or h < 8:
            return QRect(0, 0, max(0, w), max(0, h))
        ar = self.player.video_aspect() if self.player else 0.0
        if ar <= 0.01:
            return QRect(0, 0, w, h)          # 还没有视频：整块都算画面
        if w / float(h) > ar:                 # widget 更宽 → 左右留黑边
            vw = int(round(h * ar))
            return QRect((w - vw) // 2, 0, vw, h)
        vh = int(round(w / ar))               # widget 更高 → 上下留黑边
        return QRect(0, (h - vh) // 2, w, vh)

    def _fit_video_frame(self):
        """让视频框高度**跟随视频宽高比**（v1.14.3，去黑边）。

        以前 video_host 无条件铺满可用区域，比例不合的画面由 mpv 在里面
        加黑边——16:9 视频在偏方的宿主里上下全是黑框。现在拿到视频比例后
        把 host 的**最大高度**压到 `宽 / 比例`：

          · 用 maxHeight + Expanding 而不是 setFixedHeight：竖向空间不够时
            布局仍能把 host 压回可用高度（此时才轮到 mpv 左右加黑边兜底），
            不会撑破 video_col，拖竖向分割条也不会把画面挤出界；
          · 比例未知 / 没视频时解除封顶，回到铺满 + "尚未打开视频"占位；
          · 触发点：载入媒体（60ms / 400ms 两次，等 mpv 解出 video-params）、
            duration 就绪、宿主 resize（`_VideoHost.resized_cb`）、关视频。
        """
        host = self.video_host
        if host.width() < 8:
            return
        ar = self.player.video_aspect() if (self.player and self.video_path) else 0.0
        if ar <= 0.01:
            if host.maximumHeight() != 16777215:   # QWIDGETSIZE_MAX
                host.setMaximumHeight(16777215)
            return
        # 可用高度 = video_col 高度 - 控制条 - 布局间距（vclay spacing=2）
        try:
            spacing = self._vclay.spacing()
        except Exception:  # noqa: BLE001
            spacing = 2
        avail = self.video_col.height() - self.media_bar.height() - spacing
        target = int(round(host.width() / ar))
        target = max(host.minimumHeight(), min(target, max(160, avail)))
        if host.maximumHeight() != target:
            host.setMaximumHeight(target)

    def _sync_stage_visible(self):
        """按「有视频 + 页面可见」决定字幕层显隐。"""
        try:
            show = bool(self.video_path) and self.isVisible()
            if show:
                self.stage.show_over()
            else:
                self.stage.hide_stage()
        except Exception:
            pass

    def _on_stage_cue_clicked(self, idx):
        """在画面上**点一下**某条字幕：单选语义（覆盖时间轴/表格的多选）。"""
        if not (0 <= idx < len(self.doc.cues)):
            return
        self.timeline.set_selected(idx)
        self.table.select_row(idx)
        cue = self.doc.cues[idx]
        self.props.set_cue(cue, idx, len(self.doc.cues))

    def _on_stage_cue_followed(self, idx):
        """**拖动**某条字幕后的主选中跟随：只更新"当前条"，**保留多选**——
        否则 Ctrl+A 全选后拖一下画面字幕，全选就被打散了（用户实测）。"""
        if not (0 <= idx < len(self.doc.cues)):
            return
        self.timeline.selected = idx          # 只改主选中，不动 selected_set
        self.timeline._repaint_cues()
        self.table.reveal_row(idx)
        self.props.set_cue(self.doc.cues[idx], idx, len(self.doc.cues))

    def _on_stage_delete(self, idx):
        """画面右键「删除此字幕」：纯鼠标的删除入口。"""
        if not (0 <= idx < len(self.doc.cues)):
            return
        self._push_undo("删除")
        secore.delete_cues(self.doc.cues, [idx])
        self._after_bulk_change(keep_sel=min(idx, len(self.doc.cues) - 1))
        self._refresh_status("已删除 1 条（画面右键）")

    def _on_stage_command(self, name):
        """画面字幕层激活时的键盘命令（stage 是独立顶层窗口，主窗的
        QShortcut 此刻收不到——见 SubtitleStage.keyPressEvent）。"""
        fn = {"del": self.delete_selected,
              "undo": self.undo_edit,
              "redo": self.redo_edit,
              "all": self.select_all_cues,
              "play": self.toggle_play}.get(name)
        if fn:
            fn()

    def _on_stage_cleared(self):
        self.timeline.set_selected(-1)

    def _on_stage_text(self, idx, text):
        """画面上的就地编辑提交：和列表里改文本走同一条落库路径。"""
        self._on_current_text(idx, text)

    def _on_stage_layout(self, style):
        """画面拖动 / 把手缩放改了版式：并入预览样式。

        v1.14.2：画面上的一切手势只写**自由位置**（pos_x / pos_y）与字号、
        缩放，不再回写 alignment / margin_v —— 所以拖多少次都不会把面板的
        对齐选中态和全局边距改掉（"位置调整是一次性的"）。
        """
        self._preview_style = dict(secore.ASS_DEFAULT_STYLE)
        self._preview_style.update(style or {})
        self._ass_sig = None
        self._save_preview_style()
        self._push_preview(force=True)
        self.props.set_style(self._props_view(self._preview_style))
        self._refresh_status("已调整字幕版式（自由位置）")

    def _on_stage_layout_preview(self, style):
        """拖动 / 缩放**过程中**的实时读数（节流 25Hz，见 SubtitleStage）。

        只刷面板显示：不落盘、不重建预览、不动 `_preview_style` —— 那些都
        留给松手后的 `_on_stage_layout`，否则一串 mouseMove 会变成一串
        json 写盘 + ASS 重建。
        """
        try:
            self.props.set_style(self._props_view(style))
        except Exception:  # noqa: BLE001
            pass

    def _props_view(self, style):
        """给属性面板的显示副本：补上等效「垂直距 / 水平距」。

        面板那两个框的语义是"距对齐边"，而画面上拖动写的是自由位置 pos，
        不做折算就会完全脱节（用户拖动时数字一动不动）。`_va/_ha` 只是
        面板私有读法，不进样式、不落盘。
        """
        view = dict(style or {})
        try:
            view.update(self.stage.panel_metrics() or {})
        except Exception:  # noqa: BLE001
            pass
        return view

    # ---------------------------------------------------------
    # 依赖与提示
    # ---------------------------------------------------------
    def _info(self, kind, title, text, duration=4000):
        try:
            fn = {"ok": InfoBar.success, "warn": InfoBar.warning,
                  "err": InfoBar.error}.get(kind, InfoBar.info)
            fn(title, text, duration=duration, position=InfoBarPosition.TOP,
               parent=self.window() or self)
        except Exception:
            pass

    def _media_tools(self):
        """返回 (ffmpeg, ffprobe)；够不到就抛 RuntimeError 由调用方提示。"""
        if self.ffmpeg and self.ffprobe:
            return self.ffmpeg, self.ffprobe
        try:
            ff, fp = engine.ensure_ffmpeg()
        except SystemExit:
            raise RuntimeError("ffmpeg 不可用（自动下载失败）")
        if not (ff and fp and os.path.isfile(ff) and os.path.isfile(fp)):
            raise RuntimeError("找不到 ffmpeg / ffprobe")
        self.ffmpeg, self.ffprobe = ff, fp
        if self.wave_cache is None:
            self.wave_cache = WaveformCache(engine.DATA_DIR, ff, fp)
        return ff, fp

    def _ensure_player(self, quiet=False):
        """播放器按需创建：窗口真正显示后 winId() 才有效，因此不能提前建。

        构造页面时主窗口还没 show()，此时拿句柄会绑到一个随后被销毁的原生
        窗口上，表现为「有声音没画面」。

        quiet=True：失败不弹 InfoBar（拖时间轴等高频路径用——seek_ms 每次
        mouseMove 都会走到这里，去重 + 静默才能既保住"没视频也能拖时间轴
        定位"又不刷屏）。quiet=False 时同一错误 60 秒内也只提示一次。
        """
        if self.player.available:
            return True
        if not self.player.attach(self.video_host):
            err = self.player.error or "未知原因"
            now = time.monotonic()
            if (not quiet and err != self._player_err_shown
                    and now - self._player_err_at > 60):
                self._info("err", "播放器不可用", err[:300], 8000)
                self._player_err_shown = err
                self._player_err_at = now
            return False
        self._player_err_shown = ""
        return True

    def _install_mpv_async(self, pending_path=""):
        """后台补装 libmpv-2.dll（安装版不随包分发，用户机器上常常没有）。

        成功后自动重试挂播放器；pending_path 记下补装期间用户已选择的视频，
        装好即自动载入——用户对"下载了 39MB"的唯一感知就是"视频能放了"。
        """
        if self._mpv_installing:
            if pending_path:
                self._mpv_pending_path = pending_path
            return
        self._mpv_installing = True
        if pending_path:
            self._mpv_pending_path = pending_path
        self._info("warn", "正在补齐播放组件",
                   "libmpv-2.dll（约 39MB，仅首次）下载中，完成后自动恢复视频预览",
                   10000)

        def work():
            try:
                ok, err = engine.ensure_mpv_dll(self.mpv_dir)
            except Exception as e:  # noqa: BLE001
                ok, err = False, "%s: %s" % (type(e).__name__, e)
            self._mpv_ready.emit(ok, err)

        threading.Thread(target=work, name="vt-mpv-install", daemon=True).start()

    def _on_mpv_ready(self, ok, err):
        self._mpv_installing = False
        if not ok:
            self._info("err", "播放组件补装失败", (err or "未知原因")[:300], 10000)
            return
        self._info("ok", "播放组件已就绪", "视频预览已恢复可用", 5000)
        path = self._mpv_pending_path or self.video_path
        self._mpv_pending_path = ""
        if path and os.path.isfile(path) and self._ensure_player():
            self.player.load(path, autoplay=False)
            # 与 load_media 相同的延迟同步：等 mpv 解出宽高比再贴字幕层/贴合视频框
            QTimer.singleShot(60, self._sync_stage_visible)
            QTimer.singleShot(400, self._sync_stage_visible)
            QTimer.singleShot(60, self._fit_video_frame)
            QTimer.singleShot(400, self._fit_video_frame)

    def _mpv_missing_hint(self):
        dll = os.path.join(self.mpv_dir, "libmpv-2.dll")
        return ("未找到播放组件：\n%s\n\n"
                "请在程序目录执行（首次约 40MB）：\n"
                "    python tools\\download_open_source_deps.py --only mpv\n\n"
                "或到发布页手动下载 libmpv-2.zip 解压到 tools\\mpv\\。\n"
                "该组件为 LGPL 构建，不随安装包分发。" % dll)

    # ---------------------------------------------------------
    # 打开文件
    # ---------------------------------------------------------
    def _confirm_discard(self):
        if not self.dirty:
            return True
        # ⚠️ 用 ConfirmDialog（真·顶层模态），不要用 qfluentwidgets.MessageBox：
        #    后者退化成主窗口里的子控件，会被 mpv 原生子窗口吃掉鼠标、被播放器
        #    占着键盘焦点，表现为「整个框点不动、Esc/空格/回车都没反应」。
        return ConfirmDialog.ask(
            self.window() or self, "字幕尚未保存",
            "当前改动还没写回文件，确定要放弃吗？",
            yes_text="放弃改动", no_text="取消")

    def open_video(self):
        if not self._confirm_discard():
            return
        start = engine.get_saved_download_dir()
        start = start if os.path.isdir(start) else ""
        path, _ = QFileDialog.getOpenFileName(
            self, "打开视频", start, MEDIA_FILE_FILTER)
        if not path:
            return
        self.load_media(path)

    def load_media(self, path):
        """直接按路径载入媒体（拖进窗口 / 命令行入口），不再弹文件对话框。

        v1.13.0：与 open_video 共用同一套载入逻辑；libmpv 本身支持
        av1 / h264 / h265 / x264 等全格式，这里不再限制扩展名。

        v1.14.1：**播放组件缺失不再挡住载入**——此前 _ensure_player 失败
        直接 return，安装版用户（libmpv 不随包分发）连视频都放不进来，
        字幕/波形也一并瘫痪。现在降级载入：波形与字幕表照常（走 ffmpeg，
        与 mpv 无关），画面预览缺失只提示；同时后台自动补装组件，装好即
        自动载入刚才那份视频，无需用户重试。
        """
        if not self._confirm_discard():
            return False
        if not self._ensure_player(quiet=True):
            # 组件缺失：降级载入 + 后台补装，装好后 _on_mpv_ready 自动 load
            self._install_mpv_async(pending_path=path)
        self.video_path = path
        self.video_hint.hide()
        self._refresh_status()
        self._start_waveform(path)
        if self.player.available:
            self.player.load(path, autoplay=False)
            # 视频就绪 → 把画面字幕层贴到视频的**实际显示区域**并显示出来。
            # 延后一帧：此时 mpv 才拿到宽高比，抽黑边算出来的矩形才是准的。
            QTimer.singleShot(60, self._sync_stage_visible)
            QTimer.singleShot(400, self._sync_stage_visible)
            # 视频框自适应比例：mpv 解出 video-params 需要一点时间，两次兜底，
            # `_on_duration` 里还有最后一次（那时比例一定就绪了）。
            QTimer.singleShot(60, self._fit_video_frame)
            QTimer.singleShot(400, self._fit_video_frame)
        return True

    def close_video(self):
        """关闭当前视频，回到"尚未打开视频"的状态。

        只卸视频，**不动字幕**——字幕是独立文档，用户常常是"换一段视频接着
        用同一份字幕"。所以这里不碰 `doc` / `sub_path` / `dirty`。
        """
        if not self.video_path and not self.player.available:
            self._refresh_status("当前没有视频")
            return
        self._wave_stop.set()
        try:
            self.player.close_media()
        except Exception:  # noqa: BLE001
            pass
        self.video_path = ""
        try:
            self.stage.hide_stage()
        except Exception:  # noqa: BLE001
            pass
        self.video_hint.show()
        self.video_hint.raise_()
        # 解除比例封顶，视频框回到铺满状态接住占位提示
        self._fit_video_frame()
        # 波形与时长一起复位，否则时间轴还留着上一段视频的刻度
        self.timeline.set_media(bytearray(), 0, self.timeline.peaks_pps)
        self.timeline.set_cues(self.doc.cues)
        self._ass_sig = None
        self._cur_index = -2
        self._refresh_status("已关闭视频")
        self._sync_current()

    def open_subtitle(self):
        if not self._confirm_discard():
            return
        start = os.path.dirname(self.video_path) if self.video_path else ""
        if not start:
            start = engine.get_saved_download_dir()
            start = start if os.path.isdir(start) else ""
        path, _ = QFileDialog.getOpenFileName(
            self, "打开字幕", start, "字幕文件 (*.srt);;文本文件 (*.txt);;所有文件 (*.*)")
        if path:
            self.load_subtitle(path)

    def load_subtitle(self, path):
        """直接按路径载入字幕（拖进窗口 / 命令行入口）。"""
        if not self._confirm_discard():
            return False
        self._load_subtitle(path)
        return True

    def _load_subtitle(self, path):
        if not path:
            return
        try:
            with open(path, "rb") as fh:
                n, skipped = self.doc.load_bytes(fh.read(), path)
        except OSError as e:
            self._info("err", "读取失败", str(e)[:200])
            return
        self.sub_path = path
        self.undo.clear()
        self.dirty = False
        self.timeline.set_cues(self.doc.cues)
        self.table.load(self.doc.cues)
        self.timeline.set_selected(-1)
        self._sync_duration()
        self._refresh_status()
        self._mark_preview_dirty()
        self._sync_current()
        msg = "已载入 %d 条（编码 %s，换行 %s）" % (
            n, self.doc.src_encoding,
            "CRLF" if self.doc.newline == "\r\n" else "LF")
        if skipped:
            msg += "；跳过 %d 行无法识别的内容" % skipped
        self._info("ok", "字幕已载入", msg)

    def new_subtitle(self):
        if not self._confirm_discard():
            return
        self.doc = secore.SubtitleDoc()
        self.sub_path = ""
        self.undo.clear()
        self.dirty = False
        self.timeline.set_cues(self.doc.cues)
        self.table.load(self.doc.cues)
        self._refresh_status()
        self._mark_preview_dirty()
        self._sync_current()

    def _sync_duration(self):
        """时间轴总长取「视频时长 / 字幕末尾」两者较大值。"""
        dur_ms = self.player.duration_ms
        try:
            self.timeline.set_fps(self.player.fps)   # 帧刻度/帧号用真实帧率
        except Exception:
            pass
        if self.doc.cues:
            dur_ms = max(dur_ms, max(c.end for c in self.doc.cues) + 1000)
        if dur_ms:
            self.timeline.set_media(self.timeline.peaks, dur_ms,
                                    self.timeline.peaks_pps)

    # ---------------------------------------------------------
    # 保存
    # ---------------------------------------------------------
    def save(self):
        if not self.doc.cues:
            self._info("warn", "没有内容", "当前没有可保存的字幕")
            return
        if not self.doc.path:
            self.save_as()
            return
        self._write(self.doc.path)

    def save_as(self):
        if not self.doc.cues:
            self._info("warn", "没有内容", "当前没有可保存的字幕")
            return
        start = self.doc.path or (os.path.splitext(self.video_path)[0] + ".srt"
                                 if self.video_path else "")
        path, _ = QFileDialog.getSaveFileName(
            self, "另存为", start,
            "SRT 字幕 (*.srt);;ASS 字幕，含当前样式 (*.ass);;所有文件 (*.*)")
        if not path:
            return
        self._write(path)

    def _write(self, path):
        # 首次覆盖别人给的文件时留一份 .bak —— 打轴是高风险编辑，
        # 「保存后才发现切错」很常见，有备份就能回退。
        try:
            if os.path.isfile(path) and not os.path.isfile(path + ".bak"):
                with open(path, "rb") as src, open(path + ".bak", "wb") as dst:
                    dst.write(src.read())
        except OSError:
            pass
        try:
            if os.path.splitext(path)[1].lower() in (".ass", ".ssa"):
                # 源文件是 ASS/SSA：按面板样式写出 ASS——本页的 dump 只会
                # SRT，把 SRT 文本灌进 .ass 文件播放器直接读不出来
                cues = sorted(self.doc.cues,
                              key=lambda c: (int(c.start), int(c.end)))
                text = secore.render_ass(cues, self._preview_style)
                with open(path, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(text)
                self.doc.path = path
            else:
                self.doc.save_file(path)
        except OSError as e:
            self._info("err", "保存失败", str(e)[:250])
            return
        self.sub_path = path
        self.dirty = False
        self._info("ok", "已保存", path)
        self._refresh_status()

    def _bak_once(self, path):
        """导出/保存覆盖已存在文件前留一份 .bak（与 _write 同一习惯）。"""
        try:
            if os.path.isfile(path) and not os.path.isfile(path + ".bak"):
                with open(path, "rb") as src, open(path + ".bak", "wb") as dst:
                    dst.write(src.read())
        except OSError:
            pass

    # ---------------------------------------------------------
    # 导出（属性面板右上角「导出」按钮）
    # ---------------------------------------------------------
    def export_subtitle(self):
        """把当前字幕导出成文件，**不改变**当前打开的文件关联。

        与「另存为」的区别：另存为之后编辑的就是新文件（改 sub_path、
        清 dirty）；导出只是"把现在这份（含未保存改动）扔一份出去"，
        原文件关联、未保存标记都原样保留。

        两种格式：
          · SRT —— 纯文本，CRLF + 按原 BOM 习惯（to_bytes）；样式带不走
            （SRT 格式本身没有样式位）。
          · ASS —— 用 `render_ass` 连同面板这套样式字典一起写出，画面上
            预览长什么样、导出的 ASS 播出来就是什么样（含拖出来的
            \\an7\\pos 自由位置）。条目按时间轴排序，空文本条目跳过。

        ⚠️ `render_ass` 的 PlayRes 固定 1920x1080（libass 按容器等比缩放），
        与实际视频分辨率无关；这是预览层的同一套约定，不必按视频改。
        """
        if not self.doc.cues:
            self._info("warn", "没有内容", "当前没有可导出的字幕")
            return
        start = self.doc.path or (os.path.splitext(self.video_path)[0]
                                  if self.video_path else "")
        path, _ = QFileDialog.getSaveFileName(
            self, "导出字幕", start,
            "SRT 字幕 (*.srt);;ASS 字幕，含当前样式 (*.ass);;所有文件 (*.*)")
        if not path:
            return
        if not os.path.splitext(path)[1]:
            path += ".srt"                      # 没写后缀就按 SRT 兜底
        ext = os.path.splitext(path)[1].lower()
        if ext not in (".srt", ".ass"):
            self._info("err", "不支持的格式",
                       "导出只支持 .srt / .ass（当前 %s）" % ext)
            return
        self._bak_once(path)
        # 按时间轴排好再写（与内嵌字幕同一约定；doc 本身的顺序不动）
        cues = sorted(self.doc.cues, key=lambda c: (int(c.start), int(c.end)))
        try:
            if ext == ".ass":
                text = secore.render_ass(cues, self._preview_style)
                with open(path, "w", encoding="utf-8", newline="\n") as fh:
                    fh.write(text)
            else:
                data = secore.SubtitleDoc(cues=list(cues)).to_bytes()
                with open(path, "wb") as fh:
                    fh.write(data)
        except OSError as e:
            self._info("err", "导出失败", str(e)[:250])
            return
        self._info("ok", "已导出 " + ext[1:].upper(), path, 6000)

    # ---------------------------------------------------------
    # 内嵌字幕（原引擎工作台「字幕视频合成」分段，v1.13.x 并到本页）
    # ---------------------------------------------------------
    def open_compose(self):
        """打开「内嵌字幕」对话框。

        用的是**内存里的 cues**（含未保存改动），所以不必先保存——
        这正是把它从引擎工作台搬过来的意义：那边只能吃磁盘上的文件。
        只把字幕挂成独立轨道，音视频 copy、不重新编码。
        """
        if not self.video_path:
            self._info("warn", "先打开视频",
                       "内嵌字幕需要一段视频；字幕用当前编辑的这份")
            return
        if not self.doc.cues:
            self._info("warn", "没有字幕", "先在波形上打轴，或用「插入」新建一条")
            return
        try:
            dlg = ComposeDialog(self, self)
        except Exception as e:  # noqa: BLE001
            self._info("err", "无法打开内嵌面板", str(e)[:200])
            return
        dlg.exec_()

    # ---------------------------------------------------------
    # 波形
    # ---------------------------------------------------------
    def _start_waveform(self, path):
        if self._wave_busy:
            self._wave_stop.set()
        try:
            self._media_tools()
        except RuntimeError as e:
            self._info("err", "无法生成波形", str(e), 6000)
            return
        self._wave_busy = True
        self._wave_stop = threading.Event()
        self.wave_bar.setValue(0)
        self.wave_bar.show()
        self.status.setText("正在解析音频波形…")

        def work():
            try:
                peaks, dur = self.wave_cache.get_or_build(
                    path,
                    on_progress=lambda p: self._wave_progress.emit(int(p)),
                    should_stop=self._wave_stop.is_set)
                if self._wave_stop.is_set():
                    return
                self._wave_ready.emit(peaks, dur)
            except Exception as e:  # noqa: BLE001
                self._wave_failed.emit("%s: %s" % (type(e).__name__, e))

        threading.Thread(target=work, name="vt-waveform", daemon=True).start()

    def _on_wave_progress(self, pct):
        try:
            self.wave_bar.setValue(max(0, min(100, int(pct))))
        except Exception:
            pass

    def _on_wave_ready(self, peaks, dur_sec):
        self._wave_busy = False
        self.wave_bar.hide()
        dur_ms = self.player.duration_ms or int(round(float(dur_sec or 0) * 1000))
        if self.doc.cues:
            dur_ms = max(dur_ms, max(c.end for c in self.doc.cues) + 1000)
        self.timeline.set_media(peaks, dur_ms, self.timeline.peaks_pps)
        self.timeline.set_cues(self.doc.cues)
        self.timeline.fit_all()
        self._refresh_status(
            "波形就绪（%d 个采样点）" % len(peaks) if peaks else "该媒体没有音频轨")

    def _on_wave_failed(self, msg):
        self._wave_busy = False
        self.wave_bar.hide()
        self._refresh_status("波形生成失败：" + msg[:120])

    # ---------------------------------------------------------
    # 播放
    # ---------------------------------------------------------
    def toggle_play(self):
        """空格 / 「播放」按钮：播放暂停。

        ⚠️ 没有视频时**绝不能**顺手弹「打开视频」的文件对话框：用户按空格的
        意图是"播放/暂停"，突然冒出一个占满屏幕的文件对话框，只会被理解成
        "程序全屏了"（用户反馈的"没放视频时按空格会全屏"就是这个）。
        改成一条不打断操作的 InfoBar 提示，顺带告诉他在哪儿打开视频。
        """
        if not self.video_path:
            self._info("warn", "还没有视频",
                       "先打开一段视频（Ctrl+O，或把文件拖进窗口），空格才是播放/暂停")
            return
        if not self._ensure_player():
            return
        self.player.toggle_play()

    def step_frames(self, n):
        if self._table_editing():
            self._forgive_key("Left" if n < 0 else "Right")
            return
        if not self._ensure_player():
            return
        self.player.step_frame(n)

    def nudge(self, delta_ms):
        if not self._ensure_player():
            return
        self.player.nudge_ms(delta_ms)

    def seek_ms(self, ms):
        # quiet：拖时间轴每次 mouseMove 都走到这里，没有视频属正常状态，
        # 静默降级为纯时间轴定位（面板跟着走）；弹窗交给低频动作路径
        if not self._ensure_player(quiet=True):
            self._sync_current(ms)      # 没有视频时也能用时间轴定位，面板照样跟着走
            return
        self.player.seek_ms(ms)

    def goto_cue(self, step):
        """上/下一条：选中并把播放头拉过去。"""
        if not self.doc.cues:
            return
        idx = self.timeline.selected
        if idx < 0:
            # 没选中时从"播放头最近的一条"起步，再按方向挪一格，
            # 这样首次按「下一条」不会看起来"没动"。
            idx = self.doc.nearest_index(self._pos_for_panel())
            idx = max(0, min(len(self.doc.cues) - 1, idx + int(step or 0)))
        else:
            idx = max(0, min(len(self.doc.cues) - 1, idx + step))
        self._select_cue(idx, seek=True)

    def _select_cue(self, idx, seek=False):
        if not (0 <= idx < len(self.doc.cues)):
            return
        self.timeline.set_selected(idx)
        self.table.select_row(idx)
        if seek:
            self.seek_ms(self.doc.cues[idx].start)

    def _on_speed(self, text):
        try:
            self.player.set_speed(float(text))
        except (TypeError, ValueError):
            pass

    def _on_position(self, ms):
        self.timeline.set_position(ms, follow=True)
        self._update_clock(ms)
        self._sync_current(ms)

    def _on_duration(self, ms):
        self._sync_duration()
        self._update_clock(self.player.position_ms)
        # 媒体刚就绪：字幕轨这时挂最稳（loadfile 之后字幕轨会被清空）
        self._push_preview(force=True)
        # 时长都解出来了，video-params 一定就绪——最后一次视频框贴合
        self._fit_video_frame()

    def _on_playing(self, playing):
        self.btn_play.setText("暂停" if playing else "播放")
        try:
            self.btn_play.setIcon(FIF.PAUSE_BOLD if playing else FIF.PLAY_SOLID)
        except Exception:
            pass

    def _update_clock(self, ms):
        total = self.player.duration_ms or self.timeline.duration_ms
        self.lbl_time.setText("%s / %s" % (secore.ms_to_clock(ms),
                                           secore.ms_to_clock(total)))

    # ---------------------------------------------------------
    # 画面字幕预览（cues -> ASS -> mpv 自渲染，不重新编码）
    # ---------------------------------------------------------
    # 为什么由 mpv 渲染而不是用 Qt 画一层浮层：播放器是**原生子窗口**
    # （`MPV(wid=hwnd)`），Windows 上 Qt 控件永远盖不到它上面，浮层会被画面
    # 整个吃掉。让 mpv 自己渲染（libass）反而更准——透明、贴合画面、
    # 逐帧精确，而且完全不需要重新编码。
    def _pos_for_panel(self):
        """面板跟随的时间点：有视频听播放器，没视频用时间轴自己的位置。"""
        return self.player.position_ms if self.video_path else self.timeline.position_ms

    def _mark_preview_dirty(self):
        """cues 内容变了：下次推位置时重建预览字幕，并强制面板重刷。"""
        self._ass_sig = None
        self._cur_index = -2

    def _push_preview(self, force=False):
        """把当前 cues + 样式推给**画面字幕层**（v1.13.2 起不再挂 mpv 字幕轨）。

        为什么改成 Qt 自绘：字幕要能被**点中、拖动、就地改字**，就必须是
        Qt 控件；而 mpv 是原生子窗口，Windows 上盖在它上面的普通 Qt 控件既
        画不出来也收不到鼠标。于是反转过来——预览交给 `SubtitleStage`
        （顶层透明窗口），mpv 只负责画面（`sid=no` 关掉它自己的字幕轨，
        免得内嵌字幕轨和我们叠成两层）。

        样式字典与 `render_ass` 共用同一份（font/size/color/outline/
        alignment/margin_*），所以画面上看到的就是导出成 ASS 时的样子。
        指纹没变就跳过，免得播放时每 40ms 无谓重绘。
        """
        if not self.doc.cues:
            self.stage.set_cues([])
            return
        sig = secore.cues_signature(self.doc.cues)
        if not force and sig == self._ass_sig:
            return
        self._ass_sig = sig
        self.stage.set_style(self._preview_style)
        self.stage.set_cues(self.doc.cues)

    def _sync_current(self, ms=None):
        """把属性面板 / 画面字幕层对齐到播放位置。"""
        ms = self._pos_for_panel() if ms is None else ms
        idx = self.doc.index_at(int(ms))
        if idx != self._cur_index:
            self._cur_index = idx
            self.props.set_cue(self.doc.cues[idx] if idx >= 0 else None,
                               idx, len(self.doc.cues))
        self.stage.set_position(int(ms))
        self.stage.set_selected(self.timeline.selected)
        self._push_preview()

    def _on_current_text(self, idx, text):
        if not (0 <= idx < len(self.doc.cues)):
            return
        cue = self.doc.cues[idx]
        new_text = (text or "").replace("\r\n", "\n")
        if new_text == cue.text:
            return
        self._push_undo("改文本")
        cue.text = new_text
        self._after_current_change(idx)

    def _on_current_time(self, idx, start_text, end_text):
        if not (0 <= idx < len(self.doc.cues)):
            return
        cue = self.doc.cues[idx]
        s = secore.clock_to_ms(start_text)
        e = secore.clock_to_ms(end_text)
        if s is None or e is None or (s == cue.start and e == cue.end):
            self._cur_index = -2          # 输入非法或没改动：把显示复原
            self._sync_current()
            return
        self._push_undo("改时间")
        secore.set_boundary(self.doc.cues, idx, "start", s)
        secore.set_boundary(self.doc.cues, idx, "end", e)
        self._after_current_change(idx)
        self._sync_duration()

    def _after_current_change(self, idx):
        """单条改动后的统一收尾：表格 / 时间轴 / 预览 / 状态栏一起刷新。"""
        if 0 <= idx < len(self.doc.cues):
            self.table.refresh_row(idx, self.doc.cues[idx])
        self.timeline.update()
        self._mark_preview_dirty()
        self._sync_current()
        self._refresh_status()

    def _on_style_changed(self, style):
        """预览样式变了：整份重建（参数只有十来个，重生成比增量改简单）。

        ⚠️ 自由位置的取舍（v1.14.2）：**位置类参数**变了才丢弃 pos_x/pos_y
        —— 那等于用户在用「对齐 / 边距」重新定位，属于"一次性调整"，得让
        新位置说了算；改字号、颜色、描边这类**非位置**参数则要保住已经拖
        好的自由位置，否则"拖好位置再改字号"会当场跳回对齐位置。
        """
        old = self._preview_style or {}
        style = style or {}
        new = dict(secore.ASS_DEFAULT_STYLE)
        new.update(style)
        if "pos_x" in style or "pos_y" in style:
            # 样式里**显式**带了 pos 键 = 面板「回到对齐位置」按钮按下了，
            # 清掉自由位置（值本来就是 None，这里只是把语义写明确）
            new["pos_x"], new["pos_y"] = style.get("pos_x"), style.get("pos_y")
        elif not any(new.get(k) != old.get(k) for k in self.POS_KEYS):
            # 非位置类调整（字号 / 颜色 / 描边…）：保住已拖好的自由位置
            new["pos_x"], new["pos_y"] = old.get("pos_x"), old.get("pos_y")
        # 否则：位置类参数变了（对齐九宫格 / 边距）→ 保持默认 None，
        # 于是新对齐立刻生效，自由位置作废 —— 这就是"一次性调整"。
        self._preview_style = new
        self._save_preview_style()
        self._ass_sig = None
        self._push_preview(force=True)
        self.props.set_style(self._props_view(self._preview_style))  # 面板读数同步

    # ---------------------------------------------------------
    # 预览样式的持久化
    # ---------------------------------------------------------
    # 字体 / 颜色 / 描边 / 对齐 / 边距既是**画面上的预览**，也是导出 ASS 时用的
    # 同一份参数，所以理应跟项目走、而不是每次启动重来。落一个小 json 到数据
    # 根目录即可；**绝不写回用户的 .srt**——样式从来不属于字幕文件。
    STYLE_FILE = "subtitle_style.json"

    #: 位置类样式键：改动它们 = 用户在用「对齐 / 边距」重新定位，
    #: 此时丢弃画面拖动产生的自由位置（见 _on_style_changed）
    POS_KEYS = ("alignment", "margin_v", "margin_l", "margin_r")

    def _style_path(self):
        return os.path.join(engine.DATA_DIR, self.STYLE_FILE)

    def _load_preview_style(self):
        """读回上次的样式；文件缺失/损坏就退回默认（不抛异常）。"""
        try:
            with open(self._style_path(), encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                # 只认当前版本认得的键：旧版残留字段不会把样式搞乱
                return {k: v for k, v in data.items()
                        if k in secore.ASS_DEFAULT_STYLE}
        except Exception:  # noqa: BLE001
            pass
        return {}

    def _save_preview_style(self):
        """原子落盘（先写 .part 再 replace），失败静默。"""
        try:
            path = self._style_path()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".part"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self._preview_style, fh, ensure_ascii=False, indent=1)
            os.replace(tmp, path)
        except Exception:  # noqa: BLE001
            pass

    # ---------------------------------------------------------
    # 撤销 / 重做
    # ---------------------------------------------------------
    def _push_undo(self, label, snapshot=None):
        self.undo.push(self.doc.cues, label, snapshot=snapshot)
        self.dirty = True

    def undo_edit(self):
        snap, label = self.undo.undo(self.doc.cues)
        if snap is None:
            self._refresh_status("没有可撤销的操作")
            return
        self.doc.restore(snap)
        self.dirty = True
        self._after_bulk_change()
        self._refresh_status("已撤销：" + (label or "操作"))

    def redo_edit(self):
        snap, label = self.undo.redo(self.doc.cues)
        if snap is None:
            self._refresh_status("没有可重做的操作")
            return
        self.doc.restore(snap)
        self.dirty = True
        self._after_bulk_change()
        self._refresh_status("已重做：" + (label or "操作"))

    def _after_bulk_change(self, keep_sel=None):
        """条数/顺序可能都变了，表格与时间轴整体重建。"""
        self.timeline.set_cues(self.doc.cues)
        self.table.load(self.doc.cues)
        if keep_sel is not None and 0 <= keep_sel < len(self.doc.cues):
            self._select_cue(keep_sel)
        else:
            self.timeline.set_selected(-1)
        self._sync_duration()
        self._refresh_status()
        self._mark_preview_dirty()
        self._sync_current()

    # ---------------------------------------------------------
    # 选中
    # ---------------------------------------------------------
    def _on_timeline_cue_selected(self, idx):
        # 时间轴上可能是多选（框选 / Ctrl 点选），表格要跟着整批同步
        idxs = self.timeline.selected_indices()
        if idxs:
            self.table.select_rows(idxs, scroll=(len(idxs) == 1))
        if not (0 <= idx < len(self.doc.cues)):
            return
        # 播放头不在该条内时跟过去——打轴时这一步能省掉大量拖动
        c = self.doc.cues[idx]
        pos = self.player.position_ms
        if not (c.start <= pos < c.end):
            self.seek_ms(c.start)

    def _on_table_selection(self, idx):
        self.timeline.set_selected(idx)

    def _on_drag_started(self):
        # 拖拽是「边改边看」，快照必须此刻先存下来，等真正动了再压栈
        self._pre_drag = self.doc.snapshot()
        self._drag_pushed = False

    def _on_cue_dragged(self, idx, mode, value):
        """拖动时间轴上的字幕块（高频路径，每帧都会来一次）。

        两处刻意省掉的动作：
          · 抽屉收起时（默认）不刷表格——看不见的东西没必要重排；
          · 状态栏按 120ms 节流——`_refresh_status` 里的 stats 会遍历全部
            cues，字幕几百条时每帧一次全表统计，是拖动卡顿的隐形大头。
        """
        if not self._drag_pushed and self._pre_drag is not None:
            self._push_undo("拖动时间", snapshot=self._pre_drag)
            self._drag_pushed = True
        if 0 <= idx < len(self.doc.cues):
            if self.table_shell.isVisible():
                self.table.refresh_row(idx, self.doc.cues[idx])
            self._status_throttled()

    def _status_throttled(self, interval_ms=120):
        """高频路径上的状态栏刷新节流（统计要遍历全部 cues，不便宜）。"""
        now = time.time() * 1000.0
        if now - getattr(self, "_status_t", 0.0) < interval_ms:
            return
        self._status_t = now
        self._refresh_status()

    def _on_drag_finished(self):
        self._pre_drag = None
        self._drag_pushed = False
        self._status_t = 0.0          # 让收尾那次刷新不被节流吞掉
        # 多选批量平移（全选后拖一条，全部选中条一起动）：拖动中为省性能
        # 只刷被拖的那一行，松手把其余选中行的时间列一并刷掉
        rows = self.timeline.selected_indices()
        if len(rows) > 1 and self.table_shell.isVisible():
            for r in rows:
                if 0 <= r < len(self.doc.cues):
                    self.table.refresh_row(r, self.doc.cues[r])
        self._refresh_status()
        self._sync_duration()
        # 拖拽是高频路径：过程中不重建预览字幕，松手后统一来一次
        self._mark_preview_dirty()
        self._sync_current()

    def _on_split_requested(self, ms):
        self.split_at(ms)

    def _on_cell_committed(self, row, col, text):
        if not (0 <= row < len(self.doc.cues)):
            return
        c = self.doc.cues[row]
        if col == 1:
            ms = secore.clock_to_ms(text)
            if ms is None:
                self.table.refresh_row(row, c)
                return
            self._push_undo("改起点")
            secore.set_boundary(self.doc.cues, row, "start", ms)
        elif col == 2:
            ms = secore.clock_to_ms(text)
            if ms is None:
                self.table.refresh_row(row, c)
                return
            self._push_undo("改终点")
            secore.set_boundary(self.doc.cues, row, "end", ms)
        elif col == 4:
            new_text = text.replace(self.NL_SEP, "\n")
            if new_text == c.text:
                return
            self._push_undo("改文本")
            c.text = new_text
        else:
            return
        self.table.refresh_row(row, c)
        self.timeline.update()
        self._sync_duration()
        self._refresh_status()
        self._mark_preview_dirty()
        self._sync_current()

    # ---------------------------------------------------------
    # 编辑操作
    # ---------------------------------------------------------
    def _target_index(self):
        """当前要作用的那一条：优先表格多选里的第一条，其次时间轴选中。"""
        rows = self.table.selected_rows()
        if rows:
            return rows[0]
        idxs = self.timeline.selected_indices()
        return idxs[0] if idxs else -1

    def _selected_indices(self):
        """当前选中的全部下标（表格多选优先，其次时间轴多选）。"""
        rows = self.table.selected_rows()
        if rows:
            return rows
        return self.timeline.selected_indices()

    def select_all_cues(self):
        """Ctrl+A：全选字幕（表格抽屉展开时一并同步）。"""
        w = QApplication.focusWidget()
        if w is not None and w.metaObject().className() in (
                "QLineEdit", "QTextEdit", "QPlainTextEdit", "QSpinBox",
                "QDoubleSpinBox", "QAbstractSpinBox", "QComboBox"):
            self._forgive_key("Ctrl+A")      # 焦点在输入框 → 交还"全选文本"
            return
        if not self.doc.cues:
            self._refresh_status("还没有字幕")
            return
        all_idx = range(len(self.doc.cues))
        self.timeline.set_selection(all_idx)
        self.table.select_rows(all_idx, scroll=False)
        # 画面层的选中框是**单条**语义：全选后继续亮着旧的一条会显得
        # "那条被单独锁定、全选对画面无效"——清掉它
        self.stage.set_selected(-1)
        self._refresh_status("已全选 %d 条" % len(self.doc.cues))

    def split_at_playhead(self):
        pos = self.player.position_ms
        if not self.video_path:
            pos = self.timeline.position_ms
        self.split_at(pos)

    def split_at(self, ms):
        idx = self.doc.index_at(ms)
        if idx < 0:
            idx = self._target_index()
        if idx < 0:
            self._refresh_status("没有可切分的条目")
            return
        self._push_undo("切分")
        if not secore.split_cue(self.doc.cues, idx, ms):
            self.undo.undo(self.doc.cues)      # 落不下去就把刚才的快照撤回来
            self._refresh_status("切分位置太靠近边界（每条至少保留 %.0fms）"
                                 % secore.MIN_DURATION_MS)
            return
        self._after_bulk_change(keep_sel=idx + 1)

    def merge_selected(self):
        rows = self.table.selected_rows()
        if len(rows) < 2:
            self._refresh_status("合并需要选中至少两条")
            return
        self._push_undo("合并")
        new_idx = secore.merge_cues(self.doc.cues, rows)
        self._after_bulk_change(keep_sel=new_idx)

    def delete_selected(self):
        rows = self._selected_indices()
        if not rows:
            self._refresh_status("没有选中的条目")
            return
        self._push_undo("删除")
        secore.delete_cues(self.doc.cues, rows)
        self._after_bulk_change(keep_sel=min(rows))
        self._refresh_status("已删除 %d 条（Ctrl+Z 可撤销）" % len(rows))

    def insert_at_playhead(self):
        pos = self.player.position_ms if self.video_path else self.timeline.position_ms
        self._push_undo("插入")
        idx = secore.insert_cue(self.doc.cues, pos, 1500, "")
        self._after_bulk_change(keep_sel=idx)
        self.table.editItem(self.table.item(idx, 4))

    def set_start_here(self):
        self._set_boundary_here("start")

    def set_end_here(self):
        self._set_boundary_here("end")

    def _set_boundary_here(self, which):
        idx = self._target_index()
        if idx < 0:
            self._refresh_status("先选中一条字幕")
            return
        pos = self.player.position_ms if self.video_path else self.timeline.position_ms
        self._push_undo("取起点" if which == "start" else "取终点")
        ok = secore.set_boundary(self.doc.cues, idx, which, pos)
        if not ok:
            self.undo.undo(self.doc.cues)
            self._refresh_status("该时间点无法作为边界（会把条目压得过短）")
            return
        self.table.refresh_row(idx, self.doc.cues[idx])
        self.timeline.update()
        self._refresh_status()

    def shift_selected(self, delta_ms):
        rows = self._selected_indices()
        if not rows:
            self._refresh_status("先选中要平移的条目")
            return
        self._push_undo("平移选中的条目")
        moved = secore.shift_cues(self.doc.cues, rows, delta_ms)
        self._after_bulk_change(keep_sel=min(rows))
        self._refresh_status("已平移 %+dms" % moved)

    def shift_all(self, delta_ms):
        if not self.doc.cues:
            return
        self._push_undo("整轨平移")
        moved = secore.shift_all(self.doc.cues, delta_ms)
        self._after_bulk_change()
        self._refresh_status("整轨平移 %+dms" % moved)

    def fix_overlaps(self):
        self._push_undo("消除重叠")
        n = secore.fix_overlaps(self.doc.cues)
        if not n:
            self.undo.undo(self.doc.cues)
            self._refresh_status("没有相邻重叠")
            return
        self._after_bulk_change()
        self._refresh_status("已修正 %d 处重叠" % n)

    def clamp_zero(self):
        self._push_undo("修正零长条目")
        n = secore.clamp_zero_length(self.doc.cues)
        if not n:
            self.undo.undo(self.doc.cues)
            self._refresh_status("没有零长/倒挂的条目")
            return
        self._after_bulk_change()
        self._refresh_status("已修正 %d 条" % n)

    def renumber(self):
        self._push_undo("重新排序")
        secore.renumber(self.doc.cues)
        self._after_bulk_change()

    def fit_selected(self):
        """把视图缩放到选中条目所在区间（找不到选中就整轨）。"""
        rows = self._selected_indices()
        tw = max(200, self.timeline.width())
        if rows:
            c0 = self.doc.cues[rows[0]]
            c1 = self.doc.cues[rows[-1]]
            span = max(1000, c1.end - c0.start)
            self.timeline.pixels_per_second = max(
                4.0, min(4000.0, tw * 1000.0 / span * 0.9))
            self.timeline.view_start_ms = max(0, int(c0.start - span * 0.05))
            self.timeline.update()
        else:
            self.timeline.fit_all()

    # ---------------------------------------------------------
    # 状态栏
    # ---------------------------------------------------------
    def _refresh_status(self, extra=""):
        st = secore.stats(self.doc.cues)
        parts = []
        parts.append("视频：" + (os.path.basename(self.video_path) if self.video_path
                                else "未打开"))
        parts.append("字幕：" + (os.path.basename(self.sub_path) if self.sub_path
                                else "未保存"))
        parts.append("%d 条 / %d 字" % (st["count"], st["chars"]))
        if st["overlaps"]:
            parts.append("重叠 %d" % st["overlaps"])
        if st["zero"]:
            parts.append("过短 %d" % st["zero"])
        parts.append("编码 %s/%s" % (self.doc.src_encoding,
                                    "CRLF" if self.doc.newline == "\r\n" else "LF"))
        parts.append("缩放 %.0fpx/s" % self.timeline.pixels_per_second)
        if self.dirty:
            parts.append("● 未保存")
        if extra:
            parts.append(extra)
        try:
            self.status.setText("　|　".join(parts))
        except Exception:
            pass


# ========== 主窗口 ==========
# v1.13.x：页面合并后共 5 个导航页（音画合并并入视频处理、字幕校准并入字幕处理）。
# 内嵌子板块仍有自己的 objectName（MergePage / CalibPage），保留映射便于标题定位。
# 类名/objectName 一律保持 DownloadPage 不变，避免牵动既有样式与自检。
PAGE_TITLES = {"DownloadPage": "视频处理", "LibraryPage": "视频库",
               "SubtitlePage": "字幕处理", "SubtitleEditPage": "字幕编辑",
               "SettingsPage": "设置",
               "MergePage": "音画合并", "CalibPage": "字幕校准"}

#: 黄金比例（宽 : 高）。窗口默认尺寸与「按屏幕收敛」后的尺寸都按它算——
#: 比 1.38 的默认值更接近主流视频区（16:10 / 16:9）留白后的观感。
GOLDEN_RATIO = 1.6180339887

#: 无边框窗口的**边缘拖拽热区**（逻辑像素）。
#: 库默认用的是 BORDER_WIDTH 物理像素（5px），在 125%/150% 缩放下只剩 3~4 个
#: 逻辑像素，鼠标几乎点不中——用户反馈的「无法用鼠标调整窗口大小」即此。
#: 这里按设备像素比换算出一个宽容热区，四边/四角都能拖。
RESIZE_MARGIN = 8


class _ResizeHitFilter(QAbstractNativeEventFilter):
    """**应用级** WM_NCHITTEST 过滤器 —— 让「边框拖拽缩放」真正生效。

    为什么不能只在 `MainWindow.nativeEvent` 里做（v1.13.6 的关键修正）：
    mpv 通过 `wid` 嵌进 `video_host` 时会调用 `winId()`，Qt 随之把导航条 /
    标题栏 / 页面这些 widget 一并**提升成原生子窗口**。实测载入视频后多出
    二十多个 `Qt5152QWindowIcon` 子窗口，它们从窗口最边缘铺开，正好盖住
    `RESIZE_MARGIN` 那 8 逻辑像素的边框带。于是鼠标点在边框上时，
    WM_NCHITTEST 是发给**子窗口**的 —— `MainWindow.nativeEvent` 根本收不到，
    子窗口回 HTCLIENT，系统就不发起缩放。

    实测（`_workspace/probes/_diag_hittest3.py`，同一台机器同一份代码）：
        · 未载入视频：边框带上的点归属主窗口自己 -> 回 HTLEFT，能拖；
        · 载入视频后：归属某个原生子窗口      -> 子窗口回 HTCLIENT，拖不动；
        · 卸载视频后：那些子窗口还在（原生窗口一旦创建就不会撤销）
                      -> 依然拖不动。
    这正是用户反馈的「放入视频后无法调整窗口大小，视频没了也一样」。

    所以这里在应用级接住**所有** WM_NCHITTEST（含子窗口的消息），只按屏幕
    坐标判断该点是否落在主窗口的边框带上：
      · 只处理属于本窗口的消息（`GetAncestor(..., GA_ROOT)` 比对句柄），
        其它窗口与对话框原样放行；
      · 不在边缘时返回 False，交给 Qt 照常处理（按钮、拖拽、双击标题栏等
        都不受影响）。
    """

    def __init__(self, window):
        super().__init__()
        self._window = window

    def nativeEventFilter(self, eventType, message):
        try:
            if eventType not in (b"windows_generic_MSG",
                                 b"windows_dispatcher_MSG"):
                return False, 0
            win = self._window
            if win is None or not win.isVisible():
                return False, 0
            if not getattr(win, "_isResizeEnabled", True):
                return False, 0
            if win.isMaximized() or win.isFullScreen():
                return False, 0

            import ctypes
            from ctypes.wintypes import MSG
            import win32con
            import win32gui

            msg = MSG.from_address(int(message))
            if msg.message != win32con.WM_NCHITTEST:
                return False, 0
            hwnd = int(win.winId())
            if win32gui.GetAncestor(msg.hWnd, win32con.GA_ROOT) != hwnd:
                return False, 0
            rect = win32gui.GetWindowRect(hwnd)
            w, h = rect[2] - rect[0], rect[3] - rect[1]
            dpr = float(win.devicePixelRatioF() or 1.0)
            bw = max(5, int(round(RESIZE_MARGIN * dpr)))
            # 窗口本身就比热区大不了多少时不做命中，免得整窗都成了"边缘"
            if w <= bw * 4 or h <= bw * 4:
                return False, 0
            # lParam 是**屏幕物理坐标**（低 16 位 x、高 16 位 y）。
            # 这里不用 GetCursorPos()：它给的是"此刻"的鼠标位置，与消息
            # 携带的坐标在系统连发命中测试时并不一致。
            sx = ctypes.c_short(msg.lParam & 0xFFFF).value
            sy = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
            left = sx < rect[0] + bw
            right = sx > rect[2] - bw
            top = sy < rect[1] + bw
            bottom = sy > rect[3] - bw
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
            if hit is None:
                return False, 0
            # ⚠️ 关键中的关键：这条消息可能是发给**子窗口**的（载入视频后 Qt 把
            #    导航条 / 标题栏 / 页面提升成了原生子窗口）。把 NCHITTEST 改成
            #    HTLEFT 只能骗到**光标**（变成双向箭头），真正按下时
            #    WM_NCLBUTTONDOWN 还是落到那个子窗口上，系统不会进入缩放循环 ——
            #    用户看到的就是「光标对了，但拖不动，大小不变」。
            #    回 HTTRANSPARENT 才是正解：告诉系统"这个点当作透明"，系统会
            #    继续在**同一线程**里往下找窗口，最终由主窗口接手，于是
            #    NCLBUTTONDOWN / SIZING / SIZE 全都走主窗口，缩放才真能进行。
            if msg.hWnd != hwnd:
                return True, win32con.HTTRANSPARENT
            return True, hit
        except Exception:  # noqa: BLE001
            # 任何意外都退回 Qt 的默认处理，绝不因为命中测试把程序搞崩
            return False, 0


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
    """

    #: 导航项文案（宽度按其中最长的一项计算）
    #: v1.13.x：原「视频下载」更名「视频处理」——该页已同时承载「视频下载」与
    #: 「音画合并」两个板块，只叫"下载"名不副实。页内子板块名保持不变。
    NAV_TEXTS = ["视频处理", "视频库", "字幕处理", "字幕编辑", "流水线", "设置"]

    #: 默认窗口宽度（高度由黄金比例推）。 以它为上界，
    #: 而不是以"窗口当前宽度"为上界——后者会把布局撑出来的尺寸固化下来。
    DEFAULT_WIDTH = 1180

    def __init__(self, argv=None):
        # 跨屏拖拽状态必须在 super().__init__() 之前建立：窗口构造过程中
        # Qt 就会派发 moveEvent，届时 moveEvent 会读这些属性
        self._last_screen = None
        self._last_screen_geo = None
        self._drag_anchor = None      # (相对屏宽的左/右比例) 用于跨屏重定位
        self._last_dpr = None         # 上次所在屏的设备像素比（跨屏后要对比）
        self._settle_pending = False  # 跨屏收敛是否已排队（防抖，只跑一轮）
        self._settle_tries = 0        # 拖拽中延后收敛的重试次数（有上限）
        super().__init__()
        self.q = queue.Queue()
        self.setWindowTitle(f"视频工具箱 v{VERSION}")
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

        self.download_page = DownloadPage(self, self)
        self.library_page = LibraryPage(self, self)
        self.subtitle_page = SubtitlePage(self, self)
        self.subtitle_edit_page = SubtitleEditPage(self, self)
        self.pipeline_page = PipelinePage(self, self)
        self.settings_page = SettingsPage(self, self)
        # 被合并的子板块：仍挂到宿主页的堆叠里，保留快捷引用便于消息路由/自检
        self.merge_page = self.download_page.merge_page
        self.calib_page = self.subtitle_page.calib_page
        for page in (self.download_page, self.library_page, self.subtitle_page,
                     self.subtitle_edit_page, self.pipeline_page,
                     self.settings_page):
            page.installEventFilter(self)

        self.addSubInterface(self.download_page, FIF.DOWNLOAD, "视频处理")
        self.addSubInterface(self.library_page, FIF.VIDEO, "视频库")
        self.navigationInterface.addSeparator()
        self.addSubInterface(self.subtitle_page, FIF.FONT, "字幕处理")
        self.addSubInterface(self.subtitle_edit_page, FIF.CUT, "字幕编辑")
        self.addSubInterface(self.pipeline_page, FIF.SYNC, "流水线")
        self.addSubInterface(self.settings_page, FIF.SETTING, "设置",
                             position=NavigationItemPosition.BOTTOM)

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
        # 首帧后 + 字体度量就绪后再各收敛一次：任何时刻导航宽度都是
        # 「最长项文字 + 2 个字符」，不会出现「启动时一个宽度、稍后另一个宽度」
        QTimer.singleShot(0, self._apply_nav_width)
        QTimer.singleShot(400, self._apply_nav_width)

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

        self.switchTo(self.download_page)
        self._apply_argv(argv or [])
        QTimer.singleShot(400, self.library_page.auto_load)
        QTimer.singleShot(120, self._pump)
        # 流水线：延后启动，避开首屏与字幕引擎预热（v1.14.0）
        self.pipeline_registry = None
        self.pipeline = None
        QTimer.singleShot(2500, self._start_pipeline)
        # 字幕引擎界面后台预热：主窗口首帧之后立刻开始导入依赖（预热本身只起
        # 一个后台线程，不占主线程），导入完成即回主线程建界面，用户真正点进
        # 「字幕处理」时通常已是现成控件。v1.11.0 起由 900ms 提前到首帧后立即，
        # 配合 diskcache 延迟化，最坏情况下（刚启动就点进去）的等待已降到亚秒级。
        QTimer.singleShot(0, self.subtitle_page.prewarm)
        # 主屏 DPI 变化（改缩放比/换主屏）时重新计算导航宽度。
        # 注意必须用 QApplication 实例的信号：PyQt5 里类的同名属性是未绑定的
        # pyqtSignal 描述符，直接 .connect 会抛 AttributeError。
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
            try:
                page.updateGeometry()
                for sub in (getattr(page, "dl_tab", None),
                            getattr(page, "work_tab", None)):
                    if sub is not None:
                        sub.updateGeometry()
                for area in page.findChildren(QWidget):
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
        w = min(self.DEFAULT_WIDTH, max_w)
        h = int(round(w / GOLDEN_RATIO))
        if h > max_h:
            h = max_h
            w = int(round(h * GOLDEN_RATIO))
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

    def switchTo(self, page):
        # 切页时布局会按新页面的 sizeHint 把窗口撑大（实测 1180x729 → 1440x889），
        # 而用户并没有要求变大 —— 撑大后窗口可能超出屏幕，边缘够不着鼠标。
        # 记下切页前的尺寸，切页后若被撑大就还原回去（用户自己拖大的尺寸不会丢）。
        before = self.size()
        self.stackedWidget.setCurrentWidget(page, popOut=False)
        self.setWindowTitle(
            f"视频工具箱 v{VERSION} — {PAGE_TITLES.get(page.objectName(), '')}")

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
        return {"download": self.download_page, "library": self.library_page,
                "subtitle": self.subtitle_page, "edit": self.subtitle_edit_page,
                "pipeline": self.pipeline_page,
                "settings": self.settings_page}.get(key)

    # ---------- 流水线（v1.14.0） ----------
    def _start_pipeline(self):
        """延迟启动目录感知 + 流水线（不拖慢首屏）。

        registry 监视「上次使用的下载目录 + data\\downloads」，变更事件接给
        VT_NO_PIPELINE=1 可完全关闭目录感知（自检/排障用）。
        """
        if os.environ.get("VT_NO_PIPELINE"):
            return
        try:
            reg = mreg.MediaRegistry(use_watcher=True)
            pipe = pl.Pipeline(reg, log=lambda m: self.q.put(("pipe_log", str(m))))
            pipe.add_listener(lambda p: self.q.put(("pipe_state", p)))
            reg.add_listener(pipe.on_files_changed)
            reg.add_exclude(pipe.out_root)      # 成品目录不回头再被索引
            reg.start()
            self.pipeline_registry = reg
            self.pipeline = pipe
            self.pipeline_page.attach(pipe)
            pipe.manual_evaluate()              # 启动即补一次评估
        except Exception:  # noqa: BLE001 - 流水线起不来绝不能影响主程序
            self._log_error(traceback.format_exc())

    def closeEvent(self, e):
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
        # 1) 目录 → 视频库
        if dirs:
            d = dirs[0]
            self.library_page.dir_edit.setText(d)
            self.library_page.refresh()
            self.switchTo(self.library_page)
            msgs.append(f"已把「{os.path.basename(d)}」设为视频库目录")
        # 2) 字幕/视频/音频 → 字幕编辑
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
            while True:
                msg = self.q.get_nowait()
                self._dispatch(msg)
        except queue.Empty:
            pass
        QTimer.singleShot(120, self._pump)

    def _dispatch(self, msg):
        kind, args = msg[0], msg[1:]
        dl, lib, mg = self.download_page, self.library_page, self.merge_page
        cal = self.calib_page
        try:
            if kind == "detect_done":
                dl.on_detect_done(*args)
            elif kind == "sys_log":
                dl.log.line(args[0], "dim")
            elif kind == "dl_progress":
                dl.on_dl_progress(args[0], args[1])
            elif kind == "dl_log":
                dl.on_dl_log(args[0], args[1])
            elif kind == "dl_done":
                dl.on_dl_done(args[0], args[1], args[2])
            elif kind == "lib_scan_done":
                lib.on_scan_done(args[0], args[1])
            elif kind == "lib_thumb":
                lib.on_thumb(args[0], args[1])
            elif kind == "lib_thumb_fail":
                lib.on_thumb_fail(args[0])
            elif kind == "lib_log":
                lib.on_log(args[0])
            elif kind == "scan_done":
                mg.on_scan_done(*args)
            elif kind == "mg_log":
                mg.log.line(args[0], "dim")
            elif kind == "mg_progress":
                mg.progress.setValue(int(args[0]))
            elif kind == "mg_done":
                mg.on_mg_done(args[0], args[1], args[2])
            elif kind == "cal_log":
                # (文本, 级别, 任务代号)：旧线程残留消息丢弃；有效消息刷新心跳
                if len(args) < 3 or args[2] == cal._gen:
                    cal._last_beat = time.time()
                    cal.log.line(args[0], args[1] if len(args) > 1 else "dim")
            elif kind == "cal_done":
                # (rc, out, result, 任务代号)
                cal.on_cal_done(*args)
            elif kind == "pipe_log":
                self.pipeline_page.log.line(args[0], "dim")
            elif kind == "pipe_state":
                self.pipeline_page.on_state(args[0])
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


def configure_qt_plugins():
    """显式指定 Qt 平台插件目录（必须在创建 QApplication 之前调用）。

    内置 PyQt5 不是用安装器装的，而是把 wheel 解包到 tools\\python 的
    site-packages —— Qt 按 sys.prefix 推算插件的默认逻辑在这种情况下找不到
    platforms/qwindows.dll，会直接报
    「no Qt platform plugin could be initialized」并弹模态框卡住进程。
    忽略平台插件目录的探测在打包后由 PyInstaller 的钩子负责（它会把
    platforms/qwindows.dll 一起打进包里），此时若强行指向内置运行时的
    PyQt5 反而可能因版本不一致而崩，故冻结模式下直接跳过。
    """
    if getattr(sys, "frozen", False):
        return ""
    for base in (engine.EMBEDDED_SITE_PACKAGES,
                 os.path.join(engine.TOOLS_DIR, "python", "Lib", "site-packages")):
        plugins = os.path.join(base, "PyQt5", "Qt5", "plugins")
        if os.path.isdir(plugins):
            os.environ.setdefault("QT_QPA_PLATFORM_PLUGIN_PATH", plugins)
            os.environ.setdefault("QT_PLUGIN_PATH", plugins)
            return plugins
    return ""


def main():
    # 运行期环境准备（v1.10.6）：必须在任何 videocaptioner 导入之前执行——
    # 1) 把字幕引擎在系统盘的历史数据迁移到数据根目录；
    # 2) 重定向引擎的路径常量（否则它会写 %LOCALAPPDATA%，即 C 盘）；
    # 3) 把临时目录指向数据根目录，避免中间产物落系统 Temp。
    engine.prepare_runtime_env()
    # 未捕获异常兜底：装上后 Qt 槽里的异常只记日志 + 提示，不会再让进程 abort
    install_crash_guard()
    # 启动即拉取最新校准知识并入本地（v1.10.7 多用户收敛的「拉」半程；
    # 后台 daemon 线程，失败静默记 logs/calib_sync.log）
    threading.Thread(target=engine.sync_calib_on_startup, daemon=True).start()
    configure_qt_plugins()
    # 矢量化：高分屏按逻辑像素缩放、图标/文字按矢量渲染，避免放大后发虚
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    # 缩放比不取整：125% / 150% 等非整数倍率下按实际比例换算，
    # 否则 Qt 会把 1.25 四舍五入成 1.0 或 2.0，不同显示器间表现不一致
    try:
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    except Exception:
        pass
    app = QApplication(sys.argv)
    # 单实例守卫（v1.13.4）：两个实例会各自持有一份内存配置并写穿同一个
    # data\ 目录（ui_custom.json / config.json…），表现为「设置过一会儿自动
    # 复原」「这边改了那边不生效」——正是多窗口交叠写入的典型症状。
    # QLockFile 在进程存活期间持有锁；崩溃残留的锁会按锁内 PID 校验存活后放行。
    _single_lock = QLockFile(os.path.join(engine.DATA_DIR,
                                          "videotoolbox.single.lock"))
    _single_lock.setStaleLockTime(0)
    if not _single_lock.tryLock(200):
        QMessageBox.information(
            None, "视频工具箱已在运行",
            "检测到另一个视频工具箱窗口正在运行，本次启动已取消。\n\n"
            "同时运行两个实例会互相覆盖配置（例如「界面美化」的设置会被"
            "另一边的旧值写回，看起来像\"自动复原\"）。\n\n"
            "请改用已打开的窗口；若找不到它，可先在任务管理器结束旧的"
            " python.exe 再启动。")
        return
    # 界面美化（v1.13.x）：主题档/主题色读自 data/ui_custom.json（设置页可改），
    # 全局 QSS（输入框/菜单/工具提示/滚动条/进度条）在这里一并挂上
    ui_theme.apply_startup_theme(app)
    app.setFont(QFont("Microsoft YaHei UI", 9))   # 9pt 紧凑正文，高分屏随缩放走
    window = MainWindow(sys.argv[1:])
    window.fit_to_screen()

    shot_tab = os.environ.get("VT_SHOT_TAB")
    if shot_tab:
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
    # 释放 libmpv：不释放的话进程退出后 onefile 的 _MEI*** 临时目录删不掉
    app.aboutToQuit.connect(window.subtitle_edit_page.shutdown)

    window.show()
    window.raise_()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
