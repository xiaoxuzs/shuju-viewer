@echo off
setlocal
cd /d "%~dp0"
set "PYTHONHOME="
set "PYTHONPATH="
set "PYTHONNOUSERSITE=1"
"%~dp0runtime\python\python.exe" -B "%~dp0delivery.py" check
pause
endlocal
