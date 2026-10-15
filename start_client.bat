@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
if not exist .venv (echo Сначала запустите install.bat & pause & exit /b 1)
call .venv\Scripts\activate.bat
start "" .venv\Scripts\pythonw.exe run_client.py
