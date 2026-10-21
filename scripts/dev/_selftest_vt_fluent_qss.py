# -*- coding: utf-8 -*-
# @version 2.5.1
"""vt_fluent QSS 库完整性自检（令牌 / 载体 / 渲染 / app 级兜底）。

检查项：
  1. 令牌表健康     —— DESIGN_TOKENS 明暗键集一致、值非空
  2. 载体完整       —— FluentStyleSheet 全成员 content(明/暗) 非空；
                       app.qss 存在且含 QToolTip/QMenu/QMessageBox 域
  3. 渲染闭合       —— 明暗两档渲染后**规则体内**无 --Token 残留
                       （注释里的 --Xxx 允许，先剥注释再查；键缺失时
                       safe_substitute 静默跳过 = 不可见漏色，必须拦）
  4. 令牌注入抽验   —— 样例串在明暗两档输出各自令牌值；
                       --ThemeColorXxx/--FontFamilies 兼容不变
  5. 实测应用       —— 全量 QSS setStyleSheet 到 QWidget 无异常；
                       主题切换重渲染走通（light→dark 令牌值翻转）
  5b. 注册面档位一致 —— 控件注册后切主题，生效 QSS 必须等于当前档渲染
                       （updateStyleSheet 同值跳过/lazy 漏刷的库级防线，
                       2026-10-20「切主题后点一下才统一」修复配套）
  6. 透明化基座     —— QScrollArea 规则存在于渲染产物（发白缺陷的库级防线）

用法（程序根为 cwd）：
    VT_NO_SYNC=1 tools\\python\\python.exe scripts\\dev\\_selftest_vt_fluent_qss.py
退出码：0 = PASS；1 = FAIL。
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "src"))

fails = []
passed = 0


def _ok(label):
    global passed
    passed += 1


def _bad(label, detail=""):
    fails.append(f"{label}{(': ' + detail) if detail else ''}")


def _strip_comments(qss: str) -> str:
    return re.sub(r"/\*.*?\*/", "", qss, flags=re.S)


def main():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QScrollArea, QWidget
    app = QApplication.instance() or QApplication([])

    from vt_fluent import (DESIGN_TOKENS, FluentStyleSheet, Theme,
                           applyAppStyleSheet, getStyleSheet, renderQss,
                           setStyleSheet, setTheme)

    # ---- 1. 令牌表健康 -------------------------------------------------- #
    light_keys = set(DESIGN_TOKENS[Theme.LIGHT])
    dark_keys = set(DESIGN_TOKENS[Theme.DARK])
    if light_keys != dark_keys:
        _bad("令牌键集一致", f"light-dark={light_keys ^ dark_keys}")
    else:
        _ok("令牌键集一致")
    for t in (Theme.LIGHT, Theme.DARK):
        empties = [k for k, v in DESIGN_TOKENS[t].items()
                   if not (isinstance(v, str) and v.strip())]
        if empties:
            _bad(f"令牌值非空[{t.name}]", str(empties))
        else:
            _ok(f"令牌值非空[{t.name}]")

    # ---- 2. 载体完整 ------------------------------------------------------ #
    for member in FluentStyleSheet:
        for t in (Theme.LIGHT, Theme.DARK):
            text = member.content(t)
            if not text.strip():
                _bad(f"content 非空[{member.name}/{t.name}]")
        _ok(f"content 非空[{member.name}]")

    app_qss_path = os.path.join(
        os.path.dirname(os.path.abspath(
            __import__("vt_fluent._theme", fromlist=["x"]).__file__)),
        "_qss", "app.qss")
    if not os.path.isfile(app_qss_path):
        _bad("app.qss 存在", app_qss_path)
    else:
        _ok("app.qss 存在")
        from vt_fluent import getStyleSheetFromFile
        app_raw = getStyleSheetFromFile(app_qss_path)
        for sel in ("QToolTip", "QMenu", "QMessageBox"):
            if re.search(rf"^{re.escape(sel)}\b", app_raw, flags=re.M):
                _ok(f"app.qss 含 {sel} 域")
            else:
                _bad(f"app.qss 含 {sel} 域")

    # ---- 3. 渲染闭合（规则体内无 --Token 残留） --------------------------- #
    body_pat = re.compile(r"--[A-Za-z_][A-Za-z0-9_]*")
    for member in FluentStyleSheet:
        for t in (Theme.LIGHT, Theme.DARK):
            rendered = _strip_comments(getStyleSheet(member, t))
            residue = sorted(set(body_pat.findall(rendered)))
            if residue:
                _bad(f"渲染闭合[{member.name}/{t.name}]", str(residue))
    if not any(f.startswith("渲染闭合") for f in fails):
        _ok("渲染闭合（全成员 × 明暗）")
    for t in (Theme.LIGHT, Theme.DARK):
        rendered = _strip_comments(getStyleSheet(
            __import__("vt_fluent").StyleSheetFile(app_qss_path), t))
        residue = sorted(set(body_pat.findall(rendered)))
        if residue:
            _bad(f"渲染闭合[app.qss/{t.name}]", str(residue))
        else:
            _ok(f"渲染闭合[app.qss/{t.name}]")

    # ---- 4. 令牌注入抽验 --------------------------------------------------- #
    sample = ("color: --TextPrimary; bg: --SurfaceSolid; "
              "handle: --ScrollHandle; track: --TrackFill; "
              "accent: --ThemeColorPrimary; font: 14px --FontFamilies;")
    for t in (Theme.LIGHT, Theme.DARK):
        out = renderQss(sample, t)
        toks = DESIGN_TOKENS[t]
        expect = (f"color: {toks['TextPrimary']}; bg: {toks['SurfaceSolid']}; "
                  f"handle: {toks['ScrollHandle']}; track: {toks['TrackFill']}; ")
        if not out.startswith(expect):
            _bad(f"令牌注入[{t.name}]", out)
        else:
            _ok(f"令牌注入[{t.name}]")
    if "--ThemeColorPrimary" in renderQss(sample, Theme.LIGHT):
        _bad("主题色占位替换")
    else:
        _ok("主题色占位替换")
    if "Segoe UI" not in renderQss(sample, Theme.LIGHT):
        _bad("字体占位替换")
    else:
        _ok("字体占位替换")

    # ---- 5. 实测应用 ------------------------------------------------------- #
    try:
        w = QWidget()
        setStyleSheet(w, FluentStyleSheet.FLUENT_WINDOW)
        w.setStyleSheet(getStyleSheet(FluentStyleSheet.BUTTON))
        _ok("setStyleSheet 实测")
    except Exception as e:  # noqa: BLE001
        _bad("setStyleSheet 实测", repr(e))
    try:
        applyAppStyleSheet(app)
        if "QToolTip" in app.styleSheet():
            _ok("applyAppStyleSheet 实测")
        else:
            _bad("applyAppStyleSheet 实测", "app.styleSheet() 缺 QToolTip 域")
    except Exception as e:  # noqa: BLE001
        _bad("applyAppStyleSheet 实测", repr(e))

    # 主题切换重渲染：light→dark 令牌值翻转
    setTheme(Theme.LIGHT)
    light_qss = getStyleSheet(FluentStyleSheet.FLUENT_WINDOW)
    setTheme(Theme.DARK)
    dark_qss = getStyleSheet(FluentStyleSheet.FLUENT_WINDOW)
    lv, dv = DESIGN_TOKENS[Theme.LIGHT], DESIGN_TOKENS[Theme.DARK]
    if (lv["ScrollHandle"] in light_qss and dv["ScrollHandle"] in dark_qss
            and lv["ScrollHandle"] not in dark_qss):
        _ok("主题切换重渲染")
    else:
        _bad("主题切换重渲染", "令牌值未随主题翻转")
    setTheme(Theme.LIGHT)  # 还原

    # ---- 5b. 注册面档位一致（切主题漏刷的库级防线） ----------------------- #
    # 控件注册后切主题，每个控件的生效 QSS 必须等于当前档渲染结果。
    # 历史上 updateStyleSheet 的同值跳过/lazy 漏刷会让控件停旧档——
    # 用户观感「切主题后鼠标点一下颜色才统一」（2026-10-20 修复）。
    # 注：offscreen 下控件未显示，走全量刷新路径；隐藏控件的 lazy 路径
    # 由 _probe_theme_switch_guard.py（真窗口）覆盖，两者互补。
    from vt_fluent import (BodyLabel, CaptionLabel, LineEdit, PushButton,
                           styleSheetManager)
    from vt_fluent._theme import render_for_widget
    probes = [CaptionLabel("caption"), BodyLabel("body"), PushButton("btn"),
              LineEdit()]
    for t in (Theme.DARK, Theme.LIGHT):
        setTheme(t)
        mismatch = []
        for w in probes:
            exp = render_for_widget(w, styleSheetManager.source(w))
            if exp.rstrip() != (w.styleSheet() or "").rstrip():
                mismatch.append(type(w).__name__)
        if mismatch:
            _bad(f"注册面档位一致[{t.name}]", str(mismatch))
        else:
            _ok(f"注册面档位一致[{t.name}]")
    setTheme(Theme.DARK)  # 还原

    # ---- 6. 透明化基座（QScrollArea 发白缺陷的库级防线） ------------------- #
    area = QScrollArea()
    inner = QWidget()
    area.setWidget(inner)  # 触发强制 autoFillBackground=True 的路径
    qss_text = getStyleSheet(FluentStyleSheet.FLUENT_WINDOW)
    if "QScrollArea > QWidget > QWidget" in qss_text:
        _ok("滚动区透明化规则存在")
    else:
        _bad("滚动区透明化规则存在")

    # ---- 汇报 ------------------------------------------------------------ #
    total = passed + len(fails)
    print()
    if fails:
        for f in fails:
            print(f"  ✗ {f}")
        print(f"\nVT-FLUENT-QSS RESULT: FAIL（{passed}/{total} 项通过）")
        return 1
    print(f"\nVT-FLUENT-QSS RESULT: PASS（{total} 项通过：令牌/载体/渲染/app 级/实测/透明化）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
