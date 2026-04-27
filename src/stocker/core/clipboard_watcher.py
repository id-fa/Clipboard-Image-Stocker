"""Bridges Qt clipboard image data into the PasteQueue."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject
from PySide6.QtGui import QClipboard
from PySide6.QtWidgets import QApplication

from stocker.core.paste_queue import PasteQueue

log = logging.getLogger(__name__)


class ClipboardWatcher(QObject):
    """Call paste() to grab the current clipboard image and enqueue it."""

    def __init__(self, paste_queue: PasteQueue, parent: QObject | None = None):
        super().__init__(parent)
        self._queue = paste_queue

    def paste(self) -> bool:
        cb: QClipboard = QApplication.clipboard()
        qimg = cb.image()
        if qimg.isNull():
            log.debug("clipboard had no image")
            return False
        pending = self._queue.enqueue(qimg)
        return pending is not None
