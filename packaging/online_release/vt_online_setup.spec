# -*- mode: python ; coding: utf-8 -*-
# @version 2.2.5
"""视频工具箱 · 在线引导安装器 —— PyInstaller 打包配置。

产物：单文件 exe，`视频工具箱_在线安装_v<版本>.exe`（输出到 installer_online\\）。

为什么用 tkinter 而不是 Qt：本 exe 只需「版本信息 / 选目录 / 进度 / 日志」，
tkinter 是标准库，打出来约 12MB；换成 Qt（PyQt5 / PySide6）要 ~40MB —— 而它
本身也是要给用户下载的，体积直接算在更新成本里。

⚠ 只打包 vt_online_setup.py / vt_update_core.py / vt_dl.py / vt_version_index.py
   四个自研文件，**不收集任何第三方包**：
   · tkinter 由 PyInstaller 的 hook 自动带上（含 tcl/tk 运行库）；
   · 更新逻辑刻意只用标准库（见 vt_update_core.py 顶部说明），
     这样引导安装器不会被主程序的依赖树拖大。
   ⚠ 后两个模块是 import 进来的、没有在分析期被静态引用到名字，
     必须列进 hiddenimports，否则打包后运行时才 ImportError。
"""
import os

# SPECPATH 由 PyInstaller 注入，值为 spec 所在目录
SPEC_DIR = os.path.abspath(SPECPATH) if isinstance(SPECPATH, str) else SPECPATH[0]
#: 本目录 = packaging\online_release\；仓库根再上两级
ROOT = os.path.abspath(os.path.join(SPEC_DIR, os.pardir, os.pardir))

import re  # noqa: E402

_ver = "0.0.0"
_qt = os.path.join(ROOT, "src", "video_toolbox_qt.py")
if os.path.isfile(_qt):
    _m = re.search(r'VERSION\s*=\s*"([\d.]+)"',
                   open(_qt, encoding="utf-8").read())
    if _m:
        _ver = _m.group(1)

a = Analysis(
    [os.path.join(SPEC_DIR, "vt_online_setup.py")],
    pathex=[SPEC_DIR],
    binaries=[],
    datas=[],
    hiddenimports=["vt_update_core", "vt_dl", "vt_version_index"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 引导安装器不需要这些重型件；显式排除可让体积与构建时间都更可控
    # （2026-10-14 PySide6 迁移：PySide6 与 PyQt5 一并剔除，两边都别进包）
    excludes=["PyQt5", "PySide6", "numpy", "onnxruntime", "PIL", "torch", "cv2",
              "matplotlib", "pandas", "scipy", "cryptography"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="视频工具箱_在线安装_v%s" % _ver,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,          # 图形界面；--silent 时的输出仍会走标准流
    disable_windowed_traceback=False,
)
