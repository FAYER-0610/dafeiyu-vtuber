@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
if exist ".venv\Scripts\python.exe" goto install
if exist "D:\DL\Conda\python.exe" (
  "D:\DL\Conda\python.exe" -m venv .venv
) else (
  py -3.12 -m venv .venv
)
if errorlevel 1 exit /b 1
:install
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 exit /b 1
exit /b 0
