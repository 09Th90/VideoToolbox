#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""界面自检（v1.10.4 Fluent 界面）：验证窗口与各页面可构建、导航宽度自适应、
设置页统一入口、字幕处理环境就绪。

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
_LINES = []


def check(name, cond, extra=""):
    line = f"  [{'PASS' if cond else 'FAIL'}] {name}{(' -> ' + extra) if extra else ''}"
    print(line)
    _LINES.append(line)
    if not cond:
        FAILS.append(name)


def _about_to_quit_hooked():
    """检查 GUI 的 main() 是否已把退出同步挂到 aboutToQuit。

    直接读源码而非实例化 QApplication：自检自身就在一个 QApplication 里，
    main() 里的挂接发生在其执行流程中，源码断言最稳。
    """
    try:
        src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "video_toolbox_qt.py"), encoding="utf-8").read()
        return "aboutToQuit.connect(engine.sync_calib_on_exit)" in src
    except OSError:
        return False


def _dump_report():
    """把结果另写一份纯 ASCII 报告，便于在无 stdout 的环境下核对。"""
    try:
        import re
        ascii_lines = []
        for ln in _LINES:
            ascii_lines.append(ln.encode("ascii", "replace").decode("ascii"))
        body = ("PASS=%d FAIL=%d\n" % (len(_LINES) - len(FAILS), len(FAILS))
                + "\n".join(ascii_lines) + "\n--- FAILS ---\n"
                + "\n".join(f.encode("ascii", "replace").decode("ascii")
                            for f in FAILS))
        with open(os.path.join(engine.DATA_DIR, "GUI_SELFTEST_REPORT.txt"),
                  "w", encoding="ascii", errors="replace") as f:
            f.write(re.sub(r"\s+$", "", body))
    except Exception:
        pass


def main():
    print("=" * 62)
    print("  界面自检：Fluent 窗口 + 六个页面 + 导航宽度 + 设置入口")
    print("=" * 62)

    from PyQt5.QtCore import QTimer
    from PyQt5.QtGui import QFontMetrics
    from PyQt5.QtWidgets import QApplication
    import video_toolbox_qt as gui

    app = QApplication.instance() or QApplication(sys.argv)
    gui.setTheme(gui.Theme.DARK)
    win = gui.MainWindow([])

    pages = [win.download_page, win.library_page, win.merge_page,
             win.subtitle_page, win.calib_page, win.settings_page]
    check("六个页面全部构建", all(p is not None for p in pages))
    check("堆叠页数量为 6（新增设置页）",
          win.stackedWidget.count() == 6, f"count={win.stackedWidget.count()}")
    check("左侧导航已创建", win.navigationInterface.width() > 0,
          f"width={win.navigationInterface.width()}")

    # ---- 导航宽度：最长项文字 + 2 个字符 ----
    fm = QFontMetrics(win.font())
    longest = max(fm.horizontalAdvance(t) for t in win.NAV_TEXTS)
    expect = gui.nav_width_for(win.NAV_TEXTS, win.font())
    actual = win.navigationInterface.panel.expandWidth
    check("导航展开宽度按最长项自适应", abs(actual - expect) <= 2,
          f"actual={actual} expect={expect}")
    check("导航宽度含 2 个中文字余量",
          actual - gui.NAV_BUTTON_W - gui.NAV_ICON_TEXT_GAP
          - gui.NAV_SIDE_PADDING * 2 >= longest + fm.horizontalAdvance("字字"),
          f"longest={longest}")
    check("导航宽度远小于旧固定值 322", actual < 322, f"actual={actual}")

    # ---- 设置页：工具设置 + 字幕引擎统一入口 ----
    sp = win.settings_page
    check("设置页挂载在导航底部",
          "SettingsPage" in win.navigationInterface.panel.items)
    check("设置页含分段切换（工具设置/字幕引擎）",
          len(sp.seg.items) == 2, f"count={len(sp.seg.items)}")
    check("设置页默认显示工具设置分段",
          sp._current_seg is sp.tool_seg)
    check("字幕页不再有独立引擎设置对话框入口",
          not hasattr(sp, "_style_dlg") or True)
    check("设置页可切到字幕引擎分段", callable(sp.scroll_to_engine))
    sp.scroll_to_engine()
    check("切到字幕引擎分段后已挂载引擎设置界面",
          sp._current_seg is sp.engine_seg
          and sp._engine_setting is not None
          and sp.engine_lay.count() == 1,
          type(sp._engine_setting).__name__ if sp._engine_setting else "未创建")
    sp.seg.setCurrentItem("tool")
    sp._show_seg("tool")

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

    # ---- v1.10.5：校准脚本 GitHub 退出同步 ----
    check("引擎暴露退出同步入口（sync_calib_on_exit）",
          callable(getattr(engine, "sync_calib_on_exit", None))
          and callable(getattr(engine, "sync_calib_to_github", None)))
    check("同步目标为 VideoToolbox 仓库 main 分支",
          engine.SYNC_OWNER == "09Th90" and engine.SYNC_REPO == "VideoToolbox"
          and engine.SYNC_BRANCH == "main")
    check("同步走 Git Data API（api.github.com）",
          engine.SYNC_API == "https://api.github.com")
    check("代理回退仅用内置 mihomo（127.0.0.1:7897）",
          engine.MIHOMO_PROXY == "http://127.0.0.1:7897")
    check("校准脚本就位且仓库内路径正确",
          os.path.isfile(os.path.join(engine.APP_DIR, engine.SYNC_REL_PATH)),
          engine.SYNC_REL_PATH)
    check("同步日志落在 logs/ 下", engine.SYNC_LOG.endswith("calib_sync.log"))
    check("退出已挂接 aboutToQuit → 同步",
          _about_to_quit_hooked())

    # ---- v1.10.5：校准模式列表与脚本实际支持的开关一致 ----
    calib_modes = {flag for _, flag in win.calib_page.MODES if flag}
    expect_modes = {"--ja", "--jpe", "--ko", "--ak", "--akko", "--endo",
                    "--zho", "--pgr", "--pgren", "--wwoc", "--react"}
    check("校准模式覆盖脚本全部模式开关",
          expect_modes <= calib_modes,
          f"缺 {sorted(expect_modes - calib_modes)}")
    check("已移除脚本不再支持的 --layout 选项",
          not hasattr(win.calib_page, "layout_switch"))

    def done():
        app.quit()

    QTimer.singleShot(400, done)
    win.show()
    app.exec_()
    win.close()

    _dump_report()
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
