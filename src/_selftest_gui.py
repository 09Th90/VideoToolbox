#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""界面自检（v1.10.1 Fluent 界面）：验证窗口与各页面可构建、字幕处理环境就绪。

不联网、不下载视频。运行：python _selftest_gui.py
需要图形界面（本机运行）；用内置运行时 tools/python 执行。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import video_toolbox as engine

os.environ.setdefault(
    "QT_QPA_PLATFORM_PLUGIN_PATH",
    os.path.join(engine.EMBEDDED_SITE_PACKAGES, "PyQt5", "Qt5", "plugins"))

FAILS = []


def check(name, cond, extra=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}{(' -> ' + extra) if extra else ''}")
    if not cond:
        FAILS.append(name)


def main():
    print("=" * 62)
    print("  界面自检：Fluent 窗口 + 五个页面 + 字幕处理环境")
    print("=" * 62)

    from PyQt5.QtCore import QTimer
    from PyQt5.QtWidgets import QApplication
    import video_toolbox_qt as gui

    app = QApplication.instance() or QApplication(sys.argv)
    gui.setTheme(gui.Theme.DARK)
    win = gui.MainWindow([])

    pages = [win.download_page, win.library_page, win.merge_page,
             win.subtitle_page, win.calib_page]
    check("五个页面全部构建", all(p is not None for p in pages))
    check("堆叠页数量为 5（B站投稿板块已移除）",
          win.stackedWidget.count() == 5, f"count={win.stackedWidget.count()}")
    check("左侧导航已创建", win.navigationInterface.width() > 0,
          f"width={win.navigationInterface.width()}")

    check("下载页含任务表/画质列表/日志",
          win.download_page.task_table.columnCount() == 6
          and win.download_page.qlist.count() == 0
          and bool(win.download_page.log.text))
    check("合并页含配对表", win.merge_page.table.columnCount() == 5)
    check("视频库默认目录已填回", bool(win.library_page.dir_edit.text()),
          win.library_page.dir_edit.text())

    sub = win.subtitle_page
    from PyQt5.QtGui import QShowEvent
    sub.showEvent(QShowEvent())   # 首次显示触发引擎界面内嵌
    check("字幕引擎界面已内嵌（非独立窗口）",
          sub._engine is not None and sub.host_lay.count() == 1,
          type(sub._engine).__name__ if sub._engine else "未创建")
    tc = getattr(sub._engine, "task_creation_interface", None) if sub._engine else None
    check("品牌水印与捐助入口已隐藏",
          tc is not None and tc.info_label.isHidden()
          and tc.donate_button.isHidden())
    try:
        import videocaptioner  # noqa: F401
        vc_ok = True
    except Exception:
        vc_ok = False
    check("字幕引擎随 exe 内嵌（可导入）", vc_ok)
    check("第三方组件许可与来源声明随包",
          os.path.isfile(engine.VC_LICENSE_FILE)
          and os.path.isfile(engine.VC_SOURCE_FILE))

    check("投稿板块代码已移除（引擎无 UPLOADER_*）",
          not any(a.startswith("UPLOADER_") for a in dir(engine)))
    check("AI 字幕语言识别仍可用（tools/ai_client.py 就位）",
          os.path.isfile(os.path.join(engine.TOOLS_DIR, "ai_client.py")))
    check("配置目录长期记忆生效", os.path.isdir(engine.DEFAULT_DOWNLOAD_DIR))

    def done():
        app.quit()

    QTimer.singleShot(400, done)
    win.show()
    app.exec_()
    win.close()

    print("\n" + "=" * 62)
    if FAILS:
        print(f"  结果：{len(FAILS)} 项失败")
        for f in FAILS:
            print(f"    - {f}")
        print("=" * 62)
        return 1
    print("  结果：全部通过")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
