# -*- mode: python ; coding: utf-8 -*-
# @version 2.5.0
"""视频工具箱 v2.5.0 —— PyInstaller 打包配置
v2.1.0（2026-10-14）：PyQt5 → PySide6 迁移（docs/PySide6迁移方案书）。本 spec 的
        实质改动只有三处：① _DROP_BINARIES 的 QML 三件套从 Qt5 名改成 Qt6 名
        （Qt6Qml/Qt6Quick/Qt6QmlModels/Qt6QmlMeta/Qt6QmlWorkerScript.dll）；
        ② MSVC 补丁的目录判据从 `pyqt5/qt5/bin` 改为 `pyside6`/`shiboken6`
        （2026-10-14 实测：PySide6 wheel 确实自带 MSVC runtime，PySide6\ 与
        shiboken6\ 下共有 9 个同名副本，该补丁实际匹配并改写 6 个，非空转）；
        ③ 注释口径同步。其余（hiddenimports/datas/collect_* 规则）与 Qt 绑定
        无关，全部不变——PySide6 的 Qt6 DLL/plugins 由 PyInstaller 自带 hook
        收集，布局与 PyQt5 不同（扁平、无 Qt5\bin 与 Qt5\plugins 中间层），
        spec 无需手动指定路径。
v1.18.0：① 新增**主播声纹筛选**的运行时——`speaker_voiceprint_page` /
        `speaker_voiceprint` 是 `video_toolbox.vc_transcribe_ui_patch()` 里的
        **延迟导入**（缺依赖只记日志、界面照起），静态分析跟踪不到，必须显式
        声明；`onnxruntime` 同理（`faster_whisper/vad.py` 与
        `speaker_voiceprint._session()` 都在函数体内 import）。⚠⚠ 它原本在
        **excludes** 里，而 **excludes 优先级高于 hiddenimports** —— 只加
        hiddenimports 不摘 excludes，包出来照样没有；已一并摘掉并加
        `collect_dynamic_libs('onnxruntime')`（PyInstaller 无官方 hook）。
        代价约 +40MB（主要是 18MB 的 onnxruntime.dll）。声纹**模型** 27MB 仍
        按需下载、不进包。② ⚠⚠ 声纹还依赖启动期那段 MSVC 运行时预加载
        （`video_toolbox_qt.py::_fix_msvc_runtime_shadow`，必须在 PySide6 导入
        之前）——少了它，旧版 Qt 运行时会顶掉 onnxruntime 依赖的新版而加载失败
        （PyQt5 时代 Qt5\bin 自带 14.26 MSVC runtime 是真实根因；PySide6 实测
        已不自带，该函数变为防御性冗余，时机要求不变）。③ ⚠ 打包环境 `C://bld//qt_build` 当时**没有** onnxruntime
        （pip 直连 pypi 超时），已从 `tools\python\Lib\site-packages` 直接
        拷贝同版本（两侧同为 CPython 3.12.10 AMD64）。**新功能引入新三方依赖
        时，先查打包环境有没有。**
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
        字幕引擎运行时不可见，exe 里其实没进引擎。
v1.10.2：字幕引擎内嵌进 exe（collect_data_files/collect_submodules 收集
        字幕引擎运行时及其资源）；不再依赖 tools/python 里的引擎副本。

v1.10.1：入口改为 video_toolbox_qt.py（Fluent 界面，PyQt5 + qfluentwidgets；
        2026-10-14 起为 PySide6 + qfluentwidgets），
        B站投稿板块已移除；不再随包分发 tools/uploader_src 与 tools/ms-playwright。

v1.10.0：字幕链路替换为自研字幕处理引擎——原 asr_subtitle_worker.py 已移除，
        不再向 exe 注入任何 worker 数据文件；字幕处理工具以独立进程从
        tools\\python 拉起（含字幕处理引擎运行时及其依赖），exe 本身只依赖
        tkinter 标准库 + 同级 tools 目录。
v1.9.3：新增「字幕校准」功能——校准脚本 subtitle_calib_merged.py 不打包进 exe
        （运行时被 tools\\python 子进程按 APP_DIR 根目录路径调用），
        由 视频工具箱.iss 作为普通文件安装到程序目录顶层。
v1.7：源码归入 src\\，入口与 worker 均从 src\\ 收集；运行时仍锚定 exe 同级 tools。"""
import os
from PyInstaller.utils.hooks import collect_all

