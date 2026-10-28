@echo off
rem @version 2.8.0
rem Video Toolbox launcher.
rem
rem Default: pythonw.exe + start -> the console closes immediately and the
rem window appears as soon as Qt is ready. Debug mode keeps the console and
rem prints the entry-script mtimes:
rem     VideoToolbox.bat debug
rem Force a full __pycache__ purge:
rem     VideoToolbox.bat purgeall
rem
rem NOTE: keep this file ASCII-only. cmd.exe parses .bat bytes with the OEM
rem codepage (GBK on zh-CN) BEFORE `chcp 65001` takes effect; non-ASCII comments
rem saved as UTF-8 would corrupt following `set` lines and break startup.
setlocal
set "SRC=%~dp0"
set "ROOT=%~dp0.."
set "PY=%ROOT%\tools\python\python.exe"
set "PYW=%ROOT%\tools\python\pythonw.exe"
if not exist "%PY%" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not exist "%PYW%" set "PYW=%PY%"

set "MODE=run"
set "_PURGEALL="

:parse
if /i "%~1"=="debug" goto set_debug
if /i "%~1"=="purgeall" goto set_purge
goto parsed

:set_debug
set "MODE=debug"
shift
goto parse

:set_purge
set "_PURGEALL=1"
shift
goto parse

:parsed
if defined _PURGEALL (
    if exist "%SRC%__pycache__" rd /s /q "%SRC%__pycache__" 2>nul
)

set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

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
if /i "%MODE%"=="debug" (
    chcp 65001 >nul
    for %%t in ("%SRC%video_toolbox_qt.py") do echo [launcher] entry modified %%~tt
    "%PY%" "%SRC%video_toolbox_qt.py" %ARGS%
    if errorlevel 1 pause
    endlocal
    exit /b 0
)

if not exist "%PY%" (
    echo [launcher] Python runtime not found: %PY%
    pause
    endlocal
    exit /b 1
)

rem Fire-and-forget: pythonw has no console, so the batch can exit at once.
start "" "%PYW%" "%SRC%video_toolbox_qt.py" %ARGS%
endlocal
exit /b 0
