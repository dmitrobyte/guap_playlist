"""Запуск сетевых операций в фоновом потоке, чтобы окно не «зависало»."""
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from client.api import ApiError

_active: set = set()  # держим ссылки, пока задача не завершилась


class _Signals(QObject):
    ok = Signal(object)
    fail = Signal(str, object)
    done = Signal()


class _Task(QRunnable):
    def __init__(self, fn, args, kwargs):
        super().__init__()
        self.fn, self.args, self.kwargs = fn, args, kwargs
        self.signals = _Signals()
        self.setAutoDelete(False)  # временем жизни управляет Python (_active)

    def run(self):
        try:
            result = self.fn(*self.args, **self.kwargs)
        except ApiError as e:
            self.signals.fail.emit(e.message, e)
        except Exception as e:  # ошибка не должна ронять приложение
            self.signals.fail.emit(f"Непредвиденная ошибка: {e}", e)
        else:
            self.signals.ok.emit(result)
        self.signals.done.emit()


def run_async(fn, *args, on_ok=None, on_fail=None, **kwargs) -> None:
    """Выполнить fn(*args) в фоне; on_ok(result) / on_fail(message, exc) — в основном потоке."""
    task = _Task(fn, args, kwargs)
    if on_ok:
        task.signals.ok.connect(on_ok)
    if on_fail:
        task.signals.fail.connect(on_fail)
    _active.add(task)
    task.signals.done.connect(lambda: _active.discard(task))
    QThreadPool.globalInstance().start(task)
