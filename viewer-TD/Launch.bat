@echo off
setlocal EnableExtensions
set "ROOT=%~dp0"
set "BACK=%ROOT%back"
set "URL=http://127.0.0.1:7000/"

if not exist "%BACK%\app\main.py" (
  echo [Launch] Backend not found under %BACK%
  pause
  exit /b 1
)

if not exist "%ROOT%front\dist\index.html" (
  echo [Launch] Frontend not built yet. Running prepare-launch.bat ...
  call "%ROOT%prepare-launch.bat"
  if errorlevel 1 (
    echo [Launch] Prepare failed.
    pause
    exit /b 1
  )
)

if not exist "%BACK%\.venv\Scripts\python.exe" (
  echo [Launch] Backend venv missing. Running prepare-launch.bat ...
  call "%ROOT%prepare-launch.bat"
  if errorlevel 1 (
    echo [Launch] Prepare failed.
    pause
    exit /b 1
  )
)

rem Already running?
powershell -NoLogo -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:7000/health' -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }"
if not errorlevel 1 (
  echo [Launch] Server already running. Opening browser...
  start "" "%URL%"
  exit /b 0
)

if not exist "%ROOT%logs" mkdir "%ROOT%logs"
for /f "tokens=2 delims==" %%I in ('wmic os get LocalDateTime /value 2^>nul') do set "LDT=%%I"
if "%LDT%"=="" set "LDT=%date:~0,4%%date:~5,2%%date:~8,2%-%time:~0,2%%time:~3,2%%time:~6,2%"
set "STAMP=%LDT:~0,8%-%LDT:~8,6%"
set "STAMP=%STAMP: =0%"
set "LOG_FILE=%ROOT%logs\back-%STAMP%.log"

echo [Launch] Starting proteo-viewer on port 7000 ...
start "proteo-viewer" /MIN cmd /c "cd /d ""%BACK%"" && set VIRTUAL_ENV= && set VIRTUAL_ENV_PROMPT= && "".venv\Scripts\python.exe"" -m uvicorn app.main:app --host 127.0.0.1 --port 7000 2>&1 | powershell -NoLogo -NoProfile -Command ""$input | Tee-Object -FilePath '%LOG_FILE%'"""

echo [Launch] Waiting for server...
set /a TRIES=0
:wait_loop
set /a TRIES+=1
if %TRIES% GTR 60 (
  echo [Launch] Timed out. Check %LOG_FILE%
  pause
  exit /b 1
)
timeout /t 1 /nobreak >nul
powershell -NoLogo -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:7000/health' -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }"
if errorlevel 1 goto wait_loop

echo [Launch] Opening %URL%
start "" "%URL%"
echo [Launch] Done. Close the minimized "proteo-viewer" window to stop the server.
timeout /t 3 /nobreak >nul
endlocal
