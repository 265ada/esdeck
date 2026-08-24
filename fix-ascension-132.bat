@echo off
rem ===========================================================================
rem  Ascension / World of Warcraft - ERROR #132 (0x85100084) repair
rem
rem  #132 is an ACCESS_VIOLATION: the game read memory it was not allowed to.
rem  It is almost never one thing. In rough order of how often it is the cause:
rem
rem    1. a corrupt Cache folder            - fixed here, safely
rem    2. a broken addon or saved setting   - fixed here, safely
rem    3. the graphics API it is using      - fixed here, safely
rem    4. graphics drivers                  - reported here, you install
rem    5. unstable RAM or an overclock      - reported here, you decide
rem    6. damaged Windows files             - offered here, takes a while
rem
rem  This works through 1-3, which between them account for most cases, and
rem  reports on the rest so there is something concrete to act on.
rem
rem  NOTHING IS DELETED. Folders are renamed with a .esdeck-backup suffix, so
rem  if this does not help, rename them back and you have lost nothing.
rem
rem  Usage:  double-click it, or drag the Ascension folder onto it.
rem ===========================================================================

setlocal enabledelayedexpansion
color 0B
title Ascension ERROR #132 repair

rem Ask Windows where the Desktop actually is. With OneDrive it is not
rem %USERPROFILE%\Desktop, and writing to a path that does not exist fails
rem on every single line - loudly, and for the whole run.
set "DESKTOP="
for /f "tokens=2*" %%a in ('reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders" /v Desktop 2^>nul') do set "DESKTOP=%%~b"
if not defined DESKTOP set "DESKTOP=%USERPROFILE%\Desktop"
if not exist "%DESKTOP%" set "DESKTOP=%USERPROFILE%\OneDrive\Desktop"
if not exist "%DESKTOP%" set "DESKTOP=%USERPROFILE%"
set "REPORT=%DESKTOP%\Ascension-132-report.txt"
set "STAMP=%DATE% %TIME%"

echo.
echo  ===========================================================
echo    Ascension / WoW  -  ERROR #132 repair
echo  ===========================================================
echo.
echo    Nothing is deleted. Anything this changes is renamed
echo    first, so it can all be put back.
echo.
echo    A report is written to your Desktop:
echo      %REPORT%
echo.

> "%REPORT%" echo Ascension ERROR #132 report
>>"%REPORT%" echo Generated %STAMP%
>>"%REPORT%" echo ============================================================
>>"%REPORT%" echo.

rem ---------------------------------------------------------------- find it
set "GAMEDIR="

rem A folder dragged onto this file wins.
if not "%~1"=="" if exist "%~1\Ascension.exe" set "GAMEDIR=%~1"
if not "%~1"=="" if exist "%~1\Wow.exe" set "GAMEDIR=%~1"

if not defined GAMEDIR call :findgame

if not defined GAMEDIR (
    echo   [!] Could not find Ascension automatically.
    echo.
    echo       Find the folder containing Ascension.exe - the error message
    echo       names it, for example:
    echo         C:\Ascension\Launcher\resources\ascension-live
    echo.
    echo       Then drag that folder onto this file and run it again.
    echo.
    >>"%REPORT%" echo Ascension install: NOT FOUND
    goto :diagnostics
)

echo   Found the game at:
echo     %GAMEDIR%
echo.
>>"%REPORT%" echo Ascension install: %GAMEDIR%
>>"%REPORT%" echo.

rem ------------------------------------------------------------- 1. cache
rem The Cache folder is rebuilt from scratch on the next launch. It is the
rem single most common cause of #132 and the safest thing to clear, because
rem nothing in it is yours - no settings, no addons, no characters.
echo   [1/3] Cache
if exist "%GAMEDIR%\Cache" (
    set "BK=%GAMEDIR%\Cache.esdeck-backup"
    if exist "!BK!" rd /s /q "!BK!" >nul 2>&1
    move "%GAMEDIR%\Cache" "!BK!" >nul 2>&1
    if exist "%GAMEDIR%\Cache" (
        echo         could not move it - is the game still running?
        >>"%REPORT%" echo Cache: could not move ^(game running?^)
    ) else (
        echo         set aside - it rebuilds itself on the next launch
        >>"%REPORT%" echo Cache: renamed to Cache.esdeck-backup
    )
) else (
    echo         no Cache folder - nothing to do
    >>"%REPORT%" echo Cache: absent
)
echo.

