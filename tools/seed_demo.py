"""Заполняет запущенный сервер демонстрационными данными.

    python tools/seed_demo.py                         — сервер на этом компьютере
    python tools/seed_demo.py http://192.168.1.10:8000

Создаёт пользователей anna / boris / vera (пароль demo123), сообщество
«Группа ИВТ-21», добавляет композиции и несколько голосов.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from client.api import ApiClient, ApiError  # noqa: E402

PASSWORD = "demo123"


def account(url: str, login: str, name: str) -> ApiClient:
    api = ApiClient(url)
    try:
        api.register(login, name, PASSWORD)
    except ApiError as e:
        if e.code != "login_taken":
            raise
        api.login(login, PASSWORD)
    return api


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    anna = account(url, "anna", "Анна")
    boris = account(url, "boris", "Борис")
    vera = account(url, "vera", "Вера")

    existing = [c for c in anna.communities() if c["name"] == "Группа ИВТ-21"]
    com = existing[0] if existing else anna.create_community("Группа ИВТ-21")
    boris.join_community(com["invite_code"])
    vera.join_community(com["invite_code"])

    for key in ["demo-01", "demo-02", "demo-03", "demo-04"]:
        try:
            anna.add_catalog_track(com["id"], key)
        except ApiError:
            pass  # уже добавлена
    try:
        boris.add_link_track(com["id"], "Пример внешней ссылки", "Любой исполнитель",
                             "https://music.yandex.ru/")
    except ApiError:
        pass

    tracks = anna.playlist(com["id"])["tracks"]
    by_title = {t["title"]: t["id"] for t in tracks}
    for api, titles in [(anna, ["Перемена"]), (boris, ["Перемена", "Ночной коворкинг"]),
                        (vera, ["Ночной коворкинг", "Перемена"])]:
        for title in titles:
            if title in by_title:
                api.vote(by_title[title])

    print(f"Готово! Сообщество «{com['name']}», код приглашения: {com['invite_code']}")
    print(f"Аккаунты: anna, boris, vera — пароль {PASSWORD}")


if __name__ == "__main__":
    main()
