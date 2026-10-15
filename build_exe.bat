@echo off
chcp 65001 >nul
rem Необязательно (P1): собрать клиент в SharedPlaylist.exe через PyInstaller
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
call .venv\Scripts\activate.bat
pip install pyinstaller
pyinstaller --noconfirm --windowed --name SharedPlaylist run_client.py
echo.
echo Готово: папка dist\SharedPlaylist, внутри SharedPlaylist.exe
pause
