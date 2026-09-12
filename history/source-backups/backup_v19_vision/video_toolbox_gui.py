#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""视频工具箱 GUI v1.9.1
图形界面：视频下载 + 视频库 + 音视频合并 + 本地字幕生成（Whisper）+ B站自动投稿
复用 video_toolbox.py 的全部核心逻辑（同目录 / 已随 exe 打包）
v1.9.1：全部标签页支持页面滚动——内容高于可视区时自动出现垂直滚动条，
        鼠标滚轮即可滚动页面；任务列表/日志区等自带滚轮的控件保持原生滚动。
        投稿流程改为「先上传再检测」——点投稿后先上传视频进入投稿区，现场
        检测分区/话题并自动匹配任务名称填写，不再要求提前点检测按钮（检测
        按钮仍可单独使用）；分区匹配失败时正式投稿终止、预览模式继续。
v1.9.0：① 接入全局 AI（智谱 GLM：glm-4.7-flash 文本 + glm-4.6v-flash 视觉，配置见
        data\\ai_config.json）；② 分区检测/分区选择/简介填写改为纯屏幕识别 +
        模拟鼠标点击/滚动（不再注入页面脚本）；③ 字幕语言由 AI 识别标题语言自动
        匹配——下载时按标题语言拉取字幕，投稿时自动选择同语言字幕文件与 B 站
        字幕语言；④ 话题检测/参与话题同样走屏幕识别。
v1.7.1：① B站分区改为单级下拉（B站当前无一级/二级），分区/话题检测均先上传视频
        再取列表（B站上传视频后才进入投稿区）；② 新增「加入合集」自动检测当前账号
        合集并选择；③ 同步上传原始字幕（.srt，自动从视频同目录查找），字幕语言默认
        英语；④ 简介按「源地址/来源/原简介」格式自动生成。
v1.7.0：① 按功能划分目录（src/docs/data/logs/tools），程序目录顶层只留主程序；
        ② B站投稿分区改为自动检测的两级级联下拉，话题支持按所选分区自动检测、
        双击多选添加；③ 下载生成的 视频信息.txt 字段与投稿表单完全对齐
        （标题/简介/标签/分区/创作声明/话题），选视频即全字段预填。
v1.6.0：安装包瘦身：ASR 识别模型（large-v3-turbo，约 1.5GB）不再内置到安装包，
        改为在「字幕生成」页提供开源模型库（Hugging Face / hf-mirror 镜像）
        下载链接，用户下载到 tools\\asr_model 即可；运行时与投稿引擎仍随包分发。
v1.5.1：完全内嵌化：ASR 识别引擎与 B 站投稿引擎运行时均随工具箱分发，
        不再依赖 E 盘等外部程序；运行时优先调用 tools\\python\\python.exe，
        未嵌入解释器时自动使用系统 Python。
v1.5.0：新增「B站投稿」标签页——集成自动化投稿系统的 Playwright 投稿引擎：
        选视频后自动读取同目录视频信息.txt 预填标题/简介，填标签/分区/声明/话题
        后投稿；默认预览模式（只填写不点提交），正式投稿前弹窗二次确认；
        阶段实时显示，登录态长期复用。
v1.4.0：新增「字幕生成」标签页——集成本地 Whisper large-v3-turbo：
        视频/音频转写为 SRT 并自动存到原文件同文件夹；长视频 10 分钟分块 + VAD
        + 重叠去重，内存恒定；任务串行排队，子进程运行；已有同名 srt 时不覆盖
        （另存 (ASR生成) 副本）
v1.3.2：修复并行下载失败——检测结果失效（如 B 站 CDN 链接过期致 403）时，
        多个任务同时走「直接链接重新提取」兜底，并发请求互相触发站点风控（HTTP 412）
        导致并行任务集体失败。现将画质检测与兜底重新提取改为全局串行 + 退避重试；
        并为 yt-dlp/ffmpeg 首次引导下载加锁，防止并行任务重复下载损坏文件
v1.3.1：① 修复勾选「同时下载字幕」导致整个下载失败——字幕改为视频完成后单独拉取，
          字幕被风控/无字幕时只提示，不再影响视频、封面与信息文件
        ② 输入框支持 Ctrl+Z 撤销 / Ctrl+Y（或 Ctrl+Shift+Z）重做
          （Tk 8.6 起原生 undo 被移除，这里基于 textvariable 追踪手写撤销栈：
            连续打字合并为一步，粘贴与选目录等整体改动独立成步，撤销时光标一并还原）
v1.3.0：① 保存位置可自定义并长期记住（写入 config.json，重启自动填回）
        ② 每个视频打包到独立文件夹（以视频标题命名）
        ③ 一并下载封面并统一转成 1280x720 的 封面.jpg
        ④ 导出 视频信息.txt（标题 / 简介 / 视频链接 / 博主主页链接）
        ⑤ 视频库改为递归扫描，可直接看到各独立文件夹内的视频
        ⑥ 修复保存路径含 % 时被 yt-dlp 当模板解析、导致下载到错误位置的问题
