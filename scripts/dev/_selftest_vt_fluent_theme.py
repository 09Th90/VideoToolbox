# -*- coding: utf-8 -*-
# @version 2.5.0
"""vt_fluent 主题层 parity 探针（B0 门：深浅色令牌与 qfluentwidgets 逐值对照）。

同一进程内加载 qfluentwidgets（对照基准）与 vt_fluent（自研），逐项比对：
  1. ThemeColor 七档派生   —— 多主题色 × 明暗两档，.name()/.color() 逐值相等
  2. renderQss 模板替换    —— --ThemeColorXxx/--FontFamilies 输出逐字节相等
  3. ConfigItem 语义       —— key/serialize/deserializeFrom/默认值修正
  4. setFont/getFont       —— 字体族清单/像素字号/字重逐项相等
  5. isDarkTheme 解析      —— 三种主题档下深浅判定一致

qfluentwidgets 仅为对照基准存在；本测试 PASS 不要求它随包分发。

用法（程序根为 cwd）：
    VT_NO_SYNC=1 tools\\python\\python.exe scripts\\dev\\_selftest_vt_fluent_theme.py
退出码：0 = PASS；1 = FAIL。
"""
import os
import sys
from enum import Enum

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "src"))

ACCENTS = ["#009faa", "#45C877", "#3B82F6", "#EC4899", "#000000", "#FFFFFF"]

fails = []


def _cmp(label, a, b):
    if a != b:
        fails.append(f"{label}: qfluentwidgets={a!r} vt_fluent={b!r}")


