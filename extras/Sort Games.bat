@echo off
title esdeck - sort games
cd /d "%~dp0"

echo ============================================
echo   esdeck - sorting your drop folder
echo ============================================
echo.

where esdeck >nul 2>&1
if errorlevel 1 (
    echo esdeck is not on PATH. Install it with:
    echo     pip install -e "path\to\esdeck"
    echo.
    pause
    exit /b 1
)

rem Show what would happen before changing anything.
esdeck sync
echo.

set "GO="
set /p "GO=Apply these changes? [y/N] "
if /i not "%GO%"=="y" (
    echo Nothing was changed.
    echo.
    pause
    exit /b 0
)

echo.
esdeck sync --yes
echo.
pause
