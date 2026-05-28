@echo off
setlocal EnableExtensions
set "ROOT=%~dp0"
set "BACK=%ROOT%back"
set "FRONT=%ROOT%front"

echo [prepare] Checking backend dependencies...
cd /d "%BACK%"
if not exist ".venv\Scripts\python.exe" (
  uv sync
  if errorlevel 1 exit /b 1
)

echo [prepare] Building frontend...
cd /d "%FRONT%"
where pnpm >nul 2>&1
if errorlevel 1 (
  echo [prepare] pnpm not found. Install Node.js + pnpm, then run this script again.
  exit /b 1
)
if not exist "node_modules\" (
  pnpm install
  if errorlevel 1 exit /b 1
)
pnpm build
if errorlevel 1 exit /b 1

if not exist "dist\index.html" (
  echo [prepare] Build failed: dist\index.html missing.
  exit /b 1
)

echo [prepare] Ready. You can double-click Launch.bat to start.
endlocal
