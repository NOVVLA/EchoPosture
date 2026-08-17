@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\build_semi_portable_installer.ps1" %*
exit /b %errorlevel%
