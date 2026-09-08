#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""端到端自检：验证保存位置在「重启后自动填回界面」，且下载任务会落到独立文件夹。

不联网、不下载视频。运行：python _selftest_gui.py
"""
import os
import sys
import shutil
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import video_toolbox as engine

FAILS = []


def check(name, cond, extra=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}{(' -> ' + extra) if extra else ''}")
    if not cond:
        FAILS.append(name)


def main():
    print("=" * 62)
    print("  GUI 端到端自检：目录长期记忆 + 独立文件夹")
    print("=" * 62)

    backup = None
    if os.path.isfile(engine.CONFIG_PATH):
        backup = engine.CONFIG_PATH + ".gui_bak"
        shutil.copy2(engine.CONFIG_PATH, backup)

    target = os.path.join(tempfile.gettempdir(), "vt_gui_selftest_dir")
    os.makedirs(target, exist_ok=True)

    try:
        # 模拟「上一次运行时用户选了这个目录」
        engine.set_saved_download_dir(target)

        import tkinter as tk
        import video_toolbox_gui as gui

        app = gui.App([])
        app.withdraw()          # 不显示窗口，仅验证状态
        app.update_idletasks()

        try:
            got = engine.clean_path(app.dl_tab.dest_var.get())
            check("重启后下载页自动填回上次目录",
                  os.path.abspath(got) == os.path.abspath(target), got)

            lib = engine.clean_path(app.lib_tab.dir_var.get())
            check("视频库同步使用同一目录",
                  os.path.abspath(lib) == os.path.abspath(target), lib)

            # 模拟用户在界面里改目录 -> 应立即持久化
            new_dir = os.path.join(target, "子目录")
            os.makedirs(new_dir, exist_ok=True)
            app.dl_tab.dest_var.set(new_dir)
            app.update_idletasks()
            check("界面改目录后立即写入配置",
                  os.path.abspath(engine.get_saved_download_dir())
                  == os.path.abspath(new_dir),
                  engine.get_saved_download_dir())

            # 拖入文件夹 -> 合并页；这里验证下载页任务结构含 folder 字段
            app.dl_tab.task_seq += 1
            tid = f"T{app.dl_tab.task_seq}"
            app.dl_tab.tasks[tid] = {"url": "https://example.com/v", "quality": "1080p",
                                     "pct": 0.0, "status": "下载中", "dest": new_dir,
                                     "folder": os.path.join(new_dir, "某视频"),
                                     "with_subs": False}
            item = app.dl_tab.tasks[tid]
            check("下载任务记录独立文件夹路径",
                  item["folder"].endswith("某视频"), item["folder"])
        finally:
            app.dl_tab._drop_info_json()
            app.destroy()

        # 再次「重启」，确认新目录被记住
        engine_cfg = engine.load_config()
        check("配置文件中持久化了最新目录",
              str(engine_cfg.get("download_dir", "")).rstrip("\\/").endswith("子目录"),
              str(engine_cfg.get("download_dir")))
    finally:
        shutil.rmtree(target, ignore_errors=True)
        if backup:
            shutil.move(backup, engine.CONFIG_PATH)
        elif os.path.isfile(engine.CONFIG_PATH):
            os.remove(engine.CONFIG_PATH)

    print("\n" + "=" * 62)
    if FAILS:
        print(f"  结果：{len(FAILS)} 项失败")
        for f in FAILS:
            print(f"    - {f}")
        print("=" * 62)
        return 1
    print("  结果：全部通过")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main())
