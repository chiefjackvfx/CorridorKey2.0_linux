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
"venv\Scripts\python.exe" scripts\update_cli.py
if errorlevel 1 (
    pause
    exit /b 1
)
