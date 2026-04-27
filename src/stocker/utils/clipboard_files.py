"""Helpers for putting file references on the clipboard in an Explorer-compatible way."""

from __future__ import annotations

import struct
from pathlib import Path

from PySide6.QtCore import QMimeData, QUrl
from PySide6.QtGui import QClipboard, QImage
from PySide6.QtWidgets import QApplication

# Windows shell uses CF_HDROP + 'Preferred DropEffect' to know whether the
# clipboard payload should be moved or copied on paste. DROPEFFECT_COPY = 5.
PREFERRED_DROP_EFFECT_MIME = (
    'application/x-qt-windows-mime;value="Preferred DropEffect"'
)
DROPEFFECT_COPY = struct.pack("<I", 5)
DROPEFFECT_MOVE = struct.pack("<I", 2)


def copy_files_to_clipboard(paths: list[Path], move: bool = False) -> None:
    """Put file URLs on the clipboard so Explorer (and Stocker) can paste them.

    `move=True` flags the operation as a Cut (Explorer will move the source).
    """
    if not paths:
        return
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    mime.setData(
        PREFERRED_DROP_EFFECT_MIME, DROPEFFECT_MOVE if move else DROPEFFECT_COPY
    )
    QApplication.clipboard().setMimeData(mime, QClipboard.Mode.Clipboard)


def copy_image_to_clipboard(qimg: QImage) -> bool:
    if qimg.isNull():
        return False
    QApplication.clipboard().setImage(qimg, QClipboard.Mode.Clipboard)
    return True


def file_urls_from_clipboard() -> list[Path]:
    cb = QApplication.clipboard()
    mime = cb.mimeData()
    if mime is None or not mime.hasUrls():
        return []
    return [Path(u.toLocalFile()) for u in mime.urls() if u.isLocalFile() and u.toLocalFile()]
