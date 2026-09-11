// 组件安装脚本：创建用户数据/日志目录壳 + 开始菜单/桌面快捷方式
function Component()
{
}

Component.prototype.createOperations = function()
{
    component.createOperations();

    // 与 Inno 版 [Dirs] 保持一致的目录壳（用户数据、日志）
    component.addOperation("Mkdir", "@TargetDir@/data/downloads");
    component.addOperation("Mkdir", "@TargetDir@/data/thumb_cache");
    // VideoCaptioner 唤起时的工作目录（配置与日志写在 %LOCALAPPDATA%\VideoCaptioner）
    component.addOperation("Mkdir", "@TargetDir@/data/videocaptioner");

    // 开始菜单 + 桌面快捷方式；维护工具即卸载入口
    component.addOperation("CreateShortcut", "@TargetDir@/视频工具箱.exe", "@StartMenuDir@/视频工具箱.lnk");
    component.addOperation("CreateShortcut", "@TargetDir@/维护工具.exe", "@StartMenuDir@/卸载视频工具箱.lnk");
    component.addOperation("CreateShortcut", "@TargetDir@/视频工具箱.exe", "@DesktopDir@/视频工具箱.lnk");
}
