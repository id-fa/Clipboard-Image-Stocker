"""Toolbar with column slider, sort controls, paste format and other options."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QLabel,
    QSlider,
    QSpinBox,
    QToolBar,
    QWidget,
)


class StockerToolbar(QToolBar):
    columns_changed = Signal(int)
    sort_changed = Signal(str, str)
    set_workspace_requested = Signal()
    add_subfolder_requested = Signal()
    paste_format_changed = Signal(str)  # "png" | "jpeg"
    clipboard_autocapture_changed = Signal(bool)
    hover_preview_enabled_changed = Signal(bool)
    sidebar_font_size_changed = Signal(int)
    trash_days_changed = Signal(int)
    empty_trash_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__("Main", parent)
        self.setMovable(False)

        self.addAction("ワークスペース...", self.set_workspace_requested.emit)
        self.addAction("サブフォルダを追加", self.add_subfolder_requested.emit)
        self.addSeparator()

        self.addWidget(QLabel(" 列数: "))
        self._slider = QSlider(Qt.Orientation.Horizontal, self)
        self._slider.setRange(1, 16)
        self._slider.setValue(6)
        self._slider.setFixedWidth(140)
        self._slider.valueChanged.connect(self.columns_changed.emit)
        self.addWidget(self._slider)
        self._cols_label = QLabel("6", self)
        self.addWidget(self._cols_label)
        self._slider.valueChanged.connect(lambda v: self._cols_label.setText(str(v)))

        self.addSeparator()
        self.addWidget(QLabel(" 並び順: "))
        self._sort_key = QComboBox(self)
        self._sort_key.addItem("ファイル名", "name")
        self._sort_key.addItem("更新日時", "mtime")
        self._sort_key.addItem("追加日時", "added")
        self.addWidget(self._sort_key)

        self._sort_dir = QComboBox(self)
        self._sort_dir.addItem("昇順", "asc")
        self._sort_dir.addItem("降順", "desc")
        self.addWidget(self._sort_dir)
        self._sort_key.currentIndexChanged.connect(self._emit_sort)
        self._sort_dir.currentIndexChanged.connect(self._emit_sort)

        self.addSeparator()
        self.addWidget(QLabel(" 貼り付け形式: "))
        self._paste_fmt = QComboBox(self)
        self._paste_fmt.addItem("PNG", "png")
        self._paste_fmt.addItem("JPEG", "jpeg")
        self.addWidget(self._paste_fmt)
        self._paste_fmt.currentIndexChanged.connect(
            lambda _i: self.paste_format_changed.emit(self._paste_fmt.currentData())
        )

        self._auto_capture = QCheckBox("自動取込", self)
        self._auto_capture.setToolTip(
            "クリップボードに新しい画像が来たら自動的に現在のフォルダへ保存します"
        )
        self.addWidget(self._auto_capture)
        self._auto_capture.toggled.connect(self.clipboard_autocapture_changed.emit)

        self._hover_preview = QCheckBox("ホバー拡大", self)
        self._hover_preview.setToolTip(
            "サムネイル上で停止すると拡大プレビューを表示します"
        )
        self._hover_preview.setChecked(True)
        self.addWidget(self._hover_preview)
        self._hover_preview.toggled.connect(self.hover_preview_enabled_changed.emit)

        self.addSeparator()
        self.addWidget(QLabel(" ツリー字: "))
        self._font_spin = QSpinBox(self)
        self._font_spin.setRange(7, 28)
        self._font_spin.setValue(12)
        self._font_spin.setSuffix(" pt")
        self.addWidget(self._font_spin)
        self._font_spin.valueChanged.connect(self.sidebar_font_size_changed.emit)

        self.addSeparator()
        self.addWidget(QLabel(" ごみ箱保持: "))
        self._trash_days = QSpinBox(self)
        self._trash_days.setRange(0, 365)
        self._trash_days.setValue(0)
        self._trash_days.setSuffix(" 日 (0=無制限)")
        self.addWidget(self._trash_days)
        self._trash_days.valueChanged.connect(self.trash_days_changed.emit)
        self.addAction("ごみ箱を空にする", self.empty_trash_requested.emit)

    # ---- public ----

    def set_columns(self, n: int) -> None:
        self._slider.setValue(max(1, min(16, n)))

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

    def set_font_size(self, points: int) -> None:
        self._font_spin.setValue(points)

    def set_trash_days(self, days: int) -> None:
        self._trash_days.setValue(days)

    def _emit_sort(self) -> None:
        self.sort_changed.emit(self._sort_key.currentData(), self._sort_dir.currentData())
