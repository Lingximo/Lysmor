# Turn off the monitor only. The PC keeps running: QQ, AstrBot and NapCat stay online.
# 2026-11-04: replaces the old hibernate shortcut, which hung this machine.
$sig = @'
[DllImport("user32.dll")]
public static extern int SendMessage(int hWnd, int hMsg, int wParam, int lParam);
'@
$mon = Add-Type -MemberDefinition $sig -Name "MonPower" -Namespace Win32 -PassThru
# HWND_BROADCAST=0xffff, WM_SYSCOMMAND=0x0112, SC_MONITORPOWER=0xF170, 2=off
[void]$mon::SendMessage(0xffff, 0x0112, 0xF170, 2)
