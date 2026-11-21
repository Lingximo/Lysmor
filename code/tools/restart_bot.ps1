# 重启TA（2026-11-17 重写：原文件混编码损坏，本文件统一 UTF-8 BOM）
# 用法：
#   .\restart_bot.ps1            # 重启 AstrBot + 页面 + 检查 QQ
#   .\restart_bot.ps1 -BotOnly   # 只重启 AstrBot
#   .\restart_bot.ps1 -PagesOnly # 只重启页面服务
#   .\restart_bot.ps1 -QR        # 强制处理 QQ 扫码
param([switch]$BotOnly, [switch]$PagesOnly, [switch]$QR, [switch]$QROnly)

$ErrorActionPreference = 'Continue'
$log = 'D:\你的数据目录\logs\restart-bot.log'
$venv = 'C:\你的用户\.astrbot_launcher\instances\<BOT_INSTANCE>\venv\Scripts\python.exe'

function L($m) {
    $line = '[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $m
    Add-Content -Path $log -Value $line -Encoding UTF8 -ErrorAction SilentlyContinue
    Write-Host $line
}
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

function Port-Owner([int]$port) {
    $c = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($c) { return [int]$c.OwningProcess }
    return 0
}

$PAGES = @(
    @{ Port = 8003; Script = 'D:\你的数据目录\video\server.py' },
    @{ Port = 8005; Script = 'D:\你的数据目录\lifeviz\server.py' },
    @{ Port = 8006; Script = 'D:\你的数据目录\brainviz\server.py' },
    @{ Port = 8007; Script = 'D:\你的数据目录\houseviz\server.py' },
    @{ Port = 8001; Script = 'D:\你的数据目录\webchat\server.py' },
    @{ Port = 8009; Script = 'D:\你的数据目录\hub\server.py' },
    @{ Port = 8008; Script = 'D:\你的数据目录\qqwatch\watch.py' }
)

function Start-Page($p) {
    $args = @('-X', 'utf8', $p.Script)
    Start-Process -FilePath $venv -ArgumentList $args -WindowStyle Hidden `
        -RedirectStandardOutput ('D:\你的数据目录\logs\' + $p.Port + '.out.log') `
        -RedirectStandardError ('D:\你的数据目录\logs\' + $p.Port + '.err.log')
}

# 1) AstrBot（用计划任务启动，保持与开机一致）
if (-not $PagesOnly) {
    L 'AstrBot: 停止计划任务 Companion-AstrBot'
    Stop-ScheduledTask -TaskName 'Companion-AstrBot' -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match 'main\.py' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 3
    L 'AstrBot: 启动'
    Start-ScheduledTask -TaskName 'Companion-AstrBot' -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 15
}

# 2) 页面服务
if (-not $BotOnly) {
    foreach ($p in $PAGES) {
        if ($p.Port -eq 8008 -and $QROnly) {
            $pidNow = Port-Owner $p.Port
            if ($pidNow) { Stop-Process -Id $pidNow -Force -ErrorAction SilentlyContinue }
            Start-Page $p
            L ('page ' + $p.Port + ': restarted')
            continue
        }
        $pidNow = Port-Owner $p.Port
        if ($pidNow) {
            L ('page ' + $p.Port + ': stopping pid ' + $pidNow)
            Stop-Process -Id $pidNow -Force -ErrorAction SilentlyContinue
            Start-Sleep -Milliseconds 400
        }
        Start-Page $p
        Start-Sleep -Milliseconds 800
        $pidAfter = Port-Owner $p.Port
        L ('page ' + $p.Port + ': ' + $(if ($pidAfter) { 'up pid ' + $pidAfter } else { 'DOWN' }))
    }
}

# 3) QQ（NapCat + qqwatch）
if (-not $PagesOnly) {
    $qqOk = $false
    try {
        $out = & $venv -X utf8 'D:\你的数据目录\tools\check_napcat.py' 2>&1
        $qqOk = ($out -join ' ') -match 'login.*True|已登录'
    } catch { }
    if (-not $qqOk -or $QR) {
        if (-not (Get-Process NapCatWinBootMain -ErrorAction SilentlyContinue)) {
            L 'NapCat 没在跑 -> 启动'
            & 'C:\你的用户\CompanionStartup\start-napcat.ps1' | Out-Null
            Start-Sleep -Seconds 10
        }
        if (-not (Get-Process pythonw -ErrorAction SilentlyContinue | Where-Object { $_.Id -eq (Port-Owner 8008) })) {
            $venvW = $venv -replace 'python\.exe$', 'pythonw.exe'
            Start-Process -FilePath $venvW -ArgumentList @('-X', 'utf8', 'D:\你的数据目录\qqwatch\watch.py') -WindowStyle Hidden
            Start-Sleep -Seconds 6
            L 'qqwatch 已启动'
        }
    }
}

# 4) 端口表
$PORTS = @(8003, 8005, 8006, 8007, 8001, 8009, 8008, 8011, 8012, 8013)
$down = @()
foreach ($p in $PORTS) {
    if (Port-Owner $p) { L ('port ' + $p + ': OK') } else { $down += $p; L ('port ' + $p + ': DOWN') }
}
if ($down.Count) { Write-Host ('DOWN: ' + ($down -join ', ')) } else { Write-Host 'ALL PORTS OK' }
