"""Folder scanner: diff DB signatures against on-disk state."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path

from stocker.core.models import FileItem
from stocker.db.metadata_db import MetadataDB
from stocker.utils.paths import IMAGE_EXTS, normalize_rel

log = logging.getLogger(__name__)


@dataclass
class ScanResult:
    added: list[FileItem]
    updated: list[FileItem]
    removed: list[str]
    total: int

    @property
    def changed(self) -> bool:
        return bool(self.added or self.updated or self.removed)


def scan_folder(root: Path, db: MetadataDB) -> ScanResult:
    """Walk root (skipping .stocker/) and reconcile with DB state.

    Stores changes in DB and returns the diff.
    """
    root = root.resolve()
    db_sigs = db.get_signatures()
    seen: set[str] = set()
    added: list[FileItem] = []
    updated: list[FileItem] = []
    now = int(time.time())

    for abs_path in _iter_image_files(root):
        try:
            st = abs_path.stat()
        except OSError as e:
            log.warning("stat failed for %s: %s", abs_path, e)
            continue
        rel = normalize_rel(abs_path.relative_to(root))
        seen.add(rel)
        sig = (st.st_mtime_ns, st.st_size)
        prev = db_sigs.get(rel)
        if prev is None:
            added.append(
                FileItem(
                    rel_path=rel,
                    name=abs_path.name,
                    ext=abs_path.suffix.lower(),
                    size_bytes=st.st_size,
                    mtime_ns=st.st_mtime_ns,
                    added_at=now,
                )
            )
        elif prev != sig:
            updated.append(
                FileItem(
                    rel_path=rel,
                    name=abs_path.name,
                    ext=abs_path.suffix.lower(),
                    size_bytes=st.st_size,
                    mtime_ns=st.st_mtime_ns,
                    added_at=now,
                )
            )

    removed = sorted(set(db_sigs.keys()) - seen)

    if added:
        db.bulk_upsert(added)
    if updated:
        db.bulk_upsert(updated)
    if removed:
        db.bulk_delete(removed)

    db.set_scan_state(time.time_ns(), len(seen))
    return ScanResult(added=added, updated=updated, removed=removed, total=len(seen))


def count_image_files(root: Path) -> int:
    """Count image files at the top level of ``root`` (non-recursive).

    Mirrors ``_iter_image_files``'s traversal so the returned count matches
    what the scanner would put in the DB. Used by the sidebar to annotate
    folder names without having to open each folder's SQLite DB.
    """
    return sum(1 for _ in _iter_image_files(root))


def _iter_image_files(root: Path):
    """Iterate image files at the top level of `root` only.

    Scanning is non-recursive on purpose: each subfolder under a workspace is
    itself a separately-managed folder with its own DB, so recursing would
    double-count files. Hidden internal dirs (.stocker, .trash) are also
    skipped — they aren't traversed at all.
    """
    try:
        with os.scandir(root) as it:
            for entry in it:
                if entry.is_dir(follow_symlinks=False):
                    continue  # subfolders are scanned separately
                if entry.is_file(follow_symlinks=False):
                    ext = os.path.splitext(entry.name)[1].lower()
                    if ext in IMAGE_EXTS:
                        yield Path(entry.path)
    except OSError as e:
        log.warning("scandir failed for %s: %s", root, e)
