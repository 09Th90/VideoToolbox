@echo off
rem @version 1.13.0
rem Video Toolbox launcher - drag a link / .url shortcut / folder onto me
rem NOTE: keep this file ASCII-only. cmd.exe parses .bat bytes with the OEM
rem codepage (GBK on zh-CN) BEFORE `chcp 65001` takes effect; non-ASCII comments
rem saved as UTF-8 would corrupt following `set` lines and break startup.
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
rem Launcher lives in src\; app root is one level up. Prefer bundled tools\python.
set "ROOT=%~dp0.."
set "PY=%ROOT%\tools\python\python.exe"
if not exist "%PY%" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"

rem Re-quote every dropped argument. Expanding raw %* splits paths that contain
rem spaces / & / parentheses (e.g. a .url shortcut), producing "'xxx.url' is not
rem recognized". Strip existing quotes with %~1 and add one clean pair each.
set "ARGS="
:collect
if "%~1"=="" goto run
set "ARGS=%ARGS% "%~1""
shift
goto collect

:run
if exist "%PY%" (
  "%PY%" "%~dp0video_toolbox_qt.py" %ARGS%
) else (
  py -3 "%~dp0video_toolbox_qt.py" %ARGS%
)
if errorlevel 1 pause
