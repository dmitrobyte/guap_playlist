"""Экраны 2 и 3: сайдбар с сообществами, сцена сообщества с плейлистом, док-плеер."""
from PySide6.QtCore import QSettings, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QListWidget, QListWidgetItem,
                               QMainWindow, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget)

from client import theme
from client.api import ApiClient
from client.dialogs import AddMusicDialog, HistoryDialog, ManageDialog
from client.player import PlayerWidget
from client.util import ROLE_NAMES, SOURCE_NAMES, fmt_week
from client.widgets import (AvatarWidget, ElidedLabel, HoverRow, IconButton, PlayingIndicator,
                            PromptDialog, RowList, Toast, TrackCoverWidget, VoteButton, button,
                            divider, label, restyle)
from client.workers import run_async

REFRESH_MS = 5000

# Ширины колонок — общие для шапки и строк, чтобы всё стояло ровно
COL_POS, COL_SOURCE, COL_VOTES = 36, 96, 72
COL_ACTIONS, COL_ACTIONS_MOD = 44, 120
ROW_MARGIN, ROW_SPACING = 12, 14


def _plural(n: int, one: str, few: str, many: str) -> str:
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11:
        return one
    if 2 <= n10 <= 4 and not 12 <= n100 <= 14:
        return few
    return many


# ================================================================== строка трека
class TrackRowWidget(HoverRow):
    """Плоская карточка трека высотой 56px."""
    vote_clicked = Signal(dict)
    play_clicked = Signal(dict)
    hide_clicked = Signal(dict)

    def __init__(self, track: dict, is_mod: bool, playing: bool, move: tuple[str, str] | None):
        super().__init__(56)
        self.track = track
        t = track
        lay = QHBoxLayout(self)
        lay.setContentsMargins(ROW_MARGIN, 0, ROW_MARGIN, 0)
        lay.setSpacing(ROW_SPACING)

        # № позиции (топ-3 изумрудом) и маленькая стрелка изменения места
        pos_box = QWidget()
        pos_box.setFixedWidth(COL_POS)
        pl = QVBoxLayout(pos_box)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(0)
        pl.addStretch(1)
        if playing:
            ind = PlayingIndicator()
            pl.addWidget(ind, 0, Qt.AlignHCenter)
        else:
            self.pos_label = label(str(t["position"]))
            self.pos_label.setAlignment(Qt.AlignCenter)
            color = theme.ACCENT if t["position"] <= 3 else theme.TEXT_2
            self.pos_label.setStyleSheet(f"color: {color}; font-size: 14px; font-weight: 600;")
            pl.addWidget(self.pos_label)
        self.move_label = label(move[0] if move else "")
        self.move_label.setAlignment(Qt.AlignCenter)
        self.move_label.setStyleSheet(f"color: {move[1] if move else theme.TEXT_3}; font-size: 10px;")
        self.move_label.setVisible(bool(move))
        pl.addWidget(self.move_label)
        pl.addStretch(1)
        lay.addWidget(pos_box)

        # обложка + название/исполнитель
        self.cover = TrackCoverWidget(40, 6)
        self.cover.set_track(t["title"], t["artist"])
        lay.addWidget(self.cover)
        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        text_col.addStretch(1)
        self.title_label = ElidedLabel(t["title"], 13.5, 600, theme.ACCENT if playing else theme.TEXT)
        self.artist_label = ElidedLabel(t["artist"], 12, 400, theme.TEXT_2)
        text_col.addWidget(self.title_label)
        text_col.addWidget(self.artist_label)
        text_col.addStretch(1)
        lay.addLayout(text_col, 1)
        self.setToolTip(f"Добавил(а): {t.get('added_by_name', '')}")

        src = label(SOURCE_NAMES.get(t["source_type"], t["source_type"]), "secondary")
        src.setFixedWidth(COL_SOURCE)
        lay.addWidget(src)

        self.vote_btn = VoteButton(t["votes"], t["my_vote"])
        self.vote_btn.clicked.connect(lambda: self.vote_clicked.emit(self.track))
        vote_box = QWidget()
        vote_box.setFixedWidth(COL_VOTES)
        vl = QHBoxLayout(vote_box)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.addWidget(self.vote_btn)
        vl.addStretch(1)
        lay.addWidget(vote_box)

        actions = QWidget()
        actions.setFixedWidth(COL_ACTIONS_MOD if is_mod else COL_ACTIONS)
        al = QHBoxLayout(actions)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(6)
        if t["playable"]:
            self.play_btn = IconButton("play", 32, "round", "Слушать в приложении")
        else:
            self.play_btn = IconButton("link", 32, "round", "Открыть ссылку в браузере")
        self.play_btn.clicked.connect(lambda: self.play_clicked.emit(self.track))
        al.addWidget(self.play_btn)
        self.hide_btn = None
        if is_mod:
            self.hide_btn = button("Скрыть", "smallDanger")
            self.hide_btn.setToolTip("Убрать из активного плейлиста (история сохранится)")
            self.hide_btn.clicked.connect(lambda: self.hide_clicked.emit(self.track))
            sp = self.hide_btn.sizePolicy()
            sp.setRetainSizeWhenHidden(True)
            self.hide_btn.setSizePolicy(sp)
            self.hide_btn.hide()  # появляется при наведении — меньше визуального шума
            al.addWidget(self.hide_btn)
        al.addStretch(1)
        lay.addWidget(actions)

    def on_hover(self, hovered: bool) -> None:
        if self.hide_btn:
            self.hide_btn.setVisible(hovered)

    def mouseDoubleClickEvent(self, _e):
        self.play_clicked.emit(self.track)


