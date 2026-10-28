# -*- coding: utf-8 -*-
# @version 2.8.0
"""ASCII 路径驱动 PyInstaller 打包（2026-10-21 收编进仓库）。

默认 **onedir**：`dist\\视频工具箱\\视频工具箱.exe` + `_internal\\`。
传 `--mode onefile` 可回退单文件便携版（启动需解包，速度慢）。

原驱动为仓库外脚本 ``C:\\bld\\_build_vt_170.py``；构建链位于 C 盘
（``C:\\vt_build`` junction / ``C:\\bld\\qt_build`` venv），2026-10-25 自 D 盘回退，
构建入口不再依赖仓库外资产。

用法::

    C:\\bld\\qt_build\\Scripts\\python.exe scripts\\dev\\_build_onefile.py

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
BUILD_ROOT = r"C:\vt_build"
#: 构建环境（C 盘，2026-10-25 自 D 盘回退）
BLD = r"C:\bld"
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

MODE = "onedir"
_args = sys.argv[1:]
for _i, _a in enumerate(_args):
    if _a == "--mode" and _i + 1 < len(_args):
        MODE = _args[_i + 1].strip().lower()
    elif _a.startswith("--mode="):
        MODE = _a.split("=", 1)[1].strip().lower()
if MODE not in ("onedir", "onefile"):
    print("!! --mode 只能是 onedir / onefile：", MODE)
    raise SystemExit(2)
os.environ["VT_BUILD_MODE"] = MODE
print("构建模式  :", MODE)

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
        main_exe = os.path.join(p, "视频工具箱.exe")
        n_files = sum(len(fs) for _r, _d, fs in os.walk(p))
        print("   [dir] %-33s %d files, exe=%s"
              % (f, n_files,
                 os.path.getsize(main_exe) if os.path.isfile(main_exe) else "MISSING"))
