@echo off
rem ===========================================================================
rem  Sort the drop folder into the library. Nothing else.
rem
rem  esdeck.bat does this too - it sets the PC up on first run, then sorts on
rem  every run after. This file is here for when you only want the sorting:
rem  put it wherever is convenient, including the Desktop.
rem
rem  Optional:  sort-games.bat --clean   also frees space by deleting the
rem                                      Incoming copies once verified.
rem ===========================================================================
setlocal
title esdeck - sort games
cd /d "%~dp0"

set "PY="
where python >nul 2>&1 && set "PY=python"
if not defined PY where py >nul 2>&1 && set "PY=py"
if not defined PY (
    echo  Python is not installed. Run esdeck.bat first.
    echo.
    pause
    exit /b 1
)

%PY% -m esdeck doctor >nul 2>&1
if errorlevel 1 (
    echo  esdeck is not set up on this PC yet. Run esdeck.bat first.
    echo.
    pause
    exit /b 1
)

echo.
echo  Checking what is in your drop folder...
echo.
%PY% -m esdeck sync %*
echo.

set "GO="
set /p "GO=Apply these changes? [y/N] "
if /i not "%GO%"=="y" (
    echo  Nothing was changed.
    echo.
    pause
    exit /b 0
)

echo.
%PY% -m esdeck tidy --yes
%PY% -m esdeck sync --yes %*
echo.
echo  Done. Press F5 in ES-DE to see the new games.
echo.
echo  Press any key to close this window.
pause >nul
endlocal
