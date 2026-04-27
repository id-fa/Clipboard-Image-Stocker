"""Tests for PasteQueue: order, throughput, no losses on rapid enqueue."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEventLoop
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from stocker.core.paste_queue import PasteQueue


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def queue(qapp, tmp_path: Path):
    p = PasteQueue()
    p.set_target_root(tmp_path)
    p.start()
    yield p
    p.stop(timeout_ms=5000)


def _make_qimage(color: int = 0xFF0000) -> QImage:
    img = QImage(8, 8, QImage.Format.Format_RGB888)
    img.fill(color)
    return img


def _wait_until(predicate, timeout_s: float = 5.0, interval_ms: int = 10):
    """Pump the Qt event loop until predicate() is True or timeout."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, interval_ms)
        if predicate():
            return True
    return False


def test_enqueue_single(queue, tmp_path: Path):
    completed: list[tuple] = []
    queue.paste_completed.connect(lambda pid, item: completed.append((pid, item)))

    pending = queue.enqueue(_make_qimage())
    assert pending is not None

    assert _wait_until(lambda: len(completed) == 1)
    pid, item = completed[0]
    assert item.rel_path.endswith(".png")
    assert (tmp_path / item.rel_path).exists()


def test_rapid_burst_no_losses(queue, tmp_path: Path):
    completed: list[int] = []
    failed: list[int] = []
    queue.paste_completed.connect(lambda pid, item: completed.append(pid))
    queue.paste_failed.connect(lambda pid, err: failed.append(pid))

    BURST = 30
    pids: list[int] = []
    for _ in range(BURST):
        p = queue.enqueue(_make_qimage())
        assert p is not None
        pids.append(p.pid)

    # All enqueued IDs should be sequential and unique
    assert len(set(pids)) == BURST
    assert pids == sorted(pids)

    assert _wait_until(lambda: len(completed) + len(failed) == BURST, timeout_s=15)
    assert len(failed) == 0
    assert sorted(completed) == sorted(pids)
    saved = list(tmp_path.glob("paste_*.png"))
    assert len(saved) == BURST


def test_pending_added_fires_before_completion(queue):
    pendings: list[int] = []
    completed: list[int] = []
    queue.pending_added.connect(lambda p: pendings.append(p.pid))
    queue.paste_completed.connect(lambda pid, _it: completed.append(pid))

    queue.enqueue(_make_qimage())
    queue.enqueue(_make_qimage())

    # pending_added is emitted synchronously from enqueue()
    assert len(pendings) == 2
    assert _wait_until(lambda: len(completed) == 2)


def test_collision_renames_with_suffix(queue, tmp_path: Path):
    """Two pastes that would collide get unique filenames."""
    completed: list[str] = []
    queue.paste_completed.connect(lambda pid, item: completed.append(item.name))

    queue.enqueue(_make_qimage(0xFF0000))
    queue.enqueue(_make_qimage(0x00FF00))

    assert _wait_until(lambda: len(completed) == 2)
    assert len(set(completed)) == 2  # distinct filenames
