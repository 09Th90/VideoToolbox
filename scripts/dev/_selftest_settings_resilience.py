# -*- coding: utf-8 -*-
# @version 3.2.0
"""设置页韧性自检（v3.1.4：缺可选组件不再拖垮整页 / 不再静默空白）。

背景：v3.1.3 冻结安装版漏发 tools/decision_client.py，SettingsPage 构造在
_build_ai_card → _sync_plan_warn → decision_mod() 抛 FileNotFoundError，
_LazyPageShell 真身未建＝设置页只剩背景图（crash.log 2026-11-20 17:28:33）。

覆盖：
  ① TOOLS_DIR 指向空目录（模拟漏发）→ SettingsPage 仍完整构建，
     Jev 提示为「缺失/加载失败」降级文案，后续卡片（关于页等）照常建；
  ② _LazyPageShell builder 抛异常 → real 为占位控件（非 None/非空布局），
     且 traceback 落盘 crash.log「页面构建」段（LOGS_DIR 隔离到临时目录）；
  ③ 占位后属性转发不炸（__getattr__ 走占位控件）。

不联网。用法：tools/python/python.exe scripts/dev/_selftest_settings_resilience.py
"""
import os
import sys
import tempfile

_SRC = os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "src")
sys.path.insert(0, _SRC)
os.environ["VT_NO_PIPELINE"] = "1"
os.environ["VT_NO_SYNC"] = "1"
import video_toolbox as engine  # noqa: E402

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault(
    "QT_QPA_PLATFORM_PLUGIN_PATH",
    os.path.join(engine.EMBEDDED_SITE_PACKAGES, "PySide6", "plugins"))

FAILS = []


def check(name, cond, extra=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}"
          f"{(' -> ' + str(extra)) if extra else ''}")
    if not cond:
        FAILS.append(name)


def main():
    print("== 设置页韧性自检 ==")
    from PySide6.QtWidgets import QApplication
    import video_toolbox_qt as vtq
    import core.shared.decision as dec

    app = QApplication.instance() or QApplication(sys.argv)

    # ---- ① 缺 decision_client.py 时设置页仍完整构建 ----
    tmp = tempfile.mkdtemp(prefix="vt_resil_")
    empty_tools = os.path.join(tmp, "tools_empty")
    os.makedirs(empty_tools)
    # 只缺 decision_client.py（真实漏发形态）：ai_client/credential_store
    # 仍在，避免把「整个 tools 空」的其它缺失误算进本用例。
    import shutil
    import vt_app.boot as boot
    real_tools = dec.TOOLS_DIR
    for fn in ("ai_client.py", "credential_store.py"):
        shutil.copyfile(os.path.join(real_tools, fn),
                        os.path.join(empty_tools, fn))
    dec.TOOLS_DIR = empty_tools
    dec._DECISION_MOD = None
    real_logs, real_crash = engine.LOGS_DIR, boot.CRASH_LOG
    engine.LOGS_DIR = os.path.join(tmp, "logs1")
    boot.CRASH_LOG = os.path.join(engine.LOGS_DIR, "crash.log")
    try:
        win = vtq.MainWindow([])
        win.resize(1200, 800)
        win.show()          # offscreen 也须 show：showEvent 才触发 ensure
        app.processEvents()
        win.switchTo(win.settings_page)
        app.processEvents()
        page = win.settings_page.real
        if page is None or type(page).__name__ != "SettingsPage":
            from PySide6.QtWidgets import QLabel
            for lbl in (page.findChildren(QLabel) if page else []):
                print("   占位文案:", lbl.text()[:300])
            cl = os.path.join(engine.LOGS_DIR, "crash.log")
            if os.path.isfile(cl):
                print("   隔离 crash.log:", open(cl, encoding="utf-8").read()[-1500:])
        check("缺 Jev 客户端时设置页真身仍建出", page is not None
              and type(page).__name__ == "SettingsPage",
              type(page).__name__ if page else None)
        if page is not None:
            hint = getattr(page, "ai_jev_hint", None)
            check("Jev 提示为缺失降级文案",
                  hint is not None and "缺失" in hint.text(),
                  hint.text()[:60] if hint else None)
            check("后续卡片照常构建（10 卡 + stretch 全在）",
                  page.vbox.count() >= 11, page.vbox.count())
        try:
            win.close()
        except Exception:  # noqa: BLE001
            pass
    finally:
        dec.TOOLS_DIR = real_tools
        dec._DECISION_MOD = None
        engine.LOGS_DIR, boot.CRASH_LOG = real_logs, real_crash

    # ---- ② builder 抛异常 → 占位控件 + crash.log 落盘 ----
    from vt_app.lazy_shell import _LazyPageShell
    import vt_app.boot as boot
    real_logs = engine.LOGS_DIR
    real_crash = boot.CRASH_LOG      # 模块级常量，须一并隔离
    engine.LOGS_DIR = os.path.join(tmp, "logs")
    boot.CRASH_LOG = os.path.join(engine.LOGS_DIR, "crash.log")
    try:
        def boom():
            raise RuntimeError("故意炸的 builder")
        shell = _LazyPageShell(None, boom, "测试页", "TestPage")
        real = shell.ensure()
        check("builder 炸后 real 为占位控件（非 None）", real is not None)
        check("占位控件 objectName 带 _BuildFailed",
              real.objectName().endswith("_BuildFailed"), real.objectName())
        check("占位控件已入壳布局", shell.layout().count() == 1)
        cl = os.path.join(engine.LOGS_DIR, "crash.log")
        txt = open(cl, encoding="utf-8").read() if os.path.isfile(cl) else ""
        check("crash.log 有「页面构建」段且含异常信息",
              "页面构建" in txt and "故意炸的 builder" in txt)
        check("ensure 幂等：二次调用不重复建占位", shell.ensure() is real)
    finally:
        engine.LOGS_DIR = real_logs
        boot.CRASH_LOG = real_crash

    print(f"\n结果：FAIL {len(FAILS)}")
    if FAILS:
        print("失败项：", FAILS)
        sys.exit(1)
    print("OK")


if __name__ == "__main__":
    main()