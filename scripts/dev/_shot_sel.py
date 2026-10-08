# -*- coding: utf-8 -*-
"""截图：音画合并「自动配对」子页的选中态（浅色 / 深色各一张）。

用途：肉眼确认「选中的行看得见」——qfluentwidgets 的 delegate 默认只给
选中行左侧画一道细 indicator，浅色主题下底色几乎不可辨；本次补了
BackgroundRole 铺底，截图是最直接的验收手段。

用法：tools/python/python.exe scripts/dev/_shot_sel.py [输出目录]
"""
import os
import sys

_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "src")
sys.path.insert(0, _SRC)
os.environ["VT_NO_PIPELINE"] = "1"
import video_toolbox as engine  # noqa: E402

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault(
    "QT_QPA_PLATFORM_PLUGIN_PATH",
    os.path.join(engine.EMBEDDED_SITE_PACKAGES, "PyQt5", "Qt5", "plugins"))

import ui_theme  # noqa: E402


def _pairs(n=6):
    out = []
    for i in range(n):
        mt = "perfect" if i % 3 else "name_only"
        out.append((f"video{i}.mp4", f"video{i}.m4a", "m4a", mt, 0.05 + i * 0.01,
                    f"video{i}.srt", None))
    return out


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "_sel_shots")
    os.makedirs(out_dir, exist_ok=True)

    from PyQt5.QtWidgets import QApplication
    from PyQt5.QtCore import Qt
    from PyQt5.QtTest import QTest
    import video_toolbox_qt as vtq

    app = QApplication.instance() or QApplication(sys.argv)

    for mode, tag in (("light", "light"), ("dark", "dark")):
        ui_theme.set_theme_mode(mode)
        win = vtq.MainWindow([])
        mp = win.merge_page
        win.resize(1180, 860)
        win.show()
        mp.on_scan_done(_pairs(6), ([], [], []), (6, 6, 0, 6, 0), None)
        app.processEvents()

        # 选 3 行（分散在不同位置，模拟真实多选）
        mp.table.resize(1080, 260)
        vp = mp.table.viewport()
        for r, mod in ((0, Qt.NoModifier), (2, Qt.ControlModifier),
                       (4, Qt.ControlModifier)):
            rect = mp.table.visualItemRect(mp.table.item(r, 0))
            QTest.mouseClick(vp, Qt.LeftButton, mod, rect.center())
        app.processEvents()

        # 滚到「配对结果」卡片：整页截图太长，只截表格 + 按钮那一段
        mp.table.scrollToItem(mp.table.item(0, 0))
        app.processEvents()
        out = os.path.join(out_dir, f"sel_{tag}.png")
        _grab_pair(mp, out)
        print(f"{mode}: 已选 {mp.selected_rows()} -> {out}")

        # 未选中态也存一张（对照）
        mp.table.clearSelection()
        app.processEvents()
        out2 = os.path.join(out_dir, f"nosel_{tag}.png")
        _grab_pair(mp, out2)
        print(f"     未选中态 -> {out2}")
        win.close()


def _grab_pair(mp, out):
    """只截「配对结果」卡片（含表格 + 全选/清除按钮），整页图太长看不清选中底色。

    从 table 一路上溯到滚动区内容层（card() 建的 UICard 的父就是它），
    直接 grab 那个卡片自身——免去 window/滚动区坐标换算。
    """
    w = mp.table.parentWidget()
    while w is not None and w.parentWidget() is not mp.shell.content_lay \
            .parentWidget():
        w = w.parentWidget()
    return (w if w is not None else mp.table).grab().save(out)


if __name__ == "__main__":
    main()