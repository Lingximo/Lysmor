@echo off
REM ============================================================
REM  Companion watchdog setup (run ONCE, as administrator)
REM  - registers "Companion-Watchdog": run watch_servers.ps1 every 3 minutes
REM  - watch_servers.ps1 keeps pages alive + refreshes emotion state
REM    (emotion_construct.py / expect_gap.py)
REM  Usage:  install_watchdog.cmd            install
REM          install_watchdog.cmd /uninstall remove
REM ============================================================
setlocal
set TASK=Companion-Watchdog

if /I "%~1"=="/uninstall" goto uninstall

schtasks /Create /TN "%TASK%" /TR "wscript.exe //B //Nologo \"%~dp0run_watchdog_hidden.vbs\"" /SC MINUTE /MO 3 /F
if %errorlevel%==0 (
  echo [OK] Registered: %TASK%  ^(runs every 3 minutes^)
) else (
  echo [FAIL] Could not register. Right-click this file and "Run as administrator".
)
pause
exit /b 0

:uninstall
schtasks /Delete /TN "%TASK%" /F
if %errorlevel%==0 (
  echo [OK] Removed: %TASK%
) else (
  echo [INFO] Task not found.
)
pause
exit /b 0
