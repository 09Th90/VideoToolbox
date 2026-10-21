@echo off
rem @version 2.5.0
rem Video Toolbox launcher.
rem
rem Design goal: whatever you save is what runs. The launcher therefore
rem   (1) purges src\__pycache__ on every start (only src - tools\python holds
rem       the third-party engine, its cache is huge and never needs purging),
rem   (2) prints the mtime of the entry scripts so you can tell at a glance
rem       which snapshot you are launching,
rem   (3) warns when another python.exe is already alive (that stale window
rem       is the usual reason "my change did not show up").
rem
rem NOTE: keep this file ASCII-only. cmd.exe parses .bat bytes with the OEM
rem codepage (GBK on zh-CN) BEFORE `chcp 65001` takes effect; non-ASCII comments
rem saved as UTF-8 would corrupt following `set` lines and break startup.
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set "SRC=%~dp0"
set "ROOT=%~dp0.."
set "PY=%ROOT%\tools\python\python.exe"
if not exist "%PY%" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"

rem ---- 1) purge stale bytecode (selective) --------------------------------
rem Python invalidates a .pyc by comparing mtimes, which is usually enough,
rem but it silently fails when the clock moved backwards, when files were
rem copied from another machine, or when an editor preserves mtime. Dropping
rem the whole cache every start made 35+ modules recompile each launch
rem (~0.1-0.3s), so now only entries whose source is newer or gone are
rem deleted; the rest stay warm. File timestamps are same-length on this
rem locale (yyyy/MM/dd HH:mm, zero-padded), so a GTR string compare detects
rem "source newer than the .pyc" safely; minute-precision ties are kept
rem (Python still validates the mtime+size embedded in the .pyc header).
rem Force the old full purge with:  VideoToolbox.bat purgeall
setlocal enabledelayedexpansion
set "_PURGEALL="
if /i "%~1"=="purgeall" (
    set "_PURGEALL=1"
    shift
)
if defined _PURGEALL goto nukeall
if exist "%SRC%__pycache__\*.pyc" for %%c in ("%SRC%__pycache__\*.pyc") do (
    set "n=%%~nc"
    set "n=!n:.cpython-312=!"
    if not exist "%SRC%!n!.py" (
        del "%%c" 2>nul
    ) else (
        for %%p in ("%SRC%!n!.py") do if "%%~tp" GTR "%%~tc" del "%%c" 2>nul
    )
)
goto purgedone
:nukeall
if exist "%SRC%__pycache__" rd /s /q "%SRC%__pycache__" 2>nul
:purgedone

rem ---- 2) say which snapshot is being launched ----------------------------
for %%t in ("%SRC%video_toolbox_qt.py") do echo [launcher] video_toolbox_qt.py  modified %%~tt
for %%t in ("%SRC%subtitle_editor.py") do echo [launcher] subtitle_editor.py    modified %%~tt
for %%t in ("%SRC%subtitle_overlay.py") do echo [launcher] subtitle_overlay.py   modified %%~tt

rem ---- 3) warn about an already-running instance --------------------------
rem The most common "my edit did not take effect" is really "I am looking at
rem the window I started ten minutes ago". Do not kill anything automatically
rem (python.exe may well be somebody else's script), just say so.
tasklist /fi "imagename eq python.exe" /nh 2>nul | find /i "python.exe" >nul
if not errorlevel 1 echo [launcher] note: a python.exe is already running - a stale window may still be open.

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
  "%PY%" "%SRC%video_toolbox_qt.py" %ARGS%
) else (
  py -3 "%SRC%video_toolbox_qt.py" %ARGS%
)
if errorlevel 1 pause
