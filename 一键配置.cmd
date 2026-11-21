@echo off
rem ============================================================
rem  一键配置向导 - double-click entry（无黑窗口）
rem ============================================================
start "" http://127.0.0.1:8090/
where pythonw >nul 2>nul
if errorlevel 1 (
  python setup\server.py
) else (
  start "" pythonw setup\server.py
)
