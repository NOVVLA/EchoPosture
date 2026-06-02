@echo off
setlocal

set "VSWHERE=%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe"
if exist "%VSWHERE%" goto have_vswhere
echo vswhere.exe was not found.
exit /b 1
:have_vswhere

set "VSINFO=%TEMP%\echoposture_vs_path.txt"
"%VSWHERE%" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath > "%VSINFO%"
set /p VSINSTALL=<"%VSINFO%"
del "%VSINFO%" >nul 2>nul
if defined VSINSTALL goto have_vsinstall
echo Visual Studio C++ Build Tools were not found.
exit /b 1
:have_vsinstall

set "VCVARS=%VSINSTALL%\VC\Auxiliary\Build\vcvars64.bat"
if exist "%VCVARS%" goto have_vcvars
echo vcvars64.bat was not found: "%VCVARS%"
exit /b 1
:have_vcvars

set "PATH=%SystemRoot%\System32;%SystemRoot%;%SystemRoot%\System32\Wbem"
call "%VCVARS%" >nul
if errorlevel 1 exit /b 1

cl /nologo /std:c++17 /EHsc /O2 /W4 /DUNICODE /D_UNICODE ^
    /Fe:BlurOverlayHost.exe native\BlurOverlayHost.cpp ^
    /link d3d11.lib dxgi.lib dcomp.lib d3dcompiler.lib user32.lib gdi32.lib dxguid.lib
if errorlevel 1 exit /b 1

exit /b 0
