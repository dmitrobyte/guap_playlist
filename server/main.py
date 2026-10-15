"""API-сервер «Совместный плейлист».

Запуск: python run_server.py   (или uvicorn server.main:app --host 0.0.0.0 --port 8000)
Документация API в браузере: http://<адрес>:8000/docs
"""
import hashlib
import re
import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, File, Form, Header, Query, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from server import catalog, config, db, security
from server.errors import ApiError
from server.ranking import compute_ranking, ensure_current_period, period_dict


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_db()
    catalog.ensure_catalog()
    (config.DATA_DIR / "uploads").mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="Совместный плейлист — API", version="1.0", lifespan=lifespan)


# ---------------------------------------------------------------- ошибки

def _err(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


@app.exception_handler(ApiError)
async def _api_error(_req, exc: ApiError):
    return _err(exc.status, exc.code, exc.message)


@app.exception_handler(RequestValidationError)
async def _validation_error(_req, exc: RequestValidationError):
    fields = ", ".join(".".join(str(p) for p in e["loc"][1:]) or "запрос" for e in exc.errors())
    return _err(422, "validation_error", f"Некорректные данные запроса (поля: {fields})")


@app.exception_handler(StarletteHTTPException)
async def _http_error(_req, exc: StarletteHTTPException):
    messages = {404: "Ресурс не найден", 405: "Метод не поддерживается"}
    return _err(exc.status_code, "http_error", messages.get(exc.status_code, str(exc.detail)))


@app.exception_handler(Exception)
async def _unexpected(_req, _exc: Exception):
    return _err(500, "internal_error", "Внутренняя ошибка сервера. Попробуйте ещё раз.")


# ---------------------------------------------------------------- зависимости

def get_db():
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


def current_user(authorization: str | None = Header(None),
                 conn: sqlite3.Connection = Depends(get_db)) -> sqlite3.Row:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise ApiError(401, "unauthorized", "Требуется вход в аккаунт")
    token = authorization[7:].strip()
    row = conn.execute(
        """SELECT u.*, s.expires_at FROM sessions s JOIN users u ON u.id = s.user_id
           WHERE s.token_hash = ?""",
        (security.token_hash(token),),
    ).fetchone()
    if not row or row["expires_at"] < config.iso(config.real_now()) or not row["is_active"]:
        raise ApiError(401, "session_expired", "Сессия истекла. Войдите в аккаунт заново.")
    return row


def _community_and_role(conn, community_id: int, user_id: int) -> tuple[sqlite3.Row, str]:
    c = conn.execute(
        "SELECT * FROM communities WHERE id = ? AND is_active = 1", (community_id,)
    ).fetchone()
    if not c:
        raise ApiError(404, "community_not_found", "Сообщество не найдено")
    m = conn.execute(
        "SELECT role FROM memberships WHERE community_id = ? AND user_id = ?",
        (community_id, user_id),
    ).fetchone()
    if not m:
        raise ApiError(403, "not_member", "Вы не состоите в этом сообществе")
    return c, m["role"]


def _require_moderator(role: str) -> None:
    if role not in ("owner", "moderator"):
        raise ApiError(403, "forbidden",
                       "Недостаточно прав: действие доступно только владельцу и модераторам")


def _track_for_user(conn, track_id: int, user_id: int) -> tuple[sqlite3.Row, str]:
    t = conn.execute("SELECT * FROM tracks WHERE id = ?", (track_id,)).fetchone()
    if not t:
        raise ApiError(404, "track_not_found", "Композиция не найдена")
    _, role = _community_and_role(conn, t["community_id"], user_id)
    return t, role


def _user_dict(u) -> dict:
    return {"id": u["id"], "login": u["login"], "display_name": u["display_name"]}


def _community_dict(conn, c, role: str) -> dict:
    members = conn.execute(
        "SELECT COUNT(*) FROM memberships WHERE community_id = ?", (c["id"],)
    ).fetchone()[0]
    return {
        "id": c["id"], "name": c["name"], "invite_code": c["invite_code"],
        "owner_id": c["owner_id"], "created_at": c["created_at"],
        "my_role": role, "member_count": members,
    }


def _clean(text: str | None, field: str, max_len: int, required: bool = True) -> str:
    value = (text or "").strip()
    if required and not value:
        raise ApiError(400, "validation_error", f"Поле «{field}» не может быть пустым")
    if len(value) > max_len:
        raise ApiError(400, "validation_error", f"Поле «{field}» длиннее {max_len} символов")
    return value


# ---------------------------------------------------------------- служебное

@app.get("/health")
def health():
    return {"status": "ok", "server_time": config.iso(config.now())}


class FakeTimeIn(BaseModel):
    now: str | None = None


@app.post("/debug/time")
def debug_time(body: FakeTimeIn):
    """Только при PLAYLIST_DEBUG=1: подменить время сервера для проверки ротации."""
    if not config.DEBUG:
        raise ApiError(404, "http_error", "Ресурс не найден")
    config.set_fake_now(datetime.fromisoformat(body.now) if body.now else None)
    return {"server_time": config.iso(config.now())}


# ---------------------------------------------------------------- авторизация (FR-01)

LOGIN_RE = re.compile(r"^[A-Za-z0-9_.\-]{3,32}$")


class RegisterIn(BaseModel):
    login: str
    display_name: str
    password: str


class LoginIn(BaseModel):
    login: str
    password: str


def _issue_token(conn, user_id: int) -> str:
    token = security.new_token()
    now = config.real_now()
    conn.execute(
        "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (security.token_hash(token), user_id, config.iso(now),
         config.iso(now + timedelta(hours=config.TOKEN_TTL_HOURS))),
    )
    return token


