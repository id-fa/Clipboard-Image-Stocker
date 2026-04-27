"""Tests for MetadataDB: schema, CRUD, sort, signature diff."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from stocker.core.models import FileItem
from stocker.db.metadata_db import MetadataDB


def _make_item(rel: str, mtime_ns: int = 1_000_000_000_000_000_000, size: int = 100) -> FileItem:
    return FileItem(
        rel_path=rel,
        name=Path(rel).name,
        ext=Path(rel).suffix.lower(),
        size_bytes=size,
        mtime_ns=mtime_ns,
        added_at=int(time.time()),
    )


@pytest.fixture
def db(tmp_path: Path) -> MetadataDB:
    folder = tmp_path / "テスト画像"  # Japanese path
    folder.mkdir()
    d = MetadataDB.open(folder)
    yield d
    d.close()


def test_schema_creates_tables(db: MetadataDB):
    rows = db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    names = [r["name"] for r in rows]
    assert "files" in names
    assert "settings" in names
    assert "scan_state" in names


def test_upsert_inserts_then_updates(db: MetadataDB):
    db.upsert_file(_make_item("a.png", mtime_ns=1, size=100))
    db.upsert_file(_make_item("a.png", mtime_ns=2, size=200))
    items = db.list_files()
    assert len(items) == 1
    assert items[0].mtime_ns == 2
    assert items[0].size_bytes == 200


def test_bulk_upsert_thousand(db: MetadataDB):
    items = [_make_item(f"img_{i:04d}.png", mtime_ns=i, size=10 * i) for i in range(1000)]
    n = db.bulk_upsert(items)
    assert n == 1000
    assert db.count_files() == 1000


def test_list_sorted_by_name_and_mtime(db: MetadataDB):
    db.upsert_file(_make_item("c.png", mtime_ns=100))
    db.upsert_file(_make_item("a.png", mtime_ns=300))
    db.upsert_file(_make_item("b.png", mtime_ns=200))

    by_name = [it.name for it in db.list_files("name", "asc")]
    assert by_name == ["a.png", "b.png", "c.png"]

    by_mtime_desc = [it.name for it in db.list_files("mtime", "desc")]
    assert by_mtime_desc == ["a.png", "b.png", "c.png"]


def test_rename_updates_keys(db: MetadataDB):
    db.upsert_file(_make_item("old.png"))
    ok = db.rename("old.png", "新しい名前.png", "新しい名前.png")
    assert ok
    assert db.get_by_rel("old.png") is None
    item = db.get_by_rel("新しい名前.png")
    assert item is not None and item.name == "新しい名前.png"


def test_get_signatures_for_diff(db: MetadataDB):
    db.upsert_file(_make_item("a.png", mtime_ns=10, size=11))
    db.upsert_file(_make_item("b.png", mtime_ns=20, size=22))
    sigs = db.get_signatures()
    assert sigs == {"a.png": (10, 11), "b.png": (20, 22)}


def test_settings_roundtrip(db: MetadataDB):
    db.set_setting("theme", "dark")
    assert db.get_setting("theme") == "dark"
    db.set_setting("theme", "light")
    assert db.get_setting("theme") == "light"


def test_japanese_filename_roundtrip(db: MetadataDB):
    db.upsert_file(_make_item("画像／🖼.png"))
    assert db.get_by_rel("画像／🖼.png") is not None


def test_bulk_delete(db: MetadataDB):
    db.upsert_file(_make_item("x.png"))
    db.upsert_file(_make_item("y.png"))
    db.upsert_file(_make_item("z.png"))
    n = db.bulk_delete(["x.png", "z.png", "missing.png"])
    assert n == 2
    rels = db.list_rel_paths()
    assert rels == {"y.png"}
