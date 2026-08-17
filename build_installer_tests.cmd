@echo off
setlocal
set "CSC=%SystemRoot%\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
if not exist "%CSC%" set "CSC=%SystemRoot%\Microsoft.NET\Framework\v4.0.30319\csc.exe"
if not exist "%CSC%" (
    echo csc.exe was not found.
    exit /b 1
)

"%CSC%" /nologo /target:exe /optimize+ /out:EchoPostureInstallerTests.exe ^
  /reference:System.Core.dll /reference:System.Web.Extensions.dll ^
  /reference:System.IO.Compression.dll /reference:System.IO.Compression.FileSystem.dll ^
  launcher\EchoPostureInstallerCore.cs launcher\EchoPostureInstallerTests.cs
if errorlevel 1 exit /b 1

EchoPostureInstallerTests.exe
if errorlevel 1 exit /b 1

"%CSC%" /nologo /target:winexe /optimize+ /out:EchoPostureInstallerCompileCheck.exe ^
  /reference:System.Windows.Forms.dll /reference:System.Drawing.dll /reference:System.Core.dll ^
  /reference:System.Web.Extensions.dll /reference:System.IO.Compression.dll ^
  /reference:System.IO.Compression.FileSystem.dll ^
  launcher\EchoPostureInstallerCore.cs launcher\EchoPostureInstaller.cs
if errorlevel 1 exit /b 1

echo INSTALLER UI COMPILE CHECK PASSED
exit /b 0
