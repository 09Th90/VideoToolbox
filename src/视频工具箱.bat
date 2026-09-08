@echo off
rem Video Toolbox launcher - drag a link / .url shortcut / folder onto me
chcp 65001 >nul
set PYTHONUTF8=1
rem v1.7：本启动器位于 src\，程序根为其上一级；优先用根目录内嵌运行时 tools\python
set "ROOT=%~dp0.."
set "PY=%ROOT%\tools\python\python.exe"
if not exist "%PY%" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if exist "%PY%" (
  "%PY%" "%~dp0video_toolbox_gui.py" %*
) else (
  py -3 "%~dp0video_toolbox_gui.py" %*
)
if errorlevel 1 pause
