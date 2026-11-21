# 保证 Pico 的 alpha 帧链路一直活着：8003 + 8014 + Edge 面板
$ErrorActionPreference = "SilentlyContinue"
$py = "C:\你的用户\.astrbot_launcher\instances\<BOT_INSTANCE>\venv\Scripts\python.exe"
$edge = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
$log = "D:\你的数据目录\logs\alpha_watch.log"

function Log($m) { Add-Content $log ("{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $m) -Encoding UTF8 }

if (-not (Get-NetTCPConnection -LocalPort 8003 -State Listen)) {
    Log "启动 8003"
    Start-Process -FilePath $py -ArgumentList @("-u", "-X", "utf8", "D:\你的数据目录\video\server.py") `
        -WorkingDirectory "D:\你的数据目录\video" -WindowStyle Hidden `
        -RedirectStandardOutput "D:\你的数据目录\logs\video.out.log" `
        -RedirectStandardError "D:\你的数据目录\logs\video.err.log" | Out-Null
    Start-Sleep -Seconds 8
}

if (-not (Get-NetTCPConnection -LocalPort 8014 -State Listen)) {
    Log "启动 8014"
    Start-Process -FilePath $py -ArgumentList @("-u", "-X", "utf8", "D:\你的数据目录\video\panel_stream.py") `
        -WindowStyle Hidden -RedirectStandardOutput "D:\你的数据目录\logs\panel.out.log" `
        -RedirectStandardError "D:\你的数据目录\logs\panel.err.log" | Out-Null
    Start-Sleep -Seconds 3
}

# 用命令行识别面板进程，标题匹配不可靠，避免每 5 分钟重复开窗口
$has = [bool](Get-CimInstance Win32_Process -Filter "Name='msedge.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like '*edge_panel_start*' -and $_.CommandLine -like '*panel=1*' })
if (-not $has) {
    Log "打开 Edge 面板（屏幕外）"
    $url = "http://127.0.0.1:8003/?panel=1&r=" + [int](Get-Date -UFormat %s)
    Start-Process -FilePath $edge -ArgumentList @(
        "--app=$url", "--window-size=1024,960", "--window-position=-32000,-32000",
        "--user-data-dir=D:\你的数据目录\logs\edge_panel_start"
    ) -WindowStyle Normal | Out-Null
    Start-Sleep -Seconds 8
}

try {
    $r = Invoke-WebRequest "http://127.0.0.1:8003/panel/frame.png" -UseBasicParsing -TimeoutSec 6
    if ($r.StatusCode -ne 200 -or $r.RawContentLength -lt 2000) { Log ("alpha 帧异常: " + $r.StatusCode + " " + $r.RawContentLength) }
} catch {
    Log ("alpha 取不到: " + $_.Exception.Message)
}
