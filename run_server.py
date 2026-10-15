"""Запуск API-сервера.

    python run_server.py                       — сервер для всей локальной сети, порт 8000
    python run_server.py --port 9000           — другой порт
    python run_server.py --data-dir demo_data --fake-now 2026-10-19T00:05
                                               — проверка недельной ротации на отдельной базе
"""
import argparse
import os
import socket


def local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def main():
    p = argparse.ArgumentParser(description="Сервер «Совместный плейлист»")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--data-dir", help="папка для базы и загруженных файлов")
    p.add_argument("--fake-now", help="подменить текущее время (ISO), для теста ротации")
    p.add_argument("--debug", action="store_true", help="включить /debug/time")
    args = p.parse_args()

    # Настройки передаём через окружение ДО импорта сервера
    if args.data_dir:
        os.environ["PLAYLIST_DATA_DIR"] = os.path.abspath(args.data_dir)
    if args.fake_now:
        os.environ["PLAYLIST_FAKE_NOW"] = args.fake_now
    if args.debug:
        os.environ["PLAYLIST_DEBUG"] = "1"

    import uvicorn

    print("=" * 60)
    print(" Сервер «Совместный плейлист»")
    print(f" На этом компьютере:   http://127.0.0.1:{args.port}")
    print(f" Для других в сети:    http://{local_ip()}:{args.port}")
    print(f" Документация API:     http://127.0.0.1:{args.port}/docs")
    print(" Остановить: Ctrl+C")
    print("=" * 60)
    uvicorn.run("server.main:app", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
