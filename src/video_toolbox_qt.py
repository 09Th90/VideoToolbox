#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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
from datetime import datetime

from PyQt5.QtCore import Qt, QTimer, QEvent, QObject, QUrl, QPoint, QRect
from PyQt5.QtGui import (QColor, QDesktopServices, QFont, QFontMetrics,
                         QGuiApplication, QPixmap, QTextCursor)
from PyQt5.QtWidgets import (QAbstractItemView, QApplication, QDialog,
                             QFileDialog, QGridLayout, QHBoxLayout, QHeaderView,
                             QSizePolicy, QTableWidgetItem, QVBoxLayout, QWidget)

from qfluentwidgets import (BodyLabel, CardWidget, CaptionLabel,
                            ComboBox, FluentIcon as FIF,
                            FluentWindow, InfoBar, InfoBarPosition, LineEdit,
                            ListWidget, MessageBox, NavigationItemPosition,
                            PasswordLineEdit, PrimaryPushButton, ProgressBar,
                            PushButton, ScrollArea, SimpleCardWidget, SpinBox,
                            SubtitleLabel, StrongBodyLabel, SwitchButton,
                            TableWidget, TextEdit, Theme, TitleLabel,
                            setTheme, setThemeColor)
from qfluentwidgets.components.navigation.navigation_widget import NavigationWidget

import video_toolbox as engine

VERSION = "1.12.0"

LIB_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv", ".ts", ".m4v", ".webm"}
THUMB_DIR = engine.THUMB_CACHE_DIR
CARD_W, THUMB_W, THUMB_H = 232, 200, 118


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
    """日志卡片：等宽字体、按级别着色、自动滚动到底。"""

    COLORS = {"dim": "#8A8A8A", "ok": "#2E9E5B", "err": "#D64545", "info": "#B0B0B0"}

    def __init__(self, title="运行日志", height=150, parent=None):
        super().__init__(parent)
        self.text = TextEdit(self)
        self.text.setReadOnly(True)
        self.text.setMinimumHeight(height)
        # 固定深色底：qfluentwidgets 的 TextEdit 在深色主题下不会自动变色，
        # 默认白底放在深色卡片里非常突兀，这里统一成「控制台」配色
        self.text.setStyleSheet(
            "TextEdit{background:#1B1B1B;color:#D6D6D6;border:none;"
            "font-family:Consolas,'Microsoft YaHei UI';font-size:12px;}")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 14, 20, 18)
        lay.setSpacing(10)
        lay.addWidget(CaptionLabel(title, self))
        lay.addWidget(self.text)

    def line(self, msg, level="dim"):
        color = self.COLORS.get(level, self.COLORS["dim"])
        stamp = datetime.now().strftime("%H:%M:%S")
        self.text.setTextColor(QColor("#8A8A8A"))
        self.text.insertPlainText(f"{stamp}  ")
        self.text.setTextColor(QColor(color))
        self.text.insertPlainText(str(msg) + "\n")
        self.text.setTextColor(QColor("#D0D0D0"))
        self.text.moveCursor(QTextCursor.End)
        self.text.ensureCursorVisible()

    def clear(self):
        self.text.clear()


def card(title=None, caption=None):
    """新建一张卡片，返回 (卡片, 其内部竖向布局)。

    卡片会被放进滚动区，说明文字不自动换行（避免 heightForWidth 与滚动区
    互相触发重排）；文案一律保持一行能放下的长度。
    """
    box = CardWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(14, 12, 14, 14)
    lay.setSpacing(8)
    if title:
        lay.addWidget(StrongBodyLabel(title, box))
    if caption:
        lay.addWidget(fit_caption(CaptionLabel(caption, box)))
    return box, lay


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


def expand_h(widget, minimum=360):
    """让输入框横向自适应填满所在行（长 URL/路径不被截断）。"""
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
        if subtitle:
            cap = CaptionLabel(subtitle, self)
            cap.setWordWrap(True)
            outer.addWidget(cap)

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


