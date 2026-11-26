# -*- coding: utf-8 -*-
# @version 3.3.1
"""v3 壳层辅助条：内容区顶栏与底部状态栏。

只负责视觉与页面标题同步，不接管导航/堆叠/业务状态。由 MainWindow 在
首帧后按几何摆放在内容区上下，避免改动 FluentWindow 的无边框与缩放逻辑。
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy

import ui_theme


class ShellTopBar(QFrame):
    """内容区顶栏：面包屑 + 当前页标题 + 版本。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ShellTopBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(48)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 0, 10, 0)
        lay.setSpacing(8)
        self.crumb = QLabel("视频工具箱 / 首页", self)
        self.crumb.setObjectName("ShellCrumb")
        self.crumb.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.version = QLabel("", self)
        self.version.setObjectName("ShellVersion")
        self.version.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        # 顶栏整条都是拖动热区：子标签不能吞掉鼠标事件。
        for lab in (self.crumb, self.version):
            lab.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        lay.addWidget(self.crumb, 1)
        lay.addWidget(self.version)
        self._drag_offset = None
        self._apply_theme()
        ui_theme.connect_theme(self, lambda w: w._apply_theme())

    # ---- 无边框窗口拖动：顶栏覆盖了标题栏，必须自己把拖动交回系统 ----
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            win = self.window()
            handle = win.windowHandle() if win is not None else None
            if handle is not None and handle.startSystemMove():
                e.accept()
                return
            # 某些平台 startSystemMove 不可用：退化为手动跟随，保证不会卡死。
            if win is not None:
                self._drag_offset = (e.globalPosition().toPoint()
                                     - win.frameGeometry().topLeft())
                e.accept()
                return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        win = self.window()
        if (self._drag_offset is not None and win is not None
                and (e.buttons() & Qt.LeftButton)):
            win.move(e.globalPosition().toPoint() - self._drag_offset)
            e.accept()
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._drag_offset = None
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            win = self.window()
            if win is not None:
                win.showNormal() if win.isMaximized() else win.showMaximized()
                e.accept()
                return
        super().mouseDoubleClickEvent(e)

    def _apply_theme(self):
        t = ui_theme.tokens()
        self.setStyleSheet(
            "QFrame#ShellTopBar{background:%s;border-bottom:1px solid %s;}"
            "QLabel#ShellCrumb{color:%s;font-size:11.5px;font-weight:500;"
            "background:transparent;}"
            "QLabel#ShellVersion{color:%s;font-size:9.5px;background:transparent;}"
            % (t["nav"], t["card_border"], t["text"], t["text_dim"]))

    def set_page(self, title):
        self.crumb.setText("视频工具箱 / " + (title or "首页"))


class ShellStatusBar(QFrame):
    """内容区底栏：本地模式、主题、配置与版本。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ShellStatusBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(26)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(22, 0, 18, 0)
        lay.setSpacing(14)
        self.left = QLabel("本地模式", self)
        self.mode = QLabel("", self)
        self.config = QLabel("配置 本机", self)
        self.version = QLabel("", self)
        for lab in (self.left, self.mode, self.config, self.version):
            lab.setObjectName("ShellStatusText")
            lab.setStyleSheet("background:transparent;")
        self.version.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(self.left)
        lay.addWidget(self.mode)
        lay.addWidget(self.config)
        lay.addStretch(1)
        lay.addWidget(self.version)
        self._apply_theme()
        ui_theme.connect_theme(self, lambda w: w._apply_theme())

    def _apply_theme(self):
        t = ui_theme.tokens()
        self.setStyleSheet(
            "QFrame#ShellStatusBar{background:%s;border-top:1px solid %s;}"
            "QLabel#ShellStatusText{color:%s;font-size:9.5px;background:transparent;}"
            % (t["nav"], t["card_border"], t["text_dim"]))
        self.mode.setText("主题 " + ("深色" if ui_theme.is_dark() else "浅色"))

    def set_version(self, version):
        self.version.setText("v" + str(version) + "  ·  本地模式")
