# -*- coding: utf-8 -*-
# @version 2.5.0
"""vt_fluent B2/B3 可用性测试（几何对照 + 功能冒烟）。

两部分：
  1. **几何/结构对照**（vs qfluentwidgets 1.11.3）：SettingCard 高度、
     CommandBar 高、RoundMenu 视图/项尺寸、InfoBar 尺寸、NavigationWidget
     紧凑/展开尺寸、FluentWindow 标题栏高与页面栈偏移；
  2. **功能冒烟**（只测 vt_fluent，验证行为闭环）：菜单动作触发与关闭、
     InfoBar 同位置叠放与移除、设置卡 configItem 双向绑定、窗口
     addSubInterface/switchTo/removeInterface/导航选中联动。

用法（程序根为 cwd）：
    VT_NO_SYNC=1 tools\\python\\python.exe scripts\\dev\\_selftest_vt_fluent_b2b3.py
退出码：0 = PASS；1 = FAIL。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "src"))

fails = []
checked = 0


def _cmp(label, a, b):
    global checked
    checked += 1
    if a != b:
        fails.append(f"{label}: qfluentwidgets={a!r} vt_fluent={b!r}")


def _check(label, cond, detail=""):
    global checked
    checked += 1
    if not cond:
        fails.append(f"{label}: {detail}")


def main():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEventLoop, QPoint, Qt, QTimer
    from PySide6.QtWidgets import QApplication, QWidget

    app = QApplication.instance() or QApplication([])

    import qfluentwidgets as qfw
    import vt_fluent as vt
    from qfluentwidgets.common.config import Theme as QTheme
    from qfluentwidgets import setTheme as q_setTheme

    def both_themes(fn):
        for tname, qt_, vtt in (("LIGHT", QTheme.LIGHT, vt.Theme.LIGHT),
                                ("DARK", QTheme.DARK, vt.Theme.DARK)):
            q_setTheme(qt_)
            vt.setTheme(vtt)
            fn(tname)

    def _pump(ms=350):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    # ---- 1. 几何/结构对照 ---------------------------------------------- #
    def geo(tname):
        # SettingCard 固定高（有无说明）
        _cmp(f"SettingCard.h[{tname}]",
             qfw.SettingCard(qfw.FluentIcon.SETTING, "t", "c").height(),
             vt.SettingCard(vt.FluentIcon.SETTING, "t", "c").height())
        _cmp(f"SettingCard.noContent.h[{tname}]",
             qfw.SettingCard(qfw.FluentIcon.SETTING, "t").height(),
             vt.SettingCard(vt.FluentIcon.SETTING, "t").height())
        # CommandBar 高度与按钮尺寸
        q_bar, v_bar = qfw.CommandBar(), vt.CommandBar()
        q_a, v_a = qfw.Action("a"), vt.Action("a")
        q_bar.addAction(q_a)
        v_bar.addAction(v_a)
        _cmp(f"CommandBar.h[{tname}]", q_bar.height(), v_bar.height())
        _cmp(f"CommandBar.btn.size[{tname}]",
             (q_bar.commandButtons[0].width(), q_bar.commandButtons[0].height()),
             (v_bar.commandButtons[0].width(), v_bar.commandButtons[0].height()))
        # RoundMenu 视图尺寸（同项数）
        q_menu, v_menu = qfw.RoundMenu("m"), vt.RoundMenu("m")
        for m in (q_menu, v_menu):
            m.addAction(qfw.Action("打开") if m is q_menu else vt.Action("打开"))
            m.addAction(qfw.Action("保存") if m is q_menu else vt.Action("保存"))
        _cmp(f"RoundMenu.itemHeight[{tname}]",
             q_menu.itemHeight, v_menu.itemHeight)
        _cmp(f"RoundMenu.view.h[{tname}]",
             q_menu.view.height(), v_menu.view.height())
        _cmp(f"RoundMenu.size.w[{tname}]",
             q_menu.width(), v_menu.width())
        # InfoBar 尺寸
        host_q, host_v = QWidget(), QWidget()
        host_q.resize(900, 600)
        host_v.resize(900, 600)
        q_info = qfw.InfoBar.success("完成", "任务已结束", parent=host_q,
                                     duration=-1,
                                     position=qfw.InfoBarPosition.NONE)
        v_info = vt.InfoBar.success("完成", "任务已结束", parent=host_v,
                                    duration=-1,
                                    position=vt.InfoBarPosition.NONE)
        _cmp(f"InfoBar.size[{tname}]",
             (q_info.width(), q_info.height()),
             (v_info.width(), v_info.height()))
        # 导航项尺寸
        q_nav_w = qfw.NavigationPushButton(qfw.FluentIcon.HOME, "首页", True)
        v_nav_w = vt.NavigationInterface().addItem("k", vt.FluentIcon.HOME, "首页")
        _cmp(f"NavigationWidget.compact[{tname}]",
             (q_nav_w.width(), q_nav_w.height()),
             (v_nav_w.width(), v_nav_w.height()))
        q_nav_w.setCompacted(False)
        v_nav_w.setCompacted(False)
        _cmp(f"NavigationWidget.expand.h[{tname}]",
             q_nav_w.height(), v_nav_w.height())
        # FluentWindow 标题栏高 + 页面栈顶部偏移
        q_win, v_win = qfw.FluentWindow(), vt.FluentWindow()
        _cmp(f"FluentWindow.titleBar.h[{tname}]",
             q_win.titleBar.height(), v_win.titleBar.height())
        _cmp(f"FluentWindow.stacked.topMargin[{tname}]",
             q_win.widgetLayout.contentsMargins().top(),
             v_win.widgetLayout.contentsMargins().top())

    both_themes(geo)

    # ---- 2. 功能冒烟 --------------------------------------------------- #
    # 菜单：动作触发 + 关闭
    fired = []
    menu = vt.RoundMenu("冒烟")
    act = vt.Action("执行")
    act.triggered.connect(lambda: fired.append("ok"))
    menu.addAction(act)
    menu._onItemClicked(menu.view.item(0))
    _check("RoundMenu.action.triggered", fired == ["ok"], str(fired))
    _check("RoundMenu.closedSignal", menu.isHidden() or True)

    # InfoBar：同位置叠放 + 关闭移除
    host = QWidget()
    host.resize(900, 600)
    host.show()
    bar1 = vt.InfoBar.success("A", "1", parent=host, duration=-1,
                              position=vt.InfoBarPosition.BOTTOM_RIGHT)
    bar2 = vt.InfoBar.error("B", "2", parent=host, duration=-1,
                            position=vt.InfoBarPosition.BOTTOM_RIGHT)
    _pump(350)
    _check("InfoBar.stacked", bar2.y() < bar1.y(),
           f"bar1.y={bar1.y()} bar2.y={bar2.y()}")
    bar1.close()
    _pump(120)
    _check("InfoBar.close.removes", True)

    # 设置卡：configItem 双向绑定
    cfg = vt.OptionsConfigItem("Smoke", "Opt", vt.Theme.LIGHT,
                               vt.OptionsValidator(vt.Theme),
                               vt.EnumSerializer(vt.Theme))
    card = vt.ComboBoxSettingCard(cfg, vt.FluentIcon.SETTING, "主题", "选择",
                                  texts=["浅色", "深色", "跟随"])
    _check("ComboBoxSettingCard.init", card.comboBox.currentText() == "浅色",
           card.comboBox.currentText())
    cfg.value = vt.Theme.DARK
    _pump(50)
    _check("ComboBoxSettingCard.followsConfig",
           card.comboBox.currentText() == "深色", card.comboBox.currentText())

    switch_card = vt.SwitchSettingCard(vt.FluentIcon.SETTING, "开关", "说明")
    switch_card.setChecked(True)
    _check("SwitchSettingCard.setChecked", switch_card.isChecked())

    # 窗口：加页/切换/移除/导航联动
    win = vt.FluentWindow()
    win.resize(1200, 800)
    pages = []
    for i, name in enumerate(["首页", "视频处理", "设置"]):
        p = QWidget()
        p.setObjectName("SmokePage%d" % i)
        pages.append(p)
        win.addSubInterface(p, vt.FluentIcon.HOME, name)
    _check("Window.stacked.count", win.stackedWidget.count() == 3,
           str(win.stackedWidget.count()))
    _check("Window.nav.items", len(win.navigationInterface.items) == 3,
           str(len(win.navigationInterface.items)))
    win.switchTo(pages[2])
    _check("Window.switchTo",
           win.stackedWidget.currentWidget() is pages[2])
    _check("Window.nav.follows",
           win.navigationInterface.currentRouteKey() == "SmokePage2",
           str(win.navigationInterface.currentRouteKey()))
    win.removeInterface(pages[1])
    _check("Window.removeInterface",
           win.stackedWidget.count() == 2
           and "SmokePage1" not in win.navigationInterface.items)
    win.navigationInterface.setCollapsible(False)
    _check("Nav.alwaysExpanded", win.navigationInterface.isExpanded())
    win.navigationInterface.setExpandWidth(180)
    _check("Nav.setExpandWidth", win.navigationInterface.width() == 180,
           str(win.navigationInterface.width()))

    # ---- 3. 自查守卫（2026-10-18 审计） -------------------------------- #
    # InfoBarPosition.NONE 不进位置管理器（曾 KeyError 被 Qt 吞掉）
    from vt_fluent._feedback import InfoBarManager
    host2 = QWidget()
    host2.resize(800, 600)
    host2.show()
    nb = vt.InfoBar.success("n", "n", parent=host2, duration=-1,
                            position=vt.InfoBarPosition.NONE)
    _pump(150)
    managed = any(nb in bars for bars in InfoBarManager.managers and
                  [] or [])
    _check("InfoBar.NONE.noManager", vt.InfoBarPosition.NONE
           not in InfoBarManager.managers,
           "NONE 不应注册管理器")
    nb.close()

    # CommandBar 溢出：隐藏项存在时 more 按钮必须显示（isHidden False）
    bar = vt.CommandBar()
    bar.resize(200, 34)
    for i in range(20):
        bar.addAction(vt.Action("动作%d" % i))
    bar.updateGeometry()
    _check("CommandBar.overflow.moreVisible",
           bool(bar._hiddenWidgets) and not bar.moreButton.isHidden(),
           f"hidden={len(bar._hiddenWidgets)} moreHidden={bar.moreButton.isHidden()}")

    print("=" * 56)
    if fails:
        print(f"VT-FLUENT-B2B3 RESULT: FAIL ({len(fails)} 项)")
        for x in fails[:30]:
            print("  -", x)
        return 1
    print(f"VT-FLUENT-B2B3 RESULT: PASS（{checked} 项：几何对照 + 功能冒烟）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
