"""Workspace tree sidebar.

Shows the workspace root, every nested subfolder, and a special trash node.
Drop targets light up with an orange highlight while the cursor hovers them.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QModelIndex, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QTreeView

from stocker.app_paths import TRASH_DIRNAME
from stocker.i18n import tr

log = logging.getLogger(__name__)

PATH_ROLE = int(Qt.ItemDataRole.UserRole) + 1
KIND_ROLE = int(Qt.ItemDataRole.UserRole) + 2  # "workspace" | "folder" | "trash"
ORIGINAL_BG_ROLE = int(Qt.ItemDataRole.UserRole) + 3

DROP_HIGHLIGHT_BRUSH = QBrush(QColor(255, 165, 0, 180))


class Sidebar(QTreeView):
    folder_selected = Signal(object)  # Path
    trash_selected = Signal()
    create_subfolder_requested = Signal(object)  # parent Path | None
    rename_folder_requested = Signal(object)  # Path of the folder to rename
    delete_folder_requested = Signal(object)  # Path of the folder to delete
    # mode_str: "move" (default) or "copy" — set when Ctrl is held during the drop.
    drop_stocker_items_to_folder = Signal(object, bytes, str)
    drop_external_files_to_folder = Signal(object, list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._model = QStandardItemModel(self)
        self._model.setHorizontalHeaderLabels([tr("sidebar.header")])
        self.setModel(self._model)
        self.setHeaderHidden(True)
        self.setEditTriggers(QTreeView.EditTrigger.NoEditTriggers)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setExpandsOnDoubleClick(True)
        self._highlighted_idx: QModelIndex = QModelIndex()
        self.clicked.connect(self._on_clicked)

    # ---- public ----

    def populate(self, workspace: Path | None, folders: list[Path], trash_count: int = 0) -> None:
        self._model.removeRows(0, self._model.rowCount())
        self._highlighted_idx = QModelIndex()
        if workspace is None:
            return
        ws_item = QStandardItem(workspace.name or str(workspace))
        ws_item.setData(str(workspace), PATH_ROLE)
        ws_item.setData("workspace", KIND_ROLE)
        ws_item.setEditable(False)
        ws_item.setToolTip(str(workspace))
        ws_font = QFont(ws_item.font())
        ws_font.setBold(True)
        ws_item.setFont(ws_font)
        self._model.appendRow(ws_item)

        item_map: dict[Path, QStandardItem] = {workspace.resolve(): ws_item}
        for f in folders:
            f_resolved = f.resolve()
            if f_resolved == workspace.resolve():
                continue
            parent_path = f_resolved.parent
            parent_item = item_map.get(parent_path, ws_item)
            it = QStandardItem(f.name)
            it.setData(str(f_resolved), PATH_ROLE)
            it.setData("folder", KIND_ROLE)
            it.setEditable(False)
            it.setToolTip(str(f_resolved))
            parent_item.appendRow(it)
            item_map[f_resolved] = it

        # Trash node — sibling of workspace root, last
        trash_item = QStandardItem(self._trash_label(trash_count))
        trash_item.setData(str(workspace / TRASH_DIRNAME), PATH_ROLE)
        trash_item.setData("trash", KIND_ROLE)
        trash_item.setEditable(False)
        trash_item.setToolTip(tr("sidebar.trash_tooltip"))
        self._model.appendRow(trash_item)

        self.expandAll()

    def update_trash_count(self, count: int) -> None:
        for r in range(self._model.rowCount()):
            it = self._model.item(r)
            if it and it.data(KIND_ROLE) == "trash":
                it.setText(self._trash_label(count))
                return

    def _trash_label(self, count: int) -> str:
        return tr("sidebar.trash_with_count", n=count) if count else tr("sidebar.trash")

    def select_path(self, path: Path) -> None:
        target = str(path.resolve())
        idx = self._find_index_by_path(target)
        if idx.isValid():
            self.setCurrentIndex(idx)

    def set_font_size(self, points: int) -> None:
        f = QFont(self.font())
        f.setPointSize(max(6, min(48, points)))
        self.setFont(f)
        # Force a relayout / re-render
        self.viewport().update()

    # ---- selection ----

    def _on_clicked(self, idx: QModelIndex) -> None:
        kind = idx.data(KIND_ROLE)
        path_str = idx.data(PATH_ROLE)
        if kind == "trash":
            self.trash_selected.emit()
        elif path_str:
            self.folder_selected.emit(Path(path_str))

    def contextMenuEvent(self, e):
        idx = self.indexAt(e.pos())
        if not idx.isValid():
            return
        from PySide6.QtWidgets import QMenu
        kind = idx.data(KIND_ROLE)
        path_str = idx.data(PATH_ROLE)
        menu = QMenu(self)
        if kind in ("workspace", "folder") and path_str:
            menu.addAction(
                tr("sidebar.menu_create_subfolder"),
                lambda: self.create_subfolder_requested.emit(Path(path_str)),
            )
        if kind == "folder" and path_str:
            menu.addAction(
                tr("sidebar.menu_rename_folder"),
                lambda: self.rename_folder_requested.emit(Path(path_str)),
            )
            menu.addSeparator()
            menu.addAction(
                tr("sidebar.menu_delete_folder"),
                lambda: self.delete_folder_requested.emit(Path(path_str)),
            )
        menu.exec(e.globalPos())

    # ---- helpers ----

    def _find_index_by_path(self, path_str: str) -> QModelIndex:
        # Walk the model
        stack = [self._model.index(r, 0) for r in range(self._model.rowCount())]
        while stack:
            idx = stack.pop()
            if idx.data(PATH_ROLE) == path_str:
                return idx
            for r in range(self._model.rowCount(idx)):
                stack.append(self._model.index(r, 0, idx))
        return QModelIndex()

    # ---- D&D ----

    def dragEnterEvent(self, e):
        mime = e.mimeData()
        if mime.hasFormat("application/x-stocker-items") or mime.hasUrls():
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        mime = e.mimeData()
        if not (mime.hasFormat("application/x-stocker-items") or mime.hasUrls()):
            super().dragMoveEvent(e)
            return
        idx = self.indexAt(e.position().toPoint())
        kind = idx.data(KIND_ROLE) if idx.isValid() else None
        accept = kind in ("workspace", "folder", "trash")
        self._highlight(idx if accept else QModelIndex())
        if accept:
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragLeaveEvent(self, e):
        self._highlight(QModelIndex())
        super().dragLeaveEvent(e)

    def dropEvent(self, e):
        self._highlight(QModelIndex())
        idx = self.indexAt(e.position().toPoint())
        path_str = idx.data(PATH_ROLE) if idx.isValid() else None
        if not path_str:
            e.ignore()
            return
        target = Path(path_str)
        mime = e.mimeData()
        # Ctrl held during drop = COPY semantics; default = MOVE.
        modifiers = e.modifiers() if hasattr(e, "modifiers") else None
        if modifiers is None:
            from PySide6.QtWidgets import QApplication
            modifiers = QApplication.keyboardModifiers()
        mode_str = "copy" if modifiers & Qt.KeyboardModifier.ControlModifier else "move"
        if mime.hasFormat("application/x-stocker-items"):
            payload = bytes(mime.data("application/x-stocker-items"))
            self.drop_stocker_items_to_folder.emit(target, payload, mode_str)
            e.acceptProposedAction()
            return
        if mime.hasUrls():
            urls = [u.toLocalFile() for u in mime.urls() if u.isLocalFile()]
            urls = [u for u in urls if u]
            if urls:
                self.drop_external_files_to_folder.emit(target, urls)
                e.acceptProposedAction()
                return
        super().dropEvent(e)

    def _highlight(self, idx: QModelIndex) -> None:
        """Paint the row under the drag cursor with a high-contrast background."""
        if self._highlighted_idx == idx:
            return
        # Restore previous
        if self._highlighted_idx.isValid():
            old_item = self._model.itemFromIndex(self._highlighted_idx)
            if old_item is not None:
                original = old_item.data(ORIGINAL_BG_ROLE)
                if isinstance(original, QBrush):
                    old_item.setBackground(original)
                else:
                    old_item.setData(None, int(Qt.ItemDataRole.BackgroundRole))
                old_item.setData(None, ORIGINAL_BG_ROLE)
        # Apply new
        if idx.isValid():
            new_item = self._model.itemFromIndex(idx)
            if new_item is not None:
                new_item.setData(new_item.background(), ORIGINAL_BG_ROLE)
                new_item.setBackground(DROP_HIGHLIGHT_BRUSH)
        self._highlighted_idx = idx
