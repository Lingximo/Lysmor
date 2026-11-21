param(
    [ValidateSet('desktop', 'phone')][string]$Mode = 'desktop',
    [switch]$DryRun
)
# TA视频通话启动器：确保服务在跑 -> 等端口就绪 -> 打开浏览器
# 电脑版开 127.0.0.1；手机版挑局域网 IP 并带上口令，省得首次被 403 挡在门外。
# 注意：本文件必须存成 UTF-8 带 BOM，PowerShell 5.1 才认中文。

$ErrorActionPreference = 'SilentlyContinue'

$Root = 'D:\你的数据目录\video'
$Py = 'C:\你的用户\.astrbot_launcher\instances\<BOT_INSTANCE>\venv\Scripts\python.exe'
$TokenFile = 'D:\你的数据目录\gate_token.txt'
$LogFile = 'D:\你的数据目录\logs\video-launch.log'
$HttpPort = 8003

function Write-Log([string]$message) {
    $dir = Split-Path -Parent $LogFile
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    $line = '{0} [{1}] {2}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Mode, $message
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

function Get-Listener {
    return @(Get-NetTCPConnection -LocalPort $HttpPort -State Listen)
}

function Ensure-Server {
    $conn = Get-Listener
    # 只在「已经跑着但只绑了回环」时才重启：那种实例手机连不上
    $loopbackOnly = @($conn | Where-Object { $_.LocalAddress -in @('127.0.0.1', '::1') })
    if ($loopbackOnly.Count -gt 0) {
        Write-Log 'existing server is loopback-only, restarting to 0.0.0.0'
        $loopbackOnly | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
        Start-Sleep -Milliseconds 900
        $conn = @()
    }
    if (@(Get-Listener).Count -eq 0) {
        $env:VIDEO_HOST = '0.0.0.0'
        $env:VIDEO_PORT = "$HttpPort"
        $outLog = 'D:\你的数据目录\logs\video.out.log'
        $errLog = 'D:\你的数据目录\logs\video.err.log'
        Start-Process -FilePath $Py -ArgumentList "$Root\server.py" `
            -WorkingDirectory $Root -WindowStyle Hidden `
            -RedirectStandardOutput $outLog -RedirectStandardError $errLog
        Write-Log 'server process started'
    }
    for ($i = 0; $i -lt 60; $i++) {
        # 用 @(...) 包一层：函数只返回一个对象时 (Get-Listener).Count 是空的，会误判端口没起来
        if (@(Get-Listener).Count -gt 0) {
            Write-Log 'port is ready'
            return $true
        }
        Start-Sleep -Milliseconds 250
    }
    Write-Log 'server did not open the port within 15s'
    return $false
}

function Get-LanIp {
    # 优先真正的局域网（192.168.x），排除 Windows 热点网卡 192.168.137.1；
    # 蒲公英是 172.16.x，不能当手机地址，所以只做兜底。
    $candidates = @(
        Get-NetIPAddress -AddressFamily IPv4 |
            Where-Object { $_.IPAddress -like '192.168.*' -and $_.IPAddress -notlike '192.168.137.*' } |
            Select-Object -ExpandProperty IPAddress
    )
    if ($candidates.Count -eq 0) {
        $candidates = @(
            Get-NetIPAddress -AddressFamily IPv4 |
                Where-Object { $_.IPAddress -like '192.168.*' } |
                Select-Object -ExpandProperty IPAddress
        )
    }
    if ($candidates.Count -eq 0) { return $null }
    return $candidates[0]
}

function Get-GateToken {
    if (-not (Test-Path $TokenFile)) { return '' }
    $raw = Get-Content -Path $TokenFile -Raw -Encoding UTF8
    return $raw.Trim().TrimStart([char]0xFEFF)
}

$ready = Ensure-Server

if ($Mode -eq 'desktop') {
    $url = 'http://127.0.0.1:{0}/' -f $HttpPort
} else {
    $ip = Get-LanIp
    if (-not $ip) {
        Write-Log 'no LAN address found'
        if (-not $DryRun) { [System.Windows.Forms.MessageBox]::Show('没找到局域网地址，手机连不上。检查一下 Wi-Fi。') }
        return
    }
    $token = Get-GateToken
    if ($token) {
        $url = 'http://{0}:{1}/?t={2}' -f $ip, $HttpPort, $token
    } else {
        $url = 'http://{0}:{1}/' -f $ip, $HttpPort
        Write-Log 'gate token missing; url has no token'
    }
    Write-Log ("phone url: " + ($url -replace 't=[^&]+', 't=***'))
}

if ($DryRun) {
    Write-Output ("ready=" + $ready)
    Write-Output $url
    return
}
Start-Process $url