v1.2.1：修复下载失败——检测画质时保存 yt-dlp 提取结果，下载改用 --load-info-json
复用（不再二次提取网页，规避 B 站等站点 HTTP 412 风控），并对风控增加自动重试与回退
v1.2.0：视频库升级为「自动加载 + 缩略图 + 时长」，保留并行下载与隐藏控制台
"""

import os
import sys
sys.dont_write_bytecode = True   # 不在程序目录生成 __pycache__，保持文件夹整洁
import re
import json
import time
import asyncio
import logging
import hashlib
import threading
import queue
import subprocess
import webbrowser
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter.scrolledtext import ScrolledText

import video_toolbox as engine

# ========== 视觉规范 ==========
BG      = "#F6F4EF"   # 纸感米白背景
SURFACE = "#FFFFFF"   # 输入控件底
INK     = "#23201B"   # 主文字
MUTED   = "#6E675C"   # 次要文字
LINE    = "#E0DACD"   # 分隔线
ACCENT  = "#2F5D50"   # 主色：松绿
ACCENT_DK = "#254A40" # 主色按压
DANGER  = "#A6473C"

F_TITLE = ("Microsoft YaHei UI", 13, "bold")
F_HEAD  = ("Microsoft YaHei UI", 10, "bold")
F_BODY  = ("Microsoft YaHei UI", 10)
F_SMALL = ("Microsoft YaHei UI", 9)
F_MONO  = ("Consolas", 9)

PAD_X = 22
PAD_T = 18
GAP   = 10
# =============================


def setup_style(root):
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure(".", background=BG, foreground=INK, font=F_BODY, bordercolor=LINE)
    style.configure("TFrame", background=BG)
    style.configure("TLabel", background=BG, foreground=INK)
    style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=F_SMALL)
    style.configure("Title.TLabel", background=BG, foreground=INK, font=F_TITLE)
    style.configure("Head.TLabel", background=BG, foreground=INK, font=F_HEAD)
    style.configure("TNotebook", background=BG, borderwidth=0)
    style.configure("TNotebook.Tab", padding=(18, 8), font=F_BODY, background="#EAE5DA", foreground=MUTED)
    style.map("TNotebook.Tab", background=[("selected", SURFACE)], foreground=[("selected", INK)])
    style.configure("TEntry", fieldbackground=SURFACE, padding=6)
    style.configure("TCombobox", fieldbackground=SURFACE, padding=4)
    style.configure("TButton", padding=(14, 7), background=SURFACE, foreground=INK)
    style.map("TButton", background=[("active", "#EDE9DF")])
    style.configure("Accent.TButton", padding=(16, 8), background=ACCENT, foreground="#FFFFFF",
                    font=F_HEAD, borderwidth=0)
    style.map("Accent.TButton",
              background=[("active", ACCENT_DK), ("disabled", "#9DB3AC")],
              foreground=[("disabled", "#E8E4DC")])
    style.configure("TProgressbar", background=ACCENT, troughcolor=LINE, borderwidth=0, thickness=10)
    style.configure("Treeview", background=SURFACE, fieldbackground=SURFACE, rowheight=26,
                    bordercolor=LINE, font=F_BODY)
    style.configure("Treeview.Heading", font=F_HEAD, padding=(8, 6))
    style.configure("TSeparator", background=LINE)
    style.configure("TCheckbutton", background=BG)


class LogBox:
    """只读日志区（线程安全经 queue 汇入）"""
    def __init__(self, parent, height=6):
        self.widget = ScrolledText(parent, height=height, font=F_MONO, bg=SURFACE, fg=INK,
                                   insertbackground=INK, relief="solid", bd=1,
                                   state="disabled", wrap="word")
        self.widget.tag_config("ok", foreground=ACCENT)
        self.widget.tag_config("err", foreground=DANGER)
        self.widget.tag_config("dim", foreground=MUTED)

    def write(self, text, tag=None):
        self.widget.configure(state="normal")
        self.widget.insert("end", text, tag or ())
        self.widget.see("end")
        self.widget.configure(state="disabled")

    def line(self, text, tag=None):
        self.write(text.rstrip("\n") + "\n", tag)


class ScrollFrame(ttk.Frame):
    """垂直可滚动容器：把页面装进 Canvas，内容高于可视区时出现滚动条，
    并支持鼠标滚轮滚动页面（窗口变矮也能看到全部内容）。
    Treeview / Text / Listbox / Combobox 自带滚轮语义（列表滚动、换值），
    对这些控件保持原生行为，不代为滚动页面。"""

    _NATIVE_WHEEL = (tk.Listbox, ttk.Treeview, tk.Text, ttk.Combobox)

    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0, bd=0)
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vsb.set, yscrollincrement=40)
        self.vsb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = ttk.Frame(self.canvas)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

    def _on_inner_configure(self, _e):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self._sync_vsb()
        self.bind_wheel()   # 覆盖动态新增的控件

    def _on_canvas_configure(self, e):
        self.canvas.itemconfigure(self._win, width=e.width)
        self._sync_vsb()   # 纯高度变化时 inner 不触发 Configure，需自查滚动条

    def _sync_vsb(self):
        fits = self.inner.winfo_reqheight() <= self.canvas.winfo_height()
        if fits:
            self.canvas.yview_moveto(0)
            if self.vsb.winfo_ismapped():
                self.vsb.pack_forget()
        elif not self.vsb.winfo_ismapped():
            self.vsb.pack(side="right", fill="y")

    def _on_wheel(self, event):
        if self.inner.winfo_reqheight() <= self.canvas.winfo_height():
            return
        notches = int(event.delta / 120)   # Windows：滚一格 delta=±120
        if notches:
            self.canvas.yview_scroll(-notches, "units")

    def bind_wheel(self):
        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self._bind_rec(self.inner)

    def _bind_rec(self, widget):
        for child in widget.winfo_children():
            if isinstance(child, self._NATIVE_WHEEL):
                continue
            child.bind("<MouseWheel>", self._on_wheel)
            self._bind_rec(child)


# ========== 视频库（自动加载 + 缩略图，参考当前项目视频工作室实现） ==========
LIB_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv", ".ts", ".m4v", ".webm"}
THUMB_DIR = engine.THUMB_CACHE_DIR
CREATE_NO_WINDOW = 0x08000000


def thumb_cache_name(path):
    """缩略图缓存文件名：净化后的文件名前缀 + 完整路径哈希 + 修改时间戳。

    视频现在各自放在独立文件夹里，不同文件夹下可能出现同名视频，
    因此必须把完整路径纳入命名，避免缩略图互相覆盖串图。
    """
    stem = os.path.splitext(os.path.basename(path))[0]
    try:
        stamp = int(os.path.getmtime(path))
    except OSError:
        stamp = 0
    digest = hashlib.md5(os.path.abspath(path).encode("utf-8", "replace")).hexdigest()[:8]
    return (re.sub(r"[^\w.-]", "_", stem)[:60] + "__" + digest + "__" + str(stamp) + ".ppm")


def fmt_hms(seconds):
    seconds = int(seconds or 0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


# ========== 输入框撤销/重做 ==========
# Tk 8.6 起 entry 控件移除了原生 undo 栈（-undo 选项与 edit undo 子命令均不存在），
# Ctrl+Z / Ctrl+Y 默认无任何反应。这里基于 textvariable 变更追踪手写一个等效实现：
# 连续单字符输入在短时间窗内合并为一步，粘贴与程序性改动各自独立成步。
_UNDO_GROUP_GAP = 0.6      # 相邻修改间隔小于此值且为单字符变化 -> 合并为一步
_UNDO_STACK_LIMIT = 200    # 撤销栈深度上限


class EntryUndo:
    """为 ttk.Entry（须绑定 StringVar）提供 Ctrl+Z / Ctrl+Y 撤销与重做。"""

    def __init__(self, entry, var):
        self.entry = entry
        self.var = var
        self.undo_stack = []          # [(text, cursor), ...] 每步起始快照
        self.redo_stack = []
        self._prev = (var.get(), 0)
        self._last_change = 0.0
        self._last_single = False
        self._restoring = False
        var.trace_add("write", self._on_write)
        entry.bind("<Control-z>", self.undo, add="+")
        entry.bind("<Control-Z>", self.undo, add="+")      # CapsLock 开启时 keysym 为大写
        entry.bind("<Control-y>", self.redo, add="+")
        entry.bind("<Control-Y>", self.redo, add="+")
        entry.bind("<Control-Shift-Z>", self.redo, add="+")

    def _cursor(self):
        try:
            return self.entry.index("insert")
        except tk.TclError:
            return 0

    def _on_write(self, *_args):
        if self._restoring:
            return
        text = self.var.get()
        now = time.monotonic()
        old, _ = self._prev
        single = abs(len(text) - len(old)) == 1
        near = (now - self._last_change) < _UNDO_GROUP_GAP
        # 新步骤起点才入栈：单字符连续输入合并，粘贴/清空/程序改动独立成步
        if not (single and near and self._last_single):
            self.undo_stack.append(self._prev)
            if len(self.undo_stack) > _UNDO_STACK_LIMIT:
                self.undo_stack.pop(0)
        self.redo_stack.clear()       # 产生新修改后重做链失效
        self._prev = (text, self._cursor())
        self._last_change = now
        self._last_single = single

    def undo(self, _event=None):
        if not self.undo_stack:
            return "break"
        self.redo_stack.append(self._prev)
        text, cursor = self.undo_stack.pop()
        self._apply(text, cursor)
        return "break"

    def redo(self, _event=None):
        if not self.redo_stack:
            return "break"
        self.undo_stack.append(self._prev)
        text, cursor = self.redo_stack.pop()
        self._apply(text, cursor)
        return "break"

    def _apply(self, text, cursor):
        self._restoring = True
        try:
            if self.var.get() != text:
                self.var.set(text)
            try:
                self.entry.icursor(min(cursor, len(text)))
                # 把选区收缩为光标处的空区间，等效清除选区
                idx = self.entry.index("insert")
                self.entry.selection_range(idx, idx)
            except tk.TclError:
                pass
        finally:
            self._restoring = False
        self._prev = (self.var.get(), self._cursor())
        self._last_change = 0.0       # 恢复后的下一次修改必定开新步
        self._last_single = False


def attach_entry_undo(entry, var):
    """给输入框挂 Ctrl+Z / Ctrl+Y（要求 entry 已绑定该 StringVar）。

    返回的控制器须被调用方持有引用以防 GC。
    """
    ctrl = EntryUndo(entry, var)
    entry._undo_ctrl = ctrl           # 双保险：控件自身也持有一份
    return ctrl


class DownloadTab(ttk.Frame):
    """单个链接反复添加；每个下载任务独立线程，互不阻塞。"""

    # 全局提取锁：站点对无 cookie 的并发网页提取有风控（B 站 HTTP 412），
    # 画质检测 / 兜底重新提取任一时刻只允许一个，避免并行任务互相触发拦截
    _EXTRACT_LOCK = threading.Lock()

    def __init__(self, parent, app):
        super().__init__(parent, padding=(PAD_X, PAD_T, PAD_X, PAD_X))
        self.app = app
        self.qualities = []
        self.detected_url = ""
        self.info_json_path = None   # 检测画质时保存的 yt-dlp 提取结果，下载时复用
        self.detecting = False
        self.task_seq = 0
        self.tasks = {}
        self.active_task = None
        self._dest_syncing = False   # 防止保存位置回调自我触发

        ttk.Label(self, text="视频下载", style="Title.TLabel").pack(anchor="w")
        ttk.Label(self, text="检测一个链接后即可加入并行下载；每个视频自动打包成独立文件夹"
                             "（视频 + 封面.jpg + 视频信息.txt）",
                  style="Muted.TLabel").pack(anchor="w", pady=(2, GAP + 2))

        ttk.Label(self, text="视频链接", style="Head.TLabel").pack(anchor="w")
        row = ttk.Frame(self)
        row.pack(fill="x", pady=(4, GAP))
        self.url_var = tk.StringVar()
        url_entry = ttk.Entry(row, textvariable=self.url_var)
        url_entry.pack(side="left", fill="x", expand=True)
        self.url_undo = attach_entry_undo(url_entry, self.url_var)
        ttk.Button(row, text="粘贴", command=self.paste_url).pack(side="left", padx=(8, 0))

        ttk.Label(self, text="保存位置", style="Head.TLabel").pack(anchor="w")
        row2 = ttk.Frame(self)
        row2.pack(fill="x", pady=(4, GAP))
        # 启动即填入上次使用的目录；此后任何改动自动写回 config.json，长期固定
        self.dest_var = tk.StringVar(value=engine.get_saved_download_dir())
        dest_entry = ttk.Entry(row2, textvariable=self.dest_var)
        dest_entry.pack(side="left", fill="x", expand=True)
        self.dest_undo = attach_entry_undo(dest_entry, self.dest_var)
        ttk.Button(row2, text="浏览…", command=self.browse_dest).pack(side="left", padx=(8, 0))
        ttk.Label(row2, text="（自动记住，下次启动沿用）",
                  style="Muted.TLabel").pack(side="left", padx=(8, 0))
        self.dest_var.trace_add("write", self._on_dest_change)

        head = ttk.Frame(self)
        head.pack(fill="x", pady=(2, 4))
        ttk.Label(head, text="画质（仅 ≥720p，同分辨率取最大文件，优先 60fps）",
                  style="Head.TLabel").pack(side="left")
        self.detect_btn = ttk.Button(head, text="检测画质", command=self.detect)
        self.detect_btn.pack(side="right")

        self.qlist = tk.Listbox(self, height=3, font=F_BODY, bg=SURFACE, fg=INK,
                                selectbackground=ACCENT, selectforeground="#FFFFFF",
                                relief="solid", bd=1, activestyle="none", highlightthickness=0)
        self.qlist.pack(fill="x")

        opt = ttk.Frame(self)
        opt.pack(fill="x", pady=(GAP, 4))
        self.sub_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt, text="同时下载字幕（博主上传 + 自动生成，自动转 SRT）",
                        variable=self.sub_var).pack(side="left")

        row3 = ttk.Frame(self)
        row3.pack(fill="x", pady=(GAP, 4))
        self.prog = ttk.Progressbar(row3, mode="determinate", maximum=100)
        self.prog.pack(side="left", fill="x", expand=True)
        self.pct_var = tk.StringVar(value="")
        ttk.Label(row3, textvariable=self.pct_var, style="Muted.TLabel", width=8).pack(side="left", padx=(8, 0))
        self.dl_btn = ttk.Button(row3, text="加入并行下载", style="Accent.TButton",
                                 command=self.start_download)
        self.dl_btn.pack(side="right")

        task_head = ttk.Frame(self)
        task_head.pack(fill="x", pady=(4, 4))
        ttk.Label(task_head, text="并行下载任务", style="Head.TLabel").pack(side="left")
        ttk.Label(task_head, text="点击任务可查看对应进度", style="Muted.TLabel").pack(side="right")

        cols = ("id", "url", "quality", "progress", "status", "dest")
        heads = ("任务", "链接", "画质", "进度", "状态", "保存位置")
        widths = (55, 240, 90, 70, 70, 210)
        self.task_tree = ttk.Treeview(self, columns=cols, show="headings", height=4)
        for c, h, w in zip(cols, heads, widths):
            self.task_tree.heading(c, text=h)
            self.task_tree.column(c, width=w, anchor="w")
        self.task_tree.pack(fill="x")
        self.task_tree.bind("<<TreeviewSelect>>", self.on_task_select)

        self.log = LogBox(self, height=5)
        self.log.widget.pack(fill="both", expand=True, pady=(GAP, 0))

    def paste_url(self):
        try:
            self.url_var.set(self.clipboard_get().strip())
        except tk.TclError:
            pass

    def browse_dest(self):
        d = filedialog.askdirectory(initialdir=self.dest_var.get() or engine.SCRIPT_DIR)
        if d:
            self.dest_var.set(d)
            self.log.line(f"[设置] 保存位置已改为：{d}（已记住，下次启动自动沿用）", "ok")

    def _on_dest_change(self, *_args):
        """保存位置一有改动就写回 config.json，实现长期固定"""
        if self._dest_syncing:
            return
        raw = self.dest_var.get()
        d = engine.clean_path(raw)
        self._dest_syncing = True
        try:
            if d and d != raw:      # 去掉用户拖入时带的首尾空格/引号
                self.dest_var.set(d)
            if d:
                engine.set_saved_download_dir(d)
        finally:
            self._dest_syncing = False

    def set_detecting(self, busy):
        self.detecting = busy
        self.detect_btn.configure(state="disabled" if busy else "normal")

    def detect(self):
        url = engine.clean_path(self.url_var.get())
        if not url.lower().startswith("http"):
            messagebox.showwarning("提示", "请先填入有效的 http 链接")
            return
        if self.detecting:
            return
        self.set_detecting(True)
        self.log.line("[信息] 正在检测可用画质 ...", "dim")
        threading.Thread(target=self._detect_worker, args=(url,), daemon=True).start()

    def _detect_worker(self, url):
        try:
            ytdlp = engine.ensure_ytdlp()
            with DownloadTab._EXTRACT_LOCK:   # 与并行任务的兜底提取串行，规避风控
                raw = engine.fetch_info_json(
                    ytdlp, url, log=lambda m: self.app.q.put(("sys_log", m)))
            if not raw:
                self.app.q.put(("detect_done", url, None, None,
                                "站点风控或网络异常，请稍后重试"))
                return
            best = engine.parse_qualities(raw)
            info_path = engine.save_info_json(raw) if best else None
            self.app.q.put(("detect_done", url, best, info_path, None))
        except Exception as e:
            self.app.q.put(("detect_done", url, None, None, str(e)))

    def on_detect_done(self, url, best, info_path, err):
        self.set_detecting(False)
        if err or not best:
            self.log.line(f"[错误] 画质检测失败{': ' + err if err else '，未找到 ≥720p 格式'}", "err")
            return
        self.detected_url = url
        self.qualities = best
        self._drop_info_json()
        self.info_json_path = info_path
        self.qlist.delete(0, "end")
        for i, f in enumerate(best, 1):
            size = f.get("filesize") or f.get("filesize_approx") or 0
            fps = round(f.get("fps") or 0)
            tag = "（最高，推荐）" if i == 1 else ""
            self.qlist.insert("end", f"  {f['height']}p {fps}fps  ~{engine.format_size(size)} {tag}")
        self.qlist.selection_set(0)
        self.log.line(f"[OK] 检测到 {len(best)} 档画质；点击「加入并行下载」后可继续添加新链接", "ok")

    def _drop_info_json(self):
        if self.info_json_path:
            try:
                os.remove(self.info_json_path)
            except OSError:
                pass
            self.info_json_path = None

    def start_download(self):
        url = engine.clean_path(self.url_var.get())
        if not url.lower().startswith("http"):
            messagebox.showwarning("提示", "请先填入有效的 http 链接")
            return
        if url != self.detected_url or not self.qualities:
            messagebox.showwarning("提示", "当前链接尚未检测画质，请先点击「检测画质」")
            return
        if not self.info_json_path or not os.path.isfile(self.info_json_path):
            messagebox.showwarning("提示", "画质检测结果已失效，请重新点击「检测画质」")
            return
        sel = self.qlist.curselection()
        if not sel:
            messagebox.showwarning("提示", "请选择一档画质")
            return
        for item in self.tasks.values():
            if item["url"] == url and item["status"] == "下载中":
                messagebox.showinfo("提示", "这个视频正在下载中，无需重复添加")
                return

        dest = engine.clean_path(self.dest_var.get()) or engine.DEFAULT_DOWNLOAD_DIR
        os.makedirs(dest, exist_ok=True)
        engine.set_saved_download_dir(dest)   # 记住本次位置，长期固定
        fmt = self.qualities[sel[0]]
        fid = fmt["format_id"]
        height = fmt["height"]

        # 每个任务一份独立的结果副本：任务结束自行删除，互不影响
        try:
            with open(self.info_json_path, "r", encoding="utf-8") as f:
                raw_text = f.read()
            task_info = engine.save_info_json(raw_text)
        except OSError:
            messagebox.showwarning("提示", "画质检测结果已失效，请重新点击「检测画质」")
            return

        # 用视频标题建独立文件夹：视频 + 封面.jpg + 视频信息.txt 都放在里面
        try:
            meta = json.loads(raw_text)
        except ValueError:
            meta = {}
        task_folder = engine.unique_folder(
            dest, engine.sanitize_folder_name(meta.get("title"), "video"))
        try:
            os.makedirs(task_folder, exist_ok=True)
        except OSError as e:
            messagebox.showerror("创建文件夹失败", f"{task_folder}\n{e}")
            return

        self.task_seq += 1
        task_id = f"T{self.task_seq}"
        self.tasks[task_id] = {
            "url": url,
            "quality": f"{height}p",
            "pct": 0.0,
            "status": "下载中",
            "dest": dest,
            "folder": task_folder,
            "with_subs": self.sub_var.get(),
        }
        self.task_tree.insert("", "end", iid=task_id, values=(
            task_id, self._display_url(url), f"{height}p", "0.0%", "下载中", task_folder))
        self.task_tree.selection_set(task_id)
        self.active_task = task_id
        self.prog["value"] = 0
        self.pct_var.set("0.0%")
        sub_note = "（含字幕）" if self.sub_var.get() else ""
        self.log.line(f"[任务 {task_id}] {height}p 开始下载{sub_note} → {task_folder}", "dim")
        self.log.line("[提示] 该任务已在后台运行，可以继续检测并添加下一个视频", "dim")
        threading.Thread(target=self._download_worker,
                         args=(task_id, url, fid, task_folder, self.sub_var.get(),
                               task_info, meta, f"{height}p"),
                         daemon=True).start()

    def _display_url(self, url, limit=44):
        return url if len(url) <= limit else url[: limit - 3] + "..."

    SUB_LANGS = "en,zh,ja,zh-Hans,zh-Hant,ko,es,fr,de"

    def _download_worker(self, task_id, url, fid, folder, with_subs=False,
                         info_json_path=None, meta=None, quality_label=""):
        try:
            ytdlp = engine.ensure_ytdlp()
            ffmpeg_path, _ = engine.ensure_ffmpeg()
            # 主下载刻意不带任何字幕参数：yt-dlp 会先拉字幕再下视频流，
            # 字幕接口被风控/网络阻断时整个任务会直接报错退出（视频 0 字节）。
            # 字幕改为视频完成后单独拉取，失败只提示，不影响任务结果。
            opts = ["-f", f"{fid}+ba/b", "--merge-output-format", "mp4",
                    "--ffmpeg-location", os.path.dirname(ffmpeg_path),
                    "--newline", "--no-playlist",
                    # 封面一并下载，随后统一转成 1280x720 的 封面.jpg
                    "--write-thumbnail", "--convert-thumbnails", "jpg",
                    "-o", engine.output_template(folder)]

            rc = 1
            if info_json_path and os.path.isfile(info_json_path):
                # 复用检测结果：下载阶段不再请求网页，规避二次提取被站点风控拦截
                rc, _ = self._run_ytdlp(
                    [ytdlp, "--load-info-json", info_json_path, *opts], task_id)
            if rc != 0:
                self.app.q.put(("sys_log", f"[任务 {task_id}] 复用检测结果下载失败"
                                          "（多为 CDN 链接过期），改用链接重新提取"))
                self.app.q.put(("dl_progress", task_id, 0.0))
                rc = self._fallback_download(task_id, ytdlp, url, opts)

            if rc == 0:
                self._pack_task(task_id, ffmpeg_path, folder, meta, quality_label)
                if with_subs:
                    self._fetch_subtitles(task_id, ytdlp, url, folder,
                                          info_json_path, meta=meta)
            self.app.q.put(("dl_done", task_id, rc, folder))
        except Exception as e:
            self.app.q.put(("dl_done", task_id, 1, f"出错: {e}"))
        finally:
            if info_json_path:
                try:
                    os.remove(info_json_path)
                except OSError:
                    pass

    def _fallback_download(self, task_id, ytdlp, url, opts):
        """复用检测结果失败（如 CDN 链接过期 403）时的兜底：重新提取后继续下载。

        提取阶段必须全局串行：并行任务若同时请求网页提取，会互相触发站点风控
        （B 站 HTTP 412），重试也同步撞车，导致并行下载集体失败——这正是并行
        下载失败的主因。只有提取持锁，媒体下载不持锁，不损失并行速度。
        """
        def slog(m):
            self.app.q.put(("sys_log", f"[任务 {task_id}] {m}"))

        with DownloadTab._EXTRACT_LOCK:
            fresh = engine.fetch_info_json(ytdlp, url, log=slog)
        if fresh:
            tmp = engine.save_info_json(fresh)
            try:
                rc, _ = self._run_ytdlp(
                    [ytdlp, "--load-info-json", tmp, *opts], task_id)
            finally:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
            if rc == 0:
                return 0

        # 全新提取仍失败（风控持续/网络异常）：最后回退为直接链接下载，同样串行
        with DownloadTab._EXTRACT_LOCK:
            return self._run_ytdlp_with_retry([ytdlp, *opts, url], task_id)

    def _fetch_subtitles(self, task_id, ytdlp, url, folder, info_json_path,
                         meta=None):
        """视频下载完成后单独拉字幕；任何失败都只写日志，不影响任务成功状态。

        字幕语言跟随标题语言（v1.9）：AI 识别视频标题的主要语言，只拉该语言
        的字幕（如标题是英文就拉英文字幕）；AI 不可用/识别失败时回退到
        原来的多语言全量列表。--socket-timeout/--retries 收紧：字幕端点不通时
        快速放弃，避免任务长时间卡在重试（主视频下载不受此限制）。
        """
        sub_langs = self.SUB_LANGS
        title = ""
        if isinstance(meta, dict):
            title = str(meta.get("title") or "").strip()
        if title:
            code = engine.ai_detect_language(title)
            if code:
                langs = engine.ytdlp_sub_langs(code)
                if langs:
                    sub_langs = langs
                    self.app.q.put(("dl_log", task_id,
                                    f"[字幕] AI 识别标题语言为 {code}，"
                                    f"按标题语言拉取字幕（{langs}）"))
            else:
                self.app.q.put(("dl_log", task_id,
                                "[字幕] AI 语言识别不可用，按多语言列表拉取字幕"))
        opts = ["--skip-download", "--newline", "--no-playlist",
                "--socket-timeout", "15", "--retries", "2",
                "--write-subs", "--write-auto-subs",
                "--sub-langs", sub_langs,
                "--sub-format", "srt/best", "--convert-subs", "srt",
                "-o", engine.output_template(folder)]
        rc = 1
        if info_json_path and os.path.isfile(info_json_path):
            rc, _ = self._run_ytdlp(
                [ytdlp, "--load-info-json", info_json_path, *opts], task_id)
        if rc != 0:
            # 复用结果失效/报错时，用链接直接提取再试一次（提取同样全局串行防风控）
            with DownloadTab._EXTRACT_LOCK:
                rc, _ = self._run_ytdlp([ytdlp, *opts, url], task_id)

        try:
            has_srt = any(n.lower().endswith(".srt") for n in os.listdir(folder))
        except OSError:
            has_srt = False
        if has_srt:
            self.app.q.put(("dl_log", task_id,
                            "[字幕] 已下载到本视频文件夹（.srt）"))
        else:
            self.app.q.put(("dl_log", task_id,
                            "[字幕] 该视频没有可用字幕，或字幕拉取失败"
                            "——不影响视频/封面/信息文件，任务仍算完成"))

    def _pack_task(self, task_id, ffmpeg_path, folder, meta, quality_label):
        """下载完成后打包：视频信息.txt（标题/简介/视频链接/博主链接）+ 封面.jpg（1280x720）"""
        data = meta if isinstance(meta, dict) else {}

        # 1) 信息 txt
        try:
            engine.write_info_txt(folder, data, quality_label)
            self.app.q.put(("dl_log", task_id, "[打包] 视频信息.txt 已生成"
                                               "（标题 / 简介 / 视频链接 / 博主主页）"))
        except Exception as e:
            self.app.q.put(("dl_log", task_id, f"[打包] 视频信息.txt 写入失败: {e}"))

        # 2) 封面转 1280x720
        if engine.make_cover_1280x720(ffmpeg_path, folder):
            self.app.q.put(("dl_log", task_id, "[打包] 封面.jpg（1280x720）已生成"))
        else:
            self.app.q.put(("dl_log", task_id, "[打包] 该视频无可用封面，已跳过封面步骤"))

    def _run_ytdlp(self, cmd, task_id):
        """运行 yt-dlp 并把进度/日志转发到主线程；返回 (returncode, 输出行)"""
        try:
            proc = engine.popen_process(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, encoding="utf-8", errors="replace", bufsize=1)
        except Exception as e:
            self.app.q.put(("dl_log", task_id, f"[错误] 无法启动下载器: {e}"))
            return 1, []
        lines = []
        pct_re = re.compile(r"\[download\]\s+([\d.]+)%")
        for line in proc.stdout:
            line = line.rstrip()
            lines.append(line)
            m = pct_re.search(line)
            if m:
                self.app.q.put(("dl_progress", task_id, float(m.group(1))))
            elif line and "Deprecated" not in line and "WARNING" not in line:
                self.app.q.put(("dl_log", task_id, line))
        return proc.wait(), lines

    def _run_ytdlp_with_retry(self, cmd, task_id, attempts=3):
        """直接链接下载：对站点风控（HTTP 412）自动等待重试"""
        wait = 6
        rc, lines = 1, []
        for i in range(attempts):
            rc, lines = self._run_ytdlp(cmd, task_id)
            if rc == 0:
                return 0
            joined = "\n".join(lines)
            if "412" not in joined and "Unable to download webpage" not in joined:
                return rc
            if i < attempts - 1:
                self.app.q.put(("sys_log",
                                f"[任务 {task_id}] 站点风控拦截（HTTP 412），{wait}s 后重试 "
                                f"({i + 2}/{attempts}) ..."))
                time.sleep(wait)
                wait *= 2
        return rc

    def on_task_select(self, _event=None):
        sel = self.task_tree.selection()
        if not sel:
            return
        task_id = sel[0]
        item = self.tasks.get(task_id)
        if not item:
            return
        self.active_task = task_id
        self.prog["value"] = item["pct"]
        self.pct_var.set(f"{item['pct']:.1f}%" if item["status"] == "下载中" else item["status"])

    def on_dl_progress(self, task_id, pct):
        item = self.tasks.get(task_id)
        if not item:
            return
        item["pct"] = pct
        if self.task_tree.exists(task_id):
            self.task_tree.set(task_id, "progress", f"{pct:.1f}%")
            self.task_tree.set(task_id, "status", "下载中")
        if task_id == self.active_task:
            self.prog["value"] = pct
            self.pct_var.set(f"{pct:.1f}%")

    def on_dl_log(self, task_id, text):
        self.log.line(f"[任务 {task_id}] {text}", "dim")

    def on_dl_done(self, task_id, rc, folder):
        item = self.tasks.get(task_id)
        if item:
            item["pct"] = 100.0 if rc == 0 else item["pct"]
            item["status"] = "完成" if rc == 0 else "失败"
        if self.task_tree.exists(task_id):
            self.task_tree.set(task_id, "progress", "100%" if rc == 0 else "—")
            self.task_tree.set(task_id, "status", "完成" if rc == 0 else "失败")
            if rc == 0:
                self.task_tree.set(task_id, "dest", folder)
        if task_id == self.active_task:
            self.prog["value"] = 100 if rc == 0 else self.prog["value"]
            self.pct_var.set("完成" if rc == 0 else "失败")

        if rc == 0:
            self.log.line(f"[任务 {task_id}] [完成] 已打包到独立文件夹: {folder}", "ok")
            if item and item.get("with_subs"):
                self.log.line(f"[任务 {task_id}] 字幕（.srt，若有）已存入该视频文件夹", "dim")
            # 视频库指向下载根目录并刷新，新视频（含其子文件夹）立刻可见
            root_dir = (item or {}).get("dest") or os.path.dirname(folder)
            try:
                self.app.lib_tab.dir_var.set(root_dir)
                self.app.lib_tab.refresh()
            except Exception:
                pass
            if self.active_count() == 0:
                engine.open_folder(folder)
        else:
            self.log.line(f"[任务 {task_id}] [错误] 下载失败，请查看上方日志（多为站点风控或网络问题）", "err")

    def active_count(self):
        return sum(1 for item in self.tasks.values() if item["status"] == "下载中")


class SubtitleTab(ttk.Frame):
    """本地 ASR 字幕生成：运行时（tools\\python，faster-whisper）随安装包分发；
    Whisper large-v3-turbo 模型（约 1.5GB）不进安装包，需从开源模型库
    下载到 tools\\asr_model。把视频/音频转写为 SRT，输出到原文件同文件夹。
    任务串行排队（GPU 同一时刻只跑一个），子进程运行、界面不卡顿。"""

    MEDIA_EXTS = {".mp4", ".mkv", ".avi", ".mov", ".flv", ".wmv", ".ts",
                  ".m4v", ".webm", ".mp3", ".wav", ".m4a", ".flac",
                  ".aac", ".ogg"}
    LANGS = [("自动检测", ""), ("中文", "zh"), ("日语", "ja"),
             ("英语", "en"), ("韩语", "ko")]

    def __init__(self, parent, app):
        super().__init__(parent, padding=(PAD_X, PAD_T, PAD_X, PAD_X))
        self.app = app
        self.seq = 0
        self.jobs = {}            # id -> {"file","pct","status","out"}
        self._stop = threading.Event()
        self._proc = None

        ttk.Label(self, text="字幕生成（本地 Whisper）", style="Title.TLabel").pack(anchor="w")
        ttk.Label(self, text="内置 Whisper large-v3-turbo 引擎识别语音生成 SRT，全程本地运行；"
                             "自动存到视频同文件夹；支持视频与音频，长视频分块转写",
                  style="Muted.TLabel").pack(anchor="w", pady=(2, GAP + 2))

        has_runtime = os.path.isdir(engine.ASR_PYTHON_DIR) and bool(engine.system_python())
        has_model = os.path.isfile(os.path.join(engine.ASR_MODEL_DIR, "model.bin"))
        if engine.asr_env_ready():
            ttk.Label(self, text=f"识别环境已就绪（模型目录：{engine.ASR_MODEL_DIR}）",
                      style="Muted.TLabel").pack(anchor="w", pady=(0, GAP))
        else:
            miss = ("缺少 tools\\python 识别运行时，请重新安装工具箱" if not has_runtime
                    else "识别模型未下载：模型体积约 1.5GB 未随安装包分发，"
                         "点击下方按钮从开源模型库下载后放入 tools\\asr_model 即可使用")
            ttk.Label(self, text=miss, style="Muted.TLabel",
                      foreground=DANGER).pack(anchor="w")
            if has_runtime and not has_model:
                tip = ttk.Frame(self)
                tip.pack(fill="x", pady=(4, GAP))
                ttk.Button(tip, text="打开模型下载页（国内镜像）",
                           command=lambda: webbrowser.open(
                               engine.ASR_MODEL_URL_MIRROR)
                           ).pack(side="left")
                ttk.Button(tip, text="Hugging Face 原站",
                           command=lambda: webbrowser.open(
                               engine.ASR_MODEL_URL_HF)
                           ).pack(side="left", padx=(8, 0))
                ttk.Button(tip, text="下载说明…", command=self.show_model_help
                           ).pack(side="left", padx=(8, 0))
            else:
                ttk.Label(self, text="", style="Muted.TLabel").pack()

        ttk.Label(self, text="视频 / 音频（文件或文件夹，文件夹将批量排队）",
                  style="Head.TLabel").pack(anchor="w")
        row = ttk.Frame(self)
        row.pack(fill="x", pady=(4, GAP))
        self.src_var = tk.StringVar(value=engine.get_saved_download_dir())
        src_entry = ttk.Entry(row, textvariable=self.src_var)
        src_entry.pack(side="left", fill="x", expand=True)
        self.src_undo = attach_entry_undo(src_entry, self.src_var)
        ttk.Button(row, text="浏览…", command=self.browse).pack(side="left", padx=(8, 0))

        opt = ttk.Frame(self)
        opt.pack(fill="x", pady=(0, GAP))
        ttk.Label(opt, text="语言:", style="Head.TLabel").pack(side="left")
        self.lang_box = ttk.Combobox(opt, state="readonly", width=12,
                                     values=[n for n, _ in self.LANGS])
        self.lang_box.current(0)
        self.lang_box.pack(side="left", padx=(8, 0))
        self.gen_btn = ttk.Button(opt, text="生成字幕", style="Accent.TButton",
                                  command=self.start, state="normal" if
                                  engine.asr_env_ready() else "disabled")
        self.gen_btn.pack(side="right")
        self.stop_btn = ttk.Button(opt, text="全部取消", command=self.stop_all,
                                   state="disabled")
        self.stop_btn.pack(side="right", padx=(0, 8))

        cols = ("id", "file", "progress", "status", "out")
        heads = ("任务", "文件", "进度", "状态", "输出")
        widths = (55, 330, 70, 70, 220)
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=5)
        for c, h, w in zip(cols, heads, widths):
            self.tree.heading(c, text=h)
            self.tree.column(c, width=w, anchor="w")
        self.tree.pack(fill="x")

        self.log = LogBox(self, height=5)
        self.log.widget.pack(fill="both", expand=True, pady=(GAP, 0))

    def show_model_help(self):
        messagebox.showinfo("识别模型下载说明", engine.asr_model_missing_hint())

    def browse(self):
        p = filedialog.askopenfilename(
            initialdir=self.src_var.get() or engine.SCRIPT_DIR,
            filetypes=[("媒体文件", "*.mp4 *.mkv *.avi *.mov *.flv *.wmv *.ts "
                        "*.m4v *.webm *.mp3 *.wav *.m4a *.flac *.aac *.ogg"),
                       ("所有文件", "*.*")])
        if p:
            self.src_var.set(p)

    def _srt_out_path(self, video):
        """输出到视频同文件夹；已有同名 srt 时不覆盖，另存 (ASR生成) 副本"""
        base = os.path.splitext(video)[0]
        srt = base + ".srt"
        if os.path.isfile(srt):
            srt = base + " (ASR生成).srt"
        return srt

    def _collect_files(self, path):
        if os.path.isfile(path):
            return [path]
        files = []
        for root, dirs, names in os.walk(path):
            dirs[:] = [d for d in dirs if not d.startswith(".")
                       and d != "thumb_cache"]
            for n in names:
                if os.path.splitext(n)[1].lower() in self.MEDIA_EXTS:
                    files.append(os.path.join(root, n))
        files.sort(key=lambda p: os.path.basename(p).lower())
        return files

    def start(self):
        path = engine.clean_path(self.src_var.get())
        if not path:
            messagebox.showwarning("提示", "请先填入视频/音频路径或文件夹")
            return
        if not os.path.exists(path):
            messagebox.showwarning("提示", "路径不存在，请检查")
            return
        files = self._collect_files(path)
        if not files:
            messagebox.showwarning("提示", "没有找到可识别的媒体文件")
            return
        busy = {j["file"] for j in self.jobs.values()
                if j["status"] in ("排队中", "转写中")}
        fresh = [f for f in files if f not in busy]
        if not fresh:
            messagebox.showinfo("提示", "所选内容均已加入生成队列")
            return
        lang = self.LANGS[self.lang_box.current()][1]

        job_ids = []
        for f in fresh:
            self.seq += 1
            jid = f"S{self.seq}"
            out = self._srt_out_path(f)
            self.jobs[jid] = {"file": f, "pct": 0.0, "status": "排队中", "out": out}
            self.tree.insert("", "end", iid=jid, values=(
                jid, self._display_path(f), "—", "排队中", self._display_path(out)))
            job_ids.append(jid)
        self.log.line(f"[任务] 已加入 {len(job_ids)} 个转写任务（语言："
                      f"{self.LANGS[self.lang_box.current()][0]}）", "dim")
        self.stop_btn.configure(state="normal")
        threading.Thread(target=self._scheduler, args=(job_ids, lang),
                         daemon=True).start()

    def stop_all(self):
        self._stop.set()
        proc = self._proc
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
        self.log.line("[任务] 已请求取消剩余转写", "dim")

    @staticmethod
    def _display_path(path, limit=42):
        return path if len(path) <= limit else "…" + path[-(limit - 1):]

    def _scheduler(self, job_ids, lang):
        """串行执行队列：GPU 同一时刻只跑一个转写"""
        for jid in job_ids:
            if self._stop.is_set():
                self.app.q.put(("asr_done", jid, 1, "已取消"))
                continue
            self._run_job(jid, lang)
        self.app.q.put(("asr_queue_done",))

    def _run_job(self, jid, lang):
        job = self.jobs[jid]
        self.app.q.put(("asr_status", jid, "转写中", 0.0))
        cmd = [engine.system_python(), engine.asr_worker_script(),
               "--video", job["file"],
               "--model", engine.ASR_MODEL_DIR,
               "--out", job["out"],
               "--ffmpeg", engine.FFMPEG_PATH,
               "--ffprobe", engine.FFPROBE_PATH,
               "--language", lang]
        try:
            proc = engine.popen_process(cmd, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True,
                                        encoding="utf-8", errors="replace",
                                        bufsize=1, env=engine.asr_subprocess_env())
        except Exception as e:
            self.app.q.put(("asr_done", jid, 1, f"无法启动识别引擎: {e}"))
            return
        self._proc = proc
        finished = False
        try:
            for line in proc.stdout:
                line = line.rstrip()
                if not line or len(line) > 300:
                    continue
                if line.startswith("@@PROGRESS "):
                    try:
                        self.app.q.put(("asr_progress", jid,
                                        float(json.loads(line[11:])["pct"])))
                    except (ValueError, KeyError):
                        pass
                elif line.startswith("@@LOG "):
                    try:
                        self.app.q.put(("asr_log", jid,
                                        json.loads(line[6:])["msg"]))
                    except (ValueError, KeyError):
                        pass
                elif line.startswith("@@DONE "):
                    try:
                        data = json.loads(line[7:])
                        self.app.q.put(("asr_done", jid, 0,
                                        data.get("srt", job["out"])))
                    except (ValueError, KeyError):
                        self.app.q.put(("asr_done", jid, 0, job["out"]))
                    finished = True
                elif line.startswith("@@ERROR "):
                    try:
                        msg = json.loads(line[8:])["msg"]
                    except (ValueError, KeyError):
                        msg = line
                    self.app.q.put(("asr_done", jid, 1, msg))
                    finished = True
        finally:
            rc = proc.wait()
            self._proc = None
        if not finished:
            if self._stop.is_set():
                self.app.q.put(("asr_done", jid, 1, "已取消"))
            else:
                self.app.q.put(("asr_done", jid, 1,
                                f"识别引擎异常退出（代码 {rc}）"))

    # ---------- 主线程 UI 更新（经消息队列） ----------
    def on_progress(self, jid, pct):
        job = self.jobs.get(jid)
        if not job:
            return
        job["pct"] = pct
        if self.tree.exists(jid):
            self.tree.set(jid, "progress", f"{pct:.0f}%")

    def on_log(self, jid, msg):
        self.log.line(f"[任务 {jid}] {msg}", "dim")

    def on_status(self, jid, status, pct):
        job = self.jobs.get(jid)
        if not job:
            return
        job["status"] = status
        if pct is not None:
            job["pct"] = pct
        if self.tree.exists(jid):
            self.tree.set(jid, "status", status)
            if pct is not None:
                self.tree.set(jid, "progress",
                              f"{pct:.0f}%" if pct else "—")

    def on_done(self, jid, rc, info):
        job = self.jobs.get(jid)
        if job:
            job["status"] = "完成" if rc == 0 else "失败"
            if rc == 0:
                job["pct"] = 100.0
        if self.tree.exists(jid):
            self.tree.set(jid, "status", "完成" if rc == 0 else "失败")
            self.tree.set(jid, "progress", "100%" if rc == 0 else "—")
        if rc == 0:
            self.log.line(f"[任务 {jid}] [完成] 字幕已生成: {info}", "ok")
        elif info == "已取消":
            self.log.line(f"[任务 {jid}] 已取消", "dim")
        else:
            self.log.line(f"[任务 {jid}] [错误] {info}", "err")
        if self._stop.is_set() or not any(
                j["status"] in ("排队中", "转写中") for j in self.jobs.values()):
            self.stop_btn.configure(state="disabled")

    def on_queue_done(self):
        self.stop_btn.configure(state="disabled")
        self.log.line("[队列] 本批字幕生成结束", "dim")


class UploadTab(ttk.Frame):
    """B 站自动投稿：使用工具箱内置 Playwright 投稿引擎（tools\\uploader_src）。
    浏览器登录态长期复用（首次在弹出的浏览器中扫码）；默认预览模式
    （填完表单不点「立即投稿」，供人工核对）。同一时刻只跑一个投稿任务。"""

    # 日志关键词 → 阶段展示（用于状态栏/进度提示）
    STAGE_HINTS = [
        ("本次投稿任务", "引擎已启动"),
        ("启动浏览器", "启动浏览器"),
        ("打开投稿页", "打开投稿页"),
        ("登录态有效", "登录态有效"),
        ("检测到未登录", "等待扫码登录（请在浏览器中操作）"),
        ("检测到登录成功", "登录成功"),
        ("待上传文件", "注入视频"),
        ("等待视频上传", "上传视频…"),
        ("上传/初始化完成", "视频就绪"),
        ("现场检测分区", "现场检测分区"),
        ("已匹配现场分区", "分区已匹配"),
        ("等待候选封面", "选择封面"),
        ("已选择第一张候选封面", "封面已选"),
        ("立即投稿", "提交投稿"),
        ("检测到投稿成功", "投稿成功"),
        ("页面已跳转至投稿管理", "投稿成功"),
        ("全流程执行结束", "流程结束"),
    ]
    DECLARATIONS = ["（自动选择第一项）", "无需标注",
                    "该视频使用人工智能合成技术", "含有虚构演绎内容",
                    "内容为个人观点，仅供参考", "视频内含有危险动作，请勿模仿",
                    "请理性适度消费"]

    def __init__(self, parent, app):
        super().__init__(parent, padding=(PAD_X, PAD_T, PAD_X, PAD_X))
        self.app = app
        self.running = False

        ready = engine.uploader_env_ready()
        ttk.Label(self, text="B 站自动投稿", style="Title.TLabel").pack(anchor="w")
        ttk.Label(self, text="工具箱内置投稿引擎（Playwright）自动填表投稿；默认预览模式"
                             "（只填写不提交），浏览器登录态长期复用，完全独立运行",
                  style="Muted.TLabel").pack(anchor="w", pady=(2, GAP + 2))

        if ready:
            has_login = (os.path.isdir(engine.UPLOADER_PROFILE) and
                         len(os.listdir(engine.UPLOADER_PROFILE)) > 0)
            ttk.Label(self, text=f"内置投稿引擎已就绪"
                                 f"（登录态{'已存在，免登录' if has_login else '未初始化，首次投稿需扫码'}）",
                      style="Muted.TLabel").pack(anchor="w", pady=(0, GAP))
        else:
            ttk.Label(self, text="内置投稿引擎不可用：tools\\python 运行时或"
                                 "tools\\ms-playwright\\chromium 浏览器内核缺失，请在界面重新初始化",
                      style="Muted.TLabel", foreground=DANGER).pack(anchor="w", pady=(0, GAP))

        # —— 全局 AI 状态（屏幕识别 + 内容识别；分区/简介/字幕语言均依赖） ——
        ai_on, t_model, v_model = engine.ai_status()
        self._title_lang_code = ""   # AI 识别出的标题语言代码（字幕匹配用）
        airow = ttk.Frame(self)
        airow.pack(fill="x", pady=(0, GAP))
        if ai_on:
            ai_text = (f"AI 屏幕识别已启用（文本 {t_model} · 视觉 {v_model}）；"
                       "分区/简介/话题由 AI 看屏操作，字幕语言随标题语言自动匹配")
            ai_color = None
        else:
            ai_text = ("AI 未启用：分区检测/简介填写/字幕语言识别不可用，"
                       "请检查 data\\ai_config.json（enabled=true、api_key 有效）")
            ai_color = DANGER
        kw = {"style": "Muted.TLabel"}
        if ai_color:
            kw["foreground"] = ai_color
        ttk.Label(airow, text=ai_text, **kw).pack(side="left")
        ttk.Button(airow, text="测试 AI 连接",
                   command=self.test_ai).pack(side="left", padx=(10, 0))

        ttk.Label(self, text="视频文件（选中后自动读取同目录 视频信息.txt 预填标题/简介）",
                  style="Head.TLabel").pack(anchor="w")
        row = ttk.Frame(self)
        row.pack(fill="x", pady=(4, GAP))
        self.video_var = tk.StringVar()
        video_entry = ttk.Entry(row, textvariable=self.video_var)
        video_entry.pack(side="left", fill="x", expand=True)
        self.video_undo = attach_entry_undo(video_entry, self.video_var)
        ttk.Button(row, text="浏览…", command=self.browse).pack(side="left", padx=(8, 0))

        ttk.Label(self, text="标题（上限 80 字，超长由引擎自动截断）",
                  style="Head.TLabel").pack(anchor="w")
        self.title_var = tk.StringVar()
        title_entry = ttk.Entry(self, textvariable=self.title_var)
        title_entry.pack(fill="x", pady=(4, GAP))
        self.title_undo = attach_entry_undo(title_entry, self.title_var)

        ttk.Label(self, text="简介（支持换行）", style="Head.TLabel").pack(anchor="w")
        self.desc_text = tk.Text(self, height=4, font=F_BODY, bg=SURFACE, fg=INK,
                                 insertbackground=INK, relief="solid", bd=1,
                                 wrap="word", highlightthickness=0)
        self.desc_text.pack(fill="x", pady=(4, GAP))

        # —— 分区：可输入名称；投稿时上传后现场检测并自动匹配（检测按钮仍可用） ——
        zrow = ttk.Frame(self)
        zrow.pack(fill="x", pady=(0, GAP))
        ttk.Label(zrow, text="分区（可输入名称，投稿时现场检测自动匹配；也可点右侧按钮检测）:",
                  style="Head.TLabel").pack(anchor="w")
        zline = ttk.Frame(zrow)
        zline.pack(fill="x", pady=(4, 0))
        self.zone_var = tk.StringVar()
        self.zone_box = ttk.Combobox(zline, textvariable=self.zone_var, width=26)
        self.zone_box.pack(side="left")
        self.area_btn = ttk.Button(zline, text="检测/刷新分区列表",
                                   command=self.detect_areas)
        self.area_btn.pack(side="left", padx=(10, 0))
        self._areas_cache = []   # [{"name": ...}]

        # —— 加入合集：自动检测当前账号合集 ——
        crow = ttk.Frame(self)
        crow.pack(fill="x", pady=(0, GAP))
        ttk.Label(crow, text="加入合集（点右侧按钮自动检测账号合集，可留空不加入）:",
                  style="Head.TLabel").pack(anchor="w")
        cline = ttk.Frame(crow)
        cline.pack(fill="x", pady=(4, 0))
        self.collection_var = tk.StringVar()
        self.collection_box = ttk.Combobox(cline, textvariable=self.collection_var,
                                           width=26)
        self.collection_box.pack(side="left")
        self.collection_btn = ttk.Button(cline, text="检测合集",
                                         command=self.detect_collections)
        self.collection_btn.pack(side="left", padx=(10, 0))
        self._collections_cache = []

        # —— 原始字幕：随视频同步上传，语言由 AI 识别标题语言自动匹配 ——
        srow = ttk.Frame(self)
        srow.pack(fill="x", pady=(0, GAP))
        ttk.Label(srow, text="原始字幕（.srt，自动从视频同目录查找，语言随标题语言自动匹配）:",
                  style="Head.TLabel").pack(anchor="w")
        sline = ttk.Frame(srow)
        sline.pack(fill="x", pady=(4, 0))
        self.subtitle_var = tk.StringVar()
        sub_entry = ttk.Entry(sline, textvariable=self.subtitle_var)
        sub_entry.pack(side="left", fill="x", expand=True)
        self.subtitle_undo = attach_entry_undo(sub_entry, self.subtitle_var)
        ttk.Button(sline, text="浏览…",
                   command=self.browse_subtitle).pack(side="left", padx=(8, 0))
        ttk.Label(sline, text="字幕语言:", style="Head.TLabel").pack(side="left",
                                                                     padx=(10, 0))
        self.subtitle_lang_var = tk.StringVar(value="英语")
        self.SUBTITLE_LANGS = ["英语", "简体中文", "繁體中文", "日本語", "한국어",
                               "西班牙语", "法语", "德语", "俄语", "葡萄牙语",
                               "阿拉伯语", "泰语", "越南语", "印尼语"]
        self.subtitle_lang_box = ttk.Combobox(
            sline, textvariable=self.subtitle_lang_var, width=10,
            state="readonly", values=self.SUBTITLE_LANGS)
        self.subtitle_lang_box.pack(side="left", padx=(6, 0))

        grid = ttk.Frame(self)
        grid.pack(fill="x", pady=(0, GAP))
        grid.columnconfigure(1, weight=1)
        grid.columnconfigure(3, weight=1)
        ttk.Label(grid, text="标签（逗号分隔，如：鸣潮,游戏实况）:",
                  style="Head.TLabel").grid(row=0, column=0, sticky="w")
        self.tags_var = tk.StringVar()
        tags_entry = ttk.Entry(grid, textvariable=self.tags_var)
        tags_entry.grid(row=0, column=1, sticky="we", padx=(6, 12))
        self.tags_undo = attach_entry_undo(tags_entry, self.tags_var)
        ttk.Label(grid, text="创作声明:", style="Head.TLabel").grid(row=0, column=2, sticky="w")
        self.decl_box = ttk.Combobox(grid, state="readonly", width=30,
                                     values=self.DECLARATIONS)
        self.decl_box.current(0)
        self.decl_box.grid(row=0, column=3, sticky="we", padx=(6, 0))

        # —— 话题：手动输入 + 按所选分区自动检测、双击添加 ——
        ttk.Label(self, text="话题（逗号分隔，可手动输入；检测后可双击下方结果添加）",
                  style="Head.TLabel").pack(anchor="w")
        tline = ttk.Frame(self)
        tline.pack(fill="x", pady=(4, 4))
        self.topics_var = tk.StringVar()
        topics_entry = ttk.Entry(tline, textvariable=self.topics_var)
        topics_entry.pack(side="left", fill="x", expand=True)
        self.topics_undo = attach_entry_undo(topics_entry, self.topics_var)
        self.topic_btn = ttk.Button(tline, text="检测本分区话题",
                                    command=self.detect_topics)
        self.topic_btn.pack(side="left", padx=(8, 0))
        tlist = ttk.Frame(self)
        tlist.pack(fill="x", pady=(0, GAP))
        self.topic_lb = tk.Listbox(tlist, height=4, selectmode="extended",
                                   font=F_BODY, bg=SURFACE, fg=INK, relief="solid",
                                   bd=1, highlightthickness=0, activestyle="dotbox")
        tsb = ttk.Scrollbar(tlist, orient="vertical", command=self.topic_lb.yview)
        self.topic_lb.configure(yscrollcommand=tsb.set)
        self.topic_lb.pack(side="left", fill="x", expand=True)
        tsb.pack(side="left", fill="y")
        self.topic_lb.bind("<Double-Button-1>", lambda _e: self._add_selected_topics())
        ttk.Button(tlist, text="添加选中话题", width=14,
                   command=self._add_selected_topics).pack(side="left",
                                                           fill="y", padx=(8, 0))

        opt = ttk.Frame(self)
        opt.pack(fill="x", pady=(0, GAP))
        self.preview_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt, text="预览模式（只填写，不点「立即投稿」）",
                        variable=self.preview_var).pack(side="left")
        self.cover_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt, text="自动选择第一张候选封面",
                        variable=self.cover_var).pack(side="left", padx=(16, 0))

        row2 = ttk.Frame(self)
        row2.pack(fill="x", pady=(0, GAP))
        self.stage_var = tk.StringVar(value="")
        ttk.Label(row2, textvariable=self.stage_var, style="Muted.TLabel").pack(
            side="left", padx=(2, 8))
        self.up_btn = ttk.Button(row2, text="开始投稿", style="Accent.TButton",
                                 command=self.start, state="normal" if ready else "disabled")
        self.up_btn.pack(side="right")

        self.log = LogBox(self, height=6)
        self.log.widget.pack(fill="both", expand=True, pady=(0, 0))
        # 启动时从 data\catalog 缓存恢复分区树（无需开浏览器）
        self.load_areas_cache()

    # ---------- 分区/话题检测 ----------
    def _areas_cache_file(self):
        return os.path.join(engine.CATALOG_DIR, "areas.json")

    def load_areas_cache(self):
        """读取本地分区缓存，填充单级分区下拉；无缓存则保持空，可点检测按钮获取。"""
        try:
            import json
            with open(self._areas_cache_file(), "r", encoding="utf-8") as f:
                payload = json.load(f)
            self._fill_areas(payload.get("areas", []))
            ts = payload.get("cached_at", "")
            self.log.line(f"[分区] 已载入本地分区缓存（{ts}），可点「检测/刷新」更新", "dim")
        except (OSError, ValueError):
            pass

    def _fill_areas(self, areas):
        """填充单级分区下拉；兼容旧缓存中的两级树，自动拍平为叶子名称。"""
        self._areas_cache = areas or []
        names = []
        for a in self._areas_cache:
            if not isinstance(a, dict):
                continue
            name = str(a.get("name", "")).strip()
            children = a.get("children") or []
            if children:
                names.extend(str(c.get("name", "")).strip() for c in children
                             if isinstance(c, dict) and str(c.get("name", "")).strip())
            elif name:
                names.append(name)
        seen, flat = set(), []
        for n in names:
            if n and n not in seen:
                seen.add(n)
                flat.append(n)
        self.zone_box.configure(values=flat)

    def _current_zone_steps(self):
        z = self.zone_var.get().strip()
        if "/" in z:
            return [s.strip() for s in z.split("/") if s.strip()]
        return [z] if z else []

    def _set_detect_buttons(self, state: str) -> None:
        """统一设置所有检测按钮的可用状态（disabled / normal）。

        三个检测按钮（分区/合集/话题）互斥：任一检测运行时全部禁用，
        避免并行启动多个浏览器子进程导致资源竞争与界面卡死。
        """
        for btn in (self.area_btn, self.collection_btn, self.topic_btn):
            try:
                btn.configure(state=state)
            except Exception:  # noqa: BLE001
                pass

    def detect_areas(self):
        """后台启动内置浏览器：先上传所选视频（B站上传视频后才进入投稿区），
        再抓取单级分区列表（复用登录态），完成后回填下拉。"""
        if self.running:
            messagebox.showinfo("提示", "有投稿任务进行中，请稍后再检测")
            return
        video = engine.clean_path(self.video_var.get())
        if not video or not os.path.isfile(video):
            messagebox.showwarning("提示", "检测分区需要先选择视频文件（B 站上传视频后才显示分区）")
            return
        if not engine.uploader_env_ready():
            messagebox.showwarning("提示", "投稿引擎不可用，无法检测分区")
            return
        self._set_detect_buttons("disabled")
        self.up_btn.configure(state="disabled")
        self.stage_var.set("正在检测分区列表（需先上传视频，请勿关闭弹出的浏览器）…")
        self.log.line("[分区] 开始检测分区列表（会上传视频但不会投稿）…", "dim")
        threading.Thread(target=self._run_catalog, args=("areas",), daemon=True).start()

    def detect_collections(self):
        """后台检测当前账号的全部合集（创作中心 seasons 接口），回填下拉。"""
        if self.running:
            messagebox.showinfo("提示", "有投稿任务进行中，请稍后再检测")
            return
        if not engine.uploader_env_ready():
            messagebox.showwarning("提示", "投稿引擎不可用，无法检测合集")
            return
        self._set_detect_buttons("disabled")
        self.up_btn.configure(state="disabled")
        self.stage_var.set("正在检测账号合集（浏览器自动操作，请勿关闭弹出的浏览器）…")
        self.log.line("[合集] 开始检测当前账号的合集列表…", "dim")
        threading.Thread(target=self._run_catalog, args=("collections",), daemon=True).start()

    def detect_topics(self):
        """按当前选定的分区，上传已选视频后枚举该分区「参与话题」。"""
        if self.running:
            messagebox.showinfo("提示", "有投稿任务进行中，请稍后再检测")
            return
        steps = self._current_zone_steps()
        if len(steps) < 1:
            messagebox.showwarning("提示", "请先选择分区，再检测话题")
            return
        video = engine.clean_path(self.video_var.get())
        if not video or not os.path.isfile(video):
            messagebox.showwarning("提示", "检测话题需要先选择视频文件（B 站要上传视频后才显示话题）")
            return
        if not engine.uploader_env_ready():
            messagebox.showwarning("提示", "投稿引擎不可用，无法检测话题")
            return
        self._set_detect_buttons("disabled")
        self.up_btn.configure(state="disabled")
        self.stage_var.set(f"正在检测「{'/'.join(steps)}」分区的话题…")
        self.log.line(f"[话题] 开始检测分区 {steps} 的可选话题（会上传视频但不会投稿）…", "dim")
        threading.Thread(target=self._run_catalog,
                         args=("topics",), daemon=True).start()

    def _run_catalog(self, kind):
        """主进程内常驻 asyncio 循环：检测复用同一个浏览器会话，不重启。"""
        video = engine.clean_path(self.video_var.get())
        zone = "/".join(self._current_zone_steps()) if kind == "topics" else None
        out_json = os.path.join(engine.CATALOG_DIR, f"_gui_{kind}.json")
        self.app.loop.run_in_executor(
            None, self._catalog_in_loop, kind, video, zone, out_json)

    def _catalog_in_loop(self, kind, video, zone, out_json):
        """在后台 asyncio loop 中执行检测；通过 BrowserManager 复用浏览器。"""
        import asyncio
        import importlib
        if engine.UPLOADER_SRC_DIR not in sys.path:
            sys.path.insert(0, engine.UPLOADER_SRC_DIR)

        handler = None
        try:
            config_mod = importlib.import_module("config")
            catalog_mod = importlib.import_module("modules.catalog")
            browser_mod = importlib.import_module("modules.browser")
            ai_client_mod = importlib.import_module("modules.ai_client")
            vision_agent_mod = importlib.import_module("modules.vision_agent")

            # 日志转 GUI
            class _GuiLogHandler(logging.Handler):
                def emit(_, record):
                    line = record.getMessage()
                    if not line or len(line) > 600:
                        return
                    self.app.q.put(("up_log", line,
                                    record.levelno >= logging.WARNING))

            handler = _GuiLogHandler()
            root = logging.getLogger()
            root.addHandler(handler)
            old_level = root.level
            root.setLevel(logging.INFO)
            try:
                future = asyncio.run_coroutine_threadsafe(
                    self._do_catalog(kind, video, zone, out_json,
                                     config_mod, catalog_mod, browser_mod,
                                     ai_client_mod, vision_agent_mod),
                    self.app.loop)
                rc = future.result()
            finally:
                root.removeHandler(handler)
                root.setLevel(old_level)
        except Exception as e:  # noqa: BLE001
            self.app.q.put(("up_log", f"[{kind}] 检测异常: {e}", True))
            rc = 1
        self.app.q.put(("catalog_done", kind, rc, out_json))

    async def _do_catalog(self, kind, video, zone, out_json,
                          config_mod, catalog_mod, browser_mod,
                          ai_client_mod, vision_agent_mod):
        """在常驻 loop 中执行具体检测；复用 BrowserManager。"""
        import json
        from pathlib import Path
        mgr = browser_mod.BrowserManager.instance()
        session, page = await mgr.ensure()

        # 准备 AI agent
        agent = None
        if ai_client_mod.is_enabled():
            try:
                agent = vision_agent_mod.VisionAgent(page)
            except Exception as e:  # noqa: BLE001
                import logging
                logging.getLogger(__name__).warning(
                    "AI 屏幕识别初始化失败: %s", e)

        try:
            if kind == "areas":
                areas = await catalog_mod.fetch_areas(
                    video_path=video, session=session, page=page,
                    close_after=False, agent=agent)
                payload = {"kind": "areas", "areas": areas}
            elif kind == "collections":
                cols = await catalog_mod.fetch_collections(
                    video_path=video if (video and Path(video).exists()) else None,
                    session=session, page=page, close_after=False)
                payload = {"kind": "collections", "collections": cols}
            else:  # topics
                steps = [z.strip() for z in (zone or "").split("/") if z.strip()]
                topics = await catalog_mod.fetch_topics_for_zone(
                    steps, video, session=session, page=page,
                    close_after=False, agent=agent)
                payload = {"kind": "topics", "zone": steps, "topics": topics}

            Path(out_json).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8")
            catalog_mod.save_cache(kind, payload, payload.get("zone"))
            return 0
        except Exception as e:  # noqa: BLE001
            import logging
            logging.getLogger(__name__).exception("检测失败: %s", e)
            return 1

    def on_catalog_done(self, kind, rc, out_json):
        """主线程处理检测结果。"""
        self._set_detect_buttons("normal")
        self.up_btn.configure(state="normal" if engine.uploader_env_ready() else "disabled")
        import json
        if rc != 0:
            self.stage_var.set("检测失败")
            self.log.line(f"[错误] {kind} 检测失败（退出码 {rc}），详见日志目录", "err")
            return
        try:
            with open(out_json, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except OSError as e:
            self.log.line(f"[错误] 读取检测结果失败: {e}", "err")
            return
        if kind == "areas":
            self._fill_areas(payload.get("areas", []))
            n = len(self.zone_box.cget("values") or ())
            self.stage_var.set(f"分区检测完成：{n} 个")
            self.log.line(f"[OK] 检测到 {n} 个分区，已缓存", "ok")
        elif kind == "collections":
            cols = payload.get("collections", [])
            self._collections_cache = cols
            self.collection_box.configure(values=cols)
            self.stage_var.set(f"合集检测完成：{len(cols)} 个")
            self.log.line(f"[OK] 检测到 {len(cols)} 个合集，下拉即可选择", "ok")
        else:
            topics = payload.get("topics", [])
            self.topic_lb.delete(0, "end")
            for t in topics:
                self.topic_lb.insert("end", t)
            self.stage_var.set(f"话题检测完成：{len(topics)} 个")
            self.log.line(f"[OK] 检测到 {len(topics)} 个可选话题，双击即可加入", "ok")

    def on_catalog_fail(self, kind, msg):
        self._set_detect_buttons("normal")
        self.up_btn.configure(state="normal" if engine.uploader_env_ready() else "disabled")
        self.stage_var.set("检测失败")
        self.log.line("[错误] " + msg, "err")

    def _add_selected_topics(self):
        """把话题列表中选中的项去重追加到话题输入框。"""
        existing = [t.strip() for t in self.topics_var.get().split(",") if t.strip()]
        have = set(existing)
        for idx in self.topic_lb.curselection():
            t = self.topic_lb.get(idx).strip()
            if t and t not in have:
                existing.append(t)
                have.add(t)
        self.topics_var.set(",".join(existing))

    # ---------- 全局 AI：连通性测试 / 标题语言识别 ----------
    def test_ai(self):
        """后台测试 AI 连通性（文本通道 glm-4.7-flash），结果显示在日志区。"""
        self.log.line("[AI] 正在测试连接（文本模型 + 视觉模型配置）…", "dim")

        def work():
            ok, msg = engine.ai_quick_test()
            self.app.q.put(("up_log",
                            f"[AI] 连接{'成功：' + msg if ok else '失败：' + msg}",
                            not ok))
        threading.Thread(target=work, daemon=True).start()

    def _ai_detect_title_lang(self, title):
        """后台线程：AI 识别标题语言 → 回主线程设置字幕语言并按语言重配字幕文件。"""
        def work():
            code = engine.ai_detect_language(title)
            self.app.q.put(("up_ai_lang", code, title))
        threading.Thread(target=work, daemon=True).start()

    def on_ai_lang(self, code, title):
        """主线程回调：标题语言识别结果落地（字幕语言下拉 + 同目录字幕匹配）。"""
        if title != self.title_var.get().strip():
            return   # 标题已被用户修改，丢弃过期结果
        if not code:
            self.log.line("[AI] 标题语言识别不可用（AI 未启用或网络失败），"
                          "字幕语言保持当前选择", "dim")
            return
        self._title_lang_code = code
        lang = engine.bili_subtitle_lang(code)
        if lang and lang in self.SUBTITLE_LANGS:
            self.subtitle_lang_var.set(lang)
            self.log.line(f"[AI] 标题语言识别为 {code}，"
                          f"字幕语言已自动设为「{lang}」（可手动改）", "ok")
        # 按标题语言重新匹配同目录字幕文件（如标题英文则优先 *.en.srt）
        video = engine.clean_path(self.video_var.get())
        if video and os.path.isfile(video):
            sub = engine.find_subtitle_for_video(video, code)
            if sub and sub != engine.clean_path(self.subtitle_var.get()):
                self.subtitle_var.set(sub)
                self.log.line(f"[AI] 已按标题语言匹配字幕文件: {os.path.basename(sub)}",
                              "ok")

    # ---------- 表单 ----------
    def browse(self):
        init = self.video_var.get() or self.app.dl_tab.dest_var.get() or engine.SCRIPT_DIR
        p = filedialog.askopenfilename(
            initialdir=os.path.dirname(init) if os.path.isfile(init) else init,
            filetypes=[("视频文件", "*.mp4 *.mkv *.avi *.mov *.flv *.wmv *.ts *.m4v *.webm"),
                       ("所有文件", "*.*")])
        if not p:
            return
        self.video_var.set(p)
        info = engine.parse_info_txt(
            os.path.join(os.path.dirname(p), "视频信息.txt"))
        filled = []
        if info.get("title"):
            self.title_var.set(info["title"]); filled.append("标题")
        if info.get("description") or info.get("source_url"):
            self.desc_text.delete("1.0", "end")
            # 按指定格式生成简介：源地址（换行）/ 来源（同行）/ 原简介（换行）
            self.desc_text.insert("1.0", engine.build_posting_description(info))
            filled.append("简介")
        if info.get("tags"):
            self.tags_var.set(",".join(info["tags"])); filled.append("标签")
        if info.get("zone"):
            steps = [z.strip() for z in
                     re.split(r"[/／>》|]", info["zone"]) if z.strip()]
            if steps:
                self.zone_var.set(steps[0])
            filled.append("分区")
        if info.get("declaration"):
            decl = info["declaration"]
            values = list(self.DECLARATIONS)
            if decl not in values:
                values.append(decl)
                self.decl_box.configure(values=values)
            self.decl_box.set(decl); filled.append("创作声明")
        if info.get("topics"):
            self.topics_var.set(",".join(info["topics"])); filled.append("话题")
        # 自动查找同目录原始字幕（.srt，按标题语言优先匹配），供投稿时同步上传
        if not self.subtitle_var.get():
            sub = engine.find_subtitle_for_video(p, self._title_lang_code)
            if sub:
                self.subtitle_var.set(sub)
                filled.append("字幕")
        if filled:
            self.log.line("[预填] 已从 视频信息.txt / 视频目录读入：" + "、".join(filled), "ok")
        else:
            self.log.line("[预填] 该视频目录没有 视频信息.txt，请手动填写", "dim")
        # AI 识别标题语言 → 自动匹配字幕语言与字幕文件（下载的字幕应为标题语言）
        title_now = self.title_var.get().strip()
        if title_now:
            self._ai_detect_title_lang(title_now)

    def browse_subtitle(self):
        init = self.subtitle_var.get() or engine.SCRIPT_DIR
        p = filedialog.askopenfilename(
            initialdir=os.path.dirname(init) if os.path.isfile(init) else init,
            filetypes=[("字幕文件", "*.srt *.ass *.vtt"), ("所有文件", "*.*")])
        if p:
            self.subtitle_var.set(p)

    def _split_csv(self, var):
        return [t.strip() for t in var.get().split(",") if t.strip()]

    def start(self):
        if self.running:
            messagebox.showinfo("提示", "已有投稿任务在进行中，请等待其结束")
            return
        video = engine.clean_path(self.video_var.get())
        if not video or not os.path.isfile(video):
            messagebox.showwarning("提示", "请先选择一个视频文件")
            return
        title = self.title_var.get().strip()
        if not title:
            messagebox.showwarning("提示", "请填写标题")
            return
        if not engine.uploader_env_ready():
            messagebox.showwarning("提示", "投稿引擎不可用（tools\\python 运行时或 tools\\ms-playwright 内核缺失）")
            return
        desc = self.desc_text.get("1.0", "end-1c").strip()
        zone_steps = self._current_zone_steps()
        decl = "" if self.decl_box.current() == 0 else self.decl_box.get()
        # 原始字幕：手动指定优先，未指定时自动从视频同目录按标题语言查找
        subtitle = engine.clean_path(self.subtitle_var.get())
        if not subtitle:
            subtitle = engine.find_subtitle_for_video(video, self._title_lang_code)
        job = {
            "video_path": video,
            "title": title,
            "description": desc,
            "tags": self._split_csv(self.tags_var),
            "zone": zone_steps[0] if zone_steps else "",
            "declaration": decl,
            "topics": self._split_csv(self.topics_var),
            "collection": self.collection_var.get().strip(),
            "subtitle": subtitle,
            "subtitle_lang": self.subtitle_lang_var.get().strip() or "英语",
            "use_recommended": True,
            "auto_select_cover": self.cover_var.get(),
            "submit": not self.preview_var.get(),
        }
        if not job["tags"]:
            messagebox.showwarning("提示", "请至少填写一个标签")
            return
        if not job["zone"]:
            messagebox.showwarning(
                "提示", "请填写分区名（投稿时先上传视频、再现场检测分区列表自动匹配；"
                        "也可点「检测/刷新分区列表」核对名称）")
            return
        try:
            task_json = engine.write_uploader_task(job)
        except OSError as e:
            messagebox.showerror("生成任务文件失败", str(e))
            return

        self.running = True
        self.up_btn.configure(state="disabled")
        mode = "预览（不提交）" if job["submit"] is False else "正式提交"
        self.stage_var.set(f"准备中（{mode}）")
        self.log.line(f"[投稿] {mode} | 视频: {os.path.basename(video)}", "dim")
        self.log.line(f"[投稿] 标题: {title}", "dim")
        if job.get("collection"):
            self.log.line(f"[投稿] 加入合集: {job['collection']}", "dim")
        if job.get("subtitle"):
            self.log.line(f"[投稿] 同步上传字幕: {os.path.basename(job['subtitle'])}"
                          f"（语言: {job.get('subtitle_lang') or '英语'}）", "dim")
        self.log.line("[投稿] 任务文件: " + task_json, "dim")
        if job["submit"]:
            if not messagebox.askyesno(
                    "确认正式投稿",
                    "即将在 B 站正式投稿（自动点击「立即投稿」）。\n\n"
                    f"标题：{title}\n\n确定继续？"):
                self.running = False
                self.up_btn.configure(state="normal")
                self.log.line("[投稿] 已取消", "dim")
                return
        threading.Thread(target=self._run_uploader, args=(task_json,),
                         daemon=True).start()

    def _run_uploader(self, task_json):
        """主进程内常驻 asyncio 循环：所有检测 / 投稿共享同一个浏览器会话。"""
        # 投稿任务：直接走常驻 loop 即可（不重启浏览器）
        self.app.loop.run_in_executor(
            None, self._submit_in_loop, task_json)

    def _submit_in_loop(self, task_json):
        """在后台 asyncio loop 中执行投稿；统一日志经 self.app.q 回主线程。"""
        import asyncio
        import importlib
        if engine.UPLOADER_SRC_DIR not in sys.path:
            sys.path.insert(0, engine.UPLOADER_SRC_DIR)
        up_config = importlib.import_module("config")
        runner = importlib.import_module("uploader_runner")

        def on_stage(_key, label):
            self.app.q.put(("up_stage", label))

        handler_installed = False
        try:
            up_config.load_task_file(task_json)
            root = logging.getLogger()

            class _GuiLogHandler(logging.Handler):
                def emit(_, record):
                    line = record.getMessage()
                    self.app.q.put(("up_log", line,
                                    record.levelno >= logging.WARNING))

            handler = _GuiLogHandler()
            root.addHandler(handler)
            old_level = root.level
            root.setLevel(logging.INFO)
            handler_installed = True
            try:
                future = asyncio.run_coroutine_threadsafe(
                    runner.run(on_stage=on_stage,
                               use_browser_manager=True),
                    self.app.loop)
                rc = future.result()
            finally:
                root.removeHandler(handler)
                root.setLevel(old_level)
        except Exception as e:  # noqa: BLE001
            self.app.q.put(("up_log", f"[投稿] 引擎调用失败: {e}", True))
            rc = 1
        self.app.q.put(("up_done", rc, task_json))

    def _run_subprocess(self, task_json):
        """后备：子进程运行 uploader_runner.py，逐行回传日志；关键词命中时更新阶段"""
        try:
            proc = engine.popen_process(
                [engine.system_python(), engine.UPLOADER_RUNNER,
                 "--task", task_json],
                cwd=engine.UPLOADER_SRC_DIR,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1)
        except Exception as e:
            self.app.q.put(("up_done", 1, f"无法启动投稿引擎: {e}"))
            return
        for line in proc.stdout:
            line = line.rstrip()
            if not line or len(line) > 400:
                continue
            err = "| ERROR " in line or "| WARNING " in line
            self.app.q.put(("up_log", line, err))
            for kw, label in self.STAGE_HINTS:
                if kw in line:
                    self.app.q.put(("up_stage", label))
                    break
        rc = proc.wait()
        self.app.q.put(("up_done", rc, task_json))

    # ---------- 主线程 UI 更新（经消息队列） ----------
    def on_log(self, text, err):
        self.log.line(text, "err" if err else "dim")

    def on_stage(self, label):
        self.stage_var.set(label)
        self.app.status_var.set(f"投稿：{label}")

    def on_done(self, rc, info):
        self.running = False
        self.up_btn.configure(state="normal")
        if rc == 0:
            self.stage_var.set("投稿流程结束")
            self.app.status_var.set("投稿流程结束")
            self.log.line("[OK] 投稿流程执行完成，请在浏览器/投稿管理中核对结果", "ok")
        elif rc == 2:
            self.stage_var.set("失败：视频不存在")
            self.log.line("[错误] 视频文件不存在，请检查路径", "err")
        else:
            self.stage_var.set("投稿失败")
            self.log.line(f"[错误] 投稿流程失败（退出码 {rc}）。"
                          f"详情与失败截图见 {engine.UPLOADER_LOGS_DIR}\\screenshots", "err")


class MergeTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=(PAD_X, PAD_T, PAD_X, PAD_X))
        self.app = app
        self.pairs = []

        ttk.Label(self, text="音视频智能合并", style="Title.TLabel").pack(anchor="w")
        ttk.Label(self, text="自动配对 mp4 + m4a/weba + srt/ass；m4a 直封，weba 转 AAC",
                  style="Muted.TLabel").pack(anchor="w", pady=(2, GAP + 4))

        for label, attr, default in (
            ("输入文件夹", "in_var", engine.DEFAULT_INPUT_DIR),
            ("输出文件夹", "out_var", ""),
        ):
            ttk.Label(self, text=label, style="Head.TLabel").pack(anchor="w")
            row = ttk.Frame(self)
            row.pack(fill="x", pady=(4, GAP))
            var = tk.StringVar(value=default)
            setattr(self, attr, var)
            ent = ttk.Entry(row, textvariable=var)
            ent.pack(side="left", fill="x", expand=True)
            setattr(self, attr + "_undo", attach_entry_undo(ent, var))
            ttk.Button(row, text="浏览…",
                       command=lambda v=var: self.browse(v)).pack(side="left", padx=(8, 0))

        opt = ttk.Frame(self)
        opt.pack(fill="x", pady=(0, GAP))
        ttk.Label(opt, text="ASS 字幕:", style="Head.TLabel").pack(side="left")
        self.ass_var = tk.StringVar(value="烧录为硬字幕")
        ttk.Combobox(opt, textvariable=self.ass_var, state="readonly", width=14,
                     values=["烧录为硬字幕", "封装为 MKV", "忽略"]).pack(side="left", padx=(8, 16))
        self.force_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt, text="同名但时长不一致也强制合成",
                        variable=self.force_var).pack(side="left")
        self.scan_btn = ttk.Button(opt, text="扫描配对", command=self.scan)
        self.scan_btn.pack(side="right")

        cols = ("video", "audio", "sub", "match", "diff")
        heads = ("视频", "音频", "字幕", "匹配", "时长差")
        widths = (220, 220, 140, 80, 70)
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=6)
        for c, h, w in zip(cols, heads, widths):
            self.tree.heading(c, text=h)
            self.tree.column(c, width=w, anchor="w")
        self.tree.pack(fill="both", expand=True)

        row3 = ttk.Frame(self)
        row3.pack(fill="x", pady=(GAP, 4))
        self.prog = ttk.Progressbar(row3, mode="determinate", maximum=100)
        self.prog.pack(side="left", fill="x", expand=True)
        self.merge_btn = ttk.Button(row3, text="开始合成", style="Accent.TButton",
                                    command=self.start_merge)
        self.merge_btn.pack(side="right")

        self.log = LogBox(self, height=6)
        self.log.widget.pack(fill="both", expand=True, pady=(4, 0))

    def browse(self, var):
        d = filedialog.askdirectory(initialdir=var.get() or engine.SCRIPT_DIR)
        if d:
            var.set(d)

    def set_busy(self, busy):
        for b in (self.scan_btn, self.merge_btn):
            b.configure(state="disabled" if busy else "normal")

    def scan(self):
        in_dir = engine.clean_path(self.in_var.get())
        if not os.path.isdir(in_dir):
            messagebox.showwarning("提示", "输入文件夹不存在")
            return
        self.set_busy(True)
        self.log.line(f"[信息] 正在扫描: {in_dir}", "dim")
        threading.Thread(target=self._scan_worker, args=(in_dir,), daemon=True).start()

    def _scan_worker(self, in_dir):
        try:
            _, ffprobe = engine.ensure_ffmpeg()
            mp4s, m4as, webas, srts, asss = engine.scan_media(in_dir)
            pairs, rem_mp4, rem_m4a, rem_weba = engine.smart_pair(
                mp4s, m4as, webas, srts, asss, ffprobe)
            self.app.q.put(("scan_done", pairs, (rem_mp4, rem_m4a, rem_weba),
                            (len(mp4s), len(m4as), len(webas), len(srts), len(asss)), None))
        except Exception as e:
            self.app.q.put(("scan_done", None, None, None, str(e)))

    def on_scan_done(self, pairs, remaining, counts, err):
        self.set_busy(False)
        if err:
            self.log.line(f"[错误] 扫描失败: {err}", "err")
            return
        self.pairs = pairs or []
        self.tree.delete(*self.tree.get_children())
        name = {"perfect": "完美", "duration": "时长", "name_only": "仅同名"}
        for p in self.pairs:
            mp4, audio, at, mt, diff, sub, st = p
            self.tree.insert("", "end", values=(
                os.path.basename(mp4), os.path.basename(audio),
                os.path.basename(sub) if sub else "—",
                name.get(mt, mt), f"{diff:.2f}s"))
        n_mp4, n_m4a, n_weba, n_srt, n_ass = counts
        self.log.line(f"[OK] 找到 {n_mp4} 个 mp4 / {n_m4a} 个 m4a / {n_weba} 个 weba / "
                      f"{n_srt} 个 srt / {n_ass} 个 ass，配对 {len(self.pairs)} 对", "ok")
        rem_mp4, rem_m4a, rem_weba = remaining
        if rem_mp4:
            self.log.line(f"[未匹配视频] {len(rem_mp4)} 个：" +
                          "、".join(os.path.basename(f) for f in rem_mp4), "dim")
        if rem_m4a or rem_weba:
            self.log.line(f"[未匹配音频] {len(rem_m4a) + len(rem_weba)} 个", "dim")

    def start_merge(self):
        if not self.pairs:
            messagebox.showwarning("提示", "请先「扫描配对」")
            return
        in_dir = engine.clean_path(self.in_var.get())
        out_dir = engine.clean_path(self.out_var.get()) or os.path.join(in_dir, "合成结果")
        os.makedirs(out_dir, exist_ok=True)
        ass_map = {"烧录为硬字幕": "burn", "封装为 MKV": "mkv", "忽略": "ignore"}
        ass_mode = ass_map.get(self.ass_var.get(), "burn")
        to_merge = [p for p in self.pairs
                    if p[3] in ("perfect", "duration") or self.force_var.get()]
        if not to_merge:
            messagebox.showwarning("提示", "没有可合成的配对（可勾选强制合成）")
            return
        self.set_busy(True)
        self.prog["value"] = 0
        threading.Thread(target=self._merge_worker,
                         args=(to_merge, out_dir, ass_mode), daemon=True).start()

    def _merge_worker(self, to_merge, out_dir, ass_mode):
        ok_n = fail_n = 0
        try:
            ffmpeg_path, _ = engine.ensure_ffmpeg()
            total = len(to_merge)
            for idx, p in enumerate(to_merge, 1):
                mp4, audio, at, mt, diff, sub, st = p
                if st == "ass" and ass_mode == "ignore":
                    sub, st = None, None
                base = engine.get_base_name(mp4)
                out_path = os.path.join(out_dir, f"{base}_merged.mp4")
                counter, orig = 1, out_path
                while os.path.exists(out_path):
                    name, ext = os.path.splitext(orig)
                    out_path = f"{name}_{counter}{ext}"
                    counter += 1
                self.app.q.put(("mg_log", f"[{idx}/{total}] {base}"))
                ok, final_out = engine.merge_pair(mp4, audio, at, sub, st,
                                                  out_path, ffmpeg_path, ass_mode)
                if ok and os.path.exists(final_out):
                    ok_n += 1
                    self.app.q.put(("mg_log", f"     [OK] {engine.format_size(os.path.getsize(final_out))}"))
                else:
                    fail_n += 1
                    self.app.q.put(("mg_log", "     [X] 失败"))
                self.app.q.put(("mg_progress", idx / total * 100))
            self.app.q.put(("mg_done", ok_n, fail_n, out_dir))
        except Exception as e:
            self.app.q.put(("mg_done", ok_n, fail_n, f"出错: {e}"))

    def on_mg_done(self, ok_n, fail_n, out_dir):
        self.set_busy(False)
        self.prog["value"] = 100
        self.log.line(f"[完成] 成功 {ok_n} / 失败 {fail_n} → {out_dir}",
                      "ok" if fail_n == 0 else "err")
        if fail_n == 0:
            engine.open_folder(out_dir)


class LibraryTab(ttk.Frame):
    """视频库：自动加载 + 缩略图卡片（参考当前项目视频工作室实现）"""
    CARD_W = 216
    THUMB_W = 190
    THUMB_H = 115

    def __init__(self, parent, app):
        super().__init__(parent, padding=(PAD_X, PAD_T, PAD_X, PAD_X))
        self.app = app
        self.cards = {}          # path -> card 控件字典
        self.videos = []         # 扫描结果
        self.photos = {}         # path -> PhotoImage（防 GC）
        self._busy = False

        ttk.Label(self, text="视频库", style="Title.TLabel").pack(anchor="w")
        ttk.Label(self, text="打开软件自动加载；缩略图自动生成并缓存；单击卡片播放，右键打开所在文件夹",
                  style="Muted.TLabel").pack(anchor="w", pady=(2, GAP + 4))

        row = ttk.Frame(self)
        row.pack(fill="x", pady=(4, GAP))
        self.dir_var = tk.StringVar(value=engine.get_saved_download_dir())
        dir_entry = ttk.Entry(row, textvariable=self.dir_var)
        dir_entry.pack(side="left", fill="x", expand=True)
        self.dir_undo = attach_entry_undo(dir_entry, self.dir_var)
        ttk.Button(row, text="浏览…", command=self.browse).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="同步下载目录", command=self.sync_download_dir).pack(side="left", padx=(8, 0))
        self.refresh_btn = ttk.Button(row, text="刷新", command=self.refresh)
        self.refresh_btn.pack(side="left", padx=(8, 0))
        ttk.Button(row, text="打开文件夹", command=self.open_dir).pack(side="left", padx=(8, 0))

        self.count_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.count_var, style="Muted.TLabel").pack(anchor="w")

        area = ttk.Frame(self)
        area.pack(fill="both", expand=True, pady=(4, 0))
        self.canvas = tk.Canvas(area, bg=BG, highlightthickness=0)
        vsb = ttk.Scrollbar(area, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = ttk.Frame(self.canvas)
        self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>",
                        lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self._reflow())

        self.empty_var = tk.StringVar(value="")
        self.empty_label = ttk.Label(self.inner, textvariable=self.empty_var, style="Muted.TLabel")

    # ---------- 操作 ----------
    def browse(self):
        d = filedialog.askdirectory(initialdir=self.dir_var.get() or engine.SCRIPT_DIR)
        if d:
            self.dir_var.set(d)
            self.refresh()

    def sync_download_dir(self):
        self.dir_var.set(self.app.dl_tab.dest_var.get())
        self.status_var_set("已同步下载目录，正在刷新…")
        self.refresh()

    def open_dir(self):
        d = engine.clean_path(self.dir_var.get())
        if os.path.isdir(d):
            engine.open_folder(d)

    def status_var_set(self, text):
        try:
            self.app.status_var.set(text)
        except Exception:
            pass

    def auto_load(self):
        """启动时自动加载默认视频库（若文件夹存在）"""
        if os.path.isdir(engine.clean_path(self.dir_var.get())):
            self.refresh()

    def refresh(self):
        if self._busy:
            return
        folder = engine.clean_path(self.dir_var.get())
        if not os.path.isdir(folder):
            messagebox.showwarning("提示", "视频库文件夹不存在，请先选择一个有效文件夹")
            return
        self._busy = True
        self.refresh_btn.configure(state="disabled")
        self.empty_var.set("")
        self.count_var.set("正在扫描视频 …")
        self.status_var_set("正在扫描视频库 …")
        threading.Thread(target=self._scan_worker, args=(folder,), daemon=True).start()

    # ---------- 后台线程 ----------
    def _scan_worker(self, folder):
        try:
            _, ffprobe = engine.ensure_ffmpeg()
            # 每个视频都在自己的子文件夹里，因此递归扫描（含顶层）
            paths = []
            for root, dirs, files in os.walk(folder):
                dirs[:] = [d for d in dirs
                           if not d.startswith(".") and d != "thumb_cache"]
                for n in files:
                    if os.path.splitext(n)[1].lower() in LIB_EXTS:
                        paths.append(os.path.join(root, n))
            paths.sort(key=lambda p: os.path.basename(p).lower())
            videos = []
            for p in paths:
                try:
                    size = os.path.getsize(p)
                except OSError:
                    size = 0
                dur = engine.get_duration(p, ffprobe)
                # 卡片名：子文件夹内的视频显示「文件夹名 / 文件名」，便于区分
                rel = os.path.relpath(p, folder)
                name = rel if os.path.dirname(rel) else os.path.basename(p)
                videos.append({
                    "path": p, "name": name, "size": size, "dur": dur,
                    "thumb": os.path.join(THUMB_DIR, thumb_cache_name(p)),
                })
            self.app.q.put(("lib_scan_done", videos, None))
        except Exception as e:
            self.app.q.put(("lib_scan_done", None, str(e)))

    def _thumb_worker(self, videos):
        try:
            ffmpeg, _ = engine.ensure_ffmpeg()
        except Exception as e:
            self.app.q.put(("lib_log", f"[缩略图] ffmpeg 不可用：{e}"))
            return
        os.makedirs(THUMB_DIR, exist_ok=True)
        for v in videos:
            thumb = v["thumb"]
            if os.path.isfile(thumb):
                continue
            seek = 5 if (v["dur"] or 0) >= 12 else 0
            ok = self._extract_frame(ffmpeg, v["path"], thumb, seek)
            if not ok and seek:
                ok = self._extract_frame(ffmpeg, v["path"], thumb, 0)
            if ok and os.path.isfile(thumb):
                self.app.q.put(("lib_thumb", v["path"], thumb))
            else:
                self.app.q.put(("lib_thumb_fail", v["path"]))

    @staticmethod
    def _extract_frame(ffmpeg, video, thumb, seek):
        cmd = [ffmpeg, "-y"]
        if seek:
            cmd += ["-ss", str(seek)]
        cmd += ["-i", video, "-frames:v", "1",
                "-vf", f"scale={LibraryTab.THUMB_W}:-2", thumb]
        try:
            r = engine.run_process(cmd, capture_output=True, timeout=120)
            return r.returncode == 0
        except Exception:
            return False

    # ---------- UI 更新（主线程，经消息队列） ----------
    def on_scan_done(self, videos, err):
        self._busy = False
        self.refresh_btn.configure(state="normal")
        self._clear_cards()
        if err:
            self.count_var.set("")
            self.empty_var.set(f"扫描失败：{err}")
            self.status_var_set("视频库扫描失败")
            return
        self.videos = videos or []
        if not self.videos:
            self.count_var.set("共 0 个视频")
            self.empty_var.set("该文件夹下没有找到视频文件")
            self.status_var_set("视频库为空")
            return
        total = sum(v["size"] for v in self.videos)
        self.count_var.set(f"共 {len(self.videos)} 个视频 · {engine.format_size(total)}")
        for v in self.videos:
            self._make_card(v)
        self._reflow()
        self.status_var_set(f"视频库：{len(self.videos)} 个视频")
        missing = [v for v in self.videos if not os.path.isfile(v["thumb"])]
        if missing:
            threading.Thread(target=self._thumb_worker, args=(missing,), daemon=True).start()
        self.canvas.yview_moveto(0)

    def on_thumb(self, path, thumb_path):
        card = self.cards.get(path)
        if not card:
            return
        try:
            photo = tk.PhotoImage(file=thumb_path)
        except tk.TclError:
            card["canvas"].itemconfigure("placeholder", text="缩略图损坏")
            return
        self.photos[path] = photo
        cv = card["canvas"]
        cv.delete("placeholder")
        if card.get("img_id"):
            cv.delete(card["img_id"])
        card["img_id"] = cv.create_image(self.THUMB_W // 2, self.THUMB_H // 2, image=photo)

    def on_thumb_fail(self, path):
        card = self.cards.get(path)
        if card:
            card["canvas"].itemconfigure("placeholder", text="缩略图生成失败")

    def on_log(self, text):
        self.status_var_set(text)

    # ---------- 卡片 ----------
    def _clear_cards(self):
        for c in self.cards.values():
            c["frame"].destroy()
        self.cards.clear()
        self.photos.clear()
        self.empty_var.set("")

    def _make_card(self, v):
        path = v["path"]
        frame = tk.Frame(self.inner, bg=SURFACE, bd=1, relief="solid", cursor="hand2")
        cv = tk.Canvas(frame, width=self.THUMB_W, height=self.THUMB_H,
                       bg="#E7E2D6", highlightthickness=0)
        cv.pack(padx=10, pady=(10, 6))
        name_lbl = tk.Label(frame, text=v["name"], bg=SURFACE, fg=INK,
                            font=F_SMALL, wraplength=self.THUMB_W, anchor="w", justify="left")
        name_lbl.pack(fill="x", padx=12)
        info = f"{engine.format_size(v['size'])} · {fmt_hms(v['dur'])}"
        info_lbl = tk.Label(frame, text=info, bg=SURFACE, fg=MUTED, font=F_SMALL, anchor="w")
        info_lbl.pack(fill="x", padx=12, pady=(2, 10))

        if os.path.isfile(v["thumb"]):
            try:
                photo = tk.PhotoImage(file=v["thumb"])
                self.photos[path] = photo
                card_img = cv.create_image(self.THUMB_W // 2, self.THUMB_H // 2, image=photo)
            except tk.TclError:
                card_img = None
                cv.create_text(self.THUMB_W // 2, self.THUMB_H // 2, text="缩略图损坏",
                               fill=MUTED, tags="placeholder")
        else:
            card_img = None
            cv.create_text(self.THUMB_W // 2, self.THUMB_H // 2, text="正在生成缩略图 …",
                           fill=MUTED, tags="placeholder")

        card = {"frame": frame, "canvas": cv, "img_id": card_img}
        self.cards[path] = card

        def play(e=None, p=path):
            self._play(p)

        def locate(e=None, p=path):
            engine.open_folder(os.path.dirname(p))

        for w in (frame, cv, name_lbl, info_lbl):
            w.bind("<Button-1>", play)
            w.bind("<Button-3>", locate)
            w.bind("<Enter>", lambda e, f=frame: f.configure(relief="raised", bd=2))
            w.bind("<Leave>", lambda e, f=frame: f.configure(relief="solid", bd=1))

    def _reflow(self):
        if not self.cards:
            self.empty_label.grid(row=0, column=0, padx=8, pady=24, sticky="w")
            return
        self.empty_label.grid_remove()
        try:
            width = self.canvas.winfo_width()
        except tk.TclError:
            width = 800
        cols = max(1, (width - 12) // (self.CARD_W + 10))
        for i, v in enumerate(self.videos):
            card = self.cards.get(v["path"])
            if card:
                card["frame"].grid(row=i // cols, column=i % cols,
                                   padx=6, pady=6, sticky="n")

    def _play(self, path):
        try:
            os.startfile(path)
            self.status_var_set(f"正在播放：{os.path.basename(path)}")
        except Exception as e:
            messagebox.showerror("播放失败", str(e))


class App(tk.Tk):
    def __init__(self, argv):
        super().__init__()
        self.title("视频工具箱 v1.9.1")
        self.geometry("980x760")
        self.minsize(860, 640)
        self.configure(bg=BG)
        setup_style(self)

        self.q = queue.Queue()

        # 常驻 asyncio 事件循环（独立后台线程），所有检测 / 投稿都通过它
        # 调用 BrowserManager 共用同一个浏览器窗口与登录态，避免每次检测
        # 关闭并重启浏览器
        self.loop = None
        self._loop_thread = None
        self._start_async_loop()

        ttk.Label(self, text="视频工具箱", style="Title.TLabel").pack(
            anchor="w", padx=PAD_X, pady=(14, 0))
        ttk.Label(self, text="并行下载 ・ 独立打包 ・ 自动视频库 ・ 音视频合并 ・ 本地字幕生成 ・ B站自动投稿",
                  style="Muted.TLabel").pack(
            anchor="w", padx=PAD_X, pady=(0, 6))
        ttk.Separator(self).pack(fill="x", padx=PAD_X)

        status = ttk.Frame(self)
        status.pack(side="bottom", fill="x")
        ttk.Separator(status).pack(fill="x", padx=PAD_X)
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(status, textvariable=self.status_var, style="Muted.TLabel").pack(
            anchor="w", padx=PAD_X, pady=(4, 8))

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=0, pady=(6, 0))
        self.page_host = {}   # 标签页 attr → ScrollFrame 宿主（nb.select 用）

        def add_page(tab_cls, text, attr):
            """每个页面装进可滚动容器：窗口高度不足时自动出现滚动条+滚轮；
            页面实例仍挂到 self.<attr>，供 _pump/跨页联动的既有引用使用。
            page_host 记录 页面→滚动宿主 映射（nb.select 需要选宿主页面）"""
            host = ScrollFrame(self.nb)
            page = tab_cls(host.inner, self)
            page.pack(fill="both", expand=True)
            host.bind_wheel()
            self.nb.add(host, text=text)
            setattr(self, attr, page)
            self.page_host[attr] = host

        add_page(DownloadTab, "  视频下载  ", "dl_tab")
        add_page(LibraryTab, "  视频库  ", "lib_tab")
        add_page(MergeTab, "  音视频合并  ", "mg_tab")
        add_page(SubtitleTab, "  字幕生成  ", "sub_tab")
        add_page(UploadTab, "  B站投稿  ", "up_tab")

        self._apply_argv(argv)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(120, self._pump)

    def _on_close(self):
        self.dl_tab._drop_info_json()
        # 停止常驻浏览器
        try:
            if self.loop is not None and not self.loop.is_closed():
                async def _stop():
                    try:
                        import sys as _s
                        if engine.UPLOADER_SRC_DIR not in _s.path:
                            _s.path.insert(0, engine.UPLOADER_SRC_DIR)
                        from modules.browser import BrowserManager  # type: ignore
                        await BrowserManager.instance().stop()
                    except Exception:
                        pass
                fut = asyncio.run_coroutine_threadsafe(_stop(), self.loop)
                fut.result(timeout=3.0)
        except Exception:
            pass
        self.destroy()

    def _start_async_loop(self):
        """启动后台线程中的常驻 asyncio 事件循环。"""
        import asyncio
        import threading
        self.loop = asyncio.new_event_loop()

        def _run():
            asyncio.set_event_loop(self.loop)
            try:
                self.loop.run_forever()
            finally:
                self.loop.close()

        self._loop_thread = threading.Thread(
            target=_run, daemon=True, name="vt-async-loop")
        self._loop_thread.start()

    def _apply_argv(self, argv):
        """拖文件/链接到 exe：文件夹 → 合并页；链接/文件 → 下载页"""
        if not argv:
            return
        arg = engine.clean_path(argv[0])
        if os.path.isdir(arg):
            self.mg_tab.in_var.set(arg)
            self.mg_tab.out_var.set(os.path.join(arg, "合成结果"))
        else:
            url = engine.extract_url(arg)
            if url:
                self.dl_tab.url_var.set(url)

    def _pump(self):
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == "detect_done":
                    self.dl_tab.on_detect_done(*msg[1:])
                elif kind == "sys_log":
                    self.dl_tab.log.line(msg[1], "dim")
                elif kind == "dl_progress":
                    self.dl_tab.on_dl_progress(msg[1], msg[2])
                    n = self.dl_tab.active_count()
                    self.status_var.set(f"并行下载中：{n} 个任务" if n else "就绪")
                elif kind == "dl_log":
                    self.dl_tab.on_dl_log(msg[1], msg[2])
                elif kind == "dl_done":
                    self.dl_tab.on_dl_done(msg[1], msg[2], msg[3])
                    n = self.dl_tab.active_count()
                    self.status_var.set(f"并行下载中：{n} 个任务" if n else "下载任务已结束")
                elif kind == "lib_scan_done":
                    self.lib_tab.on_scan_done(msg[1], msg[2])
                elif kind == "lib_thumb":
                    self.lib_tab.on_thumb(msg[1], msg[2])
                elif kind == "lib_thumb_fail":
                    self.lib_tab.on_thumb_fail(msg[1])
                elif kind == "lib_log":
                    self.lib_tab.on_log(msg[1])
                elif kind == "scan_done":
                    self.mg_tab.on_scan_done(*msg[1:])
                elif kind == "mg_log":
                    self.mg_tab.log.line(msg[1], "dim")
                elif kind == "mg_progress":
                    self.mg_tab.prog["value"] = msg[1]
                    self.status_var.set(f"合成中 {msg[1]:.0f}%")
                elif kind == "mg_done":
                    self.mg_tab.on_mg_done(msg[1], msg[2], msg[3])
                    self.status_var.set("合成完成")
                elif kind == "asr_progress":
                    self.sub_tab.on_progress(msg[1], msg[2])
                elif kind == "asr_log":
                    self.sub_tab.on_log(msg[1], msg[2])
                elif kind == "asr_status":
                    self.sub_tab.on_status(msg[1], msg[2], msg[3])
                elif kind == "asr_done":
                    self.sub_tab.on_done(msg[1], msg[2], msg[3])
                elif kind == "asr_queue_done":
                    self.sub_tab.on_queue_done()
                    self.status_var.set("字幕生成结束")
                elif kind == "up_log":
                    self.up_tab.on_log(msg[1], msg[2])
                elif kind == "up_stage":
                    self.up_tab.on_stage(msg[1])
                elif kind == "up_done":
                    self.up_tab.on_done(msg[1], msg[2])
                elif kind == "catalog_done":
                    self.up_tab.on_catalog_done(msg[1], msg[2], msg[3])
                elif kind == "catalog_fail":
                    self.up_tab.on_catalog_fail(msg[1], msg[2])
                elif kind == "up_ai_lang":
                    self.up_tab.on_ai_lang(msg[1], msg[2])
        except queue.Empty:
            pass
        self.after(120, self._pump)


def main():
    argv = sys.argv[1:]
    app = App(argv)
    if os.environ.get("VT_SHOT_TAB") == "upload":
        def _shot_demo():
            app.nb.select(app.page_host["up_tab"])
            demo = ["游戏", "动画", "生活", "科技", "音乐", "鬼畜", "知识"]
            app.up_tab._fill_areas([{"name": n} for n in demo])
            app.up_tab.zone_var.set("游戏")
            app.up_tab.collection_box.configure(values=["我的游戏合集", "日常vlog"])
            for t in ("2026热门游戏", "电竞名场面", "游戏剪辑"):
                app.up_tab.topic_lb.insert("end", t)
        app.after(900, _shot_demo)
    if os.environ.get("VT_GUI_SELFTEST"):
        def _ok():
            try:
                with open(os.path.join(engine.DATA_DIR, "GUI_SELFTEST_OK"), "w") as f:
                    f.write("ok:" + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            except Exception:
                pass
            app.destroy()
        app.after(2600, _ok)
    app.mainloop()


if __name__ == "__main__":
    main()
