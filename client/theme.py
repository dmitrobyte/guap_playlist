"""Дизайн-система клиента: палитра Zinc / Obsidian, типографика, глобальный QSS.

Все цвета интерфейса берутся только отсюда — так их легко поменять в одном месте."""
import sys
import zlib

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication, QWidget

# ------------------------------------------------------------------ палитра
BG = "#09090B"             # фон окна — глубокий оникс
PANEL = "#121215"          # сайдбар, плеер, модальные окна
BORDER = "#222226"         # тончайшие разделители
SURFACE_HOVER = "#18181C"  # наведение на элементы
SURFACE_ACTIVE = "#1F1F24" # выбранный элемент
ROW_HOVER = "#1F1F23"      # наведение на строку трека
INPUT = "#18181C"

TEXT = "#F4F4F5"           # основной текст
TEXT_2 = "#A1A1AA"         # вторичный (исполнитель, время)
TEXT_3 = "#71717A"         # приглушённый (подсказки)

ACCENT = "#10B981"         # изумруд — только главное действие, прогресс, свой голос
ACCENT_HOVER = "#059669"
ON_ACCENT = "#03140D"      # тёмный текст на изумрудном фоне — читаемее белого

BTN = "#27272A"
BTN_BORDER = "#3F3F46"
BTN_HOVER = "#323236"
DANGER = "#F87171"

# Благородные приглушённые тона для обложек и аватаров
COVER_PALETTE = [
    "#2E2B6E",  # глубокий индиго
    "#0E4636",  # тёмный изумруд
    "#4A1E2A",  # графитовый бордо
    "#2B3D56",  # сланцевый синий
    "#3A2A4D",  # приглушённый слива
    "#3B3426",  # тёмная бронза
]

FONT_FAMILIES = ["Segoe UI", "Inter", "Helvetica Neue", "Arial"]
MONO_FAMILIES = ["Cascadia Mono", "Consolas", "JetBrains Mono", "DejaVu Sans Mono"]


def tone_for(text: str) -> QColor:
    """Детерминированный цвет по строке (одинаковый на всех компьютерах)."""
    idx = zlib.crc32((text or "").strip().lower().encode("utf-8")) % len(COVER_PALETTE)
    return QColor(COVER_PALETTE[idx])


def initials(text: str, max_letters: int = 2) -> str:
    words = [w for w in "".join(ch if ch.isalnum() else " " for ch in (text or "")).split() if w]
    if not words:
        return "?"
    letters = "".join(w[0] for w in words[:max_letters])
    return letters.upper()


def font(size_px: float, weight: int = QFont.Normal, mono: bool = False) -> QFont:
    f = QFont()
    f.setFamilies(MONO_FAMILIES if mono else FONT_FAMILIES)
    f.setPixelSize(round(size_px))
    f.setWeight(QFont.Weight(weight))
    f.setHintingPreference(QFont.PreferNoHinting)
    return f


# ------------------------------------------------------------------ глобальный стиль
_FF = ", ".join(f'"{f}"' for f in FONT_FAMILIES)

