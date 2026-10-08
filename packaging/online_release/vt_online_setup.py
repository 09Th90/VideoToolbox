# -*- coding: utf-8 -*-
# @version 1.18.0
"""视频工具箱 · 在线引导安装器（自研，替代 Qt IFW 在线安装器）。

为什么自研：见 `vt_update_core.py` 顶部长注释 —— IFW 的仓库要求
`<基址>/<组件名>/<归档>` 的**目录层级**，而 GitHub Releases 的资产是**平铺**的，
两者天生不兼容（实测嵌套 404、带斜杠 tag 撞 git D/F 冲突）。改为自己下载解压后，
资产可以完全平铺，直接吃满 Releases 的 **2GB/资产**上限，`gh-pages` 那条
**100 MiB 单文件硬限**（主程序 exe 已 103MB，撞线）就此消失。

界面用 **tkinter**（标准库）而不是 PyQt5：本 exe 只需几百 KB 逻辑，
带 PyQt5 要 ~40MB，带 tkinter 只要 ~12MB —— 而它本身也是要用户下载的。
功能上够用（版本信息 / 目录选择 / 进度 / 日志）。

用法：
    双击运行（正常图形界面）
    vt_online_setup.exe --manifest <url或本地路径> --dir <目标目录> --silent
        ↑ 无人值守，供自测与批量部署；退出码 0=成功，非 0=失败
    vt_online_setup.exe --manifest installer_online\\manifest.json --dir D:\\tmp\\vt_test
        ↑ 离线自测：manifest 可以是本地文件，资产走 file:// 或 http
"""
import argparse
import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vt_update_core as core  # noqa: E402

APP_TITLE = "视频工具箱 · 在线安装 / 更新"
WORK_DIR_NAME = "vt_online_setup_cache"


