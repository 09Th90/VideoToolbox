# -*- coding: utf-8 -*-
"""v1.7 安装结果结构校验（安装目录由命令行参数传入，必须在工作区内）"""
import os, sys

app = sys.argv[1]
problems = []

def must(cond, msg):
    print(("  OK " if cond else "  FAIL ") + msg)
    if not cond:
        problems.append(msg)

print("== 安装顶层结构 ==")
top = sorted(os.listdir(app))
print("  顶层:", top)
expect_top = {"视频工具箱.exe", "tools", "src", "docs", "data", "logs",
              "unins000.exe", "unins000.dat"}
must(set(top) <= expect_top, "顶层只含主程序/功能目录/卸载器，无散落源码")
must(os.path.isfile(os.path.join(app, "视频工具箱.exe")), "主程序在顶层")

print("== src 目录 ==")
src = set(os.listdir(os.path.join(app, "src")))
must({"video_toolbox.py", "video_toolbox_gui.py", "asr_subtitle_worker.py",
      "视频工具箱.bat"} <= src, f"src 含源码与启动器: {sorted(src)}")

print("== docs 目录 ==")
docs = set(os.listdir(os.path.join(app, "docs")))
must({"使用说明.txt", "界面预览.png"} <= docs, f"docs 含文档: {sorted(docs)}")

print("== tools 运行时 ==")
tools = os.listdir(os.path.join(app, "tools"))
for f in ("ffmpeg.exe", "ffprobe.exe", "yt-dlp.exe", "python", "ms-playwright",
          "uploader_src", "asr_model"):
    must(os.path.exists(os.path.join(app, "tools", f)), f"tools/{f} 存在")
must("uploader_profile" not in tools and "uploader_logs" not in tools
     and "uploader_tasks" not in tools, "tools 下无用户数据旧目录")

print("== data/logs 空壳 ==")
for d in ("data/downloads", "data/thumb_cache", "data/uploader_profile",
          "data/uploader_tasks", "data/catalog", "logs/uploader/screenshots",
          "tools/asr_model"):
    p = os.path.join(app, d.replace("/", os.sep))
    must(os.path.isdir(p), f"空壳目录 {d}")
    if os.path.isdir(p):
        must(len(os.listdir(p)) == 0, f"{d} 为空（无用户数据泄漏）")

print("== 排除项全盘扫描 ==")
bad_pyc, bad_cache, bad_model = [], [], []
for root, dirs, files in os.walk(app):
    for f in files:
        if f.endswith(".pyc"):
            bad_pyc.append(os.path.join(root, f))
        if f.endswith((".bin", ".safetensors")) and "asr_model" in root:
            bad_model.append(os.path.join(root, f))
    for d in dirs:
        if d == "__pycache__":
            bad_cache.append(os.path.join(root, d))
must(not bad_pyc, f"无 .pyc（{len(bad_pyc)}）")
must(not bad_cache, f"无 __pycache__（{len(bad_cache)}）")
must(not bad_model, f"asr_model 无模型文件（{len(bad_model)}）")

print("== 新功能文件就位 ==")
must(os.path.isfile(os.path.join(app, "tools", "uploader_src", "modules", "catalog.py")),
     "投稿引擎含分区/话题检测模块 catalog.py")

print("== 文件计数与体积 ==")
total, size = 0, 0
for root, _, files in os.walk(app):
    for f in files:
        total += 1
        size += os.path.getsize(os.path.join(root, f))
print(f"  文件数 {total}，总体积 {size/1024/1024:.1f} MiB")

print()
if problems:
    print("VERIFY_FAILED:", *problems, sep="\n - ")
    sys.exit(1)
print("VERIFY_ALL_PASSED")
