"""Экран 1. Вход и регистрация — карточка по центру тёмного окна."""
from PySide6.QtCore import QRectF, QSettings, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

from client import theme
from client.api import ApiClient
from client.widgets import PillTabs, button, label
from client.workers import run_async


class BrandMark(QWidget):
    """Небольшой знак продукта: три вертикальные полосы разной высоты — «рейтинг»."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(36, 36)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.SURFACE_ACTIVE))
        p.drawRoundedRect(QRectF(self.rect()), 9, 9)
        for i, (h, c) in enumerate([(10, theme.TEXT_3), (18, theme.ACCENT), (14, theme.TEXT_2)]):
            p.setBrush(QColor(c))
            p.drawRoundedRect(QRectF(10 + i * 6, 27 - h, 4, h), 1.5, 1.5)


class LoginWindow(QWidget):
    logged_in = Signal(dict)  # данные пользователя

    def __init__(self, api: ApiClient, settings: QSettings):
        super().__init__()
        self.api, self.settings = api, settings
        self.mode = "login"
        self.setObjectName("AppRoot")
        self.setAttribute(Qt.WA_StyledBackground)
        self.setWindowTitle("Совместный плейлист")
        self.resize(980, 680)
        self.setMinimumSize(520, 620)

        card = QWidget()
        card.setObjectName("Card")
        card.setAttribute(Qt.WA_StyledBackground)
        card.setFixedWidth(380)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(32, 32, 32, 28)
        lay.setSpacing(0)

        lay.addWidget(BrandMark())
        lay.addSpacing(20)
        lay.addWidget(label("Совместный плейлист", "h1"))
        lay.addSpacing(6)
        sub = label("Музыка вашей группы, которую выбирают все. "
                    "Порядок воспроизведения решает голосование.", "secondary")
        sub.setWordWrap(True)
        lay.addWidget(sub)
        lay.addSpacing(24)

        self.tabs = PillTabs(["Вход", "Регистрация"])
        self.tabs.changed.connect(self._switch_mode)
        lay.addWidget(self.tabs)
        lay.addSpacing(20)

        self.login_edit = QLineEdit(settings.value("login", ""))
        self.login_edit.setPlaceholderText("например, anna")
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Как вас увидят участники")
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setPlaceholderText("Не короче 6 символов")
        self.password_edit.returnPressed.connect(self._submit)
        self.login_edit.returnPressed.connect(lambda: self.password_edit.setFocus())

        self._field(lay, "Логин", self.login_edit)
        self.name_block = self._field(lay, "Отображаемое имя", self.name_edit)
        self._field(lay, "Пароль", self.password_edit)
        lay.addSpacing(8)

        self.submit_btn = button("Войти", "primary")
        self.submit_btn.setMinimumHeight(40)
        self.submit_btn.clicked.connect(self._submit)
        lay.addWidget(self.submit_btn)

        self.status = label("", "secondary")
        self.status.setWordWrap(True)
        self.status.setMinimumHeight(18)
        lay.addSpacing(12)
        lay.addWidget(self.status)
        lay.addSpacing(8)

        # --- адрес сервера: спрятан, чтобы не отвлекать, но всегда доступен
        self.server_edit = QLineEdit(settings.value("server_url", "http://127.0.0.1:8000"))
        self.server_edit.setPlaceholderText("http://192.168.1.10:8000")
        self.server_edit.textChanged.connect(self._update_server_caption)
        self.server_block = self._field(lay, "Адрес сервера", self.server_edit, spacing_after=0)
        self.server_block.hide()
        server_row = QHBoxLayout()
        self.server_caption = label("", "muted")
        self.server_toggle = button("Изменить", "link")
        self.server_toggle.clicked.connect(self._toggle_server)
        server_row.addWidget(self.server_caption, 1)
        server_row.addWidget(self.server_toggle)
        lay.addSpacing(6)
        lay.addLayout(server_row)
        self._update_server_caption()

        root = QVBoxLayout(self)
        root.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(card)
        row.addStretch(1)
        root.addLayout(row)
        root.addStretch(1)

        self._switch_mode(0)
        # совместимость: старые кнопки по-прежнему доступны как атрибуты
        self.login_btn = self.register_btn = self.submit_btn

    # ------------------------------------------------------------ вёрстка
    def _field(self, lay: QVBoxLayout, caption: str, edit: QLineEdit, spacing_after: int = 14) -> QWidget:
        block = QWidget()
        bl = QVBoxLayout(block)
        bl.setContentsMargins(0, 0, 0, spacing_after)
        bl.setSpacing(6)
        bl.addWidget(label(caption, "field"))
        bl.addWidget(edit)
        lay.addWidget(block)
        return block

    def _switch_mode(self, index: int) -> None:
        self.mode = "register" if index == 1 else "login"
        self.name_block.setVisible(self.mode == "register")
        self.submit_btn.setText("Создать аккаунт" if self.mode == "register" else "Войти")
        self.password_edit.setPlaceholderText("Не короче 6 символов" if self.mode == "register" else "")
        self._show("", error=False)

    def _toggle_server(self) -> None:
        show = not self.server_block.isVisible()
        self.server_block.setVisible(show)
        self.server_toggle.setText("Скрыть" if show else "Изменить")
        if show:
            self.server_edit.setFocus()

    def _update_server_caption(self) -> None:
        self.server_caption.setText(f"Сервер: {self.server_edit.text().strip() or 'не указан'}")

    # ------------------------------------------------------------ состояние
    def _busy(self, busy: bool, text: str = "") -> None:
        self.submit_btn.setEnabled(not busy)
        self.tabs.setEnabled(not busy)
        self._show(text, error=False)

    def _show(self, text: str, error: bool) -> None:
        self.status.setProperty("textRole", "error" if error else "secondary")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self.status.setText(text)

    def _fail(self, message: str, _exc=None) -> None:
        self._busy(False)
        self._show(message, error=True)

    def _ok(self, data: dict) -> None:
        self._busy(False)
        self.settings.setValue("server_url", self.api.base_url)
        self.settings.setValue("login", data["user"]["login"])
        self.settings.setValue("token", self.api.token)  # чтобы после перезапуска не входить заново
        self.password_edit.clear()
        self.logged_in.emit(data["user"])

    def _prepare(self) -> bool:
        if not self.server_edit.text().strip():
            self.server_block.show()
            self._show("Укажите адрес сервера", error=True)
            return False
        if not self.login_edit.text().strip() or not self.password_edit.text():
            self._show("Введите логин и пароль", error=True)
            return False
        self.api.set_base_url(self.server_edit.text())
        return True

    # ------------------------------------------------------------ действия
    def _submit(self) -> None:
        self.do_register() if self.mode == "register" else self.do_login()

    def do_login(self) -> None:
        if not self._prepare():
            return
        self._busy(True, "Выполняется вход…")
        run_async(self.api.login, self.login_edit.text().strip(), self.password_edit.text(),
                  on_ok=self._ok, on_fail=self._fail)

    def do_register(self) -> None:
        if not self._prepare():
            return
        if not self.name_edit.text().strip():
            if self.mode != "register":
                self.tabs.set_current(1)
            self._show("Для регистрации укажите отображаемое имя", error=True)
            return
        if len(self.password_edit.text()) < 6:
            self._show("Пароль должен быть не короче 6 символов", error=True)
            return
        self._busy(True, "Создаём аккаунт…")
        run_async(self.api.register, self.login_edit.text().strip(), self.name_edit.text().strip(),
                  self.password_edit.text(), on_ok=self._ok, on_fail=self._fail)

    def try_saved_session(self) -> None:
        """Если сохранён токен — проверяем его и входим без пароля."""
        token = self.settings.value("token", "")
        if not token:
            return
        self.api.set_base_url(self.server_edit.text())
        self.api.token = token
        self._busy(True, "Восстанавливаем прошлый вход…")

        def ok(user):
            self._busy(False)
            self.logged_in.emit(user)

        def fail(message, exc):
            self.api.token = None
            if getattr(exc, "status", None) == 401:
                self.settings.remove("token")
                self._fail("Прошлая сессия истекла — войдите снова.")
            else:
                self._fail(message)

        run_async(self.api.me, on_ok=ok, on_fail=fail)
