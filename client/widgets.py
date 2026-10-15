"""Переиспользуемые компоненты интерфейса. Иконки и обложки рисуются через QPainter —
никаких картинок и эмодзи, всё чётко на любом масштабе экрана."""
from PySide6.QtCore import (QEasingCurve, QPointF, QPropertyAnimation, QRectF, QSize, Qt,
                            QTimer, Signal)
from PySide6.QtGui import (QColor, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen,
                           QPolygonF)
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QComboBox, QDialog, QFileDialog, QFrame,
                               QGraphicsOpacityEffect, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

from client import theme


# ================================================================== мелкие фабрики
def label(text: str = "", role: str | None = None, parent=None) -> QLabel:
    lb = QLabel(text, parent)
    if role:
        lb.setProperty("textRole", role)
    return lb


def button(text: str, variant: str | None = None, parent=None) -> QPushButton:
    b = QPushButton(text, parent)
    if variant:
        b.setProperty("variant", variant)
    b.setCursor(Qt.PointingHandCursor)
    return b


def divider() -> QFrame:
    d = QFrame()
    d.setObjectName("Divider")
    d.setFrameShape(QFrame.NoFrame)
    return d


def restyle(w: QWidget) -> None:
    """Перечитать QSS после смены динамического свойства."""
    w.style().unpolish(w)
    w.style().polish(w)
    w.update()


def _painter(w: QWidget) -> QPainter:
    p = QPainter(w)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    return p