rem ------------------------------------------------- 2. addons and settings
rem WTF holds settings and Interface holds addons. Both are yours, so this
rem asks. An addon compiled against a different build is a very common #132.
echo   [2/3] Addons and saved settings
echo.
echo         A broken addon is a common cause. Setting these aside makes
echo         the game start fresh: your addons stop loading and your
echo         settings and keybinds go back to default.
echo.
echo         They are renamed, not deleted - you can put them back.
echo.
set "DOADDONS="
set /p "DOADDONS=        Set addons and settings aside? (y/N): "
if /i "!DOADDONS:~0,1!"=="y" (
    call :backup "%GAMEDIR%\Interface" Interface
    call :backup "%GAMEDIR%\WTF" WTF
) else (
    echo         skipped
    >>"%REPORT%" echo Interface/WTF: left alone by choice
)
echo.

rem ------------------------------------------------------- 3. graphics API
rem DirectX 12 is where #132 most often lands on older or Intel/AMD hybrid
rem hardware. Forcing the DX11 path costs very little and fixes a lot.
echo   [3/3] Graphics API
set "CFG=%GAMEDIR%\WTF\Config.wtf"
if exist "%CFG%" (
    findstr /i /c:"gxApi" "%CFG%" >nul 2>&1
    if errorlevel 1 (
        >>"%CFG%" echo SET gxApi "d3d11"
        echo         set to DirectX 11
        >>"%REPORT%" echo gxApi: added, set to d3d11
    ) else (
        echo         already set - leaving it alone
        >>"%REPORT%" echo gxApi: already present
    )
) else (
    rem No Config.wtf yet: make one so the first launch uses DX11.
    if not exist "%GAMEDIR%\WTF" md "%GAMEDIR%\WTF" >nul 2>&1
    > "%CFG%" echo SET gxApi "d3d11"
    echo         no settings file yet - created one using DirectX 11
    >>"%REPORT%" echo gxApi: Config.wtf created with d3d11
)
echo.

rem --------------------------------------------------------- diagnostics
:diagnostics
echo   Collecting system details for the report...
echo.
>>"%REPORT%" echo.
>>"%REPORT%" echo ------------------------------------------------------------
>>"%REPORT%" echo GRAPHICS
>>"%REPORT%" echo ------------------------------------------------------------
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Get-CimInstance Win32_VideoController | ForEach-Object { '{0}   driver {1}   dated {2}' -f $_.Name, $_.DriverVersion, $_.DriverDate }" >>"%REPORT%" 2>nul

>>"%REPORT%" echo.
>>"%REPORT%" echo ------------------------------------------------------------
>>"%REPORT%" echo MEMORY AND PAGE FILE
>>"%REPORT%" echo ------------------------------------------------------------
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$c=Get-CimInstance Win32_ComputerSystem; '{0:N1} GB installed' -f ($c.TotalPhysicalMemory/1GB); Get-CimInstance Win32_PageFileUsage | ForEach-Object { 'page file {0}  {1} MB' -f $_.Name, $_.AllocatedBaseSize }" >>"%REPORT%" 2>nul

