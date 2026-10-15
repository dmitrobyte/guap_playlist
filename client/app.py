"""Точка входа десктопного клиента."""
import sys

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from client import theme
from client.api import ApiClient
from client.login import LoginWindow
from client.main_window import MainWindow


class App:
    def __init__(self):
        self.qt = QApplication(sys.argv)
        self.qt.setApplicationName("SharedPlaylist")
        self.qt.setOrganizationName("SharedPlaylist")
        theme.apply(self.qt)
        self.settings = QSettings("SharedPlaylist", "Client")
        self.api = ApiClient(self.settings.value("server_url", "http://127.0.0.1:8000"))
        self.main: MainWindow | None = None

        self.login = LoginWindow(self.api, self.settings)
        self.login.logged_in.connect(self.show_main)
        self.login.show()
        self.login.try_saved_session()

    def show_main(self, user: dict) -> None:
        self.login.hide()
        self.main = MainWindow(self.api, self.settings, user)
        self.main.logged_out.connect(self.show_login)
        self.main.show()

    def show_login(self) -> None:
        self.api.token = None
        if self.main:
            self.main.deleteLater()
            self.main = None
        self.login.show()

    def run(self) -> int:
        return self.qt.exec()


def main() -> None:
    sys.exit(App().run())


if __name__ == "__main__":
    main()
