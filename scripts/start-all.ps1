# ============================================================
#  Companion launcher - TEMPLATE
#  Starts every service and opens the console page.
#  Edit the values below before first use.
# ============================================================

$Root        = "D:\your-install-dir"   # <-- CHANGE: your install directory
$Token       = ""                      # <-- CHANGE: shared gate token (same for all services)
$ConsolePort = 8009                    # console (aggregation page) port

# service -> relative path + port (keep in sync with services/console/data/services.json)
$services = @(
    @{ Name = "webchat"; Dir = "services\webchat"; Port = 8001 },
    @{ Name = "life";    Dir = "services\life";    Port = 8005 },
    @{ Name = "brain";   Dir = "services\brain";   Port = 8006 },
    @{ Name = "house";   Dir = "services\house";   Port = 8007 },
    @{ Name = "gallery"; Dir = "services\gallery"; Port = 8002 }
)

Write-Host "== Companion startup =="
Write-Host "Root: $Root"

# 口令为空时自动生成一个，让所有服务与控制台用同一个口令（否则互相探活会全部 403）
if (-not $Token) {
    $Token = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 16 | ForEach-Object { [char]$_ })
    Write-Host ("no token set - generated one for this run: " + $Token)
}

# 1) Ollama (local models: vision + embedding)
Write-Host "[1/3] starting Ollama ..."
Start-Process "ollama" -ArgumentList "serve" -WindowStyle Hidden
Start-Sleep -Seconds 3

# 2) Services
Write-Host "[2/3] starting services ..."
foreach ($s in $services) {
    $script = Join-Path $Root ($s.Dir + "\server.py")
    if (Test-Path $script) {
        $argsList = @("`"$script`"", "--port", [string]$s.Port)
        if ($Token) { $argsList += @("--token", $Token) }
        Write-Host ("  {0} -> port {1}" -f $s.Name, $s.Port)
        Start-Process python -ArgumentList $argsList -WindowStyle Hidden
    } else {
        Write-Host ("  skip {0}: {1} not found" -f $s.Name, $script)
    }
}

# 3) Console + open page
$console = Join-Path $Root "services\console\server.py"
if (Test-Path $console) {
    $argsList = @("`"$console`"", "--port", [string]$ConsolePort)
    if ($Token) { $argsList += @("--token", $Token) }
    Start-Process python -ArgumentList $argsList -WindowStyle Hidden
}
$gate = ""
if ($Token) { $gate = "?t=$Token" }
Start-Sleep -Seconds 2
Write-Host "[3/3] opening console ..."
Start-Process "http://127.0.0.1:$ConsolePort/$gate"

Write-Host "Done. Fresh setup? Read docs/checklist-login.md first."
