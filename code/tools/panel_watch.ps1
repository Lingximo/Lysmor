# TA Pico 面板：保证 8014 在跑，且电脑上有一个“和TA视频”的 Edge 应用窗口。
# 由计划任务 Companion-PicoPanel 每 5 分钟跑一次，开机/登录也跑。
# 2026-11-15 修复：原文件被拼接损坏（重复 4 份 + 半句残留），这里重建为单份。

$ErrorActionPreference = "SilentlyContinue"

$venv   = "C:\你的用户\.astrbot_launcher\instances\<BOT_INSTANCE>\venv\Scripts\python.exe"
$script = "D:\你的数据目录\video\panel_stream.py"
$edge   = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
$log    = "D:\你的数据目录\logs\panel_watch.log"
$url    = "http://127.0.0.1:8003/?panel=1&r=" + [int](Get-Date -UFormat %s)

function Write-Log($m) {
    Add-Content -Path $log -Value ("{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $m) -Encoding UTF8
}

# 1) 8014 面板流服务
if (-not (Get-NetTCPConnection -LocalPort 8014 -State Listen)) {
    Write-Log "8014 没在监听，启动 panel_stream"
    Start-Process -FilePath $venv -ArgumentList @("-u", "-X", "utf8", $script) -WindowStyle Hidden `
        -RedirectStandardOutput "D:\你的数据目录\logs\panel.out.log" `
        -RedirectStandardError "D:\你的数据目录\logs\panel.err.log" | Out-Null
    Start-Sleep -Seconds 3
}

# 2) Edge 面板：按命令行识别，避免标题变化导致每 5 分钟重开
$has = [bool](Get-CimInstance Win32_Process -Filter "Name='msedge.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*edge_panel_watch*" -and $_.CommandLine -like "*panel=1*" })

if (-not $has) {
    Write-Log "没有面板窗口，屏幕外拉起 Edge 面板"
    Start-Process -FilePath $edge -ArgumentList @(
        "--app=$url", "--window-size=1024,960", "--window-position=-32000,-32000",
        "--user-data-dir=D:\你的数据目录\logs\edge_panel_watch"
    ) -WindowStyle Normal | Out-Null
    Start-Sleep -Seconds 8
}

# 3) 面板是否新鲜；不新鲜时只重开 panel_watch，不动用户浏览器
$fresh = $false
try {
    $st = Invoke-RestMethod "http://127.0.0.1:8014/panel/status" -TimeoutSec 5
    if ($st.age -lt 15) {
        $fresh = $true
    } else {
        Write-Log ("面板 {0:N1}s 没更新" -f $st.age)
    }
} catch {
    Write-Log ("面板状态取不到: " + $_.Exception.Message)
}

if (-not $fresh) {
    Write-Log "面板不新鲜，重开屏幕外 Edge 面板"
    Get-CimInstance Win32_Process -Filter "Name='msedge.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*edge_panel_watch*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2
    Start-Process -FilePath $edge -ArgumentList @(
        "--app=$url", "--window-size=1024,960", "--window-position=-32000,-32000",
        "--user-data-dir=D:\你的数据目录\logs\edge_panel_watch"
    ) -WindowStyle Normal | Out-Null
    Start-Sleep -Seconds 8
}
