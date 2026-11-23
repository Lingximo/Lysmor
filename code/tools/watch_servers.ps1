# 小看门狗（每 3 分钟）：页面挂了拉起来 + 顺带跑情绪真实化的周期任务
# 用法（计划任务）：见同目录 install_watchdog.cmd
# 说明：页面列表与 restart_bot.ps1 保持一致；只拉起"端口没在听"的，不动正在跑的。
$ErrorActionPreference = "SilentlyContinue"
$log = 'D:\你的数据目录\logs\watchdog.log'
$venv = 'C:\你的用户\.astrbot_launcher\instances\<BOT_INSTANCE>\venv\Scripts\python.exe'
$venvW = $venv -replace 'python\.exe$', 'pythonw.exe'

function L($m) {
    $line = '[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $m
    Add-Content -Path $log -Value $line -Encoding UTF8 -ErrorAction SilentlyContinue
}
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

function Port-Owner([int]$port) {
    $c = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($c) { return [int]$c.OwningProcess }
    return 0
}

$targets = @(
    @{ Name = '浏览器端'; Port = 8001; Script = 'D:\你的数据目录\webchat\server.py' },
    @{ Name = '视频场景'; Port = 8003; Script = 'D:\你的数据目录\video\server.py' },
    @{ Name = '生命面板'; Port = 8005; Script = 'D:\你的数据目录\lifeviz\server.py' },
    @{ Name = '记忆星图'; Port = 8006; Script = 'D:\你的数据目录\brainviz\server.py' },
    @{ Name = '大平层'; Port = 8007; Script = 'D:\你的数据目录\houseviz\server.py' },
    @{ Name = 'QQ 手环'; Port = 8008; Script = 'D:\你的数据目录\qqwatch\watch.py' },
    @{ Name = '导航中心'; Port = 8009; Script = 'D:\你的数据目录\hub\server.py' }
)

foreach ($t in $targets) {
    $pidNow = Port-Owner $t.Port
    if ($pidNow) { continue }
    L ('{0}({1}) 没在跑，拉起' -f $t.Name, $t.Port)
    Start-Process -FilePath $venvW -ArgumentList @('-X', 'utf8', $t.Script) -WindowStyle Hidden `
        -WorkingDirectory (Split-Path -Parent $t.Script) `
        -RedirectStandardOutput ('D:\你的数据目录\logs\' + $t.Port + '.out.log') `
        -RedirectStandardError ('D:\你的数据目录\logs\' + $t.Port + '.err.log') | Out-Null
    Start-Sleep -Seconds 6
    $ok = Get-NetTCPConnection -LocalPort $t.Port -State Listen -ErrorAction SilentlyContinue
    L ('{0}({1}) {2}' -f $t.Name, $t.Port, $(if ($ok) { '已恢复' } else { '拉起失败，看日志' }))
}

# 情绪真实化周期任务（Phase B/E）：构造情绪 + 预期差（每 3 分钟刷一次）
# 只写 state/ 下的 json；插件读不到就回退原标签，不会让谁崩。
try {
    Start-Process -FilePath $venvW -ArgumentList @('-X', 'utf8', 'D:\你的数据目录\tools\emotion_construct.py') -WindowStyle Hidden -ErrorAction SilentlyContinue | Out-Null
    Start-Process -FilePath $venvW -ArgumentList @('-X', 'utf8', 'D:\你的数据目录\tools\expect_gap.py') -WindowStyle Hidden -ErrorAction SilentlyContinue | Out-Null
} catch {
}
