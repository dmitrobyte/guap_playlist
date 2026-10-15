"""Сетевой клиент: все обращения к серверу собраны здесь.
Интерфейс никогда не ходит в базу напрямую — только через эти методы."""
from pathlib import Path

import httpx


class ApiError(Exception):
    def __init__(self, message: str, status: int | None = None, code: str | None = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


class ApiClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8000"):
        self.token: str | None = None
        self._http: httpx.Client | None = None
        self.set_base_url(base_url)

    def set_base_url(self, base_url: str) -> None:
        base_url = base_url.strip().rstrip("/")
        if not base_url.startswith(("http://", "https://")):
            base_url = "http://" + base_url
        self.base_url = base_url
        if self._http:
            self._http.close()
        # The app normally talks directly to a server on this PC or local network.
        # Do not let a system HTTP_PROXY redirect that traffic and return an unrelated 503.
        self._http = httpx.Client(
            base_url=base_url,
            timeout=httpx.Timeout(15.0, read=120.0),
            trust_env=False,
        )

    # ------------------------------------------------------------ общий запрос
    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    @staticmethod
    def _raise_for(r: httpx.Response) -> None:
        if r.status_code < 400:
            return
        try:
            err = r.json()["error"]
            raise ApiError(err["message"], r.status_code, err.get("code"))
        except (ValueError, KeyError, TypeError):
            raise ApiError(f"Ошибка сервера (код {r.status_code})", r.status_code)

    def _request(self, method: str, path: str, **kw):
        try:
            r = self._http.request(method, path, headers=self._headers(), **kw)
        except httpx.ConnectError:
            raise ApiError("Не удалось подключиться к серверу. Проверьте адрес и что сервер запущен.")
        except httpx.TimeoutException:
            raise ApiError("Сервер не ответил вовремя. Попробуйте ещё раз.")
        except httpx.HTTPError as e:
            raise ApiError(f"Ошибка сети: {e}")
        self._raise_for(r)
        return r.json()

    # ------------------------------------------------------------ авторизация
    def register(self, login: str, display_name: str, password: str) -> dict:
        data = self._request("POST", "/auth/register",
                             json={"login": login, "display_name": display_name, "password": password})
        self.token = data["token"]
        return data

    def login(self, login: str, password: str) -> dict:
        data = self._request("POST", "/auth/login", json={"login": login, "password": password})
        self.token = data["token"]
        return data

    def me(self) -> dict:
        return self._request("GET", "/auth/me")["user"]

    def logout(self) -> None:
        try:
            self._request("POST", "/auth/logout")
        finally:
            self.token = None

    # ------------------------------------------------------------ сообщества
    def communities(self) -> list[dict]:
        return self._request("GET", "/communities")["communities"]

    def create_community(self, name: str) -> dict:
        return self._request("POST", "/communities", json={"name": name})["community"]

    def join_community(self, code: str) -> dict:
        return self._request("POST", "/communities/join", json={"invite_code": code})

    def members(self, cid: int) -> list[dict]:
        return self._request("GET", f"/communities/{cid}/members")["members"]

    def set_role(self, cid: int, user_id: int, role: str) -> dict:
        return self._request("POST", f"/communities/{cid}/members/{user_id}/role", json={"role": role})

    def regenerate_invite(self, cid: int) -> str:
        return self._request("POST", f"/communities/{cid}/invite/regenerate")["invite_code"]

    # ------------------------------------------------------------ композиции
    def catalog(self) -> list[dict]:
        return self._request("GET", "/catalog")["catalog"]

    def add_catalog_track(self, cid: int, key: str) -> dict:
        return self._request("POST", f"/communities/{cid}/tracks",
                             json={"source_type": "catalog", "catalog_key": key})["track"]

    def add_link_track(self, cid: int, title: str, artist: str, url: str) -> dict:
        return self._request("POST", f"/communities/{cid}/tracks",
                             json={"source_type": "link", "title": title, "artist": artist, "url": url})["track"]

    def upload_track(self, cid: int, path: str, title: str, artist: str) -> dict:
        p = Path(path)
        mime = "audio/wav" if p.suffix.lower() == ".wav" else "audio/mpeg"
        with open(p, "rb") as f:
            return self._request("POST", f"/communities/{cid}/tracks/upload",
                                 files={"file": (p.name, f, mime)},
                                 data={"title": title, "artist": artist})["track"]

    def all_tracks(self, cid: int) -> list[dict]:
        return self._request("GET", f"/communities/{cid}/tracks",
                             params={"include_hidden": "true"})["tracks"]

    def moderate(self, track_id: int, status: str) -> dict:
        return self._request("PATCH", f"/tracks/{track_id}/moderation", json={"status": status})["track"]

    def download_track(self, track_id: int, dest_dir: str) -> str:
        """Скачивает аудиофайл (вызывать только в фоновом потоке). Возвращает путь."""
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        try:
            with self._http.stream("GET", f"/tracks/{track_id}/file", headers=self._headers()) as r:
                if r.status_code >= 400:
                    r.read()
                    self._raise_for(r)
                ext = ".wav" if "wav" in r.headers.get("content-type", "") else ".mp3"
                final = dest / f"{track_id}{ext}"
                tmp = dest / f"{track_id}{ext}.part"
                with open(tmp, "wb") as f:
                    for chunk in r.iter_bytes():
                        f.write(chunk)
                tmp.replace(final)
                return str(final)
        except httpx.ConnectError:
            raise ApiError("Не удалось подключиться к серверу для загрузки файла.")
        except httpx.TimeoutException:
            raise ApiError("Загрузка файла заняла слишком много времени.")

    # ------------------------------------------------------------ плейлист и голоса
    def playlist(self, cid: int) -> dict:
        return self._request("GET", f"/communities/{cid}/playlist")

    def vote(self, track_id: int) -> dict:
        return self._request("POST", f"/tracks/{track_id}/vote")

    def unvote(self, track_id: int) -> dict:
        return self._request("DELETE", f"/tracks/{track_id}/vote")

    # ------------------------------------------------------------ история
    def periods(self, cid: int) -> list[dict]:
        return self._request("GET", f"/communities/{cid}/periods")["periods"]

    def history(self, cid: int, period_id: int | None = None) -> dict:
        params = {"period_id": period_id} if period_id else None
        return self._request("GET", f"/communities/{cid}/history", params=params)
