"""Core dataclasses used across layers."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from stocker.utils.paths import normalize_rel


class FileKind(Enum):
    DISK = "disk"
    PENDING = "pending"


@dataclass
class FileItem:
    rel_path: str  # forward-slash, root-relative
    name: str
    ext: str  # lowercase incl. leading dot, e.g. ".png"
    size_bytes: int
    mtime_ns: int
    added_at: int  # epoch seconds
    width: int | None = None
    height: int | None = None
    thumb_hash: str | None = None
    db_id: int | None = None
    kind: FileKind = FileKind.DISK
    pending_id: int | None = None  # set for kind=PENDING

    @classmethod
    def from_path(cls, root: Path, abs_path: Path) -> FileItem:
        st = abs_path.stat()
        return cls(
            rel_path=normalize_rel(abs_path.resolve().relative_to(root.resolve())),
            name=abs_path.name,
            ext=abs_path.suffix.lower(),
            size_bytes=st.st_size,
            mtime_ns=st.st_mtime_ns,
            added_at=int(time.time()),
        )


@dataclass
class FolderRoot:
    path: Path
    name: str

    @classmethod
    def from_path(cls, p: Path) -> FolderRoot:
        return cls(path=p, name=p.name or str(p))


@dataclass(frozen=True)
class ThumbKey:
    rel_path: str
    mtime_ns: int
    target_size: int


class PendingStatus(Enum):
    PENDING = "pending"
    WRITING = "writing"
    DONE = "done"
    FAILED = "failed"


@dataclass
class PendingPaste:
    pid: int
    qimage: object  # QImage; typed loosely so models.py is Qt-free at import time
    timestamp_ns: int
    suggested_name: str
    status: PendingStatus = PendingStatus.PENDING
    error: str | None = None
    rel_path_after_save: str | None = None
    extra: dict[str, object] = field(default_factory=dict)

    @staticmethod
    def make_name(ts: float | None = None, ext: str = ".png") -> str:
        t = ts if ts is not None else time.time()
        local = time.localtime(t)
        ms = int((t - int(t)) * 1000)
        if not ext.startswith("."):
            ext = "." + ext
        return time.strftime("paste_%Y%m%d_%H%M%S", local) + f"_{ms:03d}{ext}"


def stat_signature(p: Path) -> tuple[int, int]:
    """Return (mtime_ns, size_bytes) for change detection."""
    st = os.stat(p)
    return st.st_mtime_ns, st.st_size