# SPECPATH 由 PyInstaller 注入，值为 spec 文件所在目录（绝对/相对均归一）
SPEC_DIR = os.path.abspath(SPECPATH) if isinstance(SPECPATH, str) else SPECPATH[0]
# spec 位于 <仓库根>/packaging/，主程序源码在 <仓库根>/src
SRC_DIR = os.path.abspath(os.path.join(SPEC_DIR, os.pardir, "src"))

# v1.10.2：字幕引擎内嵌进 exe（运行时 + 全部 UI 资源），界面不再唤起独立窗口。
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

# 2026-10-13：P1 引擎自研化接缝（替代 videocaptioner.core.entities 的枚举与
#   videocaptioner.core.asr.asr_data 的字幕数据模型）。video_toolbox 里全是
#   **函数体内延迟 import**（如 vc_transcribe_ui_patch 内 import engine_entities、
#   _vt_filter_current_subtitle 内 import engine_asr_data），静态分析跟踪不到；
#   且 engine_asr_data 静态 import 了 engine_entities / subtitle_editor_core，
#   必须显式声明，否则声纹筛选回写字幕表格时 ModuleNotFoundError（调用点套了
#   try/except 只记日志，不报错）。两模块均零三方依赖（langdetect 为可选增强）。
hiddenimports += ['engine_entities', 'engine_asr_data']

# 2026-10-13（并行会话补）：cache / paths 两个接缝同样是函数体内延迟 import
#   （video_toolbox.vc_lazy_cache_patch 内 import engine_cache、路径重定向处
#   import engine_paths），不声明的话打包后惰性缓存与路径接管静默失效。
hiddenimports += ['engine_cache', 'engine_paths']

# 2026-10-13：翻译接缝（engine_translate）——自研替代三个免费翻译器的第三方
#   实现，是本项目**不再持有第三方翻译器源码**的关键（原先靠 docs\vc_translate_impl
#   的 GPL 副本回写引擎）。仅被自检与将来的接管调用点引用，故显式声明。
hiddenimports += ['engine_translate']

# 2026-10-13：ASR 链路（P2 档 B）—— WhisperAPI / BaseASR / ChunkedASR+ChunkMerger /
#   transcribe 编排。engine_asr 内对 engine_asr_http / engine_asr_local 都是**函数体内
#   延迟 import**（前者只在 _submit 里用到、后者只在 local 模式分发时用到），
#   静态分析跟踪不到；漏声明的表现是「远端转录可用、local 模式 ImportError」。
#   engine_asr_local 依赖 GPUtil（可选增强，try-import），不必显式声明。
hiddenimports += ['engine_asr', 'engine_asr_http', 'engine_asr_local']

# 2026-10-13（P2 尾部 / 档 B）：自研任务工厂 engine_task_factory —— 接管
#   videocaptioner.ui.task_factory 的构造逻辑，内建 vc_asr_patch_apply 的本地模型/
#   显式语言覆盖。由 vt_engine_ui._seams 在**属性访问时惰性 import**（且有引擎回退），
#   静态分析跟踪不到；漏声明的表现是「打包后自研 UI 静默回退引擎工厂」——功能不缺
#   但自研化没生效，最难发现。_selftest_engine_task_factory.py 已逐字段比对通过。
hiddenimports += ['engine_task_factory']

# v1.13.x：界面美化（各板块自定义背景图，src\ui_theme.py，video_toolbox_qt
# 顶层 import 本可被静态跟踪，按惯例显式声明双保险）。
hiddenimports += ['ui_theme']