def _columns_header(is_mod: bool) -> QWidget:
    w = QWidget()
    w.setFixedHeight(32)
    lay = QHBoxLayout(w)
    lay.setContentsMargins(ROW_MARGIN, 0, ROW_MARGIN + 4, 0)
    lay.setSpacing(ROW_SPACING)

    def col(text, width=None, align=Qt.AlignLeft):
        lb = label(text, "section")
        lb.setAlignment(align | Qt.AlignVCenter)
        if width:
            lb.setFixedWidth(width)
        return lb

    lay.addWidget(col("#", COL_POS, Qt.AlignHCenter))
    lay.addWidget(col("КОМПОЗИЦИЯ"), 1)
    lay.addWidget(col("ИСТОЧНИК", COL_SOURCE))
    lay.addWidget(col("ГОЛОСА", COL_VOTES))
    lay.addWidget(col("ДЕЙСТВИЯ", COL_ACTIONS_MOD if is_mod else COL_ACTIONS))
    return w


# ================================================================== сцена сообщества
class CommunityView(QWidget):
    """Экран 3. Общий плейлист выбранного сообщества."""
    session_expired = Signal()
    role_changed = Signal(str)
    community_loaded = Signal(dict)
    notify = Signal(str, str)  # текст, вид (info/success/error)

    def __init__(self, api: ApiClient, player: PlayerWidget, me: dict):
        super().__init__()
        self.api, self.player, self.me = api, player, me
        self.cid: int | None = None
        self.data: dict | None = None
        self._signature = None
        self._prev_positions: dict[int, int] = {}
        self._moves: dict[int, tuple[str, str]] = {}
        self._loading = False
        self._playing_id: int | None = None
        self._offline = False
        self.player.next_provider = lambda: (self.data or {}).get("tracks", [])
        self.player.track_started.connect(self._on_track_started)

        # --- шапка
        self.name_label = label("", "h1")
        self.code_badge = button("Код: —", "badge")
        self.code_badge.setToolTip("Нажмите, чтобы скопировать код приглашения")
        self.code_badge.clicked.connect(self._copy_code)
        self.week_badge = label("", "badge")
        self.meta_label = label("", "secondary")

        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        title_row.addWidget(self.name_label)
        title_row.addSpacing(4)
        title_row.addWidget(self.code_badge, 0, Qt.AlignVCenter)
        title_row.addWidget(self.week_badge, 0, Qt.AlignVCenter)
        title_row.addStretch(1)
        head_left = QVBoxLayout()
        head_left.setSpacing(6)
        head_left.addLayout(title_row)
        head_left.addWidget(self.meta_label)

        self.add_btn = button("+  Добавить музыку", "primary")
        self.history_btn = button("История и ротация")
        self.manage_btn = button("Модерация")
        self.add_btn.clicked.connect(self._add_music)
        self.history_btn.clicked.connect(self._history)
        self.manage_btn.clicked.connect(self._manage)
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addLayout(head_left, 1)
        head.addWidget(self.manage_btn, 0, Qt.AlignTop)
        head.addWidget(self.history_btn, 0, Qt.AlignTop)
        head.addWidget(self.add_btn, 0, Qt.AlignTop)

        # --- список
        self.header_host = QVBoxLayout()
        self.header_host.setContentsMargins(0, 0, 0, 0)
        self.columns = _columns_header(False)
        self.header_host.addWidget(self.columns)
        self.list = RowList()

        self.empty = QWidget()
        el = QVBoxLayout(self.empty)
        el.addStretch(1)
        e1 = label("Плейлист пока пуст", "h2")
        e1.setAlignment(Qt.AlignCenter)
        e2 = label("Добавьте трек из библиотеки, загрузите файл или вставьте ссылку.\n"
                   "Участники проголосуют — и порядок выстроится сам.", "secondary")
        e2.setAlignment(Qt.AlignCenter)
        e_btn = button("+  Добавить музыку", "primary")
        e_btn.clicked.connect(self._add_music)
        el.addWidget(e1)
        el.addSpacing(6)
        el.addWidget(e2)
        el.addSpacing(18)
        el.addWidget(e_btn, 0, Qt.AlignHCenter)
        el.addStretch(2)

        self.body = QStackedWidget()
        list_page = QWidget()
        lp = QVBoxLayout(list_page)
        lp.setContentsMargins(0, 0, 0, 0)
        lp.setSpacing(4)
        lp.addLayout(self.header_host)
        lp.addWidget(divider())
        lp.addSpacing(4)
        lp.addWidget(self.list, 1)
        self.body.addWidget(list_page)
        self.body.addWidget(self.empty)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 28, 28, 0)
        lay.setSpacing(0)
        lay.addLayout(head)
        lay.addSpacing(24)
        lay.addWidget(self.body, 1)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(REFRESH_MS)

    # ------------------------------------------------------------ загрузка данных
    def open_community(self, community_id: int) -> None:
        self.cid = community_id
        self.data = None
        self._signature = None
        self._prev_positions = {}
        self._moves = {}
        self.list.set_rows([])
        self.name_label.setText("Загрузка…")
        self.code_badge.hide()
        self.week_badge.hide()
        self.meta_label.setText("")
        self.refresh()

    def refresh(self) -> None:
        if self.cid is None or self._loading:
            return
        self._loading = True
        cid = self.cid
        run_async(self.api.playlist, cid,
                  on_ok=lambda d: self._loaded(cid, d), on_fail=self._failed)

    def _failed(self, message: str, exc) -> None:
        self._loading = False
        if getattr(exc, "status", None) == 401:
            self.session_expired.emit()
            return
        if getattr(exc, "status", None) is None:  # нет связи — тихо показываем в шапке
            self._offline = True
            self.meta_label.setProperty("textRole", "error")
            restyle(self.meta_label)
            self.meta_label.setText("Нет связи с сервером — повторим через 5 секунд")
        else:
            self.notify.emit(message, "error")

    def _loaded(self, cid: int, data: dict) -> None:
        self._loading = False
        if cid != self.cid:
            return  # пока грузили, пользователь переключил сообщество
        self.data = data
        c, p = data["community"], data["period"]
        self.name_label.setText(c["name"])
        self.code_badge.setText(f"Код: {c['invite_code']}")
        self.code_badge.show()
        self.week_badge.setText(f"Неделя {fmt_week(p)}")
        self.week_badge.show()
        n = c["member_count"]
        self.meta_label.setProperty("textRole", "secondary")
        restyle(self.meta_label)
        tracks_n = len(data["tracks"])
        self.meta_label.setText(
            f"{n} {_plural(n, 'участник', 'участника', 'участников')}  ·  "
            f"{tracks_n} {_plural(tracks_n, 'композиция', 'композиции', 'композиций')}  ·  "
            f"вы — {ROLE_NAMES.get(c['my_role'])}")
        is_mod = c["my_role"] in ("owner", "moderator")
        self.manage_btn.setVisible(is_mod)
        self.role_changed.emit(c["my_role"])
        self.community_loaded.emit(c)

        signature = (c["my_role"], p["id"], self._playing_id,
                     tuple((t["id"], t["position"], t["votes"], t["my_vote"], t["title"])
                           for t in data["tracks"]))
        if signature != self._signature:  # перерисовываем только при изменениях — без мерцания
            self._signature = signature
            self._render()

    # ------------------------------------------------------------ отрисовка
    def _render(self) -> None:
        tracks = self.data["tracks"]
        is_mod = self.data["community"]["my_role"] in ("owner", "moderator")

        # колонка действий шире, если есть права модератора
        old = self.columns
        self.columns = _columns_header(is_mod)
        self.header_host.replaceWidget(old, self.columns)
        old.deleteLater()

        # Стрелки движения пересчитываем только когда реально поменялись места
        new_positions = {t["id"]: t["position"] for t in tracks}
        if new_positions != self._prev_positions:
            moves = {}
            for t in tracks:
                prev = self._prev_positions.get(t["id"])
                if prev is None and self._prev_positions:
                    moves[t["id"]] = ("новая", theme.ACCENT)
                elif prev is not None and t["position"] < prev:
                    moves[t["id"]] = (f"▲ {prev - t['position']}", theme.ACCENT)
                elif prev is not None and t["position"] > prev:
                    moves[t["id"]] = (f"▼ {t['position'] - prev}", theme.DANGER)
            self._moves = moves
            self._prev_positions = new_positions

        rows = []
        for t in tracks:
            row = TrackRowWidget(t, is_mod, t["id"] == self._playing_id, self._moves.get(t["id"]))
            row.vote_clicked.connect(lambda tr, r=row: self._toggle_vote(tr, r.vote_btn))
            row.play_clicked.connect(self._play)
            row.hide_clicked.connect(self._hide)
            rows.append(row)
        self.list.set_rows(rows)
        self.body.setCurrentIndex(0 if tracks else 1)

    # ------------------------------------------------------------ действия
    def _copy_code(self) -> None:
        if self.data:
            QApplication.clipboard().setText(self.data["community"]["invite_code"])
            self.notify.emit("Код приглашения скопирован в буфер обмена", "success")

    def _toggle_vote(self, track: dict, vote_btn: VoteButton) -> None:
        vote_btn.set_busy()
        fn = self.api.unvote if track["my_vote"] else self.api.vote

        def ok(res):
            vote_btn.set_state(res["votes"], res["my_vote"])  # мгновенный отклик
            self.refresh()

        def fail(message, exc):
            vote_btn.set_state(track["votes"], track["my_vote"])
            self._failed(message, exc)
            self._signature = None
            self.refresh()

        run_async(fn, track["id"], on_ok=ok, on_fail=fail)

    def _play(self, track: dict) -> None:
        if track["playable"]:
            self.player.play_track(track)
        else:
            url = QUrl(track.get("source_url") or "")
            # открываем только http/https — никаких локальных путей и команд
            if url.scheme().lower() in ("http", "https") and url.host():
                QDesktopServices.openUrl(url)
                self.notify.emit("Ссылка открыта в браузере", "info")
            else:
                self.notify.emit("Некорректная ссылка у этой композиции", "error")

    def _on_track_started(self, track_id: int) -> None:
        self._playing_id = track_id
        self._signature = None
        if self.data:
            self._render()

    def _hide(self, track: dict) -> None:
        if not PromptDialog.confirm(self, "Скрыть композицию?",
                                    f"«{track['title']}» исчезнет из активного плейлиста у всех участников. "
                                    "История голосов сохранится, вернуть трек можно в разделе «Модерация».",
                                    "Скрыть", danger=True):
            return

        def ok(_r):
            self.notify.emit(f"«{track['title']}» скрыта", "info")
            self.refresh()

        run_async(self.api.moderate, track["id"], "hidden", on_ok=ok,
                  on_fail=lambda m, _e: self.notify.emit(m, "error"))

    def _add_music(self) -> None:
        dlg = AddMusicDialog(self.api, self.cid, self)
        if dlg.exec():
            if dlg.result_message:
                self.notify.emit(dlg.result_message, "success")
            self.refresh()

    def _history(self) -> None:
        HistoryDialog(self.api, self.cid, self).exec()

    def _manage(self) -> None:
        dlg = ManageDialog(self.api, self.data["community"], self.me["id"], self)
        dlg.exec()
        self._signature = None
        self.refresh()


