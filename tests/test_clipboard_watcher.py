"""Tests for ClipboardWatcher: fingerprint dedup and auto-capture toggle."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEventLoop
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from stocker.core.clipboard_watcher import ClipboardWatcher, _fingerprint
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


def _img(color: int, w: int = 8, h: int = 8) -> QImage:
    img = QImage(w, h, QImage.Format.Format_RGB888)
    img.fill(color)
    return img


def _wait_until(predicate, timeout_s: float = 3.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 10)
        if predicate():
            return True
    return False


def test_fingerprint_distinguishes_different_images():
    a = _img(0xFF0000)
    b = _img(0x00FF00)
    assert _fingerprint(a) != _fingerprint(b)


def test_fingerprint_same_for_identical_content():
    a = _img(0xFF0000)
    b = _img(0xFF0000)
    assert _fingerprint(a) == _fingerprint(b)


def test_fingerprint_handles_null():
    assert _fingerprint(QImage()) is None


def test_autocapture_off_ignores_clipboard(queue, qapp):
    watcher = ClipboardWatcher(queue)
    completed: list = []
    queue.paste_completed.connect(lambda pid, item: completed.append(item))

    QApplication.clipboard().setImage(_img(0xFF0000))
    # Pump events; nothing should be enqueued because autocapture is off
    _wait_until(lambda: False, timeout_s=0.3)
    assert completed == []


def test_autocapture_on_imports_new_image(queue, qapp, tmp_path: Path):
    watcher = ClipboardWatcher(queue)
    watcher.set_autocapture(True)
    completed: list = []
    queue.paste_completed.connect(lambda pid, item: completed.append(item))

    QApplication.clipboard().setImage(_img(0x123456))
    assert _wait_until(lambda: len(completed) == 1)
    assert (tmp_path / completed[0].rel_path).exists()


def test_autocapture_dedupes_identical_payload(queue, qapp):
    watcher = ClipboardWatcher(queue)
    watcher.set_autocapture(True)
    completed: list = []
    queue.paste_completed.connect(lambda pid, item: completed.append(item))

    img = _img(0xABCDEF)
    QApplication.clipboard().setImage(img)
    assert _wait_until(lambda: len(completed) == 1)

    # Setting the same image again should NOT trigger another save.
    QApplication.clipboard().setImage(_img(0xABCDEF))
    _wait_until(lambda: len(completed) >= 2, timeout_s=0.4)
    assert len(completed) == 1


def test_autocapture_captures_distinct_consecutive_images(queue, qapp):
    watcher = ClipboardWatcher(queue)
    watcher.set_autocapture(True)
    completed: list = []
    queue.paste_completed.connect(lambda pid, item: completed.append(item))

    QApplication.clipboard().setImage(_img(0x111111))
    assert _wait_until(lambda: len(completed) == 1)
    QApplication.clipboard().setImage(_img(0x222222))
    assert _wait_until(lambda: len(completed) == 2)


def test_note_self_copy_suppresses_echo(queue, qapp):
    watcher = ClipboardWatcher(queue)
    watcher.set_autocapture(True)
    completed: list = []
    queue.paste_completed.connect(lambda pid, item: completed.append(item))

    img = _img(0x808080)
    watcher.note_self_copy(img)  # mark as ours BEFORE putting on clipboard
    QApplication.clipboard().setImage(img)
    _wait_until(lambda: len(completed) >= 1, timeout_s=0.4)
    assert completed == []


def test_set_autocapture_seeds_with_current_clipboard(queue, qapp):
    """Enabling autocapture must NOT re-import whatever was already on
    the clipboard at toggle time."""
    QApplication.clipboard().setImage(_img(0xCAFE00))
    # Drain the dataChanged from the setImage above
    _wait_until(lambda: False, timeout_s=0.1)

    watcher = ClipboardWatcher(queue)
    completed: list = []
    queue.paste_completed.connect(lambda pid, item: completed.append(item))
    watcher.set_autocapture(True)

    _wait_until(lambda: len(completed) >= 1, timeout_s=0.3)
    assert completed == []
