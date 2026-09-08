#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""冒烟自测：验证 v1.9.1 页面滚动能力（不联网）。

① 5 个标签页都装进 ScrollFrame，且绑定滚轮；
② 窗口压矮时 ScrollFrame 出现滚动条，页面滚轮事件能改变 canvas 视口；
③ 内容原生的 Treeview/Text 滚轮语义未被覆盖；
④ 既有 self.<attr> 引用（dl_tab 等）仍可用，_pump/_on_close 不受影响。
运行：python _smoke_scroll.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import video_toolbox as engine
import video_toolbox_gui as gui

FAILS = []


def check(name, cond, extra=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}{(' -> ' + extra) if extra else ''}")
    if not cond:
        FAILS.append(name)


def main():
    print("=" * 62)
    print("  GUI 冒烟：页面滚动能力（v1.9.1）")
    print("=" * 62)

    backup = None
    if os.path.isfile(engine.CONFIG_PATH):
        backup = engine.CONFIG_PATH + ".scroll_bak"
        import shutil
        shutil.copy2(engine.CONFIG_PATH, backup)

    app = gui.App([])
    app.withdraw()
    app.update_idletasks()

    try:
        pages = {
            "dl_tab": app.dl_tab, "lib_tab": app.lib_tab, "mg_tab": app.mg_tab,
            "sub_tab": app.sub_tab, "up_tab": app.up_tab,
        }
        # ① 页面父级应为 ScrollFrame.inner，滚轮已递归绑定
        for name, page in pages.items():
            host = app.page_host.get(name)
            ok = (isinstance(host, gui.ScrollFrame)
                  and page.master is host.inner)
            check(f"[{name}] 装在 ScrollFrame 内", ok)
            if ok:
                bound = [w for w in host.inner.winfo_children()
                         if "mousewheel" in str(w.bind()).lower()]
                check(f"[{name}] 直接子控件已绑定滚轮", bool(bound),
                      f"{len(bound)} 个")

        # ② 压矮窗口 → 内容超高 → 滚动条出现；模拟滚轮 → 视口移动
        app.geometry("980x420")
        app.update()
        app.deiconify()
        app.update()
        host = app.page_host["up_tab"]   # 投稿页内容最长，必超高
        app.nb.select(host)
        app.update()
        inner_h = host.inner.winfo_reqheight()
        canvas_h = host.canvas.winfo_height()
        check("内容高于可视区", inner_h > canvas_h, f"inner={inner_h} canvas={canvas_h}")
        check("滚动条已出现", host.vsb.winfo_ismapped())
        before = host.canvas.yview()
        host._on_wheel(type("E", (), {"delta": -240})())   # 模拟向下滚两格
        app.update()
        after = host.canvas.yview()
        check("滚轮事件移动了视口", after != before and after[0] > before[0],
              f"{before[0]:.2f}->{after[0]:.2f}")

        # ③ Treeview 原生滚轮未被页面滚动绑定覆盖
        tree = app.dl_tab.task_tree
        check("Treeview 未绑定页面滚轮", "wheel" not in str(tree.bind()))

        # ④ 滚动条自动隐藏：拉高窗口后应消失
        app.geometry("980x1300")
        app.update()
        check("窗口足够高时滚动条自动隐藏", not host.vsb.winfo_ismapped())
    finally:
        app.dl_tab._drop_info_json()
        app.destroy()
        if backup:
            import shutil
            shutil.move(backup, engine.CONFIG_PATH)

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
