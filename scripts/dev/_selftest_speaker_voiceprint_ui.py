#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# @version 1.19.0
"""主播声纹 · 界面流程自检（离屏，跑真实线程 + 真实模型）

覆盖「录入卡」与「多选器」的完整交互链路：
  空列表提示 → 填表单 → 点「开始录入」→ 后台线程 → 列表刷新 + changed 信号
  → 同名重录不重复 → 缺文件提示 → 多选器勾选落盘 / 全部清除。

为什么单独成文件（而不是并进 `src\\_selftest_speaker_voiceprint.py`）：那边刻意保持
**不依赖 Qt**（纯逻辑可离线单测），这边要建 QApplication、跑 QThread，放一起会
把那边的「离线 / 无 Qt」前提破坏掉。

⚠⚠ 运行前必须先 `import video_toolbox_qt`（真实入口）：它在导入 PyQt5 **之前**
执行 `_fix_msvc_runtime_shadow()`，把 System32 的新版 MSVC 运行时装进进程；否则
onnxruntime 加载不了，症状是「未安装 onnxruntime」（其实是 `DLL 初始化例程失败`）。
本文件里那个 import 是**第一句**，不要挪到 PyQt5 之后。

运行：tools/python/python.exe scripts\\dev\\_selftest_speaker_voiceprint_ui.py
依赖：已下载声纹模型 + C:\\bld\\sv_ref\\e2e\\multi.mp4（缺失时自动跳过流程类断言）
"""
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SRC = os.path.join(ROOT, "src")
SITE = os.path.join(ROOT, "tools", "python", "Lib", "site-packages")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_PLATFORM_PLUGIN_PATH",
                      os.path.join(SITE, "PyQt5", "Qt5", "plugins"))
os.environ["VT_NO_PIPELINE"] = "1"
os.environ["VT_NO_SYNC"] = "1"
# 声纹同步独立通道也要关：UI 自检会真跑录入/删除，别往真实待传队列写测试条目
os.environ["VT_NO_VP_SYNC"] = "1"
sys.path.insert(0, SRC)
sys.path.insert(0, SITE)

#: 演示素材（三人交替的合成 mp4）；不存在则只跑不依赖模型的断言
MEDIA = r"C:\bld\sv_ref\e2e\multi.mp4"
FAILS = []


def check(name, cond, extra=""):
    print("  [%s] %s%s" % ("PASS" if cond else "FAIL", name,
                           (" -> " + str(extra)) if extra else ""))
    if not cond:
        FAILS.append(name)


def main():
    # ⚠⚠ 必须是第一件事：真实入口在 PyQt5 之前修 MSVC 运行时遮蔽
    import video_toolbox_qt  # noqa: F401

    from PyQt5.QtCore import QEventLoop, QTimer
    from PyQt5.QtWidgets import QApplication, QLabel

    import speaker_voiceprint as SV
    import speaker_voiceprint_page as P

    app = QApplication.instance() or QApplication([])

    tmp = tempfile.mkdtemp(prefix="vt_vp_ui_")
    old_dir, old_sel = SV.TEMPLATE_DIR, SV.SELECTION_PATH
    SV.TEMPLATE_DIR = tmp
    SV.SELECTION_PATH = os.path.join(tmp, "selection.json")
    try:
        card = P.VoiceprintEnrollCard()
        check("空列表提示已显示", "还没有录入任何声纹" in _texts(card, QLabel))
        check("初始无模板", SV.list_templates() == [])

        have = os.path.isfile(MEDIA) and SV.model_present()
        if not have:
            print("  [SKIP] 缺少素材或声纹模型，跳过录入流程断言")
            print("         素材：%s（存在=%s）  模型：%s"
                  % (MEDIA, os.path.isfile(MEDIA), SV.model_present()))
            return 0

        fired = []
        card.changed.connect(lambda: fired.append(1))

        card.src_edit.setText(MEDIA)
        card.start_spin.setValue(0)
        card.dur_spin.setValue(3)
        card.name_edit.setText("主播UI")
        card._do_enroll()
        check("录入期间按钮被禁用", not card.btn_enroll.isEnabled())

        _wait(card, app)
        check("录入完成（模板已落盘）", SV.list_templates() == ["主播UI"],
              SV.list_templates())
        check("按钮已恢复可用", card.btn_enroll.isEnabled())
        check("列表已刷新出该声纹", "主播UI" in _texts(card, QLabel))
        check("changed 信号已发出", len(fired) == 1, len(fired))
        check("状态栏给出成功提示", "已录入" in card.status.text(),
              card.status.text())

        card.dur_spin.setValue(2)
        card._do_enroll()
        _wait(card, app)
        check("同名重录不产生重复条目", SV.list_templates() == ["主播UI"],
              SV.list_templates())

        card.src_edit.setText("Z:/不存在.mp4")
        card._do_enroll()
        check("源文件不存在时给出提示",
              "请先选择一个存在的音视频文件" in card.status.text(),
              card.status.text())

        pick = P.VoiceprintPicker()
        pick.refresh()
        boxes = [c for c in pick._boxes if isinstance(c, P.CheckBox)]
        check("多选器列出模板", len(boxes) == 1, len(boxes))
        for c in boxes:
            c.setChecked(True)
        check("勾选后启用名单已落盘", SV.load_selection() == ["主播UI"],
              SV.load_selection())
        pick._clear()
        check("全部清除后启用名单为空", SV.load_selection() == [])
    finally:
        SV.TEMPLATE_DIR, SV.SELECTION_PATH = old_dir, old_sel
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n结果：%s" % ("全部通过" if not FAILS
                        else "%d 项失败 %s" % (len(FAILS), FAILS)))
    return 1 if FAILS else 0


def _wait(card, app, limit_ms=60000):
    from PyQt5.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    card._worker.done.connect(lambda *a: loop.quit())
    QTimer.singleShot(limit_ms, loop.quit)
    loop.exec_()
    app.processEvents()


def _texts(w, cls):
    return " ".join(x.text() for x in w.findChildren(cls))


if __name__ == "__main__":
    sys.exit(main())
