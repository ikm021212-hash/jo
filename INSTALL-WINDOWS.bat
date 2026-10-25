@echo off
setlocal
chcp 65001 >nul
title SmallCloset - Install
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows.ps1" -Mode Install
set "smallcloset_exit=%errorlevel%"
if not "%smallcloset_exit%"=="0" echo Installation failed. Please copy the error above when asking for help.
pause
exit /b %smallcloset_exit%