# ================================================================== текст с многоточием
class ElidedLabel(QWidget):
    """Однострочная подпись, которая аккуратно обрезается «…» вместо раздвигания вёрстки."""

    def __init__(self, text: str = "", size: float = 13, weight: int = 400,
                 color: str = theme.TEXT, parent=None):
        super().__init__(parent)
        self._text = text
        self._font = theme.font(size, weight)
        self._color = QColor(color)
        fm = QFontMetrics(self._font)
        self.setFixedHeight(fm.height() + 2)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumWidth(20)

    def text(self) -> str:
        return self._text

    def setText(self, text: str) -> None:
        self._text = text or ""
        self.setToolTip(self._text if QFontMetrics(self._font).horizontalAdvance(self._text) > self.width() else "")
        self.update()

    def setColor(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(QFontMetrics(self._font).horizontalAdvance(self._text) + 2, self.height())

    def paintEvent(self, _e):
        p = _painter(self)
        p.setFont(self._font)
        p.setPen(self._color)
        fm = QFontMetrics(self._font)
        p.drawText(self.rect(), Qt.AlignVCenter | Qt.AlignLeft,
                   fm.elidedText(self._text, Qt.ElideRight, self.width()))


# ================================================================== обложка трека
class TrackCoverWidget(QWidget):
    """Квадратная обложка: приглушённый тон по хешу названия + инициалы исполнителя."""

    def __init__(self, size: int = 40, radius: float = 6, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._radius = radius
        self._title = ""
        self._artist = ""

    def set_track(self, title: str, artist: str) -> None:
        self._title, self._artist = title or "", artist or ""
        self.update()

    def clear(self) -> None:
        self.set_track("", "")

    def paintEvent(self, _e):
        p = _painter(self)
        r = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(r, self._radius, self._radius)
        if not self._title and not self._artist:
            p.fillPath(path, QColor(theme.SURFACE_ACTIVE))
            # маленькая нота — пустое состояние
            pen = QPen(QColor(theme.TEXT_3), max(1.2, self.width() / 30))
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            s = self.width()
            p.drawLine(QPointF(s * 0.56, s * 0.30), QPointF(s * 0.56, s * 0.62))
            p.drawLine(QPointF(s * 0.56, s * 0.30), QPointF(s * 0.68, s * 0.36))
            p.setBrush(QColor(theme.TEXT_3))
            p.drawEllipse(QPointF(s * 0.49, s * 0.64), s * 0.08, s * 0.065)
            return
        base = theme.tone_for(self._title)
        grad = QLinearGradient(r.topLeft(), r.bottomRight())
        grad.setColorAt(0, base.lighter(118))
        grad.setColorAt(1, base.darker(108))
        p.fillPath(path, grad)
        # тонкая внутренняя обводка — даёт «материальность» без рамок
        p.setPen(QPen(QColor(255, 255, 255, 18), 1))
        p.drawPath(path)
        p.setPen(QColor(244, 244, 245, 235))
        p.setFont(theme.font(self.width() * 0.36, 600))
        p.drawText(r, Qt.AlignCenter, theme.initials(self._artist))


class AvatarWidget(QWidget):
    """Круглый аватар с первой буквой имени."""

    def __init__(self, size: int = 32, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._name = ""

    def set_name(self, name: str) -> None:
        self._name = name or ""
        self.update()

    def paintEvent(self, _e):
        p = _painter(self)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(Qt.NoPen)
        p.setBrush(theme.tone_for(self._name).lighter(125))
        p.drawEllipse(r)
        p.setPen(QColor(theme.TEXT))
        p.setFont(theme.font(self.width() * 0.42, 600))
        p.drawText(r, Qt.AlignCenter, theme.initials(self._name, 1))


class PlayingIndicator(QWidget):
    """Три изумрудные полоски — «сейчас играет» (вместо номера позиции)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(14, 14)

    def paintEvent(self, _e):
        p = _painter(self)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.ACCENT))
        for i, h in enumerate((0.55, 1.0, 0.75)):
            bh = 12 * h
            p.drawRoundedRect(QRectF(1 + i * 4.5, 13 - bh, 3, bh), 1, 1)


# ================================================================== иконки-кнопки
class IconButton(QAbstractButton):
    """Кнопка с векторной иконкой.
    kind: play, pause, stop, next, link, volume, mute
    style: ghost (прозрачная), round (круглая тёмная), contrast (круглая светлая)"""

    def __init__(self, kind: str, size: int = 32, style: str = "ghost", tooltip: str = "", parent=None):
        super().__init__(parent)
        self.kind, self._style = kind, style
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tooltip)
        self.setAttribute(Qt.WA_Hover)

    def set_kind(self, kind: str) -> None:
        self.kind = kind
        self.update()

    def enterEvent(self, e):
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, _e):
        p = _painter(self)
        r = QRectF(self.rect())
        hover = self.underMouse() and self.isEnabled()
        if self._style == "contrast":
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.TEXT if not hover else "#FFFFFF"))
            p.drawEllipse(r.adjusted(0.5, 0.5, -0.5, -0.5))
            glyph = QColor(theme.BG)
        elif self._style == "round":
            p.setPen(QPen(QColor(theme.BTN_BORDER), 1))
            p.setBrush(QColor(theme.BTN_HOVER if hover else theme.BTN))
            p.drawEllipse(r.adjusted(0.5, 0.5, -0.5, -0.5))
            glyph = QColor(theme.TEXT)
        else:
            if hover:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(theme.SURFACE_ACTIVE))
                p.drawRoundedRect(r, 6, 6)
            glyph = QColor(theme.TEXT if hover else theme.TEXT_2)
        if not self.isEnabled():
            glyph = QColor(theme.TEXT_3)
        if self.isDown():
            glyph.setAlpha(170)
        s = min(r.width(), r.height()) * (0.42 if self._style != "ghost" else 0.5)
        self._draw_glyph(p, r.center(), s, glyph)

    def _draw_glyph(self, p: QPainter, c: QPointF, s: float, color: QColor) -> None:
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        k = self.kind
        if k == "play":
            h = s * 0.5
            poly = QPolygonF([QPointF(c.x() - h * 0.62, c.y() - h), QPointF(c.x() - h * 0.62, c.y() + h),
                              QPointF(c.x() + h * 0.95, c.y())])
            path = QPainterPath()
            path.addPolygon(poly)
            p.setPen(QPen(color, s * 0.08, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPath(path)
        elif k == "pause":
            w, h = s * 0.22, s * 0.92
            p.drawRoundedRect(QRectF(c.x() - s * 0.32, c.y() - h / 2, w, h), 1.2, 1.2)
            p.drawRoundedRect(QRectF(c.x() + s * 0.10, c.y() - h / 2, w, h), 1.2, 1.2)
        elif k == "stop":
            a = s * 0.72
            p.drawRoundedRect(QRectF(c.x() - a / 2, c.y() - a / 2, a, a), 1.8, 1.8)
        elif k == "next":
            h = s * 0.42
            poly = QPolygonF([QPointF(c.x() - h * 1.0, c.y() - h), QPointF(c.x() - h * 1.0, c.y() + h),
                              QPointF(c.x() + h * 0.55, c.y())])
            p.setPen(QPen(color, s * 0.07, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPolygon(poly)
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRectF(c.x() + h * 0.62, c.y() - h, s * 0.13, h * 2), 1, 1)
        elif k == "link":
            pen = QPen(color, max(1.5, s * 0.11), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            a = s * 0.36
            p.drawLine(QPointF(c.x() - a, c.y() + a), QPointF(c.x() + a, c.y() - a))
            path = QPainterPath(QPointF(c.x() - a * 0.15, c.y() - a))
            path.lineTo(QPointF(c.x() + a, c.y() - a))
            path.lineTo(QPointF(c.x() + a, c.y() + a * 0.15))
            p.drawPath(path)
        elif k in ("volume", "mute"):
            body = QPolygonF([QPointF(c.x() - s * 0.50, c.y() - s * 0.16), QPointF(c.x() - s * 0.28, c.y() - s * 0.16),
                              QPointF(c.x() - s * 0.02, c.y() - s * 0.42), QPointF(c.x() - s * 0.02, c.y() + s * 0.42),
                              QPointF(c.x() - s * 0.28, c.y() + s * 0.16), QPointF(c.x() - s * 0.50, c.y() + s * 0.16)])
            p.drawPolygon(body)
            pen = QPen(color, max(1.4, s * 0.09), Qt.SolidLine, Qt.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            if k == "mute":
                d = s * 0.16
                x0 = c.x() + s * 0.30
                p.drawLine(QPointF(x0 - d, c.y() - d), QPointF(x0 + d, c.y() + d))
                p.drawLine(QPointF(x0 - d, c.y() + d), QPointF(x0 + d, c.y() - d))
            else:
                for rad in (0.22, 0.42):
                    rect = QRectF(c.x() - s * rad, c.y() - s * rad, s * rad * 2, s * rad * 2)
                    p.drawArc(rect.translated(s * 0.06, 0), -45 * 16, 90 * 16)


# ================================================================== кнопка голоса
class VoteButton(QAbstractButton):
    """Пилюля [▲ 12]. Залита изумрудным, если пользователь проголосовал."""

    def __init__(self, votes: int = 0, voted: bool = False, parent=None):
        super().__init__(parent)
        self.setCheckable(False)
        self.setFixedSize(64, 30)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover)
        self.votes, self.voted, self.busy = votes, voted, False
        self._sync_tooltip()

    def set_state(self, votes: int, voted: bool) -> None:
        self.votes, self.voted, self.busy = votes, voted, False
        self.setEnabled(True)
        self._sync_tooltip()
        self.update()

    def set_busy(self) -> None:
        self.busy = True
        self.setEnabled(False)
        self.update()

    def text(self) -> str:  # удобно для тестов и доступности
        return f"{'✓' if self.voted else '▲'} {self.votes}"

    def _sync_tooltip(self):
        self.setToolTip("Ваш голос учтён — нажмите, чтобы отозвать" if self.voted
                        else "Проголосовать за композицию")

    def enterEvent(self, e):
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, _e):
        p = _painter(self)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        hover = self.underMouse() and not self.busy
        if self.voted:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.ACCENT_HOVER if hover else theme.ACCENT))
            fg = QColor(theme.ON_ACCENT)
            tri = QColor(theme.ON_ACCENT)
        else:
            p.setPen(QPen(QColor(theme.BTN_BORDER), 1))
            p.setBrush(QColor(theme.BTN_HOVER if hover else theme.BTN))
            fg = QColor(theme.TEXT)
            tri = QColor(theme.ACCENT if hover else theme.TEXT_2)
        if self.busy:
            fg.setAlpha(110)
            tri.setAlpha(110)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)

        f = theme.font(12.5, 600)
        fm = QFontMetrics(f)
        count = str(self.votes)
        tw = 8 + 6 + fm.horizontalAdvance(count)
        x = r.center().x() - tw / 2
        cy = r.center().y()
        p.setPen(Qt.NoPen)
        p.setBrush(tri)
        p.drawPolygon(QPolygonF([QPointF(x, cy + 3), QPointF(x + 8, cy + 3), QPointF(x + 4, cy - 3.5)]))
        p.setPen(fg)
        p.setFont(f)
        p.drawText(QRectF(x + 14, r.top(), fm.horizontalAdvance(count) + 2, r.height()),
                   Qt.AlignVCenter | Qt.AlignLeft, count)


# ================================================================== сегментные вкладки
class PillTabs(QWidget):
    """Segmented control вместо системных закладок."""
    changed = Signal(int)

    def __init__(self, titles: list[str], parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        self.buttons: list[QPushButton] = []
        for i, t in enumerate(titles):
            b = QPushButton(t)
            b.setObjectName("PillTab")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            self.group.addButton(b, i)
            lay.addWidget(b)
            self.buttons.append(b)
        self.buttons[0].setChecked(True)
        self.group.idClicked.connect(self.changed.emit)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

    def set_title(self, index: int, text: str) -> None:
        self.buttons[index].setText(text)

    def set_current(self, index: int) -> None:
        self.buttons[index].setChecked(True)
        self.changed.emit(index)

    def paintEvent(self, _e):
        p = _painter(self)
        p.setPen(QPen(QColor(theme.BORDER), 1))
        p.setBrush(QColor(theme.SURFACE_HOVER))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)


# ================================================================== уведомление
class Toast(QWidget):
    """Короткое уведомление внизу окна, само исчезает."""

    def __init__(self, host: QWidget):
        super().__init__(host)
        self.host = host
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._text, self._kind = "", "info"
        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._anim = QPropertyAnimation(self._effect, b"opacity", self)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._timer = QTimer(self, singleShot=True, timeout=self._fade_out)
        self.bottom_offset = 96
        self.hide()

    def show_message(self, text: str, kind: str = "info", ms: int = 2600) -> None:
        self._text, self._kind = text, kind
        f = theme.font(12.5, 500)
        w = min(QFontMetrics(f).horizontalAdvance(text) + 52, self.host.width() - 40)
        self.resize(int(w), 38)
        self.move((self.host.width() - self.width()) // 2,
                  self.host.height() - self.height() - self.bottom_offset)
        self.raise_()
        self.show()
        self._anim.stop()
        self._anim.setDuration(160)
        self._anim.setStartValue(self._effect.opacity() if self.isVisible() else 0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()
        self._timer.start(ms)
        self.update()

    def _fade_out(self):
        self._anim.stop()
        self._anim.setDuration(260)
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.finished.connect(self._hide_once)
        self._anim.start()

    def _hide_once(self):
        try:
            self._anim.finished.disconnect(self._hide_once)
        except RuntimeError:
            pass
        if self._effect.opacity() < 0.05:
            self.hide()

    def paintEvent(self, _e):
        p = _painter(self)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(theme.BTN_BORDER), 1))
        p.setBrush(QColor(theme.BTN))
        p.drawRoundedRect(r, 9, 9)
        dot = {"error": theme.DANGER, "success": theme.ACCENT}.get(self._kind, theme.TEXT_2)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(dot))
        p.drawEllipse(QPointF(18, r.center().y()), 3.5, 3.5)
        p.setPen(QColor(theme.TEXT))
        f = theme.font(12.5, 500)
        p.setFont(f)
        p.drawText(r.adjusted(32, 0, -14, 0), Qt.AlignVCenter | Qt.AlignLeft,
                   QFontMetrics(f).elidedText(self._text, Qt.ElideRight, int(r.width() - 46)))


# ================================================================== прокручиваемый список строк
class RowList(QScrollArea):
    """Плавный вертикальный список виджетов-строк с пустым состоянием."""

    def __init__(self, empty_text: str = "Пусто", spacing: int = 2, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._spacing = spacing
        self._empty_text = empty_text
        self.rows: list[QWidget] = []
        self.set_rows([])

    def set_empty_text(self, text: str) -> None:
        self._empty_text = text

    def set_rows(self, rows: list[QWidget]) -> None:
        scroll = self.verticalScrollBar().value()
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 4, 0)
        lay.setSpacing(self._spacing)
        if not rows:
            e = label(self._empty_text, "secondary")
            e.setAlignment(Qt.AlignCenter)
            e.setContentsMargins(0, 36, 0, 0)
            lay.addWidget(e)
        for w in rows:
            lay.addWidget(w)
        lay.addStretch(1)
        self.setWidget(inner)
        self.rows = rows
        self.verticalScrollBar().setValue(scroll)


class HoverRow(QWidget):
    """Строка, которая мягко подсвечивается при наведении."""

    def __init__(self, height: int = 56, hover_color: str = theme.ROW_HOVER, parent=None):
        super().__init__(parent)
        self.setFixedHeight(height)
        self.setAttribute(Qt.WA_Hover)
        self._hover = False
        self._hover_color = QColor(hover_color)

    def enterEvent(self, e):
        self._hover = True
        self.on_hover(True)
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.on_hover(False)
        self.update()
        super().leaveEvent(e)

    def on_hover(self, hovered: bool) -> None:
        pass

    def paintEvent(self, _e):
        if self._hover:
            p = _painter(self)
            p.setPen(Qt.NoPen)
            p.setBrush(self._hover_color)
            p.drawRoundedRect(QRectF(self.rect()), 8, 8)


# ================================================================== диалоги
class StyledDialog(QDialog):
    """Окно в стиле приложения: заголовок, подзаголовок, тело, нижняя панель кнопок."""

    def __init__(self, title: str, subtitle: str = "", parent=None, width: int = 560):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(width)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 22)
        outer.setSpacing(0)
        self.title_label = label(title, "h2")
        outer.addWidget(self.title_label)
        if subtitle:
            outer.addSpacing(4)
            self.subtitle_label = label(subtitle, "secondary")
            self.subtitle_label.setWordWrap(True)
            outer.addWidget(self.subtitle_label)
        outer.addSpacing(18)
        self.body = QVBoxLayout()
        self.body.setSpacing(12)
        outer.addLayout(self.body, 1)
        self.footer = QHBoxLayout()
        self.footer.setSpacing(8)
        outer.addSpacing(18)
        outer.addLayout(self.footer)


class PromptDialog(StyledDialog):
    """Подтверждение или ввод одной строки — вместо системных QInputDialog/QMessageBox."""

    def __init__(self, parent, title: str, text: str = "", ok_text: str = "Готово",
                 placeholder: str | None = None, danger: bool = False):
        super().__init__(title, text, parent, width=420)
        self.edit = None
        if placeholder is not None:
            self.edit = QLineEdit()
            self.edit.setPlaceholderText(placeholder)
            self.edit.returnPressed.connect(self.accept)
            self.body.addWidget(self.edit)
        self.footer.addStretch(1)
        cancel = button("Отмена", "ghost")
        cancel.clicked.connect(self.reject)
        ok = button(ok_text, "danger" if danger else "primary")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        self.footer.addWidget(cancel)
        self.footer.addWidget(ok)

    @staticmethod
    def ask_text(parent, title: str, text: str, placeholder: str, ok_text: str) -> str | None:
        d = PromptDialog(parent, title, text, ok_text, placeholder)
        if d.exec() and d.edit.text().strip():
            return d.edit.text().strip()
        return None

    @staticmethod
    def confirm(parent, title: str, text: str, ok_text: str, danger: bool = False) -> bool:
        return bool(PromptDialog(parent, title, text, ok_text, danger=danger).exec())


# ================================================================== зона выбора файла
class DropZone(QWidget):
    """Пунктирная зона: перетащите файл или нажмите, чтобы выбрать."""
    file_chosen = Signal(str)

    def __init__(self, extensions=(".mp3", ".wav"), hint: str = "", parent=None):
        super().__init__(parent)
        self.ext = extensions
        self.hint = hint
        self.path = ""
        self.title = "Перетащите MP3 или WAV сюда"
        self.subtitle = "или нажмите, чтобы выбрать файл"
        self.setAcceptDrops(True)
        self.setFixedHeight(120)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover)
        self._drag = False

    def set_file(self, path: str, title: str, subtitle: str) -> None:
        self.path, self.title, self.subtitle = path, title, subtitle
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            path, _ = QFileDialog.getOpenFileName(self, "Выберите аудиофайл", "", "Аудио (*.mp3 *.wav)")
            if path:
                self.file_chosen.emit(path)

    def dragEnterEvent(self, e):
        urls = e.mimeData().urls()
        if urls and urls[0].toLocalFile().lower().endswith(self.ext):
            self._drag = True
            e.acceptProposedAction()
            self.update()

    def dragLeaveEvent(self, _e):
        self._drag = False
        self.update()

    def dropEvent(self, e):
        self._drag = False
        self.update()
        self.file_chosen.emit(e.mimeData().urls()[0].toLocalFile())

    def enterEvent(self, e):
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, _e):
        p = _painter(self)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        active = self._drag or self.underMouse()
        pen = QPen(QColor(theme.ACCENT if self._drag else (theme.BTN_BORDER if active else "#2E2E34")), 1.2)
        pen.setDashPattern([4, 4])
        p.setPen(pen)
        p.setBrush(QColor(theme.SURFACE_HOVER if active else theme.PANEL))
        p.drawRoundedRect(r, 10, 10)
        # стрелка «загрузка»
        c = QPointF(r.center().x(), r.top() + 34)
        p.setPen(QPen(QColor(theme.TEXT_2), 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawLine(QPointF(c.x(), c.y() + 7), QPointF(c.x(), c.y() - 7))
        p.drawLine(QPointF(c.x() - 5, c.y() - 2), QPointF(c.x(), c.y() - 7))
        p.drawLine(QPointF(c.x() + 5, c.y() - 2), QPointF(c.x(), c.y() - 7))
        p.drawLine(QPointF(c.x() - 9, c.y() + 11), QPointF(c.x() + 9, c.y() + 11))
        p.setPen(QColor(theme.TEXT))
        f1 = theme.font(13, 600)
        p.setFont(f1)
        fm1 = QFontMetrics(f1)
        p.drawText(QRectF(r.left() + 16, r.top() + 56, r.width() - 32, 20), Qt.AlignHCenter | Qt.AlignVCenter,
                   fm1.elidedText(self.title, Qt.ElideMiddle, int(r.width() - 32)))
        p.setPen(QColor(theme.TEXT_3))
        p.setFont(theme.font(11.5))
        p.drawText(QRectF(r.left(), r.top() + 78, r.width(), 18), Qt.AlignHCenter | Qt.AlignVCenter, self.subtitle)


# ================================================================== выпадающий список
class ComboBox(QComboBox):
    """QComboBox с аккуратным векторным шевроном вместо системной стрелки."""

    def paintEvent(self, e):
        super().paintEvent(e)
        p = _painter(self)
        pen = QPen(QColor(theme.TEXT_2), 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        cx, cy = self.width() - 16, self.height() / 2
        p.drawPolyline(QPolygonF([QPointF(cx - 4, cy - 2), QPointF(cx, cy + 2), QPointF(cx + 4, cy - 2)]))
