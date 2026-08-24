@echo off
rem ===========================================================================
rem  Ascension / World of Warcraft - put addons and settings back
rem
rem  The undo for fix-ascension-132.bat. That script never deleted anything: it
rem  renamed Interface, WTF and Cache with a .esdeck-backup suffix. This moves
rem  them back.
rem
rem  The one complication is that the game has probably been started since, and
rem  will have built itself fresh Interface and WTF folders. Those are set
rem  aside too rather than overwritten - if the addons turn out to be what was
rem  crashing the game, the clean set is still there to go back to.
rem
rem  So nothing is deleted here either.
rem
rem  Usage:  double-click it, or drag the Ascension folder onto it.
rem ===========================================================================

setlocal enabledelayedexpansion
color 0B
title Ascension - restore addons and settings

echo.
echo  ===========================================================
echo    Ascension  -  put addons and settings back
echo  ===========================================================
echo.

rem ---------------------------------------------------------------- find it
set "GAMEDIR="
if not "%~1"=="" if exist "%~1\Ascension.exe" set "GAMEDIR=%~1"
if not "%~1"=="" if exist "%~1\Wow.exe" set "GAMEDIR=%~1"
if not defined GAMEDIR call :findgame

if not defined GAMEDIR (
    echo   [!] Could not find Ascension automatically.
    echo.
    echo       Find the folder holding Ascension.exe, drag it onto this
    echo       file, and run it again.
    echo.
    goto :done
)

echo   Found the game at:
echo     %GAMEDIR%
echo.

rem ------------------------------------------------------ what is there
set "HAVE_IF="
set "HAVE_WTF="
set "HAVE_CACHE="
if exist "%GAMEDIR%\Interface.esdeck-backup" set "HAVE_IF=1"
if exist "%GAMEDIR%\WTF.esdeck-backup" set "HAVE_WTF=1"
if exist "%GAMEDIR%\Cache.esdeck-backup" set "HAVE_CACHE=1"

if not defined HAVE_IF if not defined HAVE_WTF (
    echo   There is nothing to put back.
    echo.
    echo   No Interface.esdeck-backup or WTF.esdeck-backup folder is here,
    echo   which means the addon step was skipped or has already been undone.
    echo.
    if defined HAVE_CACHE (
        echo   There is an old Cache.esdeck-backup, but that one is worth
        echo   leaving alone - the game rebuilds Cache itself, and the old
        echo   copy is the most likely thing to have been broken.
        echo.
    )
    goto :done
)

echo   Found backed-up:
if defined HAVE_IF    echo      Interface   (your addons)
if defined HAVE_WTF   echo      WTF         (your settings, keybinds, macros)
echo.

rem ------------------------------------------------------------- choose
echo   What would you like back?
echo.
echo      [1]  Everything - addons and settings        (the usual answer)
echo      [2]  Settings only - leave the addons out
echo      [3]  Addons only - keep the current settings
echo      [4]  Nothing, close this
echo.
echo   If the crashing stopped after the purge, one of your addons was
echo   probably the cause. Choosing 2 gets your keybinds and macros back
echo   without bringing the suspect addons with them.
echo.
set "PICK="
set /p "PICK=   Choose 1-4: "
set "PICK=!PICK:~0,1!"

if "!PICK!"=="4" goto :done
if "!PICK!"=="" goto :done

set "DO_IF="
set "DO_WTF="
if "!PICK!"=="1" set "DO_IF=1" & set "DO_WTF=1"
if "!PICK!"=="2" set "DO_WTF=1"
if "!PICK!"=="3" set "DO_IF=1"

if not defined DO_IF if not defined DO_WTF (
    echo.
    echo   That was not one of the choices - nothing has been changed.
    goto :done
)

echo.
if defined DO_IF  call :restore "%GAMEDIR%\Interface" Interface "your addons"
if defined DO_WTF call :restore "%GAMEDIR%\WTF" WTF "your settings"

rem ---------------------------------------------------- keep the DX11 fix
rem Restoring the old WTF brings back the old Config.wtf, which does not have
rem the DirectX 11 setting. That setting is a plain improvement on the
rem hardware where #132 happens, so it goes back in - it is not the part
rem anyone is trying to undo.
if defined DO_WTF (
    set "CFG=%GAMEDIR%\WTF\Config.wtf"
    if exist "!CFG!" (
        findstr /i /c:"gxApi" "!CFG!" >nul 2>&1
        if errorlevel 1 (
            >>"!CFG!" echo SET gxApi "d3d11"
            echo         kept the DirectX 11 setting
        )
    )
)

echo.
echo  ===========================================================
echo.
echo    Done. Start the game and check your addons are there.
echo.
if defined DO_IF (
    echo    If addons are still missing from the list, turn on
    echo    "Load out of date addons" on the character screen - the
    echo    box is under the AddOns button.
    echo.
)
echo    Anything that was already in place has been set aside in a
echo    .before-restore folder rather than thrown away, so this is
echo    reversible too.
echo.

:done
echo  ===========================================================
echo.
echo    Press any key to close this window.
pause >nul
endlocal
exit /b 0

rem --------------------------------------------------------------- helpers

:restore
rem  %1 = live path, %2 = folder name, %3 = description
set "LIVE=%~1"
set "BACK=%~1.esdeck-backup"
if not exist "%BACK%" (
    echo         no %~2 backup - nothing to put back
    goto :eof
)
if exist "%LIVE%" (
    rem The game has rebuilt it since. Keep that clean copy: if the addons
    rem are what was crashing, it is the thing to come back to.
    rem Pick a free name rather than stamping one: %DATE% reads differently
    rem in every region, and a stamp built from it is both ugly and liable to
    rem collide with itself when this is run twice in a day.
    set "ASIDE=%LIVE%.before-restore"
    set /a N=1
:nextname
    if exist "!ASIDE!" (
        set /a N+=1
        set "ASIDE=%LIVE%.before-restore-!N!"
        goto :nextname
    )
    move "%LIVE%" "!ASIDE!" >nul 2>&1
    if exist "%LIVE%" (
        echo         could not move the current %~2 - is the game running?
        goto :eof
    )
)
move "%BACK%" "%LIVE%" >nul 2>&1
if exist "%LIVE%" (
    echo         %~2 restored  -  %~3 are back
) else (
    echo         could not restore %~2 - is the game running?
)
goto :eof

:findgame
for %%R in (
    "%SystemDrive%\Ascension\Launcher\resources\ascension-live"
    "%LOCALAPPDATA%\Ascension\Launcher\resources\ascension-live"
    "%SystemDrive%\Ascension"
    "%SystemDrive%\Games\Ascension"
    "D:\Ascension\Launcher\resources\ascension-live"
    "D:\Ascension"
    "D:\Games\Ascension"
    "E:\Ascension"
) do (
    if exist "%%~R\Ascension.exe" (
        set "GAMEDIR=%%~R"
        goto :eof
    )
    if exist "%%~R\Wow.exe" (
        set "GAMEDIR=%%~R"
        goto :eof
    )
)

echo   Not in the usual places - searching your drives. This can take
echo   a minute or two.
echo.
for %%D in (C D E F) do (
    if exist "%%D:\" (
        for /f "delims=" %%F in ('dir /s /b "%%D:\Ascension.exe" 2^>nul') do (
            if not defined GAMEDIR set "GAMEDIR=%%~dpF"
        )
    )
)
if defined GAMEDIR if "!GAMEDIR:~-1!"=="\" set "GAMEDIR=!GAMEDIR:~0,-1!"
goto :eof
