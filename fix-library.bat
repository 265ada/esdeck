@echo off
rem ===========================================================================
rem  esdeck FIX - repair a library sorted by an older version.
rem
rem  Three jobs, in order:
rem    1. Remove artwork that was filed as games. An older esdeck treated .png
rem       as a game because ES-DE lists it for pico8 and tic80, so box art
rem       became library entries like "007 - The World Is Not Enough-image".
rem       Every system folder is checked, not just those two. Real PICO-8
rem       cartridges are identified and kept.
rem    2. Make the game controller player 1, so games stop seeing it as
rem       player 2. The keyboard keeps working.
rem    3. Offer to free the space taken by the Incoming copies, but only the
rem       ones proved byte-for-byte identical to what is in the library.
rem
rem  Steps 1 and 2 apply automatically. Step 3 asks twice before deleting.
rem
rem  Optional:  --no-pause   do not wait for a key at the end
rem ===========================================================================
setlocal enabledelayedexpansion
title esdeck - fix library
cd /d "%~dp0"

set "OPT_NOPAUSE="
for %%a in (%*) do if /i "%%~a"=="--no-pause" set "OPT_NOPAUSE=1"

echo.
echo  ===========================================================
echo    esdeck - fixing your library
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
    goto :fail
)

echo.
echo  ===========================================================
echo    1 of 3  Removing artwork that was filed as games
echo  ===========================================================
echo.
%ESDECK% cleanup --yes
echo.

echo  ===========================================================
echo    2 of 3  Making your controller player 1
echo  ===========================================================
echo.
%ESDECK% controller --yes
echo.

echo  ===========================================================
echo    3 of 3  Free the space used by the Incoming copies?
echo  ===========================================================
echo.
echo  Your games were COPIED into the library, so every one of them still
echo  exists a second time in your Incoming folder. That is duplicate space.
echo.
echo  This will DELETE files from Incoming - but only ones it has verified,
echo  byte for byte, are already in your library. Anything that does not
echo  match, or was never sorted, is kept.
echo.
echo  Your library is NOT touched either way.
echo.
%ESDECK% clean
echo.

set "GO1="
set /p "GO1=  Delete the verified Incoming copies listed above? [y/N] "
if /i not "%GO1%"=="y" (
    echo.
    echo  Keeping everything. Nothing was deleted.
    goto :ok
)

echo.
echo  ---------------------------------------------------------
echo   Second confirmation
echo  ---------------------------------------------------------
echo.
echo   You are about to permanently delete the source copies in your
echo   Incoming folder. They are your originals. Only do this if you
echo   are satisfied the games play correctly from ES-DE.
echo.
echo   Type DELETE in capitals to go ahead, or anything else to stop.
echo.
set "GO2="
set /p "GO2=  Confirm: "
if /i not "%GO2%"=="DELETE" (
    echo.
    echo  Stopped. Nothing was deleted.
    goto :ok
)

echo.
%ESDECK% clean --yes
echo.
echo  Incoming copies removed. Your library is untouched.
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
echo  ===========================================================
echo    Done - press F5 in ES-DE to refresh the game lists.
echo  ===========================================================
echo.
if not defined OPT_NOPAUSE (
    echo  Press any key to close this window.
    pause >nul
)
endlocal
exit /b 0
