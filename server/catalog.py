"""Подготовленный каталог демонстрационных композиций.

Аудио генерируется этим же скриптом (простые мелодии из синусоид), поэтому
файлы гарантированно свободны для использования на защите."""
import array
import json
import math
import wave
from pathlib import Path

from server import config

SAMPLE_RATE = 22050

# Ноты: имя -> частота (Гц)
_NOTES = {
    "C4": 261.63, "D4": 293.66, "E4": 329.63, "F4": 349.23, "G4": 392.00, "A4": 440.00,
    "B4": 493.88, "C5": 523.25, "D5": 587.33, "E5": 659.25, "G5": 783.99, "A3": 220.00,
    "G3": 196.00, "F3": 174.61, "E3": 164.81, "C3": 130.81, "D3": 146.83, "-": 0.0,
}

# key, title, artist, bpm, melody, bass
_TRACKS = [
    ("demo-01", "Утренний кампус", "Demo Ensemble", 120,
     "C4 E4 G4 C5 G4 E4 C4 E4 F4 A4 C5 A4 F4 A4 G4 -", "C3 C3 F3 F3 G3 G3 C3 C3"),
    ("demo-02", "Сессия близко", "Студенческий бэнд", 140,
     "A4 C5 E5 C5 A4 E4 A4 C5 G4 B4 D5 B4 G4 D4 G4 -", "A3 A3 G3 G3 A3 A3 G3 G3"),
    ("demo-03", "Перемена", "Lo-Fi Group", 90,
     "E4 G4 A4 G4 E4 D4 C4 D4 E4 G4 E4 D4 C4 - C4 -", "C3 C3 A3 A3 F3 F3 G3 G3"),
    ("demo-04", "Ночной коворкинг", "Synth Club", 100,
     "D4 F4 A4 D5 A4 F4 D4 A3 C4 E4 G4 C5 G4 E4 C4 -", "D3 D3 D3 D3 C3 C3 C3 C3"),
    ("demo-05", "Дедлайн в пятницу", "Demo Ensemble", 160,
     "G4 G4 D5 D5 E5 E5 D5 - C5 C5 B4 B4 A4 A4 G4 -", "G3 G3 C3 G3 C3 G3 D3 G3"),
    ("demo-06", "Факультетский вальс", "Камерный кружок", 110,
     "C4 E4 G4 E4 G4 C5 B4 G4 A4 F4 D4 F4 G4 E4 C4 -", "C3 C3 F3 F3 G3 G3 C3 C3"),
]

SOURCE_INFO = "Демо-трек, сгенерирован программно (свободен для использования)"


def catalog_path() -> Path:
    return config.CATALOG_DIR / "catalog.json"


def audio_dir() -> Path:
    return config.CATALOG_DIR / "audio"


def _synth(path: Path, bpm: int, melody: str, bass: str, repeats: int = 4) -> None:
    beat = 60.0 / bpm
    mel = melody.split() * repeats
    bas = bass.split() * repeats
    total = len(mel) * beat
    n = int(total * SAMPLE_RATE)
    samples = array.array("h", bytes(2 * n))
    note_len = int(beat * SAMPLE_RATE)
    bass_len = note_len * 2

    def add(freq: float, start: int, length: int, amp: float, harmonic: bool):
        if freq <= 0:
            return
        w = 2 * math.pi * freq / SAMPLE_RATE
        for i in range(length):
            idx = start + i
            if idx >= n:
                break
            env = min(1.0, i / 200) * max(0.0, 1 - i / length) ** 1.5
            v = math.sin(w * i)
            if harmonic:
                v += 0.3 * math.sin(2 * w * i)
            samples[idx] = max(-32767, min(32767, samples[idx] + int(amp * env * v)))

    for k, name in enumerate(mel):
        add(_NOTES[name], k * note_len, note_len, 9000, True)
    for k, name in enumerate(bas):
        add(_NOTES[name], k * bass_len, bass_len, 7000, False)

    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(samples.tobytes())


def ensure_catalog() -> None:
    """Создаёт catalog.json и аудиофайлы, если их ещё нет."""
    audio_dir().mkdir(parents=True, exist_ok=True)
    entries = []
    for key, title, artist, bpm, melody, bass in _TRACKS:
        fname = f"{key}.wav"
        fpath = audio_dir() / fname
        if not fpath.exists():
            _synth(fpath, bpm, melody, bass)
        entries.append({"key": key, "title": title, "artist": artist,
                        "source_info": SOURCE_INFO, "file": fname})
    if not catalog_path().exists():
        catalog_path().write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")


def load_catalog() -> list[dict]:
    try:
        return json.loads(catalog_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []


def find_entry(key: str) -> dict | None:
    return next((e for e in load_catalog() if e["key"] == key), None)


if __name__ == "__main__":
    ensure_catalog()
    print("Каталог готов:", catalog_path())