# v1.11.0：AI 校准 Agent（延迟导入：engine.calib_ai_run 内部 import，静态分析
# 发现不了，必须显式声明，否则打包后点「AI 校准」会 ModuleNotFoundError）。
hiddenimports += ['calib_ai_agent']

# 2026-09-20：AI 校准 Agent 的联网查证工具（calib_web_agent，同样是
# calib_ai_run 内部延迟 import，开启「联网查证」后点校准才会加载）。
hiddenimports += ['calib_web_agent']

# 2026-10-12：AI 校准 Agent 的**音画证据**工具（calib_media_agent）。engine
#   video_toolbox.py:5465 在函数体内 `import calib_media_agent as _media`
#   （开启「音画证据」开关后点校准才走），静态分析跟踪不到 ⇒ 不声明的话
#   打包后音画证据永远走降级分支、只返回「证据获取失败」，且**不报错**。
#   该模块零第三方依赖（ffmpeg 子进程 + urllib multipart POST）。
hiddenimports += ['calib_media_agent']

# v1.13.0：字幕编辑页的 libmpv 播放器。python-mpv 绑定（mpv.py，纯标准库、
# 约 90KB）由 subtitle_editor_media.load_mpv() 延迟导入，静态分析发现不了。
# 不声明的话打包后点「打开视频」会 ModuleNotFoundError: No module named 'mpv'。
# 注意：只打包**绑定**，不打包 libmpv-2.dll（95MB、LGPL，由
# tools/download_open_source_deps.py --only mpv 运行时拉取到 tools\mpv\）。
hiddenimports += ['mpv']

# v1.17.0：NewPipe Extractor 第二解析引擎后端。**必须显式声明**——
#   video_toolbox.npe_available() 与 DownloadWorker._npe_fallback() 都是在
#   函数体内 `import npe_backend`（延迟导入，防缺依赖时整个引擎起不来），
#   PyInstaller 静态分析跟踪不到 ⇒ 不声明的话打包后 yt-dlp 全源失败时
#   兜底分支必然 ModuleNotFoundError，日志只留「[NPE] 模块导入失败」。
#   该模块仅标准库（json/os/shutil/subprocess/concurrent.futures），无三方依赖。
#   ⚠️ 只内嵌 **Python 模块**；npe-cli.jar（GPL-3.0，约 3.8MB）与 java 运行时
#   都不进 exe——jar 由 视频工具箱.iss 铺到 {app}\tools\newpipe-cli\dist\，
#   java 由用户自备 JDK 17+（见 npe_backend.find_java 与 docs\组件来源声明）。
hiddenimports += ['npe_backend']

# v1.18.0：主播声纹（本地声纹筛选，只出主播字幕）。**必须显式声明**——
#   video_toolbox.vc_transcribe_ui_patch() 的两个补丁体里都是
#   `from speaker_voiceprint_page import ...`（延迟导入，缺依赖时只记日志、
#   不影响引擎界面起来），PyInstaller 静态分析跟踪不到 ⇒ 不声明的话打包后
#   界面上既没有「主播声纹」录入卡、也没有转录设置里的多声纹勾选，
#   而且**不报错**（补丁里 try/except 吞掉），最难查。
#   speaker_voiceprint 被 speaker_voiceprint_page 静态 import，声明后者即可，
#   这里一并列出双保险。
hiddenimports += ['speaker_voiceprint_page', 'speaker_voiceprint']
# v1.19.0：声纹模板的**多用户同步通道** `voiceprint_sync`（独立通道，与校准知识
#   同步无关，数据落 data\vp_sync\）。⚠ speaker_voiceprint.py 里是三处
#   **函数体内延迟 import**（录入/重录/删除时排队列），静态分析同样跟踪不到。
#   不声明的话：安装版一录入或删除声纹就 ImportError——而调用点外面套了
#   try/except 静默降级，表现为「声纹录进去了但永远不同步、且不报错」，
#   与上面 v1.18.0 那次「界面没有声纹卡且不报错」是同一类最难查的坑。
#   ⚠ 同时 packaging\视频工具箱.iss 也要装 {app}\src 下的源码副本（已装）。
hiddenimports += ['voiceprint_sync']