class SetupApp:
    def __init__(self, root, args):
        self.root = root
        self.args = args
        self.manifest = None
        self.busy = False
        self.exit_code = 0
        self.stage = ""
        self.q = queue.Queue()
        self.work_dir = os.path.join(
            os.environ.get("TEMP") or os.path.expanduser("~"), WORK_DIR_NAME)

        root.title(APP_TITLE)
        root.geometry("620x460")
        root.minsize(560, 420)
        self._build()
        root.after(80, self._pump)
        root.after(150, self._load_manifest)

    # ---------------- UI ----------------
    def _build(self):
        pad = {"padx": 12}
        head = ttk.Frame(self.root)
        head.pack(fill="x", pady=(12, 4), **pad)
        ttk.Label(head, text=APP_TITLE, font=("Microsoft YaHei UI", 13, "bold")
                  ).pack(anchor="w")
        self.lbl_ver = ttk.Label(head, text="正在获取更新信息…",
                                 foreground="#555")
        self.lbl_ver.pack(anchor="w", pady=(4, 0))

        box = ttk.LabelFrame(self.root, text="安装位置")
        box.pack(fill="x", pady=8, **pad)
        row = ttk.Frame(box)
        row.pack(fill="x", padx=8, pady=8)
        self.var_dir = tk.StringVar(value=self.args.dir or "")
        self.ent_dir = ttk.Entry(row, textvariable=self.var_dir)
        self.ent_dir.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="浏览…", command=self._browse).pack(side="left",
                                                               padx=(6, 0))
        self.lbl_hint = ttk.Label(box, text="", foreground="#8a6d00",
                                  wraplength=560, justify="left")
        self.lbl_hint.pack(fill="x", padx=8, pady=(0, 8))

        prog = ttk.Frame(self.root)
        prog.pack(fill="x", **pad)
        self.bar = ttk.Progressbar(prog, mode="determinate", maximum=100)
        self.bar.pack(fill="x")
        self.lbl_pct = ttk.Label(prog, text="", foreground="#555")
        self.lbl_pct.pack(anchor="w", pady=(2, 0))

        logf = ttk.LabelFrame(self.root, text="日志")
        logf.pack(fill="both", expand=True, pady=8, **pad)
        self.txt = tk.Text(logf, height=10, wrap="word", state="disabled",
                           font=("Consolas", 9))
        sb = ttk.Scrollbar(logf, command=self.txt.yview)
        self.txt.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.txt.pack(side="left", fill="both", expand=True, padx=(8, 0),
                      pady=8)

        btns = ttk.Frame(self.root)
        btns.pack(fill="x", pady=(0, 12), **pad)
        self.btn_go = ttk.Button(btns, text="开始安装 / 更新", command=self._go,
                                 state="disabled")
        self.btn_go.pack(side="right")
        ttk.Button(btns, text="退出", command=self.root.destroy).pack(
            side="right", padx=(0, 8))

    def _browse(self):
        d = filedialog.askdirectory(title="选择安装目录",
                                    initialdir=self.var_dir.get() or "D:\\")
        if d:
            self.var_dir.set(os.path.normpath(d))

    def _log(self, msg):
        self.txt.configure(state="normal")
        self.txt.insert("end", msg + "\n")
        self.txt.see("end")
        self.txt.configure(state="disabled")

    # ---------------- 事件泵 ----------------
    def _pump(self):
        try:
            while True:
                kind, a, b = self.q.get_nowait()
                if kind == "log":
                    self._log(a)
                elif kind == "prog":
                    if b and b > 0:
                        self.bar.configure(mode="determinate")
                        self.bar["value"] = min(100.0, a * 100.0 / b)
                        self.lbl_pct.configure(
                            text="%s  %s / %s" % (self.stage, core.human(a),
                                                  core.human(b)))
                    else:
                        self.lbl_pct.configure(text="%s  %s" % (self.stage,
                                                                core.human(a)))
                elif kind == "stage":
                    self.stage = a
                    self.lbl_pct.configure(text=a)
                elif kind == "done":
                    self._on_done(a, b)
        except queue.Empty:
            pass
        self.root.after(80, self._pump)

    # ---------------- 取 manifest ----------------
    def _load_manifest(self):
        url = self.args.manifest or core.DEFAULT_MANIFEST_URL

        def work():
            try:
                m = core.load_manifest(url)
            except core.UpdateError as e:
                self.exit_code = 2
                self.q.put(("log", str(e), None))
                self.q.put(("stage", "获取更新信息失败", None))
                self.root.after(0, lambda: self.lbl_ver.configure(
                    text="获取更新信息失败", foreground="#b00020"))
                if self.args.silent:
                    print("FAIL " + str(e))
                    self.root.after(300, self.root.destroy)
                return
            self.manifest = m
            if self.args.base_url:
                # 便于离线自测与换镜像：显式覆盖 manifest 里的 base_url
                m["base_url"] = self.args.base_url
                self.q.put(("log", "已覆盖 base_url = %s" % self.args.base_url,
                            None))
            self.root.after(0, lambda: self._manifest_ready(m))

        threading.Thread(target=work, daemon=True).start()

    def _manifest_ready(self, m):
        notes = (m.get("notes") or "").strip().replace("\n", " ")
        self.lbl_ver.configure(
            text="最新版本 v%s（%s）%s" % (m.get("version"), m.get("released", ""),
                                       ("　·　" + notes[:60]) if notes else ""),
            foreground="#1a7f37")
        total = sum(int(a.get("size") or 0) for a in m.get("assets", []))
        self._log("更新清单已获取：v%s，共 %d 个组件包，%s"
                  % (m.get("version"), len(m.get("assets", [])), core.human(total)))
        for a in m.get("assets", []):
            self._log("   %-6s %-26s %10s" % (a.get("name"), a.get("file"),
                                              core.human(int(a.get("size") or 0))))
        if not self.var_dir.get():
            det = core.detect_install_dir()
            self.var_dir.set(det or core.DEFAULT_DIR)
            if det:
                self.lbl_hint.configure(text="已自动识别到本机安装目录：%s" % det)
            else:
                self.lbl_hint.configure(
                    text="未找到已安装的视频工具箱。此工具主要用于**更新已有安装**；"
                         "若这是首次安装，建议先跑完整安装包（含运行时依赖），"
                         "或确认目标目录正确后继续。")
        self.btn_go.configure(state="normal")
        if self.args.silent:
            self._go()

    # ---------------- 执行 ----------------
    def _go(self):
        if self.busy:
            return
        if not self.manifest:
            messagebox.showwarning(APP_TITLE, "还没拿到更新信息，请稍候")
            return
        d = (self.var_dir.get() or "").strip().strip('"')
        if not d:
            messagebox.showwarning(APP_TITLE, "请先选择安装目录")
            return
        if core.app_running(d):
            if not messagebox.askokcancel(
                    APP_TITLE, "检测到视频工具箱正在运行。\n"
                               "更新会覆盖主程序文件，请先完全退出。\n\n仍要继续吗？"):
                return
        self.busy = True
        self.btn_go.configure(state="disabled", text="进行中…")
        self._log("=" * 56)
        self._log("开始安装到：%s" % d)

        def prog(stage, a, b):
            self.q.put(("prog", a, b))
            self.q.put(("stage", stage, None))

        def work():
            try:
                res = core.apply_update(
                    self.manifest, d, self.work_dir,
                    progress=prog,
                    log=lambda s: self.q.put(("log", s, None)),
                    shortcuts=(None if self.args.no_shortcuts
                               else {"desktop": True, "start_menu": True}),
                )
            except core.UpdateError as e:
                self.q.put(("log", "[失败] " + str(e), None))
                self.q.put(("done", False, str(e)))
            except Exception as e:  # noqa: BLE001
                self.q.put(("log", "[异常] %r" % e, None))
                self.q.put(("done", False, repr(e)))
            else:
                self.q.put(("done", True, res))

        threading.Thread(target=work, daemon=True).start()

    def _on_done(self, ok, info):
        self.busy = False
        self.bar.stop()
        self.bar.configure(mode="determinate")
        self.btn_go.configure(state="normal", text="重新执行")
        if ok:
            self.exit_code = 0
            self.bar["value"] = 100
            self.lbl_pct.configure(text="完成")
            self._log("[完成] v%s，%d 个文件，用时 %ss"
                      % (info.get("version"), info.get("files"),
                         info.get("seconds")))
            if self.args.silent:
                print("OK v%s %d files %ss"
                      % (info.get("version"), info.get("files"),
                         info.get("seconds")))
                self.root.after(200, self.root.destroy)
                return
            if messagebox.askyesno(
                    APP_TITLE, "更新完成（v%s，%d 个文件）。\n\n现在启动视频工具箱？"
                    % (info.get("version"), info.get("files"))):
                exe = os.path.join(info.get("dir") or self.var_dir.get(),
                                   "视频工具箱.exe")
                if os.path.isfile(exe) and hasattr(os, "startfile"):
                    try:
                        os.startfile(exe)  # noqa: S606
                    except Exception as e:  # noqa: BLE001
                        messagebox.showwarning(APP_TITLE, "启动失败：%s" % e)
            self.root.destroy()
        else:
            self.exit_code = 1
            self.lbl_pct.configure(text="失败")
            if self.args.silent:
                print("FAIL " + str(info))
                self.root.after(200, self.root.destroy)
            else:
                messagebox.showerror(APP_TITLE, "更新失败：\n\n%s" % info)


def main(argv=None):
    ap = argparse.ArgumentParser(description="视频工具箱 在线安装 / 更新")
    ap.add_argument("--manifest", default="",
                    help="更新清单地址（http(s) 或本地路径）；默认走内置地址")
    ap.add_argument("--dir", default="", help="安装目录；默认自动识别")
    ap.add_argument("--base-url", default="",
                    help="覆盖清单里的 base_url（离线自测 / 换镜像用）")
    ap.add_argument("--silent", action="store_true", help="无人值守（供自测/批处理）")
    ap.add_argument("--no-shortcuts", action="store_true", help="不创建快捷方式")
    args = ap.parse_args(argv)

    root = tk.Tk()
    try:
        root.call("tk", "scaling", 1.25)   # 高分屏下别太小
    except Exception:  # noqa: BLE001
        pass
    app = SetupApp(root, args)
    root.mainloop()
    return app.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
