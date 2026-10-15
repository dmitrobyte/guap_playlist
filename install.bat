@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === Установка "Совместного плейлиста" ===
where python >nul 2>nul || (echo Python не найден. Установите Python 3.11+ с python.org и отметьте "Add python.exe to PATH". & pause & exit /b 1)
if not exist .venv (
    echo Создаю виртуальное окружение .venv ...
    python -m venv .venv || (pause & exit /b 1)
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt || (echo Ошибка установки библиотек & pause & exit /b 1)
echo.
echo Готово! Теперь запустите start_server.bat (на одном компьютере) и start_client.bat.
pause
