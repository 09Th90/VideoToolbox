# -*- mode: python ; coding: utf-8 -*-
"""视频工具箱 v1.10.3 —— PyInstaller 打包配置
v1.10.3：打包环境固定为 tools\\python（内嵌 CPython 3.12，videocaptioner 及
        全部依赖就在其 site-packages 里）；此前用系统 Python312 打包时
        videocaptioner 不可见，exe 里其实没进引擎。
v1.10.2：字幕引擎内嵌进 exe（collect_data_files/collect_submodules 收集
        videocaptioner 及其资源）；不再依赖 tools/python 里的引擎副本。

v1.10.1：入口改为 video_toolbox_qt.py（Fluent 界面，PyQt5 + qfluentwidgets），
        B站投稿板块已移除；不再随包分发 tools/uploader_src 与 tools/ms-playwright。

v1.10.0：字幕链路替换为内置 VideoCaptioner——原 asr_subtitle_worker.py 已移除，
        不再向 exe 注入任何 worker 数据文件；字幕处理工具以独立进程从
        tools\\python 拉起（含 VideoCaptioner 及其依赖），exe 本身只依赖
        tkinter 标准库 + 同级 tools 目录。
v1.9.3：新增「字幕校准」功能——校准脚本 subtitle_calib_merged.py 不打包进 exe
        （运行时被 tools\\python 子进程按 APP_DIR 根目录路径调用），
        由 视频工具箱.iss 作为普通文件安装到程序目录顶层。
v1.7：源码归入 src\\，入口与 worker 均从 src\\ 收集；运行时仍锚定 exe 同级 tools。"""
import os
from PyInstaller.utils.hooks import collect_all

# SPECPATH 由 PyInstaller 注入，值为 spec 文件所在目录（绝对/相对均归一）
SPEC_DIR = os.path.abspath(SPECPATH) if isinstance(SPECPATH, str) else SPECPATH[0]
SRC_DIR = os.path.join(SPEC_DIR, "src")

# v1.10.2：字幕引擎内嵌进 exe（videocaptioner + 全部 UI 资源），界面不再唤起独立窗口。
#   VC 的数据文件（assets/字体/图标）与子模块需显式收集，否则运行时缺资源白屏。
datas = []
binaries = []
hiddenimports = []
from PyInstaller.utils.hooks import collect_data_files, collect_submodules
datas += collect_data_files('videocaptioner')
hiddenimports += collect_submodules('videocaptioner')

# 字幕引擎的运行时依赖：多为延迟导入，静态分析发现不了，必须显式声明
hiddenimports += ['httpx', 'httpcore', 'anyio', 'sniffio', 'h11', 'certifi',
                  'openai', 'qrcode', 'pydantic', 'pydantic_core', 'PIL',
                  'PIL.Image', 'PIL.ImageDraw', 'PIL.ImageFont', 'numpy',
                  'tqdm', 'chardet', 'colorama', 'pydub', 'psutil',
                  'diskcache', 'fontTools', 'GPUtil', 'json_repair',
                  'langdetect', 'platformdirs', 'tenacity', 'requests',
                  'urllib3', 'mutagen', 'brotli', 'curl_cffi']

# 该程序只依赖 tkinter 标准库 + 同目录 tools（运行时锚定 exe 同级 tools），
# 不引入任何重型第三方运行时；打包为单文件 exe，直接双击运行。

a = Analysis(
    [os.path.join(SRC_DIR, 'video_toolbox_qt.py')],
    pathex=[SPEC_DIR, SRC_DIR],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['torch', 'torchaudio', 'torchvision', 'gradio', 'gradio_client',
              'transformers', 'faster_whisper', 'onnxruntime', 'playwright',
              'pandas', 'matplotlib', 'scipy', 'pytest', 'cv2', 'webview',
              'pyautogui'],
    noarchive=False,
)
pyz = PYZ(a.pure)

# 瘦身：剔除明确用不到的大体积二进制，把单文件 exe 压回 GitHub 100MB 硬限制内
#   opengl32sw.dll(20MB)  软件 OpenGL 回退，有显卡驱动时不需要
#   hf_xet(9MB)           HuggingFace Xet 下载加速，字幕引擎不走 HF 大模型下载
#   PIL/_avif(7.5MB)      AVIF 解码，封面/字幕图片均为 jpg/png/webp
_DROP_BINARIES = ('opengl32sw.dll', 'hf_xet', '_avif')
a.binaries = [b for b in a.binaries
              if not any(d in os.path.basename(b[0]).lower() or d in b[0].lower()
                         for d in _DROP_BINARIES)]

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
