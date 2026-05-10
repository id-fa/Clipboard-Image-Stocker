"""Tests for the single-generation Undo/Redo container."""

from __future__ import annotations

from pathlib import Path

from stocker.core.undo_manager import UndoEntry, UndoKind, UndoManager


def _move_entry() -> UndoEntry:
    return UndoEntry(
        kind=UndoKind.MOVE,
        src_label="A", dst_label="B",
        src_root=Path("/A"), dst_root=Path("/B"),
        pairs=[("a.png", "a.png")],
    )


def _copy_entry() -> UndoEntry:
    return UndoEntry(
        kind=UndoKind.COPY,
        src_label="A", dst_label="B",
        src_root=Path("/A"), dst_root=Path("/B"),
        pairs=[("a.png", "a.png"), ("b.png", "b.png")],
    )


def _trash_entry() -> UndoEntry:
    return UndoEntry(
        kind=UndoKind.TRASH,
        src_label="A", dst_label="Trash",
        workspace=Path("/ws"),
        trashed_basenames=["a_123.png", "b_124.png"],
    )


def test_initial_state_empty():
    m = UndoManager()
    assert not m.can_undo()
    assert not m.can_redo()
    assert m.peek_undo() is None
    assert m.peek_redo() is None


def test_record_sets_undo_and_clears_redo():
    m = UndoManager()
    first = _move_entry()
    m.record(first)
    assert m.can_undo()
    assert not m.can_redo()
    assert m.peek_undo() is first


def test_undo_redo_roundtrip():
    m = UndoManager()
    e = _move_entry()
    m.record(e)

    # User hits Ctrl+Z — caller pops undo, pushes inverse to redo.
    taken = m.take_undo()
    assert taken is e
    assert not m.can_undo()
    inverse = _move_entry()  # in practice this would be the "redo" form
    m.push_redo(inverse)
    assert m.can_redo()

    # User hits Ctrl+Y — caller pops redo, pushes inverse to undo.
    taken2 = m.take_redo()
    assert taken2 is inverse
    assert not m.can_redo()
    forward = _move_entry()
    m.push_undo(forward)
    assert m.can_undo()


def test_new_record_clears_redo():
    m = UndoManager()
    m.record(_move_entry())
    m.take_undo()
    m.push_redo(_move_entry())
    assert m.can_redo()
    # A fresh op must reset redo (standard editor semantics).
    m.record(_copy_entry())
    assert m.can_undo()
    assert not m.can_redo()


def test_single_generation_only():
    """Recording a new op replaces (does not stack) any existing undo."""
    m = UndoManager()
    first = _move_entry()
    second = _copy_entry()
    m.record(first)
    m.record(second)
    assert m.peek_undo() is second
    # After popping, the stack is empty (no first-op left behind).
    m.take_undo()
    assert not m.can_undo()


def test_clear_resets_both_sides():
    m = UndoManager()
    m.record(_move_entry())
    m.take_undo()
    m.push_redo(_trash_entry())
    m.clear()
    assert not m.can_undo()
    assert not m.can_redo()


def test_count_uses_correct_field_per_kind():
    move = _move_entry()
    assert move.count == 1
    copy = _copy_entry()
    assert copy.count == 2
    trash = _trash_entry()
    assert trash.count == 2
    # Trash on the redo side: only trash_sources populated.
    trash_redo = UndoEntry(
        kind=UndoKind.TRASH,
        workspace=Path("/ws"),
        trash_sources=[(Path("/ws/A/a.png"), Path("/ws/A"))],
    )
    assert trash_redo.count == 1
