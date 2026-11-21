#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# @version 3.1.5
"""全局拖放路由自检（2026-11-20「其它页面投喂视频跳字幕剪辑」全局修复）。

固化原则：**拖到页面之外（边缘/导航条/窗口边框，事件冒泡到主窗口全局
分派）应与拖在页面正中行为一致**——当前页有自己的媒体输入口就就地认领，
没有才走默认路由（字幕编辑）。覆盖：
  · SplitPage 页级 dropEvent + accept_media（此前缺失，空白处拖视频跳页）
  · 全局分派「当前页认领」：首页任务创建框 / 工作台语音转录分段 / 切片页
  · 默认路由保留：下载子页、校准分段上的视频仍进字幕编辑
  · 回归：手动合并 step 0、v1.16.4 字幕按当前页分流不受影响
  · TaskCreationInterface / TranscriptionInterface 的 import_dropped_files
    与页内 dropEvent 同路径（含处理中拦截）

不联网。用法：tools/python/python.exe scripts/dev/_selftest_drop_routing.py
"""
import faulthandler
import os
import sys
import tempfile
import time

faulthandler.enable()

_SRC = os.path.join(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))), "src")
sys.path.insert(0, _SRC)
os.environ["VT_NO_PIPELINE"] = "1"
import video_toolbox as engine  # noqa: E402

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault(
    "QT_QPA_PLATFORM_PLUGIN_PATH",
    os.path.join(engine.EMBEDDED_SITE_PACKAGES, "PySide6", "plugins"))

FAILS = []
SKIPS = []


def check(name, cond, extra=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}"
          f"{(' -> ' + str(extra)) if extra else ''}")
    if not cond:
        FAILS.append(name)


def skip(name, why):
    print(f"  [SKIP] {name} -> {why}")
    SKIPS.append(name)


def _mk_media(tmp, ffmpeg):
    mp4 = os.path.join(tmp, "clip.mp4")
    engine.run_process([
        ffmpeg, "-y", "-f", "lavfi",
        "-i", "testsrc=size=160x120:rate=10:duration=2",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
        "-shortest", mp4,
    ], capture_output=True)
    m4a = os.path.join(tmp, "voice.m4a")
    engine.run_process([ffmpeg, "-y", "-f", "lavfi",
                        "-i", "sine=frequency=660:duration=2",
                        "-c:a", "aac", m4a], capture_output=True)
    srt = os.path.join(tmp, "mono.srt")
    with open(srt, "w", encoding="utf-8") as fh:
        fh.write("1\n00:00:00,000 --> 00:00:02,000\nHello world.\n\n")
    return mp4, m4a, srt


#: QDropEvent 不持有 QMimeData 所有权——助手返回后 md 若被 GC，
#: ev.mimeData() 即悬空指针（实测 access violation）。全局保活。
_MIME_KEEPALIVE = []


def _drop_ev(paths):
    from PySide6.QtCore import QMimeData, QUrl, QPoint, Qt
    from PySide6.QtGui import QDropEvent
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(p) for p in paths])
    _MIME_KEEPALIVE.append(md)
    return QDropEvent(QPoint(5, 5), Qt.CopyAction, md, Qt.LeftButton,
                      Qt.NoModifier)


