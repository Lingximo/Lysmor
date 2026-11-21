$targets = @(
  'D:\napcat\app\cache\qrcode.png',
  'D:\napcat\app\cache\qrcode.jpg',
  'D:\你的数据目录\webchat\qr-phone.png'
)

$removed = 0
foreach ($p in $targets) {
  if (Test-Path -LiteralPath $p) {
    Remove-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue
    if (-not (Test-Path -LiteralPath $p)) {
      Write-Host ('removed: ' + $p)
      $removed = $removed + 1
    }
  }
}

if ($removed -eq 0) {
  Write-Host 'no stale qr found'
}
Write-Host 'done'