# v1.18.0（已拍板：**打进包**）：onnxruntime 是声纹筛选的运行时。
#   faster_whisper/vad.py 是在**函数体内** `import onnxruntime`（延迟导入），
#   speaker_voiceprint 也是在 `_session()` 里延迟导入 ⇒ 两者 PyInstaller 静态
#   分析都发现不了，必须显式声明；不声明的话 exe 里既没有声纹运行时，
#   faster_whisper 的 VAD 过滤也是缺的（只是默认不开，一直没人发现）。
#   代价约 +40MB（主要是 18MB 的 onnxruntime.dll）；换来的是：
#     · 装的机器上「主播声纹筛选」开箱可用（模型另下）；
#     · faster_whisper 的 VAD 过滤一并可用。
#   ⚠ 声纹**模型**（27MB）不进包，仍由 download_open_source_deps.py 按需下载。
#   ⚠ 声纹功能还依赖启动期那段 MSVC 运行时预加载
#     （video_toolbox_qt.py::_fix_msvc_runtime_shadow，必须在 PyQt5 导入之前）——
#     少了它，onnxruntime 的 pyd 会被 Qt5\bin 里的旧运行时顶掉而加载失败。
hiddenimports += ['onnxruntime']

# ⚠⚠ 必须与上面配套：onnxruntime 原本在 **excludes** 里（当初按"重型运行时
#   一律剔"的策略加的），而 excludes 优先于 hiddenimports —— 只加 hiddenimports
#   不摘 excludes，包出来的 exe 里照样没有 onnxruntime。见下方 excludes 注释。
#   原生 DLL（onnxruntime.dll 18MB + providers_shared）放在包的 capi\ 子目录，
#   PyInstaller 无官方 hook，靠 bindepend 扫 .pyd 导入表一般能带上，这里显式
#   收集双保险（漏一个就是"导入成功但推理时报 DLL 找不到"）。
from PyInstaller.utils.hooks import collect_dynamic_libs
binaries += collect_dynamic_libs('onnxruntime')

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

# v2.0.0：主程序「检查更新」依赖自研在线安装器的三个模块。它们在
#   **packaging\online_release\ 下，不在 src\ 里**，且 `vt_update_check`
#   对它们是 `import vt_update_core` 的**普通顶层 import**——但注意
#   它自己做了 try/except 降级（找不到就返回 None），所以**漏声明的
#   症状是静默的**：更新按钮点了报「更新组件未随程序分发」，而不是崩。
#   这类「静默降级」最容易被当成功能没做，故显式声明：
#   · pathex 已在下方 Analysis 里含 PACKAGING 根，故能解析到；
#   · 同时把三个模块源码**当作数据**随包分发到 online_release\，
#     兼顾「在线安装器也能从主程序目录取用」的场景。
online_release_dir = os.path.join(SPEC_DIR, 'online_release')
hiddenimports += ['vt_dl', 'vt_update_core', 'vt_version_index']

# v2.1.0（P3 引擎自研化 · 档 C）：自研字幕工作台 UI 包 `vt_engine_ui`。
#   由 video_toolbox_qt._resolve_engine_ui() 在**函数体内** `import vt_engine_ui`
#   （延迟导入 + 引擎回退），PyInstaller 静态分析跟踪不到；其子模块
#   （home_interface / *_interface / components / _seams / _signals 等）又在包
#   __init__ 里二次延迟导入 ⇒ 不声明的话打包后自研 UI 整体缺失，_resolve 静默
#   回退引擎，表现为「替换没生效但也不报错」——与声纹那两次同类、最难查。
#   collect_submodules 递归收全包，一次到位。
#   ⚠ vt_engine_ui 物理位于 src\（非 site-packages 安装包），而 collect_submodules
#     在 **spec 解析期**就要 import 该包来枚举子模块——此时 pathex 尚未生效
#     （pathex 只作用于下方 Analysis）。不先把 SRC_DIR 塞进 sys.path，本调用会
#     **静默返回空列表**（实测 resolved=0），等于没声明。故显式补 path 再收集。
import sys as _sys
if SRC_DIR not in _sys.path:
    _sys.path.insert(0, SRC_DIR)
