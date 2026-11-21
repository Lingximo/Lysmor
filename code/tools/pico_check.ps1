# TA Pico 浮窗 · 自检

$ErrorActionPreference = "SilentlyContinue"
$adb = "D:\dev\android-sdk\platform-tools\adb.exe"
$py = "C:\你的用户\.astrbot_launcher\instances\<BOT_INSTANCE>\venv\Scripts\python.exe"
$out = @()

$out += "== 设备 =="
$out += (& $adb devices) -join "`n"

$out += "`n== 应用 =="
$pkg = & $adb shell pm list packages | Select-String "com.companion.window"
$out += if ($pkg) { "com.companion.window 已安装" } else { "未安装" }

$out += "`n== 面板流 8014 =="
$listen = Get-NetTCPConnection -LocalPort 8014 -State Listen
if ($listen) {
    $out += "8014 在监听"
    try {
        $r = Invoke-WebRequest "http://127.0.0.1:8014/panel.jpg" -UseBasicParsing -TimeoutSec 6
        $out += ("panel.jpg {0}, {1} 字节" -f $r.StatusCode, $r.RawContentLength)
    } catch {
        $out += ("panel.jpg 取不到: " + $_.Exception.Message)
    }
} else {
    $out += "8014 没在监听"
}

$out += "`n== 前台 =="
$out += (& $adb shell dumpsys activity activities | Select-String "topResumedActivity" | Select-Object -First 1)

$out += "`n== CameraVision / 语音日志（最近 300 行）=="
$logs = & $adb logcat -d -v time -t 300
$out += ($logs | Select-String -Pattern "CameraVision|CameraProbe|voice ws|mic started|sent wav" | Select-Object -Last 30)

$text = $out -join "`n"
Write-Host $text
$path = "D:\你的数据目录\logs\pico_check_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".txt"
Set-Content -Path $path -Value $text -Encoding UTF8
Write-Host "`n已保存: $path"
