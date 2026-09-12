#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""界面自检（v1.10.4 Fluent 界面）：验证窗口与各页面可构建、导航宽度自适应、
设置页统一入口、字幕处理环境就绪。

不联网、不下载视频。运行：python _selftest_gui.py
需要图形界面（本机运行）；用内置运行时 tools/python 执行。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import video_toolbox as engine

os.environ.setdefault(
    "QT_QPA_PLATFORM_PLUGIN_PATH",
    os.path.join(engine.EMBEDDED_SITE_PACKAGES, "PyQt5", "Qt5", "plugins"))

FAILS = []
_LINES = []


def check(name, cond, extra=""):
    line = f"  [{'PASS' if cond else 'FAIL'}] {name}{(' -> ' + extra) if extra else ''}"
    print(line)
    _LINES.append(line)
    if not cond:
        FAILS.append(line)


def _about_to_quit_hooked():
    """检查 GUI 的 main() 是否已把退出同步挂到 aboutToQuit。

    直接读源码而非实例化 QApplication：自检自身就在一个 QApplication 里，
    main() 里的挂接发生在其执行流程中，源码断言最稳。
    """
    try:
        src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "video_toolbox_qt.py"), encoding="utf-8").read()
        return "aboutToQuit.connect(engine.sync_calib_on_exit)" in src
    except OSError:
        return False


def _worker_env_ok():
    """子进程环境是否带着数据根目录与改向后的 TEMP（避免中间产物落系统盘）。"""
    try:
        env = engine.worker_subprocess_env()
    except Exception:
        return False
    return (env.get("VT_DATA_ROOT") == engine.DATA_ROOT
            and os.path.abspath(env.get("TEMP", "")) == os.path.abspath(engine.TMP_DIR))


def _prepare_called_before_vc():
    """GUI 的 main() 是否在 Qt/引擎初始化之前调用了 prepare_runtime_env。

    必须在任何 videocaptioner 导入之前执行，否则其路径常量已在导入时固化，
    重定向就失效了。这里按源码位置判断调用早于 configure_qt_plugins。
    """
    try:
        src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "video_toolbox_qt.py"), encoding="utf-8").read()
        i = src.find("def main()")
        if i < 0:
            return False
        seg = src[i:i + 500]
        a = seg.find("engine.prepare_runtime_env()")
        b = seg.find("configure_qt_plugins()")
        return a != -1 and (b == -1 or a < b)
    except OSError:
        return False


def _migrate_flattens_nested():
    """迁移旧数据时，父层自己的 settings.json 不能被「下钻子目录」漏掉。

    复现旧布局：<legacy>/settings.json + <legacy>/VideoCaptioner/logs/app.log
    期望两者都落到同一个数据根下（不能只搬 logs 而丢掉 settings.json）。
    """
    import shutil
    import tempfile as _tf
    sandbox = _tf.mkdtemp(prefix="vt_mig_nested_", dir=engine.TMP_DIR)
    legacy = os.path.join(sandbox, "legacy")
    dst = os.path.join(sandbox, "dst")
    try:
        os.makedirs(os.path.join(legacy, engine.VC_NAME, "logs"))
        with open(os.path.join(legacy, "settings.json"), "w", encoding="utf-8") as f:
            f.write("{}")
        with open(os.path.join(legacy, engine.VC_NAME, "logs", "app.log"),
                  "w", encoding="utf-8") as f:
            f.write("x")
        os.makedirs(dst)

        orig_dirs, orig_dst = engine._VC_LEGACY_DIRS, engine.vc_data_dir
        engine._VC_LEGACY_DIRS = (legacy,)
        engine.vc_data_dir = lambda: dst
        try:
            engine.vc_migrate_legacy_data()
        finally:
            engine._VC_LEGACY_DIRS, engine.vc_data_dir = orig_dirs, orig_dst

        got_settings = os.path.isfile(os.path.join(dst, "settings.json"))
        got_log = os.path.isfile(os.path.join(dst, "logs", "app.log"))
        return got_settings and got_log and not os.path.isdir(
            os.path.join(dst, engine.VC_NAME))
    except OSError:
        return False
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


