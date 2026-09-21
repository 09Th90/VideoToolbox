@echo off
rem @version 1.15.7
rem ============================================================
rem  Restart Video Toolbox so that the edits in src\ take effect.
rem
rem  Why this file exists:
rem  python imports every module ONCE, at startup. If a window is already
rem  open it keeps running the code from the moment it was launched, so
rem  editing a .py file changes nothing in that window. That stale window is
rem  the usual reason a fix appears to "not work".
rem
rem  The launcher itself (src\VideoToolbox.bat, Chinese file name) already
rem  warns about this. This wrapper just makes it one double-click.
rem ============================================================
setlocal
set "HERE=%~dp0"

echo.
echo   ============================================================
echo    Restart Video Toolbox
echo   ============================================================
echo.
echo    Step 1: if a Video Toolbox window is still open, close it now.
echo            (an old window keeps running the old code)
echo.
echo    Step 2: this script then launches a fresh instance.
echo.

tasklist /fi "imagename eq python.exe" /nh 2>nul | find /i "python.exe" >nul
if errorlevel 1 goto launch

echo    ------------------------------------------------------------
echo    A python.exe is running right now.
echo    If that is the Video Toolbox window, close it, THEN press a key.
echo    (this script does NOT kill it automatically: python.exe may well
echo     be some other script of yours)
echo    ------------------------------------------------------------
pause >nul

:launch
echo.
echo    Starting ...
for %%F in ("%HERE%src\*.bat") do start "" "%%~fF"
echo    Done.
echo.
