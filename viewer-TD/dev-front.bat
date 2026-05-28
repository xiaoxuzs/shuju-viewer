@echo off
setlocal EnableExtensions
title viewer-TD frontend (port 6100)
set "ROOT=%~dp0"
set "FRONT=%ROOT%front"

if not exist "%FRONT%\package.json" (
  echo [dev-front] Frontend not found: %FRONT%
  pause
  exit /b 1
)

cd /d "%FRONT%"

where pnpm >nul 2>&1
if errorlevel 1 (
  echo [dev-front] pnpm not found. Install Node.js + pnpm first.
  echo   npm install -g pnpm
  pause
  exit /b 1
)

if not exist "node_modules\" (
  echo [dev-front] Installing frontend deps...
  pnpm install
  if errorlevel 1 (
    pause
    exit /b 1
  )
)

echo.
echo ========================================
echo   viewer-TD frontend (dev)
echo   UI:      http://localhost:6100
echo   API proxy: /api -^> http://127.0.0.1:7000
echo ========================================
echo   Start dev-back.bat first, then use the UI here.
echo   Close this window or press Ctrl+C to stop.
echo.

pnpm dev
endlocal
