# -*- coding: utf-8 -*-
# @version 2.5.2
"""vt_fluent 控件族 parity 探针（B1 门：几何 + 态色与 qfluentwidgets 逐项对照）。

同一进程内加载 qfluentwidgets（对照基准）与 vt_fluent（自研），离屏
（QT_QPA_PLATFORM=offscreen）逐项比对：
  1. 几何度量   —— 固定高度/子控件尺寸/图标尺寸/表头行高等；
  2. 标签字体   —— Caption/Body/StrongBody/Subtitle/Title 的像素字号与字重；
  3. 态色矩阵   —— SwitchButton 指示器、CheckBox 的 8 态 × 明暗两档
                   背景/描边/滑块色逐值相等；
  4. 进度条色   —— ProgressBar 正常/暂停/错误三态 barColor 明暗两档。

qfluentwidgets 仅为对照基准存在；本测试 PASS 不要求它随包分发。

用法（程序根为 cwd）：
    VT_NO_SYNC=1 tools\\python\\python.exe scripts\\dev\\_selftest_vt_fluent_widgets.py
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


def _color(c):
    return None if c is None else c.name()


def _check(label, cond, detail=""):
    global checked
    checked += 1
    if not cond:
        fails.append(f"{label}: {detail}")


def _pump(ms=200):
    from PySide6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def main():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QWidget
    from PySide6.QtGui import QColor
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

    # ---- 1. 几何度量 ---------------------------------------------------- #
    def geo(tname):
        # LineEdit 固定高
        _cmp(f"LineEdit.height[{tname}]",
             qfw.LineEdit().height(), vt.LineEdit().height())
        # SpinBox 固定高 + 按钮尺寸
        q_sb, v_sb = qfw.SpinBox(), vt.SpinBox()
        _cmp(f"SpinBox.height[{tname}]", q_sb.height(), v_sb.height())
        _cmp(f"SpinBox.upButton.size[{tname}]",
             (q_sb.upButton.width(), q_sb.upButton.height()),
             (v_sb.upButton.width(), v_sb.upButton.height()))
        # CompactSpinBox 按钮
        q_cs, v_cs = qfw.CompactSpinBox(), vt.CompactSpinBox()
        _cmp(f"CompactSpinBox.button.size[{tname}]",
             (q_cs.compactSpinButton.width(), q_cs.compactSpinButton.height()),
             (v_cs.compactSpinButton.width(), v_cs.compactSpinButton.height()))
        # SwitchButton 高 + 指示器尺寸
        q_sw, v_sw = qfw.SwitchButton(), vt.SwitchButton()
        _cmp(f"SwitchButton.height[{tname}]", q_sw.height(), v_sw.height())
        _cmp(f"SwitchButton.indicator.size[{tname}]",
             (q_sw.indicator.width(), q_sw.indicator.height()),
             (v_sw.indicator.width(), v_sw.indicator.height()))
        # 滑杆把手
        q_sl, v_sl = qfw.Slider(), vt.Slider()
        _cmp(f"Slider.handle.size[{tname}]",
             (q_sl.handle.width(), q_sl.handle.height()),
             (v_sl.handle.width(), v_sl.handle.height()))
        _cmp(f"Slider.minHeight[{tname}]",
             q_sl.minimumHeight(), v_sl.minimumHeight())
        # 进度条/环
        _cmp(f"ProgressBar.height[{tname}]",
             qfw.ProgressBar().height(), vt.ProgressBar().height())
        q_pr, v_pr = qfw.ProgressRing(), vt.ProgressRing()
        _cmp(f"ProgressRing.size[{tname}]",
             (q_pr.width(), q_pr.height()), (v_pr.width(), v_pr.height()))
        _cmp(f"ProgressRing.strokeWidth[{tname}]",
             q_pr.strokeWidth, v_pr.strokeWidth)
        # 按钮图标尺寸
        q_pb, v_pb = qfw.PushButton(), vt.PushButton()
        _cmp(f"PushButton.iconSize[{tname}]",
             (q_pb.iconSize().width(), q_pb.iconSize().height()),
             (v_pb.iconSize().width(), v_pb.iconSize().height()))
        # 复选框几何（同文本）
        q_ck, v_ck = qfw.CheckBox("选项"), vt.CheckBox("选项")
        _cmp(f"CheckBox.sizeHint[{tname}]",
             (q_ck.sizeHint().width(), q_ck.sizeHint().height()),
             (v_ck.sizeHint().width(), v_ck.sizeHint().height()))
        # 表头默认行高
        q_tw, v_tw = qfw.TableWidget(), vt.TableWidget()
        _cmp(f"TableWidget.vheader.sectionSize[{tname}]",
             q_tw.verticalHeader().defaultSectionSize(),
             v_tw.verticalHeader().defaultSectionSize())

    both_themes(geo)

    # ---- 2. 标签字体 ---------------------------------------------------- #
    def fonts(tname):
        for q_cls, v_cls in ((qfw.CaptionLabel, vt.CaptionLabel),
                             (qfw.BodyLabel, vt.BodyLabel),
                             (qfw.StrongBodyLabel, vt.StrongBodyLabel),
                             (qfw.SubtitleLabel, vt.SubtitleLabel),
                             (qfw.TitleLabel, vt.TitleLabel)):
            qf, vf = q_cls().font(), v_cls().font()
            _cmp(f"{v_cls.__name__}.pixelSize[{tname}]",
                 qf.pixelSize(), vf.pixelSize())
            _cmp(f"{v_cls.__name__}.weight[{tname}]",
                 int(qf.weight()), int(vf.weight()))

    both_themes(fonts)

    # ---- 3. 态色矩阵：SwitchButton 指示器 ------------------------------- #
    def switch_colors(tname):
        q_sw, v_sw = qfw.SwitchButton(), vt.SwitchButton()
        for checked in (False, True):
            for hover in (False, True):
                for pressed in (False, True):
                    for enabled in (True, False):
                        for w in (q_sw, v_sw):
                            w.setEnabled(enabled)
                            w.indicator.setChecked(checked)
                            w.indicator.setHover(hover)
                            w.indicator.isPressed = pressed
                        tag = f"c{int(checked)}h{int(hover)}p{int(pressed)}e{int(enabled)}"
                        _cmp(f"Indicator.bg[{tname}/{tag}]",
                             _color(q_sw.indicator._backgroundColor()),
                             _color(v_sw.indicator._backgroundColor()))
                        _cmp(f"Indicator.border[{tname}/{tag}]",
                             _color(q_sw.indicator._borderColor()),
                             _color(v_sw.indicator._borderColor()))
                        _cmp(f"Indicator.slider[{tname}/{tag}]",
                             _color(q_sw.indicator._sliderColor()),
                             _color(v_sw.indicator._sliderColor()))

    both_themes(switch_colors)

    # ---- 3b. 态色矩阵：CheckBox ----------------------------------------- #
    def check_colors(tname):
        q_ck, v_ck = qfw.CheckBox("x"), vt.CheckBox("x")
        for checked in (False, True):
            for hover in (False, True):
                for pressed in (False, True):
                    for enabled in (True, False):
                        for w in (q_ck, v_ck):
                            w.setEnabled(enabled)
                            w.setChecked(checked)
                            w.isHover = hover
                            w.isPressed = pressed
                        tag = f"c{int(checked)}h{int(hover)}p{int(pressed)}e{int(enabled)}"
                        _cmp(f"CheckBox.border[{tname}/{tag}]",
                             _color(q_ck._borderColor()),
                             _color(v_ck._borderColor()))
                        _cmp(f"CheckBox.bg[{tname}/{tag}]",
                             _color(q_ck._backgroundColor()),
                             _color(v_ck._backgroundColor()))

    both_themes(check_colors)

    # ---- 4. 进度条色 ---------------------------------------------------- #
    def progress_colors(tname):
        for state in ("normal", "paused", "error"):
            q_pb, v_pb = qfw.ProgressBar(), vt.ProgressBar()
            for w in (q_pb, v_pb):
                w.setRange(0, 100)
                w.setValue(50)
                if state == "paused":
                    w.pause()
                elif state == "error":
                    w.error()
            _cmp(f"ProgressBar.barColor[{tname}/{state}]",
                 _color(q_pb.barColor()), _color(v_pb.barColor()))

    both_themes(progress_colors)

    # ---- 5. 滑杆色 ------------------------------------------------------ #
    def slider_colors(tname):
        q_sl, v_sl = qfw.Slider(), vt.Slider()
        for w in (q_sl, v_sl):
            w.setRange(0, 100)
            w.setValue(30)
        _cmp(f"Slider.handle.lightHandleColor[{tname}]",
             _color(q_sl.handle.lightHandleColor),
             _color(v_sl.handle.lightHandleColor))
        _cmp(f"Slider.handle.darkHandleColor[{tname}]",
             _color(q_sl.handle.darkHandleColor),
             _color(v_sl.handle.darkHandleColor))

    both_themes(slider_colors)

    # ---- 6. 自查守卫（2026-10-18 审计发现的回归点） -------------------- #
    import ast as _ast
    import re as _re

    # 6a. vt_fluent 内部引用的 FluentIcon 必须都在内嵌 ART 里
    #     （缺一个 → 该处画空白，且异常被 Qt 吞掉，肉眼才发现）
    vt_dir = os.path.join(ROOT, "src", "vt_fluent")
    used_icons = set()
    for fn in os.listdir(vt_dir):
        if not fn.endswith(".py"):
            continue
        tree = _ast.parse(open(os.path.join(vt_dir, fn), encoding="utf-8").read())
        for n in _ast.walk(tree):
            if (isinstance(n, _ast.Attribute) and isinstance(n.value, _ast.Name)
                    and n.value.id == "FluentIcon"):
                used_icons.add(n.attr)
    art_src = open(os.path.join(vt_dir, "_icons_data.py"), encoding="utf-8").read()
    art = set(_re.findall(r"^    '([A-Z_0-9]+)':", art_src, _re.M))
    _check("Icons.internalRefsInART", not (used_icons - art),
           f"缺 {sorted(used_icons - art)}")

    # 6b. Action 图标非空 + 菜单项图标非空（曾因 Icon(path) 恒空而全灭）
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    act = vt.Action(vt.FluentIcon.SAVE, "保存")
    _check("Action.icon.notNull", not act.icon().isNull())
    menu = vt.RoundMenu("m")
    menu.addAction(act)
    _check("Menu.item.icon.notNull", not menu.view.item(0).icon().isNull())
    img = QImage(120, 40, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    menu.view.viewport().render(img)
    painted = sum(1 for x in range(min(30, img.width()))
                  for y in range(min(16, img.height()))
                  if img.pixelColor(x, y).alpha() > 40)
    _check("Menu.item.icon.painted", painted > 20, f"pixels={painted}")

    # 6c. 滚轮必须驱动区域自身滚动条（曾驱动游离 bar → 滚轮失效）
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtCore import QPoint as _QP, QPointF as _QPF
    sa = vt.ScrollArea()
    inner = QWidget()
    inner.setMinimumHeight(2000)
    sa.setWidget(inner)
    sa.resize(300, 300)
    sa.show()
    _pump(80)
    ev = QWheelEvent(_QPF(10, 10), _QPF(10, 10), _QP(0, 0), _QP(0, -120),
                     Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    QApplication.sendEvent(sa.viewport(), ev)
    _pump(400)
    _check("ScrollArea.wheelWorks", sa.verticalScrollBar().value() > 0,
           f"value={sa.verticalScrollBar().value()}")

    # 6d. SegmentedWidget 选中块随项移动（曾在布局完成前恒停在 x=0）
    seg = vt.SegmentedWidget()
    seg.resize(600, 40)
    seg.addItem("a", "A")
    seg.addItem("b", "B")
    seg.show()
    _pump(120)
    seg.setCurrentItem("b")
    _pump(300)
    img2 = QImage(600, 40, QImage.Format_ARGB32)
    img2.fill(Qt.transparent)
    seg.render(img2)
    ca = img2.pixelColor(150, 6)
    cb = img2.pixelColor(450, 6)
    _check("Segmented.blockFollows", cb.alpha() > ca.alpha(),
           f"a={ca.getRgb()} b={cb.getRgb()}")

    print("=" * 56)
    if fails:
        print(f"VT-FLUENT-WIDGETS PARITY RESULT: FAIL ({len(fails)} 项)")
        for x in fails[:30]:
            print("  -", x)
        return 1
    print(f"VT-FLUENT-WIDGETS PARITY RESULT: PASS（{checked} 项逐值比对通过："
          f"几何/字体/8 态×明暗色矩阵/进度条/滑杆）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
