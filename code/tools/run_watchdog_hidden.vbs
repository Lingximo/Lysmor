' Run watch_servers.ps1 with no visible console window.
' Windows shows a PowerShell window for a few seconds if the scheduled task
' starts powershell.exe directly; wscript with window style 0 avoids the flash.
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
sh.Run "powershell -NoProfile -ExecutionPolicy Bypass -File """ & dir & "\watch_servers.ps1""", 0, False
