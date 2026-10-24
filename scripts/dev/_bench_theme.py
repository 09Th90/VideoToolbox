# -*- coding: utf-8 -*-
# @version 2.7.0
"""主题色切换全量重刷基准（2026-10-20 性能优化验收用）。

模拟稳态 GUI 的样式表注册面：N 个已注册控件（一半藏在不可见堆叠页里，
贴近主窗口 9 页结构——stackedWidget 持全部页面、只露当前页），计时
setThemeColor 一次全量 updateStyleSheet 的端到端耗时。
VT_QSS_NOCACHE=1 关掉文件缓存 + 渲染 memo，作对照组（≈ 优化前行为）。

用法（程序根为 cwd）：
    tools\\python\\python.exe scripts\\dev\\_bench_theme.py [控件数=400]
    VT_QSS_NOCACHE=1 tools\\python\\python.exe scripts\\dev\\_bench_theme.py 400
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "src"))


def main():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import (QApplication, QPushButton, QStackedWidget,
                                   QWidget, QVBoxLayout)
    from PySide6.QtGui import QColor
    import vt_fluent as vt

    n = int(sys.argv[1]) if len(sys.argv) > 1 else 400
    app = QApplication.instance() or QApplication([])
    vt.setTheme(vt.Theme.DARK)

    # 稳态注册面：与真实控件族同一注册路径（setStyleSheet → styleSheetManager）
    host = QWidget()
    host.setLayout(QVBoxLayout(host))
    stack = QStackedWidget()
    host.layout().addWidget(stack)
    visible_page, hidden_page = QWidget(), QWidget()
    vp_layout, hp_layout = QVBoxLayout(visible_page), QVBoxLayout(hidden_page)
    stack.addWidget(visible_page)      # index 0：当前可见
    stack.addWidget(hidden_page)       # index 1：压栈不可见
    stack.setCurrentWidget(visible_page)
    for i in range(n):
        btn = QPushButton(f"bench-{i}", visible_page if i % 2 else hidden_page)
        vt.setStyleSheet(btn, vt.FluentStyleSheet.BUTTON)
        (vp_layout if i % 2 else hp_layout).addWidget(btn)
    # 普通 Qt 控件（真实界面里的一百多个 QLineEdit/QComboBox/QSpinBox/
    # QProgressBar——它们的主题色走逐控件小表，见 ui_theme.refresh_plain_accent）
    from PySide6.QtWidgets import (QComboBox, QLineEdit, QProgressBar,
                                   QSpinBox)
    plain = 0
    for i in range(max(1, n // 8)):
        page, lay = ((visible_page, vp_layout) if i % 2
                     else (hidden_page, hp_layout))
        le = QLineEdit(f"plain-{i}", page)
        lay.addWidget(le)
        cb = QComboBox(page)
        cb.addItems(["a", "b"])
        lay.addWidget(cb)
        sp = QSpinBox(page)
        lay.addWidget(sp)
        pb = QProgressBar(page)
        lay.addWidget(pb)
        plain += 4
    # FLUENT_WINDOW 合并 QSS 套 stackedWidget（与 FluentWindow 同一路径）
    vt.FluentStyleSheet.FLUENT_WINDOW.apply(stack)
    app.processEvents()
    registered = len(list(vt.styleSheetManager.items()))
    print(f"[bench] registered widgets: {registered} (want {n + 1})"
          f" + plain-Qt x{plain}")

    def timed(color):
        t = time.perf_counter()
        vt.setThemeColor(QColor(color))
        app.processEvents()
        return time.perf_counter() - t

    warm = timed("#45C877")     # 预热：填文件缓存/memo 的一阶成本
    rounds = [timed(c) for c in ("#3B82F6", "#EC4899", "#F59E0B", "#8B5CF6")]
    nocache = "on" if os.environ.get("VT_QSS_NOCACHE") else "off"
    print(f"[bench] VT_QSS_NOCACHE={nocache}  warm-up={warm * 1000:.1f}ms  "
          f"per-change: " + " ".join(f"{r * 1000:.1f}ms" for r in rounds))
    print(f"[bench] min={min(rounds) * 1000:.1f}ms  "
          f"avg={sum(rounds) / len(rounds) * 1000:.1f}ms")

    # 同值跳过：再设一次同色应几乎瞬时（渲染 memo 命中 + Qt 侧不重解析）
    same = timed("#8B5CF6")
    print(f"[bench] same-color re-set: {same * 1000:.2f}ms")

    # 端到端（ui_theme.set_accent，含 app 级 QSS + 页面重绘），跑完还原
    try:
        import ui_theme
        old = ui_theme.get_accent()
        for c in ("#EF4444", "#10B981", "#6366F1"):
            t = time.perf_counter()
            ui_theme.set_accent(c)
            app.processEvents()
            print(f"[bench] ui_theme.set_accent({c}) = "
                  f"{(time.perf_counter() - t) * 1000:.1f}ms")
        ui_theme.set_accent(old)
        print(f"[bench] ui_custom.json accent restored to {old}")
    except Exception as e:  # noqa: BLE001 —— 基准失败不影响主流程判断
        print(f"[bench] ui_theme round skipped: {e}")


if __name__ == "__main__":
    main()
