@echo off
setlocal EnableExtensions
pushd "%~dp0." >nul 2>&1
set "REPO_ROOT=%CD%"
cd /d "%CD%\front"
if not exist "package.json" (
  echo [start-front] Run this from the viewer repo; expected package.json here.
  exit /b 1
)

rem Logs go under <repo>\logs\front-YYYYMMDD-HHMMSS.log; console keeps live output.
if not exist "%REPO_ROOT%\logs" mkdir "%REPO_ROOT%\logs"
for /f "tokens=2 delims==" %%I in ('wmic os get LocalDateTime /value 2^>nul') do set "LDT=%%I"
if "%LDT%"=="" set "LDT=%date:~0,4%%date:~5,2%%date:~8,2%-%time:~0,2%%time:~3,2%%time:~6,2%"
set "STAMP=%LDT:~0,8%-%LDT:~8,6%"
set "STAMP=%STAMP: =0%"
set "LOG_FILE=%REPO_ROOT%\logs\front-%STAMP%.log"
echo [start-front] writing logs to %LOG_FILE%

where pnpm >nul 2>&1
if "%ERRORLEVEL%"=="0" (
  pnpm run dev 2>&1 | "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -Command "$input ^| Tee-Object -FilePath '%LOG_FILE%'"
) else (
  npm run dev 2>&1 | "%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -Command "$input ^| Tee-Object -FilePath '%LOG_FILE%'"
)
endlocal
