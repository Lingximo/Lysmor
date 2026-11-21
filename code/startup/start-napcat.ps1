$ErrorActionPreference = 'SilentlyContinue'

$logDir = 'C:\你的用户\CompanionStartup\logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir 'napcat-startup.log'

function Write-Log([string]$msg) {
    Add-Content -Path $log -Value ('[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg)
}

Write-Log '--- NapCat startup check ---'

# 永久对齐：QQ / NapCat 版本不匹配时直接拒绝启动，避免被踢后无限重启+扫码
& (Join-Path $PSScriptRoot 'check-napcat-version.ps1') 2>&1 | ForEach-Object { Write-Log $_ }
if ($LASTEXITCODE -ne 0) {
    Write-Log 'NapCat version check failed; refusing to start'
    exit 2
}

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

$bat = 'D:\Napcat\app\launcher.bat'
Write-Log 'Starting NapCat launcher (hidden)'
Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', ('"{0}"' -f $bat) -WorkingDirectory 'D:\Napcat\app' -WindowStyle Hidden

for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 1
    if (Get-Process NapCatWinBootMain -ErrorAction SilentlyContinue) {
        Write-Log 'NapCatWinBootMain started'
        Start-Sleep -Seconds 15
        & (Join-Path $PSScriptRoot 'napcat-quicklogin.ps1')
        exit 0
    }
}

Write-Log 'NapCatWinBootMain did not start within 60 seconds'
exit 1


