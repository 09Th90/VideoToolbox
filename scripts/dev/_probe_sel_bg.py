# -*- coding: utf-8 -*-
# @version 1.18.0
"""探针：QTableWidgetItem 的 BackgroundRole 到底怎么才算"清干净"。

背景：qfluentwidgets 的 TableItemDelegate.paint() 里
    if index.data(Qt.BackgroundRole): painter.setBrush(那个值)
    else: painter.setBrush(QColor(c, c, c, alpha))   # 隔行/hover/选中底色
所以只要 BackgroundRole 还剩一个**有效值**（哪怕是 NoBrush），该格的
隔行色与 hover 效果就永久丢失 → 取消选中后行会变成"一块空白"。

要验三件事：
  1) setBackground(QColor) 确实写入了角色；
  2) setBackground(Qt.NoBrush) 是否**没有**清掉角色（我怀疑它是坑）；
  3) setData(role, QVariant()) 能否把角色真正删成 invalid。
用法：tools/python/python.exe scripts/dev/_probe_sel_bg.py
"""
import os
import sys

_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "src")
sys.path.insert(0, _SRC)
os.environ["VT_NO_PIPELINE"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import video_toolbox as engine  # noqa: E402

os.environ.setdefault(
    "QT_QPA_PLATFORM_PLUGIN_PATH",
    os.path.join(engine.EMBEDDED_SITE_PACKAGES, "PyQt5", "Qt5", "plugins"))

from PyQt5.QtCore import Qt, QVariant  # noqa: E402
from PyQt5.QtGui import QBrush, QColor  # noqa: E402
from PyQt5.QtWidgets import QApplication, QTableWidgetItem  # noqa: E402


def _state(item):
    """返回 (是否被判为真, repr) —— delegate 用的就是这个真值判断。"""
    v = item.data(Qt.BackgroundRole)
    return (bool(v), repr(v))


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    item = QTableWidgetItem("x")

    print("初始:", _state(item))

    item.setBackground(QColor(0, 200, 119, 60))
    print("setBackground(QColor):", _state(item))

    item.setBackground(QBrush(Qt.NoBrush))
    print("setBackground(QBrush(NoBrush)):", _state(item),
          "  <-- True 就说明 delegate 会跳过隔行/hover 底色")

    item.setData(Qt.BackgroundRole, QVariant())
    print("setData(role, QVariant()):", _state(item))

    # 复查：清掉之后重新选中，delegate 的绘制路径能恢复正常
    item.setBackground(QColor(0, 200, 119, 60))
    item.setData(Qt.BackgroundRole, QVariant())
    print("重选后再清:", _state(item))
    del app


if __name__ == "__main__":
    main()