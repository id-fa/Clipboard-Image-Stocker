"""Workspace-rooted folder management.

A *workspace* is a single base directory chosen by the user. The workspace
itself is a managed folder, and any subdirectory under it (excluding
`.stocker/` and `.trash/`) is also a managed folder with its own SQLite DB.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from stocker.app_paths import HIDDEN_DIR_NAMES, ensure_stocker_layout
from stocker.config import AppConfig, save_config

log = logging.getLogger(__name__)


class FolderManager:
    """Owns the workspace_root and exposes its subfolder tree."""

    def __init__(self, cfg: AppConfig):
        self._cfg = cfg
        self._workspace: Path | None = None
        if cfg.workspace_root:
            p = Path(cfg.workspace_root)
            if p.exists() and p.is_dir():
                self._workspace = p.resolve()

    @property
    def workspace(self) -> Path | None:
        return self._workspace

    def has_workspace(self) -> bool:
        return self._workspace is not None

    def set_workspace(self, path: Path) -> None:
        path = path.resolve()
        if not path.is_dir():
            raise ValueError(f"フォルダではありません: {path}")
        self._workspace = path
        ensure_stocker_layout(path)
        self._cfg.workspace_root = str(path)
        save_config(self._cfg)

    def all_folders(self) -> list[Path]:
        """Workspace + every subfolder (recursive), sorted by name.

        Hidden internal directories (.stocker, .trash) are excluded.
        Each returned path can be used as a managed folder root with its own DB.
        """
        if self._workspace is None:
            return []
        out: list[Path] = [self._workspace]
        # Walk so we can prune hidden dirs early
        for current_root, dirnames, _filenames in os.walk(self._workspace):
            dirnames[:] = sorted(
                d for d in dirnames if d not in HIDDEN_DIR_NAMES
            )
            for d in dirnames:
                out.append(Path(current_root) / d)
        return out

    def create_subfolder(self, name: str, parent: Path | None = None) -> Path:
        """Create a new subfolder under `parent` (or workspace root if omitted)."""
        if self._workspace is None:
            raise ValueError("ワークスペースが未設定です")
        if not name or name in (".", "..") or "/" in name or "\\" in name:
            raise ValueError(f"無効なフォルダ名です: {name}")
        if name in HIDDEN_DIR_NAMES:
            raise ValueError(f"予約済みのフォルダ名です: {name}")
        base = (parent or self._workspace).resolve()
        # Safety: parent must be within workspace
        try:
            base.relative_to(self._workspace)
        except ValueError as exc:
            raise ValueError("ワークスペース外には作成できません") from exc
        target = base / name
        if target.exists():
            raise ValueError(f"既に存在します: {target.name}")
        target.mkdir(parents=True)
        ensure_stocker_layout(target)
        log.info("created subfolder %s", target)
        return target

    def folder_under_workspace(self, p: Path) -> bool:
        if self._workspace is None:
            return False
        try:
            p.resolve().relative_to(self._workspace)
            return True
        except ValueError:
            return False