QSS = f"""
* {{ outline: none; }}
QWidget {{
    color: {TEXT};
    font-family: {_FF};
    font-size: 13px;
    selection-background-color: {ACCENT};
    selection-color: {ON_ACCENT};
}}
QMainWindow, QWidget#AppRoot {{ background: {BG}; }}
QDialog {{ background: {PANEL}; }}
QWidget#Sidebar {{ background: {PANEL}; border-right: 1px solid {BORDER}; }}
QWidget#PlayerDock {{ background: {PANEL}; border-top: 1px solid {BORDER}; }}
QWidget#Card {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 12px; }}
QFrame#Divider {{ background: {BORDER}; border: none; max-height: 1px; min-height: 1px; }}

QLabel {{ background: transparent; }}
QLabel[textRole="h1"] {{ font-size: 22px; font-weight: 700; }}
QLabel[textRole="h2"] {{ font-size: 16px; font-weight: 600; }}
QLabel[textRole="strong"] {{ font-size: 13px; font-weight: 600; }}
QLabel[textRole="secondary"] {{ color: {TEXT_2}; font-size: 12px; }}
QLabel[textRole="muted"] {{ color: {TEXT_3}; font-size: 11px; }}
QLabel[textRole="section"] {{ color: {TEXT_3}; font-size: 11px; font-weight: 600; letter-spacing: 1px; }}
QLabel[textRole="field"] {{ color: {TEXT_2}; font-size: 12px; font-weight: 500; }}
QLabel[textRole="error"] {{ color: {DANGER}; font-size: 12px; }}
QLabel[textRole="badge"] {{
    color: {TEXT_2}; font-size: 12px; background: {SURFACE_HOVER};
    border: 1px solid {BORDER}; border-radius: 6px; padding: 3px 9px;
}}

/* ---------- кнопки ---------- */
QPushButton {{
    background: {BTN}; color: {TEXT}; border: 1px solid {BTN_BORDER};
    border-radius: 8px; padding: 0 14px; min-height: 32px; font-weight: 500;
}}
QPushButton:hover {{ background: {BTN_HOVER}; }}
QPushButton:pressed {{ background: {BTN}; }}
QPushButton:disabled {{ color: {TEXT_3}; background: {SURFACE_HOVER}; border-color: {BORDER}; }}

QPushButton[variant="primary"] {{
    background: {ACCENT}; color: {ON_ACCENT}; border: 1px solid {ACCENT}; font-weight: 600;
}}
QPushButton[variant="primary"]:hover {{ background: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }}
QPushButton[variant="primary"]:disabled {{ background: #134E3A; border-color: #134E3A; color: #4B7A66; }}

QPushButton[variant="ghost"] {{ background: transparent; border: 1px solid transparent; color: {TEXT_2}; }}
QPushButton[variant="ghost"]:hover {{ background: {SURFACE_HOVER}; color: {TEXT}; }}

QPushButton[variant="danger"] {{ background: {BTN}; border: 1px solid {BTN_BORDER}; color: {DANGER}; }}
QPushButton[variant="danger"]:hover {{ background: {BTN_HOVER}; }}
QPushButton[variant="dangerGhost"] {{ background: transparent; border: 1px solid transparent; color: {DANGER}; }}
QPushButton[variant="dangerGhost"]:hover {{ background: {BTN}; }}

QPushButton[variant="small"] {{ min-height: 26px; padding: 0 10px; font-size: 12px; border-radius: 6px; }}
QPushButton[variant="smallDanger"] {{
    min-height: 26px; padding: 0 10px; font-size: 12px; border-radius: 6px;
    background: transparent; border: 1px solid transparent; color: {DANGER};
}}
QPushButton[variant="smallDanger"]:hover {{ background: {BTN}; border-color: {BTN_BORDER}; }}

QPushButton[variant="badge"] {{
    color: {TEXT_2}; font-size: 12px; font-weight: 500; background: {SURFACE_HOVER};
    border: 1px solid {BORDER}; border-radius: 6px; padding: 3px 9px; min-height: 0;
}}
QPushButton[variant="badge"]:hover {{ color: {TEXT}; border-color: {BTN_BORDER}; }}

QPushButton[variant="link"] {{
    background: transparent; border: none; color: {TEXT_3}; font-size: 12px;
    padding: 0; min-height: 0; text-decoration: none;
}}
QPushButton[variant="link"]:hover {{ color: {TEXT}; }}

QPushButton#PillTab {{
    background: transparent; border: 1px solid transparent; border-radius: 6px;
    color: {TEXT_3}; min-height: 26px; padding: 0 14px; font-weight: 500;
}}
QPushButton#PillTab:hover {{ color: {TEXT_2}; }}
QPushButton#PillTab:checked {{ background: {BTN}; border-color: {BTN_BORDER}; color: {TEXT}; }}

/* ---------- поля ввода ---------- */
QLineEdit {{
    background: {INPUT}; border: 1px solid {BORDER}; border-radius: 8px;
    padding: 0 12px; min-height: 38px; color: {TEXT};
}}
QLineEdit:hover {{ border-color: #2C2C31; }}
QLineEdit:focus {{ border: 1px solid {ACCENT}; }}
QLineEdit:read-only {{ color: {TEXT_2}; }}

QComboBox {{
    background: {INPUT}; border: 1px solid {BORDER}; border-radius: 8px;
    padding: 0 12px; min-height: 34px; color: {TEXT};
}}
QComboBox:hover {{ border-color: {BTN_BORDER}; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{ image: none; width: 0; height: 0; }}
QComboBox QAbstractItemView {{
    background: {PANEL}; border: 1px solid {BORDER}; padding: 4px; outline: none;
    selection-background-color: {SURFACE_ACTIVE}; selection-color: {TEXT};
}}

/* ---------- списки ---------- */
QListWidget {{ background: transparent; border: none; outline: none; }}
QListWidget::item {{ border-radius: 6px; padding: 0; margin: 1px 0; color: {TEXT_2}; }}
QListWidget::item:hover {{ background: {SURFACE_HOVER}; }}
QListWidget::item:selected {{ background: {SURFACE_ACTIVE}; color: {TEXT}; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #2A2A2F; border-radius: 3px; min-height: 32px; margin: 0 2px; }}
QScrollBar::handle:vertical:hover {{ background: {BTN_BORDER}; }}
QScrollBar:horizontal {{ height: 0; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
    background: none; border: none; height: 0; width: 0;
}}

/* ---------- слайдеры ---------- */
QSlider::groove:horizontal {{ height: 4px; background: {BTN_BORDER}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::add-page:horizontal {{ background: {BTN_BORDER}; border-radius: 2px; }}
QSlider::handle:horizontal {{
    background: {TEXT}; width: 12px; height: 12px; margin: -4px 0; border-radius: 6px;
}}
QSlider::handle:horizontal:disabled {{ background: {BTN_BORDER}; }}
QSlider::sub-page:horizontal:disabled {{ background: {BTN_BORDER}; }}

QSlider#Volume::sub-page:horizontal {{ background: {TEXT_2}; }}
QSlider#Volume::handle:horizontal {{ width: 10px; height: 10px; margin: -3px 0; border-radius: 5px; }}

QProgressBar {{ background: {BTN}; border: none; border-radius: 1px; max-height: 2px; min-height: 2px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 1px; }}

QToolTip {{
    background: {BTN}; color: {TEXT}; border: 1px solid {BTN_BORDER};
    border-radius: 6px; padding: 5px 8px; font-size: 12px;
}}
QMenu {{ background: {PANEL}; border: 1px solid {BORDER}; padding: 4px; }}
QMenu::item {{ padding: 6px 14px; border-radius: 4px; }}
QMenu::item:selected {{ background: {SURFACE_ACTIVE}; }}
QMessageBox {{ background: {PANEL}; }}
"""


