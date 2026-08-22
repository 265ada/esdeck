@echo off
rem ===========================================================================
rem  esdeck SORT - put your games in the library.
rem
rem  Two ways to use it:
rem    * Drag games (or folders of games) onto this file, or
rem    * Drop them in your Incoming folder and just double-click this.
rem
rem  It shows what it found and what it will do, then asks before changing
rem  anything. Run esdeck.bat first if this PC has not been set up.
rem
rem  Optional arguments:
rem    --undo       reverse the last sort instead of sorting
rem    --clean      afterwards delete the Incoming copies, once verified
rem    --yes        skip the confirmation
rem    --no-pause   do not wait for a key at the end (for scripts)
rem ===========================================================================
setlocal enabledelayedexpansion
title esdeck - sort games
cd /d "%~dp0"

set "DROPPED="
set "OPT_CLEAN="
set "OPT_UNDO="
set "OPT_YES="
set "OPT_NOPAUSE="
for %%a in (%*) do (
    set "ARG=%%~a"
    if /i "!ARG!"=="--undo"     ( set "OPT_UNDO=1"
    ) else if /i "!ARG!"=="--clean"    ( set "OPT_CLEAN=1"
    ) else if /i "!ARG!"=="--yes"      ( set "OPT_YES=1"
    ) else if /i "!ARG!"=="--no-pause" ( set "OPT_NOPAUSE=1"
    ) else ( set "DROPPED=!DROPPED! "%%~a"" )
)

echo.
echo  ===========================================================
echo    esdeck - sorting your games
echo  ===========================================================
echo.

set "PY="
where python >nul 2>&1 && set "PY=python"
if not defined PY where py >nul 2>&1 && set "PY=py"
if not defined PY (
    echo  [X] Python is not installed. Run esdeck.bat first.
    goto :fail
)
set "ESDECK=%PY% -m esdeck"

for /f "delims=" %%v in ('%ESDECK% --version 2^>nul') do echo  Using %%v
%ESDECK% check-setup
if errorlevel 1 (
    echo.
    echo  [X] This PC is not set up yet - run esdeck.bat first.
    echo      It asks where your games should live and installs everything.
    goto :fail
)

if defined OPT_UNDO (
    echo  Undoing the most recent sort. Your original files are not touched.
    echo.
    %ESDECK% undo
    echo.
    set "GO="
    set /p "GO=  Undo it? [y/N] "
    if /i not "!GO!"=="y" (
        echo  Nothing was changed.
        goto :ok
    )
    echo.
    %ESDECK% undo --yes
    goto :ok
)

rem Tidy first: removes a stray folder from an older version, and makes sure
rem each game shows once in ES-DE rather than once per file.
%ESDECK% tidy --yes --near "%~dp0." >nul 2>&1

if defined DROPPED (
    echo  Sorting what you dragged onto this file.
    echo.
) else (
    echo  Sorting your Incoming folder.
    echo.
)

set "FLAGS="
if defined OPT_CLEAN set "FLAGS=--clean"

rem Show the plan first - nothing is changed by this.
%ESDECK% sync %DROPPED% %FLAGS%
echo.

if defined OPT_YES goto :apply

set "GO="
set /p "GO=  Apply these changes? [y/N] "
if /i not "%GO%"=="y" (
    echo.
    echo  Nothing was changed.
    goto :ok
)

:apply
echo.
%ESDECK% sync %DROPPED% --yes %FLAGS%
echo.
echo  ===========================================================
echo    Done - press F5 in ES-DE to see the new games.
echo.
echo    Wrong? Run this file again with --undo to reverse it.
echo  ===========================================================
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
echo.
if not defined OPT_NOPAUSE (
    echo  Press any key to close this window.
    pause >nul
)
endlocal
exit /b 0
