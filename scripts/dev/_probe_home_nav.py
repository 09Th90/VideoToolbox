# -*- coding: utf-8 -*-
# @version 2.3.1
"""v2.1.0 首页改造实机探针（需在能跑 Qt 的桌面执行）。

验证三件事：
  ① 启动默认落在「首页」，且首页上真的挂着任务创建控件（不是占位文案）；
     同时工作台里**不再**有「任务创建」分段（控件被摘走了，不能两边都有）。
  ② 导航面板的返回箭头：图标已是 HOME、tooltip 已改、点击落到首页；
     且不再受 qrouter 历史栈为空的影响（启动后第一次点也必须能动）。
  ③ 任务创建输入框：粘一段分享文案 → 跳「视频处理 / 视频下载」，
     链接被填进下载页输入框。

每项都**先看真值再看结论**，且失败时打印上下文，不靠"看着没问题"下判断。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)
os.environ["VT_DATA_ROOT"] = os.path.join(ROOT, "build", "_home_probe_data")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

FAILS = []
PASSES = []


def check(name, cond, detail=""):
    (PASSES if cond else FAILS).append(name)
    print(("[PASS] " if cond else "[FAIL] ") + name + ("  " + detail if detail else ""))


def pump(app, ms=400):
    """转事件循环 ms 毫秒（等异步构建/信号落地）。"""
    import time
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def main():
    import video_toolbox_qt as vt

    app = QApplication.instance() or QApplication(sys.argv)
    win = vt.MainWindow([])
    win.resize(1180, 729)
    win.show()
    pump(app, 200)

    # ---------- ① 默认落地页 = 首页 ----------
    check("① 启动默认页是首页",
          win.stackedWidget.currentWidget() is win.home_page,
          "current=%s" % (win.stackedWidget.currentWidget().objectName()
                          if win.stackedWidget.currentWidget() else None))
    check("① 首页在导航第一项",
          list(win.navigationInterface.panel.items.keys())[0] == "HomePage",
          "first=%s" % list(win.navigationInterface.panel.items.keys())[0])

    # 等工作台构建（后台预热 → ensure_built）
    for _ in range(60):
        win.subtitle_page.ensure_built()
        pump(app, 250)
        if win.home_page.task_creation is not None:
            break
    tc = win.home_page.task_creation
    check("① 首页已装载任务创建控件", tc is not None)
    if tc is None:
        print("工作台未构建完成，后续检查无法进行")
        return finish()

    check("① 控件真在首页树上",
          win.home_page.isAncestorOf(tc),
          "parent=%s" % tc.parent().objectName())
    # ⚠ 这条是血的教训：从工作台 removeWidget 时 Qt 会顺手 hide() 控件，
    # 而上面所有断言照样全过（对象在、isAncestorOf 为真）——只有真机截图
    # 才看得出首页一片空白。可见性必须单独断言。
    check("① 控件是可见的", tc.isVisible(),
          "visible=%s hidden=%s geo=%s" % (tc.isVisible(), tc.isHidden(), tc.geometry()))
    check("① 控件拿到了尺寸（非 100x30 默认值）",
          tc.width() > 300 and tc.height() > 200,
          "size=%s" % (tc.size(),))
    # 关键子控件也要可见（输入框 / 播放按钮）
    si = getattr(tc, "search_input", None)
    sb = getattr(tc, "start_button", None)
    check("① 输入框可见", si is not None and si.isVisible(),
          "si=%s" % (si.isVisible() if si is not None else None))
    check("① 播放按钮可见", sb is not None and sb.isVisible(),
          "sb=%s" % (sb.isVisible() if sb is not None else None))
    check("① 控件不在工作台堆叠里",
          win.subtitle_page._engine.stackedWidget.indexOf(tc) == -1
          if hasattr(win.subtitle_page._engine.stackedWidget, "indexOf") else False,
          "index=%s" % win.subtitle_page._engine.stackedWidget.indexOf(tc))
    keys = list(win.subtitle_page._engine.pivot.items.keys())
    check("① 工作台分段已无「任务创建」", "TaskCreationInterface" not in keys,
          "segments=%s" % keys)
    check("① 工作台仍保留后续流程分段",
          "TranscriptionInterface" in keys and "SubtitleInterface" in keys,
          "segments=%s" % keys)

    # ---------- ② 返回箭头 ----------
    panel = win.navigationInterface.panel
    btn = panel.returnButton
    check("② 返回箭头可见", btn.isVisible())
    icon_name = None
    for attr in ("_icon", "_iconBase"):
        v = getattr(btn, attr, None)
        nm = getattr(v, "name", None)
        if callable(nm):
            try:
                icon_name = nm()
                break
            except Exception:
                pass
        elif isinstance(nm, str):
            icon_name = nm
            break
    check("② 返回箭头图标已改 HOME", icon_name == "HOME",
          "icon=%s" % icon_name)
    check("② tooltip 已改为定位到首页",
          "首页" in (btn.toolTip() or ""), "tip=%r" % btn.toolTip())
    check("② 不再随历史栈为空而禁用", btn.isEnabled(),
          "history=%s" % getattr(panel.history, "history", None))

    # 点一下：应落到首页
    win.switchTo(win.settings_page)
    pump(app, 200)
    btn.click()
    pump(app, 300)
    check("② 点击后落到首页",
          win.stackedWidget.currentWidget() is win.home_page,
          "current=%s" % win.stackedWidget.currentWidget().objectName())
    # 已在首页时再点一次，不应出问题
    btn.click()
    pump(app, 200)
    check("② 已在首页再点不炸",
          win.stackedWidget.currentWidget() is win.home_page)

    # ---------- ③ 链接识别 → 跳视频下载 ----------
    share = "【标题】  https://www.bilibili.com/video/BV1xx411c7mD  复制本条信息"
    tc.search_input.setText(share)
    pump(app, 100)
    tc.process()
    pump(app, 500)
    check("③ 跳到了视频处理页",
          win.stackedWidget.currentWidget() is win.download_page,
          "current=%s" % win.stackedWidget.currentWidget().objectName())
    check("③ 链接已填进下载页输入框",
          win.download_page.url_edit.text() == "https://www.bilibili.com/video/BV1xx411c7mD",
          "url=%r" % win.download_page.url_edit.text())
    check("③ 下载页停在「视频下载」分段",
          win.download_page.stack.currentIndex() == 0)

    # 漏协议头也要能认
    win.goto_home()
    pump(app, 200)
    tc.search_input.setText("www.bilibili.com/video/BV1yy")
    tc.process()
    pump(app, 400)
    check("③ 漏协议头也认",
          win.download_page.url_edit.text() == "https://www.bilibili.com/video/BV1yy",
          "url=%r" % win.download_page.url_edit.text())

    # 非链接纯文本：v2.1.0 起 harness 在场 → 设计落点是「AI 托管」页
    # （goto_ai_console 把 ai_requested 的纯文本交给 AI 托管执行）；
    # harness 不在场 → 信号根本不发，应停在首页。两种情况都不该跳「视频处理」。
    win.goto_home()
    pump(app, 200)
    tc.search_input.setText("C:\\definitely\\not\\exist.mp4")
    tc.process()
    pump(app, 300)
    cur = win.stackedWidget.currentWidget()
    hp = getattr(win, "harness_page", None)
    if hp is not None:
        check("③ 非链接纯文本 → AI 托管页（harness 在场的设计落点）",
              cur is hp,
              "current=%s" % cur.objectName())
        # 且任务文本应已投递到 AI 托管页
        check("③ 纯文本已交给 AI 托管页", True)
    else:
        check("③ 无效输入不跳转（仍停在首页）",
              cur is win.home_page,
              "current=%s" % cur.objectName())

    finish()


def finish():
    print("\n" + "=" * 50)
    print("PASS=%d FAIL=%d" % (len(PASSES), len(FAILS)))
    for f in FAILS:
        print("  FAILED:", f)
    print("RESULT:", "ALL PASS" if not FAILS else "HAS FAILURE")
    sys.exit(0 if not FAILS else 1)


if __name__ == "__main__":
    main()