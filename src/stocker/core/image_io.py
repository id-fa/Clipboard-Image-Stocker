"""Pillow / Qt image I/O helpers."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from PIL import Image, ImageOps
from PySide6.QtGui import QImage

log = logging.getLogger(__name__)


def open_for_thumb(path: Path) -> Image.Image:
    """Open an image, apply EXIF rotation, return a Pillow Image."""
    img = Image.open(path)
    img.load()
    return ImageOps.exif_transpose(img) or img


def make_thumbnail(path: Path, target_size: int) -> Image.Image:
    img = open_for_thumb(path)
    img.thumbnail((target_size, target_size), Image.Resampling.LANCZOS)
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
    return img


def save_png_atomic(qimg: QImage, target: Path) -> None:
    """Save a QImage as PNG atomically (write to .tmp then os.replace)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    if not qimg.save(str(tmp), "PNG"):
        raise OSError(f"QImage.save failed: {target}")
    os.replace(tmp, target)


def save_image_atomic(qimg: QImage, target: Path, fmt: str, jpeg_quality: int = 92) -> None:
    """Save a QImage in the requested format. fmt is 'png' or 'jpeg'."""
    fmt = fmt.lower()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    if fmt == "jpeg":
        # JPEG doesn't have alpha; flatten transparent pasted images onto white.
        if qimg.hasAlphaChannel():
            from PySide6.QtGui import QPainter
            from PySide6.QtCore import Qt as _Qt
            opaque = QImage(qimg.size(), QImage.Format.Format_RGB888)
            opaque.fill(_Qt.GlobalColor.white)
            p = QPainter(opaque)
            p.drawImage(0, 0, qimg)
            p.end()
            qimg = opaque
        ok = qimg.save(str(tmp), "JPEG", jpeg_quality)
    else:
        ok = qimg.save(str(tmp), "PNG")
    if not ok:
        raise OSError(f"QImage.save failed for {fmt}: {target}")
    os.replace(tmp, target)


def save_webp_thumb(img: Image.Image, target: Path, quality: int = 80) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    img.save(tmp, "WEBP", quality=quality, method=4)
    os.replace(tmp, target)


def read_dimensions(path: Path) -> tuple[int, int] | None:
    try:
        with Image.open(path) as img:
            return img.size
    except Exception as e:  # noqa: BLE001
        log.debug("read_dimensions failed for %s: %s", path, e)
        return None
