@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0" || exit /b 1
if exist "runtime_setup.py" goto setup
where git >nul 2>&1
if errorlevel 1 goto missinggit
set "CK_TARGET=%~1"
if not defined CK_TARGET set "CK_TARGET=%~dp0CorridorKey2.0"
if exist "%CK_TARGET%\.git" goto existing
if exist "%CK_TARGET%" for /f "delims=" %%I in ('dir /b /a "%CK_TARGET%" 2^>nul') do goto occupied
git clone --branch master https://github.com/chiefjackvfx/CorridorKey2.0.git "%CK_TARGET%"
if errorlevel 1 goto failed
:existing
cd /d "%CK_TARGET%" || goto failed
:setup
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%CD%\setup_runtime.ps1"
if errorlevel 1 goto failed
echo Installed. Launch with windows_run.bat. Use windows_install_sam.bat for optional SAM.
exit /b 0
:occupied
echo Target must be a new folder or an existing CK2 checkout.
goto failed
:missinggit
echo Install Git for Windows, then retry.
:failed
echo Install failed. Review the error above and run Install / Repair again.
pause
exit /b 1
