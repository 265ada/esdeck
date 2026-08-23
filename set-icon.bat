@echo off
rem ===========================================================================
rem  Replace the ThuggyEmuAutomation icon with your own picture.
rem
rem  Drag a square PNG onto this file, or run:
rem      set-icon.bat "C:\path\to\picture.png"
rem
rem  The picture is cropped to the circle that fits inside it, everything
rem  outside that circle is made transparent (so a black background
rem  disappears), and the Desktop shortcut is rebuilt with the new icon.
rem ===========================================================================
setlocal
title ThuggyEmuAutomation - set icon
cd /d "%~dp0"

set "SRC=%~1"
set "OPT_NOPAUSE="
if /i "%~2"=="--no-pause" set "OPT_NOPAUSE=1"
if not defined SRC (
    echo.
    echo   Drag a PNG onto this file, or run:
    echo       set-icon.bat "C:\path\to\picture.png"
    echo.
    pause >nul
    exit /b 1
)
if not exist "%SRC%" (
    echo.
    echo   Cannot find: %SRC%
    echo.
    pause >nul
    exit /b 1
)

set "PY="
where python >nul 2>&1 && set "PY=python"
if not defined PY where py >nul 2>&1 && set "PY=py"
if not defined PY (
    echo   Python is not installed. Run esdeck.bat first.
    pause >nul
    exit /b 1
)

echo.
echo   Making a circular icon from: %~nx1
echo.

rem Keep the source with the project so future setups reuse it.
if not exist "assets" mkdir "assets"
copy /y "%SRC%" "assets\ThuggyEmuAutomation.png" >nul

set "DESKTOP=%USERPROFILE%\Desktop"
if not exist "%DESKTOP%" set "DESKTOP=%USERPROFILE%\OneDrive\Desktop"

%PY% -m esdeck icon "assets\ThuggyEmuAutomation.png" ^
    --dest "%DESKTOP%\ThuggyEmuAutomation.ico" ^
    --shortcut "%DESKTOP%\ThuggyEmuAutomation.bat"
echo.
echo   If the Desktop icon still looks old, press F5 on the Desktop -
echo   Windows caches shortcut icons.
echo.
if not defined OPT_NOPAUSE (
    echo   Press any key to close this window.
    pause >nul
)
endlocal