def _palette() -> QPalette:
    p = QPalette()
    for role, color in [
        (QPalette.Window, BG), (QPalette.WindowText, TEXT), (QPalette.Base, INPUT),
        (QPalette.AlternateBase, PANEL), (QPalette.Text, TEXT), (QPalette.Button, BTN),
        (QPalette.ButtonText, TEXT), (QPalette.Highlight, ACCENT),
        (QPalette.HighlightedText, ON_ACCENT), (QPalette.ToolTipBase, BTN),
        (QPalette.ToolTipText, TEXT), (QPalette.PlaceholderText, TEXT_3),
        (QPalette.BrightText, DANGER), (QPalette.Link, ACCENT),
    ]:
        p.setColor(role, QColor(color))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor(TEXT_3))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(TEXT_3))
    p.setColor(QPalette.Disabled, QPalette.WindowText, QColor(TEXT_3))
    return p


class _DarkTitleBar(QObject):
    """Windows 10/11: тёмная системная шапка окна, чтобы не было белой полосы сверху."""

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Show and isinstance(obj, QWidget) and obj.isWindow():
            if not obj.property("_darkTitle"):
                obj.setProperty("_darkTitle", True)
                set_dark_titlebar(obj)
        return False


def set_dark_titlebar(widget: QWidget) -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes
        hwnd = int(widget.winId())
        value = ctypes.c_int(1)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (новые и старые сборки Windows 10)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value),
                                                          ctypes.sizeof(value)) == 0:
                break
    except Exception:
        pass  # не критично — просто останется системная шапка


def apply(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setPalette(_palette())
    app.setFont(font(13))
    app.setStyleSheet(QSS)
    app._dark_title_filter = _DarkTitleBar(app)
    app.installEventFilter(app._dark_title_filter)