# ========== 视频下载 ==========
class DownloadPage(QWidget):
    """单个链接反复添加；每个下载任务独立线程，互不阻塞。"""

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
        self.shell = ScrollPage("视频下载",
                                "检测一个链接后即可加入并行下载；每个视频自动打包成独立文件夹"
                                "（视频 + 封面.jpg + 视频信息.txt）", self, scrollable=True)
        outer.addWidget(self.shell)
        self.vbox = self.shell.content_lay

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
            opts = ["-f", f"{fid}+ba/b", "--merge-output-format", "mp4",
                    "--ffmpeg-location", os.path.dirname(ffmpeg_path),
                    "--newline", "--no-playlist",
                    "--write-thumbnail", "--convert-thumbnails", "jpg",
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

    def _fetch_subtitles(self, task_id, ytdlp, url, folder, info_json_path, meta=None):
        """视频下载完成后单独拉字幕；失败只写日志，不影响任务成功状态。"""
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
        opts = ["--skip-download", "--newline", "--no-playlist",
                "--socket-timeout", "15", "--retries", "2",
                "--write-subs", "--write-auto-subs", "--sub-langs", sub_langs,
                "--sub-format", "srt/best", "--convert-subs", "srt",
                "-o", engine.output_template(folder)]
        rc = 1
        if info_json_path and os.path.isfile(info_json_path):
            rc, _ = self._run_ytdlp([ytdlp, "--load-info-json", info_json_path, *opts], task_id)
        if rc != 0:
            with DownloadPage._EXTRACT_LOCK:
                rc, _ = self._run_ytdlp([ytdlp, *opts, url], task_id)
        try:
            has_srt = any(n.lower().endswith(".srt") for n in os.listdir(folder))
        except OSError:
            has_srt = False
        if has_srt:
            self.app.q.put(("dl_log", task_id, "[字幕] 已下载到本视频文件夹（.srt）"))
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
            self._reflow()
        return super().eventFilter(obj, event)

    def _clear_cards(self):
        for c in self.cards.values():
            c["box"].setParent(None)
            c["box"].deleteLater()
        self.cards.clear()
        self._pixmaps.clear()

    def _make_card(self, v):
        if v["path"] in self.cards:
            return
        box = SimpleCardWidget(self.holder)
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

    def _reflow(self):
        if not self.cards:
            return
        width = max(self.area.viewport().width(), CARD_W + 8)
        cols = max(1, width // (CARD_W + 12))
        if cols == self._cols and self.grid.count() == len(self.cards):
            return
        self._cols = cols
        while self.grid.count():
            self.grid.takeAt(0)
        for i, c in enumerate(self.cards.values()):
            self.grid.addWidget(c["box"], i // cols, i % cols)
        self.grid.setRowStretch(self.grid.rowCount(), 1)


# ========== 音视频合并 ==========
class MergePage(QWidget):
    ASS_MODES = {"烧录为硬字幕": "burn", "封装为 MKV": "mkv", "忽略": "ignore"}

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setObjectName("MergePage")
        self.pairs = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.shell = ScrollPage("音视频智能合并",
                                "自动配对 mp4 + m4a/weba + srt/ass；m4a 直封，weba 转 AAC",
                                self, scrollable=True)
        outer.addWidget(self.shell)
        self.vbox = self.shell.content_lay

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
        self.shell = ScrollPage("字幕处理",
                                "语音转录 · 字幕优化 · 翻译 · 配音 · 合成，一站式内嵌完成",
                                self, scrollable=False)
        outer.addWidget(self.shell)
        # 本页以引擎界面为主体：收紧页边距，把空间让给引擎工作台
        self.shell.layout().setContentsMargins(20, 12, 20, 12)
        self.shell.layout().setSpacing(8)
        self.vbox = self.shell.content_lay
        self.vbox.setContentsMargins(0, 0, 0, 0)
        self.vbox.setSpacing(8)

        # 中部：引擎界面宿主；底部一行：引擎状态 + 设置/许可入口
        # （第三方组件的许可与来源见 docs\ 声明文件）
        self.host = QWidget(self)
        self.host_lay = QVBoxLayout(self.host)
        self.host_lay.setContentsMargins(0, 0, 0, 0)
        self.vbox.addWidget(self.host, 1)

        foot = QWidget(self)
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
        tc = getattr(home, "task_creation_interface", None)
        if tc is not None:
            for attr in ("info_label", "donate_button"):
                w = getattr(tc, attr, None)
                if w is not None:
                    w.hide()
        return home

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
        blay.addWidget(label_row("下载目录", row(self.dir_edit, browse, None)))

        root, is_default, src = engine.data_root_info()
        self.data_edit = LineEdit(box)
        self.data_edit.setText(root)
        self.data_edit.setPlaceholderText("留空使用程序目录")
        apply_btn = PushButton(FIF.SAVE, "应用", box)
        apply_btn.clicked.connect(self._apply_data_root)
        reset_btn = PushButton(FIF.SYNC, "还原默认", box)
        reset_btn.clicked.connect(self._reset_data_root)
        blay.addWidget(label_row("数据根目录",
                                 row(self.data_edit, apply_btn, reset_btn)))
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
        blay.addWidget(label_row("引擎工作目录", self.engine_dir_edit))

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
            "内置 mihomo 代理仅用于 GitHub 加速（依赖下载、校准知识同步）；"
            "可接入自己的 Clash/mihomo 配置，按你的节点与端口启动")
        cur = engine.get_proxy_yaml()
        self.proxy_edit = LineEdit(box)
        self.proxy_edit.setPlaceholderText(
            "留空使用内置 GitHub 专用配置（tools/mihomo/config.yaml，端口 7897）")
        self.proxy_edit.setText(cur)
        self.proxy_edit.setReadOnly(True)
        browse = PushButton(FIF.FOLDER, "选择 yaml…", box)
        browse.clicked.connect(self._browse_proxy_yaml)
        reset = PushButton(FIF.SYNC, "恢复内置", box)
        reset.clicked.connect(self._reset_proxy_yaml)
        blay.addWidget(label_row("代理配置文件",
                                 row(self.proxy_edit, browse, reset)))
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
            return (f"当前：自定义配置，端口 {port or 7897}。程序按配置里的 "
                    f"mixed-port / port / socks-port 自动识别端口，"
                    f"端口已被占用（如你的 Clash 正在运行）时直接复用。"
                    f"修改后重启程序生效。")
        return ("支持 Clash / mihomo 格式；程序按配置里的 mixed-port / port / "
                "socks-port 自动识别端口，端口已被占用（如你的 Clash 正在运行）"
                "时直接复用。修改后重启程序生效。")

    def _browse_proxy_yaml(self):
        p, _ = QFileDialog.getOpenFileName(
            self, "选择 Clash/mihomo 配置", engine.APP_DIR,
            "Clash 配置 (*.yaml *.yml)")
        if not p:
            return
        if engine._proxy_yaml_port(p) is None:
            InfoBar.warning(
                "未能识别端口", "配置里没有 mixed-port / port / socks-port，"
                "将回退使用默认端口 7897", duration=4000, parent=self)
        try:
            engine.set_proxy_yaml(p)
        except (OSError, ValueError) as e:
            InfoBar.error("保存失败", str(e), duration=4000, parent=self)
            return
        self.proxy_edit.setText(p)
        self.proxy_hint.setText(self._proxy_hint_text())
        InfoBar.success("已保存", "自定义代理配置已生效，重启程序后应用",
                        duration=INFOBAR_DURATION_SUCCESS, parent=self)

    def _reset_proxy_yaml(self):
        try:
            engine.set_proxy_yaml("")
        except (OSError, ValueError):
            pass
        self.proxy_edit.setText("")
        self.proxy_hint.setText(self._proxy_hint_text())
        InfoBar.success("已恢复", "将使用内置 GitHub 专用代理配置，重启程序后生效",
                        duration=INFOBAR_DURATION_SUCCESS, parent=self)

    # ------------------------------------------------------------------ #
    # 全局 AI（LLM）：全程序唯一一套配置
    # ------------------------------------------------------------------ #
    def _build_ai_card(self):
        box, blay = card(
            "全局 AI",
            "一套配置全程序共用（OpenAI 兼容）：工具箱（标题/语言识别、视觉）、"
            "字幕引擎（优化/拆分）与 AI 校准；保存后立即写入字幕引擎")
        ai = engine.ai_load_config()

        self.ai_enabled = SwitchButton(box)
        self.ai_enabled.setChecked(bool(ai.get("enabled", True)))
        blay.addWidget(label_row("启用 AI", row(self.ai_enabled, None)))

        self.ai_key = PasswordLineEdit(box)
        self.ai_key.setText(str(ai.get("api_key", "")))
        self.ai_key.setPlaceholderText("API Key")
        blay.addWidget(label_row("密钥", self.ai_key))

        self.ai_base = LineEdit(box)
        self.ai_base.setText(str(ai.get("base_url", "")))
        self.ai_base.setPlaceholderText(
            "如 https://open.bigmodel.cn/api/paas/v4（兼容 OpenAI/DeepSeek/"
            "Gemini 兼容层/Ollama/Azure 等，填到域名或版本段均可）")
        blay.addWidget(label_row("接口地址", self.ai_base))

        self.ai_model = LineEdit(box)
        self.ai_model.setText(str(ai.get("model", "")))
        self.ai_model.setPlaceholderText("文本模型，如 glm-4.7-flash")
        blay.addWidget(label_row("文本模型", self.ai_model))

        self.ai_vision = LineEdit(box)
        self.ai_vision.setText(str(ai.get("vision_model", "")))
        self.ai_vision.setPlaceholderText("视觉模型，如 glm-4.6v-flash（屏幕识别用）")
        blay.addWidget(label_row("视觉模型", self.ai_vision))

        test_btn = PushButton(FIF.SEND, "测试接口", box)
        test_btn.clicked.connect(lambda: self._ai_test())
        save_btn = PrimaryPushButton(FIF.SAVE, "保存并应用", box)
        save_btn.clicked.connect(self._ai_save)
        blay.addWidget(row(test_btn, save_btn, None))

        self.ai_hint = fit_caption(CaptionLabel(
            "保存后立即生效：自动写入字幕引擎的 OpenAI 兼容槽，AI 校准同用本配置；"
            "地址填到域名或版本段均可自动补全（含 Azure：填到 deployments/<部署名>）",
            box))
        self.ai_hint.setTextColor("#8a8a8a", "#9a9a9a")
        blay.addWidget(self.ai_hint)
        for w in (self.ai_key, self.ai_base, self.ai_model, self.ai_vision):
            expand_h(w)
        self.vbox.addWidget(box)

    # ------------------------------------------------------------------ #
    # ASR 语音识别：独立 ASR 模型（自有服务 / 本地模型）→ 引擎「转录配置」
    # ------------------------------------------------------------------ #
    def _build_asr_card(self):
        box, blay = card(
            "ASR 语音识别（转录配置）",
            "语音转文字可用独立的 ASR 模型：自有 ASR 服务（OpenAI 兼容接口）"
            "或本地独立模型；保存后自动写入字幕引擎的「转录配置」")
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
        self.asr_base.setPlaceholderText("如 https://api.siliconflow.cn/v1")
        slay.addWidget(label_row("ASR 接口地址", self.asr_base))
        self.asr_key = PasswordLineEdit(self.asr_service_widget)
        self.asr_key.setText(str(ai.get("asr_api_key", "")))
        self.asr_key.setPlaceholderText("ASR 服务 API Key")
        slay.addWidget(label_row("ASR 密钥", self.asr_key))
        self.asr_model = LineEdit(self.asr_service_widget)
        self.asr_model.setText(str(ai.get("asr_model", "")))
        self.asr_model.setPlaceholderText("如 FunAudioLLM/SenseVoiceSmall、whisper-1")
        slay.addWidget(label_row("ASR 模型名", self.asr_model))
        self.asr_prompt = LineEdit(self.asr_service_widget)
        self.asr_prompt.setText(str(ai.get("asr_prompt", "")))
        self.asr_prompt.setPlaceholderText("识别提示词（可留空：中文会自动加简体提示）")
        slay.addWidget(label_row("识别提示词", self.asr_prompt))
        blay.addWidget(self.asr_service_widget)

        # —— 本地模型 ——
        self.asr_local_widget = QWidget(box)
        llay = QVBoxLayout(self.asr_local_widget)
        llay.setContentsMargins(0, 0, 0, 0)
        llay.setSpacing(8)
        self.asr_local_model = LineEdit(self.asr_local_widget)
        self.asr_local_model.setText(str(ai.get("asr_local_model", "")))
        self.asr_local_model.setPlaceholderText("模型名，如 large-v3、large-v3-turbo 或自训练模型目录名")
        llay.addWidget(label_row("本地模型名", self.asr_local_model))
        self.asr_local_dir = LineEdit(self.asr_local_widget)
        self.asr_local_dir.setText(str(ai.get("asr_local_model_dir", "")))
        self.asr_local_dir.setPlaceholderText("留空 = 用软件 data\\VideoCaptioner\\models")
        self.asr_local_browse = PushButton(FIF.FOLDER, "浏览…", self.asr_local_widget)
        self.asr_local_browse.clicked.connect(
            lambda: self._browse_into(self.asr_local_dir, "选择 ASR 模型目录"))
        llay.addWidget(row(self.asr_local_dir, self.asr_local_browse))
        blay.addWidget(self.asr_local_widget)

        asr_test = PushButton(FIF.SEND, "测试 ASR 配置", box)
        asr_test.clicked.connect(self._asr_test)
        asr_save = PrimaryPushButton(FIF.SAVE, "保存并应用", box)
        asr_save.clicked.connect(self._ai_save)
        blay.addWidget(row(asr_test, asr_save, None))

        self.asr_hint = fit_caption(CaptionLabel(
            "服务模式：转录模型自动切到 Whisper [API]，填自己的 ASR 地址即可；"
            "本地模式：切到 FasterWhisper 并优先用上面指定的模型/目录", box))
        self.asr_hint.setTextColor("#8a8a8a", "#9a9a9a")
        blay.addWidget(self.asr_hint)
        for w in (self.asr_base, self.asr_key, self.asr_model, self.asr_prompt,
                  self.asr_local_model, self.asr_local_dir):
            expand_h(w)
        self.vbox.addWidget(box)
        self._sync_asr_visible()

    def _sync_asr_visible(self):
        """按 ASR 模式显隐「服务 / 本地」两组输入。"""
        local = self.asr_mode_combo.currentIndex() == 1
        self.asr_service_widget.setVisible(not local)
        self.asr_local_widget.setVisible(local)
        self.asr_hint.setText(
            "本地模式：转录模型切到 FasterWhisper，优先用上面填写的模型名与目录"
            "（可指向自训练/微调的模型）；目录留空则用软件内的 models 目录"
            if local else
            "服务模式：转录模型切到 Whisper [API]，由自有 ASR 服务完成语音识别；"
            "地址填到 /v1 即可（自动补 /audio/transcriptions）")

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
            "字幕校准页开启「AI 校准」后生效：先跑术语脚本基线，再由 AI 逐块复校"
            "（只改文字，时间轴与格式一字不动；读不完自动拆分再合并）；"
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

        calib_save = PrimaryPushButton(FIF.SAVE, "保存并应用", box)
        calib_save.clicked.connect(self._ai_save)
        blay.addWidget(row(calib_save, None))

        self.calib_hint = fit_caption(CaptionLabel(
            "条数 / 字符预算越小越稳（单次读不完会自动拆半重试），越大越快；"
            "改动必须能被术语知识库解释，无法解释的提议会被拒绝并写进报告", box))
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
            "asr_local_model": self.asr_local_model.text().strip(),
            "asr_local_model_dir": engine.clean_path(self.asr_local_dir.text()),
            # AI 校准（v1.12.0：通道选择随双通道合并一并移除）
            "calib_chunk_cues": self.calib_cues.value(),
            "calib_max_chars": self.calib_chars.value(),
            "calib_max_tokens": self.calib_tokens.value(),
        }

    def _ai_save(self):
        try:
            engine.ai_save_config(self._collect_ai())
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

    def _ai_test_done(self, result, err, name="AI 接口"):
        if err is not None:
            InfoBar.error(f"{name} 测试失败", str(err)[:300], duration=6000,
                          position=InfoBarPosition.BOTTOM_RIGHT, parent=self)
            return
        ok, msg = result
        (InfoBar.success if ok else InfoBar.error)(
            f"{name} 正常" if ok else f"{name} 不可用", str(msg)[:300],
            duration=6000, position=InfoBarPosition.BOTTOM_RIGHT, parent=self)

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
    # 校准知识多用户同步（启动拉取合并 / 退出先并再推，对等并集）
    # ------------------------------------------------------------------ #
    def _build_sync_card(self):
        box, blay = card(
            "校准知识多用户同步",
            "启动自动拉取 GitHub 最新校准知识并合并其他用户的新条目；退出先并入远程再推送")
        self.sync_switch = SwitchButton(box)
        self.sync_switch.setChecked(engine.calib_sync_enabled())
        self.sync_switch.checkedChanged.connect(self._on_sync_toggle)
        blay.addWidget(label_row("启用自动同步", row(self.sync_switch, None)))

        sync_btn = PushButton(FIF.SYNC, "立即同步一次", box)
        sync_btn.clicked.connect(self._sync_now)
        blay.addWidget(row(sync_btn, None))

        self.sync_hint = fit_caption(CaptionLabel(
            "多用户互不覆盖：只做条目并集、从不删除，所有人最终收敛到全体条目的并集",
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
        InfoBar.info("正在同步", "正在拉取并合并远程校准知识…", duration=1200,
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
        self.mica_switch.setChecked(True)
        blay.addWidget(label_row("云母特效", row(self.mica_switch, None)))
        self.vbox.addWidget(box)

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


# ========== 字幕校准 ==========
class CalibPage(ScrollPage):
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
        super().__init__("字幕校准",
                         "调用统一校准脚本 subtitle_calib_merged.py 做名词级术语校准；"
                         "序号 / 时间轴 / 空行 / 换行 / BOM 一字不动", parent)
        self.app = app
        self.setObjectName("CalibPage")
        self.running = False
        self.ai_running = False
        self._cancel_flag = False   # AI 校准取消标志（关闭页面/再次点击）
        self._round = 0             # 已完成的 AI 校准轮次（「再次校准」据此递增）
        self._last_out = ""         # 上一轮 AI 校准输出（再次校准的输入）
        self._base_stem = ""        # 第 1 轮确定的输出基名（后续轮次派生命名）
        self._script = os.path.join(engine.APP_DIR, "subtitle_calib_merged.py")

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
        lay.addWidget(row(self.stage_label, None, self.again_btn, self.run_btn))
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

    def start(self):
        if self.running or self.ai_running:
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
        self.run_btn.setEnabled(False)
        self.stage_label.setText("正在校准…")
        self.log.line(f"[校准] 模式: {self.mode_combo.currentText()}"
                      + ("（仅统计）" if stats_only else ""), "dim")
        self.log.line(f"[校准] 输入: {os.path.basename(src)}", "dim")
        if out:
            self.log.line(f"[校准] 输出: {out}", "dim")
        threading.Thread(target=self._worker, args=(args, out), daemon=True).start()

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
        self.run_btn.setEnabled(False)
        self.again_btn.setEnabled(False)
        self.stage_label.setText(f"AI 校准中（第 {round_no} 轮）…")
        self.log.line(f"===== AI 校准 · 第 {round_no} 轮 =====", "info")
        self.log.line(f"[AI] 模式: {self.mode_combo.currentText()}", "dim")
        self.log.line(f"[AI] 输入: {src}", "dim")
        self.log.line(f"[AI] 输出: {out}", "dim")
        if report:
            self.log.line(f"[AI] 报告: {report}", "dim")
        threading.Thread(target=self._ai_worker,
                         args=(src, out, report, mode_flag, round_no),
                         daemon=True).start()

    def _ai_worker(self, src, out, report, mode_flag, round_no):
        def _log(msg, level="dim"):
            self.app.q.put(("cal_log", str(msg), level))

        try:
            res = engine.calib_ai_run(
                src, out=out, report=(report or None), mode_flag=mode_flag,
                fix_en=self.fix_switch.isChecked(), log=_log, round_no=round_no,
                cancel=lambda: self._cancel_flag)
        except Exception as e:  # noqa: BLE001
            res = {"ok": False, "out": out, "error": f"{type(e).__name__}: {e}",
                   "script_changes": 0, "ai_changes": 0, "rejected": 0,
                   "round": round_no}
        self.app.q.put(("cal_done", 0 if res.get("ok") else 1,
                        res.get("out") or out, res))

    def _worker(self, args, out):
        try:
            env = dict(os.environ, PYTHONIOENCODING="utf-8")
            proc = engine.popen_process(args, cwd=os.path.dirname(self._script),
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, encoding="utf-8", errors="replace",
                                        bufsize=1, env=env)
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    self.app.q.put(("cal_log", line))
            rc = proc.wait()
        except Exception as e:  # noqa: BLE001
            self.app.q.put(("cal_log", f"[错误] 校准进程异常: {e}"))
            rc = 1
        self.app.q.put(("cal_done", rc, out))

    def on_cal_done(self, rc, out, res=None):
        """校准结束（脚本模式 res 为 None；AI 模式 res 为 Agent 结果 dict）。"""
        self.running = False
        self.ai_running = False
        self.run_btn.setEnabled(True)
        res = res or {}
        if res.get("round"):                    # AI 轮次
            if rc == 0:
                self._round = int(res.get("round") or self._round)
                self._last_out = out
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
                self.log.line("如仍有残留错形，可点「再次校准」再跑一轮（在第 1 轮输出上续跑）",
                              "info")
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


# ========== 主窗口 ==========
PAGE_TITLES = {"DownloadPage": "视频下载", "LibraryPage": "视频库",
               "MergePage": "音视频合并", "SubtitlePage": "字幕处理",
               "CalibPage": "字幕校准", "SettingsPage": "设置"}


class MainWindow(FluentWindow):
    """FluentWindow + 左侧导航（结构与主流 Fluent 桌面应用一致）。

    v1.10.4 起：
      · 导航宽度按最长项文字自适应（最长文字 + 2 个字符），不再固定 322px；
      · 设置页统一挂在导航底部，字幕引擎设置并入其中；
      · 跨屏拖拽保持相对位置，不再因两屏缩放比不同而瞬移；
      · 字幕引擎界面后台预热，消除首次进入本页的数秒卡顿。
    """

    #: 导航项文案（宽度按其中最长的一项计算）
    NAV_TEXTS = ["视频下载", "视频库", "音视频合并", "字幕处理", "字幕校准", "设置"]

    def __init__(self, argv=None):
        # 跨屏拖拽状态必须在 super().__init__() 之前建立：窗口构造过程中
        # Qt 就会派发 moveEvent，届时 moveEvent 会读这些属性
        self._last_screen = None
        self._last_screen_geo = None
        self._drag_anchor = None      # (相对屏宽的左/右比例) 用于跨屏重定位
        super().__init__()
        self.q = queue.Queue()
        self.setWindowTitle(f"视频工具箱 v{VERSION}")
        self.resize(1180, 860)
        self.setMinimumSize(960, 640)

        try:
            self.setMicaEffectEnabled(True)
        except Exception:
            pass

        self.download_page = DownloadPage(self, self)
        self.library_page = LibraryPage(self, self)
        self.merge_page = MergePage(self, self)
        self.subtitle_page = SubtitlePage(self, self)
        self.calib_page = CalibPage(self, self)
        self.settings_page = SettingsPage(self, self)
        for page in (self.download_page, self.library_page, self.merge_page,
                     self.subtitle_page, self.calib_page, self.settings_page):
            page.installEventFilter(self)

        self.addSubInterface(self.download_page, FIF.DOWNLOAD, "视频下载")
        self.addSubInterface(self.library_page, FIF.VIDEO, "视频库")
        self.addSubInterface(self.merge_page, FIF.MEDIA, "音视频合并")
        self.navigationInterface.addSeparator()
        self.addSubInterface(self.subtitle_page, FIF.FONT, "字幕处理")
        self.addSubInterface(self.calib_page, FIF.EDIT, "字幕校准")
        self.addSubInterface(self.settings_page, FIF.SETTING, "设置",
                             position=NavigationItemPosition.BOTTOM)

        # 侧边导航常驻展开（默认窄条只有图标），宽度按最长项自适应
        self.navigationInterface.setCollapsible(False)
        self._apply_nav_width()
        # 首帧后 + 字体度量就绪后再各收敛一次：任何时刻导航宽度都是
        # 「最长项文字 + 2 个字符」，不会出现「启动时一个宽度、稍后另一个宽度」
        QTimer.singleShot(0, self._apply_nav_width)
        QTimer.singleShot(400, self._apply_nav_width)

        self.switchTo(self.download_page)
        self._apply_argv(argv or [])
        QTimer.singleShot(400, self.library_page.auto_load)
        QTimer.singleShot(120, self._pump)
        # 字幕引擎界面后台预热：主窗口首帧之后立刻开始导入依赖（预热本身只起
        # 一个后台线程，不占主线程），导入完成即回主线程建界面，用户真正点进
        # 「字幕处理」时通常已是现成控件。v1.11.0 起由 900ms 提前到首帧后立即，
        # 配合 diskcache 延迟化，最坏情况下（刚启动就点进去）的等待已降到亚秒级。
        QTimer.singleShot(0, self.subtitle_page.prewarm)
        # 主屏 DPI 变化（改缩放比/拖到另一块屏）时重新计算导航宽度。
        # 注意必须用 QApplication 实例的信号：PyQt5 里类的同名属性是未绑定的
        # pyqtSignal 描述符，直接 .connect 会抛 AttributeError。
        try:
            QApplication.instance().primaryScreenChanged.connect(
                lambda *_: self._on_screen_changed())
        except Exception:
            pass

    def _on_screen_changed(self):
        """屏幕变化（换主屏 / 改缩放比）时重算导航宽度并收敛窗口。"""
        self._apply_nav_width()
        self._remember_screen()

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
        """按所在屏幕可用区域收敛窗口尺寸并居中。

        1180x860 的默认尺寸在小屏（1080p 任务栏/150% 缩放）上会超出屏幕，
        导致右侧按钮被裁掉——启动时先按可用区域的 92% 收敛。
        全程用**逻辑像素**（Qt 的 geometry 在开启高 DPI 缩放后即为逻辑像素），
        因此 100% / 125% / 150% / 200% 下占用屏幕的比例保持一致。
        """
        try:
            avail = self.screen().availableGeometry()
        except Exception:
            return
        w = min(self.width(), int(avail.width() * 0.92))
        h = min(self.height(), int(avail.height() * 0.92))
        w = max(w, self.minimumWidth())
        h = max(h, self.minimumHeight())
        self.resize(w, h)
        self.move(avail.x() + (avail.width() - w) // 2,
                  avail.y() + (avail.height() - h) // 2)
        self._remember_screen()

    # ---------- 跨屏拖拽 ----------
    def _remember_screen(self):
        scr = self.screen()
        if scr is None:
            return
        if scr is not self._last_screen:
            self._last_screen = scr
            self._last_screen_geo = scr.geometry()
            # 监听该屏幕的 DPI 变化（用户改缩放比时需重算导航宽度）
            try:
                scr.logicalDotsPerInchChanged.connect(
                    lambda *_: self._apply_nav_width())
            except Exception:
                pass

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
        self.stackedWidget.setCurrentWidget(page, popOut=False)
        self.setWindowTitle(
            f"视频工具箱 v{VERSION} — {PAGE_TITLES.get(page.objectName(), '')}")

    def page_by_key(self, key):
        return {"download": self.download_page, "library": self.library_page,
                "merge": self.merge_page, "subtitle": self.subtitle_page,
                "calib": self.calib_page, "settings": self.settings_page
                }.get(key)

    def open_engine_settings(self):
        """跳到统一设置页的「字幕引擎」分组（供其他页面调用）。"""
        self.switchTo(self.settings_page)
        self.settings_page.scroll_to_engine()

    def _apply_argv(self, argv):
        """命令行/拖入 .url、含链接的 txt：提取链接填到下载页。"""
        if not argv:
            return
        arg = engine.clean_path(argv[0])
        if not arg:
            return
        if os.path.isfile(arg):
            url = engine.extract_url(arg)
            if url:
                self.download_page.url_edit.setText(url)

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
                # AI 校准会带级别（dim/ok/err/info）；脚本模式只有一行文本
                cal.log.line(args[0], args[1] if len(args) > 1 else "dim")
            elif kind == "cal_done":
                # (rc, out) 脚本模式 / (rc, out, result) AI 模式
                cal.on_cal_done(*args)
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
    setTheme(Theme.DARK)
    setThemeColor("#2F8D63")    # 品牌绿（与字幕引擎界面同色系）
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
            scr = QApplication.primaryScreen()
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

    window.show()
    window.raise_()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
