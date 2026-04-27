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
from stocker.i18n import tr

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
            raise ValueError(tr("fm.not_a_folder", path=path))
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
            raise ValueError(tr("fm.no_workspace"))
        if not name or name in (".", "..") or "/" in name or "\\" in name:
            raise ValueError(tr("fm.invalid_name", name=name))
        if name in HIDDEN_DIR_NAMES:
            raise ValueError(tr("fm.reserved_name", name=name))
        base = (parent or self._workspace).resolve()
        # Safety: parent must be within workspace
        try:
            base.relative_to(self._workspace)
        except ValueError as exc:
            raise ValueError(tr("fm.outside_workspace_create")) from exc
        target = base / name
        if target.exists():
            raise ValueError(tr("fm.already_exists", name=target.name))
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

    def rename_folder(self, path: Path, new_name: str) -> Path:
        """Rename a managed subfolder on disk. Returns the new absolute path.

        The workspace root itself cannot be renamed through this API; its path
        is owned by `AppConfig.workspace_root` and a rename here would leave
        the config dangling.
        """
        if self._workspace is None:
            raise ValueError(tr("fm.no_workspace"))
        if not new_name or new_name in (".", "..") or "/" in new_name or "\\" in new_name:
            raise ValueError(tr("fm.invalid_name", name=new_name))
        if new_name in HIDDEN_DIR_NAMES:
            raise ValueError(tr("fm.reserved_name", name=new_name))
        src = path.resolve()
        ws = self._workspace.resolve()
        if src == ws:
            raise ValueError(tr("fm.cant_rename_workspace"))
        if not self.folder_under_workspace(src):
            raise ValueError(tr("fm.cant_rename_outside"))
        if not src.is_dir():
            raise ValueError(tr("fm.not_found", path=src))
        if new_name == src.name:
            return src
        target = src.parent / new_name
        if target.exists():
            raise ValueError(tr("fm.already_exists", name=target.name))
        src.rename(target)
        log.info("renamed folder %s -> %s", src, target)
        return target.resolve()
