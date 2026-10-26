@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONUTF8=1
call "%~dp0bootstrap.bat"
if errorlevel 1 exit /b 1
".venv\Scripts\python.exe" scripts\login_bilibili.py %*
if errorlevel 1 exit /b 1
if "%~1"=="" pause
