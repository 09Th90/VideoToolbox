# -*- coding: utf-8 -*-
# @version 2.5.3
"""主题切换守卫探针（2026-10-20 「切主题后颜色不统一」修复配套）。

病史（用户原话）：「完成主题色切换的第一时间，鼠标点击后颜色才统一」。
根因（复现实锤）：
  R1 未注册页（首页/自动化/AI 托管）的 UICard 是 paintEvent 现取 token 的，
     ui_theme.refresh 却只遍历 install_for_window 注册的六页 → 切档后
     卡片停旧色，等 hover/点击；
  R2 lazy  dirty-qss 只打标记等 Paint，而 Qt 绘制缓存对「外观无变化」的
     控件直接 blit 后备存储、不发 Paint → 隐藏控件切档后永远等不到
     DirtyStyleSheetWatcher 补齐（实测切档后 670/705 个注册控件停旧档、
     切页 pump 无补救）→ 修：打脏同时 widget.update() 排重绘；
  R3 _on_theme_changed 先裸 setTheme（无 lazy 全量 43s）+ updateStyleSheet
     只捕 RuntimeError，一个坏控件中断全局刷新 → 修：单链 + except Exception。

本探针（真窗口、VT_NO_SYNC=1、VT_DATA_ROOT 隔离 + 种子 ui_custom.json）：
  正向 S1-S6：启动同档 / 切档即刷（当前可见控件）/ dirty 收敛（逐页）
              / plain 输入类同档 / UICard 切档即重绘 / 同值早退无害；
  负向 N1-N5：弄坏必须翻 FAIL（refresh no-op / 吞 Paint / plain 恒 False /
              钉死 LIGHT / 注入异常），证明断言不是聋子。

跑法：tools\\python\\python.exe scripts\\dev\\_probe_theme_switch_guard.py
"""
import os
import shutil
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
os.environ["VT_NO_SYNC"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))
ISO = os.path.join(ROOT, "build", "_theme_probe_data")
os.environ["VT_DATA_ROOT"] = ISO

from PySide6.QtWidgets import QApplication  # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("[PASS] " if cond else "[FAIL] ") + name + (("  " + str(extra)) if extra else ""))
    if not cond:
        FAILS.append(name)


