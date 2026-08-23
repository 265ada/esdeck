@echo off
rem ===========================================================================
rem  Build ThuggyEmuAutomation.exe
rem
rem  Uses csc.exe, the C# compiler that ships with Windows, so there is no
rem  toolchain to install. The icon in assets/ is embedded into the .exe.
rem ===========================================================================
setlocal
cd /d "%~dp0"

set "CSC="
for %%d in (v4.0.30319 v3.5) do (
    if exist "%WINDIR%\Microsoft.NET\Framework64\%%d\csc.exe" (
        set "CSC=%WINDIR%\Microsoft.NET\Framework64\%%d\csc.exe"
    ) else if exist "%WINDIR%\Microsoft.NET\Framework\%%d\csc.exe" (
        set "CSC=%WINDIR%\Microsoft.NET\Framework\%%d\csc.exe"
    )
)
if not defined CSC (
    echo  [X] No C# compiler found. It normally ships with Windows at
    echo      %WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe
    echo.
    pause >nul
    exit /b 1
)

set "ICONOPT="
if exist "assets\ThuggyEmuAutomation.ico" set "ICONOPT=/win32icon:assets\ThuggyEmuAutomation.ico"

echo  Building ThuggyEmuAutomation.exe ...
"%CSC%" /nologo /target:winexe /optimize+ ^
    /out:ThuggyEmuAutomation.exe %ICONOPT% ^
    /reference:System.dll ^
    /reference:System.Drawing.dll ^
    /reference:System.Windows.Forms.dll ^
    ThuggyEmuAutomation.cs
if errorlevel 1 (
    echo  [X] Build failed.
    echo.
    pause >nul
    exit /b 1
)
echo  [ok] ThuggyEmuAutomation.exe
echo.
if not "%~1"=="--no-pause" (
    echo  Press any key to close this window.
    pause >nul
)
endlocal
