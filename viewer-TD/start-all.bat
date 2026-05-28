@echo off
setlocal EnableExtensions
set "ROOT=%~dp0"
set "BACK=%ROOT%back"
set "FRONT=%ROOT%front"

if not exist "%BACK%\app\main.py" (
  echo [start-all] Backend not found: "%BACK%"
  exit /b 1
)
if not exist "%FRONT%\package.json" (
  echo [start-all] Frontend not found: "%FRONT%"
  exit /b 1
)

echo Starting backend in a new window...
rem Do not use cd "%%~dp0" (trailing \ before " breaks CMD). Let start-back.bat cd using its own %%~dp0.
start "proteo-viewer-backend" "%~dp0start-back.bat"

echo Starting frontend in a new window...
timeout /t 1 /nobreak >nul
start "proteo-viewer-frontend" cmd /k "cd /d ""%FRONT%"" && npm run dev"

echo.
echo Backend:  http://localhost:7000/docs
echo Frontend: http://localhost:6100
echo Close each window to stop that service.
endlocal
