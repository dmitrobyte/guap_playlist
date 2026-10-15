"""Экраны 4 и 5: добавление музыки, история и ротация, модерация.
Единый стиль: панель #121215, сегментные вкладки, строки-карточки вместо таблиц."""
import os
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLineEdit, QProgressBar,
                               QStackedWidget, QVBoxLayout, QWidget)

from client import theme
from client.api import ApiClient
from client.util import ROLE_NAMES, fmt_time, fmt_week
from client.widgets import (AvatarWidget, ComboBox, DropZone, ElidedLabel, HoverRow, PillTabs, PromptDialog,
                            RowList, StyledDialog, TrackCoverWidget, button, label, restyle)
from client.workers import run_async

MAX_UPLOAD_MB = 20


def _two_lines(top: str, bottom: str, top_color: str = theme.TEXT) -> QVBoxLayout:
    col = QVBoxLayout()
    col.setSpacing(2)
    col.addStretch(1)
    col.addWidget(ElidedLabel(top, 13, 600, top_color))
    col.addWidget(ElidedLabel(bottom, 12, 400, theme.TEXT_2))
    col.addStretch(1)
    return col


def _row(height: int = 52) -> tuple[HoverRow, QHBoxLayout]:
    row = HoverRow(height, theme.SURFACE_HOVER)
    lay = QHBoxLayout(row)
    lay.setContentsMargins(10, 0, 10, 0)
    lay.setSpacing(12)
    return row, lay


def _field(caption: str, widget: QWidget) -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(6)
    lay.addWidget(label(caption, "field"))
    lay.addWidget(widget)
    return w


class _StatusMixin:
    """Тонкая полоса прогресса + строка статуса внизу диалога."""

    def _init_status(self, parent_layout: QVBoxLayout) -> None:
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.hide()
        self.status = label("", "secondary")
        self.status.setWordWrap(True)
        parent_layout.addWidget(self.progress)
        parent_layout.addWidget(self.status)

    def _set_status(self, text: str, error: bool = False) -> None:
        self.status.setProperty("textRole", "error" if error else "secondary")
        restyle(self.status)
        self.status.setText(text)


