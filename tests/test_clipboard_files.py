"""Tests for clipboard helpers (file URLs + image)."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from stocker.utils.clipboard_files import (
    PREFERRED_DROP_EFFECT_MIME,
    copy_files_to_clipboard,
    copy_image_to_clipboard,
    file_urls_from_clipboard,
)


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def test_copy_files_roundtrip(qapp, tmp_path: Path):
    a = tmp_path / "a.png"; a.write_bytes(b"a")
    b = tmp_path / "日本語🖼.png"; b.write_bytes(b"jp")
    copy_files_to_clipboard([a, b])
    out = file_urls_from_clipboard()
    out_names = sorted(p.name for p in out)
    assert out_names == sorted([a.name, b.name])

    # Preferred DropEffect = COPY (5 in DWORD little-endian)
    mime = QApplication.clipboard().mimeData()
    assert mime is not None
    assert mime.hasFormat(PREFERRED_DROP_EFFECT_MIME)
    raw = bytes(mime.data(PREFERRED_DROP_EFFECT_MIME))
    assert raw == b"\x05\x00\x00\x00"


def test_copy_files_move_flag(qapp, tmp_path: Path):
    a = tmp_path / "a.png"; a.write_bytes(b"a")
    copy_files_to_clipboard([a], move=True)
    raw = bytes(QApplication.clipboard().mimeData().data(PREFERRED_DROP_EFFECT_MIME))
    # DROPEFFECT_MOVE = 2
    assert raw == b"\x02\x00\x00\x00"


def test_copy_image_to_clipboard(qapp):
    qimg = QImage(8, 8, QImage.Format.Format_RGB888)
    qimg.fill(0x00FF00)
    assert copy_image_to_clipboard(qimg) is True
    cb_img = QApplication.clipboard().image()
    assert not cb_img.isNull()
    assert cb_img.size() == qimg.size()


def test_copy_image_rejects_null(qapp):
    assert copy_image_to_clipboard(QImage()) is False


def test_file_urls_when_clipboard_has_only_image(qapp):
    qimg = QImage(4, 4, QImage.Format.Format_RGB888); qimg.fill(0)
    QApplication.clipboard().setImage(qimg)
    # Image-only clipboard — no file URLs.
    assert file_urls_from_clipboard() == []
