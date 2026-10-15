@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
if not exist .venv (echo Сначала запустите install.bat & pause & exit /b 1)
call .venv\Scripts\activate.bat
python run_server.py %*
pause
