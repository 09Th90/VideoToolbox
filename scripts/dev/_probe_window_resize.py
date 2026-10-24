# -*- coding: utf-8 -*-
# @version 2.6.0
"""窗口缩放回归探针：「页面把窗口最小尺寸钉住」类缺陷的守门人。

病史（同一签名咬过三次，用户原话依次演进）：
  v1.13.x「放入视频后无法调整窗口大小」→ 应用级 _ResizeHitFilter；
  v2.1.0「左右、对角依旧无法 / 只能拉顶部」→ 主堆叠 setMinimumSize(0,0)
           + Ignored 策略 + 窗口 minimumSizeHint 覆写；
  v2.3.1「语音转录页无法缩小 / 顶部只会移动 / 放大就无法缩小 /
          换一个页面就正常」→ FluentWindow.resizeEvent 里
          navigationInterface.setFixedHeight(self.height()) 把导航栏
          最小高度钉成窗口高度（已删，见 vt_fluent/_window.py）。

正向（修复后必须全过）：
  P1 转录段 resize(880,620) 原样生效
  P2 放大 1500x950 后再缩回生效（「放大就无法缩小」不复发）
  P3 多轮放大/缩小循环
  P4 导航栏仍铺满窗口高度（删了 setFixedHeight 后由布局拉伸兜底）
  P5 导航栏 minimumSizeHint 高度 < 620（布局最小高度未被毒化）
  P6 窗口 minimumSize/minimumSizeHint 保持 880x620
  P7 缩小后手动激活窗口布局不回弹
  P8 翻译段（对照）行为不变
负向（证明测试抓得到旧病，缺了它这套断言就是聋子）：
  N1 把毒化行原样放回 FluentWindow.resizeEvent，同一真实路径必须复现
     「缩小被撑回」；再恢复修复，同一路径必须恢复正常。

跑法：VT_NO_SYNC=1 tools\\python\\python.exe scripts\\dev\\_probe_window_resize.py
"""
import os
import shutil
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)
os.environ.setdefault("VT_DATA_ROOT", os.path.join(ROOT, "build", "_resize_probe_data"))
os.environ["VT_NO_SYNC"] = "1"

from PySide6.QtWidgets import QApplication  # noqa: E402

FAILS = []


def pump(app, ms=400):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def check(name, cond, detail=""):
    print(("[PASS] " if cond else "[FAIL] ") + name + ("  " + detail if detail else ""))
    if not cond:
        FAILS.append(name)


def build_transcribing_window():
    """建窗 → 等工作台构建 → 切到「语音转录」分段。"""
    import video_toolbox_qt as vt
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
    win = vt.MainWindow([])
    win.show()
    pump(app, 400)
    for _ in range(80):
        win.subtitle_page.ensure_built()
        pump(app, 250)
        if getattr(win.subtitle_page, "_engine_home", None) is not None:
            break
    win.switchTo(win.subtitle_page)
    pump(app, 400)
    home = win.subtitle_page._engine_home
    home.stackedWidget.setCurrentWidget(home.transcription_interface)
    home.pivot.setCurrentItem("TranscriptionInterface")
    pump(app, 400)
    return app, win, home


