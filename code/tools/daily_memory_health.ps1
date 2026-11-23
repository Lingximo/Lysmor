# 每日记忆体检：把新记忆补进账本，然后写一行健康日志
$ErrorActionPreference = "SilentlyContinue"
$venv  = "C:\你的用户\.astrbot_launcher\instances\<BOT_INSTANCE>\venv\Scripts\python.exe"
$tools = "D:\你的数据目录\tools"

# 1) 新记忆入账（不改老记录）
& $venv -X utf8 "$tools\memory_ledger.py" --sync | Out-Null

# 2) 校验 + 写一行健康日志
$result = & $venv -X utf8 "$tools\check_memory_flow.py" --line --append
$result | Out-Host

# 3) 账本坏了就额外落一个告警文件，方便一眼看见
if ($result -match "ledger=FAIL" -or $result -match "ledger=NO-LEDGER") {
    $line = "{0} LEDGER BROKEN: {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $result
    Add-Content -Path "D:\你的数据目录\logs\memory-alert.log" -Value $line -Encoding UTF8
}

# 4) 完整备份还在不在、新不新
#    00:05 的插件清理曾经把 complete_*.db 每晚删掉，而所有检查还是绿的；
#    这一步在 00:20 跑，正好能抓住「刚被删」这种情况。
$bk = & $venv -X utf8 "$tools\check_backup_freshness.py"
if ($LASTEXITCODE -ne 0) {
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path "D:\你的数据目录\logs\memory-alert.log" -Value ("{0} BACKUP: {1}" -f $stamp, $bk) -Encoding UTF8
    Add-Content -Path "D:\你的数据目录\logs\memory-health.log" -Value ("[backup] {0} {1}" -f $stamp, $bk) -Encoding UTF8
}

# 5) 清掉孤儿 -wal/-shm
#    00:05 插件轮换自己的备份时只删 .db，会留下 0 字节 .db-wal 和 32KB .db-shm；
#    只删「对应的 .db 已经不存在」的，正在用的库和备份一律不碰。
$bdir = "D:\你的数据目录\livingmemory\backups"
Get-ChildItem $bdir -File -ErrorAction SilentlyContinue | Where-Object {
    $_.Name -match '\.db-(wal|shm)$' -and
    -not (Test-Path ($_.FullName -replace '\.db-(wal|shm)$', '.db'))
} | ForEach-Object {
    Remove-Item $_.FullName -Force -ErrorAction SilentlyContinue
}

# 6) 把「账本 + 纠错留档」也存一份到 backups\sidecar
#    数据库备份只覆盖 .db；账本和 corrections.jsonl 是"她当初记的是什么、为什么改"
#    的唯一凭据，跟着每天复制一份，坏了能对照回滚。
$side = "D:\你的数据目录\livingmemory\backups\sidecar"
New-Item -ItemType Directory -Path $side -Force -ErrorAction SilentlyContinue | Out-Null
foreach ($f in @("memory-text-ledger.json", "corrections.jsonl")) {
    $src = Join-Path "D:\你的数据目录\livingmemory" $f
    if (Test-Path $src) { Copy-Item $src (Join-Path $side $f) -Force -ErrorAction SilentlyContinue }
}

# 7) 生理状态体检（2026-10-31 加）
#    状态新鲜度 / 数值范围 / 体温 / 死亡威胁一致性 / 面板一致性
#    失败只告警，不改任何状态。
$vkOut = & "D:\你的数据目录\tools\py.cmd" "D:\你的数据目录\tools\check_vitals.py" 2>&1 | Out-String
$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$vkLine = ($vkOut.Trim() -replace "`r`n", " | ")
Add-Content -Path "D:\你的数据目录\logs\memory-health.log" -Value ("[vitals] {0} {1}" -f $stamp, $vkLine) -Encoding UTF8
if ($vkLine -match "FAIL|发现问题") {
    Add-Content -Path "D:\你的数据目录\logs\memory-alert.log" -Value ("{0} VITALS: {1}" -f $stamp, $vkLine) -Encoding UTF8
}

# 8) 情绪真实化（Phase B/E）：构造情绪 + 预期差
#    Phase B 的"实时构造"需要每 3 分钟跑一次；若没配 3 分钟计划任务，
#    这里在每日体检时至少跑一次（构造文件 >10 分钟会被插件当过期、回退原标签）。
& $venv -X utf8 "$tools\emotion_construct.py" | Out-Null
& $venv -X utf8 "$tools\expect_gap.py" | Out-Null