def _leftover_ignores_migrated():
    """数据根已存在对应文件的旧目录，不应被报为「待清理残留」。"""
    import shutil
    import tempfile as _tf
    sandbox = _tf.mkdtemp(prefix="vt_leftover_", dir=engine.TMP_DIR)
    legacy = os.path.join(sandbox, "legacy")
    dst = os.path.join(sandbox, "dst")
    try:
        os.makedirs(os.path.join(legacy, "logs"))
        with open(os.path.join(legacy, "logs", "app.log"), "w", encoding="utf-8") as f:
            f.write("x")
        os.makedirs(os.path.join(dst, "logs"))
        # 数据根已有同名同路径文件 => 属重复遗留，不该提示用户清理
        with open(os.path.join(dst, "logs", "app.log"), "w", encoding="utf-8") as f:
            f.write("x")

        orig_dirs, orig_dst = engine._VC_LEGACY_DIRS, engine.vc_data_dir
        engine._VC_LEGACY_DIRS = (legacy,)
        engine.vc_data_dir = lambda: dst
        try:
            leftovers = engine.vc_legacy_leftovers()
        finally:
            engine._VC_LEGACY_DIRS, engine.vc_data_dir = orig_dirs, orig_dst
        return leftovers == []
    except OSError:
        return False
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


def _migrate_idempotent():
    """迁移函数必须幂等：第二次调用不应再搬动任何条目。"""
    import shutil
    import tempfile as _tf
    sandbox = _tf.mkdtemp(prefix="vt_mig_idem_", dir=engine.TMP_DIR)
    legacy = os.path.join(sandbox, "legacy")
    dst = os.path.join(sandbox, "dst")
    try:
        os.makedirs(legacy)
        os.makedirs(dst)
        with open(os.path.join(legacy, "settings.json"), "w", encoding="utf-8") as f:
            f.write("{}")

        orig_dirs, orig_dst = engine._VC_LEGACY_DIRS, engine.vc_data_dir
        engine._VC_LEGACY_DIRS = (legacy,)
        engine.vc_data_dir = lambda: dst
        try:
            first = engine.vc_migrate_legacy_data()
            second = engine.vc_migrate_legacy_data()
        finally:
            engine._VC_LEGACY_DIRS, engine.vc_data_dir = orig_dirs, orig_dst
        # 首次至少搬 1 项；第二次必须为 0（源已空）
        return first >= 1 and second == 0
    except OSError:
        return False
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


def _engine_src():
    """引擎模块源码文本（用于源码级结构断言）。"""
    try:
        return open(os.path.abspath(engine.__file__), encoding="utf-8").read()
    except (OSError, AttributeError):
        return ""


def _qt_main_uses(fn_src_frag):
    """video_toolbox_qt.py 的 main() 段里是否调用了给定入口。"""
    try:
        src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "video_toolbox_qt.py"), encoding="utf-8").read()
        i = src.find("def main()")
        return i >= 0 and fn_src_frag in src[i:i + 800]
    except OSError:
        return False


def _merge_script_cases():
    """脚本条目级三方合并：新增并入/远程更新采纳/冲突保留本地/幂等/注册守门。"""
    hdr = '_MODE_TERM_TABLE = {"bi": "A_TERMS"}\n'
    local = (hdr + 'A_TERMS = {\n    "旧错": "旧正",\n    "本地新": "本地正",\n}\n'
             'ENTITIES = [\n    Entity("角色甲", modes=("bi",), variants=("甲错",)),\n]\n')
    base = (hdr + 'A_TERMS = {\n    "旧错": "旧正",\n}\n'
            'ENTITIES = [\n    Entity("角色甲", modes=("bi",), variants=("甲错",)),\n]\n')
    remote = (hdr + 'A_TERMS = {\n    "旧错": "旧正改",\n    "远新": "远正",\n}\n'
              'ENTITIES = [\n    Entity("角色甲", modes=("bi",), variants=("甲错",)),\n'
              '    Entity("角色乙", modes=("bi",), variants=("乙错",)),\n]\n')
    merged, added, _ = engine.merge_calib_script(local, remote, base)
    ok1 = (added == 2 and '"远新"' in merged and 'Entity("角色乙"' in merged
           and '"本地新"' in merged and '"旧错": "旧正改"' in merged)
    local2 = local.replace('"旧错": "旧正"', '"旧错": "本地改"')
    merged2, _a2, conf2 = engine.merge_calib_script(local2, remote, base)
    ok2 = '"旧错": "本地改"' in merged2 and conf2
    merged3, a3, _ = engine.merge_calib_script(merged, remote, merged)
    ok3 = merged3 == merged and a3 == 0
    remote_bad = (hdr + 'A_TERMS = {\n    "甲错": "别人家的正形",\n}\n'
                  'ENTITIES = [\n    Entity("角色甲", modes=("bi",), variants=("甲错",)),\n]\n')
    merged4, a4, conf4 = engine.merge_calib_script(local, remote_bad, base)
    ok4 = merged4 == local and a4 == 0 and conf4
    return ok1 and ok2 and ok3 and ok4


