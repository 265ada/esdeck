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

rem /win32icon sets the icon on the file. The title-bar icon is a
rem separate thing, so the same .ico is embedded to be loaded at run time.
set "ICONRES="
if exist "assets\ThuggyEmuAutomation.ico" set "ICONRES=/resource:assets\ThuggyEmuAutomation.ico,appicon.ico"

rem Embed the wallpaper so the .exe needs nothing beside it.
set "RESOPT="
if exist "assets\background.jpg" set "RESOPT=/resource:assets\background.jpg,background.jpg"

rem Stamp the version in from the one place it is kept, so the application
rem and the code it drives can never disagree without saying so. An app
rem older than its esdeck does not warn about steps it has never heard of -
rem they simply do not run, and everything else reports success.
set "VER="
for /f tokens^=2^ delims^=^" %%v in ('findstr /b /c:"__version__" "esdeck\__init__.py"') do set "VER=%%v"
if not defined VER set "VER=unknown"
> "Version.cs" echo namespace ThuggyEmuAutomation { internal static class Build { public const string Version = "%VER%"; } }
echo  Version %VER%

echo  Building ThuggyEmuAutomation.exe ...
"%CSC%" /nologo /target:winexe /optimize+ ^
    /out:ThuggyEmuAutomation.exe %ICONOPT% %ICONRES% %RESOPT% ^
    /reference:System.dll ^
    /reference:System.Drawing.dll ^
    /reference:System.Windows.Forms.dll ^
    ThuggyEmuAutomation.cs Version.cs
if errorlevel 1 (
    echo  [X] Build failed.
    echo.
    rem --no-pause has to hold here too, or an automated build hangs
    rem on the one path where it cannot report why.
    if not "%~1"=="--no-pause" pause >nul
    exit /b 1
)
echo  [ok] ThuggyEmuAutomation.exe
echo.
if not "%~1"=="--no-pause" (
    echo  Press any key to close this window.
    pause >nul
)
endlocal
