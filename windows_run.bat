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
set QT_PLUGIN_PATH=
set QT_QPA_PLATFORM_PLUGIN_PATH=
"venv\Scripts\python.exe" -u -X faulthandler scripts\launch.py %*
if errorlevel 1 (
    echo CK2 exited with an error. Copy the output above when reporting it.
    pause
    exit /b 1
)
