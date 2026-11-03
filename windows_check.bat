@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0" || exit /b 1
if not exist "venv\Scripts\python.exe" (
    echo Run windows_install.bat first.
    pause
    exit /b 1
)
set PYTHONHOME=
set PYTHONPATH=
"venv\Scripts\python.exe" scripts\check_linux.py %*
set "CK_RESULT=%ERRORLEVEL%"
pause
exit /b %CK_RESULT%
