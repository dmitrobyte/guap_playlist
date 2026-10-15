from datetime import date, datetime

from PySide6.QtWidgets import QMessageBox, QWidget


def fmt_time(iso: str) -> str:
    """UTC-время сервера → местное время компьютера."""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()
        return dt.strftime("%d.%m.%Y %H:%M:%S")
    except (ValueError, AttributeError):
        return iso or ""


def fmt_week(period: dict) -> str:
    s = date.fromisoformat(period["week_start"]).strftime("%d.%m")
    e = date.fromisoformat(period["week_end"]).strftime("%d.%m.%Y")
    return f"{s} – {e}"


def fmt_ms(ms: int) -> str:
    s = max(0, ms // 1000)
    return f"{s // 60}:{s % 60:02d}"


def error_box(parent: QWidget, message: str, title: str = "Ошибка") -> None:
    QMessageBox.warning(parent, title, message)


def info_box(parent: QWidget, message: str, title: str = "Готово") -> None:
    QMessageBox.information(parent, title, message)


ROLE_NAMES = {"owner": "владелец", "moderator": "модератор", "member": "участник"}
SOURCE_NAMES = {"catalog": "Библиотека", "upload": "Файл", "link": "Ссылка"}
