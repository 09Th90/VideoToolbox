# -*- mode: python ; coding: utf-8 -*-
"""视频工具箱 v1.9.1 —— PyInstaller 打包配置
v1.7：源码归入 src\\，入口与 worker 均从 src\\ 收集；运行时仍锚定 exe 同级 tools。"""
import os
from PyInstaller.utils.hooks import collect_all

# SPECPATH 由 PyInstaller 注入，值为 spec 文件所在目录（绝对/相对均归一）
SPEC_DIR = os.path.abspath(SPECPATH) if isinstance(SPECPATH, str) else SPECPATH[0]
SRC_DIR = os.path.join(SPEC_DIR, "src")

# 「字幕生成」worker 脚本随包分发：运行时从 sys._MEIPASS 解包位置调用。
# ASR 运行时/模型与投稿引擎源码均位于 tools/ 目录，与 exe 一起分发，
# 不再依赖外部 E 盘程序。未嵌入解释器时调用系统 Python。
datas = [(os.path.join(SRC_DIR, "asr_subtitle_worker.py"), ".")]
binaries = []
hiddenimports = []

# 该程序只依赖 tkinter 标准库 + 同目录 tools（运行时锚定 exe 同级 tools），
# 不引入任何重型第三方运行时；打包为单文件 exe，直接双击运行。

a = Analysis(
    [os.path.join(SRC_DIR, 'video_toolbox_gui.py')],
    pathex=[SPEC_DIR, SRC_DIR],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['torch', 'torchaudio', 'torchvision', 'gradio', 'gradio_client',
              'transformers', 'faster_whisper', 'playwright', 'numpy', 'pandas',
              'matplotlib', 'scipy', 'PIL', 'pytest', 'cv2', 'webview', 'pyautogui'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='视频工具箱',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
