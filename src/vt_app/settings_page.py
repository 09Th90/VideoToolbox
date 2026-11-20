# -*- coding: utf-8 -*-
# @version 3.1.2
"""全局设置页（2026-11-15 功能解耦阶段③：从 video_toolbox_qt.py 拆出，逐字同源）。

壳层页面（非可选功能）：全程序唯一全局设置——目录 / 下载 Cookie / 全局 AI /
ASR / AI 校准 / 字幕引擎运行参数（内嵌懒加载）/ 校准知识同步 / 程序更新 /
界面美化 / 关于。随页迁入：_InnerScrollToContent / _BgPathEdit /
AsrExampleDialog / UpdateProgressDialog。

消息自订阅（bus「cookie_import_done」）；VERSION 单一来源仍在入口
video_toolbox_qt.py，本模块经 _version() 懒导入避免循环。
"""
import os
import sys
import threading

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtWidgets import (QApplication, QDialog, QFileDialog, QFrame,
                               QHBoxLayout, QLabel, QMessageBox,
                               QPlainTextEdit, QSizePolicy, QTabWidget,
                               QVBoxLayout, QWidget)

from vt_fluent import (BodyLabel, CaptionLabel, ComboBox, FluentIcon as FIF,
                       InfoBar, InfoBarPosition, LineEdit, MessageBox,
                       PasswordLineEdit, PrimaryPushButton, ProgressBar,
                       PushButton, Slider, SpinBox, StrongBodyLabel,
                       SwitchButton, TextEdit)

import video_toolbox as engine
import ui_theme
import vt_update_check

from vt_app.boot import _perf_note
from vt_app.scheduler import _SCHED, _defer
from vt_app.engine_ui import (_ENGINE_PREWARM, _engine_prewarm_probe,
                              _resolve_engine_ui, _start_engine_prewarm)
from vt_app.lazy_shell import _lazy_real
from vt_app.widgets import (AccentDot, ScrollPage, card, expand_h,
                            fit_caption, fit_spin, label_row, row, srow)


def _version():
    """版本号单一来源在入口 video_toolbox_qt.py（apply_version 锚点），懒导入避循环。"""
    from video_toolbox_qt import VERSION  # noqa: PLC0415
    return VERSION


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

        # 功能解耦阶段③：消息自订阅（原入口 _dispatch 的 cookie_import_done 分支）。
        app.bus.subscribe("cookie_import_done", self._on_bus_message)

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

    # ---------- 消息 ----------
    def _on_bus_message(self, msg):
        """bus 消息（原入口 _dispatch 的 cookie_import_done 分支，语义逐字一致）。"""
        kind, args = msg[0], msg[1:]
        if kind == "cookie_import_done":
            self.on_cookie_import_done(*args)

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
        # 壳层取下载功能的并发上限默认值：懒导入功能页（避免模块级循环）
        from features.download.page import DownloadPage  # noqa: PLC0415
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
        self.ai_jev_switch = SwitchButton(box)
        self.ai_jev_switch.setChecked(str(ai.get("decision_mode") or "shadow") != "off")
        self.ai_jev_switch.setToolTip(
            "仅在全局 AI 地址为百炼 Token Plan 专属域名时调用 "
            "decision-model-preview；只给声纹存疑和校准采纳项追加影子复核证据，"
            "不改写字幕。普通百炼、火山方舟及其他端点均不会请求。")
        blay.addWidget(label_row("Jev 影子决策", row(self.ai_jev_switch, None)))
        self.ai_jev_hint = fit_caption(CaptionLabel("", box))
        blay.addWidget(self.ai_jev_hint)
        self.ai_jev_switch.checkedChanged.connect(self._mark_ai_dirty)
        self.ai_jev_switch.checkedChanged.connect(self._sync_plan_warn)
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
        self.asr_card = box
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
        jev_hint = getattr(self, "ai_jev_hint", None)
        if jev_hint is not None:
            switch = getattr(self, "ai_jev_switch", None)
            if switch is not None and not switch.isChecked():
                text = "Jev 已关闭，不会发起结构化决策请求。"
            else:
                from core.shared.decision import decision_mod
                current = engine.ai_load_config()
                key_ready = bool(self.ai_key.text().strip()
                                 or str(current.get("api_key") or "").strip())
                token_plan = decision_mod().is_aliyun_token_plan(self.ai_base.text())
                if not token_plan:
                    text = "Jev 已开启，但当前不是百炼 Token Plan 专属端点，不会调用。"
                elif not key_ready:
                    text = "Jev 地址符合，但全局 AI 密钥未配置，不会调用。"
                elif not self.ai_enabled.isChecked():
                    text = "Jev 地址与密钥符合，但全局 AI 已禁用，不会调用。"
                else:
                    text = ("当前满足 Jev 激活条件；保存后将影子复核声纹存疑与"
                            "校准采纳项，不改写字幕。")
            jev_hint.setText(text)

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
            # Jev 仅作影子复核；真正激活还要通过百炼 Token Plan 端点门控。
            "decision_mode": ("shadow" if self.ai_jev_switch.isChecked() else "off"),
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
            # 音画证据（2026-10-12）：AI 校准 Agent 可请求源媒体音频重转写/抽帧描述
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
        text = str(msg)
        # 本地 ASR 的失败原因是**逐项清单**（缺哪个文件、回退到哪个目录）：
        # InfoBar 单行会截断成半句，改用对话框完整展示（2026-11-19）。
        if not ok and ("\n" in text or len(text) > 300):
            try:
                dlg = MessageBox(f"{name} 不可用", text[:3000], self.window())
                try:
                    dlg.yesButton.setText("知道了")
                    dlg.cancelButton.hide()
                except Exception:  # noqa: BLE001
                    pass
                dlg.exec_()
                return
            except Exception:  # noqa: BLE001 - 弹窗失败仍回退 InfoBar
                pass
        text = text[:300]
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

    def scroll_to_asr(self):
        """外部调用：定位到「ASR 语音识别」卡片（转录失败提示条用）。"""
        QTimer.singleShot(0, self._scroll_to_asr_card)

    def _scroll_to_asr_card(self):
        try:
            card_w = getattr(self, "asr_card", None)
            if self.shell.area is not None and card_w is not None:
                self.shell.area.ensureWidgetVisible(card_w, 0, 80)
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
        self.upd_ver_label = BodyLabel("当前版本 v%s" % _version(), box)
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
        box, blay = card("关于", f"视频工具箱 v{_version()}")
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


def build_page(app, parent=None):
    """壳层设置页工厂（MainWindow 经此构造，保持与功能页同一形态）。"""
    return SettingsPage(app, parent)