"""Headless-прогон всех окон клиента со скриншотами.

    python run_server.py --port 8766 --data-dir ui_test_data   (в отдельном окне)
    python tests/ui_smoke.py http://127.0.0.1:8766 screenshots

Нужен запущенный сервер на чистой папке данных. Скриншоты сохраняются в указанную папку.
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, QPoint, QSettings  # noqa: E402

import client.player as cp  # noqa: E402

if os.environ.get("UI_SMOKE_NO_AUDIO") == "1":
    # В средах без звуковой карты (CI, облако) создание аудиовыхода Qt падает — подменяем только его
    class _FakeOut(QObject):
        def setVolume(self, v):
            pass

    class _Player(cp.QMediaPlayer):
        def setAudioOutput(self, o):
            pass

    cp.QAudioOutput, cp.QMediaPlayer = _FakeOut, _Player

from client.api import ApiClient  # noqa: E402
from client.app import App  # noqa: E402
from client.dialogs import AddMusicDialog, HistoryDialog, ManageDialog  # noqa: E402
from client.widgets import PromptDialog, VoteButton  # noqa: E402

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8766"
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else "screenshots")
OUT.mkdir(parents=True, exist_ok=True)
QSettings("SharedPlaylist", "Client").clear()

app = App()


def pump(sec=1.0):
    end = time.time() + sec
    while time.time() < end:
        app.qt.processEvents()
        time.sleep(0.02)


def shot(widget, name):
    widget.grab().save(str(OUT / f"{name}.png"))
    print("  screenshot:", name)


def check(cond, msg):
    if not cond:
        raise SystemExit(f"FAIL: {msg}")
    print("  ok:", msg)


# ---------------------------------------------------------------- экран входа
L = app.login
L.server_edit.setText(URL)
pump(0.5)
shot(L, "01_login")
L.tabs.set_current(1)
L.login_edit.setText("anna")
L.name_edit.setText("Анна Смирнова")
L.password_edit.setText("x")
L._submit()
pump(0.3)
check(L.status.text().startswith("Пароль"), "клиентская проверка короткого пароля")
shot(L, "02_register_error")
L.password_edit.setText("secret123")
L._submit()
pump(2)
check(app.main is not None, "регистрация открывает главное окно")
W = app.main
W.resize(1280, 800)
pump(1)
shot(W, "03_main_no_communities")

# ---------------------------------------------------------------- данные
c = app.api.create_community("Группа ИВТ-21")
W.load_communities(select_id=c["id"])
pump(1.5)
shot(W, "04_empty_playlist")
for k in ["demo-01", "demo-02", "demo-03", "demo-04", "demo-05", "demo-06"]:
    app.api.add_catalog_track(c["id"], k)
app.api.add_link_track(c["id"], "Midnight City", "M83", "https://example.com/song")
b = ApiClient(URL)
b.register("boris", "Борис", "secret123")
b.join_community(c["invite_code"])
v = ApiClient(URL)
v.register("vera", "Вера", "secret123")
v.join_community(c["invite_code"])
tr = {t["title"]: t["id"] for t in b.playlist(c["id"])["tracks"]}
for api, titles in [(b, ["Перемена", "Midnight City", "Ночной коворкинг"]),
                    (v, ["Перемена"])]:
    for t in titles:
        api.vote(tr[t])
W.view.refresh()
pump(2)

# ---------------------------------------------------------------- голос кликом
rows = W.view.list.rows
row = next(r for r in rows if r.track["title"] == "Midnight City")
check(isinstance(row.vote_btn, VoteButton) and not row.vote_btn.voted, "у строки есть пилюля голосования")
row.vote_btn.click()
pump(2)
rows = W.view.list.rows
titles = [r.track["title"] for r in rows]
print("  порядок:", titles)
check(titles[0] == "Перемена" and titles[1] == "Midnight City", "голос поднял трек на 2-е место")
top2 = rows[1]
check(top2.vote_btn.voted and top2.vote_btn.votes == 2, "голос учтён и подсвечен")
check(top2.move_label.text().startswith("▲"), "показана стрелка роста позиции")

# ---------------------------------------------------------------- воспроизведение
W.player.play_track(W.view.data["tracks"][0])
pump(3)
check(W.player.title.text() == "Перемена", "трек загружен в плеер")
rows = W.view.list.rows
# наведение мыши на строку — мягкая подсветка и кнопка «Скрыть»
hover_row = rows[2]
hover_row.enterEvent(None) if False else None
hover_row._hover = True
hover_row.on_hover(True)
hover_row.update()
pump(0.3)
W.notify("Код приглашения скопирован в буфер обмена", "success")
pump(0.4)
shot(W, "05_main_playlist")

# ---------------------------------------------------------------- диалоги
d = AddMusicDialog(app.api, c["id"], W)
d.show()
pump(1.5)
check(len(d.catalog_list.rows) == 6, "библиотека загружена")
shot(d, "06_add_library")
d.tabs.set_current(1)
pump(0.3)
shot(d, "07_add_file")
d.tabs.set_current(2)
d.link_url.setText("ftp://bad")
d.link_title.setText("x")
d.link_artist.setText("y")
d.add_link()
pump(0.3)
check("http" in d.status.text(), "проверка протокола ссылки")
shot(d, "08_add_link_error")
d.close()

h = HistoryDialog(app.api, c["id"], W)
h.show()
pump(2)
check(len(h.ranking.rows) == 7, "рейтинг недели в истории")
shot(h, "09_history_ranking")
h.tabs.set_current(1)
pump(0.3)
check(len(h.events.rows) == 5, "журнал голосов")
shot(h, "10_history_log")
h.close()

m = ManageDialog(app.api, W.view.data["community"], W.me["id"], W)
m.show()
pump(1.5)
shot(m, "11_manage_invite")
m.tabs.set_current(1)
pump(0.3)
check(len(m.members_list.rows) == 3, "участники в модерации")
shot(m, "12_manage_members")
app.api.moderate(tr["Сессия близко"], "hidden")
m._reload()
m.tabs.set_current(2)
pump(1)
check(len(m.hidden_list.rows) == 1, "скрытый трек в модерации")
shot(m, "13_manage_hidden")
m.close()

p = PromptDialog(W, "Скрыть композицию?", "«Перемена» исчезнет из активного плейлиста у всех участников.",
                 "Скрыть", danger=True)
p.show()
pump(0.3)
shot(p, "14_confirm")
p.close()

# ---------------------------------------------------------------- клиент обычного участника
W.view.refresh()
pump(1.5)
check(len(W.view.list.rows) == 6, "скрытый трек пропал из плейлиста")
tok = QSettings("SharedPlaylist", "Client").value("token")
check(bool(tok), "токен сохранён для входа после перезапуска")
print("ALL OK")