def main():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])

    import qfluentwidgets as qfw
    import qfluentwidgets.common.config as qcfg
    import qfluentwidgets.common.style_sheet as qss
    import qfluentwidgets.common.font as qfont
    import vt_fluent as vt

    from qfluentwidgets import Theme as QTheme, setThemeColor as q_setColor, setTheme as q_setTheme
    from qfluentwidgets.common.config import qconfig as q_qconfig

    # ---- 1. ThemeColor 七档派生（多色 × 明暗） -------------------------- #
    for accent in ACCENTS:
        q_setColor(qfw.QColor(accent))
        vt.setThemeColor(vt.QColor(accent)) if hasattr(vt, "QColor") else None
        from PySide6.QtGui import QColor
        vt.setThemeColor(QColor(accent))
        for theme_name, q_t, v_t in (
                ("LIGHT", QTheme.LIGHT, vt.Theme.LIGHT),
                ("DARK", QTheme.DARK, vt.Theme.DARK)):
            q_setTheme(q_t)
            vt.setTheme(v_t)
            for member in qfw.ThemeColor:
                # ⚠ member.name 被上游覆写为「返回色值」的方法；成员名取 _name_
                q_col = member.color()
                v_col = vt.ThemeColor[member._name_].color()
                _cmp(f"ThemeColor[{accent}/{theme_name}].{member._name_}.color()",
                     (q_col.name(), q_col.getHsv()), (v_col.name(), v_col.getHsv()))
                _cmp(f"ThemeColor[{accent}/{theme_name}].{member._name_}.name()",
                     member.name(), vt.ThemeColor[member._name_].name())

    # ---- 2. renderQss / applyThemeColor --------------------------------- #
    sample = (
        "PushButton { color: --ThemeColorPrimary; border: 1px solid --ThemeColorLight1; }\n"
        "QLineEdit { selection-background-color: --ThemeColorDark2; font: 14px --FontFamilies; }\n"
        "/* --ThemeColorXxx 不存在的占位符原样保留 */\n")
    for theme_name, q_t, v_t in (("LIGHT", QTheme.LIGHT, vt.Theme.LIGHT),
                                 ("DARK", QTheme.DARK, vt.Theme.DARK)):
        q_setTheme(q_t)
        vt.setTheme(v_t)
        _cmp(f"renderQss[{theme_name}]", qss.renderQss(sample), vt.renderQss(sample))
        _cmp(f"applyThemeColor[{theme_name}]",
             qss.applyThemeColor(sample), vt.applyThemeColor(sample))

    # ---- 3. ConfigItem 语义 --------------------------------------------- #
    from qfluentwidgets.common.config import ConfigItem as QConfigItem
    for cls_q, cls_v, label in ((QConfigItem, vt.ConfigItem, "ConfigItem"),):
        q_item = cls_q("Group", "Name", 5)
        v_item = cls_v("Group", "Name", 5)
        _cmp(f"{label}.key", q_item.key, v_item.key)
        _cmp(f"{label}.defaultValue", q_item.defaultValue, v_item.defaultValue)
        _cmp(f"{label}.serialize()", q_item.serialize(), v_item.serialize())
        q_item.deserializeFrom(9)
        v_item.deserializeFrom(9)
        _cmp(f"{label}.value after deserialize", q_item.value, v_item.value)
        # 非法值修正（OptionsValidator 回落首项）
        q_opt = cls_q("G", "O", "a", validator=qfw.OptionsValidator(["a", "b"]))
        v_opt = cls_v("G", "O", "a", validator=vt.OptionsValidator(["a", "b"]))
        q_opt.value = "zzz"
        v_opt.value = "zzz"
        _cmp(f"{label} options-correct", q_opt.value, v_opt.value)
        # 区间修正
        q_rng = cls_q("G", "R", 5, validator=qfw.RangeValidator(0, 10))
        v_rng = cls_v("G", "R", 5, validator=vt.RangeValidator(0, 10))
        q_rng.value = 99
        v_rng.value = 99
        _cmp(f"{label} range-correct", q_rng.value, v_rng.value)
    # qconfig 顶层项 key
    for q_item_name in ("themeMode", "themeColor", "fontFamilies"):
        q_item = getattr(q_qconfig, q_item_name)
        v_item = getattr(vt.qconfig, q_item_name)
        _cmp(f"qconfig.{q_item_name}.key", q_item.key, v_item.key)

        def _norm(x):
            # 枚举按 value 归一（两侧 Theme 是不同模块的类，判等恒不等）
            return x.value if isinstance(x, Enum) else (
                x.name() if hasattr(x, "name") and not isinstance(x, str) else x)

        if q_item_name == "themeMode":
            # ⚠ 有据偏离（2026-10-20）：vt_fluent 默认档 Theme.DARK，与上游
            # qfluentwidgets 的 LIGHT 不等——对齐业务主题源 ui_theme
            # _default_cfg()["theme"]="dark"，防未初始化入口双轨错位。
            # 断言改为「必须是 Dark」而非与上游 parity。
            vd = _norm(v_item.defaultValue)
            _cmp("qconfig.themeMode.defaultValue == Dark(有据偏离)", vd, "Dark")
        else:
            _cmp(f"qconfig.{q_item_name}.defaultValue",
                 _norm(q_item.defaultValue), _norm(v_item.defaultValue))

    # ---- 4. setFont / getFont ------------------------------------------- #
    # ⚠ Qt 6.12 起 setWeight 只收 QFont.Weight 枚举；int 权重上游直接崩，
    # 故按真实契约（枚举权重）比对。vt_fluent 另做了 int 兼容 coercion。
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QLabel
    for size, weight in ((11, QFont.Normal), (14, QFont.Normal), (14, QFont.Bold)):
        qf = qfont.getFont(size, weight)
        vf = vt.getFont(size, weight)
        _cmp(f"getFont({size},{weight}).families", qf.families(), vf.families())
        _cmp(f"getFont({size},{weight}).pixelSize", qf.pixelSize(), vf.pixelSize())
        _cmp(f"getFont({size},{weight}).weight", int(qf.weight()), int(vf.weight()))
    q_lbl, v_lbl = QLabel(), QLabel()
    qfont.setFont(q_lbl, 12)
    vt.setFont(v_lbl, 12)
    _cmp("setFont.pixelSize", q_lbl.font().pixelSize(), v_lbl.font().pixelSize())
    _cmp("setFont.families", q_lbl.font().families(), v_lbl.font().families())
    # int 权重兼容：上游 Qt 6.12 下会 TypeError，vt_fluent 应正常
    try:
        v_int = vt.getFont(12, 75)
        v_ok = (v_int.pixelSize() == 12 and int(v_int.weight()) == 75)
    except Exception as e:
        v_ok = False
        fails.append(f"getFont int-weight coercion: {e!r}")
    if not v_ok:
        fails.append("getFont int-weight coercion: pixelSize/weight 不符")

    # ---- 5. isDarkTheme 解析 -------------------------------------------- #
    for theme_name, q_t, v_t in (("LIGHT", QTheme.LIGHT, vt.Theme.LIGHT),
                                 ("DARK", QTheme.DARK, vt.Theme.DARK)):
        q_setTheme(q_t)
        vt.setTheme(v_t)
        _cmp(f"isDarkTheme[{theme_name}]", qfw.isDarkTheme(), vt.isDarkTheme())
    # AUTO 档：两侧各自把系统档解析进 qconfig.theme
    q_setTheme(QTheme.AUTO)
    vt.setTheme(vt.Theme.AUTO)
    _cmp("AUTO resolves same", qfw.isDarkTheme(), vt.isDarkTheme())

    print("=" * 56)
    if fails:
        print(f"VT-FLUENT-THEME PARITY RESULT: FAIL ({len(fails)} 项)")
        for x in fails[:30]:
            print("  -", x)
        return 1
    print("VT-FLUENT-THEME PARITY RESULT: PASS")
    print(f"（{len(ACCENTS)} 主题色 × 明暗 × ThemeColor 七档 + QSS 渲染 + "
          f"ConfigItem + 字体 逐值比对通过）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
