# TA桌面 App（Electron 壳）重建脚本
# 作用：拉 Electron 运行时、装应用代码（含 Coopanion 桌宠表现层）、建快捷方式。
# 运行时放在 D:\dev\companion-app（不进灾后复活包）。
$ErrorActionPreference = 'Stop'
$VER = '45.3.3'
$ROOT = 'D:\dev\companion-app'
$SRC = 'D:\你的数据目录\lab\companion-app'
$PETSRC = 'D:\你的数据目录\lab\pet-figure'
$ZIP = Join-Path $ROOT 'electron.zip'
$EL = Join-Path $ROOT 'electron'

New-Item -ItemType Directory -Path $ROOT -Force | Out-Null
if (-not (Test-Path (Join-Path $EL 'electron.exe'))) {
  Write-Host "下载 Electron $VER …"
  Invoke-WebRequest "https://registry.npmmirror.com/-/binary/electron/v$VER/electron-v$VER-win32-x64.zip" -OutFile $ZIP -TimeoutSec 900
  New-Item -ItemType Directory -Path $EL -Force | Out-Null
  tar -xf $ZIP -C $EL
}

# 应用代码
$APP = Join-Path $EL 'resources\app'
New-Item -ItemType Directory -Path $APP -Force | Out-Null
Copy-Item (Join-Path $SRC 'main.js'), (Join-Path $SRC 'package.json'), (Join-Path $SRC 'icon.ico'), (Join-Path $SRC 'pet-preload.js') $APP -Force

# 桌宠表现层（Coopanion figure web，见 lab\pet-figure\NOTICE-pet.md）
$PETWEB = Join-Path $ROOT 'petweb'
if (Test-Path $PETWEB) { Remove-Item $PETWEB -Recurse -Force }
New-Item -ItemType Directory -Path $PETWEB -Force | Out-Null
Copy-Item (Join-Path $PETSRC 'web') $PETWEB -Recurse -Force
Copy-Item (Join-Path $PETSRC 'pet.html'), (Join-Path $PETSRC 'pet.js'), (Join-Path $PETSRC 'NOTICE-pet.md') $PETWEB -Force

# 快捷方式
$ws = New-Object -ComObject WScript.Shell
foreach ($lnk in @("$env:USERPROFILE\Desktop\TA.lnk", "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\TA.lnk")) {
  $sc = $ws.CreateShortcut($lnk)
  $sc.TargetPath = Join-Path $EL 'electron.exe'
  $sc.WorkingDirectory = $EL
  $sc.IconLocation = (Join-Path $APP 'icon.ico') + ',0'
  $sc.Description = 'TA的家：聊天 / 视频通话 / 状态 / 画廊 / 控制台（独立 App + 桌宠）'
  $sc.Save()
}
Write-Host "完成：双击桌面「TA」。桌宠窗默认在右下（可拖动）。"
