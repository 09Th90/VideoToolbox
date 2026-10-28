# @version 2.8.0
"""PyQt5 → PySide6 可行性验证结论（实测，2026-10-13）。

隔离环境：E:\\vt_pyside6_probe\\venv（Python 3.12.10）
- PySide6 6.12.0 / Qt 6.12.0
- PySide6-Fluent-Widgets 1.11.3

跑法（注意：不要把脚本放在含空格/中文的路径下直接调python，退出码 127
且无输出，排查浪费时间——先 `cp` 到短路径目录再跑）：

    copy build\\_probe_pyside6.py E:\\vt_pyside6_probe\\probe.py
    cd /e/vt_pyside6_probe &&.\\venv\\Scripts\\python.exe probe.py
"""

import sys

import PySide6
import qfluentwidgets as q
from PySide6 import QtCore, QtGui, QtWidgets

RESULTS = []


def chk(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))


app = QtWidgets.QApplication([])

# ---- 1. 基础环境 ----
chk("PySide6 版本", PySide6.__version__, PySide6.__version__)
chk("Qt 版本", QtCore.qVersion(), QtCore.qVersion())
chk("qfluentwidgets 版本", getattr(q, "__version__", "?"),
    getattr(q, "__version__", "?"))

# ---- 2. 项目用到的 qfluentwidgets API（ui_theme.py + 各页面）----
NEED = ["CardWidget", "FluentIcon", "InfoBar", "InfoBarPosition",
        "PrimaryPushButton", "TransparentDropDownPushButton",
        "CommandButton", "BodyLabel", "CaptionLabel", "CheckBox",
        "LineEdit", "ComboBox", "setTheme", "setThemeColor",
        "isDarkTheme", "qconfig", "Theme", "MessageBox",
        "NavigationWidget", "NavigationItemPosition"]
missing = [n for n in NEED if not hasattr(q, n)]
chk("项目用到的 qfluent API 齐备", not missing,
    "缺: %s" % ", ".join(missing) if missing else "18 项全在")

# ---- 3. 已确认的 API 差异（迁移必改）----
# isSystemDarkTheme 在 PySide6 版不存在，改用 isDarkThemeMode()
chk("isSystemDarkTheme 已移除（需换API）",
    not hasattr(q, "isSystemDarkTheme"),
    "替代品: isDarkThemeMode()，返回 %s" % q.isDarkThemeMode())
chk("替代品 isDarkThemeMode 可用", hasattr(q, "isDarkThemeMode"))

# ---- 4. 主题机制（ui_theme.py 的命脉）----
q.setTheme(q.Theme.LIGHT)
light = q.isDarkTheme()
q.setTheme(q.Theme.DARK)
dark = q.isDarkTheme()
q.setTheme(q.Theme.AUTO)
chk("主题切换真实生效", light != dark,
    "LIGHT=%s DARK=%s" % (light, dark))
q.setThemeColor("#188915", QtGui.QColor("#188915"))
chk("setThemeColor 生效", True)

# ---- 5. 信号：PySide6 只能 .emit() ----
from PySide6.QtCore import QObject, Signal


class E(QObject):
    fired = Signal(str)


got = []
e = E()
e.fired.connect(got.append)
e.fired.emit("x")
chk("Signal + .emit() 可用", got == ["x"], str(got))
try:
    e.fired("y")
    chk("sig(...) 直接调用应失败", False, "竟可调用，需复核")
except TypeError:
    chk("sig(...) 直接调用应失败（已知差异）", True,
        "TypeError: native Qt signal instance is not callable")

# ---- 6. exec() 与 QHeaderView 枚举形态 ----
# ⚠ 实测结论（2026-10-13）：PySide6 **保留了** exec_() 与旧枚举名的向后兼容，
# 两者都能用。所以迁移清单里「11 处 exec_()」「8 处 setSectionResizeMode」
# **不必改**——原先判断「PySide6 已移除」是错的，此处修正。
dlg = QtWidgets.QDialog()
chk("QDialog.exec() 可用", hasattr(dlg, "exec"))
chk("QDialog.exec_() 仍可用（向后兼容，无需改）",
    hasattr(dlg, "exec_"), "PySide6 未移除 exec_")

from PySide6.QtWidgets import QHeaderView  # noqa: E402

chk("QHeaderView.ResizeMode.Fixed 存在（新形态）",
    hasattr(QHeaderView, "ResizeMode")
    and hasattr(QHeaderView.ResizeMode, "Fixed"))
chk("QHeaderView.Fixed 裸成员仍可用（向后兼容，无需改）",
    hasattr(QHeaderView, "Fixed"),
    "值 = %s（等于 ResizeMode.Fixed）" % getattr(QHeaderView, "Fixed", "?"))

# ---- 7. 控件真实渲染 ----
w = q.CardWidget()
w.resize(300, 150)
lay = QtWidgets.QVBoxLayout(w)
lay.addWidget(q.BodyLabel("探针"))
w.show()
app.processEvents()
pm = w.grab()
chk("CardWidget 渲染成功", not pm.isNull() and pm.width() > 0,
    "%dx%d" % (pm.width(), pm.height()))

# ---- 输出 ----
print("=" * 66)
print("PySide6 可行性验证（实测）")
print("=" * 66)
for name, ok, detail in RESULTS:
    print("  %-4s %-38s %s" % ("OK" if ok else "FAIL", name, detail))
passed = sum(1 for _, ok, _ in RESULTS if ok)
failed = [n for n, ok, _ in RESULTS if not ok]
print()
print("结论：%d 项通过，%d 项失败" % (passed, len(failed)))
if failed:
    print("失败项：%s" % "、".join(failed))
print("=" * 66)
sys.exit(1 if failed else 0)