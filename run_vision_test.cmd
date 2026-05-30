@echo off
set "ECHOPOSTURE_ROOT=C:\Users\aaabb\Documents\ICC"
if not exist "%ECHOPOSTURE_ROOT%\runtime\python311\python.exe" (
    set "ECHOPOSTURE_ROOT=%~dp0"
)
cd /d "%ECHOPOSTURE_ROOT%"
runtime\python311\python.exe vision_test.py %*
