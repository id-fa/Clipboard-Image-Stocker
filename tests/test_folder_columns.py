"""Per-folder column memory (core/folder_columns.py) + config roundtrip."""

from __future__ import annotations

from pathlib import Path

from stocker.config import AppConfig
from stocker.core import folder_columns as fc


def test_folder_key_root_and_subfolders(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    (ws / "a" / "b").mkdir(parents=True)
    assert fc.folder_key(ws, ws) == "."
    assert fc.folder_key(ws, ws / "a") == "a"
    assert fc.folder_key(ws, ws / "a" / "b") == "a/b"
    assert fc.folder_key(ws, ws / ".trash") == ".trash"


def test_folder_key_outside_or_no_workspace(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    assert fc.folder_key(ws, other) is None
    assert fc.folder_key(None, ws) is None


def test_remember_and_lookup_clamp() -> None:
    m: dict[str, int] = {}
    fc.remember(m, "a", 4)
    fc.remember(m, "b", 99)
    fc.remember(m, "c", 0)
    fc.remember(m, None, 5)  # no key → no-op
    assert m == {"a": 4, "b": 16, "c": 1}
    assert fc.lookup(m, "a") == 4
    assert fc.lookup(m, "zzz") is None
    assert fc.lookup(m, None) is None
    assert fc.lookup({"x": 40}, "x") == 16
    assert fc.lookup({"x": True}, "x") is None  # bool is not a column count


def test_rename_subtree_moves_prefix_only() -> None:
    m = {".": 6, "a": 3, "a/b": 4, "ab": 5, "c": 7}
    out = fc.rename_subtree(m, "a", "z")
    assert out == {".": 6, "z": 3, "z/b": 4, "ab": 5, "c": 7}
    assert m["a"] == 3  # input untouched


def test_rename_subtree_nested_target() -> None:
    m = {"p/a": 3, "p/a/b": 4}
    assert fc.rename_subtree(m, "p/a", "q/r") == {"q/r": 3, "q/r/b": 4}


def test_drop_subtree() -> None:
    m = {".": 6, "a": 3, "a/b": 4, "ab": 5}
    assert fc.drop_subtree(m, "a") == {".": 6, "ab": 5}
    assert fc.drop_subtree(m, "nope") == m


def test_config_roundtrip_and_sanitize() -> None:
    cfg = AppConfig(folder_columns={".": 6, "a/b": 4})
    back = AppConfig.from_json(cfg.to_json())
    assert back.folder_columns == {".": 6, "a/b": 4}
    assert back.columns == 6

    # Corrupt / legacy shapes degrade gracefully instead of raising.
    assert AppConfig.from_json('{"folder_columns": [1, 2]}').folder_columns == {}
    bad = AppConfig.from_json('{"folder_columns": {"a": "x", "b": 3, "c": true}}')
    assert bad.folder_columns == {"b": 3}
    assert AppConfig.from_json("{}").folder_columns == {}