hiddenimports += collect_submodules('vt_engine_ui')

# v2.3.1（拆分工程）：自研核心域包 `core`（shared/download/asr/translate/
#   calibrate/pipeline）。facade video_toolbox.py 以 `from core.<域> import *`
#   显式再导出，静态分析能跟到各域 __init__ 层；但域内部模块（如
#   core/download/ytdlp_util）与 vt_engine_ui 同理靠 collect_submodules
#   递归收全。⚠ 同 vt_engine_ui 先例：spec 解析期 import core 需要 SRC_DIR
#   在 sys.path（上面已显式补），空骨架阶段收空列表属预期，拆到某域时自动生效。
hiddenimports += collect_submodules('core')

# v2.3.2（对象级优化，2026-10-19）：`calib_entity` 在 calib_ai_agent 里是
#   **函数体内延迟导入**（`from calib_entity.opt import kb_scope`），静态分析
#   跟不到；不声明的话打包后自动降级为旧行为——功能静默消失、且日志里看不出来
#   （try/except 只吞异常）。同 vt_engine_ui 先例：先补 SRC_DIR 再收集。
#   只依赖标准库，不会把 subtitle_calib_merged 拖进 PYZ。
hiddenimports += collect_submodules('calib_entity')

# v2.4.0（2026-10-19）：自研并行引擎 `vt_engine`（config / entities / 执行 /
#   编排 / threads 五层，31 个模块）。当前**尚未接入主程序**（只被
#   scripts/dev/_selftest_vt_engine.py 引用），主程序不 import 它，PyInstaller
#   静态分析因此收不到。这里显式收集有两个理由：
#     ① 它随源码入库，安装版应与仓库一致——否则「源码有、安装版没有」，
#        未来 _seams 切换到它时会出现只在新装的机器上才复现的 ImportError；
#     ② 只依赖标准库与 PySide6（已随包），增量约 1 MB，代价可忽略。
#   ⚠ 接入主程序后本行仍需保留（改为 collect_submodules 之外无需再动）。
hiddenimports += collect_submodules('vt_engine')
if os.path.isdir(online_release_dir):
    datas += [(os.path.join(online_release_dir, f),
               os.path.join('online_release', f))
              for f in sorted(os.listdir(online_release_dir))
              if f.endswith('.py')]

# ---------------------------------------------------------------------------
# 应用图标（v2.1.0）
# ---------------------------------------------------------------------------
# 两处都要，缺一不可，各管一段：
#   ① EXE(icon=...) —— 写进 PE 资源段，决定**资源管理器 / 任务栏 / 快捷方式**
#      显示 exe 本身时用什么图。这是最要紧的一处：安装后用户看到的图标
#      全部来自这里，光靠运行期 setWindowIcon 是**管不到**的（那是窗口图标，
#      任务栏按钮会跟着变，但 .exe 文件本身的图标不会）。
#   ② datas 收一份 —— 运行期 `MainWindow` 要 `setWindowIcon`（标题栏、
#      Alt-Tab、任务栏）；onefile 下源码 assets\ 不在磁盘上，只能从
#      `sys._MEIPASS` 读，故必须显式收进包。
# 图标由 scripts\dev\make_icon.py 从 assets\app_icon.png 生成（7 档，
# 像素画用最近邻缩放）。⚠ 换图标只需重跑该脚本并改这两行，无需动其它。
APP_ICON = os.path.join(os.path.dirname(SPEC_DIR), 'assets', 'app_icon.ico')
if not os.path.isfile(APP_ICON):
    raise SystemExit('缺少应用图标：%s（先跑 scripts\\dev\\make_icon.py 生成）'
                     % APP_ICON)
datas += [(APP_ICON, 'assets')]

