# -*- mode: python ; coding: utf-8 -*-
# @version 1.15.6
"""视频工具箱 v1.15.6 —— PyInstaller 打包配置
v1.15.2：补 `websocket` 到 hiddenimports——**实时（WebSocket）ASR 协议**（百炼
         `dashscope_realtime`）依赖 websocket-client，而此前**打包环境里根本没装
         这个包**、spec 也没声明 ⇒ exe 内嵌引擎执行到 `import websocket` 必失败，
         表现就是点「语音转录」走实时协议时弹「转录失败：实时协议缺少依赖
         websocket-client」。注意提示里那句「pip install websocket-client」对
         安装版用户是**无效指引**（exe 用的是内嵌模块，装到系统 Python 不生效）。
         处置：打包环境已装 `websocket-client==1.9.2`（与 tools\python 运行副本
         同版本、内容逐文件一致），此处再显式声明双保险。
         教训：**运行副本装了、打包副本没装的第三方向来是隐形缺口**——发布前用
         `C:\bld\_check_dep_closure.py`（在打包环境跑）扫一遍依赖闭合。
v1.12.2：AI 校准修复 + Agent 可靠性同步优化——校准页误引用设置页控件导致
         「开始校准」一点即崩、崩后界面永久卡死（启动全程异常兜底 + 校准页
         新增「刷新」与卡死自愈）；qfluentwidgets 滚动条 eventFilter 对鼠标
         事件抛 AttributeError（运行副本与 .buildvenv 打包副本已同步改为
         isinstance 判定 + 父控件尺寸——exe 内嵌的 Qt 库来自 tools\\python
         那份副本，随 视频工具箱.iss 原样分发，无需改本配置）；calib_ai_agent
         解析改三态并接入 json_repair 抢救、失败分级重试、停止条件与逐轮轨迹。
         打包配置无需变更。
v1.12.1：修复打包版「点退出后程序反复重启」（严重）——退出时的校准知识同步
         原以 [sys.executable, "-c", ...] 派生子进程；冻结成单文件 exe 后
         sys.executable 就是主程序自身，于是每次退出都拉起一个新的 GUI 实例，
         新旧实例互相抢占/删除 _MEI 临时目录，表现为退出后无限重启，并弹出
         「Failed to remove temporary directory: _MEI***」与「no Qt platform
         plugin could be initialized」错误框。现统一改用 system_python() /
         _calib_py() / calib_ai_agent.resolve_python() 解析真实解释器，并以
         _is_self_exe() 兜底：解析不到就跳过退出同步，绝不回退到 exe 自身。
         本次改动在 src\\video_toolbox.py 与 src\\calib_ai_agent.py，打包配置无需变更。
v1.12.0：翻译链路全面修缮——① 谷歌翻译改抓 Chrome 内置翻译同源免费接口
         （translate_a/t?client=dict-chrome-ex，官方旧端点已被 302 到验证码页）
         并加全局请求节流（相邻请求 ≥0.12s，约 8 QPS）；② 必应翻译换
         translatetext 端点取 token（官方匿名 token 方案已失效）；③ 翻译基类
         对失败译文（ERROR / 空 / xxx||ERROR）不写缓存、块级可重试；
         ④ LLM 翻译并发上限（_LLM_THREAD_CAP=5）与限流处理，防 429 刷屏；
         ⑤ 取消任务立即停掉翻译/优化线程池（原先取消后仍跑完剩余批次）；
         ⑥ 「启用 AI」关闭时翻译兜底不介入 LLM。打包配置无需变更。
v1.11.0：LLM 拆为两条独立通道（接口 A 工具箱 / 接口 B 引擎，各自地址+密钥+模型）、
         新增全局 ASR（自有 ASR 服务 / 本地独立模型 → 引擎「转录配置」）、
         字幕校准新增 Agent 级 AI 校准（新增 src\\calib_ai_agent.py，需作为
         hiddenimport 收进 exe）、diskcache 延迟化消除引擎界面启动数秒卡顿。
v1.10.8：设置收敛为唯一全局设置页、LLM 配置全局化（工具箱与字幕引擎共用）、
         引擎默认路径全部强制到软件文件夹；校准知识合并核心抽到
         src\\calib_merge_core.py（纯函数），需作为 hiddenimport 收进 exe。
v1.10.5：校准脚本升级（对象级 ENTITIES + 学习系统）、校准界面模式列表与脚本
         对齐（12 种模式，去掉已废弃的 --layout 开关）、新增退出时静默同步
         校准脚本到 GitHub（engine.sync_calib_on_exit，于 aboutToQuit 挂接）。
         本次改动在 src\\video_toolbox.py 与 src\\video_toolbox_qt.py，
         打包配置无需变更。
v1.10.4：界面与设置整合——导航宽度按最长项文字自适应、新增导航底部「设置」
        页统一承载工具设置与字幕引擎设置、跨屏拖拽保持相对位置、DPI 取整
        改为 PassThrough、字幕引擎界面后台预热（消除首次进入卡顿）。
        本次改动全在 src\\video_toolbox_qt.py，打包配置无需变更。
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
# 注意：引擎界面图片/字体/默认样式等 resource 静态树不打进 exe（onefile 解压目录
# 并非 vc_bundled_resource_dir 的锚点），而是由 视频工具箱.iss 原样铺到
# {app}\tools\videocaptioner\resource（exe 同级 tools），运行时按盘路径读取。

# v1.10.8：校准知识条目级合并核心（video_toolbox 顶层 import，静态分析一般能
# 跟踪到，这里显式声明双保险——退出同步子进程/界面都依赖它）。
hiddenimports += ['calib_merge_core']

# v1.13.x：界面美化（各板块自定义背景图，src\ui_theme.py，video_toolbox_qt
# 顶层 import 本可被静态跟踪，按惯例显式声明双保险）。
hiddenimports += ['ui_theme']

# v1.11.0：AI 校准 Agent（延迟导入：engine.calib_ai_run 内部 import，静态分析
# 发现不了，必须显式声明，否则打包后点「AI 校准」会 ModuleNotFoundError）。
hiddenimports += ['calib_ai_agent']

# 2026-09-20：AI 校准 Agent 的联网查证工具（calib_web_agent，同样是
# calib_ai_run 内部延迟 import，开启「联网查证」后点校准才会加载）。
hiddenimports += ['calib_web_agent']

# v1.13.0：字幕编辑页的 libmpv 播放器。python-mpv 绑定（mpv.py，纯标准库、
# 约 90KB）由 subtitle_editor_media.load_mpv() 延迟导入，静态分析发现不了。
# 不声明的话打包后点「打开视频」会 ModuleNotFoundError: No module named 'mpv'。
# 注意：只打包**绑定**，不打包 libmpv-2.dll（95MB、LGPL，由
# tools/download_open_source_deps.py --only mpv 运行时拉取到 tools\mpv\）。
hiddenimports += ['mpv']

# 字幕引擎的运行时依赖：多为延迟导入，静态分析发现不了，必须显式声明
# v1.15.2：'websocket' = websocket-client，实时 ASR 协议（dashscope_realtime）
#   必需；打包环境当初漏装该包，导致 exe 跑实时协议必报缺依赖。
hiddenimports += ['httpx', 'httpcore', 'anyio', 'sniffio', 'h11', 'certifi',
                  'openai', 'qrcode', 'pydantic', 'pydantic_core', 'PIL',
                  'PIL.Image', 'PIL.ImageDraw', 'PIL.ImageFont', 'numpy',
                  'tqdm', 'chardet', 'colorama', 'pydub', 'psutil',
                  'diskcache', 'fontTools', 'GPUtil', 'json_repair',
                  'langdetect', 'platformdirs', 'tenacity', 'requests',
                  'urllib3', 'mutagen', 'brotli', 'curl_cffi',
                  'websocket']

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
