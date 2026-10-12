"""Per-folder column-count memory.

The mapping lives in ``AppConfig.folder_columns`` keyed by the folder's
workspace-relative path (forward slashes; ``"."`` for the workspace root,
``".trash"`` for the trash view). Relative keys survive a workspace being
moved on disk and make folder rename/delete bookkeeping a prefix rewrite.
"""

from __future__ import annotations

from pathlib import Path

from stocker.utils.paths import normalize_rel

ROOT_KEY = "."
MIN_COLUMNS = 1
MAX_COLUMNS = 16


def folder_key(workspace: Path | None, folder: Path) -> str | None:
    """Return the config key for *folder*, or None if it is outside *workspace*."""
    if workspace is None:
        return None
    try:
        rel = folder.resolve().relative_to(workspace.resolve())
    except ValueError:
        return None
    s = normalize_rel(rel)
    return ROOT_KEY if s in ("", ".") else s


def lookup(mapping: dict[str, int], key: str | None) -> int | None:
    """Stored column count for *key*, clamped to the valid range; None if absent."""
    if key is None:
        return None
    v = mapping.get(key)
    if not isinstance(v, int) or isinstance(v, bool):
        return None
    return max(MIN_COLUMNS, min(MAX_COLUMNS, v))


def remember(mapping: dict[str, int], key: str | None, columns: int) -> None:
    """Record *columns* for *key* in place (no-op when key is None)."""
    if key is None:
        return
    mapping[key] = max(MIN_COLUMNS, min(MAX_COLUMNS, int(columns)))


def _in_subtree(key: str, rel: str) -> bool:
    return key == rel or key.startswith(rel + "/")


def rename_subtree(mapping: dict[str, int], old_rel: str, new_rel: str) -> dict[str, int]:
    """Return a copy of *mapping* with keys under *old_rel* moved to *new_rel*."""
    old_rel = normalize_rel(old_rel)
    new_rel = normalize_rel(new_rel)
    out: dict[str, int] = {}
    for k, v in mapping.items():
        if _in_subtree(k, old_rel):
            out[new_rel + k[len(old_rel):]] = v
        else:
            out[k] = v
    return out


def drop_subtree(mapping: dict[str, int], rel: str) -> dict[str, int]:
    """Return a copy of *mapping* without keys for *rel* and its descendants."""
    rel = normalize_rel(rel)
    return {k: v for k, v in mapping.items() if not _in_subtree(k, rel)}