def main():
    global win, app
    import vt_fluent._window as fw

    fixed_resize_event = fw.FluentWindow.resizeEvent

    # ================= 正向：修复后的源码 =================
    app, win, home = build_transcribing_window()
    nav = win.navigationInterface

    win.resize(1180, 729)
    pump(app, 300)
    win.resize(880, 620)
    pump(app, 400)
    check("P1 转录段：resize(880,620) 原样生效",
          win.size().width() == 880 and win.size().height() == 620,
          "实际 %s" % (win.size(),))

    win.resize(1500, 950)
    pump(app, 300)
    win.resize(880, 620)
    pump(app, 400)
    check("P2 转录段：放大后再缩回 880x620 生效",
          win.size().width() == 880 and win.size().height() == 620,
          "实际 %s" % (win.size(),))

    ok = True
    for w, h in ((1000, 700), (1600, 1000), (900, 640), (880, 620),
                 (1200, 800), (880, 620), (960, 660), (880, 620)):
        win.resize(w, h)
        pump(app, 250)
        if win.size().width() != w or win.size().height() != h:
            ok = False
            print("    循环卡住：目标 (%d,%d) 实际 %s" % (w, h, win.size()))
            break
    check("P3 转录段：多轮放大/缩小循环全部生效", ok)

    check("P4 导航栏仍铺满窗口高度（布局拉伸兜底）",
          abs(nav.height() - win.height()) <= 1,
          "nav.h=%d win.h=%d" % (nav.height(), win.height()))

    nmsh = nav.minimumSizeHint()
    check("P5 导航栏 minimumSizeHint 高度 < 620（未毒化布局最小高度）",
          nmsh.height() < 620, "nav.msh=%s" % (nmsh,))

    check("P6 窗口 minimumSize=880x620 且 minimumSizeHint 一致",
          win.minimumSize().width() == 880 and win.minimumSize().height() == 620
          and win.minimumSizeHint().width() == 880
          and win.minimumSizeHint().height() == 620,
          "min=%s msh=%s" % (win.minimumSize(), win.minimumSizeHint()))

    win.resize(1180, 738)
    pump(app, 300)
    win.resize(880, 620)
    pump(app, 300)
    win.layout().activate()
    pump(app, 300)
    check("P7 转录段：缩小后手动激活窗口布局，高度不回弹",
          win.size().height() == 620, "实际 %s" % (win.size(),))

    home.stackedWidget.setCurrentWidget(home.subtitle_optimization_interface)
    home.pivot.setCurrentItem("SubtitleInterface")
    pump(app, 400)
    win.resize(1500, 950)
    pump(app, 300)
    win.resize(880, 620)
    pump(app, 400)
    check("P8 翻译段（对照）：放大后缩回 880x620 生效",
          win.size().width() == 880 and win.size().height() == 620,
          "实际 %s" % (win.size(),))
    win.close()
    pump(app, 300)

    # ================= 负向：还原毒化行，旧病必须复现 =================
    def poisoned_resize_event(self, e):
        fw.QWidget.resizeEvent(self, e)
        self.titleBar.move(46, 0)
        self.titleBar.resize(self.width() - 46, self.titleBar.height())
        self.titleBar.raise_()
        self.navigationInterface.setFixedHeight(self.height())

    fw.FluentWindow.resizeEvent = poisoned_resize_event
    app, win, home = build_transcribing_window()
    win.resize(1180, 729)
    pump(app, 300)
    win.resize(880, 620)
    pump(app, 500)
    sz = win.size()
    check("N1 负向：还原 setFixedHeight 毒化行后，转录段缩小必须被撑回",
          sz.height() != 620,
          "resize(880,620) 实际 %s（被撑回才算抓到旧病）" % (sz,))
    win.close()
    pump(app, 300)

    # ================= 恢复修复，同一路径必须正常 =================
    fw.FluentWindow.resizeEvent = fixed_resize_event
    app, win, home = build_transcribing_window()
    win.resize(1180, 729)
    pump(app, 300)
    win.resize(880, 620)
    pump(app, 500)
    sz = win.size()
    check("N2 恢复修复后：转录段缩小原样生效",
          sz.width() == 880 and sz.height() == 620,
          "实际 %s" % (sz,))
    win.resize(1500, 950)
    pump(app, 300)
    win.resize(880, 620)
    pump(app, 500)
    sz = win.size()
    check("N3 恢复修复后：放大再缩回也生效",
          sz.width() == 880 and sz.height() == 620,
          "实际 %s" % (sz,))

    print("=" * 46)
    print("WINDOW-RESIZE PROBE %s（%d 项失败）" % (
        "ALL PASS" if not FAILS else "HAS FAILS", len(FAILS)))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
