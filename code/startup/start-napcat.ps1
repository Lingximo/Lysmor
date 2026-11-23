$ErrorActionPreference = 'SilentlyContinue'

$logDir = 'C:\你的用户\CompanionStartup\logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir 'napcat-startup.log'

function Write-Log([string]$msg) {
    Add-Content -Path $log -Value ('[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg)
}

Write-Log '--- NapCat startup check ---'

# 本脚本不锁 QQ / NapCat 版本：用哪个版本由使用者和 NapCat 官方文档决定。
if (Get-Process NapCatWinBootMain -ErrorAction SilentlyContinue) {
    Write-Log 'NapCatWinBootMain is already running'
    exit 0
}

for ($i = 0; $i -lt 90; $i++) {
    if (Get-NetTCPConnection -State Listen -LocalPort 8011 -ErrorAction SilentlyContinue) {
        Write-Log 'AstrBot port 8011 is ready'
        break
    }
    Start-Sleep -Seconds 1
}

$qq = Get-Process QQ -ErrorAction SilentlyContinue
if ($qq) {
    Write-Log 'QQ is running without NapCat; closing it before injection'
    $qq | Stop-Process -Force
    Start-Sleep -Seconds 4
}

# 改成你自己的 NapCat 安装目录（默认 C:\NapCat\app）。
$napcatApp = $env:NAPCAT_APP
if (-not $napcatApp) { $napcatApp = 'C:\NapCat\app' }
$bat = Join-Path $napcatApp 'launcher.bat'
Write-Log ('Starting NapCat launcher (hidden): ' + $bat)
Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', ('"{0}"' -f $bat) -WorkingDirectory $napcatApp -WindowStyle Hidden

for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 1
    if (Get-Process NapCatWinBootMain -ErrorAction SilentlyContinue) {
        Write-Log 'NapCatWinBootMain started'
        Start-Sleep -Seconds 15
        $quick = Join-Path $PSScriptRoot 'napcat-quicklogin.ps1'
        if (Test-Path $quick) { & $quick }
        exit 0
    }
}

Write-Log 'NapCatWinBootMain did not start within 60 seconds'
exit 1


