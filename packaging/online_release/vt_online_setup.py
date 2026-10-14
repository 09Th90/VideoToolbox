# -*- coding: utf-8 -*-
# @version 2.2.5
"""视频工具箱 · 在线引导安装器（自研，替代 Qt IFW 在线安装器）。

为什么自研：见 `vt_update_core.py` 顶部长注释 —— IFW 的仓库要求
`<基址>/<组件名>/<归档>` 的**目录层级**，而 GitHub Releases 的资产是**平铺**的，
两者天生不兼容（实测嵌套 404、带斜杠 tag 撞 git D/F 冲突）。改为自己下载解压后，
资产可以完全平铺，直接吃满 Releases 的 **2GB/资产**上限（超了自动分卷），
`gh-pages` 那条 **100 MiB 单文件硬限**（主程序 exe 已 103MB，撞线）就此消失。

界面用 **tkinter**（标准库）而不是 PyQt5：本 exe 只需几百 KB 逻辑，
带 PyQt5 要 ~40MB，带 tkinter 只要 ~12MB —— 而它本身也是要用户下载的。
功能上够用（版本信息 / 目录选择 / 增量计划 / 进度 / 速度 / 取消 / 日志）。

v1.20.0 起：
  · 增量更新：manifest schema 2 带文件级清单，只下变化的包（见 core.plan_update）；
  · `--check` 模式：只检查有无更新，退出码 0=已最新 / 10=有更新 / 2=失败，
    供主程序「检查更新」入口以子进程方式调用（不弹窗）；
  · 完成后自动自检更新器自身（core.ensure_updater），保证安装目录里的
    在线安装器永远是最新逻辑。

用法：
    双击运行（正常图形界面）
    vt_online_setup.exe --manifest <url或本地路径> --dir <目标目录> --silent
        ↑ 无人值守，供自测与批量部署；退出码 0=成功，非 0=失败
    vt_online_setup.exe --check [--manifest <url>] [--dir <目录>]
        ↑ 只检查更新（控制台输出，不弹窗）；退出码 0=最新 / 10=有更新 / 2=失败
    vt_online_setup.exe --manifest installer_online\\manifest.json --dir D:\\tmp\\vt_test
        ↑ 离线自测：manifest 可以是本地文件，资产走 file:// 或 http

全版本（v1.20.0 起，靠 index.json 定位）：
    vt_online_setup.exe --list-versions
        ↑ 列出所有可安装版本（* 标记 latest）；退出码 0=成功 2=失败
    vt_online_setup.exe --version 1.19.0 --dir D:\\VideoToolbox --silent
        ↑ 安装**指定版本**（回滚同样走这条）：1.20.0 / ^1.20 / >=1.19 / stable 都认
    vt_online_setup.exe --version ">=1.19" --index <index.json 路径>
        ↑ 自定义索引源（离线自测时指向本地 index.json）
    vt_online_setup.exe --version 1.18.0 --allow-hidden
        ↑ 装被撤回（yanked）/归档（archived）的版本：默认不出现在选择里
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
        #: 命中的版本记录（走索引时才有；老路径为 None）
        self.version_entry = None
        #: 全版本目录（点「全部版本…」后才拉，默认不发多余请求）
        self.index = None
        self.busy = False
        #: busy 期间用户请求过退出/关窗（done 后顺势关掉）
        self.quit_requested = False
        self.exit_code = 0
        self.stage = ""
        self.q = queue.Queue()
        self.cancel = threading.Event()
        self.stats = {"speed": 0.0, "source": ""}
        self.work_dir = os.path.join(
            os.environ.get("TEMP") or os.path.expanduser("~"), WORK_DIR_NAME)

        root.title(APP_TITLE)
        root.geometry("680x520")
        root.minsize(600, 460)
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

        # 版本选择：默认只有 latest。点「全部版本…」才去读 index.json ——
        # 默认路径因此仍是**一次请求**，不会因为加了全版本能力而变慢。
        vrow = ttk.Frame(head)
        vrow.pack(fill="x", pady=(6, 0))
        ttk.Label(vrow, text="版本：").pack(side="left")
        self.var_ver = tk.StringVar(value=self.args.version or "latest")
        self.cmb_ver = ttk.Combobox(vrow, textvariable=self.var_ver,
                                    values=["latest"], width=24,
                                    state="readonly")
        self.cmb_ver.pack(side="left")
        self.cmb_ver.bind("<<ComboboxSelected>>",
                          lambda _e: self._on_pick_version())
        self.btn_vers = ttk.Button(vrow, text="全部版本…",
                                   command=self._load_versions)
        self.btn_vers.pack(side="left", padx=(6, 0))

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
                                  wraplength=620, justify="left")
        self.lbl_hint.pack(fill="x", padx=8, pady=(0, 8))

        self.lbl_plan = ttk.Label(self.root, text="", foreground="#1a7f37",
                                  wraplength=620, justify="left")
        self.lbl_plan.pack(fill="x", **pad)

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
        self.btn_cancel = ttk.Button(btns, text="取消", command=self._cancel,
                                     state="disabled")
        self.btn_cancel.pack(side="right", padx=(0, 8))
        ttk.Button(btns, text="退出", command=self._quit).pack(
            side="right", padx=(0, 8))
        # 窗口 X 与「退出」按钮同一路径：busy 时不能裸 destroy——
        # daemon 工作线程会被强杀，若正停在 apply_staging 第一遍 rename
        # （目标已全部改名 .vtold、新文件未就位），安装目录主程序文件
        # 全在 .vtold 里，用户再启动就缺文件（2026-10-13 审查修复）。
        self.root.protocol("WM_DELETE_WINDOW", self._quit)

    def _browse(self):
        d = filedialog.askdirectory(title="选择安装目录",
                                    initialdir=self.var_dir.get() or "D:\\")
        if d:
            self.var_dir.set(os.path.normpath(d))
            self._refresh_plan()

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
                        sp = self.stats.get("speed") or 0
                        src = self.stats.get("source") or ""
                        tail = "  %.1f MB/s" % (sp / 1048576) if sp > 1024 else ""
                        self.lbl_pct.configure(
                            text="%s  %s / %s%s%s"
                            % (self.stage, core.human(a), core.human(b), tail,
                               ("  · " + src) if src else ""))
                    else:
                        self.lbl_pct.configure(text="%s  %s" % (self.stage,
                                                                core.human(a)))
                elif kind == "stage":
                    # 只记阶段名，不覆盖 lbl_pct：随后到的 prog 事件会把
                    # 「阶段 + 大小/速度/源」一起渲染；此处覆盖会让那段
                    # 详细文本永远不可见（2026-10-13 审查修复）
                    self.stage = a
                elif kind == "plan":
                    self.lbl_plan.configure(text=a)
                elif kind == "done":
                    self._on_done(a, b)
        except queue.Empty:
            pass
        self.root.after(80, self._pump)

    # ---------------- 取 manifest ----------------
    def _load_manifest(self):
        """按当前版本诉求取 manifest（走索引或走最新别名，见 core.resolve_manifest）。"""

        def work():
            try:
                m, entry = core.resolve_manifest(
                    want=self.args.version, index_url=self.args.index or None,
                    manifest=self.args.manifest or None,
                    base_url=self.args.base_url or None,
                    allow_hidden=self.args.allow_hidden,
                    log=lambda s: self.q.put(("log", s, None)))
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
            self.version_entry = entry
            if self.args.base_url:
                # 便于离线自测与换镜像：显式覆盖 manifest 里的 base_url
                m["base_url"] = self.args.base_url
                self.q.put(("log", "已覆盖 base_url = %s" % self.args.base_url,
                            None))
            self.root.after(0, lambda: self._manifest_ready(m))

        threading.Thread(target=work, daemon=True).start()

    # ---------------- 版本列表 ----------------
    def _load_versions(self):
        """拉 index.json 并把可选版本填进下拉（用户点「全部版本…」才触发）。"""
        self.btn_vers.configure(state="disabled", text="读取中…")

        def work():
            try:
                idx = core.load_version_index(
                    self.args.index or None,
                    log=lambda s: self.q.put(("log", s, None)))
            except core.UpdateError as e:
                self.q.put(("log", "读版本索引失败：%s" % e, None))
                self.root.after(0, lambda: self.btn_vers.configure(
                    state="normal", text="全部版本…"))
                return
            self.index = idx
            vers = core.list_versions(idx, allow_hidden=self.args.allow_hidden)
            vals = (["latest"]
                    + ["%s（%s）" % (v, s) for v, s, _n in vers])

            def fill():
                self.cmb_ver.configure(values=vals)
                self.btn_vers.configure(state="normal", text="全部版本…")
                self._log("版本索引共 %d 个版本可选" % len(vers))
            self.root.after(0, fill)

        threading.Thread(target=work, daemon=True).start()

    def _on_pick_version(self):
        """下拉选了别的版本 → 按它重新取 manifest 与增量计划。"""
        sel = (self.var_ver.get() or "latest").strip()
        # 下拉项是 "1.20.0（stable）" 这种，取括号前的版本号
        want = sel.split("（")[0].split("(")[0].strip() or "latest"
        self.args.version = "" if want == "latest" else want
        self.btn_go.configure(state="disabled")
        self._log("切换到版本：%s" % want)
        self._load_manifest()

    def _manifest_ready(self, m):
        notes = (m.get("notes") or "").strip().replace("\n", " ")
        want = (self.args.version or "latest").strip()
        is_latest = want.lower() in ("latest", "newest", "")
        head = "最新版本" if is_latest else "指定版本"
        self.lbl_ver.configure(
            text="%s v%s（%s）%s" % (head, m.get("version"),
                                   m.get("released", ""),
                                   ("　·　" + notes[:60]) if notes else ""),
            foreground="#1a7f37" if is_latest else "#8a6d00")
        if not is_latest:
            self._log("⚠ 正在安装**指定版本** v%s（不是最新）——"
                      "装完即固定在此版本，直到你再次选择别的版本。" % m.get("version"))
        total = sum(int(a.get("size") or 0) for a in m.get("assets", []))
        self._log("更新清单已获取：v%s，共 %d 个组件包，%s"
                  % (m.get("version"), len(m.get("assets", [])), core.human(total)))
        for a in m.get("assets", []):
            self._log("   %-6s %-26s %10s%s"
                      % (a.get("name"), a.get("file"),
                         core.human(int(a.get("size") or 0)),
                         "（%d 卷）" % len(a["parts"]) if a.get("parts") else ""))
        if not self.var_dir.get():
            det = core.detect_install_dir()
            self.var_dir.set(det or core.default_install_dir())
            if det:
                self.lbl_hint.configure(text="已自动识别到本机安装目录：%s" % det)
            else:
                self.lbl_hint.configure(
                    text="未找到已安装的视频工具箱。此工具主要用于**更新已有安装**；"
                         "若这是首次安装，建议先跑完整安装包（含运行时依赖），"
                         "或确认目标目录正确后继续。")
        self.btn_go.configure(state="normal")
        self._refresh_plan()
        if self.args.silent:
            self._go()

    def _refresh_plan(self):
        """按当前目录算增量计划并展示（将下载 X / 跳过 Y）。"""
        if not self.manifest or not self.var_dir.get():
            return
        d = self.var_dir.get()

        def work():
            try:
                plan = core.plan_update(self.manifest, d)
            except Exception as e:  # noqa: BLE001
                self.q.put(("log", "增量计划计算失败：%r" % e, None))
                return
            orphans = plan.get("orphans") or []
            if plan["need"]:
                parts = []
                for a in plan["need"]:
                    parts.append("%s %s" % (a.get("name"),
                                            core.human(int(a.get("size") or 0))))
                txt = ("本次将下载 %s（%s），跳过未变化的 %s；%d 个文件有变动"
                       % (core.human(plan["download_bytes"]), " + ".join(parts),
                          core.human(plan["skip_bytes"]), len(plan["changed"])))
                if plan["full"]:
                    txt += "　[全量安装/修复]"
                if orphans:
                    txt += "；并清理 %d 个目标版本不再包含的文件" % len(orphans)
            elif orphans:
                txt = ("内容已是目标版本，仅需清理 %d 个残留文件" % len(orphans))
            else:
                txt = "本地文件与清单一致，无需下载（点击执行也会极快完成）"
            self.q.put(("plan", txt, None))

        threading.Thread(target=work, daemon=True).start()

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
            if self.args.silent:
                # silent 模式弹 askokcancel 会永久挂起（无人点确定，
                # root.destroy 只在 done 事件后触发）——改为警告后继续：
                # apply_staging 靠 rename 语义可覆盖运行中的 exe
                self._log("[warn] 检测到程序正在运行，silent 模式继续安装")
            elif not messagebox.askokcancel(
                    APP_TITLE, "检测到视频工具箱正在运行。\n"
                               "更新会覆盖主程序文件，请先完全退出。\n\n仍要继续吗？"):
                return
        self.busy = True
        self.cancel.clear()
        self.btn_go.configure(state="disabled", text="进行中…")
        self.btn_cancel.configure(state="normal")
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
                    cancel=self.cancel, stats=self.stats,
                )
                # 收尾：自检更新器自身（安装目录里的在线安装器保持最新逻辑）
                core.ensure_updater(self.manifest, d, self.work_dir,
                                    progress=prog,
                                    log=lambda s: self.q.put(("log", s, None)))
            except core.Canceled:
                self.q.put(("log", "[已取消] 进度已保留，下次运行会续传", None))
                self.q.put(("done", "cancel", None))
            except core.UpdateError as e:
                self.q.put(("log", "[失败] " + str(e), None))
                self.q.put(("done", False, str(e)))
            except Exception as e:  # noqa: BLE001
                self.q.put(("log", "[异常] %r" % e, None))
                self.q.put(("done", False, repr(e)))
            else:
                self.q.put(("done", True, res))

        threading.Thread(target=work, daemon=True).start()

    def _cancel(self):
        if not self.busy:
            return
        self.cancel.set()
        self.btn_cancel.configure(state="disabled", text="正在取消…")
        self._log("已请求取消（当前块下完即停，进度保留可续传）")

    def _quit(self):
        """退出：busy 时先取消，等工作线程收尾（done 事件）再关窗口。"""
        if self.busy:
            self.quit_requested = True
            if not self.cancel.is_set():
                self.cancel.set()
                self.btn_cancel.configure(state="disabled", text="正在取消…")
                self._log("已请求取消（关窗将在落地收尾后完成）")
            return
        self.root.destroy()

    def _on_done(self, ok, info):
        self.busy = False
        self.bar.stop()
        self.bar.configure(mode="determinate")
        self.btn_go.configure(state="normal", text="重新执行")
        self.btn_cancel.configure(state="disabled", text="取消")
        # busy 期间用户点过退出/关窗：收尾后顺势关掉，别让他再点一次
        closing = getattr(self, "quit_requested", False)
        if ok == "cancel":
            self.lbl_pct.configure(text="已取消")
            if closing:
                self.root.after(100, self.root.destroy)
            return
        if ok:
            self.exit_code = 0
            self.bar["value"] = 100
            self.lbl_pct.configure(text="完成")
            self._log("[完成] v%s，%d 个文件落地，下载 %s，用时 %ss"
                      % (info.get("version"), info.get("files"),
                         core.human(info.get("downloaded") or 0),
                         info.get("seconds", "?")))
            if self.args.silent:
                print("OK v%s %d files %s"
                      % (info.get("version"), info.get("files"),
                         core.human(info.get("downloaded") or 0)))
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


# ------------------------------------------------------------------ --check


def run_list(args):
    """只列出可安装版本（无 UI）。退出码 0=成功 / 2=失败。"""
    try:
        idx = core.load_version_index(args.index or None)
    except core.UpdateError as e:
        print("LIST-FAIL %s" % e)
        return 2
    vers = core.list_versions(idx, allow_hidden=args.allow_hidden)
    if not vers:
        print("LIST-EMPTY 索引里没有可用版本")
        return 2
    latest = (idx.get("channels") or {}).get("latest") or ""
    for ver, state, notes in vers:
        print("%s %-10s %-12s %s"
              % ("*" if ver == latest else " ", ver, state, notes))
    print("VERSIONS %d latest=%s" % (len(vers), latest))
    return 0


def run_check(args):
    """只检查更新（无 UI）。退出码：0=已最新 / 10=有更新 / 2=检查失败。

    ⚠ 带 `--version` 时比较的是**指定版本**而非 latest：本地已是该版本
    判 UP-TO-DATE，否则判 UPDATE-AVAILABLE（升级与降级同判，因为对
    「目标版本」而言都是"当前不对"）。
    """
    try:
        m, entry = core.resolve_manifest(
            want=args.version, index_url=args.index or None,
            manifest=args.manifest or None, base_url=args.base_url or None,
            allow_hidden=args.allow_hidden)
    except core.UpdateError as e:
        print("CHECK-FAIL %s" % e)
        return 2
    if args.base_url:
        m["base_url"] = args.base_url
    d = ((args.dir or "").strip() or core.detect_install_dir()
         or core.default_install_dir())
    try:
        plan = core.plan_update(m, d)
    except Exception as e:  # noqa: BLE001
        print("CHECK-FAIL plan: %r" % e)
        return 2
    local_ver = plan.get("local_version") or "未安装"
    # remove 也要参与"有变化"判定：只该删文件的版本（无 need/orphans）
    # 曾被误报 UP-TO-DATE（2026-10-13 审查修复）
    if not plan["need"] and not plan["orphans"] and not plan["remove"]:
        print("UP-TO-DATE local=%s remote=v%s" % (local_ver, m["version"]))
        return 0
    pkgs = " + ".join("%s(%s)" % (a.get("name"), core.human(int(a.get("size") or 0)))
                      for a in plan["need"])
    print("UPDATE-AVAILABLE local=%s remote=v%s download=%s pkgs=%s "
          "changed=%d orphan=%d"
          % (local_ver, m["version"], core.human(plan["download_bytes"]),
             pkgs, len(plan["changed"]), len(plan["orphans"])))
    return 10


# ------------------------------------------------------------------ 入口


def main(argv=None):
    ap = argparse.ArgumentParser(description="视频工具箱 在线安装 / 更新")
    ap.add_argument("--manifest", default="",
                    help="更新清单地址（http(s) 或本地路径）；默认走内置地址")
    ap.add_argument("--dir", default="", help="安装目录；默认自动识别")
    ap.add_argument("--base-url", default="",
                    help="覆盖清单里的 base_url（离线自测 / 换镜像用）")
    ap.add_argument("--silent", action="store_true", help="无人值守（供自测/批处理）")
    ap.add_argument("--no-shortcuts", action="store_true", help="不创建快捷方式")
    ap.add_argument("--check", action="store_true",
                    help="只检查有无更新（不弹窗）；退出码 0=最新 10=有更新 2=失败")
    ap.add_argument("--list-versions", action="store_true",
                    help="只列出可安装版本并退出（走 --index；退出码 0/2）")
    ap.add_argument("--index", default="",
                    help="版本索引地址（http(s) 或本地路径）；装非最新版本时用")
    ap.add_argument("--version", default="",
                    help="要安装的版本（默认 latest；可写 1.20.0 / ^1.20 / "
                         ">=1.19 / stable）")
    ap.add_argument("--allow-hidden", action="store_true",
                    help="允许选中被撤回（yanked）或归档（archived）的版本")
    args = ap.parse_args(argv)

    if args.list_versions:
        return run_list(args)
    if args.check:
        return run_check(args)

    root = tk.Tk()
    if args.silent:
        # 无人值守：窗口不露面（进度/结果走标准输出，见 SetupApp 内
        # silent 分支）——主程序自动更新时会调这条路径，闪窗很吵
        root.withdraw()
    try:
        root.call("tk", "scaling", 1.25)   # 高分屏下别太小
    except Exception:  # noqa: BLE001
        pass
    app = SetupApp(root, args)
    root.mainloop()
    return app.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