a = Analysis(
    [os.path.join(SRC_DIR, 'video_toolbox_qt.py')],
    # ⚠ online_release_dir 必须在 pathex 里：三个更新模块物理上位于
    #   packaging\online_release\，而 pathex 只有 packaging 根的话，
    #   `import vt_update_core` 解析不到，hiddenimports 会静默失效。
    pathex=[SPEC_DIR, SRC_DIR] + ([online_release_dir]
                                   if os.path.isdir(online_release_dir) else []),
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # ⚠ v1.18.0：'onnxruntime' **已从剔单里摘掉**（声纹筛选要它，见上方注释）。
    #   excludes 优先级高于 hiddenimports，留着它等于白声明。
    #   'faster_whisper' 仍剔除——它跑在 tools\python 的**内嵌解释器**里
    #   （字幕引擎子进程），不占 exe 体积；同理 torch 系列一律不进。
    excludes=['torch', 'torchaudio', 'torchvision', 'gradio', 'gradio_client',
              'transformers', 'faster_whisper', 'playwright',
              'pandas', 'matplotlib', 'scipy', 'pytest', 'cv2', 'webview',
              'pyautogui',
              # ⚠⚠ 2026-10-19：**构建机 PYTHONPATH 上的 sitecustomize 会被
              #   PyInstaller 当普通模块收进 PYZ**。本次打出来的 v2.4.1 安装包
              #   里就混进了 Agent 沙箱的「安全删除」shim（把 os.remove /
              #   shutil.rmtree 改成送回收站，默认启用），既污染用户机器又会
              #   在批量删除时挂住。这两个名字永远不该进包，显式剔掉。
              'sitecustomize', 'usercustomize'],
    noarchive=False,
)
pyz = PYZ(a.pure)

# 瘦身：剔除明确用不到的大体积二进制，把单文件 exe 压回 GitHub 100MB 硬限制内
#   opengl32sw.dll(20MB)  软件 OpenGL 回退，有显卡驱动时不需要
#   hf_xet(9MB)           HuggingFace Xet 下载加速，字幕引擎不走 HF 大模型下载
#   PIL/_avif(7.5MB)      AVIF 解码，封面/字幕图片均为 jpg/png/webp
#   Qt6Qml / Qt6Quick(8.2MB)  QML 运行时（v1.18.0 追加；PySide6 迁移时按
#     Qt6 命名同步改名，见下方长注释）
_DROP_BINARIES = ('opengl32sw.dll', 'hf_xet', '_avif',
                  'qt6qml.dll', 'qt6quick.dll', 'qt6qmlmodels.dll',
                  'qt6qmlmeta.dll', 'qt6qmlworkerscript.dll',
                  # 2026-10-20 启动专项（<5s）：**零引用大文件**摘除。
                  #   src/ 与 tools\python\...\videocaptioner\ 全量 grep
                  #   `QtMultimedia|QMediaPlayer|QCamera|QAudio|QtPrint|
                  #   QtPdf|QPdf|QPrinter` → 零命中；本项目与引擎都是
                  #   纯 QtWidgets 栈（mpv 走 libmpv-2.dll，不经过
                  #   QtMultimedia）。这些 DLL/插件是 PyInstaller 的 PySide6
                  #   hook 按发行版整体带入的死重，onefile 每次启动都要
                  #   解压 + 过三套杀毒（360 / 联想 / Defender），纯付之东流。
                  #   · avcodec-63.dll(13.5M) + avformat-63(2.7M) +
                  #     swscale-10(1.2M) + avutil-61(1.1M) + swresample-7(0.2M)
                  #     = QtMultimedia 的 FFmpeg 族 ≈18.7M
                  #   · Qt6Multimedia(1.3M) + QtMultimediaWidgets(0.2M)
                  #   · Qt6Pdf.dll(4.4M)   —— 无打印/PDF 需求
                  #   · Qt6VirtualKeyboard(0.4M) —— 桌面端输入法场景用不到
                  #   · plugins/multimedia/ffmpegmediaplugin +
                  #     windowsmediaplugin(1.0M)
                  #   · qtiff(0.95M)——封面/字幕图片只有 jpg/png/webp
                  #   · qdirect2d(1.0M)——qwindows 才是主平台插件
                  #   合计 ≈28M / 16 个文件，解包与 AV 扫描同步受益。
                  'qt6multimedia.dll', 'qt6multimediawidgets.dll',
                  'qt6virtualkeyboard.dll', 'qt6pdf.dll',
                  'avcodec-', 'avformat-', 'avutil-', 'swscale-',
                  'swresample-',
                  'ffmpegmediaplugin', 'windowsmediaplugin',
                  'qtiff', 'qdirect2d')
