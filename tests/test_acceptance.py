"""Автотесты по таблице критериев приёмки (раздел 13 ТЗ).
Запуск: python -m pytest -v
"""
import io
import struct
import wave
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from server import config, security


@pytest.fixture()
def app_client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(security, "PBKDF2_ITERATIONS", 1000)  # быстрее в тестах
    config.set_fake_now(datetime(2026, 10, 14, 12, 0))  # среда
    from server.main import app
    with TestClient(app) as c:
        yield c
    config.set_fake_now(None)


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def register(c, login, name=None, pw="secret123"):
    r = c.post("/auth/register", json={"login": login, "display_name": name or login, "password": pw})
    assert r.status_code == 201, r.text
    return r.json()["token"]


def make_wav(seconds=0.2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000)
        w.writeframes(struct.pack("<h", 0) * int(8000 * seconds))
    return buf.getvalue()


@pytest.fixture()
def group(app_client):
    """Два пользователя в одном сообществе."""
    c = app_client
    a = register(c, "anna", "Анна")
    b = register(c, "boris", "Борис")
    com = c.post("/communities", json={"name": "ИВТ-21"}, headers=auth(a)).json()["community"]
    r = c.post("/communities/join", json={"invite_code": com["invite_code"]}, headers=auth(b))
    assert r.status_code == 200
    return c, a, b, com["id"]


