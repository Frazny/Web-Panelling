@echo off
setlocal
cd /d "%~dp0"

rem ================================================================
rem  Botu baslatir.
rem    baslat.bat            : arka planda (gizli) baslatir
rem    baslat.bat gorunur    : acik pencerede baslatir (hata gormek icin)
rem  Bosaltilmis loglar: bot_out.log / bot_err.log
rem ================================================================

set "MODE=hidden"
if /i "%~1"=="gorunur"  set "MODE=visible"
if /i "%~1"=="visible"  set "MODE=visible"
if /i "%~1"=="debug"    set "MODE=visible"

rem --- Zaten calisiyor mu? ---
powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'main.py' }) { exit 1 }"
if %errorlevel% equ 1 (
    echo [Bot] Zaten calisiyor. Yeniden baslatmak icin restart.bat kullanin.
    pause
    exit /b
)

rem --- Python'i bul (bilinen yollar) ---
set "PY="
if exist "%LOCALAPPDATA%\Programs\Python\Python314\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python310\python.exe"

rem --- PATH'teki gercek python (WindowsApps stub'ini atla) ---
if not defined PY (
    for /f "delims=" %%i in ('where python 2^>nul') do (
        echo %%i | findstr /i /c:"WindowsApps" >nul
        if errorlevel 1 if not defined PY set "PY=%%i"
    )
)

rem --- py launcher ---
if not defined PY (
    for /f "delims=" %%i in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do set "PY=%%i"
)

if not defined PY (
    echo.
    echo [HATA] Python bulunamadi!
    echo Bot icin Python 3.10+ gerekli. Kurmak icin sunu calistir:
    echo   winget install Python.Python.3.12
    echo.
    pause
    exit /b 1
)

echo [Bot] Python: %PY%

if "%MODE%"=="visible" (
    echo [Bot] Gorunur modda baslatiliyor... Kapatmak icin Ctrl+C.
    "%PY%" main.py
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%PY%' -ArgumentList 'main.py' -WorkingDirectory '%~dp0' -WindowStyle Hidden -RedirectStandardOutput '%~dp0bot_out.log' -RedirectStandardError '%~dp0bot_err.log'"
    if %errorlevel% equ 0 (
        echo [Bot] Baslatildi. Loglar: bot_out.log / bot_err.log
        echo [Bot] Komutlarin gecmesi ~10 saniye surer; bot_out.log kontrol et.
    ) else (
        echo [HATA] Bot baslatilamadi. Loglar: bot_out.log / bot_err.log
    )
)
pause
endlocal