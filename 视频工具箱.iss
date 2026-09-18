; @version 1.15.0
; ============================================================================
; 视频工具箱 v1.15.0 —— Inno Setup 安装包脚本
; 构建前提：已用 tools\python 执行 pyinstaller 视频工具箱.spec，
;           产物位于 dist\视频工具箱.exe
; 编译：ISCC.exe 视频工具箱.iss  →  installer\视频工具箱_Setup_v1.15.0.exe
; v1.14.1（语言修正）：安装向导固定为简体中文——ShowLanguageDialog 改 no
;         （不再弹出语言选择框），[Languages] 移除 english 仅保留中文一项。
; v1.12.1：修复打包版「点退出后程序反复重启」（严重）——退出时的校准知识同步
;         原以 [sys.executable, "-c", ...] 派生子进程；冻结成单文件 exe 后
;         sys.executable 就是主程序自身，于是每次退出都拉起一个新 GUI 实例，
;         新旧实例互相抢占/删除 _MEI 临时目录，表现为退出后无限重启，并弹出
;         「Failed to remove temporary directory: _MEI***」与「no Qt platform
;         plugin could be initialized」错误框。现统一改用 system_python() /
;         _calib_py() / calib_ai_agent.resolve_python() 解析真实解释器，并以
;         _is_self_exe() 兜底：解析不到就跳过退出同步，绝不回退到 exe 自身。
; v1.12.0：翻译链路全面修缮——① 谷歌翻译改抓 Chrome 内置翻译同源免费接口
;         （translate_a/t?client=dict-chrome-ex）并加全局请求节流（≥0.12s/次）；
;         ② 必应翻译换 translatetext 端点取 token；
;         ③ 翻译基类对失败译文（ERROR/空/xxx||ERROR）不写缓存、块级可重试；
;         ④ LLM 翻译并发上限（_LLM_THREAD_CAP=5）与限流处理，防 429 刷屏；
;         ⑤ 取消任务立即停掉翻译/优化线程池；⑥ 关闭「启用 AI」时兜底不介入 LLM。
; v1.11.0：LLM 拆为两条各自独立的 API 通道（接口 A 工具箱 / 接口 B 字幕引擎与
;         AI 校准，地址、密钥、模型可分别填写）；新增全局 ASR 语音识别配置
;         （自有 ASR 服务或本地独立模型，自动写入引擎「转录配置」）；
;         字幕校准新增 Agent 级「AI 校准」开关与「再次校准」（新增
;         src\calib_ai_agent.py，随 exe 一起打包）；披露 diskcache 延迟化，
;         消除进入「字幕处理」页的数秒卡顿（本机实测构建 0.7s 级）。
; v1.10.8：设置收敛为唯一全局设置页（取消工具/引擎分段与独立引擎对话框），
;         LLM 配置全局化（工具箱与字幕引擎共用一套），引擎工作目录等默认
;         位置全部强制到软件文件夹（不再落 C 盘）；校准知识保持启动拉取合并、
;         退出先并再推的多用户对等并集同步（合并核心抽到 src\calib_merge_core.py）。
; v1.10.5：校准脚本升级为对象级知识库版本（新增 ENTITIES 对象层与
;         learn 学习系统，kb-lint/kb-export/kb-lookup 子命令）；
;         校准界面模式列表与脚本实际支持的全部 12 种模式对齐，移除
;         脚本已删除的「长句拆两行」开关；新增退出时自动同步校准脚本
;         到 GitHub（静默后台，直连失败回退内置代理，日志见
;         logs\calib_sync.log）。
; v1.10.4：界面与设置整合——左侧导航宽度按「最长项文字 + 2 个字符」自适应
;         （不再固定 322px）；新增导航底部「设置」页，工具设置与字幕引擎
;         设置统一入口（原「字幕处理」页右下「引擎设置…」对话框并入）；
;         跨屏拖拽按相对位置平滑移动（不再因两屏缩放比不同而瞬移）；
;         DPI 取整策略改为 PassThrough，各缩放比表现一致；字幕引擎界面
;         后台预热，消除首次进入「字幕处理」页的数秒卡顿。
; v1.10.3：字幕引擎内嵌界面收尾——品牌 logo/水印彻底隐藏、任务创建页大留白
;         收紧、新增「引擎设置…」入口（原独立窗口的设置页改对话框呈现，
;         隐藏上游关于组与推广卡片）；全局字体 9pt、页边距收紧；
;         打包环境改为 tools\python（此前误用系统 Python312，videocaptioner
;         未装进 exe，字幕页报 No module named 'httpx'）。
; v1.10.1：界面重写为 Fluent 风格（照搬 VideoCaptioner 布局）；移除「B站投稿」
;         板块——tools\uploader_src、tools\ms-playwright 不再进包，新增 tools\ai_client.py；
; v1.10.0：字幕链路替换为内置 VideoCaptioner v1.4.2（GPL-3.0）——
;         1) 移除 src\asr_subtitle_worker.py 与 tools\asr_model 模型引导；
; v1.10.2：字幕引擎内嵌进主程序 exe（界面内嵌呈现，不再唤起独立窗口）；
;         tools\python 里的引擎副本与随包 wheel 不再需要，升级时自动清理；
;         GPL-3.0 许可全文与组件来源仍存 docs\（第三方组件合规声明，必须保留）。
; v1.9.3：新增「字幕校准」——subtitle_calib_merged.py 安装到程序目录顶层，
;         由「字幕校准」页签用内嵌 tools\python 子进程调用（脚本不打包进 exe）。
; v1.7：默认安装到 D 盘；按功能分目录——顶层只放主程序，tools 运行时、src 源码、
;       docs 文档、data 用户数据、logs 日志；识别模型/登录态/日志/任务均不进包。
; ============================================================================ 

