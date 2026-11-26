# -*- coding: utf-8 -*-
# @version 3.3.1
"""Qt 悬浮字幕层：置顶、透明、无边框、可拖动、滚轮字号、点击穿透。

与旧 tkinter 版（vt-web-server/itxw/ui/overlay.py）的差异：
* 复用项目一 ``features/subtitle_edit/subtitle_overlay.py`` 的顶层透明窗经验，
  不再需要第二套 GUI 事件循环；
* 只用 ``QTimer`` 由页面推送 Cue，本窗口不采集、不做网络请求；
* 点击穿透走 ``Qt.WindowTransparentForInput``，关闭后仍可用右键菜单拖动/调字号。
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication
from PySide6.QtWidgets import QFrame, QLabel, QMenu, QVBoxLayout, QWidget


def _rgb(hex_color: str, fallback=(16, 16, 16)) -> tuple[int, int, int]:
    try:
        c = QColor(str(hex_color))
        if c.isValid():
            return c.red(), c.green(), c.blue()
    except Exception:  # noqa: BLE001
        pass
    return fallback


class OverlayWindow(QWidget):
    name = "live-overlay"

    def __init__(self, cfg, parent=None):
        super().__init__(None)
        self.cfg = cfg
        self.setObjectName("LiveOverlay")
        self.setWindowTitle("实时字幕")
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint
                            | Qt.WindowStaysOnTopHint
                            | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)

        self._drag: QPoint | None = None
        self._click_through = bool(cfg.get("ui", "click_through", False))
        self._positioned = False
        self._last = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.frame = QFrame(self)
        self.frame.setObjectName("LiveOverlayFrame")
        lay = QVBoxLayout(self.frame)
        lay.setContentsMargins(26, 14, 26, 16)
        lay.setSpacing(4)

        self.history_label = QLabel("", self.frame)
        self.history_label.setAlignment(Qt.AlignCenter)
        self.history_label.setWordWrap(True)
        self.main_label = QLabel("", self.frame)
        self.main_label.setAlignment(Qt.AlignCenter)
        self.main_label.setWordWrap(True)
        self.sub_label = QLabel("", self.frame)
        self.sub_label.setAlignment(Qt.AlignCenter)
        self.sub_label.setWordWrap(True)
        lay.addWidget(self.history_label)
        lay.addWidget(self.main_label)
        lay.addWidget(self.sub_label)
        outer.addWidget(self.frame)

        self.history_label.hide()
        self.sub_label.hide()
        self._apply_fonts()
        self._apply_style()
        self.resize(900, 140)

    # ------------------------------------------------------------------ look
    def _apply_fonts(self) -> None:
        family = str(self.cfg.get("ui", "font", "Microsoft YaHei UI"))
        size_main = int(self.cfg.get("ui", "size_main", 32))
        size_sub = int(self.cfg.get("ui", "size_sub", 25))
        self.main_label.setFont(QFont(family, size_main))
        self.sub_label.setFont(QFont(family, size_sub))
        self.history_label.setFont(QFont(family, max(12, size_sub - 6)))
        self.main_label.setStyleSheet("color: %s; background: transparent;"
                                      % self.cfg.get("ui", "fg_main", "#FFFFFF"))
        self.sub_label.setStyleSheet("color: %s; background: transparent;"
                                     % self.cfg.get("ui", "fg_sub", "#9CDCFE"))
        self.history_label.setStyleSheet(
            "color: rgba(255,255,255,120); background: transparent;")

    def _apply_style(self) -> None:
        r, g, b = _rgb(self.cfg.get("ui", "bg", "#101010"))
        alpha = max(0.3, min(1.0, float(self.cfg.get("ui", "alpha", 0.88))))
        self.frame.setStyleSheet(
            "#LiveOverlayFrame { background-color: rgba(%d,%d,%d,%d); "
            "border-radius: 12px; }" % (r, g, b, int(round(alpha * 255))))

    def apply_ui(self) -> None:
        self._apply_fonts()
        self._apply_style()
        self._click_through = bool(self.cfg.get("ui", "click_through", False))
        self._apply_click_through(self._click_through)

    # ------------------------------------------------------------------ cues
    def set_cues(self, cues: list[dict]) -> None:
        finals = [c for c in (cues or [])
                  if not c.get("interim") and (c.get("main") or c.get("sub"))]
        if not finals:
            return
        self._last = finals[-1]
        history = finals[:-1]
        hist_text = "  ·  ".join(
            (c.get("main") or c.get("sub") or "").strip()
            for c in history[-2:])[:160]
        self.history_label.setText(hist_text)
        self.history_label.setVisible(bool(hist_text))
        main = (self._last.get("main") or self._last.get("sub") or "").strip()
        sub = (self._last.get("sub") or "").strip()
        self.main_label.setText(main)
        self.sub_label.setText(sub)
        self.sub_label.setVisible(bool(sub) and sub != main)
        color = self.cfg.get("ui", "fg_degraded", "#FFB86C") \
            if self._last.get("degraded") else self.cfg.get("ui", "fg_main", "#FFFFFF")
        self.main_label.setStyleSheet("color: %s; background: transparent;" % color)
        self._fit()

    def _fit(self) -> None:
        screen = QGuiApplication.screenAt(QCursor.pos()) \
            or QGuiApplication.primaryScreen()
        if screen is None:
            return
        ratio = float(self.cfg.get("ui", "width_ratio", 0.8))
        width = min(int(screen.geometry().width() * max(0.3, min(1.0, ratio))),
                    screen.geometry().width() - 40)
        self.setFixedWidth(width)
        self.adjustSize()
        self.frame.adjustSize()

    # ------------------------------------------------------------------ show
    def show_overlay(self) -> None:
        if not self._positioned:
            self.move_to_bottom()
        self._apply_click_through(self._click_through)
        self.show()
        self.raise_()
        self._positioned = True

    def hide_overlay(self) -> None:
        self.hide()

    def move_to_bottom(self) -> None:
        screen = QGuiApplication.screenAt(QCursor.pos()) \
            or QGuiApplication.primaryScreen()
        if screen is None:
            return
        self._fit()
        geo = screen.geometry()
        margin = int(self.cfg.get("ui", "margin_px", 40))
        width = self.width()
        height = max(self.sizeHint().height(), self.height())
        x = geo.left() + (geo.width() - width) // 2
        y = geo.top() + geo.height() - height - margin
        self.move(max(geo.left(), x), max(geo.top(), y))
        self._positioned = True

    # ------------------------------------------------------------------ input
    def set_click_through(self, enabled: bool) -> None:
        self.cfg.hot_update({"ui.click_through": bool(enabled)})
        self._click_through = bool(enabled)
        self._apply_click_through(self._click_through)

    def _apply_click_through(self, enabled: bool) -> None:
        self.setWindowFlag(Qt.WindowTransparentForInput, bool(enabled))
        if self.isVisible():
            self.show()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and not self._click_through:
            self._drag = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag = None
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:
        step = 2 if event.angleDelta().y() > 0 else -2
        size_main = max(14, min(72, int(self.cfg.get("ui", "size_main", 32)) + step))
        size_sub = max(12, size_main - 7)
        self.cfg.hot_update({"ui.size_main": size_main, "ui.size_sub": size_sub})
        self._apply_fonts()
        self._fit()
        event.accept()

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        menu.addAction("回到屏幕底部", self.move_to_bottom)
        menu.addAction("点击穿透：关闭" if self._click_through else "点击穿透：开启",
                       lambda: self.set_click_through(not self._click_through))
        menu.addAction("字号 +2", lambda: self._bump(2))
        menu.addAction("字号 -2", lambda: self._bump(-2))
        menu.addAction("隐藏", self.hide_overlay)
        menu.exec(event.globalPos())

    def _bump(self, step: int) -> None:
        size_main = max(14, min(72, int(self.cfg.get("ui", "size_main", 32)) + step))
        self.cfg.hot_update({"ui.size_main": size_main,
                             "ui.size_sub": max(12, size_main - 7)})
        self._apply_fonts()
        self._fit()

    def closeEvent(self, event) -> None:
        event.ignore()
        self.hide()
