"""Tests for ThumbnailCache: LRU, 500-item disk policy, disk read fallback."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

from stocker.app_paths import thumbs_dir
from stocker.core.models import ThumbKey
from stocker.core.thumbnail_cache import (
    DISK_CACHE_THRESHOLD,
    CachePolicy,
    ThumbnailCache,
    disk_thumb_path,
    policy_for,
)


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


def _pm(color: int = 0xFF) -> QPixmap:
    pm = QPixmap(8, 8)
    pm.fill()
    return pm


def test_policy_threshold():
    assert policy_for(0) is CachePolicy.MEMORY_ONLY
    assert policy_for(DISK_CACHE_THRESHOLD - 1) is CachePolicy.MEMORY_ONLY
    assert policy_for(DISK_CACHE_THRESHOLD) is CachePolicy.MEMORY_PLUS_DISK
    assert policy_for(DISK_CACHE_THRESHOLD + 100) is CachePolicy.MEMORY_PLUS_DISK


def test_lru_eviction(qapp, tmp_path: Path):
    cache = ThumbnailCache(capacity=3)
    cache.configure(tmp_path, file_count=10)
    keys = [ThumbKey(rel_path=f"f{i}.png", mtime_ns=i, target_size=64) for i in range(5)]
    for k in keys:
        cache.put(k, _pm(), write_to_disk=False)
    # Only the last 3 should remain
    assert cache.get(keys[0]) is None
    assert cache.get(keys[1]) is None
    assert cache.get(keys[2]) is not None
    assert cache.get(keys[3]) is not None
    assert cache.get(keys[4]) is not None


def test_disk_cache_writes_above_threshold(qapp, tmp_path: Path):
    cache = ThumbnailCache(capacity=10)
    cache.configure(tmp_path, file_count=DISK_CACHE_THRESHOLD)
    assert cache.policy is CachePolicy.MEMORY_PLUS_DISK
    key = ThumbKey(rel_path="日本語.png", mtime_ns=12345, target_size=128)
    cache.put(key, _pm(), write_to_disk=True)
    disk = disk_thumb_path(tmp_path, key.rel_path, 128)
    assert disk.exists()
    assert disk.stat().st_size > 0


def test_disk_cache_skipped_below_threshold(qapp, tmp_path: Path):
    cache = ThumbnailCache(capacity=10)
    cache.configure(tmp_path, file_count=10)
    assert cache.policy is CachePolicy.MEMORY_ONLY
    key = ThumbKey(rel_path="a.png", mtime_ns=1, target_size=64)
    cache.put(key, _pm(), write_to_disk=True)
    disk = disk_thumb_path(tmp_path, key.rel_path, 64)
    assert not disk.exists()


def test_disk_read_repopulates_memory(qapp, tmp_path: Path):
    """After memory clear, disk-cached thumbs should still load."""
    cache = ThumbnailCache(capacity=5)
    cache.configure(tmp_path, file_count=DISK_CACHE_THRESHOLD)
    key = ThumbKey(rel_path="x.png", mtime_ns=99, target_size=96)
    cache.put(key, _pm())
    cache.clear()
    # The disk file is still there, so get() should find and reload it.
    pm = cache.get(key)
    assert pm is not None
    assert not pm.isNull()


def test_thumbs_dir_layout(tmp_path: Path):
    p = thumbs_dir(tmp_path)
    assert p.parent.name == ".stocker"
    assert p.name == "thumbs"