#define MyAppName "视频工具箱"
#define MyAppVersion "1.15.0"
#define MyAppPublisher "VideoToolbox"
#define MyAppExeName "视频工具箱.exe"

[Setup]
; 固定 AppId，保证后续版本可识别为同一程序进行升级/覆盖
AppId={{6C4E8D2F-3A9B-4E7C-B1D5-8F2A0C6E4D39}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} v{#MyAppVersion}
AppPublisher={#MyAppPublisher}
; v1.7：默认安装位置改为 D 盘（用户可在向导中自行更改）
DefaultDirName=D:\VideoToolbox
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=installer
OutputBaseFilename=视频工具箱_Setup_v{#MyAppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; 用户级安装：无需 UAC 提权（D 盘用户目录默认可写）
PrivilegesRequired=lowest
; 安装语言固定为简体中文：不弹语言选择框（ShowLanguageDialog=no 时
; Inno 直接采用 [Languages] 第一项），且语言列表仅保留中文一项
ShowLanguageDialog=no

[Languages]
; 简体中文语言文件随项目存放（便携版编译器 Languages 目录不带中文），相对本 iss 解析
Name: "chinesesimp"; MessagesFile: "build\Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; —— 采用"白名单"逐条列举：凡未在此处出现的目录（data 用户数据、logs 日志、
;    VideoCaptioner 用户配置）都不会进入安装包，从源头杜绝账号凭据被分发。 ——
; 主程序（PyInstaller 单文件 exe）——安装后程序目录顶层唯一可执行文件
Source: "dist\视频工具箱.exe"; DestDir: "{app}"; Flags: ignoreversion
; 字幕校准统一脚本（v1.9.3）：安装到程序目录顶层，「字幕校准」页签用
; tools\python 子进程按 {app}\subtitle_calib_merged.py 调用（不打包进 exe）
Source: "subtitle_calib_merged.py"; DestDir: "{app}"; Flags: ignoreversion
; 校准知识同步连接配置（内置统一入口：GitHub 代理规则 + vt-github 仓库参数）
Source: "github_proxy.yaml"; DestDir: "{app}"; Flags: ignoreversion
; 下载与剪辑工具（压缩二进制，不再二次压缩，省时）
Source: "tools\ffmpeg.exe"; DestDir: "{app}\tools"; Flags: ignoreversion nocompression
Source: "tools\ffprobe.exe"; DestDir: "{app}\tools"; Flags: ignoreversion nocompression
Source: "tools\yt-dlp.exe"; DestDir: "{app}\tools"; Flags: ignoreversion nocompression
; 内嵌 Python 运行时（VideoCaptioner 字幕引擎及其依赖随包分发，开箱可用）；
; 排除字节码缓存瘦身
Source: "tools\python\*"; DestDir: "{app}\tools\python"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.pyc,__pycache__"
; VideoCaptioner 纯代码 wheel 不含 resource（界面图片/字体/默认字幕样式/多语言）。
; 这些静态资源随包分发，内嵌引擎才能离线自包含、真正成为程序一部分（v1.10.8）。
Source: "tools\videocaptioner\resource\*"; DestDir: "{app}\tools\videocaptioner\resource"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.pyc,__pycache__"
; AI 客户端（仅标准库）：字幕/标题语言识别用（v1.10.1 起投稿板块已移除）
Source: "tools\ai_client.py"; DestDir: "{app}\tools"; Flags: ignoreversion
; 源代码 / 脚本启动器统一归入 src\（供脚本方式运行与查阅）
Source: "src\video_toolbox.py"; DestDir: "{app}\src"; Flags: ignoreversion
Source: "src\video_toolbox_qt.py"; DestDir: "{app}\src"; Flags: ignoreversion
; v1.11.0：新增源码——合并核心、AI 校准 Agent、官方实现一键套用脚本
Source: "src\calib_merge_core.py"; DestDir: "{app}\src"; Flags: ignoreversion
Source: "src\calib_ai_agent.py"; DestDir: "{app}\src"; Flags: ignoreversion
Source: "src\apply_vc_official.py"; DestDir: "{app}\src"; Flags: ignoreversion
Source: "src\视频工具箱.bat"; DestDir: "{app}\src"; Flags: ignoreversion
; 文档资料统一归入 docs\
Source: "docs\使用说明.txt"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "docs\界面预览.png"; DestDir: "{app}\docs"; Flags: ignoreversion
; 第三方组件合规声明：VideoCaptioner（GPL-3.0）许可全文与组件来源
Source: "docs\VideoCaptioner_GPL-3.0.txt"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "docs\VideoCaptioner_组件来源.txt"; DestDir: "{app}\docs"; Flags: ignoreversion
; v1.11.0：官方新版提示词与三个免费翻译器实现归档（重装 tools\python 后
; 用 src\apply_vc_official.py 一键恢复），以及程序说明书
; v1.12.1：这两个目录同样必须排除字节码缓存——docs\vc_translate_impl 下曾残留本机
;          Python 3.13 生成的 __pycache__\*.cpython-313.pyc 被一起打进安装包（随包运行时
;          是 3.12，这些缓存既非当前版本源码、版本也不匹配）。
Source: "docs\vc_prompts_official\*"; DestDir: "{app}\docs\vc_prompts_official"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.pyc,__pycache__"
Source: "docs\vc_translate_impl\*"; DestDir: "{app}\docs\vc_translate_impl"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.pyc,__pycache__"
Source: "docs\程序说明书.md"; DestDir: "{app}\docs"; Flags: ignoreversion

[Dirs]
; 用户数据目录空壳（下载/缩略图缓存）
Name: "{app}\data\downloads"
Name: "{app}\data\thumb_cache"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[InstallDelete]
; 升级安装时清理旧版本遗留（v1.10.2 起引擎已内嵌进 exe，这些不再需要）；
; data\、logs\ 等用户数据不受影响
Type: filesandordirs; Name: "{app}\tools\uploader_src"
Type: filesandordirs; Name: "{app}\tools\ms-playwright"
Type: filesandordirs; Name: "{app}\tools\asr_model"
Type: filesandordirs; Name: "{app}\tools\videocaptioner"
Type: filesandordirs; Name: "{app}\tools\python\Lib\site-packages\videocaptioner"
Type: files; Name: "{app}\src\asr_subtitle_worker.py"
Type: files; Name: "{app}\src\video_toolbox_gui.py"

[UninstallDelete]
; 无需额外清理：v1.10.1 起不再使用递归通配分发目录（投稿引擎已移除），
; [Files] 逐条列举的项卸载时由 Inno 标准删除流程处理。
; 注意：绝不对 {app}\tools 整体使用 filesandordirs——其中 python 运行时与
; 随包 wheel 之外的用户数据不能随卸载误删。
