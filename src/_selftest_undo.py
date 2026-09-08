#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线自检：输入框 Ctrl+Z / Ctrl+Y 撤销重做（Tk 8.6 原生无此能力，手写栈验证）。

不联网。运行：python _selftest_undo.py
"""
import os
import sys
import time
import shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tkinter as tk
from tkinter import ttk
import video_toolbox as engine
import video_toolbox_gui as gui

FAILS = []


def check(name, cond, extra=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}{(' -> ' + extra) if extra else ''}")
    if not cond:
        FAILS.append(name)


def mk(root):
    var = tk.StringVar(value="")
    ent = ttk.Entry(root, textvariable=var)
    ent.pack()
    ctrl = gui.attach_entry_undo(ent, var)
    root.update()
    return var, ent, ctrl


def test_basic(root):
    print("\n[1] 基本撤销 / 重做")
    var, ent, ctrl = mk(root)

    var.set("第一段")
    time.sleep(0.7)                     # 越过合并时间窗，下一批独立成步
    var.set("第一段+第二段")
    check("初始两次程序改动后文本正确", var.get() == "第一段+第二段")

    ctrl.undo()
    check("Ctrl+Z 回到上一状态", var.get() == "第一段", repr(var.get()))
    ctrl.undo()
    check("再撤销回到空", var.get() == "", repr(var.get()))
    check("空栈后继续撤销不报错", ctrl.undo() == "break" and var.get() == "")

    ctrl.redo()
    check("Ctrl+Y 重做一步", var.get() == "第一段", repr(var.get()))
    ctrl.redo()
    check("再重做一次", var.get() == "第一段+第二段", repr(var.get()))
    check("重做到头不报错", ctrl.redo() == "break")


def test_typing_group(root):
    print("\n[2] 连续打字合并为一步，粘贴独立成步")
    var, ent, ctrl = mk(root)

    for ch in "abcdef":                  # 模拟快速连续输入（同一时间窗）
        ent.insert("end", ch)
        root.update()
    time.sleep(0.7)
    var.set("abcdef" + "整段粘贴的内容")  # 模拟粘贴（大幅变化，独立步）
    ctrl.undo()
    check("撤销一步 = 撤销粘贴整段", var.get() == "abcdef", repr(var.get()))
    ctrl.undo()
    check("再撤销一步 = 打字的六个字母整组消失", var.get() == "", repr(var.get()))

    # 新修改应清空 redo 链
    ctrl.redo()
    check("先恢复一步", var.get() == "abcdef")
    var.set("xyz")
    check("产生新修改后 redo 链被清空", ctrl.redo() == "break" and var.get() == "xyz",
          repr(var.get()))


def test_keybind():
    print("\n[3] 键盘事件真实触发绑定")
    # event_generate 只会投递到"已映射"的窗口；这里单独开一个移出屏幕的窗口，
    # 既不干扰其它隐藏窗口测试，也贴近真实按键路径。
    w = tk.Tk()
    w.geometry("300x60-32000-32000")
    w.deiconify()
    try:
        var = tk.StringVar(value="")
        ent = ttk.Entry(w, textvariable=var)
        ent.pack()
        ctrl = gui.attach_entry_undo(ent, var)
        var.set("AAA")
        time.sleep(0.7)
        var.set("BBBB")
        ent.focus_force()
        w.update()
        ent.event_generate("<Control-z>")
        w.update()
        check("Ctrl+Z 按键生效", var.get() == "AAA", repr(var.get()))
        ent.event_generate("<Control-y>")
        w.update()
        check("Ctrl+Y 按键生效", var.get() == "BBBB", repr(var.get()))
        ent.event_generate("<Control-Shift-Z>")
        w.update()
        check("Ctrl+Shift+Z（无重做时）不破坏文本", var.get() == "BBBB")
    finally:
        w.destroy()



def test_cursor_restore(root):
    print("\n[4] 撤销后光标位置还原")
    var, ent, ctrl = mk(root)
    ent.insert("end", "0123456789")
    ent.icursor(10)
    time.sleep(0.7)
    ent.insert("end", "abc")              # 从 10 开始追加
    ctrl.undo()
    check("撤销后光标回到追加前", ent.index("insert") == 10, str(ent.index("insert")))


def test_real_window(root):
    print("\n[5] 真实界面：各页输入框均已挂上撤销栈")
    app = gui.App([])
    try:
        checks = [
            ("视频链接框", getattr(app.dl_tab, "url_undo", None)),
            ("保存位置框", getattr(app.dl_tab, "dest_undo", None)),
            ("合并输入框", getattr(app.mg_tab, "in_var_undo", None)),
            ("合并输出框", getattr(app.mg_tab, "out_var_undo", None)),
            ("视频库框", getattr(app.lib_tab, "dir_undo", None)),
        ]
        for label, ctrl in checks:
            check(f"{label} 已挂撤销栈", isinstance(ctrl, gui.EntryUndo))

        # 端到端：保存位置框输入 -> Ctrl+Z -> 撤销同时同步到 config 记忆逻辑
        app.dl_tab.dest_var.set("D:\\测试目录A")
        time.sleep(0.7)
        app.dl_tab.dest_var.set("D:\\测试目录B")
        app.update()
        app.dl_tab.dest_undo.undo()
        app.update()
        check("界面级撤销生效",
              app.dl_tab.dest_var.get() == "D:\\测试目录A",
              repr(app.dl_tab.dest_var.get()))
    finally:
        app.dl_tab._drop_info_json()
        app.destroy()


def main():
    print("=" * 62)
    print("  输入框撤销/重做自检（Ctrl+Z / Ctrl+Y）")
    print("=" * 62)
    # 测试会触发保存位置的持久化回调，先备份真实配置，结束后还原
    backup = None
    if os.path.isfile(engine.CONFIG_PATH):
        backup = engine.CONFIG_PATH + ".undo_bak"
        shutil.copy2(engine.CONFIG_PATH, backup)
    root = tk.Tk()
    root.withdraw()
    try:
        test_basic(root)
        test_typing_group(root)
        test_keybind()
        test_cursor_restore(root)
        test_real_window(root)
    finally:
        root.destroy()
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
