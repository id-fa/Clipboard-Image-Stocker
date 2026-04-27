"""Memory LRU + optional WebP disk cache for thumbnails."""

from __future__ import annotations

import hashlib
import logging
from collections import OrderedDict
from enum import Enum
from pathlib import Path

from PySide6.QtGui import QPixmap

from stocker.app_paths import thumbs_dir
from stocker.core.models import ThumbKey

log = logging.getLogger(__name__)

DISK_CACHE_THRESHOLD = 500
DEFAULT_MEMORY_CAPACITY = 1024


class CachePolicy(Enum):
    MEMORY_ONLY = "memory"
    MEMORY_PLUS_DISK = "disk"


def policy_for(file_count: int) -> CachePolicy:
    return (
        CachePolicy.MEMORY_PLUS_DISK
        if file_count >= DISK_CACHE_THRESHOLD
        else CachePolicy.MEMORY_ONLY
    )


def thumb_hash(rel_path: str) -> str:
    return hashlib.sha1(rel_path.encode("utf-8")).hexdigest()


def disk_thumb_path(folder_root: Path, rel_path: str, target_size: int) -> Path:
    h = thumb_hash(rel_path)
    return thumbs_dir(folder_root) / f"{h}_{target_size}.webp"


class ThumbnailCache:
    """LRU pixmap cache. Disk-backed when policy=DISK."""

    def __init__(self, capacity: int = DEFAULT_MEMORY_CAPACITY):
        self._capacity = capacity
        self._mem: OrderedDict[ThumbKey, QPixmap] = OrderedDict()
        self._policy = CachePolicy.MEMORY_ONLY
        self._folder_root: Path | None = None

    def configure(self, folder_root: Path, file_count: int) -> None:
        self._folder_root = folder_root
        self._policy = policy_for(file_count)

    @property
    def policy(self) -> CachePolicy:
        return self._policy

    def update_policy(self, file_count: int) -> None:
        self._policy = policy_for(file_count)

    def clear(self) -> None:
        self._mem.clear()

    def get(self, key: ThumbKey) -> QPixmap | None:
        pm = self._mem.get(key)
        if pm is not None:
            self._mem.move_to_end(key)
            return pm
        if self._policy is CachePolicy.MEMORY_PLUS_DISK and self._folder_root is not None:
            disk = disk_thumb_path(self._folder_root, key.rel_path, key.target_size)
            if disk.exists():
                loaded = QPixmap(str(disk))
                if not loaded.isNull():
                    self.put(key, loaded, write_to_disk=False)
                    return loaded
        return None

    def put(self, key: ThumbKey, pm: QPixmap, write_to_disk: bool = True) -> None:
        if key in self._mem:
            self._mem.move_to_end(key)
            self._mem[key] = pm
        else:
            self._mem[key] = pm
            while len(self._mem) > self._capacity:
                self._mem.popitem(last=False)
        if (
            write_to_disk
            and self._policy is CachePolicy.MEMORY_PLUS_DISK
            and self._folder_root is not None
        ):
            try:
                from stocker.core.image_io import save_webp_thumb
                from stocker.utils.qt_helpers import qimage_to_pil

                disk = disk_thumb_path(self._folder_root, key.rel_path, key.target_size)
                save_webp_thumb(qimage_to_pil(pm.toImage()), disk)
            except Exception as e:  # noqa: BLE001
                log.warning("disk cache write failed for %s: %s", key.rel_path, e)

    # ------- relocation helpers (used by MoveService) -------

    def relocate_memory_keys(self, src_to_dst: dict[ThumbKey, ThumbKey]) -> None:
        """Re-key memory entries when files move between folders."""
        for src, dst in src_to_dst.items():
            pm = self._mem.pop(src, None)
            if pm is not None:
                self._mem[dst] = pm
