# @version 2.7.0
"""「AI 托管」页 —— 首页任务框输入**纯文本**时的落点（harness 接入的界面壳）。

边界（与 harness_bridge 的分工）
------------------------------
* 本页只做界面：状态展示、任务输入、流式输出、控制台入口；
* 所有 harness 交互（探测 / 配置同步 / 起进程 / 读回显）都在
  ``harness_bridge``（无 Qt）里，本页不碰 harness 的任何细节；
* harness 未部署 / 未装依赖 / 未构建 / 缺 node / 配置关闭时，宿主仍会创建
  本页并挂「AI 托管」导航项（适配层导入成功即创建），但本页在「状态」下方
  展示「部署引导」卡（fix_hint 处置步骤 + 可复制命令 + 部署文档入口），并
  禁用任务 / 控制台按钮，直到 ``probe()`` 返回 ``ready``。安装版（刻意不含
  harness 原件）也能直接看到怎么补齐，而不是只报一个错误。

为什么单独成模块（与 auto_vision_page 同样的理由）：主文件里的页面共享
``ScrollPage`` / ``card()``，独立成模块会反向 import 主文件形成循环导入。
本页自带一套等价的外壳（``_card`` / ``_row``），只依赖 qfluentwidgets。
"""
from __future__ import annotations

import os
import webbrowser

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel,
                             QPlainTextEdit, QSizePolicy, QVBoxLayout, QWidget)

from vt_fluent import (BodyLabel, CaptionLabel, CardWidget,
                            FluentIcon as FIF, InfoBar, InfoBarPosition,
                            PlainTextEdit, PrimaryPushButton, PushButton,
                            ScrollArea, StrongBodyLabel, TextEdit, TitleLabel)

import harness_bridge as hb

#: 等宽字体（输出区）；取不到 Courier New 时 Qt 自动回退
_MONO = QFont("Courier New", 10)


class _TaskWorker(QObject):
    """把阻塞的 harness 调用丢进后台线程（harness_bridge 全部是阻塞 API）。"""

    reasoning = Signal(str)      # reasoning 流（harness stderr）
    finished = Signal(dict)      # run_task 的完整返回

    def __init__(self, text: str, timeout: int = 0, parent=None):
        super().__init__(parent)
        self._text = text
        self._timeout = timeout

    def run(self):
        r = hb.run_task(self._text, timeout=self._timeout,
                        on_reasoning=self.reasoning.emit)
        self.finished.emit(r)


class _ProbeWorker(QObject):
    """状态探测后台化（2026-10-20 启动优化）。

    ``hb.probe(force=True)`` 与 ``hb.web_alive()`` 都是阻塞调用——后者是
    一次本地 HTTP 探测，harness 未启动时也要 ~2s 才返回。构造期同步跑会把
    首帧直接拖死（实测 MainWindow 构造里占 2.06s）。改为线程执行，结果经
    信号回主线程落地。
    """

    done = Signal(dict)

    def run(self):
        p = hb.probe(force=True)
        alive = hb.web_alive()
        self.done.emit({"p": p, "alive": alive})


def _card(parent, title=None):
    """卡片壳（对齐 auto_vision_page 的自包含写法，不反向 import 主文件）。"""
    card = CardWidget(parent)
    lay = QVBoxLayout(card)
    lay.setContentsMargins(16, 16, 16, 16)
    lay.setSpacing(10)
    if title:
        lay.addWidget(StrongBodyLabel(title, card))
    return card, lay


def _row(widgets, parent=None, stretch_last=False):
    row = QHBoxLayout()
    for i, w in enumerate(widgets):
        if w is None:
            row.addStretch(1)
        else:
            row.addWidget(w)
    if stretch_last:
        row.setStretch(len(widgets) - 1, 1)
    return row


