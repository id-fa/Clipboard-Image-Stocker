"""Frameless top-window that shows a fitted preview after a hover delay."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QRunnable, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QImageReader, QMovie, QPixmap
from PySide6.QtWidgets import QLabel, QWidget

from stocker.core.image_io import open_for_thumb
from stocker.utils.qt_helpers import pil_to_qpixmap

log = logging.getLogger(__name__)

HOVER_DELAY_MS = 1200
MARGIN = 80


class HoverPreviewWindow(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        # The preview is click-to-dismiss, so it must NOT be mouse-transparent.
        # When the preview pops up under the cursor, ThumbnailView fires leaveEvent
        # → hover_changed(None) → cancel(). We keep cancel() limited to "stop the
        # pending timer" so a visible preview survives the leaveEvent and stays
        # until the user clicks it (handled in mousePressEvent below).
        self._label = QLabel(self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet("background: #1e1e1e;")
        self._label.setScaledContents(False)
        # Label is transparent so clicks reach the window's mousePressEvent.
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
        self._animate: bool = True
        self._movie: QMovie | None = None

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        if not self._enabled:
            self.dismiss()

    def is_enabled(self) -> bool:
        return self._enabled

    def set_animate(self, enabled: bool) -> None:
        new_val = bool(enabled)
        if new_val == self._animate:
            return
        self._animate = new_val
        # Toggling animation off while a movie is on screen would otherwise
        # leave the running animation visible until the user clicks; drop it
        # so the new setting takes effect immediately.
        if not new_val and self._movie is not None:
            self.dismiss()

    def is_animate(self) -> bool:
        return self._animate

    def schedule(self, path: Path | None) -> None:
        if not self._enabled:
            return
        if path is None or not path.exists():
            self.cancel()
            return
        if self._pending_path == path:
            return
        self._pending_path = path
        self._timer.start(HOVER_DELAY_MS)

    def cancel(self) -> None:
        # Stop a pending timer only. A visible preview is kept until clicked
        # so that moving the cursor off the trigger corner does not dismiss it.
        self._timer.stop()
        if not self.isVisible():
            self._pending_path = None

    def dismiss(self) -> None:
        self._timer.stop()
        self._pending_path = None
        self._stop_movie()
        if self.isVisible():
            self.hide()

    def mousePressEvent(self, e) -> None:
        self.dismiss()
        e.accept()

    def _stop_movie(self) -> None:
        if self._movie is not None:
            self._movie.stop()
            self._movie.deleteLater()
            self._movie = None

    def _show_now(self) -> None:
        if self._pending_path is None:
            return
        token = self._target_token + 1
        self._target_token = token
        path = self._pending_path
        # Animated GIF / WebP path: detect via QImageReader (header parse only)
        # and play with QMovie on the GUI thread. QMovie cannot be moved between
        # threads, so we don't dispatch this through the worker pool.
        if self._animate:
            reader = QImageReader(str(path))
            if reader.supportsAnimation() and reader.imageCount() > 1:
                native = reader.size()
                if native.isValid() and not native.isEmpty():
                    self._show_animated(path, native)
                    return
        self._pool.start(_LoadJob(path, token, self._signals))

    def _show_animated(self, path: Path, native_size: QSize) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        avail = screen.availableGeometry()
        max_w = max(200, avail.width() - 2 * MARGIN)
        max_h = max(200, avail.height() - 2 * MARGIN)
        target = native_size.scaled(max_w, max_h, Qt.AspectRatioMode.KeepAspectRatio)
        self._stop_movie()
        movie = QMovie(str(path))
        movie.setParent(self)
        if not movie.isValid():
            self._pool.start(_LoadJob(path, self._target_token, self._signals))
            return
        movie.setScaledSize(target)
        self._label.setMovie(movie)
        self._label.resize(target)
        self.resize(target)
        center = avail.center() - QPoint(self.width() // 2, self.height() // 2)
        self.move(center)
        self._movie = movie
        movie.start()
        self.show()
        self.raise_()

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
        self._stop_movie()
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
