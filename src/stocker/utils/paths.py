"""Japanese-safe path helpers."""

from __future__ import annotations

from pathlib import Path

IMAGE_EXTS = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"})


def is_image_file(path: Path | str) -> bool:
    return Path(path).suffix.lower() in IMAGE_EXTS


def normalize_rel(rel_path: Path | str) -> str:
    """Store paths with forward slashes for portability across platforms."""
    s = str(rel_path).replace("\\", "/")
    while s.startswith("./"):
        s = s[2:]
    return s


def to_rel(root: Path, abs_path: Path) -> str:
    return normalize_rel(abs_path.resolve().relative_to(root.resolve()))


def from_rel(root: Path, rel: str) -> Path:
    return root / rel.replace("/", "\\")


def avoid_collision(target: Path) -> Path:
    """If target exists, append ' (2)', ' (3)', ... before extension until unique."""
    if not target.exists():
        return target
    stem = target.stem
    suffix = target.suffix
    parent = target.parent
    n = 2
    while True:
        candidate = parent / f"{stem} ({n}){suffix}"
        if not candidate.exists():
            return candidate
        n += 1
