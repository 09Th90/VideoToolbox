﻿Add-Type -AssemblyName System.Windows.Forms,System.Drawing
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
$target = Get-Process -Name "python" | Where-Object { $_.MainWindowTitle -like "*视频工具箱*" } | Select-Object -First 1
if (-not $target) { throw "no window" }
$h = $target.MainWindowHandle
[W]::ShowWindow($h, 9) | Out-Null
[W]::MoveWindow($h, 0, 0, 1180, 1040, $true) | Out-Null
[W]::SetForegroundWindow($h) | Out-Null
Start-Sleep -Milliseconds 1000
$b = New-Object System.Drawing.Bitmap 1180, 1040
$g = [System.Drawing.Graphics]::FromImage($b)
$g.CopyFromScreen(0, 0, 0, 0, $b.Size)
$b.Save("F:\Kimi Work\视频工具箱\build\upload_tab_v17.png", [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $b.Dispose()
Write-Host ("SAVED pid=" + $target.Id)