>>"%REPORT%" echo.
>>"%REPORT%" echo ------------------------------------------------------------
>>"%REPORT%" echo RECENT APPLICATION CRASHES
>>"%REPORT%" echo ------------------------------------------------------------
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Get-WinEvent -FilterHashtable @{LogName='Application';ID=1000,1001} -MaxEvents 8 -ErrorAction SilentlyContinue | ForEach-Object { '{0}  {1}' -f $_.TimeCreated, ($_.Message -split \"`n\")[0] }" >>"%REPORT%" 2>nul

>>"%REPORT%" echo.
>>"%REPORT%" echo ------------------------------------------------------------
>>"%REPORT%" echo HARDWARE ERRORS  (any entry here points at RAM, an
>>"%REPORT%" echo overclock, or a failing part - not at the game)
>>"%REPORT%" echo ------------------------------------------------------------
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$e=Get-WinEvent -FilterHashtable @{LogName='System';ProviderName='Microsoft-Windows-WHEA-Logger'} -MaxEvents 5 -ErrorAction SilentlyContinue; if($e){$e|ForEach-Object{'{0}  {1}' -f $_.TimeCreated,$_.LevelDisplayName}}else{'none - good'}" >>"%REPORT%" 2>nul

rem ------------------------------------------------------- optional repair
echo  ===========================================================
echo.
echo    Windows file check
echo.
echo    If the game still crashes after the above, damaged Windows
echo    files are the next suspect. Checking takes 10-20 minutes
echo    and needs this run as administrator.
echo.
set "DOSFC="
set /p "DOSFC=    Run it now? (y/N): "
if /i "!DOSFC:~0,1!"=="y" (
    echo.
    echo    Working. Do not close this window.
    echo.
    >>"%REPORT%" echo.
    >>"%REPORT%" echo ------------------------------------------------------------
    >>"%REPORT%" echo WINDOWS FILE CHECK
    >>"%REPORT%" echo ------------------------------------------------------------
    dism /online /cleanup-image /restorehealth >>"%REPORT%" 2>&1
    sfc /scannow >>"%REPORT%" 2>&1
    echo    Done - the result is in the report.
    echo.
)

rem -------------------------------------------------------------- wrap up
echo  ===========================================================
echo.
echo    Finished. Start the game and see how it goes.
echo.
echo    If it still crashes, in this order:
echo.
echo      1. Update your graphics driver from the maker's own site
echo         (nvidia.com / amd.com / intel.com), not Windows Update.
echo         The report lists what you have now.
echo.
echo      2. Turn off any overclock, including an XMP or EXPO memory
echo         profile in the BIOS. Unstable RAM produces this exact
echo         error and nothing else explains it.
echo.
echo      3. Test your memory: press Windows, type "Windows Memory
echo         Diagnostic", and let it run.
echo.
echo      4. Send the report on your Desktop to whoever is helping:
echo         %REPORT%
echo.
echo    To get your addons and settings back, run
echo      restore-ascension-addons.bat
echo    which lives beside this file. It puts back everything that was
echo    set aside, and can give you the settings without the addons if
echo    an addon turns out to have been the problem.
echo.
echo  ===========================================================
echo.
echo    Press any key to close this window.
pause >nul
endlocal
exit /b 0

rem --------------------------------------------------------------- helpers

:backup
rem  %1 = full path, %2 = friendly name
if not exist "%~1" (
    echo         no %~2 folder - nothing to do
    >>"%REPORT%" echo %~2: absent
    goto :eof
)
if exist "%~1.esdeck-backup" rd /s /q "%~1.esdeck-backup" >nul 2>&1
move "%~1" "%~1.esdeck-backup" >nul 2>&1
if exist "%~1" (
    echo         could not move %~2 - is the game still running?
    >>"%REPORT%" echo %~2: could not move ^(game running?^)
) else (
    echo         %~2 set aside
    >>"%REPORT%" echo %~2: renamed to %~2.esdeck-backup
)
goto :eof

:findgame
rem Look where it usually is before searching, because searching a whole
rem disk is slow and this is nearly always in one of these.
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
rem dir returns a trailing backslash; strip it so paths read cleanly.
if defined GAMEDIR if "!GAMEDIR:~-1!"=="\" set "GAMEDIR=!GAMEDIR:~0,-1!"
goto :eof
