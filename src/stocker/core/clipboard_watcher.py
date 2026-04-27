"""Bridges Qt clipboard image data into the PasteQueue.

Two entry points share the same dedup state:
- paste(): explicit Ctrl+V, always tries to enqueue.
- auto-capture: listens to QClipboard.dataChanged and enqueues new images
  to the PasteQueue's current target_root.

Dedup uses a cheap fingerprint (size, format, four corner pixels) so that
spurious dataChanged events on the same payload — and our own copy-to-
clipboard echoes — don't cause duplicate saves.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject
from PySide6.QtGui import QClipboard, QImage
from PySide6.QtWidgets import QApplication

from stocker.core.paste_queue import PasteQueue

log = logging.getLogger(__name__)

Fingerprint = tuple


def _fingerprint(qimg: QImage) -> Fingerprint | None:
    if qimg.isNull():
        return None
    w, h = qimg.width(), qimg.height()
    if w <= 0 or h <= 0:
        return None
    return (
        w,
        h,
        qimg.format(),  # enum member is hashable + comparable
        int(qimg.sizeInBytes()),
        int(qimg.pixel(0, 0)),
        int(qimg.pixel(w - 1, 0)),
        int(qimg.pixel(0, h - 1)),
        int(qimg.pixel(w - 1, h - 1)),
    )


class ClipboardWatcher(QObject):
    """Bridges clipboard images into the PasteQueue (manual + auto modes)."""

    def __init__(self, paste_queue: PasteQueue, parent: QObject | None = None):
        super().__init__(parent)
        self._queue = paste_queue
        self._autocapture = False
        self._last_fp: Fingerprint | None = None
        cb = QApplication.clipboard()
        if cb is not None:
            cb.dataChanged.connect(self._on_clipboard_changed)

    def set_autocapture(self, enabled: bool) -> None:
        self._autocapture = bool(enabled)
        if self._autocapture:
            # Seed with whatever is currently on the clipboard so we don't
            # immediately re-import the user's pre-existing clipboard image.
            self._last_fp = _fingerprint(QApplication.clipboard().image())
            log.info("clipboard auto-capture enabled")
        else:
            log.info("clipboard auto-capture disabled")

    def is_autocapture(self) -> bool:
        return self._autocapture

    def paste(self) -> bool:
        """Manual Ctrl+V path — always attempts enqueue regardless of toggle."""
        cb: QClipboard = QApplication.clipboard()
        qimg = cb.image()
        if qimg.isNull():
            log.debug("clipboard had no image")
            return False
        # Record fingerprint so the upcoming dataChanged echo (if any) is
        # ignored by the auto-capture path.
        self._last_fp = _fingerprint(qimg)
        pending = self._queue.enqueue(qimg)
        return pending is not None

    def note_self_copy(self, qimg: QImage) -> None:
        """Mark a fingerprint as 'just put on clipboard by us' so auto-capture
        doesn't echo it back as a new import."""
        fp = _fingerprint(qimg)
        if fp is not None:
            self._last_fp = fp

    # --- internal ---

    def _on_clipboard_changed(self) -> None:
        if not self._autocapture:
            return
        cb = QApplication.clipboard()
        if cb is None:
            return
        qimg = cb.image()
        fp = _fingerprint(qimg)
        if fp is None:
            # Non-image clipboard content; reset so we re-capture if an image
            # comes back identical to one we saw earlier.
            self._last_fp = None
            return
        if fp == self._last_fp:
            return
        self._last_fp = fp
        if self._queue.target_root() is None:
            log.debug("auto-capture skipped: no target root")
            return
        self._queue.enqueue(qimg)
