"""Trash service: workspace-level recycle bin with origin-tracked restore."""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from stocker.app_paths import STOCKER_DIRNAME, TRASH_DIRNAME
from stocker.utils.paths import avoid_collision, normalize_rel

log = logging.getLogger(__name__)

INDEX_FILENAME = "trash_index.json"


@dataclass
class TrashedItem:
    src_abs: Path
    trashed_abs: Path
    origin_folder_rel: str  # workspace-relative, "" for items in workspace root
    original_name: str


@dataclass
class RestoreResult:
    restored_abs: Path
    origin_folder_rel: str
    error: str | None = None  # set if the restore failed


def trash_root(workspace: Path) -> Path:
    return workspace / TRASH_DIRNAME


def index_path(workspace: Path) -> Path:
    return workspace / STOCKER_DIRNAME / INDEX_FILENAME


def ensure_trash(workspace: Path) -> Path:
    p = trash_root(workspace)
    p.mkdir(parents=True, exist_ok=True)
    return p


def is_in_trash(workspace: Path, abs_path: Path) -> bool:
    try:
        abs_path.resolve().relative_to(trash_root(workspace).resolve())
        return True
    except (ValueError, OSError):
        return False


# ----- index persistence -----


def _load_index(workspace: Path) -> dict[str, dict]:
    p = index_path(workspace)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError) as e:
        log.warning("trash index unreadable, starting fresh: %s", e)
        return {}


def _save_index(workspace: Path, idx: dict[str, dict]) -> None:
    p = index_path(workspace)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def get_origin(workspace: Path, trashed_basename: str) -> tuple[str, str] | None:
    """Returns (origin_folder_rel, original_name) for a trashed file, or None."""
    idx = _load_index(workspace)
    meta = idx.get(trashed_basename)
    if meta is None:
        return None
    return (
        str(meta.get("origin_folder_rel", "")),
        str(meta.get("original_name", trashed_basename)),
    )


# ----- move-to-trash -----


def move_to_trash(
    workspace: Path, sources: list[tuple[Path, Path]]
) -> list[TrashedItem]:
    """Move files to <workspace>/.trash/, recording origin per file.

    Each source is `(file_abs_path, src_managed_folder)`. The src_managed_folder
    is the managed root the file came from; relative-to-workspace becomes the
    `origin_folder_rel` used for restore.
    """
    troot = ensure_trash(workspace)
    idx = _load_index(workspace)
    moved: list[TrashedItem] = []
    workspace_resolved = workspace.resolve()
    for src, src_root in sources:
        if not src.exists() or not src.is_file():
            continue
        ts_ms = int(time.time() * 1000)
        target = avoid_collision(troot / f"{src.stem}_{ts_ms}{src.suffix}")
        try:
            try:
                os.replace(src, target)
            except OSError:
                shutil.move(str(src), str(target))
            now = time.time()
            try:
                os.utime(target, (now, now))
            except OSError:
                pass
            try:
                origin_rel = normalize_rel(
                    src_root.resolve().relative_to(workspace_resolved)
                )
                if origin_rel == ".":
                    origin_rel = ""
            except ValueError:
                origin_rel = ""
            idx[target.name] = {
                "origin_folder_rel": origin_rel,
                "original_name": src.name,
                "trashed_at_ns": time.time_ns(),
            }
            moved.append(
                TrashedItem(
                    src_abs=src,
                    trashed_abs=target,
                    origin_folder_rel=origin_rel,
                    original_name=src.name,
                )
            )
        except OSError as e:
            log.warning("trash failed for %s: %s", src, e)
    if moved:
        _save_index(workspace, idx)
    return moved


# ----- restore -----


def restore(
    workspace: Path, trashed_basenames: list[str]
) -> list[RestoreResult]:
    """Move trashed files back to their original folders. Returns per-file results."""
    idx = _load_index(workspace)
    troot = trash_root(workspace)
    results: list[RestoreResult] = []
    for basename in trashed_basenames:
        src = troot / basename
        meta = idx.get(basename)
        origin_rel = (meta or {}).get("origin_folder_rel", "")
        original_name = (meta or {}).get("original_name", basename)
        target_folder = workspace / origin_rel if origin_rel else workspace
        if not src.exists():
            results.append(
                RestoreResult(restored_abs=src, origin_folder_rel=origin_rel,
                              error="ごみ箱内にファイルがありません")
            )
            idx.pop(basename, None)
            continue
        if not target_folder.exists():
            try:
                target_folder.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                results.append(
                    RestoreResult(restored_abs=src, origin_folder_rel=origin_rel,
                                  error=f"復元先を作成できません: {e}")
                )
                continue
        target = avoid_collision(target_folder / original_name)
        try:
            try:
                os.replace(src, target)
            except OSError:
                shutil.move(str(src), str(target))
            idx.pop(basename, None)
            results.append(
                RestoreResult(restored_abs=target, origin_folder_rel=origin_rel)
            )
        except OSError as e:
            results.append(
                RestoreResult(restored_abs=target, origin_folder_rel=origin_rel,
                              error=str(e))
            )
    _save_index(workspace, idx)
    return results


# ----- purge / count -----


def auto_purge(workspace: Path, days: int) -> int:
    if days <= 0:
        return 0
    troot = trash_root(workspace)
    if not troot.exists():
        return 0
    cutoff = time.time() - days * 86400
    idx = _load_index(workspace)
    n = 0
    for p in list(troot.iterdir()):
        if not p.is_file():
            continue
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
                idx.pop(p.name, None)
                n += 1
        except OSError as e:
            log.warning("purge failed for %s: %s", p, e)
    if n:
        _save_index(workspace, idx)
        log.info("auto-purged %d trashed files (>%d days)", n, days)
    return n


def empty_trash(workspace: Path) -> int:
    troot = trash_root(workspace)
    if not troot.exists():
        return 0
    n = 0
    for p in list(troot.iterdir()):
        if p.is_file():
            try:
                p.unlink()
                n += 1
            except OSError as e:
                log.warning("empty_trash failed for %s: %s", p, e)
    if n:
        _save_index(workspace, {})
    return n


def trash_count(workspace: Path) -> int:
    troot = trash_root(workspace)
    if not troot.exists():
        return 0
    return sum(1 for p in troot.iterdir() if p.is_file())
