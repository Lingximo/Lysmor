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

Write-Host 'Starting services ...'
& $python $entry --no-browser
Start-Sleep -Seconds 3

$port = 8009
$token = ''
try {
    $cfg = Get-Content (Join-Path $Root 'config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ($cfg.ports -and $cfg.ports.hub) { $port = [int]$cfg.ports.hub }
    if ($cfg.gate_token) { $token = [string]$cfg.gate_token }
} catch {
    Write-Host 'config.json unreadable - using default Hub port 8009.'
}

$url = "http://127.0.0.1:$port/"
if ($token) { $url = "http://127.0.0.1:$port/?t=$token" }
Write-Host "Opening $url"
Start-Process $url

Write-Host 'Done.'
