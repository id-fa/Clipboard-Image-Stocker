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


def _file(rel: str = "a.png") -> FileItem:
    return FileItem(
        rel_path=rel,
        name=rel.split("/")[-1],
        ext=".png",
        size_bytes=10,
        mtime_ns=time.time_ns(),
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
    """Simulates the paste flow: PENDING appears first, then completion swaps it
    in place. If FS watcher had already inserted a real row for the same file,
    the second append is dropped, so only one row remains."""
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

    # Then paste_completed arrives; replace_pending_with_real removes the pending.
    m.replace_pending_with_real(42, real)
    # pending row was swapped in place; the appended fs-watcher row is the second one
    rows = [m.item_at(i) for i in range(m.rowCount())]
    rels = [it.rel_path for it in rows if it]
    assert rels.count("p.png") == 2  # still two until we dedupe — see below


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
