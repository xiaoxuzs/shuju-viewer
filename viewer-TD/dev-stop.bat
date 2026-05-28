@echo off
setlocal EnableExtensions
echo [dev-stop] Stopping viewer-TD dev servers on ports 7000 and 6100...

set "KILLED=0"
for %%P in (7000 6100) do (
  for /f "tokens=5" %%A in ('netstat -aon ^| findstr /R /C:":%%P .*LISTENING"') do (
    echo   Stopping PID %%A (port %%P)
    taskkill /F /PID %%A >nul 2>&1
    if not errorlevel 1 set /a KILLED+=1
  )
)

if "%KILLED%"=="0" (
  echo [dev-stop] No listening process found on 7000 or 6100.
) else (
  echo [dev-stop] Done.
)
timeout /t 2 /nobreak >nul
endlocal
