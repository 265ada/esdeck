@echo off
rem ===========================================================================
rem  Ascension / World of Warcraft - put addons and settings back
rem
rem  The undo for fix-ascension-132.bat. That script never deleted anything: it
rem  renamed Interface, WTF and Cache with a .esdeck-backup suffix. This finds
rem  them and moves them back.
rem
rem  Finding the right folder is the whole trick. Ascension.exe lives in the
rem  launcher's own folder - something like
rem      C:\Ascension\Launcher\resources\ascension-live
rem  while the addons and settings live with the game data, which is somewhere
rem  quite different:
rem      C:\ascension-live\Interface\AddOns
rem  Going by Ascension.exe therefore lands on the wrong folder and reports
rem  nothing to do while the addons sit safe a few folders away. So this looks
rem  for the data - Interface and WTF - and ignores where the .exe is.
rem
rem  Nothing is deleted here either.
rem
rem  Usage:  double-click it, or drag your ascension-live folder onto it.
rem ===========================================================================

setlocal enabledelayedexpansion
color 0B
title Ascension - restore addons and settings

echo.
echo  ===========================================================
echo    Ascension  -  put addons and settings back
echo  ===========================================================
echo.
echo    Looking for your game data. This may search your drives,
echo    so give it a moment.
echo.

rem ------------------------------------------------------------- find them
set "GAMEDIR="
set "DATADIR="

rem A folder dragged onto this file wins.
if not "%~1"=="" call :checkbackup "%~1"
if not "%~1"=="" if not defined DATADIR call :checkdata "%~1"

rem Then the places the game data actually lives.
for %%R in (
    "%SystemDrive%\ascension-live"
    "C:\ascension-live"
    "D:\ascension-live"
    "E:\ascension-live"
    "F:\ascension-live"
    "%SystemDrive%\Ascension\ascension-live"
    "D:\Ascension\ascension-live"
    "%SystemDrive%\Ascension"
    "D:\Ascension"
    "%SystemDrive%\Ascension\Launcher\resources\ascension-live"
) do (
    if not defined GAMEDIR call :checkbackup "%%~R"
    if not defined DATADIR call :checkdata "%%~R"
)

rem Then look properly. Backups first - they are what this is for.
if not defined GAMEDIR (
    echo    Searching for anything that was set aside...
    for %%D in (C D E F G) do (
        if exist "%%D:\" (
            for /f "delims=" %%F in ('dir /s /b /ad "%%D:\Interface.esdeck-backup" 2^>nul') do (
                if not defined GAMEDIR set "GAMEDIR=%%~dpF"
            )
            for /f "delims=" %%F in ('dir /s /b /ad "%%D:\WTF.esdeck-backup" 2^>nul') do (
                if not defined GAMEDIR set "GAMEDIR=%%~dpF"
            )
        )
    )
    if defined GAMEDIR if "!GAMEDIR:~-1!"=="\" set "GAMEDIR=!GAMEDIR:~0,-1!"
)

rem And find the live data too, so there is something useful to say either way.
if not defined DATADIR (
    for %%D in (C D E F G) do (
        if exist "%%D:\" (
            for /f "delims=" %%F in ('dir /s /b /ad "%%D:\ascension-live" 2^>nul') do (
                if not defined DATADIR call :checkdata "%%F"
            )
        )
    )
)

rem ------------------------------------------------------- nothing to undo
if not defined GAMEDIR (
    echo.
    echo  ===========================================================
    echo.
    echo    Nothing was set aside anywhere on this PC.
    echo.
    echo    There is no Interface.esdeck-backup or WTF.esdeck-backup on
    echo    any drive. That means the repair script never moved your
    echo    addons, so it is not what removed them - and there is
    echo    nothing here for this script to put back.
    echo.
    if defined DATADIR (
        echo    Your game data is here:
        echo      %DATADIR%
        echo.
        if exist "%DATADIR%\Interface\AddOns" (
            echo    And your addons are still installed, in:
            echo      %DATADIR%\Interface\AddOns
            echo.
            echo    Which means they have not been deleted - the game is
            echo    just not loading them. On the character screen click
            echo    AddOns, and tick "Load out of date addons".
            echo.
            echo    Addons currently installed:
            echo.
            for /f "delims=" %%A in ('dir /b /ad "%DATADIR%\Interface\AddOns" 2^>nul') do echo       %%A
        ) else (
            echo    There is no Interface\AddOns folder there, so the addons
            echo    are genuinely gone and will need reinstalling.
        )
    ) else (
        echo    The game data folder could not be found either. It is the
        echo    folder called ascension-live that contains Interface and
        echo    WTF - NOT the one inside Launcher\resources.
        echo.
        echo    Drag that folder onto this file and run it again.
    )
    echo.
    goto :done
)

echo.
echo    Found what was set aside, in:
echo      %GAMEDIR%
echo.

set "HAVE_IF="
set "HAVE_WTF="
if exist "%GAMEDIR%\Interface.esdeck-backup" set "HAVE_IF=1"
if exist "%GAMEDIR%\WTF.esdeck-backup" set "HAVE_WTF=1"
if defined HAVE_IF    echo       Interface   (your addons)
if defined HAVE_WTF   echo       WTF         (your settings, keybinds, macros)
echo.

rem ------------------------------------------------------------- choose
echo    What would you like back?
echo.
echo       [1]  Everything - addons and settings        (the usual answer)
echo       [2]  Settings only - leave the addons out
echo       [3]  Addons only - keep the current settings
echo       [4]  Nothing, close this
echo.
echo    If the crashing stopped after the purge, one of your addons was
echo    probably the cause. Choosing 2 gets your keybinds and macros back
echo    without bringing the suspect addons with them.
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
    echo    That was not one of the choices - nothing has been changed.
    goto :done
)

echo.
if defined DO_IF  call :restore "%GAMEDIR%\Interface" Interface "your addons"
if defined DO_WTF call :restore "%GAMEDIR%\WTF" WTF "your settings"

rem ---------------------------------------------------- keep the DX11 fix
rem Restoring the old WTF brings back the old Config.wtf, which will not have
rem the DirectX 11 setting. That setting is a plain improvement on the
rem hardware where #132 happens, and is not the part anyone wants undone.
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
    echo    If they are still missing from the list, click AddOns on the
    echo    character screen and tick "Load out of date addons".
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

:checkbackup
rem Does this folder hold something we set aside?
if exist "%~1\Interface.esdeck-backup" set "GAMEDIR=%~1"
if exist "%~1\WTF.esdeck-backup" set "GAMEDIR=%~1"
goto :eof

:checkdata
rem Is this the game data root? Interface and WTF live here - Ascension.exe
rem does not, and looking for the .exe is what sent us to the wrong folder.
if exist "%~1\Interface" set "DATADIR=%~1"
if exist "%~1\WTF" set "DATADIR=%~1"
goto :eof

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
    rem
    rem Pick a free name rather than stamping the date on it: %DATE% reads
    rem differently in every region, and a stamp built from it collides with
    rem itself when this runs twice in one day.
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
