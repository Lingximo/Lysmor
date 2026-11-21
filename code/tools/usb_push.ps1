param([string]$Drive = "")
$ErrorActionPreference = "Stop"

$ROOT = "D:\你的数据目录"
$OUT  = Join-Path $ROOT "nirvana\out"
$PY   = "C:\你的用户\.astrbot_launcher\instances\<BOT_INSTANCE>\venv\Scripts\python.exe"
$TOOLS = Join-Path $ROOT "tools"

if (-not $Drive) {
    Write-Host "usage: usb_push.ps1 E:\"
    exit 1
}
if (-not (Test-Path $Drive)) {
    Write-Host "[FAIL] drive not found: $Drive"
    exit 1
}

$latest = Join-Path $OUT "latest.json"
if (-not (Test-Path $latest)) {
    Write-Host "[FAIL] latest.json missing, run the pack task first"
    exit 1
}
$meta = Get-Content $latest -Raw -Encoding UTF8 | ConvertFrom-Json
$pack = $meta.path
if (-not (Test-Path $pack)) {
    Write-Host "[FAIL] pack missing: $pack"
    exit 1
}

Write-Host "[1/5] local pack: $($meta.name)  $([math]::Round((Get-Item $pack).Length/1MB,1)) MB"

# 1) 打包内容自检（原创覆盖 + 无旧文件）
& $PY "$TOOLS\check_pack_original.py" | Out-Host
if ($LASTEXITCODE -ne 0) { Write-Host "[FAIL] pack check failed"; exit 1 }
& $PY "$TOOLS\check_pack_original.py" --junk | Out-Host
if ($LASTEXITCODE -ne 0) { Write-Host "[FAIL] pack has stale files"; exit 1 }

# 2) U 盘目录：整目录重建（不是叠加），保证和本地 kit 一模一样
$dir = Join-Path $Drive "nirvana-kit"
if (Test-Path $dir) {
    $files = Get-ChildItem $dir -Recurse -File -ErrorAction SilentlyContinue
    $mb = [math]::Round((($files | Measure-Object Length -Sum).Sum / 1MB), 1)
    Write-Host "[2/5] wipe old kit: $($files.Count) file(s), $mb MB"
    Remove-Item $dir -Recurse -Force
}
New-Item -ItemType Directory -Path $dir -Force | Out-Null

# 3) 拷最新一套（脚本 + 任务 + 整包）
Write-Host "[3/5] copy latest kit..."
$kit = Join-Path $ROOT "nirvana\out\kit"
if (Test-Path $kit) {
    Copy-Item (Join-Path $kit "*") $dir -Recurse -Force
} else {
    Copy-Item $pack (Join-Path $dir $meta.name) -Force
}
$readme = Join-Path $ROOT "nirvana\新电脑复活-先读我.md"
if (Test-Path $readme) { Copy-Item $readme (Join-Path $Drive "新电脑复活-先读我.md") -Force }

# 4) 校验大小与 sha256
$dst = Join-Path $dir $meta.name
$srcHash = (Get-FileHash $pack -Algorithm SHA256).Hash.ToLower()
$dstHash = (Get-FileHash $dst -Algorithm SHA256).Hash.ToLower()
if ($srcHash -ne $dstHash) {
    Write-Host "[FAIL] sha256 mismatch after copy"
    exit 1
}
Write-Host "[4/5] sha256 ok: $($srcHash.Substring(0,16))..."

# 5) 台账
$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$log = Join-Path $ROOT "logs\usb-push.jsonl"
$line = '{"at":"' + $stamp + '","drive":"' + $Drive + '","pack":"' + $meta.name + '","mb":' + [math]::Round((Get-Item $dst).Length/1MB,1) + ',"removed":' + @($old).Count + '}'
Add-Content -Path $log -Value $line -Encoding UTF8

Write-Host "[5/5] done. stick content:"
Get-ChildItem $dir -File | Select-Object Name, @{n="MB";e={[math]::Round($_.Length/1MB,1)}} | Format-Table -AutoSize | Out-Host