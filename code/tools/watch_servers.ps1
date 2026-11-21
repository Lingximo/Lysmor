# 看门狗：面板服务挂了就拉起来（每 3 分钟跑一次）
# 由计划任务 Companion-ServerWatchdog 调用，也可以手动跑一遍
$ErrorActionPreference = "SilentlyContinue"
$venv = "C:\你的用户\.astrbot_launcher\instances\<BOT_INSTANCE>\venv\Scripts\python.exe"
$log = "D:\你的数据目录\logs\watchdog.log"
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null
$targets = @(
    @{ Port = 8003; Script = "D:\你的数据目录\video\server.py";    Name = "视频通话" },
    @{ Port = 8005; Script = "D:\你的数据目录\lifeviz\server.py";  Name = "生命状态" },
    @{ Port = 8006; Script = "D:\你的数据目录\brainviz\server.py"; Name = "记忆大脑" },
    @{ Port = 8007; Script = "D:\你的数据目录\houseviz\server.py"; Name = "大平层俯视图" },
    @{ Port = 8001; Script = "D:\你的数据目录\webchat\server.py";  Name = "她的网页" },
    @{ Port = 8010; Script = "D:\你的数据目录\lab\hands\hands_server.py"; Name = "她的手" },
    @{ Port = 8002; Script = "D:\你的数据目录\art\gallery_server.py"; Name = "简笔画画廊" },
    @{ Port = 8009; Script = "D:\你的数据目录\hub\server.py"; Name = "统一入口" }
)
function Write-Log($text) {
    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $text
    Add-Content -Path $log -Value $line -Encoding UTF8
}
# ---- Ollama / AstrBot / 生理状态 / 记忆队列（2026-11-01 加） ----
$ollama = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
if (-not (Get-NetTCPConnection -State Listen -LocalPort 11434 -ErrorAction SilentlyContinue)) {
    if (Test-Path $ollama) {
        Write-Log "Ollama(11434) 没在监听，重新拉起"
        Start-Process -FilePath $ollama -ArgumentList "serve" -WindowStyle Hidden | Out-Null
        Start-Sleep -Seconds 8
        $ok = Get-NetTCPConnection -State Listen -LocalPort 11434 -ErrorAction SilentlyContinue
        Write-Log ("Ollama(11434) " + $(if ($ok) { "已恢复" } else { "拉起失败" }))
    } else {
        Write-Log "Ollama(11434) 没在监听，且找不到 ollama.exe"
    }
}
if (-not (Get-NetTCPConnection -State Listen -LocalPort 8011 -ErrorAction SilentlyContinue)) {
    # 2026-11-12：开机时启动脚本和看门狗会各拉一次，导致两个 AstrBot 同时写记忆。
    # 先看有没有已经在启动中的 main.py，有就等它，不再拉第二个。
    $existing = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -match 'main\.py' -and $_.CommandLine -match '<BOT_INSTANCE>' }
    if ($existing) {
        Write-Log "AstrBot 进程已在启动中，等端口（不再重复拉起）"
        for ($i = 0; $i -lt 90; $i++) {
            Start-Sleep -Seconds 1
            if (Get-NetTCPConnection -State Listen -LocalPort 8011 -ErrorAction SilentlyContinue) { break }
        }
        $ok = Get-NetTCPConnection -State Listen -LocalPort 8011 -ErrorAction SilentlyContinue
        Write-Log ("AstrBot(8011) " + $(if ($ok) { "已恢复" } else { "等待超时，下轮再看" }))
    } else {
        Write-Log "AstrBot(8011) 没在监听，重新拉起"
        $vbs = "D:\你的数据目录\tools\spawn_hidden.vbs"
        $start = "C:\你的用户\CompanionStartup\start-astrbot.ps1"
        if ((Test-Path $vbs) -and (Test-Path $start)) {
            Start-Process -FilePath "$env:SystemRoot\System32\wscript.exe" `
                -ArgumentList @("//nologo", $vbs, ('"{0}"' -f $start)) -WindowStyle Hidden | Out-Null
        } else {
            Start-Process -FilePath $venv -ArgumentList @("-X", "utf8", "main.py") `
                -WorkingDirectory "C:\你的用户\.astrbot_launcher\instances\<BOT_INSTANCE>\core" `
                -WindowStyle Hidden | Out-Null
        }
        for ($i = 0; $i -lt 90; $i++) {
            Start-Sleep -Seconds 1
            if (Get-NetTCPConnection -State Listen -LocalPort 8011 -ErrorAction SilentlyContinue) { break }
        }
        $ok = Get-NetTCPConnection -State Listen -LocalPort 8011 -ErrorAction SilentlyContinue
        Write-Log ("AstrBot(8011) " + $(if ($ok) { "已恢复" } else { "拉起失败/超时" }))
    }
}
$state = "C:\你的用户\.astrbot_launcher\instances\<BOT_INSTANCE>\core\data\plugin_data\astrbot_plugin_companion_mood\state.json"
if (Test-Path $state) {
    $age = [int]((Get-Date) - (Get-Item $state).LastWriteTime).TotalSeconds
    if ($age -gt 600) {
        Write-Log ("生理状态 {0} 秒没更新（心跳可能停摆）" -f $age)
    }
}
$pending = "D:\你的数据目录\video\pending_memories.json"
if (Test-Path $pending) {
    try {
        $raw = Get-Content $pending -Raw -Encoding UTF8 | ConvertFrom-Json
        $n = if ($null -eq $raw) { 0 } else { @($raw).Count }
        if ($n -gt 20) {
            Write-Log ("记忆队列积压 {0} 条（消费者可能在重试）" -f $n)
        }
    } catch {
        Write-Log "记忆队列读取失败"
    }
}
# 记忆库 WAL 太大时做一次检查点（2026-11-09：WAL 曾涨到 4MB 以上不回收）
$lmemWal = "C:\你的用户\.astrbot_launcher\instances\<BOT_INSTANCE>\core\data\plugin_data\astrbot_plugin_livingmemory\livingmemory.db-wal"
if (Test-Path $lmemWal) {
    $walMb = [math]::Round((Get-Item $lmemWal).Length / 1MB, 1)
    if ($walMb -gt 100) {
        Write-Log ("记忆库 WAL {0} MB，做一次检查点" -f $walMb)
        & $venv -X utf8 "D:\你的数据目录\tools\memory_maintenance.py" --checkpoint | Out-Null
    }
}

foreach ($t in $targets) {
    $listening = Get-NetTCPConnection -LocalPort $t.Port -State Listen -ErrorAction SilentlyContinue
    if ($listening) { continue }
    Write-Log ("{0}({1}) 没在监听，重新拉起" -f $t.Name, $t.Port)
    $out = "D:\你的数据目录\logs\{0}.out.log" -f $t.Port
    $err = "D:\你的数据目录\logs\{0}.err.log" -f $t.Port
    Start-Process -FilePath $venv `
        -ArgumentList @("-X", "utf8", $t.Script) `
        -WindowStyle Hidden `
        -WorkingDirectory (Split-Path -Parent $t.Script) `
        -RedirectStandardOutput $out `
        -RedirectStandardError $err | Out-Null
    Start-Sleep -Seconds 6
    $ok = Get-NetTCPConnection -LocalPort $t.Port -State Listen -ErrorAction SilentlyContinue
    Write-Log ("{0}({1}) {2}" -f $t.Name, $t.Port, $(if ($ok) { "已恢复" } else { "拉起失败，看 $err" }))
}