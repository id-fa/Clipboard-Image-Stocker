"""Light / dark theme support.

Uses Qt's built-in Fusion style + a custom QPalette so we don't pull in any
additional dependencies. ``apply_theme()`` is idempotent and can be called
again at runtime when the user toggles the option from the toolbar; widgets
re-poll their palette on the resulting ``paletteChanged`` event.

Theme-dependent explicit colors (e.g. the sidebar drop highlight) are exposed
through ``drop_highlight_color()`` so the rest of the UI doesn't need to know
which theme is active.
"""

from __future__ import annotations

from typing import Literal

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

ThemeName = Literal["light", "dark"]

_active: ThemeName = "light"


def apply_theme(app: QApplication, name: str) -> None:
    """Switch the active theme. Unknown names fall back to ``"light"``."""
    global _active
    theme: ThemeName = "dark" if name == "dark" else "light"
    _active = theme
    app.setStyle("Fusion")
    app.setPalette(_dark_palette() if theme == "dark" else _light_palette())


def active_theme() -> ThemeName:
    return _active


def is_dark() -> bool:
    return _active == "dark"


def drop_highlight_color() -> QColor:
    """Sidebar drop-target highlight — orange tuned per theme."""
    return QColor(255, 170, 60, 200) if is_dark() else QColor(255, 165, 0, 180)


def thumb_placeholder_color() -> QColor:
    """Background fill for thumbnails that haven't loaded yet."""
    return QColor(60, 60, 60) if is_dark() else QColor(40, 40, 40)


def _light_palette() -> QPalette:
    """Reset to Fusion's default palette."""
    return QPalette()


def _dark_palette() -> QPalette:
    p = QPalette()
    base = QColor(45, 45, 45)
    alt_base = QColor(55, 55, 55)
    window = QColor(53, 53, 53)
    text = QColor(230, 230, 230)
    disabled_text = QColor(140, 140, 140)
    bright = QColor(255, 255, 255)
    highlight = QColor(38, 110, 180)
    tooltip_bg = QColor(70, 70, 70)

    p.setColor(QPalette.ColorRole.Window, window)
    p.setColor(QPalette.ColorRole.WindowText, text)
    p.setColor(QPalette.ColorRole.Base, base)
    p.setColor(QPalette.ColorRole.AlternateBase, alt_base)
    p.setColor(QPalette.ColorRole.ToolTipBase, tooltip_bg)
    p.setColor(QPalette.ColorRole.ToolTipText, text)
    p.setColor(QPalette.ColorRole.Text, text)
    p.setColor(QPalette.ColorRole.Button, window)
    p.setColor(QPalette.ColorRole.ButtonText, text)
    p.setColor(QPalette.ColorRole.BrightText, bright)
    p.setColor(QPalette.ColorRole.Link, QColor(80, 160, 230))
    p.setColor(QPalette.ColorRole.Highlight, highlight)
    p.setColor(QPalette.ColorRole.HighlightedText, bright)
    p.setColor(QPalette.ColorRole.PlaceholderText, disabled_text)

    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        p.setColor(QPalette.ColorGroup.Disabled, role, disabled_text)
    p.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.Highlight,
        QColor(80, 80, 80),
    )
    p.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.HighlightedText,
        disabled_text,
    )
    return p
