@echo off
title Windows Audio Auto-Mute Guardian
cd /d "%~dp0"
echo =========================================================
echo  Starting Windows Audio Auto-Mute Guardian...
echo  Press Ctrl+C or close this window to stop protection.
echo =========================================================
echo.
where py >nul 2>&1
if %errorlevel% equ 0 (
    py audio_auto_mute.py %*
) else (
    python audio_auto_mute.py %*
)
