@echo off
rem ===========================================================================
rem  esdeck SETUP - run this once on a new PC.
rem
rem  Asks where your games should live, then installs and configures
rem  everything needed to play them: Python, esdeck, ES-DE, RetroArch, 7-Zip,
rem  every emulator core, the ROM folder tree and the Incoming drop folder.
rem
rem  Safe to run again - it repairs and tops up whatever is missing.
rem  To sort games afterwards, use sort-games.bat.
rem
rem  Optional arguments, in any order:
rem    <folder>          where games live (skips the question)
rem    --no-cores        do not download emulator cores
rem    --common-cores    11 common cores instead of all of them
rem    --all-emulators   also install Dolphin, PCSX2, DuckStation, PPSSPP
rem    --repair          reinstall ES-DE/RetroArch over an existing install
rem    --no-pause        do not wait for a key at the end (for scripts)
rem ===========================================================================
setlocal enabledelayedexpansion
title esdeck setup
cd /d "%~dp0"

set "GAMEROOT="
set "OPT_NOCORES="
set "OPT_COMMON="
set "OPT_ALLEMU="
set "OPT_REPAIR="
set "OPT_NOPAUSE="
for %%a in (%*) do (
    set "ARG=%%~a"
    if /i "!ARG!"=="--no-cores"      set "OPT_NOCORES=1"
    if /i "!ARG!"=="--common-cores"  set "OPT_COMMON=1"
    if /i "!ARG!"=="--all-emulators" set "OPT_ALLEMU=1"
    if /i "!ARG!"=="--repair"        set "OPT_REPAIR=1"
    if /i "!ARG!"=="--no-pause"      set "OPT_NOPAUSE=1"
    if not "!ARG:~0,2!"=="--" if not defined GAMEROOT set "GAMEROOT=!ARG!"
)

echo.
echo  ===========================================================
echo    esdeck setup
echo  ===========================================================
echo.

set "PY="
where python >nul 2>&1 && set "PY=python"
if not defined PY where py >nul 2>&1 && set "PY=py"
if not defined PY (
    where winget >nul 2>&1
    if errorlevel 1 (
        echo  [X] Python is missing and winget cannot install it here.
        echo      Install Python from python.org, then run this again.
        goto :fail
    )
    echo  [..] Installing Python
    winget install --id Python.Python.3.12 --exact --silent ^
        --accept-package-agreements --accept-source-agreements
    echo.
    echo  Python is installed but this window cannot see it yet.
    echo  Close this window, open a new one, and run esdeck.bat again.
    goto :ok
)
echo  [ok] Python found

if not exist "pyproject.toml" (
    echo  [X] This copy of esdeck.bat is on its own and cannot install anything.
    echo.
    echo      Run it from the folder you unzipped from GitHub - the one that
    echo      contains pyproject.toml.
    goto :fail
)

echo  [..] Installing esdeck
rem A plain install, not "-e": an editable install only points at this folder,
rem so deleting the extracted ZIP afterwards would uninstall esdeck.
%PY% -m pip install . --quiet --disable-pip-version-check
if errorlevel 1 (
    echo  [X] pip install failed. Scroll up for the reason.
    goto :fail
)
set "ESDECK=%PY% -m esdeck"
for /f "delims=" %%v in ('%ESDECK% --version 2^>nul') do echo  [ok] %%v

rem Reuse an existing setup only if it is actually usable. A config left by an
rem older version can point at a relative path like "G\ROMs", which made setup
rem skip itself forever while sorting nothing.
if not defined GAMEROOT (
    %ESDECK% check-setup >nul 2>&1
    if not errorlevel 1 (
        for /f "delims=" %%r in ('%ESDECK% drives --current 2^>nul') do set "GAMEROOT=%%r"
        if defined GAMEROOT echo  [ok] Already set up - using !GAMEROOT!
    )
)

if not defined GAMEROOT (
    echo.
    echo  Where should your games live? Here is what this PC has:
    echo.
    %ESDECK% drives
    echo.
    echo  Two folders are created under whichever you choose:
    echo      ^<folder^>\ROMs       the sorted library ES-DE reads
    echo      ^<folder^>\Incoming   where you drop new games
    echo.
    echo  Answer with a drive letter ^(G^), a drive ^(G:^) or a full path.
    echo.
    for /f "delims=" %%d in ('%ESDECK% drives --suggest') do set "SUGGEST=%%d"
    set /p "GAMEROOT=  Game folder [!SUGGEST!]: "
    if not defined GAMEROOT set "GAMEROOT=!SUGGEST!"
)

rem "G" alone is a relative path - it used to create a folder called G next to
rem this script instead of using the G: drive. Turn it into a real path first.
for /f "delims=" %%n in ('%ESDECK% drives --normalize "%GAMEROOT%"') do set "GAMEROOT=%%n"
if not defined GAMEROOT (
    echo  [X] That is not a full path. Use a drive letter ^(G^) or a path
    echo      like G:\Games, then run this again.
    goto :fail
)
echo  [ok] Games folder: %GAMEROOT%

set "ROMDIR=%GAMEROOT%\ROMs"
set "INCOMING=%GAMEROOT%\Incoming"
if not exist "%ROMDIR%"   mkdir "%ROMDIR%"
if not exist "%INCOMING%" mkdir "%INCOMING%"
if not exist "%ROMDIR%" (
    echo  [X] Could not create %ROMDIR%
    echo      Is that drive plugged in, and is it writable?
    goto :fail
)
if not exist "%INCOMING%" (
    echo  [X] Could not create %INCOMING%
    goto :fail
)
echo  [ok] %ROMDIR%
echo  [ok] %INCOMING%

%ESDECK% init --rom-dir "%ROMDIR%" --source-dir "%INCOMING%" >nul
if errorlevel 1 (
    echo  [X] esdeck init failed.
    goto :fail
)
echo  [ok] Configured

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

rem Clear up a stray folder left by an older version answering "G" literally.
%ESDECK% tidy --yes --near "%~dp0." >nul 2>&1

set "DESKTOP=%USERPROFILE%\Desktop"
if not exist "%DESKTOP%" set "DESKTOP=%USERPROFILE%\OneDrive\Desktop"
if exist "%DESKTOP%" (
    for %%b in (ThuggyEmuAutomation.bat sort-games.bat fix-library.bat) do (
        if exist "%%b" copy /y "%%b" "%DESKTOP%\%%b" >nul
    )
    echo  [ok] esdeck shortcuts placed on your Desktop
    if exist "assets\ThuggyEmuAutomation.png" (
        %ESDECK% icon "assets\ThuggyEmuAutomation.png" --dest "%DESKTOP%\ThuggyEmuAutomation.ico" --shortcut "%DESKTOP%\ThuggyEmuAutomation.bat" >nul 2>&1
    )
    echo       Use "ThuggyEmuAutomation" from now on - it keeps itself updated.
)

echo.
echo  ===========================================================
echo    Checking the result
echo  ===========================================================
%ESDECK% doctor
echo.
echo  ===========================================================
echo    Setup complete
echo  ===========================================================
echo.
echo    1. Drag your games into:  %INCOMING%
echo    2. Run sort-games.bat  ^(now on your Desktop^)
echo    3. Start ES-DE and play
echo.
goto :ok

:fail
echo.
if not defined OPT_NOPAUSE (
    echo  Press any key to close this window.
    pause >nul
)
endlocal
exit /b 1

:ok
if not defined OPT_NOPAUSE (
    echo  Press any key to close this window.
    pause >nul
)
endlocal
exit /b 0
