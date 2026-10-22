# -*- coding: utf-8 -*-
# @version 2.5.2
"""ASCII 路径驱动 PyInstaller 打包 onefile exe（2026-10-21 收编进仓库）。

原驱动为仓库外脚本 ``C:\\bld\\_build_vt_170.py``；构建链 C 盘依赖
（``C:\\vt_build`` junction / ``C:\\bld\\qt_build`` venv）整体迁移至 D 盘
后随本脚本收编，构建入口不再依赖仓库外资产。

用法::

    D:\\Agent Work\\_bld\\qt_build\\Scripts\\python.exe scripts\\dev\\_build_onefile.py

要点：
- BUILD_ROOT 必须是 ASCII 路径目录联接（junction）。PyInstaller 的 Qt 钩子在
  中文项目路径下会把 QLibraryInfo 返回的路径读成 ``?????``（UTF-8 模式无效）；
- 构建环境必须装 onnxruntime（v1.17.0 起声纹筛选依赖它）；
- ``env -u PYTHONPATH``：构建机 safe-delete shim 经 PYTHONPATH 加载，
  不收干净会被 PyInstaller 收进 PYZ（spec excludes 另有 sitecustomize/
  usercustomize 兜底，双保险）。
"""
import os
import sys
import time

#: 项目目录的 NTFS 目录联接（ASCII 路径，供 PyInstaller 使用）
BUILD_ROOT = r"D:\Agent Work\_vt_build"
#: 构建环境新家（D 盘，2026-10-21 自 C:\\bld 迁出）
BLD = r"D:\Agent Work\_bld"
SPEC_REL = os.path.join("packaging", "视频工具箱.spec")

if not os.path.isdir(BUILD_ROOT):
    print("!! 打包根不存在：", BUILD_ROOT,
          "（junction 失效时用 PowerShell 重建：New-Item -ItemType Junction）")
    raise SystemExit(2)

os.chdir(BUILD_ROOT)

_probe = os.path.join(BUILD_ROOT, "src", "video_toolbox_qt.py")
if not os.path.isfile(_probe):
    print("!! 打包根下找不到 src\\video_toolbox_qt.py：", _probe)
    raise SystemExit(2)
print("打包根    :", BUILD_ROOT, "（realpath:", os.path.realpath(BUILD_ROOT), "）")
print("探针文件  :", _probe, os.path.getsize(_probe), "字节")

spec = os.path.join(BUILD_ROOT, SPEC_REL)
if not os.path.isfile(spec):
    print("!! 找不到 spec：", spec)
    raise SystemExit(2)
print("spec      :", spec, os.path.getsize(spec), "字节")

try:
    import onnxruntime as _ort
    print("onnxruntime:", _ort.__version__)
except Exception as e:  # noqa: BLE001
    print("!! 打包环境缺 onnxruntime：", e)
    raise SystemExit(2)

sys.argv = [
    "pyinstaller", spec,
    "--noconfirm",
    "--distpath", os.path.join(BUILD_ROOT, "dist"),
    "--workpath", os.path.join(BUILD_ROOT, "build_ascii"),
]

from PyInstaller.__main__ import run  # noqa: E402

t0 = time.time()
run()
print("== PyInstaller 完成，用时 %.1fs ==" % (time.time() - t0))

out = os.path.join(BUILD_ROOT, "dist")
print("dist 内容：")
for f in sorted(os.listdir(out)):
    p = os.path.join(out, f)
    if os.path.isfile(p):
        print("   %-40s %12d  %s" % (
            f, os.path.getsize(p),
            time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(p)))))
    else:
        print("   [dir] " + f)
