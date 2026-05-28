@echo off
setlocal EnableExtensions
set "ROOT=%~dp0"

echo [dev-all] Starting backend and frontend in separate windows...
echo.

start "viewer-TD backend" cmd /k ""%ROOT%dev-back.bat""
timeout /t 2 /nobreak >nul
start "viewer-TD frontend" cmd /k ""%ROOT%dev-front.bat""

echo.
echo Backend:  http://127.0.0.1:7000/docs
echo Frontend: http://localhost:6100
echo.
echo Close each window to stop that service, or run dev-stop.bat
timeout /t 4 /nobreak >nul
endlocal
