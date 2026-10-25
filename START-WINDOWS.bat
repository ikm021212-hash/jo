@echo off
setlocal
chcp 65001 >nul
title SmallCloset - Run
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows.ps1" -Mode Run
set "smallcloset_exit=%errorlevel%"
if not "%smallcloset_exit%"=="0" (
    echo Startup failed. Please copy the error above when asking for help.
    pause
)
exit /b %smallcloset_exit%
