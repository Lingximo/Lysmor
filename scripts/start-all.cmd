@echo off
rem ============================================================
rem  Companion launcher - double-click entry
rem  Edit scripts\start-all.ps1 before first use.
rem ============================================================
echo Starting companion services ...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-all.ps1"
pause
