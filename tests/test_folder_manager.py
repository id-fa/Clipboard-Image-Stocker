"""Tests for the new workspace-rooted FolderManager."""

from __future__ import annotations

from pathlib import Path

import pytest

from stocker.config import AppConfig
from stocker.core.folder_manager import FolderManager


def test_set_workspace(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    cfg = AppConfig()
    fm = FolderManager(cfg)
    assert not fm.has_workspace()

    ws = tmp_path / "ワーク基点"
    ws.mkdir()
    fm.set_workspace(ws)
    assert fm.has_workspace()
    assert fm.workspace == ws.resolve()
    assert (ws / ".stocker").is_dir()


def test_create_subfolder(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    cfg = AppConfig()
    fm = FolderManager(cfg)
    ws = tmp_path / "ws"; ws.mkdir()
    fm.set_workspace(ws)

    sub = fm.create_subfolder("ジャンルA")
    assert sub.is_dir()
    assert sub == (ws / "ジャンルA").resolve()
    assert (sub / ".stocker").is_dir()

    # Nested
    nested = fm.create_subfolder("子", parent=sub)
    assert nested.is_dir()


def test_create_subfolder_rejects_invalid(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    cfg = AppConfig()
    fm = FolderManager(cfg)
    ws = tmp_path / "ws"; ws.mkdir()
    fm.set_workspace(ws)
    for bad in ("", ".", "..", "a/b", "a\\b", ".stocker", ".trash"):
        with pytest.raises(ValueError):
            fm.create_subfolder(bad)


def test_all_folders_excludes_hidden(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    cfg = AppConfig()
    fm = FolderManager(cfg)
    ws = tmp_path / "ws"; ws.mkdir()
    fm.set_workspace(ws)
    fm.create_subfolder("A")
    fm.create_subfolder("B")
    # Manually create .trash
    (ws / ".trash").mkdir()
    folders = fm.all_folders()
    names = [f.name for f in folders]
    assert ws.name in names
    assert "A" in names
    assert "B" in names
    assert ".stocker" not in names
    assert ".trash" not in names


def test_rename_folder_basic(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    cfg = AppConfig()
    fm = FolderManager(cfg)
    ws = tmp_path / "ws"; ws.mkdir()
    fm.set_workspace(ws)
    sub = fm.create_subfolder("旧名")
    (sub / "x.png").write_bytes(b"x")
    new_path = fm.rename_folder(sub, "新名")
    assert new_path == (ws / "新名").resolve()
    assert new_path.is_dir()
    assert (new_path / "x.png").exists()
    assert (new_path / ".stocker").is_dir()
    assert not sub.exists()


def test_rename_folder_rejects_workspace(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    cfg = AppConfig()
    fm = FolderManager(cfg)
    ws = tmp_path / "ws"; ws.mkdir()
    fm.set_workspace(ws)
    with pytest.raises(ValueError):
        fm.rename_folder(ws, "別名")


def test_rename_folder_rejects_invalid_name(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    cfg = AppConfig()
    fm = FolderManager(cfg)
    ws = tmp_path / "ws"; ws.mkdir()
    fm.set_workspace(ws)
    sub = fm.create_subfolder("A")
    for bad in ("", ".", "..", "a/b", "a\\b", ".stocker", ".trash"):
        with pytest.raises(ValueError):
            fm.rename_folder(sub, bad)


def test_rename_folder_rejects_collision(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    cfg = AppConfig()
    fm = FolderManager(cfg)
    ws = tmp_path / "ws"; ws.mkdir()
    fm.set_workspace(ws)
    a = fm.create_subfolder("A")
    fm.create_subfolder("B")
    with pytest.raises(ValueError):
        fm.rename_folder(a, "B")


def test_rename_folder_rejects_outside_workspace(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    cfg = AppConfig()
    fm = FolderManager(cfg)
    ws = tmp_path / "ws"; ws.mkdir()
    fm.set_workspace(ws)
    outside = tmp_path / "外"; outside.mkdir()
    with pytest.raises(ValueError):
        fm.rename_folder(outside, "別名")


def test_folder_under_workspace(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    cfg = AppConfig()
    fm = FolderManager(cfg)
    ws = tmp_path / "ws"; ws.mkdir()
    fm.set_workspace(ws)
    sub = fm.create_subfolder("S")
    outside = tmp_path / "外"; outside.mkdir()
    assert fm.folder_under_workspace(sub)
    assert fm.folder_under_workspace(ws)
    assert not fm.folder_under_workspace(outside)