# ⚠⚠ v1.18.0 追加 QML 三件套的原因（**不是为了省体积，是被硬限逼的**）：
#   在线安装器要把组件仓库发布到 gh-pages，而 **GitHub 单文件硬限 100 MiB**。
#   本轮 exe 因引入 onnxruntime 涨到 106,281,428 字节 ⇒ `1.18.0content.7z`
#   （该归档基本就是 exe 本身）变成 101.3 MiB，**超限 1.3 MiB，git push 必被拒**。
#   而 exe 是 PyInstaller onefile（内部已 zlib 压缩）⇒ 7z 只能再压 0.06%，
#   换压缩级别完全救不回来。故只能真减内容。
#   可安全剔除的依据（已逐项核过，不是猜的）：
#     · `src\` 与 `tools\python\Lib\site-packages\videocaptioner\` 全量 grep
#       `QtQuick|QtQml|QQmlApplicationEngine|QQuickView|QtQmlModels` → **零命中**；
#       整个 site-packages 里只有 PyInstaller 自己的工具链代码提到这些名字。
#     · 本项目与字幕引擎都是 qfluentwidgets（纯 QtWidgets），**不用 QML**。
#     · 依赖方向是 Qt6Quick → Qt6Widgets/Qt6Gui/Qt6Qml，保留的 DLL 不反向依赖它们，
#       所以删掉不会连累保留下来的 Qt6Widgets/Qt6Gui/Qt6Core。
#     · PySide6 的 `QtQml.pyd` / `QtQuick.pyd` 本来就没被 PyInstaller 收进来
#       （没人 import），这几份 DLL 是 hook 按 Qt 发行版整体带进来的死重。
#   ⚠ 别顺手把 libGLESv2.dll / d3dcompiler_47.dll 也删了 —— 那是 ANGLE，
#     Qt6 在 Windows 上可能真的在用（spec 已删 opengl32sw 软件回退），删了会黑屏。
#   ⚠ 这层「100 MiB 墙」是结构性的：exe 再涨 3~4MB 就会再次越线。
#     真要治本得把组件仓库改挂 GitHub Releases（单 asset 上限 2GB），见开发版说明书 6.x。
a.binaries = [b for b in a.binaries
              if not any(d in os.path.basename(b[0]).lower() or d in b[0].lower()
                         for d in _DROP_BINARIES)]

# ⚠⚠ 2026-10-20 教训（先记后改）：曾在此过滤全部 *.dist-info + setuptools
#   （想省 ~77 个文件的解包与杀毒耗时 ≈0.4s），结果 **v2.4.1 构建③的引擎
#   预热线程 import=fail**——click/fsspec/httpx2/huggingface_hub/pydantic 等
#   多个包在 import 期用 importlib.metadata 读自己的版本/入口点，dist-info
#   一缺就 PackageNotFoundError，整条引擎导入链断掉，界面改走主线程同步
#   导入（冻结 ~10s）。dist-info 是**运行期依赖**，不是纯元数据——本过滤
#   已整体回滚。要省这里的时间，正确方向是减少「真的没人 import」的包，
#   而不是砍元数据。

