# -*- coding: utf-8 -*-
"""V2：「自动投稿」模板缺失拦截 / 放行 / 引导 —— GUI 探针（v2.4.2 热修配套）。

VT_DATA_ROOT 隔离（其下无 auto_vision/bili → 真实缺模板场景）；
VT_NO_SYNC=1 防 kb-sync 旧基线重放污染本地（项目铁律）。
断言打目标行为：弹窗标题/正文、worker 起停、阶段行归因文案。
"""
import os
import shutil
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
os.environ["VT_NO_SYNC"] = "1"
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ["VT_DATA_ROOT"] = os.path.join(ROOT, "build", "_bili_probe_data")

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

FAILS = []


def check(name, cond, extra=""):
    print(("[PASS] " if cond else "[FAIL] ") + name + (("  " + str(extra)) if extra else ""))
    if not cond:
        FAILS.append(name)


def pump(app, ms=800):
    end = time.time() + ms / 1000.0
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


class _W:
    hwnd = 0
    title = "probe-window"


def main():
    import shutil

    import numpy as np
    from PIL import Image
    import auto_vision_page as avp
    import bili_upload as bu

    # 负向锚点必须真实：每次运行先清空隔离数据目录，确保场景 1-3 面对
    # 的是「真实缺模板」现场（上次运行遗留的模板会让缺模板场景假绿）。
    probe_data = os.environ["VT_DATA_ROOT"]
    for sub in (("data", "auto_vision", "bili"),
                ("data", "bili_upload", "shots")):
        stale = os.path.join(probe_data, *sub)
        if os.path.isdir(stale):
            shutil.rmtree(stale)

    # 种子主题配置（2026-10-20 修复）：隔离目录没有 ui_custom.json 时
    # _default_cfg 落到 dark，与用户真实配置（权威源 data/ui_custom.json）
    # 可能不同档——拷一份进去，让探针渲染环境与真实程序同档。
    _real_cfg = os.path.join(ROOT, "data", "ui_custom.json")
    _iso_cfg = os.path.join(probe_data, "data", "ui_custom.json")
    if os.path.isfile(_real_cfg) and not os.path.isfile(_iso_cfg):
        os.makedirs(os.path.dirname(_iso_cfg), exist_ok=True)
        shutil.copy2(_real_cfg, _iso_cfg)

    app = QApplication.instance() or QApplication(sys.argv)
    # 与 main()（video_toolbox_qt.py）完全一致的启动主题初始化：此前探针
    # 裸构造页面，qconfig 停代码默认档、ui_theme 读隔离区配置，两轨错位
    # 渲染（浅档 QSS + 深色 UICard token 混搭 = 用户报的「色彩显示错误」）。
    import ui_theme
    ui_theme.apply_startup_theme(app)
    from vt_fluent import isDarkTheme, qconfig
    check("0.1 主题双轨同档", qconfig.theme == ui_theme.qtheme()
          and isDarkTheme() == ui_theme.is_dark(),
          f"qconfig={qconfig.theme} qtheme={ui_theme.qtheme()}")
    # 0.2 InfoBar（_tip 徽章）QSS 档位与主题轨一致——截图里曾出现
    # 「浅色框架 + 深色档徽章」的混搭（双轨错位的直观症状）。
    from vt_fluent import InfoBar, InfoBarPosition
    _bar = InfoBar.warning("档位自检", "x", duration=-1,
                           position=InfoBarPosition.BOTTOM_RIGHT)
    _want = ("rgb(67, 53, 25)" if ui_theme.is_dark()
             else "rgb(255, 244, 206)")
    check("0.2 InfoBar QSS 档位一致", _want in _bar.styleSheet())
    _bar.close()
    page = avp.AutoVisionPage()
    page.resize(1000, 780)
    page.show()
    pump(app, 500)

    # 表单前置校验素材：真实存在的文件 + 标题
    video = os.path.join(ROOT, "README.md")
    check("0 探针素材（文件路径）存在", os.path.isfile(video))
    page.bili_video.setText(video)
    page.bili_title.setText("探针投稿标题")
    page._selected_window = lambda: _W()

    seen = {"title": "", "text": "", "btn": None}

    def _auto_click(label):
        def _go():
            modal = app.activeModalWidget()
            if modal is None:
                return
            seen["title"] = modal.windowTitle()
            seen["text"] = modal.text()[:80]
            for b in modal.buttons():
                if b.text() == label:
                    seen["btn"] = label
                    b.click()
                    return
        return _go

    # ---- 场景 1：缺模板 → 弹拦截窗，点「取消」→ 不启动 ----
    QTimer.singleShot(400, _auto_click("取消"))
    page.btn_bili_run.click()
    pump(app, 900)
    check("1.1 弹窗标题含「模板」", "模板" in seen["title"], seen["title"])
    check("1.2 弹窗正文点名缺失项", "上传视频入口" in seen["text"], seen["text"])
    check("1.3 取消后 worker 未启动", page._bili_worker is None)
    check("1.4 阶段行保持未开始", page.bili_stage.text() == "尚未开始",
          page.bili_stage.text())

    # ---- 场景 2：点「仍要硬跑」→ force 放行，跑完归因含「模板」 ----
    seen["btn"] = None
    QTimer.singleShot(400, _auto_click("仍要硬跑"))
    page.btn_bili_run.click()
    pump(app, 900)
    check("2.1 硬跑放行（弹窗记录）", seen["btn"] == "仍要硬跑", seen["btn"])
    check("2.2 worker 已启动", page._bili_worker is not None)
    pump(app, 3000)
    stage = page.bili_stage.text()
    check("2.3 阶段行归因含「模板」", "模板" in stage, stage[:70])

    # ---- 场景 3：点「去采集模板」→ 不启动，滚动定位到采集卡 ----
    # 注意：_on_bili_done 不清空 _bili_worker（引用保留），判据用
    # 「未创建新 worker + 旧 worker 未在运行」，而不是 is None。
    w_before = page._bili_worker
    check("3.0 场景 2 worker 已结束", w_before is not None
          and not w_before.isRunning())
    seen["btn"] = None
    QTimer.singleShot(400, _auto_click("去采集模板"))
    page.btn_bili_run.click()
    pump(app, 900)
    check("3.1 去采集记录", seen["btn"] == "去采集模板", seen["btn"])
    check("3.2 未创建新 worker", page._bili_worker is w_before
          and not page._bili_worker.isRunning())

    # ---- 场景 4：预置 10 张必需模板 → 无弹窗直接启动 ----
    tdir = os.path.join(os.environ["VT_DATA_ROOT"], "data", "auto_vision", "bili")
    os.makedirs(tdir, exist_ok=True)
    rng = np.random.default_rng(7)
    for item in bu.TEMPLATE_MANIFEST:
        if item.get("optional"):
            continue
        Image.fromarray(rng.integers(0, 255, (24, 48, 3),
                                     dtype=np.uint8)).save(os.path.join(tdir, item["file"]))
    seen["btn"] = None
    seen["title"] = ""
    page._bili_refresh_tpl_combo()
    page.btn_bili_run.click()
    pump(app, 1200)
    check("4.1 模板齐备无弹窗", seen["title"] == "" and seen["btn"] is None,
          f"title={seen['title']!r} btn={seen['btn']!r}")
    check("4.2 worker 直接启动", page._bili_worker is not None)
    pump(app, 3000)
    check("4.3 状态行显示必需已齐", "已齐" in page.bili_tpl_status.text(),
          page.bili_tpl_status.text()[:60])

    # 弹窗中文渲染留证（真实窗口渲染，offscreen 无中文字体）
    shot = os.path.join(ROOT, "build", "_bili_guard_stage.png")
    page.grab().save(shot)
    print("    截图:", shot)

    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)} 项 → {FAILS}")
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main()
