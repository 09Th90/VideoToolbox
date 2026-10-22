# -*- coding: utf-8 -*-
# @version 2.5.4
"""安装版三处缺陷的源码侧回归探针（v2.4.1 热修）。

断言：
  A. FluentIcon.COPY 能出图（ART 有内嵌艺术字），不再抛 RuntimeError；
  B. AI 托管页可构建、可重绘（「复制命令」按钮真实存在于页面树上）；
  C. 跨屏收敛 lambda 与 StyleSheetManager 析构 lambda 都能被调用（不吃 arity）。
"""
import os
import shutil
import sys
import time
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
os.environ["VT_NO_SYNC"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ["VT_DATA_ROOT"] = os.path.join(ROOT, "build", "_harness_probe_data")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

CAUGHT = []


def _hook(exc_type, exc, tb):
    CAUGHT.append((exc_type, exc))
    print("!!! EXC: %s: %s" % (exc_type.__name__, exc))
    traceback.print_exception(exc_type, exc, tb)


sys.excepthook = _hook

FAILS = []


def check(name, cond, extra=""):
    print(("[PASS] " if cond else "[FAIL] ") + name + (("  " + str(extra)) if extra else ""))
    if not cond:
        FAILS.append(name)


def pump(app, ms=800):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def main():
    import video_toolbox_qt as vt
    from vt_fluent import FluentIcon

    app = QApplication.instance() or QApplication(sys.argv)

    # 种子主题配置 + 启动主题初始化（2026-10-20 修复）：与 main() 一致，
    # 防 qconfig 停代码默认档与 ui_theme 轨错位渲染。
    _real_cfg = os.path.join(ROOT, "data", "ui_custom.json")
    _iso_cfg = os.path.join(os.environ["VT_DATA_ROOT"], "data", "ui_custom.json")
    if os.path.isfile(_real_cfg) and not os.path.isfile(_iso_cfg):
        os.makedirs(os.path.dirname(_iso_cfg), exist_ok=True)
        shutil.copy2(_real_cfg, _iso_cfg)
    import ui_theme
    ui_theme.apply_startup_theme(app)
    from vt_fluent import isDarkTheme, qconfig
    check("0 主题双轨同档", qconfig.theme == ui_theme.qtheme()
          and isDarkTheme() == ui_theme.is_dark())

    # ---- A. COPY 图标 ----
    try:
        pm = FluentIcon.COPY.icon().pixmap(16, 16)
        check("A1 FluentIcon.COPY 出图非空", not pm.isNull(), pm.size())
    except Exception as e:
        check("A1 FluentIcon.COPY 出图非空", False, repr(e))

    win = vt.MainWindow([])
    win.resize(1180, 729)
    win.show()
    pump(app, 600)

    # ---- B. AI 托管页 ----
    hp = getattr(win, "harness_page", None)
    check("B1 AI 托管页已创建", hp is not None)
    if hp is not None:
        win.switchTo(hp)
        pump(app, 900)
        btn = getattr(hp, "_fix_copy_btn", None)
        check("B2 部署引导卡有「复制命令」按钮", btn is not None)
        if btn is not None:
            # 触发一次真实重绘：paintEvent 里走 _drawIcon → FluentIcon.COPY
            btn.repaint()
            pump(app, 200)
            pm = btn.icon().pixmap(16, 16)
            check("B3 按钮图标可渲染", not pm.isNull())
        check("B4 页面可见", hp.isVisible() or win.stackedWidget.currentWidget() is hp)
        # 截图留证
        shot = os.path.join(ROOT, "build", "_harness_page_after_fix.png")
        win.grab().save(shot)
        print("    截图:", shot)

    # ---- C. 跨屏收敛 / 样式表析构 lambda ----
    win._schedule_screen_settle()
    pump(app, 1500)

    from vt_fluent._theme import styleSheetManager, StyleSheetFile
    src = StyleSheetFile(os.path.join(ROOT, "src", "vt_fluent", "_qss", "common.qss"))
    for _ in range(3):
        w = QWidget()
        styleSheetManager.register(src, w)
        app.processEvents()
        w.deleteLater()
        pump(app, 120)
    pump(app, 600)

    check("C1 无未捕获异常（COPY / arity / 其它）", not CAUGHT,
          "; ".join("%s: %s" % (t.__name__, e) for t, e in CAUGHT))

    QTimer.singleShot(50, app.quit)
    app.exec()
    print("=== FAILS=%d ===" % len(FAILS))
    for f in FAILS:
        print("  -", f)
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