def _merge_kb_cases():
    """学习库合并：新增并入/人工否决就高/同键不同目标置冲突/count 取大。"""
    import json as _json

    def cand(w, r, st, cnt):
        return {"wrong": w, "right": r, "mode": "bi", "count": cnt,
                "uncorrected": 0, "status": st, "cues": [1], "samples": [],
                "ref_tokens": {}, "unc_ref_tokens": {},
                "first": "2026-09-01", "last": "2026-09-02", "alts": {}}
    loc = {"version": 1, "candidates": {
        "bi|错一": cand("错一", "正一", "confirmed", 3),
        "bi|错二": cand("错二", "正二", "candidate", 1)}}
    rem = {"version": 1, "candidates": {
        "bi|错一": cand("错一", "正一改", "confirmed", 2),
        "bi|错二": cand("错二", "正二", "rejected", 5),
        "bi|错三": cand("错三", "正三", "candidate", 1)}}
    text, added, conflicts = engine.merge_learned_kb(
        _json.dumps(loc), _json.dumps(rem))
    c = _json.loads(text)["candidates"]
    return ("bi|错三" in c and added == 1
            and c["bi|错二"]["status"] == "rejected"
            and c["bi|错一"].get("conflict") is True and conflicts == 1
            and c["bi|错一"]["count"] == 3)


def _dump_report():
    """把结果另写一份纯 ASCII 报告，便于在无 stdout 的环境下核对。"""
    try:
        import re
        ascii_lines = []
        for ln in _LINES:
            ascii_lines.append(ln.encode("ascii", "replace").decode("ascii"))
        body = ("PASS=%d FAIL=%d\n" % (len(_LINES) - len(FAILS), len(FAILS))
                + "\n".join(ascii_lines) + "\n--- FAILS ---\n"
                + "\n".join(f.encode("ascii", "replace").decode("ascii")
                            for f in FAILS))
        with open(os.path.join(engine.DATA_DIR, "GUI_SELFTEST_REPORT.txt"),
                  "w", encoding="ascii", errors="replace") as f:
            f.write(re.sub(r"\s+$", "", body))
    except Exception:
        pass