# ================================================================== сайдбар
class CommunityItem(QWidget):
    def __init__(self, community: dict):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 10, 0)
        lay.setSpacing(10)
        mark = TrackCoverWidget(24, 6)
        mark.set_track(community["name"], community["name"])
        lay.addWidget(mark)
        self.name = ElidedLabel(community["name"], 13, 500, theme.TEXT)
        lay.addWidget(self.name, 1)
        self.count = label(str(community["member_count"]), "muted")
        self.count.setToolTip("Участников")
        lay.addWidget(self.count)


class Sidebar(QWidget):
    def __init__(self, me: dict):
        super().__init__()
        self.setObjectName("Sidebar")
        self.setAttribute(Qt.WA_StyledBackground)
        self.setFixedWidth(250)
        self.me = me

        avatar = AvatarWidget(34)
        avatar.set_name(me["display_name"])
        self.name_label = ElidedLabel(me["display_name"], 13.5, 600, theme.TEXT)
        self.sub_label = ElidedLabel(me["login"], 12, 400, theme.TEXT_2)
        tc = QVBoxLayout()
        tc.setSpacing(1)
        tc.addWidget(self.name_label)
        tc.addWidget(self.sub_label)
        profile = QHBoxLayout()
        profile.setContentsMargins(4, 0, 0, 0)
        profile.setSpacing(10)
        profile.addWidget(avatar)
        profile.addLayout(tc, 1)

        self.list = QListWidget()
        self.list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.list.setCursor(Qt.PointingHandCursor)

        self.create_btn = button("+  Создать сообщество")
        self.join_btn = button("Вступить по коду")
        self.logout_btn = button("Выйти из аккаунта", "dangerGhost")
        self.logout_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.logout_btn.setStyleSheet("text-align: left; padding-left: 10px;")

        self.empty_hint = label("Пока ни одного сообщества.\nСоздайте своё или вступите по коду.", "muted")
        self.empty_hint.setWordWrap(True)
        self.empty_hint.setContentsMargins(4, 6, 0, 0)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 20, 12, 14)
        lay.setSpacing(0)
        lay.addLayout(profile)
        lay.addSpacing(18)
        lay.addWidget(divider())
        lay.addSpacing(18)
        sec = label("МОИ СООБЩЕСТВА", "section")
        sec.setContentsMargins(4, 0, 0, 0)
        lay.addWidget(sec)
        lay.addSpacing(8)
        lay.addWidget(self.empty_hint)
        lay.addWidget(self.list, 1)
        lay.addSpacing(12)
        lay.addWidget(self.create_btn)
        lay.addSpacing(6)
        lay.addWidget(self.join_btn)
        lay.addSpacing(10)
        lay.addWidget(divider())
        lay.addSpacing(6)
        lay.addWidget(self.logout_btn)

    def set_role(self, role: str | None) -> None:
        self.sub_label.setText(f"{self.me['login']}  ·  {ROLE_NAMES.get(role)}" if role else self.me["login"])

    def set_communities(self, items: list[dict], select_id: int | None) -> QListWidgetItem | None:
        self.list.blockSignals(True)
        self.list.clear()
        target = None
        for c in items:
            it = QListWidgetItem()
            it.setData(Qt.UserRole, c["id"])
            it.setSizeHint(QSize(0, 38))
            self.list.addItem(it)
            self.list.setItemWidget(it, CommunityItem(c))
            if c["id"] == select_id:
                target = it
        self.list.blockSignals(False)
        self.empty_hint.setVisible(not items)
        return target

    def update_community(self, c: dict) -> None:
        """Свежие данные сообщества (например, число участников) без перезагрузки списка."""
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(Qt.UserRole) == c["id"]:
                w = self.list.itemWidget(it)
                if w:
                    w.count.setText(str(c["member_count"]))
                    w.name.setText(c["name"])


