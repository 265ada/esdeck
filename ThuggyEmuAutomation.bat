@echo off
rem ===========================================================================
rem  ThuggyEmuAutomation - the only file you need.
rem
rem  Keep this one shortcut. Every time it opens it checks GitHub, updates
rem  itself and the other .bat files if anything is newer, and then offers a
rem  menu. Nothing to re-download by hand, ever.
rem
rem  Optional:  --no-update   skip the update check (offline, or in a hurry)
rem ===========================================================================
setlocal enabledelayedexpansion
title ThuggyEmuAutomation
cd /d "%~dp0"

set "OPT_NOUPDATE="
for %%a in (%*) do if /i "%%~a"=="--no-update" set "OPT_NOUPDATE=1"

set "PY="
where python >nul 2>&1 && set "PY=python"
if not defined PY where py >nul 2>&1 && set "PY=py"
if not defined PY (
    cls
    echo.
    echo   Python is not installed yet.
    echo.
    echo   Run esdeck.bat first - it installs everything this needs.
    echo.
    pause >nul
    exit /b 1
)
set "ESDECK=%PY% -m esdeck"

%ESDECK% check-setup >nul 2>&1
set "IS_SETUP=%errorlevel%"

rem ------------------------------------------------------------- update ---
if not defined OPT_NOUPDATE (
    cls
    echo.
    echo   Checking for updates...
    echo.
    %ESDECK% update --yes --bat-dir "%~dp0."
    echo.
    timeout /t 2 >nul
)

:menu
cls
echo.
echo   ===========================================================
echo     ThuggyEmuAutomation
for /f "delims=" %%v in ('%ESDECK% --version 2^>nul') do echo     %%v
echo   ===========================================================
echo.
if "%IS_SETUP%"=="0" (
    for /f "delims=" %%r in ('%ESDECK% drives --current 2^>nul') do echo     Games folder: %%r
) else (
    echo     This PC is not set up yet - start with option 1.
)
echo.
echo     1.  Set up this PC          ^(install everything^)
echo     2.  Sort games              ^(from your Incoming folder^)
echo     3.  Fix library             ^(remove artwork, fix controller^)
echo     4.  Undo the last sort
echo     5.  Check for problems      ^(doctor^)
echo     6.  Free space              ^(delete verified Incoming copies^)
echo     7.  Open the Games folder
echo.
echo     0.  Exit
echo.
set "PICK="
set /p "PICK=  Choose: "

if "%PICK%"=="1" goto :setup
if "%PICK%"=="2" goto :sort
if "%PICK%"=="3" goto :fix
if "%PICK%"=="4" goto :undo
if "%PICK%"=="5" goto :doctor
if "%PICK%"=="6" goto :free
if "%PICK%"=="7" goto :openfolder
if "%PICK%"=="0" goto :bye
goto :menu

:setup
cls
if not exist "pyproject.toml" (
    echo.
    echo   Setup needs the full download, not just this launcher.
    echo   Put this file in the folder you unzipped from GitHub.
    goto :back
)
call esdeck.bat --no-pause
goto :back

:sort
cls
call sort-games.bat --no-pause
goto :back

:fix
cls
call fix-library.bat --no-pause
goto :back

:undo
cls
echo.
%ESDECK% undo
echo.
set "GO="
set /p "GO=  Undo it? [y/N] "
if /i "%GO%"=="y" %ESDECK% undo --yes
goto :back

:doctor
cls
echo.
%ESDECK% doctor
goto :back

:free
cls
call fix-library.bat --no-pause
goto :back

:openfolder
for /f "delims=" %%r in ('%ESDECK% drives --current 2^>nul') do start "" "%%r"
goto :menu

:back
echo.
echo   Press any key to return to the menu.
pause >nul
goto :menu

:bye
endlocal
exit /b 0
