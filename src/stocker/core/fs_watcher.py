"""Thin debounced wrapper over QFileSystemWatcher for the active folder root."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer, Signal

from stocker.app_paths import STOCKER_DIRNAME

log = logging.getLogger(__name__)

DEBOUNCE_MS = 500


class FolderWatcher(QObject):
    """Watches root for changes; emits a debounced changed() signal."""

    changed = Signal(object)  # Path

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(self._on_changed)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fire)
        self._pending: Path | None = None
        self._root: Path | None = None

    def watch(self, root: Path | None) -> None:
        if self._watcher.directories():
            self._watcher.removePaths(self._watcher.directories())
        self._root = root
        self._pending = None
        if root is not None and root.exists():
            self._watcher.addPath(str(root))

    def _on_changed(self, path: str) -> None:
        p = Path(path)
        # Ignore changes that originated under .stocker/
        try:
            if STOCKER_DIRNAME in p.parts:
                return
        except Exception:  # noqa: BLE001
            pass
        self._pending = self._root
        self._timer.start(DEBOUNCE_MS)

    def _fire(self) -> None:
        if self._pending is None:
            return
        self.changed.emit(self._pending)
        self._pending = None
