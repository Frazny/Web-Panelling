$botDir = $PSScriptRoot
$flag = Join-Path $botDir "stop.flag"

$proc = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'main.py' }
$running = $proc | Select-Object -First 1

if (-not $running) {
    Write-Output "Bot zaten calismiyor."
    Remove-Item -Path $flag -Force -ErrorAction SilentlyContinue
    exit 0
}

$oldPid = $running.ProcessId
Set-Content -Path $flag -Value "stop" -Encoding ASCII
Write-Output "Durdurma istegi gonderildi (PID $oldPid), kapanmasi bekleniyor..."
Wait-Process -Id $oldPid -Timeout 30 -ErrorAction SilentlyContinue
if (Get-Process -Id $oldPid -ErrorAction SilentlyContinue) {
    Stop-Process -Id $oldPid -Force
    Write-Output "Zorla kapatildi (PID $oldPid)."
} else {
    Write-Output "Bot temiz sekilde kapatildi."
}
Remove-Item -Path $flag -Force -ErrorAction SilentlyContinue
