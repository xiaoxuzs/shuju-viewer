@echo off
setlocal EnableExtensions
rem This file lives in repo root (e.g. E:\viewer\). Join "back" without a broken "path\" quote.
pushd "%~dp0." >nul 2>&1
set "REPO_ROOT=%CD%"
set "BACK_DIR=%REPO_ROOT%\back"
cd /d "%BACK_DIR%"
if not exist "app\main.py" (
  echo [start-back] Run this from the viewer repo; expected app\main.py here.
  exit /b 1
)
rem Use this folder's .venv only (ignore a globally activated other-project venv)
if not exist ".venv\Scripts\python.exe" (
  echo [start-back] No .venv here. From this folder run:  uv sync
  exit /b 1
)
set "VIRTUAL_ENV=%BACK_DIR%\.venv"
set "VIRTUAL_ENV_PROMPT=proteo-viewer-backend"
set "PATH=%VIRTUAL_ENV%\Scripts;%PATH%"
echo [start-back] using Python: %VIRTUAL_ENV%\Scripts\python.exe
rem Logs go under <repo>\logs\back-YYYYMMDD-HHMMSS.log so each restart keeps a
rem separate file (no concurrent writes, no rotation needed). Console still
rem mirrors output for live tailing.
if not exist "%REPO_ROOT%\logs" mkdir "%REPO_ROOT%\logs"
for /f "tokens=2 delims==" %%I in ('wmic os get LocalDateTime /value 2^>nul') do set "LDT=%%I"
if "%LDT%"=="" set "LDT=%date:~0,4%%date:~5,2%%date:~8,2%-%time:~0,2%%time:~3,2%%time:~6,2%"
set "STAMP=%LDT:~0,8%-%LDT:~8,6%"
set "STAMP=%STAMP: =0%"
set "LOG_FILE=%REPO_ROOT%\logs\back-%STAMP%.log"

echo [start-back] writing logs to %LOG_FILE%
python -m uvicorn app.main:app --reload --port 8000 2>&1 | "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -Command "$input | Tee-Object -FilePath '%LOG_FILE%'"
endlocal
