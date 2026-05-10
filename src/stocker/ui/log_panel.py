"""Bottom log row above the status bar.

Single-line by default showing the most recent entry. Clicking the row toggles
an expanded multi-line history with scrolling. The history is in-memory only
(cleared on app exit) — entries are never persisted.
"""

from __future__ import annotations

import time
from collections import deque

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from stocker.i18n import tr

MAX_HISTORY = 500
EXPANDED_HEIGHT = 160


class _ClickableLabel(QLabel):
    clicked = Signal()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, ev: QMouseEvent) -> None:
        if ev.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(ev)


class LogPanel(QWidget):
    """Compact one-line log strip with click-to-expand multi-line history."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._entries: deque[tuple[str, str]] = deque(maxlen=MAX_HISTORY)  # (timestamp, message)
        self._expanded = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Single-line row
        self._row = QFrame(self)
        self._row.setFrameShape(QFrame.Shape.StyledPanel)
        self._row.setFrameShadow(QFrame.Shadow.Sunken)
        row_layout = QHBoxLayout(self._row)
        row_layout.setContentsMargins(6, 2, 6, 2)
        row_layout.setSpacing(6)

        self._chevron = _ClickableLabel("▸", self._row)
        self._chevron.setFixedWidth(14)
        self._chevron.setToolTip(tr("log.expand_tooltip"))
        self._chevron.clicked.connect(self.toggle_expanded)
        row_layout.addWidget(self._chevron)

        self._line = _ClickableLabel(tr("log.empty"), self._row)
        self._line.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._line.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self._line.setToolTip(tr("log.expand_tooltip"))
        self._line.clicked.connect(self.toggle_expanded)
        row_layout.addWidget(self._line, 1)

        outer.addWidget(self._row)

        # Expanded history (initially hidden)
        self._history = QPlainTextEdit(self)
        self._history.setReadOnly(True)
        self._history.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._history.setFixedHeight(EXPANDED_HEIGHT)
        self._history.setVisible(False)
        outer.addWidget(self._history)

    # ---- public API ----

    def append(self, message: str) -> None:
        """Add a log entry. The latest line is shown in the collapsed strip."""
        if not message:
            return
        ts = time.strftime("%H:%M:%S")
        self._entries.append((ts, message))
        self._line.setText(f"[{ts}] {message}")
        # Append to history view if it has been built
        self._history.appendPlainText(f"[{ts}] {message}")
        # Keep history scrolled to the bottom (newest)
        sb = self._history.verticalScrollBar()
        sb.setValue(sb.maximum())

    def toggle_expanded(self) -> None:
        self.set_expanded(not self._expanded)

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = bool(expanded)
        self._chevron.setText("▾" if self._expanded else "▸")
        self._history.setVisible(self._expanded)
        if self._expanded:
            # Rebuild the history pane content from the deque each time so it
            # exactly mirrors the in-memory log (cheap with MAX_HISTORY=500).
            self._history.setPlainText(
                "\n".join(f"[{ts}] {msg}" for ts, msg in self._entries)
            )
            sb = self._history.verticalScrollBar()
            sb.setValue(sb.maximum())

    def clear(self) -> None:
        self._entries.clear()
        self._line.setText(tr("log.empty"))
        self._history.clear()
