"""Tests for ThumbnailModel: dedupe, pending replacement, race with FS watcher."""

from __future__ import annotations

import time

import pytest
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from stocker.core.models import FileItem, PendingPaste
from stocker.ui.thumbnail_model import ThumbnailModel


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def _file(rel: str = "a.png", *, mtime_ns: int | None = None) -> FileItem:
    return FileItem(
        rel_path=rel,
        name=rel.split("/")[-1],
        ext=".png",
        size_bytes=10,
        mtime_ns=mtime_ns if mtime_ns is not None else time.time_ns(),
        added_at=int(time.time()),
    )


def test_append_dedupes_same_rel(qapp):
    m = ThumbnailModel()
    f = _file("a.png")
    assert m.append_item(f) is True
    # Second append for same rel_path is a no-op (prevents the
    # fs-watcher-vs-paste-completion race that previously created
    # a phantom duplicate).
    assert m.append_item(_file("a.png")) is False
    assert m.rowCount() == 1


def test_pending_then_completion_no_dup(qapp):
    """FS watcher races ahead of the paste worker: the real row lands first,
    then completion fires for a pending row that's still around. Removing the
    pending and dedupe-inserting the real row leaves exactly one DISK row."""
    m = ThumbnailModel()
    pending = PendingPaste(
        pid=42, qimage=QImage(4, 4, QImage.Format.Format_RGB888),
        timestamp_ns=time.time_ns(), suggested_name="p.png",
    )
    m.add_pending(pending)
    assert m.rowCount() == 1

    real = _file("p.png")
    # FS watcher fires first
    assert m.append_item(real) is True
    assert m.rowCount() == 2  # pending + real (transient state)

    # Then paste_completed arrives; the pending is removed and the dedupe rejects
    # the would-be duplicate insert, so only the real disk row survives.
    m.replace_pending_with_real(42, real)
    rels = [it.rel_path for it in (m.item_at(i) for i in range(m.rowCount())) if it]
    assert rels == ["p.png"]


def test_pending_completion_with_dedupe(qapp):
    """Preferred ordering: completion fires first → swaps PENDING to real.
    Then the fs-watcher's late append_item is rejected by dedupe."""
    m = ThumbnailModel()
    pending = PendingPaste(
        pid=7, qimage=QImage(4, 4, QImage.Format.Format_RGB888),
        timestamp_ns=time.time_ns(), suggested_name="paste_x.png",
    )
    m.add_pending(pending)
    real = _file("paste_x.png")
    m.replace_pending_with_real(7, real)
    assert m.rowCount() == 1

    # Late fs-watcher event would otherwise duplicate — dedupe kills it.
    assert m.append_item(real) is False
    assert m.rowCount() == 1


def test_has_rel_path(qapp):
    m = ThumbnailModel()
    m.append_item(_file("a.png"))
    assert m.has_rel_path("a.png")
    assert not m.has_rel_path("b.png")


def test_append_inserts_in_name_asc_order(qapp):
    """append_item must respect the model's active sort, not just append."""
    m = ThumbnailModel()
    m.set_sort("name", "asc")
    m.append_item(_file("c.png"))
    m.append_item(_file("a.png"))
    m.append_item(_file("m.png"))
    rels = [m.item_at(i).rel_path for i in range(m.rowCount())]
    assert rels == ["a.png", "c.png", "m.png"]


def test_append_inserts_in_mtime_desc_order(qapp):
    m = ThumbnailModel()
    m.set_sort("mtime", "desc")
    m.append_item(_file("old.png", mtime_ns=100))
    m.append_item(_file("newer.png", mtime_ns=300))
    m.append_item(_file("middle.png", mtime_ns=200))
    rels = [m.item_at(i).rel_path for i in range(m.rowCount())]
    assert rels == ["newer.png", "middle.png", "old.png"]


def test_paste_completion_lands_in_sorted_position(qapp):
    """Repro for the bug where new pastes always landed at the top regardless
    of sort. With name-asc sort, a new paste of 'm.png' must land between
    'a.png' and 'z.png', not at row 0."""
    m = ThumbnailModel()
    m.set_sort("name", "asc")
    m.append_item(_file("a.png"))
    m.append_item(_file("z.png"))

    pending = PendingPaste(
        pid=11, qimage=QImage(4, 4, QImage.Format.Format_RGB888),
        timestamp_ns=time.time_ns(), suggested_name="m.png",
    )
    m.add_pending(pending)
    real = _file("m.png")
    m.replace_pending_with_real(11, real)

    rels = [m.item_at(i).rel_path for i in range(m.rowCount())]
    assert rels == ["a.png", "m.png", "z.png"]