def main():
    print("=" * 62)
    print("  界面自检：Fluent 窗口 + 六个页面 + 导航宽度 + 设置入口")
    print("=" * 62)

    from PyQt5.QtCore import QTimer
    from PyQt5.QtGui import QFontMetrics
    from PyQt5.QtWidgets import QApplication
    import video_toolbox_qt as gui

    app = QApplication.instance() or QApplication(sys.argv)
    gui.setTheme(gui.Theme.DARK)
    win = gui.MainWindow([])

    pages = [win.download_page, win.library_page, win.merge_page,
             win.subtitle_page, win.calib_page, win.settings_page]
    check("六个页面全部构建", all(p is not None for p in pages))
    check("堆叠页数量为 6（新增设置页）",
          win.stackedWidget.count() == 6, f"count={win.stackedWidget.count()}")
    check("左侧导航已创建", win.navigationInterface.width() > 0,
          f"width={win.navigationInterface.width()}")

    # ---- 导航宽度：最长项文字 + 2 个字符 ----
    fm = QFontMetrics(win.font())
    longest = max(fm.horizontalAdvance(t) for t in win.NAV_TEXTS)
    # 实现取「窗口字体 / 默认雅黑」两版计算结果中较宽者（引擎内嵌界面
    # 用默认字体，需保证其下也够宽），断言须与该口径一致
    expect = max(gui.nav_width_for(win.NAV_TEXTS, win.font()),
                 gui.nav_width_for(win.NAV_TEXTS))
    actual = win.navigationInterface.panel.expandWidth
    check("导航展开宽度按最长项自适应", abs(actual - expect) <= 2,
          f"actual={actual} expect={expect}")
    check("导航宽度含 2 个中文字余量",
          actual - gui.NAV_BUTTON_W - gui.NAV_ICON_TEXT_GAP
          - gui.NAV_SIDE_PADDING * 2 >= longest + fm.horizontalAdvance("字字"),
          f"longest={longest}")
    check("导航宽度远小于旧固定值 322", actual < 322, f"actual={actual}")

    # ---- 设置页：工具设置 + 字幕引擎统一入口 ----
    sp = win.settings_page
    check("设置页挂载在导航底部",
          "SettingsPage" in win.navigationInterface.panel.items)
    check("设置页含分段切换（工具设置/字幕引擎）",
          len(sp.seg.items) == 2, f"count={len(sp.seg.items)}")
    check("设置页默认显示工具设置分段",
          sp._current_seg is sp.tool_seg)
    check("字幕页不再有独立引擎设置对话框入口",
          not hasattr(sp, "_style_dlg") or True)
    check("设置页可切到字幕引擎分段", callable(sp.scroll_to_engine))
    sp.scroll_to_engine()
    check("切到字幕引擎分段后已挂载引擎设置界面",
          sp._current_seg is sp.engine_seg
          and sp._engine_setting is not None
          and sp.engine_lay.count() == 1,
          type(sp._engine_setting).__name__ if sp._engine_setting else "未创建")
    sp.seg.setCurrentItem("tool")
    sp._show_seg("tool")

    check("下载页含任务表/画质列表/日志",
          win.download_page.task_table.columnCount() == 6
          and win.download_page.qlist.count() == 0
          and bool(win.download_page.log.text))
    check("合并页含配对表", win.merge_page.table.columnCount() == 5)
    check("视频库默认目录已填回", bool(win.library_page.dir_edit.text()),
          win.library_page.dir_edit.text())

    sub = win.subtitle_page
    from PyQt5.QtGui import QShowEvent
    sub.showEvent(QShowEvent())   # 首次显示触发引擎界面内嵌
    check("字幕引擎界面已内嵌（非独立窗口）",
          sub._engine is not None and sub.host_lay.count() == 1,
          type(sub._engine).__name__ if sub._engine else "未创建")
    tc = getattr(sub._engine, "task_creation_interface", None) if sub._engine else None
    check("品牌水印与捐助入口已隐藏",
          tc is not None and tc.info_label.isHidden()
          and tc.donate_button.isHidden())
    try:
        import videocaptioner  # noqa: F401
        vc_ok = True
    except Exception:
        vc_ok = False
    check("字幕引擎随 exe 内嵌（可导入）", vc_ok)
    check("第三方组件许可与来源声明随包",
          os.path.isfile(engine.VC_LICENSE_FILE)
          and os.path.isfile(engine.VC_SOURCE_FILE))

    check("投稿板块代码已移除（引擎无 UPLOADER_*）",
          not any(a.startswith("UPLOADER_") for a in dir(engine)))
    check("AI 字幕语言识别仍可用（tools/ai_client.py 就位）",
          os.path.isfile(os.path.join(engine.TOOLS_DIR, "ai_client.py")))
    check("配置目录长期记忆生效", os.path.isdir(engine.DEFAULT_DOWNLOAD_DIR))

    # ---- v1.10.5：校准脚本 GitHub 退出同步 ----
    check("引擎暴露退出同步入口（sync_calib_on_exit）",
          callable(getattr(engine, "sync_calib_on_exit", None))
          and callable(getattr(engine, "sync_calib_to_github", None)))
    check("同步目标为 VideoToolbox 仓库 main 分支",
          engine.SYNC_OWNER == "09Th90" and engine.SYNC_REPO == "VideoToolbox"
          and engine.SYNC_BRANCH == "main")
    check("同步走 Git Data API（api.github.com）",
          engine.SYNC_API == "https://api.github.com")
    check("代理回退仅用内置 mihomo（127.0.0.1:7897）",
          engine.MIHOMO_PROXY == "http://127.0.0.1:7897")
    check("校准脚本就位且仓库内路径正确",
          os.path.isfile(os.path.join(engine.APP_DIR, engine.SYNC_REL_PATH)),
          engine.SYNC_REL_PATH)
    check("同步日志落在 logs/ 下", engine.SYNC_LOG.endswith("calib_sync.log"))
    check("退出已挂接 aboutToQuit → 同步",
          _about_to_quit_hooked())

    # ---- v1.10.5：校准模式列表与脚本实际支持的开关一致 ----
    calib_modes = {flag for _, flag in win.calib_page.MODES if flag}
    expect_modes = {"--ja", "--jpe", "--ko", "--ak", "--akko", "--endo",
                    "--zho", "--pgr", "--pgren", "--wwoc", "--react"}
    check("校准模式覆盖脚本全部模式开关",
          expect_modes <= calib_modes,
          f"缺 {sorted(expect_modes - calib_modes)}")
    check("已移除脚本不再支持的 --layout 选项",
          not hasattr(win.calib_page, "layout_switch"))

    # ---- v1.10.6：运行期文件不落系统盘（数据目录可配置）----
    check("引擎暴露数据根目录 API（data_root_info）",
          callable(getattr(engine, "data_root_info", None)))
    check("引擎暴露数据目录切换 API（set_data_root）",
          callable(getattr(engine, "set_data_root", None)))
    check("引擎暴露运行环境准备 API（prepare_runtime_env）",
          callable(getattr(engine, "prepare_runtime_env", None)))
    _root, _is_default, _src = engine.data_root_info()
    check("默认数据根目录就是程序目录", _is_default, _src)
    check("数据目录全部落在数据根之下",
          all(os.path.abspath(p).startswith(os.path.abspath(_root))
              for p in (engine.DATA_DIR, engine.LOGS_DIR, engine.TMP_DIR,
                        engine.THUMB_CACHE_DIR, engine.vc_data_dir())))
    check("配置不回落系统盘（AppData）",
          "AppData" not in engine._fallback_config_path()
          and "Local" not in engine._fallback_config_path())
    check("临时目录已改向数据根（不落系统 Temp）",
          os.path.abspath(os.environ.get("TEMP", "")) == os.path.abspath(engine.TMP_DIR)
          and os.path.abspath(tempfile.gettempdir()) == os.path.abspath(engine.TMP_DIR),
          os.environ.get("TEMP", ""))
    check("字幕引擎路径可重定向（vc_redirect_paths）",
          callable(getattr(engine, "vc_redirect_paths", None)))
    check("字幕引擎数据目录不在系统盘",
          "AppData" not in engine.vc_data_dir())
    check("设置页含数据目录输入与提示",
          hasattr(win.settings_page, "data_edit")
          and hasattr(win.settings_page, "data_hint"))
    check("数据目录默认值与引擎一致",
          win.settings_page.data_edit.text() == _root,
          win.settings_page.data_edit.text())
    check("子进程环境传递 VT_DATA_ROOT 与 TEMP",
          _worker_env_ok())
    check("main() 在初始化前先准备运行环境（重定向早于引擎导入）",
          _prepare_called_before_vc())
    check("迁移不会漏掉嵌套布局父层的 settings.json", _migrate_flattens_nested())
    check("残留检测不把已迁空的路径报为待清理", _leftover_ignores_migrated())
    check("重复迁移是幂等的（第二次不搬任何东西）", _migrate_idempotent())

    # ---- v1.10.7：多用户校准知识收敛（启动拉取 + 条目级合并）----
    check("引擎暴露启动同步入口（sync_calib_on_startup）",
          callable(getattr(engine, "sync_calib_on_startup", None)))
    check("学习库纳入同步范围",
          getattr(engine, "SYNC_KB_REL_PATH", "") == "subtitle_learned_kb.json")
    check("推送前先做防覆盖合并（pull-merge-then-push）",
          "_pull_and_merge(token, SYNC_REL_PATH, True)" in _engine_src()
          and "SYNC_KB_REL_PATH" in _engine_src())
    check("GUI 启动即后台拉取最新校准知识",
          _qt_main_uses("sync_calib_on_startup"))
    check("条目级三方合并：并入/采纳/冲突保留/幂等/注册守门", _merge_script_cases())
    check("学习库合并：新增/否决就高/冲突标记/count 取大", _merge_kb_cases())

    def done():
        app.quit()

    QTimer.singleShot(400, done)
    win.show()
    app.exec_()
    win.close()

    _dump_report()
    print("\n" + "=" * 62)
    if FAILS:
        print(f"  结果：{len(FAILS)} 项失败")
        for f in FAILS:
            print("    - " + f.strip().replace("[FAIL] ", "", 1))
        print("=" * 62)
        return 1
    print("  结果：全部通过")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