# ⚠⚠⚠ v1.18.2 修：**旧版 Qt 目录里的 MSVC runtime 会顶掉 onnxruntime 的新版**
#   现象：安装版点「录入声纹」报
#     ImportError: DLL load failed while importing onnxruntime_pybind11_state:
#     动态链接库(DLL)初始化例程失败。
#   根因（PyQt5 时代实测）：exe 里同时存在**两套同名** MSVC runtime，且
#     `PyQt5\Qt5\bin` 在 DLL 搜索路径里**优先级高于 `_MEIPASS` 根目录**：
#       · PyQt5\Qt5\bin\MSVCP140.dll  = **14.26**（2020 年，Qt 自带）
#       · MSVCP140.dll（根目录）        = **14.50**（onnxruntime 依赖）
#     onnxruntime.dll（编译时链的是 14.50 的导出表）拿到 14.26 的实现 ⇒
#     符号版本不匹配 ⇒ DllMain 里就失败 ⇒ 报「初始化例程失败」而不是
#     「找不到 DLL」。⚠ 这跟上面注释担心的「pyd 被顶掉」是**两个**问题：
#     那次只解了 `onnxruntime_pybind11_state.pyd`，**onnxruntime.dll 本体
#     同样会被顶掉**，所以没修干净。
#   修法（不删文件、零体积代价）：把旧版 Qt 目录下那四个 MSVC DLL 的**内容**
#     换成根目录的新版 —— Qt 只用到运行时导出函数（memcpy/_vsnprintf 等），
#     新版对这些 ABI **完全向后兼容**；反向（旧版顶新版）才不安全。
#     已用 build/_ort_repro.py 在模拟 _MEIPASS 里双向验证：
#       场景A（现状）  → RESULT=FAIL（DLL load failed …初始化例程失败）
#       场景B（覆盖后）→ RESULT=OK  onnxruntime 1.29.0
#   ⚠ 关键前提：exe 根目录那份 14.50 **不是**从 site-packages 收集的
#     （`find site-packages -iname "*msvcp140*"` 只命中 PySide6 无关副本
#      与 numpy.libs 的 14.40），而是 PyInstaller 从 **Python 运行时目录**
#     收集的。所以不能写死某个 site-packages 路径，只能从 `a.binaries`
#     里按「目录为空 = _MEIPASS 根」筛出来，取它的**源路径**去复用。
#   PySide6 迁移后（2026-10-14 实测修正）：PySide6 的 wheel **确实自带** MSVC
#   runtime（PySide6\MSVCP140*.dll / VCRUNTIME*.dll 共 5 个，方案书初查只看了
#   Qt6 的 bin/lib 目录、漏了包根），且 shiboken6\ 下另有 4 个同名副本——扁平
#   布局下默认不进 DLL 搜索路径，但兜住所有已知布局更稳。判据覆盖两大目录：
_MSVC_DIR_PREFIXES = ('pyside6', 'shiboken6')
_MSVC_NAMES = {'msvcp140.dll', 'msvcp140_1.dll',
               'vcruntime140.dll', 'vcruntime140_1.dll'}
_root_msvc = {}
for _e in a.binaries:
    _n = os.path.basename(_e[0]).lower()
    if _n in _MSVC_NAMES and not os.path.dirname(_e[0]).strip('/\\'):
        _root_msvc[_n] = _e[1]
print('[fix] 找到根目录新版 MSVC：%s'
      % ', '.join(sorted(os.path.basename(p) for p in _root_msvc.values())))
_patched = 0
for _i, _e in enumerate(a.binaries):
    _bn = os.path.basename(_e[0])
    _dir = os.path.dirname(_e[0]).replace('\\', '/').lower()
    if (_dir.split('/')[0] in _MSVC_DIR_PREFIXES
            and _bn.lower() in _root_msvc):
        a.binaries[_i] = (_e[0], _root_msvc[_bn.lower()], _e[2])
        _patched += 1
print('[fix] PySide6/shiboken6 目录旧 MSVC runtime 已改指向根目录新版：%d 个' % _patched)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='视频工具箱',
    # v2.1.0：exe 文件自身的图标（资源管理器 / 任务栏 / 快捷方式）。
    # 见上方 APP_ICON 段注释——运行期 setWindowIcon 管不到这一段。
    icon=APP_ICON,
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
