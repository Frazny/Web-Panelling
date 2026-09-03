$botDir = $PSScriptRoot
$py = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
$flag = Join-Path $botDir "restart.flag"

$proc = Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match 'main.py' }
$running = $proc | Select-Object -First 1

if ($running) {
    $oldPid = $running.ProcessId
    Set-Content -Path $flag -Value "restart" -Encoding ASCII
    Write-Output "Eski islem (PID $oldPid) kapatiliyor..."
    Wait-Process -Id $oldPid -Timeout 30 -ErrorAction SilentlyContinue
    if (Get-Process -Id $oldPid -ErrorAction SilentlyContinue) {
        Stop-Process -Id $oldPid -Force
    }
}

Remove-Item -Path $flag -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1

if (-not (Test-Path $py)) {
    Write-Error "Python bulunamadi: $py"
    exit 1
}

Start-Process -FilePath $py -ArgumentList "main.py" -WorkingDirectory $botDir -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $botDir "bot_out.log") `
    -RedirectStandardError (Join-Path $botDir "bot_err.log")

Write-Output "Bot yeniden baslatildi."
