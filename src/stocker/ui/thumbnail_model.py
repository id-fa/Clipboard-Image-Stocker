"""QAbstractListModel backing the thumbnail grid."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QAbstractListModel, QMimeData, QModelIndex, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QPixmap

from stocker.core.models import FileItem, FileKind, PendingPaste, ThumbKey
from stocker.utils.paths import from_rel

log = logging.getLogger(__name__)

ITEM_ROLE = int(Qt.ItemDataRole.UserRole) + 1
KEY_ROLE = ITEM_ROLE + 1
PENDING_ROLE = ITEM_ROLE + 2

STOCKER_MIME = "application/x-stocker-items"


class ThumbnailModel(QAbstractListModel):
    """Holds FileItems for the currently-active folder root."""

    request_thumbnail = Signal(object, object)  # ThumbKey, abs_path

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[FileItem] = []
        self._root: Path | None = None
        self._target_size: int = 192
        self._sort_key: str = "name"
        self._sort_dir: str = "asc"
        # pixmaps come from the cache which is owned by MainWindow
        self._cache_get = None  # callable(ThumbKey) -> QPixmap | None

    # ---- configuration ----

    def set_root(self, root: Path | None) -> None:
        self._root = root

    def set_cache_lookup(self, fn) -> None:
        self._cache_get = fn

    def set_target_size(self, size: int) -> None:
        if size <= 0 or size == self._target_size:
            return
        self._target_size = size
        if self._items:
            top = self.index(0)
            bot = self.index(len(self._items) - 1)
            self.dataChanged.emit(top, bot, [Qt.ItemDataRole.DecorationRole])

    @property
    def target_size(self) -> int:
        return self._target_size

    @property
    def root(self) -> Path | None:
        return self._root

    # ---- data ----

    def replace(self, items: list[FileItem]) -> None:
        self.beginResetModel()
        self._items = list(items)
        self.endResetModel()

    def clear(self) -> None:
        self.replace([])

    def add_pending(self, pending: PendingPaste) -> None:
        item = FileItem(
            rel_path=f"<pending:{pending.pid}>",
            name=pending.suggested_name,
            ext=".png",
            size_bytes=0,
            mtime_ns=pending.timestamp_ns,
            added_at=int(pending.timestamp_ns / 1_000_000_000),
            kind=FileKind.PENDING,
            pending_id=pending.pid,
        )
        # Pending items go to the top so users see them appear immediately.
        self.beginInsertRows(QModelIndex(), 0, 0)
        self._items.insert(0, item)
        self.endInsertRows()

    def replace_pending_with_real(self, pending_id: int, real: FileItem) -> bool:
        for i, it in enumerate(self._items):
            if it.kind is FileKind.PENDING and it.pending_id == pending_id:
                self._items[i] = real
                idx = self.index(i)
                self.dataChanged.emit(idx, idx)
                return True
        # Pending was already removed (e.g. resort or fs-watcher already added).
        # Only append if the file isn't already represented as a disk row.
        self.append_item(real)
        return False

    def remove_pending(self, pending_id: int) -> bool:
        for i, it in enumerate(self._items):
            if it.kind is FileKind.PENDING and it.pending_id == pending_id:
                self.beginRemoveRows(QModelIndex(), i, i)
                self._items.pop(i)
                self.endRemoveRows()
                return True
        return False

    def append_item(self, item: FileItem) -> bool:
        """Append a disk item to the end. Returns False (no-op) if a row with the
        same rel_path is already present, preventing duplicate thumbnails when
        the FS watcher races with paste completion."""
        if item.kind is FileKind.DISK:
            for existing in self._items:
                if existing.kind is FileKind.DISK and existing.rel_path == item.rel_path:
                    return False
        n = len(self._items)
        self.beginInsertRows(QModelIndex(), n, n)
        self._items.append(item)
        self.endInsertRows()
        return True

    def has_rel_path(self, rel_path: str) -> bool:
        return any(
            it.kind is FileKind.DISK and it.rel_path == rel_path for it in self._items
        )

    def remove_by_rels(self, rels: Iterable[str]) -> int:
        targets = set(rels)
        removed = 0
        i = 0
        while i < len(self._items):
            if self._items[i].rel_path in targets:
                self.beginRemoveRows(QModelIndex(), i, i)
                self._items.pop(i)
                self.endRemoveRows()
                removed += 1
            else:
                i += 1
        return removed

    def update_item(self, rel_path: str, new: FileItem) -> bool:
        for i, it in enumerate(self._items):
            if it.rel_path == rel_path:
                self._items[i] = new
                idx = self.index(i)
                self.dataChanged.emit(idx, idx)
                return True
        return False

    def item_at(self, row: int) -> FileItem | None:
        return self._items[row] if 0 <= row < len(self._items) else None

    def items(self) -> list[FileItem]:
        return list(self._items)

    # ---- QAbstractListModel ----

    def rowCount(self, parent=QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._items)

    def data(self, index: QModelIndex, role: int = int(Qt.ItemDataRole.DisplayRole)) -> Any:
        if not index.isValid():
            return None
        item = self._items[index.row()]
        if role == int(Qt.ItemDataRole.DisplayRole):
            return item.name
        if role == int(Qt.ItemDataRole.EditRole):
            return item.name
        if role == int(Qt.ItemDataRole.ToolTipRole):
            return item.name
        if role == int(Qt.ItemDataRole.SizeHintRole):
            s = self._target_size + 32  # extra room for label
            return QSize(self._target_size + 16, s)
        if role == int(Qt.ItemDataRole.DecorationRole):
            return self._pixmap_for(item)
        if role == ITEM_ROLE:
            return item
        if role == KEY_ROLE:
            return self._key_for(item)
        if role == PENDING_ROLE:
            return item.kind is FileKind.PENDING
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        base = super().flags(index)
        if index.isValid():
            item = self._items[index.row()]
            base |= Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled
            if item.kind is FileKind.DISK:
                base |= Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsDragEnabled
        return base

    def setData(self, index: QModelIndex, value: Any, role: int = int(Qt.ItemDataRole.EditRole)) -> bool:
        # Rename is performed by RenameService; the view captures the new value
        # from the editor and then drives update_item() after success.
        del index, value, role
        return False

    # ---- D&D source/sink ----

    def supportedDragActions(self) -> Qt.DropAction:
        return Qt.DropAction.CopyAction | Qt.DropAction.MoveAction

    def supportedDropActions(self) -> Qt.DropAction:
        return Qt.DropAction.CopyAction | Qt.DropAction.MoveAction

    def canDropMimeData(self, data, action, row, column, parent) -> bool:
        # The view-level dropEvent override does the real work; this just lets
        # Qt's drag machinery (highlight, dropEvent dispatch) accept the event.
        return data.hasUrls() or data.hasFormat(STOCKER_MIME)

    def mimeTypes(self) -> list[str]:
        return ["text/uri-list", STOCKER_MIME]

    def mimeData(self, indexes: list[QModelIndex]) -> QMimeData:
        mime = QMimeData()
        if self._root is None:
            return mime
        urls: list[QUrl] = []
        items: list[dict] = []
        seen_rows: set[int] = set()
        for idx in indexes:
            if not idx.isValid() or idx.row() in seen_rows:
                continue
            seen_rows.add(idx.row())
            it = self._items[idx.row()]
            if it.kind is not FileKind.DISK:
                continue
            abs_path = from_rel(self._root, it.rel_path)
            urls.append(QUrl.fromLocalFile(str(abs_path)))
            items.append({"root": str(self._root), "rel": it.rel_path})
        mime.setUrls(urls)
        if items:
            mime.setData(STOCKER_MIME, json.dumps(items, ensure_ascii=False).encode("utf-8"))
        return mime

    # ---- helpers ----

    def _key_for(self, item: FileItem) -> ThumbKey | None:
        if item.kind is not FileKind.DISK:
            return None
        return ThumbKey(rel_path=item.rel_path, mtime_ns=item.mtime_ns, target_size=self._target_size)

    def _pixmap_for(self, item: FileItem) -> QPixmap | None:
        if self._cache_get is None or self._root is None:
            return None
        if item.kind is FileKind.PENDING:
            # PENDING items render as a placeholder + badge in the delegate.
            return None
        key = self._key_for(item)
        if key is None:
            return None
        pm = self._cache_get(key)
        if pm is None:
            self.request_thumbnail.emit(key, from_rel(self._root, item.rel_path))
            return None
        return pm
