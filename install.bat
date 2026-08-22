@echo off
rem ===========================================================================
rem  esdeck first-run setup
rem
rem  Takes a fresh Windows machine to a working emulation setup:
rem  Python + ES-DE + RetroArch + 7-Zip, a sorted ROM library, a drop folder,
rem  and a Sort Games shortcut on the Desktop.
rem
rem  Safe to run more than once - every step checks before it acts.
rem ===========================================================================
setlocal enabledelayedexpansion
title esdeck setup
cd /d "%~dp0"

echo.
echo  ===========================================================
echo    esdeck setup
echo  ===========================================================
echo.

rem --------------------------------------------------------------- winget ---
where winget >nul 2>&1
if errorlevel 1 (
    echo  [X] winget is not available.
    echo      Install "App Installer" from the Microsoft Store, then re-run this.
    echo.
    pause
    exit /b 1
)
echo  [ok] winget found

rem --------------------------------------------------------------- python ---
set "PY="
where python >nul 2>&1 && set "PY=python"
if not defined PY where py >nul 2>&1 && set "PY=py"

if not defined PY (
    echo  [..] Python not found - installing it with winget
    winget install --id Python.Python.3.12 --exact --silent ^
        --accept-package-agreements --accept-source-agreements
    echo.
    echo  Python was installed, but this window cannot see it yet.
    echo  Close this window, open a new one, and run install.bat again.
    echo.
    pause
    exit /b 0
)
for /f "tokens=*" %%v in ('%PY% --version 2^>^&1') do echo  [ok] %%v

rem ---------------------------------------------------------------- paths ---
rem Arguments, in any order:
rem   install.bat [game folder] [--no-cores] [--common-cores] [--all-emulators]
rem                     [--repair]
rem By default every core esdeck knows about is downloaded.
set "GAMEROOT="
set "OPT_NOCORES="
set "OPT_COMMON="
set "OPT_ALLEMU="
set "OPT_REPAIR="
for %%a in (%*) do (
    set "ARG=%%~a"
    if /i "!ARG!"=="--no-cores"      set "OPT_NOCORES=1"
    if /i "!ARG!"=="--common-cores"  set "OPT_COMMON=1"
    if /i "!ARG!"=="--all-emulators" set "OPT_ALLEMU=1"
    if /i "!ARG!"=="--repair"        set "OPT_REPAIR=1"
    if not "!ARG:~0,2!"=="--" if not defined GAMEROOT set "GAMEROOT=!ARG!"
)
if defined GAMEROOT set "UNATTENDED=1"
if not defined GAMEROOT (
    echo.
    echo  Where should your games live? Two folders are created under it:
    echo      ^<folder^>\ROMs       the sorted library ES-DE reads
    echo      ^<folder^>\Incoming   where you drop new games
    echo.
    set /p "GAMEROOT=  Game folder [D:\Games]: "
)
if not defined GAMEROOT set "GAMEROOT=D:\Games"
if "%GAMEROOT%"=="" set "GAMEROOT=D:\Games"

set "ROMDIR=%GAMEROOT%\ROMs"
set "INCOMING=%GAMEROOT%\Incoming"

if not exist "%ROMDIR%"   mkdir "%ROMDIR%"
if not exist "%INCOMING%" mkdir "%INCOMING%"
echo  [ok] %ROMDIR%
echo  [ok] %INCOMING%

rem --------------------------------------------------------------- esdeck ---
echo.
echo  [..] Installing esdeck
%PY% -m pip install -e . --quiet --disable-pip-version-check
if errorlevel 1 (
    echo  [X] pip install failed. Scroll up for the reason.
    echo.
    pause
    exit /b 1
)
echo  [ok] esdeck installed

rem Use "python -m esdeck" throughout: the Scripts folder may not be on PATH
rem until a new shell is opened.
set "ESDECK=%PY% -m esdeck"

%ESDECK% init --rom-dir "%ROMDIR%" --source-dir "%INCOMING%" >nul
if errorlevel 1 (
    echo  [X] esdeck init failed.
    pause
    exit /b 1
)
echo  [ok] configured

rem ------------------------------------------------- emulators + ROM tree ---
echo.
echo  [..] Installing ES-DE, RetroArch and 7-Zip ^(this can take a few minutes^)
echo.
set "BOOTFLAGS=--yes"
if defined OPT_ALLEMU set "BOOTFLAGS=%BOOTFLAGS% --all-emulators"
if defined OPT_REPAIR set "BOOTFLAGS=%BOOTFLAGS% --repair"
%ESDECK% bootstrap %BOOTFLAGS%
echo.

rem ------------------------------------------------------------ ES-DE link ---
echo  [..] Pointing ES-DE at %ROMDIR%
%ESDECK% link --yes --create
echo.

rem ----------------------------------------------------------------- cores ---
rem RetroArch ships with no emulator cores, so nothing can launch without them.
rem A fresh library is empty, so "which cores do my systems need" would answer
rem "none" - install a starter set covering the common systems instead.
if defined OPT_NOCORES (
    echo  [..] Skipping cores. Run "esdeck cores --all --yes" when you want them.
) else if defined OPT_COMMON (
    echo  [..] Downloading cores for the common systems only
    %ESDECK% cores --common --yes
) else (
    echo  [..] Downloading every emulator core esdeck knows about
    echo       ^(from the official libretro build server - a few hundred MB^)
    %ESDECK% cores --all --yes
)
echo.

rem ------------------------------------------------------------------ tidy ---
rem An existing library may predate these rules, or have been built by hand.
%ESDECK% tidy --yes
echo.

rem -------------------------------------------------------------- shortcut ---
set "DESKTOP=%USERPROFILE%\Desktop"
if not exist "%DESKTOP%" set "DESKTOP=%USERPROFILE%\OneDrive\Desktop"
if exist "%DESKTOP%" (
    copy /y "extras\Sort Games.bat" "%DESKTOP%\Sort Games.bat" >nul
    echo  [ok] "Sort Games" placed on your Desktop
)

rem ---------------------------------------------------------------- doctor ---
echo.
echo  ===========================================================
echo    Checking the result
echo  ===========================================================
%ESDECK% doctor
echo.
echo  ===========================================================
echo    Done. What happens now:
echo  ===========================================================
echo.
echo    1. Put games in:  %INCOMING%
echo    2. Double-click "Sort Games" on your Desktop
echo       (or run:  esdeck sync --yes)
echo    3. Start ES-DE - your games will be there.
echo.
echo    ES-DE needs to be launched once before it shows anything.
echo.
if not defined UNATTENDED pause
endlocal
