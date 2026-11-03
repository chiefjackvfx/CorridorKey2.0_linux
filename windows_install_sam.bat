@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0" || exit /b 1
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%CD%\setup_runtime.ps1" --sam --skip-weights %*
if errorlevel 1 (
    pause
    exit /b 1
)
echo Select your user-supplied SAM 3.1 checkpoint in the hint editor.
