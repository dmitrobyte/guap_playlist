"""Логика рейтинга и еженедельной ротации (FR-06, FR-11)."""
import sqlite3
from datetime import date, datetime, timedelta

from server import config
from server.db import transaction


def week_start_for(moment: datetime) -> date:
    """Понедельник недели, в которую попадает момент (в часовом поясе сервера)."""
    local = moment.astimezone(config.TIMEZONE)
    return local.date() - timedelta(days=local.weekday())


def compute_ranking(conn: sqlite3.Connection, community_id: int, period_id: int,
                    user_id: int | None = None) -> list[dict]:
    """Рейтинг = число активных голосов за период.
    Сортировка: голоса ↓, затем раньше добавленные, затем id."""
    rows = conn.execute(
        """
        SELECT t.id, t.title, t.artist, t.source_type, t.source_url, t.storage_path,
               t.added_at, t.added_by, u.display_name AS added_by_name,
               COUNT(v.id) AS votes,
               MAX(CASE WHEN v.user_id = ? THEN 1 ELSE 0 END) AS my_vote
        FROM tracks t
        JOIN users u ON u.id = t.added_by
        LEFT JOIN votes v ON v.track_id = t.id AND v.period_id = ?
        WHERE t.community_id = ? AND t.status = 'active'
        GROUP BY t.id
        ORDER BY votes DESC, t.added_at ASC, t.id ASC
        """,
        (user_id if user_id is not None else -1, period_id, community_id),
    ).fetchall()
    result = []
    for position, r in enumerate(rows, start=1):
        result.append({
            "position": position,
            "id": r["id"],
            "title": r["title"],
            "artist": r["artist"],
            "source_type": r["source_type"],
            "source_url": r["source_url"],
            "playable": bool(r["storage_path"]),
            "added_at": r["added_at"],
            "added_by_name": r["added_by_name"],
            "votes": r["votes"],
            "my_vote": bool(r["my_vote"]),
        })
    return result


def _save_snapshot(conn: sqlite3.Connection, community_id: int, period_id: int) -> None:
    for item in compute_ranking(conn, community_id, period_id):
        conn.execute(
            """INSERT OR IGNORE INTO playlist_snapshots
               (period_id, track_id, position, votes_count, title_snapshot, artist_snapshot)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (period_id, item["id"], item["position"], item["votes"], item["title"], item["artist"]),
        )


def ensure_current_period(conn: sqlite3.Connection, community_id: int) -> sqlite3.Row:
    """Возвращает период текущей недели. Если неделя сменилась — сохраняет снимок
    итогов прошлых периодов и создаёт новый. Выполняется при обращении к серверу,
    отдельная фоновая служба не нужна. Внутри транзакции, поэтому ротация
    выполняется ровно один раз."""
    ws = week_start_for(config.now()).isoformat()
    row = conn.execute(
        "SELECT * FROM periods WHERE community_id = ? AND week_start = ?", (community_id, ws)
    ).fetchone()
    if row:
        return row

    with transaction(conn):
        row = conn.execute(
            "SELECT * FROM periods WHERE community_id = ? AND week_start = ?", (community_id, ws)
        ).fetchone()
        if row:
            return row
        latest = conn.execute(
            "SELECT * FROM periods WHERE community_id = ? ORDER BY week_start DESC LIMIT 1",
            (community_id,),
        ).fetchone()
        if latest and latest["week_start"] > ws:
            # Часы сервера "ушли назад" (например, после теста с подменённой датой) —
            # назад не откатываемся, работаем с последним периодом.
            return latest

        stamp = config.iso(config.now())
        open_periods = conn.execute(
            "SELECT id FROM periods WHERE community_id = ? AND closed_at IS NULL AND week_start < ?",
            (community_id, ws),
        ).fetchall()
        for p in open_periods:
            _save_snapshot(conn, community_id, p["id"])
            conn.execute("UPDATE periods SET closed_at = ? WHERE id = ?", (stamp, p["id"]))

        cur = conn.execute(
            "INSERT INTO periods (community_id, week_start, created_at) VALUES (?, ?, ?)",
            (community_id, ws, stamp),
        )
        return conn.execute("SELECT * FROM periods WHERE id = ?", (cur.lastrowid,)).fetchone()


def period_dict(p: sqlite3.Row, current_id: int | None = None) -> dict:
    start = date.fromisoformat(p["week_start"])
    return {
        "id": p["id"],
        "week_start": p["week_start"],
        "week_end": (start + timedelta(days=6)).isoformat(),
        "closed": p["closed_at"] is not None,
        "is_current": current_id == p["id"],
    }
