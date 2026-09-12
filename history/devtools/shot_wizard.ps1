Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Set-Location "F:\Kimi Work\视频工具箱"

function Shot($path) {
  $b = [System.Windows.Forms.SystemInformation]::VirtualScreen
  $bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.CopyFromScreen($b.Left, $b.Top, 0, 0, $bmp.Size)
  $bmp.Save($path, [System.Drawing.Imaging.ImageFormat]::Png)
 $g.Dispose(); $bmp.Dispose()
}

$exe = "F:\Kimi Work\视频工具箱\installer\_编译验证临时包.exe"
$p = Start-Process -FilePath $exe -PassThru
Start-Sleep -Seconds 5
Shot "F:\Kimi Work\视频工具箱\_installer_check\wizard_1_lang.png"
# 语言对话框默认第一项即简体中文，回车进入
[System.Windows.Forms.SendKeys]::SendWait("{ENTER}")
Start-Sleep -Seconds 4
Shot "F:\Kimi Work\视频工具箱\_installer_check\wizard_2_welcome.png"
# Alt+F4 退出向导（若有退出确认再回车）
[System.Windows.Forms.SendKeys]::SendWait("%{F4}")
Start-Sleep -Seconds 1
[System.Windows.Forms.SendKeys]::SendWait("{ENTER}")
Start-Sleep -Seconds 1
# 兜底：结束安装向导进程
Get-Process | Where-Object { $_.Path -eq $exe } | Stop-Process -Force -ErrorAction SilentlyContinue
Write-Host "done"
