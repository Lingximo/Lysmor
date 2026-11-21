param(
    [string]$Project = 'D:\你的数据目录\lab\pico\unity\CompanionWindow',
    [string]$Apk = 'D:\dev\companion-window.apk',
    [switch]$Install
)

$ErrorActionPreference = 'Stop'
$unity = 'D:\Unity\2022.3.62f2\Editor\Unity.exe'
$log = Join-Path $Project '..\..\build_pico_guard.log'
$env:JAVA_HOME = 'D:\dev\jdk-11.0.33+10'
$env:ANDROID_HOME = 'D:\dev\android-sdk'
$env:ANDROID_SDK_ROOT = 'D:\dev\android-sdk'
$env:ANDROID_NDK_ROOT = 'D:\dev\android-sdk\ndk\23.1.7779620'

if (Test-Path $log) { Remove-Item $log -Force }
$before = if (Test-Path $Apk) { (Get-Item $Apk).LastWriteTimeUtc } else { [datetime]::MinValue }

$p = Start-Process -FilePath $unity -ArgumentList @(
    '-batchmode', '-quit', '-projectPath', $Project,
    '-executeMethod', 'Companion.Editor.SetupAndBuild.Build',
    '-logFile', $log
) -Wait -PassThru

$errors = @(Select-String -Path $log -Pattern 'error CS\d+' -ErrorAction SilentlyContinue)
$success = Select-String -Path $log -Pattern 'Build Finished, Result: Success' -ErrorAction SilentlyContinue
$apkTime = if (Test-Path $Apk) { (Get-Item $Apk).LastWriteTimeUtc } else { [datetime]::MinValue }

if ($p.ExitCode -ne 0 -or $errors.Count -gt 0 -or -not $success -or $apkTime -le $before) {
    Write-Host "BUILD REJECTED" -ForegroundColor Red
    Write-Host "exit=$($p.ExitCode) errors=$($errors.Count) success=$([bool]$success) apkNew=$($apkTime -gt $before)"
    $errors | Select-Object -First 10 | ForEach-Object { $_.Line.Trim() }
    exit 1
}

Write-Host "BUILD OK: $Apk  $apkTime" -ForegroundColor Green
if ($Install) {
    $adb = 'D:\dev\android-sdk\platform-tools\adb.exe'
    & $adb install -r $Apk
    if ($LASTEXITCODE -ne 0) { throw "adb install failed" }
    Write-Host "INSTALLED" -ForegroundColor Green
}
