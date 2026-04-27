"""Frameless top-window that shows a fitted preview after a hover delay."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import QLabel, QWidget

from stocker.core.image_io import open_for_thumb
from stocker.utils.qt_helpers import pil_to_qpixmap

log = logging.getLogger(__name__)

HOVER_DELAY_MS = 1200
MARGIN = 80


class HoverPreviewWindow(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        # CRITICAL: without this, the preview window appears under the mouse and
        # the underlying ThumbnailView fires leaveEvent → cancel() → preview hides.
        # Mouse-transparent means the cursor "passes through" to the view below.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._label = QLabel(self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet("background: #1e1e1e;")
        self._label.setScaledContents(False)
        self._label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._show_now)
        self._pending_path: Path | None = None
        self._pool = QThreadPool.globalInstance()
        self._signals = _LoadSignals(self)
        self._signals.ready.connect(self._on_loaded)
        self._target_token: int = 0
        self._enabled: bool = True

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        if not self._enabled:
            self.cancel()

    def is_enabled(self) -> bool:
        return self._enabled

    def schedule(self, path: Path | None) -> None:
        if not self._enabled:
            return
        if path is None or not path.exists():
            self.cancel()
            return
        if self._pending_path == path and self.isVisible():
            return
        self._pending_path = path
        self._timer.start(HOVER_DELAY_MS)

    def cancel(self) -> None:
        self._timer.stop()
        self._pending_path = None
        if self.isVisible():
            self.hide()

    def _show_now(self) -> None:
        if self._pending_path is None:
            return
        token = self._target_token + 1
        self._target_token = token
        path = self._pending_path
        self._pool.start(_LoadJob(path, token, self._signals))

    def _on_loaded(self, token: int, pm: QPixmap) -> None:
        if token != self._target_token or self._pending_path is None or pm.isNull():
            return
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        avail = screen.availableGeometry()
        max_w = max(200, avail.width() - 2 * MARGIN)
        max_h = max(200, avail.height() - 2 * MARGIN)
        scaled = pm.scaled(
            max_w, max_h,
            Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,
        )
        self._label.setPixmap(scaled)
        self._label.resize(scaled.size())
        self.resize(scaled.size())
        # center on screen
        center = avail.center() - QPoint(self.width() // 2, self.height() // 2)
        self.move(center)
        self.show()
        self.raise_()


class _LoadSignals(QObject):
    ready = Signal(int, QPixmap)


class _LoadJob(QRunnable):
    def __init__(self, path: Path, token: int, signals: _LoadSignals):
        super().__init__()
        self.path = path
        self.token = token
        self.signals = signals
        self.setAutoDelete(True)

    def run(self) -> None:  # type: ignore[override]
        try:
            img = open_for_thumb(self.path)
            pm = pil_to_qpixmap(img)
            self.signals.ready.emit(self.token, pm)
        except Exception as e:  # noqa: BLE001
            log.warning("hover preview load failed for %s: %s", self.path, e)
