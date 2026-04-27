"""Qt-aware debounce helper based on QTimer.singleShot."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QTimer


class Debouncer(QObject):
    """Calls `callback(*last_args, **last_kwargs)` after `delay_ms` of quiet."""

    def __init__(self, delay_ms: int, callback: Callable[..., Any], parent: QObject | None = None):
        super().__init__(parent)
        self._delay_ms = delay_ms
        self._callback = callback
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fire)
        self._args: tuple[Any, ...] = ()
        self._kwargs: dict[str, Any] = {}

    def call(self, *args: Any, **kwargs: Any) -> None:
        self._args = args
        self._kwargs = kwargs
        self._timer.start(self._delay_ms)

    def cancel(self) -> None:
        self._timer.stop()

    def _fire(self) -> None:
        self._callback(*self._args, **self._kwargs)
