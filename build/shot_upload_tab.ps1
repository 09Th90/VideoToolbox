# 启动 GUI -> 切到投稿页 -> 置前截图 -> 关闭（按窗口标题定位真实进程）
$ErrorActionPreference = "Stop"
$root = "F:\Kimi Work\视频工具箱"
$py = Join-Path $root "tools\python\python.exe"
$gui = Join-Path $root "src\video_toolbox_gui.py"
$env:VT_SHOT_TAB = "upload"
Start-Process -FilePath $py -ArgumentList @("-X","utf8",$gui) | Out-Null
Start-Sleep -Seconds 4
Add-Type -AssemblyName System.Windows.Forms,System.Drawing
$sig = @'
using System;
using System.Runtime.InteropServices;
public class W {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
  [DllImport("user32.dll")] public static extern bool MoveWindow(IntPtr h,int x,int y,int w,int ht,bool r);
}
'@
Add-Type $sig
$target = $null
foreach ($pr in (Get-Process -Name "python" -ErrorAction SilentlyContinue)) {
  if ($pr.MainWindowTitle -like "*视频工具箱*") { $target = $pr; break }
}
if (-not $target) { throw "未找到 GUI 窗口" }
$h = $target.MainWindowHandle
[W]::ShowWindow($h, 9) | Out-Null
[W]::MoveWindow($h, 0, 0, 1180, 880, $true) | Out-Null
[W]::SetForegroundWindow($h) | Out-Null
Start-Sleep -Milliseconds 900
$b = New-Object System.Drawing.Bitmap 1180, 880
$g = [System.Drawing.Graphics]::FromImage($b)
$g.CopyFromScreen(0, 0, 0, 0, $b.Size)
$out = Join-Path $root "build\upload_tab_v17.png"
$b.Save($out, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $b.Dispose()
Stop-Process -Id $target.Id -Force
Write-Host "SAVED $out"
