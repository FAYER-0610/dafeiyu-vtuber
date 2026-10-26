@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONUTF8=1
call "%~dp0bootstrap.bat"
if errorlevel 1 (
  echo Dependency setup failed. Check Python 3.12 and network.
  exit /b 1
)
if "%~1"=="--install-only" exit /b 0
".venv\Scripts\python.exe" -m host.app %*
if errorlevel 1 (
  echo Host stopped. Check .env and config.yaml.
  pause
  exit /b 1
)
