@echo off
REM NAVIER - avvio. Backend in una finestra dedicata, poi apre l'app nel browser.
REM stop.bat ferma solo il backend, non tocca il browser.
setlocal EnableDelayedExpansion
title NAVIER launcher
cd /d "%~dp0"
set "ROOT=%CD%"

echo ===========================================
echo   NAVIER - avvio
echo ===========================================

REM --- porta dal .env (default 5700) ---
set "PORT=5700"
if exist ".env" (
  for /f "usebackq eol=# tokens=1,2 delims==" %%a in (".env") do (
    if /i "%%a"=="PORT" set "PORT=%%b"
  )
)
set "PORT=%PORT: =%"
echo [i] Porta backend: %PORT%

REM --- virtualenv ---
if not exist "backend\.venv\Scripts\python.exe" (
  echo.
  echo [X] Manca il virtualenv: backend\.venv
  echo     Si crea con:
  echo         cd backend
  echo         python -m venv .venv
  echo         .venv\Scripts\activate
  echo         pip install -e ".[processing,copilot,voice]"
  echo.
  pause
  exit /b 1
)

REM --- gia' in ascolto: apre solo il browser ---
powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >nul 2>&1
if %errorlevel%==0 (
  echo [i] Backend gia' in esecuzione sulla porta %PORT%.
  goto :browser
)

REM --- build del frontend, solo la prima volta ---
if not exist "backend\app\static_dist\index.html" (
  echo [i] Frontend non buildato: eseguo "npm run build"...
  pushd frontend
  call npm run build
  popd
  if not exist "backend\app\static_dist\index.html" (
    echo [X] Build del frontend fallita. Verificare Node/npm.
    pause
    exit /b 1
  )
)

REM --- avvio backend. UVICORN_RELOAD=0: un solo processo, altrimenti il
REM     reloader respawna il figlio e stop.bat non lo ferma davvero.
echo [i] Avvio il backend...
set "UVICORN_RELOAD=0"
start "NAVIER backend" /D "%ROOT%\backend" cmd /k ".venv\Scripts\python.exe -m app.main"

REM --- attesa risposta. ping invece di timeout: timeout fallisce con stdin rediretto.
echo [i] Attendo il backend...
set /a tries=0
:wait
curl -f -s -o nul --max-time 2 "http://127.0.0.1:%PORT%/api/health" && goto :browser
set /a tries+=1
if !tries! geq 60 (
  echo.
  echo [X] Nessuna risposta dopo 60s. Controllare la finestra "NAVIER backend"
  echo     ^(di solito: dipendenze mancanti o porta occupata^).
  pause
  exit /b 1
)
ping -n 2 127.0.0.1 >nul
goto :wait

REM --- apertura browser ---
:browser
echo [i] Apro NAVIER nel browser...
set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%LocalAppData%\Google\Chrome\Application\chrome.exe"
if exist "%CHROME%" (
  start "" "%CHROME%" "http://localhost:%PORT%/"
) else (
  echo [!] Chrome non trovato: uso il browser predefinito.
  start "" "http://localhost:%PORT%/"
)

echo.
echo [OK] NAVIER avviato:   http://localhost:%PORT%/
echo      Per fermarlo:     stop.bat
ping -n 5 127.0.0.1 >nul
exit /b 0