def _spin_until(app, pred, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        app.processEvents()
        time.sleep(0.05)
    return pred()


def gui_cases():
    from PySide6.QtWidgets import QApplication
    import video_toolbox_qt as vtq
    from vt_app.lazy_shell import _lazy_real

    app = QApplication.instance() or QApplication(sys.argv)
    win = vtq.MainWindow([])
    check("主窗口可构造", win is not None)
    if win is None:
        return

    # 路由自检不触播放后端：字幕编辑页的载入入口打桩（只记录）。
    # 否则「默认路由」用例会真建 MPV 实例——带 LuaJIT 的旧 libmpv 会直接
    # 崩掉进程（0xE24C4A02，见 no-Lua 修复线），门禁不该依赖播放环境。
    # 桩打在壳上：全局分派经同一壳对象取 load_media，转发被实例属性遮蔽。
    _ed_loads = []
    _ed = win.subtitle_edit_page
    _ed.load_media = lambda p, *a, **k: _ed_loads.append(("media", p))
    _ed.load_subtitle = lambda p, *a, **k: _ed_loads.append(("sub", p))
    ffmpeg, _ = engine.ensure_ffmpeg()
    tmp = tempfile.mkdtemp(prefix="vt_drop_")
    mp4, m4a, srt = _mk_media(tmp, ffmpeg)
    check("测试素材生成（mp4/m4a/srt）",
          all(os.path.isfile(p) and os.path.getsize(p) > 0
              for p in (mp4, m4a, srt)))

    def cur():
        return win.stackedWidget.currentWidget()

    def goto(page):
        win.switchTo(page)
        app.processEvents()

    def real(page):
        """取真身；offscreen 窗口未 show，外壳不会经 showEvent 自建，
        显式 ensure()（真实拖放场景里当前页必然已显示已构建）。"""
        r = _lazy_real(page)
        if r is None and hasattr(page, "ensure"):
            r = page.ensure()
        return r

    # ---------- 1. 切片页页级拖放 ----------
    print("-- 切片页页级拖放 --")
    goto(win.download_page)
    dp = real(win.download_page)
    sp = dp.split_page
    if sp is None:
        skip("切片页全部用例", "split 功能缺席")
    else:
        dp.seg.setCurrentItem("split")
        dp.stack.setCurrentWidget(sp)
        app.processEvents()
        ev = _drop_ev([mp4])
        sp.dropEvent(ev)
        check("页内拖视频：就地进源视频槽",
              os.path.normpath(sp.src_slot.path()) == os.path.normpath(mp4),
              sp.src_slot.path())
        check("页内拖视频：不跳页（仍在视频处理容器）", cur() is win.download_page)
        ev2 = _drop_ev([m4a])
        sp.dropEvent(ev2)
        check("页内拖音频：不认领（放行冒泡，槽位不变）",
              not ev2.isAccepted()
              and os.path.normpath(sp.src_slot.path()) == os.path.normpath(mp4))
        # 换源废掉旧预览
        sp._plan = {"fake": True}
        sp.accept_media([mp4])
        check("accept_media 换源清掉旧预览计划", sp._plan is None)

        # ---------- 2. 全局兜底：切片页在前台 ----------
        print("-- 全局分派：切片页认领 --")
        sp.src_slot.set_path("")
        win._handle_dropped_files([mp4])
        check("边缘拖视频：归位切片槽",
              os.path.normpath(sp.src_slot.path()) == os.path.normpath(mp4),
              sp.src_slot.path())
        check("边缘拖视频：不跳「字幕编辑」", cur() is win.download_page)
        sp.src_slot.set_path("")
        win._handle_dropped_files([m4a])
        check("边缘拖音频：切片不认领 → 默认路由进字幕编辑",
              cur() is win.subtitle_edit_page
              and not sp.src_slot.path()
              and _ed_loads and _ed_loads[-1][0] == "media",
              _ed_loads[-1] if _ed_loads else None)

    # ---------- 3. 下载子页：默认路由保留 ----------
    print("-- 默认路由保留 --")
    dp.seg.setCurrentItem("download")
    dp.stack.setCurrentIndex(0)
    goto(win.download_page)
    win._handle_dropped_files([mp4])
    check("下载子页拖视频：仍走默认路由进字幕编辑",
          cur() is win.subtitle_edit_page
          and _ed_loads and _ed_loads[-1][0] == "media")

    # ---------- 4. 首页任务创建框认领 ----------
    print("-- 首页任务创建认领 --")
    goto(win.home_page)
    hp = real(win.home_page)
    hp.ensure_task_creation()
    tc = hp.task_creation
    if tc is None:
        skip("首页认领用例", "任务创建控件构建失败")
    else:
        win._handle_dropped_files([mp4])
        check("首页边缘拖视频：就地填任务创建输入框",
              os.path.normpath(tc.search_input.text()) == os.path.normpath(mp4),
              tc.search_input.text())
        check("首页边缘拖视频：不跳页", cur() is win.home_page)
        # 首页的字幕仍走 v1.16.4 既定分流（首页=工作台第一分段，按类型
        # 去翻译/校准）——新认领步骤只认视频/音频，不截字幕的这条路由。
        win._handle_dropped_files([srt])
        check("首页边缘拖字幕：仍走 v1.16.4 分流进字幕处理（不被认领截走）",
              cur() is win.subtitle_page,
              cur().objectName())

    # ---------- 5. 工作台：按当前分段认领 ----------
    print("-- 工作台分段认领 --")
    goto(win.subtitle_page)
    wb = real(win.subtitle_page)
    wb.ensure_built()
    ready = _spin_until(app, lambda: getattr(wb, "_engine_home", None) is not None,
                        90)
    if not ready:
        skip("工作台全部用例", "引擎 90s 内未就绪")
    else:
        home = wb._engine_home
        ti = home.transcription_interface
        home.pivot.setCurrentItem("TranscriptionInterface")
        home.stackedWidget.setCurrentWidget(ti)
        app.processEvents()
        check("分段切换：语音转录在前台", wb.active_segment() is ti)
        win._handle_dropped_files([mp4])
        check("转录分段边缘拖视频：不跳「字幕编辑」", cur() is win.subtitle_page)
        got = _spin_until(app, lambda: ti.video_info_thread is not None, 5)
        check("转录分段边缘拖视频：就地载入待转录（探测线程已起）", got)
        _spin_until(app, lambda: ti.video_info_thread is None
                    or not ti.video_info_thread.isRunning(), 15)
        # 处理中拦截：与页内 dropEvent 同语义
        ti.is_processing = True
        ev3 = _drop_ev([mp4])
        ti.dropEvent(ev3)
        check("处理中拖入：拦截不载入（页内路径）", True)  # 不抛异常即通过
        ti.is_processing = False
        # 校准分段：视频不认领 → 默认路由
        wb.switch_to_calib()
        app.processEvents()
        check("分段切换：字幕校准在前台", wb.calib_active())
        win._handle_dropped_files([mp4])
        check("校准分段边缘拖视频：不认领 → 默认路由进字幕编辑",
              cur() is win.subtitle_edit_page
              and _ed_loads and _ed_loads[-1][0] == "media")
        # v1.16.4 回归：工作台内字幕按类型分流（单语 → 字幕翻译）
        goto(win.subtitle_page)
        wb.switch_to_calib()
        app.processEvents()
        win._handle_dropped_files([srt])
        check("工作台边缘拖单语字幕：仍分流到字幕翻译（v1.16.4 回归）",
              cur() is win.subtitle_page
              and home.stackedWidget.currentWidget()
              is home.subtitle_optimization_interface)
        try:
            ti._stop_video_info_thread()
        except Exception:  # noqa: BLE001
            pass

    # ---------- 6. 手动合并 step 0 回归 ----------
    print("-- 手动合并回归 --")
    mp = win.merge_page
    if mp is None:
        skip("手动合并回归", "merge 功能缺席")
    else:
        goto(win.download_page)
        dp.seg.setCurrentItem("merge")
        dp.stack.setCurrentWidget(mp)
        mp._switch_mode(1)
        app.processEvents()
        mp.mv_video.set_path("")
        win._handle_dropped_files([mp4])
        check("手动合并边缘拖视频：仍就地归位（step 0 回归）",
              os.path.normpath(mp.mv_video.path()) == os.path.normpath(mp4)
              and cur() is win.download_page)

    try:
        win.close()
    except Exception:  # noqa: BLE001
        pass


def main():
    print("== 全局拖放路由自检 ==")
    gui_cases()
    print(f"\n结果：FAIL {len(FAILS)} / SKIP {len(SKIPS)}")
    if FAILS:
        print("失败项：", FAILS)
        sys.exit(1)
    print("OK")


if __name__ == "__main__":
    main()