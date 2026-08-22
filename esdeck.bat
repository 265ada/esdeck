@echo off
rem ===========================================================================
rem  esdeck - one file that does everything.
rem
rem  Double-click it. On a new PC it installs and configures the whole setup;
rem  after that it sorts whatever you have dropped in the Incoming folder.
rem  Safe to run as often as you like - every step checks before it acts.
rem
rem  Optional arguments, in any order:
rem    <folder>          where games live (skips the question)
rem    --no-cores        do not download emulator cores
rem    --common-cores    11 common cores instead of all of them
rem    --all-emulators   also install Dolphin, PCSX2, DuckStation, PPSSPP
rem    --repair          reinstall ES-DE/RetroArch over an existing install
rem    --clean           delete Incoming copies once verified in the library
rem    --setup           force the full first-run setup again
rem ===========================================================================
setlocal enabledelayedexpansion
title esdeck
cd /d "%~dp0"

set "GAMEROOT="
set "OPT_NOCORES="
set "OPT_COMMON="
set "OPT_ALLEMU="
set "OPT_REPAIR="
set "OPT_CLEAN="
set "OPT_SETUP="
for %%a in (%*) do (
    set "ARG=%%~a"
    if /i "!ARG!"=="--no-cores"      set "OPT_NOCORES=1"
    if /i "!ARG!"=="--common-cores"  set "OPT_COMMON=1"
    if /i "!ARG!"=="--all-emulators" set "OPT_ALLEMU=1"
    if /i "!ARG!"=="--repair"        set "OPT_REPAIR=1"
    if /i "!ARG!"=="--clean"         set "OPT_CLEAN=1"
    if /i "!ARG!"=="--setup"         set "OPT_SETUP=1"
    if not "!ARG:~0,2!"=="--" if not defined GAMEROOT set "GAMEROOT=!ARG!"
)
if defined GAMEROOT set "UNATTENDED=1"

echo.
echo  ===========================================================
echo    esdeck
echo  ===========================================================
echo.

rem --------------------------------------------------------------- python ---
set "PY="
where python >nul 2>&1 && set "PY=python"
if not defined PY where py >nul 2>&1 && set "PY=py"
if not defined PY (
    where winget >nul 2>&1
    if errorlevel 1 (
        echo  [X] Python is missing and winget is not available to install it.
        echo      Install Python from python.org, then run this again.
        echo.
        pause
        exit /b 1
    )
    echo  [..] Installing Python
    winget install --id Python.Python.3.12 --exact --silent ^
        --accept-package-agreements --accept-source-agreements
    echo.
    echo  Python is installed but this window cannot see it yet.
    echo  Close this window, open a new one, and run esdeck.bat again.
    echo.
    pause
    exit /b 0
)
set "ESDECK=%PY% -m esdeck"

rem Is esdeck already set up on this machine?
%ESDECK% doctor >nul 2>&1
set "NEEDS_SETUP=%errorlevel%"
if not exist "%USERPROFILE%\.esdeck\config.json" set "NEEDS_SETUP=1"
if defined OPT_SETUP set "NEEDS_SETUP=1"

if "%NEEDS_SETUP%"=="0" goto :sort

rem ======================= FIRST RUN: SET EVERYTHING UP =======================
echo  First run - setting this PC up.
echo.

where winget >nul 2>&1
if errorlevel 1 (
    echo  [X] winget is not available. Install "App Installer" from the
    echo      Microsoft Store, then run this again.
    echo.
    pause
    exit /b 1
)
echo  [ok] winget found

echo  [..] Installing esdeck
%PY% -m pip install -e . --quiet --disable-pip-version-check
if errorlevel 1 (
    echo  [X] pip install failed. Scroll up for the reason.
    echo.
    pause
    exit /b 1
)
echo  [ok] esdeck installed

if not defined GAMEROOT (
    echo.
    echo  Your games can live on any drive. Here is what this PC has:
    echo.
    %ESDECK% drives
    echo.
    echo  Two folders are created under whichever you choose:
    echo      ^<folder^>\ROMs       the sorted library ES-DE reads
    echo      ^<folder^>\Incoming   where you drop new games
    echo.
    for /f "delims=" %%d in ('%ESDECK% drives --suggest') do set "SUGGEST=%%d"
    set /p "GAMEROOT=  Game folder [!SUGGEST!]: "
    if not defined GAMEROOT set "GAMEROOT=!SUGGEST!"
)
if not defined GAMEROOT (
    echo  [X] No folder chosen. Re-run as:  esdeck.bat C:\Games
    echo.
    pause
    exit /b 1
)

set "ROMDIR=%GAMEROOT%\ROMs"
set "INCOMING=%GAMEROOT%\Incoming"
if not exist "%ROMDIR%"   mkdir "%ROMDIR%"
if not exist "%INCOMING%" mkdir "%INCOMING%"
if not exist "%ROMDIR%" (
    echo  [X] Could not create %ROMDIR% - is that drive available and writable?
    echo.
    pause
    exit /b 1
)
echo  [ok] %ROMDIR%
echo  [ok] %INCOMING%

%ESDECK% init --rom-dir "%ROMDIR%" --source-dir "%INCOMING%" >nul
if errorlevel 1 (
    echo  [X] esdeck init failed.
    pause
    exit /b 1
)
echo  [ok] configured

echo.
echo  [..] Installing ES-DE, RetroArch and 7-Zip
echo.
set "BOOTFLAGS=--yes"
if defined OPT_ALLEMU set "BOOTFLAGS=%BOOTFLAGS% --all-emulators"
if defined OPT_REPAIR set "BOOTFLAGS=%BOOTFLAGS% --repair"
%ESDECK% bootstrap %BOOTFLAGS%
echo.

echo  [..] Pointing ES-DE at %ROMDIR%
%ESDECK% link --yes --create
echo.

if defined OPT_NOCORES (
    echo  [..] Skipping cores. Run "esdeck cores --all --yes" when you want them.
) else if defined OPT_COMMON (
    echo  [..] Downloading cores for the common systems
    %ESDECK% cores --common --yes
) else (
    echo  [..] Downloading every emulator core ES-DE can launch
    echo       ^(official libretro build server - a few hundred MB^)
    %ESDECK% cores --all --yes
)
echo.

echo  [..] Applying emulator choices
%ESDECK% emulators --apply --yes
echo.

set "DESKTOP=%USERPROFILE%\Desktop"
if not exist "%DESKTOP%" set "DESKTOP=%USERPROFILE%\OneDrive\Desktop"
if exist "%DESKTOP%" (
    copy /y "%~f0" "%DESKTOP%\esdeck.bat" >nul
    echo  [ok] "esdeck" placed on your Desktop
)
echo.

rem ============================ SORT THE GAMES ================================
:sort
echo  ===========================================================
echo    Sorting your drop folder
echo  ===========================================================
echo.
%ESDECK% tidy --yes
echo.

set "SYNCFLAGS=--yes"
if defined OPT_CLEAN set "SYNCFLAGS=%SYNCFLAGS% --clean"
%ESDECK% sync %SYNCFLAGS%
echo.

%ESDECK% doctor
echo.
echo  ===========================================================
echo    Done. Start ES-DE to play - press F5 in it to refresh.
echo  ===========================================================
echo.
if not defined UNATTENDED pause
endlocal
