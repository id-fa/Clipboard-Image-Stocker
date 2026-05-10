"""Toolbar with column slider, sort controls, paste format and other options."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QLabel,
    QLineEdit,
    QSlider,
    QSpinBox,
    QToolBar,
    QWidget,
)

from stocker.i18n import tr


class StockerToolbar(QToolBar):
    columns_changed = Signal(int)
    aspect_changed = Signal(str)
    filter_text_changed = Signal(str)
    sort_changed = Signal(str, str)
    set_workspace_requested = Signal()
    add_subfolder_requested = Signal()
    paste_format_changed = Signal(str)  # "png" | "jpeg"
    clipboard_autocapture_changed = Signal(bool)
    hover_preview_enabled_changed = Signal(bool)
    hover_preview_animate_changed = Signal(bool)
    minimize_to_tray_changed = Signal(bool)
    dark_theme_changed = Signal(bool)
    log_panel_enabled_changed = Signal(bool)
    sidebar_font_size_changed = Signal(int)
    trash_days_changed = Signal(int)
    empty_trash_requested = Signal()
    about_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__("Main", parent)
        self.setMovable(False)

        self.addAction(tr("toolbar.workspace"), self.set_workspace_requested.emit)
        self.addAction(tr("toolbar.add_subfolder"), self.add_subfolder_requested.emit)
        self.addSeparator()

        self.addWidget(QLabel(tr("toolbar.columns_label")))
        self._slider = QSlider(Qt.Orientation.Horizontal, self)
        self._slider.setRange(1, 16)
        self._slider.setValue(6)
        self._slider.setFixedWidth(140)
        self._slider.valueChanged.connect(self.columns_changed.emit)
        self.addWidget(self._slider)
        self._cols_label = QLabel("6", self)
        self.addWidget(self._cols_label)
        self._slider.valueChanged.connect(lambda v: self._cols_label.setText(str(v)))

        self.addWidget(QLabel(tr("toolbar.aspect_label")))
        self._aspect = QComboBox(self)
        self._aspect.setToolTip(tr("toolbar.aspect_tooltip"))
        for r in ("1:1", "4:3", "16:9", "3:4", "9:16"):
            self._aspect.addItem(r, r)
        self.addWidget(self._aspect)
        self._aspect.currentIndexChanged.connect(
            lambda _i: self.aspect_changed.emit(self._aspect.currentData())
        )

        self.addSeparator()
        self.addWidget(QLabel(tr("toolbar.sort_label")))
        self._sort_key = QComboBox(self)
        self._sort_key.addItem(tr("toolbar.sort_name"), "name")
        self._sort_key.addItem(tr("toolbar.sort_mtime"), "mtime")
        self._sort_key.addItem(tr("toolbar.sort_added"), "added")
        self.addWidget(self._sort_key)

        self._sort_dir = QComboBox(self)
        self._sort_dir.addItem(tr("toolbar.sort_asc"), "asc")
        self._sort_dir.addItem(tr("toolbar.sort_desc"), "desc")
        self.addWidget(self._sort_dir)
        self._sort_key.currentIndexChanged.connect(self._emit_sort)
        self._sort_dir.currentIndexChanged.connect(self._emit_sort)

        self.addSeparator()
        self.addWidget(QLabel(tr("toolbar.filter_label")))
        self._filter = QLineEdit(self)
        self._filter.setPlaceholderText(tr("toolbar.filter_placeholder"))
        self._filter.setToolTip(tr("toolbar.filter_tooltip"))
        self._filter.setClearButtonEnabled(True)
        self._filter.setFixedWidth(180)
        self.addWidget(self._filter)
        self._filter.textChanged.connect(self.filter_text_changed)

        self.addSeparator()
        self.addWidget(QLabel(tr("toolbar.paste_format_label")))
        self._paste_fmt = QComboBox(self)
        self._paste_fmt.addItem("PNG", "png")
        self._paste_fmt.addItem("JPEG", "jpeg")
        self.addWidget(self._paste_fmt)
        self._paste_fmt.currentIndexChanged.connect(
            lambda _i: self.paste_format_changed.emit(self._paste_fmt.currentData())
        )

        self._auto_capture = QCheckBox(tr("toolbar.autocapture"), self)
        self._auto_capture.setToolTip(tr("toolbar.autocapture_tooltip"))
        self.addWidget(self._auto_capture)
        self._auto_capture.toggled.connect(self.clipboard_autocapture_changed.emit)

        self._hover_preview = QCheckBox(tr("toolbar.hover_preview"), self)
        self._hover_preview.setToolTip(tr("toolbar.hover_preview_tooltip"))
        self._hover_preview.setChecked(True)
        self.addWidget(self._hover_preview)
        self._hover_preview.toggled.connect(self.hover_preview_enabled_changed.emit)

        self._hover_animate = QCheckBox(tr("toolbar.hover_animate"), self)
        self._hover_animate.setToolTip(tr("toolbar.hover_animate_tooltip"))
        self._hover_animate.setChecked(True)
        self.addWidget(self._hover_animate)
        self._hover_animate.toggled.connect(self.hover_preview_animate_changed.emit)

        self._minimize_to_tray = QCheckBox(tr("toolbar.minimize_to_tray"), self)
        self._minimize_to_tray.setToolTip(tr("toolbar.minimize_to_tray_tooltip"))
        self.addWidget(self._minimize_to_tray)
        self._minimize_to_tray.toggled.connect(self.minimize_to_tray_changed.emit)

        self._dark_theme = QCheckBox(tr("toolbar.dark_theme"), self)
        self._dark_theme.setToolTip(tr("toolbar.dark_theme_tooltip"))
        self.addWidget(self._dark_theme)
        self._dark_theme.toggled.connect(self.dark_theme_changed.emit)

        self._log_panel = QCheckBox(tr("toolbar.log_panel"), self)
        self._log_panel.setToolTip(tr("toolbar.log_panel_tooltip"))
        self._log_panel.setChecked(True)
        self.addWidget(self._log_panel)
        self._log_panel.toggled.connect(self.log_panel_enabled_changed.emit)

        self.addSeparator()
        self.addWidget(QLabel(tr("toolbar.tree_font_label")))
        self._font_spin = QSpinBox(self)
        self._font_spin.setRange(7, 28)
        self._font_spin.setValue(12)
        self._font_spin.setSuffix(" pt")
        self.addWidget(self._font_spin)
        self._font_spin.valueChanged.connect(self.sidebar_font_size_changed.emit)

        self.addSeparator()
        self.addWidget(QLabel(tr("toolbar.trash_keep_label")))
        self._trash_days = QSpinBox(self)
        self._trash_days.setRange(0, 365)
        self._trash_days.setValue(0)
        self._trash_days.setSuffix(tr("toolbar.days_suffix"))
        self.addWidget(self._trash_days)
        self._trash_days.valueChanged.connect(self.trash_days_changed.emit)
        self.addAction(tr("toolbar.empty_trash"), self.empty_trash_requested.emit)

        self.addSeparator()
        self.addAction(tr("toolbar.about"), self.about_requested.emit)

    # ---- public ----

    def set_columns(self, n: int) -> None:
        self._slider.setValue(max(1, min(16, n)))

    def set_aspect(self, ratio: str) -> None:
        idx = self._aspect.findData(ratio)
        if idx >= 0:
            self._aspect.setCurrentIndex(idx)

    def filter_text(self) -> str:
        return self._filter.text()

    def set_filter_text(self, text: str) -> None:
        if self._filter.text() != text:
            self._filter.setText(text)

    def focus_filter(self) -> None:
        self._filter.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self._filter.selectAll()

    def set_sort(self, key: str, direction: str) -> None:
        idx = self._sort_key.findData(key)
        if idx >= 0:
            self._sort_key.setCurrentIndex(idx)
        idx = self._sort_dir.findData(direction)
        if idx >= 0:
            self._sort_dir.setCurrentIndex(idx)

    def set_paste_format(self, fmt: str) -> None:
        idx = self._paste_fmt.findData(fmt)
        if idx >= 0:
            self._paste_fmt.setCurrentIndex(idx)

    def set_autocapture(self, enabled: bool) -> None:
        self._auto_capture.setChecked(bool(enabled))

    def set_hover_preview_enabled(self, enabled: bool) -> None:
        self._hover_preview.setChecked(bool(enabled))

    def set_hover_preview_animate(self, enabled: bool) -> None:
        self._hover_animate.setChecked(bool(enabled))

    def set_minimize_to_tray(self, enabled: bool) -> None:
        self._minimize_to_tray.setChecked(bool(enabled))

    def set_dark_theme(self, enabled: bool) -> None:
        self._dark_theme.setChecked(bool(enabled))

    def set_log_panel_enabled(self, enabled: bool) -> None:
        self._log_panel.setChecked(bool(enabled))

    def set_minimize_to_tray_available(self, available: bool) -> None:
        """Disable the toggle (with explanatory tooltip) when no tray is present."""
        self._minimize_to_tray.setEnabled(bool(available))
        if not available:
            self._minimize_to_tray.setToolTip(tr("toolbar.tray_unavailable_tooltip"))

    def set_font_size(self, points: int) -> None:
        self._font_spin.setValue(points)

    def set_trash_days(self, days: int) -> None:
        self._trash_days.setValue(days)

    def _emit_sort(self) -> None:
        self.sort_changed.emit(self._sort_key.currentData(), self._sort_dir.currentData())
