param([switch]$Restart)

$ErrorActionPreference = 'SilentlyContinue'

$root = 'C:\你的用户\.astrbot_launcher\instances\<BOT_INSTANCE>'
$logDir = 'C:\你的用户\CompanionStartup\logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir 'astrbot-startup.log'

function Write-Log([string]$msg) {
    Add-Content -Path $log -Value ('[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg)
}

Write-Log '--- AstrBot startup check ---'

# 同步《助手守则》到各个工作目录（2026-11-10）
try { & 'D:\你的数据目录\tools\sync_agent_rules.ps1' } catch { }

# -Restart: really restart. Without it, an already-listening AstrBot means
# "nothing to do" (exit 0) -- that silent no-op ate the 2026-11-04 16:27 restart
# and the metadata patch never loaded (see handoff section 44.2).
if ($Restart) {
    $listener = Get-NetTCPConnection -State Listen -LocalPort 8011 -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($listener) {
        Write-Log ('Restart requested: stopping AstrBot pid ' + $listener.OwningProcess)
        Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue
        for ($i = 0; $i -lt 20; $i++) {
            if (-not (Get-NetTCPConnection -State Listen -LocalPort 8011 -ErrorAction SilentlyContinue)) { break }
            Start-Sleep -Seconds 1
        }
        if (Get-NetTCPConnection -State Listen -LocalPort 8011 -ErrorAction SilentlyContinue) {
            Write-Log 'Restart failed: port 8011 is still held'
            exit 1
        }
        Write-Log 'AstrBot stopped; starting a fresh one'
    } else {
        Write-Log 'Restart requested but nothing is listening on 8011'
    }
}

if (Get-NetTCPConnection -State Listen -LocalPort 8011 -ErrorAction SilentlyContinue) {
    Write-Log 'Port 8011 already listening; AstrBot is already running'
    exit 0
}

if (-not (Get-NetTCPConnection -State Listen -LocalPort 11434 -ErrorAction SilentlyContinue)) {
    $ollama = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
    if (Test-Path $ollama) {
        Write-Log 'Ollama is not running; starting ollama serve'
        Start-Process -FilePath $ollama -ArgumentList 'serve' -WindowStyle Hidden
    } else {
        Write-Log 'Ollama executable not found'
    }
} else {
    Write-Log 'Ollama already listening on 11434'
}

for ($i = 0; $i -lt 30; $i++) {
    if (Get-NetTCPConnection -State Listen -LocalPort 11434 -ErrorAction SilentlyContinue) {
        break
    }
    Start-Sleep -Seconds 1
}
if (-not (Get-NetTCPConnection -State Listen -LocalPort 11434 -ErrorAction SilentlyContinue)) {
    Write-Log 'Warning: Ollama still not listening after 30 seconds'
}

$python = Join-Path $root 'venv\Scripts\python.exe'
$core = Join-Path $root 'core'
$outLog = Join-Path $logDir 'astrbot.out.log'
$errLog = Join-Path $logDir 'astrbot.err.log'

Write-Log ('Starting AstrBot: {0}' -f $python)
Start-Process -FilePath $python -ArgumentList '-X', 'utf8', 'main.py' -WorkingDirectory $core -WindowStyle Hidden -RedirectStandardOutput $outLog -RedirectStandardError $errLog | Out-Null

for ($i = 0; $i -lt 90; $i++) {
    Start-Sleep -Seconds 1
    if (Get-NetTCPConnection -State Listen -LocalPort 8011 -ErrorAction SilentlyContinue) {
        Write-Log 'AstrBot is listening on 8011'
        exit 0
    }
}

Write-Log 'AstrBot did not open port 8011 within 90 seconds'
exit 1
