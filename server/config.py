"""Настройки сервера. Всё можно поменять переменными окружения (см. README)."""
import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent

# Папка с базой данных и загруженными файлами
DATA_DIR = Path(os.environ.get("PLAYLIST_DATA_DIR", str(BASE_DIR / "data")))
# Подготовленный каталог композиций (catalog.json + audio/)
CATALOG_DIR = BASE_DIR / "catalog"

# Часовой пояс для границ недели (FR-11)
TIMEZONE = ZoneInfo(os.environ.get("PLAYLIST_TZ", "Europe/Moscow"))

# Лимит размера загружаемого файла (FR-04, способ B)
MAX_UPLOAD_BYTES = int(float(os.environ.get("PLAYLIST_MAX_UPLOAD_MB", "20")) * 1024 * 1024)

# Срок жизни токена входа (часы)
TOKEN_TTL_HOURS = int(os.environ.get("PLAYLIST_TOKEN_TTL_HOURS", "168"))

# Отладочный режим: разрешает менять "текущее время" сервера для проверки ротации
DEBUG = os.environ.get("PLAYLIST_DEBUG", "0") == "1"

_fake_now: datetime | None = None
if os.environ.get("PLAYLIST_FAKE_NOW"):
    _dt = datetime.fromisoformat(os.environ["PLAYLIST_FAKE_NOW"])
    if _dt.tzinfo is None:
        _dt = _dt.replace(tzinfo=TIMEZONE)
    _fake_now = _dt.astimezone(timezone.utc)


def now() -> datetime:
    """Текущее время для логики периодов (можно подменить для теста ротации)."""
    return _fake_now or datetime.now(timezone.utc)


def real_now() -> datetime:
    """Настоящее время (для сроков действия токенов)."""
    return datetime.now(timezone.utc)


def set_fake_now(dt: datetime | None) -> None:
    global _fake_now
    if dt is not None and dt.tzinfo is None:
        dt = dt.replace(tzinfo=TIMEZONE)
    _fake_now = dt.astimezone(timezone.utc) if dt else None


def iso(dt: datetime) -> str:
    """Единый формат времени в базе: UTC, сортируется как строка."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