# ================================================================== главное окно
class MainWindow(QMainWindow):
    """Сайдбар (экран 2) + сцена сообщества (экран 3) + док-плеер."""
    logged_out = Signal()

    def __init__(self, api: ApiClient, settings: QSettings, me: dict):
        super().__init__()
        self.api, self.settings, self.me = api, settings, me
        self.setWindowTitle("Совместный плейлист")
        self.resize(1280, 800)
        self.setMinimumSize(1060, 640)

        self.player = PlayerWidget(api)
        self.view = CommunityView(api, self.player, me)
        self.view.session_expired.connect(self._session_expired)
        self.sidebar = Sidebar(me)
        self.view.role_changed.connect(self.sidebar.set_role)
        self.view.community_loaded.connect(self.sidebar.update_community)
        self.list = self.sidebar.list
        self.list.currentItemChanged.connect(self._selected)
        self.sidebar.create_btn.clicked.connect(self._create)
        self.sidebar.join_btn.clicked.connect(self._join)
        self.sidebar.logout_btn.clicked.connect(self._logout)

        placeholder = QWidget()
        pl = QVBoxLayout(placeholder)
        pl.addStretch(1)
        p1 = label("Выберите сообщество", "h2")
        p1.setAlignment(Qt.AlignCenter)
        p2 = label("Или создайте новое — код приглашения появится сразу.", "secondary")
        p2.setAlignment(Qt.AlignCenter)
        p_btn = button("+  Создать сообщество", "primary")
        p_btn.clicked.connect(self._create)
        pl.addWidget(p1)
        pl.addSpacing(6)
        pl.addWidget(p2)
        pl.addSpacing(18)
        pl.addWidget(p_btn, 0, Qt.AlignHCenter)
        pl.addStretch(2)

        self.stack = QStackedWidget()
        self.stack.addWidget(placeholder)
        self.stack.addWidget(self.view)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(0)
        top.addWidget(self.sidebar)
        top.addWidget(self.stack, 1)

        root = QWidget()
        root.setObjectName("AppRoot")
        rl = QVBoxLayout(root)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        rl.addLayout(top, 1)
        rl.addWidget(self.player)
        self.setCentralWidget(root)

        self.toast = Toast(root)
        self.view.notify.connect(self.notify)

        self.load_communities(select_id=self.settings.value("last_community", None, type=int))

    def notify(self, text: str, kind: str = "info") -> None:
        self.toast.show_message(text, kind)

    # ------------------------------------------------------------ сообщества
    def load_communities(self, select_id: int | None = None) -> None:
        def ok(items):
            target = self.sidebar.set_communities(items, select_id)
            if target:
                self.list.setCurrentItem(target)

        def fail(message, exc):
            if getattr(exc, "status", None) == 401:
                self._session_expired()
            else:
                self.notify(message, "error")

        run_async(self.api.communities, on_ok=ok, on_fail=fail)

    def _selected(self, item, _prev=None) -> None:
        if not item:
            self.stack.setCurrentIndex(0)
            self.sidebar.set_role(None)
            return
        cid = item.data(Qt.UserRole)
        self.settings.setValue("last_community", cid)
        self.stack.setCurrentIndex(1)
        self.view.open_community(cid)

    def _create(self) -> None:
        name = PromptDialog.ask_text(self, "Новое сообщество",
                                     "Например, «Группа ИВТ-21» или «Физфак». "
                                     "Вы станете владельцем и получите код приглашения.",
                                     "Название сообщества", "Создать")
        if not name:
            return

        def done(c):
            QApplication.clipboard().setText(c["invite_code"])
            self.notify(f"Сообщество создано. Код {c['invite_code']} скопирован", "success")
            self.load_communities(select_id=c["id"])

        run_async(self.api.create_community, name, on_ok=done,
                  on_fail=lambda m, _e: self.notify(m, "error"))

    def _join(self) -> None:
        code = PromptDialog.ask_text(self, "Вступить в сообщество",
                                     "Введите код приглашения, который прислал владелец или модератор.",
                                     "Например, X9CMPZK6", "Вступить")
        if not code:
            return

        def done(res):
            c = res["community"]
            self.notify(f"Вы уже состоите в «{c['name']}»" if res["already_member"]
                        else f"Добро пожаловать в «{c['name']}»", "info" if res["already_member"] else "success")
            self.load_communities(select_id=c["id"])

        run_async(self.api.join_community, code, on_ok=done,
                  on_fail=lambda m, _e: self.notify(m, "error"))

    # ------------------------------------------------------------ выход
    def _logout(self) -> None:
        run_async(self.api.logout)
        self._finish_logout()

    def _session_expired(self) -> None:
        if not self.isVisible():
            return
        self._finish_logout()

    def _finish_logout(self) -> None:
        self.view.timer.stop()
        self.player.player.stop()
        self.settings.remove("token")
        self.close()
        self.logged_out.emit()
