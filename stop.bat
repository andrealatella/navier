@echo off
REM NAVIER - arresto. Ferma il backend e chiude la sua finestra.
REM Il browser non viene toccato.
setlocal
title NAVIER stop
cd /d "%~dp0"

echo ===========================================
echo   NAVIER - arresto
echo ===========================================

REM --- porta dal .env (default 5700) ---
set "PORT=5700"
if exist ".env" (
  for /f "usebackq eol=# tokens=1,2 delims==" %%a in (".env") do (
    if /i "%%a"=="PORT" set "PORT=%%b"
  )
)
set "PORT=%PORT: =%"

echo [i] Fermo il backend sulla porta %PORT%...
powershell -NoProfile -Command "$p = Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique; if ($p) { $p | ForEach-Object { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue }; Write-Host '    backend fermato' } else { Write-Host '    non era in esecuzione' }"

echo [i] Chiudo la finestra del backend...
taskkill /F /FI "WINDOWTITLE eq NAVIER backend*" >nul 2>&1

echo.
echo [OK] Backend fermo.
ping -n 4 127.0.0.1 >nul
exit /b 0
