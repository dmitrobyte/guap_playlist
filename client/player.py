"""Встроенный аудиопроигрыватель (FR-08) — нижний док высотой 76px."""
import re
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import QHBoxLayout, QSlider, QVBoxLayout, QWidget

from client import theme
from client.api import ApiClient
from client.util import fmt_ms
from client.widgets import ElidedLabel, IconButton, TrackCoverWidget, label
from client.workers import run_async


class PlayerWidget(QWidget):
    track_started = Signal(int)  # id играющей композиции

    def __init__(self, api: ApiClient):
        super().__init__()
        self.api = api
        self.current: dict | None = None
        self.played_ids: set[int] = set()
        self.next_provider = None  # функция, возвращающая текущий рейтинг (список треков)
        self._loading_id: int | None = None
        self._last_volume = 80
        cache = QStandardPaths.writableLocation(QStandardPaths.CacheLocation) or str(Path.home() / ".shared_playlist")
        self.cache_root = Path(cache) / "tracks"

        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setVolume(0.8)
        self.player.setAudioOutput(self.audio)

        self.setObjectName("PlayerDock")
        self.setAttribute(Qt.WA_StyledBackground)
        self.setFixedHeight(76)

        # --- слева: текущий трек (250px)
        self.cover = TrackCoverWidget(40, 6)
        self.title = ElidedLabel("Ничего не играет", 13, 600, theme.TEXT)
        self.subtitle = ElidedLabel("Выберите композицию в плейлисте", 12, 400, theme.TEXT_2)
        text_col = QVBoxLayout()
        text_col.setSpacing(1)
        text_col.addStretch(1)
        text_col.addWidget(self.title)
        text_col.addWidget(self.subtitle)
        text_col.addStretch(1)
        left = QWidget()
        left.setFixedWidth(250)
        ll = QHBoxLayout(left)
        ll.setContentsMargins(16, 0, 8, 0)
        ll.setSpacing(12)
        ll.addWidget(self.cover)
        ll.addLayout(text_col, 1)

        # --- центр: управление и прогресс
        self.stop_btn = IconButton("stop", 30, "ghost", "Стоп")
        self.play_btn = IconButton("play", 36, "contrast", "Играть")
        self.next_btn = IconButton("next", 30, "ghost", "Следующая по рейтингу")
        controls = QHBoxLayout()
        controls.setSpacing(14)
        controls.addStretch(1)
        controls.addWidget(self.stop_btn)
        controls.addWidget(self.play_btn)
        controls.addWidget(self.next_btn)
        controls.addStretch(1)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.setCursor(Qt.PointingHandCursor)
        self.pos_label = label("0:00", "muted")
        self.dur_label = label("0:00", "muted")
        self.pos_label.setFixedWidth(36)
        self.pos_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.dur_label.setFixedWidth(36)
        progress = QHBoxLayout()
        progress.setSpacing(10)
        progress.addWidget(self.pos_label)
        progress.addWidget(self.slider, 1)
        progress.addWidget(self.dur_label)

        center = QWidget()
        center.setMaximumWidth(560)
        cl = QVBoxLayout(center)
        cl.setContentsMargins(0, 8, 0, 8)
        cl.setSpacing(4)
        cl.addLayout(controls)
        cl.addLayout(progress)

        # --- справа: громкость (180px)
        self.mute_btn = IconButton("volume", 28, "ghost", "Выключить звук")
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setObjectName("Volume")  # нейтральный цвет: изумруд только для прогресса
        self.volume.setRange(0, 100)
        self.volume.setValue(80)
        self.volume.setCursor(Qt.PointingHandCursor)
        right = QWidget()
        right.setFixedWidth(180)
        rl = QHBoxLayout(right)
        rl.setContentsMargins(4, 0, 20, 0)
        rl.setSpacing(8)
        rl.addWidget(self.mute_btn)
        rl.addWidget(self.volume, 1)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 1, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(left)
        lay.addStretch(1)
        lay.addWidget(center, 3)
        lay.addStretch(1)
        lay.addWidget(right)

        self.play_btn.clicked.connect(self.toggle_play)
        self.stop_btn.clicked.connect(self.player.stop)
        self.next_btn.clicked.connect(self.play_next)
        self.mute_btn.clicked.connect(self._toggle_mute)
        self.slider.sliderMoved.connect(self.player.setPosition)
        self.volume.valueChanged.connect(self._on_volume)
        self.player.positionChanged.connect(self._on_position)
        self.player.durationChanged.connect(self._on_duration)
        self.player.playbackStateChanged.connect(self._on_state)
        self.player.mediaStatusChanged.connect(self._on_status)
        self.player.errorOccurred.connect(lambda _e, msg: self._show_error(f"Ошибка воспроизведения: {msg}"))

    # ------------------------------------------------------------ кэш
    @property
    def cache_dir(self) -> Path:
        # отдельная папка кэша для каждого сервера (id треков на разных серверах совпадают)
        return self.cache_root / re.sub(r"[^A-Za-z0-9]+", "_", self.api.base_url)

    # ------------------------------------------------------------ управление
    def play_track(self, track: dict) -> None:
        if not track.get("playable"):
            return
        self.current = track
        self.played_ids.add(track["id"])
        self.cover.set_track(track["title"], track["artist"])
        self.title.setText(track["title"])
        self.title.setColor(theme.TEXT)
        cached = list(self.cache_dir.glob(f"{track['id']}.*")) if self.cache_dir.exists() else []
        cached = [p for p in cached if not p.name.endswith(".part")]
        if cached:
            self._start(str(cached[0]))
            return
        # Скачиваем в фоне — окно остаётся отзывчивым
        self._loading_id = track["id"]
        self.subtitle.setColor(theme.TEXT_3)
        self.subtitle.setText("Загрузка с сервера…")
        run_async(self.api.download_track, track["id"], str(self.cache_dir),
                  on_ok=lambda path, tid=track["id"]: self._downloaded(tid, path),
                  on_fail=lambda msg, _e: self._show_error(f"Не удалось загрузить: {msg}"))

    def _downloaded(self, track_id: int, path: str) -> None:
        if self._loading_id == track_id:
            self._start(path)

    def _start(self, path: str) -> None:
        self._loading_id = None
        self.player.setSource(QUrl.fromLocalFile(path))
        self.player.play()
        self.subtitle.setColor(theme.TEXT_2)
        self.subtitle.setText(self.current["artist"])
        self.track_started.emit(self.current["id"])

    def _show_error(self, text: str) -> None:
        self.subtitle.setColor(theme.DANGER)
        self.subtitle.setText(text)

    def toggle_play(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        elif self.player.source().isEmpty():
            self.play_next()
        else:
            self.player.play()

    def play_next(self) -> None:
        """Следующая композиция берётся из АКТУАЛЬНОГО рейтинга: самая высокая
        из ещё не сыгранных. Когда сыграны все — круг начинается заново."""
        tracks = [t for t in (self.next_provider() if self.next_provider else []) if t["playable"]]
        if not tracks:
            self.title.setText("Нечего воспроизвести")
            self.subtitle.setColor(theme.TEXT_3)
            self.subtitle.setText("Добавьте трек из библиотеки или файл")
            return
        candidates = [t for t in tracks if t["id"] not in self.played_ids]
        if not candidates:
            self.played_ids.clear()
            candidates = [t for t in tracks if not self.current or t["id"] != self.current["id"]] or tracks
        self.play_track(candidates[0])

    def _toggle_mute(self) -> None:
        if self.volume.value() > 0:
            self._last_volume = self.volume.value()
            self.volume.setValue(0)
        else:
            self.volume.setValue(self._last_volume or 60)

    # ------------------------------------------------------------ события
    def _on_volume(self, v: int) -> None:
        self.audio.setVolume(v / 100)
        self.mute_btn.set_kind("mute" if v == 0 else "volume")
        self.mute_btn.setToolTip("Включить звук" if v == 0 else "Выключить звук")

    def _on_position(self, pos: int) -> None:
        if not self.slider.isSliderDown():
            self.slider.setValue(pos)
        self.pos_label.setText(fmt_ms(pos))

    def _on_duration(self, dur: int) -> None:
        self.slider.setRange(0, dur)
        self.dur_label.setText(fmt_ms(dur))

    def _on_state(self, state) -> None:
        playing = state == QMediaPlayer.PlayingState
        self.play_btn.set_kind("pause" if playing else "play")
        self.play_btn.setToolTip("Пауза" if playing else "Играть")

    def _on_status(self, status) -> None:
        if status == QMediaPlayer.EndOfMedia:
            self.play_next()
