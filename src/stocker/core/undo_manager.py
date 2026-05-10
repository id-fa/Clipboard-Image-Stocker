"""Single-generation Undo/Redo for move / copy / trash operations.

Holds at most one entry on each side: doing an op replaces the undo entry and
clears redo; Ctrl+Z pops undo and pushes the inverse onto redo; Ctrl+Y pops
redo and pushes back onto undo. Reverse logic for each kind lives in the
MainWindow handlers — this module is just a typed container.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class UndoKind(Enum):
    MOVE = "move"
    COPY = "copy"
    TRASH = "trash"


@dataclass
class UndoEntry:
    """Snapshot of a completed operation, sufficient to both undo and redo it.

    Move/Copy fields:
      - src_root / dst_root: managed folder roots (resolved Paths).
      - pairs: list of (src_rel, dst_rel). After a successful move/copy, files
        live at dst_root/dst_rel; before they were at src_root/src_rel.

    Trash fields (only one of the two directions is populated per entry —
    whichever the entry is positioned to perform next):
      - workspace: the workspace root that owns the .trash dir.
      - trashed_basenames: filenames inside <workspace>/.trash/. Populated when
        the entry is on the UNDO stack (next action restores from trash).
      - trash_sources: (file_current_abs, src_managed_folder) pairs. Populated
        when the entry is on the REDO stack (next action re-trashes the files).
    """

    kind: UndoKind
    # display labels (workspace-relative names) for log strings
    src_label: str = ""
    dst_label: str = ""

    # MOVE / COPY
    src_root: Path | None = None
    dst_root: Path | None = None
    pairs: list[tuple[str, str]] = field(default_factory=list)

    # TRASH
    workspace: Path | None = None
    trashed_basenames: list[str] = field(default_factory=list)
    trash_sources: list[tuple[Path, Path]] = field(default_factory=list)

    @property
    def count(self) -> int:
        if self.kind is UndoKind.TRASH:
            return len(self.trashed_basenames) or len(self.trash_sources)
        return len(self.pairs)


class UndoManager:
    """Tracks a single undo entry plus a single redo entry."""

    def __init__(self) -> None:
        self._undo: UndoEntry | None = None
        self._redo: UndoEntry | None = None

    # ---- queries ----

    def can_undo(self) -> bool:
        return self._undo is not None

    def can_redo(self) -> bool:
        return self._redo is not None

    def peek_undo(self) -> UndoEntry | None:
        return self._undo

    def peek_redo(self) -> UndoEntry | None:
        return self._redo

    # ---- mutations ----

    def record(self, entry: UndoEntry) -> None:
        """Record a fresh op. Clears redo (standard editor semantics)."""
        self._undo = entry
        self._redo = None

    def take_undo(self) -> UndoEntry | None:
        """Pop the undo entry. Caller is responsible for pushing the inverse via push_redo."""
        e = self._undo
        self._undo = None
        return e

    def take_redo(self) -> UndoEntry | None:
        """Pop the redo entry. Caller is responsible for pushing the inverse via push_undo."""
        e = self._redo
        self._redo = None
        return e

    def push_redo(self, entry: UndoEntry) -> None:
        """Set the redo entry (after a successful undo)."""
        self._redo = entry

    def push_undo(self, entry: UndoEntry) -> None:
        """Set the undo entry (after a successful redo)."""
        self._undo = entry

    def clear(self) -> None:
        self._undo = None
        self._redo = None
