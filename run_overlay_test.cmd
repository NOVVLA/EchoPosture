@echo off
cd /d "%~dp0"
runtime\python311\python.exe overlay_test.py %*