# ======================================================================= добавление музыки
class AddMusicDialog(_StatusMixin, StyledDialog):
    def __init__(self, api: ApiClient, community_id: int, parent=None):
        super().__init__("Добавить музыку",
                         "Новая композиция сразу появится у всех участников и начнёт собирать голоса.",
                         parent, width=600)
        self.api, self.cid = api, community_id
        self.result_message = ""
        self.resize(600, 560)

        self.tabs = PillTabs(["Библиотека", "Файл", "Ссылка"])
        self.pages = QStackedWidget()
        self.pages.addWidget(self._library_page())
        self.pages.addWidget(self._file_page())
        self.pages.addWidget(self._link_page())
        self.tabs.changed.connect(self._tab_changed)
        self.body.addWidget(self.tabs)
        self.body.addSpacing(4)
        self.body.addWidget(self.pages, 1)
        self._init_status(self.body)

        cancel = button("Отмена", "ghost")
        cancel.clicked.connect(self.reject)
        self.primary = button("Загрузить", "primary")
        self.primary.clicked.connect(self._primary_action)
        self.footer.addStretch(1)
        self.footer.addWidget(cancel)
        self.footer.addWidget(self.primary)
        self._tab_changed(0)
        self._load_catalog()

    # ------------------------------------------------------------ страницы
    def _library_page(self) -> QWidget:
        self.catalog_list = RowList("Загрузка библиотеки…")
        return self.catalog_list

    def _file_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(14)
        self.drop = DropZone()
        self.drop.subtitle = f"или нажмите, чтобы выбрать  ·  до {MAX_UPLOAD_MB} МБ"
        self.drop.file_chosen.connect(self._file_chosen)
        self.file_title = QLineEdit()
        self.file_title.setPlaceholderText("По умолчанию — имя файла")
        self.file_artist = QLineEdit()
        self.file_artist.setPlaceholderText("Необязательно")
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(_field("Название", self.file_title))
        row.addWidget(_field("Исполнитель", self.file_artist))
        lay.addWidget(self.drop)
        lay.addLayout(row)
        lay.addStretch(1)
        self.file_path = ""
        return w

    def _link_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(14)
        self.link_title = QLineEdit()
        self.link_artist = QLineEdit()
        self.link_url = QLineEdit()
        self.link_url.setPlaceholderText("https://music.yandex.ru/…")
        self.link_url.returnPressed.connect(self.add_link)
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(_field("Название", self.link_title))
        row.addWidget(_field("Исполнитель", self.link_artist))
        lay.addLayout(row)
        lay.addWidget(_field("Ссылка на музыкальный сервис", self.link_url))
        hint = label("Такие композиции открываются во внешнем браузере. "
                     "Принимаются только адреса http:// и https://.", "muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        lay.addStretch(1)
        return w

    def _tab_changed(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        self.primary.setVisible(index != 0)
        self.primary.setText({1: "Загрузить на сервер", 2: "Добавить ссылку"}.get(index, ""))
        self._set_status("")

    def _primary_action(self) -> None:
        if self.pages.currentIndex() == 1:
            self.upload_file()
        elif self.pages.currentIndex() == 2:
            self.add_link()

    # ------------------------------------------------------------ общее
    def _busy(self, text: str) -> None:
        self.progress.show()
        self._set_status(text)
        self.setEnabled(False)

    def _done(self, track=None) -> None:
        self.progress.hide()
        self.setEnabled(True)
        if track:
            self.result_message = f"Добавлено: «{track['title']}»"
        self.accept()  # возвращаемся к плейлисту

    def _fail(self, message: str, _exc=None) -> None:
        self.progress.hide()
        self.setEnabled(True)
        self._set_status(message, error=True)

    # ------------------------------------------------------------ библиотека
    def _load_catalog(self) -> None:
        def ok(items):
            rows = []
            for e in items:
                row, lay = _row(56)
                cover = TrackCoverWidget(40, 6)
                cover.set_track(e["title"], e["artist"])
                lay.addWidget(cover)
                lay.addLayout(_two_lines(e["title"], e["artist"]), 1)
                row.setToolTip(e["source_info"])
                add = button("+  Добавить", "small")
                add.clicked.connect(lambda _=False, key=e["key"]: self.add_from_catalog(key))
                lay.addWidget(add)
                rows.append(row)
            self.catalog_list.set_empty_text("Библиотека пуста")
            self.catalog_list.set_rows(rows)
        run_async(self.api.catalog, on_ok=ok, on_fail=self._fail)

    def add_from_catalog(self, key: str) -> None:
        self._busy("Добавляем…")
        run_async(self.api.add_catalog_track, self.cid, key, on_ok=self._done, on_fail=self._fail)

    # ------------------------------------------------------------ файл
    def _file_chosen(self, path: str) -> None:
        p = Path(path)
        if p.suffix.lower() not in (".mp3", ".wav"):
            self._set_status("Поддерживаются только файлы MP3 и WAV", error=True)
            return
        size_mb = os.path.getsize(path) / (1024 * 1024)
        self.file_path = path
        self.drop.set_file(path, p.name, f"{size_mb:.1f} МБ  ·  нажмите, чтобы выбрать другой файл")
        if not self.file_title.text():
            self.file_title.setText(p.stem)
        self._set_status("")

    def upload_file(self) -> None:
        path = self.file_path
        if not path or not os.path.isfile(path):
            self._fail("Выберите файл на компьютере")
            return
        size_mb = os.path.getsize(path) / (1024 * 1024)
        if size_mb > MAX_UPLOAD_MB:
            self._fail(f"Файл весит {size_mb:.1f} МБ — это больше лимита {MAX_UPLOAD_MB} МБ")
            return
        self._busy(f"Загружаем файл ({size_mb:.1f} МБ)…")
        run_async(self.api.upload_track, self.cid, path, self.file_title.text().strip(),
                  self.file_artist.text().strip(), on_ok=self._done, on_fail=self._fail)

    # ------------------------------------------------------------ ссылка
    def add_link(self) -> None:
        title, artist, url = (self.link_title.text().strip(), self.link_artist.text().strip(),
                              self.link_url.text().strip())
        if not title or not artist or not url:
            self._fail("Заполните название, исполнителя и ссылку")
            return
        p = urlparse(url)
        if p.scheme.lower() not in ("http", "https") or not p.netloc:
            self._fail("Ссылка должна начинаться с http:// или https://")
            return
        self._busy("Добавляем ссылку…")
        run_async(self.api.add_link_track, self.cid, title, artist, url,
                  on_ok=self._done, on_fail=self._fail)


# ======================================================================= история и ротация
class HistoryDialog(_StatusMixin, StyledDialog):
    def __init__(self, api: ApiClient, community_id: int, parent=None):
        super().__init__("История и ротация",
                         "Каждый понедельник в 00:00 голосование начинается заново. "
                         "Итоги прошедших недель сохраняются и больше не меняются.",
                         parent, width=680)
        self.api, self.cid = api, community_id
        self.resize(680, 620)

        self.period_combo = ComboBox()
        self.period_combo.setMinimumWidth(300)
        self.period_combo.currentIndexChanged.connect(self._load_history)
        self.state_badge = label("", "badge")
        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(self.period_combo)
        top.addWidget(self.state_badge, 0, Qt.AlignVCenter)
        top.addStretch(1)

        self.tabs = PillTabs(["Рейтинг недели", "Журнал голосов"])
        self.ranking = RowList("За эту неделю композиций нет")
        self.events = RowList("Пока никто не голосовал")
        self.pages = QStackedWidget()
        self.pages.addWidget(self.ranking)
        self.pages.addWidget(self.events)
        self.tabs.changed.connect(self.pages.setCurrentIndex)

        self.body.addLayout(top)
        self.body.addWidget(self.tabs)
        self.body.addWidget(self.pages, 1)
        self._init_status(self.body)
        close = button("Закрыть")
        close.clicked.connect(self.accept)
        self.footer.addStretch(1)
        self.footer.addWidget(close)

        run_async(self.api.periods, self.cid, on_ok=self._periods_loaded,
                  on_fail=lambda m, _e: self._set_status(m, True))

    def _periods_loaded(self, periods: list[dict]) -> None:
        self.period_combo.blockSignals(True)
        for p in periods:
            self.period_combo.addItem(fmt_week(p) + ("  ·  текущая" if p["is_current"] else "  ·  завершена"),
                                      p["id"])
        self.period_combo.blockSignals(False)
        self._load_history()

    def _load_history(self) -> None:
        pid = self.period_combo.currentData()
        if pid is None:
            return
        self.progress.show()
        run_async(self.api.history, self.cid, pid, on_ok=self._show,
                  on_fail=lambda m, _e: (self.progress.hide(), self._set_status(m, True)))

    def _show(self, data: dict) -> None:
        self.progress.hide()
        p = data["period"]
        self.state_badge.setText("Голосование идёт" if p["is_current"] else "Итоги зафиксированы")

        rows = []
        for r in data["ranking"]:
            row, lay = _row(52)
            pos = label(str(r["position"]))
            pos.setFixedWidth(24)
            pos.setAlignment(Qt.AlignCenter)
            pos.setStyleSheet(f"color: {theme.ACCENT if r['position'] <= 3 else theme.TEXT_2};"
                              "font-size: 13px; font-weight: 600;")
            cover = TrackCoverWidget(36, 6)
            cover.set_track(r["title"], r["artist"])
            votes = label(f"{r['votes']} {_votes_word(r['votes'])}", "secondary")
            lay.addWidget(pos)
            lay.addWidget(cover)
            lay.addLayout(_two_lines(r["title"], r["artist"]), 1)
            lay.addWidget(votes)
            rows.append(row)
        self.ranking.set_rows(rows)

        rows = []
        for e in data["events"]:
            row, lay = _row(48)
            av = AvatarWidget(28)
            av.set_name(e["user_name"])
            voted = e["action"] == "vote"
            action = "проголосовал(а) за" if voted else "отозвал(а) голос за"
            mark = label("▲" if voted else "↺")
            mark.setFixedWidth(14)
            mark.setStyleSheet(f"color: {theme.ACCENT if voted else theme.TEXT_3}; font-size: 11px;")
            text = ElidedLabel(f"{e['user_name']}  {action}  «{e['track_title']}»", 13, 400, theme.TEXT)
            when = label(fmt_time(e["created_at"]), "muted")
            lay.addWidget(av)
            lay.addWidget(mark)
            lay.addWidget(text, 1)
            lay.addWidget(when)
            rows.append(row)
        self.events.set_rows(rows)
        self.tabs.set_title(1, f"Журнал голосов  {len(data['events'])}")
        self._set_status("")


def _votes_word(n: int) -> str:
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11:
        return "голос"
    if 2 <= n10 <= 4 and not 12 <= n100 <= 14:
        return "голоса"
    return "голосов"


# ======================================================================= модерация
class ManageDialog(_StatusMixin, StyledDialog):
    def __init__(self, api: ApiClient, community: dict, me_id: int, parent=None):
        super().__init__("Модерация", community["name"], parent, width=620)
        self.api, self.community, self.me_id = api, community, me_id
        self.cid = community["id"]
        self.is_owner = community["my_role"] == "owner"
        self.changed = False
        self.resize(620, 580)

        self.tabs = PillTabs(["Приглашение", "Участники", "Скрытые треки"])
        self.pages = QStackedWidget()
        self.pages.addWidget(self._invite_page())
        self.members_list = RowList("Загрузка…")
        self.pages.addWidget(self.members_list)
        self.hidden_list = RowList("Скрытых композиций нет")
        self.pages.addWidget(self.hidden_list)
        self.tabs.changed.connect(self.pages.setCurrentIndex)

        self.body.addWidget(self.tabs)
        self.body.addWidget(self.pages, 1)
        self._init_status(self.body)
        close = button("Готово")
        close.clicked.connect(self.accept)
        self.footer.addStretch(1)
        self.footer.addWidget(close)
        self._reload()

    def _invite_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 12, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(label("КОД ПРИГЛАШЕНИЯ", "section"))
        lay.addSpacing(10)
        self.code_label = label(self.community["invite_code"])
        mono = ", ".join(f'"{f}"' for f in theme.MONO_FAMILIES)
        self.code_label.setStyleSheet(f"font-family: {mono}; font-size: 30px; font-weight: 600;"
                                      f"letter-spacing: 3px; color: {theme.TEXT};")
        self.code_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(self.code_label)
        lay.addSpacing(8)
        hint = label("Отправьте этот код участникам — они введут его в «Вступить по коду». "
                     "Если код попал не туда, сгенерируйте новый: старый сразу перестанет работать.",
                     "secondary")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        lay.addSpacing(18)
        row = QHBoxLayout()
        row.setSpacing(8)
        copy = button("Скопировать код")
        copy.clicked.connect(self._copy)
        regen = button("Сгенерировать новый", "danger")
        regen.clicked.connect(self._regenerate)
        row.addWidget(copy)
        row.addWidget(regen)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addStretch(1)
        return w

    def _reload(self) -> None:
        run_async(self.api.members, self.cid, on_ok=self._show_members,
                  on_fail=lambda m, _e: self._set_status(m, True))
        run_async(self.api.all_tracks, self.cid, on_ok=self._show_hidden,
                  on_fail=lambda m, _e: self._set_status(m, True))

    def _show_members(self, members: list[dict]) -> None:
        self._members = members
        rows = []
        for m in members:
            row, lay = _row(52)
            av = AvatarWidget(32)
            av.set_name(m["display_name"])
            lay.addWidget(av)
            lay.addLayout(_two_lines(m["display_name"], m["login"]), 1)
            role = label(ROLE_NAMES.get(m["role"], m["role"]), "badge")
            if m["role"] in ("owner", "moderator"):
                role.setStyleSheet(f"color: {theme.TEXT};")
            lay.addWidget(role, 0, Qt.AlignVCenter)
            if self.is_owner and m["role"] != "owner":
                act = button("Снять модератора" if m["role"] == "moderator" else "Сделать модератором", "small")
                act.setFixedWidth(160)
                act.clicked.connect(lambda _=False, mm=m: self._toggle_role(mm))
                lay.addWidget(act)
            rows.append(row)
        self.members_list.set_rows(rows)
        self.tabs.set_title(1, f"Участники  {len(members)}")

    def _show_hidden(self, tracks: list[dict]) -> None:
        self._hidden = [t for t in tracks if t["status"] == "hidden"]
        rows = []
        for t in self._hidden:
            row, lay = _row(56)
            cover = TrackCoverWidget(40, 6)
            cover.set_track(t["title"], t["artist"])
            lay.addWidget(cover)
            lay.addLayout(_two_lines(t["title"], t["artist"], theme.TEXT_2), 1)
            restore = button("Вернуть в плейлист", "small")
            restore.clicked.connect(lambda _=False, tr=t: self._restore(tr))
            lay.addWidget(restore)
            rows.append(row)
        self.hidden_list.set_rows(rows)
        self.tabs.set_title(2, f"Скрытые треки  {len(self._hidden)}" if self._hidden else "Скрытые треки")

    # ------------------------------------------------------------ действия
    def _copy(self) -> None:
        QApplication.clipboard().setText(self.code_label.text())
        self._set_status("Код скопирован в буфер обмена")

    def _regenerate(self) -> None:
        if not PromptDialog.confirm(self, "Сгенерировать новый код?",
                                    "Старый код перестанет действовать. Уже вступившие участники останутся.",
                                    "Сгенерировать", danger=True):
            return

        def ok(code):
            self.code_label.setText(code)
            self.changed = True
            self._set_status("Новый код создан. Старый больше не работает.")
        run_async(self.api.regenerate_invite, self.cid, on_ok=ok,
                  on_fail=lambda m, _e: self._set_status(m, True))

    def _toggle_role(self, m: dict) -> None:
        new_role = "member" if m["role"] == "moderator" else "moderator"

        def ok(_r):
            self._set_status(f"{m['display_name']}: теперь {ROLE_NAMES[new_role]}")
            self._reload()
        run_async(self.api.set_role, self.cid, m["id"], new_role, on_ok=ok,
                  on_fail=lambda msg, _e: self._set_status(msg, True))

    def _restore(self, track: dict) -> None:
        def ok(_t):
            self.changed = True
            self._set_status(f"«{track['title']}» снова в плейлисте")
            self._reload()
        run_async(self.api.moderate, track["id"], "active", on_ok=ok,
                  on_fail=lambda m, _e: self._set_status(m, True))
