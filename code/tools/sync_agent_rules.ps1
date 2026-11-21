# 同步《助手守则》到各个工作目录（开机/启动时跑一次）
# 源文件：D:\你的数据目录\AGENTS.md
$src = 'D:\你的数据目录\AGENTS.md'
if (-not (Test-Path $src)) { exit 0 }
$targets = @(
    'C:\你的用户\Desktop\DeepSeek\AGENTS.md',
    'C:\你的用户\AGENTS.md',
    'C:\你的用户\Desktop\AGENTS.md'
)
foreach ($t in $targets) {
    try { Copy-Item $src $t -Force } catch { }
}
