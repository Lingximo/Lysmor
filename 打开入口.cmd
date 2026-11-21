@echo off
rem ============================================================
rem  打开入口 - 双击启动服务并打开总入口页（无黑窗口）
rem ============================================================
where pythonw >nul 2>nul
if errorlevel 1 (
  python open_entry.py
  if errorlevel 1 echo 启动失败：请确认已安装 Python 3.12（勾选 Add to PATH） && pause
) else (
  start "" pythonw open_entry.py
)
