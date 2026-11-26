@echo off
rem ============================================================
rem  Open entry - start services and open the hub page
rem  ASCII only on purpose: cmd.exe parses this file as GBK.
rem ============================================================
chcp 65001 >nul
setlocal

where python >nul 2>nul
if errorlevel 1 goto :nopython

rem --no-config: first run has no config.json yet; open_entry.py will open the wizard.
python "%~dp0preflight.py" --no-config
if errorlevel 1 (
  echo.
  echo [!] Fix the items above, then double-click this file again.
  pause
  exit /b 1
)

where pythonw >nul 2>nul
if errorlevel 1 (
  python "%~dp0open_entry.py"
) else (
  start "" pythonw "%~dp0open_entry.py"
)
exit /b 0

:nopython
echo.
echo [!] Python 3.12 was not found on PATH.
echo     Install it from https://www.python.org/downloads/
echo     Tick "Add python.exe to PATH" during setup, then double-click this file again.
echo.
pause
exit /b 1
