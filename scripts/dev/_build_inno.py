# -*- coding: utf-8 -*-
# @version 2.7.0
"""ASCII 路径驱动 Inno Setup 编译离线安装包（2026-10-21 收编进仓库）。

原驱动为仓库外脚本 ``C:\\bld\\_build_iss_now2.py``；ISCC 与构建链位于 C 盘
（``C:\\bld``），2026-10-25 自 D 盘回退。

用法::

    C:\\bld\\qt_build\\Scripts\\python.exe scripts\\dev\\_build_inno.py

注意：cwd 留在仓库根。iss 内相对 Source 路径 ``..\\src\\...`` 相对 **iss 所在
目录**解析（不受 cwd 影响），OutputDir 等相对路径以 cwd 为准。ISCC 本身对
中文路径无碍（PyInstaller 的 Qt 钩子才怕中文，故 onefile 打包走 junction）。
"""
import os
import subprocess
import time

#: 构建环境（C 盘，2026-10-25 自 D 盘回退）
BLD = r"C:\bld"

ISCC = os.path.join(BLD, "is6", "ISCC.exe")
#: 仓库根 = 本脚本所在 scripts/dev/ 的上两级（跟仓库走，不写死中文绝对路径）
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ISS = os.path.join(ROOT, "packaging", "视频工具箱.iss")

if not os.path.isfile(ISCC):
    print("!! 找不到 ISCC：", ISCC)
    raise SystemExit(2)
if not os.path.isfile(ISS):
    print("!! 找不到 iss：", ISS)
    raise SystemExit(2)

# 前置校验：待打包的主程序必须是刚构建的
exe = os.path.join(ROOT, "dist", "视频工具箱", "视频工具箱.exe")
if not os.path.isfile(exe):
    print("!! dist\\视频工具箱\\视频工具箱.exe 不存在，先跑 _build_onefile.py（onedir）")
    raise SystemExit(2)
print("主程序    : %s  %d 字节  %s" % (
    exe, os.path.getsize(exe),
    time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(exe)))))

t0 = time.time()
r = subprocess.run([ISCC, ISS], cwd=ROOT, capture_output=True)
out = (r.stdout or b"").decode("utf-8", "replace")
err = (r.stderr or b"").decode("utf-8", "replace")
log_path = os.path.join(ROOT, "build", "iscc.log")
os.makedirs(os.path.dirname(log_path), exist_ok=True)
with open(log_path, "w", encoding="utf-8", newline="") as fh:
    fh.write(out)
    if err:
        fh.write("\n---- stderr ----\n" + err)
print("ISCC 日志 :", log_path)
print("== ISCC 退出码 %d，用时 %.1fs ==" % (r.returncode, time.time() - t0))

lines = out.splitlines()
for ln in lines[-25:]:
    print("   " + ln)
if r.returncode != 0:
    print("---- stderr ----")
    print(err[-3000:])
    raise SystemExit(1)

outdir = os.path.join(ROOT, "installer")
print("installer 目录：")
for f in sorted(os.listdir(outdir)):
    p = os.path.join(outdir, f)
    if os.path.isfile(p):
        print("   %-46s %12d  %s" % (
            f, os.path.getsize(p),
            time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(p)))))
