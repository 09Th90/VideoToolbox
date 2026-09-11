; ============================================================================
; 视频工具箱 v1.10.3 —— Inno Setup 安装包脚本
; 构建前提：已用 tools\python 执行 pyinstaller 视频工具箱.spec，
;           产物位于 dist\视频工具箱.exe
; 编译：ISCC.exe 视频工具箱.iss  →  installer\视频工具箱_Setup_v1.10.3.exe
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
#define MyAppVersion "1.10.3"
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
ShowLanguageDialog=yes
LanguageDetectionMethod=none

[Languages]
; 简体中文语言文件随项目存放（便携版编译器 Languages 目录不带中文），相对本 iss 解析
Name: "chinesesimp"; MessagesFile: "build\Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

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
; 下载与剪辑工具（压缩二进制，不再二次压缩，省时）
Source: "tools\ffmpeg.exe"; DestDir: "{app}\tools"; Flags: ignoreversion nocompression
Source: "tools\ffprobe.exe"; DestDir: "{app}\tools"; Flags: ignoreversion nocompression
Source: "tools\yt-dlp.exe"; DestDir: "{app}\tools"; Flags: ignoreversion nocompression
; 内嵌 Python 运行时（VideoCaptioner 字幕引擎及其依赖随包分发，开箱可用）；
; 排除字节码缓存瘦身
Source: "tools\python\*"; DestDir: "{app}\tools\python"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.pyc,__pycache__"
; AI 客户端（仅标准库）：字幕/标题语言识别用（v1.10.1 起投稿板块已移除）
Source: "tools\ai_client.py"; DestDir: "{app}\tools"; Flags: ignoreversion
; 源代码 / 脚本启动器统一归入 src\（供脚本方式运行与查阅）
Source: "src\video_toolbox.py"; DestDir: "{app}\src"; Flags: ignoreversion
Source: "src\video_toolbox_qt.py"; DestDir: "{app}\src"; Flags: ignoreversion
Source: "src\视频工具箱.bat"; DestDir: "{app}\src"; Flags: ignoreversion
; 文档资料统一归入 docs\
Source: "docs\使用说明.txt"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "docs\界面预览.png"; DestDir: "{app}\docs"; Flags: ignoreversion
; 第三方组件合规声明：VideoCaptioner（GPL-3.0）许可全文与组件来源
Source: "docs\VideoCaptioner_GPL-3.0.txt"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "docs\VideoCaptioner_组件来源.txt"; DestDir: "{app}\docs"; Flags: ignoreversion

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
