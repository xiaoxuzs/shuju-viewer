@echo off
setlocal EnableExtensions
title viewer-TD backend (port 7000)
set "ROOT=%~dp0"
set "BACK=%ROOT%back"

if not exist "%BACK%\app\main.py" (
  echo [dev-back] Backend not found: %BACK%
  pause
  exit /b 1
)

cd /d "%BACK%"
set "VIRTUAL_ENV="
set "VIRTUAL_ENV_PROMPT="

if not exist ".venv\Scripts\python.exe" (
  echo [dev-back] Creating venv and installing deps...
  where uv >nul 2>&1
  if errorlevel 1 (
    echo [dev-back] uv not found. Install uv, then run: cd back ^&^& uv sync
    pause
    exit /b 1
  )
  uv sync
  if errorlevel 1 (
    pause
    exit /b 1
  )
)

if not exist "%ROOT%logs" mkdir "%ROOT%logs"
for /f "tokens=2 delims==" %%I in ('wmic os get LocalDateTime /value 2^>nul') do set "LDT=%%I"
if "%LDT%"=="" set "LDT=%date:~0,4%%date:~5,2%%date:~8,2%-%time:~0,2%%time:~3,2%%time:~6,2%"
set "STAMP=%LDT:~0,8%-%LDT:~8,6%"
set "STAMP=%STAMP: =0%"
set "LOG_FILE=%ROOT%logs\back-dev-%STAMP%.log"

echo.
echo ========================================
echo   viewer-TD backend (dev)
echo   API:     http://127.0.0.1:7000
echo   Swagger: http://127.0.0.1:7000/docs
echo   Health:  http://127.0.0.1:7000/health
echo   Log:     %LOG_FILE%
echo ========================================
echo   Close this window or press Ctrl+C to stop.
echo.

".venv\Scripts\python.exe" -m uvicorn app.main:app --reload --host 127.0.0.1 --port 7000 2>&1 | "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -Command "$input | Tee-Object -FilePath '%LOG_FILE%'"
endlocal