@app.post("/auth/register", status_code=201)
def register(body: RegisterIn, conn: sqlite3.Connection = Depends(get_db)):
    login = body.login.strip()
    if not LOGIN_RE.match(login):
        raise ApiError(400, "invalid_login",
                       "Логин: 3–32 символа, латинские буквы, цифры, точка, дефис или подчёркивание")
    name = _clean(body.display_name, "Отображаемое имя", 50)
    if not 6 <= len(body.password) <= 128:
        raise ApiError(400, "weak_password", "Пароль должен содержать от 6 до 128 символов")
    pw_hash, salt = security.hash_password(body.password)
    try:
        with db.transaction(conn):
            cur = conn.execute(
                """INSERT INTO users (login, display_name, password_hash, password_salt, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (login, name, pw_hash, salt, config.iso(config.real_now())),
            )
            token = _issue_token(conn, cur.lastrowid)
    except sqlite3.IntegrityError:
        raise ApiError(409, "login_taken", "Этот логин уже занят. Выберите другой.")
    user = conn.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
    return {"token": token, "user": _user_dict(user)}


@app.post("/auth/login")
def login(body: LoginIn, conn: sqlite3.Connection = Depends(get_db)):
    user = conn.execute("SELECT * FROM users WHERE login = ?", (body.login.strip(),)).fetchone()
    if not user or not user["is_active"] or not security.verify_password(
            body.password, user["password_hash"], user["password_salt"]):
        raise ApiError(401, "invalid_credentials", "Неверный логин или пароль")
    token = _issue_token(conn, user["id"])
    return {"token": token, "user": _user_dict(user)}


@app.get("/auth/me")
def me(user=Depends(current_user)):
    return {"user": _user_dict(user)}


@app.post("/auth/logout")
def logout(authorization: str | None = Header(None), user=Depends(current_user),
           conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("DELETE FROM sessions WHERE token_hash = ?",
                 (security.token_hash(authorization[7:].strip()),))
    return {"ok": True}


# ---------------------------------------------------------------- сообщества (FR-02, FR-03)

class CommunityIn(BaseModel):
    name: str


class JoinIn(BaseModel):
    invite_code: str


def _unique_invite_code(conn) -> str:
    while True:
        code = security.new_invite_code()
        if not conn.execute("SELECT 1 FROM communities WHERE invite_code = ?", (code,)).fetchone():
            return code


@app.get("/communities")
def list_communities(user=Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    rows = conn.execute(
        """SELECT c.*, m.role FROM communities c
           JOIN memberships m ON m.community_id = c.id
           WHERE m.user_id = ? AND c.is_active = 1 ORDER BY c.name COLLATE NOCASE""",
        (user["id"],),
    ).fetchall()
    return {"communities": [_community_dict(conn, r, r["role"]) for r in rows]}


@app.post("/communities", status_code=201)
def create_community(body: CommunityIn, user=Depends(current_user),
                     conn: sqlite3.Connection = Depends(get_db)):
    name = _clean(body.name, "Название сообщества", 80)
    stamp = config.iso(config.real_now())
    with db.transaction(conn):
        cur = conn.execute(
            "INSERT INTO communities (name, invite_code, owner_id, created_at) VALUES (?, ?, ?, ?)",
            (name, _unique_invite_code(conn), user["id"], stamp),
        )
        cid = cur.lastrowid
        conn.execute(
            "INSERT INTO memberships (user_id, community_id, role, joined_at) VALUES (?, ?, 'owner', ?)",
            (user["id"], cid, stamp),
        )
    ensure_current_period(conn, cid)  # первый период голосования
    c = conn.execute("SELECT * FROM communities WHERE id = ?", (cid,)).fetchone()
    return {"community": _community_dict(conn, c, "owner")}


@app.post("/communities/join")
def join_community(body: JoinIn, user=Depends(current_user),
                   conn: sqlite3.Connection = Depends(get_db)):
    code = body.invite_code.strip().upper()
    c = conn.execute(
        "SELECT * FROM communities WHERE invite_code = ? AND is_active = 1", (code,)
    ).fetchone()
    if not c:
        raise ApiError(404, "invalid_invite", "Код приглашения не найден или больше не действует")
    cur = conn.execute(
        """INSERT OR IGNORE INTO memberships (user_id, community_id, role, joined_at)
           VALUES (?, ?, 'member', ?)""",
        (user["id"], c["id"], config.iso(config.real_now())),
    )
    already = cur.rowcount == 0
    _, role = _community_and_role(conn, c["id"], user["id"])
    return {"community": _community_dict(conn, c, role), "already_member": already}


@app.get("/communities/{community_id}")
def get_community(community_id: int, user=Depends(current_user),
                  conn: sqlite3.Connection = Depends(get_db)):
    c, role = _community_and_role(conn, community_id, user["id"])
    period = ensure_current_period(conn, community_id)
    return {"community": _community_dict(conn, c, role),
            "period": period_dict(period, period["id"])}


@app.get("/communities/{community_id}/members")
def list_members(community_id: int, user=Depends(current_user),
                 conn: sqlite3.Connection = Depends(get_db)):
    _community_and_role(conn, community_id, user["id"])
    rows = conn.execute(
        """SELECT u.id, u.login, u.display_name, m.role, m.joined_at FROM memberships m
           JOIN users u ON u.id = m.user_id WHERE m.community_id = ?
           ORDER BY CASE m.role WHEN 'owner' THEN 0 WHEN 'moderator' THEN 1 ELSE 2 END,
                    u.display_name COLLATE NOCASE""",
        (community_id,),
    ).fetchall()
    return {"members": [dict(r) for r in rows]}


class RoleIn(BaseModel):
    role: str


@app.post("/communities/{community_id}/members/{member_id}/role")
def set_role(community_id: int, member_id: int, body: RoleIn, user=Depends(current_user),
             conn: sqlite3.Connection = Depends(get_db)):
    _, role = _community_and_role(conn, community_id, user["id"])
    if role != "owner":
        raise ApiError(403, "forbidden", "Назначать модераторов может только владелец сообщества")
    if body.role not in ("moderator", "member"):
        raise ApiError(400, "validation_error", "Роль может быть только moderator или member")
    target = conn.execute(
        "SELECT role FROM memberships WHERE community_id = ? AND user_id = ?",
        (community_id, member_id),
    ).fetchone()
    if not target:
        raise ApiError(404, "member_not_found", "Участник не найден в этом сообществе")
    if target["role"] == "owner":
        raise ApiError(400, "validation_error", "Нельзя изменить роль владельца")
    conn.execute("UPDATE memberships SET role = ? WHERE community_id = ? AND user_id = ?",
                 (body.role, community_id, member_id))
    return {"ok": True, "role": body.role}


@app.post("/communities/{community_id}/invite/regenerate")
def regenerate_invite(community_id: int, user=Depends(current_user),
                      conn: sqlite3.Connection = Depends(get_db)):
    _, role = _community_and_role(conn, community_id, user["id"])
    _require_moderator(role)
    with db.transaction(conn):
        code = _unique_invite_code(conn)
        conn.execute("UPDATE communities SET invite_code = ? WHERE id = ?", (code, community_id))
    return {"invite_code": code}


# ---------------------------------------------------------------- композиции (FR-04)

@app.get("/catalog")
def get_catalog(user=Depends(current_user)):
    return {"catalog": [{k: e[k] for k in ("key", "title", "artist", "source_info")}
                        for e in catalog.load_catalog()]}


def _track_dict(t) -> dict:
    return {
        "id": t["id"], "title": t["title"], "artist": t["artist"],
        "source_type": t["source_type"], "source_url": t["source_url"],
        "playable": bool(t["storage_path"]), "status": t["status"], "added_at": t["added_at"],
    }


@app.get("/communities/{community_id}/tracks")
def list_tracks(community_id: int, include_hidden: bool = Query(False),
                user=Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    _, role = _community_and_role(conn, community_id, user["id"])
    if include_hidden:
        _require_moderator(role)
        rows = conn.execute("SELECT * FROM tracks WHERE community_id = ? ORDER BY id",
                            (community_id,)).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM tracks WHERE community_id = ? AND status = 'active' ORDER BY id",
            (community_id,)).fetchall()
    return {"tracks": [_track_dict(r) for r in rows]}


class TrackIn(BaseModel):
    source_type: str              # "catalog" или "link"
    catalog_key: str | None = None
    title: str | None = None
    artist: str | None = None
    url: str | None = None


def _check_duplicate(row) -> None:
    if row:
        if row["status"] == "hidden":
            raise ApiError(409, "duplicate_hidden",
                           "Эта композиция уже добавлялась и была скрыта модератором")
        raise ApiError(409, "duplicate", "Эта композиция уже есть в плейлисте")


def _validate_url(url: str) -> str:
    url = (url or "").strip()
    parsed = urlparse(url)
    if (parsed.scheme.lower() not in ("http", "https") or not parsed.netloc
            or any(ch.isspace() for ch in url) or len(url) > 2000):
        raise ApiError(400, "invalid_url", "Ссылка должна начинаться с http:// или https://")
    return url


@app.post("/communities/{community_id}/tracks", status_code=201)
def add_track(community_id: int, body: TrackIn, user=Depends(current_user),
              conn: sqlite3.Connection = Depends(get_db)):
    _community_and_role(conn, community_id, user["id"])
    stamp = config.iso(config.real_now())

    if body.source_type == "catalog":
        entry = catalog.find_entry(body.catalog_key or "")
        if not entry:
            raise ApiError(404, "catalog_not_found", "Композиция не найдена в библиотеке")
        with db.transaction(conn):
            _check_duplicate(conn.execute(
                "SELECT status FROM tracks WHERE community_id = ? AND catalog_key = ?",
                (community_id, entry["key"])).fetchone())
            cur = conn.execute(
                """INSERT INTO tracks (community_id, title, artist, source_type, storage_path,
                   catalog_key, added_by, added_at) VALUES (?, ?, ?, 'catalog', ?, ?, ?, ?)""",
                (community_id, entry["title"], entry["artist"], f"catalog/{entry['file']}",
                 entry["key"], user["id"], stamp),
            )
    elif body.source_type == "link":
        title = _clean(body.title, "Название", 200)
        artist = _clean(body.artist, "Исполнитель", 200)
        url = _validate_url(body.url or "")
        with db.transaction(conn):
            _check_duplicate(conn.execute(
                "SELECT status FROM tracks WHERE community_id = ? AND source_url = ?",
                (community_id, url)).fetchone())
            cur = conn.execute(
                """INSERT INTO tracks (community_id, title, artist, source_type, source_url,
                   added_by, added_at) VALUES (?, ?, ?, 'link', ?, ?, ?)""",
                (community_id, title, artist, url, user["id"], stamp),
            )
    else:
        raise ApiError(400, "validation_error",
                       "source_type должен быть catalog или link (файлы — через /tracks/upload)")
    t = conn.execute("SELECT * FROM tracks WHERE id = ?", (cur.lastrowid,)).fetchone()
    return {"track": _track_dict(t)}


def _detect_audio(head: bytes) -> str | None:
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return ".wav"
    if head[:3] == b"ID3" or (len(head) > 1 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0):
        return ".mp3"
    return None


@app.post("/communities/{community_id}/tracks/upload", status_code=201)
def upload_track(community_id: int, file: UploadFile = File(...), title: str = Form(""),
                 artist: str = Form(""), user=Depends(current_user),
                 conn: sqlite3.Connection = Depends(get_db)):
    _community_and_role(conn, community_id, user["id"])
    original = Path(file.filename or "file")
    ext = original.suffix.lower()
    if ext not in (".mp3", ".wav"):
        raise ApiError(415, "unsupported_format", "Поддерживаются только файлы MP3 и WAV")

    upload_dir = config.DATA_DIR / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    # Безопасное серверное имя: случайное, не зависит от имени, присланного клиентом
    safe_name = f"{uuid.uuid4().hex}{ext}"
    dest = upload_dir / safe_name
    hasher = hashlib.sha256()
    size = 0
    head = b""
    try:
        with open(dest, "wb") as out:
            while chunk := file.file.read(1024 * 1024):
                if not head:
                    head = chunk[:16]
                size += len(chunk)
                if size > config.MAX_UPLOAD_BYTES:
                    raise ApiError(413, "file_too_large",
                                   f"Файл больше {config.MAX_UPLOAD_BYTES // (1024 * 1024)} МБ")
                hasher.update(chunk)
                out.write(chunk)
        if size == 0:
            raise ApiError(400, "empty_file", "Файл пустой")
        if _detect_audio(head) != ext:
            raise ApiError(415, "invalid_file",
                           "Файл повреждён или не является настоящим MP3/WAV")
        file_hash = hasher.hexdigest()
        clean_title = _clean(title, "Название", 200, required=False) or original.stem[:200] or "Без названия"
        clean_artist = _clean(artist, "Исполнитель", 200, required=False) or "Неизвестный исполнитель"
        with db.transaction(conn):
            _check_duplicate(conn.execute(
                "SELECT status FROM tracks WHERE community_id = ? AND file_hash = ?",
                (community_id, file_hash)).fetchone())
            cur = conn.execute(
                """INSERT INTO tracks (community_id, title, artist, source_type, storage_path,
                   file_hash, added_by, added_at) VALUES (?, ?, ?, 'upload', ?, ?, ?, ?)""",
                (community_id, clean_title, clean_artist, f"uploads/{safe_name}", file_hash,
                 user["id"], config.iso(config.real_now())),
            )
    except BaseException:
        dest.unlink(missing_ok=True)  # некорректный файл не попадает в библиотеку
        raise
    t = conn.execute("SELECT * FROM tracks WHERE id = ?", (cur.lastrowid,)).fetchone()
    return {"track": _track_dict(t)}


def _resolve_storage(storage_path: str) -> Path | None:
    if storage_path.startswith("uploads/"):
        base = (config.DATA_DIR / "uploads").resolve()
    elif storage_path.startswith("catalog/"):
        base = catalog.audio_dir().resolve()
    else:
        return None
    path = (base / storage_path.split("/", 1)[1]).resolve()
    if base not in path.parents:  # защита от выхода за пределы хранилища
        return None
    return path


@app.get("/tracks/{track_id}/file")
def get_track_file(track_id: int, user=Depends(current_user),
                   conn: sqlite3.Connection = Depends(get_db)):
    t, _ = _track_for_user(conn, track_id, user["id"])
    if not t["storage_path"]:
        raise ApiError(400, "not_playable",
                       "У этой композиции нет аудиофайла — она открывается по ссылке в браузере")
    path = _resolve_storage(t["storage_path"])
    if not path or not path.exists():
        raise ApiError(404, "file_missing", "Аудиофайл не найден на сервере")
    media = "audio/wav" if path.suffix == ".wav" else "audio/mpeg"
    return FileResponse(path, media_type=media, filename=f"track_{track_id}{path.suffix}")


# ---------------------------------------------------------------- плейлист и голоса (FR-05..07)

@app.get("/communities/{community_id}/playlist")
def get_playlist(community_id: int, user=Depends(current_user),
                 conn: sqlite3.Connection = Depends(get_db)):
    c, role = _community_and_role(conn, community_id, user["id"])
    period = ensure_current_period(conn, community_id)
    return {
        "community": _community_dict(conn, c, role),
        "period": period_dict(period, period["id"]),
        "tracks": compute_ranking(conn, community_id, period["id"], user["id"]),
        "server_time": config.iso(config.now()),
    }


def _vote_state(conn, track_id: int, period_id: int, user_id: int) -> dict:
    votes = conn.execute("SELECT COUNT(*) FROM votes WHERE track_id = ? AND period_id = ?",
                         (track_id, period_id)).fetchone()[0]
    mine = conn.execute(
        "SELECT 1 FROM votes WHERE track_id = ? AND period_id = ? AND user_id = ?",
        (track_id, period_id, user_id)).fetchone() is not None
    return {"track_id": track_id, "votes": votes, "my_vote": mine}


@app.post("/tracks/{track_id}/vote")
def vote(track_id: int, user=Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    t, _ = _track_for_user(conn, track_id, user["id"])
    if t["status"] != "active":
        raise ApiError(409, "track_hidden", "Нельзя голосовать за скрытую композицию")
    period = ensure_current_period(conn, t["community_id"])
    stamp = config.iso(config.now())
    with db.transaction(conn):
        cur = conn.execute(
            "INSERT OR IGNORE INTO votes (period_id, track_id, user_id, created_at) VALUES (?, ?, ?, ?)",
            (period["id"], track_id, user["id"], stamp),
        )
        if cur.rowcount == 1:  # новый голос → событие в историю
            conn.execute(
                """INSERT INTO vote_events (period_id, track_id, user_id, action, created_at)
                   VALUES (?, ?, ?, 'vote', ?)""",
                (period["id"], track_id, user["id"], stamp),
            )
    return _vote_state(conn, track_id, period["id"], user["id"])


@app.delete("/tracks/{track_id}/vote")
def unvote(track_id: int, user=Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    t, _ = _track_for_user(conn, track_id, user["id"])
    period = ensure_current_period(conn, t["community_id"])
    stamp = config.iso(config.now())
    with db.transaction(conn):
        cur = conn.execute("DELETE FROM votes WHERE period_id = ? AND track_id = ? AND user_id = ?",
                           (period["id"], track_id, user["id"]))
        if cur.rowcount == 1:
            conn.execute(
                """INSERT INTO vote_events (period_id, track_id, user_id, action, created_at)
                   VALUES (?, ?, ?, 'unvote', ?)""",
                (period["id"], track_id, user["id"], stamp),
            )
    return _vote_state(conn, track_id, period["id"], user["id"])


# ---------------------------------------------------------------- история (FR-09, FR-11)

@app.get("/communities/{community_id}/periods")
def list_periods(community_id: int, user=Depends(current_user),
                 conn: sqlite3.Connection = Depends(get_db)):
    _community_and_role(conn, community_id, user["id"])
    current = ensure_current_period(conn, community_id)
    rows = conn.execute("SELECT * FROM periods WHERE community_id = ? ORDER BY week_start DESC",
                        (community_id,)).fetchall()
    return {"periods": [period_dict(r, current["id"]) for r in rows]}


@app.get("/communities/{community_id}/history")
def history(community_id: int, period_id: int | None = Query(None),
            user=Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    _community_and_role(conn, community_id, user["id"])
    current = ensure_current_period(conn, community_id)
    pid = period_id or current["id"]
    period = conn.execute("SELECT * FROM periods WHERE id = ? AND community_id = ?",
                          (pid, community_id)).fetchone()
    if not period:
        raise ApiError(404, "period_not_found", "Период голосования не найден")

    if period["closed_at"]:
        rows = conn.execute(
            """SELECT track_id, position, votes_count, title_snapshot, artist_snapshot
               FROM playlist_snapshots WHERE period_id = ? ORDER BY position""", (pid,)).fetchall()
        ranking = [{"track_id": r["track_id"], "position": r["position"], "votes": r["votes_count"],
                    "title": r["title_snapshot"], "artist": r["artist_snapshot"]} for r in rows]
    else:
        ranking = [{"track_id": r["id"], "position": r["position"], "votes": r["votes"],
                    "title": r["title"], "artist": r["artist"]}
                   for r in compute_ranking(conn, community_id, pid)]

    events = conn.execute(
        """SELECT e.id, e.action, e.created_at, u.display_name AS user_name,
                  t.title AS track_title, t.artist AS track_artist
           FROM vote_events e JOIN users u ON u.id = e.user_id JOIN tracks t ON t.id = e.track_id
           WHERE e.period_id = ? ORDER BY e.id DESC LIMIT 500""", (pid,)).fetchall()
    return {
        "period": period_dict(period, current["id"]),
        "ranking": ranking,
        "events": [dict(e) for e in events],
    }


# ---------------------------------------------------------------- модерация (FR-10)

class ModerationIn(BaseModel):
    status: str  # "hidden" или "active"


@app.patch("/tracks/{track_id}/moderation")
def moderate(track_id: int, body: ModerationIn, user=Depends(current_user),
             conn: sqlite3.Connection = Depends(get_db)):
    t, role = _track_for_user(conn, track_id, user["id"])
    _require_moderator(role)
    if body.status not in ("hidden", "active"):
        raise ApiError(400, "validation_error", "Статус может быть только hidden или active")
    conn.execute("UPDATE tracks SET status = ? WHERE id = ?", (body.status, track_id))
    t = conn.execute("SELECT * FROM tracks WHERE id = ?", (track_id,)).fetchone()
    return {"track": _track_dict(t)}