def playlist(c, token, cid):
    r = c.get(f"/communities/{cid}/playlist", headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()


def add_catalog(c, token, cid, key):
    r = c.post(f"/communities/{cid}/tracks", json={"source_type": "catalog", "catalog_key": key},
               headers=auth(token))
    assert r.status_code == 201, r.text
    return r.json()["track"]["id"]


# 1–3
def test_register_duplicate_login(app_client):
    c = app_client
    register(c, "anna")
    r = c.post("/auth/register", json={"login": "ANNA", "display_name": "x", "password": "secret123"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "login_taken"
    r = c.post("/auth/login", json={"login": "anna", "password": "wrong"})
    assert r.status_code == 401 and "Неверный" in r.json()["error"]["message"]
    r = c.post("/auth/login", json={"login": "anna", "password": "secret123"})
    assert r.status_code == 200
    assert c.get("/auth/me", headers=auth(r.json()["token"])).json()["user"]["login"] == "anna"
    assert c.get("/communities").status_code == 401  # без токена нельзя


def test_password_not_stored_plain(app_client):
    register(app_client, "anna", pw="supersecret")
    from server import db
    conn = db.connect()
    row = conn.execute("SELECT password_hash FROM users").fetchone()
    assert "supersecret" not in row[0]


# 4–5
def test_create_and_join(group):
    c, a, b, cid = group
    names = [x["name"] for x in c.get("/communities", headers=auth(b)).json()["communities"]]
    assert names == ["ИВТ-21"]
    info = c.get(f"/communities/{cid}", headers=auth(a)).json()
    assert info["community"]["my_role"] == "owner" and info["community"]["member_count"] == 2
    code = info["community"]["invite_code"]
    r = c.post("/communities/join", json={"invite_code": code}, headers=auth(b))
    assert r.json()["already_member"] is True  # повторного членства нет
    assert c.get(f"/communities/{cid}", headers=auth(a)).json()["community"]["member_count"] == 2
    bad = c.post("/communities/join", json={"invite_code": "NOPE1234"}, headers=auth(b))
    assert bad.status_code == 404


def test_regenerate_invite(group):
    c, a, b, cid = group
    old = c.get(f"/communities/{cid}", headers=auth(a)).json()["community"]["invite_code"]
    assert c.post(f"/communities/{cid}/invite/regenerate", headers=auth(b)).status_code == 403
    new = c.post(f"/communities/{cid}/invite/regenerate", headers=auth(a)).json()["invite_code"]
    assert new != old
    v = register(c, "vera")
    assert c.post("/communities/join", json={"invite_code": old}, headers=auth(v)).status_code == 404
    assert c.post("/communities/join", json={"invite_code": new}, headers=auth(v)).status_code == 200


# 6–8
def test_add_three_kinds(group):
    c, a, b, cid = group
    add_catalog(c, a, cid, "demo-01")
    dup = c.post(f"/communities/{cid}/tracks", json={"source_type": "catalog", "catalog_key": "demo-01"},
                 headers=auth(b))
    assert dup.status_code == 409

    r = c.post(f"/communities/{cid}/tracks/upload", headers=auth(b),
               files={"file": ("моя песня.wav", make_wav(), "audio/wav")},
               data={"title": "Своя песня", "artist": "Борис"})
    assert r.status_code == 201, r.text
    up_id = r.json()["track"]["id"]
    f = c.get(f"/tracks/{up_id}/file", headers=auth(a))
    assert f.status_code == 200 and f.content[:4] == b"RIFF"

    r = c.post(f"/communities/{cid}/tracks", headers=auth(a), json={
        "source_type": "link", "title": "Song", "artist": "Band", "url": "https://music.example.com/t/1"})
    assert r.status_code == 201
    for bad in ["file:///C:/Windows/calc.exe", "javascript:alert(1)", "C:\\music.mp3", "ftp://x.ru/a"]:
        r = c.post(f"/communities/{cid}/tracks", headers=auth(a),
                   json={"source_type": "link", "title": "x", "artist": "y", "url": bad})
        assert r.status_code == 400, bad

    tracks = playlist(c, b, cid)["tracks"]
    assert {t["source_type"] for t in tracks} == {"catalog", "upload", "link"}
    assert c.get(f"/tracks/{add_catalog(c, a, cid, 'demo-02')}/file", headers=auth(b)).status_code == 200


def test_upload_validation(group, tmp_path):
    c, a, b, cid = group
    r = c.post(f"/communities/{cid}/tracks/upload", headers=auth(a),
               files={"file": ("virus.exe", b"MZ....", "application/octet-stream")})
    assert r.status_code == 415
    r = c.post(f"/communities/{cid}/tracks/upload", headers=auth(a),
               files={"file": ("fake.mp3", b"this is text, not audio", "audio/mpeg")})
    assert r.status_code == 415
    big = b"ID3" + b"\0" * (config.MAX_UPLOAD_BYTES + 10)
    r = c.post(f"/communities/{cid}/tracks/upload", headers=auth(a),
               files={"file": ("big.mp3", big, "audio/mpeg")})
    assert r.status_code == 413
    # отклонённые файлы не остались в хранилище
    assert list((config.DATA_DIR / "uploads").iterdir()) == []


# 9–13
def test_voting_and_ranking(group):
    c, a, b, cid = group
    t1 = add_catalog(c, a, cid, "demo-01")
    t2 = add_catalog(c, a, cid, "demo-02")
    t3 = add_catalog(c, a, cid, "demo-03")
    assert [t["id"] for t in playlist(c, a, cid)["tracks"]] == [t1, t2, t3]  # равенство → раньше добавленный

    assert c.post(f"/tracks/{t3}/vote", headers=auth(a)).json()["votes"] == 1      # 9
    assert c.post(f"/tracks/{t3}/vote", headers=auth(a)).json()["votes"] == 1      # 10 — нет второго голоса
    assert c.post(f"/tracks/{t3}/vote", headers=auth(b)).json()["votes"] == 2      # 12
    c.post(f"/tracks/{t2}/vote", headers=auth(b))
    pa, pb = playlist(c, a, cid)["tracks"], playlist(c, b, cid)["tracks"]
    assert [t["id"] for t in pa] == [t3, t2, t1] == [t["id"] for t in pb]          # 13
    assert [t["votes"] for t in pa] == [2, 1, 0]
    assert pa[1]["my_vote"] is False and pb[1]["my_vote"] is True

    r = c.delete(f"/tracks/{t3}/vote", headers=auth(a))                             # 11
    assert r.json() == {"track_id": t3, "votes": 1, "my_vote": False}
    # равенство голосов 1:1 → раньше добавленный t2 выше t3
    assert [t["id"] for t in playlist(c, a, cid)["tracks"]] == [t2, t3, t1]


def test_outsider_cannot_vote(group):
    c, a, b, cid = group
    t1 = add_catalog(c, a, cid, "demo-01")
    x = register(c, "stranger")
    assert c.post(f"/tracks/{t1}/vote", headers=auth(x)).status_code == 403
    assert c.get(f"/communities/{cid}/playlist", headers=auth(x)).status_code == 403
    assert c.get(f"/tracks/{t1}/file", headers=auth(x)).status_code == 403


# 14
def test_history(group):
    c, a, b, cid = group
    t1 = add_catalog(c, a, cid, "demo-01")
    c.post(f"/tracks/{t1}/vote", headers=auth(a))
    c.delete(f"/tracks/{t1}/vote", headers=auth(a))
    c.post(f"/tracks/{t1}/vote", headers=auth(b))
    h = c.get(f"/communities/{cid}/history", headers=auth(b)).json()
    assert [(e["user_name"], e["action"]) for e in h["events"]] == [
        ("Борис", "vote"), ("Анна", "unvote"), ("Анна", "vote")]


# 15–16
def test_moderation(group):
    c, a, b, cid = group
    t1 = add_catalog(c, b, cid, "demo-01")
    c.post(f"/tracks/{t1}/vote", headers=auth(b))
    assert c.patch(f"/tracks/{t1}/moderation", json={"status": "hidden"}, headers=auth(b)).status_code == 403
    assert c.patch(f"/tracks/{t1}/moderation", json={"status": "hidden"}, headers=auth(a)).status_code == 200
    assert playlist(c, b, cid)["tracks"] == []
    assert c.post(f"/tracks/{t1}/vote", headers=auth(a)).status_code == 409
    assert len(c.get(f"/communities/{cid}/history", headers=auth(a)).json()["events"]) == 1  # история цела
    # владелец назначает модератора → тот может восстановить
    me_b = c.get("/auth/me", headers=auth(b)).json()["user"]["id"]
    assert c.post(f"/communities/{cid}/members/{me_b}/role", json={"role": "moderator"},
                  headers=auth(a)).status_code == 200
    assert c.patch(f"/tracks/{t1}/moderation", json={"status": "active"}, headers=auth(b)).status_code == 200
    assert len(playlist(c, a, cid)["tracks"]) == 1


# 17–18
def test_weekly_rotation(group):
    c, a, b, cid = group
    t1 = add_catalog(c, a, cid, "demo-01")
    t2 = add_catalog(c, a, cid, "demo-02")
    c.post(f"/tracks/{t2}/vote", headers=auth(a))
    c.post(f"/tracks/{t2}/vote", headers=auth(b))
    c.post(f"/tracks/{t1}/vote", headers=auth(b))
    first = playlist(c, a, cid)["period"]
    assert first["week_start"] == "2026-10-12"

    # Воскресенье 23:59 по Москве — ещё та же неделя
    config.set_fake_now(datetime(2026, 10, 18, 23, 59))
    assert playlist(c, a, cid)["period"]["id"] == first["id"]

    # Понедельник 00:00 по Москве — новая неделя
    config.set_fake_now(datetime(2026, 10, 19, 0, 0))
    p = playlist(c, a, cid)
    assert p["period"]["week_start"] == "2026-10-19" and p["period"]["id"] != first["id"]
    assert all(t["votes"] == 0 for t in p["tracks"])
    playlist(c, b, cid)  # повторное обращение — ротация не повторяется
    periods = c.get(f"/communities/{cid}/periods", headers=auth(a)).json()["periods"]
    assert len(periods) == 2 and periods[1]["closed"] is True

    # Изменение трека после закрытия недели не меняет исторический снимок
    c.patch(f"/tracks/{t2}/moderation", json={"status": "hidden"}, headers=auth(a))
    h = c.get(f"/communities/{cid}/history", params={"period_id": first["id"]}, headers=auth(b)).json()
    assert [(r["track_id"], r["position"], r["votes"]) for r in h["ranking"]] == [(t2, 1, 2), (t1, 2, 1)]
    assert len(h["events"]) == 3


# 19–20
def test_data_survives_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(security, "PBKDF2_ITERATIONS", 1000)
    from server.main import app
    with TestClient(app) as c:
        a = register(c, "anna")
        cid = c.post("/communities", json={"name": "Группа"}, headers=auth(a)).json()["community"]["id"]
        r = c.post(f"/communities/{cid}/tracks/upload", headers=auth(a),
                   files={"file": ("x.wav", make_wav(), "audio/wav")})
        tid = r.json()["track"]["id"]
        c.post(f"/tracks/{tid}/vote", headers=auth(a))
    with TestClient(app) as c:  # «перезапуск» сервера
        assert c.get("/auth/me", headers=auth(a)).status_code == 200      # токен клиента действует
        t = playlist(c, a, cid)["tracks"][0]
        assert t["votes"] == 1 and t["my_vote"]
        assert c.get(f"/tracks/{tid}/file", headers=auth(a)).status_code == 200


def test_100_tracks_fast(group):
    import time
    c, a, b, cid = group
    for i in range(100):
        c.post(f"/communities/{cid}/tracks", headers=auth(a), json={
            "source_type": "link", "title": f"Track {i}", "artist": "A", "url": f"https://ex.com/{i}"})
    start = time.perf_counter()
    tracks = playlist(c, b, cid)["tracks"]
    assert len(tracks) == 100 and time.perf_counter() - start < 1.0
