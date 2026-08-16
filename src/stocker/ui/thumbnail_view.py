"""Custom QListView for the thumbnail grid: column-driven sizing + DnD."""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QDrag, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QListView

from stocker.ui.thumbnail_model import ITEM_ROLE
from stocker.utils.debounce import Debouncer

log = logging.getLogger(__name__)

MIN_COLUMNS = 1
MAX_COLUMNS = 16
# Hover preview only triggers when the cursor enters this fraction of the item
# rect, anchored at the bottom-right. 0.4 means a ~16%-area corner trigger.
HOVER_CORNER_FRAC = 0.4

# Item sizeHint = (thumb_w + ITEM_MARGIN_W, thumb_h + ITEM_MARGIN_H); the grid
# stride adds CELL_GAP on top so neighbouring cells do not touch.
ITEM_MARGIN_W = 16
ITEM_MARGIN_H = 32
CELL_GAP = 4
MIN_THUMB = 48

ASPECT_RATIOS: dict[str, tuple[int, int]] = {
    "1:1": (1, 1),
    "4:3": (4, 3),
    "16:9": (16, 9),
    "3:4": (3, 4),
    "9:16": (9, 16),
}
DEFAULT_ASPECT = "1:1"


class ThumbnailView(QListView):
    item_double_clicked = Signal(object)  # FileItem
    hover_changed = Signal(object)  # FileItem | None
    drop_files = Signal(list)  # list[str] (URLs from external D&D)
    drop_stocker_items = Signal(bytes)  # raw payload of application/x-stocker-items

    def __init__(self, parent=None):
        super().__init__(parent)
        self._columns = 6
        self._aspect_w, self._aspect_h = ASPECT_RATIOS[DEFAULT_ASPECT]
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setMovement(QListView.Movement.Static)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setUniformItemSizes(True)
        self.setLayoutMode(QListView.LayoutMode.Batched)
        self.setBatchSize(100)
        self.setSpacing(2)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        # Default DragDropMode in IconMode is "InternalMove" which silently rejects
        # external sources. We need DragDrop for both directions to work.
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setDropIndicatorShown(False)
        self.setMouseTracking(True)
        self.setEditTriggers(QAbstractItemView.EditTrigger.EditKeyPressed)

        self._resize_debounce = Debouncer(50, self._apply_size)
        self._hover_idx_row: int = -1
        self._hover_emitter: Callable[[], None] | None = None

        self.doubleClicked.connect(self._on_double_clicked)

    # ---- column / size ----

    def set_columns(self, n: int) -> None:
        n = max(MIN_COLUMNS, min(MAX_COLUMNS, n))
        if n == self._columns:
            return
        self._columns = n
        self._apply_size()

    def columns(self) -> int:
        return self._columns

    def set_aspect(self, ratio: str) -> None:
        """Pick a thumbnail cell aspect from ASPECT_RATIOS. Unknown values are ignored."""
        if ratio not in ASPECT_RATIOS:
            return
        aw, ah = ASPECT_RATIOS[ratio]
        if (aw, ah) == (self._aspect_w, self._aspect_h):
            return
        self._aspect_w, self._aspect_h = aw, ah
        self._apply_size()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._resize_debounce.call()

    def _layout_width(self) -> int:
        """Viewport width with the vertical scrollbar always accounted for.

        The bar appearing/disappearing changes the viewport width, which would
        otherwise flip the computed stride by one pixel and cost (or add) a column.
        Reserving its width even while it is hidden keeps the value stable across
        both states.
        """
        w = self.viewport().width()
        sb = self.verticalScrollBar()
        if sb is not None and not sb.isVisible():
            w -= max(0, sb.sizeHint().width())
        return w

    def _apply_size(self) -> None:
        # With an explicit grid Qt fits `(viewport_w - 1) // grid_w` items per row
        # (spacing does not enter the equation; a cell that exactly reaches the right
        # edge already wraps), so the stride is that division inverted. The old
        # formula subtracted a padding term from the stride instead, leaving enough
        # slack for an 11th item to slip into a 10-column row.
        viewport_w = max(1, self._layout_width())
        stride_w = max(MIN_THUMB + ITEM_MARGIN_W + CELL_GAP,
                       (viewport_w - 1) // self._columns)
        thumb_w = max(MIN_THUMB, stride_w - ITEM_MARGIN_W - CELL_GAP)
        thumb_h = max(MIN_THUMB, int(round(thumb_w * self._aspect_h / self._aspect_w)))
        model = self.model()
        if model is not None and hasattr(model, "set_cell_size"):
            model.set_cell_size(thumb_w, thumb_h)
        # Pin the layout to an explicit grid: relying on sizeHint + spacing lets Qt
        # derive the column count itself, which drifts from the requested value.
        self.setGridSize(QSize(stride_w, thumb_h + ITEM_MARGIN_H + CELL_GAP))
        # Trigger layout refresh
        self.scheduleDelayedItemsLayout()

    # ---- hover -> only fire when cursor is in the bottom-right corner ----

    def _corner_rect(self, idx) -> QRect:
        rect = self.visualRect(idx)
        if not rect.isValid() or rect.width() <= 0 or rect.height() <= 0:
            return QRect()
        cw = max(16, int(rect.width() * HOVER_CORNER_FRAC))
        ch = max(16, int(rect.height() * HOVER_CORNER_FRAC))
        return QRect(rect.right() - cw + 1, rect.bottom() - ch + 1, cw, ch)

    def mouseMoveEvent(self, e) -> None:
        super().mouseMoveEvent(e)
        pos = e.pos()
        idx = self.indexAt(pos)
        if not idx.isValid() or not self._corner_rect(idx).contains(pos):
            if self._hover_idx_row != -1:
                self._hover_idx_row = -1
                self.hover_changed.emit(None)
            return
        if idx.row() == self._hover_idx_row:
            return
        self._hover_idx_row = idx.row()
        item = idx.data(ITEM_ROLE)
        self.hover_changed.emit(item)

    def leaveEvent(self, e) -> None:
        self._hover_idx_row = -1
        self.hover_changed.emit(None)
        super().leaveEvent(e)

    # ---- double-click ----

    def _on_double_clicked(self, idx) -> None:
        item = idx.data(ITEM_ROLE)
        if item is not None:
            self.item_double_clicked.emit(item)

    # ---- D&D receive ----

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() or e.mimeData().hasFormat("application/x-stocker-items"):
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls() or e.mimeData().hasFormat("application/x-stocker-items"):
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):
        # Avoid handling our own internal drag (would copy to itself)
        if e.source() is self:
            e.ignore()
            return
        mime = e.mimeData()
        if mime.hasFormat("application/x-stocker-items"):
            self.drop_stocker_items.emit(bytes(mime.data("application/x-stocker-items")))
            e.acceptProposedAction()
            return
        if mime.hasUrls():
            urls = [u.toLocalFile() for u in mime.urls() if u.isLocalFile()]
            urls = [u for u in urls if u]
            if urls:
                self.drop_files.emit(urls)
                e.acceptProposedAction()
                return
        super().dropEvent(e)

    # ---- D&D source override: include drag pixmap ----

    def startDrag(self, supported_actions):
        sel = self.selectionModel().selectedIndexes() if self.selectionModel() else []
        if not sel:
            return
        model = self.model()
        if model is None or not hasattr(model, "mimeData"):
            return
        mime = model.mimeData(sel)
        drag = QDrag(self)
        drag.setMimeData(mime)
        first_pm = sel[0].data(int(Qt.ItemDataRole.DecorationRole))
        if isinstance(first_pm, QPixmap) and not first_pm.isNull():
            badge = first_pm.scaled(96, 96, Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation)
            drag.setPixmap(badge)
            drag.setHotSpot(QPoint(badge.width() // 2, badge.height() // 2))
        drag.exec(supported_actions, Qt.DropAction.CopyAction)
