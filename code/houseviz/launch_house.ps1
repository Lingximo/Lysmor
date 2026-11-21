# 打开"TA的大平层"俯视图：先确保 8007 在跑，再用默认浏览器打开。
# 只在没监听时才拉起服务；已开着就直接开页面（不会重复起进程）。
$ErrorActionPreference = "SilentlyContinue"

$venv = "C:\你的用户\.astrbot_launcher\instances\<BOT_INSTANCE>\venv\Scripts\python.exe"
$log  = "D:\你的数据目录\logs\8007.out.log"
$err  = "D:\你的数据目录\logs\8007.err.log"
$url  = "http://127.0.0.1:8007/"

function Test-HousePort {
    $conn = Get-NetTCPConnection -LocalPort 8007 -State Listen -ErrorAction SilentlyContinue
    return [bool]$conn
}

if (-not (Test-HousePort)) {
    New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null
    Start-Process -FilePath $venv `
        -ArgumentList @("-X", "utf8", "D:\你的数据目录\houseviz\server.py") `
        -WindowStyle Hidden `
        -RedirectStandardOutput $log `
        -RedirectStandardError $err | Out-Null
    for ($i = 0; $i -lt 24; $i++) {
        Start-Sleep -Milliseconds 500
        if (Test-HousePort) { break }
    }
}

Start-Process $url
