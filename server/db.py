"""Работа с SQLite: подключение, схема, транзакции."""
import sqlite3
from contextlib import contextmanager

from server import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    login         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name  TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    password_salt TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    is_active     INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,          -- храним только хеш токена
    user_id    INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS communities (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    invite_code TEXT NOT NULL UNIQUE,
    owner_id    INTEGER NOT NULL REFERENCES users(id),
    created_at  TEXT NOT NULL,
    is_active   INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS memberships (
    user_id      INTEGER NOT NULL REFERENCES users(id),
    community_id INTEGER NOT NULL REFERENCES communities(id),
    role         TEXT NOT NULL CHECK (role IN ('owner', 'moderator', 'member')),
    joined_at    TEXT NOT NULL,
    PRIMARY KEY (user_id, community_id)
);

CREATE TABLE IF NOT EXISTS tracks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    community_id INTEGER NOT NULL REFERENCES communities(id),
    title        TEXT NOT NULL,
    artist       TEXT NOT NULL,
    source_type  TEXT NOT NULL CHECK (source_type IN ('catalog', 'upload', 'link')),
    source_url   TEXT,
    storage_path TEXT,
    catalog_key  TEXT,                    -- ключ записи каталога (защита от дублей)
    file_hash    TEXT,                    -- SHA-256 загруженного файла (защита от дублей)
    added_by     INTEGER NOT NULL REFERENCES users(id),
    status       TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'hidden')),
    added_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tracks_community ON tracks(community_id, status);

CREATE TABLE IF NOT EXISTS periods (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    community_id INTEGER NOT NULL REFERENCES communities(id),
    week_start   TEXT NOT NULL,           -- YYYY-MM-DD (понедельник)
    created_at   TEXT NOT NULL,
    closed_at    TEXT,                    -- когда сохранён итоговый снимок
    UNIQUE (community_id, week_start)
);

CREATE TABLE IF NOT EXISTS votes (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    period_id  INTEGER NOT NULL REFERENCES periods(id),
    track_id   INTEGER NOT NULL REFERENCES tracks(id),
    user_id    INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    UNIQUE (period_id, track_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_votes_period ON votes(period_id, track_id);

CREATE TABLE IF NOT EXISTS vote_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    period_id  INTEGER NOT NULL REFERENCES periods(id),
    track_id   INTEGER NOT NULL REFERENCES tracks(id),
    user_id    INTEGER NOT NULL REFERENCES users(id),
    action     TEXT NOT NULL CHECK (action IN ('vote', 'unvote')),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_period ON vote_events(period_id);

CREATE TABLE IF NOT EXISTS playlist_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    period_id       INTEGER NOT NULL REFERENCES periods(id),
    track_id        INTEGER NOT NULL REFERENCES tracks(id),
    position        INTEGER NOT NULL,
    votes_count     INTEGER NOT NULL,
    title_snapshot  TEXT NOT NULL,
    artist_snapshot TEXT NOT NULL,
    UNIQUE (period_id, track_id)
);
"""


def connect() -> sqlite3.Connection:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    # isolation_level=None — автокоммит; транзакции открываем явно (см. transaction)
    conn = sqlite3.connect(
        config.DATA_DIR / "playlist.db",
        timeout=10,
        isolation_level=None,
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def init_db() -> None:
    conn = connect()
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
    finally:
        conn.close()


@contextmanager
def transaction(conn: sqlite3.Connection):
    """Атомарный блок: либо все изменения сохраняются, либо ни одного."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
