# =============================================================================
# bot-panel.zip üretir — Wispbyte (Pterodactyl) paneline yüklemek için
#
# KULLANIM:
#   powershell -ExecutionPolicy Bypass -File deploy\panel_package.ps1
#
# ÇIKTI:
#   deploy\bot-panel.zip  (zip kökünde doğrudan main.py, cogs/, utils/,
#                          config.json, data/, requirements.txt — üst klasör yok)
# =============================================================================
$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$OutPath = Join-Path $PSScriptRoot "bot-panel.zip"

# Hariç tutulacak dizinler
$ExcludeDirs = @(
    ".git", ".venv", "__pycache__", ".pytest_cache",
    "deploy", "tests", "node_modules"
)

# Hariç tutulacak dosya adları
$ExcludeFiles = @(
    ".gitignore", "restart.flag",
    "_sync.py", "_cleanup_test.py", "_komut_test.py", "_smoke_test.py", "_komut_sonuc.txt",
    "bot_out.log", "bot_err.log", "bot.log", "bot.err.log",
    "baslat.bat", "durdur.bat", "durdur.ps1", "restart.bat", "restart.ps1",
    "gonder.py", "manifest_panel.py", "frame0.png",
    "pytest.ini", "requirements-dev.txt", "cookies.txt"
)

$files = Get-ChildItem -LiteralPath $ProjectRoot -Recurse -File | Where-Object {
    $rel = $_.FullName.Substring($ProjectRoot.Length).TrimStart('\', '/')
    $parts = $rel -split '[\\/]'
    $dirParts = $parts[0..($parts.Length - 2)]

    # Dizin engeli
    foreach ($d in $dirParts) {
        if ($ExcludeDirs -contains $d) { return $false }
    }
    # Dosya engeli
    $name = $parts[-1]
    if ($ExcludeFiles -contains $name) { return $false }
    if ($name -like "*.log") { return $false }
    if ($name -eq "restart.flag") { return $false }
    return $true
}

if ($files.Count -eq 0) {
    Write-Error "Paketlenecek dosya bulunamadı: $ProjectRoot"
}

if (Test-Path -LiteralPath $OutPath) {
    Remove-Item -LiteralPath $OutPath -Force
}

Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::Open($OutPath, 2)
try {
    foreach ($f in $files) {
        $rel = $f.FullName.Substring($ProjectRoot.Length).TrimStart('\', '/')
        # Linux tarafında klasörlerin doğru açılması için zip standart
        # ayracı olan "/" kullanılmalı ("\" Linux'ta klasöre çevrilmez).
        $zipRel = $rel -replace '\\', '/'
        # Farklı paneller farklı giriş dosyası bekler (main.py / app.py);
        # her ikisini de koy, hangisi çalıştırılırsa çalışsın.
        $names = @($zipRel)
        if ($zipRel -eq 'main.py') { $names = @('main.py', 'app.py') }
        foreach ($name in $names) {
            $entry = $zip.CreateEntry($name, 1)
            $es = $entry.Open()
            try {
                $fs = [System.IO.File]::OpenRead($f.FullName)
                try { $fs.CopyTo($es) } finally { $fs.Dispose() }
            } finally { $es.Dispose() }
        }
    }
} finally {
    $zip.Dispose()
}

$sizeKB = [math]::Round((Get-Item -LiteralPath $OutPath).Length / 1KB, 1)
Write-Host ""
Write-Host "================================================================"
Write-Host "  bot-panel.zip OLUŞTURULDU"
Write-Host "  Dosya : $OutPath"
Write-Host "  Boyut : $sizeKB KB  ($($files.Count) dosya)"
Write-Host "================================================================"
Write-Host ""
Write-Host "Sıradaki adımlar:"
Write-Host "  1) Wispbyte paneli -> Files -> Upload -> bot-panel.zip (KLASÖR DEĞİL)"
Write-Host "  2) Zip satırı -> ... -> Extract (ana dizine)"
Write-Host "  3) Startup: python main.py"
Write-Host "  4) Start -> 'Bot giriş yaptı' yazısı"
