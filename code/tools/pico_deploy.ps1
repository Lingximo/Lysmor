# 等头显上线 -> 装 alpha 版 -> 授权 -> 启动 -> 拉 DebugCapture 截图
$ErrorActionPreference = "SilentlyContinue"
$adb = "D:\dev\android-sdk\platform-tools\adb.exe"
$log = "D:\你的数据目录\logs\pico_deploy.log"
function Log($m) { Add-Content $log ("{0} {1}" -f (Get-Date -Format "HH:mm:ss"), $m) -Encoding UTF8 }

Log "等待设备"
$deadline = (Get-Date).AddMinutes(40)
while ((Get-Date) -lt $deadline) {
    $dev = (& $adb devices) -join "`n"
    if ($dev -match "device$" -or $dev -match "device\s") {
        if ($dev -match "PA921HMGKC170143G\s+device") { break }
    }
    Start-Sleep -Seconds 5
}
$dev = (& $adb devices) -join "`n"
if ($dev -notmatch "PA921HMGKC170143G\s+device") { Log "40 分钟内没等到设备"; exit 1 }

Log "设备上线，安装"
& $adb install -r "D:\dev\companion-window.apk" 2>&1 | ForEach-Object { Log $_ }
& $adb shell pm grant com.companion.window android.permission.CAMERA
& $adb shell pm grant com.companion.window android.permission.RECORD_AUDIO
& $adb shell svc power stayon true
& $adb logcat -c
& $adb shell am force-stop com.companion.window
& $adb shell am start -n com.companion.window/com.unity3d.player.UnityPlayerActivity 2>&1 | ForEach-Object { Log $_ }
Start-Sleep -Seconds 15
& $adb exec-out screencap -p > "D:\你的数据目录\logs\pico_now.png"
& $adb pull /sdcard/Android/data/com.companion.window/files/debug_view.png "D:\你的数据目录\logs\pico_debug.png" 2>&1 | ForEach-Object { Log $_ }
& $adb logcat -d -v time 2>&1 | Select-String -Pattern "Unity|AlphaClient|alpha:|DebugCapture|CameraProbe|Exception" | Select-Object -Last 40 | ForEach-Object { Log $_ }
Log "部署完成"
