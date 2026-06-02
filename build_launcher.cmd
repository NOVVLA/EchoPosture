@echo off
setlocal
call build_blur_overlay_host.cmd
if errorlevel 1 exit /b 1

set "CSC=%SystemRoot%\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if not exist "%CSC%" set "CSC=%SystemRoot%\Microsoft.NET\Framework\v4.0.30319\csc.exe"
if not exist "%CSC%" (
    echo csc.exe was not found.
    exit /b 1
)

"%CSC%" /nologo /target:winexe /optimize+ /out:EchoPosture.exe /reference:System.Windows.Forms.dll launcher\EchoPostureLauncher.cs
if errorlevel 1 exit /b 1

"%CSC%" /nologo /target:exe /define:CONSOLE_APP /optimize+ /out:EchoPostureSelfTest.exe /reference:System.Windows.Forms.dll launcher\EchoPostureLauncher.cs
if errorlevel 1 exit /b 1

exit /b 0
