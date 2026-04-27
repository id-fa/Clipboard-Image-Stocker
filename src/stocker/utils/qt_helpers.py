"""Conversion helpers between Pillow and Qt image types."""

from __future__ import annotations

from PIL import Image
from PySide6.QtGui import QImage, QPixmap


def pil_to_qpixmap(img: Image.Image) -> QPixmap:
    if img.mode == "RGBA":
        data = img.tobytes("raw", "RGBA")
        qimg = QImage(data, img.width, img.height, QImage.Format.Format_RGBA8888).copy()
    else:
        rgb = img.convert("RGB")
        data = rgb.tobytes("raw", "RGB")
        qimg = QImage(data, rgb.width, rgb.height, rgb.width * 3, QImage.Format.Format_RGB888).copy()
    return QPixmap.fromImage(qimg)


def qimage_to_pil(qimg: QImage) -> Image.Image:
    """Direct buffer conversion (no PNG round-trip)."""
    converted = qimg.convertToFormat(QImage.Format.Format_RGBA8888)
    width, height = converted.width(), converted.height()
    bits = converted.constBits()
    # Each scanline is 4 bytes per pixel; bytesPerLine may add padding.
    line_bytes = converted.bytesPerLine()
    if line_bytes == width * 4:
        buf = bytes(bits)
    else:
        rows = []
        for y in range(height):
            start = y * line_bytes
            rows.append(bytes(bits[start:start + width * 4]))
        buf = b"".join(rows)
    return Image.frombuffer("RGBA", (width, height), buf, "raw", "RGBA", 0, 1).copy()
