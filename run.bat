@echo off
title Windows Audio Auto-Mute Guardian
cd /d "%~dp0"
echo =========================================================
echo  Starting Windows Audio Auto-Mute Guardian...
echo  Press Ctrl+C or close this window to stop protection.
echo =========================================================
echo.
py audio_auto_mute.py
if %errorlevel% neq 0 (
    python audio_auto_mute.py
)
