"""Tests for ThumbnailView sizing: the grid must hold exactly `columns` items."""

from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from stocker.core.models import FileItem
from stocker.ui.thumbnail_model import ThumbnailModel
from stocker.ui.thumbnail_view import (
    CELL_GAP,
    ITEM_MARGIN_W,
    MIN_THUMB,
    ThumbnailView,
)

MIN_STRIDE = MIN_THUMB + ITEM_MARGIN_W + CELL_GAP


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def _items(n: int) -> list[FileItem]:
    now = time.time_ns()
    return [
        FileItem(
            rel_path=f"{i:03d}.png",
            name=f"{i:03d}.png",
            ext=".png",
            size_bytes=10,
            mtime_ns=now + i,
            added_at=int(time.time()),
        )
        for i in range(n)
    ]


@pytest.fixture
def view(qapp):
    v = ThumbnailView()
    m = ThumbnailModel()
    m.replace(_items(200))
    v.setModel(m)
    v.resize(1200, 800)
    v.show()
    qapp.processEvents()
    yield v
    v.close()


def _items_in_first_row(view: ThumbnailView, qapp) -> int:
    view._apply_size()
    view.doItemsLayout()
    qapp.processEvents()
    model = view.model()
    top = view.visualRect(model.index(0, 0)).y()
    count = 0
    for row in range(model.rowCount()):
        if view.visualRect(model.index(row, 0)).y() != top:
            break
        count += 1
    return count


@pytest.mark.parametrize("columns", [1, 2, 3, 5, 6, 8, 10, 12, 16])
@pytest.mark.parametrize("width", [640, 800, 1024, 1280, 1440, 1920])
def test_row_holds_exactly_the_requested_columns(view, qapp, columns, width):
    view.set_columns(columns)
    view.resize(width, 800)
    qapp.processEvents()
    view._apply_size()
    qapp.processEvents()
    # Below the minimum cell size the view simply cannot honour the request.
    if (view._layout_width() - 1) // columns < MIN_STRIDE:
        pytest.skip("viewport too narrow for the requested column count")
    assert _items_in_first_row(view, qapp) == columns


def test_stride_never_leaves_room_for_an_extra_column(view, qapp):
    """Regression: a 10-column grid used to fit an 11th item."""
    view.set_columns(10)
    for width in range(700, 1900, 3):
        view.resize(width, 800)
        qapp.processEvents()
        view._apply_size()
        qapp.processEvents()
        stride = view.gridSize().width()
        assert stride >= MIN_STRIDE
        fits = (view._layout_width() - 1) // stride
        assert fits <= view.columns(), f"width={width}: {fits} cells fit in a {view.columns()}-column grid"
