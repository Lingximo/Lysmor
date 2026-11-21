@echo off
rem ��������㳪�����Ĭ�� http://127.0.0.1:18620����������ڱ��
set ROOT=%~dp0
if exist D:\companion\sing\venv set ROOT=D:\companion\sing\
"%ROOT%venv\Scripts\python.exe" "%ROOT%sing_server.py" --soulx "%ROOT%SoulX-Singer" --model "%ROOT%models\SoulX-Singer\model.pt"
pause
