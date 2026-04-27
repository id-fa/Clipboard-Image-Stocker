"""Tests for the trash service: move, restore, auto-purge, JSON index."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from stocker.app_paths import STOCKER_DIRNAME
from stocker.core import trash as t


def _ws(tmp_path: Path, name: str = "ws") -> Path:
    p = tmp_path / name
    p.mkdir()
    return p


def test_move_to_trash_records_origin(tmp_path: Path):
    ws = _ws(tmp_path, "ワーク")
    sub = ws / "ジャンルA"
    sub.mkdir()
    src = sub / "a.png"
    src.write_bytes(b"data")
    moved = t.move_to_trash(ws, [(src, sub)])
    assert len(moved) == 1
    assert not src.exists()
    assert moved[0].trashed_abs.exists()
    assert moved[0].origin_folder_rel == "ジャンルA"
    assert moved[0].original_name == "a.png"
    # Index file present and parseable
    idx_file = ws / STOCKER_DIRNAME / "trash_index.json"
    assert idx_file.exists()
    idx = json.loads(idx_file.read_text(encoding="utf-8"))
    assert moved[0].trashed_abs.name in idx


def test_move_to_trash_workspace_root_origin(tmp_path: Path):
    """Files trashed from the workspace root itself record origin = ''."""
    ws = _ws(tmp_path)
    src = ws / "x.png"; src.write_bytes(b"x")
    moved = t.move_to_trash(ws, [(src, ws)])
    assert moved[0].origin_folder_rel == ""


def test_restore_to_original_folder(tmp_path: Path):
    ws = _ws(tmp_path)
    sub = ws / "サブ"; sub.mkdir()
    src = sub / "p.png"; src.write_bytes(b"p")
    moved = t.move_to_trash(ws, [(src, sub)])
    basename = moved[0].trashed_abs.name

    results = t.restore(ws, [basename])
    assert len(results) == 1 and results[0].error is None
    restored = results[0].restored_abs
    assert restored.exists()
    assert restored.parent == sub
    assert restored.name == "p.png"
    # Trash index cleaned up
    idx = json.loads((ws / STOCKER_DIRNAME / "trash_index.json").read_text(encoding="utf-8"))
    assert basename not in idx


def test_restore_collides_with_same_name(tmp_path: Path):
    """If a same-named file already lives at the restore target, suffix it."""
    ws = _ws(tmp_path)
    sub = ws / "S"; sub.mkdir()
    src = sub / "c.png"; src.write_bytes(b"original")
    moved = t.move_to_trash(ws, [(src, sub)])
    # Recreate a different file at the original location
    (sub / "c.png").write_bytes(b"new")

    results = t.restore(ws, [moved[0].trashed_abs.name])
    assert results[0].error is None
    assert results[0].restored_abs.name == "c (2).png"
    assert (sub / "c.png").read_bytes() == b"new"
    assert results[0].restored_abs.read_bytes() == b"original"


def test_restore_when_origin_folder_was_deleted(tmp_path: Path):
    """If the origin folder no longer exists, restore should re-create it."""
    ws = _ws(tmp_path)
    sub = ws / "消えたフォルダ"; sub.mkdir()
    src = sub / "z.png"; src.write_bytes(b"z")
    moved = t.move_to_trash(ws, [(src, sub)])
    sub.rmdir()
    assert not sub.exists()
    results = t.restore(ws, [moved[0].trashed_abs.name])
    assert results[0].error is None
    assert sub.exists()
    assert (sub / "z.png").exists()


def test_auto_purge_old_files_clears_index(tmp_path: Path):
    ws = _ws(tmp_path)
    f1 = ws / "old.png"; f1.write_bytes(b"o")
    f2 = ws / "new.png"; f2.write_bytes(b"n")
    moved = t.move_to_trash(ws, [(f1, ws), (f2, ws)])
    old_target = next(m for m in moved if m.original_name == "old.png").trashed_abs
    ten_days_ago = time.time() - 10 * 86400
    os.utime(old_target, (ten_days_ago, ten_days_ago))
    purged = t.auto_purge(ws, 5)
    assert purged == 1
    assert t.trash_count(ws) == 1
    idx = json.loads((ws / STOCKER_DIRNAME / "trash_index.json").read_text(encoding="utf-8"))
    assert old_target.name not in idx


def test_auto_purge_zero_disabled(tmp_path: Path):
    ws = _ws(tmp_path)
    f = ws / "a.png"; f.write_bytes(b"a")
    t.move_to_trash(ws, [(f, ws)])
    assert t.auto_purge(ws, 0) == 0
    assert t.trash_count(ws) == 1


def test_empty_trash_clears_index(tmp_path: Path):
    ws = _ws(tmp_path)
    f = ws / "a.png"; f.write_bytes(b"a")
    t.move_to_trash(ws, [(f, ws)])
    n = t.empty_trash(ws)
    assert n == 1
    idx = json.loads((ws / STOCKER_DIRNAME / "trash_index.json").read_text(encoding="utf-8"))
    assert idx == {}


def test_rewrite_origin_paths_after_folder_rename(tmp_path: Path):
    """origin_folder_rel must follow a renamed managed subfolder so restore works."""
    ws = _ws(tmp_path)
    sub = ws / "古"; sub.mkdir()
    nested = sub / "孫"; nested.mkdir()
    other = ws / "別"; other.mkdir()
    f1 = sub / "a.png"; f1.write_bytes(b"a")
    f2 = nested / "b.png"; f2.write_bytes(b"b")
    f3 = other / "c.png"; f3.write_bytes(b"c")
    t.move_to_trash(ws, [(f1, sub), (f2, nested), (f3, other)])

    n = t.rewrite_origin_paths(ws, "古", "新")
    assert n == 2  # only entries under "古" (incl. nested) are rewritten

    idx = json.loads((ws / STOCKER_DIRNAME / "trash_index.json").read_text(encoding="utf-8"))
    origins = sorted(meta["origin_folder_rel"] for meta in idx.values())
    assert origins == ["別", "新", "新/孫"]


def test_rewrite_origin_paths_noop_when_unchanged(tmp_path: Path):
    ws = _ws(tmp_path)
    sub = ws / "S"; sub.mkdir()
    f = sub / "a.png"; f.write_bytes(b"a")
    t.move_to_trash(ws, [(f, sub)])
    assert t.rewrite_origin_paths(ws, "", "X") == 0
    assert t.rewrite_origin_paths(ws, "S", "S") == 0


def test_restore_after_folder_rename_uses_new_path(tmp_path: Path):
    """End-to-end: rename a folder, then restore — file lands under the new name."""
    ws = _ws(tmp_path)
    sub = ws / "Src"; sub.mkdir()
    f = sub / "p.png"; f.write_bytes(b"p")
    moved = t.move_to_trash(ws, [(f, sub)])
    basename = moved[0].trashed_abs.name

    # Simulate the directory rename (FolderManager would do this in production).
    new_sub = ws / "Dst"
    sub.rename(new_sub)
    t.rewrite_origin_paths(ws, "Src", "Dst")

    results = t.restore(ws, [basename])
    assert results[0].error is None
    assert results[0].restored_abs.parent == new_sub
    assert (new_sub / "p.png").exists()


def test_japanese_filename_roundtrip(tmp_path: Path):
    ws = _ws(tmp_path, "日本語ワーク")
    sub = ws / "保存先"; sub.mkdir()
    f = sub / "画像🖼.png"; f.write_bytes(b"jp")
    moved = t.move_to_trash(ws, [(f, sub)])
    results = t.restore(ws, [moved[0].trashed_abs.name])
    assert results[0].error is None
    assert (sub / "画像🖼.png").exists()
