$ErrorActionPreference = 'Stop'

$root = 'D:\Napcat'
$lockPath = Join-Path $root 'version-lock.json'
$napcatVersionPath = Join-Path $root 'app\VERSION'
$pinnedQq = 'D:\Napcat\QQNT-9.9.36\QQ.exe'
$qqPath = if (Test-Path $pinnedQq) { $pinnedQq } else { 'C:\Program Files\Tencent\QQNT\QQ.exe' }
$logDir = 'C:\你的用户\CompanionStartup\logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir 'napcat-version-check.log'

function Write-Log([string]$msg) {
    Add-Content -Path $log -Value ('[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg)
}

try {
    if (-not (Test-Path $lockPath)) { throw 'version-lock.json not found' }
    if (-not (Test-Path $napcatVersionPath)) { throw 'NapCat VERSION file not found' }
    if (-not (Test-Path $qqPath)) { throw 'QQ.exe not found' }

    $lock = Get-Content $lockPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $actualQq = (Get-Item $qqPath).VersionInfo.FileVersion
    $actualNapcat = (Get-Content $napcatVersionPath -Raw -Encoding UTF8).Trim()

    Write-Log ('lock: qq={0} napcat={1}' -f $lock.qq, $lock.napcat)
    Write-Log ('actual: qq={0} napcat={1}' -f $actualQq, $actualNapcat)

    if ($actualQq -ne $lock.qq -or $actualNapcat -ne $lock.napcat) {
        $msg = 'VERSION MISMATCH: QQ={0} NapCat={1}; lock expects QQ={2} NapCat={3}. Update NapCat or restore QQ, then edit D:\Napcat\version-lock.json.' -f $actualQq, $actualNapcat, $lock.qq, $lock.napcat
        Write-Log $msg
        Set-Content -Path (Join-Path $root 'VERSION-MISMATCH.txt') -Value $msg -Encoding UTF8
        Write-Error $msg
        exit 1
    }

    Remove-Item (Join-Path $root 'VERSION-MISMATCH.txt') -Force -ErrorAction SilentlyContinue
    Write-Log 'versions aligned'
    exit 0
} catch {
    $msg = 'VERSION CHECK FAILED: ' + $_.Exception.Message
    Write-Log $msg
    Set-Content -Path (Join-Path $root 'VERSION-MISMATCH.txt') -Value $msg -Encoding UTF8
    Write-Error $msg
    exit 1
}
