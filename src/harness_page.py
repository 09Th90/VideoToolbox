# @version 2.1.0
"""「AI 托管」页 —— 首页任务框输入**纯文本**时的落点（harness 接入的界面壳）。

边界（与 harness_bridge 的分工）
------------------------------
* 本页只做界面：状态展示、任务输入、流式输出、控制台入口；
* 所有 harness 交互（探测 / 配置同步 / 起进程 / 读回显）都在
  ``harness_bridge``（无 Qt）里，本页不碰 harness 的任何细节；
* harness 未部署 / 未装依赖 / 未构建时，宿主（video_toolbox_qt）**不会创建
  本页、不会挂导航项**——用户侧完全感知不到，既有功能零影响。

为什么单独成模块（与 auto_vision_page 同样的理由）：主文件里的页面共享
``ScrollPage`` / ``card()``，独立成模块会反向 import 主文件形成循环导入。
本页自带一套等价的外壳（``_card`` / ``_row``），只依赖 qfluentwidgets。
"""
from __future__ import annotations

import os

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel,
                             QPlainTextEdit, QSizePolicy, QVBoxLayout, QWidget)

from qfluentwidgets import (BodyLabel, CaptionLabel, CardWidget,
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

        view = QWidget(self)
        self.setWidget(view)
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

        self.refresh_status()

    # ---------------- 状态 ----------------
    def refresh_status(self):
        p = hb.probe(force=True)
        self.state_label.setText(
            "harness：%s\n· %s\n· 部署目录：%s\n· 运行期数据：%s"
            % (p["state"], p["detail"], p["dir"], hb.dsh_home()))
        if hb.web_alive():
            self.url_label.setText("控制台：%s" % hb.web_console_url())
        else:
            self.url_label.setText("控制台未启动（打开可能需要 1～3 分钟冷启动）")
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