class HarnessPage(ScrollArea):
    """AI 托管页：状态 / 任务 / 输出三张卡片 + 交互控制台入口。"""

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.setObjectName("HarnessPage")
        self.setWidgetResizable(True)
        self._thread = None
        self._worker = None
        self._running = False
        self._probe_thread = None
        self._probe_worker = None
        self._probe_done_once = False

        view = QWidget(self)
        # ⚠ 与其余滚动页一致：viewport 与内容控件**两层**透明化。ScrollArea 的
        # viewport 与 setWidget 后的内容控件 autoFillBackground 默认为 True，
        # 不处理会在深色主题下按调色板把页面背景填成浅灰白。
        view.setStyleSheet("QWidget{background:transparent;}")
        self.setWidget(view)
        self.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        outer = QVBoxLayout(view)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)

        # ---------- ① 状态 ----------
        card, lay = _card(view, "AI 托管 · 状态")
        self.state_label = BodyLabel("检测中 …", card)
        self.state_label.setWordWrap(True)
        lay.addWidget(self.state_label)
        self.sync_label = CaptionLabel("", card)
        self.sync_label.setWordWrap(True)
        lay.addWidget(self.sync_label)
        row = QHBoxLayout()
        self.console_btn = PrimaryPushButton(FIF.CONNECT, "打开交互控制台", card)
        self.console_btn.clicked.connect(self._on_open_console)
        self.stop_btn = PushButton(FIF.CLOSE, "停止控制台", card)
        self.stop_btn.clicked.connect(self._on_stop_console)
        self.refresh_btn = PushButton(FIF.SYNC, "重新检测", card)
        self.refresh_btn.clicked.connect(self.refresh_status)
        row.addWidget(self.console_btn)
        row.addWidget(self.stop_btn)
        row.addWidget(self.refresh_btn)
        row.addStretch(1)
        lay.addLayout(row)
        self.url_label = CaptionLabel("", card)
        self.url_label.setWordWrap(True)
        self.url_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.url_label)
        outer.addWidget(card)

        # ---------- ①⅔ 部署引导（仅未就绪时出现） ----------
        # 未部署 / 未装依赖 / 未构建 / 缺 node / 被禁用时，给一份可直接照做的
        # 处置步骤 + 可一键复制的命令 + 部署文档入口；ready 时整卡隐藏。
        self._fix_card, fix_lay = _card(view, "AI 托管 · 部署引导")
        self._fix_text = QPlainTextEdit(view)
        self._fix_text.setFont(_MONO)
        self._fix_text.setReadOnly(True)
        self._fix_text.setFixedHeight(220)
        self._fix_text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._fix_text.setPlainText("")
        fix_lay.addWidget(self._fix_text)
        fix_row = QHBoxLayout()
        self._fix_copy_btn = PushButton(FIF.COPY, "复制命令", view)
        self._fix_copy_btn.clicked.connect(self._on_copy_fix)
        self._fix_doc_btn = PushButton(FIF.DOCUMENT, "查看部署文档", view)
        self._fix_doc_btn.clicked.connect(self._on_open_doc)
        fix_row.addWidget(self._fix_copy_btn)
        fix_row.addWidget(self._fix_doc_btn)
        fix_row.addStretch(1)
        fix_lay.addLayout(fix_row)
        self._fix_card.setVisible(False)
        outer.addWidget(self._fix_card)

        # ---------- ② 任务 ----------
        card, lay = _card(view, "任务（与首页任务框同一个入口）")
        tip = CaptionLabel(
            "在首页任务框输入纯文本（不是文件、也不是链接）并回车，会自动跳到本页执行；"
            "也可以直接在这里输入。AI 的模型 / 密钥 / 接口地址全部取自「设置」页，"
            "harness 工作目录 = 程序根目录，AI 可读写文件、执行命令来托管本程序。", card)
        tip.setWordWrap(True)
        lay.addWidget(tip)
        self.task_edit = TextEdit(card)
        self.task_edit.setFixedHeight(110)
        lay.addWidget(self.task_edit)
        row = QHBoxLayout()
        self.run_btn = PrimaryPushButton(FIF.PLAY, "交给 AI 托管", card)
        self.run_btn.clicked.connect(self._on_run_clicked)
        row.addWidget(self.run_btn)
        row.addStretch(1)
        self.run_hint = CaptionLabel("", card)
        row.addWidget(self.run_hint)
        lay.addLayout(row)
        outer.addWidget(card)

        # ---------- ③ 输出 ----------
        card, lay = _card(view, "运行输出")
        self.out_edit = QPlainTextEdit(card)
        self.out_edit.setFont(_MONO)
        self.out_edit.setReadOnly(True)
        self.out_edit.setMinimumHeight(260)
        self.out_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        lay.addWidget(self.out_edit)
        outer.addWidget(card)
        outer.addStretch(1)

        # ⚠ 不在构造期同步探测（probe + web_alive 是阻塞调用，harness 未
        # 启动时一次 ~2s）——首帧后由 showEvent 触发第一次后台探测，
        # 期间状态卡显示「检测中 …」。
        QTimer.singleShot(0, self.refresh_status)

    def showEvent(self, e):
        super().showEvent(e)
        # 用户切到本页时补一次探测（页面在后台被构造、探测结果可能已过期）
        if not self._probe_done_once:
            return
        QTimer.singleShot(0, self.refresh_status)

    # ---------------- 状态 ----------------
    def refresh_status(self):
        """启动一次后台状态探测（线程化；连点「重新检测」不会冻结界面）。"""
        if self._probe_thread is not None and self._probe_thread.isRunning():
            return
        self.state_label.setText("检测中 …")
        self._probe_thread = QThread(self)
        self._probe_worker = _ProbeWorker()
        self._probe_worker.moveToThread(self._probe_thread)
        self._probe_thread.started.connect(self._probe_worker.run)
        self._probe_worker.done.connect(self._on_probe_done)
        self._probe_worker.done.connect(self._probe_thread.quit)
        self._probe_thread.start()

    def _on_probe_done(self, r: dict):
        self._probe_done_once = True
        p = r.get("p") or {}
        self.state_label.setText(
            "harness：%s\n· %s\n· 部署目录：%s\n· 运行期数据：%s"
            % (p.get("state", "?"), p.get("detail", ""), p.get("dir", ""),
               hb.dsh_home()))
        self._update_fix_card(p)
        if r.get("alive"):
            self.url_label.setText("控制台：%s" % hb.web_console_url())
        else:
            self.url_label.setText("控制台未启动（打开可能需要 1～3 分钟冷启动）")
        self._refresh_sync_label()

    def _update_fix_card(self, p: dict):
        """未就绪时显示处置引导；ready 时隐藏整卡，并解锁任务/控制台按钮。"""
        ready = (p["state"] == "ready")
        # 未就绪时禁用任务 / 控制台按钮，避免空点报错（引导卡已说明怎么做）
        self.console_btn.setEnabled(ready)
        self.stop_btn.setEnabled(ready)
        self.run_btn.setEnabled(ready)
        if ready:
            self._fix_card.setVisible(False)
            return
        self._fix_card.setVisible(True)
        hint = hb.fix_hint(p["state"], p)
        self._fix_text.setPlainText(hint or hb.status_text())
        cmds = hb.fix_commands(p["state"], p)
        self._fix_copy_btn.setEnabled(bool(cmds))
        self._fix_doc_btn.setEnabled(os.path.isfile(hb.doc_path()))

    def _on_copy_fix(self):
        p = hb.probe(force=True)
        cmds = hb.fix_commands(p["state"], p)
        if not cmds:
            return
        clip = QApplication.clipboard()
        if clip is not None:
            clip.setText(cmds)
            InfoBar.success("已复制", "部署命令已复制到剪贴板",
                            duration=2500, position=InfoBarPosition.TOP, parent=self)

    def _on_open_doc(self):
        doc = hb.doc_path()
        if not os.path.isfile(doc):
            InfoBar.warning("文档缺失", "未找到部署文档：%s" % doc,
                            duration=4000, position=InfoBarPosition.TOP, parent=self)
            return
        try:
            webbrowser.open("file:///" + doc.replace("\\", "/"))
        except Exception as e:  # noqa: BLE001
            InfoBar.error("打开失败", str(e)[:200],
                          duration=4000, position=InfoBarPosition.TOP, parent=self)

    def _refresh_sync_label(self):
        """只刷「设置」页 AI 配置摘要（不碰探测/控制台探针，可安全频发）。"""
        try:
            info = self.app.ai_settings_summary()
        except Exception:  # noqa: BLE001
            info = ""
        self.sync_label.setText(info or "（未读到「设置」页 AI 配置）")

    # ---------------- 任务 ----------------
    def run_task(self, text: str):
        """供宿主调用：从首页任务框带过来的文本，直接开跑。"""
        if self._running:
            InfoBar.warning("忙碌", "上一个任务还在跑，稍候 …",
                            duration=2500, position=InfoBarPosition.TOP,
                            parent=self)
            return
        text = (text or "").strip()
        if not text:
            return
        self.task_edit.setPlainText(text)
        self._start(text)

    def _on_run_clicked(self):
        self._start(self.task_edit.toPlainText())

    def _start(self, text: str):
        text = (text or "").strip()
        if not text:
            InfoBar.warning("空任务", "先输入要让 AI 做的事",
                            duration=2500, position=InfoBarPosition.TOP, parent=self)
            return
        if not hb.available():
            InfoBar.error("harness 不可用", hb.status_text(),
                          duration=4000, position=InfoBarPosition.TOP, parent=self)
            return
        self._running = True
        self.run_btn.setEnabled(False)
        self.run_hint.setText("运行中 …")
        self.out_edit.clear()
        self._append(">>> 任务：%s\n" % text)
        QApplication.processEvents()
        self._thread = QThread(self)
        self._worker = _TaskWorker(text)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.reasoning.connect(self._on_reasoning)
        self._worker.finished.connect(self._on_finished)
        self._worker.finished.connect(self._thread.quit)
        self._thread.start()

    def _on_reasoning(self, line: str):
        self._append("[推理] %s" % line)

    def _on_finished(self, result: dict):
        self._running = False
        self.run_btn.setEnabled(True)
        self.run_hint.setText("")
        ok = bool(result.get("ok"))
        self.run_hint.setText("完成 %.1fs" % float(result.get("elapsed") or 0))
        self._refresh_sync_label()   # 亮出本次实际使用的「设置」页配置
        if result.get("answer"):
            self._append("\n===== AI 答复 =====\n%s\n" % result["answer"])
        if result.get("error"):
            self._append("\n===== 诊断 =====\n%s\n" % result["error"])
        if not ok and not result.get("answer"):
            InfoBar.error("AI 托管失败", (result.get("error") or "未知错误")[:200],
                          duration=6000, position=InfoBarPosition.TOP, parent=self)
        else:
            InfoBar.success("AI 托管完成", "耗时 %.1fs" % float(result.get("elapsed") or 0),
                            duration=3000, position=InfoBarPosition.TOP, parent=self)
        try:
            self._thread.wait(3000)
        except Exception:  # noqa: BLE001
            pass

    def _append(self, text: str):
        self.out_edit.appendPlainText(text.rstrip("\n"))
        sb = self.out_edit.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ---------------- 控制台 ----------------
    def _on_open_console(self):
        if not hb.available():
            InfoBar.error("harness 不可用", hb.status_text(),
                          duration=4000, position=InfoBarPosition.TOP, parent=self)
            return
        self.console_btn.setEnabled(False)
        self.console_btn.setText("正在启动 …")
        InfoBar.info("交互控制台", "冷启动可能要 1～3 分钟，起来了会自动打开浏览器",
                     duration=5000, position=InfoBarPosition.TOP, parent=self)
        r = hb.open_web()
        self.console_btn.setEnabled(True)
        self.console_btn.setText("打开交互控制台")
        if r.get("ok"):
            self.url_label.setText("控制台：%s" % r["url"])
            InfoBar.success("控制台已就绪", r["url"][:120],
                            duration=6000, position=InfoBarPosition.TOP, parent=self)
        else:
            InfoBar.error("控制台启动失败", str(r.get("detail"))[:200],
                          duration=8000, position=InfoBarPosition.TOP, parent=self)

    def _on_stop_console(self):
        r = hb.stop_web()
        InfoBar.info("控制台", r.get("detail", ""),
                     duration=3000, position=InfoBarPosition.TOP, parent=self)
        self.url_label.setText("控制台未启动")

    def closeEvent(self, event):
        try:
            if self._thread is not None and self._thread.isRunning():
                self._thread.quit()
                self._thread.wait(2000)
        except Exception:  # noqa: BLE001
            pass
        super().closeEvent(event)
