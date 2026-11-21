# 一键准备 Pico 浮窗（电脑端）
# 用法：powershell -ExecutionPolicy Bypass -File D:\你的数据目录\tools\pico_start.ps1

$ErrorActionPreference = "SilentlyContinue"
$venv = "C:\你的用户\.astrbot_launcher\instances\<BOT_INSTANCE>\venv\Scripts\python.exe"
$edge = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
$log  = "D:\你的数据目录\logs\pico_start.log"

function Log($m) { Add-Content $log ("{0} {1}" -f (Get-Date -Format "HH:mm:ss"), $m) -Encoding UTF8 }

# 1) 视频服务 8003
if (-not (Get-NetTCPConnection -LocalPort 8003 -State Listen)) {
    Log "启动视频服务 8003"
    Start-Process -FilePath $venv -ArgumentList @("-u", "-X", "utf8", "D:\你的数据目录\video\server.py") `
        -WorkingDirectory "D:\你的数据目录\video" -WindowStyle Hidden `
        -RedirectStandardOutput "D:\你的数据目录\logs\video.out.log" `
        -RedirectStandardError "D:\你的数据目录\logs\video.err.log" | Out-Null
    Start-Sleep -Seconds 8
}

# 2) 面板流 8014
if (-not (Get-NetTCPConnection -LocalPort 8014 -State Listen)) {
    Log "启动面板流 8014"
    Start-Process -FilePath $venv -ArgumentList @("-u", "-X", "utf8", "D:\你的数据目录\video\panel_stream.py") `
        -WindowStyle Hidden `
        -RedirectStandardOutput "D:\你的数据目录\logs\panel.out.log" `
        -RedirectStandardError "D:\你的数据目录\logs\panel.err.log" | Out-Null
    Start-Sleep -Seconds 3
}

# 3) Edge 面板窗口
$has = $false
Get-Process msedge | ForEach-Object { if ($_.MainWindowTitle -like "*和TA视频*") { $has = $true } }
if (-not $has) {
    Log "打开 Edge 面板窗口"
    $url = "http://127.0.0.1:8003/?panel=1&r=" + [int](Get-Date -UFormat %s)
    Start-Process -FilePath $edge -ArgumentList @(
        "--app=$url", "--window-size=1024,960", "--window-position=90,60",
        "--user-data-dir=D:\你的数据目录\logs\edge_panel_start"
    ) -WindowStyle Normal | Out-Null
    Start-Sleep -Seconds 8
}

# 4) 报告
$v = if (Get-NetTCPConnection -LocalPort 8003 -State Listen) { "OK" } else { "DOWN" }
$p = if (Get-NetTCPConnection -LocalPort 8014 -State Listen) { "OK" } else { "DOWN" }
$age = "?"
try { $age = (Invoke-RestMethod "http://127.0.0.1:8014/panel/status" -TimeoutSec 5).age } catch { }
Write-Host ("视频 8003: {0}  面板 8014: {1}  画面年龄: {2}s" -f $v, $p, $age)
Write-Host "头显里打开 CompanionWindow 即可。"
