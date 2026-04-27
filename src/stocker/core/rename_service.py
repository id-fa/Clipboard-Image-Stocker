"""Rename a file on disk + update the DB."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from stocker.core.models import FileItem
from stocker.db.metadata_db import MetadataDB
from stocker.utils.paths import avoid_collision, from_rel, normalize_rel

log = logging.getLogger(__name__)


def rename_file(root: Path, item: FileItem, new_name: str, db: MetadataDB) -> FileItem:
    """Rename `item` within its current directory to `new_name`. Returns the updated FileItem.

    Raises FileExistsError-or-similar OSError on failure (caller should catch).
    """
    if not new_name or new_name in (".", ".."):
        raise ValueError("invalid new name")
    if "\\" in new_name or "/" in new_name:
        raise ValueError("path separators not allowed in rename")

    old_abs = from_rel(root, item.rel_path)
    if not old_abs.exists():
        raise FileNotFoundError(str(old_abs))

    new_abs = avoid_collision(old_abs.parent / new_name)
    os.replace(old_abs, new_abs)

    new_rel = normalize_rel(new_abs.relative_to(root))
    db.rename(item.rel_path, new_rel, new_abs.name)

    updated = db.get_by_rel(new_rel)
    if updated is None:
        # Fallback: synthesize from disk
        updated = FileItem.from_path(root, new_abs)
        db.upsert_file(updated)
    log.info("renamed %s -> %s", item.rel_path, new_rel)
    return updated
