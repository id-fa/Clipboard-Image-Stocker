"""Imports external image files (from D&D etc.) into a managed folder."""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from stocker.core.models import FileItem
from stocker.db.metadata_db import MetadataDB
from stocker.utils.paths import IMAGE_EXTS, avoid_collision, normalize_rel

log = logging.getLogger(__name__)


@dataclass
class ImportResult:
    imported: list[FileItem]
    skipped: list[Path]
    failed: list[tuple[Path, str]]


def import_files(sources: list[Path], dst_root: Path, db: MetadataDB) -> ImportResult:
    imported: list[FileItem] = []
    skipped: list[Path] = []
    failed: list[tuple[Path, str]] = []
    dst_root = dst_root.resolve()

    for src in sources:
        try:
            if src.is_dir():
                # Recursively import images from a dropped folder.
                for sub in _iter_images(src):
                    item = _copy_one(sub, dst_root, db)
                    if item:
                        imported.append(item)
                continue
            if src.suffix.lower() not in IMAGE_EXTS:
                skipped.append(src)
                continue
            item = _copy_one(src, dst_root, db)
            if item:
                imported.append(item)
        except Exception as e:  # noqa: BLE001
            log.exception("import failed for %s", src)
            failed.append((src, str(e)))

    return ImportResult(imported=imported, skipped=skipped, failed=failed)


def _copy_one(src: Path, dst_root: Path, db: MetadataDB) -> FileItem | None:
    target = avoid_collision(dst_root / src.name)
    shutil.copy2(src, target)
    item = FileItem.from_path(dst_root, target)
    db.upsert_file(item)
    return item


def _iter_images(folder: Path):
    for p in folder.rglob("*"):
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
            yield p


def normalize_relpath(root: Path, abs_path: Path) -> str:
    return normalize_rel(abs_path.resolve().relative_to(root.resolve()))
