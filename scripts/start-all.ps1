# ============================================================
#  Companion launcher
#
#  Starts the full stack through open_entry.py:
#    Hub / web chat / video call / life panel / memory map / 3D room
#  then opens the Hub page.
#
#  First run: if config.json does not exist yet, this opens the setup
#  wizard instead.
# ============================================================

$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

# Prefer the launcher on PATH; fall back to the py launcher.
function Get-Python {
    if (Get-Command python -ErrorAction SilentlyContinue) { return 'python' }
    if (Get-Command py -ErrorAction SilentlyContinue) { return 'py' }
    return $null
}

$python = Get-Python
if (-not $python) {
    Write-Host 'Python not found. Install Python 3.12 and tick "Add to PATH".'
    exit 1
}

$entry = Join-Path $Root 'open_entry.py'
if (-not (Test-Path $entry)) {
    Write-Host "open_entry.py not found in $Root"
    exit 1
}

if (-not (Test-Path (Join-Path $Root 'config.json'))) {
    Write-Host 'No config.json yet - opening the setup wizard ...'
    & $python $entry
    exit $LASTEXITCODE
}

# 先读端口：后面要用它判断“服务真的起来了没有”
$port = 8009
$token = ''
try {
    $cfg = Get-Content (Join-Path $Root 'config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($cfg.ports -and $cfg.ports.hub) { $port = [int]$cfg.ports.hub }
    if ($cfg.gate_token) { $token = [string]$cfg.gate_token }
} catch {
    Write-Host 'config.json unreadable - using default Hub port 8009.'
}

Write-Host 'Starting services ...'
& $python $entry --no-browser

# 2026-11-26：以前固定睡 3 秒就打开浏览器，机器慢/首次启动时 Hub 还没监听，
# 浏览器显示“连接被拒绝”（粉丝反馈的就是这个）。现在最多等 90 秒。
$deadline = (Get-Date).AddSeconds(90)
$up = $false
while ((Get-Date) -lt $deadline) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $client.Connect('127.0.0.1', $port)
        $up = $true
    } catch {
    } finally {
        $client.Close()
    }
    if ($up) { break }
    Start-Sleep -Milliseconds 600
}
if (-not $up) {
    Write-Host "Hub 没有在 $port 端口起来（等了 90 秒）。"
    Write-Host "先看 logs\ 下 8009.err.log / 8009.out.log；也可以运行 python preflight.py 体检。"
    exit 1
}

$url = "http://127.0.0.1:$port/"
if ($token) { $url = "http://127.0.0.1:$port/?t=$token" }
Write-Host "Opening $url"
Start-Process $url

Write-Host 'Done.'
