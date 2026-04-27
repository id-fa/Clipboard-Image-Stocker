"""Tests for MoveService: same/cross-volume move, collision, cross-DB consistency."""

from __future__ import annotations

from pathlib import Path

import pytest

from stocker.core.move_service import (
    MoveItemRef,
    MoveMode,
    parse_payload,
    perform_move,
)
from stocker.core.scanner import scan_folder
from stocker.core.thumbnail_cache import ThumbnailCache, disk_thumb_path
from stocker.db.metadata_db import MetadataDB


@pytest.fixture
def two_folders(tmp_path: Path):
    src = tmp_path / "src_管理フォルダ"
    dst = tmp_path / "dst_管理フォルダ"
    src.mkdir()
    dst.mkdir()
    return src, dst


def _seed_image(folder: Path, name: str, content: bytes = b"\x89PNG\r\n\x1a\n") -> Path:
    p = folder / name
    p.write_bytes(content)
    return p


def test_simple_move_one_file(two_folders):
    src, dst = two_folders
    _seed_image(src, "a.png")
    src_db = MetadataDB.open(src)
    dst_db = MetadataDB.open(dst)
    try:
        scan_folder(src, src_db)
        scan_folder(dst, dst_db)
        cache = ThumbnailCache()
        cache.configure(dst, 0)

        refs = [MoveItemRef(src_root=src, src_rel="a.png")]
        result = perform_move(refs, dst, db_for=lambda r: src_db if r.resolve() == src.resolve() else dst_db,
                              cache=cache, mode=MoveMode.MOVE)
        assert len(result.moved) == 1
        assert not result.failed
        assert not (src / "a.png").exists()
        assert (dst / "a.png").exists()
        assert src_db.get_by_rel("a.png") is None
        assert dst_db.get_by_rel("a.png") is not None
    finally:
        src_db.close()
        dst_db.close()


def test_collision_appends_suffix(two_folders):
    src, dst = two_folders
    _seed_image(src, "x.png", b"src")
    _seed_image(dst, "x.png", b"dst")
    src_db = MetadataDB.open(src)
    dst_db = MetadataDB.open(dst)
    try:
        scan_folder(src, src_db)
        scan_folder(dst, dst_db)
        cache = ThumbnailCache()
        cache.configure(dst, 0)
        refs = [MoveItemRef(src_root=src, src_rel="x.png")]
        result = perform_move(refs, dst,
                              db_for=lambda r: src_db if r.resolve() == src.resolve() else dst_db,
                              cache=cache, mode=MoveMode.MOVE)
        assert len(result.moved) == 1
        new_item = result.moved[0][1]
        assert new_item.name == "x (2).png"
        assert (dst / "x.png").read_bytes() == b"dst"  # original untouched
        assert (dst / "x (2).png").read_bytes() == b"src"
    finally:
        src_db.close()
        dst_db.close()


def test_disk_thumb_relocated(two_folders):
    src, dst = two_folders
    _seed_image(src, "p.png")
    # Pre-populate a fake WebP thumb in src/.stocker/thumbs as if cache had run.
    src_db = MetadataDB.open(src)
    dst_db = MetadataDB.open(dst)
    try:
        scan_folder(src, src_db)
        scan_folder(dst, dst_db)
        cache = ThumbnailCache()
        cache.configure(dst, 0)
        old_thumb = disk_thumb_path(src, "p.png", 192)
        old_thumb.parent.mkdir(parents=True, exist_ok=True)
        old_thumb.write_bytes(b"FAKE_WEBP")

        refs = [MoveItemRef(src_root=src, src_rel="p.png")]
        perform_move(refs, dst,
                     db_for=lambda r: src_db if r.resolve() == src.resolve() else dst_db,
                     cache=cache, mode=MoveMode.MOVE)

        new_thumb = disk_thumb_path(dst, "p.png", 192)
        assert not old_thumb.exists()
        assert new_thumb.exists()
        assert new_thumb.read_bytes() == b"FAKE_WEBP"
    finally:
        src_db.close()
        dst_db.close()


def test_missing_src_file_does_not_crash(two_folders):
    src, dst = two_folders
    src_db = MetadataDB.open(src)
    dst_db = MetadataDB.open(dst)
    try:
        cache = ThumbnailCache()
        cache.configure(dst, 0)
        refs = [MoveItemRef(src_root=src, src_rel="ghost.png")]
        result = perform_move(refs, dst,
                              db_for=lambda r: src_db if r.resolve() == src.resolve() else dst_db,
                              cache=cache, mode=MoveMode.MOVE)
        assert result.moved == []
        assert len(result.failed) == 1
    finally:
        src_db.close()
        dst_db.close()


def test_progress_callback_can_cancel(two_folders):
    src, dst = two_folders
    for i in range(5):
        _seed_image(src, f"f{i}.png")
    src_db = MetadataDB.open(src)
    dst_db = MetadataDB.open(dst)
    try:
        scan_folder(src, src_db)
        scan_folder(dst, dst_db)
        cache = ThumbnailCache()
        cache.configure(dst, 0)

        refs = [MoveItemRef(src_root=src, src_rel=f"f{i}.png") for i in range(5)]
        seen: list[int] = []

        def cb(done: int, total: int) -> bool:
            seen.append(done)
            return done < 2  # cancel after 2

        result = perform_move(refs, dst,
                              db_for=lambda r: src_db if r.resolve() == src.resolve() else dst_db,
                              cache=cache, mode=MoveMode.MOVE, progress_cb=cb)
        assert result.cancelled is True
        assert len(result.moved) == 2
        assert seen[-1] == 2
    finally:
        src_db.close()
        dst_db.close()


def test_parse_payload_roundtrip():
    payload = b'[{"root": "C:\\\\foo\\\\bar", "rel": "a/b.png"}, {"root": "D:\\\\x", "rel": "c.png"}]'
    refs = parse_payload(payload)
    assert len(refs) == 2
    assert refs[0].src_rel == "a/b.png"


def test_japanese_filename_move(two_folders):
    src, dst = two_folders
    _seed_image(src, "画像🖼.png")
    src_db = MetadataDB.open(src)
    dst_db = MetadataDB.open(dst)
    try:
        scan_folder(src, src_db)
        cache = ThumbnailCache()
        cache.configure(dst, 0)
        refs = [MoveItemRef(src_root=src, src_rel="画像🖼.png")]
        result = perform_move(refs, dst,
                              db_for=lambda r: src_db if r.resolve() == src.resolve() else dst_db,
                              cache=cache, mode=MoveMode.MOVE)
        assert len(result.moved) == 1
        assert (dst / "画像🖼.png").exists()
    finally:
        src_db.close()
        dst_db.close()
