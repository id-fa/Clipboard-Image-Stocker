"""Background thumbnail generator (QRunnable in QThreadPool)."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, Signal
from PySide6.QtGui import QPixmap

from stocker.core.image_io import make_thumbnail
from stocker.core.models import ThumbKey
from stocker.utils.qt_helpers import pil_to_qpixmap

log = logging.getLogger(__name__)


class ThumbnailSignals(QObject):
    ready = Signal(object, QPixmap)  # ThumbKey, QPixmap
    failed = Signal(object, str)  # ThumbKey, error


class ThumbnailJob(QRunnable):
    def __init__(self, key: ThumbKey, abs_path: Path, signals: ThumbnailSignals):
        super().__init__()
        self.key = key
        self.path = abs_path
        self.signals = signals
        self.setAutoDelete(True)

    def run(self) -> None:  # type: ignore[override]
        try:
            img = make_thumbnail(self.path, self.key.target_size)
            pm = pil_to_qpixmap(img)
            # Let the receiver handle the signal on the main thread.
            self.signals.ready.emit(self.key, pm)
        except Exception as e:  # noqa: BLE001
            log.warning("thumbnail failed for %s: %s", self.path, e)
            self.signals.failed.emit(self.key, str(e))


def make_placeholder(size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    return pm