def pump(app, ms=400):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def main():
    # 隔离目录清空 + 种子主题配置（隔离区无 ui_custom.json 时 _default_cfg
    # 落 dark，与用户真实配置可能不同档——拷一份进去同档渲染）。
    if os.path.isdir(ISO):
        shutil.rmtree(ISO)
    os.makedirs(os.path.join(ISO, "data"), exist_ok=True)
    real_cfg = os.path.join(ROOT, "data", "ui_custom.json")
    iso_cfg = os.path.join(ISO, "data", "ui_custom.json")
    if os.path.isfile(real_cfg):
        shutil.copy2(real_cfg, iso_cfg)

    app = QApplication.instance() or QApplication(sys.argv)

    import ui_theme
    import video_toolbox_qt as vt
    from vt_fluent import isDarkTheme, qconfig, styleSheetManager
    from vt_fluent._theme import render_for_widget

    ui_theme.apply_startup_theme(app)
    check("0.1 主题双轨同档", qconfig.theme == ui_theme.qtheme()
          and isDarkTheme() == ui_theme.is_dark(),
          f"qconfig={qconfig.theme} qtheme={ui_theme.qtheme()}")

    win = vt.MainWindow([])
    win.resize(1180, 729)
    win.show()
    win._build_auto_page()
    pump(app, 800)

    # ---------- 判据工具 ----------
    def scan_visible(detail=False):
        """当前用户可见控件里 QSS 未达当前档的个数（黄金判据）。

        豁免：整张表被 setStyleSheet 覆盖、没走 fluent 双档体系的显式
        弱化标签（color: #8a8a8a / #777 等单档硬编码，R5 已知清单——
        它们自管颜色，不参与主题档位判定）。
        """
        bad = []
        for w in list(styleSheetManager.widgets):
            try:
                if w.visibleRegion().isNull():
                    continue
                act = w.styleSheet() or ""
                if act and "FluentLabelBase" not in act \
                        and act.strip().startswith("color:"):
                    continue                    # 显式弱化单档标签，豁免
                exp = render_for_widget(w, styleSheetManager.source(w))
                if exp.rstrip() != act.rstrip():
                    bad.append(type(w).__name__)
                    if detail:
                        print("       BAD %s dirty=%s qss=%r"
                              % (type(w).__name__, w.property("dirty-qss"),
                                 act[:60]))
            except Exception:
                continue
        return bad

    def dirty_count():
        return sum(1 for w in list(styleSheetManager.widgets)
                   if w.property("dirty-qss"))

    def plain_bad():
        """plain 输入类控件的 accent 小表是否停在旧档。"""
        bad = []
        tok = ui_theme.tokens().get("input_bg", "")
        for w in app.allWidgets():
            try:
                if not isinstance(w, ui_theme._plain_accent_classes()):
                    continue
            except Exception:
                continue
            qss = w.property("vt-accent-qss")
            if qss and tok and tok not in qss:
                bad.append(type(w).__name__)
        return bad

    def card_px(card):
        img = card.grab().toImage()
        if img.isNull():
            return None
        return img.pixelColor(min(8, img.width() - 1),
                              min(8, img.height() - 1)).name()

    def first_visible_card():
        for w in app.allWidgets():
            if isinstance(w, ui_theme.UICard) and not w.visibleRegion().isNull():
                return w
        return None

    PAGES = ("download_page", "library_page", "subtitle_page",
             "subtitle_edit_page", "pipeline_page", "settings_page")

    def walk_all_pages():
        """逐页显示，收集每页 VIS-BAD 与 dirty。"""
        results = {}
        for name in PAGES + ("auto_page",):
            p = getattr(win, name, None)
            if p is None:
                continue
            win.switchTo(p)
            pump(app, 500)
            results[name] = (len(scan_visible()), dirty_count())
        return results

    # ---------- S1-S6 正向 ----------
    def s1():
        return (qconfig.theme == ui_theme.qtheme()
                and isDarkTheme() == ui_theme.is_dark())

    def s2():
        """切档后当前可见控件全部新档（两个方向都验）。"""
        ok = True
        for mode in ("light", "dark", "light"):
            ui_theme.set_theme_mode(mode)
            pump(app, 500)
            bad = scan_visible()
            if bad:
                print("     S2 %s VIS-BAD=%d %s" % (mode, len(bad), bad[:3]))
                ok = False
        return ok

    def s3():
        """切档后 dirty 收敛：逐页显示，每页可见控件全部新档。"""
        # 先清 dirty 基线：上一轮断言遗留的 dirty=True 会被后续 walk 顺带
        # 补掉，掩盖 N2 的弄坏效果（负向假绿）。
        for w in list(styleSheetManager.widgets):
            try:
                w.setProperty("dirty-qss", False)
            except Exception:
                pass
        ui_theme.set_theme_mode("dark" if ui_theme.get_theme_mode() == "light"
                                else "light")
        pump(app, 400)
        d0 = dirty_count()
        res = {}
        bad_pages = {}
        for name in PAGES + ("auto_page",):
            p = getattr(win, name, None)
            if p is None:
                continue
            # 引擎页异步构建：显式就位后再判，否则读到构建中间态
            if name == "subtitle_page":
                try:
                    p.ensure_built()
                    for _ in range(40):      # 最多 10s 等引擎界面就绪
                        if getattr(p, "_engine", None) is not None:
                            break
                        pump(app, 250)
                except Exception:
                    pass
            win.switchTo(p)
            pump(app, 700)
            bad = scan_visible(detail=True)
            res[name] = (len(bad), dirty_count())
            if bad:
                bad_pages[name] = bad[:3]
        print("     S3 dirty@switch=%d pages=%s" % (d0, res))
        return (not bad_pages), d0

    def s4():
        bad = plain_bad()
        if bad:
            print("     S4 plain-bad=%d %s" % (len(bad), bad[:3]))
        return not bad

    def s5():
        """UICard 切档即重绘（未注册页 auto 的卡片）。"""
        win.switchTo(win.auto_page)
        pump(app, 700)
        card = first_visible_card()
        if card is None:
            print("     S5 auto 页无可见 UICard")
            return False
        cur = ui_theme.get_theme_mode()
        ui_theme.set_theme_mode("light" if cur == "dark" else "dark")
        pump(app, 700)
        a = card_px(card)
        ui_theme.set_theme_mode(cur)
        pump(app, 700)
        b = card_px(card)
        print("     S5 px %s -> %s -> %s" % (b, a, b))
        return a is not None and b is not None and a != b

    def s6():
        """同值早退无害：重复切当前档，S2 仍成立。"""
        ui_theme.set_theme_mode(ui_theme.get_theme_mode())
        pump(app, 400)
        return not scan_visible()

    print()
    print("=== 正向 S1-S6 ===")
    r_s1 = check("S1 启动双轨同档", s1())
    r_s2 = check("S2 切档即刷（当前可见控件）", s2())
    r_s3, d0 = s3()
    check("S3 dirty 收敛（逐页显示后可见控件全新档）", r_s3)
    check("S3b 切档确有 dirty 产生（懒链在工作）", d0 > 0, f"dirty={d0}")
    r_s4 = check("S4 plain 输入类同档", s4())
    r_s5 = check("S5 UICard 切档即重绘", s5())
    r_s6 = check("S6 同值早退无害", s6())

    # ---------- 负向 N1-N5：弄坏必须 FAIL ----------
    print()
    print("=== 负向 N1-N5（弄坏后对应断言必须 FAIL）===")

    # N1：tokens 钉死当前档 + refresh no-op → UICard 切档后仍画旧档色。
    #     不能只 patch refresh：card.grab() 自身会触发绘制，paintEvent
    #     现取 tokens 会绕过 refresh 让判据假绿——必须连 tokens 一起钉死。
    orig_refresh = ui_theme.refresh
    orig_tokens = ui_theme.tokens
    frozen = orig_tokens()
    ui_theme.refresh = lambda deep=False: None
    ui_theme.tokens = lambda: frozen
    n1_failed = not s5()
    ui_theme.refresh = orig_refresh
    ui_theme.tokens = orig_tokens
    check("N1 弄坏 tokens+refresh → S5 必须 FAIL", n1_failed)
    check("N1r 恢复 → S5 回 PASS", s5())

    # N2：弄坏 lazy 懒链——updateStyleSheet 退化成「只刷可见控件，不打
    #     dirty 也不 update」→ 隐藏页切页后永远补不上 → S3 必须 FAIL。
    #     （比吞 watcher 更彻底：dirty 属性都不设，watcher 想补也没标记。）
    import vt_fluent._theme as _t
    orig_uss = _t.updateStyleSheet

    def _visible_only(lazy=False):
        for widget, file in list(_t.styleSheetManager.items()):
            try:
                if not isinstance(widget, _t.QWidget):
                    continue
                if widget.visibleRegion().isNull():
                    continue                    # 隐藏：不打脏、不排重绘
                new = _t.render_for_widget(widget, file, _t.qconfig.theme)
                if new != widget.styleSheet():
                    widget.setStyleSheet(new)
            except Exception:
                pass
    _t.updateStyleSheet = _visible_only
    n2 = s3()
    _t.updateStyleSheet = orig_uss
    check("N2 弄坏 lazy 懒链 → S3 必须 FAIL", not n2[0])
    check("N2r 恢复懒链 → S3 回 PASS", s3()[0])

    # N3：_set_plain_accent 恒 False → 先切档让 plain 链该刷而未刷 → S4 FAIL
    orig_spa = ui_theme._set_plain_accent
    ui_theme._set_plain_accent = lambda w, q: False
    ui_theme.set_theme_mode("light" if ui_theme.get_theme_mode() == "dark"
                            else "dark")
    pump(app, 500)
    n3_failed = not s4()
    ui_theme._set_plain_accent = orig_spa
    check("N3 弄坏 plain-accent → S4 必须 FAIL", n3_failed)
    # 恢复后再切一次档，让 plain 表重新接管理
    ui_theme.set_theme_mode("light" if ui_theme.get_theme_mode() == "dark"
                            else "dark")
    pump(app, 500)
    check("N3r 恢复 plain-accent → S4 回 PASS", s4())

    # N4：render_for_widget 钉死 LIGHT → 切 dark 时 S2 必须 FAIL
    orig_rfw = _t.render_for_widget

    def _pin_light(widget, source, theme=None):
        return orig_rfw(widget, source, _t.Theme.LIGHT)
    _t.render_for_widget = _pin_light
    ui_theme.set_theme_mode("dark")
    pump(app, 500)
    n4_failed = bool(scan_visible())
    _t.render_for_widget = orig_rfw
    check("N4 钉死 LIGHT → S2 必须 FAIL", n4_failed)
    check("N4r 恢复渲染 → S2 回 PASS", s2())

    # N5：render_for_widget 第 N 次抛异常 → 修复前会中断全局刷新（S2 FAIL），
    #     修复后（except Exception 不中断）S2 仍 PASS —— 回归锚。
    state = {"n": 0}

    def _boom(widget, source, theme=None):
        state["n"] += 1
        if state["n"] == 40:
            raise ValueError("injected")
        return orig_rfw(widget, source, theme)
    _t.render_for_widget = _boom
    ui_theme.set_theme_mode("light")
    pump(app, 500)
    n5_ok = not scan_visible()          # 修复后期望：注入后仍全绿
    _t.render_for_widget = orig_rfw
    check("N5 注入异常后全局刷新不中断（R3 修复锚）", n5_ok,
          "（若 FAIL = except Exception 回归）")

    print()
    if FAILS:
        print("FAILED: %d 项 → %s" % (len(FAILS), FAILS))
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
