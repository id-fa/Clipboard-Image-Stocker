"""Custom delegate that paints the thumbnail, label and PENDING badge."""

from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QLineEdit, QStyle, QStyledItemDelegate, QStyleOptionViewItem

from stocker.i18n import tr
from stocker.ui.theme import thumb_placeholder_color
from stocker.ui.thumbnail_model import PENDING_ROLE


LABEL_HEIGHT = 22
PADDING = 6


class ThumbnailDelegate(QStyledItemDelegate):
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        rect = option.rect.adjusted(PADDING, PADDING, -PADDING, -PADDING)
        thumb_rect = QRect(rect.x(), rect.y(), rect.width(), rect.height() - LABEL_HEIGHT)

        # Selection background
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())

        # Pixmap
        pm: QPixmap | None = index.data(int(Qt.ItemDataRole.DecorationRole))
        if pm is not None and not pm.isNull():
            scaled = pm.scaled(
                thumb_rect.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = thumb_rect.x() + (thumb_rect.width() - scaled.width()) // 2
            y = thumb_rect.y() + (thumb_rect.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)
        else:
            # Placeholder
            painter.fillRect(thumb_rect, thumb_placeholder_color())

        # PENDING badge
        if bool(index.data(PENDING_ROLE)):
            badge_rect = QRect(thumb_rect.right() - 70, thumb_rect.top() + 4, 66, 18)
            painter.fillRect(badge_rect, QColor(220, 140, 0, 220))
            painter.setPen(QPen(Qt.GlobalColor.white))
            painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, tr("delegate.saving"))

        # Selection border
        if option.state & QStyle.StateFlag.State_Selected:
            painter.setPen(QPen(option.palette.highlight().color().darker(140), 2))
            painter.drawRect(thumb_rect)

        # Label
        label_rect = QRect(rect.x(), thumb_rect.bottom() + 2, rect.width(), LABEL_HEIGHT - 2)
        painter.setPen(option.palette.text().color())
        text = index.data(int(Qt.ItemDataRole.DisplayRole)) or ""
        elided = painter.fontMetrics().elidedText(text, Qt.TextElideMode.ElideMiddle, label_rect.width())
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter, elided)

        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        s = index.data(int(Qt.ItemDataRole.SizeHintRole))
        return s if isinstance(s, QSize) else QSize(160, 192)

    def createEditor(self, parent, option, index):
        editor = QLineEdit(parent)
        editor.setFrame(True)
        return editor

    def setEditorData(self, editor: QLineEdit, index) -> None:
        editor.setText(index.data(int(Qt.ItemDataRole.EditRole)) or "")
        editor.selectAll()

    def updateEditorGeometry(self, editor: QLineEdit, option: QStyleOptionViewItem, index) -> None:
        rect = option.rect.adjusted(PADDING, option.rect.height() - LABEL_HEIGHT, -PADDING, -PADDING)
        editor.setGeometry(rect)
