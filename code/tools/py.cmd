@echo off
rem Unified entry point: run tools scripts with the AstrBot venv python.
rem Why:
rem   1) "python" on PATH is the WindowsApps stub; components\python\py312
rem      has no requests, so check_napcat.py fails with ModuleNotFoundError.
rem   2) Console defaults to GBK, so emoji in script output raises
rem      UnicodeEncodeError and fakes exit code 1.
rem Usage: py.cmd check_memory_flow.py --line
rem        py.cmd memory_ledger.py --verify
rem Keep this file ASCII-only: cmd reads UTF-8 as GBK and executes the junk.
"C:\你的用户\.astrbot_launcher\instances\<BOT_INSTANCE>\venv\Scripts\python.exe" -X utf8 %*
