# 用 aapt2 + d8 + apksigner 直接打 APK，不依赖 Gradle
# 用法： powershell -File build.ps1
$ErrorActionPreference = "Stop"

$ROOT   = "D:\你的数据目录\lab\relay\android"
$TOOLS  = "D:\你的数据目录\tools\android"
$JDK    = (Get-ChildItem $TOOLS -Directory | Where-Object { $_.Name -like "jdk-17*" } | Select-Object -First 1).FullName
$SDK    = Join-Path $TOOLS "sdk"
$BT     = Join-Path $SDK "build-tools\34.0.0"
$PLAT   = Join-Path $SDK "platforms\android-34\android.jar"
$AAPT2  = Join-Path $BT "aapt2.exe"
$D8     = Join-Path $BT "d8.bat"
$ZIPAL  = Join-Path $BT "zipalign.exe"
$SIGN   = Join-Path $BT "apksigner.bat"

$env:JAVA_HOME = $JDK
$env:PATH = "$JDK\bin;$env:PATH"

foreach ($p in @($AAPT2, $D8, $PLAT)) {
    if (-not (Test-Path $p)) { throw "缺少工具：$p" }
}

$OUT    = Join-Path $ROOT "build"
$GEN    = Join-Path $OUT "gen"
$OBJ    = Join-Path $OUT "obj"
$DEX    = Join-Path $OUT "dex"
Remove-Item $OUT -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $GEN,$OBJ,$DEX -Force | Out-Null

Write-Host "[1/6] 编译资源 (aapt2 compile)"
& $AAPT2 compile --dir (Join-Path $ROOT "res") -o (Join-Path $OUT "res.zip")
if ($LASTEXITCODE -ne 0) { throw "aapt2 compile 失败" }

Write-Host "[2/6] 链接资源 + 生成 R.java"
& $AAPT2 link -o (Join-Path $OUT "base.apk") -I $PLAT `
    --manifest (Join-Path $ROOT "AndroidManifest.xml") `
    -A (Join-Path $ROOT "assets") `
    --java $GEN (Join-Path $OUT "res.zip")
if ($LASTEXITCODE -ne 0) { throw "aapt2 link 失败" }

Write-Host "[3/6] 编译 Java"
$SRC = @(Get-ChildItem (Join-Path $ROOT "src") -Recurse -Filter *.java | ForEach-Object { $_.FullName })
$SRC += @(Get-ChildItem $GEN -Recurse -Filter *.java | ForEach-Object { $_.FullName })
& "$JDK\bin\javac.exe" -encoding UTF-8 -source 8 -target 8 -nowarn `
    -classpath $PLAT -d $OBJ $SRC
if ($LASTEXITCODE -ne 0) { throw "javac 失败" }

Write-Host "[4/6] 转成 dex (d8)"
$CLASSES = @(Get-ChildItem $OBJ -Recurse -Filter *.class | ForEach-Object { $_.FullName })
& $D8 --lib $PLAT --min-api 26 --output $DEX $CLASSES
if ($LASTEXITCODE -ne 0) { throw "d8 失败" }

Write-Host "[5/6] 打包 + 对齐"
Copy-Item (Join-Path $OUT "base.apk") (Join-Path $OUT "unsigned.apk") -Force
# 把 classes.dex 加进 APK
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::Open((Join-Path $OUT "unsigned.apk"), "Update")
$dexFile = Join-Path $DEX "classes.dex"
[System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $dexFile, "classes.dex") | Out-Null
$zip.Dispose()

& $ZIPAL -f 4 (Join-Path $OUT "unsigned.apk") (Join-Path $OUT "aligned.apk")
if ($LASTEXITCODE -ne 0) { throw "zipalign 失败" }

Write-Host "[6/6] 签名"
$KS = Join-Path $OUT "debug.keystore"
# 注意：原生命令写 stderr 时 PS5.1 会抛 NativeCommandError，用 cmd /c 包一层
$null = cmd /c "`"$JDK\bin\keytool.exe`" -genkeypair -keystore `"$KS`" -storepass android -keypass android -alias androiddebugkey -keyalg RSA -keysize 2048 -validity 10000 -dname `"CN=Android Debug,O=Android,C=US`" 2>nul"
$signOut = cmd /c "`"$SIGN`" sign --ks `"$KS`" --ks-pass pass:android --key-pass pass:android --out `"$(Join-Path $ROOT 'companion-relay.apk')`" `"$(Join-Path $OUT 'aligned.apk')`" 2>&1"
if (-not (Test-Path (Join-Path $ROOT "companion-relay.apk"))) { Write-Host $signOut; throw "apksigner 失败" }

$apk = Join-Path $ROOT "companion-relay.apk"
Write-Host ""
Write-Host "完成：$apk  $([math]::Round((Get-Item $apk).Length/1KB,1)) KB"
& $SIGN verify --print-certs $apk | Select-Object -First 2
