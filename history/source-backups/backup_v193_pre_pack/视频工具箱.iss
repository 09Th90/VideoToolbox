; ============================================================================
; 视频工具箱 v1.9.1 —— Inno Setup 安装包脚本
; 构建前提：已执行 pyinstaller 视频工具箱.spec，产物位于 dist\视频工具箱.exe
; 编译：ISCC.exe 视频工具箱.iss  →  installer\视频工具箱_Setup_v1.9.1.exe
; v1.7：默认安装到 D 盘；按功能分目录——顶层只放主程序，tools 运行时、src 源码、
;       docs 文档、data 用户数据、logs 日志；识别模型/登录态/日志/任务均不进包。
; ============================================================================

#define MyAppName "视频工具箱"
#define MyAppVersion "1.9.1"
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
OutputBaseFilename=视频工具箱_Setup_v1.7
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
; —— 采用"白名单"逐条列举：凡未在此处出现的目录（asr_model 模型、data 用户数据、
;    logs 日志）都不会进入安装包，从源头杜绝账号凭据或超大模型被分发。 ——
; 主程序（PyInstaller 单文件 exe）——安装后程序目录顶层唯一可执行文件
Source: "dist\视频工具箱.exe"; DestDir: "{app}"; Flags: ignoreversion
; 下载与剪辑工具（压缩二进制，不再二次压缩，省时）
Source: "tools\ffmpeg.exe"; DestDir: "{app}\tools"; Flags: ignoreversion nocompression
Source: "tools\ffprobe.exe"; DestDir: "{app}\tools"; Flags: ignoreversion nocompression
Source: "tools\yt-dlp.exe"; DestDir: "{app}\tools"; Flags: ignoreversion nocompression
; 内嵌 Python 运行时（faster-whisper + playwright，字幕/投稿开箱可用）；排除字节码缓存瘦身
Source: "tools\python\*"; DestDir: "{app}\tools\python"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.pyc,__pycache__"
; 内嵌 Chromium 内核（B站投稿用）——二进制为主，免压缩加快打包
Source: "tools\ms-playwright\*"; DestDir: "{app}\tools\ms-playwright"; Flags: ignoreversion recursesubdirs createallsubdirs nocompression; Excludes: "*.pyc,__pycache__"
; 投稿引擎源码（v1.7 含分区/话题自动检测模块 catalog.py）
Source: "tools\uploader_src\*"; DestDir: "{app}\tools\uploader_src"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.pyc,__pycache__"
; 源代码 / 脚本启动器统一归入 src\（供脚本方式运行与查阅）
Source: "src\video_toolbox.py"; DestDir: "{app}\src"; Flags: ignoreversion
Source: "src\video_toolbox_gui.py"; DestDir: "{app}\src"; Flags: ignoreversion
Source: "src\asr_subtitle_worker.py"; DestDir: "{app}\src"; Flags: ignoreversion
Source: "src\视频工具箱.bat"; DestDir: "{app}\src"; Flags: ignoreversion
; 文档资料统一归入 docs\
Source: "docs\使用说明.txt"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "docs\界面预览.png"; DestDir: "{app}\docs"; Flags: ignoreversion

[Dirs]
; 识别模型目录预建空壳，用户按界面提示把下载的文件放进来即可
Name: "{app}\tools\asr_model"
; 用户数据目录空壳（下载/配置/缩略图/B站登录态/投稿任务/分区缓存）
Name: "{app}\data\downloads"
Name: "{app}\data\thumb_cache"
Name: "{app}\data\uploader_profile"
Name: "{app}\data\uploader_tasks"
Name: "{app}\data\catalog"
; 日志目录空壳（投稿日志与失败截图）
Name: "{app}\logs\uploader\screenshots"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; uploader_src 是纯引擎源码目录（已禁用运行时写字节码、不写任何用户数据），
; 卸载时整体删除可消除递归通配遗留的空目录壳；[UninstallDelete] 先于标准删除
; 执行，故必须用 filesandordirs 而非 dirifempty。
; 注意：绝不对 {app}\tools 整体使用 filesandordirs——其中 asr_model 存放用户
; 自行下载的识别模型，不能随卸载删除。
Name: "{app}\tools\uploader_src"; Type: filesandordirs
