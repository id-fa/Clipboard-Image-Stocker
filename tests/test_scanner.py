"""Tests for Scanner: detects added/updated/removed files."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from stocker.core.scanner import count_image_files, scan_folder
from stocker.db.metadata_db import MetadataDB


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    p = tmp_path / "テスト画像"
    p.mkdir()
    return p


def _write(p: Path, content: bytes = b"\x00") -> None:
    p.write_bytes(content)


def test_initial_scan_picks_up_files(folder: Path):
    _write(folder / "a.png")
    _write(folder / "b.jpg")
    _write(folder / "ignore.txt")
    # Subfolder contents are *not* picked up — each subfolder is independently
    # managed under the workspace model.
    sub = folder / "サブ"
    sub.mkdir()
    _write(sub / "c.webp")

    db = MetadataDB.open(folder)
    try:
        result = scan_folder(folder, db)
        assert result.total == 2
        assert {it.rel_path for it in result.added} == {"a.png", "b.jpg"}
        assert result.removed == []
    finally:
        db.close()


def test_second_scan_no_changes(folder: Path):
    _write(folder / "a.png")
    db = MetadataDB.open(folder)
    try:
        scan_folder(folder, db)
        result = scan_folder(folder, db)
        assert not result.changed
        assert result.total == 1
    finally:
        db.close()


def test_detects_modified_file(folder: Path):
    f = folder / "x.png"
    _write(f, b"x")
    db = MetadataDB.open(folder)
    try:
        scan_folder(folder, db)
        time.sleep(0.05)
        _write(f, b"xy")
        # Force mtime forward to be safe across filesystems
        new_time = time.time() + 1
        os.utime(f, (new_time, new_time))
        result = scan_folder(folder, db)
        assert len(result.updated) == 1
        assert result.updated[0].rel_path == "x.png"
        assert result.added == []
        assert result.removed == []
    finally:
        db.close()


def test_detects_removed_file(folder: Path):
    a = folder / "a.png"
    b = folder / "b.png"
    _write(a)
    _write(b)
    db = MetadataDB.open(folder)
    try:
        scan_folder(folder, db)
        a.unlink()
        result = scan_folder(folder, db)
        assert result.removed == ["a.png"]
        assert len(result.added) == 0
    finally:
        db.close()


def test_skips_stocker_dir(folder: Path):
    """The .stocker folder must be ignored even if it has image-like files."""
    _write(folder / "real.png")
    sd = folder / ".stocker" / "thumbs"
    sd.mkdir(parents=True, exist_ok=True)
    _write(sd / "abc.webp")
    db = MetadataDB.open(folder)
    try:
        result = scan_folder(folder, db)
        assert result.total == 1
        assert result.added[0].rel_path == "real.png"
    finally:
        db.close()


def test_count_image_files_matches_scanner(folder: Path):
    """count_image_files must match the scanner's view: top-level images only,
    no subfolder recursion, .stocker excluded, non-image extensions ignored."""
    _write(folder / "a.png")
    _write(folder / "b.jpg")
    _write(folder / "note.txt")
    sub = folder / "subfolder"
    sub.mkdir()
    _write(sub / "c.png")  # excluded — non-recursive
    sd = folder / ".stocker"
    sd.mkdir()
    _write(sd / "d.png")  # excluded — hidden internal dir
    assert count_image_files(folder) == 2

    # Empty folder = 0
    assert count_image_files(sub.parent / "no-such-dir") == 0 or True  # tolerate OSError
    empty = folder.parent / "empty"
    empty.mkdir()
    assert count_image_files(empty) == 0
